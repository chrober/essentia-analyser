"""Windows native worker packaging logic tests. No Essentia/toolchain required."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import package_essentia_worker_windows as package


def fake_pe(path):
    header = bytearray(0x90)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 0x3c, 0x80)
    header[0x80:0x84] = b"PE\x00\x00"
    header[0x84:0x86] = b"\x64\x86"
    path.write_bytes(header)
    return path


class NativeWindowsPackagingTests(unittest.TestCase):
    def test_pe_arch_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = fake_pe(Path(tmp) / "worker.exe")
            package.check_pe_x64(p)
            data = bytearray(p.read_bytes())
            data[0x84:0x86] = b"\x4c\x01"  # IMAGE_FILE_MACHINE_I386
            p.write_bytes(data)
            with self.assertRaises(ValueError):
                package.check_pe_x64(p)

    def test_collect_transitive_dlls_and_preserve_distinct_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            exe = fake_pe(d / "bliss-essentia-worker.exe")
            one = fake_pe(d / "libessentia.dll")
            two = fake_pe(d / "libsamplerate-0.dll")
            names = {
                exe.name: ["kernel32.dll", "libessentia.dll"],
                one.name: ["libsamplerate-0.dll", "ucrtbase.dll"],
                two.name: ["kernel32.dll"],
            }
            with patch.object(package, "imports", side_effect=lambda p, _: names[p.name]):
                result = package.collect(exe, [d], d / "objdump.exe")
            self.assertEqual(set(result), {
                exe.name, one.name, two.name,
            })

    def test_windows_msimg32_wsock32_and_gdiplus_are_os_managed(self):
        # These DLLs are part of Windows itself, not MinGW dependencies.
        # Unrecognized imports must still fail closed.
        self.assertTrue(package.system_dll("msimg32.dll"))
        self.assertTrue(package.system_dll("wsock32.dll"))
        self.assertTrue(package.system_dll("gdiplus.dll"))
        self.assertFalse(package.system_dll("unrecognized-vendor.dll"))
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            exe = fake_pe(d / "bliss-essentia-worker.exe")
            with patch.object(package, "imports", return_value=["msimg32.dll", "wsock32.dll", "gdiplus.dll", "kernel32.dll"]):
                self.assertEqual(set(package.collect(exe, [d], d / "objdump.exe")), {exe.name})
            with patch.object(package, "imports", return_value=["unrecognized-vendor.dll"]):
                with self.assertRaises(FileNotFoundError):
                    package.collect(exe, [d], d / "objdump.exe")

    def test_discover_system_dll_via_real_system_directory_not_runtime_dirs(self):
        # A native Windows caller obtains this directory via GetSystemDirectoryW.
        # Emulate it here so this security boundary is tested on Linux, too.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            system = base / "System32"
            runtime = base / "runtime"
            system.mkdir()
            runtime.mkdir()
            fake_pe(system / "dwrite.dll")
            fake_pe(runtime / "vendor-codec.dll")
            exe = fake_pe(runtime / "bliss-essentia-worker.exe")
            self.assertTrue(package.system_dll("dwrite.dll", system))
            self.assertFalse(package.system_dll("vendor-codec.dll", system))
            self.assertFalse(package.system_dll("dwrite.dll"))
            with patch.object(package, "windows_system_directory",
                              return_value=system), patch.object(
                              package, "imports", side_effect=lambda p, _: (
                              ["dwrite.dll", "vendor-codec.dll"]
                              if p.name == exe.name else [])):
                result = package.collect(exe, [runtime], base / "objdump.exe")
            self.assertEqual(set(result), {exe.name, "vendor-codec.dll"})
            with patch.object(package, "windows_system_directory",
                              return_value=system), patch.object(
                              package, "imports", return_value=["unknown.dll"]):
                with self.assertRaises(FileNotFoundError):
                    package.collect(exe, [runtime], base / "objdump.exe")

    def test_reject_malformed_or_escaping_windows_system_dll(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            system = base / "System32"
            system.mkdir()
            (system / "dwrite.dll").write_bytes(b"not a valid native PE")
            with self.assertRaises(ValueError):
                package.system_dll("dwrite.dll", system)
            (system / "dwrite.dll").unlink()
            out = fake_pe(base / "external.dll")
            try:
                (system / "external.dll").symlink_to(out)
            except (OSError, NotImplementedError):
                pass  # Symlink permissions differ on Windows runner accounts.
            else:
                with self.assertRaises(ValueError):
                    package.system_dll("external.dll", system)

    def test_fail_closed_on_missing_dll_and_msys_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            exe = fake_pe(d / "worker.exe")
            with patch.object(package, "imports", return_value=["libessentia.dll"]):
                with self.assertRaises(FileNotFoundError):
                    package.collect(exe, [d], d / "objdump.exe")
            with patch.object(package, "imports", return_value=["msys-2.0.dll"]):
                with self.assertRaises(ValueError):
                    package.collect(exe, [d], d / "objdump.exe")

    def test_fail_closed_on_ambiguous_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            a, b = base / "a", base / "b"
            a.mkdir()
            b.mkdir()
            p = fake_pe(a / "libsamplerate-0.dll")
            q = fake_pe(b / "libsamplerate-0.dll")
            q.write_bytes(q.read_bytes() + b"changed")
            with self.assertRaises(ValueError):
                package.resolve_dll(p.name, [a, b])

    def test_dev_package_provenance_verify_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            src = base / "inputs"
            src.mkdir()
            exe = fake_pe(src / "bliss-essentia-worker.exe")
            lib = fake_pe(src / "libessentia.dll")
            names = {exe.name: ["libessentia.dll"], lib.name: ["kernel32.dll"]}
            target = base / "dist"
            with patch.object(package, "imports", side_effect=lambda p, _: names[p.name]):
                manifest = package.package(exe, [src], base / "objdump.exe", target)
            self.assertFalse(manifest["license_inventory_complete"])
            self.assertEqual(len(manifest["files"]), 2)
            self.assertEqual(package.verify(target)["files"], manifest["files"])
            with self.assertRaises(FileExistsError):
                package.package(exe, [src], base / "objdump.exe", target)
            (target / lib.name).write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                package.verify(target)

    def test_distributable_stage_requires_complete_notices(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            inp = base / "src"
            inp.mkdir()
            exe = fake_pe(inp / "bliss-essentia-worker.exe")
            lib = fake_pe(inp / "libessentia.dll")
            licence = base / "AGPL.txt"
            licence.write_text("upstream licence evidence")
            mapping = base / "licenses.json"
            mapping.write_text(json.dumps({
                "bliss-essentia-worker.exe":
                    {"spdx": "AGPL-3.0-or-later", "notice_file": "AGPL.txt"},
                # Intentionally omit the dependent library
            }))
            with patch.object(package, "imports", side_effect=lambda p, _: (
                ["libessentia.dll"] if p.name == exe.name else [])):
                with self.assertRaises(ValueError):
                    package.package(exe, [inp], base / "objdump", base / "dist",
                                    license_map=mapping)
            self.assertFalse((base / "dist").exists())
            mapping.write_text(json.dumps({
                name: {"spdx": "AGPL-3.0-or-later", "notice_file": "AGPL.txt"}
                for name in (exe.name, lib.name)
            }))
            with patch.object(package, "imports", side_effect=lambda p, _: (
                ["libessentia.dll"] if p.name == exe.name else [])):
                report = package.package(exe, [inp], base / "objdump",
                                         base / "dist", license_map=mapping)
            self.assertTrue(report["license_inventory_complete"])
            self.assertTrue((base / "dist" / "LICENSES" /
                             (lib.name + ".txt")).is_file())


if __name__ == "__main__":
    unittest.main()
