import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client'))
import document_files as files

class Documents(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.doc=files.document(1,{'title':'Notes','content':'Café λ\n日本語\r\n'})
        self.doc['revision']=3;self.calls=[];self.draft=None
    def request(self,op,**fields):
        self.calls.append((op,fields))
        if op=='presentation.get':return copy.deepcopy(self.doc)
        if op=='draft.get':return {'draft':self.draft}
        return {'event_cursor':1}
    def test_strict_round_trip_has_exact_bytes_and_private_permissions(self):
        path=self.root/'notes.txt';files.export(self.request,self.doc['surface_id'],path,3)
        self.assertEqual(path.read_bytes(),self.doc['elements']['editor']['props']['value'].encode())
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        loaded=files.read(path);self.assertEqual(loaded['content'],self.doc['elements']['editor']['props']['value'])
        self.assertNotIn('path',files.document(1,loaded));self.assertEqual(list(self.root.iterdir()),[path])
    def test_existing_file_and_symlink_are_never_replaced(self):
        path=self.root/'old';path.write_bytes(b'original');link=self.root/'link';link.symlink_to(path)
        for target in (path,link):
            with self.assertRaises(FileExistsError):files.export(self.request,self.doc['surface_id'],target,3)
        self.assertEqual(path.read_bytes(),b'original');self.assertTrue(link.is_symlink())
        self.assertFalse(list(self.root.glob('.agent-document-*')))
    def test_lossy_oversized_nonregular_and_nul_imports_are_rejected(self):
        path=self.root/'bad'
        for raw in (b'bad\xff',b'x'*65537,b'nul\0'):
            path.write_bytes(raw)
            with self.assertRaises(ValueError):files.read(path)
        path.unlink();os.mkfifo(path)
        with self.assertRaises(ValueError):files.read(path)
        path.unlink();path.symlink_to(self.root/'absent')
        with self.assertRaises(OSError):files.read(path)
    def test_stale_unsaved_and_concurrent_changes_create_no_file(self):
        path=self.root/'new'
        with self.assertRaisesRegex(ValueError,'View changed'):files.export(self.request,self.doc['surface_id'],path,2)
        self.draft='unsaved'
        with self.assertRaisesRegex(ValueError,'draft'):files.export(self.request,self.doc['surface_id'],path,3)
        self.draft=None;reads=0
        def changed(op,**fields):
            nonlocal reads
            result=self.request(op,**fields)
            if op=='presentation.get':
                reads+=1
                if reads==2:result['revision']=4
            return result
        with self.assertRaisesRegex(ValueError,'while exporting'):files.export(changed,self.doc['surface_id'],path,3)
        self.assertFalse(list(self.root.iterdir()))
    def test_import_retries_identical_transaction_after_uncertain_response(self):
        path=self.root/'notes';path.write_text('λ');calls=[]
        def request(op,**fields):
            calls.append((op,fields))
            if len(calls)==1:raise RuntimeError('Lost acknowledgement')
            return {'event_cursor':1}
        result=files.publish(request,2,path);self.assertEqual(calls[0],calls[1])
        doc=calls[0][1]['operations'][0]['document'];self.assertEqual(doc['surface_id'],result['surface_id']);self.assertEqual(doc['activity_id'],'2')
        self.assertEqual(doc['elements']['editor']['props']['value'],'λ')
