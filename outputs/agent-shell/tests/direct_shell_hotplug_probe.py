"""Kernel input through live shell overlays after virtual output recovery."""
import json
from pathlib import Path
import subprocess
import time


def verify(scene, target, snapshot, keyboard, pointer):
    connectors = [Path('/sys/class/drm/card0-Virtual-'+str(i)) for i in (1, 2)]
    assert all((p/'status').read_text().strip() == 'connected' for p in connectors)
    device = (connectors[0].parent/'card0'/'device').resolve()
    identity = dict(line.split('=', 1) for line in (device/'uevent').read_text().splitlines() if '=' in line)
    assert (device/'driver').resolve().name == 'virtio-pci' and identity.get('PCI_ID') == '1AF4:1050'

    def wait(predicate, message):
        deadline = time.monotonic()+10
        while True:
            value = predicate()
            if value:return value
            assert time.monotonic() < deadline, (message, scene())
            time.sleep(.03)

    def layers(namespace):
        return [r for r in scene()['system_layers'] if r['namespace'] == namespace and r['mapped']]

    def force(connector, value):
        (connector/'status').write_text(value)
        subprocess.run(['udevadm', 'trigger', '--action=change', '--subsystem-match=drm', '--sysname-match=card0'], check=True)
        subprocess.run(['udevadm', 'settle', '--timeout=5'], check=True)

    def dimensions():
        outputs = scene()['outputs']
        return max(o['x']+o['width'] for o in outputs), max(o['y']+o['height'] for o in outputs)

    def click_key(name):
        layer = wait(lambda: next(iter(layers('agentos-keyboard')), None), 'Keyboard missing')
        output = next(o for o in scene()['outputs'] if o['name'] == layer['output'])
        point = snapshot('keyboard:'+name)['point']
        pointer.click(output['x']+layer['geometry']['x']+point[0], output['y']+layer['geometry']['y']+point[1], *dimensions())

    original = snapshot()['text']
    preferred = {k:v['outputs'] for k,v in scene()['shared']['workspaces'].items()}
    window = wait(lambda: next((w for w in scene()['windows'] if w['id'] == target and w['geometry']), None), 'Editor missing')
    g = window['geometry']
    point = snapshot()['field']
    pointer.click(g['x']+point[0], g['y']+point[1], *dimensions())
    wait(lambda: snapshot()['focused'] and scene()['seat_focus'] == target, 'Editor focus missing')
    keyboard.chord(29, 107)  # Ctrl+End preserves any initial text.
    typed = ''
    try:
        keyboard.chord(29, 56, 37)
        osk = wait(lambda: next(iter(layers('agentos-keyboard')), None), 'Keyboard did not map')
        click_key('a')
        wait(lambda: snapshot()['text'] == original+'a', 'Initial keyboard input missing')
        keyboard.chord(29, 56, 57)
        launcher = wait(lambda: next(iter(layers('agentos-launcher')), None), 'Launcher did not map')
        wait(lambda: snapshot('launcher-request')['focused'] and scene()['seat_focus'] == launcher['id'], 'Launcher did not take focus')
        request = snapshot('launcher-request')['text']
        keyboard.chord(29, 107)
        bar = next(iter(layers('agentos-system-bar')))
        identities = {r['namespace']:r['id'] for r in (bar, osk, launcher)}
        for phase, outputs in [('primary-removed', {'Virtual-2'}), ('all-restored-secondary-first', {'Virtual-2'}), ('primary-reconnected', {'Virtual-1', 'Virtual-2'})]:
            if phase == 'primary-removed':force(connectors[0], 'off')
            elif phase == 'all-restored-secondary-first':
                force(connectors[1], 'off')
                wait(lambda: not scene()['outputs'], 'No-output state missing')
                assert any(w['id'] == target for w in scene()['windows']), 'Work lost without displays'
                print('Shell overlays: no outputs, original editor identity retained', flush=True)
                force(connectors[1], 'on')
            else:force(connectors[0], 'on')
            wait(lambda: {o['name'] for o in scene()['outputs']} == outputs, 'Output transition missing')
            for namespace, ident in identities.items():
                wait(lambda: any(r['id'] == ident for r in layers(namespace)), 'Original layer missing: '+namespace)
            wait(lambda: scene()['seat_focus'] == launcher['id'] and snapshot('launcher-request')['focused'], 'Launcher focus lost: '+phase)
            assert snapshot('launcher-request')['text'] == request+typed, 'Launcher draft changed during recovery'
            assert snapshot()['text'] == original+'a', 'Editor draft changed during recovery'
            assert {k:v['outputs'] for k,v in scene()['shared']['workspaces'].items()} == preferred, 'Recovery changed durable output preferences'
            assert scene()['keyboard_pressed_count'] == 0, 'Unbalanced key after recovery'
            click_key('a');typed += 'a'
            wait(lambda: snapshot('launcher-request')['text'] == request+typed, 'Recovered keyboard did not type into launcher')
            state = scene()
            print('Shell overlay recovery: '+json.dumps({'phase':phase, 'outputs':state['outputs'], 'layers':state['system_layers'], 'seat_focus':state['seat_focus'], 'original_layer_ids':identities, 'launcher_appended_text':typed, 'editor_text_preserved':True}), flush=True)
        keyboard.chord(29, 107)
        for _ in typed:keyboard.chord(14)
        wait(lambda: snapshot('launcher-request')['text'] == request, 'Original unsent request not restored')
        keyboard.chord(1)
        wait(lambda: not layers('agentos-launcher') and scene()['seat_focus'] == target, 'Launcher close did not restore editor')
        click_key('b')
        wait(lambda: snapshot()['text'] == original+'ab', 'Recovered keyboard did not return to editor')
        keyboard.chord(14);keyboard.chord(14)
        wait(lambda: snapshot()['text'] == original, 'Original editor text not restored')
        click_key('Hide keyboard')
        wait(lambda: not layers('agentos-keyboard') and scene()['seat_focus'] == target, 'Keyboard hide/focus failed')
        bar = next(iter(layers('agentos-system-bar')))
        output = next(o for o in scene()['outputs'] if o['name'] == bar['output'])
        assert bar['work_area']['height'] == output['height']-bar['geometry']['height'], 'Keyboard reservation not released'
        assert scene()['keyboard_pressed_count'] == 0
        print('PASS: same launcher and keyboard survive primary and all-output loss; trusted pointer typing, retained drafts, focus return, work-area restoration and balanced keys', flush=True)
    finally:
        for connector in connectors:force(connector, 'on')
        if layers('agentos-launcher'):keyboard.chord(1)
        if layers('agentos-keyboard'):keyboard.chord(29, 56, 37)
