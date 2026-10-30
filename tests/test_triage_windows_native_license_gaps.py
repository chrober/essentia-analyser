"""Read-only exact-version missing native license evidence backlog tests."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import triage_windows_native_license_gaps as triage
from test_audit_windows_native_release import fixture, overwrite


def missing_notices_kit(base):
    kit, native, provenance = fixture(base)
    key = "mingw-w64-x86_64-libsamplerate"
    provenance["packages"][key]["installed_license_files"] = []
    provenance["packages"][key]["upstream_url"] = "https://example.org/provenance-only"
    overwrite(kit / "NATIVE-PROVENANCE.json", provenance)
    native["files"]["essentia-worker.exe"]["imports"] = [
        "KERNEL32.dll", "libessentia.dll"
    ]
    native["files"]["libessentia.dll"]["imports"] = [
        "libsamplerate-0.dll"
    ]
    native["files"]["libsamplerate-0.dll"]["imports"] = [
        "KERNEL32.dll"
    ]
    overwrite(kit / "essentia-worker/worker-dependencies.json", native)
    return kit, native, provenance


class LicenseGapBacklogTests(unittest.TestCase):
    def test_full_import_reachability_has_evidence_but_release_stays_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit, native, prov = missing_notices_kit(Path(tmp))
            report = triage.plan(kit)
            self.assertEqual(report["binary_integrity"], "PASS")
            self.assertEqual(report["distribution_release_status"], "BLOCKED")
            self.assertEqual(report["native_binary_count"], 3)
            self.assertEqual(report["msys2_package_count"], 1)
            self.assertEqual(report["missing_installed_notice_packages"], 1)
            row = report["review_queue"][0]
            self.assertEqual(row["installed_package_version"], "0.2.2-1")
            self.assertEqual(row["owned_native_binary_names"], ["libsamplerate-0.dll"])
            self.assertEqual(
                row["manifest_recorded_import_chain_examples"][0],
                ["essentia-worker.exe", "libessentia.dll", "libsamplerate-0.dll"]
            )
            self.assertEqual(row["declared_upstream_url_from_pacman_metadata_unverified"],
                             "https://example.org/provenance-only")
            self.assertFalse(row["actual_license_text_validated"])
            self.assertFalse(row["license_compatibility_approved"])

    def test_installed_notice_does_not_count_as_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit, _, _ = fixture(Path(tmp))
            report = triage.plan(kit)
            self.assertEqual(report["missing_installed_notice_packages"], 0)
            self.assertEqual(report["review_queue"], [])
            self.assertEqual(report["distribution_release_status"], "BLOCKED")

    def test_manifest_import_evidence_unavailable_is_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit, _, _ = fixture(Path(tmp))
            result = triage.plan(kit)
            self.assertEqual(result["import_graph_evidence"]["reachable_binaries"], 1)
            self.assertEqual(len(result["import_graph_evidence"][
                "manifest_entries_without_import_list"
            ]), 3)

    def test_broken_hash_or_forged_approval_cannot_generate_valid_backlog(self):
        for kind in ("tamper", "approval"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                kit, native, prov = missing_notices_kit(Path(tmp))
                if kind == "tamper":
                    dll = kit / "essentia-worker/libessentia.dll"
                    dll.write_bytes(dll.read_bytes() + b"tamper")
                else:
                    prov["release_approved"] = True
                    overwrite(kit / "NATIVE-PROVENANCE.json", prov)
                with self.assertRaises((ValueError, AssertionError)):
                    triage.plan(kit)

    def test_orphan_source_package_owner_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit, native, prov = missing_notices_kit(Path(tmp))
            prov["packages"]["unreferenced-package"] = {
                "name": "unreferenced-package", "version": "1",
                "declared_licenses": "UNKNOWN", "installed_license_files": [],
            }
            overwrite(kit / "NATIVE-PROVENANCE.json", prov)
            with self.assertRaisesRegex(AssertionError, "not an owner"):
                triage.plan(kit)

    def test_no_write_to_kit_or_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kit, native, prov = missing_notices_kit(root)
            before = (kit / "NATIVE-PROVENANCE.json").read_bytes()
            report = triage.plan(kit)
            self.assertEqual(before, (kit / "NATIVE-PROVENANCE.json").read_bytes())
            self.assertEqual(report["missing_installed_notice_packages"], 1)


if __name__ == "__main__":
    unittest.main()
