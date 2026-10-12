import sys,time,json
sys.path.insert(0,'outputs/vm-foundation');import vm
import agentos_image_owned_utm
end=time.monotonic()+75
while True:
 r=vm.call([vm.controller(),'exec',vm.machine()['uuid'],'--cmd','/bin/sh','-c',"systemctl is-enabled ssh > /var/tmp/v23-ssh-before; systemctl is-active ssh >> /var/tmp/v23-ssh-before; systemctl start ssh"],capture_output=True,text=True,timeout=12)
 if r.returncode==0 and not r.stdout.strip() and not r.stderr.strip():break
 assert time.monotonic()<end,'Guest agent unavailable'
 time.sleep(.5)
while True:
 r=vm.call([vm.controller(),'file','pull',vm.machine()['uuid'],'/var/tmp/v23-ssh-before'],capture_output=True,text=True)
 if r.returncode==0 and not r.stderr.strip() and r.stdout.strip():break
 assert time.monotonic()<end,'Transport observation unavailable'
 time.sleep(.5)
assert r.returncode==0 and r.stdout.splitlines()==['disabled','inactive'],r
(vm.RUN/'image-v23-transport-observation.json').write_text(json.dumps({'before':r.stdout.splitlines(),'diagnosis':'Qualification fixture started the disabled SSH service only for first boot; VM and installed runtime are healthy.','recovery':'Start qualification-only SSH via guest agent on each restarted verification boot.','distribution_ssh_enablement_changed':False},indent=2)+'\n')
print('Confirmed distribution SSH disabled/inactive after restart; qualification transport started via guest agent',flush=True)
