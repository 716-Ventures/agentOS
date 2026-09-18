"""Local aggregate telemetry. Never stores prompts, responses, or credentials."""
import datetime
import json
import os
from pathlib import Path
import threading
import fcntl
from contextlib import contextmanager

STATE = Path('/var/lib/agent-os-ai/model-usage.json')
PUBLIC = Path('/run/agent-os-ai/model-usage.json')
THREAD_LOCK = threading.RLock()

@contextmanager
def locked():
    with THREAD_LOCK:
        with STATE.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(lock,fcntl.LOCK_UN)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def read():
    try:
        return json.loads(STATE.read_text())
    except FileNotFoundError:
        return {'version': 1, 'tracking_since': now(), 'models': {}, 'configuration': []}


def write(data):
    data['updated_at'] = now()
    for path in (STATE, PUBLIC):
        temporary = path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
        os.fchmod(fd, 0o640 if path == PUBLIC else 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out)
        temporary.replace(path)


def configure(cfg, default_model, recover=False):
    try:
        with locked():
            data = read()
            data['configuration'] = [
                {'provider': 'Vercel AI Gateway', 'model': cfg.get('gateway_model', default_model),
                 'configured': bool(cfg.get('gateway_key')), 'role': 'Conversation, reasoning, and tool planning'},
                {'provider': 'Typesafe', 'model': 'jev-latest', 'configured': bool(cfg.get('jev_key')),
                 'role': 'Runtime action risk assessment; broker enforces decisions'}]
            if recover:
                for row in data['models'].values():
                    row['interrupted'] += row.get('active', 0)
                    row['active'] = 0
            write(data)
    except (OSError, ValueError, TypeError, KeyError):
        pass  # Observability must not prevent the agent from operating.


def begin(url, body):
    provider = {'https://ai-gateway.vercel.sh/v1/chat/completions': 'Vercel AI Gateway',
                'https://api.typesafe.ai/v1/systemone': 'Typesafe'}.get(url)
    if not provider or not isinstance(body, dict):
        return None
    model = str(body.get('model', 'unknown'))[:160]
    key = provider + '/' + model
    try:
        with locked():
            data = read()
            row = data['models'].setdefault(key, dict(provider=provider, model=model,
                attempts=0, responses=0, errors=0, rate_limits=0, interrupted=0, active=0,
                input_tokens=0, output_tokens=0, total_tokens=0,
                input_reports=0, output_reports=0, total_reports=0))
            row['attempts'] += 1
            row['active'] += 1
            row['last_at'] = now()
            write(data)
        return key
    except (OSError, ValueError, TypeError, KeyError):
        return None


def finish(key, elapsed, response=None, http_status=None):
    if key is None:
        return
    try:
        with locked():
            data = read()
            row = data['models'][key]
            row['active'] = max(0, row['active'] - 1)
            row['last_at'] = now()
            row['last_latency_ms'] = round(elapsed * 1000)
            row['last_status'] = 'response received' if response is not None else ('HTTP ' + str(http_status) if http_status else 'connection or response error')
            if response is None:
                row['errors'] += 1
                row['rate_limits'] += int(http_status == 429)
            else:
                row['responses'] += 1
                if isinstance(response, dict):
                    if isinstance(response.get('model'), str):
                        row['resolved_model'] = response['model'][:160]
                    usage = response.get('usage')
                    if isinstance(usage, dict):
                        for field, aliases in [('input', ('prompt_tokens', 'input_tokens')),
                                               ('output', ('completion_tokens', 'output_tokens')),
                                               ('total', ('total_tokens',))]:
                            value = next((usage[a] for a in aliases if type(usage.get(a)) is int and usage[a] >= 0), None)
                            if value is not None:
                                row[field + '_tokens'] += value
                                row[field + '_reports'] += 1
            write(data)
    except (OSError, ValueError, TypeError, KeyError):
        pass
