"""Offline tests for adaptive v5 cohort: no original DB or private audio rescans."""
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import json
import shutil
import sqlite3
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_rust_v5_adaptive as audit
from test_verify_rust_v5_cohort import make_cohort


def synthetic_telemetry(*, changed=True):
    changes = [
        {"from_workers": 6, "to_workers": 5, "after_completed_songs": 40,
         "reason": "sustained CPU/RAM pressure"},
        {"from_workers": 5, "to_workers": 6, "after_completed_songs": 70,
         "reason": "sustained CPU/RAM headroom"},
    ] if changed else []
    return {
        "initial_workers": 6, "final_workers": 6, "peak_workers": 6,
        "peak_in_flight": 6, "peak_active_analyses": 6,
        "system_load_samples": 100, "system_cpu_average_percent": 53.1,
        "system_cpu_max_percent": 96.0,
        "system_ram_max_percent": 82.0,
        "process_working_set_max_mib": 1650.0,
        "controller_decisions": {
            "high_load_samples": 10, "low_load_samples": 33,
            "neutral_load_samples": 57,
            "increases": 1 if changed else 0,
            "decreases": 1 if changed else 0,
        },
        "adjustments": changes,
    }


def args_for(root, cohort, old, cpp, fixed, scanner):
    baseline = root / "four-worker"
    baseline.mkdir()
    fixed_db = baseline / "round-01-workers-04-rust.db"
    shutil.copyfile(fixed, fixed_db)
    baseline_report = baseline / "parity-report-private.json"
    baseline_report.write_text(json.dumps({
        "numeric_parity_status": "PASS", "worker_count": 4,
        "cohort_songs": 2, "score_components": 290,
        "rust_v5_scan": {
            "sqlite": fixed_db.name, "workers": 4, "seconds": 20.0,
        }
    }), encoding="utf-8")
    return SimpleNamespace(
        cohort_db=cohort, old_rust_db=old, essentia_db=cpp,
        fixed_db=fixed_db, fixed_report=baseline_report,
        analyzer=scanner, models_dir=root, source_root=root,
        output_dir=root / "new-adaptive",
        workers=6, min_workers=4, max_workers=8,
        expected_songs=2, tolerance=0.001,
    )


