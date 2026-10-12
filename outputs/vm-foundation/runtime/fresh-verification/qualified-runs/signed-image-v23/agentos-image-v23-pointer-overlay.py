from pathlib import Path
import sys,subprocess,hashlib,json
sys.path.insert(0,'outputs/vm-foundation');import vm
args=vm.ssh_args();args[-1]='verifier@127.0.0.1';args=[('UserKnownHostsFile='+str(vm.RUN/'image-v23-attempt1-known-hosts') if x.startswith('UserKnownHostsFile=') else x) for x in args]
remote='/home/verifier/qualification/tests/direct_input_probe.py'
old=subprocess.check_output(['git','show','1364822625108213aa7f5e4e72bd3153902254b7:outputs/agent-shell/tests/direct_input_probe.py'])
current=Path('outputs/agent-shell/tests/direct_input_probe.py').read_bytes()
h=lambda b:hashlib.sha256(b).hexdigest()
before=subprocess.check_output(args+['cat '+remote]);assert h(before)==h(old)
subprocess.run(args+['cat > '+remote],input=current,check=True)
after=subprocess.check_output(args+['cat '+remote]);assert after==current
receipt={'base_qualification_archive_sha256':h(Path('/tmp/agentos-hangup-qualified-source-v1.tar').read_bytes()),'base_source_revision':'273d5c1dee9af20acd06023c32307e56c995e781','overlay_source_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'path':'tests/direct_input_probe.py','before_sha256':h(before),'after_sha256':h(after),'runtime_binaries_changed':False,'scope':'Test input spacing only; installed runtime and all other qualification sources unchanged.'}
(vm.RUN/'image-v23-pointer-overlay.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('Applied and hash-verified test-only pointer spacing overlay; installed runtime unchanged',flush=True)
