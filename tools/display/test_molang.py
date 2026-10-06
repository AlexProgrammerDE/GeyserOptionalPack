#!/usr/bin/env python3
"""Run the generated scripts in MoJava with checksum-pinned test dependencies."""
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPENDENCIES = [
    ('mojava.jar', 'https://repo.opencollab.dev/maven-snapshots/org/cloudburstmc/mojava/0.0.1-SNAPSHOT/mojava-0.0.1-20260627.182152-2.jar', '9db3c78a27a401fcc7ef1d5510fae84193b5d3645fa2ff9bf576afcd9968c70f'),
    ('asm.jar', 'https://repo.maven.apache.org/maven2/org/ow2/asm/asm/9.7/asm-9.7.jar', 'adf46d5e34940bdf148ecdd26a9ee8eea94496a72034ff7141066b3eea5c4e9d'),
    ('gson.jar', 'https://repo.maven.apache.org/maven2/com/google/code/gson/gson/2.11.0/gson-2.11.0.jar', '57928d6e5a6edeb2abd3770a8f95ba44dce45f3b23b7a9dc2b309c581552a78b'),
]


def main():
    with tempfile.TemporaryDirectory(prefix='display-molang-') as directory:
        work = Path(directory)
        libraries = []
        for filename, url, checksum in DEPENDENCIES:
            data = subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                                   '--max-time', '30', url], check=True, capture_output=True).stdout
            if hashlib.sha256(data).hexdigest() != checksum:
                raise ValueError(f'Checksum mismatch for {filename}')
            path = work / filename
            path.write_bytes(data)
            libraries.append(str(path))
        classpath = os.pathsep.join(libraries)
        subprocess.run(['javac', '--release', '17', '-cp', classpath, '-d', str(work),
                        str(ROOT / 'tools/display/tests/InterpolationTest.java')], check=True)
        subprocess.run(['java', '-cp', classpath + os.pathsep + str(work), 'InterpolationTest',
                        str(ROOT / 'entity/item_display.entity.json'), str(ROOT / 'entity/block_display.entity.json')], check=True)


if __name__ == '__main__':
    main()
