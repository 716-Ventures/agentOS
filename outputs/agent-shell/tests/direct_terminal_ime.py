#!/usr/bin/python3
"""Installed VTE through a real trusted Wayland protocol fixture, not a language engine."""
import json
import socket
import uuid


def verify(endpoint, surface, output, presentation, observe, keyboard, wait):
    wait(endpoint.exists, 'Private input-method fixture did not start')

    def method(op, text=None):
        value={'op':op}
        if text is not None:value['text']=text
        with socket.socket(socket.AF_UNIX) as conn:
            conn.settimeout(3);conn.connect(str(endpoint))
            conn.sendall(json.dumps(value).encode()+b'\n')
            with conn.makefile('rb') as reader:line=reader.readline(4097)
        if len(line)>4096 or not line.endswith(b'\n'):
            raise RuntimeError('Incomplete or oversized input-method response')
        response=json.loads(line)
        if not response.get('ok'):raise RuntimeError('Input-method fixture rejected '+op)
        return response

    def update(label):
        document=presentation({'op':'presentation.get','document_id':surface})
        result=presentation({'op':'presentation.apply','protocol':'agentos.presentation/1',
            'catalog_revision':'native-core/1','request_id':'terminal-ime-'+uuid.uuid4().hex,
            'expected_revisions':{surface:document['revision']},
            'operations':[{'op':'element.set_props','surface_id':surface,'element_id':'ime-status','props':{'text':label}}]})
        assert result['status']=='committed',result
        wait(lambda:observe('terminal:ime-status:'+label)['rendered'], 'Unrelated terminal status was not rendered')

    wait(lambda:method('status')['active'],'VTE did not activate Wayland text input')
    before=output()
    method('preedit','にほん')
    update('IME unrelated update')
    assert method('status')['active'],'Unrelated rendering ended terminal composition'
    assert output()==before,'Uncommitted IME preedit entered the PTY'
    method('commit','日本語 λ')
    wait(lambda:'日本語 λ' in output(),'VTE did not echo the exact Unicode IME commit')
    assert 'にほん' not in output(),'Preedit was sent as program input'
    keyboard.chord(28)
    wait(lambda:'KERNEL_VTE_ACK 日本語 λ' in output(),'Composed Unicode did not reach the installed program')

    method('preedit','未確定')
    before=output()
    assert observe('terminal:detach')['requested']
    wait(lambda:observe('terminal:attach-state')['sensitive'],'Terminal did not detach during composition')
    # Some VTE versions deactivate text input; otherwise an IME commit must
    # still encounter the host's detached-session input guard.
    if method('status')['active']:method('commit','DETACHED_IME_COMMIT')
    update('IME detached update')
    assert output()==before,'IME input reached the program while detached'
    assert observe('terminal:attach')['requested']
    wait(lambda:observe('terminal:status')['attached'],'Terminal did not explicitly reattach')
    update('IME reattached update')
    assert output()==before,'Reattachment replayed a pending IME commit'
    print('PASS: installed VTE Wayland IME preedit/Unicode commit, concurrent native rendering, detached-input rejection and no reattach replay',flush=True)
