"""Prove the SL boards only call the network while somebody could be looking.

The positions endpoint is asked every three seconds and is paid for out of a
Trafiklab quota, so a board nobody is watching is a board spending money for
nothing. Three separate things are supposed to stop it - a backgrounded tab,
the board scrolled out of the viewport, and a visitor who has gone quiet - and
each is a different mechanism, so each is checked on its own by counting the
fetches the page actually makes rather than by reading its state.

The fetch stub is installed with Page.addScriptToEvaluateOnNewDocument, which
runs before the page's own scripts; installed after load it would race the
board's first fetch and undercount.
"""
import asyncio, json, sys, time, urllib.request, websockets

PAGE = 'uppsala.html'

STUB = r"""
(() => {
  window.__slCalls = { dep: 0, veh: 0 };
  try { localStorage.setItem('kvot-sl-trains', 'https://stub.invalid/trains'); } catch (e) {}
  /* Three departures, built relative to the moment the page loads: two within
     the hour and one ten hours out. The third is what the board used to hide,
     because a three-hour forecast window could not see it.

     Ten hours, not "tomorrow at 04:26": a twenty-hour window cannot reach the
     next calendar day at all when the clock has just passed midnight, so a
     fixed wall-clock time made this test pass or fail by time of day. Ten
     hours is always inside the window, and whether it lands on another date
     depends on the hour - which is why the day label is checked against the
     date the stub actually produced rather than against a guess. SL's times
     are zone-less local strings. */
  const pad = (n) => String(n).padStart(2, '0');
  const local = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  /* The real API honours `forecast`, and a stub that does not would let a
     three-hour window pass a test about showing a departure sixteen hours
     out. It takes the window from the URL, like the real one. */
  window.__slDepartures = (forecastMin) => {
    const now = new Date();
    const soon = new Date(now.getTime() + 12 * 60000);
    const later = new Date(now.getTime() + 42 * 60000);
    const distant = new Date(now.getTime() + 10 * 3600 * 1000);
    /* What the page will have to say about that third one, decided here from
       the same dates the board will see. */
    window.__slCrossesMidnight = distant.getDate() !== now.getDate();
    const horizon = now.getTime() + (forecastMin || 60) * 60000;
    return [soon, later, distant].filter((w) => w.getTime() <= horizon).map((when, i) => ({
      destination: 'Stockholm City',
      direction_code: 1,
      state: 'EXPECTED',
      scheduled: local(when),
      expected: local(when),
      line: { designation: '40' },
      journey: { id: `${when.getFullYear()}${pad(when.getMonth() + 1)}${pad(when.getDate())}${String(2270 + i).padStart(5, '0')}` },
      stop_point: { designation: '1' },
      deviations: [],
    }));
  };
  const real = window.fetch;
  const json = (body) => Promise.resolve(new Response(JSON.stringify(body),
    { status: 200, headers: { 'Content-Type': 'application/json' } }));
  window.fetch = function (input) {
    const url = String((input && input.url) || input || '');
    if (url.indexOf('/trains') >= 0) {
      window.__slCalls.veh++;
      return json({ timestamp: Math.floor(Date.now() / 1000), count: 0, trains: [] });
    }
    if (url.indexOf('transport.integration.sl.se') >= 0) {
      window.__slCalls.dep++;
      const forecast = Number((/[?&]forecast=(\d+)/.exec(url) || [])[1]) || 60;
      return json({ departures: window.__slDepartures(forecast), stopDeviations: [] });
    }
    return real.apply(this, arguments);
  };
})();
"""


