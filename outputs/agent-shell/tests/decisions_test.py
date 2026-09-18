import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import decisions,agent
from providers import ProviderError

def choice_answer(selected,options):
 return {'type':'choice','choice':selected,'confidence':.99,'probabilities':{o:float(o==selected) for o in options}}

def final_check(grounding='supported',learn=0):
 return {'status':'available','answers':{'grounding':{'choice':grounding,'confidence':.99},'outcome':{'choice':'complete'},'learning':{'noul':learn}}}

def answer(text='Done'):
 return {'message':{'role':'assistant','content':text},'model':'fixture','finish_reason':'stop'}

def tool(name,args):
 return {'message':{'role':'assistant','content':None,'tool_calls':[{'id':'x','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]},'model':'fixture','finish_reason':'tool_calls'}

class DecisionsTests(unittest.TestCase):
 def test_mixed_primitives_and_full_distributions(self):
  questions={'c':decisions.choice('select',{'a':'A','b':'B'}),'s':{'type':'score','criteria':['none','some','direct']},'n':{'type':'noul'}}
  data={'answers':{'c':choice_answer('b',['a','b']),'s':{'type':'score','score':1.5,'confidence':.5,'probabilities':{'0':0,'1':.5,'2':.5}},'n':{'type':'noul','noul':.8}}}
  self.assertEqual(decisions.validate_answers(data,questions),data['answers'])
  for invalid in (float('nan'),True,-1,2):
   data['answers']['n']['noul']=invalid
   with self.assertRaises(ValueError):decisions.validate_answers(data,questions)
 def test_unknown_choice_or_missing_probabilities_rejected(self):
  q={'c':decisions.choice('select',{'a':'A','b':'B'})}
  for a in ({'type':'choice','choice':'a','confidence':1},{'type':'choice','choice':'oops','confidence':1,'probabilities':{'a':1,'b':0}}):
   with self.assertRaises(ValueError):decisions.validate_answers({'answers':{'c':a}},q)
 def test_mismatched_score_rejected(self):
  with self.assertRaises(ValueError):decisions.validate_answers({'answers':{'s':{'type':'score','score':2,'confidence':1,'probabilities':{'0':1,'1':0,'2':0}}}},{'s':{'type':'score','criteria':['a','b','c']}})
 def test_budget_bounds_calls(self):
  d=decisions.Decisions({'jev_key':'test'})
  with patch.object(decisions,'evaluate',return_value={'status':'unavailable','reason':'test'}) as fn:
   for _ in range(15):d.ask('test',{}, {})
  self.assertEqual(fn.call_count,12);self.assertEqual(d.summary()['fallbacks'],15)
 def test_provider_failure_falls_back(self):
  with patch.object(decisions,'http_json',side_effect=ProviderError('fail')):
   self.assertEqual(decisions.evaluate({}, {}, {'jev_key':'test'})['status'],'unavailable')
 def test_secret_is_not_sent(self):
  with patch.object(decisions,'http_json') as http:
   self.assertEqual(decisions.evaluate({'password':'really-private'}, {}, {'jev_key':'test'})['reason'],'credential_material')
   http.assert_not_called()
 def test_memory_ranking_preserves_preferences(self):
  d=decisions.Decisions({})
  candidates=[{'key':'preference','basis':'user_preference'},{'key':'noise'},{'key':'useful'}]
  with patch.object(d,'ask',return_value={'status':'available','answers':{'0':{'score':0},'1':{'score':2}}}):
   self.assertEqual([x['key'] for x in d.select_memory('goal',candidates)],['preference','useful'])
 def test_history_selection_preserves_requests_and_tool_pairs(self):
  turns=[[{'role':'user','content':str(i)},{'role':'assistant','tool_calls':[{'id':str(i)}]},{'role':'tool','tool_call_id':str(i),'content':'data'}] for i in range(7)]
  original=json.dumps(turns);d=decisions.Decisions({})
  with patch.object(d,'rank',return_value=[{'index':1}]):result=d.select_history('request',turns)
  self.assertEqual([m['content'] for m in result if m['role']=='user'],[str(i) for i in range(7)])
  self.assertEqual([m['tool_call_id'] for m in result if m['role']=='tool'],['1','5','6'])
  self.assertEqual(json.dumps(turns),original)
 def test_dynamic_selection_does_not_dispatch(self):
  d=decisions.Decisions({})
  with patch.object(d,'ask',return_value={'status':'available','answers':{}}) as ask:
   result=d.select_option('goal','Which observed target?', [{'id':'a','description':'target A'},{'id':'b','description':'target B'}],'Observed two targets')
  self.assertTrue(result['advisory_only']);self.assertIn('none_of_these',ask.call_args.args[2]['selection']['criteria'])
 def test_unverified_answer_triggers_verification_and_bounded_failure(self):
  d=decisions.Decisions({})
  with patch.object(d,'completion',return_value=final_check('unsupported')),patch.object(agent,'complete',return_value=answer('Installed successfully')) as model:
   result=agent.run('install',[],{},lambda *a:self.fail('Unexpected tool'),lambda _:None,lambda _:None,decisions=d)
  self.assertEqual(model.call_count,3);self.assertNotIn('Installed successfully',result['text'])
 def test_corrected_answer_is_used(self):
  d=decisions.Decisions({})
  with patch.object(d,'completion',side_effect=[final_check('contradicted'),final_check()]),patch.object(agent,'complete',side_effect=[answer('Done'),answer('The job failed; nothing was installed.')]):
   result=agent.run('install',[],{},lambda *a:None,lambda _:None,lambda _:None,decisions=d)
  self.assertIn('failed',result['text'])
 def test_unavailable_completion_is_disclosed(self):
  d=decisions.Decisions({})
  with patch.object(d,'completion',return_value={'status':'unavailable'}),patch.object(agent,'complete',return_value=answer()):
   result=agent.run('question',[],{},lambda *a:None,lambda _:None,lambda _:None,decisions=d)
  self.assertIn('unavailable',result['text'])
 def test_failed_tool_gets_recovery_advice(self):
  d=decisions.Decisions({})
  with patch.object(d,'completion',return_value=final_check()),patch.object(d,'recovery',return_value={'status':'available'}) as recovery,patch.object(agent,'complete',side_effect=[tool('execute',{'argv':['/bin/false'],'purpose':'test'}),answer('Failed')]):
   agent.run('test',[],{},lambda *a:{'status':'failed','exit_code':1},lambda _:None,lambda _:None,decisions=d)
  recovery.assert_called_once()
 def test_unsupported_memory_never_written(self):
  d=decisions.Decisions({});writes=[]
  args={'key':'bad','kind':'skill','title':'Fake','content':'Unverified','basis':'observed','source':'guess','expected_revision':0}
  with patch.object(d,'learning',return_value={'status':'available','answers':{'support':{'choice':'unsupported'}}}),patch.object(d,'recovery',return_value={'status':'unavailable'}),patch.object(d,'completion',return_value=final_check()),patch.object(agent,'complete',side_effect=[tool('knowledge_save',args),answer()]):
   agent.run('work',[],{},lambda *a:writes.append(a),lambda _:None,lambda _:None,decisions=d)
  self.assertEqual(writes,[])
 def test_low_confidence_support_requires_correction(self):
  d=decisions.Decisions({});weak=final_check();weak['answers']['grounding']['confidence']=.2
  with patch.object(d,'completion',side_effect=[weak,final_check()]),patch.object(agent,'complete',side_effect=[answer('Uncertain'),answer('Verified from output')]) as model:
   result=agent.run('work',[],{},lambda *a:None,lambda _:None,lambda _:None,decisions=d)
  self.assertEqual(model.call_count,2);self.assertEqual(result['text'],'Verified from output')
 def test_unfinished_authorized_work_continues(self):
  d=decisions.Decisions({});partial=final_check();partial['answers']['next']={'choice':'continue_work'}
  with patch.object(d,'completion',side_effect=[partial,final_check()]),patch.object(agent,'complete',side_effect=[answer('Would you like me to continue?'),answer('Completed')]) as model:
   result=agent.run('do it',[],{},lambda *a:None,lambda _:None,lambda _:None,decisions=d)
  self.assertEqual(model.call_count,2);self.assertEqual(result['text'],'Completed')
 def test_list_results_do_not_break_completion(self):
  d=decisions.Decisions({})
  with patch.object(d,'completion',return_value=final_check()),patch.object(agent,'complete',side_effect=[tool('list_jobs',{}),answer()]):
   result=agent.run('jobs',[],{},lambda *a:[],lambda _:None,lambda _:None,decisions=d)
  self.assertEqual(result['text'],'Done')
if __name__=='__main__':unittest.main()
