"""The site footer on a phone: one line, and all of it on the screen.

The footer is one line tall. At 390px its text did not fit, and the end of it
wrapped onto a second line below the bottom of the screen, where only pulling
the page up could show it. The theme switch, absolutely placed at the right,
also sat on top of the last icon. Below 560px the street address now gives
way (the map button beside it still shows where the office is) and the line
does not wrap; below 360px the name goes too, as the header's logo carries it.

Checked on the landing page, on rdc.html (which adds two icons of its own and
so has the longest footer) and on a page in Swedish, at phone widths from 390
down to 320, and at a desktop width, where the address must still be there.

Serve the repository and start headless Chrome (the recipe is in README.md),
by default on ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose
others. Exit status is 0 when every check passes.
"""
import asyncio, json, os, sys, time, urllib.request, websockets

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))

# page, viewport width and height, whether the address shows
CASES = [
    ('index.html', 390, 664, False),
    ('index.html', 360, 640, False),
    ('index.html', 320, 568, False),
    ('rdc.html', 390, 664, False),
    ('rdc.html', 360, 640, False),
    ('inkomstdeklaration.html', 360, 640, False),
    ('rdc.html', 320, 568, False),
    ('index.html', 1400, 900, True),
    ('rdc.html', 1400, 900, True),
]

PROBE = """JSON.stringify((() => {
  const f = document.querySelector('footer');
  const line = f.querySelector('.footer-center').getBoundingClientRect();
  const toggle = f.querySelector('.theme-toggle').getBoundingClientRect();
  const items = [...f.querySelectorAll('.footer-center a, .footer-center button')].filter(e => e.checkVisibility());
  const address = f.querySelector('.footer-address');
  return {
    height: Math.round(line.height), bottom: Math.round(line.bottom), top: Math.round(line.top),
    footerTop: Math.round(f.getBoundingClientRect().top), vh: innerHeight,
    left: Math.round(line.left), right: Math.round(line.right), width: innerWidth,
    lastRight: Math.round(Math.max(...items.map(e => e.getBoundingClientRect().right))),
    toggleLeft: Math.round(toggle.left),
    address: !!address && address.checkVisibility(),
    mapButton: !!f.querySelector('[data-on-click="kvot:toggleMap"]')?.checkVisibility(),
  };
})())"""

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


async def main():
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=64 * 1024 * 1024) as ws:
        n = 0
        pending = {}
        sid = None

        async def pump():
            async for raw in ws:
                r = json.loads(raw)
                if 'id' in r and r['id'] in pending:
                    pending.pop(r['id']).set_result(r)

        async def call(method, params=None):
            nonlocal n
            n += 1
            msg = {'id': n, 'method': method, 'params': params or {}}
            if sid and not method.startswith('Target.'):
                msg['sessionId'] = sid
            fut = asyncio.get_event_loop().create_future()
            pending[n] = fut
            await ws.send(json.dumps(msg))
            return await asyncio.wait_for(fut, 60)

        asyncio.create_task(pump())
        tid = (await call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        sid = (await call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
        await call('Page.enable')
        await call('Network.enable')
        await call('Network.setCacheDisabled', {'cacheDisabled': True})
        try:
            for page, width, height, address in CASES:
                await call('Emulation.setDeviceMetricsOverride',
                           {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': width < 600})
                await call('Page.navigate', {'url': f'http://127.0.0.1:{HTTP}/{page}?nocache={int(time.time() * 1000)}'})
                for _ in range(80):
                    r = await call('Runtime.evaluate', {'expression': "!!document.querySelector('footer .footer-center')", 'returnByValue': True})
                    if r['result']['result'].get('value'):
                        break
                    await asyncio.sleep(0.1)
                await asyncio.sleep(0.4)  # the footer's font
                r = await call('Runtime.evaluate', {'expression': PROBE, 'returnByValue': True})
                g = json.loads(r['result']['result']['value'])
                where = f'{page} at {width}px'
                check(f'{where}: the footer is one line', g['height'] <= 20, True)
                check(f'{where}: all of it is on the screen', [g['top'] >= g['footerTop'], g['bottom'] <= g['vh']], [True, True])
                check(f'{where}: nothing runs off the sides', [g['left'] >= 0, g['right'] <= g['width']], [True, True])
                check(f'{where}: the theme switch is clear of the last icon', g['lastRight'] <= g['toggleLeft'], True)
                check(f'{where}: the street address {"shows" if address else "gives way, the map button stays"}',
                      [g['address'], g['mapButton']], [address, True])
        finally:
            await call('Target.closeTarget', {'targetId': tid})
    print(f'\n{checks - len(failures)} of {checks} checks passed.')
    sys.exit(1 if failures else 0)


asyncio.run(main())
