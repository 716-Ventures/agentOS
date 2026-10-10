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

class DurableEdits(unittest.TestCase):
 def test_backup_and_new_file_are_private_and_metadata_is_preserved(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);target=root/'note'
   with patch.object(files,'BACKUPS',root/'backups'):
    created=files.run(dict(op='write',path=str(target),content='old',expected_sha256='missing'))
    self.assertEqual(target.stat().st_mode&0o777,0o600)
    target.chmod(0o640)
    updated=files.run(dict(op='write',path=str(target),content='new',expected_sha256=created['sha256']))
    backup=Path(updated['backup']);self.assertEqual(backup.read_bytes(),b'old');self.assertEqual(backup.stat().st_mode&0o777,0o600)
    self.assertEqual(target.stat().st_mode&0o777,0o640)
 def test_backup_sync_failure_prevents_target_replacement(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);target=root/'note';target.write_text('original')
   import hashlib
   with patch.object(files,'BACKUPS',root/'backups'),patch.object(files,'sync_directory',side_effect=OSError('disk unavailable')):
    with self.assertRaises(OSError):files.run(dict(op='write',path=str(target),content='new',expected_sha256=hashlib.sha256(b'original').hexdigest()))
   self.assertEqual(target.read_text(),'original');self.assertFalse(list(root.glob('.agent-edit-*')))
 def test_external_change_during_backup_is_retained(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);target=root/'note';target.write_text('original')
   import hashlib
   def changed(_):target.write_text('external change')
   with patch.object(files,'BACKUPS',root/'backups'),patch.object(files,'sync_directory',side_effect=changed):
    with self.assertRaisesRegex(ValueError,'File changed while'):files.run(dict(op='write',path=str(target),content='new',expected_sha256=hashlib.sha256(b'original').hexdigest()))
   self.assertEqual(target.read_text(),'external change');self.assertFalse(list(root.glob('.agent-edit-*')))

if __name__=='__main__':unittest.main()
