#!/usr/bin/env python3
"""Compare original Essentia C++ vs Rust on short, shared-PCM audio excerpts.

Distinguishes resampling/downmix from FFT/Mel differences using the SAME
audio samples for both backends. Requires existing original C++ dev-kit,
its unchanged Rust CLI, FFmpeg/FFprobe, same ONNX models and previous
locally generated long WAV. No rebuild, no NAS access, no full song scans.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess

from diagnose_mp3_wav_control import head_differences
from test_native_essentia_protocol import exact, request

MEL_BANDS = 96
FRAMES_PER_PATCH = 128
PATCH_HOP = 62
MEL_COMPARE_PATCHES = 4


def mel_errors(reference_frames, native_patch, number=MEL_COMPARE_PATCHES):
    """Report errors at original Mel input coordinates, not aggregate scores."""
    if len(reference_frames) < FRAMES_PER_PATCH + (number - 1) * PATCH_HOP:
        raise AssertionError("Rust reference contains too few Mel frames")
    if len(native_patch) != number * FRAMES_PER_PATCH * MEL_BANDS:
        raise AssertionError("Native Mel patch shape mismatch")
    errors = []
    by_band = [[] for _ in range(MEL_BANDS)]
    by_patch = [[] for _ in range(number)]
    worst = {"error": -1.0}
    for patch in range(number):
        for frame in range(FRAMES_PER_PATCH):
            rust_frame = reference_frames[patch * PATCH_HOP + frame]
            if len(rust_frame) != MEL_BANDS:
                raise AssertionError("Invalid Rust Mel filterbank band count")
            start = (patch * FRAMES_PER_PATCH + frame) * MEL_BANDS
            for band, rust in enumerate(rust_frame):
                native = native_patch[start + band]
                if not (math.isfinite(rust) and math.isfinite(native)):
                    raise AssertionError("Nonfinite Mel coefficient")
                difference = abs(float(rust) - float(native))
                errors.append(difference)
                by_band[band].append(difference)
                by_patch[patch].append(difference)
                if difference > worst["error"]:
                    worst = {
                        "patch": patch, "frame": frame, "global_frame": patch * PATCH_HOP + frame,
                        "mel_band": band, "rust_value": rust, "essentia_value": native,
                        "error": difference,
                    }
    if not errors:
        raise AssertionError("Empty Mel comparison")
    return {
        "compared_coefficients": len(errors),
        "maximum_absolute_error": worst["error"],
        "mean_absolute_error": sum(errors) / len(errors),
        "coefficients_over_0_001": sum(x > 0.001 for x in errors),
        "worst": worst,
        "worst_bands_by_mean_error": sorted(
            range(MEL_BANDS),
            key=lambda b: -sum(by_band[b]) / len(by_band[b]),
        )[:10],
        "per_patch": [
            {"patch": n, "max_error": max(values),
             "mean_error": sum(values) / len(values)}
            for n, values in enumerate(by_patch)
        ],
    }


def execute(command, what, timeout=300):
    result = subprocess.run(command, capture_output=True, text=True,
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(
            f"{what}: exit {result.returncode}: {result.stderr[-1200:]}"
        )
    return result.stdout


# The 2x2 input layout bypasses one processing step at a time:
# full stereo/rate = downmix+resampling by each backend
# native-rate mono = only resampling by each backend
# 16kHz stereo = only downmix by each backend
# 16kHz mono = neither, isolating FFT/Mel.
PCM_VARIANTS = {
    "native-rate": (None, None),
    "native-rate-mono": (None, 1),
    "16khz-stereo": (16000, 2),
    "16khz-mono": (16000, 1),
}


def source_audio_layout(input_wav):
    output = execute(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels",
         "-of", "json", str(input_wav)],
        "FFprobe shared PCM source layout", timeout=60,
    )
    streams = json.loads(output).get("streams") or []
    if len(streams) != 1:
        raise ValueError("Expected exactly one selected first audio stream")
    rate = int(streams[0].get("sample_rate") or 0)
    channels = int(streams[0].get("channels") or 0)
    if rate <= 0 or channels not in (1, 2):
        raise ValueError("Expected valid mono or stereo PCM input")
    return rate, channels


def create_excerpt(input_wav, output_file, offset_seconds, seconds,
                   normalized=False, *, mode=None):
    if mode is None:
        mode = "16khz-mono" if normalized else "native-rate"
    if mode not in PCM_VARIANTS:
        raise ValueError(f"Unsupported PCM factor-control mode: {mode}")
    rate, channels = PCM_VARIANTS[mode]
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-n"]
    if offset_seconds:
        command += ["-ss", str(offset_seconds)]
    command += [
        "-i", str(input_wav), "-t", str(seconds),
        "-map", "0:a:0", "-vn", "-c:a", "pcm_f32le"
    ]
    if rate is not None:
        command += ["-ar", str(rate)]
    if channels is not None:
        command += ["-ac", str(channels)]
    command += [str(output_file)]
    execute(command, f"FFmpeg controlled excerpt {output_file}", timeout=180)
    if not output_file.is_file() or output_file.stat().st_size < 4096:
        raise AssertionError(f"FFmpeg excerpt unexpectedly empty: {output_file}")


def rust_mel(cli, clip):
    required_frames = FRAMES_PER_PATCH + (MEL_COMPARE_PATCHES - 1) * PATCH_HOP
    result = execute(
        [str(cli), "mel-dump", str(clip), "--max-frames", str(required_frames)],
        "Rust production Mel dump", timeout=180,
    )
    parsed = json.loads(result)
    if parsed.get("total_frames", 0) < required_frames:
        raise AssertionError("Rust clip shorter than required four Mel patches")
    frames = parsed["frames"]
    if len(frames) != required_frames:
        raise AssertionError("Expected precisely required Mel prefix")
    return frames


def head_scores(cli, worker, models_dir, clip, backend, stdout, stderr):
    command = [
        str(cli), "analyze-features", str(clip),
        "--models-dir", str(models_dir),
        "--models", "genre,moodtheme,voice",
        "--threads", "1",
        "--audio-backend", backend,
        "--json",
    ]
    if backend == "essentia":
        command += ["--essentia-worker", str(worker)]
    if stdout.exists() or stderr.exists():
        raise FileExistsError("Refusing to overwrite CLI output")
    with stdout.open("x", encoding="utf-8") as out, stderr.open(
        "x", encoding="utf-8"
    ) as err:
        code = subprocess.run(command, stdout=out, stderr=err,
                              check=False, timeout=240).returncode
    if code:
        raise RuntimeError(f"{backend} failed, see private log {stderr}")
    report = json.loads(stdout.read_text(encoding="utf-8"))
    if report.get("schema_version") != 3:
        raise AssertionError(f"{backend} wrong JSON schema")
    return report


def native_mel(worker, audio_files):
    results = {}
    with subprocess.Popen(
        [str(worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    ) as proc:
        if exact(proc.stdout, 4) != b"EFW1":
            raise RuntimeError("Not the expected original Essentia worker")
        for item, path in audio_files:
            status, packet, _, _ = request(
                proc, path, patch_cap=MEL_COMPARE_PATCHES
            )
            if status != 0:
                raise RuntimeError(f"Essentia rejected controlled WAV: {packet}")
            count, values = packet
            if count != MEL_COMPARE_PATCHES:
                raise AssertionError("Original worker returned too few patches")
            results[item] = values
        proc.stdin.close()
        if proc.wait(timeout=30):
            raise RuntimeError("Native worker failed to exit cleanly")
    return results


def diagnose(args):
    for file in (args.input_wav, args.analyzer, args.essentia_worker):
        if not file.is_file():
            raise FileNotFoundError(str(file))
    if not args.models_dir.is_dir():
        raise FileNotFoundError(str(args.models_dir))
    if args.output_dir.exists():
        raise FileExistsError("Output must be a new private directory")
    if args.offsets is None or any(x < 0 for x in args.offsets):
        raise ValueError("Offsets must be nonnegative")
    if not 4 <= args.duration_seconds <= 30:
        raise ValueError("Select 4..30 second excerpts")
    if len(args.offsets) != len(set(args.offsets)) or len(args.offsets) > 3:
        raise ValueError("Use at most three distinct offsets")
    rate, channels = source_audio_layout(args.input_wav)
    if args.factorial and (rate == 16000 or channels != 2):
        raise ValueError(
            "Factorial downmix/resampling isolation requires a stereo WAV "
            "whose original sampling rate differs from 16 kHz"
        )
    args.output_dir.mkdir(parents=True)
    samples = []
    modes = tuple(PCM_VARIANTS) if args.factorial else (
        "native-rate", "16khz-mono"
    )
    for index, offset in enumerate(args.offsets):
        for mode in modes:
            clip = args.output_dir / f"offset-{index:02d}-{mode}.wav"
            create_excerpt(
                args.input_wav, clip, offset, args.duration_seconds,
                mode=mode,
            )
            samples.append((f"{index}-{mode}", clip))
    native_patches = native_mel(args.essentia_worker, samples)
    cases = {}
    for name, clip in samples:
        frames = rust_mel(args.analyzer, clip)
        mel = mel_errors(frames, native_patches[name])
        outputs = {}
        for backend in ("rust", "essentia"):
            outputs[backend] = head_scores(
                args.analyzer, args.essentia_worker, args.models_dir,
                clip, backend,
                args.output_dir / f"{name}-{backend}-features.json",
                args.output_dir / f"{name}-{backend}-stderr.txt",
            )
        scores = head_differences(outputs["rust"], outputs["essentia"])
        cases[name] = {
            "mel": mel,
            "model_scores": scores,
            "patches_full_clip": outputs["rust"]["patches_analyzed"],
            "all_scores_within_0_001": all(
                v["maximum_absolute_score_difference"] <= 0.001
                for v in scores.values()
            ),
        }
    report = {
        "schema": "controlled-frontends-pcm-short-excerpts-v1",
        "description": (
            "Shared float32 PCM WAV clips with controlled input sample rate "
            "and channel count, including 2x2 stereo/mono x native/16kHz "
            "factorial isolation when selected. Four initial Mel patches "
            "and full-clip ONNX scores; not the 100-song parity gate."
        ),
        "offsets_seconds": args.offsets,
        "duration_seconds": args.duration_seconds,
        "source_sample_rate": rate,
        "source_channels": channels,
        "factorial_isolation": args.factorial,
        "cases": cases,
    }
    with (args.output_dir / "private-pcm-diagnostic.json").open(
        "x", encoding="utf-8"
    ) as target:
        json.dump(report, target, indent=2, ensure_ascii=False, allow_nan=False)
        target.write("\n")
    summary = {}
    for name, case in cases.items():
        summary[name] = {
            "mel_max": case["mel"]["maximum_absolute_error"],
            "mel_mean": case["mel"]["mean_absolute_error"],
            "mel_count_over_0_001": case["mel"]["coefficients_over_0_001"],
            "worst_mel_frame": case["mel"]["worst"]["global_frame"],
            "worst_mel_band": case["mel"]["worst"]["mel_band"],
            "patches": case["patches_full_clip"],
            "genre_max": case["model_scores"]["genre"]["maximum_absolute_score_difference"],
            "mood_max": case["model_scores"]["moodtheme"]["maximum_absolute_score_difference"],
            "voice_max": case["model_scores"]["voice"]["maximum_absolute_score_difference"],
            "scores_within_0_001": case["all_scores_within_0_001"],
        }
    print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))
    print(f"Detailed private report: {args.output_dir / 'private-pcm-diagnostic.json'}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-wav", type=Path, required=True)
    parser.add_argument("--analyzer", type=Path, required=True)
    parser.add_argument("--essentia-worker", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--offsets", type=str, default="0,120")
    parser.add_argument("--duration-seconds", type=float, default=12)
    parser.add_argument(
        "--factorial", action="store_true",
        help="Add native-rate mono and 16kHz stereo to separate downmix from resampling",
    )
    args = parser.parse_args()
    try:
        args.offsets = [float(part.strip()) for part in args.offsets.split(",")]
    except ValueError:
        parser.error("Offsets must be comma-separated seconds")
    if not args.offsets:
        parser.error("At least one offset required")
    diagnose(args)


if __name__ == "__main__":
    main()
