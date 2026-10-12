from pathlib import Path
import json,hashlib,shutil,gzip
root=Path('outputs/vm-foundation/runtime/fresh-verification');path=Path('outputs/vm-foundation/native-verification.json')
r=json.loads((root/'reproduction.json').read_text())
revision='d600160d7a6b83c1ea6a2b83a50ed087980b2674'
assert r['result']=='pass' and len(r['checks'])==70 and r['guest_stopped'] and r['owned_utm_app_closed']
assert r['deployment']['repository_revision']==revision and not r['deployment']['source_changes']
assert json.loads((root/'qualified-runs/virtual-multihead-clean-d600160/summary.json').read_text())['source_revision']==revision
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert h(Path('/tmp/agentos-multihead-qualified-source-v2.tar'))==r['deployment']['source_archive_sha256']
ci=json.loads(Path('/tmp/agentos-multihead-ci-v2.json').read_text());assert ci['status']=='completed' and ci['conclusion']=='success' and ci['headSha']==revision
d=json.loads(path.read_text());assert d['full_run_evidence']['source_revision']=='2f09daf9e8856eadf80a71275f9fc7218f54ed92'
dest=root/'qualified-runs/d600160-multi-output-full70';dest.mkdir(exist_ok=True)
for src,name in [(root/'reproduction.json','reproduction.json'),(Path('/tmp/agentos-multihead-full70-v2.log'),'driver.log'),(Path('/tmp/agentos-multihead-ci-v2.log'),'linux-ci.log'),(Path('/tmp/agentos-multihead-ci-v2.json'),'ci.json'),(Path('/tmp/agentos-multihead-full70-v2-installed-speech.log.gz'),'installed-reader-speech.log.gz'),(Path('/tmp/agentos-multihead-full70-v2-direct-speech.log.gz'),'direct-reader-speech.log.gz'),(Path('/tmp/agentos-capture-multihead-reader-v2.py'),'speech-capture-driver.py')]:shutil.copyfile(src,dest/name)
for name in r['checks']:shutil.copyfile(root/(name+'.log'),dest/(name+'.log'))
shutil.copyfile('/tmp/agentos-multihead-ci-first.json',dest/'previous-690f070-ci.json')
shutil.copyfile('/tmp/agentos-legacy-barrier-ci.json',dest/'previous-f4b580a-ci.json')
raw=gzip.decompress((dest/'installed-reader-speech.log.gz').read_bytes());direct=gzip.decompress((dest/'direct-reader-speech.log.gz').read_bytes())
active=False;spoken=[]
for line in raw.decode(errors='replace').splitlines():
 if 'START ' in line and 'OBJECT EVENT ' in line:active='OBJECT:ANNOUNCEMENT' in line
 if active and "SPEECH OUTPUT: 'failed'{" in line:spoken.append(line)
 if ('END ' in line or 'FINISHED ' in line) and 'OBJECT EVENT ' in line:active=False
assert len(spoken)==1,spoken
assert not any("SPEECH OUTPUT: 'core · failed" in line for line in raw.decode(errors='replace').splitlines())
assert b'Reader result outcome: failed' in raw and b'Reader failure outcome: failed' in raw
assert sum(b'SPEECH OUTPUT:' in line and b'Ask Agent text' in line for line in direct.splitlines())>=10
monitor=next(line for line in (dest/'direct-display-screen-reader.log').read_text().splitlines() if line.startswith('PASS: active Monitor reader selection '))
monitor=json.loads(monitor.split('selection ',1)[1]);assert monitor['failure_announcements']==1 and monitor['trusted_clipboard_roundtrip'] and monitor['selected_snapshot_preserved'] and monitor['reader_announced_reopens']==3
import re
raw_direct=direct.decode(errors='replace');marker=re.search(r'monitor-reader-[0-9a-f]{12}',raw_direct).group();navigation=[];announcements=[];block=None
for chunk in raw_direct.split('SPEECH OUTPUT:')[1:]:
 utterance,complete,_=chunk.partition("'{'established':")
 if not complete:continue
 if utterance==" 'Agent Monitor button":navigation.append(0)
 if utterance.startswith(" 'core · failed\n") and marker in utterance:
  assert navigation;navigation[-1]+=1
assert len(navigation)==4 and all(n>=1 for n in navigation),navigation
for line in raw_direct.splitlines():
 if 'START ' in line and 'OBJECT EVENT ' in line:block=[] if 'OBJECT:ANNOUNCEMENT' in line else None
 if block is not None:block.append(line)
 if ('END ' in line or 'FINISHED ' in line) and 'OBJECT EVENT ' in line:
  if block is not None:
   for chunk in '\n'.join(block).split('SPEECH OUTPUT:')[1:]:
    utterance,complete,_=chunk.partition("'{'established':")
    if complete and utterance.startswith(" 'core · failed\n") and marker in utterance:announcements.append(utterance)
  block=None
