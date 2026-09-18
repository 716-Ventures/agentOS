"""Real human-client approval path, using a harmless administrator printf job."""
from pathlib import Path
exec(Path(__file__).with_name('terminal_pty.py').read_text().split("pump()\nkeys('nTerminal")[0])
def remote(code):
 r=subprocess.run(vm.ssh_args()+['python3 -'],input=code,text=True,capture_output=True)
 assert r.returncode==0,r.stderr
 return r.stdout
pump(1.5);keys('nConversation approval verification\n',1.2)
activity=json.loads(subprocess.check_output(vm.ssh_args()+['cat ~/.local/state/agent-os/selection.json'],text=True))['activity_id']
base="import sys,json;sys.path.insert(0,'/usr/local/lib/agent-os/services');from broker_client import request\n"
proposal=json.loads(remote(base+"print(json.dumps(request('execute',activity="+str(activity)+",argv=['/usr/bin/printf','conversation-approval-ok'],purpose='Verify in-tile approval with harmless output',scope='system')))"))
pump(1.2)
assert any('Awaiting your approval' in line for line in screen.display),'\n'.join(screen.display)
assert any('conversation-approval-ok' in line for line in screen.display)
keys('\n');assert any('Reply to Agent' in line for line in screen.display)
keys('approved\n',2)
result=json.loads(remote(base+"print(json.dumps(request('poll',job_id='"+proposal['id']+"')))"))
assert result['status']=='succeeded',result
assert result['output']=='conversation-approval-ok',result
assert result['approved_by_uid']==0
pump(4);capture('terminal-conversation-approval')
assert any('Approved operation' in line for line in screen.display),'\n'.join(screen.display)
keys('\nSecond message in this conversation\n',3)
assert any('Second message' in line for line in screen.display),'\n'.join(screen.display)
assert sum(line.strip(' │').strip()=='You' for line in screen.display)>=2,'\n'.join(screen.display)
capture('terminal-conversation-reply');keys('q');process.wait(timeout=10)
print(json.dumps({'passed':True,'activity':activity,'operation':proposal['id'],'checks':['Enter opens reply','pending command visible','typed approval starts exact proposal','root approval recorded','result status visible','two turns remain in same tile']}))
