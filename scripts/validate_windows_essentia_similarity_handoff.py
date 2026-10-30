#!/usr/bin/env python3
"""End-to-end Windows scanner + original Essentia -> schema-v3 -> PR16 evaluator.

Use copyright-free fixture audio only. PR16's evaluator is pinned and read
as an external input, never changed or copied into the source repository.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys

FILES = ("mono-16k.wav", "stereo-44100.wav",
         "stereo-44100.flac", "stereo-44100.mp3")
DIMENSIONS = {"genre": 87, "moodtheme": 56, "voice": 2}


def run_json(command, timeout=1200):
    completed = subprocess.run([str(x) for x in command], capture_output=True,
                               text=True, errors="replace", timeout=timeout)
    if completed.returncode:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {command[:2]}\n"
            f"stdout: {completed.stdout[-1500:]}\n"
            f"stderr: {completed.stderr[-3000:]}"
        )
    return json.loads(completed.stdout)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_sqlite_contract(database):
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        rows = db.execute(
            "SELECT track_file,model_id,model_key,scores_f32_le,patches_analyzed "
            "FROM feature_tracks"
        ).fetchall()
        assert len(rows) == len(FILES) * len(DIMENSIONS), len(rows)
        seen = set()
        keys = {head: set() for head in DIMENSIONS}
        for track, head, key, blob, patches in rows:
            assert track in FILES and head in DIMENSIONS
            assert (track, head) not in seen, (track, head)
            seen.add((track, head))
            keys[head].add(key)
            assert len(blob) == DIMENSIONS[head] * 4 and patches > 0
            values = struct.unpack("<" + "f" * DIMENSIONS[head], blob)
            assert all(math.isfinite(x) and 0 <= x <= 1 for x in values)
            if head == "voice":
                assert abs(sum(values) - 1.0) < 1e-3
        assert db.execute("SELECT count(*) FROM feature_track_state").fetchone()[0] == len(rows)
        for head, model_keys in keys.items():
            assert len(model_keys) == 1, (head, model_keys)
            info = db.execute(
                "SELECT preprocessing_version,aggregation,classes_json,"
                "validated_against_essentia,models_sha256_json FROM feature_models "
                "WHERE model_key=?", (next(iter(model_keys)),)
            ).fetchone()
            assert info is not None
            preprocessing, aggregation, labels, validated, hashes = info
            assert preprocessing.startswith("experimental-essentia-cpp-dsp"), preprocessing
            assert aggregation == ("arithmetic_mean_of_per_patch_softmax_scores" if head == "voice"
                                   else "arithmetic_mean_of_per_patch_sigmoid_scores")
            assert len(json.loads(labels)) == DIMENSIONS[head]
            assert validated == 0
            provenance = json.loads(hashes)
            assert len(provenance["essentia_cpp_worker_binary_sha256"]) == 64
            assert len(provenance["essentia_cpp_native_deployment_manifest_sha256"]) == 64


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("scanner", "worker", "models-dir", "fixtures-dir", "evaluator", "work-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    scanner = args.scanner.resolve()
    worker = args.worker.resolve()
    models = args.models_dir.resolve()
    fixtures = args.fixtures_dir.resolve()
    evaluator = args.evaluator.resolve()
    work = args.work_dir.resolve()
    assert all(p.is_file() for p in (scanner, worker, evaluator))
    assert all((fixtures / name).is_file() for name in FILES)
    work.mkdir(parents=True, exist_ok=True)
    bliss, sidecar = work / "fixture-bliss.db", work / "feature-sidecar.db"
    assert not bliss.exists() and not sidecar.exists(), "Must use fresh fixture databases"
    with sqlite3.connect(bliss) as db:
        db.execute("CREATE TABLE TracksV2(File TEXT PRIMARY KEY, Ignore INTEGER DEFAULT 0)")
        db.executemany("INSERT INTO TracksV2(File) VALUES(?)", [(name,) for name in FILES])
    bliss_sha = digest(bliss)
    scan = [
        scanner, "scan-features", "--bliss-db", bliss, "--db", sidecar,
        "--models-dir", models, "--models", "genre,moodtheme,voice",
        "--source-root", fixtures, "--audio-backend", "essentia",
        "--essentia-worker", worker, "--workers", "2", "--threads", "1",
        "--max-new", "4", "--max-errors", "1", "--json",
    ]
    first = run_json(scan)
    assert (first["analyzed"], first["failures"], first["missing_files"]) == (4, 0, 0), first
    assert first["model_sessions_initialized"], first
    assert_sqlite_contract(sidecar)
    repeat = run_json(scan)
    assert (repeat["analyzed"], repeat["up_to_date"], repeat["failures"]) == (0, 4, 0), repeat
    assert digest(bliss) == bliss_sha, "Scanner modified read-only Bliss input"
    single = run_json([
        scanner, "analyze-features", fixtures / FILES[0], "--models-dir", models,
        "--models", "genre,moodtheme,voice", "--audio-backend", "essentia",
        "--essentia-worker", worker, "--threads", "1", "--json",
    ])
    assert all(len(single["classifications"][head]["scores"]) == dimensions
               for head, dimensions in DIMENSIONS.items())
    sidecar_sha = digest(sidecar)
    similarity = run_json([
        sys.executable, evaluator, "--db", sidecar, "--include-experimental",
        "--limit", "4", "--pairs", "12", "--seed", "20261020", "--examples", "2",
    ])
    assert similarity["schema"] == "similarity-metric-evaluation-v1"
    assert similarity["source"]["feature_schema"] == 3
    assert similarity["source"]["read_only"]
    assert similarity["sampling"]["sample_size"] == 4, similarity["sampling"]
    assert set(similarity["models"]) == {"genre", "moodtheme"}
    assert digest(sidecar) == sidecar_sha, "PR16 evaluator modified v3 sidecar"
    assert digest(bliss) == bliss_sha, "PR16 evaluator modified Bliss fixture"
    print(json.dumps({
        "result": "PASS", "platform": "Windows x64", "backend": "original Essentia C++",
        "scan_tracks": first["analyzed"], "repeat_up_to_date": repeat["up_to_date"],
        "schema": 3, "heads": DIMENSIONS, "pr16_similarity_tracks": 4,
        "note": "Synthetic signals only; not musical-similarity quality validation",
    }, indent=2))


if __name__ == "__main__":
    main()
