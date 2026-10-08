#!/usr/bin/python3
"""Real systemd PTYs: controlling terminal, raw input, resize, reconnect, stop/restart."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,'/usr/local/lib/agent-os/services')
from broker_client import request

activity=json.loads(subprocess.check_output(['agent-os','create','PTY acceptance']))['id']
jobs=[]

def start(code):
    job=request('execute',activity=activity,argv=['/usr/bin/python3','-u','-c',code],purpose='Harmless PTY acceptance fixture',
                terminal=True,background=True,lifetime_seconds=120,request_confirmation=True,rows=25,cols=90)
    jobs.append(job['id'])
    if job['status']=='approval_required':
        subprocess.run(['sudo','-n','agent-os-broker','approve',job['id']],check=True,stdout=subprocess.DEVNULL)
    end=time.monotonic()+10
    while request('poll',job_id=job['id'])['status']=='starting' and time.monotonic()<end:time.sleep(.05)
    assert request('poll',job_id=job['id'])['status']=='running',request('poll',job_id=job['id'])
    token=request('terminal_attach',job_id=job['id'])['token']
    return job['id'],token


def call(op,**fields):return request('terminal_'+op,job_id=ident,token=token,**fields)
def write(data):
    while data:
        sent=call('write',data=base64.b64encode(data[:4096]).decode())['written'];data=data[sent:]
        if not sent:time.sleep(.02)

def until(marker):
    global cursor,output
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        result=call('read',cursor=cursor);cursor=result['cursor'];output+=base64.b64decode(result['data'])
        if marker in output:return
        if result['closed']:break
        time.sleep(.03)
    raise AssertionError((marker,output,request('poll',job_id=ident)))

try:
    ident,token=start('''
import os,signal,sys,time
assert all(os.isatty(fd) for fd in (0,1,2))
os.close(os.open('/dev/tty',os.O_RDWR))
print('TTY_READY',os.get_terminal_size(0),flush=True)
signal.signal(signal.SIGWINCH,lambda *_:print('RESIZED',os.get_terminal_size(0),flush=True))
value=input('Name? ')
print('HELLO',value,flush=True)
try:
    while True:time.sleep(.1)
except KeyboardInterrupt:print('INTERRUPTED',flush=True)
''')
    cursor=0;output=b'';until(b'Name?')
    assert b'columns=90' in output and b'lines=25' in output,output
    call('resize',rows=31,cols=103);until(b'columns=103')
    write('Ada \u2603\n'.encode());until('HELLO Ada \u2603'.encode())
    call('detach')
    try:call('write',data='YQ==');raise AssertionError('Old controller still valid')
    except RuntimeError:pass
    token=request('terminal_attach',job_id=ident)['token']
    cursor=0;output=b'';until(b'HELLO Ada')
    write(b'\x03');until(b'INTERRUPTED')
    deadline=time.monotonic()+5
    while request('poll',job_id=ident)['status']=='running' and time.monotonic()<deadline:time.sleep(.05)
    assert request('poll',job_id=ident)['status']=='succeeded'
    call('detach')
    ident,token=start("import sys,time;print('Z'*300000,flush=True);print('LATE_PROMPT',flush=True);input();print('AFTER_LOG_LIMIT',flush=True);time.sleep(120)")
    cursor=0;output=b'';until(b'LATE_PROMPT')
    assert request('poll',job_id=ident)['output_truncated']
    write(b'continue\n');until(b'AFTER_LOG_LIMIT')
    call('detach')
    request('cancel',job_id=ident)
    deadline=time.monotonic()+8
    while request('poll',job_id=ident)['status'] in ('running','cancelling') and time.monotonic()<deadline:time.sleep(.05)
    ident,token=start("import time;print('STOP_READY',flush=True);time.sleep(120)")
    cursor=0;output=b'';until(b'STOP_READY')
    request('stop_activity',activity=activity)
    deadline=time.monotonic()+8
    while request('poll',job_id=ident)['status'] in ('running','cancelling') and time.monotonic()<deadline:time.sleep(.05)
    assert request('poll',job_id=ident)['status']=='cancelled'
    ident,token=start("import time;print('RESTART_READY',flush=True);time.sleep(120)")
    cursor=0;output=b'';until(b'RESTART_READY')
    subprocess.run(['sudo','-n','systemctl','restart','agent-os-broker'],check=True)
    deadline=time.monotonic()+10
    while not Path('/run/agent-os-broker/api.sock').exists() and time.monotonic()<deadline:time.sleep(.1)
    state=request('poll',job_id=ident)
    assert state['status']=='interrupted',state
    assert b'RESTART_READY' in state['output'].encode(),state
    assert subprocess.call(['sudo','-n','systemctl','is-active','--quiet','agent-os-exec-'+ident+'.service'])!=0
    print(json.dumps({'result':'pass','checks':['controlling PTY','prompt and Unicode input','SIGWINCH dimensions','detach/reconnect','Ctrl-C foreground signal','input/output beyond saved log cap','activity cancellation','broker restart stops terminal without replay']}))
finally:
    request('stop_activity',activity=activity)
    subprocess.run(['agent-os','remove',str(activity)],check=True,stdout=subprocess.DEVNULL)
