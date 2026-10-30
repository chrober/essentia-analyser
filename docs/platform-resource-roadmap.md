# Deferred platform-neutral resource architecture

**Status:** Roadmap; CPU-capacity discovery partly implemented in PR #18
as of 28 October 2026. **Memory-aware sizing, ARM/Raspberry Pi native
inference validation, and throughput feedback remain unimplemented.**
See [current host-sizing handover](handover-adaptive-host-sizing-20261028.md)
before relying on the historical task sequence below.
**Recorded:** 2026-10-19.
**Current priority:** [Bliss + Mood/Genre in Lyrion](lyrion-bliss-mood-genre-integration.md).
**Source of truth:** existing scanner implementation, CI, and experiment handovers.

## Product requirement

The analyzer and optional background scanner must work generically, not be
optimized around the HP Ryzen laptop used for benchmarks. The target spectrum
includes Windows x64 and Linux devices such as Raspberry Pi / Lyrion and
resource-limited headless systems. The laptop's baseline RAM utilization
(83.77% before worker launch on one benchmark) is a **test condition**, not
a reason to set global worker thresholds or defaults.

The existing fixed-worker CLI behavior and opt-in adaptive worker guard
remain available until a replacement demonstrably preserves semantics.
No changes to source audio or the read-only original Bliss database.

## Future implementation sequence (do not block the Lyrion feature work)

### R1 — Cross-platform resource discovery and build validation

- Define an optional metrics interface for logical/allowed CPU capacity,
  total/available physical memory, process memory, and usable memory limits,
  including container/cgroup/OS policy limits where discoverable.
- Distinguish **system-wide observed load**, **resource capacity**, and
  **per-process usage**. Partial/unavailable measurements must be explicit,
  never silently treated as zero load or unlimited RAM.
- Add Linux/aarch64 CI build and binary smoke testing with exact artifact
  provenance. Confirm actual ONNX Runtime library availability; a
  cross-compiled executable alone does not prove working ARM inference.
- Document and validate the *actual* Raspberry Pi target (`uname -m`,
  32-/64-bit OS, libc ABI, loader, FFmpeg, ONNX native libraries,
  persistent storage). Aarch64 builds must not be claimed to work on
  32-bit piCorePlayer.
- Add synthetic tests for 4 cores / 2 GiB, 8 cores / 16 GiB, and
  16 cores / 32 GiB, including missing metrics and constrained containers.

### R2 — Adaptive policy v2 (separate opt-in from established behavior)

- Base worker admission on a memory budget and **incremental** measured
  memory cost of concurrent ONNX sessions and decoded audio, with reserved
  headroom for the OS and other applications.
- Consider actual allowed CPU parallelism and measured throughput rather
  than fixed global RAM-percentage cutoffs. A system starting at 85% RAM
  must not be treated identically to an otherwise idle host without
  considering *available* and *recoverable* memory.
- Separate safety throttling from throughput optimization. Use hysteresis,
  cooldown, phase-aware measurements and bounded concurrency; ensure
  one SQLite writer and no cancellation of in-progress analyses.
- Preserve deterministic per-track output, idempotency, fixed-worker modes,
  and the unchanged source database/audio invariants. Gate via CI and
  representative cross-platform benchmarks.

### R3 — Optional Pi-side background operation

- Validate an actual incremental analyzer run on the deployed Lyrion host,
  with a bounded job queue, configured low priority, and memory/time budget.
- Keep library-wide ONNX inference **offline**, never on the playlist
  request path. Load precomputed feature sidecar data when creating mixes.
- Do not release or distribute model weights without reviewing their own
  licensing restrictions.

## Developer workflow contract

Read [chat-handover.md](chat-handover.md) before edits.
On the user's Windows laptop **never compile Rust locally**. Code changes
on a PR cause GitHub Actions to generate a Windows binary. Wait for all
relevant PR checks to pass, verify the artifact and exact head commit,
then give a complete PowerShell `& { ... }` script with a hardcoded valid
run ID and `gh run download` whenever local testing is needed.
Do not select a run automatically or reuse a binary from a different commit.

**Decision:** This work is deliberately parked in favor of the Lyrion
Bliss/Mood/Genre product integration below. Do not spontaneously schedule
or start new scanner performance PRs during that functional work.
