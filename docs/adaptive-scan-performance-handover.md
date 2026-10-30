# Adaptive feature scanner — performance and investigation handover

> **Historical investigation only (28 October 2026):** Adaptive worker resizing and throughput autotune are deliberately excluded from the static worker scan CLI prepared in [PR #20](https://github.com/chrober/bliss-mood-poc/pull/20). The user selected `--workers N` or explicit one-time `--workers auto`, retaining default 1. Four 100-song real-music benchmark campaigns (40 scans) are archived in [PR #19](https://github.com/chrober/bliss-mood-poc/blob/feat/ram-safe-online-autotune/docs/autotune-real-music-e2e-findings-20261028.md). The following adaptive recommendations are **not current product behavior**; consult [final architecture](multi-worker-song-analysis-final.md).


> **LATEST HANDOVER (28 OCTOBER 2026):**
> [handover-adaptive-host-sizing-20261028.md](handover-adaptive-host-sizing-20261028.md)
> plus [new-session prompt](handover-prompt-adaptive-host-sizing-20261028.md).
> The following October 19 results were obtained using different scanner
> generations/backends and are preserved as historical evidence. Native
> 100-song 30-priority-scan and 10-policy-scan results, current host CPU
> ceiling, model/parity status, and completed CI live in the latest handover.
> Older notes such as fixed auto max=8 and "native performance unmeasured"
> must **not** be treated as current PR #18 implementation statements.

**Captured:** 2026-10-19, Europe/Vienna.
**Repository:** https://github.com/chrober/bliss-mood-poc
**Implementation baseline:** main `55b35dab1a873c3e61ecd639b7430caf0b09034c`,
including merged [PR #5](https://github.com/chrober/bliss-mood-poc/pull/5).
This document records *reported experiments*, code-verified control rules, and
hypotheses separately. Re-read current code before implementing a change.
See [chat-handover.md](chat-handover.md) for the full project handover.

> **22 October 2026 addendum:** The parallel scanner's additional
> `--tracks-file` source and optional `--embedding-dir` pooled 1280D
> export are being developed in [Draft PR #18](https://github.com/chrober/bliss-mood-poc/pull/18),
> stacked on the original Essentia-C++ backend Draft PR #17 without
> modifying either PR #17 or the separate similarity experiment PR #16.
> See [manifest-batch-adaptive-analysis.md](manifest-batch-adaptive-analysis.md)
> for the new implementation, verified synthetic ONNX results, and its
> distinct *unmeasured* production performance questions. Historical
> 2026-10-19 scanner timing figures below refer to other experiments.
>
## Objective

Make offline three-head music analysis fast, correct, incremental, and
unobtrusive on a Windows laptop while music is on a Wi-Fi/NAS share. Eventually
support optional self-tuning concurrency **without sacrificing deterministic
results or interactive system responsiveness**.

Requirements and invariants:

- Retain explicitly selected fixed `--workers N` and legacy single-worker
  behavior. `--workers auto` stays available. `--adaptive-workers` is
  **opt-in**, not the default.
- `--threads 1` is required when processing songs concurrently, avoiding
  ONNX thread oversubscription.
- One ONNX Runtime process environment, independent and reused Sessions per
  worker; one coordinator owning SQLite sidecar writes; bounded in-flight
  work and bounded file/decode buffers.
- `bliss.db` is always read-only; `TracksV2.File` is the canonical key;
  audio is never modified. No production plugin or mixer modification.
- Strict `--max-new N` attempted-track limit, `--max-errors N` failure
  limit, and unchanged model outputs (Mood/Genre/Voice).
- Real-music quality remains experimental. Numerical parity to Essentia on
  deterministic test files is required but not sufficient for production use.

## Environment and reusable local inputs

| Property | Observed |
| --- | --- |
| Machine | HP Laptop 15-fc0xxx / Windows 11 |
| Processor | AMD Ryzen 7 7730U, 8 physical / 16 logical CPUs |
| RAM | 16,474,501,120 bytes (~15.34 GiB) |
| Network | Realtek RTL8852BE-VS Wi-Fi 6, 600 Mbit/s negotiated link |
| Music UNC | `\\192.168.1.100\music` |
| Local repository | `D:\LMS\bliss-mood-poc` |
| Source library | `bliss.db`, 64,062 eligible tracks |
| Reusable fixture | `benchmark-workers-20261019-060347\sample-100.db` |
| Sample | 100 tracks, Python random.Random(20261018), SELECT sorted File keys |
| Sidecars | `features-{6,8,10,12}.db`, `adaptive-20261019-080350.db` |
| Original baselines | `summary.csv`, `summary-with-6.csv`, `resources-*.csv` |

The full fixture and results are on the user's laptop, **not** in GitHub.
GitHub's Windows artifacts change by workflow run; download the newest successful
Windows x64 binary from the current main rather than reusing an old one.

## Fixed six vs eight vs ten vs twelve

An independent PowerShell benchmark analyzed the *same 100* songs per worker
count, fresh database for each, Windows process priority BelowNormal, sampled
OS metrics. All three classification heads per song = 300 classification
vectors. All vectors compared **byte-identically** across runs.

| Workers | Duration s | Songs/min | CPU avg % | CPU max % | RAM max % | Analyzer working set GB |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 6 | 80.48 | 74.6 | 47.9 | 87 | 85.0 | 0.66 |
| 8 | 80.18 | 74.8 | 63.5 | 94 | 89.5 | 1.17 |
| 10 | 82.29 | 72.9 | 70.8 | 100 | 91.6 | 1.94 |
| 12 | 112.79 | 53.2 | 83.2 | 100 | 97.5 | 3.21 |

**Interpretation:** 6 and 8 workers are practically tied in throughput;
6 consumes much less CPU/RAM. 12 is substantially worse and close to RAM
exhaustion. Six is a *measured favorable baseline*, not proven universally
optimal. Benchmark order and OS/NAS caches can bias comparisons.

At six workers, WLAN receive mean **24.05 MiB/s**, peak **39.08 MiB/s**.
This is adapter-wide traffic, not isolated SMB traffic; it does not prove
a saturated 600-Mbit/s Wi-Fi link or isolate latency. Compare local SSD
copies of the **same** tracks before asserting a NAS bottleneck.

## Adaptive run from the other chat

[PR #5](https://github.com/chrober/bliss-mood-poc/pull/5) was merged to main
as `55b35dab1a873c3e61ecd639b7430caf0b09034c`. It adds:

- `--adaptive-workers --workers 6 --min-workers 4 --max-workers 8`
- Native resource monitor: system CPU and physical RAM on Windows/Linux
- Per-song timing instrumentation: decode/FFprobe+FFmpeg, Mel+patch,
  ONNX inference, SHA-256 audio hash, ONNX model load
- JSON `diagnostics` with load samples/aggregate, initial/final/peak
  workers, and per-change `adjustments`; stderr adjustment messages

Reported 100-song run:

| Field | Output |
| --- | ---: |
| Analyzed / errors | 100 / 0 |
| Total wall time | **120.66 s** |
| Throughput | **49.7 songs/min** |
| Initial / final / peak active workers | **6 / 6 / 6** |
| System CPU average | 51.2551% |
| System RAM maximum | 86.3289% |
| Resource samples | 38 |
| Worker adjustments | none |
| Sum decode duration | 173.52 s |
| Sum Mel preprocessing duration | 100.82 s |
| Sum ONNX duration | 343.09 s |
| Sum SHA-256 hashing duration | 66.54 s |
| Sum model-loading duration | 1.63 s |
| Sum of per-song elapsed times | 685.61 s |

Database:
`D:\LMS\bliss-mood-poc\benchmark-workers-20261019-060347\adaptive-20261019-080350.db`.

**Important:** the above stage totals are *overlapping across concurrently
running songs*; they are neither whole-scan wall time nor exclusive CPU usage.
FFmpeg decoding includes file access, SHA-256 rereads the file, so two read
phases might stress SMB/NAS. The sum ~685.61 s divided by whole-scan
120.66 s is ~5.68 concurrent song-time equivalents, **not CPU utilization**.

The adaptive run is ~50.1% longer than fixed-six baseline (120.66 vs
80.48 s), even though active workers remained six. This is **an observed
regression in the reported measurement, not yet an identified software
regression**. Compare exact input keys (same 100), cache state, process
priority, OS background load, temperature/throttling, and repeated runs.
The adaptive monitor itself may contribute some overhead, but 40 s cannot
be attributed to it without evidence. Native CPU sampling and earlier
PowerShell sampling also differ in timing/methodology.

## Actual controller code contract

`src/parallel.rs::AdaptiveWorkers::observe`:

- `high = RAM >= 88% || CPU >= 90%`.
- `low = RAM <= 79% && CPU <= 65%`.
- Requires **two consecutive high observations** to reduce by one, and
  **three consecutive low observations** to increase by one.
- Cannot adjust before **24 completed songs**; cooldown requires
  `last_change.elapsed() >= 20 s`. A change resets both streak counters.
- Remains within initial/user-selected minimum and maximum; respects
  4..8 in the example. Controller only adjusts the concurrency cap, never
  interrupts running tasks.
- A sample is collected by `ResourceMonitor::sample()` at most once
  every two seconds, **when the coordinator processes a completed song**
  (`features.rs::save_completion`). If no song completes, no sample
  or policy tick occurs. Missing OS metrics mean no adjustment.
- The current JSON records only **aggregated CPU, maximum RAM and
  adjustments**, not each raw observation or hold reason.

**Why six stayed six:** with RAM often near 85–86%, it is possible to
remain in the 79–88% neutral band. A low average CPU does not satisfy
the low rule when RAM >=79%. A maximum RAM of 86.33% is under the
RAM-high threshold; spikes of CPU >=90% would still need two consecutive
eligible observations. Therefore the observed hold is **consistent with**
the code. We cannot prove the exact decision path from only the aggregate
values; do not characterize it as a confirmed defect without raw samples.

The current CI test for adaptive scanning proves unchanged features and
that the JSON diagnostics are populated, but its 8-track audio input is
shorter than the 24-track adaptation gate. Unit tests simulate simple
high/low sequences; add integration assertions for actual resizing on
longer inputs or injectable deterministic observations.

## First experiments in the next chat

1. Fetch current `main` and re-read `src/features.rs`,
   `src/parallel.rs`, `src/resources.rs`, README and this handover.
2. Reuse **the same 100-key fixture**. Run A/B/A/B or B/A/B/A fixed-6
   vs adaptive-6 with fresh separate sidecars and same process priority.
   Capture wall time, per-stage profile for *both* modes, and raw OS
   counter time series; control background load and don't assume cached
   input fairness. Optionally include fixed-eight as reference.
3. Explain no adjustment, **rather than forcing it**: add optional
   controller-decision diagnostics at every eligible tick (elapsed time,
   completed count, load, thresholds, counters, cooldown, active/in-flight
   workers, hold/change reason). Cap log volume or write to separate JSONL
   file; never fill the output JSON unboundedly on 64k songs.
4. Verify that an adjustment to the in-flight cap actually changes dispatch
   concurrency in the production path (not only `AdaptiveWorkers` unit
   tests). Test high pressure, low pressure, deadband, missing samples,
   transient spikes, 24-song gate, >=20 s cooldown, max/min boundaries.
5. Compare NAS read/decode/hash from local SSD copy of identical inputs;
   add read-bytes, cache or SMB latency metrics **only if** they can be
   measured reliably. Network Rx adapter rate is only partial evidence.
6. Decide if the UI should offer two **distinct** policies:
   pressure-protection (react to high CPU/RAM) and
   performance-optimization (slowly test throughput and preserve headroom).
   Current code implements the former, **not** throughput-maximizing
   scheduling. Do not call it auto-optimizer without a performance-feedback
   loop and a demonstrated benefit.
7. Make changes on a separate branch/PR with CI; keep
   `--workers 1`, `--workers 6`, `--workers auto`,
   `--adaptive-workers`, model-score identity, and all read-only
   source invariants intact.

## Known user-facing pitfalls

- Earlier scanner launched independent `ort::init().build()` per
  worker, causing `only one environment is allowed per process`. Fixed
  in PR #4: one process-global ORT Environment, per-worker Sessions.
- Older scanner counted only successes for `--max-new` and could traverse
  all 64k tracks if every song failed. Fixed in PR #4: count attempts,
  bounded `--max-errors`.
- PowerShell benchmark scripts must pass the `scan-features` subcommand
  as the first analyzer argument. For `Start-Process -PassThru`, obtain
  `$null = $process.Handle` early to help reliable ExitCode retrieval.
- Do not re-use a populated SQLite sidecar for throughput comparisons:
  an incremental scan may skip songs, producing meaningless timings.
- Explicit `--workers 6` does **not** automatically set BelowNormal
  Windows process priority unless adaptive mode is also enabled; apply
  the same priority to fixed and adaptive runs in the benchmark harness.
- Do not commit personal music, detailed file listings, model weights or
  SQLite contents. The local-machine paths in this handover are setup
  examples, not real data files. Avoid exposing sensitive local details
  in additional public artifacts.


## Observability follow-up (branch `feat/scanner-observability`)

The next scanner diagnostic revision adds bounded aggregated adaptive controller
decision counters (high/low/neutral load samples, minimum-song gate, cooldown,
unchanged policy holds, increases/decreases) and actual concurrency high-water
marks (`peak_in_flight` and `peak_active_analyses`). Counters do not add
per-song arrays and do not modify worker thresholds or model semantics.
`peak_in_flight` counts dispatched but uncollected jobs;
`peak_active_analyses` counts worker threads between task receipt and
completion of song analysis (including their first ONNX session setup).
It is not CPU utilization or phase-specific concurrency.

Observed same-commit 100-song A/B runs (CI Windows binary run 39234257104):

| Run | Seconds | Decode summed s | Peak RAM % |
| --- | ---: | ---: | ---: |
| fixed-1 | 159.19 | 323.31 | 95.75 |
| adaptive-1 | 126.56 | 167.91 | 93.78 |
| fixed-2 | 121.96 | 175.94 | 87.23 |
| adaptive-2 | 128.64 | 190.84 | 89.51 |

Adaptive-1 reduced 6 to 5 workers after 24 completed songs at system
CPU 61.12%, RAM 89.92%; adaptive-2 held 6. This confirms that a real
adjustment can occur but does not establish a causal source of runtime
variance. Four runs are insufficient to assign slowdown to adaptive mode.

Next steps: CI/test validation, identical-path local test with a deliberately
selected and verified Actions binary, and controlled NAS/local-SSD comparisons.
Independent timer-driven sampling and phase-specific concurrency are not
included in this first focused observability change.


## Available-RAM diagnostics follow-up

The scanner now records `diagnostics.system_available_ram_min_mib` when
the OS reports available physical memory. The value is a minimum over existing
resource sampling points (not a process-private allocation or a paging
counter), remains optional on unsupported systems, and does **not** influence
adaptive controller decisions. This intentionally small follow-up helps
interpret observations of 90%+ system-wide RAM load; detailed process
Working Set/Private Bytes and Windows paging telemetry remain future work.


## Mandatory GitHub Actions / local testing workflow (2026-10-19)

**User preference and delivery contract for all future chats:**

1. **Never build Rust binaries on the user's Windows laptop.** Do not put
   `cargo build` or local Rust compilation in a PowerShell test script.
   Source code, unit tests, and release binaries are built and verified by
   GitHub Actions.
2. Make development changes on a feature branch and open a PR. PR events
   automatically trigger the existing **Windows x64 binary** workflow
   (workflow ID `387992797`) along with Rust checks and model parity checks.
   Do not assume that a documentation-only `main` commit also generated a
   Windows executable. Inspect the PR **head SHA** and matching Actions runs.
3. **Do not stop after reporting a queued/in-progress build.** Check the
   triggered Windows workflow to completion; verify that its conclusion is
   `success`, its head SHA matches the exact code under test, and that its
   non-expired artifact **`bliss-mood-windows-x64`** exists. Check all
   relevant Rust and model-parity workflows too. If any check fails, diagnose
   and fix first; never claim the binary is available prematurely.
4. Whenever the user is asked to run a local test, provide a **complete
   executable PowerShell script in `& { ... }` form**, containing the
   **literal, verified numeric Actions run ID** (not a placeholder, an
   automatically selected run, or instructions for the user to look it up).
   Embed the actual binary download, for example:
   `gh run download $runId --repo chrober/bliss-mood-poc --name bliss-mood-windows-x64 --dir $binDir`,
   followed by verification of `bliss-mood.exe`. Download to a run-ID-specific
   path such as `bin\windows-x64\$runId` and reuse only that matching binary.
   The script must check workflow head SHA/conclusion and fail safely if they
   do not match, use a fresh benchmark sidecar, and report useful diagnostics.
5. Preserve the user's existing setup: repo
   `D:\LMS\bliss-mood-poc`, source music `\\192.168.1.100\music`,
   stable 100-song sample
   `benchmark-workers-20261019-060347\sample-100.db`,
   `--models moodtheme,genre,voice --threads 1`. Audio files and original
   `bliss.db` are read-only. Do not commit personal media or benchmark DBs.
6. If testing code on a PR branch, don't require the user's local checkout
   to be on `main`; the binary must match the chosen PR SHA. Do not merge
   before CI and local validation where required.
7. Continue gathering evidence rather than changing worker behavior based
   solely on one timing result. Keep fixed worker modes and model-score
   identity intact.

**Previously verified example:** PR #7 Windows run `39236884182`,
artifact `bliss-mood-windows-x64`, head
`d34e2c4941d008caae089640dc4b75925da5c3e6`. PR #7 was squash-merged
into main as `8ee29972999caf1e543dbb7ce63d57868fdd16f2`.
Do **not** reuse that run ID for subsequently modified code.

## PR #9 process memory follow-up (2026-10-19)

The optional scan diagnostics now include Windows process Working Set maximum
(`process_working_set_max_mib`), process Private Bytes maximum
(`process_private_bytes_max_mib`), and the difference between first and last
sampled process PageFaultCount (`process_page_fault_delta`). These samples
occur on the existing completion-driven, two-second resource monitor cadence.
They do not alter worker policy, model inference, stored scores or upstream
media. On platforms without these Win32 counters the fields remain null.

**Interpretation:** Windows PageFaultCount includes *soft faults* and must
not be interpreted as pagefile reads, hard faults, or disk I/O. The difference
covers only the measured window, not the process's complete lifetime. Both
Working Set and Private Bytes are per-process, unlike overall RAM percentage.
To prove hard paging, collect complementary Windows Memory counters or ETW
traces in a separate, explicitly benchmarked experiment.

Follow the mandatory GitHub Actions build and fixed-run-ID PowerShell rules
above, including waiting for all checks and verifying the PR artifact.


## PR #10: Pre-worker CPU and RAM baseline

Because the test laptop often has high memory load before the Rust scan
begins, do not attribute the system's RAM peak to the analyzer without a
pre-worker baseline. The scan now records `diagnostics.baseline` before any
worker threads are spawned. It captures system RAM use and available MiB,
process Working Set and Private Bytes, plus system-wide CPU use averaged
over a **measured one-second pre-worker interval**. There is no meaningful
instantaneous CPU utilization reading from cumulative OS CPU counters.

The pre-worker snapshot is taken after `bliss.db` input and SQLite sidecar
setup. It is therefore not a pre-process or fully idle desktop snapshot.
The CPU baseline adds roughly one second to the wall-clock scan runtime
but does not affect adaptive controller observations, thresholds, worker
scheduling, fixed worker modes, or ONNX inference output. Existing
post-start CPU/RAM averages and peaks continue to cover the established
completion-driven sampling window; do not conflate the two windows.

Fields: `diagnostics.baseline.system_cpu_percent`,
`diagnostics.baseline.cpu_measurement_seconds`,
`diagnostics.baseline.system_ram_percent`,
`diagnostics.baseline.system_available_ram_mib`,
`diagnostics.baseline.process_working_set_mib`,
`diagnostics.baseline.process_private_bytes_mib`.
Compare baseline with scan maxima and minima without treating values
at different instants as a simultaneous resource snapshot.

The previous Windows local test for PR #9 (`39240876213`) reported
100 analyzed, 172.41 seconds, RAM max 95.84%, available min 653 MiB,
process WS max 1128 MiB, Private Bytes max 1190 MiB, CPU avg 43.59%,
and 0 adjustments (6 final workers). PR #9 merged into `main` as
`7783a485e38e608d1dde59d14869c2015082cb25`.

Follow the mandatory GitHub Actions CI artifact and exact-run-ID
PowerShell test script process described in the chat handover.
