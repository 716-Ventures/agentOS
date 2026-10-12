import sys,pathlib,shutil,time,plistlib,subprocess,os,signal
sys.path.insert(0,'outputs/vm-foundation');import vm
import agentos_image_owned_utm as ownership
assert vm.status()=='stopped'
assert vm.call([vm.controller(),'status','4A6AFE90-531B-47F5-8109-8CF67234EB14'],capture_output=True,text=True).stdout.strip()=='stopped'
ownership.close()
bundle=pathlib.Path(vm.machine()['bundle']);data=bundle/'Data';backup=vm.RUN/'pre-candidate-v23-attempt3'
backup.mkdir(exist_ok=False)
for name in ['disk.qcow2','efi_vars.fd']:
 (data/name).rename(backup/name)
shutil.copyfile(bundle/'config.plist',backup/'config.plist')
source=vm.RUN/'candidate-v23-interrupted-1791798834593573000-disk.qcow2'
import hashlib,json
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
expected=h(source);shutil.copyfile(source,data/'disk.qcow2');assert h(data/'disk.qcow2')==expected
shutil.copyfile(vm.RUN/'candidate-v23-interrupted-1791798834593816000-efi_vars.fd',data/'efi_vars.fd')
(vm.RUN/'image-v23-resume-copy.json').write_text(json.dumps({'source':str(source),'source_sha256':expected,'copy_sha256':h(data/'disk.qcow2'),'resumes_completed_firstboot_and_twelve_direct_profiles':True},indent=2)+'\n')
config=plistlib.loads((bundle/'config.plist').read_bytes());config['Drive']=[drive for drive in config['Drive'] if drive.get('ImageName')=='disk.qcow2'];assert len(config['Drive'])==1
(bundle/'config.plist').write_bytes(plistlib.dumps(config,sort_keys=False))
print('Prepared exact clone of preserved first-attempt image copy; original remains retained',flush=True)
vm.start()
