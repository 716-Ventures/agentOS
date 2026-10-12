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
                if node.name==name and (role is None or node.getRole()==role):
                    found.append(node);return True
                queue.extend(node[index] for index in range(min(node.childCount,128)))
            except (RuntimeError,LookupError):pass
        return False
    wait(search,'Accessible control missing: '+name)
    return found[0]


def disclose(name):
    control=find(name,None)
    if not control.getState().contains(pyatspi.STATE_EXPANDED):activate(control)


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
    wait(lambda:ime_accessibility.rendered_status(marker),'Accessible editing fixture did not render the current revision')
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
    # The session owns this temporary view until teardown. Closing it here
    # would retile unrelated editors that can still hold active input.
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


def verify_reader_validation(call, speech_log):
    field=find('Accessible session draft',pyatspi.ROLE_TEXT)
    assert field.getState().contains(pyatspi.STATE_FOCUSED)
    before=call({'op':'presentation.get','document_id':'session-fixture'})
    original=before['elements']['field']['props'].copy()
    visible=text(field)
    draft=call({'op':'draft.get','surface_id':'session-fixture','element_id':'field'})
    message='Use a saved workspace name.'
    def apply(props):
        document=call({'op':'presentation.get','document_id':'session-fixture'})
        return call({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1',
                     'request_id':'reader-validation-'+str(time.monotonic_ns()),'expected_revisions':{'session-fixture':document['revision']},
                     'operations':[{'op':'element.set_props','surface_id':'session-fixture','element_id':'field','props':props}]})
    def speech_since(offset, expected):
        return any('SPEECH OUTPUT:' in line and expected in line for line in speech_log.read_text(errors='replace')[offset:].splitlines())
    baseline=len(speech_log.read_text(errors='replace'))
    assert apply({**original,'validation_message':message})['status']=='committed'
    wait(lambda:speech_since(baseline,message),'Orca did not send the focused field error message to speech')
    assert field.getState().contains(pyatspi.STATE_INVALID_ENTRY)
    assert text(field)==visible and call({'op':'draft.get','surface_id':'session-fixture','element_id':'field'})==draft
    baseline=len(speech_log.read_text(errors='replace'))
    assert apply(original)['status']=='committed'
    wait(lambda:speech_since(baseline,'Entry valid.'),'Orca did not announce cleared field validation')
    assert not field.getState().contains(pyatspi.STATE_INVALID_ENTRY)
    assert field.getState().contains(pyatspi.STATE_FOCUSED) and text(field)==visible
    assert call({'op':'presentation.get','document_id':'session-fixture'})['elements']['field']['props']==original
    assert call({'op':'draft.get','surface_id':'session-fixture','element_id':'field'})==draft
    print('PASS: session-owned Orca sends the focused field error and cleared-valid state to speech without changing input or drafts; physical audio and braille remain unqualified',flush=True)



