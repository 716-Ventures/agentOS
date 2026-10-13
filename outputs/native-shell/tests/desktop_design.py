#!/usr/bin/python3
"""Capture the real composed desktop, with a real private core and owned processes.

No model requests, provider credentials, fixture telemetry, or installed user state.
Run under dbus-run-session in the Linux verification guest.
"""
import argparse
import json
import os
import re
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import pyatspi
import accessibility
ROOT=Path(__file__).resolve().parents[1]
SHELL=ROOT.parent if (ROOT.parent/'install_runtime.py').is_file() else ROOT.parent/'agent-shell'
sys.path.insert(0,str(SHELL/'services'))
import desktop_session

def call(path,value):
    with socket.socket(socket.AF_UNIX) as conn:
        conn.settimeout(5);conn.connect(str(path));conn.sendall(json.dumps(value).encode()+b'\n')
        result=json.loads(conn.makefile('rb').readline(16*1024*1024))
        assert result['ok'],result
        return result['result']

def reap(proc):
    if proc and proc.poll() is None:os.killpg(proc.pid,signal.SIGTERM)
    if proc:
        try:proc.wait(timeout=8)
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--appearance',choices=['dark','light'],default='dark');args=parser.parse_args()
    output=ROOT/'test-output'/('desktop-design-'+args.appearance);output.mkdir(parents=True,exist_ok=True)
    for name in ('monitor.png','system-bar.png','launcher.png','settings.png','desktop.png','scene.json'):(output/name).unlink(missing_ok=True)
    desktop_session.enable_subreaper()
    with tempfile.TemporaryDirectory(prefix='agentos-desktop-design-') as directory, (output/'session.log').open('w') as log:
        root=Path(directory);config=root/'config/agent-os';config.mkdir(parents=True)
        (config/'desktop.json').write_text(json.dumps({'appearance':args.appearance,'text_scale':1.0,'reduced_motion':True}))
        state=root/'user-state/agent-os';state.mkdir(parents=True)
        endpoint=root/'core.sock';pidfile=root/'compositor.pid'
        env={**os.environ,'HOME':directory,'XDG_RUNTIME_DIR':directory,'XDG_CONFIG_HOME':str(config.parent),'XDG_STATE_HOME':str(state.parent),'AGENT_OS_STATE':str(root/'core-state'),'AGENT_OS_SOCKET':str(endpoint),'AGENT_OS_COMPOSITOR_CORE':str(endpoint),'AGENT_OS_COMPOSITOR_UID':str(os.getuid()),'AGENT_OS_BROKER_SOCKET':str(root/'absent-broker.sock'),'AGENT_OS_MODEL_USAGE':str(root/'absent-usage.json'),'LIBGL_ALWAYS_SOFTWARE':'1','GSK_RENDERER':'cairo','GDK_BACKEND':'wayland','GTK_A11Y':'atspi','G_DEBUG':'fatal-criticals','WINIT_UNIX_BACKEND':'wayland','AGENT_OS_COMPOSITOR_BACKEND':'winit','AGENT_OS_SYSTEM_BAR_CAPTURE':str(output/'system-bar.png'),'AGENT_OS_LAUNCHER_CAPTURE':str(output/'launcher.png'),'AGENT_OS_MONITOR_CAPTURE':str(output/'monitor.png'),'AGENT_OS_SETTINGS_CAPTURE':str(output/'settings.png')}
        env.pop('WAYLAND_DISPLAY',None);env.pop('DISPLAY',None)
        env['WAYLAND_DEBUG']='client' # Private fixture: inspect initial configure sizes.
        core=weston=None;owned=None
        try:
            core=subprocess.Popen([str(SHELL/'target/release/agent-os-core')],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            accessibility.wait(endpoint.exists,'Private core did not start')
            activity=call(endpoint,{'op':'create','name':'Desktop design verification'})['id']
            document={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':'design-notes','activity_id':str(activity),'revision':0,'title':'Project notes','root':'editor','elements':{'editor':{'type':'DocumentEditor@1','props':{'label':'Project notes','value':'A quiet workspace for meaningful work.\n\nDocuments, applications and agents share this desktop. Your work stays visible while you decide what to do next.'}}},'bindings':{},'actions':{}}
            call(endpoint,{'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'design-document','expected_revisions':{'design-notes':None},'operations':[{'op':'surface.create','document':document}]})
            bins=root/'bin';bins.mkdir()
            for name,target in [('agent-os-compositor',ROOT.parent/'native-compositor/target/debug/agent-os-compositor'),('agent-os-desktop',ROOT/'target/debug/agent-os-desktop')]: (bins/name).symlink_to(target)
            command=desktop_session.child_command(bins,endpoint,activity)
            child=root/'desktop-child';child.write_text('#!/bin/sh\nprintf "%s\\n" "$$" > '+shlex.quote(str(pidfile))+'\nexec '+shlex.join(command)+'\n');child.chmod(0o700)
            configuration=root/'weston.ini';configuration.write_text(desktop_session.configuration(child,'headless'))
            # Debug capture is enabled only on this private test compositor.
            weston=subprocess.Popen(['weston','--debug','--config='+str(configuration),'--socket=design-host','--width=1280','--height=800','--use-pixman'],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            accessibility.wait(lambda:pidfile.exists() and pidfile.read_text().strip(),'Owned compositor did not start')
            pid=int(pidfile.read_text());owned=(pid,desktop_session.process_identity(pid));control=root/f'agentos-compositor-{pid}.sock'
            accessibility.wait(control.exists,'Compositor control missing')
            def scene():return call(control,{'op':'snapshot'})
            accessibility.wait(lambda:any(layer['namespace']=='agentos-wallpaper' and layer['mapped'] for layer in scene()['system_layers']),'Wallpaper did not map')
            accessibility.activate(accessibility.find('Continue to desktop',pyatspi.ROLE_PUSH_BUTTON))
            accessibility.wait(lambda:(state/'welcome.json').exists(),'Welcome dismissal was not persisted')
            assert json.loads((state/'welcome.json').read_text()) == {'version':1,'dismissed':True}
            assert not (state/'setup.json').exists(),'Dismissing Welcome falsely completed provider setup'
            accessibility.activate(accessibility.find('Desktop menu',pyatspi.ROLE_TOGGLE_BUTTON))
            accessibility.activate(accessibility.find('Open launcher',pyatspi.ROLE_PUSH_BUTTON))
            accessibility.wait(lambda:any(layer['namespace']=='agentos-launcher' and layer['mapped'] for layer in scene()['system_layers']),'Desktop menu did not open launcher')
            accessibility.activate(accessibility.find('Close launcher',pyatspi.ROLE_PUSH_BUTTON))

            accessibility.activate(accessibility.find('Desktop menu',pyatspi.ROLE_TOGGLE_BUTTON))
            accessibility.activate(accessibility.find('Desktop settings…',pyatspi.ROLE_PUSH_BUTTON))
            accessibility.wait(lambda:any(w['app_id']=='agentos.settings' for w in scene()['windows']),'Desktop settings did not map')
            accessibility.wait(lambda:(output/'settings.png').exists(),'Settings capture missing')
            settings=accessibility.find('Desktop settings',pyatspi.ROLE_FRAME)
            for category,field_name in [('Activities','Current activity'),('Workspace','Arrange workspace'),('Accessibility','Show on-screen keyboard'),('Storage','Stored images'),('Setup','Setup network, audio and providers'),('Appearance','Appearance')]:
                accessibility.activate(accessibility.find(category,pyatspi.ROLE_TOGGLE_BUTTON,root=settings))
                try:accessibility.find(field_name,pyatspi.ROLE_COMBO_BOX if field_name in ('Current activity','Appearance') else None,root=settings)
                except AssertionError:
                    from collections import deque
                    queue=deque([settings]);rows=[]
                    while queue and len(rows)<120:
                        node=queue.popleft()
                        if node is None:continue
                        try:rows.append([node.name,node.getRoleName()]);queue.extend(node[i] for i in range(min(node.childCount,40)))
                        except (RuntimeError,LookupError):pass
                    print('Settings category failure',category,rows,flush=True);raise
            size=accessibility.find('Text scale',pyatspi.ROLE_SPIN_BUTTON,root=settings)
            size.queryValue().currentValue=125.0
            accessibility.wait(lambda:json.loads((config/'desktop.json').read_text())['text_scale']==1.25,'Text percentage did not persist as a scale factor')
            size.queryValue().currentValue=100.0
            accessibility.wait(lambda:json.loads((config/'desktop.json').read_text())['text_scale']==1.0,'Text size did not restore')
            accessibility.activate(accessibility.find('Close window',pyatspi.ROLE_PUSH_BUTTON,root=settings))
            accessibility.wait(lambda:not any(w['app_id']=='agentos.settings' for w in scene()['windows']),'Desktop settings did not close')

            accessibility.activate(accessibility.find('Agents',pyatspi.ROLE_PUSH_BUTTON))
            accessibility.wait(lambda:output.joinpath('monitor.png').exists(),'Monitor did not paint')
            def ready():
                observed=scene()
                monitor=next((w for w in observed['windows'] if w['title']=='Agent Monitor' and w['app_id']=='agentos.monitor'),None)
                if not monitor or monitor['id'] not in observed['shared']['identities']:return None
                workspace=next(iter(observed['shared']['workspaces'].values()));surface=observed['shared']['identities'][monitor['id']]
                if not any(item['surface_id']==surface for layout in workspace['outputs'].values() for item in layout['floating']):return None
                if monitor['xdg']['pending_count'] or observed['seat_focus']!=monitor['id']:return None
                return observed
            accessibility.wait(ready,'Monitor did not settle as the focused floating host control')
            observed=ready();monitor=next(w for w in observed['windows'] if w['title']=='Agent Monitor')
            time.sleep(.35)
            subprocess.run(['weston-screenshooter'],env={**env,'WAYLAND_DISPLAY':'design-host'},cwd=output,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=8)
            for path in output.glob('wayland-screenshot*.png'):path.rename(output/'desktop.png')
            assert (output/'desktop.png').is_file(),'Composed desktop capture missing'
            accessibility.activate(accessibility.find('Open launcher',pyatspi.ROLE_PUSH_BUTTON))
            for label in ['Open terminal','New document','Import text file…']:
                button=accessibility.find(label,pyatspi.ROLE_PUSH_BUTTON)
                assert not button.parent.getState().contains(pyatspi.STATE_FOCUSABLE), 'Layout wrapper adds a duplicate focus stop: '+label
            entry=accessibility.find('Ask Agent',pyatspi.ROLE_TEXT);entry.queryEditableText().setTextContents('Keep this unsent request λ')
            accessibility.activate(accessibility.find('Close launcher',pyatspi.ROLE_PUSH_BUTTON))
            accessibility.wait(lambda:not any(layer['namespace']=='agentos-launcher' and layer['mapped'] for layer in scene()['system_layers']),'Launcher did not dismiss')
            accessibility.activate(accessibility.find('Open launcher',pyatspi.ROLE_PUSH_BUTTON))
            accessibility.wait(lambda:any(layer['namespace']=='agentos-launcher' and layer['mapped'] for layer in scene()['system_layers']),'Launcher did not reopen')
            assert accessibility.text(accessibility.find('Ask Agent',pyatspi.ROLE_TEXT))=='Keep this unsent request λ'
            accessibility.activate(accessibility.find('Close launcher',pyatspi.ROLE_PUSH_BUTTON))
            assert call(endpoint,{'op':'snapshot'})['jobs']==[], 'Rendering or composing started work'
            log.flush()
            trace=(output/'session.log').read_text()
            for app_id,expected in [('agentos.welcome',(560,320)),('agentos.settings',(760,540)),('agentos.monitor',(920,680))]:
                named=re.search(r'xdg_toplevel[#@](\d+)\.set_app_id\("'+re.escape(app_id)+r'"\)',trace)
                assert named,'Missing control identity: '+app_id
                identity=named[1]
                created=list(re.finditer(r'get_toplevel\(new id xdg_toplevel[#@]'+identity+r'\)',trace[:named.start()]))[-1]
                configured=re.findall(r'xdg_toplevel[#@]'+identity+r'\.configure\((\d+), (\d+),',trace[created.end():])
                first=next((tuple(map(int,size)) for size in configured if all(int(v)>0 for v in size)),None)
                assert first==expected,('Desktop control opened at the wrong size',app_id,first,expected)
            # Restart the private desktop against the same user state. Dismissal
            # must survive without writing setup completion or affecting drafts.
            desktop_session.stop_compositor(root,owned);owned=None
            reap(weston);weston=None
            pidfile.unlink(missing_ok=True)
            weston=subprocess.Popen(['weston','--debug','--config='+str(configuration),'--socket=design-host','--width=1280','--height=800','--use-pixman'],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            accessibility.wait(lambda:pidfile.exists() and pidfile.read_text().strip(),'Restarted compositor did not start')
            pid=int(pidfile.read_text());owned=(pid,desktop_session.process_identity(pid));control=root/f'agentos-compositor-{pid}.sock'
            accessibility.wait(control.exists,'Restarted compositor control missing')
            accessibility.wait(lambda:any(w['app_id'].startswith('agentos.surface.') for w in scene()['windows']),'Restored document did not map')
            time.sleep(.5)
            assert not any(w['title']=='Welcome to agentOS' for w in scene()['windows']),'Welcome reappeared after dismissal'
            assert not (state/'setup.json').exists()

            (output/'scene.json').write_text(json.dumps(observed,indent=2)+'\n')
            print('PASS: real wallpaper, transparent bar, floating monitor, work preserved, launcher draft retained, desktop menu works, Welcome dismissal survives restart without completing setup; no model requests')
        finally:
            if owned and owned[1]:desktop_session.stop_compositor(root,owned)
            reap(weston);reap(core);desktop_session.reap_session_children()
if __name__=='__main__':main()
