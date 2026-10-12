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
  vm.ssh('cd /home/developer/agent-os-source && cargo test --locked --manifest-path native-shell/Cargo.toml && cargo build --locked --manifest-path native-shell/Cargo.toml && cargo build --locked --manifest-path native-compositor/Cargo.toml --examples',check=True,timeout=300)
  for appearance in ('light','dark'):
   for scale in (1,2):vm.ssh('cd /home/developer/agent-os-source && dbus-run-session -- python3 native-shell/tests/native_desktop.py --appearance '+appearance+' --text-scale '+str(scale),check=True,timeout=180)
  for flags in ('--compositor','--compositor --shared'):vm.ssh('cd /home/developer/agent-os-source && dbus-run-session -- python3 native-shell/tests/native_desktop.py '+flags,check=True,timeout=180)
  vm.ssh('cd /home/developer/agent-os-source && dbus-run-session -- python3 native-shell/tests/native_session.py --screen-reader --installed --reader-controls --reader-outcomes',check=True,timeout=240)
  raw=vm.ssh('cat /home/developer/agent-os-source/native-shell/test-output/reader-validation-speech.log',capture_output=True,check=True).stdout
  Path('/tmp/agentos-status-quiet-targeted-speech.log.gz').write_bytes(gzip.compress(raw,mtime=0))
  active=False;spoken=[]
  for line in raw.decode(errors='replace').splitlines():
   if 'START ' in line and 'OBJECT EVENT ' in line:active='OBJECT:ANNOUNCEMENT' in line
   if active and 'SPEECH OUTPUT:' in line and 'failed' in line:spoken.append(line)
   if 'END ' in line and 'OBJECT EVENT ' in line:active=False
  receipt['failed_announcement_speech']=spoken;receipt['raw_speech_sha256']=hashlib.sha256(raw).hexdigest()
  assert len(spoken)==3,spoken
  for message in ('Reader result outcome: failed','Reader failure outcome: failed','failed'):assert sum(('SPEECH OUTPUT: '+repr(message)+'{') in x for x in spoken)==1
  receipt['passed']=True
 finally:
  vm.stop();deadline=time.monotonic()+45
  while vm.status()!='stopped':
   assert time.monotonic()<deadline;time.sleep(.5)
  receipt['owned_utm_closed']=owner.close();receipt['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();Path('/tmp/agentos-status-quiet-targeted.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt),flush=True)
