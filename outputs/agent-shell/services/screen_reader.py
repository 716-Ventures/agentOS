"""Explicitly requested, session-owned Orca lifecycle; never replace another reader."""
import os
import json
import socket
from pathlib import Path
import re
import signal
import subprocess
import sys


def require_reader():
    binary=Path('/usr/bin/orca')
    if not binary.is_file():raise ValueError('Screen-reader mode requires the packaged Orca reader')
    version=subprocess.check_output([str(binary),'--version'],text=True,timeout=5).strip()
    match=re.search(r'\b(\d+)\.',version)
    if not match or int(match[1])<51:raise ValueError('Screen-reader mode requires Orca 51 or newer for Wayland without X')
    for name in ('org.gnome.Orca','org.gnome.Orca.KeyboardMonitor'):
        owner=subprocess.check_output(['gdbus','call','--session','--dest','org.freedesktop.DBus',
            '--object-path','/org/freedesktop/DBus','--method','org.freedesktop.DBus.NameHasOwner',name],text=True,timeout=5)
        if owner.strip()=='(true,)':raise ValueError('An Orca reader already owns this session; close it deliberately before starting a separate reader')
    return str(binary)


class Reader:
    def __init__(self,binary):self.binary=binary;self.process=None;self.attempted=False;self.reported=False
    def poll(self,runtime,env,compositor):
        if not self.attempted:
            # The display socket precedes backend/service initialization. Wait
            # for this owned compositor's control socket, created after its
            # accessibility manager, before Orca chooses its keyboard backend.
            if not (Path(runtime)/('agentos-compositor-'+str(compositor)+'.sock')).is_socket():return
            displays=[p for p in Path(runtime).glob('wayland-*') if p.is_socket()]
            if not displays:return
            if len(displays)!=1:raise RuntimeError('Screen reader cannot identify the owned Wayland display')
            self.attempted=True
            reader_env={**env,'WAYLAND_DISPLAY':str(displays[0]),'GTK_A11Y':'atspi'}
            for key in ('WAYLAND_SOCKET','AGENT_OS_TRUSTED_SHELL','LD_PRELOAD','DISPLAY'):reader_env.pop(key,None)
            argv=[self.binary]
            if env.get('AGENT_OS_SCREEN_READER_VERIFY')=='1':argv.append('--debug-file='+str(Path(runtime)/'orca-speech.log'))
            gate_read,gate_write=os.pipe()
            try:
                self.process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--launch-reader',str(gate_read),*argv],env=reader_env,start_new_session=True,pass_fds=(gate_read,))
                os.close(gate_read);gate_read=None
                stat=Path('/proc',str(self.process.pid),'stat').read_text().rsplit(')',1)[1].split()
                request={'op':'screen_reader.register','pid':self.process.pid,'start':stat[19]}
                with socket.socket(socket.AF_UNIX) as connection:
                    connection.settimeout(6);connection.connect(str(Path(runtime)/('agentos-compositor-'+str(compositor)+'.sock')))
                    connection.sendall(json.dumps(request).encode()+b'\n')
                    with connection.makefile('rb') as stream:response=json.loads(stream.readline(65537))
                if not response.get('ok'):raise RuntimeError('Screen reader registration failed: '+str(response.get('error')))
                os.write(gate_write,b'1')
            finally:
                if gate_read is not None:os.close(gate_read)
                os.close(gate_write)
            print('Session-owned screen reader started.',file=sys.stderr,flush=True)

        elif self.process is not None and self.process.poll() is not None and not self.reported:
            self.reported=True
            print('Screen reader stopped (exit '+str(self.process.returncode)+'); desktop controls remain available.',file=sys.stderr,flush=True)
    def close(self):
        if self.process is None:return
        proc=self.process
        if proc.poll() is None:
            try:os.killpg(proc.pid,signal.SIGTERM)
            except ProcessLookupError:pass
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)
        self.process=None


if __name__=='__main__':
    if len(sys.argv)<4 or sys.argv[1]!='--launch-reader':raise SystemExit('Internal session-owned reader launcher')
    gate=int(sys.argv[2])
    try:ready=os.read(gate,1)==b'1'
    finally:os.close(gate)
    if not ready:raise SystemExit(1)
    os.execv(sys.argv[3],sys.argv[3:])
