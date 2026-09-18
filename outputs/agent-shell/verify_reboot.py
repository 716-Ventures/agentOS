#!/usr/bin/env python3
"""Host-side full-guest reboot check. Reboots the development VM."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'vm-foundation'))
import vm


def remote(cmd):
    return subprocess.check_output(vm.ssh_args()+[cmd],text=True,stderr=subprocess.DEVNULL,timeout=8)


before=remote('cat /proc/sys/kernel/random/boot_id').strip()
activity=json.loads(remote('agent-os create "Reboot persistence check"'))['id']
job=json.loads(remote(f"agent-os run {activity} -- python3 -c 'from pathlib import Path; Path(\"reboot-marker.txt\").write_text(\"retained across reboot\")'"))['id']
time.sleep(.5)
jobs=json.loads(remote(f'agent-os jobs {activity}'))
assert next(j for j in jobs if j['id']==job)['status']=='succeeded'
interrupted=json.loads(remote(f'agent-os run {activity} -- sleep 120'))['id']
subprocess.run(vm.ssh_args()+['sudo systemctl reboot'],capture_output=True,timeout=10)
deadline=time.monotonic()+60
after=None
while time.monotonic()<deadline:
    try:
        boot=remote('cat /proc/sys/kernel/random/boot_id').strip()
        if boot!=before:
            snapshot=json.loads(remote('agent-os status'))
            after=boot;break
    except (subprocess.SubprocessError,OSError,ValueError):
        pass
    time.sleep(2)
assert after, 'Guest did not reboot and restore core in time'
assert next(j for j in snapshot['jobs'] if j['id']==interrupted)['status']=='interrupted'
assert any(a['id']==activity for a in snapshot['activities'])
read=json.loads(remote(f'agent-os run {activity} -- cat reboot-marker.txt'))['id']
time.sleep(.3)
assert remote(f'agent-os logs {read}').strip()=='retained across reboot'
assert remote('systemctl is-system-running').strip()=='running'
report=json.loads(remote('cat /home/developer/agent-os-integration.json'))
report['reboot']={'result':'pass','before_boot':before,'after_boot':after,'activity_id':activity,'interrupted_job':interrupted,'checks':['core starts at boot','activity survives','workspace file survives','unfinished job marked interrupted; not replayed','guest system healthy']}
(ROOT/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS: full VM reboot, persistent activity/file, interrupted job recovery, healthy system')
