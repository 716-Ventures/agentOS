#!/usr/bin/env python3
"""Native Link -> GIO -> real Firefox -> shared Wayland window; isolated profile."""
import copy
import argparse
import http.server
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT.parent if (ROOT.parent / 'install_runtime.py').is_file() else ROOT.parent / 'agent-shell'
OUTPUT = ROOT / 'test-output/browser-links'
OUTPUT.mkdir(parents=True, exist_ok=True)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--installed', action='store_true', help='Exercise the current immutable runtime instead of development binaries')
args = parser.parse_args()
core_binary = Path('/usr/local/lib/agent-os/current/agent-os-core') if args.installed else SHELL / 'target/release/agent-os-core'
desktop_binary = Path('/usr/local/bin/agent-os-desktop') if args.installed else ROOT / 'target/debug/agent-os-desktop'
compositor_binary = Path('/usr/local/bin/agent-os-compositor') if args.installed else ROOT.parent / 'native-compositor/target/debug/agent-os-compositor'


def wait(predicate, description, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError(description)


def reap(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def request(endpoint, value):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(6)
        connection.connect(str(endpoint))
        connection.sendall(json.dumps(value).encode() + b'\n')
        with connection.makefile('rb') as stream:
            response = json.loads(stream.readline())
        assert response['ok'], response
        return response['result']


for scheme in ('http', 'https'):
    observed = subprocess.check_output(['gio', 'mime', 'x-scheme-handler/' + scheme], text=True,
                                       env={**os.environ, 'LC_ALL': 'C.UTF-8'})
    assert observed.splitlines()[0] == 'Default application for “x-scheme-handler/' + scheme + '”: firefox-esr.desktop', observed
    print('PASS: system ' + scheme + ' handler is Firefox ESR', flush=True)

with tempfile.TemporaryDirectory(prefix='agentos-browser-') as directory:
    runtime = Path(directory)
    config, home, data, profile = [runtime / name for name in ('config', 'home', 'data', 'profile')]
    for path in (config, home, data, profile):
        path.mkdir(mode=0o700)
    (config / 'agent-os').mkdir()
    (config / 'agent-os/desktop.json').write_text(json.dumps({'appearance': 'dark', 'text_scale': 1, 'reduced_motion': True}))
    title = 'agentOS browser fixture ' + uuid.uuid4().hex
    loaded = threading.Event()

    class Page(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/fixture':
                body = ('<!doctype html><html lang="en"><title>' + title + '</title><h1>' + title + '</h1><p>Native link handoff, Unicode λ 日本語.</p></html>').encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                loaded.set()
            else:
                self.send_response(204)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Page)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    uri = 'http://127.0.0.1:' + str(server.server_port) + '/fixture'
    # Suppress marketing/default-browser prompts in this disposable profile.
    # Do not change sandbox, certificate validation or terms-of-use settings.
    (profile / 'user.js').write_text('\n'.join([
        'user_pref("browser.shell.checkDefaultBrowser", false);',
        'user_pref("browser.startup.homepage", "about:blank");',
        'user_pref("browser.startup.homepage_override.mstone", "ignore");',
        'user_pref("browser.aboutwelcome.enabled", false);',
        'user_pref("browser.newtabpage.enabled", false);',
        'user_pref("datareporting.healthreport.uploadEnabled", false);',
        'user_pref("toolkit.telemetry.enabled", false);',
    ]) + '\n')
    receipt = runtime / 'browser-process.json'
    launcher = runtime / 'launch-browser.py'
    launcher.write_text('import os,json,sys\nfrom pathlib import Path\n'
        'assert sys.argv[1:] == [' + repr(uri) + ']\n'
        'try: os.setsid()\nexcept PermissionError: assert os.getpgrp()==os.getpid()\n'
        'info={"pid":os.getpid(),"start":Path("/proc/self/stat").read_text().split(") ",1)[1].split()[19]}\n'
        'fd=os.open(' + repr(str(receipt)) + ',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)\n'
        'os.write(fd,json.dumps(info).encode());os.close(fd)\n'
        'os.execv("/usr/bin/firefox-esr",["firefox-esr","--no-remote","--profile",' + repr(str(profile)) + ',sys.argv[1]])\n')
    applications = data / 'applications'
    applications.mkdir()
    (applications / 'agentos-browser-fixture.desktop').write_text(
        '[Desktop Entry]\nType=Application\nName=Isolated Firefox fixture\n'
        'Exec=/usr/bin/python3 ' + str(launcher) + ' %u\n'
        'MimeType=x-scheme-handler/http;x-scheme-handler/https;\nTerminal=false\nStartupNotify=false\n')
    subprocess.run(['update-desktop-database', str(applications)], check=True)
    (config / 'mimeapps.list').write_text('[Default Applications]\nx-scheme-handler/http=agentos-browser-fixture.desktop\nx-scheme-handler/https=agentos-browser-fixture.desktop\n')
    endpoint = runtime / 'core.sock'
    env = {**os.environ, 'HOME': str(home), 'XDG_RUNTIME_DIR': directory,
           'XDG_CONFIG_HOME': str(config), 'XDG_DATA_HOME': str(data),
           'WAYLAND_DISPLAY': 'browser-parent', 'GDK_BACKEND': 'wayland',
           'GSK_RENDERER': 'cairo', 'GTK_A11Y': 'atspi', 'MOZ_ENABLE_WAYLAND': '1',
           'LIBGL_ALWAYS_SOFTWARE': '1', 'WINIT_UNIX_BACKEND': 'wayland',
           'AGENT_OS_STATE': str(runtime / 'state'), 'AGENT_OS_SOCKET': str(endpoint),
           'AGENT_OS_COMPOSITOR_UID': str(os.getuid())}
    processes = []
    def spawn(command, environment, log):
        process = subprocess.Popen(command, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(process)
        return process

    def group_live(group):
        for path in Path('/proc').glob('[0-9]*/stat'):
            try:
                fields=path.read_text().split(') ',1)[1].split()
                if int(fields[2])==group and fields[0] not in ('Z','X'):
                    return True
            except (FileNotFoundError,ProcessLookupError,PermissionError):
                pass
        return False

    def stop_browser():
        if not receipt.exists():
            return
        info = json.loads(receipt.read_text())
        pid = info['pid']
        stat = Path('/proc') / str(pid) / 'stat'
        try:
            assert stat.read_text().split(') ', 1)[1].split()[19] == info['start'], 'Browser PID was recycled'
            assert os.getpgid(pid) == pid, 'Fixture lost its private process group'
        except (FileNotFoundError, ProcessLookupError):
            pass  # The leader may exit before its remaining children.
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        end = time.monotonic() + 8
        while time.monotonic() < end:
            if not group_live(pid):
                return
            time.sleep(.1)
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        wait(lambda:not group_live(pid),'Owned browser group did not terminate',5)

    with (OUTPUT / 'session.log').open('w') as log:
        try:
            core = spawn([str(core_binary)], env, log)
            def core_ready():
                assert core.poll() is None,'Core exited'
                return endpoint.exists()
            wait(core_ready, 'Core socket')
            activity = request(endpoint, {'op': 'create', 'name': 'Native browser links'})['id']
            doc = {'protocol': 'agentos.presentation/1', 'catalog_revision': 'native-core/1',
                   'surface_id': 'browser-link-fixture', 'activity_id': str(activity), 'revision': 0,
                   'title': 'Native browser link', 'root': 'link',
                   'elements': {'link': {'type': 'Link@1', 'props': {'label': 'Open local browser fixture', 'url': uri}}},
                   'bindings': {}, 'actions': {}}
            request(endpoint, {'op': 'presentation.apply', 'protocol': 'agentos.presentation/1', 'catalog_revision': 'native-core/1',
                              'request_id': 'browser-link-create', 'expected_revisions': {'browser-link-fixture': None},
                              'operations': [{'op': 'surface.create', 'document': doc}]})
            weston = spawn(['weston', '--backend=headless-backend.so', '--use-pixman', '--socket=browser-parent', '--idle-time=0', '--width=1280', '--height=800'], env, log)
            wait(lambda: (runtime / 'browser-parent').exists(), 'Private parent display')
            compositor = spawn([str(compositor_binary)], {**env, 'AGENT_OS_COMPOSITOR_CORE': str(endpoint)}, log)
            control = runtime / ('agentos-compositor-' + str(compositor.pid) + '.sock')
            wait(lambda: control.exists(), 'Shared compositor control')
            displays = [path.name for path in runtime.glob('wayland-*') if path.is_socket()]
            assert len(displays) == 1, displays
            childenv = {**env, 'WAYLAND_DISPLAY': displays[0]}
            desktop = spawn([str(desktop_binary), '--socket', str(endpoint), '--activity', str(activity)], childenv, log)
            import accessibility
            import pyatspi
            accessibility.activate(accessibility.find('Open local browser fixture', pyatspi.ROLE_LINK))
            wait(loaded.is_set, 'Firefox did not retrieve the local linked page', 60)
            def browser_window():
                state = request(control, {'op': 'snapshot'})
                identities=(state.get('shared') or {}).get('identities',{})
                return next(((state, window) for window in state['windows'] if title in (window.get('title') or '') and 'firefox' in (window.get('app_id') or '').lower() and window['id'] in identities), None)
            state, window = wait(browser_window, 'Loaded browser window not registered in shared workspace', 30)
            identity = state['shared']['identities'][window['id']]
            workspace = copy.deepcopy(request(endpoint, {'op': 'presentation.snapshot'})['documents']['desktop-' + str(activity)])
            workspace['focus'] = {'surface_id': identity, 'element_id': None}
            workspace['outputs']['nested-primary']['maximized'] = identity
            request(control, {'op': 'workspace.apply', 'document': workspace, 'expected_revision': workspace['revision'], 'request_id': 'focus-maximize-browser'})
            wait(lambda: (lambda s: s['layout']['focus'] == window['id'] and next(w for w in s['windows'] if w['id'] == window['id'])['geometry']['width'] == 1280)(request(control, {'op': 'snapshot'})), 'Browser focus/maximize')
            stop_browser()
            wait(lambda: window['id'] not in [w['id'] for w in request(control, {'op': 'snapshot'})['windows']], 'Browser window removal')
            report = {'result': 'pass', 'checks': ['system HTTP/HTTPS handler', 'actual native Link action', 'GIO launch with isolated profile', 'real Firefox local page retrieval and title', 'conventional shared identity', 'durable focus/maximize', 'browser disconnect'], 'not_tested': ['physical input', 'remote website compatibility', 'hardware acceleration', 'mailto account/client']}
            report['firefox_debian_version'] = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'firefox-esr'], text=True).strip()
            report['installed_executables'] = args.installed
            print('PASS: native Link, real Firefox, shared conventional window, focus/maximize and disconnect', flush=True)
        finally:
            try:
                stop_browser()
            finally:
                for process in reversed(processes):
                    reap(process)
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
    report['cleanup_verified']=True
    (OUTPUT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
print('PASS: browser profile, launch group, native clients, core and private displays cleaned up')
