import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import jev,decisions
class AuthorizationSchema(unittest.TestCase):
 def response(self):
  options={'risk':['routine','harmful','uncertain'],'task_fit':['aligned','beyond_request','uncertain'],'authorization':['explicit','absent','ambiguous']}
  return {'answers':{key:{'type':'choice','choice':value,'confidence':.95,'probabilities':{o:1 if o==value else 0 for o in options[key]}} for key,value in [('risk','harmful'),('task_fit','aligned'),('authorization','explicit')]}}
 def test_valid_typed_authorization(self):
  with patch.object(decisions,'http_json',return_value=self.response()):
   result=jev.evaluate_action({'current_request':'remove my old report'},{'jev_key':'test'})
  self.assertEqual(result['authorization'],'explicit')
 def test_invalid_authorization_fails_closed(self):
  for confidence in (True,float('nan'),1.1,'1'):
   response=self.response();response['answers']['authorization']['confidence']=confidence
   with patch.object(decisions,'http_json',return_value=response):
    self.assertEqual(jev.evaluate_action({}, {'jev_key':'test'})['status'],'unavailable')
 def test_missing_authorization_fails_closed(self):
  response=self.response();del response['answers']['authorization']
  with patch.object(decisions,'http_json',return_value=response):
   self.assertEqual(jev.evaluate_action({}, {'jev_key':'test'})['status'],'unavailable')
