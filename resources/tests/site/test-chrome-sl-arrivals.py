"""The SL boards show when each train will be at the far end.

uppsala.html shows, for every departure, the time the train is expected at
Solna; solna.html the time it is expected at Uppsala C. The departures API
cannot give that - it lists three departures per line and direction, and at
the far end those are other trains - so the board asks SL's journey planner
for trips from here to there, joins each trip to a departure by train number,
and adds the running time the planner forecasts to the board's own forecast
for the departure.

Both APIs are stubbed, with times built from the moment the page loads:

  2243  leaves in 5 min, on time; the planner forecasts 48 min to the far end
  2245  leaves in 35 min, 7 late; forecast 46 min against 48 in the timetable,
        so it arrives 5 late and is shown in red
  2247  leaves in 65 min; the planner has no forecast for it, only the
        timetable, which then stands in
  99001 a trip in the planner's answer that the board does not list (say a
        replacement bus), between the first two. Matching by position would
        hand its time to 2245; matching by number leaves it out, and 2247,
        pushed out of the planner's three, is asked for again from its own
        minute.

Then the planner goes down while the first departure slips four minutes: the
time at the far end has to slip with it at once, from the running time already
known, and the board must not ask the planner again on every refresh.

Serve the repository and start headless Chrome (the recipe is in README.md),
by default on ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose
others. Exit status is 0 when every check passes.
"""
import asyncio, json, os, sys, time, urllib.request, websockets

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))

STUB = r"""
(() => {
  const pad = (n) => String(n).padStart(2, '0');
  const local = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  /* The planner answers in UTC, the departures API in zone-less local time. */
  const utc = (d) => d.toISOString().replace(/\.\d{3}Z$/, 'Z');
  const hhmm = (d) => d.toLocaleTimeString('sv-SE', { hour: '2-digit', minute: '2-digit' });
  const solna = location.pathname.indexOf('solna') >= 0;
  const HOME = solna ? 9509 : 6086;
  /* Whole minutes from the next minute on, as a timetable is. */
  const t0 = new Date();
  t0.setSeconds(0, 0);
  t0.setMinutes(t0.getMinutes() + 1);
  const at = (min) => new Date(t0.getTime() + min * 60000);
  const day = `${t0.getFullYear()}${pad(t0.getMonth() + 1)}${pad(t0.getDate())}`;
  /* dep and exp: scheduled and expected departure here, minutes from t0.
     run and runLive: the planner's timetabled and forecast running time.
     live false: the planner has no forecast for the train at all. */
  const S = window.__sl = {
    calls: { dep: 0, jp: 0 }, jp: [], plannerDown: location.hash === '#planner-down',
    trains: [
      { n: 2243, dep: 5, exp: 5, run: 48, runLive: 48 },
      { n: 2245, dep: 35, exp: 42, run: 48, runLive: 46 },
      { n: 2247, dep: 65, exp: 65, run: 48, runLive: 48, live: false },
    ],
    foreign: { n: 99001, dep: 20, exp: 20, run: 57, runLive: 57 },
    at, hhmm,
  };
  /* What the board should show, worked out here from the same dates. */
  window.__slExpect = (i, run) => hhmm(at(S.trains[i].exp + run));

  const json = (body, status) => Promise.resolve(new Response(JSON.stringify(body),
    { status: status || 200, headers: { 'Content-Type': 'application/json' } }));

  const planner = (url) => {
    const q = new URL(url).searchParams;
    S.jp.push(Object.fromEntries(q));
    S.calls.jp++;
    if (S.plannerDown) return json({ message: 'Service Unavailable' }, 503);
    const d = q.get('itd_date') || '', t = q.get('itd_time') || '';
    const from = new Date(+d.slice(0, 4), +d.slice(4, 6) - 1, +d.slice(6, 8), +t.slice(0, 2), +t.slice(2, 4));
    /* Like the real one: trips from the asked-for minute on, three at most. */
    const trips = S.trains.concat([S.foreign])
      .filter((tr) => at(tr.dep) >= from)
      .sort((a, b) => a.dep - b.dep)
      .slice(0, 3);
    return json({ systemMessages: [], journeys: trips.map((tr) => {
      const id = '90150010040' + String(tr.n).padStart(5, '0');
      const origin = { name: 'here', departureTimePlanned: utc(at(tr.dep)) };
      const destination = { name: 'there', arrivalTimePlanned: utc(at(tr.dep + tr.run)) };
      if (tr.live !== false) {
        origin.departureTimeEstimated = utc(at(tr.exp));
        destination.arrivalTimeEstimated = utc(at(tr.exp + tr.runLive));
      }
      return { interchanges: 0, legs: [{ origin, destination, properties: { tripId: id },
        transportation: { disassembledName: '40', properties: { RealtimeTripId: id } } }] };
    }) });
  };

  window.fetch = function (input) {
    const url = String((input && input.url) || input || '');
    if (url.indexOf('journeyplanner.integration.sl.se') >= 0) return planner(url);
    if (url.indexOf('/trains') >= 0) return json({ trains: [] });
    if (url.indexOf('transport.integration.sl.se') >= 0) {
      S.calls.dep++;
      const site = Number((/\/sites\/(\d+)\//.exec(url) || [])[1]) || 0;
      return json({ stop_deviations: [], departures: site !== HOME ? [] : S.trains.map((tr) => ({
        destination: solna ? 'Uppsala C' : 'Älvsjö', direction_code: solna ? 2 : 1,
        state: tr.state || 'EXPECTED', scheduled: local(at(tr.dep)), expected: local(at(tr.exp)),
        line: { designation: '40' }, journey: { id: day + String(tr.n).padStart(5, '0') },
        stop_point: { designation: '3' }, deviations: [],
      })) });
    }
    return Promise.reject(new Error('unexpected fetch ' + url));
  };
})();
"""

