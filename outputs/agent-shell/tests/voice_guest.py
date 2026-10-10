#!/usr/bin/python3
"""Actual CPU recognizer and local microphone lifecycle; not acoustic qualification."""
import base64
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import wave
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client'))
import voice_input


def main():
    assets=json.loads(Path('/usr/local/lib/agent-os/current/voice-assets.json').read_text())
    sample=Path(assets['root'])/'sample.wav'
    buffer=io.BytesIO()
    with wave.open(str(sample),'rb') as source,wave.open(buffer,'wb') as target:
        target.setnchannels(1);target.setsampwidth(2);target.setframerate(16000)
        target.writeframes(source.readframes(160000))
    started=time.monotonic()
    result=voice_input.request('transcribe',wav_base64=base64.b64encode(buffer.getvalue()).decode())
    transcript=result['text'].lower();assert 'ask not what your country' in transcript,result
    assert result['requires_review'] is True and result['recognition_seconds']<45,result
    print(json.dumps({'check':'real offline English recognition','result':result,'wall_seconds':time.monotonic()-started}))
    silent=io.BytesIO()
    with wave.open(silent,'wb') as target:
        target.setnchannels(1);target.setsampwidth(2);target.setframerate(16000);target.writeframes(bytes(32000))
    result=voice_input.request('transcribe',wav_base64=base64.b64encode(silent.getvalue()).decode())
    assert result['status']=='no_signal' and result['text']=='',result
    capture=voice_input.request('capture.start');assert capture['state']=='recording'
    time.sleep(.3)
    assert voice_input.request('status')['state'] in ('recording','recorded')
    # A second process cannot finish someone else's microphone session, even with its token.
    script='import sys;sys.path.insert(0,sys.argv[1]);import voice_input;voice_input.request("capture.finish",token=sys.argv[2])'
    other=subprocess.run(['/usr/bin/python3','-c',script,str(Path(__file__).resolve().parents[1]/'client'),capture['token']],capture_output=True,text=True)
    assert other.returncode and 'another input process' in other.stderr,other.stderr
    voice_input.request('cancel');assert voice_input.request('status')['state']=='idle'
    proc=subprocess.run(['pgrep','-u','agentos-voice','-x','arecord'],capture_output=True,text=True)
    assert proc.returncode==1,'Microphone child was left running: '+proc.stdout
    print('PASS: zero-signal rejection, explicit capture, owner-bound token, cancellation, no recorder leak')
    print('NOT QUALIFIED: actual host microphone speech, speaker output, accents, background-noise accuracy, hardware')

if __name__=='__main__':main()
