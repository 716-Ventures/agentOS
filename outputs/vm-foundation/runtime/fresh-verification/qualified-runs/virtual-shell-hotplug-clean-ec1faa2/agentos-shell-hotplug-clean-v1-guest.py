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
  result=subprocess.run(['python3','/home/developer/agent-os-source/tests/direct_display_guest.py',mode],capture_output=True,text=True,timeout=180)
  Path('/tmp/agentos-shell-hotplug-clean-v1-'+str(index)+'.log').write_text(result.stdout+result.stderr)
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
 Path('/tmp/agentos-shell-hotplug-clean-v1.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
