"""Compare Essentia MonoLoader PCM with FFmpeg and linear resampling.

Pure diagnostic: no TF models, ONNX weights, audio upload or database access.
"""
import json
import subprocess
from pathlib import Path
import numpy as np
from essentia.standard import MonoLoader


def decode_with_ffmpeg(path, rate):
    pcm = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(path),
         "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(rate),
         "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(pcm, dtype="<f4").astype(np.float64)


def decode_with_explicit_pan(path, rate):
    pcm = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(path),
         "-map", "0:a:0", "-vn",
         "-af", "pan=mono|c0=0.5*c0+0.5*c1",
         "-ar", str(rate), "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(pcm, dtype="<f4").astype(np.float64)


def diffs(a, b):
    n = min(len(a), len(b))
    a = a[:n]
    b = b[:n]
    return dict(samples_a=len(a), samples_b=len(b),
                mean_absolute_error=float(np.mean(np.abs(a-b))),
                max_absolute_error=float(np.max(np.abs(a-b))))


def best_lag(a, b, max_lag=24):
    results = []
    for lag in range(-max_lag, max_lag+1):
        if lag >= 0:
            a_slice, b_slice = a[lag:], b
        else:
            a_slice, b_slice = a, b[-lag:]
        n = min(len(a_slice), len(b_slice), 40000)
        if n > 0:
            results.append((float(np.mean(np.abs(a_slice[:n] - b_slice[:n]))), lag))
    return dict(zip(("mae", "lag"), min(results)))


for path in [Path("fixtures/stereo-44100.wav"), Path("fixtures/stereo-44100.flac"),
             Path("fixtures/stereo-44100.mp3"), Path("fixtures/mono-16k.wav")]:
    in_rate = 44100 if "44100" in path.name else 16000
    ffmpeg_native = decode_with_ffmpeg(path, in_rate)
    essence_native = MonoLoader(filename=str(path), sampleRate=in_rate, resampleQuality=4)()
    ffmpeg_16k = decode_with_ffmpeg(path, 16000)
    essence_16k = MonoLoader(filename=str(path), sampleRate=16000, resampleQuality=4)()
    x = np.arange(len(ffmpeg_native), dtype=np.float64)
    pos = np.arange(len(essence_16k), dtype=np.float64) * in_rate / 16000
    linear = np.interp(pos, x, ffmpeg_native, left=0., right=0.)
    if in_rate == 44100:
        ffmpeg_pan_native = decode_with_explicit_pan(path, 44100)
        ffmpeg_pan_16k = decode_with_explicit_pan(path, 16000)
        pan_native = diffs(ffmpeg_pan_native, essence_native)
        pan_16k = diffs(ffmpeg_pan_16k, essence_16k)
        pan_linear = np.interp(
            np.arange(len(essence_16k), dtype=np.float64) * in_rate / 16000,
            np.arange(len(ffmpeg_pan_native), dtype=np.float64),
            ffmpeg_pan_native, left=0, right=0)
        pan_interp = diffs(pan_linear, essence_16k)
        lag_pan = best_lag(ffmpeg_pan_16k, essence_16k)
        lag_pan_linear = best_lag(pan_linear, essence_16k)
        # Search phase offset in units of source samples (44.1 kHz).
        # Sample up to 30k points to keep this fast on CI.
        step = in_rate / 16000
        count = min(30000, len(essence_16k))
        shifts = np.arange(-8, 8.01, 0.125)
        fits = [(float(np.mean(np.abs(
                    np.interp(np.arange(count) * step + shift,
                              np.arange(len(ffmpeg_pan_native)), ffmpeg_pan_native,
                              left=0, right=0) - essence_16k[:count]))),float(shift))
                for shift in shifts]
        optimal_src_shift = dict(zip(("mae", "input_samples_shift"), min(fits)))
        fit = float(np.dot(ffmpeg_native, essence_native) / np.dot(ffmpeg_native, ffmpeg_native))
    else:
        pan_native = pan_16k = pan_interp = lag_pan = lag_pan_linear = optimal_src_shift = None
        fit = 1.0
    report = {
        "ffmpeg_default_to_essentia_gain": fit,
        "explicit_pan_native": pan_native,
        "explicit_pan_16k": pan_16k,
        "explicit_pan_linear_16k": pan_interp,
        "explicit_pan_lag": lag_pan,
        "explicit_pan_linear_lag": lag_pan_linear,
        "best_fractional_input_shift": optimal_src_shift,
        "file": path.name,
        "input_rate": in_rate,
        "lengths": dict(ffmpeg_native=len(ffmpeg_native),essentia_native=len(essence_native),
                        ffmpeg_16k=len(ffmpeg_16k),essentia_16k=len(essence_16k)),
        "native_mono": diffs(ffmpeg_native, essence_native),
        "resample_ffmpeg": diffs(ffmpeg_16k, essence_16k),
        "resample_numpy_linear": diffs(linear, essence_16k),
        "best_lag_ffmpeg": best_lag(ffmpeg_16k, essence_16k),
        "best_lag_linear": best_lag(linear, essence_16k),
    }
    print(json.dumps(report, indent=2))
