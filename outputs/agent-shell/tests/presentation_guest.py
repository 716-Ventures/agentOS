#!/usr/bin/python3
"""Real Linux IPC principals, two clients and service restart; isolated test core."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
PROTOCOL='agentos.presentation/1'
CATALOG='native-core/1'


def main():
    with tempfile.TemporaryDirectory(prefix='agentos-presentation-') as directory:
        root=Path(directory);root.chmod(0o755)
        endpoint=str(root/'api.sock')
        def start():
            proc=subprocess.Popen([str(ROOT/'target/release/agent-os-core')],env={**os.environ,'AGENT_OS_STATE':str(root/'state'),'AGENT_OS_SOCKET':endpoint},stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,start_new_session=True)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if proc.poll() is not None:raise RuntimeError(proc.stderr.read().decode())
                try:
                    result=call({'op':'catalog.get'})
                    assert result['ok'];os.chmod(endpoint,0o666);return proc
                except (OSError,ValueError):time.sleep(.02)
            raise RuntimeError('Test core did not start')
        def call(value):
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
                conn.settimeout(5);conn.connect(endpoint);conn.sendall(json.dumps(value).encode()+b'\n')
                with conn.makefile('rb') as stream:return json.loads(stream.readline(8*1024*1024))
        def ok(value):
            response=call(value);assert response['ok'],response;return response['result']
        def stop(proc):
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)
            proc.stderr.close()
        proc=None
        try:
            proc=start();activity=ok({'op':'create','name':'Presentation fixture'})['id']
            doc={'protocol':PROTOCOL,'catalog_revision':CATALOG,'surface_id':'surface-fixture','activity_id':str(activity),'revision':0,'title':'Fixture','root':'text','elements':{'text':{'type':'Text@1','props':{'text':'Original'}}},'bindings':{},'actions':{}}
            create={'op':'presentation.apply','protocol':PROTOCOL,'catalog_revision':CATALOG,'request_id':'create','expected_revisions':{'surface-fixture':None},'operations':[{'op':'surface.create','document':doc}]}
            receipt=ok(create);assert ok(create)==receipt
            ok({'op':'interaction.begin','surface_id':'surface-fixture','element_id':'text'})
            change={'op':'presentation.apply','protocol':PROTOCOL,'catalog_revision':CATALOG,'request_id':'change','expected_revisions':{'surface-fixture':0},'operations':[{'op':'element.set_props','surface_id':'surface-fixture','element_id':'text','props':{'text':'Changed'}}]}
            script='import json,socket,sys;s=socket.socket(socket.AF_UNIX);s.connect(sys.argv[1]);s.sendall(sys.argv[2].encode()+b"\\n");print(s.makefile().readline());s.close()'
            def other(value,agent=False):
                argv=['/usr/bin/python3','-c',script,endpoint,json.dumps(value)]
                if agent:argv=['sudo','-n','-u','agentos-ai',*argv]
                return json.loads(subprocess.check_output(argv,text=True))
            conflict=other(change);assert not conflict['ok'] and 'interaction_conflict' in conflict['error'],conflict
            forged=other({'op':'interaction.begin','surface_id':'surface-fixture','element_id':'text','actor':'human'},agent=True)
            assert not forged['ok'] and 'unauthorized' in forged['error'],forged
            ok({'op':'draft.save','surface_id':'surface-fixture','element_id':'text','expected_draft_revision':0,'draft':'Unsaved Unicode λ'})
            stop(proc);proc=None;Path(endpoint).unlink(missing_ok=True);proc=start()
            assert ok(create)==receipt
            recovered=ok({'op':'draft.get','surface_id':'surface-fixture','element_id':'text'});assert recovered['draft']=='Unsaved Unicode λ'
            assert not other(change)['ok']
            # This is the original authenticated input session, so a direct change is valid.
            changed=ok(change);assert changed['revisions']['surface-fixture']==1
            events=ok({'op':'presentation.subscribe','after_cursor':1});assert events['events'][0]['event_cursor']==2
            undone=ok({'op':'presentation.undo','event_cursor':2,'request_id':'undo'});assert undone['revisions']['surface-fixture']==2
            assert ok({'op':'presentation.snapshot'})['documents']['surface-fixture']['elements']['text']['props']['text']=='Original'
            job=ok({'op':'run','activity_id':activity,'argv':['/bin/sleep','30']})['id']
            deadline=time.monotonic()+5
            while True:
                observed=next(j for j in ok({'op':'snapshot'})['jobs'] if j['id']==job)
                if observed['status']=='running':break
                assert time.monotonic()<deadline;time.sleep(.02)
            action=ok({'op':'action.issue','activity_id':activity,'job_id':job,'operation':'job.cancel'})
            invocation={'op':'action.invoke','reference':action['reference'],'request_id':'stop-click','expected_source_revision':action['source_revision']}
            first=ok(invocation);assert ok(invocation)==first
            forged=other({**invocation,'request_id':'forged-click'},agent=True)
            assert not forged['ok'] and 'unauthorized' in forged['error'],forged
            deadline=time.monotonic()+5
            while True:
                status=ok({'op':'action.status','request_id':'stop-click'})
                if status['status']=='succeeded':break
                assert time.monotonic()<deadline;time.sleep(.02)
            assert status['observed_target']['status']=='cancelled',status
            ok({'op':'action.revoke','reference':action['reference']})
            metadata=ok({'op':'action.metadata','reference':action['reference']})
            revoked=call({**invocation,'request_id':'revoked-click','expected_source_revision':metadata['source_revision']})
            assert not revoked['ok'],revoked
            assert ok({'op':'presentation.snapshot'})['documents']['surface-fixture']['revision']==2
            print('PASS: host-issued stop action, actual process cancellation, idempotent callback receipt, forged actor rejection, revocation')
            print('PASS: presentation IPC principals, atomic receipts, two clients, draft recovery, ordered changes, undo')
        finally:
            if proc:stop(proc)

if __name__=='__main__':main()
