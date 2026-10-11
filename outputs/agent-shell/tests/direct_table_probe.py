#!/usr/bin/python3
"""Installed read-only Table journey through kernel input and a separate client."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid


def verify(metrics, output, core, scene, login_user, presentation, observe, keyboard, pointer, env, kind="Table@1"):
    activity = str(core('presentation.get')['activity_id'])
    surface = 'kernel-' + kind.split('@')[0].lower() + '-' + uuid.uuid4().hex
    peer = None
    receipts = metrics / 'table-clipboard-receipts.json'

    def wait(test, message):
        deadline = time.monotonic() + 10
        last = None
        while True:
            try:
                last = test()
                if last:
                    return last
            except (RuntimeError, LookupError, StopIteration, OSError, ValueError) as exc:
                last = str(exc)
            if time.monotonic() > deadline:
                raise RuntimeError(message + ': ' + repr(last))
            time.sleep(.05)

    def window(logical):
        current = scene()
        return next((row for row in current['windows'] if current['shared']['identities'].get(row['id']) == logical), None)

    work_area=next(layer['work_area'] for layer in scene()['system_layers'] if layer['namespace']=='agentos-system-bar' and layer['mapped'])

    def place(logical, x, width):
        deadline = time.monotonic() + 10
        while True:
            workspace = next(doc for doc in scene()['shared']['workspaces'].values() if doc['activity_id'] == activity)
            try:
                result = presentation({'op': 'presentation.apply', 'protocol': 'agentos.presentation/1', 'catalog_revision': 'native-core/1',
                    'request_id': surface + '-place-' + uuid.uuid4().hex, 'expected_revisions': {workspace['workspace_id']: workspace['revision']},
                    'operations': [{'op': 'workspace.edit', 'workspace_id': workspace['workspace_id'], 'edit': {'kind': 'float', 'surface_id': logical,
                        'output_id': next(iter(workspace['outputs'])), 'x': x, 'y': 0, 'width': width, 'height': 400}}]})
                assert result['status'] == 'committed', result
                break
            except RuntimeError as exc:
                if '"code":"stale_revision"' not in str(exc) or time.monotonic() > deadline:
                    raise
                time.sleep(.05)
        observed=[]
        expected={'x': x, 'y': work_area['y'], 'width': width, 'height': 400}
        def placed():
            current=scene()
            row=next((row for row in current['windows'] if current['shared']['identities'].get(row['id'])==logical),None)
            sample={'geometry':row['geometry'] if row else None,'xdg':row.get('xdg') if row else None,'work_areas':[layer['work_area'] for layer in current['system_layers'] if layer['namespace']=='agentos-system-bar' and layer['mapped']]}
            if not observed or observed[-1]!=sample:
                observed.append(sample)
                if len(observed)>8:observed.pop(0)
            return sample['geometry']==expected
        try:
            wait(placed, 'Table fixture placement was not applied')
        except RuntimeError as exc:
            current=scene()
            raise RuntimeError(str(exc)+'; placement diagnostics: '+json.dumps({'expected':expected,'observed':observed,'workspace':next((doc for doc in current['shared']['workspaces'].values() if doc['activity_id']==activity),None),'outputs':current['outputs']})) from exc
        print('CHECK: collection placement '+json.dumps({'expected':expected,'observed':observed}),flush=True)

    def click(logical, point, button=272):
        geometry = window(logical)['geometry']
        pointer.click(geometry['x'] + point[0], geometry['y'] + point[1], output['width'], output['height'], button=button)
        if button == 272:
            wait(lambda: scene()['seat_focus'] == window(logical)['id'], 'Clipboard fixture did not receive seat focus')

    def source_click(label):
        point = observe('transfer:' + label)['point']
        click(peer_id, point)
        click(peer_id, point)

    def sentinel():
        before = json.loads(receipts.read_text())['clipboard']
        source_click('Publish terminal clipboard')
        wait(lambda: json.loads(receipts.read_text())['clipboard'] > before, 'Peer did not publish clipboard sentinel')

    def read(expected):
        before = json.loads(receipts.read_text()).get('reads', 0)
        source_click('Read terminal clipboard')
        wait(lambda: json.loads(receipts.read_text()).get('reads', 0) > before, 'Peer did not finish a new clipboard read')
        assert json.loads(receipts.read_text())['copied'] == expected, json.loads(receipts.read_text())

    def menu_enabled(expected=True):
        state = observe('terminal-menu:Copy selected row')
        return state['showing'] and state['sensitive'] == expected

    def cells(label, status):
        return [label] if kind == 'List@1' else [label, status]

    def copied(label, status):
        return '\t'.join(cells(label, status))

    def menu_showing():
        try:
            return observe('terminal-menu:Copy selected row')['showing']
        except RuntimeError as exc:
            # GTK removes a dismissed popup from the accessibility tree.
            # Observer failures or unrelated missing controls are not closure.
            if 'accessible control unavailable: Copy selected row;' in str(exc):
                return False
            raise

    def menu_closed(label):
        wait(lambda: not menu_showing(), 'Copy menu did not finish dismissing')
        wait(lambda: scene()['seat_focus'] == window(surface)['id'], 'Closed Copy popup did not restore seat focus')
        wait(lambda: observe('table-cell:'+label)['focused'], 'Copy menu did not restore local collection focus')

    props = {'label': 'Kernel copy collection', 'rows': [
        {'id': 'document', 'cells': cells('Document λ 日本語', 'Saved')}, {'id': 'other', 'cells': cells('Other row', 'Observed')}]}
    if kind == 'Table@1':
        props['columns'] = ['Resource', 'Status']

    def update(rows, blocked=False):
        props['rows'] = rows
        deadline = time.monotonic() + 8
        while True:
            document = presentation({'op': 'presentation.get', 'document_id': surface})
            try:
                result = presentation({'op': 'presentation.apply', 'protocol': 'agentos.presentation/1', 'catalog_revision': 'native-core/1',
                    'request_id': surface + '-update-' + uuid.uuid4().hex, 'expected_revisions': {surface: document['revision']},
                    'operations': [{'op': 'element.set_props', 'surface_id': surface, 'element_id': 'table', 'props': props}]})
            except RuntimeError as exc:
                # Retry only a definite no-mutation interaction refusal while
                # the native focus-release message reaches the core.
                if '\"code\":\"interaction_conflict\"' not in str(exc):
                    raise
                if blocked:
                    assert presentation({'op': 'presentation.get', 'document_id': surface})['revision'] == document['revision']
                    return
                if time.monotonic() > deadline:
                    raise
                time.sleep(.05)
                continue
            assert not blocked, 'Focused Table update bypassed its interaction guard'
            assert result['status'] == 'committed', result
            return

    def select(label):
        point = observe('table-cell:' + label)['point']
        click(surface, point)
        click(surface, point)
        wait(lambda: observe('table-cell:' + label)['selected'], 'Kernel pointer did not select the Table row')

    try:
        document = {'protocol': 'agentos.presentation/1', 'catalog_revision': 'native-core/1', 'surface_id': surface, 'activity_id': activity,
            'revision': 0, 'title': 'Kernel '+kind+' fixture', 'root': 'table', 'elements': {'table': {'type': kind, 'props': props}}, 'bindings': {}, 'actions': {}}
        result = presentation({'op': 'presentation.apply', 'protocol': 'agentos.presentation/1', 'catalog_revision': 'native-core/1',
            'request_id': surface + '-create', 'expected_revisions': {surface: None}, 'operations': [{'op': 'surface.create', 'document': document}]})
        assert result['status'] == 'committed', result
        wait(lambda: window(surface), 'Installed Table did not map')
        place(surface, 0, 900)
        with (metrics / 'table-clipboard-peer.log').open('w') as log:
            peer = subprocess.Popen(['runuser', '-u', login_user, '--', 'python3', str(Path(__file__).with_name('direct_input_probe.py')),
                '--transfer-source', str(receipts), '--terminal-clipboard'], env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        def find_peer():
            current = scene()
            row = next((row for row in current['windows'] if row['title'] == 'Direct transfer source'), None)
            return current['shared']['identities'].get(row['id']) if row else None
        peer_id = wait(find_peer, 'Table clipboard peer did not register')
        place(peer_id, 980, 300)
        sentinel()
        select('Document λ 日本語')
        keyboard.chord(108)  # Down selects the following row through GTK.
        wait(lambda: observe('table-cell:Other row')['selected'], 'Table keyboard navigation did not select the following row')
        keyboard.chord(103)
        wait(lambda: observe('table-cell:Document λ 日本語')['selected'], 'Table keyboard navigation did not return to the document')
        keyboard.chord(29, 46)
        read(copied('Document λ 日本語','Saved'))

        sentinel()
        select('Document λ 日本語')
        keyboard.chord(42, 68)
        wait(lambda: menu_enabled(), 'Kernel Shift+F10 did not open the Table menu')
        next_rows = [{'id': 'other', 'cells': cells('Other row', 'Observed')}, {'id': 'document', 'cells': cells('Updated λ 日本語', 'Current')}]
        update(next_rows, blocked=True)
        wait(lambda: observe('table-cell:Document λ 日本語')['selected'], 'Rejected refresh changed selection')
        keyboard.chord(28)  # Activate the focused menu item with real Enter.
        menu_closed('Document λ 日本語')
        read(copied('Document λ 日本語','Saved'))
        update(next_rows)
        wait(lambda: observe('table-cell:Updated λ 日本語')['selected'], 'Reconciliation did not preserve selected row identity')

        sentinel()
        select('Updated λ 日本語')
        click(surface, observe('table-cell:Updated λ 日本語')['point'], button=273)
        wait(lambda: menu_enabled(), 'Secondary click did not open Table menu')
        assert observe('terminal-menu:Copy selected row-activate')['requested']
        menu_closed('Updated λ 日本語')
        read(copied('Updated λ 日本語','Current'))

        sentinel()
        select('Updated λ 日本語')
        keyboard.chord(29, 57)  # Ctrl+Space clears the current row selection.
        wait(lambda: not observe('table-cell:Updated λ 日本語')['selected'], 'Kernel selection toggle did not clear the row')
        keyboard.chord(29, 46)  # Empty selection cannot replace the sentinel.
        click(surface, observe('table-cell:Updated λ 日本語')['point'], button=273)
        wait(lambda: menu_enabled(False), 'Cleared selection left Copy enabled')
        keyboard.chord(1)
        wait(lambda: not menu_showing(), 'Empty-selection menu did not dismiss')
        wait(lambda: scene()['seat_focus'] == window(surface)['id'], 'Dismissed empty-selection menu did not restore seat focus')
        read(' λ 日本語')
        update([])
        def removed():
            try:
                observe('table-cell:Updated λ 日本語')
            except RuntimeError as exc:
                if 'accessible control unavailable: Updated λ 日本語;' in str(exc):
                    return True
                raise
            return False
        wait(removed, 'Removed collection row remained visible')
        read(' λ 日本語')
        print('PASS: installed '+kind+' kernel pointer/keyboard selection, Ctrl+C, Shift+F10/secondary menu, exact separate-client Unicode clipboard, focused refresh rejection, key-preserved reorder/update after focus release, empty-selection Copy rejection, row removal and focus restoration')
    finally:
        if peer:
            if peer.poll() is None:
                os.killpg(peer.pid, signal.SIGTERM)
            try:
                peer.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(peer.pid, signal.SIGKILL)
                peer.wait(timeout=3)
