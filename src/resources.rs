//! Lightweight system-wide CPU and physical RAM telemetry.
//! CPU is measured as a delta between OS cumulative counters; no external
//! profiling tools or dependencies required.
use serde::Serialize;
use std::{
    collections::HashSet,
    sync::{Mutex, OnceLock},
    time::{Duration, Instant},
};

/// Track only worker processes spawned by our Rust scanner. This is intentionally
/// not a system-wide process tree search; a worker never spawns Essentia helpers.
fn native_children() -> &'static Mutex<HashSet<u32>> {
    static CHILDREN: OnceLock<Mutex<HashSet<u32>>> = OnceLock::new();
    CHILDREN.get_or_init(|| Mutex::new(HashSet::new()))
}

/// Called immediately after spawning the trusted native C++ executable.
pub fn register_native_child(pid: u32) {
    if let Ok(mut children) = native_children().lock() {
        children.insert(pid);
    }
}

/// Called after terminating/reaping a child, so stale PIDs are not sampled.
pub fn unregister_native_child(pid: u32) {
    if let Ok(mut children) = native_children().lock() {
        children.remove(&pid);
    }
}

/// Persist actual Windows native child process priority classes on launch:
/// children can exit before the final scan summary is serialized.
#[cfg(windows)]
fn native_priorities() -> &'static Mutex<(std::collections::BTreeSet<String>, usize)> {
    static OBSERVED: OnceLock<Mutex<(std::collections::BTreeSet<String>, usize)>> = OnceLock::new();
    OBSERVED.get_or_init(|| Mutex::new((std::collections::BTreeSet::new(), 0)))
}

pub fn reset_native_priority_observations() {
    #[cfg(windows)]
    if let Ok(mut state) = native_priorities().lock() {
        state.0.clear();
        state.1 = 0;
    }
}

pub fn native_priority_observations() -> (Vec<String>, usize) {
    #[cfg(windows)]
    {
        return native_priorities().lock()
            .map(|state| (state.0.iter().cloned().collect(), state.1))
            .unwrap_or_else(|_| (Vec::new(), 1));
    }
    #[cfg(not(windows))]
    (Vec::new(), 0)
}

pub fn record_native_child_priority(child: &std::process::Child) {
    #[cfg(windows)]
    if let Ok(mut state) = native_priorities().lock() {
        if let Some(actual) = crate::parallel::native_child_priority(child) {
            state.0.insert(actual.to_owned());
        } else {
            state.1 += 1;
        }
    }
    #[cfg(not(windows))]
    let _ = child;
}

/// Resident and private memory combined across Rust and its directly spawned
/// Essentia subprocesses. Resident totals may include shared DLL / page-cache
/// mappings more than once; this is a conservative footprint estimate.
#[derive(Clone, Copy, Debug, Serialize)]
pub struct ProcessTreeMemoryDiagnostics {
    pub total_working_set_mib: f64,
    pub total_private_bytes_mib: f64,
    pub child_working_set_mib: f64,
    pub child_private_bytes_mib: f64,
    pub registered_children: usize,
    pub observed_children: usize,
    /// False if any registered child exited before its counters were read.
    pub complete: bool,
}

pub fn process_tree_memory_diagnostics() -> Option<ProcessTreeMemoryDiagnostics> {
    let own = native::process_memory_counters()?;
    let children: Vec<u32> = native_children().lock().ok()?.iter().copied().collect();
    let mut child_working_set: u64 = 0;
    let mut child_private: u64 = 0;
    let mut observed = 0usize;
    for pid in &children {
        if let Some((working, private, _)) = native::memory_for_pid(*pid) {
            child_working_set = child_working_set.saturating_add(working);
            child_private = child_private.saturating_add(private);
            observed += 1;
        }
    }
    const MIB: f64 = 1048576.0;
    Some(ProcessTreeMemoryDiagnostics {
        total_working_set_mib: own.0.saturating_add(child_working_set) as f64 / MIB,
        total_private_bytes_mib: own.1.saturating_add(child_private) as f64 / MIB,
        child_working_set_mib: child_working_set as f64 / MIB,
        child_private_bytes_mib: child_private as f64 / MIB,
        registered_children: children.len(),
        observed_children: observed,
        complete: children.len() == observed,
    })
}


#[derive(Clone, Copy, Debug, Serialize)]
pub struct LoadSample {
    pub system_cpu_percent: f64,
    pub system_ram_percent: f64,
}

/// Optional diagnostic snapshot; does not affect concurrency decisions.
#[derive(Clone, Copy, Debug, Serialize)]
pub struct MemoryDiagnostics {
    pub available_physical_mib: f64,
}

pub fn memory_diagnostics() -> Option<MemoryDiagnostics> {
    native::available_memory_bytes().map(|bytes| MemoryDiagnostics {
        available_physical_mib: bytes as f64 / (1024.0 * 1024.0),
    })
}

