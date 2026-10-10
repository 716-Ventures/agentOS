"""Human-selected, strict UTF-8 document imports and exclusive filesystem exports."""
import hashlib
import os
from pathlib import Path
import stat
import uuid

LIMIT=65536


def read(path):
    path=Path(path).expanduser()
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('Choose a regular UTF-8 text file')
        raw=stream.read(LIMIT+1)
    if len(raw)>LIMIT:raise ValueError('Document exceeds 64 KiB; it was not imported')
    text=raw.decode('utf-8',errors='strict')
    if '\0' in text:raise ValueError('Document contains NUL bytes')
    title=path.name
    if not title.strip() or len(title.encode('utf-8'))>256:raise ValueError('Filename must contain 1–256 UTF-8 bytes')
    return {'title':title,'content':text,'sha256':hashlib.sha256(raw).hexdigest()}


def document(activity,loaded):
    return {'protocol':'agentos.presentation/1','catalog_revision':'native-core/1',
            'surface_id':'document-'+uuid.uuid4().hex,'activity_id':str(activity),'revision':0,
            'title':loaded['title'],'root':'editor','elements':{'editor':{'type':'DocumentEditor@1','props':{'label':loaded['title'],'value':loaded['content']}}},'bindings':{},'actions':{}}


def publish(request,activity,path):
    doc=document(activity,read(path));surface=doc['surface_id']
    transaction={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'open-'+surface,
                 'expected_revisions':{surface:None},'operations':[{'op':'surface.create','document':doc}]}
    try:receipt=request('presentation.apply',**transaction)
    except (OSError,RuntimeError):receipt=request('presentation.apply',**transaction)
    return {'surface_id':surface,'receipt':receipt}


def saved_content(request,surface,revision):
    doc=request('presentation.get',document_id=surface)
    if doc.get('revision')!=revision:raise ValueError('View changed; review the current revision before exporting')
    editors=[node for node in doc.get('elements',{}).values() if node.get('type')=='DocumentEditor@1']
    if len(editors)!=1:raise ValueError('Export requires exactly one shared document editor')
    # Unsaved drafts must be explicitly resolved; do not export old committed text silently.
    element=next(key for key,node in doc['elements'].items() if node is editors[0])
    if request('draft.get',surface_id=surface,element_id=element).get('draft') is not None:
        raise ValueError('Save or discard the document draft before exporting')
    content=editors[0].get('props',{}).get('value')
    if not isinstance(content,str) or '\0' in content:raise ValueError('Invalid document content')
    raw=content.encode('utf-8')
    if len(raw)>LIMIT:raise ValueError('Document exceeds 64 KiB')
    return content


def export(request,surface,path,revision):
    raw=saved_content(request,surface,revision).encode('utf-8')
    path=Path(path).expanduser();parent=path.parent.resolve(strict=True)
    target=parent/path.name
    # Write and fsync privately, then link exclusively. Existing files/symlinks are never replaced.
    temporary=parent/('.agent-document-'+uuid.uuid4().hex)
    try:
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        # A changing shared document cannot silently become an export of a newer revision.
        if request('presentation.get',document_id=surface).get('revision')!=revision:
            raise ValueError('View changed while exporting; no file was created')
        os.link(temporary,target,follow_symlinks=False)
        directory=os.open(parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:temporary.unlink(missing_ok=True)
    return {'path':str(target),'revision':revision,'sha256':hashlib.sha256(raw).hexdigest(),'status':'Document exported'}


def review(request,surface,path,revision):
    content=saved_content(request,surface,revision)
    loaded=read(path)
    return {'before':loaded['content'],'after':content,'expected_sha256':loaded['sha256'],'revision':revision,'path':str(Path(path).expanduser().absolute())}


def replace(request,surface,path,revision,expected_sha256):
    if not isinstance(expected_sha256,str) or len(expected_sha256)!=64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError('Replacement requires the reviewed file SHA-256')
    current=review(request,surface,path,revision)
    if current['expected_sha256']!=expected_sha256:raise ValueError('File changed; review the changes again before replacing it')
    # Reuse the installed guarded file primitive, with private human-owned recovery storage.
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'))
    import files
    backups=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'agent-os/document-backups'
    backups.mkdir(mode=0o700,parents=True,exist_ok=True)
    if backups.is_symlink():raise ValueError('Document recovery directory must not be a symlink')
    backups.chmod(0o700)
    content=saved_content(request,surface,revision)
    previous=files.BACKUPS
    try:
        files.BACKUPS=backups
        result=files.run({'op':'write','path':current['path'],'content':content,'expected_sha256':expected_sha256,'preserve_path':True})
    finally:files.BACKUPS=previous
    result['status']='File saved; original retained at '+str(result['backup'])
    result['revision']=revision
    return result
