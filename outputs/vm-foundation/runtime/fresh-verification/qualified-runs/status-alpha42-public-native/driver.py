import os,sys,subprocess,json,hashlib,time,shlex,datetime,io,tarfile
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification';os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation');import vm
from utm_ownership import UTMApplicationOwnership
root=Path('/Users/chrisjdavis/development/716-ui');archive=io.BytesIO()
with tarfile.open(fileobj=archive,mode='w') as tar:
 for raw in subprocess.check_output(['git','-C',str(root),'ls-files','-z']).split(b'\0'):
  if raw:
   name=os.fsdecode(raw);p=root/name
   assert p.is_file() and not p.is_symlink();tar.add(p,arcname=name,recursive=False)
source=archive.getvalue();Path('/tmp/716-status-source.tar').write_bytes(source)
receipt={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_revision':subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),'source_changes':subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True).splitlines(),'source_archive_sha256':hashlib.sha256(source).hexdigest(),'passed':False}
with UTMApplicationOwnership(vm) as owner:
 try:
  assert vm.status()=='stopped'
  vm.start();vm.wait_ready(60)
  staged=vm.ssh('mktemp -d /home/developer/.716-status-source.XXXXXXXX',capture_output=True,text=True,check=True).stdout.strip()
  subprocess.run(vm.ssh_args()+['tar xf - -C '+shlex.quote(staged)],input=source,check=True)
  script="""from pathlib import Path
import time
source=Path('/home/developer/716-ui-verification');staged=Path(STAGED)
previous=source.with_name(source.name+'.previous-'+str(time.time_ns()))
source.rename(previous);staged.rename(source)
if (previous/'target').exists():(previous/'target').rename(source/'target')
""".replace('STAGED',repr(staged))
  subprocess.run(vm.ssh_args()+['python3 -'],input=script.encode(),check=True)
  vm.ssh('cd /home/developer/716-ui-verification && cargo test --locked --all-features && cargo build --locked --all-features --bins && dbus-run-session -- python3 tests/native_gallery.py',check=True,timeout=900)
  receipt['passed']=True
 finally:
  with Path('/tmp/716-status-native-output.tar.gz').open('wb') as output:
   vm.ssh('tar czf - -C /home/developer/716-ui-verification test-output',stdout=output,check=False)
  vm.stop();deadline=time.monotonic()+45
  while vm.status()!='stopped':
   assert time.monotonic()<deadline;time.sleep(.5)
  receipt['owned_utm_identity']=owner.owned;receipt['owned_utm_closed']=owner.close();receipt['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
  Path('/tmp/716-status-qualification.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt),flush=True)
