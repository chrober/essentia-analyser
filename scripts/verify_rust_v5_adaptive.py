#!/usr/bin/env python3
"""One controlled adaptive Rust-v5 100-song scan using saved C++ and fixed-4-worker references.

Use only the *existing* bounded 100-song Bliss cohort; no C++ or fixed-4-worker
rescan. All existing SQLite files, WAVs, music and models are read-only.
Creates a NEW schema-v3 SQLite sidecar for 6->4..8 adaptive Rust workers.
Full JSON reports and log files remain local/private. A completed run can FAIL
numerical parity or worker-invariance without discarding the fresh evidence.
"""
import argparse
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from benchmark_audio_backends import (
    checked_cohort, compare_feature_tables, digest, load_feature_rows,
    validate_report, verify_backend_fingerprint_separation,
)
from verify_rust_v5_cohort import (
    FIXED_RUST_PREPROCESSING, HEADS, compare_versions,
    fingerprint_and_audio_rows,
)

def positive_float(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AssertionError(f"Missing numeric {label}")
    if not math.isfinite(value) or value <= 0:
        raise AssertionError(f"Invalid {label}: {value}")
    return float(value)


def read_baseline(report_file, baseline_db, expected_count):
    if not report_file.is_file() or report_file.parent.resolve() != baseline_db.parent.resolve():
        raise ValueError("Baseline report must be next to existing four-worker SQLite sidecar")
    report = json.loads(report_file.read_text(encoding="utf-8"))
    if (report.get("numeric_parity_status") != "PASS"
            or report.get("worker_count") != 4
            or report.get("cohort_songs") != expected_count
            or report.get("score_components") != expected_count * 145):
        raise AssertionError("Wrong or unproven fixed four-worker baseline report")
    scan = report.get("rust_v5_scan") or {}
    if scan.get("sqlite") != baseline_db.name or scan.get("workers") != 4:
        raise AssertionError("Baseline report points to a different SQLite sidecar")
    seconds = positive_float(report.get("rust_v5_elapsed_seconds", scan.get("seconds")),
                             "four-worker baseline elapsed seconds")
    return seconds


def audit_controller(report, initial, minimum, maximum, expected_songs):
    """Fail closed if CLI quietly ignores --adaptive-workers or emits malformed data."""
    validate_report(report, expected_songs)
    d = report.get("diagnostics")
    if not isinstance(d, dict):
        raise AssertionError("Scan JSON lacks resource/adaptive diagnostics")
    if report.get("workers") != initial or d.get("initial_workers") != initial:
        raise AssertionError("Scanner did not start with requested workers")
    for name in ("initial_workers", "final_workers", "peak_workers",
                 "peak_in_flight", "peak_active_analyses", "system_load_samples"):
        value = d.get(name)
        if type(value) is not int or value < 0:
            raise AssertionError(f"Invalid adaptive diagnostic {name}: {value}")
    if (not minimum <= d["final_workers"] <= maximum
            or not initial <= d["peak_workers"] <= maximum
            or not 1 <= d["peak_active_analyses"] <= maximum
            or not 1 <= d["peak_in_flight"] <= maximum
            or d["system_load_samples"] <= 0):
        raise AssertionError("Adaptive concurrency/resource counters out of bounds")
    decisions = d.get("controller_decisions")
    changes = d.get("adjustments")
    if not isinstance(decisions, dict) or not isinstance(changes, list):
        raise AssertionError("Missing actual adaptive controller decisions/adjustments")
    for key in ("high_load_samples", "low_load_samples", "neutral_load_samples",
                "increases", "decreases"):
        value = decisions.get(key)
        if type(value) is not int or value < 0:
            raise AssertionError(f"Missing/invalid controller counter {key}")
    if decisions["increases"] + decisions["decreases"] != len(changes):
        raise AssertionError("Controller adjustment counters disagree with events")
    active = initial
    for record in changes:
        if not isinstance(record, dict) or record.get("from_workers") != active:
            raise AssertionError("Adaptive adjustment history is discontinuous")
        new = record.get("to_workers")
        if type(new) is not int or abs(new - active) != 1 or not minimum <= new <= maximum:
            raise AssertionError("Adaptive adjustment violates min/max or one-worker policy")
        completed = record.get("after_completed_songs")
        if type(completed) is not int or not 24 <= completed <= expected_songs:
            raise AssertionError("Invalid adaptive adjustment song threshold")
        active = new
    if active != d["final_workers"]:
        raise AssertionError("Final worker count disagrees with adjustment history")
    return {
        "initial_workers": initial, "minimum_workers": minimum,
        "maximum_workers": maximum, "final_workers": d["final_workers"],
        "peak_worker_limit": d["peak_workers"],
        "peak_active_analyses": d["peak_active_analyses"],
        "peak_in_flight": d["peak_in_flight"],
        "system_load_samples": d["system_load_samples"],
        "controller_decisions": decisions, "adjustments": changes,
        "system_cpu_average_percent": d.get("system_cpu_average_percent"),
        "system_cpu_max_percent": d.get("system_cpu_max_percent"),
        "system_ram_max_percent": d.get("system_ram_max_percent"),
        "process_working_set_max_mib": d.get("process_working_set_max_mib"),
        "process_private_bytes_max_mib": d.get("process_private_bytes_max_mib"),
        "process_tree_working_set_max_mib": d.get("process_tree_working_set_max_mib"),
        "system_available_ram_min_mib": d.get("system_available_ram_min_mib"),
        "process_page_fault_delta": d.get("process_page_fault_delta"),
    }


def compare_adaptive(cohort_db, old_rust_db, cpp_db, fixed_db, adaptive_db, tolerance):
    cohort = checked_cohort(cohort_db)
    fixed = compare_versions(cohort_db, old_rust_db, cpp_db, fixed_db, tolerance)
    current = compare_versions(cohort_db, old_rust_db, cpp_db, adaptive_db, tolerance)
    fixed_audio, fixed_keys = fingerprint_and_audio_rows(
        fixed_db, FIXED_RUST_PREPROCESSING, cohort
    )
    current_audio, current_keys = fingerprint_and_audio_rows(
        adaptive_db, FIXED_RUST_PREPROCESSING, cohort
    )
    if fixed_audio != current_audio:
        raise AssertionError("Adaptive and fixed Rust v5 analyzed different audio SHA256")
    if fixed_keys != current_keys:
        raise AssertionError("Adaptive and fixed Rust v5 have different DSP/model fingerprints")
    if verify_backend_fingerprint_separation(adaptive_db, cpp_db) != sorted(HEADS):
        raise AssertionError("Adaptive/C++ model heads differ")
    invariance = compare_feature_tables(
        load_feature_rows(adaptive_db), load_feature_rows(fixed_db),
        expected_models=HEADS, expected_tracks=cohort,
    )
    invariant = (not invariance["patch_count_mismatches"]
                 and invariance["maximum_absolute_score_difference"] <= tolerance)
    status = ("PASS" if fixed["numeric_parity_status"] == "PASS"
              and current["numeric_parity_status"] == "PASS" and invariant
              else "FAIL")
    return {
        "acceptance_status": status,
        "parity_vs_saved_original_cpp": current,
        "fixed_four_worker_reference_status": fixed["numeric_parity_status"],
        "worker_count_invariance_vs_fixed_four": {
            "status": "PASS" if invariant else "FAIL",
            "maximum_absolute_difference": invariance["maximum_absolute_score_difference"],
            "exact_bitwise_equal_scores": invariance["maximum_absolute_score_difference"] == 0,
            "patch_mismatches": invariance["patch_count_mismatches"],
            "per_head": invariance["per_head"],
        },
    }


def invoke_once(args, expected_songs):
    """Call real production Rust CLI exactly once and keep raw reports even on failure."""
    output = args.output_dir
    new_db = output / "rust-v5-adaptive-workers.db"
    raw_json = output / "rust-v5-adaptive-scan.json"
    stderr_file = output / "rust-v5-adaptive-stderr.txt"
    command = [
        str(args.analyzer.resolve()), "scan-features",
        "--bliss-db", str(args.cohort_db.resolve()),
        "--db", str(new_db),
        "--models-dir", str(args.models_dir.resolve()),
        "--models", "genre,moodtheme,voice",
        "--source-root", str(args.source_root),
        "--workers", str(args.workers),
        "--adaptive-workers",
        "--min-workers", str(args.min_workers),
        "--max-workers", str(args.max_workers),
        "--threads", "1", "--max-errors", "1",
        "--max-new", str(expected_songs),
        "--audio-backend", "rust", "--json",
    ]
    started = time.perf_counter()
    with raw_json.open("x", encoding="utf-8") as stdout, stderr_file.open(
        "x", encoding="utf-8"
    ) as stderr:
        code = subprocess.run(command, stdout=stdout, stderr=stderr,
                              check=False).returncode
    seconds = time.perf_counter() - started
    if code != 0:
        raise RuntimeError(
            f"Adaptive production scanner failed (exit {code}); preserve "
            f"existing evidence in {output} and inspect {stderr_file}"
        )
    report = json.loads(raw_json.read_text(encoding="utf-8"))
    telemetry = audit_controller(
        report, args.workers, args.min_workers, args.max_workers, expected_songs
    )
    return new_db, seconds, telemetry


def run(args):
    if not 2 <= args.expected_songs <= 500:
        raise ValueError("Only explicit 2..500 song cohort allowed")
    if (not 1 <= args.min_workers <= args.workers <= args.max_workers <= 16
            or args.workers < 2):
        raise ValueError("Expected 2+ initial workers with 1 <= min <= initial <= max <= 16")
    if not math.isfinite(args.tolerance) or not 0 < args.tolerance < 0.1:
        raise ValueError("Invalid strict numeric score tolerance")
    if args.output_dir.exists():
        raise FileExistsError("Choose a new output directory, never overwrite old evidence")
    inputs = {
        "cohort": args.cohort_db, "rust_v4": args.old_rust_db,
        "original_cpp": args.essentia_db, "fixed_v5": args.fixed_db,
        "fixed_report": args.fixed_report, "rust_v5_scanner": args.analyzer,
    }
    for name, source in inputs.items():
        if not source.is_file():
            raise FileNotFoundError(f"Missing required {name}: {source}")
    if not args.models_dir.is_dir() or not args.source_root.is_dir():
        raise FileNotFoundError("Models or source NAS music directory unavailable")
    cohort = checked_cohort(args.cohort_db)
    if len(cohort) != args.expected_songs:
        raise AssertionError("Wrong number of eligible songs in bounded cohort")
    baseline_seconds = read_baseline(
        args.fixed_report, args.fixed_db, len(cohort)
    )
    reference = compare_versions(
        args.cohort_db, args.old_rust_db, args.essentia_db,
        args.fixed_db, args.tolerance
    )
    if reference["numeric_parity_status"] != "PASS":
        raise AssertionError("Existing four-worker Rust-v5/native C++ parity must pass")
    saved_hashes = {key: digest(path) for key, path in inputs.items()}
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "manifest.json").write_text(
        json.dumps({
            "scan": "one_adaptive_rust_v5_scan_vs_saved_cpp_and_fixed_v5",
            "cohort_songs": len(cohort), "worker_policy": {
                "initial": args.workers, "min": args.min_workers,
                "max": args.max_workers, "onnx_threads_per_worker": 1,
                "adaptive_workers": True,
            },
            "baseline_fixed_workers": 4, "baseline_seconds": baseline_seconds,
            "saved_input_sha256": saved_hashes,
            "note": "Music and existing v4/v5/C++ SQLite are read-only; no new C++ scan",
        }, indent=2) + "\n", encoding="utf-8",
    )
    new_db, duration, telemetry = invoke_once(args, len(cohort))
    if not new_db.is_file():
        raise FileNotFoundError("Scanner succeeded without producing new adaptive feature sidecar")
    for name, path in inputs.items():
        if digest(path) != saved_hashes[name]:
            raise AssertionError(f"Read-only input changed during adaptive scan: {name}")
    comparisons = compare_adaptive(
        args.cohort_db, args.old_rust_db, args.essentia_db,
        args.fixed_db, new_db, args.tolerance,
    )
    speedup = baseline_seconds / positive_float(duration, "adaptive runtime seconds")
    complete = {
        **comparisons,
        "scope": "same_100_song_cohort_6_to_4_8_adaptive_rust_v5_vs_saved_cpp",
        "cohort_songs": len(cohort), "score_components": len(cohort) * 145,
        "maximum_allowed_score_difference": args.tolerance,
        "adaptive_controller": telemetry,
        "performance": {
            "adaptive_wall_seconds": duration, "four_fixed_workers_wall_seconds": baseline_seconds,
            "adaptive_songs_per_minute": len(cohort) * 60.0 / duration,
            "fixed_four_songs_per_minute": len(cohort) * 60.0 / baseline_seconds,
            "adaptive_vs_fixed_four_speedup": speedup,
            "caveat": (
                "Two separate runs under potentially different NAS/cache/CPU load. "
                "This is exploratory, not a controlled replicated speedup claim."
            ),
        },
        "inputs_sha256": saved_hashes,
    }
    result_file = args.output_dir / "adaptive-parity-and-performance-private.json"
    with result_file.open("x", encoding="utf-8") as target:
        json.dump(complete, target, indent=2, ensure_ascii=False, allow_nan=False)
        target.write("\n")
    brief = {
        "acceptance_status": complete["acceptance_status"],
        "cohort_songs": complete["cohort_songs"],
        "score_components": complete["score_components"],
        "max_score_diff_vs_original_cpp":
            complete["parity_vs_saved_original_cpp"]["new_rust_v5"]["maximum_absolute_score_difference"],
        "patch_mismatches_vs_original_cpp":
            complete["parity_vs_saved_original_cpp"]["new_rust_v5"]["patch_count_mismatches"],
        "per_head_cpp_max_difference": {
            head: value["maximum_absolute_score_difference"]
            for head, value in complete["parity_vs_saved_original_cpp"]
                                    ["new_rust_v5"]["per_head"].items()
        },
        # Never print the detailed 'per_head' dict containing private
        # worst_track paths. Only the full local JSON retains those.
        "worker_invariance_vs_four": {
            key: value for key, value in
            complete["worker_count_invariance_vs_fixed_four"].items()
            if key != "per_head"
        },
        "controller": telemetry,
        "performance": complete["performance"],
        "full_private_report": str(result_file),
    }
    print(json.dumps(brief, indent=2, ensure_ascii=False, allow_nan=False))
    return complete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-db", type=Path, required=True)
    parser.add_argument("--old-rust-db", type=Path, required=True)
    parser.add_argument("--essentia-db", type=Path, required=True)
    parser.add_argument("--fixed-db", type=Path, required=True)
    parser.add_argument("--fixed-report", type=Path, required=True)
    parser.add_argument("--analyzer", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--min-workers", type=int, default=4)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--expected-songs", type=int, default=100)
    parser.add_argument("--score-max-tolerance", type=float, default=0.001, dest="tolerance")
    args = parser.parse_args()
    result = run(args)
    if result["acceptance_status"] != "PASS":
        sys.exit(2)


if __name__ == "__main__":
    main()
