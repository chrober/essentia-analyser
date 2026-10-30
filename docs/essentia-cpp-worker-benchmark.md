# A/B benchmark: Rust frontend versus original Essentia C++ subprocess

**Status:** reproducible runner implemented; no new real-library measurements
have been taken in this PR. Run locally only after numeric codec + ONNX
parity is green and a native Essentia worker binary is installed.

## What is compared

Both variants use the **same Rust scanner, adaptive-worker-independent fixed
scheduling, ONNX models, track selection, single SQLite writer and 
generic \`scan-features\` command**. Only DSP frontend changes:

- \`rust\`: current FFmpeg -> native Rust Mel preprocessing -> ONNX Runtime.
- \`essentia\`: native original C++ MonoLoader/FrameCutter/
  TensorflowInputMusiCNN child per Rust worker -> same ONNX Runtime.

The experiment uses paired fixed worker settings **1 / 2 / 4 / 6** and
AB/BA backend order on repeated rounds; it randomizes the worker-count
order deterministically per round. Every run writes to a **new SQLite
sidecar**; reused feature caches are explicitly forbidden. No
\`bliss.db\`, music files, or model files are written.

Choose a bounded, representative \`TracksV2\` subset such as the existing
100-key \`benchmark-workers-20261019-060347/sample-100.db\` fixture. The
runner refuses source cohorts outside **2..500 eligible unique tracks**.
It records the SHA-256 of that input fixture before and after all runs
and refuses a nonempty results directory.

Each run writes structured \`scan-features --json\` diagnostics and stderr
logs. Every Rust/C++ pair is checked for identical set of
\`(TracksV2.File, model_id)\` keys, equal patch counts, equal class-vector
dimensions and maximum output-score difference under the configured
threshold (default 1e-3). It compares **scores**, not model keys, because
the backend fingerprint intentionally differs. A parity failure stops
the experiment: do **not** rank throughput of inconsistent backends.

## Example: Windows/PowerShell

Use the **same local models and same music source** for all runs. Ensure
that the native \`bliss-essentia-worker.exe\` has its licensed upstream
Essentia C++ dependencies correctly installed (its Windows packaging
is still under validation). This script is intended to run on the
user's development PC; no personal audio or SQLite artifacts are
uploaded to CI.

~~~powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location 'D:\LMS\bliss-mood-poc'

    $benchmarkArgs = @(
        'scripts/benchmark_audio_backends.py',
        '--cohort-db', 'benchmark-workers-20261019-060347/sample-100.db',
        '--analyzer', 'bin/bliss-mood.exe',
        '--essentia-worker', 'bin/bliss-essentia-worker.exe',
        '--models-dir', 'models',
        '--source-root', '\\192.168.1.100\music',
        '--output-dir', 'D:\LMS\essentia-cpp-benchmark-20261020',
        '--models', 'moodtheme,genre,voice',
        '--workers', '1,2,4,6',
        '--repeats', '2',
        '--seed', '20261020'
    )

    py -3 @benchmarkArgs
    if ($LASTEXITCODE -ne 0) {
        throw 'A/B benchmark or numerical score parity failed'
    }
    Get-Content 'D:\LMS\essentia-cpp-benchmark-20261020\summary.json'
}
~~~

Use an **unused** output directory for each independent benchmark.
When \`TracksV2.File\` contains absolute source paths, supply both
\`--library-root\` (old prefix) and \`--source-root\` (current root);
when keys are relative, only \`--source-root\` is necessary.

## Report interpretation

\`summary.json\` contains every raw run with:
- Elapsed wall time and songs per minute.
- CPU average and maximum system RAM pressure.
- Rust-only working set and combined Rust+C++ working-set/private-memory
  high-water observations.
- Maximum number of native child processes and incomplete RAM samples.
- Cross-backend per-score maximum/mean differences and patch-count parity.
- Median elapsed seconds, throughput and maximum observed RAM per backend
  and fixed worker count.

\`runs.csv\` is a small spreadsheet-friendly overview. Each run's fresh
\`*.db\`, full \`*.json\` and \`*.stderr.txt\` are retained locally. Review
these on failures. Raw test directories may contain personal
\`TracksV2.File\` keys; **never commit or upload them**.

**Caveats:** the controller samples RAM after completed songs, so the
reported maximum is an observed high-water sample, *not* a kernel-level
peak RSS; summed resident pages can double-count shared mappings.
Network cache, CPU temperature, native dependency version and music
library traffic also affect results. Workload order is balanced, not
a substitute for repeated cold-/warm-cache trials. This runner does
not by itself validate ARM64/piCorePlayer or prove music similarity
quality.

Before selecting a default backend, require equivalent model outputs,
stable Windows and Linux native builds, reproducible throughput/memory
results and a separate license/dependency deployment review.
