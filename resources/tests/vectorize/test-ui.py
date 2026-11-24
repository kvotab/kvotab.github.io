#!/usr/bin/env python3
"""vectorize.html in a real browser: tracing black lines only, and editing
the vector.

test-trace.js proves the engine. This proves the page, on its own coloured
cartoon (the Sample with black lines only chosen), so it needs no files:

- the Trace choice, its hints, the preset that chooses black lines only, and
  Faint lines set aside for it; a picture in colour traced by darkness
  offers black lines only, and the offer works;
- black lines only leaves the colours out (a red wall, the sky) and keeps a
  black area (the cat), where tracing by darkness fills the wall;
- Remove: the part under the pointer in red, a click takes it out at once
  and the trace agrees, a box takes out what is wholly inside it, a tap
  does on a touch screen; Undo and Redo by button and by key; removed parts
  stay out when the line weight changes;
- Erase: the stroke hides the drawing as it is painted, and the trace then
  cuts the outline open; dragging selects no text;
- the space bar held moves the picture whatever the tool, and does not
  press a focused button; Escape goes back to Move; Restore all, and its
  undo; the Black & white view and the downloaded SVG have the edits;
- the Trace choice is kept over a reload, and an old "light lines" tick
  becomes that choice.

Serve the repository and start Chrome first, muted. The ports are 8861 and
9361 unless VZ_HTTP_PORT and VZ_CDP_PORT say otherwise; check them with
`lsof -nP -iTCP:<port> -sTCP:LISTEN` first, because other sessions use ports
too:

    python3 -m http.server 8861 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
      --headless=new --remote-debugging-port=9361 --no-first-run \\
      --user-data-dir=/tmp/vztest --mute-audio about:blank

    python3 -u resources/tests/vectorize/test-ui.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import os
import re
import sys
import urllib.request

import websockets

HTTP = int(os.environ.get('VZ_HTTP_PORT', '8861'))
CDP = int(os.environ.get('VZ_CDP_PORT', '9361'))
URL = f'http://127.0.0.1:{HTTP}/vectorize.html'

passed, failed = 0, []


def check(label, ok, detail=''):
    global passed
    if ok:
        passed += 1
    else:
        failed.append(label)
    print(('ok    ' if ok else 'FAIL  ') + label + (f': {detail}' if detail != '' else ''), flush=True)


class Page:
    """One tab, driven over the DevTools protocol."""

    def __init__(self):
        self.n = 0
        self.waiting = {}
        self.errors = []

    async def open(self, url):
        req = urllib.request.Request(f'http://127.0.0.1:{CDP}/json/new?about:blank', method='PUT')
        self.target = json.loads(urllib.request.urlopen(req).read())
        self.ws = await websockets.connect(self.target['webSocketDebuggerUrl'], max_size=2 ** 28)
        self.reader = asyncio.create_task(self.pump())
        for m in ('Page.enable', 'Runtime.enable', 'DOM.enable', 'Network.enable'):
            await self.call(m)
        await self.call('Network.setCacheDisabled', {'cacheDisabled': True})
        await self.call('Emulation.setDeviceMetricsOverride', {'width': 1400, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
        await self.call('Page.navigate', {'url': url})
        await self.wait("document.readyState === 'complete' && !!document.getElementById('vz-tools')", 20)

    async def pump(self):
        async for raw in self.ws:
            m = json.loads(raw)
            if m.get('id') in self.waiting:
                self.waiting.pop(m['id']).set_result(m)
            elif m.get('method') == 'Runtime.exceptionThrown':
                d = m['params']['exceptionDetails']
                self.errors.append((d.get('exception') or {}).get('description') or d.get('text', ''))
            elif m.get('method') == 'Runtime.consoleAPICalled' and m['params']['type'] == 'error':
                self.errors.append(' '.join(str(a.get('value', a.get('description', ''))) for a in m['params']['args']))

    async def call(self, method, params=None):
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.waiting[self.n] = fut
        await self.ws.send(json.dumps({'id': self.n, 'method': method, 'params': params or {}}))
        m = await asyncio.wait_for(fut, 60)
        if 'error' in m:
            raise RuntimeError(f"{method}: {m['error']}")
        return m['result']

    async def ev(self, expr):
        r = await self.call('Runtime.evaluate', {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
        if 'exceptionDetails' in r:
            raise RuntimeError('in the page: ' + json.dumps(r['exceptionDetails'])[:600])
        return r['result'].get('value')

    async def wait(self, expr, timeout=20):
        for _ in range(int(timeout / 0.1)):
            if await self.ev(expr):
                return True
            await asyncio.sleep(0.1)
        return False

    async def mouse(self, kind, x, y, buttons=0):
        await self.call('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left', 'buttons': buttons, 'clickCount': 1})

    async def click(self, x, y):
        await self.mouse('mouseMoved', x, y)
        await self.mouse('mousePressed', x, y, 1)
        await self.mouse('mouseReleased', x, y)

    async def drag(self, a, b, steps=8):
        await self.mouse('mouseMoved', *a)
        await self.mouse('mousePressed', *a, 1)
        for k in range(1, steps + 1):
            await self.mouse('mouseMoved', a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps, 1)
        await self.mouse('mouseReleased', *b)

    async def key(self, key, code, kind, mods=0, vk=0):
        await self.call('Input.dispatchKeyEvent', {'type': kind, 'key': key, 'code': code, 'modifiers': mods, 'windowsVirtualKeyCode': vk})

    async def reload(self):
        await self.ev('window.__beforeReload = true, 1')
        await self.call('Page.reload')
        await self.wait("!window.__beforeReload && document.readyState === 'complete' && !!document.getElementById('vz-tools')", 20)
        await asyncio.sleep(0.3)

    async def close(self):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json/close/{self.target['id']}").read()
        except Exception:
            pass
        self.reader.cancel()


# The cartoon's places, in its own pixels (560 x 380).
SUN_RING = (482, 32.5)      # the top of the sun's outline
WALL = (100, 262)           # the red wall, away from any line
SKY = (60, 60)
CAT = (120, 336)            # the black cat's body
CLOUD_RIM = (276, 86)       # the cloud's outline at its left
RIGHT_FLOWERS = ((452, 304), (532, 386))
STEMS = {'left': [(301.3, 343), (333.3, 361)], 'right': [(471.3, 351), (511.3, 369)]}   # flower stems, ink

SCREEN = "((x, y) => { const p = new DOMPoint(x, y).matrixTransform(document.getElementById('vz-svg').getScreenCTM()); return [p.x, p.y]; })"
INK = "((x, y) => document.getElementById('vz-path').isPointInFill(new DOMPoint(x, y)))"
OUTLINES = "((document.getElementById('vz-path').getAttribute('d') || '').match(/M/g) || []).length"
EDITS = "(document.getElementById('vz-edits').hidden ? '' : document.getElementById('vz-edits-text').textContent)"


async def main():
    p = Page()
    await p.open(URL)
    try:
        await run(p)
    finally:
        await p.close()
    for e in p.errors:
        check('no script error', False, e)
    print(f'\n{passed}/{passed + len(failed)} checks passed')
    if failed:
        print('Failed:\n  ' + '\n  '.join(failed))
        sys.exit(1)


async def settle(p):
    await asyncio.sleep(0.15)
    await p.wait("document.getElementById('vz-busy').hidden", 30)
    await asyncio.sleep(0.1)


async def at(p, xy):
    return await p.ev(f'{SCREEN}({xy[0]}, {xy[1]})')


async def ink(p, xy):
    return await p.ev(f'{INK}({xy[0]}, {xy[1]})')


async def run(p):
    await p.ev("localStorage.removeItem('vectorize.settings'), 1")
    await p.reload()
    check('Trace starts at Everything dark, with its hint',
          await p.ev("document.querySelector('input[name=vz-ink]:checked').value") == 'dark' and
          (await p.ev("document.getElementById('vz-ink-hint').textContent")).startswith('Whatever is darker'))
    check('the tools wait for a picture', await p.ev("document.getElementById('vz-tools').hidden"))

    # A picture in colour, traced by darkness, offers black lines only.
    await p.ev("""(async () => {
      const c = document.createElement('canvas'); c.width = 240; c.height = 160;
      const g = c.getContext('2d');
      g.fillStyle = '#2b62c8'; g.fillRect(0, 0, 240, 160);
      g.fillStyle = '#e0402a'; g.fillRect(40, 30, 160, 100);
      g.lineWidth = 4; g.strokeRect(40, 30, 160, 100);
      const blob = await new Promise(r => c.toBlob(r, 'image/png'));
      const dt = new DataTransfer();
      dt.items.add(new File([blob], 'colours.png', { type: 'image/png' }));
      document.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true }));
      return 1; })()""")
    await p.wait("document.getElementById('vz-stats').textContent.length > 0", 30)
    offer = await p.ev("(document.querySelector('#vz-status .vz-linkbtn') || {}).textContent || ''")
    check('a picture in colour traced by darkness offers black lines only', offer == 'trace black lines only' and 'leave its colours out' in await p.ev("document.getElementById('vz-status').textContent"),
          await p.ev("document.getElementById('vz-status').textContent"))
    await p.ev("document.querySelector('#vz-status .vz-linkbtn').click(), 1")
    await settle(p)
    check('the offer chooses black lines only', await p.ev("document.querySelector('input[name=vz-ink]:checked').value") == 'black')
    check('the frame of the red box is traced, the red and the blue are not', await ink(p, (40, 80)) and not await ink(p, (120, 80)) and not await ink(p, (15, 15)))

    # The preset for a cartoon chooses black lines only, and sets Faint lines aside.
    await p.ev("document.querySelector('input[name=vz-ink][value=dark]').click(), 1")
    await p.ev("(() => { const s = document.getElementById('vz-preset'); s.value = 'cartoon'; s.dispatchEvent(new Event('change')); })(), 1")
    check('the cartoon preset chooses black lines only', await p.ev("document.querySelector('input[name=vz-ink]:checked').value") == 'black')
    check('Faint lines is set aside, and says why', await p.ev("document.getElementById('vz-faint').disabled") and
          'Not used for black lines only' in await p.ev("document.getElementById('vz-faint-hint').textContent"))
    await p.ev("document.querySelector('[data-act=sample]').click(), 1")
    await p.wait("document.getElementById('vz-source').textContent.startsWith('sample-cartoon')", 30)
    await settle(p)
    check('the Sample with black lines only is the coloured cartoon', True)
    check('black lines only: the red wall and the sky are not ink, the black cat is',
          not await ink(p, WALL) and not await ink(p, SKY) and await ink(p, CAT))
    await p.ev("document.querySelector('input[name=vz-ink][value=dark]').click(), 1")
    await settle(p)
    check('traced by darkness, the red wall is ink', await ink(p, WALL))
    await p.ev("document.querySelector('input[name=vz-ink][value=black]').click(), 1")
    await settle(p)
    outlines0 = await p.ev(OUTLINES)

    # Remove: hover, click, undo, redo.
    check('the tools are there with a picture', not await p.ev("document.getElementById('vz-tools').hidden"))
    await p.ev("document.querySelector('[data-tool=remove]').click(), 1")
    check('Remove is the tool, and the status says how', await p.ev("document.querySelector('[data-tool=remove]').getAttribute('aria-pressed')") == 'true' and
          (await p.ev("document.getElementById('vz-status').textContent")).startswith('Click a part'))
    sun = await at(p, SUN_RING)
    await p.mouse('mouseMoved', *sun)
    await asyncio.sleep(0.25)
    hl = await p.ev("document.getElementById('vz-hl').getAttribute('d') || ''")
    check('the part under the pointer shows in red: the sun, outline and hole', hl.count('M') == 2, hl[:50])
    await p.mouse('mousePressed', *sun, 1)
    await p.mouse('mouseReleased', *sun)
    check('a click takes the sun out at once', await p.ev(OUTLINES) == outlines0 - 2 and not await ink(p, SUN_RING))
    await settle(p)
    check('and the trace agrees', await p.ev(OUTLINES) == outlines0 - 2)
    check('the edits line says so, with Restore all', await p.ev(EDITS) == '1 part removed.')
    await p.ev("document.getElementById('vz-undo').click(), 1")
    await settle(p)
    check('Undo brings the sun back', await p.ev(OUTLINES) == outlines0 and await ink(p, SUN_RING) and await p.ev(EDITS) == '')
    await p.key('z', 'KeyZ', 'keyDown', 12, 90)
    await p.key('z', 'KeyZ', 'keyUp', 12, 90)
    await settle(p)
    check('Shift+Cmd+Z redoes it', await p.ev(OUTLINES) == outlines0 - 2)

    # A box round the two flowers on the right: every piece of them (their
    # thin petal outlines come out as several) goes, and nothing else.
    async def stems(side):
        return [await ink(p, xy) for xy in STEMS[side]]
    right_before = await stems('right')
    await p.drag(await at(p, RIGHT_FLOWERS[0]), await at(p, RIGHT_FLOWERS[1]))
    await settle(p)
    edits = await p.ev(EDITS)
    m = re.match(r'(\d+) parts removed\.$', edits)
    check('a box takes out the two flowers wholly inside it', all(right_before) and not any(await stems('right')) and m and int(m.group(1)) >= 3, edits)
    check('and nothing outside it', all(await stems('left')) and await ink(p, CAT))
    parts = int(m.group(1)) if m else 0

    # Removed parts stay out as the settings change.
    await p.ev("(() => { const r = document.getElementById('vz-weight'); r.value = 62; r.dispatchEvent(new Event('input', { bubbles: true })); })(), 1")
    await asyncio.sleep(0.3)
    await settle(p)
    check('with a heavier line weight the removed parts stay out', not await ink(p, SUN_RING) and not any(await stems('right')) and await ink(p, CAT))
    await p.ev("(() => { const r = document.getElementById('vz-weight'); r.value = 45; r.dispatchEvent(new Event('input', { bubbles: true })); })(), 1")
    await asyncio.sleep(0.3)
    await settle(p)

    # Erase across the cloud's outline.
    await p.ev("document.querySelector('[data-tool=erase]').click(), 1")
    check('Erase shows the brush size', not await p.ev("document.getElementById('vz-brushsize').hidden"))
    before = await p.ev(OUTLINES)
    a = await at(p, (CLOUD_RIM[0] - 14, CLOUD_RIM[1]))
    b = await at(p, (CLOUD_RIM[0] + 10, CLOUD_RIM[1]))
    await p.mouse('mouseMoved', *a)
    await p.mouse('mousePressed', *a, 1)
    for k in range(1, 9):
        await p.mouse('mouseMoved', a[0] + (b[0] - a[0]) * k / 8, a[1], 1)
    check('the stroke hides the drawing as it is painted', await p.ev("document.getElementById('vz-path').getAttribute('mask')") == 'url(#vz-erasing)')
    await p.mouse('mouseReleased', *b)
    await settle(p)
    check('the trace cuts the cloud open: one outline fewer, and the hiding is over',
          await p.ev(OUTLINES) == before - 1 and not await p.ev("document.getElementById('vz-path').hasAttribute('mask')"), f'{before} -> {await p.ev(OUTLINES)}')
    erased = f'{parts} parts removed, 1 stroke erased.'
    check('the edits line counts the stroke', await p.ev(EDITS) == erased, await p.ev(EDITS))
    check('dragging selected no text', await p.ev('getSelection().toString()') == '')

    # The space bar moves the picture, and does not press a focused button.
    await p.ev("document.querySelector('[data-tool=remove]').focus(), 1")
    vb = await p.ev("document.getElementById('vz-svg').getAttribute('viewBox')")
    await p.key(' ', 'Space', 'keyDown', 0, 32)
    await p.drag((1100, 400), (1140, 430), 4)
    await p.key(' ', 'Space', 'keyUp', 0, 32)
    await asyncio.sleep(0.1)
    check('the space bar held: a drag moves the picture and erases nothing',
          await p.ev("document.getElementById('vz-svg').getAttribute('viewBox')") != vb and await p.ev(EDITS) == erased)
    check('and does not press the focused Remove button', await p.ev("document.querySelector('[data-tool=erase]').getAttribute('aria-pressed')") == 'true')
    await p.ev("document.getElementById('vz-fit').click(), 1")
    await p.key('Escape', 'Escape', 'keyDown', 0, 27)
    await p.key('Escape', 'Escape', 'keyUp', 0, 27)
    check('Escape goes back to Move', await p.ev("document.querySelector('[data-tool=move]').getAttribute('aria-pressed')") == 'true')

    # What is saved, and what the Black & white view shows, has the edits.
    await p.ev("""(() => { window.__svg = null; const own = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function () { window.__svg = fetch(this.href).then(r => r.text()); HTMLAnchorElement.prototype.click = own; }; })(), 1""")
    await p.ev("document.getElementById('vz-download').click(), 1")
    svg = await p.ev('window.__svg')
    d = await p.ev("document.getElementById('vz-path').getAttribute('d')")
    check('Download SVG has the edited drawing', bool(svg) and f'd="{d}"' in svg)
    await p.ev("document.getElementById('vz-mode-prepared').click(), 1")
    await settle(p)
    await asyncio.sleep(0.2)
    white = await p.ev(f"""(() => {{
      const c = document.getElementById('vz-canvas'), r = c.getBoundingClientRect(), v = document.getElementById('vz-pane-vec').getBoundingClientRect();
      const [x, y] = {SCREEN}({SUN_RING[0]}, {SUN_RING[1]});
      return c.getContext('2d').getImageData(Math.round(x - v.left), Math.round(y - v.top), 1, 1).data[0]; }})()""")
    check('the Black & white view shows the removed sun as paper', white > 200, white)
    await p.ev("document.getElementById('vz-mode-original').click(), 1")

    # Restore all, and undo it.
    await p.ev("document.getElementById('vz-restore').click(), 1")
    await settle(p)
    check('Restore all brings everything back', await p.ev(OUTLINES) == outlines0 and await p.ev(EDITS) == '')
    await p.ev("document.getElementById('vz-undo').click(), 1")
    await settle(p)
    check('and can be undone', await p.ev(EDITS) == erased)

    # A tap on a touch screen.
    await p.ev("document.querySelector('[data-tool=remove]').click(), 1")
    cat = await at(p, CAT)
    await p.call('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': cat[0], 'y': cat[1]}]})
    await p.call('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
    await settle(p)
    check('a tap with Remove takes the cat out', not await ink(p, CAT) and await p.ev(EDITS) == f'{parts + 1} parts removed, 1 stroke erased.', await p.ev(EDITS))

    # Kept over a reload; an old tick for light lines.
    await p.reload()
    check('black lines only is kept over a reload', await p.ev("document.querySelector('input[name=vz-ink]:checked').value") == 'black')
    await p.ev("localStorage.setItem('vectorize.settings', JSON.stringify({ invert: true, detail: 2 })), 1")
    await p.reload()
    check('an old Light lines tick becomes that choice', await p.ev("document.querySelector('input[name=vz-ink]:checked').value") == 'light')
    await p.ev("localStorage.removeItem('vectorize.settings'), 1")


if __name__ == '__main__':
    asyncio.run(main())
