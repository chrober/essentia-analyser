#!/usr/bin/env python3
"""Executable end-to-end smoke for actual compiled original Essentia C++ worker."""
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import wave

def exact(stream, count):
    result = bytearray()
    while len(result) < count:
        part = stream.read(count - len(result))
        if not part:
            raise RuntimeError(f"Truncated native stream: wanted {count} bytes, got {len(result)}")
        result.extend(part)
    return bytes(result)

def request(proc, path, patch_cap=0):
    encoded = str(path).encode("utf-8")
    proc.stdin.write(b"REQ1" + struct.pack("<II", len(encoded), patch_cap) + encoded)
    proc.stdin.flush()
    header = exact(proc.stdout, 25)
    if header[:4] != b"RES1":
        raise RuntimeError(f"Protocol mismatch: {header[:4]!r}")
    status = header[4]
    count, decoding, frontend = struct.unpack("<IQQ", header[5:])
    if status == 1:
        if count > 4096: raise RuntimeError("Excessive error response")
        return status, exact(proc.stdout, count).decode("utf8"), decoding, frontend
    if status != 0 or count == 0 or count > 2048:
        raise RuntimeError("Invalid native status / patch count")
    raw = exact(proc.stdout, count * 128 * 96 * 4)
    values = struct.unpack("<" + "f" * (count * 128 * 96), raw)
    if not all(math.isfinite(v) and v >= 0 for v in values):
        raise RuntimeError("Invalid Mel values from original Essentia")
    return status, (count, values), decoding, frontend

def compare_to_rust_mel(rust_executable, path, patches):
    """Every f32 in every native EffNet patch must agree with Rust frontend."""
    output = subprocess.run(
        [rust_executable, "mel-dump", str(path), "--max-frames", "1024"],
        check=False, capture_output=True, text=True, timeout=120,
    )
    if output.returncode:
        raise RuntimeError(
            f"Rust reference failed with exit={output.returncode}: "
            f"{output.stderr[-4000:]}"
        )
    parsed = json.loads(output.stdout)
    frames = parsed["frames"]
    count, native = patches
    if len(frames) < 128 + (count - 1) * 62 or any(len(frame) != 96 for frame in frames):
        raise RuntimeError("Rust Mel reference has insufficient/malformed frames")
    errors = []
    for patch_index in range(count):
        for frame_index in range(128):
            ref = frames[patch_index * 62 + frame_index]
            offset = (patch_index * 128 + frame_index) * 96
            errors.extend(abs(a - b) for a, b in zip(native[offset:offset + 96], ref))
    if not errors or len(errors) != count * 128 * 96:
        raise RuntimeError("Native Mel comparison length mismatch")
    max_error = max(errors)
    mae = sum(errors) / len(errors)
    if max_error > 1e-3:
        worst = errors.index(max_error)
        raise AssertionError(
            f"Native original Essentia vs Rust Mel mismatch: MAE={mae:.8g}, "
            f"max={max_error:.8g} at patch={worst//(128*96)} "
            f"frame={(worst//96)%128} band={worst%96}"
        )
    print(f"Mel parity PASS: {len(errors)} coefficients across {count} EffNet patches; "
          f"MAE={mae:.8g}, max error={max_error:.8g}")

def main(exe, rust_executable=None):
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "essentia-synthetic-16k-mono.wav"
        with wave.open(str(source), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            samples = (int(13000 * math.sin(2 * math.pi * 440 * i / 16000))
                       for i in range(6 * 16000))
            output.writeframes(struct.pack("<" + "h" * (6 * 16000), *samples))
        with subprocess.Popen(
            [exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as proc:
            hello = exact(proc.stdout, 4)
            if hello != b"EFW1":
                raise RuntimeError(f"Essentia startup handshake mismatch: {hello!r}")
            status, result, decode, mel = request(proc, source)
            assert status == 0 and result[0] == 4, f"Expected 4 patches, got {result[0]}"
            assert max(result[1]) > 0.0
            assert decode > 0 and mel > 0
            if rust_executable:
                compare_to_rust_mel(rust_executable, source, result)
            status, bounded, _, _ = request(proc, source, patch_cap=2)
            assert status == 0 and bounded[0] == 2, "Explicit patch limit ignored"
            status, err, _, _ = request(proc, Path(folder) / "not-a-file.wav")
            assert status == 1 and err, "Missing audio must report an error"
            status, again, _, _ = request(proc, source)
            assert status == 0 and again[0] == 4, "C++ worker did not survive recoverable DSP error"
            proc.stdin.close()
            if proc.wait(timeout=10) != 0:
                raise RuntimeError("Native worker did not exit cleanly: "
                                   + proc.stderr.read().decode("utf8", "replace")[-1000:])
            print("Essentia native C++ smoke PASS: startup, 4 patches, cap, error, reuse")

if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("Usage: python test_native_essentia_protocol.py WORKER_EXECUTABLE [RUST_EXECUTABLE]")
    main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None)