/// Windows process memory counters. Page faults include soft faults and are
/// not a direct count of pagefile reads or physical disk I/O.
#[derive(Clone, Copy, Debug, Serialize)]
pub struct ProcessMemoryDiagnostics {
    pub working_set_mib: f64,
    pub private_bytes_mib: f64,
    pub page_fault_count: u64,
}

pub fn process_memory_diagnostics() -> Option<ProcessMemoryDiagnostics> {
    native::process_memory_counters().map(|(working_set, private_bytes, faults)| {
        ProcessMemoryDiagnostics {
            working_set_mib: working_set as f64 / 1048576.0,
            private_bytes_mib: private_bytes as f64 / 1048576.0,
            page_fault_count: faults,
        }
    })
}

/// System and analyzer resource usage before any scan worker is started.
///
/// CPU is an average across a one-second pre-worker interval, not an
/// instantaneous value. The interval does not contribute to adaptive-worker
/// load decisions or the scan's ordinary resource samples.
#[derive(Clone, Copy, Debug, Serialize)]
pub struct ScanResourceBaseline {
    pub system_cpu_percent: Option<f64>,
    pub cpu_measurement_seconds: f64,
    pub system_ram_percent: Option<f64>,
    pub system_available_ram_mib: Option<f64>,
    pub process_working_set_mib: Option<f64>,
    pub process_private_bytes_mib: Option<f64>,
}

/// Called after opening the scan's input and sidecar DB, before spawning
/// workers or dispatching any audio jobs.
pub fn scan_resource_baseline() -> ScanResourceBaseline {
    let system_ram_percent = memory_load();
    let system_available_ram_mib = memory_diagnostics()
        .map(|memory| memory.available_physical_mib);
    let process = process_memory_diagnostics();

    let first = cpu_ticks();
    let start = Instant::now();
    std::thread::sleep(Duration::from_secs(1));
    let elapsed = start.elapsed().as_secs_f64();
    let second = cpu_ticks();

    let system_cpu_percent = match (first, second) {
        (Some(before), Some(after)) => cpu_usage_between(before, after),
        _ => None,
    };

    ScanResourceBaseline {
        system_cpu_percent,
        cpu_measurement_seconds: elapsed,
        system_ram_percent,
        system_available_ram_mib,
        process_working_set_mib: process.map(|p| p.working_set_mib),
        process_private_bytes_mib: process.map(|p| p.private_bytes_mib),
    }
}

/// Busy ticks and total ticks must use the same system-wide CPU counter.
fn cpu_usage_between(before: (u64, u64), after: (u64, u64)) -> Option<f64> {
    let busy = after.0.saturating_sub(before.0);
    let total = after.1.saturating_sub(before.1);
    if total == 0 { return None; }
    Some((100.0 * busy as f64 / total as f64).clamp(0.0, 100.0))
}

pub struct ResourceMonitor {
    previous: Option<(u64, u64)>,
    last: Instant,
}

impl ResourceMonitor {
    pub fn new() -> Self {
        Self {
            previous: cpu_ticks(),
            last: Instant::now(),
        }
    }

    pub fn sample(&mut self) -> Option<LoadSample> {
        if self.last.elapsed() < Duration::from_secs(2) {
            return None;
        }
        self.last = Instant::now();
        let current = cpu_ticks()?;
        let previous = self.previous.replace(current)?;
        let cpu = cpu_usage_between(previous, current)?;
        let ram = memory_load()?;
        if !ram.is_finite() { return None; }
        Some(LoadSample {
            system_cpu_percent: cpu,
            system_ram_percent: ram.clamp(0.0, 100.0),
        })
    }
}

#[cfg(windows)]
mod native {
    #[repr(C)]
    #[derive(Default, Clone, Copy)]
    struct FileTime {
        low: u32,
        high: u32,
    }

    #[repr(C)]
    #[derive(Default)]
    struct MemoryStatusEx {
        length: u32,
        memory_load: u32,
        total_phys: u64,
        avail_phys: u64,
        total_pagefile: u64,
        avail_pagefile: u64,
        total_virtual: u64,
        avail_virtual: u64,
        avail_extended_virtual: u64,
    }

    #[repr(C)]
    #[derive(Default)]
    struct ProcessMemoryCountersEx {
        cb: u32,
        page_fault_count: u32,
        peak_working_set_size: usize,
        working_set_size: usize,
        quota_peak_paged_pool_usage: usize,
        quota_paged_pool_usage: usize,
        quota_peak_non_paged_pool_usage: usize,
        quota_non_paged_pool_usage: usize,
        pagefile_usage: usize,
        peak_pagefile_usage: usize,
        private_usage: usize,
    }

