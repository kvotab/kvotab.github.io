"""proj.html bulk conversion: the worker must run, and agree with the main thread.

The worker is built by serialising page functions into a blob. That drops
everything they closed over, so for a long time it threw a ReferenceError on
its first message and worker.onerror fell back to convertMainThread() without
saying anything — the results were right, every conversion just silently ran on
the main thread, which is the one thing the worker exists to avoid.

Two things are therefore checked, because either alone would have passed while
the bug was present:

  * the fallback is not taken (convertMainThread is spied on)
  * the worker's numbers equal the main thread's, for each projection pair

The sweref_99_1200 pair matters most: it is a local zone with polygon bounds,
so it exercises point_in_zone_bounds -> point_in_ring -> sweref99_zone_polygons,
the dependencies that were missing.

The national pair, wgs84_dd -> sweref_99_tm, is checked for what it *says*
about each row and not only for agreement, because agreement alone passed with
the old check. That check was a longitude band, 10.7-24.45E: Halden, Tornio
and Helsingor were "in zone", and Sandhamn was in only because the band did not
know about the sea. "In zone" for a national system now means inside Swedish
territory out to the maritime median lines (sweden_territory), which the
worker reaches through importScripts. Six rows straddle the border on purpose.

Needs a static server on 127.0.0.1:8765 and Chrome on 127.0.0.1:9222.
"""
import asyncio, json, sys, time, urllib.request, websockets

PROBE = r"""(async () => {
  const CASES = [
    ['rt90_2.5_gon_v', 'sweref_99_tm'],
    ['sweref_99_tm', 'wgs84_dd'],
    ['wgs84_dd', 'sweref_99_1200'],
    ['rt90_7.5_gon_v', 'sweref_99_tm'],
    ['wgs84_dd', 'sweref_99_tm']          // national: the flags are checked too
  ];
  /* The national case: three inside Sweden, three just outside it. Sandhamn
     is an island Natural Earth does not draw; Ven sits in Oresund 4 km from
     Denmark; Tornio is across the river from Haparanda. */
  const BORDER = [
    ['Stockholm',    59.3293, 18.0686, false],
    ['Sandhamn',     59.2880, 18.9150, false],
    ['Ven',          55.9100, 12.6950, false],
    ['Halden NO',    59.1200, 11.3870, true],
    ['Tornio FI',    65.8480, 24.1466, true],
    ['Helsingor DK', 56.0361, 12.6136, true]
  ];
  const INPUT = {
    'rt90_2.5_gon_v': '6580000\t1628000\n6590000\t1630000\n6600000\t1632000',
    'sweref_99_tm':   '6580000\t674000\n6590000\t676000\n6600000\t678000',
    'wgs84_dd':       '59.32\t18.07\n59.40\t18.10\n59.50\t18.20',
    'rt90_7.5_gon_v': '6400000\t1500000\n6410000\t1502000\n6420000\t1504000'
  };
  const NATIONAL_INPUT = BORDER.map(b => b[1] + '\t' + b[2]).join('\n');
  const btn = [...document.querySelectorAll('button')]
    .find(b => /convert/i.test(b.textContent) && !/clear/i.test(b.textContent));

  /* If the worker still fails, convertMainThread is what picks up the pieces. */
  let fellBack = false;
  const realFallback = window.convertMainThread;
  window.convertMainThread = function (...a) { fellBack = true; return realFallback.apply(this, a); };

  async function run(from, to, useWorker) {
    const RealWorker = window.Worker;
    if (!useWorker) window.Worker = function () { throw new Error('worker disabled for comparison'); };
    document.getElementById('bulk_from').value = from;
    document.getElementById('bulk_to').value = to;
    document.getElementById('bulk_input').value = (from === 'wgs84_dd' && to === 'sweref_99_tm') ? NATIONAL_INPUT : INPUT[from];
    btn.click();
    await new Promise(r => setTimeout(r, 2200));
    window.Worker = RealWorker;
    return (window.phase3Results || []).map(r =>
      `${r.status}|${typeof r.output1==='number'?r.output1.toFixed(6):'-'}|`
      + `${typeof r.output2==='number'?r.output2.toFixed(6):'-'}|${r.outside}`);
  }

  const report = [];
  for (const [from, to] of CASES) {
    fellBack = false;
    const w = await run(from, to, true);
    const workerFellBack = fellBack;
    const m = await run(from, to, false);
    const entry = { pair: `${from} -> ${to}`, match: JSON.stringify(w) === JSON.stringify(m),
                    fellBack: workerFellBack, worker: w[0], main: m[0], rows: w.length };
    if (from === 'wgs84_dd' && to === 'sweref_99_tm') {
      /* The fourth field of each row string is r.outside. */
      entry.flags = BORDER.map((b, i) => {
        const got = (w[i] || '').split('|')[3];
        return { name: b[0], want: b[3], got: got === 'true' ? true : got === 'false' ? false : got };
      });
    }
    report.push(entry);
  }
  return JSON.stringify(report);
})()"""

async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=100*1024*1024) as bws:
        await bws.send(json.dumps({'id':1,'method':'Target.createTarget','params':{'url':'about:blank'}}))
        t=None
        while t is None:
            m=json.loads(await bws.recv())
            if m.get('id')==1: t=m['result']['targetId']
        await bws.send(json.dumps({'id':2,'method':'Target.attachToTarget','params':{'targetId':t,'flatten':True}}))
        s=None
        while s is None:
            m=json.loads(await bws.recv())
            if m.get('id')==2: s=m['result']['sessionId']
        await bws.send(json.dumps({'id':3,'method':'Network.enable','sessionId':s}))
        await bws.send(json.dumps({'id':4,'method':'Network.setCacheDisabled','sessionId':s,'params':{'cacheDisabled':True}}))
        await bws.send(json.dumps({'id':5,'method':'Page.navigate','sessionId':s,'params':{'url':'http://127.0.0.1:8765/proj.html?n=%d'%int(time.time()*1000)}}))
        await asyncio.sleep(6)
        await bws.send(json.dumps({'id':6,'method':'Runtime.evaluate','sessionId':s,'params':{'expression':PROBE,'awaitPromise':True,'returnByValue':True,'timeout':120000}}))
        while True:
            m=json.loads(await bws.recv())
            if m.get('id')==6:
                r=m.get('result',{})
                if 'exceptionDetails' in r:
                    print('EXCEPTION', json.dumps(r['exceptionDetails'])[:500]); sys.exit(1)
                rows=json.loads(r['result']['value'])
                bad=0
                for x in rows:
                    ok = x['match'] and not x['fellBack']
                    print('%-38s rows=%d  %-6s %s' % (
                        x['pair'], x['rows'], 'MATCH' if x['match'] else 'DIFFER',
                        'worker' if not x['fellBack'] else 'FELL BACK TO MAIN THREAD'))
                    if not ok:
                        bad+=1
                        if not x['match']:
                            print('    worker:', x['worker'])
                            print('    main  :', x['main'])
                    for f in x.get('flags', []):
                        right = f['got'] == f['want']
                        print('    %-14s outside=%-5s %s' % (f['name'], f['got'],
                              'ok' if right else '<-- should be %s' % f['want']))
                        if not right: bad+=1
                print()
                print('all identical' if not bad else '%d mismatches' % bad)
                sys.exit(1 if bad else 0)
asyncio.run(main())
