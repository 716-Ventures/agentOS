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

def property_rollback_guard(installer,source):
    probe=verify();ident='install-property-probe-'+os.urandom(12).hex()
    def present(value):
        return json.loads(subprocess.check_output(['agent-os','presentation','-'],input=json.dumps(value).encode()))
    def apply(request,expected,operations):
        return present({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1',
                        'request_id':ident+'-'+request,'expected_revisions':{ident:expected},'operations':operations})
    document={'protocol':'agentos.presentation/1','catalog_revision':'native-core/1','surface_id':ident,
              'activity_id':str(probe['activity']),'revision':0,'title':'Install property guard',
              'root':'button','elements':{'button':{'type':'Button@1','props':{'label':'Next λ','icon':'arrow-right','icon_position':'only','size':'xs'}}},'actions':{},'bindings':{}}
    apply('create',None,[{'op':'surface.create','document':document}])
    try:
        contract=json.loads((source/'release-contract.json').read_text());contract.pop('component_schemas')
        (source/'release-contract.json').write_text(json.dumps(contract));legacy=installer.stage(source)
        current=Path('/usr/local/lib/agent-os/current').resolve().name;journal=installer.journal.read_bytes()
        units=installer.contract(Path('/usr/local/lib/agent-os/current'))['units']
        def identities():return subprocess.check_output(['systemctl','show','--property=MainPID','--property=ActiveEnterTimestampMonotonic',*units],text=True)
        before=identities();saved=present({'op':'presentation.get','document_id':ident})
        try:installer.activate(legacy)
        except ValueError as error:assert 'Button@1.icon' in str(error),error
        else:raise AssertionError('Unannotated legacy runtime accepted saved icon properties')
        assert identities()==before,'Incompatible preflight stopped or restarted a live service'
        assert installer.journal.read_bytes()==journal
        assert Path('/usr/local/lib/agent-os/current').resolve().name==current
        assert present({'op':'presentation.get','document_id':ident})==saved
        apply('plain',saved['revision'],[{'op':'element.set_props','surface_id':ident,'element_id':'button','props':{'label':'Plain legacy action λ'}}])
        for kind,value,extra in (
            ('TextField@1','Unsaved authority remains separate',{}),
            ('Choice@1','First',{'options':['First','Second λ']}),
            ('Toggle@1',False,{}),
        ):
            field={'type':kind,'props':{'label':'Saved validation λ','value':value,**extra,'validation_message':'Choose another saved name.'}}
            current_doc=present({'op':'presentation.get','document_id':ident})
            apply('validation-'+kind.split('@')[0],current_doc['revision'],[{'op':'element.put','surface_id':ident,'element_id':'button','element':field}])
            saved=present({'op':'presentation.get','document_id':ident})
            try:installer.activate(legacy)
            except ValueError as error:assert kind+'.validation_message' in str(error),error
            else:raise AssertionError('Unannotated legacy runtime accepted saved '+kind+' validation properties')
            assert identities()==before,'Validation preflight stopped or restarted a live service'
            assert installer.journal.read_bytes()==journal
            assert Path('/usr/local/lib/agent-os/current').resolve().name==current
            assert present({'op':'presentation.get','document_id':ident})==saved
            field['props'].pop('validation_message')
            apply('plain-'+kind.split('@')[0],saved['revision'],[{'op':'element.set_props','surface_id':ident,'element_id':'button','props':field['props']}])
            installer.compatible_components(installer.contract(installer.root/'releases'/legacy))
        verify()
        print('PASS: installed schema preflight rejects saved icon and text/choice/toggle validation properties without stopping services or changing journal/document; plain legacy controls remain compatible',flush=True)
    finally:
        current=present({'op':'presentation.get','document_id':ident})
        apply('close',current['revision'],[{'op':'surface.close','surface_id':ident}])

def rollbacks():
    setup()
    spec=importlib.util.spec_from_file_location('installed_installer',SOURCE/'install_runtime.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    installer=module.Installer();original=Path('/usr/local/lib/agent-os/current').resolve().name
    assert installer.contract(Path('/usr/local/lib/agent-os/current'))['state_contract']=='agentos.state/1'
    with tempfile.TemporaryDirectory(prefix='agentos-update-probe-') as directory:
        source=Path(directory)/'source'
        shutil.copytree(SOURCE,source,ignore=shutil.ignore_patterns('target','__pycache__','.git'))
        binary=source/'target/release/agent-os-core';binary.parent.mkdir(parents=True);shutil.copyfile(SOURCE/'target/release/agent-os-core',binary)
        for crate,name in [('native-shell','agent-os-desktop'),('native-compositor','agent-os-compositor')]:
            tree=SOURCE/crate if (SOURCE/crate).is_dir() else SOURCE.parent/crate
            binary=source/crate/'target/release'/name;binary.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(tree/'target/release'/name,binary)
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
        property_rollback_guard(installer,source)
    return ['Compatible update and rollback preserve activities, outputs, layouts, pending approvals, user files and provider configuration',
            'SIGKILL during rollback at stopped and activated phases recovers to the selected release without rewinding live state',
            'Saved property/schema incompatibility is rejected without stopping live services, changing document/journal or preventing plain legacy controls']

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
