#!/usr/bin/env python3
"""Install the Go toolchain selected by a go.mod file on Linux."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


DOWNLOAD_INDEX = "https://go.dev/dl/?mode=json&include=all"
DOWNLOAD_ROOT = "https://go.dev/dl"
VERSION_PATTERN = re.compile(r"\d+\.\d+(?:\.\d+)?(?:beta\d+|rc\d+)?\Z")
ARCHITECTURES = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64"}


def read_go_version(go_mod: Path) -> str:
    """Return the toolchain directive, falling back to the go directive."""
    directives: dict[str, str] = {}
    for raw_line in go_mod.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("//", 1)[0].strip()
        fields = line.split()
        if len(fields) >= 2 and fields[0] in {"go", "toolchain"}:
            directives[fields[0]] = fields[1]

    toolchain = directives.get("toolchain")
    if toolchain and toolchain != "default":
        if not toolchain.startswith("go"):
            raise ValueError(f"Unsupported toolchain directive: {toolchain}")
        version = toolchain.removeprefix("go")
    else:
        version = directives.get("go", "")

    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Unsupported or missing Go version in {go_mod}: {version!r}")
    return version


def select_archive(
    releases: list[dict[str, Any]], requested: str, architecture: str
) -> dict[str, Any]:
    """Select the official Linux archive for the requested Go version."""
    exact = requested.count(".") >= 2 or "beta" in requested or "rc" in requested
    if exact:
        candidates = [
            release
            for release in releases
            if release.get("version") == f"go{requested}"
        ]
    else:
        prefix = f"go{requested}."
        candidates = [
            release
            for release in releases
            if release.get("stable")
            and str(release.get("version", "")).startswith(prefix)
        ]
        candidates.sort(key=_stable_version_key, reverse=True)

    if not candidates:
        raise ValueError(f"Go {requested} was not found in the official download index")

    for release in candidates:
        for file_info in release.get("files", []):
            if (
                file_info.get("os") == "linux"
                and file_info.get("arch") == architecture
                and file_info.get("kind") == "archive"
            ):
                sha256 = str(file_info.get("sha256", ""))
                if not re.fullmatch(r"[0-9a-f]{64}", sha256):
                    raise ValueError(
                        "The official download index returned an invalid checksum"
                    )
                return file_info

    raise ValueError(f"No Linux {architecture} archive exists for Go {requested}")


def _stable_version_key(release: dict[str, Any]) -> tuple[int, int, int]:
    match = re.fullmatch(r"go(\d+)\.(\d+)\.(\d+)", str(release.get("version", "")))
    if not match:
        return (-1, -1, -1)
    return tuple(int(part) for part in match.groups())


def fetch_json(url: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "hysteria2-python-build"}
    )
    with urllib.request.urlopen(request) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise ValueError("The official Go download index is not a list")
    return payload


def download_verified(url: str, destination: Path, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    request = urllib.request.Request(
        url, headers={"User-Agent": "hysteria2-python-build"}
    )
    with urllib.request.urlopen(request) as response, destination.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ValueError(f"Checksum mismatch for {url}")


def install(go_mod: Path, install_dir: Path, machine: str) -> None:
    architecture = ARCHITECTURES.get(machine.lower())
    if not architecture:
        raise ValueError(f"Unsupported Linux architecture: {machine}")

    version = read_go_version(go_mod)
    archive = select_archive(fetch_json(DOWNLOAD_INDEX), version, architecture)
    filename = str(archive["filename"])
    if Path(filename).name != filename or not filename.endswith(".tar.gz"):
        raise ValueError(f"Invalid archive filename in download index: {filename}")

    if install_dir.exists() and any(install_dir.iterdir()):
        raise ValueError(f"Installation directory is not empty: {install_dir}")
    install_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="go-toolchain-") as temporary_dir:
        archive_path = Path(temporary_dir, filename)
        download_verified(
            f"{DOWNLOAD_ROOT}/{filename}", archive_path, str(archive["sha256"])
        )
        subprocess.run(
            [
                "tar",
                "-xzf",
                str(archive_path),
                "-C",
                str(install_dir),
                "--strip-components=1",
            ],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--go-mod", type=Path, required=True)
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--machine", default=platform.machine())
    args = parser.parse_args()
    install(args.go_mod, args.install_dir, args.machine)


if __name__ == "__main__":
    main()
