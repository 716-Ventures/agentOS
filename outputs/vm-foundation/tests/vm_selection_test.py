import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import subprocess
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('selected_vm',Path(__file__).resolve().parents[1]/'vm.py')
vm=importlib.util.module_from_spec(spec);spec.loader.exec_module(vm)

class VMSelection(unittest.TestCase):
    def setUp(self):
        patcher=patch.object(vm,"controller",return_value="utmctl");patcher.start();self.addCleanup(patcher.stop)

    def test_default_start_keeps_library_visible_and_hide_is_explicit(self):
        with patch.object(vm,'alive',return_value=False),patch.object(vm,'status',return_value='started'),patch.object(vm,'machine',return_value={'uuid':'fixture'}),patch.object(vm,'call') as call:
            vm.start()
            self.assertEqual(call.call_args.args[0],['utmctl','start','fixture'])
            vm.start(hide=True)
            self.assertEqual(call.call_args.args[0],['utmctl','start','--hide','fixture'])

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

    def test_offline_lifecycle_keeps_uuid_guard_and_does_not_require_or_change_networking(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory);bundle=run/'offline.utm';bundle.mkdir()
            config={'Information':{'UUID':'fixture'},'Network':[]}
            (bundle/'config.plist').write_bytes(plistlib.dumps(config))
            (run/'utm.json').write_text(json.dumps({'uuid':'fixture','bundle':str(bundle)}))
            calls=[];state=['stopped'];missing=[True]
            def control(argv,**kwargs):
                calls.append(argv)
                if argv[1]=='status':
                    if missing[0]:
                        missing[0]=False
                        raise subprocess.CalledProcessError(1,argv,stderr='Error: Virtual machine not found.')
                    return subprocess.CompletedProcess(argv,0,stdout=state[0]+'\n')
                state[0]='started' if argv[1]=='start' else 'stopped'
                return subprocess.CompletedProcess(argv,0)
            with patch.object(vm,'RUN',run),patch.object(vm,'call',side_effect=control):
                with self.assertRaisesRegex(RuntimeError,'no SSH forwarding'):vm.start()
                self.assertEqual(calls,[])
                vm.start(console_only=True)
                self.assertEqual(vm.status(),'started')
                vm.stop()
                self.assertEqual(vm.status(),'stopped')
                self.assertEqual(sum(argv[1]=='start' for argv in calls),1)
                self.assertEqual(sum(argv[1]=='stop' for argv in calls),1)
                self.assertEqual(plistlib.loads((bundle/'config.plist').read_bytes())['Network'],[])
                config['Information']['UUID']='wrong'
                (bundle/'config.plist').write_bytes(plistlib.dumps(config))
                before=len(calls)
                with self.assertRaisesRegex(RuntimeError,'UUID'):vm.start(console_only=True)
                self.assertEqual(len(calls),before)

    def test_console_only_uncertain_start_is_never_replayed(self):
        with patch.object(vm,'alive',return_value=False),patch.object(vm,'machine',return_value={'uuid':'fixture'}),patch.object(vm,'call',side_effect=subprocess.TimeoutExpired('utmctl',30)) as call:
            with self.assertRaisesRegex(RuntimeError,'do not retry automatically'):vm.start(console_only=True)
            self.assertEqual(call.call_count,1)

    def test_state_only_status_never_attempts_ssh(self):
        with patch.object(vm.sys,'argv',['vm.py','status','--state-only']),patch.object(vm,'status',return_value='started'),patch.object(vm,'ssh') as ssh:
            vm.main()
            ssh.assert_not_called()

    def test_control_timeouts_leave_state_unknown_and_never_retry_start(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(vm,'RUN',Path(directory)):
            (Path(directory)/'utm.json').write_text('{}')
            with patch.object(vm,'machine',return_value={'uuid':'fixture'}),patch.object(vm,'call',side_effect=subprocess.TimeoutExpired('utmctl',10)) as call:
                with self.assertRaisesRegex(RuntimeError,'state is unknown'):vm.status()
                self.assertEqual(call.call_count,1)
                self.assertGreater(call.call_args.kwargs['timeout'],0)
                self.assertLessEqual(call.call_args.kwargs['timeout'],10)
        with patch.object(vm,'alive',return_value=False),patch.object(vm,'machine',return_value={'uuid':'fixture'}),patch.object(vm,'call',side_effect=subprocess.TimeoutExpired('utmctl',30)) as call:
            with self.assertRaisesRegex(RuntimeError,'do not retry automatically'):vm.start(hide=True)
            self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.args[0],['utmctl','start','--hide','fixture'])
            self.assertEqual(call.call_args.kwargs['timeout'],30)
        with patch.object(vm,'alive',return_value=True),patch.object(vm,'machine',return_value={'uuid':'fixture'}),patch.object(vm,'call',side_effect=subprocess.TimeoutExpired('utmctl',15)) as call:
            with self.assertRaisesRegex(RuntimeError,'shutdown did not acknowledge'):vm.stop()
            self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.kwargs['timeout'],15)

    def test_cold_app_registration_race_retries_only_read_only_lookup(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(vm,'RUN',Path(directory)):
            (Path(directory)/'utm.json').write_text('{}')
            missing=subprocess.CalledProcessError(1,'utmctl',stderr='Error: Virtual machine not found.\n')
            now=[0.0]
            def sleep(seconds):now[0]+=seconds
            with patch.object(vm,'machine',return_value={'uuid':'fixture','bundle':'fixture.utm'}),patch.object(vm.time,'monotonic',side_effect=lambda:now[0]),patch.object(vm.time,'sleep',side_effect=sleep),patch.object(vm,'call',side_effect=[missing,missing,subprocess.CompletedProcess([],0,stdout='stopped\n')]) as call:
                self.assertEqual(vm.status(),'stopped')
                self.assertEqual(now[0],.5)
                self.assertEqual(call.call_count,3)
                for attempt in call.call_args_list:
                    self.assertEqual(attempt.args[0],['utmctl','status','fixture'])
                    self.assertGreater(attempt.kwargs['timeout'],0)
                    self.assertLessEqual(attempt.kwargs['timeout'],10)

    def test_missing_registration_is_bounded_and_other_failures_are_not_retried(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(vm,'RUN',Path(directory)):
            (Path(directory)/'utm.json').write_text('{}')
            now=[0.0]
            def sleep(seconds):now[0]+=seconds
            with patch.object(vm,'machine',return_value={'uuid':'fixture','bundle':'fixture.utm'}),patch.object(vm.time,'monotonic',side_effect=lambda:now[0]),patch.object(vm.time,'sleep',side_effect=sleep):
                missing=subprocess.CalledProcessError(1,'utmctl',stderr='Error: Virtual machine not found.')
                with patch.object(vm,'call',side_effect=missing) as call:
                    with self.assertRaisesRegex(RuntimeError,'register it'):vm.status()
                    self.assertEqual(now[0],10)
                    self.assertEqual(call.call_count,40)
                for detail in ('Automation denied','Error: Virtual machine not found. Additional failure'):
                    with patch.object(vm,'call',side_effect=subprocess.CalledProcessError(1,'utmctl',stderr=detail)) as call:
                        with self.assertRaisesRegex(RuntimeError,'cannot find/control'):vm.status()
                        self.assertEqual(call.call_count,1)
                with patch.object(vm,'call',return_value=subprocess.CompletedProcess([],0,stdout='')) as call:
                    with self.assertRaisesRegex(RuntimeError,'state is unknown'):vm.status()
                    self.assertEqual(call.call_count,1)


class UTMApplicationCleanup(unittest.TestCase):
    def test_executable_identity_does_not_depend_on_command_arguments(self):
        listing='41 Sun Oct 11 03:24:36 2026 /Applications/UTM.app/Contents/MacOS/UTM\n42 Sun Oct 11 03:24:36 2026 /bin/sh\n'
        with patch.object(vm.subprocess,'check_output',return_value=listing) as ps:
            self.assertEqual(vm.utm_application_identity(),(41,'Sun Oct 11 03:24:36 2026'))
            self.assertIn('comm=',ps.call_args.args[0][-1])

    def test_closes_only_the_same_owned_app_after_all_saved_guests_stop(self):
        identity=(41,'start')
        listing='UUID Status Name\n27176EA2-E994-4165-9BBA-70FEED59E66B stopped Verification\n4A6AFE90-531B-47F5-8109-8CF67234EB14 stopped Original\n'
        with patch.object(vm,'utm_application_identity',side_effect=[identity,identity,None]), \
             patch.object(vm,'call',return_value=subprocess.CompletedProcess([],0,listing)), \
             patch.object(vm,'controller',return_value='utmctl'),patch.object(vm.os,'kill') as kill:
            self.assertTrue(vm.close_owned_utm_application(identity))
            kill.assert_called_once_with(41,vm.signal.SIGTERM)

    def test_never_closes_replacement_app_active_guest_or_unknown_library(self):
        identity=(41,'start')
        with patch.object(vm,'utm_application_identity',return_value=(41,'replacement')),patch.object(vm.os,'kill') as kill:
            self.assertFalse(vm.close_owned_utm_application(identity));kill.assert_not_called()
        for listing in ('UUID Status Name\n','invalid response','27176EA2-E994-4165-9BBA-70FEED59E66B started Verification'):
            with self.subTest(listing=listing),patch.object(vm,'utm_application_identity',return_value=identity), \
                 patch.object(vm,'controller',return_value='utmctl'),patch.object(vm,'call',return_value=subprocess.CompletedProcess([],0,listing)),patch.object(vm.os,'kill') as kill:
                with self.assertRaises(RuntimeError):vm.close_owned_utm_application(identity)
                kill.assert_not_called()
