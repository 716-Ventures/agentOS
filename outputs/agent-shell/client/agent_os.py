#!/usr/bin/python3
"""Terminal client and scriptable interface for the Agent OS environment core."""
import argparse
import curses
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import textwrap
import sys
import time
import unicodedata
from urllib.parse import urlsplit

SOCKET = os.environ.get('AGENT_OS_SOCKET', '/run/agent-os/runtime.sock')
LIVE = {'starting', 'running', 'cancelling'}


def request(op, **fields):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(3)
        conn.connect(SOCKET)
        conn.sendall(json.dumps({'op': op, **fields}).encode() + b'\n')
        with conn.makefile('rb') as f:
            result = json.loads(f.readline(2 * 1024 * 1024))
    if not result['ok']:
        raise RuntimeError(result['error'])
    return result['result']


def layout_request(op, **fields):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(3)
        conn.connect('/run/agent-os-layout/api.sock')
        conn.sendall(json.dumps({'op':op,**fields}).encode()+b'\n')
        with conn.makefile('rb') as f: result=json.loads(f.readline(512*1024))
    if not result['ok']:raise RuntimeError(result['error'])
    return result['result']


def broker_request(op, **fields):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(3);conn.connect('/run/agent-os-broker/api.sock')
        conn.sendall(json.dumps({'op':op,**fields}).encode()+b'\n')
        with conn.makefile('rb') as f: result=json.loads(f.readline(512*1024))
    if not result['ok']:raise RuntimeError(result['error'])
    return result['result']


def approval_target(text, proposals):
    words=text.lower().strip().rstrip('.!').split()
    if not words or words[0] not in ('approved','approve'):return None
    if len(words)==1:
        if len(proposals)!=1:raise ValueError('More than one action needs approval. Reply approve 1, approve 2, and so on.')
        return proposals[0]
    if len(words)==2:
        if words[1].isdigit() and 1<=int(words[1])<=len(proposals):return proposals[int(words[1])-1]
        target=next((j for j in proposals if j['id']==words[1]),None)
        if target:return target
    raise ValueError('That operation was not pending when you opened this reply. Review the current proposals and reply again.')


def approve_operation(proposal):
    # Only the local human client crosses this boundary. Never a model tool.
    current=broker_request('poll',job_id=proposal['id'])
    if current['status']!='approval_required' or any(current[k]!=proposal[k] for k in ('argv','activity','scope')):
        raise RuntimeError('This proposal changed or was already handled. Nothing was approved.')
    result=subprocess.run(['/usr/bin/sudo','-n','/usr/local/bin/agent-os-broker','approve',proposal['id']],
                          capture_output=True,text=True,timeout=15)
    if result.returncode:
        raise RuntimeError('Approval failed: '+clean(result.stderr.strip() or result.stdout.strip()))
    return json.loads(result.stdout)


def conversation_turn(job,raw):
    question=job_label(job['argv'])[5:]
    if question.startswith('I approved operation ') and 'Poll this existing operation' in question:
        question='Approved.'
    if '\nModel: ' in raw:
        body=raw.rsplit('\nModel: ',1)[0]
        for marker in ('Answer:\n','Reading the results…\n','Thinking…\n'):
            if marker in body:body=body.rsplit(marker,1)[1];break
    else:
        steps=[line for line in raw.splitlines() if line.startswith(('Thinking','Using ','Reading the results','Broker job ','Agent OS:','The model provider'))]
        updates=[line[8:] for line in raw.splitlines() if line.startswith('Update: ')]
        if 'HTTP 429' in raw:body='The AI service is limiting requests, so I couldn’t finish this reply. Completed actions are saved. Please try again later.'
        elif 'Agent OS:' in raw:
            error=raw.rsplit('Agent OS:',1)[1].strip().splitlines()[0]
            if any('HTTP '+str(code) in error for code in (500,502,503,504)):
                body='The AI service temporarily stopped responding. Actions already started may still be running; any instructions needing your attention appear below. You can reply to resume.'
            else:body='I couldn’t finish this request: '+error
        elif job.get('status') in ('failed','interrupted','cancelled'):body='This request stopped before I could finish. You can try again.'
        elif updates:
            recent=list(dict.fromkeys(updates[-8:]))[-3:]
            body='Working…\n\n'+'\n'.join('• '+line for line in recent)
        elif any('approval_required' in line for line in steps):body='Ready for your go-ahead.'
        elif steps and steps[-1].startswith('Reading'):body='Putting the pieces together…'
        else:body='On it…'
    if re.search(r'<\s*(?:tool_call|arg_key|arg_value)(?:\s|>)',body,re.I):
        body='The model returned an invalid action request instead of a progress report. That text was not executed. Earlier actions may have started; reply to check progress and continue.'
    return 'You\n'+question+'\n\nAgent\n'+body.strip()


def web_links(text):
    result=[]
    for match in re.finditer(r'https?://[^\s<>"\x00-\x1f\x7f]+',clean(text)):
        url=match.group().rstrip('.,;!?)]`')
        try:
            parsed=urlsplit(url)
            if parsed.hostname and not parsed.username and not parsed.password:result.append((match.start(),url))
        except ValueError:pass
    return result


def hyperlink_escape(url,label):
    # Only our validated HTTP(S) links become terminal control sequences.
    if not any(u==url for _,u in web_links(url)) or any(ord(c)<32 or ord(c)==127 for c in url):return clean(label)
    return '\x1b]8;;'+url+'\x1b\\'+clean(label)+'\x1b]8;;\x1b\\'


def clean(text):
    # Render untrusted process output as text, never terminal escape sequences.
    text = re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)', '', str(text))
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    return ''.join(c for c in text if c in '\n\t' or not unicodedata.category(c).startswith('C'))


def job_label(argv):
    if len(argv) >= 5 and argv[2] == '/usr/local/lib/agent-os/services/worker.py':
        if argv[3] == 'disk': return 'Inspect disk usage'
        if argv[3] == 'ask': return 'Ask: ' + (argv[5] if len(argv) > 5 else '')
    return shlex.join(argv)


def stamp(ts):
    return datetime.datetime.fromtimestamp(ts).strftime('%H:%M:%S')


def selection_path():
    return Path.home() / '.local/state/agent-os/selection.json'


def remember(activity):
    p = selection_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    temporary = p.with_suffix('.tmp')
    temporary.write_text(json.dumps({'activity_id': activity}))
    temporary.replace(p)


def previous():
    try:
        return json.loads(selection_path().read_text())['activity_id']
    except (OSError, ValueError, KeyError):
        return None


