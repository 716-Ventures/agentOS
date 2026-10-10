#!/usr/bin/python3
"""Build hash-pinned offline speech assets once, preserving third-party notices."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from install_runtime import atomic_write

ROOT=Path(__file__).resolve().parent
STATE=Path('/var/lib/agent-os-install')
ASSETS=Path('/usr/local/lib/agent-os/voice')
FLAGS=['-DCMAKE_BUILD_TYPE=Release','-DBUILD_SHARED_LIBS=OFF','-DGGML_NATIVE=OFF',
       '-DGGML_CPU_ARM_ARCH=armv8-a','-DGGML_OPENMP=OFF','-DWHISPER_BUILD_TESTS=OFF',
       '-DWHISPER_BUILD_SERVER=OFF','-DWHISPER_CURL=OFF','-DWHISPER_SDL2=OFF']


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def download(item,path):
    if path.exists() and path.stat().st_size==item['bytes'] and sha(path)==item['sha256']:return
    temporary=path.with_suffix('.download')
    try:
        with urllib.request.urlopen(item['url'],timeout=60) as response,temporary.open('wb') as stream:
            total=0
            while True:
                block=response.read(1024*1024)
                if not block:break
                total+=len(block)
                if total>item['bytes']:raise ValueError('Speech download exceeds pinned size')
                stream.write(block)
            stream.flush();os.fsync(stream.fileno())
        if total!=item['bytes'] or sha(temporary)!=item['sha256']:raise ValueError('Speech asset integrity check failed')
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def verify(folder):
    manifest=json.loads((folder/'manifest.json').read_text())
    for name,expected in manifest['files'].items():
        path=folder/name
        if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()) or sha(path)!=expected:
            raise ValueError('Offline speech asset changed: '+name)
    return manifest


def main():
    if os.geteuid()!=0:raise SystemExit('Run with sudo')
    lock=json.loads((ROOT/'voice-assets.lock.json').read_text())
    recipe={'lock':lock,'flags':FLAGS,'builder_sha256':sha(Path(__file__)),'model_license_sha256':sha(ROOT/'licenses/Whisper-MIT.txt'),'compiler':subprocess.check_output(['c++','--version'],text=True).splitlines()[0]}
    key=hashlib.sha256(json.dumps(recipe,sort_keys=True).encode()).hexdigest()
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True);ASSETS.mkdir(mode=0o755,parents=True,exist_ok=True)
    with (STATE/'voice.lock').open('a+b') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX)
        target=ASSETS/key
        if not target.exists():
            cache=Path('/var/cache/agent-os-voice');cache.mkdir(mode=0o700,parents=True,exist_ok=True)
            source_archive=cache/'whisper.tar.gz';model=cache/'ggml-tiny.en.bin'
            download(lock['engine'],source_archive);download(lock['model'],model)
            with tempfile.TemporaryDirectory(prefix='.build-',dir=ASSETS) as temporary:
                work=Path(temporary);source=work/'source';source.mkdir()
                with tarfile.open(source_archive) as archive:archive.extractall(source,filter='data')
                source=next(source.iterdir());build=work/'build'
                subprocess.run(['cmake','-S',str(source),'-B',str(build),*FLAGS],check=True)
                subprocess.run(['cmake','--build',str(build),'--target','whisper-cli','-j','2'],check=True)
                result=work/'release';result.mkdir(mode=0o755)
                shutil.copyfile(build/'bin/whisper-cli',result/'whisper-cli');(result/'whisper-cli').chmod(0o755)
                shutil.copyfile(model,result/'ggml-tiny.en.bin')
                shutil.copyfile(source/'LICENSE',result/'LICENSE.whisper.cpp')
                shutil.copyfile(ROOT/'licenses/Whisper-MIT.txt',result/'LICENSE.Whisper-model')
                # Upstream's known speech sample provides a real decoder acceptance fixture.
                shutil.copyfile(source/'samples/jfk.wav',result/'sample.wav')
                notice='Offline recognition: whisper.cpp '+lock['engine']['revision']+' (MIT).\nWhisper tiny.en weights from ggerganov/whisper.cpp '+lock['model']['revision']+' (MIT); original OpenAI Whisper weights.\nNo audio is sent to a network service.\n'
                (result/'NOTICE').write_text(notice)
                for file in result.iterdir():
                    if file.name!='whisper-cli':file.chmod(0o644)
                manifest={'recipe':recipe,'files':{p.name:sha(p) for p in sorted(result.iterdir())}}
                atomic_write(result/'manifest.json',(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode())
                verify(result);os.rename(result,target)
                fd=os.open(ASSETS,os.O_RDONLY|os.O_DIRECTORY)
                try:os.fsync(fd)
                finally:os.close(fd)
        manifest=verify(target)
        descriptor={'root':str(target),'manifest_sha256':sha(target/'manifest.json'),
                    'engine':lock['engine'],'model':lock['model'],'files':manifest['files']}
        atomic_write(STATE/'voice.json',(json.dumps(descriptor,sort_keys=True,indent=2)+'\n').encode(),0o600)
        print('Verified offline speech assets:',key)

if __name__=='__main__':main()
