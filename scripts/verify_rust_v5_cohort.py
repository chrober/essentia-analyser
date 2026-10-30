#!/usr/bin/env python3
"""One Rust-v5 100-song scan vs SAVED original Essentia C++ v3 sidecar.

Never rescans C++ or modifies any existing cohort/audio/model/feature database.
Reuse the previously completed original Essentia C++ one-worker comparison
and the old Rust-v4 sidecar. A new dedicated v5 sidecar is created once;
strict original 1e-3 tolerance is unchanged. Save full private diagnostics,
including private track names, inside a NEW output directory only.
"""
import argparse
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

from benchmark_audio_backends import (
    checked_cohort, compare_feature_tables, digest, load_feature_rows,
    run_scan, validate_source_roots, verify_backend_fingerprint_separation,
)
from verify_resampler_fix_on_existing_wav import (
    FIXED_RUST_PREPROCESSING, OLD_RUST_PREPROCESSING,
)

NATIVE_CPP_PREPROCESSING = "experimental-essentia-cpp-dsp-v1-unvalidated"
HEADS = ("genre", "moodtheme", "voice")
EXPECTED_SCORES = 87 + 56 + 2


def fingerprint_and_audio_rows(db, expected_version, cohort, heads=HEADS):
    """Inspect *used* model definitions; never accept stale/mixed version keys."""
    with closing(sqlite3.connect(
        f"file:{db.resolve().as_posix()}?mode=ro", uri=True
    )) as conn:
        if conn.execute("PRAGMA user_version").fetchone()[0] != 3:
            raise AssertionError(f"Expected schema v3 sidecar: {db}")
        records = conn.execute(
            "SELECT t.track_file, t.model_id, t.audio_sha256, "
            "t.model_key, m.preprocessing_version "
            "FROM feature_tracks AS t "
            "LEFT JOIN feature_models AS m ON m.model_key=t.model_key"
        ).fetchall()
    expected = {(key, head) for key in cohort for head in heads}
    observed = {(track, head) for track, head, _, _, _ in records}
    if len(records) != len(expected) or observed != expected:
        raise AssertionError(
            f"Expected exactly {len(expected)} unique track/head pairs: {db}; "
            f"got {len(records)} rows, {len(observed)} distinct pairs"
        )
    audio = {}
    keys = {}
    for track, head, sha, model_key, version in records:
        if version != expected_version:
            raise AssertionError(
                f"Incorrect or stale preprocessing version for {head}: "
                f"{version!r}, expected {expected_version!r}"
            )
        if (not isinstance(sha, str) or len(sha) != 64
                or any(char not in "0123456789abcdefABCDEF" for char in sha)):
            raise AssertionError(f"Invalid source audio SHA for {track}")
        if not model_key:
            raise AssertionError(f"Missing fingerprint for {head}")
        if track in audio and audio[track].lower() != sha.lower():
            raise AssertionError(f"Inconsistent source audio SHA across heads: {track}")
        if head in keys and keys[head] != model_key:
            raise AssertionError(f"Mixed fingerprint for head: {head}")
        audio[track] = sha.lower()
        keys[head] = model_key
    return audio, keys


