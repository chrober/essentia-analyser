//! Read-only, opt-in IPC for a long-lived *native Essentia C++* DSP child.
//! The child owns all Essentia state. Rust keeps ONNX, scheduling and SQLite.
use anyhow::{bail, Context, Result};
use std::{
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::mpsc,
    time::Duration,
};
use crate::{preprocess, sha256_file};

const MAX_PATH_BYTES: usize = 16_384;
const MAX_PATCHES: usize = 2_048; // about 96 MiB in Float32 payload
const MAX_ERROR_BYTES: usize = 4_096;
const VALUES_PER_PATCH: usize = preprocess::PATCH_FRAMES * preprocess::MEL_BANDS;
pub const CPP_PREPROCESSING: &str = "experimental-essentia-cpp-dsp-v1-unvalidated";

#[derive(Clone, Debug)]
pub enum BackendChoice {
    Rust,
    Essentia {
        executable: PathBuf,
        worker_sha256: String,
        deployment_sha256: Option<String>,
        timeout_seconds: u64,
    },
}


/// Prevent Windows DLL changes from silently reusing an older feature cache.
/// The mandatory generated manifest lists EVERY explicitly bundled native
/// dependency and its checksum, not just the worker executable.
#[cfg(windows)]
fn verify_windows_deployment(exe: &Path) -> Result<String> {
    use serde::Deserialize;
    use std::collections::BTreeMap;

    #[derive(Deserialize)]
    struct BundleFile {
        sha256: String,
        size_bytes: u64,
    }
    #[derive(Deserialize)]
    struct Bundle {
        schema_version: u32,
        platform: String,
        worker_executable: String,
        files: BTreeMap<String, BundleFile>,
    }
    let dir = exe.parent().context("Worker directory missing")?;
    let file = dir.join("worker-dependencies.json");
    if !file.is_file() {
        bail!("Native Essentia C++ Windows backend requires a complete worker-dependencies.json beside the EXE; run scripts/package_essentia_worker_windows.py");
    }
    let content = fs::read(&file)
        .with_context(|| format!("Cannot read native deployment manifest {}", file.display()))?;
    if content.len() > 512 * 1024 { bail!("Native manifest exceeds size limit"); }
    let bundle: Bundle = serde_json::from_slice(&content)
        .context("Invalid native Essentia Windows deployment manifest")?;
    if bundle.schema_version != 1 || bundle.platform != "windows-x86_64-mingw64" {
        bail!("Unsupported Essentia Windows native bundle identity");
    }
    let actual_exe = exe.file_name().and_then(|x| x.to_str())
        .context("Worker filename must be UTF-8")?.to_ascii_lowercase();
    if bundle.worker_executable != actual_exe ||
        bundle.files.len() > 256 || !bundle.files.contains_key(&actual_exe)
    {
        bail!("Worker EXE is not correctly identified in the native bundle");
    }
    for (name, entry) in &bundle.files {
        if name.is_empty() || name.contains('/') || name.contains('\\') ||
            name.contains("..") || name != &name.to_ascii_lowercase() ||
            !(name.ends_with(".dll") || name.ends_with(".exe"))
        {
            bail!("Invalid DLL/EXE name in native bundle manifest");
        }
        let path = dir.join(name);
        if !path.is_file() || fs::canonicalize(&path)?.parent() != Some(dir) {
            bail!("Native library missing or outside checked bundle: {name}");
        }
        let on_disk = fs::metadata(&path)?.len();
        if on_disk != entry.size_bytes ||
            !sha256_file(&path)?.eq_ignore_ascii_case(&entry.sha256)
        {
            bail!("Native dependency changed since packaging: {name}");
        }
    }
    // Cache provenance includes the manifest's SHA256 as a *separate* hash,
    // preserving the existing independently hashed native executable entry.
    sha256_file(&file)
}

