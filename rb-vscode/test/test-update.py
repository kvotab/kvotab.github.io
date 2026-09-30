#!/usr/bin/env python3
"""An installed copy updates itself, in a real VS Code.

This folder, packaged, is installed into a VS Code of its own (a fresh
profile, as vscode_driver.py makes one) as a user installs a download from the
site. A server here plays the site: its release note names the next version,
signed with a key made for the test, and its package is this one's with the
version raised. The extension is pointed at both (KVOT_HDF5_UPDATE_URL and
KVOT_HDF5_UPDATE_KEY; everything else is as installed), and then:

  1. soon after VS Code starts it looks by itself, downloads the package,
     checks it and has VS Code install it, and offers to reload the window;
  2. Reload Window, clicked in that notification, starts the new version,
     and VS Code marks the old one for removal;
  3. which does not look again so soon: a look holds for twelve hours, for
     every window and every version;
  4. HDF5 Browser: Check for Updates, from the Command Palette, looks at
     once, and says it is up to date;
  5. and the extension's gear menu in the Extensions view has it too. The
     menu is read where VS Code draws it in the window (window.menuStyle
     custom); a VS Code without that setting (1.100) uses macOS's own menus,
     which cannot be read, and the check is skipped there.

VS Code is driven over the DevTools protocol (the notification's button, the
Command Palette) and read from its logs; nothing here uses test/runner.js,
which needs a copy run from its folder, and such a copy is never updated.

    RB_VSCODE_EXE=... python3 rb-vscode/test/test-update.py

Exit status is 0 when every check passes.
"""
import asyncio
import base64
import glob
import hashlib
import http.server
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
EXTENSION = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from vscode_driver import SETTINGS, free_port, vscode_executable  # noqa: E402

ID = 'kvotab.hdf5-browser'
failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'), flush=True)
    if not ok:
        failures.append(label)


def next_version(v):
    a, b, c = (int(x) for x in v.split('.'))
    return f'{a}.{b}.{c + 1}'


def raised(vsix, old, new):
    """The package with its version raised from `old` to `new`, in its manifest and its package.json."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(vsix)) as src, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == 'extension/package.json':
                pkg = json.loads(data)
                assert pkg['version'] == old
                pkg['version'] = new
                data = json.dumps(pkg, indent=2).encode()
            elif item.filename == 'extension.vsixmanifest':
                text = data.decode()
                assert f'Version="{old}"' in text
                data = text.replace(f'Version="{old}"', f'Version="{new}"', 1).encode()
            dst.writestr(item, data)
    return out.getvalue()


def signed_note(version, package):
    """A key pair made for the test, and the release note release.mjs would write, signed with it by src/update.js."""
    script = r"""
const crypto = require('crypto');
const { signRelease } = require(process.argv[1]);
const [version, sha256] = [process.argv[2], process.argv[3]];
const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519');
process.stdout.write(JSON.stringify({
  publicKey: publicKey.export({ type: 'spki', format: 'pem' }),
  signature: signRelease(privateKey, 'kvotab.hdf5-browser', version, sha256)
}));
"""
    sha256 = hashlib.sha256(package).hexdigest()
    out = json.loads(subprocess.run(['node', '-e', script, os.path.join(EXTENSION, 'src', 'update.js'), version, sha256],
                                    check=True, capture_output=True, text=True).stdout)
    note = {'name': 'HDF5 Browser', 'version': version, 'file': 'hdf5-browser.vsix', 'bytes': len(package), 'sha256': sha256,
            'released': time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime()), 'build': 'test-update.py',
            'vscode': '^1.100.0', 'signature': out['signature']}
    return note, out['publicKey']


class Site(http.server.ThreadingHTTPServer):
    """The site's two files, and what was asked of it."""

    def __init__(self, note, package):
        self.note = json.dumps(note).encode()
        self.package = package
        self.requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(h):
                self.requests.append(h.path)
                path = h.path.split('?')[0]
                body = {'/dist/latest.json': self.note, '/dist/hdf5-browser.vsix': self.package}.get(path)
                if body is None:
                    h.send_response(404)
                    h.end_headers()
                    return
                h.send_response(200)
                h.send_header('Content-Type', 'application/json' if path.endswith('.json') else 'application/octet-stream')
                h.send_header('Content-Length', str(len(body)))
                h.end_headers()
                h.wfile.write(body)

            def log_message(h, *args):
                pass

        super().__init__(('127.0.0.1', 0), Handler)


