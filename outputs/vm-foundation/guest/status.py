#!/usr/bin/python3
import json
from pathlib import Path
import platform
import subprocess

def output(*args):
    return subprocess.run(args, text=True, capture_output=True).stdout.strip()

history = Path('/var/lib/agent-os/boots.jsonl')
result = {
    'release': json.loads(Path('/etc/agent-os/release.json').read_text()),
    'kernel': platform.release(),
    'architecture': platform.machine(),
    'pid1': Path('/proc/1/comm').read_text().strip(),
    'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    'recorded_boots': len(history.read_text().splitlines()) if history.exists() else 0,
    'foundation_service': output('systemctl', 'is-active', 'agent-os-foundation.service'),
    'root_mount': output('findmnt', '-n', '-o', 'SOURCE,FSTYPE,OPTIONS', '/'),
    'network': json.loads(output('ip', '-j', 'address')),
}
print(json.dumps(result, indent=2))
