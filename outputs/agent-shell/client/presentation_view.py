"""Terminal projection of the shared inert presentation and callback contracts."""
import json
import os
from pathlib import Path
import re
import tempfile
import textwrap
import threading
import time
import unicodedata


def clean(value):
    text=re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)','',str(value))
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)
    return ''.join(c for c in text if c in '\n\t' or not unicodedata.category(c).startswith('C'))


def text_value(value,bindings):
    if isinstance(value,dict) and set(value)=={'binding'}:
        binding=bindings.get(value['binding'],{})
        if binding.get('availability')!='available':return 'Unavailable'
        value=binding.get('value')
    if value is None:return 'Unavailable'
    return value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)


def project(document,bindings=None,width=80):
    """Stable control IDs survive updates; no text is interpreted as executable input."""
    bindings=bindings or {};lines=[];controls={};elements=document.get('elements',{})
    def walk(key,depth=0):
        if depth>32:raise ValueError('View tree is too deep')
        node=elements[key];props=node.get('props',{});kind=node['type']
        if kind in ('Stack@1','Row@1'):
            for child in node.get('slots',{}).get('children',[]):walk(child,depth+1)
            return
        if kind in ('Text@1','Status@1'):text=text_value(props.get('text' if kind=='Text@1' else 'value'),bindings)
        elif kind=='Progress@1':
            value=props.get('value');value=text_value(value,bindings)
            try:amount=float(value);progress=f'{amount*100:.0f}%' if 0<=amount<=1 else 'Unavailable'
            except (ValueError,TypeError):progress='Unavailable'
            text=f"{props.get('label','Work')}: {progress}"
        elif kind=='TextField@1':text=f"[{key}] {props.get('label','Text')}: {props.get('value','')}";controls[key]=node
        elif kind=='Button@1':
            text=f"[{key}] {props.get('label','Action')}"+(' (disabled)' if props.get('disabled') else '')
            if not props.get('disabled'):controls[key]=node
        elif kind=='Link@1':text=f"[{key}] {props.get('label','Link')} — {props.get('url','')}";controls[key]=node
        else:text=f'Unsupported control: {kind}'
        for line in clean(text).splitlines() or ['']:lines.extend(textwrap.wrap(line,max(20,width),replace_whitespace=False) or [''])
    walk(document['root']);return lines,controls


def parameters(action,metadata,fields):
    result={};schema=metadata.get('parameter_schema',{})
    for key,definition in action.get('parameters',{}).items():
        rule=schema.get(key,{})
        if rule.get('type')!='integer':raise ValueError('Unsupported callback parameter: '+key)
        if definition.get('kind')=='literal':value=definition.get('value')
        elif definition.get('kind')=='field':
            text=fields(definition['element_id']).strip()
            if not re.fullmatch(r'[0-9]+',text):raise ValueError(key+': enter a nonnegative whole number')
            value=int(text)
        else:raise ValueError('Unknown callback parameter definition')
        if type(value) is not int or not rule['minimum']<=value<=rule['maximum']:raise ValueError(key+': outside its supported range')
        result[key]=value
    return result


def invoke(request,document,element,key=None):
    node=document['elements'][element];event='submit' if node['type']=='TextField@1' else 'activate'
    action_id=node.get('events',{}).get(event,{}).get('action')
    if not action_id:raise ValueError('This control has no registered action')
    action=document['actions'][action_id];metadata=request('action.metadata',reference=action['ref'])
    def field(ident):
        node=document['elements'].get(ident,{})
        if node.get('type')!='TextField@1':raise ValueError('Callback field is unavailable')
        draft=request('draft.get',surface_id=document['surface_id'],element_id=ident)
        return draft.get('draft') if draft.get('draft') is not None else node.get('props',{}).get('value','')
    values=parameters(action,metadata,field)
    ident=key or f'terminal-{os.getpid()}-{time.time_ns()}'
    try:return request('action.invoke',reference=action['ref'],request_id=ident,expected_source_revision=metadata['source_revision'],surface_id=document['surface_id'],expected_surface_revision=document['revision'],action_id=action_id,parameters=values)
    except (OSError,RuntimeError) as original:
        # A response may have been lost after acceptance. Never replay an effect.
        try:return request('action.status',request_id=ident)
        except (OSError,RuntimeError):raise original


class Lease:
    def __init__(self,request,surface,element):self.request=request;self.surface=surface;self.element=element;self.stop=threading.Event();self.error=None
    def __enter__(self):
        self.receipt=self.request('interaction.begin',surface_id=self.surface,element_id=self.element)
        def renew():
            while not self.stop.wait(8):
                try:self.request('interaction.renew',surface_id=self.surface,element_id=self.element)
                except (OSError,RuntimeError) as exc:self.error=exc;return
        self.worker=threading.Thread(target=renew,daemon=True);self.worker.start();return self
    def __exit__(self,*_):
        self.stop.set();self.worker.join(timeout=4)
        try:self.request('interaction.end',surface_id=self.surface,element_id=self.element)
        except (OSError,RuntimeError):pass


