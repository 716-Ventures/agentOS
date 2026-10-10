"""Coalesced broker observations; authoritative outcomes remain in broker storage."""
import json
import os
import re
import socket
import threading
import time


class BrokerSources:
    def __init__(self,endpoint=None):
        self.endpoint=endpoint or os.environ.get('AGENT_OS_SOCKET','/run/agent-os/runtime.sock')
        self.pending={};self.lock=threading.Lock();self.stop=threading.Event();self.worker=None
    def mark(self,job):
        if not re.fullmatch('[0-9a-f]{32}',str(job.get('id',''))) or type(job.get('activity')) is not int:return
        error=job.get('error')
        if isinstance(error,str) and len(error.encode())>16000:error=error.encode()[:15900].decode(errors='ignore')+' [truncated]'
        payload={'op':'source.publish','source':'broker:'+job['id'],'activity_id':str(job['activity']),'source_revision':job.get('source_revision',0),
                 'values':{'status':job['status'],'exit_code':job.get('exit_code'),'error':error,'created_at':job.get('created_at'),'finished_at':job.get('finished_at')}}
        with self.lock:
            if len(self.pending)>=1024 and payload['source'] not in self.pending:self.pending.pop(next(iter(self.pending)))
            self.pending[payload['source']]=payload
    def request(self,value):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.settimeout(.3);conn.connect(self.endpoint);conn.sendall(json.dumps(value,separators=(',',':')).encode()+b'\n')
            with conn.makefile('rb') as stream:response=json.loads(stream.readline(65537))
            if not response.get('ok'):raise RuntimeError(response.get('error','Source publication failed'))
    def start(self):
        if self.worker is not None:return
        self.worker=threading.Thread(target=self.run,name='broker-source-observations',daemon=True);self.worker.start()
    def run(self):
        heartbeat=0
        while not self.stop.is_set():
            with self.lock:batch=list(self.pending.items())[:16]
            for source,payload in batch:
                if self.stop.is_set():break
                try:self.request(payload)
                except (OSError,RuntimeError,ValueError):break
                with self.lock:
                    if self.pending.get(source)==payload:self.pending.pop(source,None)
            with self.lock:pending=bool(self.pending)
            if not pending and time.monotonic()-heartbeat>=5:
                try:self.request({'op':'source.heartbeat'});heartbeat=time.monotonic()
                except (OSError,RuntimeError,ValueError):pass
            self.stop.wait(.25 if batch else .5)
    def close(self):
        self.stop.set()
        if self.worker:self.worker.join(timeout=2)
