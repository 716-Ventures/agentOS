import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
import broker
import agent
import assistant
import worker
from layout_state import canonical, surface
spec=importlib.util.spec_from_file_location('work_ui',Path(__file__).resolve().parents[1]/'client/agent_os.py')
ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)

class WorkVisibility(unittest.TestCase):
    def test_projection_distinguishes_ids_and_retains_removed_activity(self):
        snapshot={'activities':[{'id':1,'name':'Visible'}], 'jobs':[{'id':2,'activity_id':1,'status':'running'}]}
        jobs=ui.work_projection(snapshot,[{'id':'a'*32,'activity':3,'status':'running'}])
        self.assertEqual(jobs[0]['work_ref'],'core:2')
        self.assertEqual(jobs[1]['id'],'broker:'+'a'*32)
        self.assertIn('removed',jobs[1]['activity_name'])
        with patch.object(ui,'request') as core,patch.object(ui,'broker_request') as control:
            ui.stop_work('broker:'+'a'*32);control.assert_called_once_with('cancel',job_id='a'*32);core.assert_not_called()
            ui.stop_work('core:2');core.assert_called_once_with('cancel',job_id=2)

    def test_broker_surface_roundtrip_and_invalid_references(self):
        pane=surface('broker:'+'a'*32,'output')
        state={'tree':pane,'focus':pane['id'],'zoom':None}
        self.assertEqual(canonical(state)['tree']['job'],pane['job'])
        self.assertTrue(agent.valid_args('layout_change',dict(operation='bind',expected_revision=0,job_id=pane['job'])))
        for value in ('broker:2','broker:../private',True,0):
            pane['job']=value
            with self.assertRaises(ValueError):canonical(state)
            with self.assertRaises(ValueError):ui.work_reference(value)
            self.assertFalse(agent.valid_args('layout_change',dict(operation='bind',expected_revision=0,job_id=value)))

    def test_stop_activity_closes_worker_startup_race_and_waits(self):
        running={'id':2,'activity_id':1,'status':'running'}
        snapshots=iter([{'jobs':[running]}, {'jobs':[]}])
        calls=[]
        def core(op,**fields):
            calls.append(('core',op))
            return next(snapshots) if op=='snapshot' else {'status':'cancelling'}
        def control(op,**fields):
            calls.append(('broker',op))
            if op=='stop_activity':return {'generation':len(calls),'jobs':[{'id':'a'*32}]}
            return {'status':'cancelled'}
        with patch.object(ui,'request',side_effect=core),patch.object(ui,'broker_request',side_effect=control),patch.object(ui.time,'sleep'):
            result=ui.stop_activity_work(1)
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(calls[0],('broker','stop_activity'))
        self.assertEqual(calls[-2:], [('broker','stop_activity'),('broker','poll')])
        self.assertIn(('core','cancel'),calls)

    def test_incomplete_stop_does_not_report_success(self):
        with patch.object(ui,'request',return_value={'jobs':[{'id':2,'activity_id':1,'status':'running'}]}), \
             patch.object(ui,'broker_request',return_value={'jobs':[],'generation':1}) as control:
            with self.assertRaisesRegex(RuntimeError,'not finished stopping'):ui.stop_activity_work(1,timeout=0)
        control.assert_called_once_with('stop_activity',activity=1)

class BrokerLifecycle(unittest.TestCase):
    def test_inflight_assessment_and_queued_request_are_revoked_durably(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(broker,'STATE',Path(tmp)), \
             patch.object(broker,'workspace',return_value=tmp),patch.object(broker,'JOBS',{}),patch.object(broker,'start') as launch:
            entered=threading.Event();release=threading.Event();errors=[]
            def assess(*a,**kw):
                entered.set();self.assertTrue(release.wait(3))
                return SimpleNamespace(returncode=0,stdout=json.dumps({'status':'available','risk':'routine','confidence':1}))
            req=dict(op='execute',activity=1,argv=['/usr/bin/true'],purpose='Fixture',expected_generation=0)
            def execute():
                try:broker.handle(req,123)
                except ValueError as exc:errors.append(str(exc))
            with patch.object(broker.subprocess,'run',side_effect=assess):
                worker=threading.Thread(target=execute);worker.start()
                try:
                    self.assertTrue(entered.wait(3))
                    stopped=broker.handle({'op':'stop_activity','activity':1},123)
                    self.assertEqual(stopped['generation'],1)
                finally:release.set();worker.join(4)
            self.assertFalse(worker.is_alive());self.assertIn('during assessment',errors[0]);launch.assert_not_called()
            self.assertEqual(broker.activity_generation(1),1)
            with self.assertRaisesRegex(ValueError,'start a new request'):broker.handle(req,123)
            with patch.object(broker.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{}')):
                fresh=broker.handle({**req,'expected_generation':1,'request_confirmation':True},123)
            self.assertEqual(fresh['status'],'approval_required')
            broker.handle({'op':'stop_activity','activity':1},123)
            self.assertEqual(broker.JOBS[fresh['id']]['status'],'rejected')
            with self.assertRaisesRegex(ValueError,'not awaiting'):broker.handle({'op':'approve','job_id':fresh['id']},0)

    def test_all_active_jobs_remain_visible_beyond_recent_limit(self):
        rows={str(i):dict(id=str(i),activity=1,created_at=i,status='succeeded') for i in range(110)}
        rows['0']['status']='running';rows['1']['status']='approval_required'
        with patch.object(broker,'JOBS',rows):result=broker.handle({'op':'list'},123)
        self.assertEqual(len(result),102)
        self.assertIn('0',[j['id'] for j in result]);self.assertIn('1',[j['id'] for j in result])


class RequestProvenance(unittest.TestCase):
    def test_worker_captures_generation_before_queueing_and_passes_core_id(self):
        with patch.object(sys,'argv',['worker','ask','1','Fixture']), \
             patch.dict(worker.os.environ,{'AGENT_OS_JOB_ID':'42'}), \
             patch('broker_client.request',return_value={'generation':7}) as state, \
             patch.object(worker,'connect',return_value=MagicMock()) as connect, \
             patch.object(worker,'read_line',return_value={'done':True,'ok':True}):
            self.assertEqual(worker.main(),0)
        state.assert_called_once_with('activity_state',activity=1)
        self.assertEqual(connect.call_args.args[1],dict(op='ask',activity=1,prompt='Fixture',expected_generation=7,core_job_id=42))

    def test_revoked_queued_conversation_never_reaches_inference(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(assistant,'STATE',Path(tmp)), \
             patch.object(assistant,'config',return_value={}), \
             patch.object(assistant,'broker_request',return_value={'generation':1}), \
             patch.object(assistant,'Decisions') as decisions,patch.object(assistant,'run_agent') as run:
            with self.assertRaisesRegex(ValueError,'no longer active'):
                assistant.handle(dict(op='ask',activity=1,prompt='Queued fixture',expected_generation=0),None)
        decisions.assert_not_called();run.assert_not_called()
