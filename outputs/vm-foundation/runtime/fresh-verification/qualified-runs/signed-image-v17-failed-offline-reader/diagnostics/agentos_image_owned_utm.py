"""Exact shared UTM ownership for serial image qualification subprocesses."""
import json, os, subprocess
from pathlib import Path
import vm

record=Path(os.environ['AGENT_OS_IMAGE_OWNERSHIP'])
if not record.exists():
    assert vm.utm_application_identity() is None, 'UTM was already open; it is not owned by this image driver'
    with record.open('x') as stream:stream.write('null\n')

def identity():
    value=json.loads(record.read_text())
    return tuple(value) if value else None

def write(value):
    temporary=record.with_suffix('.tmp')
    temporary.write_text(json.dumps(value)+'\n');temporary.replace(record)

assert vm.utm_application_identity()==identity(), 'UTM identity differs from the driver ownership record'
controller_path=str(vm.controller())
original_run=subprocess.run

def run(args,*positional,**kwargs):
    if not isinstance(args,(tuple,list)) or not args or str(args[0])!=controller_path:
        return original_run(args,*positional,**kwargs)
    before=vm.utm_application_identity()
    assert before is None or before==identity(), 'Refusing to operate an unowned UTM application'
    try:return original_run(args,*positional,**kwargs)
    finally:
        if before is None:
            after=vm.utm_application_identity()
            if after is not None:write(after)

subprocess.run=run

def close():
    current=vm.utm_application_identity();expected=identity()
    if current is None:write(None);return
    assert expected is not None and current==expected, 'Refusing to close an unowned UTM application'
    assert vm.close_owned_utm_application(expected), 'Owned UTM exit not verified'
    write(None)
    print('Exact owned UTM application exit verified',flush=True)
