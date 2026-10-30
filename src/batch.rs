//! Incremental analysis of the exact file identities already present in bliss.db.
//! No write access to Bliss and no implicit deletion/pruning of old Mood rows.
use anyhow::{bail, Context, Result};
use serde::Serialize;
use std::{path::{Path, PathBuf}, time::{Instant, UNIX_EPOCH}};

use crate::{engine::{ModelProfile, MoodEngine}, storage};

#[derive(Debug, Serialize)]
pub struct ScanSummary {
    pub bliss_tracks: usize,
    pub checked: usize,
    pub up_to_date: usize,
    pub pending: usize,
    pub analyzed: usize,
    pub missing_files: usize,
    pub failures: usize,
    pub limit_reached: bool,
    pub elapsed_seconds: f64,
    pub model_sessions_initialized: bool,
    pub experimental_results: bool,
}

#[derive(Debug)]
pub struct ScanOptions<'a> {
    pub bliss_db: &'a Path,
    pub mood_db: &'a Path,
    pub models_dir: &'a Path,
    pub source_root: Option<&'a Path>,
    pub library_root: Option<&'a str>,
    pub max_new: Option<usize>,
    pub threads: usize,
    pub dry_run: bool,
    /// If set, process exactly one matching TracksV2.File key.
    pub only_track: Option<&'a str>,
}

/// Resolve an exact Bliss TracksV2.File identity against the analysis machine.
///
/// In many LMS configurations TracksV2.File is already relative to the music
/// directory. In that case only --source-root is needed, e.g.
/// "\\192.168.1.100\music" for Windows and "/mnt/music" on Linux.
/// Never let a relative key escape the declared source root.
pub(crate) fn source_path(
    track_key: &str,
    library_root: Option<&str>,
    source_root: Option<&Path>,
) -> Result<PathBuf> {
    match (library_root, source_root) {
        (None, None) => Ok(PathBuf::from(track_key)),
        (None, Some(root)) => safe_join(root, track_key),
        (Some(prefix), Some(root)) => {
            let prefix = prefix.trim_end_matches(&['/', '\\'][..]);
            if prefix.is_empty() {
                bail!("--library-root must not be empty");
            }
            let relative = track_key.strip_prefix(prefix)
                .context("Track path does not begin with the configured library root")?
                .strip_prefix(&['/', '\\'][..])
                .context("Library prefix must be followed by a path separator")?;
            safe_join(root, relative)
        }
        (Some(_), None) => bail!("--library-root requires --source-root"),
    }
}

fn safe_join(root: &Path, relative: &str) -> Result<PathBuf> {
    if root.as_os_str().is_empty() || relative.is_empty() {
        bail!("Source root and relative Bliss path must be non-empty");
    }
    let mut result = root.to_path_buf();
    // Split both separators explicitly: Bliss stores portable forward slashes,
    // while Windows UNC roots use backslashes.
    for part in relative.split(&['/', '\\'][..]) {
        if part.is_empty() || part == "." || part == ".." || part.contains(':') {
            bail!("Unsafe/ambiguous component in Bliss track path: {relative}");
        }
        result.push(part);
    }
    Ok(result)
}

pub(crate) fn file_stat(file: &Path) -> Result<(i64, i64)> {
    let meta = std::fs::metadata(file)
        .with_context(|| format!("Unable to stat {}", file.display()))?;
    if !meta.is_file() {
        bail!("Not a regular music file: {}", file.display());
    }
    let size = i64::try_from(meta.len()).context("File length overflows SQLite integer")?;
    let since_epoch = meta.modified()?.duration_since(UNIX_EPOCH)
        .context("File has modification time before Unix epoch")?;
    let modified_ns = i64::try_from(since_epoch.as_nanos())
        .context("Modification time outside SQLite integer range")?;
    Ok((size, modified_ns))
}

