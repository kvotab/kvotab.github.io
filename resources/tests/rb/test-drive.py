#!/usr/bin/env python3
"""Google Drive: the button, Google's sign-in and picker, and the files fetched.

Nothing of Google's own can run in a test: a real sign-in needs the Google
Cloud project named in rb-drive-config.js and a person at Google's window. So
the page's code runs as it is, against stand-ins served at Google's real
addresses through Chrome's request interception (CDP Fetch):

    rb-drive-config.js                       a project, or none, or no file
    https://accounts.google.com/gsi/client   Google's sign-in: answers a token
    https://apis.google.com/js/api.js        the picker: answers files picked
    https://www.googleapis.com/drive/v3/files/<id>   the Drive API: the bytes,
                                             or the name, type and size

The stand-ins take Google's documented names (initTokenClient, PickerBuilder,
DocsView, Action.PICKED, ...); what Google's real ones do with them is not
tested here, and needs the project.

Checked:
  - with the project empty, or its file missing, the button and the welcome
    sentence are not shown, and nothing is fetched from Google;
  - with a project, the button shows, and still nothing is fetched from
    Google until it is clicked;
  - the first click opens the dialog and loads the two scripts once; Choose
    files asks for drive.file and nothing else, with the project's client,
    from within the click, so a browser would let Google's window open;
  - the picker gets the token, the key and the project number, three views in
    a list, several files at once;
  - the files picked open as files from disk do: an HDF5 file, a MAT-file
    shared by link (its resource key sent with it) and a JSON file, and a name
    with a slash in it stays one level;
  - the token goes with the Drive API's file requests and with no other
    request, and is in no storage;
  - a second click goes straight to the picker; a cancel does nothing;
  - a Google Docs file, a folder, a file over the size limit and an ID that
    is not a Drive ID are refused before any request;
  - Drive's refusals are said in words: 403 cannotDownloadFile, 404, and 401,
    after which the next click asks Google again, from the click;
  - Google's sign-in refused, the Drive box left unticked, its window blocked
    or closed, are each said in the dialog, and Escape and a click beside it
    close it;
  - a script of Google's that does not load is said, and Try again loads
    that one again and not the other;
  - Google's window blocked before the reader chose an account leaves the
    choice of account for the next try;
  - an HDF5 file read a piece at a time (kvot-rb-lazy = always stands in for
    one of 256 MB): every request for it a range, the page's first one and
    the worker's, each with the token; its values the same as the same file's
    read whole; a MAT-file still read whole; and when Google stops taking the
    token, the next read says so, and once Google gives a new one the worker
    reads on with it, the file open all the while;
  - opened by "Open with" in Drive (its `state` in the address), the page
    opens the dialog by itself, saying what Drive asked for, takes the request
    out of the address, and asks Drive nothing before Open; Open asks Google
    from the click, straight for the account Drive named, then asks Drive
    each file's name, type and size and opens them as picked files open, the
    resource key with both requests, no picker shown;
  - a request from Drive that cannot be acted on (an ID that is no Drive ID,
    no JSON, Drive's New, a Google Docs file) is said, the picker offered
    instead; a file Drive will not show the page is said and the rest still
    open; with no account named the reader chooses one; Cancel lets Drive's
    files go;
  - the dialog's offer to add the Data Browser to Drive's Open with menu asks
    Google, from the click, for drive.install with drive.file; that box left
    unticked is said; given, it is said done, the access kept, and the offer
    not made again in the tab.

Start the server and the browser as in README.md (RB_TEST_HTTP and
RB_TEST_CDP choose other ports), then

    python3 resources/tests/rb/test-drive.py

Exit status is 0 when every check passes.
"""
import asyncio
import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request

import websockets

HTTP = int(os.environ.get('RB_TEST_HTTP', '8765'))
CDP = int(os.environ.get('RB_TEST_CDP', '9222'))
ORIGIN = f'http://127.0.0.1:{HTTP}'
HERE = os.path.dirname(os.path.abspath(__file__))

TOKEN = 'ya29.TEST-ACCESS-TOKEN-not-a-real-one'
TOKEN2 = 'ya29.TEST-ACCESS-TOKEN-renewed'
CLIENT = '000000000000-test.apps.googleusercontent.com'
KEY = 'AIzaTEST-KEY-not-a-real-one'
APP = '123456789012'
SCOPE = 'https://www.googleapis.com/auth/drive.file'
INSTALL = 'https://www.googleapis.com/auth/drive.install'
USER = '109876543210987654321'   # a Google account ID, as Drive's Open with names the reader
SIGN_IN = 'https://accounts.google.com/gsi/client'
PICKER = 'https://apis.google.com/js/api.js'
FILES_API = 'https://www.googleapis.com/drive/v3/files/'
GOOGLE_HOSTS = ('accounts.google.com', 'apis.google.com', 'www.googleapis.com', 'docs.google.com')

CONFIG_JS = ("'use strict';\nconst RB_GOOGLE_DRIVE = Object.freeze("
             + json.dumps({'clientId': CLIENT, 'apiKey': KEY, 'appId': APP}) + ');\n')
EMPTY_CONFIG_JS = ("'use strict';\nconst RB_GOOGLE_DRIVE = Object.freeze("
                   + json.dumps({'clientId': '', 'apiKey': '', 'appId': ''}) + ');\n')
NO_FILE = 404

# Google's sign-in, as far as the page uses it. The test sets
# __driveTest.nextToken to say how the next request is answered; each request
# records its overrides and whether the page was within a click when it asked.
SIGN_IN_JS = r"""
(function () {
  const T = window.__driveTest = window.__driveTest || {};
  T.signInLoads = (T.signInLoads || 0) + 1;
  T.tokenConfigs = T.tokenConfigs || [];
  T.tokenRequests = T.tokenRequests || [];
  window.google = window.google || {};
  window.google.accounts = { oauth2: {
    initTokenClient(config) {
      T.tokenConfigs.push({ client_id: config.client_id, scope: config.scope,
        callback: typeof config.callback, error_callback: typeof config.error_callback });
      return { requestAccessToken(overrides) {
        T.tokenRequests.push({ overrides: overrides === undefined ? null : overrides,
                               active: navigator.userActivation.isActive });
        const a = T.nextToken || { kind: 'token' };
        setTimeout(() => {
          if (a.kind === 'error_callback') config.error_callback({ type: a.type });
          else if (a.kind === 'error') config.callback({ error: a.error });
          else config.callback({ access_token: a.token || T.token, expires_in: 3599,
                                 scope: a.scope || T.scope, token_type: 'Bearer' });
        }, 20);
      } };
    },
    hasGrantedAllScopes(response, ...scopes) {
      const granted = String(response.scope || '').split(' ');
      return scopes.every(s => granted.includes(s));
    },
    revoke() {}
  } };
})();
"""

