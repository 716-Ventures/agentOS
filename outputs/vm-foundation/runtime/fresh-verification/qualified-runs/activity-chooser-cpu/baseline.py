import os,sys,subprocess,json,time,datetime,hashlib
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification';os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path[:0]=['outputs/vm-foundation','outputs/agent-shell'];import vm
from utm_ownership import UTMApplicationOwnership
r={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'passed':False,'test_files':{}}
with UTMApplicationOwnership(vm) as owner:
 try:
  assert vm.status()=='stopped';vm.start();vm.wait_ready(60)
  for name in ('controls.rs','verification.rs'):
   data=(Path('outputs/native-shell/src')/name).read_bytes();r['test_files'][name]=hashlib.sha256(data).hexdigest()
   vm.ssh('cat > /home/developer/agent-os-source/native-shell/src/'+name,input=data,check=True)
  vm.ssh('cd /home/developer/agent-os-source && cargo build --locked --manifest-path native-shell/Cargo.toml && dbus-run-session -- python3 native-shell/tests/native_desktop.py --appearance dark --text-scale 1',check=True,timeout=300)
  r['passed']=True
 finally:
  vm.stop();deadline=time.monotonic()+60
  while vm.status()!='stopped':
   assert time.monotonic()<deadline;time.sleep(.5)
  r['owned_utm_closed']=owner.close();r['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();Path('/tmp/agentos-activity-chooser-baseline-valid.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True)
