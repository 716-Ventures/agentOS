import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('setup',Path(__file__).resolve().parents[1]/'services/setup.py')
setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
class FirstRun(unittest.TestCase):
    def test_unavailable_services_and_devices_are_explicit(self):
        with patch.object(setup,'command',return_value={'available':False,'text':'Unavailable'}),patch.object(Path,'read_text',side_effect=FileNotFoundError):
            value=setup.snapshot()
        self.assertFalse(value['network']['default_route']);self.assertFalse(value['microphone']['available']);self.assertIsNone(value['providers'])
    def test_configured_route_is_not_claimed_as_connectivity(self):
        with patch.object(setup,'command',return_value={'available':True,'text':'[{"gateway":"192.0.2.1"}]'}),patch.object(Path,'read_text',return_value='{"configuration":[{"provider":"Test","model":"Test","configured":false,"gateway_key":"never copied"}]}'):
            value=setup.snapshot()
        self.assertTrue(value['network']['default_route']);self.assertNotIn('gateway_key',json.dumps(value));self.assertIn('does not establish',value['network']['note'])
    def test_completion_is_private_atomic_and_replaces_previous_record(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_STATE_HOME':directory}):
            setup.complete({'network':False});setup.complete({'network':True});path=setup.state_path()
            self.assertEqual(json.loads(path.read_text())['checks'],{'network':True});self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(list(path.parent.iterdir()),[path])
