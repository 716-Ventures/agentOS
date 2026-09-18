import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import knowledge as k
class Knowledge(unittest.TestCase):
 def test_revisions_stale_writes_archive_restore(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(k,'PATH',Path(tmp)/'knowledge.json'):
   args=dict(key='workflow',kind='skill',title='Workflow',content='Verify before reporting completion.',basis='observed',source='Successful tool output',expected_revision=0)
   one=k.operate('save',activity=4,**args)
   self.assertEqual(one['revision'],1)
   with self.assertRaises(ValueError):k.operate('save',**args)
   k.operate('save',**{**args,'expected_revision':1,'content':'Updated procedure.'})
   k.operate('archive',key='workflow',expected_revision=2)
   self.assertEqual(k.context(),[])
   restored=k.operate('restore',key='workflow',expected_revision=3,revision=1)
   self.assertEqual(restored['content'],args['content'])
   self.assertEqual(len(k.operate('history',key='workflow')),4)
   self.assertEqual(k.context()[0]['basis'],'observed')
   self.assertEqual(restored['authority'],'reference_only')
if __name__=='__main__':unittest.main()
