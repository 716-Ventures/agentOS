import os,sys,time,json,gzip,hashlib,subprocess,datetime
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification';os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation');import vm
from utm_ownership import UTMApplicationOwnership
root=vm.RUN
assert json.loads((root/'reproduction.json').read_text())['deployment']['repository_revision']=='ca4a112986464b5a70e58544bbae51620d911a59'
assert json.loads((root/'reproduction.json').read_text())['result']=='pass'
receipt={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'passed':False}
with UTMApplicationOwnership(vm) as owner:
 try:
  assert vm.status()=='stopped';vm.start();vm.wait_ready(60)
  with Path('/tmp/agentos-chrome-installed-reader-repeat.log').open('wb') as out:
   vm.ssh('cd /home/developer/agent-os-source && dbus-run-session -- python3 native-shell/tests/native_session.py --screen-reader --installed --reader-controls --reader-outcomes',stdout=out,stderr=subprocess.STDOUT,check=True,timeout=240)
  raw=vm.ssh('cat /home/developer/agent-os-source/native-shell/test-output/reader-validation-speech.log',capture_output=True,check=True).stdout
  Path('/tmp/agentos-chrome-installed-reader-repeat-speech.log.gz').write_bytes(gzip.compress(raw,mtime=0))
  active=False;spoken=[]
  for line in raw.decode(errors='replace').splitlines():
   if 'START ' in line and 'OBJECT EVENT ' in line:active='OBJECT:ANNOUNCEMENT' in line
   if active and 'SPEECH OUTPUT:' in line and 'failed' in line:spoken.append(line)
   if 'END ' in line and 'OBJECT EVENT ' in line:active=False
  receipt['failed_announcement_speech']=spoken;receipt['raw_speech_sha256']=hashlib.sha256(raw).hexdigest()
  assert len(spoken)==3,spoken
  assert sum('Reader result outcome: failed' in s for s in spoken)==1
  assert sum('Reader failure outcome: failed' in s for s in spoken)==1
  receipt['passed']=True
 finally:
  vm.stop();deadline=time.monotonic()+45
  while vm.status()!='stopped':
   assert time.monotonic()<deadline;time.sleep(.5)
  receipt['owned_utm_closed']=owner.close();receipt['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
  Path('/tmp/agentos-chrome-installed-reader-repeat.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt),flush=True)
