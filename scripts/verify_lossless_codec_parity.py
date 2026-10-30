#!/usr/bin/env python3
"""Bounded cross-codec release gate: SAME real-song PCM in 24-bit WAV and FLAC.

Use the ALREADY generated float32 PCM WAV from the real 837-patch MP3
experiment. Quantize once to PCM 24-bit WAV, encode that WAV to lossless
FLAC, independently decode both to raw 24-bit little-endian PCM and
require identical SHA256, raw byte length and stream layout. Then call
the *same already validated Rust-v5 CLI* in both modes on both files:
2 formats x (native original Essentia C++ / Rust v5) = four analyses.

This measures WAV/FLAC container/decoding parity for ONE original real
song; not an independently sourced FLAC cohort, commercial license
authorization, OS compatibility, or a complete library gate.
No original WAV/MP3/music/model/SQLite files are modified.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

from diagnose_mp3_wav_control import analyze, head_differences
from verify_resampler_fix_on_existing_wav import (
    FIXED_RUST_PREPROCESSING, REQUIRED_HEADS, audit_pair, sha256,
)

CPP_PREPROCESSING = "experimental-essentia-cpp-dsp-v1-unvalidated"


def invoke(command, description, timeout=1200):
    result = subprocess.run(command, capture_output=True, text=True,
                            check=False, timeout=timeout)
    if result.returncode:
        raise RuntimeError(
            f"{description} failed (exit {result.returncode}): {result.stderr[-900:]}"
        )
    return result.stdout


def ffprobe_layout(path):
    output = invoke([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels",
        "-of", "json", str(path)
    ], "FFprobe input layout", timeout=60)
    streams = json.loads(output).get("streams", [])
    if len(streams) != 1:
        raise AssertionError("Audio file has no unique first audio stream")
    rate = int(streams[0].get("sample_rate") or 0)
    channels = int(streams[0].get("channels") or 0)
    if rate <= 0 or channels not in (1, 2):
        raise AssertionError("Require valid mono/stereo audio stream")
    return {"sample_rate": rate, "channels": channels}


def encode_control_pair(original, wav24, flac):
    # Quantization is deliberately a single common step; FLAC is encoded
    # FROM integer WAV24, never independently quantized from float32.
    invoke([
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-n", "-i", str(original), "-map", "0:a:0", "-vn",
        "-c:a", "pcm_s24le", "-f", "wav", str(wav24)
    ], "One-time PCM float -> 24-bit WAV")
    if not wav24.is_file() or wav24.stat().st_size < 1000:
        raise AssertionError("Missing/empty PCM24 WAV")
    invoke([
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-n", "-i", str(wav24), "-map", "0:a:0", "-vn",
        "-c:a", "flac", "-sample_fmt", "s32",
        "-bits_per_raw_sample", "24", str(flac)
    ], "PCM24 WAV -> FLAC without second quantization")
    if not flac.is_file() or flac.stat().st_size < 1000:
        raise AssertionError("Missing/empty FLAC")


def decoded_pcm_digest(audio, output_raw):
    invoke([
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-n", "-i", str(audio), "-map", "0:a:0", "-vn",
        "-c:a", "pcm_s24le", "-f", "s24le", str(output_raw),
    ], "Decode WAV/FLAC to raw PCM24 for exact SHA256 comparison")
    if not output_raw.is_file() or output_raw.stat().st_size <= 0:
        raise AssertionError("Empty decoded PCM24 stream")
    return {"sha256": sha256(output_raw), "bytes": output_raw.stat().st_size}


def compare_codec_scores(a, b, tolerance):
    if a.get("schema_version") != 3 or b.get("schema_version") != 3:
        raise AssertionError("Both formats must produce schema-v3 reports")
    if a["preprocessing_version"] != b["preprocessing_version"]:
        raise AssertionError("Same backend switched preprocessing across formats")
    for head in REQUIRED_HEADS:
        left = a["classifications"][head]
        right = b["classifications"][head]
        for field in ("model_key", "embedding_model", "classification_model",
                      "models_sha256", "aggregation", "output_type"):
            if left[field] != right[field]:
                raise AssertionError(f"{head}: codec path changed {field}")
    diffs = head_differences(a, b)
    passed = all(
        value["maximum_absolute_score_difference"] <= tolerance
        for value in diffs.values()
    )
    return diffs, passed


def inspect_results(reports, source_sha, source_cpp, source_v5,
                    control_digests, layouts, tolerance):
    if not math.isfinite(tolerance) or not 0 < tolerance < 0.1:
        raise ValueError("Expected finite score tolerance between zero and 0.1")
    audit_pair(source_cpp, source_v5, source_sha, FIXED_RUST_PREPROCESSING)
    if source_cpp.get("preprocessing_version") != CPP_PREPROCESSING:
        raise AssertionError("Saved source C++ WAV is not from original worker")
    if layouts["wav24"] != layouts["flac"]:
        raise AssertionError("Converted files changed source rate/channel layout")
    if control_digests["wav24"] != control_digests["flac"]:
        raise AssertionError("FLAC and WAV do not decode to bit-identical PCM24")
    comparisons = {}
    score_pass = True
    for fmt in ("wav24", "flac"):
        rust = reports[fmt]["rust"]
        cpp = reports[fmt]["essentia"]
        if cpp.get("preprocessing_version") != CPP_PREPROCESSING:
            raise AssertionError("Not the original C++ Essentia DSP")
        # Every analysis must use the exact same Rust/C++ deployment and
        # model fingerprint as the previously PASSing real-WAV control.
        # Checking just the shared ONNX hashes would not catch replacement
        # of the original native C++ worker executable.
        for head in REQUIRED_HEADS:
            for reference, fresh, backend in (
                (source_cpp, cpp, "essentia"),
                (source_v5, rust, "rust"),
            ):
                a = reference["classifications"][head]
                b = fresh["classifications"][head]
                for field in ("model_key", "models_sha256", "embedding_model",
                              "classification_model", "aggregation", "output_type"):
                    if a[field] != b[field]:
                        raise AssertionError(
                            f"{fmt} {backend} changed verified reference {field} for {head}"
                        )
                if set(a["scores"]) != set(b["scores"]):
                    raise AssertionError(
                        f"{fmt} {backend} changed class labels for {head}"
                    )
        converted_sha = reports[fmt]["source_sha256"]
        result = audit_pair(cpp, rust, converted_sha, FIXED_RUST_PREPROCESSING)
        passed = all(
            v["maximum_absolute_score_difference"] <= tolerance
            for v in result.values()
        )
        score_pass = score_pass and passed
        comparisons[fmt] = {
            "backend_parity": result,
            "max_difference": max(
                v["maximum_absolute_score_difference"] for v in result.values()
            ),
            "patches": rust["patches_analyzed"],
            "status": "PASS" if passed else "FAIL",
        }
    for backend in ("rust", "essentia"):
        scores, passed = compare_codec_scores(
            reports["wav24"][backend], reports["flac"][backend], tolerance
        )
        comparisons[f"{backend}_wav24_vs_flac"] = {
            "per_head": scores,
            "max_difference": max(
                v["maximum_absolute_score_difference"] for v in scores.values()
            ),
            "status": "PASS" if passed else "FAIL",
        }
        score_pass = score_pass and passed
    patches = {reports[fmt][b]["patches_analyzed"]
               for fmt in ("wav24", "flac") for b in ("rust", "essentia")}
    if len(patches) != 1:
        raise AssertionError("Patch counts differ between formats or backends")
    return {
        "gate": "real_song_single_pcm24_wav_flac_cross_codec_v1",
        "status": "PASS" if score_pass else "FAIL",
        "tolerance": tolerance,
        "converted_same_pcm24_sha256": control_digests["wav24"]["sha256"],
        "converted_same_pcm24_bytes": control_digests["wav24"]["bytes"],
        "codec_layout": layouts["wav24"],
        "patches": patches.pop(),
        "comparisons": comparisons,
        "scope_note": (
            "One existing full real song quantized ONCE from float32 to integer "
            "PCM24. Identical decoded WAV24/FLAC PCM and matched original Essentia "
            "C++ vs corrected Rust-v5 ONNX scores. Does NOT cover independently "
            "sourced FLAC tracks, float-vs-int sample identity, platform "
            "portability, full library or redistribution licensing."
        ),
    }


def run(args):
    if not math.isfinite(args.tolerance) or not 0 < args.tolerance < 0.1:
        raise ValueError("Require finite max score tolerance in (0,0.1)")
    if args.output_dir.exists():
        raise FileExistsError("Choose a new private output folder; never overwrite")
    for item in (args.input_wav, args.saved_cpp_wav_json,
                 args.saved_rust_v5_wav_json, args.analyzer,
                 args.essentia_worker):
        if not item.is_file():
            raise FileNotFoundError(f"Missing prior input or executable: {item}")
    if not args.models_dir.is_dir():
        raise FileNotFoundError("Missing official ONNX model directory")
    source_sha = sha256(args.input_wav)
    old_cpp = json.loads(args.saved_cpp_wav_json.read_text(encoding="utf-8"))
    old_v5 = json.loads(args.saved_rust_v5_wav_json.read_text(encoding="utf-8"))
    audit_pair(old_cpp, old_v5, source_sha, FIXED_RUST_PREPROCESSING)
    input_layout = ffprobe_layout(args.input_wav)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    wav24 = args.output_dir / "real-song-common-pcm24.wav"
    flac = args.output_dir / "real-song-common-pcm24.flac"
    encode_control_pair(args.input_wav, wav24, flac)
    layouts = {"wav24": ffprobe_layout(wav24), "flac": ffprobe_layout(flac)}
    if any(value != input_layout for value in layouts.values()):
        raise AssertionError("Output WAV/FLAC rate/channels differ from input")
    with tempfile.TemporaryDirectory(prefix="pcm-proof-", dir=args.output_dir) as temp:
        raw_wav = Path(temp) / "wav24.s24le"
        raw_flac = Path(temp) / "flac.s24le"
        pcm_hashes = {
            "wav24": decoded_pcm_digest(wav24, raw_wav),
            "flac": decoded_pcm_digest(flac, raw_flac),
        }
    if pcm_hashes["wav24"] != pcm_hashes["flac"]:
        raise AssertionError("FLAC PCM24 samples differ from WAV24: stop before ONNX")
    results = {}
    for fmt, source in (("wav24", wav24), ("flac", flac)):
        results[fmt] = {"source_sha256": sha256(source)}
        for backend in ("rust", "essentia"):
            results[fmt][backend] = analyze(
                args.analyzer, source, args.models_dir, backend,
                args.essentia_worker if backend == "essentia" else None,
                args.output_dir / f"{fmt}-{backend}.json",
                args.output_dir / f"{fmt}-{backend}.stderr.txt",
            )
        # Fail promptly on model mismatches; preserve all reports so far.
        audit_pair(
            results[fmt]["essentia"], results[fmt]["rust"],
            results[fmt]["source_sha256"], FIXED_RUST_PREPROCESSING
        )
    if sha256(args.input_wav) != source_sha:
        raise AssertionError("Original source WAV changed during codec control")
    report = inspect_results(
        results, source_sha, old_cpp, old_v5, pcm_hashes, layouts, args.tolerance
    )
    (args.output_dir / "private-codec-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "scope": report["gate"],
        "pcm24_sha_equal": True,
        "patches": report["patches"],
        "wav24_cpp_vs_rust_max": report["comparisons"]["wav24"]["max_difference"],
        "flac_cpp_vs_rust_max": report["comparisons"]["flac"]["max_difference"],
        "rust_wav_vs_flac_max":
            report["comparisons"]["rust_wav24_vs_flac"]["max_difference"],
        "cpp_wav_vs_flac_max":
            report["comparisons"]["essentia_wav24_vs_flac"]["max_difference"],
        "tolerance": report["tolerance"],
        "private_report": str(args.output_dir / "private-codec-report.json"),
    }, indent=2, ensure_ascii=False, allow_nan=False))
    if report["status"] != "PASS":
        sys.exit(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-wav", type=Path, required=True)
    parser.add_argument("--saved-cpp-wav-json", type=Path, required=True)
    parser.add_argument("--saved-rust-v5-wav-json", type=Path, required=True)
    parser.add_argument("--analyzer", type=Path, required=True)
    parser.add_argument("--essentia-worker", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--score-max-tolerance", type=float,
                        default=0.001, dest="tolerance")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
