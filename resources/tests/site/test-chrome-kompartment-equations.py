"""Kompartment's equation boxes, in a block's settings window.

An equation is typed in a box that is one line at rest and opens, while it has
the keyboard, to show the whole equation: as wide as the text on one line, up
to the edge of the panel it is in, then wrapped and as tall as that takes. It
is drawn over the form, so nothing else moves. Home and End go to the start
and the end of the equation -- also as a Mac sends them, as commands to scroll
the page, which in a text field leave the caret where it was. Enter commits
the box once. See kompartment/src/ui/equationbox.js.

The equation is drawn in colour by a copy under the field, whose own text is
invisible: a block's name in its kind's colour, the library's functions in
theirs, and a name the check would refuse marked where it stands.

Checked with real mouse presses and key presses, on two bundled models:
  - at rest the box is a textarea one line high, exactly as tall as the
    <input> beside it;
  - its text is drawn by the copy, the field's own glyphs invisible over it,
    each part in the span for what it is (a parameter, an expression, a
    function), and the copy's characters are where the field has them;
  - a press puts the caret on the character pressed, in the line that was
    seen, also past where the open box wraps its first line; the release opens
    it, all of the equation in sight, and the line under it does not move;
  - a double-click on a word in a box at rest selects the word;
  - Home and End, plain, with Shift, and as a Mac sends them, go to the ends
    of the equation, and the window does not scroll;
  - typing a name opens the completion list, under the open box; Home closes
    it; Enter with the list open takes a row and commits nothing, and Enter
    with it closed commits once, with the box still open and the caret where
    it was; Tab out commits nothing more and the box is one line again;
  - a line break pasted in is a space; Down moves down a wrapped line, and at
    the end opens the list;
  - a name the model has not got is marked, and the copy of an open box is
    where the field is;
  - in a per-index grid, a value the row inherits is drawn muted; a box opens
    wider than its column, to the right and no further than the grid, and a
    long equation wraps at the grid's edge, the copy wrapping where the field
    does;
  - and that the page raised nothing.

Serve the repository and start headless Chrome (the recipe is in README.md),
by default on ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose
others. Exit status is 0 when every check passes.
"""
import asyncio, json, os, sys, urllib.request
import websockets

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))
PAGE = 'http://127.0.0.1:%d/kompartment/index.html?model=' % HTTP

ERRORS = """window.__errors = [];
addEventListener('error', e => window.__errors.push(String(e.message)));
addEventListener('unhandledrejection', e => window.__errors.push('rejected: ' + e.reason));"""

# The open window's first equation box, and what it and its box look like.
FIELD = "document.querySelector('dialog[open] .eq-field')"
STATE = """JSON.stringify((() => {
  const f = document.activeElement, pop = document.querySelector('.ac-pop');
  const box = f && f.parentElement, r = f ? f.getBoundingClientRect() : null;
  return { tag: f ? f.tagName : null, value: f ? f.value : null,
           sel: f ? [f.selectionStart, f.selectionEnd] : null,
           open: !!box && box.classList.contains('is-open'),
           height: r ? r.height : null, rest: box ? box.getBoundingClientRect().height : null,
           all: f ? f.scrollHeight <= f.clientHeight + 1 : null,
           list: !!pop && !pop.hidden, listTop: pop && !pop.hidden ? pop.getBoundingClientRect().top : null,
           bottom: r ? r.bottom : null,
           scroll: document.querySelector('dialog[open] .modal-body').scrollTop };
})())"""


