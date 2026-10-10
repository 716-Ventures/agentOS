#!/usr/bin/python3
"""Real direct-backend startup failures must exit without launching a nested host."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
COMPOSITOR=ROOT/'native-compositor/target/debug/agent-os-compositor'

def main():
    with tempfile.TemporaryDirectory(prefix='agentos-direct-startup-') as directory:
        root=Path(directory);root.chmod(0o700)
        env={**os.environ,'XDG_RUNTIME_DIR':str(root),'XDG_CONFIG_HOME':str(root),
             'AGENT_OS_COMPOSITOR_BACKEND':'drm','LIBSEAT_BACKEND':'agentos-invalid-backend'}
        result=subprocess.run([str(COMPOSITOR)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
        assert result.returncode!=0,result.stdout
        assert b'"wayland_display"' not in result.stdout,result.stdout
        assert not list(root.glob('wayland-*')) and not list(root.glob('agentos-compositor-*.sock'))
        config=root/'agentos';config.mkdir();(config/'outputs.json').write_text('{"outputs":{"DP-1":{"scale":0}}}')
        result=subprocess.run([str(COMPOSITOR)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
        assert result.returncode!=0 and b'Invalid output scale' in result.stderr,result.stderr
        assert not list(root.glob('wayland-*')) and not list(root.glob('agentos-compositor-*.sock'))
    print('PASS: direct backend rejects unavailable seat/invalid output preferences without fallback or leaked sockets')

if __name__=='__main__':main()
