# Essentia Analyser: initial repository extraction provenance

Date: 30 October 2026

| Field | Fixed value |
| --- | --- |
| Source repository | [`chrober/bliss-mood-poc`](https://github.com/chrober/bliss-mood-poc) |
| Source ref | `main` |
| **Source SHA (immutable)** | `9a9ca062f9bf5adacb640f89c9dc8cf29895f951` |
| New repository | `chrober/essentia-analyser` |
| Initial branch | `feat/initial-analyser-extraction` |
| Original Rust package | `bliss-mood` (name intentionally preserved in first migration) |
| Original C++ target | `bliss-essentia-worker` |
| Existing storage | SQLite feature database schema v3, unchanged |
| Native redistribution | **Blocked** pending completed license and package provenance review |

## What is imported

All **109 tracked source files except the source README and its 13 original workflow definitions** are copied (one Cargo.toml repository URL changed). This includes 12 Rust `src/` files, the 9-file native build/fixture directory, Cargo.lock, LICENSE, model registry, existing 35 scanner/diagnostic scripts, 16 tests, and 32 archival/scanner documents. The new root README and `.github/workflows/scanner-ci.yml` are separate new artifacts. The source workflow definitions remain available in the immutable [source commit's workflows](https://github.com/chrober/bliss-mood-poc/tree/9a9ca062f9bf5adacb640f89c9dc8cf29895f951/.github/workflows) but **are not activated** in this public new repository. Research-specific docs included in the snapshot are archival; their old PR and clone paths should not be treated as instructions for the new product repository.

The new repository must keep an exact licensed source record. The import is a **copy**, not a destructive move: the old repository's code and research datasets remain available for reproducibility. No library/source-code deletion or old-branch rewrite is part of extraction.

## Gates before treating this as the canonical scanner

1. Confirm Rust Linux and Windows Cargo tests and native protocol fixture tests with locked dependencies; validate model registry and source file hashes against original frozen source.
2. Verify original worker IPC and scanner CLI backwards compatibility (the binaries remain `bliss-mood` and `bliss-essentia-worker` for this first stage).
3. Check actual numeric v3 feature output parity on a bounded existing, approved fixture cohort; do not rescan private music unnecessarily.
4. Confirm native Essentia Windows/Linux build parity is still supported with separately provisioned dependencies; static CI smoke is **not** a real upstream Essentia build.
5. Re-review native dependency licenses, model weights, FFmpeg, 17 Windows package notice gaps and actual public packaging. Release `BLOCKED` until cleared.
6. Only after acceptance, rename the binary/CLI in a distinct PR if desired; preserve old-name compatibility or provide an explicit migration guide.
7. Keep `bliss-mood-poc` solely as the research project going forward; new scanner fixes and updates should live here, while research consumes a pinned CLI artifact and feature schema versions.

## Exclusions and non-goals

No new General/Personal Metric, no Spotify/Last.fm guidance, no Lyrion plugin, no changes to the current fixed/auto worker strategy, no dynamic worker optimization, no full music library scan, no audio file or Bliss database mutations. The original research branch `feat/general-pairwise-similarity-research` is **not** the scanner source; it lacks the full native C++ worker tree and diverges materially from scanner main.

## Licensing

The imported Rust scanner source retains the original repository's MIT LICENSE and copyright. Bundled third-party models, binaries or downstream licenses are **not** automatically covered by MIT. Source-only CI and manual development is not approval for distributing native binaries.
