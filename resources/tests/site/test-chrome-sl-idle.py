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
  /* Minutes from the first station of each corridor, so a journey's times
     advance down the line the way real ones do. Without this every station
     answered with the same clock time, no train could be placed *between* two
     of them, and the diagram drew no chips at all. */
  const ALONG = { 6086: 0, 6092: 10, 9511: 18, 9502: 28,
                  1080: 0, 9117: 2, 9509: 7, 9508: 10, 9507: 13 };
  window.__slDepartures = (forecastMin, siteId) => {
    const now = new Date();
    const at = ALONG[siteId] || 0;
    const from = (mins) => new Date(now.getTime() + (mins + at) * 60000);
    /* One service already running, so there is a train on the line rather
       than only trains yet to leave. It left before "now", so the departure
       list drops it while the diagram still draws it. */
    const running = from(-8);
    const soon = from(12);
    const later = from(42);
    const distant = new Date(now.getTime() + (10 * 60 + at) * 60000);
    /* What the page will have to say about that third one, decided here from
       the same dates the board will see. */
    window.__slCrossesMidnight = distant.getDate() !== now.getDate();
    /* One northbound service, due at the far end of the drawing in ten
       minutes. A southbound train approaching the *home* station is never
       drawn - the board's own list is about those - so without this there is
       no "not here yet" marker anywhere to check. Its times run the other way
       along the corridor, which is what makes it northbound. */
    const north = new Date(now.getTime() + (10 + (28 - at)) * 60000);
    const horizon = now.getTime() + (forecastMin || 60) * 60000;
    const rows = [
      { when: running, dir: 1, dest: 'Stockholm City' },
      { when: soon, dir: 1, dest: 'Stockholm City' },
      { when: later, dir: 1, dest: 'Stockholm City' },
      { when: distant, dir: 1, dest: 'Stockholm City' },
      { when: north, dir: 2, dest: 'Uppsala C' },
      /* Southbound, leaving Uppsala C shortly, and deliberately given no
         position: Uppsala C is a terminus, so this train is standing at the
         platform rather than approaching from anywhere, and the diagram has to
         show it. It used to be left off entirely - the list said six minutes
         and the platform was drawn empty. */
      { when: from(7), dir: 1, dest: 'Stockholm City' },
    ];
    /* A line 41 service, calling only at Upplands Väsby - which is where 41
       joins this corridor from Märsta. Due in a minute, so it should be drawn
       a minute down the Märsta curve rather than on the main band. */
    if (siteId === 9502) rows.push({ when: from(1 - at), dir: 1, dest: 'Södertälje centrum', line: '41' });
    return rows.filter((r) => r.when.getTime() <= horizon).map(({ when, dir, dest, line }, i) => ({
      destination: dest,
      direction_code: dir,
      state: 'EXPECTED',
      scheduled: local(when),
      expected: local(when),
      line: { designation: line || '40' },
      /* The journey id must be the *first* station's date, or the same train
         would carry different ids along the corridor and never join up. */
      journey: { id: `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}${String(2269 + i).padStart(5, '0')}` },
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
      /* Four trains running down the Uppsala C -> Knivsta leg close enough
         together to crowd each other, each at its own speed so the gaps
         between them open and close as time passes. That is the scene that
         made rows flicker. 9999 matches no departure and must never be drawn.
         Positions are interpolated along the real leg, so they land on the
         corridor rather than beside it. */
      const A = { lat: 59.8573, lon: 17.6485 }, B = { lat: 59.7259, lon: 17.7869 };
      const at = (f) => ({ lat: A.lat + f * (B.lat - A.lat), lon: A.lon + f * (B.lon - A.lon),
                           speed: 96, bearing: 150, ageSec: 4 });
      /*
        A queue of four trains on the leg. The first stands still; the gap to
        the second is swept by the test from far too small to comfortably
        large, while the third and fourth follow the second at a fixed spacing
        that is always tight.

        That sweep is the whole point. It takes one gap through the threshold
        at which trains have to be drawn in separate rows, which is where a
        rule that chains each train's row off its neighbour's flips the row of
        every train behind it - the flicker this is here to catch. The third
        and fourth trains never change their spacing at all, so any change in
        *their* rows is the cascade and nothing else.

        The phase comes from the test, not the clock. Two earlier versions
        could not be compared between runs: a steady drift ran the trains off
        the end of the corridor, and a wall-clock sine had every run sampling a
        different part of the cycle - the same code scored 5 row changes one
        run and 0 the next, which measures nothing.
      */
      const t = window.__slPhase || 0;
      const fA = 0.08;
      /* The gap to the second train alternates across the margin that a
         "leave a comfortable space" rule treats as the moment to move, while
         staying well inside the band that a "only move when they actually
         collide" rule tolerates. In viewBox units that is roughly 55 against
         70, around a margin near 60 and an overlap near 54.

         This is the reported symptom, not a sweep: nothing on the track is
         really changing, the gap merely breathes on the threshold. A rule
         that chains each train's row off its neighbour's flips this train
         every step and the two behind it with it. */
      const fB = fA + 0.162 + 0.044 * (t % 2);
      const fC = fB + 0.115, fD = fC + 0.115;
      /* 2272 is deliberately absent: a departure with no position falls back
         to the forecast, which parks it short of the first station it is due
         at as a hollow "not here yet" marker. Without one of those the
         approach-side checks have nothing to look at. */
      const moving = [['2269', fA], ['2270', fB], ['2271', fC]]
        .map(([number, f]) => Object.assign({ number }, at(f)));
      return json({ timestamp: Math.floor(Date.now() / 1000), count: moving.length + 1,
                    trains: moving.concat([Object.assign({ number: '9999' }, at(0.92))]) });
    }
    if (url.indexOf('transport.integration.sl.se') >= 0) {
      window.__slCalls.dep++;
      const forecast = Number((/[?&]forecast=(\d+)/.exec(url) || [])[1]) || 60;
      const site = Number((/\/sites\/(\d+)\//.exec(url) || [])[1]) || 0;
      return json({ departures: window.__slDepartures(forecast, site), stopDeviations: [] });
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
            keys: [...document.querySelectorAll('.sl-train')].map((g) => g.getAttribute('data-key')),
            /* A train standing at its terminus waiting to leave. */
            departing: [...document.querySelectorAll('.sl-train title')]
              .map((t) => t.textContent).filter((t) => /leaves in \\d+ min/.test(t)),
            unnamed: document.querySelectorAll('.sl-train-unnamed').length,
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
        keys = board['keys']
        check(results, 'a fix matching a departure is drawn', 'gps:tv:2269' in keys,
              ', '.join(keys) or 'nothing drawn')
        check(results, 'the train about to leave is drawn at its terminus',
              len(board['departing']) >= 1,
              '; '.join(t[:58] for t in board['departing'][:2]) or 'platform drawn empty')
        check(results, 'a fix matching nothing is left off',
              not any('9999' in k for k in keys) and board['unnamed'] == 0,
              '%d unnamed chips' % board['unnamed'])
        # Four southbound services are offered within the window - in seven and
        # twelve and forty-two minutes, and one ten hours out - and every one of
        # them has to reach the list. At the old three-hour window the last was
        # simply missing, which is the bug this guards.
        check(results, 'every departure offered reaches the list', board['count'] == 4,
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
            # The CSS reflows on its own, but the diagram's shapes are drawn in
            # units computed from the element's width, so the board has to run
            # a render before they mean anything at the new size.
            await s.js("document.querySelector('.sl-board').__slBoard.start(); 'ok'")
            await asyncio.sleep(1.3)
            return json.loads(await s.js("""JSON.stringify((() => {
              const b = document.querySelector('.sl-board').getBoundingClientRect();
              const intro = document.querySelector('.sl-intro');
              /* This site has twice shipped a padded content-box that widened
                 the layout viewport, so scrollWidth agreed while the element
                 stuck out. Measure elements against innerWidth instead. */
              /* Both edges. Measuring only the right one let a label that hung
                 off the left of the panel go unnoticed. */
              let widest = 0, widestEl = '', leftmost = 0, leftEl = '';
              for (const el of document.querySelectorAll('.sl-wrap *')) {
                const b = el.getBoundingClientRect();
                const name = el.tagName.toLowerCase() + '.' + (el.getAttribute('class') || '') +
                  ' "' + (el.textContent || '').trim().slice(0, 20) + '"';
                if (Math.round(b.right) > widest) { widest = Math.round(b.right); widestEl = name; }
                if (Math.round(b.left) < leftmost) { leftmost = Math.round(b.left); leftEl = name; }
              }
              const c = document.querySelector('.content').getBoundingClientRect();
              /* renderNav puts the hamburger and its menu after <header>, not
                 inside it, so hiding the header alone leaves a button over the
                 board - every piece is listed here, not just the two tags. */
              const shown = ['header', 'footer', '.nav-toggle', '#menu', '#kvotmap']
                .filter((sel) => { const e = document.querySelector(sel);
                                   return e && getComputedStyle(e).display !== 'none'; });
              /* preserveAspectRatio="none" stretches the two axes by very
                 different amounts, so shapes are drawn in units pre-divided by
                 that ratio. The proof is that a chip and a stop keep the same
                 rendered proportions at any width of screen - without the
                 correction a chip is a wide lozenge on a desktop and a narrow
                 sliver on a phone. */
              const ratio = (sel) => {
                const e = document.querySelector(sel);
                if (!e) return null;
                const r = e.getBoundingClientRect();
                return r.height > 0 ? Math.round((r.width / r.height) * 100) / 100 : null;
              };
              return { vw: innerWidth, vh: innerHeight,
                       chipRatio: ratio('.sl-train-body'), stopRatio: ratio('.sl-stop'),
                       left: Math.round(b.left), right: Math.round(b.right), top: Math.round(b.top),
                       introShown: intro ? getComputedStyle(intro).display !== 'none' : null,
                       radius: getComputedStyle(document.querySelector('.sl-board')).borderTopLeftRadius,
                       contentTop: Math.round(c.top), contentH: Math.round(c.height),
                       chromeShown: shown, widest, widestEl, leftmost, leftEl };
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
              'widest %d vs viewport %d - %s' % (phone['widest'], phone['vw'], phone['widestEl']))
        check(results, 'site header, footer, nav and map are all gone',
              phone['chromeShown'] == [], ', '.join(phone['chromeShown']) or 'none shown')
        check(results, 'the page area is the whole screen',
              phone['contentTop'] == 0 and phone['contentH'] == phone['vh'],
              'content top %d height %d of %d' % (phone['contentTop'], phone['contentH'], phone['vh']))

        narrow = await layout(320, 568)
        check(results, 'nothing hangs off the left either', phone['leftmost'] >= 0,
              'leftmost %d - %s' % (phone['leftmost'], phone['leftEl']) if phone['leftmost'] < 0 else 'flush at 0')
        check(results, 'still fits a 320px screen', narrow['widest'] <= narrow['vw'],
              'widest %d vs viewport %d - %s' % (narrow['widest'], narrow['vw'], narrow['widestEl']))

        # Same shapes, screen four times wider: the proportions must not move.
        wideV = await layout(1280, 900)
        # The number that matters is that the two agree; the target just
        # catches a shape collapsing. It follows the drawn proportions - a chip
        # is 28 viewBox units wide by 24 tall - so it moves when those do.
        for name, key, want in (('train chip', 'chipRatio', 28 / 24), ('stop marker', 'stopRatio', 0.35)):
            a, b = phone[key], wideV[key]
            ok = a is not None and b is not None and abs(a - b) <= 0.12 and abs(a - want) <= 0.25
            check(results, '%s keeps its shape at any width' % name, ok,
                  'phone %s vs desktop %s (want ~%s)' % (a, b, want))

        desk = wideV
        check(results, 'desktop keeps its introduction', desk['introShown'] is True,
              'shown' if desk['introShown'] else 'MISSING')
        check(results, 'desktop panel stays inset and rounded',
              desk['left'] > 0 and desk['radius'] != '0px',
              'x %d..%d radius %s' % (desk['left'], desk['right'], desk['radius']))
        check(results, 'desktop keeps the site chrome',
              'header' in desk['chromeShown'] and 'footer' in desk['chromeShown'],
              ', '.join(desk['chromeShown']) or 'NONE - navigation lost on desktop too')

        print('\n11. Trains stand one after another, not on top of each other')
        # The board is running and desktop-sized after section 10. The stub has
        # four trains crowding each other, with the gap between the first two
        # alternating across the margin - the scene that used to send chips
        # hopping between rows. There are no rows now: chips are nudged along
        # the line instead, so what has to hold is that they never overlap,
        # never change height, and keep their order.
        frames = []
        for step in range(14):
            await s.js("window.__slPhase = %s;"
                       "document.querySelector('.sl-board').__slBoard.refreshTrains(); 'ok'" % step)
            # A chip slides to its new place over a second, so a reading taken
            # before that is of trains mid-move and finds overlaps that are
            # never on screen when they come to rest.
            await asyncio.sleep(1.2)
            frames.append(json.loads(await s.js("""JSON.stringify(
              /* The chip itself, not the group: a group's box includes the
                 chevron and the speed label, which are meant to sit outside
                 the body and are not what "on top of each other" means. */
              [...document.querySelectorAll('.sl-train')].map((g) => {
                const r = g.querySelector('.sl-train-body').getBoundingClientRect();
                return { key: g.getAttribute('data-key'),
                         left: Math.round(r.left), right: Math.round(r.right),
                         y: Math.round(r.top) };
              }))""")))

        drawn = {c['key'] for f in frames for c in f}
        check(results, 'the scene really crowds the trains', len(drawn) >= 3,
              '%d chips over %d samples' % (len(drawn), len(frames)))

        overlaps = []
        for i, f in enumerate(frames):
            for a, b in zip(sorted(f, key=lambda c: c['left']), sorted(f, key=lambda c: c['left'])[1:]):
                if b['left'] < a['right'] and abs(a['y'] - b['y']) < 6:
                    overlaps.append('sample %d %s[%d-%d] over %s[%d-%d] by %dpx' % (
                        i, a['key'][-4:], a['left'], a['right'],
                        b['key'][-4:], b['left'], b['right'], a['right'] - b['left']))
        widths = sorted({c['right'] - c['left'] for f in frames for c in f})
        check(results, 'no two chips overlap', not overlaps,
              ('; '.join(overlaps[:2]) + ' | chip widths seen: %s' % widths) if overlaps
              else 'clear in every sample')

        # Chips on a branch curve are excluded: climbing the curve is exactly
        # what they are supposed to do, so their height changing is the
        # feature rather than the fault.
        heights = {}
        for f in frames:
            for c in f:
                if c['key'].startswith('br:'):
                    continue
                heights.setdefault(c['key'], set()).add(c['y'])
        hopped = {k: sorted(v) for k, v in heights.items() if len(v) > 1}
        check(results, 'no chip changes height', not hopped,
              ', '.join('%s %s' % kv for kv in list(hopped.items())[:3]) or 'every chip held its line')

        # A train that has not arrived must be drawn short of the station it
        # is due at, on the side it is coming from - never on the platform and
        # never past it. The sweep that spreads trains apart can push it
        # across its own station, which is what the bounds are for.
        appr = json.loads(await s.js("""JSON.stringify(
          [...document.querySelectorAll('.sl-train-approaching')].map((g) => {
            const body = g.querySelector('.sl-train-body').getBoundingClientRect();
            const name = ((g.querySelector('title').textContent.match(/due at (.+?) in /) || [])[1] || '').trim();
            const stop = [...document.querySelectorAll('.sl-station')]
              .find((st) => st.querySelector('text').textContent.trim() === name);
            const r = stop ? stop.querySelector('rect').getBoundingClientRect() : null;
            return { name, laneA: /sl-lane-a/.test(g.getAttribute('class')),
                     left: Math.round(body.left), right: Math.round(body.right),
                     stopLeft: r ? Math.round(r.left) : null,
                     stopRight: r ? Math.round(r.right) : null };
          }))"""))
        bad = []
        for c in appr:
            if c['stopLeft'] is None:
                bad.append('%s: station not found' % c['name']); continue
            if c['laneA'] and c['right'] > c['stopLeft']:
                bad.append('%s: on or past the stop (chip ends %d, stop starts %d)'
                           % (c['name'], c['right'], c['stopLeft']))
            if not c['laneA'] and c['left'] < c['stopRight']:
                bad.append('%s: on or past the stop (chip starts %d, stop ends %d)'
                           % (c['name'], c['left'], c['stopRight']))
        check(results, 'trains not here yet stop short of the platform',
              bool(appr) and not bad,
              '; '.join(bad[:2]) if bad else '%d checked, all clear of the stop' % len(appr))

        # A line that joins or leaves this one rides the curve at its junction,
        # not the main band: a 41 due at Upplands Väsby in a minute is a minute
        # down the Märsta curve, and a 43 past Odenplan is on its way to
        # Bålsta. Without this they either sit on the band they are not on, or
        # vanish at the junction with nothing to say where they went.
        onBranch = json.loads(await s.js("""JSON.stringify((() => {
          const curve = document.querySelector('[data-branch="41"]');
          const b = curve ? curve.getBBox() : null;
          const chips = [...document.querySelectorAll('.sl-train')]
            .filter((g) => (g.getAttribute('data-key') || '').startsWith('br:'))
            .map((g) => {
              const m = /translate\\(([-\\d.]+) ([-\\d.]+)\\)/.exec(g.getAttribute('transform') || '');
              return { x: m ? +m[1] : null, y: m ? +m[2] : null,
                       title: (g.querySelector('title') || {}).textContent };
            });
          return { box: b ? { x: b.x, y: b.y, w: b.width, h: b.height } : null, chips };
        })())"""))
        box, chips = onBranch['box'], onBranch['chips']
        ok = bool(box) and len(chips) == 1 and (
            box['x'] - 14 <= chips[0]['x'] <= box['x'] + box['w'] + 14 and
            box['y'] - 14 <= chips[0]['y'] <= box['y'] + box['h'] + 14)
        check(results, 'a joining line rides its own curve', ok,
              ('at %.0f,%.0f on a curve spanning %.0f..%.0f' % (
                  chips[0]['x'], chips[0]['y'], box['x'], box['x'] + box['w']))
              if ok else 'curve=%s chips=%s' % (bool(box), chips))

        # Nudging must never reorder them: a train behind another must stay
        # behind it, or the diagram is telling a lie to save space.
        order = [tuple(c['key'] for c in sorted(f, key=lambda c: c['left'])) for f in frames]
        swaps = sum(1 for a, b in zip(order, order[1:])
                    if [k for k in a if k in b] != [k for k in b if k in a])
        check(results, 'their order never changes', swaps == 0, '%d reorderings' % swaps)

        await ws.send(json.dumps({'id': 999, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    bad = [r for r in results if not r[1]]
    print('\n%d/%d checks pass' % (len(results) - len(bad), len(results)))
    for label, _, detail in bad:
        print('  FAILED: %s  %s' % (label, detail))
    sys.exit(1 if bad else 0)


asyncio.run(main())
