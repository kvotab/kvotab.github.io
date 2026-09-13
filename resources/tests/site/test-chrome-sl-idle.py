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
      return json({ departures: [], stopDeviations: [] });
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

        print('\n8. The live dot holds its position')
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

        await ws.send(json.dumps({'id': 999, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    bad = [r for r in results if not r[1]]
    print('\n%d/%d checks pass' % (len(results) - len(bad), len(results)))
    for label, _, detail in bad:
        print('  FAILED: %s  %s' % (label, detail))
    sys.exit(1 if bad else 0)


asyncio.run(main())
