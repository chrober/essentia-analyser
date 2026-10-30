//! Research-only, standalone song representation; never a classifier score vector.
//! All pooling arithmetic is f64 in the original patch order and quantized once to f32.
use anyhow::{bail, Context, Result};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{
    fs::OpenOptions,
    io::{BufWriter, Write},
    path::Path,
    sync::atomic::{AtomicU64, Ordering},
};

pub const DIMENSIONS: usize = 1280;
pub const POOLING: &str = "patch_f64_arithmetic_mean_v1";
pub const NORMALIZATION: &str = "song_f64_l2_then_cast_f32_v1";

#[derive(Debug, Serialize)]
pub struct SongEmbedding {
    pub schema_version: u32,
    pub kind: &'static str,
    pub validation_status: &'static str,
    pub dimension: usize,
    pub patches_analyzed: usize,
    pub encoder_model: String,
    pub encoder_sha256: String,
    pub preprocessing_version: String,
    pub pooling_version: &'static str,
    pub normalization_version: &'static str,
    pub representation_fingerprint: String,
    pub audio_sha256: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub track_file: Option<String>,
    pub vector_f32: Vec<f32>,
}

/// A f64 accumulation of raw (not patch-normalized) encoder vectors.
pub fn add_patch(sums: &mut [f64], patch: &[f32]) -> Result<()> {
    if sums.len() != DIMENSIONS || patch.len() != DIMENSIONS {
        bail!("Encoder dimension mismatch (expected {DIMENSIONS})");
    }
    for (sum, value) in sums.iter_mut().zip(patch.iter()) {
        if !value.is_finite() {
            bail!("Non-finite encoder embedding component");
        }
        *sum += f64::from(*value);
        if !sum.is_finite() {
            bail!("Non-finite pooled embedding accumulation");
        }
    }
    Ok(())
}

/// Arithmetic mean in f64, L2 normalization in f64, one final f32 rounding.
/// Reject empty, non-finite and zero-norm vectors rather than emitting NaNs.
pub fn finish(sums: &[f64], patches: usize) -> Result<Vec<f32>> {
    if sums.len() != DIMENSIONS || patches == 0 || sums.iter().any(|x| !x.is_finite()) {
        bail!("Invalid embedding sums or empty patch cohort");
    }
    let means: Vec<f64> = sums.iter().map(|sum| sum / patches as f64).collect();
    let norm2: f64 = means.iter().map(|x| x * x).sum();
    if !norm2.is_finite() || norm2 <= 0.0 {
        bail!("Zero-norm or non-finite pooled embedding");
    }
    let norm = norm2.sqrt();
    let vector: Vec<f32> = means.iter().map(|x| (x / norm) as f32).collect();
    if vector.iter().any(|x| !x.is_finite()) {
        bail!("Invalid normalized embedding");
    }
    Ok(vector)
}

pub fn build(
    sums: &[f64], patches: usize, encoder_model: &str, encoder_sha256: &str,
    preprocessing: &str, audio_sha256: &str,
) -> Result<SongEmbedding> {
    for (name, hash) in [("encoder", encoder_sha256), ("audio", audio_sha256)] {
        if hash.len() != 64 || !hash.bytes().all(|c| c.is_ascii_hexdigit()) {
            bail!("Invalid {name} SHA256");
        }
    }
    if encoder_model.is_empty() || preprocessing.is_empty() {
        bail!("Encoder model and preprocessing version required");
    }
    let vector_f32 = finish(sums, patches)?;
    // Identity binds exact weights + preprocessing + pooling + normalization,
    // independently of classification-head weights and their class ordering.
    let contract = serde_json::to_vec(&(
        1_u32, encoder_model, encoder_sha256, preprocessing, POOLING, NORMALIZATION, DIMENSIONS
    ))?;
    let representation_fingerprint = format!("{:x}", Sha256::digest(&contract));
    Ok(SongEmbedding {
        schema_version: 1,
        kind: "discogs_effnet_song_embedding",
        validation_status: "experimental_unvalidated",
        dimension: DIMENSIONS,
        patches_analyzed: patches,
        encoder_model: encoder_model.to_owned(),
        encoder_sha256: encoder_sha256.to_owned(),
        preprocessing_version: preprocessing.to_owned(),
        pooling_version: POOLING,
        normalization_version: NORMALIZATION,
        representation_fingerprint,
        audio_sha256: audio_sha256.to_owned(),
        track_file: None,
        vector_f32,
    })
}

