#!/usr/bin/python3
"""Repeatable kernel interactions in the owned direct-display fixture.

Observer convergence times include control-socket polling; presentation receipts
and completed-frame intervals are reported separately. No Mac scanout claim.
"""
import json,math,socket,time,threading
from pathlib import Path

def verify(metrics, keyboard, pointer, output, target, snapshot, scene, core, presentation, env):
    width,height=output['width'],output['height']
    endpoint=env['AGENT_OS_COMPOSITOR_SOCKET']
    def status():
        with socket.socket(socket.AF_UNIX) as conn:
            conn.settimeout(3);conn.connect(endpoint);conn.sendall(b'{"op":"interaction.status"}\n')
            value=json.loads(conn.makefile().readline())
            assert value['ok'],value
            return value['result']
    def wait(fn,timeout=5):
        end=time.monotonic()+timeout
        while True:
            value=fn()
            if value:return value
            assert time.monotonic()<end,'Interaction did not converge'
            time.sleep(.005)
    def summary(values):
        ordered=sorted(values)
        return {'samples':len(values),'p50_ms':round(ordered[math.ceil(len(values)*.5)-1],2),'p95_ms':round(ordered[math.ceil(len(values)*.95)-1],2),'max_ms':round(max(values),2)}
    # Native registration, focus and first completed frame after a real bar click.
    opening=[]
    for _ in range(8):
        point=snapshot('monitor-button')['point']
        pointer.event(3,0,round(point[0]*65535/width));pointer.event(3,1,round(point[1]*65535/height));pointer.sync();time.sleep(.04)
        before=status()['frames'];started=time.monotonic();pointer.chord(272)
        def ready():
            value=status();monitor=next((w for w in value['windows'] if w['title']=='Agent Monitor'),None)
            return monitor if monitor and value['seat_focus']==monitor['id'] and value['frames']>before else None
        wait(ready);opening.append((time.monotonic()-started)*1000)
        snapshot('performance-close-monitor');wait(lambda:not any(w['title']=='Agent Monitor' for w in status()['windows']));time.sleep(.06)
    print('MONITOR_OPEN_BASELINE '+json.dumps(summary(opening)),flush=True)
    current=next(w for w in status()['windows'] if w['id']==target)
    save=snapshot()['save'];pointer.click(current['geometry']['x']+save[0],current['geometry']['y']+save[1],width,height)
    wait(lambda:core('draft.get')['draft'] is None)
    time.sleep(.15)
    # Float the private fixture through the ordinary revision-checked workspace API.
    logical=core('presentation.get')['surface_id'];observed=scene()
    workspace=next(d for d in observed['shared']['workspaces'].values() if d.get('activity_id')==core('presentation.get')['activity_id'])
    deadline=time.monotonic()+5
    while True:
        workspace=presentation({'op':'presentation.get','document_id':workspace['workspace_id']})
        try:
            presentation({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'interaction-placement-'+str(time.time_ns()),'expected_revisions':{workspace['workspace_id']:workspace['revision']},'operations':[{'op':'workspace.edit','workspace_id':workspace['workspace_id'],'edit':{'kind':'float','surface_id':logical,'output_id':next(iter(workspace['outputs'])),'x':200,'y':150,'width':720,'height':500}}]})
            break
        except RuntimeError as error:
            if 'stale_revision' not in str(error) or time.monotonic()>deadline:raise
            time.sleep(.03)

    geometry=wait(lambda:next((w['geometry'] for w in status()['windows'] if w['id']==target and w['geometry']['width']==720),None));time.sleep(.2)
    start=(geometry['x']+350,geometry['y']+19)
    def move(x,y):
        pointer.event(3,0,round(x*65535/width));pointer.event(3,1,round(y*65535/height));pointer.sync()
    move(*start);time.sleep(.08);pointer.event(1,272,1);pointer.sync();time.sleep(.08)
    samples=[];errors=[]
    def motion():
        try:
            for step in range(120):
                move(start[0]+round(150*math.sin(step*math.pi/60)),start[1]+round(45*math.sin(step*math.pi/60)))
                time.sleep(1/60)
        except BaseException as error:errors.append(str(error))
    producer=threading.Thread(target=motion);producer.start()
    try:
        while producer.is_alive():
            value=status();window=next(w for w in value['windows'] if w['id']==target);point=value['pointer']
            samples.append({'time':time.monotonic(),'x':window['geometry']['x'],'expected':geometry['x']+point[0]-start[0],'error':value['error'],'preview':value['previews'].get(target),'error_px':abs(window['geometry']['x']-(geometry['x']+point[0]-start[0]))})
    finally:
        producer.join();pointer.event(1,272,0);pointer.sync()
    assert not errors,errors
    gaps=[(b['time']-a['time'])*1000 for a,b in zip(samples,samples[1:]) if b['x']!=a['x']]
    time.sleep(.3)
    # Populate only the disposable fixture. Then measure actual GTK scroll commits.
    snapshot('performance-fill');keyboard.chord(29,102);time.sleep(.2) # Ctrl+Home
    window=next(w for w in status()['windows'] if w['id']==target)
    move(window['geometry']['x']+300,window['geometry']['y']+250);time.sleep(.08)
    def receipts():
        return next((json.loads(p.read_text()) for p in metrics.glob('feedback-scroll-*.json') if json.loads(p.read_text())['requested']),None)
    for index in range(20):
        previous=receipts();count=previous['presented'] if previous else 0
        pointer.event(2,8,-3);pointer.sync()
        wait(lambda: (r:=receipts()) and r['presented']>count)
        time.sleep(.025)
    scroll=receipts();assert scroll['invalid']==0 and scroll['discarded']==0,scroll
    report={'meaning':'Guest kernel interactions; opening/drag observations include control polling, scroll uses completed GTK presentation receipts. Mac host presentation is not measured.', 'monitor_open_observed':summary(opening),'drag_geometry_observer_gaps':summary(gaps),'drag_max_pointer_distance_px':round(max(s['error_px'] for s in samples),2),'drag_worst_sample':max(samples,key=lambda s:s['error_px']),'scroll_presentation':scroll}
    (metrics/'interactions.json').write_text(json.dumps(report));print('INTERACTION_MEASUREMENTS '+json.dumps(report),flush=True)
    assert report['monitor_open_observed']['p95_ms']<750,report
    assert report['drag_max_pointer_distance_px']<24,report
    assert scroll['p95_ms']<=50,scroll

