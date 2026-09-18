"""Real terminal observes external agent-identity edits; active input blocks them."""
from pathlib import Path
exec(Path(__file__).with_name('terminal_pty.py').read_text().split("pump()\nkeys('nTerminal")[0])
def remote(code):
 return subprocess.run(vm.ssh_args()+['sudo runuser -u agentos-ai -g agentos -- python3 -'],input=code,text=True,capture_output=True)
pump(1.5)
keys('nShared layout live terminal\n',1.2)
selection=subprocess.check_output(vm.ssh_args()+['cat ~/.local/state/agent-os/selection.json'],text=True)
activity=json.loads(selection)['activity_id']
base="import sys;sys.path.insert(0,'/usr/local/lib/agent-os/services');from layout_client import request\na="+str(activity)+"\ns=request('snapshot',activity=a)\n"
change="request('apply',activity=a,expected_revision=s['revision'],action={'operation':'split','axis':'x','surface_id':s['focus'],'view':'history'})"
keys('aI am typing')
r=remote(base+change);assert r.returncode!=0 and 'typing' in r.stderr,r.stderr
keys('\x1b')
r=remote(base+change);assert r.returncode==0,r.stderr
pump(1.5)
assert any('Activity history' in line for line in screen.display),'\n'.join(screen.display)
capture('terminal-shared-layout')
keys('q');process.wait(timeout=10)
print(json.dumps({'passed':True,'activity':activity,'checks':['agent split appears in running terminal','typing prevents external agent change']}))
