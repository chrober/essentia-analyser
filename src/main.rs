mod preprocess;
mod audio_decode;
mod storage;
mod engine;
mod batch;
mod features;
mod song_embedding;
mod essentia_worker;
mod feature_lookup;
mod parallel;
mod resources;

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand};
use serde::Serialize;
use audio_decode::ffmpeg_pcm_mono_16k;
#[cfg(test)]
use audio_decode::essentia_linear_resample;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs::File,
    io::Read,
    path::{Path, PathBuf},
};

const ENCODER: &str = "discogs-effnet-bsdynamic-1.onnx";
const CLASSIFIER: &str = "mtg_jamendo_moodtheme-discogs-effnet-1.onnx";
const LABELS: &str = "mtg_jamendo_moodtheme-discogs-effnet-1.json";

#[derive(Parser)]
#[command(name = "bliss-mood", about = "Experimental ONNX mood analysis (not yet Essentia-validated)")]
struct Cli {
    #[command(subcommand)]
    action: Action,
}

#[derive(Subcommand)]
enum Action {
    /// Classify diagnostic 1280-D embeddings using the ONNX 56-class head.
    /// This command does not read or modify music or SQLite databases.
    ClassifyEmbeddings {
        input_json: PathBuf,
        #[arg(long, default_value = "models")]
        models_dir: PathBuf,
        #[arg(long, default_value_t = 1)]
        threads: usize,
    },
    /// Export first N 1280-D Discogs-EffNet ONNX embeddings for Essentia comparison.
    /// No classifier needed and no SQLite or audio files modified.
    EmbeddingDump {
        source: PathBuf,
        #[arg(long, default_value = "models")]
        models_dir: PathBuf,
        #[arg(long, default_value_t = 4)]
        max_patches: usize,
        #[arg(long, default_value_t = 1)]
        threads: usize,
    },
    /// Export first N raw Mel feature frames for comparison with Essentia.
    /// Does not require ONNX models and never modifies source audio.
    MelDump {
        source: PathBuf,
        #[arg(long, default_value_t = 32)]
        max_frames: usize,
    },
    Analyze {
        /// Source audio file (never modified).
        source: PathBuf,
        #[arg(long, default_value = "models")]
        models_dir: PathBuf,
        /// Limit to N initial patches (for exploratory performance benchmarks).
        #[arg(long)]
        max_patches: Option<usize>,
        /// Limit ONNX internal worker threads. Use 1 for a shared Lyrion host.
        #[arg(long, default_value_t = 1)]
        threads: usize,
        #[arg(long)]
        json: bool,
        /// Optional separate SQLite sidecar to store result (never modifies bliss.db).
        #[arg(long)]
        db: Option<PathBuf>,
        /// Exact TracksV2.File path on the target Lyrion system, required with --db.
        #[arg(long)]
        track_key: Option<String>,
    },
    /// Generic, opt-in classifier inference. All heads share the same 1280D EffNet embeddings.
    AnalyzeFeatures {
        source: PathBuf,
        #[arg(long, default_value = "models")]
        models_dir: PathBuf,
        #[arg(long)]
        registry: Option<PathBuf>,
        /// Comma-separated registry model IDs (e.g. moodtheme,genre,voice).
        #[arg(long, default_value = "moodtheme,genre")]
        models: String,
        /// Explicitly select native C++ Essentia DSP; default preserves Rust/ONNX behavior.
        #[arg(long, default_value = "rust", value_parser = ["rust", "essentia"])]
        audio_backend: String,
        /// Trusted executable for original Essentia C++ DSP subprocess.
        #[arg(long)]
        essentia_worker: Option<PathBuf>,
        /// Hard wall-clock limit per C++ worker request, including first handshake.
        #[arg(long, default_value_t = 900)]
        essentia_timeout_seconds: u64,
        #[arg(long)]
        max_patches: Option<usize>,
        #[arg(long, default_value_t = 1)]
        threads: usize,
        #[arg(long)]
        json: bool,
        #[arg(long)]
        db: Option<PathBuf>,
        #[arg(long)]
        track_key: Option<String>,
    },
    /// Incremental, model-independent sidecar analysis; legacy mood_tracks remain untouched.
    ScanFeatures {
        /// Read exactly one of --bliss-db or --tracks-file.
        #[arg(long, conflicts_with = "tracks_file", required_unless_present = "tracks_file")]
        bliss_db: Option<PathBuf>,
        /// UTF-8 newline-delimited source-relative track identities, no Bliss DB needed.
        #[arg(long, conflicts_with = "bliss_db", requires = "source_root")]
        tracks_file: Option<PathBuf>,
        /// Private directory of opaque, versioned 1280D song embedding JSON exports.
        /// Available only for explicit manifests and never in dry-run.
        #[arg(long, requires = "tracks_file")]
        embedding_dir: Option<PathBuf>,
        #[arg(long)]
        db: PathBuf,
        #[arg(long, default_value = "models")]
        models_dir: PathBuf,
        #[arg(long)]
        registry: Option<PathBuf>,
        #[arg(long, default_value = "moodtheme,genre")]
        models: String,
        #[arg(long, requires = "source_root")]
        library_root: Option<String>,
        #[arg(long)]
        source_root: Option<PathBuf>,
        #[arg(long)]
        only_track: Option<String>,
        /// Maximum newly attempted tracks (successful or failed).
        #[arg(long)]
        max_new: Option<usize>,
        /// Stop a scan after this many errors, instead of walking the whole library.
        #[arg(long, default_value_t = 5)]
        max_errors: usize,
        #[arg(long, default_value_t = 1)]
        threads: usize,
        /// Parallel tracks: auto preserves interactive CPU headroom.
        #[arg(long, default_value = "1")]
        workers: String,
        /// Optional original C++ Essentia frontend per Rust worker (default rust).
        #[arg(long, default_value = "rust", value_parser = ["rust", "essentia"])]
        audio_backend: String,
        /// Trusted native Essentia C++ worker executable.
        #[arg(long)]
        essentia_worker: Option<PathBuf>,
        /// Hard wall-clock limit per native worker song/handshake (1..7200 seconds).
        #[arg(long, default_value_t = 900)]
        essentia_timeout_seconds: u64,
        /// Optional Windows process priority, independent of fixed workers.
        /// Also applies to native Essentia children through CreateProcess flags.
        #[arg(long, value_parser = ["normal", "below-normal", "above-normal"])]
        priority: Option<String>,
        #[arg(long)]
        dry_run: bool,
        #[arg(long)]
        json: bool,
    },
    /// Inspect cached Mood/Genre vectors by exact Bliss file key without
    /// opening source audio, starting ONNX or changing the sidecar SQLite.
    InspectFeatures {
        #[arg(long)]
        db: PathBuf,
        /// Exact TracksV2.File; can be repeated for a bounded candidate batch.
        #[arg(long = "track-key", required = true)]
        track_keys: Vec<String>,
        #[arg(long, default_value = "moodtheme,genre")]
        models: String,
        /// Explicitly expose unvalidated experimental predictions in Lab tests.
        #[arg(long)]
        include_experimental: bool,
        #[arg(long)]
        json: bool,
    },
    /// Compare an arbitrary registered classifier against a reference TF head.
    ClassifyFeatureEmbeddings {
        input_json: PathBuf,
        #[arg(long, default_value = "models")]
        models_dir: PathBuf,
        #[arg(long)]
        registry: Option<PathBuf>,
        #[arg(long, default_value = "genre")]
        model: String,
        #[arg(long, default_value_t = 1)]
        threads: usize,
    },
    /// Compare stored Mood tracks with eligible tracks in an existing Bliss database.
    DbCoverage {
        #[arg(long)]
        db: PathBuf,
        #[arg(long)]
        bliss_db: PathBuf,
        #[arg(long)]
        json: bool,
    },
    /// Incrementally analyze Lyrion's Bliss library into mood.db.
    Scan {
        #[arg(long)]
        bliss_db: PathBuf,
        #[arg(long)]
        db: PathBuf,
        #[arg(long, default_value = "models")]
        models_dir: PathBuf,
        /// Optional prefix from absolute Bliss track paths; OMIT when TracksV2.File is relative.
        #[arg(long, requires = "source_root")]
        library_root: Option<String>,
        /// Music directory on this machine; supports UNC paths on Windows.
        #[arg(long)]
        source_root: Option<PathBuf>,
        /// Process exactly this TracksV2.File key (useful for a single-song smoke test).
        #[arg(long)]
        only_track: Option<String>,
        /// Maximum newly analyzed tracks in this run (useful for Pi/quick tests).
        #[arg(long)]
        max_new: Option<usize>,
        #[arg(long, default_value_t = 1)]
        threads: usize,
        #[arg(long)]
        dry_run: bool,
        #[arg(long)]
        json: bool,
    },
}

