"""Shared local layout API used by the assistant and other clients."""
from common import connect, read_line


def request(op,**fields):
    with connect('/run/agent-os-layout/api.sock',{'op':op,**fields},timeout=3) as conn:
        with conn.makefile('rb') as f:result=read_line(f)
    if not result['ok']:raise RuntimeError(result['error'])
    return result['result']
