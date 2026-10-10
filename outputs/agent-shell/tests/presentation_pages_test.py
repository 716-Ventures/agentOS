import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client'))
import presentation_pages as pages

class Pages(unittest.TestCase):
    def test_page_cursor_scope_and_metadata_are_forwarded(self):
        calls=[]
        def request(op,**fields):
            calls.append((op,fields))
            if len(calls)==1:return {'event_cursor':3,'documents':{'a':{}},'next_after_id':'a'}
            if len(calls)==2:return {'event_cursor':3,'documents':{'b':{}},'next_after_id':None}
            return {'event_cursor':3,'host_surfaces':{}}
        state=pages.read(request,7)
        self.assertEqual(set(state['documents']),{'a','b'})
        self.assertEqual(calls[1][1]['expected_cursor'],3);self.assertEqual(calls[1][1]['after_id'],'a')
        self.assertTrue(all(fields['activity_id']=='7' for _,fields in calls))
        self.assertEqual(calls[-1][0],'presentation.metadata')
    def test_mixed_revision_is_retried_from_scratch(self):
        calls=[]
        def request(op,**fields):
            calls.append((op,fields))
            if len(calls)==1:return {'event_cursor':1,'documents':{'old':{}},'next_after_id':'old'}
            if len(calls)==2:raise RuntimeError('resync_required')
            self.assertEqual(fields['after_id'],'')
            return {'event_cursor':2,'documents':{'new':{}},'next_after_id':None}
        self.assertEqual(set(pages.read(request,metadata=False)['documents']),{'new'})
    def test_outage_cancellation_and_bad_cursor_do_not_spin(self):
        calls=[]
        def request(op,**fields):calls.append(op);raise RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):pages.read(request)
        self.assertEqual(len(calls),1)
        with self.assertRaisesRegex(RuntimeError,'cancelled'):pages.read(request,stopped=lambda:True)
        self.assertEqual(len(calls),1)
        with self.assertRaisesRegex(RuntimeError,'cursor'):pages.read(lambda *_a,**_k:{'event_cursor':0,'documents':{},'next_after_id':''})



class Incremental(unittest.TestCase):
    def test_changed_documents_tombstones_and_unchanged_refresh(self):
        cache=pages.Cache();cache.scope='1';cache.state={'event_cursor':1,'documents':{'a':{'revision':0},'gone':{}}}
        calls=[]
        def request(op,**fields):
            calls.append(op)
            if op=='presentation.changes':return {'events':[{'event_cursor':2,'revisions':{'a':1,'gone':None}}],'latest_cursor':2,'next_cursor':2,'has_more':False}
            if op=='presentation.get':
                self.assertEqual(fields,{'document_id':'a','expected_cursor':2,'activity_id':'1'})
                return {'revision':1}
            if op=='presentation.metadata':return {'event_cursor':2}
            self.fail('Unexpected full scan')
        self.assertEqual(cache.read(request,1)['documents'],{'a':{'revision':1}})
        self.assertEqual(calls,['presentation.changes','presentation.get','presentation.metadata'])
        def unchanged(op,**fields):
            if op=='presentation.changes':return {'events':[],'latest_cursor':2,'next_cursor':2,'has_more':False}
            self.fail('Unchanged document fetched')
        self.assertEqual(cache.read(unchanged,1,metadata=False)['documents'],{'a':{'revision':1}})

    def test_incomplete_refresh_never_overwrites_a_consistent_cache(self):
        cache=pages.Cache();cache.state={'event_cursor':1,'documents':{'a':{}}}
        old=cache.state.copy()
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            cache.read(lambda *args,**kw:self.fail('Cancelled request'),stopped=lambda:True)
        with self.assertRaisesRegex(RuntimeError,'continuation'):
            cache.read(lambda *args,**kw:{'events':[],'latest_cursor':2,'next_cursor':1,'has_more':True})
        self.assertEqual(cache.state,old)

if __name__=='__main__':unittest.main()
