"""Explicit human import of bounded immutable PNG resources and their image view."""
import os
from pathlib import Path
import stat
import uuid

LIMIT=256*1024


def publish(request,activity,path,label=None):
    path=Path(path).expanduser()
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('Choose a regular PNG file')
        data=stream.read(LIMIT+1)
    if len(data)>LIMIT:raise ValueError('PNG image exceeds 256 KiB')
    label=label if label is not None else path.name
    if not isinstance(label,str) or not label.strip() or len(label.encode())>256 or '\0' in label:raise ValueError('Use an alternative label of 1–256 bytes')
    reference='resource-'+uuid.uuid4().hex
    payload={'reference':reference,'activity_id':str(activity),'label':label,'png_hex':data.hex()}
    # Immutable references make an uncertain publication safe to reconcile exactly once.
    try:resource=request('resource.publish',**payload)
    except (OSError,RuntimeError):resource=request('resource.publish',**payload)
    surface='image-'+uuid.uuid4().hex
    document={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':surface,'activity_id':str(activity),'revision':0,
              'title':label,'root':'image','elements':{'image':{'type':'Image@1','props':{'label':label,'reference':reference}}},'bindings':{},'actions':{}}
    transaction={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','request_id':'open-'+surface,
                 'expected_revisions':{surface:None},'operations':[{'op':'surface.create','document':document}]}
    try:receipt=request('presentation.apply',**transaction)
    except (OSError,RuntimeError):receipt=request('presentation.apply',**transaction)
    return {'resource':resource,'surface_id':surface,'receipt':receipt}
