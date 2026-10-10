"""Resume an approved existing operation once, using its original durable request."""
import json
import os
from pathlib import Path
import re
import tempfile
import time

def identity(value):return isinstance(value,str) and re.fullmatch('[0-9a-f]{32}',value) is not None

def read(path,limit=8*1024*1024):
    if path.is_symlink() or path.stat().st_size>limit:raise ValueError('Continuation record needs recovery')
    value=json.loads(path.read_text())
    if not isinstance(value,dict):raise ValueError('Invalid continuation record')
    return value

def save(path,value):
    fd,temporary=tempfile.mkstemp(prefix='.continuation-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o600);json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:Path(temporary).unlink(missing_ok=True)

def claim(directory,req,broker):
    activity=req.get('activity');ident=req.get('job_id')
    if type(activity) is not int or activity<=0 or not identity(ident):raise ValueError('Invalid approved operation')
    job=broker('poll',job_id=ident)
    origin=job.get('origin') or {};parent=origin.get('conversation_id')
    approved=job.get('approved_at')
    if (job.get('id')!=ident or job.get('activity')!=activity or type(job.get('approved_by_uid')) is not int or job['approved_by_uid']!=0
            or type(approved) not in (int,float) or not 0<=approved<=2**53 or not identity(parent)
            or job.get('status') not in ('starting','running','succeeded','failed','interrupted')):
        raise ValueError('This operation has no approved agent request to continue')
    directory=Path(directory);trace=read(directory/('agent-'+parent+'.json'))
    prompt=trace.get('request');generation=trace.get('generation')
    if (trace.get('id')!=parent or trace.get('activity')!=activity or not isinstance(prompt,str) or not 1<=len(prompt)<=4000
            or type(generation) is not int or generation<0):raise ValueError('Original request needs recovery before continuation')
    if not any(event.get('kind')=='tool' and isinstance(event.get('result'),dict) and event['result'].get('id')==ident
               and event['result'].get('status')=='approval_required' for event in trace.get('events',[]) if isinstance(event,dict)):
        raise ValueError('Approved operation was not observed in its original request')
    if broker('activity_state',activity=activity)['generation']!=generation:raise ValueError('Activity was stopped; enter a fresh request')
    if req.get('expected_generation',generation)!=generation:raise ValueError('Activity generation changed before continuation')
    marker=directory/('continuation-'+ident+'.json')
    if marker.exists() or marker.is_symlink():
        previous=read(marker,65536)
        if previous.get('job_id')!=ident or previous.get('parent_trace')!=parent:raise ValueError('Continuation record needs recovery')
        return {'existing':previous}
    record={'job_id':ident,'parent_trace':parent,'activity':activity,'core_job_id':req.get('core_job_id'),'status':'claimed','at':time.time()}
    # The assistant is serial. This fsynced claim precedes inference; a crash never replays it.
    save(marker,record)
    fields={key:job.get(key) for key in ('id','activity','argv','status','exit_code','created_at','finished_at','approved_at','approved_by_uid','stdin_sha256','stdin_bytes')}
    return {'prompt':prompt,'generation':generation,'parent_trace':parent,'job_id':ident,'observation':fields,'marker':marker,'record':record}

def finish(continuation,status,trace_id):
    save(continuation['marker'],{**continuation['record'],'status':status,'trace_id':trace_id,'finished_at':time.time()})
