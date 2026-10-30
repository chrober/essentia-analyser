#!/usr/bin/env python3
"""Stage a Windows-native Essentia C++ worker with its complete DLL closure.

The input must be a separately compiled original Essentia C++ EXE.  This
program is a **packager**, NOT a replacement for its native build.
Dependency names come from the PE import table (GNU objdump -p); every
non-OS DLL is copied from explicitly trusted runtime directories. Unresolved
or MSYS/Cygwin dependencies abort rather than shipping a broken package.

With no license inventory this produces DEVELOPMENT-ONLY packages.
"""
import argparse
import ctypes
import os
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess

MAX_FILES = 256
MAX_TOTAL_BYTES = 600 * 1024 * 1024
NAME = re.compile(r"^[a-zA-Z0-9_.+-]+\.dll$", re.I)
DLL_LINE = re.compile(r"^\s*DLL Name:\s*(\S+\.dll)\s*$", re.I | re.M)
WINDOWS_OS_DLLS = {
    "advapi32.dll", "bcrypt.dll", "bcryptprimitives.dll", "cfgmgr32.dll",
    "combase.dll", "comctl32.dll", "comdlg32.dll", "crypt32.dll",
    "cryptbase.dll", "dwmapi.dll", "dnsapi.dll", "gdi32.dll",
    "gdi32full.dll", "gdiplus.dll", "imm32.dll", "iphlpapi.dll", "kernel32.dll",
    "msimg32.dll",  # Windows built-in GDI alpha-blending DLL, not a MinGW dependency.
    "kernelbase.dll", "mpr.dll", "msvcrt.dll", "ncrypt.dll",
    "normaliz.dll", "ntdll.dll", "ole32.dll", "oleaut32.dll",
    "powrprof.dll", "psapi.dll", "rpcrt4.dll", "secur32.dll",
    "setupapi.dll", "shell32.dll", "shcore.dll", "shlwapi.dll",
    "ucrtbase.dll", "user32.dll", "userenv.dll", "usp10.dll",
    "version.dll", "winhttp.dll", "wininet.dll", "winmm.dll",
    "winspool.drv", "wldap32.dll", "ws2_32.dll", "wsock32.dll",
    "avrt.dll",
}
REJECT_RUNTIME = {"msys-2.0.dll", "cygwin1.dll"}


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for data in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def check_pe_x64(file):
    """Reject architecture-confused, non-PE and maliciously short inputs."""
    with file.open("rb") as handle:
        header = handle.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise ValueError(f"Expected Windows PE file: {file}")
        offset = struct.unpack_from("<I", header, 0x3c)[0]
        if offset > 1024 * 1024:
            raise ValueError("PE header offset out of bounds")
        handle.seek(offset)
        if handle.read(4) != b"PE\x00\x00":
            raise ValueError(f"Invalid PE signature: {file}")
        machine = handle.read(2)
        if machine != b"\x64\x86":  # IMAGE_FILE_MACHINE_AMD64, 0x8664
            raise ValueError(f"Windows x64 PE required: {file}")


def imports(file, objdump):
    result = subprocess.run([str(objdump), "-p", str(file)], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=30, check=False)
    if result.returncode:
        raise RuntimeError(f"Cannot inspect PE imports for {file}: "
                           f"{result.stderr[-800:]}")
    text = result.stdout
    if "file format pei-x86-64" not in text.lower():
        # MinGW objdump often reports "pei-x86-64", LLVM variants differ.
        if not re.search(r"pei-x86-64|pe-x86-64", text, re.I):
            raise ValueError(f"objdump did not identify 64-bit PE: {file}")
    dlls = [name.lower() for name in DLL_LINE.findall(text)]
    return sorted(set(dlls))


def windows_system_directory():
    """Discover the real OS System32 directory; never trust PATH or user-supplied roots.

    A native 64-bit Windows Python interpreter is required when building
    Windows packages. Non-Windows hosts retain the conservative static
    allowlist and reject unresolved imports rather than guessing.
    """
    if os.name != "nt":
        return None
    buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if size <= 0 or size >= len(buffer):
        raise OSError("Could not discover trusted Windows System32 directory")
    system_dir = Path(buffer.value)
    if not system_dir.is_dir():
        raise FileNotFoundError(f"Windows System32 directory does not exist: {system_dir}")
    return system_dir


def system_dll(name, system_directory=None):
    if (name in WINDOWS_OS_DLLS or name.startswith("api-ms-win-")
            or name.startswith("ext-ms-win-")):
        return True
    if system_directory is None:
        return False
    # Only the genuine GetSystemDirectoryW() directory is passed by collect().
    # A file in an arbitrary MinGW DLL directory is never evidence of OS origin.
    system_file = system_directory / name
    if not system_file.is_file():
        return False
    if not system_file.resolve().is_relative_to(system_directory.resolve()):
        raise ValueError(f"Windows system DLL escapes System32: {system_file}")
    check_pe_x64(system_file)
    return True


def resolve_dll(name, search_dirs):
    matches = []
    for base in search_dirs:
        if not base.is_dir():
            raise ValueError(f"Invalid trusted dependency directory {base}")
        matching = [item for item in base.iterdir()
                    if item.is_file() and item.name.lower() == name]
        for file in matching:
            if not file.resolve().is_relative_to(base.resolve()):
                raise ValueError(f"Unsafe symlink outside trusted DLL root: {file}")
            matches.append(file)
    if not matches:
        raise FileNotFoundError(f"Unresolved Windows native dependency: {name}")
    hashes = {sha256(path) for path in matches}
    if len(hashes) != 1:
        raise ValueError(f"Ambiguous DLL name with conflicting binaries: {name}")
    return matches[0]