# Google's loader and picker. Each picker built is recorded; shown, it first
# says it has loaded (as Google's does) and then answers __driveTest.nextPick.
PICKER_JS = r"""
(function () {
  const T = window.__driveTest = window.__driveTest || {};
  T.pickerLoads = (T.pickerLoads || 0) + 1;
  T.pickers = T.pickers || [];
  T.answered = T.answered || 0;
  window.gapi = { load(name, config) {
    T.gapiLoad = name;
    setTimeout(() => {
      class DocsView {
        constructor(viewId) { this.view = { viewId }; }
      }
      for (const m of ['setParent', 'setIncludeFolders', 'setSelectFolderEnabled', 'setMode',
                       'setOwnedByMe', 'setEnableDrives', 'setStarred', 'setMimeTypes', 'setQuery'])
        DocsView.prototype[m] = function (v) { this.view[m] = v; return this; };
      class PickerBuilder {
        constructor() { this.r = { views: [], features: [], shown: 0, disposed: false }; }
        addView(v) { this.r.views.push(v instanceof DocsView ? v.view : v); return this; }
        enableFeature(f) { this.r.features.push(f); return this; }
        setTitle(t) { this.r.title = t; return this; }
        setOAuthToken(t) { this.r.token = t; return this; }
        setDeveloperKey(k) { this.r.key = k; return this; }
        setAppId(a) { this.r.appId = a; return this; }
        setCallback(f) { this.f = f; return this; }
        build() {
          const r = this.r, f = this.f;
          T.pickers.push(r);
          return {
            setVisible(v) {
              if (!v) return this;
              r.shown++;
              const answer = T.nextPick || { action: 'cancel' };
              setTimeout(() => { f({ action: 'loaded' }); f(answer); T.answered++; }, 20);
              return this;
            },
            dispose() { r.disposed = true; }
          };
        }
      }
      window.google = window.google || {};
      window.google.picker = {
        PickerBuilder, DocsView,
        ViewId: { DOCS: 'all', FOLDERS: 'folders' },
        DocsViewMode: { GRID: 'grid', LIST: 'list' },
        Feature: { MULTISELECT_ENABLED: 'multiselectEnabled', NAV_HIDDEN: 'navHidden' },
        Action: { PICKED: 'picked', CANCEL: 'cancel', ERROR: 'error' },
        Response: { ACTION: 'action', DOCUMENTS: 'docs' },
        Document: { ID: 'id', NAME: 'name', MIME_TYPE: 'mimeType' }
      };
      (typeof config === 'function' ? config : config.callback)();
    }, 20);
  } };
})();
"""


def fixture(name):
    with open(os.path.join(HERE, 'fixtures', name), 'rb') as f:
        return f.read()


JSON_BYTES = json.dumps({'run': {'time': [0, 1, 2], 'value': [1.5, 2.5, 3.5]}}).encode()


def big_file():
    """An HDF5 file of four datasets of 5 MB each, d<i> holding k*(i+1) at k:
    each larger than the 4 MB from which the worker reads straight from the
    file rather than through its block cache, so that every read of one is
    a request, whatever was read before. Made here, so no data is committed."""
    import io
    import h5py
    import numpy as np
    out = io.BytesIO()
    with h5py.File(out, 'w') as f:
        runs = f.create_group('runs')
        for i in range(4):
            runs.create_dataset(f'd{i}', data=np.arange(655360, dtype='<f8') * (i + 1))
    return out.getvalue()
# id: (content type, bytes, resource key the file needs or None)
DRIVE_FILES = {
    'fileA': ('application/x-hdf5', fixture('sample-a.h5'), None),
    'fileM': ('application/octet-stream', fixture('matlab-v7.mat'), 'rk-1'),
    'fileJ': ('application/json', JSON_BYTES, None),
    'fileS': ('application/x-hdf5', fixture('sample-b.h5'), None),
    'fileL': ('application/x-hdf5', fixture('sample-a.h5'), None),
    'fileB': ('application/x-hdf5', big_file(), None),
}
# id: the name the Drive API gives the file, asked for its details
DRIVE_NAMES = {'fileA': 'sample-a.h5', 'fileM': 'matlab-v7.mat', 'fileJ': 'runs.json',
               'fileS': 'results/b.h5', 'fileL': 'big-a.h5', 'fileB': 'big.h5'}
# id: (status, reason, message)
DRIVE_ERRORS = {
    'denied': (403, 'cannotDownloadFile', 'The user does not have permission to download this file.'),
    'gone': (404, 'notFound', 'File not found: gone.'),
    'expired': (401, 'authError', 'Invalid Credentials'),
}


def doc(fid, name, mime='application/octet-stream', size=None, key=''):
    d = {'id': fid, 'name': name, 'mimeType': mime, 'resourceKey': key}
    if size is not None:
        d['sizeBytes'] = size
    return d


def picked(*docs):
    return {'action': 'picked', 'docs': list(docs)}


failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


def header(headers, name):
    for k, v in (headers or {}).items():
        if k.lower() == name.lower():
            return v
    return None


