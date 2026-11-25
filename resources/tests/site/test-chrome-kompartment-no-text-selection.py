"""Kompartment's diagram is drawn, not read: a press on it starts a gesture and
never a text selection.

A double-click on a block opens its settings, a shift-click adds a block to
the selection, a shift-drag draws a box round blocks. Left to the browser, the
double-click also selected the name it landed on, and shift extended the
page's text selection over every label between the two blocks pressed or in
the box. `.graph-host` in kompartment/css/app.css takes the selection away
from the whole canvas.

Checked with real presses and drags on the landscape example: a double-click
on a block's label, a click and then a shift-click on another block, a
shift-drag box across the labels, a drag of a block across others, a pan from
the background, and drags that start on the canvas and end on the text beside
it -- none of them leaves any text selected; a selection made elsewhere
on the page still goes when the canvas is pressed; and the page raised
nothing.

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

# Every block on the diagram with a label, by name, with its label's box on screen.
LABELS = """Object.fromEntries([...document.querySelectorAll('.graph-nodes .gnode')].map((n) => {
  const t = n.querySelector('text'); const r = (t ?? n).getBoundingClientRect();
  return [n.dataset.name, [r.x, r.y, r.width, r.height]]; }).filter(([, r]) => r[2] > 10))"""
SELECTED = 'String(getSelection())'
SHIFT = 8
# A point of bare canvas, low on it: the diagram's own background, not a block,
# a line or the bar over the top of the canvas.
BACKGROUND = """(() => { const s = document.querySelector('.graph-svg'); const r = s.getBoundingClientRect();
  for (let y = r.bottom - 20; y > r.top + r.height / 2; y -= 15)
    for (let x = r.left + 20; x < r.right - 20; x += 15)
      if (document.elementFromPoint(x, y) === s) return [x, y];
  return null; })()"""


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

        async def mouse(kind, x, y, buttons=0, clicks=1, modifiers=0):
            # A move with a button held says which, as a real mouse's does:
            # sent as `none`, Chrome takes it for a hover and the pointer
            # capture a drag asked for is never given.
            await cmd('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'modifiers': modifiers,
                      'button': 'left' if kind != 'mouseMoved' or buttons else 'none',
                      'buttons': buttons, 'clickCount': clicks}, session)

        async def press(x, y, clicks=1, modifiers=0):
            await mouse('mouseMoved', x, y, 0, 1, modifiers)
            await mouse('mousePressed', x, y, 1, clicks, modifiers)
            await mouse('mouseReleased', x, y, 0, clicks, modifiers)
            await asyncio.sleep(0.2)

        async def drag(x0, y0, x1, y1, modifiers=0, steps=12):
            await mouse('mouseMoved', x0, y0, 0, 1, modifiers)
            await mouse('mousePressed', x0, y0, 1, 1, modifiers)
            for k in range(1, steps + 1):
                await mouse('mouseMoved', x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps, 1, 1, modifiers)
                await asyncio.sleep(0.02)
            await mouse('mouseReleased', x1, y1, 0, 1, modifiers)
            await asyncio.sleep(0.3)

        async def close_window():
            # By its x rather than by Escape: in headless Chrome on macOS an
            # Escape the page does not take goes on to the browser, which opens
            # its About page, and the next press sent never comes back.
            xy = await ev("""(() => { const b = document.querySelector('dialog.is-floating[open] .modal-close');
              if (!b) return null; const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()""")
            if xy:
                await press(*xy)

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
        await cmd('Page.navigate', {'url': PAGE}, session)
        for _ in range(100):
            await asyncio.sleep(0.15)
            try:
                if await ev("document.querySelectorAll('.graph-nodes .gnode').length > 3"):
                    break
            except AssertionError:
                pass
        await asyncio.sleep(0.6)

        labels = sorted((await ev(LABELS)).items(), key=lambda kv: (kv[1][1], kv[1][0]))
        if len(labels) < 3:
            print('FAIL the diagram has %d labelled blocks' % len(labels))
            return 1
        (_, a), (_, b) = labels[0], labels[1]
        mid_a = (a[0] + a[2] / 2, a[1] + a[3] / 2)
        mid_b = (b[0] + b[2] / 2, b[1] + b[3] / 2)
        background = await ev(BACKGROUND)
        if not background:
            print('FAIL no bare canvas to press on')
            return 1
        # Where a box drawn from the background reaches: past every label, and
        # still on the canvas.
        canvas = await ev("""(() => { const r = document.querySelector('.graph-svg').getBoundingClientRect();
          return [r.left, r.top, r.right, r.bottom]; })()""")
        # Text beside the canvas that can be selected: the model's comment in
        # the Information view.
        beside = await ev("""(() => { const c = document.querySelector('.info-comment'); if (!c) return null;
          const r = c.getBoundingClientRect(); return r.height ? [r.x + 30, r.y + 8] : null; })()""")
        if not beside:
            print('FAIL no text beside the canvas to drag onto')
            return 1

        async def fresh():
            await ev('getSelection().removeAllRanges()')
            await press(*background)

        # --- a double-click opens the block, and selects none of its name --
        await fresh()
        await press(*mid_a, 1)
        await press(*mid_a, 2)
        await asyncio.sleep(0.3)
        check(await ev(SELECTED) == '', 'a double-click on a label selected %r' % await ev(SELECTED))
        check(await ev("!!document.querySelector('dialog.is-floating[open]')"), 'the double-click opened no block window')
        await close_window()

        # --- shift adds blocks, and stretches no selection between them ----
        await fresh()
        await press(*mid_a)
        await press(*mid_b, 1, SHIFT)
        check(await ev(SELECTED) == '', 'a click and a shift-click selected %r' % await ev(SELECTED))

        await fresh()
        far = (min(max(r[0] + r[2] for _, r in labels) + 40, canvas[2] - 10),
               max(min(r[1] for _, r in labels) - 20, canvas[1] + 60))
        await drag(*background, *far, SHIFT)
        check(await ev(SELECTED) == '', 'a shift-drag box selected %r' % await ev(SELECTED))

        # --- a block dragged over others, and a pan ------------------------
        await fresh()
        await drag(*mid_a, b[0] + b[2] + 80, b[1] + 40)
        check(await ev(SELECTED) == '', 'a block dragged across others selected %r' % await ev(SELECTED))

        await fresh()
        await drag(*background, *mid_b)
        check(await ev(SELECTED) == '', 'a pan selected %r' % await ev(SELECTED))

        # --- off the canvas: a drag out of it, and a selection made elsewhere
        await fresh()
        await drag(*background, *beside)
        check(await ev(SELECTED) == '', 'a drag from the canvas onto the text beside it selected %r'
              % await ev(SELECTED))
        await fresh()
        await drag(*background, *beside, SHIFT)
        check(await ev(SELECTED) == '', 'a shift-drag from the canvas onto the text beside it selected %r'
              % await ev(SELECTED))

        await ev("""(() => { const r = document.createRange(); r.selectNodeContents(document.querySelector('.info-comment'));
          getSelection().removeAllRanges(); getSelection().addRange(r); })()""")
        selected = await ev(SELECTED)
        await press(*background)
        check(selected and await ev(SELECTED) == '',
              'a press on the canvas left a selection made elsewhere: %r of %r' % ((await ev(SELECTED))[:40], selected[:40]))

        errors = await ev('window.__errors')
        check(not errors, 'the page raised: %s' % errors)

        await cmd('Target.closeTarget', {'targetId': target})

        for f in failures:
            print('FAIL ' + f)
        total = passed[0] + len(failures)
        print('%d/%d checks passed' % (passed[0], total))
        return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
