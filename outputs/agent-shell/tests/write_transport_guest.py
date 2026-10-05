#!/usr/bin/python3
"""Run as root in the development guest; approve only temporary-file fixtures."""
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

activity = json.loads(subprocess.check_output(['agent-os', 'create', 'Write transport verification']))['id']
checks = []

def execute(argv, content):
    job = request('execute', activity=activity, argv=argv, stdin=content,
                  purpose='Harmless write transport fixture', request_confirmation=True, timeout_seconds=15)
    assert 'stdin' not in job
    assert job['stdin_sha256'] == hashlib.sha256(content.encode()).hexdigest()
    assert request('input', job_id=job['id'])['stdin'] == content
    if job['status'] == 'approval_required':
        request('approve', job_id=job['id'])
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline:
            job = request('poll', job_id=job['id'])
            if job['status'] not in ('starting', 'running', 'cancelling'):
                return job
            time.sleep(.1)
        raise AssertionError('Fixture timed out')
    finally:
        request('cancel', job_id=job['id'])

with tempfile.TemporaryDirectory(prefix='agent-os-write-') as tmp:
    root = Path(tmp)
    (root / 'ai').mkdir()
    for index, content in enumerate(('a' * 65536, '😀' * 16384, '\0' * 65536, '')):
        path = root / str(index)
        old = b'previous revision'
        path.write_bytes(old)
        digest = hashlib.sha256(old).hexdigest()
        def route(op, **fields):
            if op == 'execute':
                argv = fields['argv']
                assert argv[:3] == ['/usr/bin/python3', '/usr/local/lib/agent-os/services/files.py', '--stdin-content']
                descriptor = json.loads(argv[3])
                assert descriptor == dict(op='write', path=str(path), expected_sha256=digest,
                                          content_sha256=hashlib.sha256(content.encode()).hexdigest())
                assert fields['stdin'] == content
                return execute(argv, content)
            return request(op, **fields)
        def workflow(prompt, history, cfg, dispatch, progress, record, **kw):
            result = dispatch('write_file', dict(path=str(path), content=content, expected_sha256=digest))
            assert result['status'] == 'succeeded', result
            written = result['file_result']
            assert written['sha256'] == hashlib.sha256(content.encode()).hexdigest()
            assert path.read_bytes() == content.encode()
            assert Path(written['backup']).read_bytes() == old
            Path(written['backup']).unlink()
            if content:
                stale = dispatch('write_file', dict(path=str(path), content=content, expected_sha256=digest))
                assert stale['status'] == 'failed', stale
                assert 'File changed' in stale['file_result']['error']
                assert path.read_bytes() == content.encode()
            return dict(text='Verified fixture.', model='fixture', finish_reason='stop',
                        messages=[{'role':'user','content':prompt},{'role':'assistant','content':'Verified fixture.'}])
        decisions = SimpleNamespace(select_history=lambda *a:[], select_memory=lambda *a:[], summary=lambda:{})
        with patch.object(assistant, 'STATE', root / 'ai'), patch.object(assistant, 'config', return_value={}), \
             patch.object(assistant.model_usage, 'configure'), patch.object(assistant.knowledge, 'context', return_value=[]), \
             patch.object(assistant, 'Decisions', return_value=decisions), patch.object(assistant, 'run_agent', side_effect=workflow), \
             patch.object(assistant, 'broker_request', side_effect=route), patch.object(assistant, 'emit'), patch.object(assistant, 'send'):
            assistant.handle({'op':'ask','activity':activity,'prompt':'Write temporary fixture '+str(path)}, None)
        checks.append(('ASCII', 'emoji', 'NUL', 'empty')[index] + ': exact write, hash and backup')
    path = root / 'mismatch'
    argv = ['/usr/bin/python3', '/usr/local/lib/agent-os/services/files.py', '--stdin-content',
            json.dumps(dict(op='write', path=str(path), expected_sha256='missing', content_sha256='incorrect'))]
    job = execute(argv, 'content')
    assert job['status'] == 'failed' and 'Input content hash mismatch' in job['output']
    assert not path.exists()
    try:
        request('execute', activity=activity, argv=argv, stdin='x' * 65537)
    except RuntimeError as exc:
        assert '64 KiB' in str(exc)
    else:
        raise AssertionError('Oversized input accepted')
    checks.append('Mismatched and oversized input rejected without a write')
    job = execute(['/usr/bin/python3', '-u', '-c',
                   'import sys; sys.stdout.write("x"*100000); sys.stdout.flush(); print(len(sys.stdin.buffer.read()))'], 'a'*65536)
    assert job['status'] == 'succeeded', job
    # This fixture is plain output, so collect the tail directly instead of parsing JSON.
    assert request('poll', job_id=job['id'], offset=100000)['output'].strip() == '65536'
    checks.append('Output-before-input completes without a pipe deadlock')
print(json.dumps(dict(result='pass', checks=checks, provider_calls='fixtures; no live inference')))
