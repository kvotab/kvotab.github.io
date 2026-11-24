"""rdc.html's bar under the header: the search, the page's buttons, and the full window.

The search for a radionuclide stood in the site's header, and the page's two
buttons, the chain as a PNG and the help, in its footer; a full window, which
hides both, would have taken them with it. Since 2026-11-24 they are in the
bar under the header (#databar), with the full window's button:

  - the search at the bar's start, out of the header, finding Cs-137 and
    drawing its chain; the header holds the page's name and nothing else,
    the footer none of the page's buttons;
  - at the bar's right end the PNG and the help, which opens;
  - the full window, the four corners at the end: no header or footer, the
    bar at the top of the window and the graph under it to the window's
    foot, the kvot mark (home) at the bar's left and the light/dark switch
    beside the button; cytoscape's own size follows its box; a nuclide's
    menu has the whole height under the bar (a hidden footer measures 0,
    which left it 120px at the top); kept in localStorage kvot.rdc.full and
    put on by the page's head before the first paint;
  - a phone: the search and the buttons on the bar's first line, the
    database under them, nothing wider than the screen, the search in 16px.

Serve the repository and start headless Chrome (the recipe is in README.md),
by default on ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose
others. Exit status is 0 when every check passes.
"""
import asyncio, json, os, sys, time, urllib.request
import websockets

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))

ERRORS = """window.__errors = [];
addEventListener('error', e => window.__errors.push(String(e.message)));
addEventListener('unhandledrejection', e => window.__errors.push('rejected: ' + e.reason));"""

# The page's state when the parser puts rdc.js in: the head's script has run,
# the page's own not yet (the button is not marked pressed), so only the head
# can have put the page in the full window.
EARLY = """new MutationObserver((records, observer) => {
  if (window.rdcEarly || !document.querySelector('script[src*="rdc.js"]')) return;
  const h = document.querySelector('body > header'), b = document.getElementById('rdcFull');
  window.rdcEarly = { full: document.documentElement.classList.contains('rdc-full'),
    header: h ? getComputedStyle(h).display : null,
    barTop: Math.round(document.getElementById('databar').getBoundingClientRect().top),
    corners: [...b.querySelectorAll('path')].map((p) => getComputedStyle(p).display),
    pressed: b.getAttribute('aria-pressed') };
  observer.disconnect();
}).observe(document, { childList: true, subtree: true });"""

FULL = """JSON.stringify((() => {
  const r = (q) => document.querySelector(q).getBoundingClientRect(), b = document.getElementById('rdcFull'),
    shown = (q) => { const e = document.querySelector(q); return !!e && getComputedStyle(e).display !== 'none'; };
  return { on: document.documentElement.classList.contains('rdc-full'),
    header: getComputedStyle(document.querySelector('body > header')).display,
    footer: getComputedStyle(document.querySelector('body > footer')).display,
    barTop: Math.round(r('#databar').top), barBottom: Math.round(r('#databar').bottom),
    cyTop: Math.round(r('#cy').top), cyBottom: Math.round(r('#cy').bottom), h: innerHeight,
    cyHeight: Math.round(CY.height()), cyBox: Math.round(r('#cy').height), navBottom: Math.round(r('nav').bottom),
    mark: shown('#databar .rdc-homelink'), theme: shown('#databar .theme-toggle'),
    corners: [...b.querySelectorAll('path')].map((p) => getComputedStyle(p).display),
    pressed: b.getAttribute('aria-pressed'), key: localStorage.getItem('kvot.rdc.full') };
})())"""


