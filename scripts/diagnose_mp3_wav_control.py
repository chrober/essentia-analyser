#!/usr/bin/env python3
"""Controlled single-track MP3-vs-decoded-WAV original Essentia frontend test.

Use *one existing* high-drift MP3 from the local private diagnostics.
Convert its complete audio stream to lossless float32 WAV once using FFmpeg
(without resampling/downmix), then analyze that same WAV with BOTH audio
backends and the exact same ONNX model weights. Never touch private music
or existing schema-v3 databases. Reports and WAV stay local.
"""
import argparse
import json
import math
from pathlib import Path, PurePosixPath
import subprocess

from benchmark_audio_backends import load_feature_rows


def safe_source(root, key):
    if not isinstance(key, str) or not key or "\x00" in key:
        raise ValueError("Missing/invalid song path in private diagnostic")
    unix_key = key.replace("\\", "/")
    posix = PurePosixPath(unix_key)
    if (posix.is_absolute() or not posix.parts
            or any(part in (".", "..") or ":" in part for part in unix_key.split("/"))
            or unix_key.startswith("//")):
        raise ValueError("Refusing absolute/traversal track key")
    return root.joinpath(*posix.parts)


def head_differences(rust, cpp):
    a, b = rust["classifications"], cpp["classifications"]
    if not a or a.keys() != b.keys():
        raise AssertionError("Different or missing model heads for WAV control")
    if rust["patches_analyzed"] != cpp["patches_analyzed"]:
        raise AssertionError("WAV backend patch counts disagree")
    results = {}
    for head in sorted(a):
        left, right = a[head]["scores"], b[head]["scores"]
        if left.keys() != right.keys() or not left:
            raise AssertionError(f"Different class identities for {head}")
        differences = {
            key: abs(left[key] - right[key]) for key in left
        }
        if any(not math.isfinite(d) for d in differences.values()):
            raise AssertionError("Nonfinite output difference")
        worst = max(differences, key=differences.get)
        results[head] = {
            "classes": len(differences),
            "maximum_absolute_score_difference": differences[worst],
            "mean_absolute_score_difference":
                sum(differences.values()) / len(differences),
            "worst_class": worst,
        }
    return results


def previous_track_differences(rust_db, cpp_db, key):
    old = load_feature_rows(rust_db)
    new = load_feature_rows(cpp_db)
    heads = {head for track, head in old if track == key}
    if heads != {head for track, head in new if track == key}:
        raise AssertionError("Original MP3 head identities differ")
    results = {}
    for head in sorted(heads):
        a_count, a = old[key, head]
        b_count, b = new[key, head]
        if a_count != b_count or len(a) != len(b):
            raise AssertionError("Existing MP3 sidecar shape mismatch")
        differences = [abs(x - y) for x, y in zip(a, b)]
        results[head] = {
            "patches": a_count,
            "maximum_absolute_score_difference": max(differences),
            "mean_absolute_score_difference": sum(differences) / len(differences),
        }
    return results


def analyze(executable, wav, models_dir, backend, worker, report_file, error_file):
    args = [
        str(executable), "analyze-features", str(wav),
        "--models-dir", str(models_dir),
        "--models", "genre,moodtheme,voice",
        "--audio-backend", backend,
        "--threads", "1", "--json",
    ]
    if backend == "essentia":
        args.extend(["--essentia-worker", str(worker)])
    with report_file.open("x", encoding="utf-8") as out, error_file.open(
        "x", encoding="utf-8"
    ) as stderr:
        result = subprocess.run(args, stdout=out, stderr=stderr,
                                check=False, timeout=1200)
    if result.returncode:
        raise RuntimeError(
            f"WAV {backend} analysis exited {result.returncode}. "
            f"Inspect private error file {error_file}"
        )
    report = json.loads(report_file.read_text(encoding="utf-8"))
    if report["schema_version"] != 3:
        raise AssertionError("Unexpected CLI schema, expected v3")
    return report


