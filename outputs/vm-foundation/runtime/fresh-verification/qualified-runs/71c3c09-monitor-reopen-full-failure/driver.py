import os,sys,runpy
from pathlib import Path
os.environ['AGENT_OS_VM_RUNTIME']='outputs/vm-foundation/runtime/fresh-verification'
os.environ['AGENT_OS_VM_SSH_PORT']='22221'
os.environ['AGENT_OS_IMAGE_OWNERSHIP']='/tmp/agentos-monitor-reopen-full70-ownership.json'
sys.path.insert(0,'outputs/vm-foundation')
import vm
import agentos_image_owned_utm as ownership
original_close=vm.close_owned_utm_application
def guarded_close(identity):
    if identity != ownership.identity():
        raise RuntimeError('Refusing reproduction cleanup of an unowned UTM identity')
    result=original_close(identity)
    if result:ownership.write(None)
    return result
vm.close_owned_utm_application=guarded_close
sys.argv=['outputs/vm-foundation/reproduce.py','--runtime','outputs/vm-foundation/runtime/fresh-verification','--ssh-port','22221']
try:
    runpy.run_path(sys.argv[0],run_name='__main__')
finally:
    ownership.close()
    assert vm.utm_application_identity() is None
