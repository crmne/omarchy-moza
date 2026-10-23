import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "1234567890abcdef1234567890abcdef12345678"


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "tools").mkdir()
        shutil.copy(ROOT / "tools/binary-provenance.sh", self.root / "tools")
        for name in ("bin/omarchy-moza", "bin/omarchy-moza-shm.exe", "rev/Cargo.lock", "vendor/boxflat.lock.json"):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("test fixture\n")
        self.commands = self.root / "commands"
        self.commands.mkdir()
        self.command("pacman", "printf 'rust 1:1.98.0-1\\n'\n")
        self.command("rustc", "printf 'rustc 1.98.0\\n'\n")

    def command(self, name, body):
        path = self.commands / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def run_report(self, *args):
        return subprocess.run(
            ["bash", str(self.root / "tools/binary-provenance.sh"), *args],
            env={**os.environ, "PATH": f"{self.commands}:/usr/bin:/bin"},
            capture_output=True, text=True,
        )

    def test_archive_checkout_without_git_metadata_keeps_exact_commit(self):
        self.command("git", "echo 'Git metadata unavailable' >&2\nexit 128\n")
        result = self.run_report(COMMIT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"source_commit={COMMIT}\n", result.stdout)
        self.assertIn("verified_reproducible_builds=2\n", result.stdout)
        self.assertIn("  bin/omarchy-moza\n", result.stdout)

    def test_missing_or_invalid_commit_fails_before_writing_report(self):
        for args in ((), ("",), ("abc123",), ("g" * 40,), (COMMIT + "\n",), (COMMIT, "extra")):
            with self.subTest(args=args):
                result = self.run_report(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_missing_artifact_fails(self):
        (self.root / "bin/omarchy-moza").unlink()
        self.assertNotEqual(self.run_report(COMMIT).returncode, 0)

    def test_missing_package_metadata_fails(self):
        self.command("pacman", "exit 1\n")
        self.assertNotEqual(self.run_report(COMMIT).returncode, 0)