/// Publish a complete JSON with atomic no-overwrite semantics.
/// The sibling temporary file and the target are on the same filesystem;
/// the final hard link is atomic and refuses any existing target. A crash may
/// leave a *.partial file, never an incomplete published *.json.
pub fn write_new(path: &Path, embedding: &SongEmbedding) -> Result<()> {
    static SEQUENCE: AtomicU64 = AtomicU64::new(0);
    let attempt = SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let temp = path.with_extension(format!(
        "json.{}.{}.partial", std::process::id(), attempt,
    ));
    let file = OpenOptions::new().write(true).create_new(true).open(&temp)
        .with_context(|| format!("Cannot stage song embedding {}", temp.display()))?;
    let result = (|| {
        let mut writer = BufWriter::new(file);
        serde_json::to_writer(&mut writer, embedding)?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        drop(writer);
        std::fs::hard_link(&temp, path)
            .with_context(|| format!(
                "Refusing existing output or filesystem without hard-link support: {}",
                path.display(),
            ))?;
        Ok(())
    })();
    // Success: unlink the staging name; target retains the same data.
    // Failure: preserve any pre-existing target, never publish partial JSON.
    std::fs::remove_file(&temp).ok();
    result
}


/// Stable, opaque JSON filename: no music or artist identity in the filename.
pub fn track_output_path(folder: &Path, track: &str) -> std::path::PathBuf {
    folder.join(format!("{:x}.json", Sha256::digest(track.as_bytes())))
}

fn fingerprint(model: &str, encoder_sha: &str, preprocessing: &str) -> Result<String> {
    let contract = serde_json::to_vec(&(
        1_u32, model, encoder_sha, preprocessing, POOLING, NORMALIZATION, DIMENSIONS
    ))?;
    Ok(format!("{:x}", Sha256::digest(&contract)))
}

/// Cache is valid only with an exact encoder / frontend / song fingerprint.
/// If a file exists but is corrupted, fail closed instead of silently replacing it.
pub fn cached_matches(
    path: &Path, track: &str, audio_sha: &str, patches: usize,
    model: &str, encoder_sha: &str, preprocessing: &str,
) -> Result<bool> {
    if !path.exists() { return Ok(false); }
    let size = std::fs::metadata(path)?.len();
    if !(1..=200_000).contains(&size) {
        bail!("Existing song embedding has invalid file size");
    }
    let data: serde_json::Value =
        serde_json::from_reader(std::fs::File::open(path)?)?;
    let exact = data["schema_version"] == 1
        && data["kind"] == "discogs_effnet_song_embedding"
        && data["validation_status"] == "experimental_unvalidated"
        && data["dimension"].as_u64() == Some(DIMENSIONS as u64)
        && data["patches_analyzed"].as_u64() == Some(patches as u64)
        && data["track_file"].as_str() == Some(track)
        && data["audio_sha256"].as_str() == Some(audio_sha)
        && data["encoder_model"].as_str() == Some(model)
        && data["encoder_sha256"].as_str() == Some(encoder_sha)
        && data["preprocessing_version"].as_str() == Some(preprocessing)
        && data["pooling_version"] == POOLING
        && data["normalization_version"] == NORMALIZATION
        && data["representation_fingerprint"].as_str()
            == Some(fingerprint(model, encoder_sha, preprocessing)?.as_str());
    if !exact { bail!("Existing song embedding has incompatible provenance"); }
    let vector: Vec<f32> = serde_json::from_value(data["vector_f32"].clone())?;
    if vector.len() != DIMENSIONS || vector.iter().any(|v| !v.is_finite()) {
        bail!("Existing song embedding vector is malformed");
    }
    let magnitude = vector.iter()
        .map(|v| f64::from(*v).powi(2)).sum::<f64>().sqrt();
    if !magnitude.is_finite() || (magnitude - 1.0).abs() >= 1e-5 {
        bail!("Existing song embedding vector is not L2 normalized");
    }
    Ok(true)
}

