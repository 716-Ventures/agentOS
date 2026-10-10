import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import presentation_client as client

class PresentationClientTests(unittest.TestCase):
    def test_activity_scope_rejects_cross_activity_documents_and_existing_surfaces(self):
        state={'documents':{'allowed':{'activity_id':'1'},'foreign':{'activity_id':'2'}}}
        with patch.object(client,'request',return_value=state) as request:
            for operation in (
                {'op':'surface.create','document':{'surface_id':'new','activity_id':'2'}},
                {'op':'element.set_props','surface_id':'foreign','element_id':'text','props':{'text':'changed'}},
                {'op':'surface.replace','document':{'surface_id':'foreign','activity_id':'1'}},
            ):
                with self.assertRaises(ValueError):client.apply_for_activity(1,{'op':'presentation.apply','operations':[operation]})
            self.assertTrue(all(c.args==('presentation.snapshot',) for c in request.call_args_list))
    def test_scoped_snapshot_and_valid_forwarding(self):
        state={'documents':{'allowed':{'activity_id':'1'},'foreign':{'activity_id':'2'}},'event_cursor':4}
        with patch.object(client,'request',return_value=state):
            self.assertEqual(set(client.for_activity(1)['documents']),{'allowed'})
        tx={'op':'presentation.apply','operations':[{'op':'element.set_props','surface_id':'allowed','element_id':'text','props':{'text':'changed'}}]}
        with patch.object(client,'for_activity',return_value={'documents':{'allowed':{}}}),patch.object(client,'request',return_value={'status':'committed'}) as request:
            self.assertEqual(client.apply_for_activity(1,tx)['status'],'committed');request.assert_called_once_with(**tx)

if __name__=='__main__':unittest.main()
