import os,sys,subprocess,json,time,datetime,hashlib,gzip
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification';os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path[:0]=['outputs/vm-foundation','outputs/agent-shell'];import vm,deploy
from utm_ownership import UTMApplicationOwnership
r={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'passed':False,'source_archive_sha256':hashlib.sha256(deploy.source_archive()).hexdigest(),'checks':[]}
with UTMApplicationOwnership(vm) as owner:
 try:
  assert vm.status()=='stopped';vm.start();vm.wait_ready(60)
  subprocess.run([sys.executable,'outputs/agent-shell/deploy.py'],check=True)
  r['deployment']=json.loads((vm.RUN/'deployment.json').read_text())
  r['runtime_release']=json.loads(vm.ssh('cat /etc/agent-os/release.json',capture_output=True,text=True,check=True).stdout)['runtime_release']
  checks=[('native-build','cargo test --locked --manifest-path native-shell/Cargo.toml && cargo build --locked --manifest-path native-shell/Cargo.toml --examples && cargo build --locked --manifest-path native-shell/Cargo.toml && cargo build --locked --manifest-path native-compositor/Cargo.toml --examples && cargo build --locked --manifest-path native-compositor/Cargo.toml')]
  checks += [('native-'+appearance+'-'+str(scale),'dbus-run-session -- python3 native-shell/tests/native_desktop.py --appearance '+appearance+' --text-scale '+str(scale)) for appearance in ('dark','light') for scale in (1,2)]
  checks += [('native-compositor','dbus-run-session -- python3 native-shell/tests/native_desktop.py --compositor'),('native-shared','dbus-run-session -- python3 native-shell/tests/native_desktop.py --compositor --shared'),('reader','sudo -n python3 tests/direct_display_guest.py --screen-reader-input'),('loaded','sudo -n python3 tests/direct_display_guest.py --native-feedback-load'),('idle','sudo -n python3 tests/direct_display_guest.py --native-feedback')]
  for name,command in checks:
   with Path('/tmp/agentos-activity-chooser-fixed-'+name+'.log').open('w') as out:vm.ssh('cd /home/developer/agent-os-source && '+command,stdout=out,stderr=subprocess.STDOUT,check=True,timeout=300)
   r['checks'].append(name);print('PASS:',name,flush=True)
  r['passed']=True
 finally:
  raw=vm.ssh('sudo -n cat /home/developer/agent-os-source/test-output/orca-kernel-speech.log',capture_output=True,check=False).stdout
  Path('/tmp/agentos-activity-chooser-fixed-reader-speech.log.gz').write_bytes(gzip.compress(raw,mtime=0));r['reader_raw_sha256']=hashlib.sha256(raw).hexdigest()
  vm.stop();deadline=time.monotonic()+60
  while vm.status()!='stopped':
   assert time.monotonic()<deadline;time.sleep(.5)
  r['owned_utm_closed']=owner.close();r['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();Path('/tmp/agentos-activity-chooser-fixed.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True)
