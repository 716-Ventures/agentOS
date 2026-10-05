#!/usr/bin/python3
"""Root development-guest fixtures; no provider inference or credentials."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,'/usr/local/lib/agent-os/services')
import assistant
from broker_client import request as broker
import importlib.util
from importlib.machinery import SourceFileLoader
spec=importlib.util.spec_from_loader('work_ui',SourceFileLoader('work_ui','/usr/local/bin/agent-os'))
ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)

def cli(*args):return json.loads(subprocess.check_output(['agent-os',*map(str,args)]))
def wait(predicate):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.1)
    raise AssertionError('Fixture did not reach expected state')
def launch(activity,argv,**fields):
    job=broker('execute',activity=activity,argv=argv,purpose='Harmless lifecycle fixture',request_confirmation=True,**fields)
    if job['status']=='approval_required':broker('approve',job_id=job['id'])
    return job['id']
checks=[]
a=cli('create','Lifecycle stopped activity')['id'];b=cli('create','Lifecycle retained activity')['id']
core_a=cli('run',a,'--','/bin/sh','-c','echo "$AGENT_OS_JOB_ID"; exec /usr/bin/sleep 120')['id']
core_b=cli('run',b,'--','/usr/bin/sleep','120')['id']
broker_ids=[]
with tempfile.TemporaryDirectory(prefix='agent-os-lifecycle-') as tmp:
    root=Path(tmp);(root/'ai').mkdir();marker=root/'pids'
    code='import os,subprocess,time; p=subprocess.Popen(["/usr/bin/sleep","120"],start_new_session=True); open('+repr(str(marker))+',"w").write(str(os.getpid())+" "+str(p.pid)); time.sleep(120)'
    def workflow(prompt,history,cfg,dispatch,progress,record,**kw):
        result=dispatch('execute',dict(argv=['/usr/bin/python3','-c',code],purpose='Harmless detached-child fixture',background=True,lifetime_seconds=120,request_confirmation=True))
        assert result['status']=='approval_required',result
        assert result['origin']['core_job_id']==core_a
        assert len(result['origin']['conversation_id'])==32
        broker_ids.append(result['id']);broker('approve',job_id=result['id'])
        return dict(text='Fixture launched.',model='fixture',finish_reason='stop',messages=[{'role':'user','content':prompt},{'role':'assistant','content':'Fixture launched.'}])
    decisions=SimpleNamespace(select_history=lambda *a:[],select_memory=lambda *a:[],summary=lambda:{})
    try:
        with patch.object(assistant,'STATE',root/'ai'),patch.object(assistant,'config',return_value={}), \
             patch.object(assistant.model_usage,'configure'),patch.object(assistant.knowledge,'context',return_value=[]), \
             patch.object(assistant,'Decisions',return_value=decisions),patch.object(assistant,'run_agent',side_effect=workflow), \
             patch.object(assistant,'emit'),patch.object(assistant,'send'):
            assistant.handle(dict(op='ask',activity=a,prompt='Launch harmless test work',core_job_id=core_a,
                                  expected_generation=broker('activity_state',activity=a)['generation']),None)
        wait(marker.exists);pids=list(map(int,marker.read_text().split()))
        retained=launch(b,['/usr/bin/sleep','120'],background=True,lifetime_seconds=120);broker_ids.append(retained)
        pending=broker('execute',activity=a,argv=['/usr/bin/true'],purpose='Harmless pending fixture',request_confirmation=True)
        broker_ids.append(pending['id']);assert pending['status']=='approval_required'
        core_log=wait(lambda:ui.work_log(core_a)['text'].strip())
        assert core_log==str(core_a),core_log
        layout=ui.layout_request('ensure',activity=a)
        layout=ui.layout_request('apply',activity=a,expected_revision=layout['revision'],action=dict(operation='bind',surface_id=layout['surfaces'][0]['id'],job_id='broker:'+broker_ids[0],view='output'))
        assert layout['surfaces'][0]['job']=='broker:'+broker_ids[0]
        cli('remove',a)
        jobs=cli('jobs');refs={j['work_ref']:j for j in jobs}
        assert refs['core:'+str(core_a)]['status'] in ui.LIVE
        assert 'removed' in refs['broker:'+broker_ids[0]]['activity_name']
        checks.append('Core, broker and removed-activity work remain visible; broker binding and launch origin persist')
        generation=broker('activity_state',activity=a)['generation']
        stopped=cli('stop-activity',a);assert stopped['status']=='stopped'
        assert broker('poll',job_id=pending['id'])['status']=='rejected'
        for pid in pids:
            # A dead zombie has no running work; /proc remains until init reaps it.
            stat=Path('/proc')/str(pid)/'stat'
            assert not stat.exists() or stat.read_text().split(') ',1)[1].startswith('Z '),pid
        assert broker('poll',job_id=retained)['status'] in ui.LIVE
        assert next(j for j in cli('jobs',b) if j['native_id']==core_b)['status'] in ui.LIVE
        checks.append('Activity stop ends core and broker work, removes detached child, rejects approval and retains other activity')
        try:broker('execute',activity=a,argv=['/usr/bin/true'],purpose='Stale queued fixture',expected_generation=generation)
        except RuntimeError as exc:assert 'stopped' in str(exc)
        else:raise AssertionError('Stale generation launched')
        cli('stop-activity',b)
        saved=broker('activity_state',activity=a)['generation']
        subprocess.run(['systemctl','restart','agent-os-broker'],check=True)
        def recovered_generation():
            try:return broker('activity_state',activity=a)['generation']
            except OSError:return None
        assert wait(recovered_generation)==saved
        fresh=launch(a,['/usr/bin/true'],expected_generation=saved);broker_ids.append(fresh)
        wait(lambda:broker('poll',job_id=fresh)['status']=='succeeded')
        checks.append('Stop generation survives restart; stale requests fail and explicit new work succeeds')
    finally:
        for ident in broker_ids:
            try:broker('cancel',job_id=ident)
            except (OSError,RuntimeError):pass
        for activity in (a,b):
            try:ui.stop_activity_work(activity)
            except (OSError,RuntimeError):pass
print(json.dumps(dict(result='pass',checks=checks,provider_calls='fixtures; no live inference')))
