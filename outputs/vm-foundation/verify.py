#!/usr/bin/env python3
"""Integration test of the actual guest. Reboots and cold-starts this VM."""
import datetime
import json
from pathlib import Path
import secrets
import time
import vm


def remote(command):
    result = vm.ssh(command, capture_output=True, text=True, timeout=25)
    if result.returncode:
        raise RuntimeError(f'Guest check failed: {command}\n{result.stderr}\n{result.stdout}')
    return result.stdout.strip()


def state():
    return json.loads(remote('agent-os-status'))


def wait_new_boot(previous):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            current = state()
            if current['boot_id'] != previous and current['foundation_service'] == 'active':
                return current
        except (RuntimeError, TimeoutError):
            pass
        time.sleep(2)
    raise RuntimeError('Reboot did not produce a new ready guest boot within 60 seconds.')


def main():
    vm.wait_ready(45)
    before = state()
    assert before['pid1'] == 'systemd', before
    assert before['architecture'] == 'aarch64', before
    assert before['root_mount'].startswith('/dev/vda1 ext4 '), before
    assert remote('cloud-init status --wait') == 'status: done'
    assert remote('systemctl is-system-running') == 'running'
    assert remote('id -un') == 'developer'
    remote('getent hosts deb.debian.org')
    assert remote('curl -sS -o /dev/null -w "%{http_code}" --fail --max-time 15 https://deb.debian.org/debian/') == '200'
    remote('sudo systemctl restart agent-os-foundation.service')
    assert state()['recorded_boots'] == before['recorded_boots'], 'Service restart duplicated a boot'
    token = secrets.token_hex(24)
    remote(f"printf '%s\\n' '{token}' > /home/developer/m0-persistence-probe")
    print('PASS: login, kernel/init, root disk, cloud-init, system health, DNS, HTTPS, service restart', flush=True)
    vm.ssh('sudo systemctl reboot', capture_output=True, timeout=15)
    rebooted = wait_new_boot(before['boot_id'])
    assert remote('cat /home/developer/m0-persistence-probe') == token
    assert rebooted['recorded_boots'] == before['recorded_boots'] + 1
    print('PASS: guest reboot, changed boot ID, persistent user data and boot history', flush=True)
    vm.qmp('system_powerdown')
    deadline = time.monotonic() + 30
    while vm.alive() and time.monotonic() < deadline:
        time.sleep(1)
    assert not vm.alive(), 'Guest failed to shut down'
    vm.start('hvf')
    cold = wait_new_boot(rebooted['boot_id'])
    assert remote('cat /home/developer/m0-persistence-probe') == token
    assert cold['recorded_boots'] == before['recorded_boots'] + 2
    assert remote('systemctl is-system-running') == 'running'
    print('PASS: full shutdown and hardware-accelerated cold start with persistent data', flush=True)
    report = {
        'tested_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'result': 'pass', 'before': before, 'after_reboot': rebooted, 'after_cold_start': cold,
        'checks': ['SSH login', 'ARM64 Linux kernel', 'systemd PID 1', 'persistent ext4 root',
                   'cloud-init complete', 'system running', 'DNS', 'outbound HTTPS',
                   'foundation service restart', 'guest reboot', 'cold start', 'data persistence'],
        'not_tested': ['agent runtime', 'Jev', 'voice/audio', 'installer', 'OS updates/rollback',
                       'physical hardware', 'graphical desktop'],
    }
    path = vm.ROOT / 'verification.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print('Evidence:', path)


if __name__ == '__main__':
    main()
