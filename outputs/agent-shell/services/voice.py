#!/usr/bin/python3
"""Local bounded speech recognition; capture requires authenticated native input."""
import base64
import binascii
import hashlib
import io
import json
import math
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from common import listen, read_line, send

SOCKET='/run/agent-os-voice/api.sock'
RATE=16000
MAX_SECONDS=10
MAX_BYTES=RATE*2*MAX_SECONDS
ASSETS=Path('/usr/local/lib/agent-os/current/voice-assets.json')


def pcm_from_wav(raw):
    if len(raw)>MAX_BYTES+4096:raise ValueError('Audio exceeds ten seconds')
    try:
        with wave.open(io.BytesIO(raw),'rb') as source:
            if source.getparams()[:3]!=(1,2,RATE) or source.getcomptype()!='NONE':
                raise ValueError('Use 16 kHz mono 16-bit PCM WAV audio')
            count=source.getnframes()
            if not RATE//4<=count<=RATE*MAX_SECONDS:raise ValueError('Use between 0.25 and 10 seconds of audio')
            pcm=source.readframes(count)
            if len(pcm)!=count*2:raise ValueError('Incomplete WAV audio')
            return pcm
    except (wave.Error,EOFError) as exc:raise ValueError('Invalid WAV audio') from exc


def level(pcm):
    if len(pcm)%2:pcm=pcm[:-1]
    if not pcm:return 0.0
    samples=struct.unpack('<'+'h'*(len(pcm)//2),pcm)
    return math.sqrt(sum(float(s)*s for s in samples)/len(samples))/32768


def wave_file(path,pcm):
    with wave.open(str(path),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(RATE);output.writeframes(pcm)


def verify_assets(descriptor):
    root=Path(descriptor['root'])
    if not root.is_absolute() or root.is_symlink():raise ValueError('Invalid speech asset location')
    if hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()!=descriptor['manifest_sha256']:raise ValueError('Speech manifest integrity check failed')
    if not {'whisper-cli','ggml-tiny.en.bin','LICENSE.whisper.cpp','LICENSE.Whisper-model'}.issubset(descriptor['files']):raise ValueError('Incomplete speech assets')
    for name,expected in descriptor['files'].items():
        file=root/name
        if file.is_symlink() or not file.resolve().is_relative_to(root.resolve()):raise ValueError('Invalid speech asset path')
        digest=hashlib.sha256()
        with file.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        if digest.hexdigest()!=expected:raise ValueError('Speech asset integrity check failed')
    return root


class Voice:
    def __init__(self,descriptor):
        self.assets=verify_assets(descriptor)
        self.lock=threading.RLock();self.capture=None;self.decoder=None;self.decoder_owner=None;self.decoder_token=None;self.pending=None;self.generations={}
        self.busy=threading.Lock()

    def owner(self,conn):
        pid,uid,gid=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        start=Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split()[19]
        return uid,str(pid)+':'+start

    def human(self,owner):
        if owner[0]!=0 and owner[0]<1000:raise ValueError('Microphone capture requires direct native user input')

    def stop_process(self,proc):
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:proc.wait(timeout=2)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=2)

    def discard(self):
        with self.lock:
            capture=self.capture;self.capture=None
            if capture:
                self.stop_process(capture['process']);capture['temporary'].cleanup()

    def owner_alive(self,owner):
        try:
            pid,start=owner[1].split(':',1)
            return Path('/proc/'+pid+'/stat').read_text().rsplit(')',1)[1].split()[19]==start
        except (OSError,ValueError,IndexError):return False

    def reap(self):
        while True:
            time.sleep(.5)
            with self.lock:
                if self.capture and (time.monotonic()-self.capture['started']>30 or not self.owner_alive(self.capture['owner'])):self.discard()
                if self.decoder and not self.owner_alive(self.decoder_owner):self.stop_process(self.decoder)

    def transcribe(self,pcm,owner,epoch=None,token=None):
        if not RATE//2<=len(pcm)<=MAX_BYTES or len(pcm)%2:raise ValueError('Use between 0.25 and 10 seconds of audio')
        rms=level(pcm)
        if rms<.002:return {'text':'','status':'no_signal','rms':rms,'duration_seconds':len(pcm)/(RATE*2)}
        if not self.busy.acquire(blocking=False):raise ValueError('Speech recognition is busy; try again shortly')
        started=time.monotonic()
        with self.lock:
            if epoch is None:epoch=self.generations.get(owner,0)
        try:
            with tempfile.TemporaryDirectory(prefix='agentos-speech-') as tmp:
                root=Path(tmp);audio=root/'audio.wav';wave_file(audio,pcm)
                with (root/'decoder.log').open('w+b') as log:
                    argv=[str(self.assets/'whisper-cli'),'-m',str(self.assets/'ggml-tiny.en.bin'),'-f',str(audio),'-l','en','-ng','-nt','-np','-otxt','-of',str(root/'transcript'),'-t','2']
                    with self.lock:
                        if epoch!=self.generations.get(owner,0):raise ValueError('Speech input was cancelled')
                        proc=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=log,stderr=log,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
                        self.decoder=proc;self.decoder_owner=owner;self.decoder_token=token;self.pending=None
                    try:
                        try:code=proc.wait(timeout=45)
                        except subprocess.TimeoutExpired:self.stop_process(proc);raise ValueError('Speech recognition timed out; audio was discarded')
                        if code:raise ValueError('Speech recognition failed or was cancelled; audio was discarded')
                        path=root/'transcript.txt'
                        if path.stat().st_size>16384:raise ValueError('Speech transcript exceeds its limit')
                        text=path.read_text().strip()
                        text=' '.join(''.join(c for c in text if c in '\n\t' or ord(c)>=32).split())
                        return {'text':text[:4000],'status':'transcribed' if text else 'no_speech','rms':rms,
                                'duration_seconds':len(pcm)/(RATE*2),'recognition_seconds':time.monotonic()-started,'engine':'whisper.cpp/1.9.5 tiny.en','requires_review':True}
                    finally:
                        with self.lock:self.decoder=None;self.decoder_owner=None;self.decoder_token=None
        finally:
            with self.lock:
                if self.pending and self.pending[0]==owner:self.pending=None
            self.busy.release()

    def handle(self,request,owner):
        op=request.get('op')
        if op=='status':
            with self.lock:
                capture=self.capture
                return {'state':'transcribing' if self.decoder else 'recording' if capture and capture['process'].poll() is None else 'recorded' if capture else 'idle',
                        'maximum_seconds':MAX_SECONDS,'offline':True,'language':'en'}
        if op=='transcribe':
            self.human(owner)
            try:raw=base64.b64decode(request.get('wav_base64',''),validate=True)
            except (binascii.Error,ValueError,TypeError) as exc:raise ValueError('Invalid audio encoding') from exc
            return self.transcribe(pcm_from_wav(raw),owner)
        if op=='capture.start':
            self.human(owner)
            with self.lock:
                if self.capture or self.decoder or self.pending:raise ValueError('Microphone or recognizer is already in use')
                tmp=tempfile.TemporaryDirectory(prefix='agentos-microphone-');path=Path(tmp.name)/'capture.pcm'
                try:proc=subprocess.Popen(['/usr/bin/arecord','--quiet','-t','raw','-f','S16_LE','-c','1','-r',str(RATE),'-d',str(MAX_SECONDS),str(path)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                except BaseException:tmp.cleanup();raise
                token=uuid.uuid4().hex;self.capture={'temporary':tmp,'path':path,'process':proc,'owner':owner,'token':token,'started':time.monotonic()}
                return {'token':token,'state':'recording','maximum_seconds':MAX_SECONDS}
        if op=='cancel':
            with self.lock:
                token=request.get('token')
                capture_match=self.capture and self.capture['owner']==owner and (token is None or token==self.capture['token'])
                decoder_match=self.decoder and self.decoder_owner==owner and (token is None or token==self.decoder_token)
                pending_match=self.pending and self.pending[0]==owner and (token is None or token==self.pending[1])
                if capture_match or decoder_match or pending_match:
                    self.generations[owner]=self.generations.get(owner,0)+1
                    if capture_match:self.discard()
                    if decoder_match:self.stop_process(self.decoder)
            return {'state':'idle'}
        if op=='capture.finish':
            self.human(owner)
            with self.lock:
                capture=self.capture
                if not capture or capture['owner']!=owner or request.get('token')!=capture['token']:raise ValueError('Microphone session is absent or belongs to another input process')
                self.stop_process(capture['process'])
                try:pcm=capture['path'].read_bytes()[:MAX_BYTES]
                except OSError:pcm=b''
                epoch=self.generations.get(owner,0);token=capture['token']
                self.pending=(owner,token)
                self.discard()
            try:return self.transcribe(pcm,owner,epoch=epoch,token=token)
            finally:
                with self.lock:
                    if self.pending==(owner,token):self.pending=None
        raise ValueError('Unsupported voice operation')


def main():
    service=Voice(json.loads(ASSETS.read_text()))
    threading.Thread(target=service.reap,daemon=True).start()
    server=listen(SOCKET)
    # Bound connection workers independently of inference/capture duration.
    workers=threading.BoundedSemaphore(8)
    def serve(conn):
        try:
            with conn:
                conn.settimeout(50)
                try:
                    owner=service.owner(conn)
                    with conn.makefile('rb') as stream:request=read_line(stream)
                    send(conn,{'ok':True,'result':service.handle(request,owner)})
                except (OSError,ValueError,KeyError,subprocess.SubprocessError) as exc:
                    try:send(conn,{'ok':False,'error':str(exc)[:500]})
                    except OSError:pass
        finally:workers.release()
    try:
        while True:
            conn,_=server.accept()
            if not workers.acquire(blocking=False):conn.close();continue
            threading.Thread(target=serve,args=(conn,),daemon=True).start()
    finally:service.discard();server.close()

if __name__=='__main__':main()
