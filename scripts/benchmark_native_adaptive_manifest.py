#!/usr/bin/env python3
"""Local-only, bounded native Essentia fixed-vs-adaptive worker benchmark.

Uses a deliberately sampled Bliss TracksV2 cohort (30..500 entries) and
new independent feature sidecars. Never uploads music or reports to CI.
This is an observational benchmark, not simulated adaptive telemetry.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
import csv
import json
import math
import os
import ctypes
from pathlib import Path
import random
import sqlite3
import statistics
import subprocess
import time

from benchmark_audio_backends import (
    checked_cohort, digest, model_fingerprints_by_head, validate_report,
)
from verify_manifest_batch_smoke import stored_embeddings

def normalize_manifest_key(key: str, library_root: str | None) -> str:
    """Map a sampled TracksV2.File identity to a safe source-relative manifest key.

    This is deliberate identity normalization. Scanner --tracks-file forbids
    absolute paths and --library-root. Reject mismatched roots rather than
    trying the full original Bliss database or searching the whole disk.
    """
    if library_root is not None:
        prefix = library_root.rstrip("/\\")
        if not prefix:
            raise ValueError("--library-root must contain a nonempty absolute prefix")
        if not key.startswith(prefix) or key[len(prefix):len(prefix) + 1] not in ("/", "\\"):
            raise ValueError("A sample track does not have the specified --library-root prefix")
        key = key[len(prefix) + 1:]
    normalized = key.replace("\\", "/")
    parts = normalized.split("/")
    if (not normalized or normalized != normalized.strip()
            or normalized.startswith("/") or ":" in normalized
            or "\x00" in normalized or "\r" in normalized or "\n" in normalized
            or any(not part or part in (".", "..") for part in parts)):
        raise ValueError("A sample track is not a safe source-root-relative manifest identity")
    return normalized


def prepare_manifest_keys(keys: list[str], library_root: str | None) -> list[str]:
    mapped = [normalize_manifest_key(key, library_root) for key in keys]
    if len(set(mapped)) != len(mapped):
        raise ValueError("Bliss paths collide after normalization to manifest identities")
    return mapped


def verify_music_paths(keys: list[str], source_root: Path) -> None:
    """Read-only availability and root containment check before starting ONNX."""
    if not source_root.is_dir():
        raise ValueError("Missing --source-root directory")
    actual_root = source_root.resolve(strict=True)
    missing = 0
    for key in keys:
        path = source_root.joinpath(*key.split("/"))
        if not path.is_file():
            missing += 1
            continue
        if not path.resolve(strict=True).is_relative_to(actual_root):
            raise ValueError("Selected music file resolves outside --source-root")
    if missing:
        raise ValueError(f"{missing}/{len(keys)} sample audio files are unavailable under --source-root")


def exact_feature_rows(db: Path, track_keys: list[str],
                       heads: list[str]) -> dict[tuple[str, str], tuple]:
    """Compare EVERY per-track/head float blob, not only a song's last model.

    The short synthetic test helper stored_features() has a one-row-per-song
    contract and deliberately collapses keys across different model heads.
    It must not be used to validate the 3-head real-music benchmark.
    """
    with closing(sqlite3.connect(
        f"file:{db.resolve().as_posix()}?mode=ro", uri=True
    )) as conn:
        rows = conn.execute(
            "SELECT track_file, model_id, model_key, audio_sha256, "
            "patches_analyzed, scores_f32_le FROM feature_tracks "
            "ORDER BY track_file, model_id"
        ).fetchall()
    expected = {(track, head) for track in track_keys for head in heads}
    found = {(track, head) for track, head, *_ in rows}
    if len(rows) != len(expected) or found != expected:
        raise AssertionError(
            f"Wrong real-cohort classification coverage: expected "
            f"{len(expected)} rows, found {len(rows)}; missing="
            f"{len(expected - found)} unexpected={len(found - expected)}"
        )
    dimensions = {"moodtheme": 56, "genre": 87, "voice": 2}
    for track, head, model_key, sha, patches, blob in rows:
        if not model_key or not sha or len(sha) != 64 or patches <= 0:
            raise AssertionError(f"Invalid feature metadata for {head}")
        if not blob or len(blob) != dimensions[head] * 4:
            raise AssertionError(f"Invalid {head} score blob dimension")
    return {
        (track, head): (model_key, sha, patches, bytes(blob))
        for track, head, model_key, sha, patches, blob in rows
    }


POLICY_MODES = ("fixed6", "adaptive2_gate24", "adaptive4_gate24",
                "adaptive6_gate24", "adaptive2_gate8")
SCALING_MODES = ("fixed6", "fixed8", "fixed10", "fixed12")


def windows_memory_snapshot() -> dict[str, float] | None:
    """Physical RAM headroom, independent of completion-driven scanner sampling.

    Return None on unsupported platforms or failed Windows API calls: actual
    scaling runs fail closed rather than interpreting missing data as free RAM.
    """
    if os.name != "nt":
        return None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    state = MEMORYSTATUSEX()
    state.dwLength = ctypes.sizeof(state)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
        return None
    return {
        "available_mib": state.ullAvailPhys / 1048576.0,
        "total_mib": state.ullTotalPhys / 1048576.0,
        "ram_percent": float(state.dwMemoryLoad),
    }


def memory_guard_reason(snapshot: dict[str, float] | None,
                        min_available_mib: float,
                        max_ram_percent: float) -> str | None:
    if snapshot is None:
        return "Unable to read Windows physical RAM; refusing unsafe scan"
    if not all(math.isfinite(v) for v in snapshot.values()):
        return "Invalid Windows physical RAM telemetry"
    if snapshot["available_mib"] < min_available_mib:
        return (f"Available physical RAM {snapshot['available_mib']:.0f} MiB "
                f"below safety reserve {min_available_mib:.0f} MiB")
    if snapshot["ram_percent"] >= max_ram_percent:
        return (f"System RAM {snapshot['ram_percent']:.1f}% "
                f"at/above safety limit {max_ram_percent:.1f}%")
    return None


def run_scanner_guarded(cmd: list[str], out, err,
                        min_available_mib: float,
                        max_ram_percent: float) -> tuple[int, float]:
    """Monitor Windows RAM once per second; stop the entire native process tree.

    This safety gate is independent of the adaptive controller and thus also
    protects fixed-12 experiments. No result is declared valid on abort.
    """
    first = windows_memory_snapshot()
    reason = memory_guard_reason(first, min_available_mib, max_ram_percent)
    if reason:
        raise RuntimeError("RAM safety preflight: " + reason)
    min_seen = first["available_mib"]
    with subprocess.Popen(cmd, stdout=out, stderr=err) as proc:
        while proc.poll() is None:
            snapshot = windows_memory_snapshot()
            reason = memory_guard_reason(snapshot, min_available_mib, max_ram_percent)
            if reason:
                # Windows tree termination covers native Essentia child processes;
                # killing only the Rust parent would leave ONNX workers running.
                try:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            check=False, timeout=15,
                        )
                finally:
                    if proc.poll() is None:
                        proc.kill()
                    proc.wait()
                raise RuntimeError("RAM safety stop: " + reason)
            min_seen = min(min_seen, snapshot["available_mib"])
            time.sleep(1)
        return proc.returncode, min_seen



def mode_configuration(mode: str) -> tuple[int, bool, int, int]:
    """workers, adaptive, min_workers, completed-song gate."""
    if mode in POLICY_MODES[1:]:
        # Separate policy study; all adaptive runs share min=2 and max=6.
        parts = mode.removeprefix("adaptive").split("_gate")
        workers, gate = map(int, parts)
        return workers, True, 2, gate
    if mode == "adaptive2":
        return 2, True, 1, 24
    if mode in ("fixed1", "fixed2", "fixed4", "fixed6", "fixed8", "fixed10", "fixed12"):
        return int(mode.removeprefix("fixed")), False, 1, 24
    raise ValueError(f"Unknown bounded benchmark mode: {mode}")


def schedule(repeats: int, seed: int, experiment: str = "baseline") -> list[tuple[int, str]]:
    modes = (list(SCALING_MODES) if experiment == "native-scaling" else
             list(POLICY_MODES) if experiment == "adaptive-policy" else
             ["fixed1", "fixed2", "fixed4", "fixed6", "adaptive2"])
    if experiment not in ("baseline", "adaptive-policy", "native-scaling"):
        raise ValueError("Unknown experiment")
    rng = random.Random(seed)
    rng.shuffle(modes)
    return [
        (repeat + 1, mode)
        for repeat in range(repeats)
        for mode in (modes if repeat % 2 == 0 else list(reversed(modes)))
    ]


def analyze(args: argparse.Namespace, round_no: int, mode: str,
            expected: int) -> tuple[dict, dict, dict]:
    workers, is_adaptive, min_workers, completed_gate = mode_configuration(mode)
    stem = f"round-{round_no:02d}-{mode}"
    db = args.output_dir / f"{stem}.sqlite"
    embedding_dir = args.output_dir / f"{stem}-embeddings"
    stdout_path = args.output_dir / f"{stem}.scanner.json"
    stderr_path = args.output_dir / f"{stem}.stderr.txt"
    if db.exists() or embedding_dir.exists() or stdout_path.exists() or stderr_path.exists():
        raise FileExistsError(f"Will not reuse or overwrite benchmark output: {stem}")
    embedding_dir.mkdir()
    cmd = [
        str(args.analyzer), "scan-features",
        "--tracks-file", str(args.manifest_file), "--source-root", str(args.source_root),
        "--db", str(db),
        "--embedding-dir", str(embedding_dir),
        "--models-dir", str(args.models_dir),
        "--models", args.models,
        "--audio-backend", "essentia",
        "--essentia-worker", str(args.essentia_worker),
        "--essentia-timeout-seconds", str(args.timeout_seconds),
        "--workers", str(workers),
        "--priority", args.scan_priority,
        "--threads", "1",
        "--max-new", str(expected), "--max-errors", "1", "--json",
    ]
    if is_adaptive:
        cmd.extend([
            "--adaptive-workers", "--min-workers", str(min_workers),
            "--max-workers", "6",
            "--adaptive-min-completed-songs", str(completed_gate),
        ])
    start = time.perf_counter()
    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open(
        "w", encoding="utf-8"
    ) as err:
        returncode, guarded_ram_min_mib = run_scanner_guarded(
            cmd, out, err, args.min_available_ram_mib, args.max_system_ram_percent
        )
    elapsed = time.perf_counter() - start
    if returncode != 0:
        raise RuntimeError(f"{stem} failed (exit {returncode}); inspect {stderr_path}")
    summary = json.loads(stdout_path.read_text(encoding="utf-8"))
    validate_report(summary, expected)
    diag = summary.get("diagnostics") or {}
    baseline_s = (diag.get("baseline") or {}).get("cpu_measurement_seconds") or 0
    if not 0 <= baseline_s < elapsed or not math.isfinite(elapsed):
        raise AssertionError("Invalid wall time or resource-baseline measurement")
    priority = summary.get("priority")
    if not isinstance(priority, dict):
        raise AssertionError("Scanner missing priority diagnostics; use current PR #18 Windows binary")
    if (priority.get("requested") != args.scan_priority
            or priority.get("policy") != args.scan_priority
            or priority.get("effective_scanner") != args.scan_priority):
        raise AssertionError(
            f"{stem}: real scanner priority differs from requested {args.scan_priority}: {priority}"
        )
    child_classes = priority.get("native_worker_classes")
    if (child_classes != [args.scan_priority]
            or priority.get("native_worker_observation_failures") != 0):
        raise AssertionError(
            f"{stem}: actual native Essentia worker priority is not verified: {priority}"
        )
    adjustments = diag.get("adjustments", [])
    if not isinstance(adjustments, list):
        raise AssertionError("Malformed native adaptive diagnostics")
    if is_adaptive:
        if (diag.get("initial_workers") != workers
                or not min_workers <= diag.get("final_workers", 0) <= 6
                or diag.get("adaptive_min_completed_songs") != completed_gate):
            raise AssertionError("Adaptive mode, gate, or worker bounds do not match requested experiment")
        if any(not min_workers <= event.get("to_workers", 0) <= 6
               or event.get("after_completed_songs", 0) < completed_gate
               for event in adjustments):
            raise AssertionError("Adaptive controller violated gate or worker bounds")
    elif adjustments or diag.get("adaptive_min_completed_songs") is not None:
        raise AssertionError("Fixed worker run unexpectedly changed worker count or gate")
    if not is_adaptive:
        if (diag.get("initial_workers") != workers
                or diag.get("final_workers") != workers
                or diag.get("configured_max_workers") != workers):
            raise AssertionError(f"{stem}: scanner did not honor fixed {workers} workers")
    if diag.get("logical_cpu_capacity", 0) < workers:
        raise AssertionError(f"{stem}: reported CPU capacity below requested workers")
    peak_active = diag.get("peak_active_analyses")
    if not isinstance(peak_active, int) or not 1 <= peak_active <= workers:
        raise AssertionError(f"{stem}: invalid observed concurrency")
    if not 1 <= diag.get("native_child_processes_max", 0) <= workers:
        raise AssertionError(f"{stem}: missing or excessive native Essentia processes")
    record = {
        "round": round_no, "mode": mode,
        "requested_priority": args.scan_priority,
        "observed_scanner_priority": priority["effective_scanner"],
        "observed_native_child_priorities": ",".join(child_classes),
        "initial_workers": workers,
        "adaptive_min_completed_songs": completed_gate if is_adaptive else None,
        "first_resize_after_completed_songs": (
            adjustments[0]["after_completed_songs"] if adjustments else None),
        "resize_song_positions": ",".join(
            str(event["after_completed_songs"]) for event in adjustments),
        "controller_gate_holds": (diag.get("controller_decisions") or {})
            .get("minimum_song_gate_holds"),
        "controller_cooldown_holds": (diag.get("controller_decisions") or {})
            .get("cooldown_holds"),
        "tracks": expected, "wall_seconds": round(elapsed, 3),
        "songs_per_minute": round(expected * 60 / elapsed, 3),
        "preworker_cpu_baseline_seconds": round(baseline_s, 3),
        "wall_excluding_preworker_baseline_seconds": round(elapsed - baseline_s, 3),
        "scan_seconds": round(summary.get("elapsed_seconds", 0), 3),
        "cumulative_decode_seconds": diag.get("cumulative_decode_seconds"),
        "cumulative_preprocess_seconds": diag.get("cumulative_features_seconds"),
        "cumulative_inference_seconds": diag.get("cumulative_inference_seconds"),
        "cumulative_hash_seconds": diag.get("cumulative_hash_seconds"),
        "cumulative_model_load_seconds": diag.get("cumulative_model_load_seconds"),
        "peak_active_analyses": diag.get("peak_active_analyses"),
        "peak_in_flight": diag.get("peak_in_flight"),
        "final_workers": diag.get("final_workers"),
        "adjustments": len(adjustments),
        "system_cpu_average_percent": diag.get("system_cpu_average_percent"),
        "system_cpu_max_percent": diag.get("system_cpu_max_percent"),
        "system_ram_max_percent": diag.get("system_ram_max_percent"),
        "system_available_ram_min_mib": diag.get("system_available_ram_min_mib"),
        "guarded_available_ram_min_mib": round(guarded_ram_min_mib, 2),
        "process_private_mib_max": diag.get("process_private_bytes_max_mib"),
        "native_child_private_mib_max": diag.get("native_child_private_bytes_max_mib"),
        "process_tree_working_set_mib_max": diag.get("process_tree_working_set_max_mib"),
        "process_tree_private_mib_max": diag.get("process_tree_private_bytes_max_mib"),
        "process_tree_incomplete_samples": diag.get("process_tree_incomplete_samples"),
        "native_child_processes_max": diag.get("native_child_processes_max"),
    }
    # Exact parity remains mandatory across all fixed/adaptive run orders.
    return record, exact_feature_rows(db, args.cohort, args.models.split(',')), {
        "vectors": stored_embeddings(embedding_dir, args.cohort),
        "fingerprints": model_fingerprints_by_head(db),
    }


def summarize(runs: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in runs:
        groups[item["mode"]].append(item)
    return [
        {
            "mode": mode,
            "repeats": len(group),
            "median_wall_seconds": round(
                statistics.median(g["wall_seconds"] for g in group), 3),
            "median_songs_per_minute": round(
                statistics.median(g["songs_per_minute"] for g in group), 3),
            "peak_process_tree_private_mib": max(
                (g["process_tree_private_mib_max"] for g in group
                 if g["process_tree_private_mib_max"] is not None),
                default=None),
            "observed_adaptive_adjustments": sum(g["adjustments"] for g in group),
            "min_guarded_available_ram_mib": round(min(
                g["guarded_available_ram_min_mib"] for g in group), 2),
            "peak_native_child_private_mib": max((
                g["native_child_private_mib_max"] for g in group
                if g["native_child_private_mib_max"] is not None), default=None),
            "median_system_cpu_average_percent": (
                round(statistics.median(
                    g["system_cpu_average_percent"] for g in group), 2)
                if all(g["system_cpu_average_percent"] is not None for g in group)
                else None),

        }
        for mode, group in sorted(groups.items())
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-db", required=True, type=Path,
                        help="An existing bounded TracksV2 cohort DB; never a full-library DB")
    parser.add_argument("--analyzer", required=True, type=Path)
    parser.add_argument("--essentia-worker", required=True, type=Path)
    parser.add_argument("--models-dir", required=True, type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--library-root")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--models", default="moodtheme,genre,voice")
    parser.add_argument("--expected-tracks", type=int,
                        help="Fail if the deliberate sample has a different song count")
    parser.add_argument("--experiment", choices=("baseline", "adaptive-policy", "native-scaling"),
                        default="baseline",
                        help="Baseline, controlled adaptive policy, or fixed 6/8/10/12 native scaling")
    parser.add_argument("--scan-priority", choices=("normal", "below-normal", "above-normal"),
                        default="normal",
                        help="Apply identical observed Windows priority to all scan modes")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--min-available-ram-mib", type=float, default=1536,
                        help="Fail closed and stop full process tree below this available physical RAM")
    parser.add_argument("--max-system-ram-percent", type=float, default=90,
                        help="Fail closed and stop full process tree at this system RAM percentage")
    args = parser.parse_args()
    if (not math.isfinite(args.min_available_ram_mib)
            or args.min_available_ram_mib < 512
            or not math.isfinite(args.max_system_ram_percent)
            or not 50 <= args.max_system_ram_percent <= 95):
        parser.error("RAM safety requires reserve >=512 MiB and max RAM 50..95%")
    if args.repeats not in (2, 4):
        parser.error("--repeats must be 2 or 4 for balanced run order")
    if not 1 <= args.timeout_seconds <= 7200:
        parser.error("--timeout-seconds must be 1..7200")
    heads = args.models.split(",")
    if not heads or any(head not in ("moodtheme", "genre", "voice") for head in heads) or len(set(heads)) != len(heads):
        parser.error("Models must be unique names from moodtheme,genre,voice")
    if args.source_root is None:
        parser.error("--source-root is required: embeddings require --tracks-file")
    try:
        cohort = checked_cohort(args.cohort_db)
        mapped = prepare_manifest_keys(cohort, args.library_root)
        verify_music_paths(mapped, args.source_root)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if len(cohort) < 30:
        parser.error("Adaptive evaluation requires a deliberate 30..500-track cohort")
    if args.expected_tracks is not None and len(cohort) != args.expected_tracks:
        parser.error(f"Expected {args.expected_tracks} sample tracks, found {len(cohort)}")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("Output directory must be new/empty; never overwrite prior runs")
    for item in (args.analyzer, args.essentia_worker):
        if not item.is_file():
            parser.error(f"Missing executable: {item}")
    if not args.models_dir.is_dir():
        parser.error("Missing ONNX model directory")
    # Forbid placement inside read-only music/model trees even in plan-only mode.
    out_real = args.output_dir.resolve()
    for protected in (args.source_root.resolve(), args.models_dir.resolve(),
                      args.cohort_db.resolve()):
        if out_real == protected or out_real.is_relative_to(protected):
            parser.error("Benchmark output must be outside source audio, model, and cohort paths")
    plan = schedule(args.repeats, args.seed, args.experiment)
    print("Local, private, bounded experiment plan:")
    print(json.dumps({"tracks": len(cohort), "order": plan,
                      "experiment": args.experiment,
                      "scan_priority": args.scan_priority,
                      "validated_audio_paths": len(mapped),
                      "manifest": "generated locally from bounded TracksV2 cohort",
                      "note": "No music or private database contents uploaded"},
                     indent=2))
    if args.plan_only:
        return
    if os.name != "nt":
        parser.error("Actual native-scaling benchmarks require Windows RAM safety telemetry")
    if args.experiment == "native-scaling" and (os.cpu_count() or 0) < 12:
        parser.error("Native scaling requires at least 12 logical CPUs; no oversubscription")
    reason = memory_guard_reason(
        windows_memory_snapshot(), args.min_available_ram_mib, args.max_system_ram_percent)
    if reason:
        parser.error("RAM safety preflight: " + reason)
    args.cohort = mapped
    args.manifest_file = args.output_dir / "selected-tracks.txt"
    args.analyzer = args.analyzer.resolve()
    args.essentia_worker = args.essentia_worker.resolve()
    args.cohort_db = args.cohort_db.resolve()
    args.models_dir = args.models_dir.resolve()
    args.source_root = args.source_root.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # UTF-8 manifest identity is the relative path, not the original absolute
    # LMS File key. This guarantees all embedding outputs match our lookups.
    args.manifest_file.write_text("\n".join(mapped) + "\n", encoding="utf-8")
    original_cohort_hash = digest(args.cohort_db)
    manifest = {
        "cohort_tracks": len(cohort),
        "cohort_database_sha256": original_cohort_hash,
        "selected_track_manifest_sha256": digest(args.manifest_file),
        "model_file_sha256": {
            item.name: digest(item)
            for item in sorted(args.models_dir.glob("*"))
            if item.is_file() and item.suffix in (".onnx", ".json")
        },
        "analyzer_sha256": digest(args.analyzer),
        "native_worker_sha256": digest(args.essentia_worker),
        "models": args.models,
        "experiment": args.experiment,
        "scan_priority": args.scan_priority,
        "min_available_ram_mib": args.min_available_ram_mib,
        "max_system_ram_percent": args.max_system_ram_percent,
        "schedule": plan,
        "note": "PRIVATE LOCAL BENCHMARK; never commit or upload outputs",
    }
    (args.output_dir / "experiment.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    reference_scores = reference_vectors = reference_models = None
    records: list[dict] = []
    for ordinal, (round_no, mode) in enumerate(plan, start=1):
        rec, scores, extra = analyze(args, round_no, mode, len(cohort))
        if reference_scores is None:
            reference_scores = scores
            reference_vectors = extra["vectors"]
            reference_models = extra["fingerprints"]
        elif (scores != reference_scores or
              extra["vectors"] != reference_vectors or
              extra["fingerprints"] != reference_models):
            raise AssertionError(
                f"Native fixed/adaptive numerical parity drift at {mode}, "
                f"round {round_no}; results remain LOCAL in {args.output_dir}")
        records.append(rec)
        (args.output_dir / "summary.json").write_text(
            json.dumps({"experiment": manifest, "runs": records,
                        "aggregates": summarize(records),
                        "exact_numeric_parity": True},
                       indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with (args.output_dir / "runs.csv").open("w", newline="", encoding="utf-8") as csvout:
            writer = csv.DictWriter(csvout, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
        print(f"PASS {ordinal}/{len(plan)} {mode}: {rec['wall_seconds']:.2f}s; "
              f"resizes={rec['adjustments']}", flush=True)
    if digest(args.cohort_db) != original_cohort_hash:
        raise AssertionError("Read-only input Bliss cohort DB unexpectedly changed")
    if digest(args.manifest_file) != manifest["selected_track_manifest_sha256"]:
        raise AssertionError("Local track manifest unexpectedly changed during the benchmark")
    with (args.output_dir / "runs.csv").open("w", newline="", encoding="utf-8") as csvout:
        writer = csv.DictWriter(csvout, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    print(f"PASS {args.experiment} fixed/adaptive benchmark, exact parity: {args.output_dir}")


if __name__ == "__main__":
    main()
