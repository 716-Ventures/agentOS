#!/usr/bin/python3
"""Privileged, fixed read-only disk metadata collector. No arbitrary commands."""
import datetime
import os
import subprocess
from common import DISK_SOCKET, listen, read_line, send

# No caller-provided paths, options, environment, or shell invocation.
TARGETS = ('/', '/usr', '/var', '/home', '/var/cache', '/var/log')


def collect():
    s = os.statvfs('/')
    report = {'measured_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'filesystem': {'path': '/', 'total_bytes': s.f_blocks*s.f_frsize,
                             'used_bytes': (s.f_blocks-s.f_bfree)*s.f_frsize,
                             'available_bytes': s.f_bavail*s.f_frsize},
              'evidence': [], 'limitations': [
                  'One filesystem only; directory totals overlap and must not be added together.',
                  'Measurements are not atomic. Allocated file blocks differ from filesystem accounting.',
                  'Directory size is not an estimate of safely reclaimable space.',
                  'Only directory metadata is read. File contents are not collected.']}
    report['filesystem']['display'] = {key.removesuffix('_bytes'): f'{value / 1024**3:.2f} GiB'
        for key, value in report['filesystem'].items() if key.endswith('_bytes')}
    for index, path in enumerate(TARGETS, 1):
        argv = ['/usr/bin/du', '-x', '-B1', '--max-depth=1', '--', path]
        try:
            result = subprocess.run(argv, capture_output=True, timeout=15,
                                    env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
            rows = []
            for line in result.stdout.decode('utf-8', 'replace').splitlines():
                size, sep, name = line.partition('\t')
                if sep and size.isdigit():
                    rows.append({'path': name, 'allocated_bytes': int(size)})
            rows.sort(key=lambda row: row['allocated_bytes'], reverse=True)
            report['evidence'].append({'id': f'D{index}', 'command': argv,
                'exit_code': result.returncode, 'rows': rows[:100],
                'rows_omitted': max(0, len(rows)-100),
                'errors': result.stderr.decode('utf-8', 'replace')[:2000]})
        except subprocess.TimeoutExpired:
            report['evidence'].append({'id': f'D{index}', 'command': argv,
                                      'error': 'Timed out after 15 seconds; measurement unavailable.'})
    return report


def main():
    for_conn = listen(DISK_SOCKET)
    while True:
        conn, _ = for_conn.accept()
        with conn:
            conn.settimeout(5)
            try:
                with conn.makefile('rb') as f:
                    request = read_line(f)
                if request != {'op': 'disk'}:
                    raise ValueError('Only the fixed disk inspection is supported')
                send(conn, {'ok': True, 'report': collect()})
            except (OSError, ValueError):
                try: send(conn, {'ok': False, 'error': 'Disk inspection failed'})
                except OSError: pass


if __name__ == '__main__': main()
