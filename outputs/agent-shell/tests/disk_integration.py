#!/usr/bin/env python3
"""Run inside the real Linux guest. Does not require or print provider keys."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
sys.path.insert(0, '/usr/local/lib/agent-os/services')
from common import connect, read_line, AI_SOCKET, DISK_SOCKET


def cli(*args):
    return json.loads(subprocess.check_output(['agent-os', *map(str,args)]))


def main():
    checks=[]
    status=cli('providers')
    activity=cli('create','Disk verification')['id']
    job=cli('disk',activity)['id']
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        state=next(j for j in cli('jobs',activity) if j['id']==job)
        if state['status'] not in ('starting','running','cancelling'): break
        time.sleep(.2)
    else: raise AssertionError('Disk job did not finish')
    report=cli('report',activity)
    fs=report['report']['filesystem']
    real=os.statvfs('/')
    assert fs['total_bytes']==real.f_blocks*real.f_frsize
    assert abs(fs['used_bytes']-(real.f_blocks-real.f_bfree)*real.f_frsize)<20*1024*1024
    assert len(report['report']['evidence'])==6
    assert all(e.get('exit_code')==0 for e in report['report']['evidence'])
    checks.append('Real fixed disk measurements agree with statvfs and all six du inspections completed')
    text=subprocess.check_output(['agent-os','logs',str(job)],text=True)
    assert 'Evidence saved as report' in text
    if not status['gateway_configured']:
        assert 'Vercel AI Gateway is not configured' in text
        assert state['status']=='failed'
        checks.append('Missing gateway key is explicit; evidence saved without fabricated explanation')
    # Arbitrary supervised job identity cannot bypass collector or read assistant state.
    for command in (
        ['test','-r',f'/var/lib/agent-os-ai/activity-{activity}.json'],
        ['test','-w','/usr/local/lib/agent-os/services/providers.py'],
        ['python3','-c',"import socket;s=socket.socket(socket.AF_UNIX);s.connect('/run/agent-os-disk/api.sock')"],
    ):
        result=subprocess.run(['sudo','-u','agentos','--',*command],capture_output=True)
        assert result.returncode!=0
    checks.append('Job identity cannot read assistant state, modify provider code, or invoke privileged collector')
    # Fixed collector rejects any caller-supplied command/path even from its permitted identity.
    source="""import sys;sys.path.insert(0,'/usr/local/lib/agent-os/services')
from common import *
with connect(DISK_SOCKET, {'op':'disk','path':'/etc','argv':['id']}) as s:
 with s.makefile('rb') as f:
  assert read_line(f)['ok'] is False
"""
    subprocess.run(['sudo','-u','agentos-ai','python3','-c',source],check=True)
    checks.append('Collector refuses caller-provided paths and commands')
    before=report['id']
    subprocess.run(['sudo','systemctl','restart','agent-os-ai'],check=True)
    for _ in range(30):
        try:
            after=cli('report',activity)
            break
        except subprocess.CalledProcessError: time.sleep(.1)
    assert after['id']==before
    checks.append('Measured evidence survives assistant service restart')
    print(json.dumps({'checks':checks,'activity':activity,'job':job,'provider_status':status,
        'authenticated_models_tested': bool(report['exchanges']), 'root_used_bytes':fs['used_bytes']},indent=2))

if __name__=='__main__': main()
