#!/usr/bin/env python3
"""Exercise real curses controls over SSH using only the Python standard library."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import termios
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'vm-foundation'))
import vm

def guest(code):
    return json.loads(subprocess.check_output(vm.ssh_args()+['python3 -'],input=code.encode()))
fixture=guest('''
import json,sys,subprocess
from pathlib import Path
sys.path.insert(0,'/usr/local/lib/agent-os/services')
from broker_client import request
activity=json.loads(subprocess.check_output(['agent-os','create','Terminal lifecycle fixture']))['id']
selection=Path.home()/'.local/state/agent-os/selection.json'
old=selection.read_text() if selection.exists() else None
selection.parent.mkdir(parents=True,exist_ok=True);selection.write_text(json.dumps({'activity_id':activity}))
job=request('execute',activity=activity,argv=['/usr/bin/python3','-u','-c','import time; print("Visible broker fixture",flush=True); time.sleep(120)'],purpose='Harmless terminal fixture',background=True,lifetime_seconds=120,request_confirmation=True)
if job['status']=='approval_required':subprocess.run(['sudo','-n','agent-os-broker','approve',job['id']],check=True,stdout=subprocess.DEVNULL)
print(json.dumps({'activity':activity,'job':job['id'],'old_selection':old}))
''')
master,slave=pty.openpty();process=None
fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',40,140,0,0))

def pump(seconds=1):
    output=b'';deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if select.select([master],[],[],.1)[0]:
            try:output+=os.read(master,65536)
            except OSError:break
    return output

def keys(value,seconds=1):os.write(master,value.encode());return pump(seconds)
try:
    args=vm.ssh_args();process=subprocess.Popen(args[:-1]+['-tt']+args[-1:]+['exec env TERM=xterm-256color agent-os'],stdin=slave,stdout=slave,stderr=slave)
    pump(1.5)
    picker=keys('o');assert b'broker:' in picker,picker.decode(errors='replace')
    output=keys('\n',1.5);assert b'Visible broker fixture' in output,output.decode(errors='replace')
    keys('x',1.5)
    state=guest("import json,sys; sys.path.insert(0,'/usr/local/lib/agent-os/services'); from broker_client import request; print(json.dumps(request('poll',job_id="+repr(fixture['job'])+")))")
    assert state['status']=='cancelled',state
    confirmation=keys('Y');assert b'Stop all work in this activity?' in confirmation
    keys('j\n',1.5)
    keys('q');process.wait(timeout=10)
    print(json.dumps({'result':'pass','checks':['Real picker binds broker output','x cancels selected broker job','Y activity-stop confirmation and completion']}))
finally:
    if process and process.poll() is None:
        process.terminate()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:process.kill();process.wait()
    os.close(master);os.close(slave)
    guest("import json,subprocess; from pathlib import Path; subprocess.run(['agent-os','stop-activity',"+repr(str(fixture['activity']))+"],check=True,stdout=subprocess.DEVNULL); p=Path.home()/'.local/state/agent-os/selection.json'; old="+repr(fixture['old_selection'])+"; p.write_text(old) if old is not None else p.unlink(missing_ok=True); print('{}')")
