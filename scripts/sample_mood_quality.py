r"""Read-only deterministic feature-quality sample from a copy of bliss.db.

Default remains legacy Mood-only JSON for compatibility. To evaluate three
heads in one shared embedding pass use --models moodtheme,genre,voice.
No command in this script passes --db to the analyzer or changes a source file.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
import csv
import json
import random
import sqlite3
import subprocess
import sys
from pathlib import Path


def normalize_track_key(key):
    parts = key.replace("\\", "/").split("/")
    if not parts or any(part in ("", ".", "..") or ":" in part for part in parts):
        raise ValueError(f"Unsafe relative music path: {key!r}")
    if key.startswith(("/", "\\")):
        raise ValueError(f"Absolute music path rejected: {key!r}")
    return parts


def select_keys(bliss_db, count, seed):
    database = Path(bliss_db).resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Bliss database copy missing: {database}")
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        keys = [key for (key,) in db.execute(
            "SELECT File FROM TracksV2 WHERE Ignore IS NOT 1 ORDER BY File"
        ) if key]
    return random.Random(seed).sample(keys, min(count, len(keys))), len(keys)


def load_classifiers(registry_file, models_dir, model_ids):
    registry = json.loads(registry_file.read_text(encoding="utf-8"))
    catalog = {desc["id"]: desc for desc in registry["models"]}
    result = {}
    for model_id in model_ids:
        if model_id not in catalog or model_id in result:
            raise ValueError(f"Unknown or duplicate classifier: {model_id}")
        descriptor = catalog[model_id]
        classes = json.loads(
            (models_dir / descriptor["metadata"]).read_text(encoding="utf-8")
        )["classes"]
        if len(classes) != descriptor["expected_classes"] or len(set(classes)) != len(classes):
            raise ValueError(f"Invalid label metadata for {model_id}")
        result[model_id] = classes
    return result


def collect_scores(data, classifiers, legacy):
    if legacy:
        scores = {"moodtheme": data["scores"]}
    else:
        scores = {
            model_id: data["classifications"][model_id]["scores"]
            for model_id in classifiers
        }
    for model_id, labels in classifiers.items():
        if set(scores[model_id]) != set(labels):
            raise ValueError(f"Label mismatch for {model_id}")
    return scores



def resolve_workers(spec):
    """Limit parallel analyzer *processes* more strictly than native threads."""
    if spec.lower() == "auto":
        count = os.cpu_count() or 2
        usable = max(1, count - max(2, count // 4))
        return min(4, usable)  # Each process loads its own ONNX models.
    try:
        count = int(spec)
    except ValueError as exc:
        raise ValueError("--workers must be auto or an integer 1..16") from exc
    if not 1 <= count <= 16:
        raise ValueError("--workers must be between 1 and 16")
    return count


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bliss-db", type=Path, required=True)
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--exe", type=Path, required=True)
    p.add_argument("--models-dir", type=Path, required=True)
    p.add_argument("--registry", type=Path)
    p.add_argument("--models", default="moodtheme",
                   help="moodtheme (legacy) or moodtheme,genre,voice (shared-embedding analysis)")
    p.add_argument("--count", type=int, default=12)
    p.add_argument("--seed", type=int, default=20261018)
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--workers", default="1", help="parallel songs: 1 or auto (limited to four child processes)")
    p.add_argument("--timeout-seconds", type=int, default=180)
    p.add_argument("--output", type=Path, default=Path("mood-quality-sample.csv"))
    args = p.parse_args()
    if args.count < 1 or args.count > 100 or args.threads < 1:
        p.error("--count must be 1..100 and --threads must be positive")
    try:
        workers = resolve_workers(args.workers)
    except ValueError as exc:
        p.error(str(exc))
    if workers > 1 and args.threads != 1:
        p.error("parallel --workers requires --threads 1 to avoid ONNX oversubscription")
    if not args.exe.is_file():
        p.error(f"Executable missing: {args.exe}")

    selected = [part.strip() for part in args.models.split(",")]
    legacy = selected == ["moodtheme"]
    registry_file = args.registry or Path(__file__).resolve().parents[1] / "model-registry.json"
    classifiers = load_classifiers(registry_file, args.models_dir, selected)

    keys, total = select_keys(args.bliss_db, args.count, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mood_columns = tuple(classifiers.get("moodtheme", ()))
    other_columns = tuple(
        name
        for model_id, labels in classifiers.items()
        if model_id != "moodtheme"
        for name in (f"{model_id}_top5", *(f"{model_id}:{label}" for label in labels))
    )
    columns = ("track_key", "status", "error", "total_seconds", "patches",
               "preprocessing_version", "top5") + mood_columns + other_columns
    def process_key(key):
        row = {"track_key": key, "status": "error", "error": ""}
        try:
            path = args.source_root.joinpath(*normalize_track_key(key))
            if not path.is_file():
                raise FileNotFoundError(str(path))
            command = [
                str(args.exe.resolve()), "analyze" if legacy else "analyze-features",
                str(path), "--models-dir", str(args.models_dir.resolve()),
                "--threads", str(args.threads), "--json",
            ]
            if not legacy:
                command += ["--models", ",".join(selected)]
                if args.registry:
                    command += ["--registry", str(args.registry.resolve())]
            result = subprocess.run(
                command, check=True, capture_output=True,
                text=True, encoding="utf-8", timeout=args.timeout_seconds,
                creationflags=(subprocess.BELOW_NORMAL_PRIORITY_CLASS
                               if sys.platform == "win32" and args.workers.lower() == "auto"
                               else 0),
            )
            data = json.loads(result.stdout)
            scores = collect_scores(data, classifiers, legacy)
            row.update({
                "status": "ok",
                "total_seconds": round(data["timings"]["total_seconds"], 3),
                "patches": data["patches_analyzed"],
                "preprocessing_version": data["preprocessing_version"],
            })
            for model_id, values in scores.items():
                top = ", ".join(
                    f"{name}={score:.3f}"
                    for name, score in sorted(values.items(), key=lambda pair: -pair[1])[:5]
                )
                if model_id == "moodtheme":
                    row["top5"] = top
                    row.update(values)
                else:
                    row[f"{model_id}_top5"] = top
                    row.update({f"{model_id}:{name}": score
                                for name, score in values.items()})

        except (OSError, ValueError, KeyError,
                subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            row["error"] = str(exc)[:400]
        return row

    success = 0
    with args.output.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        # map keeps the seeded, deterministic CSV ordering even when analysis
        # completion order differs. Only the parent process writes the CSV.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i, (key, row) in enumerate(zip(keys, pool.map(process_key, keys)), 1):
                if row["status"] == "ok":
                    success += 1
                writer.writerow(row)
                fp.flush()
                print(f"[{i}/{len(keys)}] {row['status']}: {key}", file=sys.stderr)
    print(f"Selected {len(keys)} of {total} eligible tracks; {success} succeeded. "
          f"Output: {args.output}")
    if success != len(keys):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
