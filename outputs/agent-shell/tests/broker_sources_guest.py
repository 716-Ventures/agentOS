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
from file_observations import FileObservations
from files import metadata
from pathlib import Path
publisher=BrokerSources(sys.argv[2]);job={'id':'c'*32,'activity':int(sys.argv[3]),'source_revision':0,'status':'running','created_at':1}
job_path=Path(sys.argv[4])/'job.json'
if job_path.exists():job=json.loads(job_path.read_text())
store=FileObservations(Path(sys.argv[4])/'observations',publisher)
note=Path(sys.argv[4])/'note'
if not note.exists():note.write_text('private content')
store.recover();source=store.save(int(sys.argv[3]),metadata(note))
publisher.mark(job);publisher.start();print(source,flush=True)
try:
    for line in sys.stdin:
        command=json.loads(line);job['status']=command['status'];job['source_revision']+=1;publisher.mark(job)
        job_path.write_text(json.dumps(job))
        note.write_text('new');store.save(int(sys.argv[3]),metadata(note))
finally:publisher.close()
'''
        def start_producer():return subprocess.Popen(['sudo','-n','/usr/bin/python3','-u','-c',script,str(ROOT/'services'),str(endpoint),str(activity),str(root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        producer=start_producer();file_source=producer.stdout.readline().strip()
        assert file_source.startswith('file:')
        source='broker:'+'c'*32
        wait(lambda:any(row['source']==source and row['availability']=='available' for row in call('source.list',activity_id=str(activity))['sources']))
        doc={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':'broker-status','activity_id':str(activity),'revision':0,'title':'Broker state','root':'status','elements':{'status':{'type':'Status@1','props':{'value':{'binding':'job'}}}},'bindings':{'job':{'source':source,'path':'/status','access':'read'}},'actions':{}}
        call('presentation.apply',protocol='agentos.presentation/1',catalog_revision='native-core/1',request_id='broker-state-view',expected_revisions={'broker-status':None},operations=[{'op':'surface.create','document':doc}])
        def binding():return call('binding.snapshot',surface_id='broker-status')['bindings']['job']
        assert binding()['value']=='running' and binding()['availability']=='available'
        wait(lambda:any(row['source']==file_source for row in call('source.list',activity_id=str(activity))['sources']))
        file_doc=json.loads(json.dumps(doc));file_doc['surface_id']='file-size';file_doc['bindings']['job']={'source':file_source,'path':'/size_text','access':'read'}
        call('presentation.apply',protocol='agentos.presentation/1',catalog_revision='native-core/1',request_id='file-size-view',expected_revisions={'file-size':None},operations=[{'op':'surface.create','document':file_doc}])
        def file_binding():return call('binding.snapshot',surface_id='file-size')['bindings']['job']
        assert file_binding()['value']=='15 bytes' and file_binding()['availability']=='available'
        assert 'private content' not in json.dumps(file_binding())
        producer.stdin.write(json.dumps({'status':'succeeded'})+'\n');producer.stdin.flush()
        wait(lambda:binding()['value']=='succeeded')
        wait(lambda:file_binding()['value']=='3 bytes')
        try:call('source.heartbeat')
        except AssertionError as exc:assert 'unauthorized' in str(exc)
        else:raise AssertionError('An unprivileged UI claimed authoritative source availability')
        stop(core);core=None;endpoint.unlink(missing_ok=True);core=start()
        assert binding()['value']=='succeeded' and binding()['availability']=='available'
        assert file_binding()['value']=='3 bytes' and file_binding()['availability']=='available'
        producer.stdin.close();assert producer.wait(timeout=5)==0
        wait(lambda:binding()['availability']=='unavailable')
        assert binding()['value']=='succeeded','Last observed outcome was lost on source disconnection'
        wait(lambda:file_binding()['availability']=='unavailable')
        producer.stdout.close();producer=start_producer()
        assert producer.stdout.readline().strip()==file_source
        wait(lambda:file_binding()['availability']=='available')
        assert file_binding()['value']=='3 bytes'
        print('PASS: root-owned broker and file publishers, durable file identity recovery, live scoped binding, domain-write rejection, core restart and truthful backend outage')
    finally:
        if producer:
            if producer.stdin and not producer.stdin.closed:producer.stdin.close()
            try:producer.wait(timeout=5)
            except subprocess.TimeoutExpired:producer.terminate();producer.wait(timeout=5)
            if producer.stdout:producer.stdout.close()
        if core:stop(core)
        subprocess.run(['sudo','-n','/usr/bin/python3','-c','import shutil,sys;shutil.rmtree(sys.argv[1],ignore_errors=True)',str(root/'observations')],check=True)
