"""Private screen keepers and bounded display transports. Broker lock required."""
import base64
import binascii
import errno
import fcntl
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import struct
import subprocess
import termios
import time
import uuid

LIMIT = 256 * 1024
SESSIONS = {}


def dimensions(rows, cols):
    if type(rows) is not int or type(cols) is not int or not (1 <= rows <= 500 and 1 <= cols <= 1000):
        raise ValueError('Terminal size must be 1–500 rows and 1–1000 columns')
    return struct.pack('HHHH', rows, cols, 0, 0)


def command(job, state):
    """The control client, server, command, and descendants share the unit cgroup."""
    socket = state / (job['id']+'.tmux.sock')
    config = state / (job['id']+'.tmux.conf')
    exit_path = state / (job['id']+'.exit')
    exit_path.unlink(missing_ok=True)
    # No user configuration, multiplexing shortcuts, status bar, or history.
    # Dead panes remain until the broker drains output and collects the real exit.
    config.write_text('\n'.join([
        'set -g status off', 'set -g prefix None', 'unbind-key -a',
        'set -g history-limit 0', 'set -g window-size latest',
        'set -g default-terminal xterm-256color', 'set -g escape-time 10',
        'set -g remain-on-exit on',
        'set-hook -g pane-died '+shlex.quote('run-shell '+shlex.quote(
            "printf '%s:%s' '#{pane_dead_status}' '#{pane_dead_signal}' > "+shlex.quote(str(exit_path)+'.tmp')+
            ' && mv '+shlex.quote(str(exit_path)+'.tmp')+' '+shlex.quote(str(exit_path)))),
    ])+'\n')
    return socket, exit_path, ['/usr/bin/tmux','-u','-C','-S',str(socket),'-f',str(config),
        'new-session','-f','ignore-size','-s','terminal','-x',str(job['cols']),'-y',str(job['rows']),
        'exec '+shlex.join(job['argv'])]


class ControlOutput:
    """Decode tmux's escaped %output records, preserving arbitrary raw bytes."""
    def __init__(self):self.pending=b''
    def feed(self, data):
        self.pending += data
        if len(self.pending)>512*1024:
            raise OSError('Oversized terminal control record')
        lines=self.pending.split(b'\n');self.pending=lines.pop()
        output=[]
        for line in lines:
            if not line.startswith(b'%output '):continue
            parts=line.split(b' ',2)
            if len(parts)!=3:raise OSError('Invalid terminal control output')
            raw=parts[2];decoded=bytearray();index=0
            while index<len(raw):
                if raw[index]==92:
                    octal=raw[index+1:index+4]
                    if len(octal)!=3 or any(c not in b'01234567' for c in octal):
                        raise OSError('Invalid terminal control escape')
                    value=int(octal,8)
                    if value>255:raise OSError('Invalid terminal control byte')
                    decoded.append(value);index+=4
                else:decoded.append(raw[index]);index+=1
            output.append(bytes(decoded))
        return b''.join(output)


def register(ident, proc, socket, rows, cols):
    for key in [k for k,v in SESSIONS.items() if not v['running']][:-31]:
        close_reader(SESSIONS.pop(key))
    SESSIONS[ident]=dict(proc=proc,socket=socket,rows=rows,cols=cols,running=True,
                         reader=None,token=None,expires=0)


def close_reader(session):
    reader=session.get('reader')
    if not reader:return
    session['reader']=None
    if reader['fd'] is not None:os.close(reader['fd']);reader['fd']=None
    proc=reader['proc']
    if proc.poll() is None:proc.terminate()
    try:proc.wait(timeout=1)
    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=1)


