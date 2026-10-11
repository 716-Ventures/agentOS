import os,sys,subprocess,json,hashlib,time,shlex,datetime
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification'
os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path[:0]=['outputs/vm-foundation','outputs/agent-shell']
import vm,deploy
from utm_ownership import UTMApplicationOwnership
archive=deploy.source_archive()
receipt={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_changes':subprocess.check_output(['git','status','--porcelain'],text=True).splitlines(),'source_archive_sha256':hashlib.sha256(archive).hexdigest(),'passed':False}
with UTMApplicationOwnership(vm) as owner:
 try:
  assert vm.status()=='stopped'
  vm.start();vm.wait_ready(60)
  staged=vm.ssh('mktemp -d /home/developer/.notice-source.XXXXXXXX',capture_output=True,text=True,check=True).stdout.strip()
  subprocess.run(vm.ssh_args()+['tar xf - -C '+shlex.quote(staged)],input=archive,check=True)
  script="""from pathlib import Path
import time
source=Path('/home/developer/agent-os-source'); staged=Path(STAGED)
previous=source.with_name(source.name+'.previous-'+str(time.time_ns()))
source.rename(previous);staged.rename(source)
for name in ('target','native-shell/target','native-compositor/target'):
 if (previous/name).exists():(previous/name).rename(source/name)
""".replace('STAGED',repr(staged))
  subprocess.run(vm.ssh_args()+['python3 -'],input=script.encode(),check=True)
  vm.ssh('cd /home/developer/agent-os-source && cargo build --locked --manifest-path native-shell/Cargo.toml && cargo build --locked --manifest-path native-compositor/Cargo.toml && cargo build --locked --manifest-path native-compositor/Cargo.toml --examples',check=True)
  receipt['baseline_failures_reproduced']=[]
  for kind in ('message','voice','model','work'):
   result=vm.ssh('cd /home/developer/agent-os-source && AGENT_OS_STATUS_SELECTION_CASE='+kind+' dbus-run-session -- python3 native-shell/tests/native_desktop.py --appearance light --text-scale 1',check=False,capture_output=True,text=True,timeout=180)
   output=result.stdout+result.stderr
   Path('/tmp/agentos-direct-status-baseline-'+kind+'.log').write_text(output)
   assert result.returncode!=0 and kind+': background refresh replaced selected status' in output,(kind,result.returncode,output[-3000:])
   receipt['baseline_failures_reproduced'].append(kind)
 finally:
  with Path('/tmp/agentos-direct-status-baseline-last-speech.log').open('wb') as out:
   vm.ssh('cat /home/developer/agent-os-source/native-shell/test-output/session-orca-speech.log',stdout=out,check=False)
  vm.stop();deadline=time.monotonic()+45
  while vm.status()!='stopped':
   assert time.monotonic()<deadline;time.sleep(.5)
  receipt['owned_utm_identity']=owner.owned
  receipt['owned_utm_closed']=owner.close()
  receipt['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
  Path('/tmp/agentos-direct-status-baseline.json').write_text(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(receipt),flush=True)
