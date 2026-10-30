//! Opt-in, capability-based classification heads sharing one EffNet embedding pass.
//! No source music or Bliss database is ever opened for writing.
use anyhow::{bail, Context, Result};
use ort::{session::Session, value::TensorRef};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, HashSet},
    path::{Component, Path, PathBuf},
    time::Instant,
};

use crate::{ffmpeg_pcm_mono_16k, preprocess, sha256_file, storage, Timing};
use crate::essentia_worker::{BackendChoice, EssentiaWorker};

const PREPROCESSING: &str = crate::audio_decode::RUST_PREPROCESSING;
const AGGREGATION: &str = "arithmetic_mean_of_per_patch_sigmoid_scores";
const SOFTMAX_AGGREGATION: &str = "arithmetic_mean_of_per_patch_softmax_scores";

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OutputType {
    #[default]
    Sigmoid,
    Softmax,
}

impl OutputType {
    fn aggregation(self) -> &'static str {
        match self {
            Self::Sigmoid => AGGREGATION,
            Self::Softmax => SOFTMAX_AGGREGATION,
        }
    }
}

fn valid_head_scores(values: &[f32], count: usize, kind: OutputType) -> bool {
    if values.len() != count || !values.iter().all(|v| v.is_finite() && (0.0..=1.0).contains(v)) {
        return false;
    }
    kind != OutputType::Softmax
        || (values.iter().map(|v| f64::from(*v)).sum::<f64>() - 1.0).abs() <= 1e-3
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Descriptor {
    id: String,
    capability: String,
    embedding_model: String,
    classification_model: String,
    metadata: String,
    embedding_dimensions: usize,
    expected_classes: usize,
    #[serde(default)]
    output_type: OutputType,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Registry {
    schema_version: u32,
    models: Vec<Descriptor>,
}

#[derive(Clone, Debug)]
pub struct Profile {
    descriptor: Descriptor,
    labels: Vec<String>,
    encoder_path: PathBuf,
    head_path: PathBuf,
    hashes: BTreeMap<String, String>,
    pub model_key: String,
}

fn safe_model_name(name: &str) -> bool {
    let path = Path::new(name);
    name.len() <= 180
        && !name.chars().any(|c| matches!(c, '/' | '\\' | ':' | '\0'))
        && path.components().count() == 1
        && matches!(path.components().next(), Some(Component::Normal(_)))
        && name != "." && name != ".."
}

pub fn load_profiles(
    models_dir: &Path, registry_path: Option<&Path>, selected: &str,
) -> Result<Vec<Profile>> {
    let source = match registry_path {
        Some(file) => std::fs::read_to_string(file)
            .with_context(|| format!("Cannot read model registry {}", file.display()))?,
        None => include_str!("../model-registry.json").to_owned(),
    };
    let registry: Registry = serde_json::from_str(&source)?;
    if ![1, 2].contains(&registry.schema_version) || registry.models.is_empty() {
        bail!("Expected nonempty model registry schema_version 1 or 2");
    }
    let ids: Vec<_> = selected.split(',').map(str::trim).collect();
    if ids.is_empty() || ids.iter().any(|id| id.is_empty()) {
        bail!("--models requires comma-separated nonempty model IDs");
    }
    let mut profiles = Vec::new();
    let mut unique = HashSet::new();
    for id in ids {
        if !unique.insert(id.to_owned()) {
            bail!("Duplicate selected model: {id}");
        }
        let descriptor = registry.models.iter().find(|x| x.id == id)
            .with_context(|| format!("Unknown model '{id}' in registry"))?.clone();
        if !safe_model_name(&descriptor.embedding_model)
            || !safe_model_name(&descriptor.classification_model)
            || !safe_model_name(&descriptor.metadata)
            || descriptor.id.trim().is_empty()
            || descriptor.capability.trim().is_empty()
            || !(1..=2048).contains(&descriptor.expected_classes)
            || descriptor.embedding_dimensions != 1280
        {
            bail!("Unsupported or unsafe model registry descriptor for '{id}'");
        }
        if profiles.first().is_some_and(|first: &Profile| {
            first.descriptor.embedding_model != descriptor.embedding_model
        }) {
            bail!("Selected heads require different encoders; analyze them separately");
        }
        let encoder_path = models_dir.join(&descriptor.embedding_model);
        let head_path = models_dir.join(&descriptor.classification_model);
        let metadata_path = models_dir.join(&descriptor.metadata);
        for file in [&encoder_path, &head_path, &metadata_path] {
            if !file.is_file() {
                bail!("Missing model file {} (run scripts/download-models.ps1)", file.display());
            }
        }
        let metadata: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&metadata_path)?)?;
        let labels: Vec<String> = metadata["classes"].as_array()
            .context("Model metadata must contain 'classes' array")?
            .iter()
            .map(|x| x.as_str().map(str::to_owned).context("Invalid nonstring class label"))
            .collect::<Result<_>>()?;
        if labels.len() != descriptor.expected_classes
            || labels.iter().any(|s| s.is_empty())
            || labels.iter().collect::<HashSet<_>>().len() != labels.len()
        {
            bail!("Invalid number of unique labels for '{id}'");
        }
        // Cross-check declared semantics with official JSON metadata when present.
        if let Some(outputs) = metadata["schema"]["outputs"].as_array() {
            for output in outputs {
                if output["output_purpose"].as_str() == Some("predictions") {
                    let expected = match descriptor.output_type {
                        OutputType::Sigmoid => "Sigmoid",
                        OutputType::Softmax => "Softmax",
                    };
                    if output["op"].as_str() != Some(expected) {
                        bail!("Output type/metadata mismatch for '{id}': expected {expected}");
                    }
                }
            }
        }
        let hashes = BTreeMap::from([
            (descriptor.embedding_model.clone(), sha256_file(&encoder_path)?),
            (descriptor.classification_model.clone(), sha256_file(&head_path)?),
        ]);
        let model_key = storage::model_key_for(
            &descriptor.embedding_model, &descriptor.classification_model,
            &hashes, PREPROCESSING, descriptor.output_type.aggregation(), &labels, false,
        )?;
        profiles.push(Profile {
            descriptor, labels, encoder_path, head_path, hashes, model_key,
        });
    }
    Ok(profiles)
}

/// Profile model keys must differ for alternative preprocessing code and each
/// exact native-worker binary. Never alias the default Rust frontend cache.
pub fn retarget_profiles(profiles: &mut [Profile], backend: &BackendChoice) -> Result<()> {
    if let Some(worker_hash) = backend.worker_hash() {
        for profile in profiles {
            profile.hashes.insert(
                "essentia_cpp_worker_binary_sha256".to_owned(),
                worker_hash.to_owned(),
            );
            if let Some(deployment_hash) = backend.deployment_hash() {
                profile.hashes.insert(
                    "essentia_cpp_native_deployment_manifest_sha256".to_owned(),
                    deployment_hash.to_owned(),
                );
            }
            profile.model_key = storage::model_key_for(
                &profile.descriptor.embedding_model,
                &profile.descriptor.classification_model,
                &profile.hashes,
                backend.preprocessing(),
                profile.descriptor.output_type.aggregation(),
                &profile.labels, false,
            )?;
        }
    }
    Ok(())
}

#[derive(Clone, Serialize)]
pub struct ClassificationResult {
    pub capability: String,
    pub output_type: OutputType,
    pub aggregation: &'static str,
    pub embedding_model: String,
    pub classification_model: String,
    pub models_sha256: BTreeMap<String, String>,
    pub model_key: String,
    pub validated_against_essentia: bool,
    pub scores: BTreeMap<String, f32>,
}

#[derive(Serialize)]
pub struct FeatureReport {
    pub schema_version: u32,
    pub preprocessing_version: &'static str,
    pub aggregation: &'static str,
    pub audio_path: String,
    pub audio_sha256: String,
    pub sample_rate: usize,
    pub patches_analyzed: usize,
    pub threads: usize,
    pub timings: Timing,
    pub classifications: BTreeMap<String, ClassificationResult>,
}

