#!/bin/sh
set -eu
cd "$(dirname "$0")"
cargo build --release --locked
sudo groupadd --system -f agentos
if ! id agentos >/dev/null 2>&1; then
  sudo useradd --system --gid agentos --home-dir /var/lib/agent-os-runtime --shell /usr/sbin/nologin agentos
fi
if ! id agentos-layout >/dev/null 2>&1; then
  sudo useradd --system --gid agentos --home-dir /var/lib/agent-os-layout --shell /usr/sbin/nologin agentos-layout
fi
sudo usermod -a -G agentos developer
sudo groupadd --system -f agentos-ai
if ! id agentos-ai >/dev/null 2>&1; then
  sudo useradd --system --gid agentos-ai --home-dir /var/lib/agent-os-ai --shell /usr/sbin/nologin agentos-ai
fi
sudo groupadd --system -f agentos-broker
sudo usermod -a -G agentos-broker agentos-ai
sudo usermod -a -G agentos-broker developer
sudo install -d -m 0755 /var/lib/agent-os-workspaces
sudo systemctl stop agent-os-broker.service 2>/dev/null || true
sudo systemctl stop agent-os-ai.service agent-os-disk.service agent-os-layout.service 2>/dev/null || true
sudo install -d -m 0755 /usr/local/lib/agent-os/services
sudo install -m 0644 services/*.py /usr/local/lib/agent-os/services/
sudo install -m 0644 systemd/agent-os-ai.service systemd/agent-os-disk.service /etc/systemd/system/
sudo install -m 0644 systemd/agent-os-broker.service systemd/agent-os-layout.service /etc/systemd/system/
sudo install -m 0755 services/broker-launcher.sh /usr/local/bin/agent-os-broker
sudo install -m 0755 services/configure-launcher.sh /usr/local/bin/agent-os-configure
sudo systemctl stop agent-os-core.service 2>/dev/null || true
sudo install -d /usr/local/lib/agent-os
sudo install -m 0755 target/release/agent-os-core /usr/local/lib/agent-os/agent-os-core
sudo install -m 0755 client/agent_os.py /usr/local/bin/agent-os
sudo install -m 0644 systemd/agent-os-core.service /etc/systemd/system/agent-os-core.service
sudo systemctl daemon-reload
sudo systemctl enable --now agent-os-layout.service agent-os-core.service agent-os-disk.service agent-os-broker.service agent-os-ai.service
sudo python3 - <<'PY'
import json
from pathlib import Path
p=Path('/etc/agent-os/release.json')
s=json.loads(p.read_text())
s.update(version='0.5.0',milestone='Shared agent and terminal layouts',agent_runtime='Gateway agent with general execution and filesystem broker; Jev typed effect advisory',voice='not implemented')
p.write_text(json.dumps(s,indent=2)+'\n')
Path('/etc/motd').write_text('''
Agent OS 0.5 | Shared agent and terminal layouts

  agent-os          Open the terminal environment
  agent-os --help   Scriptable commands
  agent-os-status   Inspect the Linux foundation

Inside agent-os: F6 selects activities; d removes an activity; i inspects disk; Enter replies.
Set up model keys: sudo agent-os-configure
Provider status: agent-os providers. Voice is not connected yet.
The ordinary Linux shell and sudo remain available for recovery.

''')
PY
echo 'Installed. Reconnect your login session for agentos group membership, then run agent-os.'
