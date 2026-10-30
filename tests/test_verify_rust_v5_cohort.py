"""Fast strict v5 cohort acceptance tests; original SQLite artifacts read-only."""
from contextlib import closing
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_rust_v5_cohort as gate


def make_cohort(root, *, v5_diff=2e-6, wrong_audio=False, wrong_version=False):
    cohort = root / "sample.db"
    songs = [f"artist/song-{i:02}.mp3" for i in range(2)]
    with closing(sqlite3.connect(cohort)) as db:
        with db:
            db.execute("CREATE TABLE TracksV2 (File TEXT, Ignore INTEGER)")
            db.executemany("INSERT INTO TracksV2 VALUES (?,0)", [(s,) for s in songs])

    paths = {}
    for backend in ("v4", "cpp", "v5"):
        filename = root / f"{backend}.db"
        paths[backend] = filename
        with closing(sqlite3.connect(filename)) as db:
            with db:
                db.execute("PRAGMA user_version=3")
                db.execute(
                    "CREATE TABLE feature_models ("
                    "model_key TEXT PRIMARY KEY, embedding_model TEXT, "
                    "classification_model TEXT, models_sha256_json TEXT, "
                    "preprocessing_version TEXT, aggregation TEXT, classes_json TEXT)"
                )
                db.execute(
                    "CREATE TABLE feature_tracks ("
                    "track_file TEXT, model_id TEXT, audio_sha256 TEXT, "
                    "model_key TEXT, patches_analyzed INTEGER, scores_f32_le BLOB)"
                )
                versions = {
                    "v4": gate.OLD_RUST_PREPROCESSING,
                    "cpp": gate.NATIVE_CPP_PREPROCESSING,
                    "v5": gate.FIXED_RUST_PREPROCESSING,
                }
                version = versions[backend]
                if wrong_version and backend == "v5":
                    version = versions["v4"]
                for head, dimensions in (("genre", 87), ("moodtheme", 56),
                                         ("voice", 2)):
                    key = f"{backend}-{head}"
                    hashes = {"encoder.onnx": "b" * 64, f"{head}.onnx": "c" * 64}
                    if backend == "cpp":
                        hashes["essentia_cpp_worker_binary_sha256"] = "d" * 64
                    db.execute(
                        "INSERT INTO feature_models VALUES (?,?,?,?,?,?,?)",
                        (key, "encoder.onnx", f"{head}.onnx", json.dumps(hashes),
                         version, "arithmetic-mean",
                         json.dumps([f"class-{i}" for i in range(dimensions)])),
                    )
                    for song in songs:
                        drift = 0 if backend == "cpp" else (
                            0.003 if backend == "v4" else v5_diff
                        )
                        scores = [0.2 + drift] + [0.2] * (dimensions - 1)
                        sha = ("f" if wrong_audio and backend == "v5"
                               and song == songs[0] else "a") * 64
                        db.execute(
                            "INSERT INTO feature_tracks VALUES (?,?,?,?,?,?)",
                            (song, head, sha, key, 837,
                             struct.pack(f"<{dimensions}f", *scores)),
                        )
    return cohort, paths["v4"], paths["cpp"], paths["v5"]