impl BackendChoice {
    pub fn from_cli(name: &str, worker_path: Option<&Path>, timeout_seconds: u64) -> Result<Self> {
        if timeout_seconds == 0 || timeout_seconds > 7200 {
            bail!("--essentia-timeout-seconds must be within 1..=7200");
        }
        match (name, worker_path) {
            ("rust", None) => Ok(Self::Rust),
            ("essentia", Some(path)) => {
                if !path.is_file() {
                    bail!("Essentia worker executable not found: {}", path.display());
                }
                // This fingerprint prevents cache aliasing across different native workers.
                let executable = fs::canonicalize(path)
                    .with_context(|| format!("Invalid Essentia worker path {}", path.display()))?;
                let worker_sha256 = sha256_file(&executable)?;
                #[cfg(windows)]
                let deployment_sha256 = Some(verify_windows_deployment(&executable)?);
                #[cfg(not(windows))]
                let deployment_sha256 = None;
                Ok(Self::Essentia {
                    executable, worker_sha256, deployment_sha256, timeout_seconds,
                })
            }
            ("rust", Some(_)) => bail!("--essentia-worker requires --audio-backend essentia"),
            ("essentia", None) => bail!("--audio-backend essentia requires --essentia-worker"),
            _ => bail!("--audio-backend must be rust or essentia"),
        }
    }

    pub fn preprocessing(&self) -> &'static str {
        match self {
            Self::Rust => crate::audio_decode::RUST_PREPROCESSING,
            Self::Essentia { .. } => CPP_PREPROCESSING,
        }
    }
    pub fn worker_hash(&self) -> Option<&str> {
        match self { Self::Rust => None, Self::Essentia { worker_sha256, .. } => Some(worker_sha256) }
    }
    pub fn deployment_hash(&self) -> Option<&str> {
        match self {
            Self::Rust => None,
            Self::Essentia { deployment_sha256, .. } => deployment_sha256.as_deref(),
        }
    }
}

pub struct NativePatches {
    pub patches: Vec<Vec<f32>>,
    pub decode_seconds: f64,
    pub features_seconds: f64,
}

struct ChildIo {
    child: Child,
    input: Option<ChildStdin>,
    output: Option<ChildStdout>,
    hello_pending: bool,
}

impl Drop for ChildIo {
    fn drop(&mut self) {
        // On timeout or native failure, close/kill and reap before next song.
        let pid = self.child.id();
        let _ = self.child.kill();
        let _ = self.child.wait();
        crate::resources::unregister_native_child(pid);
    }
}

/// One Rust worker thread owns one long-lived *process*, never shared Essentia
/// objects. Blocking native pipe I/O runs on a short-lived transport thread:
/// the caller owns Child and can forcibly terminate an unresponsive native
/// process, releasing a hung read or handshake on every supported platform.
pub struct EssentiaWorker {
    executable: PathBuf,
    child: Option<ChildIo>,
    timeout: Duration,
}

impl EssentiaWorker {
    #[cfg(test)]
    pub fn new(executable: PathBuf) -> Self {
        Self::with_timeout(executable, Duration::from_secs(900))
    }

    pub fn with_timeout(executable: PathBuf, timeout: Duration) -> Self {
        Self { executable, child: None, timeout }
    }

    fn start(&mut self) -> Result<()> {
        if self.child.is_some() { return Ok(()); }
        let mut command = Command::new(&self.executable);
        command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::inherit());
        crate::parallel::configure_native_child_command(&mut command);
        let mut child = command.spawn().with_context(|| format!(
            "Failed to launch native Essentia worker {}", self.executable.display()
        ))?;
        if let Err(err) = crate::parallel::verify_native_child_priority(&child) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(err);
        }
        let input = child.stdin.take().context("Native worker stdin missing")?;
        let output = child.stdout.take().context("Native worker stdout missing")?;
        // Handshake occurs *under the same hard deadline* as the first request.
        crate::resources::register_native_child(child.id());
        crate::resources::record_native_child_priority(&child);
        self.child = Some(ChildIo {
            child, input: Some(input), output: Some(output), hello_pending: true,
        });
        Ok(())
    }

    pub fn analyze(&mut self, path: &Path, max_patches: Option<usize>) -> Result<NativePatches> {
        let path = path.to_str().context("Essentia worker needs a UTF-8 source path")?;
        if path.is_empty() || path.contains('\0') || path.len() > MAX_PATH_BYTES {
            bail!("Native worker source path invalid or too long");
        }
        let cap = max_patches.unwrap_or(0);
        if cap > MAX_PATCHES || max_patches == Some(0) {
            bail!("Essentia patch limit must be between 1 and {MAX_PATCHES}, or omitted");
        }
        self.start()?;
        let mut io = self.child.take().context("Missing Essentia worker")?;
        let input = io.input.take().context("Native worker input missing")?;
        let output = io.output.take().context("Native worker output missing")?;
        let initial = io.hello_pending;
        let path = path.as_bytes().to_vec();
        let (tx, rx) = mpsc::sync_channel(1);
        let handle = std::thread::spawn(move || {
            let mut input = input;
            let mut output = output;
            let result = (|| -> Result<NativePatches> {
                if initial {
                    let mut hello = [0u8; 4];
                    output.read_exact(&mut hello)
                        .context("Native Essentia worker handshake failed")?;
                    if &hello != b"EFW1" {
                        bail!("Native Essentia worker protocol mismatch: expected EFW1");
                    }
                }
                input.write_all(b"REQ1")?;
                input.write_all(&(path.len() as u32).to_le_bytes())?;
                input.write_all(&(cap as u32).to_le_bytes())?;
                input.write_all(&path)?;
                input.flush()?;
                read_response(&mut output, max_patches)
            })();
            let _ = tx.send((result, input, output));
        });
        match rx.recv_timeout(self.timeout) {
            Ok((result, input, output)) => {
                let _ = handle.join();
                if result.is_ok() {
                    io.input = Some(input);
                    io.output = Some(output);
                    io.hello_pending = false;
                    self.child = Some(io);
                }
                // Errors retire the process; never silently mix a Rust fallback.
                result
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {
                // io still owns Child, so dropping it kills the blocked C++
                // process, releases the pipe reads and reaps the child.
                drop(io);
                let _ = handle.join();
                bail!("Native Essentia worker exceeded {}-second deadline", self.timeout.as_secs());
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                drop(io);
                let _ = handle.join();
                bail!("Native Essentia worker transport thread exited unexpectedly");
            }
        }
    }
}

