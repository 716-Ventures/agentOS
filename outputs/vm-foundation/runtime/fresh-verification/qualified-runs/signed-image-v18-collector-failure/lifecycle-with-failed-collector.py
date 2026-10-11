import sys,pathlib,subprocess,time,json,plistlib,shutil,os,signal,uuid as uuid_module
sys.path.insert(0,'outputs/vm-foundation');import vm
import agentos_image_owned_utm as ownership
uuid=vm.machine(require_ssh=False)['uuid'];controller=str(vm.controller());bundle=pathlib.Path(vm.machine(require_ssh=False)['bundle'])
args=vm.ssh_args();args[-1]='verifier@127.0.0.1';args=[('UserKnownHostsFile='+str(vm.RUN/'image-v18-attempt1-known-hosts') if x.startswith('UserKnownHostsFile=') else x) for x in args]
def ssh(cmd,**kw):return subprocess.run(args+[cmd],check=True,**kw)
def call(*command,**kw):return subprocess.run([controller,*command],check=True,timeout=20,**kw)
def push(path,data):call('file','push',uuid,path,input=data,capture_output=True)
def pull(path):return call('file','pull',uuid,path,capture_output=True).stdout
counter=0
def rootrun(command,wait_seconds=90):
 global counter
 counter+=1;prefix='/var/tmp/image-v18-root-'+uuid_module.uuid4().hex
 call('exec',uuid,'--cmd','/bin/sh','-c',command+' > '+prefix+'.out 2> '+prefix+'.err; echo $? > '+prefix+'.status',capture_output=True)
 deadline=time.monotonic()+wait_seconds
 while True:
  try:
   status=pull(prefix+'.status').strip()
   if status:break
   if time.monotonic()>deadline:raise RuntimeError('Empty completion marker')
   time.sleep(.2)
  except subprocess.CalledProcessError:
   if time.monotonic()>deadline:raise RuntimeError('Read-only observer not yet available')
   time.sleep(.5)
 if status!=b'0':raise RuntimeError(pull(prefix+'.err').decode(errors='replace'))
 return pull(prefix+'.out').decode()
def stopped():
 deadline=time.monotonic()+45
 while call('status',uuid,capture_output=True,text=True).stdout.strip()!='stopped':
  if time.monotonic()>deadline:raise RuntimeError('VM shutdown not acknowledged; disk not changed')
  time.sleep(.5)
def reload_host():
 ownership.close()
def agent_ready():
 deadline=time.monotonic()+75
 while True:
  r=subprocess.run([controller,'exec',uuid,'--cmd','/bin/true'],capture_output=True,timeout=10)
  if r.returncode==0 and not r.stdout.strip() and not r.stderr.strip():return
  if time.monotonic()>deadline:raise RuntimeError('Guest agent readiness timeout')
  time.sleep(.5)
expected=json.loads(pathlib.Path('outputs/vm-foundation/runtime/release-artifacts/candidate-v18.json').read_text())['runtime_release']
push('/home/verifier/expected-runtime',(expected+'\n').encode())
push('/var/tmp/image-v18-persistence.py',pathlib.Path('/tmp/agentos-image-v18-persistence.py').read_bytes())
push('/var/tmp/image-v18-resume.py',pathlib.Path('/tmp/agentos-image-resume-probe.py').read_bytes())
before=json.loads(rootrun('python3 /var/tmp/image-v18-persistence.py',wait_seconds=5));print('Before reboot:',json.dumps(before),flush=True)
call('exec',uuid,'--cmd','/bin/systemctl','reboot',capture_output=True)
time.sleep(3);agent_ready()
deadline=time.monotonic()+75
while True:
 try:
  after=json.loads(rootrun('python3 /var/tmp/image-v18-persistence.py',wait_seconds=5))
  assert after['boot_id']!=before['boot_id'];break
 except (RuntimeError,AssertionError):
  if time.monotonic()>deadline:raise
  time.sleep(1)
print('After reboot:',json.dumps(after),flush=True)
call('stop',uuid,'--request',capture_output=True);stopped()
reload_host()
online=(bundle/'config.plist').read_bytes();(vm.RUN/'pre-candidate-v18-attempt1/online-config.plist').write_bytes(online)
config=plistlib.loads(online);config['Network']=[];(bundle/'config.plist').write_bytes(plistlib.dumps(config,sort_keys=False))
vm.start(console_only=True);agent_ready()
deadline=time.monotonic()+75
while True:
 try:offline=json.loads(rootrun('python3 /var/tmp/image-v18-persistence.py',wait_seconds=5));break
 except RuntimeError:
  if time.monotonic()>deadline:raise
  time.sleep(1)
