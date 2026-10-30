"""Read-only parity regression using synthetic schema-v3 feature sidecars."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_existing_backend_sidecars as audit


def build_fixture(root, error=0.0, change_model=False):
    cohort = root / "cohort.db"
    with closing(sqlite3.connect(cohort)) as conn:
        with conn:
            conn.execute("CREATE TABLE TracksV2 (File TEXT, Ignore INTEGER)")
            conn.executemany("INSERT INTO TracksV2 VALUES (?, 0)",
                             [(f"track-{n}.flac",) for n in range(2)])
    files = []
    for backend in ("rust", "essentia"):
        db = root / f"{backend}.db"
        files.append(db)
        with closing(sqlite3.connect(db)) as conn:
            with conn:
                conn.execute("PRAGMA user_version=3")
                conn.execute("CREATE TABLE feature_models ("
                             "model_key TEXT, embedding_model TEXT, "
                             "classification_model TEXT, models_sha256_json TEXT, "
                             "aggregation TEXT, classes_json TEXT)")
                conn.execute("CREATE TABLE feature_tracks ("
                             "track_file TEXT, model_id TEXT, model_key TEXT, "
                             "patches_analyzed INTEGER, scores_f32_le BLOB)")
                for head, dimension in (("genre", 87), ("moodtheme", 56),
                                        ("voice", 2)):
                    key = f"{backend}-{head}"
                    hashes = {
                        "encoder.onnx": "a" * 64,
                        f"{head}.onnx": "b" * 64,
                    }
                    if backend == "essentia":
                        hashes["essentia_cpp_worker_binary_sha256"] = "c" * 64
                        hashes[
                            "essentia_cpp_native_deployment_manifest_sha256"
                        ] = "d" * 64
                        if change_model and head == "genre":
                            hashes[f"{head}.onnx"] = "e" * 64
                    conn.execute(
                        "INSERT INTO feature_models VALUES (?,?,?,?,?,?)",
                        (key, "encoder.onnx", f"{head}.onnx",
                         json.dumps(hashes), "mean",
                         json.dumps([f"class-{i}" for i in range(dimension)])),
                    )
                    for n in range(2):
                        values = [0.25] * dimension
                        if backend == "essentia" and head == "genre" and n == 1:
                            values[0] += error
                        conn.execute(
                            "INSERT INTO feature_tracks VALUES (?,?,?,?,?)",
                            (f"track-{n}.flac", head, key, 3,
                             struct.pack(f"<{dimension}f", *values)),
                        )
    return cohort, files[0], files[1]


class ExistingAudioSidecarAuditTests(unittest.TestCase):
    def test_intentional_worker_deployment_hashes_do_not_implicate_onnx(self):
        with tempfile.TemporaryDirectory() as tmp:
            trio = build_fixture(Path(tmp))
            before = tuple(audit.digest(x) for x in trio)
            report = audit.verify(*trio, ("genre", "moodtheme", "voice"), 1e-3)
            after = tuple(audit.digest(x) for x in trio)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["song_count"], 2)
            self.assertEqual(report["numerical_parity"]["compared_scores"], 290)
            self.assertEqual(before, after)

    def test_numeric_drift_is_detected_without_modifying_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            trio = build_fixture(Path(tmp), error=0.01)
            with self.assertRaisesRegex(AssertionError, "Model-score parity failed"):
                audit.verify(*trio, ("genre", "moodtheme", "voice"), 1e-3)

    def test_real_onnx_hash_change_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            trio = build_fixture(Path(tmp), change_model=True)
            with self.assertRaisesRegex(AssertionError, "Different ONNX model weights"):
                audit.verify(*trio, ("genre", "moodtheme", "voice"), 1e-3)

    def test_wrong_cohort_and_missing_head_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            trio = build_fixture(Path(tmp))
            with self.assertRaisesRegex(AssertionError, "Some tracks lack requested model heads"):
                audit.verify(*trio, ("genre", "moodtheme"), 1e-3)
            with closing(sqlite3.connect(trio[0])) as conn:
                with conn:
                    conn.execute("UPDATE TracksV2 SET File='other.flac' "
                                 "WHERE File='track-1.flac'")
            with self.assertRaisesRegex(AssertionError, "exact Bliss cohort"):
                audit.verify(*trio, ("genre", "moodtheme", "voice"), 1e-3)


if __name__ == "__main__":
    unittest.main()
