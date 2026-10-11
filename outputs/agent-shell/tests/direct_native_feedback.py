#!/usr/bin/python3
"""Sequential real GTK typing receipts, optionally during two owned broker CPU jobs."""
import json
from pathlib import Path
import subprocess
import time


def verify(metrics, core, login_user, keyboard, wait_text, load=False):
    def broker(op, **fields):
        code="import sys,json;sys.path.insert(0,'/usr/local/lib/agent-os/services');from broker_client import request;q=json.load(sys.stdin);print(json.dumps(request(q.pop('op'),**q)))"
        result=subprocess.run(['runuser','-u',login_user,'--','python3','-c',code],input=json.dumps({'op':op,**fields}),text=True,capture_output=True,check=True,timeout=8)
        return json.loads(result.stdout)
    def wait(predicate, meaning):
        deadline=time.monotonic()+8
        while True:
            result=predicate()
            if result:return result
            if time.monotonic()>deadline:raise RuntimeError(meaning)
            time.sleep(.03)
    def cpu_usage(job):
        unit='agent-os-exec-'+job+'.service'
        group=subprocess.check_output(['systemctl','show',unit,'--property=ControlGroup','--value'],text=True).strip()
        if not group.startswith('/') or '..' in group.split('/'):raise RuntimeError('Invalid owned work cgroup')
        values=dict(line.split() for line in (Path('/sys/fs/cgroup')/group.lstrip('/')/'cpu.stat').read_text().splitlines())
        return int(values['usage_usec'])
    def receipt():
        reports=[json.loads(p.read_text()) for p in metrics.glob('feedback-*.json')]
        return next((r for r in reports if r['requested']),None)
    jobs=[]
    try:
        if load:
            activity=int(core('presentation.get')['activity_id'])
            code="import time;print('CPU_LOAD_READY',flush=True);end=time.monotonic()+60\nwhile time.monotonic()<end: pass"
            for index in range(2):
                job=broker('execute',activity=activity,argv=['/usr/bin/python3','-u','-c',code,str(index)],purpose='Bounded native feedback CPU contention fixture',background=True,lifetime_seconds=60,request_confirmation=True)['id']
                assert job not in jobs,'Distinct CPU fixtures were unexpectedly deduplicated'
                jobs.append(job)
                state=broker('poll',job_id=job)
                assert state['status']=='approval_required',state
                subprocess.run(['agent-os-broker','approve',job],check=True,stdout=subprocess.DEVNULL,timeout=10)
                wait(lambda:broker('poll',job_id=job)['status']=='running' and 'CPU_LOAD_READY' in broker('poll',job_id=job)['output'],'Owned CPU work did not start')
            before={job:cpu_usage(job) for job in jobs}
        for index in range(20):
            keyboard.chord(30)
            wait_text(lambda value:value['text']=='a'*(index+1))
            deadline=time.monotonic()+5
            while True:
                report=receipt()
                if report and report['presented']==index+1:break
                if time.monotonic()>deadline:raise RuntimeError('Native GTK presentation receipt missing: '+repr(report))
                time.sleep(.01)
            assert report['requested']==index+1 and report['discarded']==0 and report['invalid']==0 and report['pending']==0,report
        if load:
            usage=[cpu_usage(job)-before[job] for job in jobs]
            assert all(value>=100000 for value in usage),usage
            assert all(broker('poll',job_id=job)['status']=='running' for job in jobs),'CPU work stopped before measurement completed'
            report={**report,'profile':'two concurrent broker CPU jobs','job_cpu_usage_usec':usage}
        else:report={**report,'profile':'idle editor'}
        print('Native GTK input-to-presentation measurement '+json.dumps(report),flush=True)
        assert report['p95_ms']<=50,report
        print('PASS: native GTK editor kernel input-to-presentation '+json.dumps(report),flush=True)
    finally:
        errors=[]
        for job in jobs:
            try:
                broker('cancel',job_id=job)
                wait(lambda:broker('poll',job_id=job)['status'] in ('cancelled','failed','succeeded'),'Owned CPU work did not stop')
                assert subprocess.run(['systemctl','is-active','--quiet','agent-os-exec-'+job+'.service']).returncode!=0,'Owned CPU work unit leaked'
            except Exception as error:errors.append(str(error))
        if errors:raise RuntimeError('Owned CPU work cleanup failed: '+repr(errors))