pub fn scan(options: ScanOptions<'_>) -> Result<ScanSummary> {
    let started = Instant::now();
    if options.threads == 0 || options.max_new == Some(0) {
        bail!("--threads and --max-new must be >= 1");
    }
    if options.library_root.is_some() && options.source_root.is_none() {
        bail!("--library-root requires --source-root");
    }
    // The source library is opened read-only and sorted by its canonical File key.
    let mut tracks = storage::bliss_files(options.bliss_db)?;
    if let Some(exact) = options.only_track {
        tracks.retain(|key| key == exact);
        if tracks.is_empty() {
            bail!("--only-track was not found as an exact TracksV2.File key: {exact}");
        }
    }
    let mut profile = Some(ModelProfile::load(options.models_dir)?);
    let model_key = profile.as_ref().expect("profile").model_key.clone();
    let mut conn = if options.dry_run {
        storage::open_readonly_scan_db(options.mood_db)?
    } else {
        Some(storage::open_scan_db(options.mood_db)?)
    };
    let mut engine: Option<MoodEngine> = None;
    let mut summary = ScanSummary {
        bliss_tracks: tracks.len(),
        checked: 0, up_to_date: 0, pending: 0, analyzed: 0,
        missing_files: 0, failures: 0, limit_reached: false,
        elapsed_seconds: 0.0,
        model_sessions_initialized: false,
        experimental_results: true,
    };
    for track in tracks {
        summary.checked += 1;
        let source = match source_path(
            &track, options.library_root, options.source_root
        ) {
            Ok(path) => path,
            Err(e) => {
                summary.failures += 1;
                eprintln!("MAPPING ERROR {track}: {e:#}");
                continue;
            }
        };
        let (size, modified) = match file_stat(&source) {
            Ok(meta) => meta,
            Err(e) => {
                summary.missing_files += 1;
                eprintln!("SOURCE UNAVAILABLE {}: {e:#}", source.display());
                continue;
            }
        };
        if conn.as_ref()
            .map(|db| storage::is_current(db, &track, size, modified, &model_key))
            .transpose()?
            .unwrap_or(false)
        {
            summary.up_to_date += 1;
            continue;
        }
        summary.pending += 1;
        if options.dry_run {
            continue;
        }
        if options.max_new.is_some_and(|max| summary.analyzed >= max) {
            summary.limit_reached = true;
            break;
        }
        if engine.is_none() {
            engine = Some(MoodEngine::new(profile.take().expect("profile only loaded once"), options.threads)?);
            summary.model_sessions_initialized = true;
        }
        let result = engine.as_mut().expect("model initialized").analyze(&source, None);
        match result.and_then(|report| {
            // New scores are committed only after all model stages succeed.
            storage::persist_scanned(conn.as_mut().expect("writable db in non-dry-run"), &track, &report, size, modified)
        }) {
            Ok(()) => {
                summary.analyzed += 1;
                eprintln!("ANALYZED {} ({}/{})", track, summary.analyzed, summary.pending);
            }
            Err(error) => {
                summary.failures += 1;
                eprintln!("ANALYSIS FAILED {track}: {error:#}");
            }
        }
    }
    summary.elapsed_seconds = started.elapsed().as_secs_f64();
    Ok(summary)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn supports_native_identity_and_mapped_roots() {
        assert_eq!(source_path("/mnt/music/a.flac", None, None).unwrap(),
                   PathBuf::from("/mnt/music/a.flac"));
        assert_eq!(
            source_path("/mnt/music/Rock/a.flac", Some("/mnt/music"), Some(Path::new("D:/Music"))).unwrap(),
            PathBuf::from("D:/Music").join("Rock").join("a.flac")
        );
        assert!(source_path("/mnt/musical/a.flac", Some("/mnt/music"), Some(Path::new("D:/Music"))).is_err());
        assert!(source_path("/mnt/music/../secret", Some("/mnt/music"), Some(Path::new("D:/Music"))).is_err());
        assert!(source_path("/mnt/music/song", Some("/mnt/music"), None).is_err());
        assert_eq!(
            source_path("Acid Mammoth/2024 - Supersonic Megafuana Collision/04 Atomic Shaman.mp3",
                None, Some(Path::new(r"\\192.168.1.100\music"))).unwrap(),
            PathBuf::from(r"\\192.168.1.100\music")
                .join("Acid Mammoth")
                .join("2024 - Supersonic Megafuana Collision")
                .join("04 Atomic Shaman.mp3")
        );
        assert!(source_path("../outside.flac", None, Some(Path::new("/mnt/music"))).is_err());
        assert!(source_path("/root/escape.flac", None, Some(Path::new("/mnt/music"))).is_err());
        assert!(source_path(r"C:\escape.flac", None, Some(Path::new("/mnt/music"))).is_err());
    }
}