class AdaptiveRealCohortTests(unittest.TestCase):
    def test_controller_history_and_no_change_are_both_valid(self):
        for active in (True, False):
            with self.subTest(actual_adjustments=active):
                report = {
                    "analyzed": 100, "failures": 0, "missing_files": 0,
                    "pending": 100, "workers": 6,
                    "diagnostics": synthetic_telemetry(changed=active),
                }
                result = audit.audit_controller(report, 6, 4, 8, 100)
                self.assertEqual(len(result["adjustments"]), 2 if active else 0)
                self.assertEqual(result["final_workers"], 6)

    def test_bad_controller_report_is_not_silently_accepted(self):
        report = {
            "analyzed": 100, "failures": 0, "missing_files": 0,
            "pending": 100, "workers": 6,
            "diagnostics": synthetic_telemetry(),
        }
        for name in ("controller_decisions", "adjustments", "initial_workers"):
            invalid = json.loads(json.dumps(report))
            invalid["diagnostics"].pop(name)
            with self.subTest(missing=name):
                with self.assertRaises(AssertionError):
                    audit.audit_controller(invalid, 6, 4, 8, 100)
        report["diagnostics"]["adjustments"][0]["to_workers"] = 9
        with self.assertRaisesRegex(AssertionError, "violates min/max"):
            audit.audit_controller(report, 6, 4, 8, 100)

    def test_adaptive_scan_command_has_real_flags_and_single_thread(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            out = root / "new-adaptive"
            out.mkdir()
            args = SimpleNamespace(
                output_dir=out, analyzer=root / "scanner.exe",
                cohort_db=root / "subset.db", models_dir=root,
                source_root=root, workers=6, min_workers=4, max_workers=8,
            )
            captured = []

            def stub_subprocess(command, stdout, stderr, check):
                captured.append(command)
                stdout.write(json.dumps({
                    "analyzed": 2, "failures": 0, "missing_files": 0,
                    "pending": 2, "workers": 6,
                    "diagnostics": synthetic_telemetry(changed=False),
                }))
                (out / "rust-v5-adaptive-workers.db").write_bytes(b"fake sqlite")
                return SimpleNamespace(returncode=0)

            with patch.object(audit.subprocess, "run", side_effect=stub_subprocess):
                db, seconds, telemetry = audit.invoke_once(args, 2)
            self.assertTrue(db.is_file())
            self.assertGreater(seconds, 0)
            self.assertEqual(telemetry["initial_workers"], 6)
            self.assertEqual(len(captured), 1)
            cmd = captured[0]
            for flag, value in (("--workers", "6"), ("--min-workers", "4"),
                                ("--max-workers", "8"), ("--threads", "1"),
                                ("--max-new", "2"), ("--audio-backend", "rust")):
                self.assertEqual(cmd[cmd.index(flag) + 1], value)
            self.assertIn("--adaptive-workers", cmd)
            self.assertNotIn("--essentia-worker", cmd)

    def test_real_adapter_one_scan_and_reference_sidecars_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cohort, old, cpp, fixed = make_cohort(root)
            scanner = root / "scanner.exe"
            scanner.write_bytes(b"pretend pinned scanner")
            args = args_for(root, cohort, old, cpp, fixed, scanner)
            sources = (cohort, old, cpp, args.fixed_db, args.fixed_report, scanner)
            before = tuple(audit.digest(p) for p in sources)

            def stub_once(run_args, expected):
                self.assertEqual(expected, 2)
                self.assertEqual((run_args.workers, run_args.min_workers,
                                  run_args.max_workers), (6, 4, 8))
                db = run_args.output_dir / "rust-v5-adaptive-workers.db"
                shutil.copyfile(fixed, db)
                return db, 16.0, audit.audit_controller({
                    "analyzed": 2, "failures": 0, "missing_files": 0,
                    "pending": 2, "workers": 6,
                    "diagnostics": synthetic_telemetry(changed=False),
                }, 6, 4, 8, 2)

            printed = StringIO()
            with patch.object(audit, "invoke_once", side_effect=stub_once) as run_mock:
                with redirect_stdout(printed):
                    report = audit.run(args)
            self.assertNotIn("artist/song-", printed.getvalue())
            self.assertIn('"per_head_cpp_max_difference"', printed.getvalue())
            run_mock.assert_called_once()
            self.assertEqual(report["acceptance_status"], "PASS")
            self.assertEqual(report["worker_count_invariance_vs_fixed_four"]["status"], "PASS")
            self.assertTrue(report["worker_count_invariance_vs_fixed_four"]["exact_bitwise_equal_scores"])
            self.assertEqual(report["performance"]["adaptive_vs_fixed_four_speedup"], 1.25)
            self.assertTrue((args.output_dir / "adaptive-parity-and-performance-private.json").exists())
            self.assertEqual(before, tuple(audit.digest(p) for p in sources))

    def test_different_workers_can_fail_and_do_not_relax_score_tolerance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cohort, old, cpp, fixed = make_cohort(root)
            adaptive_db = root / "adaptive.db"
            shutil.copyfile(fixed, adaptive_db)
            with closing(sqlite3.connect(adaptive_db)) as conn:
                with conn:
                    conn.execute(
                        "UPDATE feature_tracks SET scores_f32_le=? "
                        "WHERE track_file='artist/song-00.mp3' AND model_id='voice'",
                        (sqlite3.Binary(struct.pack("<2f", 0.205, 0.2)),),
                    )
            result = audit.compare_adaptive(cohort, old, cpp, fixed, adaptive_db, 0.001)
            self.assertEqual(result["acceptance_status"], "FAIL")
            self.assertEqual(result["worker_count_invariance_vs_fixed_four"]["status"], "FAIL")

    def test_fail_preflight_before_any_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cohort, old, cpp, fixed = make_cohort(root)
            scanner = root / "scanner.exe"
            scanner.write_bytes(b"valid")
            args = args_for(root, cohort, old, cpp, fixed, scanner)
            args.min_workers = 7
            with patch.object(audit, "invoke_once") as do_scan:
                with self.assertRaisesRegex(ValueError, "initial"):
                    audit.run(args)
            do_scan.assert_not_called()
            self.assertFalse(args.output_dir.exists())


if __name__ == "__main__":
    unittest.main()
