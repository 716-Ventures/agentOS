from pathlib import Path
import os,sys,shutil,subprocess,plistlib,time,json,hashlib
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification';os.environ['AGENT_OS_VM_SSH_PORT']='22221';os.environ['AGENT_OS_IMAGE_OWNERSHIP']='/tmp/agentos-v17-diagnostic-ownership.json'
sys.path.insert(0,'outputs/vm-foundation');import vm
import agentos_image_owned_utm as ownership
bundle=Path(vm.machine()['bundle']);data=bundle/'Data';backup=vm.RUN/'pre-v17-failure-diagnostics';backup.mkdir()
original={name:(data/name).stat().st_ino for name in ('disk.qcow2','efi_vars.fd')};configuration=(bundle/'config.plist').read_bytes()
failed=vm.RUN/'candidate-v17-interrupted-1791752966724430000-disk.qcow2';failed_efi=vm.RUN/'candidate-v17-interrupted-1791752966724665000-efi_vars.fd'
assert failed.is_file() and failed_efi.is_file()
controller=str(vm.controller());uuid=vm.machine()['uuid']
try:
 assert vm.status()=='stopped'
 for name in original:(data/name).rename(backup/name)
 shutil.copyfile(failed,data/'disk.qcow2');shutil.copyfile(failed_efi,data/'efi_vars.fd')
 config=plistlib.loads((vm.RUN/'pre-candidate-v17-attempt1/online-config.plist').read_bytes());config['Network']=[];(bundle/'config.plist').write_bytes(plistlib.dumps(config,sort_keys=False))
 vm.start(console_only=True)
 deadline=time.monotonic()+75
 while True:
  r=subprocess.run([controller,'exec',uuid,'--cmd','/bin/true'],capture_output=True,timeout=10)
  if r.returncode==0 and not r.stdout.strip() and not r.stderr.strip():break
  assert time.monotonic()<deadline;time.sleep(.5)
 raw=subprocess.check_output([controller,'file','pull',uuid,'/home/verifier/qualification/test-output/orca-kernel-speech.log'])
 Path('/tmp/agentos-v17-failed-offline-reader-speech.log').write_bytes(raw)
 print('Collected failed speech bytes/hash:',len(raw),hashlib.sha256(raw).hexdigest(),flush=True)
finally:
 vm.stop();deadline=time.monotonic()+45
 while vm.status()!='stopped':
  assert time.monotonic()<deadline;time.sleep(.5)
 ownership.close()
 for name in original:
  saved=backup/name
  if saved.exists():
   current=data/name
   if current.exists():current.unlink()
   saved.rename(current)
 (bundle/'config.plist').write_bytes(configuration)
 assert all((data/name).stat().st_ino==inode for name,inode in original.items())
 assert vm.utm_application_identity() is None
 backup.rmdir()
 print('Diagnostic copy removed; original development disk/EFI identities/config restored; owned app closed',flush=True)
