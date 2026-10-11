#!/usr/bin/python3
"""Empty real core -> explicit native New document -> implicit activity, without models."""
import json
import os
from pathlib import Path
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
OUTPUT=ROOT/'test-output'/'first-document';OUTPUT.mkdir(parents=True,exist_ok=True)

def reap(proc):
    if proc is None:return
    if proc.poll() is None:os.killpg(proc.pid,signal.SIGTERM)
    try:proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)

with tempfile.TemporaryDirectory(prefix='agentos-first-document-') as directory:
    root=Path(directory);endpoint=root/'core.sock';runtime=root/'runtime';runtime.mkdir(mode=0o700)
    env={**os.environ,'CARGO_HOME':os.environ.get('CARGO_HOME',str(Path.home()/'.cargo')),'RUSTUP_HOME':os.environ.get('RUSTUP_HOME',str(Path.home()/'.rustup')),'HOME':directory,'XDG_RUNTIME_DIR':str(runtime),'XDG_CONFIG_HOME':str(root/'config'),'XDG_STATE_HOME':str(root/'state'),'WAYLAND_DISPLAY':'first-document','GDK_BACKEND':'wayland','GSK_RENDERER':'cairo','GTK_A11Y':'atspi','G_DEBUG':'fatal-criticals','AGENT_OS_COMPOSITOR_UID':str(os.getuid()),'AGENT_OS_STATE':str(root/'core-state'),'AGENT_OS_SOCKET':str(endpoint),'AGENT_OS_BROKER_SOCKET':str(root/'absent-broker.sock')}
    def call(query):
        with socket.socket(socket.AF_UNIX) as conn:
            conn.settimeout(3);conn.connect(str(endpoint));conn.sendall(json.dumps(query).encode()+b'\n')
            response=json.loads(conn.makefile('rb').readline(4*1024*1024+1))
            assert response['ok'],response
            return response['result']
    desktop=display=core=nested=chooser=None
    with (OUTPUT/'journey.log').open('w') as log:
        try:
            core=subprocess.Popen([str(SHELL/'target/release/agent-os-core')],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            accessibility.wait(lambda:endpoint.exists(),'Empty core did not start')
            assert call({'op':'snapshot'})['activities']==[]
            display=subprocess.Popen(['weston','--backend=headless-backend.so','--use-pixman','--socket=first-document','--idle-time=0'],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            accessibility.wait(lambda:(runtime/'first-document').exists(),'Private first-document display did not start')
            nested=subprocess.Popen([str(ROOT.parent/'native-compositor/target/debug/agent-os-compositor')],env={**env,'AGENT_OS_COMPOSITOR_CORE':str(endpoint),'LIBGL_ALWAYS_SOFTWARE':'1','WINIT_UNIX_BACKEND':'wayland'},stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            control=runtime/f'agentos-compositor-{nested.pid}.sock'
            accessibility.wait(lambda:control.exists(),'Shared compositor did not start')
            displays=[path.name for path in runtime.glob('wayland-*') if path.is_socket()]
            assert len(displays)==1,displays
            env={**env,'WAYLAND_DISPLAY':displays[0],'AGENT_OS_COMPOSITOR_SOCKET':str(control)}
            def scene():
                with socket.socket(socket.AF_UNIX) as conn:
                    conn.settimeout(6);conn.connect(str(control));conn.sendall(b'{"op":"snapshot"}\n')
                    response=json.loads(conn.makefile('rb').readline(4*1024*1024+1))
                    return response.get('result') if response.get('ok') else None
            desktop=subprocess.Popen([str(ROOT/'target/debug/agent-os-desktop'),'--socket',str(endpoint)],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            accessibility.activate(accessibility.find('Agent Monitor',pyatspi.ROLE_PUSH_BUTTON))
            button=accessibility.find('New document',pyatspi.ROLE_PUSH_BUTTON)
            accessibility.wait(lambda:button.getState().contains(pyatspi.STATE_SENSITIVE),'New document required a prior activity')
            importer=accessibility.find('Import text file…',pyatspi.ROLE_PUSH_BUTTON)
            assert importer.getState().contains(pyatspi.STATE_SENSITIVE),'Import required a prior activity'
            if '--import' in sys.argv or '--queued' in sys.argv:
                path=root/'selected.txt';path.write_text('Selected document λ 日本語')
                chooser=subprocess.Popen(['cargo','test','--locked','--manifest-path',str(ROOT/'Cargo.toml'),('transport::initial_document_tests::queued_new_documents_reuse_the_confirmed_activity' if '--queued' in sys.argv else 'transport::initial_document_tests::import_into_an_empty_core_validates_before_creating_an_activity'),'--','--ignored','--exact','--nocapture'],env={**env,'AGENT_OS_INITIAL_IMPORT':str(path)},stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                assert chooser.wait(timeout=45)==0,'Initial document backend regression failed; inspect journey.log'
            else:accessibility.activate(button)
            accessibility.wait(lambda:len(call({'op':'snapshot'})['activities'])>=1,'New document did not create its internal activity')
            state=call({'op':'snapshot'});activity=state['activities'][0]['id'];assert state['activities'][0]['name']=='Personal'
            def documents():return call({'op':'presentation.snapshot'})['documents']
            accessibility.wait(lambda:len([doc for doc in documents().values() if doc.get('root')=='editor'])==(2 if '--queued' in sys.argv else 1),'First documents did not appear')
            def placed_document():
                observed=scene()
                if not observed:return False
                identities=(observed.get('shared') or {}).get('identities',{})
                ids={identities[key] for key in observed['layout']['order'] if key in identities}
                docs=documents()
                return any(key in ids and doc.get('root')=='editor' for key,doc in docs.items())
            try:accessibility.wait(placed_document,'First document did not map into the shared compositor')
            except AssertionError:
                print('Scene:',json.dumps(scene()),flush=True);print('Core presentation:',json.dumps(call({'op':'presentation.snapshot'})),flush=True);raise
            editor=accessibility.find('selected.txt' if '--import' in sys.argv else 'Document',pyatspi.ROLE_TEXT)
            accessibility.wait(lambda:editor.getState().contains(pyatspi.STATE_EDITABLE),'First document was not editable')
            if '--queued' not in sys.argv:accessibility.activate(button)
            accessibility.wait(lambda:len([doc for doc in documents().values() if doc.get('root')=='editor'])==2,'Second document did not appear')
            assert len(call({'op':'snapshot'})['activities'])==1,'Second document created a duplicate activity'
            assert all(doc['activity_id']==str(activity) for doc in documents().values() if doc.get('root')=='editor')
            chooser=subprocess.Popen(['cargo','test','--locked','--manifest-path',str(ROOT/'Cargo.toml'),'document_dialog::initial_import_tests::accepted_file_selection_keeps_its_optional_activity_context','--','--ignored','--exact','--nocapture'],env={**env,'GTK_A11Y':'none'},stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            assert chooser.wait(timeout=45)==0,'Native chooser regression failed; inspect journey.log'
            print('PASS: empty native session creates editable documents without a separate activity task; Import enabled; one internal activity reused')
        finally:
            reap(chooser);reap(desktop);reap(nested);reap(display);reap(core)
