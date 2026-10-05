"""Regressions at the broker, local protocol and guarded-write boundaries."""
import io
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services'))
import broker
import common
import files


class BrokerHardening(unittest.TestCase):
    def test_routine_needs_confident_alignment_for_agent_requests(self):
        for fit, confidence in [('aligned', .79), ('uncertain', 1), ('aligned', True),
                                ('aligned', None), ('aligned', float('nan'))]:
            with self.subTest(fit=fit, confidence=confidence), tempfile.TemporaryDirectory() as tmp:
                assessment = dict(status='available', risk='routine', confidence=1,
                                  task_fit=fit, task_fit_confidence=confidence)
                with patch.object(broker, 'workspace', return_value=tmp), patch.object(broker, 'STATE', Path(tmp)), \
                     patch.object(broker, 'JOBS', {}), patch.object(broker, 'start') as start, \
                     patch.object(broker.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(assessment))):
                    result = broker.handle(dict(op='execute', activity=1, argv=['/usr/bin/id'],
                                                purpose='Inspect', current_request='Inspect my machine'), 123)
                    self.assertEqual(result['status'], 'inspection_required')
                    start.assert_not_called()

    def test_aligned_routine_executes_without_extra_consent(self):
        with tempfile.TemporaryDirectory() as tmp:
            assessment = dict(status='available', risk='routine', confidence=.9,
                              task_fit='aligned', task_fit_confidence=.9, authorization='absent')
            with patch.object(broker, 'workspace', return_value=tmp), patch.object(broker, 'STATE', Path(tmp)), \
                 patch.object(broker, 'JOBS', {}), patch.object(broker, 'start') as start, \
                 patch.object(broker.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(assessment))):
                result = broker.handle(dict(op='execute', activity=1, argv=['/usr/bin/id'],
                                            purpose='Inspect', current_request='Inspect my machine'), 123)
                self.assertEqual(result['status'], 'starting')
                start.assert_called_once()

    def test_cancel_before_launch_never_spawns_command(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(broker, 'STATE', Path(tmp)), \
             patch.object(broker.subprocess, 'Popen') as spawn:
            job = dict(id='a'*32, timeout_seconds=30, workspace=tmp, argv=['/usr/bin/id'],
                       status='cancelling', cancel_requested=True)
            broker.launch(job)
            spawn.assert_not_called()
            self.assertEqual(job['status'], 'cancelled')
            self.assertIn('finished_at', job)
            self.assertEqual(json.loads((Path(tmp)/(job['id']+'.json')).read_text())['status'], 'cancelled')

    def test_capacity_failure_does_not_record_an_approval(self):
        pending = dict(id='a'*32, status='approval_required', scope='system')
        jobs = {str(i): {'status': 'running'} for i in range(4)}
        jobs[pending['id']] = pending
        with patch.object(broker, 'JOBS', jobs):
            with self.assertRaisesRegex(ValueError, 'Four broker jobs'):
                broker.handle({'op': 'approve', 'job_id': pending['id']}, 0)
        self.assertEqual(pending['status'], 'approval_required')
        self.assertNotIn('approved_at', pending)


class GuardedWriteHardening(unittest.TestCase):
    def test_two_writers_cannot_both_replace_the_same_revision(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(files, 'BACKUPS', Path(tmp)/'backups'):
            path = Path(tmp)/'note'; path.write_text('original')
            digest = files.run(dict(op='read', path=str(path)))['sha256']
            def write(content):
                try:
                    return files.run(dict(op='write', path=str(path), content=content, expected_sha256=digest))
                except ValueError:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(write, ['first', 'second']))
            successes = [r for r in results if r]
            self.assertEqual(len(successes), 1)
            self.assertEqual(Path(successes[0]['backup']).read_text(), 'original')
            self.assertIn(path.read_text(), ('first', 'second'))

    def test_fifo_reads_and_writes_fail_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(files, 'BACKUPS', Path(tmp)/'backups'):
            path = Path(tmp)/'pipe'; os.mkfifo(path)
            for request in [dict(op='read', path=str(path)),
                            dict(op='write', path=str(path), content='data', expected_sha256='missing')]:
                with self.assertRaisesRegex(ValueError, 'non-regular'):
                    files.run(request)

    def test_failed_replace_cleans_temporary_file_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(files, 'BACKUPS', Path(tmp)/'backups'):
            path = Path(tmp)/'note'; path.write_text('original')
            digest = files.run(dict(op='read', path=str(path)))['sha256']
            with patch.object(Path, 'replace', side_effect=OSError('failed')):
                with self.assertRaises(OSError):
                    files.run(dict(op='write', path=str(path), content='new', expected_sha256=digest))
            self.assertEqual(path.read_text(), 'original')
            self.assertEqual(list(Path(tmp).glob('.agent-edit-*')), [])


class LocalProtocol(unittest.TestCase):
    def test_rejects_non_objects_non_finite_numbers_and_incomplete_messages(self):
        for data in (b'[]\n', b'null\n', b'{"x":NaN}\n', b'{"x":Infinity}\n', b'{}'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                common.read_line(io.BytesIO(data))
        self.assertEqual(common.read_line(io.BytesIO(b'{"ok":true}\n')), {'ok': True})
