import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import broker

class StoredInput(unittest.TestCase):
    def job(self):
        text='λ 日本語\n$(never execute preview)'
        return {'id':'a'*32,'activity':1,'status':'approval_required','stdin':text,'stdin_sha256':hashlib.sha256(text.encode()).hexdigest(),'stdin_bytes':len(text.encode())}
    def test_only_administrator_can_read_the_exact_stored_input(self):
        job=self.job()
        with tempfile.TemporaryDirectory() as directory,patch.object(broker,'STATE',Path(directory)),patch.dict(broker.JOBS,{job['id']:job},clear=True):
            for uid in (999,1000):
                with self.assertRaisesRegex(ValueError,'administrator'):broker.handle({'op':'input','job_id':job['id']},uid)
            result=broker.handle({'op':'input','job_id':job['id']},0)
            self.assertEqual(result['stdin'],job['stdin']);self.assertNotIn('stdin',broker.view(job))
    def test_changed_input_cannot_be_previewed_or_launched(self):
        for key,value in [('stdin','changed'),('stdin_sha256','wrong'),('stdin_bytes',0)]:
            job=self.job();job[key]=value
            with patch.dict(broker.JOBS,{job['id']:job},clear=True),patch.object(broker,'persist') as persist,patch.object(broker.threading,'Thread') as thread:
                with self.assertRaises(ValueError):broker.handle({'op':'input','job_id':job['id']},0)
                with self.assertRaises(ValueError):broker.start(job)
                persist.assert_not_called();thread.assert_not_called();self.assertEqual(job['status'],'approval_required')
    def test_absent_and_empty_inputs_remain_distinct(self):
        self.assertIsNone(broker.checked_input({}))
        empty={'stdin':'','stdin_bytes':0,'stdin_sha256':hashlib.sha256(b'').hexdigest()}
        self.assertEqual(broker.checked_input(empty),'')
        with self.assertRaises(ValueError):broker.checked_input({'stdin_sha256':'wrong'})
