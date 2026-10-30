# Verified original Essentia C++ baseline — PR #18

**Baseline date:** 22 October 2026
**Validated PR head:** `c5df10b070174c1f844b9feb47b84c1ae8704724`
**Native workflow:** https://github.com/chrober/bliss-mood-poc/actions/runs/39787075901 (all stages PASS)
**Other successful runs at the same SHA:** [Voice](https://github.com/chrober/bliss-mood-poc/actions/runs/39787075964), [Genre](https://github.com/chrober/bliss-mood-poc/actions/runs/39787075939), [Rust checks](https://github.com/chrober/bliss-mood-poc/actions/runs/39787075844), [Windows binary](https://github.com/chrober/bliss-mood-poc/actions/runs/39787075920).

## Verified dependency identity

- Official unchanged MTG/Essentia C++ commit: `dc91e47ed634e0b152d3d0229ec86751bb315473` (14 October 2026).
- Official FFmpeg 9.0.2 source commit: `946fcce07b6dcd0331c8cc609192aeff5e1924f8`, linked libavcodec version `63.1.102`.
- Native CI runner: Ubuntu 24.04. The prebuilt static ONNX Runtime requires newer glibc/libstdc++ than Ubuntu 22.04.
- Native Essentia Waf configuration: upstream lightweight audio preprocessing with FFmpeg, libsamplerate and FFTW; no custom Essentia DSP port.
- Synthetic test-file encoder: separately pinned `imageio-ffmpeg==0.6.0`, reporting `ffmpeg 7.0.2-static`. An independent genuine `ffprobe` CLI supplies reference Rust decoder metadata. These fixture utilities **are not** the FFmpeg 9 libraries linked into native Essentia.

## Observed numerical and integration results

| Gate | Evidence |
| --- | --- |
| Four-patch C++ vs Rust Mel protocol | PASS; 49,152 coefficients; MAE **1.7774358e-07**, maximum error **8.4042549e-06** |
| WAV / FLAC / MP3 synthetic frontend | PASS; Mel MAE **6.3381264e-07–6.3811956e-07**, observed maximum **2.5510788e-05** |
| End-to-end Discogs EffNet + Mood + Genre + Voice comparisons | PASS on the same synthetic audio/official ONNX files |
| Production Rust scanner + original Essentia child processes | PASS |
| Fixed 1, 2 and 4 workers and adaptive mode initialized at 2 | PASS; observed peak active analyses 1, 2, 4, 2 |
| Stored score blobs and pooled 1280D embeddings across four worker configurations | **Exactly identical** |

In the original eight-song smoke, `adjustments=[]`. This is expected because
the conservative controller requires at least **24 completed tracks** and
**20 seconds** from its last capacity adjustment. Successful entry into
adaptive mode **does not demonstrate real dynamic resizing**.

## Real adaptive controller resize: verified native integration

The [extended native run 39791414361](https://github.com/chrober/bliss-mood-poc/actions/runs/39791414361)
at commit `38426ab4281fabb4e6d95e5841122782c6febf81`
**passed** every native CI stage, including the additional real adaptive
test using **36 distinct synthetic five-minute WAV inputs**. The original
C++ worker was used for both separate, fresh SQLite scans; only the
Mood/EffNet ONNX head was selected to keep this gate bounded.

- Fixed 2 workers: **32.493 s** total wall time.
- Adaptive initial 2 workers, bounds 1–3: **32.932 s**.
- The real production controller made **one legitimate 2 → 3 increase
  after 27 completed songs**. Its measured system CPU at that decision
  was **51.07%** and RAM **7.95%**, consistent with the existing
  sustained-headroom threshold. The observed peak active analyses and
  in-flight jobs both reached **3**.
- Nine interval-based CPU/RAM observations were recorded: **seven low
  load** and **two neutral**, with six observations below the 24-song
  threshold and three at/above it. The untouched 20-second cooldown
  expired before the change.
- Exactly identical per-song classification bytes and complete
  normalized 1280D song embeddings were written by both modes.
  **All assertions passed.** No synthetic CPU load or test-only
  controller overrides were used.

This is the **first observed real scanner worker resize**, not an
evaluation of performance improvement. The adaptive run took
**0.439 s longer** in these two unpaired sequential shared-CI runs.
Uncontrolled runner conditions and repeated synthetic tones do not
support interpreting that difference as a policy slowdown, either.
A representative, balanced local music benchmark remains required.

## Remaining qualification

1. **Observed dynamic resizing is qualified for the synthetic native CI cohort**
   (36 songs, 2 → 3 after the 27th completed song). Separate validation
   of adaptive scaling down under pressure and real music/NAS load remains.
2. For operational performance, use a deliberately bounded representative
   local cohort: fixed **1/2/4/6** workers and adaptive, order balanced
   across repetitions, fresh sidecars, matched binaries/models and track
   sets, exact output parity, end-to-end time including startup and
   preworker resource baseline, and tree memory measurements. CI sine tones
   do not establish NAS throughput.
3. End-user binaries need a separate license/distribution review for
   FFmpeg, original Essentia, transitive libraries, ONNX Runtime, and
   platform-dependent ABI constraints. A green CI run is not a release.

PR #18 is stacked upon PR #17 and does not itself update main or the
PR #16 similarity research work.

## 27 October 2026: completed private 100-song NAS benchmark and priority confound

The bounded local native C++ experiment completed **ten real-music scans**
(two reversed-order repetitions of fixed 1/2/4/6 and adaptive 2–6),
with strict, exactly equal Mood/Genre/Voice feature blobs and pooled
1280D embeddings. Median end-to-end wall times in seconds:
fixed1 **282.126**, fixed2 **277.649**, fixed4 **110.803**,
fixed6 **93.417**, adaptive2–6 **116.852**. Adaptive increased
from 2 to 6 workers in four adjustments in **each** repetition.
The maximum private process-tree memory in MiB was 226.922 (fixed2),
419.023 (fixed4), 657.281 (fixed6), and 552.539 (adaptive).
These results are user-supplied aggregate diagnostics; **no private
music, manifest, or source SQLite data is stored in git**.

IMPORTANT: the old scanner only lowered Win32 priority for auto/adaptive,
so fixed modes normally ran at `Normal` and adaptive at `BelowNormal`.
The experiment therefore combines **priority and worker scheduling
effects**, and it cannot establish which caused the difference.

The follow-up control is specified in
[Windows native worker priority study](native-worker-priority-study.md):
`scan-features --priority normal|below-normal`, real Win32
scanner/child process class reporting, and strict equal-priority
validation in `scripts/benchmark_native_adaptive_manifest.py`.
That script now defaults to **Normal for all five configurations**,
without changing the public scanner's default behavior for legacy
calls where `--priority` is omitted. An identical-priority real
music benchmark is **not yet measured**; use a new verified Windows
binary for this CLI flag, never the previous artifact that lacks it.

## Local real-music performance benchmark (not executed in CI)

The standalone [native fixed-vs-adaptive benchmark](../scripts/benchmark_native_adaptive_manifest.py)
takes an **existing intentionally bounded 30–500-track** Bliss TracksV2
cohort database and exercises the original native C++ backend in a
balanced, deterministic order: fixed 1/2/4/6 workers and adaptive
(initial 2, limits 1–6) twice, with a reversed order on the second round.

Run this only on the machine that can read the sampled music and has
the tested native worker and official ONNX models. For example,
from the repository root (paths are illustrative and must be replaced):

```powershell
python scripts/benchmark_native_adaptive_manifest.py `
  --cohort-db "C:\\path\\sample-100.db" `
  --analyzer "C:\\path\\bliss-mood.exe" `
  --essentia-worker "C:\\path\\bliss-essentia-worker.exe" `
  --models-dir "C:\\path\\models" `
  --source-root "C:\\path\\music" `
  --output-dir "C:\\path\\benchmark-native-adaptive" `
  --plan-only
```

The benchmark derives a UTF-8, source-relative `selected-tracks.txt`
manifest from the **existing 100-key TracksV2 sample**, rather than
running the full Bliss scanner. This is essential: the Rust CLI deliberately
rejects `--embedding-dir` with `--bliss-db`. A sample database containing
absolute LMS paths needs `--library-root` for the **benchmark's local
manifest conversion**; `--library-root` is never passed to the
manifest-mode Rust scanner. Every selected music path and normalized
manifest identity is checked before model execution. Use
`--expected-tracks 100` to demand the exact historical sample size.

The numerical gate compares **all per-track/head score blobs** (100 songs
times 3 model heads = 300 independent classification rows), all official
model fingerprints, and the **complete pooled 1280D embedding JSON** for
each song. It fails on one changed classification head; the simpler
single-model synthetic helper must never be reused for this 3-head check.
The Python safety tests are integrated into the Rust checks workflow.

Remove `--plan-only` to run the full experiment. `--source-root` is
appropriate for relative `TracksV2.File` keys; add `--library-root`
only if the preexisting keys include an absolute LMS prefix that needs
remapping. Output must be new/empty; each configuration receives a fresh
SQLite sidecar and embedding directory. Scores, head fingerprints and
entire pooled 1280D embeddings **must match exactly** between modes.
The tool writes a local-only `summary.json`, `runs.csv`, and complete
per-run scanner logs, including controller adjustments and process-tree
memory diagnostics. It also verifies that the sampled input Bliss
database hash does not change.

**The script is prepared but real-music benchmarking has not been
run here** because the user's music and local native binaries are not
available to this session. Do not claim throughput gains, or upload
raw local reports or the private cohort database to the repository.
