"""The full window on the tool pages that have it from kvot-fullwin.js.

Since 2026-11-24 seventeen pages have the button with four corners that takes
the site's header and footer away (resources/js/kvot-fullwin.js and
resources/css/kvot-fullwin.css; the pages with a full window of their own
before that, such as distributions.html and rdc.html, have their own tests).
For each page:

  - at first the site's header and footer, the button in the page's own bar,
    not pressed, and neither the kvot mark nor the light/dark switch beside it;
  - the button: no header or footer, the page's box from the window's top to
    its foot, one kvot mark (the page's own where it has one, gitarr and
    piano), the light/dark switch, which switches, the button pressed and
    saying so in the page's language, the window told of its new size, and
    nothing wider than the window; kept in localStorage kvot.full.<page>;
  - the next visit: in the full window from the head's script, before the
    page's body is read, and the buttons in their place as soon as the
    parser puts it in, so no paint shows the bar without them;
  - the button again: the header and footer back, and remembered so;
  - a phone: the button on the screen, or none where the page never shows
    the site's header and footer on a phone (gitarr, piano, the SL boards);
  - nothing raised.

Serve the repository and start headless Chrome with --mute-audio (the recipe
is in README.md; gitarr, piano and karaoke can make sounds), by default on
ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose others. FW_PAGES
(comma-separated names without .html) runs some of the pages only. Exit
status is 0 when every check passes.
"""
import asyncio, json, os, sys, time, urllib.request
import websockets

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))

# page: the box that fills the window, whether the page shows a mark and a
# switch of its own (the button alone, data-parts="full"), whether a phone
# has it (no: the page is always without the site's chrome there), the language
PAGES = {
    'FARF31': {}, 'SimpleFunctions': {}, 'erosion_corrosion': {}, 'zoterify': {},
    'gitarr': {'own': True, 'phone': False, 'sv': True},
    'piano': {'own': True, 'phone': False, 'sv': True},
    'blockmodellen': {'own': True, 'phone': False, 'sv': True},
    'karaoke': {'box': '.karaoke-wrap', 'sv': True},
    'logn': {}, 'arsredovisning': {'sv': True}, 'inkomstdeklaration': {'sv': True},
    'proj': {}, 'skb_qa_summary': {}, 'skbref': {},
    'solna': {'phone': False}, 'uppsala': {'phone': False},
    'svensk_text': {}, 'vectorize': {},
}

ERRORS = """window.__errors = [];
addEventListener('error', e => window.__errors.push(String(e.message)));
addEventListener('unhandledrejection', e => window.__errors.push('rejected: ' + e.reason));
window.__resized = 0; addEventListener('resize', () => window.__resized++);"""

# The first visit starts without the setting; the head's script reads it
# before any test code could remove it.
CLEAR = "\ntry { localStorage.removeItem('kvot.full.%s'); } catch (e) {}"

# The next visit: is the page in the full window when the parser reaches the
# body (the head's script alone can have done it), and is each place for the
# buttons filled as soon as it is in? This observer is made before the page's
# own, so it hears of a place first, still empty; by its next call the
# page's observer has filled it, in the same turn, before the browser could
# paint. A place filled later (at DOMContentLoaded, say) is still empty then:
# a paint on a slow network would show the bar without its buttons.
EARLY = """window.__early = null; window.__places = 0; window.__late = [];
const __seen = new Set();
new MutationObserver(() => {
  if (document.body && !window.__early)
    window.__early = { full: document.documentElement.classList.contains('kvot-full') };
  for (const place of __seen) if (!place.firstChild && !window.__late.includes(place.className)) window.__late.push(place.className);
  document.querySelectorAll('.kvot-fullwin, .kvot-fullwin-home').forEach((place) => {
    if (!__seen.has(place)) { __seen.add(place); window.__places++; } });
}).observe(document, { childList: true, subtree: true });"""

