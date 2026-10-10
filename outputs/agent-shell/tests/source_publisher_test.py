import sys
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
from source_publisher import BrokerSources
import broker

class Sources(unittest.TestCase):
    def job(self,revision=1,status='running'):
        return {'id':'a'*32,'activity':1,'source_revision':revision,'status':status,'created_at':1,'stdin':'private input'}
    def test_publisher_carries_only_observed_fields_and_coalesces_by_revision(self):
        sources=BrokerSources('/unused');sources.mark(self.job());sources.mark(self.job(2,'succeeded'))
        self.assertEqual(len(sources.pending),1)
        payload=next(iter(sources.pending.values()));self.assertEqual(payload['source_revision'],2);self.assertNotIn('stdin',payload['values']);self.assertEqual(payload['values']['status'],'succeeded')
    def test_outage_keeps_pending_observation_and_close_is_bounded(self):
        sources=BrokerSources('/unused');sources.mark(self.job())
        with patch.object(sources,'request',side_effect=OSError('Core offline')):
            sources.start();time.sleep(.02);sources.close()
        self.assertFalse(sources.worker.is_alive());self.assertEqual(len(sources.pending),1)
    def test_persisted_job_revision_precedes_publication(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(broker,'STATE',Path(directory)),patch.object(broker.SOURCES,'mark') as mark:
            job=self.job();broker.persist(job);self.assertEqual(job['source_revision'],2)
            import json
            self.assertEqual(json.loads((Path(directory)/(job['id']+'.json')).read_text())['source_revision'],2)
            mark.assert_called_once_with(job)
