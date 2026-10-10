import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
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
            self.assertIn('watch=true',session.configuration(root/'child','headless'))
            with self.assertRaises(ValueError):session.configuration(Path('/tmp/child\npath=other'),'drm')

    def test_shutdown_does_not_signal_a_reused_process_identity(self):
        owned=(123,('old-start',55,1000,Path('/runtime/compositor')))
        with patch.object(session,'process_identity',return_value=('new-start',55,1000,Path('/runtime/compositor'))),patch.object(session.os,'kill') as kill:
            session.stop_compositor(Path('/tmp'),owned)
            kill.assert_not_called()