class NewRustCohortGateTests(unittest.TestCase):
    def test_all_three_heads_pass_after_true_v5_change(self):
        with tempfile.TemporaryDirectory() as temp:
            cohort, old, cpp, new = make_cohort(Path(temp))
            before = tuple(gate.digest(path) for path in (cohort, old, cpp, new))
            report = gate.compare_versions(cohort, old, cpp, new, 0.001)
            self.assertEqual(report["numeric_parity_status"], "PASS")
            self.assertEqual(report["score_components"], 290)
            self.assertEqual(report["new_rust_v5"]["patch_count_mismatches"], 0)
            self.assertGreater(
                report["per_head_improvement"]["genre"]["old_max_abs_error"],
                0.002,
            )
            self.assertLess(
                report["per_head_improvement"]["voice"]["new_max_abs_error"],
                1e-5,
            )
            self.assertEqual(before, tuple(
                gate.digest(path) for path in (cohort, old, cpp, new)
            ))

    def test_parallel_four_workers_execute_exactly_one_new_rust_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cohort, old, cpp, v5_fixture = make_cohort(root)
            output = root / "new-parallel-sidecar"
            scanner = root / "v5-scanner.exe"
            scanner.write_bytes(b"synthetic scanner not invoked in this test")
            args = SimpleNamespace(
                cohort_db=cohort, old_rust_db=old, essentia_db=cpp,
                analyzer=scanner, models_dir=root, source_root=root,
                output_dir=output, workers=4, expected_songs=2,
                score_max_tolerance=0.001,
            )
            original_hashes = tuple(gate.digest(path) for path in (
                cohort, old, cpp, v5_fixture
            ))

            def simulate_scan(scan_args, round_index, workers, backend, expected):
                self.assertEqual((round_index, workers, backend, expected),
                                 (1, 4, "rust", 2))
                self.assertEqual(scan_args.models, "genre,moodtheme,voice")
                self.assertEqual(scan_args.output_dir, output)
                target = output / "round-01-workers-04-rust.db"
                shutil.copyfile(v5_fixture, target)
                return ({"sqlite": target.name, "seconds": 12.5}, {})

            with patch.object(gate, "run_scan", side_effect=simulate_scan) as mock:
                report = gate.run(args)
            mock.assert_called_once()
            self.assertEqual(report["numeric_parity_status"], "PASS")
            self.assertEqual(report["worker_count"], 4)
            self.assertEqual(report["onnx_threads_per_worker"], 1)
            self.assertIn("workers_4", report["scope"])
            self.assertEqual(report["rust_v5_scan"]["seconds"], 12.5)
            self.assertTrue((output / "parity-report-private.json").is_file())
            self.assertEqual(original_hashes, tuple(gate.digest(path) for path in (
                cohort, old, cpp, v5_fixture
            )))

    def test_rejects_unsupported_worker_counts_before_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cohort, old, cpp, _ = make_cohort(root)
            scanner = root / "v5-scanner.exe"
            scanner.write_bytes(b"synthetic scanner")
            args = SimpleNamespace(
                cohort_db=cohort, old_rust_db=old, essentia_db=cpp,
                analyzer=scanner, models_dir=root, source_root=root,
                output_dir=root / "should-not-be-created",
                workers=3, expected_songs=2,
                score_max_tolerance=0.001,
            )
            with patch.object(gate, "run_scan") as mock:
                with self.assertRaisesRegex(ValueError, "fixed Rust --workers"):
                    gate.run(args)
            mock.assert_not_called()
            self.assertFalse(args.output_dir.exists())

    def test_out_of_tolerance_remains_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            cohort, old, cpp, new = make_cohort(Path(temp), v5_diff=0.002)
            result = gate.compare_versions(cohort, old, cpp, new, 0.001)
            self.assertEqual(result["numeric_parity_status"], "FAIL")

    def test_different_audio_and_stale_version_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            cohort, old, cpp, new = make_cohort(Path(temp), wrong_audio=True)
            with self.assertRaisesRegex(AssertionError, "audio SHA256 differs"):
                gate.compare_versions(cohort, old, cpp, new, 0.001)
        with tempfile.TemporaryDirectory() as temp:
            cohort, old, cpp, new = make_cohort(Path(temp), wrong_version=True)
            with self.assertRaisesRegex(AssertionError, "Incorrect or stale preprocessing"):
                gate.compare_versions(cohort, old, cpp, new, 0.001)

    def test_wrong_old_cache_key_or_mixed_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            cohort, old, cpp, new = make_cohort(Path(temp))
            with closing(sqlite3.connect(new)) as db:
                with db:
                    db.execute(
                        "UPDATE feature_models SET model_key='v4-genre' "
                        "WHERE model_key='v5-genre'"
                    )
                    db.execute(
                        "UPDATE feature_tracks SET model_key='v4-genre' "
                        "WHERE model_id='genre'"
                    )
            with self.assertRaisesRegex(AssertionError, "aliases historical v4"):
                gate.compare_versions(cohort, old, cpp, new, 0.001)

    def test_exact_existing_cohort_is_required(self):
        with tempfile.TemporaryDirectory() as temp:
            cohort, old, cpp, new = make_cohort(Path(temp))
            with closing(sqlite3.connect(cohort)) as db:
                with db:
                    db.execute("UPDATE TracksV2 SET File='another.mp3' "
                               "WHERE File='artist/song-00.mp3'")
            with self.assertRaisesRegex(AssertionError, "Expected exactly"):
                gate.compare_versions(cohort, old, cpp, new, 0.001)


if __name__ == "__main__":
    unittest.main()
