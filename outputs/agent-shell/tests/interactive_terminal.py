#!/usr/bin/env python3
"""Real SSH terminal and curses dashboard attachment, with deterministic fixtures."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import shlex
import struct
import subprocess
import sys
import termios
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'vm-foundation'))
import vm


def guest(code):
    return json.loads(subprocess.check_output(vm.ssh_args()+['python3 -'],input=code.encode(),timeout=20))

fixture=guest('''
import json,subprocess
from pathlib import Path
activity=json.loads(subprocess.check_output(['agent-os','create','Interactive terminal fixture']))['id']
p=Path.home()/'.local/state/agent-os/selection.json'
old=p.read_text() if p.exists() else None
p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'activity_id':activity}))
print(json.dumps({'activity':activity,'old_selection':old}))
''')
master,slave=pty.openpty();process=None
fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',40,140,0,0))


def pump(seconds=1):
    output=b'';deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if select.select([master],[],[],.05)[0]:
            try:output+=os.read(master,65536)
            except OSError:break
    return output


def keys(value,seconds=1):os.write(master,value.encode());return pump(seconds)


def observed(marker, initial=b'', seconds=10):
    output=initial;deadline=time.monotonic()+seconds
    while marker not in output:
        assert process is not None and process.poll() is None,'Terminal client exited before expected state'
        assert time.monotonic()<deadline,(marker,output[-8000:])
        output=(output+pump(.1))[-262144:]
    return output


def spawn(command):
    args=vm.ssh_args()
    return subprocess.Popen(args[:-1]+['-tt']+args[-1:]+['exec env TERM=xterm-256color '+command],stdin=slave,stdout=slave,stderr=slave)

try:
    process=spawn('agent-os');observed(b'Connected')
    code="import os,signal,time;signal.signal(signal.SIGWINCH,lambda *_:print('SCREEN_SIZE',os.get_terminal_size(),flush=True));print('PTY_UI_READY',flush=True);name=input('Who? ');print('WELCOME',name,flush=True);time.sleep(120)"
    command=shlex.join(['/usr/bin/python3','-u','-c',code])
    keys('R',.1);keys(command+'\n',.1)
    # Observe command submission before sending a shortcut. Long pasted text
    # must never turn the following shortcut into part of the command.
    guest("import json,sys,time;sys.path.insert(0,'/usr/local/lib/agent-os/services');from broker_client import request;end=time.monotonic()+10\nwhile not request('list',activity="+str(fixture['activity'])+"):\n assert time.monotonic()<end,'Command submission timed out'\n time.sleep(.05)\nprint('{}')")
    approval=observed(b'Allow interactive root input',keys('I',.1))
    keys('j\n',.5)
    output=observed(b'Who?',keys('I',.1));assert b'PTY_UI_READY' in output,output
    output=observed(b'WELCOME Grace',keys('Grace\n',.1))
    fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',33,111,0,0))
    os.kill(process.pid,signal.SIGWINCH)
    output=pump(1);assert b'columns=111' in output and b'lines=33' in output,output
    output=keys('\x1d',.5);assert b'Terminal detached' in output,output
    row=guest("import json,sys;sys.path.insert(0,'/usr/local/lib/agent-os/services');from broker_client import request;print(json.dumps(request('list',activity="+str(fixture['activity'])+")[0]))")
    assert row['status']=='running',row
    keys('q');process.wait(timeout=5)
    process=spawn('agent-os attach broker:'+row['id'])
    output=observed(b'WELCOME Grace')
    keys('\x1d');assert process.wait(timeout=5)==0
    # A full-screen curses application receives function/navigation keys and
    # redraws using the terminal's native emulator rather than plain-text tiles.
    full="""import curses

def main(s):
 s.addstr(1,2,'FULL_SCREEN_READY');s.refresh()
 while True:
  key=s.getkey()
  if key!='KEY_RESIZE':break
 s.addstr(2,2,'KEY:'+key);s.refresh()
 while s.getkey()=='KEY_RESIZE':pass
curses.wrapper(main)
"""
    row=guest("import json,subprocess,sys;sys.path.insert(0,'/usr/local/lib/agent-os/services');from broker_client import request;j=request('execute',activity="+str(fixture['activity'])+",argv=['/usr/bin/python3','-u','-c',"+repr(full)+"],purpose='Full screen terminal fixture',terminal=True,background=True,lifetime_seconds=120,request_confirmation=True);subprocess.run(['sudo','-n','agent-os-broker','approve',j['id']],check=True,stdout=subprocess.DEVNULL) if j['status']=='approval_required' else None;print(json.dumps(j))")
    time.sleep(.2)
    process=spawn('agent-os attach broker:'+row['id']);output=observed(b'FULL_SCREEN_READY')
    output=keys('\x1bOB');assert b'KEY:KEY_DOWN' in output,output
    keys('q');assert process.wait(timeout=5)==0
    print(json.dumps({'result':'pass','checks':['dashboard R starts proposal','I reviews explicit root terminal approval','I attaches and sends input','SSH window resize','Ctrl-] returns to working dashboard','CLI reconnect preserves running command','full screen curses and arrow keys']}))
finally:
    if process and process.poll() is None:
        process.terminate()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:process.kill();process.wait()
    os.close(master);os.close(slave)
    guest("import json,subprocess;from pathlib import Path;subprocess.run(['agent-os','stop-activity',"+repr(str(fixture['activity']))+"],check=True,stdout=subprocess.DEVNULL);subprocess.run(['agent-os','remove',"+repr(str(fixture['activity']))+"],check=True,stdout=subprocess.DEVNULL);p=Path.home()/'.local/state/agent-os/selection.json';old="+repr(fixture['old_selection'])+";p.write_text(old) if old is not None else p.unlink(missing_ok=True);print('{}')")
