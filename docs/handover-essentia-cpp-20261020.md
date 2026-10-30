# Handover — Essentia C++ frontend / Rust orchestration (2026-10-20)

## 21 October 2026: real Windows kit license audit, 17-package evidence backlog

**Latest release/readiness checkpoint:** The user's already-downloaded
Windows Essentia dev kit passed a real **read-only** integrity audit:

| Observed field | Verified value |
| --- | --- |
| `binary_integrity` | **PASS** |
| Native EXE/DLLs in closure | **100** |
| Installed MSYS2 package owners with version metadata | **77** |
| Valid existing installed/upstream notice-file references | **94** |
| Missing already-referenced notice files | **0** |
| Packages with **no installed** notice files | **17** |
| `distribution_release_status` | **BLOCKED**, manual review required |

Private Windows report:
`D:\LMS\bliss-mood-poc\audit-windows-essentia-20261021-060841\release-readiness-audit-private.json`.
Missing an *installed* notice is an evidence gap, not evidence that
a package lacks a license. The complete list of affected package names
and distribution scenarios A–D are now in the **authoritative**
[licensing/distribution strategy](essentia-licensing-distribution-strategy.md).

**Implemented next engineering gate:** 
`scripts/triage_windows_native_license_gaps.py` runs against the
existing already verified, unmodified test kit. It writes a private
exact-version review register for every missing-notice package with
MSYS2 package metadata (unverified licensing hints), owning DLLs
and manifest-recorded DLL import chains. It never downloads source
or invents SPDX grants. The six new Python regression tests PASS
in both Rust CI jobs. The real Windows-native workflow also calls it
on the actual staged kit and stores a JSON-only report as build
diagnostics; native kit hashes/functional smoke remain under CI.

**Security/distribution gate changed:** Native original Essentia
C++ Windows testing stays enabled but the upload of a new public
100-binary native DLL test ZIP is now **disabled** on this **public**
repository pending explicit redistribution, corresponding-source,
AGPL/FFmpeg, MTG model and notice review. Private-run upload is
additionally guarded by the explicitly named review variable.
Historical publicly accessible test artifacts are **not deleted**;
their status and any earlier distribution obligations require a
separate human decision. Previously downloaded local verified kits
can continue supporting user's offline development and PR #16
similarity investigations.

**Selected distribution approach from existing strategy:**
For eventual general releases prioritize **C** (provide properly
licensed worker source/build instructions and use native system
dependencies) or **D** (standalone Rust DSP with separately
installed FFmpeg) before **A** (shipping full DLL closure).
Scenario **B** still ships the original C++ worker executable and
does not eliminate corresponding AGPL/combination questions.
A separate model download does not grant a license to use the weights.
Technical library reduction needs a fresh minimal-audio C++/FFmpeg
build and fresh *targeted* smoke, never manual removal of old DLLs.

Do not reopen the 100-MP3, controlled PCM or two independently
downloaded FLAC/WAV numeric tests; all of them already PASS for
the Windows test scope. `main` / PR #16 unchanged; #17 Draft.

---

## 21 October 2026: all tested real MP3/FLAC/WAV Windows numeric gates PASS

**Latest authoritative checkpoint superseding historical preflight blockers:**
user's completed **original independent lossless** Bandcamp-source test
`benchmark-bandcamp-lossless-20261020-220117` PASSED.

- Original native **FLAC 48 kHz / 24-bit stereo**: 604.75 seconds,
  608 Essentia/Rust equal Mel patches, genre worst
  **2.019999999991473e-6**, Mood/Theme **7.399999999990747e-7**,
  Voice **3.7999999996651823e-7**.
- Original native **WAV 44.1 kHz / 16-bit stereo**: 356.28 seconds,
  358 patches, genre worst **1.3999999999292356e-6**,
  Mood/Theme **5.149999999995436e-7**,
  Voice **1.360000000005801e-6**. The artwork MJPEG stream does not
  affect the first audio stream probe.
- Both PASS strict unchanged **0.001** maximum absolute class-score
  tolerance, same original C++ versus corrected Rust v5 model-weight
  SHA and class definitions, no patch mismatches. Private report
  `D:\LMS\bliss-mood-poc\benchmark-bandcamp-lossless-20261020-220117\natural-lossless-parity-private.json`
  remains on user's workstation; preserve it. The earlier 420-second
  FLAC preflight rejection is explained by the actual 604.75-second
  duration, and was not a classifier parity failure.
- Previous 100-real-MP3-song/14,500-score four-worker and
  adaptive-enabled-six-worker parity, exact Rust result invariance,
  and controlled 837-patch PCM WAV24/FLAC checks remain PASS.
  **Stop repeated parity rescans of the same dataset.**