PROBE = r"""JSON.stringify((() => {
  const hero = document.querySelector('.sl-hero');
  const heroArr = hero && hero.querySelector('.sl-arr .sl-arr-time');
  const box = (el) => { const r = el.getBoundingClientRect(); return { left: r.left, right: r.right }; };
  const rows = [...document.querySelectorAll('.sl-row')].map((r) => {
    const cell = r.querySelector('.sl-row-arr'), t = cell && cell.querySelector('.sl-arr-time');
    return { cell: !!cell, label: cell && cell.querySelector('small') ? cell.querySelector('small').textContent.trim() : null,
             time: t ? t.textContent.trim() : null, late: !!(t && t.classList.contains('sl-arr-late')),
             cellBox: cell ? box(cell) : null, timeBox: t ? box(t) : null, rowBox: box(r),
             destBox: box(r.querySelector('.sl-row-dest')) };
  });
  return {
    labels: hero ? [...hero.querySelectorAll('.sl-time-label')].map((l) => l.textContent.trim()) : [],
    hero: heroArr ? { time: heroArr.textContent.trim(), late: heroArr.classList.contains('sl-arr-late') } : null,
    rows, calls: window.__sl.calls, jp: window.__sl.jp,
    error: (document.querySelector('.sl-board .sl-error') || {}).textContent || null,
    departures: (hero ? 1 : 0) + rows.length,
    first: { date: (() => { const d = window.__sl.at(window.__sl.trains[0].dep);
                            const p = (n) => String(n).padStart(2, '0');
                            return [`${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`, `${p(d.getHours())}${p(d.getMinutes())}`]; })(),
             third: (() => { const d = window.__sl.at(window.__sl.trains[2].dep);
                            const p = (n) => String(n).padStart(2, '0');
                            return [`${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`, `${p(d.getHours())}${p(d.getMinutes())}`]; })() },
  };
})())"""

