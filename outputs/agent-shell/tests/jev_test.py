import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import jev
from providers import ProviderError
class JevTests(unittest.TestCase):
 def fixture(self):return {'model':'jev-fixture','answers':{'effect':{'type':'choice','choice':'creation','confidence':.9},'next_step':{'type':'choice','choice':'inspect_state','confidence':.8}}}
 def test_typed_advice_does_not_authorize(self):
  with patch.object(jev,'http_json',return_value=self.fixture()) as call:
   r=jev.review(['/usr/bin/touch','new.txt'],'workspace',{'jev_key':'fixture'})
   self.assertEqual(r['status'],'available');self.assertFalse(r['authorizes_execution']);self.assertEqual(call.call_args.kwargs['timeout'],8)
 def test_invalid_and_unavailable_remain_advisory(self):
  f=self.fixture();f['answers']['effect']['choice']='allow_root'
  for fixture in (f,{}, {'answers':{'effect':{'type':'choice','choice':'creation','confidence':float('nan')}}}):
   with patch.object(jev,'http_json',return_value=fixture):self.assertEqual(jev.review(['/usr/bin/touch','new.txt'],'workspace',{'jev_key':'fixture'})['status'],'unavailable')
  with patch.object(jev,'http_json',side_effect=ProviderError('offline')):
   self.assertEqual(jev.review(['/usr/bin/touch','new.txt'],'workspace',{'jev_key':'fixture'})['status'],'unavailable')
 def test_missing_key_and_credentials_make_no_call(self):
  with patch.object(jev,'http_json') as call:
   jev.review(['/usr/bin/touch','new.txt'],'workspace',{})
   jev.review(['/usr/bin/curl','--header','Authorization: secret'],'workspace',{'jev_key':'fixture'})
   call.assert_not_called()
if __name__=='__main__':unittest.main()