**Now implement/verify distribution blockers without distributing
any more binaries:** `scripts/audit_windows_native_release.py`
checks `D:\LMS\essentia-cli-test` read-only: actual PE-x64 and
SHA256 closure, `worker-dependencies.json` and the installed
`NATIVE-PROVENANCE.json` (including available notices and MSYS2
package IDs/versions). Auditor may return `binary_integrity=PASS`
yet **must return `distribution_release_status=BLOCKED`**, because
there is no legal release approval. Tests use entirely synthetic
PE/package manifests. Run the one-block PowerShell and read
release blockers in [release-qualification-gates.md](release-qualification-gates.md).

**Merge/release decision:** numeric Windows Rust-v5 and original
Essentia frontend parity is technically accepted for the test scope,
not globally guaranteed. Keep #17 Draft until review/approvals;
do not publish a native DLL kit as production or assert
MIT/AGPL/FFmpeg/MTG-ONNX license compatibility without a formal audit.
Similarity PR #16 remains separate and can proceed with the existing
locally verified scanner. Do not modify `main` or #16.

---

## 20 Oct 2026: two Bandcamp lossless originals, preflight blocker diagnosed

The user prepared TWO genuine local lossless downloads for the bounded
original-file test: FLAC **48 kHz / 24-bit / stereo**, WAV **44.1 kHz /
16-bit / stereo**, of different songs. The WAV ffprobe inventory also
lists MJPEG (embedded cover artwork); the Python comparator deliberately
uses the first **audio** stream `a:0` and will ignore image streams.
Separate NAS MP3 files for the same song titles exist, but are
**lossy**, cannot be used as bit-identical PCM references, and need
not be rescanned. Do not publish private per-song NAS paths.

**First attempt did not reach audio inference**: local helper raised
`Explicit .flac outside bounded duration/size/rate limits`
inside `select_sources`. The original 48 kHz FLAC samplerate is
allowed, so a default song duration cap of **420 s** or maximum
file size of **150 MiB** was likely exceeded; specific file duration/
bytes were not supplied in the first log. This does **not** change
the previously PASSing controlled WAV24/FLAC test or the 100-MP3 parity.

**Corrected gate in branch:** `scripts/verify_original_lossless_tracks.py`
now reports **actual measured seconds/MiB** and exact exceeded bounds.
For **two explicit** `--track sample.flac --track sample.wav` choices,
a bounded override can use `--max-seconds 1800 --max-file-mib 512`
without broadening automatic NAS search. Longer/larger tracks should
be replaced rather than cropped/transcoded for this original-source
test. CLI score tolerance remains **0.001**; old music, JSON reference
and SQLite sidecars remain read-only.

**Docs:** [release-qualification-gates.md](release-qualification-gates.md)
contains revised local preflight and safe Bandcamp retry. Regression
tests cover long-track rejection detail, file-size thresholds, audio
stream selection despite artwork and the distinction between automatic
and explicit duration hard caps. **Real two-Bandcamp-song parity is
still pending**, not failed numerically.

---

## 20 October 2026: controlled real-song WAV24 / FLAC passed; native library codec test ready

**Actual Windows/NAS cross-codec result from user, not CI fixture:**
`scripts/verify_lossless_codec_parity.py` **PASS** on the already known
837-patch real-song PCM signal. Both 24-bit WAV and FLAC independently
decoded to identical raw PCM (SHA256 and byte count). The
**original Essentia C++ versus corrected Rust v5** maximum class-score
difference is **6.3700000000332935e-6** on *each* format, versus
unchanged **0.001** threshold. Within Rust, WAV-versus-FLAC max
score difference is **0.0**; within genuine Essentia C++, also **0.0**.
Exact full local private evidence:

`D:\LMS\bliss-mood-poc\benchmark-real-wav-flac-v5-20261020-204139\private-codec-report.json`.

This represents one authentic song originally stored as MP3, explicitly
quantized once to WAV24 and then losslessly copied to FLAC. It **does
not establish naturally existing WAV/FLAC library coverage**.
**Do not rerun this already passed test.**

**Next bounded original-file gate**:
`scripts/verify_original_lossless_tracks.py` selects **one actual FLAC
and one actual WAV already present on the original music NAS**.
It searches at most 6000 directory entries and six nesting levels,
without following symlinks. If none is found within this bound, it
stops before running inference; explicit safe relative
`--track` overrides are available. It runs only **two songs × Rust-v5
and original C++** with the existing verified Windows Binaries,
without transcoding or modifying either source. Real WAV reference
ONNX weights / model keys / native C++ worker executable SHA are
checked for identity; 3 heads × (87+56+2) classes per song, same
source audio SHA, same patch counts, and strict score error ≤0.001.
New results written locally to an isolated fresh directory; old v4/v5,
original C++ and 100 MP3 sidecars remain read-only.

