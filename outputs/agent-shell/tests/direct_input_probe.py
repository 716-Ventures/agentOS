#!/usr/bin/python3
"""Dedicated-VM uinput journey: kernel -> libinput -> Wayland -> GTK -> core.

Synthetic kernel devices exercise the direct input stack. This is not evidence
of physical host keyboard/mouse delivery, speech, or human usability.
"""
import ast
import fcntl
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import time


class Device:
    def __init__(self,keyboard):
        self.fd=os.open('/dev/uinput',os.O_WRONLY|os.O_NONBLOCK)
        try:
            fcntl.ioctl(self.fd,0x40045564,1) # UI_SET_EVBIT EV_KEY
            if keyboard:
                for key in range(1,249):fcntl.ioctl(self.fd,0x40045565,key)
            else:
                for key in (272,273,274):fcntl.ioctl(self.fd,0x40045565,key)
                fcntl.ioctl(self.fd,0x40045564,3) # EV_ABS
                for axis in (0,1):
                    fcntl.ioctl(self.fd,0x40045567,axis) # UI_SET_ABSBIT
                    fcntl.ioctl(self.fd,0x401c5504,struct.pack('H2xiiiiii',axis,0,0,65535,0,0,0))
            name=('agentOS verification keyboard' if keyboard else 'agentOS verification pointer').encode()
            fcntl.ioctl(self.fd,0x405c5503,struct.pack('HHHH80sI',3,0x1209,0x716,1,name,0))
            fcntl.ioctl(self.fd,0x5501) # UI_DEV_CREATE
        except BaseException:
            os.close(self.fd);raise
    def event(self,kind,code,value):
        os.write(self.fd,struct.pack('llHHi',0,0,kind,code,value))
    def sync(self):self.event(0,0,0)
    def chord(self,*keys):
        for key in keys:self.event(1,key,1);self.sync()
        for key in reversed(keys):self.event(1,key,0);self.sync()
    def click(self,x,y,width,height):
        self.event(3,0,round(x*65535/width));self.event(3,1,round(y*65535/height));self.sync()
        time.sleep(.1)
        self.chord(272)
    def close(self):
        try:fcntl.ioctl(self.fd,0x5502)
        finally:os.close(self.fd)


def assistive():
    import pyatspi
    from collections import deque
    def find(name,role):
        queue=deque([pyatspi.Registry.getDesktop(0)]);observed=[]
        for _ in range(2048):
            if not queue:break
            node=queue.popleft()
            try:
                observed.append((node.name,node.getRoleName()))
                if node.name==name and node.getRole()==role:return node
                queue.extend(node[index] for index in range(min(node.childCount,128)))
            except (RuntimeError,LookupError):pass
        raise ValueError('Input fixture accessible control unavailable: '+name+'; tree='+repr(observed[:80]))
    for line in sys.stdin:
        try:
            assert line.strip()=='snapshot'
            field=find('Direct input fixture',pyatspi.ROLE_TEXT)
            ancestor=field
            while ancestor.parent is not None and ancestor.getRole()!=pyatspi.ROLE_FRAME:ancestor=ancestor.parent
            def within(node):
                if node.name=='Save draft' and node.getRole()==pyatspi.ROLE_PUSH_BUTTON:return node
                for index in range(node.childCount):
                    result=within(node[index])
                    if result is not None:return result
                return None
            save=within(ancestor)
            if save is None:raise ValueError('Save button not in editor window')
            def rect(node):
                # GTK's screen coordinates have a zero origin on Wayland.
                # Window coordinates include ancestor offsets; the compositor supplies placement.
                value=node.queryComponent().getExtents(pyatspi.WINDOW_COORDS)
                return [value.x+value.width/2,value.y+value.height/2]
            text=field.queryText();value=text.getText(0,text.characterCount)
            response={'text':value,'field':rect(field),'save':rect(save),'focused':field.getState().contains(pyatspi.STATE_FOCUSED)}
        except Exception as exc:response={'error':str(exc)}
        print(json.dumps(response),flush=True)