class Session:
    def __init__(self, ws, sid):
        self.ws, self.sid, self.n = ws, sid, 100

    async def call(self, method, params=None):
        self.n += 1
        mid = self.n
        msg = {'id': mid, 'method': method, 'sessionId': self.sid}
        if params: msg['params'] = params
        await self.ws.send(json.dumps(msg))
        while True:
            m = json.loads(await self.ws.recv())
            if m.get('id') == mid:
                return m

    async def js(self, expr):
        m = await self.call('Runtime.evaluate',
                            {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
        r = m.get('result', {}).get('result', {})
        if 'value' not in r:
            raise RuntimeError('JS failed: ' + json.dumps(m)[:500])
        return r['value']


STATE = r"""JSON.stringify((() => {
  const h = document.getElementById('board').__slBoard;
  /* Tolerant of a board that has none of these, so this file can be run
     against an older sl-board.js and report failures rather than crash. */
  return { dep: window.__slCalls.dep, veh: window.__slCalls.veh,
           polling: typeof h.polling === 'boolean' ? h.polling : null,
           paused: h.paused === undefined ? null : h.paused,
           active: typeof h.isActive === 'function' ? h.isActive() : null,
           live: document.querySelector('#board .sl-live').textContent,
           greyed: document.getElementById('board').classList.contains('sl-paused') };
})())"""


async def state(s):
    return json.loads(await s.js(STATE))


def check(results, label, ok, detail):
    results.append((label, ok, detail))
    print('  %-46s %-5s %s' % (label, 'PASS' if ok else 'FAIL', detail))


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    results = []
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as ws:
        await ws.send(json.dumps({'id': 1, 'method': 'Target.createTarget',
                                  'params': {'url': 'about:blank'}}))
        tid = None
        while tid is None:
            m = json.loads(await ws.recv())
            if m.get('id') == 1: tid = m['result']['targetId']
        await ws.send(json.dumps({'id': 2, 'method': 'Target.attachToTarget',
                                  'params': {'targetId': tid, 'flatten': True}}))
        sid = None
        while sid is None:
            m = json.loads(await ws.recv())
            if m.get('id') == 2: sid = m['result']['sessionId']
        s = Session(ws, sid)

        await s.call('Page.enable')
        await s.call('Runtime.enable')
        # The page URL is cache-busted but its stylesheet and script are not,
        # so without this Chrome happily serves the previous run's sl-board.js
        # against the current sl-board.css. That produced one baffling failure
        # where the synthetic cell checks passed and the live clock still
        # jittered: new CSS, old JS.
        await s.call('Network.enable')
        await s.call('Network.setCacheDisabled', {'cacheDisabled': True})
        await s.call('Emulation.setDeviceMetricsOverride',
                     {'width': 1000, 'height': 700, 'deviceScaleFactor': 1, 'mobile': False})
        await s.call('Page.addScriptToEvaluateOnNewDocument', {'source': STUB})
        await s.call('Page.navigate',
                     {'url': 'http://127.0.0.1:8765/%s?nocache=%d' % (PAGE, int(time.time() * 1000))})
        await asyncio.sleep(4)

        print('\n1. Watched board polls')
        a = await state(s)
        await asyncio.sleep(8)
        b = await state(s)
        check(results, 'positions polled while watched', b['veh'] - a['veh'] >= 2,
              '%d calls in 8s' % (b['veh'] - a['veh']))
        check(results, 'board reports itself active', b['active'] is True and b['polling'] is True, str(b['live']))
        check(results, 'not greyed while live', not b['greyed'], '')

        print('\n2. Scrolled out of the viewport')
        await s.js("document.body.insertAdjacentHTML('beforeend',"
                   "'<div id=spacer style=height:4000px></div>'); window.scrollTo(0, 4200); 'ok'")
        await asyncio.sleep(1.0)
        c = await state(s)
        await asyncio.sleep(4)
        d = await state(s)
        check(results, 'polling stops off-screen', d['polling'] is False, 'polling=%s' % d['polling'])
        check(results, 'no vehicle calls off-screen', d['veh'] == c['veh'],
              '%d calls in 4s' % (d['veh'] - c['veh']))
        check(results, 'no departure calls off-screen', d['dep'] == c['dep'],
              '%d calls in 4s' % (d['dep'] - c['dep']))
        check(results, 'reason is "not in view"', d['paused'] == 'not in view', repr(d['paused']))
        check(results, 'board greyed while paused', d['greyed'], '')
        check(results, 'says it is paused', 'Paused' in (d['live'] or ''), repr(d['live']))

        print('\n3. Scrolled back')
        await s.js("window.scrollTo(0, 0); 'ok'")
        await asyncio.sleep(1.0)
        e = await state(s)
        check(results, 'resumes on returning to view', e['polling'] is True, 'polling=%s' % e['polling'])
        check(results, 'refetches at once, not on the next tick', e['veh'] > d['veh'],
              '%d new calls' % (e['veh'] - d['veh']))
        check(results, 'grey removed', not e['greyed'], '')

        print('\n4. Tab backgrounded')
        await s.js("Object.defineProperty(document, 'hidden', {configurable: true, get: () => true});"
                   "Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'});"
                   "document.dispatchEvent(new Event('visibilitychange')); 'ok'")
        await asyncio.sleep(0.4)
        f = await state(s)
        await asyncio.sleep(4)
        g = await state(s)
        check(results, 'polling stops when hidden', g['polling'] is False, 'polling=%s' % g['polling'])
        check(results, 'no calls while hidden', g['veh'] == f['veh'],
              '%d calls in 4s' % (g['veh'] - f['veh']))
        await s.js("Object.defineProperty(document, 'hidden', {configurable: true, get: () => false});"
                   "Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'visible'});"
                   "document.dispatchEvent(new Event('visibilitychange')); 'ok'")
        await asyncio.sleep(0.6)
        h = await state(s)
        check(results, 'resumes when shown again', h['polling'] is True and h['veh'] > g['veh'],
              '%d new calls' % (h['veh'] - g['veh']))

        print('\n5. Visitor goes quiet (idleMs 1500)')
        await s.js("""(() => {
          const root = document.getElementById('board');
          const cfg = Object.assign({}, root.__slBoard.config, { idleMs: 1500 });
          root.__slBoard.stop();
          KVOT_SL.mountBoard(root, cfg);
          return 'ok';
        })()""")
        await asyncio.sleep(1.0)
        i = await state(s)
        check(results, 'remounted board polls at first', i['polling'] is True, 'polling=%s' % i['polling'])
        # No input is dispatched here, so the board should time itself out.
        await asyncio.sleep(3.5)
        j = await state(s)
        check(results, 'polling stops when idle', j['polling'] is False, 'polling=%s' % j['polling'])
        check(results, 'reason is "idle"', j['paused'] == 'idle', repr(j['paused']))
        k = await state(s)
        await asyncio.sleep(3)
        l = await state(s)
        check(results, 'stays stopped while idle', l['veh'] == k['veh'],
              '%d calls in 3s' % (l['veh'] - k['veh']))

        print('\n6. A real mouse move wakes it')
        await s.call('Input.dispatchMouseEvent',
                     {'type': 'mouseMoved', 'x': 400, 'y': 300, 'button': 'none', 'clickCount': 0})
        await asyncio.sleep(0.8)
        m2 = await state(s)
        check(results, 'resumes on pointer movement', m2['polling'] is True, 'polling=%s' % m2['polling'])
        check(results, 'refetches on waking', m2['veh'] > l['veh'], '%d new calls' % (m2['veh'] - l['veh']))
        check(results, 'no longer greyed', not m2['greyed'], repr(m2['live']))

        print('\n7. idleMs 0 disables the idle gate')
        await s.js("""(() => {
          const root = document.getElementById('board');
          const cfg = Object.assign({}, root.__slBoard.config, { idleMs: 0 });
          root.__slBoard.stop();
          KVOT_SL.mountBoard(root, cfg);
          return 'ok';
        })()""")
        await asyncio.sleep(0.5)
        n1 = await state(s)
        await asyncio.sleep(8)
        n2 = await state(s)
        check(results, 'unattended board keeps polling', n2['polling'] is True, 'polling=%s' % n2['polling'])
        check(results, 'still fetching after quiet 8s', n2['veh'] - n1['veh'] >= 2,
              '%d calls in 8s' % (n2['veh'] - n1['veh']))

        print('\n8. Direction, and the third departure')
        board = json.loads(await s.js("""JSON.stringify((() => {
          const hero = document.querySelector('.sl-hero');
          const rows = [...document.querySelectorAll('.sl-row')];
          const unit = (el) => (el.querySelector('small') || {}).textContent || '';
          return {
            /* A bearing within a right angle of the segment means the train is
               heading for the far end. The inline version of this read
               `diff > 90` and drew every unnamed train backwards. */
            forward: [
              [0, 0], [10, 350], [350, 10], [89, 0],
              [91, 0], [180, 0], [270, 0], [200, 10]
            ].map(([b, seg]) => KVOT_SL.runsForward(b, seg)),
            noBearing: KVOT_SL.runsForward(null, 0),
            forecast: document.querySelector('.sl-board').__slBoard.config.forecast,
            corridorKm: KVOT_SL.GPS_CORRIDOR_KM,
            count: (hero ? 1 : 0) + rows.length,
            heroUnit: hero ? (hero.querySelector('.sl-count-small') || {}).textContent : null,
            lastUnit: rows.length ? unit(rows[rows.length - 1].querySelector('.sl-row-count')) : null,
            crossesMidnight: window.__slCrossesMidnight
          };
        })())"""))
        # First four bearings agree with the segment, last four oppose it.
        check(results, 'direction from bearing is not inverted',
              board['forward'] == [True, True, True, True, False, False, False, False],
              str(board['forward']))
        check(results, 'a train with no bearing is not flipped', board['noBearing'] is True,
              str(board['noBearing']))
        check(results, 'forecast window reaches past a quiet night', board['forecast'] >= 600,
              '%s minutes' % board['forecast'])
        check(results, 'corridor is tight enough to exclude the next track',
              board['corridorKm'] <= 1.5, '%s km' % board['corridorKm'])
        check(results, 'all three departures are shown', board['count'] == 3,
              '%s shown (1 hero + %s rows)' % (board['count'], board['count'] - 1))
        # A departure ten hours out is past the hour mark, so it shows a clock
        # time; whether that carries a day label depends on whether it crossed
        # midnight, which the stub recorded when it built it.
        unit = board['lastUnit'] or ''
        if board['crossesMidnight']:
            check(results, "a departure on another date says tomorrow",
                  'tomorrow' in unit, repr(unit))
        else:
            check(results, "a departure later today carries no day label",
                  'tomorrow' not in unit and 'day' not in unit,
                  '%r (stub stayed on today)' % unit)

        print('\n9. The live dot holds its position')
        # Two independent things move next to the dot, and the first version of
        # this section only tested one of them: it stopped the board to hold
        # the status text still, which stopped the clock as well. The clock is
        # the worse offender - see below - so it is sampled first, with the
        # board running and the seconds really ticking.
        samples = []
        for _ in range(12):
            samples.append(json.loads(await s.js("""JSON.stringify((() => {
              const live = document.querySelector('#sl-live');
              const clock = document.querySelector('#sl-clock');
              const meta = document.querySelector('.sl-meta');
              const l = live.getBoundingClientRect();
              /* Everything that could move the dot is recorded beside it, so a
                 failure says which one did rather than needing a rerun. */
              return { dotX: Math.round(l.right * 10) / 10,
                       clock: clock.textContent,
                       cells: clock.childElementCount,
                       clockW: Math.round(clock.getBoundingClientRect().width * 100) / 100,
                       liveW: Math.round(l.width * 100) / 100,
                       metaW: Math.round(meta.getBoundingClientRect().width * 100) / 100 };
            })())""")))
            await asyncio.sleep(1.05)
        ticked = len({x['clock'] for x in samples})
        xs = sorted({x['dotX'] for x in samples})
        check(results, 'clock actually ticked during the sample', ticked >= 8,
              '%d distinct times in 12 reads' % ticked)
        if len(xs) == 1:
            detail = 'fixed at %.1f' % xs[0]
        else:
            moved = [k for k in ('clockW', 'liveW', 'metaW', 'cells')
                     if len({x[k] for x in samples}) > 1]
            detail = 'swings %.1fpx across %s; also varying: %s' % (
                xs[-1] - xs[0], xs, ', '.join(moved) or 'nothing measured')
        check(results, 'dot holds still while the clock runs', len(xs) == 1, detail)

        # Now the status text, with the board stopped so the tick cannot
        # overwrite what is set here. The dot is #sl-live's ::after, so it sits
        # at the element's RIGHT edge - that is the edge that has to hold
        # still. The left edge is expected to move: the text grows from it.
        dot = json.loads(await s.js("""JSON.stringify((() => {
          const live = document.querySelector('#sl-live');
          const clock = document.querySelector('#sl-clock');
          document.querySelector('.sl-board').__slBoard.stop();
          const out = [];
          for (const t of ['Last update 23:45 \u2014 retrying', 'Paused \u2014 not in view',
                           'Paused \u2014 idle', 'No connection', 'Updated 118s ago',
                           'Updated 12s ago', 'Updating\u2026', 'Live']) {
            live.textContent = t;
            const r = live.getBoundingClientRect(), c = clock.getBoundingClientRect();
            out.push({ text: t, dotX: Math.round(r.right * 10) / 10,
                       textLeft: Math.round(r.left * 10) / 10,
                       clockRight: Math.round(c.right * 10) / 10 });
          }
          return out;
        })())"""))
        xs = sorted({r['dotX'] for r in dot})
        cs = sorted({r['clockRight'] for r in dot})
        check(results, 'dot does not move as the text changes', len(xs) == 1,
              ('fixed at %.1f' % xs[0]) if len(xs) == 1 else 'swings %.1fpx across %s' % (xs[-1] - xs[0], xs))
        check(results, 'clock does not move either', len(cs) == 1,
              ('fixed at %.1f' % cs[0]) if len(cs) == 1 else 'moves %s' % cs)
        ls = sorted({r['textLeft'] for r in dot})
        check(results, 'text still grows leftwards from the dot', len(ls) > 1,
              '%d distinct left edges, %.1fpx span' % (len(ls), ls[-1] - ls[0]))

        # The extremes the 12-second sample cannot reach. This font has no
        # tabular figures - "1" is 2.22px where "3" and "8" are 6.02px - so
        # hh:mm:ss once swung 22.5px between 11:11:11 and 23:33:33. The cells
        # are what make every time the same width; this asserts that contract
        # between the class names the JS writes and the widths the CSS gives.
        cells = json.loads(await s.js("""JSON.stringify((() => {
          const clock = document.querySelector('#sl-clock');
          const paint = (t) => {
            clock.textContent = '';
            for (const ch of t) {
              const cell = document.createElement('span');
              cell.className = ch === ':' ? 'sl-clock-sep' : 'sl-clock-digit';
              cell.textContent = ch;
              clock.appendChild(cell);
            }
            return Math.round(clock.getBoundingClientRect().width * 100) / 100;
          };
          const widths = {};
          for (const t of ['11:11:11', '23:33:33', '00:00:00', '08:58:38', '19:30:00'])
            widths[t] = paint(t);
          paint('23:33:33');
          const digitCells = [...clock.querySelectorAll('.sl-clock-digit')]
            .map((c) => Math.round(c.getBoundingClientRect().width * 100) / 100);
          return { widths, digitCells };
        })())"""))
        ws_ = sorted(set(cells['widths'].values()))
        check(results, 'every possible time is the same width', len(ws_) == 1,
              ('%.2fpx for all' % ws_[0]) if len(ws_) == 1
              else 'spread %.2fpx %s' % (ws_[-1] - ws_[0], cells['widths']))
        ds = sorted(set(cells['digitCells']))
        check(results, 'digit cells are uniform', len(ds) == 1,
              ('%.2fpx each' % ds[0]) if len(ds) == 1 else 'differ %s' % ds)

        print('\n10. On a phone the panel is the page')
        # Pure CSS, so the viewport can simply be resized - media queries
        # re-evaluate without a reload, and the board is already stopped.
        async def layout(w, h):
            await s.call('Emulation.setDeviceMetricsOverride',
                         {'width': w, 'height': h, 'deviceScaleFactor': 1, 'mobile': w < 600})
            await asyncio.sleep(0.4)
            return json.loads(await s.js("""JSON.stringify((() => {
              const b = document.querySelector('.sl-board').getBoundingClientRect();
              const intro = document.querySelector('.sl-intro');
              /* This site has twice shipped a padded content-box that widened
                 the layout viewport, so scrollWidth agreed while the element
                 stuck out. Measure elements against innerWidth instead. */
              const widest = [...document.querySelectorAll('.sl-wrap *')]
                .reduce((m, el) => Math.max(m, Math.round(el.getBoundingClientRect().right)), 0);
              return { vw: innerWidth,
                       left: Math.round(b.left), right: Math.round(b.right), top: Math.round(b.top),
                       introShown: intro ? getComputedStyle(intro).display !== 'none' : null,
                       radius: getComputedStyle(document.querySelector('.sl-board')).borderTopLeftRadius,
                       widest };
            })())"""))

        phone = await layout(390, 844)
        check(results, 'intro is dropped on a phone', phone['introShown'] is False,
              'display none' if phone['introShown'] is False else 'still shown')
        check(results, 'panel spans the full width',
              phone['left'] == 0 and phone['right'] == phone['vw'],
              'x %d..%d of %d' % (phone['left'], phone['right'], phone['vw']))
        check(results, 'panel starts under the header, no gap',
              phone['top'] <= 44, 'top %d' % phone['top'])
        check(results, 'corners squared off at the edge', phone['radius'] == '0px', phone['radius'])
        check(results, 'nothing sticks out sideways', phone['widest'] <= phone['vw'],
              'widest %d vs viewport %d' % (phone['widest'], phone['vw']))

        narrow = await layout(320, 568)
        check(results, 'still fits a 320px screen', narrow['widest'] <= narrow['vw'],
              'widest %d vs viewport %d' % (narrow['widest'], narrow['vw']))

        desk = await layout(1280, 900)
        check(results, 'desktop keeps its introduction', desk['introShown'] is True,
              'shown' if desk['introShown'] else 'MISSING')
        check(results, 'desktop panel stays inset and rounded',
              desk['left'] > 0 and desk['radius'] != '0px',
              'x %d..%d radius %s' % (desk['left'], desk['right'], desk['radius']))

        await ws.send(json.dumps({'id': 999, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    bad = [r for r in results if not r[1]]
    print('\n%d/%d checks pass' % (len(results) - len(bad), len(results)))
    for label, _, detail in bad:
        print('  FAILED: %s  %s' % (label, detail))
    sys.exit(1 if bad else 0)


asyncio.run(main())
