"""A reused job must satisfy the requested execution mode and lifetime."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services'))
import broker


class BrokerReuse(unittest.TestCase):
    def run_request(self, changes=None, status='running'):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = str(Path(tmp).resolve())
            existing = dict(id='a' * 32, activity=1, argv=['/usr/bin/sleep', '60'],
                workspace=tmp, cwd=tmp, background=True, timeout_seconds=120,
                scope='system', status=status, created_at=1, exit_code=None)
            existing.update(changes or {})
            assessment = SimpleNamespace(returncode=0, stdout=json.dumps(
                dict(status='available', risk='routine', confidence=1)))
            with patch.object(broker, 'STATE', Path(tmp)), patch.object(broker, 'workspace', return_value=tmp), \
                 patch.object(broker, 'JOBS', {existing['id']: existing}), \
                 patch.object(broker.subprocess, 'run', return_value=assessment), \
                 patch.object(broker, 'start') as start:
                result = broker.handle(dict(op='execute', activity=1, argv=['/usr/bin/sleep', '60'],
                    purpose='Keep a task running', background=True, lifetime_seconds=120), 123)
                return existing, result, start.call_count, len(broker.JOBS)

    def test_identical_background_retry_reuses_starting_or_running_job(self):
        for status in ('starting', 'running'):
            with self.subTest(status=status):
                existing, result, starts, count = self.run_request(status=status)
                self.assertEqual(result['id'], existing['id'])
                self.assertEqual(starts, 0)
                self.assertEqual(count, 1)

    def test_foreground_job_does_not_satisfy_background_request(self):
        existing, result, starts, count = self.run_request({'background': False})
        self.assertNotEqual(result['id'], existing['id'])
        self.assertTrue(result['background'])
        self.assertEqual(result['timeout_seconds'], 120)
        self.assertEqual(starts, 1)
        self.assertEqual(count, 2)

    def test_different_lifetime_does_not_reuse_an_existing_job(self):
        existing, result, starts, count = self.run_request({'timeout_seconds': 30})
        self.assertNotEqual(result['id'], existing['id'])
        self.assertEqual(result['timeout_seconds'], 120)
        self.assertEqual(starts, 1)
        self.assertEqual(count, 2)

    def test_other_execution_settings_do_not_reuse_an_existing_job(self):
        for change in ({'scope': 'workspace'}, {'activity': 2},
                       {'cwd': '/different/path'}, {'argv': ['/usr/bin/sleep', '61']}):
            with self.subTest(change=change):
                existing, result, starts, count = self.run_request(change)
                self.assertNotEqual(result['id'], existing['id'])
                self.assertEqual(starts, 1)
                self.assertEqual(count, 2)

    def test_terminal_or_cancelling_jobs_are_not_reused(self):
        for status in ('succeeded', 'failed', 'cancelled', 'cancelling', 'interrupted'):
            with self.subTest(status=status):
                existing, result, starts, count = self.run_request(status=status)
                self.assertNotEqual(result['id'], existing['id'])
                self.assertEqual(starts, 1)
                self.assertEqual(count, 2)
