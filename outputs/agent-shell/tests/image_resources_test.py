import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client'))
import image_resources

class ImageResources(unittest.TestCase):
    def test_import_reconciles_the_same_immutable_reference_and_transaction_after_lost_responses(self):
        calls=[];failed=set()
        def request(op,**fields):
            calls.append((op,fields))
            if op not in failed:failed.add(op);raise RuntimeError('Lost response')
            if op=='resource.publish':return {key:fields[key] for key in ('reference','activity_id')}
            return {'revisions':{fields['operations'][0]['document']['surface_id']:0}}
        result=image_resources.publish(request,7,Path(__file__).parent/'fixtures/pixel.png','Blue pixel')
        self.assertEqual(calls[0],calls[1]);self.assertEqual(calls[2],calls[3])
        document=calls[2][1]['operations'][0]['document']
        self.assertEqual(document['elements']['image']['props']['reference'],result['resource']['reference'])
        self.assertEqual(document['activity_id'],'7');self.assertEqual(document['elements']['image']['type'],'Image@1')
        self.assertNotIn('path',calls[0][1]);self.assertNotIn('png_hex',document['elements']['image']['props'])
    def test_oversized_files_and_bad_alternative_labels_fail_before_publication(self):
        def unexpected(*args,**fields):self.fail('Invalid image sent to core')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'large.png';path.write_bytes(b'x'*(image_resources.LIMIT+1))
            with self.assertRaises(ValueError):image_resources.publish(unexpected,1,path)
        path=Path(__file__).parent/'fixtures/pixel.png'
        for label in (' ','x'*257,'bad\0label'):
            with self.assertRaises(ValueError):image_resources.publish(unexpected,1,path,label)
