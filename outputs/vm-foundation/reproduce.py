#!/usr/bin/env python3
"""Provision and verify a selected development guest; always shut it down afterward."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
SHELL=ROOT.parent/'agent-shell'


def graphical_checks():
    """Commands run in the deployed source root, using private headless displays."""
    checks=[('native-build',
        'cargo test --locked --manifest-path native-shell/Cargo.toml && '
        'cargo build --locked --manifest-path native-shell/Cargo.toml --examples && '
        'cargo build --locked --manifest-path native-shell/Cargo.toml && '
        'cargo test --locked --manifest-path native-compositor/Cargo.toml && '
        'cargo build --locked --manifest-path native-compositor/Cargo.toml --examples && '
        'cargo build --locked --manifest-path native-compositor/Cargo.toml',900),
        ('native-broker-pty','python3 native-shell/tests/pty_broker.py',90),
        ('native-installed-broker','dbus-run-session -- python3 native-shell/tests/installed_broker.py',120),
        ('direct-backend-cleanup','python3 native-shell/tests/direct_backend.py',30)]
    for appearance in ('light','dark'):
        for scale in (1,2):
            checks.append((f'native-{appearance}-{scale}',f'dbus-run-session -- python3 native-shell/tests/native_desktop.py --appearance {appearance} --text-scale {scale}',120))
    checks += [
        ('native-small-display','dbus-run-session -- python3 native-shell/tests/native_desktop.py --small --text-scale 2',120),
        ('native-cpu-contention','dbus-run-session -- python3 native-shell/tests/native_desktop.py --load',120),
        ('native-compositor','dbus-run-session -- python3 native-shell/tests/native_desktop.py --compositor',120),
        ('native-shared-workspace','dbus-run-session -- python3 native-shell/tests/native_desktop.py --compositor --shared',180)]
    for name,option in [('logout',''),('ime','--ime'),('host-loss','--host-failure'),('compositor-loss','--compositor-failure')]:
        checks.append(('native-session-'+name,'dbus-run-session -- python3 native-shell/tests/native_session.py '+option,120))
    checks.append(('direct-display-vt','sudo -n python3 tests/direct_display_guest.py',90))
    checks.append(('signed-graphical-release','python3 tests/graphical_release.py',300))
    return checks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',required=True,help='Separate runtime directory containing this guest disk and SSH identity')
    parser.add_argument('--ssh-port',type=int,default=22221)
    parser.add_argument('--prepare-only',action='store_true',help='Create a fresh bundle, then register it once in UTM')
    parser.add_argument('--base',help='Existing pinned Debian base image; checked by SHA-512')
    args=parser.parse_args()
    os.environ['AGENT_OS_VM_RUNTIME']=str(Path(args.runtime).expanduser().resolve())
    os.environ['AGENT_OS_VM_SSH_PORT']=str(args.ssh_port)
    import vm
    if args.prepare_only:
        vm.prepare(args.base)
        print('Register the printed bundle once in UTM, then repeat this command without --prepare-only.')
        return
    machine=vm.machine()
    report={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'result':'running',
            'vm_uuid':machine['uuid'],'base_sha512':vm.LOCK['sha512'],'checks':[],
            'not_tested':['live model inference','microphone/speaker signal','physical graphical input','physical hardware','OS update rollback']}
    def local(args,name,timeout=600):
        path=vm.RUN/(name+'.log')
        with path.open('w') as log:subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=timeout)
        print('PASS:',name,flush=True);report['checks'].append(name)
    def remote(command,name,timeout=180):local(vm.ssh_args()+[command],name,timeout)
    try:
        local([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tests'),'-p','*_test.py'],'vm-tool-tests')
        if not vm.alive():vm.start(hide=True)
        vm.wait_ready(60)
        remote('cloud-init status --wait','cloud-init',120)
        local([sys.executable,str(SHELL/'deploy.py')],'provision',900)
        report['deployment']=json.loads((vm.RUN/'deployment.json').read_text())
        remote('cd /home/developer/agent-os-source && python3 -m unittest discover -s tests -p "*_test.py" && cargo test --locked','unit-suites')
        for test,root in [('integration',False),('activity_removal',False),('broker_integration',False),
                          ('broker_restart_guest',False),('broker_reuse_guest',False),('file_result_guest',False),('image_preview_guest',False),
                          ('write_transport_guest',True),('layout_guest',False),('work_lifecycle_guest',True),('terminal_guest',False),('terminal_screen_guest',False),('presentation_guest',False),('broker_sources_guest',False),('voice_guest',False)]:
            remote(('sudo -n ' if root else '')+'python3 /home/developer/agent-os-source/tests/'+test+'.py',test)
        for name,command,timeout in graphical_checks():
            remote('cd /home/developer/agent-os-source && '+command,name,timeout)
        local([sys.executable,str(SHELL/'tests/work_lifecycle_terminal.py')],'terminal')
        local([sys.executable,str(SHELL/'tests/interactive_terminal.py')],'interactive-terminal')
        local([sys.executable,str(SHELL/'tests/voice_terminal.py')],'voice-terminal')
        remote('sudo -n python3 /home/developer/agent-os-source/tests/installation_guest.py interrupts','installation-interruption')
        remote('sudo -n python3 /home/developer/agent-os-source/tests/installation_guest.py rollbacks','runtime-rollback-recovery',300)
        local([sys.executable,str(ROOT/'verify.py')],'foundation-reboot-cold-start',240)
        remote('sudo -n python3 /home/developer/agent-os-source/tests/installation_guest.py verify','runtime-state-after-reboots')
        before=json.loads(vm.ssh('cat /etc/agent-os/release.json',capture_output=True,text=True,check=True).stdout)['runtime_release']
        remote('cd /home/developer/agent-os-source && sh install.sh','repeat-install',180)
        after=json.loads(vm.ssh('cat /etc/agent-os/release.json',capture_output=True,text=True,check=True).stdout)['runtime_release']
        if before!=after:raise RuntimeError('Repeat install changed the release identity unexpectedly')
        remote('sudo -n python3 /home/developer/agent-os-source/tests/installation_guest.py verify','state-after-repeat-install')
        remote('sudo -n python3 /home/developer/agent-os-source/tests/installation_guest.py cleanup','probe-cleanup')
        report['runtime_release']=after
        report['dependency_manifest']=json.loads(vm.ssh('sudo -n cat /var/lib/agent-os-install/dependencies.json',capture_output=True,text=True,check=True).stdout)
        report['host_tools']={name:subprocess.check_output(command,text=True).strip() for name,command in
                              [('utm',['utmctl','version']),('qemu_img',['qemu-img','--version']),('python',[sys.executable,'--version'])]}
        report['result']='pass'
    except Exception as exc:
        report.update(result='failed',error=str(exc));raise
    finally:
        try:
            vm.stop();deadline=time.monotonic()+40
            while vm.alive() and time.monotonic()<deadline:time.sleep(1)
            if vm.alive():raise RuntimeError('Guest did not complete orderly shutdown')
            report['guest_stopped']=True
        except Exception as exc:
            report.update(result='failed',error='Shutdown failed: '+str(exc));raise
        finally:
            report['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
            (vm.RUN/'reproduction.json').write_text(json.dumps(report,indent=2)+'\n')
            print('Evidence:',vm.RUN/'reproduction.json',flush=True)

if __name__=='__main__':main()