def collect(executable, dependency_dirs, objdump):
    if not executable.is_file():
        raise ValueError(f"Worker executable not found: {executable}")
    check_pe_x64(executable)
    system_directory = windows_system_directory()
    entries = {executable.name.lower(): executable}
    queue = [executable]
    total_size = 0
    while queue:
        file = queue.pop(0)
        check_pe_x64(file)
        total_size += file.stat().st_size
        if total_size > MAX_TOTAL_BYTES:
            raise ValueError("Dependency closure exceeds 600 MiB safety bound")
        for dll in imports(file, objdump):
            if not NAME.fullmatch(dll):
                raise ValueError(f"Unsafe imported DLL basename: {dll!r}")
            if dll in REJECT_RUNTIME:
                raise ValueError(f"MSYS/Cygwin runtime forbidden in native worker: {dll}")
            if system_dll(dll, system_directory) or dll in entries:
                continue
            if len(entries) >= MAX_FILES:
                raise ValueError("Dependency closure exceeds safety limit")
            dependency = resolve_dll(dll, dependency_dirs)
            entries[dll] = dependency
            queue.append(dependency)
    return entries


def package(executable, dependency_dirs, objdump, output, license_map=None):
    if output.exists():
        raise FileExistsError(f"Refuse existing package path: {output}")
    entries = collect(executable, dependency_dirs, objdump)
    distribution_ready = license_map is not None
    # Validating license records BEFORE copying prevents half-made packages.
    licensed = {}
    if license_map is not None:
        raw = json.loads(license_map.read_text(encoding="utf-8"))
        for name, source in entries.items():
            key = name.lower()
            record = raw.get(key)
            if not isinstance(record, dict):
                raise ValueError(f"Missing license inventory for {key}")
            notice = license_map.parent / record.get("notice_file", "")
            if not (isinstance(record.get("spdx"), str)
                    and record["spdx"].strip() and notice.is_file()):
                raise ValueError(f"Invalid SPDX ID or missing license notice for {key}")
            licensed[key] = (record["spdx"].strip(), notice)
    output.mkdir(parents=True)
    manifest_files = {}
    notices = output / "LICENSES"
    if distribution_ready:
        notices.mkdir()
    for name, source in sorted(entries.items()):
        destination = output / name
        shutil.copyfile(source, destination)
        manifest_files[name] = {
            "size_bytes": destination.stat().st_size,
            "sha256": sha256(destination),
            "imports": imports(destination, objdump),
            "spdx": licensed[name][0] if distribution_ready else None,
        }
        if distribution_ready:
            shutil.copyfile(licensed[name][1], notices / (name + ".txt"))
    manifest = {
        "schema_version": 1,
        "platform": "windows-x86_64-mingw64",
        "verified_with": "PE x86_64 plus transitive imported DLL inspection",
        "license_inventory_complete": distribution_ready,
        "release_approved": False,
        "requires_distribution_license_review": True,
        "worker_executable": executable.name.lower(),
        "files": manifest_files,
        "notes": (
            "Development-only: original Essentia C++ is AGPLv3 and "
            "dynamic library licences and distribution conditions require review."
        ),
    }
    (output / "worker-dependencies.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify(output):
    manifest = json.loads((output / "worker-dependencies.json").read_text(
        encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported native bundle manifest")
    expected = set(manifest["files"])
    found = {p.name.lower() for p in output.iterdir()
             if p.is_file() and (p.suffix.lower() in {".exe", ".dll"})}
    if found != expected:
        raise ValueError("Native bundle contains missing or unexpected executables/DLLs")
    for name, entry in manifest["files"].items():
        path = output / name
        if (not NAME.fullmatch(name)
                and not re.fullmatch(r"[a-zA-Z0-9_.+-]+\.exe", name, re.I)):
            raise ValueError("Invalid native bundle file name")
        check_pe_x64(path)
        if path.stat().st_size != entry["size_bytes"] or sha256(path) != entry["sha256"]:
            raise ValueError(f"Native DLL or EXE changed after packaging: {name}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--dll-dir", type=Path, action="append", default=[])
    parser.add_argument("--objdump", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--license-map", type=Path,
                        help="JSON name -> {spdx, notice_file}. Mandatory for "
                             "licensing-complete candidate; legal review still required.")
    parser.add_argument("--verify", type=Path,
                        help="Verify hashes and complete native bundle inventory")
    args = parser.parse_args()
    if args.verify:
        manifest = verify(args.verify)
        print(f"Windows native bundle checksums PASS: "
              f"{len(manifest['files'])} files")
        return
    if not (args.worker and args.objdump and args.output and args.dll_dir):
        parser.error("Packaging requires --worker, --objdump, --output, --dll-dir")
    manifest = package(
        args.worker.resolve(), [p.resolve() for p in args.dll_dir],
        args.objdump.resolve(), args.output, args.license_map,
    )
    print(f"Native Windows bundle staged: {args.output} / "
          f"{len(manifest['files'])} binaries / "
          f"license_inventory_complete={manifest['license_inventory_complete']}")
    print("NOT RELEASE APPROVED: independent licensing/dependency review is required")


if __name__ == "__main__":
    main()