# Every element of the page's own content against the screen, both edges.
FIT = r"""JSON.stringify((() => {
  let widest = 0, widestEl = '', leftmost = 0, leftEl = '';
  for (const el of document.querySelectorAll('.sl-wrap *')) {
    const b = el.getBoundingClientRect();
    if (!b.width && !b.height) continue;
    const name = el.tagName.toLowerCase() + '.' + (el.getAttribute('class') || '') +
      ' "' + (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 24) + '"';
    if (Math.round(b.right) > widest) { widest = Math.round(b.right); widestEl = name; }
    if (Math.round(b.left) < leftmost) { leftmost = Math.round(b.left); leftEl = name; }
  }
  /* The far-end time itself, not only its cell: a cell can sit inside its
     row while the text in it is cut off at the row's edge. */
  const cut = [...document.querySelectorAll('.sl-row')].filter((r) => {
    const t = r.querySelector('.sl-arr-time');
    if (!t) return false;
    const a = t.getBoundingClientRect(), b = r.getBoundingClientRect();
    return a.right > b.right + 0.5 || a.left < b.left - 0.5;
  }).length;
  return { vw: innerWidth, widest, widestEl, leftmost, leftEl, cut,
           times: [...document.querySelectorAll('.sl-row .sl-arr-time')].length };
})())"""


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

    async def probe(self):
        return json.loads(await self.js(PROBE))

    async def refresh(self, settle=0.6):
        # refresh() resolves when the departures are in; the planner is asked
        # after that, so give it a moment to answer before reading the board.
        await self.js("document.getElementById('board').__slBoard.refresh().then(() => 'ok')")
        await asyncio.sleep(settle)


def check(results, label, ok, detail):
    results.append((label, ok, detail))
    print('  %-52s %-5s %s' % (label, 'PASS' if ok else 'FAIL', detail))


