from pathlib import Path
import os,sys,time,hashlib,gzip
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification'
os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation');import vm
log=Path('/tmp/agentos-launcher-full70.log');deadline=time.monotonic()+900
while 'PASS: native-session-screen-reader' not in log.read_text().splitlines():
 assert time.monotonic()<deadline,'Installed reader capture timed out'
 assert 'Traceback (most recent call last):' not in log.read_text(),'Full run failed before reader capture'
 time.sleep(.2)
raw=vm.ssh('cat /home/developer/agent-os-source/native-shell/test-output/reader-validation-speech.log',capture_output=True,check=True).stdout
assert b'Reader result outcome: failed' in raw and b'Reader failure outcome: failed' in raw
Path('/tmp/agentos-launcher-full70-installed-speech.log.gz').write_bytes(gzip.compress(raw,mtime=0))
print('Captured installed actual outcome speech SHA-256:',hashlib.sha256(raw).hexdigest(),flush=True)

while 'PASS: direct-display-screen-reader' not in log.read_text().splitlines():
 assert time.monotonic()<deadline,'Direct reader capture timed out'
 assert 'Traceback (most recent call last):' not in log.read_text(),'Full run failed before direct reader capture'
 time.sleep(.2)
raw=vm.ssh('sudo -n cat /home/developer/agent-os-source/test-output/orca-kernel-speech.log',capture_output=True,check=True).stdout
Path('/tmp/agentos-launcher-full70-direct-speech.log.gz').write_bytes(gzip.compress(raw,mtime=0))
print('Captured installed launcher actual speech SHA-256:',hashlib.sha256(raw).hexdigest(),flush=True)
