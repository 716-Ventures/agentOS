#!/usr/bin/python3
"""Stage complete runtime releases and resume interrupted activation without rebuilding."""
import argparse
import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import time

SOURCE=Path(__file__).resolve().parent
UNITS=['agent-os-core','agent-os-layout','agent-os-disk','agent-os-broker','agent-os-ai']


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path,data,mode=0o644):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data);f.flush();os.fchmod(f.fileno(),mode);os.fsync(f.fileno())
        os.replace(name,path)
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        Path(name).unlink(missing_ok=True)


class Installer:
    def __init__(self,prefix=Path('/')):
        self.prefix=prefix
        self.root=self.path('/usr/local/lib/agent-os')
        self.state=self.path('/var/lib/agent-os-install')
        self.journal=self.state/'transaction.json'

    def path(self,value):return self.prefix / value.lstrip('/')
    def run(self,args,**kw):return subprocess.run(args,check=True,**kw)
    def record(self,transaction):
        atomic_write(self.journal,(json.dumps(transaction,indent=2)+'\n').encode(),0o600)

    def stage(self,source):
        files={'agent-os-core':source/'target/release/agent-os-core'}
        for pattern in ('services/*.py','services/*-launcher.sh','systemd/*.service','client/agent_os.py'):
            files.update({str(p.relative_to(source)):p for p in sorted(source.glob(pattern))})
        for name in ('Cargo.lock','Cargo.toml','dependencies.json','install_runtime.py'):
            files[name]=source/name
        files['dependencies.installed.json']=self.state/'dependencies.json'
        for name,path in files.items():
            if name.endswith('.py'):ast.parse(path.read_bytes(),filename=name)
        binary=files['agent-os-core'].read_bytes()
        if binary[:4]!=b'\x7fELF' or len(binary)<20 or binary[4:6]!=b'\x02\x01' or int.from_bytes(binary[18:20],'little')!=183:
            raise ValueError('Build the ARM64 Linux executable before installing')
        hashes={name:digest(path) for name,path in files.items()}
        ident=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
        self.root.mkdir(mode=0o755,parents=True,exist_ok=True)
        releases=self.root/'releases';releases.mkdir(mode=0o755,exist_ok=True)
        target=releases/ident
        if target.exists():self.verify(target);return ident
        with tempfile.TemporaryDirectory(prefix='.stage-',dir=releases) as tmp:
            staged=Path(tmp);staged.chmod(0o755)
            for name,path in files.items():
                dest=staged/name;dest.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
                mode=0o755 if name=='agent-os-core' or name=='client/agent_os.py' or name.endswith('-launcher.sh') else 0o644
                atomic_write(dest,path.read_bytes(),mode)
            atomic_write(staged/'manifest.json',json.dumps(hashes,indent=2,sort_keys=True).encode())
            self.verify(staged)
            # Copy to a durable root-owned release; the temporary tree cleans up independently.
            os.rename(staged,target)
            fd=os.open(releases,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
            # TemporaryDirectory cleanup tolerates the old pathname having moved.
        return ident

    def verify(self,release):
        hashes=json.loads((release/'manifest.json').read_text())
        if not isinstance(hashes,dict) or not hashes:raise ValueError('Invalid release manifest')
        for name,expected in hashes.items():
            path=release/name
            if not path.resolve().is_relative_to(release.resolve()) or digest(path)!=expected:
                raise ValueError('Staged release integrity check failed: '+name)
        return hashes

    def link(self,path,target):
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.is_dir() and not path.is_symlink():
            path.rename(path.with_name(path.name+'-legacy-'+str(time.time_ns())))
        temporary=path.with_name('.'+path.name+'-link')
        temporary.unlink(missing_ok=True);temporary.symlink_to(target)
        os.replace(temporary,path)
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def accounts(self):
        for group in ('agentos','agentos-ai','agentos-broker'):
            self.run(['groupadd','--system','-f',group])
        for name,group,home in (('agentos','agentos','runtime'),('agentos-layout','agentos','layout'),('agentos-ai','agentos-ai','ai')):
            try:pwd.getpwnam(name)
            except KeyError:self.run(['useradd','--system','--gid',group,'--home-dir','/var/lib/agent-os-'+home,'--shell','/usr/sbin/nologin',name])
        self.run(['usermod','-a','-G','agentos,agentos-broker','developer'])
        self.run(['usermod','-a','-G','agentos-broker','agentos-ai'])
        self.path('/var/lib/agent-os-workspaces').mkdir(mode=0o755,exist_ok=True)

    def health(self):
        deadline=time.monotonic()+30
        sockets=['/run/agent-os/runtime.sock','/run/agent-os-layout/api.sock','/run/agent-os-broker/api.sock',
                 '/run/agent-os-ai/api.sock','/run/agent-os-disk/api.sock']
        while time.monotonic()<deadline:
            states=subprocess.run(['systemctl','is-active',*UNITS],capture_output=True,text=True).stdout.splitlines()
            active=states==['active']*len(UNITS)
            ready=all(p.exists() and stat.S_ISSOCK(p.stat().st_mode) for p in map(self.path,sockets))
            if active and ready:
                # An active PID/socket alone cannot establish core startup/recovery readiness.
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
                    conn.settimeout(3);conn.connect(str(self.path(sockets[0])))
                    conn.sendall(b'{"op":"snapshot"}\n')
                    with conn.makefile('rb') as stream:result=json.loads(stream.readline(2*1024*1024))
                if result.get('ok'):return
            time.sleep(.2)
        raise RuntimeError('Runtime health checks failed; retain the journal and run recovery after inspecting services')

    def activate(self,ident,interrupt=None):
        if not re.fullmatch('[a-f0-9]{64}',ident):raise ValueError('Invalid staged release ID')
        release=self.root/'releases'/ident;hashes=self.verify(release)
        if hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()!=ident:
            raise ValueError('Release ID does not match its manifest')
        current=self.root/'current'
        transaction={'release':ident,'previous':str(current.resolve()) if current.exists() else None,'phase':'staged'}
        self.record(transaction)
        # Recovery remains callable even before the first release is activated.
        atomic_write(self.root/'install-recovery.py',(release/'install_runtime.py').read_bytes())
        self.accounts()
        existing=[name for name in UNITS if self.path('/etc/systemd/system/'+name+'.service').exists()]
        if existing:self.run(['systemctl','stop',*existing])
        transaction['phase']='stopped';self.record(transaction)
        if interrupt=='stopped':os.kill(os.getpid(),signal.SIGKILL)
        self.link(current,release)
        self.link(self.root/'services',current/'services')
        self.link(self.root/'agent-os-core',current/'agent-os-core')
        self.link(self.path('/usr/local/bin/agent-os'),current/'client/agent_os.py')
        for name in ('broker','configure'):
            self.link(self.path('/usr/local/bin/agent-os-'+name),current/'services'/f'{name}-launcher.sh')
        for name in UNITS:
            atomic_write(self.path('/etc/systemd/system/'+name+'.service'),(release/'systemd'/f'{name}.service').read_bytes())
        transaction['phase']='activated';self.record(transaction)
        if interrupt=='activated':os.kill(os.getpid(),signal.SIGKILL)
        self.run(['systemctl','daemon-reload'])
        self.run(['systemctl','enable','--now',*UNITS])
        self.health()
        metadata=self.path('/etc/agent-os/release.json')
        info=json.loads(metadata.read_text())
        info.update(version='0.6.0',milestone='Interactive terminal sessions',runtime_release=ident,
                    agent_runtime='Gateway agent with general execution and filesystem broker; Jev typed effect advisory',voice='not implemented')
        atomic_write(metadata,(json.dumps(info,indent=2)+'\n').encode())
        atomic_write(self.path('/etc/motd'),b'\nAgent OS 0.6 | Interactive terminal sessions\n\n  agent-os          Open the terminal environment\n  agent-os-status   Inspect the Linux foundation\n  sudo agent-os-configure   Set up providers\n\nOrdinary Linux shell and sudo remain available for recovery.\n\n')
        transaction.update(phase='complete',completed_at=time.time());self.record(transaction)
        atomic_write(self.state/'installed.json',(json.dumps(transaction,indent=2)+'\n').encode(),0o600)
        print('Installed and healthy:',ident)

    def recover(self):
        if not self.journal.exists():raise ValueError('No installation transaction to recover')
        transaction=json.loads(self.journal.read_text())
        self.activate(transaction['release'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recover',action='store_true')
    parser.add_argument('--test-interrupt',choices=['stopped','activated'],help='Development-guest crash injection; terminates installer with SIGKILL')
    args=parser.parse_args()
    if os.geteuid()!=0:parser.error('Run with sudo')
    installer=Installer();installer.state.mkdir(mode=0o700,parents=True,exist_ok=True);installer.state.chmod(0o700)
    with (installer.state/'lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if args.recover:installer.recover()
        else:
            if installer.journal.exists() and json.loads(installer.journal.read_text())['phase']!='complete':
                installer.recover()
            installer.activate(installer.stage(SOURCE),args.test_interrupt)

if __name__=='__main__':main()
