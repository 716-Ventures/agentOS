#!/usr/bin/env python3
"""Exercise graphical verification from the exact flattened deployment archive."""
import importlib.util
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('deployment',ROOT/'deploy.py')
deployment=importlib.util.module_from_spec(spec);spec.loader.exec_module(deployment)
with tempfile.TemporaryDirectory(prefix='agentos-deployed-graphics-') as directory:
    tree=Path(directory)
    with tarfile.open(fileobj=io.BytesIO(deployment.source_archive())) as archive:
        archive.extractall(tree,filter='data')
    # Reuse real compiled programs, never generated runtime state or credentials.
    for target,upstream in [('target',ROOT/'target'),('native-shell/target',ROOT.parent/'native-shell/target'),('native-compositor/target',ROOT.parent/'native-compositor/target')]:
        (tree/target).symlink_to(upstream.resolve(),target_is_directory=True)
    for command in [
        ['dbus-run-session','--','python3','native-shell/tests/native_desktop.py'],
        ['dbus-run-session','--','python3','native-shell/tests/native_session.py'],
        ['python3','tests/graphical_release.py']]:
        subprocess.run(command,cwd=tree,check=True,timeout=300)
print('PASS: native rendering, session cleanup and signed packaging from exact deployment layout')
