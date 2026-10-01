#!/usr/bin/env python3
"""The looks (Utseenden) of winnetkakort.html and flashcards.html, in a browser.

card-looks.css gives both pages twenty looks, from the site's own to space,
candy and an arcade game. This test is what keeps them readable: every look's
colours are measured against each other by WCAG contrast, and a look that is
fun but hard to read fails. It also checks the picker (each tile a preview in
its own look), that a look is kept per person and set before the first paint,
and that no look breaks the layout on a phone.

Serve the repository and start headless Chrome (the recipe is in README.md),
on ports 8847 and 9347 unless WK_HTTP_PORT and WK_CDP_PORT say otherwise:

    python3 resources/tests/winnetkakort/test-looks.py

With WK_SHOTS=<folder> it saves the picker and a card in every look.
Exit status is 0 when every check passes.
"""
import asyncio
import base64
import json
import os
import struct
import sys
import urllib.request
import zlib

import websockets

HTTP = int(os.environ.get('WK_HTTP_PORT', '8847'))
CDP = int(os.environ.get('WK_CDP_PORT', '9347'))
ORIGIN = f'http://127.0.0.1:{HTTP}'
SHOTS = os.environ.get('WK_SHOTS')

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


# What must be readable on what, and how well. Text on cards and on the page
# is held to 7:1; everything else to 4.5:1, or 3:1 for lines and rings
# (WCAG 1.4.11). A token with a fallback is written the way the CSS uses it.
PAIRS = [
    ('--text-primary', '--bg-primary', 7), ('--text-primary', '--bg-surface', 7), ('--text-primary', '--wk-paper', 7),
    ('--text-primary', '--wk-paper-back', 7), ('--text-primary', '--bg-secondary', 4.5),
    ('--text-secondary', '--bg-primary', 4.5), ('--text-secondary', '--bg-surface', 4.5), ('--text-secondary', '--wk-paper', 4.5),
    ('--text-muted', '--bg-surface', 4.5), ('--text-muted', '--wk-paper', 4.5),
    ('--text-primary', '--wk-green', 4.5), ('--text-primary', '--wk-blue', 4.5), ('--text-primary', '--wk-yellow', 4.5),
    ('--text-primary', '--wk-red', 4.5), ('--text-primary', '--wk-purple', 4.5), ('--text-primary', '--wk-teal', 4.5),
    ('--text-primary', '--wk-accent', 4.5),
    ('--wk-on-accent, #ffffff', '--accent-fill', 4.5), ('--wk-on-accent, #ffffff', '--accent-fill-hover', 4.5),
    ('--wk-on-kan', '--wk-kan', 4.5), ('--wk-on-ova, #ffffff', '--wk-ova', 4.5),
    ('--text-primary', '--wk-kan-soft', 4.5), ('--text-primary', '--wk-ova-soft', 4.5),
    ('--accent-text', '--bg-primary', 4.5), ('--accent-text', '--bg-surface', 4.5), ('--accent-text', '--wk-paper-back', 4.5),
    ('--wk-kan', '--bg-primary', 4.5), ('--wk-kan', '--wk-paper-back', 4.5),
    ('--link-color', '--bg-surface', 4.5),
    ('--accent-line', '--bg-surface', 3), ('--accent-line', '--bg-primary', 3), ('--input-border', '--input-bg', 3),
    ('--look-tick, #ffffff', '--check-fill, var(--color-kvot-accent)', 3), ('--check-fill, var(--color-kvot-accent)', '--bg-surface', 3),
]

AUDIT = """(pairs => {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const g = canvas.getContext('2d', { willReadFrequently: true });
  const rgb = css => { g.clearRect(0, 0, 1, 1); g.fillStyle = '#000'; g.fillStyle = css; g.fillRect(0, 0, 1, 1); return [...g.getImageData(0, 0, 1, 1).data].slice(0, 3); };
  const probe = document.createElement('span');
  document.querySelector('.wk-tile, .wk-group, main').appendChild(probe);
  const color = name => { if (name.startsWith('#')) return rgb(name); probe.style.color = 'var(' + name + ')'; return rgb(getComputedStyle(probe).color); };
  const lin = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  const lum = ([r, gg, b]) => 0.2126 * lin(r) + 0.7152 * lin(gg) + 0.0722 * lin(b);
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const fails = [];
  for (const [fg, bg, min] of pairs) {
    const r = ratio(color(fg), color(bg));
    if (r < min) fails.push(fg.split(',')[0] + ' on ' + bg.split(',')[0] + ': ' + r.toFixed(2) + ' < ' + min);
  }
  probe.remove();
  return fails;
})(%s)"""


