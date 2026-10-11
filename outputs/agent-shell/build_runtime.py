#!/usr/bin/env python3
"""Build current local crates even when restored source timestamps moved backward."""
from pathlib import Path
import subprocess


def build_release(manifest, package):
    # Cargo's source freshness checks can accept an older restored mtime even
    # when the bytes differ. Remove only this package's artifacts, retaining
    # dependency caches. Include debug artifacts used by qualification as well.
    for profile in ('dev', 'release'):
        subprocess.run(['cargo', 'clean', '--profile', profile, '--manifest-path', str(manifest), '--package', package], check=True)
    subprocess.run(['cargo', 'build', '--release', '--locked', '--manifest-path', str(manifest)], check=True)


def main():
    root = Path(__file__).resolve().parent
    native = root if (root/'native-shell').is_dir() else root.parent
    for manifest, package in (
        (root/'Cargo.toml', 'agent-os-core'),
        (native/'native-shell/Cargo.toml', 'agent-os-desktop'),
        (native/'native-compositor/Cargo.toml', 'agent-os-compositor'),
    ):
        build_release(manifest, package)


if __name__ == '__main__':
    main()
