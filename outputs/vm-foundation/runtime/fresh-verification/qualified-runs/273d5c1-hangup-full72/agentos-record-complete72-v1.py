from pathlib import Path
import json,hashlib,shutil,gzip,subprocess
root=Path('outputs/vm-foundation/runtime/fresh-verification')
path=Path('outputs/vm-foundation/native-verification.json')
r=json.loads((root/'reproduction.json').read_text())
revision='273d5c1dee9af20acd06023c32307e56c995e781'
assert r['result']=='pass' and len(r['checks'])==72 and r['guest_stopped'] and r['owned_utm_app_closed']
assert r['deployment']['repository_revision']==revision and not r['deployment']['source_changes']
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert h(Path('/tmp/agentos-hangup-qualified-source-v1.tar'))==r['deployment']['source_archive_sha256']
ci=json.loads(Path('/tmp/agentos-hangup-ci-v1.json').read_text())
assert ci['status']=='completed' and ci['conclusion']=='success' and ci['headSha']==revision
repeat=json.loads(Path('/tmp/agentos-restoration-clean-v2-driver.json').read_text())
assert repeat['source_revision']==revision and repeat['source_clean'] and repeat['installed_runtime']==r['runtime_release']
assert repeat['original_config_restored'] and repeat['original_disk_efi_inodes_preserved'] and repeat['owned_utm_closed']
assert repeat['all_deployed_source_files_verified']>200
assert len(repeat['virtual_kms']['cases'])==4 and all(row['kms_session']['result']=='pass' for row in repeat['virtual_kms']['cases'])
d=json.loads(path.read_text());dest=root/'qualified-runs/273d5c1-hangup-full72';dest.mkdir(exist_ok=True)
for src,name in [(root/'reproduction.json','reproduction.json'),(Path('/tmp/agentos-complete72-v1.log'),'driver.log'),(Path('/tmp/agentos-hangup-ci-v1.log'),'linux-ci.log'),(Path('/tmp/agentos-hangup-ci-v1.json'),'ci.json'),(Path('/tmp/agentos-complete72-v1-installed-speech.log.gz'),'installed-reader-speech.log.gz'),(Path('/tmp/agentos-complete72-v1-direct-speech.log.gz'),'direct-reader-speech.log.gz')]:shutil.copyfile(src,dest/name)
for name in r['checks']:shutil.copyfile(root/(name+'.log'),dest/(name+'.log'))
for source in ['/tmp/agentos-complete72-v1.py','/tmp/agentos-capture-complete72-reader-v1.py','/tmp/agentos-record-complete72-v1.py']:
 shutil.copyfile(source,dest/Path(source).name)
clean=root/'qualified-runs/explicit-restoration-clean-273d5c1';clean.mkdir(exist_ok=True)
for src in Path('/tmp').glob('agentos-restoration-clean-v2*'):
 if src.suffix=='.plist':continue
 if src.suffix=='.log':(clean/(src.name+'.gz')).write_bytes(gzip.compress(src.read_bytes(),mtime=0))
 elif src.suffix in ('.py','.json','.png'):shutil.copyfile(src,clean/src.name)
journeys=[]
for index,count in enumerate([60,100,140,60]):
 text=Path(f'/tmp/agentos-restoration-clean-v2-{index}.log').read_text()
 observed=[json.loads(line.split(': ',1)[1]) for line in text.splitlines() if line.startswith('Completed output journey: ')]
 assert sum(len(row['receipts']) for row in observed)==count
 journeys.append({'case':index,'named_key_frames':count})
(clean/'summary.json').write_text(json.dumps({**repeat,'journeys':journeys},indent=2)+'\n')
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
 if utterance==" 'Agent Monitor":navigation.append(0)
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
monitor_speech={'raw_sha256':hashlib.sha256(direct).hexdigest(),'completed_exact_work_utterances_by_monitor_window_speech_episode':navigation,'reopen_speech_before_tree_inspection_verified_by_direct_probe':monitor['reader_announced_reopens'],'background_failure_announcements':len(announcements),'marker_required_inside_completed_speech_utterance':True}
(dest/'monitor-completed-speech-summary.json').write_text(json.dumps(monitor_speech,indent=2)+'\n')
assert '66 passed; 0 failed' in (dest/'native-build.log').read_text()
for name in ('direct-display-input-vt','direct-display-fresh-profile-input'):
 content=(dest/(name+'.log')).read_text()
 assert 'PASS: two kernel keyboards retain merged Shift' in content
 report=json.loads(next(line for line in content.splitlines() if line.startswith('{"result": "pass"')))
 assert report['multiple_keyboard_input_qualified']