    #[link(name = "psapi")]
    extern "system" {
        fn GetProcessMemoryInfo(
            process: *mut std::ffi::c_void,
            counters: *mut ProcessMemoryCountersEx,
            cb: u32,
        ) -> i32;
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn OpenProcess(access: u32, inherit: i32, pid: u32) -> *mut std::ffi::c_void;
        fn CloseHandle(handle: *mut std::ffi::c_void) -> i32;
        fn GetSystemTimes(idle: *mut FileTime, kernel: *mut FileTime, user: *mut FileTime) -> i32;
        fn GlobalMemoryStatusEx(status: *mut MemoryStatusEx) -> i32;
        fn GetCurrentProcess() -> *mut std::ffi::c_void;
    }

    pub fn process_memory_counters() -> Option<(u64, u64, u64)> {
        let mut counters = ProcessMemoryCountersEx {
            cb: std::mem::size_of::<ProcessMemoryCountersEx>() as u32,
            ..ProcessMemoryCountersEx::default()
        };
        // SAFETY: process pseudo-handle is valid for the caller and the fixed
        // C layout is initialized, with its size passed to the Win32 API.
        let size = counters.cb;
        let ok = unsafe {
            GetProcessMemoryInfo(GetCurrentProcess(), &mut counters, size)
        };
        if ok == 0 { return None; }
        Some((
            counters.working_set_size as u64,
            counters.private_usage as u64,
            counters.page_fault_count as u64,
        ))
    }

    pub fn memory_for_pid(pid: u32) -> Option<(u64, u64, u64)> {
        const PROCESS_QUERY_INFORMATION: u32 = 0x0400;
        const PROCESS_VM_READ: u32 = 0x0010;
        // SAFETY: OpenProcess is called with read-only access, and CloseHandle
        // balances every successful call even if memory probing fails.
        let handle = unsafe { OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, 0, pid) };
        if handle.is_null() { return None; }
        let mut counters = ProcessMemoryCountersEx {
            cb: std::mem::size_of::<ProcessMemoryCountersEx>() as u32,
            ..ProcessMemoryCountersEx::default()
        };
        let size = counters.cb;
        let result = unsafe { GetProcessMemoryInfo(handle, &mut counters, size) };
        unsafe { CloseHandle(handle) };
        if result == 0 { return None; }
        Some((
            counters.working_set_size as u64,
            counters.private_usage as u64,
            counters.page_fault_count as u64,
        ))
    }

    fn to_ticks(time: FileTime) -> u64 {
        (u64::from(time.high) << 32) | u64::from(time.low)
    }

    pub fn cpu_ticks() -> Option<(u64, u64)> {
        let (mut idle, mut kernel, mut user) = (FileTime::default(), FileTime::default(), FileTime::default());
        // SAFETY: The OS populates all three fixed-layout structures; no pointers are retained.
        if unsafe { GetSystemTimes(&mut idle, &mut kernel, &mut user) } == 0 {
            return None;
        }
        let total = to_ticks(kernel).saturating_add(to_ticks(user));
        let busy = total.saturating_sub(to_ticks(idle));
        Some((busy, total))
    }

    fn memory_status() -> Option<MemoryStatusEx> {
        let mut info = MemoryStatusEx {
            length: std::mem::size_of::<MemoryStatusEx>() as u32,
            ..MemoryStatusEx::default()
        };
        // SAFETY: Fixed-layout MEMORYSTATUSEX, correct dwLength supplied.
        if unsafe { GlobalMemoryStatusEx(&mut info) } == 0 {
            return None;
        }
        if info.total_phys == 0 { return None; }
        Some(info)
    }

    pub fn memory_load() -> Option<f64> {
        let info = memory_status()?;
        Some(100.0 * (1.0 - info.avail_phys as f64 / info.total_phys as f64))
    }

    pub fn available_memory_bytes() -> Option<u64> {
        Some(memory_status()?.avail_phys)
    }
}

