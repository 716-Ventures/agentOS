"""Real session-owned Orca commands over kernel input; null sink, not audible QA."""
from pathlib import Path
import ast
import subprocess
import time


def verify(metrics,env,login_user,keyboard,snapshot,wait,core,scene):
    log=Path(env['XDG_RUNTIME_DIR'])/'orca-speech.log'
    output=Path(__file__).resolve().parents[1]/'test-output'
    output.mkdir(exist_ok=True)
    def speech():return log.read_text() if log.exists() else ''
    def await_speech(predicate,label):
        deadline=time.monotonic()+15
        while not predicate(speech()):
            if time.monotonic()>deadline:raise RuntimeError(label+'; speech tail: '+speech()[-16000:])
            time.sleep(.05)
    def navigate(name,back=False,leave_editor=False):
        # Traverse semantic reading order, including selectable status text.
        if leave_editor:keyboard.chord(29,15)
        deadline=time.monotonic()+5
        for _ in range(12):
            focus=snapshot('focused')
            if focus['name']==name and (name=='Direct input fixture' or focus.get('button')):return
            keyboard.chord(*((42,15) if back else (15,)))
            time.sleep(.1)
            if time.monotonic()>deadline:break
        raise RuntimeError('Keyboard reading order did not reach '+name+'; '+repr(snapshot('focused')))
    try:
        await_speech(lambda text:'Using speech server factory:' in text,'Session-owned Orca did not initialize speech')
        for cycle in range(30):
            baseline=len(speech());keyboard.chord(29,56,57)
            deadline=time.monotonic()+8
            while not any(layer['namespace']=='agentos-launcher' and layer['mapped'] for layer in scene()['system_layers']):
                if time.monotonic()>deadline:raise RuntimeError('Reader launcher did not open')
                time.sleep(.05)
            try:await_speech(lambda text:'SPEECH OUTPUT:' in text[baseline:] and 'Ask Agent text' in text[baseline:],'Repeated launcher speech failed at cycle '+str(cycle))
            except BaseException:
                print('LAUNCHER_DIAGNOSTIC failed cycle='+str(cycle)+' '+str(snapshot('launcher-diagnostic')),flush=True);raise
            keyboard.chord(1)
            deadline=time.monotonic()+8
            while any(layer['namespace']=='agentos-launcher' and layer['mapped'] for layer in scene()['system_layers']):
                if time.monotonic()>deadline:raise RuntimeError('Reader launcher did not close')
                time.sleep(.05)
            print('PASS: launcher speech cycle '+str(cycle),flush=True)
        # An unrelated bus client must not gain keyboard observation or grabs.
        denied=subprocess.run(['runuser','-u',login_user,'--','gdbus','call','--session',
            '--dest','org.freedesktop.a11y.Manager','--object-path','/org/freedesktop/a11y/Manager',
            '--method','org.freedesktop.a11y.KeyboardMonitor.WatchKeyboard'],env=env,capture_output=True,text=True,timeout=5)
        assert denied.returncode and 'AccessDenied' in denied.stderr,denied
        # Same-user access to the control socket does not authorize registering
        # a replacement reader; the compositor checks the kernel peer PID.
        registration="""import json,socket,sys
with socket.socket(socket.AF_UNIX) as connection:
 connection.settimeout(6);connection.connect(sys.argv[1])
 connection.sendall(b'{"op":"screen_reader.register","pid":1,"start":"0"}\\n')
 with connection.makefile('rb') as stream:rejected=json.loads(stream.readline())
assert rejected.get('ok') is False and 'owning graphical session' in rejected.get('error',''),rejected
print('PASS: same-user control client cannot replace the registered reader')
"""
        controls=list(Path(env['XDG_RUNTIME_DIR']).glob('agentos-compositor-*.sock'))
        assert len(controls)==1,controls
        subprocess.run(['runuser','-u',login_user,'--','python3','-c',registration,str(controls[0])],env=env,check=True,timeout=8)
        navigate('Direct input fixture',back=True,leave_editor=True)
        wait(lambda value:value['focused'])
        await_speech(lambda text:'SPEECH OUTPUT:' in text and 'Direct input fixture' in text,'Orca did not announce the focused editor')
        baseline=len(speech());keyboard.chord(110,35) # Insert+H, current Orca learn mode.
        await_speech(lambda text:'Entering learn mode.' in text[baseline:],'Kernel Orca command did not enter learn mode')
        # The rescue console must remain reachable during Orca's full grab.
        before_resume=scene()['direct_frames_presented']
        keyboard.chord(29,56,60)
        try:
            deadline=time.monotonic()+5
            while Path('/sys/class/tty/tty0/active').read_text().strip()!='tty2' or scene()['direct_active'] is not False:
                if time.monotonic()>deadline:raise RuntimeError('Orca full grab blocked the rescue VT shortcut')
                time.sleep(.05)
        finally:subprocess.run(['chvt','7'],check=True)
        deadline=time.monotonic()+8
        while scene()['direct_frames_presented']<=before_resume:
            if time.monotonic()>deadline:raise RuntimeError('Display did not resume after Orca-grab VT escape')
            time.sleep(.05)
        keyboard.chord(30);time.sleep(.2)
        assert snapshot()['text']=='','Learn-mode keystroke leaked into the document'
        baseline=len(speech());keyboard.chord(1)
        await_speech(lambda text:'Exiting learn mode.' in text[baseline:],'Kernel Escape did not exit Orca learn mode')
        keyboard.chord(30);wait(lambda value:value['text']=='a')
        baseline=len(speech());navigate('Save draft',leave_editor=True)
        await_speech(lambda text:'Save draft' in text[baseline:],'Keyboard navigation did not announce Save draft')
        keyboard.chord(28)
        deadline=time.monotonic()+8
        while core('presentation.get')['elements']['editor']['props']['value']!='a':
            if time.monotonic()>deadline:raise RuntimeError('Reader-guided keyboard Save did not commit')
            time.sleep(.05)
        navigate('Direct input fixture',back=True);wait(lambda value:value['focused'])
        keyboard.chord(31);wait(lambda value:value['text']=='as')
        baseline=len(speech());navigate('Discard draft',leave_editor=True)
        await_speech(lambda text:'Discard draft' in text[baseline:],'Keyboard navigation did not announce Discard draft')
        keyboard.chord(28);wait(lambda value:value['text']=='a')
        navigate('Direct input fixture',back=True);wait(lambda value:value['focused'])
        baseline=len(speech());keyboard.chord(110,35)
        await_speech(lambda text:'Entering learn mode.' in text[baseline:],'Reader did not re-enter learn mode for stop qualification')
        def bus(method,name):
            return subprocess.check_output(['runuser','-u',login_user,'--','gdbus','call','--session','--dest','org.freedesktop.DBus','--object-path','/org/freedesktop/DBus','--method','org.freedesktop.DBus.'+method,name],env=env,text=True,timeout=5)
        pid=ast.literal_eval(bus('GetConnectionUnixProcessID','org.gnome.Orca.KeyboardMonitor').replace('uint32 ',''))[0]
        assert Path('/proc',str(pid),'comm').read_text().strip()=='orca'
        subprocess.run(['runuser','-u',login_user,'--','/bin/kill','-TERM',str(pid)],check=True)
        deadline=time.monotonic()+8
        while bus('NameHasOwner','org.gnome.Orca.KeyboardMonitor').strip()!='(false,)':
            if time.monotonic()>deadline:raise RuntimeError('Owned reader did not release its monitor identity')
            time.sleep(.05)
        keyboard.chord(29,107);keyboard.chord(32);wait(lambda value:value['text']=='ad')
        spoof="""from gi.repository import Gio,GLib
c=Gio.bus_get_sync(Gio.BusType.SESSION,None)
r=c.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName',GLib.Variant('(su)',('org.gnome.Orca.KeyboardMonitor',4)),None,Gio.DBusCallFlags.NONE,1000,None)
assert r.unpack()==(1,)
try:c.call_sync('org.freedesktop.a11y.Manager','/org/freedesktop/a11y/Manager','org.freedesktop.a11y.KeyboardMonitor','WatchKeyboard',None,None,Gio.DBusCallFlags.NONE,1000,None)
except GLib.Error as error:assert 'AccessDenied' in str(error)
else:raise AssertionError('Spoofed reader gained keyboard access')
print('PASS: a same-user process claiming the Orca monitor name cannot access keyboard input')
"""
        subprocess.run(['runuser','-u',login_user,'--','python3','-c',spoof],env=env,check=True,timeout=5)
        print('PASS: session-owned Orca announces launcher/editor/Save/Discard; kernel learn-mode enter/exit isolates grabs, restores typing and completes edit/save/correction/discard; rescue VT remains reachable during a full grab; reader stop releases active grabs and preserves typing; unrelated and spoofed monitor access denied',flush=True)
    finally:
        if log.exists():
            destination=output/'orca-kernel-speech.log';destination.write_bytes(log.read_bytes());destination.chmod(0o600)
