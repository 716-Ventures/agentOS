import os,sys,json,time,hashlib,plistlib,datetime
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification'
os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation')
import vm
from utm_ownership import UTMApplicationOwnership
config_path=Path(vm.machine()['bundle'])/'config.plist'
original=config_path.read_bytes()
Path('/tmp/agentos-multihead-original-config.plist').write_bytes(original)
data=config_path.parent/'Data'
disk_inodes={name:(data/name).stat().st_ino for name in ('disk.qcow2','efi_vars.fd')}
config=plistlib.loads(original)
assert len(config['Display'])==1 and config['Display'][0]['Hardware']=='virtio-gpu-gl-pci'
assert not config['QEMU']['AdditionalArguments']
config['QEMU']['AdditionalArguments']=['-global','virtio-gpu-gl-pci.max_outputs=2']
receipt={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_config_sha256':hashlib.sha256(original).hexdigest(),'purpose':'Enumerate a second virtual connector on one GPU; not physical or host-view qualification'}
with UTMApplicationOwnership(vm) as owner:
 try:
  assert vm.status()=='stopped'
  owner.close()
  config_path.write_bytes(plistlib.dumps(config))
  vm.start();vm.wait_ready(60)
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
  script="""from pathlib import Path
import json
rows=[]
for p in sorted(Path('/sys/class/drm').glob('card[0-9]*')):
 if '-' in p.name:continue
 rows.append({'card':p.name,'path':str(p.resolve()),'device':str((p/'device').resolve()),'driver_exists':(p/'device/driver').exists(),'driver':str((p/'device/driver').resolve()),'module':str((p/'device/driver/module').resolve()),'device_uevent':(p/'device/uevent').read_text() if (p/'device/uevent').exists() else None})
print(json.dumps(rows))
"""
  result=vm.ssh('python3 -',input=script,text=True,capture_output=True,check=True)
  receipt['driver_identities']=json.loads(result.stdout)

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
  Path('/tmp/agentos-multihead-driver-identity.json').write_text(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(receipt),flush=True)
