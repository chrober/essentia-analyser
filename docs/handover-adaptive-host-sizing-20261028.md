# Handover: native Essentia adaptive workers, priority, and host-dependent limits (2026-10-28)

**Canonical current handover for PR #18 (code baseline):** [PR #18](https://github.com/chrober/bliss-mood-poc/pull/18), branch `feat/manifest-batch-adaptive-worker-analysis`, code head `ea514f144183fc8b24c82ad25e93c0f3e201b2e2` **before this documentation update**. PR #18 is stacked on PR #17 (`feat/essentia-cpp-worker-backend`), not on `main`. Independent similarity research PR #16 remains unaffected. **Always re-read the live PR head** and corresponding CI checks; this SHA is a historical verification point, not a permanent tip.

See [the paste-ready handover prompt](handover-prompt-adaptive-host-sizing-20261028.md), [adaptive historical handover](adaptive-scan-performance-handover.md), [manifest/scanner design](manifest-batch-adaptive-analysis.md), [priority investigations](native-worker-priority-study.md), and [cross-platform resource roadmap](platform-resource-roadmap.md).

## 1. Purpose and immutable boundaries

Investigate fast, repeatable **offline** Mood/Genre/Voice inference with an original Essentia C++ audio frontend and Rust scan coordinator. Per-song embedding: shared Discogs-EffNet **1280D**; heads: Jamendo Mood/Theme (56 labels), Genre (87 labels), Voice/Instrumental (2 labels). Original music and Bliss DB must remain **read-only**; store scans in fresh local SQLite sidecars and optional embedding JSON directories. Keep original model weights, output identity, source track keys, independent per-worker model sessions, a single SQLite writer, `--max-new`, `--max-errors`, native timeouts, `--threads 1` with parallel workers, and exact score/embedding parity. Production plugin/mixer changes and similarity PR #16 are out of scope.

The representative private local benchmark uses an existing **100-song** `TracksV2` cohort on Windows 11 / Ryzen 7 7730U (**16 logical CPUs**, ~16 GB RAM), original song audio on NAS over Wi-Fi, official ONNX models, and the verified original Essentia C++ worker. **Do not commit/upload personal media, private cohort DB, local manifests, raw per-song scanner logs, ONNX weights or machine secrets.** Only aggregate findings and generic instructions belong in the repository.

## 2. Real-music evidence — completed experiments, not performance hypotheses

### 2a. Prior unbalanced priority comparison (27 October 2026)

100 songs, fixed 1/2/4/6 vs adaptive 2–6, two repetitions each, exact output parity. Median seconds: fixed1 **282.126**, fixed2 **277.649**, fixed4 **110.803**, fixed6 **93.417**, adaptive2–6 **116.852**. **Confounded**: old adaptive mode ran Windows `BelowNormal`, fixed numeric runs normally `Normal`; cannot infer adaptive overhead from that experiment alone.

### 2b. Explicit three-priority matrix (27–28 October 2026)

Exactly **30 completed scans** (five modes × three priority classes × two repetitions; all 100 songs and three heads), original native C++ backend, verified exact classification and complete embedding parity, actual Win32 priority class verified for scanner and every native subprocess.

| Mode | BelowNormal median s | Normal median s | AboveNormal median s |
|---|---:|---:|---:|
| fixed1 | 414.889 | 416.232 | 403.865 |
| fixed2 | 257.683 | 238.162 | 270.009 |
| fixed4 | 167.856 | 163.123 | 164.551 |
| fixed6 | 118.605 | 107.819 | 112.764 |
| adaptive2–6 | 174.288 | 171.791 | 172.294 |

Interpretation: no reliable/reproducible benefit from `AboveNormal` on this unloaded workload. Six fixed workers beat slowly growing adaptive 2→6. The three priority groups were **run sequentially**, so background changes, NAS caches, power/thermal state and song-duration variance remain confounders. Do not use this data to claim scheduling priority never matters under CPU contention.

