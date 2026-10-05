#!/usr/bin/python3
"""Real broker output and assistant dispatch; provider calls are replaced by fixtures."""
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, '/usr/local/lib/agent-os/services')
import assistant
from broker_client import request

activity = json.loads(subprocess.check_output(['agent-os', 'create', 'File result verification']))['id']
checks = []
with tempfile.TemporaryDirectory(prefix='agent-os-file-result-') as tmp:
    root = Path(tmp)
    (root / 'ai').mkdir()
    for index, content in enumerate(('a' * 65536, '界' * 21845, '😀' * 16384)):
        path = root / str(index)
        path.write_text(content, encoding='utf-8')
        expected_argv = ['/usr/bin/python3', '/usr/local/lib/agent-os/services/files.py',
                         json.dumps({'op':'read','path':str(path)})]
        job = request('execute', activity=activity, argv=expected_argv,
            purpose='Read harmless large file fixture', request_confirmation=True, timeout_seconds=15)
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
            assert len(job['output'].encode()) <= 32768
            def route(op, **fields):
                if op == 'execute':
                    # Return only the already approved/executed harmless fixture;
                    # never bypass assessment for an actual new command.
                    assert fields['argv'] == expected_argv
                    return job
                return request(op, **fields)
            def workflow(prompt, history, cfg, dispatch, progress, record, **kw):
                result = dispatch('read_file', {'path':str(path)})
                assert 'error' not in result, result.get('error')
                assert result['file_result']['content'] == content
                assert result['file_result']['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
                assert not result['file_result']['truncated']
                return dict(text='Verified fixture.', model='fixture', finish_reason='stop',
                    messages=[{'role':'user','content':prompt},{'role':'assistant','content':'Verified fixture.'}])
            decisions = SimpleNamespace(select_history=lambda *a:[], select_memory=lambda *a:[], summary=lambda:{})
            with patch.object(assistant, 'STATE', root / 'ai'), patch.object(assistant, 'config', return_value={}), \
                 patch.object(assistant.model_usage, 'configure'), patch.object(assistant.knowledge, 'context', return_value=[]), \
                 patch.object(assistant, 'Decisions', return_value=decisions), patch.object(assistant, 'run_agent', side_effect=workflow), \
                 patch.object(assistant, 'broker_request', side_effect=route), patch.object(assistant, 'emit'), patch.object(assistant, 'send'):
                assistant.handle({'op':'ask','activity':activity,'prompt':'Read '+str(path)}, None)
            checks.append('Full content and hash: '+('ASCII', 'CJK', 'emoji')[index])
        finally:
            request('cancel', job_id=job['id'])
print(json.dumps({'result':'pass','checks':checks,'provider_calls':'fixtures; no live model inference'}))
