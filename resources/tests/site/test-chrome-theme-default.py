"""Which theme a page starts in, given the system setting and what is stored.

uppsala.html and solna.html fill the screen on a phone and hide the site
chrome, theme toggle included - so a visitor whose phone is set to dark got a
dark board and no way to change it. Below the layout's own 560px breakpoint
those two pages pin light as the *default*.

A default is not an override, and the distinction is the whole reason this file
exists: a theme the visitor has actually chosen still wins, every other page is
untouched, and a desktop-width board still follows the system. Each of those is
a row in the table below, so a change that fixes the phone by breaking one of
them cannot pass.

The system setting is emulated with Emulation.setEmulatedMedia rather than
trusted from the host, and localStorage is set before navigation so the page's
own boot snippet sees it.
"""
import asyncio, json, sys, time, urllib.request, websockets

# page, viewport width, system scheme, stored choice, expected theme
CASES = [
    ('uppsala.html', 390, 'dark', None, 'light'),
    ('solna.html', 390, 'dark', None, 'light'),
    ('uppsala.html', 390, 'light', None, 'light'),
    # Wide enough for the chrome to be back, so the system decides again.
    ('uppsala.html', 1280, 'dark', None, 'dark'),
    # Any other page is none of this file's business.
    ('index.html', 390, 'dark', None, 'dark'),
    ('rdc.html', 390, 'dark', None, 'dark'),
    # An explicit choice beats the pinned default, in both directions.
    ('uppsala.html', 390, 'dark', 'dark', 'dark'),
    ('uppsala.html', 390, 'light', 'dark', 'dark'),
    ('uppsala.html', 1280, 'dark', 'light', 'light'),
]

PROBE = """JSON.stringify({
  theme: document.documentElement.getAttribute('data-theme'),
  pinned: document.documentElement.getAttribute('data-theme-default'),
  bodyBg: getComputedStyle(document.body).backgroundColor
})"""


async def run(ws, page, width, scheme, stored):
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
    n = [10]

    async def call(method, params=None):
        n[0] += 1
        mid = n[0]
        msg = {'id': mid, 'method': method, 'sessionId': sid}
        if params: msg['params'] = params
        await ws.send(json.dumps(msg))
        while True:
            mm = json.loads(await ws.recv())
            if mm.get('id') == mid: return mm

    await call('Page.enable')
    await call('Network.enable')
    await call('Network.setCacheDisabled', {'cacheDisabled': True})
    await call('Emulation.setDeviceMetricsOverride',
               {'width': width, 'height': 844, 'deviceScaleFactor': 1, 'mobile': width < 600})
    await call('Emulation.setEmulatedMedia',
               {'features': [{'name': 'prefers-color-scheme', 'value': scheme}]})
    # Before navigation: the page decides its theme in a <head> snippet, so a
    # value written after load would be read too late to matter.
    await call('Page.addScriptToEvaluateOnNewDocument', {'source':
        ("try{localStorage.setItem('kvot-theme','%s')}catch(e){}" % stored) if stored
        else "try{localStorage.removeItem('kvot-theme')}catch(e){}"})
    await call('Page.navigate',
               {'url': 'http://127.0.0.1:8765/%s?nocache=%d' % (page, int(time.time() * 1000))})
    await asyncio.sleep(3.5)
    m = await call('Runtime.evaluate', {'expression': PROBE, 'returnByValue': True})
    value = m.get('result', {}).get('result', {}).get('value')
    await ws.send(json.dumps({'id': 999, 'method': 'Target.closeTarget',
                              'params': {'targetId': tid}}))
    return json.loads(value) if value else {}


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    failures = []
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as ws:
        for page, width, scheme, stored, want in CASES:
            r = await run(ws, page, width, scheme, stored)
            got = r.get('theme')
            ok = got == want
            if not ok: failures.append((page, width, scheme, stored, want, got))
            print('%-14s %5dpx  system=%-5s stored=%-5s -> %-5s %-12s pinned=%-5s bg=%s' % (
                page, width, scheme, stored or '-', got,
                'OK' if ok else 'WANTED ' + str(want), str(r.get('pinned')), r.get('bodyBg')))
    print()
    print('%d/%d as intended' % (len(CASES) - len(failures), len(CASES)))
    for f in failures:
        print('  FAILED: %s at %dpx, system %s, stored %s -> wanted %s, got %s' % f)
    sys.exit(1 if failures else 0)


asyncio.run(main())
