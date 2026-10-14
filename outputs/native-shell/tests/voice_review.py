"""Private synthetic voice transport; never opens a microphone or a provider."""
import json
import socket
import threading
import time
from collections import deque
import pyatspi
import accessibility


class Fixture:
    def __init__(self, root):
        self.fail = True
        self.calls = []
        self.stop = threading.Event()
        self.sockets = []
        self.threads = []
        self.env = {}
        for variable, name in [('AGENT_OS_VOICE_SOCKET', 'voice.sock'), ('AGENT_OS_BROKER_SOCKET', 'voice-broker.sock')]:
            path = root / name
            server = socket.socket(socket.AF_UNIX)
            server.bind(str(path));server.listen(4);server.settimeout(.1)
            self.sockets.append(server)
            self.env[variable] = str(path)
            worker = threading.Thread(target=self.serve, args=(server,), daemon=True)
            worker.start();self.threads.append(worker)

    def serve(self, server):
        while not self.stop.is_set():
            try: connection, _ = server.accept()
            except socket.timeout: continue
            with connection:
                connection.settimeout(2)
                with connection.makefile('rb') as stream:
                    request = json.loads(stream.readline(16384))
                operation = request.get('op')
                self.calls.append(operation)
                if operation == 'capture.start' and self.fail:
                    reply = {'ok': False, 'error': 'Microphone unavailable in verification fixture.'}
                elif operation == 'capture.start':
                    reply = {'ok': True, 'result': {'token': 'private-verification-token'}}
                elif operation == 'capture.finish':
                    reply = {'ok': True, 'result': {'text': 'Review this transcript λ 日本語'}}
                elif operation == 'cancel':
                    reply = {'ok': True, 'result': {}}
                elif operation == 'activity_state':
                    reply = {'ok': True, 'result': {'generation': 1}}
                elif operation == 'list.page':
                    reply = {'ok': True, 'result': {'revision': 'voice-verification:0', 'jobs': [], 'next_before': None}}
                else:
                    reply = {'ok': False, 'error': 'Unexpected verification operation'}
                connection.sendall(json.dumps(reply).encode() + b'\n')

    def close(self):
        self.stop.set()
        for worker in self.threads: worker.join(timeout=3)
        for server in self.sockets: server.close()
        assert not any(worker.is_alive() for worker in self.threads), 'Voice fixture leaked a worker'


