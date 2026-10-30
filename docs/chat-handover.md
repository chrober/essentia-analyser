# Chat handover — adaptive offline feature scans (2026-10-19)

> **Static scanner integration supersedes historical adaptive plans (28 Oct 2026):** New code path [PR #20](https://github.com/chrober/bliss-mood-poc/pull/20) carries verified native Essentia C++ and manifest/1280D embedding analysis without runtime worker resizing. `--workers 1` remains default, `--workers auto` is one-time conservative CPU sizing. Former dynamic/adaptive implementation and four real-music benchmark campaigns remain *research* in [PR #19](https://github.com/chrober/bliss-mood-poc/pull/19). Consult [final architecture](multi-worker-song-analysis-final.md) and [Similarity handback](handback-multi-worker-to-similarity-20261028.md) for the actual production target. Legacy instructions below may be invalid for the static CLI.


> **CURRENT 28 OCTOBER 2026 HANDOVER:** Start with
> [handover-adaptive-host-sizing-20261028.md](handover-adaptive-host-sizing-20261028.md)
> and [its copy-paste prompt](handover-prompt-adaptive-host-sizing-20261028.md).
> This file is a **historical** account of older PR #5 / October 19
> experiments. The current PR #18 includes real 30-scan Windows priority
> and 10-scan native adaptive-gate experiments, and system-dependent
> `--max-workers auto` in place of the historical default eight.
> Re-check the PR head and CI, do **not** treat older fixed/auto defaults
> and open investigations below as current facts.

> **Purpose:** Start a new development chat without losing the current project
> state. The detailed performance experiment, raw benchmark measurements,
> implementation details and open questions are in
> [adaptive-scan-performance-handover.md](adaptive-scan-performance-handover.md).
>
> **Source of truth:** Always re-check current GitHub `main` before making
> claims or changing code. This handover was prepared against
> `55b35dab1a873c3e61ecd639b7430caf0b09034c` (PR #5 merged), before the
> documentation-only handover PR. Do not assume that SHA is still the latest.

> **22 October 2026 addendum — active adaptive batch workstream:** This document is a
> historical account of main / PR #5. The current implementation branch is
> [feat/manifest-batch-adaptive-worker-analysis](https://github.com/chrober/bliss-mood-poc/tree/feat/manifest-batch-adaptive-worker-analysis),
> tracked in [Draft PR #18](https://github.com/chrober/bliss-mood-poc/pull/18),
> **stacked on PR #17 rather than main**. It adds a manifest-based batch
> scanner and opt-in pooled 1280D song embedding export using the original
> bounded parallel/adaptive Rust worker scheduler. Read
> [manifest-batch-adaptive-analysis.md](manifest-batch-adaptive-analysis.md)
> for architecture, CLI examples, synthetic ONNX parity/Resume CI and open
> performance, atomic-file and licensing restrictions. The independent PR #16
> similarity workstream is unchanged. Do not treat the new experimental CLI
> as a released production interface.
>
## Project and boundaries

Repository: [chrober/bliss-mood-poc](https://github.com/chrober/bliss-mood-poc).
Experimental Rust/ONNX offline audio analysis to complement Lyrion/Bliss,
**not** an instruction to change production mixers, plugins or Bliss Guidance
SPI. The generic CLI handles **three independent heads** sharing one
Discogs-EffNet embedding per song:

- `moodtheme` — 56-label MTG-Jamendo Mood/Theme (Sigmoid).
- `genre` — 87-label MTG-Jamendo Genre (Sigmoid).
- `voice` — Voice/Instrumental, 2 labels (Softmax). Not vocal-technique or
  percentage-of-vocal-time detection.

Original `bliss.db` and audio are read-only. Experimental results live in a
separate SQLite sidecar, schema v3, keyed by exact `TracksV2.File` identity.
Old Mood-only CLI and legacy rows remain untouched. Real-world prediction
quality is **not** production-validated; verified synthetic Essentia numerical
parity is not evidence of musical usefulness. See
[feature-provider-architecture.md](feature-provider-architecture.md) and
[offline-mood-database.md](offline-mood-database.md).

## What has shipped

1. Generic Mood + Genre + Voice analysis, shared encoder, model registry,
   per-head caching and validated numerical parity.
2. Incremental `scan-features` with bounded, parallel *songs*, independent
   per-worker ONNX Sessions and a single transaction-safe SQLite writer.
3. Corrected ONNX Runtime process-global Environment (earlier concurrent
   `ort::init().build()` attempts failed on Windows).
4. `--max-new N` means **at most N newly attempted tracks**, not N
   successes; `--max-errors N` aborts repeatedly failing scans.
5. `--workers auto` keeps Windows responsive (roughly 25% CPU headroom,
   cap eight), `--workers N` is explicit; for parallel use `--threads 1`.
6. [PR #5](https://github.com/chrober/bliss-mood-poc/pull/5), merged:
   opt-in `--adaptive-workers` with `--workers 6 --min-workers 4
   --max-workers 8`; per-song decode/preprocessing/inference/hash/load
   stage totals; OS CPU/RAM monitoring; logged worker adjustments.
   The fixed-worker interface remains available and unchanged.

Important source entry points:

- `src/features.rs`: `FeatureEngine`, `scan_parallel`,
  `save_completion`, `ScanSummary`, `ScanDiagnostics`.
- `src/parallel.rs`: `worker_count`, `AdaptiveWorkers::observe`.
- `src/resources.rs`: OS-level load sampling.
- `src/main.rs`: CLI flags and validation.
- `src/storage.rs`: read-only upstream Bliss access and SQLite sidecar.
- `model-registry.json` and
  `.github/workflows/voice-parity.yml`: model contract and integration tests.
- `README.md`: usage and caveats.

## Real test setup

User machine: Windows 11, HP Laptop 15-fc0xxx, AMD Ryzen 7 7730U,
8 physical cores / 16 logical CPUs, ~16 GB physical RAM; Wi-Fi 6 Realtek
RTL8852BE-VS at negotiated 600 Mbit/s. Music on NAS UNC share
`\\192.168.1.100\music`, local checkout
`D:\LMS\bliss-mood-poc`, 64,062 eligible Bliss tracks.

Deterministic local 100-song fixture:
`D:\LMS\bliss-mood-poc\benchmark-workers-20261019-060347\sample-100.db`
(seed 20261018). Benchmark sidecars:
`features-6.db`, `features-8.db`, `features-10.db`,
`features-12.db`; raw samples `resources-*.csv`, `summary.csv`
and `summary-with-6.csv`. Keep this suite for apples-to-apples work;
do **not** upload personal music or database to GitHub.

**Fixed-worker results over the same 100 tracks**:

| Workers | Wall time | Songs/min | System CPU avg | RAM max | Analyzer RAM max |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 6 | 80.48 s | 74.6 | 47.9% | 85.0% | 0.66 GB |
| 8 | 80.18 s | 74.8 | 63.5% | 89.5% | 1.17 GB |
| 10 | 82.29 s | 72.9 | 70.8% | 91.6% | 1.94 GB |
| 12 | 112.79 s | 53.2 | 83.2% | 97.5% | 3.21 GB |

All 300 model vectors per run were **byte-identical**. With six workers:
CPU max 87%, WLAN receive mean 24.05 MiB/s, max 39.08 MiB/s. Six fixed
workers are the measured efficiency baseline; eight have similar throughput
at much higher resource pressure.

**First adaptive run**, reported after PR #5 from a database within the
same benchmark directory:
`adaptive-20261019-080350.db`; 100/100 successful, zero failures,
**120.66 s (49.7 songs/min)**; workers initial/final/max **6/6/6**,
CPU avg 51.26%, peak RAM 86.33%, 38 OS-load samples, **no adjustments**.
Per-song *summed overlapping* durations: decoding 173.52 s, Mel/patches
100.82 s, ONNX 343.09 s, SHA-256 reread 66.54 s, session init 1.63 s,
sum of song durations 685.61 s. These are NOT sequential wall-clock or
exclusive CPU durations.

The adaptive controller's low-load rule is **CPU <=65% AND RAM <=79%
for 3 consecutive resource observations**. High-load rule is **CPU >=90%
OR RAM >=88% for 2 consecutive observations**. Changes are inhibited
until >=24 completed songs and at least 20 s since the last adjustment
(or creation). The observed near-86% RAM can sit in the deadband for the
entire run. Therefore **no worker change is not proof of a bug**. The
report shows only maximum RAM, not every sample: inspect actual timelines
and effective conditions before concluding why no adjustment occurred.
Whether the ~50% longer adaptive runtime is reproducible, and whether
the command truly used an identical track set/cache/priority, remain OPEN.

## Next work — priority order

1. **Investigate the adaptive performance regression** on exactly the
   existing `sample-100.db` and music source. Compare fixed six vs adaptive
   six under equivalent environment and process priority; alternate run
   order/repeat measurements, inspect NAS/OS caching, thermal/power throttling,
   and runtime phases. Do not conclude adaptive scheduling is at fault merely
   because of one timing difference.
2. **Make decisions explainable**: record per-resource sample time, CPU/RAM,
   consecutive low/high counters, cooldown, controller state, real in-flight
   count and why it held or changed. Check for starvation caused by samples
   only being taken when job results arrive.
3. **Evaluate safe policy options**, with tests: explicit pressure-only guard
   (reduce at high RAM/CPU), separate throughput-seeking tuning policy, or
   thresholds based on available memory + CPU/queue throughput rather than
   CPU/RAM fixed cutoffs alone. A correct policy may intentionally stay at six.
   Do not blindly force an adjustment.
4. **Measure NAS versus local SSD** on identical files with controlled
   cache state; distinguish SMB latency, network throughput and CPU
   preprocessing/inference. File hashing reads the source twice overall.
5. Regression CI: deterministic simulated resource timelines (high, low,
   deadband, missing samples, cooldown); verify real in-flight changes,
   maximum attempts, error stop and byte-identical feature vectors.
6. Only after evidence, optimize the controller and maybe expose explicit
   `--max-workers` defaults; keep fixed-worker behavior stable. Later:
   full-library progress/ETA and resumable/interruptible UX.

## Rules for the next chat

- Fetch fresh `main` SHA and review these docs + source **first**.
- Diagnose rather than assert adaptive is broken: 6/6/6 can be correct.
- Prefer a reproducible minimal PR; run Rust tests, Clippy, Windows x64,
  and required Essentia/model parity before merge.
- No production mixer/plugin changes. Keep `bliss.db`/music read-only;
  new SQLite benchmark DBs only; never commit music, model weights,
  local sidecar DBs or personal track lists.
- Always bound experiments: `--max-new`, `--max-errors`, timeouts;
  `--threads 1` when parallel. Retain `--workers N` and
  `--adaptive-workers` as optional.
- The user prefers actionable full PowerShell blocks (`& { ... }`) and
  measured evidence over speculative optimizations.


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


## PR #10 pre-worker baseline measurement (2026-10-19)

**New benchmark requirement:** capture and report the system's RAM **and CPU
baseline before any scanner worker starts**, plus available physical RAM
and analyzer process Working Set and Private Bytes. For CPU, a single
instantaneous OS counter is meaningless: use a **one-second interval** before
workers are spawned, and expose the actual elapsed measurement window.
Do **not** feed this baseline into the adaptive worker controller or
normal runtime samples. On Linux and Windows this is measured at the start of
the parallel scan, after opening the input and sidecar DB and before
creating ONNX worker sessions. The one-second baseline measurement is
included in wall-clock scan elapsed time.

The JSON location is `diagnostics.baseline`:
`system_cpu_percent`, `cpu_measurement_seconds`,
`system_ram_percent`, `system_available_ram_mib`,
`process_working_set_mib`, `process_private_bytes_mib`.
These baseline values reflect **pre-worker** machine load, not a completely
idle Windows system before the application was launched. Compare changes
with runtime extrema; extrema can occur at different instants and do not
prove the analyzer was the cause of overall RAM pressure.

Use the mandatory PR-triggered GitHub Actions Windows artifact workflow
and exact-run PowerShell download rules documented above; never suggest
local cargo builds.


## Current product priority: Bliss + Mood/Genre Lyrion integration (2026-10-19)

**Read [lyrion-bliss-mood-genre-integration.md](lyrion-bliss-mood-genre-integration.md) before new product changes.** The immediate engineering task is F1: reliable exact `TracksV2.File` joining and read-only model-provenance-aware Mood/Genre SQLite retrieval for a bounded Bliss/Lyrion candidate set. The first strategy is **Bliss-first with optional Mood/Genre reranking in BlissMixerLab** through guidance SPI v2, with hard eligibility and original Bliss untouched, separate per-head influence, experimental preview opt-in and neutral fallback. Current provider host transmits candidate IDs/urlmd5, but exact file keys are not yet guaranteed; do not silently join by title/artist. Do not enable stored unvalidated model scores for production playlist generation by default.

The cross-platform worker and Raspberry Pi runtime/resource strategy is **deferred**, documented in [platform-resource-roadmap.md](platform-resource-roadmap.md). The user explicitly does not want tuning for one benchmark laptop; development focus now is meaningful playlist fusion, not scanner performance.

## Three-way mixing decision and local workfiles (2026-10-19)

The mixing architecture remains **undecided** between **Bliss-first**,
**Mood-/Genre-first**, and **Hybrid**. The first integration vertical slice
uses Bliss-first because the existing SPI v2 can already rerank a Bliss
candidate pool, **not** because Bliss-first has won a listening/coverage
comparison. All three must be compared on equivalent seeds, constraints,
coverage, transition quality, drift/diversity and Pi budgets before choosing.
See [lyrion-bliss-mood-genre-integration.md](lyrion-bliss-mood-genre-integration.md).

Root-level `benchmark-*/`, `bin/`, local `mood-full.json` and
`mood-quality-*.csv` are excluded by `.gitignore`; keep personal
music paths/analysis outputs out of commits. Do **not** ignore
`Cargo.lock`: this binary application's dependency lockfile should
be separately versioned once. Git status will continue showing it as
untracked until added/committed.
