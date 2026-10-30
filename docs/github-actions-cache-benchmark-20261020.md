# GitHub Actions cache & Cargo.lock benchmark — 2026-10-20

> **Scope:** Draft [PR #17](https://github.com/chrober/bliss-mood-poc/pull/17)
> (`feat/essentia-cpp-worker-backend`), no changes to `main` or PR #16.
> Times below were read from GitHub's **per-job/per-step**
> `started_at` and `completed_at` fields via the Actions REST API.
> Only completed, **successful** comparable jobs are included.
> This is observational build telemetry, not a randomized causal experiment.

## Comparison: before native Waf caching vs. warmed native Waf cache

All times in seconds, measured at the **job level** (not workflow queue time).
The new Essentia upstream `actions/cache@v4` **hit** is explicitly confirmed
in the warmed-run job logs. Exact native toolchain and upstream source SHA
are part of the cache key. CI still runs configure/build/install, native IPC,
ONNX, PE/DLL packaging and the synthetic parity gates on a cache hit.

| Target | Before: successful run IDs (job seconds) | Warm-cache: successful run IDs (job seconds) | Median before | Median warmed | Reduction |
| --- | --- | --- | ---: | ---: | ---: |
| Original Essentia Windows x64 (MinGW) | [39464494441](https://github.com/chrober/bliss-mood-poc/actions/runs/39464494441) (1056), [39464587598](https://github.com/chrober/bliss-mood-poc/actions/runs/39464587598) (1061), [39465052673](https://github.com/chrober/bliss-mood-poc/actions/runs/39465052673) (1060) | [39468729420](https://github.com/chrober/bliss-mood-poc/actions/runs/39468729420) (491), [39468747018](https://github.com/chrober/bliss-mood-poc/actions/runs/39468747018) (419), [39468855235](https://github.com/chrober/bliss-mood-poc/actions/runs/39468855235) (500) | **1060s / 17:40** | **491s / 8:11** | **−53.7% / −9:29** |
| Original Essentia Linux (Ubuntu 22.04) | [39464495640](https://github.com/chrober/bliss-mood-poc/actions/runs/39464495640) (397), [39464588142](https://github.com/chrober/bliss-mood-poc/actions/runs/39464588142) (310) | [39468729343](https://github.com/chrober/bliss-mood-poc/actions/runs/39468729343) (92), [39468747116](https://github.com/chrober/bliss-mood-poc/actions/runs/39468747116) (86), [39468854889](https://github.com/chrober/bliss-mood-poc/actions/runs/39468854889) (77) | **353.5s / 5:53.5** | **86s / 1:26** | **−75.7% / −4:27.5** |

### Direct upstream Waf configure/build/install time

| Target | Before (step seconds) | Warm cache (step seconds) | Median before | Median warmed | Reduction |
| --- | --- | --- | ---: | ---: | ---: |
| Windows | 530, 486, 525 | 5, 3, 5 | 525s | 5s | **−99.0%** |
| Linux | 293, 206 | 2, 2, 1 | 249.5s | 2s | **−99.2%** |

The Windows run [39468855235](https://github.com/chrober/bliss-mood-poc/actions/runs/39468855235)
explicitly logs `Cache hit for: original-essentia-waf-win2022-mingw64-v1-...`,
a roughly **400 MB** restore, and `waf -j 4` completing inside the
5-second Waf step. The Linux run
[39468854889](https://github.com/chrober/bliss-mood-poc/actions/runs/39468854889)
also records a cache hit and roughly **400 MB** restored. These cache
downloads are included in the total job durations above.

### Rust workflows: interpreted separately

`Swatinem/rust-cache@v2` was already enabled **before** these changes
in `ci.yml` and `windows-binary.yml`. These are example job-level timings
showing variation; **do not attribute their differences to adding Cargo.lock**:

| Workflow | Example before new native Waf cache | Example after root Cargo.lock and `--locked` (successful) |
| --- | ---: | ---: |
| [Windows x64 binary](https://github.com/chrober/bliss-mood-poc/actions/runs/39464587948) | 148 s | [132 s](https://github.com/chrober/bliss-mood-poc/actions/runs/39470239847) |
| [Rust checks](https://github.com/chrober/bliss-mood-poc/actions/runs/39464588003) | 46 s | [27 s](https://github.com/chrober/bliss-mood-poc/actions/runs/39470240011) |

Cargo.lock primarily improves **reproducibility and reliable cache
invalidation**, not necessarily build speed. The workflows were changed to
`cargo build/test/run/clippy --locked`, and path-filtered workflows now
watch `Cargo.lock`. The standalone
`native/rust-mel-reference/Cargo.lock` was made consistent with **Cargo's
actual dependency resolution** after the first strict Linux build exposed
a stale dependency graph. The subsequent complete native Linux run
[39471057861](https://github.com/chrober/bliss-mood-poc/actions/runs/39471057861)
**passed `cargo build --locked`**, confirming correct dependency identity.

## Method and limitations

- Use **job timestamps**, not workflow-created-to-completed time, because
  queue and runner allocation depend on external GitHub demand.
- Compare **successful** jobs and collect 2–3 samples per configuration;
  one Linux pre-cache run failed and is deliberately excluded.
- Different commits may change other steps and GitHub runner load varies.
  Cache hits plus dramatically shorter Waf steps support a real build
  acceleration, but the exact end-to-end median is environment-dependent.
- The native Linux and Windows jobs download external official model files
  with their own SHA/size checks. Those weight files and user music are
  **not stored** in the GitHub cache.
- Cache entries are large (about 400 MB per native platform) and must be
  monitored for storage/eviction; a cache miss is safe and falls back to
  full upstream compilation.
- Always re-check **latest PR head and CI** before reporting newer build
  statuses. None of these measurements asserts that PR #17 is ready to merge.

## Implementation

- Cache and ABI-key changes: `native-essentia-windows.yml`,
  `native-essentia-cpp.yml`; Windows both Cargo workspaces cached.
- Locked Cargo changes: [commit 7635333c](https://github.com/chrober/bliss-mood-poc/commit/7635333ce19557b9032819b6ae9c29d9c660b008)
  across the Rust-build workflows.
- Independent Mel reference lockfile correction based on the real CI Cargo
  resolver output: [commit caf6a807](https://github.com/chrober/bliss-mood-poc/commit/caf6a80714cc63f33f5539d713552bbb9cc5cebd).
