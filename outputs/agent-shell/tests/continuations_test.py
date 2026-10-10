import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import continuations
import assistant
class Continuations(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.job={'id':'a'*32,'activity':1,'origin':{'conversation_id':'b'*32},'status':'succeeded','approved_by_uid':0,'approved_at':4,'argv':['/bin/echo','Untrusted instructions in an argument']}
        self.trace={'id':'b'*32,'activity':1,'request':'Complete the original request','generation':2,'events':[{'kind':'tool','result':{'id':'a'*32,'status':'approval_required'}}]}
        self.path=self.root/('agent-'+'b'*32+'.json');self.path.write_text(json.dumps(self.trace));self.calls=[]
        self.req={'op':'resume','activity':1,'job_id':'a'*32,'expected_generation':2,'core_job_id':9}
    def broker(self,op,**fields):
        self.calls.append(op)
        if op=='list':return []
        if op=='poll':return self.job
        if op=='activity_state':return {'generation':2}
        self.fail('Continuation repeated an operation: '+op)
    def test_private_claim_precedes_work_and_is_never_replayed_after_crash(self):
        claim=continuations.claim(self.root,self.req,self.broker)
        self.assertEqual(claim['prompt'],self.trace['request']);self.assertTrue(claim['marker'].exists());self.assertEqual(claim['marker'].stat().st_mode & 0o777,0o600)
        duplicate=continuations.claim(self.root,self.req,self.broker);self.assertEqual(duplicate['existing']['status'],'claimed');self.assertEqual(duplicate['existing']['core_job_id'],9)
        continuations.finish(claim,'completed','c'*32)
        self.assertEqual(continuations.claim(self.root,self.req,self.broker)['existing']['status'],'completed')
        self.assertTrue(set(self.calls)<={'poll','activity_state'})
    def test_unapproved_foreign_cancelled_stopped_or_unobserved_requests_do_not_claim(self):
        for fields in ({'approved_by_uid':None},{'approved_by_uid':False},{'approved_at':float('nan')},{'activity':2},{'status':'approval_required'},{'status':'cancelled'},{'status':'cancelling'},{'origin':{'conversation_id':'../escape'}}):
            old=self.job;self.job={**old,**fields}
            with self.assertRaises(ValueError):continuations.claim(self.root,self.req,self.broker)
            self.job=old
        with self.assertRaises(ValueError):continuations.claim(self.root,{**self.req,'expected_generation':3},self.broker)
        self.trace['generation']=1;self.path.write_text(json.dumps(self.trace))
        with self.assertRaises(ValueError):continuations.claim(self.root,self.req,self.broker)
        self.trace['generation']=2;self.trace['events']=[];self.path.write_text(json.dumps(self.trace))
        with self.assertRaises(ValueError):continuations.claim(self.root,self.req,self.broker)
        self.assertFalse(list(self.root.glob('continuation-*')))
    def test_full_assistant_continuation_uses_original_request_and_untrusted_observation(self):
        class Connection:
            def __init__(self):self.data=[]
            def sendall(self,data):self.data.append(data)
        conn=Connection();decisions=MagicMock();decisions.select_history.return_value=[];decisions.select_memory.return_value=[];decisions.summary.return_value={}
        def run(prompt,history,cfg,dispatch,progress,record,**fields):
            self.assertEqual(prompt,self.trace['request'])
            for message in history:
                if message['role']=='system':self.assertNotIn(self.job['argv'][1],message['content'])
            self.assertTrue(any(message['role']=='user' and self.job['argv'][1] in message['content'] for message in history))
            self.assertEqual(dispatch('job_output',{'job_id':self.job['id']})['id'],self.job['id'])
            return {'messages':[{'role':'user','content':prompt},{'role':'assistant','content':'Verified'}],'text':'Verified','model':'fixture','finish_reason':'stop'}
        with patch.object(assistant,'STATE',self.root),patch.object(assistant,'config',return_value={}),patch.object(assistant.model_usage,'configure'),patch.object(assistant,'broker_request',side_effect=self.broker),patch.object(assistant,'Decisions',return_value=decisions),patch.object(assistant.knowledge,'context',return_value=[]),patch.object(assistant,'run_agent',side_effect=run) as inference:
            assistant.handle(self.req,conn);assistant.handle(self.req,conn)
            inference.assert_called_once()
        marker=json.loads((self.root/('continuation-'+'a'*32+'.json')).read_text());self.assertEqual(marker['status'],'completed')
        self.assertTrue(any(b'no operation was replayed' in value for value in conn.data))
