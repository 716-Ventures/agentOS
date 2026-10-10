#!/usr/bin/python3
"""Independent assistive journey through the installed desktop and root broker.

Run as developer inside dbus-run-session in the dedicated development guest.
Approves only harmless stdin echo and bounded sleep fixtures; calls no models.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

import pyatspi
import accessibility
sys.path.insert(0, '/usr/local/lib/agent-os/services')
from broker_client import request

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'test-output'
OUTPUT.mkdir(exist_ok=True)


def button(name, work=None):
    # Completed work retains disabled controls. Select only the actionable row.
    found = []
    def search():
        from collections import deque
        queue = deque([pyatspi.Registry.getDesktop(0)])
        visited = 0
        while queue and visited < 4096:
            node = queue.popleft()
            visited += 1
            try:
                if (node.name == name and node.getRole() == pyatspi.ROLE_PUSH_BUTTON
                        and node.getState().contains(pyatspi.STATE_SENSITIVE)):
                    ancestor = node
                    matches = work is None or node.description == "Work broker:" + str(work)
                    for _ in range(32):
                        if ancestor is None:
                            break
                        if ancestor.name == 'Work broker:' + str(work):
                            matches = True
                            break
                        ancestor = ancestor.parent
                    if matches:
                        found.append(node)
                        return True
                queue.extend(node[index] for index in range(min(node.childCount, 128)))
            except (RuntimeError, LookupError):
                pass
        return False
    try:
        accessibility.wait(search, 'Actionable installed control missing: ' + name)
    except AssertionError:
        from collections import deque
        queue = deque([pyatspi.Registry.getDesktop(0)])
        for _ in range(512):
            if not queue:break
            node=queue.popleft()
            try:
                print('Accessible:',node.getRoleName(),repr(node.name),repr(node.description),
                      'sensitive=',node.getState().contains(pyatspi.STATE_SENSITIVE),flush=True)
                queue.extend(node[index] for index in range(min(node.childCount,128)))
            except (RuntimeError,LookupError):pass
        raise
    return found[0]


def reap(proc):
    if proc is None:
        return
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=12)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)


def main():
    activity = json.loads(subprocess.check_output(['agent-os', 'create', 'Installed native broker verification']))['id']
    jobs = []
    host = desktop = None
    def propose(argv, stdin=None):
        fields = {} if stdin is None else {'stdin': stdin}
        job = request('execute', activity=activity, argv=argv,
                      purpose='Harmless native review verification', request_confirmation=True,
                      timeout_seconds=40, **fields)
        assert job['status'] == 'approval_required', job
        jobs.append(job['id'])
        return job['id']
    def poll(ident):
        return request('poll', job_id=ident)
    def click(name, work=None):
        accessibility.activate(button(name, work))
    text = 'Native reviewed stdin λ 日本語\n$(literal input, never a command)'
    echo = ['/usr/bin/python3', '-c', 'import sys; print(sys.stdin.read(),end="")']
    try:
        approved = propose(echo, text)
        with tempfile.TemporaryDirectory(prefix='agentos-installed-broker-') as directory:
            root = Path(directory)
            runtime = root / 'runtime'
            runtime.mkdir(mode=0o700)
            env = {**os.environ, 'HOME': directory, 'XDG_RUNTIME_DIR': str(runtime),
                   'XDG_CONFIG_HOME': str(root / 'config'), 'XDG_STATE_HOME': str(root / 'state'),
                   'WAYLAND_DISPLAY': 'installed-broker-test', 'GDK_BACKEND': 'wayland',
                   'GSK_RENDERER': 'cairo', 'GTK_A11Y': 'atspi', 'G_DEBUG': 'fatal-criticals'}
            env.pop('AGENT_OS_SOCKET', None)
            env.pop('AGENT_OS_BROKER_SOCKET', None)
            # D-Bus activation must use this user's private test runtime, too.
            subprocess.run(['dbus-update-activation-environment', 'HOME', 'XDG_RUNTIME_DIR',
                            'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'GDK_BACKEND', 'GTK_A11Y'],
                           env=env, check=True)
            with (OUTPUT / 'installed-broker.log').open('w') as log:
                try:
                    host = subprocess.Popen(['weston', '--backend=headless-backend.so', '--use-pixman',
                                             '--socket=installed-broker-test', '--idle-time=0'],
                                            env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    accessibility.wait(lambda: (runtime / 'installed-broker-test').exists(), 'Private display failed to start')
                    desktop = subprocess.Popen(['/usr/local/bin/agent-os-desktop', '--activity', str(activity)],
                                               env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    click('Agent Monitor')
                    click('Review approval', approved)
                    click('Inspect stored input')
                    preview = accessibility.find('Stored operation input', pyatspi.ROLE_TEXT)
                    accessibility.wait(lambda: accessibility.text(preview) == text, 'Privileged input inspection did not show exact Unicode text')
                    assert poll(approved)['status'] == 'approval_required', 'Inspection executed the proposal'
                    click('Approve this operation')
                    accessibility.wait(lambda: poll(approved)['status'] == 'succeeded', 'Native approval did not execute the harmless fixture')
                    assert poll(approved)['output'] == text
                    rejected = propose(echo, 'Rejected input must not run')
                    click('Review approval', rejected)
                    click('Reject this operation')
                    accessibility.wait(lambda: poll(rejected)['status'] == 'rejected', 'Native rejection did not cancel the proposal')
                    assert poll(rejected)['output'] == ''
                    sleeping = propose(['/usr/bin/sleep', '30'])
                    click('Review approval', sleeping)
                    click('Approve this operation')
                    accessibility.wait(lambda: poll(sleeping)['status'] == 'running', 'Bounded sleep fixture did not start')
                    click('Stop work', sleeping)
                    accessibility.wait(lambda: poll(sleeping)['status'] == 'cancelled', 'Native stop did not cancel installed systemd work')
                    print('PASS: installed native AT-SPI review, exact root input preview, deliberate approval, rejection and direct systemd stop without models')
                finally:
                    reap(desktop)
                    desktop = None
                    reap(host)
                    host = None

    finally:
        reap(desktop)
        reap(host)
        for ident in jobs:
            request('cancel', job_id=ident)
        subprocess.run(['agent-os', 'remove', str(activity)], check=True, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
