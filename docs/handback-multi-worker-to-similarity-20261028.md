# Handback: static native multi-worker song analysis → Similarity PR #16

**Prepared 28 October 2026.** This file is the integration handback for the separate [Similarity Metric Evaluation PR #16](https://github.com/chrober/bliss-mood-poc/pull/16). PR #16's source, metrics, human listening comparisons and measurements are **not modified** by this work.

> **Integration complete and source-tree verified (28 October 2026):** Static native multi-worker CLI was squash-merged to `main` as [`783b05761b6b322a85753acded63ffe336874a6d`](https://github.com/chrober/bliss-mood-poc/commit/783b05761b6b322a85753acded63ffe336874a6d) in [PR #20](https://github.com/chrober/bliss-mood-poc/pull/20). The merged Git *tree SHA* (`60695657fad43d00e6a080ba3a617d428e172f97`) was compared through GitHub against the complete CI-verified PR head `da8fecee23930c2e52abcb473a62b8178b2d5474`, and **they are identical**. This establishes source-tree identity for the tested scanner, despite the different squash-merge commit SHA. Native third-party DLL redistribution remains BLOCKED; source merge is not license clearance.

## What is integrated and what is deferred

The source integration combines [native Essentia C++ backend PR #17](https://github.com/chrober/bliss-mood-poc/pull/17) and stable functionality from [manifest/parallel embedding PR #18](https://github.com/chrober/bliss-mood-poc/pull/18) via [static integration PR #20](https://github.com/chrober/bliss-mood-poc/pull/20). Components include trusted persistent native C++ DSP worker IPC, reused model sessions for shared EffNet and Mood/Theme, Genre, Voice, a bounded fixed-capacity Rust worker coordinator, exactly one transactional SQLite writer, Bliss-catalog selection or read-only track manifest, resume/skip, private sidecar storage, strict path identity and 1280D normalized song embeddings. See [architecture and CLI guide](multi-worker-song-analysis-final.md).

**Not integrated:** ongoing worker count changes, experimental `--adaptive-policy resource/autotune`, `--adaptive-workers` and related min/max/song-gates, the isolated ONNX worker prototype and associated adaptive research in [PR #19](https://github.com/chrober/bliss-mood-poc/pull/19). Its four-campaign research log is [archived on that branch](https://github.com/chrober/bliss-mood-poc/blob/feat/ram-safe-online-autotune/docs/autotune-real-music-e2e-findings-20261028.md); the branch should not be deleted.

## Version and binary chain of custody

- **Integration PR:** #20; original stable source base `c4db3a5aa948f67ecbdeece435f479871ab9f496` (PR #18, which contains PR #17).
- **Actual integrated source commit on `main`:** `783b05761b6b322a85753acded63ffe336874a6d`, which has Git tree `60695657fad43d00e6a080ba3a617d428e172f97`.
- **Exactly source-tree-identical verified PR head:** `da8fecee23930c2e52abcb473a62b8178b2d5474`; this was the successful GitHub Actions checkout source for the CLI and native Linux checks. `main` squash merge changes the Git commit identity but **not one file in the tree**. Later documentation-only commits will change `main` HEAD, not the originally qualified scanner code.
- **Windows x64 binary:** [Windows CI run #40758319812](https://github.com/chrober/bliss-mood-poc/actions/runs/40758319812) **SUCCESS**, artifact `bliss-mood-windows-x64`, source-HEAD exactly `da8fecee23930c2e52abcb473a62b8178b2d5474`. Artifact ZIP SHA256 (not EXE) `d8a34f8448c6db8faff2e2560f0c332997c875c2c2ae6628a4094a3f643c200d`. Download the artifact from that run (not simply the latest branch build), verify `BUILD.txt` and `SHA256SUMS.txt` against the actual executable. **EXE SHA256 has not been independently extracted in this handback and must not be invented.**
- **Rust + Clippy:** [#40758319810](https://github.com/chrober/bliss-mood-poc/actions/runs/40758319810) **SUCCESS**; **native original Essentia C++ Linux** [#40758319837](https://github.com/chrober/bliss-mood-poc/actions/runs/40758319837) **SUCCESS**, including fixed-worker concurrency/parity; **Genre** [#40758319838](https://github.com/chrober/bliss-mood-poc/actions/runs/40758319838) **SUCCESS**; **Voice** [#40758319821](https://github.com/chrober/bliss-mood-poc/actions/runs/40758319821) **SUCCESS**; **Windows native DLL packaging fixture (no native library distribution)** [#40758319841](https://github.com/chrober/bliss-mood-poc/actions/runs/40758319841) **SUCCESS**.
- **Experimental original Essentia C++ native Windows integration gate:** [#40758319829](https://github.com/chrober/bliss-mood-poc/actions/runs/40758319829) **FAILED**, but **only at the independent PR #16 evaluator fetch step, after native C++ compilation**: the workflow fetched a moving PR #16 head while expecting evaluator snapshot `4b397c9310a7e82f0e2e723b11954475b41c3e10`. An even earlier iteration failed because external Essentia PR #1540 moved from upstream `b0661db99be4a8e2c6fabbe90a996f89786fdd8e`. Both dependencies are now pinned by immutable SHA. Follow-up [#40760885061](https://github.com/chrober/bliss-mood-poc/actions/runs/40760885061) on documentation/CI [PR #22](https://github.com/chrober/bliss-mood-poc/pull/22) validates the corrected external fetch and the remaining native Windows compatibility steps; **do not claim it passed without checking the actual run conclusion**. The successful regular Windows-x64 CLI artifact [#40758319812](https://github.com/chrober/bliss-mood-poc/actions/runs/40758319812) is a different build and does not constitute approval to redistribute a native Essentia/FFmpeg dependency kit.
- **Executable SHA256:** read from the verified artifact's `SHA256SUMS.txt` and compare locally with `Get-FileHash`; do not substitute the GitHub ZIP artifact digest for the executable digest.
- **`BUILD.txt` checkout/source SHAs:** must agree with the verified source / build provenance for that exact artifact, including any merge-commit semantics.
- **Native worker EXE, models and label mappings:** independently fingerprint with SHA256 and record versions on the private machine. The scanner ZIP does **not** authorize or guarantee distribution of original Essentia native third-party dependencies.
- **Numeric parity:** use only the explicit scopes of the successful workflow IDs above. Historical PR #17/18 and PR #19 results are separate provenance; they do not substitute for this source-tree verification.

## Windows provisioning and safe run

Retrieve the binary from the **successful final-commit Windows x64 workflow** under [Actions → Windows x64 binary](https://github.com/chrober/bliss-mood-poc/actions/workflows/windows-binary.yml), artifact `bliss-mood-windows-x64`. Extract to a new versioned local folder, verify `BUILD.txt` / `SHA256SUMS.txt` / `Get-FileHash`. Obtain official ONNX weights and JSON label maps separately. Install `ffmpeg` and `ffprobe` and provision the original Essentia C++ native worker **locally under an independently reviewed dependency/license regime**; do not publish or share unapproved native EXE/DLL bundles.

Use new **private** sidecar/embedding paths, never the original Bliss database as an output and never the user’s public audio/model directory. A manifest contains exact source-relative `TracksV2.File` keys, one per line, forward slash format, no duplicates or absolute paths. An example command after setting paths:

```powershell
$exe = '.\bin\windows-x64\VERIFIED\bliss-mood.exe'
$audio = 'D:\Music'
$native = '.\native\bliss-essentia-worker.exe'
$manifest = '.\private-similarity-cohort.txt'
$sidecar = '.\private-similarity-features.sqlite'
$embeddings = '.\private-similarity-embeddings'
New-Item -ItemType Directory -Force $embeddings | Out-Null
& $exe scan-features `
  --tracks-file $manifest --source-root $audio `
  --db $sidecar --embedding-dir $embeddings `
  --models-dir '.\models' --models moodtheme,genre,voice `
  --audio-backend essentia --essentia-worker $native `
  --workers auto --threads 1 --max-errors 3 --json
```

To read the Bliss database rather than a manifest, replace `--tracks-file` with `--bliss-db ...` and **omit `--embedding-dir`** (embedding export requires an explicit manifest). For a reproducible fixed worker count, replace `--workers auto` with `--workers 1`, `2` or `4`; never request more than process-visible logical CPUs. `--workers auto` is calculated **once** from visible logical CPUs and caps at eight; it is not throughput autotuning. The **default is 1**. Explicit non-native `--audio-backend rust` remains available but can yield distinct numerical DSP behavior; do not mix backend provenance in similarity evaluation.

Resume should skip already completed exact matches. A deleted embedding triggers only the missing output regeneration; a conflicting/corrupted output is an error, not an authorization to overwrite. Verify output sidecar schema and hashes and preserve the source manifest and model/native/CLI fingerprints privately for reproducibility. Use **read-only original Bliss/audio inputs**; avoid sensitive paths in public benchmark reports.

## Numerical evidence and constraints

- The original C++ / earlier Rust-v5 parity work reported max absolute score tolerance **0.001** on its selected 100-song scope; this is *tolerance-based comparison*, **not** a bitwise equality statement.
- Synthetic real-ONNX parity gates cover fixed 1/2/4 serialized score bytes and pooled 1280D JSON representation, with separate manifest resume/corruption tests. Exact CI results and job scopes from the **final integrated commit** must be recorded after merge.
- New source should preserve Mood/Theme **56D**, Genre **87D**, Voice **2D**, and normalized pooled audio embedding **1280D**, without changing model identities, patch count algorithm, source path identity or aggregation.
- The four experimental 100-song campaign reports (40 full scans) reported exact per-song output parity and different wall-time medians; they do **not** validate throughput benefit for an online controller or establish an optimal fixed worker count on arbitrary hardware.
- Only actual tested OS/architecture combinations can be described as verified. Windows CI build alone is not a native C++ Windows redistributable release approval.

## Legal/distribution warning — explicit and unresolved

The native development-kit license inventory has `license_inventory_complete=false`, `release_approved=false`, `distribution_release_status=BLOCKED`, including **17 native package notices still missing** from the installed collection. Native Essentia licensing, FFmpeg-linked dependencies, Rust transitive dependencies and third-party model notices/source obligations require independent compliance review. **The user explicitly requires source integration into `main` while retaining this documented risk; no unaudited EXE/DLL bundle may be publicly distributed as a result.** See [license strategy](essentia-licensing-distribution-strategy.md) and keep platform packaging gates intact.

## Dedicated prompt for PR #16

> Continue the **Similarity Metric Evaluation** in Draft PR #16 of `chrober/bliss-mood-poc`. First read `docs/handback-multi-worker-to-similarity-20261028.md` and `docs/multi-worker-song-analysis-final.md` from the actual `main` commit. Confirm the exact verified Windows x64 source/build/EXE SHA256 and native worker/model hashes, without modifying private Bliss/music inputs. Use `scan-features --tracks-file` with `--audio-backend essentia`, all three ONNX heads and `--embedding-dir` to prepare pooled 1280D song embeddings using `--workers auto` or a deliberately chosen fixed worker count, `--threads 1`. Do not work on dynamic worker autotuning, PR #19 or process isolation. Resume the planned mathematical and subjective comparisons of Mood/Genre/Embedding similarity metrics in PR #16. Do not change its existing human ratings and dataset unless explicitly instructed. Respect documented license/distribution and numerical parity limits. If the final binary/merge is still pending, report that honestly rather than substituting an experimental PR #19 build.