[One-block Windows PowerShell and updated release matrix](release-qualification-gates.md)
now contain the exact paths and options. **Six new native-lossless
safety regression tests passed in both GitHub Rust CI jobs**
(`6133fea2ce648f1f1a78df7b747f9d51ec7bdd91`).
Real native FLAC/WAV outcome **not yet established**.

Licensing, independently supplied model-weight rights and multi-OS
packaging remain separate explicit release gates. PR #17 stays Draft;
no edits to PR #16 or `main`.

---

## Post-parity release-readiness checkpoint: WAV24/FLAC and rights (20 Oct 2026)

The previous fixed-four and adaptive-enabled-six worker real 100-song
MP3 numeric checks are **PASSED**. Do not repeatedly analyze those 100
tracks; the original Essentia C++ and Rust v4/v5 sidecars are immutable
references.

**New controlled cross-codec diagnostic in PR #17:**

- `scripts/verify_lossless_codec_parity.py` processes the **already
  saved real 837-patch float32 PCM WAV**, not the NAS music.
  It quantizes **once** to PCM24 WAV; creates FLAC from *that WAV*.
  FFmpeg decodes WAV and FLAC to raw signed PCM24, and their **actual
  decoded SHA256 + byte length must match** before any inference.
- Runs only **four full-song analyses** on those two created files:
  same validated Rust v5 CLI with `--audio-backend rust` and with
  `--audio-backend essentia` plus the existing genuine original C++
  worker. Compares official ONNX SHA256/labels, frontend cache
  fingerprints, all Mel patch counts and all class scores at 1e-3.
- The complete release gate matrix plus a single self-checking
  Windows PowerShell recipe lives in
  [docs/release-qualification-gates.md](release-qualification-gates.md).
  It reuses the directories `benchmark-essentia-real-20261020-160351`,
  `mp3-wav-control-20261020-164836` and
  `rust-v5-one-track-20261020-190110` already present on the
  Windows machine. Do not re-download/rebuild Rust v5 or C++ worker.
- Unit tests `tests/test_verify_lossless_codec_parity.py` exercise
  strict PCM equality, code and model identity, patch counts, and
  tolerance failures. **Five new tests passed in GitHub Rust CI** for
  commit `d4465e48443b0282a2e88c855331ab4d322f0d3e`, both
  Rust-check workflows green. The controlled Windows WAV/FLAC result
  has since PASSED as documented above.
- This is a **controlled codec** test on one authentic music signal,
  *not* evidence of independently sourced FLAC/WAV library tracks.
  Genuine mixed-samplerate naturally occurring lossless examples
  would be the subsequent, explicitly bounded codec gate.

**No redistribution clearance is implied.** The separate
[docs/essentia-licensing-distribution-strategy.md](essentia-licensing-distribution-strategy.md)
still has outstanding AGPL/FFmpeg/ONNX model rights and native DLL
dependency-closure questions. Windows native fixture passing is
functional evidence only. Keep PR #17 Draft, separate from #16/main.

---

## Real 100-song adaptive Rust-v5 run: PASS, numerically invariant (20 October 2026)

**Measured locally by user; real source results, not synthetic unit tests.**
One new Rust-v5 scan of the same 100-song MP3 cohort with
`--workers 6 --adaptive-workers --min-workers 4 --max-workers 8 --threads 1`:

| Metric | Actual result |
| --- | --- |
| Numerical parity vs saved original Essentia C++ | **PASS**, all 14,500 scores |
| Patch-count mismatches | **0** |
| Max absolute score drift vs C++ | **1.2695789337158203e-5** (limit 1e-3) |
| Genre / MoodTheme / Voice max drift | 5.3942203521728516e-6 / 7.12275505065918e-6 / 1.2695789337158203e-5 |
| Compared against fixed-4 Rust v5 sidecar | **PASS, bitwise identical 14,500 class scores**, zero patch differences |
| Adaptive run elapsed | **92.86673710000468 s** |
| Saved fixed-4 baseline elapsed | 183.28881380002713 s |
| Between-run wall-clock speedup | **1.9736756079052322x**, exploratory / unreplicated |
| Initial / final workers; peak active analyses | 6 / 6; 6 |
| Controller changes | **0 up / 0 down**, 32 sampled loads (4 low/28 neutral/0 high) |
| System CPU mean / max | 47.7641% / 67.9338% |
| System RAM max | 84.8146% |
| Rust process working-set max | 999.8516 MiB |
| Minimum available system RAM | 2385.8281 MiB |
| Page-fault counter delta | 10,798,677 (includes **soft faults**, NOT disk paging I/O) |

