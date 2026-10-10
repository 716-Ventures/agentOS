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

    def test_queue_pressure_streams_every_durable_observation_without_restart(self):
        records=[{**self.job(), 'id':format(i,'032x')} for i in range(1100)]
        sources=BrokerSources('/unused',replay=lambda:(sources.job_payload(job) for job in records))
        for job in records:sources.mark(job)
        self.assertEqual(len(sources.pending),1024);self.assertTrue(sources.needs_replay)
        seen=set()
        def deliver(payload):
            seen.add(payload['source'])
            if len(seen)==len(records):sources.stop.set()
        with patch.object(sources,'request',side_effect=deliver),patch.object(sources.stop,'wait'):
            sources.run()
        self.assertEqual(len(seen),1100)
        self.assertLessEqual(len(sources.pending),1024)

    def test_backfill_reads_only_bounded_regular_durable_records(self):
        import json
        import files
        from file_observations import FileObservations
        with tempfile.TemporaryDirectory() as directory,patch.object(broker,'STATE',Path(directory)):
            root=Path(directory);job=self.job();(root/(job['id']+'.json')).write_text(json.dumps(job))
            (root/'bad.json').write_text('{bad')
            (root/'link.json').symlink_to(root/(job['id']+'.json'))
            FileObservations(root/'file-observations',BrokerSources()).save(1,files.metadata(root/'missing'))
            rows=list(broker.source_backfill())
            self.assertEqual(len(rows),2);self.assertEqual({r['source'].split(':')[0] for r in rows},{'broker','file'})
            self.assertNotIn('private input',json.dumps(rows))

    def test_replay_drops_only_proven_older_observations(self):
        import io
        import json
        from unittest.mock import MagicMock
        payload=BrokerSources.job_payload(self.job(2))
        for revision,source,ignored in [(3,payload['source'],True),(2,payload['source'],False),
                                        (1,payload['source'],False),(True,payload['source'],False),
                                        (3,'broker:'+'b'*32,False),(None,payload['source'],False)]:
            error={'code':'stale_revision','source':source,'current_revision':revision}
            conn=MagicMock();conn.__enter__.return_value=conn
            conn.makefile.return_value=io.BytesIO(json.dumps({'ok':False,'error':json.dumps(error)}).encode()+b'\n')
            with patch('source_publisher.socket.socket',return_value=conn):
                if ignored:BrokerSources('/unused').request(payload)
                else:
                    with self.assertRaises(RuntimeError):BrokerSources('/unused').request(payload)
