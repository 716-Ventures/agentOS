#!/usr/bin/python3
"""General execution broker. Only this trusted service talks to systemd as root."""
import json
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
from common import listen, read_line, send
from effects import assess

SOCKET = '/run/agent-os-broker/api.sock'
STATE = Path('/var/lib/agent-os-broker')
WORK = Path('/var/lib/agent-os-workspaces')
LOCK = threading.RLock()
LIMIT = 256 * 1024
JOBS = {}


def persist(job):
    p = STATE / (job['id']+'.json')
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(job, indent=2)+'\n')
    tmp.replace(p)


def workspace(activity):
    if type(activity) is not int or not 1 <= activity <= 2147483647:
        raise ValueError('Invalid activity id')
    path = WORK / str(activity)
    path.mkdir(mode=0o700, exist_ok=True)
    return str(path)


def validate(req):
    argv = req.get('argv')
    if (not isinstance(argv, list) or not 1 <= len(argv) <= 128 or
        any(not isinstance(a, str) or '\0' in a or len(a) > 32000 for a in argv)
        or not argv[0].startswith('/')):
        raise ValueError('argv must contain an absolute executable and at most 128 bounded text arguments')
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
    props = ['Type=exec', 'KillMode=control-group', 'TimeoutStopSec=2',
             f"RuntimeMaxSec={job['timeout_seconds']}", 'MemoryMax=256M', 'TasksMax=64',
             'UMask=0077', 'StandardInput=null']
    # All assessed actions operate on the Linux OS with system authority.
    props += ['User=root', 'Group=root']
    command = ['/usr/bin/systemd-run', '--quiet', '--wait', '--pipe', '--collect',
               '--unit=agent-os-exec-'+ident, '--working-directory='+job.get('cwd',job['workspace']),
               '--setenv=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               '--setenv=LANG=C.UTF-8', '--setenv=HOME='+job['workspace']]
    for prop in props: command += ['--property='+prop]
    command += ['--', *job['argv']]
    try:
        with LOCK:
            # Starting while holding the lock makes a concurrent cancellation observe a launched request.
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    env={'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8'})
            job['status'] = 'running'; persist(job)
        count = 0
        with (STATE / (ident+'.log')).open('wb') as f:
            while True:
                data = proc.stdout.read1(4096)
                if not data: break
                take = min(len(data), max(0,LIMIT-count))
                if take: f.write(data[:take]); f.flush(); count += take
                if take < len(data):
                    with LOCK: job['output_truncated'] = True
        code = proc.wait()
        with LOCK:
            job['exit_code'] = code
            job['status'] = 'cancelled' if job.get('cancel_requested') else ('succeeded' if code == 0 else 'failed')
    except OSError:
        with LOCK: job.update(status='failed', error='Could not start or supervise command')
    finally:
        with LOCK:
            job['finished_at'] = time.time(); persist(job)


def start(job):
    if sum(j['status'] in ('starting','running','cancelling') for j in JOBS.values()) >= 4:
        raise ValueError('Four broker jobs are active; wait or stop one')
    job['status'] = 'starting'; persist(job)
    threading.Thread(target=launch, args=(job,), daemon=True).start()


def view(job, offset=0):
    result = dict(job)
    p = STATE / (job['id']+'.log')
    if p.exists():
        with p.open('rb') as f:
            f.seek(offset); data = f.read(32768)
        result.update(output=data.decode('utf-8','replace'), next_offset=offset+len(data))
    else: result.update(output='', next_offset=offset)
    return result


