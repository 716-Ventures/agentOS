import sys,pathlib,subprocess,tarfile,io,json,time
sys.path.insert(0,'outputs/vm-foundation');import vm
import agentos_image_owned_utm as ownership
sys.path.insert(0,'outputs/agent-shell');import deploy
out=pathlib.Path('outputs/vm-foundation/runtime/release-artifacts')
args=vm.ssh_args();args[-1]='verifier@127.0.0.1';args=[('-o' if x=='-o' else 'UserKnownHostsFile='+str(vm.RUN/'image-v21-attempt1-known-hosts') if x.startswith('UserKnownHostsFile=') else x) for x in args]
def ssh(cmd,**kw):return subprocess.run(args+[cmd],check=True,**kw)
# This qualification-only sudo fixture follows successful password-protected sudo.
cmd="printf 'verifier ALL=(ALL) NOPASSWD:ALL\\n' > /etc/sudoers.d/99-image-verification; chmod 440 /etc/sudoers.d/99-image-verification; printf 'SUDO_FIXTURE_READY\\n' > /tmp/sudo-fixture-result"
vm.call([vm.controller(),'exec',vm.machine()['uuid'],'--cmd','/bin/sh','-c',cmd],capture_output=True,text=True)
for _ in range(30):
 r=subprocess.run([str(vm.controller()),'file','pull',vm.machine()['uuid'],'/tmp/sudo-fixture-result'],capture_output=True)
 if b'SUDO_FIXTURE_READY' in r.stdout:break
 time.sleep(.2)
else:raise RuntimeError('Test-only sudo fixture did not acknowledge')
archive=pathlib.Path('/tmp/agentos-activity-qualified-source.tar').read_bytes()
import hashlib
full=json.loads((vm.RUN/'reproduction.json').read_text())
assert full['result']=='pass' and len(full['checks'])==70 and not full['deployment']['source_changes']
assert hashlib.sha256(archive).hexdigest()==full['deployment']['source_archive_sha256']
ssh('mkdir /home/verifier/qualification && tar xf - -C /home/verifier/qualification',input=archive)
ssh('cat > /home/verifier/reader-compatible-runtime.tar.gz',stdin=(out/'reader-compatible-runtime.tar.gz').open('rb'))
for helper in ('presentation_fixture','ime_fixture'):
 ssh('mkdir -p /home/verifier/qualification/native-compositor/target/debug/examples')
 with (out/('qualification-v21-'+helper)).open('rb') as binary:
  ssh('cat > /home/verifier/qualification/native-compositor/target/debug/examples/'+helper,stdin=binary)
 ssh('chmod 755 /home/verifier/qualification/native-compositor/target/debug/examples/'+helper)
with pathlib.Path('/tmp/agentos-image-v21-schema-guard.py').open('rb') as fixture:
 ssh('cat > /home/verifier/image-v21-schema-guard.py',stdin=fixture)
