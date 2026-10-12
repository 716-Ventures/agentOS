import os,sys,json,time,hashlib,plistlib,datetime
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification'
os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation')
import vm
from utm_ownership import UTMApplicationOwnership
config_path=Path(vm.machine()['bundle'])/'config.plist'
original=config_path.read_bytes()
Path('/tmp/agentos-explicit-restoration-fixed-v1-original-config.plist').write_bytes(original)
data=config_path.parent/'Data'
disk_inodes={name:(data/name).stat().st_ino for name in ('disk.qcow2','efi_vars.fd')}
config=plistlib.loads(original)
assert len(config['Display'])==1 and config['Display'][0]['Hardware']=='virtio-gpu-gl-pci'
assert not config['QEMU']['AdditionalArguments']
config['QEMU']['AdditionalArguments']=['-global','virtio-gpu-gl-pci.max_outputs=2']
receipt={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_config_sha256':hashlib.sha256(original).hexdigest(),'purpose':'Targeted explicit preferred-output restoration, core recovery unit regressions and actual kernel/native controls; not physical hotplug'}
with UTMApplicationOwnership(vm) as owner:
 try:
  # Prior exact cleanup confirmed stop. Do not cold-launch only to close
  # again: edit the inactive bundle before its single owned cold launch.
  import subprocess
  assert vm.utm_application_identity() is None
  for name in disk_inodes:
   check=subprocess.run(['/usr/sbin/lsof','-n','-Fpcn',str(data/name)],capture_output=True,text=True)
   assert check.returncode==1 and not check.stdout
  assert not any('qemu' in row.lower() for row in subprocess.check_output(['ps','-axo','comm='],text=True).splitlines())
  config_path.write_bytes(plistlib.dumps(config))
  vm.start();vm.wait_ready(60)
  import runpy,subprocess
  runpy.run_path('outputs/agent-shell/deploy.py',run_name='__main__')
  receipt['deployment']=json.loads((vm.RUN/'deployment.json').read_text())
  receipt['installed_runtime']=vm.ssh('readlink -f /usr/local/lib/agent-os/current',capture_output=True,text=True,check=True).stdout.strip().rsplit('/',1)[-1]
  vm.ssh('cd /home/developer/agent-os-source && cargo test --locked --manifest-path native-compositor/Cargo.toml && cargo build --locked --manifest-path native-compositor/Cargo.toml --examples',check=True,timeout=240)
  result=vm.ssh('sudo -n python3 -',input=Path('/tmp/agentos-explicit-restoration-fixed-v1-guest.py').read_text(),text=True,capture_output=True,check=False,timeout=700)
  Path('/tmp/agentos-explicit-restoration-fixed-v1-guest-output.log').write_text(result.stdout+result.stderr)
  for remote,local in [*[(f'/tmp/agentos-explicit-restoration-fixed-v1-{i}.log',f'/tmp/agentos-explicit-restoration-fixed-v1-{i}.log') for i in range(4)],('/tmp/agentos-explicit-restoration-fixed-v1.json','/tmp/agentos-explicit-restoration-fixed-v1.json')]:
   observed=vm.ssh('sudo -n cat '+remote,capture_output=True,check=False)
   if observed.returncode==0:Path(local).write_bytes(observed.stdout)
  assert result.returncode==0,'Explicit restoration probe failed; full guest trace retained'
  receipt['virtual_kms']=json.loads(result.stdout)
  assert len(receipt['virtual_kms']['cases'])==4
  assert receipt['virtual_kms']['cases'][0]['kms_session']['virtual_explicit_output_restoration_qualified']

 finally:
  vm.stop();deadline=time.monotonic()+60
  while vm.status()!='stopped':
   assert time.monotonic()<deadline,'Guest stop unconfirmed; retain experimental config for safe recovery'
   time.sleep(.5)
  receipt['owned_utm_closed']=owner.close()
  config_path.write_bytes(original)
  assert config_path.read_bytes()==original
  assert all((data/name).stat().st_ino==inode for name,inode in disk_inodes.items())
  assert vm.utm_application_identity() is None
  receipt['original_disk_efi_inodes_preserved']=True
  receipt['original_config_restored']=True
  Path('/tmp/agentos-explicit-restoration-fixed-v1-driver.json').write_text(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(receipt),flush=True)
