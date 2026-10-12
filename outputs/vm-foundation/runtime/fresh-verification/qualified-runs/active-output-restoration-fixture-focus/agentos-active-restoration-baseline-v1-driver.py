import os,sys,json,time,hashlib,plistlib,datetime
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification'
os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation')
import vm
from utm_ownership import UTMApplicationOwnership
config_path=Path(vm.machine()['bundle'])/'config.plist'
original=config_path.read_bytes()
Path('/tmp/agentos-active-restoration-baseline-v1-original-config.plist').write_bytes(original)
data=config_path.parent/'Data'
disk_inodes={name:(data/name).stat().st_ino for name in ('disk.qcow2','efi_vars.fd')}
config=plistlib.loads(original)
assert len(config['Display'])==1 and config['Display'][0]['Hardware']=='virtio-gpu-gl-pci'
assert not config['QEMU']['AdditionalArguments']
config['QEMU']['AdditionalArguments']=['-global','virtio-gpu-gl-pci.max_outputs=2']
receipt={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_config_sha256':hashlib.sha256(original).hexdigest(),'purpose':'Targeted live launcher/keyboard virtual recovery on unchanged complete70 production binaries; not physical hotplug'}
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
  full=json.loads((vm.RUN/'reproduction.json').read_text())
  revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
  assert revision=='5e0058b7bd26556f2498203fb48774342cda856c'
  assert not subprocess.check_output(['git','status','--porcelain'])
  assert full['result']=='pass' and len(full['checks'])==70 and not full['deployment']['source_changes']
  import tarfile,io
  frozen=Path('/tmp/agentos-activation-qualified-source-v1.tar').read_bytes()
  assert hashlib.sha256(frozen).hexdigest()==full['deployment']['source_archive_sha256']
  new=deploy.source_archive()
  receipt['targeted_source_archive_sha256']=hashlib.sha256(new).hexdigest()
  Path('/tmp/agentos-active-restoration-baseline-v1-source.tar').write_bytes(new)
  def members(raw):
   with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
    return {p.name:archive.extractfile(p).read() for p in archive if p.isfile()}
  old_files,new_files=members(frozen),members(new)
  allowed={'tests/direct_display_guest.py','tests/direct_input_probe.py','tests/direct_shell_hotplug_probe.py','LAYOUT.md','native-shell/README.md'}
  changes={name for name in old_files.keys()|new_files.keys() if old_files.get(name)!=new_files.get(name)}
  assert changes==allowed,changes
  receipt['source_changes']=subprocess.check_output(['git','status','--porcelain'],text=True).splitlines()
  receipt['qualified_production_source_archive_sha256']=full['deployment']['source_archive_sha256']
  receipt['test_only_source_changes']=sorted(changes)
  receipt['targeted_test_source_sha256']={name:hashlib.sha256(new_files[name]).hexdigest() for name in allowed}
  overlay=io.BytesIO()
  with tarfile.open(fileobj=overlay,mode='w') as archive:
   for name in sorted(allowed):
    info=tarfile.TarInfo(name);info.size=len(new_files[name]);info.mode=0o644
    archive.addfile(info,io.BytesIO(new_files[name]))
  Path('/tmp/agentos-active-restoration-baseline-v1-overlay.tar').write_bytes(overlay.getvalue())
  vm.ssh('tar xf - -C /home/developer/agent-os-source',input=overlay.getvalue(),check=True)
  for name in allowed:
   observed=vm.ssh('sha256sum /home/developer/agent-os-source/'+name,capture_output=True,text=True,check=True).stdout.split()[0]
   assert observed==receipt['targeted_test_source_sha256'][name],name
  actual=vm.ssh('readlink -f /usr/local/lib/agent-os/current',capture_output=True,text=True,check=True).stdout.strip().rsplit('/',1)[-1]
  assert actual==full['runtime_release']
  for local,remote in [('outputs/agent-shell/tests/direct_multi_output_probe.py','tests/direct_multi_output_probe.py'),('outputs/agent-shell/tests/direct_input_probe.py','tests/direct_input_probe.py'),('outputs/agent-shell/tests/direct_display_guest.py','tests/direct_display_guest.py'),('outputs/native-compositor/examples/presentation_fixture.rs','native-compositor/examples/presentation_fixture.rs'),('outputs/native-compositor/src/input.rs','native-compositor/src/input.rs'),('outputs/native-compositor/src/pointer_geometry.rs','native-compositor/src/pointer_geometry.rs'),('outputs/native-compositor/src/direct.rs','native-compositor/src/direct.rs'),('outputs/native-shell/tests/native_desktop.py','native-shell/tests/native_desktop.py'),('outputs/native-compositor/src/state.rs','native-compositor/src/state.rs'),('outputs/native-compositor/src/control.rs','native-compositor/src/control.rs'),('outputs/agent-shell/tests/direct_table_probe.py','tests/direct_table_probe.py')]:
   expected=hashlib.sha256(Path(local).read_bytes()).hexdigest()
   observed=vm.ssh('sha256sum /home/developer/agent-os-source/'+remote,capture_output=True,text=True,check=True).stdout.split()[0]
   assert observed==expected,remote
  receipt.update(source_revision=revision,qualified_runtime_source_archive_sha256=full['deployment']['source_archive_sha256'],installed_runtime=actual,source_clean=not receipt['source_changes'])
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
  result=vm.ssh('sudo -n python3 -',input=Path('/tmp/agentos-active-restoration-baseline-v1-guest.py').read_text(),text=True,capture_output=True,check=False,timeout=180)
  Path('/tmp/agentos-active-restoration-baseline-v1-guest-output.log').write_text(result.stdout+result.stderr)
  for remote,local in [('/tmp/agentos-active-restoration-baseline-v1-0.log','/tmp/agentos-active-restoration-baseline-v1-0.log'),('/tmp/agentos-active-restoration-baseline-v1-1.log','/tmp/agentos-active-restoration-baseline-v1-1.log'),('/tmp/agentos-active-restoration-baseline-v1.json','/tmp/agentos-active-restoration-baseline-v1.json')]:
   observed=vm.ssh('sudo -n cat '+remote,capture_output=True,check=False)
   if observed.returncode==0:Path(local).write_bytes(observed.stdout)
  assert result.returncode==0,'Virtual KMS probe failed; full guest trace retained in /tmp/agentos-active-restoration-baseline-v1-guest-output.log'
  receipt['virtual_kms']=json.loads(result.stdout)
  assert len(receipt['virtual_kms']['cases'])==1
  assert all(row['kms_session']['virtual_shell_hotplug_qualified'] for row in receipt['virtual_kms']['cases'])
  assert receipt['virtual_kms']['cases'][0]['kms_session']['virtual_shell_hotplug_qualified']

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
  Path('/tmp/agentos-active-restoration-baseline-v1-driver.json').write_text(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(receipt),flush=True)
