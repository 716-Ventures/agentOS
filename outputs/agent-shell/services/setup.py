#!/usr/bin/python3
"""First-run checks and deliberate local audio/provider setup; no implicit model calls."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def command(argv):
    try:
        result=subprocess.run(argv,capture_output=True,text=True,timeout=5)
        return dict(available=result.returncode==0,text=(result.stdout or result.stderr)[-12000:])
    except (OSError,subprocess.TimeoutExpired) as exc:return dict(available=False,text=str(exc))


def state_path():return Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'agent-os/setup.json'


def snapshot():
    network=command(['ip','-j','route','show','default'])
    try:routes=json.loads(network['text']) if network['available'] else []
    except ValueError:routes=[]
    try:
        usage=json.loads(Path('/run/agent-os-ai/model-usage.json').read_text())
        models=[{k:row.get(k) for k in ('provider','model','role','configured')} for row in usage.get('configuration',[])]
    except (OSError,ValueError,TypeError):models=None
    return dict(network=dict(default_route=bool(routes),note='A configured route does not establish internet connectivity'),
                microphone=command(['arecord','-l']),speaker=command(['aplay','-l']),
                providers=models,services=command(['systemctl','is-active','agent-os-core','agent-os-broker','agent-os-ai','agent-os-voice']))


def complete(observed):
    path=state_path();path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.setup-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o600)
            json.dump(dict(version=1,completed_at=time.time(),checks=observed),stream);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:Path(temporary).unlink(missing_ok=True)


def audio_check():
    # Capture is explicitly requested here and remains owned by this setup process.
    sys.path.insert(0,'/usr/local/lib/agent-os/current/client')
    from voice_input import VoiceInput
    voice=VoiceInput()
    print('Recording up to ten seconds. Speak a short sentence; press Enter to finish. Audio is discarded after recognition.')
    voice.start({})
    try:
        deadline=time.monotonic()+8
        while voice.snapshot()['state']=='starting' and time.monotonic()<deadline:time.sleep(.05)
        current=voice.snapshot()
        if current['state']!='recording':raise RuntimeError(current.get('error') or 'Microphone did not start')
        input();voice.finish();deadline=time.monotonic()+55
        while voice.snapshot()['state']=='transcribing' and time.monotonic()<deadline:time.sleep(.05)
        current=voice.snapshot()
        if current['state']!='review':raise RuntimeError(current.get('error') or 'Recognition timed out')
        result=current['result'];print('Recognized:',result.get('text') or 'No speech signal detected')
        print('This transcript was not submitted. Compare it with what you said; retry if needed.')
    finally:voice.cancel()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--json',action='store_true');args=parser.parse_args()
    observed=snapshot()
    if args.json:print(json.dumps(observed,indent=2));return
    if not sys.stdin.isatty():raise RuntimeError('Run agent-os-setup from an interactive Linux terminal')
    print('Welcome to agentOS. Local controls work without a model account.\n')
    while True:
        print('Network:', 'default route configured' if observed['network']['default_route'] else 'no default route; inspect networkctl status')
        print('Microphone devices:\n'+observed['microphone']['text']);print('Speaker devices:\n'+observed['speaker']['text'])
        for model in observed['providers'] or []:print(model['model']+': '+('configured' if model['configured'] else 'setup required'))
        if observed['providers'] is None:print('Provider configuration status unavailable; inspect agent-os-ai service')
        print('\n[m] Test microphone  [s] Test speaker  [p] Configure providers  [r] Recheck  [d] Finish setup  [q] Exit')
        choice=input('Choose: ').strip().lower()
        try:
            if choice=='m':audio_check()
            elif choice=='s':
                print('Playing a short test tone. Check whether you can hear it.')
                subprocess.run(['speaker-test','-t','sine','-f','440','-l','1'],check=True,timeout=15)
            elif choice=='p':subprocess.run(['sudo','agent-os-configure'],check=True)
            elif choice=='r':observed=snapshot()
            elif choice=='d':complete(observed);print('Setup recorded. Run agent-os for the terminal environment or open the native desktop.');return
            elif choice=='q':return
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:print('Setup check:',exc)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,RuntimeError,KeyboardInterrupt) as exc:print('Setup:',exc,file=sys.stderr);sys.exit(1)
