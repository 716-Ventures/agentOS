#!/usr/bin/python3
"""Enter API keys locally; nothing is echoed or placed in shell history."""
import getpass
import grp
import json
import os
from pathlib import Path
import sys
from providers import CONFIG, DEFAULT_MODEL, ProviderError, free_models


def main():
    if os.geteuid() != 0 or not sys.stdin.isatty():
        raise RuntimeError('Run sudo agent-os-configure from an interactive Linux terminal.')
    models = free_models()
    ids = {m['id'] for m in models}
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    ids.update(cfg.get('paid_models_allowed',[]))
    print('Available free models and explicitly authorized paid models:')
    for name in sorted(ids): print('  ' + name)
    default = cfg.get('gateway_model', DEFAULT_MODEL)
    chosen = input(f'Model [{default}]: ').strip() or default
    if chosen not in ids: raise RuntimeError('Choose a listed model. No configuration was changed.')
    print('\nQuestions and selected tool output, including files you ask the agent to read, go to Vercel and its model provider.')
    print('Normal broker execution cannot access provider credentials, private service state, or user home directories.')
    print('Keys stay inside this VM. Blank input keeps an existing key. Jev is used for automatic action assessment.')
    gateway = getpass.getpass('Vercel AI Gateway key: ').strip()
    jev = getpass.getpass('Jev / TypeSafe key (runtime action assessment): ').strip()
    if gateway: cfg['gateway_key'] = gateway
    if jev: cfg['jev_key'] = jev
    if not cfg.get('gateway_key'): raise RuntimeError('A Vercel AI Gateway key is required.')
    cfg['gateway_model'] = chosen
    CONFIG.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = CONFIG.with_suffix('.tmp')
    # O_NOFOLLOW protects this root-owned configuration path against accidental symlinks.
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:
        os.fchmod(f.fileno(), 0o640)
        os.fchown(f.fileno(), 0, grp.getgrnam('agentos-ai').gr_gid)
        json.dump(cfg, f); f.write('\n'); f.flush(); os.fsync(f.fileno())
    temporary.replace(CONFIG)
    print('Saved. Keys are read on each request; no restart is required.')
    print('Run agent-os, select an activity, and press i for disk inspection or a to ask a question.')


if __name__ == '__main__':
    try: main()
    except (RuntimeError, ProviderError, OSError, ValueError) as exc:
        print('Setup: ' + str(exc), file=sys.stderr); sys.exit(1)