def verify_reader_controls(call, speech_log):
    """Observe real Orca speech for the remaining native validation controls."""
    import ime_accessibility
    activity=call({'op':'presentation.get','document_id':'session-fixture'})['activity_id']
    surface='session-fixture'
    props={
        'editor':{'label':'Reader document draft','value':'Saved document'},
        'choice':{'label':'Reader workspace choice','options':['First','Second'],'value':'First'},
        'toggle':{'label':'Reader confirmation','value':False},
    }
    kinds={'editor':('DocumentEditor@1',pyatspi.ROLE_TEXT),'choice':('Choice@1',pyatspi.ROLE_COMBO_BOX),'toggle':('Toggle@1',pyatspi.ROLE_CHECK_BOX)}
    def current():return call({'op':'presentation.get','document_id':surface})
    def apply(operations,revision):
        return call({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'reader-controls-'+str(time.monotonic_ns()),'expected_revisions':{surface:revision},'operations':operations})
    frame=find('Agent view · Session lifecycle',pyatspi.ROLE_FRAME)
    def speech_since(offset,message):
        return any('SPEECH OUTPUT:' in line and message in line for line in speech_log.read_text(errors='replace')[offset:].splitlines())
    def focused(control):
        queue=deque([control]);visited=0
        while queue and visited<128:
            node=queue.popleft();visited+=1
            if node is None:continue
            if node.getState().contains(pyatspi.STATE_FOCUSED):return True
            queue.extend(node[i] for i in range(min(node.childCount,32)))
        return False
    activate(find('Agents',pyatspi.ROLE_PUSH_BUTTON))
    disclose('Desktop controls')
    activate(find('Keyboard',pyatspi.ROLE_PUSH_BUTTON))
    tab=find('Tab',pyatspi.ROLE_PUSH_BUTTON)
    control_modifier=False
    def focused_path():
        queue=deque([(frame,())]);visited=0
        while queue and visited<512:
            node,path=queue.popleft();visited+=1
            if node is None:continue
            if node.getState().contains(pyatspi.STATE_FOCUSED):return (path,node.name,node.getRole())
            queue.extend((node[i],path+(i,)) for i in range(min(node.childCount,64)))
        return None
    def navigate(control):
        nonlocal control_modifier
        for _ in range(32):
            if focused(control):return
            previous=focused_path()
            needs_control=previous is not None and previous[1]==props['editor']['label']
            if needs_control!=control_modifier:
                activate(find('Ctrl on' if control_modifier else 'Ctrl',pyatspi.ROLE_PUSH_BUTTON))
                control_modifier=needs_control
            activate(tab)
            wait(lambda:ime_accessibility.rendered_text('Keyboard ready'),'Trusted navigation stroke did not finish')
            try:wait(lambda:focused_path()!=previous,'Tab did not move native focus')
            except AssertionError:
                print('Reader navigation diagnostics: '+json.dumps({'before':previous,'after':focused_path(),'target':control.name,'control_modifier':control_modifier,'labels':accessible_labels()}),flush=True)
                raise
        raise AssertionError('Native keyboard navigation did not reach '+control.name)
    def scoped_discard(control):
        parent=control.parent
        for _ in range(12):
            if parent is None:break
            queue=deque([parent]);buttons=[];visited=0
            while queue and visited<512:
                node=queue.popleft();visited+=1
                if node is None:continue
                if node.name=='Discard draft' and node.getRole()==pyatspi.ROLE_PUSH_BUTTON:buttons.append(node)
                queue.extend(node[i] for i in range(min(node.childCount,64)))
            if len(buttons)==1:return buttons[0]
            if len(buttons)>1:break
            parent=parent.parent
        raise AssertionError('No unique Discard control in the same field group: '+control.name)
    for key,(kind,role) in kinds.items():
        name=props[key]['label']+(': First' if key=='choice' else '')
        control=find(name,role,root=frame)
        focus_baseline=len(speech_log.read_text(errors='replace'))
        navigate(control)
        wait(lambda:speech_since(focus_baseline,props[key]['label']),'Orca did not announce initial '+kind+' focus')
        if key=='editor':
            assert control.queryEditableText().setTextContents('Unsaved document λ 日本語')
            wait(lambda:call({'op':'draft.get','surface_id':surface,'element_id':key}).get('draft')=='Unsaved document λ 日本語','Reader editor draft did not reach core')
        elif key=='choice':
            assert not control_modifier
            activate(find('Space',pyatspi.ROLE_PUSH_BUTTON))
            wait(lambda:ime_accessibility.rendered_text('Keyboard ready'),'Choice open stroke did not finish')
            wait(lambda:control.getState().contains(pyatspi.STATE_EXPANDED),'Choice popup did not open')
            activate(find('Down',pyatspi.ROLE_PUSH_BUTTON))
            wait(lambda:ime_accessibility.rendered_text('Keyboard ready'),'Choice navigation stroke did not finish')
            activate(find('Enter',pyatspi.ROLE_PUSH_BUTTON))
            wait(lambda:call({'op':'draft.get','surface_id':surface,'element_id':key}).get('draft')=='Second','Keyboard Choice did not retain the pending option')
            wait(lambda:control.name==props[key]['label']+': Second' and not control.getState().contains(pyatspi.STATE_EXPANDED),'Selected Choice name/popup state did not reconcile')
        elif key=='toggle':
            activate(control)
            wait(lambda:call({'op':'draft.get','surface_id':surface,'element_id':key}).get('draft')=='true','Reader toggle draft did not reach core')
        before=call({'op':'draft.get','surface_id':surface,'element_id':key})
        visible=text(control) if key=='editor' else control.name if key=='choice' else control.getState().contains(pyatspi.STATE_CHECKED)
        message={'editor':'Review this document before saving.','choice':'Choose an available workspace.','toggle':'Confirm this requirement before continuing.'}[key]
        baseline=len(speech_log.read_text(errors='replace'))
        assert apply([{'op':'element.set_props','surface_id':surface,'element_id':key,'props':{**props[key],'validation_message':message}}],current()['revision'])['status']=='committed'
        wait(lambda:speech_since(baseline,message),'Orca did not speak '+kind+' validation')
        assert control.getState().contains(pyatspi.STATE_INVALID_ENTRY)
        assert call({'op':'draft.get','surface_id':surface,'element_id':key})==before
        baseline=len(speech_log.read_text(errors='replace'))
        assert apply([{'op':'element.set_props','surface_id':surface,'element_id':key,'props':props[key]}],current()['revision'])['status']=='committed'
        wait(lambda:speech_since(baseline,'Entry valid.'),'Orca did not speak cleared '+kind+' validation')
        assert not control.getState().contains(pyatspi.STATE_INVALID_ENTRY) and focused(control)
        after=text(control) if key=='editor' else control.name if key=='choice' else control.getState().contains(pyatspi.STATE_CHECKED)
        assert after==visible and call({'op':'draft.get','surface_id':surface,'element_id':key})==before
        assert current()['elements'][key]['props']==props[key]
        if before.get('draft') is not None:
            activate(scoped_discard(control))
            wait(lambda:call({'op':'draft.get','surface_id':surface,'element_id':key}).get('draft') is None,'Reader fixture draft did not explicitly discard')
            def restored():
                if key=='editor':return text(control)==props[key]['value']
                if key=='choice':return control.name==props[key]['label']+': '+props[key]['value']
                return not control.getState().contains(pyatspi.STATE_CHECKED)
            wait(restored,'Explicit reader Discard did not restore the visible saved value')
        print('PASS: real Orca error/clear speech retains '+kind+' focus, value and exact draft without Save',flush=True)
    navigate(find('Accessible session draft',pyatspi.ROLE_TEXT))
    if control_modifier:activate(find('Ctrl on',pyatspi.ROLE_PUSH_BUTTON))
    activate(find('Hide keyboard',pyatspi.ROLE_PUSH_BUTTON))

