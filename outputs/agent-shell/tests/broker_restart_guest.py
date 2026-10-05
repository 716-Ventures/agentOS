#!/usr/bin/python3
"""Run as developer in the guest. Restarts the broker and stops its harmless fixture."""
import json
import subprocess
import sys
import time
sys.path.insert(0, '/usr/local/lib/agent-os/services')
from broker_client import request

activity = json.loads(subprocess.check_output(['agent-os', 'create', 'Broker restart verification']))['id']
# This unapproved printf is harmless; the literal hazard marker creates a proposal.
pending = request('execute', activity=activity, argv=['/usr/bin/printf', '%s', 'rm '],
                  purpose='Unapproved harmless restart fixture')
assert pending['status'] == 'approval_required', pending
code = '''import os, signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = os.fork()
if child == 0:
    os.setsid()
    while True: time.sleep(1)
print(os.getpid(), child, flush=True)
while True: time.sleep(1)
'''
job = request('execute', activity=activity, argv=['/usr/bin/python3', '-u', '-c', code],
              purpose='Restart stops a parent and detached child fixture',
              background=True, lifetime_seconds=120, request_confirmation=True)
if job['status'] == 'approval_required':
    subprocess.run(['sudo', '-n', 'agent-os-broker', 'approve', job['id']],
                   check=True, stdout=subprocess.DEVNULL)
try:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        running = request('poll', job_id=job['id'])
        if running['status'] == 'running' and running['output'].strip():
            break
        time.sleep(.1)
    else:
        raise AssertionError('Fixture failed to start')
    pids = [int(value) for value in running['output'].split()]
    assert len(pids) == 2, running
    subprocess.run(['sudo', '-n', 'systemctl', 'restart', 'agent-os-broker'], check=True)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            recovered = request('poll', job_id=job['id'])
            break
        except (RuntimeError, OSError):
            time.sleep(.1)
    else:
        raise AssertionError('Broker failed to recover')
    assert recovered['status'] == 'interrupted', recovered
    assert recovered['finished_at'] >= running['created_at'], recovered
    for pid in pids:
        result = subprocess.run(['sudo', '-n', 'kill', '-0', str(pid)], capture_output=True)
        assert result.returncode != 0, f'Process {pid} survived restart'
    kept = request('poll', job_id=pending['id'])
    assert kept['status'] == 'approval_required', kept
    assert kept['output'] == '', kept
    subprocess.run(['sudo', '-n', 'systemctl', 'restart', 'agent-os-broker'], check=True)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            again = request('poll', job_id=job['id'])
            break
        except (RuntimeError, OSError):
            time.sleep(.1)
    else:
        raise AssertionError('Second recovery failed')
    assert again['finished_at'] == recovered['finished_at'], again
    assert again['output'] == recovered['output'], again
    print(json.dumps({'result': 'pass', 'checks': [
        'Broker restart stops root command and detached child',
        'Interrupted status and completion time are persisted',
        'Unapproved proposal survives without execution',
        'Second restart preserves evidence without replay']}))
finally:
    # Reject only this test's proposal and stop only this test's command.
    request('cancel', job_id=pending['id'])
    request('cancel', job_id=job['id'])
