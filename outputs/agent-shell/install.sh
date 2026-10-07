#!/bin/sh
set -eu
cd "$(dirname "$0")"
sudo -n python3 bootstrap.py
cargo build --release --locked
sudo -n python3 install_runtime.py
echo 'Installed. Reconnect your login session for group membership, then run agent-os.'
