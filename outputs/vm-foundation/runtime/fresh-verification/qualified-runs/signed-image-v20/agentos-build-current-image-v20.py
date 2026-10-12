import subprocess,io,tarfile,sys,os,signal,time
from pathlib import Path
root=Path('/Users/chrisjdavis/development/716-ui')
sys.path.insert(0,'outputs/vm-foundation');import vm
os.environ['AGENT_OS_IMAGE_OWNERSHIP']='/tmp/agentos-v20-build-ownership.json'
import agentos_image_owned_utm as ownership
started=False
try:
 assert vm.status()=='stopped'
 started=True
 vm.start();vm.wait_ready(60)

 import json,hashlib
 assert not subprocess.check_output(['git','status','--porcelain'],text=True).strip(), 'Commit source before image build'
 report=json.loads((vm.RUN/'reproduction.json').read_text())
 assert report['result']=='pass' and len(report['checks'])==70
 sys.path.insert(0,'outputs/agent-shell');import deploy
 assert report['deployment']['source_archive_sha256']==hashlib.sha256(deploy.source_archive()).hexdigest(), 'Image sources differ from complete70 deployment'
 assert not report['deployment']['source_changes'], 'Image must use the clean complete70 source'
 out=Path('outputs/vm-foundation/runtime/release-artifacts')
 assert not (out/'candidate-v20.qcow2').exists()
 archive=io.BytesIO()
 with tarfile.open(fileobj=archive,mode='w') as tar:
  for name in subprocess.check_output(['git','ls-files','outputs/vm-foundation'],text=True).splitlines():
   path=Path(name)
   if path.is_file():tar.add(path,arcname=str(path.relative_to('outputs')),recursive=False)
 vm.ssh('sudo -n tar xf - -C /home/developer/agentos-image-inputs',input=archive.getvalue(),check=True)
 vm.ssh('df -h /home/developer/agentos-image-inputs',check=True)
 vm.ssh('cd /home/developer/agent-os-source/native-compositor && cargo build --locked --examples',check=True)
 for helper in ('presentation_fixture','ime_fixture'):
  fixture=out/('qualification-v20-'+helper)
  source='/home/developer/agent-os-source/native-compositor/target/debug/examples/'+helper
  expected=vm.ssh('sha256sum '+source,capture_output=True,text=True,check=True).stdout.split()[0]
  if not fixture.exists():
   with fixture.open('xb') as target:vm.ssh('cat '+source,stdout=target,check=True)
  assert hashlib.sha256(fixture.read_bytes()).hexdigest()==expected, 'Qualification helper differs from the compiled source'
 image_runtime=vm.ssh("python3 -c 'from pathlib import Path; print(Path(\"/usr/local/lib/agent-os/current\").resolve().name)'",capture_output=True,text=True,check=True).stdout.strip()
 assert image_runtime==report['runtime_release'], 'Image must use the complete70 runtime'
 current=json.loads(vm.ssh('cat /usr/local/lib/agent-os/current/manifest.json',capture_output=True,text=True,check=True).stdout)
 prior=json.loads(vm.ssh('cat /usr/local/lib/agent-os/releases/'+report['runtime_release']+'/manifest.json',capture_output=True,text=True,check=True).stdout)
 names=['agent-os-core','native/agent-os-desktop','native/agent-os-compositor']
 assert all(current[name]==prior[name] for name in names)
 (out/'qualification-v20-binary-equivalence.json').write_text(json.dumps({'factory_source_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'runtime_source_revision':report['deployment']['repository_revision'],'source_archive_sha256':report['deployment']['source_archive_sha256'],'qualified_runtime':report['runtime_release'],'image_runtime':image_runtime,'binaries':{name:current[name] for name in names}},indent=2)+'\n')
 Path('/tmp/agentos-v20-build-source-frozen').write_text(report['deployment']['source_archive_sha256']+'\n')
 vm.ssh('sudo -n python3 /home/developer/agentos-image-inputs/vm-foundation/build_release_image.py --dedicated-builder --compress --base /home/developer/agentos-image-inputs/base.qcow2 --output /home/developer/agentos-image-inputs/agentos-release-v20.qcow2 --bootstrap /home/developer/agent-os-source/bootstrap.py --update-key /home/developer/agentos-image-inputs/update-signing-key.pem',check=True)
 for suffix in ('qcow2','json'):
  with (out/('candidate-v20.'+suffix)).open('xb') as target:
   vm.ssh('sudo -n cat /home/developer/agentos-image-inputs/agentos-release-v20.'+suffix,stdout=target,check=True)
 metadata=json.loads((out/'candidate-v20.json').read_text())
 assert metadata['runtime_release']==image_runtime
 digest=hashlib.sha256()
 with (out/'candidate-v20.qcow2').open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
 assert digest.hexdigest()==metadata['image_sha256']
 print('New clean image transferred and hash verified:',digest.hexdigest(),flush=True)
 subprocess.run([sys.executable,'outputs/vm-foundation/package_release_image.py','create','--image',str(out/'candidate-v20.qcow2'),'--metadata',str(out/'candidate-v20.json'),'--signing-key',str(out/'image-signing.pem'),'--output',str(out/'candidate-v20.utm')],check=True)
 subprocess.run([sys.executable,'outputs/vm-foundation/package_release_image.py','verify',str(out/'candidate-v20.utm'),'--trusted-key',str(out/'update-signing-key.pem')],check=True)

finally:
 if started:
  vm.stop();deadline=time.monotonic()+45
  while vm.status()!='stopped':
   if time.monotonic()>deadline:raise RuntimeError('VM did not stop; exact owned app retained')
   time.sleep(.5)
 ownership.close()
 print('Owned image-builder guest and exact UTM app stopped',flush=True)