previous={k:d[k] for k in ['runtime_release','finished_at','deployment','full_run_evidence','current_native_editor_receipts','ui_dependency','public_ui_release']}
previous['checks']=len(d['checks']);not_tested=d['not_tested'];d.update(r);d['not_tested']=not_tested
reg=d['additional_targeted_regressions'];reg['pre_multi_keyboard_complete70']=previous
reg['multi_keyboard_first_full70_ci_failure']={**json.loads((root/'qualified-runs/e2bae2c-full70-ci-failure/summary.json').read_text()),'evidence_directory':'qualified-runs/e2bae2c-full70-ci-failure'}
reg['session_hangup_cleanup'].update(complete_suite_pending=False,complete_suite_verified=True,complete_suite_check_count=72,clean_source_revision=revision,complete_runtime_release=r['runtime_release'])
reg['post_undo_mapped_identity'].update(complete70_pending=False,complete70_verified=True,clean_source_revision=revision,complete70_runtime_release=r['runtime_release'])
reg['installed_approval_absent_child'].update(subsequent_ci_and_clean_source_full70_pending=False,complete70_verified=True,clean_source_revision=revision,private_ci_run=ci['databaseId'])
reg['multiple_keyboard_ownership'].update(complete70_pending=False,complete70_verified=True,clean_source_revision=revision,complete70_runtime_release=r['runtime_release'])
reg['scene_snapshot_sharing'].update(complete70_pending=False,complete70_verified=True,clean_source_revision=revision,complete70_runtime_release=r['runtime_release'])
reg['mapped_copy_popup_lease'].update(complete70_pending=False,complete70_verified=True,clean_source_revision=revision,complete70_runtime_release=r['runtime_release'])
reg['explicit_output_restoration'].update(complete70_pending=False,complete70_verified=True,clean_final_four_mode_repeat_pending=False,clean_final_four_mode_repeat_verified=True,clean_source_revision=revision,private_ci_run=ci['databaseId'],clean_repeat_evidence_directory=str(clean.relative_to(root)),clean_repeat_named_key_frames=360,complete70_runtime_release=r['runtime_release'])
d['full_run_evidence']={'source_revision':revision,'evidence_directory':str(dest.relative_to(root)),'reproduction_sha256':h(dest/'reproduction.json'),'driver_log_sha256':h(dest/'driver.log'),'check_log_sha256':{name:h(dest/(name+'.log')) for name in r['checks']},'ci_run':ci['databaseId'],'ci_result':'success','ci_source_revision':revision,'installed_reader_raw_speech_sha256':hashlib.sha256(raw).hexdigest(),'direct_reader_raw_speech_sha256':hashlib.sha256(direct).hexdigest(),'inactive_host_failure_speech_count':0,'active_monitor_reader':monitor,'monitor_completed_speech':monitor_speech,'virtual_restore_clean_repeat':str(clean.relative_to(root))}
d['current_native_editor_receipts']={}
for name in ['direct-native-feedback-load','direct-native-feedback','direct-rotated-output']:
 line=next(s for s in (dest/(name+'.log')).read_text().splitlines() if s.startswith('Native GTK input-to-presentation measurement '))
 data=json.loads(line.split('measurement ',1)[1]);d['current_native_editor_receipts'][name]=data
 assert data['presented']==20 and data['invalid']==0 and data['discarded']==0 and data['pending']==0 and data['p95_ms']<=50
receipts=d['current_native_editor_receipts']
text=f"Clean source 273d5c1 passes all 72 runtime checks with 716 UI alpha.43 and runtime {r['runtime_release']}. Preferred display return leaves active editing on the recovery display until the human chooses Restore preferred placement in Agent Monitor. Original saved placements, drafts and typing survive; new floating controls remain reachable, the exact trusted renderer authorizes restoration, and stale topology/recovery/activity offers and same-user observer injection are rejected. All 66 compositor tests pass. Session SIGHUP uses graceful teardown; dedicated hangup and forced-systemd-stop regressions verify owned children, session directories and PAM scope cleanup. Expanded ordinary-input journeys have a 120-second whole-journey watchdog and unchanged individual interaction and 50 ms p95 limits. Installed approval searches tolerate absent AT-SPI children, and post-Undo input waits for a unique mapped compositor identity without replaying the action; both fixture regressions and prior failures remain retained. Multi-keyboard ownership and partial/final device removal preserve held modifiers, reject on-screen input until the final release and restore balanced lowercase typing in both ordinary and fresh-profile installed journeys. Immutable shared scenes avoid copying workspace history during rendering and input reads. Mapped collection Copy menus retain interaction leases through GTK activation and root-focus handoffs until dismissal; the identical final native fixture fails with the old handler and passes with the fix. All 36 native Rust tests pass (7 existing ignored). The prior a45fb85 full run stopped at a guarded List update after 49 checks; that failure remains retained without assigning its exact historical cause. An exact clean-source four-mode virtual KMS repeat verifies every deployed source file and 360 named kernel-key frames through secondary, primary and total display loss, plus retained launcher/keyboard identities and actual restoration controls. Native editor p95 is {receipts['direct-native-feedback']['p95_ms']} ms idle, {receipts['direct-native-feedback-load']['p95_ms']} ms loaded and {receipts['direct-rotated-output']['p95_ms']} ms rotated, with all 60 presentation receipts completed. Installed and direct reader journeys retain three exact-work Monitor reopens before tree inspection and one background failure announcement. Rollback/interruption, reboot, repeat installation, VT resume and exact owned guest/app cleanup pass. CI {ci['databaseId']} is green. Signed v22 retains its separately qualified c57b60 runtime pending a new image qualification. Physical audio/braille/input/GPU/hotplug, live providers and full reference conformance remain unqualified; retained historical intermittent failures still have no established cause unless independently demonstrated."
d['observations'].append(text);path.write_text(json.dumps(d,indent=2)+'\n')
p=Path('outputs/implementation-status.md');s=p.read_text();a=s.index('Current October 12 progress:');b=s.index('\n\n',a);s=s[:a]+'Current October 12 progress: '+text+s[b:];s+='\n'+text+'\n';p.write_text(s)
p=Path('outputs/vm-foundation/README.md');p.write_text(p.read_text()+'\n'+text+'\n')
print(text)
