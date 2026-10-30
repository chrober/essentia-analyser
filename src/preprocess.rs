//! Experimental approximation of Essentia TensorflowInputMusiCNN.
//! Correctness against Essentia is an explicit validation gate.
use anyhow::{bail, Result};
use rustfft::{num_complex::Complex32, FftPlanner};
use std::f64::consts::PI;

pub const RATE: usize = 16_000;
pub const FFT: usize = 512;
pub const HOP: usize = 256;
pub const MEL_BANDS: usize = 96;
pub const PATCH_FRAMES: usize = 128;
pub const PATCH_HOP: usize = 62;

fn hz_to_mel(hz: f64) -> f64 {
    let linear = hz / (200.0 / 3.0);
    if hz < 1000.0 {
        linear
    } else {
        1000.0 / (200.0 / 3.0) + (hz / 1000.0).ln() / (6.4_f64.ln() / 27.0)
    }
}

fn mel_to_hz(mel: f64) -> f64 {
    let cutoff = 1000.0 / (200.0 / 3.0);
    if mel < cutoff {
        mel * (200.0 / 3.0)
    } else {
        1000.0 * ((mel - cutoff) * (6.4_f64.ln() / 27.0)).exp()
    }
}

/// Slaney-style triangular filterbank, mirroring librosa's `norm="slaney"`.
fn mel_filters() -> Vec<Vec<f32>> {
    let high = hz_to_mel((RATE / 2) as f64);
    let hz: Vec<f64> = (0..MEL_BANDS + 2)
        .map(|i| mel_to_hz(high * i as f64 / (MEL_BANDS + 1) as f64))
        .collect();
    (0..MEL_BANDS)
        .map(|band| {
            let (left, center, right) = (hz[band], hz[band + 1], hz[band + 2]);
            let norm = 2.0 / (right - left);
            (0..=FFT / 2)
                .map(|bin| {
                    let f = bin as f64 * RATE as f64 / FFT as f64;
                    let a = (f - left) / (center - left);
                    let b = (right - f) / (right - center);
                    (a.min(b).max(0.0) * norm) as f32
                })
                .collect()
        })
        .collect()
}

/// Frame-centered Hann STFT and power-Mel, then log10(1 + 10_000 * mel).
/// The original Essentia implementation may differ in padding/normalisation.
pub fn mel_spectrogram(samples: &[f32]) -> Result<Vec<[f32; MEL_BANDS]>> {
    if samples.is_empty() {
        bail!("Audio contains no samples");
    }
    let filters = mel_filters();
    // Essentia TensorflowPredictEffnetDiscogs::padSignal counts valid frames as
    // 1 + ceil((nSamples - FFT/2) / HOP); with FFT=2*HOP this reduces
    // to ceil(nSamples/HOP). In particular, do not add an extra frame
    // when nSamples is an exact multiple of HOP.
    let frames = samples.len().div_ceil(HOP);
    let mut planner = FftPlanner::<f32>::new();
    let fft = planner.plan_fft_forward(FFT);
    let mut spectrum = vec![Complex32::new(0.0, 0.0); FFT];
    let mut out = Vec::with_capacity(frames);
    for frame in 0..frames {
        for (i, v) in spectrum.iter_mut().enumerate() {
            let idx = frame as isize * HOP as isize + i as isize - (FFT / 2) as isize;
            let sample = if idx >= 0 && (idx as usize) < samples.len() {
                samples[idx as usize]
            } else {
                0.0
            };
            // Essentia Windowing defaults to symmetric=true, so the Hann denominator is N-1.
            let hann = (0.5 - 0.5 * (2.0 * PI * i as f64 / (FFT - 1) as f64).cos()) as f32;
            *v = Complex32::new(sample * hann, 0.0);
        }
        fft.process(&mut spectrum);
        let power: Vec<f32> = spectrum
            .iter()
            .take(FFT / 2 + 1)
            .map(|v| v.norm_sqr())
            .collect();
        let mut band_frame = [0.0f32; MEL_BANDS];
        for (band, weights) in filters.iter().enumerate() {
            let energy: f32 = weights.iter().zip(&power).map(|(w, p)| w * p).sum();
            band_frame[band] = (1.0 + 10_000.0 * energy.max(0.0)).log10();
        }
        out.push(band_frame);
    }
    Ok(out)
}

/// Individual patches, each in row-major [128,96] layout.
pub fn patches(mel: &[[f32; MEL_BANDS]], limit: Option<usize>) -> Result<Vec<Vec<f32>>> {
    if mel.len() < PATCH_FRAMES {
        bail!("Audio is too short for the 128-frame model input (requires approx. 2.1 seconds)");
    }
    if limit == Some(0) {
        bail!("--max-patches must be >= 1");
    }
    let mut out = Vec::new();
    for start in (0..=mel.len() - PATCH_FRAMES).step_by(PATCH_HOP) {
        let mut flat = Vec::with_capacity(PATCH_FRAMES * MEL_BANDS);
        for row in &mel[start..start + PATCH_FRAMES] {
            flat.extend_from_slice(row);
        }
        out.push(flat);
        if out.len() == limit.unwrap_or(usize::MAX) {
            break;
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_audio_gives_zero_mel() {
        let v = mel_spectrogram(&vec![0.0; 3 * RATE]).unwrap();
        assert!(v.iter().flatten().all(|x| *x == 0.0));
        assert_eq!(patches(&v, None).unwrap()[0].len(), PATCH_FRAMES * MEL_BANDS);
    }

    #[test]
    fn sine_audio_has_finite_mel() {
        let v: Vec<_> = (0..3 * RATE)
            .map(|i| (2.0 * std::f32::consts::PI * 440.0 * i as f32 / RATE as f32).sin())
            .collect();
        let mel = mel_spectrogram(&v).unwrap();
        assert!(mel.iter().flatten().all(|v| v.is_finite() && *v >= 0.0));
        assert!(mel.iter().flatten().any(|x| *x > 0.0));
    }

    #[test]
    fn exact_hop_length_does_not_add_spurious_final_patch() {
        // 6 seconds at 16 kHz is exactly 375 hops of 256 samples.
        // Official Essentia reports 4 patches for this signal.
        let mel = mel_spectrogram(&vec![0.0; 6 * RATE]).unwrap();
        assert_eq!(mel.len(), 375);
        assert_eq!(patches(&mel, None).unwrap().len(), 4);
    }

    #[test]
    fn short_audio_is_rejected() {
        let v = mel_spectrogram(&vec![0.0; RATE / 2]).unwrap();
        assert!(patches(&v, None).is_err());
    }

    #[test]
    fn patch_limit_is_honored() {
        let v = mel_spectrogram(&vec![0.0; 10 * RATE]).unwrap();
        assert_eq!(patches(&v, Some(2)).unwrap().len(), 2);
        assert!(patches(&v, Some(0)).is_err());
    }
}