def open_reader(session):
    deadline=time.monotonic()+2
    while subprocess.run(['/usr/bin/tmux','-S',str(session['socket']),'has-session','-t','terminal'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=1).returncode:
        if time.monotonic()>=deadline:raise ValueError('Terminal screen is not ready; retry attachment')
        time.sleep(.02)
    master,slave=pty.openpty()
    try:
        fcntl.ioctl(slave,termios.TIOCSWINSZ,dimensions(session['rows'],session['cols']))
        proc=subprocess.Popen(['/usr/bin/tmux','-u','-S',str(session['socket']),
            'attach-session','-t','terminal'],stdin=slave,stdout=slave,stderr=slave,
            start_new_session=True,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','TERM':'xterm-256color'})
    except BaseException:
        os.close(master);raise
    finally:os.close(slave)
    os.set_blocking(master,False)
    return dict(fd=master,proc=proc,data=b'',end=0,closed=False)


def append(reader,data):
    reader['data']=(reader['data']+data)[-LIMIT:];reader['end']+=len(data)


def pump(reader):
    if reader['fd'] is None:return
    if not select.select([reader['fd']],[],[],0)[0]:return
    try:data=os.read(reader['fd'],16384)
    except BlockingIOError:return
    except OSError as exc:
        if exc.errno!=errno.EIO:raise
        data=b''
    if data:append(reader,data)
    else:
        os.close(reader['fd']);reader['fd']=None;reader['closed']=True
        reader['proc'].wait(timeout=1)


def reap_expired():
    now=time.monotonic()
    for session in SESSIONS.values():
        if session['token'] and session['expires']<=now:
            close_reader(session);session.update(token=None,expires=0)


def finish(ident):
    session=SESSIONS.get(ident)
    if session:session['running']=False
    for key in [k for k,v in SESSIONS.items() if not v['running']][:-32]:
        close_reader(SESSIONS.pop(key))


def control(ident, req):
    session=SESSIONS.get(ident)
    if session is None:raise ValueError('Terminal transport is unavailable; inspect the saved job output')
    now=time.monotonic();op=req['op']
    if op=='terminal_attach':
        if session['token'] and session['expires']>now:
            raise ValueError('This terminal already has an input controller; detach it or wait 15 seconds after disconnect')
        if not session['running']:raise ValueError('Terminal has exited; inspect its saved job output')
        rows=req.get('rows',session['rows']);cols=req.get('cols',session['cols']);dimensions(rows,cols)
        close_reader(session);session.update(rows=rows,cols=cols)
        session['reader']=open_reader(session)
        session.update(token=uuid.uuid4().hex,expires=time.monotonic()+15)
        return {'token':session['token'],'cursor':0,'screen_restored':True}
    if not session['token'] or req.get('token')!=session['token'] or session['expires']<=now:
        raise ValueError('Terminal attachment expired; attach again')
    session['expires']=now+15
    if op=='terminal_detach':
        close_reader(session);session.update(token=None,expires=0)
        return {'detached':True}
    reader=session['reader']
    if op=='terminal_read':
        cursor=req.get('cursor',0)
        if type(cursor) is not int or not 0<=cursor<=reader['end']:raise ValueError('Invalid terminal cursor')
        pump(reader)
        base=reader['end']-len(reader['data'])
        reset=cursor<base
        if reset:
            # Never begin in the middle of UTF-8 or an escape sequence. A fresh
            # client emits a complete screen instead of replaying a broken tail.
            if not session['running']:raise ValueError('Display fell behind after terminal exit; inspect saved output')
            close_reader(session);session['reader']=reader=open_reader(session)
            cursor=base=0;pump(reader)
        data=reader['data'][cursor-base:cursor-base+16384]
        return dict(data=base64.b64encode(data).decode(),cursor=cursor+len(data),
                    reset=reset,dropped=False,closed=reader['closed'])
    if not session['running'] or reader['fd'] is None:raise ValueError('Terminal has exited')
    if op=='terminal_resize':
        rows=req.get('rows');cols=req.get('cols');size=dimensions(rows,cols)
        fcntl.ioctl(reader['fd'],termios.TIOCSWINSZ,size)
        os.kill(reader['proc'].pid,signal.SIGWINCH)
        session.update(rows=rows,cols=cols)
        return {'resized':True}
    if op=='terminal_write':
        try:
            encoded=req.get('data')
            if not isinstance(encoded,str) or len(encoded)>5500:raise ValueError('Terminal input exceeds 4096 bytes')
            data=base64.b64decode(encoded,validate=True)
            if len(data)>4096:raise ValueError('Terminal input exceeds 4096 bytes')
        except (binascii.Error,UnicodeError):raise ValueError('Terminal input must be base64') from None
        try:written=os.write(reader['fd'],data)
        except BlockingIOError:written=0
        return {'written':written}
    raise ValueError('Unknown terminal operation')
