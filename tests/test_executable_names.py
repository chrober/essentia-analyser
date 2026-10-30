"""Test the actual Rust and CMake executable naming contracts."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ExecutableNamingTests(unittest.TestCase):
    def test_rust_crate_and_cli_names(self):
        cargo = (ROOT / "Cargo.toml").read_text(encoding="utf-8")
        lock = (ROOT / "Cargo.lock").read_text(encoding="utf-8")
        source = (ROOT / "src/main.rs").read_text(encoding="utf-8")
        self.assertIn('name = "essentia-analyser"', cargo)
        self.assertIn('name = "essentia-analyser"', lock)
        self.assertNotIn('name = "bliss-mood"', lock)
        self.assertIn('#[command(name = "essentia-analyser"', source)
        self.assertNotIn('#[command(name = "bliss-mood"', source)

    def test_native_essentia_worker_target(self):
        cmake = (ROOT / "native/CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("add_executable(essentia-worker essentia_cpp_worker.cpp)", cmake)
        self.assertNotIn("bliss-essentia-worker", cmake)
        self.assertIn("PkgConfig::ESSENTIA", cmake)

    def test_ci_invokes_new_cli_name(self):
        ci = (ROOT / ".github/workflows/scanner-ci.yml").read_text(encoding="utf-8")
        self.assertIn("target/debug/essentia-analyser.exe", ci)
        self.assertNotIn("target/debug/bliss-mood.exe", ci)

if __name__ == "__main__":
    unittest.main()
