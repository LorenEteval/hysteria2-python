from setuptools import setup, find_packages
from setuptools.command.install import install

import pathlib
import platform
import subprocess


PLATFORM = platform.system()
ROOT_DIR = pathlib.Path().resolve()
PACKAGE_NAME = 'hysteria2'
BINDING_NAME = 'hysteria2'
CMAKE_BUILD_CACHE = 'CMakeBuildCache'


def getHysteriaVersion():
    return '2.7.0'


def runCommand(command):
    subprocess.run(command, check=True)


def buildHysteria():
    output = f'{BINDING_NAME}.lib' if PLATFORM == 'Windows' else f'{BINDING_NAME}.a'

    runCommand(
        [
            'go',
            'build',
            '-C',
            'hysteria2-go',
            '-o',
            f'{ROOT_DIR / "gobuild" / output}',
            '-buildmode=c-archive',
            '-trimpath',
            '-ldflags',
            '-s -w -buildid=',
            './app',
        ]
    )


def buildBindings():
    configureCache = [
        'cmake',
        '-S',
        '.',
        '-B',
        CMAKE_BUILD_CACHE,
        '-DCMAKE_BUILD_TYPE=Release',
    ]

    if PLATFORM == 'Windows':
        configureCache += ['-G', 'MinGW Makefiles']

    runCommand(configureCache)

    runCommand(
        [
            'cmake',
            '--build',
            CMAKE_BUILD_CACHE,
            '--target',
            BINDING_NAME,
        ]
    )


class InstallHysteria(install):
    def run(self):
        buildHysteria()
        buildBindings()

        install.run(self)


with open('README.md', 'r', encoding='utf-8') as file:
    long_description = file.read()


setup(
    name=PACKAGE_NAME,
    version=getHysteriaVersion(),
    license='MIT',
    description='Python bindings for hysteria2.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Loren Eteval',
    author_email='loren.eteval@proton.me',
    url='https://github.com/LorenEteval/hysteria2-python',
    cmdclass={'install': InstallHysteria},
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
        'Operating System :: OS Independent',
        'Topic :: Internet',
        'Topic :: Internet :: Proxy Servers',
    ],
    zip_safe=False,
)
