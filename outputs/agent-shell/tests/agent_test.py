import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import agent
import providers


def call(name='execute', args='{"argv":["/usr/bin/uname","-r"],"purpose":"Inspect kernel"}'):
    return {'message': {'role':'assistant','content':None,'tool_calls':[{'id':'c1','type':'function','function':{'name':name,'arguments':args}}]}, 'model':'fixture','finish_reason':'tool_calls'}

def answer():
    return {'message':{'role':'assistant','content':'Measured kernel.'},'model':'fixture','finish_reason':'stop'}

class AgentTests(unittest.TestCase):
    def test_tool_loop_without_jev(self):
        with patch.object(agent,'complete',side_effect=[call(),answer()]) as complete:
            events=[]; used=[]
            result=agent.run('what kernel?',[],{'gateway_key':'fixture'},lambda name,args: used.append(name) or {'kernel':'real-fixture'},lambda _:None,events.append)
            self.assertEqual(used,['execute'])
            self.assertEqual(result['messages'][2]['role'],'tool')
            self.assertIn('real-fixture',result['messages'][2]['content'])
            self.assertEqual(result['text'],'Measured kernel.')

    def test_unavailable_tool_and_arguments_never_execute(self):
        for name,args in [('shell','{}'),('execute','{"command":"rm"}'),('read_file','[]'),('execute','not json')]:
            with self.subTest(name=name,args=args), patch.object(agent,'complete',side_effect=[call(name,args),answer()]):
                with patch('builtins.print'):
                    used=[]
                    result=agent.run('try',[],{},used.append,lambda _:None,lambda _:None)
                    self.assertEqual(used,[])
                    self.assertIn('error',result['messages'][2]['content'])

    def test_loop_is_bounded(self):
        with patch.object(agent,'complete',return_value=call()), self.assertRaises(providers.ProviderError):
            agent.run('loop',[],{},lambda name,args: {},lambda _:None,lambda _:None)

    def test_markup_is_repaired_not_executed_or_saved(self):
        malformed = {'message': {'role':'assistant','content':'<tool_call>execute<arg_value>["rm","-rf","/"]</arg_value></tool_call>'}, 'model':'fixture','finish_reason':'stop'}
        with patch.object(agent,'complete',side_effect=[malformed,call(),answer()]) as complete:
            used=[];events=[]
            result=agent.run('inspect kernel',[],{},lambda name,args: used.append(args['argv']) or {'ok':True},lambda _:None,events.append)
        self.assertEqual(used,[['/usr/bin/uname','-r']])
        self.assertNotIn('<tool_call>',str(result['messages']))
        self.assertEqual(events[0]['kind'],'protocol_repair')

    def test_final_budget_repair_keeps_running_job_and_disables_tools(self):
        malformed = {'message': {'role':'assistant','content':'<tool_call>execute</tool_call>'}, 'model':'fixture','finish_reason':'stop'}
        flags=[]
        responses=iter([call(),malformed,answer()])
        def complete(messages,tools,cfg,allow_tools):
            flags.append(allow_tools)
            if len(flags)>1:self.assertIn('still-running-job',str(messages))
            return next(responses)
        with patch.object(agent,'MAX_ROUNDS',2),patch.object(agent,'complete',side_effect=complete):
            used=[]
            agent.run('set up development',[],{},lambda name,args:used.append(name) or {'job_id':'still-running-job','status':'running'},lambda _:None,lambda _:None)
        self.assertEqual(used,['execute'])
        self.assertEqual(flags,[True,False,False])

    def test_repeated_markup_fails_without_dispatch(self):
        malformed={'message':{'role':'assistant','content':'<tool_call>execute</tool_call>'},'model':'fixture','finish_reason':'stop'}
        with patch.object(agent,'complete',return_value=malformed) as complete:
            used=[]
            with self.assertRaisesRegex(providers.ProviderError,'malformed reply was not executed'):
                agent.run('setup',[],{},lambda *args:used.append(args),lambda _:None,lambda _:None)
            self.assertEqual(complete.call_count,3)
            self.assertEqual(used,[])

    def test_old_markup_is_removed_from_model_history(self):
        with patch.object(agent,'complete',return_value=answer()) as complete:
            agent.run('continue',[{'role':'assistant','content':'<tool_call>execute</tool_call>'}],{},lambda *args:None,lambda _:None,lambda _:None)
            self.assertNotIn('<tool_call>',str(complete.call_args.args[0]))

    def test_empty_response_recovers_with_prior_tool_evidence(self):
        used=[]
        with patch.object(agent,'complete',side_effect=[call(),providers.InvalidAgentResponse('empty'),answer()]) as complete:
            result=agent.run('continue',[],{},lambda name,args:used.append(name) or {'job_id':'existing','status':'running'},lambda _:None,lambda _:None)
            self.assertEqual(used,['execute'])
            self.assertIn('existing',str(complete.call_args.args[0]))
            self.assertEqual(result['text'],'Measured kernel.')

    def test_empty_response_retries_are_bounded(self):
        with patch.object(agent,'complete',side_effect=providers.InvalidAgentResponse('empty')) as complete:
            with self.assertRaisesRegex(providers.ProviderError,'after retrying'):
                agent.run('continue',[],{},lambda *a:self.fail('No dispatch'),lambda _:None,lambda _:None)
            self.assertEqual(complete.call_count,3)

    def test_final_summary_omits_tool_definitions(self):
        with patch.object(providers,'require_selected'),patch.object(providers,'http_json',return_value={'choices':[{'message':{'content':'Partial progress'},'finish_reason':'stop'}]}) as http:
            providers.complete([],agent.TOOLS,{'gateway_key':'fixture'},allow_tools=False)
            body=http.call_args.args[1]
            self.assertNotIn('tools',body)
            self.assertNotIn('tool_choice',body)

    def test_blank_answer_is_recoverable(self):
        with patch.object(providers,'require_selected'),patch.object(providers,'http_json',return_value={'choices':[{'message':{'content':'  '},'finish_reason':'stop'}]}):
            with self.assertRaises(providers.InvalidAgentResponse):
                providers.complete([],agent.TOOLS,{'gateway_key':'fixture'})

    def test_provider_requires_only_gateway_key(self):
        with patch.object(providers,'require_free'), patch.object(providers,'http_json',return_value={'choices':[{'message':{'content':'hi'},'finish_reason':'stop'}]}) as http:
            providers.complete([],agent.TOOLS,{'gateway_key':'fixture'})
            self.assertEqual(http.call_count,1)
            self.assertIn('/chat/completions',http.call_args.args[0])

if __name__=='__main__': unittest.main()
