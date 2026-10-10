#!/usr/bin/env python3
"""Real core, validated documents, GTK/Wayland renderer; all children reaped."""
import copy
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
    shared='--shared' in sys.argv
    env={**os.environ,'AGENT_OS_COMPOSITOR_UID':str(os.getuid()),'XDG_RUNTIME_DIR':directory,'WAYLAND_DISPLAY':'native-test','GDK_BACKEND':'wayland','GSK_RENDERER':'cairo','GTK_A11Y':'atspi','G_DEBUG':'fatal-criticals','AGENT_OS_STATE':str(runtime/'state'),'AGENT_OS_SOCKET':str(endpoint)}
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
            deadline=time.monotonic()+5
            while next(j for j in call({'op':'snapshot'})['jobs'] if j['id']==job)['status'] not in ('succeeded','failed'):
                assert time.monotonic()<deadline,'Fixture job did not finish'
                time.sleep(.02)
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
                    nested=subprocess.Popen([str(ROOT.parent/'native-compositor/target/debug/agent-os-compositor')],env={**env,**({'AGENT_OS_COMPOSITOR_CORE':str(endpoint)} if shared else {}),'LIBGL_ALWAYS_SOFTWARE':'1','WINIT_UNIX_BACKEND':'wayland'},stdout=nestedlog,stderr=subprocess.STDOUT,start_new_session=True)
                    control=runtime/f'agentos-compositor-{nested.pid}.sock'
                    deadline=time.monotonic()+20
                    while not control.exists():
                        assert nested.poll() is None,'Native compositor exited; inspect compositor.log'
                        assert time.monotonic()<deadline,'Native compositor startup timed out'
                        time.sleep(.05)
                    displays=[p.name for p in runtime.glob('wayland-*') if p.is_socket()]
                    assert len(displays)==1,displays
                    childenv={**env,'WAYLAND_DISPLAY':displays[0],'AGENT_OS_NATIVE_TEST_DELAY_MS':('10000' if shared else '3000')}
                    def control_call(value):
                        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
                            conn.settimeout(3);conn.connect(str(control));conn.sendall(json.dumps(value).encode()+b'\n')
                            with conn.makefile('rb') as stream:return json.loads(stream.readline())
                    def snapshot():return control_call({'op':'snapshot'})['result']
                    def wait_windows(count):
                        deadline=time.monotonic()+10
                        while True:
                            state=snapshot()
                            if len(state['windows'])>=count and len(state['layout']['order'])>=count:return state
                            assert time.monotonic()<deadline,state
                            time.sleep(.02)
                    simple=subprocess.Popen(['weston-simple-shm'],env=childenv,stdout=nestedlog,stderr=subprocess.STDOUT,start_new_session=True);applications.append(simple)
                    state=wait_windows(1);ident=state['windows'][0]['id']
                    if shared:
                        def wait_shared(predicate):
                            deadline=time.monotonic()+10
                            while True:
                                observed=snapshot()
                                if predicate(observed):return observed
                                assert time.monotonic()<deadline,observed
                                time.sleep(.03)
                        def workspace():return copy.deepcopy(call({'op':'presentation.snapshot'})['documents'][f'desktop-{activity}'])
                        def put(document,request):return control_call({'op':'workspace.apply','document':document,'expected_revision':document['revision'],'request_id':request})
                        state=wait_shared(lambda s:ident in (s.get('shared') or {}).get('identities',{}))
                        surface_id=state['shared']['identities'][ident]
                        initial=workspace();initial['focus']={'surface_id':surface_id,'element_id':None}
                        assert put(initial,'manual-focus')['ok']
                        wait_shared(lambda s:s['layout']['focus']==ident)
                    else:assert control_call({'op':'focus','id':ident,'expected_revision':state['layout']['revision']})['ok']
                    desktop=subprocess.Popen(command,env=childenv,stdout=None,stderr=None,start_new_session=True);applications.append(desktop)
                    state=wait_windows(3);assert state['layout']['focus']==ident,'A new native surface stole focus'
                    simple2=subprocess.Popen(['weston-simple-shm'],env=childenv,stdout=nestedlog,stderr=subprocess.STDOUT,start_new_session=True);applications.append(simple2)
                    state=wait_windows(4);assert state['layout']['focus']==ident,'A conventional app stole focus'
                    if shared:
                        state=wait_shared(lambda s:len((s.get('shared') or {}).get('identities',{}))==4 and any(w['app_id']=='agentos.surface.native-fixture' for w in s['windows']))
                        native=next(w for w in state['windows'] if w['app_id']=='agentos.surface.native-fixture')
                        assert state['shared']['identities'][native['id']]=='native-fixture'
                        document=workspace();before=copy.deepcopy(document)
                        def remove(tile,identity):
                            if tile is None:return None
                            if tile['kind']=='leaf':return None if tile['surface_id']==identity else tile
                            children=[remove(c,identity) for c in tile['children']]
                            paired=[(c,r) for c,r in zip(children,tile['ratios']) if c is not None]
                            if not paired:return None
                            if len(paired)==1:return paired[0][0]
                            total=sum(r for _,r in paired)
                            return {**tile,'children':[c for c,_ in paired],'ratios':[r/total for _,r in paired]}
                        output=document['outputs']['nested-primary'];output['tiles']=remove(output['tiles'],surface_id)
                        output['floating'].append({'surface_id':surface_id,'x':100,'y':80,'width':320,'height':240})
                        response=put(document,'manual-float');assert response['ok'],response
                        assert not put(before,'stale-workspace')['ok'],'Stale workspace revision accepted'
                        wait_shared(lambda s:next(w for w in s['windows'] if w['id']==ident)['geometry']=={'x':100,'y':80,'width':320,'height':240})
                        restored=control_call({'op':'workspace.undo','event_cursor':response['result']['event_cursor'],'request_id':'undo-manual-float'})
                        assert restored['ok'],restored
                        assert workspace()['outputs']==before['outputs']
                        document=workspace();document['outputs']['nested-primary']['maximized']=surface_id
                        assert put(document,'manual-maximize')['ok']
                        wait_shared(lambda s:next(w for w in s['windows'] if w['id']==ident)['geometry']['width']==1280)
                        assert workspace()['focus']['surface_id']==surface_id
                        second_activity=call({'op':'create','name':'Set-aside verification'})['id']
                        assert control_call({'op':'workspace.activity','activity_id':str(second_activity)})['ok']
                        wait_shared(lambda s:all(w['geometry']['x']<0 for w in s['windows']))
                        assert simple.poll() is None and simple2.poll() is None,'Switching activity terminated work'
                        assert control_call({'op':'workspace.activity','activity_id':str(activity)})['ok']
                        wait_shared(lambda s:next(w for w in s['windows'] if w['id']==ident)['geometry']['width']==1280 and s['layout']['focus']==ident)
                        minimum=subprocess.Popen([str(ROOT/'target/debug/examples/minimum_client')],env=childenv,stdout=nestedlog,stderr=subprocess.STDOUT,start_new_session=True);applications.append(minimum)
                        state=wait_shared(lambda s:any(w['app_id']=='com.agentos.MinimumFixture' and w['id'] in s['shared']['identities'] for w in s['windows']) and bool(s['shared'].get('overview')))
                        minimum_window=next(w for w in state['windows'] if w['app_id']=='com.agentos.MinimumFixture')
                        minimum_id=state['shared']['identities'][minimum_window['id']]
                        preferred=workspace();focused=copy.deepcopy(preferred);focused['focus']={'surface_id':minimum_id,'element_id':None}
                        assert put(focused,'focus-minimum-fixture')['ok']
                        state=wait_shared(lambda s:s['layout']['focus']==minimum_window['id'] and next(w for w in s['windows'] if w['id']==minimum_window['id'])['geometry']['width']>=1600)
                        assert next(w for w in state['windows'] if w['id']==minimum_window['id'])['geometry']['height']>=900
                        before_pan=workspace()
                        assert control_call({'op':'viewport.pan','id':minimum_window['id'],'x':1,'y':1})['ok']
                        state=wait_shared(lambda s:next(w for w in s['windows'] if w['id']==minimum_window['id'])['geometry']['x']<0)
                        panned=next(w for w in state['windows'] if w['id']==minimum_window['id'])['geometry']
                        output=state['outputs'][0]
                        assert panned['x']+panned['width']==output['x']+output['width'] and panned['y']+panned['height']==output['y']+output['height'],(panned,output)
                        assert workspace()==before_pan,'Viewport panning changed preferred layout or document revision'
                        assert control_call({'op':'workspace.activity','activity_id':str(second_activity)})['ok']
                        state=wait_shared(lambda s:next(w for w in s['windows'] if w['id']==minimum_window['id'])['geometry']['x']<-50000)
                        hidden=next(w for w in state['windows'] if w['id']==minimum_window['id'])['geometry']
                        assert hidden['width']==panned['width'] and hidden['height']==panned['height'],'Hidden oversized view was shrunk'
                        assert control_call({'op':'workspace.activity','activity_id':str(activity)})['ok']
                        wait_shared(lambda s:next(w for w in s['windows'] if w['id']==minimum_window['id'])['geometry']['x']==panned['x'])
                        assert workspace()['outputs']==preferred['outputs'],'Pressure handling rewrote preferred placement'
                        assert minimum.poll() is None,'Pressure handling terminated a preserved view'
                        print('PASS: measured minimum sizes, viewport edges, preserved hidden geometry, activity restore and unchanged preferred placement')
                        # Simulate losing a previously observed output; no physical second
                        # monitor is claimed by this headless recovery-policy check.
                        call({'op':'outputs.register','output_id':'removed-fixture','width':1280,'height':800})
                        saved=workspace();off_output=copy.deepcopy(saved)
                        off_output['outputs']['nested-primary']['tiles']=remove(off_output['outputs']['nested-primary']['tiles'],surface_id)
                        off_output['outputs']['nested-primary']['floating']=[entry for entry in off_output['outputs']['nested-primary']['floating'] if entry['surface_id']!=surface_id]
                        if off_output['outputs']['nested-primary']['maximized']==surface_id:off_output['outputs']['nested-primary']['maximized']=None
                        off_output['outputs']['removed-fixture']={'tiles':{'kind':'leaf','surface_id':surface_id},'floating':[],'maximized':None}
                        off_output['focus']={'surface_id':surface_id,'element_id':None}
                        assert put(off_output,'move-to-removed-output')['ok']
                        call({'op':'outputs.disconnect','output_id':'removed-fixture'})
                        state=wait_shared(lambda s:'removed-fixture' in ((s['shared'].get('overview') or {}).get('recovered_outputs') or []) and next(w for w in s['windows'] if w['id']==ident)['geometry']['x']==0)
                        retained=workspace();assert retained['outputs']['removed-fixture']==off_output['outputs']['removed-fixture']
                        saved['revision']=retained['revision'];assert put(saved,'restore-from-removed-output')['ok']
                        wait_shared(lambda s:not ((s['shared'].get('overview') or {}).get('recovered_outputs')))
                        print('PASS: simulated output loss, temporary reachable projection, preserved placement and explicit recovery')
                        print('PASS: authenticated native identity, conventional registration, durable shared layout/focus, stale revision rejection, actual float/maximize rendering and journal undo')
                    else:
                        revision=state['layout']['revision']
                        assert not control_call({'op':'place','id':ident,'expected_revision':revision-1,'placement':{'mode':'maximized'}})['ok']
                        revision=snapshot()['layout']['revision']
                        response=control_call({'op':'place','id':ident,'expected_revision':revision,'placement':{'mode':'floating','rect':{'x':100,'y':80,'width':320,'height':240}}})
                        assert response['ok'],response
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
