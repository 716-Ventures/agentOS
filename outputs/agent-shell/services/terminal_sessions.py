"""Bounded live PTY transport. Called under the broker's lock."""
import base64
import binascii
import fcntl
import os
import signal
import struct
import termios
import time
import uuid

LIMIT = 256 * 1024
SESSIONS = {}


def dimensions(rows, cols):
    if type(rows) is not int or type(cols) is not int or not (1 <= rows <= 500 and 1 <= cols <= 1000):
        raise ValueError('Terminal size must be 1–500 rows and 1–1000 columns')
    return struct.pack('HHHH', rows, cols, 0, 0)


def register(ident, master, proc):
    # Retain a bounded tail for recently finished sessions as well as live work.
    finished = [k for k, v in SESSIONS.items() if v['fd'] is None]
    for key in finished[:-32]:
        del SESSIONS[key]
    os.set_blocking(master, False)
    SESSIONS[ident] = dict(fd=master, proc=proc, data=b'', end=0, token=None, expires=0)


def append(ident, data):
    session = SESSIONS[ident]
    session['data'] = (session['data'] + data)[-LIMIT:]
    session['end'] += len(data)


def finish(ident):
    session = SESSIONS.get(ident)
    if session and session['fd'] is not None:
        os.close(session['fd'])
        session['fd'] = None
    finished = [k for k, v in SESSIONS.items() if v['fd'] is None]
    for key in finished[:-32]:
        del SESSIONS[key]


def control(ident, req):
    session = SESSIONS.get(ident)
    if session is None:
        raise ValueError('Terminal transport is unavailable; inspect the saved job output')
    now = time.monotonic()
    op = req['op']
    if op == 'terminal_attach':
        if session['token'] and session['expires'] > now:
            raise ValueError('This terminal already has an input controller; detach it or wait 15 seconds after disconnect')
        session.update(token=uuid.uuid4().hex, expires=now + 15)
        return {'token': session['token']}
    if not session['token'] or req.get('token') != session['token'] or session['expires'] <= now:
        raise ValueError('Terminal attachment expired; attach again')
    session['expires'] = now + 15
    if op == 'terminal_detach':
        session.update(token=None, expires=0)
        return {'detached': True}
    if op == 'terminal_read':
        cursor = req.get('cursor', 0)
        if type(cursor) is not int or not 0 <= cursor <= session['end']:
            raise ValueError('Invalid terminal cursor')
        base = session['end'] - len(session['data'])
        start = max(base, cursor)
        data = session['data'][start-base:start-base+16384]
        return dict(data=base64.b64encode(data).decode(), cursor=start+len(data),
                    dropped=cursor < base, closed=session['fd'] is None)
    if session['fd'] is None:
        raise ValueError('Terminal has exited')
    if op == 'terminal_resize':
        size = dimensions(req.get('rows'), req.get('cols'))
        fcntl.ioctl(session['fd'], termios.TIOCSWINSZ, size)
        # systemd-run forwards this size to the command's controlling terminal.
        os.kill(session['proc'].pid, signal.SIGWINCH)
        return {'resized': True}
    if op == 'terminal_write':
        try:
            encoded = req.get('data')
            if not isinstance(encoded, str) or len(encoded) > 5500:
                raise ValueError('Terminal input exceeds 4096 bytes')
            data = base64.b64decode(encoded, validate=True)
            if len(data) > 4096:
                raise ValueError('Terminal input exceeds 4096 bytes')
        except (binascii.Error, UnicodeError):
            raise ValueError('Terminal input must be base64') from None
        try:
            written = os.write(session['fd'], data)
        except BlockingIOError:
            written = 0
        return {'written': written}
    raise ValueError('Unknown terminal operation')
