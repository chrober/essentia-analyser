"""Produce deterministic copyright-free audio fixtures at different formats/rates.

These are musical *test signals*, NOT recordings of real songs or quality labels.
Only Python stdlib + ffmpeg are used.
"""
import math
import struct
import subprocess
import wave
from pathlib import Path

out_dir = Path("fixtures")
out_dir.mkdir(exist_ok=True)


def create(name, rate, duration, stereo):
    n_samples = round(duration * rate)
    with wave.open(str(out_dir / name), "wb") as wf:
        wf.setnchannels(2 if stereo else 1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        # The test includes a changing bass line, percussive transients,
        # amplitude modulation, stereo differences and a deliberately
        # non-hop-aligned tail.
        block = bytearray()
        for n in range(n_samples):
            t = n / rate
            beat = t % 0.46
            bass = [110, 146.83, 164.81, 123.47][int(t / 1.65) % 4]
            envelope = math.exp(-beat * 10)
            low = 0.17 * math.sin(2 * math.pi * bass * t)
            melody = 0.22 * math.sin(2 * math.pi * (330 + 35 * math.sin(t * 2)) * t)
            drums = 0.13 * envelope * math.sin(2 * math.pi * 2000 * t)
            left = low + melody + drums
            right = low + 0.6 * melody - 0.6 * drums
            for v in (left, right) if stereo else ((left + right) * 0.5,):
                block.extend(struct.pack("<h", round(max(-1, min(1, v)) * 32767)))
            if len(block) >= 65536:
                wf.writeframesraw(block)
                block.clear()
        if block:
            wf.writeframesraw(block)


create("mono-16k.wav", 16000, 8.729, False)
create("stereo-44100.wav", 44100, 9.113, True)
for codec, ext, extra in [
    ("flac", "flac", []),
    ("libmp3lame", "mp3", ["-q:a", "2"]),
]:
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(out_dir / "stereo-44100.wav"),
         "-c:a", codec, *extra, str(out_dir / f"stereo-44100.{ext}")],
        check=True,
    )
print("Generated fixtures:", [(p.name, p.stat().st_size) for p in sorted(out_dir.glob("*"))])
