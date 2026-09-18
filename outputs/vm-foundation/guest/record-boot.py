#!/usr/bin/python3
"""Record actual guest boots; this is a foundation check, not an agent."""
import datetime
import json
import os
from pathlib import Path
import platform

state = Path('/var/lib/agent-os')
record = {
    'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'kernel': platform.release(),
    'architecture': platform.machine(),
}
history = state / 'boots.jsonl'
previous = [json.loads(line) for line in history.read_text().splitlines()] if history.exists() else []
if not any(item['boot_id'] == record['boot_id'] for item in previous):
    with history.open('a') as f:
        f.write(json.dumps(record) + '\n')
        f.flush()
        os.fsync(f.fileno())
print(json.dumps(record))
