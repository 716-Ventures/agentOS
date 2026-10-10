#!/usr/bin/env python3
"""Deploy an exact source tree to the selected Linux guest and build there."""
from pathlib import Path
import io
import shlex
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'vm-foundation'))
import vm


def main():
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w') as tar:
        for folder,prefix in [(ROOT,''),(ROOT.parent/'native-shell','native-shell'),(ROOT.parent/'native-compositor','native-compositor')]:
            for path in sorted(folder.rglob('*')):
                relative=path.relative_to(folder)
                if path.is_file() and not any(p in ('target','__pycache__','.git','test-output') for p in relative.parts):
                    tar.add(path,arcname=str(Path(prefix)/relative))
    staged=vm.ssh('mktemp -d /home/developer/.agent-os-source.XXXXXXXX',capture_output=True,text=True,check=True).stdout.strip()
    try:
        subprocess.run(vm.ssh_args()+['tar xf - -C '+shlex.quote(staged)],input=archive.getvalue(),check=True)
        # Keep the old source, but carry only its build cache into the exact new tree.
        script='''
from pathlib import Path
import time
source=Path('/home/developer/agent-os-source')
staged=Path(STAGED)
previous=source.with_name(source.name+'.previous-'+str(time.time_ns()))
if source.exists():source.rename(previous)
try:staged.rename(source)
except BaseException:
    if previous.exists():previous.rename(source)
    raise
for name in ('target','native-shell/target','native-compositor/target'):
    if (previous/name).exists():(previous/name).rename(source/name)
'''.replace('STAGED',repr(staged))
        subprocess.run(vm.ssh_args()+['python3 -'],input=script.encode(),check=True)
    finally:
        script='import shutil; shutil.rmtree('+repr(staged)+',ignore_errors=True)'
        subprocess.run(vm.ssh_args()+['python3 -c '+shlex.quote(script)],check=True)
    subprocess.run(vm.ssh_args()+['cd /home/developer/agent-os-source && sh install.sh'],check=True)

if __name__=='__main__':main()
