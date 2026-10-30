"""Compare the Rust FFT/Mel frontend with Essentia's TensorflowInputMusiCNN.

This phase does not load TensorFlow models, share copyrighted songs, or use ONNX.
It compares the exact log-Mel feature frames fed to Discogs-EffNet.

Usage:
  python scripts/compare_mel_essentia.py --audio test.wav --rust-json rust-mel.json

Requires: pip install 'numpy<2' 'essentia==2.1b6.dev1389' (Linux)
"""
import argparse
import json
from pathlib import Path

import numpy as np
from essentia.standard import FrameGenerator, MonoLoader, TensorflowInputMusiCNN


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--rust-json", type=Path, required=True)
    parser.add_argument("--absolute-tolerance", type=float, default=1e-3)
    parser.add_argument("--relative-tolerance", type=float, default=1e-3)
    args = parser.parse_args()

    rust = json.loads(args.rust_json.read_text(encoding="utf-8"))
    assert rust["sample_rate"] == 16000
    assert rust["fft_size"] == 512
    assert rust["hop_size"] == 256
    assert rust["mel_bands"] == 96

    rust_mel = np.asarray(rust["frames"], dtype=np.float64)
    assert rust_mel.ndim == 2 and rust_mel.shape[1] == 96
    audio = MonoLoader(filename=str(args.audio), sampleRate=16000, resampleQuality=4)()
    compute_mel = TensorflowInputMusiCNN()

    reference = []
    for frame in FrameGenerator(audio, frameSize=512, hopSize=256):
        reference.append(compute_mel(frame))
        if len(reference) >= len(rust_mel):
            break
    essence_mel = np.asarray(reference, dtype=np.float64)
    if essence_mel.shape != rust_mel.shape:
        raise AssertionError(f"Shape mismatch: Rust={rust_mel.shape}, Essentia={essence_mel.shape}")

    errors = np.abs(rust_mel - essence_mel)
    worst_flat = int(np.argmax(errors))
    f, b = np.unravel_index(worst_flat, errors.shape)
    mae = float(np.mean(errors))
    max_err = float(errors.max())
    rmse = float(np.sqrt(np.mean(np.square(errors))))
    passed = bool(np.allclose(
        rust_mel,
        essence_mel,
        atol=args.absolute_tolerance,
        rtol=args.relative_tolerance,
    ))

    print(json.dumps({
        "passed": passed,
        "frames_compared": len(rust_mel),
        "bands_per_frame": 96,
        "mean_absolute_error": mae,
        "root_mean_square_error": rmse,
        "maximum_absolute_error": max_err,
        "worst_frame": int(f),
        "worst_band": int(b),
        "rust_value_at_worst": float(rust_mel[f, b]),
        "essentia_value_at_worst": float(essence_mel[f, b]),
        "atol": args.absolute_tolerance,
        "rtol": args.relative_tolerance,
        "essentia_version": __import__("essentia").__version__,
    }, indent=2))

    if not passed:
        raise SystemExit(
            "FAIL: Rust log-Mel features differ from Essentia. "
            "Do not start a library-wide Mood scan."
        )


if __name__ == "__main__":
    main()
