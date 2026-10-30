#!/usr/bin/env python3
"""Observe real native adaptive worker decisions after >=24 synthetic songs.

No OS-load injection, fake time source, or modified decision thresholds.
A zero-adjustment run is reported as inconclusive for real resizing.
Compare exact classification bytes and embeddings against fixed 2 workers.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import wave

from verify_manifest_batch_smoke import stored_features, stored_embeddings

SONGS = 36
DURATION = 300
SAMPLE_RATE = 16_000


def generate_wav(path: Path, hz: int) -> None:
    # Integer-Hz tone repeats exactly each second, cheaply generating long WAVs.
    second = struct.pack(
        "<" + "h" * SAMPLE_RATE,
        *(round(10000 * math.sin(2 * math.pi * hz * i / SAMPLE_RATE))
          for i in range(SAMPLE_RATE)),
    )
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        for _ in range(DURATION):
            wav.writeframesraw(second)


def scan(binary: Path, models: Path, worker: Path, source: Path, manifest: Path,
         db: Path, exports: Path, *, adaptive: bool) -> tuple[dict, float]:
    cmd = [
        str(binary), "scan-features", "--tracks-file", str(manifest),
        "--source-root", str(source), "--db", str(db),
        "--embedding-dir", str(exports), "--models-dir", str(models),
        "--models", "moodtheme", "--audio-backend", "essentia",
        "--essentia-worker", str(worker), "--essentia-timeout-seconds", "120",
        "--workers", "2", "--threads", "1", "--max-new", str(SONGS),
        "--max-errors", "1", "--json",
    ]
    if adaptive:
        cmd += ["--adaptive-workers", "--min-workers", "1", "--max-workers", "3"]
    start = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=720)
    wall = time.perf_counter() - start
    if proc.returncode != 0:
        raise AssertionError(f"native scan failed: {proc.stderr[-2500:]}")
    summary = json.loads(proc.stdout)
    for key in ("analyzed", "pending", "bliss_tracks"):
        if summary[key] != SONGS:
            raise AssertionError(f"wrong song count {key}: {summary[key]}")
    if summary["failures"] or summary["missing_files"]:
        raise AssertionError(f"native scan reported errors: {summary}")
    return summary, wall


def verify_controller(diag: dict) -> dict:
    decisions = diag.get("controller_decisions")
    adjustments = diag.get("adjustments")
    if not isinstance(decisions, dict) or not isinstance(adjustments, list):
        raise AssertionError("No real adaptive controller diagnostic history")
    samples = sum(decisions[k] for k in (
        "high_load_samples", "low_load_samples", "neutral_load_samples"))
    if samples != diag.get("system_load_samples") or samples < 3:
        raise AssertionError(f"Incomplete real resource sampling: {diag}")
    # The OS CPU sampler is interval-based. A completed-song event may have
    # no fresh resource delta, so samples cannot be counted as songs.
    before_gate = decisions["minimum_song_gate_holds"]
    if before_gate < 1 or before_gate >= samples:
        raise AssertionError("No valid samples on both sides of the 24-song gate")
    if decisions["increases"] + decisions["decreases"] != len(adjustments):
        raise AssertionError("Controller counters disagree with resize history")
    if diag.get("initial_workers") != 2:
        raise AssertionError("Unexpected initial concurrency")
    active = 2
    last_song = 23
    for adjustment in adjustments:
        song = adjustment["after_completed_songs"]
        if not last_song < song <= SONGS:
            raise AssertionError("Invalid adjustment completion boundary")
        if adjustment["from_workers"] != active:
            raise AssertionError("Discontinuous worker adjustment sequence")
        target = adjustment["to_workers"]
        if target not in (active - 1, active + 1) or not 1 <= target <= 3:
            raise AssertionError("Invalid production worker adjustment")
        if adjustment["reason"] not in (
            "sustained CPU/RAM pressure", "sustained CPU/RAM headroom"
        ):
            raise AssertionError("Invalid resize reason")
        active, last_song = target, song
    if diag.get("final_workers") != active:
        raise AssertionError("Final workers do not match resize history")
    for key in ("peak_active_analyses", "peak_in_flight"):
        if not 2 <= diag.get(key, 0) <= 3:
            raise AssertionError(f"Unexpected concurrency: {key}")
    return {
        "adjustments": adjustments,
        "controller_decisions": decisions,
        "actual_resizing_observed": bool(adjustments),
        "samples": samples,
        "observations_before_24_completed_songs": before_gate,
        "observations_at_or_after_24_completed_songs": samples - before_gate,
        "initial_workers": 2,
        "final_workers": active,
        "peak_active_analyses": diag["peak_active_analyses"],
        "peak_in_flight": diag["peak_in_flight"],
        "system_cpu_average_percent": diag.get("system_cpu_average_percent"),
        "system_cpu_max_percent": diag.get("system_cpu_max_percent"),
        "system_ram_max_percent": diag.get("system_ram_max_percent"),
    }


def run(binary: Path, models: Path, worker: Path, report: Path) -> None:
    if not binary.is_file() or not worker.is_file() or not models.is_dir():
        raise FileNotFoundError("Missing native scanner/worker/ONNX model prerequisites")
    with tempfile.TemporaryDirectory(prefix="original-essentia-long-adaptive-") as name:
        root = Path(name)
        source = root / "audio"
        source.mkdir()
        tracks = [f"long-{i:02d}.wav" for i in range(SONGS)]
        for i, key in enumerate(tracks):
            generate_wav(source / key, 220 + 19 * i)
        manifest = root / "tracks.txt"
        manifest.write_text("\n".join(tracks) + "\n", encoding="utf-8")
        cases = {}
        for case, adaptive in (("fixed2", False), ("adaptive2", True)):
            db = root / f"{case}.sqlite"
            exports = root / f"{case}-embeddings"
            exports.mkdir()
            summary, wall = scan(
                binary, models, worker, source, manifest, db, exports,
                adaptive=adaptive)
            cases[case] = {
                "summary": summary, "wall": wall,
                "features": stored_features(db),
                "embeddings": stored_embeddings(exports, tracks),
            }
            print(f"{case}: {summary['analyzed']} songs / {wall:.2f}s", flush=True)
        if cases["fixed2"]["features"] != cases["adaptive2"]["features"]:
            raise AssertionError("Adaptive mode changed stored classification bytes")
        if cases["fixed2"]["embeddings"] != cases["adaptive2"]["embeddings"]:
            raise AssertionError("Adaptive mode changed pooled 1280D embeddings")
        fixed_diag = cases["fixed2"]["summary"].get("diagnostics") or {}
        adaptive_diag = cases["adaptive2"]["summary"].get("diagnostics") or {}
        if fixed_diag.get("peak_active_analyses", 0) < 2:
            raise AssertionError("Fixed2 never used concurrent native workers")
        decision = verify_controller(adaptive_diag)
        result = {
            "kind": "native_essentia_adaptive_long_observation_v1",
            "synthetic_songs": SONGS,
            "seconds_per_song": DURATION,
            "model_heads": ["moodtheme"],
            "fresh_sidecars": True,
            "exact_classification_and_1280d_embedding_parity": True,
            "fixed2_wall_seconds": round(cases["fixed2"]["wall"], 3),
            "adaptive2_wall_seconds": round(cases["adaptive2"]["wall"], 3),
            "adaptive_wall_exceeded_20_second_cooldown": cases["adaptive2"]["wall"] >= 21.0,
            "adaptive": decision,
            "actual_resizing_proven_in_this_run": decision["actual_resizing_observed"],
            "limitations": [
                "Unmodified real CPU/RAM readings; no induced synthetic load",
                "Uncontrolled runner load may produce zero legitimate adjustments",
                "CPU load samples occur at time intervals, not on every song completion",
                "Zero changes means resizing was NOT observed, even when CI succeeds",
                "Sequential fixed/adaptive runs cannot establish a speedup",
                "Synthetic tones are not representative real music or NAS access",
            ],
        }
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n",
                          encoding="utf-8")
        print(json.dumps(result, sort_keys=True, indent=2), flush=True)
        if decision["actual_resizing_observed"]:
            print("OBSERVED real native worker resizing under sampled system load")
        else:
            print("INCONCLUSIVE actual resizing: no adjustment was observed")
        print("PASS 36-song native fixed/adaptive exact parity and controller diagnostics")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--essentia-worker", type=Path, required=True)
    parser.add_argument("--report-output", type=Path,
                        default=Path("results/native-adaptive-long.json"))
    args = parser.parse_args()
    run(args.binary.resolve(), args.models_dir.resolve(),
        args.essentia_worker.resolve(), args.report_output.resolve())
