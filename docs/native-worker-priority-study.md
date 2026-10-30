# Windows scanner / original Essentia C++ worker priority control

**Status:** implemented in draft PR #18. The first verified exact Windows
priority build completed on an earlier source commit. For the current
October 28 code baseline and its green checks, plus **measured** results,
see [current host-sizing handover](handover-adaptive-host-sizing-20261028.md).
Do not reuse a Windows artifact from a mismatched code commit.
The original qualification policy still requires the green CI
checks **for the code being tested** and a matching Windows x64 artifact. This change does
not alter the class/mood/voice model weights, feature computation, original
Essentia C++ backend, existing song files or Bliss database.

## Prior measured confound: 27 October 2026, real 100-song NAS cohort

A controlled, bounded local 100-song native C++ benchmark completed two
repetitions of fixed 1/2/4/6 and adaptive 2–6 worker configurations. The local
report asserted **exact classification byte equality for all 300
song/head entries and complete 1280D embeddings**, with no failed scans.
Only aggregate statistics are retained below; private paths/song identities,
individual music files and private scanner logs are **not** committed.

| Mode | 2-run median wall seconds | 2-run median songs/min | Peak private process-tree MiB |
| --- | ---: | ---: | ---: |
| fixed 1 | 282.126 | 21.276 | not sampled in serial |
| fixed 2 | 277.649 | 21.950 | 226.922 |
| fixed 4 | 110.803 | 54.581 | 419.023 |
| fixed 6 | **93.417** | **65.144** | 657.281 |
| adaptive 2–6 | 116.852 | 51.367 | 552.539 |

Adaptive mode increased from **2 → 6 workers** through **four
adjustments per run**. The lower CPU utilization is not directly evidence
of Windows scheduler throttling: six parallel single-threaded inference jobs
cannot automatically saturate 16 logical CPUs; the pipeline also reads
music over the NAS, preprocesses audio and hashes files. A 20-second
controller cooldown and 24-completion minimum gate reduce early worker
admission. The two-run wall time is not enough to isolate those effects.

**Critical experimental confound:** previously `src/main.rs` lowered
Windows process priority to `BelowNormal` whenever `--workers auto` or
`--adaptive-workers` was enabled. Fixed numeric worker counts kept the
OS-assigned priority (normally `Normal`). Original Essentia subprocesses
are spawned without explicit priority flags, so Windows normally inherits
the parent's priority class. Earlier fixed/adaptive throughput numbers
therefore **do not isolate the adaptive controller**.

## New CLI behavior

`scan-features --priority below-normal|normal|above-normal` sets the **Windows process
priority class** independent of `--workers`, `--workers auto` and
`--adaptive-workers`. The flag is **optional** and does not alter existing
behavior when omitted:

| Priority flag | Numeric fixed N | Auto or adaptive |
| --- | --- | --- |
| Omitted | Do not override OS-assigned class | Request `BelowNormal` (legacy) |
| `--priority normal` | Explicitly set `Normal` | Explicitly set `Normal` |
| `--priority below-normal` | Explicitly set `BelowNormal` | Explicitly set `BelowNormal` |
| `--priority above-normal` | Explicitly set `AboveNormal` | Explicitly set `AboveNormal` |

On **non-Windows platforms**, explicitly specifying `--priority` fails
with a clear error: mapping the Windows-specific priority class to POSIX
`nice` levels without an equivalent scheduling guarantee would be
misleading. Omitting it preserves the existing Linux/macOS behavior.
Dry-run does not modify the current process's priority.

Explicit Windows priority selection fails if `SetPriorityClass` fails
or if `GetPriorityClass` does not report the requested class. This is a
fail-closed experimental control; legacy implicit background priority
still warns on failure rather than silently changing the legacy exit
contract.

## Diagnostic contract

The `scan-features --json` output now contains a `priority` object
**also for a one-worker serial scan**, whose structure is:

```json
{
  "priority": {
    "requested": "normal",
    "policy": "normal",
    "effective_scanner": "normal",
    "native_worker_classes": ["normal"],
    "native_worker_observation_failures": 0
  }
}
```

`effective_scanner` is an actual Win32 `GetPriorityClass` reading,
not inferred from CLI arguments. The scanner reads `GetPriorityClass`
from each **original Essentia C++ child process handle immediately after
spawn**, stores its distinct observed classes, and reports the number
of failed queries. All launched children are included even if they exit
before the final scanner summary. For all three explicitly selected priorities, the scanner passes the requested
class as a Windows `CreateProcess` creation flag; relying on implicit
inheritance would be incorrect for `AboveNormal`. The scanner verifies the
child process class immediately after spawning it, before handling a song,
and terminates a mismatched child. For the omitted priority option, it
does not set creation flags, retaining the legacy scheduling behavior.
An empty child array is expected
for the Rust audio backend or a scan with no new songs, but **is not**
accepted by the strict native benchmark. No child priority is guessed
from the parent's priority.

This is an OS process **scheduling priority**, *not* a CPU quota or an
affinity setting. It may affect latency under contention, but it
cannot be equated directly with the aggregate CPU utilization metric.

## Next comparison gate

`scripts/benchmark_native_adaptive_manifest.py` now passes
`--priority normal` by default to **every** fixed and adaptive scan.
It rejects any run for which `priority.effective_scanner` or the real
observed native child class is not exactly `normal`, and records
priority alongside timing and memory metrics in local `summary.json` /
`runs.csv`. Users can select `--scan-priority below-normal` or
`--scan-priority above-normal` to compare at an independently controlled
priority, but **never mix two priorities within the same five-mode
fixed/adaptive experiment**.

