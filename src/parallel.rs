//! Conservative CPU worker sizing for background offline library analysis.
//! --threads controls ONNX *inside one track*; --workers controls parallel tracks.

use anyhow::{bail, Result};

/// Logical CPUs available to this process (not physical core count or a
/// measured performance optimum). Respect CPU affinity/container restrictions.
pub fn available_worker_capacity() -> usize {
    std::thread::available_parallelism()
        .map(|n| n.get()).unwrap_or(1).clamp(1, 64)
}

fn worker_count_for(spec: &str, permitted: usize) -> Result<(usize, bool)> {
    let cap = permitted.clamp(1, 64);
    if spec.eq_ignore_ascii_case("auto") {
        // Keep the existing conservative initial policy: reserve CPU headroom.
        // This is a one-time, conservative CPU-based choice (not autotuning).
        let reserve = (cap / 4).max(2);
        Ok((cap.saturating_sub(reserve).clamp(1, 8), true))
    } else {
        let workers: usize = spec.parse().map_err(|_| {
            anyhow::anyhow!("--workers must be 'auto' or a positive integer")
        })?;
        if !(1..=64).contains(&workers) {
            bail!("--workers must be between 1 and 64");
        }
        if workers > cap {
            bail!("--workers {workers} exceeds the {cap} logical CPUs available to this process");
        }
        Ok((workers, false))
    }
}

pub fn worker_count(spec: &str) -> Result<(usize, bool)> {
    worker_count_for(spec, available_worker_capacity())
}

/// Explicit Windows priority is independent of the fixed worker count.
/// Without --priority, auto retains the background scheduling behavior.
#[derive(Clone, Debug, serde::Serialize)]
pub struct PriorityDiagnostics {
    pub requested: String,
    pub policy: String,
    pub effective_scanner: Option<String>,
    pub native_worker_classes: Vec<String>,
    pub native_worker_observation_failures: usize,
}

fn priority_policy(requested: Option<&str>, is_auto: bool) -> Result<&'static str> {
    match requested {
        Some("normal") => Ok("normal"),
        Some("below-normal") => Ok("below-normal"),
        Some("above-normal") => Ok("above-normal"),
        None if is_auto => Ok("below-normal"),
        None => Ok("unchanged"),
        Some(_) => bail!("Invalid --priority; choose below-normal, normal or above-normal"),
    }
}

pub fn configure_scan_priority(
    requested: Option<&str>, is_auto: bool, dry_run: bool,
) -> Result<PriorityDiagnostics> {
    let policy = priority_policy(requested, is_auto)?;
    #[cfg(not(windows))]
    if requested.is_some() {
        bail!("--priority is Windows-only; omit it to use platform-native scheduling");
    }

    #[cfg(windows)]
    if !dry_run && policy != "unchanged" {
        let target = match policy {
            "normal" => NORMAL_PRIORITY_CLASS,
            "below-normal" => BELOW_NORMAL_PRIORITY_CLASS,
            "above-normal" => ABOVE_NORMAL_PRIORITY_CLASS,
            _ => unreachable!("validated priority class"),
        };
        if let Err(err) = set_current_windows_priority(target) {
            if requested.is_some() {
                return Err(err);
            }
            eprintln!("WARNING: Cannot lower Windows process priority: {err:#}");
        }
    }
    let effective = current_windows_priority().map(str::to_owned);
    #[cfg(windows)]
    if requested.is_some() && !dry_run && effective.as_deref() != Some(policy) {
        bail!("Windows priority mismatch: requested {policy}, observed {effective:?}");
    }
    // Explicit classes must be passed to CreateProcess for native children:
    // Windows only inherits BelowNormal/Idle, not AboveNormal.
    // Zero means legacy child priority behavior (no creation class flag).
    #[cfg(windows)]
    NATIVE_CHILD_CREATION_CLASS.store(
        if !dry_run && requested.is_some() {
            match policy {
                "normal" => NORMAL_PRIORITY_CLASS,
                "below-normal" => BELOW_NORMAL_PRIORITY_CLASS,
                "above-normal" => ABOVE_NORMAL_PRIORITY_CLASS,
                _ => unreachable!("validated priority class"),
            }
        } else {
            0
        },
        std::sync::atomic::Ordering::SeqCst,
    );
    crate::resources::reset_native_priority_observations();
    Ok(PriorityDiagnostics {
        requested: requested.unwrap_or("default").to_owned(),
        policy: if dry_run { "unchanged" } else { policy }.to_owned(),
        effective_scanner: effective,
        native_worker_classes: Vec::new(),
        native_worker_observation_failures: 0,
    })
}

impl PriorityDiagnostics {
    pub fn collect_native_workers(&mut self) {
        let (classes, failures) = crate::resources::native_priority_observations();
        self.native_worker_classes = classes;
        self.native_worker_observation_failures = failures;
    }
}

#[cfg(windows)]
static NATIVE_CHILD_CREATION_CLASS: std::sync::atomic::AtomicU32 =
    std::sync::atomic::AtomicU32::new(0);

#[cfg(windows)]
const ABOVE_NORMAL_PRIORITY_CLASS: u32 = 0x0000_8000;
#[cfg(windows)]
const NORMAL_PRIORITY_CLASS: u32 = 0x0000_0020;
#[cfg(windows)]
const BELOW_NORMAL_PRIORITY_CLASS: u32 = 0x0000_4000;

#[cfg(windows)]
#[link(name = "kernel32")]
extern "system" {
    fn GetCurrentProcess() -> *mut std::ffi::c_void;
    fn GetPriorityClass(process: *mut std::ffi::c_void) -> u32;
    fn SetPriorityClass(process: *mut std::ffi::c_void, priority: u32) -> i32;
}

