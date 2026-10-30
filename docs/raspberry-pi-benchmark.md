# Raspberry Pi 4 / piCorePlayer feasibility benchmark

Target: Raspberry Pi 4B running piCorePlayer 11.1.0 with Lyrion Music Server.
**Status: proposed benchmark, not a measured result.**

## Constraints

- CPU-only ONNX inference on Cortex-A72; no supported NPU is available.
- piCorePlayer 11.1.0 offers both 32-bit and 64-bit images; the project targets **aarch64** first.
- Prebuilt ONNX Runtime binaries might not link on piCorePlayer because of the platform-specific shared library / libc dependencies. Investigate a native or cross-build if needed.
- Running a second application must not degrade Lyrion responsiveness or audio playback.

## Test configuration

On the Pi:
```sh
uname -m
getconf LONG_BIT
free -m
cat /etc/os-release
```

Record the Pi model, installed RAM, pCP image architecture, storage medium, CPU governor, temperatures, and whether audio is actively playing.

## Proposed measurements

Use the *same* 3–4 minute lossless track on Windows/x86_64 Linux and the Pi (same SHA-256). With models already downloaded, run:

```sh
nice -n 15 ./bliss-mood analyze song.flac --models-dir ./models --max-patches 10 --threads 1 --json
nice -n 15 ./bliss-mood analyze song.flac --models-dir ./models --max-patches 60 --threads 1 --json
nice -n 15 ./bliss-mood analyze song.flac --models-dir ./models --threads 1 --json
```

The JSON reports the timings of PCM decoding, mel feature extraction, model loading, ONNX inference, and total run time. The `--max-patches` option only limits **inference**; decoding and feature extraction still run on the complete song. Repeat each run (cold and warm) and record peak resident memory, CPU temperature/throttling, and any Lyrion responsiveness problems. Compare `--threads 1` against `--threads 2` only if single-thread testing is stable.

## Decision gates

1. Does the entire ONNX pipeline load and run on piCorePlayer ARM64?
2. Are mood outputs numerically consistent with the validated desktop implementation?
3. Is peak RSS acceptable relative to free memory *while Lyrion is running*?
4. Is the Pi responsive during active playback with the worker at low priority?
5. How many complete songs per hour can be analyzed without throttling?

If either compatibility or performance is poor, **do not force on-device inference**. Run batch analysis on another machine and let Lyrion consume cached JSON / SQLite sidecar values only.

## Potential optimizations (only after Essentia parity)

- Reduce patches per song using a documented sampling strategy and quantify prediction drift.
- ONNX quantization, after accuracy comparison.
- Reuse decoder output shared with bliss-rs.
- Experiment with `tract` to avoid ONNX Runtime deployment dependencies.
- One worker process, explicit one- or two-thread CPU cap, `nice`, idle windows, and caching.
