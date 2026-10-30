#!/usr/bin/env python3
"""Read-only original Essentia C++ -> ONNX end-to-end parity regression.

The Rust frontend is the real production src/audio_decode.rs +
src/preprocess.rs, compiled in native/rust-mel-reference without ORT to
avoid Ubuntu 22.04's incompatible prebuilt ort-sys static glibc ABI.
The same official ONNX weights run on patches from both frontends in Python
ONNX Runtime. This validates model output equivalence caused by the two DSP
pipelines, not Rust-ort binary ABI or real-world musical labeling quality.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
from test_native_essentia_protocol import exact, request

AUDIO = ("mono-16k.wav", "stereo-44100.wav",
         "stereo-44100.flac", "stereo-44100.mp3")
HEADS = {
    "genre": ("mtg_jamendo_genre-discogs-effnet-1.onnx", 87),
    "moodtheme": ("mtg_jamendo_moodtheme-discogs-effnet-1.onnx", 56),
    "voice": ("voice_instrumental-discogs-effnet-1.onnx", 2),
}
EMBEDDING = "discogs-effnet-bsdynamic-1.onnx"
ABS_TOLERANCE = 1e-3
# Lossy MP3 decode differs slightly between FFmpeg's PCM conversion and
# Essentia's FFmpeg-backed native MonoLoader. The measured error is very sparse
# (MAE ~1.36e-5; max ~3.2e-3 on the deterministic fixture). Enforce BOTH
# bounds rather than weakening WAV/FLAC or any model-output thresholds.
MP3_MEL_MAX_TOLERANCE = 5e-3
MP3_MEL_MAE_TOLERANCE = 3e-5


def rust_reference(executable, path):
    result = subprocess.run(
        [str(executable), "mel-dump", str(path), "--max-frames", "1024"],
        check=True, text=True, capture_output=True, timeout=120,
    )
    parsed = json.loads(result.stdout)
    frames = parsed["frames"]
    if (parsed["total_frames"] != len(frames)
            or any(len(frame) != 96 for frame in frames)
            or len(frames) < 128):
        raise AssertionError(f"Unexpected Rust Mel output for {path}")
    if not all(math.isfinite(x) and x >= 0 for frame in frames for x in frame):
        raise AssertionError("Rust reference returned nonfinite or negative Mel")
    expected_patches = 1 + (len(frames) - 128) // 62
    patches = [
        [x for frame in frames[n * 62:n * 62 + 128] for x in frame]
        for n in range(expected_patches)
    ]
    return patches


def error_stats(lhs, rhs, label, max_tolerance=ABS_TOLERANCE, mae_tolerance=None):
    if len(lhs) != len(rhs) or not lhs:
        raise AssertionError(f"{label}: incompatible/nonempty arrays")
    errors = [abs(float(a) - float(b)) for a, b in zip(lhs, rhs)]
    if any(not math.isfinite(err) for err in errors):
        raise AssertionError(f"{label}: NaN/Inf values in result")
    max_error = max(errors)
    mean_error = sum(errors) / len(errors)
    if max_error > max_tolerance or (
        mae_tolerance is not None and mean_error > mae_tolerance
    ):
        raise AssertionError(
            f"{label}: max error {max_error:.8g} (limit {max_tolerance}), "
            f"MAE {mean_error:.8g} (limit {mae_tolerance})"
        )
    return {"count": len(errors), "mean_absolute_error": mean_error,
            "max_absolute_error": max_error,
            "max_tolerance": max_tolerance, "mae_tolerance": mae_tolerance}


def load_onnx(models_dir):
    import onnxruntime as ort
    sessions = {}
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    for name, filename in [("embedding", EMBEDDING), *(
        (key, filename) for key, (filename, _) in HEADS.items()
    )]:
        path = models_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"Missing model weight {path}")
        sessions[name] = ort.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"]
        )
    return sessions


def model_outputs(patches, sessions):
    import numpy as np
    e = sessions["embedding"]
    embeddings = []
    outputs = {head: [] for head in HEADS}
    for patch in patches:
        sample = np.asarray(patch, dtype=np.float32).reshape(1, 128, 96)
        # Discogs-EffNet may expose the original 400-style prediction
        # alongside its 1,280-D embedding. Match the production Rust
        # FeatureEngine behavior: choose by exact tensor size, never output 0.
        candidates = [
            np.asarray(value, dtype=np.float32).reshape(-1)
            for value in e.run(None, {e.get_inputs()[0].name: sample})
        ]
        matched = [value for value in candidates
                   if value.size == 1280 and np.isfinite(value).all()]
        if len(matched) != 1:
            raise AssertionError(
                f"Expected one finite 1280-D EffNet embedding; "
                f"output sizes {[x.size for x in candidates]}"
            )
        embed = matched[0]
        embeddings.extend(embed.tolist())
        for head, (_, count) in HEADS.items():
            session = sessions[head]
            possible = [
                np.asarray(value, dtype=np.float32).reshape(-1)
                for value in session.run(
                    None, {session.get_inputs()[0].name: embed.reshape(1, 1280)}
                )
            ]
            matching = [
                values for values in possible if (
                    values.size == count and np.isfinite(values).all()
                    and np.all(values >= 0.0) and np.all(values <= 1.0)
                )
            ]
            if len(matching) != 1:
                raise AssertionError(
                    f"Invalid {head} head outputs: "
                    f"tensor sizes {[x.size for x in possible]}"
                )
            result = matching[0]
            outputs[head].append(result.tolist())
    return embeddings, outputs


def compare_models(reference, native, sessions):
    a_embeddings, a = model_outputs(reference, sessions)
    b_embeddings, b = model_outputs(native, sessions)
    results = {"embedding": error_stats(
        a_embeddings, b_embeddings, "EffNet 1280-D embedding"
    )}
    for head in HEADS:
        a_flat = [v for patch in a[head] for v in patch]
        b_flat = [v for patch in b[head] for v in patch]
        a_mean = [sum(row[i] for row in a[head]) / len(a[head])
                  for i in range(len(a[head][0]))]
        b_mean = [sum(row[i] for row in b[head]) / len(b[head])
                  for i in range(len(b[head][0]))]
        results[head] = {
            "per_patch": error_stats(a_flat, b_flat, f"{head} per-patch"),
            "mean": error_stats(a_mean, b_mean, f"{head} aggregate"),
        }
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--rust-reference", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=Path("fixtures"))
    parser.add_argument("--models-dir", type=Path,
                        help="Official ONNX weights to enable complete output parity")
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()
    sessions = load_onnx(args.models_dir) if args.models_dir else None
    report = {"schema_version": 1,
              "mode": "mel-and-all-onnx-heads" if sessions else "mel-only",
              "absolute_tolerance": ABS_TOLERANCE, "cases": {}}
    with subprocess.Popen([str(args.worker)], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        if exact(proc.stdout, 4) != b"EFW1":
            raise AssertionError("Not an original native Essentia worker")
        for name in AUDIO:
            source = args.fixtures / name
            if not source.is_file():
                raise FileNotFoundError(source)
            status, result, decode, mel = request(proc, source)
            if status != 0:
                raise AssertionError(f"Original Essentia rejected {source}: {result}")
            count, flattened = result
            native = [flattened[i * 128 * 96:(i + 1) * 128 * 96]
                      for i in range(count)]
            rust = rust_reference(args.rust_reference, source)
            if len(rust) != count:
                raise AssertionError(
                    f"{name}: Rust and Essentia patch counts {len(rust)} vs {count}"
                )
            is_mp3 = source.suffix.lower() == ".mp3"
            stats = error_stats(
                [v for patch in rust for v in patch],
                [v for patch in native for v in patch],
                f"{name} Mel",
                max_tolerance=MP3_MEL_MAX_TOLERANCE if is_mp3 else ABS_TOLERANCE,
                mae_tolerance=MP3_MEL_MAE_TOLERANCE if is_mp3 else None,
            )
            case = {"patches": count, "mel": stats,
                    "decode_seconds": decode / 1e9,
                    "feature_seconds": mel / 1e9}
            if sessions:
                case["onnx"] = compare_models(rust, native, sessions)
            report["cases"][name] = case
            print(f"{name}: patches={count} Mel MAE={stats['mean_absolute_error']:.8g} "
                  f"max={stats['max_absolute_error']:.8g}, "
                  f"model_parity={'yes' if sessions else 'not requested'}")
        proc.stdin.close()
        if proc.wait(timeout=10) != 0:
            raise AssertionError("Original C++ worker failed after multiple codecs")
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"End-to-end native C++/Rust parity PASS ({len(AUDIO)} codecs): "
          f"{args.report_output}")


if __name__ == "__main__":
    main()
