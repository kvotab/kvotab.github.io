#!/usr/bin/env python3
"""gitarr.html in a real browser.

Plucked strings are made in the page by synth.js and fed through the page's
own frame logic (GT.test.feed), played through the real audio path in place
of the microphone (GT.test.play), and handed to the page by getUserMedia as
a MediaStream after a trusted click on Starta (mic_suite: why not Chrome's
own fake microphone is written there).

Start a server on the repository root and headless Chrome, by default on
ports 8849 and 9349 (GT_HTTP_PORT and GT_CDP_PORT for others). Check the
ports first with lsof -nP -iTCP:<port> -sTCP:LISTEN, other sessions use
ports too:

    python3 -m http.server 8849 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
      --headless=new --remote-debugging-port=9349 --no-first-run \\
      --user-data-dir=/tmp/gttest --disable-gpu \\
      --autoplay-policy=no-user-gesture-required about:blank

    python3 resources/tests/gitarr/test-ui.py

With GT_SHOTS=<folder> it saves screenshots. Exit status is 0 when every
check passes.
"""
import asyncio
import base64
import json
import os
import sys
import urllib.request

import websockets

HTTP = int(os.environ.get('GT_HTTP_PORT', '8849'))
CDP = int(os.environ.get('GT_CDP_PORT', '9349'))
ORIGIN = f'http://127.0.0.1:{HTTP}'
URL = f'{ORIGIN}/gitarr.html'
SHOTS = os.environ.get('GT_SHOTS')
HERE = os.path.dirname(os.path.abspath(__file__))
SYNTH = open(os.path.join(HERE, 'synth.js'), encoding='utf-8').read()

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
        self.console = []

    async def call(self, method, params=None, timeout=60):
        self.n += 1
        i = self.n
        msg = {'id': i, 'method': method, 'params': params or {}}
        if self.sid and not method.startswith('Target.'):
            msg['sessionId'] = self.sid
        fut = asyncio.get_event_loop().create_future()
        self.pending[i] = fut
        await self.bws.send(json.dumps(msg))
        return await asyncio.wait_for(fut, timeout)

    async def pump(self):
        async for raw in self.bws:
            r = json.loads(raw)
            if r.get('method') == 'Runtime.exceptionThrown':
                d = r['params']['exceptionDetails']
                self.errors.append(str(d.get('exception', {}).get('description') or d.get('text', ''))[:300])
            if r.get('method') == 'Runtime.consoleAPICalled' and r['params']['type'] == 'error':
                self.console.append(' '.join(str(a.get('value', a.get('description', ''))) for a in r['params']['args'])[:300])
            if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                self.pending[r['id']].set_result(r)

    async def ev(self, expr):
        r = await self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:300]
        return res.get('result', {}).get('value')

    async def js(self, expr):
        """A JSON-returning expression, parsed."""
        v = await self.ev(f'JSON.stringify({expr})')
        if isinstance(v, str) and v.startswith('EXCEPTION'):
            raise RuntimeError(v)
        return json.loads(v) if v is not None else None

    async def click_xy(self, x, y):
        for kind in ('mousePressed', 'mouseReleased'):
            await self.call('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})

    async def click(self, selector):
        """A real click, with the mouse: unlike element.click(), it counts as
        the tap after which a browser lets a page use sound."""
        xy = await self.js(f"(e => {{ const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})(document.querySelector({json.dumps(selector)}))")
        await self.click_xy(*xy)

    async def key(self, k):
        codes = {'Enter': ('Enter', 13, '\r'), ' ': ('Space', 32, ' '), 'Tab': ('Tab', 9, '')}
        code, vk, text = codes[k]
        down = {'type': 'keyDown', 'key': k, 'code': code, 'windowsVirtualKeyCode': vk}
        if text:
            down['text'] = text
        await self.call('Input.dispatchKeyEvent', down)
        await self.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': k, 'code': code, 'windowsVirtualKeyCode': vk})

    async def load(self, width=1400, height=900, theme='light', mobile=False, settings=None):
        """A fresh page; its storage as given (settings None: nothing stored)."""
        await self.call('Emulation.setDeviceMetricsOverride',
                        {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': mobile})
        await self.call('Emulation.setTouchEmulationEnabled', {'enabled': mobile, 'maxTouchPoints': 5 if mobile else 0})
        await self.call('Page.navigate', {'url': f'{ORIGIN}/robots.txt'})
        await settle(self, 'document.readyState', 'complete')
        await self.ev(f"localStorage.clear(); localStorage.setItem('kvot-theme', {json.dumps(theme)});"
                      + (f"localStorage.setItem('gitarr.settings', {json.dumps(json.dumps(settings))});" if settings is not None else ''))
        await self.call('Page.navigate', {'url': URL})
        # typeof, not window.GT: a top-level const is not a property of window
        await settle(self, "typeof GT !== 'undefined' && document.querySelectorAll('.gt-key').length === 6", True)
        await self.ev(SYNTH)
        await asyncio.sleep(0.15)

    async def shot(self, name):
        if not SHOTS:
            return
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.3)
        r = await self.call('Page.captureScreenshot', {'format': 'png'})
        with open(os.path.join(SHOTS, name), 'wb') as f:
            f.write(base64.b64decode(r['result']['data']))


async def settle(page, expr, want, tries=60, pause=0.1):
    got = None
    for _ in range(tries):
        got = await page.ev(expr)
        if got == want:
            return got
        await asyncio.sleep(pause)
    return got


async def attach(port):
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version'))
    bws = await websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024)
    page = Page(bws)
    asyncio.create_task(page.pump())
    tid = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
    page.sid = (await page.call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
    for m in ('Runtime.enable', 'Page.enable', 'Network.enable'):
        await page.call(m)
    await page.call('Network.setCacheDisabled', {'cacheDisabled': True})
    return bws, page, tid


FREQ = [82.4069, 110.0, 146.8324, 195.9977, 246.9417, 329.6276]
NAMES = ['låga E', 'A', 'D', 'G', 'B', 'höga E']
NBH = '‑'  # the hyphen in "A‑strängen" that never breaks a line

# Plucks through the page's own frame logic: 33 readings a second of clock
# from `t`, as the frame loop takes them. Returns GT.inspect() after.
FEED = """(() => {
  const sr = 48000, o = Object.assign({ sr, dur: 1.2 }, %s);
  const x = GT_SYNTH.pluck(o), need = 8192, hop = Math.round(sr / 33);
  let t = %s;
  for (let end = need; end <= x.length; end += hop) { GT.test.feed(x.subarray(end - need, end), sr, t); t += 1000 / 33; }
  window.__t = t;
  return GT.inspect();
})()"""


async def feed(page, f0, t=None, **o):
    if t is None:
        t = await page.ev('(window.__t || 1000) + 3000')
    o['f0'] = f0
    return await page.js(FEED % (json.dumps(o), json.dumps(t)))


def at(i, cents):
    return FREQ[i] * 2 ** (cents / 1200)


# What of the site's chrome is on screen, and whether the page fits it.
CHROME_STATE = """(() => {
  const shown = sel => { const e = document.querySelector(sel); return !!e && e.checkVisibility(); };
  const c = document.querySelector('.gt-content');
  const r = sel => document.querySelector(sel).getBoundingClientRect();
  const inside = b => b.top >= -0.5 && b.left >= -0.5 && b.bottom <= innerHeight + 0.5 && b.right <= innerWidth + 0.5;
  const keys = [...document.querySelectorAll('.gt-key')].map(k => k.getBoundingClientRect());
  return { header: shown('body > header'), footer: shown('body > footer'), brand: shown('.gt-brand'),
           theme: shown('.gt-top-end > .theme-toggle'), help: shown('[data-on-click="gt:help"]'),
           scroll: c.scrollHeight - c.clientHeight, sideways: c.scrollWidth - c.clientWidth,
           docSideways: document.documentElement.scrollWidth - document.documentElement.clientWidth,
           guitar: inside(r('#gt-guitar')), start: inside(r('#gt-start')), msg: inside(r('#gt-msg')), meter: inside(r('#gt-meter')),
           keysInside: keys.every(inside), keyMin: Math.round(Math.min(...keys.map(k => Math.min(k.width, k.height)))),
           guitarH: Math.round(r('#gt-guitar').height), msgLines: Math.round(r('#gt-msg').height / parseFloat(getComputedStyle(document.getElementById('gt-msg')).lineHeight)) };
})()"""

PHONES = [(390, 664, 'iPhone upright'), (844, 340, 'iPhone on its side'),
          (375, 548, 'iPhone SE upright'), (667, 325, 'iPhone SE on its side'),
          (360, 560, 'small Android upright'), (320, 520, 'narrowest phone')]


async def main_suite(page):
    # ── The desktop ──────────────────────────────────────────────────────
    await page.load()
    st = await page.js(CHROME_STATE)
    check('desktop: the site header and footer are shown', [st['header'], st['footer']], [True, True])
    check('desktop: the page bar has no brand of its own', st['brand'], False)
    check('desktop: the page does not scroll', [st['scroll'] <= 0, st['sideways'] <= 0], [True, True])
    g = await page.js('GT.inspect()')
    check('idle: Starta, Auto on, nothing heard', [g['running'], g['picked'], g['msg'], g['meter']],
          [False, None, 'Tryck på Starta och tillåt mikrofonen.', 'idle'])
    letters = await page.js("[...document.querySelectorAll('.gt-key-letter')].map(t => t.textContent)")
    check('six keys, lettered E A D G B E from the low string', letters, ['E', 'A', 'D', 'G', 'B', 'E'])
    keys = g['keys']
    check('E A D on the left, G B E on the right', [k['left'] for k in keys], [True, True, True, False, False, False])
    check('the low E and the high E have the keys nearest the nut',
          [keys[0]['y'] > keys[1]['y'] > keys[2]['y'], keys[5]['y'] > keys[4]['y'] > keys[3]['y']], [True, True])
    # every string reaches its post on the side toward the middle of the headstock
    inner = await page.js("""[...document.querySelectorAll('.gt-string')].map((s, i) => {
      const l = s.querySelectorAll('line')[1], c = document.querySelectorAll('.gt-post')[i].transform.baseVal[0].matrix;
      return { end: +l.getAttribute('x2'), post: c.e };
    })""")
    check('each string is wound on the inside of its post',
          [(r['end'] > r['post']) == (i < 3) for i, r in enumerate(inner)], [True] * 6)
    # kvot ab's logo cut small into the headstock: the site's own mark, a cut
    # per face, the letters kv/ot, rims drawn by the carving filter; gold laid
    # in what the header draws in its light colour (class stTop: the mark's
    # top face and the letters), bare wood in two shades on the other faces.
    logo = await page.js("""(() => {
      const g = document.querySelector('.gt-head .gt-logo');
      if (!g) return null;
      const box = g.getBoundingClientRect(), head = document.querySelector('.gt-head > path').getBoundingClientRect();
      const bushes = [...document.querySelectorAll('.gt-postbody')].map(p => p.getBoundingClientRect());
      const header = new DOMParser().parseFromString(KVOT_ICONS.LOGO_SVG, 'image/svg+xml');
      const theirs = sel => [...header.querySelectorAll(sel)];
      const floors = sel => [...g.querySelectorAll(':scope > g:first-child > ' + sel)];
      const gilded = sel => floors(sel).map((e, i) => (e.getAttribute('fill') === 'url(#gt-gold)') === (theirs(sel)[i].getAttribute('class') === 'stTop'));
      const area = Math.min(...bushes.map(b => b.top)) - head.top;
      return {
        faces: floors('polygon').map((p, i) => p.getAttribute('points') === theirs('polygon')[i].getAttribute('points')),
        tones: new Set(floors('polygon').map(p => p.getAttribute('fill'))).size,
        letters: floors('path').length,
        gilded: [...gilded('polygon'), ...gilded('path')].every(Boolean),
        goldParts: g.querySelectorAll('[fill="url(#gt-gold)"]').length,
        stops: document.querySelectorAll('#gt-gold stop').length,
        rims: [...g.querySelectorAll('[filter]')].map(r => r.getAttribute('filter')),
        inside: box.left > head.left && box.right < head.right && box.top > head.top,
        clear: bushes.every(b => b.top > box.bottom),
        centred: Math.abs((box.left + box.right) / 2 - (head.left + head.right) / 2) < 3,
        small: box.width / head.width < 0.45,
        low: ((box.top + box.bottom) / 2 - head.top) / area,
        painted: document.querySelectorAll('.gt-head text').length,
      };
    })()""")
    check('the headstock carries the site\'s logo, carved: three faces in their own cuts, the letters kv/ot, every cut with its rims',
          logo and [logo['faces'], logo['tones'], logo['letters'], logo['rims']],
          [[True, True, True], 3, 4, ['url(#gt-carve)'] * 4])
    check('…gold in the top face and the letters (the header\'s light colour), wood on the other two faces',
          logo and [logo['gilded'], logo['goldParts'], logo['stops'] >= 3], [True, 5, True])
    check('…small, centred, a little below the middle of the space over the posts, and no painted name',
          logo and [logo['small'], logo['centred'], 0.5 < logo['low'] < 0.75, logo['inside'], logo['clear'], logo['painted']],
          [True, True, True, True, True, 0])
    check('no errors on load', page.errors + page.console, [])
    await page.shot('desktop-idle.png')

    # ── Every string, flat and sharp ─────────────────────────────────────
    for i in range(6):
        for cents in (-25, 25):
            g = await feed(page, at(i, cents), seed=i + 3)
            left = i < 3
            tighten = cents < 0
            want_front = 'up' if left == tighten else 'down'
            want_post = 'ccw' if left == tighten else 'cw'
            name = NAMES[i] + NBH + 'strängen'
            word = f'spänn {name}' if tighten else f'släpp efter på {name}'
            sign = '−' if tighten else '+'
            ok = (g['active'] == i and g['turn'] == {'front': want_front, 'post': want_post, 'side': 'left' if left else 'right'}
                  and word in g['msg'] and g['cents'] == f'{sign}25 cent' and g['meter'] == 'off' and abs(g['mark'] - cents) < 0.5)
            check(f'{NAMES[i]} {cents:+d} cents: its key, the front rolls {want_front}, the post turns {want_post}, "{word}"',
                  True if ok else g, True)
    await page.shot('desktop-highE-sharp.png')

    g = await feed(page, at(2, -9), seed=4)
    check('D 9 cents flat: near, "Lite för lågt – spänn lite till."',
          [g['meter'], g['msg'], g['turn']['front'] if g['turn'] else None], ['near', 'Lite för lågt – spänn lite till.', 'up'])
    g = await feed(page, at(3, 11), seed=4)
    check('G 11 cents sharp: near, "Lite för högt – släpp efter lite."', [g['meter'], g['msg']], ['near', 'Lite för högt – släpp efter lite.'])
    g = await feed(page, at(1, -80), seed=4)
    check('A 80 cents flat: "Mycket för lågt", the mark at the end of the scale',
          [g['msg'], g['mark']], [f'Mycket för lågt – spänn A{NBH}strängen.', -50])
    g = await feed(page, at(1, 2), seed=5)
    check('A 2 cents sharp: in tune, green, no arrows, the key ticked',
          [g['meter'], g['msg'], g['turn'], g['tuned'][1]], ['ok', f'A{NBH}strängen är stämd!', None, True])
    vis = await page.js("[...document.querySelectorAll('.gt-key-check')].map(c => getComputedStyle(c).display !== 'none')")
    check('…and only its tick is shown', vis, [False, True, False, False, False, False])
    # computed display, not checkVisibility(): Chrome calls a display:none SVG group visible
    arrows = await page.js("[...document.querySelectorAll('.gt-turn, .gt-spin')].filter(e => getComputedStyle(e).display !== 'none').length")
    check('…and no arrow is on screen', arrows, 0)
    await page.shot('desktop-A-in-tune.png')

    # The string goes quiet: dimmed, then gone.
    t = await page.ev('window.__t')
    g = await page.js(f"(GT.test.feed(new Float32Array(8192), 48000, {t + 600}), GT.inspect())")
    check('silent for 0.6 s: still shown, dimmed', [g['active'], g['snap']['live'], await page.ev("document.getElementById('gt-panel').classList.contains('is-quiet')")], [1, False, True])
    g = await page.js(f"(GT.test.feed(new Float32Array(8192), 48000, {t + 2000}), GT.inspect())")
    check('silent for 2 s: back to "Slå an en sträng"', [g['active'], g['msg']], [None, 'Slå an en sträng i taget och låt den klinga.'])

    # ── All six ──────────────────────────────────────────────────────────
    for i in range(6):
        g = await feed(page, at(i, -1 + i * 0.5), seed=20 + i)
    check('all six in tune: every key ticked and the banner up', [g['tuned'], g['done']], [[True] * 6, True])
    banner = await page.js("(b => { const r = b.getBoundingClientRect(); return { lines: Math.round(r.height / 24), text: b.textContent.trim().replace(/\\s+/g, ' ') }; })(document.getElementById('gt-done'))")
    check('the banner says so', banner['text'], 'Alla sex strängar är stämda! Stäm igen')
    await page.shot('desktop-all-tuned.png')
    await page.click('[data-on-click="gt:again"]')
    g = await page.js('GT.inspect()')
    check('"Stäm igen" clears the ticks and the banner', [g['tuned'], g['done']], [[False] * 6, False])

    # ── Picking a string ─────────────────────────────────────────────────
    await page.ev('GT.test.reset()')
    await page.click('.gt-key[data-i="2"]')
    g = await page.js('GT.inspect()')
    check('a click on the D key picks D', [g['picked'], g['picked_keys'][2], g['what']], [2, True, f'Bara D{NBH}strängen'])
    check('…the key says so', await page.ev("document.querySelector('.gt-key[data-i=\"2\"]').getAttribute('aria-pressed')"), 'true')
    check('…and Auto is off', await page.ev("document.getElementById('gt-auto').getAttribute('aria-pressed')"), 'false')
    g = await feed(page, at(2, -400), seed=8)
    check('D picked, D 400 cents flat: read against D', [g['active'], g['cents'], g['msg']],
          [2, '−400 cent', f'Mycket för lågt – spänn D{NBH}strängen.'])
    await page.click('#gt-auto')
    g = await page.js('GT.inspect()')
    check('Auto gives the choice back', [g['picked'], g['picked_keys']], [None, [False] * 6])
    g = await feed(page, at(2, -400), seed=8)
    check('…and then the same note is an A, 100 cents sharp', [g['active'], g['cents']], [1, '+100 cent'])
    await page.ev("document.querySelector('.gt-key[data-i=\"3\"]').focus()")
    await page.key('Enter')
    check('Enter on the focused G key picks G', (await page.js('GT.inspect()'))['picked'], 3)
    await page.key(' ')
    check('Space on it again lets go', (await page.js('GT.inspect()'))['picked'], None)

    # ── Settings ─────────────────────────────────────────────────────────
    await page.ev('GT.test.reset()')
    await page.click('[data-on-click="gt:settings"]')
    check('⚙ opens the settings', await page.ev("document.getElementById('gt-settings').open"), True)
    await page.click('#gt-settings input[name="reverse"]')
    await page.click('#gt-settings [data-on-click="gt:close"].gt-btn')
    check('Klar closes them', await page.ev("document.getElementById('gt-settings').open"), False)
    g = await feed(page, at(0, -20), seed=2)
    check('keys the other way: a flat low E rolls the front down, the post still anticlockwise',
          g['turn'], {'front': 'down', 'post': 'ccw', 'side': 'left'})
    check('…kept for next time', await page.ev("localStorage.getItem('gitarr.settings')"), '{"lefty":false,"reverse":true}')

    logo_spot = await page.js("(b => [Math.round(b.left), Math.round(b.width)])(document.querySelector('.gt-logo polygon').getBoundingClientRect())")
    await page.load(settings={'lefty': True, 'reverse': False})
    g = await page.js('GT.inspect()')
    check('left-handed: E A D on the right', [k['left'] for k in g['keys']], [False, False, False, True, True, True])
    check('left-handed: the logo still reads the right way round', await page.js(
          "(b => [Math.round(b.left), Math.round(b.width)])(document.querySelector('.gt-logo polygon').getBoundingClientRect())")
          == logo_spot, True)
    g = await feed(page, at(0, -20), seed=2)
    check('left-handed: a flat low E is a right key, rolled down, post clockwise', g['turn'], {'front': 'down', 'post': 'cw', 'side': 'right'})
    await page.click('[data-on-click="gt:settings"]')
    check('the settings show what is stored', await page.js("[...document.querySelectorAll('#gt-settings input')].map(i => i.checked)"), [False, True])
    await page.click('#gt-settings input[name="lefty"]')
    await page.click('#gt-settings .gt-dialog-head [data-on-click="gt:close"]')
    g = await page.js('GT.inspect()')
    check('unticked, the guitar is right-handed again at once', [k['left'] for k in g['keys']], [True, True, True, False, False, False])
    await page.load(settings={'lefty': 'yes', 'reverse': 1})
    check('settings that are not booleans are ignored', (await page.js('GT.inspect()'))['settings'], {'lefty': False, 'reverse': False})

    # ── Help ─────────────────────────────────────────────────────────────
    await page.click('[data-on-click="gt:help"]')
    check('? opens the help', await page.ev("document.getElementById('gt-help').open"), True)
    rows = await page.js("[...document.querySelectorAll('#gt-table-body tr')].map(r => [...r.cells].map(c => c.textContent))")
    check('the help lists the six strings, high to low', rows,
          [['1', 'E · E4', '329,63 Hz'], ['2', 'B (H) · B3', '246,94 Hz'], ['3', 'G · G3', '196,00 Hz'],
           ['4', 'D · D3', '146,83 Hz'], ['5', 'A · A2', '110,00 Hz'], ['6', 'E · E2', '82,41 Hz']])
    await page.shot('desktop-help.png')
    await page.click('#gt-help .gt-dialog-head [data-on-click="gt:close"]')
    check('✕ closes it', await page.ev("document.getElementById('gt-help').open"), False)

    # ── Microphone errors ────────────────────────────────────────────────
    for name, want in (('NotAllowedError', 'Sidan fick inte använda mikrofonen.'), ('NotFoundError', 'Hittade ingen mikrofon.'),
                       ('NotReadableError', 'Mikrofonen gick inte att starta.')):
        await page.load()
        await page.ev(f"navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('no', '{name}'))")
        await page.click('#gt-start')
        await settle(page, "GT.inspect().error !== null", True)
        g = await page.js('GT.inspect()')
        check(f'{name}: says so, and Starta can be pressed again',
              [g['msg'].startswith(want), g['msgState'], g['running'], await page.ev("document.getElementById('gt-start').disabled")],
              [True, 'error', False, False])
    await page.shot('desktop-mic-denied.png')

    # ── The real audio path, a buffer in place of the microphone ─────────
    await page.load()
    state = await page.ev("GT.test.play(GT_SYNTH.pluck({ sr: 48000, f0: %f, dur: 1.5, hp: 150 }), 48000, true)" % at(1, -15))
    check('played through Web Audio: the context runs', state, 'running')
    await settle(page, 'GT.inspect().active', 1, tries=40)
    await asyncio.sleep(0.6)
    g = await page.js('GT.inspect()')
    cents = float(g['cents'].replace('−', '-').replace(' cent', '')) if g['cents'] else None
    check('…the analyser and the frame loop hear an A, 15 cents flat (±2)', [g['running'], g['active'], cents is not None and abs(cents + 15) <= 2, g['sampleRate']],
          [True, 1, True, 48000])
    lit = await page.ev("document.querySelectorAll('#gt-level i.is-lit').length")
    check('…and the level bars light', lit >= 3, True)
    await page.click('#gt-start')
    g = await page.js('GT.inspect()')
    check('Stoppa stops it', [g['running'], g['msg'], g['active']], [False, 'Mikrofonen är avstängd. Tryck på Starta för att fortsätta.', None])
    await page.ev('GT.test.idleAfter(700)')
    await page.ev('GT.test.play(new Float32Array(48000), 48000, true)')
    await settle(page, 'GT.inspect().running', False, tries=40)
    g = await page.js('GT.inspect()')
    check('no string heard for the idle time: the microphone closes', [g['running'], g['stopped']], [False, 'idle'])
    await page.ev('GT.test.idleAfter(0)')

    # ── Reduced motion, dark ─────────────────────────────────────────────
    await page.call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
    await page.load()
    await feed(page, at(4, -30))
    anim = await page.js("['.gt-key.is-active .gt-turn-march', '.gt-key.is-active .gt-roll-inner', '.gt-post.is-turn .gt-spin-inner'].map(s => getComputedStyle(document.querySelector(s)).animationName)")
    check('reduced motion: the arrows stand still', anim, ['none', 'none', 'none'])
    await page.call('Emulation.setEmulatedMedia', {'features': []})
    await page.load(theme='dark')
    check('dark: the browser draws its own widgets dark too', await page.ev('getComputedStyle(document.documentElement).colorScheme'), 'dark')
    await feed(page, at(5, 30))
    await page.shot('desktop-dark-highE.png')
    check('no errors anywhere in the main suite', page.errors + page.console, [])


async def phones_suite(page):
    for w, h, label in PHONES:
        await page.load(width=w, height=h, mobile=True)
        st = await page.js(CHROME_STATE)
        check(f'{label} ({w}×{h}): no site header or footer, the page bar has the brand and the theme switch',
              [st['header'], st['footer'], st['brand'], st['theme'], st['help']], [False, False, True, True, True])
        g = await feed(page, at(0, -35))
        st = await page.js(CHROME_STATE)
        check(f'{label}: everything on one screen, nothing scrolls',
              [st['scroll'] <= 0, st['sideways'] <= 0, st['docSideways'] <= 0, st['guitar'], st['keysInside'], st['meter'], st['msg'], st['start']],
              [True] * 8)
        check(f'{label}: the keys are big enough to tap (≥ 30 px)', st['keyMin'] >= 30, True)
        check(f'{label}: the low E\'s message fits on its two lines', st['msgLines'] <= 2, True)
        await page.shot(f'phone-{w}x{h}.png')
    # A tablet upright keeps the site's chrome but stacks the guitar over the
    # panel, as a phone does: in two columns the guitar was a thin strip.
    await page.load(width=820, height=1180, mobile=True)
    await feed(page, at(2, -18))
    st = await page.js(CHROME_STATE)
    stacked = await page.js("(() => { const g = document.getElementById('gt-guitar').getBoundingClientRect(), p = document.getElementById('gt-panel').getBoundingClientRect(); return [p.top >= g.bottom - 1, Math.round(g.height)]; })()")
    check('tablet upright (820×1180): header and footer shown, guitar over the panel, nothing scrolls',
          [st['header'], st['footer'], stacked[0], stacked[1] > 700, st['scroll'] <= 0, st['keysInside'], st['start']],
          [True, True, True, True, True, True, True])
    await page.shot('tablet-820x1180.png')
    still = await page.js("(() => { const c = e => getComputedStyle(e); return [c(document.documentElement).touchAction, c(document.documentElement).overflow, c(document.body).position]; })()")
    check('the page itself cannot be dragged or double-tap zoomed', still, ['manipulation', 'hidden', 'fixed'])
    check('no errors on the phones', page.errors + page.console, [])


# getUserMedia, answered with a real MediaStream: a looped pluck played into
# a MediaStreamAudioDestinationNode. Chrome's own fake microphone
# (--use-fake-device-for-media-stream, with or without a WAV file) is no use
# here: in headless Chrome on macOS getUserMedia never settles, even with the
# permission granted, the devices listed and the page focused.
MIC_STUB = """(() => {
  const x = GT_SYNTH.pluck({ sr: 48000, f0: %f, dur: 2.5, hp: 120, noise: 0.001 });
  window.__gum = [];
  const AC0 = window.AudioContext;   // the page's may be swapped later
  navigator.mediaDevices.getUserMedia = async constraints => {
    const ctx = new AC0({ sampleRate: 48000 });
    const buf = ctx.createBuffer(1, x.length, 48000);
    buf.copyToChannel(x, 0);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.loop = true;
    const dest = ctx.createMediaStreamDestination();
    src.connect(dest);
    src.start();
    await ctx.resume();
    window.__gum.push({ constraints, track: dest.stream.getAudioTracks()[0] });
    return dest.stream;
  };
  return true;
})()"""


async def mic_suite(page):
    """Starta pressed by a trusted click, the microphone a looped low E 20
    cents flat, as a phone hears it."""
    await page.load(width=390, height=664, mobile=True)
    await page.ev(MIC_STUB % at(0, -20))
    await page.click('#gt-start')
    ok = await settle(page, 'GT.inspect().running', True, tries=50)
    check('microphone: Starta opens it', ok, True)
    asked = await page.js('window.__gum[0].constraints')
    check('microphone: asked for without echo cancelling, noise suppression or gain control',
          asked, {'audio': {'echoCancellation': False, 'noiseSuppression': False, 'autoGainControl': False}})
    await settle(page, 'GT.inspect().active', 0, tries=60)
    await asyncio.sleep(1.0)
    g = await page.js('GT.inspect()')
    cents = float(g['cents'].replace('−', '-').replace(' cent', '')) if g['cents'] else None
    check('microphone: the low E, 20 cents flat (±3), left key, front up, post anticlockwise',
          [g['active'], cents is not None and abs(cents + 20) <= 3, g['turn']],
          [0, True, {'front': 'up', 'post': 'ccw', 'side': 'left'}])
    check('microphone: the button now says Stoppa', await page.ev("document.getElementById('gt-start-label').textContent"), 'Stoppa')
    await page.shot('mic-lowE.png')
    # Leaving the page closes the microphone; coming back opens it again.
    await page.ev("Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange'))")
    g = await page.js('GT.inspect()')
    ended = await page.ev("window.__gum[0].track.readyState")
    check('microphone: page hidden, it closes and the track is stopped', [g['running'], g['stopped'], ended], [False, 'hidden', 'ended'])
    check('microphone: …and says so', g['msg'], 'Mikrofonen stängdes när du lämnade sidan. Tryck på Starta för att fortsätta.')
    await page.ev("Object.defineProperty(document, 'hidden', { configurable: true, get: () => false }); document.dispatchEvent(new Event('visibilitychange'))")
    ok = await settle(page, 'GT.inspect().running', True, tries=50)
    check('microphone: shown again, it opens again by itself', [ok, await page.ev('window.__gum.length')], [True, 2])
    await page.click('#gt-start')
    g = await page.js('GT.inspect()')
    check('microphone: Stoppa closes it', [g['running'], g['stopped'], await page.ev("window.__gum[1].track.readyState")], [False, 'user', 'ended'])

    # Sound taken away while listening (a call, another app): one try at
    # resuming, then a tap is asked for rather than listening to silence.
    await page.click('#gt-start')
    await settle(page, 'GT.inspect().running', True, tries=50)
    await page.ev("(c => { c.resume = () => Promise.resolve(); return c.suspend(); })(GT.test.context())")
    await settle(page, 'GT.inspect().running', False, tries=40)
    g = await page.js('GT.inspect()')
    check('microphone: sound suspended under it: stops and asks for a tap', [g['running'], g['stopped'], g['msg']],
          [False, 'tap', 'Tryck på Starta för att börja lyssna.'])

    # A browser that will not start sound without a tap of its own: Starta
    # does not hang on "Startar mikrofonen …".
    await page.ev("""(() => {
      const Orig = window.AudioContext;
      window.AudioContext = class extends Orig {
        constructor(o) { super(o); this.suspend(); }
        resume() { return new Promise(() => {}); }
      };
      return true;
    })()""")
    await page.click('#gt-start')
    check('microphone: while it waits, the button cannot be pressed twice', await page.ev("document.getElementById('gt-start').disabled"), True)
    # (stopped is already 'tap' from the case above, so wait on starting)
    await settle(page, 'GT.inspect().starting', False, tries=40)
    g = await page.js('GT.inspect()')
    check('microphone: sound that never starts is given up after 1.5 s, the track stopped',
          [g['running'], g['starting'], g['stopped'], await page.ev('window.__gum[window.__gum.length - 1].track.readyState')],
          [False, False, 'tap', 'ended'])
    check('microphone: no errors', page.errors + page.console, [])


async def main():
    bws, page, _ = await attach(CDP)
    await main_suite(page)
    await phones_suite(page)
    await mic_suite(page)
    await bws.close()
    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('FAILED:\n  ' + '\n  '.join(failures))
        sys.exit(1)


asyncio.run(main())
