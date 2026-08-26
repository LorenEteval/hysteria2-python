#!/usr/bin/env python3
"""Synchronize, verify, and release exact stable Hysteria upstream versions."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT / "hysteria2-go"
PATCH_DIR = ROOT / "patches"
PACKAGE_VERSION_FILE = ROOT / "PACKAGE_VERSION"
UPSTREAM_VERSION_FILE = ROOT / "UPSTREAM_VERSION"
UPSTREAM_COMMIT_FILE = ROOT / "UPSTREAM_COMMIT"
UPSTREAM_REPOSITORY = "HyNetworks/hysteria"
UPSTREAM_URL = f"https://github.com/{UPSTREAM_REPOSITORY}.git"
PROJECT_REPOSITORY = "LorenEteval/hysteria2-python"
PYPI_PROJECT = "hysteria2"
PROJECT_ADDITIONS = frozenset(
    {
        "app/cmd/python_binding.go",
        "app/python_binding.go",
    }
)
OMITTED_UPSTREAM_GITLINKS: frozenset[str] = frozenset()
UPSTREAM_TAG_PATTERN = re.compile(r"app/v(?P<version>\d+\.\d+\.\d+)\Z")
PACKAGE_VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:\.\d+)?\Z")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


class SyncError(RuntimeError):
    """A safe, user-facing synchronization failure."""


@dataclass(frozen=True)
class UpstreamCheckout:
    repository: pathlib.Path
    treeish: str
    commit: str


def run(
    command: Sequence[str],
    *,
    cwd: pathlib.Path | None = None,
    input_text: str | None = None,
    text: bool = True,
) -> str | bytes:
    result = subprocess.run(
        command,
        cwd=cwd or ROOT,
        input=input_text,
        capture_output=True,
        text=text,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if text else result.stderr.decode().strip()
        raise SyncError(f"Command failed: {' '.join(command)}\n{stderr}")
    return result.stdout


def parse_upstream_tag(tag: str) -> tuple[int, int, int]:
    match = UPSTREAM_TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise SyncError(f"Expected a stable app/vX.Y.Z tag, got {tag!r}")
    return tuple(int(part) for part in match.group("version").split("."))


def upstream_package_version(tag: str) -> str:
    match = UPSTREAM_TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise SyncError(f"Expected a stable app/vX.Y.Z tag, got {tag!r}")
    return match.group("version")


def parse_package_version(version: str) -> tuple[int, ...]:
    if PACKAGE_VERSION_PATTERN.fullmatch(version) is None:
        raise SyncError(f"Expected X.Y.Z or X.Y.Z.N package version, got {version!r}")
    return tuple(int(part) for part in version.split("."))


def read_metadata(path: pathlib.Path, description: str) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as error:
        raise SyncError(f"Missing {description} file: {path}") from error
    if not value:
        raise SyncError(f"Empty {description} file: {path}")
    return value


def current_upstream_tag() -> str:
    tag = read_metadata(UPSTREAM_VERSION_FILE, "upstream version")
    parse_upstream_tag(tag)
    return tag


def current_upstream_commit() -> str:
    commit = read_metadata(UPSTREAM_COMMIT_FILE, "upstream commit")
    if COMMIT_PATTERN.fullmatch(commit) is None:
        raise SyncError(f"Invalid upstream commit: {commit!r}")
    return commit


def current_package_version() -> str:
    version = read_metadata(PACKAGE_VERSION_FILE, "package version")
    parse_package_version(version)
    return version


def downstream_tag(version: str) -> str:
    parse_package_version(version)
    return f"v{version}"


def request_json(url: str, *, missing_ok: bool = False) -> Any | None:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "hysteria2-python-upstream-sync",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if missing_ok and error.code == 404:
            return None
        raise SyncError(f"HTTP {error.code} while requesting {url}") from error
    except urllib.error.URLError as error:
        raise SyncError(f"Unable to request {url}: {error.reason}") from error


def stable_release(requested_tag: str | None) -> dict[str, Any]:
    if requested_tag is None:
        url = f"https://api.github.com/repos/{UPSTREAM_REPOSITORY}/releases/latest"
    else:
        parse_upstream_tag(requested_tag)
        encoded_tag = urllib.parse.quote(requested_tag, safe="")
        url = (
            f"https://api.github.com/repos/{UPSTREAM_REPOSITORY}"
            f"/releases/tags/{encoded_tag}"
        )
    release = request_json(url)
    if not isinstance(release, dict):
        raise SyncError("GitHub returned an invalid upstream release response")
    tag = release.get("tag_name")
    if not isinstance(tag, str):
        raise SyncError("The upstream release does not contain a tag name")
    parse_upstream_tag(tag)
    if release.get("draft") or release.get("prerelease"):
        raise SyncError(f"Refusing non-stable upstream release {tag}")
    if requested_tag is not None and tag != requested_tag:
        raise SyncError(f"Requested {requested_tag}, but GitHub returned {tag}")
    return release


def github_resource_exists(endpoint: str) -> bool:
    url = f"https://api.github.com/repos/{PROJECT_REPOSITORY}/{endpoint}"
    return request_json(url, missing_ok=True) is not None


def pypi_version_exists(version: str) -> bool:
    parse_package_version(version)
    encoded_version = urllib.parse.quote(version, safe="")
    url = f"https://pypi.org/pypi/{PYPI_PROJECT}/{encoded_version}/json"
    return request_json(url, missing_ok=True) is not None


def published_state(release_tag: str, package_version: str) -> dict[str, bool]:
    encoded_tag = urllib.parse.quote(release_tag, safe="")
    return {
        "tag": github_resource_exists(f"git/ref/tags/{encoded_tag}"),
        "release": github_resource_exists(f"releases/tags/{encoded_tag}"),
        "pypi": pypi_version_exists(package_version),
    }


def write_github_output(path: pathlib.Path | None, values: dict[str, str]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise SyncError(f"GitHub output {key!r} contains a newline")
            output.write(f"{key}={value}\n")


def check_release(args: argparse.Namespace) -> None:
    current_tag = current_upstream_tag()
    current_version = parse_upstream_tag(current_tag)
    release = stable_release(args.tag)
    target_tag = release["tag_name"]
    target_version = parse_upstream_tag(target_tag)
    if target_version < current_version:
        raise SyncError(
            f"Upstream target {target_tag} is older than current {current_tag}"
        )
    update_required = target_version > current_version
    package_version = (
        upstream_package_version(target_tag)
        if update_required
        else current_package_version()
    )
    release_tag = downstream_tag(package_version)
    state = published_state(release_tag, package_version)
    if update_required and any(state.values()):
        occupied = ", ".join(name for name, exists in state.items() if exists)
        raise SyncError(f"Release target {release_tag} is occupied by: {occupied}")
    if not update_required and any(state.values()) and not all(state.values()):
        present = ", ".join(name for name, exists in state.items() if exists)
        missing = ", ".join(name for name, exists in state.items() if not exists)
        raise SyncError(
            f"Release {release_tag} is inconsistent; present: {present}; "
            f"missing: {missing}"
        )
    release_required = update_required or not all(state.values())
    values = {
        "current_upstream_tag": current_tag,
        "upstream_tag": target_tag,
        "package_version": package_version,
        "release_tag": release_tag,
        "release_required": str(release_required).lower(),
        "update_required": str(update_required).lower(),
    }
    write_github_output(args.github_output, values)
    print(json.dumps(values, indent=2, sort_keys=True))


@contextlib.contextmanager
def upstream_checkout(
    tag: str, supplied_repository: pathlib.Path | None = None
) -> Iterator[UpstreamCheckout]:
    parse_upstream_tag(tag)
    if supplied_repository is not None:
        repository = supplied_repository.resolve()
        commit = str(
            run(["git", "rev-parse", f"{tag}^{{commit}}"], cwd=repository)
        ).strip()
        yield UpstreamCheckout(repository, tag, commit)
        return
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="hysteria-upstream-", dir=ROOT / "build"
    ) as raw:
        repository = pathlib.Path(raw)
        run(["git", "init", "--quiet"], cwd=repository)
        run(["git", "remote", "add", "origin", UPSTREAM_URL], cwd=repository)
        run(
            ["git", "fetch", "--quiet", "--depth=1", "origin", f"refs/tags/{tag}"],
            cwd=repository,
        )
        commit = str(
            run(["git", "rev-parse", "FETCH_HEAD^{commit}"], cwd=repository)
        ).strip()
        yield UpstreamCheckout(repository, "FETCH_HEAD", commit)


def upstream_tree(
    checkout: UpstreamCheckout,
) -> tuple[dict[str, tuple[str, str]], set[str]]:
    output = run(
        ["git", "ls-tree", "-r", "-z", checkout.treeish],
        cwd=checkout.repository,
        text=False,
    )
    assert isinstance(output, bytes)
    blobs: dict[str, tuple[str, str]] = {}
    gitlinks: set[str] = set()
    for raw_entry in output.split(b"\0"):
        if not raw_entry:
            continue
        metadata, raw_path = raw_entry.split(b"\t", 1)
        mode, object_type, object_hash = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if object_type == "blob":
            blobs[path] = (mode, object_hash)
        elif mode == "160000" and object_type == "commit":
            gitlinks.add(path)
        else:
            raise SyncError(
                f"Unsupported upstream tree entry {mode} {object_type} at {path}"
            )
    return blobs, gitlinks


def safe_extract(archive: pathlib.Path, destination: pathlib.Path) -> None:
    destination_resolved = destination.resolve()
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            target = (destination / member.name).resolve()
            if target != destination_resolved and destination_resolved not in target.parents:
                raise SyncError(f"Unsafe path in upstream archive: {member.name}")
        if hasattr(tarfile, "data_filter"):
            source.extractall(destination, filter="data")
        else:
            source.extractall(destination)


def export_upstream(checkout: UpstreamCheckout, destination: pathlib.Path) -> None:
    archive = destination.parent / "upstream.tar"
    run(
        [
            "git",
            "archive",
            "--format=tar",
            f"--output={archive}",
            checkout.treeish,
        ],
        cwd=checkout.repository,
    )
    destination.mkdir()
    safe_extract(archive, destination)
    archive.unlink()


def patch_files() -> tuple[pathlib.Path, ...]:
    if not PATCH_DIR.is_dir():
        return ()
    return tuple(sorted(PATCH_DIR.glob("*.patch")))


def patch_targets(
    patches: Sequence[pathlib.Path], destination: pathlib.Path
) -> set[pathlib.Path]:
    targets = set()
    destination_resolved = destination.resolve()
    for patch in patches:
        for line in patch.read_text(encoding="utf-8").splitlines():
            if not line.startswith("+++ b/"):
                continue
            relative = pathlib.PurePosixPath(line.removeprefix("+++ b/"))
            if relative.is_absolute() or ".." in relative.parts:
                raise SyncError(f"Unsafe target path in {patch.name}: {relative}")
            target = destination.joinpath(*relative.parts).resolve()
            if destination_resolved not in target.parents or not target.is_file():
                raise SyncError(f"Invalid target path in {patch.name}: {relative}")
            targets.add(target)
    if not targets:
        raise SyncError("Explicit patches do not contain any file targets")
    return targets


def apply_patches(destination: pathlib.Path) -> None:
    patches = patch_files()
    if not patches:
        return
    targets = patch_targets(patches, destination)
    uses_crlf = any(b"\r\n" in target.read_bytes() for target in targets)
    run(["git", "init", "--quiet"], cwd=destination)
    # Normalize CRLF patch targets through the temporary index while leaving
    # LF-only trees byte-stable.
    run(
        ["git", "config", "core.autocrlf", str(uses_crlf).lower()],
        cwd=destination,
    )
    run(["git", "add", "--force", "--all"], cwd=destination)
    try:
        for patch in patches:
            run(["git", "apply", "--check", str(patch)], cwd=destination)
            run(["git", "apply", str(patch)], cwd=destination)
    finally:
        shutil.rmtree(destination / ".git", ignore_errors=True)


def tree_files(root: pathlib.Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if ".git" not in path.relative_to(root).parts
        and (path.is_file() or path.is_symlink())
    )


def git_blob_hash(path: pathlib.Path, *, filters: bool) -> str:
    command = ["git", "hash-object"]
    if not filters:
        command.append("--no-filters")
    command.append(str(path))
    return str(run(command)).strip()


def verify_file_modes(expected: dict[str, tuple[str, str]]) -> None:
    if os.name == "nt":
        print("Skipping executable-mode verification on Windows")
        return
    changed = []
    for path, (expected_mode, _) in expected.items():
        source = VENDOR_DIR / path
        if source.is_symlink():
            actual_mode = "120000"
        elif source.stat().st_mode & stat.S_IXUSR:
            actual_mode = "100755"
        else:
            actual_mode = "100644"
        if actual_mode != expected_mode:
            changed.append(f"{path} ({actual_mode}, expected {expected_mode})")
    if changed:
        raise SyncError("Modified upstream file modes: " + ", ".join(changed))


def verify_vendor(checkout: UpstreamCheckout) -> None:
    upstream_blobs, gitlinks = upstream_tree(checkout)
    if gitlinks != OMITTED_UPSTREAM_GITLINKS:
        raise SyncError(
            "Upstream gitlinks changed; expected "
            f"{', '.join(sorted(OMITTED_UPSTREAM_GITLINKS)) or 'none'}; found "
            f"{', '.join(sorted(gitlinks)) or 'none'}"
        )
    collisions = PROJECT_ADDITIONS.intersection(upstream_blobs)
    if collisions:
        raise SyncError(
            "Upstream now owns project addition paths: "
            + ", ".join(sorted(collisions))
        )
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="hysteria-expected-", dir=ROOT / "build"
    ) as raw:
        expected_root = pathlib.Path(raw) / "hysteria2-go"
        export_upstream(checkout, expected_root)
        apply_patches(expected_root)
        expected_paths = set(tree_files(expected_root))
        upstream_paths = set(upstream_blobs)
        if expected_paths != upstream_paths:
            added = sorted(expected_paths - upstream_paths)
            removed = sorted(upstream_paths - expected_paths)
            details = []
            if added:
                details.append("added by patches: " + ", ".join(added))
            if removed:
                details.append("removed by patches: " + ", ".join(removed))
            raise SyncError(
                "Explicit patches may modify but not add or remove upstream paths; "
                + "; ".join(details)
            )
        actual_paths = set(tree_files(VENDOR_DIR))
        allowed_paths = expected_paths.union(PROJECT_ADDITIONS)
        missing = sorted(allowed_paths - actual_paths)
        unexpected = sorted(actual_paths - allowed_paths)
        if missing or unexpected:
            details = []
            if missing:
                details.append("missing: " + ", ".join(missing))
            if unexpected:
                details.append("unexpected: " + ", ".join(unexpected))
            raise SyncError("Vendor path mismatch; " + "; ".join(details))
        changed = []
        for relative in sorted(expected_paths):
            actual_hash = git_blob_hash(VENDOR_DIR / relative, filters=True)
            expected_hash = git_blob_hash(expected_root / relative, filters=True)
            if actual_hash != expected_hash:
                changed.append(relative)
        if changed:
            raise SyncError("Modified upstream files: " + ", ".join(changed))
    verify_file_modes(upstream_blobs)
    patch_names = ", ".join(path.name for path in patch_files()) or "none"
    print(
        f"Verified {len(upstream_blobs)} upstream files against {checkout.commit}; "
        f"project additions: {', '.join(sorted(PROJECT_ADDITIONS))}; "
        f"patches: {patch_names}"
    )


def verify_command(args: argparse.Namespace) -> None:
    tag = args.tag or current_upstream_tag()
    with upstream_checkout(tag, args.upstream_dir) as checkout:
        if tag == current_upstream_tag() and checkout.commit != current_upstream_commit():
            raise SyncError(
                f"Upstream tag {tag} resolved to {checkout.commit}, "
                f"not pinned commit {current_upstream_commit()}"
            )
        verify_vendor(checkout)


def ensure_clean_worktree() -> None:
    status = str(run(["git", "status", "--porcelain", "--untracked-files=all"])).strip()
    if status:
        raise SyncError("Synchronization requires a clean Git worktree")


def write_metadata(path: pathlib.Path, value: str) -> None:
    path.write_text(f"{value}\n", encoding="utf-8", newline="\n")


def sync_command(args: argparse.Namespace) -> None:
    ensure_clean_worktree()
    current_tag = current_upstream_tag()
    current_commit = current_upstream_commit()
    current_package = current_package_version()
    current_version = parse_upstream_tag(current_tag)
    target_version = parse_upstream_tag(args.tag)
    if target_version < current_version:
        raise SyncError(f"Refusing to downgrade from {current_tag} to {args.tag}")
    with upstream_checkout(current_tag, args.current_upstream_dir) as current_checkout:
        if current_checkout.commit != current_commit:
            raise SyncError(
                f"Upstream tag {current_tag} resolved to {current_checkout.commit}, "
                f"not pinned commit {current_commit}"
            )
        verify_vendor(current_checkout)
    if target_version == current_version:
        print(f"{current_tag} is already synchronized")
        return
    (ROOT / "build").mkdir(exist_ok=True)
    with upstream_checkout(args.tag, args.upstream_dir) as target_checkout:
        target_blobs, _ = upstream_tree(target_checkout)
        collisions = PROJECT_ADDITIONS.intersection(target_blobs)
        if collisions:
            raise SyncError(
                "Upstream now owns project addition paths: "
                + ", ".join(sorted(collisions))
            )
        with tempfile.TemporaryDirectory(
            prefix="hysteria-import-", dir=ROOT / "build"
        ) as raw:
            temporary = pathlib.Path(raw)
            staged_vendor = temporary / "hysteria2-go"
            export_upstream(target_checkout, staged_vendor)
            apply_patches(staged_vendor)
            for relative in PROJECT_ADDITIONS:
                source = VENDOR_DIR / relative
                if not source.is_file():
                    raise SyncError(f"Missing project-owned addition: {relative}")
                destination = staged_vendor / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            backup = temporary / "previous-hysteria2-go"
            VENDOR_DIR.rename(backup)
            try:
                staged_vendor.rename(VENDOR_DIR)
                write_metadata(UPSTREAM_VERSION_FILE, args.tag)
                write_metadata(UPSTREAM_COMMIT_FILE, target_checkout.commit)
                write_metadata(PACKAGE_VERSION_FILE, upstream_package_version(args.tag))
                verify_vendor(target_checkout)
            except BaseException:
                if VENDOR_DIR.exists():
                    shutil.rmtree(VENDOR_DIR)
                backup.rename(VENDOR_DIR)
                write_metadata(UPSTREAM_VERSION_FILE, current_tag)
                write_metadata(UPSTREAM_COMMIT_FILE, current_commit)
                write_metadata(PACKAGE_VERSION_FILE, current_package)
                raise
    print(f"Synchronized Hysteria {args.tag} ({target_checkout.commit})")


def guard_release(args: argparse.Namespace) -> None:
    if current_upstream_tag() != args.upstream_tag:
        raise SyncError(
            f"Release upstream tag {args.upstream_tag} does not match "
            f"{UPSTREAM_VERSION_FILE.name} ({current_upstream_tag()})"
        )
    expected_release_tag = downstream_tag(current_package_version())
    if args.release_tag != expected_release_tag:
        raise SyncError(
            f"Release tag {args.release_tag} does not match package version "
            f"({expected_release_tag})"
        )
    encoded_tag = urllib.parse.quote(args.release_tag, safe="")
    tag_exists = github_resource_exists(f"git/ref/tags/{encoded_tag}")
    if tag_exists and not args.allow_existing_tag:
        raise SyncError(f"Project tag {args.release_tag} already exists unexpectedly")
    if not tag_exists and args.allow_existing_tag:
        raise SyncError(f"Expected project tag {args.release_tag} does not exist")
    if github_resource_exists(f"releases/tags/{encoded_tag}"):
        raise SyncError(
            f"Project GitHub Release {args.release_tag} already exists unexpectedly"
        )
    if pypi_version_exists(current_package_version()):
        raise SyncError(
            f"PyPI version {current_package_version()} already exists unexpectedly"
        )
    print(f"Release target {args.release_tag} is available")


def release_notes_text(upstream_tag: str) -> str:
    parse_upstream_tag(upstream_tag)
    return f"Corresponds to hysteria2 {upstream_tag.removeprefix('app/')}\n"


def release_notes_command(args: argparse.Namespace) -> None:
    if args.upstream_tag != current_upstream_tag():
        raise SyncError(
            f"Release upstream tag {args.upstream_tag} does not match "
            f"{UPSTREAM_VERSION_FILE.name} ({current_upstream_tag()})"
        )
    notes = release_notes_text(args.upstream_tag)
    if args.output is None:
        print(notes, end="")
    else:
        args.output.write_text(notes, encoding="utf-8", newline="\n")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="check for a new stable release")
    check.add_argument("--tag", help="check one explicit stable app/vX.Y.Z release")
    check.add_argument("--github-output", type=pathlib.Path)
    check.set_defaults(handler=check_release)

    verify = commands.add_parser("verify", help="verify the current vendor tree")
    verify.add_argument("--tag", help="upstream tag; defaults to UPSTREAM_VERSION")
    verify.add_argument("--upstream-dir", type=pathlib.Path)
    verify.set_defaults(handler=verify_command)

    sync = commands.add_parser("sync", help="synchronize an exact upstream tag")
    sync.add_argument("--tag", required=True)
    sync.add_argument("--upstream-dir", type=pathlib.Path)
    sync.add_argument("--current-upstream-dir", type=pathlib.Path)
    sync.set_defaults(handler=sync_command)

    guard = commands.add_parser(
        "guard-release", help="fail if a release target is inconsistent or occupied"
    )
    guard.add_argument("--release-tag", required=True)
    guard.add_argument("--upstream-tag", required=True)
    guard.add_argument("--allow-existing-tag", action="store_true")
    guard.set_defaults(handler=guard_release)

    notes = commands.add_parser("release-notes", help="write release provenance text")
    notes.add_argument("--upstream-tag", required=True)
    notes.add_argument("--output", type=pathlib.Path)
    notes.set_defaults(handler=release_notes_command)

    return result


def main() -> int:
    args = parser().parse_args()
    try:
        args.handler(args)
    except SyncError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
