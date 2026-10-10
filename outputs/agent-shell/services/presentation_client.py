"""Authenticated local native-presentation client; no action execution or actor labels."""
import json
import os
import socket

PROTOCOL='agentos.presentation/1'
CATALOG='native-core/1'
LIMIT=4*1024*1024


def request(op, **fields):
    payload=json.dumps({'op':op,**fields},separators=(',',':')).encode()+b'\n'
    if len(payload)>LIMIT:raise ValueError('Presentation transaction exceeds 4 MiB')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
        conn.settimeout(5);conn.connect(os.environ.get('AGENT_OS_SOCKET','/run/agent-os/runtime.sock'))
        conn.sendall(payload)
        with conn.makefile('rb') as stream:
            line=stream.readline(16*LIMIT+1)
            if len(line)>16*LIMIT or not line.endswith(b'\n'):raise RuntimeError('Presentation response exceeds transport limit')
            result=json.loads(line)
    if not result['ok']:raise RuntimeError(result['error'])
    return result['result']


def for_activity(activity):
    state=request('presentation.snapshot')
    state['documents']={key:doc for key,doc in state['documents'].items() if doc['activity_id']==str(activity)}
    state['host_surfaces']={key:host for key,host in state.get('host_surfaces',{}).items() if host.get('activity_id')==str(activity)}
    state['renderers']={key:owner for key,owner in state.get('renderers',{}).items() if key in state['documents']}
    return state


def apply_for_activity(activity, transaction):
    """Restrict model tools to the activity hosting the current request."""
    if not isinstance(transaction,dict) or transaction.get('op')!='presentation.apply':
        raise ValueError('Expected a presentation.apply transaction')
    state=for_activity(activity)
    for operation in transaction.get('operations',[]):
        if not isinstance(operation,dict):raise ValueError('Malformed operation')
        document=operation.get('document')
        if document is not None:
            if not isinstance(document,dict) or document.get('activity_id')!=str(activity):
                raise ValueError('Document belongs to another activity')
            ident=document.get('surface_id',document.get('workspace_id'))
            if operation.get('op') not in ('surface.create','workspace.put') and ident not in state['documents']:
                raise ValueError('Unknown surface in this activity')
        elif operation.get('surface_id') not in state['documents']:
            raise ValueError('Unknown surface in this activity')
    return request(**transaction)
