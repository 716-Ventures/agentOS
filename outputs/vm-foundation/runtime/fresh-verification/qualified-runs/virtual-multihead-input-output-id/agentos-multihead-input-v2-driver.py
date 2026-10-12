import os,sys,json,time,hashlib,plistlib,datetime
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification'
os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation')
import vm
from utm_ownership import UTMApplicationOwnership
config_path=Path(vm.machine()['bundle'])/'config.plist'
original=config_path.read_bytes()
Path('/tmp/agentos-multihead-input-v2-original-config.plist').write_bytes(original)
data=config_path.parent/'Data'
disk_inodes={name:(data/name).stat().st_ino for name in ('disk.qcow2','efi_vars.fd')}
config=plistlib.loads(original)
assert len(config['Display'])==1 and config['Display'][0]['Hardware']=='virtio-gpu-gl-pci'
assert not config['QEMU']['AdditionalArguments']
config['QEMU']['AdditionalArguments']=['-global','virtio-gpu-gl-pci.max_outputs=2']
receipt={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_config_sha256':hashlib.sha256(original).hexdigest(),'purpose':'Force one virtual connector for two-output KMS/VT qualification; not physical or host-view qualification'}
with UTMApplicationOwnership(vm) as owner:
 try:
  assert vm.status()=='stopped'
  owner.close()
  config_path.write_bytes(plistlib.dumps(config))
  vm.start();vm.wait_ready(60)
  import io,tarfile
  payload=io.BytesIO()
  with tarfile.open(fileobj=payload,mode='w') as archive:
   for local,remote in [('outputs/agent-shell/tests/direct_multi_output_probe.py','tests/direct_multi_output_probe.py'),('outputs/agent-shell/tests/direct_input_probe.py','tests/direct_input_probe.py'),('outputs/agent-shell/tests/direct_display_guest.py','tests/direct_display_guest.py'),('outputs/native-compositor/examples/presentation_fixture.rs','native-compositor/examples/presentation_fixture.rs')]:
    archive.add(local,arcname=remote)
  vm.ssh('tar xf - -C /home/developer/agent-os-source',input=payload.getvalue(),check=True)
  vm.ssh('cd /home/developer/agent-os-source && cargo build --locked --manifest-path native-compositor/Cargo.toml --example presentation_fixture',check=True,timeout=180)
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
  result=vm.ssh('sudo -n python3 -',input=Path('/tmp/agentos-multihead-input-guest-v2.py').read_text(),text=True,capture_output=True,check=False,timeout=180)
  Path('/tmp/agentos-multihead-input-v2-guest-output.log').write_text(result.stdout+result.stderr)
  for remote,local in [('/tmp/agentos-multihead-input-v2.log','/tmp/agentos-multihead-input-v2.log'),('/tmp/agentos-multihead-input-v2.json','/tmp/agentos-multihead-input-v2.json')]:
   observed=vm.ssh('sudo -n cat '+remote,capture_output=True,check=False)
   if observed.returncode==0:Path(local).write_bytes(observed.stdout)
  assert result.returncode==0,'Virtual KMS probe failed; full guest trace retained in /tmp/agentos-multihead-input-v2-guest-output.log'
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
  Path('/tmp/agentos-multihead-input-v2-driver.json').write_text(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(receipt),flush=True)
