import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services'));sys.path.insert(0,str(ROOT/'client'))
import broker
import broker_pages
class BrokerPages(unittest.TestCase):
    def records(self,count=300):
        return {format(i,'032x'):{'id':format(i,'032x'),'activity':1,'created_at':i//2,'status':'succeeded','argv':['/bin/echo','日本語'*1000],
                                'cwd':'/tmp','scope':'system','stdin':'private input','requested_argv':['private duplicate'],'policy':{'reason':'Observed','private_evidence':'private evidence'}} for i in range(1,count+1)}
    def test_complete_history_stays_byte_bounded_and_does_not_publish_private_input(self):
        with patch.object(broker,'JOBS',self.records()):
            def request(op,**fields):
                page=broker.handle({'op':op,**fields},1000)
                self.assertLessEqual(len(json.dumps(page).encode()),448*1024)
                self.assertNotIn('private input',json.dumps(page));self.assertNotIn('private evidence',json.dumps(page));self.assertNotIn('private duplicate',json.dumps(page))
                return page
            jobs=broker_pages.read(request,1);self.assertEqual(len(jobs),300)
            self.assertEqual([job['id'] for job in jobs],sorted(self.records(),reverse=True))
            self.assertEqual(broker_pages.read(request,2),[])
            self.assertEqual(len(broker_pages.read(request,1,recent=True)),100)
    def test_epoch_changes_and_interleaved_writes_require_restart(self):
        with patch.object(broker,'JOBS',self.records(1)):
            page=broker.list_page({})
            with patch.object(broker,'EPOCH','new-epoch'):
                with self.assertRaisesRegex(ValueError,'resync_required'):broker.list_page({'expected_revision':page['revision']})
            with patch.object(broker,'REVISION',broker.REVISION+1):
                with self.assertRaisesRegex(ValueError,'resync_required'):broker.list_page({'expected_revision':page['revision']})
    def test_bad_cursor_limits_and_cancellation_do_not_spin(self):
        for fields in ({'limit':True},{'limit':65},{'before':[float('nan'),'a'*32]},{'before':[10**1000,'a'*32]},{'before':[1,'bad']},{'activity':True}):
            with self.assertRaises(ValueError):broker.list_page(fields)
        with self.assertRaisesRegex(RuntimeError,'cancelled'):broker_pages.read(lambda *args,**kwargs:self.fail('Dispatched after cancel'),stopped=lambda:True)
        with self.assertRaisesRegex(RuntimeError,'cursor'):broker_pages.read(lambda *args,**kwargs:{'revision':'epoch:0','jobs':[],'next_before':[1,'a'*32]})
    def test_pending_work_outside_recent_window_stays_visible(self):
        records=self.records();records[format(1,'032x')]['status']='approval_required'
        with patch.object(broker,'JOBS',records):
            jobs=broker_pages.read(lambda op,**fields:broker.handle({'op':op,**fields},1000),recent=True)
            self.assertEqual(len(jobs),101);self.assertEqual(jobs[-1]['id'],format(1,'032x'))