def verify_reader_outcomes(call, speech_log, outcomes, database):
    """Real job transitions must remain perceivable beside a selected snapshot."""
    import ime_accessibility
    frame=find('Agent view · Session lifecycle',pyatspi.ROLE_FRAME)
    field=find('Accessible session draft',pyatspi.ROLE_TEXT,root=frame)
    draft=call({'op':'draft.get','surface_id':'session-fixture','element_id':'field'})
    activate(find('Agents',pyatspi.ROLE_PUSH_BUTTON))
    disclose('Desktop controls')
    activate(find('Keyboard',pyatspi.ROLE_PUSH_BUTTON))
    def stroke(name):
        activate(find(name,pyatspi.ROLE_PUSH_BUTTON))
        wait(lambda:ime_accessibility.rendered_text('Keyboard ready'),'Reader outcome keyboard stroke did not finish')
    def focused_path():
        queue=deque([(frame,())]);visited=0
        while queue and visited<512:
            node,path=queue.popleft();visited+=1
            if node is None:continue
            if node.getState().contains(pyatspi.STATE_FOCUSED):return (path,node.name,node.getRole())
            queue.extend((node[i],path+(i,)) for i in range(min(node.childCount,64)))
        return None
    def navigate(target):
        for _ in range(32):
            if target.getState().contains(pyatspi.STATE_FOCUSED):return
            previous=focused_path()
            editor_focused=previous is not None and previous[1]=='Reader document draft'
            if editor_focused:stroke('Ctrl')
            stroke('Tab')
            wait(lambda:focused_path()!=previous,'Reader outcome Tab did not acknowledge changed focus')
            if editor_focused:stroke('Ctrl on')
        raise AssertionError('Reader outcome keyboard did not reach '+target.name)
    for key,(job,latch) in outcomes.items():
        label='Reader '+key+' outcome'
        if key=='status':
            message=find('running',pyatspi.ROLE_LABEL,root=frame)
            group=message.parent
        else:
            heading=find(label,pyatspi.ROLE_HEADING,root=frame)
            group=heading.parent
            message=find('running',pyatspi.ROLE_LABEL,root=group)
        value=message.queryText()
        navigate(message)
        stroke('Ctrl');stroke('a');stroke('Ctrl on')
        wait(lambda:value.getNSelections()==1,'Reader outcome keyboard did not select the snapshot')
        # Observe the real host's lease independently of the accessibility tree.
        import sqlite3
        def leased():
            with sqlite3.connect(database) as db:
                row=db.execute("SELECT expires,session FROM presentation_leases WHERE document=? AND element=?",('session-fixture',key)).fetchone()
            return row is not None and row[0]>=int(time.time()) and ':' in row[1]
        wait(leased,'Selected reading text did not acquire the host focus lease')
        assert value.getText(*value.getSelection(0))=='running'
        baseline=len(speech_log.read_text(errors='replace'))
        latch.touch()
        wait(lambda:next(row for row in call({'op':'snapshot'})['jobs'] if row['id']==job)['status']=='failed','Reader outcome job did not fail')
        expected='Current value:\n'+('' if key=='status' else label+'\n')+'failed'
        observed=[]
        def current_notice():
            queue=deque([group]);observed.clear()
            while queue and len(observed)<128:
                node=queue.popleft()
                if node is None:continue
                try:content=text(node)
                except (RuntimeError,NotImplementedError):content=None
                observed.append({'name':node.name,'role':node.getRoleName(),'text':content})
                if content==expected:
                    print('Reader current notice: '+json.dumps(observed[-1]),flush=True)
                    return node
                queue.extend(node[i] for i in range(min(node.childCount,32)))
            return False
        try:wait(current_notice,'Selected outcome did not expose its exact current notice')
        except AssertionError:
            print('Reader outcome diagnostics: '+json.dumps({'accessible':observed,'binding':call({'op':'binding.snapshot','surface_id':'session-fixture'}),'selected':value.getNSelections(),'message':text(message)}),flush=True)
            raise
        assert text(message)=='running' and value.getNSelections()==1
        assert message.getState().contains(pyatspi.STATE_FOCUSED)
        assert leased(),'Job observation displaced the human focus lease'
        assert value.getText(*value.getSelection(0))=='running'
        assert call({'op':'draft.get','surface_id':'session-fixture','element_id':'field'})==draft
        announcement='failed' if key=='status' else label+': failed'
        def announcements():
            # Orca also reads changed label text in response to the user's Right
            # key. Count actual speech inside announcement event dispatch, not
            # that ordinary caret/name reading. Preserve the complete raw trace.
            active=False;spoken=[]
            for line in speech_log.read_text(errors='replace')[baseline:].splitlines():
                if 'START ' in line and 'OBJECT EVENT ' in line:
                    active='OBJECT:ANNOUNCEMENT' in line
                if active and ('SPEECH OUTPUT: '+repr(announcement)+'{') in line:
                    spoken.append(line)
                if ('END ' in line or 'FINISHED ' in line) and 'OBJECT EVENT ' in line:active=False
            return spoken
        wait(lambda:announcements(),'Orca did not announce changed selected '+key+' outcome')
        if key=='status':
            assert "SPEECH OUTPUT: 'core · failed" not in speech_log.read_text(errors='replace')[baseline:], 'Inactive monitor work rows competed with the selected Status announcement'
            stroke('Ctrl');stroke('c');stroke('Ctrl on')
        stroke('Right')
        wait(lambda:text(message)=='failed','Reader outcome did not reconcile after deselection')
        time.sleep(.8) # Observe several normal reconciliation polls after deselection.
        assert len(announcements())==1,'Unchanged outcome refresh or deselection repeated speech'
        print('PASS: actual Orca announces changed '+key+' job outcome once while selected snapshot, focus and exact field draft persist',flush=True)
        if key=='status':
            copied=find('Status copy check',pyatspi.ROLE_TEXT,root=frame)
            navigate(copied)
            stroke('Ctrl');stroke('v');stroke('Ctrl on')
            wait(lambda:text(copied)=='running','Ctrl+C did not preserve the selected old status in the Wayland clipboard')
            assert call({'op':'draft.get','surface_id':'session-fixture','element_id':'field'})==draft
            print('PASS: trusted Ctrl+C copies the selected old Status through the Wayland clipboard after its live job has failed',flush=True)
    navigate(field)
    activate(find('Hide keyboard',pyatspi.ROLE_PUSH_BUTTON))


