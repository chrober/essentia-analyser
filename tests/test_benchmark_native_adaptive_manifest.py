"""Regression tests for local-only bounded native adaptive scanner benchmark."""
from __future__ import annotations

import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import benchmark_native_adaptive_manifest as bench


class NativeAdaptiveManifestTests(unittest.TestCase):
    def test_relative_bliss_keys_are_manifest_compatible(self):
        keys = ["Artist/Album/a.mp3", "Other\\Album\\b.flac"]
        self.assertEqual(bench.prepare_manifest_keys(keys, None), [
            "Artist/Album/a.mp3", "Other/Album/b.flac",
        ])

    def test_library_root_remapping_is_explicit(self):
        keys = ["/mnt/music/Artist/Album/a.mp3"]
        self.assertEqual(bench.prepare_manifest_keys(keys, "/mnt/music"),
                         ["Artist/Album/a.mp3"])
        self.assertEqual(
            bench.prepare_manifest_keys(
                ["D:\\Music\\Artist\\track.mp3"], "D:\\Music"
            ), ["Artist/track.mp3"])
        with self.assertRaises(ValueError):
            bench.prepare_manifest_keys(["/another/music/a.mp3"], "/mnt/music")

    def test_rejects_unsafe_or_ambiguous_paths(self):
        bad = [
            "", "/absolute.wav", "C:\\music\\song.mp3", "a//b.mp3",
            "a/../b.mp3", "a/./b.mp3", "a\\..\\b.mp3", " song.mp3",
            "song.mp3 ", "a\nb.mp3", "a\r.mp3", "a\x00b.mp3",
        ]
        for key in bad:
            with self.subTest(key=repr(key)), self.assertRaises(ValueError):
                bench.normalize_manifest_key(key, None)
        with self.assertRaises(ValueError):
            bench.prepare_manifest_keys(["a/b.mp3", "a\\b.mp3"], None)

    def test_two_repeats_reverse_execution_order(self):
        first = bench.schedule(2, 20261022)
        self.assertEqual(len(first), 10)
        self.assertEqual(first[:5], [
            (1, mode) for mode in reversed([p[1] for p in first[5:]])
        ])
        self.assertEqual(set(name for _, name in first), {
            "fixed1", "fixed2", "fixed4", "fixed6", "adaptive2",
        })

    def test_policy_matrix_is_balanced_and_mappings_are_correct(self):
        plan = bench.schedule(2, 20261022, "adaptive-policy")
        self.assertEqual(len(plan), 10)
        self.assertEqual(plan[:5], [(1, m) for _, m in reversed(plan[5:])])
        self.assertEqual({mode for _, mode in plan}, set(bench.POLICY_MODES))
        self.assertEqual(bench.mode_configuration("fixed6"), (6, False, 1, 24))
        self.assertEqual(bench.mode_configuration("adaptive2"), (2, True, 1, 24))
        self.assertEqual(bench.mode_configuration("adaptive2_gate24"), (2, True, 2, 24))
        self.assertEqual(bench.mode_configuration("adaptive4_gate24"), (4, True, 2, 24))
        self.assertEqual(bench.mode_configuration("adaptive6_gate24"), (6, True, 2, 24))
        self.assertEqual(bench.mode_configuration("adaptive2_gate8"), (2, True, 2, 8))
        with self.assertRaises(ValueError):
            bench.mode_configuration("adaptive99_gate0")

    def test_native_scaling_matrix_is_balanced_and_never_adaptive(self):
        plan = bench.schedule(2, 20261028, "native-scaling")
        self.assertEqual(len(plan), 8)
        self.assertEqual(plan[:4], [(1, m) for _, m in reversed(plan[4:])])
        self.assertEqual({mode for _, mode in plan}, set(bench.SCALING_MODES))
        for workers in (6, 8, 10, 12):
            self.assertEqual(bench.mode_configuration(f"fixed{workers}"),
                             (workers, False, 1, 24))

    def test_ram_guard_fails_closed_and_preserves_healthy_sample(self):
        healthy = {"available_mib": 2100., "total_mib": 16384.,
                   "ram_percent": 85.}
        self.assertIsNone(bench.memory_guard_reason(healthy, 1536, 90))
        self.assertIn("Unable to read",
                      bench.memory_guard_reason(None, 1536, 90))
        self.assertIn("below safety reserve",
                      bench.memory_guard_reason({**healthy, "available_mib": 1500},
                                                1536, 90))
        self.assertIn("at/above safety limit",
                      bench.memory_guard_reason({**healthy, "ram_percent": 90},
                                                1536, 90))
        self.assertIn("Invalid",
                      bench.memory_guard_reason({**healthy, "ram_percent": float("nan")},
                                                1536, 90))

    def test_ram_guard_rejects_before_spawning_if_reserve_is_violated(self):
        good = {"available_mib": 2000., "total_mib": 16000., "ram_percent": 85.}
        with patch.object(bench, "windows_memory_snapshot",
                          return_value={**good, "available_mib": 1000}):
            with patch.object(bench.subprocess, "Popen") as spawn:
                with self.assertRaisesRegex(RuntimeError, "preflight"):
                    bench.run_scanner_guarded(["ignored"], None, None, 1536, 90)
                spawn.assert_not_called()

    def test_ram_guard_terminates_running_scanner_on_pressure(self):
        healthy = {"available_mib": 2400., "total_mib": 16000.,
                   "ram_percent": 85.}
        pressure = {**healthy, "available_mib": 1400.}

        class FakeProcess:
            pid = 43210
            killed = False
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def poll(self):
                return 1 if self.killed else None
            def kill(self):
                self.killed = True
            def wait(self):
                self.killed = True
                return 1

        fake = FakeProcess()
        with patch.object(bench, "windows_memory_snapshot",
                          side_effect=[healthy, pressure]):
            with patch.object(bench.subprocess, "Popen", return_value=fake) as spawn:
                # Never invoke real Windows taskkill against a fabricated PID.
                with patch.object(bench.subprocess, "run") as terminate_tree:
                    with self.assertRaisesRegex(RuntimeError, "RAM safety stop"):
                        bench.run_scanner_guarded(["scanner", "--workers", "12"],
                                                  None, None, 1536, 90)
                    spawn.assert_called_once()
                    self.assertTrue(fake.killed)
                    if bench.os.name == "nt":
                        terminate_tree.assert_called_once()
                    else:
                        terminate_tree.assert_not_called()

    def test_policy_modes_emit_exact_requested_gate_and_start_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opts = argparse.Namespace(
                analyzer=root / "bliss-mood.exe", essentia_worker=root / "worker.exe",
                source_root=root / "music", manifest_file=root / "tracks.txt",
                models_dir=root / "models", models="moodtheme,genre,voice",
                timeout_seconds=900, scan_priority="normal",
                min_available_ram_mib=1536, max_system_ram_percent=90, output_dir=root,
            )
            class Captured(Exception):
                pass
            for mode in bench.POLICY_MODES:
                workers, adaptive, minimum, gate = bench.mode_configuration(mode)
                with patch.object(bench, "run_scanner_guarded", side_effect=Captured) as run:
                    with self.assertRaises(Captured):
                        bench.analyze(opts, 1, mode, 100)
                cmd = run.call_args.args[0]
                self.assertEqual(cmd[cmd.index("--workers") + 1], str(workers))
                self.assertEqual("--adaptive-workers" in cmd, adaptive)
                if adaptive:
                    self.assertEqual(cmd[cmd.index("--min-workers") + 1], str(minimum))
                    self.assertEqual(cmd[cmd.index("--adaptive-min-completed-songs") + 1], str(gate))
                else:
                    self.assertNotIn("--adaptive-min-completed-songs", cmd)

    def test_scaling_commands_use_exact_fixed_worker_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opts = argparse.Namespace(
                analyzer=root / "bliss-mood.exe", essentia_worker=root / "worker.exe",
                source_root=root / "music", manifest_file=root / "tracks.txt",
                models_dir=root / "models", models="moodtheme,genre,voice",
                timeout_seconds=900, scan_priority="normal",
                min_available_ram_mib=1536, max_system_ram_percent=90,
                output_dir=root,
            )
            class Captured(Exception):
                pass
            for mode in bench.SCALING_MODES:
                with self.subTest(mode=mode):
                    with patch.object(bench, "run_scanner_guarded",
                                      side_effect=Captured) as run:
                        with self.assertRaises(Captured):
                            bench.analyze(opts, 1, mode, 100)
                    cmd = run.call_args.args[0]
                    self.assertNotIn("--adaptive-workers", cmd)
                    self.assertEqual(cmd[cmd.index("--workers") + 1],
                                     mode.removeprefix("fixed"))
                    self.assertEqual(cmd[cmd.index("--priority") + 1], "normal")
                    self.assertEqual(run.call_args.args[3:], (1536, 90))

    def test_preflight_rejects_missing_music_and_symlink_escapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "music"
            root.mkdir()
            (root / "one.mp3").write_bytes(b"stub")
            bench.verify_music_paths(["one.mp3"], root)
            with self.assertRaisesRegex(ValueError, "unavailable"):
                bench.verify_music_paths(["missing.mp3"], root)
            outside = base / "other.mp3"
            outside.write_bytes(b"stub")
            link = root / "escape.mp3"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                return  # Symlink privileges are optional on Windows.
            with self.assertRaisesRegex(ValueError, "outside"):
                bench.verify_music_paths(["escape.mp3"], root)

    def test_scan_command_uses_manifest_and_not_bliss_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            options = argparse.Namespace(
                analyzer=root / "bliss-mood", essentia_worker=root / "native-worker",
                source_root=root / "music", manifest_file=root / "tracks.txt",
                models_dir=root / "models", models="moodtheme,genre,voice",
                timeout_seconds=900, scan_priority="normal",
                min_available_ram_mib=1536, max_system_ram_percent=90,
                output_dir=root / "results",
            )
            options.output_dir.mkdir()
            class Capture(Exception):
                pass
            with patch.object(bench, "run_scanner_guarded", side_effect=Capture) as run:
                with self.assertRaises(Capture):
                    bench.analyze(options, 1, "adaptive2", 100)
                arguments = run.call_args.args[0]
            self.assertIn("--tracks-file", arguments)
            self.assertIn("--source-root", arguments)
            self.assertIn("--embedding-dir", arguments)
            self.assertNotIn("--bliss-db", arguments)
            self.assertNotIn("--library-root", arguments)
            self.assertIn("--adaptive-workers", arguments)
            self.assertEqual(arguments[arguments.index("--priority") + 1], "normal")
            self.assertEqual(arguments[arguments.index("--max-new") + 1], "100")

    def test_exact_feature_rows_include_all_three_heads_not_just_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "features.sqlite"
            keys = ["Artist/one.mp3", "Artist/two.mp3"]
            heads = ["moodtheme", "genre", "voice"]
            conn = sqlite3.connect(db)
            conn.execute(
                "CREATE TABLE feature_tracks (track_file TEXT, model_id TEXT, "
                "model_key TEXT, audio_sha256 TEXT, patches_analyzed INTEGER, "
                "scores_f32_le BLOB)"
            )
            dims = {"moodtheme": 56, "genre": 87, "voice": 2}
            for key in keys:
                for head in heads:
                    values = bytes(dims[head] * 4)
                    conn.execute(
                        "INSERT INTO feature_tracks VALUES (?,?,?,?,?,?)",
                        (key, head, "stable-model-fingerprint", "a" * 64, 4, values),
                    )
            conn.commit()
            conn.close()
            all_rows = bench.exact_feature_rows(db, keys, heads)
            self.assertEqual(len(all_rows), 6)
            self.assertEqual(
                set(all_rows), {(track, head) for track in keys for head in heads},
            )
            # sqlite3.Connection.__exit__ commits, but does NOT close.
            # Keep both contexts so Windows can delete features.sqlite on exit.
            with closing(sqlite3.connect(db)) as changed, changed:
                changed.execute(
                    "UPDATE feature_tracks SET scores_f32_le=? "
                    "WHERE track_file=? AND model_id=?",
                    (bytes([1]) + bytes(dims["moodtheme"] * 4 - 1), keys[0], "moodtheme"),
                )
            self.assertNotEqual(
                bench.exact_feature_rows(db, keys, heads), all_rows,
                "Changing only mood must not be hidden by a last-head-wins map",
            )
            with closing(sqlite3.connect(db)) as deleted, deleted:
                deleted.execute(
                    "DELETE FROM feature_tracks WHERE track_file=? AND model_id=?",
                    (keys[1], "genre"),
                )
            with self.assertRaisesRegex(AssertionError, "coverage"):
                bench.exact_feature_rows(db, keys, heads)

    def test_benchmark_rejects_mismatched_or_unobserved_child_priority(self):
        # A successful scan must not be classified as a fair comparison unless
        # BOTH parent and actual native child process classes match.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opts = argparse.Namespace(
                analyzer=root / "analyzer.exe", essentia_worker=root / "worker.exe",
                source_root=root / "music", manifest_file=root / "tracks.txt",
                models_dir=root / "models", models="moodtheme",
                timeout_seconds=900, scan_priority="normal",
                min_available_ram_mib=1536, max_system_ram_percent=90, output_dir=root / "out",
            )
            opts.output_dir.mkdir()
            fake = {
                "analyzed": 100, "pending": 100, "failures": 0, "missing_files": 0,
                "elapsed_seconds": 10.0,
                "priority": {
                    "requested": "normal", "policy": "normal",
                    "effective_scanner": "normal",
                    "native_worker_classes": ["below-normal"],
                    "native_worker_observation_failures": 0,
                },
                "diagnostics": {"baseline": {"cpu_measurement_seconds": 0.0}},
            }
            result = argparse.Namespace(returncode=0)
            def fake_run(*args, **kwargs):
                (opts.output_dir / "round-01-fixed2.scanner.json").write_text(
                    __import__("json").dumps(fake), encoding="utf-8"
                )
                return (result.returncode, 2000.0)
            with patch.object(bench, "run_scanner_guarded", side_effect=fake_run):
                with self.assertRaisesRegex(AssertionError, "native Essentia worker priority"):
                    bench.analyze(opts, 1, "fixed2", 100)

    def test_plan_only_on_exact_local_30_track_sqlite_cohort(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            audio = base / "music"
            audio.mkdir()
            models = base / "models"
            models.mkdir()
            cohort = base / "sample-30.db"
            conn = sqlite3.connect(cohort)
            conn.execute("CREATE TABLE TracksV2 (File TEXT, Ignore INTEGER)")
            for i in range(30):
                key = f"artist_{i:02d}/song.flac"
                folder = audio / f"artist_{i:02d}"
                folder.mkdir()
                (folder / "song.flac").write_bytes(b"placeholder")
                conn.execute("INSERT INTO TracksV2 VALUES (?, ?)", (key, 0))
            conn.commit()
            conn.close()
            exe = base / "bliss-mood.exe"
            native = base / "bliss-essentia-worker.exe"
            exe.write_bytes(b"stub")
            native.write_bytes(b"stub")
            out = base / "output"
            argv = [
                "--cohort-db", str(cohort), "--analyzer", str(exe),
                "--essentia-worker", str(native),
                "--models-dir", str(models), "--source-root", str(audio),
                "--output-dir", str(out), "--plan-only",
            ]
            with patch.object(sys, "argv", ["benchmark_native_adaptive_manifest.py", *argv]):
                bench.main()
            self.assertFalse(out.exists(), "plan-only must not write files")


if __name__ == "__main__":
    unittest.main()
