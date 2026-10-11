"""Independent AT-SPI journey through the running desktop and real core."""
from collections import deque
import json
import time
import pyatspi
import gi
gi.require_version('Gtk','4.0')
from gi.repository import Gtk
ERROR_RELATION = pyatspi.RELATION_DESCRIBED_BY if Gtk.get_major_version()==4 and Gtk.get_minor_version()<16 else pyatspi.RELATION_ERROR_MESSAGE


def wait(predicate,description):
    end=time.monotonic()+10
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.05)
    raise AssertionError(description)


def find(name,role,root=None):
    found=[]
    def search():
        queue=deque([root if root is not None else pyatspi.Registry.getDesktop(0)])
        visited=0
        while queue and visited<4096:
            node=queue.popleft();visited+=1
            if node is None:continue # AT-SPI can expose an absent child during widget teardown.
            try:
                if node.name==name and node.getRole()==role:
                    found.append(node);return True
                queue.extend(node[index] for index in range(min(node.childCount,128)))
            except (RuntimeError,LookupError):pass
        return False
    wait(search,'Accessible control missing: '+name)
    return found[0]


def text(node):
    value=node.queryText()
    return value.getText(0,value.characterCount)


def activate(node):
    states=node.getState()
    assert not states.contains(pyatspi.STATE_DEFUNCT),'Accessible action refers to a destroyed control'
    # GTK 4.14 maps disabled=false to SENSITIVE, not ENABLED:
    # https://github.com/GNOME/gtk/blob/4.14.5/gtk/a11y/gtkatspicontext.c
    assert states.contains(pyatspi.STATE_SENSITIVE)
    action=node.queryAction();assert action.nActions>0
    assert action.doAction(0)


def draft_action(call,label):
    document=call({'op':'presentation.get','document_id':'session-fixture'})
    frame=find('Agent view · '+document['title'],pyatspi.ROLE_FRAME)
    activate(find(label,pyatspi.ROLE_PUSH_BUTTON,root=frame))


def accessible_labels():
    queue=deque([pyatspi.Registry.getDesktop(0)]);labels=[];visited=0
    while queue and visited<256 and len(labels)<64:
        node=queue.popleft();visited+=1
        if node is None:continue
        try:
            if node.name:labels.append({'role':node.getRoleName(),'name':node.name[:512]})
            queue.extend(node[index] for index in range(min(node.childCount,64)))
        except (RuntimeError,LookupError):pass
    return labels


def verify(call):
    # A preceding journey can commit in core before GTK has reconciled the
    # receipt. Observe a fresh status in this same surface before beginning
    # another Save against the renderer's displayed revision.
    import ime_accessibility
    document=call({'op':'presentation.get','document_id':'session-fixture'})
    marker='Accessible editing ready '+str(time.monotonic_ns())
    receipt=call({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1',
                  'request_id':'accessible-render-barrier-'+str(time.monotonic_ns()),
                  'expected_revisions':{'session-fixture':document['revision']},
                  'operations':[{'op':'element.set_props','surface_id':'session-fixture','element_id':'reading','props':{'value':marker}}]})
    assert receipt['status']=='committed',receipt
    wait(lambda:ime_accessibility.rendered_text(marker),'Accessible editing fixture did not render the current revision')
    field=find('Accessible session draft',pyatspi.ROLE_TEXT)
    assert text(field)=='Original accessible value'
    def saved():
        return call({'op':'presentation.snapshot'})['documents']['session-fixture']['elements']['field']['props']['value']
    def draft():
        return call({'op':'draft.get','surface_id':'session-fixture','element_id':'field'}).get('draft')
    value='AT-SPI saved λ 日本語'
    assert field.queryEditableText().setTextContents(value)
    wait(lambda:draft()==value,'Accessible edit was not retained by core')
    assert saved()=='Original accessible value','Editing committed without deliberate save'
    draft_action(call,'Save draft')
    try:
        wait(lambda:saved()==value,'Accessible Save did not commit the exact Unicode draft')
    except AssertionError:
        queue=deque([pyatspi.Registry.getDesktop(0)]);labels=[];visited=0
        while queue and visited<256 and len(labels)<64:
            node=queue.popleft();visited+=1
            if node is None:continue
            try:
                if node.name:labels.append({'role':node.getRoleName(),'name':node.name[:512]})
                queue.extend(node[index] for index in range(min(node.childCount,64)))
            except (RuntimeError,LookupError):pass
        print('Accessible Save diagnostics: '+json.dumps({'document':call({'op':'presentation.get','document_id':'session-fixture'}),'draft':call({'op':'draft.get','surface_id':'session-fixture','element_id':'field'}),'visible':text(field),'accessible_labels':labels}),flush=True)
        raise
    assert field.queryEditableText().setTextContents('Discard this accessible edit')
    wait(lambda:draft()=='Discard this accessible edit','Second edit was not retained')
    draft_action(call,'Discard draft')
    observed={}
    def discarded():
        observed.update(draft=call({'op':'draft.get','surface_id':'session-fixture','element_id':'field'}),saved=saved(),visible=text(field))
        return observed['draft'].get('draft') is None and observed['visible']==value
    try:
        wait(discarded,'Accessible Discard did not restore committed text')
    except AssertionError:
        queue=deque([pyatspi.Registry.getDesktop(0)]);labels=[];visited=0
        while queue and visited<256 and len(labels)<64:
            node=queue.popleft();visited+=1
            if node is None:continue
            try:
                if node.name:labels.append({'role':node.getRoleName(),'name':node.name[:512]})
                queue.extend(node[index] for index in range(min(node.childCount,64)))
            except (RuntimeError,LookupError):pass
        print('Accessible Discard diagnostics: '+json.dumps({**observed,'accessible_labels':labels}),flush=True)
        raise
    assert saved()==value
    print('PASS: independent AT-SPI desktop Unicode editing, deliberate save, discard and real core state')