def compare_versions(cohort, old_db, cpp_db, new_db, threshold):
    if not math.isfinite(threshold) or not 0 < threshold < 0.1:
        raise ValueError("Invalid numerical tolerance")
    cohort = checked_cohort(cohort)
    previous_audio, old_keys = fingerprint_and_audio_rows(
        old_db, OLD_RUST_PREPROCESSING, cohort
    )
    cpp_audio, cpp_keys = fingerprint_and_audio_rows(
        cpp_db, NATIVE_CPP_PREPROCESSING, cohort
    )
    if previous_audio != cpp_audio:
        raise AssertionError("Original v4 and C++ sidecars hash different source audio")
    new_audio, new_keys = fingerprint_and_audio_rows(
        new_db, FIXED_RUST_PREPROCESSING, cohort
    )
    if new_audio != cpp_audio:
        raise AssertionError(
            "New Rust-v5 audio SHA256 differs from saved native C++ input; "
            "cannot attribute score differences solely to resampler correction"
        )
    if any(old_keys[head] == new_keys[head] for head in HEADS):
        raise AssertionError("Rust-v5 model fingerprint aliases historical v4 features")
    if any(new_keys[head] == cpp_keys[head] for head in HEADS):
        raise AssertionError("Rust-v5 model fingerprint aliases native Essentia")

    # Old and new must both preserve *actual* ONNX weights/labels/aggregations.
    if verify_backend_fingerprint_separation(old_db, cpp_db) != sorted(HEADS):
        raise AssertionError("Historical v4/C++ model heads differ")
    if verify_backend_fingerprint_separation(new_db, cpp_db) != sorted(HEADS):
        raise AssertionError("New v5/C++ model heads differ")
    previous = compare_feature_tables(
        load_feature_rows(old_db), load_feature_rows(cpp_db),
        expected_models=HEADS, expected_tracks=cohort,
    )
    current = compare_feature_tables(
        load_feature_rows(new_db), load_feature_rows(cpp_db),
        expected_models=HEADS, expected_tracks=cohort,
    )
    if previous["patch_count_mismatches"]:
        raise AssertionError("Saved previous Rust/C++ patch counts differ")
    max_error = current["maximum_absolute_score_difference"]
    status = ("PASS" if not current["patch_count_mismatches"]
              and max_error <= threshold else "FAIL")
    return {
        "numeric_parity_status": status,
        "scope": "same_100_song_cohort_rust_v5_vs_saved_original_essentia_cpp",
        "note": (
            "PASS checks scores and patch counts at 1 worker, not 2-worker "
            "stability, repeated performance, cross-codec/library coverage "
            "or license/distribution clearance"
        ),
        "cohort_songs": len(cohort),
        "model_heads": list(HEADS),
        "score_components": len(cohort) * EXPECTED_SCORES,
        "maximum_allowed_score_difference": threshold,
        "old_rust_v4": previous,
        "new_rust_v5": current,
        "per_head_improvement": {
            head: {
                "old_max_abs_error":
                    previous["per_head"][head]["maximum_absolute_score_difference"],
                "new_max_abs_error":
                    current["per_head"][head]["maximum_absolute_score_difference"],
                "new_mean_abs_error":
                    current["per_head"][head]["mean_absolute_score_difference"],
            } for head in HEADS
        },
    }