class Workbench:
    """VS Code's own window, over the DevTools protocol."""

    def __init__(self, port):
        self.port = port
        self.ws = None
        self._id = 0

    async def connect(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            try:
                pages = [t for t in json.load(urllib.request.urlopen(f'http://127.0.0.1:{self.port}/json/list', timeout=5))
                         if t['type'] == 'page' and 'workbench' in t.get('url', '')]
                if pages:
                    if self.ws:
                        await self.ws.close()
                    self.ws = await websockets.connect(pages[0]['webSocketDebuggerUrl'], max_size=64 * 1024 * 1024)
                    return
            except Exception:
                pass
            await asyncio.sleep(0.5)
        raise TimeoutError('no workbench window')

    async def send(self, method, params=None):
        self._id += 1
        await self.ws.send(json.dumps({'id': self._id, 'method': method, 'params': params or {}}))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get('id') == self._id:
                return r

    async def ev(self, expr):
        r = await self.send('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        return r.get('result', {}).get('result', {}).get('value')

    async def toasts(self):
        """The notifications showing: their text and their buttons."""
        return await self.ev("""[...document.querySelectorAll('.notification-toast')].map(t => ({
          text: (t.querySelector('.notification-list-item-message') || t).innerText.trim(),
          buttons: [...t.querySelectorAll('.monaco-button')].map(b => b.innerText.trim()).filter(Boolean)
        }))""") or []

    async def wait_toast(self, pred, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            for t in await self.toasts():
                if pred(t['text']):
                    return t
            await asyncio.sleep(0.3)
        return None

    async def click(self, text, button):
        return await self.ev("""(() => {
          for (const t of document.querySelectorAll('.notification-toast')) {
            if (!(t.innerText || '').includes(%s)) continue;
            for (const b of t.querySelectorAll('.monaco-button')) if (b.innerText.trim() === %s) { b.click(); return true; }
          }
          return false;
        })()""" % (json.dumps(text), json.dumps(button)))

    async def key(self, key, code, vk):
        for kind in ('keyDown', 'keyUp'):
            await self.send('Input.dispatchKeyEvent', {'type': kind, 'key': key, 'code': code, 'windowsVirtualKeyCode': vk})

    async def gear_menu(self, name):
        """What the gear (Manage) of an installed extension in the Extensions view offers; None if no menu can be read."""
        await self.command('Extensions: Show Installed Extensions')
        end = time.time() + 20
        at = None
        while time.time() < end and not isinstance(at, list):
            at = await self.ev("""(() => {
              const item = [...document.querySelectorAll('.extension-list-item')].find(i => (i.querySelector('.name') || {}).innerText === %s);
              const gear = item && item.querySelector('.action-label.manage');
              const r = gear && gear.getBoundingClientRect();
              return r && r.width > 0 && r.height > 0 ? [r.x + r.width / 2, r.y + r.height / 2] : null;
            })()""" % json.dumps(name))
            await asyncio.sleep(0.3)
        # The view slides in: clicked at once, the gear has moved from under the pointer.
        await asyncio.sleep(1.5)
        at = await self.ev("""(() => {
          const item = [...document.querySelectorAll('.extension-list-item')].find(i => (i.querySelector('.name') || {}).innerText === %s);
          const r = item && item.querySelector('.action-label.manage').getBoundingClientRect();
          return r ? [r.x + r.width / 2, r.y + r.height / 2] : null;
        })()""" % json.dumps(name)) if isinstance(at, list) else at
        if not isinstance(at, list):
            return None
        x, y = at
        await self.send('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y})
        for kind in ('mousePressed', 'mouseReleased'):
            await self.send('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
        end = time.time() + 5
        while time.time() < end:
            labels = await self.ev("[...document.querySelectorAll('.monaco-menu .action-label')].map(a => a.innerText.trim()).filter(Boolean)")
            if labels:
                return labels
            await asyncio.sleep(0.3)
        return None

    async def command(self, title):
        """A command run from the Command Palette, as a user runs one."""
        await self.key('F1', 'F1', 112)
        await asyncio.sleep(0.8)
        await self.send('Input.insertText', {'text': title})
        await asyncio.sleep(1.2)
        await self.key('Enter', 'Enter', 13)


def draws_menus_in_window(exe):
    """Whether this VS Code has window.menuStyle, which can put its menus in the window (where they can be read)."""
    js = os.path.join(os.path.dirname(os.path.dirname(exe)), 'Resources', 'app', 'out', 'vs', 'workbench', 'workbench.desktop.main.js')
    try:
        with open(js, errors='replace') as fh:
            return '"window.menuStyle"' in fh.read()
    except OSError:
        return True


def log_text(profile):
    """Every log the extension wrote in this profile, windows and reloads together."""
    parts = []
    for p in sorted(glob.glob(os.path.join(profile, 'ud', 'logs', '**', ID, '*.log'), recursive=True)):
        with open(p, errors='replace') as fh:
            parts.append(fh.read())
    return '\n'.join(parts)


def wait_log(profile, pattern, timeout, proc):
    end = time.time() + timeout
    while time.time() < end:
        m = re.search(pattern, log_text(profile))
        if m:
            return m
        if proc.poll() is not None:
            raise RuntimeError(f'VS Code exited ({proc.returncode})')
        time.sleep(0.3)
    return None


async def main():
    exe = vscode_executable()
    cli = os.path.join(os.path.dirname(os.path.dirname(exe)), 'Resources', 'app', 'bin', 'code')
    with open(os.path.join(EXTENSION, 'package.json')) as fh:
        base_version = json.load(fh)['version']
    new_version = next_version(base_version)
    work = tempfile.mkdtemp(prefix='rbu-')
    profile = os.path.join(work, 'p')
    ud, ext, shared = (os.path.join(profile, x) for x in ('ud', 'ext', 'shared'))
    os.makedirs(os.path.join(ud, 'User'))
    # VS Code's own auto-update on, as it is by default: with it off, the
    # extension offers a new version instead of installing it.
    # Menus drawn in the window (step 5).
    settings = dict(SETTINGS, **{'extensions.autoUpdate': True, 'extensions.autoCheckUpdates': True, 'window.menuStyle': 'custom'})
    with open(os.path.join(ud, 'User', 'settings.json'), 'w') as fh:
        json.dump(settings, fh, indent=1)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('VSCODE_') and k not in ('ELECTRON_RUN_AS_NODE', 'ELECTRON_NO_ATTACH_CONSOLE')}
    dirs = [f'--user-data-dir={ud}', f'--extensions-dir={ext}', f'--shared-data-dir={shared}']
    proc = None
    site = None
    try:
        base_vsix = os.path.join(work, f'hdf5-browser-{base_version}.vsix')
        subprocess.run(['node', os.path.join(EXTENSION, 'node_modules', '@vscode', 'vsce', 'vsce'), 'package', '--out', base_vsix],
                       cwd=EXTENSION, check=True, capture_output=True)
        with open(base_vsix, 'rb') as fh:
            package = raised(fh.read(), base_version, new_version)
        note, public_key = signed_note(new_version, package)
        site = Site(note, package)
        threading.Thread(target=site.serve_forever, daemon=True).start()
        env['KVOT_HDF5_UPDATE_URL'] = f'http://127.0.0.1:{site.server_address[1]}/dist/'
        env['KVOT_HDF5_UPDATE_KEY'] = public_key

        r = subprocess.run([cli, *dirs, '--install-extension', base_vsix], env=env, capture_output=True, text=True)
        check(f'{base_version} installs into a profile of its own', sorted(os.listdir(ext)).count(f'{ID}-{base_version}'), 1)

        port = free_port()
        proc = subprocess.Popen([exe, *dirs, '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes', '--disable-telemetry',
                                 '--new-window', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding',
                                 '--disable-background-timer-throttling', f'--remote-debugging-port={port}'],
                                env=env, stdout=open(os.path.join(work, 'stdout.log'), 'w'), stderr=subprocess.STDOUT)
        wb = Workbench(port)
        await wb.connect()

        # 1. by itself: download, check, install, offer the reload
        started = wait_log(profile, rf'HDF5 Browser {re.escape(base_version)}, page', 90, proc)
        check(f'{base_version} starts (installed, not run from its folder)', bool(started))
        installed = wait_log(profile, rf'Installed {re.escape(new_version)}', 120, proc)
        check(f'soon after, it installs {new_version} by itself', bool(installed))
        check('  having asked the site for the note, then the package once',
              ([p.split('?')[0] for p in site.requests]), ['/dist/latest.json', '/dist/hdf5-browser.vsix'])
        folder = os.path.join(ext, f'{ID}-{new_version}')
        with open(os.path.join(folder, 'package.json')) as fh:
            check(f'  VS Code put {new_version} in a folder of its own', json.load(fh)['version'], new_version)
        with open(os.path.join(ext, 'extensions.json')) as fh:
            listed = [e['version'] for e in json.load(fh) if e['identifier']['id'] == ID]
        check('  and lists it as the version installed', listed, [new_version])
        offer = f'HDF5 Browser {new_version} is installed. Reload the window to start it.'
        toast = await wb.wait_toast(lambda t: t.startswith(offer), 20)
        check('  and the window is offered a reload', toast and toast['buttons'], ['Reload Window'])

        # 2. Reload Window, from that notification
        clicked = await wb.click(offer, 'Reload Window')
        check('Reload Window can be clicked', clicked)
        restarted = wait_log(profile, rf'HDF5 Browser {re.escape(new_version)}, page', 90, proc)
        check(f'  and the window runs {new_version}', bool(restarted))
        with open(os.path.join(ext, '.obsolete')) as fh:
            check(f'  and VS Code is to remove {base_version}', json.load(fh), {f'{ID}-{base_version}': True})
        await wb.connect()

        # 3. no second look so soon: past the new version's first (20 s after it starts)
        await asyncio.sleep(25)
        check(f'{new_version} does not look again so soon: the look before the reload holds for it',
              [p.split('?')[0] for p in site.requests], ['/dist/latest.json', '/dist/hdf5-browser.vsix'])

        # 4. the command, as a user gives it
        await wb.command('HDF5 Browser: Check for Updates')
        up = await wb.wait_toast(lambda t: 'is up to date' in t, 20)
        check('HDF5 Browser: Check for Updates, from the Command Palette, looks at once and says it is up to date',
              up and up['text'], f'The HDF5 Browser is up to date: {new_version} is the latest version.')
        check('  having read the note, and downloaded nothing', [p.split('?')[0] for p in site.requests],
              ['/dist/latest.json', '/dist/hdf5-browser.vsix', '/dist/latest.json'])

        # 5. the gear menu
        if draws_menus_in_window(exe):
            labels = await wb.gear_menu('HDF5 Browser')
            check("the extension's gear menu in the Extensions view has Check for Updates", 'Check for Updates' in (labels or []))
        else:
            print("skip  the extension's gear menu: this VS Code draws it with macOS's own menus", flush=True)

        text = log_text(profile)
        check('the extension logged no error', [l for l in text.splitlines() if '[error]' in l][:3], [])
        host = '\n'.join(open(p, errors='replace').read() for p in glob.glob(os.path.join(ud, 'logs', '**', 'exthost.log'), recursive=True))
        check('VS Code found nothing wrong with its contributions (the command, the gear menu, the setting)',
              [l for l in host.splitlines() if ID in l and ('[warning]' in l or '[error]' in l)][:3], [])
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(10)
        if site:
            site.shutdown()
        if os.environ.get('RB_KEEP'):
            print(f'kept {work}')
        else:
            shutil.rmtree(work, ignore_errors=True)

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
