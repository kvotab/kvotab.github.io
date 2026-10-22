"""Kompartment's bar over the diagram, on the Build tab.

The bar floats over the top of the canvas and holds what the canvas's
right-click menu is reached for most for: blocks to add, what is drawn, the
zoom. A click on a block's button adds one in the middle of the view, on the
nearest place nothing is drawn at; a drag drops it where it is let go. Its
menus are the canvas menu's own. It can be put away, which this browser
remembers. See kompartment/src/ui/canvasbar.js.

Checked with real presses and drags, on the landscape model:
  - the bar is up, at the top of the canvas, one stop for Tab, and a fitted
    diagram starts below it;
  - a click on Compartment adds one in the middle of what can be seen, and
    selects it; a second click adds another beside it rather than on it;
  - a drag of Expression drops one centred where it is let go, an outline of
    it following the pointer on the way; Escape during a drag adds nothing;
  - Show opens the canvas menu's own Show, under the button, and a second
    press closes it;
  - the grid switch follows the setting both ways, the canvas menu's tick
    with it; the zoom buttons and the level between them agree;
  - the arrow keys move along the bar, and Down opens a menu that Escape
    closes, the focus back on its button;
  - inside a transport the sub-system button is off and More starts with a
    transport operation;
  - × puts the bar away, a reload keeps it away, and Canvas ▸ Show toolbar
    brings it back;
  - and that the page raised nothing.

Serve the repository and start headless Chrome (the recipe is in README.md),
by default on ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose
others. Exit status is 0 when every check passes.
"""
import asyncio, json, os, sys, urllib.request
import websockets

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))
PAGE = 'http://127.0.0.1:%d/kompartment/index.html?model=landscape.json' % HTTP

ERRORS = """window.__errors = [];
addEventListener('error', e => window.__errors.push(String(e.message)));
addEventListener('unhandledrejection', e => window.__errors.push('rejected: ' + e.reason));"""

BUTTON = "[...document.querySelectorAll('.canvas-bar button')].find((b) => b.getAttribute('aria-label') === %s)"
# A menu item by its label, in the panel opened last (a submenu is a panel of
# its own); the tick a switch carries is a glyph before the label.
ITEM = "[...document.querySelectorAll('.menu-layer .menu-panel:last-child .menu-item')].find((b) => b.textContent.replace('\\u2713', '').trim().startsWith(%s))"
# Every node on the diagram, by name, with its box on screen.
NODES = """Object.fromEntries([...document.querySelectorAll('.graph-nodes .gnode')].map((n) => {
  const r = n.getBoundingClientRect(); return [n.dataset.name, [r.x, r.y, r.width, r.height]]; }))"""