# Layout is view state only: closing a tile never cancels its job.
def leaf(job=None, view='answer'):
    return {'id': os.urandom(4).hex(), 'job': job, 'view': view, 'scroll': 0}


def leaves(tree):
    if 'id' in tree: return [tree]
    return leaves(tree['first']) + leaves(tree['second'])


def replace_tile(tree, ident, replacement):
    if tree.get('id') == ident: return replacement
    if 'id' not in tree:
        tree['first'] = replace_tile(tree['first'], ident, replacement)
        tree['second'] = replace_tile(tree['second'], ident, replacement)
    return tree


def close_tile(tree, ident):
    if 'id' in tree: return tree
    if tree['first'].get('id') == ident: return tree['second']
    if tree['second'].get('id') == ident: return tree['first']
    tree['first'] = close_tile(tree['first'], ident)
    tree['second'] = close_tile(tree['second'], ident)
    return tree


def parent_split(tree, ident):
    if 'id' in tree: return None
    if any(tree[k].get('id') == ident for k in ('first', 'second')): return tree
    return parent_split(tree['first'], ident) or parent_split(tree['second'], ident)


def minimum(tree):
    if 'id' in tree: return (28, 7)
    a,b=minimum(tree['first']),minimum(tree['second'])
    return (a[0]+b[0]+1,max(a[1],b[1])) if tree['axis']=='x' else (max(a[0],b[0]),a[1]+b[1]+1)


def rectangles(tree, x,y,w,h):
    if 'id' in tree: return [(tree,x,y,w,h)]
    a,b=minimum(tree['first']),minimum(tree['second'])
    if tree['axis']=='x':
        cut=max(a[0],min(w-1-b[0],round((w-1)*tree['ratio'])))
        return rectangles(tree['first'],x,y,cut,h)+rectangles(tree['second'],x+cut+1,y,w-cut-1,h)
    cut=max(a[1],min(h-1-b[1],round((h-1)*tree['ratio'])))
    return rectangles(tree['first'],x,y,w,cut)+rectangles(tree['second'],x,y+cut+1,w,h-cut-1)


def valid_tree(t, depth=0):
    if not isinstance(t,dict) or depth>5: return False
    if 'id' in t:
        return (isinstance(t['id'],str) and t.get('view') in ('answer','output','history','jobs')
                and (t.get('job') is None or type(t['job']) is int)
                and type(t.get('scroll')) is int and t['scroll']>=0)
    return (t.get('axis') in ('x','y') and type(t.get('ratio')) in (int,float)
            and .15<=t['ratio']<=.85 and valid_tree(t.get('first'),depth+1) and valid_tree(t.get('second'),depth+1))


def cells(s):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W','F') else 1 for c in s)


def clipped(s, width):
    out='';used=0
    for c in s:
        size=cells(c)
        if used+size>width:break
        out+=c;used+=size
    return out


def elide(text,width):
    return text if cells(text)<=width else clipped(text,max(0,width-1))+'…'


def wrapped(text,width):
    result=[]
    for line in clean(text).expandtabs(4).splitlines():
        if not line:result.append('');continue
        # Wrap in display cells, preserving wide Unicode and indentation.
        while cells(line)>width:
            part=clipped(line,width)
            split=part.rfind(' ')
            if split>width//2:part=part[:split]
            if not part:break
            result.append(part);line=line[len(part):].lstrip()
        result.append(line)
    return result


MODEL_USAGE = Path('/run/agent-os-ai/model-usage.json')


def knowledge_request(action,**fields):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
        conn.settimeout(180);conn.connect('/run/agent-os-ai/api.sock')
        conn.sendall(json.dumps({'op':'knowledge','action':action,**fields}).encode()+b'\n')
        with conn.makefile('rb') as f:result=json.loads(f.readline(4*1024*1024))
    if 'error' in result:raise RuntimeError(result['error'])
    return result['result']


def model_snapshot():
    try:
        return json.loads(MODEL_USAGE.read_text())
    except (OSError, ValueError):
        return {'unavailable': True}


def model_lines(data):
    if data.get('unavailable'):
        return ['Usage is temporarily unavailable.', '', 'Reconnecting automatically…']
    def age(value):
        try:
            seconds=max(0,int((datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(value)).total_seconds()))
            return 'just now' if seconds<60 else f'{seconds//60}m ago' if seconds<3600 else f'{seconds//3600}h ago' if seconds<86400 else f'{seconds//86400}d ago'
        except (TypeError,ValueError):return 'unknown'
    def count(row,field):
        reports=row.get(field+'_reports',0)
        if not reports:return 'not reported'
        return f"{row[field+'_tokens']:,}" + ('*' if reports<row['responses'] else '')
    rows=list(data.get('models',{}).values());lines=[];shown=set()
    configs=data.get('configuration',[])
    for cfg in configs:
        matching=[r for r in rows if r['provider']==cfg['provider'] and r['model']==cfg['model']]
        row=matching[0] if matching else None
        title='Ling 3.0 Flash' if cfg['model']=='inclusionai/ling-3.0-flash' else 'Jev' if cfg['provider']=='Typesafe' else cfg['model']
        role='Reasoning & action planning' if cfg['provider']=='Vercel AI Gateway' else 'Action effects & risk assessment'
        lines += [title,role,cfg['provider']+' · '+('Configured' if cfg['configured'] else 'Not configured')]
        if row:
            shown.add((row['provider'],row['model']))
            served=row.get('resolved_model',cfg['model'])
            if cfg['provider']=='Typesafe':lines += ['Version: '+served]
            elif title==cfg['model']:pass
            else:lines += [cfg['model']]
            def metric(label,value):return f'{label:<16}  {value}'
            lines += ['',metric('Requests',f"{row['attempts']:,}"),
                      metric('In progress',str(row['active'])),
                      metric('Input tokens',count(row,'input')),
                      metric('Output tokens',count(row,'output')), '',
                      metric('Errors',f"{row['errors']:,}"),
                      metric('Rate limits',f"{row['rate_limits']:,}")]
            if row.get('interrupted'):lines += [metric('Interrupted',f"{row['interrupted']:,}")]
            if row.get('last_latency_ms') is not None:
                lines += ['',metric('Last duration',f"{row['last_latency_ms']/1000:.2f} s"),
                          metric('Last activity',age(row['last_at']))]
            if row.get('last_status') not in (None,'response received'):
                lines += ['Last result: '+row['last_status']]
        else:
            lines += ['', 'No requests yet.' if cfg['configured'] else 'Add credentials to enable this model.']
        lines += ['', '']
    previous=[r for r in rows if (r['provider'],r['model']) not in shown]
    if previous:
        lines += ['Previously used', '']
        for row in previous:
            lines += [row['model'],f"{row['attempts']:,} requests · {row['errors']:,} errors",'Input '+count(row,'input')+' · Output '+count(row,'output'),'']
    try:
        started=datetime.datetime.fromisoformat(data['tracking_since']).strftime('%b %d, %H:%M UTC')
    except (KeyError,TypeError,ValueError):started='tracking began'
    lines += ['About these numbers', 'Usage since '+started+'.',
              'Requests include retries and planning.',
              '* Partial token reporting, when marked.',
              'Billing & credit balance not connected.']
    return lines


