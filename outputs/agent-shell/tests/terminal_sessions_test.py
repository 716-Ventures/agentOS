"""PTY protocol bounds, exclusivity, and service-identity separation."""
import base64
import os
from pathlib import Path
import pty
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import broker
import terminal_sessions as terminals


class TerminalTransport(unittest.TestCase):
    def setUp(self):
        self.slaves=[]
        self.sessions=patch.object(terminals,'SESSIONS',{});self.sessions.start()
        def reader(session):
            self.master,self.slave=pty.openpty();self.slaves.append(self.slave)
            os.set_blocking(self.master,False)
            proc=Mock(pid=123);proc.poll.return_value=0
            return dict(fd=self.master,proc=proc,data=b'',end=0,closed=False)
        self.readers=patch.object(terminals,'open_reader',side_effect=reader);self.readers.start()
        terminals.register('fixture',SimpleNamespace(pid=123),Path('/private/socket'),24,80)
        self.token=terminals.control('fixture',{'op':'terminal_attach'})['token']

    def tearDown(self):
        for session in terminals.SESSIONS.values():terminals.close_reader(session)
        for slave in self.slaves:os.close(slave)
        self.readers.stop();self.sessions.stop()

    def call(self,op,**fields):
        return terminals.control('fixture',dict(op='terminal_'+op,token=self.token,**fields))

    def test_raw_bytes_and_tail_survive_retention_limit(self):
        data=b'x'*(terminals.LIMIT+100)+b'\x00\xff\x1b[2J'
        reader=terminals.SESSIONS['fixture']['reader']
        terminals.append(reader,data)
        result=self.call('read',cursor=100)
        self.assertFalse(result['dropped'])
        self.assertTrue(result['reset'])
        self.assertEqual(result['cursor'],0)
        self.assertIsNot(terminals.SESSIONS['fixture']['reader'],reader)

    def test_binary_stream_is_exact_and_completion_drains_before_close(self):
        reader=terminals.SESSIONS['fixture']['reader']
        data=b'hello\x00\xff\x1b[2J'
        terminals.append(reader,data)
        result=self.call('read',cursor=0)
        self.assertEqual(base64.b64decode(result['data']),data)
        terminals.finish('fixture')
        with self.assertRaises(ValueError):terminals.control('fixture',dict(op='terminal_attach'))
        os.close(self.slave);self.slaves.remove(self.slave)
        self.assertTrue(self.call('read',cursor=result['cursor'])['closed'])

    def test_controller_exclusion_expiry_and_detach(self):
        with self.assertRaises(ValueError):terminals.control('fixture',{'op':'terminal_attach'})
        with self.assertRaises(ValueError):terminals.control('fixture',dict(op='terminal_write',token='wrong',data=''))
        terminals.SESSIONS['fixture']['expires']=0
        terminals.reap_expired()
        self.assertIsNone(terminals.SESSIONS['fixture']['reader'])
        with self.assertRaises(ValueError):self.call('read')
        self.token=terminals.control('fixture',{'op':'terminal_attach'})['token']
        self.call('detach')
        self.token=terminals.control('fixture',{'op':'terminal_attach'})['token']

    def test_input_is_bounded_and_checks_backpressure(self):
        result=self.call('write',data=base64.b64encode(b'hello\n').decode())
        self.assertEqual(result['written'],6)
        self.assertEqual(os.read(self.slave,6),b'hello\n')
        for value in ('!',base64.b64encode(b'x'*4097).decode(),123):
            with self.assertRaises(ValueError):self.call('write',data=value)
        with patch.object(terminals.os,'write',side_effect=BlockingIOError):
            self.assertEqual(self.call('write',data='YQ==')['written'],0)

    def test_invalid_size_and_cursor(self):
        for rows,cols in ((0,80),(24,1001),(True,80),(24,'80')):
            with self.assertRaises(ValueError):self.call('resize',rows=rows,cols=cols)
        for cursor in (-1,1,True,'0'):
            with self.assertRaises(ValueError):self.call('read',cursor=cursor)

    def test_finished_transport_retention_is_bounded(self):
        for index in range(40):
            ident=str(index)
            terminals.register(ident,SimpleNamespace(pid=123),Path('/private/socket'),24,80)
            terminals.finish(ident)
        self.assertEqual(sum(not s['running'] for s in terminals.SESSIONS.values()),32)
        self.assertIn('fixture',terminals.SESSIONS)

    def test_terminal_mode_changes_operation_identity(self):
        job=dict(activity=1,argv=['/bin/bash'],cwd='/tmp',workspace='/tmp',background=True,timeout_seconds=60,scope='system')
        self.assertFalse(broker.same_operation(job,1,job['argv'],'/tmp',True,60,'system',terminal=True))

    def test_service_identities_cannot_create_or_control_terminals(self):
        for uid,name in ((999,'agentos'),(1001,'agentos-ai'),(1002,'agentos')):
            with patch.object(broker.pwd,'getpwuid',return_value=SimpleNamespace(pw_name=name)):
                with self.assertRaises(ValueError):broker.human_terminal_user(uid)
        with patch.object(broker.pwd,'getpwuid',return_value=SimpleNamespace(pw_name='developer')):
            broker.human_terminal_user(1000)

    def test_broker_denies_service_terminal_requests_before_assessment(self):
        with patch.object(broker.pwd,'getpwuid',return_value=SimpleNamespace(pw_name='agentos-ai')),patch.object(broker,'assess') as assess:
            with self.assertRaises(ValueError):broker.handle(dict(op='execute',activity=1,argv=['/bin/bash'],purpose='fixture',terminal=True),1001)
            assess.assert_not_called()

    def test_terminal_and_stored_input_cannot_mix(self):
        with self.assertRaises(ValueError):broker.validate(dict(argv=['/bin/cat'],purpose='fixture',terminal=True,stdin='test'))


class TerminalControlRecords(unittest.TestCase):
    def test_split_records_preserve_unicode_controls_and_literal_backslash(self):
        decoder=terminals.ControlOutput()
        data=b'%begin 0 1 0\n%end 0 1 0\n%output %0 hi\\015\\012\\134'+" \u2603".encode()+b'\n'
        received=b''.join(decoder.feed(bytes([byte])) for byte in data)
        self.assertEqual(received,b'hi\r\n\\'+" \u2603".encode())

    def test_protocol_is_bounded_and_rejects_malformed_escapes(self):
        with self.assertRaises(OSError):terminals.ControlOutput().feed(b'x'*(512*1024+1))
        for escape in (b'\\xyz',b'\\777'):
            with self.assertRaises(OSError):terminals.ControlOutput().feed(b'%output %0 '+escape+b'\n')
