"""Local shell journey through owned kernel input, native menus and Wayland clipboard."""
import json
from pathlib import Path
import time


def verify(metrics,output,scene,observe,keyboard,pointer):
    def wait(predicate,meaning):
        end=time.monotonic()+10;last=None
        while time.monotonic()<end:
            try:
                last=predicate()
                if last:return last
            except (RuntimeError,ValueError,StopIteration) as error:last=str(error)
            time.sleep(.05)
        raise RuntimeError(meaning+': '+repr(last))
    def terminal():return next(w for w in scene()['windows'] if w['app_id'].startswith('agentos.local-terminal.'))
    width,height=output['width'],output['height']
    prior=next(w for w in scene()['windows'] if w['title'].endswith('Kernel terminal fixture'))
    assert scene()['seat_focus']==prior['id'],'Broker terminal journey did not retain focus'
    keyboard.chord(29,56,111)
    wait(lambda:not any(w['id']==prior['id'] for w in scene()['windows']),'Completed broker fixture did not close')
    keyboard.chord(29,56,57)
    launcher=wait(lambda:next((l for l in scene()['system_layers'] if l['namespace']=='agentos-launcher' and l['mapped']),None),'Launcher did not open')
    point=observe('local-terminal:launcher-button')['point'];g=launcher['geometry']
    assert 0<point[0]<g['width'] and 0<point[1]<g['height'],(point,g)
    print('CHECK: local launcher terminal point',point,g,flush=True)
    pointer.click(g['x']+point[0],g['y']+point[1],width,height)
    try:window=wait(terminal,'Local terminal did not map')
    except RuntimeError:
        s=scene();print('Local launch diagnostic',{k:s[k] for k in ['seat_focus','pointer_location','pointer_routing','system_layers','windows']},observe('local-terminal:launcher-button'),flush=True);raise
    wait(lambda:scene()['seat_focus']==window['id'] and scene()['shared']['focus']==window['id'],'Local terminal did not become authoritative focus')
    assert not any(l['namespace']=='agentos-launcher' and l['mapped'] for l in scene()['system_layers'])
    def click_terminal():
        point=observe('local-terminal:snapshot')['point'];g=terminal()['geometry']
        pointer.click(g['x']+point[0],g['y']+point[1],width,height)
        wait(lambda:observe('local-terminal:snapshot')['focused'],'Kernel pointer did not focus local shell')
    click_terminal()
    for key in [18,46,35,24,57,38,24,46,30,38,24,37]:keyboard.chord(key) # echo localok
    keyboard.chord(28)
    wait(lambda:'\nlocalok\n' in observe('local-terminal:snapshot')['text'],'Kernel typing did not execute in local shell')
    span=observe('local-terminal:copy-span');g=terminal()['geometry']
    pointer.drag([g['x']+span['start'][0],g['y']+span['start'][1]],[g['x']+span['end'][0],g['y']+span['end'][1]],width,height)
    point=observe('local-terminal:snapshot')['point']
    pointer.click(g['x']+point[0],g['y']+point[1],width,height,button=273)
    assert wait(lambda:observe('local-terminal:menu-copy'),'Local context menu missing')['sensitive']
    assert observe('local-terminal:menu-copy-activate')['requested']
    wait(lambda:observe('local-terminal:snapshot')['focused'] and scene()['seat_focus']==window['id'],'Copy did not return local and seat focus')
    source=next(w for w in scene()['windows'] if w['title']=='Direct transfer source')
    def peer_button(label):
        point=observe('transfer:'+label)['point'];g=source['geometry']
        pointer.click(g['x']+point[0],g['y']+point[1],width,height)
        wait(lambda:scene()['seat_focus']==source['id'],'Clipboard peer did not receive focus')
        pointer.click(g['x']+point[0],g['y']+point[1],width,height)
    receipts=metrics/'transfer-receipts.json'
    peer_button('Read terminal clipboard')
    wait(lambda:json.loads(receipts.read_text()).get('copied')=='localok\n','Local menu Copy did not publish exact shell output')
    count=json.loads(receipts.read_text())['clipboard'];peer_button('Publish terminal clipboard')
    wait(lambda:json.loads(receipts.read_text())['clipboard']>count,'Unicode clipboard peer did not publish')
    click_terminal()
    keyboard.chord(42,68) # Shift+F10, same native menu as secondary click.
    assert wait(lambda:observe('local-terminal:menu-paste'),'Keyboard context menu missing')['sensitive']
    assert observe('local-terminal:menu-paste-activate')['requested']
    wait(lambda:'λ 日本語' in observe('local-terminal:snapshot')['text'] and observe('local-terminal:snapshot')['focused'],'Unicode menu Paste or focus return failed')
    keyboard.chord(29,21) # Ctrl+U clears the pasted shell input without executing it.
    pid=wait(lambda:json.loads((metrics/'local-terminal.json').read_text())['pid'],'Local shell PID was not recorded')
    keyboard.chord(29,42,17) # Ctrl+Shift+W closes this human-owned terminal.
    wait(lambda:not any(w['id']==window['id'] for w in scene()['windows']),'Local close shortcut failed')
    wait(lambda:not Path(f'/proc/{pid}').exists(),'Local close leaked its shell child')
    print('PASS: local Terminal kernel launch/typing, native mouse/keyboard Copy/Paste menus, exact output and Unicode clipboard, popup focus return, close shortcut and owned child cleanup',flush=True)
