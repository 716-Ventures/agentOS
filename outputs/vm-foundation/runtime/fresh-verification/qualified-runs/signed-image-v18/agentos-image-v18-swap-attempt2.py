import sys,pathlib,shutil,time,plistlib,subprocess,os,signal
sys.path.insert(0,'outputs/vm-foundation');import vm
import agentos_image_owned_utm as ownership
assert vm.status()=='stopped'
assert vm.call([vm.controller(),'status','4A6AFE90-531B-47F5-8109-8CF67234EB14'],capture_output=True,text=True).stdout.strip()=='stopped'
ownership.close()
bundle=pathlib.Path(vm.machine()['bundle']);data=bundle/'Data';backup=vm.RUN/'pre-candidate-v18-attempt2'
backup.mkdir(exist_ok=False)
for name in ['disk.qcow2','efi_vars.fd']:
 (data/name).rename(backup/name)
shutil.copyfile(bundle/'config.plist',backup/'config.plist')
shutil.copyfile('outputs/vm-foundation/runtime/release-artifacts/candidate-v18.qcow2',data/'disk.qcow2')
config=plistlib.loads((bundle/'config.plist').read_bytes());config['Drive']=[drive for drive in config['Drive'] if drive.get('ImageName')=='disk.qcow2'];assert len(config['Drive'])==1
(bundle/'config.plist').write_bytes(plistlib.dumps(config,sort_keys=False))
print('Prepared separate verification copy with fresh EFI and no seed',flush=True)
vm.start()
