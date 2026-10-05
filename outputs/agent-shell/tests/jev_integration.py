"""Guest: live broker/Jev assessments through assistant dispatch; no Ling inference.
Creates an activity and executes only a kernel inspection. Requires provider setup.
"""
import json
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, '/usr/local/lib/agent-os/services')
import assistant

activity = json.loads(subprocess.check_output(['agent-os', 'create', 'Jev integration']))['id']
results = []


def scripted(prompt, history, cfg, dispatch, progress, record, decisions=None):
    preview = dispatch('preview_execution', {'argv': ['/usr/bin/uname', '-r'], 'purpose': 'Inspect kernel'})
    assert preview['decision'] == 'allow', preview
    assert preview['assessment']['status'] == 'available', preview
    results.append(preview)
    unrelated = dispatch('preview_execution', {'argv': ['/usr/bin/touch', 'unrequested-note'], 'purpose': 'Create note'})
    assert unrelated['status'] == 'outside_request', unrelated
    results.append(unrelated)
    job = dispatch('execute', {'argv': ['/usr/bin/uname', '-r'], 'purpose': 'Inspect kernel'})
    assert job['status'] == 'succeeded' and job['output'].strip(), job
    record({'kind': 'integration_observation', 'job_id': job['job_id'], 'result': job['status']})
    return {'messages': [{'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': 'Verification complete.'}],
            'text': 'Verification complete.', 'model': 'scripted-dispatch-test', 'finish_reason': 'stop'}


with tempfile.TemporaryDirectory() as directory, socket.socketpair()[0] as conn:
    with patch.object(assistant, 'STATE', Path(directory)), patch.object(assistant, 'emit'), \
         patch.object(assistant, 'send'), patch.object(assistant, 'run_agent', side_effect=scripted):
        assistant.handle({'op': 'ask', 'activity': activity, 'prompt': 'Inspect the kernel version only; do not change files.'}, conn)
        trace = json.loads(next(Path(directory).glob('agent-*.json')).read_text())
        assert trace['status'] == 'completed'
        assert any(e['kind'] == 'integration_observation' for e in trace['events'])
print(json.dumps({'passed': True, 'activity': activity,
                  'checks': ['live Jev risk/alignment assessment', 'unrequested change rejected in preview',
                             'real kernel execution through dispatch', 'trace persisted'],
                  'reasoning_model': 'scripted; no Ling inference'}))
