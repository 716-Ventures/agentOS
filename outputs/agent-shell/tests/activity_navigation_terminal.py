from pathlib import Path
exec(Path(__file__).with_name('terminal_pty.py').read_text().split("pump()\nkeys('nTerminal")[0])
pump(1.5);keys('nKeyboard navigation A\n',1.2);keys('nKeyboard navigation B\n',1.2)
def selected_activity():return json.loads(subprocess.check_output(vm.ssh_args()+['cat ~/.local/state/agent-os/selection.json'],text=True))['activity_id']
b=selected_activity()
keys('\x1bOD');assert any('Activities ◂' in line for line in screen.display),'\n'.join(screen.display)
keys('\x1bOB',1.2);a=selected_activity();assert a!=b
keys('\x1bOA',1.2);assert selected_activity()==b
keys('d');assert any('Remove Keyboard navigation B?' in line for line in screen.display),'\n'.join(screen.display)
keys('\x1b');keys('d');keys('j\n',1.2)
activities=json.loads(subprocess.check_output(vm.ssh_args()+['agent-os activities'],text=True));assert b not in [x['id'] for x in activities]
size(60,24);screen.resize(24,60);pump(1)
assert any('Activities ◂' in line for line in screen.display)
capture('terminal-activity-keyboard')
keys('\n');keys('\n');assert any('Reply to Agent' in line for line in screen.display)
keys('\x1b');keys('q');process.wait(timeout=10)
# Retire the other test activity; never remove user activities.
subprocess.run(vm.ssh_args()+['agent-os remove '+str(a)],check=True,capture_output=True)
print(json.dumps({'passed':True,'checks':['left focuses activities','down and up select activities','lowercase d opens removal','cancel and confirm','compact activity navigation','Enter opens work then reply']}))
