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
import sys
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
    env={**os.environ,'AGENT_OS_STATE':str(root/'state'),'AGENT_OS_SOCKET':str(endpoint),'AGENT_OS_BROKER_SOCKET':str(root/'broker.sock')}
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
        script=r'''import json,sys
sys.path.insert(0,sys.argv[1])
from source_publisher import BrokerSources
from file_observations import FileObservations
from files import metadata
from pathlib import Path
import broker,socket,threading,os
publisher=BrokerSources(sys.argv[2]);job={'id':'c'*32,'activity':int(sys.argv[3]),'source_revision':0,'status':'running','created_at':1}
job_path=Path(sys.argv[4])/'job.json'
if job_path.exists():job=json.loads(job_path.read_text())
store=FileObservations(Path(sys.argv[4])/'observations',publisher)
note=Path(sys.argv[4])/'note'
if not note.exists():note.write_text('private content')
store.recover();source=store.save(int(sys.argv[3]),metadata(note))
broker.STATE=Path(sys.argv[4])/'broker-state';broker.STATE.mkdir(exist_ok=True)
(broker.STATE/(job['id']+'.log')).write_text('Observed 日本語')
broker.JOBS[job['id']]=job
endpoint=Path(sys.argv[4])/'broker.sock';endpoint.unlink(missing_ok=True)
server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(endpoint));os.chmod(endpoint,0o666);server.listen(8)
def serve():
    while True:
        try:conn,_=server.accept()
        except OSError:return
        with conn:
            with conn.makefile('rb') as stream:request=json.loads(stream.readline())
            try:response={'ok':True,'result':broker.handle(request,1000)}
            except ValueError as exc:response={'ok':False,'error':str(exc)}
            conn.sendall(json.dumps(response).encode()+b'\n')
threading.Thread(target=serve,daemon=True).start()
# A rejected durable observation must not block this unrelated live job.
publisher.mark({**job,'id':'d'*32,'activity':2147483647})
publisher.mark(job);publisher.start();print(source,flush=True)
try:
    for line in sys.stdin:
        command=json.loads(line);job['status']=command['status'];job['source_revision']+=1;broker.REVISION+=1;publisher.mark(job)
        job_path.write_text(json.dumps(job))
        note.write_text('new');store.save(int(sys.argv[3]),metadata(note))
finally:publisher.close();server.close()
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
        callbacks=call('action.ensure_sources',activity_id=activity,sources=[source,file_source])['actions']
        output_action=next(row for row in callbacks if row['operation']=='broker.read_output')
        file_action=next(row for row in callbacks if row['operation']=='file.inspect')
        output_invocation=dict(reference=output_action['reference'],request_id='broker-output-callback',expected_source_revision=output_action['source_revision'],parameters={'offset':0})
        def broker_call(op,**fields):
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
                conn.settimeout(3);conn.connect(str(root/'broker.sock'));conn.sendall(json.dumps({'op':op,**fields}).encode()+b'\n')
                with conn.makefile('rb') as stream:response=json.loads(stream.readline())
                assert response['ok'],response
                return response['result']
        initial_broker=broker_call('list.page',activity=activity)
        assert initial_broker['jobs'][0]['id']=='c'*32
        sys.path.insert(0,str(ROOT/'client'))
        from broker_pages import read as read_broker
        assert read_broker(broker_call,activity)[0]['status']=='running'
        output_receipt=call('action.invoke',**output_invocation)
        assert output_receipt['status']=='succeeded' and output_receipt['observed_target']['output']=='Observed 日本語'
        file_invocation=dict(reference=file_action['reference'],request_id='file-metadata-callback',expected_source_revision=file_action['source_revision'])
        file_receipt=call('action.invoke',**file_invocation)
        assert file_receipt['status']=='succeeded' and file_receipt['observed_target']['values']['size_bytes']==15
        assert 'private content' not in json.dumps(file_receipt)

        producer.stdin.write(json.dumps({'status':'succeeded'})+'\n');producer.stdin.flush()
        wait(lambda:binding()['value']=='succeeded')
        wait(lambda:file_binding()['value']=='3 bytes')
        try:broker_call('list.page',activity=activity,expected_revision=initial_broker['revision'])
        except AssertionError as exc:assert 'resync_required' in str(exc)
        else:raise AssertionError('Broker pages accepted a mixed metadata revision')
        assert read_broker(broker_call,activity)[0]['status']=='succeeded'

        try:call('source.heartbeat')
        except AssertionError as exc:assert 'unauthorized' in str(exc)
        else:raise AssertionError('An unprivileged UI claimed authoritative source availability')
        stop(core);core=None;endpoint.unlink(missing_ok=True);core=start()
        assert binding()['value']=='succeeded' and binding()['availability']=='available'
        assert file_binding()['value']=='3 bytes' and file_binding()['availability']=='available'
        assert call('action.invoke',**file_invocation)==file_receipt
        assert call('action.invoke',**output_invocation)==output_receipt
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
        subprocess.run(['sudo','-n','/usr/bin/python3','-c','import shutil,sys;shutil.rmtree(sys.argv[1],ignore_errors=True)',str(root/'broker-state')],check=True)