pub struct FeatureEngine {
    encoder: Session,
    heads: Vec<(Profile, Session)>,
    embedding_enabled: bool,
    last_song_embedding: Option<crate::song_embedding::SongEmbedding>,
    load_secs: f64,
    counted_load: bool,
    threads: usize,
    frontend: Option<EssentiaWorker>,
    preprocessing: &'static str,
}

fn classify(session: &mut Session, vector: &[f32], count: usize, kind: OutputType) -> Result<Vec<f32>> {
    let input = TensorRef::from_array_view(([1usize, 1280usize], vector))?;
    let outputs = session.run(ort::inputs![input])?;
    for output in outputs.values() {
        let (_, values) = output.try_extract_tensor::<f32>()?;
        if valid_head_scores(values, count, kind) {
            return Ok(values.to_vec());
        }
    }
    bail!("Classifier did not output {count} valid {kind:?} scores")
}

/// ONNX Runtime permits only one Environment per process (even with
/// multiple independent Sessions). Hold it for process lifetime so workers
/// cannot race the ort::init().build() singleton check.
fn feature_environment() -> Result<&'static ort::environment::Environment> {
    static ENV: std::sync::OnceLock<Result<ort::environment::Environment, String>> =
        std::sync::OnceLock::new();
    let initialized = ENV.get_or_init(|| ort::init().build().map_err(|err| err.to_string()));
    initialized.as_ref().map_err(|err| anyhow::anyhow!(
        "ONNX Runtime process-wide initialization failed: {err}"
    ))
}

impl FeatureEngine {
    #[allow(dead_code)] // Retain legacy constructor for code paths using the Rust frontend.
    pub fn new(profiles: Vec<Profile>, threads: usize) -> Result<Self> {
        Self::with_backend(profiles, threads, &BackendChoice::Rust)
    }

    pub fn with_backend(
        profiles: Vec<Profile>, threads: usize, backend: &BackendChoice,
    ) -> Result<Self> {
        if profiles.is_empty() || threads == 0 {
            bail!("At least one model and one inference thread required");
        }
        let started = Instant::now();
        let env = feature_environment()?;
        let encoder = Session::builder(env)?
            .with_intra_threads(threads)
            .map_err(|e| anyhow::anyhow!("{e}"))?
            .commit_from_file(&profiles[0].encoder_path)?;
        let mut heads = Vec::new();
        for profile in profiles {
            let session = Session::builder(env)?
                .with_intra_threads(threads)
                .map_err(|e| anyhow::anyhow!("{e}"))?
                .commit_from_file(&profile.head_path)?;
            heads.push((profile, session));
        }
        let frontend = match backend {
            BackendChoice::Rust => None,
            BackendChoice::Essentia { executable, timeout_seconds, .. } =>
                Some(EssentiaWorker::with_timeout(
                    executable.clone(), std::time::Duration::from_secs(*timeout_seconds),
                )),
        };
        Ok(Self { encoder, heads, load_secs: started.elapsed().as_secs_f64(),
            counted_load: false, threads, frontend,
            embedding_enabled: false, last_song_embedding: None,
            preprocessing: backend.preprocessing() })
    }

    /// An opt-in f64 pooled 1280D song embedding. Legacy scans never enable it.
    pub fn request_song_embedding(&mut self) {
        self.embedding_enabled = true;
    }

    pub fn take_song_embedding(&mut self) -> Option<crate::song_embedding::SongEmbedding> {
        self.last_song_embedding.take()
    }

    pub fn analyze(&mut self, path: &Path, max_patches: Option<usize>) -> Result<FeatureReport> {
        self.last_song_embedding = None;
        if !path.is_file() {
            bail!("Audio file does not exist: {}", path.display());
        }
        let started = Instant::now();
        let (patches, decode_seconds, features_seconds) = match self.frontend.as_mut() {
            Some(worker) => {
                let native = worker.analyze(path, max_patches)?;
                (native.patches, native.decode_seconds, native.features_seconds)
            }
            None => {
                let at = Instant::now();
                let audio = ffmpeg_pcm_mono_16k(path)?;
                let decode_seconds = at.elapsed().as_secs_f64();
                let at = Instant::now();
                let mel = preprocess::mel_spectrogram(&audio)?;
                let patches = preprocess::patches(&mel, max_patches)?;
                (patches, decode_seconds, at.elapsed().as_secs_f64())
            }
        };
        let count = patches.len();
        let mut embedding_sums = self.embedding_enabled
            .then(|| vec![0.0_f64; crate::song_embedding::DIMENSIONS]);
        let mut sums: Vec<Vec<f64>> = self.heads.iter()
            .map(|(profile, _)| vec![0.0; profile.labels.len()]).collect();
        let at = Instant::now();
        for patch in &patches {
            let input = TensorRef::from_array_view(([1usize, 128usize, 96usize], patch.as_slice()))?;
            let outputs = self.encoder.run(ort::inputs![input])?;
            let mut vector = None;
            for output in outputs.values() {
                let (_, tensor) = output.try_extract_tensor::<f32>()?;
                if tensor.len() == 1280 {
                    vector = Some(tensor.to_vec());
                    break;
                }
            }
            let vector = vector.context("EffNet did not output a 1280-dimensional embedding")?;
            if let Some(ref mut embedding_sums) = embedding_sums {
                crate::song_embedding::add_patch(embedding_sums, &vector)?;
            }
            for (i, (profile, session)) in self.heads.iter_mut().enumerate() {
                let scores = classify(session, &vector, profile.labels.len(), profile.descriptor.output_type)?;
                for (sum, value) in sums[i].iter_mut().zip(scores) {
                    *sum += f64::from(value);
                }
            }
        }
        let inference_seconds = at.elapsed().as_secs_f64();
        let model_load_seconds = if self.counted_load { 0.0 } else { self.load_secs };
        self.counted_load = true;
        let mut classifications = BTreeMap::new();
        for ((profile, _), sums) in self.heads.iter().zip(sums) {
            let scores = profile.labels.iter().cloned()
                .zip(sums.into_iter().map(|v| (v / count as f64) as f32))
                .collect();
            classifications.insert(profile.descriptor.id.clone(), ClassificationResult {
                capability: profile.descriptor.capability.clone(),
                output_type: profile.descriptor.output_type,
                aggregation: profile.descriptor.output_type.aggregation(),
                embedding_model: profile.descriptor.embedding_model.clone(),
                classification_model: profile.descriptor.classification_model.clone(),
                models_sha256: profile.hashes.clone(),
                model_key: profile.model_key.clone(),
                validated_against_essentia: false,
                scores,
            });
        }
        let at_hash = Instant::now();
        let audio_hash = sha256_file(path)?;
        if let Some(ref embedding_sums) = embedding_sums {
            let profile = &self.heads[0].0;
            let model = &profile.descriptor.embedding_model;
            let model_sha = profile.hashes.get(model)
                .context("No encoder SHA256 for embedding export")?;
            self.last_song_embedding = Some(crate::song_embedding::build(
                embedding_sums, count, model, model_sha, self.preprocessing, &audio_hash,
            )?);
        }
        let hash_seconds = at_hash.elapsed().as_secs_f64();
        Ok(FeatureReport {
            schema_version: 3, preprocessing_version: self.preprocessing,
            aggregation: AGGREGATION,
            audio_path: path.display().to_string(),
            audio_sha256: audio_hash,
            sample_rate: preprocess::RATE,
            patches_analyzed: count, threads: self.threads,
            timings: Timing {
                decode_seconds, features_seconds, hash_seconds, model_load_seconds,
                inference_seconds,
                total_seconds: started.elapsed().as_secs_f64() + model_load_seconds,
            },
            classifications,
        })
    }
}

