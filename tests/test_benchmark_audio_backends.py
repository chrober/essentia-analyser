"""No binaries/models required: guard the A/B native benchmark against bias."""
import sqlite3
import json
from contextlib import closing, contextmanager
import struct
import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import benchmark_audio_backends as bench


@contextmanager
def writable_db(path):
    # sqlite3's transaction context alone does not close Windows file handles;
    # closing alone rolls back uncommitted INSERT/UPDATE transactions.
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            yield conn


class AudioBackendBenchmarkTests(unittest.TestCase):
    def test_root_mapping_accepts_relative_file_keys_on_windows(self):
        bench.validate_source_roots(Path(r"\\nas\music"), None)
        bench.validate_source_roots(None, None)
        bench.validate_source_roots(Path(r"\\nas\music"), r"Z:\legacy")
        with self.assertRaisesRegex(ValueError, "--library-root requires"):
            bench.validate_source_roots(None, r"Z:\legacy")

    def test_plan_is_paired_and_alternates_backend_order(self):
        plan = bench.experiment_plan([1, 2, 4, 6], repeats=2, seed=22)
        self.assertEqual(len(plan), 16)
        for round_index in (1, 2):
            for count in (1, 2, 4, 6):
                pair = [row[2] for row in plan
                        if row[0] == round_index and row[1] == count]
                self.assertEqual(pair, ["rust", "essentia"] if round_index == 1
                                 else ["essentia", "rust"])

    def test_score_comparison_independent_of_model_fingerprint(self):
        reference = (0.1, 0.5, 0.8) + (0.1,) * 53
        native = (0.1001, 0.5, 0.8) + (0.1,) * 53
        baseline = {("track.flac", "moodtheme"): (3, reference)}
        alternative = {("track.flac", "moodtheme"): (3, native)}
        stats = bench.compare_feature_tables(
            baseline, alternative, expected_models=("moodtheme",)
        )
        self.assertEqual(stats["patch_count_mismatches"], 0)
        self.assertEqual(stats["compared_scores"], 56)
        self.assertEqual(stats["per_head"]["moodtheme"]["tracks"], 1)
        self.assertEqual(stats["worst_score_difference"]["class_index"], 0)
        self.assertLess(stats["maximum_absolute_score_difference"], 1e-3)

    def test_comparison_detects_missing_class_and_patch_count_drift(self):
        ref = {("track", "genre"): (3, (0.1,) * 87)}
        with self.assertRaises(AssertionError):
            bench.compare_feature_tables(ref, {})
        with self.assertRaises(AssertionError):
            bench.compare_feature_tables(ref, {
                ("track", "genre"): (3, (0.2,))
            })
        result = bench.compare_feature_tables(ref, {
            ("track", "genre"): (4, (0.1,) * 87)
        })
        self.assertEqual(result["patch_count_mismatches"], 1)
        self.assertEqual(result["patch_count_mismatch_examples"][0]["head"], "genre")

    def test_per_head_numeric_drift_and_complete_head_coverage(self):
        same = (0.1,) * 87
        changed = (0.1,) * 86 + (0.12,)
        baseline = {
            ("track-a", "genre"): (2, same),
            ("track-b", "genre"): (2, same),
            ("track-a", "moodtheme"): (2, (0.2,) * 56),
            ("track-b", "moodtheme"): (2, (0.2,) * 56),
        }
        alternative = dict(baseline)
        alternative["track-b", "genre"] = (2, changed)
        stats = bench.compare_feature_tables(
            baseline, alternative, expected_models=("genre", "moodtheme")
        )
        self.assertAlmostEqual(
            stats["per_head"]["genre"]["maximum_absolute_score_difference"],
            0.02
        )
        self.assertEqual(
            stats["per_head"]["moodtheme"]["maximum_absolute_score_difference"],
            0.0
        )
        self.assertEqual(stats["worst_score_difference"]["track_file"], "track-b")
        self.assertEqual(stats["worst_score_difference"]["head"], "genre")
        self.assertEqual(stats["worst_score_difference"]["class_index"], 86)
        partial = dict(baseline)
        del partial["track-b", "moodtheme"]
        with self.assertRaisesRegex(AssertionError, "Partial model-head coverage"):
            bench.compare_feature_tables(partial, partial, ("genre", "moodtheme"))
        invalid = {("track-a", "genre"): (2, (0.2,) * 86)}
        with self.assertRaisesRegex(AssertionError, "Invalid known head dimension"):
            bench.compare_feature_tables(invalid, invalid)
        with self.assertRaisesRegex(AssertionError, "exact Bliss cohort"):
            bench.compare_feature_tables(
                baseline, alternative, ("genre", "moodtheme"),
                expected_tracks=["track-a", "track-b", "track-c"]
            )
        matched = bench.compare_feature_tables(
            baseline, alternative, ("genre", "moodtheme"),
            expected_tracks=["track-b", "track-a"]
        )
        self.assertEqual(matched["tracks_and_heads"], 4)


    def test_fingerprints_must_be_distinct_between_backends(self):
        with tempfile.TemporaryDirectory() as tmp:
            rust_db = Path(tmp) / "rust.db"
            cpp_db = Path(tmp) / "essentia.db"

            def create(path, keys, backend):
                with writable_db(path) as conn:
                    conn.execute("PRAGMA user_version=3")
                    conn.execute(
                        "CREATE TABLE feature_tracks "
                        "(track_file TEXT, model_id TEXT, model_key TEXT)"
                    )
                    conn.execute(
                        "CREATE TABLE feature_models "
                        "(model_key TEXT, embedding_model TEXT, "
                        "classification_model TEXT, models_sha256_json TEXT, "
                        "aggregation TEXT, classes_json TEXT)"
                    )
                    metadata = []
                    for head, key in keys:
                        hashes = {
                            "shared-effnet.onnx": "a" * 64,
                            f"{head}.onnx": "b" * 64,
                        }
                        if backend == "essentia":
                            hashes["essentia_cpp_worker_binary_sha256"] = "c" * 64
                            hashes[
                                "essentia_cpp_native_deployment_manifest_sha256"
                            ] = "d" * 64
                        metadata.append((
                            key, "shared-effnet.onnx", f"{head}.onnx",
                            json.dumps(hashes), "mean", '["first","second"]'
                        ))
                    conn.executemany(
                        "INSERT INTO feature_models VALUES (?,?,?,?,?,?)",
                        metadata
                    )
                    conn.executemany(
                        "INSERT INTO feature_tracks VALUES (?,?,?)",
                        [(f"track-{n}.flac", head, key)
                         for head, key in keys
                         for n in range(2)]
                    )

            create(rust_db, [("genre", "rust-genre"),
                             ("moodtheme", "rust-mood")], "rust")
            create(cpp_db, [("genre", "cpp-genre"),
                            ("moodtheme", "cpp-mood")], "essentia")
            self.assertEqual(
                bench.verify_backend_fingerprint_separation(rust_db, cpp_db),
                ["genre", "moodtheme"],
            )
            with writable_db(cpp_db) as conn:
                conn.execute(
                    "UPDATE feature_tracks SET model_key='rust-genre' "
                    "WHERE model_id='genre'"
                )
            with self.assertRaisesRegex(AssertionError, "must not share"):
                bench.verify_backend_fingerprint_separation(rust_db, cpp_db)
            with writable_db(cpp_db) as conn:
                conn.execute(
                    "UPDATE feature_tracks SET model_key='cpp-genre' "
                    "WHERE model_id='genre'"
                )
                conn.execute(
                    "UPDATE feature_models SET classes_json='[\"reordered\",\"labels\"]' "
                    "WHERE model_key='cpp-genre'"
                )
            with self.assertRaisesRegex(
                AssertionError, "Different ONNX model weights, class labels"
            ):
                bench.verify_backend_fingerprint_separation(rust_db, cpp_db)
            with writable_db(cpp_db) as conn:
                conn.execute(
                    "UPDATE feature_models SET classes_json='[\"first\",\"second\"]' "
                    "WHERE model_key='cpp-genre'"
                )
                modified = json.loads(conn.execute(
                    "SELECT models_sha256_json FROM feature_models "
                    "WHERE model_key='cpp-genre'"
                ).fetchone()[0])
                modified["genre.onnx"] = "e" * 64
                conn.execute(
                    "UPDATE feature_models SET models_sha256_json=? "
                    "WHERE model_key='cpp-genre'",
                    (json.dumps(modified),)
                )
            with self.assertRaisesRegex(
                AssertionError, "Different ONNX model weights, class labels"
            ):
                bench.verify_backend_fingerprint_separation(rust_db, cpp_db)
            # Do not accept unrecognized "metadata" keys as cache decorations.
            with writable_db(cpp_db) as conn:
                modified["genre.onnx"] = "b" * 64
                modified["unrecognized"] = "f" * 64
                conn.execute(
                    "UPDATE feature_models SET models_sha256_json=? "
                    "WHERE model_key='cpp-genre'",
                    (json.dumps(modified),)
                )
            with self.assertRaisesRegex(AssertionError, "Unexpected essentia model SHA keys"):
                bench.verify_backend_fingerprint_separation(rust_db, cpp_db)
            with writable_db(cpp_db) as conn:
                conn.execute(
                    "UPDATE feature_tracks SET model_key='extra-model' "
                    "WHERE track_file='track-0.flac' AND model_id='genre'"
                )
            with self.assertRaisesRegex(AssertionError, "Mixed model fingerprints"):
                bench.model_fingerprints_by_head(cpp_db)

    def test_fail_closed_on_incomplete_result(self):
        bench.validate_report({"analyzed": 5, "pending": 5,
                               "failures": 0, "missing_files": 0}, 5)
        with self.assertRaises(AssertionError):
            bench.validate_report({"analyzed": 4, "pending": 5,
                                   "failures": 1, "missing_files": 0}, 5)

    def test_readonly_bliss_cohort_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "cohort.db"
            with writable_db(db) as conn:
                conn.executescript("CREATE TABLE TracksV2 (File TEXT, Ignore INTEGER);")
                conn.executemany("INSERT INTO TracksV2 VALUES (?, 0)",
                                 ((f"song-{i}.flac",) for i in range(3)))
            self.assertEqual(len(bench.checked_cohort(db)), 3)
            with writable_db(db) as conn:
                conn.execute("DELETE FROM TracksV2 WHERE File <> 'song-0.flac'")
            with self.assertRaises(ValueError):
                bench.checked_cohort(db)

    def test_load_little_endian_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.db"
            with writable_db(db) as conn:
                conn.executescript(
                    "CREATE TABLE feature_tracks (track_file TEXT, model_id TEXT, "
                    "patches_analyzed INTEGER, scores_f32_le BLOB);"
                )
                conn.execute(
                    "INSERT INTO feature_tracks VALUES (?,?,?,?)",
                    ("song.mp3", "voice", 3, struct.pack("<ff", 0.25, 0.75)),
                )
            rows = bench.load_feature_rows(db)
            self.assertEqual(rows["song.mp3", "voice"], (3, (0.25, 0.75)))


if __name__ == "__main__":
    unittest.main()
