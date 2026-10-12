import sys,time,json
from pathlib import Path
sys.path.insert(0,'outputs/vm-foundation');import vm
import os
os.environ['AGENT_OS_IMAGE_OWNERSHIP']='/tmp/agentos-pointer-debounce-ownership.json'
import agentos_image_owned_utm as owner
if True:
 try:
  assert vm.status()=='stopped';vm.start();vm.wait_ready(60)
  r=vm.ssh('sudo -n python3 -',input=Path('/tmp/agentos-pointer-debounce-guest.py').read_text(),capture_output=True,text=True)
  Path('/tmp/agentos-pointer-debounce.json').write_text(r.stdout);Path('/tmp/agentos-pointer-debounce.log').write_text(r.stdout+r.stderr);print(r.stdout,r.stderr);assert r.returncode==0
 finally:
  vm.stop();end=time.monotonic()+45
  while vm.status()!='stopped':
   assert time.monotonic()<end;time.sleep(.5)
  owner.close()
