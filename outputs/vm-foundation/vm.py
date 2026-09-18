#!/usr/bin/env python3
"""Build and operate the complete ARM64 Agent OS development guest on macOS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import select
import shutil
import socket
import subprocess
import sys
import time
import termios
import tty

ROOT = Path(__file__).resolve().parent
RUN = ROOT / 'runtime'
LOCK = json.loads((ROOT / 'image-lock.json').read_text())
QMP = Path('/tmp') / ('agent-os-' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:12] + '.sock')
SERIAL = QMP.with_suffix('.serial')


def call(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def digest(path):
    h = hashlib.sha512()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def qmp(command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect(str(QMP))
        with s.makefile('rwb', buffering=0) as stream:
            json.loads(stream.readline())
            for cmd in ['qmp_capabilities', command]:
                stream.write(json.dumps({'execute': cmd}).encode() + b'\n')
                while True:
                    message = json.loads(stream.readline())
                    if 'error' in message:
                        raise RuntimeError(message['error'])
                    if 'return' in message:
                        break
            return message['return']


def alive():
    if not QMP.exists():
        return False
    try:
        qmp('query-status')
        return True
    except (OSError, ValueError):
        return False


def prepare(source=None):
    if alive():
        raise RuntimeError('Stop the VM before preparing its image.')
    if (RUN / 'disk.qcow2').exists():
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
    prefix = Path(call(['brew', '--prefix'], text=True, capture_output=True).stdout.strip())
    shutil.copyfile(prefix / 'share/qemu/edk2-aarch64-code.fd', RUN / 'uefi-code.fd')
    shutil.copyfile(prefix / 'share/qemu/edk2-arm-vars.fd', RUN / 'uefi-vars.fd')
    (RUN / 'build.json').write_text(json.dumps(build, indent=2) + '\n')
    (RUN / 'prepared').touch()
    print('Prepared standalone disk and first-boot configuration. Credentials:', credentials)


def start(accel):
    if alive():
        raise RuntimeError('VM is already running.')
    if not (RUN / 'prepared').exists():
        raise RuntimeError('Run prepare first.')
    if QMP.exists():
        QMP.unlink()
    if SERIAL.exists():
        SERIAL.unlink()
    pidfile = RUN / 'qemu.pid'
    if pidfile.exists():
        pidfile.unlink()
    args = ['qemu-system-aarch64', '-name', 'agent-os-dev', '-machine', 'virt',
            '-accel', accel, '-cpu', 'host' if accel == 'hvf' else 'cortex-a72',
            '-smp', str(LOCK['cpus']), '-m', str(LOCK['memory_mib']),
            '-drive', f'if=pflash,format=raw,readonly=on,file={RUN}/uefi-code.fd',
            '-drive', f'if=pflash,format=raw,file={RUN}/uefi-vars.fd',
            '-drive', f'if=none,id=os,format=qcow2,file={RUN}/disk.qcow2',
            '-device', 'virtio-blk-pci,drive=os',
            '-drive', f'if=none,id=seed,format=raw,readonly=on,file={RUN}/seed.iso',
            '-device', 'virtio-blk-pci,drive=seed',
            '-netdev', f'user,id=net,hostfwd=tcp:127.0.0.1:{LOCK["ssh_port"]}-:22',
            '-device', 'virtio-net-pci,netdev=net', '-device', 'virtio-rng-pci',
            '-display', 'none',
            '-chardev', f'socket,id=console,path={SERIAL},server=on,wait=off,logfile={RUN}/console.log,logappend=on',
            '-serial', 'chardev:console',
            '-monitor', 'none', '-qmp', f'unix:{QMP},server=on,wait=off',
            '-pidfile', str(pidfile), '-daemonize']
    call(args)
    print(f'VM started ({accel}); SSH is forwarded on localhost:{LOCK["ssh_port"]}.')
    print('Boot log:', RUN / 'console.log')


def console():
    if not sys.stdin.isatty():
        raise RuntimeError('Open console in an interactive terminal.')
    print('Guest serial console. Press Ctrl-] to detach without stopping the VM.')
    print('Local credentials:', RUN / 'console-credentials.txt')
    original = termios.tcgetattr(sys.stdin)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(SERIAL))
        try:
            tty.setraw(sys.stdin.fileno())
            s.sendall(b'\r')
            while True:
                ready, _, _ = select.select([s, sys.stdin], [], [])
                if s in ready:
                    data = s.recv(16384)
                    if not data:
                        break
                    os.write(sys.stdout.fileno(), data)
                if sys.stdin in ready:
                    data = os.read(sys.stdin.fileno(), 1024)
                    if b'\x1d' in data or not data:
                        break
                    s.sendall(data)
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, original)
            print()


def ssh_args():
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
    raise RuntimeError('Guest readiness deadline exceeded; inspect runtime/console.log.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    b = commands.add_parser('prepare'); b.add_argument('--base')
    s = commands.add_parser('start'); s.add_argument('--accel', choices=['hvf', 'tcg'], default='hvf')
    w = commands.add_parser('wait'); w.add_argument('--seconds', type=int, default=60)
    c = commands.add_parser('ssh'); c.add_argument('remote', nargs=argparse.REMAINDER)
    for cmd in ['status', 'stop', 'reboot', 'console']:
        commands.add_parser(cmd)
    args = p.parse_args()
    if args.command == 'prepare': prepare(args.base)
    elif args.command == 'start': start(args.accel)
    elif args.command == 'wait': wait_ready(args.seconds)
    elif args.command == 'console': console()
    elif args.command == 'ssh':
        os.execvp('ssh', ssh_args() + args.remote)
    elif args.command == 'status':
        print(json.dumps(qmp('query-status'), indent=2) if alive() else 'VM stopped')
        if alive():
            sys.exit(ssh('agent-os-status').returncode)
    elif args.command == 'stop':
        if alive():
            qmp('system_powerdown')
            print('Requested orderly guest shutdown. Check status before restarting.')
        else: print('VM already stopped.')
    elif args.command == 'reboot':
        sys.exit(ssh('sudo systemctl reboot').returncode)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
