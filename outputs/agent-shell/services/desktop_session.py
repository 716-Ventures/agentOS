#!/usr/bin/python3
"""Own a graphical login's Weston display host and agentOS desktop lifecycle."""
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


def child_command(bin_dir,core):
    compositor=bin_dir/'agent-os-compositor';desktop=bin_dir/'agent-os-desktop'
    if any(not path.is_absolute() or not path.is_file() or not os.access(path,os.X_OK) for path in (compositor,desktop)):
        raise ValueError('The graphical runtime is not installed')
    return [str(compositor),'--command',str(desktop),'--socket',str(core)]


def configuration(child,backend):
    if '\n' in str(child) or '\r' in str(child):raise ValueError('Invalid session path')
    return ('[core]\nbackend='+backend+'\nshell=kiosk-shell.so\nidle-time=0\nxwayland=false\n'+
            '[autolaunch]\npath='+str(child)+'\nwatch=true\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['drm','wayland','headless'],default='drm',help='Headless/Wayland modes are for explicit verification')
    parser.add_argument('--bin-dir',type=Path,default=Path('/usr/local/bin'))
    parser.add_argument('--socket',type=Path,default=Path('/run/agent-os/runtime.sock'))
    parser.add_argument('--pixman',action='store_true')
    args=parser.parse_args();runtime=runtime_directory();command=child_command(args.bin_dir,args.socket)
    env={**os.environ,'XDG_SESSION_TYPE':'wayland','XDG_CURRENT_DESKTOP':'agentOS','DESKTOP_SESSION':'agent-os',
         'AGENT_OS_COMPOSITOR_CORE':str(args.socket),'WINIT_UNIX_BACKEND':'wayland','GDK_BACKEND':'wayland'}
    stopped=False
    def stop(_signum,_frame):
        nonlocal stopped
        stopped=True
    previous={sig:signal.signal(sig,stop) for sig in (signal.SIGINT,signal.SIGTERM)}
    proc=None
    try:
        with tempfile.TemporaryDirectory(prefix='agentos-session-',dir=runtime) as directory:
            root=Path(directory);child=root/'desktop-child';pidfile=root/'compositor.pid'
            script = "#!/bin/sh\nprintf '%s\\n' \"$$\" > " + shlex.quote(str(pidfile)) + "\nexec " + shlex.join(command) + "\n"
            child.write_text(script);child.chmod(0o700)
            config=root/'weston.ini';config.write_text(configuration(child,args.backend))
            argv=['weston','--config='+str(config),'--socket=agentos-host-'+str(os.getpid())]
            if args.pixman:argv.append('--use-pixman')
            if args.backend=='headless':argv.extend(['--width=1280','--height=800'])
            proc=subprocess.Popen(argv,env=env,start_new_session=True)
            while proc.poll() is None and not stopped:time.sleep(.05)
            # Weston may also exit unexpectedly. Stop the recorded compositor first;
            # its renderer has a separate process group and must be reaped by it.
            try:
                ident=int(pidfile.read_text().strip())
                if os.getpgid(ident)!=proc.pid:raise ValueError('Compositor ownership changed')
                path=runtime/f'agentos-compositor-{ident}.sock'
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
                    conn.settimeout(.3);conn.connect(str(path));conn.sendall(json.dumps({'op':'shutdown'}).encode()+b'\n');conn.recv(4096)
            except (OSError,ValueError):pass
            if proc.poll() is None:
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGTERM)
            try:return proc.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);return proc.wait(timeout=5)
    finally:
        if proc and proc.poll() is None:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)
        for sig,handler in previous.items():signal.signal(sig,handler)


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError) as exc:raise SystemExit('Desktop session: '+str(exc))
