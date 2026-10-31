//! Conservative per-file source-stability guard for scanner persistence.
//! This compares the SHA-256 of original bytes BEFORE decoding to the
//! SHA-256 already recorded by the analyser AFTER decoding, and requires
//! stable file identity/stat on both sides. No additional post-hash pass.
//! It is NOT an atomic filesystem snapshot or a host scan-generation token.
use anyhow::{bail, Context, Result};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, Metadata},
    io::Read,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

#[derive(Debug, Clone, PartialEq, Eq)]
struct FileStamp {
    len: u64,
    modified: SystemTime,
    #[cfg(unix)]
    dev: u64,
    #[cfg(unix)]
    ino: u64,
}

impl FileStamp {
    fn read(meta: &Metadata) -> Result<Self> {
        if !meta.is_file() { bail!("Source is not a regular audio file"); }
        #[cfg(unix)]
        use std::os::unix::fs::MetadataExt;
        Ok(Self {
            len: meta.len(),
            modified: meta.modified().context("Source modification timestamp unavailable")?,
            #[cfg(unix)]
            dev: meta.dev(),
            #[cfg(unix)]
            ino: meta.ino(),
        })
    }

    fn verify_scan_stat(&self, expected: Option<(i64, i64)>) -> Result<()> {
        if let Some((size, ns)) = expected {
            let modified_ns = self.modified.duration_since(UNIX_EPOCH)
                .context("Source timestamp precedes Unix epoch")?.as_nanos();
            if i64::try_from(self.len).ok() != Some(size)
                || i64::try_from(modified_ns).ok() != Some(ns)
            {
                bail!("Source changed after scan task was admitted");
            }
        }
        Ok(())
    }
}

/// Evidence is local to a single in-flight analysis, never persisted as
/// a cross-database generation or a permanent attestation token.
pub(crate) struct SourceEvidence {
    path: PathBuf,
    canonical: PathBuf,
    stamp: FileStamp,
    before_sha256: String,
}

impl SourceEvidence {
    pub(crate) fn begin(path: &Path, expected: Option<(i64, i64)>) -> Result<Self> {
        let mut file = File::open(path)
            .with_context(|| format!("Cannot open original audio source {}", path.display()))?;
        let before = FileStamp::read(&file.metadata()?)?;
        before.verify_scan_stat(expected)?;
        let canonical = fs::canonicalize(path)
            .context("Cannot resolve audio path before decode")?;
        let mut hasher = Sha256::new();
        let mut buf = [0u8; 64 * 1024];
        loop {
            let n = file.read(&mut buf).context("Cannot hash original audio before decode")?;
            if n == 0 { break; }
            hasher.update(&buf[..n]);
        }
        // This also protects the pre-read itself against ordinary edits or
        // path replacement while the initial hash is being calculated.
        if FileStamp::read(&file.metadata()?)? != before
            || FileStamp::read(&fs::metadata(path)?)? != before
            || fs::canonicalize(path)? != canonical
        {
            bail!("Audio source changed while hashing before decode");
        }
        Ok(Self {
            path: path.to_owned(), canonical, stamp: before,
            before_sha256: format!("{:x}", hasher.finalize()),
        })
    }

    /// Validate the analyser's already-computed post-decode source hash.
    pub(crate) fn finish(&self, post_decode_sha256: &str) -> Result<()> {
        if post_decode_sha256 != self.before_sha256 {
            bail!("Original audio bytes differ before and after decode");
        }
        self.verify_still_current(None)
    }

    /// The SQLite writer rechecks stat after the worker result is received.
    /// This does not promise atomicity after this final check.
    pub(crate) fn verify_still_current(
        &self, expected: Option<(i64, i64)>,
    ) -> Result<()> {
        let current = FileStamp::read(&fs::metadata(&self.path)?)?;
        if current != self.stamp
            || fs::canonicalize(&self.path)? != self.canonical
        {
            bail!("Audio source changed between analysis and storage");
        }
        current.verify_scan_stat(expected)
    }
}

pub(crate) fn analyse_checked<T, F, H>(
    path: &Path, expected: Option<(i64, i64)>, analyse: F, recorded_hash: H,
) -> Result<(T, SourceEvidence)>
where
    F: FnOnce() -> Result<T>,
    H: FnOnce(&T) -> &str,
{
    let proof = SourceEvidence::begin(path, expected)?;
    let result = analyse()?;
    proof.finish(recorded_hash(&result))?;
    Ok((result, proof))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture(name: &str) -> PathBuf {
        let tag = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        std::env::temp_dir().join(format!(
            "essentia-audio-stability-{name}-{}-{tag}", std::process::id()))
    }

    fn file_state(path: &Path) -> (i64, i64) {
        let meta = fs::metadata(path).unwrap();
        (meta.len() as i64, meta.modified().unwrap()
            .duration_since(UNIX_EPOCH).unwrap().as_nanos() as i64)
    }

    #[test]
    fn stable_audio_bytes_accept_normal_analysis_and_writer_check() {
        let path = fixture("stable");
        fs::write(&path, b"a synthetic audio source").unwrap();
        let stat = file_state(&path);
        let (value, proof) = analyse_checked(&path, Some(stat),
            || Ok(17usize), |_| "3a");
        assert!(value.is_err() || proof.is_err());
        let expected_sha = format!("{:x}", Sha256::digest(fs::read(&path).unwrap()));
        let (value, proof) = analyse_checked(&path, Some(stat),
            || Ok(17usize), |_| expected_sha.as_str()).unwrap();
        assert_eq!(value, 17);
        proof.verify_still_current(Some(stat)).unwrap();
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn rejects_changed_bytes_even_with_same_length_and_restored_mtime() {
        let path = fixture("mutated");
        fs::write(&path, b"ABCD").unwrap();
        let stat = file_state(&path);
        let after = format!("{:x}", Sha256::digest(b"WXYZ"));
        let outcome = analyse_checked(&path, Some(stat), || {
            fs::write(&path, b"WXYZ")?;
            Ok(())
        }, |_| after.as_str());
        assert!(outcome.is_err());
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn refuses_admission_when_scan_queue_stat_is_stale() {
        let path = fixture("queue");
        fs::write(&path, b"ABCD").unwrap();
        let (size, ns) = file_state(&path);
        let entered = std::cell::Cell::new(false);
        let result = analyse_checked(&path, Some((size, ns + 1)),
            || { entered.set(true); Ok(()) }, |_| "irrelevant");
        assert!(result.is_err());
        assert!(!entered.get(), "no decoder invoked on stale task");
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn writer_detects_changes_after_worker_completed() {
        let path = fixture("writer");
        fs::write(&path, b"ABCD").unwrap();
        let expected = format!("{:x}", Sha256::digest(b"ABCD"));
        let state = file_state(&path);
        let (_, proof) = analyse_checked(&path, Some(state),
            || Ok(()), |_| expected.as_str()).unwrap();
        fs::write(&path, b"MORE").unwrap();
        assert!(proof.verify_still_current(Some(state)).is_err());
        fs::remove_file(path).unwrap();
    }
}
