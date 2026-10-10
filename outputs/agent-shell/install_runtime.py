#!/usr/bin/python3
"""Stage complete runtime releases and resume interrupted activation without rebuilding."""
import argparse
import ast
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import socket
import sqlite3
import stat
import subprocess
import tempfile
import time

SOURCE=Path(__file__).resolve().parent
UNITS=['agent-os-core','agent-os-layout','agent-os-disk','agent-os-broker','agent-os-ai','agent-os-voice']


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
        for pattern in ('services/*.py','services/*-launcher.sh','systemd/*.service','client/*.py','session/*.desktop'):
            files.update({str(p.relative_to(source)):p for p in sorted(source.glob(pattern))})
        for name in ('LICENSE','Cargo.lock','Cargo.toml','dependencies.json','release-contract.json','install_runtime.py'):
            files[name]=source/name
        files['dependencies.installed.json']=self.state/'dependencies.json'
        files['voice-assets.json']=self.state/'voice.json'
        contract=json.loads((source/'release-contract.json').read_text())
        if contract.get('desktop'):
            for crate,binary in (('native-shell','agent-os-desktop'),('native-compositor','agent-os-compositor')):
                tree=source/crate if (source/crate).is_dir() else source.parent/crate
                files['native/'+binary]=tree/'target/release'/binary
                for name in ('Cargo.toml','Cargo.lock'):
                    files['native/'+crate+'/'+name]=tree/name
                for pattern in ('licenses/**/*','LICENSE-SMITHAY','THIRD_PARTY.md'):
                    for path in sorted(tree.glob(pattern)):
                        if path.is_file():files['native/'+crate+'/'+str(path.relative_to(tree))]=path
            licenses=source/'third-party-licenses'
            if not (licenses/'dependencies.json').is_file():raise ValueError('Collect dependency license notices before staging the graphical runtime')
            files.update({'third-party-licenses/'+str(p.relative_to(licenses)):p for p in sorted(licenses.rglob('*')) if p.is_file()})

        for name,path in files.items():
            if name.endswith('.py'):ast.parse(path.read_bytes(),filename=name)
        for name in ['agent-os-core',*(['native/agent-os-desktop','native/agent-os-compositor'] if contract.get('desktop') else [])]:
            binary=files[name].read_bytes()
            if binary[:4]!=b'\x7fELF' or len(binary)<20 or binary[4:6]!=b'\x02\x01' or int.from_bytes(binary[18:20],'little')!=183:
                raise ValueError('Build the ARM64 Linux executable before installing: '+name)
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
                mode=0o755 if name in ('agent-os-core','native/agent-os-desktop','native/agent-os-compositor') or name=='client/agent_os.py' or name.endswith('-launcher.sh') else 0o644
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

    def contract(self,release):
        value=json.loads((release/'release-contract.json').read_text())
        if (not isinstance(value,dict) or value.get('format')!=1
                or not isinstance(value.get('state_contract'),str) or not value['state_contract']
                or not isinstance(value.get('units'),list) or 'agent-os-core' not in value['units']
                or any(not isinstance(unit,str) for unit in value['units'])
                or len(set(value['units']))!=len(value['units'])
                or any(unit not in UNITS or not (release/'systemd'/f'{unit}.service').is_file() for unit in value['units'])):
            raise ValueError('Invalid runtime release contract')
        if 'components' in value:
            components=value['components']
            if (not isinstance(components,list) or not components or len(components)>256
                    or any(not isinstance(kind,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*@[1-9][0-9]*',kind) for kind in components)
                    or len(set(components))!=len(components)):
                raise ValueError('Invalid release component capabilities')
        if value.get('desktop') is not None:
            required=('native/agent-os-desktop','native/agent-os-compositor','services/desktop_session.py','services/session-launcher.sh','session/agent-os.desktop','third-party-licenses/dependencies.json')
            if value['desktop']!={'format':1} or any(not (release/name).is_file() for name in required):raise ValueError('Invalid graphical runtime contract')
        return value

    def compatible_components(self,contract):
        # Old releases predate catalog declarations and support only the original
        # vocabulary. A matching SQLite format alone does not make them safe.
        supported=set(contract.get('components',[
            'Stack@1','Row@1','Text@1','Status@1','Button@1','Link@1','TextField@1','Progress@1']))
        path=self.path('/var/lib/agent-os-runtime/state.sqlite3')
        if not path.exists():return
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='presentation_documents'").fetchone():return
            # Stream documents and reject oversized data before transferring it.
            for ident,body in db.execute("SELECT id,CASE WHEN length(CAST(body AS BLOB))<=1048576 THEN body END FROM presentation_documents"):
                if body is None:raise ValueError('Saved document exceeds compatibility read limit: '+ident)
                document=json.loads(body)
                if not isinstance(document,dict):raise ValueError('Invalid saved presentation document')
                elements=document.get('elements',{})
                if not isinstance(elements,dict):raise ValueError('Invalid saved presentation elements')
                for element in elements.values():
                    kind=element.get('type') if isinstance(element,dict) else None
                    if kind not in supported:
                        raise ValueError('Release lacks saved component '+str(kind)+'; an explicit migration is required')

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
        for name,group,home in (('agentos','agentos','runtime'),('agentos-layout','agentos','layout'),('agentos-ai','agentos-ai','ai'),('agentos-voice','agentos','voice')):
            try:pwd.getpwnam(name)
            except KeyError:self.run(['useradd','--system','--gid',group,'--home-dir','/var/lib/agent-os-'+home,'--shell','/usr/sbin/nologin',name])
        self.run(['usermod','-a','-G','agentos,agentos-broker','developer'])
        self.run(['usermod','-a','-G','agentos-broker','agentos-ai'])
        self.path('/var/lib/agent-os-workspaces').mkdir(mode=0o755,exist_ok=True)

    def health(self):
        deadline=time.monotonic()+30
        units=getattr(self,'active_units',UNITS)
        socket_map=dict(zip(UNITS,['/run/agent-os/runtime.sock','/run/agent-os-layout/api.sock','/run/agent-os-disk/api.sock',
                 '/run/agent-os-broker/api.sock','/run/agent-os-ai/api.sock','/run/agent-os-voice/api.sock']))
        sockets=[socket_map[unit] for unit in units]
        while time.monotonic()<deadline:
            states=subprocess.run(['systemctl','is-active',*units],capture_output=True,text=True).stdout.splitlines()
            active=states==['active']*len(units)
            ready=all(p.exists() and stat.S_ISSOCK(p.stat().st_mode) for p in map(self.path,sockets))
            if active and ready:
                # An active PID/socket alone cannot establish core startup/recovery readiness.
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
                    conn.settimeout(3);conn.connect(str(self.path('/run/agent-os/runtime.sock')))
                    conn.sendall(b'{"op":"state.page","collection":"activities","limit":1}\n')
                    with conn.makefile('rb') as stream:result=json.loads(stream.readline(2*1024*1024))
                if result.get('ok'):return
            time.sleep(.2)
        raise RuntimeError('Runtime health checks failed; retain the journal and run recovery after inspecting services')

    def activate(self,ident,interrupt=None):
        if not re.fullmatch('[a-f0-9]{64}',ident):raise ValueError('Invalid staged release ID')
        release=self.root/'releases'/ident;hashes=self.verify(release)
        if hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()!=ident:
            raise ValueError('Release ID does not match its manifest')
        contract=self.contract(release)
        desktop_uid=None
        if contract.get('desktop'):
            desktop_uid=pwd.getpwnam('developer').pw_uid
            if desktop_uid<1000:raise ValueError('The graphical login must use an ordinary user account')
        current=self.root/'current'
        if current.exists() and (current/'release-contract.json').exists():
            live=self.contract(current)
            if live['state_contract']!=contract['state_contract']:
                raise ValueError('Incompatible state contract; an explicit migration is required before activation')
        self.compatible_components(contract)
        prior_journal=self.journal.read_bytes() if self.journal.exists() else None
        previous=str(current.resolve()) if current.exists() else None
        if self.journal.exists():
            prior=json.loads(self.journal.read_text())
            if prior.get('release')==ident and (prior.get('phase')!='complete' or current.resolve()==release.resolve()):
                previous=prior.get('previous')
        transaction={'release':ident,'previous':previous,'phase':'staged','state_contract':contract['state_contract']}
        self.active_units=contract['units']
        self.record(transaction)
        # Recovery remains callable even before the first release is activated.
        atomic_write(self.root/'install-recovery.py',(release/'install_runtime.py').read_bytes())
        self.accounts()
        existing=[name for name in UNITS if self.path('/etc/systemd/system/'+name+'.service').exists()]
        if existing:self.run(['systemctl','stop',*existing])
        try:
            # Recheck after writers stop: a new component may have been saved
            # between the initial preflight and service shutdown.
            self.compatible_components(contract)
        except Exception:
            if prior_journal is None:self.journal.unlink(missing_ok=True)
            else:atomic_write(self.journal,prior_journal,0o600)
            if existing:self.run(['systemctl','start',*existing])
            raise
        transaction['phase']='stopped';self.record(transaction)
        if interrupt=='stopped':os.kill(os.getpid(),signal.SIGKILL)
        self.link(current,release)
        self.link(self.root/'services',current/'services')
        self.link(self.root/'agent-os-core',current/'agent-os-core')
        self.link(self.path('/usr/local/bin/agent-os'),current/'client/agent_os.py')
        for name in ('broker','configure','setup','update'):
            self.link(self.path('/usr/local/bin/agent-os-'+name),current/'services'/f'{name}-launcher.sh')
        desktop=bool(contract.get('desktop'))
        for name,target in [('agent-os-desktop','native/agent-os-desktop'),('agent-os-compositor','native/agent-os-compositor'),('agent-os-session','services/session-launcher.sh')]:
            path=self.path('/usr/local/bin/'+name)
            if desktop:self.link(path,current/target)
            elif path.is_symlink() and str(path.readlink()).startswith(str(self.root)+'/'):path.unlink()
        entry=self.path('/usr/share/wayland-sessions/agent-os.desktop')
        host=self.path('/etc/systemd/system/agent-os-core.service.d/30-compositor.conf')
        if desktop:
            atomic_write(entry,(release/'session/agent-os.desktop').read_bytes())
            atomic_write(host,('[Service]\nEnvironment=AGENT_OS_COMPOSITOR_UID='+str(desktop_uid)+'\n').encode())
        else:
            entry.unlink(missing_ok=True);host.unlink(missing_ok=True)
        for name in set(existing)-set(self.active_units):
            self.run(['systemctl','disable',name])
            self.path('/etc/systemd/system/'+name+'.service').unlink()
        for name in self.active_units:
            atomic_write(self.path('/etc/systemd/system/'+name+'.service'),(release/'systemd'/f'{name}.service').read_bytes())
        transaction['phase']='activated';self.record(transaction)
        if interrupt=='activated':os.kill(os.getpid(),signal.SIGKILL)
        self.run(['systemctl','daemon-reload'])
        self.run(['systemctl','enable','--now',*self.active_units])
        self.health()
        metadata=self.path('/etc/agent-os/release.json')
        info=json.loads(metadata.read_text())
        info.update(version=('0.7.0-dev' if contract.get('desktop') else '0.6.0'),milestone=('Experimental native desktop' if contract.get('desktop') else 'Interactive terminal sessions'),runtime_release=ident,
                    agent_runtime='Gateway agent with general execution and filesystem broker; Jev typed effect advisory',voice='Offline English recognition and reviewed microphone input')
        atomic_write(metadata,(json.dumps(info,indent=2)+'\n').encode())
        message='\nAgent OS '+info['version']+' | '+info['milestone']+'\n\n  agent-os          Open the terminal environment\n  agent-os-status   Inspect the Linux foundation\n  sudo agent-os-configure   Set up providers\n'
        if desktop:message+='  agent-os-session  Start the experimental native desktop from a local login\n'
        atomic_write(self.path('/etc/motd'),(message+'\nOrdinary Linux shell and sudo remain available for recovery.\n\n').encode())
        transaction.update(phase='complete',completed_at=time.time());self.record(transaction)
        atomic_write(self.state/'installed.json',(json.dumps(transaction,indent=2)+'\n').encode(),0o600)
        print('Installed and healthy:',ident)

    def rollback(self,ident=None,interrupt=None):
        current=self.root/'current'
        if not current.exists():raise ValueError('No installed runtime to roll back')
        live=self.contract(current)
        if ident is None:
            installed=json.loads((self.state/'installed.json').read_text())
            previous=installed.get('previous')
            if not previous:raise ValueError('No previous compatible release recorded')
            target=Path(previous)
            if target.parent.resolve()!=(self.root/'releases').resolve():raise ValueError('Invalid previous release path')
            ident=target.name
        if not re.fullmatch('[a-f0-9]{64}',ident):raise ValueError('Invalid rollback release ID')
        release=self.root/'releases'/ident
        self.verify(release)
        if self.contract(release)['state_contract']!=live['state_contract']:
            raise ValueError('Rollback would cross an incompatible state contract; live state was preserved')
        self.activate(ident,interrupt)

    def recover(self):
        if not self.journal.exists():raise ValueError('No installation transaction to recover')
        transaction=json.loads(self.journal.read_text())
        self.activate(transaction['release'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    operation=parser.add_mutually_exclusive_group()
    operation.add_argument('--recover',action='store_true')
    operation.add_argument('--rollback',nargs='?',const='previous',metavar='RELEASE_ID')
    operation.add_argument('--activate',metavar='RELEASE_ID')
    operation.add_argument('--list-releases',action='store_true')
    operation.add_argument('--stage-bundle',type=Path,metavar='BUNDLE',help='Verify a signed bundle and stage it without activating')
    operation.add_argument('--export-bundle',type=Path,metavar='OUTPUT',help='Sign and export an immutable runtime release')
    parser.add_argument('--signing-key',type=Path,help='Ed25519 private PEM key used only for export')
    parser.add_argument('--trusted-key',type=Path,default=Path('/etc/agent-os/update-signing-key.pem'),help='Explicitly provisioned Ed25519 public PEM key')
    parser.add_argument('--release-id',help='Release to export; defaults to the installed current release')
    parser.add_argument('--test-interrupt',choices=['stopped','activated'],help='Development-guest crash injection; terminates installer with SIGKILL')
    args=parser.parse_args()
    if args.export_bundle and not args.signing_key:parser.error('--export-bundle requires --signing-key')
    if args.signing_key and not args.export_bundle:parser.error('--signing-key requires --export-bundle')
    if args.release_id and not args.export_bundle:parser.error('--release-id requires --export-bundle')
    if os.geteuid()!=0:parser.error('Run with sudo')
    installer=Installer();installer.state.mkdir(mode=0o700,parents=True,exist_ok=True);installer.state.chmod(0o700)
    with (installer.state/'lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if args.stage_bundle or args.export_bundle:
            module=SOURCE/'services/release_bundle.py'
            if not module.is_file():module=installer.root/'current/services/release_bundle.py'
            spec=importlib.util.spec_from_file_location('agentos_release_bundle',module)
            bundles=importlib.util.module_from_spec(spec);spec.loader.exec_module(bundles)
            if args.stage_bundle:
                ident=bundles.import_bundle(installer,args.stage_bundle,args.trusted_key)
                print('Verified and staged:',ident)
                print('Activate with: sudo agent-os-update --activate '+ident)
            else:
                ident=args.release_id or (installer.root/'current').resolve().name
                bundles.export(installer,ident,args.signing_key,args.export_bundle)
                print('Signed runtime bundle:',args.export_bundle)
        elif args.list_releases:
            current=(installer.root/'current').resolve()
            releases=[]
            for release in sorted((installer.root/'releases').glob('*')):
                if re.fullmatch('[a-f0-9]{64}',release.name):
                    try:
                        installer.verify(release);contract=installer.contract(release)
                        releases.append(dict(release=release.name,current=release==current,state_contract=contract['state_contract']))
                    except (OSError,ValueError):releases.append(dict(release=release.name,unavailable=True))
            print(json.dumps(releases,indent=2))
        elif args.recover:installer.recover()
        elif args.rollback:installer.rollback(None if args.rollback=='previous' else args.rollback,args.test_interrupt)
        elif args.activate:installer.activate(args.activate,args.test_interrupt)
        else:
            if installer.journal.exists() and json.loads(installer.journal.read_text())['phase']!='complete':
                installer.recover()
            installer.activate(installer.stage(SOURCE),args.test_interrupt)

if __name__=='__main__':main()
