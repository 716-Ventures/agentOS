import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import jev
class AuthorizationSchema(unittest.TestCase):
 def response(self):
  return {'answers':{key:{'type':'choice','choice':value,'confidence':.95} for key,value in [('risk','harmful'),('task_fit','aligned'),('authorization','explicit')]}}
 def test_valid_typed_authorization(self):
  with patch.object(jev,'http_json',return_value=self.response()):
   result=jev.evaluate_action({'current_request':'remove my old report'},{'jev_key':'test'})
  self.assertEqual(result['authorization'],'explicit')
 def test_invalid_authorization_fails_closed(self):
  for confidence in (True,float('nan'),1.1,'1'):
   response=self.response();response['answers']['authorization']['confidence']=confidence
   with patch.object(jev,'http_json',return_value=response):
    self.assertEqual(jev.evaluate_action({}, {'jev_key':'test'})['status'],'unavailable')
 def test_missing_authorization_fails_closed(self):
  response=self.response();del response['answers']['authorization']
  with patch.object(jev,'http_json',return_value=response):
   self.assertEqual(jev.evaluate_action({}, {'jev_key':'test'})['status'],'unavailable')