def verify(metrics,output,core,scene,target,login_user):
    subprocess.run(['modprobe','uinput'],check=True)
    # Join only this test session's accessibility bus; never inspect other users.
    bus=None;observer_runtime=None;deadline=time.monotonic()+10
    while bus is None and time.monotonic()<deadline:
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():continue
            try:
                values=dict(value.split(b'=',1) for value in (proc/'environ').read_bytes().split(b'\0') if b'=' in value)
                if ((proc/'exe').resolve().name=='agent-os-desktop' and values.get(b'AGENT_OS_METRICS_DIR')==str(metrics).encode() and values.get(b'DBUS_SESSION_BUS_ADDRESS')):
                    bus=values[b'DBUS_SESSION_BUS_ADDRESS'].decode();observer_runtime=values[b'XDG_RUNTIME_DIR'].decode();break
            except (OSError,ValueError):pass
        if bus is None:time.sleep(.05)
    if bus is None:raise RuntimeError('Owned direct-session bus not found')
    env={**os.environ,'DBUS_SESSION_BUS_ADDRESS':bus,'XDG_RUNTIME_DIR':observer_runtime}
    # libatspi may otherwise reuse the login user's cached accessibility bus.
    address=subprocess.check_output(['runuser','-u',login_user,'--','gdbus','call','--session','--dest','org.a11y.Bus','--object-path','/org/a11y/bus','--method','org.a11y.Bus.GetAddress'],env=env,text=True,timeout=5)
    env['AT_SPI_BUS_ADDRESS']=ast.literal_eval(address)[0]
    helper=subprocess.Popen(['runuser','-u',login_user,'--','python3',str(Path(__file__).resolve()),'--accessibility'],
                            env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    keyboard=pointer=None
    try:
        def snapshot():
            helper.stdin.write('snapshot\n');helper.stdin.flush()
            if not select.select([helper.stdout],[],[],3)[0]:raise RuntimeError('Assistive input observation timed out')
            line=helper.stdout.readline(65537)
            if not line or len(line)>65536:raise RuntimeError('Assistive observer disconnected')
            value=json.loads(line)
            if 'error' in value:raise RuntimeError(value['error'])
            return value
        def wait(predicate):
            deadline=time.monotonic()+8;last=None
            while True:
                try:
                    value=snapshot();last=value
                    if predicate(value):return value
                except RuntimeError as exc:
                    last=str(exc)
                    if helper.poll() is not None:raise
                if time.monotonic()>deadline:raise RuntimeError('Direct input did not reach the expected GTK state: '+repr(last))
                time.sleep(.05)
        initial=wait(lambda value:value['text']=='')
        keyboard=Device(True);pointer=Device(False)
        subprocess.run(['udevadm','settle','--timeout=5'],check=True)
        for node in Path('/sys/class/input').glob('event*'):
            try:
                if 'agentOS verification' in (node/'device/name').read_text():
                    properties=subprocess.check_output(['udevadm','info','--query=property','--path',str(node)],text=True)
                    print('Input fixture device:',node.name,[line for line in properties.splitlines() if line.startswith('ID_INPUT')],flush=True)
            except OSError:pass
        time.sleep(.5) # bounded kernel/udev/libinput hotplug discovery
        width,height=output['width'],output['height']
        def click(point):
            geometry=next(row['geometry'] for row in scene()['windows'] if row['id']==target)
            x,y=point[0]+geometry['x'],point[1]+geometry['y']
            if not (0<x<width and 0<y<height):raise RuntimeError('Fixture lies outside the direct output')
            pointer.click(x,y,width,height)
        click(initial['field'])
        time.sleep(.2)
        observed=scene()
        assert observed['seat_focus']==target,'Kernel click changed the focused window unexpectedly'
        wait(lambda value:value['focused'])
        for key in (30,34,18,49,20,24,31):keyboard.chord(key) # agentos
        wait(lambda value:value['text']=='agentos')
        # Include the separator in the copied span. GTK coalesces adjacent single-word inserts.
        keyboard.chord(57);keyboard.chord(29,30);keyboard.chord(29,46);keyboard.chord(107);keyboard.chord(29,47)
        wait(lambda value:value['text']=='agentos agentos ')
        keyboard.chord(29,44) # Ctrl+Z undoes the paste as one action
        wait(lambda value:value['text']=='agentos ')
        keyboard.chord(29,42,44) # Ctrl+Shift+Z redo
        wait(lambda value:value['text']=='agentos agentos ')
        keyboard.chord(29,44)
        wait(lambda value:value['text']=='agentos ')
        keyboard.chord(14)
        current=wait(lambda value:value['text']=='agentos')
        deadline=time.monotonic()+8
        while True:
            draft=core('draft.get')
            if draft['draft']=='agentos':break
            if time.monotonic()>deadline:raise RuntimeError('Kernel typing did not retain the exact core draft: '+repr(draft))
            time.sleep(.05)
        assert core('presentation.get')['elements']['editor']['props']['value']=='','Typing committed before deliberate Save'
        click(current['save'])
        deadline=time.monotonic()+8
        while core('presentation.get')['elements']['editor']['props']['value']!='agentos':
            if time.monotonic()>deadline:raise RuntimeError('Kernel pointer Save did not commit the exact draft')
            time.sleep(.05)
        assert core('draft.get')['draft'] is None
        print('PASS: direct kernel/libinput keyboard, absolute pointer, GTK clipboard, grouped undo/redo, retained draft and deliberate Save')
    finally:
        if pointer:pointer.close()
        if keyboard:keyboard.close()
        helper.terminate()
        try:helper.wait(timeout=3)
        except subprocess.TimeoutExpired:helper.kill();helper.wait(timeout=3)


if __name__=='__main__' and '--accessibility' in sys.argv:assistive()
