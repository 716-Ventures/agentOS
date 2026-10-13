#!/bin/sh
# Ubuntu 24.04's VTE predates GTK4 terminal accessibility. Supply the minimum
# supported upstream release on disposable CI runners; Debian 13 ships newer.
set -eu
if pkg-config --atleast-version=0.78 vte-2.91-gtk4; then exit 0; fi
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT HUP INT TERM
curl -fsSL https://download.gnome.org/sources/vte/0.78/vte-0.78.2.tar.xz -o "$root/vte.tar.xz"
echo "35d7bcde07356846b4a12881c8e016705b70a9004a9082285eee5834ccc49890  $root/vte.tar.xz" | sha256sum -c -
tar xf "$root/vte.tar.xz" -C "$root"
# Use the runner's system library directory: GTK's link flags put it before
# /usr/local/lib, otherwise the linker still selects Ubuntu's older VTE.
meson setup "$root/build" "$root/vte-0.78.2" --prefix=/usr --libdir="lib/$(cc -dumpmachine)" \
  -Dgtk3=false -Dgtk4=true -Da11y=true -Dgir=false -Dvapi=false -Ddocs=false \
  -Dglade=false -Dgnutls=false -Dicu=false -D_systemd=false
meson compile -C "$root/build" -j 2
sudo meson install -C "$root/build"
sudo install -D -m 644 "$root/vte-0.78.2/COPYING.LGPL3" /usr/local/share/doc/vte/COPYING.LGPL3
sudo ldconfig