expected=json.loads((out/'candidate-v21.json').read_text())['runtime_release']
older=(out/'reader-compatible-runtime-id.txt').read_text().strip()
health="""set -eu
python3 - <<'DISKS'
import json,subprocess
nodes=json.loads(subprocess.check_output(['lsblk','--json','--output','NAME,TYPE,LABEL'],text=True))['blockdevices']
assert len(nodes)==1 and nodes[0]['name']=='vda',nodes
print('No development seed or additional disk attached:',nodes)
DISKS
systemctl is-active agent-os-core agent-os-layout agent-os-disk agent-os-broker agent-os-ai agent-os-voice
agent-os-status
curl -fIs --max-time 20 https://deb.debian.org/debian/ >/dev/null
agent-os create 'Image update continuity' > /home/verifier/image-activity.json
printf image-persistence-ok > /home/verifier/image-persistence
readlink -f /usr/local/lib/agent-os/current > /home/verifier/image-original-release
sudo -n agent-os-update --stage-bundle /home/verifier/reader-compatible-runtime.tar.gz
cmp /home/verifier/image-original-release /dev/stdin <<EOF
$(readlink -f /usr/local/lib/agent-os/current)
EOF
sudo -n agent-os-update --activate OLDER
sudo -n agent-os-update --rollback
cmp /home/verifier/image-original-release /dev/stdin <<EOF
$(readlink -f /usr/local/lib/agent-os/current)
EOF
sudo -n agent-os-update --activate EXPECTED
python3 - <<'CHECK'
import json,pathlib,subprocess
activity=json.loads(pathlib.Path('/home/verifier/image-activity.json').read_text())['id']
snapshot=json.loads(subprocess.check_output(['agent-os','activities'],text=True))
print('Saved activity identity:',activity)
assert any(row['id']==activity for row in snapshot), snapshot
print('Activity persisted through signed activation and rollback')
assert pathlib.Path('/usr/local/lib/agent-os/current').resolve().name=='EXPECTED'
assert pathlib.Path('/home/verifier/image-persistence').read_text()=='image-persistence-ok'
CHECK
sudo -n python3 /home/verifier/qualification/tests/direct_display_guest.py --input
sudo -n python3 /home/verifier/qualification/tests/direct_display_guest.py --input --fresh-profile
sudo -n python3 /home/verifier/qualification/tests/direct_display_guest.py --table-input
sudo -n python3 /home/verifier/qualification/tests/direct_display_guest.py --list-input
sudo -n python3 /home/verifier/qualification/tests/direct_display_guest.py --keyvalue-input
sudo -n python3 /home/verifier/qualification/tests/direct_display_guest.py --terminal-input
sudo -n python3 /home/verifier/qualification/tests/direct_display_guest.py --terminal-ime
sudo -n python3 /home/verifier/qualification/tests/direct_display_guest.py --native-feedback
sudo -n python3 /home/verifier/qualification/tests/direct_display_guest.py --native-feedback-load
sudo -n python3 /home/verifier/qualification/tests/direct_display_guest.py --presentation-feedback
sudo -n python3 /home/verifier/qualification/tests/direct_display_guest.py --screen-reader-input
mkdir -p /home/verifier/qualification/target/release /home/verifier/qualification/native-shell/target/debug /home/verifier/qualification/native-compositor/target/debug
ln -s /usr/local/lib/agent-os/current/agent-os-core /home/verifier/qualification/target/release/agent-os-core
ln -s /usr/local/bin/agent-os-desktop /home/verifier/qualification/native-shell/target/debug/agent-os-desktop
ln -s /usr/local/bin/agent-os-compositor /home/verifier/qualification/native-compositor/target/debug/agent-os-compositor
cd /home/verifier/qualification && dbus-run-session -- python3 native-shell/tests/native_session.py --screen-reader --installed --reader-controls --reader-outcomes
cp /home/verifier/qualification/native-shell/test-output/reader-validation-speech.log /home/verifier/image-v21-reader-controls-speech.log
cd /home/verifier/qualification && dbus-run-session -- python3 native-shell/tests/native_session.py --display-zoom --screen-reader
cd /home/verifier/qualification && dbus-run-session -- python3 native-shell/tests/native_session.py --screen-reader --compositor-failure
python3 /home/verifier/qualification/tests/voice_guest.py
cd /home/verifier/qualification && dbus-run-session -- python3 native-shell/tests/browser_links.py --installed
sudo -n python3 /home/verifier/image-v21-schema-guard.py OLDER
printf 'IMAGE_UPDATE_QUALIFIED\\n'
""".replace('EXPECTED',expected).replace('OLDER',older)
ssh(health,stdout=open('/tmp/agentos-image-v21-attempt1-qualification.log','w'),stderr=subprocess.STDOUT)
with (vm.RUN/'image-v21-dependencies.json').open('wb') as target:
 ssh('sudo -n cat /var/lib/agent-os-install/dependencies.json',stdout=target)
with (vm.RUN/'image-v21-browser.json').open('wb') as target:
 ssh('cat /home/verifier/qualification/native-shell/test-output/browser-links/verification.json',stdout=target)
with (vm.RUN/'image-v21-schema-guard.json').open('wb') as target:
 ssh('cat /tmp/image-v21-schema-guard-result.json',stdout=target)
print('Image signed update, rollback, direct input and voice passed',flush=True)

with (vm.RUN/'image-v21-reader-controls-speech.log.gz').open('wb') as target:
 ssh('gzip -c /home/verifier/image-v21-reader-controls-speech.log',stdout=target)

with (vm.RUN/"image-v21-online-launcher-speech.log.gz").open("wb") as target:
 ssh("sudo -n gzip -c /home/verifier/qualification/test-output/orca-kernel-speech.log",stdout=target)
