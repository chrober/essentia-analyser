#!/usr/bin/env python3
"""Read-only numerical drift diagnostics for existing paired real-music sidecars.

A completed diagnosis can contain FAILing numeric parity: successful execution
is not compatibility certification. This utility never analyzes audio or
changes input SQLite files; its detailed JSON may contain private file paths.
"""
import argparse
from collections import defaultdict
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3

from benchmark_audio_backends import (
    checked_cohort, compare_feature_tables, digest, load_feature_rows,
    verify_backend_fingerprint_separation,
)


def percentile(values, percent):
    """Deterministic nearest-rank percentile (no external dependencies)."""
    if not values:
        return None
    data = sorted(values)
    index = max(0, math.ceil(len(data) * percent / 100) - 1)
    return data[index]


def summarize(values, threshold):
    if not values:
        return {"scores": 0}
    return {
        "scores": len(values),
        "mean_absolute_error": sum(values) / len(values),
        "maximum_absolute_error": max(values),
        "p50_absolute_error": percentile(values, 50),
        "p90_absolute_error": percentile(values, 90),
        "p95_absolute_error": percentile(values, 95),
        "p99_absolute_error": percentile(values, 99),
        "scores_exceeding_tolerance": sum(x > threshold for x in values),
    }


def diagnose(cohort, rust_db, cpp_db, models, tolerance):
    if not math.isfinite(tolerance) or not 0 < tolerance < 0.1:
        raise ValueError("Tolerance must be a finite value between 0 and 0.1")
    files = (cohort, rust_db, cpp_db)
    if len({p.resolve() for p in files}) != 3:
        raise ValueError("Three separate SQLite input databases are required")
    if any(not p.is_file() for p in files):
        raise FileNotFoundError("One of the three input SQLite databases is missing")
    original_hashes = [digest(p) for p in files]
    tracks = checked_cohort(cohort)
    rust = load_feature_rows(rust_db)
    cpp = load_feature_rows(cpp_db)
    aggregate = compare_feature_tables(
        rust, cpp, expected_models=models, expected_tracks=tracks
    )
    checked_heads = verify_backend_fingerprint_separation(rust_db, cpp_db)
    if checked_heads != sorted(models):
        raise AssertionError(f"Unexpected model heads: {checked_heads}")
    errors_by_head = defaultdict(list)
    errors_by_extension = defaultdict(list)
    track_head_max = defaultdict(list)
    patch_discrepancies = []
    rows = []
    for (track, head), (rust_patches, rust_scores) in sorted(rust.items()):
        cpp_patches, cpp_scores = cpp[track, head]
        errors = [abs(a - b) for a, b in zip(rust_scores, cpp_scores)]
        maximum = max(errors)
        file_format = Path(track).suffix.casefold() or "(none)"
        errors_by_head[head].extend(errors)
        errors_by_extension[file_format].extend(errors)
        track_head_max[head].append(maximum)
        if rust_patches != cpp_patches:
            patch_discrepancies.append({
                "track_file": track, "head": head,
                "rust_patches": rust_patches, "essentia_patches": cpp_patches,
            })
        index = errors.index(maximum)
        rows.append({
            "track_file": track, "extension": file_format, "head": head,
            "rust_patches": rust_patches, "essentia_patches": cpp_patches,
            "maximum_absolute_error": maximum,
            "mean_absolute_error": sum(errors) / len(errors),
            "worst_class_index": index,
            "rust_score": rust_scores[index],
            "essentia_score": cpp_scores[index],
        })
    head_summary = {}
    for head in sorted(errors_by_head):
        summary = summarize(errors_by_head[head], tolerance)
        summary["tracks"] = len(track_head_max[head])
        summary["tracks_exceeding_tolerance"] = sum(
            value > tolerance for value in track_head_max[head]
        )
        head_summary[head] = summary
    format_summary = {}
    for ext in sorted(errors_by_extension):
        summary = summarize(errors_by_extension[ext], tolerance)
        relevant = [r for r in rows if r["extension"] == ext]
        summary["tracks"] = len(set(r["track_file"] for r in relevant))
        summary["tracks_exceeding_tolerance"] = len(set(
            r["track_file"] for r in relevant
            if r["maximum_absolute_error"] > tolerance
        ))
        format_summary[ext] = summary
    total_bad_tracks = len({
        r["track_file"] for r in rows
        if r["maximum_absolute_error"] > tolerance
    })
    status = "PASS" if not patch_discrepancies and not total_bad_tracks else "FAIL"
    if [digest(p) for p in files] != original_hashes:
        raise AssertionError("Input SQLite changed while checking")
    return {
        "report_schema": "backend-drift-diagnostics-v1",
        "numeric_parity_status": status,
        "diagnostic_completed": True,
        "meaning": "A completed diagnostic is NOT a pass when numeric_parity_status is FAIL",
        "tolerance": tolerance,
        "cohort_tracks": len(tracks),
        "model_heads": checked_heads,
        "tracks_exceeding_tolerance_any_head": total_bad_tracks,
        "patch_mismatch_count": len(patch_discrepancies),
        "patch_mismatch_examples": patch_discrepancies[:20],
        "per_head": head_summary,
        "per_extension": format_summary,
        "worst_track_head_pairs": sorted(
            rows, key=lambda r: (-r["maximum_absolute_error"], r["track_file"], r["head"])
        )[:25],
        "input_sha256": {
            "cohort": original_hashes[0],
            "rust": original_hashes[1],
            "essentia": original_hashes[2],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-db", required=True, type=Path)
    parser.add_argument("--rust-db", required=True, type=Path)
    parser.add_argument("--essentia-db", required=True, type=Path)
    parser.add_argument("--models", default="genre,moodtheme,voice")
    parser.add_argument("--score-max-tolerance", type=float, default=0.001)
    parser.add_argument("--output", type=Path, required=True,
                        help="NEW private JSON path; refuse to overwrite")
    args = parser.parse_args()
    models = tuple(x.strip() for x in args.models.split(","))
    if not models or any(not x for x in models) or len(set(models)) != len(models):
        parser.error("Expected unique nonempty model head names")
    result = diagnose(
        args.cohort_db, args.rust_db, args.essentia_db,
        models, args.score_max_tolerance
    )
    # Do not replace a previous diagnostic: preserve all original evidence.
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    # Summary output deliberately omits paths; full details stay local.
    summary = {
        "numeric_parity_status": result["numeric_parity_status"],
        "cohort_tracks": result["cohort_tracks"],
        "tracks_exceeding_tolerance_any_head":
            result["tracks_exceeding_tolerance_any_head"],
        "patch_mismatch_count": result["patch_mismatch_count"],
        "per_head": result["per_head"],
        "per_extension": result["per_extension"],
        "full_private_report": str(args.output),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
