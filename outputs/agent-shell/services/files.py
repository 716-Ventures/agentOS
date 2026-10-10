#!/usr/bin/python3
"""Filesystem primitives for OS-wide guarded reads and edits."""
from common import BROKER_INPUT_LIMIT
import hashlib
import fcntl
import json
import os
from pathlib import Path
import sys
import stat
import uuid
import time

BACKUPS=Path('/var/lib/agent-os-file-backups')


def read_regular(path):
    # Opening a FIFO must not hang the service before its type can be checked.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError('Use execute for non-regular files')
        return f.read(65537)


def operate(req):
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
        data=read_regular(path)
        return {'path':str(path),'content':data[:65536].decode('utf-8','replace'), 'truncated':len(data)>65536,
                'sha256':hashlib.sha256(data).hexdigest() if len(data)<=65536 else None}
    if op=='write':
        target=path.resolve()
        locks=BACKUPS/'.locks';locks.mkdir(mode=0o700,parents=True,exist_ok=True)
        lock_path=locks/hashlib.sha256(os.fsencode(target)).hexdigest()
        with lock_path.open('a+b') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            return write_guarded(target,req)
    raise ValueError('Unknown file operation')


def metadata(path):
    path=Path(os.path.abspath(path))
    try:
        info=path.lstat()
        kind='file' if stat.S_ISREG(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode) else 'symlink' if stat.S_ISLNK(info.st_mode) else 'other'
        return {'path':str(path),'kind':kind,'size_bytes':info.st_size,'modified_at':info.st_mtime,'mode':stat.S_IMODE(info.st_mode),'measured_at':time.time()}
    except FileNotFoundError:kind='missing'
    except OSError:kind='unavailable'
    return {'path':str(path),'kind':kind,'size_bytes':None,'modified_at':None,'mode':None,'measured_at':time.time()}


def run(req):
    result=operate(req);result['metadata']=metadata(result['path']);return result


def write_guarded(target, req):
    if target.exists():
        old=read_regular(target)
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
    try:
        with temporary.open('xb') as f:f.write(content);f.flush();os.fsync(f.fileno())
        if target.exists():
            original=target.stat()
            os.chmod(temporary,original.st_mode & 0o777)
            os.chown(temporary,original.st_uid,original.st_gid)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {'path':str(target),'sha256':hashlib.sha256(content).hexdigest(),'backup':str(backup) if backup else None}

def read_request(args, stream):
    if args and args[0]=='--stdin-content':
        if len(args)!=2:raise ValueError('Use a guarded write descriptor with stdin content')
        req=json.loads(args[1])
        if not isinstance(req,dict) or req.get('op')!='write' or 'content' in req:
            raise ValueError('stdin content requires a guarded write')
        data=stream.read(BROKER_INPUT_LIMIT+1)
        if len(data)>BROKER_INPUT_LIMIT:raise ValueError('Content too large')
        expected=req.pop('content_sha256',None)
        if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Input content hash mismatch')
        req['content']=data.decode('utf-8')
        return req
    if len(args)!=1:raise ValueError('Use a file operation descriptor')
    req=json.loads(args[0])
    if not isinstance(req,dict):raise ValueError('Use a file operation descriptor')
    return req


if __name__=='__main__':
    try:
        # Use UTF-8 for ordinary text, but JSON-escape undecodable filename
        # surrogates instead of emitting invalid UTF-8 into the broker stream.
        payload=json.dumps(run(read_request(sys.argv[1:],sys.stdin.buffer)), ensure_ascii=False)
        sys.stdout.buffer.write(payload.encode('utf-8','backslashreplace')+b'\n')
    except (OSError,ValueError,KeyError) as exc:
        print(json.dumps({'error':str(exc)}));sys.exit(1)