def first_pixel(png):
    """The first pixel of a PNG as (r, g, b), which is all a 1 x 1 screenshot
    has. Every PNG filter leaves the first pixel of the first row as it is."""
    pos, idat = 8, b''
    while pos < len(png):
        n, kind = struct.unpack('>I4s', png[pos:pos + 8])
        if kind == b'IDAT':
            idat += png[pos + 8:pos + 8 + n]
        pos += 12 + n
    return tuple(zlib.decompress(idat)[1:4])


# The heights a page really gets on a phone, once the browser's bars have
# taken their share (as in test-ui.py).
PHONES = [(390, 664, 'An iPhone 13 upright'), (375, 548, 'An iPhone SE upright'), (667, 325, 'An iPhone SE on its side')]


class Page:
    def __init__(self, bws):
        self.bws = bws
        self.n = 0
        self.pending = {}
        self.sid = None
        self.errors = []
        self.script = None

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
            if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                self.pending[r['id']].set_result(r)

    async def ev(self, expr):
        r = await self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:300]
        return res.get('result', {}).get('value')

    async def load(self, page, width=1300, height=850, theme='light', mobile=False, keep=False):
        """The page, fresh (or with its storage kept), watching when data-look is set."""
        await self.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': mobile})
        if not self.script:
            r = await self.call('Page.addScriptToEvaluateOnNewDocument', {'source': """
              window.__lookAt = null;
              new MutationObserver((m, o) => {
                if (document.documentElement && document.documentElement.dataset.look) {
                  window.__lookAt = document.body ? 'after the body' : 'in the head'; o.disconnect();
                }
              }).observe(document, { attributes: true, subtree: true, attributeFilter: ['data-look'] });"""})
            self.script = r['result']['identifier']
        if not keep:
            await self.call('Page.navigate', {'url': f'{ORIGIN}/robots.txt'})
            await asyncio.sleep(0.3)
            await self.ev(f"localStorage.clear(); localStorage.setItem('kvot-theme', {json.dumps(theme)})")
        await self.call('Page.navigate', {'url': f'{ORIGIN}/{page}'})
        for _ in range(80):
            if await self.ev("!!document.querySelector('.wk-look') && !!document.querySelector('.wk-tile')"):
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.2)

    async def pixel(self, x, y):
        """The colour on the screen at (x, y), as the page is painted."""
        r = await self.call('Page.captureScreenshot', {'format': 'png', 'clip': {'x': x, 'y': y, 'width': 1, 'height': 1, 'scale': 1}})
        return first_pixel(base64.b64decode(r['result']['data']))

    async def shot(self, name):
        if not SHOTS:
            return
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.4)
        r = await self.call('Page.captureScreenshot', {'format': 'png'})
        with open(os.path.join(SHOTS, name), 'wb') as f:
            f.write(base64.b64decode(r['result']['data']))


async def main():
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        page = Page(bws)
        asyncio.create_task(page.pump())
        tid = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        page.sid = (await page.call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
        for m in ('Runtime.enable', 'Page.enable', 'Network.enable'):
            await page.call(m)
        await page.call('Network.setCacheDisabled', {'cacheDisabled': True})
        try:
            await run(page)
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})
    print(f'\n{checks - len(failures)} of {checks} checks passed.')
    sys.exit(1 if failures else 0)