def dashboard(screen):
    curses.curs_set(0);screen.timeout(150)
    try:curses.set_escdelay(30)
    except AttributeError:pass
    mouse_enabled=False
    try:curses.mousemask(0)
    except curses.error:pass
    color={}
    if curses.has_colors():
        curses.start_color();curses.use_default_colors()
        # Quiet slate surfaces; cyan is the existing identity, used only for focus/actions.
        if curses.COLORS>=256:
            palette={'base':(252,233),'muted':(245,233),'accent':(117,233),'line':(240,233),
                     'selected':(255,24),'bar':(252,235),'good':(151,233),'bad':(210,233)}
        else:
            palette={'base':(7,-1),'muted':(7,-1),'accent':(6,-1),'line':(7,-1),
                     'selected':(0,6),'bar':(7,-1),'good':(2,-1),'bad':(1,-1)}
        for i,(name,(fg,bg)) in enumerate(palette.items(),1):
            curses.init_pair(i,fg,bg);color[name]=curses.color_pair(i)
    def style(name):return color.get(name,0)
    screen.bkgd(' ',style('base'))
    path=selection_path().with_name('layouts-v1.json')
    try:stored=json.loads(path.read_text())
    except (OSError,ValueError):stored={}
    legacy={}
    for key,value in stored.get('activities',{}).items():
        tree=value.get('tree') if isinstance(value,dict) else None
        if valid_tree(tree) and len(leaves(tree))<=6 and len({p['id'] for p in leaves(tree)})==len(leaves(tree)):
            legacy[key]=value
    path=selection_path().with_name('layout-client.json')
    try:preferences=json.loads(path.read_text())
    except (OSError,ValueError):preferences=stored
    saved_views=preferences.get('views',{})
    layouts={}
    client_id=os.urandom(16).hex()
    theme=preferences.get('theme','dark')
    def set_theme():
        if curses.has_colors() and curses.COLORS>=256:
            values=([(252,233),(245,233),(117,233),(240,233),(255,24),(252,235),(151,233),(210,233)]
                    if theme=='dark' else [(235,255),(240,255),(24,255),(247,255),(255,24),(235,254),(22,255),(124,255)])
            for i,(fg,bg) in enumerate(values,1):curses.init_pair(i,fg,bg)
    set_theme()
    sidebar=bool(preferences.get('sidebar',True));activity=previous();focus=''
    zoom=False;note='';note_until=0;cache={};state={'activities':[],'jobs':[]};last_fetch=0;connected=True
    menu=None;menu_index=0;editor=None;cursor=0;history_cache={};dirty=False;last_save=0
    active_rects=[];rail_hits=[];menu_hits=[];buttons=[]
    broker_jobs=[];broker_error='';attention=[]
    rail_focus=False
    models_open=False;models_scroll=0;models_focus=False

    def save():
        nonlocal dirty,last_save
        path.parent.mkdir(parents=True,exist_ok=True)
        views={p['id']:{k:p.get(k) for k in ('job','view','scroll','at_end')} for layout in layouts.values() for p in leaves(layout['tree'])}
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps({'views':{**saved_views,**views},'sidebar':sidebar,'theme':theme}))
        tmp.replace(path);dirty=False;last_save=time.monotonic()
        if activity:remember(activity)

    def notify(message):
        nonlocal note,note_until
        note=message;note_until=time.monotonic()+5

    def put(y,x,text,width=None,kind='base',bold=False):
        h,w=screen.getmaxyx()
        if not 0<=y<h or not 0<=x<w-1:return
        limit=max(0,min(w-x-1,width if width is not None else w-x-1))
        value=clipped(clean(text).replace('\n',' '),limit)
        try:screen.addstr(y,x,value,style(kind)|(curses.A_BOLD if bold else 0))
        except curses.error:pass

    def fill(y,x,width,kind):
        put(y,x,' '*max(0,width),width,kind)

    def current():
        if not activity:return None
        key=str(activity)
        return layouts.get(key)

    def selected():
        layout=current()
        if not layout:return None
        return next((p for p in leaves(layout['tree']) if p['id']==focus),leaves(layout['tree'])[0])

    def accept_layout(remote):
        nonlocal focus,zoom
        old={p['id']:p for p in leaves(layouts[str(activity)]['tree'])} if str(activity) in layouts else saved_views
        for pane in leaves(remote['tree']):
            previous_view=old.get(pane['id'],{})
            if previous_view.get('job')==pane['job'] and previous_view.get('view')==pane['view']:
                pane['scroll']=previous_view.get('scroll',0) or 0
                pane['at_end']=previous_view.get('at_end',False)
        layouts[str(activity)]=remote
        focus=remote['focus'];zoom=remote['zoom'] is not None

    def pull_layout():
        if not activity:return
        key=str(activity)
        if key not in layouts:
            seed=legacy.get(key)
            if seed is None:
                recent=next((j['id'] for j in state['jobs'] if j['activity_id']==activity),None)
                seed={'tree':leaf(recent),'focus':None}
            accept_layout(layout_request('ensure',activity=activity,seed=seed))
        else:
            remote=layout_request('snapshot',activity=activity)
            if remote['revision']!=layouts[key]['revision']:accept_layout(remote)

    def mutate(operation,**fields):
        nonlocal dirty
        layout=current()
        if layout is None:raise RuntimeError('Layout service unavailable; reconnecting.')
        action={'operation':operation,**fields}
        if operation not in ('restore','undo') and 'surface_id' not in action:
            action['surface_id']=selected()['id']
        try:
            accept_layout(layout_request('apply',activity=activity,expected_revision=layout['revision'],action=action))
            dirty=True
        except RuntimeError:
            pull_layout()
            raise

    def editing(active):
        if activity:layout_request('editing',activity=activity,client_id=client_id,active=active)

    def switch(ident):
        nonlocal activity,focus,zoom,dirty
        activity=ident
        pull_layout();dirty=True

    def ask_input(kind):
        nonlocal editor,cursor
        editing(True)
        editor={'kind':kind,'text':'','proposals':[dict(j) for j in broker_jobs if j['status']=='approval_required' and j['activity']==activity]};cursor=0
        if kind=='ask' and selected():
            mutate('view',view='answer');selected()['scroll']=0;selected()['at_end']=True

    def choose(kind,items):
        nonlocal menu,menu_index
        menu={'kind':kind,'items':items};menu_index=0

    actions=[('models','Models and usage','p'),('ask','Reply to Agent','Enter / a'),('run','Run a command','r'),('split_x','Split side by side','v'),
             ('split_y','Split top / bottom','s'),('jobs','Choose work for this tile','o'),
             ('view','Change tile view','t'),('zoom','Maximize / restore tile','z'),('grow','Grow tile','+'),
             ('shrink','Shrink tile','−'),('swap','Swap with next tile','m'),('close','Close tile; keep work running','w'),
             ('undo','Undo last layout change','u'),('remove','Remove activity from sidebar','d'),('sidebar','Show / hide activities','b'),
             ('mouse','Toggle mouse controls / text selection','M'),('theme','Switch light / dark theme','T'),('new','New activity','n'),('disk','Inspect disk usage','i'),('stop','Stop selected core job','x')]

    def action(name):
        nonlocal focus,zoom,sidebar,dirty,menu,theme,rail_focus,mouse_enabled,models_open,models_scroll,models_focus
        if name=='models':
            models_open=not models_open;models_focus=models_open;models_scroll=0;return
        pane=selected();layout=current()
        if name=='mouse':
            mouse_enabled=not mouse_enabled
            curses.mousemask(curses.ALL_MOUSE_EVENTS if mouse_enabled else 0)
            notify('Mouse controls enabled · M returns to text selection' if mouse_enabled else 'Text selection enabled · drag to select, then use your terminal’s Copy command')
            return
        if name=='new':ask_input('new');return
        if name=='remove' and activity:
            choose('remove',[(False,'Cancel'),(True,'Remove from sidebar; files and existing work are retained')]);return
        if name=='theme':theme='light' if theme=='dark' else 'dark';set_theme();dirty=True;return
        if name=='sidebar':sidebar=not sidebar;dirty=True;return
        if name=='ask' and not pane:rail_focus=False;ask_input('ask');return
        if not pane:notify('Press Enter to ask, or n to name an activity.');return
        if name in ('ask','run'):rail_focus=False;ask_input(name);return
        if name=='view':
            choose('view',[('answer','Conversation'),('output','Full output'),('history','Activity history'),('jobs','Work list')]);return
        if name=='jobs':
            choose('jobs',[(j['id'],job_label(j['argv'])+'  ·  '+j['status']) for j in jobs]);return
        if name in ('split_x','split_y'):
            mutate('split',axis='x' if name=='split_x' else 'y')
            notify('New tile · o chooses work · a asks · r runs a command')
        elif name=='close':
            mutate('close');notify('Tile closed. Its work continues.')
        elif name=='zoom':mutate('restore' if zoom else 'zoom')
        elif name in ('grow','shrink'):mutate('resize',delta=.05 if name=='grow' else -.05)
        elif name=='swap':
            panes=leaves(layout['tree'])
            if len(panes)>1:mutate('swap',other_id=panes[(panes.index(pane)+1)%len(panes)]['id'])
        elif name=='undo':mutate('undo')
        elif name=='disk':submit(workflow_argv('disk',activity),'output')
        elif name=='stop':
            if pane['job']:
                result=request('cancel',job_id=pane['job']);notify('Job '+str(pane['job'])+': '+result['status']+'. Broker jobs have separate controls.')
        dirty=True

    def remove_selected(confirm):
        nonlocal activity,state,dirty,last_fetch,broker_jobs
        if not confirm:return
        request('remove_activity',activity_id=activity)
        state=request('snapshot');activity=state['activities'][0]['id'] if state['activities'] else None
        broker_jobs=[]
        if activity:pull_layout()
        else:selection_path().unlink(missing_ok=True)
        dirty=True;last_fetch=0;notify('Activity removed. Restore with agent-os restore ID; list IDs with agent-os removed.')

    def submit(argv,view):
        nonlocal focus,dirty,last_fetch
        pane=selected()
        ident=request('run',activity_id=activity,argv=argv)['id']
        mutate('bind',surface_id=pane['id'],job_id=ident,view=view)
        last_fetch=0
        notify('Work started. You can keep using other tiles.')

    def pane_text(pane):
        job=next((j for j in jobs if j['id']==pane['job']),None)
        if pane['view']=='history':
            events=history_cache.get(activity,[])
            return 'Activity history','\n'.join(stamp(e['at'])+'  '+e['kind']+'\n  '+json.dumps(e['detail'],ensure_ascii=False) for e in reversed(events)),None
        if pane['view']=='jobs':
            return 'Work in this activity','\n\n'.join(str(j['id'])+'  '+j['status']+'\n'+job_label(j['argv']) for j in jobs),None
        if job is None:
            return 'Ready',proposal_text()+'\n\nMake room for your work.\n\nAsk a question, run a command, or open existing work in this tile.\n\na  Ask Agent\nr  Run a command\no  Choose work\n\nv  Split side by side\ns  Split top / bottom',None
        raw=cache.get(job['id'],{}).get('text','')
        label=job_label(job['argv'])
        if pane['view']=='answer' and label.startswith('Ask: '):
            exchanges=sorted((j for j in jobs if job_label(j['argv']).startswith('Ask: ')),key=lambda j:j['id'])[-20:]
            raw='\n\n────────────────────\n\n'.join(conversation_turn(j,cache.get(j['id'],{}).get('text','')) for j in exchanges)
            raw+='\n\n'+'\n\n'.join(attention)+'\n\n'+proposal_text()+'\nEnter / a  Reply to this conversation'
            return 'Conversation',raw,job
        if job.get('error'):raw+='\n\n'+job['error']
        if pane['view']=='answer':raw+='\n\n'+proposal_text()
        if pane['view']=='output':
            for pending in broker_jobs:
                if pending['status']=='approval_required':raw+='\n\nPending approval: '+pending['id']+'\n'+shlex.join(pending['argv'])
        return label,raw,job

    def proposal_text():
        pending=[j for j in broker_jobs if j['status']=='approval_required' and j['activity']==activity]
        if pending:
            lines=['An action needs your review']
            for number,j in enumerate(pending,1):
                argv=j['argv']
                if argv and argv[0] in ('apt-get','/usr/bin/apt-get','apt','/usr/bin/apt') and argv[1:]==['update']:
                    summary='Refresh the list of available software.'
                elif len(argv)>2 and argv[0] in ('apt-get','/usr/bin/apt-get','apt','/usr/bin/apt') and argv[1]=='install' and all(not a.startswith('-') or a in ('-y','--yes') for a in argv[2:]):
                    summary='Install '+', '.join(a for a in argv[2:] if not a.startswith('-'))+' and any required dependencies.'
                else:summary=j['purpose']+'\n'+j.get('policy',{}).get('reason','Review the effects before proceeding.')
                lines.append((str(number)+'. ' if len(pending)>1 else '')+summary)
            lines.append('Reply “approved” to continue.' if len(pending)==1 else 'Reply “approve 1”, “approve 2”, and so on.')
            return '\n'.join(lines)
        if broker_error:return 'I can’t check approvals right now. Please reconnect and try again.'
        recent=[j for j in broker_jobs if j.get('approved_at')]
        if any(j['status'] in LIVE for j in recent):return 'Taking care of the action you approved…'
        if recent and recent[0]['status'] in ('failed','interrupted'):return 'The approved action didn’t finish successfully. I’ll need to check what happened.'
        return ''

    def reply(text,proposals):
        if not activity:switch(request('create',name='Conversation')['id'])
        target=approval_target(text,proposals)
        if target:
            result=approve_operation(target)
            text='I approved operation '+target['id']+' ('+shlex.join(target['argv'])+'). It is '+result['status']+'. Poll this existing operation, report the result, and continue our conversation. Do not create another proposal for the same command.'
        submit(workflow_argv('ask',activity,text),'answer')
        selected()['at_end']=True;selected()['scroll']=0

    while True:
        now=time.monotonic();h,w=screen.getmaxyx()
        try:
            if now-last_fetch>=.6:
                state=request('snapshot');connected=True;last_fetch=now
                if activity not in [a['id'] for a in state['activities']]:
                    if state['activities']:switch(state['activities'][0]['id'])
                    else:activity=None
                if editor:editing(True)
                if activity:pull_layout()
                if current():
                    ids={p['job'] for p in leaves(current()['tree']) if p['job']}
                    ids.update(j['id'] for j in [j for j in state['jobs'] if j['activity_id']==activity and job_label(j['argv']).startswith('Ask: ')][:20])
                    for ident in ids:
                        item=cache.setdefault(ident,{'offset':0,'text':''})
                        data=request('log',job_id=ident,offset=item['offset'])
                        item['offset']=data['offset'];item['text']=(item['text']+data['text'])[-262144:]
                    if any(p['view']=='history' for p in leaves(current()['tree'])):
                        history_cache[activity]=request('history',activity_id=activity)
                try:
                    broker_jobs=broker_request('list',activity=activity);broker_error='';attention=[]
                    for task in broker_jobs:
                        if task['status'] in LIVE:
                            live=broker_request('poll',job_id=task['id'])
                            output=clean(live.get('output',''))
                            if live['status'] in LIVE and any(marker in output.lower() for marker in ('one-time code','device code','open this url','visit this url')):
                                attention.append('Needs your attention\n'+'\n'.join(output.strip().splitlines()[-8:]))
                except (OSError,RuntimeError,ValueError) as exc:broker_jobs=[];attention=[];broker_error=str(exc)
            jobs=[j for j in state['jobs'] if j['activity_id']==activity]
            if dirty and now-last_save>.4:save()
        except (OSError,RuntimeError,ValueError) as exc:
            connected=False;last_fetch=now;notify(str(exc));jobs=[j for j in state['jobs'] if j['activity_id']==activity]
        panel_width=min(52,max(24,w//3)) if models_open and w>=44 else 0
        work_right=w-panel_width
        screen.erase();buttons=[];rail_hits=[];menu_hits=[];active_rects=[];visible_links=[]
        if h<14 or w<44:
            put(1,2,'Agent OS',bold=True);put(3,2,'Expand to 44 columns × 14 rows.');put(5,2,'Your layout and work are preserved.');put(7,2,'q  Leave')
        else:
            fill(0,0,w,'bar');put(0,2,'Agent OS',kind='bar',bold=True)
            chosen=next((a for a in state['activities'] if a['id']==activity),None)
            if w>=72:put(0,14,'/  '+elide(chosen['name'] if chosen else 'Welcome',max(1,w-45)),max(0,w-42),'bar')
            else:put(1,2,elide(chosen['name'] if chosen else 'Welcome',w-4),w-4,'muted')
            put(0,max(16,w-23),'Connected' if connected else 'Reconnecting',kind='bar')
            show_rail=sidebar and (work_right>=100 or (rail_focus and work_right>=68));left=24 if show_rail else 1
            if show_rail:
                put(2,2,'Activities ◂' if rail_focus else 'Activities',kind='accent' if rail_focus else 'muted',bold=rail_focus);put(2,19,'+ n',kind='accent')
                idx=next((i for i,a in enumerate(state['activities']) if a['id']==activity),0)
                start=max(0,idx-(h-11))
                for row,a in enumerate(state['activities'][start:start+h-10],4):
                    if a['id']==activity:fill(row,1,21,'selected')
                    put(row,2,('› ' if a['id']==activity else '  ')+elide(a['name'],18),20,'selected' if a['id']==activity else 'muted')
                    rail_hits.append((row,a['id']))
                for y in range(2,h-4):put(y,23,'│',kind='line')
                put(h-5,2,'↑↓ Move  d Remove' if rail_focus else '← Activities  n New',20,'accent' if rail_focus else 'muted')
            layout=current();area=(left,2,work_right-left-1,h-6)
            if layout:
                panes=leaves(layout['tree'])
                if focus not in [p['id'] for p in panes]:focus=layout.get('focus') if layout.get('focus') in [p['id'] for p in panes] else panes[0]['id']
                pane=selected();small=minimum(layout['tree'])[0]>area[2] or minimum(layout['tree'])[1]>area[3]
                active_rects=[(pane,*area)] if zoom or small else rectangles(layout['tree'],*area)
                for p,x,y,pw,ph in active_rects:
                    active=p['id']==focus and not models_focus;edge='accent' if active else 'line'
                    for yy in range(y+1,y+ph-1):put(yy,x,'│',kind=edge);put(yy,x+pw-1,'│',kind=edge)
                    put(y,x,'╭'+'─'*(pw-2)+'╮',pw,edge);put(y+ph-1,x,'╰'+'─'*(pw-2)+'╯',pw,edge)
                    title,body,job=pane_text(p)
                    put(y,x+2,' '+str(panes.index(p)+1)+'  '+elide(title,max(1,pw-21))+' ',max(1,pw-14),'accent' if active else 'muted',active)
                    status=job['status'] if job else ('focus' if active else '')
                    put(y,x+pw-min(13,len(status)+3),' '+status+' ',min(12,pw-4),'bad' if status in ('failed','interrupted') else ('accent' if active else 'muted'))
                    prose=p['view']=='answer' and job and job_label(job['argv']).startswith('Ask: ')
                    lines=wrapped(body,min(76,pw-4) if prose else max(1,pw-4));visible_h=ph-3
                    scroll=min(p['scroll'],max(0,len(lines)-visible_h));end=max(0,len(lines)-scroll)
                    # Static completed answers begin at their top; live output follows its tail.
                    if p['view']=='answer' and job and not job_label(job['argv']).startswith('Ask: ') and job['status'] not in LIVE and p['scroll']==0 and not p.get('at_end',False):
                        end=min(len(lines),visible_h)
                    for row,line in enumerate(lines[max(0,end-visible_h):end],y+1):
                        kind='base';bold=False
                        if line in ('You','Agent'):kind='accent' if line=='Agent' else 'muted';bold=True
                        if p['view']=='answer' and job and job_label(job['argv']).startswith('Ask: '):
                            if line.startswith('#'):line=line.lstrip('#').strip();bold=True
                            line=re.sub(r'\*\*(.*?)\*\*',r'\1',line)
                        put(row,x+2,line,pw-4,kind,bold)
                        visible=clipped(clean(line),pw-4)
                        originals=[url for _,url in web_links(body)]
                        for offset,label in web_links(visible):
                            target=next((url for url in originals if url.startswith(label)),None)
                            if target:
                                column=x+2+cells(visible[:offset])
                                visible_links.append((row,column,target,label))
                                try:screen.addstr(row,column,label,style('accent')|curses.A_UNDERLINE)
                                except curses.error:pass
                    if len(lines)>visible_h:put(y+ph-1,x+pw-20,f' {end}/{len(lines)} · PgUp ',18,'muted')
                if small and not zoom:put(h-4,left,'Compact view · Tab switches tiles · saved splits return when space allows',work_right-left-2,'muted')
                elif zoom:put(h-4,left,'Focused view · z restores your layout',work_right-left-2,'muted')
            else:
                put(4,left+3,'A place for your work.',work_right-left-5,bold=True);put(6,left+3,'Enter  Ask the agent',work_right-left-5,kind='accent')
                put(8,left+3,'n  Name an activity (does not send a message)',width=work_right-left-5)
            fill(h-3,0,w,'bar')
            segments=[('Enter Reply','ask'),('r Run','run'),('v Split','split_x'),('s Stack','split_y'),('z Focus','zoom'),('Space Actions','menu')]
            if w<85:segments=[('Enter Reply','ask'),('r Run','run'),('Space Actions','menu')]
            xx=2
            for label,act in segments:
                if xx+len(label)>w-2:break
                put(h-3,xx,label,kind='bar');buttons.append((xx,xx+len(label),act));xx+=len(label)+3
            hints=('↑↓ Activity  Enter Open  d Remove  n New  F6 Work' if rail_focus else 'F6 Activities  Tab Focus  d Remove  o Work  t View  p Models  ? Help  q Leave') if w>=85 else ('↑↓ Move · d Remove · Enter Open' if rail_focus else 'F6 Activities · Space Actions · q Leave')
            put(h-2,2,note if now<note_until else hints,w-4,'muted')
            if editor:
                fill(h-3,0,w,'selected');fill(h-2,0,w,'base')
                label={'ask':'Reply to Agent','run':'Run command','new':'Name activity · this is a label, not a message'}[editor['kind']]
                put(h-3,2,label+'  ·  Enter submit / Esc cancel',w-4,'selected')
                available=w-6;prefix=editor['text'][:cursor];start=max(0,cursor-available+2)
                while cells(prefix[start:])>available-1:start+=1
                put(h-2,2,'›',kind='accent');put(h-2,4,editor['text'][start:],available)
                curses.curs_set(1)
                try:screen.move(h-2,min(w-2,4+cells(prefix[start:])))
                except curses.error:pass
            else:curses.curs_set(0)
            if panel_width:
                px=work_right;pw=panel_width-1;edge='accent' if models_focus else 'line'
                for yy in range(3,h-5):
                    put(yy,px,'│',kind=edge);put(yy,px+pw-1,'│',kind=edge)
                put(2,px,'╭'+'─'*(pw-2)+'╮',pw,edge)
                put(h-5,px,'╰'+'─'*(pw-2)+'╯',pw,edge)
                put(2,px+2,' Models ',pw-4,'accent',True)
                panel_lines=[]
                for line in model_lines(model_snapshot()):
                    panel_lines.extend(wrapped(line,max(1,pw-4)) or [''])
                page=max(1,h-8)
                models_scroll=max(0,min(models_scroll,max(0,len(panel_lines)-page)))
                for row,line in enumerate(panel_lines[models_scroll:models_scroll+page],3):
                    heading=line in ('Ling 3.0 Flash','Jev','Previously used','About these numbers')
                    secondary=line.startswith(('Vercel AI Gateway','Typesafe ·','inclusionai/','Version:','Usage since','Requests include','* Partial','Billing &'))
                    metric_row=re.match(r'^(.+?) {2,}(\S.*)$',line)
                    if metric_row and pw>=34:
                        label,value=metric_row.groups()
                        put(row,px+2,label,16,'base')
                        put(row,px+20,value,pw-22,'base',True)
                    else:
                        put(row,px+2,line,pw-4,'accent' if heading else 'muted' if secondary else 'base',heading)
                position=f' {models_scroll+1}–{min(len(panel_lines),models_scroll+page)}/{len(panel_lines)} · Live ' if len(panel_lines)>page else ' Live usage '
                put(h-5,px+2,position,pw-4,'muted')
                put(h-4,px+1,'Tab Work · p Close' if models_focus else 'p Close · Tab Focus',pw-2,'muted')
            if menu:
                items=menu['items'];mw=min(68,w-6);mh=min(len(items)+4,h-4);mx=(w-mw)//2;my=(h-mh)//2
                for yy in range(my,my+mh):fill(yy,mx,mw,'bar')
                put(my+1,mx+2,{'actions':'Actions','jobs':'Open work in this tile','view':'Tile view','remove':'Remove '+next((a['name'] for a in state['activities'] if a['id']==activity),'activity')+'?'}[menu['kind']],mw-4,'bar',True)
                begin=max(0,menu_index-(mh-4))
                for row,(value,label) in enumerate(items[begin:begin+mh-3],my+2):
                    idx=begin+row-my-2;kind='selected' if idx==menu_index else 'bar'
                    fill(row,mx+1,mw-2,kind);put(row,mx+3,label,mw-6,kind)
                    menu_hits.append((row,idx))
                if not items:put(my+2,mx+3,'No work yet. Ask or run a command.',mw-6,'bar')
        if editor and not menu:
            try:screen.move(h-2,min(w-2,4+cells(prefix[start:])))
            except curses.error:pass
        screen.refresh()
        if visible_links and not menu:
            output='\x1b7'
            for row,column,target,label in visible_links:
                link_color=24 if theme=='light' else 117
                output+=f'\x1b[{row+1};{column+1}H\x1b[4;38;5;{link_color}m'+hyperlink_escape(target,label)
            sys.stdout.write(output+'\x1b[0m\x1b8');sys.stdout.flush()
        try:key=screen.get_wch()
        except curses.error:continue
        try:
            if not editor and not menu:
                if key=='p':action('models');continue
                if models_focus:
                    if key in ('\x1b','q'):models_open=False;models_focus=False;continue
                    if key in ('\t',curses.KEY_LEFT):models_focus=False;rail_focus=False;continue
                    if key in (curses.KEY_DOWN,'j'):models_scroll+=1;continue
                    if key in (curses.KEY_UP,'k'):models_scroll-=1;continue
                    if key==curses.KEY_NPAGE:models_scroll+=max(1,h-8);continue
                    if key==curses.KEY_PPAGE:models_scroll-=max(1,h-8);continue
                    if key==curses.KEY_HOME:models_scroll=0;continue
                    if key==curses.KEY_END:models_scroll=100000;continue
                    models_focus=False
            if editor:
                if key=='\x1b':editor=None;editing(False);continue
                if key in ('\n','\r',curses.KEY_ENTER):
                    text=editor['text'].strip();kind=editor['kind'];proposals=editor['proposals'];editor=None;editing(False)
                    if text:
                        if kind=='new':switch(request('create',name=text)['id'])
                        elif kind=='ask':reply(text,proposals)
                        else:submit(shlex.split(text),'output')
                    continue
                if key in (curses.KEY_BACKSPACE,'\x7f','\b'):
                    if cursor:editor['text']=editor['text'][:cursor-1]+editor['text'][cursor:];cursor-=1
                elif key==curses.KEY_DC:editor['text']=editor['text'][:cursor]+editor['text'][cursor+1:]
                elif key==curses.KEY_LEFT:cursor=max(0,cursor-1)
                elif key==curses.KEY_RIGHT:cursor=min(len(editor['text']),cursor+1)
                elif key in (curses.KEY_HOME,'\x01'):cursor=0
                elif key in (curses.KEY_END,'\x05'):cursor=len(editor['text'])
                elif key=='\x15':editor['text']=editor['text'][cursor:];cursor=0
                elif isinstance(key,str) and key.isprintable() and len(editor['text'])<4000:
                    editor['text']=editor['text'][:cursor]+key+editor['text'][cursor:];cursor+=len(key)
                continue
            if menu:
                if key in ('\x1b','q'):menu=None;continue
                if key in (curses.KEY_UP,'k'):menu_index=max(0,menu_index-1)
                elif key in (curses.KEY_DOWN,'j'):menu_index=min(len(menu['items'])-1,menu_index+1)
                elif key in ('\n','\r',curses.KEY_ENTER) and menu['items']:
                    value=menu['items'][menu_index][0];kind=menu['kind'];menu=None
                    if kind=='actions':action(value)
                    elif kind=='remove':remove_selected(value)
                    elif kind=='jobs':mutate('bind',job_id=value);last_fetch=0
                    else:mutate('view',view=value)
                elif key==curses.KEY_MOUSE:
                    _,mx,my,_,state_mouse=curses.getmouse()
                    if state_mouse & (curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED):
                        for row,idx in menu_hits:
                            if my==row and (w-min(68,w-6))//2<=mx<(w+min(68,w-6))//2:
                                value=menu['items'][idx][0];kind=menu['kind'];menu=None
                                if kind=='actions':action(value)
                                elif kind=='remove':remove_selected(value)
                                elif kind=='jobs':mutate('bind',job_id=value);last_fetch=0
                                else:mutate('view',view=value)
                                break
                continue
            if key==curses.KEY_F6 or key==curses.KEY_LEFT:
                rail_focus=not rail_focus if key==curses.KEY_F6 else True
                if rail_focus:sidebar=True
                continue
            if rail_focus:
                if key in (curses.KEY_UP,curses.KEY_DOWN,curses.KEY_HOME,curses.KEY_END):
                    activities=state['activities'];idx=next((i for i,a in enumerate(activities) if a['id']==activity),0)
                    idx=0 if key==curses.KEY_HOME else len(activities)-1 if key==curses.KEY_END else idx+(-1 if key==curses.KEY_UP else 1)
                    if activities:switch(activities[max(0,min(len(activities)-1,idx))]['id'])
                    continue
                if key in ('\n','\r',curses.KEY_ENTER,curses.KEY_RIGHT,'\x1b','\t'):
                    rail_focus=False
                    if key=='\t' and current():mutate('focus',surface_id=leaves(current()['tree'])[0]['id'])
                    continue
            if key in ('\n','\r',curses.KEY_ENTER):action('ask');continue
            if key=='q':save();return
            if key in (' ','?',':'):
                choose('actions',[(name,label+'    '+shortcut) for name,label,shortcut in actions]);continue
            if key=='\t' and current():
                panes=leaves(current()['tree']);idx=next((i for i,p in enumerate(panes) if p['id']==focus),0)
                if idx==len(panes)-1:
                    if models_open:models_focus=True;rail_focus=False
                    else:rail_focus=True;sidebar=True
                else:mutate('focus',surface_id=panes[idx+1]['id'])
                continue
            if key in ('[',']') and not editor:
                activities=state['activities'];idx=next((i for i,a in enumerate(activities) if a['id']==activity),0)
                if activities:switch(activities[max(0,min(len(activities)-1,idx+(-1 if key=='[' else 1)))]['id'])
                continue
            if key in (curses.KEY_PPAGE,curses.KEY_NPAGE,curses.KEY_UP,curses.KEY_DOWN,'e') and selected():
                pane=selected();title,body,job=pane_text(pane)
                rect=next((r for r in active_rects if r[0]['id']==pane['id']),None)
                if rect:
                    prose=pane['view']=='answer' and job and job_label(job['argv']).startswith('Ask: ')
                    total=len(wrapped(body,min(76,rect[3]-4) if prose else max(1,rect[3]-4)));page=rect[4]-3
                    current_scroll=pane['scroll']
                    if pane['view']=='answer' and job and job['status'] not in LIVE and current_scroll==0 and not pane.get('at_end',False):current_scroll=max(0,total-page)
                    pane['scroll']=0 if key=='e' else max(0,min(max(0,total-page),current_scroll+({curses.KEY_PPAGE:page,curses.KEY_NPAGE:-page,curses.KEY_UP:1,curses.KEY_DOWN:-1}.get(key,0))))
                    pane['at_end']=True;dirty=True
                continue
            if key==curses.KEY_MOUSE:
                _,mx,my,_,ms=curses.getmouse()
                if not ms & (curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED):continue
                if panel_width and mx>=work_right and 2<=my<h-3:
                    models_focus=True;rail_focus=False;continue
                for p,x,y,pw,ph in active_rects:
                    if x<=mx<x+pw and y<=my<y+ph:
                        rail_focus=False
                        if p['id']!=focus:mutate('focus',surface_id=p['id'])
                for row,ident in rail_hits:
                    if my==row and mx<23:rail_focus=True;switch(ident)
                if my==h-3:
                    for x1,x2,act in buttons:
                        if x1<=mx<=x2:
                            if act=='menu':choose('actions',[(n,l+'    '+s) for n,l,s in actions])
                            else:action(act)
                continue
            mapping={'M':'mouse','D':'remove','a':'ask','r':'run','n':'new','v':'split_x','s':'split_y','z':'zoom','w':'close','+':'grow','=':'grow','-':'shrink','m':'swap','b':'sidebar','u':'undo','o':'jobs','t':'view','d':'remove','i':'disk','x':'stop','T':'theme'}
            if key in mapping:action(mapping[key])
            elif key=='h' and selected():mutate('view',view='history');last_fetch=0
        except (OSError,RuntimeError,ValueError,subprocess.SubprocessError,curses.error) as exc:notify(str(exc))

def workflow_argv(op, activity, question=None):
    argv=['/usr/bin/python3', '-u', '/usr/local/lib/agent-os/services/worker.py', op, str(activity)]
    if question is not None: argv.append(question)
    return argv


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='cmd')
    sub.add_parser('status')
    sub.add_parser('activities')
    sub.add_parser('removed')
    for command in ('remove','restore'):
        c=sub.add_parser(command);c.add_argument('activity',type=int)
    sub.add_parser('providers')
    c=sub.add_parser('knowledge',help='Inspect and restore versioned memory and skills')
    c.add_argument('action',choices=['list','read','history','restore','archive'],nargs='?',default='list')
    c.add_argument('key',nargs='?');c.add_argument('--revision',type=int);c.add_argument('--expected-revision',type=int)
    sub.add_parser('models', help='Read model configuration and measured usage as JSON')
    c=sub.add_parser('disk');c.add_argument('activity',type=int)
    c=sub.add_parser('ask');c.add_argument('activity',type=int);c.add_argument('question')
    c=sub.add_parser('report');c.add_argument('activity',type=int)
    c=sub.add_parser('create');c.add_argument('name')
    c=sub.add_parser('run');c.add_argument('activity',type=int);c.add_argument('argv',nargs=argparse.REMAINDER)
    c=sub.add_parser('jobs');c.add_argument('activity',type=int,nargs='?')
    c=sub.add_parser('stop');c.add_argument('job',type=int)
    c=sub.add_parser('history');c.add_argument('activity',type=int)
    c=sub.add_parser('logs');c.add_argument('job',type=int);c.add_argument('--follow',action='store_true')
    args=p.parse_args()
    if not args.cmd:
        if not sys.stdin.isatty(): p.error('Interactive dashboard requires a terminal; use status for JSON.')
        curses.wrapper(dashboard); return
    if args.cmd=='status': result=request('snapshot')
    elif args.cmd=='knowledge':result=knowledge_request(args.action,**{k:v for k,v in {'key':args.key,'revision':args.revision,'expected_revision':args.expected_revision}.items() if v is not None})
    elif args.cmd=='models': result=model_snapshot()
    elif args.cmd=='providers':
        sys.exit(subprocess.call(workflow_argv('status', 1)))
    elif args.cmd=='report':
        sys.exit(subprocess.call(workflow_argv('report', args.activity)))
    elif args.cmd in ('disk', 'ask'):
        result=request('run', activity_id=args.activity, argv=workflow_argv(args.cmd, args.activity, getattr(args,'question',None)))
    elif args.cmd=='removed': result=request('removed_activities')
    elif args.cmd in ('remove','restore'): result=request(args.cmd+'_activity',activity_id=args.activity)
    elif args.cmd=='activities': result=request('snapshot')['activities']
    elif args.cmd=='create': result=request('create',name=args.name)
    elif args.cmd=='run':
        argv=args.argv[1:] if args.argv[:1]==['--'] else args.argv
        result=request('run',activity_id=args.activity,argv=argv)
    elif args.cmd=='jobs': result=[j for j in request('snapshot')['jobs'] if args.activity is None or j['activity_id']==args.activity]
    elif args.cmd=='stop': result=request('cancel',job_id=args.job)
    elif args.cmd=='history': result=request('history',activity_id=args.activity)
    elif args.cmd=='logs':
        offset=0
        while True:
            chunk=request('log',job_id=args.job,offset=offset)
            print(clean(chunk['text']),end='',flush=True)
            progressed=chunk['offset']!=offset;offset=chunk['offset']
            if progressed: continue
            if not args.follow: return
            job=next((j for j in request('snapshot')['jobs'] if j['id']==args.job),None)
            if not job or job['status'] not in LIVE: return
            time.sleep(.2)
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: pass
    except (OSError, RuntimeError, ValueError) as exc:
        print('Agent OS: '+clean(str(exc)),file=sys.stderr);sys.exit(1)
