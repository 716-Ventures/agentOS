#!/usr/bin/python3
"""Own an agentOS graphical login and its display/compositor lifecycle."""
import argparse
import json
import socket
import os
from pathlib import Path
import shlex
import signal
import stat
import subprocess
import tempfile
import time


def runtime_directory():
    if os.getuid()<1000:raise ValueError('Start the desktop from a normal local user login')
    runtime=Path(os.environ.get('XDG_RUNTIME_DIR',''))
    if not runtime.is_absolute():raise ValueError('A local graphical login with XDG_RUNTIME_DIR is required')
    info=runtime.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:
        raise ValueError('XDG_RUNTIME_DIR must be a private directory owned by the login user')
    return runtime


def child_command(bin_dir,core,activity=None):
    compositor=bin_dir/'agent-os-compositor';desktop=bin_dir/'agent-os-desktop'
    if any(not path.is_absolute() or not path.is_file() or not os.access(path,os.X_OK) for path in (compositor,desktop)):
        raise ValueError('The graphical runtime is not installed')
    command=[str(compositor),'--command',str(desktop),'--socket',str(core)]
    if activity is not None:
        if type(activity) is not int or activity<1:raise ValueError('Choose a positive activity ID')
        command.extend(['--activity',str(activity)])
    return command


def configuration(child,backend):
    if '\n' in str(child) or '\r' in str(child):raise ValueError('Invalid session path')
    return ('[core]\nbackend='+backend+'\nshell=kiosk-shell.so\nidle-time=0\nxwayland=false\n'+
            '[autolaunch]\npath='+str(child)+'\nwatch=true\n')


def process_identity(pid):
    try:
        root=Path('/proc')/str(pid);fields=(root/'stat').read_text().rsplit(')',1)[1].split()
        return (fields[19],int(fields[1]),root.stat().st_uid,(root/'exe').resolve()) if fields[0]!='Z' else None
    except (OSError,ValueError,IndexError):return None


def stop_compositor(runtime,owned):
    if not owned:return
    ident,identity=owned
    current=process_identity(ident)
    if current is None or current[0]!=identity[0]:return
    path=runtime/f'agentos-compositor-{ident}.sock'
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.settimeout(.3);conn.connect(str(path));conn.sendall(json.dumps({'op':'shutdown'}).encode()+b'\n');conn.recv(4096)
    except OSError:
        try:os.kill(ident,signal.SIGTERM)
        except ProcessLookupError:return
    deadline=time.monotonic()+5
    while process_identity(ident) is not None and time.monotonic()<deadline:time.sleep(.05)
    if process_identity(ident) is not None:
        os.kill(ident,signal.SIGTERM)
        deadline=time.monotonic()+5
        while process_identity(ident) is not None and time.monotonic()<deadline:time.sleep(.05)
    if process_identity(ident) is not None:raise RuntimeError('Owned compositor failed to stop')

def enable_subreaper():
    # Adopt renderer grandchildren after compositor/display-host failure so this
    # login can reap them instead of leaving cleanup to the system init process.
    import ctypes
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(36,1,0,0,0)!=0:raise OSError(ctypes.get_errno(),'Cannot establish session child ownership')


def reap_session_children():
    children=Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children')
    try:pids=[int(p) for p in children.read_text().split()]
    except FileNotFoundError:return
    pending=[]
    for pid in pids:
        try:
            waited,_=os.waitpid(pid,os.WNOHANG)
            if waited:continue
            identity=process_identity(pid)
            if identity and identity[1]==os.getpid() and identity[2]==os.getuid():
                group=os.getpgid(pid)==pid
                (os.killpg if group else os.kill)(pid,signal.SIGTERM)
                pending.append((pid,group))
        except (ChildProcessError,ProcessLookupError):pass
    deadline=time.monotonic()+3
    while pending and time.monotonic()<deadline:
        remaining=[]
        for pid,group in pending:
            try:
                waited,_=os.waitpid(pid,os.WNOHANG)
                if not waited:remaining.append((pid,group))
            except ChildProcessError:pass
        pending=remaining
        if pending:time.sleep(.05)
    for pid,group in pending:
        try:
            # An unreaped child keeps its PID reserved, including after exit.
            (os.killpg if group else os.kill)(pid,signal.SIGKILL)
            os.waitpid(pid,0)
        except (ChildProcessError,ProcessLookupError):pass


