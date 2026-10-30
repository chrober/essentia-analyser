//! One ONNX session pair per process, reused across the entire music library.
//! The numerical parity of the pre-processing is not yet established.
use anyhow::{bail, Context, Result};
use ort::{session::Session, value::TensorRef};
use std::{collections::BTreeMap, path::{Path, PathBuf}, time::Instant};

use crate::{ffmpeg_pcm_mono_16k, preprocess, sha256_file, Report, Timing, CLASSIFIER, ENCODER, LABELS};

pub struct ModelProfile {
    pub labels: Vec<String>,
    pub hashes: BTreeMap<String, String>,
    pub model_key: String,
    encoder_path: PathBuf,
    classifier_path: PathBuf,
}

impl ModelProfile {
    pub fn load(dir: &Path) -> Result<Self> {
        let encoder_path = dir.join(ENCODER);
        let classifier_path = dir.join(CLASSIFIER);
        for path in [&encoder_path, &classifier_path] {
            if !path.is_file() {
                bail!("Missing ONNX model: {} (run scripts/download-models.ps1)", path.display());
            }
        }
        let metadata = std::fs::read(dir.join(LABELS))
            .context("Could not read MTG-Jamendo classes metadata")?;
        let meta: serde_json::Value = serde_json::from_slice(&metadata)?;
        let labels = meta["classes"].as_array()
            .context("Model metadata has no 'classes' array")?
            .iter()
            .map(|v| v.as_str().map(ToOwned::to_owned).context("Non-string Mood class"))
            .collect::<Result<Vec<String>>>()?;
        if labels.len() != 56 {
            bail!("Expected exactly 56 mood/theme classes");
        }
        let mut hashes = BTreeMap::new();
        hashes.insert(ENCODER.to_owned(), sha256_file(&encoder_path)?);
        hashes.insert(CLASSIFIER.to_owned(), sha256_file(&classifier_path)?);
        let model_key = crate::storage::model_key_for(
            ENCODER, CLASSIFIER, &hashes,
            crate::audio_decode::RUST_PREPROCESSING,
            "arithmetic_mean_of_per_patch_sigmoid_scores",
            &labels,
            false,
        )?;
        Ok(Self { labels, hashes, model_key, encoder_path, classifier_path })
    }
}

pub struct MoodEngine {
    profile: ModelProfile,
    encoder: Session,
    classifier: Session,
    load_secs: f64,
    counted_load: bool,
    threads: usize,
}

fn embedding(session: &mut Session, patch: &[f32]) -> Result<Vec<f32>> {
    let input = TensorRef::from_array_view(([1usize, 128usize, 96usize], patch))?;
    let outputs = session.run(ort::inputs![input])?;
    for output in outputs.values() {
        let (_, tensor) = output.try_extract_tensor::<f32>()?;
        if tensor.len() == 1280 {
            return Ok(tensor.to_vec());
        }
    }
    bail!("EffNet did not output a 1280-dimensional embedding")
}

fn infer_moods(session: &mut Session, vector: &[f32]) -> Result<Vec<f32>> {
    let input = TensorRef::from_array_view(([1usize, 1280usize], vector))?;
    let outputs = session.run(ort::inputs![input])?;
    for output in outputs.values() {
        let (_, tensor) = output.try_extract_tensor::<f32>()?;
        if tensor.len() == 56 && tensor.iter().all(|v| v.is_finite() && (0.0..=1.0).contains(v)) {
            return Ok(tensor.to_vec());
        }
    }
    bail!("Classifier did not output 56 finite sigmoid probabilities")
}

/// Diagnostic-only embedding export, independent of classifier and SQLite.
/// No automatic validation/persistence; the caller must compare with Essentia.
pub fn embeddings_for_parity(
    path: &Path, models_dir: &Path, max_patches: usize, threads: usize,
) -> Result<Vec<Vec<f32>>> {
    if !(1..=64).contains(&max_patches) || threads == 0 {
        bail!("--max-patches must be 1..64 and --threads must be >= 1");
    }
    let encoder_path = models_dir.join(ENCODER);
    if !encoder_path.is_file() {
        bail!("Missing ONNX embedding model: {}", encoder_path.display());
    }
    let audio = ffmpeg_pcm_mono_16k(path)?;
    let mel = preprocess::mel_spectrogram(&audio)?;
    let patches = preprocess::patches(&mel, Some(max_patches))?;
    let env = ort::init().build()?;
    let mut encoder = Session::builder(&env)?
        .with_intra_threads(threads).map_err(|e| anyhow::anyhow!("{e}"))?
        .commit_from_file(&encoder_path)?;
    let mut vectors = Vec::with_capacity(patches.len());
    for patch in patches {
        vectors.push(embedding(&mut encoder, &patch)?);
    }
    Ok(vectors)
}

