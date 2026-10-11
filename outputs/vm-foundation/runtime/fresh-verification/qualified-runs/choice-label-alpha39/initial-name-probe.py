"""Qualification-only independent check of retained Choice naming in agentOS."""
import sys,runpy,json,time
from collections import deque
sys.path.insert(0,'native-shell/tests')
import accessibility,pyatspi
original=accessibility.verify_toggle_validation

def probe(call):
    original(call)
    ident='choice-name-probe';label='Available workspace'
    activity=call({'op':'presentation.get','document_id':'session-fixture'})['activity_id']
    props={'label':label,'options':['First','Second'],'value':'First','validation_message':'Initial choice error'}
    document={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':ident,'activity_id':activity,'revision':0,'title':'Choice name fixture','root':'choice','elements':{'choice':{'type':'Choice@1','props':props}},'actions':{},'bindings':{}}
    def apply(operations,revision):
        return call({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'choice-name-'+str(time.monotonic_ns()),'expected_revisions':{ident:revision},'operations':operations})
    assert apply([{'op':'surface.create','document':document}],None)['status']=='committed'
    frame=accessibility.find('Agent view · Choice name fixture',pyatspi.ROLE_FRAME)
    controls=[]
    def found():
        queue=deque([frame])
        while queue:
            node=queue.popleft()
            if node is None:continue
            if node.getRole()==pyatspi.ROLE_COMBO_BOX:controls.append(node);return True
            queue.extend(node[index] for index in range(min(node.childCount,128)))
        return False
    accessibility.wait(found,'Choice control missing from its own frame')
    control=controls[0]
    for index in range(3):
        message='Reconciled choice error '+str(index)
        current=call({'op':'presentation.get','document_id':ident})
        assert apply([{'op':'element.set_props','surface_id':ident,'element_id':'choice','props':{**props,'validation_message':message}}],current['revision'])['status']=='committed'
        def related():
            relations=[r for r in control.getRelationSet() if r.getRelationType()==accessibility.ERROR_RELATION]
            if len(relations)!=1 or relations[0].getNTargets()!=1:return False
            target=relations[0].getTarget(0)
            return target is not None and accessibility.text(target)==message
        accessibility.wait(related,'Choice did not reconcile its exact related error')
        observed={'name':control.name,'expected':label+': First','iteration':index,'committed':call({'op':'presentation.get','document_id':ident})['elements']['choice']['props']['value']}
        print('Choice naming observation: '+json.dumps(observed),flush=True)
        assert control.name==label+': First','Retained Choice reconciliation replaced its field-plus-option accessible name'
        assert observed['committed']=='First'
    print('PASS: independent agentOS Choice retains its field-plus-option name across three rendered feedback revisions',flush=True)

accessibility.verify_toggle_validation=probe
sys.argv=['native-shell/tests/native_session.py']
runpy.run_path(sys.argv[0],run_name='__main__')