**Interpretation:** The controller genuinely ran but **never changed its
active limit**. This proves parity with six simultaneous Rust analyses
and controller instrumentation, not performance gains due to adjustment.
Comparing two distinct runs cannot isolate NAS/SMB cache and system load.
An observed 1.97x wall-clock difference vs four workers is larger than
the nominal 1.5x pure-concurrency gain, so uncontrolled conditions
clearly matter. **Do not change controller thresholds solely based on
this observation.** The native Rust policy already has deterministic
high/low-load and cooldown unit tests in `src/parallel.rs`; an actual
forced adjustment under external load was not observed here.

**Preserved user-local private data:**
`D:\LMS\bliss-mood-poc\benchmark-rust-v5-adaptive-20261020-193942\adaptive-parity-and-performance-private.json`
plus `rust-v5-adaptive-workers.db` and raw scanner JSON/stderr.
Original C++, Rust v4 and 4-worker Rust v5 sidecars are unchanged.
Do not rerun scans just to summarize these results.

**Release/next-work judgment:** Real MP3 numerical parity is established
for both fixed 4-worker and adaptive-enabled 6-worker Rust v5 vs the
unchanged C++ reference, and scores are identical between these Rust
runs. PR #17 remains Draft while native packaging, platform/codec scope
and redistribution/license reviews remain open. Performance/control
optimization must not block separate PR #16 similarity work.

---

## Verified 100-song Rust v5 parity / adaptive benchmark (20 October 2026)

**Authoritative real-music outcome from user's local machine:** original
Essentia C++ and corrected original-SRC_LINEAR-compatible Rust **v5**
match on the exact same **100 MP3 songs** when Rust runs with
**four fixed parallel song workers, one ONNX thread per worker**.
All **14,500 class probabilities** and patch counts were compared
(0 mismatched patch counts), with maximum score difference
**0.000012695789337158203**, well below the unchanged
**0.001** gate. Per-head v5 max differences:
Genre **5.394220352172852e-6**, Mood/Theme **7.12275505065918e-6**,
Voice **1.2695789337158203e-5**. Measured Rust four-worker
wall time **183.28881380002713 seconds**. This is a genuine
real-music *numerical* gate pass, not proof of non-MP3 or release/licensing.

**Existing local evidence, do NOT overwrite or re-scan:**
- Four-worker Rust v5 full-feature sidecar
  `D:\LMS\bliss-mood-poc\benchmark-rust-v5-workers4-20261020-191946\round-01-workers-04-rust.db`
  and adjacent `parity-report-private.json`.
- Original C++ and Rust v4 sidecars
  `D:\LMS\bliss-mood-poc\benchmark-essentia-real-20261020-160351\round-01-workers-01-essentia.db`,
  and `...-rust.db`.
- Existing cohort
  `D:\LMS\bliss-mood-poc\benchmark-workers-20261019-060347\sample-100.db`.
- Already vetted v5 Windows scanner
  `D:\LMS\bliss-mood-rust-v5-test\bliss-mood.exe`.
  Original Build.txt contains *PR temporary merge SHA*
  `a6a5c8607064e95d291cc85a0500472ff20bcc4e`;
  parent PR head SHA `9ca4d3d2e248a528008e70c9ba0951902b2acc67`.

**Historical pre-test plan (completed successfully above):** adaptive Rust v5 with
initial 6, min 4, max 8 song workers and exactly 1 ONNX thread each.
New `scripts/verify_rust_v5_adaptive.py` checks old reference
sidecars and fixed-v5 baseline *before running* and then performs exactly
one new adaptive 100-song Rust scan. It validates full original
C++ parity and fixed-four-worker Rust v5 invariance at 0.001,
all original audio/ONNX/fingerprint/patch identities, plus actual
adaptive controller decisions, concurrent analyses, CPU/RAM telemetry,
and exploratory (NOT AB/BA) speedup versus 183.29 s.
Private output and SQLite are preserved even on score failure.

Full **single self-checking PowerShell command** lives in
[real-music compatibility gate](essentia-cpp-real-music-compatibility-gate.md)
under "Adaptive six-worker performance and parity gate".
Use exactly the known private cohort/source-root paths. The actual user
must run this NAS-dependent scan locally; CI can test its synthetic
workflow only, not real music. Unit tests
`tests/test_verify_rust_v5_adaptive.py` are registered in Rust CI.