def preserve(text,surface,element):
    root=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'agent-os/terminal-drafts'
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='recovered-',suffix='.json',dir=root)
    with os.fdopen(fd,'w') as stream:
        os.fchmod(stream.fileno(),0o600);json.dump({'format':1,'surface_id':surface,'element_id':element,'text':text},stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
    return name


def edit(request,document,element,input_fn=input,output=print):
    surface=document['surface_id'];node=document['elements'][element]
    with Lease(request,surface,element) as lease:
        recovered=request('draft.get',surface_id=surface,element_id=element)
        output('Current text: '+clean(recovered.get('draft') if recovered.get('draft') is not None else node.get('props',{}).get('value','')))
        if node.get('props',{}).get('multiline'):
            output('Enter lines. A single period finishes; two periods enter a literal period.');rows=[]
            while True:
                line=input_fn('> ')
                if line=='.':break
                rows.append('.' if line=='..' else line)
                if len('\n'.join(rows).encode())>65536:raise ValueError('Draft exceeds 64 KiB')
            text='\n'.join(rows)
        else:text=input_fn('New text: ')
        if len(text.encode())>65536:raise ValueError('Draft exceeds 64 KiB')
        try:
            if lease.error:raise RuntimeError(str(lease.error))
            saved=request('draft.save',surface_id=surface,element_id=element,expected_draft_revision=recovered['draft_revision'],draft=text)
        except (OSError,RuntimeError):
            output('Draft saved locally for recovery: '+preserve(text,surface,element));raise
        choice=input_fn('[s] Save to view  [k] Keep draft  [d] Discard: ').strip().lower()
        if choice=='s':
            current=request('presentation.snapshot')['documents'][surface]
            result=request('presentation.apply',protocol='agentos.presentation/1',catalog_revision='native-core/1',request_id=f'terminal-save-{time.time_ns()}',expected_revisions={surface:current['revision']},operations=[{'op':'draft.commit','surface_id':surface,'element_id':element,'expected_draft_revision':saved['draft_revision']}])
            output('Saved. Revision '+str(result['revisions'][surface]))
        elif choice=='d':request('draft.save',surface_id=surface,element_id=element,expected_draft_revision=saved['draft_revision'],draft=None);output('Draft discarded.')
        else:output('Draft retained; it is separate from the view document.')


def interact(activity,request,input_fn=input,output=print):
    """Ordinary terminal controls explicitly separated from agent/command input."""
    selected=None;offset=0
    while True:
        try:
            documents={key:doc for key,doc in request('presentation.snapshot')['documents'].items() if doc.get('surface_id') and doc['activity_id']==str(activity)}
            output('\nShared views — activity '+str(activity))
            if selected not in documents:
                selected=None
                for index,(key,doc) in enumerate(documents.items(),1):output(f"{index}. {clean(doc['title'])} [{key}]")
                choice=input_fn('View number, r refresh, q back: ').strip()
                if choice.lower()=='q':return
                if choice.lower()=='r':continue
                if not choice.isdigit() or not 1<=int(choice)<=len(documents):continue
                selected=list(documents)[int(choice)-1];offset=0
            document=documents[selected];bindings=request('binding.snapshot',surface_id=selected)['bindings']
            lines,controls=project(document,bindings)
            offset=max(0,min(offset,max(0,len(lines)-1)))
            output(clean(document['title'])+f' · revision {document["revision"]}')
            for line in lines[offset:offset+24]:output(line)
            output(f'Lines {offset+1}–{min(offset+24,len(lines))}/{len(lines)}')
            choice=input_fn('Control ID · + next · - previous · b views · r refresh · q back: ').strip()
            if choice=='q':return
            if choice=='+':offset+=24;continue
            if choice=='-':offset=max(0,offset-24);continue
            if choice=='b':selected=None;continue
            if choice=='r':continue
            if choice not in controls:output('Choose a listed control ID.');continue
            node=controls[choice]
            if node['type']=='Link@1':output(clean(node.get('props',{}).get('url','')))
            elif node['type']=='TextField@1':edit(request,document,choice,input_fn,output)
            else:
                receipt=invoke(request,document,choice);output(clean(json.dumps(receipt,ensure_ascii=False,indent=2)))
        except (OSError,RuntimeError,ValueError,KeyError) as exc:output('View unavailable: '+clean(str(exc)))
        except (EOFError,KeyboardInterrupt):output('\nBack to terminal.');return
