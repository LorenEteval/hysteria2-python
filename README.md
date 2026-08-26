# hysteria2-python

[![Deploy PyPI](https://github.com/LorenEteval/hysteria2-python/actions/workflows/deploy-pypi.yml/badge.svg?branch=main)](https://github.com/LorenEteval/hysteria2-python/actions/workflows/deploy-pypi.yml)

Python bindings for [hysteria2](https://github.com/apernet/hysteria).

## Install

```
pip install hysteria2
```

Published releases provide platform-specific binary wheels. On a supported Python, operating system, and architecture,
pip downloads the matching wheel, so Go, CMake, and a C/C++ compiler are not required for installation.

## Binary Wheel Platforms

Binary wheels are built and tested in [GitHub Actions](https://github.com/LorenEteval/hysteria2-python/actions).

| Platform                  | Architecture    | CPython versions |
|---------------------------|-----------------|:----------------:|
| Linux (manylinux2014)     | x86_64, aarch64 |     3.8-3.14     |
| Windows                   | AMD64           |     3.8-3.14     |
| Windows 11 ARM            | ARM64           |     3.9-3.14     |
| macOS 12 and later        | x86_64, arm64   |     3.8-3.14     |

Available free-threaded CPython 3.13 and 3.14 variants are also built. Windows ARM64 starts at Python 3.9 because
cibuildwheel does not provide a CPython 3.8 ARM64 build.

## Building from Source

Building from source is only necessary when no compatible wheel is available or when modifying the native binding.
The build requires:

* [Go](https://go.dev/doc/install) 1.25.1 or later in your PATH;
* a working C/C++ compiler toolchain;
* MinGW-w64 on Windows AMD64, or LLVM-MinGW on Windows ARM64.

## API

```pycon
>>> import hysteria2
>>> help(hysteria2) 
Help on package hysteria2:                                                                                                                                                                                    

NAME
    hysteria2

PACKAGE CONTENTS
    hysteria2

FUNCTIONS
    startFromJSON(...) method of builtins.PyCapsule instance
        startFromJSON(json: str) -> None

        Start Hysteria2 client with JSON
```

## Upstream Source and Releases

The [HyNetworks/hysteria](https://github.com/HyNetworks/hysteria) source is
vendored so source distributions and wheel builds are reproducible without a
Git submodule or an unpinned branch checkout. `UPSTREAM_VERSION` records the
exact release tag and `UPSTREAM_COMMIT` records the resolved commit.

The vendored upstream files are kept unchanged. Python-binding support is
implemented by two explicitly project-owned Go files:

* `hysteria2-go/app/cmd/python_binding.go`;
* `hysteria2-go/app/python_binding.go`.

`scripts/sync-hysteria.py verify` compares every other vendored file and its
mode with the pinned upstream commit. Scheduled automation detects stable
upstream releases, imports the exact tag, runs validation, and reuses the
normal wheel/sdist publishing workflow.

## License

The license for this project follows its original go repository [hysteria](https://github.com/apernet/hysteria) and is
under [MIT License](https://github.com/LorenEteval/hysteria2-python/blob/main/LICENSE).
