import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import providers as p
class Retries(unittest.TestCase):
 def test_paid_authorization_is_model_specific(self):
  model='inclusionai/ling-3.0-flash'
  with patch.object(p,'http_json',return_value={'data':[{'id':model,'type':'language'}]}),patch.object(p,'require_free') as free:
   p.require_selected(model,{'paid_models_allowed':[model]});free.assert_not_called()
   p.require_selected('other/model',{'paid_models_allowed':[model]});free.assert_called_once_with('other/model')
 def test_paid_model_does_not_switch_models(self):
  with patch.object(p,'require_selected'),patch.object(p,'http_json',side_effect=p.RateLimited(60)) as http:
   with self.assertRaises(p.RateLimited):p.complete([],[],{'gateway_key':'fixture','gateway_model':'paid/model','paid_models_allowed':['paid/model']})
   self.assertEqual(http.call_count,1)
 def test_retry_then_free_fallback(self):
  result={'choices':[{'message':{'content':'Done'},'finish_reason':'stop'}]}
  with patch.object(p,'require_free') as guard,patch.object(p.time,'sleep') as sleep,patch.object(p,'http_json',side_effect=[p.RateLimited(3),p.RateLimited(),result]) as http:
   answer=p.complete([],[],{'gateway_key':'fixture'})
   self.assertEqual(answer['model'],'poolside/laguna-s-2.1-free');self.assertEqual(http.call_count,3)
   sleep.assert_called_once_with(3);self.assertEqual(guard.call_count,2)
 def test_long_retry_delay_not_ignored_on_same_model(self):
  result={'choices':[{'message':{'content':'Done'},'finish_reason':'stop'}]}
  with patch.object(p,'require_free'),patch.object(p.time,'sleep') as sleep,patch.object(p,'http_json',side_effect=[p.RateLimited(60),result]) as http:
   p.complete([],[],{'gateway_key':'fixture'});sleep.assert_not_called();self.assertEqual(http.call_count,2)
 def test_paid_fallback_rejected(self):
  with patch.object(p,'require_free',side_effect=[None,p.ProviderError('not free')]),patch.object(p,'http_json',side_effect=p.RateLimited(60)) as http:
   with self.assertRaises(p.ProviderError):p.complete([],[],{'gateway_key':'fixture'})
   self.assertEqual(http.call_count,1)
 def test_other_failure_not_retried(self):
  with patch.object(p,'require_free'),patch.object(p,'http_json',side_effect=p.ProviderError('401')) as http:
   with self.assertRaises(p.ProviderError):p.complete([],[],{'gateway_key':'fixture'})
   self.assertEqual(http.call_count,1)
if __name__=='__main__':unittest.main()