def verify(fixture, scene, output):
    def activate(name, root=None):
        target = accessibility.find(name, pyatspi.ROLE_PUSH_BUTTON, root=root)
        accessibility.wait(lambda:target.getState().contains(pyatspi.STATE_SENSITIVE), 'Voice action is disabled: '+name)
        accessibility.activate(target)

    def review(title):
        def focused():
            state = scene()
            return any(w['app_id']=='agentos.voice-review' and w['id']==state['seat_focus'] for w in state['windows']) and not any(layer['namespace']=='agentos-launcher' and layer['mapped'] for layer in state['system_layers'])
        accessibility.wait(focused, 'Voice review did not receive committed focus and dismiss launcher')
        frame = accessibility.find(title, pyatspi.ROLE_FRAME)
        accessibility.wait(lambda:frame.getState().contains(pyatspi.STATE_ACTIVE), 'Voice review is not active in GTK')
        window = next(w for w in scene()['windows'] if w['app_id']=='agentos.voice-review')
        assert window['geometry']['height']>=window['xdg']['client_min_size'][1], 'Voice review ignores its readable minimum height'
        keyboard = next((layer for layer in scene()['system_layers'] if layer['namespace']=='agentos-keyboard' and layer['mapped']), None)
        if keyboard:
            work=keyboard['work_area'];geometry=window['geometry']
            assert geometry['x']>=work['x'] and geometry['y']>=work['y'] and geometry['x']+geometry['width']<=work['x']+work['width'] and geometry['y']+geometry['height']<=work['y']+work['height'], ('Voice review overlaps the on-screen keyboard',geometry,work)
        for name in ['Dismiss'] if fixture.fail else ['Discard', 'Send request']:
            action = accessibility.find(name, pyatspi.ROLE_PUSH_BUTTON, root=frame)
            assert not action.parent.getState().contains(pyatspi.STATE_FOCUSABLE), 'Voice layout adds a tab stop'
            box = action.parent.queryComponent().getExtents(pyatspi.WINDOW_COORDS)
            origin = frame.queryComponent().getExtents(pyatspi.WINDOW_COORDS)
            assert box.x>=origin.x and box.y>=origin.y and box.x+box.width<=origin.x+window['geometry']['width'] and box.y+box.height<=origin.y+window['geometry']['height'], ('Voice action outside viewport', name, box, window)
        return frame

    def launcher_returned():
        accessibility.wait(lambda:any(layer['namespace']=='agentos-launcher' and layer['mapped'] for layer in scene()['system_layers']), 'Discard did not return to the launcher')
        field=accessibility.find('Ask Agent',pyatspi.ROLE_TEXT)
        accessibility.wait(lambda:field.getState().contains(pyatspi.STATE_FOCUSED), 'Returned launcher did not restore typing focus')
        assert accessibility.text(field)=='Keep this unsent voice companion draft λ'

    entry = accessibility.find('Ask Agent', pyatspi.ROLE_TEXT)
    entry.queryEditableText().setTextContents('Keep this unsent voice companion draft λ')
    activate('Record voice')
    frame = review('Voice recording failed')
    minimum = next(w['xdg']['client_min_size'] for w in scene()['windows'] if w['app_id']=='agentos.voice-review')
    queue = deque([frame]);labels = []
    while queue:
        node = queue.popleft()
        if node is None: continue
        labels.append(node.name)
        queue.extend(node[i] for i in range(min(node.childCount,32)))
    assert any('Voice recording failed.' in name and 'Setup' in name for name in labels), labels
    assert 'Send request' not in labels, 'Failure exposes transcript submission'
    accessibility.wait(lambda:(output/'voice-error.png').exists(), 'Voice error capture missing')
    details=accessibility.find('Details',None,root=frame)
    accessibility.activate(details)
    accessibility.find('Microphone unavailable in verification fixture.',pyatspi.ROLE_LABEL,root=frame)
    accessibility.activate(details)
    time.sleep(.2)
    activate('Dismiss', frame)
    accessibility.wait(lambda:not any(w['app_id']=='agentos.voice-review' for w in scene()['windows']), 'Dismiss did not close voice failure')
    fixture.fail = False
    launcher_returned()
    activate('Record voice');activate('Finish recording')
    frame = review('Review voice request')
    transcript = accessibility.find('Transcript', pyatspi.ROLE_TEXT, root=frame)
    assert accessibility.text(transcript)=='Review this transcript λ 日本語'
    assert transcript.getState().contains(pyatspi.STATE_FOCUSED), 'Transcript did not receive editing focus'
    accessibility.wait(lambda:(output/'voice-transcript.png').exists(), 'Voice transcript capture missing')
    viewport = accessibility.find('Voice review content', None, root=frame)
    print('Voice viewport allocations',list(transcript.queryComponent().getExtents(pyatspi.WINDOW_COORDS)),list(viewport.queryComponent().getExtents(pyatspi.WINDOW_COORDS)),flush=True)
    def visible_transcript():
        # GTK's AT-SPI text bridge lacks GetCharacterExtents on supported
        # releases. Check the real editable field's central text band instead;
        # padded entry border bounds can extend beyond the viewport by padding.
        field = transcript.queryComponent().getExtents(pyatspi.WINDOW_COORDS)
        box = viewport.queryComponent().getExtents(pyatspi.WINDOW_COORDS)
        visible_height = min(field.y+field.height,box.y+box.height)-max(field.y,box.y)
        return field.width>0 and field.height>0 and box.x<=field.x+field.width/2<=box.x+box.width and box.y<=field.y+field.height/2<=box.y+box.height and visible_height>=min(field.height*.65,40)
    accessibility.wait(visible_transcript, 'Focused transcript remains outside the scrolling viewport')
    import ime_accessibility
    activate('Keyboard')
    review('Review voice request')
    for name in ['Ctrl','a','Ctrl on','a']:
        activate(name)
        accessibility.wait(lambda:ime_accessibility.rendered_text('Keyboard ready'), 'Voice review keyboard stroke did not finish')
    accessibility.wait(lambda:accessibility.text(transcript)=='a', 'Trusted keyboard did not edit the focused transcript')
    accessibility.wait(visible_transcript, 'On-screen keyboard hides the focused transcript')
    (output/'voice-keyboard-scene.json').write_text(json.dumps(scene(),indent=2)+'\n')
    activate('Hide keyboard')
    transcript.queryEditableText().setTextContents('   ')
    send = accessibility.find('Send request', pyatspi.ROLE_PUSH_BUTTON, root=frame)
    accessibility.wait(lambda:not send.getState().contains(pyatspi.STATE_SENSITIVE), 'Empty transcript can be submitted')
    transcript.queryEditableText().setTextContents('λ'*4000)
    accessibility.wait(lambda:send.getState().contains(pyatspi.STATE_SENSITIVE), 'Valid Unicode character limit is treated as a byte limit')
    oversized='λ'*4001
    transcript.queryEditableText().setTextContents(oversized)
    accessibility.wait(lambda:not send.getState().contains(pyatspi.STATE_SENSITIVE), 'Oversized transcript can be submitted')
    assert accessibility.text(transcript)==oversized, 'Oversized edit was silently truncated'
    transcript.queryEditableText().setTextContents('Edited transcript λ 日本語')
    accessibility.wait(lambda:send.getState().contains(pyatspi.STATE_SENSITIVE), 'Edited transcript cannot be reviewed')
    accessibility.wait(lambda:(output/'voice-transcript.png').exists(), 'Voice transcript capture missing')
    activate('Discard', frame)
    accessibility.wait(lambda:fixture.calls.count('cancel')==1, 'Discard did not cancel its exact capture')
    launcher_returned()
    assert fixture.calls.count('capture.start')==2 and fixture.calls.count('capture.finish')==1, fixture.calls
    assert set(fixture.calls)<={'activity_state','capture.start','capture.finish','cancel','list.page'}, fixture.calls
    activate('Close launcher')
    print('PASS: synthetic voice failure recovery and editable Unicode transcript receive native focus; field/actions fit above keyboard; blank/oversized Send is disabled; discard cancels only its capture and returns to unsent typing', flush=True)
    return {'width':max(700,minimum[0]),'height':max(220,minimum[1])}
