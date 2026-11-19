#!/usr/bin/env python3
"""piano.html in a real browser.

Lessons are walked an exercise at a time: keys are pressed on the screen's
keyboard with the mouse (a trusted click, after which a browser lets a page
use sound), on the computer's keyboard, or handed to the page as heard
(PN.test.hear). Piano notes made in the page by synth.js are played through
the page's real audio path in place of the microphone (PN.test.play), and a
MediaStream is handed to the page by getUserMedia after a trusted click on
the microphone button (why not Chrome's own fake microphone: it never
settles in headless Chrome on macOS; see ../gitarr/test-ui.py).

Start a server on the repository root and headless Chrome, by default on
ports 8851 and 9351 (PN_HTTP_PORT and PN_CDP_PORT for others). Check the
ports first with lsof -nP -iTCP:<port> -sTCP:LISTEN, other sessions use
ports too:

    python3 -m http.server 8851 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
      --headless=new --remote-debugging-port=9351 --no-first-run \\
      --user-data-dir=/tmp/pntest --disable-gpu \\
      --autoplay-policy=no-user-gesture-required about:blank

    python3 resources/tests/piano/test-ui.py

With PN_SHOTS=<folder> it saves screenshots. Exit status is 0 when every
check passes.
"""
import asyncio
import base64
import json
import os
import sys
import urllib.request

import websockets

HTTP = int(os.environ.get('PN_HTTP_PORT', '8851'))
CDP = int(os.environ.get('PN_CDP_PORT', '9351'))
ORIGIN = f'http://127.0.0.1:{HTTP}'
URL = f'{ORIGIN}/piano.html'
SHOTS = os.environ.get('PN_SHOTS')
HERE = os.path.dirname(os.path.abspath(__file__))
SYNTH = (open(os.path.join(HERE, '..', 'gitarr', 'synth.js'), encoding='utf-8').read()
         + open(os.path.join(HERE, 'synth.js'), encoding='utf-8').read())