/// Diagnostic-only 56-class head inference on externally supplied, fixed ONNX
/// embeddings. Using identical inputs in TensorFlow isolates classifier parity.
pub fn classify_embeddings_for_parity(
    input: &[Vec<f32>], models_dir: &Path, threads: usize,
) -> Result<Vec<Vec<f32>>> {
    if input.is_empty() || input.len() > 64 || threads == 0 {
        bail!("Need 1..64 embeddings and at least one inference thread");
    }
    if input.iter().any(|v| v.len() != 1280 || v.iter().any(|x| !x.is_finite())) {
        bail!("Each embedding must have exactly 1280 finite f32 values");
    }
    let classifier_path = models_dir.join(CLASSIFIER);
    if !classifier_path.is_file() {
        bail!("Missing ONNX classification model: {}", classifier_path.display());
    }
    let env = ort::init().build()?;
    let mut classifier = Session::builder(&env)?
        .with_intra_threads(threads).map_err(|e| anyhow::anyhow!("{e}"))?
        .commit_from_file(&classifier_path)?;
    let mut scores = Vec::with_capacity(input.len());
    for vector in input {
        scores.push(infer_moods(&mut classifier, vector)?);
    }
    Ok(scores)
}

impl MoodEngine {
    pub fn new(profile: ModelProfile, threads: usize) -> Result<Self> {
        if threads == 0 {
            bail!("--threads must be >= 1");
        }
        let start = Instant::now();
        let env = ort::init().build()?;
        let encoder = Session::builder(&env)?
            .with_intra_threads(threads).map_err(|e| anyhow::anyhow!("{e}"))?
            .commit_from_file(&profile.encoder_path)?;
        let classifier = Session::builder(&env)?
            .with_intra_threads(threads).map_err(|e| anyhow::anyhow!("{e}"))?
            .commit_from_file(&profile.classifier_path)?;
        Ok(Self {
            profile, encoder, classifier, load_secs: start.elapsed().as_secs_f64(),
            counted_load: false, threads,
        })
    }

    pub fn analyze(&mut self, path: &Path, max_patches: Option<usize>) -> Result<Report> {
        let started = Instant::now();
        let decode_at = Instant::now();
        let samples = ffmpeg_pcm_mono_16k(path)?;
        let decode_seconds = decode_at.elapsed().as_secs_f64();
        let features_at = Instant::now();
        let mel = preprocess::mel_spectrogram(&samples)?;
        let patches = preprocess::patches(&mel, max_patches)?;
        let features_seconds = features_at.elapsed().as_secs_f64();
        let infer_at = Instant::now();
        let count = patches.len();
        let mut sums = vec![0f64; 56];
        for patch in &patches {
            let vector = embedding(&mut self.encoder, patch)?;
            let scores = infer_moods(&mut self.classifier, &vector)?;
            for (sum, value) in sums.iter_mut().zip(scores) {
                *sum += f64::from(value);
            }
        }
        let inference_seconds = infer_at.elapsed().as_secs_f64();
        let model_load_seconds = if self.counted_load { 0.0 } else { self.load_secs };
        self.counted_load = true;
        let scores = self.profile.labels.iter().cloned()
            .zip(sums.iter().map(|value| (value / count as f64) as f32))
            .collect();
        let at_hash = Instant::now();
        let audio_hash = sha256_file(path)?;
        let hash_seconds = at_hash.elapsed().as_secs_f64();
        Ok(Report {
            schema_version: 1,
            preprocessing_version: crate::audio_decode::RUST_PREPROCESSING,
            classification_model: CLASSIFIER,
            embedding_model: ENCODER,
            audio_path: path.display().to_string(),
            audio_sha256: audio_hash,
            models_sha256: self.profile.hashes.clone(),
            sample_rate: preprocess::RATE,
            patches_analyzed: count,
            threads: self.threads,
            aggregation: "arithmetic_mean_of_per_patch_sigmoid_scores",
            validated_against_essentia: false,
            timings: Timing {
                decode_seconds, features_seconds, hash_seconds, model_load_seconds,
                inference_seconds,
                total_seconds: started.elapsed().as_secs_f64() + model_load_seconds,
            },
            scores,
        })
    }
}
