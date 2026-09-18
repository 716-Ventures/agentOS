"""Run inside the guest as developer; exercises real socket identities and restart."""
import sys,json,subprocess,time
sys.path.insert(0,'/usr/local/lib/agent-os/services')
from common import connect,read_line
from layout_client import request
with connect('/run/agent-os/runtime.sock',{'op':'create','name':'Shared layout verification'}) as c:
 with c.makefile('rb') as f:activity=read_line(f)['result']['id']
def agent(payload):
 code="import sys,json;sys.path.insert(0,'/usr/local/lib/agent-os/services');from layout_client import request; p=json.loads(sys.argv[1]);print(json.dumps(request(**p)))"
 return subprocess.run(['sudo','-u','agentos-ai','-g','agentos','python3','-c',code,json.dumps(payload)],capture_output=True,text=True)
s=request('ensure',activity=activity)
request('editing',activity=activity,client_id='qa',active=True)
p={'op':'apply','activity':activity,'expected_revision':0,'action':{'operation':'split','axis':'x','surface_id':s['focus'],'view':'history'}}
r=agent(p);assert r.returncode!=0 and 'typing' in r.stderr,r.stderr
request('editing',activity=activity,client_id='qa',active=False)
r=agent(p);assert r.returncode==0,r.stderr
s=json.loads(r.stdout);assert len(s['surfaces'])==2
assert request('snapshot',activity=activity)['revision']==1
assert agent(p).returncode!=0
subprocess.run(['sudo','systemctl','restart','agent-os-layout'],check=True)
for _ in range(30):
 try:request('snapshot',activity=activity);break
 except OSError:time.sleep(.1)
s=request('apply',activity=activity,expected_revision=1,action={'operation':'undo'});assert len(s['surfaces'])==1
assert request('events',activity=activity)[1]['actor']=='agent'
print(json.dumps({'activity':activity,'passed':True,'checks':['SO_PEERCRED agent attribution','typing gate','shared snapshots','stale revision rejection','restart persistence','durable undo']}))
