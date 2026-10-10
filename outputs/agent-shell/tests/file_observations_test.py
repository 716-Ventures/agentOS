"""Metadata adapters publish only assessed outcomes after durable private storage."""
import concurrent.futures
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import files
from file_observations import FileObservations, HELPER, valid
from source_publisher import BrokerSources

class Observations(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'note';self.path.write_text('private contents')
        self.publisher=BrokerSources();self.store=FileObservations(self.root/'observations',self.publisher)
    def record(self):return json.loads(next(self.store.directory.glob('*.json')).read_text())
    def test_stable_scoped_identity_private_storage_and_replay(self):
        values=files.metadata(self.path)
        def published(record):
            self.assertEqual(self.record(),record)
            self.assertEqual(next(self.store.directory.glob('*.json')).stat().st_mode & 0o777,0o600)
        with patch.object(self.publisher,'mark_file',side_effect=published):source=self.store.save(1,values)
        self.assertEqual(self.store.directory.stat().st_mode & 0o777,0o700)
        self.path.write_text('new');self.assertEqual(self.store.save(1,files.metadata(self.path)),source)
        self.assertEqual(self.record()['source_revision'],2)
        self.assertNotEqual(self.store.save(2,values),source)
        self.publisher.pending.clear();self.store.recover()
        self.assertEqual(len(self.publisher.pending),2)
        self.assertEqual(self.publisher.pending[source]['values']['size_bytes'],3)
        self.assertNotIn('private contents',json.dumps(self.publisher.pending))
    def test_concurrent_completion_keeps_monotonic_revision(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            sources=list(pool.map(lambda _:FileObservations(self.store.directory,self.publisher).save(1,files.metadata(self.path)),range(40)))
        self.assertEqual(len(set(sources)),1);self.assertEqual(self.record()['source_revision'],40)
    def test_unavailable_publisher_does_not_lose_durable_observation(self):
        with patch.object(self.publisher,'mark_file',side_effect=OSError('offline')):
            with self.assertRaises(OSError):self.store.save(1,files.metadata(self.path))
        self.store.recover();self.assertEqual(len(self.publisher.pending),1)
    def test_corrupt_record_is_preserved_and_symlink_not_followed(self):
        self.store.save(1,files.metadata(self.path));record=next(self.store.directory.glob('*.json'))
        record.write_text('{broken')
        with self.assertRaises(ValueError):self.store.save(1,files.metadata(self.path))
        self.assertEqual(record.read_text(),'{broken');self.publisher.pending.clear();self.store.recover()
        self.assertFalse(self.publisher.pending)
        record.unlink();record.symlink_to(self.root/'missing')
        with self.assertRaises(ValueError):self.store.save(1,files.metadata(self.path))
        self.assertFalse((self.root/'missing').exists())
    def test_only_successful_fixed_helper_results_are_observed(self):
        job={'id':'d'*32,'argv':['/usr/bin/python3',HELPER,json.dumps({'op':'read','path':str(self.path)})],
             'activity':1,'status':'succeeded','exit_code':0}
        (self.root/(job['id']+'.log')).write_text(json.dumps(files.run({'op':'read','path':str(self.path)})))
        self.assertTrue(self.store.completed(job))
        self.publisher.pending.clear()
        for change in ({'status':'failed'},{'exit_code':1},{'terminal':True},{'output_truncated':True},
                       {'argv':['python3',HELPER,job['argv'][-1]]},{'argv':['/usr/bin/python3','/tmp/files.py',job['argv'][-1]]},
                       {'argv':['/usr/bin/python3',HELPER,json.dumps({'op':'write'})]}):
            self.assertIsNone(self.store.completed({**job,**change}))
        self.assertFalse(self.publisher.pending)
    def test_image_preview_observation_requires_its_assessed_activity(self):
        job={'id':'e'*32,'argv':['/usr/bin/python3',HELPER,json.dumps({'op':'image','path':str(self.path),'activity_id':1})],
             'activity':1,'status':'succeeded','exit_code':0}
        (self.root/(job['id']+'.log')).write_text(json.dumps({'metadata':files.metadata(self.path),'surface_id':'preview'}))
        self.assertTrue(self.store.completed(job))
        job['argv'][-1]=json.dumps({'op':'image','path':str(self.path),'activity_id':2})
        self.assertIsNone(self.store.completed(job))
    def test_metadata_types_and_no_content_extension(self):
        values=files.metadata(self.path);self.assertTrue(valid(values));self.assertEqual(values['kind'],'file')
        link=self.root/'link';link.symlink_to(self.path);self.assertEqual(files.metadata(link)['kind'],'symlink')
        self.assertEqual(files.metadata(self.root)['kind'],'directory')
        self.assertEqual(files.metadata(self.root/'absent')['kind'],'missing')
        with patch('files.Path.lstat',side_effect=PermissionError()):self.assertEqual(files.metadata(self.path)['kind'],'unavailable')
        for change in ({'content':'secret'},{'mode':True},{'size_bytes':-1},{'measured_at':float('nan')},{'path':'relative'},{'path':'/bad\udcff'}):
            self.assertFalse(valid({**values,**change}))
        self.store.save(1,values);record=next(self.store.directory.glob('*.json'));saved=self.record()
        saved['source_revision']=2**63-1;record.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError,'exhausted'):self.store.save(1,values)
        self.assertEqual(json.loads(record.read_text()),saved)
