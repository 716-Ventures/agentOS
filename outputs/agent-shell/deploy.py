#!/usr/bin/env python3
"""Deploy the checked-in source to the existing full Linux guest and build there."""
from pathlib import Path
import io
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'vm-foundation'))
import vm

archive=io.BytesIO()
with tarfile.open(fileobj=archive,mode='w') as tar:
    for path in sorted(ROOT.rglob('*')):
        if path.is_file() and not any(p in ('target','__pycache__','.git') for p in path.parts):
            tar.add(path,arcname=str(path.relative_to(ROOT)))
subprocess.run(vm.ssh_args()+['mkdir -p /home/developer/agent-os-source && tar xf - -C /home/developer/agent-os-source'],input=archive.getvalue(),check=True)
subprocess.run(vm.ssh_args()+['cd /home/developer/agent-os-source && sh install.sh'],check=True)
