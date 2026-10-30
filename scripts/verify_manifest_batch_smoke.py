#!/usr/bin/env python3
"""CI-only integration: compare serial/fixed real ONNX synthetic-audio scans.

No local libraries, track metadata, private audio, or user feature vectors are read.
The only inputs are a verified analyzer binary and public ONNX model directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import struct
import subprocess
import tempfile
import wave


def synthetic_wav(path: Path, frequency: int, seconds: int = 4) -> None:
    """Use deterministic signed 16-bit mono PCM, four seconds at 16 kHz."""
    rate = 16000
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        for offset in range(0, rate * seconds, 4000):
            frames = [
                round(10000 * math.sin(2 * math.pi * frequency * sample / rate))
                for sample in range(offset, offset + 4000)
            ]
            file.writeframesraw(struct.pack("<" + "h" * len(frames), *frames))


def invoke(binary: Path, model_root: Path, source: Path, manifest: Path,
           sidecar: Path, exports: Path, worker_args: list[str]) -> dict:
    command = [
        str(binary), "scan-features", "--tracks-file", str(manifest),
        "--source-root", str(source), "--db", str(sidecar),
        "--embedding-dir", str(exports), "--models-dir", str(model_root),
        "--models", "moodtheme", "--threads", "1", "--max-new", "20",
        "--max-errors", "3", "--json", *worker_args,
    ]
    result = subprocess.run(command, check=False, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise AssertionError(
            f"scan-features failed, exit={result.returncode}: "
            + result.stderr[-1200:]
        )
    output = json.loads(result.stdout)
    if output["failures"] != 0 or output["missing_files"] != 0:
        raise AssertionError(f"scan had missing or failed synthetic songs: {output}")
    return output


def stored_features(sidecar: Path) -> dict[str, tuple]:
    with sqlite3.connect(f"file:{sidecar.as_posix()}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            """SELECT track_file, model_id, model_key, audio_sha256,
                      patches_analyzed, scores_f32_le
               FROM feature_tracks ORDER BY track_file, model_id"""
        ).fetchall()
    return {row[0]: tuple(row[1:]) for row in rows}


def stored_embeddings(folder: Path, keys: list[str]) -> dict[str, dict]:
    output: dict[str, dict] = {}
    for key in keys:
        target = folder / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert payload["kind"] == "discogs_effnet_song_embedding"
        assert payload["track_file"] == key
        assert payload["dimension"] == 1280
        assert payload["pooling_version"] == "patch_f64_arithmetic_mean_v1"
        assert payload["normalization_version"] == "song_f64_l2_then_cast_f32_v1"
        assert payload["preprocessing_version"].startswith("experimental")
        assert len(payload["vector_f32"]) == 1280
        assert payload["patches_analyzed"] > 0
        vector = payload["vector_f32"]
        assert all(isinstance(x, float) and math.isfinite(x) for x in vector)
        assert abs(sum(value * value for value in vector) ** .5 - 1.0) < 1e-5
        fp_contract = [
            1, payload["encoder_model"], payload["encoder_sha256"],
            payload["preprocessing_version"], payload["pooling_version"],
            payload["normalization_version"], 1280
        ]
        digest = hashlib.sha256(json.dumps(
            fp_contract, ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest()
        assert payload["representation_fingerprint"] == digest
        assert len(payload["audio_sha256"]) == 64
        output[key] = payload
    return output


def run(binary: Path, models: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="synthetic-manifest-batch-") as temp:
        root = Path(temp)
        music = root / "audio"
        music.mkdir()
        keys = ["tone-220.wav", "tone-330.wav", "tone-440.wav"]
        for name, frequency in zip(keys, [220, 330, 440]):
            synthetic_wav(music / name, frequency)
        manifest = root / "tracks.txt"
        manifest.write_text("\n".join(keys) + "\n", encoding="utf-8")

        settings = {
            "sequential": ["--workers", "1"],
            "fixed2": ["--workers", "2"],
            "fixed2_repeat": ["--workers", "2"],
        }
        results: dict[str, tuple] = {}
        for name, workers in settings.items():
            sidecar = root / f"{name}.sqlite"
            export = root / f"{name}-embeddings"
            export.mkdir()
            report = invoke(binary, models, music, manifest, sidecar, export, workers)
            assert report["analyzed"] == len(keys)
            assert report["pending"] == len(keys)
            results[name] = (
                stored_features(sidecar),
                stored_embeddings(export, keys),
                report,
            )
            print(f"PASS {name}: completed={report['analyzed']} "
                  f"elapsed_seconds={report['elapsed_seconds']:.3f}")

        reference_rows, reference_vectors, _ = results["sequential"]
        assert len(reference_rows) == len(keys)
        for name, (rows, vectors, _report) in results.items():
            # Real ONNX inference on each actual WAV, one shared model. Neither
            # the workers nor a second fixed run can change the
            # numeric feature blob or pooled JSON song representation.
            assert rows == reference_rows, f"Changed feature bytes: {name}"
            assert vectors == reference_vectors, f"Changed embedding values: {name}"
        print("PASS exact fixed-only feature-blob and pooled-embedding parity")

        sidecar, folder = root / "fixed2.sqlite", root / "fixed2-embeddings"
        unchanged = invoke(binary, models, music, manifest, sidecar, folder,
                           settings["fixed2"])
        assert unchanged["analyzed"] == 0
        assert unchanged["up_to_date"] == len(keys)
        print("PASS complete resume skips all analyzed tracks")

        # One missing JSON must trigger exactly one reanalysis and restore
        # the same representation with no change to the other songs.
        target = folder / (hashlib.sha256(keys[0].encode()).hexdigest() + ".json")
        original = target.read_bytes()
        target.unlink()
        partial = invoke(binary, models, music, manifest, sidecar, folder,
                         settings["fixed2"])
        assert partial["analyzed"] == 1
        assert partial["up_to_date"] == len(keys) - 1
        assert stored_features(sidecar) == reference_rows
        assert stored_embeddings(folder, keys) == reference_vectors
        assert target.read_bytes() == original
        print("PASS missing-embedding resume recreates exactly one identical JSON")

        # An existing corrupted output must fail closed; no implicit overwrite.
        target.write_text("{corrupt", encoding="utf-8")
        failed = subprocess.run([
            str(binary), "scan-features", "--tracks-file", str(manifest),
            "--source-root", str(music), "--db", str(sidecar),
            "--embedding-dir", str(folder), "--models-dir", str(models),
            "--models", "moodtheme", "--workers", "2", "--threads", "1",
            "--json",
        ], capture_output=True, text=True, check=False)
        assert failed.returncode != 0
        assert target.read_text(encoding="utf-8") == "{corrupt"
        print("PASS corrupt existing embedding fails closed, does not overwrite")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.binary.resolve(), args.models_dir.resolve())
