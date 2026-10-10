import copy
import importlib.util
from pathlib import Path
import unittest
import tempfile
import json
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('presentation_view',ROOT/'client/presentation_view.py');view=importlib.util.module_from_spec(spec);spec.loader.exec_module(view)

def document():
    return {'surface_id':'view','activity_id':'1','revision':4,'root':'root','elements':{'root':{'type':'Stack@1','slots':{'children':['text','status','field','button']}},'text':{'type':'Text@1','props':{'text':'Café 日本語\x1b]52;c;evil\x07'}},'status':{'type':'Status@1','props':{'value':{'binding':'work'}}},'field':{'type':'TextField@1','props':{'label':'Offset','value':'0'}},'button':{'type':'Button@1','props':{'label':'Read'},'events':{'activate':{'action':'read'}}}},'actions':{'read':{'ref':'action:1','parameters':{'offset':{'kind':'field','element_id':'field'}}}}}

class Projection(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup);self.state=Path(directory.name)
        env=patch.dict(view.os.environ,{'XDG_STATE_HOME':str(self.state)});env.start();self.addCleanup(env.stop)
    def test_completed_multiline_input_survives_interruption(self):
        doc=document();doc['elements']['field']['props']['multiline']=True;calls=[]
        def request(op,**fields):calls.append(op);return {'draft_revision':0,'draft':None}
        answers=iter(['First λ','Second 日本語'])
        def read(_):
            try:return next(answers)
            except StopIteration:raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):view.edit(request,doc,'field',read,lambda _:None)
        files=list(view.recovery_root().glob('*.json'));self.assertEqual(len(files),1)
        self.assertEqual(json.loads(files[0].read_text())['text'],'First λ\nSecond 日本語')
        self.assertEqual(files[0].stat().st_mode & 0o777,0o600);self.assertEqual(calls[-1],'interaction.end')
    def test_recovery_is_explicit_revision_guarded_and_kept_after_save_failure(self):
        path=Path(view.preserve('Recovered λ','view','field'));calls=[]
        def request(op,**fields):
            calls.append((op,fields))
            if op=='draft.get':return {'draft_revision':7,'draft':'Current draft'}
            if op=='draft.save':raise RuntimeError('backend unavailable')
            return {}
        answers=iter(['1','restore'])
        with self.assertRaises(RuntimeError):view.recover(request,document(),lambda _:next(answers),lambda _:None)
        self.assertTrue(path.exists());self.assertEqual(calls[-1][0],'interaction.end')
        saved=next(fields for op,fields in calls if op=='draft.save');self.assertEqual(saved['expected_draft_revision'],7)
        def success(op,**fields):
            calls.append((op,fields));return {'draft_revision':8,'draft':'Current draft'}
        answers=iter(['1','restore']);view.recover(success,document(),lambda _:next(answers),lambda _:None)
        self.assertFalse(path.exists());self.assertNotIn('presentation.apply',[op for op,_ in calls])
    def test_recovery_ignores_symlinks_malformed_and_other_surfaces(self):
        target=self.state/'external';target.write_text('private');(view.recovery_root()/'recovered-link.json').symlink_to(target)
        (view.recovery_root()/'recovered-malformed.json').write_text('{bad')
        other=Path(view.preserve('Other','another-view','field'));out=[]
        view.recover(lambda *_a,**_k:self.fail('No IPC expected'),document(),lambda _:self.fail('No input expected'),out.append)
        self.assertIn('No local recovery drafts',out[0]);self.assertTrue(other.exists());self.assertEqual(target.read_text(),'private')

    def test_shared_content_is_inert_and_unknown_sources_stay_unavailable(self):
        lines,controls=view.project(document(),{'work':{'availability':'unavailable','value':'succeeded'}})
        text='\n'.join(lines);self.assertIn('Café 日本語',text);self.assertNotIn('evil',text);self.assertNotIn('\x1b',text);self.assertIn('Unavailable',text);self.assertNotIn('succeeded',text)
        self.assertEqual(set(controls),{'field','button'})
    def test_terminal_edit_uses_a_lease_and_current_exact_revision_then_ends_ownership(self):
        calls=[]
        def request(op,**fields):
            calls.append((op,fields))
            return {'interaction.begin':{},'draft.get':{'draft_revision':3,'draft':None},'draft.save':{'draft_revision':4},'presentation.snapshot':{'documents':{'view':{'revision':5}}},'presentation.apply':{'revisions':{'view':6}},'interaction.end':{}}[op]
        inputs=iter(['42','s']);view.edit(request,document(),'field',lambda _:next(inputs),lambda _:None)
        self.assertEqual(calls[0][0],'interaction.begin');self.assertEqual(calls[-1][0],'interaction.end')
        apply=next(fields for op,fields in calls if op=='presentation.apply');self.assertEqual(apply['expected_revisions'],{'view':5});self.assertEqual(apply['operations'][0]['expected_draft_revision'],4)
    def test_callback_uses_edited_data_and_reconciles_a_lost_response_without_replay(self):
        calls=[]
        def request(op,**fields):
            calls.append((op,fields))
            if op=='action.metadata':return {'parameter_schema':{'offset':{'type':'integer','minimum':0,'maximum':100}},'source_revision':8}
            if op=='draft.get':return {'draft':'42'}
            if op=='action.invoke':raise RuntimeError('Response lost')
            if op=='action.status':return {'status':'succeeded'}
            raise AssertionError(op)
        self.assertEqual(view.invoke(request,document(),'button','click')['status'],'succeeded')
        invoke=[fields for op,fields in calls if op=='action.invoke'];self.assertEqual(len(invoke),1);self.assertEqual(invoke[0]['parameters'],{'offset':42});self.assertEqual(invoke[0]['expected_surface_revision'],4)
    def test_field_input_cannot_become_an_execution_target(self):
        schema={'parameter_schema':{'offset':{'type':'integer','minimum':0,'maximum':100}}}
        for text in ['-1','$(id)','101','1.5']:
            with self.assertRaises(ValueError):view.parameters(document()['actions']['read'],schema,lambda _:text)
    def test_edit_interruption_releases_the_lease(self):
        calls=[]
        def request(op,**fields):calls.append(op);return {'draft_revision':0}
        def interrupted(_):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):view.edit(request,document(),'field',interrupted,lambda _:None)
        self.assertEqual(calls[-1],'interaction.end')
