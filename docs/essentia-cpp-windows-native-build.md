# Original Essentia C++ Windows native build (experimental)

**Verified status (2026-10-20, PR #17 pre-handover head `efda3f27e196`):**
the **original upstream Essentia C++ library now compiles and links as
`essentia.dll` under MinGW64 on Windows**. The separate
`bliss-essentia-worker.exe` compilation also passes, but **EXE linkage
fails** with unresolved original Essentia C++ symbols such as
`essentia::init()`, `essentia::shutdown()`,
`essentia::Logger::debug()` and `essentia::ParameterMap::add()`.
See [Windows CI run #39382026896](https://github.com/chrober/bliss-mood-poc/actions/runs/39382026896).

**Next action:** inspect the PE exports, MinGW import library,
`pkg-config --libs essentia` and the actual CMake link command.
Do not treat this as an audio DSP failure. Detailed commands and a decision
tree: [Windows linker handover](handover-essentia-windows-linker-20261020.md).
The **synthetic DLL-packaging smoke is green**, but it is not a test of the
original Essentia-linked Windows worker.

Windows Essentia C++ sources are checked out from upstream MTG/essentia
commit `b0661db99be4a8e2c6fabbe90a996f89786fdd8e` (an **unmerged**
upstream PR 1540 candidate adding FFmpeg 8/9 API support, 2026-10-19).
This revision has different provenance from the fully numerically validated
Linux FFmpeg-4.4 reference at `9ceef0a3a7900ad51eb42aa5b6c6789b4bec6a47`.

**Do not promote the Windows result even if it builds** until true
WAV/FLAC/MP3 DSP parity and ONNX output checks pass against Rust and
the known Linux reference. The point of this trial is to test the
original upstream C++ code *without maintaining our own DSP port*.

See `native/README.md`, `docs/essentia-cpp-windows-packaging.md`,
`scripts/package_essentia_worker_windows.py`.

The workflow uses MSYS2 MINGW64's native dependency packages.
A fixed Essentia Git SHA is recorded, but the MSYS2 repository packages
are rolling. Their exact versions and import closure are recorded by
pacman and the bundle manifest on every CI run. A passing CI run is not
yet a fully reproducible binary release: release builds need immutable
third-party dependency versions, hashes, notices and a clean Windows
runtime smoke.

Essentia remains AGPLv3. Generated native test packages are
development-only and must not be redistributed as project releases
without a separate licensing audit.
