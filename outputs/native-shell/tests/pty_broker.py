#!/usr/bin/python3
"""Native Rust transport against the actual broker handler, tmux and OS PTYs.
The fixture supplies a job record directly; it does not qualify systemd execution policy.
"""
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
ROOT=Path(__file__).resolve().parents[1]
SHELL=ROOT.parent if (ROOT.parent/'install_runtime.py').is_file() else ROOT.parent/'agent-shell'
sys.path.insert(0,str(SHELL/'services'))
import broker
import terminal_sessions as terminals

with tempfile.TemporaryDirectory(prefix='agentos-native-pty-') as directory:
    root=Path(directory);broker.STATE=root
    ident='a'*32
    code='''import os,signal
print('NATIVE_READY',flush=True)
signal.signal(signal.SIGWINCH,lambda *_:print('GRID',os.get_terminal_size().columns,os.get_terminal_size().lines,flush=True))
while True:
    try:value=input()
    except EOFError:break
    print('HELLO',value,flush=True)
'''
    job={'id':ident,'activity':1,'status':'running','terminal':True,'rows':24,'cols':80,'argv':['/usr/bin/python3','-u','-c',code]}
    broker.JOBS[ident]=job
    tmux,exit_path,argv=terminals.command(job,root);argv.remove('-C');argv.insert(argv.index('new-session')+1,'-d')
    server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);endpoint=root/'broker.sock';server.bind(str(endpoint));server.listen(8)
    stopping=threading.Event()
    def serve():
        while not stopping.is_set():
            conn,_=server.accept()
            with conn:
                raw=conn.makefile('rb').readline(4*1024*1024)
                if not raw:continue
                req=json.loads(raw)
                uid=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
                try:response={'ok':True,'result':broker.handle(req,uid)}
                except ValueError as exc:response={'ok':False,'error':str(exc)}
                conn.sendall(json.dumps(response).encode()+b'\n')
    worker=threading.Thread(target=serve)
    try:
        subprocess.run(argv,check=True,timeout=5,env={**os.environ,'TERM':'xterm-256color'})
        terminals.register(ident,None,tmux,24,80);worker.start()
        subprocess.run(['cargo','+1.85.1','test','--locked','--manifest-path',str(ROOT/'Cargo.toml'),'pty_transport::tests::real_broker_terminal_round_trip_and_reattach','--','--ignored','--exact','--nocapture'],
            env={**os.environ,'AGENT_OS_PTY_TEST_SOCKET':str(endpoint),'AGENT_OS_PTY_TEST_JOB':ident},check=True,timeout=90)
        assert terminals.SESSIONS[ident]['token'] is None
        assert terminals.SESSIONS[ident]['reader'] is None
        print('PASS: native transport / real broker / Unicode PTY input / SIGWINCH / detach / restored screen / reader cleanup')
    finally:
        stopping.set()
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as wake:
            wake.connect(str(endpoint))
        if worker.ident:worker.join(timeout=5)
        server.close()
        for session in terminals.SESSIONS.values():terminals.close_reader(session)
        subprocess.run(['/usr/bin/tmux','-S',str(tmux),'kill-server'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
        assert not worker.is_alive()
