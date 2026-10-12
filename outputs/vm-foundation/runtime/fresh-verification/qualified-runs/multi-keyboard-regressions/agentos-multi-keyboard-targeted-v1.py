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
  Path('/tmp/agentos-multi-keyboard-targeted-v1-source.tar').write_bytes(deploy.source_archive())
  runpy.run_path('outputs/agent-shell/deploy.py',run_name='__main__')
  receipt['deployment']=json.loads((vm.RUN/'deployment.json').read_text())
  receipt['installed_runtime']=vm.ssh('readlink -f /usr/local/lib/agent-os/current',capture_output=True,text=True,check=True).stdout.strip().rsplit('/',1)[-1]
  vm.ssh('cd /home/developer/agent-os-source && cargo test --locked --manifest-path native-compositor/Cargo.toml && cargo build --locked --manifest-path native-compositor/Cargo.toml --examples',check=True,timeout=240)
  guest="from pathlib import Path\nimport subprocess,json\nroot=Path('/home/developer/agent-os-source');release=Path('/usr/local/lib/agent-os/current').resolve();report={'runtime_release':release.name,'cases':[]}\ncases=[['python3',str(root/'tests/direct_display_guest.py'),*flags] for flags in [['--input'],['--input','--fresh-profile'],['--screen-reader-input']]]\nfor i,argv in enumerate(cases):\n result=subprocess.run(argv,cwd=root,capture_output=True,text=True,timeout=240)\n Path(f'/tmp/agentos-multi-keyboard-targeted-v1-{i}.log').write_text(result.stdout+result.stderr)\n report['cases'].append({'argv':argv,'returncode':result.returncode})\n if result.returncode!=0:break\nPath('/tmp/agentos-multi-keyboard-targeted-v1.json').write_text(json.dumps(report,indent=2)+'\\n');print(json.dumps(report))\n"
  result=vm.ssh('sudo -n python3 -',input=guest,text=True,capture_output=True,timeout=1000)
  Path('/tmp/agentos-multi-keyboard-targeted-v1-guest.log').write_text(result.stdout+result.stderr)
  for suffix in [*[f'-{i}.log' for i in range(3)],'.json']:
   r=vm.ssh('sudo -n cat /tmp/agentos-multi-keyboard-targeted-v1'+suffix,capture_output=True)
   if r.returncode==0:Path('/tmp/agentos-multi-keyboard-targeted-v1'+suffix).write_bytes(r.stdout)
  assert result.returncode==0,'A/B diagnostics failed before complete measurements'
  receipt['measurements']=json.loads(result.stdout)
  assert len(receipt['measurements']['cases'])==3 and all(r['returncode']==0 for r in receipt['measurements']['cases']),'Multiple keyboard target verification failed'
 finally:
  vm.stop();end=time.monotonic()+60
  while vm.status()!='stopped':
   assert time.monotonic()<end;time.sleep(.5)
  receipt['owned_utm_closed']=owner.close()
  assert vm.utm_application_identity() is None
  assert (bundle/'config.plist').read_bytes()==config
  assert all((bundle/'Data'/n).stat().st_ino==ino for n,ino in inodes.items())
  receipt.update(original_config_unchanged=True,original_disk_efi_inodes_preserved=True)
  Path('/tmp/agentos-multi-keyboard-targeted-v1-driver.json').write_text(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(receipt),flush=True)
