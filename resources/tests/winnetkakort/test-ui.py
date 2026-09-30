#!/usr/bin/env python3
"""winnetkakort.html in a real browser, played the way a child plays it.

Answers are typed and Enter pressed as trusted key events (CDP Input), not
set from script, so the page's own keyboard handling is what is tested.

Start a server on the repository root and headless Chrome, by default on
ports 8847 and 9347 (WK_HTTP_PORT and WK_CDP_PORT for others; check them first
with lsof -nP -iTCP:<port> -sTCP:LISTEN, other sessions use ports too):

    python3 -m http.server 8847 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
      --headless=new --remote-debugging-port=9347 --no-first-run \\
      --user-data-dir=/tmp/wktest --disable-gpu about:blank

    python3 resources/tests/winnetkakort/test-ui.py

With WK_SHOTS=<folder> it saves screenshots and the printed cards as a PDF.
Exit status is 0 when every check passes.
"""
import asyncio
import base64
import json
import os
import sys
import urllib.request

import websockets

HTTP = int(os.environ.get('WK_HTTP_PORT', '8847'))
CDP = int(os.environ.get('WK_CDP_PORT', '9347'))
ORIGIN = f'http://127.0.0.1:{HTTP}'
URL = f'{ORIGIN}/winnetkakort.html'
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


