"""Fail-closed cross-codec parity and identity tests, no real private music/ONNX."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_lossless_codec_parity as gate
from test_verify_resampler_fix_on_existing_wav import reports, AUDIO_SHA


def example():
    _old, original_cpp, original_v5 = reports(old_difference=0.003, new_difference=0.000002)
    layouts = {"wav24": {"sample_rate": 44100, "channels": 2},
               "flac": {"sample_rate": 44100, "channels": 2}}
    pcm = {"wav24": {"sha256": "c" * 64, "bytes": 400000},
           "flac": {"sha256": "c" * 64, "bytes": 400000}}
    scans = {}
    for fmt, sha in (("wav24", "1" * 64), ("flac", "2" * 64)):
        scans[fmt] = {
            "source_sha256": sha,
            "rust": deepcopy(original_v5),
            "essentia": deepcopy(original_cpp),
        }
        scans[fmt]["rust"]["audio_sha256"] = sha
        scans[fmt]["essentia"]["audio_sha256"] = sha
    return scans, original_cpp, original_v5, pcm, layouts


class LosslessCodecGateTests(unittest.TestCase):
    def test_exact_pcm_and_scores_allow_release_control_pass(self):
        data, cpp, rust, pcm, layouts = example()
        result = gate.inspect_results(
            data, AUDIO_SHA, cpp, rust, pcm, layouts, 0.001,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["patches"], 837)
        self.assertEqual(result["comparisons"]["rust_wav24_vs_flac"]["max_difference"], 0)
        self.assertEqual(result["comparisons"]["essentia_wav24_vs_flac"]["status"], "PASS")
        self.assertEqual(result["converted_same_pcm24_bytes"], 400000)

    def test_refuses_lossy_flac_or_nonidentical_pcm_and_layout(self):
        for issue in ("sha", "size", "channels"):
            data, cpp, rust, pcm, layouts = example()
            if issue == "sha":
                pcm["flac"]["sha256"] = "f" * 64
            elif issue == "size":
                pcm["flac"]["bytes"] = 400001
            else:
                layouts["flac"]["channels"] = 1
            with self.subTest(issue=issue), self.assertRaisesRegex(
                AssertionError, "PCM24|layout"
            ):
                gate.inspect_results(
                    data, AUDIO_SHA, cpp, rust, pcm, layouts, 0.001,
                )

    def test_fails_when_onxx_score_drift_exceeds_real_tolerance(self):
        data, cpp, rust, pcm, layouts = example()
        data["flac"]["rust"]["classifications"]["voice"]["scores"]["class-0"] += 0.002
        result = gate.inspect_results(
            data, AUDIO_SHA, cpp, rust, pcm, layouts, 0.001,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["comparisons"]["flac"]["status"], "FAIL")
        self.assertEqual(result["comparisons"]["rust_wav24_vs_flac"]["status"], "FAIL")

    def test_catches_wrong_weights_backend_and_patch_count(self):
        for issue in ("weights", "wrong_c++", "patches", "model_key", "native_binary"):
            data, cpp, rust, pcm, layouts = example()
            if issue == "weights":
                data["flac"]["rust"]["classifications"]["genre"]["models_sha256"]["genre.onnx"] = "f"*64
            elif issue == "wrong_c++":
                data["flac"]["essentia"]["preprocessing_version"] = gate.FIXED_RUST_PREPROCESSING
            elif issue == "patches":
                data["flac"]["rust"]["patches_analyzed"] = 836
            elif issue == "native_binary":
                data["flac"]["essentia"]["classifications"]["genre"]["models_sha256"]["essentia_cpp_worker_binary_sha256"] = "e"*64
            else:
                data["flac"]["rust"]["classifications"]["genre"]["model_key"] = "unexpected"
            with self.subTest(issue=issue), self.assertRaises(AssertionError):
                gate.inspect_results(data, AUDIO_SHA, cpp, rust, pcm, layouts, 0.001)

    def test_converter_quantizes_once_then_encodes_from_wav24(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src = root / "original.wav"
            src.write_bytes(b"x" * 2000)
            wav = root / "pcm24.wav"
            flac = root / "pcm24.flac"
            commands = []

            def fake_invoke(command, description, timeout=1200):
                commands.append(command)
                Path(command[-1]).write_bytes(b"x" * 2000)
                return ""

            with patch.object(gate, "invoke", side_effect=fake_invoke):
                gate.encode_control_pair(src, wav, flac)
            self.assertEqual(len(commands), 2)
            self.assertIn("pcm_s24le", commands[0])
            self.assertEqual(commands[0][commands[0].index("-i") + 1], str(src))
            self.assertEqual(commands[1][commands[1].index("-i") + 1], str(wav))
            self.assertEqual(commands[1][commands[1].index("-bits_per_raw_sample") + 1], "24")
            self.assertIn("flac", commands[1])


if __name__ == "__main__":
    unittest.main()
