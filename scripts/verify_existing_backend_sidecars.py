#!/usr/bin/env python3
"""Read-only Rust vs original Essentia C++ numerical parity on existing v3 DBs.

Never rescans music. Audit same exact song/head cohort, backend-isolated
model fingerprints, *actual* shared ONNX model SHA256/class order/aggregation,
patch count parity, and bounded per-class numeric differences. Intended
for the first paired 100-song scan from PR #17.
"""
import argparse
import json
from pathlib import Path

from benchmark_audio_backends import (
    checked_cohort,
    compare_feature_tables,
    digest,
    load_feature_rows,
    verify_backend_fingerprint_separation,
)


def verify(cohort_db: Path, rust_db: Path, essentia_db: Path,
           model_names: tuple[str, ...], tolerance: float) -> dict:
    if not (0 < tolerance < 0.1):
        raise ValueError("Tolerance must be strictly between 0 and 0.1")
    expected = checked_cohort(cohort_db)
    inputs = (cohort_db, rust_db, essentia_db)
    if any(not file.is_file() for file in inputs):
        raise FileNotFoundError("All three SQLite databases must already exist")
    if len({file.resolve() for file in inputs}) != 3:
        raise ValueError("Cohort, Rust and C++ databases must be distinct")
    before = {str(file): digest(file) for file in inputs}
    baseline = load_feature_rows(rust_db)
    native = load_feature_rows(essentia_db)
    numeric = compare_feature_tables(
        baseline, native, expected_models=model_names, expected_tracks=expected
    )
    heads = verify_backend_fingerprint_separation(rust_db, essentia_db)
    if heads != sorted(model_names):
        raise AssertionError(f"Unexpected analyzed heads: {heads}")
    if numeric["patch_count_mismatches"]:
        raise AssertionError(
            "Nonidentical audio patch counts: "
            + json.dumps(numeric["patch_count_mismatch_examples"])
        )
    if numeric["maximum_absolute_score_difference"] > tolerance:
        worst = numeric["worst_score_difference"]
        raise AssertionError(
            f"Model-score parity failed (limit {tolerance}): "
            + json.dumps(worst, ensure_ascii=False)
        )
    after = {str(file): digest(file) for file in inputs}
    if before != after:
        raise AssertionError("One of the input SQLite files changed during comparison")
    return {
        "status": "pass",
        "comparison": "rust_vs_original_essentia_cpp",
        "song_count": len(expected),
        "checked_model_heads": heads,
        "maximum_allowed_score_difference": tolerance,
        "numerical_parity": numeric,
        "input_sha256": before,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-db", type=Path, required=True)
    parser.add_argument("--rust-db", type=Path, required=True)
    parser.add_argument("--essentia-db", type=Path, required=True)
    parser.add_argument("--models", default="genre,moodtheme,voice")
    parser.add_argument("--score-max-tolerance", type=float, default=1e-3)
    args = parser.parse_args()
    models = tuple(x.strip() for x in args.models.split(","))
    if not models or any(not x for x in models) or len(set(models)) != len(models):
        parser.error("--models must contain unique nonempty IDs")
    report = verify(args.cohort_db, args.rust_db, args.essentia_db,
                    models, args.score_max_tolerance)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
