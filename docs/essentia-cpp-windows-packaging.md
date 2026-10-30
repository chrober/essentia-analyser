# Windows x64: original Essentia C++ worker packaging

**Actual verified status (2026-10-20):** The **original** Windows x64 Essentia
library and `bliss-essentia-worker.exe` now build, link and process real
synthetic audio. The complete development-only DLL-closure contains **100**
native EXE/DLL files, is SHA256-verified and passes startup/repeated audio
jobs with MinGW removed from `PATH`. WAV/FLAC/MP3 Mel and the full
1280-D EffNet plus 87/56/2 classifier-head comparisons against production
Rust preprocessing all passed in
[Actions run #39413454780](https://github.com/chrober/bliss-mood-poc/actions/runs/39413454780).
This is the real Essentia-backed Windows worker, **not** the synthetic fixture.

For the broader Linux, macOS, Raspberry Pi/piCorePlayer and other
Lyrion-host targets, see [platform support contract](platform-support-lyrion.md).

## Native sources and packaging boundary

- Upstream original Windows Essentia candidate:
  `b0661db99be4a8e2c6fabbe90a996f89786fdd8e` (upstream PR #1540
  candidate, FFmpeg 9 compatible; **not a custom DSP port**).
- MSYS2 MinGW64 original Essentia `essentia.dll` requires Waf's
  `-Wl,--export-all-symbols` export policy and MinGW
  `--enable-auto-import/--enable-runtime-pseudo-reloc` for original globals.
- `scripts/package_essentia_worker_windows.py` inspects actual PE imports
  using GNU `objdump -p`, validates x64 PE architecture, recursively copies
  non-OS DLLs from explicit trusted directories and hashes their bytes.
- **System DLL classification:** Native x64 Windows Python calls the Win32
  `GetSystemDirectoryW` API to identify the real `System32` directory.
  Alongside a conservative well-known OS/API-set allowlist, only an
  architecture-valid PE actually present in the true System32 may be skipped
  as OS-managed. This replaces brittle manual additions (`msimg32.dll`,
  `wsock32.dll`, `gdiplus.dll`, `dwrite.dll`, etc.). Unknown non-OS DLLs
  must resolve from trusted runtime roots; any missing/conflicting DLL,
  wrong architecture, unsafe symlink, MSYS/Cygwin dependency, oversized
  file graph or checksum mismatch fails closed.
- Windows CI invokes the packager with **native Windows Python**, not MSYS
  Python. Final ONNX comparison explicitly reuses the same native Python
  interpreter to which `onnxruntime` was installed; prepending MinGW's bin
  path must not silently select a different `python.exe`.

Example for your **own** Windows x64 environment, after building original
Essentia and the worker (replace paths as appropriate):

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $worker = 'D:\\native-build\\bliss-essentia-worker.exe'
    $objdump = 'C:\\msys64\\mingw64\\bin\\objdump.exe'
    $mingwDllDir = 'C:\\msys64\\mingw64\\bin'
    $essentiaDllDir = 'C:\\msys64\\mingw64\\lib'
    $out = 'D:\\LMS\\essentia-worker-x64-experimental'

    py -3 .\\scripts\\package_essentia_worker_windows.py `
        --worker $worker `
        --objdump $objdump `
        --dll-dir $mingwDllDir `
        --dll-dir $essentiaDllDir `
        --output $out
    if ($LASTEXITCODE -ne 0) { throw 'Original Windows native closure failed' }

    py -3 .\\scripts\\package_essentia_worker_windows.py --verify $out
    if ($LASTEXITCODE -ne 0) { throw 'Windows native bundle verification failed' }
}
```

The generated `worker-dependencies.json` is mandatory for the Rust
scanner's opt-in original Essentia backend on Windows. Runtime hashes guard
against DLL or EXE replacement and change the model/feature cache identity.

## Status of native test binaries and redistribution

**Windows test binaries are built and executed in GitHub Actions.** A passing
CI job proves that its authentic EXE/DLL development bundle runs and
matches Rust numerically. The bundle is not yet a downloadable project
release. The current manifest records `license_inventory_complete=false`
and `release_approved=false`; dependency packages remain rolling MSYS2
inputs and need lockfile/licence provenance review.

The original Essentia library is AGPLv3 and its FFmpeg/other dependencies
have independent conditions. A complete license inventory and notices,
redistribution terms and target-specific release validation are required
before any public Windows installer/EXE-DLL artifact is provided. Do not
commit or upload model weights, audio library content or private DB files.

## Remaining work

1. Revalidate on a bounded set of real (private/local) songs and compare
   fixed 1/2/4/6-worker throughput, peak process-tree RAM and I/O vs Rust.
2. Validate cross-platform targets independently, starting with
   Raspberry Pi 4B / piCorePlayer 11 64-bit and macOS (see matrix).
3. Audit/lock Windows runtime dependency versions, licence notices and
   distribution obligations before external test-bundle delivery.
4. Keep the original Rust backend as default. No merge to main without
   explicit instruction.
