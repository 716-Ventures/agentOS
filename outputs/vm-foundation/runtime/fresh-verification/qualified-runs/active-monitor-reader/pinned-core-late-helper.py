import os,sys,subprocess,json,hashlib,time,gzip,datetime
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification';os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path[:0]=['outputs/vm-foundation','outputs/agent-shell'];import vm,deploy
from utm_ownership import UTMApplicationOwnership
receipt={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_changes':subprocess.check_output(['git','status','--porcelain'],text=True).splitlines(),'source_archive_sha256':hashlib.sha256(deploy.source_archive()).hexdigest(),'passed':False}
with UTMApplicationOwnership(vm) as owner:
 try:
  assert vm.status()=='stopped';vm.start();vm.wait_ready(60)
  subprocess.run([sys.executable,'outputs/agent-shell/deploy.py'],check=True)
  vm.ssh('cd /home/developer/agent-os-source && sudo -n python3 tests/direct_display_guest.py --screen-reader-input',check=True,timeout=240)
  raw=vm.ssh('sudo -n cat /home/developer/agent-os-source/test-output/orca-kernel-speech.log',capture_output=True,check=True).stdout
  Path('/tmp/agentos-active-monitor-pinned-speech.log.gz').write_bytes(gzip.compress(raw,mtime=0))
  receipt['raw_speech_sha256']=hashlib.sha256(raw).hexdigest()
  receipt['passed']=True
  receipt['deployment']=json.loads((vm.RUN/'deployment.json').read_text())
  receipt['runtime_release']=json.loads(vm.ssh('cat /etc/agent-os/release.json',capture_output=True,text=True,check=True).stdout)['runtime_release']
 finally:
  raw=vm.ssh('sudo -n cat /home/developer/agent-os-source/test-output/orca-kernel-speech.log',capture_output=True,check=False).stdout
  Path('/tmp/agentos-active-monitor-pinned-speech.log.gz').write_bytes(gzip.compress(raw,mtime=0))
  vm.stop();deadline=time.monotonic()+45
  while vm.status()!='stopped':
   assert time.monotonic()<deadline;time.sleep(.5)
  receipt['owned_utm_closed']=owner.close();receipt['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();Path('/tmp/agentos-active-monitor-pinned.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt),flush=True)
