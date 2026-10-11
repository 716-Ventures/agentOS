#!/usr/bin/python3
"""Real Wayland receipts from virtual KMS; this client is not native GTK latency evidence."""
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import uuid


def verify(env, metrics, core, scene, login_user, presentation, keyboard):
    endpoint=metrics/'presentation-test.sock'
    binary=Path(__file__).resolve().parents[1]/'native-compositor/target/debug/examples/presentation_fixture'
    log_path=metrics/'presentation-client.log'
    client=None
    def wait(predicate, meaning, seconds=10):
        deadline=time.monotonic()+seconds
        while True:
            if client.poll() is not None:raise RuntimeError('Presentation fixture exited: '+log_path.read_text()[-4096:])
            result=predicate()
            if result:return result
            if time.monotonic()>deadline:raise RuntimeError(meaning)
            time.sleep(.02)
    def method(op):
        with socket.socket(socket.AF_UNIX) as conn:
            conn.settimeout(3);conn.connect(str(endpoint));conn.sendall(json.dumps({'op':op}).encode()+b'\n')
            with conn.makefile('rb') as reader:line=reader.readline(65537)
        if len(line)>65536 or not line.endswith(b'\n'):raise RuntimeError('Invalid presentation fixture response size')
        result=json.loads(line)
        assert result['ok'],result
        return result
    def receipt(ident, kind):return next((r for r in method('status')['receipts'] if r['id']==ident and r['kind']==kind),None)
    with log_path.open('w') as log:
        client=subprocess.Popen(['runuser','-u',login_user,'--',str(binary),str(endpoint)],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            wait(endpoint.exists,'Presentation fixture did not start')
            initial=method('status');assert initial['clock_id']==time.CLOCK_MONOTONIC,initial
            deadline=time.monotonic()+.5
            while time.monotonic()<deadline:
                assert not method('status')['receipts'],'Unbuffered content received a presentation receipt'
                time.sleep(.02)
            before=scene()['direct_frames_presented']
            mapped=method('map')['id']
            def window():
                observed=scene()
                return next((row for row in observed['windows'] if row['app_id']=='com.agentos.PresentationFixture' and row['id'] in observed['shared']['identities']),None)
            target=wait(window,'Presentation client did not join the shared workspace')
            activity=core('presentation.get')['activity_id']
            deadline=time.monotonic()+8
            while True:
                observed=scene();logical=observed['shared']['identities'][target['id']]
                workspace=next(w for w in observed['shared']['workspaces'].values() if w['activity_id']==activity)
                try:
                    presentation({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'presentation-focus-'+uuid.uuid4().hex,'expected_revisions':{workspace['workspace_id']:workspace['revision']},'operations':[{'op':'workspace.edit','workspace_id':workspace['workspace_id'],'edit':{'kind':'maximize','surface_id':logical}},{'op':'workspace.edit','workspace_id':workspace['workspace_id'],'edit':{'kind':'focus','surface_id':logical,'element_id':None}}]})
                    break
                except RuntimeError as exc:
                    if '"code":"stale_revision"' not in str(exc) or time.monotonic()>deadline:raise
                    time.sleep(.02)
            wait(lambda:scene()['seat_focus']==target['id'],'Presentation client did not receive keyboard focus')
            first=wait(lambda:receipt(mapped,'presented'),'Mapped frame was not presented')
            wait(lambda:receipt(1,'discarded'),'Superseded unbuffered commit was not discarded')
            assert first['flags']&1 and first['refresh_ns']>0,first
            assert scene()['direct_frames_presented']>before,'Receipt preceded all completed KMS frames'
            assert abs(time.monotonic_ns()-first['time_ns'])<2_000_000_000,first
            latencies=[]
            for _ in range(20):
                previous=max(r['id'] for r in method('status')['receipts'])
                keyboard.chord(30)
                event=wait(lambda:next((r for r in method('status')['receipts'] if r['id']>previous and r['kind']=='presented' and r['key_time_ms'] is not None),None),'Key-triggered buffer did not receive presentation feedback')
                # Wayland key time wraps at 32 bits. Both clocks are the guest
                # CLOCK_MONOTONIC; millisecond quantization overestimates by <1ms.
                latency=((event['time_ns']//1_000_000)-event['key_time_ms'])&0xffffffff
                assert latency<2000,event
                latencies.append(latency)
            last=method('supersede')['id']
            wait(lambda:receipt(last-1,'discarded'),'Unseen superseded content was reported as presented')
            wait(lambda:receipt(last,'presented'),'Replacement content was not presented')
            method('unmap')
            wait(lambda:target['id'] not in scene()['shared']['identities'],'Unmapped content stayed published')
            result={'meaning':'Synthetic Wayland client kernel-event to virtual KMS presentation receipt; not native GTK or physical display latency','samples':len(latencies),'p50_ms':sorted(latencies)[math.ceil(.5*len(latencies))-1],'p95_ms':sorted(latencies)[math.ceil(.95*len(latencies))-1],'max_ms':max(latencies),'clock':'CLOCK_MONOTONIC','timestamp_quantization_ms':1,'target_ms':50,'target_met':sorted(latencies)[math.ceil(.95*len(latencies))-1]<=50}
            print('Presentation receipt measurement:',json.dumps(result),flush=True)
            print('PASS: actual virtual KMS presentation receipts, monotonic timestamps, kernel key-triggered frames, superseded discard and unmap',flush=True)
        finally:
            if client.poll() is None:
                try:method('stop')
                except (OSError,RuntimeError,AssertionError):pass
                try:client.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(client.pid,signal.SIGTERM)
                    try:client.wait(timeout=3)
                    except subprocess.TimeoutExpired:os.killpg(client.pid,signal.SIGKILL);client.wait(timeout=3)
