import os,signal,subprocess,time,json,hashlib,shutil
from pathlib import Path
import sys
sys.path.insert(0,'outputs/vm-foundation')
import vm
expected=(74546,'Sun Oct 11 23:35:59 2026')
assert vm.utm_application_identity()==expected,vm.utm_application_identity()
rows=subprocess.check_output(['ps','-axo','comm='],text=True).splitlines()
assert not any('qemu' in r.lower() or 'QEMULauncher' in r for r in rows)
config=Path('outputs/vm-foundation/runtime/fresh-verification/agentOS.utm/config.plist')
for name in ('disk.qcow2','efi_vars.fd'):
 observed=subprocess.run(['/usr/sbin/lsof','-n','-Fpcn',str(config.parent/'Data'/name)],capture_output=True,text=True)
 assert observed.returncode==1 and not observed.stdout,(observed.returncode,observed.stdout)
assert vm.utm_application_identity()==expected
os.kill(expected[0],signal.SIGTERM)
deadline=time.monotonic()+10
while vm.utm_application_identity()==expected:
 assert time.monotonic()<deadline
 time.sleep(.1)
original=Path('/tmp/agentos-multihead-input-v3-original-config.plist').read_bytes()
assert hashlib.sha256(original).hexdigest()=='b2ba8798840483e3a9d810658eb84e69eba42cfadd6460844f3e3d91e38cd186'
config.write_bytes(original)
assert vm.utm_application_identity() is None
root=Path('outputs/vm-foundation/runtime/qualified-runs/virtual-multihead-startup-failure');root.mkdir(parents=True,exist_ok=True)
for name in ('agentos-multihead-input-v3-driver.py','agentos-multihead-input-v3-driver.log','agentos-utm-reopen-existing.swift','agentos-multihead-startup-recovery.py'):
 shutil.copy2(Path('/tmp')/name,root/name)
(root/'recovery.json').write_text(json.dumps({'exact_owned_app':expected,'start_command_issued':False,'no_qemu_backend':True,'disk_and_efi_not_open':True,'owned_app_closed':True,'original_config_restored':True},indent=2)+'\n')
print('Exact startup failure cleaned; original configuration restored')
