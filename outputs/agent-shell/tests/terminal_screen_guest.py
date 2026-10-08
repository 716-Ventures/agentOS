#!/usr/bin/python3
"""Render the actual attachment in an independent terminal; assert screen state."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,'/usr/local/lib/agent-os/services')
from broker_client import request

activity=json.loads(subprocess.check_output(['agent-os','create','Screen restoration acceptance']))['id']
ident=None


def wait(check,timeout=10):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=check()
        if value:return value
        time.sleep(.05)
    raise AssertionError('Timed out waiting for terminal state')

try:
    # The static header is drawn once, before far more than 256 KiB of output.
    # Subsequent updates touch only row 5. Raw tail replay cannot recover row 2.
    code=r'''
import os,signal,sys,termios,tty
saved=termios.tcgetattr(0);tty.setraw(0)
def write(data):
 data=data.encode()
 while data:data=data[os.write(1,data):]
def footer(*_):
 size=os.get_terminal_size(0)
 write('\x1b[8;1H\x1b[0mSIZE %dx%d\x1b[K\x1b[4;7H'%(size.columns,size.lines))
try:
 write('\x1b[2J\x1b[2;3HNORMAL_BUFFER')
 write('\x1b[?1049h\x1b[2J\x1b[2;3H\x1b[1;38;5;196mSTATIC_HEADER \u2603 \u754c\x1b[0m')
 write('\x1b[4;1HINPUT:\x1b[?1h\x1b[?25l')
 footer();signal.signal(signal.SIGWINCH,footer)
 while True:
  char=os.read(0,1)
  if char==b'g':
   for i in range(20000):write('\x1b[5;1H\x1b[0mUPDATE %05d\x1b[K'%i)
   write('\x1b[6;1HHEAVY_DONE\x1b[4;7H')
  elif char==b'z':write('\x1b[4;7HZ\x1b[4;8H')
  elif char==b'n':write('\x1b[?1049l\x1b[3;1HNORMAL_ACTIVE\x1b[4;7H')
  elif char==b'q':break
finally:
 termios.tcsetattr(0,termios.TCSANOW,saved)
 write('\x1b[?25h\x1b[?1l\x1b[?1049l')
'''
    job=request('execute',activity=activity,argv=['/usr/bin/python3','-u','-c',code],purpose='Harmless full-screen restoration fixture',
                terminal=True,background=True,lifetime_seconds=180,request_confirmation=True,rows=24,cols=80)
    ident=job['id']
    if job['status']=='approval_required':subprocess.run(['sudo','-n','agent-os-broker','approve',ident],check=True,stdout=subprocess.DEVNULL)
    wait(lambda:request('poll',job_id=ident)['status']=='running')
    with tempfile.TemporaryDirectory(prefix='agent-os-screen-') as tmp:
        socket=str(Path(tmp)/'display.sock')
        def tmux(*args):
            return subprocess.check_output(['tmux','-S',socket,*args],text=True,stderr=subprocess.DEVNULL)
        attach='exec agent-os attach broker:'+ident
        try:
            tmux('-f','/dev/null','new-session','-d','-s','display','-x','80','-y','24',attach)
            tmux('set','-g','remain-on-exit','on');tmux('set','-g','status','off');tmux('set','-g','window-size','manual')
            def screen():return tmux('capture-pane','-p','-t','display:0.0')
            wait(lambda:'STATIC_HEADER' in screen())
            tmux('send-keys','-t','display:0.0','g')
            wait(lambda:request('poll',job_id=ident).get('output_truncated'))
            wait(lambda:'HEAVY_DONE' in screen(),20)
            tmux('send-keys','-t','display:0.0','C-]')
            wait(lambda:tmux('display-message','-p','-t','display:0.0','#{pane_dead}').strip()=='1')
            tmux('respawn-pane','-k','-t','display:0.0',attach)
            wait(lambda:'HEAVY_DONE' in screen())
            rendered=screen().splitlines()
            assert rendered[1].startswith('  STATIC_HEADER \u2603 \u754c'),rendered
            assert 'UPDATE 19999' in rendered[4],rendered
            assert tmux('display-message','-p','-t','display:0.0','#{cursor_x},#{cursor_y},#{cursor_flag}').strip()=='6,3,0'
            styled=tmux('capture-pane','-p','-e','-t','display:0.0')
            assert '\x1b[1m' in styled and ('\x1b[38;5;196m' in styled or '\x1b[91m' in styled),repr(styled)
            tmux('send-keys','-t','display:0.0','z')
            wait(lambda:'INPUT:Z' in screen())
            # A killed attachment cannot run its finally block. The exclusive
            # controller expires; the program and its screen must remain intact.
            pid=int(tmux('display-message','-p','-t','display:0.0','#{pane_pid}').strip())
            os.kill(pid,signal.SIGKILL)
            wait(lambda:tmux('display-message','-p','-t','display:0.0','#{pane_dead}').strip()=='1')
            try:
                request('terminal_attach',job_id=ident)
                raise AssertionError('Disconnected controller lease was not retained')
            except RuntimeError as exc:assert 'controller' in str(exc),exc
            time.sleep(15.5)
            # Resize while no display client is attached, then reconnect without
            # asking the application to repaint its static header.
            tmux('resize-window','-t','display:0','-x','100','-y','30')
            tmux('respawn-pane','-k','-t','display:0.0',attach)
            wait(lambda:'SIZE 100x30' in screen())
            rendered=screen().splitlines()
            assert rendered[1].startswith('  STATIC_HEADER \u2603 \u754c'),rendered
            assert 'INPUT:Z' in rendered[3] and 'UPDATE 19999' in rendered[4],rendered
            tmux('send-keys','-t','display:0.0','n')
            wait(lambda:'NORMAL_ACTIVE' in screen())
            assert 'NORMAL_BUFFER' in screen() and 'STATIC_HEADER' not in screen()
            tmux('send-keys','-t','display:0.0','C-]')
            wait(lambda:tmux('display-message','-p','-t','display:0.0','#{pane_dead}').strip()=='1')
            tmux('respawn-pane','-k','-t','display:0.0',attach)
            wait(lambda:'NORMAL_ACTIVE' in screen())
            assert 'NORMAL_BUFFER' in screen()
            tmux('send-keys','-t','display:0.0','q')
            wait(lambda:request('poll',job_id=ident)['status']=='succeeded')
            # An actual editor retains its unsaved buffer and insertion mode.
            filename=str(Path(tmp)/'editor.txt')
            editor=request('execute',activity=activity,argv=['/usr/bin/vi','-n','-u','NONE','-i','NONE',filename],
                purpose='Harmless editor reconnect fixture',terminal=True,background=True,lifetime_seconds=90,request_confirmation=True)
            if editor['status']=='approval_required':subprocess.run(['sudo','-n','agent-os-broker','approve',editor['id']],check=True,stdout=subprocess.DEVNULL)
            wait(lambda:request('poll',job_id=editor['id'])['status']=='running')
            editor_attach='exec agent-os attach broker:'+editor['id']
            tmux('respawn-pane','-k','-t','display:0.0',editor_attach)
            # vi clears its transient filename message after SIGWINCH.
            wait(lambda:screen().count('\n~')>20)
            tmux('send-keys','-l','-t','display:0.0','iEDITOR_BUFFER')
            wait(lambda:'EDITOR_BUFFER' in screen())
            tmux('send-keys','-t','display:0.0','C-]')
            wait(lambda:tmux('display-message','-p','-t','display:0.0','#{pane_dead}').strip()=='1')
            tmux('resize-window','-t','display:0','-x','90','-y','28')
            tmux('respawn-pane','-k','-t','display:0.0',editor_attach)
            wait(lambda:'EDITOR_BUFFER' in screen())
            tmux('send-keys','-l','-t','display:0.0',' AFTER_RECONNECT')
            wait(lambda:'EDITOR_BUFFER AFTER_RECONNECT' in screen())
            tmux('send-keys','-t','display:0.0','Escape',':wq','Enter')
            wait(lambda:request('poll',job_id=editor['id'])['status']=='succeeded')
            assert subprocess.check_output(['sudo','-n','cat',filename])==b'EDITOR_BUFFER AFTER_RECONNECT\n'
        finally:
            subprocess.run(['tmux','-S',socket,'kill-server'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    # Exit status and exact raw log output must not become display-client status.
    job=request('execute',activity=activity,argv=['/usr/bin/python3','-u','-c',"import os,sys;os.write(1,b'raw-log\\x1b[31m\\n');sys.exit(7)"],
                purpose='Harmless exit-status fixture',terminal=True,background=True,lifetime_seconds=30,request_confirmation=True)
    if job['status']=='approval_required':subprocess.run(['sudo','-n','agent-os-broker','approve',job['id']],check=True,stdout=subprocess.DEVNULL)
    result=wait(lambda:(lambda j:j if j['status'] in ('succeeded','failed') else None)(request('poll',job_id=job['id'])))
    assert result['status']=='failed' and result['exit_code']==7,result
    assert result['output']=='raw-log\x1b[31m\r\n',repr(result['output'])
    print(json.dumps({'result':'pass','checks':['static screen survives >256 KiB','normal and alternate screens','Unicode and color restoration','cursor position and visibility','continued keyboard input','lost connection lease recovery','detached resize and reattach','real command exit status','raw logs remain exact','vi unsaved buffer, insert mode and saved file']}))
finally:
    request('stop_activity',activity=activity)
    subprocess.run(['agent-os','remove',str(activity)],check=True,stdout=subprocess.DEVNULL)
