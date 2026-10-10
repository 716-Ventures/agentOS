import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client'))
from state_pages import read
class StatePages(unittest.TestCase):
    def test_history_is_scoped_ordered_and_restarted_after_interleaved_write(self):
        calls=[]
        def request(op,**fields):
            calls.append(fields)
            if len(calls)==1:return {'revision':1,'rows':[{'id':2}],'next_before_id':2}
            if len(calls)==2:raise RuntimeError('resync_required')
            if len(calls)==3:
                self.assertNotIn('expected_revision',fields)
                return {'revision':2,'rows':[{'id':3}],'next_before_id':None}
            self.assertEqual(fields['collection'],'jobs');self.assertEqual(fields['activity_id'],3);self.assertEqual(fields['expected_revision'],2)
            return {'revision':2,'rows':[{'id':7}],'next_before_id':None}
        self.assertEqual(read(request,3)['jobs'],[{'id':7}]);self.assertEqual(calls[1]['before_id'],2)
    def test_cancellation_bad_rows_and_nonadvancing_cursor_fail_without_spin(self):
        def unexpected(*args,**kwargs):self.fail('Cancelled request dispatched')
        with self.assertRaisesRegex(RuntimeError,'cancelled'):read(unexpected,stopped=lambda:True)
        for entries,next_id in (([],2),([{'id':2}],3),([{'id':2},{'id':2}],None),([{'id':True}],None)):
            with self.assertRaisesRegex(RuntimeError,'cursor'):read(lambda *args,**kwargs:{'revision':1,'rows':entries,'next_before_id':next_id})
