#!/usr/bin/python3
"""Root broker publisher, unprivileged binding reader, outage and restart contracts."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]

def wait(predicate,timeout=10):
    deadline=time.monotonic()+timeout
    while True:
        value=predicate()
        if value:return value
        assert time.monotonic()<deadline,'Source observation timed out'
        time.sleep(.05)

with tempfile.TemporaryDirectory(prefix='agentos-broker-source-') as directory:
    root=Path(directory);endpoint=root/'core.sock'
    env={**os.environ,'AGENT_OS_STATE':str(root/'state'),'AGENT_OS_SOCKET':str(endpoint)}
    core=None;producer=None
    def start():
        proc=subprocess.Popen([str(ROOT/'target/release/agent-os-core')],env=env,start_new_session=True)
        wait(endpoint.exists);return proc
    def stop(proc):
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)
    def call(op,**fields):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.settimeout(3);conn.connect(str(endpoint));conn.sendall(json.dumps({'op':op,**fields}).encode()+b'\n')
            with conn.makefile('rb') as stream:response=json.loads(stream.readline())
            assert response['ok'],response
            return response['result']
    try:
        core=start();activity=call('create',name='Broker observation fixture')['id']
        script='''import json,sys
sys.path.insert(0,sys.argv[1])
from source_publisher import BrokerSources
publisher=BrokerSources(sys.argv[2]);job={'id':'c'*32,'activity':int(sys.argv[3]),'source_revision':0,'status':'running','created_at':1}
publisher.mark(job);publisher.start();print('ready',flush=True)
try:
    for line in sys.stdin:
        command=json.loads(line);job['status']=command['status'];job['source_revision']+=1;publisher.mark(job)
finally:publisher.close()
'''
        producer=subprocess.Popen(['sudo','-n','/usr/bin/python3','-u','-c',script,str(ROOT/'services'),str(endpoint),str(activity)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        assert producer.stdout.readline().strip()=='ready'
        source='broker:'+'c'*32
        wait(lambda:any(row['source']==source and row['availability']=='available' for row in call('source.list',activity_id=str(activity))['sources']))
        doc={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':'broker-status','activity_id':str(activity),'revision':0,'title':'Broker state','root':'status','elements':{'status':{'type':'Status@1','props':{'value':{'binding':'job'}}}},'bindings':{'job':{'source':source,'path':'/status','access':'read'}},'actions':{}}
        call('presentation.apply',protocol='agentos.presentation/1',catalog_revision='native-core/1',request_id='broker-state-view',expected_revisions={'broker-status':None},operations=[{'op':'surface.create','document':doc}])
        def binding():return call('binding.snapshot',surface_id='broker-status')['bindings']['job']
        assert binding()['value']=='running' and binding()['availability']=='available'
        producer.stdin.write(json.dumps({'status':'succeeded'})+'\n');producer.stdin.flush()
        wait(lambda:binding()['value']=='succeeded')
        try:call('source.heartbeat')
        except AssertionError as exc:assert 'unauthorized' in str(exc)
        else:raise AssertionError('An unprivileged UI claimed authoritative source availability')
        stop(core);core=None;endpoint.unlink(missing_ok=True);core=start()
        assert binding()['value']=='succeeded' and binding()['availability']=='available'
        producer.stdin.close();assert producer.wait(timeout=5)==0
        wait(lambda:binding()['availability']=='unavailable')
        assert binding()['value']=='succeeded','Last observed outcome was lost on source disconnection'
        print('PASS: root-owned broker publisher, live scoped binding, domain-write rejection, core restart and truthful backend outage')
    finally:
        if producer:
            if producer.stdin and not producer.stdin.closed:producer.stdin.close()
            try:producer.wait(timeout=5)
            except subprocess.TimeoutExpired:producer.terminate();producer.wait(timeout=5)
            if producer.stdout:producer.stdout.close()
        if core:stop(core)
