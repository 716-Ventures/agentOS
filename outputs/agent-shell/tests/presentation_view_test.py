import copy
import sys
import importlib.util
from pathlib import Path
import unittest
import tempfile
import json
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'client'))
spec=importlib.util.spec_from_file_location('presentation_view',ROOT/'client/presentation_view.py');view=importlib.util.module_from_spec(spec);spec.loader.exec_module(view)

def document():
    return {'surface_id':'view','activity_id':'1','revision':4,'root':'root','elements':{'root':{'type':'Stack@1','slots':{'children':['text','status','field','button']}},'text':{'type':'Text@1','props':{'text':'Café 日本語\x1b]52;c;evil\x07'}},'status':{'type':'Status@1','props':{'value':{'binding':'work'}}},'field':{'type':'TextField@1','props':{'label':'Offset','value':'0'}},'button':{'type':'Button@1','props':{'label':'Read'},'events':{'activate':{'action':'read'}}}},'actions':{'read':{'ref':'action:1','parameters':{'offset':{'kind':'field','element_id':'field'}}}}}

class Projection(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup);self.state=Path(directory.name)
        env=patch.dict(view.os.environ,{'XDG_STATE_HOME':str(self.state)});env.start();self.addCleanup(env.stop)
    def test_table_projects_headers_and_rows_as_inert_terminal_text(self):
        doc=document();doc['elements']['table']={'type':'Table@1','props':{'label':'Observed files','columns':['Name','State'],'rows':[{'id':'a','cells':['日本語','Ready\x1b]52;c;evil\x07']}]}}
        doc['elements']['root']['slots']['children'].append('table')
        lines,controls=view.project(doc,width=40);text='\n'.join(lines)
        self.assertIn('Name | State',text);self.assertIn('日本語 | Ready',text);self.assertNotIn('evil',text);self.assertNotIn('table',controls)
    def test_lists_and_key_value_groups_project_read_only_sanitized_text(self):
        doc=document();doc['elements']['list']={'type':'List@1','props':{'label':'Items','rows':[{'id':'a','cells':['日本語\x1b]52;c;evil\x07']}]}}
        doc['elements']['details']={'type':'KeyValue@1','props':{'label':'Details','rows':[{'id':'mode','cells':['Mode','0644']}]}}
        doc['elements']['root']['slots']['children']+=['list','details']
        lines,controls=view.project(doc);text='\n'.join(lines)
        self.assertIn('• 日本語',text);self.assertIn('Mode: 0644',text);self.assertNotIn('evil',text)
        self.assertNotIn('list',controls);self.assertNotIn('details',controls)
    def test_sections_and_scroll_regions_preserve_labels_content_and_controls(self):
        doc=document();doc['elements']['root']={'type':'Section@1','props':{'label':'Section 日本語\x1b]52;c;evil\x07'},'slots':{'children':['region']}}
        doc['elements']['region']={'type':'Scroll@1','props':{'label':'Scrollable details'},'slots':{'children':['text','field','button']}}
        lines,controls=view.project(doc);text='\n'.join(lines)
        self.assertIn('Section 日本語',text);self.assertIn('Scrollable details',text);self.assertIn('Café 日本語',text);self.assertNotIn('evil',text)
        self.assertEqual(set(controls),{'field','button'})
    def test_tabs_and_splits_project_every_page_and_control_without_hiding_content(self):
        doc=document();doc['elements']['root']={'type':'Tabs@1','props':{'label':'Details','labels':['Read','Edit']},'slots':{'children':['text','split']}}
        doc['elements']['split']={'type':'Split@1','props':{'label':'Inputs'},'slots':{'children':['field','button']}}
        lines,controls=view.project(doc);text='\n'.join(lines)
        self.assertIn('Read',text);self.assertIn('Edit',text);self.assertIn('Inputs',text);self.assertIn('Café 日本語',text)
        self.assertEqual(set(controls),{'field','button'})
    def test_choice_and_toggle_edits_save_typed_drafts_deliberately(self):
        for kind,props,value in [('Choice@1',{'label':'Density','options':['Compact','Comfortable'],'value':'Comfortable'},'Compact'),('Toggle@1',{'label':'Wrap','value':True},'false')]:
            doc=document();doc['elements']['field']={'type':kind,'props':props};calls=[]
            def request(op,**fields):
                calls.append((op,fields))
                if op=='draft.get':return {'draft_revision':0,'draft':None}
                if op=='draft.save':return {'draft_revision':1}
                if op=='presentation.get':return doc
                if op=='presentation.apply':return {'revisions':{'view':5}}
                return {}
            answers=iter([value,'s']);view.edit(request,doc,'field',lambda _:next(answers),lambda _:None)
            self.assertEqual(next(fields['draft'] for op,fields in calls if op=='draft.save'),value)
            self.assertEqual(sum(op=='presentation.apply' for op,_ in calls),1)
            with self.assertRaises(ValueError):view.edit(request,doc,'field',lambda _:'unknown',lambda _:None)
    def test_rich_text_and_charts_keep_exact_inert_terminal_alternatives(self):
        doc=document();doc['elements']['rich']={'type':'RichText@1','props':{'runs':[{'text':'<b>日本語</b>','style':'strong'},{'text':' λ','style':'emphasis'}]}}
        doc['elements']['chart']={'type':'Chart@1','props':{'label':'Comparison','points':[{'id':'a','label':'Loss','value':-2.5},{'id':'b','label':'Gain','value':7}]}}
        doc['elements']['root']['slots']['children']+=['rich','chart'];lines,controls=view.project(doc);text='\n'.join(lines)
        self.assertIn('<b>日本語</b> λ',text);self.assertIn('Loss: -2.5',text);self.assertIn('Gain: 7',text)
        self.assertNotIn('rich',controls);self.assertNotIn('chart',controls)
    def test_view_references_have_explicit_sanitized_navigation_controls(self):
        doc=document()
        for kind in ('DocumentReference@1','ApplicationReference@1'):
            doc['elements']['reference']={'type':kind,'props':{'label':'Related 日本語\x1b]52;c;evil\x07','target':'view-target'}}
            doc['elements']['root']['slots']['children'].append('reference')
            lines,controls=view.project(doc)
            self.assertIn('Related 日本語 → view-target','\n'.join(lines));self.assertNotIn('evil','\n'.join(lines))
            self.assertEqual(controls['reference']['type'],kind)
            doc['elements']['root']['slots']['children'].remove('reference')
    def test_results_and_errors_keep_source_content_and_explicit_recovery_callbacks(self):
        doc=document();doc['elements']['result']={'type':'Result@1','props':{'label':'Completed','value':{'binding':'status'}}}
        doc['elements']['failure']={'type':'Error@1','props':{'label':'Failed','message':'Literal <retry> 日本語','recovery_label':'Inspect work'},'events':{'recover':{'action':'inspect'}}}
        doc['actions']['inspect']={'ref':'inspect-callback'};doc['elements']['root']['slots']['children']+=['result','failure']
        lines,controls=view.project(doc,{'status':{'availability':'available','value':'succeeded'}})
        self.assertIn('Completed: succeeded','\n'.join(lines));self.assertIn('Failed: Literal <retry> 日本語','\n'.join(lines));self.assertIn('[failure] Inspect work','\n'.join(lines))
        self.assertNotIn('result',controls);self.assertIn('failure',controls)
        calls=[]
        def request(op,**fields):
            calls.append((op,fields))
            if op=='action.metadata':return {'source_revision':4,'parameter_schema':{}}
            return {'status':'succeeded'}
        view.invoke(request,doc,'failure')
        invoked=next(fields for op,fields in calls if op=='action.invoke')
        self.assertEqual(invoked['reference'],'inspect-callback');self.assertEqual(invoked['action_id'],'inspect')
        self.assertEqual(invoked['expected_surface_revision'],doc['revision'])
    def test_embedded_terminal_projection_preserves_identity_without_dispatching_input(self):
        doc=document();doc['elements']['pty']={'type':'PtySession@1','props':{'label':'Interactive work','source':'broker:'+'d'*32}}
        doc['elements']['root']['slots']['children'].append('pty');lines,controls=view.project(doc)
        self.assertIn('[Interactive terminal] Interactive work','\n'.join(lines));self.assertNotIn('pty',controls)
    def test_images_have_inert_labeled_terminal_fallbacks(self):
        doc=document();doc['elements']['image']={'type':'Image@1','props':{'label':'Blue pixel 日本語','reference':'resource-'+'a'*32}}
        doc['elements']['root']['slots']['children'].append('image');lines,controls=view.project(doc)
        self.assertIn('[Image] Blue pixel 日本語','\n'.join(lines));self.assertNotIn('image',controls)
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
            return {'interaction.begin':{},'draft.get':{'draft_revision':3,'draft':None},'draft.save':{'draft_revision':4},'presentation.get':{'revision':5},'presentation.apply':{'revisions':{'view':6}},'interaction.end':{}}[op]
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
