# hysteria2-python

[![Build hysteria binding](https://github.com/LorenEteval/hysteria2-python/actions/workflows/wheels.yml/badge.svg?branch=main)](https://github.com/LorenEteval/hysteria2-python/actions/workflows/wheels.yml)

Python bindings for [hysteria2](https://github.com/apernet/hysteria). This package provides a bridge to start hysteria
client directly from Python on any platform.

Python binding for legacy hysteria1: [hysteria-python](https://github.com/LorenEteval/hysteria-python)

Looking for [Xray-core](https://github.com/XTLS/Xray-core) bindings?
Check [Xray-core-python](https://github.com/LorenEteval/Xray-core-python).

See the real-world production GUI client that takes advantage of the Python binding:
[Furious](https://github.com/LorenEteval/Furious).

## Start

To use this binding, please first make sure that:

* You are a Python developer, or your application is associated with this package.
* You are building a client application. There is no point to use binding on the server side.
* You want to provide additional abstraction for your client. The core(i.e. hysteria) will be shipped with your
  application as dynamic link library, not an executable.
* This bridge provides functionality to start hysteria directly from Python string(see the API below). What that means
  is that the client config stays in memory all the time, and cannot(or very hard to) be inspected. So you can, for
  example, get a configuration template from a remote server and edit it for a group of specific client and start the
  service.

## Install

### Core Building Tools

You have to install the following tools to be able to install this package successfully.

* [go](https://go.dev/doc/install) in your PATH. go 1.20.0 and above is recommended. To check go is ready,
  type `go version`. Also, if google service is blocked in your region(such as Mainland China), you have to configure
  your GOPROXY to be able to pull go packages. For Chinese users, refer to [goproxy.cn](https://goproxy.cn/) for more
  information.
* [cmake](https://cmake.org/download/) in your PATH. To check cmake is ready, type `cmake --version`.
* A working GNU C++ compiler(i.e. GNU C++ toolchains). To check GNU C++ compiler is ready, type `g++ --version`. These
  tools should have been installed in Linux or macOS by default. If you don't have GNU C++ toolchains(especially for
  Windows users) anyway:

    * For Linux users: type `sudo apt update && sudo apt install g++` and that should work out fine.
    * For Windows users: install [MinGW-w64](https://sourceforge.net/projects/mingw-w64/files/mingw-w64/)
      or [Cygwin](https://www.cygwin.com/) and make sure you have add them to PATH.

### Install Package

```
pip install hysteria2
```

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

## Source Code Modification

This repository, including the package that distributes to pypi,
contains [hysteria](https://github.com/apernet/hysteria) source code that's been
modified to build the binding and specific API. If without explicitly remark, the version of this package corresponds to
the version of the origin source code tag, so the binding will have full features as the original go distribution will
have. And due to its backward compatibility, there's no plan to generate bindings for older release of hysteria.

To make installation of this package easier, I didn't add the original [hysteria](https://github.com/apernet/hysteria)
source code as a submodule. To track what modifications have been made to the source code, you can compare it with the
same version under Python binding and corresponding go repository.

## Tested Platform

hysteria2-python works on all major platform with all Python version(Python 3).

Below are tested build in [github actions](https://github.com/LorenEteval/hysteria2-python/actions).

| Platform     | Python 3.7-Python 3.11 |
|--------------|:----------------------:|
| ubuntu 20.04 |   :heavy_check_mark:   |
| ubuntu 22.04 |   :heavy_check_mark:   |
| windows-2019 |   :heavy_check_mark:   |
| windows-2022 |   :heavy_check_mark:   |
| macos-11     |   :heavy_check_mark:   |
| macos-12     |   :heavy_check_mark:   |
| macos-13     |   :heavy_check_mark:   |

## License

The license for this project follows its original go repository [hysteria](https://github.com/apernet/hysteria) and is
under [MIT License](https://github.com/LorenEteval/hysteria2-python/blob/main/LICENSE).
