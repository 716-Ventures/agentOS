import importlib.util
from pathlib import Path
import json
import unittest

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'native-shell' if (ROOT/'native-shell').is_dir() else ROOT.parent/'native-shell'
spec=importlib.util.spec_from_file_location('fixture_session_focus',NATIVE/'tests/session_focus.py')
focus=importlib.util.module_from_spec(spec);spec.loader.exec_module(focus)


class SessionFocusTest(unittest.TestCase):
    def run_focus(self,errors):
        calls=[]
        def request(value):
            calls.append(value)
            if value['op']=='presentation.snapshot':
                return {'documents':{'desktop':{'revision':len(calls)}}}
            if errors:
                raise errors.pop(0)
            return {'status':'committed'}
        return calls,lambda:focus.focus(request,'desktop','fixture','field','test-focus')

    def test_stale_rejection_reads_fresh_revision_and_preserves_exact_intent(self):
        calls,run=self.run_focus([AssertionError({'ok':False,'error':json.dumps({'code':'stale_revision'})})])
        self.assertEqual(run(),{'status':'committed'})
        mutations=[c for c in calls if c['op']=='presentation.apply']
        self.assertEqual([c['expected_revisions'] for c in mutations],[{'desktop':1},{'desktop':3}])
        self.assertEqual(mutations[0]['operations'],mutations[1]['operations'])
        self.assertNotEqual(mutations[0]['request_id'],mutations[1]['request_id'])

    def test_uncertain_transport_failure_is_never_replayed(self):
        calls,run=self.run_focus([TimeoutError('outcome unknown')])
        with self.assertRaises(TimeoutError):run()
        self.assertEqual(len(calls),2)

    def test_other_rejections_are_never_retried(self):
        for code in ('interaction_conflict','unauthorized','missing_reference'):
            calls,run=self.run_focus([AssertionError({'ok':False,'error':json.dumps({'code':code})})])
            with self.assertRaises(AssertionError):run()
            self.assertEqual(len(calls),2)

    def test_malformed_error_is_not_a_stale_rejection(self):
        calls,run=self.run_focus([AssertionError({'ok':False,'error':'stale_revision without structured rejection'})])
        with self.assertRaises(AssertionError):run()
        self.assertEqual(len(calls),2)

    def test_continuous_stale_rejections_are_bounded(self):
        calls,run=self.run_focus([AssertionError({'ok':False,'error':json.dumps({'code':'stale_revision'})}) for _ in range(8)])
        with self.assertRaises(AssertionError):run()
        self.assertEqual(len(calls),16)


if __name__=='__main__':unittest.main()
