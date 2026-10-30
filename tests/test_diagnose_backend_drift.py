"""Numeric drift diagnostics must not relax parity or modify old DBs."""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import diagnose_backend_drift as diagnostic
from test_verify_existing_backend_sidecars import build_fixture


class DiagnoseBackendDriftTests(unittest.TestCase):
    def test_identical_real_song_vectors_pass_without_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            inputs = build_fixture(Path(folder))
            hashes_before = [diagnostic.digest(path) for path in inputs]
            data = diagnostic.diagnose(
                *inputs, ("genre", "moodtheme", "voice"), 0.001
            )
            self.assertEqual(data["numeric_parity_status"], "PASS")
            self.assertEqual(data["cohort_tracks"], 2)
            self.assertEqual(data["tracks_exceeding_tolerance_any_head"], 0)
            self.assertEqual(data["per_head"]["voice"]["scores"], 4)
            self.assertEqual(data["per_extension"][".flac"]["tracks"], 2)
            self.assertEqual(hashes_before, [
                diagnostic.digest(path) for path in inputs
            ])

    def test_real_score_drift_reports_outliers_without_saying_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            inputs = build_fixture(Path(folder), error=0.0038242)
            data = diagnostic.diagnose(
                *inputs, ("genre", "moodtheme", "voice"), 0.001
            )
            self.assertEqual(data["numeric_parity_status"], "FAIL")
            self.assertEqual(data["tracks_exceeding_tolerance_any_head"], 1)
            self.assertEqual(data["per_head"]["genre"]["tracks_exceeding_tolerance"], 1)
            self.assertEqual(data["per_head"]["moodtheme"]["tracks_exceeding_tolerance"], 0)
            self.assertEqual(data["per_extension"][".flac"]["tracks_exceeding_tolerance"], 1)
            self.assertEqual(data["worst_track_head_pairs"][0]["head"], "genre")
            self.assertGreater(
                data["worst_track_head_pairs"][0]["maximum_absolute_error"], 0.003
            )

    def test_patch_drift_fails_even_when_scores_match(self):
        with tempfile.TemporaryDirectory() as folder:
            inputs = build_fixture(Path(folder))
            with closing(sqlite3.connect(inputs[2])) as conn:
                with conn:
                    conn.execute(
                        "UPDATE feature_tracks SET patches_analyzed=4 "
                        "WHERE model_id='voice' AND track_file='track-1.flac'"
                    )
            data = diagnostic.diagnose(
                *inputs, ("genre", "moodtheme", "voice"), 0.001
            )
            self.assertEqual(data["numeric_parity_status"], "FAIL")
            self.assertEqual(data["patch_mismatch_count"], 1)
            self.assertEqual(data["tracks_exceeding_tolerance_any_head"], 0)

    def test_onnx_identity_guard_is_still_enforced(self):
        with tempfile.TemporaryDirectory() as folder:
            inputs = build_fixture(Path(folder), change_model=True)
            with self.assertRaisesRegex(AssertionError, "Different ONNX model"):
                diagnostic.diagnose(
                    *inputs, ("genre", "moodtheme", "voice"), 0.001
                )


if __name__ == "__main__":
    unittest.main()
