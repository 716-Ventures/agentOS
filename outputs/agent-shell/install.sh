#!/bin/sh
set -eu
cd "$(dirname "$0")"
sudo -n python3 bootstrap.py
sudo -n python3 bootstrap_voice.py
cargo build --release --locked
native_root=..
if [ -d native-shell ]; then native_root=.; fi
cargo build --release --locked --manifest-path "$native_root/native-shell/Cargo.toml"
cargo build --release --locked --manifest-path "$native_root/native-compositor/Cargo.toml"
python3 collect_licenses.py Cargo.toml "$native_root/native-shell/Cargo.toml" "$native_root/native-compositor/Cargo.toml"
sudo -n python3 install_runtime.py
echo 'Installed. Reconnect your login session for group membership, then run agent-os.'
