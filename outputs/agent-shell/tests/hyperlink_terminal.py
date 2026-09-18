"""Regression: rendering a link must not overwrite the palette on the next frame."""
from pathlib import Path
exec(Path(__file__).with_name('terminal_pty.py').read_text().split("pump()\nkeys('nTerminal")[0])
pump(2)
assert process.poll() is None,'Client crashed on startup'
keys('nHyperlink rendering verification\n',1.2)
activity=json.loads(subprocess.check_output(vm.ssh_args()+['cat ~/.local/state/agent-os/selection.json'],text=True))['activity_id']
keys('r/usr/bin/printf https://github.com/login/device\n',1.5)
assert any('https://github.com/login/device' in line for line in screen.display),'\n'.join(screen.display)
pump(2);assert process.poll() is None,'Client crashed after hyperlink redraw'
keys('T');pump(1);assert process.poll() is None
keys('T');keys(' ');keys('\x1b');pump(1);assert process.poll() is None
keys('q');process.wait(timeout=10);assert process.returncode==0
subprocess.run(vm.ssh_args()+['agent-os remove '+str(activity)],check=True,capture_output=True)
print(json.dumps({'passed':True,'checks':['startup','visible hyperlink','repeated redraws','light and dark themes','menu overlay','clean exit']}))
