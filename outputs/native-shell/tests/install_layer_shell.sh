#!/bin/sh
# Ubuntu 24.04 CI lacks the Debian runtime package. Build the exact MIT upstream
# used by Debian 13; this script is for disposable CI runners only.
set -eu
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT HUP INT TERM
git -C "$root" init -q
git -C "$root" fetch -q --depth=1 https://github.com/wmww/gtk4-layer-shell.git 536ff516ed68b9bb34afc4c07f942a54b2b4b03f
git -C "$root" checkout -q --detach FETCH_HEAD
meson setup "$root/build" "$root" --prefix=/usr/local --libdir=lib -Dintrospection=false -Dvapi=false -Dexamples=false -Dtests=false -Dsmoke-tests=false -Ddocs=false
meson compile -C "$root/build"
sudo meson install -C "$root/build"
sudo install -D -m 644 "$root/LICENSE" /usr/local/share/doc/gtk4-layer-shell/LICENSE
sudo ldconfig
