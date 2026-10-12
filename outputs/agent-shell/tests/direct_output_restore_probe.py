"""Explicit preferred-output restoration through trusted native controls."""
from pathlib import Path
import json
import subprocess
import time



def restore_preferred(scene, snapshot, keyboard, pointer, capture=None):
    def wait(predicate, message):
        end=time.monotonic()+10
        while True:
            try:value=predicate()
            except RuntimeError:value=None
            if value:return value
            state=scene()
            assert time.monotonic()<end, (message,{k:state[k] for k in ('outputs','windows','seat_focus','pointer_routing')},state['shared']['error'],state['shared']['overview'])
            time.sleep(.03)
    offer=(scene()['shared']['overview'] or {}).get('restoration')
    assert offer,'No preferred placement restoration offered'
    bar=next(r for r in scene()['system_layers'] if r['namespace']=='agentos-system-bar' and r['mapped'])
    output=next(o for o in scene()['outputs'] if o['name']==bar['output'])
    point=snapshot('monitor-button')['point']
    def click(x,y):
        outputs=scene()['outputs']
        pointer.click(x,y,max(o['x']+o['width'] for o in outputs),max(o['y']+o['height'] for o in outputs))
    click(output['x']+bar['geometry']['x']+point[0],output['y']+bar['geometry']['y']+point[1])
    def monitor():return next((w for w in scene()['windows'] if w['title']=='Agent Monitor' and w['geometry'] and w['xdg']['pending_count']==0),None)
    settled={'geometry':None,'since':0}
    def monitor_settled():
        row=monitor()
        if not row:return None
        g=row['geometry'];xdg=row['xdg'];size=[g['width'],g['height']]
        if g['x']<0 or g['y']<0 or xdg['acked_size']!=size or xdg['committed_size']!=size:
            settled['geometry']=None;return None
        if settled['geometry']!=g:
            settled.update(geometry=dict(g),since=time.monotonic());return None
        return row if time.monotonic()-settled['since']>=.3 else None
    window=wait(monitor_settled,'Agent Monitor geometry did not commit and settle')
    print('Settled Monitor before focus: '+json.dumps(window),flush=True)
    # Mapping a window does not grant it keyboard focus. Establish deliberate
    # pointer focus, then reacquire allocation after the core commits it.
    g=window['geometry'];click(g['x']+g['width']/2,g['y']+24)
    def monitor_focused():
        row=monitor();state=scene()
        return row if (row and state['seat_focus']==row['id'] and state['shared']['focus']==row['id'] and row['xdg']['acked_activated'] and row['xdg']['committed_activated']) else None
    window=wait(monitor_focused,'Monitor pointer focus did not commit before restoration')
    if capture is not None:wait(capture.exists,'Mapped restoration controls were not captured')
    wait(lambda:(scene()['shared']['overview'] or {}).get('restoration'),'Opening Monitor released recovery without an explicit action')
    control=wait(lambda:(lambda r:r if r['sensitive'] else None)(snapshot('restore-output-placement')),'Restoration control unavailable')
    window=monitor();g=window['geometry'];point=control['point']
    print('Explicit restoration click: '+json.dumps({'window':window,'control':control,'global_point':[g['x']+point[0],g['y']+point[1]],'current_offer':(scene()['shared']['overview'] or {}).get('restoration')}),flush=True)
    click(g['x']+point[0],g['y']+point[1])
    wait(lambda:not (scene()['shared']['overview'] or {}).get('restoration'),'Explicit restoration did not complete')
    print('Explicit preferred-output restoration: '+json.dumps({'reviewed_offer':offer,'trusted_pointer_action':True,'outputs':scene()['outputs']}),flush=True)
    wait(monitor_focused,'Restoration lost committed Monitor focus')
    keyboard.chord(29,56,111)
    wait(lambda:monitor() is None,'Monitor close failed after restoration')

