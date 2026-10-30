#!/usr/bin/env python3
"""Check corrected Rust SRC_LINEAR against saved genuine C++ *full-song* report.

Runs exactly ONE production Rust analyze-features call on an existing WAV,
and compares it to already-saved C++ and old-Rust JSON. Never opens the NAS,
invokes C++, changes SQLite sidecars or writes source music. The new Rust CLI
must come from PR17 commit including SRC_LINEAR float32-ratio fix.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

from diagnose_mp3_wav_control import analyze, head_differences

REQUIRED_HEADS = {"genre": 87, "moodtheme": 56, "voice": 2}
FIXED_RUST_PREPROCESSING = "experimental-essentia-audio-v5-f32-src-ratio-unvalidated"
OLD_RUST_PREPROCESSING = "experimental-essentia-audio-v4-unvalidated"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit_pair(reference, current, expected_sha, rust_version):
    if reference.get("schema_version") != 3 or current.get("schema_version") != 3:
        raise AssertionError("Expected existing schema v3 classification reports")
    if reference.get("audio_sha256") != expected_sha or current.get("audio_sha256") != expected_sha:
        raise AssertionError("Saved C++ and new Rust analyses must describe the SAME WAV bytes")
    if current.get("preprocessing_version") != rust_version:
        raise AssertionError(
            f"Wrong Rust frontend identity: {current.get('preprocessing_version')}"
        )
    if reference.get("preprocessing_version") == rust_version:
        raise AssertionError("Rust and C++ must not use identical backend identity")
    if (reference.get("patches_analyzed") != current.get("patches_analyzed")
            or not isinstance(reference.get("patches_analyzed"), int)
            or reference["patches_analyzed"] <= 0):
        raise AssertionError("Different full-song Mel patch counts")
    left = reference["classifications"]
    right = current["classifications"]
    if set(left) != set(REQUIRED_HEADS) or set(right) != set(REQUIRED_HEADS):
        raise AssertionError("Expected identical Genre/Mood/Voice model heads")
    for head, count in REQUIRED_HEADS.items():
        cpp, rust = left[head], right[head]
        if (cpp["embedding_model"] != rust["embedding_model"]
                or cpp["classification_model"] != rust["classification_model"]
                or cpp["aggregation"] != rust["aggregation"]
                or cpp["output_type"] != rust["output_type"]
                or set(cpp["scores"]) != set(rust["scores"])
                or len(cpp["scores"]) != count):
            raise AssertionError(f"Different actual model semantics for {head}")
        required = {cpp["embedding_model"], cpp["classification_model"]}
        hashes = cpp["models_sha256"]
        other = rust["models_sha256"]
        if set(other) != required or any(
            hashes.get(key) != other.get(key) for key in required
        ):
            raise AssertionError(f"ONNX weights differ for {head}")
        if cpp["model_key"] == rust["model_key"]:
            raise AssertionError(f"Backend identities aliased for {head}")
    return head_differences(reference, current)


def inspect_reports(old, cpp, fixed, expected_sha, tol):
    if not math.isfinite(tol) or not 0 < tol < 0.1:
        raise ValueError("Require a finite numeric score tolerance in (0, 0.1)")
    old_scores = audit_pair(
        cpp, old, expected_sha, OLD_RUST_PREPROCESSING
    )
    new_scores = audit_pair(
        cpp, fixed, expected_sha, FIXED_RUST_PREPROCESSING
    )
    for head in REQUIRED_HEADS:
        if old["classifications"][head]["model_key"] == fixed["classifications"][head]["model_key"]:
            raise AssertionError("Rust corrected DSP reuses old v4 cache fingerprint")
    passed = all(
        v["maximum_absolute_score_difference"] <= tol
        for v in new_scores.values()
    )
    return {
        "scope": "single_full_song_837_patch_rust_v5_against_saved_original_cpp",
        "numeric_parity_status": "PASS_THIS_TRACK" if passed else "FAIL_THIS_TRACK",
        "note": "Single-track pass is not proof that the prior 100-song cohort passes",
        "wav_patches": fixed["patches_analyzed"],
        "tolerance": tol,
        "per_head": {
            head: {
                "old_rust_v4_max_abs_error":
                    old_scores[head]["maximum_absolute_score_difference"],
                "new_rust_v5_max_abs_error":
                    new_scores[head]["maximum_absolute_score_difference"],
                "new_rust_v5_mean_abs_error":
                    new_scores[head]["mean_absolute_score_difference"],
                "new_worst_class": new_scores[head]["worst_class"],
            }
            for head in REQUIRED_HEADS
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", required=True, type=Path)
    parser.add_argument("--old-rust-json", required=True, type=Path)
    parser.add_argument("--essentia-json", required=True, type=Path)
    parser.add_argument("--analyzer", required=True, type=Path)
    parser.add_argument("--models-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--score-max-tolerance", type=float, default=0.001)
    args = parser.parse_args()
    inputs = (args.wav, args.old_rust_json, args.essentia_json, args.analyzer)
    if any(not file.is_file() for file in inputs):
        raise FileNotFoundError("Original PCM WAV, old reports or new scanner are missing")
    if not args.models_dir.is_dir():
        raise FileNotFoundError("Missing ONNX models directory")
    if args.output_dir.exists():
        raise FileExistsError("Refusing to reuse a prior local report directory")
    old = json.loads(args.old_rust_json.read_text(encoding="utf-8"))
    cpp = json.loads(args.essentia_json.read_text(encoding="utf-8"))
    # Verify the independent old scan before spending CPU time on a new scan.
    expected_sha = sha256(args.wav)
    audit_pair(cpp, old, expected_sha, OLD_RUST_PREPROCESSING)
    args.output_dir.mkdir(parents=True)
    fixed = analyze(
        args.analyzer, args.wav, args.models_dir, "rust", None,
        args.output_dir / "rust-v5-full-wav.json",
        args.output_dir / "rust-v5-full-wav.stderr.txt",
    )
    if sha256(args.wav) != expected_sha:
        raise AssertionError("Input WAV changed while running the read-only analysis")
    summary = inspect_reports(
        old, cpp, fixed, expected_sha, args.score_max_tolerance
    )
    report = args.output_dir / "strict-rust-v5-vs-original-cpp-private.json"
    with report.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, ensure_ascii=False, allow_nan=False)
        output.write("\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))
    if summary["numeric_parity_status"] != "PASS_THIS_TRACK":
        sys.exit(2)


if __name__ == "__main__":
    main()
