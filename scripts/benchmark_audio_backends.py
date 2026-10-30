#!/usr/bin/env python3
"""Reproducible Windows/Linux A/B benchmark of Rust and native Essentia DSP.

Uses the existing Rust scan-features orchestrator for BOTH backends and
separate fresh schema-v3 SQLite sidecars. Does not alter Bliss or audio.
Sample cohort MUST be an existing bounded TracksV2 database, preferably
the repository's documented 100-key fixture generated on the user's PC.
Never run against the full 64,000-track library without selecting a cohort.
"""
import argparse
import csv
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
import statistics
import struct
import subprocess
import sys
import time

MAX_SAMPLE_TRACKS = 500
VALID_WORKERS = (1, 2, 4, 6, 8, 10, 12)


def checked_cohort(path):
    if not path.is_file():
        raise ValueError(f"Missing cohort database: {path}")
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        query = ("SELECT File FROM TracksV2 "
                 "WHERE Ignore IS NOT 1 ORDER BY File")
        rows = [row[0] for row in conn.execute(query)]
    finally:
        conn.close()
    if not 2 <= len(rows) <= MAX_SAMPLE_TRACKS:
        raise ValueError(
            f"Require a deliberate 2..{MAX_SAMPLE_TRACKS}-track Bliss cohort; "
            f"found {len(rows)} eligible tracks. Never benchmark all LMS tracks."
        )
    if len(set(rows)) != len(rows):
        raise ValueError("Cohort contains duplicate Bliss track identity")
    return rows


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def experiment_plan(worker_counts, repeats, seed):
    """AB / BA order per repeat and shuffled worker order for cache fairness."""
    randomizer = random.Random(seed)
    runs = []
    for round_index in range(repeats):
        counts = list(worker_counts)
        randomizer.shuffle(counts)
        backend_order = ("rust", "essentia") if round_index % 2 == 0 else (
            "essentia", "rust"
        )
        for worker_count in counts:
            for backend in backend_order:
                runs.append((round_index + 1, worker_count, backend))
    return runs


def load_feature_rows(db):
    # Context-managed transactions do NOT close a connection on Windows.
    # Keep the feature sidecar strictly read-only and release the handle.
    with closing(sqlite3.connect(
        f"file:{db.resolve().as_posix()}?mode=ro", uri=True
    )) as conn:
        records = conn.execute(
            "SELECT track_file, model_id, patches_analyzed, scores_f32_le "
            "FROM feature_tracks ORDER BY track_file, model_id"
        ).fetchall()
    result = {}
    for track, model, count, blob in records:
        if not blob or len(blob) % 4:
            raise AssertionError("Invalid feature row shape")
        values = struct.unpack(f"<{len(blob)//4}f", blob)
        if count <= 0 or not all(math.isfinite(x) for x in values):
            raise AssertionError("Nonfinite scores or invalid patch count")
        result[track, model] = (count, values)
    return result


def model_fingerprints_by_head(db):
    """Require one unambiguous model key per head in one isolated sidecar."""
    with closing(sqlite3.connect(
        f"file:{db.resolve().as_posix()}?mode=ro", uri=True
    )) as conn:
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if schema_version != 3:
            raise AssertionError(f"Expected schema v3: {db} has {schema_version}")
        rows = conn.execute(
            "SELECT model_id, model_key FROM feature_tracks"
        ).fetchall()
    keys = {}
    for head, fingerprint in rows:
        if not fingerprint:
            raise AssertionError(f"Missing model fingerprint for {head}")
        if head in keys and keys[head] != fingerprint:
            raise AssertionError(
                f"Mixed model fingerprints for head {head} within {db}"
            )
        keys[head] = fingerprint
    if not keys:
        raise AssertionError(f"No recorded model keys in {db}")
    return keys


