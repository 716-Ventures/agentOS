#!/usr/bin/python3
"""Create the first ordinary login and activate a preverified image runtime.

Runs only on the image's local console. Passwords are passed to chpasswd on stdin
and are never journaled. A root-owned journal makes account creation resumable.
"""
import fcntl
import getpass
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import tempfile
import uuid

STATE = Path('/var/lib/agent-os-image')
CONFIG = Path('/etc/agent-os/image.json')


def username(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,30}', value):
        raise ValueError('Use 1–31 lowercase letters, digits, underscores or hyphens; start with a letter')
    if value in ('root', 'debian', 'nobody', 'agent-os', 'agentos'):
        raise ValueError('Choose a personal login name')
    return value


def atomic(path, value):
    fd, name = tempfile.mkstemp(prefix='.setup-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        Path(name).unlink(missing_ok=True)


def load(path):
    info = path.lstat()
    if (not path.is_file() or path.is_symlink() or info.st_uid != 0
            or info.st_mode & 0o022 or info.st_size > 16384):
        raise ValueError('First-run metadata must be a bounded root-owned regular file')
    return json.loads(path.read_text())


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def account(name):
    try: return pwd.getpwnam(name)
    except KeyError: return None


def setup(config):
    journal = STATE / 'setup.json'
    if journal.exists():
        pending = load(journal)
        if pending.get('format') != 1 or pending.get('phase') not in ('chosen', 'account-ready'):
            raise ValueError('Invalid first-run journal phase')
        if 'uid' in pending and (type(pending['uid']) is not int or pending['uid'] < 1000):
            raise ValueError('Invalid first-run login identity')
        name = username(pending['name'])
        if not re.fullmatch('[a-f0-9]{32}', pending.get('token', '')):
            raise ValueError('Invalid first-run journal')
        print('Resuming setup for ' + name, flush=True)
    else:
        while True:
            try:
                name = username(input('Choose your login name: ').strip())
                if account(name) is not None: raise ValueError('That account already exists')
                break
            except ValueError as exc: print(str(exc), flush=True)
        pending = {'format': 1, 'name': name, 'token': uuid.uuid4().hex, 'phase': 'chosen'}
        atomic(journal, pending)
    marker = 'agentOS first-run ' + pending['token']
    login = account(name)
    if login is None:
        if pending['phase'] != 'chosen':
            raise ValueError('The selected account disappeared; recover from the ordinary rescue shell')
        run('useradd', '--create-home', '--shell', '/bin/bash', '--groups', 'sudo', '--comment', marker, name)
        login = pwd.getpwnam(name)
    # Never adopt an unrelated account after an interrupted account creation.
    if login.pw_uid < 1000 or login.pw_gecos != marker or pending.get('uid', login.pw_uid) != login.pw_uid:
        raise ValueError('The pending login identity changed; automatic setup stopped')
    pending.update(uid=login.pw_uid)
    atomic(journal, pending)
    if pending['phase'] == 'chosen':
        while True:
            password = getpass.getpass('Choose a password (at least 12 characters): ')
            if not 12 <= len(password) <= 1024 or any(c in password for c in '\0\r\n'):
                print('Use 12–1024 characters without line breaks', flush=True); continue
            if getpass.getpass('Confirm password: ') != password:
                print('Passwords did not match', flush=True); continue
            run('chpasswd', input=name + ':' + password + '\n', text=True)
            del password
            break
        pending['phase'] = 'account-ready'; atomic(journal, pending)
    atomic(STATE / 'account-ready', {'name': name, 'uid': login.pw_uid})
    # TTY 2 remains a model-free rescue login if activation needs repair.
    run('systemctl', 'start', 'getty@tty2.service')
    release = Path('/usr/local/lib/agent-os/releases') / config['runtime_release']
    print('Activating the installed agentOS runtime…', flush=True)
    run('/usr/bin/python3', str(release / 'install_runtime.py'), '--activate', config['runtime_release'], '--login-user', name)
    atomic(STATE / 'ready', {'format': 1, 'name': name, 'uid': login.pw_uid, 'runtime_release': config['runtime_release']})
    print('\nSetup complete. Log in as ' + name + '.\n'
          'Run agent-os for the terminal, or agent-os-session from the local graphical console.\n'
          'Provider setup: sudo agent-os-configure. Audio setup: agent-os setup.\n'
          'The ordinary shell, sudo and TTY 2 remain available for recovery.\n', flush=True)
    run('systemctl', '--no-block', 'start', 'getty@tty1.service', 'serial-getty@ttyAMA0.service')


def main():
    if os.geteuid() != 0 or not sys.stdin.isatty():
        raise SystemExit('First-run setup requires the local root-owned console service')
    config = load(CONFIG)
    if (config.get('format') != 1 or not isinstance(config.get('runtime_release'), str)
            or not re.fullmatch('[a-f0-9]{64}', config['runtime_release'])):
        raise ValueError('Invalid image runtime identity')
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if STATE.is_symlink() or STATE.stat().st_uid != 0 or STATE.stat().st_mode & 0o077:
        raise ValueError('First-run state must be private and root-owned')
    with (STATE / 'lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (STATE / 'ready').exists(): return
        # Generate per-machine host identity without enabling remote login.
        run('ssh-keygen', '-A')
        print('\nWelcome to agentOS. Create your own account to finish setup.\n', flush=True)
        setup(config)


if __name__ == '__main__':
    main()
