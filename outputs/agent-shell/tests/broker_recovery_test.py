"""Recovery must not hide live root commands behind a terminal job status."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services'))
import broker


class BrokerRecovery(unittest.TestCase):
    def recover(self, responses, status='running'):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ('a' * 32 + '.json')
            original = {'id': 'a' * 32, 'status': status, 'created_at': 1}
            path.write_text(json.dumps(original))
            with patch.object(broker, 'STATE', Path(tmp)), patch.object(broker, 'JOBS', {}), \
                 patch.object(broker.subprocess, 'run', side_effect=responses) as run:
                error = None
                try:
                    broker.recover_jobs()
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    error = exc
                return original, json.loads(path.read_text()), dict(broker.JOBS), error, run.call_args_list

    def result(self, code=0, active='inactive', main='0', control='0', load='loaded', tasks='0', group=''):
        return SimpleNamespace(returncode=code, stdout=f'LoadState={load}\nActiveState={active}\nMainPID={main}\nControlPID={control}\nTasksCurrent={tasks}\nControlGroup={group}\n')

    def test_stop_error_with_live_unit_preserves_saved_status(self):
        for code in (0, 1):
            with self.subTest(stop_exit=code):
                old, saved, jobs, error, calls = self.recover([
                    self.result(code), self.result(active='active', main='123')])
                self.assertIsInstance(error, RuntimeError)
                self.assertEqual(saved, old)
                self.assertEqual(jobs, {})
                self.assertFalse(any('systemd-run' in str(call) for call in calls))

    def test_successful_stop_must_also_have_no_control_process(self):
        old, saved, jobs, error, _ = self.recover([
            self.result(), self.result(control='123')])
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(saved, old)
        self.assertEqual(jobs, {})

    def test_failed_unit_with_remaining_cgroup_tasks_is_not_interrupted(self):
        old, saved, jobs, error, _ = self.recover([
            self.result(), self.result(active='failed', tasks='2', group='/system.slice/fixture')])
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(saved, old)
        self.assertEqual(jobs, {})

    def test_collected_unit_is_interrupted_even_when_stop_reports_not_found(self):
        _, saved, jobs, error, calls = self.recover([
            self.result(5), self.result(4, load='not-found')])
        self.assertIsNone(error)
        self.assertEqual(saved['status'], 'interrupted')
        self.assertIn('finished_at', saved)
        self.assertEqual(jobs[saved['id']], saved)
        self.assertEqual(len(calls), 2)

    def test_query_failure_or_missing_properties_cannot_claim_stopped(self):
        for response in (self.result(1), SimpleNamespace(returncode=0, stdout=''),
                         subprocess.TimeoutExpired('systemctl', 10)):
            with self.subTest(response=response):
                old, saved, jobs, error, _ = self.recover([self.result(), response])
                self.assertIsNotNone(error)
                self.assertEqual(saved, old)
                self.assertEqual(jobs, {})

    def test_stopped_unit_has_terminal_time_and_is_not_replayed(self):
        for active in ('inactive', 'failed'):
            with self.subTest(active=active):
                _, saved, jobs, error, calls = self.recover([
                    self.result(), self.result(active=active)], status='cancelling')
                self.assertIsNone(error)
                self.assertEqual(saved['status'], 'interrupted')
                self.assertIn('finished_at', saved)
                self.assertEqual(jobs[saved['id']], saved)
                self.assertEqual(calls[0].args[0][1], 'stop')

    def test_proposals_and_completed_jobs_survive_without_systemd_calls(self):
        for status in ('approval_required', 'succeeded', 'failed', 'interrupted', 'rejected'):
            with self.subTest(status=status):
                old, saved, jobs, error, calls = self.recover([], status=status)
                self.assertIsNone(error)
                self.assertEqual(saved, old)
                self.assertEqual(jobs[saved['id']], old)
                self.assertEqual(calls, [])
