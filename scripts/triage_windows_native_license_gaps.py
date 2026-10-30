#!/usr/bin/env python3
"""Create a source-version-linked, read-only license evidence backlog.

Only works from a verified *unapproved* original Essentia Windows
development kit. Does NOT guess license obligations or fetch missing
notices. Display links/import chains are imported from the kit's
manifest and are explicitly *not* a fresh binary dependency scan.

Missing *installed* license notices do NOT prove a package is
unlicensed. Corresponding exact-version upstream sources and build
configurations must still be reviewed before redistribution.
"""
import argparse
from collections import deque
import json
from pathlib import Path

from audit_windows_native_release import audit, load_object


def import_routes(native):
    """Shortest manifest-recorded DLL import paths from actual worker."""
    files = native["files"]
    root = native["worker_executable"]
    if root not in files:
        raise AssertionError("Worker executable absent from manifest")
    unknown = []
    graph = {}
    for filename, record in files.items():
        imports = record.get("imports")
        if not isinstance(imports, list) or any(not isinstance(s, str) for s in imports):
            unknown.append(filename)
            continue
        graph[filename] = sorted({
            name.lower() for name in imports if name.lower() in files
        })
    paths = {root: [root]}
    todo = deque([root])
    while todo:
        src = todo.popleft()
        for dst in graph.get(src, ()):
            if dst not in paths:
                paths[dst] = paths[src] + [dst]
                todo.append(dst)
    return paths, sorted(unknown)


def plan(kit):
    verification = audit(kit)  # actual PE/hash/license file checks first
    native = load_object(kit / "essentia-worker" / "worker-dependencies.json")
    provenance = load_object(kit / "NATIVE-PROVENANCE.json")
    paths, graph_missing = import_routes(native)
    binaries = provenance["binaries"]
    packages = provenance["packages"]
    missing = set(verification["packages_without_installed_notices"])
    queue = []
    for name in sorted(packages):
        p = packages[name]
        linked = sorted(
            filename for filename, b in binaries.items()
            if b.get("package") == name
        )
        if not linked:
            raise AssertionError(f"Recorded package is not an owner of any DLL: {name}")
        if name in missing:
            queue.append({
                "package": name,
                "installed_package_version": p["version"],
                "declared_licenses_from_pacman_metadata_unverified": p["declared_licenses"],
                "declared_upstream_url_from_pacman_metadata_unverified": p.get("upstream_url", ""),
                "owned_native_binary_names": linked,
                "owned_native_binary_count": len(linked),
                "manifest_recorded_import_chain_examples": [
                    paths[dll] if dll in paths else None for dll in linked
                ],
                "installed_notice_count": 0,
                "exact_version_source_package_reviewed": False,
                "corresponding_source_and_build_flags_reviewed": False,
                "actual_license_text_validated": False,
                "license_compatibility_approved": False,
                "review_action": (
                    "Retrieve original exact-version MSYS2 source/PKGBUILD "
                    "from authoritative source; verify checksum, license texts, "
                    "build configuration, transitive/source obligations and "
                    "appropriate notices. Do not infer license from package name."
                ),
            })
    return {
        "schema_version": 1,
        "scope": "real_windows_dev_bundle_missing_installed_notices",
        "binary_integrity": verification["binary_integrity"],
        "native_binary_count": verification["native_binary_count"],
        "msys2_package_count": verification["package_count"],
        "installed_notice_file_references_verified":
            verification["installed_notice_file_references_verified"],
        "missing_installed_notice_packages": len(queue),
        "review_queue": queue,
        "import_graph_evidence": {
            "kind": "recorded_PE_imports_from_unapproved_manifest_not_fresh_PE_rescan",
            "manifest_entries_without_import_list": graph_missing,
            "reachable_binaries": len(paths),
            "manifest_entries": len(native["files"]),
            "caution": (
                "Recorded imports are a technical starting point. They do "
                "not justify deleting DLLs, establish runtime dlopen/codec "
                "coverage, or prove license/linkage compatibility."
            ),
        },
        "recommended_path_from_existing_strategy":
            "Development/PR16: continue existing verified Rust v5 scanner. "
            "Distribution: prefer source/build-based worker installation "
            "with system native dependencies and separate model download; "
            "no exemption from AGPL/FFmpeg/MTG model usage rights.",
        "distribution_release_status": "BLOCKED",
        "non_automatable_review_remaining": [
            "Essentia AGPL corresponding source/derivative/IPC combination",
            "Actual FFmpeg LGPL/GPL/nonfree and enabled codecs/build flags",
            "Native source/notices and precise copyleft license obligations",
            "Four separately fetched MTG ONNX model usage licenses",
            "Cargo transitive licensing/source provenance and user distribution",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit-root", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path,
                        help="Optional new output folder, outside dev kit")
    args = parser.parse_args()
    if args.output_dir:
        if args.output_dir.exists():
            raise FileExistsError("Output folder exists: refuse overwrite")
        if args.output_dir.resolve().is_relative_to(args.kit_root.resolve()):
            raise ValueError("Output must be outside the development kit")
    result = plan(args.kit_root)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "native-license-evidence-backlog.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "binary_integrity": result["binary_integrity"],
        "native_binary_count": result["native_binary_count"],
        "msys2_package_count": result["msys2_package_count"],
        "missing_installed_notice_packages":
            result["missing_installed_notice_packages"],
        "review_packages": [r["package"] for r in result["review_queue"]],
        "distribution_release_status": "BLOCKED",
        "note": "Full versioned license-gap evidence is in optional local JSON.",
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
