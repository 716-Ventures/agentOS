"""Real GTK text-input-v3 composition through the private test helper."""
import json
import socket
import pyatspi
import accessibility


def verify(call, endpoint):
    def method(op, text=None):
        request = {'op': op}
        if text is not None:
            request['text'] = text
        with socket.socket(socket.AF_UNIX) as conn:
            conn.settimeout(3)
            conn.connect(str(endpoint))
            conn.sendall(json.dumps(request).encode() + b'\n')
            with conn.makefile('rb') as stream:
                result = json.loads(stream.readline(4096))
        assert result['ok'], result
        return result
    field = accessibility.find('Accessible session draft', pyatspi.ROLE_TEXT)
    assert field.queryEditableText().setTextContents('')
    def draft():
        return call({'op': 'draft.get', 'surface_id': 'session-fixture', 'element_id': 'field'}).get('draft')
    accessibility.wait(lambda: draft() == '', 'Initial local draft did not reach core')
    assert field.queryComponent().grabFocus(), 'Editor could not acquire keyboard focus'
    accessibility.wait(lambda: method('status')['active'], 'GTK did not activate the input method')
    method('preedit', 'にほん')
    assert draft() == '', 'Uncommitted composition entered the durable draft'
    document = call({'op': 'presentation.snapshot'})['documents']['session-fixture']
    call({'op': 'presentation.apply', 'protocol': 'agentos.presentation/1', 'catalog_revision': 'native-core/1',
          'request_id': 'ime-concurrent-status', 'expected_revisions': {'session-fixture': document['revision']},
          'operations': [{'op': 'element.set_props', 'surface_id': 'session-fixture', 'element_id': 'reading',
                          'props': {'text': 'Unrelated update during composition'}}]})
    # Wait for the actual renderer to consume the update, not just core acceptance.
    accessibility.find('Unrelated update during composition', pyatspi.ROLE_LABEL)
    assert method('status')['active'], 'Unrelated update ended editor composition/focus'
    assert draft() == '', 'Unrelated update committed or erased composition'
    value = '日本語 λ'
    method('commit', value)
    accessibility.wait(lambda: draft() == value and accessibility.text(field) == value,
                       'GTK composition did not become the exact local Unicode draft')
    current = call({'op': 'presentation.snapshot'})['documents']['session-fixture']['elements']['field']['props']['value']
    assert current == 'Original accessible value', 'IME commit bypassed deliberate Save'
    accessibility.activate(accessibility.find('Save draft', pyatspi.ROLE_PUSH_BUTTON))
    accessibility.wait(lambda: call({'op': 'presentation.snapshot'})['documents']['session-fixture']['elements']['field']['props']['value'] == value,
                       'Deliberate Save did not commit composed Unicode text')
    print('PASS: GTK text-input-v3 Unicode preedit/commit survives unrelated rendering; draft and Save remain distinct')
