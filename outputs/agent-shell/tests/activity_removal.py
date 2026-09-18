"""Guest integration test; retains history and rejects new work until restored."""
import sys,json
sys.path.insert(0,'/usr/local/lib/agent-os/services')
from common import connect,read_line
def call(op,**fields):
 with connect('/run/agent-os/runtime.sock',dict(op=op,**fields)) as c:
  with c.makefile('rb') as f:r=read_line(f)
 if not r['ok']:raise RuntimeError(r['error'])
 return r['result']
a=call('create',name='Activity removal verification')['id']
call('remove_activity',activity_id=a)
assert a not in [x['id'] for x in call('snapshot')['activities']]
assert a in [x['id'] for x in call('removed_activities')]
try:call('run',activity_id=a,argv=['/usr/bin/true'])
except RuntimeError:pass
else:raise AssertionError('Removed activity accepted new work')
assert call('history',activity_id=a)
call('restore_activity',activity_id=a)
assert a in [x['id'] for x in call('snapshot')['activities']]
call('remove_activity',activity_id=a)
print(json.dumps({'passed':True,'activity':a,'checks':['removed from snapshot','listed for recovery','new work rejected','history retained','restored successfully']}))
