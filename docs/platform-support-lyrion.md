# Lyrion host-platform support contract (original Essentia C++ backend)

**Decision (2026-10-20):** Target any OS/architecture on which Lyrion Music
Server can run **where the entire analysis stack can also be built and
validated**. Lyrion being installable is necessary context, not proof that
the Rust scanner, upstream Essentia C++ dependencies and ONNX Runtime are
available on every architecture. No platform is labelled supported without
target-native build and numerical evidence.

Lyrion references: https://lyrion.org/reference/lyrion-music-server/ and
https://lyrion.org/getting-started/ .

## Fixed portable core

Keep the existing Rust orchestrator, adaptive workers, ONNX sessions, model
registry, optional native-process supervisor and single sidecar SQLite writer.
Each worker owns one long-lived original Essentia C++ process, communicating
only through the versioned EFW1/REQ1/RES1 binary IPC contract. The Rust frontend
remains the default; original Essentia is explicit opt-in. Do not introduce
`essentia-rs`, duplicate original C++ DSP in Rust, or link native C++ into the
Rust process using a platform-specific C++ ABI. Avoid Windows-specific
assumptions in paths, subprocess lifecycle, decode, scheduling and IPC.

The C++ binary, its runtime dependency closure, ONNX Runtime build and model
cache must be generated/validated **per platform/architecture**. A Windows
PE/DLL bundle cannot be reused on macOS, Linux or the Raspberry Pi.

## Qualification matrix (evidence, not marketing)

| Target | Build and runtime requirements | Validated evidence |
|---|---|---|
| Windows x86_64 | Real MinGW64 Essentia/PE worker; System32-vs-MinGW DLL closure; stand-alone PATH-isolated binary; original audio+Rust/ONNX comparison | **Experimental native CI green**: https://github.com/chrober/bliss-mood-poc/actions/runs/39413454780 |
| Linux x86_64 | Pinned original upstream Essentia, ELF loader/runtime libraries, WAV/FLAC/MP3 and full ONNX parity | **Experimental native CI green**: https://github.com/chrober/bliss-mood-poc/actions/runs/39373185587 |
| Linux aarch64, Raspberry Pi 4B, piCorePlayer 11 (64-bit) | Build native C++/Rust/ONNX for actual Pi userland; verify libc, loader, FFmpeg/FFT and library extensions; persist binaries/models under piCorePlayer's deployment constraints | **Not validated**; primary next ARM64 target |
| Linux on other Lyrion-capable CPUs/NAS/Docker | Target-native container/runtime, ELF libc and ONNX availability, memory and I/O bounds | **Not validated as an independent target** |
| macOS x86_64 and arm64 (Apple Silicon) | Native Clang/Mach-O + Essentia dylib dependencies and install names; ONNX native architecture; EFW1 and numeric parity, packaging/signing considerations | **Not validated** |
| Other Lyrion-supported Unix-like OS or CPU families | Capability-gate each Rust compiler, original Essentia dependency, supported ONNX Runtime and native loader rather than claiming blanket compatibility | **Not validated** |

These targets are independent qualification gates. Windows proof does not
establish macOS, ARM64, piCorePlayer persistence, or portability to 32-bit
architectures. Upstream Essentia revisions are currently distinct: Linux
reference `9ceef0a3a7900ad51eb42aa5b6c6789b4bec6a47` (FFmpeg 4.4),
Windows candidate `b0661db99be4a8e2c6fabbe90a996f89786fdd8e` (FFmpeg 9).
Record exact revision and dynamic library provenance on each platform.

## Mandatory target-native evidence

1. Compile **real** architecture-matching original Essentia C++ worker and
   Rust scanner; verify EFW1 handshake, repeated requests, crash/restart,
   hard timeout and resource observations (not only protocol fixtures).
2. Inspect the platform-specific loaded runtime dependency closure
   (Windows PE imports, Linux ELF dependencies/rpaths, macOS Mach-O
   dylib/install names). Hash every shipped non-OS dependency; fail closed
   on missing, shadowed or untrusted dependencies.
3. Verify synthetic mono/stereo WAV, FLAC, MP3 patch counts and Mel numerical
   agreement against the same production Rust decoder/preprocessor sources.
   Verify 1280-D EffNet embeddings and all 87 genre, 56 mood/theme and 2
   voice probabilities using SHA256-verified original ONNX model files.
4. Test fixed 1/2/4/6 workers **only if memory permits**; compare Rust default
   vs native opt-in with identical audio cohorts, full process-tree RSS/private
   memory, CPU, latency, I/O and restart behaviour.
5. On Raspberry Pi 4B + piCorePlayer 11 64-bit, first prove **one worker** fits
   available memory and that the complete deployment, model files and
   launcher survive the system's persistence/reboot model. Do not assume
   Debian/glibc binaries or external native libraries work on piCorePlayer.
6. Perform separate dependency provenance, source/notice licensing review and
   distribution audit before publishing or declaring native bundles
   production-approved.

## Windows binaries are a non-negotiable validation input

The Windows Actions workflow builds the original Essentia **Windows x64**
`bliss-essentia-worker.exe` plus real dependency DLLs and runs that actual
binary, including the isolated bundle, on a Windows x64 runner. Run
#39413454780 passed genuine WAV/FLAC/MP3 and all-head numerical parity.
This is materially different from a cross-platform fixture.

The currently produced Windows development bundle contains **100 binaries**
and a hashed `worker-dependencies.json`. Its manifest deliberately records
`license_inventory_complete=false` and `release_approved=false`.
CI uses those real Windows binaries **inside the build runner**; it does not
yet upload a redistributable EXE/DLL artifact for external installation.
That separate delivery gate requires inventory of all Essentia/FFmpeg and
other licenses and notices. Neither model weights nor personal audio should
be committed or included in binary artifacts.

Scope remains an experimental Draft PR. Do not merge into `main`, change
`BlissMixerLab` or modify the original music database in this work.
