import os,sys,json,time,hashlib,plistlib,datetime
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification'
os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation')
import vm
from utm_ownership import UTMApplicationOwnership
config_path=Path(vm.machine()['bundle'])/'config.plist'
original=config_path.read_bytes()
Path('/tmp/agentos-restoration-clean-v1-original-config.plist').write_bytes(original)
data=config_path.parent/'Data'
disk_inodes={name:(data/name).stat().st_ino for name in ('disk.qcow2','efi_vars.fd')}
config=plistlib.loads(original)
assert len(config['Display'])==1 and config['Display'][0]['Hardware']=='virtio-gpu-gl-pci'
assert not config['QEMU']['AdditionalArguments']
config['QEMU']['AdditionalArguments']=['-global','virtio-gpu-gl-pci.max_outputs=2']
receipt={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_config_sha256':hashlib.sha256(original).hexdigest(),'purpose':'Exact clean-source secondary, primary and all-output synthetic connector recovery; not physical hotplug'}
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
  import subprocess
  sys.path.insert(0,'outputs/agent-shell');import deploy
  assert not subprocess.check_output(['git','status','--porcelain'])
  full=json.loads((vm.RUN/'reproduction.json').read_text())
  revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
  assert full['result']=='pass' and len(full['checks'])==70 and not full['deployment']['source_changes']
  assert revision==full['deployment']['repository_revision']
  assert hashlib.sha256(deploy.source_archive()).hexdigest()==full['deployment']['source_archive_sha256']
  actual=vm.ssh('readlink -f /usr/local/lib/agent-os/current',capture_output=True,text=True,check=True).stdout.strip().rsplit('/',1)[-1]
  assert actual==full['runtime_release']
  import io,tarfile
  with tarfile.open(fileobj=io.BytesIO(deploy.source_archive())) as bundle:
   expected={p.name:hashlib.sha256(bundle.extractfile(p).read()).hexdigest() for p in bundle if p.isfile()}
  observe="from pathlib import Path\nimport hashlib,json\nroot=Path('/home/developer/agent-os-source')\nprint(json.dumps({name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in "+repr(sorted(expected))+"}))\n"
  observed=json.loads(vm.ssh('python3 -',input=observe,text=True,capture_output=True,check=True).stdout)
  assert observed==expected,'Deployed source differs from clean committed source'
  receipt['all_deployed_source_files_verified']=len(expected)
  receipt.update(source_revision=revision,source_archive_sha256=full['deployment']['source_archive_sha256'],installed_runtime=actual,source_clean=True)
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
  result=vm.ssh('sudo -n python3 -',input=Path('/tmp/agentos-restoration-clean-v1-guest.py').read_text(),text=True,capture_output=True,check=False,timeout=700)
  Path('/tmp/agentos-restoration-clean-v1-guest-output.log').write_text(result.stdout+result.stderr)
  for remote,local in [*[(f'/tmp/agentos-restoration-clean-v1-{i}.log',f'/tmp/agentos-restoration-clean-v1-{i}.log') for i in range(4)],('/tmp/agentos-restoration-clean-v1.json','/tmp/agentos-restoration-clean-v1.json')]:
   observed=vm.ssh('sudo -n cat '+remote,capture_output=True,check=False)
   if observed.returncode==0:Path(local).write_bytes(observed.stdout)
  capture=vm.ssh('sudo -n cat /home/developer/agent-os-source/test-output/preferred-output-restoration.png',capture_output=True,check=False)
  if capture.returncode==0:Path('/tmp/agentos-restoration-clean-v1.png').write_bytes(capture.stdout)
  assert result.returncode==0,'Virtual KMS probe failed; full guest trace retained in /tmp/agentos-restoration-clean-v1-guest-output.log'
  receipt['virtual_kms']=json.loads(result.stdout)
  assert len(receipt['virtual_kms']['cases'])==4
  assert all(row['kms_session']['result']=='pass' for row in receipt['virtual_kms']['cases'])
  assert receipt['virtual_kms']['cases'][0]['kms_session']['virtual_explicit_output_restoration_qualified']
  assert receipt['virtual_kms']['cases'][2]['kms_session']['virtual_all_outputs_removed_qualified']
  assert receipt['virtual_kms']['cases'][3]['kms_session']['virtual_shell_hotplug_qualified']

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
  Path('/tmp/agentos-restoration-clean-v1-driver.json').write_text(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(receipt),flush=True)
