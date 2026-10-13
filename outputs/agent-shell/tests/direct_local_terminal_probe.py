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
    wait(lambda:'λ 日本語' in observe('local-terminal:snapshot')['text'] and observe('local-terminal:snapshot')['focused'] and scene()['seat_focus']==window['id'],'Unicode menu Paste or focus return failed')
    keyboard.chord(29,22) # Ctrl+U clears the pasted shell input without executing it.
    def prompt_ready():
        lines=[line for line in observe('local-terminal:snapshot')['text'].splitlines() if line.strip()]
        return bool(lines) and lines[-1].rstrip().endswith('$')
    wait(prompt_ready,'Clear-line command did not reach the local shell')
    pid=wait(lambda:json.loads((metrics/'local-terminal.json').read_text())['pid'],'Local shell PID was not recorded')
    parent=int(Path(f'/proc/{pid}/stat').read_text().split(') ',1)[1].split()[1])
    assert Path(f'/proc/{pid}/cgroup').read_text()==Path(f'/proc/{parent}/cgroup').read_text(),'Local shell escaped its owned graphical login scope'
    def work_children():
        children=Path(f'/proc/{pid}/task/{pid}/children').read_text().split()
        return [int(child) for child in children if Path(f'/proc/{child}/comm').read_text().strip()=='sleep']
    def start_sleep(background=False):
        for key in [31,38,18,18,25,57,7,11]:keyboard.chord(key) # sleep 60
        if background:keyboard.chord(57);keyboard.chord(42,8) # &
        keyboard.chord(28)
        try:return wait(work_children,'Owned sleep did not start')[0]
        except RuntimeError:
            print('Owned command diagnostic',observe('local-terminal:snapshot'),scene()['keyboard_pressed_count'],flush=True);raise
    foreground=start_sleep()
    keyboard.chord(29,42,17)
    wait(lambda:observe('local-terminal:close-cancel')['showing'],'Running foreground work did not open close confirmation')
    assert Path(f'/proc/{pid}').exists() and Path(f'/proc/{foreground}').exists(),'Close terminated work before confirmation'
    for _ in range(4):
        keyboard.chord(15) # Tab stays inside the confirmation.
        wait(lambda:observe('local-terminal:close-cancel')['dialog_focus'],'Confirmation focus escaped into the terminal toolbar')
    point=observe('local-terminal:close-cancel')['point'];g=terminal()['geometry']
    pointer.click(g['x']+point[0],g['y']+point[1],width,height)
    wait(lambda:observe('local-terminal:snapshot')['focused'],'Pointer Cancel did not restore terminal focus')
    assert Path(f'/proc/{foreground}/stat').read_text().split(') ',1)[1].split()[0]!='Z','Pointer Cancel ended foreground work'
    keyboard.chord(29,42,17)
    wait(lambda:observe('local-terminal:close-cancel')['showing'],'Close shortcut did not reopen confirmation')
    keyboard.chord(1) # Escape also cancels, retaining the foreground program.
    wait(lambda:observe('local-terminal:snapshot')['focused'],'Cancel did not restore local terminal focus')
    assert Path(f'/proc/{foreground}').exists() and Path(f'/proc/{foreground}/stat').read_text().split(') ',1)[1].split()[0]!='Z','Cancel ended the foreground program'
    keyboard.chord(29,46) # Ctrl+C remains program input after Cancel.
    wait(lambda:not Path(f'/proc/{foreground}').exists(),'Cancel did not restore program input')
    wait(prompt_ready,'Foreground interrupt did not restore shell prompt')
    background=start_sleep(True)
    point=observe('local-terminal:window-close')['point'];g=terminal()['geometry']
    print('CHECK: native close target',point,g,flush=True)
    pointer.click(g['x']+point[0],g['y']+point[1],width,height)
    wait(lambda:observe('local-terminal:close-confirm')['showing'],'Background job did not open close confirmation')
    assert Path(f'/proc/{background}').exists(),'Background work ended before confirmation'
    point=observe('local-terminal:close-confirm')['point'];g=terminal()['geometry']
    pointer.click(g['x']+point[0],g['y']+point[1],width,height)
    wait(lambda:not Path(f'/proc/{background}').exists(),'Confirmed close leaked background work')
    wait(lambda:not any(w['id']==window['id'] for w in scene()['windows']),'Local close shortcut failed')
    wait(lambda:not Path(f'/proc/{pid}').exists(),'Local close leaked its shell child')
    keyboard.chord(29,56,57)
    launcher=wait(lambda:next((l for l in scene()['system_layers'] if l['namespace']=='agentos-launcher' and l['mapped']),None),'Launcher did not reopen after terminal close')
    point=observe('local-terminal:launcher-button')['point'];g=launcher['geometry']
    pointer.click(g['x']+point[0],g['y']+point[1],width,height)
    idle=wait(terminal,'Second idle terminal did not map')
    wait(lambda:scene()['seat_focus']==idle['id'] and scene()['shared']['focus']==idle['id'],'Idle terminal did not receive focus')
    idle_pid=wait(lambda:json.loads((metrics/'local-terminal.json').read_text())['pid'] if json.loads((metrics/'local-terminal.json').read_text())['pid']!=pid else None,'New shell PID was not recorded')
    keyboard.chord(29,42,17)
    wait(lambda:not any(w['id']==idle['id'] for w in scene()['windows']),'Idle terminal unnecessarily blocked closing')
    wait(lambda:not Path(f'/proc/{idle_pid}').exists(),'Idle close leaked its child')
    print('PASS: local Terminal kernel launch/typing, mouse/keyboard clipboard menus, exact output and Unicode paste, foreground/background close guard, cancel/input restoration, idle close and owned child cleanup',flush=True)
