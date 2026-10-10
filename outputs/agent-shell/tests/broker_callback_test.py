import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import broker
class CallbackGuards(unittest.TestCase):
    def test_callback_checks_actual_source_revision_and_activity_before_effect(self):
        job={'id':'e'*32,'activity':1,'source_revision':7,'status':'succeeded','created_at':1}
        request={'op':'cancel','job_id':job['id'],'expected_source_revision':7,'expected_activity':1}
        with patch.object(broker,'JOBS',{job['id']:job}),patch.object(broker,'cancel_job',return_value={'status':'succeeded'}) as cancel:
            for change in ({'expected_source_revision':6},{'expected_source_revision':True},{'expected_activity':2},{'expected_activity':True}):
                with self.assertRaises(ValueError):broker.handle({**request,**change},1000)
            cancel.assert_not_called();self.assertEqual(broker.handle(request,1000),{'status':'succeeded'});cancel.assert_called_once_with(job)
