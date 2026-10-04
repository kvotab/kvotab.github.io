"""rdc.html's circles filling from the chart without the chain blinking.

With the chart set to compare data on hover, the pointer's place on the time
axis fills each nuclide's circle with its share of the chain at that time. The
fill and the label were one SVG picture, drawn again for every level, and
cytoscape draws a circle whose picture has not decoded yet without it: no fill
and no text for a frame. A sweep along the chart changed every level many
times a second, and about every second frame of every circle was blank.

The fill is now one picture per theme that the level slides up and down, and
the label one per nuclide and theme. The sweep here counts the draws of a
circle whose pictures were not decoded at that moment (there must be none),
and the pictures cytoscape holds (the sweep must not add any; it used to add
one per circle per step).

Plotly answers each step of the pointer with an unhover for the points it
leaves and a hover for the ones it reaches, and the page used to restyle every
circle's border on both. That is counted too: in compare mode the same
nuclides stay lit, so a sweep relights at most one round of them.

The levels glide to the point under the pointer instead of jumping at Plotly's
20 reports a second, and jump when the system asks for reduced motion. Both
are checked, and that they land on the shares of the points Plotly reports,
that leaving the chart brings back the shares at the start, that the closest
mode lights one curve's nuclide at a time, and, in the screenshot, that the
fill's edge sits where the level says, in both themes.

Serve the repository and start headless Chrome (the recipe is in README.md),
by default on ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose
others. Exit status is 0 when every check passes.
"""
import asyncio, base64, io, json, os, sys, time, urllib.request
import websockets
from PIL import Image

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))

ERRORS = """window.__errors = [];
addEventListener('error', e => window.__errors.push(String(e.message)));
addEventListener('unhandledrejection', e => window.__errors.push('rejected: ' + e.reason));"""

# U-238 alone at the start, over a million years: every daughter's share rises
# from nothing, so the levels move all along the axis.
SETUP = """(async () => {
  CY.getElementById('U-238').data('IC', 1);
  updateLevel('IC');
  document.getElementById('timeinput').value = '1e6';
  document.getElementById('timeunit').value = 'year';
  runAndUpdateChart();
  await new Promise(r => setTimeout(r, 1000));
  return JSON.stringify({
    open: !!$('#chartdialog').dialog('isOpen'),
    traces: CHARTDIALOG[0].data.map(t => t.name) });
})()"""

# What cytoscape draws and holds, and how often the page restyles a border.
INSTRUMENT = """(() => {
  const r = CY.renderer(), draw = r.drawNode;
  window.__seen = { draws: 0, blank: 0, borders: 0 };
  r.drawNode = function (context, node) {
    const urls = node.pstyle('background-image').value || [];
    const cache = r.imageCache || {};
    if (urls.some(u => u && u !== 'none' && !(cache[u] && cache[u].image.complete))) window.__seen.blank++;
    window.__seen.draws++;
    return draw.apply(this, arguments);
  };
  const border = window.styleBorder;
  window.styleBorder = function () { window.__seen.borders++; return border.apply(this, arguments); };
  return true;
})()"""

SEEN = """JSON.stringify(Object.assign({}, window.__seen, {
  images: Object.keys(CY.renderer().imageCache || {}).length }))"""

RESET_SEEN = "Object.assign(window.__seen, { draws: 0, blank: 0, borders: 0 }); true"

# Shown levels, targets, who is lit, and the shares of what Plotly is hovering.
# Tolerates a page without the targets and the frame, so that one is reported
# rather than raising on the first read.
STATE = """JSON.stringify((() => {
  const nuclides = CY.nodes().filter(n => n.data('Z') !== 0);
  const targets = typeof levelTargets === 'undefined' ? null : levelTargets;
  const out = { level: {}, target: {}, lit: [], hovered: null,
                frame: typeof levelFrame === 'undefined' ? 'no frame on the page' : levelFrame };
  nuclides.forEach(n => {
    out.level[n.id()] = +n.data('level') || 0;
    if (targets && targets[n.id()] !== undefined) out.target[n.id()] = targets[n.id()];
    if (Number(n.style('background-opacity')) < 1) out.lit.push(n.id());
  });
  const points = CHARTDIALOG[0]._hoverdata;
  if (points && points.length) {
    const total = points.reduce((s, p) => s + p.y, 0);
    out.hovered = {};
    points.forEach(p => { out.hovered[p.data.name] = total > 0 ? p.y / total : 0; });
  }
  return out;
})())"""

