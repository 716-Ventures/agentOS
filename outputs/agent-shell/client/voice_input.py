"""Native client's asynchronous microphone state; no model calls or implicit submission."""
import base64
import json
import os
from pathlib import Path
import socket
import threading
import time
import uuid

SOCKET='/run/agent-os-voice/api.sock'


def request(op, **fields):
    payload=json.dumps({'op':op,**fields}).encode()+b'\n'
    if len(payload)>512*1024:raise ValueError('Voice request exceeds transport limit')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
        conn.settimeout(50);conn.connect(SOCKET);conn.sendall(payload)
        with conn.makefile('rb') as stream:
            line=stream.readline(512*1024+1)
            if len(line)>512*1024 or not line.endswith(b'\n'):raise ValueError('Invalid voice response')
            result=json.loads(line)
    if not result['ok']:raise RuntimeError(result['error'])
    return result['result']


def from_file(path):
    with Path(path).open('rb') as stream:raw=stream.read(324097)
    if len(raw)>324096:raise ValueError('Use a 16 kHz mono 16-bit WAV of at most ten seconds')
    try:return request('transcribe',wav_base64=base64.b64encode(raw).decode())
    except BaseException:
        try:request('cancel')
        except (OSError,RuntimeError,ValueError):pass
        raise


class VoiceInput:
    def __init__(self):
        self.lock=threading.Lock();self.state='idle';self.result=None;self.error=None
        self.context=None;self.token=None;self.epoch=0;self.started=0

    def snapshot(self):
        with self.lock:return {'state':self.state,'context':self.context,'result':self.result,'error':self.error,'started':self.started}

    def start(self,context):
        with self.lock:
            if self.state!='idle':raise ValueError('Finish or cancel the current recording first')
            self.epoch+=1;epoch=self.epoch;self.context={**context,'input_id':uuid.uuid4().hex,'captured_at':time.time(),'modality':'voice'}
            self.state='starting';self.result=None;self.error=None;self.started=time.monotonic()
        def begin():
            try:
                result=request('capture.start')
                with self.lock:
                    if epoch==self.epoch:self.token=result['token'];self.state='recording';return
                request('cancel',token=result['token'])
            except (OSError,RuntimeError,ValueError) as exc:self.fail(epoch,exc)
        threading.Thread(target=begin,daemon=True).start()

    def fail(self,epoch,exc):
        with self.lock:
            if epoch==self.epoch:self.error=str(exc);self.state='error'

    def finish(self):
        with self.lock:
            if self.state!='recording':return
            self.state='transcribing';epoch=self.epoch;token=self.token
        def decode():
            try:
                result=request('capture.finish',token=token)
                with self.lock:
                    if epoch==self.epoch:self.result=result;self.state='review'
            except (OSError,RuntimeError,ValueError) as exc:self.fail(epoch,exc)
        threading.Thread(target=decode,daemon=True).start()

    def consume(self):
        with self.lock:
            result={'state':self.state,'context':self.context,'result':self.result,'error':self.error}
            self.state='idle';self.result=None;self.error=None;self.token=None
            return result

    def cancel(self):
        with self.lock:
            self.epoch+=1;was_active=self.state!='idle';token=self.token;self.state='idle';self.result=None;self.error=None;self.token=None
        if was_active:
            try:request('cancel',**({'token':token} if token is not None else {}))
            except (OSError,RuntimeError,ValueError):pass
