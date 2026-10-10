import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('desktop_session',ROOT/'services/desktop_session.py');session=importlib.util.module_from_spec(spec);spec.loader.exec_module(session)
class DesktopSession(unittest.TestCase):
    def test_runtime_is_a_private_owned_login_directory(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_RUNTIME_DIR':directory}),patch.object(session.os,'getuid',return_value=os.stat(directory).st_uid):
            if os.stat(directory).st_uid>=1000:self.assertEqual(session.runtime_directory(),Path(directory))
            os.chmod(directory,0o755)
            with self.assertRaises(ValueError):session.runtime_directory()
    def test_session_command_uses_exact_executable_paths_and_no_shell_interpretation(self):
        with tempfile.TemporaryDirectory(prefix='desktop with spaces ') as directory:
            root=Path(directory)
            for name in ('agent-os-compositor','agent-os-desktop'):(root/name).write_text('#!/bin/sh\nexit 0\n');(root/name).chmod(0o700)
            argv=session.child_command(root,root/'core with spaces.sock')
            self.assertEqual(argv,[str(root/'agent-os-compositor'),'--command',str(root/'agent-os-desktop'),'--socket',str(root/'core with spaces.sock')])
            self.assertEqual(session.child_command(root,root/'core.sock',17)[-2:],['--activity','17'])
            for invalid in (0,-1,True,'17'):
                with self.assertRaises(ValueError):session.child_command(root,root/'core.sock',invalid)
            self.assertIn('watch=true',session.configuration(root/'child','headless'))
            with self.assertRaises(ValueError):session.configuration(Path('/tmp/child\npath=other'),'drm')

    def test_shutdown_does_not_signal_a_reused_process_identity(self):
        owned=(123,('old-start',55,1000,Path('/runtime/compositor')))
        with patch.object(session,'process_identity',return_value=('new-start',55,1000,Path('/runtime/compositor'))),patch.object(session.os,'kill') as kill:
            session.stop_compositor(Path('/tmp'),owned)
            kill.assert_not_called()

    def test_direct_session_launches_no_display_host_and_reaps_the_owned_compositor(self):
        command=['/runtime/agent-os-compositor','--command','/runtime/agent-os-desktop']
        proc=MagicMock();proc.pid=456;proc.poll.return_value=0;proc.wait.return_value=0
        identity=('start',os.getpid(),os.getuid(),Path(command[0]))
        with patch.object(session.subprocess,'Popen',return_value=proc) as spawn,patch.object(session,'process_identity',return_value=identity),patch.object(session,'stop_compositor') as stop:
            self.assertEqual(session.direct_session(command,{'AGENT_OS_COMPOSITOR_BACKEND':'winit'},Path('/runtime'),lambda:False),0)
        spawn.assert_called_once_with(command,env={'AGENT_OS_COMPOSITOR_BACKEND':'drm'},start_new_session=True)
        self.assertEqual(stop.call_args.args,(Path('/runtime'),(456,identity)))
        proc.wait.assert_called_once_with(timeout=5)

    def test_reaping_never_signals_a_child_that_was_already_reaped(self):
        def wait(pid,options):return (pid,0) if pid==123 or options==0 else (0,0)
        identity=('start',os.getpid(),os.getuid(),Path('/runtime/renderer'))
        with patch.object(session.Path,'read_text',return_value='123 456'),patch.object(session.os,'waitpid',side_effect=wait),patch.object(session,'process_identity',return_value=identity),patch.object(session.os,'getpgid',return_value=456),patch.object(session.os,'killpg') as kill,patch.object(session.time,'monotonic',side_effect=[0,4]):
            session.reap_session_children()
        self.assertEqual(kill.call_args_list[0].args,(456,session.signal.SIGTERM))
        self.assertEqual(kill.call_args_list[1].args,(456,session.signal.SIGKILL))
        self.assertTrue(all(call.args[0]!=123 for call in kill.call_args_list))
