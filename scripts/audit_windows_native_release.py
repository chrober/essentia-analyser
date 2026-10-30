#!/usr/bin/env python3
"""Read-only integrity/provenance audit for existing Windows Essentia dev kit.

This script does NOT grant redistribution permission. It validates the actual
packaged PE x64 DLL closure against worker-dependencies.json, links the
separately generated MSYS2/native provenance to those precise binary names,
checks installed notice files, and reports outstanding release blockers.

Source kit is never modified. Optional --output-dir MUST be a new folder.
No source audio, ONNX weights, model downloads or network operations.
"""
import argparse
import json
from pathlib import Path
import sys

from package_essentia_worker_windows import verify as verify_native


def load_object(path):
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"Missing regular provenance/manifest file: {path.name}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise AssertionError(f"Expected JSON object: {path.name}")
    return obj


def check_reference_path(kit_root, relative):
    if (not isinstance(relative, str) or not relative
            or "\\" in relative or relative.startswith("/")):
        raise AssertionError("Unsafe notice reference path")
    path = Path(relative)
    if any(part in ("", ".", "..") or ":" in part for part in path.parts):
        raise AssertionError("Unsafe traversing notice reference")
    dest = kit_root.joinpath(*path.parts)
    if dest.is_symlink() or not dest.resolve().is_relative_to(kit_root.resolve()):
        raise AssertionError("Notice points outside kit root or through symlink")
    if not dest.is_file():
        return False
    if dest.stat().st_size == 0:
        raise AssertionError("Empty notice file")
    return True


def audit(kit_root):
    if not kit_root.is_dir():
        raise FileNotFoundError("Missing Windows native dev kit root")
    if kit_root.is_symlink():
        raise ValueError("Refuse symbolic-link kit root")
    worker_dir = kit_root / "essentia-worker"
    if not worker_dir.is_dir() or worker_dir.is_symlink():
        raise FileNotFoundError("Missing original Essentia C++ worker directory")
    # Reuse existing strict PE-x64 SHA256/size integrity implementation.
    native = verify_native(worker_dir)
    if (native.get("platform") != "windows-x86_64-mingw64"
            or native.get("release_approved") is not False
            or native.get("license_inventory_complete") is not False
            or native.get("requires_distribution_license_review") is not True):
        raise AssertionError(
            "Not the expected unapproved Windows dev-only manifest; "
            "do not treat any altered release flag as approval"
        )
    files = native.get("files")
    worker = native.get("worker_executable")
    if not isinstance(files, dict) or worker not in files or not worker.endswith(".exe"):
        raise AssertionError("Native manifest has no worker executable entry")
    provenance = load_object(kit_root / "NATIVE-PROVENANCE.json")
    if (provenance.get("schema_version") != 1
            or provenance.get("kind")
            != "windows-development-binary-license-provenance-not-release-audit"
            or provenance.get("release_approved") is not False
            or provenance.get("license_inventory_complete") is not False
            or provenance.get("requires_distribution_license_review") is not True):
        raise AssertionError("Untrusted or misleading native provenance flags")
    binaries = provenance.get("binaries")
    packages = provenance.get("packages")
    if (not isinstance(binaries, dict) or not isinstance(packages, dict)
            or set(binaries) != set(files)
            or provenance.get("complete_binary_origin_mapping") is not True):
        raise AssertionError("Native provenance and binary closure names differ")
    no_installed_notice = []
    notices_missing_files = []
    confirmed_notice_files = 0
    for package_name, pkg in sorted(packages.items()):
        if not isinstance(pkg, dict) or not isinstance(pkg.get("installed_license_files"), list):
            raise AssertionError("Missing package metadata/notice list")
        if (pkg.get("name") != package_name or not pkg.get("version")
                or not isinstance(pkg.get("declared_licenses"), str)):
            raise AssertionError("Unpinned/missing MSYS2 package license metadata")
        notices = pkg["installed_license_files"]
        if not notices:
            no_installed_notice.append(package_name)
        for notice in notices:
            if not check_reference_path(kit_root, notice):
                notices_missing_files.append({"package": package_name, "notice": notice})
            else:
                confirmed_notice_files += 1
    for filename, record in sorted(binaries.items()):
        if not isinstance(record, dict) or not record.get("origin"):
            raise AssertionError("Native binary lacks origin information")
        owner = record.get("package")
        if owner is not None:
            if owner not in packages:
                raise AssertionError("DLL referenced missing MSYS2 package inventory")
        else:
            notices = record.get("license_notices")
            if not isinstance(notices, list) or not notices:
                raise AssertionError("Non-package binary missing upstream/project notices")
            for notice in notices:
                if not check_reference_path(kit_root, notice):
                    notices_missing_files.append({"binary": filename, "notice": notice})
                else:
                    confirmed_notice_files += 1

    blockers = [
        "Original Essentia AGPL corresponding source, attribution and IPC "
        "combination require explicit legal review",
        "Native DLL/FFmpeg/FFTW/libsamplerate full license obligations, "
        "source offers and compatible redistribution terms are not approved",
        "ONNX model-by-model rights for redistribution and commercial use unresolved",
        "Independent Rust-Cargo/ONNX-runtime transitives and source provenance need SBOM review",
        "Windows kit is an unapproved development artifact; not a public release",
    ]
    if no_installed_notice:
        blockers.append(
            f"{len(no_installed_notice)} packages lack installed license notices; "
            "inspect matching exact-version upstream source packages"
        )
    if notices_missing_files:
        blockers.append(
            f"{len(notices_missing_files)} referenced notice files are missing from kit"
        )
    return {
        "schema_version": 1,
        "scope": "existing_windows_native_essentia_dev_kit_read_only",
        "binary_integrity": "PASS",
        "native_binary_count": len(files),
        "package_count": len(packages),
        "installed_notice_file_references_verified": confirmed_notice_files,
        "packages_without_installed_notices": no_installed_notice,
        "missing_notice_references": notices_missing_files,
        "manifests_intentionally_unapproved": True,
        "distribution_release_status": "BLOCKED",
        "review_required": True,
        "blockers": blockers,
        "note": (
            "A passing binary hash and provenance check is not a license "
            "grant. Do not copy DLLs or model weights into distributable artifacts "
            "based on this result alone."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path,
                        help="Optional NEW output folder for private full JSON report")
    args = parser.parse_args()
    if args.output_dir:
        if args.output_dir.exists():
            raise FileExistsError("Audit output folder must be new")
        if args.output_dir.resolve().is_relative_to(args.kit_root.resolve()):
            raise ValueError("Audit output must be outside source dev kit")
    result = audit(args.kit_root)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "release-readiness-audit-private.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    # Intentionally non-zero only on integrity/malformed manifests; BLOCKED
    # itself is a valid, truthful current legal-release observation.
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
