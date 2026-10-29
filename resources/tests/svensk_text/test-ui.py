#!/usr/bin/env python3
"""svensk_text.html in a real browser: does the page do the thing.

test-core.js proves the subtitle work. This proves the wiring, with Chrome's
built-in translator replaced by a stand-in that answers "SV " and the English
(a headless Chrome cannot fetch Google's model, and the answers must not
change from run to run):

- the page loads without a script error, in the site's header and footer;
- the sample scene shows Google's real Swedish, seven subtitles to look at;
- a live run asks for its model on the click, sends whole sentences twelve at
  a time, and keeps the phrasebook's line;
- an .srt opened from disk is translated, and saved as a Windows-ready .srt
  under a Swedish name; the work is still there after a reload;
- without the translator the page picks the open model by itself;
- the front page has the tool's card.

Serve the repository and start Chrome first. The ports are 8851 and 9351
unless ST_HTTP_PORT and ST_CDP_PORT say otherwise; check them with
`lsof -nP -iTCP:<port> -sTCP:LISTEN` first, because other sessions use ports
too:

    python3 -m http.server 8851 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
      --headless=new --remote-debugging-port=9351 --no-first-run \\
      --user-data-dir=/tmp/sttest --disable-gpu about:blank

    python3 resources/tests/svensk_text/test-ui.py

Exit status is 0 when every check passes.
"""
import asyncio
import base64
import json
import os
import sys
import tempfile
import urllib.request

import websockets

HTTP = int(os.environ.get('ST_HTTP_PORT', '8851'))
CDP = int(os.environ.get('ST_CDP_PORT', '9351'))
URL = f'http://127.0.0.1:{HTTP}/svensk_text.html'
INDEX = f'http://127.0.0.1:{HTTP}/index.html'

# Chrome's Translator API as the page uses it: 'downloadable' until create(),
# a download that reports its progress, then a translation of each line.
STUB = r"""
(() => {
  let state = 'downloadable';
  window.__trCalls = [];
  window.Translator = {
    availability: async ({ sourceLanguage, targetLanguage }) => (sourceLanguage === 'en' && targetLanguage === 'sv' ? state : 'unavailable'),
    create: async ({ monitor }) => {
      const target = new EventTarget();
      if (monitor) monitor(target);
      for (const v of [0, 0.5, 1]) { await new Promise(r => setTimeout(r, 40)); const e = new Event('downloadprogress'); e.loaded = v; target.dispatchEvent(e); }
      state = 'available';
      return { translate: async t => { window.__trCalls.push(t); return t.split('\n').map(l => 'SV ' + l).join('\n'); } };
    },
  };
})();
"""
NO_TRANSLATOR = "Object.defineProperty(window, 'Translator', { value: undefined, configurable: true, writable: true });"
FORGET = "try { Object.keys(localStorage).filter(k => k.startsWith('kvot-st-v1')).forEach(k => localStorage.removeItem(k)); } catch (e) {}"

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


