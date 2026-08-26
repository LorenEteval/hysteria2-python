import argparse
import contextlib
import importlib.util
import io
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "sync-hysteria.py"
SPEC = importlib.util.spec_from_file_location("sync_hysteria", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
SYNC = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SYNC
SPEC.loader.exec_module(SYNC)


class SyncHysteriaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        temporary = pathlib.Path(self.temporary.name)
        self.root = temporary / "project"
        self.upstream = temporary / "upstream"
        self.root.mkdir()
        self.upstream.mkdir()
        self._git(self.root, "init", "--quiet")
        self._git(self.upstream, "init", "--quiet")
        for repository in (self.root, self.upstream):
            self._git(repository, "config", "user.name", "Test User")
            self._git(repository, "config", "user.email", "test@example.com")
            self._git(repository, "config", "core.autocrlf", "false")

        self._write_upstream("README.md", "upstream 1.0.0\n")
        self._write_upstream("app/main.go", "package main\n")
        self.commit_100 = self._commit_upstream("initial", "app/v1.0.0")
        self._write_upstream("README.md", "upstream 1.1.0\n")
        self._write_upstream("NEW.md", "new upstream file\n")
        self.commit_110 = self._commit_upstream("update", "app/v1.1.0")
        self._write_upstream(
            "app/python_binding.go", "package main\n// upstream collision\n"
        )
        self.commit_120 = self._commit_upstream("collision", "app/v1.2.0")

        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(SYNC, "ROOT", self.root))
        self.stack.enter_context(
            mock.patch.object(SYNC, "VENDOR_DIR", self.root / "hysteria2-go")
        )
        self.stack.enter_context(
            mock.patch.object(SYNC, "PATCH_DIR", self.root / "patches")
        )
        self.stack.enter_context(
            mock.patch.object(
                SYNC, "PACKAGE_VERSION_FILE", self.root / "PACKAGE_VERSION"
            )
        )
        self.stack.enter_context(
            mock.patch.object(
                SYNC, "UPSTREAM_VERSION_FILE", self.root / "UPSTREAM_VERSION"
            )
        )
        self.stack.enter_context(
            mock.patch.object(
                SYNC, "UPSTREAM_COMMIT_FILE", self.root / "UPSTREAM_COMMIT"
            )
        )

        with SYNC.upstream_checkout(
            "app/v1.0.0", self.upstream
        ) as current_checkout:
            SYNC.export_upstream(current_checkout, SYNC.VENDOR_DIR)
        for relative in SYNC.PROJECT_ADDITIONS:
            path = SYNC.VENDOR_DIR / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"binding-owned {relative}\n", encoding="utf-8")
        SYNC.write_metadata(SYNC.PACKAGE_VERSION_FILE, "1.0.0")
        SYNC.write_metadata(SYNC.UPSTREAM_VERSION_FILE, "app/v1.0.0")
        SYNC.write_metadata(SYNC.UPSTREAM_COMMIT_FILE, self.commit_100)
        self._git(self.root, "add", "--all")
        self._git(self.root, "commit", "--quiet", "-m", "initial project")

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _git(repository, *args):
        result = subprocess.run(
            ["git", *args],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def _write_upstream(self, relative, content):
        path = self.upstream / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    def _commit_upstream(self, message, tag):
        self._git(self.upstream, "add", "--all")
        self._git(self.upstream, "commit", "--quiet", "-m", message)
        self._git(self.upstream, "tag", tag)
        return self._git(self.upstream, "rev-parse", "HEAD")

    def _verify(self, tag="app/v1.0.0"):
        args = argparse.Namespace(tag=tag, upstream_dir=self.upstream)
        SYNC.verify_command(args)

    def test_verify_current_vendor_and_detect_unexpected_modification(self):
        self._verify()
        (SYNC.VENDOR_DIR / "README.md").write_text(
            "unexpected\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(SYNC.SyncError, "Modified upstream files: README.md"):
            self._verify()

    def test_explicit_patch_applies_cleanly(self):
        SYNC.PATCH_DIR.mkdir()
        (SYNC.PATCH_DIR / "0001-readme.patch").write_text(
            """diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-upstream 1.0.0
+patched upstream 1.0.0
""",
            encoding="utf-8",
            newline="\n",
        )
        (SYNC.VENDOR_DIR / "README.md").write_text(
            "patched upstream 1.0.0\n", encoding="utf-8", newline="\n"
        )
        self._verify()

    def test_sync_preserves_additions_updates_provenance_and_is_idempotent(self):
        additions = {
            relative: (SYNC.VENDOR_DIR / relative).read_text(encoding="utf-8")
            for relative in SYNC.PROJECT_ADDITIONS
        }
        args = argparse.Namespace(
            tag="app/v1.1.0",
            upstream_dir=self.upstream,
            current_upstream_dir=self.upstream,
        )
        SYNC.sync_command(args)
        self.assertEqual(SYNC.current_upstream_tag(), "app/v1.1.0")
        self.assertEqual(SYNC.current_upstream_commit(), self.commit_110)
        self.assertEqual(SYNC.current_package_version(), "1.1.0")
        self.assertEqual(
            (SYNC.VENDOR_DIR / "README.md").read_text(encoding="utf-8"),
            "upstream 1.1.0\n",
        )
        self.assertTrue((SYNC.VENDOR_DIR / "NEW.md").is_file())
        for relative, content in additions.items():
            self.assertEqual(
                (SYNC.VENDOR_DIR / relative).read_text(encoding="utf-8"), content
            )
        self._git(self.root, "add", "--all")
        self._git(self.root, "commit", "--quiet", "-m", "sync")
        before = self._git(self.root, "status", "--porcelain")
        SYNC.sync_command(args)
        after = self._git(self.root, "status", "--porcelain")
        self.assertEqual(before, "")
        self.assertEqual(after, "")

    def test_sync_rejects_project_addition_collision_without_changes(self):
        args = argparse.Namespace(
            tag="app/v1.2.0",
            upstream_dir=self.upstream,
            current_upstream_dir=self.upstream,
        )
        with self.assertRaisesRegex(SYNC.SyncError, "project addition paths"):
            SYNC.sync_command(args)
        self.assertEqual(SYNC.current_upstream_tag(), "app/v1.0.0")
        self.assertEqual(SYNC.current_upstream_commit(), self.commit_100)
        self.assertEqual(SYNC.current_package_version(), "1.0.0")

    def test_check_release_noop_and_inconsistent_state(self):
        args = argparse.Namespace(tag=None, github_output=None)
        release = {"tag_name": "app/v1.0.0", "draft": False, "prerelease": False}
        with mock.patch.object(SYNC, "stable_release", return_value=release), mock.patch.object(
            SYNC,
            "published_state",
            return_value={"tag": True, "release": True, "pypi": True},
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            SYNC.check_release(args)
        self.assertIn('"release_required": "false"', output.getvalue())
        with mock.patch.object(SYNC, "stable_release", return_value=release), mock.patch.object(
            SYNC,
            "published_state",
            return_value={"tag": True, "release": False, "pypi": False},
        ):
            with self.assertRaisesRegex(SYNC.SyncError, "inconsistent"):
                SYNC.check_release(args)

    def test_new_release_rejects_occupied_downstream_state(self):
        args = argparse.Namespace(tag="app/v1.1.0", github_output=None)
        release = {"tag_name": "app/v1.1.0", "draft": False, "prerelease": False}
        with mock.patch.object(SYNC, "stable_release", return_value=release), mock.patch.object(
            SYNC,
            "published_state",
            return_value={"tag": False, "release": False, "pypi": True},
        ):
            with self.assertRaisesRegex(SYNC.SyncError, "occupied by: pypi"):
                SYNC.check_release(args)

    def test_release_notes_use_exact_upstream_tag_and_commit(self):
        notes = SYNC.release_notes_text("app/v1.0.0", self.commit_100)
        self.assertIn("Corresponds to hysteria2 app/v1.0.0", notes)
        self.assertIn(self.commit_100, notes)


if __name__ == "__main__":
    unittest.main()
