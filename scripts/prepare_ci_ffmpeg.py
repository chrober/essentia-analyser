#!/usr/bin/env python3
"""Expose version-pinned CI-only ffmpeg AND ffprobe without Ubuntu multimedia APT."""
import os
from importlib.metadata import distribution
from pathlib import Path
import shutil
import subprocess

import imageio_ffmpeg


def require_working_binary(binary: Path, name: str) -> str:
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(f"CI {name} is missing or not executable: {binary}")
    output = subprocess.run(
        [str(binary), "-hide_banner", "-version"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    if not output or not output[0].startswith(f"{name} version "):
        raise RuntimeError(f"Unexpected {name} version output from {binary}: {output[:1]}")
    return output[0]


def bundled_ffprobe_for_linux_x64(destination: Path) -> Path:
    """Locate the actual ELF binary in the pinned wheel, not a Python import.

    ffprobe-binaries-only 0.1.2 installs successfully but does not export
    the documented `ffprobe_binaries` module. The wheel RECORD is an
    authoritative manifest of files pip installed.
    """
    dist = distribution("ffprobe-binaries-only")
    files = list(dist.files or [])
    options = []
    for item in files:
        if "ffprobe" not in item.name.lower():
            continue
        path = Path(dist.locate_file(item))
        if not path.is_file() or path.stat().st_size < 1_000_000:
            continue
        with path.open("rb") as handle:
            header = handle.read(20)
        # Require a 64-bit little-endian Linux x86-64 ELF executable.
        if (len(header) == 20 and header[:4] == bytes((0x7F, 0x45, 0x4C, 0x46))
                and header[4] == 2 and header[5] == 1
                and int.from_bytes(header[18:20], "little") == 62):
            options.append(path)
    if len(options) != 1:
        names = [str(item) for item in files if "ffprobe" in str(item).lower()]
        raise RuntimeError(
            f"Expected one Linux x86-64 ffprobe ELF in pinned wheel, "
            f"got {len(options)}: {[str(p) for p in options]}; "
            f"packaged files mentioning ffprobe: {names[:30]}"
        )
    # Copy to a controlled CI-owned path in case the wheel strips mode bits.
    shutil.copy2(options[0], destination)
    destination.chmod(0o755)
    return destination


def main() -> None:
    # imageio-ffmpeg's pinned platform wheel bundles FFmpeg but NOT ffprobe.
    ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    if ffmpeg.parent.name != "binaries":
        raise RuntimeError(f"Expected FFmpeg bundled in imageio-ffmpeg wheel, got {ffmpeg}")
    ffmpeg_version = require_working_binary(ffmpeg, "ffmpeg")
    encoders = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-encoders"],
        check=True, capture_output=True, text=True,
    ).stdout
    for name in ("libmp3lame", "flac"):
        if name not in encoders:
            raise RuntimeError(f"Bundled FFmpeg lacks required audio encoder: {name}")

    # This is the real ffprobe CLI used unchanged by src/audio_decode.rs.
    # Pin its wheel version as an independent CI dependency.
    cli_dir = Path(os.environ["RUNNER_TEMP"]) / "ci-ffmpeg-cli"
    cli_dir.mkdir(parents=True, exist_ok=True)
    ffprobe = bundled_ffprobe_for_linux_x64(cli_dir / "ffprobe")
    ffprobe_version = require_working_binary(ffprobe, "ffprobe")
    (cli_dir / "ffmpeg").symlink_to(ffmpeg)
    with open(os.environ["GITHUB_PATH"], "a", encoding="utf-8") as path_file:
        path_file.write(f"{cli_dir}\n")

    print(f"CI fixture encoder: {ffmpeg_version}")
    print(f"CI audio metadata probe: {ffprobe_version}")
    print(f"Added both commands to PATH for subsequent CI steps: {cli_dir}")


if __name__ == "__main__":
    main()
