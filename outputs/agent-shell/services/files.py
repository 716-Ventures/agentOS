#!/usr/bin/python3
"""Filesystem primitives for OS-wide guarded reads and edits."""
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

BACKUPS=Path('/var/lib/agent-os-file-backups')


def run(req):
    path=Path(req['path'])
    if not path.is_absolute():path=Path.cwd()/path
    op=req['op']
    if op=='list':
        rows=[]
        with os.scandir(path) as entries:
            for e in entries:
                if len(rows)>=200:break
                s=e.stat(follow_symlinks=False)
                rows.append({'name':e.name,'directory':e.is_dir(follow_symlinks=False),'symlink':e.is_symlink(),'size_bytes':s.st_size})
        return {'path':str(path),'entries':rows,'limit':200}
    if op=='read':
        if not path.exists():return {'path':str(path),'exists':False,'expected_sha256':'missing','note':'For a new file, write_file expected_sha256 must be the literal string missing.'}
        with path.open('rb') as f:
            if not __import__('stat').S_ISREG(os.fstat(f.fileno()).st_mode):raise ValueError('Use execute for non-regular files')
            data=f.read(65537)
        return {'path':str(path),'content':data[:65536].decode('utf-8','replace'), 'truncated':len(data)>65536,
                'sha256':hashlib.sha256(data).hexdigest() if len(data)<=65536 else None}
    if op=='write':
        target=path.resolve()
        if target.exists():
            with target.open('rb') as f:old=f.read(65537)
            if len(old)>65536:raise ValueError('File too large for recoverable edit')
            digest=hashlib.sha256(old).hexdigest()
        else:old=None;digest='missing'
        if req.get('expected_sha256')!=digest:
            raise ValueError('This file does not exist. To create it, pass expected_sha256 as the literal string missing; do not hash the new content.' if old is None else 'File changed; read it again and use the returned current-file sha256, not the hash of your new content.')
        content=req['content'].encode()
        if len(content)>65536:raise ValueError('Content too large')
        backup=None
        if old is not None:
            directory=BACKUPS;directory.mkdir(mode=0o700,exist_ok=True)
            backup=directory/uuid.uuid4().hex
            with backup.open('xb') as f:f.write(old)
        temporary=target.with_name('.agent-edit-'+uuid.uuid4().hex)
        with temporary.open('xb') as f:f.write(content);f.flush();os.fsync(f.fileno())
        if target.exists():
            original=target.stat()
            os.chmod(temporary,original.st_mode & 0o777)
            os.chown(temporary,original.st_uid,original.st_gid)
        temporary.replace(target)
        return {'path':str(target),'sha256':hashlib.sha256(content).hexdigest(),'backup':str(backup) if backup else None}
    raise ValueError('Unknown file operation')

if __name__=='__main__':
    try:print(json.dumps(run(json.loads(sys.argv[1]))))
    except (OSError,ValueError,KeyError) as exc:
        print(json.dumps({'error':str(exc)}));sys.exit(1)
