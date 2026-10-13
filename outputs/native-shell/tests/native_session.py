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
import session_focus

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
        binary=Path('/usr/local/bin')/name if '--installed' in sys.argv else ROOT.parent/crate/'target/debug'/name
        (bins/name).symlink_to(binary)
    env={**os.environ,'HOME':str(root),'XDG_RUNTIME_DIR':str(runtime),'XDG_CONFIG_HOME':str(root/'config'),
         'XDG_STATE_HOME':str(root/'user-state'),'AGENT_OS_STATE':str(root/'core-state'),
         'AGENT_OS_SOCKET':str(endpoint),'AGENT_OS_COMPOSITOR_UID':str(os.getuid()),
         'AGENT_OS_BROKER_SOCKET':str(root/'unavailable-broker.sock'),
         'LIBGL_ALWAYS_SOFTWARE':'1','GSK_RENDERER':'cairo','G_DEBUG':'fatal-criticals','GTK_A11Y':'atspi'}
    env.pop('WAYLAND_DISPLAY',None);env.pop('DISPLAY',None)
    display_zoom='--display-zoom' in sys.argv
    screen_keyboard='--screen-keyboard' in sys.argv or display_zoom
    system_bar='--system-bar' in sys.argv
    if system_bar or screen_keyboard:
        appearance=os.environ.get('AGENT_OS_BAR_TEST_APPEARANCE','dark');scale=float(os.environ.get('AGENT_OS_BAR_TEST_SCALE','1'))
        config=root/'config/agent-os';config.mkdir(parents=True)
        (config/'desktop.json').write_text(json.dumps({'appearance':appearance,'text_scale':scale,'reduced_motion':True}))
        env['AGENT_OS_SYSTEM_BAR_CAPTURE']=str(OUTPUT/f'system-bar-{appearance}-{scale:g}.png')
        env['AGENT_OS_LAUNCHER_CAPTURE']=str(OUTPUT/f'launcher-{appearance}-{scale:g}.png')
    if screen_keyboard:
        (OUTPUT/'screen-keyboard.json').unlink(missing_ok=True)
        (OUTPUT/'screen-keyboard-geometry.json').unlink(missing_ok=True)
        env['AGENT_OS_KEYBOARD_CAPTURE']=str(OUTPUT/'screen-keyboard.png')
        env['AGENT_OS_KEYBOARD_GEOMETRY']=str(OUTPUT/'screen-keyboard-geometry.json')
        env['AGENT_OS_NATIVE_IME_FIXTURE']='1'
    screen_reader='--screen-reader' in sys.argv
    if screen_reader:
        env.update(GSETTINGS_BACKEND='keyfile',XDG_DATA_HOME=str(root/'data'),
                   XDG_SESSION_TYPE='wayland',XDG_CURRENT_DESKTOP='agentOS',LANG='C.UTF-8',
                   AGENT_OS_SCREEN_READER_VERIFY='1',AGENT_OS_NATIVE_IME_FIXTURE='1')
        speech=root/'config/speech-dispatcher';speech.mkdir(parents=True)
        (speech/'speechd.conf').write_text('AddModule "espeak-ng" "sd_espeak-ng" "/etc/speech-dispatcher/modules/espeak-ng.conf"\nDefaultModule espeak-ng\nAudioOutputMethod "alsa"\nAudioALSADevice "null"\n')
    ime_editor='--ime-editor' in sys.argv
    ime_failure='--ime-failure' in sys.argv
    ime='--ime' in sys.argv or ime_editor or ime_failure
    if ime:
        env['AGENT_OS_INPUT_METHOD_ARGV']=json.dumps([str(ROOT.parent/'native-compositor/target/debug/examples/ime_fixture'),str(runtime/'ime-test.sock')])
        env['GTK_IM_MODULE']='wayland'
        env['AGENT_OS_NATIVE_IME_FIXTURE']='editor' if ime_editor else '1'
        if ime_editor:env['AGENT_OS_NATIVE_IME_OBSERVATION']=str(runtime/'ime-observation.json')
    host_failure='--host-failure' in sys.argv
    compositor_failure='--compositor-failure' in sys.argv
    session_hangup='--session-hangup' in sys.argv
    with (OUTPUT/('session-compositor-failure.log' if compositor_failure else 'session-host-failure.log' if host_failure else 'session-ime-failure.log' if ime_failure else 'session-ime-editor.log' if ime_editor else 'session-ime.log' if ime else 'session-reader.log' if screen_reader else 'session.log')).open('w') as log:
        core=subprocess.Popen([str(SHELL/'target/release/agent-os-core')],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        session=None;owned=[]
        try:
            wait_for(endpoint.exists,[core])
            activity=call(endpoint,{'op':'create','name':'Full desktop session'})['id']
            document={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':'session-fixture','activity_id':str(activity),'revision':0,'title':'Session lifecycle','root':'root','elements':{'root':{'type':'Stack@1','props':{'spacing':'normal'},'slots':{'children':['reading','field']}},'reading':{'type':'Status@1','props':{'value':'Authenticated session fixture'}},'field':{'type':'DocumentEditor@1' if ime_editor else 'TextField@1','props':{'label':'Accessible session draft','value':'Original accessible value'}}},'bindings':{},'actions':{}}
            reader_outcomes={}
            if '--reader-outcomes' in sys.argv:
                for key,kind in [('result','Result@1'),('failure','Error@1'),('status','Status@1')]:
                    latch=root/('reader-'+key)
                    job=call(endpoint,{'op':'run','activity_id':activity,'argv':['/bin/sh','-c','while [ ! -e "$1" ]; do sleep .1; done; exit 7','reader-outcome',str(latch)]})['id']
                    reader_outcomes[key]=(job,latch)
                    document['elements'][key]={'type':kind,'props':{'message' if key=='failure' else 'value':{'binding':key}}}
                    if key!='status':document['elements'][key]['props']['label']='Reader '+key+' outcome'
                    document['bindings'][key]={'source':f'job:{job}','path':'/status','access':'read'}
                    document['elements']['root']['slots']['children'].append(key)
                document['elements']['status-copy']={'type':'TextField@1','props':{'label':'Status copy check','value':''}}
                document['elements']['root']['slots']['children'].append('status-copy')
            if '--reader-controls' in sys.argv:
                document['elements'].update({'editor':{'type':'DocumentEditor@1','props':{'label':'Reader document draft','value':'Saved document'}},'choice':{'type':'Choice@1','props':{'label':'Reader workspace choice','options':['First','Second'],'value':'First'}},'toggle':{'type':'Toggle@1','props':{'label':'Reader confirmation','value':False}}})
                document['elements']['root']['slots']['children'].extend(['editor','choice','toggle'])
            call(endpoint,{'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'session-fixture','expected_revisions':{'session-fixture':None},'operations':[{'op':'surface.create','document':document}]})
            session=subprocess.Popen(['python3',str(SHELL/'services/desktop_session.py'),'--backend','headless','--pixman','--bin-dir',str(bins),'--socket',str(endpoint)]+(['--screen-reader'] if screen_reader else []),env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            pidfile=wait_for(lambda:next(runtime.glob('agentos-session-*/compositor.pid'),None),[core,session])
            compositor=int(wait_for(lambda:pidfile.read_text().strip(),[core,session]));owned.append(compositor)
            control=pidfile.parent/f'agentos-compositor-{compositor}.sock'
            wait_for(control.exists,[core,session])
            state=wait_for(lambda:(lambda s:s if s.get('shared') and 'session-fixture' in s['shared']['identities'].values() else None)(call(control,{'op':'snapshot'})),[core,session])
            assert any(w['app_id'].startswith('agentos.surface.') for w in state['windows']),state
            layers=wait_for(lambda:(lambda s:s if any(layer['namespace']=='agentos-system-bar' and layer['mapped'] and layer['geometry']['height']>0 for layer in s['system_layers']) else None)(call(control,{'op':'snapshot'})),[core,session])
            bar=next(layer for layer in layers['system_layers'] if layer['namespace']=='agentos-system-bar')
            assert any(layer['namespace']=='agentos-wallpaper' and layer['mapped'] for layer in layers['system_layers']),layers
            output=layers['outputs'][0]
            assert bar['geometry']['width']==output['width'] and 0<bar['geometry']['height']<output['height']/2,bar
            assert bar['work_area']['y']==output['y']+bar['geometry']['height'],bar
            assert bar['work_area']['height']==output['height']-bar['geometry']['height'],bar
            assert not any(w['title'] in ('agentOS','agentOS system bar','Agent launcher') for w in layers['windows']),layers
            if screen_keyboard:
                import accessibility,pyatspi
                session_focus.focus(lambda value:call(endpoint,value),f'desktop-{activity}','session-fixture','field','keyboard-field-focus')
                field=accessibility.find('Accessible session draft',pyatspi.ROLE_TEXT)
                wait_for(lambda:field.getState().contains(pyatspi.STATE_FOCUSED),[core,session])
                original=call(control,{'op':'snapshot'})['seat_focus']
                for operation in ('keyboard.stroke','keyboard.restore_focus'):
                    with socket.socket(socket.AF_UNIX) as connection:
                        connection.settimeout(3);connection.connect(str(control))
                        connection.sendall(json.dumps({'op':operation,'keycode':38,'modifiers':0}).encode()+b'\n')
                        with connection.makefile('rb') as stream:reply=json.loads(stream.readline())
                    assert not reply['ok'] and 'Trusted renderer required' in reply['error'],reply
                accessibility.activate(accessibility.find('Agents',pyatspi.ROLE_PUSH_BUTTON))
                accessibility.disclose('Desktop controls')
                # Agents deliberately presents and focuses the floating monitor.
                # Return to the editor before testing the keyboard's focus lease.
                def monitor_focused():
                    state=call(control,{'op':'snapshot'})
                    (OUTPUT/'monitor-focus.json').write_text(json.dumps(state,indent=2))
                    return any(w['app_id']=='agentos.monitor' and w['id']==state['seat_focus'] for w in state['windows'])
                wait_for(monitor_focused,[core,session])
                session_focus.focus(lambda value:call(endpoint,value),f'desktop-{activity}','session-fixture','field','keyboard-return-to-editor')
                wait_for(lambda:field.getState().contains(pyatspi.STATE_FOCUSED),[core,session])
                accessibility.activate(accessibility.find('Keyboard',pyatspi.ROLE_PUSH_BUTTON))
                shown=wait_for(lambda:(lambda state:state if any(layer['namespace']=='agentos-keyboard' and layer['mapped'] for layer in state['system_layers']) else None)(call(control,{'op':'snapshot'})),[core,session])
                keyboard=next(layer for layer in shown['system_layers'] if layer['namespace']=='agentos-keyboard')
                assert shown['seat_focus']==original,shown
                close=accessibility.find('Hide keyboard',pyatspi.ROLE_PUSH_BUTTON).queryComponent().getExtents(pyatspi.WINDOW_COORDS)
                frame=accessibility.find('On-screen keyboard',pyatspi.ROLE_FRAME).queryComponent().getExtents(pyatspi.WINDOW_COORDS)
                # Compare accessibility coordinates within the native frame.
                assert frame.width==keyboard['geometry']['width'],(frame,keyboard)
                # CI reports padded AT-SPI extents beyond the painted button.
                # Use native widget bounds for clipping and AT-SPI's centre for
                # pointer reachability (also exercised by the kernel journey).
                geometry_path=OUTPUT/'screen-keyboard.json'
                geometry=wait_for(lambda:json.loads(geometry_path.read_text()) if geometry_path.exists() else None,[core,session])
                x,y,w,h=geometry['dismissal'];width,height=geometry['window']
                assert width==frame.width and height==frame.height,geometry
                assert 0<=x and x+w<=width and 0<=y and y+h<=height,geometry
                assert 0<=close.x-frame.x+close.width/2<frame.width,(close,frame)
                assert 0<=close.y-frame.y and close.y-frame.y+close.height<=frame.height,('Hide keyboard clipped vertically',close,frame,keyboard)
                assert keyboard['work_area']['height'] < bar['work_area']['height'],keyboard
                assert keyboard['geometry']['y']+keyboard['geometry']['height']==output['y']+output['height'],keyboard
                assert field.queryEditableText().setTextContents('')
                accessibility.activate(accessibility.find('a',pyatspi.ROLE_PUSH_BUTTON))
                wait_for(lambda:accessibility.text(field)=='a',[core,session])
                import ime_accessibility
                wait_for(lambda:ime_accessibility.rendered_text('Keyboard ready'),[core,session])
                accessibility.activate(accessibility.find('Shift',pyatspi.ROLE_PUSH_BUTTON))
                accessibility.activate(accessibility.find('A',pyatspi.ROLE_PUSH_BUTTON))
                wait_for(lambda:accessibility.text(field)=='aA',[core,session])
                accessibility.activate(accessibility.find('Shift on',pyatspi.ROLE_PUSH_BUTTON))
                accessibility.activate(accessibility.find('Backspace',pyatspi.ROLE_PUSH_BUTTON))
                wait_for(lambda:accessibility.text(field)=='a',[core,session])
                assert call(control,{'op':'snapshot'})['keyboard_pressed_count']==0
                accessibility.activate(accessibility.find('Ctrl',pyatspi.ROLE_PUSH_BUTTON))
                accessibility.activate(accessibility.find('Alt',pyatspi.ROLE_PUSH_BUTTON))
                accessibility.activate(accessibility.find('Space',pyatspi.ROLE_PUSH_BUTTON))
                wait_for(lambda:any(layer['namespace']=='agentos-launcher' and layer['mapped'] for layer in call(control,{'op':'snapshot'})['system_layers']),[core,session])
                assert call(control,{'op':'snapshot'})['keyboard_pressed_count']==0
                accessibility.activate(accessibility.find('Ctrl on',pyatspi.ROLE_PUSH_BUTTON))
                accessibility.activate(accessibility.find('Alt on',pyatspi.ROLE_PUSH_BUTTON))
                accessibility.activate(accessibility.find('Close launcher',pyatspi.ROLE_PUSH_BUTTON))
                wait_for(lambda:call(control,{'op':'snapshot'})['seat_focus']==original,[core,session])
                accessibility.activate(accessibility.find('Save draft',pyatspi.ROLE_PUSH_BUTTON))
                wait_for(lambda:call(endpoint,{'op':'presentation.get','document_id':'session-fixture'})['elements']['field']['props']['value']=='a',[core,session])
                assert field.queryEditableText().setTextContents('Original accessible value')
                accessibility.activate(accessibility.find('Save draft',pyatspi.ROLE_PUSH_BUTTON))
                wait_for(lambda:call(endpoint,{'op':'presentation.get','document_id':'session-fixture'})['elements']['field']['props']['value']=='Original accessible value',[core,session])
                accessibility.activate(accessibility.find('Hide keyboard',pyatspi.ROLE_PUSH_BUTTON))
                restored=wait_for(lambda:(lambda state:state if not any(layer['namespace']=='agentos-keyboard' and layer['mapped'] for layer in state['system_layers']) else None)(call(control,{'op':'snapshot'})),[core,session])
                assert restored['seat_focus']==original,restored
                restored_bar=next(layer for layer in restored['system_layers'] if layer['namespace']=='agentos-system-bar')
                assert restored_bar['work_area']==bar['work_area'],restored_bar
                print('PASS: private on-screen keyboard reserves/restores work area, preserves focus, types/edits, releases modifiers, invokes launcher and rejects same-login injection',flush=True)
            if display_zoom:
                import accessibility,pyatspi,ime_accessibility,shutil
                denied=call(control,{'op':'snapshot'})['display_zoom']
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
                    conn.connect(str(control));conn.sendall(b'{"op":"display.zoom","direction":1}\n')
                    with conn.makefile('rb') as stream:response=json.loads(stream.readline())
                assert not response['ok'] and call(control,{'op':'snapshot'})['display_zoom']==denied,response
                accessibility.disclose('Desktop controls')
                accessibility.activate(accessibility.find('Keyboard',pyatspi.ROLE_PUSH_BUTTON))
                def zoomed_keyboard():
                    state=call(control,{'op':'snapshot'})
                    layer=next((layer for layer in state['system_layers'] if layer['namespace']=='agentos-keyboard' and layer['mapped']),None)
                    return (state,layer) if layer and 0<layer['geometry']['height']<=state['outputs'][0]['height']/2 else None
                def wait_zoomed_keyboard():
                    try:return wait_for(zoomed_keyboard,[core,session])
                    except AssertionError:
                        print('Zoom sizing failure:',json.dumps(call(control,{'op':'snapshot'})),flush=True)
                        for name in ['screen-keyboard.json','screen-keyboard-geometry.json']:
                            geometry=OUTPUT/name
                            if geometry.exists():print('Native '+name+':',geometry.read_text(),flush=True)
                        raise
                for factor in (1.25,1.5,1.75,2.0):
                    accessibility.activate(accessibility.find('Zoom in',pyatspi.ROLE_PUSH_BUTTON))
                    wait_for(lambda:call(control,{'op':'snapshot'})['display_zoom']==factor,[core,session])
                    wait_for(lambda:ime_accessibility.rendered_text(f'Display zoom {factor*100:.0f}%'),[core,session])
                    wait_zoomed_keyboard()
                zoomed,layer=wait_zoomed_keyboard()
                assert zoomed['outputs'][0]['width']==output['width']//2,zoomed
                assert zoomed['outputs'][0]['height']==output['height']//2,zoomed
                assert layer['work_area']['height']>0,layer
                assert zoomed['seat_focus']==original,zoomed
                def fitted_dismissal():
                    geometry=json.loads((OUTPUT/'screen-keyboard.json').read_text())
                    if geometry['window']!=[layer['geometry']['width'],layer['geometry']['height']]:return None
                    x,y,w,h=geometry['dismissal'];width,height=geometry['window']
                    return geometry if 0<=x and x+w<=width and 0<=y and y+h<=height else None
                wait_for(fitted_dismissal,[core,session])
                shutil.copyfile(OUTPUT/'screen-keyboard.png',OUTPUT/'display-zoom.png')
                field=accessibility.find('Accessible session draft',pyatspi.ROLE_TEXT)
                assert field.queryEditableText().setTextContents('')
                accessibility.activate(accessibility.find('a',pyatspi.ROLE_PUSH_BUTTON))
                wait_for(lambda:accessibility.text(field)=='a',[core,session])
                assert field.queryEditableText().setTextContents('Original accessible value')
                accessibility.activate(accessibility.find('Hide keyboard',pyatspi.ROLE_PUSH_BUTTON))
                accessibility.activate(accessibility.find('Reset zoom',pyatspi.ROLE_PUSH_BUTTON))
                wait_for(lambda:call(control,{'op':'snapshot'})['display_zoom']==1.0,[core,session])
                restored=wait_for(lambda:(lambda state:state if state['outputs'][0]['width']==output['width'] and not any(layer['namespace']=='agentos-keyboard' and layer['mapped'] for layer in state['system_layers']) else None)(call(control,{'op':'snapshot'})),[core,session])
                assert next(layer['work_area'] for layer in restored['system_layers'] if layer['namespace']=='agentos-system-bar')==bar['work_area'],restored
                assert restored['keyboard_pressed_count']==0,restored
                print('PASS: trusted display zoom changes real output/workspace geometry; doubled zoom preserves keyboard dismissal, local typing and exact reset; same-login control denied',flush=True)
            if screen_reader:
                import accessibility,pyatspi
                session_focus.focus(lambda value:call(endpoint,value),f'desktop-{activity}','session-fixture','field','reader-fixture-focus')
                field=accessibility.find('Accessible session draft',pyatspi.ROLE_TEXT)
                wait_for(lambda:field.getState().contains(pyatspi.STATE_FOCUSED),[core,session])
                reader_log=pidfile.parent/'orca-speech.log'
                def announced():
                    text=reader_log.read_text() if reader_log.exists() else ''
                    return 'Using speech server factory:' in text and 'SPEECH OUTPUT:' in text and 'Accessible session draft' in text
                wait_for(announced,[core,session],timeout=30)
                print('PASS: session-owned Orca initializes speech and announces the focused native field',flush=True)
                accessibility.verify_reader_validation(lambda value:call(endpoint,value),reader_log)
                if '--reader-controls' in sys.argv:
                    accessibility.verify_reader_controls(lambda value:call(endpoint,value),reader_log)
                if '--reader-outcomes' in sys.argv:
                    accessibility.verify_reader_outcomes(lambda value:call(endpoint,value),reader_log,reader_outcomes,root/"core-state/state.sqlite3")
                # Normal logout removes the private session directory before finally.
                # Capture tested speech while that owned directory is still alive.
                (OUTPUT/'reader-validation-speech.log').write_bytes(reader_log.read_bytes())
                if screen_keyboard:
                    accessibility.disclose('Desktop controls')
                    accessibility.activate(accessibility.find('Keyboard',pyatspi.ROLE_PUSH_BUTTON))
                    wait_for(lambda:any(layer['namespace']=='agentos-keyboard' and layer['mapped'] for layer in call(control,{'op':'snapshot'})['system_layers']),[core,session])
                    wait_for(lambda:(lambda r:r and r['verified'] and r['watching'] and r['insert_registered'])(call(control,{'op':'snapshot'})['reader']),[core,session])
                    baseline=len(reader_log.read_text())
                    accessibility.activate(accessibility.find('Insert',pyatspi.ROLE_PUSH_BUTTON))
                    accessibility.activate(accessibility.find('h',pyatspi.ROLE_PUSH_BUTTON))
                    wait_for(lambda:ime_accessibility.rendered_text('Keyboard ready'),[core,session])
                    try:wait_for(lambda:'Entering learn mode.' in reader_log.read_text()[baseline:],[core,session])
                    except AssertionError:
                        print('Keyboard reader failure:',json.dumps({'field':accessibility.text(field),'scene':call(control,{'op':'snapshot'}),'speech':reader_log.read_text()[baseline:],'input_expired':ime_accessibility.rendered_text('Input expired; try again')}),flush=True)
                        raise
                    accessibility.activate(accessibility.find('Insert on',pyatspi.ROLE_PUSH_BUTTON))
                    accessibility.activate(accessibility.find('a',pyatspi.ROLE_PUSH_BUTTON))
                    time.sleep(.2)
                    assert accessibility.text(field)=='Original accessible value','Reader grab leaked virtual input'
                    baseline=len(reader_log.read_text())
                    accessibility.activate(accessibility.find('Escape',pyatspi.ROLE_PUSH_BUTTON))
                    wait_for(lambda:'Exiting learn mode.' in reader_log.read_text()[baseline:],[core,session])
                    assert call(control,{'op':'snapshot'})['keyboard_pressed_count']==0
                    accessibility.activate(accessibility.find('Hide keyboard',pyatspi.ROLE_PUSH_BUTTON))
                    wait_for(lambda:not any(layer['namespace']=='agentos-keyboard' and layer['mapped'] for layer in call(control,{'op':'snapshot'})['system_layers']),[core,session])
                    print('PASS: on-screen Insert+H reaches Orca, learn-mode grab isolates typing and Escape releases it',flush=True)

            if system_bar:
                import accessibility,pyatspi
                accessibility.activate(accessibility.find('Agents',pyatspi.ROLE_PUSH_BUTTON))
                # Monitor opening intentionally focuses it. Establish a known
                # content focus before testing a background focus change.
                wait_for(lambda:any(w['app_id']=='agentos.monitor' and w['id']==call(control,{'op':'snapshot'})['seat_focus'] for w in call(control,{'op':'snapshot'})['windows']),[core,session])
                session_focus.focus(lambda value:call(endpoint,value),f'desktop-{activity}','session-fixture','field','launcher-initial-content-focus')
                def content_focused():
                    state=call(control,{'op':'snapshot'})
                    return any(w['app_id']=='agentos.surface.session-fixture' and w['id']==state['seat_focus'] for w in state['windows'])
                wait_for(content_focused,[core,session])
                focused_scene=call(control,{'op':'snapshot'})
                assert focused_scene['windows'][-1]['id']==focused_scene['seat_focus'], 'Focused work remained below a floating desktop control'
                accessibility.activate(accessibility.find('Open launcher',pyatspi.ROLE_PUSH_BUTTON))
                def launcher_ready():
                    state=call(control,{'op':'snapshot'})
                    focused=any(layer['namespace']=='agentos-launcher' and layer['mapped'] and state['seat_focus']==layer['id'] for layer in state['system_layers'])
                    registered=any(window['title']=='Agent Monitor' and window['id'] in state['shared']['identities'] for window in state['windows'])
                    return state if focused and registered else None
                opened=wait_for(launcher_ready,[core,session])
                launcher=next(layer for layer in opened['system_layers'] if layer['namespace']=='agentos-launcher')
                assert launcher['work_area']==bar['work_area'],(launcher,bar)
                assert not any(w['title']=='Agent launcher' for w in opened['windows']),opened
                monitor=next(w for w in opened['windows'] if w['title']=='Agent Monitor')
                monitor_surface=opened['shared']['identities'][monitor['id']]
                workspace_id=f'desktop-{activity}'
                workspace=call(endpoint,{'op':'presentation.snapshot'})['documents'][workspace_id]
                assert workspace['focus'] is None or workspace['focus']['surface_id']!=monitor_surface
                call(endpoint,{'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1',
                    'request_id':'launcher-background-focus','expected_revisions':{workspace_id:workspace['revision']},
                    'operations':[{'op':'workspace.edit','workspace_id':workspace_id,'edit':{'kind':'focus','surface_id':monitor_surface,'element_id':None}}]})
                reconciled=wait_for(lambda:(lambda s:s if (s['shared']['workspaces'][workspace_id]['focus'] or {}).get('surface_id')==monitor_surface else None)(call(control,{'op':'snapshot'})),[core,session])
                assert reconciled['seat_focus']==launcher['id'], 'Background workspace reconciliation stole launcher keyboard focus: '+json.dumps({'seat_focus':reconciled['seat_focus'],'launcher':launcher['id']})
                print('PASS: background workspace focus reconciliation preserves active launcher typing')
                request=accessibility.find('Ask Agent',pyatspi.ROLE_TEXT)
                assert request.queryEditableText().setTextContents('Retain this launcher draft λ')
                accessibility.activate(accessibility.find('Close launcher',pyatspi.ROLE_PUSH_BUTTON))
                wait_for(lambda:not any(layer['namespace']=='agentos-launcher' and layer['mapped'] for layer in call(control,{'op':'snapshot'})['system_layers']),[core,session])
                wait_for(lambda:call(control,{'op':'snapshot'})['seat_focus']==monitor['id'],[core,session])
                accessibility.activate(accessibility.find('Open launcher',pyatspi.ROLE_PUSH_BUTTON))
                wait_for(lambda:any(layer['namespace']=='agentos-launcher' and layer['mapped'] for layer in call(control,{'op':'snapshot'})['system_layers']),[core,session])
                assert accessibility.text(accessibility.find('Ask Agent',pyatspi.ROLE_TEXT))=='Retain this launcher draft λ'
                accessibility.activate(accessibility.find('Close launcher',pyatspi.ROLE_PUSH_BUTTON))
                wait_for(lambda:Path(env['AGENT_OS_SYSTEM_BAR_CAPTURE']).exists(),[core,session])
                print('PASS: private system bar reserves work area; launcher opens, closes and retains drafts without workspace tiles')
            if not host_failure and not compositor_failure:
                if ime:
                    import ime_accessibility
                    wait_for(lambda:(runtime/'ime-test.sock').exists(),[core,session])
                    focused=session_focus.focus(lambda value:call(endpoint,value),f'desktop-{activity}','session-fixture','field','ime-fixture-focus')
                    assert focused['status']=='committed',focused
                    try:ime_accessibility.verify(lambda value:call(endpoint,value),runtime/'ime-test.sock',editor=ime_editor,observation=runtime/'ime-observation.json')
                    except Exception:
                        print('Failed IME focus state:',call(control,{'op':'snapshot'}),flush=True)
                        raise
                    if ime_failure:
                        with socket.socket(socket.AF_UNIX) as conn:
                            conn.settimeout(3);conn.connect(str(runtime/'ime-test.sock'))
                            conn.sendall(b'{"op":"status"}\n')
                            with conn.makefile('rb') as stream:helper=json.loads(stream.readline(4096))['pid']
                        assert isinstance(helper,int) and helper>1
                        assert Path(f'/proc/{helper}/exe').resolve().name=='ime_fixture'
                        os.kill(helper,signal.SIGKILL)
                        wait_for(lambda:not alive(helper),[core,session])
                        # Continue actual desktop/core reconciliation after the
                        # disconnect, rather than observing one pre-crash frame.
                        import accessibility,pyatspi
                        document=call(endpoint,{'op':'presentation.get','document_id':'session-fixture'})
                        receipt=call(endpoint,{'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'ime-recovery-render-barrier','expected_revisions':{'session-fixture':document['revision']},'operations':[{'op':'element.set_props','surface_id':'session-fixture','element_id':'reading','props':{'value':'Input method stopped; desktop available'}}]})
                        assert receipt['status']=='committed',receipt
                        # The previous Save's core receipt precedes renderer
                        # reconciliation. Observe a new rendered status before
                        # asking the editor to Save against its displayed view.
                        accessibility.wait(lambda:ime_accessibility.rendered_status('Input method stopped; desktop available'),'Native desktop did not render after input-method loss')
                        field=accessibility.find('Accessible session draft',pyatspi.ROLE_TEXT)
                        value='Recovered without input method λ'
                        assert field.queryEditableText().setTextContents(value)
                        wait_for(lambda:call(endpoint,{'op':'draft.get','surface_id':'session-fixture','element_id':'field'}).get('draft')==value,[core,session])
                        accessibility.activate(accessibility.find('Save draft',pyatspi.ROLE_PUSH_BUTTON))
                        try:wait_for(lambda:call(endpoint,{'op':'presentation.get','document_id':'session-fixture'})['elements']['field']['props']['value']==value,[core,session])
                        except AssertionError:
                            print('Failed IME recovery Save:',json.dumps({'document':call(endpoint,{'op':'presentation.get','document_id':'session-fixture'}),'draft':call(endpoint,{'op':'draft.get','surface_id':'session-fixture','element_id':'field'}),'visible':accessibility.text(field),'scene':call(control,{'op':'snapshot'})}),flush=True)
                            raise
                        assert call(control,{'op':'snapshot'})['shared']['error'] is None
                        print('PASS: failed input method leaves the native desktop and deliberate Unicode Save available',flush=True)
                else:
                    import accessibility
                    accessibility.verify_button(lambda value:call(endpoint,value))
                    accessibility.verify_validation(lambda value:call(endpoint,value))
                    accessibility.verify_toggle_validation(lambda value:call(endpoint,value))
                    accessibility.verify_choice_name(lambda value:call(endpoint,value))
                    accessibility.verify_local_form(lambda value:call(endpoint,value),root/"core-state/state.sqlite3")
                    accessibility.verify(lambda value:call(endpoint,value))
            if system_bar:
                core.terminate();assert core.wait(timeout=5) in (0,-signal.SIGTERM)
                accessibility.wait(lambda:accessibility.find('Agents',pyatspi.ROLE_PUSH_BUTTON).description=='Connection unavailable','Offline Agents entry did not expose connection status')
                accessibility.activate(accessibility.find('Open launcher',pyatspi.ROLE_PUSH_BUTTON))
                accessibility.wait(lambda:any(layer['namespace']=='agentos-launcher' and layer['mapped'] for layer in call(control,{'op':'snapshot'})['system_layers']), 'Offline launcher did not map')
                assert session.poll() is None
                assert accessibility.text(accessibility.find('Ask Agent',pyatspi.ROLE_TEXT))=='Retain this launcher draft λ'
                accessibility.activate(accessibility.find('Close launcher',pyatspi.ROLE_PUSH_BUTTON))
                print('PASS: core outage is visible; independent launcher and retained draft remain reachable without model work')
            # Every process in this private runtime is ours. Record identities before teardown.
            for proc in Path('/proc').iterdir():
                if not proc.name.isdigit() or int(proc.name)==core.pid:continue
                try:values=(proc/'environ').read_bytes().split(b'\0')
                except (PermissionError,FileNotFoundError,ProcessLookupError):continue
                if any(value==('XDG_RUNTIME_DIR='+str(runtime)).encode() or value.startswith(('XDG_RUNTIME_DIR='+str(runtime)+'/agentos-session-').encode()) for value in values):owned.append(int(proc.name))
            # Orca's process-title support rewrites its initial environment.
            # Include actual descendants of our exact session process as well as
            # the private-runtime scan, including adopted speech children.
            if screen_reader:
                parents={}
                for proc in Path('/proc').iterdir():
                    if not proc.name.isdigit():continue
                    try:parents[int(proc.name)]=int((proc/'stat').read_text().rsplit(') ',1)[1].split()[1])
                    except (PermissionError,FileNotFoundError,ProcessLookupError):continue
                descendants={session.pid}
                while True:
                    expanded=descendants|{pid for pid,parent in parents.items() if parent in descendants}
                    if expanded==descendants:break
                    descendants=expanded
                owned.extend(descendants-{session.pid})
            if screen_reader:
                assert any(Path(f'/proc/{pid}/comm').read_text().strip()=='orca' for pid in owned if alive(pid)), 'Owned reader missing before teardown'
            if compositor_failure:
                os.kill(compositor,signal.SIGKILL)
            elif host_failure:
                # Simulate display-host loss, rather than the ordinary logout path.
                host=int(Path(f'/proc/{session.pid}/task/{session.pid}/children').read_text().split()[0])
                os.kill(host,signal.SIGTERM)
            elif session_hangup:session.send_signal(signal.SIGHUP)
            else:session.terminate()
            exit_code=session.wait(timeout=20)
            if session_hangup:
                print('SESSION_HANGUP_OUTCOME '+json.dumps({'exit_code':exit_code,'runtime_directories':[str(p) for p in runtime.glob('agentos-session-*')]}),flush=True)
            assert exit_code>=0 if compositor_failure else exit_code==0
            remaining=lambda:[pid for pid in owned if alive(pid)]
            try:wait_for(lambda:not remaining(),[core] if core.poll() is None else [],timeout=5)
            except AssertionError:raise AssertionError('Session processes survived shutdown: '+str({pid:Path(f'/proc/{pid}/cmdline').read_bytes().replace(bytes([0]),b' ') for pid in remaining()}))
            if screen_reader:print('PASS: owned reader and speech processes reaped after '+('compositor failure' if compositor_failure else 'normal logout'),flush=True)
            assert not control.exists(),'Compositor socket leaked'
            assert not list(runtime.glob('agentos-session-*')),'Session directory leaked'
            if ime_failure:
                log.flush()
                assert (OUTPUT/'session-ime-failure.log').read_text().count('Input method unavailable:')==1,'Helper failure must be reported exactly once'
            print('PASS: '+('session hangup' if session_hangup else 'abrupt compositor loss' if compositor_failure else 'display-host loss' if host_failure else 'normal session')+' maps authenticated surfaces and reaps display host, compositor and renderer')
        finally:
            if screen_reader and 'pidfile' in locals():
                speech_log=pidfile.parent/'orca-speech.log'
                if speech_log.exists():(OUTPUT/'session-orca-speech.log').write_bytes(speech_log.read_bytes())
            if session:reap(session)
            for pid in owned:
                try:
                    values=Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
                    if any(value==('XDG_RUNTIME_DIR='+str(runtime)).encode() or value.startswith(('XDG_RUNTIME_DIR='+str(runtime)+'/agentos-session-').encode()) for value in values) and alive(pid):
                        if os.getpgid(pid)==pid:os.killpg(pid,signal.SIGKILL)
                        else:os.kill(pid,signal.SIGKILL)
                except (FileNotFoundError,ProcessLookupError,PermissionError):pass
            reap(core)
