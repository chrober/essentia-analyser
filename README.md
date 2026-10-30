# Essentia Analyser

Portable offline **Rust + original Essentia C++ audio feature analyser**. This is the dedicated application repository extracted from [`bliss-mood-poc`](https://github.com/chrober/bliss-mood-poc). The latter remains an independent research and experiment laboratory (WP1 General Metric, WP2 Personal Metric, WP3 Bliss↔Essentia relationships).

## Mission: free and open source for the Lyrion community

**This is a non-commercial community project, not a commercial product.** Its code, development, documentation and intended end-user availability are oriented toward the **Lyrion Music Server community**, freely accessible and free of charge. We are not planning a paid edition, a closed-source product or a commercial model service.

We want to make offline music-feature analysis practical for community members on Windows, Linux, macOS and smaller systems where technically supported. The scanner, [Essentia Similarity](https://github.com/chrober/essentia-similarity) and the optional Lyrion Guidance integration remain **separate repositories with distinct responsibilities**. [`bliss-mood-poc`](https://github.com/chrober/bliss-mood-poc) stays the general research laboratory; **no repository merge is proposed**.

Our own source is MIT-licensed (subject to source provenance review); that licence permits downstream commercial reuse even though **we do not intend commercial use**. Essentia C++ (AGPL), FFmpeg and the separately supplied MTG/ONNX model weights retain their **own** terms. In particular, the external model weights must **not** be described as MIT/OSI-open-source merely because the project is free and open source. Noncommercial intent does not exempt a publicly redistributed native binary package from licence compliance.

**Read the [community mission and distribution policy](docs/community-project-policy.md)** for the project's intended use, source-first installation strategy, free community binary goals and precise separation between development and package-release checks.

## Applications included

- **`bliss-mood`** (`bliss-mood.exe` on Windows): existing Rust CLI for decoding/analysis orchestration, persistent feature extraction, bounded fixed and auto worker parallelism, ONNX Runtime, model fingerprinting and SQLite sidecars. This initial extraction intentionally preserves the old executable name and CLI flags; a separately tested future rename can produce `essentia-analyser`.
- **`bliss-essentia-worker`** (`bliss-essentia-worker.exe` on Windows): existing *original Essentia C++* worker source in `native/essentia_cpp_worker.cpp`. Compiled independently using CMake against a separately provisioned pinned upstream MTG Essentia library and native codec dependencies. On-demand when the CLI selects `--audio-backend essentia --essentia-worker <path>`.

These binaries are **not** produced together automatically by `cargo build`. The C++ worker has its own prerequisites and build pipeline. Neither application is part of `essentia-similarity`: that independent project consumes **precomputed features**, not audio files or ONNX weights.

## First migration: unchanged behavior

The first branch copies the complete application `src/`, `native/`, model-registry, `Cargo.lock`, existing tests, technical scripts and historical scanner documentation from the frozen, audited source commit. **No changes to the native IPC protocol, feature SQLite v3 schema, exact feature keys, worker scheduling or analysis defaults.** Existing scanner binary remains named `bliss-mood` for compatibility. Changing the CLI name and cleaning the historical experiment switches is separate follow-on work after parity.

```bash
cargo test --locked
cargo build --release --locked
cargo run -- scan-features --help
```

To use the original C++ worker, build it with the separately provisioned upstream Essentia and compiler/toolchain described in [`native/README.md`](native/README.md); then pass it explicitly to the Rust CLI. FFmpeg/ffprobe and the independently obtained ONNX model files are prerequisites as documented in the scanner's existing workflow. No third-party audio or ONNX files are vendored.

## Distribution and licenses

**Current packaging gate (30 Oct 2026): `distribution_release_status=BLOCKED`, `release_approved=false` for an unaudited public native bundle.** This does **not** block continued open-source development or the aim of convenient, free community releases. The sources are publicly available; **a distributable bundle of original Essentia/FFmpeg/worker/DLL binaries or third-party MTG models is not yet approved**. The [current license and distribution audit](docs/licensing-compliance-review-20261030.md) records the actual MIT/AGPL/FFmpeg/Creative-Commons distinctions, the 17 historic native notice gaps, the model-license page conflict, and the exact steps before any binary release. Model downloads by end users do not waive model terms or automatically resolve the program-combination question.

**Caution:** Successful compilation and numerical parity do **not** grant permission to redistribute upstream Essentia, FFmpeg, runtime DLLs, audio datasets or third-party ONNX models. This public repository is source-only. The native Essentia/FFmpeg dependency inventory and license notices require separate approval. Prior public development artifact packaging is not automatically authorized. See [licensing strategy](docs/essentia-licensing-distribution-strategy.md), [release qualification](docs/release-qualification-gates.md), and [extraction provenance](docs/extraction-provenance.md).

The previous `.github/workflows` are **not automatically enabled** here. The new CI runs only unit/fixture tests and compiler checks: **no C++ upstream Essentia distribution, model downloads, Windows DLL package uploads or published release artifacts**.

## Ecosystem boundaries

| Repository | Owner |
| --- | --- |
| [`essentia-analyser`](https://github.com/chrober/essentia-analyser) | Audio decoding / native worker orchestration / ONNX inference / SQLite v3 feature production |
| [`essentia-similarity`](https://github.com/chrober/essentia-similarity) | Generic reusable scoring core / read-only feature store / Shadow evaluator |
| [`bliss-mood-poc`](https://github.com/chrober/bliss-mood-poc) | Research laboratory: all exploratory studies, benchmarks, WP1/WP2/WP3 |
| [`bliss-guidance-essentia`](https://github.com/chrober/bliss-guidance-essentia) | Native Bliss SPI v2 provider (currently shadow-neutral) |
| [`lms-guidance-essentia`](https://github.com/chrober/lms-guidance-essentia) | Lyrion installation/provider UI (not implemented yet) |

**Cutover policy:** Develop application fixes here *after* accepting extraction parity; keep historical research reproducible in `bliss-mood-poc` without deleting its old scanner source. A compatible sidecar format is a versioned data contract, not a reason to couple the two Cargo build graphs.