async def main():
    version = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json/version' % CDP))
    async with websockets.connect(version['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as bws:
        counter = [0]

        async def cmd(method, params=None, session=None):
            counter[0] += 1
            mid = counter[0]
            message = {'id': mid, 'method': method, 'params': params or {}}
            if session:
                message['sessionId'] = session
            await bws.send(json.dumps(message))
            while True:
                reply = json.loads(await bws.recv())
                if reply.get('id') == mid:
                    return reply

        async def ev(expression):
            reply = await cmd('Runtime.evaluate',
                              {'expression': expression, 'awaitPromise': True,
                               'returnByValue': True, 'timeout': 30000}, session)
            result = reply.get('result', {})
            if 'exceptionDetails' in result:
                raise AssertionError('page threw: ' + json.dumps(result['exceptionDetails'])[:300])
            return result.get('result', {}).get('value')

        async def state():
            return json.loads(await ev(STATE))

        async def mouse(kind, x, y, buttons=0, clicks=1):
            await cmd('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left'
                      if kind != 'mouseMoved' else 'none', 'buttons': buttons, 'clickCount': clicks}, session)

        async def click(x, y, clicks=1):
            await mouse('mouseMoved', x, y)
            await mouse('mousePressed', x, y, 1, clicks)
            await mouse('mouseReleased', x, y, 0, clicks)
            await asyncio.sleep(0.15)

        async def center(expression):
            return await ev("""(() => { const e = %s; if (!e) return null; e.scrollIntoView({block: 'nearest'});
              const b = e.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()""" % expression)

        KEYS = {'Home': 36, 'End': 35, 'Enter': 13, 'Tab': 9, 'ArrowDown': 40}

        async def key(name, shift=False, command=None):
            code = KEYS[name]
            base = {'key': name, 'code': name, 'windowsVirtualKeyCode': code,
                    'nativeVirtualKeyCode': code, 'modifiers': 8 if shift else 0}
            down = dict(base, type='keyDown', text='\r') if name == 'Enter' else dict(base, type='rawKeyDown')
            if command:
                down['commands'] = [command]
            await cmd('Input.dispatchKeyEvent', down, session)
            await cmd('Input.dispatchKeyEvent', dict(base, type='keyUp'), session)
            await asyncio.sleep(0.05)

        async def typed(text):
            for ch in text:
                await cmd('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': ch, 'text': ch}, session)
                await cmd('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': ch}, session)
            await asyncio.sleep(0.3)

        async def load(model):
            await cmd('Page.navigate', {'url': PAGE + model}, session)
            for _ in range(100):
                await asyncio.sleep(0.15)
                try:
                    if await ev("document.querySelectorAll('.trow .tname').length > 3"):
                        break
                except AssertionError:
                    pass
            await asyncio.sleep(0.5)

        async def settings(block):
            xy = await center("[...document.querySelectorAll('.trow .tname')].find(e => e.textContent.trim() === %s)"
                              % json.dumps(block))
            await click(*xy)
            xy = await center("[...document.querySelectorAll('button.info-act')].find(b => b.textContent.startsWith('Edit'))")
            await click(*xy)
            await asyncio.sleep(0.4)

        failures = []
        passed = [0]

        def check(condition, message):
            if condition:
                passed[0] += 1
            else:
                failures.append(message)

        target = (await cmd('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        session = (await cmd('Target.attachToTarget',
                             {'targetId': target, 'flatten': True}))['result']['sessionId']
        await cmd('Network.enable', {}, session)
        await cmd('Network.setCacheDisabled', {'cacheDisabled': True}, session)
        await cmd('Page.addScriptToEvaluateOnNewDocument', {'source': ERRORS}, session)
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session)

        # --- a block's own equation: Exact, in the mass on a spring ---------
        await load('harmonic-oscillator.json')
        await settings('Exact')
        if not await ev('!!' + FIELD):
            print('FAIL the settings window has no equation box')
            return 1
        # Beside it, for its height, the <input> an equation used to be typed in.
        rest = json.loads(await ev("""JSON.stringify((() => {
          const f = %s, cs = getComputedStyle(f);
          const unit = document.createElement('input');
          unit.type = 'text'; unit.className = 'mono'; f.closest('.insp-row').append(unit);
          const was = unit.getBoundingClientRect().height; unit.remove();
          const probe = document.createElement('span');
          probe.style.cssText = 'position:absolute;white-space:pre;visibility:hidden';
          // The longhands: the field's `font` shorthand is empty, since no
          // shorthand can say its `font-variant-ligatures: none`.
          probe.style.fontFamily = cs.fontFamily; probe.style.fontSize = cs.fontSize;
          probe.textContent = 'x'.repeat(100); document.body.append(probe);
          const char = probe.getBoundingClientRect().width / 100; probe.remove();
          const r = f.getBoundingClientRect();
          const below = f.closest('.insp-row').querySelector('.insp-atstart');
          return { tag: f.tagName, rows: f.rows, height: r.height, unit: was,
                   x: r.x, y: r.y, w: r.width, char, left: parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth),
                   value: f.value, open: f.parentElement.classList.contains('is-open'),
                   below: below ? below.getBoundingClientRect().top : null };
        })())""" % FIELD))
        check(rest['tag'] == 'TEXTAREA' and not rest['open'], 'the equation is not in a closed equation box: %s' % rest)
        check(abs(rest['height'] - rest['unit']) < 0.01,
              'at rest the box is %s px tall and an <input> in its place %s' % (rest['height'], rest['unit']))

        # In colour: a copy of the text under the field, the field's own glyphs
        # invisible over it, each part in the span for what it is -- and every
        # character of the copy where the field has it.
        drawn = json.loads(await ev("""JSON.stringify((() => {
          const f = %s, copy = f.parentElement.querySelector('.eq-hl');
          if (!copy) return null;
          const part = (word) => [...copy.querySelectorAll('span')].find((s) => s.textContent === word)?.className ?? null;
          const texts = [];
          const walk = (e) => { for (const c of e.childNodes) { if (c.nodeType === 3) texts.push(c); else walk(c); } };
          walk(copy);
          const at = (k) => {
            let n = 0;
            for (const t of texts) {
              if (k < n + t.length) {
                const r = document.createRange(); r.setStart(t, k - n); r.setEnd(t, k - n + 1);
                return r.getBoundingClientRect().left;
              }
              n += t.length;
            }
            return null;
          };
          return { text: copy.textContent, fill: getComputedStyle(f).webkitTextFillColor,
                   x0: part('x0'), omega: part('omega'), exp: part('exp'), time: part('time'),
                   lefts: [0, 10, 20, 40].map(at) };
        })())""" % FIELD))
        check(drawn is not None and drawn['text'] == rest['value'] and drawn['fill'] == 'rgba(0, 0, 0, 0)',
              'the equation is not drawn by a copy under an invisible field: %s' % drawn)
        check(drawn is not None and drawn['x0'] == 'eqh-ref eqh-parameter'
              and drawn['omega'] == 'eqh-ref eqh-expression'
              and drawn['exp'] == 'eqh-fn' and drawn['time'] == 'eqh-fn',
              'the parts are not drawn as what they are: %s' % drawn)
        want = [rest['x'] + rest['left'] + rest['char'] * k for k in (0, 10, 20, 40)]
        check(drawn is not None and all(a is not None and abs(a - b) < 0.5 for a, b in zip(drawn['lefts'], want)),
              "the copy's characters are not where the field has them: %s, not %s"
              % (drawn and drawn['lefts'], want))

        # A press on a character the open box puts on its second line.
        k = rest['value'].index('omega_d')
        x = rest['x'] + rest['left'] + rest['char'] * (k + 0.25)
        y = rest['y'] + rest['height'] / 2
        await click(x, y)
        s = await state()
        check(s['sel'] == [k, k], 'the caret went to %s, not to %d where the press was' % (s['sel'], k))
        check(s['open'] and s['height'] > rest['height'] + 10 and s['all'],
              'the box did not open to all of its equation: %s' % s)
        check(abs(s['rest'] - rest['height']) < 0.01, 'the box left %s px in the form, not %s' % (s['rest'], rest['height']))
        below = await ev("%s.closest('.insp-row').querySelector('.insp-atstart').getBoundingClientRect().top" % FIELD)
        check(below == rest['below'], 'the line under the box moved from %s to %s' % (rest['below'], below))

        # A double-click on a word in a box at rest.
        await ev('document.activeElement.blur()')
        await asyncio.sleep(0.1)
        x = rest['x'] + rest['left'] + rest['char'] * (k + 3)
        await mouse('mouseMoved', x, y)
        await mouse('mousePressed', x, y, 1, 1)
        await mouse('mouseReleased', x, y, 0, 1)
        await mouse('mousePressed', x, y, 1, 2)
        await mouse('mouseReleased', x, y, 0, 2)
        await asyncio.sleep(0.2)
        s = await state()
        check(s['sel'] == [k, k + 7], 'a double-click on omega_d selected %s' % s['sel'])

        # Home and End, plain, with Shift, and as a Mac sends them.
        n = len(rest['value'])
        top = s['scroll']
        seen = []
        for name, shift, command in (('End', False, None), ('Home', False, None),
                                     ('End', True, None), ('Home', False, 'scrollToBeginningOfDocument'),
                                     ('End', False, 'scrollToEndOfDocument'),
                                     ('Home', True, 'moveToBeginningOfDocumentAndModifySelection')):
            await key(name, shift, command)
            seen.append((await state())['sel'])
        check(seen == [[n, n], [0, 0], [0, n], [0, 0], [n, n], [0, n]],
              'Home and End took the caret to %s' % seen)
        check((await state())['scroll'] == top, 'Home or End scrolled the window')

        # The completion list, and Home with it open.
        await key('End')
        await typed(' + om')
        s = await state()
        check(s['list'] and s['listTop'] is not None and s['listTop'] >= s['bottom'] - 1,
              'the list is not open under the open box: %s' % s)
        await key('Home')
        s = await state()
        check(s['sel'] == [0, 0] and not s['list'], 'Home with the list open: %s' % s)

        # Enter: the list's first, then the box's, once.
        await ev("""(() => { window.__commits = 0;
          document.querySelector('dialog[open]').addEventListener('change', e => {
            if (e.target.classList.contains('eq-field')) window.__commits++; }); })()""")
        await key('End')
        await typed('ega_')
        await key('Enter')
        s = await state()
        check(s['value'].endswith('+ omega_d') and await ev('window.__commits') == 0,
              'Enter with the list open did not take omega_d alone: %s' % s['value'][-20:])
        await key('Enter')
        await asyncio.sleep(0.6)
        s = await state()
        tree = await ev("[...document.querySelectorAll('.trow')].find(r => r.querySelector('.tname')?.textContent.trim() === 'Exact').textContent")
        check(await ev('window.__commits') == 1 and tree.strip().endswith('+ omega_d'),
              'Enter committed %s times; the tree says %r' % (await ev('window.__commits'), tree[-30:]))
        check(s['tag'] == 'TEXTAREA' and s['open'] and s['sel'] == [n + 10, n + 10],
              'after Enter the box is not open with the caret where it was: %s' % s)
        await key('Tab')
        await asyncio.sleep(0.4)
        closed = json.loads(await ev("""JSON.stringify((() => { const f = %s;
          return [f.parentElement.classList.contains('is-open'), f.getBoundingClientRect().height]; })())""" % FIELD))
        check(await ev('window.__commits') == 1, 'leaving the box committed the edit again')
        check(not closed[0] and abs(closed[1] - rest['height']) < 0.01, 'after Tab the box is %s' % closed)

        # A pasted line break, and Down in a wrapped box.
        xy = await center(FIELD)
        await click(*xy)
        await key('End')
        await ev("document.execCommand('insertText', false, ' + x0\\n* zeta\\n')")
        s = await state()
        check(s['value'].endswith(' + x0 * zeta') and '\n' not in s['value'],
              'a pasted line break is still one: %r' % s['value'][-14:])
        await key('Home')
        await key('ArrowDown')
        s = await state()
        check(0 < s['sel'][0] < len(s['value']) and not s['list'], 'Down from the first line: %s' % s)
        await key('End')
        await key('ArrowDown')
        s = await state()
        check(s['list'], 'Down at the end did not open the list')

        # A name the model has not got is marked where it stands, and the
        # copy of an open box is where the field is.
        await key('End')
        await typed(' + nope')
        marked = json.loads(await ev("""JSON.stringify((() => {
          const f = document.activeElement, copy = f.parentElement.querySelector('.eq-hl');
          const r = f.getBoundingClientRect(), c = copy.getBoundingClientRect();
          return { bad: [...copy.querySelectorAll('.eqh-bad')].map((s) => s.textContent),
                   off: [r.x - c.x, r.y - c.y, r.width - c.width, r.height - c.height] };
        })())"""))
        check(marked['bad'] == ['nope'], 'the name the model has not got is not marked: %s' % marked)
        check(all(abs(v) < 0.01 for v in marked['off']), 'the copy of the open box is off the field: %s' % marked)

        # --- a per-index grid: Release, in the landscape model ---------------
        await load('landscape.json')
        await settings('Release')
        cell = "document.querySelectorAll('dialog[open] .insp-entry .eq-field')[2]"
        check(await ev("%s.parentElement.querySelector('.eq-hl').classList.contains('is-muted')" % cell),
              'a value the row inherits is not drawn muted')
        before = json.loads(await ev("""JSON.stringify((() => { const f = %s, r = f.getBoundingClientRect();
          const list = f.closest('.insp-entry-list').getBoundingClientRect();
          return { x: r.x, w: r.width, h: r.height, right: list.right }; })())""" % cell))
        xy = await center(cell)
        await click(*xy)
        s = json.loads(await ev("""JSON.stringify((() => { const f = document.activeElement, r = f.getBoundingClientRect();
          return { x: r.x, w: r.width, h: r.height, open: f.parentElement.classList.contains('is-open') }; })())"""))
        check(s['open'] and s['x'] == before['x'] and s['w'] > before['w'] and abs(s['h'] - before['h']) < 0.01,
              'the grid box did not open wider on one line: %s, from %s' % (s, before))
        # The copy wraps where the field does: as wide inside, and as tall.
        # (It once kept a scrollbar it was given in the instant it opened,
        # and wrapped a word earlier than the field.)
        WRAPS = """JSON.stringify((() => {
          const f = document.activeElement, c = f.parentElement.querySelector('.eq-hl');
          const inner = (e) => e.clientWidth - parseFloat(getComputedStyle(e).paddingLeft)
            - parseFloat(getComputedStyle(e).paddingRight);
          return [inner(f), inner(c), f.scrollHeight, c.scrollHeight]; })())"""
        w = json.loads(await ev(WRAPS))
        check(abs(w[0] - w[1]) < 0.5 and w[2] == w[3], 'the open copy wraps elsewhere than the field: %s' % w)
        await key('End')
        await typed(' * exp(-time()/1000) * (1 + Kd*rho/porosity) * (1 + Kd*rho/porosity)')
        s = json.loads(await ev("""JSON.stringify((() => { const f = document.activeElement, r = f.getBoundingClientRect();
          return { right: r.right, h: r.height, all: f.scrollHeight <= f.clientHeight + 1 }; })())"""))
        check(s['right'] <= before['right'] and s['h'] > before['h'] + 10 and s['all'],
              'a long equation in the grid is not wrapped inside it: %s, the grid ends at %s' % (s, before['right']))
        w = json.loads(await ev(WRAPS))
        check(abs(w[0] - w[1]) < 0.5 and w[2] == w[3], 'the wrapped copy wraps elsewhere than the field: %s' % w)

        errors = await ev('window.__errors')
        check(not errors, 'the page raised: %s' % errors)

        await cmd('Target.closeTarget', {'targetId': target})
        total = passed[0] + len(failures)
        for f in failures:
            print('FAIL', f)
        print('%d/%d checks passed' % (passed[0], total))
        return 1 if failures else 0


sys.exit(asyncio.run(main()))
