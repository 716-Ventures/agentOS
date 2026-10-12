from pathlib import Path
import subprocess,json,time
connectors=sorted(Path('/sys/class/drm').glob('card*-Virtual-*'))
assert len(connectors)==2,[p.name for p in connectors]
second=next(p for p in connectors if p.name.endswith('-Virtual-2'))
card=Path('/sys/class/drm')/second.name.split('-',1)[0]
device=(card/'device').resolve()
identity=dict(line.split('=',1) for line in (device/'uevent').read_text().splitlines() if '=' in line)
assert (device/'driver').resolve().name=='virtio-pci' and identity.get('PCI_ID')=='1AF4:1050' and identity.get('PCI_CLASS')=='38000',identity
original=(second/'status').read_text().strip()
assert original=='disconnected',original
report={'virtual_gpu_pci_identity':identity,'original_second_connector_status':original,'synthetic_connector_force':True,'physical_hotplug_qualified':False}
report['cases']=[]
try:
 for index,mode in enumerate(['--multi-output-shell-hotplug']):
  (second/'status').write_text('on')
  report['forced_status']=(second/'status').read_text().strip()
  report['forced_modes']=(second/'modes').read_text().splitlines()
  assert report['forced_status']=='connected' and report['forced_modes'],report
  result=subprocess.run(['python3','-c','import sys,runpy,types;sys.path.insert(0,\'/home/developer/agent-os-source/tests\');import direct_shell_hotplug_probe; probe=types.ModuleType(\'restoration_baseline\');exec(\'"""Prove that a returning preferred display must not move an active editor."""\\nfrom pathlib import Path\\nimport json\\nimport subprocess\\nimport time\\n\\n\\ndef verify(scene, target, snapshot, keyboard, pointer):\\n    primary = Path(\\\'/sys/class/drm/card0-Virtual-1\\\')\\n    assert (primary/\\\'status\\\').read_text().strip() == \\\'connected\\\'\\n    def wait(predicate, message):\\n        end = time.monotonic()+10\\n        while True:\\n            value = predicate()\\n            if value:return value\\n            state=scene()\\n            assert time.monotonic()<end, (message, {k:state[k] for k in (\\\'outputs\\\',\\\'windows\\\',\\\'seat_focus\\\')}, state[\\\'shared\\\'][\\\'overview\\\'])\\n            time.sleep(.03)\\n    def force(value):\\n        (primary/\\\'status\\\').write_text(value)\\n        subprocess.run([\\\'udevadm\\\',\\\'trigger\\\',\\\'--action=change\\\',\\\'--subsystem-match=drm\\\',\\\'--sysname-match=card0\\\'],check=True)\\n        subprocess.run([\\\'udevadm\\\',\\\'settle\\\',\\\'--timeout=5\\\'],check=True)\\n    def editor():return next(w for w in scene()[\\\'windows\\\'] if w[\\\'id\\\']==target)\\n    def click_editor():\\n        g=editor()[\\\'geometry\\\'];p=snapshot()[\\\'field\\\'];outputs=scene()[\\\'outputs\\\']\\n        pointer.click(g[\\\'x\\\']+p[0],g[\\\'y\\\']+p[1],max(o[\\\'x\\\']+o[\\\'width\\\'] for o in outputs),max(o[\\\'y\\\']+o[\\\'height\\\'] for o in outputs))\\n        wait(lambda:snapshot()[\\\'focused\\\'] and scene()[\\\'seat_focus\\\']==target,\\\'Editor not focused\\\')\\n    original=snapshot()[\\\'text\\\']\\n    before=editor();assert before[\\\'geometry\\\'][\\\'x\\\']<1280, before\\n    click_editor()\\n    try:\\n        force(\\\'off\\\')\\n        wait(lambda:{o[\\\'name\\\'] for o in scene()[\\\'outputs\\\']}=={\\\'Virtual-2\\\'},\\\'Primary removal missing\\\')\\n        wait(lambda:editor()[\\\'geometry\\\'][\\\'x\\\']>=0 and editor()[\\\'geometry\\\'][\\\'x\\\']<1024,\\\'Editor recovery missing\\\')\\n        click_editor();keyboard.chord(29,107);keyboard.chord(30)\\n        wait(lambda:snapshot()[\\\'text\\\']==original+\\\'a\\\' and snapshot()[\\\'focused\\\'],\\\'Recovered editor typing missing\\\')\\n        recovered=editor();secondary=next(o for o in scene()[\\\'outputs\\\'] if o[\\\'name\\\']==\\\'Virtual-2\\\')\\n        relative={k:recovered[\\\'geometry\\\'][k]-(secondary[\\\'x\\\'] if k==\\\'x\\\' else secondary[\\\'y\\\'] if k==\\\'y\\\' else 0) for k in (\\\'x\\\',\\\'y\\\',\\\'width\\\',\\\'height\\\')}\\n        force(\\\'on\\\')\\n        wait(lambda:{o[\\\'name\\\'] for o in scene()[\\\'outputs\\\']}=={\\\'Virtual-1\\\',\\\'Virtual-2\\\'},\\\'Primary return missing\\\')\\n        # Wait for the restored output\\\'s shared projection to settle, rather\\n        # than sampling the immediate old frame after connector discovery.\\n        time.sleep(.4)\\n        current=editor();secondary=next(o for o in scene()[\\\'outputs\\\'] if o[\\\'name\\\']==\\\'Virtual-2\\\')\\n        expected={**relative,\\\'x\\\':relative[\\\'x\\\']+secondary[\\\'x\\\'],\\\'y\\\':relative[\\\'y\\\']+secondary[\\\'y\\\']}\\n        print(\\\'Active editor reconnection evidence: \\\'+json.dumps({\\\'expected_retained_secondary_geometry\\\':expected,\\\'observed_geometry\\\':current[\\\'geometry\\\'],\\\'focused\\\':snapshot()[\\\'focused\\\'],\\\'draft_preserved\\\':snapshot()[\\\'text\\\']==original+\\\'a\\\',\\\'seat_focus\\\':scene()[\\\'seat_focus\\\'],\\\'overview\\\':scene()[\\\'shared\\\'][\\\'overview\\\']}),flush=True)\\n        assert current[\\\'geometry\\\']==expected, \\\'Returning preferred output moved the focused editor during active input\\\'\\n        assert snapshot()[\\\'text\\\']==original+\\\'a\\\' and snapshot()[\\\'focused\\\'] and scene()[\\\'seat_focus\\\']==target\\n        print(\\\'PASS: returning output offers restoration without moving the active editor\\\',flush=True)\\n    finally:force(\\\'on\\\')\\n\',probe.__dict__);direct_shell_hotplug_probe.verify=probe.verify;sys.argv=[\'/home/developer/agent-os-source/tests/direct_display_guest.py\',\'--multi-output-shell-hotplug\'];runpy.run_path(sys.argv[0],run_name=\'__main__\')'],capture_output=True,text=True,timeout=180)
  Path('/tmp/agentos-active-restoration-baseline-v2-'+str(index)+'.log').write_text(result.stdout+result.stderr)
  assert result.returncode==0,result.stdout[-5000:]+result.stderr[-5000:]
  rows=[]
  for line in result.stdout.splitlines():
   try:value=json.loads(line)
   except ValueError:continue
   if isinstance(value,dict) and value.get('result')=='pass':rows.append(value)
  assert len(rows)==1 and len(rows[0]['outputs'])==2,rows
  assert {o['name'] for o in rows[0]['outputs']}=={'Virtual-1','Virtual-2'}
  report['cases'].append({'mode':mode,'kms_session':rows[0]})
finally:
 (card.parent/'card0-Virtual-1'/'status').write_text('detect')
 (second/'status').write_text('detect')
 report['restored_second_connector_status']=(second/'status').read_text().strip()
 assert report['restored_second_connector_status']==original
 Path('/tmp/agentos-active-restoration-baseline-v2.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
