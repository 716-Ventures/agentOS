"""Coalesced broker observations; authoritative outcomes remain in broker storage."""
import json
import os
import re
import socket
import threading
import time


class BrokerSources:
    def __init__(self,endpoint=None,replay=None):
        self.endpoint=endpoint or os.environ.get('AGENT_OS_SOCKET','/run/agent-os/runtime.sock')
        self.replay=replay;self.needs_replay=False
        self.pending={};self.lock=threading.Lock();self.stop=threading.Event();self.worker=None
    @staticmethod
    def job_payload(job):
        if not re.fullmatch('[0-9a-f]{32}',str(job.get('id',''))) or type(job.get('activity')) is not int:return
        error=job.get('error')
        if isinstance(error,str) and len(error.encode())>16000:error=error.encode()[:15900].decode(errors='ignore')+' [truncated]'
        payload={'op':'source.publish','source':'broker:'+job['id'],'activity_id':str(job['activity']),'source_revision':job.get('source_revision',0),
                 'values':{'status':job['status'],'exit_code':job.get('exit_code'),'error':error,'created_at':job.get('created_at'),'finished_at':job.get('finished_at')}}
        return payload
    def mark(self,job):
        payload=self.job_payload(job)
        if payload:self.enqueue(payload)
    @staticmethod
    def file_payload(record):
        from file_observations import record_valid
        if not record_valid(record):return
        return {'op':'source.publish','source':record['source'],'activity_id':str(record['activity']),
                'source_revision':record['source_revision'],'values':dict(record['values'])}
    def mark_file(self,record):
        payload=self.file_payload(record)
        if payload:self.enqueue(payload)
    def enqueue(self,payload):
        with self.lock:
            if len(self.pending)>=1024 and payload['source'] not in self.pending:
                self.pending.pop(next(iter(self.pending)));self.needs_replay=True
            self.pending[payload['source']]=payload
    def request(self,value):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.settimeout(.3);conn.connect(self.endpoint);conn.sendall(json.dumps(value,separators=(',',':')).encode()+b'\n')
            with conn.makefile('rb') as stream:response=json.loads(stream.readline(65537))
            if not response.get('ok'):
                error=response.get('error','Source publication failed')
                # A replay can encounter a newer observation already delivered by the live queue.
                try:obsolete=json.loads(error).get('code')=='stale_revision'
                except (TypeError,ValueError,AttributeError):obsolete=False
                if not obsolete:raise RuntimeError(error)
    def start(self):
        if self.worker is not None:return
        self.worker=threading.Thread(target=self.run,name='broker-source-observations',daemon=True);self.worker.start()
    def run(self):
        heartbeat=0;replaying=None
        while not self.stop.is_set():
            with self.lock:batch=list(self.pending.items())[:16]
            for source,payload in batch:
                if self.stop.is_set():break
                try:self.request(payload)
                except (OSError,RuntimeError,ValueError):break
                with self.lock:
                    if self.pending.get(source)==payload:self.pending.pop(source,None)
            with self.lock:
                if replaying is None and self.needs_replay and self.replay:
                    replaying=iter(self.replay());self.needs_replay=False
            if replaying is not None and not self.stop.is_set():
                for _ in range(16):
                    try:payload=next(replaying)
                    except StopIteration:replaying=None;break
                    if self.stop.is_set():break
                    try:self.request(payload)
                    except (OSError,RuntimeError,ValueError):
                        replaying=None
                        with self.lock:self.needs_replay=True
                        break
            with self.lock:pending=bool(self.pending) or replaying is not None or (self.needs_replay and self.replay is not None)
            if not pending and time.monotonic()-heartbeat>=5:
                try:self.request({'op':'source.heartbeat'});heartbeat=time.monotonic()
                except (OSError,RuntimeError,ValueError):pass
            self.stop.wait(.25 if batch else .5)
    def close(self):
        self.stop.set()
        if self.worker:self.worker.join(timeout=2)