async def open_page(ws, page, width, height, hash_=''):
    await ws.send(json.dumps({'id': 1, 'method': 'Target.createTarget', 'params': {'url': 'about:blank'}}))
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
    # A stale sl-board.js against a fresh sl-board.css is the one combination
    # that makes these files lie; see test-chrome-sl-idle.py.
    await s.call('Network.enable')
    await s.call('Network.setCacheDisabled', {'cacheDisabled': True})
    await s.call('Emulation.setDeviceMetricsOverride',
                 {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': width < 600})
    await s.call('Page.addScriptToEvaluateOnNewDocument', {'source': STUB})
    await s.call('Page.navigate', {'url': 'http://127.0.0.1:%d/%s?nocache=%d%s' % (
        HTTP, page, int(time.time() * 1000), hash_)})
    await asyncio.sleep(3)
    return s, tid


async def close(ws, tid):
    await ws.send(json.dumps({'id': 999, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))


async def uppsala(ws, results):
    s, tid = await open_page(ws, 'uppsala.html', 1000, 900)
    exp = lambda i, run: s.js('window.__slExpect(%d, %d)' % (i, run))

    print('\n1. Uppsala C: each departure says when it is at Solna')
    b = await s.probe()
    check(results, 'the board lists the three departures', b['departures'] == 3,
          '%d shown' % b['departures'])
    want0 = await exp(0, 48)
    check(results, 'next train: "At Solna" with its time', 'At Solna' in b['labels'] and
          b['hero'] and b['hero']['time'] == want0,
          'labels %s, time %s, want %s' % (b['labels'], b['hero'] and b['hero']['time'], want0))
    check(results, 'next train, on time: not marked late', b['hero'] and not b['hero']['late'], '')
    rows = b['rows']
    want1, want2 = await exp(1, 46), await exp(2, 48)
    check(results, 'each following row has its own time at Solna',
          len(rows) == 2 and [r['time'] for r in rows] == [want1, want2]
          and all(r['label'] == 'at Solna' for r in rows),
          'rows %s, want %s' % ([(r['label'], r['time']) for r in rows], [want1, want2]))
    check(results, 'joined by train number, not by place in the list',
          rows and rows[0]['time'] == want1,
          '2245 shows %s (the replacement trip would have given %s)' % (
              rows and rows[0]['time'], await s.js('window.__sl.hhmm(window.__sl.at(20 + 57))')))
    check(results, 'a train 5 min late at the far end is in red', rows and rows[0]['late'], '')
    check(results, 'with no forecast the timetable stands in, not marked late',
          len(rows) > 1 and rows[1]['time'] == want2 and not rows[1]['late'],
          '%s' % (rows[1]['time'] if len(rows) > 1 else None))

    jp = b['jp']
    first = jp[0] if jp else {}
    check(results, 'the planner is asked about the right trip',
          first.get('name_origin') == '9091001000006086' and first.get('name_destination') == '9091001000009509'
          and first.get('max_changes') == '0' and first.get('calc_number_of_trips') == '3'
          and first.get('calc_one_direction') == 'true',
          '%s -> %s, changes %s, trips %s, one direction %s' % (
              first.get('name_origin'), first.get('name_destination'), first.get('max_changes'),
              first.get('calc_number_of_trips'), first.get('calc_one_direction')))
    check(results, 'from the first departure\'s own minute',
          [first.get('itd_date'), first.get('itd_time')] == b['first']['date'],
          '%s %s, want %s' % (first.get('itd_date'), first.get('itd_time'), ' '.join(b['first']['date'])))
    check(results, 'the train pushed out of its three is asked for again',
          len(jp) == 2 and [jp[1].get('itd_date'), jp[1].get('itd_time')] == b['first']['third'],
          '%d requests%s' % (len(jp), (', second from %s %s' % (jp[1].get('itd_date'), jp[1].get('itd_time')))
                              if len(jp) > 1 else ''))
    check(results, 'no drawing of the route is asked for', first.get('gen_c') == 'false',
          'gen_c=%s' % first.get('gen_c'))
    # The join itself, on ids as the two APIs really write them.
    # Tolerant of an sl-board.js without it, so that one reports a failure
    # here rather than crashing the run.
    ids = json.loads(await s.js("JSON.stringify(typeof KVOT_SL.tripNumberOf !== 'function' ? null :"
                                " [KVOT_SL.tripNumberOf('9015001004002243'),"
                                " KVOT_SL.trainNumberOf('2026101802243'), KVOT_SL.tripNumberOf('abc'),"
                                " KVOT_SL.tripNumberOf(null)])"))
    check(results, 'trip 9015001004002243 is train 2243, as is journey 2026101802243',
          ids == ['2243', '2243', None, None], str(ids))

    print('\n2. Nothing changed: the planner is not asked again')
    before = b['calls']['jp']
    await s.refresh()
    await s.refresh()
    b = await s.probe()
    check(results, 'two refreshes of the departures, no new request',
          b['calls']['jp'] == before and b['calls']['dep'] > 0,
          '%d planner requests before, %d after' % (before, b['calls']['jp']))

    print('\n3. The first train slips 4 min while the planner is down')
    await s.js("window.__sl.plannerDown = true; window.__sl.trains[0].exp = 9; 'ok'")
    before = b['calls']['jp']
    await s.refresh()
    b = await s.probe()
    want0 = await exp(0, 48)
    check(results, 'a departure that moved is asked about at once', b['calls']['jp'] == before + 1,
          '%d new request(s)' % (b['calls']['jp'] - before))
    check(results, 'the time at Solna slips with the departure',
          b['hero'] and b['hero']['time'] == want0, '%s, want %s' % (b['hero'] and b['hero']['time'], want0))
    check(results, 'and is now marked late', b['hero'] and b['hero']['late'], '')
    check(results, 'the failure is quiet: departures still shown, no error',
          b['departures'] == 3 and not b['error'], 'error %r' % b['error'])
    before = b['calls']['jp']
    for _ in range(3):
        await s.refresh(0.3)
    b = await s.probe()
    check(results, 'no request on every refresh while it is down', b['calls']['jp'] == before,
          '%d new request(s) in three refreshes' % (b['calls']['jp'] - before))

    print('\n4. A cancelled train has no time at the far end')
    await s.js("window.__sl.trains[1].state = 'CANCELLED'; 'ok'")
    await s.refresh()
    b = await s.probe()
    check(results, 'its row keeps the cell, empty', b['rows'] and b['rows'][0]['cell'] and b['rows'][0]['time'] is None,
          'time %r' % (b['rows'] and b['rows'][0]['time']))
    await s.js("window.__sl.trains[1].state = 'EXPECTED'; 'ok'")
    await s.refresh()

    print('\n5. Rows line up and fit, desktop and phone')
    b = await s.probe()
    lefts = sorted({round(r['cellBox']['left'], 1) for r in b['rows'] if r['cellBox']})
    check(results, 'the time at the far end is one column on a desktop', len(lefts) == 1,
          'left edges %s' % lefts)
    clear = all(r['timeBox']['right'] <= r['destBox']['left'] for r in b['rows'] if r['timeBox'])
    check(results, 'and stays clear of the destination', clear,
          '; '.join('%.0f..%.0f vs %.0f' % (r['timeBox']['left'], r['timeBox']['right'], r['destBox']['left'])
                    for r in b['rows'] if r['timeBox']))
    for w, h in ((390, 664), (320, 568)):
        await s.call('Emulation.setDeviceMetricsOverride',
                     {'width': w, 'height': h, 'deviceScaleFactor': 1, 'mobile': True})
        await asyncio.sleep(1.3)
        f = json.loads(await s.js(FIT))
        check(results, '%dpx: nothing sticks out on either side' % w,
              f['widest'] <= f['vw'] and f['leftmost'] >= 0,
              'widest %d of %d (%s), leftmost %d (%s)' % (f['widest'], f['vw'], f['widestEl'],
                                                         f['leftmost'], f['leftEl']))
        check(results, '%dpx: every row\'s time at Solna is whole' % w, f['times'] == 2 and f['cut'] == 0,
              '%d shown, %d cut off' % (f['times'], f['cut']))
    await close(ws, tid)


async def solna(ws, results):
    print('\n6. Solna: the time at Uppsala C')
    s, tid = await open_page(ws, 'solna.html', 1000, 900)
    b = await s.probe()
    want0 = await s.js('window.__slExpect(0, 48)')
    check(results, 'next train: "At Uppsala C" with its time',
          'At Uppsala C' in b['labels'] and b['hero'] and b['hero']['time'] == want0,
          'labels %s, time %s, want %s' % (b['labels'], b['hero'] and b['hero']['time'], want0))
    check(results, 'rows say "at Uppsala C"', b['rows'] and all(r['label'] == 'at Uppsala C' for r in b['rows']),
          str([r['label'] for r in b['rows']]))
    first = b['jp'][0] if b['jp'] else {}
    check(results, 'asked from Solna to Uppsala C',
          first.get('name_origin') == '9091001000009509' and first.get('name_destination') == '9091001000006086',
          '%s -> %s' % (first.get('name_origin'), first.get('name_destination')))
    await close(ws, tid)

    print('\n7. The planner down from the start')
    s, tid = await open_page(ws, 'solna.html', 1000, 900, '#planner-down')
    await s.refresh()
    await s.refresh()
    b = await s.probe()
    check(results, 'departures shown, with no time at the far end and no error',
          b['departures'] == 3 and b['hero'] is None and not b['error']
          and not any(r['time'] for r in b['rows']),
          '%d departures, next train\'s time %r, error %r' % (b['departures'], b['hero'], b['error']))
    check(results, 'asked once, not on every refresh', b['calls']['jp'] == 1,
          '%d requests over %d departure refreshes' % (b['calls']['jp'], b['calls']['dep']))
    await close(ws, tid)


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json/version' % CDP))
    results = []
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as ws:
        await uppsala(ws, results)
        await solna(ws, results)

    bad = [r for r in results if not r[1]]
    print('\n%d/%d checks pass' % (len(results) - len(bad), len(results)))
    for label, _, detail in bad:
        print('  FAILED: %s  %s' % (label, detail))
    sys.exit(1 if bad else 0)


asyncio.run(main())
