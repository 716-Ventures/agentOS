#!/usr/bin/python3
"""Run in guest as developer. Uses live systemd isolation; no model fixtures."""
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
    return request('execute',activity=activity,argv=argv,purpose='Broker integration verification',**kw)


def finish(job,timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        j=request('poll',job_id=job['id'])
        if j['status'] not in ('starting','running','cancelling'):return j
        time.sleep(.1)
    raise AssertionError('Job did not complete: '+job['id'])


def run(argv,**kw):return finish(execute(argv,**kw))


def file_op(op,**fields):
    result=run(['/usr/bin/python3','/usr/local/lib/agent-os/services/files.py',json.dumps({'op':op,**fields})])
    return result,json.loads(result['output'])

j=run(['/usr/bin/uname','-r']);assert j['status']=='succeeded',j
assert j['output'].strip()==subprocess.check_output(['uname','-r'],text=True).strip()
checks.append('General execute returns the real guest kernel')
j=run(['/bin/sh','-c','id -un; command -v ip; cat /etc/os-release'])
assert 'agentos-w'+str(activity) in j['output'] and 'Debian' in j['output'],j
checks.append('Normal execution uses a dedicated activity identity and can inspect OS files/tools')
for argv in [
 ['/usr/bin/touch','/etc/agent-os-broker-test'],
 ['/bin/sh','-c','test -r /etc/agent-os/providers.json'],
 ['/bin/sh','-c','test -r /var/lib/agent-os-ai'],
 ['/usr/bin/sudo','-n','true'],
 ['/usr/bin/python3','-c',"import socket;s=socket.socket(socket.AF_UNIX);s.connect('/run/agent-os-broker/api.sock')"],
]:
 j=run(argv);assert j['status']=='failed',(argv,j)
checks.append('Sandbox blocks system writes, keys, assistant state, sudo and broker recursion')
created,data=file_op('write',path='example.txt',content='first\n',expected_sha256='missing');assert created['status']=='succeeded',created
read,data=file_op('read',path='example.txt');digest=data['sha256'];assert data['content']=='first\n'
updated,data=file_op('write',path='example.txt',content='second\n',expected_sha256=digest);assert updated['status']=='succeeded',updated
backup=data['backup'];assert run(['/usr/bin/cat',backup])['output']=='first\n'
stale,data=file_op('write',path='example.txt',content='third',expected_sha256=digest);assert stale['status']=='failed'
assert run(['/usr/bin/cat','example.txt'])['output']=='second\n'
checks.append('File reads, guarded writes, backups and stale-hash rejection work')
other=json.loads(subprocess.check_output(['agent-os','create','Broker isolation peer']))['id']
j=finish(request('execute',activity=other,argv=['/usr/bin/cat',updated['workspace']+'/example.txt'],purpose='Cross-activity isolation check'))
assert j['status']=='failed',j
checks.append('Separate activity identities prevent cross-activity workspace reads')
j=run(['/bin/sh','-c','echo failure-output; exit 7']);assert j['exit_code']==7 and 'failure-output' in j['output'],j
j=run(['/usr/bin/python3','-c','print("x"*500000)']);assert j['output_truncated'] and j['status']=='succeeded',j
checks.append('Exit codes and bounded output are retained')
j=run(['/usr/bin/sleep','30'],timeout_seconds=1);assert j['status']=='failed',j
checks.append('Runtime deadline stops a command through systemd')
j=execute(['/bin/sh','-c','setsid sleep 120 & wait'],timeout_seconds=150)
time.sleep(.5);request('cancel',job_id=j['id']);j=finish(j)
assert j['status']=='cancelled',j
r=subprocess.run(['systemctl','is-active','agent-os-exec-'+j['id']+'.service'],capture_output=True)
assert r.returncode!=0
checks.append('Cancellation removes the entire service cgroup, including a setsid descendant')
j=execute(['/usr/bin/id','-u'],scope='system');assert j['status']=='approval_required'
try:request('approve',job_id=j['id']);raise AssertionError('Non-root approval succeeded')
except RuntimeError:pass
subprocess.run(['sudo','agent-os-broker','approve',j['id']],check=True,stdout=subprocess.DEVNULL)
j=finish(j);assert j['output'].strip()=='0' and j['status']=='succeeded',j
checks.append('System scope waits for local root approval; approved id command runs as root')
print(json.dumps({'activity':activity,'checks':checks},indent=2))
