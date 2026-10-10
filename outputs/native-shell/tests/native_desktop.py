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
            subprocess.run([str(ROOT/'target/debug/agent-os-desktop'),'--self-test','--socket',str(endpoint),'--capture',str(OUTPUT/'desktop.png')],env=env,check=True,timeout=30)
        finally:
            if compositor:reap(compositor)
            reap(core)
print('PASS: native test core and private display cleaned up')
