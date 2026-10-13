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

def local_bounds(node,frame):
    # GTK 4.14 includes the CSD inset in WINDOW_COORDS; newer GTK reports
    # content-relative coordinates. Both widgets share the frame's origin.
    bounds=node.queryComponent().getExtents(pyatspi.WINDOW_COORDS)
    origin=frame.queryComponent().getExtents(pyatspi.WINDOW_COORDS)
    return (bounds.x-origin.x,bounds.y-origin.y,bounds.width,bounds.height)

def within(bounds,geometry):
    x,y,width,height=bounds
    return x>=0 and y>=0 and width>0 and height>0 and x+width<=geometry['width'] and y+height<=geometry['height']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--appearance',choices=['dark','light'],default='dark');parser.add_argument('--initial-text-scale',type=float,choices=[1.0,3.0],default=1.0);parser.add_argument('--close-small',action='store_true',help='Qualify 300% close confirmation in a 360px terminal');args=parser.parse_args()
    output=ROOT/'test-output'/('desktop-design-'+args.appearance+('-close-small' if args.close_small else '')+('-large' if args.initial_text_scale==3 else ''));output.mkdir(parents=True,exist_ok=True)
    for name in ('monitor.png','system-bar.png','launcher.png','settings.png','terminal.png','terminal.json','terminal-close.png','welcome.png','desktop.png','scene.json'):(output/name).unlink(missing_ok=True)
    desktop_session.enable_subreaper()
    with tempfile.TemporaryDirectory(prefix='agentos-desktop-design-') as directory, (output/'session.log').open('w') as log:
        root=Path(directory);config=root/'config/agent-os';config.mkdir(parents=True)
        (config/'desktop.json').write_text(json.dumps({'appearance':args.appearance,'text_scale':args.initial_text_scale,'reduced_motion':True}))
        state=root/'user-state/agent-os';state.mkdir(parents=True)
        endpoint=root/'core.sock';pidfile=root/'compositor.pid'
        env={**os.environ,'HOME':directory,'XDG_RUNTIME_DIR':directory,'XDG_CONFIG_HOME':str(config.parent),'XDG_STATE_HOME':str(state.parent),'AGENT_OS_STATE':str(root/'core-state'),'AGENT_OS_SOCKET':str(endpoint),'AGENT_OS_COMPOSITOR_CORE':str(endpoint),'AGENT_OS_COMPOSITOR_UID':str(os.getuid()),'AGENT_OS_BROKER_SOCKET':str(root/'absent-broker.sock'),'AGENT_OS_MODEL_USAGE':str(root/'absent-usage.json'),'LIBGL_ALWAYS_SOFTWARE':'1','GSK_RENDERER':'cairo','GDK_BACKEND':'wayland','GTK_A11Y':'atspi','G_DEBUG':'fatal-criticals','WINIT_UNIX_BACKEND':'wayland','AGENT_OS_COMPOSITOR_BACKEND':'winit','AGENT_OS_SYSTEM_BAR_CAPTURE':str(output/'system-bar.png'),'AGENT_OS_LAUNCHER_CAPTURE':str(output/'launcher.png'),'AGENT_OS_MONITOR_CAPTURE':str(output/'monitor.png'),'AGENT_OS_SETTINGS_CAPTURE':str(output/'settings.png'),'AGENT_OS_WELCOME_CAPTURE':str(output/'welcome.png')}
        env.pop('WAYLAND_DISPLAY',None);env.pop('DISPLAY',None)
        env['WAYLAND_DEBUG']='client' # Private fixture: inspect initial configure sizes.
        env.update(AGENT_OS_LOCAL_TERMINAL_VERIFY='1',AGENT_OS_LOCAL_TERMINAL_VERIFY_WORK='1',AGENT_OS_TERMINAL_CLOSE_CAPTURE=str(output/'terminal-close.png'),AGENT_OS_LOCAL_TERMINAL_VERIFY_MENU='1',AGENT_OS_LOCAL_TERMINAL_CAPTURE=str(output/'terminal.png'),AGENT_OS_LOCAL_TERMINAL_OBSERVATION=str(output/'terminal.json'))
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
            accessibility.wait(lambda:(output/'welcome.png').exists(),'Welcome did not paint')
            welcome=accessibility.find('Welcome to agentOS',pyatspi.ROLE_FRAME)
            welcome_window=next(w for w in scene()['windows'] if w['app_id']=='agentos.welcome')
            actual=welcome_window['geometry']
            assert actual['height']>=welcome_window['xdg']['client_min_size'][1],'Welcome ignores its minimum readable height'
            action=accessibility.find('Continue to desktop',pyatspi.ROLE_PUSH_BUTTON,root=welcome)
            assert not action.parent.getState().contains(pyatspi.STATE_FOCUSABLE),'Welcome layout wrapper adds a focus stop'
            if args.initial_text_scale==3:
                for label in ['Continue to desktop','Open setup']:
                    bounds=local_bounds(accessibility.find(label,pyatspi.ROLE_PUSH_BUTTON,root=welcome),welcome)
                    assert within(bounds,actual),('Welcome action outside viewport',label,bounds,actual)
            accessibility.activate(action)
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
            for category,field_name in [('Activities','Current activity'),('Workspace','Arrange workspace'),('Accessibility','Show on-screen keyboard'),('Storage','Stored images'),('Setup','Open setup…'),('Appearance','Appearance')]:
                accessibility.activate(accessibility.find(category,pyatspi.ROLE_TOGGLE_BUTTON,root=settings))
                if category=='Setup' and args.initial_text_scale==3:
                    setup=accessibility.find('Open setup…',pyatspi.ROLE_PUSH_BUTTON,root=settings)
                    bounds=local_bounds(setup,settings)
                    geometry=next(w for w in scene()['windows'] if w['app_id']=='agentos.settings')['geometry']
                    assert within(bounds,geometry),('Setup action outside viewport',bounds,geometry)
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
            if args.close_small:
                size.queryValue().currentValue=300.0
                accessibility.wait(lambda:json.loads((config/'desktop.json').read_text())['text_scale']==3.0,'300% text did not persist')
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
            accessibility.wait(lambda:accessibility.find('Agent Monitor',pyatspi.ROLE_FRAME).getState().contains(pyatspi.STATE_ACTIVE),'Foreground Monitor is not active in GTK')
            assert not accessibility.find('Agent view · Project notes',pyatspi.ROLE_FRAME).getState().contains(pyatspi.STATE_ACTIVE),'Covered document retained GTK activation'
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
            accessibility.activate(accessibility.find('Open terminal',pyatspi.ROLE_PUSH_BUTTON))
            def terminal_ready():
                observed=scene()
                terminal=next((w for w in observed['windows'] if w['app_id'].startswith('agentos.local-terminal.')),None)
                return terminal if terminal and observed['seat_focus']==terminal['id'] and observed['shared']['focus']==terminal['id'] and not any(layer['namespace']=='agentos-launcher' and layer['mapped'] for layer in observed['system_layers']) else None
            accessibility.wait(terminal_ready,'Native terminal did not open and replace launcher focus')
            terminal_window=terminal_ready()
            inactive_monitor=next(w for w in scene()['windows'] if w['id']==monitor['id'])
            assert inactive_monitor['geometry']==monitor['geometry'],'Deactivation shifted Monitor placement'
            assert inactive_monitor['xdg']['client_geometry']==monitor['xdg']['client_geometry'],'Deactivation changed client shadow extents'
            terminal=accessibility.find('Local terminal',pyatspi.ROLE_TERMINAL)
            accessibility.wait(lambda:'native-terminal-λ' in accessibility.text(terminal).splitlines(),'Native PTY did not execute the exact Unicode verification line')
            accessibility.wait(lambda:(output/'terminal.png').exists(),'Native terminal did not paint')
            copy_menu=accessibility.find('Copy',pyatspi.ROLE_MENU_ITEM)
            assert copy_menu.getState().contains(pyatspi.STATE_SENSITIVE),'Selected local terminal text did not enable context Copy'
            assert accessibility.find('Paste',pyatspi.ROLE_MENU_ITEM).getState().contains(pyatspi.STATE_SENSITIVE),'Ready local shell did not enable context Paste'
            accessibility.activate(copy_menu)
            accessibility.wait(lambda:accessibility.find('Local terminal',pyatspi.ROLE_TERMINAL).getState().contains(pyatspi.STATE_FOCUSED),'Context Copy did not restore terminal keyboard focus')
            terminal_geometry=terminal_ready()['geometry']
            assert [terminal_geometry['width'],terminal_geometry['height']]==[880,560],terminal_geometry
            child=json.loads((output/'terminal.json').read_text())['pid']
            terminal_frame=accessibility.find('Terminal',pyatspi.ROLE_FRAME)
            if args.close_small:
                end=time.monotonic()+10
                while True:
                    current=scene();workspace=next(iter(current['shared']['workspaces'].values()));logical=current['shared']['identities'][terminal_window['id']]
                    try:
                        receipt=call(endpoint,{'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'small-terminal-close-'+str(time.time_ns()),'expected_revisions':{workspace['workspace_id']:workspace['revision']},'operations':[{'op':'workspace.edit','workspace_id':workspace['workspace_id'],'edit':{'kind':'float','surface_id':logical,'output_id':next(iter(workspace['outputs'])),'x':200,'y':0,'width':880,'height':360}},{'op':'workspace.edit','workspace_id':workspace['workspace_id'],'edit':{'kind':'focus','surface_id':logical,'element_id':None}}]})
                        assert receipt['status']=='committed',receipt
                        break
                    except AssertionError as error:
                        if 'stale_revision' not in str(error) or time.monotonic()>end:raise
                        time.sleep(.05)
                try:accessibility.wait(lambda:terminal_ready() and terminal_ready()['geometry']['height']==360 and terminal_ready()['xdg']['pending_count']==0,'Small terminal did not settle')
                except AssertionError:
                    print('Small terminal scene',json.dumps(scene()),flush=True);raise
            programs=Path(f'/proc/{child}/task/{child}/children').read_text().split()
            assert programs,'Verification foreground program did not start'
            original_geometry=terminal_ready()['geometry']
            accessibility.activate(accessibility.find('Close window',pyatspi.ROLE_PUSH_BUTTON,root=terminal_frame))
            cancel=accessibility.find('Cancel',pyatspi.ROLE_PUSH_BUTTON,root=terminal_frame)
            assert Path(f'/proc/{child}').exists() and all(Path(f'/proc/{pid}').exists() for pid in programs),'Close ended work before confirmation'
            accessibility.wait(lambda:(output/'terminal-close.png').exists(),'Close guard did not paint')
            assert terminal_ready()['geometry']==original_geometry,'Close confirmation changed terminal geometry'
            for name in ['Cancel','Close terminal']:
                bounds=local_bounds(accessibility.find(name,pyatspi.ROLE_PUSH_BUTTON,root=terminal_frame),terminal_frame)
                assert within(bounds,original_geometry),('Close action outside viewport',name,bounds,original_geometry)
            accessibility.activate(cancel)
            accessibility.wait(lambda:accessibility.find('Local terminal',pyatspi.ROLE_TERMINAL).getState().contains(pyatspi.STATE_FOCUSED),'Cancel did not restore terminal focus')
            assert Path(f'/proc/{child}').exists() and all(Path(f'/proc/{pid}').exists() for pid in programs),'Cancel ended running work'
            accessibility.activate(accessibility.find('Close window',pyatspi.ROLE_PUSH_BUTTON,root=terminal_frame))
            accessibility.activate(accessibility.find('Close terminal',pyatspi.ROLE_PUSH_BUTTON,root=terminal_frame))
            def reaped_programs():
                for pid in programs:
                    try:os.waitpid(int(pid),os.WNOHANG)
                    except ChildProcessError:pass
                return all(not Path(f'/proc/{pid}').exists() for pid in programs)
            accessibility.wait(reaped_programs,'Confirmed close leaked foreground work')
            accessibility.wait(lambda:not Path(f'/proc/{child}').exists(),'Closing native terminal leaked its shell child')
            with socket.socket(socket.AF_UNIX) as connection:
                connection.connect(str(control));connection.sendall(json.dumps({'op':'terminal.present','app_id':terminal_window['app_id']}).encode()+b'\n')
                denied=json.loads(connection.makefile('rb').readline())
                assert not denied['ok'],'Same-user process gained native terminal focus authority'
            accessibility.activate(accessibility.find('Open launcher',pyatspi.ROLE_PUSH_BUTTON))
            assert accessibility.text(accessibility.find('Ask Agent',pyatspi.ROLE_TEXT))=='Keep this unsent request λ'
            accessibility.activate(accessibility.find('New document',pyatspi.ROLE_PUSH_BUTTON))
            accessibility.wait(lambda:not any(layer['namespace']=='agentos-launcher' and layer['mapped'] for layer in scene()['system_layers']),'Successful document creation left the launcher covering work')
            accessibility.wait(lambda:any(w['app_id'].startswith('agentos.surface.document-') and scene()['seat_focus']==w['id'] for w in scene()['windows']),'New document did not receive focus')
            accessibility.activate(accessibility.find('Open launcher',pyatspi.ROLE_PUSH_BUTTON))
            accessibility.activate(accessibility.find('Close launcher',pyatspi.ROLE_PUSH_BUTTON))
            assert call(endpoint,{'op':'snapshot'})['jobs']==[], 'Rendering or composing started work'
            log.flush()
            trace=(output/'session.log').read_text()
            for app_id,expected in [('agentos.welcome',(560,320)),('agentos.settings',(760,540)),('agentos.monitor',(920,680)),(terminal_window['app_id'],(880,560))]:
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
            print('PASS: composed desktop, settings and menu; native VTE Unicode output, child cleanup and guarded focus; successful actions dismiss launcher and preserve drafts; Welcome dismissal survives restart without completing setup; no model requests')
        finally:
            if owned and owned[1]:desktop_session.stop_compositor(root,owned)
            reap(weston);reap(core);desktop_session.reap_session_children()
if __name__=='__main__':main()
