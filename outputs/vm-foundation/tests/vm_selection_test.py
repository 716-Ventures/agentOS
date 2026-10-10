import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import subprocess
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('selected_vm',Path(__file__).resolve().parents[1]/'vm.py')
vm=importlib.util.module_from_spec(spec);spec.loader.exec_module(vm)

class VMSelection(unittest.TestCase):
    def test_default_start_avoids_console_creation_and_visible_start_is_explicit(self):
        with patch.object(vm,'alive',return_value=False),patch.object(vm,'status',return_value='started'),patch.object(vm,'machine',return_value={'uuid':'fixture'}),patch.object(vm,'call') as call:
            vm.start()
            self.assertEqual(call.call_args.args[0],['utmctl','start','--hide','fixture'])
            vm.start(hide=False)
            self.assertEqual(call.call_args.args[0],['utmctl','start','fixture'])

    def test_successful_cli_exit_requires_observed_running_guest(self):
        for observed in ('stopped', 'starting', 'paused', 'unknown'):
            with self.subTest(observed=observed),patch.object(vm,'alive',return_value=False),patch.object(vm,'status',return_value=observed),patch.object(vm,'machine',return_value={'uuid':'fixture'}),patch.object(vm,'call') as call:
                with self.assertRaisesRegex(RuntimeError,'do not retry automatically'):
                    vm.start()
                self.assertEqual(call.call_count,1)

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

    def test_control_timeouts_leave_state_unknown_and_never_retry_start(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(vm,'RUN',Path(directory)):
            (Path(directory)/'utm.json').write_text('{}')
            with patch.object(vm,'machine',return_value={'uuid':'fixture'}),patch.object(vm,'call',side_effect=subprocess.TimeoutExpired('utmctl',10)) as call:
                with self.assertRaisesRegex(RuntimeError,'state is unknown'):vm.status()
                self.assertEqual(call.call_count,1)
                self.assertEqual(call.call_args.kwargs['timeout'],10)
        with patch.object(vm,'alive',return_value=False),patch.object(vm,'machine',return_value={'uuid':'fixture'}),patch.object(vm,'call',side_effect=subprocess.TimeoutExpired('utmctl',30)) as call:
            with self.assertRaisesRegex(RuntimeError,'do not retry automatically'):vm.start(hide=True)
            self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.args[0],['utmctl','start','--hide','fixture'])
            self.assertEqual(call.call_args.kwargs['timeout'],30)
        with patch.object(vm,'alive',return_value=True),patch.object(vm,'machine',return_value={'uuid':'fixture'}),patch.object(vm,'call',side_effect=subprocess.TimeoutExpired('utmctl',15)) as call:
            with self.assertRaisesRegex(RuntimeError,'shutdown did not acknowledge'):vm.stop()
            self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.kwargs['timeout'],15)
