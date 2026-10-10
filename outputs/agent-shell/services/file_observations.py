"""Durable metadata from completed, assessed file-helper operations; no content collection."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import uuid

HELPER='/usr/local/lib/agent-os/services/files.py'
LOCK=threading.RLock()
FIELDS={'path','kind','size_bytes','modified_at','mode','measured_at'}


def valid(values):
    try:
        if not isinstance(values,dict) or set(values)!=FIELDS:return False
        path=values['path']
        if not isinstance(path,str) or not path.startswith('/') or '\0' in path or len(path.encode())>4096:return False
        if values['kind'] not in ('file','directory','symlink','other','missing','unavailable'):return False
        if values['size_bytes'] is not None and (type(values['size_bytes']) is not int or not 0<=values['size_bytes']<=2**63-1):return False
        if values['mode'] is not None and (type(values['mode']) is not int or not 0<=values['mode']<=0o7777):return False
        for key in ('modified_at','measured_at'):
            value=values[key]
            if value is None and key=='modified_at':continue
            if type(value) not in (float,int) or not math.isfinite(value):return False
        return values['measured_at']>=0
    except (UnicodeError,TypeError,ValueError,OverflowError):return False


def record_valid(record):
    return (isinstance(record,dict) and record.get('format')==1 and type(record.get('activity')) is int and record['activity']>0
            and re.fullmatch('file:[0-9a-f]{32}',str(record.get('source',''))) is not None
            and type(record.get('source_revision')) is int and 0<=record['source_revision']<2**63 and valid(record.get('values')))


class FileObservations:
    def __init__(self,directory,publisher):self.directory=Path(directory);self.publisher=publisher
    def completed(self,job):
        argv=job.get('argv',[])
        if (job.get('status')!='succeeded' or job.get('exit_code')!=0 or job.get('output_truncated') or job.get('terminal')
                or len(argv) not in (3,4) or argv[:2]!=['/usr/bin/python3',HELPER]):return None
        descriptor=json.loads(argv[-1])
        if not isinstance(descriptor,dict) or descriptor.get('op') not in ('read','list','write'):return None
        if len(argv)==4 and (argv[2]!='--stdin-content' or descriptor['op']!='write'):return None
        if len(argv)==3 and descriptor['op']=='write':return None
        path=self.directory.parent/(job['id']+'.log')
        with path.open('rb') as stream:data=stream.read(1024*1024+1)
        if len(data)>1024*1024:return None
        result=json.loads(data)
        if not isinstance(result,dict) or not valid(result.get('metadata')):return None
        return self.save(job['activity'],result['metadata'])
    def save(self,activity,values):
        with LOCK:return self._save(activity,values)
    def _save(self,activity,values):
        if type(activity) is not int or activity<=0 or not valid(values):raise ValueError('Invalid file metadata observation')
        self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.directory.is_symlink():raise ValueError('Invalid file observation directory')
        self.directory.chmod(0o700)
        key=hashlib.sha256((str(activity)+'\0'+values['path']).encode()).hexdigest();path=self.directory/(key+'.json')
        previous=None
        if path.is_symlink():raise ValueError('Invalid stored file observation')
        if path.exists():
            if path.is_symlink() or path.stat().st_size>128*1024:raise ValueError('Invalid stored file observation')
            previous=json.loads(path.read_text())
            if not record_valid(previous) or previous['activity']!=activity or previous['values']['path']!=values['path']:raise ValueError('Stored file observation needs recovery')
        if previous and previous['source_revision']==2**63-1:raise ValueError('File observation revision exhausted')
        record={'format':1,'source':previous['source'] if previous else 'file:'+uuid.uuid4().hex,'activity':activity,
                'source_revision':previous['source_revision']+1 if previous else 1,'values':dict(values)}
        fd,temporary=tempfile.mkstemp(prefix='.observation-',dir=self.directory)
        try:
            with os.fdopen(fd,'w') as stream:
                os.fchmod(stream.fileno(),0o600);json.dump(record,stream);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path)
            parent=os.open(self.directory,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(parent)
            finally:os.close(parent)
        finally:Path(temporary).unlink(missing_ok=True)
        self.publisher.mark_file(record);return record['source']
    def recover(self):
        for path in sorted(self.directory.glob('*.json')):
            try:
                if path.is_symlink() or path.stat().st_size>128*1024:continue
                record=json.loads(path.read_text())
                if record_valid(record):self.publisher.mark_file(record)
            except (OSError,ValueError,TypeError):continue