async def main():
    version = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json/version' % CDP))
    async with websockets.connect(version['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
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
                    if 'error' in reply:
                        raise AssertionError('%s: %s' % (method, reply['error']))
                    return reply

        async def ev(expression, session):
            reply = await cmd('Runtime.evaluate',
                              {'expression': expression, 'awaitPromise': True,
                               'returnByValue': True, 'timeout': 60000}, session)
            result = reply.get('result', {})
            if 'exceptionDetails' in result:
                raise AssertionError('page threw: ' + json.dumps(result['exceptionDetails'])[:400])
            return result.get('result', {}).get('value')

        async def settle(expression, session, tries=120, pause=0.25):
            got = None
            for _ in range(tries):
                try:
                    got = await ev(expression, session)
                except AssertionError:
                    got = None
                if got:
                    return got
                await asyncio.sleep(pause)
            return got

        failures = []
        passed = [0]

        def check(condition, message):
            if condition:
                passed[0] += 1
            else:
                failures.append(message)

        async def open_page(width=1400, height=900, mobile=False, early=''):
            target = (await cmd('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
            session = (await cmd('Target.attachToTarget', {'targetId': target, 'flatten': True}))['result']['sessionId']
            for method in ('Runtime.enable', 'Page.enable', 'Network.enable', 'DOM.enable'):
                await cmd(method, {}, session)
            await cmd('Network.setCacheDisabled', {'cacheDisabled': True}, session)
            await cmd('Page.addScriptToEvaluateOnNewDocument', {'source': ERRORS + early}, session)
            await cmd('Emulation.setDeviceMetricsOverride',
                      {'width': width, 'height': height, 'deviceScaleFactor': 2 if mobile else 1, 'mobile': mobile}, session)
            if mobile:
                await cmd('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5}, session)
            await cmd('Page.navigate', {'url': 'http://127.0.0.1:%d/rdc.html?n=%d' % (HTTP, int(time.time() * 1000))}, session)
            await settle("typeof CY !== 'undefined' && CY.nodes().length > 5", session)
            return target, session

        target, session = await open_page()
        try:
            await ev("localStorage.removeItem('kvot.rdc.full'); 1", session)
            # ── the search and the buttons, in the bar ────────────────────────
            where = json.loads(await ev("""JSON.stringify((() => {
              const bar = document.getElementById('databar'), header = document.querySelector('body > header'),
                footer = document.querySelector('body > footer'), s = document.getElementById('search-input');
              return { inBar: bar.contains(s), first: [...bar.children].filter(e => getComputedStyle(e).display !== 'none')[0] === s,
                headerInputs: header.querySelectorAll('input, button:not(.nav-toggle)').length,
                footerButtons: !!footer.querySelector('#print-decay-chain, #myBtn'),
                end: [...document.querySelectorAll('#databar .databar-end > button')].filter(b => getComputedStyle(b).display !== 'none').map(b => b.id || b.className),
                font: getComputedStyle(s).fontFamily === getComputedStyle(document.getElementById('dbSelect')).fontFamily,
                height: s.getBoundingClientRect().height === document.getElementById('dbSelect').getBoundingClientRect().height };
            })())""", session))
            check(where['inBar'] and where['first'], 'the search should be the first thing in the bar under the header: %r' % (where,))
            check(where['headerInputs'] == 0, 'the header should hold the page\'s name alone: %r' % (where,))
            check(not where['footerButtons'], 'the footer should hold none of the page\'s buttons')
            check(where['end'] == ['print-decay-chain', 'myBtn', 'rdcFull'],
                  'at the bar\'s right end: the PNG, the help and the full window, got %r' % (where['end'],))
            check(where['font'] and where['height'], 'the search is a field of the bar\'s, as tall as its menu: %r' % (where,))
            await ev("""(() => { const input = document.getElementById('search-input');
              input.value = 'Cs-137'; input.dispatchEvent(new Event('input', { bubbles: true })); return 1; })()""", session)
            found = await settle("($('#tree').jstree(true).get_selected(true)[0] || {}).text === 'Cs-137' && !CY.getElementById('Ba-137m').empty()", session)
            check(found, 'the search in the bar should choose Cs-137 and draw its chain')
            await ev("document.getElementById('myBtn').click(); 1", session)
            await asyncio.sleep(0.4)
            check(await ev("document.getElementById('myModal').open", session), 'the help button in the bar opens the help')
            check('four corners' in (await ev("document.getElementById('myModal').textContent", session)),
                  'and the help says what the bar\'s buttons do')
            await ev("document.querySelector('#myModal .help-close-button').click(); 1", session)

            # ── the full window ───────────────────────────────────────────────
            before = json.loads(await ev(FULL, session))
            check((before['on'], before['header'], before['footer'], before['mark'], before['theme'], before['corners'], before['pressed'])
                  == (False, 'grid', 'block', False, False, ['inline', 'none'], 'false'),
                  'the page should start with the site\'s header and footer, the mark and the switch hidden: %r' % (before,))
            await ev("document.getElementById('rdcFull').click(); 1", session)
            await asyncio.sleep(0.6)
            on = json.loads(await ev(FULL, session))
            check((on['on'], on['header'], on['footer'], on['barTop'], on['pressed'], on['key']) == (True, 'none', 'none', 0, 'true', '1'),
                  'the four corners should make the full window, the bar at the top: %r' % (on,))
            check(abs(on['cyTop'] - on['barBottom']) <= 1 and abs(on['cyBottom'] - on['h']) <= 1 and on['h'] - on['navBottom'] <= 1,
                  'the graph and the element list from the bar to the window\'s foot (the header and footer were written in as 74px): %r' % (on,))
            check(abs(on['cyHeight'] - on['cyBox']) <= 1, 'cytoscape\'s own size follows its box: %r' % (on,))
            check((on['mark'], on['theme'], on['corners']) == (True, True, ['none', 'inline']),
                  'the kvot mark at the bar\'s left, the light/dark switch beside the button, which points in: %r' % (on,))
            check(await ev("document.querySelector('#databar .rdc-homelink').getAttribute('href')", session) == './index.html', 'the mark goes home')
            menu = json.loads(await ev("""JSON.stringify((() => { positionNodeMenu(300, innerHeight - 40);
              const m = NODE_MENU.getBoundingClientRect(), bar = document.getElementById('databar').getBoundingClientRect(),
                out = { top: Math.round(m.top), bottom: Math.round(m.bottom), max: parseFloat(NODE_MENU.style.maxHeight), h: innerHeight, bar: Math.round(bar.bottom) };
              closeNodeMenu(); return out; })())""", session))
            check(menu['max'] >= menu['h'] - menu['bar'] - 16 - 1 and menu['bottom'] <= menu['h'] - 8 and menu['top'] >= menu['bar'] + 8,
                  'a nuclide\'s menu has the height under the bar, and stays off the window\'s foot: %r' % (menu,))
            theme0 = await ev("document.documentElement.getAttribute('data-theme')", session)
            await ev("document.querySelector('#databar .theme-toggle').click(); 1", session)
            theme1 = await ev("document.documentElement.getAttribute('data-theme')", session)
            check(theme1 != theme0 and theme1 in ('light', 'dark'), 'the switch switches light and dark: %r -> %r' % (theme0, theme1))
            await ev("document.querySelector('#databar .theme-toggle').click(); 1", session)
        finally:
            await cmd('Target.closeTarget', {'targetId': target})

        # The next visit: in the full window before the page's script runs.
        target, session = await open_page(early=EARLY)
        try:
            early = await ev('window.rdcEarly || null', session)
            check(early == {'full': True, 'header': 'none', 'barTop': 0, 'corners': ['none', 'inline'], 'pressed': 'false'},
                  'the next visit should be in the full window before the page\'s script runs: %r' % (early,))
            check((json.loads(await ev(FULL, session)))['pressed'] == 'true', 'and once it has run, its button is pressed')
            await ev("document.getElementById('rdcFull').click(); 1", session)
            await asyncio.sleep(0.6)
            off = json.loads(await ev(FULL, session))
            check((off['on'], off['header'], off['footer'], off['key']) == (False, 'grid', 'block', '0'),
                  'the button again: the header and footer back, and remembered so: %r' % (off,))
            errors = await ev('window.__errors', session)
            check(errors == [], 'the page should raise nothing, got %r' % (errors,))
            await ev("localStorage.removeItem('kvot.rdc.full'); 1", session)
        finally:
            await cmd('Target.closeTarget', {'targetId': target})

        # ── a phone ───────────────────────────────────────────────────────────
        target, session = await open_page(390, 664, mobile=True)
        try:
            await asyncio.sleep(0.6)
            phone = json.loads(await ev("""JSON.stringify((() => {
              const r = (q) => document.querySelector(q).getBoundingClientRect(), s = r('#search-input'), end = r('#databar .databar-end'),
                db = r('#dbSelect');
              return { line1: Math.abs(s.top - end.top) < 4 && s.right <= end.left, under: db.top >= s.bottom,
                inside: end.right <= innerWidth, wide: document.documentElement.scrollWidth <= innerWidth,
                font: getComputedStyle(document.getElementById('search-input')).fontSize };
            })())""", session))
            check(phone['line1'] and phone['under'], 'phone: the search and the buttons on the first line, the database under them: %r' % (phone,))
            check(phone['inside'] and phone['wide'], 'phone: the buttons on the screen, nothing wider than it: %r' % (phone,))
            check(phone['font'] == '16px', 'phone: the search in 16px, which iOS does not zoom into: %r' % (phone,))
            errors = await ev('window.__errors', session)
            check(errors == [], 'the page should raise nothing on a phone, got %r' % (errors,))
        finally:
            await cmd('Target.closeTarget', {'targetId': target})

        if failures:
            print('%d of %d check(s) failed:' % (len(failures), len(failures) + passed[0]))
            for failure in failures:
                print('  - ' + failure)
            sys.exit(1)
        print('%d checks passed: rdc.html\'s bar holds the search and the page\'s buttons, and gives the page a full window.' % passed[0])


asyncio.run(main())
