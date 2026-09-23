"""Prove nothing on the SL boards shifts sideways as its numbers tick.

RawengulkSans has no tabular figures - "1" is .178em where "3" and "8" are
.482em - and `font-variant-numeric: tabular-nums` does nothing without a `tnum`
feature to switch on. So every number that changes once a second moved: the
centred "1:51" countdown by 13.4px a tick, and "Updated 4s ago", which grows
leftwards from the live dot, by a digit's difference. The board now writes
those digits into fixed-width cells; this checks the glyphs themselves hold
still, on both pages, at desktop and phone width.

Positions are measured on the text, through a Range, not on the elements: the
hero's count is a block as wide as its grid column, so its box stood perfectly
still while the digits inside it jumped.

The departures are stubbed so the next two trains are under two minutes away,
which is when the count is shown to the second.
"""
import asyncio, json, sys, time, urllib.request, websockets

SAMPLES = 12

STUB = r"""
(() => {
  try { localStorage.setItem('kvot-sl-trains', 'https://stub.invalid/trains'); } catch (e) {}
  const pad = (n) => String(n).padStart(2, '0');
  const local = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  /* Fixed at load, so the counts run down through the whole sample: 113 s is
     still under two minutes after load plus twelve seconds of reading. */
  const t0 = Date.now();
  const toUppsala = location.pathname.indexOf('solna') >= 0;
  const row = (sec, i) => {
    const w = new Date(t0 + sec * 1000);
    return { destination: toUppsala ? 'Uppsala C' : 'Stockholm City', direction_code: toUppsala ? 2 : 1,
             state: 'EXPECTED', scheduled: local(w), expected: local(w), line: { designation: '40' },
             journey: { id: '20260923' + String(2269 + i).padStart(5, '0') },
             stop_point: { designation: '1' }, deviations: [] };
  };
  const json = (body) => Promise.resolve(new Response(JSON.stringify(body),
    { status: 200, headers: { 'Content-Type': 'application/json' } }));
  window.fetch = function (input) {
    const url = String((input && input.url) || input || '');
    if (url.indexOf('/trains') >= 0) return json({ timestamp: Math.floor(Date.now() / 1000), count: 0, trains: [] });
    return json({ departures: [row(113, 0), row(118, 1), row(1500, 2)], stopDeviations: [] });
  };
})();
"""

# The text's own extent, and the colon's, for each thing that ticks.
PROBE = r"""JSON.stringify((() => {
  const box = (node) => {
    const rg = document.createRange();
    rg.selectNodeContents(node);
    const b = rg.getBoundingClientRect();
    return { left: Math.round(b.left * 10) / 10, width: Math.round(b.width * 10) / 10 };
  };
  /* The colon, whichever way it was written: a cell of its own, or a
     character inside a plain text node as the old code left it. */
  const colon = (el) => {
    const cell = el.querySelector('.sl-tnum-sep');
    if (cell) return box(cell).left;
    const tn = [...el.childNodes].find((n) => n.nodeType === 3 && n.data.indexOf(':') >= 0);
    if (!tn) return null;
    const rg = document.createRange(), i = tn.data.indexOf(':');
    rg.setStart(tn, i); rg.setEnd(tn, i + 1);
    return Math.round(rg.getBoundingClientRect().left * 10) / 10;
  };
  const read = (sel) => {
    const el = document.querySelector(sel);
    return el ? Object.assign({ text: el.textContent.trim(), colon: colon(el) }, box(el)) : null;
  };
  return { clock: read('#sl-clock'), live: read('#sl-live'),
           hero: read('.sl-count-big'), row: read('.sl-row-count') };
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


def check(results, label, ok, detail):
    results.append((label, ok, detail))
    print('  %-46s %-5s %s' % (label, 'PASS' if ok else 'FAIL', detail))


def spread(values):
    vs = sorted(set(values))
    return 0.0 if len(vs) < 2 else vs[-1] - vs[0]


async def board(ws, results, page, width):
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
    # The page URL is cache-busted but its stylesheet and script are only
    # versioned, and a stale sl-board.js against a fresh sl-board.css is the
    # one combination that makes this file lie. See test-chrome-sl-idle.py.
    await s.call('Network.enable')
    await s.call('Network.setCacheDisabled', {'cacheDisabled': True})
    await s.call('Emulation.setDeviceMetricsOverride',
                 {'width': width, 'height': 800, 'deviceScaleFactor': 1, 'mobile': width < 600})
    await s.call('Page.addScriptToEvaluateOnNewDocument', {'source': STUB})
    await s.call('Page.navigate',
                 {'url': 'http://127.0.0.1:8765/%s?nocache=%d' % (page, int(time.time() * 1000))})
    await asyncio.sleep(3)

    samples = []
    for _ in range(SAMPLES):
        samples.append(json.loads(await s.js(PROBE)))
        await asyncio.sleep(1.0)
    await ws.send(json.dumps({'id': 999, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    print('\n%s at %dpx' % (page, width))
    for key, name in (('hero', 'next-train countdown'), ('row', 'following-train countdown')):
        got = [x[key] for x in samples if x[key]]
        texts = [x['text'] for x in got]
        # Guard the guard: a count that never moved would pass every check
        # below while testing nothing.
        check(results, '%s ticks to the second' % name,
              len(got) == SAMPLES and len(set(texts)) >= SAMPLES - 3 and all(':' in t for t in texts),
              '%d distinct of %d, %s..%s' % (len(set(texts)), len(got), texts[0] if texts else '-',
                                             texts[-1] if texts else '-'))
        check(results, '%s colon holds still' % name, spread(x['colon'] for x in got) == 0,
              'moves %.1fpx' % spread(x['colon'] for x in got))
        check(results, '%s digits hold still' % name,
              spread(x['left'] for x in got) == 0 and spread(x['width'] for x in got) == 0,
              'left moves %.1fpx, width %.1fpx' % (spread(x['left'] for x in got),
                                                   spread(x['width'] for x in got)))

    # "Updated 4s ago" is right-aligned against the dot, so it grows leftwards
    # and is meant to move when its wording changes - "Live" to "Updated", or a
    # second digit arriving. Between two texts of the same length, it may not.
    by_len = {}
    for x in samples:
        by_len.setdefault(len(x['live']['text']), []).append(x['live'])
    wobble = {n: spread(v['left'] for v in vs) for n, vs in by_len.items()}
    varied = [n for n, vs in by_len.items() if len({v['text'] for v in vs}) > 1]
    check(results, 'status text had same-length changes to test', bool(varied),
          ', '.join(sorted({x['live']['text'] for x in samples})))
    check(results, 'status text holds still between them', all(w == 0 for w in wobble.values()),
          'left edge spread by length %s' % {n: round(w, 1) for n, w in wobble.items()})

    clocks = [x['clock'] for x in samples]
    check(results, 'clock ticks and holds still',
          len({c['text'] for c in clocks}) >= SAMPLES - 3 and spread(c['left'] for c in clocks) == 0
          and spread(c['width'] for c in clocks) == 0,
          'left moves %.1fpx, width %.1fpx' % (spread(c['left'] for c in clocks),
                                               spread(c['width'] for c in clocks)))


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    results = []
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as ws:
        for page in ('uppsala.html', 'solna.html'):
            for width in (1000, 390):
                await board(ws, results, page, width)

    bad = [r for r in results if not r[1]]
    print('\n%d/%d checks pass' % (len(results) - len(bad), len(results)))
    for label, _, detail in bad:
        print('  FAILED: %s  %s' % (label, detail))
    sys.exit(1 if bad else 0)


asyncio.run(main())
