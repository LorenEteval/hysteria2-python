import os
import pathlib
import platform
import shlex
import subprocess
import sys

import pybind11
from setuptools import Extension, find_packages, setup
from setuptools.command.build_ext import build_ext


ROOT_DIR = pathlib.Path(__file__).resolve().parent
PACKAGE_NAME = 'hysteria2'
BINDING_NAME = 'hysteria2'


def get_hysteria_version():
    return (ROOT_DIR / 'PACKAGE_VERSION').read_text(encoding='utf-8').strip()


def get_macos_architecture():
    if platform.system() != 'Darwin':
        return None

    arch_flags = shlex.split(os.environ.get('ARCHFLAGS', ''))
    architectures = []
    for index, flag in enumerate(arch_flags):
        if flag == '-arch':
            if index + 1 == len(arch_flags):
                raise RuntimeError('ARCHFLAGS ends with -arch but has no architecture')
            architectures.append(arch_flags[index + 1])

    architectures = list(dict.fromkeys(architectures))
    if not architectures:
        return None
    if len(architectures) != 1:
        raise RuntimeError(
            'Universal2 builds are not supported because one Go c-archive '
            'cannot contain both macOS architectures; build separate x86_64 '
            'and arm64 wheels instead'
        )

    architecture = architectures[0]
    if architecture not in {'x86_64', 'arm64'}:
        raise RuntimeError(f'Unsupported macOS architecture: {architecture}')
    return architecture


class CMakeExtension(Extension):
    '''A setuptools extension whose sources are built by CMake.'''

    def __init__(self, name):
        # CMake owns the source list. Declaring an Extension tells setuptools
        # and wheel that this distribution contains platform-native code.
        super().__init__(name, sources=[])


class CMakeBuild(build_ext):
    '''Build the Go archive and pybind11 module into the wheel staging tree.'''

    def build_extension(self, ext):
        extension_path = pathlib.Path(self.get_ext_fullpath(ext.name)).resolve()
        extension_dir = extension_path.parent
        build_temp = pathlib.Path(self.build_temp).resolve() / ext.name
        go_build_dir = build_temp / 'gobuild'
        cmake_build_dir = build_temp / 'cmake'

        extension_dir.mkdir(parents=True, exist_ok=True)
        go_build_dir.mkdir(parents=True, exist_ok=True)
        cmake_build_dir.mkdir(parents=True, exist_ok=True)

        macos_architecture = get_macos_architecture()
        go_environment = os.environ.copy()
        go_environment['CGO_ENABLED'] = '1'
        if macos_architecture:
            go_environment['GOARCH'] = {
                'x86_64': 'amd64',
                'arm64': 'arm64',
            }[macos_architecture]
            for variable in ('CGO_CFLAGS', 'CGO_CXXFLAGS', 'CGO_LDFLAGS'):
                current_flags = go_environment.get(variable, '')
                go_environment[variable] = (
                    f'{current_flags} -arch {macos_architecture}'.strip()
                )

        archive_name = (
            f'{BINDING_NAME}.lib'
            if platform.system() == 'Windows'
            else f'{BINDING_NAME}.a'
        )
        subprocess.run(
            [
                'go',
                '-C',
                str(ROOT_DIR / 'hysteria2-go'),
                'build',
                '-mod=readonly',
                '-o',
                str(go_build_dir / archive_name),
                '-buildmode=c-archive',
                '-trimpath',
                '-ldflags',
                '-s -w -buildid=',
                './app',
            ],
            check=True,
            env=go_environment,
        )

        cmake_args = [
            '-S',
            str(ROOT_DIR),
            '-B',
            str(cmake_build_dir),
            '-DCMAKE_BUILD_TYPE=Release',
            f'-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={extension_dir.as_posix()}',
            f'-DCMAKE_LIBRARY_OUTPUT_DIRECTORY_RELEASE={extension_dir.as_posix()}',
            f'-DHYSTERIA2_GO_BUILD_DIR={go_build_dir.as_posix()}',
            f'-DHYSTERIA2_VERSION={get_hysteria_version()}',
            f'-Dpybind11_DIR={pathlib.Path(pybind11.get_cmake_dir()).as_posix()}',
            f'-DPython_EXECUTABLE={pathlib.Path(sys.executable).as_posix()}',
        ]
        if macos_architecture:
            cmake_args.append(f'-DCMAKE_OSX_ARCHITECTURES={macos_architecture}')
        if platform.system() == 'Windows':
            cmake_args.extend(['-G', 'MinGW Makefiles'])

        subprocess.run(['cmake', *cmake_args], check=True)

        build_args = [
            'cmake',
            '--build',
            str(cmake_build_dir),
            '--config',
            'Release',
            '--target',
            BINDING_NAME,
        ]
        if self.parallel:
            build_args.extend(['--parallel', str(self.parallel)])
        subprocess.run(build_args, check=True)

        if not extension_path.is_file():
            produced = ', '.join(path.name for path in extension_dir.glob('hysteria2*'))
            produced_description = produced or 'nothing'
            raise RuntimeError(
                f'CMake did not create the expected extension {extension_path.name}; '
                f'produced: {produced_description}'
            )


with (ROOT_DIR / 'README.md').open('r', encoding='utf-8') as file:
    long_description = file.read()


setup(
    name=PACKAGE_NAME,
    version=get_hysteria_version(),
    license='MIT',
    description='Python bindings for hysteria2.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Loren Eteval',
    author_email='loren.eteval@proton.me',
    url='https://github.com/LorenEteval/hysteria2-python',
    cmdclass={'build_ext': CMakeBuild},
    ext_modules=[CMakeExtension('hysteria2.hysteria2')],
    packages=find_packages(),
    include_package_data=True,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: MIT License',
        'Intended Audience :: Developers',
        'Programming Language :: C++',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Programming Language :: Python :: 3.14',
        'Topic :: Internet',
        'Topic :: Internet :: Proxy Servers',
    ],
    zip_safe=False,
)