PLOT_BOX = """JSON.stringify((() => {
  const r = CHARTDIALOG[0].querySelector('.nsewdrag').getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
})())"""

BUTTON = """JSON.stringify((() => {
  const b = CHARTDIALOG[0].querySelector('.modebar-btn[data-attr="hovermode"][data-val="%s"]');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const under = document.elementFromPoint(x, y);
  return { x: x, y: y, reaches: !!under && (under === b || b.contains(under)) };
})())"""

# Where a nuclide's circle is on the screen, with its label picture hidden so
# that only the fill and the background are left in it.
CIRCLE = """(async (id) => {
  const n = CY.getElementById(id);
  CY.zoom(1.5); CY.center(n);
  n.style('background-image-opacity', [1, 0]);
  await new Promise(r => setTimeout(r, 400));
  const box = document.getElementById('cy').getBoundingClientRect();
  const p = n.renderedPosition();
  const x = box.left + p.x, y = box.top + p.y, h = n.renderedHeight();
  const under = document.elementFromPoint(x, y);
  return JSON.stringify({ x: x, y: y, h: h, level: +n.data('level'),
                          visible: !!under && document.getElementById('cy').contains(under) });
})"""

FILL = {'light': (255, 244, 163), 'dark': (90, 69, 32)}


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

        async def ev(expression, session):
            reply = await cmd('Runtime.evaluate',
                              {'expression': expression, 'awaitPromise': True,
                               'returnByValue': True, 'timeout': 30000}, session)
            result = reply.get('result', {})
            if 'exceptionDetails' in result:
                raise AssertionError('page threw: ' + json.dumps(result['exceptionDetails'])[:300])
            return result.get('result', {}).get('value')

        async def state(session):
            return json.loads(await ev(STATE, session))

        async def move(session, x, y):
            await cmd('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y}, session)

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
        try:
            await cmd('Runtime.enable', {}, session)
            await cmd('Page.enable', {}, session)
            await cmd('Network.enable', {}, session)
            await cmd('Network.setCacheDisabled', {'cacheDisabled': True}, session)
            await cmd('Page.addScriptToEvaluateOnNewDocument', {'source': ERRORS}, session)
            await cmd('Emulation.setDeviceMetricsOverride',
                      {'width': 1400, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False}, session)
            await cmd('Page.navigate',
                      {'url': 'http://127.0.0.1:%d/rdc.html?n=%d' % (HTTP, int(time.time() * 1000))},
                      session)
            await asyncio.sleep(7)

            setup = json.loads(await ev(SETUP, session))
            check(setup['open'] and len(setup['traces']) > 10,
                  'U-238 with an inventory should open the chart with its chain, got %r' % (setup,))
            nuclides = setup['traces']

            # ── Compare data on hover, with the real button ──────────────────
            button = json.loads(await ev(BUTTON % 'x', session) or 'null')
            check(button is not None and button['reaches'],
                  'the chart should have a reachable "Compare data on hover" button, got %r' % (button,))
            if button:
                await move(session, button['x'], button['y'])
                for kind in ('mousePressed', 'mouseReleased'):
                    await cmd('Input.dispatchMouseEvent',
                              {'type': kind, 'x': button['x'], 'y': button['y'],
                               'button': 'left', 'clickCount': 1}, session)
                await asyncio.sleep(0.5)
            mode = await ev('CHARTDIALOG[0]._fullLayout.hovermode', session)
            check(mode == 'x', 'the button should set the chart to compare, got %r' % (mode,))

            # ── A sweep along the time axis ──────────────────────────────────
            plot = json.loads(await ev(PLOT_BOX, session))
            await ev(INSTRUMENT, session)
            before = json.loads(await ev(SEEN, session))
            seen_levels = []
            steps = 100
            for i in range(steps + 1):
                await move(session, plot['x'] + 4 + (plot['w'] - 8) * i / steps, plot['y'] + plot['h'] / 2)
                await asyncio.sleep(0.02)
                # From the first report on: before it, U-238 holds the whole start
                if i % 10 == 0 and i > 0:
                    seen_levels.append((await state(session))['level'].get('U-238', 0))
            await asyncio.sleep(0.6)
            after = json.loads(await ev(SEEN, session))
            check(max(seen_levels) - min(seen_levels) > 0.2,
                  "U-238's circle should empty as its daughters grow along the sweep, "
                  'its levels were %r' % ([round(v, 3) for v in seen_levels],))
            check(after['draws'] > 10 * len(nuclides),
                  'the sweep should have redrawn the chain many times, got %d draws' % after['draws'])
            check(after['blank'] == 0,
                  '%d of %d circle draws had no decoded picture: each is a frame with that circle '
                  'blank' % (after['blank'], after['draws']))
            check(after['images'] == before['images'],
                  'a level is not a new picture: the sweep took the cache from %d pictures to %d'
                  % (before['images'], after['images']))
            check(after['borders'] <= len(nuclides),
                  'in compare mode the same nuclides stay lit, yet the sweep restyled %d borders '
                  'for %d nuclides' % (after['borders'], len(nuclides)))

            rest = await state(session)
            hovered = rest['hovered'] or {}
            check(len(hovered) == len(nuclides),
                  'compare mode should report every curve under the pointer, got %d of %d'
                  % (len(hovered), len(nuclides)))
            off = {k: (round(rest['level'].get(k, 0), 5), round(v, 5)) for k, v in hovered.items()
                   if abs(rest['level'].get(k, 0) - v) > 1e-3}
            check(not off, 'at rest the circles should hold the shares under the pointer '
                           '(shown, share): %r' % (off,))
            check(rest['frame'] == 0, 'with every level arrived the page should stop asking for frames')
            check(sorted(rest['lit']) == sorted(nuclides),
                  'every curve under the pointer should light its nuclide, lit: %r' % (rest['lit'],))

            # ── Leaving the chart ────────────────────────────────────────────
            await move(session, plot['x'] - 300, plot['y'] - 20)
            await asyncio.sleep(0.6)
            left = await state(session)
            check(left['lit'] == [], 'leaving the chart should put every nuclide out, lit: %r' % (left['lit'],))
            start = {k: (1.0 if k == 'U-238' else 0.0) for k in nuclides}
            off = {k: round(left['level'].get(k, 0), 5) for k, v in start.items()
                   if abs(left['level'].get(k, 0) - v) > 1e-3}
            check(not off, 'and the circles should go back to the shares at the start: %r' % (off,))

            # ── Closest data on hover: one curve at a time ───────────────────
            button = json.loads(await ev(BUTTON % 'closest', session) or 'null')
            if button:
                await move(session, button['x'], button['y'])
                for kind in ('mousePressed', 'mouseReleased'):
                    await cmd('Input.dispatchMouseEvent',
                              {'type': kind, 'x': button['x'], 'y': button['y'],
                               'button': 'left', 'clickCount': 1}, session)
                await asyncio.sleep(0.5)
            mode = await ev('CHARTDIALOG[0]._fullLayout.hovermode', session)
            check(mode == 'closest', 'the closest button should set the chart to closest, got %r' % (mode,))
            many, reported, moved = [], 0, []
            for i in range(12):
                for j in range(3):
                    await move(session, plot['x'] + plot['w'] * (0.1 + 0.07 * i),
                               plot['y'] + plot['h'] * (0.2 + 0.3 * j))
                    await asyncio.sleep(0.12)
                    now = await state(session)
                    if now['hovered']:
                        reported += 1
                    if len(now['lit']) > 1:
                        many.append(now['lit'])
                    wrong = {k: v for k, v in now['target'].items() if abs(v - start.get(k, 0)) > 1e-9}
                    if wrong:
                        moved.append(wrong)
            check(reported > 0, 'the closest mode should have hovered a curve somewhere in the plot')
            check(not many, 'one curve under the pointer lights one nuclide, got %r' % (many[:3],))
            check(not moved, 'a single curve says nothing about shares: the circles keep the start, '
                             'got targets %r' % (moved[:2],))
            await move(session, plot['x'] - 300, plot['y'] - 20)
            await asyncio.sleep(0.6)

            # ── Gliding, and jumping when reduced motion is asked for ────────
            glide = """(async () => {
              updateLevel('level', ['U-238', 'Th-234'], [%s, %s]);
              await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
              return +CY.getElementById('U-238').data('level');
            })()"""
            first = await ev(glide % (1, 3), session)
            await asyncio.sleep(0.6)
            check(0.25 < first < 1,
                  'one frame in, the fill should be part of the way from 1 to 0.25, got %r' % (first,))
            await cmd('Emulation.setEmulatedMedia',
                      {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]}, session)
            jumped = await ev(glide % (3, 1), session)
            check(abs(jumped - 0.75) < 1e-12,
                  'with reduced motion asked for, the fill should be there one frame in, got %r' % (jumped,))
            await cmd('Emulation.setEmulatedMedia', {'features': []}, session)

            # ── The fill's edge is where the level says ──────────────────────
            await ev("$('#chartdialog').dialog('close')", session)
            for theme in ('light', 'dark'):
                await ev("document.documentElement.setAttribute('data-theme', '%s')" % theme, session)
                await ev("updateLevel('level', ['U-238', 'Th-234'], [3, 7])", session)
                await asyncio.sleep(0.8)
                for nuclide in ('U-238', 'Th-234'):
                    circle = json.loads(await ev('(%s)(%s)' % (CIRCLE, json.dumps(nuclide)), session))
                    check(circle['visible'], '%s should be in view for the picture' % nuclide)
                    top = circle['y'] - circle['h'] / 2
                    shot = await cmd('Page.captureScreenshot',
                                     {'format': 'png', 'clip': {'x': circle['x'] - 1, 'y': top,
                                                                'width': 2, 'height': circle['h'],
                                                                'scale': 1}}, session)
                    image = Image.open(io.BytesIO(base64.b64decode(shot['result']['data']))).convert('RGB')
                    column = [image.getpixel((0, row)) for row in range(image.height)]
                    fill = [row for row, rgb in enumerate(column)
                            if max(abs(a - b) for a, b in zip(rgb, FILL[theme])) <= 6]
                    expected = (1 - circle['level']) * circle['h']
                    edge = fill[0] if fill else None
                    check(edge is not None and abs(edge - expected) <= 1.5,
                          '%s, %s at %.2f: the fill should start %.1f px down the circle, '
                          'it starts at %r' % (theme, nuclide, circle['level'], expected, edge))
                    check(bool(fill) and fill[-1] - fill[0] + 1 >= 0.9 * (circle['h'] - expected) - 3,
                          '%s, %s: the fill should run unbroken to the bottom of the circle, rows %r'
                          % (theme, nuclide, (fill[0], fill[-1], len(fill)) if fill else None))
                    await ev("CY.getElementById(%s).removeStyle('background-image-opacity')"
                             % json.dumps(nuclide), session)

            errors = await ev('window.__errors', session)
            check(errors == [], 'the page should raise nothing, got %r' % (errors,))
        finally:
            await cmd('Target.closeTarget', {'targetId': target})

        if failures:
            print('%d of %d check(s) failed:' % (len(failures), len(failures) + passed[0]))
            for failure in failures:
                print('  - ' + failure)
            sys.exit(1)
        print('%d checks passed: the circles fill from the chart without a blank frame, '
              'glide to the shares under the pointer and sit where the level says.' % passed[0])


asyncio.run(main())
