#!/usr/bin/python3
"""General execution broker. Only this trusted service talks to systemd as root."""
import json
import select
import terminal_sessions
from source_publisher import BrokerSources
from file_observations import FileObservations
import codecs
import math
import hashlib
import os
from pathlib import Path
import pwd
import re
import socket
import struct
import subprocess
import threading
import time
import uuid
from common import BROKER_INPUT_LIMIT, BROKER_OUTPUT_LIMIT, listen, read_line, send
from effects import assess

SOCKET = '/run/agent-os-broker/api.sock'
STATE = Path('/var/lib/agent-os-broker')
WORK = Path('/var/lib/agent-os-workspaces')
LOCK = threading.RLock()
LIMIT = BROKER_OUTPUT_LIMIT
JOBS = {}
EPOCH=uuid.uuid4().hex
REVISION=0
SOURCES = BrokerSources()


def confident(value, threshold):
    return type(value) in (int, float) and math.isfinite(value) and threshold <= value <= 1


def persist(job):
    global REVISION
    job['source_revision']=job.get('source_revision',0)+1
    p = STATE / (job['id']+'.json')
    tmp = p.with_suffix('.tmp')
    with tmp.open('w') as stream:
        os.fchmod(stream.fileno(),0o600);stream.write(json.dumps(job,indent=2)+'\n');stream.flush();os.fsync(stream.fileno())
    tmp.replace(p)
    fd=os.open(STATE,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    REVISION+=1
    SOURCES.mark(job)


def workspace(activity):
    if type(activity) is not int or not 1 <= activity <= 2147483647:
        raise ValueError('Invalid activity id')
    path = WORK / str(activity)
    path.mkdir(mode=0o700, exist_ok=True)
    return str(path)


def activity_generation(activity):
    if type(activity) is not int or not 1 <= activity <= 2147483647:
        raise ValueError('Invalid activity id')
    path=STATE / f'activity-{activity}.generation'
    return int(path.read_text()) if path.exists() else 0


def cancel_job(job):
    if job['status']=='approval_required':
        job.update(status='rejected',finished_at=time.time());persist(job)
    elif job['status'] in ('starting','running','cancelling'):
        job['cancel_requested']=True; job['status']='cancelling';persist(job)
        threading.Thread(target=stop_unit,args=(job,),daemon=True).start()
    return view(job)


def validate(req):
    argv = req.get('argv')
    if (not isinstance(argv, list) or not 1 <= len(argv) <= 128 or
        any(not isinstance(a, str) or '\0' in a or len(a) > 32000 for a in argv)
        or not argv[0].startswith('/')):
        raise ValueError('argv must contain an absolute executable and at most 128 bounded text arguments')
    if 'stdin' in req:
        content=req['stdin']
        if not isinstance(content,str):raise ValueError('stdin must be UTF-8 text')
        try: size=len(content.encode('utf-8'))
        except UnicodeEncodeError:raise ValueError('stdin must be UTF-8 text') from None
        if size>BROKER_INPUT_LIMIT:raise ValueError('stdin exceeds the 64 KiB input limit')
    terminal=req.get('terminal',False)
    if type(terminal) is not bool:raise ValueError('terminal must be boolean')
    if terminal:
        if 'stdin' in req:raise ValueError('Terminal sessions cannot use stored stdin')
        terminal_sessions.dimensions(req.get('rows',24),req.get('cols',80))
    background=req.get('background',False)
    if type(background) is not bool:raise ValueError('background must be boolean')
    timeout = req.get('lifetime_seconds',86400) if background else req.get('timeout_seconds',30)
    if type(timeout) is not int or not 1 <= timeout <= (86400 if background else 600):
        raise ValueError('Use a bounded lifetime: at most 600 seconds, or 86400 for background work')
    # Legacy clients may still send workspace; it no longer limits authority.
    if req.get('scope','system') not in ('workspace','system'):raise ValueError('Invalid authority scope')
    scope = 'system'
    purpose = req.get('purpose', '')
    if not isinstance(purpose, str) or not 1 <= len(purpose) <= 1000:
        raise ValueError('Describe the purpose in 1–1000 characters')
    return argv, timeout, scope, purpose


def launch(job):
    ident = job['id']
    content=job.get('stdin')
    terminal=job.get('terminal',False)
    proc=None
    terminal_socket=terminal_exit=None
    decoder=terminal_sessions.ControlOutput() if terminal else None
    props = ['Type=exec', 'KillMode=control-group', 'TimeoutStopSec=2',
             f"RuntimeMaxSec={job['timeout_seconds']}", 'MemoryMax=256M', 'TasksMax=64',
             'UMask=0077']
    if content is None and not terminal:props.append('StandardInput=null')
    # All assessed actions operate on the Linux OS with system authority.
    props += ['User=root', 'Group=root']
    command = ['/usr/bin/systemd-run', '--quiet', '--wait', '--pipe', '--collect',
               '--unit=agent-os-exec-'+ident, '--working-directory='+job.get('cwd',job['workspace']),
               '--setenv=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               '--setenv=LANG=C.UTF-8', '--setenv=HOME='+job['workspace']]
    if terminal:command += ['--setenv=TERM=xterm-256color']
    for prop in props: command += ['--property='+prop]
    try:
        argv=job['argv']
        if terminal:terminal_socket,terminal_exit,argv=terminal_sessions.command(job,STATE)
        command += ['--', *argv]
        with LOCK:
            if job.get('cancel_requested'):
                job['status'] = 'cancelled'
                return
            # Starting while holding the lock makes a concurrent cancellation observe a launched request.
            proc = subprocess.Popen(command, stdin=subprocess.PIPE if content is not None or terminal else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    env={'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8'})
            if terminal:terminal_sessions.register(ident,proc,terminal_socket,job['rows'],job['cols'])
            job['status'] = 'running'; persist(job)
        if content is not None:
            # Feed while draining output: a child may write before reading stdin.
            def feed():
                try:
                    proc.stdin.write(content.encode('utf-8'))
                    proc.stdin.flush()
                except (BrokenPipeError,OSError):
                    pass
                finally:
                    try:proc.stdin.close()
                    except (BrokenPipeError,OSError):pass
            threading.Thread(target=feed,daemon=True).start()
        count = 0
        with (STATE / (ident+'.log')).open('wb') as f:
            while True:
                if terminal:
                    if not select.select([proc.stdout],[],[],.1)[0]:
                        if terminal_exit.exists():
                            subprocess.run(['/usr/bin/tmux','-S',str(terminal_socket),'kill-server'],
                                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3)
                        if proc.poll() is not None:break
                        continue
                data=proc.stdout.read1(4096)
                if not data:break
                if terminal:
                    data=decoder.feed(data)
                    if not data:continue
                take = min(len(data), max(0,LIMIT-count))
                if take: f.write(data[:take]); f.flush(); count += take
                if take < len(data):
                    with LOCK: job['output_truncated'] = True
        code = proc.wait()
        if terminal and terminal_exit.exists():
            status,sig=terminal_exit.read_text().split(':')
            code=int(status) if status else 128+int(sig) if sig else code
        with LOCK:
            job['exit_code'] = code
            job['status'] = 'cancelled' if job.get('cancel_requested') else ('succeeded' if code == 0 else 'failed')
    except OSError:
        with LOCK: job.update(status='failed', error='Could not start or supervise command')
    finally:
        with LOCK:
            if terminal:terminal_sessions.finish(ident)
            if proc is not None:
                if proc.stdout is not None:proc.stdout.close()
                if terminal and proc.stdin is not None:proc.stdin.close()
            job['finished_at'] = time.time()
            try:
                source=FileObservations(STATE/'file-observations',SOURCES).completed(job)
                if source:job['file_source']=source
            except (OSError,ValueError,KeyError,TypeError):job['metadata_observation_unavailable']=True
            persist(job)


def checked_input(job):
    content=job.get('stdin')
    if content is None:
        if job.get('stdin_sha256') is not None or job.get('stdin_bytes',0)!=0:raise ValueError('Stored operation input is inconsistent; reassess this operation')
        return None
    if not isinstance(content,str):raise ValueError('Stored operation input is invalid')
    raw=content.encode('utf-8')
    if len(raw)>BROKER_INPUT_LIMIT or job.get('stdin_bytes')!=len(raw) or job.get('stdin_sha256')!=hashlib.sha256(raw).hexdigest():
        raise ValueError('Stored operation input changed; reassess this operation')
    return content


def start(job):
    checked_input(job)
    if sum(j['status'] in ('starting','running','cancelling') for j in JOBS.values()) >= 4:
        raise ValueError('Four broker jobs are active; wait or stop one')
    job['status'] = 'starting'; persist(job)
    threading.Thread(target=launch, args=(job,), daemon=True).start()


def view(job, offset=0):
    result = {k:v for k,v in job.items() if k!='stdin'}
    p = STATE / (job['id']+'.log')
    if p.exists():
        with p.open('rb') as f:
            f.seek(offset); data = f.read(32768)
        # Keep an incomplete UTF-8 suffix for the next byte-offset poll. Decoding
        # each page independently otherwise corrupts valid multibyte characters.
        final = job['status'] not in ('starting', 'running', 'cancelling') and offset + len(data) >= p.stat().st_size
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        output = decoder.decode(data, final=final)
        pending = decoder.getstate()[0]
        result.update(output=output, next_offset=offset+len(data)-len(pending),has_more=offset+len(data)-len(pending)<p.stat().st_size)
    else: result.update(output='', next_offset=offset,has_more=False)
    return result


def list_page(req):
    activity=req.get('activity')
    if activity is not None and (type(activity) is not int or activity<=0):raise ValueError('Invalid activity filter')
    limit=req.get('limit',32)
    if type(limit) is not int or not 1<=limit<=64:raise ValueError('Page size must be between 1 and 64')
    before=req.get('before')
    if before is not None:
        if (not isinstance(before,list) or len(before)!=2 or type(before[0]) not in (float,int) or not 0<=before[0]<=2**53
                or not isinstance(before[1],str) or not re.fullmatch('[0-9a-f]{32}',before[1])):raise ValueError('Invalid broker page cursor')
        before=tuple(before)
    revision=EPOCH+':'+str(REVISION)
    if 'expected_revision' in req and req['expected_revision']!=revision:raise ValueError('resync_required: Broker metadata changed while reading pages')
    selected=sorted((job for job in JOBS.values() if (activity is None or job['activity']==activity) and (before is None or (job['created_at'],job['id'])<before)),key=lambda job:(job['created_at'],job['id']),reverse=True)
    recent_only=req.get('recent_only',False)
    if type(recent_only) is not bool:raise ValueError('Invalid recent-work filter')
    if recent_only:
        recent={job['id'] for job in sorted((job for job in JOBS.values() if activity is None or job['activity']==activity),key=lambda job:(job['created_at'],job['id']),reverse=True)[:100]}
        selected=[job for job in selected if job['id'] in recent or job['status'] in ('starting','running','cancelling','approval_required')]
    fields=('id','activity','argv','cwd','scope','purpose','timeout_seconds','background','terminal','rows','cols','status','exit_code','created_at','finished_at','error','stdin_sha256','stdin_bytes','source_revision','origin','file_source','metadata_observation_unavailable')
    rows=[];size=256;more=False
    for job in selected:
        row={key:job[key] for key in fields if key in job}
        row['policy']={key:job.get('policy',{}).get(key) for key in ('decision','reason')}
        encoded=len(json.dumps(row,ensure_ascii=True,allow_nan=False).encode())+2
        if len(rows)>=limit or size+encoded>448*1024:
            if not rows:raise ValueError('Broker metadata record exceeds page limit; inspect this job separately')
            more=True;break
        rows.append(row);size+=encoded
    return {'revision':revision,'jobs':rows,'next_before':[rows[-1]['created_at'],rows[-1]['id']] if more else None}


def same_operation(job, activity, argv, cwd, background, timeout, scope, stdin_sha256=None, terminal=False):
    """Deduplication must preserve the requested execution contract."""
    return (job['activity'] == activity and job['argv'] == argv
            and job.get('cwd', job['workspace']) == cwd
            and job.get('background', False) == background
            and job['timeout_seconds'] == timeout and job['scope'] == scope
            and job.get('stdin_sha256') == stdin_sha256
            and job.get('terminal',False) == terminal)


def human_terminal_user(uid):
    # Interactive input grants arbitrary effects beyond the initially assessed argv.
    # Keep that channel out of the credential-owning AI and core service identities.
    user=pwd.getpwuid(uid)
    if uid!=0 and (uid<1000 or user.pw_name in ('agentos','agentos-ai')):
        raise ValueError('Interactive terminals require a local human login')


def handle(req, uid):
    op = req.get('op')
    with LOCK:
        terminal_sessions.reap_expired()
        if op == 'activity_state':
            return {'generation':activity_generation(req.get('activity'))}
        if op == 'stop_activity':
            activity=req.get('activity');generation=activity_generation(activity)+1
            path=STATE / f'activity-{activity}.generation'
            tmp=path.with_suffix('.tmp');tmp.write_text(str(generation));tmp.replace(path)
            affected=[cancel_job(j) for j in JOBS.values() if j['activity']==activity
                      and j['status'] in ('starting','running','cancelling','approval_required')]
            return {'activity':activity,'generation':generation,'jobs':affected}
        if op == 'list.page':return list_page(req)
        if op == 'list':
            activity = req.get('activity')
            selected=sorted((j for j in JOBS.values() if activity is None or j['activity']==activity),
                            key=lambda j:j['created_at'],reverse=True)
            recent={j['id'] for j in selected[:100]}
            return [{k:v for k,v in j.items() if k!='stdin'} for j in selected
                    if j['id'] in recent or j['status'] in ('starting','running','cancelling','approval_required')]
        if op in ('execute','preview'):
            argv, timeout, scope, purpose = validate(req)
            if req.get('terminal'):human_terminal_user(uid)
            generation=activity_generation(req.get('activity'))
            expected=req.get('expected_generation',generation)
            if type(expected) is not int or expected!=generation:
                raise ValueError('Activity work was stopped; start a new request before launching more work')
            origin=req.get('origin')
            if origin is not None:
                if (not isinstance(origin,dict) or set(origin)-{'conversation_id','core_job_id'}
                    or not isinstance(origin.get('conversation_id'),str)
                    or not re.fullmatch('[a-f0-9]{32}',origin['conversation_id'])
                    or (origin.get('core_job_id') is not None and
                        (type(origin['core_job_id']) is not int or origin['core_job_id']<=0))):
                    raise ValueError('Invalid job origin')
            content=req.get('stdin')
            input_hash=hashlib.sha256(content.encode('utf-8')).hexdigest() if content is not None else None
            path = workspace(req.get('activity'))
            cwd=req.get('cwd',path)
            if not isinstance(cwd,str):raise ValueError('cwd must be a directory')
            cwd=str((Path(path)/cwd).resolve())
            if not Path(cwd).is_dir():raise ValueError('Working directory does not exist')
            policy=assess(argv,scope)
            if req.get('terminal'):policy['interactive_input']='local_human_only; root authority'
            if content is not None:
                policy.update(stdin_sha256=input_hash,stdin_bytes=len(content.encode('utf-8')))
            deterministic_harm=policy['decision']=='approve'
            if policy['decision']=='inspect' or (deterministic_harm and req.get('current_request')):
                LOCK.release()
                try:
                    completed=subprocess.run(['/usr/sbin/runuser','-u','agentos-ai','-g','agentos','-G','agentos-ai','--',
                        '/usr/bin/python3','/usr/local/lib/agent-os/services/assess_action.py'],
                        input=json.dumps({'terminal':req.get('terminal',False),'stdin_untrusted':content,'stdin_sha256':input_hash,'argv':policy['argv'],'scope':scope,'cwd':cwd,'background':req.get('background',False),
                            'lifetime_seconds':timeout,'purpose_untrusted':purpose,'current_request':str(req.get('current_request',''))[:4000],
                            'evidence_untrusted':str(req.get('evidence',''))[:8000],
                            'conversation_context':req.get('conversation_context',[]),
                            'authority':'Linux guest root with full OS access. Activity directory is only a default cwd, not a filesystem boundary.'},ensure_ascii=False),
                        text=True,capture_output=True,timeout=18)
                    try:assessment=json.loads(completed.stdout) if completed.returncode==0 else {}
                    except ValueError:assessment={}
                except (OSError,subprocess.TimeoutExpired):
                    assessment={}
                finally:
                    LOCK.acquire()
                if not isinstance(assessment,dict):assessment={}
                if req.get('current_request') and assessment.get('status')=='available' and assessment.get('task_fit')=='beyond_request':
                    return {'status':'outside_request','next_step':'This action is not established as part of the current request. Research and answer the question instead of changing state; clarify only if needed. This is not a permissions restriction.','assessment':assessment}
                policy['assessment']=assessment
                policy['thresholds']={'routine':.8,'task_fit':.8,'authorization':.6,'calibration':'provisional; see labeled Jev evaluation'}
                aligned=(not req.get('current_request') or
                    (assessment.get('task_fit')=='aligned' and confident(assessment.get('task_fit_confidence'), .8)))
                routine=(not deterministic_harm and aligned and assessment.get('status')=='available' and assessment.get('risk')=='routine'
                    and confident(assessment.get('confidence'), .8))
                authorized=(bool(req.get('current_request')) and assessment.get('status')=='available'
                    and assessment.get('risk') in ('routine','harmful')
                    and assessment.get('task_fit')=='aligned'
                    and confident(assessment.get('task_fit_confidence'), .8)
                    and assessment.get('authorization')=='explicit'
                    and confident(assessment.get('authorization_confidence'), .6))
                if authorized:
                    policy['authorization']={'source':'current_user_request','request':req['current_request'],
                        'context':req.get('conversation_context',[]),'argv':policy['argv'],'cwd':cwd,'stdin_sha256':input_hash}
                policy.update(decision='allow' if routine or authorized else 'approve' if deterministic_harm or assessment.get('risk')=='harmful' or req.get('request_confirmation') is True else 'inspect',effect='assessed_routine' if routine else 'potential_harm',
                    reason='The current user instruction explicitly authorizes this exact action and its effects.' if authorized else 'Jev assessed this exact action as routine; execution uses supervised OS-level authority.' if routine else
                    'This action may have harmful effects or its material effects remain uncertain. Inspect further or obtain confirmation for this exact action.')
            # Assessment releases LOCK; a stop can revoke this request meanwhile.
            if activity_generation(req['activity'])!=generation:
                raise ValueError('Activity work was stopped during assessment; this action was not launched')
            if op=='preview':return policy
            if policy['decision']=='inspect':
                return {'status':'inspection_required','policy':policy,'authority':'root; full Linux OS access','next_step':'Assessment is inconclusive, not a permissions failure. Inspect effects or simplify the plan and reassess. If material uncertainty remains, request_confirmation=true creates a human-review proposal for this exact action.'}
            original_argv=argv
            argv,scope=policy['argv'],policy['scope']
            # Reuse exact proposals, preserving identity across retries and consent.
            matches=[j for j in JOBS.values() if j['status']=='approval_required'
                and same_operation(j, req['activity'], argv, cwd, req.get('background',False), timeout, scope, input_hash, req.get('terminal',False))]
            if matches:
                existing=min(matches,key=lambda j:j['created_at'])
                for duplicate in matches:
                    if duplicate is not existing:
                        duplicate.update(status='superseded',superseded_by=existing['id']);persist(duplicate)
                if policy['decision']=='allow':
                    existing['policy']=policy
                    start(existing)
                return view(existing)
            if req.get('background',False) and not req.get('terminal',False):
                for existing in JOBS.values():
                    if existing['status'] in ('starting','running') and same_operation(existing, req['activity'], argv, cwd, True, timeout, scope, input_hash, req.get('terminal',False)):
                        return view(existing)
            job = {'id':uuid.uuid4().hex, 'activity':req['activity'], 'argv':argv,
                   'timeout_seconds':timeout, 'scope':scope, 'purpose':purpose, 'workspace':path, 'cwd':cwd, 'background':req.get('background',False),
                   'policy':policy,'requested_argv':original_argv,'requested_by_uid':uid, 'created_at':time.time(), 'exit_code':None,
                   'status':'approval_required' if policy['decision']=='approve' else 'starting'}
            job['activity_generation']=generation
            if req.get('terminal'):
                job.update(terminal=True,rows=req.get('rows',24),cols=req.get('cols',80))
            if origin is not None:job['origin']=dict(origin)
            if content is not None:
                job.update(stdin=content,stdin_sha256=input_hash,stdin_bytes=len(content.encode('utf-8')))
            JOBS[job['id']] = job
            if policy['decision']=='approve': persist(job)
            else:
                try: start(job)
                except ValueError:
                    del JOBS[job['id']]; raise
            return view(job)
        ident = req.get('job_id')
        if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{32}',ident) or ident not in JOBS:
            raise ValueError('Unknown broker job')
        job = JOBS[ident]
        if 'expected_activity' in req and (type(req['expected_activity']) is not int or req['expected_activity']!=job['activity']):raise ValueError('Callback target changed activity')
        if 'expected_source_revision' in req and (type(req['expected_source_revision']) is not int or req['expected_source_revision']!=job.get('source_revision',0)):raise ValueError('Callback source changed; refresh before submitting')
        if isinstance(op,str) and op.startswith('terminal_'):
            human_terminal_user(uid)
            if not job.get('terminal'):raise ValueError('This job has no interactive terminal')
            if op in ('terminal_write','terminal_resize') and job['status']!='running':
                raise ValueError('Terminal is not running')
            return terminal_sessions.control(ident,req)
        if op == 'input':
            if uid != 0:raise ValueError('Only a local administrator may inspect stored input')
            return {'stdin':checked_input(job),'stdin_sha256':job.get('stdin_sha256'),'stdin_bytes':job.get('stdin_bytes',0)}
        if op == 'poll':
            offset=req.get('offset',0)
            if type(offset) is not int or not 0 <= offset <= LIMIT: raise ValueError('Invalid offset')
            return view(job, offset)
        if op == 'approve':
            if uid != 0: raise ValueError('Only a local administrator may approve system operations')
            if job['status'] != 'approval_required': raise ValueError('This operation is not awaiting approval')
            if job['scope']!='system':raise ValueError('This proposal used the retired restricted authority. Reassess it with current OS authority before approval.')
            start(job)
            job['approved_by_uid']=uid; job['approved_at']=time.time(); persist(job)
            return view(job)
        if op == 'cancel':return cancel_job(job)
        raise ValueError('Unknown broker operation')


def stop_unit(job):
    # Retry briefly if cancellation races systemd registering the transient unit.
    for _ in range(30):
        subprocess.run(['/usr/bin/systemctl','stop','agent-os-exec-'+job['id']+'.service'],
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        with LOCK:
            if job['status'] not in ('starting','running','cancelling'): return
        time.sleep(.1)


def serve(conn):
    with conn:
        conn.settimeout(5)
        try:
            uid=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
            with conn.makefile('rb') as f: req=read_line(f)
            result=handle(req,uid)
            send(conn,{'ok':True,'result':result})
        except (ValueError,OSError,KeyError,TypeError,subprocess.TimeoutExpired) as exc:
            try: send(conn,{'ok':False,'error':str(exc) if isinstance(exc,ValueError) else 'Broker request failed'})
            except OSError: pass


def recover_jobs():
    """Reconcile saved jobs before accepting new commands; never replay them."""
    recovered = {}
    for p in STATE.glob('*.json'):
        job = json.loads(p.read_text())
        if job['status'] in ('starting', 'running', 'cancelling'):
            unit = 'agent-os-exec-' + job['id'] + '.service'
            # A stop error can mean the collected unit is already gone. Inspect
            # systemd rather than treating either exit code as proof of completion.
            subprocess.run(['/usr/bin/systemctl', 'stop', unit], capture_output=True, timeout=10)
            result = subprocess.run(['/usr/bin/systemctl', 'show', unit,
                '--property=LoadState,ActiveState,MainPID,ControlPID,TasksCurrent,ControlGroup'],
                capture_output=True, text=True, timeout=10)
            state = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
            stopped = (state.get('ActiveState') in ('inactive', 'failed')
                       and state.get('MainPID') == '0' and state.get('ControlPID') == '0'
                       and (state.get('ControlGroup') == '' or state.get('TasksCurrent') == '0')
                       and (result.returncode == 0 or state.get('LoadState') == 'not-found'))
            if not stopped:
                raise RuntimeError('Broker recovery cannot confirm that ' + unit +
                    ' stopped. Saved status retained; new execution is unavailable until recovery succeeds.')
            job.update(status='interrupted', finished_at=time.time(),
                       error='Broker restarted; operation was stopped and was not replayed')
            persist(job)
        recovered[job['id']] = job
    JOBS.clear()
    JOBS.update(recovered)
    for job in recovered.values():SOURCES.mark(job)



def source_backfill():
    # Stream authoritative records after queue pressure; never retain a second unbounded queue.
    for directory,adapter in ((STATE,SOURCES.job_payload),(STATE/'file-observations',SOURCES.file_payload)):
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if not entry.name.endswith('.json') or not entry.is_file(follow_symlinks=False) or entry.stat().st_size>1024*1024:continue
                        with open(entry.path) as stream:record=json.load(stream)
                        payload=adapter(record)
                        if payload:yield payload
                    except (OSError,ValueError,KeyError,TypeError):continue
        except FileNotFoundError:continue


def main():
    SOURCES.replay=source_backfill
    recover_jobs()
    FileObservations(STATE/'file-observations',SOURCES).recover()
    SOURCES.start()
    def reap_terminals():
        while True:
            time.sleep(.5)
            with LOCK:terminal_sessions.reap_expired()
    threading.Thread(target=reap_terminals,daemon=True).start()
    server=listen(SOCKET)
    while True:
        conn,_=server.accept()
        threading.Thread(target=serve,args=(conn,),daemon=True).start()

if __name__=='__main__':main()
