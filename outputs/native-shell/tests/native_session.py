#!/usr/bin/env python3
"""Exercise the installed session lifecycle with real Linux graphical processes."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'test-output';OUTPUT.mkdir(exist_ok=True)

def wait_for(predicate,children,timeout=20):
    deadline=time.monotonic()+timeout
    while True:
        result=predicate()
        if result:return result
        assert all(p.poll() is None for p in children),'A session process exited; inspect session.log'
        assert time.monotonic()<deadline,'Session lifecycle timed out'
        time.sleep(.05)

def call(path,value):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
        conn.settimeout(2);conn.connect(str(path));conn.sendall(json.dumps(value).encode()+b'\n')
        with conn.makefile('rb') as stream:response=json.loads(stream.readline())
        assert response['ok'],response
        return response['result']

def alive(pid):
    try:
        # Zombies are exited; their parent still owns reaping them.
        return Path(f'/proc/{pid}/stat').read_text().split(') ',1)[1].split()[0]!='Z'
    except FileNotFoundError:return False

def reap(proc):
    if proc.poll() is None:os.killpg(proc.pid,signal.SIGTERM)
    try:proc.wait(timeout=12)
    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)

with tempfile.TemporaryDirectory(prefix='agentos-session-test-') as directory:
    root=Path(directory);runtime=root/'runtime';runtime.mkdir(mode=0o700)
    endpoint=root/'core.sock';bins=root/'bin';bins.mkdir()
    for crate,name in [('native-shell','agent-os-desktop'),('native-compositor','agent-os-compositor')]:
        (bins/name).symlink_to(ROOT.parent/crate/'target/debug'/name)
    env={**os.environ,'HOME':str(root),'XDG_RUNTIME_DIR':str(runtime),'XDG_CONFIG_HOME':str(root/'config'),
         'XDG_STATE_HOME':str(root/'user-state'),'AGENT_OS_STATE':str(root/'core-state'),
         'AGENT_OS_SOCKET':str(endpoint),'AGENT_OS_COMPOSITOR_UID':str(os.getuid()),
         'LIBGL_ALWAYS_SOFTWARE':'1','GSK_RENDERER':'cairo','G_DEBUG':'fatal-criticals'}
    env.pop('WAYLAND_DISPLAY',None);env.pop('DISPLAY',None)
    with (OUTPUT/'session.log').open('w') as log:
        core=subprocess.Popen([str(ROOT.parent/'agent-shell/target/release/agent-os-core')],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        session=None;owned=[]
        try:
            wait_for(endpoint.exists,[core])
            activity=call(endpoint,{'op':'create','name':'Full desktop session'})['id']
            document={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':'session-fixture','activity_id':str(activity),'revision':0,'title':'Session lifecycle','root':'root','elements':{'root':{'type':'Text@1','props':{'text':'Authenticated session fixture'}}},'bindings':{},'actions':{}}
            call(endpoint,{'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'session-fixture','expected_revisions':{'session-fixture':None},'operations':[{'op':'surface.create','document':document}]})
            session=subprocess.Popen(['python3',str(ROOT.parent/'agent-shell/services/desktop_session.py'),'--backend','headless','--pixman','--bin-dir',str(bins),'--socket',str(endpoint)],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            pidfile=wait_for(lambda:next(runtime.glob('agentos-session-*/compositor.pid'),None),[core,session])
            compositor=int(wait_for(lambda:pidfile.read_text().strip(),[core,session]));owned.append(compositor)
            control=runtime/f'agentos-compositor-{compositor}.sock'
            wait_for(control.exists,[core,session])
            state=wait_for(lambda:(lambda s:s if s.get('shared') and 'session-fixture' in s['shared']['identities'].values() else None)(call(control,{'op':'snapshot'})),[core,session])
            assert any(w['app_id'].startswith('agentos.surface.') for w in state['windows']),state
            # Every process in this private runtime is ours. Record identities before teardown.
            for proc in Path('/proc').iterdir():
                if not proc.name.isdigit() or int(proc.name)==core.pid:continue
                try:values=(proc/'environ').read_bytes().split(b'\0')
                except (PermissionError,FileNotFoundError,ProcessLookupError):continue
                if ('XDG_RUNTIME_DIR='+str(runtime)).encode() in values:owned.append(int(proc.name))
            session.terminate();assert session.wait(timeout=15)==0
            remaining=lambda:[pid for pid in owned if alive(pid)]
            try:wait_for(lambda:not remaining(),[core],timeout=5)
            except AssertionError:raise AssertionError('Session processes survived shutdown: '+str({pid:Path(f'/proc/{pid}/cmdline').read_bytes().replace(bytes([0]),b' ') for pid in remaining()}))
            assert not control.exists(),'Compositor socket leaked'
            assert not list(runtime.glob('agentos-session-*')),'Session directory leaked'
            print('PASS: normal native session maps authenticated surfaces and reaps display host, compositor and renderer')
        finally:
            if session:reap(session)
            reap(core)
