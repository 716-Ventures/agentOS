#!/usr/bin/python3
"""Owned installed VTE journey; synthetic kernel input is not physical input evidence."""
import json
from pathlib import Path
import subprocess
import time
import uuid


def verify(metrics, output, core, scene, login_user, presentation, observe, keyboard, pointer):
    activity = int(core('presentation.get')['activity_id'])
    def broker(op, **fields):
        query = json.dumps({'op':op, **fields})
        code = "import sys,json;sys.path.insert(0,'/usr/local/lib/agent-os/services');from broker_client import request;q=json.load(sys.stdin);print(json.dumps(request(q.pop('op'),**q)))"
        result = subprocess.run(['runuser','-u',login_user,'--','python3','-c',code],input=query,text=True,capture_output=True,check=True,timeout=8)
        return json.loads(result.stdout)
    def wait(predicate, meaning, seconds=10):
        deadline = time.monotonic()+seconds
        last = None
        while True:
            try:
                last = predicate()
                if last:return last
            except (RuntimeError,LookupError,StopIteration) as exc:last=str(exc)
            if time.monotonic()>deadline:raise RuntimeError(meaning+': '+repr(last))
            time.sleep(.05)
    job = None
    surface = 'kernel-terminal-'+uuid.uuid4().hex
    try:
        code="import sys,time;print('KERNEL_VTE_READY',flush=True)\nwhile True:\n value=input()\n print('KERNEL_VTE_ACK '+value,flush=True)"
        job = broker('execute',activity=activity,argv=['/usr/bin/python3','-u','-c',code],purpose='Harmless installed native terminal kernel-input fixture',terminal=True,background=True,lifetime_seconds=90,request_confirmation=True,rows=24,cols=80)['id']
        state = broker('poll',job_id=job)
        assert state['status']=='approval_required',state
        subprocess.run(['agent-os-broker','approve',job],check=True,stdout=subprocess.DEVNULL,timeout=10)
        wait(lambda:broker('poll',job_id=job)['status']=='running','Owned terminal did not start')
        wait(lambda:any(row['source']=='broker:'+job and row['availability']=='available' for row in presentation({'op':'source.list','activity_id':str(activity),'limit':64})['sources']),'Owned broker source was not registered')
        document={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':surface,'activity_id':str(activity),'revision':0,'title':'Kernel terminal fixture','root':'terminal','elements':{'terminal':{'type':'PtySession@1','props':{'label':'Kernel terminal fixture','source':'broker:'+job}}},'bindings':{},'actions':{}}
        result=presentation({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':surface+'-create','expected_revisions':{surface:None},'operations':[{'op':'surface.create','document':document}]})
        assert result['status']=='committed',result
        def terminal_window():
            observed=scene()
            return next((row for row in observed['windows'] if observed['shared']['identities'].get(row['id'])==surface),None)
        terminal=wait(terminal_window,'Native terminal surface did not map')
        def focus(maximize=True):
            deadline=time.monotonic()+8
            while True:
                workspace=next(doc for doc in scene()['shared']['workspaces'].values() if doc['activity_id']==str(activity))
                try:
                    geometry={'x':0,'y':0,'width':output['width'] if maximize else min(900,output['width']),'height':output['height'] if maximize else min(600,output['height'])}
                    floating={'op':'workspace.edit','workspace_id':workspace['workspace_id'],'edit':{'kind':'float','surface_id':surface,'output_id':next(iter(workspace['outputs'])),**geometry}}
                    changing={'op':'workspace.edit','workspace_id':workspace['workspace_id'],'edit':{'kind':'maximize' if maximize else 'restore','surface_id':surface}}
                    edits=([floating,changing] if maximize else [changing,floating])+[{'op':'workspace.edit','workspace_id':workspace['workspace_id'],'edit':{'kind':'focus','surface_id':surface,'element_id':'terminal'}}]
                    result=presentation({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':surface+'-focus-'+uuid.uuid4().hex,'expected_revisions':{workspace['workspace_id']:workspace['revision']},'operations':edits})
                    assert result['status']=='committed',result
                    break
                except RuntimeError as exc:
                    # Only a definite stale rejection permits a fresh transaction.
                    if '"code":"stale_revision"' not in str(exc) or time.monotonic()>deadline:raise
                    time.sleep(.05)
            wait(lambda:scene()['seat_focus']==terminal['id'] and terminal_window()['geometry']==geometry,'Terminal did not receive its requested geometry and seat focus')

        focus()
        wait(lambda:observe('terminal:attach-state')['sensitive'],'Attach control did not become available')
        assert observe('terminal:attach')['requested']
        wait(lambda:observe('terminal:status')['attached'],'Native terminal did not confirm attachment')
        # The terminal's local status confirms attachment before input is sent.
        def point():return observe('terminal:snapshot')['point']
        location=wait(point,'VTE accessibility location unavailable')
        geometry=terminal_window()['geometry']
        pointer.click(geometry['x']+location[0],geometry['y']+location[1],output['width'],output['height'])
        wait(lambda:observe('terminal:snapshot')['focused'],'Kernel pointer did not focus VTE')
        # Actual evdev keys -> libinput -> Wayland -> VTE commit -> broker -> PTY.
        for key in (20,18,19,50,23,49,30,38):keyboard.chord(key)
        keyboard.chord(28)
        wait(lambda:'KERNEL_VTE_ACK terminal' in broker('poll',job_id=job)['output'],'Kernel typing did not reach installed PTY')
        focus(False) # Expose the clipboard publisher beside the terminal.
        source=next(row for row in scene()['windows'] if row['title']=='Direct transfer source')
        value=observe('transfer:Publish terminal clipboard')['point']
        pointer.click(source['geometry']['x']+value[0],source['geometry']['y']+value[1],output['width'],output['height'])
        wait(lambda:scene()['seat_focus']==source['id'],'Clipboard source did not receive focus')
        count=json.loads((metrics/'transfer-receipts.json').read_text())['clipboard']
        pointer.click(source['geometry']['x']+value[0],source['geometry']['y']+value[1],output['width'],output['height'])
        wait(lambda:json.loads((metrics/'transfer-receipts.json').read_text())['clipboard']>count,'Clipboard was not published by the owned client')
        focus()
        geometry=terminal_window()['geometry'];location=point()
        pointer.click(geometry['x']+location[0],geometry['y']+location[1],output['width'],output['height'])
        wait(lambda:observe('terminal:snapshot')['focused'],'VTE did not regain keyboard focus')
        keyboard.chord(29,42,47) # Ctrl+Shift+V: native terminal paste.
        try:wait(lambda:'λ 日本語' in broker('poll',job_id=job)['output'],'Pasted Unicode did not echo before Enter')
        except RuntimeError:
            print('Owned terminal output:',repr(broker('poll',job_id=job)['output']),flush=True);raise
        keyboard.chord(28)
        wait(lambda:'KERNEL_VTE_ACK  λ 日本語' in broker('poll',job_id=job)['output'],'Unicode clipboard paste did not reach installed PTY')
        before_detach=broker('poll',job_id=job)['output']
        assert observe('terminal:detach')['requested']
        wait(lambda:observe('terminal:attach-state')['sensitive'],'Attach control did not become available')
        keyboard.chord(29,42,47);keyboard.chord(28)
        time.sleep(.2) # Let queued kernel/Wayland events drain while explicitly detached.
        assert broker('poll',job_id=job)['output']==before_detach,'Detached terminal accepted program input'
        assert observe('terminal:attach')['requested']
        wait(lambda:observe('terminal:status')['attached'],'Native terminal did not confirm attachment')
        print('PASS: installed native VTE kernel keyboard, pointer focus, Unicode Wayland clipboard paste and explicit detach/reattach',flush=True)
    finally:
        if job is not None:
            broker('cancel',job_id=job)
            wait(lambda:broker('poll',job_id=job)['status'] in ('cancelled','failed','succeeded'),'Owned terminal work did not stop')
