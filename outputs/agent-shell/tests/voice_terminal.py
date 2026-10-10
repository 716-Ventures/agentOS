#!/usr/bin/env python3
"""Real SSH/curses microphone controls; speech quality is tested separately."""
from pathlib import Path
exec(Path(__file__).with_name('interactive_terminal.py').read_text().split('try:\n    process=spawn')[0])
try:
    process=spawn('agent-os');pump(1)
    started=keys('V',.5);assert b'Microphone' in started,started
    stopped=keys('V',2);assert b'off' in stopped and (b'transcrib' in stopped or b'ready' in stopped),stopped
    reviewed=keys('V',.5)
    # The guest can receive silence or incidental environmental speech. Neither submits work.
    assert b'No speech signal' in reviewed or b'Review voice transcript' in reviewed,reviewed
    jobs=guest("import json,subprocess;print(subprocess.check_output(['agent-os','jobs',"+repr(str(fixture['activity']))+"],text=True))")
    assert not jobs,'A recording submitted work without transcript review: '+repr(jobs)
    keys('\x1b',.3)
    keys('V',.3);keys('\x1b',.3)
    status=guest("import json,sys;sys.path.insert(0,'/usr/local/lib/agent-os/current/client');import voice_input;print(json.dumps(voice_input.request('status')))")
    assert status['state']=='idle',status
    # Leaving while recording must close the recorder, without waiting for its ten-second cap.
    keys('V',.3);keys('q',.3);assert process.wait(timeout=5)==0
    status=guest("import json,sys;sys.path.insert(0,'/usr/local/lib/agent-os/current/client');import voice_input;print(json.dumps(voice_input.request('status')))")
    assert status['state']=='idle',status
    print(json.dumps({'result':'pass','checks':['visible microphone state','explicit finish','transcript or no-signal review','no implicit request submission','Esc cancellation','q recorder cleanup']}))
finally:
    if process and process.poll() is None:
        keys('\x1b',.2);keys('q',.2)
        process.terminate() if process.poll() is None else None
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:process.kill();process.wait()
    os.close(master);os.close(slave)
    guest("import json,subprocess;from pathlib import Path;subprocess.run(['agent-os','stop-activity',"+repr(str(fixture['activity']))+"],check=True,stdout=subprocess.DEVNULL);subprocess.run(['agent-os','remove',"+repr(str(fixture['activity']))+"],check=True,stdout=subprocess.DEVNULL);p=Path.home()/'.local/state/agent-os/selection.json';old="+repr(fixture['old_selection'])+";p.write_text(old) if old is not None else p.unlink(missing_ok=True);print('{}')")
