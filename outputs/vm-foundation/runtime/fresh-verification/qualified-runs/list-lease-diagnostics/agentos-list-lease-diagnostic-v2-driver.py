import os,sys,json,time,hashlib
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification'
os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation')
import vm
from utm_ownership import UTMApplicationOwnership
report={}
with UTMApplicationOwnership(vm) as owner:
 try:
  assert vm.utm_application_identity() is None
  vm.start();vm.wait_ready(60)
  report['runtime']=vm.ssh('readlink -f /usr/local/lib/agent-os/current',capture_output=True,text=True,check=True).stdout.strip()
  r=vm.ssh('sudo -n python3 -',input=Path('/tmp/agentos-list-lease-diagnostic-v2-guest.py').read_text(),text=True,capture_output=True,check=False,timeout=510)
  Path('/tmp/agentos-list-lease-diagnostic-v2-guest-output.log').write_text(r.stdout+r.stderr)
  assert r.returncode==0,'Diagnostic setup failed; see retained output'
  report['runs']=json.loads(r.stdout)
  for row in report['runs']:
   name='agentos-list-lease-diagnostic-v2-'+str(row['index'])+'.log'
   raw=vm.ssh('sudo -n cat /tmp/'+name,capture_output=True,check=True).stdout
   Path('/tmp',name).write_bytes(raw)
 finally:
  vm.stop();deadline=time.monotonic()+60
  while vm.status()!='stopped':
   assert time.monotonic()<deadline,'Guest stop unconfirmed'
   time.sleep(.5)
  report['owned_app_closed']=owner.close()
  assert vm.utm_application_identity() is None
  Path('/tmp/agentos-list-lease-diagnostic-v2-driver.json').write_text(json.dumps(report,indent=2)+'\n')
  print(json.dumps(report),flush=True)
