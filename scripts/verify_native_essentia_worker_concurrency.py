#!/usr/bin/env python3
"""Native Essentia C++ worker-concurrency gate on deterministic public test tones.

Runs the actual Rust scan-features orchestrator and native Essentia child EXE.
Only synthetic audio and official ONNX weights; no private music or Bliss DB.
Fixed 1/2/4 and repeated fixed 2 are parity/concurrency tests,
not a throughput ranking or any evidence of autotuning.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time

from verify_manifest_batch_smoke import (
    stored_embeddings, stored_features, synthetic_wav,
)


def run_scan(binary: Path, models: Path, native: Path, audio: Path,
             manifest: Path, sidecar: Path, exports: Path,
             name: str, workers: int) -> tuple[dict, float]:
    args = [
        str(binary), "scan-features",
        "--tracks-file", str(manifest),
        "--source-root", str(audio),
        "--db", str(sidecar),
        "--embedding-dir", str(exports),
        "--models-dir", str(models),
        "--models", "moodtheme",
        "--audio-backend", "essentia",
        "--essentia-worker", str(native),
        "--essentia-timeout-seconds", "120",
        "--workers", str(workers),
        "--threads", "1",
        "--max-new", "8",
        "--max-errors", "1",
        "--json",
    ]
    started = time.perf_counter()
    done = subprocess.run(args, text=True, capture_output=True, check=False, timeout=180)
    wall_seconds = time.perf_counter() - started
    if done.returncode:
        raise AssertionError(f"{name}: native C++ scan exit={done.returncode}: "
                             + done.stderr[-2000:])
    report = json.loads(done.stdout)
    if any(report[k] != 8 for k in ("analyzed", "pending", "bliss_tracks")):
        raise AssertionError(f"{name}: incomplete 8-song cohort: {report}")
    if report["failures"] or report["missing_files"]:
        raise AssertionError(f"{name}: native C++ analysis failed: {report}")
    return report, wall_seconds


def run(binary: Path, models: Path, native: Path) -> None:
    for target in (binary, native):
        if not target.is_file():
            raise FileNotFoundError(target)
    if not models.is_dir():
        raise FileNotFoundError(models)
    with tempfile.TemporaryDirectory(prefix="native-essentia-fixed-worker-gate-") as temp:
        base = Path(temp)
        audio = base / "audio"
        audio.mkdir()
        keys = [f"tone-{i:02d}.wav" for i in range(8)]
        for i, key in enumerate(keys):
            synthetic_wav(audio / key, 220 + i * 51, seconds=20)
        manifest = base / "tracks.txt"
        manifest.write_text("\n".join(keys) + "\n", encoding="utf-8")

        baseline_features = baseline_embeddings = None
        observations = []
        for name, workers in (
            ("fixed1", 1),
            ("fixed2", 2),
            ("fixed4", 4),
            ("fixed2_repeat", 2),
        ):
            sidecar = base / f"{name}.sqlite"
            exports = base / f"{name}-embeddings"
            exports.mkdir()
            summary, wall = run_scan(
                binary, models, native, audio, manifest,
                sidecar, exports, name, workers,
            )
            features = stored_features(sidecar)
            embeddings = stored_embeddings(exports, keys)
            if len(features) != len(keys) or len(embeddings) != len(keys):
                raise AssertionError(f"{name}: unexpected classification/embedding coverage")
            if baseline_features is None:
                baseline_features, baseline_embeddings = features, embeddings
            elif features != baseline_features or embeddings != baseline_embeddings:
                raise AssertionError(
                    f"{name}: native C++ fixed worker count changed "
                    "stored classification bytes or pooled 1280D vectors"
                )

            diag = summary.get("diagnostics") or {}
            # This counter is independent of CPU utilization and proves the
            # Rust scanner entered multiple analyses concurrently. Every one
            # uses --audio-backend essentia, with no Rust fallback permitted.
            if workers > 1 and diag.get("peak_active_analyses", 0) < workers:
                raise AssertionError(
                    f"{name}: did not observe {workers} concurrent analyses: {diag}"
                )
            if workers > 1 and diag.get("peak_in_flight", 0) < workers:
                raise AssertionError(f"{name}: coordinator did not dispatch {workers} jobs")
            observations.append({
                "case": name,
                "requested_workers": workers,
                "adaptive_enabled": False,
                "analyzed": summary["analyzed"],
                "wall_seconds": round(wall, 3),
                "preworker_cpu_baseline_seconds": (
                    (diag.get("baseline") or {}).get("cpu_measurement_seconds")
                ),
                "peak_active_analyses": diag.get("peak_active_analyses"),
                "peak_in_flight": diag.get("peak_in_flight"),
                "sampled_native_children_max": diag.get("native_child_processes_max"),
                "native_tree_private_mib_max": diag.get("process_tree_private_bytes_max_mib"),
                "native_tree_incomplete_samples": diag.get("process_tree_incomplete_samples"),
                "configured_capacity_unchanged": diag.get("final_workers") == diag.get("initial_workers"),
            })
            print(f"PASS {name}: {workers} workers, "
                  f"{summary['analyzed']} native Essentia songs, "
                  f"peak active={diag.get('peak_active_analyses', 1)}", flush=True)

        print(json.dumps({
            "kind": "synthetic_native_essentia_worker_concurrency_gate_v1",
            "synthetic_songs": len(keys),
            "seconds_per_song": 20,
            "backend": "original_essentia_cpp",
            "models": ["moodtheme"],
            "numeric_parity": "EXACT_classification_bytes_and_1280d_embediings",
            "observations": observations,
            "limitations": [
                "8 synthetic 20-second WAV tones are not representative music",
                "A completed-song resource sampler may miss short-lived native children",
                "These timings include process startup and preworker CPU baseline",
                "No dynamic worker control is present in the product CLI",
                "This gate does not establish NAS throughput or production speedups",
            ],
        }, indent=2, sort_keys=True))
        print("PASS exact C++ serial/fixed-worker classification and song-embedding parity")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--essentia-worker", type=Path, required=True)
    opts = parser.parse_args()
    run(opts.binary.resolve(), opts.models_dir.resolve(), opts.essentia_worker.resolve())
