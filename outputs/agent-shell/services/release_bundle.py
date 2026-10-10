"""Signed, bounded runtime bundles; user state and signing keys are never packaged."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request

OPENSSL='/usr/bin/openssl'
MAX_FILE=128*1024*1024
MAX_TOTAL=512*1024*1024
MAX_FILES=10000
MAX_DOWNLOAD=MAX_TOTAL+16*1024*1024


def download_url(value):
    if not isinstance(value,str) or len(value)>4096 or any(ord(char)<33 for char in value):
        raise ValueError('Use an HTTPS runtime bundle URL')
    parsed=urllib.parse.urlsplit(value)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError('Runtime downloads require HTTPS without URL credentials or fragments')
    return value


class SecureRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections=5
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        download_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch_bundle(installer,url,trusted_key):
    """Download into private temporary storage, verify, and stage; never activate."""
    download_url(url);key_type(Path(trusted_key),True)
    installer.state.mkdir(mode=0o700,parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.download-',dir=installer.state) as directory:
        path=Path(directory)/'runtime.tar.gz';deadline=time.monotonic()+120
        opener=urllib.request.build_opener(SecureRedirect())
        request=urllib.request.Request(url,headers={'User-Agent':'agentOS-runtime-update/1','Accept-Encoding':'identity'})
        with opener.open(request,timeout=15) as response,path.open('xb') as stream:
            path.chmod(0o600)
            length=response.headers.get('Content-Length')
            if length is not None and (not length.isdecimal() or int(length)>MAX_DOWNLOAD):
                raise ValueError('Runtime download exceeds its size limit')
            total=0
            while True:
                if time.monotonic()>deadline:raise ValueError('Runtime download exceeded its time limit')
                data=response.read(min(1024*1024,MAX_DOWNLOAD-total+1))
                if not data:break
                total+=len(data)
                if total>MAX_DOWNLOAD:raise ValueError('Runtime download exceeds its size limit')
                stream.write(data)
            stream.flush();os.fsync(stream.fileno())
        return import_bundle(installer,path,trusted_key)


def sha(data):return hashlib.sha256(data).hexdigest()
def canonical(value):return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
def path_name(name):
    if (not isinstance(name,str) or not name or len(name)>1024 or '\\' in name or any(ord(c)<32 for c in name)
            or PurePosixPath(name).is_absolute() or any(p in ('','..','.') for p in name.split('/'))):raise ValueError('Invalid runtime payload path')
    return name


def crypto(arguments):
    try:result=subprocess.run([OPENSSL,*arguments],stdin=subprocess.DEVNULL,capture_output=True,timeout=10)
    except (OSError,subprocess.TimeoutExpired) as exc:raise ValueError('OpenSSL 3 or later is required for runtime signatures') from exc
    if result.returncode:raise ValueError('Runtime signing key or signature verification failed')
    return result.stdout


def key_type(key,public):
    der=crypto(['pkey',*(['-pubin'] if public else []),'-in',str(key),'-pubout','-outform','DER'])
    if len(der)!=44 or not der.startswith(bytes.fromhex('302a300506032b6570032100')):raise ValueError('Runtime signing keys must use Ed25519')


def mode(name):return 0o755 if name in ('agent-os-core','native/agent-os-desktop','native/agent-os-compositor','client/agent_os.py') or name.endswith('-launcher.sh') else 0o644


def export(installer,release_id,key,output):
    if not re.fullmatch('[a-f0-9]{64}',release_id):raise ValueError('Invalid runtime release ID')
    release=installer.root/'releases'/release_id;hashes=installer.verify(release);contract=installer.contract(release)
    if sha(json.dumps(hashes,sort_keys=True).encode())!=release_id:raise ValueError('Runtime release identity mismatch')
    output=Path(output);key=Path(key)
    if output.exists() or output.resolve()==key.resolve() or output.resolve().is_relative_to(release.resolve()):raise ValueError('Choose a new bundle path outside the immutable release')
    if len(hashes)>MAX_FILES:raise ValueError('Runtime has too many payload files')
    total=0
    for name in hashes:
        path_name(name);path=release/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_FILE:raise ValueError('Invalid runtime payload file')
        total+=path.stat().st_size
    if total>MAX_TOTAL:raise ValueError('Runtime payload exceeds its size limit')
    key_type(key,False)
    manifest=(release/'manifest.json').read_bytes()
    if len(manifest)>2*1024*1024:raise ValueError('Runtime manifest exceeds its size limit')
    envelope=canonical({'format':'agentos.release/1','architecture':'aarch64','signature_algorithm':'Ed25519','release':release_id,'state_contract':contract['state_contract'],'manifest_sha256':sha(manifest)})
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.runtime-bundle-',dir=output.parent)
    try:
        with tempfile.TemporaryDirectory(prefix='agentos-sign-') as directory:
            root=Path(directory);message=root/'envelope';signature=root/'signature';message.write_bytes(envelope)
            crypto(['pkeyutl','-sign','-rawin','-inkey',str(key),'-in',str(message),'-out',str(signature)])
            signed=signature.read_bytes()
            if len(signed)!=64:raise ValueError('Invalid Ed25519 signature size')
            with os.fdopen(fd,'wb') as stream:
                os.fchmod(stream.fileno(),0o644)
                with gzip.GzipFile(filename='',mode='wb',fileobj=stream,mtime=0) as zipped,tarfile.open(fileobj=zipped,mode='w|',format=tarfile.PAX_FORMAT) as archive:
                    def add(name,data,permissions=0o644):
                        info=tarfile.TarInfo(name);info.size=len(data);info.mode=permissions;info.mtime=0;archive.addfile(info,io.BytesIO(data))
                    add('envelope.json',envelope);add('envelope.sig',signed);add('release/manifest.json',manifest)
                    for name in sorted(hashes):add('release/'+name,(release/name).read_bytes(),mode(name))
                stream.flush();os.fsync(stream.fileno())
        os.link(temporary,output)
        parent=os.open(output.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(parent)
        finally:os.close(parent)
    finally:
        try:os.close(fd)
        except OSError:pass
        Path(temporary).unlink(missing_ok=True)
    return release_id


def installed_packages():
    rows=subprocess.check_output(['/usr/bin/dpkg-query','-W','-f=${binary:Package}\t${Version}\t${db:Status-Status}\n'],text=True)
    return {name:version for name,version,status in (row.split('\t') for row in rows.splitlines()) if status=='installed'}


def validate_host(installer,release):
    if platform.system()!='Linux' or platform.machine() not in ('aarch64','arm64'):raise ValueError('Runtime updates require ARM64 Linux')
    profile_bytes=(release/'dependencies.json').read_bytes();profile=json.loads(profile_bytes)
    recorded=json.loads((release/'dependencies.installed.json').read_text())
    if recorded.get('profile_sha256')!=sha(profile_bytes) or not isinstance(profile.get('packages'),list):raise ValueError('Runtime dependency record does not match its profile')
    actual=installed_packages()
    for package in profile['packages']:
        expected={name:version for name,version in recorded.get('packages',{}).items() if name.split(':')[0]==package}
        if not expected or any(actual.get(name)!=version for name,version in expected.items()):raise ValueError('Install the recorded runtime dependency before updating: '+str(package))
    if json.loads((release/'voice-assets.json').read_text())!=json.loads((installer.state/'voice.json').read_text()):raise ValueError('Install the matching voice assets before updating this runtime')


class BoundedArchive:
    """Limit decompressed bytes, including tar headers and PAX metadata."""
    def __init__(self,source):
        self.source=source;self.remaining=MAX_TOTAL+4*1024*1024+MAX_FILES*2048
    def read(self,size=-1):
        size=self.remaining+1 if size<0 else min(size,self.remaining+1)
        data=self.source.read(size);self.remaining-=len(data)
        if self.remaining<0:raise ValueError('Runtime archive exceeds its decompressed size limit')
        return data


def import_bundle(installer,bundle,trusted_key):
    bundle=Path(bundle)
    if bundle.stat().st_size>MAX_TOTAL:raise ValueError('Runtime bundle exceeds its size limit')
    key_type(trusted_key,True)
    releases=installer.root/'releases';releases.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.bundle-',dir=releases) as directory:
        root=Path(directory);staged=root/'payload';staged.mkdir(mode=0o755)
        try:
            with gzip.open(bundle,'rb') as zipped,tarfile.open(fileobj=BoundedArchive(zipped),mode='r|') as archive:
                def read(name,limit):
                    member=archive.next()
                    if member is None or member.name!=name or not member.isreg() or not 0<=member.size<=limit:raise ValueError('Invalid runtime bundle structure')
                    return archive.extractfile(member).read(limit+1)
                envelope=read('envelope.json',65536);signature=read('envelope.sig',64)
                if len(signature)!=64:raise ValueError('Invalid signature size')
                (root/'envelope').write_bytes(envelope);(root/'signature').write_bytes(signature)
                crypto(['pkeyutl','-verify','-rawin','-pubin','-inkey',str(trusted_key),'-in',str(root/'envelope'),'-sigfile',str(root/'signature')])
                value=json.loads(envelope)
                if (set(value)!=set(('format','architecture','signature_algorithm','release','state_contract','manifest_sha256')) or value['format']!='agentos.release/1' or value['signature_algorithm']!='Ed25519' or value['architecture']!='aarch64' or not isinstance(value['release'],str) or not re.fullmatch('[a-f0-9]{64}',value['release'])):raise ValueError('Unsupported signed runtime envelope')
                manifest=read('release/manifest.json',2*1024*1024)
                if sha(manifest)!=value['manifest_sha256']:raise ValueError('Signed runtime manifest changed')
                hashes=json.loads(manifest)
                if not isinstance(hashes,dict) or not 1<=len(hashes)<=MAX_FILES or sha(json.dumps(hashes,sort_keys=True).encode())!=value['release']:raise ValueError('Invalid signed runtime identity')
                for name,digest in hashes.items():
                    path_name(name)
                    if name=='manifest.json' or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('Invalid content manifest')
                (staged/'manifest.json').write_bytes(manifest);seen=set();total=0
                while (member:=archive.next()) is not None:
                    if not member.name.startswith('release/') or not member.isreg():raise ValueError('Runtime bundles contain only regular payload files')
                    name=path_name(member.name[len('release/'):])
                    if name not in hashes or name in seen or not 0<=member.size<=MAX_FILE:raise ValueError('Unexpected or duplicate runtime payload')
                    seen.add(name);total+=member.size
                    if total>MAX_TOTAL:raise ValueError('Runtime payload exceeds its size limit')
                    path=staged/name;path.parent.mkdir(parents=True,exist_ok=True);digest=hashlib.sha256()
                    with path.open('xb') as stream:
                        source=archive.extractfile(member)
                        while True:
                            chunk=source.read(1024*1024)
                            if not chunk:break
                            digest.update(chunk);stream.write(chunk)
                        os.fchmod(stream.fileno(),mode(name));stream.flush();os.fsync(stream.fileno())
                    if digest.hexdigest()!=hashes[name]:raise ValueError('Runtime payload integrity failure: '+name)
                if seen!=set(hashes):raise ValueError('Runtime bundle is incomplete')
        except (tarfile.TarError,EOFError) as exc:raise ValueError('Invalid runtime archive') from exc
        installer.verify(staged);contract=installer.contract(staged)
        if contract['state_contract']!=value['state_contract']:raise ValueError('Signed state contract mismatch')
        for name in ['agent-os-core',*(['native/agent-os-desktop','native/agent-os-compositor'] if contract.get('desktop') else [])]:
            with (staged/name).open('rb') as stream:header=stream.read(20)
            if len(header)<20 or header[:6]!=b'\x7fELF\x02\x01' or int.from_bytes(header[18:20],'little')!=183:raise ValueError('Runtime executable is not ARM64 Linux')
        validate_host(installer,staged)
        current=installer.root/'current'
        if current.exists() and installer.contract(current)['state_contract']!=contract['state_contract']:
            raise ValueError('Incompatible state contract; an explicit migration is required before updating')
        with (staged/'manifest.json').open('rb') as stream:os.fsync(stream.fileno())
        for parent in sorted([staged,*[p for p in staged.rglob('*') if p.is_dir()]],key=lambda p:len(p.parts),reverse=True):
            fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
        target=releases/value['release']
        if target.exists():installer.verify(target)
        else:
            os.rename(staged,target)
            parent=os.open(releases,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(parent)
            finally:os.close(parent)
        return value['release']
