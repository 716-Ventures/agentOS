import os,sys,json,time,subprocess,hashlib
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification';os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation');import vm
from utm_ownership import UTMApplicationOwnership
bundle=Path(vm.machine()['bundle']);config=(bundle/'config.plist').read_bytes();inodes={n:(bundle/'Data'/n).stat().st_ino for n in ('disk.qcow2','efi_vars.fd')}
receipt={'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_clean':not subprocess.check_output(['git','status','--porcelain'])}
with UTMApplicationOwnership(vm) as owner:
 try:
  assert vm.utm_application_identity() is None
  vm.start();vm.wait_ready(60)
  import runpy
  sys.path.insert(0,'outputs/agent-shell');import deploy
  Path('/tmp/agentos-scene-sharing-targeted-v1-source.tar').write_bytes(deploy.source_archive())
  runpy.run_path('outputs/agent-shell/deploy.py',run_name='__main__')
  receipt['deployment']=json.loads((vm.RUN/'deployment.json').read_text())
  receipt['installed_runtime']=vm.ssh('readlink -f /usr/local/lib/agent-os/current',capture_output=True,text=True,check=True).stdout.strip().rsplit('/',1)[-1]
  vm.ssh('cd /home/developer/agent-os-source && cargo test --locked --manifest-path native-compositor/Cargo.toml -- --nocapture && cargo build --locked --manifest-path native-compositor/Cargo.toml --examples',check=True,timeout=240)
  guest=r'''from pathlib import Path
import subprocess,json,hashlib
old='e33cf49ba658e780eb61a23056a22e8b2974afa4d31ef294b662f92714a40410'
new='NEW_RUNTIME'
root=Path('/usr/local/lib/agent-os/releases');assert Path('/usr/local/lib/agent-os/current').resolve()==root/new
manifests={name:json.loads((root/name/'manifest.json').read_text()) for name in (old,new)}
assert manifests[old]['agent-os-core']==manifests[new]['agent-os-core'],'Core differs between A/B profiles'
report={'old_runtime':old,'candidate_runtime':new,'unchanged_core':manifests[new]['agent-os-core'],'cases':[]}
for i,(release,mode) in enumerate([(old,'load'),(new,'load'),(new,'load'),(old,'load'),(new,'idle'),(new,'rotated')]):
 argv=['python3','/home/developer/agent-os-source/tests/direct_display_guest.py','--native-feedback-load' if mode=='load' else '--native-feedback','--bin-dir',str(root/release/'native')]
 if mode=='rotated':argv+=['--output-transform','90']
 result=subprocess.run(argv,capture_output=True,text=True,timeout=150)
 Path(f'/tmp/agentos-scene-sharing-targeted-v1-{i}.log').write_text(result.stdout+result.stderr)
 prefix='Native GTK input-to-presentation measurement '
 rows=[json.loads(line[len(prefix):]) for line in result.stdout.splitlines() if line.startswith(prefix)]
 assert len(rows)==1,(i,result.returncode,result.stdout[-1000:],result.stderr[-1000:])
 row=rows[0];assert row['presented']==20 and row['invalid']==row['discarded']==row['pending']==0,row
 report['cases'].append({'runtime':release,'profile':mode,'returncode':result.returncode,'measurement':row})
Path('/tmp/agentos-scene-sharing-targeted-v1.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
'''
  guest=guest.replace('NEW_RUNTIME',receipt['installed_runtime'])
  result=vm.ssh('sudo -n python3 -',input=guest,text=True,capture_output=True,timeout=1000)
  Path('/tmp/agentos-scene-sharing-targeted-v1-guest.log').write_text(result.stdout+result.stderr)
  for suffix in [*[f'-{i}.log' for i in range(6)],'.json']:
   r=vm.ssh('sudo -n cat /tmp/agentos-scene-sharing-targeted-v1'+suffix,capture_output=True)
   if r.returncode==0:Path('/tmp/agentos-scene-sharing-targeted-v1'+suffix).write_bytes(r.stdout)
  assert result.returncode==0,'A/B diagnostics failed before complete measurements'
  receipt['measurements']=json.loads(result.stdout)
  assert all(r['returncode']==0 for r in receipt['measurements']['cases'] if r['runtime']==receipt['installed_runtime']),'New shared-scene runtime missed acceptance'
 finally:
  vm.stop();end=time.monotonic()+60
  while vm.status()!='stopped':
   assert time.monotonic()<end;time.sleep(.5)
  receipt['owned_utm_closed']=owner.close()
  assert vm.utm_application_identity() is None
  assert (bundle/'config.plist').read_bytes()==config
  assert all((bundle/'Data'/n).stat().st_ino==ino for n,ino in inodes.items())
  receipt.update(original_config_unchanged=True,original_disk_efi_inodes_preserved=True)
  Path('/tmp/agentos-scene-sharing-targeted-v1-driver.json').write_text(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(receipt),flush=True)