pub fn classify_embeddings(
    vectors: &[Vec<f32>], profile: &Profile, threads: usize,
) -> Result<Vec<Vec<f32>>> {
    if vectors.is_empty() || vectors.len() > 64 || threads == 0
        || vectors.iter().any(|v| v.len() != 1280 || v.iter().any(|x| !x.is_finite()))
    {
        bail!("Need 1..64 finite 1280D embeddings and valid thread count");
    }
    let env = feature_environment()?;
    let mut head = Session::builder(env)?
        .with_intra_threads(threads)
        .map_err(|e| anyhow::anyhow!("{e}"))?
        .commit_from_file(&profile.head_path)?;
    vectors.iter().map(|v| classify(&mut head, v, profile.labels.len(), profile.descriptor.output_type)).collect()
}

pub fn parity_output(
    vectors: &[Vec<f32>], profile: &Profile, threads: usize,
) -> Result<serde_json::Value> {
    let rows = classify_embeddings(vectors, profile, threads)?;
    let mut means = vec![0.0f64; profile.labels.len()];
    for row in &rows {
        for (mean, score) in means.iter_mut().zip(row) {
            *mean += f64::from(*score);
        }
    }
    let means: Vec<f32> = means.into_iter()
        .map(|x| (x / rows.len() as f64) as f32).collect();
    Ok(serde_json::json!({
        "schema_version": 2,
        "validation_status": "experimental-unvalidated",
        "classification_model": profile.descriptor.classification_model,
        "classification_model_sha256": profile.hashes[&profile.descriptor.classification_model],
        "patches_classified": rows.len(),
        "classes": profile.labels,
        "scores_per_patch": rows,
        "mean_scores": means,
        "aggregation": profile.descriptor.output_type.aggregation(),
        "output_type": profile.descriptor.output_type,
    }))
}

/// Versioned model-independent scores; never changes the legacy mood_tracks table.
pub fn persist(
    db_path: &Path, track_key: &str, report: &FeatureReport,
    state: Option<(i64, i64)>,
) -> Result<()> {
    let mut conn = storage::open_scan_db(db_path)?;
    persist_into(&mut conn, track_key, report, state)
}

fn persist_into(
    conn: &mut Connection, track_key: &str, report: &FeatureReport,
    state: Option<(i64, i64)>,
) -> Result<()> {
    if track_key.is_empty() || track_key.trim() != track_key || track_key.contains('\0') {
        bail!("Invalid exact Bliss track key");
    }
    if report.patches_analyzed == 0 || report.audio_sha256.len() != 64
        || !report.audio_sha256.bytes().all(|b| b.is_ascii_hexdigit())
        || report.classifications.is_empty()
    {
        bail!("Malformed feature report");
    }
    let tx = conn.transaction()?;
    for (id, classifier) in &report.classifications {
        if classifier.aggregation != classifier.output_type.aggregation() {
            bail!("Output type/aggregation mismatch for {id}");
        }
        if id.is_empty() || classifier.scores.is_empty()
            || classifier.scores.len() > 2048
            || !valid_head_scores(
                &classifier.scores.values().copied().collect::<Vec<_>>(),
                classifier.scores.len(), classifier.output_type,
            )
        {
            bail!("Malformed classification results for {id}");
        }
        let labels: Vec<String> = classifier.scores.keys().cloned().collect();
        let key = storage::model_key_for(
            &classifier.embedding_model, &classifier.classification_model,
            &classifier.models_sha256, report.preprocessing_version,
            classifier.aggregation, &labels, classifier.validated_against_essentia,
        )?;
        if key != classifier.model_key {
            bail!("Model fingerprint mismatch for {id}");
        }
        tx.execute(
            "INSERT OR IGNORE INTO feature_models
               (model_key, embedding_model, classification_model, models_sha256_json,
                preprocessing_version, aggregation, classes_json, validated_against_essentia)
             VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
            params![key, classifier.embedding_model, classifier.classification_model,
                serde_json::to_string(&classifier.models_sha256)?,
                report.preprocessing_version, classifier.aggregation,
                serde_json::to_string(&labels)?, classifier.validated_against_essentia],
        )?;
        let scores: Vec<u8> = classifier.scores.values()
            .flat_map(|value| value.to_le_bytes()).collect();
        tx.execute(
            "INSERT INTO feature_tracks
                (track_file, model_id, capability, audio_sha256, model_key, scores_f32_le, patches_analyzed)
             VALUES(?1,?2,?3,?4,?5,?6,?7)
             ON CONFLICT(track_file, model_id) DO UPDATE SET
               capability=excluded.capability, audio_sha256=excluded.audio_sha256,
               model_key=excluded.model_key, scores_f32_le=excluded.scores_f32_le,
               patches_analyzed=excluded.patches_analyzed, analyzed_at=CURRENT_TIMESTAMP",
            params![track_key, id, classifier.capability, report.audio_sha256,
                key, scores, report.patches_analyzed as i64],
        )?;
        tx.execute("DELETE FROM feature_track_state WHERE track_file=?1 AND model_id=?2",
            params![track_key, id])?;
        if let Some((size, modified)) = state {
            tx.execute(
                "INSERT INTO feature_track_state(track_file,model_id,file_size,modified_ns,model_key)
                 VALUES(?1,?2,?3,?4,?5)",
                params![track_key, id, size, modified, key],
            )?;
        }
    }
    tx.commit()?;
    Ok(())
}

fn is_current(
    conn: &Connection, track_key: &str, profiles: &[Profile], state: (i64, i64),
) -> Result<bool> {
    if conn.pragma_query_value(None, "user_version", |row| row.get::<_, i64>(0))? < 3 {
        return Ok(false);
    }
    for profile in profiles {
        let found: i64 = conn.query_row(
            "SELECT count(*) FROM feature_track_state s
               JOIN feature_tracks t ON t.track_file=s.track_file AND t.model_id=s.model_id
             WHERE s.track_file=?1 AND s.model_id=?2 AND s.file_size=?3 AND s.modified_ns=?4
               AND s.model_key=?5 AND t.model_key=?5",
            params![track_key, profile.descriptor.id, state.0, state.1, profile.model_key],
            |row| row.get(0),
        )?;
        if found != 1 { return Ok(false); }
    }
    Ok(true)
}

#[derive(Debug, Serialize)]
pub struct ScanSummary {
    model_ids: Vec<String>,
    workers: usize,
    bliss_tracks: usize,
    checked: usize,
    up_to_date: usize,
    pending: usize,
    analyzed: usize,
    missing_files: usize,
    failures: usize,
    limit_reached: bool,
    elapsed_seconds: f64,
    model_sessions_initialized: bool,
    experimental_results: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    priority: Option<crate::parallel::PriorityDiagnostics>,
    #[serde(skip_serializing_if = "Option::is_none")]
    diagnostics: Option<ScanDiagnostics>,
}


impl ScanSummary {
    pub fn set_priority_diagnostics(&mut self, report: crate::parallel::PriorityDiagnostics) {
        self.priority = Some(report);
    }
}

#[derive(Debug, Default, Serialize)]
struct ScanDiagnostics {
    /// Baseline captured before starting any scan worker; separate from
    /// the controller's later completion-driven resource samples.
    baseline: Option<crate::resources::ScanResourceBaseline>,
    /// Sum of per-song timings; overlapping workers mean these totals are NOT
    /// wall-clock durations or exclusive CPU time.
    completed_songs: usize,
    cumulative_decode_seconds: f64,
    cumulative_features_seconds: f64,
    cumulative_inference_seconds: f64,
    cumulative_hash_seconds: f64,
    cumulative_model_load_seconds: f64,
    cumulative_song_seconds: f64,
    system_load_samples: usize,
    system_cpu_average_percent: Option<f64>,
    system_cpu_max_percent: Option<f64>,
    system_ram_max_percent: Option<f64>,
    /// Minimum available physical RAM seen at resource sampling points.
    system_available_ram_min_mib: Option<f64>,
    process_working_set_max_mib: Option<f64>,
    process_private_bytes_max_mib: Option<f64>,
    /// Observed high-water estimate for the Rust process plus registered
    /// Essentia worker subprocesses. Shared pages may be counted twice.
    process_tree_working_set_max_mib: Option<f64>,
    process_tree_private_bytes_max_mib: Option<f64>,
    native_child_working_set_max_mib: Option<f64>,
    native_child_private_bytes_max_mib: Option<f64>,
    native_child_processes_max: usize,
    /// Transient child exits may race with resource enumeration: samples
    /// missing child counters are recorded but not treated as complete.
    process_tree_incomplete_samples: usize,
    /// Difference between first and last sampled Windows page-fault counter.
    /// Includes soft faults; is NOT disk page-ins or paging-file I/O.
    process_page_fault_delta: Option<u64>,
    #[serde(skip)]
    #[cfg_attr(not(windows), allow(dead_code))]
    process_first_page_fault_count: Option<u64>,
    initial_workers: usize,
    logical_cpu_capacity: usize,
    /// Effective pool capacity after limits and bounded cohort size.
    configured_max_workers: usize,
    final_workers: usize,
    peak_workers: usize,
    /// Max number of jobs dispatched but not yet collected by coordinator.
    peak_in_flight: usize,
    /// Actual worker threads inside a song's analysis path simultaneously.
    peak_active_analyses: usize,
    #[serde(skip)]
    cpu_sum: f64,
}

