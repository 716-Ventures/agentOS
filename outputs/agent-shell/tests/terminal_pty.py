import atexit,signal,codecs,os,sys,pty,fcntl,termios,struct,subprocess,time,select,json
from pathlib import Path
import pyte
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT.parent.parent)
sys.path.insert(0,str(ROOT.parent/'vm-foundation'));import vm
decoder=codecs.getincrementaldecoder('utf-8')('replace')
master,slave=pty.openpty()
def size(w,h):
 fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',h,w,0,0))
 if 'process' in globals():os.kill(process.pid,signal.SIGWINCH)
size(140,40)
screen=pyte.Screen(140,40);stream=pyte.Stream(screen)
args=vm.ssh_args();process=subprocess.Popen(args[:-1]+['-tt']+args[-1:]+['exec env TERM=xterm-256color agent-os'],stdin=slave,stdout=slave,stderr=slave)
def cleanup():
 if process.poll() is None:
  process.terminate()
  try:process.wait(timeout=2)
  except subprocess.TimeoutExpired:process.kill()
 os.close(master);os.close(slave)
atexit.register(cleanup)

def pump(seconds=.8):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  if select.select([master],[],[],.1)[0]:
   try:data=os.read(master,65536)
   except OSError:break
   stream.feed(decoder.decode(data))
def keys(text,seconds=.8):os.write(master,text.encode());pump(seconds)
def capture(name):
 font=ImageFont.truetype('/System/Library/Fonts/Menlo.ttc',15)
 cw=round(font.getlength('M'));ch=22
 image=Image.new('RGB',(screen.columns*cw,screen.lines*ch),'#121212');draw=ImageDraw.Draw(image)
 colors={'default':'d0d0d0','black':'000000','red':'cd0000','green':'00cd00','brown':'cdcd00','blue':'0000ee','magenta':'cd00cd','cyan':'00cdcd','white':'e5e5e5'}
 for y in range(screen.lines):
  for x in range(screen.columns):
   c=screen.buffer[y][x];fg=colors.get(c.fg,c.fg);bg='121212' if c.bg=='default' else colors.get(c.bg,c.bg)
   if c.reverse:fg,bg=bg,fg
   draw.rectangle((x*cw,y*ch,(x+1)*cw,(y+1)*ch),fill='#'+bg)
   if c.data:draw.text((x*cw,y*ch),c.data,font=font,fill='#'+fg)
 image.save('outputs/agent-shell/'+name+'.png')
 Path('outputs/agent-shell/'+name+'.txt').write_text('\n'.join(screen.display))
pump()
keys('nTerminal design verification\n')
keys('r/usr/bin/uname -a\n',1.2)
keys('v');keys('r/bin/df -h /\n',1.2)
keys('s');keys('r/bin/cat /etc/os-release\n',1.2)
capture('terminal-tiles')
assert any('PRETTY_NAME=' in line for line in screen.display), '\n'.join(screen.display)
keys('z');capture('terminal-focused');keys('z')
keys('+');keys('m');keys('u')
size(50,24);screen.resize(24,50);pump(1);capture('terminal-compact')
assert any('Compact view' in line for line in screen.display)
size(140,40);screen.resize(40,140);pump(1)
keys('T');capture('terminal-light');keys('T');keys(' ');capture('terminal-actions');keys('\x1b')
keys('a'+('A long editable question about this system. '*8)+'你好');capture('terminal-input');keys('\x1b')
keys('w');keys('u')
keys('q');process.wait(timeout=10)
process=subprocess.Popen(args[:-1]+['-tt']+args[-1:]+['exec env TERM=xterm-256color agent-os'],stdin=slave,stdout=slave,stderr=slave)
pump(1.5);capture('terminal-restored')
assert any('uname' in line for line in screen.display)
assert any('os-release' in line for line in screen.display)
keys('q');process.wait(timeout=10)
print(json.dumps({'pty_actions':'created activity, executed real commands, split both axes, zoomed/restored, resized, swapped/undid, opened actions, resized terminal, quit','passed':True}))
