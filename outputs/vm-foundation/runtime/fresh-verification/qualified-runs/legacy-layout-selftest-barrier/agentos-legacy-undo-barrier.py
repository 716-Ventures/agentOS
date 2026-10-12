import os,sys,time,json
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification'
os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation')
import vm
from utm_ownership import UTMApplicationOwnership
report={'result':'running','checks':[]}
with UTMApplicationOwnership(vm) as owner:
 try:
  assert vm.status()=='stopped'
  vm.start();vm.wait_ready(60)
  vm.ssh('cat > /home/developer/agent-os-source/native-shell/tests/native_desktop.py',input=Path('outputs/native-shell/tests/native_desktop.py').read_bytes(),check=True)
  for name,flag in [('legacy','--compositor'),('shared','--compositor --shared')]:
   result=vm.ssh('cd /home/developer/agent-os-source && dbus-run-session -- python3 native-shell/tests/native_desktop.py '+flag,capture_output=True,text=True,check=False,timeout=180)
   Path('/tmp/agentos-legacy-undo-barrier-'+name+'.log').write_text(result.stdout+result.stderr)
   assert result.returncode==0,name
   report['checks'].append(name)
  report['result']='pass'
 finally:
  vm.stop();deadline=time.monotonic()+60
  while vm.status()!='stopped':
   assert time.monotonic()<deadline
   time.sleep(.5)
  report['owned_app_closed']=owner.close()
  report['guest_stopped']=True
  assert vm.utm_application_identity() is None
  Path('/tmp/agentos-legacy-undo-barrier.json').write_text(json.dumps(report,indent=2)+'\n')
  print(json.dumps(report),flush=True)
