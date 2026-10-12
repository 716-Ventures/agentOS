from pathlib import Path
import os,sys,time,gzip,hashlib
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification'
os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation');import vm
log=Path('/tmp/agentos-complete72-v1.log');deadline=time.monotonic()+1200
for check,remote,name in [('native-session-screen-reader','cat /home/developer/agent-os-source/native-shell/test-output/reader-validation-speech.log','installed'),('direct-display-screen-reader','sudo -n cat /home/developer/agent-os-source/test-output/orca-kernel-speech.log','direct')]:
 while 'PASS: '+check not in log.read_text().splitlines():
  assert time.monotonic()<deadline,'Reader evidence collection timed out'
  assert 'Traceback (most recent call last):' not in log.read_text(),'Runtime qualification failed before reader evidence collection'
  time.sleep(.2)
 raw=vm.ssh(remote,capture_output=True,check=True).stdout
 Path('/tmp/agentos-complete72-v1-'+name+'-speech.log.gz').write_bytes(gzip.compress(raw,mtime=0))
 if name=='installed':
  assert b'Reader result outcome: failed' in raw and b'Reader failure outcome: failed' in raw
  active=False;spoken=[]
  for line in raw.decode(errors='replace').splitlines():
   if 'START ' in line and 'OBJECT EVENT ' in line:active='OBJECT:ANNOUNCEMENT' in line
   if active and "SPEECH OUTPUT: 'failed'{" in line:spoken.append(line)
   if ('END ' in line or 'FINISHED ' in line) and 'OBJECT EVENT ' in line:active=False
  assert len(spoken)==1,spoken
 else:
  assert sum(b'SPEECH OUTPUT:' in line and b'Ask Agent text' in line for line in raw.splitlines())>=10
  direct=(vm.RUN/'direct-display-screen-reader.log').read_text()
  assert 'PASS: active Monitor reader selection ' in direct and '"trusted_clipboard_roundtrip": true' in direct
  assert '"failure_announcements": 1' in direct and '"reader_announced_reopens": 3' in direct
 Path('/tmp/agentos-complete72-v1-'+name+'-speech.log.gz').write_bytes(gzip.compress(raw,mtime=0))
 print('Captured',name,'raw speech SHA-256',hashlib.sha256(raw).hexdigest(),flush=True)
