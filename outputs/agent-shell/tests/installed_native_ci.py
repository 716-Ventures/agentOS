#!/usr/bin/python3
"""Install production core/broker units on an ephemeral ARM64 Actions runner.

This supplements, rather than qualifies, the pinned Debian VM. No provider or
voice fixtures are installed, no network/model calls are made by the journey.
"""
import importlib.util
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT.parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    if (os.geteuid() != 0 or os.environ.get('GITHUB_ACTIONS') != 'true'
            or platform.machine() != 'aarch64' or not Path('/run/systemd/system').is_dir()):
        raise SystemExit('Only run as root on an ephemeral ARM64 GitHub Actions systemd runner')
    if Path('/usr/local/lib/agent-os/current').exists():
        raise SystemExit('Refusing to replace an existing installation')
    installer = module('ci_installer', ROOT / 'install_runtime.py')
    licenses = module('ci_licenses', ROOT / 'collect_licenses.py')
    bundles = module('ci_bundles', ROOT / 'services/release_bundle.py')
    try:
        pwd.getpwnam('developer')
    except KeyError:
        run('useradd', '--create-home', '--shell', '/bin/bash', 'developer')
    account = pwd.getpwnam('developer')
    with tempfile.TemporaryDirectory(prefix='agentos-installed-ci-') as directory:
        root = Path(directory)
        source = root / 'source'
        shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(
            'target', '__pycache__', 'third-party-licenses', 'test-output'))
        (source / 'target/release').mkdir(parents=True)
        shutil.copy2(ROOT / 'target/release/agent-os-core', source / 'target/release/agent-os-core')
        for crate, binary in [('native-shell', 'agent-os-desktop'), ('native-compositor', 'agent-os-compositor')]:
            upstream = NATIVE / crate
            tree = source / crate
            tree.mkdir()
            for name in ('Cargo.toml', 'Cargo.lock', 'LICENSE-SMITHAY', 'THIRD_PARTY.md'):
                if (upstream / name).is_file():
                    shutil.copy2(upstream / name, tree / name)
            if (upstream / 'licenses').is_dir():
                shutil.copytree(upstream / 'licenses', tree / 'licenses')
            (tree / 'target/release').mkdir(parents=True)
            shutil.copy2(upstream / 'target/debug' / binary, tree / 'target/release' / binary)
        # Use the actual Ubuntu dependency manifest, never the Debian profile.
        profile = b'{"packages":["python3","openssl"]}\n'
        (source / 'dependencies.json').write_bytes(profile)
        contract = json.loads((source / 'release-contract.json').read_text())
        contract['units'] = ['agent-os-core', 'agent-os-broker']
        (source / 'release-contract.json').write_text(json.dumps(contract))
        licenses.collect([ROOT / 'Cargo.toml', NATIVE / 'native-shell/Cargo.toml',
                          NATIVE / 'native-compositor/Cargo.toml'], source / 'third-party-licenses')
        inst = installer.Installer()
        inst.state.mkdir(mode=0o700, parents=True)
        (inst.state / 'dependencies.json').write_text(json.dumps({
            'profile_sha256': bundles.sha(profile), 'packages': bundles.installed_packages()}))
        (inst.state / 'voice.json').write_text('{}\n')
        Path('/etc/agent-os').mkdir(exist_ok=True)
        Path('/etc/agent-os/release.json').write_text('{}\n')
        installed = False
        try:
            ident = inst.stage(source)
            inst.activate(ident)
            installed = True
            # Only the existing deliberately privileged broker CLI is allowed.
            sudoers = Path('/etc/sudoers.d/agentos-ci-review')
            sudoers.write_text('developer ALL=(root) NOPASSWD: /usr/local/bin/agent-os-broker\n')
            sudoers.chmod(0o440)
            run('visudo', '-cf', str(sudoers))
            journey = root / 'journey'
            (journey / 'tests').mkdir(parents=True)
            for name in ('installed_broker.py', 'accessibility.py'):
                shutil.copy2(NATIVE / 'native-shell/tests' / name, journey / 'tests' / name)
            for path in [root, journey, journey / 'tests', *list((journey / 'tests').iterdir())]:
                os.chown(path, account.pw_uid, account.pw_gid)
            root.chmod(0o755)
            try:
                run('runuser', '-u', 'developer', '--', 'dbus-run-session', '--',
                    'python3', str(journey / 'tests/installed_broker.py'), timeout=120)
            finally:
                output = NATIVE / 'native-shell/test-output/installed-services'
                if (journey / 'test-output').exists():
                    shutil.copytree(journey / 'test-output', output, dirs_exist_ok=True)
                    for path in output.rglob('*'):
                        path.chmod(0o755 if path.is_dir() else 0o644)
        finally:
            Path('/etc/sudoers.d/agentos-ci-review').unlink(missing_ok=True)
            # Stop even if activation failed partway through.
            subprocess.run(['systemctl', 'stop', 'agent-os-broker', 'agent-os-core'], check=False)
            if installed:
                print('Stopped installed CI services')


if __name__ == '__main__':
    main()
