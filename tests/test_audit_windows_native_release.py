"""Offline release-readiness inventory checks; no audio/network/native DLL distribution."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_windows_native_release as audit
from package_essentia_worker_windows import sha256
from test_package_essentia_worker_windows import fake_pe


def fixture(root):
    kit = root / "dev-kit"
    worker = kit / "essentia-worker"
    worker.mkdir(parents=True)
    names = ("essentia-worker.exe", "libessentia.dll",
             "libsamplerate-0.dll")
    for name in names:
        fake_pe(worker / name)
    paths = {
        "THIRD-PARTY-NOTICES/essentia-upstream/COPYING.txt": "AGPL",
        "THIRD-PARTY-NOTICES/essentia-analyser-project/LICENSE": "MIT",
        "THIRD-PARTY-NOTICES/mingw-w64-x86_64-libsamplerate/001-LICENSE.txt":
            "libsamplerate license",
    }
    for name, text in paths.items():
        dst = kit / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
    manifest = {
        "schema_version": 1, "platform": "windows-x86_64-mingw64",
        "release_approved": False,
        "license_inventory_complete": False,
        "requires_distribution_license_review": True,
        "worker_executable": names[0],
        "files": {
            name: {
                "size_bytes": (worker / name).stat().st_size,
                "sha256": sha256(worker / name),
            }
            for name in names
        },
    }
    provenance = {
        "schema_version": 1,
        "kind": "windows-development-binary-license-provenance-not-release-audit",
        "release_approved": False,
        "license_inventory_complete": False,
        "requires_distribution_license_review": True,
        "complete_binary_origin_mapping": True,
        "binaries": {
            names[0]: {
                "origin": "this project", "license_notices": [
                    "THIRD-PARTY-NOTICES/essentia-analyser-project/LICENSE"
                ],
            },
            names[1]: {
                "origin": "upstream Essentia", "license_notices": [
                    "THIRD-PARTY-NOTICES/essentia-upstream/COPYING.txt"
                ],
            },
            names[2]: {
                "origin": "MSYS2 mingw64",
                "package": "mingw-w64-x86_64-libsamplerate",
            },
        },
        "packages": {
            "mingw-w64-x86_64-libsamplerate": {
                "name": "mingw-w64-x86_64-libsamplerate",
                "version": "0.2.2-1",
                "declared_licenses": "BSD",
                "installed_license_files": [
                    "THIRD-PARTY-NOTICES/mingw-w64-x86_64-libsamplerate/001-LICENSE.txt"
                ],
            }
        },
    }
    (worker / "worker-dependencies.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (kit / "NATIVE-PROVENANCE.json").write_text(
        json.dumps(provenance), encoding="utf-8"
    )
    return kit, manifest, provenance


def overwrite(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


class WindowsNativeReleaseAuditTests(unittest.TestCase):
    def test_intact_dev_kit_passes_integrity_but_cannot_be_distribution_approved(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, manifest, provenance = fixture(Path(temp))
            result = audit.audit(kit)
            self.assertEqual(result["binary_integrity"], "PASS")
            self.assertEqual(result["distribution_release_status"], "BLOCKED")
            self.assertTrue(result["review_required"])
            self.assertEqual(result["native_binary_count"], 3)
            self.assertEqual(result["package_count"], 1)
            self.assertEqual(result["installed_notice_file_references_verified"], 3)
            self.assertFalse(result["packages_without_installed_notices"])
            self.assertFalse(result["missing_notice_references"])

    def test_pe_tampering_fails_integrity_even_with_apparent_license_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, _, _ = fixture(Path(temp))
            dll = kit / "essentia-worker/libessentia.dll"
            dll.write_bytes(dll.read_bytes() + b"altered")
            with self.assertRaises(ValueError):
                audit.audit(kit)

    def test_release_approval_flags_cannot_be_forged(self):
        for target, field, value in (
            ("manifest", "release_approved", True),
            ("manifest", "license_inventory_complete", True),
            ("provenance", "release_approved", True),
            ("provenance", "license_inventory_complete", True),
            ("provenance", "requires_distribution_license_review", False),
        ):
            with self.subTest(target=target, field=field):
                with tempfile.TemporaryDirectory() as temp:
                    kit, manifest, prov = fixture(Path(temp))
                    obj = manifest if target == "manifest" else prov
                    obj[field] = value
                    path = kit / ("essentia-worker/worker-dependencies.json"
                                  if target == "manifest" else "NATIVE-PROVENANCE.json")
                    overwrite(path, obj)
                    with self.assertRaises(AssertionError):
                        audit.audit(kit)

    def test_binary_origin_inventory_must_exactly_match_actual_dll_closure(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, manifest, provenance = fixture(Path(temp))
            provenance["binaries"].pop("libsamplerate-0.dll")
            overwrite(kit / "NATIVE-PROVENANCE.json", provenance)
            with self.assertRaisesRegex(AssertionError, "closure names differ"):
                audit.audit(kit)

    def test_missing_installed_package_notice_is_explicit_release_blocker(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, manifest, provenance = fixture(Path(temp))
            name = "mingw-w64-x86_64-libsamplerate"
            provenance["packages"][name]["installed_license_files"] = []
            overwrite(kit / "NATIVE-PROVENANCE.json", provenance)
            result = audit.audit(kit)
            self.assertEqual(result["packages_without_installed_notices"], [name])
            self.assertEqual(result["distribution_release_status"], "BLOCKED")
            self.assertTrue(any("lack installed license" in b for b in result["blockers"]))

    def test_missing_referenced_license_file_is_reported_not_silently_approved(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, _, provenance = fixture(Path(temp))
            p = kit / provenance["packages"]["mingw-w64-x86_64-libsamplerate"][
                "installed_license_files"
            ][0]
            p.unlink()
            result = audit.audit(kit)
            self.assertEqual(len(result["missing_notice_references"]), 1)
            self.assertEqual(result["distribution_release_status"], "BLOCKED")

    def test_bad_path_or_unpinned_package_metadata_fails_closed(self):
        for problem in ("traversal", "missing_version", "missing_package"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as temp:
                kit, _, provenance = fixture(Path(temp))
                key = "mingw-w64-x86_64-libsamplerate"
                if problem == "traversal":
                    provenance["packages"][key]["installed_license_files"] = ["../outside.txt"]
                elif problem == "missing_version":
                    provenance["packages"][key]["version"] = None
                else:
                    provenance["binaries"]["libsamplerate-0.dll"]["package"] = "unknown"
                overwrite(kit / "NATIVE-PROVENANCE.json", provenance)
                with self.assertRaises(AssertionError):
                    audit.audit(kit)

    def test_missing_provenance_file_never_implies_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            kit, _, _ = fixture(Path(temp))
            (kit / "NATIVE-PROVENANCE.json").unlink()
            with self.assertRaises(FileNotFoundError):
                audit.audit(kit)


if __name__ == "__main__":
    unittest.main()
