#!/bin/zsh
set -eu
cd -- "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
python3 vm.py start
python3 vm.py wait --seconds 60
exec python3 vm.py ssh
