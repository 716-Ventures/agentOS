#!/usr/bin/python3
"""Supervised job entry point; streams workflow output without holding credentials."""
import argparse
import json
import sys
import unicodedata
from common import AI_SOCKET, connect, read_line


def clean(s):
    return ''.join(c for c in str(s) if c in '\n\t' or not unicodedata.category(c).startswith('C'))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('op', choices=['status', 'disk', 'ask', 'report'])
    p.add_argument('activity', type=int, nargs='?', default=1)
    p.add_argument('prompt', nargs='?')
    args = p.parse_args()
    req = {'op': args.op, 'activity': args.activity}
    if args.prompt is not None: req['prompt'] = args.prompt
    with connect(AI_SOCKET, req, timeout=240) as conn:
        with conn.makefile('rb') as f:
            while True:
                value = read_line(f)
                if 'text' in value: print(clean(value['text']), flush=True)
                if 'status' in value: print(json.dumps(value['status'], indent=2), flush=True)
                if 'report' in value: print(json.dumps(value['report'], indent=2), flush=True)
                if 'error' in value: raise RuntimeError(value['error'])
                if value.get('done'): return 0 if value.get('ok', True) else 1


if __name__ == '__main__':
    try: sys.exit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print('Agent OS: ' + clean(str(exc)), file=sys.stderr); sys.exit(1)
