#!/usr/bin/python3
"""Root-only development-guest install interruption and reboot persistence probes."""
import argparse
import grp
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tempfile
import shutil
sys.path.insert(0,'/usr/local/lib/agent-os/services')
from broker_client import request as broker
from layout_client import request as layout
STATE=Path('/var/lib/agent-os-install')
PROBE=STATE/'persistence-probe.json'
SOURCE=Path(__file__).resolve().parents[1]
CONFIG=Path('/etc/agent-os/providers.json')

def cli(*args):return json.loads(subprocess.check_output(['agent-os',*map(str,args)]))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def setup():
    if PROBE.exists():return verify()
    token=os.urandom(24).hex()
    activity=cli('create','Installation persistence probe')['id']
    user_file=Path('/home/developer')/('agent-os-install-probe-'+token)
    user_file.write_text(token)
    job=cli('run',activity,'--','/usr/bin/printf','%s',token)['id']
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if next(j for j in cli('status')['jobs'] if j['id']==job)['status']=='succeeded':break
        time.sleep(.1)
    else:raise AssertionError('Core persistence fixture did not finish')
    state=layout('ensure',activity=activity)
    state=layout('apply',activity=activity,expected_revision=state['revision'],action=dict(operation='bind',surface_id=state['surfaces'][0]['id'],job_id=job,view='output'))
    proposal=broker('execute',activity=activity,argv=['/usr/bin/true'],purpose='Unexecuted harmless install persistence probe',request_confirmation=True)
    assert proposal['status']=='approval_required',proposal
    # A config without provider keys tests preservation without calling an external model.
    created_config=not CONFIG.exists()
    if created_config:
        CONFIG.write_text(json.dumps({'reproduction_fixture':token}))
        os.chmod(CONFIG,0o640);os.chown(CONFIG,0,grp.getgrnam('agentos-ai').gr_gid)
    probe=dict(activity=activity,job=job,file=str(user_file),token=token,layout=state,
               proposal=proposal['id'],generation=broker('activity_state',activity=activity)['generation'],
               config_sha256=sha(CONFIG),config_mode=CONFIG.stat().st_mode & 0o777,
               config_owner=[CONFIG.stat().st_uid,CONFIG.stat().st_gid],created_config=created_config)
    PROBE.write_text(json.dumps(probe));os.chmod(PROBE,0o600)
    verify()
    return probe

def verify():
    probe=json.loads(PROBE.read_text())
    assert Path(probe['file']).read_text()==probe['token']
    assert any(a['id']==probe['activity'] for a in cli('activities'))
    job=next(j for j in cli('status')['jobs'] if j['id']==probe['job'])
    assert job['status']=='succeeded'
    assert subprocess.check_output(['agent-os','logs',str(probe['job'])],text=True)==probe['token']
    current=layout('snapshot',activity=probe['activity'])
    for key in ('revision','tree','focus','zoom'):assert current[key]==probe['layout'][key],key
    assert broker('poll',job_id=probe['proposal'])['status']=='approval_required'
    assert broker('activity_state',activity=probe['activity'])['generation']==probe['generation']
    assert sha(CONFIG)==probe['config_sha256']
    assert CONFIG.stat().st_mode & 0o777==probe['config_mode']
    assert [CONFIG.stat().st_uid,CONFIG.stat().st_gid]==probe['config_owner']
    receipt=json.loads((STATE/'installed.json').read_text())
    assert receipt['phase']=='complete'
    release=json.loads(Path('/etc/agent-os/release.json').read_text())
    assert release['runtime_release']==receipt['release']
    manifest=Path('/usr/local/lib/agent-os/current/manifest.json')
    for name,expected in json.loads(manifest.read_text()).items():assert sha(manifest.parent/name)==expected,name
    return probe

def interrupts():
    setup();checks=[]
    for phase in ('stopped','activated'):
        result=subprocess.run([sys.executable,str(SOURCE/'install_runtime.py'),'--test-interrupt',phase])
        assert result.returncode==-9,result.returncode
        assert json.loads((STATE/'transaction.json').read_text())['phase']==phase
        subprocess.run([sys.executable,'/usr/local/lib/agent-os/install-recovery.py','--recover'],check=True)
        verify();checks.append('SIGKILL at '+phase+' recovered from staged release; state and config preserved')
    return checks

def rollbacks():
    setup()
    spec=importlib.util.spec_from_file_location('installed_installer',SOURCE/'install_runtime.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    installer=module.Installer();original=Path('/usr/local/lib/agent-os/current').resolve().name
    assert installer.contract(Path('/usr/local/lib/agent-os/current'))['state_contract']=='agentos.state/1'
    with tempfile.TemporaryDirectory(prefix='agentos-update-probe-') as directory:
        source=Path(directory)/'source'
        shutil.copytree(SOURCE,source,ignore=shutil.ignore_patterns('target','__pycache__','.git'))
        binary=source/'target/release/agent-os-core';binary.parent.mkdir(parents=True);shutil.copyfile(SOURCE/'target/release/agent-os-core',binary)
        with (source/'services/common.py').open('a') as out:out.write('\n# Compatible runtime rollback verification fixture.\n')
        candidate=installer.stage(source);assert candidate!=original
        installer.activate(candidate);verify()
        installer.rollback();verify();assert Path('/usr/local/lib/agent-os/current').resolve().name==original
        for phase in ('stopped','activated'):
            installer.activate(candidate)
            result=subprocess.run([sys.executable,str(SOURCE/'install_runtime.py'),'--rollback',original,'--test-interrupt',phase])
            assert result.returncode==-9,result.returncode
            subprocess.run([sys.executable,'/usr/local/lib/agent-os/install-recovery.py','--recover'],check=True)
            verify();assert Path('/usr/local/lib/agent-os/current').resolve().name==original
    return ['Compatible update and rollback preserve activities, outputs, layouts, pending approvals, user files and provider configuration',
            'SIGKILL during rollback at stopped and activated phases recovers to the selected release without rewinding live state']

def cleanup():
    probe=verify()
    broker('cancel',job_id=probe['proposal']);Path(probe['file']).unlink()
    if probe['created_config']:CONFIG.unlink()
    cli('remove',probe['activity']);PROBE.unlink()

if __name__=='__main__':
    if os.geteuid()!=0:raise SystemExit('Run this development-guest test with sudo')
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['interrupts','rollbacks','verify','cleanup'])
    operation=parser.parse_args().operation
    checks=interrupts() if operation=='interrupts' else rollbacks() if operation=='rollbacks' else [operation]
    if operation=='verify':verify()
    if operation=='cleanup':cleanup()
    print(json.dumps({'result':'pass','checks':checks,'provider_calls':'none'}))
