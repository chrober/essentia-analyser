"""Compare any registered ONNX and TensorFlow heads on identical embeddings.

This isolates the classification head from Mel/FFmpeg/Discogs-EffNet
differences. Its input is a diagnostic, synthetic-audio ONNX embedding dump.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from essentia.standard import TensorflowPredict2D


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--embeddings", type=Path, required=True)
    p.add_argument("--onnx-json", type=Path, required=True)
    p.add_argument("--tf-model", type=Path, required=True)
    p.add_argument("--tf-output", help="Explicit TensorFlow output node, e.g. model/Softmax")
    p.add_argument("--report-output", type=Path, default=Path("classification-parity-report.json"))
    p.add_argument("--absolute-tolerance", type=float, default=1e-3)
    p.add_argument("--relative-tolerance", type=float, default=1e-3)
    args = p.parse_args()

    inputs = json.loads(args.embeddings.read_text(encoding="utf-8"))
    onnx_report = json.loads(args.onnx_json.read_text(encoding="utf-8"))
    embeddings = np.asarray(inputs["embeddings"], dtype=np.float32)
    onnx = np.asarray(onnx_report["scores_per_patch"], dtype=np.float64)
    onnx_means = np.asarray(onnx_report["mean_scores"], dtype=np.float64)
    assert embeddings.ndim == 2 and embeddings.shape[1] == 1280
    classes = onnx_report["classes"]
    num_classes = len(classes)
    assert num_classes > 0
    assert onnx.shape == (embeddings.shape[0], num_classes)
    assert onnx_means.shape == (num_classes,)
    assert all(isinstance(label, str) for label in onnx_report["classes"])
    assert onnx_report["validation_status"] == "experimental-unvalidated"

    classifier = TensorflowPredict2D(
        graphFilename=str(args.tf_model),
        **({"output": args.tf_output} if args.tf_output else {}),
        batchSize=-1,
        patchSize=1,
        patchHopSize=1,
    )
    reference = np.asarray(classifier(embeddings), dtype=np.float64)
    if reference.shape != onnx.shape:
        report = {
            "passed": False,
            "reason": "TensorFlow returned unexpected classification shape",
            "onnx_shape": list(onnx.shape),
            "tensorflow_shape": list(reference.shape),
        }
    else:
        assert np.isfinite(onnx).all() and np.isfinite(reference).all()
        assert ((onnx >= 0) & (onnx <= 1)).all()
        assert ((reference >= 0) & (reference <= 1)).all()
        tf_means = reference.mean(axis=0)
        delta = np.abs(onnx - reference)
        means_delta = np.abs(onnx_means - tf_means)
        worst = np.unravel_index(int(np.argmax(delta)), delta.shape)
        pass_patches = bool(np.allclose(
            onnx, reference, rtol=args.relative_tolerance,
            atol=args.absolute_tolerance,
        ))
        pass_means = bool(np.allclose(
            onnx_means, tf_means, rtol=args.relative_tolerance,
            atol=args.absolute_tolerance,
        ))
        report = {
            "passed": pass_patches and pass_means,
            "per_patch_passed": pass_patches,
            "aggregate_passed": pass_means,
            "patches_compared": int(onnx.shape[0]),
            "classes_compared": num_classes,
            "values_compared": int(onnx.size),
            "mean_absolute_error": float(delta.mean()),
            "maximum_absolute_error": float(delta.max()),
            "aggregate_mean_absolute_error": float(means_delta.mean()),
            "aggregate_maximum_absolute_error": float(means_delta.max()),
            "worst_patch": int(worst[0]),
            "worst_class": onnx_report["classes"][int(worst[1])],
            "onnx_value_at_worst": float(onnx[worst]),
            "tensorflow_value_at_worst": float(reference[worst]),
            "atol": args.absolute_tolerance,
            "rtol": args.relative_tolerance,
            "tensorflow_model": args.tf_model.name,
            "onnx_model": onnx_report["classification_model"],
            "essentia_version": __import__("essentia").__version__,
        }

    args.report_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit("Classifier head parity failed; keep all scores experimental")


if __name__ == "__main__":
    main()
