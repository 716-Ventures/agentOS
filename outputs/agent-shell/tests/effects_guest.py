"""Real broker effect decisions; no destructive proposal is approved."""
import sys,json,time,uuid,subprocess
sys.path.insert(0,'/usr/local/lib/agent-os/services')
from broker_client import request
activity=2
name='effects-verify-'+uuid.uuid4().hex
path='/var/tmp/'+name
checks=[]
def run(argv,scope='system'):
 j=request('execute',activity=activity,argv=argv,scope=scope,purpose='Verify effects-based policy',timeout_seconds=120)
 assert j['status']!='approval_required',j
 end=time.monotonic()+120
 while j['status'] in ('starting','running','cancelling') and time.monotonic()<end:
  time.sleep(.2);j=request('poll',job_id=j['id'])
 assert j['status']=='succeeded',j
 return j
j=run(['/usr/bin/apt-get','install','-y','git']);assert '--no-remove' in j['argv'];checks.append('package install runs automatically with removal guard')
j=run(['/bin/mkdir','-p',path]);checks.append('system directory creation runs automatically')
j=request('execute',activity=activity,argv=['/bin/rmdir',path],scope='system',purpose='Verify deletion remains gated')
assert j['status']=='approval_required';assert __import__('pathlib').Path(path).is_dir()
request('cancel',job_id=j['id']);checks.append('destructive action held; target retained')
j=request('execute',activity=activity,argv=['/bin/rm','-rf','project'],scope='workspace',purpose='Verify workspace removal is gated');assert j['status']=='approval_required';request('cancel',job_id=j['id']);checks.append('workspace deletion also gated')
j=request('execute',activity=activity,argv=['/usr/bin/python3','-c','print(123)'],scope='system',purpose='Inspect unknown effects');assert j['status']=='inspection_required';checks.append('unknown code requires inspection and does not run')
subprocess.run(['sudo','rmdir',path],check=True)
print(json.dumps({'passed':True,'checks':checks}))
