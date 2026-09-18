#!/usr/bin/python3
import argparse
import json
import sys
from common import connect, read_line

SOCKET='/run/agent-os-broker/api.sock'


def request(op,**fields):
    with connect(SOCKET,{'op':op,**fields},timeout=25) as conn:
        with conn.makefile('rb') as f:r=read_line(f)
    if not r['ok']:raise RuntimeError(r['error'])
    return r['result']


def main():
    p=argparse.ArgumentParser(description='Review and control general system broker operations')
    p.add_argument('op',choices=['list','poll','cancel','approve'])
    p.add_argument('job_id',nargs='?')
    args=p.parse_args()
    print(json.dumps(request(args.op,**({'job_id':args.job_id} if args.job_id else {})),indent=2))

if __name__=='__main__':
    try:main()
    except (OSError,RuntimeError,ValueError) as exc:print(str(exc),file=sys.stderr);sys.exit(1)