### 2c. Controlled adaptive start/gate study (28 October 2026)

**10 completed scans**, same 100 songs, models, binary class `Normal`, two order-balanced repetitions, exact score/embedding parity. Every adaptive variant used minimum **2**, maximum **6**; fixed6 was the reference. Table is median wall seconds over two runs, **not an independently proven universal ranking**.

| Mode | Median wall s | Peak private process-tree MiB | Total changes over 2 runs |
|---|---:|---:|---:|
| adaptive6_gate24 | **119.668** | 635.027 | 0 |
| fixed6 | 125.589 | 647.445 | 0 |
| adaptive4_gate24 | 126.537 | 625.828 | 4 |
| adaptive2_gate8 | 146.344 | 604.090 | 8 |
| adaptive2_gate24 | 148.650 | 604.461 | 8 |

Real worker adjustment positions:
- adaptive2_gate24: round1 **25,34,48,68**; round2 **25,35,48,62**.
- adaptive2_gate8: round1 **12,30,38,56**; round2 **9,27,40,58**.
- adaptive4_gate24: round1 **25,38**; round2 **26,35**.
- adaptive6_gate24: no changes; active six throughout both runs.
- fixed6: fixed six throughout.

**Interpret carefully:** earlier gate eight advanced the first growth but barely improved median whole-run time versus gate 24 (**146.344 vs 148.650 s**); startup **2 versus 4 versus 6** is much more consequential. Adaptive-start-6 vs fixed6 differed in round1 (109.656 vs 121.546 s) but were practically tied in round2 (129.680 vs 129.631 s). This is likely run-to-run variability, **not proven adaptive-over-fixed speedup**. In both adaptive6 runs no resize occurred. Every adaptive run starting under six eventually reached **the configured maximum six**; therefore measurements **cannot yet determine** whether the true optimal native-worker count is 6, 8, 10, 12 or another value. CPU/RAM measurements at six showed headroom, but that alone does not prove throughput scales further. Earlier 6/8/10/12 tests on a *different Rust audio backend/setup* are historical, **not direct native-C++ evidence**.

## 3. Current controller algorithm (code-verified)

`src/parallel.rs::AdaptiveWorkers::observe_at`:
- High load when **system RAM >=88% OR system CPU >=90%** for **two consecutive valid resource samples** → decrease by **one** active slot, unless already at minimum.
- Low load when **system RAM <=79% AND system CPU <=65%** for **three consecutive valid samples** → increase by **one** slot, unless at maximum.
- Neutral observations reset both streaks. Require at least **24 successfully completed songs** by default (`--adaptive-min-completed-songs 8` in special test) **and** **20 seconds** since controller creation or last change for either direction.
- Resource observations are completion-driven, no more often than every **2 seconds**, **not** a continuous timer; empty/missing metrics do not drive decisions.
- A controller decision modifies **in-flight admission cap**, not ongoing tasks or loaded ONNX sessions. Actual native worker pool can already have max-capacity thread slots; only admitted concurrent song jobs change.
- Adaptive diagnostics: `diagnostics.initial_workers`, `final_workers`, `peak_workers`, `adaptive_min_completed_songs`, `adjustments[]` with `after_completed_songs`, `from_workers`, `to_workers`, `reason`, CPU/RAM; `controller_decisions` with low/high/neutral samples and hold/change counters. The benchmark `runs.csv` includes `first_resize_after_completed_songs`, `resize_song_positions`, `controller_gate_holds`, `controller_cooldown_holds`.
- Current algorithm uses **CPU/RAM threshold headroom**, **not** actual throughput-improvement feedback. Dynamic process priority is **not implemented**.

## 4. Host-dependent maximum: current implemented semantics

User requirement: **no fixed global 6/8-worker cap**; Raspberry Pi 4B with **4 permitted logical CPUs** must not get a fixed-six limit. In the current PR #18 code, `src/parallel.rs` uses `std::thread::available_parallelism()` (may reflect affinity/container limits; max technical 64, fallback one CPU):

