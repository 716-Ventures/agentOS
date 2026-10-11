import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import threading
import json
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import screen_reader

def authorize(control):
    control.listen(1)
    def serve():
        connection,_=control.accept()
        with connection:
            with connection.makefile('rb') as stream:request=json.loads(stream.readline())
            assert request['op']=='screen_reader.register'
            assert Path('/proc',str(request['pid']),'stat').read_text().rsplit(')',1)[1].split()[19]==request['start']
            connection.sendall(b'{"ok":true,"result":{}}\n')
    worker=threading.Thread(target=serve,daemon=True);worker.start();return worker

@unittest.skipUnless(Path('/proc/self/stat').exists(),'Linux process start identity required')
class ScreenReader(unittest.TestCase):
    def test_owned_reader_is_reaped_and_an_unrelated_process_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);binary=root/'reader';binary.write_text('#!/bin/sh\nexec sleep 60\n');binary.chmod(0o700)
            with socket.socket(socket.AF_UNIX) as display,socket.socket(socket.AF_UNIX) as control:
                display.bind(str(root/'wayland-1'));control.bind(str(root/'agentos-compositor-123.sock'));worker=authorize(control)
                unrelated=subprocess.Popen(['sleep','60'],start_new_session=True)
                reader=screen_reader.Reader(str(binary))
                try:
                    with patch.object(screen_reader.subprocess,'Popen',wraps=subprocess.Popen) as launch:
                        reader.poll(root,{**os.environ,'WAYLAND_SOCKET':'19','AGENT_OS_TRUSTED_SHELL':'1','LD_PRELOAD':'private-capability.so','DISPLAY':':4'},123)
                        process=reader.process;env=launch.call_args.kwargs['env']
                        self.assertEqual(env['WAYLAND_DISPLAY'],str(root/'wayland-1'))
                        self.assertTrue(all(key not in env for key in ('WAYLAND_SOCKET','AGENT_OS_TRUSTED_SHELL','LD_PRELOAD','DISPLAY')))
                        self.assertNotIn('--replace',launch.call_args.args[0]);worker.join(timeout=5);self.assertFalse(worker.is_alive())
                        reader.close();reader.close()
                        self.assertIsNotNone(process.poll());self.assertIsNone(unrelated.poll())
                        self.assertEqual(launch.call_count,1)
                finally:
                    reader.close();unrelated.terminate();unrelated.wait(timeout=5)

    def test_missing_display_waits_and_exited_reader_is_not_restarted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);reader=screen_reader.Reader('/usr/bin/false')
            reader.poll(root,{},123);self.assertFalse(reader.attempted)
            with socket.socket(socket.AF_UNIX) as display,socket.socket(socket.AF_UNIX) as control:
                display.bind(str(root/'wayland-1'));control.bind(str(root/'agentos-compositor-123.sock'));worker=authorize(control);reader.poll(root,{},123)
                process=reader.process;process.wait(timeout=5)
                reader.poll(root,{},123);reader.poll(root,{},123)
                self.assertIs(reader.process,process);self.assertTrue(reader.reported);reader.close()

    def test_wayland_version_floor_and_preexisting_reader_are_checked_before_launch(self):
        with patch.object(screen_reader.Path,'is_file',return_value=True):
            for version in ('Orca 48.1','unknown'):
                with patch.object(screen_reader.subprocess,'check_output',return_value=version):
                    with self.assertRaisesRegex(ValueError,'51'):screen_reader.require_reader()
            with patch.object(screen_reader.subprocess,'check_output',side_effect=['Orca 51.0','(true,)']):
                with self.assertRaisesRegex(ValueError,'already owns'):screen_reader.require_reader()
            with patch.object(screen_reader.subprocess,'check_output',side_effect=['Orca 51.0','(false,)','(false,)']):
                self.assertEqual(screen_reader.require_reader(),'/usr/bin/orca')
