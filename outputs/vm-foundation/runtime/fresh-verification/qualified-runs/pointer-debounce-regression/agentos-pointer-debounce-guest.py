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
results=[]
for gap in (0,.04):
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
  results.append({'release_to_next_press_gap_seconds':gap+.005,'libinput_button_states':events,'presses':events.count(1),'releases':events.count(0)})
 finally:
  if ctx:lib.libinput_unref(ctx)
  d.close()
print(json.dumps({'cases':results}))
assert results[0]['presses']==1 and results[1]['presses']==2,results
