import os,sys,json,time,runpy
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
  runpy.run_path('outputs/agent-shell/deploy.py',run_name='__main__')
  report['runtime']=vm.ssh('readlink -f /usr/local/lib/agent-os/current',capture_output=True,text=True,check=True).stdout.strip()
  r=vm.ssh('cd /home/developer/agent-os-source && sudo -n python3 tests/direct_display_guest.py --list-input',text=True,capture_output=True,check=False,timeout=150)
  Path('/tmp/agentos-activation-baseline-v1.log').write_text(r.stdout+r.stderr)
  report['returncode']=r.returncode
  assert r.returncode!=0 and 'did not acknowledge activation without a geometry change' in r.stdout+r.stderr,'Expected independent activation failure was not reproduced'
 finally:
  vm.stop();deadline=time.monotonic()+60
  while vm.status()!='stopped':
   assert time.monotonic()<deadline,'Guest stop unconfirmed'
   time.sleep(.5)
  report['owned_app_closed']=owner.close()
  assert vm.utm_application_identity() is None
  Path('/tmp/agentos-activation-baseline-v1-driver.json').write_text(json.dumps(report,indent=2)+'\n')
  print(json.dumps(report),flush=True)
