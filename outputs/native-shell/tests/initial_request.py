#!/usr/bin/python3
"""Real empty core and native backend; absent broker prevents inference dispatch."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
SHELL=ROOT.parent if (ROOT.parent/'install_runtime.py').is_file() else ROOT.parent/'agent-shell'
with tempfile.TemporaryDirectory(prefix='agentos-initial-request-') as directory:
    root=Path(directory);endpoint=root/'core.sock'
    env={**os.environ,'AGENT_OS_SOCKET':str(endpoint),'AGENT_OS_STATE':str(root/'core-state'),
         'XDG_STATE_HOME':str(root/'state'),'AGENT_OS_BROKER_SOCKET':str(root/'absent-broker.sock')}
    with (root/'core.log').open('w') as log:
        core=subprocess.Popen([str(SHELL/'target/release/agent-os-core')],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            deadline=time.monotonic()+10
            while not endpoint.exists():
                assert core.poll() is None and time.monotonic()<deadline,'Private core did not start'
                time.sleep(.05)
            subprocess.run(['cargo','test','--locked','--manifest-path',str(ROOT/'Cargo.toml'),
                'transport::initial_document_tests::initial_typed_requests_validate_before_creating_and_never_launch_on_broker_failure',
                '--','--ignored','--exact','--nocapture'],env=env,check=True,timeout=60)
            with socket.socket(socket.AF_UNIX) as conn:
                conn.settimeout(2);conn.connect(str(endpoint));conn.sendall(b'{"op":"snapshot"}\n')
                response=json.loads(conn.makefile('rb').readline());assert response['ok'],response
                assert len(response['result']['activities'])==1 and response['result']['jobs']==[]
            print('PASS: blank typed request creates no activity; explicit requests reuse one internal activity; broker failure launches no inference')
        finally:
            if core.poll() is None:os.killpg(core.pid,signal.SIGTERM)
            try:core.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(core.pid,signal.SIGKILL);core.wait(timeout=5)
            print('PASS: private request-test core reaped')
