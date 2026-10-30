# Handover prompt — adaptive host-aware worker sizing (2026-10-28)

Paste the following into a new ChatGPT project session. The detailed current handover is [handover-adaptive-host-sizing-20261028.md](handover-adaptive-host-sizing-20261028.md).

---

I am continuing the `Lyrion: Mood Analysis` project in GitHub `chrober/bliss-mood-poc`. Please adopt the project context and **first read** the live GitHub PR #18 (`feat/manifest-batch-adaptive-worker-analysis`, stacked on original Essentia C++ PR #17), source, CI, and these docs:

- `docs/handover-adaptive-host-sizing-20261028.md` (authoritative recent handover)
- `docs/adaptive-scan-performance-handover.md` and `docs/chat-handover.md` (historical background)
- `docs/native-worker-priority-study.md`, `docs/manifest-batch-adaptive-analysis.md`
- `docs/platform-resource-roadmap.md`, `docs/native-essentia-ci-baseline.md`.

Latest **verified code** before handover documentation update: `ea514f144183fc8b24c82ad25e93c0f3e201b2e2`. CI Windows x64 run `40653208925` passed with a non-expired `bliss-mood-windows-x64` artifact matched to that code SHA; Rust, native C++ smoke, Genre and Voice parity also passed on that code commit. **Do not assume this is still the PR head. Verify live head and associated runs.** A previous Clippy `large_enum_variant` error from `--max-workers: String` was already fixed with compact `usize` parsing (`auto` is an internal zero sentinel resolved before worker creation).

Context: Rust scanner orchestrates separate original Essentia C++ workers, ONNX Mood (56), Genre (87), Voice (2), shared 1280D Discogs-EffNet embeddings, one SQLite sidecar writer and per-worker sessions. Source Bliss DB and music read-only, PR #16 similarity untouched. Real music/DB/manifests/model weights stay LOCAL, never commit.

Real completed 100-song NAS experiments:
- 30 scans across `BelowNormal`, `Normal`, `AboveNormal`: **no convincing AboveNormal throughput benefit**; six workers materially better than adaptive start 2. Exact numeric parity verified.
- 10 scans of `fixed6`, `adaptive2_gate24`, `adaptive4_gate24`, `adaptive6_gate24`, `adaptive2_gate8`, all at `Normal`: medians **125.589 / 148.650 / 126.537 / 119.668 / 146.344 seconds** respectively. All adaptive runs growing from below six reached maximum six; adaptive6 never resized and was almost identical to fixed6 in its second repetition. The shortened gate had little effect; higher initial workers mattered more. At six, observed CPU/RAM had reserve, but **native C++ scaling beyond six remains unmeasured**.
- Current controller grows one after 3 low-load samples (CPU <=65% and RAM <=79%); shrinks one after 2 high-load samples (CPU >=90% or RAM >=88%); default 24 completed songs, at least 20 seconds between adjustments, resource sampling at most every two seconds on song completions. `--adaptive-min-completed-songs 8` is opt-in. It is not throughput optimizing.

New requirement implemented in PR #18: system-dependent worker ceiling. Default `--max-workers auto` = `std::thread::available_parallelism()` (available logical CPUs, max technical 64); explicit worker values above CPU count fail; `--min-workers` now defaults 1; `--workers auto` uses reserve max(2, quarter CPU) and initial cap 8, while `--workers` default remains 1. Thus Raspberry Pi 4B with four permitted CPUs starts auto at 2 and caps at 4; Ryzen with 16 starts at 8 and caps at 16. **CPU-derived cap is not yet memory-safe for 4 GB Raspberry Pi**. Windows explicit process priority can be `below-normal|normal|above-normal` applied and verified on native child processes; dynamic priority is not implemented.

**Completed Phase A evidence (28 October 2026):** eight local fixed 6/8/10/12 scans, 100 songs × 3 heads, two reversed-order repetitions, exact classifier and 1280D embedding parity, all fixed worker and child concurrency counts verified, no RAM safety stop. See `docs/native-worker-scaling-study.md` for the privacy-safe aggregate table. Median wall seconds: 6=84.558, 8=85.562, 10=94.127, **12=68.069**; twelve yields **88.166 songs/min** (+24.2% throughput vs six). The peak observed twelve-worker private process-tree footprint was ~1127 MiB, minimum free RAM ~3679 MiB. Ten workers were anomalously slower than six; not causally explained. This benchmark supports **twelve as the best tested count on this Ryzen/NAS workload**, NOT the general optimum or a Raspberry Pi default. Raw private CSV/JSON, manifest, DB, hashes and tracks must remain local.

**Next objective:** decide whether to test 14/16 fixed workers and repeat 10/12 under stricter controls (NAS/power/thermal variability) before designing **memory-aware, portable adaptive limits** for constrained systems. Separate a hard RAM admission/safety governor from throughput-driven optimization. Do not replace the CPU-only cap with a claimed universal 12-worker default. Consider throughput feedback only as a separately controlled v2 controller; do not conflate throughput, CPU capacity, and RAM safety. Review and update docs/tests. Work in the appropriate PR branch, not main. Do not alter or create a new performance policy without evidence.

Windows workflow: **never compile Rust locally**; verify Actions Windows binary + source SHA + BUILD.txt + SHA256, use complete copy-pastable PowerShell `& { ... }` script with verified literal Actions run ID and `gh run download` for any local experiment; no invented run IDs or promises of unverified binaries. Do not make production Lyrion/Bliss integration or PR #16 similarity changes. First report a concise assessment of current live PR/CI status and a concrete next test proposal, then implement authorized changes directly.

--- 
