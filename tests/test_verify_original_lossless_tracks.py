"""Native FLAC/WAV two-track gate: independent real file sources, no NAS/ONNX in tests."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_original_lossless_tracks as gate
from test_verify_resampler_fix_on_existing_wav import reports, AUDIO_SHA


def synthetic_cases(drift=1e-6):
    _old, reference_cpp, reference_v5 = reports(new_difference=1e-6)
    reference = {"essentia": reference_cpp, "rust": reference_v5}
    cases, selected = {}, {}
    for fmt, sha in ((".wav", "1" * 64), (".flac", "2" * 64)):
        cpp = deepcopy(reference_cpp)
        rust = deepcopy(reference_v5)
        cpp["audio_sha256"] = rust["audio_sha256"] = sha
        for head in gate.REQUIRED_HEADS:
            rust["classifications"][head]["scores"]["class-0"] = (
                cpp["classifications"][head]["scores"]["class-0"] + drift
            )
        cases[fmt] = {
            "source_sha256": sha, "reference": reference,
            "rust": rust, "essentia": cpp,
        }
        selected[fmt] = (
            f"Artist/Album/track{fmt}", Path(f"track{fmt}"),
            {"sample_rate": 48000 if fmt == ".flac" else 44100,
             "channels": 2, "duration_seconds": 85.0},
        )
    return cases, selected


class NaturalLosslessTracksTests(unittest.TestCase):
    def test_small_real_original_track_gate_pass(self):
        results, selected = synthetic_cases()
        summary = gate.compare_cases(results, selected, 0.001)
        self.assertEqual(summary["status"], "PASS")
        self.assertLess(summary["two_original_tracks"]["flac"]["max_score_difference"], 1e-5)
        self.assertEqual(summary["two_original_tracks"]["wav"]["patches"], 837)
        self.assertEqual(summary["two_original_tracks"]["flac"]["sample_rate"], 48000)

    def test_score_tolerance_cannot_be_relaxed(self):
        cases, selected = synthetic_cases(drift=0.002)
        summary = gate.compare_cases(cases, selected, 0.001)
        self.assertEqual(summary["status"], "FAIL")
        self.assertEqual(summary["two_original_tracks"]["flac"]["status"], "FAIL")

    def test_original_worker_and_official_models_fingerprinted(self):
        for field in ("worker", "onnx", "labels", "patches", "wrong_backend"):
            cases, selected = synthetic_cases()
            target = cases[".flac"]
            if field == "worker":
                target["essentia"]["classifications"]["voice"]["models_sha256"]["essentia_cpp_worker_binary_sha256"] = "e"*64
            elif field == "onnx":
                target["rust"]["classifications"]["voice"]["models_sha256"]["voice.onnx"] = "e"*64
            elif field == "labels":
                d = target["essentia"]["classifications"]["genre"]["scores"]
                d["extra"] = d.pop("class-1")
            elif field == "patches":
                target["rust"]["patches_analyzed"] = 836
            else:
                target["essentia"]["preprocessing_version"] = gate.FIXED_RUST_PREPROCESSING
            with self.subTest(field=field), self.assertRaises(AssertionError):
                gate.compare_cases(cases, selected, 0.001)

    def test_discovery_bounded_and_only_unmodified_lossless(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Artist1").mkdir()
            (root / "Artist2").mkdir()
            (root / "Artist1" / "song.flac").write_bytes(b"x")
            (root / "Artist1" / "song.mp3").write_bytes(b"x")
            (root / "Artist2" / "song.wav").write_bytes(b"x")
            (root / "Artist2" / "song.flac").write_bytes(b"x")
            first = list(gate.candidate_keys(root, max_entries=50, max_depth=2))
            self.assertIn("Artist1/song.flac", first)
            self.assertIn("Artist2/song.wav", first)
            self.assertNotIn("Artist1/song.mp3", first)
            self.assertLessEqual(len(list(gate.candidate_keys(
                root, max_entries=1, max_depth=2
            ))), 1)

    def test_selection_requires_both_formats_and_prevents_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "test.flac").write_bytes(b"x" * 10240)
            (root / "test.wav").write_bytes(b"x" * 10240)
            args = SimpleNamespace(
                source_root=root, track=["test.flac", "test.wav"],
                max_entries=100, max_depth=4, min_seconds=30,
                max_seconds=420, max_file_mib=150
            )
            fake = {
                "sample_rate": 44100, "channels": 2, "duration_seconds": 90,
            }
            with patch.object(gate, "probe", return_value=fake):
                selected = gate.select_sources(args)
            self.assertEqual(set(selected), {".flac", ".wav"})
            args.track = ["../outside.flac", "test.wav"]
            with patch.object(gate, "probe", return_value=fake):
                with self.assertRaisesRegex(ValueError, "traversal"):
                    gate.select_sources(args)
            args.track = ["test.flac", "test.flac"]
            with patch.object(gate, "probe", return_value=fake):
                with self.assertRaisesRegex(ValueError, "one eligible original"):
                    gate.select_sources(args)

    def test_explicit_flac_preflight_reports_exact_failed_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "sample.flac").write_bytes(b"x" * 4096)
            (root / "sample.wav").write_bytes(b"x" * 4096)
            args = SimpleNamespace(
                source_root=root, track=["sample.flac", "sample.wav"],
                max_entries=100, max_depth=4, min_seconds=30,
                max_seconds=420, max_file_mib=150,
            )
            metadata = {
                "sample_rate": 48000, "channels": 2,
                "duration_seconds": 530,
            }
            with patch.object(gate, "probe", return_value=metadata):
                with self.assertRaisesRegex(
                    ValueError, r"Explicit \.flac.*duration=530\.00s.*420\.00"
                ):
                    gate.select_sources(args)
            args.max_seconds = 900
            with patch.object(gate, "probe", return_value=metadata):
                self.assertEqual(
                    set(gate.select_sources(args)), {".flac", ".wav"}
                )

    def test_explicit_file_size_rejection_shows_mebibytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "sample.flac"
            audio.write_bytes(b"x" * 4096)
            info = {"duration_seconds": 600, "sample_rate": 48000}
            reasons = gate.limit_reasons(audio, info, 30, 420, 2048)
            self.assertEqual(len(reasons), 2)
            self.assertTrue(any("600.00s" in s for s in reasons))
            self.assertTrue(any("file_size=" in s and "MiB" in s for s in reasons))

    def test_extended_bound_only_for_explicit_two_tracks(self):
        # No filesystem actions: reject an implicit discovery request
        # before reference scanning or modifying output directories.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = SimpleNamespace(
                output_dir=root / "new-scan", tolerance=0.001,
                min_seconds=30, max_seconds=1500,
                max_file_mib=512, track=None,
                reference_wav=root / "missing",
            )
            with self.assertRaisesRegex(ValueError, "900 seconds"):
                gate.run(args)
            self.assertFalse(args.output_dir.exists())

    def test_ffprobe_chooses_audio_stream_not_embedded_cover_art(self):
        with tempfile.TemporaryDirectory() as temp:
            wav = Path(temp) / "sample.wav"
            recorded = []
            def fake_run(command, **kwargs):
                recorded.extend(command)
                return SimpleNamespace(returncode=0, stdout=(
                    '{"streams":[{"sample_rate":"44100","channels":2,'
                    '"bits_per_raw_sample":"N/A"}],'
                    '"format":{"duration":"180.5"}}'
                ))
            with patch.object(gate.subprocess, "run", side_effect=fake_run):
                result = gate.probe(wav)
            self.assertEqual(result["sample_rate"], 44100)
            self.assertEqual(result["channels"], 2)
            self.assertEqual(result["duration_seconds"], 180.5)
            self.assertEqual(recorded[recorded.index("-select_streams")+1],
                             "a:0")

    def test_no_unsupported_rate_or_large_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.flac"
            path.write_bytes(b"x" * 4096)
            info = {"duration_seconds": 120, "sample_rate": 48000, "channels": 2}
            self.assertTrue(gate.acceptable(path, info, 30, 420, 8*1024*1024))
            self.assertFalse(gate.acceptable(path, {**info, "sample_rate": 500000},
                                             30, 420, 8*1024*1024))
            self.assertFalse(gate.acceptable(path, {**info, "duration_seconds": 900},
                                             30, 420, 8*1024*1024))
            self.assertFalse(gate.acceptable(path, info, 30, 420, 4095))


if __name__ == "__main__":
    unittest.main()