impl ScanDiagnostics {
    fn add(&mut self, report: &FeatureReport) {
        let t = &report.timings;
        self.completed_songs += 1;
        self.cumulative_decode_seconds += t.decode_seconds;
        self.cumulative_features_seconds += t.features_seconds;
        self.cumulative_inference_seconds += t.inference_seconds;
        self.cumulative_hash_seconds += t.hash_seconds;
        self.cumulative_model_load_seconds += t.model_load_seconds;
        self.cumulative_song_seconds += t.total_seconds;
    }

    fn sample(&mut self, load: crate::resources::LoadSample) {
        self.system_load_samples += 1;
        self.cpu_sum += load.system_cpu_percent;
        self.system_cpu_average_percent =
            Some(self.cpu_sum / self.system_load_samples as f64);
        self.system_cpu_max_percent = Some(self.system_cpu_max_percent
            .unwrap_or(0.0).max(load.system_cpu_percent));
        self.system_ram_max_percent = Some(self.system_ram_max_percent
            .unwrap_or(0.0).max(load.system_ram_percent));
        if let Some(process) = crate::resources::process_memory_diagnostics() {
            self.process_working_set_max_mib = Some(self.process_working_set_max_mib
                .unwrap_or(0.0).max(process.working_set_mib));
            self.process_private_bytes_max_mib = Some(self.process_private_bytes_max_mib
                .unwrap_or(0.0).max(process.private_bytes_mib));
            #[cfg(windows)]
            {
                let first = *self.process_first_page_fault_count
                    .get_or_insert(process.page_fault_count);
                self.process_page_fault_delta =
                    Some(process.page_fault_count.wrapping_sub(first));
            }
        }
        if let Some(tree) = crate::resources::process_tree_memory_diagnostics() {
            self.native_child_processes_max =
                self.native_child_processes_max.max(tree.registered_children);
            if tree.complete {
                self.process_tree_working_set_max_mib = Some(
                    self.process_tree_working_set_max_mib.unwrap_or(0.0)
                        .max(tree.total_working_set_mib));
                self.process_tree_private_bytes_max_mib = Some(
                    self.process_tree_private_bytes_max_mib.unwrap_or(0.0)
                        .max(tree.total_private_bytes_mib));
                self.native_child_working_set_max_mib = Some(
                    self.native_child_working_set_max_mib.unwrap_or(0.0)
                        .max(tree.child_working_set_mib));
                self.native_child_private_bytes_max_mib = Some(
                    self.native_child_private_bytes_max_mib.unwrap_or(0.0)
                        .max(tree.child_private_bytes_mib));
            } else {
                self.process_tree_incomplete_samples += 1;
            }
        }
        if let Some(memory) = crate::resources::memory_diagnostics() {
            self.system_available_ram_min_mib = Some(self.system_available_ram_min_mib
                .map_or(memory.available_physical_mib, |previous|
                    previous.min(memory.available_physical_mib)));
        }
    }
}

pub struct ScanOptions<'a> {
    pub bliss_db: Option<&'a Path>,
    pub tracks_file: Option<&'a Path>,
    pub embedding_dir: Option<&'a Path>,
    pub db: &'a Path,
    pub models_dir: &'a Path,
    pub registry: Option<&'a Path>,
    pub models: &'a str,
    pub source_root: Option<&'a Path>,
    pub library_root: Option<&'a str>,
    pub only_track: Option<&'a str>,
    pub max_new: Option<usize>,
    pub max_errors: usize,
    pub threads: usize,
    pub workers: usize,
    pub dry_run: bool,
    pub backend: BackendChoice,
}

/// Keep explicit research cohorts independent of Bliss's catalog while using
/// the same scanner, worker scheduling and SQLite persistence code.
fn read_track_manifest(path: &Path) -> Result<Vec<String>> {
    use std::io::Read;
    const MAX_MANIFEST_BYTES: u64 = 32 * 1024 * 1024;
    let file = std::fs::File::open(path)
        .with_context(|| format!("Cannot open track manifest {}", path.display()))?;
    let mut content = String::new();
    file.take(MAX_MANIFEST_BYTES + 1).read_to_string(&mut content)
        .with_context(|| format!("Cannot read UTF-8 track manifest {}", path.display()))?;
    if content.len() as u64 > MAX_MANIFEST_BYTES {
        bail!("Track manifest exceeds 32 MiB input limit");
    }
    let mut tracks = Vec::new();
    let mut unique = HashSet::new();
    for (index, raw) in content.lines().enumerate() {
        let key = raw.strip_suffix('\r').unwrap_or(raw);
        if key.is_empty() { continue; }
        if key.trim() != key || key.chars().any(|c| matches!(c, '\\' | ':' | '\0'))
            || key.starts_with('/')
            || key.split('/').any(|part| part.is_empty() || part == "." || part == "..")
        {
            bail!("Unsafe manifest track identity on line {}", index + 1);
        }
        if !unique.insert(key.to_owned()) {
            bail!("Duplicate manifest track identity on line {}", index + 1);
        }
        if tracks.len() >= 100_000 {
            bail!("Track manifest exceeds the 100000-song safety limit");
        }
        tracks.push(key.to_owned());
    }
    if tracks.is_empty() {
        bail!("Track manifest contains no song identities");
    }
    Ok(tracks)
}

fn selected_tracks(options: &ScanOptions<'_>) -> Result<Vec<String>> {
    let mut tracks = match (options.bliss_db, options.tracks_file) {
        (Some(db), None) => storage::bliss_files(db)?,
        (None, Some(manifest)) => {
            let root = options.source_root.context("--tracks-file requires --source-root")?;
            if options.library_root.is_some() {
                bail!("--library-root is incompatible with --tracks-file");
            }
            let root_real = std::fs::canonicalize(root)
                .context("Cannot resolve manifest --source-root")?;
            let tracks = read_track_manifest(manifest)?;
            // Deny any existing symlink that escapes the permitted local audio root.
            // Unavailable files are handled by the scanner's usual missing-file policy.
            for track in &tracks {
                let path = crate::batch::source_path(track, None, Some(root))?;
                if let Ok(resolved) = std::fs::canonicalize(&path) {
                    if !resolved.starts_with(&root_real) {
                        bail!("Manifest track resolves outside --source-root");
                    }
                }
            }
            tracks
        }
        _ => bail!("Specify exactly one of --bliss-db and --tracks-file"),
    };
    if let Some(exact) = options.only_track {
        tracks.retain(|key| key == exact);
        if tracks.is_empty() {
            bail!("Exact --only-track not found in selected tracks");
        }
    }
    Ok(tracks)
}

