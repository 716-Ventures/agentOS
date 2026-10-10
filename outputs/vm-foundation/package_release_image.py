#!/usr/bin/env python3
"""Create or verify a signed UTM release bundle without development seed/state."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import secrets
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parent
OPENSSL = '/opt/homebrew/opt/openssl@3/bin/openssl' if Path('/opt/homebrew/opt/openssl@3/bin/openssl').exists() else '/usr/bin/openssl'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): value.update(chunk)
    return value.hexdigest()


def crypto(*arguments):
    return subprocess.check_output([OPENSSL, *map(str, arguments)], stderr=subprocess.PIPE, timeout=15)


def ed25519(key, public=False):
    value = crypto('pkey', *(['-pubin'] if public else []), '-in', key, '-pubout', '-outform', 'DER')
    if len(value) != 44 or not value.startswith(bytes.fromhex('302a300506032b6570032100')):
        raise ValueError('Use an Ed25519 signing/verification key')


def configuration():
    value = plistlib.loads((ROOT / 'utm-template.plist').read_bytes())
    value['Information']['UUID'] = str(uuid.uuid4()).upper()
    value['Information']['Name'] = 'agentOS experimental release'
    value['Drive'] = [drive for drive in value['Drive'] if drive['ImageName'] == 'disk.qcow2']
    if len(value['Drive']) != 1: raise ValueError('Expected one release disk')
    value['Drive'][0]['Identifier'] = str(uuid.uuid4()).upper()
    value['Network'][0]['MacAddress'] = '02:' + ':'.join(f'{byte:02X}' for byte in secrets.token_bytes(5))
    value['Network'][0]['PortForward'] = []
    if value['Sharing']['DirectoryShareMode'] != 'None' or value['Sharing']['ClipboardSharing']:
        raise ValueError('Release bundles must not inherit host directory or clipboard sharing')
    return plistlib.dumps(value, sort_keys=False)


def verify(bundle, trusted_key):
    ed25519(trusted_key, public=True)
    for name in ('release.json', 'release.sig', 'config.plist', 'Data/disk.qcow2'):
        path = bundle / name
        if path.is_symlink() or not path.is_file(): raise ValueError('Missing regular bundle file: ' + name)
    if (bundle / 'release.json').stat().st_size > 16384 or (bundle / 'release.sig').stat().st_size != 64:
        raise ValueError('Invalid signed image metadata size')
    crypto('pkeyutl', '-verify', '-rawin', '-pubin', '-inkey', trusted_key, '-in', bundle / 'release.json', '-sigfile', bundle / 'release.sig')
    info = json.loads((bundle / 'release.json').read_text())
    if info.get('format') != 'agentos.vm-release/1' or info.get('architecture') != 'arm64':
        raise ValueError('Unsupported image release')
    if digest(bundle / 'config.plist') != info['configuration_sha256'] or digest(bundle / 'Data/disk.qcow2') != info['image']['image_sha256']:
        raise ValueError('Signed VM configuration or image changed')
    return info


def package(image, metadata, key, output):
    ed25519(key)
    info = json.loads(metadata.read_text())
    if info.get('format') != 1 or info.get('architecture') != 'arm64' or digest(image) != info.get('image_sha256'):
        raise ValueError('Image does not match the builder metadata')
    public = crypto('pkey', '-in', key, '-pubout')
    if hashlib.sha256(public).hexdigest() != info.get('update_key_sha256'):
        raise ValueError('Image update trust does not match this signing key')
    if image.is_symlink() or not image.is_file(): raise ValueError('Use the newly built regular image file')
    output.mkdir(mode=0o755)
    (output / 'INCOMPLETE').write_text('Do not import this bundle until packaging completes.\n')
    data = output / 'Data'; data.mkdir()
    shutil.copyfile(image, data / 'disk.qcow2')
    config = configuration(); (output / 'config.plist').write_bytes(config)
    envelope = {'format': 'agentos.vm-release/1', 'architecture': 'arm64',
                'configuration_sha256': hashlib.sha256(config).hexdigest(), 'packager_sha256': digest(Path(__file__)), 'image': info}
    (output / 'release.json').write_text(json.dumps(envelope, sort_keys=True, separators=(',', ':')) + '\n')
    (output / 'update-signing-key.pem').write_bytes(public)
    crypto('pkeyutl', '-sign', '-rawin', '-inkey', key, '-in', output / 'release.json', '-out', output / 'release.sig')
    verify(output, output / 'update-signing-key.pem')
    (output / 'README.txt').write_text(
        'agentOS experimental ARM64 image\n\n'
        'Verify release.sig and the disk/configuration hashes with a separately trusted public key before import.\n'
        'The included key identifies this development build; its inclusion alone does not establish trust.\n'
        'Import this .utm bundle into UTM. First-run setup on the local console creates your account.\n'
        'No account password, provider key, SSH authorized key, host directory, or development seed is included.\n'
        'SSH is disabled. The ordinary local shell and sudo remain available after account setup.\n'
        'Run agent-os for terminal access, or agent-os-session from a local graphical login.\n'
        'Runtime updates require bundles signed by the provisioned Ed25519 update key.\n'
        'This development image is not qualification of physical input/audio, hardware, or daily usability.\n')
    (output / 'INCOMPLETE').unlink()
    print('Signed UTM bundle:', output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    create = sub.add_parser('create')
    for name in ('image', 'metadata', 'signing-key', 'output'): create.add_argument('--' + name, type=Path, required=True)
    check = sub.add_parser('verify'); check.add_argument('bundle', type=Path)
    check.add_argument('--trusted-key', type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'create': package(args.image, args.metadata, args.signing_key, args.output)
    else:
        verify(args.bundle, args.trusted_key)
        print('Verified signed image and VM configuration:', args.bundle)


if __name__ == '__main__': main()