def feature_model_definitions_by_head(db, backend):
    """Compare actual ONNX/label identity, not frontend deployment hash keys.

    The C++ frontend intentionally adds its worker-executable SHA and optional
    native DLL manifest SHA to models_sha256_json when calculating model_key.
    Those are *cache identity*, not alternate ONNX model weights.
    """
    if backend not in ("rust", "essentia"):
        raise ValueError(f"Unknown audio backend: {backend}")
    with closing(sqlite3.connect(
        f"file:{db.resolve().as_posix()}?mode=ro", uri=True
    )) as conn:
        rows = conn.execute(
            "SELECT DISTINCT t.model_id, m.embedding_model, "
            "m.classification_model, m.models_sha256_json, "
            "m.aggregation, m.classes_json "
            "FROM feature_tracks AS t "
            "JOIN feature_models AS m ON m.model_key = t.model_key"
        ).fetchall()
    models = {}
    deployment_keys = {
        "essentia_cpp_worker_binary_sha256",
        "essentia_cpp_native_deployment_manifest_sha256",
    }
    for head, encoder, classifier, raw_hashes, aggregation, raw_labels in rows:
        try:
            hashes, labels = json.loads(raw_hashes), json.loads(raw_labels)
        except (TypeError, ValueError) as exc:
            raise AssertionError(f"Malformed model metadata for {head}") from exc
        if not isinstance(hashes, dict) or not isinstance(labels, list):
            raise AssertionError(f"Invalid model metadata shapes for {head}")
        required = {encoder, classifier}
        if len(required) != 2 or not all(
            isinstance(name, str) and name.endswith(".onnx")
            for name in required
        ):
            raise AssertionError(f"Invalid shared model filenames for {head}")
        extra = set(hashes) - required
        if not required <= set(hashes) or (
            backend == "rust" and extra
        ) or (
            backend == "essentia"
            and (extra - deployment_keys
                 or "essentia_cpp_worker_binary_sha256" not in extra)
        ):
            raise AssertionError(
                f"Unexpected {backend} model SHA keys for {head}: {sorted(extra)}"
            )
        # Every stored hash must be a full SHA256 hex digest.
        if any(
            not isinstance(value, str)
            or len(value) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in value)
            for value in hashes.values()
        ):
            raise AssertionError(f"Invalid SHA256 digest in model metadata for {head}")
        if not labels or not all(isinstance(x, str) and x for x in labels):
            raise AssertionError(f"Invalid ordered class metadata for {head}")
        if len(set(labels)) != len(labels):
            raise AssertionError(f"Duplicate class labels for {head}")
        definition = (
            encoder, classifier, hashes[encoder].lower(),
            hashes[classifier].lower(), aggregation, tuple(labels),
        )
        if head in models and models[head] != definition:
            raise AssertionError(f"Conflicting model definitions for {head}")
        models[head] = definition
    if set(models) != set(model_fingerprints_by_head(db)):
        raise AssertionError("Feature model metadata missing or mismatched")
    return models


def verify_backend_fingerprint_separation(rust_db, essentia_db):
    old = model_fingerprints_by_head(rust_db)
    new = model_fingerprints_by_head(essentia_db)
    if old.keys() != new.keys():
        raise AssertionError("Rust/Essentia model heads differ")
    shared = sorted(key for key in old if old[key] == new[key])
    if shared:
        raise AssertionError(
            "Distinct DSP backends must not share feature fingerprint: "
            + ", ".join(shared)
        )
    old_definitions = feature_model_definitions_by_head(rust_db, "rust")
    new_definitions = feature_model_definitions_by_head(essentia_db, "essentia")
    if old_definitions != new_definitions:
        different = sorted(
            head for head in old_definitions
            if old_definitions.get(head) != new_definitions.get(head)
        )
        raise AssertionError(
            f"Different ONNX model weights, class labels, or aggregation: {different}"
        )
    return sorted(old)


