import ctypes as c,os,time,select,json,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/home/developer/agent-os-source/tests');from direct_input_probe import Device
lib=c.CDLL('libinput.so.10');OPEN=c.CFUNCTYPE(c.c_int,c.c_char_p,c.c_int,c.c_void_p);CLOSE=c.CFUNCTYPE(None,c.c_int,c.c_void_p)
@OPEN
def opened(p,f,u):
 try:return os.open(p,f)
 except OSError as e:return -e.errno
@CLOSE
def closed(fd,u):os.close(fd)
class Interface(c.Structure):_fields_=[('open_restricted',OPEN),('close_restricted',CLOSE)]
interface=Interface(opened,closed)
for name,args,restype in [('libinput_path_create_context',[c.POINTER(Interface),c.c_void_p],c.c_void_p),('libinput_path_add_device',[c.c_void_p,c.c_char_p],c.c_void_p),('libinput_get_fd',[c.c_void_p],c.c_int),('libinput_dispatch',[c.c_void_p],c.c_int),('libinput_get_event',[c.c_void_p],c.c_void_p),('libinput_event_get_type',[c.c_void_p],c.c_int),('libinput_event_get_pointer_event',[c.c_void_p],c.c_void_p),('libinput_event_pointer_get_button_state',[c.c_void_p],c.c_int),('libinput_event_destroy',[c.c_void_p],None),('libinput_unref',[c.c_void_p],c.c_void_p)]:
 fn=getattr(lib,name);fn.argtypes=args;fn.restype=restype
old_device=Device
results=[]
for gap,patched in ((0,False),(.04,False),(0,True)):
 if patched:
  import direct_input_probe
  namespace=dict(vars(direct_input_probe));exec("class Device:\n    def __init__(self,keyboard,motion_ready=None):\n        self.motion_ready=motion_ready\n        self.last_click=None\n        self.last_pointer_release=None\n        self.fd=os.open('/dev/uinput',os.O_WRONLY|os.O_NONBLOCK)\n        try:\n            fcntl.ioctl(self.fd,0x40045564,1) # UI_SET_EVBIT EV_KEY\n            if keyboard:\n                for key in range(1,249):fcntl.ioctl(self.fd,0x40045565,key)\n            else:\n                for key in (272,273,274):fcntl.ioctl(self.fd,0x40045565,key)\n                fcntl.ioctl(self.fd,0x40045564,2) # EV_REL scroll, with absolute pointer motion\n                for axis in (6,8):fcntl.ioctl(self.fd,0x40045566,axis) # HWHEEL, WHEEL\n                fcntl.ioctl(self.fd,0x40045564,3) # EV_ABS\n                for axis in (0,1):\n                    fcntl.ioctl(self.fd,0x40045567,axis) # UI_SET_ABSBIT\n                    fcntl.ioctl(self.fd,0x401c5504,struct.pack('H2xiiiiii',axis,0,0,65535,0,0,0))\n            name=('agentOS verification keyboard' if keyboard else 'agentOS verification pointer').encode()\n            fcntl.ioctl(self.fd,0x405c5503,struct.pack('HHHH80sI',3,0x1209,0x716,1,name,0))\n            fcntl.ioctl(self.fd,0x5501) # UI_DEV_CREATE\n        except BaseException:\n            os.close(self.fd);raise\n    def event(self,kind,code,value):\n        os.write(self.fd,struct.pack('llHHi',0,0,kind,code,value))\n    def sync(self):self.event(0,0,0)\n    def chord(self,*keys):\n        for key in keys:self.event(1,key,1);self.sync()\n        for key in reversed(keys):self.event(1,key,0);self.sync()\n    def click(self,x,y,width,height,button=272):\n        self.last_click={'x':x,'y':y,'button':button}\n        self.event(3,0,round(x*65535/width));self.event(3,1,round(y*65535/height));self.sync()\n        if self.motion_ready:self.motion_ready(x,y)\n        else:time.sleep(.1)\n        # libinput debounces switch bounce. Motion acknowledgement can be\n        # faster than that interval; adjacent zero-duration test clicks would\n        # otherwise collapse into one physical press/release.\n        if self.last_pointer_release is not None:\n            remaining=.04-(time.monotonic()-self.last_pointer_release)\n            if remaining>0:time.sleep(remaining)\n        self.chord(button)\n        self.last_pointer_release=time.monotonic()\n    def drag(self,start,end,width,height,observe=None):\n        def move(x,y):\n            self.event(3,0,round(x*65535/width));self.event(3,1,round(y*65535/height));self.sync()\n        move(*start);time.sleep(.1)\n        self.event(1,272,1);self.sync()\n        try:\n            for step in range(1,11):\n                move(*(start[axis]+(end[axis]-start[axis])*step/10 for axis in (0,1)))\n                time.sleep(.04)\n                if step==5 and observe:observe()\n        finally:self.event(1,272,0);self.sync()\n    def close(self):\n        try:fcntl.ioctl(self.fd,0x5502)\n        finally:os.close(self.fd)",namespace);Device=namespace["Device"]
 d=Device(False,lambda x,y:None);ctx=None
 try:
  subprocess.run(['udevadm','settle','--timeout=5'],check=True)
  nodes=[p for p in Path('/sys/class/input').glob('event*') if (p/'device/name').read_text().strip()=='agentOS verification pointer'];assert len(nodes)==1
  ctx=lib.libinput_path_create_context(c.byref(interface),None);assert ctx
  assert lib.libinput_path_add_device(ctx,('/dev/input/'+nodes[0].name).encode())
  fd=lib.libinput_get_fd(ctx);events=[]
  def drain(duration):
   end=time.monotonic()+duration
   while time.monotonic()<end:
    lib.libinput_dispatch(ctx)
    while True:
     e=lib.libinput_get_event(ctx)
     if not e:break
     if lib.libinput_event_get_type(e)==402:events.append(lib.libinput_event_pointer_get_button_state(lib.libinput_event_get_pointer_event(e)))
     lib.libinput_event_destroy(e)
    select.select([fd],[],[],min(.002,max(0,end-time.monotonic())))
  drain(.1)
  d.click(100,100,1280,800);drain(.005+gap)
  d.click(116,196,1280,800);drain(.15)
  results.append({'requested_gap_seconds':gap+.005,'patched_device':patched,'libinput_button_states':events,'presses':events.count(1),'releases':events.count(0)})
 finally:
  if ctx:lib.libinput_unref(ctx)
  d.close()
print(json.dumps({'cases':results}))
assert results[0]['presses']==1 and results[1]['presses']==2 and results[2]['presses']==2,results