fn is_scan_complete(
    conn: &Connection, track: &str, profiles: &[Profile], state: (i64, i64),
    embedding_dir: Option<&Path>, preprocessing: &str,
) -> Result<bool> {
    if !is_current(conn, track, profiles, state)? { return Ok(false); }
    let Some(dir) = embedding_dir else { return Ok(true); };
    let profile = &profiles[0];
    let model = &profile.descriptor.embedding_model;
    let encoder_sha = profile.hashes.get(model)
        .context("Encoder SHA256 missing from model metadata")?;
    let (audio_sha, patches): (String, i64) = conn.query_row(
        "SELECT audio_sha256, patches_analyzed FROM feature_tracks
          WHERE track_file=?1 AND model_id=?2 AND model_key=?3",
        params![track, &profile.descriptor.id, &profile.model_key],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )?;
    if patches <= 0 { return Ok(false); }
    crate::song_embedding::cached_matches(
        &crate::song_embedding::track_output_path(dir, track),
        track, &audio_sha, patches as usize, model, encoder_sha, preprocessing,
    )
}

fn persist_scan_output(
    conn: &mut Connection, track: &str, state: (i64, i64),
    report: &FeatureReport,
    embedding: Option<crate::song_embedding::SongEmbedding>,
    embedding_dir: Option<&Path>,
) -> Result<()> {
    if let Some(dir) = embedding_dir {
        let mut embedding = embedding.context("Requested 1280D embedding was not returned")?;
        embedding.track_file = Some(track.to_owned());
        crate::song_embedding::write_or_verify(
            &crate::song_embedding::track_output_path(dir, track), &embedding,
        )?;
    }
    persist_into(conn, track, report, Some(state))
}

pub fn scan(options: ScanOptions<'_>) -> Result<ScanSummary> {
    let started = Instant::now();
    if options.threads == 0 || options.max_new == Some(0) || options.max_errors == 0 {
        bail!("--threads, --max-new and --max-errors must be positive");
    }
    let tracks = selected_tracks(&options)?;
    if let Some(out) = options.embedding_dir {
        if options.tracks_file.is_none() || options.dry_run {
            bail!("--embedding-dir requires --tracks-file and forbids --dry-run");
        }
        if !out.is_dir() {
            bail!("--embedding-dir must be an existing private directory");
        }
        let out_real = std::fs::canonicalize(out)?;
        for protected in [options.source_root, Some(options.models_dir)].into_iter().flatten() {
            if out_real.starts_with(std::fs::canonicalize(protected)?) {
                bail!("Embedding output directory must be outside audio and model roots");
            }
        }
    }
    let mut profiles = load_profiles(options.models_dir, options.registry, options.models)?;
    retarget_profiles(&mut profiles, &options.backend)?;
    let cpu_cap = crate::parallel::available_worker_capacity();
    if !options.dry_run && (options.workers == 0 || options.workers > cpu_cap) {
        bail!("Worker count must be within 1..={cpu_cap} logical CPUs available to this process");
    }
    if options.workers > 1 && options.threads > 1 {
        bail!("Parallel analysis requires --threads 1 to avoid ONNX oversubscription");
    }
    if options.workers > 1 && !options.dry_run {
        return scan_parallel(options, profiles, tracks, started);
    }
    let mut conn = if options.dry_run {
        storage::open_readonly_scan_db(options.db)?
    } else {
        Some(storage::open_scan_db(options.db)?)
    };
    let mut engine = None;
    let mut summary = ScanSummary {
        model_ids: profiles.iter().map(|p| p.descriptor.id.clone()).collect(),
        workers: if options.dry_run { 0 } else { 1 },
        bliss_tracks: tracks.len(),
        checked: 0, up_to_date: 0, pending: 0, analyzed: 0,
        missing_files: 0, failures: 0, limit_reached: false,
        elapsed_seconds: 0.0, model_sessions_initialized: false,
        experimental_results: true,
        priority: None, diagnostics: None,
    };
    for track in tracks {
        // Bound attempted songs, not just successful writes. A broken ONNX
        // configuration cannot silently traverse the entire source library.
        if options.max_new.is_some_and(|max| summary.pending >= max) {
            summary.limit_reached = true;
            break;
        }
        if summary.failures + summary.missing_files >= options.max_errors {
            bail!("Feature scan stopped after {} errors (--max-errors {}). Analyzed={}, attempted={}",
                summary.failures + summary.missing_files, options.max_errors,
                summary.analyzed, summary.pending);
        }
        summary.checked += 1;
        let path = match crate::batch::source_path(
            &track, options.library_root, options.source_root,
        ) {
            Ok(path) => path,
            Err(e) => {
                summary.failures += 1;
                eprintln!("MAPPING ERROR {track}: {e:#}");
                continue;
            }
        };
        let state = match crate::batch::file_stat(&path) {
            Ok(stat) => stat,
            Err(error) => {
                summary.missing_files += 1;
                eprintln!("SOURCE UNAVAILABLE {}: {error:#}", path.display());
                continue;
            }
        };
        if conn.as_ref().map(|db| is_scan_complete(
            db, &track, &profiles, state, options.embedding_dir,
            options.backend.preprocessing(),
        )).transpose()?.unwrap_or(false) {
            summary.up_to_date += 1;
            continue;
        }
        summary.pending += 1;
        if options.dry_run { continue; }
        if options.max_new.is_some_and(|max| summary.analyzed >= max) {
            summary.limit_reached = true;
            break;
        }
        if engine.is_none() {
            let mut created = FeatureEngine::with_backend(
                profiles.clone(), options.threads, &options.backend,
            )?;
            if options.embedding_dir.is_some() {
                created.request_song_embedding();
            }
            engine = Some(created);
            summary.model_sessions_initialized = true;
        }
        let engine = engine.as_mut().expect("engine available");
        let outcome = engine.analyze(&path, None).and_then(|report| {
            persist_scan_output(
                conn.as_mut().expect("writable feature database"), &track, state,
                &report, engine.take_song_embedding(), options.embedding_dir,
            )
        });
        match outcome {
            Ok(()) => {
                summary.analyzed += 1;
                eprintln!("ANALYZED {} ({}/{})", track, summary.analyzed, summary.pending);
            }
            Err(error) => {
                summary.failures += 1;
                eprintln!("ANALYSIS FAILED {track}: {error:#}");
            }
        }
    }
    summary.elapsed_seconds = started.elapsed().as_secs_f64();
    Ok(summary)
}

/// One music track and its exact Bliss file identity, never mutable source data.
struct FeatureJob {
    track: String,
    path: PathBuf,
    state: (i64, i64),
}

type FeatureCompletion = (
    FeatureJob,
    Result<(FeatureReport, Option<crate::song_embedding::SongEmbedding>)>,
);

#[derive(Clone, Copy)]
struct CompletionPolicy<'a> {
    expected: Option<usize>,
    embedding_dir: Option<&'a Path>,
}

fn save_completion(
    rx: &std::sync::mpsc::Receiver<FeatureCompletion>,
    conn: &mut Connection,
    summary: &mut ScanSummary,
    diagnostics: &mut ScanDiagnostics,
    monitor: &mut crate::resources::ResourceMonitor,
    policy: CompletionPolicy<'_>,
) -> Result<()> {
    let (job, result) = rx.recv().context("All feature workers exited before returning results")?;
    match result {
        Ok((report, embedding)) => match persist_scan_output(
            conn, &job.track, job.state, &report, embedding, policy.embedding_dir,
        ) {
            Ok(()) => {
                diagnostics.add(&report);
                summary.analyzed += 1;
                if let Some(max) = policy.expected {
                    eprintln!("ANALYZED {} ({}/{})", job.track, summary.analyzed, max);
                } else {
                    eprintln!("ANALYZED {} (completed={}, attempted={})",
                        job.track, summary.analyzed, summary.pending);
                }
            }
            Err(err) => {
                summary.failures += 1;
                eprintln!("STORAGE FAILED {}: {err:#}", job.track);
            }
        },
        Err(err) => {
            summary.failures += 1;
            eprintln!("ANALYSIS FAILED {}: {err:#}", job.track);
        }
    }
    if let Some(load) = monitor.sample() {
        diagnostics.sample(load);
    }
    Ok(())
}

