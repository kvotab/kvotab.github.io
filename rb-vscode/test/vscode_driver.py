"""Drive a real VS Code with a development copy of the extension in it.

What the tests need, and how they get it:

  * a VS Code of its own: a separate build (@vscode/test-electron downloads
    it, or RB_VSCODE_EXE names one), started with a fresh profile, its own
    extensions and shared-data folders, updates and telemetry off, so nothing
    of the user's own VS Code is read or written;
  * the extension's side: commands and events through test/runner.js, which
    VS Code runs in the extension host (--extensionTestsPath);
  * the page's side: Chrome DevTools Protocol on the webview's frame, with the
    same `ev(expr)` the site's tests use (resources/tests/rb/driver.py), so
    their steps run unchanged inside VS Code.

Traps met on the way, all handled here:

  * VS Code started from a terminal inside VS Code inherits
    ELECTRON_RUN_AS_NODE and VSCODE_*: the binary then runs as plain Node
    ("bad option") or talks to the running VS Code. They are removed.
  * macOS caps a socket path at 103 characters and VS Code puts one in the
    profile, so the profile lives in a short temporary folder.
  * The test copy's updater shares ~/Library/Caches/com.microsoft.VSCode.ShipIt
    with the real VS Code and once replaced the test build with a newer one;
    "update.mode": "none" stops it.
  * VS Code keeps application state in ~/.vscode-shared unless given
    --shared-data-dir.
  * A file named on the command line is opened before a development
    extension's editor is registered, so by the text editor. Files are opened
    through the runner instead, once the extension is active.
  * rb awaits requestAnimationFrame, which Chromium stops for a window it
    counts as hidden, and a test window can open behind another: a lazy
    characterisation run once stalled at the group chart and timed out. The
    backgrounding switches below keep a covered window drawing.
"""
import asyncio
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request

import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
EXTENSION = os.path.dirname(HERE)
VERSION = os.environ.get('RB_VSCODE_VERSION', '1.135.0')

SETTINGS = {
    'update.mode': 'none',
    'extensions.autoCheckUpdates': False,
    'extensions.autoUpdate': False,
    'telemetry.telemetryLevel': 'off',
    'workbench.startupEditor': 'none',
    'workbench.colorTheme': 'Default Dark Modern',
    'security.workspace.trust.enabled': False,
    'chat.disableAIFeatures': True,
    'window.restoreWindows': 'none',
}


def vscode_executable():
    exe = os.environ.get('RB_VSCODE_EXE')
    if exe:
        return exe
    out = subprocess.run(['node', os.path.join(HERE, 'vscode-path.mjs'), VERSION],
                         cwd=EXTENSION, check=True, capture_output=True, text=True)
    return out.stdout.strip().splitlines()[-1]


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Page:
    """The rb page inside a webview, as resources/tests/rb/driver.py's Page."""

    def __init__(self, ws, target):
        self.ws = ws
        self.target = target
        self.logs = []
        self.contexts = {}      # id -> context description
        self.context_id = None
        self._id = 0
        self._events = []

    def _grab(self, r):
        m = r.get('method')
        p = r.get('params', {})
        if m == 'Runtime.executionContextCreated':
            self.contexts[p['context']['id']] = p['context']
        elif m == 'Runtime.executionContextDestroyed':
            self.contexts.pop(p['executionContextId'], None)
            if p['executionContextId'] == self.context_id:
                self.context_id = None
        elif m == 'Runtime.consoleAPICalled' and p.get('executionContextId') == self.context_id:
            if p['type'] in ('error', 'warning'):
                parts = [str(a.get('value', a.get('description', '?')))[:200] for a in p['args']]
                self.logs.append((p['type'], ' '.join(parts)))
        elif m == 'Runtime.exceptionThrown':
            d = p['exceptionDetails']
            if d.get('executionContextId') in (None, self.context_id):
                self.logs.append(('exception', (d.get('exception', {}).get('description') or d.get('text', ''))[:300]))

    async def send(self, method, params=None):
        self._id += 1
        await self.ws.send(json.dumps({'id': self._id, 'method': method, 'params': params or {}}))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get('id') == self._id:
                return r
            self._grab(r)

    async def pump(self, seconds=0.2):
        """Take in what the target has said, for a moment."""
        end = time.time() + seconds
        while time.time() < end:
            try:
                r = json.loads(await asyncio.wait_for(self.ws.recv(), max(0.01, end - time.time())))
                self._grab(r)
            except asyncio.TimeoutError:
                break

    async def find_page_context(self, timeout=60):
        """The execution context of the frame the page runs in (inside VS Code's own webview frame)."""
        end = time.time() + timeout
        while time.time() < end:
            await self.pump(0.3)
            for cid, ctx in list(self.contexts.items()):
                if not ctx.get('auxData', {}).get('isDefault'):
                    continue
                r = await self.send('Runtime.evaluate', {'expression': "typeof loadedFiles === 'object' && typeof KvotVscodeHost === 'object'",
                                                         'contextId': cid, 'returnByValue': True})
                if r.get('result', {}).get('result', {}).get('value') is True:
                    self.context_id = cid
                    return cid
        raise TimeoutError('the rb page did not appear in the webview')

    async def ev(self, expr, timeout=120, user_gesture=False):
        if self.context_id is None:
            await self.find_page_context()
        r = await asyncio.wait_for(self.send('Runtime.evaluate', {
            'expression': expr, 'contextId': self.context_id, 'returnByValue': True,
            'awaitPromise': True, 'userGesture': user_gesture}), timeout)
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:400]
        return res.get('result', {}).get('value')

    async def close(self):
        await self.ws.close()


