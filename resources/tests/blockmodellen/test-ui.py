#!/usr/bin/env python3
"""blockmodellen.html in a real browser.

Lessons are walked a step at a time with the mouse and the keyboard, as a
pupil would: words in the problem are tapped, blocks are given bits with
the + and - buttons, pieces are marked, numbers are put into the model by
tapping its places, and the working and the answer are typed. Mistakes are
made on purpose, to see what the page says back. Then the practice, the
cheat sheet, the settings, reading aloud (a stand-in for the browser's
voices), a phone upright and on its side, the dark theme and print.

Start a server on the repository root and headless Chrome, by default on
ports 8863 and 9363 (BM_HTTP_PORT and BM_CDP_PORT for others). Check the
ports first with lsof -nP -iTCP:<port> -sTCP:LISTEN, other sessions use
ports too:

    python3 resources/tests/serve.py 8863
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
      --headless=new --remote-debugging-port=9363 --no-first-run \\
      --user-data-dir=/tmp/bmtest --disable-gpu --mute-audio about:blank

    python3 resources/tests/blockmodellen/test-ui.py

With BM_SHOTS=<folder> it saves screenshots. Exit status is 0 when every
check passes.
"""
import asyncio
import atexit
import base64
import json
import os
import sys
import urllib.request

import websockets

HTTP = int(os.environ.get('BM_HTTP_PORT', '8863'))
CDP = int(os.environ.get('BM_CDP_PORT', '9363'))
ORIGIN = f'http://127.0.0.1:{HTTP}'
URL = f'{ORIGIN}/blockmodellen.html'
SHOTS = os.environ.get('BM_SHOTS')

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
                self.errors.append(' '.join(str(a.get('value', a.get('description', ''))) for a in r['params']['args'])[:300])
            if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                self.pending[r['id']].set_result(r)

    async def ev(self, expr):
        r = await self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:300]
        return res.get('result', {}).get('value')

    async def js(self, expr):
        v = await self.ev(f'JSON.stringify({expr})')
        if isinstance(v, str) and v.startswith('EXCEPTION'):
            raise RuntimeError(v)
        return json.loads(v) if v is not None else None

    async def state(self):
        return await self.js('BM.inspect()')

    async def click_xy(self, x, y):
        for kind in ('mousePressed', 'mouseReleased'):
            await self.call('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})

    async def click(self, selector, index=0):
        """A real click, with the mouse, at the middle of the element."""
        xy = await self.js(f"(e => {{ if (!e) return null; e.scrollIntoView({{ block: 'center' }}); const r = e.getBoundingClientRect();"
                           f" return [r.left + r.width / 2, r.top + r.height / 2]; }})(document.querySelectorAll({json.dumps(selector)})[{index}])")
        if xy is None:
            raise RuntimeError(f'nothing to click: {selector}')
        await asyncio.sleep(0.04)
        await self.click_xy(*xy)
        await asyncio.sleep(0.08)

    async def tap(self, selector):
        """A finger on a touch screen."""
        xy = await self.js(f"(e => {{ e.scrollIntoView({{ block: 'center' }}); const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})(document.querySelector({json.dumps(selector)}))")
        await self.call('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': xy[0], 'y': xy[1]}]})
        await self.call('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        await asyncio.sleep(0.1)

    async def type(self, text):
        for ch in str(text):
            await self.call('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': ch, 'text': ch})
            await self.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': ch})

    async def enter(self):
        for kind in ('keyDown', 'keyUp'):
            await self.call('Input.dispatchKeyEvent', {'type': kind, 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13})
        await asyncio.sleep(0.1)

    async def type_into(self, selector, text, enter=True):
        await self.click(selector)
        await self.ev(f"document.querySelector({json.dumps(selector)}).value = ''")
        await self.type(text)
        if enter:
            await self.enter()

    async def size(self, w, h, mobile=False):
        await self.call('Emulation.setDeviceMetricsOverride', {'width': w, 'height': h, 'deviceScaleFactor': 1, 'mobile': mobile})
        await self.call('Emulation.setTouchEmulationEnabled', {'enabled': mobile, 'maxTouchPoints': 5 if mobile else 0})

    async def load(self, width=1280, height=860, theme='light', mobile=False, store=None):
        """A fresh page; what it has stored as given (None: nothing)."""
        await self.size(width, height, mobile)
        await self.call('Page.navigate', {'url': f'{ORIGIN}/robots.txt'})
        await settle(self, 'document.readyState', 'complete')
        await self.ev(f"localStorage.clear(); localStorage.setItem('kvot-theme', {json.dumps(theme)});"
                      + (f"localStorage.setItem('blockmodellen.v1', {json.dumps(json.dumps(store))});" if store is not None else ''))
        await self.reload()

    async def reload(self):
        await self.ev('window.__old = true')
        await self.call('Page.navigate', {'url': URL})
        # typeof, not window.BM: a top-level const is not a property of window
        await settle(self, "!window.__old && typeof BM !== 'undefined' && document.querySelectorAll('.bm-node').length > 10", True)
        await asyncio.sleep(0.2)

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


