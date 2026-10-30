"""End-to-end per-track Rust/ONNX versus official Essentia/TensorFlow parity.

Unlike head-only checks this compares full independent paths:
FFmpeg -> Rust log-Mel -> ONNX EffNet -> ONNX head -> mean
versus Essentia MonoLoader -> TensorflowPredictEffnetDiscogs -> TensorflowPredict2D -> mean.
Reports exact patch counts and 56 class-aligned probabilities. No databases touched.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--audio", type=Path, required=True)
    p.add_argument("--model", choices=["moodtheme", "genre", "voice"], default="moodtheme")
    p.add_argument("--onnx-json", type=Path, required=True)
    p.add_argument("--models-dir", type=Path, required=True)
    p.add_argument("--report-output", type=Path, required=True)
    p.add_argument("--atol", type=float, default=1e-3)
    p.add_argument("--rtol", type=float, default=1e-3)
    args = p.parse_args()

    report = json.loads(args.onnx_json.read_text(encoding="utf-8-sig"))
    prefix = "voice_instrumental" if args.model == "voice" else "mtg_jamendo_" + args.model
    # moodtheme retains the original version-1 JSON report; generic runs
    # expose independent results under classifications.<model-id>.
    result_node = report if "scores" in report else report["classifications"][args.model]
    scores = result_node["scores"]
    labels = json.loads((args.models_dir / (prefix + "-discogs-effnet-1.json")).read_text())["classes"]
    if set(labels) != set(scores) or len(labels) == 0:
        raise ValueError("Class name/label mismatch: do NOT compare by unknown order")

    rust_scores = np.asarray([scores[label] for label in labels], dtype=np.float64)
    audio = MonoLoader(filename=str(args.audio), sampleRate=16000, resampleQuality=4)()
    embeddings = TensorflowPredictEffnetDiscogs(
        graphFilename=str(args.models_dir / "discogs-effnet-bs64-1.pb"),
        output="PartitionedCall:1",
        batchSize=64,
        patchSize=128,
        patchHopSize=62,
        lastBatchMode="same",
        lastPatchMode="discard",
    )(audio)
    embeddings = np.asarray(embeddings, dtype=np.float32)
    if embeddings.ndim != 2 or embeddings.shape[1] != 1280:
        raise ValueError(f"Unexpected Essentia embedding shape: {embeddings.shape}")
    predictions = TensorflowPredict2D(
        graphFilename=str(args.models_dir / (prefix + "-discogs-effnet-1.pb")),
        **({"output": "model/Softmax"} if args.model == "voice" else {}),
        batchSize=-1,
        patchSize=1,
        patchHopSize=1,
    )(embeddings)
    predictions = np.asarray(predictions, dtype=np.float64)
    if predictions.shape != (len(embeddings), len(labels)):
        raise ValueError(f"Unexpected Essentia classifier shape {predictions.shape}")
    reference = np.mean(predictions, axis=0)
    delta = np.abs(rust_scores - reference)
    worst_index = int(np.argmax(delta))
    patch_count_match = report["patches_analyzed"] == len(embeddings)
    scores_match = bool(np.allclose(rust_scores, reference, atol=args.atol, rtol=args.rtol))
    result = {
        "passed": bool(patch_count_match and scores_match),
        "audio_file": args.audio.name,
        "onnx_patches": report["patches_analyzed"],
        "essentia_patches": int(len(embeddings)),
        "patch_counts_match": patch_count_match,
        "class_count": len(labels),
        "mean_absolute_error": float(delta.mean()),
        "root_mean_squared_error": float(np.sqrt(np.mean(delta * delta))),
        "maximum_absolute_error": float(delta.max()),
        "worst_class": labels[worst_index],
        "onnx_value_at_worst": float(rust_scores[worst_index]),
        "essentia_value_at_worst": float(reference[worst_index]),
        "onnx_top_five": [label for label in sorted(labels, key=lambda x: -scores[x])[:5]],
        "essentia_top_five": [labels[i] for i in np.argsort(-reference)[:5]],
        "atol": args.atol,
        "rtol": args.rtol,
        "essentia_version": __import__("essentia").__version__,
        "preprocessing_version": report["preprocessing_version"],
        "audio_sha256": report["audio_sha256"],
        "model_sha256": result_node["models_sha256"],
        "validated_against_essentia_in_db": result_node["validated_against_essentia"],
        "model_id": args.model,
    }
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit("End-to-end Essentia parity FAILED; no validated scores should be imported")


if __name__ == "__main__":
    main()
