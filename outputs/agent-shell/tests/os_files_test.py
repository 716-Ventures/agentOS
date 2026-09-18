import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import files
class OSFiles(unittest.TestCase):
 def test_guarded_edits_outside_activity(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);activity=root/'activity';activity.mkdir();outside=root/'system-file'
   original=Path.cwd()
   try:
    os.chdir(activity)
    with patch.object(files,'BACKUPS',root/'backups'):
     first=files.run(dict(op='write',path=str(outside),content='original',expected_sha256='missing'))
     second=files.run(dict(op='write',path=str(outside),content='changed',expected_sha256=first['sha256']))
     self.assertEqual(Path(second['backup']).read_text(),'original')
     self.assertEqual(outside.read_text(),'changed')
     with self.assertRaises(ValueError):files.run(dict(op='write',path=str(outside),content='stale',expected_sha256=first['sha256']))
   finally:os.chdir(original)
if __name__=='__main__':unittest.main()
