# Executable renaming — Essentia Analyser and Essentia Worker

**Decision: 30 October 2026.** The dedicated repository now uses its own name for both executable targets. No repositories are being merged.

| Historical target | New executable | Builder |
| --- | --- | --- |
| Rust Cargo package bliss-mood, Windows bliss-mood.exe | **essentia-analyser.exe** | cargo build --release --locked |
| Essentia native C++ target bliss-essentia-worker.exe | **essentia-worker.exe** | CMake against independently installed original Essentia |

On Linux/macOS, omit the .exe suffix.

## Run the CLI (Windows PowerShell)

    & {
        $ErrorActionPreference = 'Stop'
        # From the essentia-analyser clone.
        cargo build --release --locked
        if ($LASTEXITCODE -ne 0) { throw 'Rust analyser build failed' }

        $analyser = (Resolve-Path './target/release/essentia-analyser.exe').Path
        & $analyser scan-features --help
        if ($LASTEXITCODE -ne 0) { throw 'Analyser CLI smoke failed' }

        # For genuine audio analysis, install upstream Essentia, compile
        # native/essentia_cpp_worker.cpp and configure the worker explicitly:
        # & $analyser analyze-features 'D:\Music\Example.flac' `
        #     --models-dir './models' --models moodtheme,genre,voice `
        #     --audio-backend essentia --essentia-worker './bin/essentia-worker.exe' --json
    }

## What is unchanged

- All CLI subcommands and flags: scan-features, analyze-features, --essentia-worker, --audio-backend, --workers, --workers auto, and --bliss-db. The latter flag identifies an *external Bliss database*, not the old application name, and is therefore deliberately preserved.
- Original native Essentia C++ algorithms, EFW1/REQ1/RES1 worker IPC framing, SQLite schema-v3 track storage and model registry.
- Rust build alone produces only the Rust executable. A genuine Essentia C++ library and its native dependencies must still be installed separately to compile the worker.
- No native redistributable package, third-party model weights or private audio files are created by this rename.

## Compatibility, provenance and roll-out

Existing locally installed old executables and older Windows development kits are **not automatically renamed or deleted**. Update any local PowerShell launchers, shortcuts and configuration paths to the new binaries. Historical CI logs, audit notices and source provenance refer to their original filenames and remain historically correct.

The native-worker executable and dependency-manifest SHA-256 are part of the feature cache provenance. A new compiled/renamed worker can have a different checksum; **do not bypass these checks to reuse old features**. Confirm the current binary, dependency manifest and fingerprint compatibility; if necessary reanalyse only the affected tracks under the verified new identity.

New Linux and Windows CI exercises the Rust executable path and CLI help, actual synthetic C++ protocol fixture, locked Cargo build and parser, packaging fixture and name-consistency tests. A fully original upstream Essentia C++-linked worker build, real-codec parity and public release license audit remain **separate** quality/release gates.

The scanner belongs to essentia-analyser, independent similarity scoring to essentia-similarity, and continued general WP1/WP2/WP3 research to bliss-mood-poc. See [project policy](community-project-policy.md) and [license review](licensing-compliance-review-20261030.md).
