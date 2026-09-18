import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
from layout_service import LayoutStore
from layout_state import leaves
class LayoutTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'state.db';self.store=LayoutStore(self.path)
  self.state=self.call('ensure')
 def tearDown(self):self.store.db.close();self.tmp.cleanup()
 def call(self,op,actor='user',**kw):return self.store.handle(dict(op=op,activity=1,**kw),100,actor)
 def change(self,op,**kw):
  self.state=self.call('apply',expected_revision=self.state['revision'],action=dict(operation=op,**kw));return self.state
 def test_persistent_undo_and_stale_revision(self):
  original=self.state['tree'];self.change('split',surface_id=self.state['focus'],axis='x')
  with self.assertRaises(ValueError):self.call('apply',expected_revision=0,action={'operation':'undo'})
  self.store.db.close();self.store=LayoutStore(self.path)
  self.change('undo');self.assertEqual(self.state['tree'],original)
 def test_typing_protects_agent_but_not_human(self):
  self.call('editing',client_id='terminal',active=True)
  with self.assertRaisesRegex(ValueError,'typing'):self.call('apply',actor='agent',expected_revision=0,action={'operation':'zoom','surface_id':self.state['focus']})
  self.change('zoom',surface_id=self.state['focus'])
  self.call('editing',client_id='terminal',active=False)
  self.call('apply',actor='agent',expected_revision=1,action={'operation':'restore'})
  self.assertEqual(self.call('events')[-1]['actor'],'agent')
 def test_import_once_swap_and_limit(self):
  self.change('split',surface_id=self.state['focus'],axis='y');ids=[p['id'] for p in leaves(self.state['tree'])]
  self.change('swap',surface_id=ids[0],other_id=ids[1]);self.assertEqual([p['id'] for p in leaves(self.state['tree'])],ids[::-1])
  self.assertEqual(self.call('ensure',seed={'bad':True})['revision'],2)
  for _ in range(4):self.change('split',surface_id=self.state['focus'],axis='x')
  with self.assertRaises(ValueError):self.change('split',surface_id=self.state['focus'],axis='x')
 def test_bad_actions_atomic(self):
  for action in ({'operation':'split','surface_id':self.state['focus'],'axis':'bad'},{'operation':'view','surface_id':self.state['focus'],'view':'bad'},{'operation':'close','surface_id':self.state['focus']}):
   with self.assertRaises(ValueError):self.call('apply',expected_revision=0,action=action)
  self.assertEqual(self.call('snapshot')['revision'],0)
if __name__=='__main__':unittest.main()