fn u32le(input: &mut impl Read) -> Result<u32> {
    let mut buf = [0u8; 4];
    input.read_exact(&mut buf).context("Truncated native worker response")?;
    Ok(u32::from_le_bytes(buf))
}
fn u64le(input: &mut impl Read) -> Result<u64> {
    let mut buf = [0u8; 8];
    input.read_exact(&mut buf).context("Truncated native worker timing")?;
    Ok(u64::from_le_bytes(buf))
}

fn read_response(input: &mut impl Read, requested_cap: Option<usize>) -> Result<NativePatches> {
    let mut header = [0u8; 5];
    input.read_exact(&mut header).context("Truncated Essentia response header")?;
    if &header[..4] != b"RES1" { bail!("Native worker returned invalid response magic"); }
    let count = u32le(input)? as usize;
    let decode_seconds = u64le(input)? as f64 / 1e9;
    let features_seconds = u64le(input)? as f64 / 1e9;
    match header[4] {
        1 => {
            if count > MAX_ERROR_BYTES { bail!("Native worker error message exceeds protocol limit"); }
            let mut error = vec![0u8; count];
            input.read_exact(&mut error).context("Truncated native worker error")?;
            let message = String::from_utf8(error).context("Invalid worker error UTF-8")?;
            bail!("Essentia C++ frontend error: {message}");
        }
        0 => {
            if count == 0 || count > MAX_PATCHES || requested_cap.is_some_and(|c| count > c) {
                bail!("Essentia worker patch count out of bounds");
            }
            let mut patches = Vec::with_capacity(count);
            for _ in 0..count {
                let mut bytes = vec![0u8; VALUES_PER_PATCH * 4];
                input.read_exact(&mut bytes).context("Truncated native worker patch")?;
                let mut patch = Vec::with_capacity(VALUES_PER_PATCH);
                for chunk in bytes.as_chunks::<4>().0 {
                    let v = f32::from_le_bytes(*chunk);
                    if !v.is_finite() || v < 0.0 {
                        bail!("Native worker returned invalid Mel coefficient");
                    }
                    patch.push(v);
                }
                patches.push(patch);
            }
            Ok(NativePatches { patches, decode_seconds, features_seconds })
        }
        _ => bail!("Native worker response status invalid"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn response(status: u8, count: u32, body: &[u8]) -> Vec<u8> {
        let mut v = b"RES1".to_vec();
        v.push(status);
        v.extend_from_slice(&count.to_le_bytes());
        v.extend_from_slice(&9u64.to_le_bytes());
        v.extend_from_slice(&27u64.to_le_bytes());
        v.extend_from_slice(body);
        v
    }

    #[test]
    fn rejects_corrupt_and_oversized_protocol() {
        assert!(read_response(&mut Cursor::new(b"GARBAGE"), None).is_err());
        assert!(read_response(&mut Cursor::new(response(0, 2049, &[])), None).is_err());
        assert!(read_response(&mut Cursor::new(response(0, 2, &[])), Some(1)).is_err());
        assert!(read_response(&mut Cursor::new(response(0, 1, &[])), None).is_err());
        assert!(read_response(&mut Cursor::new(response(3, 0, &[])), None).is_err());
        assert!(read_response(&mut Cursor::new(response(1, 4097, &[])), None).is_err());
    }

    #[test]
    fn parses_bounded_error_without_confusing_it_with_success() {
        let data = response(1, 4, b"oops");
        let err = read_response(&mut Cursor::new(data), None).err().unwrap();
        assert!(format!("{err:#}").contains("oops"));
    }

    #[test]
    fn validates_exact_float_payload_and_stage_timing() {
        let patch = vec![0.5_f32; VALUES_PER_PATCH];
        let body: Vec<u8> = patch.iter().flat_map(|v| v.to_le_bytes()).collect();
        let p = read_response(&mut Cursor::new(response(0, 1, &body)), Some(1)).unwrap();
        assert_eq!(p.patches.len(), 1);
        assert_eq!(p.patches[0].len(), VALUES_PER_PATCH);
        assert_eq!(p.patches[0][0], 0.5);
        assert!((p.decode_seconds - 9e-9).abs() < 1e-12);
        let mut bad = body.clone();
        bad[0..4].copy_from_slice(&f32::NAN.to_le_bytes());
        assert!(read_response(&mut Cursor::new(response(0, 1, &bad)), None).is_err());
    }

    #[test]
    fn child_protocol_reuses_and_restarts_real_process() {
        let Some(exe) = std::env::var_os("ESSENTIA_IPC_FIXTURE_EXE") else {
            // Native fixture is built in the Rust CI job; local builds do
            // not require any native C++ toolchain or Essentia install.
            return;
        };
        let mut worker = EssentiaWorker::new(PathBuf::from(exe));
        let first = worker.analyze(Path::new("good-one.wav"), None).unwrap();
        assert_eq!(first.patches.len(), 1);
        assert_eq!(first.patches[0][0], 0.25);
        let raw = worker.analyze(Path::new("binary-bytes.wav"), None).unwrap();
        assert_eq!(raw.patches[0][0].to_bits(), 0x3f1a0a0d,
            "Native IPC must preserve CR/LF/CTRL-Z bytes on Windows");
        assert!((first.decode_seconds - 0.001).abs() < 1e-6);
        let first_pid = worker.child.as_ref().unwrap().child.id();
        let second = worker.analyze(Path::new("good-two.flac"), Some(1)).unwrap();
        assert_eq!(second.patches[0][0], 0.25);
        assert_eq!(worker.child.as_ref().unwrap().child.id(), first_pid,
                   "C++ worker must be reused across consecutive songs");
        assert!(worker.analyze(Path::new("fail.flac"), None).is_err());
        assert!(worker.child.is_none(), "native errors retire the process");
        let after = worker.analyze(Path::new("good-after-error.flac"), None).unwrap();
        assert_eq!(after.patches.len(), 1);
        assert!(worker.analyze(Path::new("crash.flac"), None).is_err());
        assert!(worker.child.is_none(), "native crashes must not poison future jobs");
        assert_eq!(worker.analyze(Path::new("good-restarted.flac"), None)
            .unwrap().patches.len(), 1);
    }

    #[test]
    fn hard_deadline_kills_hung_worker_and_allows_restart() {
        let Some(exe) = std::env::var_os("ESSENTIA_IPC_FIXTURE_EXE") else { return };
        let mut worker = EssentiaWorker::with_timeout(
            PathBuf::from(exe), Duration::from_millis(250),
        );
        let started = std::time::Instant::now();
        let failure = worker.analyze(Path::new("hang.flac"), None)
            .err().expect("hung native worker must time out");
        assert!(format!("{failure:#}").contains("deadline"));
        assert!(started.elapsed() < Duration::from_secs(4));
        assert!(worker.child.is_none());
        assert_eq!(worker.analyze(Path::new("recovered.wav"), Some(1))
            .unwrap().patches.len(), 1);
    }

    #[test]
    fn independent_cpp_processes_support_parallel_rust_workers() {
        let Some(exe) = std::env::var_os("ESSENTIA_IPC_FIXTURE_EXE") else { return };
        let participants = 4usize;
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(participants + 1));
        let mut handles = Vec::new();
        for worker_id in 0..participants {
            let exe = PathBuf::from(&exe);
            let gate = std::sync::Arc::clone(&barrier);
            handles.push(std::thread::spawn(move || {
                let mut worker = EssentiaWorker::with_timeout(
                    exe, Duration::from_secs(10),
                );
                let first = format!("parallel-first-{worker_id}.flac");
                let second = format!("parallel-second-{worker_id}.flac");
                let a = worker.analyze(Path::new(&first), Some(1)).unwrap();
                assert_eq!(a.patches.len(), 1);
                let pid = worker.child.as_ref().unwrap().child.id();
                // All processes are alive together, ruling out PID reuse.
                gate.wait();
                // Keep the native process alive while the parent samples
                // combined Rust + native child resident/private memory.
                gate.wait();
                let b = worker.analyze(Path::new(&second), None).unwrap();
                assert_eq!(b.patches[0][0], 0.25);
                assert_eq!(worker.child.as_ref().unwrap().child.id(), pid);
                pid
            }));
        }
        barrier.wait();
        let concurrent_tree = crate::resources::process_tree_memory_diagnostics();
        // Always release the test worker threads before assertions; otherwise
        // a failed RSS check would strand all four threads on their barrier.
        barrier.wait();
        let mut pids = std::collections::HashSet::new();
        for handle in handles {
            assert!(pids.insert(handle.join().unwrap()),
                "Parallel Rust workers must each own a distinct native process");
        }
        assert_eq!(pids.len(), participants);
        if let Some(tree) = concurrent_tree {
            assert!(tree.registered_children >= participants);
            if tree.complete {
                assert!(tree.observed_children >= participants);
                assert!(tree.child_working_set_mib > 0.0);
                assert!(tree.total_working_set_mib >= tree.child_working_set_mib);
            }
        }
        if let Some(tree) = crate::resources::process_tree_memory_diagnostics() {
            // All test-owned workers have exited. Other tests may have
            // concurrently spawned their own worker processes.
            assert!(tree.registered_children < participants);
        }
    }

    #[cfg(windows)]
    #[test]
    fn windows_manifest_guards_actual_worker_and_dependency_bytes() {
        let Some(fixture) = std::env::var_os("ESSENTIA_IPC_FIXTURE_EXE") else {
            return; // CI supplies MSVC-compiled native protocol fixture.
        };
        let exe = PathBuf::from(fixture);
        let dir = std::env::temp_dir().join(format!(
            "bliss-native-bundle-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()
        ));
        std::fs::create_dir(&dir).unwrap();
        let target = dir.join("essentia-protocol-fixture.exe");
        let dll = dir.join("synthetic-dependency.dll");
        std::fs::copy(&exe, &target).unwrap();
        std::fs::copy(&exe, &dll).unwrap();
        assert!(BackendChoice::from_cli("essentia", Some(&target), 900).is_err(),
                "Windows native C++ executable without DLL manifest is not safe");
        let manifest = serde_json::json!({
            "schema_version": 1,
            "platform": "windows-x86_64-mingw64",
            "worker_executable": "essentia-protocol-fixture.exe",
            "files": {
                "essentia-protocol-fixture.exe": {
                    "size_bytes": std::fs::metadata(&target).unwrap().len(),
                    "sha256": sha256_file(&target).unwrap()
                },
                "synthetic-dependency.dll": {
                    "size_bytes": std::fs::metadata(&dll).unwrap().len(),
                    "sha256": sha256_file(&dll).unwrap()
                }
            }
        });
        std::fs::write(dir.join("worker-dependencies.json"), manifest.to_string()).unwrap();
        let checked = BackendChoice::from_cli("essentia", Some(&target), 900).unwrap();
        assert_eq!(checked.worker_hash(), Some(sha256_file(&target).unwrap().as_str()));
        assert_eq!(
            checked.deployment_hash(),
            Some(sha256_file(&dir.join("worker-dependencies.json")).unwrap().as_str())
        );
        std::fs::write(&dll, b"tampered after packaging").unwrap();
        assert!(BackendChoice::from_cli("essentia", Some(&target), 900).is_err(),
                "Changing a bundled DLL must invalidate the entire native backend");
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn backend_selection_is_explicit() {
        assert!(matches!(BackendChoice::from_cli("rust", None, 900), Ok(BackendChoice::Rust)));
        assert!(BackendChoice::from_cli("unknown", None, 900).is_err());
        assert!(BackendChoice::from_cli("essentia", None, 900).is_err());
        assert!(BackendChoice::from_cli("rust", Some(Path::new("worker")), 900).is_err());
        assert!(BackendChoice::from_cli("rust", None, 0).is_err());
        assert!(BackendChoice::from_cli("rust", None, 7201).is_err());
    }
}