def handle(req, uid):
    op = req.get('op')
    with LOCK:
        if op == 'list':
            activity = req.get('activity')
            return [dict(j) for j in sorted(JOBS.values(),key=lambda j:j['created_at'],reverse=True)
                    if activity is None or j['activity']==activity][:100]
        if op in ('execute','preview'):
            argv, timeout, scope, purpose = validate(req)
            path = workspace(req.get('activity'))
            cwd=req.get('cwd',path)
            if not isinstance(cwd,str):raise ValueError('cwd must be a directory')
            cwd=str((Path(path)/cwd).resolve())
            if not Path(cwd).is_dir():raise ValueError('Working directory does not exist')
            policy=assess(argv,scope)
            deterministic_harm=policy['decision']=='approve'
            if policy['decision']=='inspect' or (deterministic_harm and req.get('current_request')):
                LOCK.release()
                try:
                    completed=subprocess.run(['/usr/sbin/runuser','-u','agentos-ai','-g','agentos','-G','agentos-ai','--',
                        '/usr/bin/python3','/usr/local/lib/agent-os/services/assess_action.py'],
                        input=json.dumps({'argv':policy['argv'],'scope':scope,'cwd':cwd,'background':req.get('background',False),
                            'lifetime_seconds':timeout,'purpose_untrusted':purpose,'current_request':str(req.get('current_request',''))[:4000],
                            'evidence_untrusted':str(req.get('evidence',''))[:8000],
                            'conversation_context':req.get('conversation_context',[]),
                            'authority':'Linux guest root with full OS access. Activity directory is only a default cwd, not a filesystem boundary.'}),
                        text=True,capture_output=True,timeout=18)
                    try:assessment=json.loads(completed.stdout) if completed.returncode==0 else {}
                    except ValueError:assessment={}
                except (OSError,subprocess.TimeoutExpired):
                    assessment={}
                finally:
                    LOCK.acquire()
                if not isinstance(assessment,dict):assessment={}
                if req.get('current_request') and assessment.get('task_fit')!='aligned':
                    return {'status':'outside_request','next_step':'This action is not established as part of the current request. Research and answer the question instead of changing state; clarify only if needed. This is not a permissions restriction.','assessment':assessment}
                policy['assessment']=assessment
                routine=(not deterministic_harm and assessment.get('status')=='available' and assessment.get('risk')=='routine'
                    and type(assessment.get('confidence')) in (int,float) and .8<=assessment['confidence']<=1)
                authorized=(bool(req.get('current_request')) and assessment.get('status')=='available'
                    and assessment.get('risk') in ('routine','harmful')
                    and assessment.get('task_fit')=='aligned'
                    and type(assessment.get('task_fit_confidence')) in (int,float) and .8<=assessment['task_fit_confidence']<=1
                    and assessment.get('authorization')=='explicit'
                    and type(assessment.get('authorization_confidence')) in (int,float)
                    and .6<=assessment['authorization_confidence']<=1)
                if authorized:
                    policy['authorization']={'source':'current_user_request','request':req['current_request'],
                        'context':req.get('conversation_context',[]),'argv':policy['argv'],'cwd':cwd}
                policy.update(decision='allow' if routine or authorized else 'approve' if deterministic_harm or assessment.get('risk')=='harmful' or req.get('request_confirmation') is True else 'inspect',effect='assessed_routine' if routine else 'potential_harm',
                    reason='The current user instruction explicitly authorizes this exact action and its effects.' if authorized else 'Jev assessed this exact action as routine; execution uses supervised OS-level authority.' if routine else
                    'This action may have harmful effects or its material effects remain uncertain. Inspect further or obtain confirmation for this exact action.')
            if op=='preview':return policy
            if policy['decision']=='inspect':
                return {'status':'inspection_required','policy':policy,'authority':'root; full Linux OS access','next_step':'Assessment is inconclusive, not a permissions failure. Inspect effects or simplify the plan and reassess. If material uncertainty remains, request_confirmation=true creates a human-review proposal for this exact action.'}
            original_argv=argv
            argv,scope=policy['argv'],policy['scope']
            # Reuse exact proposals, preserving identity across retries and consent.
            matches=[j for j in JOBS.values() if j['activity']==req['activity'] and j['argv']==argv
                and j.get('cwd',j['workspace'])==cwd and j.get('background',False)==req.get('background',False)
                and j['timeout_seconds']==timeout and j['scope']==scope and j['status']=='approval_required']
            if matches:
                existing=min(matches,key=lambda j:j['created_at'])
                for duplicate in matches:
                    if duplicate is not existing:
                        duplicate.update(status='superseded',superseded_by=existing['id']);persist(duplicate)
                if policy['decision']=='allow':
                    existing['policy']=policy
                    start(existing)
                return view(existing)
            if req.get('background',False):
                for existing in JOBS.values():
                    if existing['activity']==req['activity'] and existing['argv']==argv and existing.get('cwd',existing['workspace'])==cwd and existing['status'] in ('starting','running'):
                        return view(existing)
            job = {'id':uuid.uuid4().hex, 'activity':req['activity'], 'argv':argv,
                   'timeout_seconds':timeout, 'scope':scope, 'purpose':purpose, 'workspace':path, 'cwd':cwd, 'background':req.get('background',False),
                   'policy':policy,'requested_argv':original_argv,'requested_by_uid':uid, 'created_at':time.time(), 'exit_code':None,
                   'status':'approval_required' if policy['decision']=='approve' else 'starting'}
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
        if op == 'poll':
            offset=req.get('offset',0)
            if type(offset) is not int or not 0 <= offset <= LIMIT: raise ValueError('Invalid offset')
            return view(job, offset)
        if op == 'approve':
            if uid != 0: raise ValueError('Only a local administrator may approve system operations')
            if job['status'] != 'approval_required': raise ValueError('This operation is not awaiting approval')
            if job['scope']!='system':raise ValueError('This proposal used the retired restricted authority. Reassess it with current OS authority before approval.')
            job['approved_by_uid']=uid; job['approved_at']=time.time(); start(job)
            return view(job)
        if op == 'cancel':
            if job['status']=='approval_required':
                job['status']='rejected';persist(job)
            elif job['status'] in ('starting','running','cancelling'):
                job['cancel_requested']=True; job['status']='cancelling';persist(job)
                threading.Thread(target=stop_unit,args=(job,),daemon=True).start()
            return view(job)
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


def main():
    for p in STATE.glob('*.json'):
        job=json.loads(p.read_text())
        if job['status'] in ('starting','running','cancelling'):
            subprocess.run(['/usr/bin/systemctl','stop','agent-os-exec-'+job['id']+'.service'],capture_output=True,timeout=10)
            job.update(status='interrupted',error='Broker restarted; operation was not replayed');persist(job)
        JOBS[job['id']]=job
    server=listen(SOCKET)
    while True:
        conn,_=server.accept()
        threading.Thread(target=serve,args=(conn,),daemon=True).start()

if __name__=='__main__':main()
