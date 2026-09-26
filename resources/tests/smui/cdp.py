"""A small Chrome DevTools Protocol driver for the smui.html tests.

    page = await open_page(url)          # a new tab, cache off, light theme
    await wait_engine(page)              # until SM.engine is ready (or failed)
    value = await page.ev('js expression, may return a promise')
    await page.shot('file.png')
    await page.close()

page.errors collects uncaught exceptions, page.console console errors and
warnings. The ports come from SMUI_HTTP_PORT and SMUI_CDP_PORT (defaults
8791 and 9291); start the server on the repository root and headless Chrome
as ../rb/README.md shows, on those ports.
"""
import asyncio
import base64
import json
import os
import urllib.request

import websockets

HTTP = int(os.environ.get('SMUI_HTTP_PORT', '8791'))
CDP = int(os.environ.get('SMUI_CDP_PORT', '9291'))
BASE = f'http://127.0.0.1:{HTTP}'


class Page:
    def __init__(self, bws):
        self.bws = bws
        self.n = 0
        self.pending = {}
        self.sid = None
        self.tid = None
        self.errors = []
        self.console = []

    async def call(self, method, params=None, session=None, timeout=120):
        self.n += 1
        i = self.n
        msg = {'id': i, 'method': method, 'params': params or {}}
        if session:
            msg['sessionId'] = session
        fut = asyncio.get_event_loop().create_future()
        self.pending[i] = fut
        await self.bws.send(json.dumps(msg))
        return await asyncio.wait_for(fut, timeout)

    async def pump(self):
        try:
            async for raw in self.bws:
                r = json.loads(raw)
                m = r.get('method')
                if m == 'Runtime.exceptionThrown':
                    d = r['params']['exceptionDetails']
                    self.errors.append(str(d.get('exception', {}).get('description') or d.get('text', ''))[:600])
                elif m == 'Runtime.consoleAPICalled' and r['params'].get('type') in ('error', 'warning'):
                    self.console.append(' '.join(str(a.get('value', a.get('description', ''))) for a in r['params'].get('args', []))[:400])
                if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                    self.pending[r['id']].set_result(r)
        except websockets.ConnectionClosed:
            pass

    async def ev(self, expr, timeout=120):
        """Evaluate in the page; promises are awaited; the value comes back
        as JSON. An exception comes back as a string 'EXCEPTION: ...'."""
        r = await self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True}, session=self.sid, timeout=timeout)
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:600]
        return res.get('result', {}).get('value')

    async def shot(self, path):
        r = await self.call('Page.captureScreenshot', {'format': 'png'}, session=self.sid)
        with open(path, 'wb') as f:
            f.write(base64.b64decode(r['result']['data']))

    async def mouse(self, kind, x, y, button='left', clicks=1, modifiers=0):
        await self.call('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': button, 'clickCount': clicks, 'modifiers': modifiers}, session=self.sid)

    async def click(self, x, y, modifiers=0):
        await self.mouse('mouseMoved', x, y)
        await self.mouse('mousePressed', x, y, modifiers=modifiers)
        await self.mouse('mouseReleased', x, y, modifiers=modifiers)

    async def key(self, key, code=None, text=None, modifiers=0):
        base = {'key': key, 'code': code or key, 'modifiers': modifiers}
        if text:
            base['text'] = text
        await self.call('Input.dispatchKeyEvent', {'type': 'keyDown', **base}, session=self.sid)
        await self.call('Input.dispatchKeyEvent', {'type': 'keyUp', **base}, session=self.sid)

    async def close(self):
        try:
            await self.call('Target.closeTarget', {'targetId': self.tid}, timeout=10)
        finally:
            await self.bws.close()


async def open_page(url, width=1500, height=950, dark=False):
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    bws = await websockets.connect(ver['webSocketDebuggerUrl'], max_size=400 * 1024 * 1024)
    page = Page(bws)
    asyncio.create_task(page.pump())
    page.tid = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
    page.sid = (await page.call('Target.attachToTarget', {'targetId': page.tid, 'flatten': True}))['result']['sessionId']
    for m in ('Runtime.enable', 'Page.enable', 'Network.enable'):
        await page.call(m, session=page.sid)
    await page.call('Network.setCacheDisabled', {'cacheDisabled': True}, session=page.sid)
    await page.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    theme = 'dark' if dark else 'light'
    await page.call('Page.addScriptToEvaluateOnNewDocument', {'source': f"try{{localStorage.setItem('kvot-theme','{theme}')}}catch(e){{}}"}, session=page.sid)
    await page.call('Page.navigate', {'url': url}, session=page.sid)
    return page


async def wait_engine(page, seconds=240):
    """Wait until the Python engine is ready or has failed; return its state."""
    st = None
    for _ in range(int(seconds * 2)):
        st = await page.ev('window.SM && SM.engine && SM.engine.state')
        if st in ('ready', 'error'):
            return st
        await asyncio.sleep(0.5)
    return st


class Checks:
    """ok/FAIL lines and a count, for a test's exit status."""

    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, got, want=True):
        self.n += 1
        ok = got == want
        print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
        if not ok:
            self.failed.append(label)
        return ok

    def near(self, label, got, want, tol=1e-6):
        ok = isinstance(got, (int, float)) and isinstance(want, (int, float)) and abs(got - want) <= tol * max(1.0, abs(want))
        return self(label + f' ≈ {want}', True if ok else got, True if ok else want)

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        if self.failed:
            print('failed:', *self.failed, sep='\n  ')
        return 0 if not self.failed else 1


# The JavaScript every test uses: open a report and wait for it.
OPEN_REPORT = '''
(async (platform, roles, options) => {
  const t = SM.app.current; const P = SM.platforms.get(platform);
  const ids = {};
  for (const [k, names] of Object.entries(roles)) ids[k] = names.map(n => { const c = t.col(n); if (!c) throw new Error('no column ' + n); return c.id; });
  const rep = SM.app.openReport(P, { roles: ids, options: options || {} }, t);
  await new Promise(res => rep.on('done', res));
  return {
    title: rep.title,
    outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
    errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 500)),
    warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)),
    plots: rep.plots.length,
  };
})
'''


def open_report_js(platform, roles, options=None):
    return f'({OPEN_REPORT})({json.dumps(platform)}, {json.dumps(roles)}, {json.dumps(options or {})})'


# The rows of the report table under an outline titled `title` (the first
# match), as lists of cell texts, header first.
TABLE_UNDER = '''
((title, n) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const heads = [...rep.body.querySelectorAll('.sm-ob-head')].filter(h => h.textContent.trim() === title);
  if (!heads.length) return null;
  const body = heads[0].parentElement.querySelector(':scope > .sm-ob-body');
  const t = body.querySelectorAll('table.sm-rt, table.sm-kv')[n || 0];
  if (!t) return null;
  return [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent.trim()));
})
'''


def table_under_js(title, n=0):
    return f'({TABLE_UNDER})({json.dumps(title)}, {n})'