- `--max-workers auto` **default** resolves to permitted logical CPUs capped at **64**. In `src/main.rs`, CLI `auto` parses internally as sentinel `0`, then resolves before constructing `ScanOptions`; `0` is **never** a real count.
- `--workers auto` remains a conservative **initial** sizing: reserve `max(2, floor(allowed_CPUs/4))`, then cap start at **8**, minimum 1.
- `--min-workers` default **1** (formerly 4), allowing small CPU devices. `--workers` CLI default remains `1`; simply enabling `--adaptive-workers` without choosing `--workers auto` does **not** mean automatic initial sizing.
- Explicit `--workers N` and explicit `--max-workers N` above available logical CPUs are **rejected**, rather than silently oversubscribing. A fixed cap requested by benchmark is still honored on capable machines. Adaptive validation still requires `min <= initial <= max`.
- Examples: with **4** permitted CPUs: `--workers auto` starts **2**, `--max-workers auto` resolves **4**; with **16**: starts **8**, maximum **16**; with **1**: initial/max **1** (serial path).
- `diagnostics.logical_cpu_capacity` and `diagnostics.configured_max_workers` report host capacity and effective pool cap (pool is also bounded by number of candidate tracks).
- **Not RAM-aware yet.** A Raspberry Pi 4B with 4 GB RAM can still run out of memory with four ONNX sessions, and thermals, I/O, memory/cgroup quotas and library workload can lower the *safe/optimal* cap. CPU-only is a first-stage ceiling, not a promised optimal or always-safe default. `available_parallelism` is not a guaranteed precise cgroup quota measurement on every host.

Explicit Windows priority classes `--priority below-normal|normal|above-normal` independently apply to scanner and original C++ children (explicit Win32 process creation flags; actual observed classes verified). Omitted priority retains legacy behavior: fixed numeric doesn't change priority; auto/adaptive requests `BelowNormal`. Explicit priority currently unsupported on Linux/macOS (error). All real-music comparisons above used explicit equal priority per respective group. No dynamic priority governor.

## 5. Source/CI status and precise reproducibility

**Code-verified baseline before writing this handover:** `ea514f144183fc8b24c82ad25e93c0f3e201b2e2`. The earlier host-cap patch `5b36652f...` triggered strict Clippy `large_enum_variant` when `--max-workers` was represented as `String`. That issue was subsequently fixed in actual source by parsing `auto` to `usize=0` sentinel; do **not** reintroduce the large enum issue. The CI follow-up also changed the voice parity workflow to avoid explicit oversubscription on small hosted runners; check current `.github/workflows/voice-parity.yml`.

