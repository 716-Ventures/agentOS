import importlib.util
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('agentos_deploy',Path(__file__).resolve().parents[1]/'deploy.py')
deploy=importlib.util.module_from_spec(spec);spec.loader.exec_module(deploy)

class SourceArchive(unittest.TestCase):
    def test_archive_contains_current_tracked_source_and_excludes_local_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);subprocess.run(['git','init','-q',str(root)],check=True)
            for path in ['outputs/agent-shell/services/runtime.py','outputs/native-shell/src/main.rs','outputs/native-compositor/src/main.rs']:
                file=root/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('tracked source')
            subprocess.run(['git','-C',str(root),'add','outputs'],check=True)
            current=root/'outputs/agent-shell/services/runtime.py';current.write_text('current edit')
            for path in ['outputs/agent-shell/.env','outputs/agent-shell/private.pem','outputs/agent-shell/third-party-licenses/generated','outputs/native-shell/target/cache','outputs/agent-shell/untracked.py']:
                file=root/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('private or untracked')
            with tarfile.open(fileobj=io.BytesIO(deploy.source_archive(root))) as archive:
                self.assertEqual(set(archive.getnames()),{'services/runtime.py','native-shell/src/main.rs','native-compositor/src/main.rs'})
                self.assertEqual(archive.extractfile('services/runtime.py').read(),b'current edit')
            current.unlink();current.symlink_to(root/'outputs/agent-shell/.env')
            with self.assertRaisesRegex(ValueError,'regular files'):deploy.source_archive(root)

if __name__=='__main__':unittest.main()
