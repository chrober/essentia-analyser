"""Read-only boundaries and report math for MP3 vs lossless WAV control."""
import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import diagnose_mp3_wav_control as control


class Mp3WavControlTests(unittest.TestCase):
    def test_private_key_must_be_strict_relative_file(self):
        root = Path("C:/music")
        self.assertEqual(
            control.safe_source(root, "Artist/Album/song.mp3"),
            root / "Artist" / "Album" / "song.mp3"
        )
        for key in (
            "/absolute.mp3", "../outside.mp3", "a/../outside.mp3",
            "C:/absolute.mp3", "//remote/share/file.mp3",
            "foo/./song.mp3", "foo:\\malicious.mp3", "",
        ):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    control.safe_source(root, key)

    def test_wav_comparison_agreement_and_small_drift(self):
        baseline = {
            "schema_version": 3,
            "patches_analyzed": 42,
            "classifications": {
                "genre": {"scores": {"jazz": 0.2, "rock": 0.5}},
                "voice": {"scores": {"voice": 0.7, "instrumental": 0.3}},
            }
        }
        other = {
            "schema_version": 3,
            "patches_analyzed": 42,
            "classifications": {
                "genre": {"scores": {"jazz": 0.2001, "rock": 0.5}},
                "voice": {"scores": {"voice": 0.7, "instrumental": 0.3}},
            }
        }
        stats = control.head_differences(baseline, other)
        self.assertAlmostEqual(
            stats["genre"]["maximum_absolute_score_difference"], 0.0001
        )
        self.assertEqual(stats["voice"]["maximum_absolute_score_difference"], 0)
        self.assertEqual(stats["genre"]["classes"], 2)

    def test_wav_control_rejects_non_equivalent_shapes(self):
        reference = {
            "patches_analyzed": 10,
            "classifications": {"genre": {"scores": {"jazz": 0.2}}},
        }
        variant = {
            "patches_analyzed": 11,
            "classifications": {"genre": {"scores": {"jazz": 0.2}}},
        }
        with self.assertRaisesRegex(AssertionError, "patch counts disagree"):
            control.head_differences(reference, variant)
        variant["patches_analyzed"] = 10
        variant["classifications"]["genre"]["scores"] = {"rock": 0.2}
        with self.assertRaisesRegex(AssertionError, "Different class identities"):
            control.head_differences(reference, variant)
        variant["classifications"] = {}
        with self.assertRaisesRegex(AssertionError, "Different or missing model heads"):
            control.head_differences(reference, variant)


if __name__ == "__main__":
    unittest.main()
