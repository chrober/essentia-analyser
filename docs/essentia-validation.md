# Essentia numerical validation gates

## Current status

- Windows ONNX CLI runs end-to-end against an NAS track, with complete-track inference.
- Incremental scan was verified using a new test database: pending -> analyzed -> skipped.
- Gate 1 PASS (2026-10-18): 32 x 96 = 3,072 log-Mel values compared with Essentia 2.1-beta6-dev on a deterministic synthetic WAV. Mean absolute error 8.71447e-7; max absolute error 1.85370e-5. Successful run: https://github.com/chrober/bliss-mood-poc/actions/runs/39112792580
- The initial Mel mismatch was caused by a periodic Hann window (denominator N) in Rust; official Essentia uses symmetric Hann (denominator N-1). An additional boundary mismatch affected hop-aligned audio lengths: Rust generated one extra Mel frame and sometimes an extra patch. This was fixed using Essentia's frame-count formula, and preprocessing version v3 intentionally invalidates prior cache model keys.
- Windows release binary, Rust checks, and ONNX synthetic-audio smoke test are green for the corrected commit 32b4a45613060abc89e392cc029e49c4091e22bd.
- Gates 1-3 PASSED for deterministic synthetic audio: Mel frontend, 1280-dimensional embeddings, and 56-class head including four-patch means. This is numerical model parity, NOT real-world mood quality validation or a full-track padding/codec check. Keep validated_against_essentia=false until independent real-world validation.
- The earlier Linux model-smoke workflow failed downloading official weights from essentia.upf.edu (curl timeout), not in the ONNX implementation.

## Gate 1: Deterministic log-Mel parity (automated GitHub Actions)

Workflow: .github/workflows/mel-parity.yml

1. Generate a deterministic 16-kHz, mono, 16-bit WAV on the GitHub runner.
2. Run the model-free Rust mel-dump CLI with 32 frames.
3. Run scripts/compare_mel_essentia.py against the same audio and official TensorflowInputMusiCNN.
4. Compare all 32 x 96 float values with relative and absolute tolerance 1e-3. Report MAE, RMSE, worst frame/band and fail on mismatch.

This tolerance follows an Essentia contributor's example at https://github.com/MTG/essentia/issues/1471 . Passing does not prove agreement on lossy decoding, boundary-frame padding, model embeddings or scores.

Upstream TensorflowInputMusiCNN source configures 512 FFT frame samples, non-normalized window, 96 bands, slaneyMel, linear frequency weighting, unit_tri normalization, shift=1, scale=10000, log10. Verify these numerical details against our Rust approximation before ever changing validation flags.

CI pins Python 3.11, NumPy 1.26.4 and Essentia 2.1b6.dev1389 (non-TensorFlow wheel) on GitHub-hosted Linux. No user music, trained models or local Python installations required for Gate 1.

## Gate 2: 1280-dimensional embeddings (PASSED 2026-10-18)

Workflow: .github/workflows/embedding-parity.yml
First limited-patch run: https://github.com/chrober/bliss-mood-poc/actions/runs/39113628553
Full-length synthetic signal and strict patch count parity PASSED: https://github.com/chrober/bliss-mood-poc/actions/runs/39114494745
Full diagnostic uses --max-patches 64 (nonbinding for this 6-second signal) and --require-full. TensorFlow and ONNX both produce exactly 4 patches, and all 5,120 values agree: MAE=4.52084e-7, maximum absolute error=6.73532e-6, min cosine=0.9999999999626.
Four x 1280 = 5,120 values; MAE=4.460145135e-7, RMSE=7.178915839e-7, max abs=7.0333480835e-6, minimum per-patch cosine=0.999999999964. Both TensorFlow and ONNX produced four aligned patches.

CLI: bliss-mood embedding-dump AUDIO --models-dir models --max-patches 4 --threads 1
Comparator: scripts/compare_embedding_essentia.py

- Export the ONNX encoder's 1280-D embedding vector for each of the first four audio patches. The diagnostic command needs only the ONNX embedding model, not the 56-class head, and does not touch SQLite or modify media.
- On a GitHub-hosted Linux runner, install TensorFlow-enabled Essentia, download the original official fixed-batch-64 discogs-effnet-bs64-1.pb and dynamic-batch ONNX weights (model weights are not committed nor uploaded as artifacts).
- Use a deterministic 6-second 16-kHz mono WAV. Essentia's TensorflowPredictEffnetDiscogs runs with output=PartitionedCall:1, batchSize=64, lastBatchMode=same, lastPatchMode=discard, patchSize=128 and patchHopSize=62.
- Compare four 1280-value vectors with allclose rtol=1e-3 atol=1e-3. Record MAE, RMSE, maximum absolute difference and per-patch cosine similarity. A numeric mismatch fails the job and uploads diagnostics.
- Passing the Mel test only validates its first 32 frames; this longer test exercises patch construction and four positions across the song as well. Do not infer full musical quality or long-track padding parity from this synthetic test.
- Unlike regular analyze/scan, embedding-dump has no persistence effects. validated_against_essentia remains false until all reference gates pass.

Official sources: https://essentia.upf.edu/reference/std_TensorflowPredictEffnetDiscogs.html and https://essentia.upf.edu/models.html .