def run(args):
    inputs = (args.cohort_db, args.old_rust_db, args.essentia_db, args.analyzer)
    if any(not item.is_file() for item in inputs):
        raise FileNotFoundError("Missing existing cohort, old v4/C++ sidecar or v5 scanner")
    if not args.source_root.is_dir() or not args.models_dir.is_dir():
        raise FileNotFoundError("Missing readable library source root or ONNX model directory")
    if args.output_dir.exists():
        raise FileExistsError("Use a NEW v5 scan output directory; never reuse existing DBs")
    # A single fresh cohort scan may use fixed parallel Rust workers.
    # Each song is independently analyzed with 1 ONNX thread per worker;
    # comparison is keyed by song/head, never by completion order.
    if args.workers not in (1, 2, 4, 6, 8):
        raise ValueError("Require fixed Rust --workers from 1,2,4,6,8")
    if not math.isfinite(args.score_max_tolerance) or not 0 < args.score_max_tolerance < 0.1:
        raise ValueError("Score tolerance must be finite and strictly between 0 and 0.1")
    validate_source_roots(args.source_root, None)
    cohort = checked_cohort(args.cohort_db)
    if len(cohort) != args.expected_songs:
        raise AssertionError(
            f"Deliberate cohort requires {args.expected_songs} songs, found {len(cohort)}"
        )
    paths = (args.cohort_db, args.old_rust_db, args.essentia_db, args.analyzer)
    original_hashes = {name: digest(path) for name, path in zip(
        ("cohort", "old_rust_v4", "native_cpp", "rust_v5_exe"), paths
    )}
    cpp_audio, _ = fingerprint_and_audio_rows(
        args.essentia_db, NATIVE_CPP_PREPROCESSING, cohort
    )
    old_audio, _ = fingerprint_and_audio_rows(
        args.old_rust_db, OLD_RUST_PREPROCESSING, cohort
    )
    if old_audio != cpp_audio:
        raise AssertionError("Existing v4 and original C++ do not hash same songs")
    verify_backend_fingerprint_separation(args.old_rust_db, args.essentia_db)

    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "manifest.json").write_text(
        json.dumps({
            "scan": "one_rust_v5_scan_and_reuse_original_essentia_sidecar",
            "worker_count": args.workers,
        "onnx_threads_per_worker": 1, "models": list(HEADS),
            "cohort_size": len(cohort), "source_sha256": original_hashes,
            "note": "New v5 sidecar; old original C++ and Rust v4 remain read-only",
        }, indent=2) + "\n", encoding="utf-8",
    )
    scan_args = SimpleNamespace(
        analyzer=args.analyzer.resolve(), cohort_db=args.cohort_db.resolve(),
        models_dir=args.models_dir.resolve(), models="genre,moodtheme,voice",
        source_root=args.source_root, library_root=None,
        output_dir=args.output_dir, essentia_worker=None, timeout_seconds=900,
    )
    scan, _ = run_scan(scan_args, 1, args.workers, "rust", len(cohort))
    fresh_db = args.output_dir / scan["sqlite"]
    # Scan may have been long; fail closed on changed originals.
    for name, path in zip(("cohort", "old_rust_v4", "native_cpp", "rust_v5_exe"), paths):
        if digest(path) != original_hashes[name]:
            raise AssertionError(f"Input file changed during new v5 scan: {name}")
    report = compare_versions(
        args.cohort_db, args.old_rust_db, args.essentia_db,
        fresh_db, args.score_max_tolerance,
    )
    report["rust_v5_scan"] = scan
    report["worker_count"] = args.workers
    report["onnx_threads_per_worker"] = 1
    report["scope"] = (
        "same_100_song_cohort_rust_v5_"
        f"workers_{args.workers}_vs_saved_original_essentia_cpp"
    )
    report["note"] = (
        "PASS checks numeric score/patch parity for a full cohort with "
        f"{args.workers} fixed Rust workers versus original C++ one-worker "
        "reference, not reproducibility across worker counts, repeated "
        "throughput, cross-codec/library coverage or licensing/distribution"
    )
    report["original_input_sha256"] = original_hashes
    report_file = args.output_dir / "parity-report-private.json"
    with report_file.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, ensure_ascii=False, allow_nan=False)
        output.write("\n")
    print(json.dumps({
        "numeric_parity_status": report["numeric_parity_status"],
        "cohort_songs": report["cohort_songs"],
        "worker_count": args.workers,
        "onnx_threads_per_worker": 1,
        "score_components": report["score_components"],
        "patch_mismatches": report["new_rust_v5"]["patch_count_mismatches"],
        "maximum_absolute_difference":
            report["new_rust_v5"]["maximum_absolute_score_difference"],
        "per_head_improvement": report["per_head_improvement"],
        "rust_v5_elapsed_seconds": scan["seconds"],
        "private_report_file": str(report_file),
    }, indent=2, ensure_ascii=False, allow_nan=False))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-db", type=Path, required=True)
    parser.add_argument("--old-rust-db", type=Path, required=True)
    parser.add_argument("--essentia-db", type=Path, required=True)
    parser.add_argument("--analyzer", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4,
                        help="Fixed parallel Rust workers: 1,2,4,6,8 (default 4); 1 ONNX thread each")
    parser.add_argument("--expected-songs", type=int, default=100)
    parser.add_argument("--score-max-tolerance", type=float, default=0.001)
    args = parser.parse_args()
    if not 2 <= args.expected_songs <= 500:
        parser.error("Expected deliberate bounded 2..500-song cohort")
    result = run(args)
    if result["numeric_parity_status"] != "PASS":
        sys.exit(2)


if __name__ == "__main__":
    main()
