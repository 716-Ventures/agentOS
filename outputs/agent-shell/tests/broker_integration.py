#!/usr/bin/python3
"""Run in guest as developer. Uses real systemd jobs with OS authority; approves only the harmless fixtures below."""
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,'/usr/local/lib/agent-os/services')
from broker_client import request

activity=json.loads(subprocess.check_output(['agent-os','create','Broker verification']))['id']
checks=[]


def execute(argv,**kw):
    return request('execute',activity=activity,argv=argv,purpose='Broker integration verification',request_confirmation=True,**kw)


def finish(job,timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        j=request('poll',job_id=job['id'])
        if j['status'] not in ('starting','running','cancelling'):return j
        time.sleep(.1)
    raise AssertionError('Job did not complete: '+job['id'])


def start_fixture(argv, **kw):
    job = execute(argv, **kw)
    if job['status'] == 'approval_required':
        subprocess.run(['sudo', '-n', 'agent-os-broker', 'approve', job['id']],
                       check=True, stdout=subprocess.DEVNULL)
    assert job['status'] in ('starting', 'running', 'approval_required', 'succeeded', 'failed'), job
    return job


def run(argv, **kw): return finish(start_fixture(argv, **kw))


def file_op(op,**fields):
    result=run(['/usr/bin/python3','/usr/local/lib/agent-os/services/files.py',json.dumps({'op':op,**fields})])
    return result,json.loads(result['output'])

j=run(['/usr/bin/uname','-r']);assert j['status']=='succeeded',j
assert j['output'].strip()==subprocess.check_output(['uname','-r'],text=True).strip()
checks.append('General execute returns the real guest kernel')
j=run(['/bin/sh','-c','id -un; command -v ip; cat /etc/os-release'])
assert j['output'].splitlines()[0]=='root' and 'Debian' in j['output'],j
checks.append('Assessed execution uses root authority and can inspect OS files/tools')
# A unique test file verifies intentional OS-wide write authority. No credentials are read.
system_path='/var/tmp/agent-os-broker-'+str(activity)+'.txt'
j=run(['/usr/bin/touch',system_path]);assert j['status']=='succeeded',j
checks.append('OS-wide writes are available; activity directories are organizational')
created,data=file_op('write',path='example.txt',content='first\n',expected_sha256='missing');assert created['status']=='succeeded',created
read,data=file_op('read',path='example.txt');digest=data['sha256'];assert data['content']=='first\n'
updated,data=file_op('write',path='example.txt',content='second\n',expected_sha256=digest);assert updated['status']=='succeeded',updated
backup=data['backup'];assert run(['/usr/bin/cat',backup])['output']=='first\n'
stale,data=file_op('write',path='example.txt',content='third',expected_sha256=digest);assert stale['status']=='failed'
assert run(['/usr/bin/cat','example.txt'])['output']=='second\n'
checks.append('File reads, guarded writes, backups and stale-hash rejection work')
other=json.loads(subprocess.check_output(['agent-os','create','Broker access peer']))['id']
j=request('execute',activity=other,argv=['/usr/bin/cat',updated['workspace']+'/example.txt'],purpose='Cross-activity access check',request_confirmation=True)
if j['status']=='approval_required':
 subprocess.run(['sudo','-n','agent-os-broker','approve',j['id']],check=True,stdout=subprocess.DEVNULL)
j=finish(j)
assert j['status']=='succeeded' and j['output']=='second\n',j
checks.append('Activities do not impose filesystem isolation')
j=run(['/bin/sh','-c','echo failure-output; exit 7']);assert j['exit_code']==7 and 'failure-output' in j['output'],j
j=run(['/usr/bin/python3','-c','print("x"*500000)']);assert j['output_truncated'] and j['status']=='succeeded',j
checks.append('Exit codes and bounded output are retained')
j=run(['/usr/bin/sleep','30'],timeout_seconds=1);assert j['status']=='failed',j
checks.append('Runtime deadline stops a command through systemd')
j=start_fixture(['/bin/sh','-c','setsid sleep 120 & wait'],timeout_seconds=150)
time.sleep(.5);request('cancel',job_id=j['id']);j=finish(j)
assert j['status']=='cancelled',j
r=subprocess.run(['systemctl','is-active','agent-os-exec-'+j['id']+'.service'],capture_output=True)
assert r.returncode!=0
checks.append('Cancellation removes the entire service cgroup, including a setsid descendant')
# Conservative hazard matching sees the literal 'rm ' in a harmless printf.
# This deliberately exercises local approval without executing a removal.
j=execute(['/usr/bin/printf','%s\n','rm '],scope='system');assert j['status']=='approval_required'
try:request('approve',job_id=j['id']);raise AssertionError('Non-root approval succeeded')
except RuntimeError:pass
subprocess.run(['sudo','agent-os-broker','approve',j['id']],check=True,stdout=subprocess.DEVNULL)
j=finish(j);assert j['output'].strip()=='rm' and j['status']=='succeeded',j
checks.append('Hazard proposal requires local root approval; the approved harmless fixture runs')
print(json.dumps({'activity':activity,'checks':checks},indent=2))
