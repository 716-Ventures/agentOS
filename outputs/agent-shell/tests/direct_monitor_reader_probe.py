"""Foreground Monitor speech and selected text through actual kernel input."""
from pathlib import Path
import json
import time
import uuid


def verify(log, keyboard, pointer, snapshot, scene, request, output, activity, restore_editor):
    marker='monitor-reader-'+uuid.uuid4().hex[:12]
    latch=Path('/var/lib/agent-os-runtime')/marker
    job=None
    def until(predicate, meaning, seconds=8):
        deadline=time.monotonic()+seconds
        while True:
            try:
                value=predicate()
                if value:return value
                last=None
            except RuntimeError as error:last=str(error)
            if time.monotonic()>deadline:raise RuntimeError(meaning+('; '+last if last else ''))
            time.sleep(.05)
    def work():return snapshot('monitor-work:'+marker)
    def window():return next((w for w in scene()['windows'] if w['title']=='Agent Monitor'),None)
    def point(local):
        geometry=until(window,'Monitor did not map')['geometry']
        x,y=geometry['x']+local[0],geometry['y']+local[1]
        assert 0<x<output['width'] and 0<y<output['height'],(local,geometry)
        pointer.click(x,y,output['width'],output['height'])
    try:
        # The shared direct-input fixture deliberately maximizes its editor.
        # Restore its saved arrangement before navigating a second tiled view.
        keyboard.chord(29,56,67) # Ctrl+Alt+F9; preserve the focused editor's lease.
        until(lambda:all(not layout.get('maximized') for doc in scene()['shared']['workspaces'].values() if str(doc['activity_id'])==str(activity) for layout in doc['outputs'].values()),'Editor restore did not settle')
        time.sleep(.3)
        code='import pathlib,sys,time\np=pathlib.Path(sys.argv[1]);end=time.monotonic()+60\nwhile time.monotonic()<end and not p.exists(): time.sleep(.05)\nsys.exit(7 if p.exists() else 0)'
        job=request({'op':'run','activity_id':int(activity),'argv':['/usr/bin/python3','-u','-c',code,str(latch),marker]})['id']
        until(lambda:next((j for j in request({'op':'snapshot'})['jobs'] if j['id']==job and j['status']=='running'),None),'Monitor fixture job did not start')
        bar=next(layer['geometry'] for layer in scene()['system_layers'] if layer['namespace']=='agentos-system-bar' and layer['mapped'])
        button=snapshot('monitor-button')['point']
        pointer.click(bar['x']+button[0],bar['y']+button[1],output['width'],output['height'])
        def placed_window():
            observed=scene()
            candidate=next((w for w in observed['windows'] if w['title']=='Agent Monitor'),None)
            if candidate and candidate['id'] in observed['shared']['identities'] and candidate['geometry']['x']>=0 and candidate['geometry']['y']>=0:return candidate
            return None
        until(placed_window,'Kernel Monitor button did not place the window')
        time.sleep(.3)
        state=until(lambda:work(),'Monitor work observation unavailable')
        point([state['width']/2,80])
        for _ in range(32):
            state=work()
            if 40<state['point'][1]<state['height']-40:break
            pointer.event(2,8,-1 if state['point'][1]>=state['height']-40 else 1);pointer.sync();time.sleep(.05)
        else:raise RuntimeError('Monitor work text did not scroll into view: '+json.dumps(state))
        point(state['point'])
        try:until(lambda:work()['active'] and work()['focused'],'Kernel click did not focus the real Monitor status')
        except RuntimeError:
            state=scene()
            print('Monitor focus diagnostics: '+json.dumps({'work':work(),'scene':{k:state.get(k) for k in ('windows','outputs','seat_focus','pointer_routing','layout')},'last_click':pointer.last_click}),flush=True)
            raise
        keyboard.chord(29,30)
        selected=until(lambda:(lambda s:s if s['selection']==s['text'] and s['text'].startswith('core · running\n') else None)(work()),'Kernel Ctrl+A did not select the running Monitor snapshot')
        baseline=len(log.read_text(errors='replace'))
        latch.touch()
        until(lambda:next((j for j in request({'op':'snapshot'})['jobs'] if j['id']==job and j['status']=='failed'),None),'Monitor fixture job did not fail')
        expected=selected['text'].replace('core · running\n','core · failed\n',1)
        latest=until(lambda:(lambda s:s if s['current']=='Current value:\n'+expected else None)(work()),'Selected Monitor status did not expose the current failure')
        assert latest['selection']==selected['text'] and latest['text']==selected['text'] and latest['active'] and latest['focused'],latest
        def announcements():
            blocks=[];block=None
            for line in log.read_text(errors='replace')[baseline:].splitlines():
                if 'START ' in line and 'OBJECT EVENT ' in line:block=[] if 'OBJECT:ANNOUNCEMENT' in line else None
                if block is not None:block.append(line)
                if ('END ' in line or 'FINISHED ' in line) and 'OBJECT EVENT ' in line:
                    if block is not None:
                        value='\n'.join(block)
                        if "SPEECH OUTPUT: 'core · failed" in value and marker in value:blocks.append(value)
                    block=None
            return blocks
        until(announcements,'Active Monitor failure was not spoken',15)
        keyboard.chord(29,46) # Copy the protected older snapshot.
        keyboard.chord(106) # Deselect and adopt the current observation.
        until(lambda:(lambda s:s['text']==expected and s['selection'] is None and not s['current'])(work()),'Monitor deselection did not adopt the latest state')
        time.sleep(.8)
        assert len(announcements())==1,'Unchanged Monitor refresh/deselection repeated speech'
        keyboard.chord(29,56,111) # agentOS close-view shortcut; close only the utility window.
        until(lambda:window() is None,'Monitor close did not release its window')
        restore_editor()
        until(lambda:snapshot()['focused'],'Monitor clipboard receiver did not receive focus')
        keyboard.chord(29,47)
        try:until(lambda:snapshot()['text']==selected['text'],'Monitor Ctrl+C did not retain exact older text')
        except RuntimeError:
            print('Monitor clipboard diagnostics: '+json.dumps({'expected':selected['text'],'receiver':snapshot(),'seat_focus':scene()['seat_focus']}),flush=True)
            raise
        keyboard.chord(29,30);keyboard.chord(14)
        until(lambda:snapshot()['text']=='','Monitor clipboard fixture did not clear its unrelated editor draft')
        return {'job_id':job,'active_monitor':True,'selected_snapshot_preserved':True,'current_failure_visible':True,'failure_announcements':1,'deselection_adopts_latest':True,'trusted_clipboard_roundtrip':True}
    finally:
        if job is not None:
            state=next((j for j in request({'op':'snapshot'})['jobs'] if j['id']==job),None)
            if state and state['status'] not in ('failed','succeeded','cancelled'):request({'op':'cancel','job_id':job})
        latch.unlink(missing_ok=True)
