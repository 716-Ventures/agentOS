import os,sys,subprocess,json,hashlib,time,datetime
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification';os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path[:0]=['outputs/vm-foundation','outputs/agent-shell'];import vm
from utm_ownership import UTMApplicationOwnership
r={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'checks':[]}
with UTMApplicationOwnership(vm) as owner:
 try:
  assert vm.status()=='stopped';vm.start();vm.wait_ready(60)
  r['runtime_release']=json.loads(vm.ssh('cat /etc/agent-os/release.json',capture_output=True,text=True,check=True).stdout)['runtime_release']
  r['binary_comparison']=json.loads(vm.ssh("python3 - <<'P'\nimport json\nfrom pathlib import Path\na=json.loads(Path('/usr/local/lib/agent-os/current/manifest.json').read_text());b=json.loads(Path('/usr/local/lib/agent-os/releases/b0f51bf0bbb2a6859b977fb836c4341558423a0f53f97407471172bb0cef5679/manifest.json').read_text());names=['agent-os-core','native/agent-os-desktop','native/agent-os-compositor'];print(json.dumps({n:{'current':a[n],'prior':b[n],'equal':a[n]==b[n]} for n in names}))\nP",capture_output=True,text=True,check=True).stdout)
  data=Path('outputs/agent-shell/tests/direct_native_feedback.py').read_bytes();r['test_sha256']=hashlib.sha256(data).hexdigest()
  vm.ssh('cat > /home/developer/agent-os-source/tests/direct_native_feedback.py',input=data,check=True)
  for profile,option in [('loaded','--native-feedback-load'),('idle','--native-feedback')]:
   with Path('/tmp/agentos-loaded-latency-diagnostic-'+profile+'.log').open('w') as out:
    result=vm.ssh('cd /home/developer/agent-os-source && sudo -n python3 tests/direct_display_guest.py '+option,stdout=out,stderr=subprocess.STDOUT,timeout=180,check=False)
   r['checks'].append({'profile':profile,'exit_code':result.returncode})
 finally:
  vm.stop();deadline=time.monotonic()+60
  while vm.status()!='stopped':
   assert time.monotonic()<deadline;time.sleep(.5)
  r['owned_utm_closed']=owner.close();r['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();Path('/tmp/agentos-loaded-latency-diagnostic.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True)
