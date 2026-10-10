import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('startup_control',Path(__file__).resolve().parents[1]/'build_utmctl.py')
control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)


class ControlIntegrity(unittest.TestCase):
    def test_controller_falls_back_only_when_no_build_exists_and_rejects_changed_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'control'
            self.assertEqual(control.controller(output),'utmctl')
            output.mkdir();binary=output/'utmctl';binary.write_bytes(b'fixture')
            (output/'build.json').write_text(json.dumps({'source_revision':control.REVISION,
                'launch_policy':control.POLICY,'binary_sha256':hashlib.sha256(b'fixture').hexdigest()}))
            self.assertEqual(control.controller(output),str(binary))
            binary.write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'changed'):control.controller(output)
            binary.unlink();binary.symlink_to(output/'build.json')
            with self.assertRaisesRegex(RuntimeError,'symlink'):control.controller(output)

    def test_launch_patch_removes_hidden_app_flag_without_changing_library_hide_option(self):
        source='app.launchFlags = [.defaults, .andHide]\nif environment.hide { library.close() }'
        patched=control.patch_launch(source)
        self.assertIn('app.launchFlags = [.defaults]',patched)
        self.assertIn('if environment.hide { library.close() }',patched)
        self.assertNotIn('.andHide',patched)
        for invalid in ('changed upstream',source+'\n'+source):
            with self.assertRaises(ValueError):control.patch_launch(invalid)
