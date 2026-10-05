#!/usr/bin/python3
"""Run as developer. Exercise real reuse/deadlines; approve only these sleep fixtures."""
import json
import subprocess
import sys
import time
sys.path.insert(0, '/usr/local/lib/agent-os/services')
from broker_client import request

activity = json.loads(subprocess.check_output(['agent-os', 'create', 'Broker reuse verification']))['id']
argv = ['/usr/bin/sleep', '120']
created = set()

def execute(background, seconds):
    fields = {'lifetime_seconds' if background else 'timeout_seconds': seconds}
    job = request('execute', activity=activity, argv=argv, purpose='Harmless deadline/reuse fixture',
                  background=background, request_confirmation=True, **fields)
    created.add(job['id'])
    if job['status'] == 'approval_required':
        subprocess.run(['sudo', '-n', 'agent-os-broker', 'approve', job['id']],
                       check=True, stdout=subprocess.DEVNULL)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        job = request('poll', job_id=job['id'])
        if job['status'] == 'running':
            state = subprocess.check_output(['systemctl', 'show',
                'agent-os-exec-' + job['id'] + '.service', '--property=ActiveState'], text=True)
            if state.strip() == 'ActiveState=active':
                return job
        time.sleep(.1)
    raise AssertionError('Fixture did not start')

try:
    foreground = execute(False, 30)
    background = execute(True, 30)
    longer = execute(True, 60)
    assert len({foreground['id'], background['id'], longer['id']}) == 3
    assert not foreground['background'] and foreground['timeout_seconds'] == 30
    assert background['background'] and background['timeout_seconds'] == 30
    assert longer['background'] and longer['timeout_seconds'] == 60
    retry = execute(True, 60)
    assert retry['id'] == longer['id'], retry
    assert len(request('list', activity=activity)) == 3
    for job in (background, longer):
        setting = subprocess.check_output(['systemctl', 'show',
            'agent-os-exec-' + job['id'] + '.service', '--property=RuntimeMaxUSec', '--value'], text=True).strip()
        assert setting == {30: '30s', 60: '1min'}[job['timeout_seconds']], setting
    print(json.dumps({'result': 'pass', 'checks': [
        'Foreground and background requests have distinct real units',
        'Different lifetimes have distinct real units and matching systemd deadlines',
        'Identical background retry retains its ID without launching another unit']}))
finally:
    for ident in created:
        request('cancel', job_id=ident)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if all(request('poll', job_id=ident)['status'] not in ('starting', 'running', 'cancelling') for ident in created):
            break
        time.sleep(.1)
    else:
        raise AssertionError('A reuse fixture failed to stop')
