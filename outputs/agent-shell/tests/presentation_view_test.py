import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('presentation_view',ROOT/'client/presentation_view.py');view=importlib.util.module_from_spec(spec);spec.loader.exec_module(view)

def document():
    return {'surface_id':'view','activity_id':'1','revision':4,'root':'root','elements':{'root':{'type':'Stack@1','slots':{'children':['text','status','field','button']}},'text':{'type':'Text@1','props':{'text':'Café 日本語\x1b]52;c;evil\x07'}},'status':{'type':'Status@1','props':{'value':{'binding':'work'}}},'field':{'type':'TextField@1','props':{'label':'Offset','value':'0'}},'button':{'type':'Button@1','props':{'label':'Read'},'events':{'activate':{'action':'read'}}}},'actions':{'read':{'ref':'action:1','parameters':{'offset':{'kind':'field','element_id':'field'}}}}}

class Projection(unittest.TestCase):
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
