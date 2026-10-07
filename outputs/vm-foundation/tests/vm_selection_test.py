import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('selected_vm',Path(__file__).resolve().parents[1]/'vm.py')
vm=importlib.util.module_from_spec(spec);spec.loader.exec_module(vm)

class VMSelection(unittest.TestCase):
    def test_port_and_uuid_must_match_the_selected_bundle_before_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);bundle=run/'test.utm';bundle.mkdir()
            config={'Information':{'UUID':'fixture'},'Network':[{'PortForward':[{'HostPort':22221}]}]}
            (bundle/'config.plist').write_bytes(plistlib.dumps(config))
            (run/'utm.json').write_text(json.dumps({'uuid':'fixture','bundle':str(bundle)}))
            with patch.object(vm,'RUN',run),patch.dict(vm.LOCK,{'ssh_port':22221}):
                self.assertEqual(vm.machine()['uuid'],'fixture')
                config['Network'][0]['PortForward'][0]['HostPort']=22220
                (bundle/'config.plist').write_bytes(plistlib.dumps(config))
                with self.assertRaisesRegex(RuntimeError,'requested port'):vm.machine()
                config['Information']['UUID']='other'
                (bundle/'config.plist').write_bytes(plistlib.dumps(config))
                with self.assertRaisesRegex(RuntimeError,'UUID'):vm.machine()