## Gate 3: 56 Mood/Theme classification heads (PASSED 2026-10-18)

Workflow: .github/workflows/classification-parity.yml
Successful run: https://github.com/chrober/bliss-mood-poc/actions/runs/39114008062
Four x 56 = 224 class probabilities: MAE=2.7806631e-8, max absolute error=1.1920929e-7. Mean-score MAE=1.7828175e-8, max mean-score deviation=5.9604645e-8. Per-patch and aggregated tests both passed.

CLI: bliss-mood classify-embeddings onnx-embeddings.json --models-dir models --threads 1
Comparator: scripts/compare_classification_essentia.py

- Generate a deterministic 6-second 16-kHz WAV and export the first four ONNX Discogs-EffNet embeddings (using the validated upstream preprocessing).
- Use those *exact same* 4 x 1280 float32 embeddings for both the official TensorFlow classification-head .pb through Essentia TensorflowPredict2D and our ONNX Mood/Theme classifier. This eliminates Mel/encoder differences from the classifier comparison.
- Verify 4 x 56=224 per-patch sigmoid probabilities and 56 arithmetic means with allclose rtol=1e-3, atol=1e-3; report worst class, worst patch, MAE and maximum error.
- Require the official 56-class metadata to be present and valid; no database changes, no user music, and no committed model weights.
- An initial synthetically generated signal is not sufficient to validate classification on real-world genres; a diverse corpus and complete-track patch and padding checks follow before production use.

Official reference: https://essentia.upf.edu/reference/std_TensorflowPredict2D.html .

## Gate 4: Full audio codec and sample-rate parity (PASSED 2026-10-18)

Workflow: .github/workflows/full-audio-parity.yml
First diagnostic (intentional failure): https://github.com/chrober/bliss-mood-poc/actions/runs/39115832449
Resampler/MonoMixer diagnosis: https://github.com/chrober/bliss-mood-poc/actions/runs/39116221791
Full comparison PASSED after correction: https://github.com/chrober/bliss-mood-poc/actions/runs/39116616406

The workflow creates deterministic, synthetic musical test clips in four formats, then compares every final 56-class track score from two independent paths:
- Rust: native PCM FFmpeg decode -> Rust 0.5/0.5 stereo downmix -> streaming SRC_LINEAR phase reproduction -> Rust Mel features -> ONNX EffNet -> ONNX classifier -> score means
- Official Essentia: MonoLoader(16000 Hz, resampleQuality=4) -> TensorflowPredictEffnetDiscogs (fixed-batch 64, proper padding) -> TensorflowPredict2D -> score means.

Scores are aligned **by class name**, never by assumptions about JSON/map iteration order; patch counts must match, and every score must satisfy atol=1e-3, rtol=1e-3.

| Deterministic fixture | Patches | Largest absolute score error |
| --- | ---: | ---: |
| mono-16k.wav | 7/7 | 3.7542673e-7 |
| stereo-44100.wav | 8/8 | 3.6311691e-6 |
| stereo-44100.flac | 8/8 | 3.6311691e-6 |
| stereo-44100.mp3 | 8/8 | 1.2959489e-5 |

Root cause: FFmpeg's default stereo downmix used coefficients that were sqrt(2) larger than Essentia's explicit arithmetic average. Additionally, Essentia's streaming libsamplerate SRC_LINEAR converter (quality=4) differs from FFmpeg's default SRC. A PCM-only diagnostic found correct linear sample positions at n*inputRate/outputRate-1, with a special initial-sample rule. The Rust decoder was updated accordingly. This changed the preprocessing identifier to experimental-essentia-audio-v4-unvalidated to invalidate earlier v3 cache records.

FFmpeg and **ffprobe** must both be on PATH at runtime. These tests are limited to the reported fixtures and do not establish all codecs, sample rates, channel layouts, long-track memory/performance or subjective mood quality.

## Gate 5: Controlled real NAS music quality sampling (prepared, not run)

Script: scripts/sample_mood_quality.py. Read-only SQLite selects a deterministic random 12-track subset from a *copy* of bliss.db, then executes the newest Windows analyzer on matching files in the NAS source root and writes a local CSV of 56-class scores and top-five moods. No music or database contents are uploaded by the script. Paths in CSV are private; the default output name is gitignored. After basic QA, review 50-100 musically diverse songs manually. Numerical parity is necessary, but not evidence the model predicts a user's preferred moods.

## Gate 6: NAS/Pi deployment and post-scan automation (not yet implemented)

Check modification-time identity Windows/SMB versus Linux mount, Pi AArch64 ONNX execution and benchmarks under playback, post-library-scan triggering, and plugin isolation. Do not launch the 65,000-track scan before real music quality and Pi stability are understood.

Check modification-time identity Windows/SMB versus Linux mount, Pi AArch64 ONNX execution and benchmarks under playback, post-library-scan triggering, and plugin isolation. Do not launch the 65,000-track scan before preceding gates are satisfied.

## User tasks

CI validation is entirely cloud-hosted. For the next *real music* quality review, run the local sampler against a copy of bliss.db and your NAS share; no Essentia or TensorFlow installation is required on Windows. Only share the CSV if you choose to, as its track keys reveal your music library.
