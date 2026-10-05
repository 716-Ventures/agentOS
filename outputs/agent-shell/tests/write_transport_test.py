"""Bounded stdin carries guarded edits without weakening assessment or identity."""
import hashlib
import io
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import broker
import files
import jev
import providers
from common import LIMIT


def descriptor(path, content, expected='missing'):
    return ['--stdin-content',json.dumps({'op':'write','path':str(path),
        'expected_sha256':expected,'content_sha256':hashlib.sha256(content.encode()).hexdigest()})]


class GuardedInput(unittest.TestCase):
    def test_full_64k_ascii_unicode_and_control_content_preserves_hash_and_backup(self):
        for content in ('a'*65536,'😀'*16384,'\0'*65536,''):
            with self.subTest(sample=content[:1]), tempfile.TemporaryDirectory() as tmp, \
                 patch.object(files,'BACKUPS',Path(tmp)/'backups'):
                path=Path(tmp)/'note'
                first=files.run(files.read_request(descriptor(path,content),io.BytesIO(content.encode())))
                self.assertEqual(path.read_bytes(),content.encode())
                self.assertEqual(first['sha256'],hashlib.sha256(content.encode()).hexdigest())
                updated=files.run(files.read_request(descriptor(path,'replacement',first['sha256']),io.BytesIO(b'replacement')))
                self.assertEqual(Path(updated['backup']).read_bytes(),content.encode())
                with self.assertRaisesRegex(ValueError,'File changed'):
                    files.run(files.read_request(descriptor(path,'stale',first['sha256']),io.BytesIO(b'stale')))
                self.assertEqual(path.read_bytes(),b'replacement')

    def test_missing_mismatched_or_partial_input_cannot_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'note'
            for data in (b'',b'part',b'different'):
                with self.subTest(data=data),self.assertRaisesRegex(ValueError,'hash mismatch'):
                    files.read_request(descriptor(path,'complete'),io.BytesIO(data))
                self.assertFalse(path.exists())

    def test_oversize_and_non_write_stdin_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'too large'):
            files.read_request(descriptor('/tmp/fixture','a'*65537),io.BytesIO(b'a'*65537))
        with self.assertRaisesRegex(ValueError,'guarded write'):
            files.read_request(['--stdin-content','{"op":"read","path":"/tmp/fixture"}'],io.BytesIO())

    def test_legacy_descriptors_still_work(self):
        req={'op':'write','path':'note','content':'old client','expected_sha256':'missing'}
        self.assertEqual(files.read_request([json.dumps(req)],io.BytesIO()),req)


class BrokerInput(unittest.TestCase):
    def test_input_is_byte_bounded_valid_utf8_without_relaxing_argv_limits(self):
        base={'argv':['/usr/bin/cat'],'purpose':'Fixture'}
        for content in ('a'*65536,'😀'*16384,'\0'*65536,''):
            broker.validate({**base,'stdin':content})
        for content in ('a'*65537,'😀'*16385,'\ud800',None,True):
            with self.subTest(content_type=type(content)),self.assertRaises(ValueError):
                broker.validate({**base,'stdin':content})
        with self.assertRaises(ValueError):
            broker.validate({**base,'argv':['/usr/bin/cat','a'*32001]})

    def test_exact_input_is_assessed_but_public_views_omit_payload(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(broker,'STATE',Path(tmp)), \
             patch.object(broker,'workspace',return_value=tmp),patch.object(broker,'JOBS',{}), \
             patch.object(broker,'start') as start:
            content='a'*65536
            response=SimpleNamespace(returncode=0,stdout=json.dumps({'status':'available','risk':'routine','confidence':1}))
            with patch.object(broker.subprocess,'run',return_value=response) as assess:
                result=broker.handle({'op':'execute','activity':1,'argv':['/usr/bin/cat'],
                                     'purpose':'Fixture','stdin':content},123)
            received=json.loads(assess.call_args.kwargs['input'])
            self.assertEqual(received['stdin_untrusted'],content)
            self.assertEqual(received['stdin_sha256'],hashlib.sha256(content.encode()).hexdigest())
            self.assertNotIn('stdin',result)
            self.assertNotIn('stdin',broker.handle({'op':'list'},123)[0])
            self.assertEqual(result['stdin_bytes'],65536)
            self.assertEqual(broker.JOBS[result['id']]['stdin'],content)
            with self.assertRaisesRegex(ValueError,'administrator'):
                broker.handle({'op':'input','job_id':result['id']},123)
            self.assertEqual(broker.handle({'op':'input','job_id':result['id']},0)['stdin'],content)
            start.assert_called_once()

    def test_proposals_with_different_input_are_distinct_and_exact_retry_reuses(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(broker,'STATE',Path(tmp)), \
             patch.object(broker,'workspace',return_value=tmp),patch.object(broker,'JOBS',{}), \
             patch.object(broker,'start') as start:
            response=SimpleNamespace(returncode=0,stdout=json.dumps({'status':'available','risk':'harmful','confidence':1}))
            req={'op':'execute','activity':1,'argv':['/usr/bin/cat'],'purpose':'Fixture'}
            with patch.object(broker.subprocess,'run',return_value=response):
                one=broker.handle({**req,'stdin':'one'},123)
                two=broker.handle({**req,'stdin':'two'},123)
                retry=broker.handle({**req,'stdin':'one'},123)
            self.assertNotEqual(one['id'],two['id'])
            self.assertEqual(one['id'],retry['id'])
            self.assertEqual(len(broker.JOBS),2)
            start.assert_not_called()

    def test_no_input_and_empty_input_are_different_execution_contracts(self):
        job={'activity':1,'argv':['/usr/bin/cat'],'workspace':'/tmp','cwd':'/tmp',
             'background':True,'timeout_seconds':30,'scope':'system'}
        self.assertTrue(broker.same_operation(job,1,job['argv'],'/tmp',True,30,'system'))
        self.assertFalse(broker.same_operation(job,1,job['argv'],'/tmp',True,30,'system',hashlib.sha256(b'').hexdigest()))


class AssessmentInput(unittest.TestCase):
    def test_full_escaped_payload_reaches_evaluator(self):
        action={'stdin_untrusted':'\0'*65536, 'argv':['/usr/bin/cat']}
        raw=json.dumps(action).encode()
        self.assertGreater(len(raw),65537)
        with patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(raw))), \
             patch.object(sys,'stdout',io.StringIO()), patch.object(providers,'config',return_value={}), \
             patch.object(jev,'evaluate_action',return_value={'status':'unavailable'}) as evaluate:
            runpy.run_path(str(Path(files.__file__).with_name('assess_action.py')),run_name='__main__')
        evaluate.assert_called_once_with(action,{})

    def test_oversize_assessment_fails_closed_without_evaluation(self):
        with patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(b'x'*(LIMIT+1)))), \
             patch.object(sys,'stdout',io.StringIO()) as output, patch.object(jev,'evaluate_action') as evaluate:
            runpy.run_path(str(Path(files.__file__).with_name('assess_action.py')),run_name='__main__')
        self.assertEqual(json.loads(output.getvalue())['status'],'unavailable')
        evaluate.assert_not_called()