The original 100-song private sample, official model files, native
worker and verified new Windows scanner artifact are reused.
The benchmark requires a *fresh, empty* output directory, does not
overwrite the original source DB or songs, and does not upload them.

Regression gates:

1. Rust CLI accepts valid explicit values independently of adaptive
   settings and rejects unrecognized or unsafe values.
2. Production priority resolution preserves the omitted-flag legacy
   policy on all platforms.
3. Windows native unit test sets all three classes in a separate test process,
   launches an actual Win32 child and queries its **actual** priority
   to test inheritance. It does not alter priority in the parent CI
   test harness shared by other tests.
4. Python benchmark tests enforce `--priority` in every scanner command
   and reject mismatched/unobserved native worker priority.

This change alone **does not** prove priority is responsible for the
previous performance difference. Confirm the new scanner CI artifact
and reproduce the bounded local comparison before drawing that
conclusion.

## Controlled start-worker vs song-gate experiment (28 October 2026)

The production controller now supports **opt-in**
`scan-features --adaptive-min-completed-songs 8` (requires
`--adaptive-workers`). If omitted, the existing minimum **24 completed
songs** and **20-second cooldown** remain unchanged. CPU/RAM load
thresholds, hysteresis (three low-load samples to increase, two high-load
samples to reduce), one-worker-per-decision changes, model output, and
native C++ backend all remain unchanged. The gate applies equally to
**increases and decreases**; this experiment does not establish an
independent emergency downscaling policy.

A new `--experiment adaptive-policy` switch in
`scripts/benchmark_native_adaptive_manifest.py` runs five configurations,
with the same existing seed-balanced reversed round ordering and exact
per-head classification/1280D pooled embedding parity requirements:

| Mode | Initial workers | Min–max | Minimum completed songs |
| --- | ---: | --- | ---: |
| `fixed6` | 6 | fixed | — |
| `adaptive2_gate24` | 2 | 2–6 | 24 |
| `adaptive4_gate24` | 4 | 2–6 | 24 |
| `adaptive6_gate24` | 6 | 2–6 | 24 |
| `adaptive2_gate8` | 2 | 2–6 | 8 |

The previous `adaptive2` baseline had **minimum 1**, not 2. This
new experiment intentionally uses **minimum 2** uniformly for the four
adaptive policy configurations; interpret previous baseline comparisons
accordingly. Fixed 6 and Adaptive Start 6 are not guaranteed identical
because the adaptive controller is still allowed to **downscale** if it
observes sustained resource pressure.

Run the original benchmark command with
`--experiment adaptive-policy --scan-priority normal --repeats 2`, using
a **new, empty output directory** and the latest verified Windows x64
scanner artifact. Each run verifies the actual effective scanner and
native child process priority. An explicit per-run JSON field
`diagnostics.adaptive_min_completed_songs` confirms the production gate;
`runs.csv` additionally records the first resize position, all resize
positions and controller hold counters.

**This only makes the controlled experiment reproducible.** No new real-
music NAS performance results have been measured by CI. Changes to the
Windows process priority *during* a scan are **not** implemented and must
not be mixed into the policy experiment. A future independent study might
measure process-tree CPU entitlement, competing foreground latency and
throughput before considering a hysteretic priority governor.

## Host-dependent worker ceiling (28 October 2026)

The default `--max-workers auto` now resolves from
`std::thread::available_parallelism()` (logical CPUs available to the
**process**, including affinity/container restrictions), capped by the
existing 64-worker technical maximum. For example, a Raspberry Pi 4B
with four permitted CPUs has a maximum of **4** and a 16-logical-CPU
Ryzen has a maximum of **16**. These are hardware ceilings, **not**
measurements of optimal song throughput.

The existing `--workers auto` initial-sizing formula is unchanged:
reserve the larger of two CPUs or one-quarter of CPU capacity, and cap
the initial worker count at eight. On a 4-CPU host the initial count is
**2** with max **4**; on a 16-CPU host initial **8** with max **16**.
The adaptive `--min-workers` default is now **1** (previously 4),
allowing `--workers auto --adaptive-workers` on smaller devices.
Explicit `--workers N` or `--max-workers N` exceeding the permitted
CPU count fail with an error rather than silently clamping. The
`--max-workers` option only governs adaptive pool limits, while
`--workers` sets the initial or fixed count.

Parallel scan JSON diagnostics include `logical_cpu_capacity` and
`configured_max_workers` (actual allocated pool size, also bounded
by the cohort size). The CPU count does not constitute a RAM budget:
available memory, model sessions and native process overhead remain
resource constraints to validate independently. In particular, old
fixed-six research cohorts are intentionally not valid benchmark
configurations on a four-CPU Raspberry Pi.

The historical Windows 100-song performance results remain unchanged.
New host-dependent settings require a new matching Windows binary;
do not reuse pre-change artifacts for auto max-worker experiments.

## Subsequent completed controls (28 October 2026)

The originally proposed priority matrix **has now been measured locally**:
30 real-music scans on the same 100-song cohort, three priorities, five
fixed/adaptive worker configurations, twice each, with exact classifier
and 1280D embedding parity and actual scanner/native child priority
verification. The results show no convincing speedup from `AboveNormal`
under these conditions. For complete medians, methodology and caveats,
refer to [current handover](handover-adaptive-host-sizing-20261028.md).

A separate 10-scan adaptive-start/gate experiment found that moving
the start from 2 to 4 or 6 improved wall time more than changing the
song gate from 24 to 8; however, all adaptive modes were capped at six
and every growing mode reached six. This **does not** establish six
as the performance optimum. The next step is controlled native C++
fixed 6/8/10/12 scaling, while host-dependent CPU capacity is an
upper safety bound and actual memory cost remains to be validated.