# The middle of the canvas below the bar, on screen.
MIDDLE = """(() => { const s = document.querySelector('.graph-svg').getBoundingClientRect();
  const b = document.querySelector('.canvas-bar').getBoundingClientRect();
  const top = b.bottom + 6; return [s.x + s.width / 2, top + (s.bottom - top) / 2]; })()"""


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

        async def mouse(kind, x, y, buttons=0, clicks=1, button='left'):
            # A move with a button held says which, as a real mouse's does:
            # sent as `none`, Chrome takes it for a hover and the pointer
            # capture a drag asked for is never given.
            await cmd('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y,
                      'button': button if kind != 'mouseMoved' or buttons else 'none',
                      'buttons': buttons, 'clickCount': clicks}, session)

        async def centre(expression):
            # In sight first: a menu opened low down is cut to the room there
            # and scrolls, and its last items start below its edge.
            return await ev("""(() => { const e = %s; if (!e) return null; e.scrollIntoView({ block: 'nearest' });
              const b = e.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()""" % expression)

        async def click(expression):
            xy = await centre(expression)
            if not xy:
                raise AssertionError('nothing to click: ' + expression[:80])
            await mouse('mouseMoved', *xy)
            await mouse('mousePressed', *xy, 1)
            await mouse('mouseReleased', *xy, 0)
            await asyncio.sleep(0.3)

        async def right_click_canvas():
            x, y = await ev("""(() => { const r = document.querySelector('.graph-svg').getBoundingClientRect();
              return [r.x + 30, r.bottom - 30]; })()""")
            await mouse('mouseMoved', x, y)
            await mouse('mousePressed', x, y, 2, 1, 'right')
            await mouse('mouseReleased', x, y, 0, 1, 'right')
            await asyncio.sleep(0.3)

        KEYS = {'Tab': 9, 'ArrowRight': 39, 'ArrowLeft': 37, 'ArrowDown': 40, 'Home': 36, 'End': 35, 'Escape': 27}

        async def key(name):
            base = {'key': name, 'code': name, 'windowsVirtualKeyCode': KEYS[name], 'nativeVirtualKeyCode': KEYS[name]}
            await cmd('Input.dispatchKeyEvent', dict(base, type='rawKeyDown'), session)
            await cmd('Input.dispatchKeyEvent', dict(base, type='keyUp'), session)
            await asyncio.sleep(0.1)

        async def load():
            await cmd('Page.navigate', {'url': PAGE}, session)
            for _ in range(100):
                await asyncio.sleep(0.15)
                try:
                    if await ev("document.querySelectorAll('.graph-nodes .gnode').length > 3"):
                        break
                except AssertionError:
                    pass
            await asyncio.sleep(0.6)

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

        # From a fresh start: whatever an earlier run left in this profile goes.
        await load()
        await ev("localStorage.removeItem('kompartment.canvasBar')")
        await load()
        if not await ev("!!document.querySelector('.canvas-bar')"):
            print('FAIL the canvas has no bar')
            return 1

        # --- up, in its place, and a fit starts under it -------------------
        bar = json.loads(await ev("""JSON.stringify((() => {
          const b = document.querySelector('.canvas-bar'), s = document.querySelector('.graph-svg');
          const r = b.getBoundingClientRect(), c = s.getBoundingClientRect();
          return { hidden: b.hidden, role: b.getAttribute('role'), top: r.top - c.top, left: r.left - c.left,
                   bottom: r.bottom, inside: b.parentElement === s.parentElement,
                   stops: [...b.querySelectorAll('button')].filter((x) => x.tabIndex === 0).length };
        })())"""))
        check(not bar['hidden'] and bar['role'] == 'toolbar' and bar['inside'] and 0 <= bar['top'] < 16
              and 0 <= bar['left'] < 16 and bar['stops'] == 1, 'the bar is not up at the top of the canvas: %s' % bar)
        await click(BUTTON % json.dumps('Fit to view'))
        nodes = await ev(NODES)
        top = min(r[1] for r in nodes.values())
        check(top > bar['bottom'], 'a fitted diagram starts at %s, under the bar ending at %s' % (top, bar['bottom']))

        # --- a click adds in the middle of the view, a second beside it -----
        before = await ev(NODES)
        mid = await ev(MIDDLE)
        await click(BUTTON % json.dumps('Compartment'))
        after = await ev(NODES)
        new = [n for n in after if n not in before]
        selected = await ev("[...document.querySelectorAll('.graph-nodes .gnode.is-selected')].map((n) => n.dataset.name)")
        ok = len(new) == 1
        if ok:
            x, y, w, h = after[new[0]]
            ok = abs(x + w / 2 - mid[0]) < 14 and abs(y + h / 2 - mid[1]) < 14 and selected == new
        check(ok, 'a click did not add one selected compartment in the middle %s: %s, selected %s'
              % (mid, [(n, after[n]) for n in new], selected))
        await click(BUTTON % json.dumps('Compartment'))
        again = await ev(NODES)
        second = [n for n in again if n not in after]

        def apart(a, b):
            return a[0] >= b[0] + b[2] or b[0] >= a[0] + a[2] or a[1] >= b[1] + b[3] or b[1] >= a[1] + a[3]
        check(len(second) == 1 and new and apart(again[second[0]], again[new[0]]),
              'the second compartment was put on the first: %s' % [(n, again[n]) for n in second + new])

        # --- a drag drops one where it is let go ----------------------------
        before = await ev(NODES)
        start = await centre(BUTTON % json.dumps('Expression'))
        drop = [mid[0] + 260, mid[1] + 170]
        await mouse('mouseMoved', *start)
        await mouse('mousePressed', *start, 1)
        for i in range(1, 11):
            await mouse('mouseMoved', start[0] + (drop[0] - start[0]) * i / 10,
                        start[1] + (drop[1] - start[1]) * i / 10, 1)
        ghost = await ev("(() => { const g = document.querySelector('.canvas-bar-ghost'); return g ? g.className : null; })()")
        await mouse('mouseReleased', *drop, 0)
        await asyncio.sleep(0.3)
        after = await ev(NODES)
        new = [n for n in after if n not in before]
        ok = len(new) == 1
        if ok:
            x, y, w, h = after[new[0]]
            ok = abs(x + w / 2 - drop[0]) < 10 and abs(y + h / 2 - drop[1]) < 10
        check(ghost == 'canvas-bar-ghost is-over' and ok and not await ev("!!document.querySelector('.canvas-bar-ghost')"),
              'a dragged expression did not land on %s: %s, the outline %s' % (drop, [(n, after.get(n)) for n in new], ghost))
        # Escape on the way adds nothing, and leaves no outline behind.
        before = await ev(NODES)
        start = await centre(BUTTON % json.dumps('Compartment'))
        await mouse('mouseMoved', *start)
        await mouse('mousePressed', *start, 1)
        for i in range(1, 6):
            await mouse('mouseMoved', start[0] + 50 * i, start[1] + 60 * i, 1)
        await key('Escape')
        await mouse('mouseReleased', start[0] + 250, start[1] + 300, 0)
        await asyncio.sleep(0.3)
        check(len(await ev(NODES)) == len(before) and not await ev("!!document.querySelector('.canvas-bar-ghost')"),
              'Escape during a drag still added a block')

        # --- Show is the canvas menu's own --------------------------------
        await right_click_canvas()
        await click(ITEM % json.dumps('Show'))
        theirs = await ev("[...document.querySelectorAll('.menu-layer .menu-panel:last-child .menu-item')].map((b) => b.textContent.trim())")
        await key('Escape')
        await asyncio.sleep(0.2)
        await click(BUTTON % json.dumps('Show'))
        ours = await ev("[...document.querySelectorAll('.menu-layer .menu-panel:last-child .menu-item')].map((b) => b.textContent.trim())")
        under = await ev("""(() => { const p = document.querySelector('.menu-layer .menu-panel'), b = %s;
          return p ? p.getBoundingClientRect().top - b.getBoundingClientRect().bottom : null; })()""" % (BUTTON % json.dumps('Show')))
        check(ours and ours == theirs and under is not None and 0 <= under < 12,
              "the bar's Show is not the canvas menu's: %s against %s, %s px under the button" % (ours, theirs, under))
        await click(BUTTON % json.dumps('Show'))
        check(not await ev("!!document.querySelector('.menu-layer')"), 'a second press on Show left its menu open')

        # --- the grid switch, both ways ------------------------------------
        was = await ev("document.querySelector('.graph-svg').classList.contains('has-grid')")
        await click(BUTTON % json.dumps('Show grid'))
        now = await ev("[document.querySelector('.graph-svg').classList.contains('has-grid'), %s.getAttribute('aria-pressed')]"
                       % (BUTTON % json.dumps('Show grid')))
        await right_click_canvas()
        await click(ITEM % json.dumps('Canvas'))
        tick = await ev("(() => { const i = %s; return i ? String(i.querySelector('.menu-tick')?.textContent === '\\u2713') : null; })()"
                        % (ITEM % json.dumps('Show grid')))
        await click(ITEM % json.dumps('Show grid'))
        back = await ev("%s.getAttribute('aria-pressed')" % (BUTTON % json.dumps('Show grid')))
        await key('Escape')
        check(now == [not was, str(not was).lower()] and tick == str(not was).lower() and back == str(was).lower(),
              'the grid switch and the menu disagree: was %s, then %s, ticked %s, back %s' % (was, now, tick, back))

        # --- the zoom ------------------------------------------------------
        await click(BUTTON % json.dumps('Back to 100%'))
        levels = [await ev("document.querySelector('.canvas-bar-level').textContent")]
        await click(BUTTON % json.dumps('Zoom in'))
        levels.append(await ev("document.querySelector('.canvas-bar-level').textContent"))
        await click(BUTTON % json.dumps('Zoom out'))
        await click(BUTTON % json.dumps('Zoom out'))
        levels.append(await ev("document.querySelector('.canvas-bar-level').textContent"))
        check(levels == ['100%', '125%', '80%'], 'the zoom read %s' % levels)

        # --- the keyboard --------------------------------------------------
        await ev(BUTTON % json.dumps('Compartment') + '.focus()')
        moves = []
        for name in ('ArrowRight', 'ArrowLeft', 'End', 'Home'):
            await key(name)
            moves.append(await ev("document.activeElement.getAttribute('aria-label')"))
        await ev(BUTTON % json.dumps('Show') + '.focus()')
        await key('ArrowDown')
        opened = await ev("!!document.activeElement.closest('.menu-layer')")
        await key('Escape')
        await asyncio.sleep(0.2)
        check(moves == ['Expression', 'Compartment', 'Put the bar away', 'Compartment'] and opened
              and await ev("document.activeElement.getAttribute('aria-label')") == 'Show'
              and not await ev("!!document.querySelector('.menu-layer')"),
              'the keys along the bar: %s, the menu opened %s' % (moves, opened))

        # --- inside a transport ------------------------------------------
        await click(BUTTON % json.dumps('More blocks'))
        await click(ITEM % json.dumps('1-D transport'))
        xy = await centre("[...document.querySelectorAll('.graph-nodes .gnode')].find((n) => n.dataset.name === 'Transport')")
        await mouse('mouseMoved', *xy)
        await mouse('mousePressed', *xy, 1, 1)
        await mouse('mouseReleased', *xy, 0, 1)
        await mouse('mousePressed', *xy, 1, 2)
        await mouse('mouseReleased', *xy, 0, 2)
        await asyncio.sleep(0.5)
        off = await ev(BUTTON % json.dumps('Sub-system') + '.disabled')
        await click(BUTTON % json.dumps('More blocks'))
        first = await ev("document.querySelector('.menu-layer .menu-item')?.textContent.trim()")
        await key('Escape')
        check(off and first == 'Transport operation',
              'inside a transport: sub-system button %s, More starts with %r' % ('off' if off else 'on', first))

        # --- away, and back ------------------------------------------------
        await click(BUTTON % json.dumps('Put the bar away'))
        away = [await ev("document.querySelector('.canvas-bar').hidden"),
                await ev("localStorage.getItem('kompartment.canvasBar')")]
        await load()
        away.append(await ev("document.querySelector('.canvas-bar').hidden"))
        await right_click_canvas()
        await click(ITEM % json.dumps('Canvas'))
        await click(ITEM % json.dumps('Show toolbar'))
        await key('Escape')
        back = [await ev("document.querySelector('.canvas-bar').hidden"),
                await ev("localStorage.getItem('kompartment.canvasBar')")]
        check(away == [True, 'off', True] and back == [False, 'on'],
              'put away %s, then brought back %s' % (away, back))

        errors = await ev('window.__errors')
        check(not errors, 'the page raised: %s' % errors)

        await cmd('Target.closeTarget', {'targetId': target})
        total = passed[0] + len(failures)
        for f in failures:
            print('FAIL', f)
        print('%d/%d checks passed' % (passed[0], total))
        return 1 if failures else 0


sys.exit(asyncio.run(main()))
