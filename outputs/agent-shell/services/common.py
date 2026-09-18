"""Small bounded JSON protocol shared by trusted local services."""
import json
import os
import socket

LIMIT = 512 * 1024
AI_SOCKET = '/run/agent-os-ai/api.sock'
DISK_SOCKET = '/run/agent-os-disk/api.sock'


def send(conn, value):
    conn.sendall(json.dumps(value, ensure_ascii=True, allow_nan=False).encode() + b'\n')


def read_line(f):
    line = f.readline(LIMIT + 1)
    if not line or len(line) > LIMIT or not line.endswith(b'\n'):
        raise ValueError('Invalid or oversized local request')
    return json.loads(line)


def connect(path, value, timeout=180):
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    conn.connect(path)
    send(conn, value)
    return conn


def listen(path):
    if os.path.exists(path):
        os.unlink(path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    os.chmod(path, 0o660)
    server.listen(8)
    return server