failures = []
checks = 0
LESSONS = SONGS = XMAS = 0      # read from the page by main_suite


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

    async def state(self):
        return await self.js('PN.inspect()')

    async def click_xy(self, x, y):
        for kind in ('mousePressed', 'mouseReleased'):
            await self.call('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})

    async def click(self, selector):
        """A real click, with the mouse: unlike element.click(), it counts as
        the tap after which a browser lets a page use sound."""
        xy = await self.js("(e => { e.scrollIntoView({ block: 'center' }); const r = e.getBoundingClientRect();"
                           f" return [r.left + r.width / 2, r.top + r.height / 2]; }})(document.querySelector({json.dumps(selector)}))")
        await self.click_xy(*xy)

    async def tap(self, selector):
        """A finger on a touch screen."""
        xy = await self.js(f"(e => {{ const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height * 0.8]; }})(document.querySelector({json.dumps(selector)}))")
        await self.call('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': xy[0], 'y': xy[1]}]})
        await self.call('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})

    async def key(self, k, code, vk):
        down = {'type': 'keyDown', 'key': k, 'code': code, 'windowsVirtualKeyCode': vk}
        if len(k) == 1:
            down['text'] = k
        await self.call('Input.dispatchKeyEvent', down)
        await self.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': k, 'code': code, 'windowsVirtualKeyCode': vk})

    async def load(self, width=1280, height=800, theme='light', mobile=False, store=None):
        """A fresh page; what it has stored as given (None: nothing)."""
        await self.call('Emulation.setDeviceMetricsOverride',
                        {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': mobile})
        await self.call('Emulation.setTouchEmulationEnabled', {'enabled': mobile, 'maxTouchPoints': 5 if mobile else 0})
        await self.call('Page.navigate', {'url': f'{ORIGIN}/robots.txt'})
        await settle(self, 'document.readyState', 'complete')
        await self.ev(f"localStorage.clear(); localStorage.setItem('kvot-theme', {json.dumps(theme)});"
                      + (f"localStorage.setItem('piano.v1', {json.dumps(json.dumps(store))});" if store is not None else ''))
        await self.reload()

    async def reload(self):
        await self.call('Page.navigate', {'url': URL})
        # typeof, not window.PN: a top-level const is not a property of window
        await settle(self, "typeof PN !== 'undefined' && document.querySelectorAll('.pn-node').length > 10", True)
        await self.ev(SYNTH)
        await asyncio.sleep(0.15)

    async def shot(self, name):
        if not SHOTS:
            return
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.35)
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


OPEN = {'v': 1, 'settings': {'openAll': True}}

# Every note of a melody in time, played at its moment inside the page:
# `skip` leaves out notes by index, `late` (ms) delays one.
PLAY_IN_TIME = """(() => {
  const i = PN.inspect().tempo, skip = %s, late = %s;
  i.midis.forEach((m, k) => { if (!skip.includes(k)) setTimeout(() => PN.test.hear(m), i.t0 + i.times[k] * 1000 - performance.now() + 15 + (late[k] || 0)); });
  return i.midis.length;
})()"""


async def next_exercise(page, i, tries=80):
    """Wait until the lesson has moved past exercise i (or ended)."""
    return await settle(page, f"(g => g.view !== 'lesson' || g.run.i !== {i})(PN.inspect())", True, tries=tries, pause=0.05)


async def solve(page, wrong=0):
    """Answer the exercise on screen right (after `wrong` wrong keys), and
    wait for the next one. Returns the exercise's type."""
    g = await page.state()
    ex = g['ex']
    i = g['run']['i']
    kind = ex['type']
    if kind == 'info':
        await page.click('#pn-go')
    elif kind == 'find':
        for _ in range(wrong):
            await page.ev(f"PN.test.hear({ex['note'] + 2})")
        await page.ev(f"PN.test.hear({ex['note']})")
        await page.click('#pn-go')
    elif kind == 'name':
        for m in [c for c in ex['choices'] if c != ex['note']][:wrong]:
            await page.click(f'.pn-choice[data-midi="{m}"]')
        await page.click(f'.pn-choice[data-midi="{ex["note"]}"]')
        await page.click('#pn-go')
    elif kind in ('echo', 'play'):
        if kind == 'echo':
            await settle(page, 'PN.inspect().alt', 'Lyssna igen', tries=200, pause=0.05)
        for k, m in enumerate(ex['midis']):
            if k < wrong:
                await page.ev(f"PN.test.hear({m + 1})")
            await page.ev(f"PN.test.hear({m})")
        await page.click('#pn-go')
    elif kind == 'tempo':
        await page.click('#pn-go')
        await page.ev(PLAY_IN_TIME % ('[]', '{}'))
        await settle(page, 'PN.inspect().tempo.state', 'done', tries=400, pause=0.05)
        await page.click('#pn-go')
    await next_exercise(page, i)
    return kind


async def start(page, lesson):
    await page.click(f'.pn-node[data-id="{lesson}"]')
    await settle(page, 'PN.inspect().view', 'lesson')


async def walk(page, lesson, until=None):
    """A lesson from its start, every answer right, to its end - or until an
    exercise for which until(ex) holds is on screen."""
    await start(page, lesson)
    for _ in range(40):
        g = await page.state()
        if g['view'] != 'lesson' or (until and until(g['ex'])):
            return g
        await solve(page)
    return await page.state()


SHOWN = "(s => { const e = document.querySelector(s); return !!e && e.checkVisibility(); })"


async def main_suite(page):
    await page.load()
    g = await page.state()
    check('home: the page opens on the path', [g['view'], g['tab'], await page.ev('document.title')], ['home', 'path', 'Pianoskolan — kvot ab'])
    # How many lessons and songs there are is piano-songs.js's to say (its own
    # test pins the numbers): here the page is checked against it.
    global LESSONS, SONGS, XMAS
    LESSONS, SONGS, XMAS = await page.js('[PN_SONGS.ORDER.length, PN_SONGS.SONGS.length, PN_SONGS.SONGS.filter(s => s.xmas).length]')
    check('home: there are lessons and songs to show', [LESSONS >= 49, SONGS >= 8, XMAS >= 6], [True, True, True])
    nodes = await page.js("[...document.querySelectorAll('.pn-node')].map(b => [b.dataset.id, b.dataset.state, b.disabled])")
    check('home: every lesson, the first one waiting, the rest locked',
          [len(nodes), nodes[0], sum(1 for n in nodes if n[1] == 'locked' and n[2])], [LESSONS, ['u1-cde', 'current', False], LESSONS - 1])
    check('home: no days, no points, no stars yet',
          await page.js("['streak', 'goal', 'stars'].map(k => document.getElementById('pn-stat-' + k).textContent)"), ['0', '0/40', '0'])
    check('home: a locked lesson does not start', [await page.click('.pn-node[data-id="u1-fg"]'), (await page.state())['view']], [None, 'home'])
    await page.shot('home.png')
    await page.click('#pn-tab-songs')
    check('home: the songs, and a card for an own one',
          await page.js("[document.getElementById('pn-songs').hidden, document.querySelectorAll('article.pn-song').length, document.querySelectorAll('.pn-song.is-xmas').length, !!document.querySelector('.pn-song-new')]"),
          [False, SONGS, XMAS, True])
    await page.shot('songs.png')
    await page.click('#pn-tab-badges')
    check('home: nineteen badges, none earned',
          await page.js("[document.querySelectorAll('.pn-badge').length, document.querySelectorAll('.pn-badge.is-got').length]"), [19, 0])
    await page.shot('badges.png')
    await page.click('#pn-tab-path')
    check('home: the site lists the page in its menu', await page.ev("[...document.querySelectorAll('#menu [aria-current], #menu a')].some(e => e.textContent.includes('Pianoskolan'))"), True)

    # The first lesson, with the mistakes a beginner makes.
    await start(page, 'u1-cde')
    g = await page.state()
    check('lesson: opens on a card that explains', [g['ex']['type'], g['prompt'], g['go'], g['run']['count']], ['info', 'Här bor C, D och E', 'Fortsätt', 12])
    check('lesson: the site\'s header and footer are out of the way',
          await page.js(f"[{SHOWN}('body > header'), {SHOWN}('body > footer'), {SHOWN}('.pn-top')]"), [False, False, False])
    check('lesson: the keys from C to C, the three it is about lit and named',
          await page.js("[document.querySelectorAll('.pn-white').length, document.querySelectorAll('.pn-black').length,"
                        " [...document.querySelectorAll('.pn-key.is-show')].map(k => k.querySelector('.pn-keyname').textContent).join('')]"), [8, 5, 'CDE'])
    await page.shot('lesson-info.png')
    await solve(page)
    g = await page.state()
    check('find: asks for C with its key lit', [g['ex']['type'], g['prompt'], g['ex']['hint'], await page.ev("document.querySelector('.pn-key.is-hint').dataset.midi")],
          ['find', 'Spela C', True, '60'])
    await page.ev('PN_SOUND.clearLog()')
    await page.click('.pn-key[data-midi="62"]')
    g = await page.state()
    check('find: a wrong key on the screen sounds, and is gently wrong',
          [g['feedback'], g['feedbackState'], g['last'], g['sounds']], ['Det var D. Leta lite till!', 'bad', {'midi': 62, 'source': 'screen', 'answer': 'wrong'}, ['note:62']])
    await page.click('.pn-key[data-midi="60"]')
    g = await page.state()
    check('find: the right key', [g['feedbackState'], g['feedback'].endswith('Det är C.'), g['go'], g['sounds'][-2:]], ['good', True, 'Fortsätt', ['note:60', 'right']])
    check('find: it goes on by itself', await next_exercise(page, 1), True)
    await solve(page)
    await solve(page)
    g = await page.state()
    check('find: then without the lit key, and without names that would give it away',
          [g['ex']['hint'], g['sub'], await page.ev("document.querySelector('.pn-key.is-hint')"), await page.ev("getComputedStyle(document.querySelector('.pn-white .pn-keyname')).visibility")],
          [False, 'Var sitter den?', None, 'hidden'])
    await page.shot('lesson-find.png')
    target = g['ex']['note']
    await page.ev(f'PN.test.hear({target + 1})')
    check('find: one wrong key gives no hint', await page.ev("document.querySelector('.pn-key.is-hint')"), None)
    await page.ev(f'PN.test.hear({target - 1})')
    check('find: the second one lights the key', await page.ev("document.querySelector('.pn-key.is-hint').dataset.midi"), str(target))
    await page.ev(f'PN.test.hear({target})')
    await page.click('#pn-go')
    await next_exercise(page, 4)
    g = await page.state()
    check('find: wrong keys cost one mark, however many', [g['run']['items'], g['run']['right']], [4, 2])
    await solve(page)
    await solve(page)
    g = await page.state()
    check('name: a key is lit and names are offered', [g['ex']['type'], g['ex']['from'], len(g['ex']['choices']), await page.ev("document.querySelectorAll('.pn-choice').length")], ['name', 'key', 3, 3])
    await page.shot('lesson-name.png')
    other = [c for c in g['ex']['choices'] if c != g['ex']['note']][0]
    await page.click(f'.pn-choice[data-midi="{other}"]')
    g2 = await page.state()
    check('name: a wrong name is crossed out', [g2['feedbackState'], await page.ev(f"document.querySelector('.pn-choice[data-midi=\"{other}\"]').disabled")], ['bad', True])
    await page.click(f'.pn-choice[data-midi="{g["ex"]["note"]}"]')
    check('name: the right name', (await page.state())['feedbackState'], 'good')
    await page.click('#pn-go')
    await next_exercise(page, 7)
    await solve(page)
    g = await page.state()
    check('echo: the page plays first', [g['ex']['type'], g['prompt'], g['sub']], ['echo', 'Lyssna och härma', 'Först spelar jag …'])
    await page.ev(f"PN.test.hear({g['ex']['midis'][0]})")
    check('echo: a key played meanwhile does not count', (await page.state())['staff'].count('is-right'), 0)
    await settle(page, 'PN.inspect().alt', 'Lyssna igen', tries=200, pause=0.05)
    g = await page.state()
    check('echo: then it is the pupil\'s turn, the first note marked', [g['sub'], g['staff'][0]], ['… och nu är det din tur!', 'is-now'])
    await page.ev(f"PN.test.hear({g['ex']['midis'][0]})")
    check('echo: a right note turns green and the next is marked', (await page.state())['staff'][:2], ['is-right', 'is-now'])
    await page.shot('lesson-echo.png')
    for m in g['ex']['midis'][1:]:
        await page.ev(f'PN.test.hear({m})')
    g = await page.state()
    check('echo: all of it right', [g['feedbackState'], g['feedback'].endswith('Alla toner rätt.')], ['good', True])
    await page.click('#pn-go')
    await next_exercise(page, 9)
    await solve(page, wrong=1)
    g = await page.state()
    check('play: the last exercise is a little tune from the staff, the next key lit',
          [g['ex']['type'], g['ex']['midis'], g['ex']['hint'], await page.ev("document.querySelector('.pn-key.is-hint').dataset.midi")], ['play', [60, 62, 64, 62, 60], True, '60'])
    check('play: letters under the notes in the first unit', await page.ev("[...document.querySelectorAll('.pn-letter')].map(t => t.textContent).join('')"), 'CDEDC')
    await page.shot('lesson-play.png')
    await solve(page)
    g = await page.state()
    check('finish: the lesson is over, with two stars for 80 % (16 of 20 right the first time)',
          [g['view'], g['finish']['stars'], g['finish']['xp'], round(g['finish']['accuracy'], 2), g['finish']['badges']], ['finish', 2, 25, 0.8, ['first', 'real']])
    check('finish: stored', [g['store']['lessons'], g['store']['xp'], g['store']['streak']['count'], g['next']], [{'u1-cde': {'stars': 2, 'times': 1}}, 25, 1, 'u1-fg'])
    check('finish: says so', await page.js("[document.querySelector('#pn-finish h2').textContent, document.querySelectorAll('#pn-finish .pn-star.is-on').length,"
                                          " [...document.querySelectorAll('#pn-finish .pn-tile-big')].map(e => e.textContent), document.getElementById('pn-next').textContent]"),
          ['Bra jobbat!', 2, ['+25', '80 %', '1'], 'Nästa lektion'])
    await page.shot('finish.png')
    await page.click('#pn-next')
    await settle(page, 'PN.inspect().view', 'lesson')
    g = await page.state()
    check('finish: on to the next lesson', [g['run']['id'], g['ex']['type']], ['u1-fg', 'info'])
    await solve(page)

    # Leaving in the middle.
    await page.click('[data-on-click="pn:quit"]')
    check('quit: asks first', await page.js("[document.getElementById('pn-ask').open, document.getElementById('pn-ask-title').textContent]"), [True, 'Avsluta?'])
    await page.click('#pn-ask-no')
    check('quit: staying stays', [(await page.state())['view'], await page.ev("document.getElementById('pn-ask').open")], ['lesson', False])
    await page.click('[data-on-click="pn:quit"]')
    await page.click('#pn-ask-yes')
    g = await page.state()
    check('quit: leaving leaves, and the half lesson is not counted', [g['view'], list(g['store']['lessons'])], ['home', ['u1-cde']])
    nodes = await page.js("[...document.querySelectorAll('.pn-node')].slice(0, 3).map(b => [b.dataset.state, b.querySelectorAll('.pn-star.is-on').length])")
    check('home: the first lesson done with its stars, the second waiting', nodes, [['done', 2], ['current', 0], ['locked', 0]])
    check('home: a day in a row, 25 of 40 points, two stars',
          await page.js("['streak', 'goal', 'stars'].map(k => document.getElementById('pn-stat-' + k).textContent)"), ['1', '25/40', '2'])

    # The computer's keyboard.
    await start(page, 'u1-cde')
    await solve(page)
    await page.key('s', 'KeyS', 83)
    g = await page.state()
    check('keys: S on the keyboard is D', g['last'], {'midi': 62, 'source': 'keys', 'answer': 'wrong'})
    await page.key('a', 'KeyA', 65)
    check('keys: A is C', (await page.state())['last'], {'midi': 60, 'source': 'keys', 'answer': 'right'})
    await page.key('Enter', 'Enter', 13)
    check('keys: Enter goes on', await next_exercise(page, 1), True)
    await page.key('x', 'KeyX', 88)
    check('keys: a key that is no piano key does nothing', (await page.state())['last'], {'midi': 60, 'source': 'keys', 'answer': 'right'})
    check('main: no errors', page.errors + page.console, [])


async def tempo_suite(page):
    await page.load(store=OPEN)
    await page.ev('PN.test.hurry(3)')
    g = await walk(page, 'u1-hand', lambda ex: ex['type'] == 'tempo')
    check('tempo: waits for Starta', [g['prompt'], g['go'], g['alt'], g['tempo']['state'], g['tempo']['bpm']], ['Spela i takt', 'Starta', 'Lyssna', 'ready', 228])
    check('tempo: finger numbers over the notes', await page.ev("[...document.querySelectorAll('.pn-finger')].map(t => t.textContent).join('')"), '123454321')
    await page.click('#pn-go')
    g = await page.state()
    check('tempo: a bar is counted in', [g['tempo']['state'], g['tempo']['lead'], g['go'], g['alt']], ['running', 4, None, 'Börja om'])
    count = await settle(page, "document.querySelector('.pn-count').textContent !== ''", True, tries=40, pause=0.03)
    check('tempo: the count shows', count, True)
    await page.ev(PLAY_IN_TIME % ('[3]', '{"5": 420}'))
    await settle(page, 'PN.inspect().tempo.state', 'done', tries=300, pause=0.05)
    g = await page.state()
    check('tempo: seven of nine - one left out, one far too late', [g['feedback'], g['staff'][3], g['staff'][5], g['staff'].count('is-right')],
          ['7 av 9 toner i takt.', 'is-missed', 'is-missed', 7])
    check('tempo: again, or on', [g['go'], g['alt']], ['Fortsätt', 'En gång till'])
    await page.shot('tempo-done.png')
    await page.click('#pn-alt')
    await page.ev(PLAY_IN_TIME % ('[]', '{}'))
    await settle(page, 'PN.inspect().tempo.state', 'done', tries=300, pause=0.05)
    g = await page.state()
    check('tempo: the second time all nine', [g['feedback'].endswith('9 av 9 toner i takt.'), g['tempo']['best']['hits']], [True, 9])
    await page.click('#pn-go')
    await settle(page, 'PN.inspect().view', 'finish')
    g = await page.state()
    check('tempo: the best try is the one that counts', [g['finish']['stars'], g['finish']['accuracy']], [3, 1])

    # A concert: its stars are the stars of how the song went in time.
    await page.ev('PN.test.reload()')
    g = await walk(page, 'u2-bj5', lambda ex: ex['type'] == 'tempo')
    check('concert: the whole of Bjällerklang at its own tempo', [len(g['ex']['midis']), g['ex']['grade'], g['ex']['bpm']], [51, True, 104])
    await page.click('#pn-go')
    await page.ev(PLAY_IN_TIME % ('[4, 9, 14, 19, 24, 29, 34, 39, 44, 49]', '{}'))
    await settle(page, 'PN.inspect().tempo.state', 'done', tries=600, pause=0.05)
    await page.click('#pn-go')
    await settle(page, 'PN.inspect().view', 'finish')
    g = await page.state()
    check('concert: 41 of 51 is two stars, and the badges of a first Christmas concert',
          [g['finish']['stars'], round(g['finish']['accuracy'], 3), [b for b in g['finish']['badges'] if b in ('concert', 'xmas1', 'perfect')]], [2, 0.804, ['concert', 'xmas1']])
    await page.shot('concert-finish.png')
    check('tempo: no errors', page.errors + page.console, [])


async def days_suite(page):
    await page.load(store=OPEN)
    for day, want in (('2026-12-01', 1), ('2026-12-02', 2), ('2026-12-03', 3), ('2026-12-05', 1)):
        await page.ev(f"PN.test.today('{day}'); PN.test.reload()")
        g = await walk(page, 'u1-cde')
        check(f'days: {day} makes {want} in a row', [g['view'], g['finish']['streak']], ['finish', want])
    g = await page.state()
    check('days: the badge for three days was earned on the third', 'streak3' in g['store']['badges'], True)
    await page.ev("PN.test.today('2026-12-07'); PN.test.reload()")
    check('days: two days later the count shows as none', await page.ev("document.getElementById('pn-stat-streak').textContent"), '0')
    await page.click('#pn-tab-badges')
    check('days: the numbers under Märken', await page.js("[...document.querySelectorAll('#pn-badges .pn-tile-big')].map(e => e.textContent)"), ['Nivå 2', '0', '72'])
    check('days: the week shows the day that was played', await page.js("[...document.querySelectorAll('.pn-day')].map(d => d.className.replace('pn-day', '').trim())"),
          ['is-some', 'is-some', 'is-some', '', 'is-some', '', 'is-today'])
    check('days: no errors', page.errors + page.console, [])


async def settings_suite(page):
    await page.load(store=OPEN)
    check('settings: Swedish names to begin with', await page.ev("document.querySelector('.pn-node[data-id=\"u4-hc\"] .pn-node-title').textContent"), 'H och höga C')
    await page.click('[data-on-click="pn:settings"]')
    check('settings: the dialog shows what is set',
          await page.js("(d => [d.open, d.querySelector('input[name=names]:checked').value, d.querySelector('select[name=letters]').value, d.querySelector('select[name=goal]').value, d.querySelector('input[name=sound]').checked])(document.getElementById('pn-settings'))"),
          [True, 'h', 'auto', '40', True])
    await page.shot('settings.png')
    await page.click('#pn-settings input[name="names"][value="b"]')
    await page.ev("(s => { s.value = 'never'; s.dispatchEvent(new Event('change', { bubbles: true })); })(document.querySelector('#pn-settings select[name=letters]'))")
    await page.ev("(s => { s.value = '20'; s.dispatchEvent(new Event('change', { bubbles: true })); })(document.querySelector('#pn-settings select[name=goal]'))")
    await page.click('#pn-settings input[name="sound"]')
    await page.click('#pn-settings .pn-btn-go')
    check('settings: B for H at once, and the goal',
          await page.js("[document.querySelector('.pn-node[data-id=\"u4-hc\"] .pn-node-title').textContent, document.getElementById('pn-stat-goal').textContent]"), ['B och höga C', '0/20'])
    await page.reload()
    g = await page.state()
    check('settings: kept over a reload', [g['store']['settings'][k] for k in ('names', 'letters', 'goal', 'sound')], ['b', 'never', 20, False])
    g = await walk(page, 'u1-hand', lambda ex: ex['type'] == 'play')
    check('settings: no letters under the notes when never',
          await page.js("[document.querySelectorAll('.pn-letter').length, document.querySelector('.pn-key[data-midi=\"71\"] .pn-keyname').textContent]"), [0, 'B'])
    await page.ev('PN_SOUND.clearLog()')
    await page.click('.pn-key[data-midi="60"]')
    check('settings: with the sound off the page makes none', await page.ev('PN_SOUND.isOn()'), False)
    check('settings: ... and the key still counts', (await page.state())['last']['answer'], 'right')
    await page.ev('PN.test.reload()')
    await page.click('[data-on-click="pn:settings"]')
    await page.click('#pn-settings input[name="openAll"]')
    check('settings: lessons lock again, one at a time', await page.ev("document.querySelectorAll('.pn-node:disabled').length"), LESSONS - 1)
    await page.click('[data-on-click="pn:reset"]')
    check('settings: starting over asks first', await page.js("[document.getElementById('pn-ask').open, document.getElementById('pn-ask-yes').textContent]"), [True, 'Börja om'])
    await page.click('#pn-ask-no')

    # An own song.
    await page.click('#pn-settings input[name="names"][value="h"]')
    await page.click('#pn-settings .pn-btn-go')
    await page.click('#pn-tab-songs')
    await page.click('.pn-song-new')
    check('own: the editor opens, nothing to save yet and nothing to delete',
          await page.js(f"[document.getElementById('pn-own').open, document.getElementById('pn-own-save').disabled, {SHOWN}('#pn-own-delete')]"), [True, True, False])
    await page.ev("(e => { e.value = 'Min låt'; e.dispatchEvent(new Event('input', { bubbles: true })); })(document.getElementById('pn-own-name'))")
    await page.ev("(e => { e.value = 'c d e2 | h b a2 | zz'; e.dispatchEvent(new Event('input', { bubbles: true })); })(document.getElementById('pn-own-text'))")
    check('own: what is not a note is pointed out', await page.js("[document.getElementById('pn-own-msg').textContent, document.getElementById('pn-own-save').disabled]"), ['Förstår inte: zz', True])
    await page.ev("(e => { e.value = 'c d e2 | h b a2'; e.dispatchEvent(new Event('input', { bubbles: true })); })(document.getElementById('pn-own-text'))")
    check('own: the melody is counted and drawn',
          await page.js("[document.getElementById('pn-own-msg').textContent, document.querySelectorAll('#pn-own-staff .pn-n').length, document.getElementById('pn-own-save').disabled]"),
          ['6 toner, 2 takter.', 6, False])
    await page.shot('own.png')
    await page.click('#pn-own-save')
    g = await page.state()
    check('own: saved, with its badge', [g['store']['own'], 'own' in g['store']['badges'], await page.ev("document.querySelectorAll('article.pn-song').length")], [1, True, SONGS + 1])
    own = await page.ev("document.querySelector('article.pn-song:last-of-type').dataset.song")
    await page.click(f'article[data-song="{own}"] [data-mode="play"]')
    await settle(page, 'PN.inspect().view', 'lesson')
    g = await page.state()
    check('own: it plays - in Swedish a bare B is the black key', [g['run']['kind'], g['ex']['type'], g['ex']['midis']], ['song', 'play', [60, 62, 64, 71, 70, 69]])
    await solve(page)
    g = await page.state()
    check('own: a song from the list gives points too', [g['view'], g['finish']['kind'], g['finish']['xp'], g['store']['songs'][own]['stars']], ['finish', 'song', 10, 3])
    await page.click('#pn-next')
    check('own: back to the songs', [(await page.state())['tab'], await page.ev("document.getElementById('pn-songs').hidden")], ['songs', False])
    await page.click(f'article[data-song="{own}"] [data-on-click="pn:own"]')
    check('own: opened again, it reads as it was typed', await page.ev("document.getElementById('pn-own-text').value"), 'C D E2 | H B A2')
    await page.click('#pn-own-delete')
    await page.click('#pn-ask-yes')
    g = await page.state()
    check('own: deleted', [g['store']['own'], await page.ev("document.querySelectorAll('article.pn-song').length"), await page.ev("document.getElementById('pn-own').open")], [0, SONGS, False])

    # A song in time, from the list.
    await page.ev('PN.test.hurry(4)')
    await page.click('article[data-song="blinka"] [data-mode="tempo"]')
    await settle(page, 'PN.inspect().view', 'lesson')
    g = await page.state()
    check('songs: Blinka lilla stjärna in time, at the list\'s tempo', [g['ex']['type'], g['ex']['bpm'], len(g['ex']['midis'])], ['tempo', 77, 42])
    await solve(page)
    g = await page.state()
    check('songs: its stars are kept with the song', [g['finish']['kind'], g['store']['songs']['blinka']['stars']], ['song', 3])
    check('settings: no errors', page.errors + page.console, [])


# getUserMedia answers with a MediaStream of silence from an AudioContext of
# its own (or refuses, as a visitor who says no), and remembers what it was
# asked for.
MIC_STUB = """(() => {
  window.__gum = [];
  window.__refuse = false;
  const AC0 = window.AudioContext;
  navigator.mediaDevices.getUserMedia = async constraints => {
    if (window.__refuse) throw new DOMException('no', 'NotAllowedError');
    const ctx = new AC0({ sampleRate: 48000 });
    const dest = ctx.createMediaStreamDestination();
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    g.gain.value = 0;
    osc.connect(g).connect(dest);
    osc.start();
    await ctx.resume();
    window.__gum.push({ constraints, track: dest.stream.getAudioTracks()[0] });
    return dest.stream;
  };
  return true;
})()"""

# Bjällerklang's first four bars as a piano plays them, in place of the microphone.
MELODY = """(async () => {
  const beats = [1, 1, 2, 1, 1, 2, 1, 1, 1.5, 0.5, 4];
  const sig = PN_SYNTH.melody(PN.inspect().ex.midis.map((m, i) => [m, beats[i]]), Object.assign({ bpm: 104, lead: 0.6, sr: 48000 }, %s));
  return await PN.test.play(sig.x, 48000);
})()"""


async def mic_suite(page):
    await page.load(store=OPEN)
    g = await walk(page, 'u2-bj1', lambda ex: ex['type'] == 'play')
    check('microphone: the exercise is the beginning of Bjällerklang', g['ex']['midis'], [64, 64, 64, 64, 64, 64, 64, 67, 60, 62, 64])
    check('microphone: the sound runs', await page.ev(MELODY % '{}'), 'running')
    ok = await next_exercise(page, g['run']['i'], tries=300)
    g2 = await page.state()
    check('microphone: a piano playing it is heard, every note, and the page moves on',
          [ok, g2['run']['i'], g2['run']['right'] - g['run']['right'], g2['run']['real'], g2['last']['source']], [True, g['run']['i'] + 1, 11, True, 'mic'])
    await page.shot('mic-after.png')
    # The same on a piano a third of a semitone flat, through a phone.
    await page.ev('PN.test.stopMic()')
    await asyncio.sleep(0.3)
    check('microphone: the next exercise is the same notes', g2['ex']['midis'], g['ex']['midis'])
    await page.ev(MELODY % '{ cents: -30, hp: 220, noise: 0.003 }')
    ok = await next_exercise(page, g2['run']['i'], tries=300)
    g3 = await page.state()
    check('microphone: a flat piano through a phone is followed too', [ok, g3['run']['right'] - g2['run']['right'], g3['mic']['tune'] < -8], [True, 11, True])
    await page.ev('PN.test.stopMic()')
    check('microphone: how the piano is tuned is kept for next time', (await page.state())['store']['tune'] < -8, True)

    # The button, the permission, and leaving the page.
    await page.load(width=390, height=664, mobile=True, store=OPEN)
    await page.ev(MIC_STUB)
    check('microphone: off to begin with', await page.js("[PN.inspect().mic.on, document.getElementById('pn-mic').getAttribute('aria-pressed'), document.querySelector('#pn-mic .pn-miclabel').textContent]"),
          [False, 'false', 'Lyssna på pianot'])
    await page.click('#pn-mic')
    ok = await settle(page, 'PN.inspect().mic.on', True, tries=50)
    check('microphone: the button opens it', ok, True)
    check('microphone: asked for without echo cancelling, noise suppression or gain control',
          await page.js('window.__gum[0].constraints'), {'audio': {'echoCancellation': False, 'noiseSuppression': False, 'autoGainControl': False}})
    check('microphone: the button says it listens, and it is remembered',
          await page.js("[document.getElementById('pn-mic').getAttribute('aria-pressed'), document.querySelector('#pn-mic .pn-miclabel').textContent, PN.inspect().store.settings.mic]"), ['true', 'Lyssnar', True])
    await page.shot('mic-on-phone.png')
    await start(page, 'u1-cde')
    await solve(page)
    await page.click('.pn-key[data-midi="60"]')
    g = await page.state()
    check('microphone: a key pressed on the screen counts once, though the microphone is on', [g['run']['items'], g['run']['right'], g['last']['source']], [1, 1, 'screen'])
    await page.ev("Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange'))")
    check('microphone: page hidden, it closes and the track is stopped', [(await page.state())['mic']['on'], await page.ev('window.__gum[0].track.readyState')], [False, 'ended'])
    await page.ev("Object.defineProperty(document, 'hidden', { configurable: true, get: () => false }); document.dispatchEvent(new Event('visibilitychange'))")
    ok = await settle(page, 'PN.inspect().mic.on', True, tries=50)
    check('microphone: shown again, it opens again by itself', [ok, await page.ev('window.__gum.length')], [True, 2])
    await page.click('#pn-mic2')
    g = await page.state()
    check('microphone: the button in the lesson closes it, and that is remembered too',
          [g['mic']['on'], g['store']['settings']['mic'], await page.ev('window.__gum[1].track.readyState')], [False, False, 'ended'])
    await page.ev('window.__refuse = true')
    await page.click('#pn-mic2')
    await settle(page, 'PN.inspect().mic.error !== null', True, tries=30)
    g = await page.state()
    check('microphone: refused, the page says what to do and goes on without',
          [g['mic']['on'], g['mic']['error'], await page.ev("document.getElementById('pn-toast').hidden"), g['view']],
          [False, 'Sidan fick inte använda mikrofonen. Tillåt mikrofonen för den här sidan i webbläsarens inställningar och tryck igen.', False, 'lesson'])
    check('microphone: no errors', page.errors + page.console, [])


# What of the site's chrome is on screen, and whether the lesson fits it.
FIT = """(() => {
  const shown = s => { const e = document.querySelector(s); return !!e && e.checkVisibility(); };
  const inside = s => { const e = document.querySelector(s); if (!e || !e.checkVisibility()) return null; const b = e.getBoundingClientRect();
    return b.top >= -0.5 && b.left >= -0.5 && b.bottom <= innerHeight + 0.5 && b.right <= innerWidth + 0.5 && b.height > 20; };
  return { header: shown('body > header'), footer: shown('body > footer'), brand: shown('.pn-brand'), theme: shown('.pn-top-end .theme-toggle'),
    wide: document.documentElement.scrollWidth > innerWidth, bar: inside('.pn-lbar .pn-iconbtn') && inside('.pn-lbar .pn-micbtn'), prompt: inside('.pn-prompt'), staff: inside('#pn-staff'),
    card: inside('#pn-card'), keys: inside('#pn-keys'), foot: inside('#pn-foot'),
    staffH: (e => (e ? Math.round(e.getBoundingClientRect().height) : 0))(document.querySelector('.pn-staff')),
    // How large the notes are: from one line of the staff to the next, and the letters under them.
    gap: (l => (l.length === 2 ? Math.round((l[1] - l[0]) * 10) / 10 : 0))([...document.querySelectorAll('.pn-staff > .pn-staffline')].slice(0, 2).map(e => e.getBoundingClientRect().top)),
    letter: (e => (e ? Math.round(e.getBoundingClientRect().height) : 0))(document.querySelector('.pn-letter')),
    centred: (e => { if (!e) return null; const s = e.getBoundingClientRect(), b = e.parentElement.getBoundingClientRect();
      return s.width > b.width || Math.abs((s.left + s.right) - (b.left + b.right)) < 6; })(document.querySelector('.pn-staff')),
    key: Math.round(document.querySelector('.pn-white') ? document.querySelector('.pn-white').getBoundingClientRect().width : 0) };
})()"""


async def phones_suite(page):
    # An iPhone with a notch gives a page the screen less the notch on both
    # sides: 734 of an iPhone 16's 852 points, and 340 of its 393 under
    # Safari's bar.
    for name, w, h in (('iPhone', 390, 664), ('iPhone SE', 375, 548), ('small Android', 360, 560), ('iPhone 16 on its side', 734, 340),
                       ('iPhone 13 on its side', 844, 340), ('SE on its side', 667, 325), ('iPad', 820, 1050)):
        phone = name != 'iPad'
        side = 'on its side' in name
        await page.load(width=w, height=h, mobile=True, store=OPEN, theme='dark' if name == 'iPhone' else 'light')
        f = await page.js(FIT)
        check(f'{name}: home without the site\'s header and footer, with its own mark and theme switch',
              [f['header'], f['footer'], f['brand'], f['theme'], f['wide']], [not phone, not phone, phone, phone, False])
        check(f'{name}: every field is 16px, so that a tap does not zoom',
              await page.ev("[...document.querySelectorAll('select, input[type=text], textarea')].every(e => parseFloat(getComputedStyle(e).fontSize) >= 16)"), True)
        if name == 'iPhone':
            await page.shot('phone-home.png')
        g = await walk(page, 'u2-bj2', lambda ex: ex['type'] == 'play')
        f = await page.js(FIT)
        check(f'{name}: a melody fits the screen - bar, prompt, notes, keys and foot',
              [f['bar'], f['prompt'], f['staff'], f['keys'], f['foot'], f['wide']], [True, True, True, True, True, False])
        # Read from a music stand: a staff's lines at least 13 px apart, 16 on a
        # phone on its side (they were 8 there, and a child could not read
        # them: the user's daughter, 2026-11-19), the letters as tall as text.
        check(f'{name}: the notes are large enough to read from the piano (lines {f["gap"]}px apart, letters {f["letter"]}px) and the keys to see ({f["key"]}px)',
              [f['gap'] >= (16 if side else 13), f['letter'] >= 16, f['key'] >= 38], [True, True, True])
        if name in ('iPhone', 'iPhone 16 on its side'):
            await page.shot(f'phone-play-{w}.png')
        if side:
            await page.ev('PN.test.hear(60)')
            over = await page.js("(r => [document.getElementById('pn-feedback').textContent, r('#pn-feedback').top >= 0, r('#pn-feedback').bottom <= r('#pn-staff').top + 1, r('#pn-feedback').right <= innerWidth])(s => document.querySelector(s).getBoundingClientRect())")
            check(f'{name}: what the page says back lies over the top row, off the notes', over, ['Det var C. Prova igen!', True, True, True])
            check(f'{name}: the keys and the buttons share the bottom row',
                  await page.js("(r => [Math.abs(r('#pn-keys').top - r('#pn-foot').top) < 1, r('#pn-keys').right <= r('#pn-foot').left, r('#pn-alt').bottom <= innerHeight])(s => document.querySelector(s).getBoundingClientRect())"), [True, True, True])
        await page.tap('.pn-key[data-midi="65"]')
        g2 = await page.state()
        check(f'{name}: a finger on a key plays it', [g2['last'], g2['staff'][0]], [{'midi': 65, 'source': 'screen', 'answer': 'right'}, 'is-right'])
        await page.ev('PN.test.reload()')
        await walk(page, 'u3-r1', lambda ex: ex['type'] == 'name')
        f = await page.js(FIT)
        check(f'{name}: a question with its choices fits too, the note in the middle of its box', [f['card'], f['staff'], f['keys'], f['foot'], f['wide'], f['centred']], [True, True, True, True, False, True])
        if side:
            check(f'{name}: the choices stand beside the note, not over it',
                  await page.js("(r => r('#pn-card').right <= r('#pn-staff').left && Math.abs(r('#pn-card').top - r('#pn-staff').top) < 1)(s => document.querySelector(s).getBoundingClientRect())"), True)
        if name == 'iPhone 16 on its side':
            await page.shot('phone-name-734.png')
        if name == 'iPhone SE':
            await page.shot('phone-name-se.png')
    await page.load(width=1280, height=800, theme='dark', store=OPEN)
    await walk(page, 'u8-lu5', lambda ex: ex['type'] == 'play')
    check('dark: the notes are light on dark paper',
          await page.js("[getComputedStyle(document.querySelector('.pn-head')).fill, getComputedStyle(document.getElementById('pn-staff')).backgroundColor]"),
          ['rgb(228, 232, 236)', 'rgb(21, 26, 32)'])
    check('dark: the keys stay white and black',
          await page.js("[getComputedStyle(document.querySelector('.pn-white')).color, getComputedStyle(document.querySelector('.pn-black')).color]"), ['rgb(43, 50, 58)', 'rgb(238, 241, 244)'])
    check('staff: Sankta Lucia has its sharps, beams and dots', await page.js("[document.querySelectorAll('.pn-sharp').length, document.querySelectorAll('.pn-staff rect.pn-ink').length >= 8, document.querySelectorAll('.pn-staff circle.pn-ink').length >= 4]"),
          [2, True, True])
    await page.shot('dark-lucia.png')
    check('phones: no errors', page.errors + page.console, [])


async def main():
    bws, page, _ = await attach(CDP)
    await main_suite(page)
    await tempo_suite(page)
    await days_suite(page)
    await settings_suite(page)
    await mic_suite(page)
    await phones_suite(page)
    await bws.close()
    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('FAILED:\n  ' + '\n  '.join(failures))
        sys.exit(1)


asyncio.run(main())
