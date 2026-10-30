"""Unit tests for full precision Rust/native Mel comparison on shared PCM."""
import sys
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import diagnose_pcm_frontend as diag


class ControlledPcmFrontendTests(unittest.TestCase):
    def test_precise_mel_equal_and_band_level_signal(self):
        count = diag.FRAMES_PER_PATCH + 3 * diag.PATCH_HOP
        rust = [[0.5] * 96 for _ in range(count)]
        native = [0.5] * (4 * 128 * 96)
        equal = diag.mel_errors(rust, native)
        self.assertEqual(equal["compared_coefficients"], 4 * 128 * 96)
        self.assertEqual(equal["maximum_absolute_error"], 0)
        self.assertEqual(equal["coefficients_over_0_001"], 0)
        # Two overlapping patches include the same shared global frame.
        index = ((2 * 128 + 16) * 96) + 23
        native[index] = 0.504
        d = diag.mel_errors(rust, native)
        self.assertAlmostEqual(d["maximum_absolute_error"], 0.004)
        self.assertEqual(d["coefficients_over_0_001"], 1)
        self.assertEqual(d["worst"]["patch"], 2)
        self.assertEqual(d["worst"]["global_frame"], 2 * 62 + 16)
        self.assertEqual(d["worst"]["mel_band"], 23)
        self.assertEqual(d["worst_bands_by_mean_error"][0], 23)

    def test_2x2_controls_separate_downmix_and_resample(self):
        self.assertEqual(set(diag.PCM_VARIANTS), {
            "native-rate", "native-rate-mono",
            "16khz-stereo", "16khz-mono"
        })
        with tempfile.TemporaryDirectory() as temp:
            input_wav = Path(temp) / "shared.wav"
            input_wav.write_bytes(b"x" * 5000)
            commands = []

            def fake_execute(command, what, timeout=180):
                commands.append(command)
                Path(command[-1]).write_bytes(b"x" * 5000)
                return ""

            with patch.object(diag, "execute", side_effect=fake_execute):
                for mode in diag.PCM_VARIANTS:
                    diag.create_excerpt(
                        input_wav, Path(temp) / f"{mode}.wav",
                        offset_seconds=120, seconds=12, mode=mode
                    )
            self.assertEqual(len(commands), 4)
            for mode, command in zip(diag.PCM_VARIANTS, commands):
                rate, channels = diag.PCM_VARIANTS[mode]
                if rate is None:
                    self.assertNotIn("-ar", command)
                else:
                    self.assertEqual(command[command.index("-ar") + 1], str(rate))
                if channels is None:
                    self.assertNotIn("-ac", command)
                else:
                    self.assertEqual(command[command.index("-ac") + 1], str(channels))
                self.assertIn("120", command)

    def test_probe_validates_input_layout(self):
        good = '{"streams":[{"sample_rate":"44100","channels":2}]}'
        with patch.object(diag, "execute", return_value=good):
            self.assertEqual(diag.source_audio_layout(Path("shared.wav")),
                             (44100, 2))
        for response in ('{"streams":[]}',
                         '{"streams":[{"sample_rate":"0","channels":2}]}',
                         '{"streams":[{"sample_rate":"44100","channels":6}]}'):
            with patch.object(diag, "execute", return_value=response):
                with self.assertRaises(ValueError):
                    diag.source_audio_layout(Path("shared.wav"))

    def test_rejects_malformed_mel(self):
        frames = [[0.0] * 96 for _ in range(314)]
        native = [0.0] * (4 * 128 * 96)
        with self.assertRaisesRegex(AssertionError, "too few"):
            diag.mel_errors(frames[:313], native)
        with self.assertRaisesRegex(AssertionError, "shape mismatch"):
            diag.mel_errors(frames, native[:4])
        frames[10][0] = float("nan")
        with self.assertRaisesRegex(AssertionError, "Nonfinite Mel"):
            diag.mel_errors(frames, native)


if __name__ == "__main__":
    unittest.main()