class Page:
    def __init__(self, ws):
        self.ws = ws
        self.n = 0
        self.pending = {}
        self.sid = None
        self.requests = []       # every request the page made: url, method, headers
        self.drive = []          # Drive API file requests the stand-in answered
        self.preflights = []     # CORS preflights it answered
        self.scripts = []        # Google's scripts asked for
        self.unexpected = []     # intercepted addresses nothing here serves
        self.errors = []         # console.error lines and exceptions
        self.config = None       # rb-drive-config.js to serve, NO_FILE, or None for the real one
        self.fail_scripts = set()
        self.valid_tokens = {TOKEN}   # the tokens the Drive API takes

    async def call(self, method, params=None, timeout=60):
        self.n += 1
        i = self.n
        msg = {'id': i, 'method': method, 'params': params or {}}
        if self.sid and not method.startswith('Target.'):
            msg['sessionId'] = self.sid
        fut = asyncio.get_event_loop().create_future()
        self.pending[i] = fut
        await self.ws.send(json.dumps(msg))
        return await asyncio.wait_for(fut, timeout)

    async def pump(self):
        async for raw in self.ws:
            r = json.loads(raw)
            m = r.get('method')
            if m == 'Fetch.requestPaused':
                asyncio.ensure_future(self.serve(r['params']))
            elif m == 'Network.requestWillBeSent':
                q = r['params']['request']
                self.requests.append({'url': q['url'], 'method': q['method'], 'headers': q.get('headers', {})})
            elif m == 'Runtime.consoleAPICalled' and r['params']['type'] == 'error':
                self.errors.append(' '.join(str(a.get('value', a.get('description', '')))
                                            for a in r['params']['args'])[:600])
            elif m == 'Runtime.exceptionThrown':
                d = r['params']['exceptionDetails']
                self.errors.append('EXCEPTION ' + str(d.get('exception', {}).get('description') or d.get('text', ''))[:600])
            if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                self.pending[r['id']].set_result(r)

    async def fulfill(self, rid, status, headers, body):
        await self.call('Fetch.fulfillRequest', {
            'requestId': rid, 'responseCode': status,
            'responseHeaders': [{'name': k, 'value': v} for k, v in headers.items()],
            'body': base64.b64encode(body).decode()})

    async def serve(self, p):
        rid = p['requestId']
        req = p['request']
        url = req['url']
        parts = urllib.parse.urlsplit(url)
        try:
            if parts.netloc == f'127.0.0.1:{HTTP}' and parts.path.endswith('/rb-drive-config.js'):
                if self.config is None:
                    await self.call('Fetch.continueRequest', {'requestId': rid})
                elif self.config == NO_FILE:
                    await self.fulfill(rid, 404, {'Content-Type': 'text/plain'}, b'not here')
                else:
                    await self.fulfill(rid, 200, {'Content-Type': 'text/javascript'}, self.config.encode())
                return
            if url.startswith(SIGN_IN) or url.startswith(PICKER):
                base = SIGN_IN if url.startswith(SIGN_IN) else PICKER
                self.scripts.append(base)
                if base in self.fail_scripts:
                    await self.fulfill(rid, 404, {'Content-Type': 'text/plain'}, b'not here')
                else:
                    body = SIGN_IN_JS if base == SIGN_IN else PICKER_JS
                    await self.fulfill(rid, 200, {'Content-Type': 'text/javascript'}, body.encode())
                return
            if url.startswith(FILES_API):
                cors = {'Access-Control-Allow-Origin': ORIGIN, 'Access-Control-Expose-Headers': 'content-length'}
                if req['method'] == 'OPTIONS':
                    self.preflights.append(url)
                    asked = header(req['headers'], 'Access-Control-Request-Headers') or ''
                    await self.fulfill(rid, 204, {**cors, 'Access-Control-Allow-Methods': 'GET',
                                                  'Access-Control-Allow-Headers': asked}, b'')
                    return
                fid = urllib.parse.unquote(parts.path[len('/drive/v3/files/'):])
                auth = header(req['headers'], 'Authorization')
                keys = header(req['headers'], 'X-Goog-Drive-Resource-Keys')
                rng = header(req['headers'], 'Range')
                self.drive.append({'id': fid, 'query': urllib.parse.parse_qs(parts.query),
                                   'auth': auth, 'keys': keys, 'range': rng})

                async def error(status, reason, message):
                    body = json.dumps({'error': {'code': status, 'message': message,
                                                 'errors': [{'reason': reason, 'message': message}]}}).encode()
                    await self.fulfill(rid, status, {**cors, 'Content-Type': 'application/json'}, body)

                if auth not in {f'Bearer {t}' for t in self.valid_tokens}:
                    await error(401, 'authError', 'Invalid Credentials')
                elif fid in DRIVE_ERRORS:
                    await error(*DRIVE_ERRORS[fid])
                elif fid not in DRIVE_FILES or (DRIVE_FILES[fid][2] and keys != f'{fid}/{DRIVE_FILES[fid][2]}'):
                    # A file shared by link is not found without its resource key.
                    await error(404, 'notFound', f'File not found: {fid}.')
                elif 'alt' not in urllib.parse.parse_qs(parts.query):   # its details, as JSON
                    kind, body, _ = DRIVE_FILES[fid]
                    details = {'name': DRIVE_NAMES[fid], 'mimeType': kind, 'size': str(len(body))}
                    await self.fulfill(rid, 200, {**cors, 'Content-Type': 'application/json'},
                                       json.dumps(details).encode())
                else:
                    kind, body, _ = DRIVE_FILES[fid]
                    m = re.fullmatch(r'bytes=(\d+)-(\d*)', rng or '')
                    if rng and m:   # a part, as Drive answers a range
                        a = int(m.group(1))
                        b = min(int(m.group(2)) if m.group(2) else len(body) - 1, len(body) - 1)
                        part = body[a:b + 1]
                        await self.fulfill(rid, 206, {**cors, 'Content-Type': kind,
                                                      'Content-Length': str(len(part)),
                                                      'Content-Range': f'bytes {a}-{b}/{len(body)}'}, part)
                    else:
                        await self.fulfill(rid, 200, {**cors, 'Content-Type': kind,
                                                      'Content-Length': str(len(body))}, body)
                return
            self.unexpected.append(url)
            await self.call('Fetch.failRequest', {'requestId': rid, 'errorReason': 'BlockedByClient'})
        except Exception as e:  # never leave a request hanging
            print(f'      (serving {url} failed: {e})')
            try:
                await self.call('Fetch.failRequest', {'requestId': rid, 'errorReason': 'Failed'})
            except Exception:
                pass

    async def ev(self, expr, timeout=60):
        r = await self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True,
                                                 'awaitPromise': True}, timeout)
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:400]
        return res.get('result', {}).get('value')

    async def click(self, selector):
        """A real click, with the mouse: what lets a page open a window."""
        pos = await self.ev("(() => { const e = document.querySelector(%s); if (!e) return null;"
                            " const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()"
                            % json.dumps(selector))
        if not pos:
            raise RuntimeError(f'nothing to click at {selector}')
        await self.click_at(*pos)

    async def click_at(self, x, y):
        for kind in ('mousePressed', 'mouseReleased'):
            await self.call('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y,
                                                         'button': 'left', 'clickCount': 1})

    async def load(self, n, config, state=None):
        """The page, afresh; with `state`, as Drive's Open with opens it (a
        dict as JSON, a string as it is)."""
        self.config = config
        self.fail_scripts = set()
        query = f'drive={n}'
        if state is not None:
            query += '&state=' + urllib.parse.quote(state if isinstance(state, str) else json.dumps(state))
        await self.call('Page.navigate', {'url': f'{ORIGIN}/rb.html?{query}'})
        await settle(self, "document.readyState === 'complete' && typeof setUpGoogleDrive === 'function'"
                           " && typeof waitForH5Wasm === 'function'", True, tries=200)
        await self.ev('waitForH5Wasm().then(() => true)', timeout=60)
        # Merged into what the stand-ins have recorded: opened by Drive, the
        # page loads Google's scripts by itself, maybe before this runs.
        await self.ev('window.__driveTest = Object.assign(window.__driveTest || {},'
                      ' { token: %s, scope: %s, nextToken: { kind: "token" } }); true'
                      % (json.dumps(TOKEN), json.dumps(SCOPE)))


