import os,sys,time,json,hashlib,subprocess,importlib.util
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification'
os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation')
import vm
from utm_ownership import UTMApplicationOwnership
spec=importlib.util.spec_from_file_location('candidate','/tmp/agentos-build-utmctl-v3-candidate.py');candidate=importlib.util.module_from_spec(spec);spec.loader.exec_module(candidate)
vm.controller=candidate.controller
report={'result':'running','candidate':json.loads((candidate.OUTPUT/'build.json').read_text()),'cycles':[]}
config=Path(vm.machine()['bundle'])/'config.plist';original=config.read_bytes()
assert vm.utm_application_identity() is None
with UTMApplicationOwnership(vm) as owner:
 try:
  for cycle in range(3):
   row={'cycle':cycle+1,'rapid_cold_launches':[]}
   for launch in range(2):
    assert vm.status()=='stopped'
    identity=vm.utm_application_identity();assert identity
    args=subprocess.check_output(['ps','-p',str(identity[0]),'-o','args='],text=True).strip()
    assert '-ApplePersistenceIgnoreState YES' in args,args
    assert len(vm.call([candidate.controller(),'list'],capture_output=True,text=True,timeout=10).stdout.splitlines())>=3
    row['rapid_cold_launches'].append({'app_identity':identity,'arguments':args})
    if launch==0:assert owner.close()
   started=time.monotonic();vm.start();vm.wait_ready(60)
   row['guest_ready_seconds']=time.monotonic()-started
   vm.ssh('test "$(uname -m)" = aarch64 && systemctl is-active --quiet agent-os-core agent-os-broker',check=True)
   vm.stop();deadline=time.monotonic()+60
   while vm.status()!='stopped':
    assert time.monotonic()<deadline
    time.sleep(.5)
   row['owned_app_closed']=owner.close();assert vm.utm_application_identity() is None
   assert config.read_bytes()==original
   row['guest_stopped']=True;row['config_unchanged']=True
   report['cycles'].append(row)
   print('PASS: candidate rapid-cold/start/readiness/stop/cleanup cycle',cycle+1,flush=True)
  report['result']='pass'
 finally:
  if vm.utm_application_identity() is not None:
   vm.stop();deadline=time.monotonic()+60
   while vm.status()!='stopped':
    assert time.monotonic()<deadline
    time.sleep(.5)
   owner.close()
  report['owned_app_absent']=vm.utm_application_identity() is None
  Path('/tmp/agentos-utm-v3-cycles.json').write_text(json.dumps(report,indent=2)+'\n')
  print(json.dumps(report),flush=True)
