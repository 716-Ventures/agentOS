"""Versioned agent memory and skills; content is reference data, never authority."""
import datetime
import json
from pathlib import Path
import re
import threading

PATH=Path('/var/lib/agent-os-ai/knowledge.json')
LOCK=threading.RLock()

def load():
    try:return json.loads(PATH.read_text())
    except FileNotFoundError:return {}

def operate(op, activity=None, **args):
    with LOCK:
        data=load()
        if op=='list':
            return [{'key':key,**{k:rows[-1][k] for k in ('kind','title','revision','basis','updated_at','archived')}} for key,rows in data.items()]
        key=args.get('key','')
        if not isinstance(key,str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}',key):raise ValueError('Use a short lowercase knowledge key')
        versions=data.get(key,[])
        if op=='read':return versions[-1] if versions else {'missing':True,'revision':0}
        if op=='history':return versions
        if op not in ('save','restore','archive'):raise ValueError('Unknown knowledge operation')
        revision=versions[-1]['revision'] if versions else 0
        if type(args.get('expected_revision')) is not int or args['expected_revision']!=revision:raise ValueError('Knowledge changed; read its current revision first')
        if op=='restore':
            source=next((r for r in versions if r['revision']==args.get('revision')),None)
            if not source:raise ValueError('Unknown revision')
            record={**source,'archived':False}
        elif op=='archive':
            if not versions:raise ValueError('Unknown entry')
            record={**versions[-1],'archived':True}
        else:
            if args.get('kind') not in ('memory','skill') or args.get('basis') not in ('user_preference','observed','inferred'):raise ValueError('Invalid knowledge kind or basis')
            for name,limit in [('title',160),('content',12000),('source',2000)]:
                if not isinstance(args.get(name),str) or not 1<=len(args[name])<=limit:raise ValueError('Invalid '+name)
            if re.search(r'(?i)(-----BEGIN .*PRIVATE KEY-----|Bearer\s+[A-Za-z0-9._-]{16,}|sk-[A-Za-z0-9_-]{20,})',args['content']):raise ValueError('Do not save credential material in knowledge')
            record={k:args[k] for k in ('kind','title','content','basis','source')}
            record['archived']=False
        if not versions and len(data)>=200:raise ValueError('Knowledge capacity reached; consolidate existing entries')
        record.update(revision=revision+1,activity=activity,updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),authority='reference_only')
        data[key]=[*versions,record]
        tmp=PATH.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2));tmp.chmod(0o600);tmp.replace(PATH)
        return {'key':key,**record}

def context():
    entries=load()
    # Bound context; the agent can read full entries through tools.
    return [{'key':key,**{k:rows[-1][k] for k in ('kind','title','revision','basis')},'excerpt':rows[-1]['content'][:700]} for key,rows in list(entries.items())[-60:] if not rows[-1]['archived']]
