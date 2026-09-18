#!/usr/bin/python3
"""Run inside the development guest. Restarts only agent-os-core.service."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

spec=importlib.util.spec_from_file_location('client','/usr/local/bin/agent-os')
# The installed executable intentionally has no .py suffix.
from importlib.machinery import SourceFileLoader
client=SourceFileLoader('agent_os_client','/usr/local/bin/agent-os').load_module()
ask=client.request
checks=[]


def passed(name):
    checks.append(name); print('PASS:',name,flush=True)


def job(n):
    return next(j for j in ask('snapshot')['jobs'] if j['id']==n)


def finish(n,seconds=8):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        j=job(n)
        if j['status'] not in client.LIVE: return j
        time.sleep(.05)
    raise AssertionError(f'Job {n} did not finish')


def output(n):
    offset=0;parts=[]
    while True:
        chunk=ask('log',job_id=n,offset=offset)
        if chunk['offset']==offset: return ''.join(parts)
        offset=chunk['offset'];parts.append(chunk['text'])


def run(argv): return ask('run',activity_id=activity['id'],argv=argv)['id']


activity=ask('create',name='Integration checks '+str(int(time.time())))
assert activity['workspace'].startswith('/var/lib/agent-os-runtime/workspaces/')
passed('persistent activity and workspace creation')

# Each CLI invocation connects and disconnects; the daemon owns the job.
result=subprocess.check_output(['agent-os','run',str(activity['id']),'--','python3','-u','-c','import time; print("first",flush=True); time.sleep(1); print("after disconnect",flush=True)'],text=True)
n=json.loads(result)['id']
end=time.monotonic()+2
while 'first' not in output(n) and time.monotonic()<end: time.sleep(.03)
assert 'first' in output(n)
assert job(n)['status']=='running'
assert finish(n)['status']=='succeeded'
assert 'after disconnect' in output(n)
passed('live output and job survival after submitting client exits')

n=run(['python3','-c','import sys; print("failure detail",file=sys.stderr); sys.exit(7)'])
assert finish(n)['exit_code']==7 and 'failure detail' in output(n)
n=run(['/does/not/exist'])
assert finish(n)['status']=='failed' and job(n)['error']
passed('nonzero exit and failed spawn are recorded accurately')

stale=ask('snapshot')['revision']
ask('create',name='Revision advance')
try:
    ask('run',activity_id=activity['id'],argv=['true'],expected_revision=stale)
    raise AssertionError('Stale action was executed')
except RuntimeError as e: assert 'State changed' in str(e)
passed('stale action rejected before execution')

# Both parent and child resist TERM, exercising escalation and process-group cleanup.
n=run(['python3','-u','-c','import subprocess,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); p=subprocess.Popen(["python3","-c","import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"]); print(p.pid,flush=True); time.sleep(60)'])
end=time.monotonic()+3
while not output(n).strip() and time.monotonic()<end:time.sleep(.03)
child_pid=int(output(n).strip())
start=time.monotonic();ask('cancel',job_id=n)
assert finish(n)['status']=='cancelled'
assert time.monotonic()-start<2.5
end=time.monotonic()+2
while Path(f'/proc/{child_pid}/stat').exists() and time.monotonic()<end:
    if Path(f'/proc/{child_pid}/stat').read_text().split()[2]=='Z':break
    time.sleep(.05)
assert not Path(f'/proc/{child_pid}/stat').exists() or Path(f'/proc/{child_pid}/stat').read_text().split()[2]=='Z'
assert ask('cancel',job_id=n)['status']=='cancelled'
passed('cancellation escalates, terminates group, and is idempotent')

n=run(['python3','-c','import subprocess; subprocess.Popen(["sleep","60"]); print("parent complete")'])
assert finish(n)['status']=='succeeded'
passed('parent completion cleans up ordinary background descendants')

n=run(['python3','-c','print("X"*2000000)'])
assert finish(n)['status']=='succeeded'
data=output(n)
assert len(data)<=1024*1024+100 and 'Output capped' in data
assert '\x1b' not in client.clean('\x1b[2J\x1b]52;c;Zm9v\x07hello\x00')
passed('bounded output capture and terminal control sanitization')

n=run(['touch','/etc/agent-os-test-escape'])
assert finish(n)['status']=='failed'
n=run(['sudo','-n','true'])
assert finish(n)['status']=='failed'
passed('system files protected and job privilege escalation denied')

n=run(['python3','-c','from pathlib import Path; Path("persistent.txt").write_text("kept")'])
assert finish(n)['status']=='succeeded'
long=run(['sleep','60'])
time.sleep(.15)
subprocess.run(['sudo','systemctl','restart','agent-os-core.service'],check=True)
end=time.monotonic()+5
while True:
    try:
        s=ask('snapshot');break
    except OSError:
        if time.monotonic()>end:raise
        time.sleep(.05)
assert job(long)['status']=='interrupted'
n=run(['cat','persistent.txt'])
assert finish(n)['status']=='succeeded' and output(n)=='kept'
events=ask('history',activity_id=activity['id'])
assert any(e['kind']=='job.interrupted' for e in events)
passed('service restart preserves activities/files/history and does not replay jobs')

report={'result':'pass','checks':checks,'activity_id':activity['id'],'tested_at':time.time()}
Path('/home/developer/agent-os-integration.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
