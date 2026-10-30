#!/usr/bin/env python3
"""Bounded CI diagnostic benchmark: fixed 1 vs 2 Rust song workers, ABBA.

Synthetic public-domain test tones and official ONNX models only.
Measures complete scanner invocations including worker/model startup,
with independent sidecars. Not an NAS, adaptive-policy, or audio-quality test.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import statistics
import tempfile
import time

from verify_manifest_batch_smoke import (
    invoke, stored_embeddings, stored_features, synthetic_wav,
)


def run(binary: Path, models: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="manifest-fixed-worker-abba-") as temp:
        base = Path(temp)
        audio = base / "audio"
        audio.mkdir()
        keys = [f"synthetic-{i:02d}.wav" for i in range(8)]
        for i, key in enumerate(keys):
            synthetic_wav(audio / key, 220 + 37 * i, seconds=20)
        manifest = base / "tracks.txt"
        manifest.write_text("\n".join(keys) + "\n", encoding="utf-8")

        baseline_features = None
        baseline_embeddings = None
        durations: dict[int, list[float]] = {1: [], 2: []}
        net_durations: dict[int, list[float]] = {1: [], 2: []}
        runs = []
        for index, workers in enumerate((1, 2, 2, 1), start=1):
            sidecar = base / f"run{index}.sqlite"
            embeddings = base / f"embeddings{index}"
            embeddings.mkdir()
            started = time.perf_counter()
            summary = invoke(
                binary, models, audio, manifest, sidecar, embeddings,
                ["--workers", str(workers)],
            )
            wall_s = time.perf_counter() - started
            if summary["analyzed"] != len(keys) or summary["pending"] != len(keys):
                raise AssertionError("ABBA benchmark did not analyze the exact same cohort")
            feature_rows = stored_features(sidecar)
            embedding_rows = stored_embeddings(embeddings, keys)
            if baseline_features is None:
                baseline_features, baseline_embeddings = feature_rows, embedding_rows
            elif feature_rows != baseline_features or embedding_rows != baseline_embeddings:
                raise AssertionError("ABBA worker setting changed exact numeric features")
            diagnostic = summary.get("diagnostics") or {}
            baseline = diagnostic.get("baseline") or {}
            baseline_s = float(baseline.get("cpu_measurement_seconds") or 0.0)
            # A parallel scan deliberately sleeps ~1s to establish CPU
            # resource load before starting workers; serial does not.
            # Do not hide this time from the actual wall-clock result.
            net_wall_s = wall_s - baseline_s
            assert 0 <= baseline_s < wall_s
            durations[workers].append(wall_s)
            net_durations[workers].append(net_wall_s)
            runs.append({
                "preworker_cpu_baseline_seconds": round(baseline_s, 3),
                "wall_excluding_preworker_baseline_seconds": round(net_wall_s, 3),
                "ordinal": index,
                "workers": workers,
                "songs": summary["analyzed"],
                "wall_seconds": round(wall_s, 3),
                "scanner_seconds": round(summary["elapsed_seconds"], 3),
                "peak_active_analyses": diagnostic.get("peak_active_analyses"),
                "peak_in_flight": diagnostic.get("peak_in_flight"),
                "max_system_ram_percent": diagnostic.get("system_ram_max_percent"),
                "max_process_private_mib": diagnostic.get("process_private_bytes_max_mib"),
            })

        # This prints only aggregate diagnostics. No private content is involved.
        import json
        result = {
            "kind": "synthetic_fixed_worker_abba_diagnostic_v1",
            "cohort_songs": len(keys),
            "duration_seconds_per_song": 20,
            "run_order": [1, 2, 2, 1],
            "numeric_parity": "EXACT",
            "results": runs,
            "median_wall_seconds": {
                str(worker): round(statistics.median(times), 3)
                for worker, times in durations.items()
            },
            "median_wall_excluding_preworker_baseline_seconds": {
                str(worker): round(statistics.median(times), 3)
                for worker, times in net_durations.items()
            },
            "limitations": [
                "Runner CPU/IO resources may vary and are not guaranteed across runs",
                "Synthetic sine waves are not representative music or NAS/SMB access",
                "Startup and model loading are included in each independent invocation",
                "Parallel scans deliberately perform ~1 second pre-worker CPU baseline",
                "Excluding that observed baseline is diagnostic only, not a user-visible speedup",
                "A two-repeat ABBA diagnostic is not a confidence interval or causal speedup estimate",
                "No adaptive worker increase/decrease is studied",
            ],
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        print("PASS identical feature and song-embedding bytes across fixed ABBA runs")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.binary.resolve(), args.models_dir.resolve())