**Decisions:** The resampler bug is fixed in Rust v5, no tolerance
relaxation, no new C++ scan, no change to PR #16 or main. PR #17 remains
Draft while adaptive throughput, broader platform/codec support and
licensing/distribution details are assessed.

---


Detailed measured pre-cache vs warmed-cache times: [GitHub Actions cache benchmark](github-actions-cache-benchmark-20261020.md).

## CI caching checkpoint — 2026-10-20

To reduce **GitHub Actions build duration** without changing binaries,
three complementary layers are now present in draft PR #17:

1. **Rust:** Existing `Swatinem/rust-cache@v2` is already active in
   `ci.yml`, `windows-binary.yml`, and most other Rust jobs. It was
   added to `native-essentia-windows.yml` with both root and
   `native/rust-mel-reference` workspaces. The Windows fixture, Rust
   unit tests, release binary, CLI smoke tests and checksum checks
   remain mandatory on cache hits.
2. **MSYS2:** `msys2/setup-msys2@v2` already has its own
   **enabled-by-default dependency cache**. We do not duplicate the
   whole MSYS2 install with a custom cache.
3. **Original upstream Essentia C++ Waf build:** Both the Linux
   `native-essentia-cpp.yml` and MinGW
   `native-essentia-windows.yml` now cache the pinned upstream source
   **including Waf's compiled objects**, keyed by the pinned Essentia
   SHA, target OS/toolchain, and a hash of the *installed native package
   versions* generated at the start of the job. There are intentionally
   **no broad restore-keys**. All runs still verify the upstream Git SHA
   and origin URL and execute configure/build/install, native worker
   linkage, PE/DLL verification, and numerical parity. An invalidated
   cache triggers the original complete build automatically.

Caches are an acceleration only, **never the published CLI artifact**.
Do not store private audio, the `bliss.db` library, credentials or
unreviewed ONNX redistribution payloads in GitHub caches. Official
model weights remain downloaded and checksum-validated separately.
Do not remove mandatory checks or change class/model preprocessing
semantics for caching. In the GitHub Actions logs compare the
`Restore ... Waf objects` cache hit/miss and `waf -j 4` elapsed time
between an initial successful cache-producing run and a *subsequent*
run on the same dependency versions; **no speedup measurement exists
yet**.

