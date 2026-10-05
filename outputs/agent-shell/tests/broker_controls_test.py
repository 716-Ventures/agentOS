"""Exercise the dashboard's direct stop path without model or guest services."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

source = Path(__file__).resolve().parents[1] / 'client/agent_os.py'
spec = importlib.util.spec_from_file_location('broker_controls_client', source)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


class BrokerControls(unittest.TestCase):
    def test_keyboard_cancels_broker_work_without_cancelling_core_job(self):
        for status in ('running', 'approval_required'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                screen = Mock()
                screen.getmaxyx.return_value = (40, 140)
                screen.get_wch.side_effect = ['X', '\n', 'q']
                pane = ui.leaf(None)
                layout = dict(tree=pane, focus=pane['id'], zoom=None, revision=0)
                snapshot = dict(activities=[dict(id=1, name='Activity')], jobs=[], revision=0)
                job = dict(id='a'*32, activity=1, argv=['/bin/sleep', '60'], purpose='Wait for cancellation', status=status)
                def broker(op, **fields):
                    if op == 'list':
                        self.assertEqual(fields, {})
                        return [job]
                    if op == 'poll': return {**job, 'output': ''}
                    if op == 'cancel': return {'status': 'cancelled'}
                    self.fail('Unexpected broker operation: '+op)
                with patch.object(ui.curses, 'curs_set'), patch.object(ui.curses, 'set_escdelay'), \
                     patch.object(ui.curses, 'mousemask'), patch.object(ui.curses, 'has_colors', return_value=False), \
                     patch.object(ui, 'selection_path', return_value=Path(tmp)/'selection.json'), \
                     patch.object(ui, 'previous', return_value=1), patch.object(ui, 'remember'), \
                     patch.object(ui, 'request', return_value=snapshot) as core, \
                     patch.object(ui, 'layout_request', return_value=layout), \
                     patch.object(ui, 'broker_request', side_effect=broker) as control:
                    ui.dashboard(screen)
                    control.assert_any_call('cancel', job_id=job['id'])
                    self.assertFalse(any(call.args[0] == 'cancel' for call in core.call_args_list))