def close_at_exit(port, target_id):
    def close():
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/json/close/{target_id}', timeout=5).read()
        except Exception:
            pass   # closed already
    atexit.register(close)


async def attach(port):
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version'))
    bws = await websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024)
    page = Page(bws)
    asyncio.create_task(page.pump())
    tid = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
    close_at_exit(port, tid)
    page.sid = (await page.call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
    for m in ('Runtime.enable', 'Page.enable', 'Network.enable'):
        await page.call(m)
    await page.call('Network.setCacheDisabled', {'cacheDisabled': True})
    return bws, page, tid


# ── Doing a step right, as a pupil would ─────────────────────────────────

async def go(page):
    await page.click('#bm-go')
    await asyncio.sleep(0.1)


async def do_step(page):
    """The step on screen done right. Returns its name, or None at the end."""
    st = await page.state()
    pl = st['play']
    if st['view'] != 'lesson':
        return None
    if not pl:
        sc = st['run']['screens'][st['run']['i']]
        if sc == 'order':
            for n in range(1, 9):
                await page.click(f'.bm-order-card[data-n="{n}"]')
        await go(page)
        return sc
    s = pl['step']
    demo = pl['mode'] == 'demo'
    if pl['answered']:
        await go(page)
    elif s == 'who' and not demo:
        for w in range(pl['who']):
            if w not in pl['found']:
                tk = next(t for t in pl['whoTokens'] if t['who'] == w)
                await page.click(f'#bm-text .bm-w[data-s="{tk["s"]}"][data-t="{tk["t"]}"]')
        await go(page)
    elif s == 'build' and not demo:
        sub = pl['build'][pl['sub']]
        if sub['do'] == 'shape':
            for k, want in sub['rows'].items():
                have = pl['shape'].get(k, {'bits': 1, 'x': 0})
                wb = want.get('n', want.get('bits'))
                wx = 0 if 'n' in want else want.get('x', 0)
                for kind, w_, h_ in (('bits', wb, have['bits']), ('x', wx, have['x'])):
                    for _ in range(abs(w_ - h_)):
                        await page.click(f'.bm-stepbtn[data-row="{k}"][data-kind="{kind}"][data-d="{1 if w_ > h_ else -1}"]')
        else:
            done, i = 0, 0
            while done < sub['count']:
                marked = await page.ev(f"document.querySelectorAll('.bm-model .bm-row[data-row=\"{sub['row']}\"] .bm-pc')[{i}].classList.contains('is-marked')")
                if not marked:
                    await page.click(f'.bm-model [data-piece="{sub["row"]}.{i}"]')
                    done += 1
                i += 1
        await go(page)   # Kolla
        await go(page)   # Nästa
    elif s == 'place' and not demo:
        f = pl['facts'][pl['fi']]
        await page.click(f'.bm-model [data-slot="{f["at"]}"]')
        st2 = await page.state()
        if st2['play']['fi'] >= len(pl['facts']):
            await go(page)
    elif s == 'ask' and not demo:
        await page.click(f'.bm-model [data-slot="{pl["ask"]}"]')
        await go(page)
    elif s == 'calc' and not demo:
        for i in range(pl['ci'], len(pl['calc'])):
            if not pl['calc'][i]['given']:
                await page.type_into(f'input[data-line="{i}"]', pl['calc'][i]['v'])
        await go(page)
    elif s in ('answer', 'solve') and not demo:
        await page.type_into('.bm-answer-input', pl['answer'])
        await go(page)
    elif s == 'choose':
        await page.click(f'.bm-choice[data-type="{pl["type"]}"]')
        await go(page)
    else:
        await go(page)
    return s


async def finish_run(page, limit=300):
    for _ in range(limit):
        if await do_step(page) is None:
            return True
    return False


async def until(page, pred, limit=60):
    """Steps done right until pred(state) holds."""
    for _ in range(limit):
        st = await page.state()
        if pred(st):
            return st
        await do_step(page)
    return await page.state()


async def overflow(page):
    return await page.ev('document.documentElement.scrollWidth > innerWidth || document.querySelector(".bm-content").scrollWidth > document.querySelector(".bm-content").clientWidth')


# ── The suites ───────────────────────────────────────────────────────────

async def home_suite(page):
    await page.load()
    check('home: no errors on load', page.errors, [])
    check('home: the title', await page.ev('document.title'), 'Blockmodellen — kvot ab')
    n_units = await page.ev('BM_PROBLEMS.UNITS.length')
    n_lessons = await page.ev('BM_PROBLEMS.LESSONS.length')
    check('home: a card for every chapter', await page.ev('document.querySelectorAll("#bm-path .bm-unit").length'), n_units)
    check('home: a button for every lesson', await page.ev('document.querySelectorAll("#bm-path .bm-node").length'), n_lessons)
    check('home: the first lesson beckons', await page.ev('document.querySelector(".bm-node[data-state=current]").getAttribute("data-id")'), 'start-1')
    check('home: a welcome before the first lesson', await page.ev('!!document.querySelector(".bm-welcome")'), True)
    check('home: nothing counted yet', await page.ev('[...document.querySelectorAll(".bm-stat b")].map(b => b.textContent).join()'), '0,0,0')
    check('home: the site\'s header on a desktop, and the full-window button', await page.ev(
        'getComputedStyle(document.querySelector("body > header")).display !== "none" && !!document.querySelector(".kvot-fullwin button")'), True)
    check('home: every chapter of a kind has its picture', await page.ev('[...document.querySelectorAll(".bm-unit")].filter(u => !["start", "mix"].includes(u.dataset.unit)).every(u => u.querySelectorAll(".bm-unit-pic svg .bm-pc").length > 0)'), True)
    await page.shot('home.png')
    await page.click('[data-tab="train"]')
    n_types = await page.ev('BM_PROBLEMS.TYPES.length')
    check('practice: a card for every kind, and the mixed one', await page.ev('[document.querySelectorAll(".bm-type").length, !!document.querySelector(".bm-mixcard")]'), [n_types, True])
    check('practice: the tab is selected and the others not', await page.ev('[...document.querySelectorAll("#bm-tabs [role=tab]")].map(b => b.getAttribute("aria-selected")).join()'), 'false,true,false')
    await page.click('[data-tab="sheet"]')
    await asyncio.sleep(0.3)
    check('cheat sheet: the eight steps', await page.ev('document.querySelectorAll(".bm-sheet-steps li").length'), 8)
    check('cheat sheet: every model drawn, at the width of its box', await page.ev(
        '[...document.querySelectorAll(".bm-sheet-model")].map(c => { const s = c.querySelector("svg"); return s.querySelectorAll(".bm-pc").length > 0 && Math.abs(s.getBoundingClientRect().width - s.parentElement.clientWidth) < 2; })'), [True] * n_types)
    check('cheat sheet: mistakes and words', await page.ev('[document.querySelectorAll(".bm-sheet-list li").length, document.querySelectorAll(".bm-sheet-words dt").length]'), [6, 6])
    await page.shot('sheet.png')
    # Print: the cheat sheet alone, on white.
    await page.call('Emulation.setEmulatedMedia', {'media': 'print'})
    check('print: the cheat sheet and nothing else', await page.ev(
        '[getComputedStyle(document.querySelector("#bm-sheet")).display !== "none", getComputedStyle(document.querySelector(".bm-top")).display, getComputedStyle(document.querySelector("body > header")).display, getComputedStyle(document.querySelector(".bm-tabs")).display]'),
        [True, 'none', 'none', 'none'])
    await page.call('Emulation.setEmulatedMedia', {'media': ''})
    await page.click('[data-tab="path"]')
    check('home: no errors on the tabs', page.errors, [])


async def lesson_suite(page):
    await page.load()
    await page.ev('BM.test.seed(11)')
    await page.click('[data-id="start-1"]')
    st = await page.state()
    check('Kom igång: cards, a worked example, a problem to finish', st['run']['screens'][:4] + st['run']['screens'][4:5], ['card', 'card', 'card', 'card', 'demo:jm-fler'])
    check('Kom igång: the site\'s chrome gone in a lesson', await page.ev('getComputedStyle(document.querySelector("body > header")).display'), 'none')
    check('a card: a picture of a model', await settle(page, 'document.querySelectorAll(".bm-card-svg .bm-pc").length > 0', True), True)
    for _ in range(4):
        await go(page)
    st = await page.state()
    check('the worked example: the page does the steps', [st['play']['mode'], st['play']['step'], st['go']], ['demo', 'read', 'Nästa steg'])
    await until(page, lambda s: s['play'] and s['play']['step'] == 'place')
    check('the worked example: the mascot says what is done', await page.ev('!document.querySelector(".bm-narr").hidden && document.querySelector(".bm-bubble").textContent.length > 20'), True)
    check('the worked example: steps 4 and 5 lit together', await page.ev('[...document.querySelectorAll(".bm-steps li.is-now")].map(li => li.dataset.n).join()'), '4,5')
    check('the worked example: no places to tap', await page.ev('document.querySelectorAll(".bm-model .bm-target").length'), 0)
    st = await until(page, lambda s: s['play'] and s['play']['mode'] == 'fill')
    check('finish the problem: the blocks are drawn from the start', [st['play']['step'], st['play']['built'], await page.ev('document.querySelectorAll(".bm-model .bm-pc").length > 0')], ['read', True, True])
    check('finish the problem: the model has the problem\'s names', await page.ev('[...document.querySelectorAll(".bm-model .bm-lab")].map(t => t.textContent).length > 0'), True)
    ok = await finish_run(page)
    st = await page.state()
    check('Kom igång: done with three stars', [ok, st['view'], st['finish']['stars']], [True, 'finish', 3])
    check('Kom igång: the first badge', 'first' in [b['id'] for b in st['finish']['badges']], True)
    await page.shot('finish.png')
    await page.click('[data-on-click="bm:home"]')
    check('home again: the lesson has its stars, the next one beckons', await page.ev(
        '[document.querySelector("[data-id=\'start-1\'] .bm-stars").getAttribute("aria-label"), document.querySelector(".bm-node[data-state=current]").dataset.id]'),
        ['3 av 3 stjärnor', 'start-2'])
    await page.reload()
    st = await page.state()
    check('kept after a reload', [st['store']['lessons'].get('start-1'), st['store']['solved'] >= 1], [{'stars': 3, 'times': 1}, True])

    # The eight steps, with one slip.
    await page.click('[data-id="start-2"]')
    await go(page)
    await page.click('.bm-order-card[data-n="2"]')
    st = await page.state()
    check('the eight steps: a step out of turn is not taken', [st['feedbackState'], await page.ev('document.querySelectorAll(".bm-order-card").length')], ['bad', 8])
    for n in range(1, 9):
        await page.click(f'.bm-order-card[data-n="{n}"]')
    check('the eight steps: all in their slots', await page.ev('document.querySelectorAll(".bm-order-slot.is-done").length'), 8)
    await go(page)
    st = await page.state()
    check('the eight steps: one slip, two stars, no badge', [st['finish']['stars'], 'steps' in st['store']['badges']], [2, False])
    await page.click('[data-on-click="bm:again"]')
    await finish_run(page)
    st = await page.state()
    check('the eight steps without a slip: the badge', [st['finish']['stars'], 'steps' in st['store']['badges']], [3, True])
    check('lessons: no errors', page.errors, [])


async def mistakes_suite(page):
    """A guided problem, with a mistake at every step."""
    await page.load()
    await page.ev('BM.test.seed(5)')
    await page.click('[data-id="jmf-2"]')
    await go(page)   # read
    st = await page.state()
    pl = st['play']
    check('Rita själv: step 2, every word can be tapped', [pl['step'], await page.ev('document.querySelectorAll("#bm-text .bm-w.is-tap").length > 5')], ['who', True])
    who_cells = {(t['s'], t['t']) for t in pl['whoTokens']}
    other = await page.js('[...document.querySelectorAll("#bm-text .bm-w")].map(e => [Number(e.dataset.s), Number(e.dataset.t), e.textContent])')
    miss = next(o for o in other if (o[0], o[1]) not in who_cells and len(o[2]) > 2)
    await page.click(f'#bm-text .bm-w[data-s="{miss[0]}"][data-t="{miss[1]}"]')
    st = await page.state()
    check('a word that is not who or what: said so', [st['feedbackState'], st['feedback'].startswith('Nja')], ['bad', True])
    for w in range(pl['who']):
        tk = next(t for t in pl['whoTokens'] if t['who'] == w)
        await page.click(f'#bm-text .bm-w[data-s="{tk["s"]}"][data-t="{tk["t"]}"]')
    st = await page.state()
    check('both found: a block each, coloured as their names', [len(st['play']['found']), await page.ev('document.querySelectorAll(".bm-model .bm-row").length'), await page.ev('document.querySelectorAll("#bm-text .bm-w.is-found").length >= 2')], [2, 2, True])
    await go(page)
    check('step 3: + and − for each block', await page.ev('document.querySelectorAll(".bm-shape").length'), 2)
    await go(page)   # Kolla, unchanged
    st = await page.state()
    check('blocks left as they were: not right', [st['feedbackState'], st['feedback'].startswith('Inte riktigt')], ['bad', True])
    await page.click('.bm-stepbtn[data-row="B"][data-kind="bits"][data-d="1"]')
    await go(page)
    st = await page.state()
    check('"more than" drawn as twice as many: told about the other bit', ['annan bit' in st['feedback'], await page.ev('document.querySelector(".bm-shape[data-row=B]").classList.contains("is-bad")')], [True, True])
    check('the drawing follows the buttons: three bits', await page.ev('document.querySelectorAll(".bm-model .bm-pc").length'), 3)
    await page.click('.bm-stepbtn[data-row="B"][data-kind="bits"][data-d="-1"]')
    await page.click('.bm-stepbtn[data-row="B"][data-kind="x"][data-d="1"]')
    await go(page)
    st = await page.state()
    check('right blocks: praised, and why', [st['feedbackState'], st['go']], ['good', 'Nästa'])
    await go(page)
    st = await page.state()
    pl = st['play']
    check('step 5: the model drawn to scale, with places to tap', [pl['step'], pl['built'], await page.ev('document.querySelectorAll(".bm-model .bm-target").length >= 3')], ['place', True, True])
    check('step 5: the sentence and the number lit', await page.ev('[!!document.querySelector(".bm-sent.is-cur"), document.querySelector(".bm-num.is-cur").textContent]'), [True, f"{pl['facts'][0]['v']}"])
    f = pl['facts'][0]
    wrong = next(sl for sl in pl['slots'] if sl != f['at'] and sl != 'A')
    await page.click(f'.bm-model [data-slot="{wrong}"]')
    st = await page.state()
    check('a number in the wrong place: said where that is', [st['feedbackState'], st['feedback'].startswith('Inte där')], ['bad', True])
    await page.click(f'.bm-model [data-slot="{wrong}"]')
    check('twice wrong: the right place lights up', await page.ev('!!document.querySelector(".bm-model .bm-hl")'), True)
    await page.click(f'.bm-model [data-slot="{f["at"]}"]')
    check('the right place: the number is in the model', await page.ev(f'[...document.querySelectorAll(".bm-model .bm-val")].some(t => t.textContent === "{f["v"]}")'), True)
    st = await until(page, lambda s: s['play']['step'] == 'ask')
    check('step 6: the question lit', await page.ev('document.querySelector(".bm-sent.is-cur").textContent.trim().endsWith("?")'), True)
    await page.click(f'.bm-model [data-slot="{st["play"]["ask"]}"]')
    check('the question mark in the model', await page.ev('!!document.querySelector(".bm-model .bm-q")'), True)
    await go(page)
    st = await page.state()
    line = st['play']['calc'][st['play']['ci']]
    await page.type_into(f'input[data-line="{st["play"]["ci"]}"]', line['v'] + 1)
    st = await page.state()
    check('a wrong sum: a hint', [st['feedbackState'], st['feedback'].startswith('Inte riktigt')], ['bad', True])
    await page.type_into(f'input[data-line="{st["play"]["ci"]}"]', line['v'] + 2)
    check('wrong again: the arithmetic shown', await page.ev('!!document.querySelector(".bm-cline.is-now .bm-cshow")'), True)
    await page.type_into(f'input[data-line="{st["play"]["ci"]}"]', line['v'])
    st = await until(page, lambda s: s['play']['step'] == 'answer')
    a = st['play']['answer']
    traps = await page.js('Object.keys(BM_PROBLEMS.make(BM.inspect().play.tid, BM.inspect().play.seed, null).answer.traps)')
    await page.type_into('.bm-answer-input', traps[0])
    st = await page.state()
    check('an answer that is a known mistake: told what it is', [st['feedbackState'], len(st['feedback']) > 25], ['bad', True])
    await page.type_into('.bm-answer-input', a)
    st = await page.state()
    check('the answer right: the question mark becomes the answer', [st['play']['answered'], await page.ev(f'document.querySelector(".bm-model .bm-ans").textContent')], [True, str(a)])
    check('and the check: is it reasonable', await page.ev('document.querySelector(".bm-check").textContent.startsWith("Kolla")'), True)
    st = await page.state()
    check('the slips are counted', sum(1 for it in st['run']['items'] if not it['first']) >= 5, True)
    await page.shot('mistakes.png')
    await finish_run(page)
    st = await page.state()
    check('the lesson with slips: fewer stars', st['finish']['stars'] < 3, True)
    check('mistakes: no errors', page.errors, [])


async def solve_suite(page):
    await page.load()
    await page.ev('BM.test.seed(8)')
    await page.click('[data-id="brak-3"]')
    st = await page.state()
    check('Lös uppgifter: the answer first, no steps shown, no model', [st['play']['step'], await page.ev('document.querySelector(".bm-steps").hidden'), await page.ev('document.querySelector(".bm-stage").hidden')], ['solve', True, True])
    check('Lös uppgifter: drawing is help', st['alt'], 'Rita modellen')
    await page.type_into('.bm-answer-input', st['play']['answer'] + 1)
    st = await page.state()
    check('a wrong answer: try again or draw', st['feedbackState'], 'bad')
    await page.click('#bm-alt')
    st = await page.state()
    check('Rita modellen: the steps from 2, the steps shown', [st['play']['step'], await page.ev('document.querySelector(".bm-steps").hidden')], ['who', False])
    st = await until(page, lambda s: s['play']['step'] == 'answer')
    await page.type_into('.bm-answer-input', st['play']['answer'])
    st = await page.state()
    check('drawn with help: solved, not right the first time', [st['play']['answered'], st['store']['types'].get('brak')], [True, {'tries': 1, 'right': 0}])
    await go(page)
    st = await page.state()
    await page.type_into('.bm-answer-input', st['play']['answer'])
    st = await page.state()
    check('right the first time: counted so', st['store']['types'].get('brak'), {'tries': 2, 'right': 1})
    check('right the first time: the model is shown as it would be drawn', [await page.ev('document.querySelector(".bm-stage").hidden'), await page.ev('document.querySelectorAll(".bm-model .bm-pc").length > 0'), await page.ev('!!document.querySelector(".bm-model .bm-ans")')], [False, True, True])
    await page.shot('solved.png')
    await go(page)
    # Three wrong: the answer is shown, and the problem goes on.
    st = await page.state()
    for k in (1, 2, 3):
        await page.type_into('.bm-answer-input', st['play']['answer'] + k)
    st = await page.state()
    check('three wrong: the answer and its model are shown', [st['play']['answered'], st['go'] in ('Nästa uppgift', 'Klar')], [True, True])
    await finish_run(page)
    st = await page.state()
    check('Lös uppgifter: done', [st['view'], st['finish']['items']], ['finish', 4])

    # Mixed: which model fits.
    await page.click('[data-on-click="bm:home"]')
    await page.click('[data-id="mix-1"]')
    await go(page)   # the card
    st = await page.state()
    check('Blandat: which model fits, four choices', [st['play']['step'], len(st['play']['choices'])], ['choose', 4])
    wrong = next(t for t in st['play']['choices'] if t != st['play']['type'])
    await page.click(f'.bm-choice[data-type="{wrong}"]')
    st = await page.state()
    check('a model that does not fit: said so, and greyed', [st['feedbackState'], await page.ev(f'document.querySelector(".bm-choice[data-type={wrong}]").disabled')], ['bad', True])
    await page.click(f'.bm-choice[data-type="{st["play"]["type"]}"]')
    st = await page.state()
    check('the model that fits: on to the answer', [st['feedbackState'], st['go']], ['good', 'Nästa'])
    await finish_run(page)
    st = await page.state()
    check('Blandat: done, and its badge', [st['view'], 'mixed' in st['store']['badges']], ['finish', True])

    # Practice from the practice tab.
    await page.click('[data-on-click="bm:home"]')
    await page.click('[data-tab="train"]')
    await page.click('.bm-type .bm-btn[data-type="ggr"]')
    st = await page.state()
    check('Träna: five problems of one kind', [st['run']['kind'], st['run']['count'], {s.split(':')[1][:2] for s in st['run']['screens']}], ['practice', 5, {'gg'}])
    await finish_run(page)
    st = await page.state()
    check('Träna: done, and counted for the kind', [await page.ev('document.querySelector(".bm-finish h2").textContent'), st['store']['types'].get('ggr', {}).get('tries')], ['Bra tränat!', 5])
    await page.click('[data-on-click="bm:home"]')
    check('Träna: the kind\'s card says how it went', await page.ev('[...document.querySelectorAll(".bm-type")].find(c => c.querySelector("[data-type=ggr]")).querySelector(".bm-type-stat").textContent'), '5 av 5 rätt direkt')
    check('solve: no errors', page.errors, [])


async def settings_suite(page):
    await page.load()
    await page.click('[data-on-click="bm:settings"]')
    await page.type_into('#bm-set-name', 'Lisa', enter=False)
    await page.click('input[name="bm-pron"][value="hon"]')
    st = await page.state()
    check('settings: the name and how to say it are kept', [st['store']['settings']['name'], st['store']['settings']['pron']], ['Lisa', 'hon'])
    await page.click('#bm-settings [data-on-click="bm:close"]')
    # The pupil turns up in the problems.
    texts = []
    for seed in range(1, 13):
        await page.ev(f'BM.test.seed({seed})')
        await page.click('[data-tab="train"]')
        await page.click('.bm-type .bm-btn[data-type="delhel"]')
        texts.append((await page.state())['play']['text'])
        await page.click('[data-on-click="bm:quit"]')
    mine = [t for t in texts if 'Lisa' in t]
    check('the pupil\'s name in some problems, not all', 0 < len(mine) < len(texts), True)
    check('and she is "hon" there', any(' hon ' in t for t in mine) and not any(' han ' in t or ' hen ' in t for t in mine), True)
    # Reading aloud, with a voice the tests hand the page.
    await page.ev("""window.__spoken = []; BM.test.speech({
        getVoices: () => [{ lang: 'en-US', name: 'Sam' }, { lang: 'sv-SE', name: 'Alva' }],
        speak: u => window.__spoken.push([u.text, u.lang]), cancel() {}, addEventListener() {} })""")
    await page.ev('BM.test.seed(4)')
    await page.click('[data-tab="path"]')
    await page.click('[data-id="brak-2"]')
    check('with a Swedish voice: the button to read aloud', await page.ev('!document.querySelector(".bm-speak").hidden'), True)
    await page.click('.bm-speak')
    spoken = await page.js('window.__spoken')
    check('read aloud in Swedish, the fractions in words', [len(spoken), spoken[0][1] if spoken else None, '/' not in (spoken[0][0] if spoken else '/')], [1, 'sv-SE', True])
    await page.click('[data-on-click="bm:quit"]')
    await page.click('[data-on-click="bm:settings"]')
    await page.click('#bm-set-speech')
    await page.click('#bm-settings [data-on-click="bm:close"]')
    await page.click('[data-id="brak-2"]')
    check('reading aloud switched off: no button', await page.ev('document.querySelector(".bm-speak").hidden'), True)
    await page.click('[data-on-click="bm:quit"]')
    await page.ev("BM.test.speech({ getVoices: () => [{ lang: 'en-US', name: 'Sam' }], speak() {}, cancel() {}, addEventListener() {} })")
    await page.click('[data-on-click="bm:settings"]')
    await page.click('#bm-set-speech')
    check('no Swedish voice: the settings say so', await page.ev('document.querySelector("#bm-speech-note").textContent.length > 10'), True)
    await page.click('#bm-settings [data-on-click="bm:close"]')
    # Help, badges, starting again.
    await page.click('[data-on-click="bm:help"]')
    check('help: opens, with the two sources', await page.ev('[document.querySelector("#bm-help").open, [...document.querySelectorAll("#bm-help a[href^=\'https://ncm.gu.se\']")].length]'), [True, 2])
    await page.click('#bm-help [data-on-click="bm:close"]')
    await page.click('#bm-stat-stars')
    check('badges: every badge listed', await page.ev('document.querySelectorAll("#bm-badge-body .bm-badge").length'), await page.ev('BM_GAME.BADGES.length'))
    await page.click('#bm-badges [data-on-click="bm:close"]')
    await page.ev('BM.test.seed(3)')
    await page.click('[data-id="start-2"]')
    await finish_run(page)
    await page.click('[data-on-click="bm:home"]')
    await page.click('[data-on-click="bm:settings"]')
    await page.click('[data-on-click="bm:reset"]')
    check('start again: asked first', await page.ev('document.querySelector("#bm-ask").open'), True)
    await page.click('#bm-ask-yes')
    st = await page.state()
    check('started again: no lessons, the name kept', [st['store']['lessons'], st['store']['settings']['name']], [{}, 'Lisa'])
    # Days in a row.
    await page.ev("BM.test.today('2026-11-24')")
    await page.click('[data-id="start-2"]')
    await finish_run(page)
    await page.click('[data-on-click="bm:home"]')
    await page.ev("BM.test.today('2026-11-25')")
    await page.click('[data-id="start-2"]')
    await finish_run(page)
    await page.click('[data-on-click="bm:home"]')
    check('two days running: two days in a row', await page.ev('document.querySelector("#bm-stat-streak b").textContent'), '2')
    await page.ev("BM.test.today('2026-11-28')")
    check('a gap: the count is over', await page.ev('document.querySelector("#bm-stat-streak b").textContent'), '0')
    await page.ev('BM.test.today(null)')
    check('settings: no errors', page.errors, [])


async def phone_suite(page):
    await page.load(390, 664, mobile=True)
    check('phone: no site header, the page\'s own bar', await page.ev('[getComputedStyle(document.querySelector("body > header")).display, getComputedStyle(document.querySelector(".bm-brand")).display]'), ['none', 'flex'])
    check('phone: nothing wider than the screen', await overflow(page), False)
    await page.shot('phone-home.png')
    await page.ev('BM.test.seed(6)')
    await page.tap('[data-id="brak-2"]')
    sizes, offs, foot = [], [], []
    for _ in range(60):
        st = await page.state()
        if st['view'] != 'lesson' or not st['play'] or st['run']['i'] > 0:
            break
        offs.append(await overflow(page))
        foot.append(await page.ev('(() => { const r = document.querySelector("#bm-foot").getBoundingClientRect(); return r.bottom <= innerHeight + 1 && r.top > innerHeight * 0.5; })()'))
        sizes.append(await page.ev('Math.min(16, ...[...document.querySelectorAll(".bm-input, .bm-field input")].map(i => parseFloat(getComputedStyle(i).fontSize)))'))
        if st['play']['step'] == 'build':
            check('phone: the + and − buttons are big enough for a finger', await page.ev('[...document.querySelectorAll(".bm-stepbtn")].every(b => b.getBoundingClientRect().width >= 40)'), True)
            await page.shot('phone-build.png')
        if st['play']['step'] == 'place':
            check('phone: the model fits the screen', await page.ev('document.querySelector(".bm-model").getBoundingClientRect().right <= innerWidth'), True)
            await page.shot('phone-place.png')
        if st['play']['step'] == 'calc':
            await page.shot('phone-calc.png')
        await do_step(page)
    check('phone: no step wider than the screen', any(offs), False)
    check('phone: the buttons always at the bottom of the screen', all(foot), True)
    check('phone: fields at 16 px, so iOS does not zoom', min(sizes) >= 16, True)
    await finish_run(page)
    check('phone: the end of a lesson, its buttons in sight', await page.ev('[...document.querySelectorAll(".bm-finish-btns button")].every(b => b.getBoundingClientRect().bottom <= innerHeight)'), True)
    await page.shot('phone-finish.png')
    # On its side: the problem beside its model.
    await page.load(844, 340, mobile=True)
    await page.ev('BM.test.seed(6)')
    await page.tap('[data-id="jmf-2"]')
    await until(page, lambda s: s['play'] and s['play']['step'] == 'place')
    check('phone on its side: the model beside the problem', await page.ev(
        '(() => { const t = document.querySelector(".bm-task").getBoundingClientRect(), s = document.querySelector(".bm-stage").getBoundingClientRect(); return s.left >= t.right - 1 && s.top < t.bottom; })()'), True)
    check('phone on its side: nothing wider than the screen', await overflow(page), False)
    await page.shot('phone-side.png')
    check('phone: no errors', page.errors, [])


async def key(page, k, code, vk):
    down = {'type': 'keyDown', 'key': k, 'code': code, 'windowsVirtualKeyCode': vk}
    if k in (' ', 'Enter'):
        down['text'] = ' ' if k == ' ' else '\r'
    await page.call('Input.dispatchKeyEvent', down)
    await page.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': k, 'code': code, 'windowsVirtualKeyCode': vk})
    await asyncio.sleep(0.12)


async def keys_suite(page):
    """The model with the keyboard: its places and pieces are buttons with names."""
    await page.load()
    await page.ev('BM.test.seed(12)')
    await page.click('[data-id="fore-2"]')
    await go(page)
    pl = (await page.state())['play']
    for w in range(pl['who']):
        tk = next(t for t in pl['whoTokens'] if t['who'] == w)
        await page.ev(f'document.querySelector(\'#bm-text .bm-w[data-s="{tk["s"]}"][data-t="{tk["t"]}"]\').focus()')
        await key(page, 'Enter', 'Enter', 13)
    st = await page.state()
    check('keys: a word found with Enter', len(st['play']['found']), pl['who'])
    check('before and after: a block before, and one after', 'ett block för före och ett för efter' in st['feedback'], True)
    await go(page)
    sub = (await page.state())['play']['build'][0]
    for k, want in sub['rows'].items():
        for _ in range(want.get('x', 0)):
            await page.ev(f'document.querySelector(\'.bm-stepbtn[data-row="{k}"][data-kind="x"][data-d="1"]\').focus()')
            await key(page, 'Enter', 'Enter', 13)
    check('keys: the focus stays on the button pressed', await page.ev('document.activeElement.classList.contains("bm-stepbtn")'), True)
    await go(page)
    st = await page.state()
    check('keys: the blocks drawn with the + buttons', st['feedbackState'], 'good')
    await go(page)
    st = await page.state()
    f = st['play']['facts'][0]
    names = await page.js('[...document.querySelectorAll(".bm-model [data-slot]")].map(e => [e.dataset.slot, e.getAttribute("aria-label"), e.getAttribute("role"), e.tabIndex])')
    check('keys: every place is a named button that takes the focus', all(n[1] and n[1] != n[0] and n[2] == 'button' and n[3] == 0 for n in names), True)
    await page.ev(f'document.querySelector(\'.bm-model [data-slot="{f["at"]}"]\').focus()')
    await key(page, 'Enter', 'Enter', 13)
    st = await page.state()
    check('keys: a number put in its place with Enter', st['play']['fi'], 1)
    check('keys: the focus kept in the model', await page.ev('!!document.activeElement.closest(".bm-model")'), True)
    # Marking with the space bar.
    await page.click('[data-on-click="bm:quit"]')
    await page.ev('BM.test.seed(2)')
    await page.click('[data-id="brak-2"]')
    st = await until(page, lambda s: s['play'] and s['play']['step'] == 'build' and s['play']['build'][s['play']['sub']]['do'] == 'mark')
    await page.ev('document.querySelector(\'.bm-model [data-piece="A.0"]\').focus()')
    await key(page, ' ', 'Space', 32)
    check('keys: a bit marked with the space bar, and said to be', await page.ev('document.querySelector(\'.bm-model [data-piece="A.0"]\').getAttribute("aria-pressed")'), 'true')
    check('keys: no errors', page.errors, [])


def lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


async def colour_suite(page):
    for theme in ('light', 'dark'):
        await page.load(1280, 860, theme=theme)
        await page.ev('BM.test.seed(9)')
        await page.click('[data-id="sumdiff-1"]')
        await until(page, lambda s: s['play'] and s['play']['mode'] == 'demo' and s['play']['step'] == 'calc')
        cols = await page.js("""(() => {
          const rgb = s => s.match(/[\\d.]+/g).slice(0, 3).map(Number);
          const val = document.querySelector('.bm-model .bm-val:not(.bm-q)');
          const q = document.querySelector('.bm-model .bm-q');
          const lab = document.querySelector('.bm-model .bm-lab');
          const bit = [...document.querySelectorAll('.bm-model .bm-pc.is-bit')].map(e => rgb(getComputedStyle(e).fill));
          const del = [...document.querySelectorAll('.bm-model .bm-pc.is-del')].map(e => rgb(getComputedStyle(e).fill));
          const paper = rgb(getComputedStyle(document.querySelector('.bm-stage')).backgroundColor);
          return { val: rgb(getComputedStyle(val).fill), q: q && rgb(getComputedStyle(q).fill), lab: rgb(getComputedStyle(lab).fill), bit, del, paper };
        })()""")
        worst = min(contrast(cols['val'], c) for c in cols['bit'] + cols['del'])
        check(f'{theme}: numbers in the blocks stand out from every block (4.5:1)', worst >= 4.5, True)
        check(f'{theme}: names on the paper (4.5:1)', contrast(cols['lab'], cols['paper']) >= 4.5, True)
        if cols['q']:
            check(f'{theme}: the question mark on the paper (3:1)', contrast(cols['q'], cols['paper']) >= 3, True)
        check(f'{theme}: the blocks show on the paper', min(contrast(c, cols['paper']) for c in cols['bit']) >= 1.05, True)
        await page.shot(f'colour-{theme}.png')
    check('colours: no errors', page.errors, [])


async def main():
    bws, page, tid = await attach(CDP)
    try:
        for suite in (home_suite, lesson_suite, mistakes_suite, keys_suite, solve_suite, settings_suite, phone_suite, colour_suite):
            print(f'\n── {suite.__name__}')
            await suite(page)
    finally:
        try:
            await page.call('Target.closeTarget', {'targetId': tid})
        except Exception:
            pass
        await bws.close()
    print(f'\n{checks - len(failures)} of {checks} checks passed.')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    asyncio.run(main())