class Page:
    def __init__(self, bws):
        self.bws = bws
        self.n = 0
        self.pending = {}
        self.sid = None
        self.errors = []

    async def call(self, method, params=None, session=None):
        self.n += 1
        i = self.n
        msg = {'id': i, 'method': method, 'params': params or {}}
        if session:
            msg['sessionId'] = session
        fut = asyncio.get_event_loop().create_future()
        self.pending[i] = fut
        await self.bws.send(json.dumps(msg))
        return await asyncio.wait_for(fut, 120)

    async def pump(self):
        async for raw in self.bws:
            r = json.loads(raw)
            if r.get('method') == 'Runtime.exceptionThrown' and r.get('sessionId') == self.sid:
                d = r['params']['exceptionDetails']
                self.errors.append(str(d.get('exception', {}).get('description') or d.get('text', ''))[:300])
            if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                self.pending[r['id']].set_result(r)

    async def ev(self, expr):
        r = await self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True, 'userGesture': True}, session=self.sid)
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:300]
        return res.get('result', {}).get('value')

    async def open(self, url, scripts):
        tid = (await self.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        self.sid = (await self.call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
        for m in ('Runtime.enable', 'Page.enable', 'Network.enable', 'DOM.enable'):
            await self.call(m, session=self.sid)
        await self.call('Emulation.setDeviceMetricsOverride', {'width': 1400, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=self.sid)
        await self.call('Network.setCacheDisabled', {'cacheDisabled': True}, session=self.sid)
        # In front, or a headless tab may hold back its animation frames.
        await self.call('Page.bringToFront', {}, session=self.sid)
        self.scripts = {}
        for s in scripts:
            r = await self.call('Page.addScriptToEvaluateOnNewDocument', {'source': s}, session=self.sid)
            self.scripts[s] = r['result']['identifier']
        await self.call('Page.navigate', {'url': url}, session=self.sid)
        return tid

    async def drop_script(self, source):
        """Stop running `source` on each new document, so that a reload keeps what it would undo."""
        await self.call('Page.removeScriptToEvaluateOnNewDocument', {'identifier': self.scripts.pop(source)}, session=self.sid)

    async def set_file(self, selector, path):
        doc = await self.call('DOM.getDocument', {}, session=self.sid)
        node = await self.call('DOM.querySelector', {'nodeId': doc['result']['root']['nodeId'], 'selector': selector}, session=self.sid)
        await self.call('DOM.setFileInputFiles', {'nodeId': node['result']['nodeId'], 'files': [path]}, session=self.sid)


async def settle(page, expr, want, tries=80, pause=0.25):
    got = None
    for _ in range(tries):
        got = await page.ev(expr)
        if got == want:
            return got
        await asyncio.sleep(pause)
    return got


def text(sel):
    return f"(document.querySelector({json.dumps(sel)}) || {{}}).textContent"


def sv_of(n):
    return f"document.querySelector('.st-row[data-n=\"{n}\"] .st-sv-text').textContent"


def test_srt():
    """60 subtitles: sound descriptions, a speaker label, italics, two speakers,
    a sentence over two subtitles and a filler, and a pause after every tenth."""
    lines = ['Where were you last night?', "I don't know what you mean.", '[phone ringing]', 'HOPE: You know exactly what I mean,',
             'and you know it.', '<i>Leave a message after the tone.</i>', '- Will?\n- Yeah?', 'Um, we need to talk about the money.']
    out, t = [], 1000

    def ts(ms):
        return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'
    for i in range(1, 61):
        d = 1500 + (i % 5) * 300
        out.append(f'{i}\n{ts(t)} --> {ts(t + d)}\n{lines[i % len(lines)]}')
        t += d + (3000 if i % 10 == 0 else 250)
    return '\n\n'.join(out) + '\n'


async def main():
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    srt_path = os.path.join(tempfile.mkdtemp(), 'Test.Film.en.srt')
    with open(srt_path, 'w', encoding='utf-8') as f:
        f.write(test_srt())
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        page = Page(bws)
        asyncio.create_task(page.pump())

        # --- the page, with the stand-in translator ---------------------------
        tid = await page.open(URL, [FORGET, STUB])
        try:
            check('the sample is on screen', await settle(page, text('#st-sub'), 'Will! Vart i helvete har du hållit hus?'), 'Will! Vart i helvete har du hållit hus?')
            await page.drop_script(FORGET)
            check('no script errors on load', page.errors, [])
            check('in the site\'s header, with its title', await page.ev(text('header .title')), 'Svensk text')
            check('the menu leads home and to the other projects, not here',
                  await page.ev("[!!document.querySelector('#menu a[href=\"./index.html\"]'), !!document.querySelector('#menu a[href=\"./gitarr.html\"]'), !!document.querySelector('#menu a[href=\"./svensk_text.html\"]')]"), [True, True, False])
            check('and the footer', await page.ev("!!document.querySelector('footer .theme-toggle')"), True)
            check('what waits to be shown is not shown: the drop zone, the question, the close button, the progress',
                  await page.ev("['st-drop', 'st-confirm', 'st-close', 'st-progress', 'st-alert'].filter(id => getComputedStyle(document.getElementById(id)).display !== 'none')"), [])
            check('23 subtitles, the door left out', await page.ev(text('#st-c-all')), '23')
            check('seven to look at, as Google left them', await page.ev(text('#st-c-attn')), '7')
            check('Google in Chrome is chosen, its model not yet fetched',
                  await settle(page, f"[document.getElementById('st-eng-chrome').checked, {text('#st-chrome-state')}]", [True, 'Ready to download']), [True, 'Ready to download'])
            check('subtitles 6 and 7 are one sentence', await page.ev(sv_of(7)), 'hade vi inte behövt köra\nåtta mil för att leta efter dig.')

            # --- the sample, live ---------------------------------------------
            await page.ev("document.getElementById('st-go').click()")
            check('a live run of the sample finishes', await settle(page, f"{text('#st-alert')}.startsWith('Done.')", True), True)
            check('the model was fetched on the click', await page.ev(text('#st-chrome-state')), 'Ready')
            calls = await page.ev("window.__trCalls.map(c => c.split('\\n').length)")
            check('whole sentences, twelve to a request', calls, [12, 10])
            check('the filler was gone before it went', await page.ev("window.__trCalls[0].split('\\n')[1]"), 'I got held up at work.')
            check('the phrasebook\'s line is kept', await page.ev(sv_of(23)), 'Nu räcker det för i kväll.')
            check('two speakers, a hyphen each', await page.ev(sv_of(4)), '-SV At two in the morning?\n-SV I\'m sorry, okay?')

            # --- a file from disk ---------------------------------------------
            await page.set_file('#st-file-input', srt_path)
            check('an .srt opens', await settle(page, text('#st-file-name'), 'Test.Film.en.srt'), 'Test.Film.en.srt')
            check('52 subtitles, 8 sound descriptions left out', [await page.ev(text('#st-c-all')), await page.ev(text('#st-c-todo'))], ['52', '52'])
            await page.ev("window.__trCalls.length = 0; document.getElementById('st-go').click()")
            check('and is translated', await settle(page, text('#st-c-todo'), '0'), '0')
            check('44 sentences in four requests (the speaker\'s "Yeah?" from the phrasebook)', await page.ev("window.__trCalls.map(c => c.split('\\n').length)"), [12, 12, 12, 8])
            check('the list is up to date when the run ends', await page.ev("document.querySelectorAll('#st-list .st-sv-text.st-muted').length"), 8)
            check('the speaker label is gone', await page.ev(sv_of(3)), 'SV You know exactly what I mean,')
            check('the sentence over 3 and 4 is shared between them', await page.ev(sv_of(4)), 'and you know it.')
            check('no script errors while translating', page.errors, [])

            await page.ev("""(() => { window.__saved = null;
              HTMLAnchorElement.prototype.click = function () {
                const a = this; fetch(a.href).then(r => r.arrayBuffer()).then(b => {
                  const u = new Uint8Array(b); let s = ''; for (const x of u) s += String.fromCharCode(x);
                  window.__saved = { name: a.download, b64: btoa(s) }; }); }; })()""")
            await page.ev("document.querySelector('[data-on-click=\"st:save\"]').click()")
            saved = await settle(page, "window.__saved && window.__saved.name", 'Test.Film.sv.srt')
            check('saved under a Swedish name', saved, 'Test.Film.sv.srt')
            raw = base64.b64decode(await page.ev("window.__saved.b64") or '')
            check('as UTF-8 with a BOM and Windows line ends', raw[:3] == b'\xef\xbb\xbf' and b'\r\n' in raw, True)
            body = raw[3:].decode('utf-8')
            check('starting at the first subtitle', body.split('\r\n')[:3], ['1', '00:00:01,000 --> 00:00:02,800', "SV I don't know what you mean."])
            check('with the italics back on', '<i>SV Leave a message after the tone.</i>' in body, True)

            await page.call('Page.reload', {}, session=page.sid)
            check('the work is still there after a reload', await settle(page, f"[{text('#st-file-name')}, {text('#st-c-todo')}]", ['Test.Film.en.srt', '0']), ['Test.Film.en.srt', '0'])

            await page.ev("document.querySelector('footer .theme-toggle').click()")
            await asyncio.sleep(0.3)
            check('the theme switch redraws without an error', [await page.ev("document.documentElement.getAttribute('data-theme')") in ('dark', 'light'), page.errors], [True, []])
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})

        # --- no translator in the browser ---------------------------------------
        page.errors = []
        tid = await page.open(URL, [FORGET, NO_TRANSLATOR])
        try:
            got = await settle(page, f"[document.getElementById('st-eng-opus').checked, {text('#st-chrome-state')}]", [True, 'Not in this browser'])
            check('without the translator, the open model is chosen by itself', got, [True, 'Not in this browser'])
            check('and its download is announced', await page.ev(f"{text('#st-estimate')}.includes('about 105 MB')"), True)
            check('no script errors', page.errors, [])
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})

        # --- the front page -------------------------------------------------------
        page.errors = []
        tid = await page.open(INDEX, [])
        try:
            card = await settle(page, "(() => { const a = document.querySelector('#project-grid a[href=\"./svensk_text.html\"]'); return a && a.querySelector('.project-card-title').textContent; })()", 'Svensk text')
            check('the front page has the card', card, 'Svensk text')
            check('no script errors on the front page', page.errors, [])
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})
    os.unlink(srt_path)
    print(f'{checks} checks, {len(failures)} failed')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    asyncio.run(main())
