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
    accessibility.wait(lambda: method('status')['active'], 'GTK did not activate the input method')
    method('preedit', 'にほん')
    assert draft() == '', 'Uncommitted composition entered the durable draft'
    document = call({'op': 'presentation.snapshot'})['documents']['session-fixture']
    updated=call({'op': 'presentation.apply', 'protocol': 'agentos.presentation/1', 'catalog_revision': 'native-core/1',
          'request_id': 'ime-concurrent-status', 'expected_revisions': {'session-fixture': document['revision']},
          'operations': [{'op': 'element.set_props', 'surface_id': 'session-fixture', 'element_id': 'reading',
                          'props': {'value': 'Unrelated update during composition'}}]})
    assert updated['status']=='committed',updated
    # Wait for the actual renderer to consume the update, not just core acceptance.
    def rendered_status():
        from collections import deque
        queue=deque([pyatspi.Registry.getDesktop(0)])
        for _ in range(2048):
            if not queue:break
            node=queue.popleft()
            try:
                if accessibility.text(node)=='Unrelated update during composition':return True
            except (NotImplementedError,RuntimeError,LookupError):pass
            try:queue.extend(node[index] for index in range(min(node.childCount,128)))
            except (RuntimeError,LookupError):pass
        return False
    try:accessibility.wait(rendered_status,'Unrelated status was not rendered during composition')
    except AssertionError:
        print('Current composition document:',call({'op':'presentation.get','document_id':'session-fixture'}),flush=True)
        from collections import deque
        queue=deque([pyatspi.Registry.getDesktop(0)])
        for _ in range(256):
            if not queue:break
            node=queue.popleft()
            try:
                print('IME accessible:',node.getRoleName(),repr(node.name),flush=True)
                queue.extend(node[index] for index in range(min(node.childCount,128)))
            except (RuntimeError,LookupError):pass
        raise
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