async def run(page):
    await page.load('winnetkakort.html')
    looks = json.loads(await page.ev("JSON.stringify(CARD_LOOKS.LOOKS)"))
    ids = [l['id'] for l in looks]
    check('twenty looks, six calm and fourteen fun, every id unique',
          [len(ids), sum(l['group'] == 'lugn' for l in looks), len(set(ids))], [20, 6, 20])
    check('no script errors on load', page.errors, [])

    # --- every look readable -------------------------------------------------
    for theme in ('light', 'dark'):
        await page.ev(f"document.documentElement.setAttribute('data-theme', '{theme}'); document.documentElement.dataset.look = 'kvot'")
        check(f'Kvot, the site’s own look, {theme}: every pair readable', await page.ev(AUDIT % json.dumps(PAIRS)), [])
    await page.ev("document.documentElement.setAttribute('data-theme', 'light')")
    for look in ids[1:]:
        await page.ev(f"document.documentElement.dataset.look = '{look}'")
        check(f'{look}: every pair readable', await page.ev(AUDIT % json.dumps(PAIRS)), [])
    await page.ev("document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev("document.documentElement.dataset.look = 'godis'")
    check('a look is the same whatever the site’s own dark mode says', await page.ev(AUDIT % json.dumps(PAIRS)), [])
    check('and sets its own light or dark for the browser’s controls',
          await page.ev("getComputedStyle(document.documentElement).colorScheme"), 'light')
    await page.ev("document.documentElement.setAttribute('data-theme', 'light')")

    # --- what each look is ---------------------------------------------------
    motifs = json.loads(await page.ev("""JSON.stringify(CARD_LOOKS.ids.map(id => {
      document.documentElement.dataset.look = id;
      const v = getComputedStyle(document.body).getPropertyValue('--wk-motif').trim();
      return [id, v ? JSON.parse(v) : ''];
    }))"""))
    check('each look’s motif in the CSS is the one in the picker', [m for m, l in zip(motifs, looks) if m[1] != l['motif']], [])
    shapes = json.loads(await page.ev("""JSON.stringify(Object.fromEntries(['kvot', 'rymden', 'godis', 'pixel', 'robot'].map(id => {
      document.documentElement.dataset.look = id;
      return [id, getComputedStyle(document.querySelector('.wk-face')).clipPath.split('(')[0]];
    })))"""))
    check('cards: cut corners for Kvot and the robot, round for space and candy, square for the arcade',
          shapes, {'kvot': 'polygon', 'rymden': 'inset', 'godis': 'inset', 'pixel': 'inset', 'robot': 'polygon'})
    fonts = json.loads(await page.ev("""JSON.stringify(Object.fromEntries(['kvot', 'hjalte', 'pixel'].map(id => {
      document.documentElement.dataset.look = id;
      return [id, getComputedStyle(document.querySelector('.wk-paper')).fontFamily.split(',')[0].replace(/"/g, '')];
    })))"""))
    check('each look its own card font: Verdana, Comic Sans, monospace', fonts, {'kvot': 'verdana', 'hjalte': 'Comic Sans MS', 'pixel': 'ui-monospace'})
    await page.ev("document.documentElement.dataset.look = 'kvot'")

    # --- the picker ----------------------------------------------------------
    await page.ev("document.getElementById('wk-settings').open = true")
    tiles = json.loads(await page.ev("JSON.stringify([...document.querySelectorAll('#wk-looks .wk-look')].map(t => [t.dataset.look, t.getAttribute('aria-pressed')]))"))
    check('the picker: every look, the standard one chosen', [len(tiles), [t for t in tiles if t[1] == 'true']], [20, [['kvot', 'true']]])
    check('two groups, calm first', await page.ev("[...document.querySelectorAll('#wk-looks .wk-looks-head')].map(h => h.textContent).join(' | ')"),
          'Lugna och tydliga | Roliga')
    await page.shot('picker.png')
    await page.ev("document.querySelector('#wk-looks [data-look=rymden]').focus(); document.querySelector('#wk-looks [data-look=rymden]').click()")
    check('choosing a tile puts the page in the look, marks the tile and keeps the focus on it',
          await page.ev("[document.documentElement.dataset.look, document.querySelector('#wk-looks [data-look=rymden]').getAttribute('aria-pressed'), document.activeElement.dataset.look]"),
          ['rymden', 'true', 'rymden'])
    check('and says so in the settings line', await page.ev("document.getElementById('wk-settings-sum').textContent.endsWith('Rymden 🚀')"), True)
    check('kept with the person', await page.ev("WK.inspect().store.profiles.p1.look"), 'rymden')
    scenes = json.loads(await page.ev("""JSON.stringify(Object.fromEntries(['kvot', 'godis', 'rymden'].map(id =>
      [id, getComputedStyle(document.querySelector('#wk-looks [data-look=' + id + '] .wk-look-scene')).backgroundColor])))"""))
    check('each tile shows its own look, the standard one too, while the page is in space',
          scenes, {'kvot': 'rgb(255, 255, 255)', 'godis': 'rgb(255, 240, 246)', 'rymden': 'rgb(11, 16, 51)'})
    await page.shot('home-rymden.png')
    # The window-sized layers of a background are drawn at all: the pinned
    # body leaves <html> no height, and they came out zero pixels high while
    # the body's background was drawn by <html>. Rymden's planet is in the
    # margin, a little right of the page (1300 / 2 + 590 = 1240).
    await page.ev("document.querySelector('#wk-looks [data-look=rymden]').click()")
    await asyncio.sleep(0.3)
    near = lambda got, want: all(abs(a - b) <= 8 for a, b in zip(got, want))
    check('the planet of Rymden is drawn, in the margin beside the page', near(await page.pixel(1240, 150), (0xff, 0x9f, 0x43)), True)
    # Printed, the cards are ink on white paper, whatever the look - and
    # test-ui.py prints its PDF with the backgrounds, as a browser may.
    await page.ev("window.print = () => {}")
    await page.ev("document.querySelector('[data-on-click=\"wk:clear\"]').click(); document.querySelector('[data-set=t7]').click(); document.getElementById('wk-print-btn').click()")
    await page.call('Emulation.setEmulatedMedia', {'media': 'print'})
    check('printed: white paper, black ink and the light pile colours, in space too',
          await page.ev("""[getComputedStyle(document.documentElement).backgroundColor, getComputedStyle(document.body).backgroundColor,
                          getComputedStyle(document.body).backgroundImage, getComputedStyle(document.documentElement).colorScheme,
                          getComputedStyle(document.querySelector('#wk-print .wk-pc')).color,
                          getComputedStyle(document.querySelector('#wk-print .wk-pc-band')).backgroundColor]"""),
          ['rgb(255, 255, 255)', 'rgb(255, 255, 255)', 'none', 'light', 'rgb(0, 0, 0)', 'rgb(241, 196, 182)'])
    await page.call('Emulation.setEmulatedMedia', {'media': ''})
    await page.load('winnetkakort.html', keep=True)
    check('after a reload the look is set in the head, before the body - no flash of the standard look',
          await page.ev("[document.documentElement.dataset.look, window.__lookAt]"), ['rymden', 'in the head'])
    await page.ev("document.getElementById('wk-newperson-btn').click()")
    await page.ev("document.getElementById('wk-newname').value = 'Kim'; document.querySelector('[data-on-click=\"wk:addPerson\"]').click()")
    check('a new person starts in the standard look', await page.ev("document.documentElement.dataset.look"), 'kvot')
    await page.ev("(s => { s.value = 'p1'; s.dispatchEvent(new Event('change', { bubbles: true })); })(document.getElementById('wk-who'))")
    check('and switching back brings the first person’s look', await page.ev("document.documentElement.dataset.look"), 'rymden')
    bad = json.dumps({'v': 1, 'current': 'p1', 'profiles': {'p1': {'name': 'x', 'look': 'nonsense', 'facts': {}}}})
    await page.ev(f"localStorage.setItem('winnetkakort.v1', {json.dumps(bad)})")
    await page.load('winnetkakort.html', keep=True)
    check('a look that does not exist falls back to the standard one', [await page.ev("document.documentElement.dataset.look"),
          await page.ev("getComputedStyle(document.body).backgroundColor")], ['kvot', 'rgb(255, 255, 255)'])

    # --- every look on a phone, practising ----------------------------------------
    # A look brings wider fonts, thicker lines and other corners, so each is
    # tried where the room is least: the heights a page really gets.
    await page.call('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5})
    for width, height, name in PHONES:
        await page.load('winnetkakort.html', width, height, mobile=True)
        broken = []
        for look in ids:
            # A look is chosen as a child chooses it: the page puts the person's
            # own look back whenever it redraws, so setting data-look would not last.
            await page.ev("(b => b && b.click())(document.querySelector('[data-on-click=\"wk:quit\"]'))")
            await page.ev(f"document.querySelector('#wk-looks [data-look={look}]').click()")
            await page.ev("document.querySelector('[data-on-click=\"wk:clear\"]').click(); document.querySelector('[data-set=t7]').click(); document.getElementById('wk-start').click()")
            await asyncio.sleep(0.5)
            geo = json.loads(await page.ev("""JSON.stringify((() => {
              const s = document.getElementById('wk-scroll'), pad = document.getElementById('wk-numpad').getBoundingClientRect();
              const theme = document.querySelector('.wk-top-end > .theme-toggle');
              return { over: s.scrollHeight - s.clientHeight, side: s.scrollWidth - s.clientWidth, pad: pad.bottom <= innerHeight,
                       toggle: getComputedStyle(theme).display !== 'none' };
            })())"""))
            if geo['over'] or geo['side'] or not geo['pad'] or geo['toggle'] != (look == 'kvot'):
                broken.append([look, geo])
            if width == 390:
                await page.shot(f'phone-{look}.png')
        check(f'{name}, in every look: nothing to scroll, the key pad in sight, and the theme switch only in Kvot', broken, [])
    await page.call('Emulation.setTouchEmulationEnabled', {'enabled': False})

    # --- Glosor ------------------------------------------------------------------------
    await page.load('flashcards.html')
    check('Glosor: the same picker, every look', await page.ev("document.querySelectorAll('#fc-looks .wk-look').length"), 20)
    await page.ev("document.getElementById('fc-settings').open = true; document.querySelector('#fc-looks [data-look=dino]').click()")
    check('choosing a look there puts the page in it, and keeps it with the person',
          await page.ev("[document.documentElement.dataset.look, FC.inspect().store.profiles.p1.settings.look, document.getElementById('fc-settings-sum').textContent.endsWith('Dinosaurier 🦖')]"),
          ['dino', 'dino', True])
    fc_pairs = PAIRS + [('--text-primary', '--bg-surface', 7)]
    check('Glosor in that look: readable too', await page.ev(AUDIT % json.dumps(fc_pairs)), [])
    await page.load('flashcards.html', keep=True)
    check('Glosor after a reload: set in the head', await page.ev("[document.documentElement.dataset.look, window.__lookAt]"), ['dino', 'in the head'])
    await page.shot('glosor-dino.png')
    for look in ('hjalte', 'rymden', 'godis', 'pixel', 'tavla', 'havet'):
        await page.ev("(b => b && b.click())(document.querySelector('[data-on-click=\"fc:quit\"]'))")
        await page.ev(f"document.querySelector('#fc-looks [data-look={look}]').click()")
        await page.ev("document.querySelector('[data-on-click=\"fc:clear\"]').click(); document.querySelector('[data-set=husdjur]').click(); document.getElementById('fc-start').click()")
        await asyncio.sleep(0.5)
        await page.shot(f'glosor-{look}.png')

    # --- Glosor on the smallest phone, in every look ------------------------------------
    # Spanish typed is the tallest card, with its row of letters; four to
    # choose among is the other way of answering.
    await page.call('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5})
    for width, height, name, rounds in ((375, 548, 'an iPhone SE upright', (('skriv', 'frukt', 'es'), ('valj', 'mat', 'en'))),
                                        (667, 325, 'an iPhone SE on its side', (('skriv', 'frukt', 'es'),))):
        await page.load('flashcards.html', width, height, mobile=True)
        broken = []
        for look in ids:
            for mode, pile, lang in rounds:
                await page.ev("(b => b && b.click())(document.querySelector('[data-on-click=\"fc:quit\"]:not([hidden])'))")
                await page.ev(f"document.querySelector('#fc-looks [data-look={look}]').click()")
                await page.ev(f"document.querySelector('.fc-lang [data-lang={lang}]').click()")
                await page.ev(f"document.getElementById('fc-settings').open = true; document.querySelector('#fc-settings input[name=mode][value={mode}]').click()")
                await page.ev(f"document.querySelector('[data-on-click=\"fc:clear\"]').click(); document.querySelector('[data-set={pile}]').click(); document.getElementById('fc-start').click()")
                for _ in range(40):
                    if await page.ev("FC.inspect().round && FC.inspect().round.phase") == 'answer':
                        break
                    await asyncio.sleep(0.1)
                await asyncio.sleep(0.3)  # past the card's fade-in
                fit = json.loads(await page.ev("""JSON.stringify((() => {
                  const s = document.getElementById('fc-scroll'), d = document.getElementById('fc-deck').getBoundingClientRect();
                  const bottoms = ['fc-actions', 'fc-choices', 'fc-accents', 'fc-input'].map(id => document.getElementById(id))
                    .filter(e => e && e.checkVisibility()).map(e => Math.round(e.getBoundingClientRect().bottom));
                  return { vh: innerHeight, deckH: Math.round(d.height), deckBottom: Math.round(d.bottom), lowest: Math.max(0, ...bottoms),
                           scroll: s.scrollHeight - s.clientHeight, sideways: s.scrollWidth - s.clientWidth, ratio: Math.round(d.width / d.height * 100) / 100 };
                })())"""))
                if [fit['lowest'] <= fit['vh'], fit['deckBottom'] <= fit['vh'], fit['scroll'], fit['sideways'], fit['ratio'], fit['deckH'] >= 100] != [True, True, 0, 0, 1.5, True]:
                    broken.append([look, mode, lang, fit])
                if mode == 'skriv' and width == 375:
                    await page.shot(f'glosor-se-{look}.png')
        check(f'Glosor on {name}, in every look: the card and what answers it fit, nothing to scroll', broken, [])
    await page.call('Emulation.setTouchEmulationEnabled', {'enabled': False})
    check('no script errors at the end', page.errors, [])


asyncio.run(main())