KEYS = {
    'Enter': ('Enter', 13, '\r'), ' ': ('Space', 32, ' '), 'ArrowRight': ('ArrowRight', 39, ''),
    'ArrowLeft': ('ArrowLeft', 37, ''), 'k': ('KeyK', 75, 'k'),
}


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

    async def key(self, k):
        code, vk, text = KEYS[k]
        down = {'type': 'keyDown', 'key': k, 'code': code, 'windowsVirtualKeyCode': vk}
        if text:
            down['text'] = text
        await self.call('Input.dispatchKeyEvent', down)
        await self.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': k, 'code': code, 'windowsVirtualKeyCode': vk})

    async def type(self, text):
        await self.call('Input.insertText', {'text': text})

    async def load(self, width=1400, height=900, theme='light', storage=None, mobile=False):
        """A fresh page in this theme, its storage as given (None: nothing stored).

        The storage is written from another page of the same origin, so the
        page under test finds it on its first load, as a returning visitor's."""
        await self.call('Emulation.setDeviceMetricsOverride',
                        {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': mobile})
        await self.call('Page.navigate', {'url': f'{ORIGIN}/robots.txt'})
        await settle(self, "document.readyState", 'complete')
        await self.ev(f"localStorage.clear(); localStorage.setItem('kvot-theme', {json.dumps(theme)});"
                      + (f"localStorage.setItem('winnetkakort.v1', {json.dumps(storage)});" if storage is not None else ''))
        await self.call('Page.navigate', {'url': URL})
        await settle(self, "!!(window.WK && document.querySelectorAll('.wk-tile').length)", True)
        await asyncio.sleep(0.2)

    async def reload(self):
        """The same page again, storage kept."""
        await self.call('Page.reload', {'ignoreCache': True})
        await asyncio.sleep(0.3)
        await settle(self, "!!(window.WK && document.querySelectorAll('.wk-tile').length)", True)

    async def shot(self, name):
        if not SHOTS:
            return
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.5)  # past the card's flip and fade-in
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


ROUND = "JSON.stringify(WK.inspect().round)"

# What of the site's chrome and the page bar is on screen, and where the page starts.
CHROME = """JSON.stringify((() => {
  const shown = sel => { const e = document.querySelector(sel); return !!e && e.checkVisibility(); };
  const c = document.querySelector('.content').getBoundingClientRect();
  return { header: shown('body > header'), footer: shown('body > footer'), menu: shown('body > .nav-toggle'),
           brand: shown('.wk-brand'), theme: shown('.wk-top-end > .theme-toggle'), full: shown('#wk-home .wk-fullbtn'),
           top: Math.round(c.top), fills: Math.round(c.height) === innerHeight,
           full_class: document.documentElement.classList.contains('wk-full') };
})())"""

# Whether the practice view fits the screen: the card, the key pad, what scrolls.
FIT = """JSON.stringify((() => {
  const b = id => document.getElementById(id).getBoundingClientRect();
  const pad = document.getElementById('wk-numpad');
  const s = document.getElementById('wk-scroll');
  const d = b('wk-deck');
  const middle = e => { const r = e.getBoundingClientRect(); return Math.round((r.top + r.bottom) / 2 / 6); };
  return { vh: innerHeight, deck: Math.round(d.bottom), deckTop: Math.round(d.top), deckH: Math.round(d.height),
           ratio: Math.round(d.width / d.height * 100) / 100,
           pad: pad.hidden ? null : Math.round(b('wk-numpad').bottom),
           scroll: s.scrollHeight, sideways: s.scrollWidth - s.clientWidth,
           scrollX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
           oneLine: new Set([...document.getElementById('wk-eq').children].map(middle)).size === 1,
           barRows: new Set([...document.querySelector('.wk-bar').children].filter(e => e.checkVisibility()).map(middle)).size };
})())"""

# What a page gets on a phone once the browser's own bars have taken their
# share: an iPhone 13 in Safari upright and on its side, an iPhone SE (the
# smallest iPhone in use) both ways, and a small Android phone in Chrome.
PHONES = [(390, 664, 'iPhone upright'), (844, 340, 'iPhone on its side'),
          (375, 548, 'iPhone SE upright'), (667, 325, 'iPhone SE on its side'),
          (360, 560, 'small Android upright')]

# Whether a tap can zoom the page, and whether the page itself can move.
STILL = """JSON.stringify((() => {
  const css = e => getComputedStyle(e);
  const fields = [...document.querySelectorAll('#wk-home select, #wk-home input[type=text]')];
  return { smallest: Math.min(...fields.map(f => parseFloat(css(f).fontSize))),
           touch: css(document.documentElement).touchAction,
           html: css(document.documentElement).overflow, body: css(document.body).position,
           overscroll: [css(document.documentElement).overscrollBehaviorY, css(document.getElementById('wk-scroll')).overscrollBehaviorY],
           sideways: css(document.getElementById('wk-scroll')).overflowX };
})())"""


async def rnd(page):
    s = await page.ev(ROUND)
    return json.loads(s) if s and s != 'null' else None


def swedish(x):
    """The answer as a child types it: decimal comma, hyphen for minus."""
    s = f'{x:.10f}'.rstrip('0').rstrip('.') if isinstance(x, float) else str(x)
    return s.replace('.', ',')


async def phase(page, want):
    return await settle(page, "WK.inspect().round && WK.inspect().round.phase", want)


async def play_card(page, answer=None, advance=True):
    """Answer the card in front of us, by keyboard; return the round after."""
    await phase(page, 'answer')
    r = await rnd(page)
    await page.ev("document.getElementById('wk-input').focus()")
    await page.type(swedish(r['answer']) if answer is None else answer)
    await page.key('Enter')
    await phase(page, 'feedback')
    after = await rnd(page)
    if advance:
        await page.key('Enter')
        await settle(page, f"(() => {{ const r = WK.inspect().round; return !r || r.phase === 'done' || r.i > {r['i']}; }})()", True)
    return after


async def play_round(page, wrong=()):
    """Every card of the round, right except the ones listed by index."""
    r = await rnd(page)
    for i in range(r['n']):
        await play_card(page, '999' if i in wrong else None)
    await settle(page, "!document.getElementById('wk-summary').hidden", True)


async def choose(page, *ids):
    await page.ev("document.querySelector('[data-on-click=\"wk:clear\"]').click()")
    for i in ids:
        await page.ev(f"document.querySelector('[data-set=\"{i}\"]').click()")


async def start(page):
    await page.ev("document.getElementById('wk-start').click()")
    await phase(page, 'answer')
    await asyncio.sleep(0.3)  # past the card's fade-in, which scales it while it runs


async def setting(page, name, value):
    await page.ev(f"document.querySelector('input[name={name}][value=\"{value}\"]').click()")


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
    await page.load()

    # --- the home view -------------------------------------------------------
    check('no script errors on load', page.errors + page.console, [])
    check('45 piles in six groups, and no "svåra kort" before anything is missed',
          await page.ev("[document.querySelectorAll('.wk-tile').length, document.querySelectorAll('.wk-group').length]"), [45, 6])
    check('nothing chosen: Börja öva and Skriv ut are off',
          await page.ev("[document.getElementById('wk-start').disabled, document.getElementById('wk-print-btn').disabled]"), [True, True])
    await choose(page, 't7')
    check('choosing the 7:ans tabell', await page.ev("document.getElementById('wk-selbar-text').textContent"), '7:ans tabell · 10 kort')
    check('the tile says it is chosen', await page.ev("document.querySelector('[data-set=t7]').getAttribute('aria-pressed')"), 'true')
    check('its example is a card from it', await page.ev("document.querySelector('[data-set=t7] .wk-tile-eg').textContent"), '7 · 7 = ?')
    check('the settings as they start', await page.ev("document.getElementById('wk-settings-sum').textContent"),
          'Skriv svaret · snabbt inom 5 s · 20 kort per omgång')
    check('no horizontal scroll at 1400 px', await page.ev("document.documentElement.scrollWidth - document.documentElement.clientWidth"), 0)
    await page.shot('home.png')

    # --- a clean round: all right, first time ---------------------------------
    await start(page)
    r = await rnd(page)
    check('the round is the ten cards, one at a time', [r['n'], r['i']], [10, 0])
    check('the answer is typed straight into the card',
          await page.ev("document.activeElement.id + ' ' + document.getElementById('wk-eq').contains(document.activeElement)"), 'wk-input true')
    check('the back, with the answer, is hidden from a screen reader until the card turns',
          await page.ev("[document.getElementById('wk-back').getAttribute('aria-hidden'), document.getElementById('wk-front').getAttribute('aria-hidden')]"),
          ['true', 'false'])
    check('the practice view says where we are', await page.ev("document.getElementById('wk-round-count').textContent"), 'Kort 1 av 10')
    under = json.loads(await page.ev("""JSON.stringify([...document.querySelectorAll('#wk-deck > .wk-under')].map(u => {
      const paper = getComputedStyle(u, '::before');
      return [getComputedStyle(u).opacity, paper.backgroundImage.startsWith('linear-gradient'), u.getAttribute('aria-hidden')];
    }))"""))
    check('under the card, two cards of the pile: opaque paper with its band, what shows while the card turns',
          under, [['1', True, 'true'], ['1', True, 'true']])
    bands = json.loads(await page.ev("""JSON.stringify((() => {
      const stops = getComputedStyle(document.querySelector('#wk-deck > .wk-under'), '::before').backgroundImage.match(/[\\d.]+px/g) || [];
      return [parseFloat(getComputedStyle(document.getElementById('wk-band-front')).height), parseFloat(stops[stops.length - 1])];
    })())"""))
    check('the card’s band lines up with theirs', abs(bands[0] - bands[1]) < 0.5 and 24 <= bands[0] <= 34, True)
    await page.shot('practice.png')
    after = await play_card(page, advance=False)
    check('a quick right answer goes to Kan', [after['kan'], after['ova']], [1, 0])
    check('the card has turned, and the back is what a screen reader finds',
          await page.ev("[document.getElementById('wk-card').dataset.side, document.getElementById('wk-back').getAttribute('aria-hidden')]"),
          ['back', 'false'])
    check('it says so', await page.ev("document.getElementById('wk-feedback').textContent"), 'Rätt!')
    await page.shot('practice-back.png')
    await page.key('Enter')
    for _ in range(9):
        await play_card(page)
    await settle(page, "!document.getElementById('wk-summary').hidden", True)
    check('all ten in Kan', await page.ev("[document.getElementById('wk-sum-title').textContent, document.getElementById('wk-sum-kan').textContent, document.getElementById('wk-sum-ova').textContent]"),
          ['Alla kort hamnade i Kan-högen!', '10', '0'])
    check('the time is the first record for the pile',
          await page.ev("document.getElementById('wk-sum-time').textContent.endsWith('Det är ditt rekord för den här högen.')"), True)
    st = json.loads(await page.ev("JSON.stringify(WK.inspect().store)"))
    check('the record is kept', st['profiles']['p1']['best'].get('t7', 0) > 0, True)
    check('each fact is kept: right once, never wrong', st['profiles']['p1']['facts']['mul:7:7'] | {'t': 0, 'd': ''},
          {'n': 1, 'w': 0, 's': 1, 't': 0, 'd': ''})
    check('never missed and right once is "kan"', await page.ev("WK.inspect().status('mul:7:7')"), 'kan')
    await page.shot('summary.png')
    await page.ev("document.querySelector('[data-on-click=\"wk:home\"]').click()")
    check('the tile shows it', await page.ev("document.querySelector('[data-set=t7] .wk-tile-meta').textContent.startsWith('10 kort · 10 kan · rekord 0:0')"), True)
    check('and its meter is full', await page.ev("document.querySelector('[data-set=t7] .wk-meter-kan').style.width"), '100%')

    # --- the progress grid -----------------------------------------------------
    await page.ev("document.querySelector('[data-grid=ganger]').click()")
    check('the times grid: 10 of 100 known, the 7 column',
          await page.ev("[document.getElementById('wk-grid-sum').textContent.slice(0, 18), [...document.querySelectorAll('.wk-cell[data-status=kan]')].map(c => c.dataset.key).join(' ')]"),
          ['Du kan 10 av 100. ', ' '.join(f'mul:{k}:7' for k in range(1, 11))])
    await page.ev("document.querySelector('.wk-cell[data-key=\"mul:6:7\"]').click()")
    check('a cell tells its story', await page.ev("document.getElementById('wk-grid-caption').textContent"),
          '6 · 7 = 42 · kan · övat en gång, inga fel')
    check('the minus and division grids are whole',
          [await page.ev("(document.querySelector('[data-grid=minus]').click(), document.querySelectorAll('.wk-cell').length)"),
           await page.ev("(document.querySelector('[data-grid=delat]').click(), document.querySelectorAll('.wk-cell').length)")], [81, 90])

    # --- a wrong answer, and the Öva mer pile ------------------------------------
    await choose(page, 't3')
    await start(page)
    first = (await rnd(page))['key']
    after = await play_card(page, '999', advance=False)
    check('a wrong answer goes to Öva mer', [after['kan'], after['ova']], [0, 1])
    check('the right answer is shown and Nästa kort waits, focused',
          await page.ev("[document.getElementById('wk-feedback').textContent.startsWith('Inte riktigt – rätt svar är '), document.activeElement.id]"),
          [True, 'wk-next'])
    check('the back says what was typed', await page.ev("document.getElementById('wk-verdict').textContent"), 'Du skrev 999')
    await page.shot('practice-wrong.png')
    await asyncio.sleep(1.5)
    check('a wrong card does not move on by itself', (await rnd(page))['phase'], 'feedback')
    await page.key('Enter')
    for _ in range(9):
        await play_card(page)
    await settle(page, "!document.getElementById('wk-summary').hidden", True)
    check('the summary lists the card to practise', await page.ev("document.querySelectorAll('.wk-chip').length"), 1)
    check('a round with a miss sets no record',
          json.loads(await page.ev("JSON.stringify(WK.inspect().store)"))['profiles']['p1']['best'].get('t3'), None)
    check('missed is "öva mer"', await page.ev(f"WK.inspect().status('{first}')"), 'ova')
    check('the first button offers the Öva mer pile', await page.ev("document.activeElement.textContent"), 'Öva på kortet igen')
    await page.ev("document.querySelector('[data-on-click=\"wk:home\"]').click()")
    check('back home, the missed card is in "Mina svåra kort"',
          await page.ev("[document.querySelectorAll('.wk-group').length, document.querySelector('[data-set=svara] .wk-tile-meta').textContent]"),
          [7, '1 kort'])
    await choose(page, 'svara')
    await start(page)
    check('"Mina svåra kort" is that card', [(await rnd(page))['key'], (await rnd(page))['n']], [first, 1])
    await play_round(page)
    check('right once after a miss is "på gång"', await page.ev(f"WK.inspect().status('{first}')"), 'nara')
    await page.ev("document.querySelector('[data-on-click=\"wk:repeat\"]').click()")
    await phase(page, 'answer')
    await play_round(page)
    check('twice in a row is "kan"', await page.ev(f"WK.inspect().status('{first}')"), 'kan')

    # --- Öva på de … korten igen -------------------------------------------------
    await page.ev("document.querySelector('[data-on-click=\"wk:home\"]').click()")
    await choose(page, 'd4')
    await start(page)
    await play_round(page, wrong={0, 1})
    check('two missed', await page.ev("document.getElementById('wk-sum-ova').textContent"), '2')
    await page.ev("document.querySelector('[data-on-click=\"wk:again\"]').click()")
    await phase(page, 'answer')
    check('the next round is just those two, and says so',
          [(await rnd(page))['n'], await page.ev("document.getElementById('wk-round-title').textContent")], [2, 'Öva mer · Delat med 4'])
    await play_round(page)
    check('the Öva mer pile is empty', await page.ev("document.getElementById('wk-sum-title').textContent"), 'Alla kort hamnade i Kan-högen!')

    # --- the hint and the slow answer --------------------------------------------
    await page.ev("document.querySelector('[data-on-click=\"wk:home\"]').click()")
    await choose(page, 'sp')
    await start(page)
    await page.ev("document.querySelector('[data-on-click=\"wk:hint\"]').click()")
    check('the hint shows a way to think and a picture',
          await page.ev("[!document.getElementById('wk-hint').hidden, !!document.querySelector('#wk-hint svg'), document.querySelector('[data-on-click=\"wk:hint\"]').disabled]"),
          [True, True, True])
    await page.shot('practice-hint.png')
    after = await play_card(page, advance=False)
    check('right with the hint goes to Öva mer', [after['kan'], after['ova']], [0, 1])
    check('and says why', await page.ev("document.getElementById('wk-feedback').textContent.includes('tipset')"), True)
    await page.key('Enter')
    await page.ev("document.querySelector('[data-on-click=\"wk:quit\"]').click()")
    check('Avsluta goes home', await page.ev("[document.getElementById('wk-home').hidden, WK.inspect().round]"), [False, None])
    await page.ev("document.getElementById('wk-settings').open = true")
    await setting(page, 'limit', '3')
    await start(page)
    await asyncio.sleep(3.3)
    after = await play_card(page, advance=False)
    check('right but slower than the limit goes to Öva mer', [after['kan'], after['ova']], [0, 1])
    check('and says how long it took', await page.ev("/^Rätt, men det tog 3,\\d sekunder/.test(document.getElementById('wk-feedback').textContent)"), True)
    await page.key('Enter')
    await page.ev("document.querySelector('[data-on-click=\"wk:quit\"]').click()")
    await setting(page, 'limit', '0')
    await start(page)
    await asyncio.sleep(0.4)
    check('with no time limit there is no timer bar', await page.ev("document.getElementById('wk-timer').hidden"), True)
    await page.ev("document.querySelector('[data-on-click=\"wk:quit\"]').click()")
    await setting(page, 'limit', '5')

    # --- not a number -----------------------------------------------------------
    await choose(page, 't2')
    await start(page)
    await page.ev("document.getElementById('wk-input').focus()")
    await page.type('abc')
    check('letters are not typed into the answer', await page.ev("document.getElementById('wk-input').value"), '')
    await page.key('Enter')
    check('an empty answer is asked for, not marked', [await page.ev("document.getElementById('wk-feedback').textContent"), (await rnd(page))['phase']],
          ['Skriv ditt svar först.', 'answer'])
    await page.ev("document.querySelector('[data-on-click=\"wk:quit\"]').click()")

    # --- decimals and negatives, as typed ----------------------------------------
    for pile, label in (('bdp', 'decimal comma'), ('neg', 'minus as a hyphen'), ('tiop', 'tenths and hundredths')):
        await choose(page, pile)
        await setting(page, 'count', '0')
        await start(page)
        await play_round(page)
        check(f'{label}: the whole {pile} pile, typed, all right',
              await page.ev("[document.getElementById('wk-sum-kan').textContent, document.getElementById('wk-sum-ova').textContent]"),
              [str(json.loads(await page.ev(f"JSON.stringify(WK_SETS.setById['{pile}'].facts.length)"))), '0'])
        await page.ev("document.querySelector('[data-on-click=\"wk:home\"]').click()")
    await choose(page, 'neg')
    await start(page)
    while (await rnd(page))['answer'] >= 0:
        await play_card(page)
    before = (await rnd(page))['kan']
    after = await play_card(page, swedish((await rnd(page))['answer']).replace('-', '−'), advance=False)
    check('the true minus sign is read too', after['kan'], before + 1)
    await page.ev("document.querySelector('[data-on-click=\"wk:quit\"]').click()")
    await setting(page, 'count', '20')

    # --- a big pile starts with what needs practice --------------------------------
    seeded = await page.ev("""(() => {
      const s = JSON.parse(localStorage.getItem('winnetkakort.v1'));
      for (const k of ['mul:3:4', 'mul:6:8', 'mul:9:7']) s.profiles.p1.facts[k] = { n: 2, w: 2, s: 0, t: 4000, d: '2026-09-30' };
      localStorage.setItem('winnetkakort.v1', JSON.stringify(s));
      return true; })()""")
    await page.reload()
    await choose(page, 'tall')
    await setting(page, 'count', '10')
    await start(page)
    keys = json.loads(await page.ev("JSON.stringify(WK.inspect().keys)"))
    check('ten of the hundred, and the three missed ones are among them',
          [len(keys), all(k in keys for k in ['mul:3:4', 'mul:6:8', 'mul:9:7'])], [10, True])
    await page.ev("document.querySelector('[data-on-click=\"wk:quit\"]').click()")
    await setting(page, 'count', '20')

    # --- question forms and signs ---------------------------------------------------
    await setting(page, 'form', 'saknat')
    await setting(page, 'signs', 'kryss')
    check('× in the tiles once chosen', await page.ev("document.querySelector('[data-set=t7] .wk-tile-eg').textContent"), '7 × 7 = ?')
    await choose(page, 't6')
    await start(page)
    forms = set()
    check('× on the card too', await page.ev("document.querySelector('#wk-eq .wk-sym').textContent"), '×')
    misplaced = []
    for _ in range(10):
        r = await rnd(page)
        forms.add(r['form'])
        where = await page.ev("[...document.getElementById('wk-eq').children].findIndex(e => e.id === 'wk-input')")
        if where != {'a': 0, 'b': 2}.get(r['form']):
            misplaced.append((r['key'], r['form'], where))
        await play_card(page)
    check('"Saknat tal": never the plain result', forms <= {'a', 'b'}, True)
    check('"Saknat tal": the box stands where the missing number is', misplaced, [])
    await settle(page, "!document.getElementById('wk-summary').hidden", True)
    await page.ev("document.querySelector('[data-on-click=\"wk:home\"]').click()")
    await setting(page, 'form', 'vanlig')
    await setting(page, 'signs', 'punkt')

    # --- turn the card over (Vänd kortet) ---------------------------------------------
    await setting(page, 'mode', 'vand')
    await choose(page, 't5')
    await start(page)
    check('no answer box, a question mark', await page.ev("[!!document.getElementById('wk-input'), document.querySelector('#wk-eq .wk-blank-q').textContent]"), [False, '?'])
    await page.key(' ')
    await phase(page, 'judge')
    check('Space turns the card; the child says which pile',
          await page.ev("[document.getElementById('wk-card').dataset.side, [...document.querySelectorAll('#wk-actions button')].map(b => b.textContent).join(' | ')]"),
          ['back', '← Öva mer | Kan →'])
    await page.shot('flip-judge.png')
    await page.key('ArrowRight')
    await phase(page, 'answer')
    await page.key(' ')
    await phase(page, 'judge')
    await page.key('ArrowLeft')
    await phase(page, 'answer')
    await page.key(' ')
    await phase(page, 'judge')
    await page.key('k')
    await phase(page, 'answer')
    await page.ev("document.getElementById('wk-deck').click()")
    await phase(page, 'judge')
    await page.ev("document.getElementById('wk-pile-kan').click()")
    await phase(page, 'answer')
    r = await rnd(page)
    check('→, ← , K and a tap on the pile sort the cards', [r['kan'], r['ova'], r['i']], [3, 1, 4])
    await page.ev("document.querySelector('[data-on-click=\"wk:hint\"]').click()")
    await page.ev("document.querySelector('[data-on-click=\"wk:flip\"]').click()")
    await phase(page, 'judge')
    check('with the hint, Kan is off', await page.ev("document.querySelector('[data-kan=\"1\"]').disabled"), True)
    await page.key('ArrowRight')
    await asyncio.sleep(0.2)
    check('and → does not put it there', (await rnd(page))['phase'], 'judge')
    await page.key('ArrowLeft')
    for _ in range(5):
        await phase(page, 'answer')
        await page.key(' ')
        await phase(page, 'judge')
        await page.key('ArrowRight')
    await settle(page, "!document.getElementById('wk-summary').hidden", True)
    check('Vänd kortet keeps no time and no record', await page.ev("document.getElementById('wk-sum-time').textContent"), '')
    await page.ev("document.querySelector('[data-on-click=\"wk:home\"]').click()")
    await setting(page, 'mode', 'skriv')

    # --- the key pad --------------------------------------------------------------------
    await page.ev("document.getElementById('wk-settings').open = true")
    await setting(page, 'pad', 'pa')
    await choose(page, 'neg')
    await start(page)
    check('the key pad, and no system keyboard over it',
          await page.ev("[!document.getElementById('wk-numpad').hidden, document.querySelectorAll('#wk-numpad button').length, document.getElementById('wk-input').inputMode]"),
          [True, 14, 'none'])
    ans = (await rnd(page))['answer']
    for ch in swedish(abs(ans)):
        name = 'comma' if ch == ',' else ch
        await page.ev(f"document.querySelector('#wk-numpad [data-key=\"{name}\"]').click()")
    if ans < 0:
        await page.ev("document.querySelector('#wk-numpad [data-key=minus]').click()")
    check('the keys write the answer, the minus key in front', await page.ev("document.getElementById('wk-input').value"),
          ('−' if ans < 0 else '') + swedish(abs(ans)))
    await page.ev("document.querySelector('#wk-numpad [data-key=ok]').click()")
    await phase(page, 'feedback')
    check('OK answers', (await rnd(page))['kan'], 1)
    await page.ev("document.querySelector('[data-on-click=\"wk:quit\"]').click()")
    await setting(page, 'pad', 'av')

    # --- settings are kept -------------------------------------------------------------
    await setting(page, 'mode', 'vand')
    await page.reload()
    check('the settings outlive the page', await page.ev("document.querySelector('input[name=mode]:checked').value"), 'vand')
    await setting(page, 'mode', 'skriv')

    # --- people -------------------------------------------------------------------------
    mine = await page.ev("document.querySelector('[data-set=t7] .wk-tile-meta').textContent")
    await page.ev("document.getElementById('wk-newperson-btn').click()")
    await page.type('Anna')
    await page.key('Enter')
    check('a new person, chosen at once, starts from nothing',
          await page.ev("[document.getElementById('wk-who').selectedOptions[0].textContent, document.querySelector('[data-set=t7] .wk-tile-meta').textContent]"),
          ['Anna', '10 kort'])
    await page.ev("(() => { const s = document.getElementById('wk-who'); s.value = 'p1'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
    check('the first one keeps their progress', await page.ev("document.querySelector('[data-set=t7] .wk-tile-meta').textContent"), mine)
    await page.ev("(() => { const s = document.getElementById('wk-who'); s.value = 'p2'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
    await page.ev("document.getElementById('wk-remove').click()")
    check('removing asks first', [await page.ev("document.getElementById('wk-remove').textContent"), await page.ev("document.getElementById('wk-who').options.length")],
          ['Tryck igen för att ta bort Anna', 2])
    await page.ev("document.getElementById('wk-remove').click()")
    check('then removes', await page.ev("[document.getElementById('wk-who').options.length, document.getElementById('wk-remove').hidden]"), [1, True])

    # --- printing ------------------------------------------------------------------------
    await choose(page, 't7', 'tio')
    await page.ev("window.print = () => { window.__printed = (window.__printed || 0) + 1; }")
    await page.ev("document.getElementById('wk-print-btn').click()")
    check('Skriv ut asks the browser to print', await page.ev("window.__printed"), 1)
    sheets = json.loads(await page.ev("""JSON.stringify([...document.querySelectorAll('#wk-print .wk-sheet')].map(s => ({
      side: s.dataset.side,
      cards: [...s.querySelectorAll('.wk-pc:not(.wk-pc-empty)')].length,
      first: [...s.querySelectorAll('.wk-pc')].slice(0, 3).map(c => c.textContent.trim()) })))"""))
    check('21 cards: two sheets, front and back', [(s['side'], s['cards']) for s in sheets],
          [('front', 18), ('back', 18), ('front', 3), ('back', 3)])
    row = json.loads(await page.ev("""JSON.stringify([
      [...document.querySelectorAll('#wk-print .wk-sheet')[0].querySelectorAll('.wk-pc-eq')].slice(0, 3).map(e => e.textContent),
      [...document.querySelectorAll('#wk-print .wk-sheet')[1].querySelectorAll('.wk-pc-ans')].slice(0, 3).map(e => e.textContent)])"""))
    # Tiokompisar come first, in pile order: 0 + ? = 10, 1 + ? = 10, 2 + ? = 10.
    check('the first row on the front, and its answers mirrored behind it',
          row, [['0+=10', '1+=10', '2+=10'], ['8', '9', '10']])
    await page.call('Emulation.setEmulatedMedia', {'media': 'print'})
    check('printing shows only the cards',
          await page.ev("[getComputedStyle(document.getElementById('wk-print')).display, getComputedStyle(document.querySelector('.content')).display, getComputedStyle(document.querySelector('header')).display]"),
          ['block', 'none', 'none'])
    pdf = await page.call('Page.printToPDF', {'preferCSSPageSize': True, 'printBackground': True})
    data = base64.b64decode(pdf['result']['data'])
    check('four A4 pages', data.count(b'/Type /Page') - data.count(b'/Type /Pages'), 4)
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        with open(os.path.join(SHOTS, 'cards.pdf'), 'wb') as f:
            f.write(data)
    await page.call('Emulation.setEmulatedMedia', {'media': ''})

    # --- reset -------------------------------------------------------------------------------
    await page.ev("document.getElementById('wk-reset').click()")
    await page.ev("document.getElementById('wk-reset').click()")
    check('reset, after asking, clears the progress',
          await page.ev("[Object.keys(WK.inspect().store.profiles.p1.facts).length, document.querySelector('[data-set=t7] .wk-tile-meta').textContent]"),
          [0, '10 kort'])
    check('no script errors while playing', page.errors + page.console, [])

    # --- storage that is not ours --------------------------------------------------------------
    page.errors.clear()
    await page.load(storage='{not json')
    check('broken storage: the page starts afresh', await page.ev("[document.querySelectorAll('.wk-tile').length, WK.inspect().store.current]"), [45, 'p1'])
    hostile = json.dumps({'v': 1, 'current': 'p1', 'settings': {'mode': 'hack', 'limit': 7},
                          'profiles': {'p1': {'name': '<img src=x onerror="window.__pwned=1">', 'facts': {'__proto__': {'n': 5}, 'mul:2:2': {'n': 'x'}}},
                                       'evil': {'name': 'x'}}})
    await page.load(storage=hostile)
    check('a name from storage is text, never markup, and at most 30 characters',
          await page.ev("[document.getElementById('wk-who').options[0].textContent, !!document.querySelector('#wk-who img'), !!window.__pwned]"),
          ['<img src=x onerror="window.__pwned=1">'[:30], False, False])
    check('unknown settings and ids are dropped', await page.ev("[WK.inspect().store.settings.mode, WK.inspect().store.settings.limit, Object.keys(WK.inspect().store.profiles).join()]"),
          ['skriv', 5, 'p1'])
    check('and a fact key cannot reach the prototype', await page.ev("({}).n === undefined && WK.inspect().status('mul:2:2')"), 'none')
    check('no script errors with hostile storage', page.errors + page.console, [])

    # --- dark ------------------------------------------------------------------------------------------
    await page.load(theme='dark')
    check('dark: the pile colours change with the theme',
          await page.ev("getComputedStyle(document.body).getPropertyValue('--wk-green').trim()"), '#46592f')
    await page.shot('home-dark.png')

    # --- the full window ----------------------------------------------------------------------------------
    await page.load()
    chrome = json.loads(await page.ev(CHROME))
    check('desktop: the site header and footer, and the full-window button',
          [chrome[k] for k in ('header', 'footer', 'menu', 'full', 'brand', 'theme', 'top')], [True, True, True, True, False, False, 43])
    button = "document.querySelector('#wk-home .wk-fullbtn')"
    check('the button says what it does', await page.ev(f"[{button}.getAttribute('aria-label'), {button}.getAttribute('aria-pressed'), {button}.title]"),
          ['Helt fönster', 'false', 'Helt fönster: sidan utan sajtens sidhuvud och sidfot'])
    await page.ev(f"{button}.click()")
    chrome = json.loads(await page.ev(CHROME))
    check('the full window: no site header, footer or menu, and the page fills the window',
          [chrome[k] for k in ('header', 'footer', 'menu', 'top', 'fills')], [False, False, False, 0, True])
    check('the page bar takes over: the kvot mark, the title and the theme switch',
          [chrome['brand'], chrome['theme'], chrome['full']], [True, True, True])
    check('the button shows it is on, and offers the way back',
          await page.ev(f"[{button}.getAttribute('aria-pressed'), {button}.title, localStorage.getItem('winnetkakort.full')]"),
          ['true', 'Visa sajtens sidhuvud och sidfot igen', '1'])
    check('the mark goes to the home page', await page.ev(
          "[new URL(document.querySelector('.wk-homelink').href).pathname, document.querySelector('.wk-homelink img').alt]"),
          ['/index.html', 'kvot ab: startsidan'])
    theme = "document.querySelector('.wk-top-end > .theme-toggle')"
    await page.ev(f"{theme}.click()")
    check('the theme switch in the page bar works like the footer’s', await page.ev(f"[document.documentElement.dataset.theme, {theme}.textContent]"), ['dark', '☀️'])
    await page.ev(f"{theme}.click()")
    check('and back', await page.ev(f"[document.documentElement.dataset.theme, {theme}.textContent]"), ['light', '🌙'])
    await page.shot('desktop-full.png')
    await page.reload()
    chrome = json.loads(await page.ev(CHROME))
    check('the full window outlives the page, set in its head before the first paint',
          [chrome['full_class'], chrome['header'], chrome['top'], await page.ev(f"{button}.getAttribute('aria-pressed')")], [True, False, 0, 'true'])
    await choose(page, 't2')
    await start(page)
    bar = "document.querySelector('.wk-bar .wk-fullbtn')"
    check('practising, the button is at the end of the bar', await page.ev(f"[{bar}.checkVisibility(), {bar}.getAttribute('aria-pressed')]"), [True, 'true'])
    await page.ev(f"{bar}.click()")
    chrome = json.loads(await page.ev(CHROME))
    check('and brings the header and footer back, for both buttons',
          [chrome['header'], chrome['footer'], chrome['top'], await page.ev(f"[{bar}, {button}].map(b => b.getAttribute('aria-pressed')).join()"),
           await page.ev("localStorage.getItem('winnetkakort.full')")], [True, True, 43, 'false,false', '0'])
    check('the round goes on meanwhile', (await rnd(page))['phase'], 'answer')
    await page.ev("document.querySelector('[data-on-click=\"wk:quit\"]').click()")

    # --- phones: never the header and footer --------------------------------------------------------------
    await page.call('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5})
    for width, height, name in PHONES:
        await page.load(width, height, mobile=True)
        chrome = json.loads(await page.ev(CHROME))
        check(f'{name}: no site header, footer or menu, and no full-window button either',
              [chrome[k] for k in ('header', 'footer', 'menu', 'full', 'top', 'fills')], [False, False, False, False, 0, True])
        check(f'{name}: the kvot mark, the title and the theme switch instead', [chrome['brand'], chrome['theme']], [True, True])
        still = json.loads(await page.ev(STILL))
        check(f'{name}: no tap can zoom the page (fields 16px, no double-tap zoom), and the page itself cannot move',
              [still['smallest'] >= 16, still['touch'], still['html'], still['body'], still['overscroll'], still['sideways']],
              [True, 'manipulation', 'hidden', 'fixed', ['none', 'contain'], 'hidden'])
        check(f'{name}: no horizontal scroll on the home view',
              await page.ev("[document.documentElement.scrollWidth - document.documentElement.clientWidth, (s => s.scrollWidth - s.clientWidth)(document.getElementById('wk-scroll'))]"),
              [0, 0])
        await choose(page, 't8')
        await start(page)
        fit = json.loads(await page.ev(FIT))
        check(f'{name}: the key pad comes by itself on a touch screen', fit['pad'] is not None, True)
        check(f'{name}: the card and the key pad fit the screen, with nothing to scroll either way',
              [fit['deck'] <= fit['vh'], fit['pad'] <= fit['vh'], fit['scroll'] <= fit['vh'], fit['sideways'], fit['scrollX']], [True, True, True, 0, 0])
        check(f'{name}: the card is 3:2 and of a good size', [fit['ratio'], fit['deckH'] >= 150], [1.5, True])
        check(f'{name}: the card’s sum is on one line, and the bar over it one row', [fit['oneLine'], fit['barRows']], [True, 1])
        await page.ev("document.querySelector('[data-on-click=\"wk:hint\"]').click()")
        hinted = json.loads(await page.ev(FIT))
        check(f'{name}: with the hint open the card and the pad still fit, the card at most a little smaller',
              [hinted['pad'] <= hinted['vh'], hinted['scroll'] <= hinted['vh'], hinted['sideways'], hinted['ratio'], hinted['oneLine'],
               fit['deckH'] * 0.7 <= hinted['deckH'] <= fit['deckH']], [True, True, 0, 1.5, True, True])
        await page.shot(f"{name.replace(' ', '-').replace('’', '')}.png")
        await play_card(page, advance=False)
        check(f'{name}: and it answers', (await rnd(page))['phase'], 'feedback')
    await page.load(820, 1180, mobile=True)
    chrome = json.loads(await page.ev(CHROME))
    check('a tablet keeps the header and footer, and the button', [chrome['header'], chrome['footer'], chrome['full']], [True, True, True])
    await page.call('Emulation.setTouchEmulationEnabled', {'enabled': False})

    # --- reduced motion ------------------------------------------------------------------------------------
    await page.load()
    await choose(page, 't8')
    await start(page)
    await page.call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
    await play_card(page, advance=False)
    await page.key('Enter')
    check('reduced motion: the next card comes at once', (await rnd(page))['i'], 1)
    await page.call('Emulation.setEmulatedMedia', {'features': []})
    check('no script errors at the end', page.errors + page.console, [])


asyncio.run(main())
