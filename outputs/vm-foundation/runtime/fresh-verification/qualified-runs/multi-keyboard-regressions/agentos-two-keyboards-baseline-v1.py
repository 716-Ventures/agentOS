import os,sys,json,time,subprocess,hashlib
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification';os.environ['AGENT_OS_VM_SSH_PORT']='22221'
sys.path.insert(0,'outputs/vm-foundation');import vm
from utm_ownership import UTMApplicationOwnership
bundle=Path(vm.machine()['bundle']);config=(bundle/'config.plist').read_bytes();inodes={n:(bundle/'Data'/n).stat().st_ino for n in ('disk.qcow2','efi_vars.fd')}
receipt={'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_clean':not subprocess.check_output(['git','status','--porcelain'])}
with UTMApplicationOwnership(vm) as owner:
 try:
  assert vm.utm_application_identity() is None
  vm.start();vm.wait_ready(60)
  guest='from pathlib import Path\nimport subprocess,json,hashlib,tempfile,shutil\nroot=Path(\'/home/developer/agent-os-source\')\ninstalled=Path(\'/usr/local/lib/agent-os/current\').resolve()\nreport={\'installed_runtime\':installed.name,\'manifest\':json.loads((installed/\'manifest.json\').read_text())}\nwith tempfile.TemporaryDirectory(prefix=\'agentos-two-keyboard-\') as tmp:\n isolated=Path(tmp);isolated.chmod(0o755);shutil.copytree(root/\'tests\',isolated/\'tests\')\n for name in (\'native-shell\',\'native-compositor\'):(isolated/name).symlink_to(root/name,target_is_directory=True)\n probe=isolated/\'tests/direct_input_probe.py\';source=probe.read_text()\n marker="        work_area=next(layer[\'work_area\'] for layer in scene()[\'system_layers\'] if layer[\'namespace\']==\'agentos-system-bar\' and layer[\'mapped\'])\\n"\n addition="        second=Device(True)\\n        try:\\n            subprocess.run([\'udevadm\',\'settle\',\'--timeout=5\'],check=True);time.sleep(.5)\\n            observed=scene();window=next(w for w in observed[\'windows\'] if w[\'id\']==target);point=initial[\'field\'];geometry=window[\'geometry\']\\n            pointer.click(geometry[\'x\']+point[0],geometry[\'y\']+point[1],width,height)\\n            wait(lambda v:v[\'focused\'])\\n            second.chord(46);wait(lambda v:v[\'text\']==\'c\')\\n            keyboard.event(1,42,1);keyboard.sync()\\n            second.event(1,42,1);second.sync();second.chord(30)\\n            wait(lambda v:v[\'text\']==\'cA\')\\n            keyboard.event(1,42,0);keyboard.sync();second.chord(48)\\n            observed=wait(lambda v:len(v[\'text\'])==3)\\n            time.sleep(.1) # Permit the already-typed character\'s release to reach the seat.\\n            count=scene()[\'keyboard_pressed_count\']\\n            print(\'Overlapping keyboard observation:\',json.dumps({\'text\':observed[\'text\'],\'keyboard_pressed_count\':count}),flush=True)\\n            assert observed[\'text\']==\'cAB\' and count==1,\'OVERLAPPING_KEYBOARD_MODIFIER_RELEASE: \'+repr({\'text\':observed[\'text\'],\'held_seat_keys\':count})\\n        finally:\\n            for device in (keyboard,second):device.event(1,42,0);device.sync()\\n            second.close()\\n        return\\n"\n assert source.count(marker)==1;probe.write_text(source.replace(marker,marker+addition))\n result=subprocess.run([\'python3\',str(isolated/\'tests/direct_display_guest.py\'),\'--input\'],capture_output=True,text=True,timeout=150)\n Path(\'/tmp/agentos-two-keyboards-baseline-v1-guest.log\').write_text(result.stdout+result.stderr)\n report.update(returncode=result.returncode,independent_negative=result.returncode!=0 and \'OVERLAPPING_KEYBOARD_MODIFIER_RELEASE\' in result.stdout+result.stderr)\n assert report[\'independent_negative\'],(result.returncode,result.stdout[-2000:],result.stderr[-2000:])\nPath(\'/tmp/agentos-two-keyboards-baseline-v1.json\').write_text(json.dumps(report,indent=2)+\'\\n\')\nprint(json.dumps(report))\n'
  result=vm.ssh('sudo -n python3 -',input=guest,text=True,capture_output=True,timeout=1000)
  Path('/tmp/agentos-two-keyboards-baseline-v1-guest.log').write_text(result.stdout+result.stderr)
  for suffix in ['-guest.log','.json']:
   r=vm.ssh('sudo -n cat /tmp/agentos-two-keyboards-baseline-v1'+suffix,capture_output=True)
   if r.returncode==0:Path('/tmp/agentos-two-keyboards-baseline-v1'+suffix).write_bytes(r.stdout)
  assert result.returncode==0,'Independent overlapping-keyboard diagnostic failed'
  receipt['keyboard_diagnostic']=json.loads(result.stdout)
 finally:
  vm.stop();end=time.monotonic()+60
  while vm.status()!='stopped':
   assert time.monotonic()<end;time.sleep(.5)
  receipt['owned_utm_closed']=owner.close()
  assert vm.utm_application_identity() is None
  assert (bundle/'config.plist').read_bytes()==config
  assert all((bundle/'Data'/n).stat().st_ino==ino for n,ino in inodes.items())
  receipt.update(original_config_unchanged=True,original_disk_efi_inodes_preserved=True)
  Path('/tmp/agentos-two-keyboards-baseline-v1-driver.json').write_text(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(receipt),flush=True)
