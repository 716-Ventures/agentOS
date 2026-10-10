#!/usr/bin/python3
"""Build a new offline ARM64 disk from the pinned base in a dedicated Linux VM.

The running VM supplies only verified immutable runtime files and offline voice
assets. Its disk, users, credentials, journals and activity state are never copied.
The resulting image has no personal account; local first-run setup creates one.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def command(*argv, **kwargs):
    return subprocess.run([str(value) for value in argv], check=True, **kwargs)


def sha(path, algorithm='sha256'):
    result = hashlib.new(algorithm)
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): result.update(chunk)
    return result.hexdigest()


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise ValueError('A regular input file is required: ' + str(path))


def publish_image(source, output):
    """Publish the completed inode exclusively, without another disk-sized copy."""
    regular(source)
    source.chmod(0o644)
    with source.open('rb') as stream:
        os.fsync(stream.fileno())
    # The private build directory is on the output filesystem. Hard linking is
    # atomic and refuses existing files/symlinks, unlike a replacing rename.
    os.link(source, output)
    directory = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def payload(release):
    release = release.resolve(strict=True)
    regular(release / 'manifest.json')
    hashes = json.loads((release / 'manifest.json').read_text())
    if not isinstance(hashes, dict) or not 1 <= len(hashes) <= 10000:
        raise ValueError('Invalid immutable runtime manifest')
    for name, digest in hashes.items():
        if (not isinstance(name, str) or not name or len(name) > 1024 or '\\' in name
                or any(ord(char) < 32 for char in name) or Path(name).is_absolute()
                or any(part in ('', '.', '..') for part in name.split('/'))
                or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest)):
            raise ValueError('Invalid immutable runtime entry')
        source = release / name
        regular(source)
        if not source.resolve().is_relative_to(release) or sha(source) != digest:
            raise ValueError('Immutable runtime changed: ' + name)
    ident = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    if release.name != ident: raise ValueError('Immutable runtime identity mismatch')
    contract = json.loads((release / 'release-contract.json').read_text())
    if not contract.get('desktop'): raise ValueError('Build the complete native runtime first')
    return ident, hashes


def write(root, name, data, mode=0o644):
    path = root / name.lstrip('/')
    if path.is_symlink(): raise ValueError('Unexpected image symlink: ' + name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    path.chmod(mode)


def copy_payload(root, release, ident, hashes):
    target = root / 'usr/local/lib/agent-os/releases' / ident
    target.mkdir(parents=True)
    for name in ['manifest.json', *sorted(hashes)]:
        source = release / name
        dest = target / name; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        executable = (name in ('agent-os-core', 'native/agent-os-desktop', 'native/agent-os-compositor', 'client/agent_os.py')
                      or name.endswith('-launcher.sh'))
        dest.chmod(0o755 if executable else 0o644)
        if name in hashes and sha(dest) != hashes[name]: raise ValueError('Runtime changed during copy')
    descriptor = json.loads((release / 'voice-assets.json').read_text())
    assets = Path(descriptor['root'])
    if (not assets.is_absolute() or assets.parent != Path('/usr/local/lib/agent-os/voice')
            or not re.fullmatch('[a-f0-9]{64}', assets.name) or assets.is_symlink()):
        raise ValueError('Invalid offline speech asset location')
    regular(assets / 'manifest.json')
    if sha(assets / 'manifest.json') != descriptor['manifest_sha256']:
        raise ValueError('Offline speech manifest changed')
    recorded = json.loads((assets / 'manifest.json').read_text())
    if recorded['files'] != descriptor['files']: raise ValueError('Offline speech files changed')
    voice = root / str(assets).lstrip('/'); voice.mkdir(parents=True)
    for name, expected in {**descriptor['files'], 'manifest.json': descriptor['manifest_sha256']}.items():
        if not isinstance(name, str) or '/' in name or name in ('', '.', '..') or '\\' in name:
            raise ValueError('Invalid speech payload name')
        source = assets / name; regular(source)
        if sha(source) != expected: raise ValueError('Offline speech asset changed: ' + name)
        shutil.copyfile(source, voice / name)
        (voice / name).chmod(0o755 if name == 'whisper-cli' else 0o644)
        if sha(voice / name) != expected: raise ValueError('Speech asset changed during copy')
    write(root, '/var/lib/agent-os-install/voice.json', json.dumps(descriptor, sort_keys=True) + '\n', 0o600)
    (root / 'var/lib/agent-os-install').chmod(0o700)


def customize(root, release, ident, hashes, bootstrap, lock, update_key):
    # Prevent package maintainer scripts from starting services in the builder.
    write(root, '/usr/sbin/policy-rc.d', '#!/bin/sh\nexit 101\n', 0o755)
    write(root, '/tmp/agentos-bootstrap/bootstrap.py', bootstrap.read_bytes())
    write(root, '/tmp/agentos-bootstrap/dependencies.json', (release / 'dependencies.json').read_bytes())
    # Minimal device nodes avoid exposing the builder VM's disks inside chroot.
    resolver = root / 'etc/resolv.conf'
    resolver_link = os.readlink(resolver) if resolver.is_symlink() else None
    resolver_bytes = resolver.read_bytes() if resolver.exists() and not resolver.is_symlink() else None
    resolver.unlink(missing_ok=True)
    resolver.write_bytes(Path('/etc/resolv.conf').read_bytes())
    mounts = ExitStack()
    try:
        dev = root / 'dev'; dev.mkdir(exist_ok=True)
        command('mount', '-t', 'tmpfs', '-o', 'mode=755,nosuid', 'tmpfs', dev)
        mounts.callback(command, 'umount', dev)
        for name, major, minor in [('null', 1, 3), ('zero', 1, 5), ('random', 1, 8), ('urandom', 1, 9)]:
            node = root / 'dev' / name
            if node.exists() or node.is_symlink(): node.unlink()
            os.mknod(node, stat.S_IFCHR | 0o666, os.makedev(major, minor))
            node.chmod(0o666)
        proc = root / 'proc'; proc.mkdir(exist_ok=True)
        command('mount', '-t', 'proc', 'proc', proc)
        mounts.callback(command, 'umount', proc)
        command('chroot', root, '/usr/bin/python3', '/tmp/agentos-bootstrap/bootstrap.py')
        expected = json.loads((release / 'dependencies.installed.json').read_text())['packages']
        actual = json.loads((root / 'var/lib/agent-os-install/dependencies.json').read_text())['packages']
        packages = json.loads((release / 'dependencies.json').read_text())['packages']
        for package in packages:
            entries = {name: version for name, version in expected.items() if name.split(':')[0] == package}
            if not entries or any(actual.get(name) != version for name, version in entries.items()):
                raise ValueError('Image dependency differs from the runtime build: ' + package)
        copy_payload(root, release, ident, hashes)
        write(root, '/usr/local/lib/agent-os-image/first-run.py', (ROOT / 'guest/first-run.py').read_bytes())
        write(root, '/etc/systemd/system/agent-os-first-run.service', (ROOT / 'guest/agent-os-first-run.service').read_bytes())
        write(root, '/usr/local/bin/agent-os-status', (ROOT / 'guest/status.py').read_bytes(), 0o755)
        write(root, '/usr/local/lib/agent-os/record-boot.py', (ROOT / 'guest/record-boot.py').read_bytes(), 0o755)
        write(root, '/etc/systemd/system/agent-os-foundation.service', (ROOT / 'guest/agent-os-foundation.service').read_bytes())
        write(root, '/etc/agent-os/update-signing-key.pem', update_key.read_bytes())
        write(root, '/etc/cloud/cloud-init.disabled', '')
        # Cloud-init is disabled in the distributed image, so networking must
        # not depend on a development seed. Local setup also works offline.
        write(root, '/etc/systemd/network/20-agentos.network',
              '[Match]\nName=en* eth*\n\n[Link]\nRequiredForOnline=no\n\n[Network]\nDHCP=yes\n')
        write(root, '/etc/hostname', 'agentos\n')
        write(root, '/etc/hosts', '127.0.0.1 localhost\n127.0.1.1 agentos\n::1 localhost ip6-localhost ip6-loopback\n')
        write(root, '/etc/ssh/sshd_config.d/10-agentos.conf', 'PermitRootLogin no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n')
        for service in ('getty@tty1.service', 'serial-getty@ttyAMA0.service'):
            write(root, '/etc/systemd/system/' + service + '.d/10-first-run.conf', '[Unit]\nConditionPathExists=/var/lib/agent-os-image/ready\n')
        write(root, '/etc/systemd/system/getty@tty2.service.d/10-first-run.conf', '[Unit]\nConditionPathExists=/var/lib/agent-os-image/account-ready\n')
        command('systemctl', '--root', root, 'enable', 'agent-os-first-run.service', 'agent-os-foundation.service', 'getty@tty2.service')
        command('systemctl', '--root', root, 'disable', 'ssh.service', 'ssh.socket')
        command('chroot', root, 'passwd', '--lock', 'root')
        # The pinned upstream base has no provisioned personal login. Refuse a
        # replacement base containing one rather than trying to sanitize it.
        users = (root / 'etc/passwd').read_text().splitlines()
        if any(1000 <= int(row.split(':')[2]) < 65534 for row in users):
            raise ValueError('The base contains a personal login; it cannot become a release image')
        for path in (root / 'etc/ssh').glob('ssh_host_*'): path.unlink()
        for folder in ('root/.ssh', 'var/lib/cloud', 'var/log/journal', 'tmp/agentos-bootstrap'):
            shutil.rmtree(root / folder, ignore_errors=True)
        for path in (root / 'var/log').rglob('*'):
            if path.is_file() and not path.is_symlink(): path.write_bytes(b'')
        machine = root / 'var/lib/dbus/machine-id'
        machine.unlink(missing_ok=True)
        write(root, '/etc/machine-id', '')
        for name in ('var/lib/systemd/random-seed', 'var/lib/systemd/credential.secret',
                     'etc/ssl/private/ssl-cert-snakeoil.key', 'etc/ssl/certs/ssl-cert-snakeoil.pem'):
            (root / name).unlink(missing_ok=True)
        (root / 'usr/sbin/policy-rc.d').unlink()
        info = {'format': 1, 'name': 'agentOS experimental native image', 'architecture': 'arm64',
                'base_sha512': lock['sha512'], 'runtime_release': ident,
                'dependency_profile_sha256': sha(release / 'dependencies.json'),
                'builder_sha256': sha(Path(__file__)), 'bootstrap_sha256': sha(bootstrap),
                'first_run_sha256': sha(ROOT / 'guest/first-run.py'),
                'first_run_unit_sha256': sha(ROOT / 'guest/agent-os-first-run.service'),
                'dependency_manifest_sha256': sha(root / 'var/lib/agent-os-install/dependencies.json'),
                'voice_descriptor_sha256': sha(release / 'voice-assets.json'),
                'foundation_sources': {name: sha(ROOT / 'guest' / name)
                                       for name in ('status.py', 'record-boot.py', 'agent-os-foundation.service')},
                'disk_size': '20G',
                'update_key_sha256': sha(update_key),
                'contains_personal_account': False, 'contains_provider_credentials': False}
        write(root, '/etc/agent-os/image.json', json.dumps(info, sort_keys=True, indent=2) + '\n')
        write(root, '/etc/agent-os/release.json', json.dumps({'name': 'agentOS', 'version': 'experimental', 'milestone': 'First-run setup'}) + '\n')
        write(root, '/etc/motd', 'agentOS experimental native image. Finish local first-run setup.\n')
        # Free blocks contain only the upstream base and builder package caches;
        # trim them before converting the newly constructed disk for distribution.
        command('chroot', root, 'apt-get', 'clean')
        command('fstrim', root)
        return info
    finally:
        resolver.unlink(missing_ok=True)
        if resolver_link is not None:resolver.symlink_to(resolver_link)
        elif resolver_bytes is not None:resolver.write_bytes(resolver_bytes)
        mounts.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New qcow2 file; existing paths are refused')
    parser.add_argument('--release', type=Path, default=Path('/usr/local/lib/agent-os/current'))
    parser.add_argument('--bootstrap', type=Path, required=True)
    parser.add_argument('--update-key', type=Path, required=True, help='Ed25519 public PEM key; never a signing private key')
    parser.add_argument('--compress', action='store_true', help='Use zlib compression for a smaller, slower-to-build qcow2 export')
    parser.add_argument('--dedicated-builder', action='store_true', help='Confirm this is the dedicated Linux image-building VM')
    args = parser.parse_args()
    if not args.dedicated_builder or os.geteuid() != 0 or platform.machine() not in ('aarch64', 'arm64'):
        parser.error('Run as root in the dedicated ARM64 Linux builder with --dedicated-builder')
    required = ('qemu-img', 'losetup', 'growpart', 'e2fsck', 'resize2fs', 'mount', 'umount',
                'lsblk', 'openssl', 'udevadm', 'systemctl', 'chroot', 'fstrim')
    missing = [name for name in required if shutil.which(name) is None]
    if missing:raise ValueError('Missing dedicated-builder tools: ' + ', '.join(missing))
    regular(args.base); regular(args.bootstrap); regular(args.update_key)
    public = command('openssl', 'pkey', '-pubin', '-in', args.update_key, '-pubout', '-outform', 'DER', capture_output=True).stdout
    if len(public) != 44 or not public.startswith(bytes.fromhex('302a300506032b6570032100')):
        raise ValueError('Use an Ed25519 public verification key')
    lock = json.loads((ROOT / 'image-lock.json').read_text())
    if sha(args.base, 'sha512') != lock['sha512']: raise ValueError('Pinned upstream base checksum mismatch')
    release = args.release.resolve(strict=True); ident, hashes = payload(release)
    output = args.output.absolute()
    if output.exists() or output.is_symlink() or output.with_suffix('.json').exists() or output.with_suffix('.json').is_symlink():
        raise ValueError('Choose new output and metadata paths')
    output.parent.mkdir(parents=True, exist_ok=True)
    loop = None; mounted = False
    with tempfile.TemporaryDirectory(prefix='agentos-image-', dir=output.parent) as directory:
        work = Path(directory); raw = work / 'disk.raw'; root = work / 'root'; root.mkdir()
        command('qemu-img', 'convert', '-f', 'qcow2', '-O', 'raw', args.base, raw)
        command('qemu-img', 'resize', '-f', 'raw', raw, '20G')
        loop = command('losetup', '--find', '--show', '--partscan', raw, capture_output=True, text=True).stdout.strip()
        try:
            command('udevadm', 'settle', '--timeout=10')
            devices = json.loads(command('lsblk', '--json', '--tree', '--output', 'PATH,FSTYPE', loop, capture_output=True, text=True).stdout)
            children = devices['blockdevices'][0].get('children', [])
            roots = [node['path'] for node in children if node.get('fstype') == 'ext4']
            if len(roots) != 1: raise ValueError('Expected one ext4 root partition in the pinned base')
            partition = roots[0]; number = re.fullmatch(re.escape(loop) + r'p([0-9]+)', partition)
            if number is None: raise ValueError('Unexpected loop partition')
            command('growpart', loop, number[1])
            command('udevadm', 'settle', '--timeout=10')
            check = subprocess.run(['e2fsck', '-f', '-p', partition])
            if check.returncode not in (0, 1): raise ValueError('Base filesystem repair failed')
            command('resize2fs', partition)
            command('mount', '-o', 'nodev,nosuid', partition, root); mounted = True
            info = customize(root, release, ident, hashes, args.bootstrap, lock, args.update_key)
            command('sync', '-f', root)
            command('umount', root); mounted = False
        finally:
            if mounted: command('umount', root)
            command('losetup', '--detach', loop)
        completed = work / 'completed.qcow2'
        command('qemu-img', 'convert', '-f', 'raw', '-O', 'qcow2', *(['-c'] if args.compress else []), raw, completed)
        info['compression'] = 'zlib' if args.compress else 'none'
        command('qemu-img', 'check', completed)
        info['image_sha256'] = sha(completed)
        publish_image(completed, output)
        with output.with_suffix('.json').open('x') as stream:
            json.dump(info, stream, sort_keys=True, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        print('Built new release image:', output)
        print('SHA-256:', info['image_sha256'])


if __name__ == '__main__': main()