#[cfg(windows)]
fn priority_class_name(priority: u32) -> &'static str {
    match priority {
        0x0000_0040 => "idle",
        0x0000_4000 => "below-normal",
        0x0000_0020 => "normal",
        0x0000_8000 => "above-normal",
        0x0000_0080 => "high",
        0x0000_0100 => "realtime",
        _ => "unknown",
    }
}

#[cfg(windows)]
fn set_current_windows_priority(priority: u32) -> Result<()> {
    if unsafe { SetPriorityClass(GetCurrentProcess(), priority) } == 0 {
        bail!("SetPriorityClass failed: {}", std::io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(windows)]
fn current_windows_priority() -> Option<&'static str> {
    let value = unsafe { GetPriorityClass(GetCurrentProcess()) };
    (value != 0).then(|| priority_class_name(value))
}

#[cfg(not(windows))]
fn current_windows_priority() -> Option<&'static str> { None }

/// Add the verified explicit class to CreateProcess before the native worker
/// executes anything. This is essential for AboveNormal, which Windows does
/// not inherit from its parent.
pub fn configure_native_child_command(command: &mut std::process::Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let flags = NATIVE_CHILD_CREATION_CLASS.load(std::sync::atomic::Ordering::SeqCst);
        if flags != 0 {
            command.creation_flags(flags);
        }
    }
    #[cfg(not(windows))]
    let _ = command;
}

/// Explicit selection is fail-closed: never analyze tracks under an
/// unexpected native child priority class.
pub fn verify_native_child_priority(child: &std::process::Child) -> Result<()> {
    #[cfg(windows)]
    {
        let expected = NATIVE_CHILD_CREATION_CLASS.load(std::sync::atomic::Ordering::SeqCst);
        if expected != 0 {
            let actual = native_child_priority(child);
            if actual != Some(priority_class_name(expected)) {
                bail!("Native worker scheduling priority mismatch: expected {}, got {actual:?}",
                    priority_class_name(expected));
            }
        }
    }
    #[cfg(not(windows))]
    let _ = child;
    Ok(())
}

/// Query the actual native child process handle immediately after spawn.
#[cfg(windows)]
pub fn native_child_priority(child: &std::process::Child) -> Option<&'static str> {
    use std::os::windows::io::AsRawHandle;
    let value = unsafe { GetPriorityClass(child.as_raw_handle().cast()) };
    (value != 0).then(|| priority_class_name(value))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn priority_is_explicit_or_auto_background_only() {
        assert_eq!(priority_policy(None, false).unwrap(), "unchanged");
        assert_eq!(priority_policy(None, true).unwrap(), "below-normal");
        for auto in [false, true] {
            for name in ["normal", "below-normal", "above-normal"] {
                assert_eq!(priority_policy(Some(name), auto).unwrap(), name);
            }
        }
        assert!(priority_policy(Some("realtime"), false).is_err());
    }

    /// Run priority changes in an isolated test-harness subprocess so other
    /// concurrently running tests never have their own priority changed.
    #[cfg(windows)]
    #[test]
    fn windows_priority_is_applied_and_inherited_by_real_child() {
        const CHILD: &str = "LYRION_TEST_PRIORITY_CHILD";
        if std::env::var_os(CHILD).is_none() {
            let current = std::env::current_exe().unwrap();
            let result = std::process::Command::new(current)
                .args(["--exact",
                    "parallel::tests::windows_priority_is_applied_and_inherited_by_real_child",
                    "--nocapture"])
                .env(CHILD, "yes")
                .output()
                .unwrap();
            assert!(result.status.success(),
                "child test failed: {} {}",
                String::from_utf8_lossy(&result.stdout),
                String::from_utf8_lossy(&result.stderr));
            return;
        }
        for requested in ["below-normal", "normal", "above-normal"] {
            let observed = configure_scan_priority(
                Some(requested), false, false,
            ).unwrap();
            assert_eq!(observed.effective_scanner.as_deref(), Some(requested));
            let mut command = std::process::Command::new("powershell.exe");
            command.args(["-NoProfile", "-NonInteractive",
                "-Command", "Start-Sleep -Milliseconds 700"]);
            configure_native_child_command(&mut command);
            let mut child = command.spawn().unwrap();
            assert_eq!(native_child_priority(&child), Some(requested));
            verify_native_child_priority(&child).unwrap();
            child.wait().unwrap();
        }
    }

    #[cfg(windows)]
    #[test]
    fn maps_windows_priority_classes() {
        assert_eq!(priority_class_name(NORMAL_PRIORITY_CLASS), "normal");
        assert_eq!(priority_class_name(BELOW_NORMAL_PRIORITY_CLASS), "below-normal");
        assert_eq!(priority_class_name(ABOVE_NORMAL_PRIORITY_CLASS), "above-normal");
        assert_eq!(priority_class_name(0), "unknown");
    }

    #[test]
    fn resolves_fixed_workers_and_conservative_auto_for_varied_cpu_caps() {
        for (cpu, auto) in [(1,1), (2,1), (4,2), (8,6), (16,8), (64,8)] {
            assert_eq!(worker_count_for("auto", cpu).unwrap(), (auto,true));
            assert_eq!(worker_count_for(&cpu.to_string(), cpu).unwrap(), (cpu,false));
        }
        assert_eq!(worker_count("1").unwrap(), (1,false));
        let (auto,flag) = worker_count("auto").unwrap();
        assert!(flag && (1..=8).contains(&auto));
        for value in ["0","65","-1","NaN","4.5",""] {
            assert!(worker_count(value).is_err());
        }
        assert!(worker_count_for("6",4).is_err());
        assert!(worker_count_for("12",16).is_ok());
    }
}
