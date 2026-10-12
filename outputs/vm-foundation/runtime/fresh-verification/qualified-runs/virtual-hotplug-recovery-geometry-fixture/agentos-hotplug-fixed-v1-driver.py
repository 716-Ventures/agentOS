import os,sys,json,time,hashlib,plistlib,datetime
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification'
os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation')
import vm
from utm_ownership import UTMApplicationOwnership
config_path=Path(vm.machine()['bundle'])/'config.plist'
original=config_path.read_bytes()
Path('/tmp/agentos-hotplug-fixed-v1-original-config.plist').write_bytes(original)
data=config_path.parent/'Data'
disk_inodes={name:(data/name).stat().st_ino for name in ('disk.qcow2','efi_vars.fd')}
config=plistlib.loads(original)
assert len(config['Display'])==1 and config['Display'][0]['Hardware']=='virtio-gpu-gl-pci'
assert not config['QEMU']['AdditionalArguments']
config['QEMU']['AdditionalArguments']=['-global','virtio-gpu-gl-pci.max_outputs=2']
receipt={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_config_sha256':hashlib.sha256(original).hexdigest(),'purpose':'Force one virtual connector for two-output KMS/VT qualification; not physical or host-view qualification'}
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
  import runpy
  runpy.run_path('outputs/agent-shell/deploy.py',run_name='__main__')
  vm.ssh('cd /home/developer/agent-os-source && cargo test --locked --manifest-path native-compositor/Cargo.toml && cargo build --locked --manifest-path native-compositor/Cargo.toml --example presentation_fixture',check=True,timeout=300)
  probe="""from pathlib import Path
import json
rows=[]
for p in sorted(Path('/sys/class/drm').glob('card*-Virtual-*')):
 rows.append({'name':p.name,'status':(p/'status').read_text().strip(),'modes':(p/'modes').read_text().splitlines(),'enabled':(p/'enabled').read_text().strip()})
print(json.dumps(rows))
"""
  result=vm.ssh('python3 -',input=probe,text=True,capture_output=True,check=True)
  receipt['connectors']=json.loads(result.stdout)
  receipt['two_connectors_observed']=len(receipt['connectors'])==2
  assert receipt['two_connectors_observed']
  result=vm.ssh('sudo -n python3 -',input=Path('/tmp/agentos-hotplug-fixed-v1-guest.py').read_text(),text=True,capture_output=True,check=False,timeout=180)
  Path('/tmp/agentos-hotplug-fixed-v1-guest-output.log').write_text(result.stdout+result.stderr)
  for remote,local in [('/tmp/agentos-hotplug-fixed-v1.log','/tmp/agentos-hotplug-fixed-v1.log'),('/tmp/agentos-hotplug-fixed-v1.json','/tmp/agentos-hotplug-fixed-v1.json')]:
   observed=vm.ssh('sudo -n cat '+remote,capture_output=True,check=False)
   if observed.returncode==0:Path(local).write_bytes(observed.stdout)
  assert result.returncode==0,'Virtual KMS probe failed; full guest trace retained in /tmp/agentos-hotplug-fixed-v1-guest-output.log'
  receipt['virtual_kms']=json.loads(result.stdout)

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
  Path('/tmp/agentos-hotplug-fixed-v1-driver.json').write_text(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(receipt),flush=True)
