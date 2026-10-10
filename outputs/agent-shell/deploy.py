#!/usr/bin/env python3
"""Deploy an exact source tree to the selected Linux guest and build there."""
from pathlib import Path
import io
import os
import shlex
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'vm-foundation'))


def source_archive(repository=ROOT.parent.parent):
    """Package tracked runtime sources; ignored state and build caches stay on the host."""
    repository=Path(repository).resolve()
    folders=[('outputs/agent-shell',''),('outputs/native-shell','native-shell'),('outputs/native-compositor','native-compositor')]
    names=subprocess.check_output(['git','-C',str(repository),'ls-files','-z','--',*[folder for folder,_ in folders]])
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w') as tar:
        for raw in sorted(set(names.split(b'\0'))-{b''}):
            relative=Path(os.fsdecode(raw));path=repository/relative
            if path.is_symlink() or not path.resolve().is_relative_to(repository):raise ValueError('Deployment sources must be regular files inside the repository')
            if not path.exists():continue
            if not path.is_file():raise ValueError('Invalid tracked deployment source')
            for folder,prefix in folders:
                if relative.is_relative_to(folder):
                    tar.add(path,arcname=str(Path(prefix)/relative.relative_to(folder)),recursive=False);break
    return archive.getvalue()


def main():
    import vm
    archive=source_archive()
    staged=vm.ssh('mktemp -d /home/developer/.agent-os-source.XXXXXXXX',capture_output=True,text=True,check=True).stdout.strip()
    try:
        subprocess.run(vm.ssh_args()+['tar xf - -C '+shlex.quote(staged)],input=archive,check=True)
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