Successful checks on that exact code commit:
- Rust checks: [40653208984](https://github.com/chrober/bliss-mood-poc/actions/runs/40653208984) — PASS.
- Windows x64 binary: [40653208925](https://github.com/chrober/bliss-mood-poc/actions/runs/40653208925) — PASS; verified existing, non-expired `bliss-mood-windows-x64` artifact on matching source code SHA.
- Original native Essentia C++ smoke: [40653208936](https://github.com/chrober/bliss-mood-poc/actions/runs/40653208936) — PASS.
- Genre ONNX/TensorFlow parity: [40653208976](https://github.com/chrober/bliss-mood-poc/actions/runs/40653208976) — PASS.
- Voice/Instrumental parity: [40653208956](https://github.com/chrober/bliss-mood-poc/actions/runs/40653208956) — PASS.

**After these Markdown changes the PR head will differ from that code commit.** A documentary commit is not a code change, but any new run/artifact must still be matched to the exact commit under test; do not claim prior artifacts are for the newer documentation commit.

Local workflow: **no Rust build on Windows laptop**; build via CI. Use a complete self-contained PowerShell `& { ... }` block with verified literal run ID, `gh run download`, `BUILD.txt` source-commit identity, SHA256 verification, clean detached worktree, 100-song bounded input, explicit `--threads 1`, `--priority normal`, native worker prerequisite and new/empty result dir. No login access to private local Windows/NAS from remote GitHub Actions. Use `--experiment adaptive-policy` for the earlier 2/4/6 and 8/24-song controller study; its study modes deliberately cap at 6. Do not present that experiment as a validation of host-`auto` on a Pi. Use the CI-backed binary from a **matching commit** and confirm green Windows + Rust + native/model parity workflows. Separate all code changes from experiment result claims.

> **Phase A measured update (28 October 2026):** The independent
> [native 6/8/10/12 fixed-worker scaling study](native-worker-scaling-study.md)
> now includes **eight completed private local real-music scans** (100 songs,
> three heads, exact classifier and 1280D embedding parity). Median whole
> scan times: fixed6 **84.558 s**, fixed8 **85.562 s**, fixed10 **94.127 s**,
> fixed12 **68.069 s**. Twelve was fastest in both repeats, at **88.166 songs/min**
> and **1127 MiB** peak observed private process-tree memory, with at least
> **3679 MiB** physical RAM available. This is the best *tested* worker count,
> **not** proof of the optimum at fourteen/sixteen or on small ARM hardware.
> The ten-worker slowdown is not yet explained. The scanner code and
> last Windows binary remain tied to the prior **10dadb65** source SHA;
> subsequent Markdown commits must not be presented as new binary validation.
>
## 6. Recommended next work (do not skip controls)

1. **Native throughput-versus-memory scaling:** On the 16-logical-CPU Windows host, compare **fixed 6/8/10/12** (or an incremental stop-on-memory-pressure schedule), two balanced repetitions with identical 100-song sample, priority `Normal`, clean sidecars. Preserve exact 3-head scores and 1280D embeddings, measure wall/songs-min, system CPU/RAM, available memory, process-tree private MiB, real active concurrency and native child count. These are *not yet measured* for this native C++ cohort beyond six. Avoid oversubscribing Raspberry Pi hardware.
2. **Host auto sizing tests:** simulate/reproduce 1/2/4/8/16/64-permitted CPUs; run constrained Linux/cgroup and (if actual target is available) genuine Raspberry Pi 4B with 4 cores/4 GB, Linux ARM architecture and ONNX runtime prerequisites. Verify one/2/4 worker start/max and memory headroom. No claim that x64 CI provides ARM validation.
3. **Memory-aware policy:** incorporate actual available memory, session and native child working sets, cgroup limits, per-model memory cost and safety headroom. Consider an optional ceiling lower than logical CPU cap; large real models on a 4 GB Pi may demand fewer than 4 workers.
4. **Throughput feedback as a separate experiment:** after establishing a safe fixed-worker optimum, compare controlled, phase-aware songs/time trends with hysteresis and bounded exploration. Avoid interpreting variable song durations, NAS cache and SMB I/O as an immediate throughput signal.
5. **Priority controller:** defer dynamic `Normal`/`BelowNormal` process-tree changes pending competing foreground load and user-facing latency experiments. The 30-scan priority matrix supplied no persuasive `AboveNormal` benefit in uncontended conditions.
6. Keep PR #17's original Essentia C++ backend, PR #16 similarity, licenses/distribution and Lyrion integration outside this optimization PR unless separately authorized.

## 7. New-session checklist

Read this document and [the handover prompt](handover-prompt-adaptive-host-sizing-20261028.md). Fetch **live** PR #18 head + checks + source before changes. Distinguish **completed local measurements** from code/CI-only verification and unmeasured throughput hypotheses. Do not repeat prior questions already answered. Continue within `feat/manifest-batch-adaptive-worker-analysis` (unless a focused new branch is justified), update docs/tests together, keep private input read-only, and use commit-matched GitHub Actions artifacts for any Windows testing.