def compare_feature_tables(baseline, alternative, expected_models=None,
                           expected_tracks=None):
    """Strict per-track/head parity with actionable per-head error diagnostics.

    Compare numeric arrays, not backend-specific model fingerprint keys.
    Keep worst offending file keys in local JSON only; never upload it.
    """
    if baseline.keys() != alternative.keys():
        missing = sorted(baseline.keys() - alternative.keys())
        extra = sorted(alternative.keys() - baseline.keys())
        raise AssertionError(
            f"Different analyzed cohorts: missing={len(missing)}, extra={len(extra)} "
            f"examples_missing={missing[:3]} examples_extra={extra[:3]}"
        )

    dimensions = {"genre": 87, "moodtheme": 56, "voice": 2}
    if expected_tracks is not None:
        if len(expected_tracks) != len(set(expected_tracks)):
            raise AssertionError("Expected real-music cohort contains duplicate keys")
        observed = {file for file, _ in baseline}
        if observed != set(expected_tracks):
            missing = sorted(set(expected_tracks) - observed)
            extra = sorted(observed - set(expected_tracks))
            raise AssertionError(
                "Feature sidecar does not match exact Bliss cohort: "
                f"missing={missing[:5]}, extra={extra[:5]}"
            )
    if expected_models is not None:
        expected_models = tuple(expected_models)
        if not expected_models or len(expected_models) != len(set(expected_models)):
            raise ValueError("Expected model names must be distinct and nonempty")
        if len(baseline) % len(expected_models):
            raise AssertionError("Partial model-head coverage in feature sidecar")
        track_count = len(baseline) // len(expected_models)
        files = {track for track, _ in baseline}
        if len(files) != track_count or any(
            (file, head) not in baseline for file in files
            for head in expected_models
        ):
            raise AssertionError("Some tracks lack requested model heads")
    stats = {}
    patch_mismatches = []
    worst = None
    total_sum, total_count = 0.0, 0
    for (file, head), (a_count, a) in sorted(baseline.items()):
        b_count, b = alternative[file, head]
        if a_count != b_count:
            patch_mismatches.append({
                "track_file": file, "head": head,
                "rust_patches": a_count, "essentia_patches": b_count,
            })
        if len(a) != len(b):
            raise AssertionError(f"Class-vector dimension mismatch: {file}, {head}")
        if head in dimensions and len(a) != dimensions[head]:
            raise AssertionError(
                f"Invalid known head dimension {file}, {head}: {len(a)}"
            )
        if not all(math.isfinite(x) for x in (*a, *b)):
            raise AssertionError(f"Nonfinite model output at {file}, {head}")
        errors = [abs(x - y) for x, y in zip(a, b)]
        head_stats = stats.setdefault(head, {
            "track_count": 0, "score_count": 0,
            "maximum_absolute_score_difference": 0.0, "score_error_sum": 0.0,
            "max_error_track": None, "max_error_class_index": None,
        })
        head_stats["track_count"] += 1
        head_stats["score_count"] += len(errors)
        head_stats["score_error_sum"] += sum(errors)
        for index, error in enumerate(errors):
            if error > head_stats["maximum_absolute_score_difference"]:
                head_stats["maximum_absolute_score_difference"] = error
                head_stats["max_error_track"] = file
                head_stats["max_error_class_index"] = index
            if worst is None or error > worst["absolute_error"]:
                worst = {
                    "track_file": file, "head": head, "class_index": index,
                    "rust_score": a[index], "essentia_score": b[index],
                    "absolute_error": error,
                }
        total_sum += sum(errors)
        total_count += len(errors)

    if not total_count:
        raise AssertionError("Empty feature comparison")
    per_head = {}
    for head, item in sorted(stats.items()):
        per_head[head] = {
            "tracks": item["track_count"],
            "compared_scores": item["score_count"],
            "maximum_absolute_score_difference":
                item["maximum_absolute_score_difference"],
            "mean_absolute_score_difference":
                item["score_error_sum"] / item["score_count"],
            "worst_track": item["max_error_track"],
            "worst_class_index": item["max_error_class_index"],
        }
    return {
        "tracks_and_heads": len(baseline),
        "compared_scores": total_count,
        "patch_count_mismatches": len(patch_mismatches),
        "patch_count_mismatch_examples": patch_mismatches[:10],
        "maximum_absolute_score_difference": worst["absolute_error"],
        "mean_absolute_score_difference": total_sum / total_count,
        "worst_score_difference": worst,
        "per_head": per_head,
    }


def validate_report(report, expected):
    if (report.get("analyzed") != expected or report.get("failures") != 0
            or report.get("missing_files") != 0):
        raise AssertionError(
            f"Scan incomplete: analyzed={report.get('analyzed')} "
            f"failures={report.get('failures')} "
            f"missing={report.get('missing_files')}; expected={expected}"
        )
    if report.get("pending") != expected:
        raise AssertionError("Scan did not attempt exactly the expected cohort")