def direct_session(command,env,runtime,stopped):
    """Own the direct compositor; its renderer remains the compositor's child."""
    proc=None;owned=None
    try:
        proc=subprocess.Popen(command,env={**env,'AGENT_OS_COMPOSITOR_BACKEND':'drm'},start_new_session=True)
        identity=process_identity(proc.pid)
        if identity and identity[1]==os.getpid() and identity[2]==os.getuid() and identity[3]==Path(command[0]).resolve():
            owned=(proc.pid,identity)
        while proc.poll() is None and not stopped():time.sleep(.05)
        stop_compositor(runtime,owned)
        try:return proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGTERM)
            try:return proc.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);return proc.wait(timeout=5)
    finally:
        try:stop_compositor(runtime,owned)
        finally:
            if proc and proc.poll() is None:
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['drm','wayland','headless','direct'],default='drm',help='drm uses the Weston host; direct is experimental KMS; headless/wayland are explicit verification modes')
    parser.add_argument('--bin-dir',type=Path,default=Path('/usr/local/bin'))
    parser.add_argument('--socket',type=Path,default=Path('/run/agent-os/runtime.sock'))
    parser.add_argument('--activity',type=int,help='Open this existing activity in the graphical session')
    parser.add_argument('--pixman',action='store_true')
    args=parser.parse_args()
    if args.backend=='direct' and args.pixman:raise ValueError('The direct backend requires GBM/GLES; pixman is a Weston host option')
    runtime=runtime_directory();command=child_command(args.bin_dir,args.socket,args.activity)
    enable_subreaper()
    env={**os.environ,'XDG_SESSION_TYPE':'wayland','XDG_CURRENT_DESKTOP':'agentOS','DESKTOP_SESSION':'agent-os',
         'AGENT_OS_COMPOSITOR_CORE':str(args.socket),'AGENT_OS_COMPOSITOR_BACKEND':'winit','WINIT_UNIX_BACKEND':'wayland','GDK_BACKEND':'wayland'}
    stopped=False
    def stop(_signum,_frame):
        nonlocal stopped
        stopped=True
    previous={sig:signal.signal(sig,stop) for sig in (signal.SIGINT,signal.SIGTERM)}
    proc=None;owned=None;display_runtime=runtime
    try:
        with tempfile.TemporaryDirectory(prefix='agentos-session-',dir=runtime) as directory:
            root=Path(directory);display_runtime=root;env['XDG_RUNTIME_DIR']=str(root)
            if args.backend=='direct':return direct_session(command,env,root,lambda:stopped)
            child=root/'desktop-child';pidfile=root/'compositor.pid'
            script = "#!/bin/sh\nprintf '%s\\n' \"$$\" > " + shlex.quote(str(pidfile)) + "\nexec " + shlex.join(command) + "\n"
            child.write_text(script);child.chmod(0o700)
            config=root/'weston.ini';config.write_text(configuration(child,args.backend))
            argv=['weston','--config='+str(config),'--socket=agentos-host-'+str(os.getpid())]
            if args.pixman:argv.append('--use-pixman')
            if args.backend=='headless':argv.extend(['--width=1280','--height=800'])
            proc=subprocess.Popen(argv,env=env,start_new_session=True)
            while proc.poll() is None and not stopped:
                if owned is None and pidfile.exists():
                    try:
                        ident=int(pidfile.read_text().strip());identity=process_identity(ident)
                        if identity and identity[1]==proc.pid and identity[2]==os.getuid() and identity[3]==Path(command[0]).resolve():owned=(ident,identity)
                    except (OSError,ValueError):pass
                time.sleep(.05)
            # Weston starts autolaunched clients in separate process groups. Bind
            # ownership to its direct child and Linux start identity, not its pgid.
            stop_compositor(display_runtime,owned)
            if proc.poll() is None:
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGTERM)
            try:return proc.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);return proc.wait(timeout=5)
    finally:
        try:stop_compositor(display_runtime,owned)
        finally:
            if proc and proc.poll() is None:
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)
            reap_session_children()
            for sig,handler in previous.items():signal.signal(sig,handler)



if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError) as exc:raise SystemExit('Desktop session: '+str(exc))
