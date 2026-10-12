import json,pwd,pathlib,subprocess
expected=pathlib.Path('/home/verifier/expected-runtime').read_text().strip()
assert pathlib.Path('/usr/local/lib/agent-os/current').resolve().name==expected
assert pwd.getpwnam('verifier').pw_uid==1000
assert pathlib.Path('/home/verifier/image-persistence').read_text()=='image-persistence-ok'
activity=json.loads(pathlib.Path('/home/verifier/image-activity.json').read_text())['id']
activities=json.loads(subprocess.check_output(['runuser','-u','verifier','--','agent-os','activities'],text=True))
assert any(row['id']==activity for row in activities)
services=subprocess.check_output(['systemctl','is-active','agent-os-core','agent-os-layout','agent-os-disk','agent-os-broker','agent-os-ai','agent-os-voice'],text=True).splitlines()
assert services==['active']*6, services
boot=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
network=json.loads(subprocess.check_output(['ip','-j','link'],text=True))
print(json.dumps({'result':'pass','boot_id':boot,'runtime':expected,'uid':1000,'activity':activity,'file_persisted':True,'healthy_services':services,'network_interfaces':[r['ifname'] for r in network]}))