STATE = """JSON.stringify((() => {
  const q = (s) => document.querySelector(s), b = q('.kvot-fullbtn'),
    shown = (e) => !!e && getComputedStyle(e).display !== 'none' && e.getClientRects().length > 0,
    box = q(%s), r = box && box.getBoundingClientRect(), br = b && b.getBoundingClientRect();
  return { on: document.documentElement.classList.contains('kvot-full'),
    header: shown(q('body > header')), footer: shown(q('body > footer')),
    button: shown(b), right: br ? Math.round(br.right) : null, pressed: b && b.getAttribute('aria-pressed'),
    label: b && b.getAttribute('aria-label'),
    marks: [...document.querySelectorAll('img[src*="kvot-logotype"]')].filter(shown).length,
    homeHref: (q('.kvot-fullwin-mark') || {}).getAttribute ? q('.kvot-fullwin-mark').getAttribute('href') : null,
    theme: [...document.querySelectorAll('.kvot-fullwin .theme-toggle')].filter(shown).length,
    empty: document.querySelectorAll('.kvot-fullwin:empty').length,
    top: r ? Math.round(r.top) : null, bottom: r ? Math.round(r.bottom) : null, h: innerHeight, w: innerWidth,
    wide: document.documentElement.scrollWidth, resized: window.__resized,
    key: localStorage.getItem('kvot.full.' + %s), errors: window.__errors };
})())"""


