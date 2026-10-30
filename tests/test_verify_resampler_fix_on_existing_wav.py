"""Strict reusable-diagnostic tests: old v4 vs new v5 vs saved native C++."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_resampler_fix_on_existing_wav as verify

AUDIO_SHA = "a" * 64


def reports(old_difference=0.003, new_difference=0.00002):
    cpp = {
        "schema_version": 3,
        "preprocessing_version": "experimental-essentia-cpp-dsp-v1-unvalidated",
        "audio_sha256": AUDIO_SHA,
        "patches_analyzed": 837,
        "classifications": {},
    }
    old = deepcopy(cpp)
    fixed = deepcopy(cpp)
    old["preprocessing_version"] = verify.OLD_RUST_PREPROCESSING
    fixed["preprocessing_version"] = verify.FIXED_RUST_PREPROCESSING
    for head, count in verify.REQUIRED_HEADS.items():
        filename = f"{head}.onnx"
        metadata = {
            "embedding_model": "encoder.onnx",
            "classification_model": filename,
            "aggregation": "mean",
            "output_type": "softmax" if head == "voice" else "sigmoid",
            "scores": {f"class-{i}": 0.5 for i in range(count)},
        }
        for label, report, delta in (
            ("cpp", cpp, 0),
            ("v4", old, old_difference),
            ("v5", fixed, new_difference),
        ):
            item = deepcopy(metadata)
            item["model_key"] = f"{head}-{label}"
            item["scores"]["class-0"] += delta
            item["models_sha256"] = {
                "encoder.onnx": "b" * 64,
                filename: "c" * 64,
            }
            if label == "cpp":
                item["models_sha256"]["essentia_cpp_worker_binary_sha256"] = "d" * 64
            report["classifications"][head] = item
    return old, cpp, fixed


class ResamplerFixAuditTests(unittest.TestCase):
    def test_single_full_song_success_is_not_100_song_gate(self):
        old, cpp, fixed = reports()
        r = verify.inspect_reports(old, cpp, fixed, AUDIO_SHA, 0.001)
        self.assertEqual(r["numeric_parity_status"], "PASS_THIS_TRACK")
        self.assertEqual(r["wav_patches"], 837)
        self.assertIn("not proof", r["note"])
        self.assertAlmostEqual(r["per_head"]["voice"]["old_rust_v4_max_abs_error"], 0.003)
        self.assertAlmostEqual(r["per_head"]["voice"]["new_rust_v5_max_abs_error"], 0.00002)

    def test_still_rejects_drift_over_original_tolerance(self):
        old, cpp, fixed = reports(new_difference=0.002)
        r = verify.inspect_reports(old, cpp, fixed, AUDIO_SHA, 0.001)
        self.assertEqual(r["numeric_parity_status"], "FAIL_THIS_TRACK")

    def test_rejects_old_cache_key_reuse_and_versions(self):
        old, cpp, fixed = reports()
        fixed["classifications"]["voice"]["model_key"] = (
            old["classifications"]["voice"]["model_key"]
        )
        with self.assertRaisesRegex(AssertionError, "reuses old v4"):
            verify.inspect_reports(old, cpp, fixed, AUDIO_SHA, 0.001)
        old, cpp, fixed = reports()
        fixed["preprocessing_version"] = verify.OLD_RUST_PREPROCESSING
        with self.assertRaisesRegex(AssertionError, "Wrong Rust frontend identity"):
            verify.inspect_reports(old, cpp, fixed, AUDIO_SHA, 0.001)

    def test_rejects_different_pcm_onnx_or_model_semantics(self):
        old, cpp, fixed = reports()
        fixed["audio_sha256"] = "f" * 64
        with self.assertRaisesRegex(AssertionError, "SAME WAV bytes"):
            verify.inspect_reports(old, cpp, fixed, AUDIO_SHA, 0.001)
        old, cpp, fixed = reports()
        fixed["classifications"]["genre"]["models_sha256"]["genre.onnx"] = "f" * 64
        with self.assertRaisesRegex(AssertionError, "ONNX weights differ"):
            verify.inspect_reports(old, cpp, fixed, AUDIO_SHA, 0.001)
        old, cpp, fixed = reports()
        fixed["patches_analyzed"] = 836
        with self.assertRaisesRegex(AssertionError, "patch counts"):
            verify.inspect_reports(old, cpp, fixed, AUDIO_SHA, 0.001)
        old, cpp, fixed = reports()
        fixed["classifications"]["voice"]["scores"].pop("class-1")
        with self.assertRaisesRegex(AssertionError, "model semantics"):
            verify.inspect_reports(old, cpp, fixed, AUDIO_SHA, 0.001)


if __name__ == "__main__":
    unittest.main()
