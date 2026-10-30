//! CLI-only numerical reference for the native Essentia C++ parity workflow.
//! Reuses the ACTUAL existing Rust Mel implementation; never links ONNX Runtime.
//! Production decoding and sample-rate conversion is reused verbatim,
//! permitting comparisons of mono WAV, stereo WAV, FLAC and MP3.
#[path = "../../../src/preprocess.rs"]
mod preprocess;
#[path = "../../../src/audio_decode.rs"]
mod audio_decode;

use anyhow::{bail, Context, Result};
use std::{env, path::Path};

fn main() -> Result<()> {
    let mut args = env::args_os();
    let _program = args.next();
    if args.next().as_deref() != Some(std::ffi::OsStr::new("mel-dump")) {
        bail!("Usage: rust-mel-reference mel-dump WAV --max-frames 1024");
    }
    let source = args.next().context("Expected WAV source")?;
    if args.next().as_deref() != Some(std::ffi::OsStr::new("--max-frames")) {
        bail!("Expected --max-frames");
    }
    let limit = args.next().context("Missing max-frames value")?
        .to_string_lossy().parse::<usize>()?;
    if !(1..=1024).contains(&limit) || args.next().is_some() {
        bail!("Max frames must be 1..=1024 and no extra arguments are allowed");
    }

    let samples = audio_decode::ffmpeg_pcm_mono_16k(Path::new(&source))?;
    let frames = preprocess::mel_spectrogram(&samples)?;
    println!("{}", serde_json::json!({
        "total_frames": frames.len(),
        "frames": frames.iter().take(limit).map(|frame| frame.as_slice()).collect::<Vec<_>>(),
    }));
    Ok(())
}
