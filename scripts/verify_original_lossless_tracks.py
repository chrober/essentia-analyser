#!/usr/bin/env python3
"""Bounded native FLAC/WAV read-only real-library gate for original C++ vs Rust-v5.

Unlike the MP3-derived controlled WAV/FLAC test, these are *existing*
library files. Automatically find ONE .flac and ONE .wav with bounded
directory traversal, or supply precisely one original relative key of
each via repeated --track. Analyze each actual source exactly once with
both existing proven backends (four calls total). Never alter the NAS,
old models, saved SQLite sidecars or any source music.

This is an exploratory two-track independent-container cohort, not a
claim of universal codec/library or distribution/license qualification.
"""
import argparse
from collections import deque
import itertools
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from diagnose_mp3_wav_control import analyze, safe_source
from verify_lossless_codec_parity import (
    CPP_PREPROCESSING, REQUIRED_HEADS, compare_codec_scores,
)
from verify_resampler_fix_on_existing_wav import (
    FIXED_RUST_PREPROCESSING, audit_pair, sha256,
)

FORMATS = (".flac", ".wav")


def probe(path):
    """Technical metadata only. Never decode/re-encode original music."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries",
        "stream=sample_rate,channels,bits_per_raw_sample,bits_per_sample:format=duration",
        "-of", "json", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=45, check=False)
    if result.returncode:
        raise ValueError("Audio probe failed")
    data = json.loads(result.stdout)
    streams = data.get("streams") or []
    if len(streams) != 1:
        raise ValueError("Missing first audio stream")
    try:
        rate = int(streams[0]["sample_rate"])
        channels = int(streams[0]["channels"])
        duration = float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError("Incomplete audio technical metadata") from e
    if not math.isfinite(duration) or rate <= 0 or channels not in (1, 2):
        raise ValueError("Invalid rate/channels/duration")
    return {
        "sample_rate": rate, "channels": channels,
        "duration_seconds": duration,
        "bits_per_raw_sample": streams[0].get("bits_per_raw_sample"),
        "bits_per_sample": streams[0].get("bits_per_sample"),
    }


def limit_reasons(path, info, minimum, maximum, max_bytes):
    """Explain pre-inference size/duration/rate filters without leaking song path."""
    reasons = []
    duration = info["duration_seconds"]
    rate = info["sample_rate"]
    if not minimum <= duration <= maximum:
        reasons.append(
            f"duration={duration:.2f}s outside [{minimum:.2f}, {maximum:.2f}]s"
        )
    if not 8000 <= rate <= 192000:
        reasons.append(f"sample_rate={rate}Hz outside [8000, 192000]Hz")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError("Could not stat original source file") from exc
    if not 4096 <= size <= max_bytes:
        reasons.append(
            f"file_size={size / (1024 * 1024):.2f}MiB outside "
            f"[0.004, {max_bytes / (1024 * 1024):.2f}]MiB"
        )
    return reasons


def acceptable(path, info, minimum, maximum, max_bytes):
    try:
        return not limit_reasons(path, info, minimum, maximum, max_bytes)
    except (OSError, ValueError):
        return False


def validate_file(root, key):
    path = safe_source(root, key)
    if path.suffix.casefold() not in FORMATS:
        raise ValueError("Only actual source .flac and .wav tracks are allowed")
    root_absolute = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root_absolute):
        raise ValueError("Symlink or junction escapes the declared source root")
    if not path.is_file():
        raise FileNotFoundError("Lossless source is missing")
    return path


def candidate_keys(root, max_entries, max_depth):
    """Bounded BFS over original library, skipping links; no writes or rglob."""
    queue = deque([(root, 0)])
    inspected = 0
    while queue and inspected < max_entries:
        folder, depth = queue.popleft()
        # islice limits enumeration even for unexpectedly huge folders.
        remaining = max_entries - inspected
        try:
            with os.scandir(folder) as iterator:
                entries = sorted(
                    itertools.islice(iterator, remaining),
                    key=lambda item: item.name.casefold()
                )
        except OSError:
            continue
        inspected += len(entries)
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_file(follow_symlinks=False):
                    if Path(entry.name).suffix.casefold() in FORMATS:
                        yield Path(entry.path).relative_to(root).as_posix()
                elif depth < max_depth and entry.is_dir(follow_symlinks=False):
                    queue.append((Path(entry.path), depth + 1))
            except OSError:
                continue


def select_sources(args):
    root = args.source_root
    if not root.is_dir():
        raise FileNotFoundError("Music source root is not readable")
    if args.track:
        if len(args.track) != 2:
            raise ValueError("Explicit original tracks require one .wav and one .flac")
        keys = args.track
    else:
        if not 100 <= args.max_entries <= 20000 or not 1 <= args.max_depth <= 12:
            raise ValueError("Require bounded NAS discovery: 100..20000 entries, depth 1..12")
        keys = candidate_keys(root, args.max_entries, args.max_depth)
    selected = {}
    for key in keys:
        suffix = Path(key).suffix.casefold()
        if suffix not in FORMATS or suffix in selected:
            continue
        try:
            path = validate_file(root, key)
            metadata = probe(path)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            if args.track:
                raise
            continue
        violations = limit_reasons(
            path, metadata, args.min_seconds, args.max_seconds,
            args.max_file_mib * 1024 * 1024,
        )
        if violations:
            if args.track:
                raise ValueError(
                    f"Explicit {suffix} exceeds preflight limits: "
                    + "; ".join(violations)
                    + ". Adjust --max-seconds/--max-file-mib within the "
                    "hard bounded limits only after inspecting file metadata."
                )
            continue
        selected[suffix] = (key, path, metadata)
        if len(selected) == 2:
            break
    if set(selected) != set(FORMATS):
        raise ValueError(
            "Could not select one eligible original .flac and .wav within "
            "bounded NAS traversal. Use --track with two safe relative paths "
            "or increase --max-entries/--max-depth deliberately."
        )
    if selected[".flac"][1].resolve() == selected[".wav"][1].resolve():
        raise AssertionError("Two independent containers must be different files")
    return selected


def verify_reference(cpp, rust, sha):
    audit_pair(cpp, rust, sha, FIXED_RUST_PREPROCESSING)
    if cpp.get("preprocessing_version") != CPP_PREPROCESSING:
        raise AssertionError("Saved reference must be genuine original Essentia C++")
    for head in REQUIRED_HEADS:
        a, b = cpp["classifications"][head], rust["classifications"][head]
        if len(a["scores"]) != REQUIRED_HEADS[head]:
            raise AssertionError("Original source reference has wrong output dimensionality")
        if list(a["scores"]) != list(b["scores"]):
            raise AssertionError("Original source reference class label order changed")


def verify_new_pair(reference, sha, rust, cpp):
    if cpp.get("preprocessing_version") != CPP_PREPROCESSING:
        raise AssertionError("Output not from original Essentia C++")
    diffs = audit_pair(cpp, rust, sha, FIXED_RUST_PREPROCESSING)
    for head in REQUIRED_HEADS:
        # Exact official model weights/class order and native-worker hash
        # must match the saved REAL source proven reference, not merely
        # each other within a fresh pair.
        for expected, current in (
            (reference["essentia"]["classifications"][head],
             cpp["classifications"][head]),
            (reference["rust"]["classifications"][head],
             rust["classifications"][head]),
        ):
            for field in (
                "model_key", "models_sha256", "embedding_model",
                "classification_model", "aggregation", "output_type",
            ):
                if expected[field] != current[field]:
                    raise AssertionError(f"Changed verified backend/model identity for {head}: {field}")
            if list(expected["scores"]) != list(current["scores"]):
                raise AssertionError(f"Different class label order for {head}")
    return diffs


def compare_cases(results, selected, tolerance):
    if not math.isfinite(tolerance) or not 0 < tolerance < 0.1:
        raise ValueError("Require finite strict score tolerance in (0,0.1)")
    all_pass = True
    summary = {}
    for extension in FORMATS:
        case = results[extension]
        diffs = verify_new_pair(
            case["reference"], case["source_sha256"],
            case["rust"], case["essentia"]
        )
        worst = max(
            head["maximum_absolute_score_difference"] for head in diffs.values()
        )
        okay = worst <= tolerance
        all_pass = all_pass and okay
        summary[extension[1:]] = {
            "status": "PASS" if okay else "FAIL",
            "sample_rate": selected[extension][2]["sample_rate"],
            "channels": selected[extension][2]["channels"],
            "duration_seconds": selected[extension][2]["duration_seconds"],
            "patches": case["rust"]["patches_analyzed"],
            "max_score_difference": worst,
            "per_head_max": {
                h: v["maximum_absolute_score_difference"]
                for h, v in diffs.items()
            },
        }
    return {"status": "PASS" if all_pass else "FAIL", "two_original_tracks": summary}


def run(args):
    if args.output_dir.exists():
        raise FileExistsError("Output must be a NEW private folder; never overwrite")
    if not math.isfinite(args.tolerance) or not 0 < args.tolerance < 0.1:
        raise ValueError("Invalid numeric tolerance")
    # Longer user-provided jazz recordings are permitted only through
    # explicitly selected, bounded source keys, never automatic discovery.
    hard_duration_limit = 1800 if args.track else 900
    if not 20 <= args.min_seconds < args.max_seconds <= hard_duration_limit:
        raise ValueError(
            f"Require bounded song durations 20..{hard_duration_limit} seconds; "
            "1800-second exception requires two explicit --track values"
        )
    if not 8 <= args.max_file_mib <= 512:
        raise ValueError("Require bounded file size 8..512 MiB")
    for path in (
        args.reference_wav, args.reference_cpp_json, args.reference_v5_json,
        args.analyzer, args.essentia_worker
    ):
        if not path.is_file():
            raise FileNotFoundError("Missing prior verified original C++/v5 report or binary")
    if not args.models_dir.is_dir():
        raise FileNotFoundError("Missing ONNX models directory")
    ref_cpp = json.loads(args.reference_cpp_json.read_text(encoding="utf-8"))
    ref_rust = json.loads(args.reference_v5_json.read_text(encoding="utf-8"))
    ref_sha = sha256(args.reference_wav)
    verify_reference(ref_cpp, ref_rust, ref_sha)
    selected = select_sources(args)
    source_hashes = {
        ext: sha256(path) for ext, (_, path, _) in selected.items()
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    private_manifest = {
        "scope": "two_original_natural_lossless_source_tracks",
        "tolerance": args.tolerance,
        "original_source_tracks_private": {
            ext: {"key": key, "file_sha256": source_hashes[ext],
                  "source_path": str(path), "technical": info}
            for ext, (key, path, info) in selected.items()
        },
        "reference_wav_sha256": ref_sha,
        "scanner_sha256": sha256(args.analyzer),
        "worker_sha256": sha256(args.essentia_worker),
        "note": "Existing music/NAS and all prior reports never modified",
    }
    (args.output_dir / "source-manifest-private.json").write_text(
        json.dumps(private_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )
    results = {}
    for ext in FORMATS:
        _, source, _ = selected[ext]
        fmt = ext.lstrip(".")
        results[ext] = {
            "source_sha256": source_hashes[ext],
            "reference": {"rust": ref_rust, "essentia": ref_cpp},
        }
        for backend in ("rust", "essentia"):
            result = analyze(
                args.analyzer, source, args.models_dir, backend,
                args.essentia_worker if backend == "essentia" else None,
                args.output_dir / f"{fmt}-{backend}.json",
                args.output_dir / f"{fmt}-{backend}.stderr.txt",
            )
            results[ext][backend] = result
        verify_new_pair(
            results[ext]["reference"], source_hashes[ext],
            results[ext]["rust"], results[ext]["essentia"],
        )
        if sha256(source) != source_hashes[ext]:
            raise AssertionError("Source music changed during read-only scanner operation")
    if sha256(args.reference_wav) != ref_sha:
        raise AssertionError("Saved real reference WAV changed during test")
    report = compare_cases(results, selected, args.tolerance)
    report["scope"] = "two_actual_unmodified_library_flac_wav_v1"
    report["tolerance"] = args.tolerance
    report["note"] = (
        "Two actual unmodified original library files; results only qualify "
        "these tracks, not all sample rates, FLAC/WAV libraries, platforms "
        "or licensing rights."
    )
    (args.output_dir / "natural-lossless-parity-private.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )
    print(json.dumps({
        "status": report["status"],
        "scope": report["scope"],
        "tracks": report["two_original_tracks"],
        "tolerance": args.tolerance,
        "private_report": str(args.output_dir / "natural-lossless-parity-private.json"),
    }, indent=2, ensure_ascii=False, allow_nan=False))
    if report["status"] != "PASS":
        sys.exit(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--track", action="append",
        help="Optional existing relative NAS key. Supply exactly one FLAC and one WAV."
    )
    parser.add_argument("--max-entries", type=int, default=6000)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--min-seconds", type=float, default=30.0)
    parser.add_argument("--max-seconds", type=float, default=420.0,
                        help="Maximum song duration (default 420s, hard cap 900s for discovery / 1800s for explicit --track)")
    parser.add_argument("--max-file-mib", type=int, default=150)
    parser.add_argument("--reference-wav", type=Path, required=True)
    parser.add_argument("--reference-cpp-json", type=Path, required=True)
    parser.add_argument("--reference-v5-json", type=Path, required=True)
    parser.add_argument("--analyzer", type=Path, required=True)
    parser.add_argument("--essentia-worker", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--score-max-tolerance", type=float,
                        default=0.001, dest="tolerance")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