def verify(scene, target, snapshot, keyboard, pointer, capture=None):
    primary = Path('/sys/class/drm/card0-Virtual-1')
    assert (primary/'status').read_text().strip() == 'connected'
    def wait(predicate, message):
        end = time.monotonic()+10
        while True:
            value = predicate()
            if value:return value
            state=scene()
            assert time.monotonic()<end, (message, {k:state[k] for k in ('outputs','windows','seat_focus')}, state['shared']['overview'])
            time.sleep(.03)
    def force(value):
        (primary/'status').write_text(value)
        subprocess.run(['udevadm','trigger','--action=change','--subsystem-match=drm','--sysname-match=card0'],check=True)
        subprocess.run(['udevadm','settle','--timeout=5'],check=True)
    def editor():return next(w for w in scene()['windows'] if w['id']==target)
    def click_editor():
        g=editor()['geometry'];p=snapshot()['field'];outputs=scene()['outputs']
        pointer.click(g['x']+p[0],g['y']+p[1],max(o['x']+o['width'] for o in outputs),max(o['y']+o['height'] for o in outputs))
        wait(lambda:snapshot()['focused'] and scene()['seat_focus']==target,'Editor not focused')
    original=snapshot()['text']
    before=editor();assert before['geometry']['x']<1280, before
    click_editor()
    try:
        force('off')
        wait(lambda:{o['name'] for o in scene()['outputs']}=={'Virtual-2'},'Primary removal missing')
        wait(lambda:editor()['geometry']['x']>=0 and editor()['geometry']['x']<1024,'Editor recovery missing')
        click_editor();keyboard.chord(29,107);keyboard.chord(30)
        wait(lambda:snapshot()['text']==original+'a' and snapshot()['focused'],'Recovered editor typing missing')
        recovered=editor();secondary=next(o for o in scene()['outputs'] if o['name']=='Virtual-2')
        relative={k:recovered['geometry'][k]-(secondary['x'] if k=='x' else secondary['y'] if k=='y' else 0) for k in ('x','y','width','height')}
        force('on')
        wait(lambda:{o['name'] for o in scene()['outputs']}=={'Virtual-1','Virtual-2'},'Primary return missing')
        wait(lambda:(scene()['shared']['overview'] or {}).get('restoration'), 'Returned display restoration offer missing')
        wait(lambda:editor()['xdg']['pending_count']==0, 'Recovered editor configuration unsettled')
        current=editor();secondary=next(o for o in scene()['outputs'] if o['name']=='Virtual-2')
        expected={**relative,'x':relative['x']+secondary['x'],'y':relative['y']+secondary['y']}
        print('Active editor reconnection evidence: '+json.dumps({'expected_retained_secondary_geometry':expected,'observed_geometry':current['geometry'],'focused':snapshot()['focused'],'draft_preserved':snapshot()['text']==original+'a','seat_focus':scene()['seat_focus'],'overview':scene()['shared']['overview']}),flush=True)
        assert current['geometry']==expected, 'Returning preferred output moved the focused editor during active input'
        assert snapshot()['text']==original+'a' and snapshot()['focused'] and scene()['seat_focus']==target
        rejection=snapshot('restore-output-rejection')['response']
        assert rejection['ok'] is False and 'Trusted renderer required' in rejection['error'], rejection
        keyboard.chord(48)
        wait(lambda:snapshot()['text']==original+'ab' and snapshot()['focused'],'Typing interrupted by preferred display return')
        restore_preferred(scene,snapshot,keyboard,pointer,capture=capture)
        # The bar remains on its recovered display, so the preferred output's
        # current work area can differ from its pre-disconnect work area.
        primary_output=next(o for o in scene()['outputs'] if o['name']=='Virtual-1')
        area=next((r['work_area'] for r in scene()['system_layers'] if r['mapped'] and r['namespace']=='agentos-system-bar' and r['output']=='Virtual-1'),primary_output)
        expected_primary={k:area[k] for k in ('x','y','width','height')}
        wait(lambda:editor()['geometry']==expected_primary,'Explicit restoration did not return the current preferred work area')
        click_editor()
        keyboard.chord(46)
        wait(lambda:snapshot()['text']==original+'abc' and snapshot()['focused'],'Typing after explicit restoration missing')
        keyboard.chord(14);keyboard.chord(14);keyboard.chord(14)
        wait(lambda:snapshot()['text']==original,'Original text not restored')
        print('PASS: returning output offers restoration without moving the active editor; same-user restore denied; trusted pointer action restores preferred geometry and typing',flush=True)
    finally:force('on')
