#!/usr/bin/python3
"""Two virtual outputs: real kernel input and output-named Wayland receipts."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import uuid


def verify(env, metrics, core, scene, login_user, presentation, keyboard, pointer):
    outputs = scene()['outputs']
    assert len(outputs) == 2 and {o['name'] for o in outputs} == {'Virtual-1', 'Virtual-2'}, outputs
    assert all(o['scale'] == 1 and o['transform'] == 'Normal' and o['x'] >= 0 and o['y'] >= 0 for o in outputs), outputs
    width = max(o['x'] + o['width'] for o in outputs)
    height = max(o['y'] + o['height'] for o in outputs)
    endpoint = metrics/'multi-output-client.sock'
    binary = Path(__file__).resolve().parents[1]/'native-compositor/target/debug/examples/presentation_fixture'
    log_path = metrics/'multi-output-client.log'
    results = []
    with log_path.open('w') as log:
        client = subprocess.Popen(['runuser', '-u', login_user, '--', str(binary), str(endpoint)], env=env,
                                  stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        def wait(predicate, meaning):
            deadline = time.monotonic() + 10
            while True:
                if client.poll() is not None:raise RuntimeError('Fixture exited: '+log_path.read_text()[-4096:])
                value = predicate()
                if value:return value
                if time.monotonic() > deadline:
                    observed = scene()
                    print('Multi-output failure state: '+json.dumps({key: observed.get(key) for key in ('outputs','windows','seat_focus','pointer_location','pointer_routing','shared')}), flush=True)
                    print('Multi-output failure receipts: '+json.dumps(method('status')), flush=True)
                    raise RuntimeError(meaning)
                time.sleep(.02)
        def method(op):
            with socket.socket(socket.AF_UNIX) as conn:
                conn.settimeout(3);conn.connect(str(endpoint))
                conn.sendall(json.dumps({'op': op}).encode()+b'\n')
                with conn.makefile('rb') as reader:line = reader.readline(65537)
            assert len(line) <= 65536 and line.endswith(b'\n'), 'Invalid fixture response'
            value = json.loads(line)
            assert value['ok'], value
            return value
        try:
            wait(endpoint.exists, 'Fixture socket missing')
            assert method('status')['clock_id'] == time.CLOCK_MONOTONIC
            ident = method('map')['id']
            wait(lambda: any(r['id'] == ident and r['kind'] == 'presented' for r in method('status')['receipts']), 'Initial frame missing')
            def window():
                observed = scene()
                return next((w for w in observed['windows'] if w['app_id'] == 'com.agentos.PresentationFixture' and w['id'] in observed['shared']['identities']), None)
            target = wait(window, 'Fixture workspace identity missing')
            activity = core('presentation.get')['activity_id']
            # Return to the first head as well, to exercise movement in both directions.
            for output in sorted(outputs, key=lambda o: o['x']) + [min(outputs, key=lambda o: o['x'])]:
                deadline = time.monotonic() + 8
                while True:
                    observed = scene()
                    logical = observed['shared']['identities'][target['id']]
                    workspace = next(w for w in observed['shared']['workspaces'].values() if w['activity_id'] == activity)
                    try:
                        receipt = presentation({'op': 'presentation.apply', 'protocol': 'agentos.presentation/1', 'catalog_revision': 'native-core/1',
                            'request_id': 'multi-output-'+uuid.uuid4().hex, 'expected_revisions': {workspace['workspace_id']: workspace['revision']},
                            'operations': [{'op': 'workspace.edit', 'workspace_id': workspace['workspace_id'],
                                            'edit': {'kind': 'float', 'surface_id': logical, 'output_id': 'drm-'+output['name'], 'x': 100, 'y': 120, 'width': 200, 'height': 160}},
                                           {'op': 'workspace.edit', 'workspace_id': workspace['workspace_id'],
                                            'edit': {'kind': 'focus', 'surface_id': logical, 'element_id': None}}]})
                        assert receipt['status'] == 'committed', receipt
                        break
                    except RuntimeError as exc:
                        if '"code":"stale_revision"' not in str(exc) or time.monotonic() > deadline:raise
                        time.sleep(.02)
                area = next((layer['work_area'] for layer in scene()['system_layers']
                             if layer['mapped'] and layer['namespace'] == 'agentos-system-bar'
                             and layer['work_area']['x'] == output['x'] and layer['work_area']['width'] == output['width']), output)
                def placed():
                    row = window()
                    if not row:return None
                    g = row['geometry']
                    return row if (g and g['x'] == area['x']+100 and g['y'] == area['y']+120 and
                        g['x']+g['width'] <= output['x']+output['width'] and g['y']+g['height'] <= output['y']+output['height'] and
                        row['xdg']['configured'] and row['xdg']['pending_count'] == 0 and row['xdg']['acked_size'] == [200, 160]) else None
                row = wait(placed, 'Fixture did not settle wholly on '+output['name'])
                print('Multi-output placed client: '+json.dumps(row), flush=True)
                g = row['geometry']
                bar = next(layer for layer in scene()['system_layers'] if layer['namespace'] == 'agentos-system-bar' and layer['mapped'])
                bg = bar['geometry']
                pointer.click(bg['x']+bg['width']//2, bg['y']+bg['height']//2, width, height)
                wait(lambda: scene()['seat_focus'] == bar['id'], 'System bar did not take deliberate pointer focus')
                pointer.click(g['x']+16, g['y']+16, width, height)
                def pointer_focused():
                    observed = scene()
                    return observed['seat_focus'] == target['id'] and observed['pointer_routing']['under'] == target['id']
                wait(pointer_focused, 'Pointer did not focus fixture on '+output['name'])
                samples = []
                for _ in range(20):
                    previous = max(r['id'] for r in method('status')['receipts'])
                    keyboard.chord(30)
                    event = wait(lambda: next((r for r in method('status')['receipts'] if r['id'] > previous and r['kind'] == 'presented' and r['key_time_ms'] is not None), None), 'Key frame missing on '+output['name'])
                    assert event['outputs'] == [output['name']], event
                    assert event['flags'] & 1 and event['refresh_ns'] > 0, event
                    assert abs(time.monotonic_ns()-event['time_ns']) < 2_000_000_000, event
                    assert ((event['time_ns']//1_000_000)-event['key_time_ms']) & 0xffffffff < 2000, event
                    samples.append(event)
                results.append({'output': output, 'placement': g, 'pointer': scene()['pointer_location'], 'receipts': samples})
                print('Completed output journey: '+json.dumps(results[-1]), flush=True)
            method('unmap')
            wait(lambda: target['id'] not in scene()['shared']['identities'], 'Unmapped fixture stayed published')
            print('Two-output receipt evidence: '+json.dumps({'physical_display_qualified': False, 'native_gtk_latency_qualified': False, 'journeys': results}), flush=True)
            print('PASS: kernel pointer and keyboard input with 60 named KMS presentation receipts across both virtual outputs and return movement', flush=True)
        finally:
            if client.poll() is None:
                try:method('stop')
                except (OSError, RuntimeError, AssertionError):pass
                try:client.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(client.pid, signal.SIGTERM)
                    try:client.wait(timeout=3)
                    except subprocess.TimeoutExpired:os.killpg(client.pid, signal.SIGKILL);client.wait(timeout=3)
