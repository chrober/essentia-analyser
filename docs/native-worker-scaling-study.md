# Native Essentia C++ fixed-worker scaling (Phase A, 28 October 2026)

**Status:** eight local real-music native C++ fixed-worker scans have now completed with exact three-head/embedding parity and without RAM safety abort (28 October 2026); the benchmark implementation remains on draft [PR #18](https://github.com/chrober/bliss-mood-poc/pull/18). Do not reuse old Rust-backend 6/8/10/12 timing as evidence for original C++.

## Objective and boundaries

Find the best effective song throughput subject to **RAM safety**, not simply the highest CPU utilization. Reuse the existing private 100-song `TracksV2` sample, unchanged Mood/Theme, Genre and Voice official ONNX models, the *same* original native Essentia C++ worker and Windows priority `Normal`. This experiment does not modify the production adaptive controller, PR #16, native worker code, personal music, source Bliss database or model weights.

The implementation extends **`scripts/benchmark_native_adaptive_manifest.py`** with `--experiment native-scaling`. Existing `baseline` and `adaptive-policy` experiments keep their five existing configurations and controller settings.

| Mode | Workers | Repeats | Scheduling |
| --- | ---: | ---: | --- |
| fixed6 | 6 | 2 | fixed, no adaptive controller |
| fixed8 | 8 | 2 | fixed, no adaptive controller |
| fixed10 | 10 | 2 | fixed, no adaptive controller |
| fixed12 | 12 | 2 | fixed, no adaptive controller |

A seeded shuffle determines the first four run positions; the second four **reverse** that exact sequence. Each of the eight runs uses a fresh SQLite classification sidecar and independent pooled-embedding directory. No cache warm-start from a previous run is allowed. Exact three-head float32 blob equality and 1280D embedding equality against the first completed run remain **mandatory**; model fingerprints must also match. `summary.json` contains the runs and per-mode medians; `runs.csv` is refreshed after each successful run so that partial evidence is retained if a later run is safety-aborted.

## RAM safety and limitations

`--max-system-ram-percent 90` and `--min-available-ram-mib 1536` are conservative **defaults**, not a universal per-host worker budget. The benchmark reads `GlobalMemoryStatusEx` before starting and approximately every second while the scanner is running. The first threshold reached aborts the benchmark and invokes Windows `taskkill /T /F` to end the scanner **and its native child processes**. Missing or invalid Windows RAM telemetry fails closed. Before the eight runs, the script also checks that the Windows machine reports at least 12 logical CPUs; the scanner independently enforces its allowed-CPU cap and reports that actual capacity.

This is an experiment safety stop, **not** an implementation of memory-aware adaptive worker downscaling. An in-progress file decode/ONNX allocation may exceed the reserve between one-second samples; the guard is not an absolute OOM guarantee. The sample is acquired independently of the scanner's two-second/completion-driven internal metrics. A safety stop invalidates the current comparison; do not interpret a partial ranking as proving the optimal count or bypass the memory gate merely to force completion. Keep other high-RAM applications closed, prevent sleep/power-throttling and note unusually heavy NAS or background activity. Small-memory Raspberry Pis must not run this 6–12-worker experiment.

## Collected evidence and its interpretation

Each run records: full wall time and songs/minute, preworker CPU-baseline seconds, scanner CPU mean/maximum, system RAM peak and minimum available physical RAM, **guard-observed** minimum free physical RAM, Rust-process private-memory high water, child-process private-memory high water, process-tree private and working-set peaks, missing child-process samples, peak active analyses, native child-process count, final fixed workers, and native stage totals (decoding, preprocessing, inference, hashing and model loading) where provided by the scanner.

Stage totals add across **concurrent songs**, so they do not sum to wall clock or exclusive CPU utilization. Process-tree working set can double-count shared pages. Resource and allocation samples do not necessarily catch momentary peaks. A pair of repetitions provides a directional comparison, not a robust confidence interval or a universal hardware default.

Safety and correctness controls: selected manifest paths validated against the source root (including symlink containment); original 30–500-track bounded source DB checked for hash stability; original source audio and models never opened for writing; executable and model hashes logged; original sample DB hashes verified after the benchmark; `--threads 1`, `--max-new 100`, `--max-errors 1`, exact observed scanner/child priority classes all set to `normal`; no scans of the entire library, no upload/commit of private manifests, embeddings, sidecars or raw outputs.

## Phase A measured results — 8 real-music Windows/NAS scans (28 October 2026)

**Evidence boundary:** User-supplied private local `summary.json` and `runs.csv` were compared: exactly eight same-order records, four fixed configurations × two reverse-balanced repetitions, 100 songs per scan, the same three official ONNX heads, `Normal` observed scanner and native-child priority, and `exact_numeric_parity=true`. These two result files remain **private**; do not commit the raw reports, selected track manifest, SQLite sidecars, models, song identities or embeddings. Source SHA256 identifiers are retained in the private experiment manifest rather than this public Markdown. No new real-song analysis was performed remotely.

| Native workers | Median wall seconds | Median songs/min | Median system CPU average | Peak system RAM | Peak process-tree private MiB | Minimum guard-observed available MiB |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 6 | 84.558 | 70.980 | 34.25% | 73.64% | 612.02 | 4091.86 |
| 8 | 85.562 | 70.416 | 40.74% | 75.61% | 876.07 | 3833.38 |
| 10 | 94.127 | 63.750 | 62.45% | 76.39% | 989.58 | 3686.47 |
| **12** | **68.069** | **88.166** | **58.00%** | **76.42%** | **1127.44** | **3679.19** |

*Column semantics:* median wall/songs-min/CPU across two independent runs; system RAM, process-tree private MiB are **maxima** across both; available RAM is the **minimum** from the independent one-second watchdog. Peak samples are high-water observations, not hard OS-guaranteed allocation maxima. No safety stop was triggered; all native child counts and peak active analyses reached the requested fixed worker count, and process-tree incomplete-sample counts were zero.

**Observed finding:** Of the tested counts, **12 workers were fastest in both repetitions**, with a 19.5% shorter median whole-run wall time and **24.2% more songs/min** than fixed 6. The two twelve-worker wall times differed by only about two seconds. The observed peak private process-tree footprint increased by **515 MiB** vs six workers, but the worst observed twelve-worker free physical RAM was **3679 MiB**, safely above the experiment's 1536 MiB floor. This establishes feasibility on this specific host/sample, **not** an always-safe worker count for other workloads or hardware.

**Non-monotonicity / investigation needed:** fixed 10 took 11.3% longer than fixed 6 on median, whereas fixed 12 was fastest. Ten workers also had a higher median sampled average system CPU load (62.45%) than twelve (58.00%). The slow ten-worker scans showed much larger cumulative inference-stage elapsed seconds than six or twelve; these are sums of overlapping per-song durations, **not** exclusive CPU work or a diagnosis. Eight-worker repeat wall times differed by about eleven seconds, showing material ambient variability. Potential sources include shared NAS/I/O and cache, thermal/power scheduling, OS contention, and differing concurrent model/session bottlenecks, **none established as the cause**.

**Decision:** Do **not** configure 12 as a universal adaptive default yet and do **not** interpret 10-worker degradation as evidence of an intrinsic forbidden worker count. The tested upper bound was 12, below the Ryzen's 16 logical CPUs. Before choosing a throughput-optimizing controller target, extend a *separate* bounded and reverse-balanced fixed-worker experiment to 14/16, remeasure 10 and 12 as controls with more repetitions, retain the RAM watchdog and parity gates, and consider cold/warm NAS cache and power/thermal observability. If additional runs cannot be justified, twelve is the **current best measured candidate** for this machine only. For Phase B, design **RAM safety as a hard independent admission constraint** and throughput-based exploration as a secondary, hysteretic mechanism; the present CPU-only host ceiling is insufficient for 4-GB Raspberry Pi hardware.

## Windows prerequisites and execution

Run from a clean checkout/worktree of **the exact PR #18 source head** and only after matching GitHub Actions Rust checks, Windows x64 binary, native Essentia codec/model and genre/voice parity checks are green. The Windows analyzer is downloaded from the matching successful **Windows x64 binary** workflow artifact `bliss-mood-windows-x64` and must have `BUILD.txt` linking it to the exact source commit plus verified `SHA256SUMS.txt`. The original native C++ worker is **not** currently distributed as a new public ZIP; reuse your previously installed, locally verified development worker directory (including matching DLLs and native manifest) and keep it intact. ONNX weights/JSON files remain privately provisioned; FFmpeg/ffprobe must be on PATH. Never compile Rust locally on Windows.

With preverified local prerequisites (full setup and pinned Actions run ID will be provided only after actual CI qualification):

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location 'D:\LMS\bliss-mood-poc'
    $results = Join-Path (Get-Location) ('benchmark-native-scaling-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    if (Test-Path $results) { throw 'Result directory already exists' }
    $args = @(
        'scripts/benchmark_native_adaptive_manifest.py',
        '--experiment', 'native-scaling', '--cohort-db', 'benchmark-workers-20261019-060347/sample-100.db',
        '--expected-tracks', '100',
        '--analyzer', 'bin/bliss-mood.exe',
        '--essentia-worker', 'D:\LMS\essentia-cli-test\essentia-worker\bliss-essentia-worker.exe',
        '--models-dir', 'models', '--source-root', '\\192.168.1.100\music',
        '--output-dir', $results, '--models', 'moodtheme,genre,voice',
        '--scan-priority', 'normal', '--repeats', '2', '--seed', '20261028',
        '--min-available-ram-mib', '1536', '--max-system-ram-percent', '90'
    )
    py -3 @args
    if ($LASTEXITCODE -ne 0) { throw 'Benchmark stopped or exact parity failed; inspect private output' }
    Get-Content (Join-Path $results 'summary.json')
}
```

If `TracksV2.File` keys are absolute instead of relative, supply `--library-root` with the **original path prefix** matching the stored DB keys. The experiment does not remap media on its own. Use a completely new output directory for every attempt. `--plan-only` validates all sampled paths and the run matrix without writing output. Python 3.10+ is required for `Path.is_relative_to` and modern typing.

## Exit criteria and Phase B handoff

1. Exact committed source head matches the Windows analyzer artifact, tested native worker and model/fixture hashes recorded in private `experiment.json`.
2. All eight runs complete with exact head/embedding parity and no RAM safety stop. If 10/12 is unsafe, document the last **safely completed** configuration and memory evidence rather than forcing eight runs.
3. Present median wall/songs-min **alongside** highest RAM/process-tree consumption, repeat variability and concurrent native count; explicitly distinguish scanner telemetry from independent RAM guard samples.
4. Then decide whether to investigate another count (e.g. 7/9), revise the RAM-safe ceiling, or advance Phase B (start sizing, throughput feedback, fast pressure reduction and hysteresis). Avoid claiming that a single Ryzen/NAS optimum generalizes to Pi 4B or other systems.

The eight-scan Phase A benchmark now has real local measurements; see the aggregated findings above. Its results do **not** yet establish the optimal worker count beyond the measured maximum of twelve or a transferable default for other hosts.
