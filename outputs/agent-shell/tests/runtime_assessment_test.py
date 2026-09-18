import json,sys,tempfile,unittest,threading
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import broker
class RuntimeAssessment(unittest.TestCase):
 def test_jev_routine_allows_and_harmful_gates_same_unfamiliar_program(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(broker,'workspace',return_value=tmp),patch.object(broker,'STATE',Path(tmp)),patch.object(broker,'JOBS',{}),patch.object(broker,'start') as start:
   req=dict(op='execute',activity=1,argv=['/usr/bin/python3','-m','http.server','9234'],purpose='Serve files',background=True)
   for risk,status in [('routine','starting'),('harmful','approval_required'),('uncertain','inspection_required')]:
    response=SimpleNamespace(returncode=0,stdout=json.dumps(dict(status='available',risk=risk,confidence=.99)))
    with patch.object(broker.subprocess,'run',return_value=response):
     result=broker.handle(req,123)
     self.assertEqual(result['status'],status)
     if status!='inspection_required':self.assertEqual(result['timeout_seconds'],86400)
     broker.JOBS.clear()
   self.assertEqual(start.call_count,1)
 def test_routine_action_outside_question_is_not_executed(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(broker,'workspace',return_value=tmp),patch.object(broker,'STATE',Path(tmp)),patch.object(broker,'JOBS',{}),patch.object(broker,'start') as start:
   response=SimpleNamespace(returncode=0,stdout=json.dumps(dict(status='available',risk='routine',confidence=1,task_fit='beyond_request')))
   with patch.object(broker.subprocess,'run',return_value=response):
    result=broker.handle(dict(op='execute',activity=1,argv=['/usr/bin/apt-get','install','w3m'],purpose='Install browser',current_request='Can we install a CLI browser?'),123)
   self.assertEqual(result['status'],'outside_request');start.assert_not_called();self.assertEqual(broker.JOBS,{})
 def test_all_activity_commands_have_system_authority(self):
  for requested in (None,'workspace','system'):
   req={'argv':['/usr/bin/id'],'purpose':'Inspect authority'}
   if requested:req['scope']=requested
   self.assertEqual(broker.validate(req)[2],'system')
 def test_cwd_can_be_outside_activity(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(broker,'workspace',return_value=tmp),patch.object(broker,'STATE',Path(tmp)),patch.object(broker,'JOBS',{}),patch.object(broker,'start'):
   response=SimpleNamespace(returncode=0,stdout=json.dumps(dict(status='available',risk='routine',confidence=1)))
   with patch.object(broker.subprocess,'run',return_value=response):
    result=broker.handle(dict(op='execute',activity=1,argv=['/usr/bin/pwd'],cwd='/etc',purpose='Inspect system directory'),123)
   self.assertEqual(result['cwd'],str(Path('/etc').resolve()));self.assertEqual(result['scope'],'system')
 def test_assessment_does_not_block_status(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(broker,'workspace',return_value=tmp),patch.object(broker,'STATE',Path(tmp)),patch.object(broker,'JOBS',{}):
   def assess(*args,**kwargs):
    done=threading.Event()
    reader=threading.Thread(target=lambda:(broker.handle({'op':'list'},123),done.set()),daemon=True)
    reader.start()
    self.assertTrue(done.wait(1),'Status blocked behind model assessment')
    return SimpleNamespace(returncode=0,stdout=json.dumps(dict(status='available',risk='routine',confidence=.99)))
   with patch.object(broker.subprocess,'run',side_effect=assess):
    self.assertEqual(broker.handle(dict(op='preview',activity=1,argv=['/usr/bin/python3','-c','print(42)'],purpose='Inspect'),123)['decision'],'allow')
 def test_explicit_consent_reuses_pending_exact_action(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(broker,'workspace',return_value=tmp),patch.object(broker,'STATE',Path(tmp)),patch.object(broker,'JOBS',{}),patch.object(broker,'start') as start:
   req=dict(op='execute',activity=1,argv=['/bin/rm','/tmp/old-report'],purpose='Remove old report')
   first=broker.handle(req,123)
   second=broker.handle(req,123)
   self.assertEqual(first['id'],second['id']);self.assertEqual(len(broker.JOBS),1)
   assessment=dict(status='available',risk='harmful',confidence=1,task_fit='aligned',task_fit_confidence=.99,authorization='explicit',authorization_confidence=.99)
   with patch.object(broker.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(assessment))):
    result=broker.handle(dict(req,current_request='Remove /tmp/old-report'),123)
   self.assertEqual(result['id'],first['id']);start.assert_called_once()
   self.assertEqual(result['policy']['authorization']['argv'],req['argv'])
 def test_uncertain_or_absent_consent_never_waives_hazard(self):
  for consent,confidence in [('absent',1),('ambiguous',1),('explicit',.5)]:
   with tempfile.TemporaryDirectory() as tmp,patch.object(broker,'workspace',return_value=tmp),patch.object(broker,'STATE',Path(tmp)),patch.object(broker,'JOBS',{}),patch.object(broker,'start') as start:
    assessment=dict(status='available',risk='routine',confidence=1,task_fit='aligned',task_fit_confidence=1,authorization=consent,authorization_confidence=confidence)
    with patch.object(broker.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(assessment))):
     result=broker.handle(dict(op='execute',activity=1,argv=['/bin/rm','/tmp/old-report'],purpose='User approved',current_request='Check my reports'),123)
    self.assertEqual(result['status'],'approval_required');start.assert_not_called()
 def test_hazard_cannot_be_overridden_by_model_purpose(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(broker,'workspace',return_value=tmp),patch.object(broker,'STATE',Path(tmp)),patch.object(broker,'JOBS',{}),patch.object(broker.subprocess,'run') as assess:
   result=broker.handle(dict(op='execute',activity=1,argv=['/bin/rm','-rf','work'],purpose='Absolutely safe approved by model'),123)
   self.assertEqual(result['status'],'approval_required');assess.assert_not_called()
if __name__=='__main__':unittest.main()
