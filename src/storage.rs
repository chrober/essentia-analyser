//! Versioned offline SQLite sidecar for Mood results. Bliss DB is always read-only.
use anyhow::{bail, Context, Result};
use rusqlite::{params, Connection, OpenFlags};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{path::Path, time::Duration};

use crate::Report;

const SCHEMA_VERSION: i64 = 3;
const SCORE_COUNT: usize = 56;

const SCHEMA: &str = r#"
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS mood_models (
    model_key TEXT PRIMARY KEY,
    embedding_model TEXT NOT NULL,
    classification_model TEXT NOT NULL,
    models_sha256_json TEXT NOT NULL,
    preprocessing_version TEXT NOT NULL,
    aggregation TEXT NOT NULL,
    classes_json TEXT NOT NULL,
    validated_against_essentia INTEGER NOT NULL
        CHECK (validated_against_essentia IN (0,1))
);
CREATE TABLE IF NOT EXISTS mood_tracks (
    track_file TEXT PRIMARY KEY NOT NULL,
    audio_sha256 TEXT NOT NULL,
    model_key TEXT NOT NULL REFERENCES mood_models(model_key),
    scores_f32_le BLOB NOT NULL CHECK (length(scores_f32_le) = 224),
    patches_analyzed INTEGER NOT NULL CHECK (patches_analyzed > 0),
    analyzed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS mood_tracks_model_idx ON mood_tracks(model_key);
CREATE TABLE IF NOT EXISTS mood_track_state (
    track_file TEXT PRIMARY KEY REFERENCES mood_tracks(track_file) ON DELETE CASCADE,
    file_size INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    model_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feature_models (
    model_key TEXT PRIMARY KEY,
    embedding_model TEXT NOT NULL,
    classification_model TEXT NOT NULL,
    models_sha256_json TEXT NOT NULL,
    preprocessing_version TEXT NOT NULL,
    aggregation TEXT NOT NULL,
    classes_json TEXT NOT NULL,
    validated_against_essentia INTEGER NOT NULL CHECK (validated_against_essentia IN (0,1))
);
CREATE TABLE IF NOT EXISTS feature_tracks (
    track_file TEXT NOT NULL,
    model_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    audio_sha256 TEXT NOT NULL,
    model_key TEXT NOT NULL REFERENCES feature_models(model_key),
    scores_f32_le BLOB NOT NULL CHECK (length(scores_f32_le) > 0 AND length(scores_f32_le) % 4 = 0),
    patches_analyzed INTEGER NOT NULL CHECK (patches_analyzed > 0),
    analyzed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (track_file, model_id)
);
CREATE INDEX IF NOT EXISTS feature_tracks_model_key_idx ON feature_tracks(model_key);
CREATE TABLE IF NOT EXISTS feature_track_state (
    track_file TEXT NOT NULL,
    model_id TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    model_key TEXT NOT NULL,
    PRIMARY KEY (track_file, model_id),
    FOREIGN KEY (track_file, model_id) REFERENCES feature_tracks(track_file, model_id) ON DELETE CASCADE
);
"#;

fn schema_version(conn: &Connection) -> Result<i64> {
    Ok(conn.pragma_query_value(None, "user_version", |row| row.get(0))?)
}

fn create_schema(conn: &Connection) -> Result<()> {
    // Never alter an upstream Bliss database, even if passed by mistake.
    let bliss_tables: i64 = conn.query_row(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='TracksV2'",
        [],
        |row| row.get(0),
    )?;
    if bliss_tables != 0 {
        bail!("Refusing to alter bliss.db: TracksV2 exists in target database");
    }
    let other_tables: i64 = conn.query_row(
        "SELECT count(*) FROM sqlite_master WHERE type='table'
           AND name NOT LIKE 'sqlite_%'
           AND name NOT IN ('mood_models', 'mood_tracks', 'mood_track_state', 'feature_models', 'feature_tracks', 'feature_track_state')",
        [],
        |row| row.get(0),
    )?;
    if other_tables != 0 {
        bail!("Refusing to alter unrelated SQLite database");
    }
    let version = schema_version(conn)?;
    if ![0, 1, 2, SCHEMA_VERSION].contains(&version) {
        bail!("Unsupported mood.db schema version {version} (expected {SCHEMA_VERSION})");
    }
    conn.execute_batch(SCHEMA)?;
    if version < SCHEMA_VERSION {
        // All legacy Mood rows and their scan snapshots remain unchanged.
        // The feature tables are additive and keep independent model rows.
        conn.pragma_update(None, "user_version", SCHEMA_VERSION)?;
    }
    Ok(())
}

fn checked_report(report: &Report) -> Result<(String, String, Vec<u8>, String, String)> {
    if report.scores.len() != SCORE_COUNT || report.patches_analyzed == 0 {
        bail!("Expected 56 named scores and at least one analysed audio patch");
    }
    if report
        .scores
        .values()
        .any(|x| !x.is_finite() || !(0.0..=1.0).contains(x))
    {
        bail!("Mood scores must be finite probabilities in [0,1]");
    }
    // BTreeMap sorts labels deterministically; the stored classes_json provides
    // the exact interpretation of every 4-byte f32 vector position.
    let classes: Vec<&str> = report.scores.keys().map(String::as_str).collect();
    let classes_json = serde_json::to_string(&classes)?;
    let models_json = serde_json::to_string(&report.models_sha256)?;
    let model_key = model_key_for(
        report.embedding_model,
        report.classification_model,
        &report.models_sha256,
        report.preprocessing_version,
        report.aggregation,
        &classes.iter().map(|s| (*s).to_owned()).collect::<Vec<_>>(),
        report.validated_against_essentia,
    )?;
    let mut score_bytes = Vec::with_capacity(SCORE_COUNT * 4);
    for score in report.scores.values() {
        score_bytes.extend_from_slice(&score.to_le_bytes());
    }
    Ok((model_key, classes_json, score_bytes, models_json, report.audio_sha256.clone()))
}

/// Writes only to the new mood.db. The track_key MUST equal Bliss TracksV2.File
/// on the destination server (no implicit prefix conversion or normalization).
pub fn persist(db_path: &Path, track_key: &str, report: &Report) -> Result<()> {
    let mut conn = Connection::open(db_path)
        .with_context(|| format!("Unable to open mood database {}", db_path.display()))?;
    conn.busy_timeout(Duration::from_secs(5))?;
    insert(&mut conn, track_key, report)
}

fn insert(conn: &mut Connection, track_key: &str, report: &Report) -> Result<()> {
    insert_inner(conn, track_key, report, None)
}

fn insert_inner(
    conn: &mut Connection,
    track_key: &str,
    report: &Report,
    file_state: Option<(i64, i64)>,
) -> Result<()> {
    if track_key.is_empty() || track_key.trim() != track_key || track_key.contains('\0') {
        bail!("Invalid track key: use exact non-empty TracksV2.File path");
    }
    if report.audio_sha256.len() != 64
        || !report.audio_sha256.bytes().all(|b| b.is_ascii_hexdigit())
    {
        bail!("Audio SHA256 must be a 64-character hex string");
    }
    let (model_key, classes_json, scores, models_json, audio_sha256) =
        checked_report(report)?;
    create_schema(conn)?;
    let transaction = conn.transaction()?;
    transaction.execute(
        "INSERT INTO mood_models
            (model_key, embedding_model, classification_model, models_sha256_json,
             preprocessing_version, aggregation, classes_json, validated_against_essentia)
          VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
          ON CONFLICT(model_key) DO NOTHING",
        params![
            model_key,
            report.embedding_model,
            report.classification_model,
            models_json,
            report.preprocessing_version,
            report.aggregation,
            classes_json,
            report.validated_against_essentia,
        ],
    )?;
    transaction.execute(
        "INSERT INTO mood_tracks (track_file, audio_sha256, model_key, scores_f32_le, patches_analyzed)
          VALUES (?1, ?2, ?3, ?4, ?5)
          ON CONFLICT(track_file) DO UPDATE SET
            audio_sha256=excluded.audio_sha256,
            model_key=excluded.model_key,
            scores_f32_le=excluded.scores_f32_le,
            patches_analyzed=excluded.patches_analyzed,
            analyzed_at=CURRENT_TIMESTAMP",
        params![
            track_key,
            audio_sha256,
            model_key,
            scores,
            report.patches_analyzed as i64,
        ],
    )?;
    // Keep result and its provenance snapshot in the *same* SQLite transaction.
    // A standalone single-file write deliberately invalidates old scan snapshots.
    transaction.execute("DELETE FROM mood_track_state WHERE track_file=?1", [track_key])?;
    if let Some((file_size, modified_ns)) = file_state {
        transaction.execute(
            "INSERT INTO mood_track_state(track_file,file_size,modified_ns,model_key)
             VALUES(?1,?2,?3,?4)",
            params![track_key, file_size, modified_ns, model_key],
        )?;
    }
    transaction.commit()?;
    Ok(())
}


pub fn model_key_for(
    embedding: &str,
    classifier: &str,
    hashes: &std::collections::BTreeMap<String,String>,
    preprocessing: &str,
    aggregation: &str,
    labels: &[String],
    validated: bool,
) -> Result<String> {
    let mut labels_sorted = labels.to_vec();
    labels_sorted.sort();
    if labels_sorted.is_empty() || labels_sorted.len() > 2048
        || labels_sorted.iter().any(|label| label.is_empty())
        || labels_sorted.windows(2).any(|w| w[0] == w[1]) {
        bail!("Model requires 1..2048 unique, nonempty class labels");
    }
    let fingerprint = serde_json::to_vec(&(
        embedding, classifier, hashes, preprocessing, aggregation, &labels_sorted, validated
    ))?;
    Ok(format!("{:x}", Sha256::digest(&fingerprint)))
}

pub fn open_scan_db(path: &Path) -> Result<Connection> {
    let conn = Connection::open(path)
        .with_context(|| format!("Cannot open mood database {}", path.display()))?;
    conn.busy_timeout(Duration::from_secs(10))?;
    create_schema(&conn)?;
    Ok(conn)
}


/// Dry-run must never create or migrate a database; v1 has no scan snapshot.
pub fn open_readonly_scan_db(path: &Path) -> Result<Option<Connection>> {
    if !path.exists() {
        return Ok(None);
    }
    let conn = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .with_context(|| format!("Cannot read mood.db: {}", path.display()))?;
    match schema_version(&conn)? {
        1 => Ok(None),
        2 | SCHEMA_VERSION => Ok(Some(conn)),
        other => bail!("Unsupported mood.db schema version {other}"),
    }
}

/// Persist one successful analysis and its corresponding file snapshot.
/// The scores and scan stat are updated transactionally as one unit.
pub fn persist_scanned(
    conn: &mut Connection,
    track_file: &str,
    report: &Report,
    file_size: i64,
    modified_ns: i64,
) -> Result<()> {
    insert_inner(conn, track_file, report, Some((file_size, modified_ns)))
}

pub fn is_current(
    conn: &Connection,
    track_file: &str,
    file_size: i64,
    modified_ns: i64,
    model_key: &str,
) -> Result<bool> {
    let count: i64 = conn.query_row(
        "SELECT COUNT(1) FROM mood_track_state s
         JOIN mood_tracks t ON s.track_file=t.track_file
         WHERE s.track_file=?1 AND s.file_size=?2
           AND s.modified_ns=?3 AND s.model_key=?4
           AND t.model_key=?4",
        params![track_file,file_size,modified_ns,model_key],
        |r| r.get(0),
    )?;
    Ok(count == 1)
}

/// Bliss DB must only ever be opened read-only by the Mood tool.
pub fn bliss_files(bliss_path: &Path) -> Result<Vec<String>> {
    let bliss = Connection::open_with_flags(bliss_path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .with_context(|| format!("Cannot read Bliss DB {}", bliss_path.display()))?;
    let mut stmt = bliss.prepare(
        "SELECT File FROM TracksV2 WHERE Ignore IS NOT 1 ORDER BY File"
    )?;
    let rows = stmt.query_map([], |r| r.get::<_, String>(0))?;
    rows.collect::<std::result::Result<Vec<_>, _>>().map_err(Into::into)
}

#[derive(Debug, Serialize)]
pub struct Coverage {
    schema_version: i64,
    bliss_eligible_tracks: u64,
    matched_tracks: u64,
    validated_tracks: u64,
    experimental_tracks: u64,
    missing_tracks: u64,
    stored_mood_tracks: u64,
    unmatched_mood_tracks: u64,
}

/// Does not modify bliss.db or mood.db; exact path matches only.
pub fn coverage(mood_path: &Path, bliss_path: &Path) -> Result<Coverage> {
    let flags = OpenFlags::SQLITE_OPEN_READ_ONLY;
    let mood = Connection::open_with_flags(mood_path, flags)
        .with_context(|| format!("Cannot read mood.db: {}", mood_path.display()))?;
    let bliss = Connection::open_with_flags(bliss_path, flags)
        .with_context(|| format!("Cannot read bliss.db: {}", bliss_path.display()))?;
    let version = schema_version(&mood)?;
    if version != 2 && version != SCHEMA_VERSION {
        bail!("Unsupported mood.db schema version {version}");
    }
    let stored: u64 = mood.query_row("SELECT count(*) FROM mood_tracks", [], |row| row.get(0))?;
    let mut bliss_query = bliss.prepare("SELECT File FROM TracksV2 WHERE Ignore IS NOT 1")?;
    let mut mood_query = mood.prepare(
        "SELECT m.validated_against_essentia
           FROM mood_tracks t JOIN mood_models m ON t.model_key=m.model_key
          WHERE t.track_file=?1",
    )?;
    let mut eligible = 0u64;
    let mut matched = 0u64;
    let mut validated = 0u64;
    let mut experimental = 0u64;
    let rows = bliss_query.query_map([], |row| row.get::<_, String>(0))?;
    for file in rows {
        let file = file?;
        eligible += 1;
        match mood_query.query_row([file.as_str()], |row| row.get::<_, i64>(0)) {
            Ok(1) => {
                matched += 1;
                validated += 1;
            }
            Ok(_) => {
                matched += 1;
                experimental += 1;
            }
            Err(rusqlite::Error::QueryReturnedNoRows) => {}
            Err(error) => return Err(error.into()),
        }
    }
    Ok(Coverage {
        schema_version: version,
        bliss_eligible_tracks: eligible,
        matched_tracks: matched,
        validated_tracks: validated,
        experimental_tracks: experimental,
        missing_tracks: eligible - matched,
        stored_mood_tracks: stored,
        unmatched_mood_tracks: stored.saturating_sub(matched),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn sample() -> Report {
        Report {
            schema_version: 1,
            preprocessing_version: "unvalidated-test-v1",
            classification_model: "head.onnx",
            embedding_model: "encoder.onnx",
            audio_path: "input.flac".into(),
            audio_sha256: "a".repeat(64),
            models_sha256: BTreeMap::from([("head.onnx".into(), "b".repeat(64))]),
            sample_rate: 16000,
            patches_analyzed: 5,
            threads: 1,
            aggregation: "mean",
            validated_against_essentia: false,
            timings: crate::Timing {
                decode_seconds: 0.0,
                features_seconds: 0.0,
                hash_seconds: 0.0,
                model_load_seconds: 0.0,
                inference_seconds: 0.0,
                total_seconds: 0.0,
            },
            scores: (0..56).map(|n| (format!("label{n:02}"), n as f32 / 100.0)).collect(),
        }
    }

    #[test]
    fn insert_read_back_and_replace_without_duplicate() {
        let mut conn = Connection::open_in_memory().unwrap();
        let mut report = sample();
        insert(&mut conn, "/music/abc.flac", &report).unwrap();
        let (count, len, validated): (i64, i64, i64) = conn
            .query_row(
                "SELECT count(*), length(t.scores_f32_le), max(m.validated_against_essentia)
                   FROM mood_tracks t JOIN mood_models m ON t.model_key=m.model_key",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .unwrap();
        assert_eq!((count, len, validated), (1, 224, 0));
        report.scores.insert("label00".into(), 0.99);
        insert(&mut conn, "/music/abc.flac", &report).unwrap();
        let (count, score): (i64, Vec<u8>) = conn
            .query_row(
                "SELECT count(*), scores_f32_le FROM mood_tracks",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(count, 1);
        assert_eq!(f32::from_le_bytes(score[..4].try_into().unwrap()), 0.99);
        assert_eq!(schema_version(&conn).unwrap(), SCHEMA_VERSION);
    }

    #[test]
    fn invalid_data_not_saved() {
        let mut conn = Connection::open_in_memory().unwrap();
        let mut report = sample();
        assert!(insert(&mut conn, "", &report).is_err());
        report.scores.insert("label00".into(), f32::NAN);
        assert!(insert(&mut conn, "/music/bad.flac", &report).is_err());
        report.scores.insert("label00".into(), 0.1);
        report.scores.remove("label01");
        assert!(insert(&mut conn, "/music/bad.flac", &report).is_err());
    }

    #[test]
    fn never_writes_into_a_bliss_db() {
        let mut conn = Connection::open_in_memory().unwrap();
        conn.execute_batch("CREATE TABLE TracksV2 (File TEXT NOT NULL);").unwrap();
        assert!(insert(&mut conn, "/music/song.flac", &sample()).is_err());
        let has_mood: i64 = conn
            .query_row(
                "SELECT count(*) FROM sqlite_master WHERE name='mood_tracks'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(has_mood, 0);
    }

    #[test]
    fn refuses_other_sqlite_databases() {
        let mut conn = Connection::open_in_memory().unwrap();
        conn.execute_batch("CREATE TABLE private_data (id INTEGER);").unwrap();
        assert!(insert(&mut conn, "/music/song.flac", &sample()).is_err());
    }


    #[test]
    fn v1_migrates_without_losing_analysis() {
        let mut conn = Connection::open_in_memory().unwrap();
        insert(&mut conn, "/music/old.flac", &sample()).unwrap();
        conn.pragma_update(None, "user_version", 1).unwrap();
        conn.execute_batch("DROP TABLE mood_track_state").unwrap();
        create_schema(&conn).unwrap();
        assert_eq!(schema_version(&conn).unwrap(), 3);
        let count: i64 = conn.query_row("SELECT count(*) FROM mood_tracks",[],|r|r.get(0)).unwrap();
        assert_eq!(count, 1);
    }

    #[test]
    fn scanner_skips_only_same_stat_and_model() {
        let mut conn = Connection::open_in_memory().unwrap();
        let report = sample();
        persist_scanned(&mut conn, "/music/a.flac", &report, 1024, 100).unwrap();
        let key = model_key_for(
            report.embedding_model, report.classification_model,
            &report.models_sha256, report.preprocessing_version,
            report.aggregation, &report.scores.keys().cloned().collect::<Vec<_>>(),
            false
        ).unwrap();
        assert!(is_current(&conn, "/music/a.flac", 1024, 100, &key).unwrap());
        assert!(!is_current(&conn, "/music/a.flac", 1025, 100, &key).unwrap());
        assert!(!is_current(&conn, "/music/a.flac", 1024, 101, &key).unwrap());
        assert!(!is_current(&conn, "/music/a.flac", 1024, 100, "different-model").unwrap());
        insert(&mut conn, "/music/a.flac", &report).unwrap();
        assert!(!is_current(&conn, "/music/a.flac", 1024, 100, &key).unwrap());
    }


    #[test]
    fn v2_migrates_without_losing_mood_and_scan_snapshots() {
        let mut conn = Connection::open_in_memory().unwrap();
        let report = sample();
        persist_scanned(&mut conn, "/music/song.flac", &report, 1200, 99).unwrap();
        conn.pragma_update(None, "user_version", 2).unwrap();
        conn.execute_batch("DROP TABLE feature_track_state; DROP TABLE feature_tracks;").unwrap();
        create_schema(&conn).unwrap();
        assert_eq!(schema_version(&conn).unwrap(), 3);
        let model_key = model_key_for(
            report.embedding_model, report.classification_model, &report.models_sha256,
            report.preprocessing_version, report.aggregation,
            &report.scores.keys().cloned().collect::<Vec<_>>(), false
        ).unwrap();
        assert!(is_current(&conn, "/music/song.flac", 1200, 99, &model_key).unwrap());
    }

    #[test]
    fn allows_distinct_label_counts_for_new_model_fingerprints() {
        let hashes = BTreeMap::from([("genre.onnx".to_owned(), "1".repeat(64))]);
        let mood = (0..56).map(|i| format!("label{i}")).collect::<Vec<_>>();
        let genre = (0..87).map(|i| format!("label{i}")).collect::<Vec<_>>();
        let a = model_key_for("encoder", "mood", &hashes, "v4", "mean", &mood, false).unwrap();
        let b = model_key_for("encoder", "genre", &hashes, "v4", "mean", &genre, false).unwrap();
        assert_ne!(a, b);
    }

    #[test]
    fn refuses_other_schema_versions() {
        let mut conn = Connection::open_in_memory().unwrap();
        conn.pragma_update(None, "user_version", 5).unwrap();
        assert!(insert(&mut conn, "/music/abc.flac", &sample()).is_err());
    }
}
