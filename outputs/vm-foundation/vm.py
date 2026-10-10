#!/usr/bin/env python3
"""Build and operate the complete ARM64 Agent OS development guest on macOS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import select
import termios
import tty
import shutil
import subprocess
import sys
import time
import plistlib
import uuid

from build_utmctl import controller

ROOT = Path(__file__).resolve().parent
RUN = Path(os.environ.get('AGENT_OS_VM_RUNTIME',str(ROOT / 'runtime'))).expanduser().resolve()
LOCK = json.loads((ROOT / 'image-lock.json').read_text())
if os.environ.get('AGENT_OS_VM_SSH_PORT'):
    LOCK['ssh_port']=int(os.environ['AGENT_OS_VM_SSH_PORT'])
if not 1024 <= LOCK['ssh_port'] <= 65535:
    raise ValueError('Use a non-privileged SSH port between 1024 and 65535')


def call(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def digest(path):
    h = hashlib.sha512()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def machine():
    path = RUN / 'utm.json'
    if not path.exists():
        raise RuntimeError('Run prepare first, or migrate the existing disk with bundle.')
    current=json.loads(path.read_text())
    config=plistlib.loads((Path(current['bundle'])/'config.plist').read_bytes())
    if config['Information']['UUID']!=current['uuid']:
        raise RuntimeError('Selected VM metadata does not match the bundle UUID')
    actual=config['Network'][0]['PortForward'][0]['HostPort']
    if actual!=LOCK['ssh_port']:
        raise RuntimeError(f'Selected VM forwards SSH on {actual}, but the requested port is {LOCK["ssh_port"]}. Set AGENT_OS_VM_SSH_PORT to match.')
    return current


def status():
    if not (RUN / 'utm.json').exists():
        return 'stopped'
    current = machine()
    try:
        result = call([controller(), 'status', current['uuid']], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('UTM status timed out after 10 seconds; VM state is unknown. Inspect UTM before retrying.') from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f'UTM cannot find/control this guest. Open {current["bundle"]} in UTM to register it.\n{exc.stderr.strip()}') from exc
    return result.stdout.strip()


def alive():
    return status() != 'stopped'


def bundle():
    """Move a stopped standalone guest into a UTM bundle without rebuilding it."""
    if (RUN / 'utm.json').exists():
        raise RuntimeError('A UTM bundle already exists; it will not be overwritten.')
    if not (RUN / 'disk.qcow2').exists() or not (RUN / 'seed.iso').exists():
        raise RuntimeError('Run prepare first.')
    # A legacy runner must be stopped before migration; a locked disk rejects this probe.
    call(['qemu-img', 'check', '-q', RUN / 'disk.qcow2'], stdout=subprocess.DEVNULL)
    target = RUN / 'agentOS.utm'
    target.mkdir(mode=0o700)
    data = target / 'Data'
    data.mkdir(mode=0o700)
    config = plistlib.loads((ROOT / 'utm-template.plist').read_bytes())
    ident = str(uuid.uuid4()).upper()
    config['Information']['UUID'] = ident
    config['Information']['Name'] = 'agentOS '+RUN.name
    config['System']['CPUCount'] = LOCK['cpus']
    config['System']['MemorySize'] = LOCK['memory_mib']
    config['Network'][0]['MacAddress'] = '02:' + ':'.join(f'{v:02X}' for v in secrets.token_bytes(5))
    config['Network'][0]['PortForward'][0]['HostPort'] = LOCK['ssh_port']
    for drive in config['Drive']:
        drive['Identifier'] = str(uuid.uuid4()).upper()
    (target / 'config.plist').write_bytes(plistlib.dumps(config, sort_keys=False))
    # Move, rather than duplicate, the authoritative guest disk. Runtime remains ignored.
    shutil.move(RUN / 'disk.qcow2', data / 'disk.qcow2')
    shutil.copyfile(RUN / 'seed.iso', data / 'seed.iso')
    (RUN / 'utm.json').write_text(json.dumps({'uuid': ident, 'bundle': str(target), 'ssh_port': LOCK['ssh_port']}, indent=2) + '\n')
    print('Prepared UTM bundle:', target)
    print('Open this bundle once in UTM to register it, then run start.')


def prepare(source=None):
    if alive():
        raise RuntimeError('Stop the VM before preparing its image.')
    if (RUN / 'disk.qcow2').exists() or (RUN / 'utm.json').exists():
        raise RuntimeError('An existing disk will not be overwritten. Use it with start.')
    RUN.mkdir(mode=0o700, exist_ok=True)
    RUN.chmod(0o700)
    base = Path(source).resolve() if source else RUN / 'base.qcow2'
    if not base.exists():
        partial = base.with_suffix('.partial')
        call(['curl', '--fail', '--location', '--retry', '3', LOCK['base_url'], '-o', partial])
        if digest(partial) != LOCK['sha512']:
            raise RuntimeError('Base image checksum mismatch.')
        partial.replace(base)
    if digest(base) != LOCK['sha512']:
        raise RuntimeError('Base image checksum mismatch.')
    # Standalone disk: no dependency on the download path or a backing image.
    call(['qemu-img', 'convert', '-f', 'qcow2', '-O', 'qcow2', base, RUN / 'disk.qcow2'])
    call(['qemu-img', 'resize', RUN / 'disk.qcow2', LOCK['disk_size']])
    key = RUN / 'id_ed25519'
    if not key.exists():
        call(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'agent-os-local-development', '-f', key])
    password = secrets.token_urlsafe(18)
    openssl = Path('/opt/homebrew/opt/openssl@3/bin/openssl')
    encrypted = call([openssl, 'passwd', '-6', '-stdin'], input=password + '\n', text=True,
                     capture_output=True).stdout.strip()
    credentials = RUN / 'console-credentials.txt'
    credentials.write_text('User: developer\nPassword: ' + password + '\n')
    credentials.chmod(0o600)
    build = {
        'name': 'Agent OS development foundation', 'version': '0.0.1',
        'milestone': 'M0', 'base': 'Debian 13', 'architecture': 'arm64',
        'base_build': LOCK['debian_build'], 'base_sha512': LOCK['sha512'],
        'agent_runtime': 'not implemented', 'voice': 'not implemented',
        'guest_sources': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted((ROOT / 'guest').iterdir()) if p.is_file()},
    }
    files = []
    def write(path, content, permissions='0644'):
        files.append({'path': path, 'content': content, 'permissions': permissions, 'owner': 'root:root'})
    write('/etc/agent-os/release.json', json.dumps(build, indent=2) + '\n')
    write('/etc/motd', '\nAgent OS | Linux development foundation | M0\n'
          'Full ARM64 Linux guest. Agent and voice integration are not implemented yet.\n'
          'Inspect: agent-os-status    Logs: journalctl -u agent-os-foundation\n'
          'Recovery: ordinary shell and sudo remain available.\n\n')
    write('/usr/local/bin/agent-os-status', (ROOT / 'guest' / 'status.py').read_text(), '0755')
    write('/usr/local/lib/agent-os/record-boot.py', (ROOT / 'guest' / 'record-boot.py').read_text(), '0755')
    write('/etc/systemd/system/agent-os-foundation.service',
          (ROOT / 'guest' / 'agent-os-foundation.service').read_text())
    config = {
        'hostname': 'agent-os-dev', 'manage_etc_hosts': True,
        'disable_root': True, 'ssh_pwauth': False,
        'users': [{'name': 'developer', 'groups': ['sudo'], 'shell': '/bin/bash',
                   'sudo': 'ALL=(ALL) NOPASSWD:ALL', 'lock_passwd': False,
                   'passwd': encrypted, 'ssh_authorized_keys': [key.with_suffix('.pub').read_text().strip()]}],
        'package_update': False, 'package_upgrade': False,
        'write_files': files,
        'runcmd': [['systemctl', 'daemon-reload'],
                   ['systemctl', 'enable', '--now', 'agent-os-foundation.service']],
    }
    seed = RUN / 'seed'
    seed.mkdir(exist_ok=True)
    (seed / 'user-data').write_text('#cloud-config\n' + json.dumps(config, indent=2) + '\n')
    (seed / 'meta-data').write_text(json.dumps({'instance-id': 'agent-os-' + secrets.token_hex(8),
                                              'local-hostname': 'agent-os-dev'}))
    call(['hdiutil', 'makehybrid', '-iso', '-joliet', '-default-volume-name', 'CIDATA',
          '-o', RUN / 'seed.iso', seed])
    (RUN / 'build.json').write_text(json.dumps(build, indent=2) + '\n')
    (RUN / 'prepared').touch()
    bundle()
    print('First-boot configuration ready. Credentials:', credentials)


def start(hide=False):
    if alive():
        raise RuntimeError('VM is already running or suspended; inspect UTM before restarting.')
    try:
        call([controller(), 'start'] + (['--hide'] if hide else []) + [machine()['uuid']], timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('UTM start did not acknowledge within 30 seconds; do not retry automatically. Inspect the selected guest before continuing.') from exc
    observed = status()
    if observed != 'started':
        raise RuntimeError(f'UTM start returned but guest state is {observed!r}; do not retry automatically. Inspect the selected guest before continuing.')
    print(f'UTM guest started; SSH is forwarded on localhost:{LOCK["ssh_port"]}.')


def stop():
    if alive():
        try:
            call([controller(), 'stop', machine()['uuid'], '--request'], timeout=15)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('UTM shutdown did not acknowledge within 15 seconds; inspect the selected guest before continuing.') from exc
        print('Requested orderly guest shutdown. Check status before restarting.')
    else:
        print('VM already stopped.')


def console():
    if not sys.stdin.isatty():
        raise RuntimeError('Open console in an interactive terminal.')
    # UTM 4.7.5 attach prints the PTY path but does not relay input/output.
    result = call([controller(), 'attach', machine()['uuid']], capture_output=True, text=True)
    paths = [line.split(':', 1)[1].strip() for line in result.stdout.splitlines()
             if line.startswith('PTTY:')]
    if len(paths) != 1 or not paths[0].startswith('/dev/tty'):
        raise RuntimeError('UTM did not expose a serial PTY; open the serial console in UTM.')
    print('Guest serial console. Press Ctrl-] to detach without stopping the VM.')
    print('Local credentials:', RUN / 'console-credentials.txt', flush=True)
    fd = os.open(paths[0], os.O_RDWR | os.O_NOCTTY)
    original = termios.tcgetattr(sys.stdin)
    serial_original = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        tty.setraw(fd)
        os.write(fd, b'\r')
        while True:
            ready, _, _ = select.select([fd, sys.stdin], [], [])
            if fd in ready:
                data = os.read(fd, 16384)
                if not data:
                    break
                os.write(sys.stdout.fileno(), data)
            if sys.stdin in ready:
                data = os.read(sys.stdin.fileno(), 1024)
                if b'\x1d' in data or not data:
                    break
                os.write(fd, data)
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, original)
        try:
            termios.tcsetattr(fd, termios.TCSANOW, serial_original)
        finally:
            os.close(fd)
        print()



def ssh_args():
    machine()  # Verify that SSH and lifecycle operations select the same guest.
    return ['ssh', '-p', str(LOCK['ssh_port']), '-i', str(RUN / 'id_ed25519'),
            '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=accept-new',
            '-o', f'UserKnownHostsFile={RUN}/known_hosts', '-o', 'ConnectTimeout=3',
            '-o', 'BatchMode=yes', '-o', 'LogLevel=ERROR', 'developer@127.0.0.1']


def ssh(command, **kwargs):
    return subprocess.run(ssh_args() + [command], **kwargs)


def wait_ready(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        r = ssh('test -f /etc/agent-os/release.json && systemctl is-active --quiet agent-os-foundation.service',
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode == 0:
            print('Guest login and foundation service are ready.')
            return
        time.sleep(2)
    raise RuntimeError('Guest readiness deadline exceeded; inspect the display or serial console in UTM.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    b = commands.add_parser('prepare'); b.add_argument('--base')
    s = commands.add_parser('start')
    display = s.add_mutually_exclusive_group()
    display.add_argument('--hide', dest='hide', action='store_true', default=False,
                         help='Hide the UTM library window; the VM console is still created')
    display.add_argument('--show', dest='hide', action='store_false',
                         help='Keep the UTM library visible during startup (default)')
    commands.add_parser('bundle')
    w = commands.add_parser('wait'); w.add_argument('--seconds', type=int, default=60)
    c = commands.add_parser('ssh'); c.add_argument('remote', nargs=argparse.REMAINDER)
    for cmd in ['status', 'stop', 'reboot', 'console']:
        commands.add_parser(cmd)
    args = p.parse_args()
    if args.command == 'prepare': prepare(args.base)
    elif args.command == 'bundle': bundle()
    elif args.command == 'start': start(args.hide)
    elif args.command == 'wait': wait_ready(args.seconds)
    elif args.command == 'console': console()
    elif args.command == 'ssh':
        os.execvp('ssh', ssh_args() + args.remote)
    elif args.command == 'status':
        print('UTM guest:', status(), flush=True)
        if alive():
            sys.exit(ssh('agent-os-status').returncode)
    elif args.command == 'stop': stop()
    elif args.command == 'reboot':
        sys.exit(ssh('sudo systemctl reboot').returncode)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