def run_scan(args, round_index, workers, backend, expected):
    stem = f"round-{round_index:02d}-workers-{workers:02d}-{backend}"
    db = args.output_dir / (stem + ".db")
    result_file = args.output_dir / (stem + ".json")
    err_file = args.output_dir / (stem + ".stderr.txt")
    if db.exists() or result_file.exists() or err_file.exists():
        raise FileExistsError(f"Refusing to overwrite benchmark artifacts for {stem}")
    cmd = [
        str(args.analyzer), "scan-features",
        "--bliss-db", str(args.cohort_db),
        "--db", str(db),
        "--models-dir", str(args.models_dir),
        "--models", args.models,
        "--workers", str(workers),
        "--threads", "1",
        "--max-errors", "1",
        "--max-new", str(expected),
        "--audio-backend", backend,
        "--json",
    ]
    if args.source_root:
        cmd.extend(["--source-root", str(args.source_root)])
    if args.library_root:
        cmd.extend(["--library-root", args.library_root])
    if backend == "essentia":
        cmd.extend([
            "--essentia-worker", str(args.essentia_worker),
            "--essentia-timeout-seconds", str(args.timeout_seconds),
        ])
    start = time.perf_counter()
    with result_file.open("w", encoding="utf-8") as out, err_file.open(
        "w", encoding="utf-8"
    ) as error:
        result = subprocess.run(cmd, stdout=out, stderr=error, check=False)
    elapsed = time.perf_counter() - start
    if result.returncode:
        raise RuntimeError(
            f"{stem} failed (exit {result.returncode}); inspect {err_file}"
        )
    report = json.loads(result_file.read_text(encoding="utf-8"))
    validate_report(report, expected)
    details = report.get("diagnostics") or {}
    scan = {
        "round": round_index, "workers": workers, "backend": backend,
        "tracks": expected, "seconds": elapsed,
        "songs_per_minute": 60.0 * expected / elapsed,
        "reported_scan_seconds": report["elapsed_seconds"],
        "cpu_average_percent": details.get("system_cpu_average_percent"),
        "system_ram_max_percent": details.get("system_ram_max_percent"),
        "rust_working_set_mib": details.get("process_working_set_max_mib"),
        "process_tree_working_set_mib":
            details.get("process_tree_working_set_max_mib"),
        "process_tree_private_bytes_mib":
            details.get("process_tree_private_bytes_max_mib"),
        "native_children_max": details.get("native_child_processes_max"),
        "incomplete_memory_samples":
            details.get("process_tree_incomplete_samples"),
        "sqlite": db.name, "report": result_file.name,
    }
    if not math.isfinite(elapsed) or elapsed <= 0.0:
        raise AssertionError("Invalid wall-clock measurement")
    return scan, load_feature_rows(db)


def matrix_aggregate(runs):
    groups = {}
    for record in runs:
        groups.setdefault((record["workers"], record["backend"]), []).append(record)
    data = []
    for (workers, backend), entries in sorted(groups.items()):
        data.append({
            "workers": workers,
            "backend": backend,
            "runs": len(entries),
            "median_seconds": statistics.median(x["seconds"] for x in entries),
            "median_songs_per_minute": statistics.median(
                x["songs_per_minute"] for x in entries),
            "max_process_tree_working_set_mib": max(
                (x["process_tree_working_set_mib"]
                 for x in entries if x["process_tree_working_set_mib"] is not None),
                default=None),
            "max_system_ram_percent": max(
                (x["system_ram_max_percent"] for x in entries
                 if x["system_ram_max_percent"] is not None),
                default=None),
        })
    return data


