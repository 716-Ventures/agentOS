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

if __name__=='__main__':unittest.main()