#[cfg(target_os = "linux")]
mod native {
    use std::fs;
    pub fn cpu_ticks() -> Option<(u64, u64)> {
        let stats = fs::read_to_string("/proc/stat").ok()?;
        let line = stats.lines().next()?;
        let mut items = line.split_whitespace();
        if items.next()? != "cpu" {
            return None;
        }
        let values: Vec<u64> = items.take(8).map(str::parse).collect::<Result<_, _>>().ok()?;
        if values.len() < 4 {
            return None;
        }
        let total: u64 = values.iter().sum();
        let idle = values[3].saturating_add(values.get(4).copied().unwrap_or(0));
        Some((total.saturating_sub(idle), total))
    }
    /// Linux resident memory comes from VmRSS; true non-shared private pages
    /// come from smaps_rollup Private_Clean + Private_Dirty (not VmData).
    /// smaps_rollup may be unavailable on older kernels or restricted procfs.
    pub fn memory_for_pid(pid: u32) -> Option<(u64, u64, u64)> {
        let status = fs::read_to_string(format!("/proc/{pid}/status")).ok()?;
        let rss_kib = parse_kib_field(&status, "VmRSS:")?;
        let rollup = fs::read_to_string(format!("/proc/{pid}/smaps_rollup")).ok()?;
        let private_kib = parse_kib_field(&rollup, "Private_Clean:")?
            .checked_add(parse_kib_field(&rollup, "Private_Dirty:")?)?;
        Some((
            rss_kib.checked_mul(1024)?,
            private_kib.checked_mul(1024)?,
            0, // Linux fault counters are not exposed by this lightweight probe.
        ))
    }
    pub(super) fn parse_kib_field(text: &str, name: &str) -> Option<u64> {
        text.lines().find(|line| line.starts_with(name))?
            .split_whitespace().nth(1)?.parse::<u64>().ok()
    }
    pub fn process_memory_counters() -> Option<(u64, u64, u64)> {
        memory_for_pid(std::process::id())
    }
    pub fn available_memory_bytes() -> Option<u64> {
        let stats = fs::read_to_string("/proc/meminfo").ok()?;
        let line = stats.lines().find(|line| line.starts_with("MemAvailable:"))?;
        let kib: u64 = line.split_whitespace().nth(1)?.parse().ok()?;
        kib.checked_mul(1024)
    }
    pub fn memory_load() -> Option<f64> {
        let stats = fs::read_to_string("/proc/meminfo").ok()?;
        let get = |prefix: &str| -> Option<f64> {
            stats.lines().find(|line| line.starts_with(prefix))?
                .split_whitespace().nth(1)?.parse().ok()
        };
        let total = get("MemTotal:")?;
        let available = get("MemAvailable:")?;
        if total <= 0.0 { return None; }
        Some(100.0 * (1.0 - available / total))
    }
}

#[cfg(not(any(target_os = "linux", windows)))]
mod native {
    pub fn cpu_ticks() -> Option<(u64,u64)> { None }
    pub fn memory_load() -> Option<f64> { None }
    pub fn available_memory_bytes() -> Option<u64> { None }
    pub fn process_memory_counters() -> Option<(u64, u64, u64)> { None }
    pub fn memory_for_pid(_pid: u32) -> Option<(u64, u64, u64)> { None }
}

use native::{cpu_ticks, memory_load};

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cpu_usage_between_handles_empty_and_valid_intervals() {
        assert_eq!(cpu_usage_between((10, 20), (30, 60)), Some(50.0));
        assert_eq!(cpu_usage_between((10, 20), (10, 20)), None);
        assert_eq!(cpu_usage_between((10, 20), (30, 30)), Some(100.0));
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn parses_linux_smaps_rollup_fields_without_using_vmdata_as_private() {
        let fixture = "Rss:              400 kB\nPrivate_Clean:    100 kB\nPrivate_Dirty:    222 kB\n";
        assert_eq!(native::parse_kib_field(fixture, "Private_Clean:"), Some(100));
        assert_eq!(native::parse_kib_field(fixture, "Private_Dirty:"), Some(222));
        assert_eq!(native::parse_kib_field(fixture, "VmData:"), None);
    }

    #[test]
    fn native_child_registry_is_idempotent() {
        let pid = u32::MAX; // never an actual operating-system PID
        unregister_native_child(pid);
        register_native_child(pid);
        register_native_child(pid);
        assert!(native_children().lock().unwrap().contains(&pid));
        unregister_native_child(pid);
        assert!(!native_children().lock().unwrap().contains(&pid));
    }

    #[test]
    fn memory_and_cpu_queries_are_optional_but_bounded() {
        if let Some(percentage) = memory_load() {
            assert!((0.0..=100.0).contains(&percentage));
        }
        if let Some((busy, total)) = cpu_ticks() {
            assert!(total >= busy);
        }
        if let Some(detail) = memory_diagnostics() {
            assert!(detail.available_physical_mib.is_finite());
            assert!(detail.available_physical_mib >= 0.0);
        }
        if let Some(process) = process_memory_diagnostics() {
            assert!(process.working_set_mib.is_finite() && process.working_set_mib >= 0.0);
            assert!(process.private_bytes_mib.is_finite() && process.private_bytes_mib >= 0.0);
        }
        if let Some(tree) = process_tree_memory_diagnostics() {
            assert!(tree.total_working_set_mib >= 0.0);
            assert!(tree.total_private_bytes_mib >= 0.0);
            assert!(tree.child_working_set_mib >= 0.0);
            assert!(tree.observed_children <= tree.registered_children);
        }
        let mut monitor = ResourceMonitor::new();
        // First sample intentionally waits for a nonzero OS counter interval.
        assert!(monitor.sample().is_none());
    }
}
