"""Real GTK text-input-v3 composition through the private test helper."""
import json
import socket
import pyatspi
import accessibility


def verify(call, endpoint, editor=False, observation=None):
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
    if editor:
        bounded='x'*65536
        assert field.queryEditableText().setTextContents(bounded)
        accessibility.wait(lambda:draft()==bounded,'Maximum-sized editor draft did not reach core')
        # GTK's AT-SPI selection setters are unsupported on the tested versions.
        # The explicit native fixture selects this range once through public
        # GTK APIs; AT-SPI independently observes it and the later restoration.
        accessibility.wait(lambda:field.queryText().getNSelections()==1 and field.queryText().getSelection(0)==(0,3),
                           'Native editor fixture did not select its bounded replacement')
        method('preedit','にほん')
        # A protocol roundtrip does not guarantee GTK processed preedit.
        # GTK 4.14 deletes the selection at preedit-start; 4.18 retains it.
        accessibility.wait(lambda:observation.exists() and json.loads(observation.read_text())['preedit_bytes']==len('にほん'.encode()),
                           'GTK did not process selected preedit before commit')
        method('commit','日本語 λ')
        # Observe the rejection, so unchanged text before GTK receives the
        # commit cannot accidentally satisfy the preservation assertion.
        try:accessibility.find('Document text is limited to 64 KiB; this insertion was not applied',pyatspi.ROLE_LABEL)
        except AssertionError:
            print('Overflow diagnostic:',len(accessibility.text(field).encode()),len((draft() or '').encode()),method('status'),field.queryText().getNSelections(),flush=True)
            raise
        accessibility.wait(lambda:draft()==bounded and accessibility.text(field)==bounded,
                           'Rejected IME replacement deleted selected document text')
        assert field.queryText().getSelection(0)==(0,3),'Rejected IME replacement lost its selection'
        saved=call({'op':'presentation.get','document_id':'session-fixture'})['elements']['field']['props']['value']
        assert saved==value,'Rejected IME replacement committed a document change'
        print('PASS: actual GTK text-input-v3 editor overflow preserves selected text, exact durable draft and committed value')
    print('PASS: GTK text-input-v3 Unicode preedit/commit survives unrelated rendering; draft and Save remain distinct')
