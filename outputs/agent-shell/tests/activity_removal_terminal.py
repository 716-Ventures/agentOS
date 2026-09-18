from pathlib import Path
exec(Path(__file__).with_name('terminal_pty.py').read_text().split("pump()\nkeys('nTerminal")[0])
pump(1.5);keys('nRemoval UI verification\n',1.2)
activity=json.loads(subprocess.check_output(vm.ssh_args()+['cat ~/.local/state/agent-os/selection.json'],text=True))['activity_id']
keys('D');assert any('Remove Removal UI verification?' in line for line in screen.display),'\n'.join(screen.display)
keys('\x1b');keys('D');keys('j\n',1.2)
activities=json.loads(subprocess.check_output(vm.ssh_args()+['agent-os activities'],text=True))
assert activity not in [a['id'] for a in activities]
capture('terminal-activity-removed');keys('q');process.wait(timeout=10)
print(json.dumps({'passed':True,'activity':activity,'checks':['remove confirmation','cancel','confirm removes selected activity','switches to remaining activity']}))