async def settle(page, expr, want=True, tries=100, pause=0.1):
    got = None
    for _ in range(tries):
        got = await page.ev(expr)
        if got == want:
            return got
        await asyncio.sleep(pause)
    return got


T = 'window.__driveTest'
DIALOG_SHOWN = "document.getElementById('driveDialog').style.display !== 'none'"
DIALOG_ERROR = "document.getElementById('driveError').textContent"
CHOOSE = "document.getElementById('driveChooseBtn')"
BUTTON = '[data-on-click="openGoogleDrive"]'


async def pick(page, answer):
    """Set what the picker answers, and wait for the next answer to be opened."""
    await page.ev(f'{T}.nextPick = {json.dumps(answer)}; true')
    return await page.ev(f'{T}.answered')


async def opened(page, before):
    """Wait for the picker's next answer, and for the files of it to be opened."""
    await settle(page, f'{T}.answered > {before}', True)
    return await page.ev('(async () => { await driveQueue; return true; })()', timeout=60)


def new_errors(page, since):
    return '\n'.join(page.errors[since:])


async def main():
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        page = Page(bws)
        asyncio.ensure_future(page.pump())
        tid = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        page.sid = (await page.call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
        try:
            for m in ('Runtime.enable', 'Page.enable', 'Network.enable'):
                await page.call(m)
            await page.call('Network.setCacheDisabled', {'cacheDisabled': True})
            await page.call('Emulation.setDeviceMetricsOverride',
                            {'width': 1400, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
            await page.call('Fetch.enable', {'patterns': [
                {'urlPattern': '*rb-drive-config.js*'},
                {'urlPattern': 'https://accounts.google.com/*'},
                {'urlPattern': 'https://apis.google.com/*'},
                {'urlPattern': 'https://www.googleapis.com/*'},
                {'urlPattern': 'https://docs.google.com/*'}]})

            # --- not configured ---------------------------------------------
            await page.load(1, EMPTY_CONFIG_JS)
            check('with no project the Google Drive button is in the header but hidden',
                  await page.ev(f"(() => {{ const b = document.querySelector('{BUTTON}');"
                                " return !!b && b.hidden && getComputedStyle(b).display === 'none'; })()"))
            check('and the welcome panel does not name it',
                  await page.ev("getComputedStyle(document.querySelector('#info .rb-drive-only')).display"), 'none')
            check('and the root is not marked ready',
                  await page.ev("document.documentElement.classList.contains('rb-drive-ready')"), False)
            check('nothing was fetched from Google',
                  [r['url'] for r in page.requests if urllib.parse.urlsplit(r['url']).hostname in GOOGLE_HOSTS], [])

            errors_before = len(page.errors)
            await page.load(2, NO_FILE)
            check('with the project\'s file missing the button stays hidden too',
                  await page.ev(f"document.querySelector('{BUTTON}').hidden"))
            check('and the page works on: nothing but the missing file went wrong',
                  [e for e in page.errors[errors_before:] if 'rb-drive-config' not in e], [])
            check('and still nothing was fetched from Google',
                  [r['url'] for r in page.requests if urllib.parse.urlsplit(r['url']).hostname in GOOGLE_HOSTS], [])

            # --- configured -------------------------------------------------
            page.requests.clear()
            await page.load(3, CONFIG_JS)
            check('with a project the button shows, labelled Google Drive',
                  await page.ev(f"(() => {{ const b = document.querySelector('{BUTTON}');"
                                " return !b.hidden && getComputedStyle(b).display !== 'none' && b.textContent.trim(); })()"),
                  'Google Drive')
            check('beside URL, before Sample Data',
                  await page.ev("[...document.querySelectorAll('header .add-file-btn')].map(b => b.dataset.onClick).join(' ')"),
                  'openFilePicker openUrlDialog openGoogleDrive openSampleDataDialog openVscodeDialog')
            check('and the welcome panel names it, among the ways to load files and for large ones',
                  await page.ev("[...document.querySelectorAll('#info .rb-drive-only')]"
                                ".map(e => getComputedStyle(e).display).join(' ')"), 'inline inline')
            check('but nothing is fetched from Google before a click',
                  [r['url'] for r in page.requests if urllib.parse.urlsplit(r['url']).hostname in GOOGLE_HOSTS], [])

            # The first click: the dialog, and Google's two scripts behind it.
            await page.click(BUTTON)
            check('the first click opens the dialog', await settle(page, DIALOG_SHOWN))
            check('which says the files are read here and sent nowhere else',
                  await page.ev("document.getElementById('driveDialog').textContent.includes('sent nowhere else')"))
            check('and links to where the access is withdrawn, in a tab of its own',
                  await page.ev("(() => { const a = document.querySelector('#driveDialog a');"
                                " return [a.href, a.target, a.rel]; })()"),
                  ['https://myaccount.google.com/connections', '_blank', 'noopener noreferrer'])
            check('and to the site\'s privacy page, in a tab of its own, so no file open here is lost',
                  await page.ev("(() => { const a = document.querySelector('#driveDialog a[href^=\"privacy.html\"]');"
                                " return a && [new URL(a.href).pathname, a.target]; })()"),
                  ['/privacy.html', '_blank'])
            check('Choose files is offered once Google\'s scripts are loaded',
                  await settle(page, f"!{CHOOSE}.disabled && {CHOOSE}.textContent"), 'Choose files…')
            check('the two scripts were each fetched once', sorted(page.scripts), sorted([SIGN_IN, PICKER]))
            check('the picker library was asked for', await page.ev(f'{T}.gapiLoad'), 'picker')
            check('the sign-in was set up with the project\'s client, for drive.file alone',
                  await page.ev(f'{T}.tokenConfigs'),
                  [{'client_id': CLIENT, 'scope': SCOPE, 'callback': 'function', 'error_callback': 'function'}])

            # Choose files: Google is asked, from the click; the picker opens.
            before = await pick(page, picked(
                doc('fileA', 'sample-a.h5', 'application/x-hdf5', 69208),
                doc('fileM', 'matlab-v7.mat', 'application/octet-stream', 5811, 'rk-1'),
                doc('fileJ', 'runs.json', 'application/json'),
                doc('fileS', 'results/b.h5', 'application/x-hdf5')))
            errors_before = len(page.errors)
            await page.click('#driveChooseBtn')
            await opened(page, before)
            requests = await page.ev(f'{T}.tokenRequests')
            check('Choose files asked Google once, letting the reader choose an account',
                  requests, [{'overrides': {}, 'active': True}])
            check('the dialog closed', await page.ev(DIALOG_SHOWN), False)
            pk = await page.ev(f'{T}.pickers[0]')
            check('the picker was given the token, the key and the project number',
                  [pk['token'], pk['key'], pk['appId']], [TOKEN, KEY, APP])
            check('it shows My Drive from the top, what is shared, and shared drives, in a list',
                  pk['views'], [
                      {'viewId': 'all', 'setParent': 'root', 'setIncludeFolders': True,
                       'setSelectFolderEnabled': False, 'setMode': 'list'},
                      {'viewId': 'all', 'setOwnedByMe': False, 'setMode': 'list'},
                      {'viewId': 'all', 'setEnableDrives': True, 'setIncludeFolders': True,
                       'setSelectFolderEnabled': False, 'setMode': 'list'}])
            check('several files can be picked at once', pk['features'], ['multiselectEnabled'])
            check('and it is put away once answered', [pk['shown'], pk['disposed']], [1, True])

            order = await page.ev('fileOrder.slice()')
            check('the HDF5 file opened', 'sample-a.h5' in order)
            check('the MAT-file opened', 'matlab-v7.mat' in order)
            check('the JSON file opened', 'runs.json' in order)
            check('a name with a slash in it stays one level', 'results_b.h5' in order)
            check('each has its tab', await page.ev(
                "['sample-a.h5', 'matlab-v7.mat', 'runs.json', 'results_b.h5'].every(n =>"
                " [...document.querySelectorAll('#fileTabs .file-tab')].some(t => t.dataset.file === n))"))
            check('the HDF5 file reads as its fixture does',
                  await page.ev("loadedFiles['sample-a.h5'].keys().length > 0"))
            check('nothing went wrong on the way', new_errors(page, errors_before), '')
            check('the ticker is put away', await page.ev("document.getElementById('fileLoadTicker').hidden"))

            drive = {d['id']: d for d in page.drive}
            check('each file was asked of the Drive API once',
                  sorted(d['id'] for d in page.drive), ['fileA', 'fileJ', 'fileM', 'fileS'])
            check('for its content, shared drives included',
                  all(d['query'] == {'alt': ['media'], 'supportsAllDrives': ['true']} for d in page.drive))
            check('with the token', all(d['auth'] == f'Bearer {TOKEN}' for d in page.drive))
            check('the file shared by link with its resource key', drive['fileM']['keys'], 'fileM/rk-1')
            check('and the others without one', [drive[i]['keys'] for i in ('fileA', 'fileJ', 'fileS')], [None] * 3)
            if page.preflights:
                print(f'      ({len(page.preflights)} CORS preflights were answered by the interception)')

            carrying = [r['url'] for r in page.requests
                        if TOKEN in r['url'] or TOKEN in json.dumps(r['headers'])]
            check('the token went with those requests and with no other',
                  sorted(set(urllib.parse.urlsplit(u).path for u in carrying)),
                  sorted(f'/drive/v3/files/{i}' for i in ('fileA', 'fileJ', 'fileM', 'fileS')))
            check('and it is in no storage', await page.ev(
                "[JSON.stringify({...localStorage}), JSON.stringify({...sessionStorage}), document.cookie]"
                f".some(s => s.includes({json.dumps(TOKEN)}))"), False)

            # A second click: straight to the picker. A cancel does nothing.
            before = await pick(page, {'action': 'cancel'})
            errors_before = len(page.errors)
            await page.click(BUTTON)
            await opened(page, before)
            check('a second click goes straight to the picker, asking Google nothing',
                  [await page.ev(f'{T}.tokenRequests.length'), await page.ev(f'{T}.pickers.length'),
                   await page.ev(DIALOG_SHOWN)], [1, 2, False])
            check('and a cancel opens nothing and says nothing',
                  [await page.ev('fileOrder.length'), new_errors(page, errors_before)], [len(order), ''])

            # Refused before any request.
            asked = len(page.drive)
            before = await pick(page, picked(
                doc('doc1', 'Notes', 'application/vnd.google-apps.document'),
                doc('fold1', 'Results', 'application/vnd.google-apps.folder'),
                doc('big1', 'big.mat', 'application/octet-stream', 2 * 1024 ** 3),
                doc('../up', 'up.h5')))
            errors_before = len(page.errors)
            await page.click(BUTTON)
            await opened(page, before)
            said = new_errors(page, errors_before)
            check('a Google Docs file is refused: it has no file of its own',
                  'Notes lives only in Google Drive' in said)
            check('a folder is refused, with where to look instead', 'Results is a folder' in said)
            check('a file read whole that is over the limit is refused before it is fetched', 'big.mat is 2.0 GB' in said)
            check('an ID that is no Drive ID is refused', 'the picker gave the file ID "../up"' in said)
            check('and none of them was asked of Drive', len(page.drive), asked)

            check('an HDF5 file of 256 MB or more is read a piece at a time instead, whatever its size,'
                  ' and a smaller one, or one of another kind, whole', await page.ev(
                      "[['huge.h5', 2 * 1024 ** 3], ['big.h5', 256 * 1024 ** 2], ['small.h5', 10 * 1024 ** 2],"
                      " ['huge.mat', 2 * 1024 ** 3], ['huge.json', 2 * 1024 ** 3], ['nosize.h5', NaN]]"
                      ".map(([name, size]) => driveWantsLazy({ name, size }))"),
                  [True, True, False, False, False, False])

            # Drive's refusals, in words.
            before = await pick(page, picked(doc('denied', 'locked.h5'), doc('gone', 'moved.h5')))
            errors_before = len(page.errors)
            await page.click(BUTTON)
            await opened(page, before)
            said = new_errors(page, errors_before)
            check('a file whose owner stops downloads is said so',
                  'The owner of locked.h5 does not let it be downloaded' in said)
            check('a file Drive no longer has for this page is said so',
                  'Google Drive has no file moved.h5 that this page may open' in said)
            check('the banner shows the last of them',
                  'moved.h5' in (await page.ev("document.querySelector('#failureBanner .failure-banner-text').textContent")))

            # A 401: the access is forgotten, and the next click asks again.
            before = await pick(page, picked(doc('expired', 'late.h5')))
            errors_before = len(page.errors)
            await page.click(BUTTON)
            await opened(page, before)
            check('a token Google no longer takes is said so',
                  'Google no longer accepts the access given' in new_errors(page, errors_before))
            check('and forgotten', await page.ev('driveToken'), None)
            before = await pick(page, {'action': 'cancel'})
            await page.click(BUTTON)
            await opened(page, before)
            check('so the next click asks Google again, from the click, without the account chooser',
                  (await page.ev(f'{T}.tokenRequests'))[1:], [{'overrides': {'prompt': ''}, 'active': True}])
            check('and goes on to the picker', await page.ev(f'{T}.pickers.length'), 6)

            # Google's answers that open nothing are said in the dialog.
            await page.ev('driveToken = null; true')
            await page.ev(f'{T}.nextToken = {{ kind: "error", error: "access_denied" }}; true')
            await page.click(BUTTON)
            check('access refused on Google\'s page is said in the dialog',
                  await settle(page, f'{DIALOG_SHOWN} && {DIALOG_ERROR}'),
                  'Google Drive was not opened: access was not given.')
            await page.ev(f'{T}.nextToken = {{ kind: "token", scope: "openid email" }}; true')
            await page.click('#driveChooseBtn')
            check('the Drive box left unticked is said, with what to do',
                  await settle(page, f"{DIALOG_ERROR}.includes('tick it')"))
            check('and opens no picker', await page.ev(f'{T}.pickers.length'), 6)
            await page.ev(f'{T}.nextToken = {{ kind: "error_callback", type: "popup_failed_to_open" }}; true')
            await page.click('#driveChooseBtn')
            check('Google\'s window blocked is said, with what to do',
                  await settle(page, f"{DIALOG_ERROR}.includes('allow pop-ups')"))
            await page.ev(f'{T}.nextToken = {{ kind: "error_callback", type: "popup_closed" }}; true')
            await page.click('#driveChooseBtn')
            check('Google\'s window closed early is said',
                  await settle(page, f"{DIALOG_ERROR}.includes('closed before it finished')"))
            check('each of them asked from a click', all(r['active'] for r in await page.ev(f'{T}.tokenRequests')))
            await page.ev("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); true")
            check('Escape closes the dialog', await page.ev(DIALOG_SHOWN), False)
            await page.ev(f'{T}.nextToken = {{ kind: "error", error: "access_denied" }}; true')
            await page.click(BUTTON)
            check('a click on the button with access refused opens it again', await settle(page, DIALOG_SHOWN))
            await page.click_at(20, 600)
            check('and a click beside it closes it', await settle(page, f'!({DIALOG_SHOWN})'))

            # --- a script of Google's that does not load --------------------
            page.scripts.clear()
            await page.load(4, CONFIG_JS)
            page.fail_scripts = {PICKER}
            await page.click(BUTTON)
            check('a script that does not load is said, naming where from',
                  await settle(page, f"{DIALOG_ERROR}.startsWith('Google’s file picker could not be loaded from apis.google.com')"))
            check('and the button offers to try again',
                  [await page.ev(f'{CHOOSE}.disabled'), await page.ev(f'{CHOOSE}.textContent')], [False, 'Try again'])
            page.fail_scripts = set()
            await page.click('#driveChooseBtn')
            check('Try again loads it', await settle(page, f'{CHOOSE}.textContent'), 'Choose files…')
            check('the one that failed again, and not the one that loaded',
                  sorted(page.scripts), sorted([SIGN_IN, PICKER, PICKER]))
            check('and the error is gone', await page.ev(DIALOG_ERROR), '')

            # A window that never opened: the next try still offers the accounts.
            await page.ev(f'{T}.nextToken = {{ kind: "error_callback", type: "popup_failed_to_open" }}; true')
            await page.click('#driveChooseBtn')
            await settle(page, f"{DIALOG_ERROR}.includes('allow pop-ups')")
            await page.ev(f'{T}.nextToken = {{ kind: "token" }}; true')
            before = await pick(page, {'action': 'cancel'})
            await page.click('#driveChooseBtn')
            await opened(page, before)
            check('Google\'s window blocked leaves the choice of account for the next try',
                  [r['overrides'] for r in await page.ev(f'{T}.tokenRequests')], [{}, {}])

            # --- a large file, a piece at a time ------------------------------
            await page.load(5, CONFIG_JS)
            await page.ev("localStorage.setItem('kvot-rb-lazy', 'always'); true")
            page.drive.clear()
            size_a = len(DRIVE_FILES['fileL'][1])
            size_b = len(DRIVE_FILES['fileB'][1])
            before = await pick(page, picked(
                doc('fileL', 'big-a.h5', 'application/x-hdf5', size_a),
                doc('fileB', 'big.h5', 'application/x-hdf5', size_b),
                doc('fileM', 'matlab-v7.mat', 'application/octet-stream', len(DRIVE_FILES['fileM'][1]), 'rk-1')))
            errors_before = len(page.errors)
            await page.click(BUTTON)
            await settle(page, f"!{CHOOSE}.disabled")
            await page.click('#driveChooseBtn')
            await opened(page, before)
            check('a large HDF5 file opens to be read a piece at a time',
                  await page.ev("!!lazyStateOf(loadedFiles['big-a.h5']) && !!lazyStateOf(loadedFiles['big.h5'])"))
            check('a MAT-file is still read whole, as one from disk is',
                  [await page.ev("'matlab-v7.mat' in loadedFiles"),
                   await page.ev("!lazyStateOf(loadedFiles['matlab-v7.mat'])")], [True, True])
            check('and its tree is there', await page.ev(
                "lazyStateOf(loadedFiles['big-a.h5']).paths.includes('/biosphere/vault_A/mire/total/Ac-227')"))
            check('nothing went wrong on the way', new_errors(page, errors_before), '')
            await page.ev("""(async () => {
              const r = await fetch('./resources/tests/rb/fixtures/sample-a.h5');
              await ingestFileBuffer('mem-a.h5', await r.arrayBuffer(), 'test'); return true; })()""")
            SAME = """(async (path) => {
              const s = lazyStateOf(loadedFiles['big-a.h5']);
              await s.ensureGroup(path.slice(0, path.lastIndexOf('/')));
              await s.ensureValues([path]);
              const lazy = s.value(path);
              if (!lazy) return 'nothing read';
              const mem = loadedFiles['mem-a.h5'].get(path).value;
              return JSON.stringify(Array.from(lazy)) === JSON.stringify(Array.from(mem)) ? lazy.length : 'differs';
            })(%s)"""
            check('a dataset read from it is the same as read whole, value for value',
                  await page.ev(SAME % json.dumps('/biosphere/vault_A/mire/total/Ac-227')), 720)
            BIG = """(async (i) => {
              const s = lazyStateOf(loadedFiles['big.h5']);
              await s.ensureGroup('/runs');
              await s.ensureValues(['/runs/d' + i]);
              const v = s.value('/runs/d' + i);
              if (!v) return 'nothing read';
              for (let k = 0; k < v.length; k++) if (v[k] !== k * (i + 1)) return 'differs at ' + k;
              return v.length;
            })(%d)"""
            await page.ev("lazyStateOf(loadedFiles['big.h5']).ensureGroup('/runs').then(() => true)")
            seen = len(page.drive)
            check('a dataset of 5 MB is read right', await page.ev(BIG % 0), 655360)
            direct = [d for d in page.drive[seen:] if d['id'] == 'fileB']
            check('in one request for its own range, past the block cache',
                  [len(direct), direct and int(direct[0]['range'].split('-')[1]) - int(direct[0]['range'][6:].split('-')[0]) + 1 >= 5242880],
                  [1, True])
            asked = [d for d in page.drive if d['id'] in ('fileL', 'fileB')]
            check('every request for them was for a range, never the whole file',
                  all(d['range'] and d['range'].startswith('bytes=') for d in asked))
            check('and carried the token', all(d['auth'] == f'Bearer {TOKEN}' for d in asked))
            print(f'      ({len([d for d in asked if d["id"] == "fileL"])} range requests for a file of {size_a} bytes,'
                  f' {len([d for d in asked if d["id"] == "fileB"])} for one of {size_b})')

            # Google stops taking the token: the next read says so.
            page.valid_tokens = {TOKEN2}
            await page.ev("hideFailureBanner(); true")
            check('a read once Google has stopped taking the access reads nothing',
                  await page.ev(BIG % 1), 'nothing read')
            check('and says so, and how to go on', await settle(page,
                  "((document.querySelector('#failureBanner.show .failure-banner-text') || {}).textContent || '')"
                  ".startsWith('Google’s access to big.h5 has run out')", True, tries=50))
            check('the access is forgotten', await page.ev('driveToken'), None)
            check('and the file stays open', await page.ev("!!lazyStateOf(loadedFiles['big.h5'])"))

            # A new token: the worker reads on with it.
            await page.ev(f'{T}.nextToken = {{ kind: "token", token: {json.dumps(TOKEN2)} }}; true')
            before = await pick(page, {'action': 'cancel'})
            await page.click(BUTTON)
            await opened(page, before)
            seen = len(page.drive)
            check('once Google gives a new token, the same read works', await page.ev(BIG % 1), 655360)
            check('with the new token', [d['auth'] for d in page.drive[seen:] if d['id'] == 'fileB'],
                  [f'Bearer {TOKEN2}'])
            await page.ev("localStorage.removeItem('kvot-rb-lazy'); true")

            # --- opened by "Open with" in Google Drive -------------------------
            OPENED = "(async () => { await driveQueue; return true; })()"
            SHOWN_PS = ("[...document.querySelectorAll('#driveDialog p')]"
                        ".filter(p => getComputedStyle(p).display !== 'none').map(p => p.id || 'access').join(' ')")
            page.drive.clear()
            page.valid_tokens = {TOKEN}
            await page.load(6, CONFIG_JS, {'ids': ['fileA', 'fileM'], 'resourceKeys': {'fileM': 'rk-1'},
                                           'action': 'open', 'userId': USER})
            errors_before = len(page.errors)
            check('opened by Drive\'s Open with, the page opens the dialog by itself', await settle(page, DIALOG_SHOWN))
            check('saying what Drive asked for', await page.ev("document.getElementById('driveLaunchText').textContent"),
                  'Google Drive asked the Data Browser to open 2 files. They open here as files from your own'
                  ' disk do: read in this browser, and sent nowhere else.')
            check('and not the picker\'s text, nor the offer to add the page to Drive', await page.ev(SHOWN_PS),
                  'driveLaunchText access')
            check('its button is Open, once Google\'s scripts are loaded',
                  await settle(page, f"!{CHOOSE}.disabled && {CHOOSE}.textContent"), 'Open')
            check('Drive\'s request is gone from the address, the rest of it kept',
                  await page.ev('location.search'), '?drive=6')
            check('nothing is asked of Drive before the click', page.drive, [])
            await page.click('#driveChooseBtn')
            await settle(page, "['sample-a.h5', 'matlab-v7.mat'].every(n => n in loadedFiles)", True, tries=200)
            await page.ev(OPENED, timeout=60)
            check('Open asked Google, from the click, straight for the account Drive is open in',
                  await page.ev(f'{T}.tokenRequests'), [{'overrides': {'prompt': '', 'login_hint': USER}, 'active': True}])
            details = [d for d in page.drive if 'alt' not in d['query']]
            check('each file\'s name, type and size were asked of Drive once, shared drives included',
                  [sorted(d['id'] for d in details),
                   all(d['query'] == {'fields': ['name,mimeType,size'], 'supportsAllDrives': ['true']} for d in details)],
                  [['fileA', 'fileM'], True])
            check('then each file\'s content, as a picked file\'s is',
                  sorted(d['id'] for d in page.drive if d['query'].get('alt') == ['media']), ['fileA', 'fileM'])
            check('every request with the token', all(d['auth'] == f'Bearer {TOKEN}' for d in page.drive))
            check('the file shared by link with its resource key, both times',
                  [d['keys'] for d in page.drive if d['id'] == 'fileM'], ['fileM/rk-1'] * 2)
            check('each opened under the name Drive gave it, with its tab', await page.ev(
                "['sample-a.h5', 'matlab-v7.mat'].every(n => n in loadedFiles"
                " && [...document.querySelectorAll('#fileTabs .file-tab')].some(t => t.dataset.file === n))"))
            check('no picker was shown, and the dialog closed',
                  [await page.ev(f'{T}.pickers.length'), await page.ev(DIALOG_SHOWN)], [0, False])
            check('nothing went wrong on the way', new_errors(page, errors_before), '')

            # A request from Drive that cannot be acted on: said, the picker offered instead.
            asked = len(page.drive)
            for n, state, said in (
                    (7, {'ids': ['../up'], 'action': 'open'},
                     'Google Drive asked this page to open a file by an ID that is not a Drive file’s.'),
                    (8, '{"ids": ["fileA"', 'This page was opened with a request from Google Drive that it cannot read.'),
                    (9, {'action': 'create', 'folderId': 'root'},
                     'The Data Browser makes no new files in Google Drive: open one that is there.'),
                    (10, {'exportIds': ['doc1'], 'action': 'open'},
                     'Google Docs, Sheets and Slides files live only in Google Drive, and have no file of their'
                     ' own to open here.')):
                await page.load(n, CONFIG_JS, state)
                check(f'a request from Drive that cannot be acted on is said: “{said[:48]}…”',
                      await settle(page, f'{DIALOG_SHOWN} && {DIALOG_ERROR}'), said)
            check('the picker is offered instead, and the offer to add the page to Drive',
                  [await settle(page, f"!{CHOOSE}.disabled && {CHOOSE}.textContent"), await page.ev(SHOWN_PS)],
                  ['Choose files…', 'drivePickText access driveInstallLine'])
            check('nothing was asked of Drive for them', len(page.drive), asked)

            # A file Drive will not show the page; no account named, so the reader chooses one.
            await page.load(11, CONFIG_JS, {'ids': ['gone', 'fileA'], 'action': 'open'})
            await settle(page, f"!{CHOOSE}.disabled")
            errors_before = len(page.errors)
            await page.click('#driveChooseBtn')
            await settle(page, "'sample-a.h5' in loadedFiles", True, tries=200)
            await page.ev(OPENED, timeout=60)
            check('with no account named, Open lets the reader choose one',
                  await page.ev(f'{T}.tokenRequests'), [{'overrides': {}, 'active': True}])
            check('a file Drive will not show the page is said, with what to do',
                  'Google Drive did not let this page see the file it asked it to open' in new_errors(page, errors_before))
            check('and the other still opens', await page.ev("'sample-a.h5' in loadedFiles"))

            # Cancel lets Drive's file go; the button then works as it does.
            await page.load(12, CONFIG_JS, {'ids': ['fileA'], 'action': 'open', 'userId': USER})
            check('one file is said as one', await settle(page,
                  "document.getElementById('driveLaunchText').textContent"
                  ".startsWith('Google Drive asked the Data Browser to open a file. It opens here')"))
            await settle(page, f"!{CHOOSE}.disabled")
            await page.click('#driveDialog .url-btn-cancel')
            check('Cancel closes the dialog', await page.ev(DIALOG_SHOWN), False)
            before = await pick(page, {'action': 'cancel'})
            await page.click(BUTTON)
            await opened(page, before)
            check('and lets the file go: the button asks Google and shows the picker, as it does',
                  [await page.ev(f'{T}.tokenRequests'), await page.ev(f'{T}.pickers.length'),
                   await page.ev('Object.keys(loadedFiles).length')],
                  [[{'overrides': {}, 'active': True}], 1, 0])

            # --- the Data Browser added to Drive's Open with menu -------------
            await page.load(13, CONFIG_JS)
            await page.click(BUTTON)
            check('the dialog offers to add the Data Browser to Drive\'s Open with menu, once Google\'s scripts load',
                  await settle(page, "(() => { const b = document.getElementById('driveInstallBtn');"
                                     " return getComputedStyle(b.closest('p')).display !== 'none' && !b.disabled"
                                     " && b.textContent; })()"), 'add the Data Browser to that menu')
            await page.ev(f'{T}.nextToken = {{ kind: "token", scope: {json.dumps(SCOPE)} }}; true')
            await page.click('#driveInstallBtn')
            check('it asks Google, from the click, for that as well as for the files',
                  await page.ev(f'{T}.tokenRequests'), [{'overrides': {'scope': f'{SCOPE} {INSTALL}'}, 'active': True}])
            check('that box left unticked on Google\'s page is said',
                  await settle(page, f"{DIALOG_ERROR}.startsWith('The Data Browser was not added to Google Drive')"))
            check('and the offer stays', await page.ev(f"({SHOWN_PS}).includes('driveInstallLine')"))
            await page.ev(f'{T}.nextToken = {{ kind: "token", scope: {json.dumps(f"{SCOPE} {INSTALL}")} }}; true')
            await page.click('#driveInstallBtn')
            check('asked again, without the accounts again',
                  (await page.ev(f'{T}.tokenRequests'))[1:],
                  [{'overrides': {'prompt': '', 'scope': f'{SCOPE} {INSTALL}'}, 'active': True}])
            check('given, it is said done, with where to look', await settle(page,
                  "document.getElementById('driveNote').textContent"
                  ".startsWith('Done: Google has let the Data Browser add itself to your Google Drive.')"))
            check('in the dialog, which stays open, the offer and the error gone',
                  [await page.ev(DIALOG_SHOWN), await page.ev(SHOWN_PS), await page.ev(DIALOG_ERROR)],
                  [True, 'drivePickText access', ''])
            before = await pick(page, {'action': 'cancel'})
            await page.click('#driveChooseBtn')
            await opened(page, before)
            check('the access given with it is kept: Choose files goes straight to the picker',
                  [len(await page.ev(f'{T}.tokenRequests')), await page.ev(f'{T}.pickers.length'),
                   await page.ev(DIALOG_SHOWN)], [2, 1, False])
            await page.ev('driveToken = null; true')
            await page.ev(f'{T}.nextToken = {{ kind: "error", error: "access_denied" }}; true')
            await page.click(BUTTON)
            await settle(page, f'{DIALOG_SHOWN} && !!{DIALOG_ERROR}')
            check('nor is it offered again in the tab', await page.ev(SHOWN_PS), 'drivePickText access')

            check('nothing outside the stand-ins was fetched from Google', page.unexpected, [])
        finally:
            try:
                await page.ev("localStorage.removeItem('kvot-rb-lazy'); true")
            except Exception:
                pass
            try:
                await page.call('Fetch.disable')
            except Exception:
                pass
            await bws.send(json.dumps({'id': 999999, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
