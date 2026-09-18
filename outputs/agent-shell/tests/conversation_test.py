import importlib.util,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('ui',Path(__file__).resolve().parents[1]/'client/agent_os.py');ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)
class ConversationTests(unittest.TestCase):
 def setUp(self):self.proposal={'id':'a'*32,'argv':['/usr/bin/true'],'activity':1,'scope':'system','status':'approval_required'}
 def test_explicit_approval_and_ambiguity(self):
  self.assertEqual(ui.approval_target('approved',[self.proposal]),self.proposal)
  self.assertIsNone(ui.approval_target('yes',[self.proposal]))
  self.assertIsNone(ui.approval_target('Can you install git?',[self.proposal]))
  for proposals in ([],[self.proposal,self.proposal]):
   with self.assertRaises(ValueError):ui.approval_target('approved',proposals)
  with self.assertRaises(ValueError):ui.approval_target('approve '+'b'*32,[self.proposal])
  self.assertEqual(ui.approval_target('approve '+'a'*32,[self.proposal]),self.proposal)
 def test_approval_rechecks_before_sudo(self):
  for change in ({'status':'succeeded'},{'argv':['/bin/false']},{'activity':2}):
   with patch.object(ui,'broker_request',return_value={**self.proposal,**change}),patch.object(ui.subprocess,'run') as run:
    with self.assertRaises(RuntimeError):ui.approve_operation(self.proposal)
    run.assert_not_called()
 def test_turn_keeps_question_answer_and_failure(self):
  j={'argv':['python3','-u','/usr/local/lib/agent-os/services/worker.py','ask','1','Install git']}
  text=ui.conversation_turn(j,'Thinking…\nUsing execute…\nReading the results…\nPlease approve.\n\nModel: test\n')
  self.assertIn('Install git',text);self.assertIn('Please approve.',text);self.assertNotIn('Using execute',text)
  self.assertIn('limiting requests',ui.conversation_turn(j,'Thinking…\nAgent OS: HTTP 429'))
  live=ui.conversation_turn(j,'Using execute…\nBroker job abc: running\nUpdate: Checking how it went…\n')
  self.assertIn('Checking how it went',live);self.assertNotIn('Broker job',live);self.assertNotIn('execute',live)
  malformed=ui.conversation_turn(j,'Answer:\n<tool_call>execute</tool_call>\n\nModel: test\n')
  self.assertNotIn('<tool_call>',malformed)
  self.assertIn('Earlier actions may have started',malformed)
  self.assertEqual(ui.approval_target('approve 1',[self.proposal]),self.proposal)
if __name__=='__main__':unittest.main()