assert offline['boot_id']!=after['boot_id'] and offline['network_interfaces']==['lo'], offline
print('Offline cold boot:',json.dumps(offline),flush=True)
rootrun("runuser -u verifier -- sh -c 'cd /home/verifier/qualification && dbus-run-session -- python3 native-shell/tests/browser_links.py --installed'",wait_seconds=120)
offline_browser=json.loads(pull('/home/verifier/qualification/native-shell/test-output/browser-links/verification.json'))
assert offline_browser['result']=='pass' and offline_browser['installed_executables'] and offline_browser['cleanup_verified']
print('Offline browser handoff:',json.dumps(offline_browser),flush=True)
rootrun('python3 /home/verifier/qualification/tests/direct_display_guest.py --screen-reader-input',wait_seconds=180)
print('PASS: offline cold-boot image reader commands and rescue VT work without network or models',flush=True)
rootrun('gzip -c /home/verifier/qualification/test-output/orca-kernel-speech.log > /var/tmp/image-v18-offline-launcher-speech.log.gz',wait_seconds=10)
(vm.RUN/'image-v18-offline-launcher-speech.log.gz').write_bytes(pull('/var/tmp/image-v18-offline-launcher-speech.log.gz'))
import gzip,hashlib
launcher_speech=gzip.decompress((vm.RUN/'image-v18-offline-launcher-speech.log.gz').read_bytes())
launcher_announcements=sum(b'SPEECH OUTPUT:' in line and b'Ask Agent text' in line for line in launcher_speech.splitlines())
assert launcher_announcements>=10
print('Offline launcher actual request announcements:',launcher_announcements,'raw SHA-256:',hashlib.sha256(launcher_speech).hexdigest(),flush=True)

rootrun("runuser -u verifier -- sh -c 'cd /home/verifier/qualification && dbus-run-session -- python3 native-shell/tests/native_session.py --display-zoom --screen-reader'",wait_seconds=180)
print('PASS: offline image display zoom, keyboard and session-owned reader work without network or models',flush=True)
rootrun('python3 /var/tmp/image-v18-resume.py')
resume=json.loads(pull('/tmp/image-resume-result.json'));assert resume['result']=='pass',resume
print('Activation failure and resume:',json.dumps(resume),flush=True)
rootrun('agent-os-update --activate '+expected)
final=json.loads(rootrun('python3 /var/tmp/image-v18-persistence.py',wait_seconds=5));assert final['network_interfaces']==['lo']
# Remove the qualification-only authority and remote access before archiving.
rootrun('rm /etc/sudoers.d/99-image-verification; rm /home/verifier/.ssh/authorized_keys; systemctl disable ssh; systemctl stop ssh')
call('stop',uuid,'--request',capture_output=True);stopped()
reload_host()
backup=vm.RUN/'pre-candidate-v18-attempt1';data=bundle/'Data'
for name,target in [('disk.qcow2','candidate-v18-attempt1-booted.qcow2'),('efi_vars.fd','candidate-v18-attempt1-booted-efi.fd')]:
 assert not (vm.RUN/target).exists();(data/name).rename(vm.RUN/target);(backup/name).rename(data/name)
(bundle/'config.plist').write_bytes((backup/'config.plist').read_bytes())
(backup/'config.plist').unlink();(backup/'online-config.plist').unlink();backup.rmdir()
assert vm.status()=='stopped'
reload_host()
report={'offline_launcher_request_announcements':launcher_announcements,'offline_launcher_raw_speech_sha256':hashlib.sha256(launcher_speech).hexdigest(),'result':'pass','before':before,'reboot':after,'offline':offline,'activation_resume':resume,'offline_browser':offline_browser,'offline_screen_reader_qualified':True,'offline_display_zoom_and_keyboard_qualified':True,'final_offline_runtime':final['runtime'],'development_disk_restored':True,'guest_stopped':True}
(vm.RUN/'image-v18-lifecycle.json').write_text(json.dumps(report,indent=2)+'\n')
print('Development disk/config/EFI restored; qualification VM stopped',flush=True)