def verify_local_form(call, database):
    import accessibility as a
    import pyatspi,json,time,sqlite3,ime_accessibility
    activity=call({'op':'presentation.get','document_id':'session-fixture'})['activity_id']
    content='Local callback output λ 日本語'
    job=call({'op':'run','activity_id':int(activity),'argv':['/bin/echo',content]})['id']
    a.wait(lambda:next(j for j in call({'op':'snapshot'})['jobs'] if j['id']==job)['status']=='succeeded','Local callback job did not finish')
    actions=call({'op':'action.ensure','activity_id':int(activity),'job_ids':[job]})['actions']
    reference=next(action['reference'] for action in actions if action['operation']=='job.read_output')
    surface='local-callback-form'
    document={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':surface,'activity_id':activity,'revision':0,'title':'Local callback form','root':'root','elements':{'root':{'type':'Stack@1','slots':{'children':['offset','read']}},'offset':{'type':'TextField@1','props':{'label':'Local byte offset','value':'0'},'events':{'submit':{'action':'read'}}},'read':{'type':'Button@1','props':{'label':'Read local callback output'},'events':{'activate':{'action':'read'}}}},'bindings':{},'actions':{'read':{'ref':reference,'parameters':{'offset':{'kind':'field','element_id':'offset'}}}}}
    assert call({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'local-form-create','expected_revisions':{surface:None},'operations':[{'op':'surface.create','document':document}]})['status']=='committed'
    frame=a.find('Agent view · Local callback form',pyatspi.ROLE_FRAME)
    field=a.find('Local byte offset',pyatspi.ROLE_TEXT,root=frame)
    button=a.find('Read local callback output',pyatspi.ROLE_PUSH_BUTTON,root=frame)
    a.wait(lambda:button.getState().contains(pyatspi.STATE_SENSITIVE),'Local form action unavailable')
    def receipts():
        with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as db:
            return [(request,json.loads(receipt)) for request,receipt in db.execute('SELECT request,receipt FROM presentation_action_invocations WHERE reference=?',(reference,))]
    def draft():return call({'op':'draft.get','surface_id':surface,'element_id':'offset'}).get('draft')
    def saved():return call({'op':'presentation.get','document_id':surface})['elements']['offset']['props']['value']
    def related(message):
        return any(relation.getRelationType()==a.ERROR_RELATION and any(a.text(relation.getTarget(index))==message for index in range(relation.getNTargets())) for relation in field.getRelationSet())
    initial=receipts()
    for invalid,message in [('日本語 $(id)','offset: enter a nonnegative whole number'),('18446744073709551615','offset: enter a whole number from 0 to 1048576')]:
        assert field.queryEditableText().setTextContents(invalid)
        a.wait(lambda:draft()==invalid,'Invalid local field was not retained')
        a.activate(button)
        a.wait(lambda:related(message),'Local callback error was not related to its exact field')
        assert field.getState().contains(pyatspi.STATE_INVALID_ENTRY)
        assert a.text(field)==invalid and draft()==invalid and saved()=='0'
        assert receipts()==initial,'Invalid local parameter dispatched an action'
        assert field.queryEditableText().setTextContents(' 0 ')
        a.wait(lambda:not field.getState().contains(pyatspi.STATE_INVALID_ENTRY),'Editing did not clear the local callback error')
        assert not any(relation.getRelationType()==a.ERROR_RELATION for relation in field.getRelationSet())
    a.wait(lambda:draft()==' 0 ','Corrected form draft was not retained')
    a.activate(button)
    a.wait(lambda:len(receipts())==len(initial)+1,'Corrected local form did not dispatch exactly once')
    # Acceptance is durable before execution finishes; observe the same receipt,
    # never replay the action or mistake an accepted job snapshot for its output.
    a.wait(lambda:receipts()[-1][1]['status'] not in ('accepted','running'),'Corrected callback did not finish')
    assert len(receipts())==len(initial)+1,'Corrected callback dispatched more than once'
    result=receipts()[-1][1]
    assert result['status']=='succeeded' and result['observed_target']['text']==content+'\n',result
    a.activate(a.find('Agents',pyatspi.ROLE_PUSH_BUTTON))
    a.wait(lambda:ime_accessibility.rendered_text(content+'\n'),'Corrected callback output was not displayed')
    assert saved()=='0' and draft()==' 0 ' and a.text(field)==' 0 ','Callback implicitly saved or replaced the local form draft'
    assert call({'op':'presentation.get','document_id':surface})['revision']==0
    print('PASS: local callback parse/range errors relate to the exact retained field, never dispatch or Save, clear on edit and retry once with registered typed values',flush=True)
