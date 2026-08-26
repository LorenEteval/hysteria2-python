import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "install-go-from-mod.py"
SPEC = importlib.util.spec_from_file_location("install_go_from_mod", SCRIPT)
INSTALLER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(INSTALLER)


class GoModVersionTests(unittest.TestCase):
    def read(self, contents):
        with tempfile.TemporaryDirectory() as temporary_dir:
            go_mod = Path(temporary_dir, "go.mod")
            go_mod.write_text(contents, encoding="utf-8")
            return INSTALLER.read_go_version(go_mod)

    def test_toolchain_directive_takes_precedence(self):
        self.assertEqual(
            self.read("module example.com/test\n\ngo 1.25.0\ntoolchain go1.25.1\n"),
            "1.25.1",
        )

    def test_go_directive_is_the_fallback(self):
        self.assertEqual(
            self.read("module example.com/test\n\ngo 1.25.0\n"), "1.25.0"
        )

    def test_default_toolchain_uses_go_directive(self):
        self.assertEqual(
            self.read("go 1.25.0\ntoolchain default\n"),
            "1.25.0",
        )

    def test_missing_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing Go version"):
            self.read("module example.com/test\n")


class ArchiveSelectionTests(unittest.TestCase):
    RELEASES = [
        {
            "version": "go1.25.1",
            "stable": True,
            "files": [
                {
                    "filename": "go1.25.1.linux-amd64.tar.gz",
                    "os": "linux",
                    "arch": "amd64",
                    "kind": "archive",
                    "sha256": "a" * 64,
                }
            ],
        },
        {
            "version": "go1.25.2",
            "stable": True,
            "files": [
                {
                    "filename": "go1.25.2.linux-amd64.tar.gz",
                    "os": "linux",
                    "arch": "amd64",
                    "kind": "archive",
                    "sha256": "b" * 64,
                }
            ],
        },
    ]

    def test_exact_toolchain_version_is_selected(self):
        archive = INSTALLER.select_archive(self.RELEASES, "1.25.1", "amd64")
        self.assertEqual(archive["filename"], "go1.25.1.linux-amd64.tar.gz")

    def test_go_language_version_selects_latest_patch(self):
        archive = INSTALLER.select_archive(self.RELEASES, "1.25", "amd64")
        self.assertEqual(archive["filename"], "go1.25.2.linux-amd64.tar.gz")

    def test_missing_architecture_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "No Linux arm64 archive"):
            INSTALLER.select_archive(self.RELEASES, "1.25.1", "arm64")


if __name__ == "__main__":
    unittest.main()