def verify_button(call):
    # Use a separate view: focused editors deliberately defer composition.
    activity=call({'op':'presentation.get','document_id':'session-fixture'})['activity_id']
    document={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':'button-session-fixture','activity_id':activity,'revision':0,'title':'Styled button fixture','root':'styled-button','elements':{'styled-button':{'type':'Button@1','props':{'label':'Accessible styled action λ','variant':'outline','size':'xs','icon':'plus'}}},'bindings':{},'actions':{}}
    assert call({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'styled-button-create','expected_revisions':{'button-session-fixture':None},'operations':[{'op':'surface.create','document':document}]})['status']=='committed'
    button=find('Accessible styled action λ',pyatspi.ROLE_PUSH_BUTTON)
    assert not button.getState().contains(pyatspi.STATE_SENSITIVE),'Missing host action enabled a styled button'
    before=call({'op':'presentation.get','document_id':'button-session-fixture'})
    request={'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1',
             'request_id':'styled-button-change','expected_revisions':{'button-session-fixture':before['revision']},
             'operations':[{'op':'element.set_props','surface_id':'button-session-fixture','element_id':'styled-button',
                            'props':{'label':'Next styled action 日本語','variant':'secondary','size':'lg','icon':'arrow-right','icon_position':'only'}}]}
    assert call(request)['status']=='committed'
    renamed=find('Next styled action 日本語',pyatspi.ROLE_PUSH_BUTTON)
    assert not renamed.getState().contains(pyatspi.STATE_SENSITIVE)
    assert renamed.queryAction().nActions>0
    current=call({'op':'presentation.get','document_id':'button-session-fixture'})
    request['request_id']='styled-button-reject';request['expected_revisions']['button-session-fixture']=current['revision']
    request['operations'][0]['props']={'label':'Invalid unnamed icon','icon_position':'only'}
    try:call(request)
    except (AssertionError,RuntimeError) as error:
        assert 'Invalid button declaration' in str(error),error
    else:raise AssertionError('Core accepted an icon position without an icon')
    assert call({'op':'presentation.get','document_id':'button-session-fixture'})==current
    assert find('Next styled action 日本語',pyatspi.ROLE_PUSH_BUTTON).queryAction().nActions>0
    print('PASS: independent AT-SPI names survive typed button style/icon updates; unavailable actions stay disabled and invalid declarations preserve the revision')


def verify_validation(call):
    field=find('Accessible session draft',pyatspi.ROLE_TEXT)
    value='Validation draft λ 日本語'
    assert field.queryEditableText().setTextContents(value)
    def draft():return call({'op':'draft.get','surface_id':'session-fixture','element_id':'field'}).get('draft')
    wait(lambda:draft()==value,'Validation draft did not reach core')
    def document():return call({'op':'presentation.get','document_id':'session-fixture'})
    def apply(props):
        return call({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1',
                     'request_id':'validation-'+str(time.monotonic_ns()),'expected_revisions':{'session-fixture':document()['revision']},
                     'operations':[{'op':'element.set_props','surface_id':'session-fixture','element_id':'field','props':props}]})
    props=document()['elements']['field']['props'].copy()
    message='Choose <b>literal 日本語</b> λ'
    assert apply({**props,'validation_message':message})['status']=='committed'
    wait(lambda:field.getState().contains(pyatspi.STATE_INVALID_ENTRY),'Missing accessible invalid state')
    def related_error():
        relations=[r for r in field.getRelationSet() if r.getRelationType()==ERROR_RELATION]
        return len(relations)==1 and relations[0].getNTargets()==1 and text(relations[0].getTarget(0))==message
    wait(related_error,'Missing exact accessible validation message')
    assert text(field)==value and draft()==value
    saved=document();assert saved['elements']['field']['props']['value']=='Original accessible value'
    for invalid in ('','λ'*513):
        try:apply({**props,'validation_message':invalid})
        except (AssertionError,RuntimeError) as error:assert 'Invalid validation message' in str(error),error
        else:raise AssertionError('Core accepted invalid feedback')
        assert document()==saved and draft()==value and text(field)==value
    assert apply(props)['status']=='committed'
    wait(lambda:not field.getState().contains(pyatspi.STATE_INVALID_ENTRY),'Accessible invalid state did not clear')
    wait(lambda:not any(r.getRelationType()==ERROR_RELATION for r in field.getRelationSet()),'Accessible error relation did not clear')
    assert draft()==value and text(field)==value
    draft_action(call,'Discard draft')
    observed={}
    def discarded():
        observed.update(draft=call({'op':'draft.get','surface_id':'session-fixture','element_id':'field'}),visible=text(field))
        return observed['draft'].get('draft') is None and observed['visible']==props['value']
    try:wait(discarded,'Explicit Discard did not restore the validation draft')
    except AssertionError:
        print('Validation Discard diagnostics: '+json.dumps({**observed,'document':document(),'accessible_labels':accessible_labels()}),flush=True)
        raise
    print('PASS: independent AT-SPI inline validation exposes literal error relation, preserves durable Unicode draft, rejects invalid transactions and clears without implicit Save')


def verify_toggle_validation(call):
    ident='toggle-validation-session-fixture'
    activity=call({'op':'presentation.get','document_id':'session-fixture'})['activity_id']
    props={'label':'Accessible validation toggle','value':False}
    document={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':ident,'activity_id':activity,'revision':0,'title':'Toggle validation fixture','root':'toggle','elements':{'toggle':{'type':'Toggle@1','props':props}},'actions':{},'bindings':{}}
    def current():return call({'op':'presentation.get','document_id':ident})
    def apply(operations,revision,expected=None):
        return call({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'toggle-validation-'+str(time.monotonic_ns()),'expected_revisions':expected if expected is not None else {ident:revision},'operations':operations})
    assert apply([{'op':'surface.create','document':document}],None)['status']=='committed'
    control=find(props['label'],pyatspi.ROLE_CHECK_BOX)
    assert not control.getState().contains(pyatspi.STATE_CHECKED)
    activate(control)
    def draft():return call({'op':'draft.get','surface_id':ident,'element_id':'toggle'}).get('draft')
    wait(lambda:draft()=='true','Accessible toggle did not retain a boolean draft')
    message='Confirm this form requirement λ'
    assert apply([{'op':'element.set_props','surface_id':ident,'element_id':'toggle','props':{**props,'validation_message':message}}],current()['revision'])['status']=='committed'
    wait(lambda:control.getState().contains(pyatspi.STATE_INVALID_ENTRY),'Toggle invalid state is missing')
    def related():
        relations=[r for r in control.getRelationSet() if r.getRelationType()==ERROR_RELATION]
        return len(relations)==1 and relations[0].getNTargets()==1 and text(relations[0].getTarget(0))==message
    wait(related,'Toggle readable error is missing')
    assert control.getState().contains(pyatspi.STATE_CHECKED) and draft()=='true'
    assert current()['elements']['toggle']['props']['value'] is False
    assert apply([{'op':'element.set_props','surface_id':ident,'element_id':'toggle','props':props}],current()['revision'])['status']=='committed'
    wait(lambda:not control.getState().contains(pyatspi.STATE_INVALID_ENTRY),'Toggle invalid state did not clear')
    wait(lambda:not any(r.getRelationType()==ERROR_RELATION for r in control.getRelationSet()),'Toggle error relation did not clear')
    assert control.getState().contains(pyatspi.STATE_CHECKED) and draft()=='true'
    frame=find('Agent view · Toggle validation fixture',pyatspi.ROLE_FRAME)
    activate(find('Discard draft',pyatspi.ROLE_PUSH_BUTTON,root=frame))
    wait(lambda:draft() is None and not control.getState().contains(pyatspi.STATE_CHECKED),'Explicit Discard did not restore the saved toggle')
    assert current()['elements']['toggle']['props']['value'] is False
    # The compositor has placed this view. Remove its workspace reference and
    # document in one revision-guarded transaction, as the native Close path does.
    expected={ident:current()['revision']};operations=[]
    def contains(value):
        if isinstance(value,dict):return value.get('surface_id')==ident or any(contains(v) for v in value.values())
        return isinstance(value,list) and any(contains(v) for v in value)
    for workspace in call({'op':'presentation.snapshot'})['documents'].values():
        if 'workspace_id' in workspace and contains(workspace['outputs']):
            expected[workspace['workspace_id']]=workspace['revision']
            operations.append({'op':'workspace.edit','workspace_id':workspace['workspace_id'],'edit':{'kind':'remove','surface_id':ident}})
    operations.append({'op':'surface.close','surface_id':ident})
    assert apply(operations,expected[ident],expected)['status']=='committed'
    print('PASS: independent AT-SPI toggle activation reaches the real durable draft; feedback and clearing retain the boolean without Save; scoped Discard restores committed state')


def verify_choice_name(call):
    ident='choice-name-probe';label='Available workspace'
    activity=call({'op':'presentation.get','document_id':'session-fixture'})['activity_id']
    props={'label':label,'options':['First','Second'],'value':'First','validation_message':'Initial choice error'}
    document={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':ident,'activity_id':activity,'revision':0,'title':'Choice name fixture','root':'choice','elements':{'choice':{'type':'Choice@1','props':props}},'actions':{},'bindings':{}}
    def apply(operations,revision):
        return call({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'choice-name-'+str(time.monotonic_ns()),'expected_revisions':{ident:revision},'operations':operations})
    assert apply([{'op':'surface.create','document':document}],None)['status']=='committed'
    frame=find('Agent view · Choice name fixture',pyatspi.ROLE_FRAME)
    controls=[]
    def found():
        queue=deque([frame])
        while queue:
            node=queue.popleft()
            if node is None:continue
            if node.getRole()==pyatspi.ROLE_COMBO_BOX:controls.append(node);return True
            queue.extend(node[index] for index in range(min(node.childCount,128)))
        return False
    wait(found,'Choice control missing from its own frame')
    control=controls[0]
    for index in range(3):
        message='Reconciled choice error '+str(index)
        current=call({'op':'presentation.get','document_id':ident})
        assert apply([{'op':'element.set_props','surface_id':ident,'element_id':'choice','props':{**props,'validation_message':message}}],current['revision'])['status']=='committed'
        def related():
            relations=[r for r in control.getRelationSet() if r.getRelationType()==ERROR_RELATION]
            if len(relations)!=1 or relations[0].getNTargets()!=1:return False
            target=relations[0].getTarget(0)
            return target is not None and text(target)==message
        wait(related,'Choice did not reconcile its exact related error')
        observed={'name':control.name,'expected':label+': First','iteration':index,'committed':call({'op':'presentation.get','document_id':ident})['elements']['choice']['props']['value']}
        print('Choice naming observation: '+json.dumps(observed),flush=True)
        assert control.name==label+': First','Retained Choice reconciliation replaced its field-plus-option accessible name'
        assert observed['committed']=='First'
    print('PASS: independent agentOS Choice retains its field-plus-option name across three rendered feedback revisions',flush=True)