class VSCode:
    def __init__(self, settings=None, keep=False, theme=None):
        self.exe = vscode_executable()
        self.port = free_port()
        self.keep = keep
        self.settings = dict(SETTINGS, **(settings or {}))
        if theme:
            self.settings['workbench.colorTheme'] = theme
        self.dir = tempfile.mkdtemp(prefix='rbv-')
        self.profile = os.path.join(self.dir, 'p')
        self.io = os.path.join(self.dir, 'io')
        os.makedirs(os.path.join(self.profile, 'ud', 'User'))
        os.makedirs(self.io)
        with open(os.path.join(self.profile, 'ud', 'User', 'settings.json'), 'w') as fh:
            json.dump(self.settings, fh, indent=1)
        self.events = []
        self._offset = 0
        self._seq = 0
        self.proc = None
        self.log = None

    def start(self, timeout=90):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('VSCODE_') and k not in ('ELECTRON_RUN_AS_NODE', 'ELECTRON_NO_ATTACH_CONSOLE')}
        env['KVOT_HDF5_TEST_DIR'] = self.io
        args = [self.exe,
                f'--extensionDevelopmentPath={EXTENSION}',
                f'--extensionTestsPath={os.path.join(HERE, "runner.js")}',
                f'--user-data-dir={os.path.join(self.profile, "ud")}',
                f'--extensions-dir={os.path.join(self.profile, "ext")}',
                f'--shared-data-dir={os.path.join(self.profile, "shared")}',
                '--disable-extensions', '--disable-workspace-trust', '--skip-welcome',
                '--skip-release-notes', '--disable-telemetry', '--new-window',
                # rb waits for animation frames (yieldForPaint, the chart), and a
                # window Chromium thinks is behind another gets none: a test
                # window that opened behind the user's own stalled for minutes.
                '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding',
                '--disable-background-timer-throttling',
                f'--remote-debugging-port={self.port}']
        self.log = open(os.path.join(self.dir, 'stdout.log'), 'w')
        self.proc = subprocess.Popen(args, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        try:
            self.wait_event(lambda e: e['type'] == 'activated', timeout, 'the extension to activate')
        except BaseException:
            # The caller has no object to stop yet, so a VS Code that never came
            # up would otherwise stay open on the screen after the test ends.
            self.stop()
            raise
        return self

    # ── the extension's side ───────────────────────────────────────────────

    def read_events(self):
        path = os.path.join(self.io, 'events.jsonl')
        if not os.path.exists(path):
            return []
        with open(path) as fh:
            fh.seek(self._offset)
            chunk = fh.read()
        complete = chunk[:chunk.rfind('\n') + 1]
        self._offset += len(complete.encode())
        fresh = [json.loads(line) for line in complete.splitlines() if line.strip()]
        self.events.extend(fresh)
        return fresh

    def wait_event(self, pred, timeout=60, what='an event', since=0):
        end = time.time() + timeout
        while time.time() < end:
            self.read_events()
            for e in self.events[since:]:
                if pred(e):
                    return e
            if self.proc and self.proc.poll() is not None:
                raise RuntimeError(f'VS Code exited ({self.proc.returncode}) while waiting for {what}; see {self.dir}/stdout.log')
            time.sleep(0.1)
        raise TimeoutError(f'no {what} within {timeout} s')

    def command(self, cmd, timeout=60, **kw):
        self._seq += 1
        cid = self._seq
        with open(os.path.join(self.io, 'commands.jsonl'), 'a') as fh:
            fh.write(json.dumps(dict(kw, id=cid, cmd=cmd)) + '\n')
        ack = self.wait_event(lambda e: e['type'] == 'ack' and e.get('id') == cid, timeout, f'an answer to {cmd}')
        if ack.get('error'):
            raise RuntimeError(f'{cmd}: {ack["error"]}')
        return ack.get('result')

    def mark(self):
        """Where the event list is now, to wait for what comes after."""
        self.read_events()
        return len(self.events)

    # ── the page's side ────────────────────────────────────────────────────

    def targets(self):
        return json.load(urllib.request.urlopen(f'http://127.0.0.1:{self.port}/json/list', timeout=10))

    async def webviews(self, count=1, timeout=60):
        end = time.time() + timeout
        while True:
            views = [t for t in self.targets() if t.get('url', '').startswith('vscode-webview://')]
            if len(views) >= count or time.time() > end:
                return views
            await asyncio.sleep(0.3)

    async def page(self, index=-1, timeout=60):
        """The rb page in a webview; by default the one opened last."""
        views = await self.webviews(1, timeout)
        if not views:
            raise TimeoutError('no webview appeared')
        found = []
        for t in views:
            ws = await websockets.connect(t['webSocketDebuggerUrl'], max_size=300 * 1024 * 1024)
            p = Page(ws, t)
            await p.send('Runtime.enable')
            await p.send('Page.enable')
            try:
                await p.find_page_context(timeout=timeout)
                found.append(p)
            except TimeoutError:
                await p.close()
        if not found:
            raise TimeoutError('no webview has the rb page in it')
        chosen = found[index]
        for p in found:
            if p is not chosen:
                await p.close()
        state = await chosen.ev('document.visibilityState')
        if state != 'visible':
            print(f'warning: the page is {state}; it draws nothing until it is visible', flush=True)
        return chosen

    async def page_for(self, name, timeout=60):
        """The page in the view that has the file of this name open."""
        end = time.time() + timeout
        while time.time() < end:
            for t in await self.webviews(1, 5):
                ws = await websockets.connect(t['webSocketDebuggerUrl'], max_size=300 * 1024 * 1024)
                p = Page(ws, t)
                await p.send('Runtime.enable')
                try:
                    await p.find_page_context(timeout=5)
                    if await p.ev('fileOrder.includes(%s)' % json.dumps(name)):
                        return p
                except TimeoutError:
                    pass
                await p.close()
            await asyncio.sleep(0.5)
        raise TimeoutError(f'no view has {name} open')

    async def workbench_screenshot(self, path):
        t = [t for t in self.targets() if t['type'] == 'page' and 'workbench' in t.get('url', '')][0]
        async with websockets.connect(t['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as ws:
            await ws.send(json.dumps({'id': 1, 'method': 'Page.captureScreenshot', 'params': {'format': 'png'}}))
            while True:
                r = json.loads(await ws.recv())
                if r.get('id') == 1:
                    break
        import base64
        with open(path, 'wb') as fh:
            fh.write(base64.b64decode(r['result']['data']))
        return path

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.command('quit', timeout=10)
            except Exception:
                pass
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)
        if self.log:
            self.log.close()
        if not self.keep:
            shutil.rmtree(self.dir, ignore_errors=True)
        else:
            print(f'kept {self.dir}')