/// Worker sessions are created only when a job arrives, then reused. One
/// coordinator owns SQLite and controls how many tasks are in flight, so
/// adjusting the active concurrency never discards in-progress work.
fn scan_parallel(
    options: ScanOptions<'_>,
    profiles: Vec<Profile>,
    tracks: Vec<String>,
    started: Instant,
) -> Result<ScanSummary> {
    use std::sync::{mpsc, Arc, Mutex};
    use std::sync::atomic::{AtomicUsize, Ordering};
    let mut conn = storage::open_scan_db(options.db)?;
    // Scan capacity is fixed at startup, independent of the number of
    // remaining songs or temporarily idle workers.
    let pool_size = options.workers.min(tracks.len()).max(1);
    let baseline = crate::resources::scan_resource_baseline();
    let mut diagnostics = ScanDiagnostics {
        initial_workers: pool_size,
        logical_cpu_capacity: crate::parallel::available_worker_capacity(),
        configured_max_workers: pool_size,
        final_workers: pool_size,
        peak_workers: pool_size,
        baseline: Some(baseline),
        ..ScanDiagnostics::default()
    };
    let mut monitor = crate::resources::ResourceMonitor::new();
    let mut summary = ScanSummary {
        model_ids: profiles.iter().map(|p| p.descriptor.id.clone()).collect(),
        workers: pool_size, bliss_tracks: tracks.len(),
        checked: 0, up_to_date: 0, pending: 0, analyzed: 0,
        missing_files: 0, failures: 0, limit_reached: false,
        elapsed_seconds: 0.0, model_sessions_initialized: false,
        experimental_results: true,
        priority: None, diagnostics: None,
    };

    // A single bounded task channel; only up to active jobs in flight.
    // The result channel contains small classification reports, not PCM audio.
    let (task_tx, task_rx) = mpsc::sync_channel::<FeatureJob>(pool_size);
    let task_rx = Arc::new(Mutex::new(task_rx));
    let (result_tx, result_rx) = mpsc::channel::<FeatureCompletion>();
    let active_analyses = Arc::new(AtomicUsize::new(0));
    let peak_active_analyses = Arc::new(AtomicUsize::new(0));
    let aborted = std::thread::scope(|scope| -> Result<bool> {
        for _ in 0..pool_size {
            let rx = Arc::clone(&task_rx);
            let tx = result_tx.clone();
            let profiles = profiles.clone();
            let backend = options.backend.clone();
            let active_analyses = Arc::clone(&active_analyses);
            let peak_active_analyses = Arc::clone(&peak_active_analyses);
            scope.spawn(move || {
                let mut engine: Option<FeatureEngine> = None;
                loop {
                    let task = match rx.lock() {
                        Ok(guard) => match guard.recv() {
                            Ok(task) => task,
                            Err(_) => break,
                        },
                        Err(_) => break,
                    };
                    let active = active_analyses.fetch_add(1, Ordering::SeqCst) + 1;
                    peak_active_analyses.fetch_max(active, Ordering::SeqCst);
                    let report = match engine.as_mut() {
                        Some(engine) => engine.analyze(&task.path, None)
                            .map(|report| (report, engine.take_song_embedding())),
                        None => match FeatureEngine::with_backend(
                            profiles.clone(), options.threads, &backend,
                        ) {
                            Ok(mut created) => {
                                if options.embedding_dir.is_some() {
                                    created.request_song_embedding();
                                }
                                let result = created.analyze(&task.path, None)
                                    .map(|report| (report, created.take_song_embedding()));
                                engine = Some(created);
                                result
                            }
                            Err(err) => Err(err),
                        },
                    };
                    active_analyses.fetch_sub(1, Ordering::SeqCst);
                    if tx.send((task, report)).is_err() {
                        break;
                    }
                }
            });
        }
        drop(result_tx);
        let mut in_flight = 0usize;
        let mut stopped_for_errors = false;
        for track in tracks {
            // max-new counts attempted tracks, not only successful writes.
            if options.max_new.is_some_and(|max| summary.pending >= max) {
                summary.limit_reached = true;
                break;
            }
            if summary.failures + summary.missing_files >= options.max_errors {
                stopped_for_errors = true;
                break;
            }
            summary.checked += 1;
            let path = match crate::batch::source_path(
                &track, options.library_root, options.source_root,
            ) {
                Ok(path) => path,
                Err(err) => {
                    summary.failures += 1;
                    eprintln!("MAPPING ERROR {track}: {err:#}");
                    continue;
                }
            };
            let state = match crate::batch::file_stat(&path) {
                Ok(state) => state,
                Err(err) => {
                    summary.missing_files += 1;
                    eprintln!("SOURCE UNAVAILABLE {}: {err:#}", path.display());
                    continue;
                }
            };
            if is_scan_complete(
                &conn, &track, &profiles, state, options.embedding_dir,
                options.backend.preprocessing(),
            )? {
                summary.up_to_date += 1;
                continue;
            }
            // Do not scan ahead of the active concurrency limit; always
            // receive and persist a result before scheduling another song.
            while in_flight >= pool_size {
                let failures_before = summary.failures;
                save_completion(
                    &result_rx, &mut conn, &mut summary, &mut diagnostics,
                    &mut monitor, CompletionPolicy { expected: options.max_new, embedding_dir: options.embedding_dir },
                )?;
                in_flight -= 1;
                if summary.failures > failures_before {
                    // Stop dispatching new songs on the first inference or
                    // storage failure. Drain existing work to avoid starting
                    // a fifth failing song while four are already in flight.
                    while in_flight > 0 {
                        save_completion(
                            &result_rx, &mut conn, &mut summary, &mut diagnostics,
                            &mut monitor, CompletionPolicy { expected: options.max_new, embedding_dir: options.embedding_dir },
                        )?;
                        in_flight -= 1;
                    }
                }
                if summary.failures + summary.missing_files >= options.max_errors {
                    stopped_for_errors = true;
                    break;
                }
            }
            if stopped_for_errors {
                break;
            }
            task_tx.send(FeatureJob { track, path, state })
                .context("Feature work queue unexpectedly closed")?;
            summary.model_sessions_initialized = true;
            summary.pending += 1;
            in_flight += 1;
            diagnostics.peak_in_flight = diagnostics.peak_in_flight.max(in_flight);
        }
        drop(task_tx);
        // Return all in-flight reports before leaving scoped threads.
        while in_flight > 0 {
            save_completion(
                &result_rx, &mut conn, &mut summary, &mut diagnostics,
                &mut monitor, CompletionPolicy { expected: options.max_new, embedding_dir: options.embedding_dir },
            )?;
            in_flight -= 1;
        }
        Ok(stopped_for_errors || summary.failures + summary.missing_files >= options.max_errors)
    })?;
    diagnostics.peak_active_analyses = peak_active_analyses.load(Ordering::SeqCst);
    summary.elapsed_seconds = started.elapsed().as_secs_f64();
    summary.diagnostics = Some(diagnostics);
    if aborted {
        bail!(
            "Feature scan stopped after {} errors (limit {}). Analyzed={}, attempted={}",
            summary.failures + summary.missing_files, options.max_errors,
            summary.analyzed, summary.pending
        );
    }
    Ok(summary)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::UNIX_EPOCH;

    #[test]
    fn manifest_selection_reuses_scan_options_and_filters_exact_identity() {
        let dir = std::env::temp_dir().join(format!(
            "essentia-analyser-manifest-cohort-{}-{}", std::process::id(),
            std::time::SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()
        ));
        let music = dir.join("music");
        std::fs::create_dir_all(music.join("Artist")).unwrap();
        std::fs::write(music.join("Artist").join("one.flac"), b"synthetic").unwrap();
        let manifest = dir.join("selected.txt");
        std::fs::write(&manifest, "Artist/one.flac\nArtist/missing.flac\n").unwrap();
        let mut options = ScanOptions {
            bliss_db: None, tracks_file: Some(manifest.as_path()),
            embedding_dir: None, db: std::path::Path::new("unused.db"),
            models_dir: std::path::Path::new("unused-models"),
            registry: None, models: "genre",
            source_root: Some(music.as_path()), library_root: None,
            only_track: None, max_new: None, max_errors: 5,
            threads: 1, workers: 2, dry_run: true,
            backend: BackendChoice::Rust,
        };
        // Missing audio is a scanner-stage error, not silently lost in the manifest.
        assert_eq!(selected_tracks(&options).unwrap(),
            vec!["Artist/one.flac", "Artist/missing.flac"]);
        options.only_track = Some("Artist/one.flac");
        assert_eq!(selected_tracks(&options).unwrap(), vec!["Artist/one.flac"]);
        options.only_track = Some("Artist/not-selected.flac");
        assert!(selected_tracks(&options).is_err());
        options.only_track = None;
        options.library_root = Some("/wrong");
        assert!(selected_tracks(&options).is_err());
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn manifest_rejects_existing_symlink_outside_source_root() {
        use std::os::unix::fs::symlink;
        let dir = std::env::temp_dir().join(format!(
            "essentia-analyser-manifest-symlink-{}-{}", std::process::id(),
            std::time::SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()
        ));
        let music = dir.join("music");
        std::fs::create_dir_all(&music).unwrap();
        let outside = dir.join("outside.wav");
        std::fs::write(&outside, b"synthetic").unwrap();
        symlink(&outside, music.join("linked.wav")).unwrap();
        let manifest = dir.join("selected.txt");
        std::fs::write(&manifest, "linked.wav\n").unwrap();
        let options = ScanOptions {
            bliss_db: None, tracks_file: Some(manifest.as_path()),
            embedding_dir: None, db: std::path::Path::new("unused.db"),
            models_dir: std::path::Path::new("unused-models"),
            registry: None, models: "genre", source_root: Some(music.as_path()),
            library_root: None, only_track: None, max_new: None,
            max_errors: 5, threads: 1, workers: 2, dry_run: true,
            backend: BackendChoice::Rust,
        };
        assert!(selected_tracks(&options).is_err());
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn manifest_preserves_order_and_rejects_aliases_or_duplicates() {
        let file = std::env::temp_dir().join(format!(
            "essentia-analyser-manifest-{}-{}.txt", std::process::id(),
            std::time::SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()
        ));
        std::fs::write(&file, "Artist/B.flac\nArtist/A.flac\n").unwrap();
        assert_eq!(read_track_manifest(&file).unwrap(),
            vec!["Artist/B.flac", "Artist/A.flac"]);
        for contents in [
            "Artist/A.flac\nArtist/A.flac\n",
            "../outside.mp3\n",
            "Artist/./song.flac\n",
            "Artist//song.mp3\n",
            "C:/escape.mp3\n",
            "Artist\\song.mp3\n",
            "/outside/song.mp3\n",
        ] {
            std::fs::write(&file, contents).unwrap();
            assert!(read_track_manifest(&file).is_err(), "{contents:?}");
        }
        std::fs::write(&file, vec![b'a'; 32 * 1024 * 1024 + 1]).unwrap();
        assert!(read_track_manifest(&file).is_err());
        std::fs::remove_file(&file).unwrap();
    }



    fn fake_result(model_id: &str, capability: &str, count: usize) -> ClassificationResult {
        let embedding_model = "encoder.onnx".to_owned();
        let classification_model = format!("{model_id}.onnx");
        let hashes = BTreeMap::from([
            (embedding_model.clone(), "a".repeat(64)),
            (classification_model.clone(), "b".repeat(64)),
        ]);
        let scores = (0..count)
            .map(|i| (format!("label{i:03}"), i as f32 / 1000.0))
            .collect::<BTreeMap<_, _>>();
        let labels = scores.keys().cloned().collect::<Vec<_>>();
        let model_key = storage::model_key_for(
            &embedding_model, &classification_model, &hashes,
            PREPROCESSING, AGGREGATION, &labels, false,
        ).unwrap();
        ClassificationResult {
            capability: capability.to_owned(),
            output_type: OutputType::Sigmoid, aggregation: AGGREGATION,
            embedding_model, classification_model, models_sha256: hashes,
            model_key, validated_against_essentia: false, scores,
        }
    }

    fn fake_report() -> FeatureReport {
        FeatureReport {
            schema_version: 3, preprocessing_version: PREPROCESSING,
            aggregation: AGGREGATION, audio_path: "track.flac".to_owned(),
            audio_sha256: "c".repeat(64), sample_rate: 16000,
            patches_analyzed: 5, threads: 1,
            timings: Timing {
                decode_seconds: 0.0, features_seconds: 0.0,
                hash_seconds: 0.0, model_load_seconds: 0.0, inference_seconds: 0.0,
                total_seconds: 0.0,
            },
            classifications: BTreeMap::from([
                ("moodtheme".to_owned(), fake_result("mood", "mood_theme", 56)),
                ("genre".to_owned(), fake_result("genre", "genre", 87)),
            ]),
        }
    }

    #[test]
    fn generic_storage_preserves_legacy_rows_and_other_models() {
        let db = std::env::temp_dir().join(format!(
            "essentia-analyser-feature-test-{}-{}.db", std::process::id(),
            std::time::SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos(),
        ));
        let legacy = crate::Report {
            schema_version: 1, preprocessing_version: PREPROCESSING,
            classification_model: "mood.onnx",
            embedding_model: "encoder.onnx",
            audio_path: "song.flac".to_owned(),
            audio_sha256: "c".repeat(64),
            models_sha256: BTreeMap::from([("mood.onnx".to_owned(), "b".repeat(64))]),
            sample_rate: 16000, patches_analyzed: 5, threads: 1,
            aggregation: AGGREGATION, validated_against_essentia: false,
            timings: Timing { decode_seconds: 0.0, features_seconds: 0.0,
                hash_seconds: 0.0, model_load_seconds: 0.0, inference_seconds: 0.0, total_seconds: 0.0 },
            scores: (0..56).map(|i| (format!("label{i:03}"), 0.1)).collect(),
        };
        let key = "Artist/Album/song.flac";
        storage::persist(&db, key, &legacy).unwrap();
        let report = fake_report();
        persist(&db, key, &report, Some((5000, 12345))).unwrap();
        let conn = Connection::open(&db).unwrap();
        let (legacy_count, feature_count, catalog_count, state_count): (i64, i64, i64, i64) =
            (
                conn.query_row("SELECT count(*) FROM mood_tracks", [], |r| r.get(0)).unwrap(),
                conn.query_row("SELECT count(*) FROM feature_tracks", [], |r| r.get(0)).unwrap(),
                conn.query_row("SELECT count(*) FROM feature_models", [], |r| r.get(0)).unwrap(),
                conn.query_row("SELECT count(*) FROM feature_track_state", [], |r| r.get(0)).unwrap(),
            );
        assert_eq!((legacy_count, feature_count, catalog_count, state_count), (1, 2, 2, 2));
        let lengths = conn.prepare(
            "SELECT model_id, length(scores_f32_le) FROM feature_tracks ORDER BY model_id",
        ).unwrap().query_map([], |row| Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?)))
            .unwrap().collect::<rusqlite::Result<Vec<_>>>().unwrap();
        assert_eq!(lengths, [("genre".to_owned(), 348), ("moodtheme".to_owned(), 224)]);
        drop(conn);
        let mut partial = fake_report();
        partial.classifications.remove("moodtheme");
        persist(&db, key, &partial, Some((5001, 12346))).unwrap();
        let conn = Connection::open(&db).unwrap();
        let n: i64 = conn.query_row("SELECT count(*) FROM feature_tracks", [], |r| r.get(0)).unwrap();
        assert_eq!(n, 2);
        let old_mood_stat: i64 = conn.query_row(
            "SELECT file_size FROM feature_track_state WHERE model_id='moodtheme'",
            [], |r| r.get(0),
        ).unwrap();
        let new_genre_stat: i64 = conn.query_row(
            "SELECT file_size FROM feature_track_state WHERE model_id='genre'",
            [], |r| r.get(0),
        ).unwrap();
        assert_eq!((old_mood_stat, new_genre_stat), (5000, 5001));
        drop(conn);
        std::fs::remove_file(db).unwrap();
    }

    #[test]
    fn voice_softmax_persists_without_changing_mood_or_genre() {
        let db = std::env::temp_dir().join(format!(
            "essentia-analyser-voice-{}-{}.db", std::process::id(),
            std::time::SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos(),
        ));
        let track = "Artist/Album/voice.flac";
        let original = fake_report();
        persist(&db, track, &original, Some((1200, 44))).unwrap();
        let mut voice = fake_result("voice", "voice_presence", 2);
        voice.output_type = OutputType::Softmax;
        voice.aggregation = SOFTMAX_AGGREGATION;
        voice.scores = BTreeMap::from([
            ("instrumental".to_owned(), 0.25),
            ("voice".to_owned(), 0.75),
        ]);
        voice.model_key = storage::model_key_for(
            &voice.embedding_model, &voice.classification_model,
            &voice.models_sha256, PREPROCESSING, voice.aggregation,
            &voice.scores.keys().cloned().collect::<Vec<_>>(), false,
        ).unwrap();
        let report = FeatureReport { classifications: BTreeMap::from([
            ("voice".to_owned(), voice)
        ]), ..fake_report() };
        persist(&db, track, &report, Some((1200, 44))).unwrap();
        let conn = Connection::open(&db).unwrap();
        let rows = conn.prepare(
            "SELECT t.model_id, length(t.scores_f32_le), m.aggregation
             FROM feature_tracks t JOIN feature_models m ON m.model_key=t.model_key
             ORDER BY t.model_id"
        ).unwrap().query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?,
                row.get::<_, String>(2)?))
        }).unwrap().collect::<rusqlite::Result<Vec<_>>>().unwrap();
        assert_eq!(rows, [
            ("genre".to_owned(), 348, AGGREGATION.to_owned()),
            ("moodtheme".to_owned(), 224, AGGREGATION.to_owned()),
            ("voice".to_owned(), 8, SOFTMAX_AGGREGATION.to_owned())
        ]);
        drop(conn);
        std::fs::remove_file(db).unwrap();
    }

    #[test]
    fn invalid_second_head_rolls_back_entire_feature_transaction() {
        let db = std::env::temp_dir().join(format!(
            "essentia-analyser-feature-rollback-{}-{}.db", std::process::id(),
            std::time::SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos(),
        ));
        let mut report = fake_report();
        report.classifications.get_mut("moodtheme").unwrap().scores
            .insert("label000".to_owned(), f32::NAN);
        assert!(persist(&db, "song.flac", &report, Some((5000, 12345))).is_err());
        let conn = Connection::open(&db).unwrap();
        let count: i64 =
            conn.query_row("SELECT count(*) FROM feature_tracks", [], |r| r.get(0)).unwrap();
        assert_eq!(count, 0);
        drop(conn);
        std::fs::remove_file(db).unwrap();
    }

    #[test]
    fn output_type_controls_probability_checks_and_model_fingerprint() {
        assert!(valid_head_scores(&[0.6, 0.4], 2, OutputType::Softmax));
        assert!(!valid_head_scores(&[0.6, 0.6], 2, OutputType::Softmax));
        assert!(valid_head_scores(&[0.6, 0.6], 2, OutputType::Sigmoid));
        assert!(!valid_head_scores(&[f32::NAN, 1.0], 2, OutputType::Softmax));
        let classes = vec!["instrumental".to_owned(), "voice".to_owned()];
        let hashes = BTreeMap::from([("head.onnx".to_owned(), "f".repeat(64))]);
        let sigmoid = storage::model_key_for("effnet", "head.onnx", &hashes,
            PREPROCESSING, AGGREGATION, &classes, false).unwrap();
        let softmax = storage::model_key_for("effnet", "head.onnx", &hashes,
            PREPROCESSING, SOFTMAX_AGGREGATION, &classes, false).unwrap();
        assert_ne!(sigmoid, softmax);
    }

    #[test]
    fn rejects_absolute_and_parent_model_paths() {
        for name in ["../head.onnx", "/tmp/head.onnx", r"C:\test.onnx", "foo/bar.onnx"] {
            assert!(!safe_model_name(name));
        }
        assert!(safe_model_name("head.onnx"));
    }

    #[test]
    fn native_frontend_has_distinct_cached_model_key_per_worker_binary() {
        let descriptor = Descriptor {
            id: "genre".to_owned(), capability: "genre".to_owned(),
            embedding_model: "encoder.onnx".to_owned(),
            classification_model: "genre.onnx".to_owned(),
            metadata: "genre.json".to_owned(), embedding_dimensions: 1280,
            expected_classes: 2, output_type: OutputType::Sigmoid,
        };
        let hashes = BTreeMap::from([
            ("encoder.onnx".to_owned(), "a".repeat(64)),
            ("genre.onnx".to_owned(), "b".repeat(64)),
        ]);
        let labels = vec!["a".to_owned(), "b".to_owned()];
        let original_key = storage::model_key_for(
            "encoder.onnx", "genre.onnx", &hashes, PREPROCESSING,
            AGGREGATION, &labels, false,
        ).unwrap();
        let original = Profile {
            descriptor, labels, encoder_path: PathBuf::from("encoder.onnx"),
            head_path: PathBuf::from("genre.onnx"), hashes,
            model_key: original_key.clone(),
        };
        let mut untouched = vec![original.clone()];
        retarget_profiles(&mut untouched, &BackendChoice::Rust).unwrap();
        assert_eq!(untouched[0].model_key, original_key);
        let mk_backend = |fingerprint: &str| BackendChoice::Essentia {
            executable: PathBuf::from("test-only-worker"),
            worker_sha256: fingerprint.repeat(64),
            deployment_sha256: None, timeout_seconds: 900,
        };
        let mut first = vec![original.clone()];
        let mut second = vec![original];
        retarget_profiles(&mut first, &mk_backend("c")).unwrap();
        retarget_profiles(&mut second, &mk_backend("d")).unwrap();
        assert_ne!(first[0].model_key, original_key);
        assert_ne!(second[0].model_key, first[0].model_key);
        assert_eq!(first[0].hashes["essentia_cpp_worker_binary_sha256"], "c".repeat(64));
        let mut with_dependencies = vec![first[0].clone()];
        let installed = BackendChoice::Essentia {
            executable: PathBuf::from("test-only-worker"),
            worker_sha256: "c".repeat(64),
            deployment_sha256: Some("d".repeat(64)),
            timeout_seconds: 900,
        };
        retarget_profiles(&mut with_dependencies, &installed).unwrap();
        assert_eq!(
            with_dependencies[0].hashes["essentia_cpp_native_deployment_manifest_sha256"],
            "d".repeat(64)
        );
        assert_ne!(with_dependencies[0].model_key, first[0].model_key);
    }

    #[test]
    fn registry_has_independent_capabilities() {
        let registry: Registry = serde_json::from_str(include_str!("../model-registry.json")).unwrap();
        assert_eq!(registry.schema_version, 2);
        assert_eq!(registry.models.len(), 3);
        assert_eq!(registry.models[0].capability, "mood_theme");
        assert_eq!(registry.models[1].capability, "genre");
        assert_eq!(registry.models[1].expected_classes, 87);
        assert_eq!(registry.models[0].embedding_model, registry.models[1].embedding_model);
        assert_eq!(registry.models[0].embedding_model, registry.models[2].embedding_model);
        assert_eq!(registry.models[2].capability, "voice_presence");
        assert_eq!(registry.models[2].expected_classes, 2);
        assert_eq!(registry.models[2].output_type, OutputType::Softmax);
    }

    #[test]
    fn rejects_unknown_registry_model_without_audio_or_db() {
        let missing = load_profiles(Path::new("models"), None, "unlisted");
        assert!(missing.is_err());
    }
}
