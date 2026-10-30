"""Numerical Essentia TensorFlow vs Rust ONNX embedding parity gate.

Run on the same synthetic WAV; do not persist either model's output in mood.db.
Official reference: TensorflowPredictEffnetDiscogs with fixed-bs64 .pb, which
pads its last batch and returns only real patches (lastBatchMode="same").
"""
import argparse
import json
from pathlib import Path

import numpy as np
from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--rust-json", type=Path, required=True)
    parser.add_argument("--tf-model", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, default=Path("embedding-parity-report.json"))
    parser.add_argument("--absolute-tolerance", type=float, default=1e-3)
    parser.add_argument("--relative-tolerance", type=float, default=1e-3)
    parser.add_argument("--require-full", action="store_true", help="Require exactly equal full-track patch counts")
    args = parser.parse_args()

    rust = json.loads(args.rust_json.read_text(encoding="utf-8"))
    assert rust["embedding_dimensions"] == 1280
    assert rust["embedding_model"] == "discogs-effnet-bsdynamic-1.onnx"
    assert rust["validation_status"] == "experimental-unvalidated"
    onnx = np.asarray(rust["embeddings"], dtype=np.float64)
    assert onnx.ndim == 2 and onnx.shape[1] == 1280 and onnx.shape[0] > 0
    assert onnx.shape[0] == rust["patches_analyzed"]
    assert np.isfinite(onnx).all(), "ONNX embedding contains NaN or infinity"

    audio = MonoLoader(filename=str(args.audio), sampleRate=16000, resampleQuality=4)()
    tf = TensorflowPredictEffnetDiscogs(
        graphFilename=str(args.tf_model),
        output="PartitionedCall:1",
        batchSize=64,
        patchSize=128,
        patchHopSize=62,
        lastBatchMode="same",
        lastPatchMode="discard",
    )
    all_reference = np.asarray(tf(audio), dtype=np.float64)
    # The diagnostic ONNX CLI intentionally limits processing to the first N
    # patches, whereas Essentia computes the entire short test signal.
    # Compare aligned prefixes, but NEVER silently pad or invent missing output.
    if (
        all_reference.ndim != 2
        or all_reference.shape[1] != 1280
        or all_reference.shape[0] < onnx.shape[0]
        or (args.require_full and all_reference.shape[0] != onnx.shape[0])
    ):
        report = {
            "passed": False,
            "reason": "TensorFlow patch count or embedding dimensions differ",
            "onnx_shape": list(onnx.shape),
            "tensorflow_shape": list(all_reference.shape),
        }
    else:
        reference = all_reference[:onnx.shape[0]]
        assert np.isfinite(reference).all(), "TensorFlow embedding contains NaN or infinity"
        delta = np.abs(onnx - reference)
        scale = np.linalg.norm(onnx, axis=1) * np.linalg.norm(reference, axis=1)
        cosine = np.divide(
            np.einsum("ij,ij->i", onnx, reference),
            scale,
            out=np.zeros_like(scale),
            where=scale > 0,
        )
        where = np.unravel_index(int(np.argmax(delta)), delta.shape)
        report = {
            "passed": bool(np.allclose(
                onnx, reference,
                rtol=args.relative_tolerance,
                atol=args.absolute_tolerance,
            )),
            "patches_compared": int(onnx.shape[0]),
            "full_track_count_required": args.require_full,
            "tensorflow_total_patches": int(all_reference.shape[0]),
            "embedding_dimensions": 1280,
            "values_compared": int(onnx.size),
            "mean_absolute_error": float(delta.mean()),
            "root_mean_square_error": float(np.sqrt((delta ** 2).mean())),
            "maximum_absolute_error": float(delta.max()),
            "worst_patch": int(where[0]),
            "worst_dimension": int(where[1]),
            "onnx_value_at_worst": float(onnx[where]),
            "tensorflow_value_at_worst": float(reference[where]),
            "min_cosine_similarity": float(np.min(cosine)),
            "per_patch_cosine_similarity": cosine.tolist(),
            "atol": args.absolute_tolerance,
            "rtol": args.relative_tolerance,
            "onnx_model": rust["embedding_model"],
            "tensorflow_model": args.tf_model.name,
            "essentia_version": __import__("essentia").__version__,
        }

    args.report_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(
            "Embedding parity FAILED. Keep validated_against_essentia=false "
            "and do not start a library-wide Mood scan."
        )


if __name__ == "__main__":
    main()