#[derive(Serialize)]
struct Timing {
    decode_seconds: f64,
    features_seconds: f64,
    hash_seconds: f64,
    model_load_seconds: f64,
    inference_seconds: f64,
    total_seconds: f64,
}

#[derive(Serialize)]
struct Report {
    schema_version: u32,
    preprocessing_version: &'static str,
    classification_model: &'static str,
    embedding_model: &'static str,
    audio_path: String,
    audio_sha256: String,
    models_sha256: BTreeMap<String, String>,
    sample_rate: usize,
    patches_analyzed: usize,
    threads: usize,
    aggregation: &'static str,
    validated_against_essentia: bool,
    timings: Timing,
    scores: BTreeMap<String, f32>,
}

fn sha256_file(path: &Path) -> Result<String> {
    let mut input = File::open(path).with_context(|| format!("Cannot open {}", path.display()))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let size = input.read(&mut buffer)?;
        if size == 0 {
            break;
        }
        hasher.update(&buffer[..size]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}


fn analyze(
    path: &Path,
    models_dir: &Path,
    max_patches: Option<usize>,
    threads: usize,
) -> Result<Report> {
    if !path.is_file() {
        bail!("Audio file not found: {}", path.display());
    }
    let profile = engine::ModelProfile::load(models_dir)?;
    let mut engine = engine::MoodEngine::new(profile, threads)?;
    engine.analyze(path, max_patches)
}

fn main() -> Result<()> {
    match Cli::parse().action {
        Action::ClassifyEmbeddings { input_json, models_dir, threads } => {
            let diagnostic: serde_json::Value =
                serde_json::from_reader(File::open(&input_json)?)?;
            let vectors: Vec<Vec<f32>> =
                serde_json::from_value(diagnostic["embeddings"].clone())?;
            let scores = engine::classify_embeddings_for_parity(
                &vectors, &models_dir, threads,
            )?;
            let model_metadata: serde_json::Value = serde_json::from_slice(
                &std::fs::read(models_dir.join(LABELS))?,
            )?;
            let classes = model_metadata["classes"].as_array()
                .context("Classifier metadata has no classes list")?;
            if classes.len() != 56 || classes.iter().any(|x| !x.is_string()) {
                bail!("Classifier metadata must contain 56 string class names");
            }
            let mut means = vec![0.0_f64; 56];
            for row in &scores {
                for (sum, value) in means.iter_mut().zip(row) {
                    *sum += *value as f64;
                }
            }
            let means: Vec<f32> = means.into_iter()
                .map(|sum| (sum / scores.len() as f64) as f32).collect();
            let output = serde_json::json!({
                "schema_version": 1,
                "validation_status": "experimental-unvalidated",
                "classification_model": CLASSIFIER,
                "classification_model_sha256": sha256_file(&models_dir.join(CLASSIFIER))?,
                "embedding_model": diagnostic["embedding_model"],
                "embedding_model_sha256": diagnostic["embedding_model_sha256"],
                "patches_classified": scores.len(),
                "classes": classes,
                "scores_per_patch": scores,
                "mean_scores": means,
                "aggregation": "arithmetic_mean_of_per_patch_sigmoid_scores",
            });
            println!("{}", serde_json::to_string(&output)?);
        }
        Action::EmbeddingDump { source, models_dir, max_patches, threads } => {
            let vectors = engine::embeddings_for_parity(
                &source, &models_dir, max_patches, threads,
            )?;
            let output = serde_json::json!({
                "schema_version": 1,
                "validation_status": "experimental-unvalidated",
                "preprocessing_version": audio_decode::RUST_PREPROCESSING,
                "embedding_model": ENCODER,
                "embedding_model_sha256": sha256_file(&models_dir.join(ENCODER))?,
                "audio_sha256": sha256_file(&source)?,
                "patches_analyzed": vectors.len(),
                "embedding_dimensions": 1280,
                "embeddings": vectors,
            });
            println!("{}", serde_json::to_string(&output)?);
        }
        Action::MelDump { source, max_frames } => {
            if max_frames == 0 || max_frames > 1024 {
                bail!("--max-frames must be between 1 and 1024");
            }
            let samples = ffmpeg_pcm_mono_16k(&source)?;
            let mel = preprocess::mel_spectrogram(&samples)?;
            let frame_count = mel.len();
            let output = serde_json::json!({
                "preprocessing_version": audio_decode::RUST_PREPROCESSING,
                "sample_rate": preprocess::RATE,
                "fft_size": preprocess::FFT,
                "hop_size": preprocess::HOP,
                "mel_bands": preprocess::MEL_BANDS,
                "total_frames": frame_count,
                "frames": mel.iter().take(max_frames).map(|frame| frame.as_slice()).collect::<Vec<_>>(),
            });
            println!("{}", serde_json::to_string(&output)?);
        }
        Action::Analyze {
            source,
            models_dir,
            max_patches,
            threads,
            json,
            db,
            track_key,
        } => {
            if db.is_some() != track_key.is_some() {
                bail!("--db and --track-key must be specified together");
            }
            let report = analyze(&source, &models_dir, max_patches, threads)?;
            if let (Some(db_path), Some(key)) = (db.as_deref(), track_key.as_deref()) {
                storage::persist(db_path, key, &report)?;
            }
            if json {
                println!("{}", serde_json::to_string_pretty(&report)?);
            } else {
                println!("{} patches: {}", report.patches_analyzed, report.audio_path);
                let mut sorted: Vec<_> = report.scores.iter().collect();
                sorted.sort_by(|a, b| b.1.total_cmp(a.1));
                for (name, score) in sorted {
                    println!("{name:20} {score:.4}");
                }
                println!(
                    "Inference: {:.3}s; total: {:.3}s",
                    report.timings.inference_seconds, report.timings.total_seconds
                );
            }
        }
        Action::AnalyzeFeatures {
            source, models_dir, registry, models, audio_backend,
            essentia_worker, essentia_timeout_seconds, max_patches, threads, json, db, track_key,
        } => {
            if db.is_some() != track_key.is_some() {
                bail!("--db and --track-key must be specified together");
            }
            let backend = essentia_worker::BackendChoice::from_cli(
                &audio_backend, essentia_worker.as_deref(), essentia_timeout_seconds,
            )?;
            let mut profiles = features::load_profiles(&models_dir, registry.as_deref(), &models)?;
            features::retarget_profiles(&mut profiles, &backend)?;
            let mut engine = features::FeatureEngine::with_backend(profiles, threads, &backend)?;
            let report = engine.analyze(&source, max_patches)?;
            if let (Some(db), Some(key)) = (db.as_deref(), track_key.as_deref()) {
                features::persist(db, key, &report, None)?;
            }
            if json {
                println!("{}", serde_json::to_string_pretty(&report)?);
            } else {
                println!("{} patches: {}", report.patches_analyzed, report.audio_path);
                for (id, result) in &report.classifications {
                    println!("[{id}] {}", result.capability);
                    let mut sorted: Vec<_> = result.scores.iter().collect();
                    sorted.sort_by(|a, b| b.1.total_cmp(a.1));
                    for (name, score) in sorted.into_iter().take(10) {
                        println!("  {name:22} {score:.4}");
                    }
                }
                println!("Total: {:.3}s", report.timings.total_seconds);
            }
        }
        Action::ScanFeatures {
            bliss_db, tracks_file, embedding_dir, db, models_dir, registry, models, library_root,
            source_root, only_track, max_new, max_errors, threads, workers,
            audio_backend, essentia_worker, essentia_timeout_seconds,
            priority, dry_run, json,
        } => {
            if tracks_file.is_some() && library_root.is_some() {
                bail!("--library-root is only supported with --bliss-db");
            }
            let (worker_count, is_auto) = parallel::worker_count(&workers)?;
            if worker_count > 1 && threads > 1 {
                bail!("Parallel --workers requires --threads 1 to prevent ONNX oversubscription");
            }
            let mut priority_report = parallel::configure_scan_priority(
                priority.as_deref(), is_auto, dry_run,
            )?;
            let backend = essentia_worker::BackendChoice::from_cli(
                &audio_backend, essentia_worker.as_deref(), essentia_timeout_seconds,
            )?;
            let mut summary = features::scan(features::ScanOptions {
                bliss_db: bliss_db.as_deref(), tracks_file: tracks_file.as_deref(),
                embedding_dir: embedding_dir.as_deref(),
                db: &db, models_dir: &models_dir,
                registry: registry.as_deref(), models: &models,
                source_root: source_root.as_deref(),
                library_root: library_root.as_deref(),
                only_track: only_track.as_deref(),
                max_new, max_errors, threads, workers: worker_count,
                dry_run, backend,
            })?;
            priority_report.collect_native_workers();
            summary.set_priority_diagnostics(priority_report);
            if json {
                println!("{}", serde_json::to_string_pretty(&summary)?);
            } else {
                println!("{summary:#?}");
            }
            // Same nonzero exit contract as the legacy scanner.
            let result = serde_json::to_value(&summary)?;
            if result["failures"].as_u64().unwrap_or(0) > 0
                || result["missing_files"].as_u64().unwrap_or(0) > 0
            {
                bail!("Feature scan completed with failed or unavailable songs");
            }
        }
        Action::InspectFeatures {
            db, track_keys, models, include_experimental, json,
        } => {
            let found = feature_lookup::inspect(
                &db, &track_keys, &models, include_experimental,
            )?;
            if json {
                println!("{}", serde_json::to_string_pretty(&found)?);
            } else {
                for track in &found {
                    println!("{}", track.track_file);
                    for (id, head) in &track.models {
                        println!("  {id}: {}", head.status);
                    }
                }
            }
        }
        Action::ClassifyFeatureEmbeddings {
            input_json, models_dir, registry, model, threads,
        } => {
            let diagnostic: serde_json::Value =
                serde_json::from_reader(File::open(&input_json)?)?;
            let vectors: Vec<Vec<f32>> =
                serde_json::from_value(diagnostic["embeddings"].clone())?;
            let mut profiles = features::load_profiles(&models_dir, registry.as_deref(), &model)?;
            let output = features::parity_output(&vectors, &profiles.remove(0), threads)?;
            println!("{}", serde_json::to_string(&output)?);
        }
        Action::DbCoverage { db, bliss_db, json } => {
            let result = storage::coverage(&db, &bliss_db)?;
            if json {
                println!("{}", serde_json::to_string_pretty(&result)?);
            } else {
                println!("{result:#?}");
            }
        }
        Action::Scan {
            bliss_db, db, models_dir, library_root, source_root, only_track, max_new, threads, dry_run, json
        } => {
            let summary = batch::scan(batch::ScanOptions {
                bliss_db: &bliss_db,
                mood_db: &db,
                models_dir: &models_dir,
                source_root: source_root.as_deref(),
                library_root: library_root.as_deref(),
                max_new, threads, dry_run,
                only_track: only_track.as_deref(),
            })?;
            if json {
                println!("{}", serde_json::to_string_pretty(&summary)?);
            } else {
                println!("{summary:#?}");
            }
            if summary.failures > 0 || summary.missing_files > 0 {
                bail!("Mood scan completed with {} failures and {} unavailable files",
                    summary.failures, summary.missing_files);
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod manifest_cli_tests {
    use super::{Action, Cli};
    use clap::Parser;

    #[test]
    fn legacy_dynamic_flags_are_rejected_not_silently_ignored() {
        for extra in [
            vec!["--adaptive-workers"],
            vec!["--adaptive-policy", "resource"],
            vec!["--adaptive-policy", "autotune"],
            vec!["--min-workers", "2"],
            vec!["--max-workers", "6"],
            vec!["--adaptive-min-completed-songs", "8"],
        ] {
            let mut args = vec!["bliss-mood", "scan-features",
                "--bliss-db", "cohort.db", "--db", "features.db"];
            args.extend(extra);
            assert!(Cli::try_parse_from(args).is_err());
        }
    }

    #[test]
    fn fixed_worker_cli_keeps_opt_in_auto_and_priority() {
        for workers in ["1", "2", "4", "auto"] {
            for priority in ["normal", "below-normal", "above-normal"] {
                let args = ["bliss-mood", "scan-features",
                    "--bliss-db", "cohort.db", "--db", "features.db",
                    "--workers", workers, "--priority", priority];
                let cli = Cli::try_parse_from(args).unwrap();
                match cli.action {
                    Action::ScanFeatures { workers: selected, priority: p, .. } => {
                        assert_eq!(selected, workers);
                        assert_eq!(p.as_deref(), Some(priority));
                    }
                    _ => panic!("Expected feature scan"),
                }
            }
        }
        assert!(Cli::try_parse_from([
            "bliss-mood", "scan-features", "--bliss-db", "cohort.db",
            "--db", "features.db", "--priority", "realtime",
        ]).is_err());
        let cli = Cli::try_parse_from([
            "bliss-mood", "scan-features", "--bliss-db", "cohort.db",
            "--db", "features.db",
        ]).unwrap();
        assert!(matches!(cli.action, Action::ScanFeatures { workers, .. } if workers == "1"));
    }

    #[test]
    fn source_selection_is_exclusive_and_manifest_requires_root() {
        let valid = Cli::try_parse_from([
            "bliss-mood", "scan-features", "--tracks-file", "cohort.txt",
            "--source-root", "music", "--db", "features.db",
            "--workers", "2", "--threads", "1"
        ]).unwrap();
        match valid.action {
            Action::ScanFeatures { bliss_db, tracks_file, .. } => {
                assert!(bliss_db.is_none());
                assert_eq!(tracks_file.unwrap(), std::path::PathBuf::from("cohort.txt"));
            }
            _ => panic!("Expected scan-features"),
        }
        assert!(Cli::try_parse_from([
            "bliss-mood", "scan-features", "--db", "features.db",
        ]).is_err());
        assert!(Cli::try_parse_from([
            "bliss-mood", "scan-features", "--tracks-file", "cohort.txt", "--db", "features.db",
        ]).is_err());
        assert!(Cli::try_parse_from([
            "bliss-mood", "scan-features", "--tracks-file", "cohort.txt",
            "--source-root", "music", "--bliss-db", "bliss.db", "--db", "features.db",
        ]).is_err());
        assert!(Cli::try_parse_from([
            "bliss-mood", "scan-features", "--bliss-db", "bliss.db", "--db", "features.db",
        ]).is_ok());
    }
}

#[cfg(test)]
mod pcm_tests {
    use super::essentia_linear_resample;

    #[test]
    fn identity_resampling_preserves_pcm() {
        assert_eq!(essentia_linear_resample(&[0.25, -0.3], 16000), vec![0.25, -0.3]);
    }
    #[test]
    fn streaming_linear_phase_matches_first_sample_rule() {
        let s = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0];
        let y = essentia_linear_resample(&s, 32000);
        assert_eq!(y.len(), 3);
        assert_eq!(y, vec![0.0, 1.0, 3.0]);
    }
    #[test]
    fn stereo_average_remains_unscaled() {
        let stereo = [0.2f32, 0.6f32];
        assert!((0.5 * (stereo[0] + stereo[1]) - 0.4).abs() < 1e-6);
    }
}