def run(args):
    if args.output_dir.exists():
        raise FileExistsError(
            f"Choose a NEW output directory, will not overwrite: {args.output_dir}"
        )
    if any(not p.is_file() for p in (
        args.drift_report, args.rust_db, args.essentia_db,
        args.analyzer, args.essentia_worker
    )):
        raise FileNotFoundError("Missing input diagnostic, database, or binary")
    if not args.models_dir.is_dir() or not args.source_root.is_dir():
        raise FileNotFoundError("Missing model directory or NAS music root")
    report = json.loads(args.drift_report.read_text(encoding="utf-8"))
    if report.get("numeric_parity_status") != "FAIL":
        raise ValueError("Expected confirmed failed numeric MP3 parity report")
    worst = report.get("worst_track_head_pairs") or []
    if not 1 <= args.rank <= len(worst):
        raise ValueError("Invalid rank in recorded worst-track diagnostics")
    key = worst[args.rank - 1]["track_file"]
    original = safe_source(args.source_root, key)
    if original.suffix.casefold() != ".mp3" or not original.is_file():
        raise ValueError("Selected private track is not an available real MP3")
    original_stats = previous_track_differences(
        args.rust_db, args.essentia_db, key
    )
    args.output_dir.mkdir(parents=True)
    wav = args.output_dir / "control-from-mp3-decoded-float32.wav"
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-n", "-i", str(original), "-map", "0:a:0", "-vn",
        "-c:a", "pcm_f32le", "-f", "wav", str(wav),
    ]
    result = subprocess.run(command, check=False, capture_output=True,
                            text=True, timeout=1200)
    if result.returncode or not wav.is_file() or wav.stat().st_size <= 44:
        raise RuntimeError(
            f"Lossless WAV conversion failed (exit {result.returncode}): "
            + result.stderr[-600:]
        )
    generated = {}
    for backend in ("rust", "essentia"):
        generated[backend] = analyze(
            args.analyzer, wav, args.models_dir, backend, args.essentia_worker,
            args.output_dir / f"{backend}-wav.json",
            args.output_dir / f"{backend}-wav.stderr.txt",
        )
    differences = head_differences(generated["rust"], generated["essentia"])
    wav_parity = all(
        s["maximum_absolute_score_difference"] <= args.tolerance
        for s in differences.values()
    )
    # Even an identical WAV can have slightly different patch boundaries from
    # the original MP3 due to encoder delay/trimming. Report, never hide it.
    wav_patches = generated["rust"]["patches_analyzed"]
    same_number_of_patches = all(
        old["patches"] == wav_patches for old in original_stats.values()
    )
    summary = {
        "schema": "real-mp3-decoded-wav-control-v1",
        "interpretation": (
            "The WAV control uses a shared FFmpeg-decoded PCM input. "
            "WAV agreement suggests differences arise in how the original "
            "MP3 is decoded/trimmed, but does not independently prove it. "
            "WAV disagreement indicates a further frontend/resampling/DSP "
            "difference, not necessarily the same cause as original MP3 drift."
        ),
        "selected_outlier_rank": args.rank,
        "original_mp3_saved_sidecars": original_stats,
        "decoded_wav_backend_comparison": differences,
        "decoded_wav_max_error_within_original_tolerance": wav_parity,
        "decoded_wav_patch_count": wav_patches,
        "decoded_wav_patch_count_matches_original_mp3": same_number_of_patches,
        "original_track_key_private": key,
        "decoder": "ffmpeg external to Windows dev kit; pcm_f32le WAV, native sample rate/channels",
        "wav_local_private": str(wav),
    }
    target = args.output_dir / "control-summary-private.json"
    with target.open("x", encoding="utf-8") as out:
        json.dump(summary, out, indent=2, ensure_ascii=False, allow_nan=False)
        out.write("\n")
    # No private track keys in stdout or CI logs.
    print(json.dumps({
        "original_mp3_by_head": original_stats,
        "wav_control_by_head": differences,
        "wav_control_within_tolerance": wav_parity,
        "wav_patches_match_original": same_number_of_patches,
        "private_report": str(target),
    }, indent=2, allow_nan=False))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drift-report", required=True, type=Path)
    parser.add_argument("--rust-db", required=True, type=Path)
    parser.add_argument("--essentia-db", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--analyzer", required=True, type=Path)
    parser.add_argument("--essentia-worker", required=True, type=Path)
    parser.add_argument("--models-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--rank", type=int, default=1,
                        help="Worst saved song/head pair rank (default 1)")
    parser.add_argument("--score-max-tolerance", type=float, default=0.001,
                        dest="tolerance")
    args = parser.parse_args()
    if not math.isfinite(args.tolerance) or not (0 < args.tolerance < 0.1):
        parser.error("Require finite tolerance between zero and 0.1")
    run(args)


if __name__ == "__main__":
    main()
