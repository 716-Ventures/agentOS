import os,sys,time,signal,subprocess,json,hashlib
from pathlib import Path
sys.path.insert(0,'outputs/vm-foundation');import vm
os.environ['AGENT_OS_IMAGE_OWNERSHIP']='/tmp/agentos-v23-qualification-attempt3-ownership.json'
import agentos_image_owned_utm as ownership
bundle=Path(vm.machine()['bundle']);data=bundle/'Data';backup=vm.RUN/'pre-candidate-v23-attempt3'
assert not backup.exists()
assert not Path('outputs/vm-foundation/runtime/release-artifacts/verification-password-v23-attempt1').exists()
original={name:(data/name).stat().st_ino for name in ('disk.qcow2','efi_vars.fd')}
config=(bundle/'config.plist').read_bytes()
def close_app():
 ownership.close()
try:
 subprocess.run([sys.executable,'outputs/vm-foundation/package_release_image.py','verify','outputs/vm-foundation/runtime/release-artifacts/candidate-v23.utm','--trusted-key','outputs/vm-foundation/runtime/release-artifacts/update-signing-key.pem'],check=True)
 for name in ('agentos-image-v23-swap-attempt3.py','agentos-image-v23-check-transport.py','agentos-image-v23-pointer-overlay.py','agentos-image-v23-output-restoration.py','agentos-image-v23-lifecycle-attempt3.py'):
  print('Qualification step:',name,flush=True)
  subprocess.run([sys.executable,'/tmp/'+name],check=True)
finally:
 if backup.exists():
  vm.stop();deadline=time.monotonic()+45
  while vm.status()!='stopped':
   if time.monotonic()>deadline:raise RuntimeError('Guest stop unconfirmed; original disks retained in backup')
   time.sleep(.5)
  assert vm.call([vm.controller(),'status','4A6AFE90-531B-47F5-8109-8CF67234EB14'],capture_output=True,text=True).stdout.strip()=='stopped'
  close_app()
  for name in ('disk.qcow2','efi_vars.fd'):
   saved=backup/name
   if saved.exists():
    current=data/name
    if current.exists():
     archive=vm.RUN/('candidate-v23-interrupted-'+str(time.time_ns())+'-'+name)
     assert not archive.exists();current.rename(archive)
    saved.rename(current)
  if (backup/'config.plist').exists():(bundle/'config.plist').write_bytes((backup/'config.plist').read_bytes())
 else:close_app()
 assert all((data/name).stat().st_ino==inode for name,inode in original.items()),'Original development disks were not restored'
 assert (bundle/'config.plist').read_bytes()==config,'Development VM config was not restored'
 Path('outputs/vm-foundation/runtime/release-artifacts/verification-password-v23-attempt1').unlink(missing_ok=True)
 assert vm.utm_application_identity() is None
 print('Original development disk/EFI identities and configuration restored; owned UTM app closed',flush=True)
subprocess.run([sys.executable,'outputs/vm-foundation/package_release_image.py','verify','outputs/vm-foundation/runtime/release-artifacts/candidate-v23.utm','--trusted-key','outputs/vm-foundation/runtime/release-artifacts/update-signing-key.pem'],check=True)
