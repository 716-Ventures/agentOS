import os,sys,time,subprocess,json,hashlib,plistlib
from pathlib import Path
sys.path.insert(0,'outputs/vm-foundation');import vm
import agentos_image_owned_utm as ownership
bundle=Path(vm.machine()['bundle']);config_path=bundle/'config.plist'
original=config_path.read_bytes();config=plistlib.loads(original)
assert len(config['Display'])==1 and config['Display'][0]['Hardware']=='virtio-gpu-gl-pci'
assert not config['QEMU']['AdditionalArguments']
data=bundle/'Data';inodes={n:(data/n).stat().st_ino for n in ('disk.qcow2','efi_vars.fd')}
args=vm.ssh_args();args[-1]='verifier@127.0.0.1'
args=[('UserKnownHostsFile='+str(vm.RUN/'image-v23-attempt1-known-hosts') if x.startswith('UserKnownHostsFile=') else x) for x in args]
def ssh(cmd,**kw):return subprocess.run(args+[cmd],**kw)
def stop():
 vm.stop();end=time.monotonic()+60
 while vm.status()!='stopped':
  assert time.monotonic()<end,'Image guest shutdown unconfirmed'
  time.sleep(.5)
 ownership.close()
 assert vm.utm_application_identity() is None
 for name in inodes:
  r=subprocess.run(['/usr/sbin/lsof','-n','-Fpcn',str(data/name)],capture_output=True,text=True)
  assert r.returncode==1 and not r.stdout,'Image disk remains open'
def start():
 vm.start();end=time.monotonic()+75
 # Remote access is deliberately disabled in the distribution. Start the
 # already-authorized qualification transport via the guest agent on each boot.
 while True:
  agent=vm.call([vm.controller(),'exec',vm.machine()['uuid'],'--cmd','/bin/systemctl','start','ssh'],capture_output=True,text=True,timeout=12)
  if agent.returncode==0 and not agent.stdout.strip() and not agent.stderr.strip():break
  assert time.monotonic()<end,'Image guest agent unavailable'
  time.sleep(.5)
 while True:
  r=ssh('true',capture_output=True,timeout=12)
  if r.returncode==0:return
  assert time.monotonic()<end,'Image verification login unavailable'
  time.sleep(.5)
receipt={'original_config_sha256':hashlib.sha256(original).hexdigest(),'physical_hotplug_qualified':False}
passed=False
stop()
try:
 config['QEMU']['AdditionalArguments']=['-global','virtio-gpu-gl-pci.max_outputs=2']
 config_path.write_bytes(plistlib.dumps(config))
 start()
 expected=json.loads(Path('outputs/vm-foundation/runtime/release-artifacts/candidate-v23.json').read_text())['runtime_release']
 actual=ssh('readlink -f /usr/local/lib/agent-os/current',capture_output=True,text=True,check=True).stdout.strip().rsplit('/',1)[-1]
 assert actual==expected;receipt['installed_runtime']=actual
 guest=Path('/tmp/agentos-restoration-clean-v1-guest.py').read_text().replace('/home/developer/agent-os-source','/home/verifier/qualification').replace('agentos-restoration-clean-v1','agentos-image-v23-output-restoration')
 result=ssh('sudo -n python3 -',input=guest,text=True,capture_output=True,timeout=700)
 Path('/tmp/agentos-image-v23-output-restoration-guest.log').write_text(result.stdout+result.stderr)
 for suffix in [*[f'-{i}.log' for i in range(4)],'.json']:
  r=ssh('sudo -n cat /tmp/agentos-image-v23-output-restoration'+suffix,capture_output=True)
  if r.returncode==0:Path('/tmp/agentos-image-v23-output-restoration'+suffix).write_bytes(r.stdout)
 r=ssh('sudo -n cat /home/verifier/qualification/test-output/preferred-output-restoration.png',capture_output=True)
 if r.returncode==0:Path('/tmp/agentos-image-v23-output-restoration.png').write_bytes(r.stdout)
 assert result.returncode==0,'Image virtual output restoration failed; exact logs retained'
 receipt['virtual_kms']=json.loads(result.stdout)
 assert len(receipt['virtual_kms']['cases'])==4 and all(r['kms_session']['result']=='pass' for r in receipt['virtual_kms']['cases'])
 passed=True
finally:
 stop();config_path.write_bytes(original)
 assert config_path.read_bytes()==original
 assert all((data/n).stat().st_ino==inode for n,inode in inodes.items())
 receipt.update(result='pass' if passed else 'failed',original_config_restored=True,image_disk_efi_inodes_preserved=True,temporary_two_head_guest_stopped=True,temporary_owned_utm_closed=True)
 (vm.RUN/'image-v23-output-restoration.json').write_text(json.dumps(receipt,indent=2)+'\n')
 if passed:start()
print('Fresh signed image passes all four virtual output restoration modes; original one-head configuration restored',flush=True)
