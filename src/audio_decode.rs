//! Shared Rust audio decoder used by both the production Rust-ONNX frontend
//! and the standalone (ONNX-free) native Essentia DSP parity harness.
//! This isolates the exact reference DSP behavior without duplicating it.
use crate::preprocess;

/// Cache identity for the corrected original libsamplerate SRC_LINEAR phase.
/// Historical Rust v4 sidecars must stay distinct and never be reused here.
pub(crate) const RUST_PREPROCESSING: &str = "experimental-essentia-audio-v5-f32-src-ratio-unvalidated";
use anyhow::{bail, Context, Result};
use std::{path::Path, process::Command as ProcessCommand};

/// Match Essentia MonoLoader(resampleQuality=4) rather than FFmpeg's default
/// downmix and sample-rate converter.  Essentia averages stereo samples at
/// 0.5/0.5 and its streaming Resample uses libsamplerate SRC_LINEAR (quality 4).
pub(crate) fn essentia_linear_resample(samples: &[f32], input_rate: usize) -> Vec<f32> {
    if input_rate == preprocess::RATE {
        return samples.to_vec();
    }
    if samples.is_empty() {
        return Vec::new();
    }
    let count = samples.len().saturating_mul(preprocess::RATE).div_ceil(input_rate);
    // Essentia streaming::Resample computes src_ratio in essentia::Real
    // (float32), then passes that *rounded* ratio to libsamplerate SRC_LINEAR.
    // Using mathematically exact input_rate/16000 here shifts the interpolation
    // phase progressively on real music (up to >1 source sample over a long
    // track). Reproduce Essentia's float32 ratio before reciprocal conversion.
    // Keep the existing output length until streaming end-of-input is compared
    // independently; the Mel patch-count invariant is already verified.
    let src_ratio = preprocess::RATE as f32 / input_rate as f32;
    let step = 1.0_f64 / f64::from(src_ratio);
    let mut result = Vec::with_capacity(count);
    for n in 0..count {
        // libsamplerate's streaming SRC_LINEAR: first sample at 0; thereafter
        // the interpolation phase is (n * inputRate/outputRate) - 1.
        // The previous sample is retained between input blocks.
        let p = if n == 0 { 0.0 } else { n as f64 * step - 1.0 };
        if p <= 0.0 {
            result.push(samples[0]);
        } else {
            let left = (p.floor() as usize).min(samples.len() - 1);
            let right = (left + 1).min(samples.len() - 1);
            let fraction = p - left as f64;
            result.push((samples[left] as f64
                + fraction * (samples[right] as f64 - samples[left] as f64)) as f32);
        }
    }
    result
}

pub(crate) fn ffmpeg_pcm_mono_16k(input: &Path) -> Result<Vec<f32>> {
    // FFmpeg only decodes to float PCM at the *native* sample rate.
    // Probe stream metadata once to avoid FFmpeg's different default
    // channel weights and its incompatible sample-rate conversion.
    let probe = ProcessCommand::new("ffprobe")
        .args(["-v", "error", "-select_streams", "a:0",
               "-show_entries", "stream=sample_rate,channels", "-of", "json"])
        .arg(input).output()
        .context("ffprobe not found; install the full FFmpeg distribution")?;
    if !probe.status.success() {
        bail!("ffprobe failed: {}", String::from_utf8_lossy(&probe.stderr));
    }
    let metadata: serde_json::Value = serde_json::from_slice(&probe.stdout)?;
    let first = &metadata["streams"][0];
    let input_rate: usize = first["sample_rate"]
        .as_str().context("Missing source sample rate")?.parse()?;
    let channels = first["channels"].as_u64().context("Missing channel count")? as usize;
    if input_rate == 0 || !(1..=2).contains(&channels) {
        bail!("Unsupported input audio layout: {channels} channels, {input_rate} Hz");
    }
    let output = ProcessCommand::new("ffmpeg")
        .args(["-hide_banner", "-nostdin", "-loglevel", "error", "-i"])
        .arg(input)
        .args(["-map", "0:a:0", "-vn", "-acodec", "pcm_f32le",
               "-f", "f32le", "pipe:1"])
        .output()
        .context("FFmpeg not found; install FFmpeg and add it to PATH")?;
    if !output.status.success() {
        bail!("FFmpeg failed: {}", String::from_utf8_lossy(&output.stderr));
    }
    if output.stdout.len() % (4 * channels) != 0 || output.stdout.is_empty() {
        bail!("FFmpeg produced empty or malformed f32 PCM");
    }
    let samples: Vec<f32> = output.stdout.as_chunks::<4>().0.iter()
        .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]])).collect();
    let mono: Vec<f32> = if channels == 2 {
        samples.as_chunks::<2>().0.iter().map(|c| 0.5 * (c[0] + c[1])).collect()
    } else {
        samples
    };
    Ok(essentia_linear_resample(&mono, input_rate))
}

#[cfg(test)]
mod tests {
    use super::essentia_linear_resample;

    #[test]
    fn src_linear_matches_upstream_libsamplerate_float32_ratio_on_twelve_seconds() {
        // SRC_LINEAR 4, mono 44,100 -> 16,000 Hz; reference values were
        // generated with original libsamplerate src_simple (not from our Rust
        // implementation) using the deterministic full-length input below.
        // Exact-ratio f64 resampling fails this regression by ~0.00146.
        const RATE: usize = 44_100;
        let input: Vec<f32> = (0..RATE * 12)
            .map(|n| {
                let t = n as f64 / RATE as f64;
                (0.7 * (2.0 * std::f64::consts::PI * 300.0 * t).sin()
                    + 0.1 * (2.0 * std::f64::consts::PI * 2453.0 * t).sin()
                    + 0.1 * (2.0 * std::f64::consts::PI * 3650.0 * t).sin()) as f32
            })
            .collect();
        let output = essentia_linear_resample(&input, RATE);
        assert_eq!(output.len(), 192_000);
        // libsamplerate can return one trailing terminal frame on this exact
        // boundary; check matching frames, not its separate EOF behavior.
        let reference = [
            (1, 0.186_830_77_f32),
            (160, 0.035_811_3_f32),
            (65_535, -0.542_090_36_f32),
            (100_000, 0.113_633_87_f32),
            (160_000, -0.115_302_905_f32),
            (191_999, -0.298_430_03_f32),
        ];
        for (index, native) in reference {
            let difference = (output[index] - native).abs();
            assert!(
                difference < 2e-5,
                "SRC_LINEAR mismatch at output sample {index}:                  Rust={} native={native} delta={difference}",
                output[index],
            );
        }
    }

    #[test]
    fn unchanged_rate_is_exact_identity() {
        let samples = [0.25_f32, -0.3_f32, 0.4_f32];
        assert_eq!(essentia_linear_resample(&samples, 16_000), samples);
    }
}
