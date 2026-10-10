#!/usr/bin/python3
"""Bounded direct KMS/seat/VT qualification in the dedicated development VM.

Run as root. Owns one transient local login on unused VT 7, restores the original
VT and stops the session even after failure. Optional uinput devices exercise the kernel stack, not physical host input.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import socket
import subprocess
import tempfile
import time
import uuid


def command(*argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hold-seconds', type=int, default=0, choices=range(31),
                        help='Keep the verified desktop visible briefly for console inspection (0–30 seconds)')
    parser.add_argument('--input',action='store_true',help='Exercise temporary kernel input devices in this dedicated VM')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run this dedicated-VM display qualification with sudo')
    login = json.loads(Path('/etc/agent-os/login-user.json').read_text())
    user = pwd.getpwnam(login['name'])
    if user.pw_uid < 1000 or user.pw_uid != login['uid']:
        raise RuntimeError('Installed ordinary login identity changed')
    runtime = Path('/run/user') / str(user.pw_uid)
    original = Path('/sys/class/tty/tty0/active').read_text().strip()
    if original == 'tty7':
        raise RuntimeError('VT 7 is already active; no session was changed')
    sessions = json.loads(subprocess.check_output(['loginctl', 'list-sessions', '--json=short'], text=True))
    if any(row.get('tty') == 'tty7' for row in sessions):
        raise RuntimeError('VT 7 already has a login; no session was changed')
    unit = 'agentos-display-test-' + uuid.uuid4().hex
    before = set(runtime.glob('agentos-session-*'))
    owned = set()
    leader = None
    snapshot = None
    verified = False
    activity = surface = None
    with tempfile.TemporaryDirectory(prefix='agentos-display-metrics-') as directory:
        metrics = Path(directory)
        os.chown(metrics, user.pw_uid, user.pw_gid)
        def control(path, op):
            with socket.socket(socket.AF_UNIX) as conn:
                # The server bounds queued control work at five seconds. This
                # read-only observer must allow that bound during a VT transition.
                conn.settimeout(6)
                conn.connect(str(path))
                conn.sendall(json.dumps({'op': op}).encode() + b'\n')
                result = json.loads(conn.makefile('rb').readline(65537))
                if not result.get('ok'):
                    raise RuntimeError(result.get('error', 'Display control unavailable'))
                return result.get('result')
        try:
            if args.input:
                fixture=metrics/'Direct input fixture';fixture.write_text('');os.chown(fixture,user.pw_uid,user.pw_gid)
                activity=json.loads(command('runuser','-u',user.pw_name,'--','agent-os','create','Direct input verification',capture_output=True).stdout)['id']
                surface=json.loads(command('runuser','-u',user.pw_name,'--','agent-os','document','import',str(activity),str(fixture),capture_output=True).stdout)['surface_id']
            command('chvt', '7')
            command('systemd-run', '--quiet', '--unit=' + unit, '--uid=' + user.pw_name,
                    '--property=PAMName=login', '--property=TTYPath=/dev/tty7',
                    '--property=StandardInput=tty', '--property=TTYReset=yes',
                    '--property=TTYVHangup=yes', '--property=KillMode=control-group',
                    '--property=StandardOutput=journal', '--property=StandardError=journal',
                    '--property=TimeoutStopSec=15', '--property=RuntimeMaxSec=90',
                    '--setenv=XDG_RUNTIME_DIR=' + str(runtime),
                    '--setenv=XDG_SESSION_TYPE=wayland', '--setenv=XDG_SESSION_CLASS=user',
                    '--setenv=XDG_SEAT=seat0', '--setenv=XDG_VTNR=7',
                    '--setenv=LIBSEAT_BACKEND=logind', '--setenv=AGENT_OS_METRICS_DIR=' + directory,
                    *(['--setenv=GTK_A11Y=atspi'] if args.input else []),
                    '/usr/bin/dbus-run-session', '--', '/usr/local/bin/agent-os-session', '--backend', 'direct',
                    *(['--activity',str(activity)] if activity else []))
            leader = int(subprocess.check_output(['systemctl', 'show', unit, '--property=MainPID', '--value'], text=True))
            assert leader > 0, 'Local login wrapper did not start'
            deadline = time.monotonic() + 30
            endpoint = None
            while time.monotonic() < deadline:
                owned.update(set(runtime.glob('agentos-session-*')) - before)
                endpoints = [p for root in owned for p in root.glob('agentos-compositor-*.sock')]
                if endpoints:
                    try:
                        snapshot = control(endpoints[0], 'snapshot')
                        if (snapshot['windows'] and snapshot['outputs'] and snapshot['direct_frames_presented'] > 0
                                and snapshot['shared'] and not snapshot['shared']['error']):
                            endpoint = endpoints[0]
                            break
                    except (OSError, RuntimeError):
                        pass
                time.sleep(.1)
            if endpoint is None:
                raise RuntimeError('Direct display did not expose a native window and output within 30 seconds')
            assert all(row['width'] > 0 and row['height'] > 0 for row in snapshot['outputs']), snapshot
            assert snapshot['shared'] and not snapshot['shared']['error'], snapshot
            command('chvt', original.removeprefix('tty'))
            time.sleep(.5)
            command('chvt', '7')
            deadline = time.monotonic() + 5
            while True:
                try:
                    resumed = control(endpoint, 'snapshot')
                    assert resumed['outputs'] == snapshot['outputs'], resumed
                    assert resumed['windows'], resumed
                    if resumed['direct_frames_presented'] <= snapshot['direct_frames_presented']:
                        raise RuntimeError('No completed KMS frame after VT resume')
                    break
                except (OSError, RuntimeError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.1)
            if args.input:
                import direct_input_probe
                def core(op):
                    payload={'op':op,**({'document_id':surface} if op=='presentation.get' else {'surface_id':surface,'element_id':'editor'})}
                    return json.loads(command('runuser','-u',user.pw_name,'--','agent-os','presentation','-',input=json.dumps(payload),capture_output=True).stdout)
                def presentation(payload):
                    result=subprocess.run(['runuser','-u',user.pw_name,'--','agent-os','presentation','-'],input=json.dumps(payload),capture_output=True,text=True)
                    if result.returncode:raise RuntimeError('Fixture workspace request failed: '+result.stdout+result.stderr)
                    return json.loads(result.stdout)
                deadline=time.monotonic()+8
                def placed(value):
                    if isinstance(value,dict):
                        return value.get('surface_id')==surface or any(placed(child) for child in value.values())
                    if isinstance(value,list):return any(placed(child) for child in value)
                    return False
                while True:
                    try:
                        workspace=presentation({'op':'presentation.snapshot'})['documents'].get(f'desktop-{activity}')
                        if not workspace or not placed(workspace.get('outputs',{})):
                            if time.monotonic()>deadline:raise RuntimeError('Imported document did not receive a workspace placement')
                            time.sleep(.05);continue
                        receipt=presentation({'op':'presentation.apply','protocol':'agentos.presentation/1','catalog_revision':'native-core/1',
                            'request_id':'direct-input-focus-'+uuid.uuid4().hex,'expected_revisions':{workspace['workspace_id']:workspace['revision']},
                            'operations':[{'op':'workspace.edit','workspace_id':workspace['workspace_id'],'edit':{'kind':'maximize','surface_id':surface}},
                                          {'op':'workspace.edit','workspace_id':workspace['workspace_id'],'edit':{'kind':'focus','surface_id':surface,'element_id':'editor'}}]})
                        break
                    except RuntimeError as exc:
                        if '"code":"stale_revision"' not in str(exc) or time.monotonic()>deadline:raise
                        time.sleep(.05)
                assert receipt['status']=='committed',receipt
                deadline=time.monotonic()+8
                while True:
                    observed=control(endpoint,'snapshot')
                    target=next((ident for ident,logical in observed['shared']['identities'].items() if logical==surface),None)
                    if target is not None and observed.get('seat_focus')==target:break
                    if time.monotonic()>deadline:raise RuntimeError('Direct input fixture did not receive seat focus')
                    time.sleep(.05)
                direct_input_probe.verify(metrics,snapshot['outputs'][0],core,lambda:control(endpoint,'snapshot'),target,user.pw_name,presentation)
            if args.hold_seconds:
                print('Direct desktop ready for console inspection', flush=True)
                time.sleep(args.hold_seconds)
            control(endpoint, 'shutdown')
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                running = subprocess.run(['systemctl', 'is-active', '--quiet', unit], check=False)
                if running.returncode != 0:
                    break
                time.sleep(.1)
            verified = True
        finally:
            try:
                if subprocess.run(['systemctl', 'is-active', '--quiet', unit], check=False).returncode == 0:
                    subprocess.run(['systemctl', 'stop', unit], check=False, timeout=20)
            finally:
                # PAM moves descendants into a session scope. Accessibility bus
                # daemons may outlive the wrapper; terminate only our exact login.
                current = json.loads(subprocess.check_output(['loginctl', 'list-sessions', '--json=short'], text=True))
                for row in current:
                    if row.get('tty') == 'tty7' and row.get('uid') == user.pw_uid and row.get('leader') == leader:
                        command('loginctl', 'terminate-session', row['session'])
                        scope = 'session-' + row['session'] + '.scope'
                        if not verified:print(subprocess.check_output(['journalctl','-u',scope,'--no-pager','-o','cat','-n','80'],text=True))
                        deadline = time.monotonic() + 3
                        while time.monotonic() < deadline:
                            if subprocess.run(['systemctl', 'is-active', '--quiet', scope], check=False).returncode != 0:
                                break
                            time.sleep(.1)
                        else:
                            # Some activated accessibility bus daemons ignore
                            # SIGTERM. The exact owned scope is the cleanup bound.
                            subprocess.run(['systemctl', 'kill', '--signal=SIGKILL', '--kill-whom=all', scope], check=False)
                command('chvt', original.removeprefix('tty'))
                if activity is not None:
                    command('runuser','-u',user.pw_name,'--','agent-os','remove',str(activity),stdout=subprocess.DEVNULL)
                logs = subprocess.check_output(['journalctl', '-u', unit, '--no-pager', '-o', 'cat'], text=True)
                print(logs)
                subprocess.run(['systemctl', 'reset-failed', unit], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 5
        while any(path.exists() for path in owned) and time.monotonic() < deadline:
            time.sleep(.1)
        assert not any(path.exists() for path in owned), 'Direct session runtime leaked'
        deadline = time.monotonic() + 5
        while True:
            sessions = json.loads(subprocess.check_output(['loginctl', 'list-sessions', '--json=short'], text=True))
            if not any(row.get('leader') == leader and row.get('tty') == 'tty7' for row in sessions):
                break
            assert time.monotonic() < deadline, 'Owned local login scope leaked'
            time.sleep(.1)
        reports = [json.loads(path.read_text()) for path in metrics.glob('render-*.json')]
        assert any(row['stages'].get('compositor.direct_render_attempt', {}).get('samples_total', 0) > 0
                   for row in reports), 'Direct session produced no render diagnostics'
        print(json.dumps({'result': 'pass', 'outputs': snapshot['outputs'], 'metrics': reports,
                          'frames_before_vt': snapshot['direct_frames_presented'],
                          'frames_after_vt': resumed['direct_frames_presented'],
                          'checks': ['direct native window', 'KMS output discovery', 'shared core connection',
                                     'VT switch and resume', 'orderly shutdown', 'session directory cleanup', 'owned login scope cleanup'] + (['kernel keyboard and absolute pointer','clipboard copy/paste','undo/redo','retained draft','deliberate pointer Save','kernel workspace move/resize/maximize/restore/undo','native titlebar drag with durable placement','kernel focus cycling','kernel VT shortcut and acknowledged resume','kernel close and native assistive undo','focused primary middle-paste across Wayland clients','Unicode COPY drag/drop and grouped undo','oversized drop rejection','drag icon rendering and release cleanup'] if args.input else []),
                          'not_tested': ['physical input', 'hotplug', 'physical GPU presentation']}))


if __name__ == '__main__':
    main()