async def main():
    only = [p for p in os.environ.get('FW_PAGES', '').split(',') if p]
    pages = [p for p in PAGES if not only or p in only]
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

        failures = []
        passed = [0]

        def check(condition, message):
            if condition:
                passed[0] += 1
            else:
                failures.append(message)

        async def open_page(page, width=1280, height=800, mobile=False, early=''):
            target = (await cmd('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
            session = (await cmd('Target.attachToTarget', {'targetId': target, 'flatten': True}))['result']['sessionId']
            for method in ('Runtime.enable', 'Page.enable'):
                await cmd(method, {}, session)
            await cmd('Page.addScriptToEvaluateOnNewDocument', {'source': ERRORS + early}, session)
            await cmd('Emulation.setDeviceMetricsOverride',
                      {'width': width, 'height': height, 'deviceScaleFactor': 2 if mobile else 1, 'mobile': mobile}, session)
            if mobile:
                await cmd('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5}, session)
            await cmd('Page.navigate', {'url': 'http://127.0.0.1:%d/%s.html?n=%d' % (HTTP, page, int(time.time() * 1000))}, session)
            for _ in range(120):
                try:
                    if await ev("document.readyState === 'complete'", session):
                        break
                except AssertionError:
                    pass
                await asyncio.sleep(0.25)
            await asyncio.sleep(0.8)
            return target, session

        for page in pages:
            spec = PAGES[page]
            box = json.dumps(spec.get('box', '.content'))
            state_js = STATE % (box, json.dumps(page))
            sv = spec.get('sv', False)

            async def state(session):
                return json.loads(await ev(state_js, session))

            target, session = await open_page(page, early=CLEAR % page)
            try:
                s0 = await state(session)
                check(s0['header'] and s0['footer'] and not s0['on'], '%s: at first the header and footer: %r' % (page, s0))
                check(s0['button'] and s0['pressed'] == 'false' and s0['empty'] == 0,
                      '%s: the button in the page\'s bar, not pressed: %r' % (page, s0))
                check(s0['marks'] == 0 and s0['theme'] == 0, '%s: no mark or switch beside it yet: %r' % (page, s0))
                check(s0['label'] == ('Hela fönstret' if sv else 'Full window'), '%s: the button says what it does: %r' % (page, s0['label']))
                resized = s0['resized']
                await ev("document.querySelector('.kvot-fullbtn').click(); 1", session)
                await asyncio.sleep(0.5)
                s1 = await state(session)
                check(s1['on'] and not s1['header'] and not s1['footer'] and s1['key'] == '1',
                      '%s: the button makes the full window, kept: %r' % (page, s1))
                check(s1['top'] == 0 and s1['bottom'] >= s1['h'] - 1,
                      '%s: the page\'s box from the window\'s top to its foot: %r' % (page, s1))
                check(s1['marks'] == 1, '%s: one kvot mark in the full window: %r' % (page, s1))
                if not spec.get('own'):
                    check(s1['homeHref'] == './index.html' and s1['theme'] == 1,
                          '%s: the mark goes home, the switch beside the button: %r' % (page, s1))
                check(s1['pressed'] == 'true' and s1['label'] == ('Lämna hela fönstret' if sv else 'Leave the full window'),
                      '%s: the button pressed, and saying so: %r' % (page, s1))
                check(s1['resized'] > resized, '%s: the window told of its new size: %r' % (page, s1))
                check(s1['wide'] <= s1['w'], '%s: nothing wider than the window: %r' % (page, s1))
                switch = '.kvot-fullwin .theme-toggle' if not spec.get('own') else '.theme-toggle:not(footer .theme-toggle)'
                theme0 = await ev("document.documentElement.getAttribute('data-theme')", session)
                stored = await ev("localStorage.getItem('kvot-theme')", session)
                await ev("[...document.querySelectorAll(%s)].find(b => b.getClientRects().length).click(); 1" % json.dumps(switch), session)
                theme1 = await ev("document.documentElement.getAttribute('data-theme')", session)
                check(theme1 != theme0 and theme1 in ('light', 'dark'), '%s: the switch switches: %r -> %r' % (page, theme0, theme1))
                await ev("[...document.querySelectorAll(%s)].find(b => b.getClientRects().length).click(); 1" % json.dumps(switch), session)
                if stored is None:
                    await ev("localStorage.removeItem('kvot-theme'); 1", session)
            finally:
                await cmd('Target.closeTarget', {'targetId': target})

            target, session = await open_page(page, early=EARLY)
            try:
                early = await ev('window.__early', session)
                places = await ev('[window.__places, window.__late]', session)
                check(early == {'full': True}, '%s: the next visit in the full window before the body is read: %r' % (page, early))
                check(places[0] > 0 and places[1] == [],
                      '%s: each place for the buttons filled as it is read (places, filled late): %r' % (page, places))
                s2 = await state(session)
                check(s2['on'] and not s2['header'] and s2['pressed'] == 'true', '%s: and so once loaded: %r' % (page, s2))
                await ev("document.querySelector('.kvot-fullbtn').click(); 1", session)
                await asyncio.sleep(0.5)
                s3 = await state(session)
                check(not s3['on'] and s3['header'] and s3['footer'] and s3['key'] == '0' and s3['pressed'] == 'false',
                      '%s: the button again: the header and footer back, remembered: %r' % (page, s3))
                check(s3['errors'] == [], '%s: nothing raised: %r' % (page, s3['errors']))
                await ev("localStorage.removeItem('kvot.full.%s'); 1" % page, session)
            finally:
                await cmd('Target.closeTarget', {'targetId': target})

            target, session = await open_page(page, 390, 844, mobile=True, early=CLEAR % page)
            try:
                s4 = await state(session)
                if spec.get('phone', True):
                    check(s4['button'] and s4['right'] <= s4['w'], '%s: phone: the button on the screen: %r' % (page, s4))
                else:
                    check(not s4['button'] and not s4['header'],
                          '%s: phone: no button, the page is without the site\'s chrome there anyway: %r' % (page, s4))
                check(s4['errors'] == [], '%s: phone: nothing raised: %r' % (page, s4['errors']))
            finally:
                await cmd('Target.closeTarget', {'targetId': target})
            print('%s done' % page, flush=True)

        if failures:
            print('%d of %d check(s) failed:' % (len(failures), len(failures) + passed[0]))
            for failure in failures:
                print('  - ' + failure)
            sys.exit(1)
        print('%d checks passed: the full window on %d pages.' % (passed[0], len(pages)))


asyncio.run(main())
