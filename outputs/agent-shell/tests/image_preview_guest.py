#!/usr/bin/python3
"""Assessed PNG preview through installed systemd broker and core services.

Provider decisions are fixtures; approval applies only to this harmless PNG read.
"""
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, '/usr/local/lib/agent-os/services')
from broker_client import request
from presentation_client import request as presentation

activity = json.loads(subprocess.check_output(['agent-os', 'create', 'PNG preview verification']))['id']
path = Path(__file__).parent / 'fixtures/pixel.png'
descriptor = {'op': 'image', 'path': str(path), 'activity_id': activity,
              'label': 'Systemd preview pixel'}
job = request('execute', activity=activity,
              argv=['/usr/bin/python3', '/usr/local/lib/agent-os/services/files.py', json.dumps(descriptor)],
              purpose='Preview this harmless PNG fixture', request_confirmation=True, timeout_seconds=15)
if job['status'] == 'approval_required':
    subprocess.run(['sudo', '-n', 'agent-os-broker', 'approve', job['id']],
                   check=True, stdout=subprocess.DEVNULL)
try:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = request('poll', job_id=job['id'])
        if job['status'] not in ('starting', 'running', 'cancelling'):
            break
        time.sleep(.1)
    assert job['status'] == 'succeeded', job
    result = json.loads(job['output'])
    reference = result['resource']['reference']
    assert 'png_hex' not in job['output'] and path.read_bytes().hex() not in job['output']
    assert result['metadata']['kind'] == 'file' and job.get('file_source'), job
    document = presentation('presentation.get', document_id=result['surface_id'])
    assert document['elements']['image']['props']['reference'] == reference
    resource = presentation('resource.get', activity_id=str(activity), reference=reference)
    assert resource['png_hex'] == path.read_bytes().hex()
    script = '''import json,sys
sys.path.insert(0, '/usr/local/lib/agent-os/services')
from presentation_client import request
activity,reference=sys.argv[1:]
rows=request('resource.list',activity_id=activity)['resources']
assert any(row['reference']==reference for row in rows)
assert 'png_hex' not in json.dumps(rows)
try:request('resource.get',activity_id=activity,reference=reference)
except RuntimeError:pass
else:raise AssertionError('Model principal read private image bytes')
'''
    # Match the installed assistant unit's User=agentos-ai, Group=agentos.
    subprocess.run(['sudo', '-n', '/usr/sbin/runuser', '-u', 'agentos-ai', '-g', 'agentos', '--', '/usr/bin/python3', '-c', script,
                    str(activity), reference], check=True, timeout=10)
    print('PASS: assessed systemd PNG preview, durable view, human byte retrieval, file observation and model byte denial')
finally:
    request('cancel', job_id=job['id'])
