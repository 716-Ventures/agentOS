#!/usr/bin/env python3
from pathlib import Path
import os,sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'vm-foundation'))
import vm
args=vm.ssh_args()
os.execvp('ssh',args[:-1]+['-t']+args[-1:]+['exec env TERM=xterm-256color agent-os'])