assert len(announcements)==1,announcements
monitor_speech={'raw_sha256':hashlib.sha256(direct).hexdigest(),'completed_exact_work_utterances_by_monitor_button_episode':navigation,'reopen_speech_before_tree_inspection_verified_by_direct_probe':monitor['reader_announced_reopens'],'background_failure_announcements':len(announcements),'marker_required_inside_completed_speech_utterance':True}
(dest/'monitor-completed-speech-summary.json').write_text(json.dumps(monitor_speech,indent=2)+'\n')
previous={k:d[k] for k in ['runtime_release','finished_at','deployment','full_run_evidence','current_native_editor_receipts','ui_dependency','public_ui_release']};previous['checks']=len(d['checks'])
not_tested=d['not_tested'];d.update(r);d['not_tested']=not_tested;d['additional_targeted_regressions']['pre_multi_output_complete70']=previous
d['additional_targeted_regressions']['virtual_multi_output'].update(full70_pending=False,complete70_verified=True,clean_source_revision=revision,private_ci_run=38201831893,clean_repeat_evidence_directory='qualified-runs/virtual-multihead-clean-d600160')
d['full_run_evidence']={'source_revision':revision,'evidence_directory':str(dest.relative_to(root)),'reproduction_sha256':h(dest/'reproduction.json'),'driver_log_sha256':h(dest/'driver.log'),'check_log_sha256':{name:h(dest/(name+'.log')) for name in r['checks']},'ci_run':38201831893,'ci_result':'success','ci_source_revision':revision,'installed_reader_raw_speech_sha256':hashlib.sha256(raw).hexdigest(),'direct_reader_raw_speech_sha256':hashlib.sha256(direct).hexdigest(),'inactive_host_failure_speech_count':0,'active_monitor_reader':monitor}
d['full_run_evidence']['monitor_completed_speech']=monitor_speech
d['current_native_editor_receipts']={}
for name in ['direct-native-feedback-load','direct-native-feedback','direct-rotated-output']:
 line=next(s for s in (dest/(name+'.log')).read_text().splitlines() if s.startswith('Native GTK input-to-presentation measurement '));data=json.loads(line.split('measurement ',1)[1]);d['current_native_editor_receipts'][name]=data
 assert data['presented']==20 and data['invalid']==0 and data['discarded']==0 and data['pending']==0 and data['p95_ms']<=50
 print(name,data['p95_ms'])
receipts=d['current_native_editor_receipts']
text=f"Clean source d600160 passes all 70 runtime checks with unchanged 716 UI alpha.43 and runtime {r['runtime_release']}. Absolute pointer devices now span the logical desktop and clamp gaps to live outputs; DRM resume resets connector and cached surface state so both heads modeset after VT switching. A separate exact clean-source repeat verifies kernel pointer focus and 60 output-named keyboard-triggered presentation receipts across Virtual-1, Virtual-2 and return to Virtual-1. The old pointer mapping and second-head post-VT frame failure remain independently retained. UTM controller v3 completes LaunchServices open before creating ScriptingBridge; six rapid cold launches and three actual boot/readiness/shutdown cycles pass, with original configuration and exact owned app exit. The first 690f070 full run failed after 33 checks when GTK self-test window lifecycle changed the legacy Undo revision; the isolated revision fixture now passes without changing production Undo or replaying mutations. Three actual Monitor reopens each still produce exact-work Orca speech before tree inspection, with one background failure announcement; installed Status remains quiet for inactive Monitor. Native editor presentation p95 is {receipts['direct-native-feedback']['p95_ms']} ms idle, {receipts['direct-native-feedback-load']['p95_ms']} ms loaded and {receipts['direct-rotated-output']['p95_ms']} ms rotated; all 60 receipts complete without invalid, discarded or pending receipts. Rollback/interruption, reboot, repeat install and exact owned guest/app cleanup pass. Private CI 38201831893 is green; public alpha.43 CI 38187956822 remains green. Signed v21 retains its separately qualified 54b321 runtime pending a new image qualification. Virtual two-output presentation/input is now qualified; physical audio/braille/input/GPU, live hotplug, multi-output system layers, live providers and full reference conformance remain unqualified."
d['observations'].append(text);path.write_text(json.dumps(d,indent=2)+'\n')
p=Path('outputs/implementation-status.md');s=p.read_text();a=s.index('Current October 11 progress:');b=s.index('\n\n',a);s=s[:a]+'Current October 12 progress: '+text+s[b:];s+='\n'+text+'\n';p.write_text(s)
p=Path('outputs/vm-foundation/README.md');p.write_text(p.read_text()+'\n'+text+'\n')
print('Recorded',r['runtime_release'],r['finished_at'])