/// Existing output from a prior partial run may be reused only if byte-level
/// JSON semantics match a fresh deterministic analysis. Never overwrite.
pub fn write_or_verify(path: &Path, embedding: &SongEmbedding) -> Result<()> {
    if !path.exists() { return write_new(path, embedding); }
    let existing: serde_json::Value =
        serde_json::from_reader(std::fs::File::open(path)?)?;
    // Round through the same JSON wire representation; f32 decimal encoding
    // must not be compared against a different internal f64 conversion.
    let expected: serde_json::Value =
        serde_json::from_slice(&serde_json::to_vec(embedding)?)?;
    if existing != expected {
        bail!("Refusing to replace an existing incompatible song embedding");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hashed_name_and_cached_vector_metadata_round_trip() {
        let dir = std::env::temp_dir().join(format!(
            "embedding-cache-{}-{}", std::process::id(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
                .unwrap().as_nanos()
        ));
        std::fs::create_dir(&dir).unwrap();
        let mut sum = vec![0.0; DIMENSIONS];
        sum[0] = 1.0;
        let track = "Artist/Test/song.flac";
        let mut embedding = build(&sum, 1, "encoder.onnx", &"a".repeat(64),
            "frontend-v5", &"b".repeat(64)).unwrap();
        embedding.track_file = Some(track.to_owned());
        let path = track_output_path(&dir, track);
        assert!(!path.to_string_lossy().contains("Artist"));
        assert!(!cached_matches(&path, track, &"b".repeat(64), 1,
            "encoder.onnx", &"a".repeat(64), "frontend-v5").unwrap());
        write_or_verify(&path, &embedding).unwrap();
        assert!(write_new(&path, &embedding).is_err());
        assert_eq!(std::fs::read_dir(&dir).unwrap().count(), 1);
        write_or_verify(&path, &embedding).unwrap();
        assert!(cached_matches(&path, track, &"b".repeat(64), 1,
            "encoder.onnx", &"a".repeat(64), "frontend-v5").unwrap());
        assert!(cached_matches(&path, track, &"c".repeat(64), 1,
            "encoder.onnx", &"a".repeat(64), "frontend-v5").is_err());
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn identical_patches_and_scaling_are_invariant() {
        let mut a = vec![0.0; DIMENSIONS];
        let mut b = vec![0.0; DIMENSIONS];
        let mut patch = vec![0_f32; DIMENSIONS];
        patch[0] = 3.0;
        patch[1] = 4.0;
        add_patch(&mut a, &patch).unwrap();
        add_patch(&mut b, &patch).unwrap();
        add_patch(&mut b, &patch).unwrap();
        assert_eq!(finish(&a, 1).unwrap(), finish(&b, 2).unwrap());
        let result = finish(&a, 1).unwrap();
        assert!((result[0] - 0.6).abs() < 1e-6);
        assert!((result[1] - 0.8).abs() < 1e-6);
    }

    #[test]
    fn reject_zero_cancelled_nonfinite_and_invalid_dimensions() {
        let zero = vec![0.0; DIMENSIONS];
        assert!(finish(&zero, 1).is_err());
        assert!(finish(&zero, 0).is_err());
        assert!(finish(&zero[..2], 1).is_err());
        let mut accum = vec![0.0; DIMENSIONS];
        let mut patch = vec![0_f32; DIMENSIONS];
        patch[12] = f32::NAN;
        assert!(add_patch(&mut accum, &patch).is_err());
        patch[12] = f32::INFINITY;
        assert!(add_patch(&mut accum, &patch).is_err());
        patch[12] = 1.0;
        add_patch(&mut accum, &patch).unwrap();
        patch[12] = -1.0;
        add_patch(&mut accum, &patch).unwrap();
        assert!(finish(&accum, 2).is_err());
    }

    #[test]
    fn rounding_is_deterministic_and_fingerprint_is_weight_sensitive() {
        let mut sums = vec![0.0; DIMENSIONS];
        sums[0] = 1.0;
        sums[1] = -0.25;
        let a = build(&sums, 1, "encoder.onnx", &"a".repeat(64), "frontend-v1", &"f".repeat(64)).unwrap();
        let b = build(&sums, 1, "encoder.onnx", &"a".repeat(64), "frontend-v1", &"f".repeat(64)).unwrap();
        let c = build(&sums, 1, "encoder.onnx", &"b".repeat(64), "frontend-v1", &"f".repeat(64)).unwrap();
        assert_eq!(a.vector_f32, b.vector_f32);
        assert_eq!(a.representation_fingerprint, b.representation_fingerprint);
        assert_ne!(a.representation_fingerprint, c.representation_fingerprint);
        let length = a.vector_f32.iter().map(|v| f64::from(*v).powi(2)).sum::<f64>().sqrt();
        assert!((length - 1.0).abs() < 1e-6);
    }
}
