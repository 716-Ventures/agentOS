#!/usr/bin/env python3
"""Exercise the installed session lifecycle with real Linux graphical processes."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
SHELL=ROOT.parent if (ROOT.parent/'install_runtime.py').is_file() else ROOT.parent/'agent-shell'
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
         'LIBGL_ALWAYS_SOFTWARE':'1','GSK_RENDERER':'cairo','G_DEBUG':'fatal-criticals','GTK_A11Y':'atspi'}
    env.pop('WAYLAND_DISPLAY',None);env.pop('DISPLAY',None)
    ime='--ime' in sys.argv
    if ime:
        env['AGENT_OS_INPUT_METHOD_ARGV']=json.dumps([str(ROOT.parent/'native-compositor/target/debug/examples/ime_fixture'),str(runtime/'ime-test.sock')])
        env['GTK_IM_MODULE']='wayland'
    host_failure='--host-failure' in sys.argv
    compositor_failure='--compositor-failure' in sys.argv
    with (OUTPUT/('session-compositor-failure.log' if compositor_failure else 'session-host-failure.log' if host_failure else 'session-ime.log' if ime else 'session.log')).open('w') as log:
        core=subprocess.Popen([str(SHELL/'target/release/agent-os-core')],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        session=None;owned=[]
        try:
            wait_for(endpoint.exists,[core])
            activity=call(endpoint,{'op':'create','name':'Full desktop session'})['id']
            document={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':'session-fixture','activity_id':str(activity),'revision':0,'title':'Session lifecycle','root':'root','elements':{'root':{'type':'Stack@1','props':{'spacing':'normal'},'slots':{'children':['reading','field']}},'reading':{'type':'Text@1','props':{'text':'Authenticated session fixture'}},'field':{'type':'TextField@1','props':{'label':'Accessible session draft','value':'Original accessible value'}}},'bindings':{},'actions':{}}
            call(endpoint,{'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'session-fixture','expected_revisions':{'session-fixture':None},'operations':[{'op':'surface.create','document':document}]})
            session=subprocess.Popen(['python3',str(SHELL/'services/desktop_session.py'),'--backend','headless','--pixman','--bin-dir',str(bins),'--socket',str(endpoint)],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            pidfile=wait_for(lambda:next(runtime.glob('agentos-session-*/compositor.pid'),None),[core,session])
            compositor=int(wait_for(lambda:pidfile.read_text().strip(),[core,session]));owned.append(compositor)
            control=pidfile.parent/f'agentos-compositor-{compositor}.sock'
            wait_for(control.exists,[core,session])
            state=wait_for(lambda:(lambda s:s if s.get('shared') and 'session-fixture' in s['shared']['identities'].values() else None)(call(control,{'op':'snapshot'})),[core,session])
            assert any(w['app_id'].startswith('agentos.surface.') for w in state['windows']),state
            if not host_failure and not compositor_failure:
                if ime:
                    import ime_accessibility
                    wait_for(lambda:(runtime/'ime-test.sock').exists(),[core,session])
                    ime_accessibility.verify(lambda value:call(endpoint,value),runtime/'ime-test.sock')
                else:
                    import accessibility
                    accessibility.verify(lambda value:call(endpoint,value))
            # Every process in this private runtime is ours. Record identities before teardown.
            for proc in Path('/proc').iterdir():
                if not proc.name.isdigit() or int(proc.name)==core.pid:continue
                try:values=(proc/'environ').read_bytes().split(b'\0')
                except (PermissionError,FileNotFoundError,ProcessLookupError):continue
                if any(value==('XDG_RUNTIME_DIR='+str(runtime)).encode() or value.startswith(('XDG_RUNTIME_DIR='+str(runtime)+'/agentos-session-').encode()) for value in values):owned.append(int(proc.name))
            if compositor_failure:
                os.kill(compositor,signal.SIGKILL)
            elif host_failure:
                # Simulate display-host loss, rather than the ordinary logout path.
                host=int(Path(f'/proc/{session.pid}/task/{session.pid}/children').read_text().split()[0])
                os.kill(host,signal.SIGTERM)
            else:session.terminate()
            exit_code=session.wait(timeout=20)
            assert exit_code>=0 if compositor_failure else exit_code==0
            remaining=lambda:[pid for pid in owned if alive(pid)]
            try:wait_for(lambda:not remaining(),[core],timeout=5)
            except AssertionError:raise AssertionError('Session processes survived shutdown: '+str({pid:Path(f'/proc/{pid}/cmdline').read_bytes().replace(bytes([0]),b' ') for pid in remaining()}))
            assert not control.exists(),'Compositor socket leaked'
            assert not list(runtime.glob('agentos-session-*')),'Session directory leaked'
            print('PASS: '+('abrupt compositor loss' if compositor_failure else 'display-host loss' if host_failure else 'normal session')+' maps authenticated surfaces and reaps display host, compositor and renderer')
        finally:
            if session:reap(session)
            for pid in owned:
                try:
                    values=Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
                    if any(value==('XDG_RUNTIME_DIR='+str(runtime)).encode() or value.startswith(('XDG_RUNTIME_DIR='+str(runtime)+'/agentos-session-').encode()) for value in values) and alive(pid):
                        if os.getpgid(pid)==pid:os.killpg(pid,signal.SIGKILL)
                        else:os.kill(pid,signal.SIGKILL)
                except (FileNotFoundError,ProcessLookupError,PermissionError):pass
            reap(core)