Potential later enhancement: version the currently untracked
`Cargo.lock` in a **separate reviewed change** to lock Rust
dependencies and stabilize dependency cache reuse. Do not silently
resolve/upgrade dependencies while diagnosing backend parity.
For details see [PR #17](https://github.com/chrober/bliss-mood-poc/pull/17)
and the actual workflow files.

---

## Updated checkpoint — Windows original Essentia succeeds; real-song gate next (2026-10-20)

**This checkpoint overrides the older failed-linker history below.** The
original Windows-x64 worker **did link and passed** the complete synthetic
Windows audio/DSP/model/feature-sidecar/PR16 evaluator handoff. Verified
[run #39421541546](https://github.com/chrober/bliss-mood-poc/actions/runs/39421541546),
source commit `bdb281d3a952775d62f4b29786e687a05471f9b1`;
the 70.7MB development artifact
`bliss-mood-essentia-windows-x64-dev` is available through 2026-11-03.
This proves Windows synthetic compatibility, **not real-library parity**.

**Immediate next task:** run the reproducible [real-music compatibility
gate](essentia-cpp-real-music-compatibility-gate.md) on the *same* bounded
real-music cohort using the exact packaged `bliss-mood.exe`, both
frontends, same models, separate v3 feature sidecars and 1/2 workers.
The benchmark Python tool in this PR now accepts `--source-root`
without `--library-root` for relative Bliss keys, checks strict score
parity and checks that fingerprints are *different* across the two
backends. Keep the original Rust-feature sidecar isolated.

**Sequence:** pass real-music patch/model-score/fingerprint/worker parity
→ review CI and compatibility results → merge #17 to main upon the user's
conditional authorization → bring #16 up to date with the merged backend
→ rerun/extend the independent Genre and Mood Similarity evaluation using
**new C++ feature data**. No production release or native redistribution
until all applicable native dependency licenses are reviewed.

**Read this first in the next ChatGPT session.** This document captures the verified state of [draft PR #17](https://github.com/chrober/bliss-mood-poc/pull/17) originally based on GitHub Actions **historical head `efda3f27e1965d65ebf73fad7de35bcba1dd907a`**. For the newer status, see the first checkpoint below. The docs commits themselves advance the PR head: always re-read the live PR and CI status before editing.

## Latest verified checkpoint — 2026-10-20, branch head `e011e99f1dc38790ec441720b696a2f3fe4602e1`

**This section supersedes the historical pre-handover snapshot `efda3f27...` below.** The branch has advanced. The current reviewed PR #17 is still **Draft / not merged**; verify its HEAD and matching GitHub Actions again when starting the new session, especially after documentation-only commits.

At the reviewed source SHA **six of the eight workflow runs succeeded** (including both Rust-check runs). **Two workflows failed for different reasons:**

| Check | Verified result at `e011e99f1dc3` | Exact evidence |
| --- | --- | --- |
| Rust checks (two runs), Windows Rust x64 binary, Genre parity, Voice parity | **PASS** | [Actions for this commit](https://github.com/chrober/bliss-mood-poc/actions?query=branch%3Afeat%2Fessentia-cpp-worker-backend) |
| Windows native DLL packaging (**synthetic** C++ worker with imported test DLL) | **PASS** | [Run 39389850761](https://github.com/chrober/bliss-mood-poc/actions/runs/39389850761) |
| Original upstream Essentia C++ **Linux** codec/ONNX workflow | **FAIL, external model download only**. Native C++ build, IPC, WAV/FLAC/MP3 decoding and Mel parity already passed in this run. `curl: (28) Connection timeout after 15001 ms` occurred while fetching official ONNX weights from `essentia.upf.edu`; model comparison **did not run on this SHA**. | [Run 39389850681](https://github.com/chrober/bliss-mood-poc/actions/runs/39389850681) |
| Original upstream Essentia C++ **Windows** MinGW64 build | **FAIL at final downstream worker-EXE link**, despite successful upstream `essentia.dll` build and successful worker object compilation. Missing symbols include `essentia::init`, `shutdown`, `Logger::debug`, `ParameterMap::add`. Root cause still unproven (export/import/ABI/link configuration). All downstream real-Windows audio and package checks were skipped. | [Run 39389850876](https://github.com/chrober/bliss-mood-poc/actions/runs/39389850876) |

The established **earlier fully green** Linux C++ → Mel → 1280-D EffNet → 87/56/2 ONNX synthetic WAV/FLAC/MP3 check remains [run 39373185587](https://github.com/chrober/bliss-mood-poc/actions/runs/39373185587). This establishes prior parity, **not** a pass at the newest SHA and **not** Windows parity.

**Immediate action on next session:** inspect actual PE exports/import libraries and verbose final CMake link invocation on the Windows-original-Essentia job; fix the link using upstream/build configuration rather than implementing Essentia DSP locally. In parallel, re-run the Linux native gate when ONNX model origin is reachable, or address fetch reliability without bypassing required model integrity verification. Do not loosen numerical tolerance to conceal a build/network issue.

**Do not conflate:** the 2023 Linux source pin `9ceef0a3a7900ad51eb42aa5b6c6789b4bec6a47` (FFmpeg 4.4) and the unmerged FFmpeg-9 Windows upstream PR #1540 source pin `b0661db99be4a8e2c6fabbe90a996f89786fdd8e`. Neither `essentia-rs` nor a new Rust DSP port is in scope.

## Project, objective and non-negotiable decisions

- Repository: [`chrober/bliss-mood-poc`](https://github.com/chrober/bliss-mood-poc).
- Feature branch: **`feat/essentia-cpp-worker-backend`**; base branch: `main`. PR #17 **DRAFT; not merged**. Do not merge or modify `main` without explicit approval. Do not touch `lms-blissmixer-lab` in this workstream.
- Objective: **reuse the original upstream MTG/Essentia C++ implementation**, *not* `essentia-rs` and not a newly maintained Rust port of its DSP frontend.
- Keep the existing Rust scanner/worker scheduler, optional adaptive worker control, ONNX Runtime model inference, model registry, single SQLite sidecar writer and diagnostics.
- Keep the legacy **`--audio-backend rust` as the default**, with `--audio-backend essentia --essentia-worker <EXE>` explicit opt-in. No silent Rust fallback after a native worker error; no migration/production retagging.
- The library's own audio analysis and model classifications are still *experimental*; synthetic numerical parity does not establish subjective real-music labeling or relevance quality.

## Architecture (what actually runs)

~~~mermaid
flowchart TD
    L["bliss TracksV2 / audio sources (read-only)"] --> R["Rust scanner / optional adaptive worker orchestrator"]
    R --> W1["Rust worker 1: reusable ONNX sessions"]
    R --> WN["Rust worker N: reusable ONNX sessions"]
    W1 <-->|"EFW1/REQ1/RES1: file path ↔ Mel patches"| C1["Original Essentia C++ child process 1"]
    WN <-->|"Same IPC, independent process"| CN["Original Essentia C++ child process N"]
    C1 --> P["16 kHz mono / FrameCutter / TensorflowInputMusiCNN"]
    CN --> P
    W1 --> O["Discogs-EffNet 1280-d → 87 genre + 56 mood/theme + 2 voice"]
    WN --> O
    O --> DB["Single SQLite feature sidecar writer"]
~~~

Each Rust worker owns a long-lived, single-threaded original C++ subprocess, so no cross-thread Essentia object sharing is assumed. The Rust process owns lifecycle, deadlines, bounded in-flight work, child PID/memory observations, model sessions and persistence.

Key implementation:
- `native/essentia_cpp_worker.cpp` — original C++ Essentia `MonoLoader`, `FrameCutter`, `TensorflowInputMusiCNN` behind framed binary protocol. **No TensorFlow execution in C++ child.**
- `native/CMakeLists.txt` — C++ worker and separate protocol fixture; links via `pkg_check_modules(ESSENTIA ... essentia)`.
- `src/essentia_worker.rs` — Rust IPC subprocess reuse/restart/deadline; Windows signed deployment manifest validation and distinct backend fingerprint.
- `src/audio_decode.rs`, `src/preprocess.rs` — current Rust-reference decoder/DSP; keep available for parity and Rust backend.
- `src/features.rs` — ONNX EffNet and 3 classification heads, feature fingerprints and backend selection.
- `src/resources.rs` — process-tree RAM/PID metrics; relevant for multiworker comparisons.
- `scripts/test_native_essentia_protocol.py`, `scripts/compare_native_cpp_end_to_end.py` — real C++ protocol and numerical regression.
- `scripts/package_essentia_worker_windows.py` — recursively resolves Windows PE DLL imports, verifies hashes and writes `worker-dependencies.json`; **not a native compiler**.
- `scripts/benchmark_audio_backends.py` — paired fixed 1/2/4/6-worker Rust-vs-C++ scans, fresh SQLite sidecars, numerical-score consistency; needs bounded local real-audio cohort.
- Relevant CI: `.github/workflows/native-essentia-cpp.yml` (Linux original upstream), `.github/workflows/native-essentia-windows.yml` (Windows *original* C++), `.github/workflows/windows-native-packaging.yml` (**synthetic** Windows PE/DLL packaging), and existing Rust/Windows/Genre/Voice workflows.

## Historical status at `efda3f27...` (superseded by latest checkpoint above)

| Gate | Result | Evidence |
| --- | --- | --- |
| Rust checks / Windows Rust executable | **PASS** | PR #17 head `efda3f27...` CI |
| Genre and voice model-reference parity | **PASS** | Same PR head |
| Windows native subprocess and DLL packaging with real dependent **fixture DLL** | **PASS**, but **synthetic**, not original Essentia | [Windows packaging run 39377836160](https://github.com/chrober/bliss-mood-poc/actions/runs/39377836160) |
| Linux **original Essentia C++** native worker (pinned older upstream), WAV/FLAC/MP3 Mel, EffNet 1280-d, 87/56/2 heads | **PASS** on deterministic synthetic audio | [Original C++ / ONNX parity run 39373185587](https://github.com/chrober/bliss-mood-poc/actions/runs/39373185587) |
| Windows **original upstream Essentia C++ library** built via MinGW64 Waf | **PASS: compilation and DLL linking completed** | [Windows run 39382026896](https://github.com/chrober/bliss-mood-poc/actions/runs/39382026896), upstream step successful |
| Windows **original Essentia C++ worker EXE** link | **FAIL: unresolved Essentia C++ symbols** | Same [run 39382026896](https://github.com/chrober/bliss-mood-poc/actions/runs/39382026896) |
| Actual Windows original-worker audio smoke and closed-DLL bundle | **NOT RUN**: dependent on link fix | Windows CI skipped these steps |
| Actual library A/B 1/2/4/6-worker performance | **NOT RUN** (harness ready) | Local bounded `TracksV2` + music required |
| ARM64/piCorePlayer packaging and validation, licensing audit | **OPEN** | Not production-ready |

**Exactly 7 of 8 checks passed** for head `efda3f27e196...`; the failing gate was **`Native original Essentia C++ Windows x64 (experimental)`**. GitHub job built `build/src/essentia.dll`, installed upstream via `waf install`, and CMake found `essentia` version `2.1-beta6-dev`. The worker object compiled; **final linkage** failed with undefined references, e.g.:

- `essentia::init()` and `essentia::shutdown()`
- `essentia::Logger::debug(...)` and `essentia::ParameterMap::add(...)`
- `essentia::nameOfType[abi:cxx11](...)`, `essentia::loggerInstance`, `essentia::debugIndentLevel`, `essentia::activatedDebugLevels`

This is a **symbol export/import/link configuration issue to investigate**, *not yet a proven root cause*. A successfully created DLL does **not** establish it exported the symbols required by a separate EXE; check both export table and actual CMake linker line before changing source. Read **[focused Windows linker handover](handover-essentia-windows-linker-20261020.md)** for commands and decision tree.

### Upstream version differences (do not conflate)

- **Linux proven reference:** upstream `MTG/essentia` at `9ceef0a3a7900ad51eb42aa5b6c6789b4bec6a47`, Ubuntu 22.04 / FFmpeg 4.4.
- **Windows trial:** upstream `MTG/essentia` at `b0661db99be4a8e2c6fabbe90a996f89786fdd8e` (unmerged upstream PR #1540, supporting FFmpeg 8/9, fetched with `refs/pull/1540/head` and SHA verified), MSYS2 MINGW64 / FFmpeg 9.0.2.
- Windows Waf: `--std=gnu++14 --lightweight=libav,libsamplerate,fftw` to avoid C++17 `std::byte` collisions and irrelevant TagLib/YAML/Chromaprint dependencies. CMake worker similarly sets GNU/MinGW C++14.
- These two upstream releases have **NOT** been numerically proven equivalent. A green Linux run does not clear the new Windows build.

## Next engineering steps, strictly ordered

1. **Inspect Windows library symbol exports and import library** and the `pkg-config`/CMake verbose link command for the generated C++ worker. Determine whether exports are absent, import libraries are absent/empty, or linkage targets the wrong artifact or ABI. Do not presume one explanation.
2. Fix **link/export mechanics only**, favoring build-system flags or an upstream-supported static/shared configuration; avoid forking Essentia DSP algorithms. Add explicit CI diagnostics/checks for symbols and exact linked binary provenance.
3. Obtain a **genuine original-Essentia-linked Windows EXE**, and pass its `EFW1` handshake plus multiple synthetic WAV/FLAC/MP3 requests and child reuse/restart tests.
4. Package the real DLL-closed worker, verify PE import closure, binary hashes and isolated process start. Keep artifacts non-redistributable pending dependency/AGPL license review.
5. Re-run **Windows original Essentia C++ vs production Rust** Mel-patch parity, 1280-d EffNet and 87/56/2 classes with the previously defined codec tolerances. Do not use the fixture-only gate as proof.
6. Only then run actual repeated 1/2/4/6-worker A/B comparisons on the same bounded Bliss cohort with fresh SQLite sidecars, read-only sources and process-tree RAM observability.
7. ARM64/piCorePlayer build/parity, upstream version and license audit before release decisions.

## Existing documentation / workflows to read

- [C++ subprocess/orchestrator architecture](essentia-cpp-worker-architecture.md) — includes Mermaid IPC and worker diagrams, provenance and parity.
- [Immediate Windows linker runbook](handover-essentia-windows-linker-20261020.md) — **next task**.
- [Windows native build trial](essentia-cpp-windows-native-build.md) — note newer verified status in this handover.
- [Windows DLL packaging and licensing](essentia-cpp-windows-packaging.md).
- [Paired audio backend benchmark](essentia-cpp-worker-benchmark.md).
- [Baseline adaptive-worker diagnostics](adaptive-scan-performance-handover.md).
- [PR #17](https://github.com/chrober/bliss-mood-poc/pull/17), [latest failed Windows job](https://github.com/chrober/bliss-mood-poc/actions/runs/39382026896).

## Working conventions and safety constraints

- Read **live** PR head and CI first: the handover describes a verified historical SHA, not necessarily the future tip of the branch.
- Keep changes on `feat/essentia-cpp-worker-backend`; do not merge PR #17 or change `main`. Keep it Draft.
- Prefer reusing upstream original C++, existing Rust multi-worker orchestrator and existing ONNX/single-writer code.
- For Windows PowerShell, wrap **every complete snippet** in a single outer `& { ... }`; use proper error checking.
- This project must not modify original `bliss.db` / NAS music; benchmarking must use read-only, explicitly capped cohorts and fresh sidecars.
- Record exact evidence for passed gates vs failed/skipped; no unsupported claim of Windows original Essentia end-to-end success.
- Be explicit when a CI failure is a new Windows linker issue versus existing green Linux or synthetic-fixture tests.
