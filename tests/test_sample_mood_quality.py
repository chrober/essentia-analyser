"""Tests for read-only quality sampling without accessing a real music library."""
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "sample_mood_quality.py"
spec = importlib.util.spec_from_file_location("sample_mood_quality", MODULE)
sample = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sample)


class SamplingTests(unittest.TestCase):
    def test_normalizes_relative_bliss_paths(self):
        self.assertEqual(sample.normalize_track_key("Band/Album/Song.mp3"),
                         ["Band", "Album", "Song.mp3"])
        self.assertEqual(sample.normalize_track_key(r"Band\Album\Song.flac"),
                         ["Band", "Album", "Song.flac"])

    def test_rejects_unsafe_paths(self):
        for key in ("../secret", "/absolute/song", r"C:\Music\track.flac",
                    r"\\server\share\song.mp3", "a//b"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    sample.normalize_track_key(key)


    def test_dual_model_output_decoding(self):
        classifiers = {"moodtheme": ["heavy"], "genre": ["metal"]}
        payload = {"classifications": {
            "moodtheme": {"scores": {"heavy": 0.4}},
            "genre": {"scores": {"metal": 0.7}},
        }}
        self.assertEqual(sample.collect_scores(payload, classifiers, False), {
            "moodtheme": {"heavy": 0.4}, "genre": {"metal": 0.7}
        })
        with self.assertRaises(ValueError):
            sample.collect_scores(payload, {"genre": ["pop"]}, False)

    def test_parallel_sampling_worker_policy(self):
        self.assertEqual(sample.resolve_workers("1"), 1)
        self.assertEqual(sample.resolve_workers("3"), 3)
        self.assertGreaterEqual(sample.resolve_workers("auto"), 1)
        self.assertLessEqual(sample.resolve_workers("auto"), 4)
        for invalid in ("0", "17", "-1", "many"):
            with self.assertRaises(ValueError):
                sample.resolve_workers(invalid)

    def test_three_model_score_extraction_keeps_all_labels(self):
        classifiers = {
            "moodtheme": ["heavy"], "genre": ["metal"],
            "voice": ["voice", "instrumental"]
        }
        payload = {"classifications": {
            "moodtheme": {"scores": {"heavy": 0.5}},
            "genre": {"scores": {"metal": 0.8}},
            "voice": {"scores": {"voice": 0.75, "instrumental": 0.25}}
        }}
        scores = sample.collect_scores(payload, classifiers, False)
        self.assertEqual(scores["voice"]["voice"], 0.75)
        self.assertEqual(scores["voice"]["instrumental"], 0.25)
        self.assertEqual(len(scores), 3)

    def test_reads_bliss_copy_without_writing_or_including_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "bliss.db"
            with sqlite3.connect(db_path) as db:
                db.execute("CREATE TABLE TracksV2 (File TEXT NOT NULL, Ignore INTEGER)")
                db.executemany(
                    "INSERT INTO TracksV2 (File, Ignore) VALUES (?, ?)",
                    [(f"Artist/{n:03d}.flac", None) for n in range(100)]
                    + [("Artist/ignored.flac", 1)],
                )
            before = db_path.read_bytes()
            first, total = sample.select_keys(db_path, 12, 42)
            second, total_second = sample.select_keys(db_path, 12, 42)
            self.assertEqual(total, 100)
            self.assertEqual(total_second, 100)
            self.assertEqual(len(first), 12)
            self.assertEqual(first, second)
            self.assertNotIn("Artist/ignored.flac", first)
            self.assertEqual(before, db_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
