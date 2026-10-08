"""PTY protocol bounds, exclusivity, and service-identity separation."""
import base64
import os
from pathlib import Path
import pty
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import broker
import terminal_sessions as terminals


class TerminalTransport(unittest.TestCase):
    def setUp(self):
        self.master,self.slave=pty.openpty()
        self.sessions=patch.object(terminals,'SESSIONS',{});self.sessions.start()
        terminals.register('fixture',self.master,SimpleNamespace(pid=123))
        self.token=terminals.control('fixture',{'op':'terminal_attach'})['token']

    def tearDown(self):
        terminals.finish('fixture');os.close(self.slave);self.sessions.stop()

    def call(self,op,**fields):
        return terminals.control('fixture',dict(op='terminal_'+op,token=self.token,**fields))

    def test_raw_bytes_and_tail_survive_retention_limit(self):
        data=b'x'*(terminals.LIMIT+100)+b'\x00\xff\x1b[2J'
        terminals.append('fixture',data)
        result=self.call('read',cursor=0)
        self.assertTrue(result['dropped'])
        self.assertEqual(len(terminals.SESSIONS['fixture']['data']),terminals.LIMIT)
        cursor=result['cursor'];received=base64.b64decode(result['data'])
        while cursor<len(data):
            result=self.call('read',cursor=cursor);cursor=result['cursor'];received+=base64.b64decode(result['data'])
        self.assertEqual(received,data[-terminals.LIMIT:])
        terminals.finish('fixture');self.assertTrue(self.call('read',cursor=cursor)['closed'])

    def test_controller_exclusion_expiry_and_detach(self):
        with self.assertRaises(ValueError):terminals.control('fixture',{'op':'terminal_attach'})
        with self.assertRaises(ValueError):terminals.control('fixture',dict(op='terminal_write',token='wrong',data=''))
        terminals.SESSIONS['fixture']['expires']=0
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
        with patch.object(terminals.os,'set_blocking'),patch.object(terminals.os,'close'):
            for index in range(40):
                ident=str(index)
                terminals.register(ident,-1,SimpleNamespace(pid=123));terminals.finish(ident)
        self.assertEqual(sum(s['fd'] is None for s in terminals.SESSIONS.values()),32)
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
