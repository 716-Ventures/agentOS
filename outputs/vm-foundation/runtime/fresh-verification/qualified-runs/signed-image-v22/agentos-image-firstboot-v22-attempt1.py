import os,sys,tty,select,time,secrets,termios
from pathlib import Path
sys.path.insert(0,'outputs/vm-foundation');import vm
import agentos_image_owned_utm as ownership
end=time.monotonic()+30
while True:
 try:
  r=vm.call([vm.controller(),'attach',vm.machine()['uuid']],capture_output=True,text=True)
  p=[x.split(':',1)[1].strip() for x in r.stdout.splitlines() if x.startswith('PTTY:')][0]
  fd=os.open(p,os.O_RDWR|os.O_NOCTTY);tty.setraw(fd);break
 except (OSError,IndexError):
  if time.monotonic()>end:raise
  time.sleep(.25)
password=secrets.token_urlsafe(24)
credential=Path('outputs/vm-foundation/runtime/release-artifacts/verification-password-v22-attempt1')
f=os.open(credential,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.write(f,password.encode());os.close(f)
carry=b''
def wait(token,timeout=120):
 global carry
 data=carry;end=time.monotonic()+timeout;needle=token.encode()
 while needle not in data:
  if time.monotonic()>end: raise RuntimeError('Timeout '+token+' '+repr(data[-4000:].decode(errors='replace').replace(password,'[REDACTED]')))
  if select.select([fd],[],[],1)[0]: data+=os.read(fd,65536)
 consumed=data.index(needle)+len(needle);carry=data[consumed:]
 print(data[:consumed].decode(errors='replace').replace(password,'[REDACTED]'),flush=True)
 return data[:consumed]
def send(value):os.write(fd,(value+'\n').encode())
send('');wait('Choose your login name:')
send('verifier');wait('Choose a password')
send(password);wait('Confirm password:');send(password)
wait('Setup complete.',300);wait('login:');send('verifier');wait('Password:');send(password)
wait('verifier@');send('sudo -i');wait('password for verifier:');send(password);wait('root@')
# Test-only SSH access is added after proving the local setup path.
key=Path('outputs/vm-foundation/runtime/fresh-verification/id_ed25519.pub').read_text().strip()
cmd="ssh-keygen -A >/dev/null; install -d -m 700 -o verifier -g verifier /home/verifier/.ssh; printf '%s\\n' '"+key+"' > /home/verifier/.ssh/authorized_keys; chmod 600 /home/verifier/.ssh/authorized_keys; chown verifier:verifier /home/verifier/.ssh/authorized_keys; systemctl start ssh; systemctl is-active agent-os-core agent-os-broker; cat /var/lib/agent-os-image/ready; printf 'FIRSTBOOT_%s\\n' VERIFIED"
send(cmd);wait('FIRSTBOOT_VERIFIED\r\n');os.close(fd)
