#!/usr/bin/env python3
"""Real core, validated documents, GTK/Wayland renderer; all children reaped."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
import sys

ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT.parent/'agent-shell/target/release/agent-os-core'
OUTPUT=ROOT/'test-output'
OUTPUT.mkdir(exist_ok=True)

def reap(proc):
    if proc.poll() is None:os.killpg(proc.pid,signal.SIGTERM)
    try:proc.wait(timeout=5)
    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)

with tempfile.TemporaryDirectory(prefix='agentos-native-') as directory:
    runtime=Path(directory);endpoint=runtime/'core.sock'
    env={**os.environ,'XDG_RUNTIME_DIR':directory,'WAYLAND_DISPLAY':'native-test','GDK_BACKEND':'wayland','GSK_RENDERER':'cairo','GTK_A11Y':'atspi','G_DEBUG':'fatal-criticals','AGENT_OS_STATE':str(runtime/'state'),'AGENT_OS_SOCKET':str(endpoint)}
    def call(value):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.settimeout(5);conn.connect(str(endpoint));conn.sendall(json.dumps(value).encode()+b'\n')
            with conn.makefile('rb') as stream:response=json.loads(stream.readline())
            assert response['ok'],response
            return response['result']
    with (OUTPUT/'core.log').open('w') as corelog,(OUTPUT/'weston.log').open('w') as displaylog:
        core=subprocess.Popen([str(CORE)],env=env,stdout=corelog,stderr=subprocess.STDOUT,start_new_session=True)
        compositor=None
        nested=None
        applications=[]
        try:
            deadline=time.monotonic()+10
            while not endpoint.exists():
                assert core.poll() is None,'Core exited'
                assert time.monotonic()<deadline,'Core startup timeout'
                time.sleep(.05)
            activity=call({'op':'create','name':'Native renderer fixture'})['id']
            job=call({'op':'run','activity_id':activity,'argv':['/bin/true']})['id']
            doc={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':'native-fixture','activity_id':str(activity),'revision':0,'title':'Native presentation fixture','root':'root','elements':{
                'root':{'type':'Stack@1','props':{'spacing':'relaxed'},'slots':{'children':['reading','field','status','button','link','progress']}},
                'reading':{'type':'Text@1','props':{'text':'Native café · 日本語 · select this text'}},
                'field':{'type':'TextField@1','props':{'label':'Editable local draft','value':'Original draft'}},
                'status':{'type':'Status@1','props':{'value':{'binding':'work'}}},
                'button':{'type':'Button@1','props':{'label':'Host action'}},
                'link':{'type':'Link@1','props':{'label':'716 UI','url':'https://github.com/716-Ventures/716-ui'}},
                'progress':{'type':'Progress@1','props':{'label':'Observed work','value':.5}},
            },'bindings':{'work':{'source':f'job:{job}','path':'/status','access':'read'}},'actions':{}}
            call({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'fixture','expected_revisions':{'native-fixture':None},'operations':[{'op':'surface.create','document':doc}]})
            compositor=subprocess.Popen(['weston','--backend=headless-backend.so','--use-pixman','--socket=native-test','--idle-time=0','--width=1280','--height=800'],env=env,stdout=displaylog,stderr=subprocess.STDOUT,start_new_session=True)
            deadline=time.monotonic()+10
            while not (runtime/'native-test').exists():
                assert compositor.poll() is None,'Display exited'
                assert time.monotonic()<deadline,'Display startup timeout'
                time.sleep(.05)
            command=[str(ROOT/'target/debug/agent-os-desktop'),'--self-test','--socket',str(endpoint),'--capture',str(OUTPUT/'desktop.png')]
            if '--compositor' not in sys.argv:subprocess.run(command,env=env,check=True,timeout=30)
            else:
                with (OUTPUT/'compositor.log').open('w') as nestedlog:
                    nested=subprocess.Popen([str(ROOT.parent/'native-compositor/target/debug/agent-os-compositor')],env={**env,'LIBGL_ALWAYS_SOFTWARE':'1','WINIT_UNIX_BACKEND':'wayland'},stdout=nestedlog,stderr=subprocess.STDOUT,start_new_session=True)
                    control=runtime/f'agentos-compositor-{nested.pid}.sock'
                    deadline=time.monotonic()+20
                    while not control.exists():
                        assert nested.poll() is None,'Native compositor exited; inspect compositor.log'
                        assert time.monotonic()<deadline,'Native compositor startup timed out'
                        time.sleep(.05)
                    displays=[p.name for p in runtime.glob('wayland-*') if p.is_socket()]
                    assert len(displays)==1,displays
                    childenv={**env,'WAYLAND_DISPLAY':displays[0],'AGENT_OS_NATIVE_TEST_DELAY_MS':'3000'}
                    def control_call(value):
                        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
                            conn.settimeout(3);conn.connect(str(control));conn.sendall(json.dumps(value).encode()+b'\n')
                            with conn.makefile('rb') as stream:return json.loads(stream.readline())
                    def snapshot():return control_call({'op':'snapshot'})['result']
                    def wait_windows(count):
                        deadline=time.monotonic()+10
                        while True:
                            state=snapshot()
                            if len(state['windows'])>=count:return state
                            assert time.monotonic()<deadline,state
                            time.sleep(.02)
                    simple=subprocess.Popen(['weston-simple-shm'],env=childenv,stdout=nestedlog,stderr=subprocess.STDOUT,start_new_session=True);applications.append(simple)
                    state=wait_windows(1);ident=state['windows'][0]['id']
                    assert control_call({'op':'focus','id':ident,'expected_revision':state['layout']['revision']})['ok']
                    desktop=subprocess.Popen(command,env=childenv,stdout=None,stderr=None,start_new_session=True);applications.append(desktop)
                    state=wait_windows(2);assert state['layout']['focus']==ident,'A new native surface stole focus'
                    simple2=subprocess.Popen(['weston-simple-shm'],env=childenv,stdout=nestedlog,stderr=subprocess.STDOUT,start_new_session=True);applications.append(simple2)
                    state=wait_windows(3);assert state['layout']['focus']==ident,'A conventional app stole focus'
                    revision=state['layout']['revision']
                    assert not control_call({'op':'place','id':ident,'expected_revision':revision-1,'placement':{'mode':'maximized'}})['ok']
                    assert control_call({'op':'place','id':ident,'expected_revision':revision,'placement':{'mode':'floating','rect':{'x':100,'y':80,'width':320,'height':240}}})['ok']
                    state=snapshot();assert state['layout']['placements'][ident]['mode']=='floating'
                    assert control_call({'op':'undo','expected_revision':state['layout']['revision']})['ok']
                    state=snapshot();assert state['layout']['placements'][ident]['mode']=='tiled'
                    assert control_call({'op':'place','id':ident,'expected_revision':state['layout']['revision'],'placement':{'mode':'maximized'}})['ok']
                    assert desktop.wait(timeout=30)==0
                    print('PASS: agentOS Wayland compositor renders native and conventional apps, exact revisions, float/maximize/undo, no focus stealing')
                    assert control_call({'op':'shutdown'})['ok'];nested.wait(timeout=10)

        finally:
            for application in applications:reap(application)
            if nested:reap(nested)
            if compositor:reap(compositor)
            reap(core)
print('PASS: native test core and private display cleaned up')
