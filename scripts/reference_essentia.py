"""Essentia reference for verification. Requires essentia-tensorflow + official .pb weights.

Usage:
    python scripts/reference_essentia.py path/to/song.flac --models-dir models

Download additional reference weights from the official MTG directories:
- feature-extractors/discogs-effnet/discogs-effnet-bs64-1.pb
- classification-heads/mtg_jamendo_moodtheme/mtg_jamendo_moodtheme-discogs-effnet-1.pb
"""
import argparse
import json
from pathlib import Path

import numpy as np
from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs, TensorflowPredict2D


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--models-dir", type=Path, default=Path("models"))
    args = parser.parse_args()
    audio = MonoLoader(filename=str(args.audio), sampleRate=16000, resampleQuality=4)()
    embeddings = TensorflowPredictEffnetDiscogs(
        graphFilename=str(args.models_dir / "discogs-effnet-bs64-1.pb"),
        output="PartitionedCall:1",
    )(audio)
    predictions = TensorflowPredict2D(
        graphFilename=str(args.models_dir / "mtg_jamendo_moodtheme-discogs-effnet-1.pb")
    )(embeddings)
    labels = json.loads(
        (args.models_dir / "mtg_jamendo_moodtheme-discogs-effnet-1.json").read_text()
    )["classes"]
    values = np.asarray(predictions).mean(axis=0)
    assert values.shape == (56,), values.shape
    print(json.dumps({
        "model": "essentia-reference",
        "scores": dict(zip(labels, map(float, values)))
    }, indent=2))


if __name__ == "__main__":
    main()
