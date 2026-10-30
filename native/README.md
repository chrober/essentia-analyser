# Original Essentia C++ worker (experimental)

This directory implements a long-lived **original MTG Essentia C++** audio
frontend and a separate, no-Essentia protocol fixture. It does not use
essentia-rs or TensorFlow. Rust retains its ONNX Runtime sessions, single
SQLite writer and adaptive orchestration.

## Prerequisites and native build

Build and install a **pinned upstream Essentia C++ source revision** first,
with MonoLoader, FrameCutter and TensorflowInputMusiCNN plus their
dependencies. The Essentia install must expose pkg-config name "essentia".
A lightweight native build may exclude algorithms; test the exact requested
algorithms before relying on it.

On a prepared Linux host:

~~~sh
cmake -S native -B build/essentia-cpp -DCMAKE_BUILD_TYPE=Release
cmake --build build/essentia-cpp --parallel
./build/essentia-cpp/bliss-essentia-worker </dev/null >/tmp/essentia-hello.bin
~~~

The final command should write exactly four bytes (ASCII EFW1) and then
exit cleanly. If original Essentia logs to stdout during initialization,
the handshake will fail; correct that before attempting integration.

**Windows native packaging is now a separate audited gate**:
[Windows original Essentia packaging instructions](../docs/essentia-cpp-windows-packaging.md).
The Python packaging tool closes the Windows x64 PE/DLL import graph,
checks all native dependency hashes and writes a required Windows
`worker-dependencies.json`. On Windows the Rust scanner checks the
entire manifest and includes its SHA256 in the feature identity in
addition to the EXE hash. Missing DLLs / changed binaries fail early.
**Updated 2026-10-20:** The original upstream **Essentia library now
compiles and links as `essentia.dll` under Windows MinGW64** using the
separately pinned FFmpeg-9-compatible upstream candidate
`b0661db99be4a8e2c6fabbe90a996f89786fdd8e`. The actual
`bliss-essentia-worker.exe` still **fails to link** because symbols
such as `essentia::init()` and `essentia::Logger::debug()` are unresolved.
See [confirmed CI run](https://github.com/chrober/bliss-mood-poc/actions/runs/39382026896)
and [focused linker handover](../docs/handover-essentia-windows-linker-20261020.md).
Genuine native Windows audio parity is therefore still outstanding.
Since this is a separate EXE it does **not** link to the MSVC Rust process.
Neither the x64 Linux build nor a Windows mock-worker run establishes
Pi/aarch64 compatibility.

## Explicit opt-in (Windows PowerShell)

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location 'D:\LMS\bliss-mood-poc'
    $exe = '.\bin\bliss-mood.exe'
    $worker = '.\bin\bliss-essentia-worker.exe'
    & $exe analyze-features 'D:\Music\Example.flac' `
        --models-dir .\models `
        --models moodtheme,genre,voice `
        --audio-backend essentia `
        --essentia-worker $worker `
        --essentia-timeout-seconds 900 `
        --threads 1 --json
    if ($LASTEXITCODE -ne 0) { throw 'Essentia backend analysis failed' }
}
~~~

For scan-features the two new flags are the same; the existing worker
flags and adaptive policy are preserved. Start with **one worker** and
compare the original Mel coefficients with Rust before running a library
scan. The binary is neither inferred from PATH nor silently downloaded.
Missing executable, invalid protocol or native DSP failure does not
fall back to an incompatible preprocessing identity.

The established Rust frontend remains the CLI default. The alternative
backend gets its own preprocessing version and the native executable's
SHA-256 in the feature model fingerprint. Unvalidated results remain
experimental.

## Windows subprocess regression gate (without installed Essentia)

The `.github/workflows/windows-binary.yml` gate now independently builds
the test-only `native/protocol_fixture.cpp` with the Windows MSVC C++
toolchain using `native/protocol-fixture/CMakeLists.txt`, then runs Rust
tests with `ESSENTIA_IPC_FIXTURE_EXE` pointing at that binary. The
tests exercise startup, process reuse, crash/restart, a deliberately hung
request with a hard timeout, and four parallel distinct native processes.
Windows child-PID memory readings are also probed during concurrent work.

**This fixture is not an original Essentia DLL/EXE.** It proves Windows
orchestration and native IPC, not Windows Essentia build compatibility.
The Linux native smoke is separately responsible for compiling and
running genuine upstream Essentia C++ algorithms.

## Transport tests vs DSP tests

native/protocol_fixture.cpp is an isolated test-only native program.
GitHub Actions compiles it without installing Essentia. Rust unit tests
exercise an actual persistent child process, two songs through one
instance, errors, crashes, restart and bounded binary parsing.

The separate native CI gate **has built upstream Essentia C++ and run
real synthetic WAV decoding and patch extraction successfully**. The
current workflow compared all four 128x96 patches to the Rust reference
numerically **successfully** (49,152 floating-point coefficients;
MAE 1.7774358e-7, maximum error 8.4042549e-6; GitHub run
39295089664). This parity test is distinct from the earlier
protocol-only smoke. Full WAV/FLAC/MP3 and ONNX head parity against the original Linux
Essentia C++ worker are **now green**, including 1280 EffNet embedding
dimensions and 87/56/2-class classification heads
([run 39373185587](https://github.com/chrober/bliss-mood-poc/actions/runs/39373185587)).
Windows **original Essentia-linked worker EXE linkage**, native full-codec
parity, ARM64 and real-world acoustic validation remain mandatory gates.
The upstream Windows Essentia library build itself is now complete.

Rust now enforces a hard per-song timeout with
`--essentia-timeout-seconds` (default 900, allowed 1..7200), including
the initial native handshake. On expiry the native child is killed and
reaped, and a subsequent job can start a new instance. The simulated
hanging-child test exercises that behavior. Aggregate process-tree RAM
observation is now implemented for Windows and Linux: every child PID is
registered on spawn and unregistered on exit, with the scan diagnostics
reporting process-tree resident/private memory peaks, child-only memory
peaks, observed native-worker concurrency, and incomplete OS samples.
The adaptive policy still uses **system-wide RAM** (which already accounts
for native children); its thresholds have not changed. Windows/ARM64
timeout validation, real NAS load benchmarks and ARM64 packaging remain
required before unattended large-library deployment.

No merge to main without explicit user approval.
