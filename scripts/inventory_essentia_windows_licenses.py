#!/usr/bin/env python3
"""Generate transparent source/licence provenance for a Windows MinGW test bundle.

Run inside the MSYS2 MINGW64 shell *after* Windows native DLL closure packaging.
This does not claim a legal audit or change release_approved=false.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

SAFE = re.compile(r"^[A-Za-z0-9_.+-]+$")


def pacman(*args):
    result = subprocess.run(["pacman", *args], text=True, capture_output=True,
                            timeout=45, check=False)
    if result.returncode:
        raise RuntimeError(f"pacman {' '.join(args)} failed: {result.stderr[-500:]}")
    return result.stdout


def owner_for(path):
    result = pacman("-Qo", str(path))
    match = re.search(r" is owned by (\S+) ", result)
    if not match:
        raise ValueError(f"Missing trustworthy MSYS2 pacman ownership: {path}")
    return match.group(1)


def package_info(name):
    data = {}
    current = None
    for line in pacman("-Qi", name).splitlines():
        if ":" in line and not line.startswith(" "):
            key, val = line.split(":", 1)
            current = key.strip()
            data[current] = val.strip()
        elif current and line.strip():
            data[current] += " " + line.strip()
    if data.get("Name") != name or not data.get("Version"):
        raise ValueError(f"Incomplete MSYS2 package information for {name}")
    return {"name": name, "version": data["Version"],
            "declared_licenses": data.get("Licenses", "UNKNOWN"),
            "upstream_url": data.get("URL", "")}


def notices_for(name, outdir):
    files = []
    # This is observed install-package data, not an invented license assertion.
    for row in pacman("-Ql", name).splitlines():
        parts = row.split(maxsplit=1)
        if len(parts) != 2:
            continue
        candidate = Path(parts[1])
        if ("/share/licenses/" not in candidate.as_posix()
                or not candidate.is_file()
                or candidate.is_symlink()
                or candidate.stat().st_size > 1024 * 1024):
            continue
        files.append(candidate)
    output = []
    for index, path in enumerate(sorted(set(files))):
        dest = outdir / name / f"{index:03d}-{path.name}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        output.append(str(dest.relative_to(outdir.parent)).replace("\\", "/"))
    return output


def inventory(bundle, mingw, upstream, project_license, output):
    manifest = json.loads((bundle / "worker-dependencies.json").read_text(encoding="utf-8"))
    if (manifest.get("platform") != "windows-x86_64-mingw64"
            or manifest.get("release_approved") is not False):
        raise ValueError("Only unapproved Windows native dev bundles accepted")
    output.mkdir(parents=True, exist_ok=False)
    notice_root = output / "THIRD-PARTY-NOTICES"
    notice_root.mkdir()
    upstream_notices = []
    for name in ["COPYING.txt", "Essentia Licensing.txt", "AUTHORS"]:
        src = upstream / name
        if not src.is_file():
            raise FileNotFoundError(f"Missing original Essentia source notice: {src}")
        dst = notice_root / "essentia-upstream" / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        upstream_notices.append(str(dst.relative_to(output)).replace("\\", "/"))
    if not project_license.is_file():
        raise FileNotFoundError(f"Missing project license: {project_license}")
    local = notice_root / "essentia-analyser-project" / "LICENSE"
    local.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(project_license, local)

    package_cache = {}
    binaries = {}
    for filename in sorted(manifest["files"]):
        if not SAFE.fullmatch(filename):
            raise ValueError(f"Invalid native binary name: {filename}")
        if filename == manifest["worker_executable"]:
            binaries[filename] = {"origin": "this project, original C++ worker source",
                                  "source": "https://github.com/chrober/essentia-analyser",
                                  "license_notices": [str(local.relative_to(output))]}
            continue
        if filename == "essentia.dll":
            binaries[filename] = {
                "origin": "original upstream MTG/essentia C++",
                "commit": "b0661db99be4a8e2c6fabbe90a996f89786fdd8e",
                "source": "https://github.com/MTG/essentia/tree/b0661db99be4a8e2c6fabbe90a996f89786fdd8e",
                "license_notices": upstream_notices,
            }
            continue
        sources = [p for root in (mingw / "bin", mingw / "lib")
                   for p in root.iterdir()
                   if p.is_file() and p.name.lower() == filename]
        if not sources:
            raise FileNotFoundError(f"No installed MinGW owner candidate for {filename}")
        owners = {owner_for(p) for p in sources}
        if len(owners) != 1:
            raise ValueError(f"Ambiguous package origin for {filename}: {owners}")
        pkg = next(iter(owners))
        if pkg not in package_cache:
            info = package_info(pkg)
            info["installed_license_files"] = notices_for(pkg, notice_root)
            # Warn even when all metadata exists: notices may be in source packages
            # and static-link/transitive obligations require separate analysis.
            info["requires_redistribution_review"] = True
            package_cache[pkg] = info
        binaries[filename] = {"origin": "MSYS2 mingw64", "package": pkg}
    report = {
        "schema_version": 1,
        "kind": "windows-development-binary-license-provenance-not-release-audit",
        "complete_binary_origin_mapping": len(binaries) == len(manifest["files"]),
        "license_inventory_complete": False,
        "release_approved": False,
        "requires_distribution_license_review": True,
        "notes": ("Machine-generated MSYS2 pacman provenance + installed license notices. "
                  "Not proof all GPL/AGPL/LGPL source, link, patent or notice duties "
                  "are fulfilled. Do not publish as a production release."),
        "binaries": binaries, "packages": package_cache,
    }
    (output / "NATIVE-PROVENANCE.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    missing = [p for p, record in package_cache.items()
               if not record["installed_license_files"]]
    print(f"Provenance: {len(binaries)} native binaries; {len(package_cache)} "
          f"MSYS2 packages; {len(missing)} with no installed notice file")
    if missing:
        print("Installed NOTICE files unavailable (source package review needed): " +
              ", ".join(missing))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--mingw", type=Path, required=True)
    parser.add_argument("--essentia-source", type=Path, required=True)
    parser.add_argument("--project-license", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    inventory(a.bundle.resolve(), a.mingw.resolve(),
              a.essentia_source.resolve(), a.project_license.resolve(),
              a.output.resolve())


if __name__ == "__main__":
    main()
