# Windows original Essentia C++ linker — first task after 2026-10-20 handover

**Problem:** The original `MTG/essentia` C++ library **compiles as a DLL** under Windows MinGW64, but the downstream `bliss-essentia-worker.exe` cannot link to several essential C++ symbols. The latest confirmed failure is [run #39389850876](https://github.com/chrober/bliss-mood-poc/actions/runs/39389850876). This run is red; native Windows audio/parity/packaging steps were skipped.

Use the [overall handover](handover-essentia-cpp-20261020.md) first. **Do not merge, modify `main`, or replace the original Essentia DSP with another port.**

## Latest confirmation at source SHA `e011e99f1dc38790ec441720b696a2f3fe4602e1`

**The same Windows linker defect persists** in [native Windows run 39389850876](https://github.com/chrober/bliss-mood-poc/actions/runs/39389850876): the original Essentia MinGW64 DLL successfully builds, the worker source compiles, but its final EXE link fails. The same unresolved `essentia::init()`, `shutdown()`, `Logger::debug()`, `ParameterMap::add()`, `nameOfType()` and logging-variable symbols recur. There is **no evidence yet** that any preceding linker fix actually resolved exports/imports. Earlier [run 39382026896](https://github.com/chrober/bliss-mood-poc/actions/runs/39382026896) is useful historical context, not the current failed CI head.

GitHub PR #17 remains **Draft**, `main` unchanged. The latest Linux native gate has a **separate** external official-ONNX-model HTTP connection timeout, [run 39389850681](https://github.com/chrober/bliss-mood-poc/actions/runs/39389850681), after native Mel parity succeeded. Do **not** label that failure an Essentia DSP regression. Older full synthetic Linux model parity remains green in [run 39373185587](https://github.com/chrober/bliss-mood-poc/actions/runs/39373185587).

**First repair action:** compare the **actual** exported symbols and import archive from the Windows `essentia.dll` against undefined worker object symbols, inspect full `pkg-config --libs essentia` and CMake verbose link arguments, then change only the proven problem. Check for GNU C++ ABI mismatch, incorrect static/import library selection, or MinGW auto-export behavior. Do not introduce fake implementations of missing upstream functions or modify classifier/DSP algorithms to make CI pass.

## Exact failure evidence

- PR #17 baseline head: `efda3f27e1965d65ebf73fad7de35bcba1dd907a`.
- Job: `Native original Essentia C++ Windows x64 (experimental)`, [run 39382026896](https://github.com/chrober/bliss-mood-poc/actions/runs/39382026896).
- Upstream Essentia Waf step: `[298/298] Linking build/src/essentia.dll`, `waf install` succeeded.
- Worker CMake: `Found essentia, version 2.1-beta6-dev`; `[3/4] Building CXX ...essentia_cpp_worker.cpp.obj` succeeded.
- `[4/4] Linking CXX executable bliss-essentia-worker.exe` failed at MinGW64 `ld.exe`.
- Example failures (from actual GitHub log):
  - `undefined reference to essentia::init()`
  - `undefined reference to essentia::shutdown()`
  - `undefined reference to essentia::Logger::debug(...)`
  - `undefined reference to essentia::ParameterMap::add(...)`
  - `undefined reference to essentia::nameOfType[abi:cxx11](...)`
  - `undefined reference to essentia::loggerInstance`, `essentia::debugIndentLevel`, `essentia::activatedDebugLevels`.
- Not observed: actual `MonoLoader` audio behavior on the new Windows binary, nor numerical parity against the Linux reference.

**Hypothesis, not yet verified:** The generated shared `essentia.dll` might not export needed symbols (or might not ship the correct MinGW `.dll.a` import library). Alternative causes include using an empty/wrong import library, the wrong link order, or mismatched ABI/compiler flags. Observe first.

## Files to inspect

- `.github/workflows/native-essentia-windows.yml` — Windows 2022 + `msys2/setup-msys2@v2`; `waf configure --prefix=/mingw64 --std=gnu++14 --lightweight=libav,libsamplerate,fftw` then `waf -j 4` and `waf install`; worker `cmake -S native -B build/windows-native/worker -G Ninja -DCMAKE_BUILD_TYPE=Release`.
- `native/CMakeLists.txt` — `pkg_check_modules(ESSENTIA REQUIRED IMPORTED_TARGET essentia)`, `target_link_libraries(bliss-essentia-worker PRIVATE PkgConfig::ESSENTIA)`. On MinGW the worker CXX standard is 14.
- `native/essentia_cpp_worker.cpp` — calls `essentia::init`, `shutdown`, `AlgorithmFactory::instance` etc.
- Upstream C++ **source pin** for this Windows build: `b0661db99be4a8e2c6fabbe90a996f89786fdd8e` from **unmerged** [upstream PR #1540](https://github.com/MTG/essentia/pull/1540), retrieved from `refs/pull/1540/head` and SHA-checked. **Not** the Linux-proven 2023 commit.

## Add diagnostics *before* changing linkage

Use a short, fail-fast CI stage immediately after Waf install and before CMake build, **in `shell: msys2 {0}`**, to record:

~~~bash
set -euo pipefail
echo "=== Libraries and pkg-config target ==="
pkg-config --variable=prefix essentia
pkg-config --variable=libdir essentia
pkg-config --libs essentia
pkg-config --cflags essentia
find /mingw64/lib /mingw64/bin \
  -maxdepth 2 \( -iname '*essentia*.a' -o -iname '*essentia*.dll' \) \
  -print
echo "=== Built Essentia PE export table ==="
objdump -p build/windows-native/essentia-source/build/src/essentia.dll \
  | sed -n '/The Export Tables/,/The Import Tables/p' | head -n 150 || true
echo "=== Imported library symbols (if produced) ==="
find /mingw64/lib -maxdepth 1 \( -iname '*essentia*.a' \) -print \
  -exec nm -gC {} \; | grep -E \
  'essentia::(init|shutdown|Logger::debug|ParameterMap::add)' || true
echo "=== Verbose downstream link ==="
cmake --build build/windows-native/worker --parallel 4 --verbose
~~~

**Caution:** The Waf output DLL path is a *known log path*; installed DLL/import library names and locations must be measured rather than assumed. Change the source path if upstream Waf changes it. On some GNU toolchains `objdump -p` export headings differ; an empty grep alone is not proof of missing exports. Don't accidentally swallow the build failure with `|| true`: it is only appropriate for optional diagnostics.

Look for the **exact** C++ symbols by both mangled and demangled names (GNU `nm -gC` on objects/libraries, and `objdump -p` for PE exports). Confirm worker object's undefined names match the library's definitions and verify which `-l...` file is actually passed by the CMake linker. Inspect Waf-generated build logs and `essentia.pc`.

## Decision tree

~~~mermaid
flowchart TD
    A["Waf original Essentia DLL builds"] --> B{"Do DLL exports include init/shutdown and factory symbols?"}
    B -->|"No"| C["Investigate Waf MinGW PE export settings / static build option"]
    B -->|"Yes"| D{"Does suitable x64 MinGW import library exist and contain matching names?"}
    C --> E["Make a *build-system-only* correction, preserve upstream algorithms"]
    D -->|"No"| E
    D -->|"Yes"| F{"Does verbose CMake link select that library and use the same C++ ABI?"}
    F -->|"No"| G["Fix pkg-config / import library path / link order / ABI flags"]
    F -->|"Yes"| H["Compare mangled names and dependency closure; reproduce minimal extern caller"]
    E --> I["Rebuild native EXE and run real EFW1/WAV checks"]
    G --> I
    H --> I
    I --> J["Windows real-audio and codec/model parity, THEN native package"]
~~~

**Potential fixes to evaluate (not guaranteed):**

1. If *DLL export table is empty or missing required symbols*: test upstream Waf's MinGW shared export flags (e.g. an explicit GNU linker export policy such as `-Wl,--export-all-symbols`) in a controlled build **without editing DSP algorithm implementations**, and confirm the DLL export list and import lib. Do not claim DLL output alone suffices.
2. If auto-export is unsuitable for the upstream class/API surface, consider upstream's **`--build-static`** option and explicit transitive link dependencies; verify that CMake selects the correct archive. Static linking does not remove third-party licensing obligations, can increase EXE size, and may expose new link-order requirements.
3. If symbols are present in DLL/import archive but the EXE still fails: correct `PkgConfig::ESSENTIA` target/link order, `libessentia.dll.a` selection and/or compiler ABI flags rather than duplicating C++ sources.
4. Do not solve unresolved `essentia::init` by implementing stubs in the worker. Do not weaken numerical parity or silently switch to the synthetic fixture to make CI green.

## Success criteria and continuation

1. Worker links to **original upstream** Essentia C++, not mock fixture.
2. Windows CI confirms actual exported symbols, import linkage/provenance and successful worker executable launch/EFW1 handshake.
3. Runs multiple synthetic WAV requests and confirms process reuse/restart and proper error/deadline handling (where applicable).
4. Runs `scripts/package_essentia_worker_windows.py` on the real EXE, recursively packages true native DLL closure and verifies `worker-dependencies.json`.
5. Runs **real original Windows C++ vs Rust** DSP and ONNX tests: WAV, FLAC, MP3 → Mel patches → 1280-d EffNet → 87/56/2 scores. Linux reference succeeded but did not test this new Windows upstream revision/FFmpeg 9.
6. Maintains seven earlier passing CI gates; PR remains Draft and `main` untouched.

### Important caveats

- A GitHub Actions workflow triggered only by selected `paths` might not rerun on a new handover doc. To validate changes to its own build use its actual workflow path, or an explicit manual `workflow_dispatch`, and always reference the checked SHA.
- MinGW GCC/FFmpeg/MSYS2 repository packages are rolling; `pacman -Q` and the worker SHA/DLL manifest provide observed provenance, not fully immutable release reproducibility.
- Windows PE/MSVC **fixture** smoke [39377836160](https://github.com/chrober/bliss-mood-poc/actions/runs/39377836160) is green but says nothing about original-Essentia exports.
