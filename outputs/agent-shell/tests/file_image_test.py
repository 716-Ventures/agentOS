"""Assessed file preview publishes bytes only through the trusted native resource path."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import files
import presentation_client
import agent

class FileImagePreview(unittest.TestCase):
    def test_preview_returns_only_references_and_metadata_to_broker_output(self):
        calls=[]
        def request(op,**fields):
            calls.append((op,fields))
            if op=='resource.publish':return {'reference':fields['reference'],'width':1,'height':1}
            return {'event_cursor':1}
        path=Path(__file__).parent/'fixtures/pixel.png'
        with patch.object(presentation_client,'request',side_effect=request):
            result=files.run({'op':'image','path':str(path),'activity_id':7,'label':'Blue pixel'})
        self.assertEqual([op for op,_ in calls],['resource.publish','presentation.apply'])
        self.assertEqual(calls[0][1]['activity_id'],'7');self.assertEqual(calls[0][1]['png_hex'],path.read_bytes().hex())
        encoded=json.dumps(result);self.assertNotIn('png_hex',encoded);self.assertNotIn(path.read_bytes().hex(),encoded)
        self.assertEqual(result['metadata']['kind'],'file')
        doc=calls[1][1]['operations'][0]['document'];self.assertNotIn('path',doc)
        self.assertEqual(doc['elements']['image']['props']['reference'],result['resource']['reference'])
    def test_preview_rejects_missing_activity_before_read_or_publication(self):
        for activity in (None,True,0,-1,'1',2147483648):
            with self.assertRaises(ValueError):files.run({'op':'image','path':'/absent','activity_id':activity})
    def test_catalog_exposes_bounded_preview_without_publication_authority(self):
        preview=next(row for row in agent.TOOLS if row['function']['name']=='preview_image')['function']
        self.assertEqual(set(preview['parameters']['properties']),{'path','label'})
        self.assertNotIn('activity_id',preview['parameters']['properties'])