def validate_source_roots(source_root, library_root):
    """Relative TracksV2.File keys need only --source-root.

    --library-root remaps an existing absolute prefix and therefore always
    requires --source-root; the converse is not true.
    """
    if library_root and not source_root:
        raise ValueError("--library-root requires --source-root")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-db", required=True, type=Path,
                        help="Prebuilt bounded Bliss TracksV2 subset, e.g. sample-100.db")
    parser.add_argument("--analyzer", required=True, type=Path)
    parser.add_argument("--essentia-worker", required=True, type=Path)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--library-root")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--models", default="moodtheme,genre,voice")
    parser.add_argument("--workers", default="1,2,4,6")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261020)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--score-max-tolerance", type=float, default=1e-3)
    args = parser.parse_args()
    if args.repeats not in (1, 2, 3, 4):
        parser.error("--repeats must be between 1 and 4")
    if args.timeout_seconds not in range(1, 7201):
        parser.error("--timeout-seconds must be 1..7200")
    try:
        counts = [int(i) for i in args.workers.split(",")]
    except ValueError:
        parser.error("--workers must be comma-separated integers")
    if not counts or len(counts) != len(set(counts)) or any(
        count not in VALID_WORKERS for count in counts
    ):
        parser.error(f"--workers must be unique values from {VALID_WORKERS}")
    if not 0 < args.score_max_tolerance < 0.1:
        parser.error("--score-max-tolerance must be between zero and 0.1")
    try:
        validate_source_roots(args.source_root, args.library_root)
    except ValueError as error:
        parser.error(str(error))
    for name, path in [("analyzer", args.analyzer),
                       ("Essentia worker", args.essentia_worker)]:
        if not path.is_file():
            parser.error(f"Missing {name} executable: {path}")
    if not args.models_dir.is_dir():
        parser.error("Missing models directory")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("Output directory must be new or empty (fresh sidecars)")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.analyzer = args.analyzer.resolve()
    args.essentia_worker = args.essentia_worker.resolve()
    args.cohort_db = args.cohort_db.resolve()
    args.models_dir = args.models_dir.resolve()
    if args.source_root:
        args.source_root = args.source_root.resolve()

    cohort = checked_cohort(args.cohort_db)
    original_cohort_sha = digest(args.cohort_db)
    manifest = {
        "schema_version": 1, "cohort_size": len(cohort),
        "cohort_database_sha256": original_cohort_sha,
        "analyzer_binary_sha256": digest(args.analyzer),
        "essentia_worker_binary_sha256": digest(args.essentia_worker),
        "models": args.models, "worker_counts": counts,
        "repeats": args.repeats, "seed": args.seed,
        "backend_order": "AB/BA per repeat, worker counts shuffled",
        "note": "Synthetic/test or private library only; do not commit output artifacts",
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    runs, comparisons = [], []
    for round_index, count, backend in experiment_plan(
        counts, args.repeats, args.seed
    ):
        record, scores = run_scan(args, round_index, count, backend, len(cohort))
        runs.append(record)
        print(f"{backend:8} workers={count} run={round_index}: "
              f"{record['seconds']:.2f}s; "
              f"{record['songs_per_minute']:.1f} tracks/min", flush=True)
        partner = next((r for r in runs[:-1] if r["round"] == round_index
                        and r["workers"] == count and r["backend"] != backend), None)
        if partner:
            prior = load_feature_rows(args.output_dir / partner["sqlite"])
            baseline, native = (scores, prior) if backend == "rust" else (prior, scores)
            comp = compare_feature_tables(
                baseline, native, expected_models=args.models.split(","),
                expected_tracks=cohort,
            )
            rust_db, native_db = (
                (args.output_dir / record["sqlite"], args.output_dir / partner["sqlite"])
                if backend == "rust" else
                (args.output_dir / partner["sqlite"], args.output_dir / record["sqlite"])
            )
            comp["fingerprint_heads_checked"] = verify_backend_fingerprint_separation(
                rust_db, native_db
            )
            comp.update({"workers": count, "round": round_index})
            comparisons.append(comp)
            if comp["patch_count_mismatches"] or (
                comp["maximum_absolute_score_difference"]
                > args.score_max_tolerance
            ):
                diagnostic = {
                    "status": "failed",
                    "reason": "Real audio Rust/Essentia parity outside configured bounds",
                    "maximum_allowed_score_difference": args.score_max_tolerance,
                    "comparison": comp,
                    "round": round_index,
                    "workers": count,
                    "input_cohort_sha256": original_cohort_sha,
                }
                failure_file = args.output_dir / "parity-failure.json"
                failure_file.write_text(
                    json.dumps(diagnostic, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                raise AssertionError(
                    f"Backend drift at {count} workers, round {round_index}. "
                    f"See {failure_file} for per-head diagnostics and worst track."
                )

    if digest(args.cohort_db) != original_cohort_sha:
        raise AssertionError("Input Bliss cohort database changed; benchmark invalid")
    summary = {
        "manifest": manifest,
        "runs": runs,
        "aggregates": matrix_aggregate(runs),
        "backend_parity": comparisons,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if runs:
        with (args.output_dir / "runs.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(runs[0]))
            writer.writeheader()
            writer.writerows(runs)
    print(f"Benchmark and backend score parity PASS: {args.output_dir}")


if __name__ == "__main__":
    main()
