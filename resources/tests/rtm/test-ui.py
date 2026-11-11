#!/usr/bin/env python3
"""rtm.html in a real browser: does the page actually do the thing.

test-model.js proves the mathematics. This proves the wiring — that the text
compiles through the worker, that a run reaches the charts, that the two chart
tabs draw what they claim to, and that a model which does not compile says so
instead of failing silently.

Start the server and the browser as in ../rb/README.md (on ports 8765 and
9222, or on others named by RTM_HTTP_PORT and RTM_CDP_PORT), then

    python3 resources/tests/rtm/test-ui.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import math
import os
import re
import sys
import tempfile
import urllib.request

import websockets

HTTP = int(os.environ.get('RTM_HTTP_PORT', '8765'))
CDP = int(os.environ.get('RTM_CDP_PORT', '9222'))

# Chrome's rule for a control inside a <summary> ("An interactive element was
# found within a <summary> element"): the summaries that break it, or ''.
NO_CONTROL_IN_SUMMARY = (
    "[...document.querySelectorAll('summary')].filter((s) => s.querySelector('a[href], audio[controls], button,"
    " details, embed, iframe, img[usemap], input:not([type=hidden]), label, object[usemap], select, textarea,"
    " video[controls], [tabindex], [contenteditable]')).map((s) => s.textContent.trim()).join(' | ')")
# The headings whose (i), in the slot before their <details>, is not centred
# on the summary's line and at its end, or ''; %s is the box holding the two.
HEADING_I_OFF = (
    "[...document.querySelectorAll('%s > details')].filter((d) => {"
    " const s = d.querySelector(':scope > summary');"
    " const b = d.previousElementSibling && d.previousElementSibling.querySelector('.info-btn');"
    " if (!s || !b || !s.getClientRects().length) return false;"
    " const cs = getComputedStyle(s), r = s.getBoundingClientRect(), q = b.getBoundingClientRect();"
    " const px = (v) => parseFloat(v) || 0;"
    " const top = r.top + px(cs.borderTopWidth) + px(cs.paddingTop);"
    " const bottom = r.bottom - px(cs.borderBottomWidth) - px(cs.paddingBottom);"
    " const right = r.right - px(cs.borderRightWidth) - px(cs.paddingRight);"
    " return Math.abs((q.top + q.bottom) / 2 - (top + bottom) / 2) > 0.5 || Math.abs(q.right - right) > 0.5;"
    "}).map((d) => d.querySelector('summary').textContent.trim()).join(' | ')")

# The (i) slots written into rtm.html: two section headings, twenty settings
# of the Solver section, eleven tab toolbars, and the PHREEQC panel's heading and
# four settings.
STATIC_SLOTS = 40

PAINTED = """(() => {
  const c = document.getElementById('rtmJacCanvas');
  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  const seen = new Map();
  for (let i = 0; i < d.length; i += 4) {
    const k = (d[i] << 16) | (d[i + 1] << 8) | d[i + 2];
    seen.set(k, (seen.get(k) || 0) + 1);
  }
  // The background is the commonest colour: the pattern is far from full.
  let bg = 0;
  for (const [, n] of seen) bg = Math.max(bg, n);
  return 1 - bg / (c.width * c.height);
})()"""

URL = f'http://127.0.0.1:{HTTP}/rtm.html'

failures = []
checks = 0


# A water with an activity model, acid added at a rate, a phase it is far from and an output of its own, and a pH
# measured at 500 s: what the quantities block of the checks runs.
QUANTITY_MODEL = '''
<SETTINGS>
MODE = batch
TEND = 1000
ACTIVITY = davies
EQUILIBRATE = always

<SPECIES>
H+      1e-7
OH-     1e-7
Na+     1e-3
Cl-     1e-3

<REACTIONS>
=> H+ + Cl-, r = 1e-6

<EQUILIBRIUM>
 <=> H+ + OH-, logK = -14

<PHASES>
Halite <=> Na+ + Cl-, logK = 1.57

<OUTPUT>
acid = [H+] - [OH-], unit = mol/kgw

<DATA>
time  pH   cell = 0
500   3.3
'''


# A water whose major ions are round numbers -- Ca 2.2, Mg 1, Na + K 2.1, Cl 2, SO4 1 and HCO3 + CO3 3 meq/kgw -- and a
# calcite that dissolves too slowly to change them, and a water measured at 50 s: what the composition block runs.
COMP_MODEL = '''
<SETTINGS>
MODE = batch
TEND = 100
ACTIVITY = davies

<SPECIES>
Ca+2     1e-3
Mg+2     5e-4
Na+      2e-3
K+       1e-4
Cl-      2e-3
SO4-2    4e-4
CaSO4    1e-4
HCO3-    2.9e-3
CO3-2    5e-5
Calcite  2e-3  mineral

<REACTIONS>
Calcite => Ca+2 + CO3-2, r = 1e-30

<DATA>
time  tot(Ca)  Mg+2  Na+   K+    Cl-   tot(S)  alk(CO3)  cell = 0
50    1e-3     5e-4  3e-3  1e-4  3e-3  5e-4    2.5e-3
'''

# A carbonate water without activities: its carbon's shares against pH are Bjerrum's fractions, what the diagrams block
# checks them against.
DIAGRAM_MODEL = '''
<SETTINGS>
MODE = batch
TEND = 1
EQUILIBRATE = 1

<SPECIES>
H+      1e-7
OH-     1e-7
Na+     3e-3
CO2     1e-4
HCO3-   2e-3
CO3-2   1e-5

<EQUILIBRIUM>
 <=> H+ + OH-,          logK = -14
CO2 <=> H+ + HCO3-,     logK = -6.352
HCO3- <=> H+ + CO3-2,   logK = -10.329
'''

# Four ions that only mix: the same D, no reactions, a different water flowing in. Every water of the column is the two end
# members mixed, so principal components of them, taken as they are, are one component; a water measured half and half lies
# on it.
MIX_MODEL = '''
<SETTINGS>
MODE = transport
CELLS = 5
LENGTH = 0.05
VELOCITY = 1e-5
DIFFUSION = 1
ADVECTION = 1
LEFT = robin
RIGHT = free
TEND = 2e4

<SPECIES>
Na+     1e-3    D=1e-9  left=1e-2
Cl-     1.2e-3  D=1e-9  left=1.1e-2
Ca+2    2e-3    D=1e-9  left=1e-3
SO4-2   5e-4    D=1e-9  left=3e-3

<DATA>
time  Na+  Cl-  Ca+2  SO4-2  cell = 4
5000  5.5e-3  6.1e-3  1.5e-3  1.75e-3
'''

# A first-order decay at a rate kk of <PARAMETERS>: a sweep of kk leaves exp(-kk t) of A, what the sweeps block checks.
# One couple, iron(3) over iron(2), no complexes and no activities: it turns over where the two are as much, at pe 13.02
# whatever the pH, the relation's log K by hand.
LADDER_MODEL = '''
<SETTINGS>
MODE = batch
TEND = 1
EQUILIBRATE = always

<SPECIES>
H+    1e-3
OH-   1e-11
e-    electron  pe=12
Fe+2  1e-5
Fe+3  1e-5
Cl-   5e-5

<EQUILIBRIUM>
 <=> H+ + OH-, logK = -14
Fe+2 <=> Fe+3 + e-, logK = -13.02
'''

# Two couples, no complexes and no activities: iron(3) over iron(2) turns over at pe 13.02 whatever the pH; sulfate over
# sulfide where log K = 9 pH + 8 pe, pe = (33.65 - 9 pH)/8.
COUPLES_MODEL = '''
<SETTINGS>
MODE = batch
TEND = 1
EQUILIBRATE = always

<SPECIES>
H+     1e-3
OH-    1e-11
e-     electron  pe=12
Fe+2   1e-5
Fe+3   1e-5
SO4-2  1e-4
HS-    0
Na+    2.3e-4
Cl-    5e-5

<EQUILIBRIUM>
 <=> H+ + OH-, logK = -14
Fe+2 <=> Fe+3 + e-, logK = -13.02
SO4-2 + 9 H+ + 8 e- <=> HS- + 4 H2O, logK = 33.65
'''

SWEEP_MODEL = '''
<SETTINGS>
MODE = batch
TEND = 10

<SPECIES>
A  1
B  0

<PARAMETERS>
kk  all  0.1

<REACTIONS>
A => B, r = kk*[A]
'''

# A decay at a rate kk and a number zz that nothing reads: drawn for the uncertainty bands, A's percentiles at the end are
# exp(-10 kk) at kk's order statistics, and zz matters not at all.
UNCERTAIN_MODEL = '''
<SETTINGS>
MODE = batch
TEND = 10

<SPECIES>
A  1
B  0

<PARAMETERS>
kk  all  0.25
zz  all  3

<REACTIONS>
A => B, r = kk*[A]
B => , r = 0*zz*[B]
'''

def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


class Page:
    def __init__(self, bws):
        self.bws = bws
        self.n = 0
        self.pending = {}
        self.sid = None
        self.errors = []

    async def call(self, method, params=None, session=None):
        self.n += 1
        i = self.n
        msg = {'id': i, 'method': method, 'params': params or {}}
        if session:
            msg['sessionId'] = session
        fut = asyncio.get_event_loop().create_future()
        self.pending[i] = fut
        await self.bws.send(json.dumps(msg))
        return await asyncio.wait_for(fut, 600)

    async def pump(self):
        async for raw in self.bws:
            r = json.loads(raw)
            if r.get('method') == 'Runtime.exceptionThrown':
                d = r['params']['exceptionDetails']
                self.errors.append(str(d.get('exception', {}).get('description') or d.get('text', ''))[:200])
            if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                self.pending[r['id']].set_result(r)

    async def ev(self, expr, timeout=600):
        r = await self.call('Runtime.evaluate',
                            {'expression': expr, 'returnByValue': True, 'awaitPromise': True},
                            session=self.sid)
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:200]
        return res.get('result', {}).get('value')


async def settle(page, expr, want, tries=240, pause=1.0):
    got = None
    for _ in range(tries):
        got = await page.ev(expr)
        if got == want:
            return got
        await asyncio.sleep(pause)
    return got


async def wait_run(page):
    """Wait for the status line to stop saying it is running."""
    status = ''
    for _ in range(300):
        await asyncio.sleep(1)
        status = await page.ev("document.getElementById('rtmStatus').textContent")
        if isinstance(status, str) and (status.startswith('Done') or status.startswith('The run failed')
                                        or status.startswith('Stopped')):
            break
    return status


async def set_text(page, text):
    await page.ev("""(() => {
      const t = document.getElementById('rtmText');
      t.value = %s;
      t.dispatchEvent(new Event('input', { bubbles: true }));
    })()""" % json.dumps(text))


async def press(page, sel):
    """A click with the mouse at the middle of the element, so that whatever lies on top of it is what is hit."""
    x, y = await page.ev("(() => { const e = document.querySelector(%s); e.scrollIntoView({ block: 'nearest' });"
                         " const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()"
                         % json.dumps(sel))
    for kind in ('mouseMoved', 'mousePressed', 'mouseReleased'):
        await page.call('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1},
                        session=page.sid)
    await asyncio.sleep(0.3)


async def main():
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        page = Page(bws)
        asyncio.create_task(page.pump())
        # The HDF5 button below really downloads, and a headless Chrome saves
        # into ~/Downloads: sixty megabytes a run, left behind. The check reads
        # what the page says it wrote, so the file itself is refused.
        await page.call('Browser.setDownloadBehavior', {'behavior': 'deny'})
        tid = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        page.sid = (await page.call('Target.attachToTarget',
                                    {'targetId': tid, 'flatten': True}))['result']['sessionId']
        await page.call('Runtime.enable', session=page.sid)
        await page.call('Page.enable', session=page.sid)
        await page.call('Emulation.setDeviceMetricsOverride',
                        {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False},
                        session=page.sid)
        await page.call('Network.setCacheDisabled', {'cacheDisabled': True}, session=page.sid)
        # A clean slate: the page keeps the model text in localStorage, so a
        # run left over from a previous pass would be what is tested.
        await page.call('Page.addScriptToEvaluateOnNewDocument',
                        {'source': "try{localStorage.removeItem('kvot-rtm-v1')}catch(e){}"},
                        session=page.sid)
        # Nor a full window left on by an interrupted run. rtm.html's head reads
        # that before anything else, so it is cleared first, from a file of the
        # same origin that runs no script.
        await page.call('Page.navigate', {'url': f'http://127.0.0.1:{HTTP}/resources/css/rtm.css'}, session=page.sid)
        await settle(page, 'document.readyState', 'complete', tries=40, pause=0.25)
        await page.ev("localStorage.removeItem('kvot.rtm.full')")
        await page.call('Page.navigate', {'url': URL}, session=page.sid)
        try:
            await asyncio.sleep(5)
            status = await settle(page, "document.getElementById('rtmStatus')"
                                        ".textContent.slice(0, 9)", 'Compiled:')
            check('the built-in model compiles on load', status, 'Compiled:')
            check('and the panel says what is being solved', await page.ev(
                "document.getElementById('rtmFacts').textContent.startsWith('transport')"), True)
            check('the species picker is filled, the species first and then the quantities', await page.ev(
                "[document.querySelectorAll('#rtmSeries .rtm-item[data-group=\"species\"]').length,"
                " [...document.querySelectorAll('#rtmSeries .rtm-item:not([data-group=\"species\"]) input')]"
                ".map((i) => i.value).join(' ')]"),
                [36, 'pH I charge tot(C) alk(CO3) ' + ' '.join(f'rate({n}) extent({n})' for n in range(1, 128))])
            check('  what each of its 127 reactions does, a group shut until it is opened: a network\'s 254 entries', await page.ev(
                "(() => { const h = document.querySelector('#rtmSeries .rtm-series-head[data-group=\"reactions\"]');"
                " const items = [...document.querySelectorAll('#rtmSeries .rtm-item[data-group=\"reactions\"]')];"
                " return [h ? h.getAttribute('aria-expanded') : null, items.length, items.every((e) => e.hidden)]; })()"),
                ['false', 254, True])
            check('and there is a cell to choose, or an end of the column', await page.ev(
                "[...document.getElementById('rtmCell').options].map((o) => o.value).slice(18).join(',')"),
                '18,19,left,right')

            # --- the (i) beside each setting, section and tab toolbar ----------
            # kvot-info.js fills the slots of rtm.html from the topics in
            # rtm-ui.js. They replace the hover tooltips the settings had, so
            # none may be left on the panel or a toolbar.
            audit = await page.ev("KvotInfo.audit()")
            audit = audit if isinstance(audit, dict) else {'noTopic': audit, 'brokenMore': audit, 'buttons': 0, 'slots': -1}
            check('every (i) slot has a topic', audit['noTopic'], [])
            check('and every "Read more in Help" has its heading', audit['brokenMore'], [])
            check(f'an (i) in every slot, at least the {STATIC_SLOTS} of the markup ({audit["buttons"]})',
                  audit['buttons'] >= STATIC_SLOTS and audit['buttons'] == audit['slots'], True)
            # A section heading's (i) is in the slot before its <details>, not in the
            # summary: Chrome reports every control inside a <summary>.
            check('no (i) slot is inside a <summary>', audit.get('inSummary'), [])
            check('nor any other control inside a <summary>', await page.ev(NO_CONTROL_IN_SUMMARY), '')
            check('each heading\'s (i) is centred on its line, at its end', await page.ev(HEADING_I_OFF % '.kvot-info-sec'), '')
            check('no hover tooltip is left on a setting or a toolbar', await page.ev(
                "document.querySelectorAll('.rtm-side [title], .rtm-toolbar [title]').length"), 0)
            await page.ev("document.querySelector('[data-info=\"set:rtol\"]').click()")
            check('clicking an (i) opens the panel with its title', await page.ev(
                "document.querySelector('#kvot-info-panel .info-panel-title').textContent"), 'Relative tolerance')
            check('  and marks that (i) open', await page.ev(
                "document.querySelector('[data-info=\"set:rtol\"]').getAttribute('aria-expanded')"), 'true')
            check('  the panel lying between the header and the footer', await page.ev(
                "(() => { const p = document.getElementById('kvot-info-panel').getBoundingClientRect();"
                " const h = document.querySelector('header').getBoundingClientRect();"
                " const f = document.querySelector('footer').getBoundingClientRect();"
                " return Math.abs(p.top - h.bottom) <= 1 && Math.abs(p.bottom - f.top) <= 1; })()"), True)
            await page.ev("document.querySelector('#kvot-info-panel .info-panel-close').click()")
            check('its × closes it', await page.ev("!document.getElementById('kvot-info-panel')"), True)
            await page.ev("document.querySelector('[data-info=\"sec:solver\"]').click()")
            check('a section heading has one, and it leaves the section as it was', await page.ev(
                "!!document.getElementById('kvot-info-panel') && document.getElementById('sec-solver').open"), True)
            await page.ev("document.querySelector('[data-info=\"sec:solver\"]').click()")
            check('the same (i) closes it again', await page.ev("!document.getElementById('kvot-info-panel')"), True)
            # Escape from the panel, as a key press rather than a synthetic event.
            await page.ev("document.querySelector('[data-info=\"pane:time\"]').click()")
            for kind in ('rawKeyDown', 'keyUp'):
                await page.call('Input.dispatchKeyEvent', {'type': kind, 'key': 'Escape', 'code': 'Escape',
                                                           'windowsVirtualKeyCode': 27, 'nativeVirtualKeyCode': 27},
                                session=page.sid)
            await asyncio.sleep(0.3)
            check('Escape closes it and gives the focus back to its (i)', await page.ev(
                "!document.getElementById('kvot-info-panel') && document.activeElement.dataset.info"), 'pane:time')
            # A topic with choices marks the current one, and follows the
            # setting while it is open.
            await page.ev("document.querySelector('[data-info=\"set:method\"]').click()")
            check('a topic with choices marks the one chosen', await page.ev(
                "document.querySelector('#kvot-info-panel .info-choices dt.is-current').textContent"), 'NDF')
            await page.ev("""(() => { const m = document.getElementById('rtmMethod');
              m.value = 'julia_fbdf'; m.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            check('  and follows a change while it is open', await page.ev(
                "document.querySelector('#kvot-info-panel .info-choices dt.is-current').textContent"), 'FBDF')
            await page.ev("""(() => { const m = document.getElementById('rtmMethod');
              m.value = 'ndf'; m.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            # Its "Read more in Help" shows the Help, at the heading it names.
            await page.ev("document.querySelector('#kvot-info-panel .info-panel-more').click()")
            await asyncio.sleep(0.4)
            check('"Read more in Help" opens the Help at its heading', await page.ev(
                "(() => { const pane = document.querySelector('[data-pane=\"help\"]');"
                " const r = pane.getBoundingClientRect();"
                " const h = document.getElementById('help-solver').getBoundingClientRect();"
                " return !pane.hidden && !document.getElementById('kvot-info-panel')"
                " && h.top >= r.top - 1 && h.bottom <= r.bottom; })()"), True)
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            # The (i)s of the panel sit at the right-hand end of their lines,
            # the section headings' among them, so they line up.
            await page.ev("document.getElementById('rtmMore').click()")
            await asyncio.sleep(0.3)
            rights = await page.ev(
                "[...document.querySelectorAll('.rtm-side .info-btn')].filter((b) => b.offsetParent)"
                ".map((b) => Math.round(b.getBoundingClientRect().right))")
            check(f'the (i)s of the panel line up at its right ({sorted(set(rights)) if isinstance(rights, list) else rights})',
                  isinstance(rights, list) and len(rights) >= 15 and max(rights) - min(rights) <= 1, True)
            await page.ev("document.getElementById('rtmMore').click()")

            # --- a transport run reaches both charts -------------------------
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('a transport run finishes', isinstance(run, str) and run.startswith('Done'), True)
            check('and says what it cost', 'steps' in run and 'LU' in run, True)

            await page.ev("""(() => {
              const el = document.querySelector('#rtmSeries input[value="H2O2"]');
              el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await asyncio.sleep(1.5)
            check('ticking a species draws it against time', await page.ev(
                "(() => { const d = document.getElementById('rtmChartTime');"
                " return d.data ? d.data.map(t => t.name).join(',') : 'none'; })()"), 'H2O2')
            # The list item is the only place a pick is shown or taken back:
            # a separate row of chips used to sit above the list and appear and
            # disappear with the first and last pick, moving everything below it.
            check('and the list marks it as picked', await page.ev(
                "document.querySelectorAll('#rtmSeries .rtm-item.on').length"), 1)
            check('with no second place to show it', await page.ev(
                "document.querySelectorAll('.rtm-chip').length"), 0)
            top = await page.ev(
                "document.querySelector('#rtmSeries .rtm-item').getBoundingClientRect().top")
            await page.ev("""(() => {
              const el = document.querySelector('#rtmSeries input[value="H2O2"]');
              el.checked = false; el.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await asyncio.sleep(0.8)
            check('unticking removes it again', await page.ev(
                "document.querySelectorAll('#rtmSeries .rtm-item.on').length"), 0)
            check('and the list has not moved', await page.ev(
                "document.querySelector('#rtmSeries .rtm-item').getBoundingClientRect().top"), top)

            # The profile tab: one curve per stored time, one point per cell.
            await page.ev("document.querySelector('[data-tab=\"profile\"]').click()")
            await asyncio.sleep(1.5)
            check('the profile draws a curve per time over the cells', await page.ev(
                "(() => { const d = document.getElementById('rtmChartProfile');"
                " return d.data ? d.data.length + ':' + d.data[0].x.length : 'none'; })()"), '8:20')

            # --- choosing which times the profile draws ----------------------
            async def times(v):
                await page.ev("""(() => {
                  const el = document.getElementById('rtmProfileTimes');
                  el.value = %s;
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                })()""" % json.dumps(v))
                await asyncio.sleep(1.2)

            # TEND is 1E5 s, so all three are inside the run.
            await times('0, 1 h, 10 h')
            drawn = await page.ev(
                "(() => { const d = document.getElementById('rtmChartProfile');"
                " return d.data.map(t => t.name); })()")
            check(f'the profile draws only the times it is given ({drawn})',
                  isinstance(drawn, list) and len(drawn) == 3, True)
            # Each carries a unit, and the unit is chosen to read well: the
            # nearest stored point to 1 h is 3582 s, which is 59.7 min rather
            # than 0.995 h.
            check('and names them in a unit that reads well, not in raw seconds',
                  isinstance(drawn, list)
                  and all(any(d.endswith(u) for u in (' s', ' min', ' h', ' d', ' a')) for d in drawn)
                  and not drawn[1].endswith(' s') and not drawn[2].endswith(' s'), True)
            # The solver's own steps are thousands of seconds wide by then, so
            # the nearest computed profile to 10 h is not at 10 h. The chart
            # draws what was computed and the note says which times moved.
            note = await page.ev("document.getElementById('rtmProfileNote').textContent")
            check(f'and says when the nearest computed time was used ({note})',
                  isinstance(note, str) and 'nearest stored time used for' in note, True)
            await times('0 3600 36000')
            check('a bare list of seconds means the same thing', await page.ev(
                "(() => { const d = document.getElementById('rtmChartProfile');"
                " return d.data.map(t => t.name).join('|'); })()"),
                  '|'.join(drawn) if isinstance(drawn, list) else '?')

            await times('1 h, oops, 1000 y')
            note = await page.ev("document.getElementById('rtmProfileNote').textContent")
            check('an unreadable time is reported rather than ignored',
                  isinstance(note, str) and 'could not read oops' in note, True)
            check('and one past the end of the run says so',
                  isinstance(note, str) and 'past the end of the run' in note, True)
            check('leaving only the time that was in range', await page.ev(
                "document.getElementById('rtmChartProfile').data.length"), 1)

            await times('')
            check('and emptying the field goes back to a spread over the run', await page.ev(
                "document.getElementById('rtmChartProfile').data.length"), 8)

            # --- the third-type inlet, through the page ------------------------
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
            await set_text(page, (
                '<SETTINGS>\nMODE = transport\nCELLS = 30\nLENGTH = 1\n'
                'DIFFUSION = 1\nADVECTION = 1\nVELOCITY = 1E-6\n'
                'LEFT = cauchy\nRIGHT = outflow\nTEND = 2E6\n\n'
                '<SPECIES>\nX 0.0 D=2E-7 left=1.0\n\n<REACTIONS>\n'))
            await settle(page, "document.getElementById('rtmStatus')"
                               ".textContent.startsWith('Compiled: 1 species')", True, tries=40)
            check('the aliases reach the panel as the names they mean', await page.ev(
                "document.getElementById('rtmFacts').textContent.includes('robin | free')"), True)
            check('and no warning is raised when the flow suits the faces', await page.ev(
                "document.getElementById('rtmModelNote').hidden"), True)
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('a column with a third-type inlet runs',
                  isinstance(run, str) and run.startswith('Done'), True)
            # A robin inlet never brings the first cell up to the face value;
            # diffusion through a dirichlet face pulls it most of the way.
            await page.ev("document.querySelector('[data-tab=\"profile\"]').click()")
            await asyncio.sleep(1.2)
            first = await page.ev(
                "(() => { const d = document.getElementById('rtmChartProfile');"
                " return d.data[d.data.length - 1].y[0]; })()")
            check(f'and its first cell sits below the inlet concentration ({first})',
                  isinstance(first, (int, float)) and 0.5 < first < 1.0, True)

            # Asking for an inlet the flow cannot supply is said, not ignored.
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
            await set_text(page, (
                '<SETTINGS>\nMODE = transport\nCELLS = 30\nLENGTH = 1\n'
                'DIFFUSION = 1\nADVECTION = 0\n'
                'LEFT = robin\nRIGHT = free\nTEND = 2E6\n\n'
                '<SPECIES>\nX 0.0 D=2E-7 left=1.0\n\n<REACTIONS>\n'))
            await settle(page, "(() => { const n = document.getElementById('rtmModelNote');"
                               " return !n.hidden && n.textContent.includes('nothing flows in'); })()",
                         True, tries=40)
            check('a robin face with no flow into it is warned about', await page.ev(
                "document.getElementById('rtmModelNote').textContent.includes('nothing flows in')"), True)
            check('and so is a free face with nothing to carry anything out', await page.ev(
                "document.getElementById('rtmModelNote').textContent.includes('nothing to carry')"), True)

            # --- the example picker, and the time unit -------------------------
            check('the picker offers every example, in groups', await page.ev(
                "(() => { const s = document.getElementById('rtmExample');"
                " return s.querySelectorAll('option[value]:not([value=\"\"])').length"
                " + ':' + s.querySelectorAll('optgroup').length; })()"), '35:12')
            # Robertson: a batch model in seconds with a published answer.
            await page.ev("""(() => { const s = document.getElementById('rtmExample');
              s.value = 'robertson'; s.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            await settle(page, "document.getElementById('rtmStatus')"
                               ".textContent.startsWith('Compiled: 3 species')", True, tries=40)
            check('choosing one loads its text', await page.ev(
                "document.getElementById('rtmText').value.includes(\"Robertson's problem\")"), True)
            check('and says what it is, with where it comes from', await page.ev(
                "(() => { const a = document.getElementById('rtmExampleAbout');"
                " return (!a.hidden) && a.textContent.includes('Robertson') ? 'shown' : 'no'; })()"), 'shown')
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('an example runs', isinstance(run, str) and run.startswith('Done'), True)

            # The U-238 chain is in years: the axis, the panel and the boxes
            # must all say so rather than calling them seconds.
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
            await page.ev("""(() => { const s = document.getElementById('rtmExample');
              s.value = 'u238chain'; s.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            await settle(page, "document.getElementById('rtmStatus')"
                               ".textContent.startsWith('Compiled: 6 species')", True, tries=40)
            check('a model in years labels its own boxes in years', await page.ev(
                "document.getElementById('rtmTMinUnit').textContent"), 'a')
            check('and the panel says the simulated time is in years', await page.ev(
                "document.getElementById('rtmTendUnit').textContent.startsWith('years')"), True)
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('the U-238 chain runs', isinstance(run, str) and run.startswith('Done'), True)
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await page.ev("""(() => {
              const el = document.querySelector('#rtmSeries input[value="Ra226"]');
              el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await asyncio.sleep(1.2)
            check('and its time axis is in years, not seconds', await page.ev(
                "document.getElementById('rtmChartTime').layout.xaxis.title.text"), 'time (a)')

            # --- a rock matrix beside the fracture ------------------------------
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
            await set_text(page, (
                '<SETTINGS>\nMODE = transport\nCELLS = 5\nLENGTH = 20\n'
                'DIFFUSION = 1\nADVECTION = 1\nVELOCITY = 1\nLEFT = robin\nRIGHT = free\n'
                'PECLET = 8\nMATRIX_CELLS = 3\nMATRIX_DEPTH = 5\nMATRIX_FIRST = 0.001\n'
                'MATRIX_POROSITY = 0.0018\nWETTED_SURFACE = 500\nTEND = 200\n\n'
                '<SPECIES>\nX 0 D=0 left=1 Dm=0.001\n\n<REACTIONS>\n'))
            # Wait for THIS model: the U-238 chain before it is dual porosity too,
            # so the panel says "dual porosity" before the new text has compiled.
            await settle(page, "document.getElementById('rtmFacts').textContent"
                               ".includes('3 matrix layers to 5 m')", True, tries=40)
            check('a dual-porosity model compiles and the panel says so', await page.ev(
                "document.getElementById('rtmFacts').textContent.includes('3 matrix layers to 5 m')"), True)
            check('and says which species enter the rock', await page.ev(
                "document.getElementById('rtmFacts').textContent.includes('X enters the rock')"), True)
            check('the layer picker appears with the fracture and each layer', await page.ev(
                "(() => { const w = document.getElementById('rtmLayerWrap');"
                " return (!w.hidden) + ':' + document.getElementById('rtmLayer').options.length; })()"), 'true:4')
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('a dual-porosity run finishes', isinstance(run, str) and run.startswith('Done'), True)
            # The time chart at the fracture and at the first rock layer are
            # different series of the same species.
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await page.ev("""(() => {
              const el = document.querySelector('#rtmSeries input[value="X"]');
              el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await asyncio.sleep(1.0)
            frac = await page.ev("(() => { const y = document.getElementById('rtmChartTime').data[0].y; return y[y.length - 1]; })()")
            await page.ev("""(() => { const s = document.getElementById('rtmLayer');
              s.value = '1'; s.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            await asyncio.sleep(1.0)
            rock = await page.ev("(() => { const y = document.getElementById('rtmChartTime').data[0].y; return y[y.length - 1]; })()")
            check(f'the time chart follows the chosen layer (fracture {frac}, rock {rock})',
                  isinstance(frac, (int, float)) and isinstance(rock, (int, float)) and rock < frac, True)
            # Across the rock: the fracture at depth zero, then the three layers.
            await page.ev("document.querySelector('[data-tab=\"profile\"]').click()")
            await asyncio.sleep(0.8)
            await page.ev("""(() => { const s = document.getElementById('rtmProfileAxis');
              s.value = 'matrix'; s.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            await asyncio.sleep(1.2)
            check('the profile across the rock has the fracture and every layer', await page.ev(
                "(() => { const d = document.getElementById('rtmChartProfile').data;"
                " return d[d.length - 1].x.length + ':' + d[d.length - 1].x[0]; })()"), '4:0')
            check('and the picker now chooses the cell', await page.ev(
                "document.getElementById('rtmProfileLayerLabel').textContent"), 'At cell')
            check('and the concentration falls into the rock', await page.ev(
                "(() => { const y = document.getElementById('rtmChartProfile').data.at(-1).y; return y[0] > y[3]; })()"), True)
            # The gradient at a rock layer draws too.
            await page.ev("document.querySelector('[data-tab=\"gradient\"]').click()")
            await asyncio.sleep(0.8)
            await page.ev("""(() => { const s = document.getElementById('rtmGradLayer');
              s.value = '2'; s.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            await asyncio.sleep(1.2)
            check('the gradient draws a rock layer along the fracture', await page.ev(
                "(() => { const d = document.getElementById('rtmChartGradient').data[0];"
                " return d.z.length + ':' + document.getElementById('rtmGradNote').textContent.includes('rock layer 2'); })()"), '5:true')
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")

            # --- a far-field path as Kompartment starts one ------------------
            # Its layers worked out, the rock going on past the release point,
            # and the release read through the right-hand end.
            await page.ev("""(() => { const s = document.getElementById('rtmExample');
              s.value = 'farfield'; s.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            await settle(page, "document.getElementById('rtmFacts').textContent"
                               ".includes('12 matrix layers to 12.5 m')", True, tries=40)
            facts = await page.ev("document.getElementById('rtmFacts').textContent")
            check('a far-field path has twelve matched layers, the first worked out from the path',
                  isinstance(facts, str) and 'matched: the first 11.5 mm (worked out from the path)' in facts, True)
            check('  and the panel says how many cells stand past the right-hand end',
                  isinstance(facts, str) and 'robin | semi-infinite boundaries, 5 cells past the right-hand end' in facts, True)
            check('  and the travel time the flow makes',
                  isinstance(facts, str) and 'a travel time of 100 a' in facts, True)
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('the far-field path runs', isinstance(run, str) and run.startswith('Done'), True)
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await page.ev("""(() => {
              const el = document.querySelector('#rtmSeries input[value="Tracer"]');
              el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true }));
              const s = document.getElementById('rtmCell');
              s.value = 'right'; s.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await asyncio.sleep(1.2)
            check('choosing the right-hand end draws what crosses it', await page.ev(
                "document.getElementById('rtmChartTime').layout.yaxis.title.text.startsWith('flux through the right end')"), True)
            out = await page.ev("(() => { const t = document.getElementById('rtmChartTime').data.find((d) => d.name === 'Tracer');"
                                " return t ? t.y[t.y.length - 1] : null; })()")
            check(f'  and the tracer released at one a year all comes out in the end ({out})',
                  isinstance(out, (int, float)) and abs(out - 1) < 1e-3, True)
            check('  with no layer to pick at an end', await page.ev(
                "document.getElementById('rtmLayerWrap').hidden"), True)
            await page.ev("""(() => { const s = document.getElementById('rtmCell');
              s.value = '19'; s.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            await asyncio.sleep(1.0)
            check('back at a cell, the layers come back', await page.ev(
                "!document.getElementById('rtmLayerWrap').hidden && document.getElementById('rtmChartTime')"
                ".layout.yaxis.title.text === 'concentration'"), True)
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")

            # --- a release history, read at the clock -------------------------
            await page.ev("""(() => { const s = document.getElementById('rtmExample');
              s.value = 'releasehistory'; s.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            await settle(page, "document.getElementById('rtmFacts').textContent.includes('read at the clock')", True, tries=40)
            check('a release history: the panel says what is read at the clock and how many corners it has', await page.ev(
                "document.getElementById('rtmFacts').textContent.includes("
                "'read at the clock: release, the run started again at 5 corners up to TEND')"), True)
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('  it runs, and the status line says it was started again at them',
                  isinstance(run, str) and run.startswith('Done') and 'started again at 5 table corners' in run, True)
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await page.ev("""(() => {
              for (const el of document.querySelectorAll('#rtmSeries input')) {
                const want = el.value === 'I129';
                if (el.checked !== want) { el.checked = want; el.dispatchEvent(new Event('change', { bubbles: true })); }
              }
              const s = document.getElementById('rtmCell');
              s.value = 'right'; s.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await asyncio.sleep(1.2)
            top = await page.ev("(() => { const t = document.getElementById('rtmChartTime').data.find((d) => d.name === 'I129');"
                                " return t ? Math.max(...t.y) : null; })()")
            check(f'  and I-129 comes out through the right end at half the release at most ({top})',
                  isinstance(top, (int, float)) and 0.4 < top < 0.6, True)
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")

            # Back to the built-in model, which the checks below are about.
            await page.ev("(() => { const t = document.getElementById('rtmText');"
                          " t.value = RTM_DEFAULT_MODEL;"
                          " t.dispatchEvent(new Event('input', { bubbles: true })); })()")
            await settle(page, "document.getElementById('rtmStatus')"
                               ".textContent.startsWith('Compiled: 36 species')", True, tries=40)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)

            # --- the whole run as one picture --------------------------------
            await page.ev("document.querySelector('[data-tab=\"gradient\"]').click()")
            await asyncio.sleep(1.5)

            async def grad(js):
                await page.ev("(() => { %s })()" % js)
                await asyncio.sleep(1.3)

            await grad("""const s = document.getElementById('rtmGradSpecies');
              s.value = 'H2O2'; s.dispatchEvent(new Event('change', { bubbles: true }));""")
            shape = await page.ev(
                "(() => { const d = document.getElementById('rtmChartGradient');"
                " return d.data ? d.data[0].type + ' ' + d.data[0].z.length"
                " + 'x' + (d.data[0].z[0].length > 100) : 'none'; })()")
            check('the gradient is a heatmap with a row per cell', shape, 'heatmap 20xtrue')
            check('and time runs along x, distance up y from zero', await page.ev(
                "(() => { const l = document.getElementById('rtmChartGradient').layout;"
                " return l.xaxis.title.text.slice(0, 4)"
                " + '|' + (l.yaxis.range[0] < l.yaxis.range[1]); })()"), 'time|true')
            # The axis starts at "from", not at the solver's first femtosecond.
            first = await page.ev("document.getElementById('rtmChartGradient').data[0].x[0]")
            check(f'and it starts at the "from" time, not the first stored step ({first})',
                  isinstance(first, (int, float)) and first >= 1e-6, True)
            check('the note says how many points that left off', await page.ev(
                "document.getElementById('rtmGradNote').textContent"
                ".includes('earlier points left off')"), True)

            await grad("""for (const id of ['rtmGradLogC', 'rtmGradSmooth']) {
              const el = document.getElementById(id); el.checked = true;
              el.dispatchEvent(new Event('change', { bubbles: true })); }""")
            # log concentration puts log10 into z, which for this species is
            # a number around -6, not the 1e-6 itself.
            zz = await page.ev("document.getElementById('rtmChartGradient').data[0].z[10][500]")
            check(f'log concentration plots the logarithm ({zz})',
                  isinstance(zz, (int, float)) and -20 < zz < 0, True)
            check('and says so on the colour bar', await page.ev(
                "document.getElementById('rtmChartGradient')"
                ".data[0].colorbar.title.text.startsWith('log')"), True)
            check('and the range is given as powers', await page.ev(
                "document.getElementById('rtmGradNote').textContent.includes('10^-')"), True)
            check('smoothing is a choice, not the default', await page.ev(
                "document.getElementById('rtmChartGradient').data[0].zsmooth"), 'best')
            await grad("""for (const id of ['rtmGradLogC', 'rtmGradSmooth']) {
              const el = document.getElementById(id); el.checked = false;
              el.dispatchEvent(new Event('change', { bubbles: true })); }""")
            # As contours, with their values on them, and as a surface in three dimensions.
            await grad("""const v = document.getElementById('rtmGradView');
              v.value = 'contour'; v.dispatchEvent(new Event('change', { bubbles: true }));""")
            check('the gradient as contours, their values written on them', await page.ev(
                "(() => { const d = document.getElementById('rtmChartGradient').data[0];"
                " return d.type + '|' + d.contours.showlabels; })()"), 'contour|true')
            await grad("""const v = document.getElementById('rtmGradView');
              v.value = 'surface'; v.dispatchEvent(new Event('change', { bubbles: true }));""")
            check('and as a surface, the value up', await page.ev(
                "(() => { const p = document.getElementById('rtmChartGradient');"
                " return p.data[0].type + '|' + !!p.layout.scene; })()"), 'surface|true')
            # A quantity of the water: the pH the radiolysis leaves, cell by cell, worked out in the worker.
            await grad("""const v = document.getElementById('rtmGradView'); v.value = 'map';
              const s = document.getElementById('rtmGradSpecies');
              s.value = 'pH'; s.dispatchEvent(new Event('change', { bubbles: true }));""")
            ph = await settle(page, "(() => { const p = document.getElementById('rtmChartGradient');"
                                    " if (p.hidden || !p.data || p.data[0].colorbar.title.text !== 'pH') return null;"
                                    " const z = p.data[0].z.flat().filter((v) => v !== null);"
                                    " return [Math.min(...z) > 2, Math.max(...z) < 12]; })()", [True, True], tries=40)
            check('a quantity on the gradient: the pH in every cell, from the run\'s concentrations', ph, [True, True])
            check('the picker offers the species and then the quantities, grouped', await page.ev(
                "[...document.querySelectorAll('#rtmGradSpecies optgroup')].map((g) => g.label).join('|')"),
                'Species|The water|Totals in the water|What each reaction does')
            await grad("""const s = document.getElementById('rtmGradSpecies');
              s.value = 'H2O2'; s.dispatchEvent(new Event('change', { bubbles: true }));""")

            # --- the budget by each reaction, on the built-in model's hydrogen peroxide ---
            # Over the whole column, what each reaction made and took of H2O2. The radiolysis that makes it comes first,
            # nine tenths of what is made. Each equilibrium written as two lines is one reaction, both lines given. The
            # eight that move most are named and the rest together, made above nought and taken below. Every reaction's
            # net and what no line accounts for are together what the budget counts the reactions as having made, the
            # leftover the summing's, the model having no relations. At the fuel surface, cell 0, the radiolysis makes
            # nearly all of it, and the CSV has each reaction's rates and sum at every stored point.
            async def pick(id_, value):
                await page.ev("(() => { const s = document.getElementById(%s); s.value = %s;"
                              " s.dispatchEvent(new Event('change', { bubbles: true })); })()" % (json.dumps(id_), json.dumps(value)))

            comp_before = await page.ev("[document.getElementById('rtmCompView').value, document.getElementById('rtmCompBudgetOf').value]")
            await page.ev("document.querySelector('[data-tab=\"composition\"]').click()")
            await pick('rtmCompView', 'budget')
            await pick('rtmCompBudgetOf', 'species:H2O2')
            await pick('rtmCompBudgetBy', 'lines')
            await settle(page, "!document.getElementById('rtmCompLines').hidden", True, tries=80, pause=0.25)
            by_rx = await page.ev("""(() => {
              const rows = [...document.querySelectorAll('#rtmCompLines tbody tr')].map((tr) => [...tr.children]);
              const v = (td) => (td.dataset.v === undefined ? null : Number(td.dataset.v));
              const by = (name) => rows.find((r) => r[0].textContent === name);
              const d = document.getElementById('rtmChartComp').data;
              const all = by('every reaction');
              const gross = v(all[2]) - v(all[3]);
              const rest = v(by("the summing's error")[4]);
              const made = v(by('made by reactions, net, as the budget has it')[4]);
              return [rows[0][0].textContent + ' [' + rows[0][1].textContent + ']', v(rows[0][5]) > 0.85,
                rows.filter((r) => r[1].textContent.includes(',')).map((r) => r[0].textContent + ' [' + r[1].textContent + ']').join(' | '),
                d.filter((t) => t.stackgroup && t.showlegend !== false).length, d.some((t) => /^the other \\d+ reactions$/.test(t.name)),
                d[d.length - 1].name, d.every((t) => !t.stackgroup || t.y.every((y) => (t.stackgroup === 'made' ? y >= 0 : y <= 0))),
                Math.abs(v(all[4]) + rest - made) <= 1e-12 * gross, Math.abs(rest) / gross < 1e-6,
                /; the summing's error [-0-9.e+]+, [0-9.e+-]+ of what was made and taken$/.test(document.getElementById('rtmCompNote').textContent),
                document.getElementById('rtmChartComp').layout.yaxis.title.text]; })()""")
            check('the budget by each reaction, of the built-in model\'s H2O2 over the whole column: the radiolysis first, nine '
                  'tenths of what is made; each equilibrium written as two lines one reaction; the eight that move most named and '
                  'the rest together, made above nought and taken below; every reaction\'s net and the summing\'s error '
                  'together what the reactions made, the model having no relations', by_rx,
                  ['=> H2O2 [73]', True, 'H+ + HO2- <=> H2O2 [135, 149] | HO2- + H2O <=> OH- + H2O2 [138, 150]', 9, True,
                   'made less taken, every reaction', True, True, True, True,
                   "made (+) and taken (−) per s<br>concentration × m per m² of the water's cross-section"])
            await pick('rtmCompBudgetAt', '0')
            await settle(page, "/^H2O2 at cell 0:/.test(document.getElementById('rtmCompNote').textContent)", True, tries=80, pause=0.25)
            at0 = await page.ev("document.getElementById('rtmCompNote').textContent")
            surface = re.search(r'made by \d+ reactions, [0-9.e+-]+, the most by => H2O2 \(([0-9.]+) %\)', at0 or '')
            await page.ev("(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;"
                          " HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };"
                          " if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()")
            await page.ev("document.querySelector('[data-pane=\"composition\"][data-as=\"csv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            rcsv = await page.ev("(async () => { const r = window.__saved[0]; return r ? [r.name, (await r.body).trim().split('\\n')] : null; })()")
            check('  at the fuel surface, cell 0, the radiolysis nearly all that makes it, and no leftover where the water carries it '
                  'in and out besides; the CSV each reaction\'s rates and sum at every stored point',
                  [surface is not None and float(surface.group(1)) > 95,
                   await page.ev("[...document.querySelectorAll('#rtmCompLines tbody tr')].some((tr) => tr.children[0].textContent"
                                 " === \"the summing's error\")"),
                   # The name after the Example picker, which still shows the example before the built-in model was put back.
                   [rcsv[0].split('_', 2)[-1], rcsv[1][0][:111], len(rcsv[1]) > 500] if isinstance(rcsv, list) else rcsv],
                  [True, False, ['budget_H2O2_by_reaction_cell0.csv',
                                 't (s),"=> H2O2 (line 73), made per s","=> H2O2 (line 73), taken per s","=> H2O2 (line 73), net since the start"',
                                 True]])
            await pick('rtmCompBudgetAt', 'column')
            await pick('rtmCompBudgetBy', 'where')
            await pick('rtmCompBudgetOf', comp_before[1])
            await pick('rtmCompView', comp_before[0])
            await asyncio.sleep(0.3)

            # --- what a run can be read as: quantities, <OUTPUT>, <DATA>, saving ---
            # The model and the picks of the checks before are put back after it: the ones after read them.
            before = await page.ev("[document.getElementById('rtmText').value, "
                                   "[...document.querySelectorAll('#rtmSeries input:checked')].map((i) => i.value)]")
            await page.ev("document.querySelector('[data-on-click=\"rtm:clearSeries\"]').click()")
            await set_text(page, QUANTITY_MODEL)
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 4 species')", True, tries=40)
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check(f'a water with an activity model, a phase and <OUTPUT> runs ({str(run)[:40]})',
                  isinstance(run, str) and run.startswith('Done'), True)
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            check('the list groups the species and what the run comes to besides them, the log activities shut', await page.ev(
                "[...document.querySelectorAll('#rtmSeries .rtm-series-head')]"
                ".map((b) => b.dataset.group + ':' + b.getAttribute('aria-expanded')).join(' ')"),
                'species:true water:true saturation:true outputs:true reactions:true activities:false')
            check('  a shut group\'s entries are hidden until it is opened', await page.ev(
                "[...document.querySelectorAll('#rtmSeries .rtm-item[data-group=\"activities\"]')].every((e) => e.hidden)"), True)
            await page.ev("document.querySelector('#rtmSeries .rtm-series-head[data-group=\"activities\"]').click()")
            await asyncio.sleep(0.4)
            check('  and shown when it is', await page.ev(
                "[...document.querySelectorAll('#rtmSeries .rtm-item[data-group=\"activities\"]')].every((e) => !e.hidden)"), True)
            for key in ['pH', 'SI(Halite)', 'acid']:
                await page.ev("(() => { const el = [...document.querySelectorAll('#rtmSeries input')]"
                              ".find((i) => i.value === %s); el.click(); })()" % json.dumps(key))
            traces = await settle(page, "document.getElementById('rtmChartTime').data.map((t) => t.name + '|' + (t.yaxis || 'y')"
                                        " + '|' + t.mode).join(' / ')",
                                  'pH|y2|lines / pH, measured|y2|markers / SI(Halite)|y2|lines / acid (mol/kgw)|y|lines', tries=40)
            check('pH and SI(Halite) on the right-hand axis, the <OUTPUT> in mol/kgw on the left, the pH <DATA> measured as '
                  'points in the colour of its line', traces,
                  'pH|y2|lines / pH, measured|y2|markers / SI(Halite)|y2|lines / acid (mol/kgw)|y|lines')
            at500 = await page.ev("(() => { const t = document.getElementById('rtmChartTime').data[0]; let k = 0;"
                                  " t.x.forEach((x, i) => { if (Math.abs(x - 500) < Math.abs(t.x[k] - 500)) k = i; });"
                                  " return [t.x[k], t.y[k], document.getElementById('rtmChartTime').data[1].marker.color"
                                  " === t.line.color]; })()")
            check(f'  the pH at 500 s is -log a(H+) of the acid the reaction has added ({at500})',
                  isinstance(at500, list) and abs(at500[0] - 500) < 30 and abs(at500[1] - 3.32) < 0.02 and at500[2], True)
            # Saving: CSV and Excel of the series, the figure as SVG and PNG -- each caught as the page hands it over.
            await page.ev("""(() => {
              window.__saved = [];
              window.__click = HTMLAnchorElement.prototype.click;
              HTMLAnchorElement.prototype.click = function () {
                const rec = { name: this.download, href: this.href.slice(0, 40) };
                if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.arrayBuffer())
                  .then((b) => Array.from(new Uint8Array(b.slice(0, 300))));
                window.__saved.push(rec);
              };
            })()""")
            for sel in ['[data-on-click="rtm:downloadCsv"]', '[data-pane="time"][data-as="xlsx"]', '[data-pane="time"][data-as="svg"]',
                        '[data-pane="time"][data-as="png"]']:
                await page.ev("document.querySelector(%s).click()" % json.dumps(sel))
                await asyncio.sleep(1.2)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            saved = await page.ev("""(async () => Promise.all(window.__saved.map(async (r) => {
              const b = r.body ? await r.body : null;
              return [r.name, b ? (r.name.endsWith('.csv') ? String.fromCharCode(...b).split('\\n')[0] : String.fromCharCode(...b.slice(0, 2)))
                : r.href.slice(0, 18)];
            })))()""")
            want_csv = 't (s),pH @ cell 0,SI(Halite) @ cell 0,acid (mol/kgw) @ cell 0'
            shapes = [[r[0].split('_')[-1], r[1]] for r in saved] if isinstance(saved, list) else saved
            check('saved as CSV, with the quantities ticked, as an Excel workbook, and the chart as SVG and PNG', shapes,
                  [['cell0.csv', want_csv], ['cell0.xlsx', 'PK'], ['time.svg', '<s'], ['time.png', '\x89P']])
            await page.ev("document.querySelector('[data-on-click=\"rtm:clearSeries\"]').click()")
            await set_text(page, before[0])
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            for key in before[1]:
                await page.ev("(() => { const el = [...document.querySelectorAll('#rtmSeries input')]"
                              ".find((i) => i.value === %s); if (el && !el.checked) el.click(); })()" % json.dumps(key))

            # --- what the water is made of: the Composition tab ---
            before = await page.ev("document.getElementById('rtmText').value")
            await set_text(page, COMP_MODEL)
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 10 species')", True, tries=40)
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check(f'a water of known major ions runs ({str(run)[:40]})', isinstance(run, str) and run.startswith('Done'), True)
            await page.ev("document.querySelector('[data-tab=\"composition\"]').click()")
            await asyncio.sleep(0.6)

            async def comp(view, **extra):
                sets = ''.join("document.getElementById('%s').value = %s;" % (k, json.dumps(v)) for k, v in extra.items())
                await page.ev("(() => { document.getElementById('rtmCompView').value = %s; %s"
                              " document.getElementById('rtmCompView').dispatchEvent(new Event('change', { bubbles: true })); })()"
                              % (json.dumps(view), sets))
                await asyncio.sleep(0.6)

            await comp('where', rtmCompIn='all', rtmCompElement='Ca')
            where = await page.ev("""(() => { const d = document.getElementById('rtmChartComp').data;
              const sums = d[0].y.map((_, j) => d.reduce((s, t) => s + (t.y[j] || 0), 0));
              return [d.map((t) => t.name).join(' / '), sums.every((v) => Math.abs(v - 100) < 1e-9), d[0].stackgroup]; })()""")
            check('where calcium is, in the whole cell: the calcite (made of what its reaction says), Ca+2 and CaSO4 as shares '
                  'stacked to 100 % at every point', where, ['Calcite, mineral / Ca+2 / CaSO4', True, 'one'])
            await comp('where', rtmCompIn='water')
            check('  in the water alone, the mineral left out', await page.ev(
                "document.getElementById('rtmChartComp').data.map((t) => t.name).join(' / ')"), 'Ca+2 / CaSO4')
            await comp('piper')
            piper = await page.ev("""(() => { const d = document.getElementById('rtmChartComp').data.filter((t) => t.name === 'the model');
              return d.map((t) => [t.x[0], t.y[0]]); })()""")
            # By hand: the cations 2.2, 1, 2.1 of 5.3 and the anions 2, 1, 3 of 6, on triangles of side 1 with 0.2 between.
            h = math.sqrt(3) / 2
            ca, mg, nak, cl, so4 = 2.2 / 5.3, 1 / 5.3, 2.1 / 5.3, 2 / 6, 1 / 6
            want = [[nak + 0.5 * mg, h * mg], [1.2 + cl + 0.5 * so4, h * so4],
                    [1.1 - 0.5 * (ca + mg) + 0.5 * (cl + so4), 0.2 * h + h * (ca + mg + cl + so4)]]
            check('a Piper diagram: the water in the cations\' triangle, the anions\' and the diamond where the shares of its '
                  'major ions put it, CaSO4 and CO3-2 counted', isinstance(piper, list) and len(piper) == 3 and all(
                      abs(a - b) < 1e-9 for pt, wpt in zip(piper, want) for a, b in zip(pt, wpt)), True)
            check('  the measured water beside it, in each of the three', await page.ev(
                "document.getElementById('rtmChartComp').data.filter((t) => t.name === 'measured').length"), 3)
            check('  and its type in the note', await page.ev(
                "document.getElementById('rtmCompNote').textContent.includes('Ca–Na–HCO₃')"), True)
            # A Durov diagram: the cations' triangle on the square's left, the anions' on its top, the water in the square at
            # HCO3 + SO4/2 across and Ca + Mg/2 up; its total dissolved solids, every species dissolved by its formula and
            # IUPAC's weights, 405.00 mg/kgw by hand -- and no pH, the model having no H+.
            await comp('durov')
            durov = await page.ev("""(() => { const d = document.getElementById('rtmChartComp').data.filter((t) => t.name === 'the model');
              return d.map((t) => [t.x[0], t.y[0], t.text[0]]); })()""")
            hco3 = 3 / 6
            across, up = hco3 + so4 / 2, ca + mg / 2
            w = {'H': 1.008, 'C': 12.011, 'O': 15.999, 'Na': 22.990, 'Mg': 24.305, 'S': 32.06, 'Cl': 35.45, 'K': 39.098, 'Ca': 40.078}
            tds = 1000 * (1e-3 * w['Ca'] + 5e-4 * w['Mg'] + 2e-3 * w['Na'] + 1e-4 * w['K'] + 2e-3 * w['Cl']
                          + 4e-4 * (w['S'] + 4 * w['O']) + 1e-4 * (w['Ca'] + w['S'] + 4 * w['O'])
                          + 2.9e-3 * (w['H'] + w['C'] + 3 * w['O']) + 5e-5 * (w['C'] + 3 * w['O']))
            want = [[-h * mg, up], [across, 1 + h * so4], [across, up], [1 + 0.62 * tds / 500, up]]
            check('a Durov diagram: the water in the cations\' triangle, the anions\' and the square where the two meet, HCO3 + SO4/2 '
                  'across and Ca + Mg/2 up, to 1e-9; its total dissolved solids, %.2f mg/kgw by hand, on the panel at the right; no '
                  'pH panel, the model having no H+, and the note saying so' % tds,
                  [isinstance(durov, list) and len(durov) == 4 and all(abs(a - b) < 1e-9 for pt, wpt in zip(durov, want)
                                                                        for a, b in zip(pt[:2], wpt)),
                   isinstance(durov, list) and len(durov) == 4 and 'TDS %s mg/kgw' % ('%.4g' % tds) in durov[0][2],
                   await page.ev("document.getElementById('rtmCompNote').textContent.includes('no pH: the model has no H+')"),
                   await page.ev("document.getElementById('rtmChartComp').data.filter((t) => t.name === 'measured').length")],
                  [True, True, True, 3])
            await comp('schoeller', rtmCompTimes='0, 100')
            sch = await page.ev("""(() => { const d = document.getElementById('rtmChartComp');
              return [d.data.length, d.data[0].y, d.data[2].line.dash, d.layout.yaxis.type, d.layout.yaxis.title.text]; })()""")
            check('a Schoeller diagram: a line per water asked for, in meq/kgw on a log axis, the measured one dotted',
                  isinstance(sch, list) and sch[0] == 3 and all(abs(a - b) < 1e-9 for a, b in zip(sch[1], [2.2, 1, 2.1, 2, 1, 3]))
                  and sch[2:] == ['dot', 'log', 'meq/kgw'], True)
            await comp('stiff')
            check('Stiff diagrams: one per water, the measured one too', await page.ev(
                "document.getElementById('rtmChartComp').data.filter((t) => t.fill === 'toself').length"), 3)
            await page.ev("""(() => {
              window.__saved = [];
              window.__click = HTMLAnchorElement.prototype.click;
              HTMLAnchorElement.prototype.click = function () {
                const rec = { name: this.download };
                if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text());
                window.__saved.push(rec);
              };
            })()""")
            await page.ev("document.querySelector('[data-pane=\"composition\"][data-as=\"csv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            csv = await page.ev("(async () => { const r = window.__saved[0]; return r ? [r.name, (await r.body).split('\\n')] : null; })()")
            check('saved as CSV: each water\'s ions in meq/kgw, their shares and its type',
                  [csv[1][0][:42], csv[1][1][:10], csv[1][1][-10:], len(csv[1])] if isinstance(csv, list) else csv,
                  ['water,t (s),cell,distance (m),Ca (meq/kgw)', '"model, 0.', 'Ca–Na–HCO₃', 4])
            # A USSL diagram: none without the conductance; with <CONDUCTANCE>, the water's SC and its SAR by hand,
            # 1000 Na/sqrt(1000 (Ca + Mg)) of the dissolved totals, and the measured water's from its Na, Ca and Mg.
            await comp('ussl')
            check('a USSL diagram needs the conductance, and says where it comes from', await page.ev(
                "document.getElementById('rtmCompEmpty').textContent.includes('<CONDUCTANCE>')"), True)
            await set_text(page, COMP_MODEL.replace('cell = 0\n50    1e-3     5e-4  3e-3  1e-4  3e-3  5e-4    2.5e-3',
                                                    'SC  cell = 0\n50    1e-3     5e-4  3e-3  1e-4  3e-3  5e-4    2.5e-3  450')
                           + '\n<CONDUCTANCE>\nCa+2   gfw 40.08  dw 0.79e-9\nMg+2   gfw 24.31  dw 0.71e-9\nNa+    gfw 22.99  dw 1.33e-9\n'
                           'K+     gfw 39.10  dw 1.96e-9\nCl-    gfw 35.45  dw 2.03e-9\nSO4-2  gfw 96.06  dw 1.07e-9\n'
                           'CaSO4  gfw 136.14\nHCO3-  gfw 61.02  dw 1.18e-9\nCO3-2  gfw 60.01  dw 0.96e-9\n')
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 10 species')", True, tries=40)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await page.ev("document.querySelector('[data-tab=\"composition\"]').click()")
            await comp('ussl')
            await settle(page, "(() => { const d = document.getElementById('rtmChartComp').data;"
                         " return !!(d && d.some((t) => t.name === 'the model')); })()", True, tries=60, pause=0.25)
            ussl = await page.ev("""(() => { const p = document.getElementById('rtmChartComp');
              const m = p.data.find((t) => t.name === 'the model'); const d = p.data.find((t) => t.name === 'measured');
              return [m.x[0], m.y[0], d ? [d.x[0], d.y[0]] : null, p.layout.xaxis.type, p.layout.shapes.map((s) => s.x0),
                document.getElementById('rtmCompNote').textContent]; })()""")
            ok = isinstance(ussl, list) and 250 < ussl[0] < 750 and abs(ussl[1] - 2 / math.sqrt(1.6)) < 1e-9 \
                and ussl[2] is not None and abs(ussl[2][0] - 450) < 1e-9 and abs(ussl[2][1] - 3 / math.sqrt(1.5)) < 1e-9 \
                and ussl[3] == 'log' and ussl[4] == [250, 750, 2250] and 'C2-S1 at the start' in ussl[5] and '1 measured' in ussl[5]
            check('  with <CONDUCTANCE>: the water\'s SC and its SAR by hand, the measured water\'s from Na, Ca and Mg, the '
                  f'classes split at 250, 750 and 2,250 uS/cm on a log axis, C2-S1 in the note ({str(ussl)[:150]})', ok, True)
            # Wilcox's diagram: the cations in meq/kgw across -- Ca 1.1 mmol with its CaSO4, Mg 0.5, Na 2, K 0.1 is 2.2 + 1 + 2 +
            # 0.1 = 5.3 -- and Na over them up, 2/5.3; the measured water 2 + 1 + 3 + 0.1 = 6.1 and 3/6.1.
            await comp('wilcox')
            wil = await page.ev("""(() => { const p = document.getElementById('rtmChartComp');
              const m = p.data.find((t) => t.name === 'the model'); const d = p.data.find((t) => t.name === 'measured');
              return [m.x[0], m.y[0], d ? [d.x[0], d.y[0]] : null, p.layout.xaxis2.range[1] / p.layout.xaxis.range[1],
                document.getElementById('rtmCompNote').textContent]; })()""")
            ok = isinstance(wil, list) and abs(wil[0] - 5.3) < 1e-9 and abs(wil[1] - 200 / 5.3) < 1e-9 and wil[2] is not None \
                and abs(wil[2][0] - 6.1) < 1e-9 and abs(wil[2][1] - 300 / 6.1) < 1e-9 and abs(wil[3] - 100) < 1e-9 \
                and wil[4].startswith('cell 0: excellent to good at the start') and wil[4].endswith('; 1 measured')
            check('a Wilcox diagram: the cations\' total and the percent sodium by hand, the model\'s and the measured water\'s, '
                  f'the conductance along the top a hundred times the e.p.m., excellent to good in the note ({str(wil)[:160]})', ok, True)
            # Measured waters across every class: Wilcox's own example, the Colorado at Yuma (12.06 e.p.m., 39 %), and one either
            # side of each curve, the traced curves 56.25 % at 12.06, 85.73 % at 10, 93.63 % at 25 and 71.05 % at 5.
            wil_data = '\n<DATA>\ntime  tot(Ca)  Na+  cell = 0\n' + '\n'.join(
                f'{i + 1}  {(e - e * p / 100) / 2000:.8g}  {e * p / 100000:.8g}' for i, (e, p) in enumerate([
                    (12.06, 39), (3, 30), (10, 70), (10, 90), (25, 50), (32, 20), (5, 99.5), (12.06, 56), (12.06, 56.5),
                    (10, 85.5), (10, 86), (25, 93.4), (25, 93.9), (5, 70.8), (5, 71.3)])) + '\n'
            await set_text(page, COMP_MODEL[:COMP_MODEL.index('<DATA>')] + wil_data)
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 10 species')", True, tries=40)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await page.ev("document.querySelector('[data-tab=\"composition\"]').click()")
            await comp('wilcox')
            classes = await page.ev("(() => { const d = document.getElementById('rtmChartComp').data.find((t) => t.name === 'measured');"
                                    " return d ? d.text.map((t) => t.split('<br>')[1].split(':')[0]) : null; })()")
            check('  the classes: Wilcox\'s Yuma water good to permissible, as he has it, and a water either side of each traced curve',
                  classes, ['good to permissible', 'excellent to good', 'permissible to doubtful', 'doubtful to unsuitable',
                            'doubtful to unsuitable', 'unsuitable', 'unsuitable', 'good to permissible', 'permissible to doubtful',
                            'permissible to doubtful', 'doubtful to unsuitable', 'doubtful to unsuitable', 'unsuitable',
                            'excellent to good', 'permissible to doubtful'])
            # Along a column: the same water in three cells, each a point of the Piper and a Stiff diagram.
            await set_text(page, COMP_MODEL.replace('MODE = batch', 'MODE = transport\nCELLS = 3'))
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 10 species')", True, tries=40)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await page.ev("document.querySelector('[data-tab=\"composition\"]').click()")
            await comp('piper', rtmCompAlong='distance', rtmCompTimes='')
            check('along the column: a point per cell, coloured by distance', await page.ev(
                "(() => { const d = document.getElementById('rtmChartComp').data.find((t) => t.name === 'the model');"
                " return [d.x.length, d.marker.colorbar.title.text]; })()"), [3, 'distance (m)'])

            # Principal components, of a column whose four ions only mix.
            await set_text(page, MIX_MODEL)
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 4 species')", True, tries=40)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await page.ev("document.querySelector('[data-tab=\"composition\"]').click()")

            async def pca(**opts):
                sets = ''.join(("document.getElementById('%s').checked = %s;" % (k, 'true' if v else 'false')) if isinstance(v, bool)
                               else ("document.getElementById('%s').value = %s;" % (k, json.dumps(v))) for k, v in opts.items())
                await page.ev("(() => { document.getElementById('rtmCompView').value = 'pca'; %s"
                              " document.getElementById('rtmCompView').dispatchEvent(new Event('change', { bubbles: true })); })()" % sets)
                await asyncio.sleep(0.6)
                return await page.ev("(() => { const e = document.getElementById('rtmCompEmpty');"
                                     " return e.hidden ? document.getElementById('rtmCompNote').textContent : 'EMPTY ' + e.textContent; })()")

            flat = await pca(rtmCompAlong='time', rtmCompCell='4', rtmCompPcaVars='', rtmCompPcaLog=False, rtmCompLogT=True)
            lie = await page.ev("""(() => { const d = document.getElementById('rtmChartComp').data;
              const m = d.find((t) => t.name === 'the model'), me = d.find((t) => t.name === 'measured');
              const reach = Math.max(...m.x.map(Math.abs));
              return [Math.max(...m.y.map(Math.abs)) < 1e-9 * reach, me ? me.x.length : 0, me ? Math.abs(me.y[0]) < 1e-9 * reach : false,
                (document.getElementById('rtmChartComp').layout.annotations || []).filter((a) => a.text).map((a) => a.text).join(' ')]; })()""")
            check('principal components of a column whose four ions only mix, taken as they are, at its last cell: each element '
                  f'dissolved by default, all of the variance on the first component ({flat})',
                  isinstance(flat, str) and re.match(r'cell 4: \d+ waters, 4 variables; PC1 100\.0 % of the variance, PC2 0\.0 %, PC3 0\.0 %; '
                                                     r'1 measured, put on them$', flat) is not None, True)
            check('  every water on that one line, the water measured half and half on it too, and an arrow for each ion', lie,
                  [True, 1, True, 'Ca+2 Cl- Na+ SO4-2'])
            logged = await pca(rtmCompPcaLog=True)
            m_log = re.search(r'PC1 ([0-9.]+) % of the variance', logged or '')
            check(f'  as logs, which mixing does not keep on a line, the first component carries less ({logged})',
                  m_log is not None and 90 < float(m_log.group(1)) < 100, True)
            bad_of = await pca(rtmCompPcaVars='Na+, Kryptonite')
            check('  a variable the model does not have is said', bad_of,
                  'EMPTY "Kryptonite": no species or quantity of the model. Name them as the time chart does: pH, tot(Ca), Na+, SI(Calcite).')
            start = await pca(rtmCompPcaVars='', rtmCompAlong='distance', rtmCompTimes='0')
            check('  along the column at the start, where every cell is one water: nothing varies, and that is said', start,
                  'EMPTY Principal components need two things that vary from one water to another, and these waters have none.')
            await pca(rtmCompAlong='time', rtmCompTimes='')
            await page.ev("""(() => {
              window.__xlsx = null;
              window.__click = HTMLAnchorElement.prototype.click;
              HTMLAnchorElement.prototype.click = function () {
                if (this.download.endsWith('.xlsx')) window.__xlsx = fetch(this.href).then((r) => r.arrayBuffer())
                  .then((buf) => JSZip.loadAsync(buf)).then((z) => z.file('xl/workbook.xml').async('string'));
              };
            })()""")
            await page.ev("document.querySelector('[data-pane=\"composition\"][data-as=\"xlsx\"]').click()")
            await asyncio.sleep(1.5)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            pca_sheets = await page.ev("(async () => { const w = await window.__xlsx;"
                                       " return w ? [...w.matchAll(/<sheet [^>]*name=\"([^\"]+)\"/g)].map((m) => m[1]) : null; })()")
            check('  saved to Excel: the scores, the loadings, the variance each component carries, and the model text', pca_sheets,
                  ['run', 'loadings', 'variance', 'model'])
            await pca(rtmCompPcaLog=True)
            await comp('wilcox')
            check('a Wilcox diagram without an ACTIVITY: refused, the concentrations\' unit unknown', await page.ev(
                "document.getElementById('rtmCompEmpty').textContent"),
                'A Wilcox diagram needs the concentrations in mol/kgw, which a model with ACTIVITY has: its classes are set by the '
                'cations\' total in milliequivalents.')
            await comp('where')
            await comp('where', rtmCompAlong='time')
            await set_text(page, before)
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)

            # --- the model's own chemistry, as PhreePlot draws PHREEQC's: the Diagrams tab ---
            before = await page.ev("document.getElementById('rtmText').value")
            await set_text(page, DIAGRAM_MODEL)
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 6 species')", True, tries=40)
            await page.ev("document.querySelector('[data-tab=\"diagram\"]').click()")
            await asyncio.sleep(0.4)

            async def dg(calc=None, show=None):
                if calc:
                    sets = ''.join("(() => { const e = document.getElementById('%s'); e.value = %s;"
                                   " e.dispatchEvent(new Event('change', { bubbles: true })); })();" % (k, json.dumps(v)) for k, v in calc)
                    await page.ev(sets)
                    await page.ev("document.getElementById('rtmStatus').textContent = ''")
                    await page.ev("document.getElementById('rtmDgGo').click()")
                    await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Diagram worked out')", True, tries=60, pause=0.25)
                if show:
                    sets = ''.join("document.getElementById('%s').value = %s;" % (k, json.dumps(v)) for k, v in show)
                    await page.ev("(() => { %s document.getElementById('rtmDgShow').dispatchEvent(new Event('change', { bubbles: true })); })()" % sets)
                    await asyncio.sleep(0.4)

            check('one thing varied: the second axis\'s range is hidden', await page.ev(
                "document.getElementById('rtmDgYMore').getClientRects().length"), 0)
            await dg(calc=[['rtmDgXKind', 'pH'], ['rtmDgXFrom', '2'], ['rtmDgXTo', '12'], ['rtmDgXN', '11']],
                     show=[['rtmDgShow', 'shares'], ['rtmDgEl', 'C']])
            bj = await page.ev("""(() => { const d = document.getElementById('rtmChartDg').data;
              const k1 = 10 ** -6.352, k2 = 10 ** -10.329;
              let worst = 0;
              d[0].x.forEach((ph, i) => { const h = 10 ** -ph, den = 1 + k1 / h + k1 * k2 / (h * h);
                const want = { CO2: 1 / den, 'HCO3-': k1 / h / den, 'CO3-2': k1 * k2 / (h * h) / den };
                for (const t of d) worst = Math.max(worst, Math.abs(t.y[i] / 100 - want[t.name])); });
              return [d.map((t) => t.name).join(' '), worst < 1e-9]; })()""")
            check('pH varied from 2 to 12: the carbon\'s shares are Bjerrum\'s fractions, to 1e-9', bj, ['CO2 HCO3- CO3-2', True])
            await dg(calc=[['rtmDgYKind', 'tot'], ['rtmDgYSp', 'C'], ['rtmDgYFrom', '-5'], ['rtmDgYTo', '-1'], ['rtmDgYN', '5']],
                     show=[['rtmDgShow', 'predominance'], ['rtmDgEl', 'C']])
            pred = await page.ev("""(() => { const t = document.getElementById('rtmChartDg').data[0];
              const at = (ph) => t.text[2][t.x.indexOf(ph)].split(':')[0];
              return [t.type, t.z.length + 'x' + t.z[0].length, at(6), at(7), at(11)]; })()""")
            check('pH against log total C: a map of the species that holds most of the carbon -- CO2 at pH 6, HCO3- at 7, '
                  'CO3-2 at 11', pred, ['heatmap', '5x11', 'CO2', 'HCO3-', 'CO3-2'])
            await settle(page, "/its boundaries found/.test(document.getElementById('rtmStatus').textContent)", True, tries=60, pause=0.25)
            bd = await page.ev("""(() => { const d = document.getElementById('rtmChartDg').data;
              const fills = d.filter((t) => t.fill === 'toself').map((t) => t.name).sort().join(' ');
              const b = d.find((t) => t.name === 'boundaries');
              const xs = b ? b.x.filter((x) => x !== null) : [];
              const off = Math.max(...xs.map((x) => Math.min(Math.abs(x - 6.352), Math.abs(x - 10.329))));
              return [fills, xs.length > 0 && off < 1e-9,
                document.getElementById('rtmDgNote').textContent.includes('the boundaries between them found to 1e-10')]; })()""")
            check('  its boundaries found between the points: the fields drawn as the shapes they bound, and the boundaries at pH '
                  '6.352 and 10.329, where the carbon\'s log Ks put them, to 1e-9', bd, ['CO2 CO3-2 HCO3-', True, True])
            await page.ev("""(() => {
              window.__xlsx = null;
              window.__click = HTMLAnchorElement.prototype.click;
              HTMLAnchorElement.prototype.click = function () {
                if (this.download.endsWith('.xlsx')) window.__xlsx = fetch(this.href).then((r) => r.arrayBuffer())
                  .then((buf) => JSZip.loadAsync(buf)).then((z) => z.file('xl/workbook.xml').async('string'));
              };
            })()""")
            await page.ev("document.querySelector('[data-pane=\"diagram\"][data-as=\"xlsx\"]').click()")
            await asyncio.sleep(1.5)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            sheets = await page.ev("(async () => { const w = await window.__xlsx;"
                                   " return w ? [...w.matchAll(/<sheet [^>]*name=\"([^\"]+)\"/g)].map((m) => m[1]) : null; })()")
            check('  saved to Excel: the points, the boundaries on a sheet of their own, and the model text', sheets,
                  ['run', 'boundaries', 'model'])
            await dg(show=[['rtmDgShow', 'contour'], ['rtmDgQ', 'tot(C)']])
            tot = await page.ev("""(() => { const t = document.getElementById('rtmChartDg').data[0];
              return [t.type, t.y.every((y, j) => t.z[j].every((v) => Math.abs(v - y) < 1e-9))]; })()""")
            check('  and as contours, the total of carbon worked out at each point is the one it was held at', tot, ['contour', True])
            await page.ev("""(() => {
              window.__saved = [];
              window.__click = HTMLAnchorElement.prototype.click;
              HTMLAnchorElement.prototype.click = function () {
                const rec = { name: this.download };
                if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text());
                window.__saved.push(rec);
              };
            })()""")
            await page.ev("document.querySelector('[data-pane=\"diagram\"][data-as=\"csv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            csv = await page.ev("(async () => { const r = window.__saved[0]; return r ? [r.name, (await r.body).split('\\n').length] : null; })()")
            check('saved as CSV: a row per log total, a column per pH', csv, ['rtm_diagram_pH_tot.csv', 6])
            await dg(calc=[['rtmDgYKind', '']])
            await set_text(page, before)
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40)

            # --- a redox ladder: each couple where it turns over, the pH held; by hand, iron(3) over iron(2) alone ---
            before = await page.ev("document.getElementById('rtmText').value")
            await set_text(page, LADDER_MODEL)
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled:')", True, tries=40)
            await page.ev("document.querySelector('[data-tab=\"diagram\"]').click()")
            await asyncio.sleep(0.4)
            await page.ev("(() => { const e = document.getElementById('rtmDgYKind'); e.value = 'pHheld';"
                          " e.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            check('and the pH held at: one number, the neutral water\'s to begin with, no range', await page.ev(
                "['rtmDgYFromWord', 'rtmDgYRange', 'rtmDgYSp'].map((id) => document.getElementById(id).getClientRects().length)"
                ".concat([document.getElementById('rtmDgYFrom').value, document.getElementById('rtmDgYFrom').getAttribute('aria-label')])"),
                [0, 0, 0, '7', 'the pH'])
            await page.ev("(() => { const e = document.getElementById('rtmDgXKind'); e.value = 'pH';"
                          " e.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev("document.getElementById('rtmDgGo').click()")
            await asyncio.sleep(0.3)
            check('  refused where the pH is what is varied', await page.ev("document.getElementById('rtmStatus').textContent"),
                  'The pH is what is varied: it cannot be held as well.')
            await dg(calc=[['rtmDgXKind', 'pe'], ['rtmDgXFrom', '10'], ['rtmDgXTo', '16'], ['rtmDgXN', '61'], ['rtmDgYFrom', '3']],
                     show=[['rtmDgShow', 'ladder']])
            await settle(page, "/turns over here/.test(document.getElementById('rtmDgNote').textContent)", True, tries=60, pause=0.25)
            rung = "(() => { const d = document.getElementById('rtmChartDg').data; return d.filter((t) => t.line && t.line.width === 2.4).map((t) => t.y[0]); })()"
            pe_rung = await page.ev(rung)
            check('along pe from 10 to 16, the pH held at 3: the redox couples as a ladder, iron(3) over iron(2) turning over at pe '
                  '13.02, the relation\'s log K, to 1e-9; the water\'s own pe, 12, dotted; the note saying so', [
                      isinstance(pe_rung, list) and len(pe_rung) == 1 and abs(pe_rung[0] - 13.02) < 1e-9,
                      await page.ev("document.getElementById('rtmChartDg').data.filter((t) => t.line && t.line.dash === 'dot').map((t) => t.y[0])"),
                      await page.ev("document.getElementById('rtmDgNote').textContent")],
                  [True, [12], 'cell 0 as it starts, its pH held at 3.000; 1 couple turns over here: Fe+3/Fe+2 at pe 13.02'])
            await page.ev("(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;"
                          " HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };"
                          " if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()")
            await page.ev("document.querySelector('[data-pane=\"diagram\"][data-as=\"csv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            lcsv = await page.ev("(async () => { const r = window.__saved[0]; return r ? [r.name, ...(await r.body).trim().split('\\n')] : null; })()")
            check('  saved as CSV: a row per couple, its pe and its Eh', isinstance(lcsv, list) and lcsv[:2] == ['rtm_ladder_pH_3.csv',
                  'couple,oxidised,reduced,pe,Eh (V)'] and lcsv[2].startswith('Fe+3/Fe+2,Fe(3),Fe(2),13.02') and len(lcsv) == 3, True)
            per25 = math.log(10) * 0.0083147 * 298.15 / 96.4935
            await dg(calc=[['rtmDgXKind', 'Eh'], ['rtmDgXFrom', '0.6'], ['rtmDgXTo', '0.95'], ['rtmDgXN', '36'], ['rtmDgYFrom', '3']],
                     show=[['rtmDgShow', 'ladder']])
            await settle(page, "/turns over here/.test(document.getElementById('rtmDgNote').textContent)", True, tries=60, pause=0.25)
            eh_rung = await page.ev(rung)
            check('  along Eh: the same couple at 13.02 times the volts of a pe at 25 C, to 1e-9', isinstance(eh_rung, list)
                  and len(eh_rung) == 1 and abs(eh_rung[0] - 13.02 * per25) < 1e-9, True)
            # The couples across a map of pH and pe: each a line where the water holds as much of its element in either state.
            await set_text(page, COUPLES_MODEL)
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled:')", True, tries=40)
            await dg(calc=[['rtmDgXKind', 'pH'], ['rtmDgXFrom', '2'], ['rtmDgXTo', '8'], ['rtmDgXN', '13'],
                           ['rtmDgYKind', 'pe'], ['rtmDgYFrom', '-4'], ['rtmDgYTo', '14'], ['rtmDgYN', '19']],
                     show=[['rtmDgShow', 'couples']])
            await settle(page, "/turn over on this map/.test(document.getElementById('rtmDgNote').textContent)", True, tries=60, pause=0.25)
            lines = await page.ev("""(() => { const d = document.getElementById('rtmChartDg').data;
              const of = (name) => d.filter((t) => t.name === name && t.mode === 'lines');
              const off = (ts, f) => Math.max(...ts.flatMap((t) => t.x.map((x, i) => Math.abs(t.y[i] - f(x)))));
              const fe = of('Fe+3/Fe+2'), so = of('SO4-2/HS-');
              return [d.filter((t) => t.mode === 'lines' && t.showlegend !== false && !(t.line && t.line.dash === 'dash' && !t.name))
                .map((t) => t.name).join(' | '), fe.length, off(fe, () => 13.02) < 1e-9, so.length, off(so, (x) => (33.65 - 9 * x) / 8) < 1e-9,
                Math.min(...so.flatMap((t) => t.x)) === 2, document.getElementById('rtmDgNote').textContent]; })()""")
            check('the redox couples, as lines, over pH 2 to 8 and pe -4 to 14: iron(3) over iron(2) flat at pe 13.02, the relation\'s '
                  'log K, and sulfate over sulfide along pe = (33.65 - 9 pH)/8, each to 1e-9; the note saying how many turn over',
                  lines, ['Fe+3/Fe+2 | SO4-2/HS-', 1, True, 1, True, True,
                          'cell 0 as it starts; 2 couples turn over on this map, each where the water holds as much of its element in '
                          'either state'])
            await dg(calc=[['rtmDgYKind', ''], ['rtmDgXKind', 'pH']])
            await set_text(page, before)
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40)

            # --- the model run again for each value of what is varied: the Sweeps tab ---
            before = await page.ev("document.getElementById('rtmText').value")
            await set_text(page, SWEEP_MODEL)
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 2 species')", True, tries=40)
            await page.ev("document.querySelector('[data-tab=\"sweep\"]').click()")
            await asyncio.sleep(0.4)
            check('a parameter offered to vary, and a new choice starting from half, the value and twice it', await page.ev(
                "(() => { const w = document.getElementById('rtmSwWhat'); w.value = 'parameter:kk';"
                " w.dispatchEvent(new Event('change', { bubbles: true }));"
                " return document.getElementById('rtmSwValues').value; })()"), '0.05, 0.1, 0.2')
            await page.ev("(() => { const v = document.getElementById('rtmSwValues'); v.value = '0.1 to 0.4 in 4';"
                          " v.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev("document.getElementById('rtmSwGo').click()")
            done = await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 22)", '4 of 4 runs done in 0.', tries=60, pause=0.5)
            check(f'four runs, one for each value of kk ({done})', isinstance(done, str) and done.startswith('4 of 4 runs done'), True)
            await page.ev("(() => { const k = document.getElementById('rtmSwKey'); k.value = 'A';"
                          " k.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.4)
            summ = await page.ev("""(() => { const t = document.getElementById('rtmChartSw').data[0];
              return [t.x.join(' '), Math.max(...t.x.map((k, i) => Math.abs(t.y[i] / Math.exp(-10 * k) - 1))) < 5e-5]; })()""")
            # To the solver's tolerance, rtol 1e-6 on the way: 1.1e-5 at kk = 0.4. test-model.js has a sweep's run the same to
            # the bit as the text run by itself.
            check('against what was varied: A at the end of each run, exp(-10 kk)', summ, ['0.1 0.2 0.3 0.4', True])
            # The reaction's rate is offered, kk A at the end of each run; its extent, a sum over the run, is not.
            await page.ev("(() => { const k = document.getElementById('rtmSwKey'); k.value = 'rate(1)';"
                          " k.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.4)
            sw_rate = await page.ev("""(() => { const p = document.getElementById('rtmChartSw'), t = p.data[0];
              return [[...document.getElementById('rtmSwKey').options].map((o) => o.value).filter((v) => /^(rate|extent)\\(/.test(v)).join(' '),
                p.layout.yaxis.title.text, t.x.join(' '),
                Math.max(...t.x.map((k, i) => Math.abs(t.y[i] / (k * Math.exp(-10 * k)) - 1))) < 5e-5]; })()""")
            check('  a reaction\'s rate among what can be drawn, kk A at the end of each run; its extent, a sum over the run, not',
                  sw_rate, ['rate(1)', 'A => B, rate (/s), at the end at cell 0', '0.1 0.2 0.3 0.4', True])
            await page.ev("(() => { const k = document.getElementById('rtmSwKey'); k.value = 'A';"
                          " k.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.4)
            await page.ev("(() => { const s = document.getElementById('rtmSwShow'); s.value = 'time';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.4)
            check('  and against time, a curve per run, named for its value', await page.ev(
                "document.getElementById('rtmChartSw').data.map((t) => t.name).join(' / ')"),
                'kk = 0.1 / kk = 0.2 / kk = 0.3 / kk = 0.4')
            # Each constant in turn: kk, the model's one, raised and lowered 1 %, three runs. A at the end, exp(-10 kk), moves
            # -10 kk = -1 per cent for each per cent of kk: a bar to the left; the CSV a row for it.
            await page.ev("(() => { const s = document.getElementById('rtmSwWhat'); s.value = '*each';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            each_bar = await page.ev("[document.getElementById('rtmSwWhat').selectedOptions[0].textContent,"
                                     " document.getElementById('rtmSwOverWrap').hidden, document.getElementById('rtmSwAndWrap').hidden]")
            await page.ev("document.getElementById('rtmSwGo').click()")
            each_done = await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 17)", '3 of 3 runs done ', tries=60, pause=0.5)
            await page.ev("(() => { const k = document.getElementById('rtmSwKey'); k.value = 'A';"
                          " k.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.4)
            ranked = await page.ev("""(() => { const p = document.getElementById('rtmChartSw'), t = p.data[0];
              return [document.getElementById('rtmSwShow').value, t.type + ' ' + t.orientation, t.y.join(' | '), Math.abs(t.x[0] + 1) < 1e-4,
                t.marker.color[0], p.layout.xaxis.title.text, document.getElementById('rtmSwNote').textContent]; })()""")
            await page.ev("(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;"
                          " HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };"
                          " if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()")
            await page.ev("document.querySelector('[data-pane=\"sweep\"][data-as=\"csv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            each_csv = await page.ev("(async () => { const r = window.__saved[0]; return r ? [r.name, (await r.body).trim().split('\\n')] : null; })()")
            check('each constant in turn, first in Vary: kk, the model\'s one, raised and lowered 1 %, three runs; A at the end, '
                  'exp(-10 kk), moves -1 per cent for each per cent of kk, a bar to the left, to 1e-4; the CSV a row for it',
                  [each_bar, each_done, ranked, [each_csv[0], each_csv[1][0], len(each_csv[1])] if isinstance(each_csv, list) else each_csv],
                  [['its one constant, 1 % either way (3 runs)', True, True], '3 of 3 runs done ',
                   ['ranked', 'bar h', 'kk', True, '#e0663e', '% change in A, at the end, for 1 % more of each',
                    'A, at the end at cell 0, 0.3679 as written; 1 constant, 3 runs; 1 moves it by more than 0.1 % for 1 % more, '
                    'the most kk, -1'],
                   ['rtm_each_constant_A_end.csv', 'constant,as the text gives it,"A at the end, as written",with 1 % more of it,'
                    'with 1 % less,% change for 1 % more', 2]])
            await page.ev("(() => { const s = document.getElementById('rtmSwWhat'); s.value = 'parameter:kk';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            await set_text(page, before)
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40)

            # --- the examples that show a way of reading results open on it, once they have run ---
            before = await page.ev("document.getElementById('rtmText').value")

            async def example(ex, done, tries=120):
                await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
                await page.ev("(() => { const s = document.getElementById('rtmExample'); s.value = %s;"
                              " s.dispatchEvent(new Event('change', { bubbles: true })); })()" % json.dumps(ex))
                await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40, pause=0.25)
                await page.ev("document.getElementById('rtmRun').click()")
                return await settle(page, done, True, tries=tries, pause=0.5)

            ok = await example('bjerrum', "document.getElementById('rtmStatus').textContent.startsWith('Diagram worked out')")
            check('the carbonate example, once run, opens on Diagrams and works out the carbon against pH', [ok, await page.ev(
                "[document.querySelector('.rtm-tabs button.active').dataset.tab,"
                " document.getElementById('rtmChartDg').data.slice(0, 3).map((t) => t.name).join(' ')]")],
                [True, ['diagram', 'CO2 HCO3- CO3-2']])
            # Eh in volts up, as Pourbaix diagrams are drawn; the water's own limits in volts at 25 C.
            ok = await example('pourbaix', "/its boundaries found/.test(document.getElementById('rtmStatus').textContent)")
            eh_map = await page.ev("""(() => { const p = document.getElementById('rtmChartDg'), d = p.data;
              const per = RtmModel.ehPerPe(298.15);
              const water = d.filter((t) => t.line && t.line.dash === 'dash');
              const off = Math.max(...water.flatMap((t, q) => t.x.map((x, i) => Math.abs(t.y[i] - per * ((q ? 0 : 20.78) - x)))));
              return [document.querySelector('.rtm-tabs button.active').dataset.tab, p.layout.yaxis.title.text,
                water.map((t) => t.x.join(' to ')).join(' | '), off < 1e-12,
                [...document.getElementById('rtmDgQ').options].some((o) => o.value === 'Eh')]; })()""")
            check('the iron example, once run, opens on an Eh-pH Pourbaix diagram: Eh in volts up, the water\'s own limits at '
                  '1.229 - 0.0592 pH and -0.0592 pH volts at 25 C, and Eh among the quantities to draw', [ok, eh_map],
                  [True, ['diagram', 'Eh (V)', '2 to 12 | 2 to 12', True, True]])
            bounds_now = "(() => { const b = document.getElementById('rtmChartDg').data.find((t) => t.name === 'boundaries'); return b ? [b.x, b.y] : null; })()"
            eh_bounds = await page.ev(bounds_now)
            per = math.log(10) * 0.0083147 * 298.15 / 96.4935
            await dg(calc=[['rtmDgYKind', 'pe'], ['rtmDgYFrom', repr(-0.8 / per)], ['rtmDgYTo', repr(1.2 / per)], ['rtmDgYN', '81']])
            await settle(page, "/its boundaries found/.test(document.getElementById('rtmStatus').textContent)", True, tries=60, pause=0.25)
            pe_bounds = await page.ev(bounds_now)

            def same_bounds(a, b):
                if not a or not b or len(a[0]) != len(b[0]) or not a[0]:
                    return False
                pairs = list(zip(a[0], b[0])) + [(u, None if v is None else per * v) for u, v in zip(a[1], b[1])]
                return all((u is None) == (v is None) and (u is None or abs(u - v) < 1e-9) for u, v in pairs)
            check('  worked out again over pe, the same range in pe: the same boundaries, the Eh of each point its pe in volts, '
                  'to 1e-9', [same_bounds(eh_bounds, pe_bounds), bool(eh_bounds and len(eh_bounds[0]) > 10)], [True, True])

            # --- a chart saved as a page of its own: opened from the disk with the network off, the same chart ---
            async def saved_page(pane):
                return await page.ev("""(async () => {
                  const keep = HTMLAnchorElement.prototype.click;
                  let got = null;
                  HTMLAnchorElement.prototype.click = function () {
                    if (this.download.endsWith('.html')) got = { name: this.download, body: fetch(this.href).then((r) => r.text()) };
                  };
                  try {
                    document.querySelector('[data-pane="%s"][data-as="html"]').click();
                    for (let i = 0; i < 300 && !got; i++) await new Promise((r) => setTimeout(r, 100));
                  } finally { HTMLAnchorElement.prototype.click = keep; }
                  return got ? [got.name, await got.body] : null; })()""" % pane)

            async def ev_in(sid, expr):
                r = await page.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True},
                                    session=sid)
                res = r.get('result', {})
                if 'exceptionDetails' in res:
                    return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:200]
                return res.get('result', {}).get('value')

            async def open_offline(body, ask):
                """The page written to a file and opened in a tab of its own with the network off; ask's answer there."""
                folder = tempfile.mkdtemp(prefix='rtm-html-')
                path = os.path.join(folder, 'chart.html')
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(body)
                t2 = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
                sid2 = (await page.call('Target.attachToTarget', {'targetId': t2, 'flatten': True}))['result']['sessionId']
                try:
                    await page.call('Runtime.enable', session=sid2)
                    await page.call('Network.enable', session=sid2)
                    await page.call('Network.emulateNetworkConditions', {'offline': True, 'latency': 0, 'downloadThroughput': -1,
                                                                         'uploadThroughput': -1}, session=sid2)
                    await page.call('Page.navigate', {'url': 'file://' + path}, session=sid2)
                    for _ in range(100):
                        if await ev_in(sid2, "!!(document.getElementById('chart') && document.getElementById('chart').data)"):
                            break
                        await asyncio.sleep(0.2)
                    return await ev_in(sid2, ask)
                finally:
                    await page.call('Target.closeTarget', {'targetId': t2})
                    os.remove(path)
                    os.rmdir(folder)

            shown = await page.ev("""(() => { const p = document.getElementById('rtmChartDg');
              const b = p.data.find((t) => t.name === 'boundaries');
              return [p.data.length, p.data.map((t) => t.name || '').join('|'), JSON.stringify([b.x, b.y]),
                document.getElementById('rtmDgNote').textContent.trim(), p.layout.yaxis.title.text]; })()""")
            got = await saved_page('diagram')
            name, body = got if got else (None, '')
            there = await open_offline(body, """(() => { const p = document.getElementById('chart');
              const b = p.data.find((t) => t.name === 'boundaries');
              return [p.data.length, p.data.map((t) => t.name || '').join('|'), JSON.stringify([b.x, b.y]),
                document.querySelector('.note').textContent, typeof Plotly === 'object' && Plotly.version,
                p.layout.yaxis.title.text, !!p.querySelector('.main-svg'),
                document.querySelector('pre').textContent.includes('Ferrihydrite + 3 H+')]; })()""") if body else None
            check('a chart saved as HTML: a page of its own with plotly.js 2.27.0 in it, nothing loaded from elsewhere; opened from '
                  'the disk with the network off it draws the same traces, the same boundaries and the same axes, under the '
                  'chart\'s note, the model text below', [name, body.startswith('<!doctype html>'), 'plotly.js v2.27.0' in body,
                                                          '<script src' not in body, there],
                  ['rtm_pourbaix_diagram.html', True, True, True, shown[:4] + ['2.27.0', shown[4], True, True]])
            # What is the model's goes into the page as text, whatever it says.
            hostile = '# </script><img src=x onerror="window.__pwned=1"><!-- <script>window.__pwned=2</script> & "q"\n'
            await set_text(page, hostile + await page.ev("document.getElementById('rtmText').value"))
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40, pause=0.25)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.ev("document.getElementById('rtmDgGo').click()")
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Diagram worked out')", True,
                         tries=60, pause=0.25)
            got = await saved_page('diagram')
            body = got[1] if got else ''
            inert = await open_offline(body, """(() => [window.__pwned === undefined, document.images.length,
              document.querySelectorAll('script').length, document.querySelector('pre').textContent.startsWith(%s),
              document.getElementById('chart').data.length > 0])()""" % json.dumps(hostile.rstrip('\n'))) if body else None
            check('  a model text that would close the script and add an image comes through as text: nothing of it runs, no '
                  'image, the two scripts the page has, the comment shown as it is written', inert, [True, 0, 2, True, True])
            # A groundwater's redox ladder at pH 7, phreeqc.dat's couples: nitrate to nitrogen at the top, carbonate to methane at the
            # foot, where test-phreeqc.js has them against PHREEQC; the water's limits dashed, the water itself dotted at pe 4.
            ok = await example('redoxladder', "/turns? over here/.test(document.getElementById('rtmDgNote').textContent)")
            lad = await page.ev("""(() => { const p = document.getElementById('rtmChartDg'), d = p.data;
              const rungs = d.filter((t) => t.line && t.line.width === 2.4).map((t) => [t.hovertemplate.split(':')[0], t.y[0]])
                .sort((a, b) => b[1] - a[1]);
              const want = [11.930, 7.285, 6.135, 4.468, -3.654, -4.047];
              return [document.querySelector('.rtm-tabs button.active').dataset.tab, document.getElementById('rtmDgShow').value,
                document.getElementById('rtmDgYKind').value, rungs.map(([n]) => n).join(' > '),
                rungs.length === 6 && rungs.every(([, v], i) => Math.abs(v - want[i]) < 0.005),
                d.filter((t) => t.line && t.line.dash === 'dash').map((t) => t.y[0].toFixed(2)).join(' '),
                d.filter((t) => t.line && t.line.dash === 'dot').map((t) => t.y[0].toFixed(2)).join(' '), p.layout.yaxis.title.text]; })()""")
            check('the redox ladder example opens on its ladder at pH 7: nitrate to nitrogen, to nitrite and to ammonium, ferric to '
                  'ferrous, sulfate to sulfide and carbonate to methane, each where test-phreeqc.js has phreeqc.dat\'s; O2 and H2 at '
                  '1 atm dashed, the water itself dotted at pe 4', [ok, lad],
                  [True, ['diagram', 'ladder', 'pHheld', 'NO3-/N2 > NO3-/NO2- > NO3-/NH4+ > Fe+3/Fe+2 > SO4-2/HS- > CO3-2/CH4', True,
                          '13.78 -7.00', '4.00', 'pe']])
            # The same groundwater's couples across pH 4 to 10: nitrate to nitrite falling a pe for each pH, its two species of one
            # charge, on (28.57 - 2 pH)/2 but for the water's activity in its relation, which the ionic strength moves (9e-7 in the
            # slope, 3e-5 off the line); ferric to ferrous through the ladder's rung at pH 7.
            ok = await example('redoxcouples', "/turn over on this map/.test(document.getElementById('rtmDgNote').textContent)")
            pp = await page.ev("""(() => { const d = document.getElementById('rtmChartDg').data;
              const of = (name) => d.find((t) => t.name === name && t.mode === 'lines');
              const n2 = of('NO3-/NO2-'), fe = of('Fe+3/Fe+2');
              const slope = Math.max(...n2.x.slice(1).map((x, i) => Math.abs((n2.y[i + 1] - n2.y[i]) / (x - n2.x[i]) + 1)));
              const onK = Math.max(...n2.x.map((x, i) => Math.abs(n2.y[i] - (28.57 - 2 * x) / 2)));
              const i7 = fe.x.findIndex((x) => Math.abs(x - 7) < 1e-9);
              return [document.getElementById('rtmDgShow').value,
                d.filter((t) => t.mode === 'lines' && t.name && t.showlegend !== false).map((t) => t.name).sort().join(' | '),
                slope < 1e-5 && onK < 1e-4, i7 >= 0 && Math.abs(fe.y[i7] - 4.468) < 1e-3, d.filter((t) => t.line && t.line.dash === 'dash' && !t.name).length,
                d.some((t) => t.name === 'this water')]; })()""")
            check('the couples example opens on its pe-pH diagram over pH 4 to 10: the six couples as lines, nitrate to nitrite falling '
                  'a pe for each pH to 1e-5 and on its log K\'s (28.57 - 2 pH)/2 to 1e-4, the water\'s activity in its relation '
                  'between; ferric to ferrous through the ladder\'s 4.468 at pH 7; the water\'s limits dashed, the water itself marked',
                  [ok, pp],
                  [True, ['couples', 'CO3-2/CH4 | Fe+3/Fe+2 | NO3-/N2 | NO3-/NH4+ | NO3-/NO2- | SO4-2/HS-', True, True, 2, True]])
            # A silicate stability diagram: each phase per mole of aluminium over an activity ratio, quartz and silica dotted.
            ok = await example('silicates', "document.getElementById('rtmChartDg').data"
                                            ".filter((t) => / at saturation$/.test(t.name || '')).length === 2")
            sil = await page.ev("""(() => { const p = document.getElementById('rtmChartDg'), d = p.data;
              const fills = d.filter((t) => t.fill === 'toself').map((t) => t.name).sort().join(' ');
              const sat = (nm, at) => { const t = d.find((u) => u.name === nm + ' at saturation');
                return t ? Math.max(...t.x.filter((v) => v !== null).map((v) => Math.abs(v - at))) < 1e-9 : false; };
              const b = d.find((t) => t.name === 'boundaries');
              const gk = b ? Math.min(...b.x.filter((v) => v !== null).map((v) => Math.abs(v + 4.3925))) < 1e-9 : false;
              return [document.querySelector('.rtm-tabs button.active').dataset.tab, p.layout.yaxis.title.text, fills,
                sat('Quartz', -3.9804), sat('SiO2(a)', -2.7118), gk,
                /dotted, where Quartz and SiO2\\(a\\) are at saturation/.test(document.getElementById('rtmDgNote').textContent),
                document.getElementById('rtmDgShow').value, document.getElementById('rtmDgEl').value]; })()""")
            check('the silicate example opens on its stability diagram: K-feldspar, muscovite, kaolinite and gibbsite per mole of '
                  'aluminium over log a(H4SiO4) and log a(K+)/a(H+), gibbsite and kaolinite parted at -4.3925, quartz and amorphous '
                  'silica dotted at -3.9804 and -2.7118', [ok, sil],
                  [True, ['diagram', 'log a(K+)/a(H+)', 'Gibbsite K_feldspar K_mica Kaolinite', True, True, True, True, 'stable', 'Al']])
            # --- a run kept, and the next drawn beside it on the charts of the run ---
            ok = await example('salinisation', "document.querySelector('.rtm-tabs button.active').dataset.tab === 'composition'"
                                               " && !document.getElementById('rtmChartComp').hidden")
            await page.ev("""(() => { const sel = document.getElementById('rtmCell'); sel.value = '19';
              sel.dispatchEvent(new Event('change', { bubbles: true }));
              for (const v of ['Na+', 'pH']) {
                const el = document.querySelector(`#rtmSeries input[value="${v}"]`);
                if (el && !el.checked) { el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })); }
              } })()""")
            await settle(page, "(document.getElementById('rtmChartTime').data || []).map((t) => t.name).join(' | ')", 'Na+ | pH', tries=60, pause=0.25)
            first = await page.ev("Object.fromEntries(document.getElementById('rtmChartTime').data.map((t) => [t.name, t.y]))")
            await page.ev("document.getElementById('rtmKeep').click()")
            keep = await page.ev("[document.getElementById('rtmBesideWrap').hidden, document.getElementById('rtmBeside').selectedOptions[0].textContent,"
                                 " /^This run is kept, kept at \\d\\d:\\d\\d/.test(document.getElementById('rtmStatus').textContent)]")
            label = keep[1].split(',')[0]
            check('Keep this run: the run kept, chosen to be drawn beside the next, named by the time it was kept and its example',
                  [keep[0], bool(re.match(r'^kept at \d\d:\d\d(:\d\d)?, salinisation$', keep[1])), keep[2]], [False, True, True])
            # The next run: the water through twice as fast.
            await set_text(page, (await page.ev("document.getElementById('rtmText').value")).replace('VELOCITY = 1e-5', 'VELOCITY = 2e-5'))
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40, pause=0.25)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await settle(page, "(document.getElementById('rtmChartTime').data || []).length", 4, tries=80, pause=0.25)
            beside = await page.ev("""((label, first) => { const d = document.getElementById('rtmChartTime').data;
              const of = (n) => d.find((t) => t.name === n);
              const same = (a, b) => !!a && !!b && a.length === b.length && a.every((v, i) => v === b[i]);
              const na = of('Na+'), kna = of(`Na+, ${label}`), kph = of(`pH, ${label}`);
              return [d.map((t) => t.name).join(' | '), same(Array.from(kna.y), first['Na+']), same(Array.from(kph.y), first.pH),
                kna.line.dash, kna.line.color === na.line.color, kph.yaxis, !same(Array.from(na.y), first['Na+']),
                document.getElementById('rtmTimeNote').textContent.includes(`dashed, the run ${label}`)]; })(%s, %s)"""
                % (json.dumps(label), json.dumps(first)))
            check('  run again, the water twice as fast: against time each line ticked again for the kept run, dashed in its colour, '
                  'its values the first run\'s to the last digit, pH on its own axis; this run\'s not', beside,
                  ['Na+ | pH | Na+, %s | pH, %s' % (label, label), True, True, 'dash', True, 'y2', True, True])
            others = await page.ev("""((label) => { const p = document.getElementById('rtmChartProfile').data || [];
              const g = document.getElementById('rtmChartGradient').data || [];
              const piper = (document.getElementById('rtmChartComp').data || []).filter((t) => t.name === label);
              return [p.filter((t) => t.name.endsWith(`, ${label}`)).length === p.filter((t) => !t.name.includes(', kept at')
                && !t.name.startsWith('measured')).length && p.some((t) => t.name.endsWith(`, ${label}`)),
                g.length, g[1] && g[1].xaxis, g.length === 2 && g[0].zmin === g[1].zmin && g[0].zmax === g[1].zmax,
                piper.length, document.getElementById('rtmCompNote').textContent.includes(`dashed, the run ${label}`)]; })(%s)"""
                % json.dumps(label))
            check('  against distance each profile again for it, dashed; on Gradient its own map under this one, on one colour scale; '
                  'on the Piper diagram its path through all three panels', others, [True, 2, 'x2', True, 3, True])
            await page.ev("(() => { const s = document.getElementById('rtmCompView'); s.value = 'durov';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await settle(page, "(document.getElementById('rtmChartComp').data || []).filter((t) => t.name === %s).length" % json.dumps(label),
                         5, tries=60, pause=0.25)
            durov_beside = await page.ev("""((label) => { const d = document.getElementById('rtmChartComp').data;
              return [d.filter((t) => t.name === 'the model').length, d.filter((t) => t.name === label).length,
                d.filter((t) => t.name === label).every((t) => t.line.dash === 'dash')]; })(%s)""" % json.dumps(label))
            check('  on a Durov diagram its path through both triangles, the square, the pH and the dissolved solids, as this '
                  "run's", durov_beside, [5, 5, True])
            await page.ev("(() => { const s = document.getElementById('rtmCompView'); s.value = 'piper';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.4)
            await page.ev("(() => { const s = document.getElementById('rtmBeside'); s.value = '';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            check('  beside it nothing: the run alone again', await page.ev(
                "document.getElementById('rtmChartTime').data.map((t) => t.name).join(' | ')"), 'Na+ | pH')

            # A run kept in seconds beside one in minutes: its times in minutes, the same decay on the same curve.
            await set_text(page, '<SETTINGS>\nMODE = batch\nTEND = 600\n\n<SPECIES>\nA  1\n\n<REACTIONS>\nA => , r = 0.01*[A]\n')
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40, pause=0.25)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await page.ev("""(() => { const el = document.querySelector('#rtmSeries input[value="A"]');
              if (el && !el.checked) { el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })); } })()""")
            await page.ev("document.getElementById('rtmKeep').click()")
            label2 = (await page.ev("document.getElementById('rtmBeside').selectedOptions[0].textContent")).split(',')[0]
            await set_text(page, '<SETTINGS>\nMODE = batch\nTIME_UNIT = minute\nTEND = 10\n\n<SPECIES>\nA  1\n\n<REACTIONS>\nA => , r = 0.6*[A]\n')
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40, pause=0.25)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await settle(page, "(document.getElementById('rtmChartTime').data || []).length", 2, tries=60, pause=0.25)
            units = await page.ev("""((label) => { const d = document.getElementById('rtmChartTime').data;
              const a = d.find((t) => t.name === 'A'), k = d.find((t) => t.name === `A, ${label}`);
              return [d.length, document.getElementById('rtmBeside').options.length, Math.max(...k.x),
                Math.abs(k.y[k.y.length - 1] / a.y[a.y.length - 1] - 1) < 1e-3,
                document.getElementById('rtmChartTime').layout.xaxis.title.text]; })(%s)""" % json.dumps(label2))
            check('  a run kept in seconds beside one in minutes: its times drawn in minutes, 600 s at 10, the same decay to the same '
                  'end; both kept runs on the menu', units, [2, 3, 10, True, 'time (min)'])
            # Nothing left behind for what follows: no run beside, no ticks, the first cell -- a click at a time, as a reader
            # makes them: a chart drawn and cleared in one go throws in Plotly, its legend's margins still to come.
            await page.ev("(() => { const s = document.getElementById('rtmBeside'); s.value = '';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            await page.ev('document.querySelector(\'[data-on-click="rtm:clearSeries"]\').click()')
            await asyncio.sleep(0.3)
            await page.ev("(() => { const c = document.getElementById('rtmCell'); c.value = '0';"
                          " c.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            ok = await example('exchangesweep', "/^4 of 4 runs done/.test(document.getElementById('rtmStatus').textContent)")
            check('the exchange example opens on Sweeps and runs four capacities, a curve each at the outlet against linear time',
                  [ok, await page.ev("(() => { const p = document.getElementById('rtmChartSw');"
                                     " return [document.querySelector('.rtm-tabs button.active').dataset.tab, p.data.length,"
                                     " p.layout.xaxis.type, document.getElementById('rtmSwWhat').selectedOptions[0].textContent]; })()")],
                  [True, ['sweep', 4, 'linear', 'X- at the start (0.002)']])
            ok = await example('salinisation', "document.querySelector('.rtm-tabs button.active').dataset.tab === 'composition'"
                                               " && !document.getElementById('rtmChartComp').hidden")
            check('the salinisation example opens on Composition: the outlet\'s path through a Piper diagram, the measured waters '
                  'beside it, from Ca-HCO3 at the start to Na-Cl', [ok, await page.ev(
                      "[document.getElementById('rtmChartComp').data.filter((t) => t.name === 'measured').length,"
                      " /^cell 19: Ca–HCO₃ at the start, Na–Cl at/.test(document.getElementById('rtmCompNote').textContent)]")],
                  [True, [3, True]])
            # The examples of what came after: each opens, once run, on its view, worked out there.
            ok = await example('sodicwater', "document.getElementById('rtmCompView').value === 'wilcox'"
                                             " && /excellent|permissible|unsuitable/.test(document.getElementById('rtmCompNote').textContent)")
            check('the sodic water opens on a Wilcox diagram: excellent to good at the start, doubtful to unsuitable once the well '
                  'water comes through', [ok, await page.ev("[document.getElementById('rtmCompView').value,"
                                                            " document.getElementById('rtmCompNote').textContent]")],
                  [True, ['wilcox', 'cell 19: excellent to good at the start, doubtful to unsuitable at 1.39 d']])
            ok = await example('salinitypca', "/PC1/.test(document.getElementById('rtmCompNote').textContent)")
            pc_note = await page.ev("document.getElementById('rtmCompNote').textContent") or ''
            pc1 = re.search(r'PC1 ([0-9.]+) % of the variance', pc_note)
            check(f'the salinity example read as principal components: the first near nine tenths of the variance ({pc_note})',
                  bool(ok) and pc1 is not None and 80 < float(pc1.group(1)) < 95 and pc_note.startswith('cell 19: '), True)
            # Fresh water through a salty aquifer, on a Durov diagram in linear time: the outlet's water through the four types of
            # an aquifer freshening, its pH highest where it is Na-HCO3, its dissolved solids falling, the measured waters one a type.
            # Its pH and TDS come from the worker after the first drawing: the five panels are there once they have.
            ok = await example('freshening', "document.getElementById('rtmCompView').value === 'durov'"
                                             " && /^cell 19: /.test(document.getElementById('rtmCompNote').textContent)"
                                             " && document.getElementById('rtmChartComp').data.filter((d) => d.name === 'the model').length === 5")
            fresh = await page.ev(r"""(() => { const p = document.getElementById('rtmChartComp');
              const m = p.data.find((d) => d.name === 'the model');
              const ph = m.text.map((s) => Number((/pH ([0-9.]+)/.exec(s) || [])[1]));
              const tds = m.text.map((s) => Number((/TDS ([0-9.e+]+)/.exec(s) || [])[1]));
              const kinds = new Set(m.text.map((s) => s.split('<br>')[1]));
              const top = ph.indexOf(Math.max(...ph));
              return [document.getElementById('rtmCompNote').textContent, document.getElementById('rtmCompLogT').checked,
                p.data.filter((d) => d.name === 'the model').length, p.data.filter((d) => d.name === 'measured').length,
                ['Na–Cl', 'Na–HCO₃', 'Mg–HCO₃', 'Ca–HCO₃'].every((k) => kinds.has(k)), m.text[top].split('<br>')[1],
                Math.max(...ph) > 8.7 && Math.max(...ph) < 9, tds[0] > 3600 && tds[0] < 3800,
                tds[tds.length - 1] > 450 && tds[tds.length - 1] < 550,
                p.data.find((d) => d.name === 'measured').text.map((s) => s.split('<br>')[1]).join(' / ')]; })()""")
            check('the freshening example opens on a Durov diagram in linear time: the outlet\'s water from Na-Cl through Na-HCO3, '
                  'its pH highest there, near 9, and Mg-HCO3 to Ca-HCO3, its TDS from near 3700 mg/kgw to 500, in all five panels; '
                  'the measured waters one of each type', [ok, fresh],
                  [True, ['cell 19: Na–Cl at the start, Ca–HCO₃ at 6.94 d; 4 measured', False, 5, 3, True, 'Na–HCO₃', True, True, True,
                          'Na–Cl / Na–HCO₃ / Mg–HCO₃ / Ca–HCO₃']])
            # The same run in the unit the example gives, mg/kgw, on every chart of concentrations. Against time at the outlet the
            # calcium, magnesium, sodium and chloride dissolved, each by its atomic weight, and what was measured of them by the
            # same -- 1.0e-3 mol/kgw of calcium 40.078 mg/kgw; in mmol/kgw, chosen on another tab's bar, a thousand times the
            # model's, the four selects as one; a species whose name is no formula left off in mg, the note naming it, and in
            # the CSV in its own unit, the rest's headers in mg/kgw; the run kept and run again, the kept one beside it in mg
            # too, the same to the last digit.
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await settle(page, "(document.getElementById('rtmChartTime').data || []).length", 8, tries=60, pause=0.25)
            units_js = "['rtmUnitTime', 'rtmUnitProfile', 'rtmUnitGrad', 'rtmUnitComp'].map((id) => document.getElementById(id).value).join(' ')"
            ca_js = "Array.from(document.getElementById('rtmChartTime').data.find((t) => t.name === 'Ca, dissolved').y)"
            mg = await page.ev("""(() => { const p = document.getElementById('rtmChartTime');
              return [%s, [...document.getElementById('rtmUnitTime').options].map((o) => o.textContent).join(' | '),
                p.layout.yaxis.title.text, Array.from(p.data.find((t) => t.name === 'Ca, dissolved, measured').y), %s]; })()"""
                               % (units_js, ca_js))

            async def unit(sel, value):
                await page.ev("(() => { const s = document.getElementById(%s); s.value = %s;"
                              " s.dispatchEvent(new Event('change', { bubbles: true })); })()" % (json.dumps(sel), json.dumps(value)))
                await asyncio.sleep(0.5)
            await unit('rtmUnitProfile', 'mmol')
            mmol = await page.ev("[%s, document.getElementById('rtmChartTime').layout.yaxis.title.text, %s]" % (units_js, ca_js))
            await unit('rtmUnitTime', '')
            own = await page.ev("[document.getElementById('rtmChartTime').layout.yaxis.title.text, %s]" % ca_js)
            ratio = lambda a, b, f: (isinstance(a, list) and isinstance(b, list) and len(a) == len(b) > 100
                                     and max(abs(x / (y * f) - 1) for x, y in zip(a, b) if y > 0) < 1e-12)
            check('  in mg/kgw, as the example has it, against time: the outlet\'s calcium 40078 times its mol/kgw, the measured '
                  'calcium by the same -- 1.0e-3 mol/kgw 40.078 mg/kgw; in mmol/kgw, chosen on another tab, a thousand times, the '
                  'four selects as one; in the model\'s own the title as it was',
                  [mg[0], mg[1], mg[2], [round(v, 9) for v in mg[3]], ratio(mg[4], own[1], 40078), mmol[0], mmol[1],
                   ratio(mmol[2], own[1], 1000), own[0]],
                  ['mg mg mg mg', 'mol/kgw | mmol/kgw | µmol/kgw | nmol/kgw | mg/kgw | µg/kgw', 'concentration (mg/kgw)',
                   [40.078, 2.80546, 22.44368, 92.1794], True, 'mmol mmol mmol mmol', 'concentration (mmol/kgw)', True,
                   'concentration'])
            await unit('rtmUnitTime', 'mg')
            await page.ev("""(() => { for (const v of ['CaX2', 'Ca+2']) {
                const el = document.querySelector(`#rtmSeries input[value="${v}"]`);
                if (el && !el.checked) { el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })); } } })()""")
            await settle(page, "document.getElementById('rtmChartTime').data.some((t) => t.name === 'Ca+2')", True, tries=40, pause=0.25)
            await page.ev("(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;"
                          " HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };"
                          " if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()")
            await page.ev("document.querySelector('[data-on-click=\"rtm:downloadCsv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            left = await page.ev("""(async () => { const r = window.__saved[0];
              return [document.getElementById('rtmChartTime').data.map((t) => t.name).join(' | '),
                document.getElementById('rtmTimeNote').textContent, r ? (await r.body).split('\\n')[0] : null]; })()""")
            check('  a species whose name is no formula, CaX2, ticked in mg: left off, the note naming it; in the CSV in its own '
                  'unit, mol/kgw, the rest in mg/kgw', left,
                  ['Ca, dissolved | Ca, dissolved, measured | Mg, dissolved | Mg, dissolved, measured | Na, dissolved | '
                   'Na, dissolved, measured | Cl- | Cl-, measured | Ca+2', 'left off, not in mg/kgw: CaX2 (no formula mass)',
                   't (s),"Ca, dissolved (mg/kgw) @ cell 19","Mg, dissolved (mg/kgw) @ cell 19","Na, dissolved (mg/kgw) @ cell 19",'
                   'Cl- (mg/kgw) @ cell 19,CaX2 (mol/kgw) @ cell 19,Ca+2 (mg/kgw) @ cell 19'])
            await page.ev("document.getElementById('rtmKeep').click()")
            klabel = (await page.ev("document.getElementById('rtmBeside').selectedOptions[0].textContent")).split(',')[0]
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await settle(page, "(document.getElementById('rtmChartTime').data || []).length", 14, tries=80, pause=0.25)
            kept = await page.ev("""((label) => { const d = document.getElementById('rtmChartTime').data;
              const of = (n) => d.find((t) => t.name === n);
              const same = (a, b) => !!a && !!b && a.y.length === b.y.length && Array.from(a.y).every((v, i) => v === b.y[i]);
              return [['Ca, dissolved', 'Na, dissolved', 'Cl-', 'Ca+2'].map((n) => same(of(n), of(`${n}, ${label}`))),
                of(`Ca+2, ${label}`).line.dash, !d.some((t) => t.name.startsWith('CaX2'))]; })(%s)""" % json.dumps(klabel))
            check('  the run kept and run again: beside it, dashed, the kept run in mg/kgw, the same to the last digit, CaX2 left '
                  'off for it too', kept, [[True, True, True, True], 'dash', True])
            await page.ev("(() => { const s = document.getElementById('rtmBeside'); s.value = '';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            await page.ev("""(() => { for (const v of ['CaX2', 'Ca+2']) {
                const el = document.querySelector(`#rtmSeries input[value="${v}"]`);
                if (el && el.checked) { el.checked = false; el.dispatchEvent(new Event('change', { bubbles: true })); } } })()""")
            await asyncio.sleep(0.3)
            # Against distance and Gradient, a chart of one: CaX2 drawn as the model has it, which the note says, Ca+2 in mg/kgw
            # with the unit in its title and in the CSV's headers.
            await page.ev("document.querySelector('[data-tab=\"profile\"]').click()")
            prof = []
            for key in ['CaX2', 'Ca+2']:
                await page.ev("(() => { const s = document.getElementById('rtmProfileSpecies'); s.value = %s;"
                              " s.dispatchEvent(new Event('change', { bubbles: true })); })()" % json.dumps(key))
                await asyncio.sleep(0.6)
                prof.append(await page.ev("[document.getElementById('rtmChartProfile').layout.yaxis.title.text,"
                                          " document.getElementById('rtmProfileNote').textContent.split('; ').slice(1).join('; ')]"))
            await page.ev("(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;"
                          " HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };"
                          " if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()")
            await page.ev("document.querySelector('[data-pane=\"profile\"][data-as=\"csv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            phead = await page.ev("(async () => { const r = window.__saved[0]; return r ? (await r.body).split('\\n')[0].split(',') : null; })()")
            await page.ev("document.querySelector('[data-tab=\"gradient\"]').click()")
            await page.ev("(() => { const s = document.getElementById('rtmGradSpecies'); s.value = 'Ca+2';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.6)
            grad = await page.ev("document.getElementById('rtmChartGradient').data[0].colorbar.title.text")
            no_zones = await page.ev("[...document.getElementById('rtmGradSpecies').options].some((o) => o.value === '*zones')")
            check('  against distance CaX2 as the model has it, the note saying why, and Ca+2 in mg/kgw, the CSV\'s headers saying '
                  'so; on Gradient Ca+2 in mg/kgw, and no redox zones in Show, the model having no electron',
                  [prof, phead[0] if phead else None, bool(phead) and all(h.endswith(' (mg/kgw)') for h in phead[1:]), grad, no_zones],
                  [[['CaX2 concentration', 'CaX2 as the model has it, not in mg/kgw: no formula mass'], ['Ca+2 (mg/kgw)', '']],
                   'distance from the left-hand face (m)', True, 'Ca+2 (mg/kgw)', False])
            # Against distance one time at a time: the slider under the bar at the end while the Times are drawn; moved, one
            # curve at the stored point it is at, on an axis that spans the whole run and so holds still from point to point;
            # the very curve the Times draw at that stored time, typed; play moves it on through the run at the pace chosen and
            # stops at the end; back to Times draws the eight again; those ticked against time follow the slider too.
            t300 = await page.ev("(() => { document.querySelector('[data-tab=\"time\"]').click();"
                                 " return document.getElementById('rtmChartTime').data.find((t) => t.name === 'Ca, dissolved').x[300]; })()")
            await page.ev("document.querySelector('[data-tab=\"profile\"]').click()")
            await page.ev("(() => { const s = document.getElementById('rtmProfileSpecies'); s.value = 'Ca+2';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.6)
            row_js = ("(() => { const a = document.getElementById('rtmProfileAt'), p = document.getElementById('rtmChartProfile');"
                      " return [document.getElementById('rtmProfilePlayRow').hidden, a.max, a.value, document.getElementById('rtmProfileAtLabel').textContent,"
                      " document.getElementById('rtmProfileAll').disabled, document.getElementById('rtmProfilePlay').textContent, p.data.length,"
                      " JSON.stringify(p.layout.yaxis.range)]; })()")

            async def slide(v):
                await page.ev("(() => { const a = document.getElementById('rtmProfileAt'); a.value = %s;"
                              " a.dispatchEvent(new Event('input', { bubbles: true })); a.dispatchEvent(new Event('change', { bubbles: true })); })()"
                              % json.dumps(str(v)))
                await asyncio.sleep(0.4)
            at_times = await page.ev(row_js)
            await slide(100)
            at100 = await page.ev(row_js)
            note100 = await page.ev("document.getElementById('rtmProfileNote').textContent")
            await slide(300)
            at300 = await page.ev(row_js)
            y300 = await page.ev("Array.from(document.getElementById('rtmChartProfile').data[0].y)")
            await page.ev("(() => { const t = document.getElementById('rtmProfileTimes'); t.value = %s;"
                          " t.dispatchEvent(new Event('change', { bubbles: true })); })()" % json.dumps(repr(t300)))
            await asyncio.sleep(0.5)
            typed = await page.ev("[Array.from(document.getElementById('rtmChartProfile').data[0].y), document.getElementById('rtmProfileAtLabel').textContent]")
            await page.ev("(() => { const t = document.getElementById('rtmProfileTimes'); t.value = '';"
                          " t.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            check('  against distance one time at a time: the slider at the end under the Times, the eight curves; at a stored point '
                  'one curve, the note saying so, its axis the same from point to point; the very curve the Times draw at that '
                  'stored time, typed, which brings the Times back',
                  [at_times[:7], at100[:7], note100, at100[7] == at300[7], typed[0] == y300 and len(y300) == 20, typed[1]],
                  [[False, '513', '513', 'drag or play', True, 'play', 8], [False, '513', '100', '1.31 h', False, 'play', 1],
                   '20 cells over 0.2 m; at 1.31 h on the slider, the axis over the whole run', True, True, 'drag or play'])
            await slide(300)
            await page.ev("(() => { const s = document.getElementById('rtmProfilePace'); s.value = '5';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev("document.getElementById('rtmProfilePlay').click()")
            await asyncio.sleep(0.3)
            p1 = await page.ev(row_js)
            await asyncio.sleep(1.0)
            p2 = await page.ev(row_js)
            ended = await settle(page, "document.getElementById('rtmProfilePlay').textContent", 'play', tries=40, pause=0.25)
            p3 = await page.ev(row_js)
            await page.ev("document.getElementById('rtmProfileAll').click()")
            await asyncio.sleep(0.3)
            back = await page.ev(row_js)
            check('  play, the run in 5 s: the slider moving on from point 300, the button pause, the axis still; at the end of the '
                  'run it stops, the button play again; back to Times the eight curves again',
                  [p1[5], 300 < int(p1[2]) < int(p2[2]) < 513, p1[7] == p2[7] == at300[7], ended, p3[2], p3[3], back[:7]],
                  ['pause', True, True, 'play', '513', '6.94 d', [False, '513', '513', 'drag or play', True, 'play', 8]])
            await page.ev("(() => { const s = document.getElementById('rtmProfileSpecies'); s.value = '*ticked';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.6)
            await slide(60)
            tk60 = await page.ev(row_js)
            tk_names = await page.ev("document.getElementById('rtmChartProfile').data.map((t) => t.name).join(' | ')")
            await slide(450)
            tk450 = await page.ev(row_js)
            check('  those ticked against time on the slider: the four at its stored point, their axis the same from point to point',
                  [tk60[2:4], tk_names, tk60[7] == tk450[7], tk450[3]],
                  [['60', '18.4 min'], 'Ca, dissolved | Mg, dissolved | Na, dissolved | Cl-', True, '2.04 d'])
            await page.ev("document.getElementById('rtmProfileAll').click()")
            await page.ev("(() => { const s = document.getElementById('rtmProfileSpecies'); s.value = 'Ca+2';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            # Time in pore volumes, and several cells at once on Against time: breakthrough curves. The freshening column is
            # 0.2 m at 1e-5 m/s with a porosity of 1, so a pore volume is 2e4 s: every stored time over it, the "from" turned
            # with it, what was measured put on the axis by its own time, the three selects as one; the chloride at the outlet
            # half-way from the brackish water's to the fresh one's at about one pore volume (the cell's centre 0.975 of the
            # way along, the front spread a little). At four cells down the column each species' curves in its colour,
            # faintest at the inlet and every step 3:1 against the page, each the very curve the one cell draws; the CSV
            # with the pore volumes first and each cell's distance; a cell that is not there, said. Gradient across pore
            # volumes, its CSV saying so; Against distance's Times read in them, 2 PV as typed; back in seconds, the Times'
            # bare numbers and each "from" turned into seconds and the same curves drawn.
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await asyncio.sleep(0.4)
            in_s = await page.ev("Array.from(document.getElementById('rtmChartTime').data.find((t) => t.name === 'Cl-').x)")
            await unit('rtmTimeInTime', 'pv')
            pv = await page.ev("""(() => { const p = document.getElementById('rtmChartTime'), d = p.data;
              const cl = d.find((t) => t.name === 'Cl-'), y = cl.y, h = (y[0] + y[y.length - 1]) / 2;
              let half = null;
              for (let i = 1; i < y.length && half === null; i++) {
                if ((y[i - 1] - h) * (y[i] - h) <= 0) half = cl.x[i - 1] + ((h - y[i - 1]) / (y[i] - y[i - 1])) * (cl.x[i] - cl.x[i - 1]);
              }
              return [p.layout.xaxis.title.text, ['rtmTimeInTime', 'rtmTimeInProfile', 'rtmTimeInGrad'].map((id) => document.getElementById(id).value).join(' '),
                `${document.getElementById('rtmTMin').value} ${document.getElementById('rtmTMinUnit').textContent}`,
                document.getElementById('rtmTimeNote').textContent, Array.from(d.find((t) => t.name === 'Cl-, measured').x),
                Array.from(cl.x), half]; })()""")
            check('  time in pore volumes on Against time: each stored time over 2e4 s, the from turned with it, what was measured '
                  'at its own time over the same, the three selects as one; the outlet\'s chloride half-way at about one pore volume',
                  [pv[:4], [round(v, 12) for v in pv[4]], len(pv[5]) == len(in_s) > 100
                   and max(abs(x * 2e4 / t - 1) for x, t in zip(pv[5], in_s) if t > 0) < 1e-12,
                   isinstance(pv[6], (int, float)) and 0.9 < pv[6] < 1.0],
                  [['pore volumes', 'pv pv pv', '5e-11 PV', 'a pore volume 5.56 h'], [0.5, 2.25, 5.0, 20.0], True, True])

            async def cells(text):
                await page.ev("(() => { const c = document.getElementById('rtmCells'); c.value = %s;"
                              " c.dispatchEvent(new Event('change', { bubbles: true })); })()" % json.dumps(text))
                await asyncio.sleep(0.6)

            def lum(rgb):
                c = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in (x / 255 for x in rgb)]
                return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
            await cells('4, 9, 14, end')
            four = await page.ev("""(() => { const d = document.getElementById('rtmChartTime').data;
              const cl = d.filter((t) => /^Cl- at /.test(t.name) && !/measured/.test(t.name));
              return [cl.map((t) => t.name).join(' | '), cl.map((t) => t.line.color), getComputedStyle(document.body).backgroundColor,
                d.filter((t) => / at /.test(t.name) && !/measured/.test(t.name)).length, Array.from(cl[1].y),
                document.getElementById('rtmCell').disabled, document.getElementById('rtmTimeNote').textContent]; })()""")
            await page.ev("(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;"
                          " HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };"
                          " if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()")
            await page.ev("document.querySelector('[data-on-click=\"rtm:downloadCsv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            csv4 = await page.ev("""(async () => { const r = window.__saved[0]; const l = r ? (await r.body).split('\\n') : [''];
              const row = (l[101] || '').split(',').slice(0, 2).map(Number);
              return [r && r.name, l[0].startsWith('pore volumes,t (s),"Ca, dissolved (mg/kgw) @ cell 4 (0.045 m)",'
                + '"Ca, dissolved (mg/kgw) @ cell 9 (0.095 m)"'), l[0].endsWith(',Cl- (mg/kgw) @ cell 19 (0.195 m)'),
                Math.abs(row[0] * 2e4 / row[1] - 1) < 1e-12]; })()""")
            await cells('')
            await unit('rtmCell', '9')
            one = await page.ev("Array.from(document.getElementById('rtmChartTime').data.find((t) => t.name === 'Cl-').y)")
            await unit('rtmCell', '19')
            await cells('4, 40, x')
            bad = await page.ev("document.getElementById('rtmTimeNote').textContent")
            await cells('')
            bg = [int(v) for v in re.findall(r'\d+', four[2])[:3]] if isinstance(four, list) else [0, 0, 0]
            ratios = [(max(lum(c), lum(bg)) + 0.05) / (min(lum(c), lum(bg)) + 0.05)
                      for c in ([int(h[k:k + 2], 16) for k in (1, 3, 5)] for h in four[1])] if isinstance(four, list) else []
            check('  four cells down the column: each species at each, named by its distance, faintest at the inlet, every step '
                  '3:1 against the page, cell 9\'s curve the very one Cell draws, Cell set aside; the CSV with the pore volumes '
                  'first and each cell\'s distance; a cell that is not there, said',
                  [four[0], four[3], len(ratios) == 4 and all(a < b for a, b in zip(ratios, ratios[1:])) and min(ratios) >= 3,
                   four[4] == one and len(one) > 100, four[5], four[6], csv4, bad],
                  ['Cl- at 0.045 m | Cl- at 0.095 m | Cl- at 0.145 m | Cl- at 0.195 m', 16, True, True, True,
                   'at cells 4, 9, 14, 19, faintest nearest the inlet; a pore volume 5.56 h',
                   ['rtm_cell4_9_14_19.csv', True, True, True],
                   'at cell 4; could not read 40, x as a cell: 20 cells, 0 to 19; a pore volume 5.56 h'])
            await page.ev("document.querySelector('[data-tab=\"gradient\"]').click()")
            await asyncio.sleep(0.6)
            await page.ev("(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;"
                          " HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };"
                          " if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()")
            await page.ev("document.querySelector('[data-pane=\"gradient\"][data-as=\"csv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            grad_pv = await page.ev("""(async () => { const p = document.getElementById('rtmChartGradient'), r = window.__saved[0];
              const tx = document.getElementById('rtmChartTime').data.find((t) => t.name === 'Cl-').x, gx = p.data[0].x;
              return [p.layout.xaxis.title.text, p.data[0].hovertemplate.split('<br>')[0],
                `${document.getElementById('rtmGradTMin').value} ${document.getElementById('rtmGradTMinUnit').textContent}`,
                r ? (await r.body).split('\\n')[0].split(',')[0] : null, gx.length === tx.length - 1 && gx.every((x, k) => x === tx[k + 1])]; })()""")
            await page.ev("document.querySelector('[data-tab=\"profile\"]').click()")
            await page.ev("(() => { const t = document.getElementById('rtmProfileTimes'); t.value = '0.5, 1, 2 PV, 5';"
                          " t.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.6)
            prof_js = "[document.getElementById('rtmChartProfile').data.map((t) => t.name).join(' | '), Array.from(document.getElementById('rtmChartProfile').data[1].y)]"
            prof_pv = await page.ev(prof_js)
            await unit('rtmTimeInProfile', '')
            back = await page.ev("""[...%s, document.getElementById('rtmProfileTimes').value, document.getElementById('rtmTMin').value,
              document.getElementById('rtmGradTMin').value, ['rtmTimeInTime', 'rtmTimeInProfile', 'rtmTimeInGrad'].map((id) => document.getElementById(id).value).join('|'),
              document.getElementById('rtmChartTime').layout.xaxis.title.text]""" % prof_js)
            await page.ev("(() => { const t = document.getElementById('rtmProfileTimes'); t.value = '';"
                          " t.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            check('  Gradient across pore volumes, its from turned, its CSV saying so; Against distance\'s Times read in them, 2 PV '
                  'as typed; back in seconds, the Times\' bare numbers and each from turned into seconds, the same curves drawn',
                  [grad_pv, prof_pv[0], back[0], back[1] == prof_pv[1] and len(back[1]) == 20, back[2:]],
                  [['pore volumes', '%{x:.3g} PV', '5e-11 PV', 'distance (m) \\ pore volumes: Ca+2 (mg/kgw)', True],
                   '0.498 PV | 0.999 PV | 2.00 PV | 4.97 PV', '2.77 h | 5.55 h | 11.1 h | 1.15 d', True,
                   ['10000, 20000, 2 PV, 100000', '1e-6', '1e-6', '||', 'time (s)']])
            await page.ev("document.querySelector('[data-tab=\"composition\"]').click()")
            await asyncio.sleep(0.3)
            # The same water as PHREEQC lists it, on the Composition tab: one cell at one stored point, from the model's own
            # speciation, in PHREEQC's blocks; a complex under each of its elements, each element's total as its species make
            # it, the calcite at saturation, the exchanger's equivalent fractions adding up to 1; a time asked for; the Text
            # and the CSV saved.
            await page.ev("(() => { const v = document.getElementById('rtmCompView'); v.value = 'listing';"
                          " v.dispatchEvent(new Event('change', { bubbles: true })); })()")
            shown = await settle(page, "!document.getElementById('rtmCompListing').hidden", True, tries=60, pause=0.25)
            listed = await page.ev(r"""(() => { const box = document.getElementById('rtmCompListing');
              const heads = [...box.querySelectorAll('h4')].map((h) => h.textContent);
              const tables = [...box.querySelectorAll('table')];
              const byHead = (h) => tables[heads.slice(1).indexOf(h)];
              const dist = byHead('Distribution of species');
              const rows = [...dist.querySelectorAll('tbody tr')];
              const groupOf = new Map();
              let g = '';
              const under = [];
              for (const tr of rows) {
                if (tr.classList.contains('rtm-listing-group')) { g = tr.children[0].textContent; groupOf.set(g, tr.children[1].textContent); continue; }
                under.push([g, tr.children[0].textContent]);
              }
              const comp = Object.fromEntries([...byHead('Solution composition').querySelectorAll('tbody tr')].map((tr) => [tr.children[0].textContent, tr.children[1].textContent]));
              const si = Object.fromEntries([...byHead('Saturation indices').querySelectorAll('tbody tr')].map((tr) => [tr.children[0].textContent, tr.children[1].textContent]));
              const ex = [...byHead('Exchange composition').querySelectorAll('tbody tr')].map((tr) => Number(tr.children[2].textContent));
              const shown = (id) => !document.getElementById(id).hidden;
              return [heads, under.slice(0, 2).map((u) => u[1]).join(' '),
                under.filter((u) => u[1] === 'CaHCO3+').map((u) => u[0]).join(' '), groupOf.get('Ca') === comp.Ca && groupOf.get('Mg') === comp.Mg,
                si.Calcite, Math.abs(ex.reduce((a, b) => a + b, 0) - 1) < 1e-3,
                ['rtmCompCellWrap', 'rtmCompTimesWrap', 'rtmCompAlongWrap', 'rtmCompLogTWrap'].map(shown).join(' '),
                [...document.querySelectorAll('button[data-pane="composition"]')].filter((b) => !b.hidden).map((b) => b.textContent).join(' ')]; })()""")
            check('  the same water as PHREEQC lists it: its blocks in PHREEQC\'s order, H+ and OH- first, CaHCO3+ under C and Ca, each '
                  'element\'s total as its species make it, the calcite at saturation, the exchanger\'s fractions adding up to 1; '
                  'Cell and At in the toolbar, Along and log time not; Text among the saves, the picture\'s not',
                  [shown, listed],
                  [True, [['The water of cell 19 (1.95e-1 m) at 6.94 d', 'Solution composition', 'Description of solution',
                           'Distribution of species', 'Saturation indices', 'Minerals', 'Exchange composition'],
                          'OH- H+', 'C Ca', True, '0.00', True, 'true true false false', 'CSV Excel Text']])
            await page.ev("(() => { const t = document.getElementById('rtmCompTimes'); t.value = '1 d';"
                          " t.dispatchEvent(new Event('change', { bubbles: true })); })()")
            # The stored point nearest a day, which reads as 1.00 d, or as 24.0 h a little short of one.
            at1 = await settle(page, "/^The water of cell 19 \\(1\\.95e-1 m\\) at (1\\.0\\d d|2[34]\\.\\d h)$/.test("
                                     "document.querySelector('#rtmCompListing h4').textContent)", True, tries=60, pause=0.25)
            await page.ev("(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;"
                          " HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };"
                          " if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()")
            await page.ev("document.querySelector('[data-pane=\"composition\"][data-as=\"txt\"]').click()")
            await page.ev("document.querySelector('[data-pane=\"composition\"][data-as=\"csv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            saved = await page.ev("(async () => Promise.all(window.__saved.map(async (r) => [r.name, (await r.body).split('\\n')])))()")
            txt = saved[0] if isinstance(saved, list) and saved else ['', ['']]
            csv = saved[1] if isinstance(saved, list) and len(saved) > 1 else ['', ['']]
            # In mg/kgw, as the example has it: a column after PHREEQC's own, calcium's total by its atomic weight.
            ca_line = next((l.split() for l in txt[1] if l.startswith('\tCa ')), None)
            check('  at a time asked for, 1 d, its water; saved as Text in PHREEQC\'s columns and blocks, a column in mg/kgw after '
                  'them, and as CSV the distribution of species, the same column last',
                  [at1, txt[0], bool(re.match(r'The water of cell 19 \(1\.95e-1 m\) at (1\.0\d d|2[34]\.\d h)$', txt[1][0])), txt[1][2], any(l.strip().startswith('pH  =') for l in txt[1]),
                   sum(1 for l in txt[1] if l.startswith('Ca ')), txt[1][4].split(), bool(ca_line) and len(ca_line) == 3
                   and abs(float(ca_line[2]) / (float(ca_line[1]) * 40078) - 1) < 1e-3, csv[0], csv[1][0]],
                  [True, 'rtm_freshening_water_cell19.txt', True,
                   '-----------------------------Solution composition------------------------------', True, 1,
                   ['Elements', 'Molality', 'mg/kgw'], True,
                   'rtm_freshening_water_cell19.csv', 'species,in,molality,activity,log molality,log activity,log gamma,mg/kgw'])
            # The same run's calcium as a budget over the run: in the water, on the exchanger and in the calcite, stacked, what
            # has gone out on top, and what was there and came in, dashed, along the top of the stack: it closes; the CSV a row
            # for each stored time.
            await page.ev("(() => { const t = document.getElementById('rtmCompTimes'); t.value = '';"
                          " const v = document.getElementById('rtmCompView'); v.value = 'budget';"
                          " v.dispatchEvent(new Event('change', { bubbles: true }));"
                          " const o = document.getElementById('rtmCompBudgetOf'); o.value = 'element:Ca';"
                          " o.dispatchEvent(new Event('change', { bubbles: true })); })()")
            budget = await settle(page, "(() => { const p = document.getElementById('rtmChartComp');"
                                        " return !p.hidden && /^Ca, all of it at the end/.test(document.getElementById('rtmCompNote').textContent)"
                                        " ? (p.data || []).map((t) => t.name).join(' | ') : ''; })()",
                                  'in the water | on an exchanger | Calcite | gone out at the right-hand end | there at the start, and come in '
                                  'at the left | made by reactions, net', tries=60, pause=0.25)
            closed = re.search(r'no reaction makes or takes any to speak of: what is left over, at most [0-9.e+-]+, ([0-9.e+-]+) of',
                               await page.ev("document.getElementById('rtmCompNote').textContent") or '')
            await page.ev("(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;"
                          " HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };"
                          " if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()")
            await page.ev("document.querySelector('[data-pane=\"composition\"][data-as=\"csv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            bcsv = await page.ev("(async () => { const r = window.__saved[0]; return r ? [r.name, (await r.body).trim().split('\\n')] : null; })()")
            check('  its calcium as a budget over the run: in the water, on the exchanger and in the calcite, stacked, what has gone '
                  'out on top and what was there and came in dashed beside them -- closing to 1e-5; the CSV a row for each stored time',
                  [budget, closed is not None and float(closed.group(1)) < 1e-5,
                   [bcsv[0], bcsv[1][0], len(bcsv[1]) > 100] if isinstance(bcsv, list) else bcsv],
                  ['in the water | on an exchanger | Calcite | gone out at the right-hand end | there at the start, and come in at the '
                   'left | made by reactions, net', True,
                   ['rtm_freshening_budget_Ca.csv', 't (s),in the water,on an exchanger,Calcite,gone out at the right-hand end,'
                    'come in at the left-hand end,"made by reactions, net","in the column, all of it"', True]])
            await page.ev("(() => { const t = document.getElementById('rtmCompTimes'); t.value = '';"
                          " t.dispatchEvent(new Event('change', { bubbles: true }));"
                          " const v = document.getElementById('rtmCompView'); v.value = 'durov'; v.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            # The box as the other examples find it.
            await page.ev("(() => { const b = document.getElementById('rtmCompLogT'); b.checked = true;"
                          " b.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            # Play on the Composition tab, the same run along the column: no slider along the run; along the column one, at
            # the end under At. At a stored point the column at that time, the very waters At draws when given that time;
            # from point 100 to point 400 the waters move and the axes hold still -- the Durov's pH and dissolved solids, the
            # Schoeller's scale, the bands of where an element is, and the principal components, whose loadings and variance
            # are the whole run's; play, the run in 5 s, moves on from 300 and stops at the end; back to At, At's time again.
            t400 = await page.ev("document.getElementById('rtmChartTime').data.find((t) => t.name === 'Ca, dissolved').x[400]")
            comp_row = ("(() => { const a = document.getElementById('rtmCompAt'); return [document.getElementById('rtmCompPlayRow').hidden,"
                        " a.max, a.value, document.getElementById('rtmCompAtLabel').textContent, document.getElementById('rtmCompAll').disabled,"
                        " document.getElementById('rtmCompPlay').textContent]; })()")
            row_time = await page.ev(comp_row)
            await page.ev("(() => { const s = document.getElementById('rtmCompAlong'); s.value = 'distance';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.8)
            row_col = await page.ev(comp_row)

            async def comp_slide(v):
                await page.ev("(() => { const a = document.getElementById('rtmCompAt'); a.value = %s;"
                              " a.dispatchEvent(new Event('input', { bubbles: true })); a.dispatchEvent(new Event('change', { bubbles: true })); })()"
                              % json.dumps(str(v)))
                await asyncio.sleep(0.8)

            async def comp_view(v):
                await page.ev("(() => { const s = document.getElementById('rtmCompView'); s.value = %s;"
                              " s.dispatchEvent(new Event('change', { bubbles: true })); })()" % json.dumps(v))
                await asyncio.sleep(1.0)
            look = """(() => { const p = document.getElementById('rtmChartComp'), L = p.layout;
              return [Object.keys(L).filter((k) => /^[xy]axis/.test(k)).sort().map((k) => `${k}:${JSON.stringify(L[k].range || null)}`).join(' '),
                (L.annotations || []).map((a) => `${a.text}@${a.x},${a.y}`).join(' '), JSON.stringify(p.data.map((t) => [t.name, t.x, t.y])),
                p.data.map((t) => t.name).join(' | ')]; })()"""
            stills = {}
            for v in ['durov', 'schoeller', 'where', 'pca']:
                await comp_view(v)
                await comp_slide(100)
                a = await page.ev(look)
                await comp_slide(400)
                b = await page.ev(look)
                stills[v] = [a[0] == b[0], a[1] == b[1] if v in ('durov', 'pca') else True, a[2] != b[2], a[3] == b[3]]
            note400 = await page.ev("document.getElementById('rtmCompNote').textContent")
            await comp_view('piper')
            await comp_slide(400)
            slid = await page.ev("JSON.stringify(document.getElementById('rtmChartComp').data.find((t) => t.name === 'the model'))")
            label400 = (await page.ev(comp_row))[3]
            await page.ev("(() => { const t = document.getElementById('rtmCompTimes'); t.value = %s;"
                          " t.dispatchEvent(new Event('change', { bubbles: true })); })()" % json.dumps(repr(t400)))
            await asyncio.sleep(0.8)
            typed = await page.ev("JSON.stringify(document.getElementById('rtmChartComp').data.find((t) => t.name === 'the model'))")
            typed_row = await page.ev(comp_row)
            check('  the Composition tab one time at a time: no slider along the run, along the column one at the end under At; at a '
                  'stored point the very waters At draws when given its time, typing At bringing At back; from point 100 to 400 the '
                  'waters move and the axes hold still on the Durov, the Schoeller, where an element is (its bands the same) and the '
                  'principal components (their loadings the same), the note saying so',
                  [row_time[0], row_col, stills, slid == typed, label400, typed_row[3], note400.endswith('on the slider, the axes over the whole run')],
                  [True, [False, '513', '513', 'drag or play', True, 'play'],
                   {'durov': [True, True, True, True], 'schoeller': [True, True, True, True], 'where': [True, True, True, True],
                    'pca': [True, True, True, True]}, True, '1.08 d', 'drag or play', True])
            await page.ev("(() => { const t = document.getElementById('rtmCompTimes'); t.value = '';"
                          " t.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.4)
            await comp_slide(300)
            await page.ev("(() => { const s = document.getElementById('rtmCompPace'); s.value = '5';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev("document.getElementById('rtmCompPlay').click()")
            await asyncio.sleep(0.3)
            c1 = await page.ev(comp_row)
            await asyncio.sleep(1.0)
            c2 = await page.ev(comp_row)
            c_ended = await settle(page, "document.getElementById('rtmCompPlay').textContent", 'play', tries=40, pause=0.25)
            c3 = await page.ev(comp_row)
            await page.ev("document.getElementById('rtmCompAll').click()")
            await asyncio.sleep(0.4)
            c_back = await page.ev(comp_row)
            check('  play on the Composition tab, the run in 5 s: the slider moving on from point 300, the button pause; at the end of '
                  'the run it stops; back to At, At\'s time again',
                  [c1[5], 300 < int(c1[2]) < int(c2[2]) < 513, c_ended, c3[2:4], c_back],
                  ['pause', True, 'play', ['513', '6.94 d'], [False, '513', '513', 'drag or play', True, 'play']])
            # As the examples after it find the tab: along the run, a Durov diagram.
            await page.ev("(() => { const s = document.getElementById('rtmCompAlong'); s.value = 'time';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await comp_view('durov')
            # A tracer kept and run again at twice the speed, its dispersion a dispersivity (PECLET) and the run half as long,
            # at three cells down the column: in hours the faster front reaches each cell in half the time; in pore volumes,
            # each run in its own, the two cross one half at the same pore volume and the curves lie on each other, to the
            # solver's tolerance; the note says how long each run's pore volume is.
            tracer = ('# A tracer through a column, its dispersion a dispersivity: PECLET = LENGTH over it.\n\n<SETTINGS>\n'
                      'MODE = transport\nCELLS = 25\nLENGTH = 0.5\nDIFFUSION = 1\nADVECTION = 1\nVELOCITY = %s\nPOROSITY = 0.4\n'
                      'PECLET = 50\nLEFT = robin\nRIGHT = free\nTEND = %s\nTIME_UNIT = hour\n\n<SPECIES>\nTr  0.0  left=1.0\n\n'
                      '<REACTIONS>\n')
            boxes = await page.ev("[document.getElementById('rtmLogT').checked, document.getElementById('rtmLogY').checked]")

            async def box(bid, on):
                await page.ev("(() => { const b = document.getElementById(%s); b.checked = %s;"
                              " b.dispatchEvent(new Event('change', { bubbles: true })); })()" % (json.dumps(bid), json.dumps(on)))
                await asyncio.sleep(0.3)
            await set_text(page, tracer % ('0.002', '500'))
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 1 species')", True, tries=40, pause=0.25)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await page.ev("""(() => { const el = document.querySelector('#rtmSeries input[value="Tr"]');
              if (el && !el.checked) { el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })); } })()""")
            await cells('4, 12, end')
            await box('rtmLogT', False)
            await box('rtmLogY', False)
            await page.ev("document.getElementById('rtmKeep').click()")
            klabel = (await page.ev("document.getElementById('rtmBeside').selectedOptions[0].textContent")).split(',')[0]
            await set_text(page, tracer % ('0.004', '250'))
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 1 species')", True, tries=40, pause=0.25)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await settle(page, "(document.getElementById('rtmChartTime').data || []).length", 6, tries=40, pause=0.25)
            halves_js = """((label) => { const d = document.getElementById('rtmChartTime').data;
              const half = (t) => { for (let i = 1; i < t.y.length; i++) if (t.y[i - 1] < 0.5 && t.y[i] >= 0.5) {
                return t.x[i - 1] + ((0.5 - t.y[i - 1]) / (t.y[i] - t.y[i - 1])) * (t.x[i] - t.x[i - 1]); } return null; };
              const names = ['Tr at 0.09 m', 'Tr at 0.25 m', 'Tr at 0.49 m'];
              let apart = 0;
              for (const n of names) {
                const a = d.find((t) => t.name === n), b = d.find((t) => t.name === `${n}, ${label}`);
                for (let i = 0; i < a.x.length; i++) {
                  let j = 1;
                  while (j < b.x.length - 1 && b.x[j] < a.x[i]) j++;
                  const y = b.y[j - 1] + ((b.y[j] - b.y[j - 1]) * (a.x[i] - b.x[j - 1])) / (b.x[j] - b.x[j - 1]);
                  apart = Math.max(apart, Math.abs(y - a.y[i]));
                }
              }
              return [names.map((n) => half(d.find((t) => t.name === n))), names.map((n) => half(d.find((t) => t.name === `${n}, ${label}`))),
                apart, document.getElementById('rtmTimeNote').textContent]; })(%s)""" % json.dumps(klabel)
            hours = await page.ev(halves_js)
            await unit('rtmTimeInTime', 'pv')
            pvs = await page.ev(halves_js)
            ok_hours = isinstance(hours, list) and all(isinstance(v, (int, float)) for v in hours[0] + hours[1]) \
                and max(abs(a / b - 0.5) for a, b in zip(hours[0], hours[1])) < 1e-4
            ok_pv = isinstance(pvs, list) and all(isinstance(v, (int, float)) for v in pvs[0] + pvs[1]) \
                and max(abs(a - b) for a, b in zip(pvs[0], pvs[1])) < 1e-5
            check('  a tracer kept and run again at twice the speed, the same dispersivity: in hours its front at each cell in half '
                  'the time, in pore volumes, each run in its own, at the same pore volume and the curves on each other to 1e-4; the '
                  f'note giving each run\'s pore volume (half-way at {pvs[0] if isinstance(pvs, list) else pvs} PV, '
                  f'{pvs[2] if isinstance(pvs, list) else ""} apart at most)',
                  [ok_hours, ok_pv, isinstance(pvs, list) and pvs[2] < 1e-4, isinstance(pvs, list) and pvs[3]],
                  [True, True, True, f'at cells 4, 12, 24, faintest nearest the inlet; a pore volume 2.08 d; in the model\'s own unit: '
                   f'mg/kgw needs ACTIVITY, whose concentrations are mol/kgw; dashed, the run {klabel} in its own pore volumes, 4.17 d each'])
            # As the next model finds them: in seconds, at one cell, nothing beside, the log boxes as they were.
            await unit('rtmTimeInTime', '')
            await cells('')
            await box('rtmLogT', boxes[0])
            await box('rtmLogY', boxes[1])
            await page.ev("(() => { const s = document.getElementById('rtmBeside'); s.value = '';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            # A model without ACTIVITY, mg/kgw still chosen: its concentrations are in whatever unit its text means, so they are
            # drawn as it has them and the note says why; mg and µg on the menu, not to be chosen; times 10^3 a thousand times,
            # the title saying so.
            await set_text(page, '<SETTINGS>\nMODE = batch\nTEND = 10\n\n<SPECIES>\nA  2e-3\nB  0\n\n<REACTIONS>\nA => B, k = 0.1\n')
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40, pause=0.25)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await page.ev("""(() => { const el = document.querySelector('#rtmSeries input[value="A"]');
              if (el && !el.checked) { el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })); } })()""")
            await settle(page, "(document.getElementById('rtmChartTime').data || []).some((t) => t.name === 'A')", True, tries=40, pause=0.25)
            a_js = "document.getElementById('rtmChartTime').data.find((t) => t.name === 'A').y[0]"
            bare = await page.ev("""(() => { const p = document.getElementById('rtmChartTime');
              return [[...document.getElementById('rtmUnitTime').options].map((o) => o.textContent + (o.disabled ? ' (off)' : '')).join(' | '),
                document.getElementById('rtmUnitTime').value, p.layout.yaxis.title.text, document.getElementById('rtmTimeNote').textContent,
                %s]; })()""" % a_js)
            await unit('rtmUnitTime', 'mmol')
            bare2 = await page.ev("[document.getElementById('rtmChartTime').layout.yaxis.title.text, %s]" % a_js)
            check('a model without ACTIVITY, mg/kgw chosen before: drawn as its text has it, the note saying why; mg and µg on the '
                  'menu, not to be chosen; times 10^3 a thousand times, the title saying so',
                  [bare[:4], bare[4], bare2[0], isinstance(bare2[1], (int, float)) and bare2[1] == bare[4] * 1000],
                  [['as the model has them | × 10³ | × 10⁶ | × 10⁹ | mg/kgw, under ACTIVITY (off) | µg/kgw, under ACTIVITY (off)', '',
                    'concentration', "in the model's own unit: mg/kgw needs ACTIVITY, whose concentrations are mol/kgw"],
                   0.002, 'concentration × 10³', True])
            # The Danckwerts example opens on Against time in pore volumes, its tracer at four cells a quarter of the column
            # apart, as its description says: at a Péclet number of 5 the front spreading as it goes, half-way up at 0.29 pore
            # volumes a quarter of the way along and at 0.86 at the outlet.
            ok = await example('danckwerts', "document.getElementById('rtmStatus').textContent.startsWith('Done')"
                                             " && document.querySelector('.rtm-tabs button.active').dataset.tab === 'time'")
            await settle(page, "(document.getElementById('rtmChartTime').data || []).length", 4, tries=40, pause=0.25)
            dw = await page.ev("""(() => { const p = document.getElementById('rtmChartTime'), d = p.data;
              const half = (t) => { for (let i = 1; i < t.y.length; i++) if (t.y[i - 1] < 0.5 && t.y[i] >= 0.5) {
                return t.x[i - 1] + ((0.5 - t.y[i - 1]) / (t.y[i] - t.y[i - 1])) * (t.x[i] - t.x[i - 1]); } return null; };
              return [p.layout.xaxis.title.text, p.layout.xaxis.type, d.map((t) => t.name).join(' | '), document.getElementById('rtmCells').value,
                document.getElementById('rtmTimeNote').textContent, d.map((t) => Number(half(t).toFixed(2)))]; })()""")
            check('the Danckwerts example opens on Against time in pore volumes at four cells a quarter of the column apart, '
                  'the front half-way up at 0.29 pore volumes a quarter of the way along and at 0.86 at the outlet', [ok, dw],
                  [True, ['pore volumes', 'linear', 'X at 0.238 m | X at 0.488 m | X at 0.738 m | X at 0.988 m', '9, 19, 29, 39',
                          'at cells 9, 19, 29, 39, faintest nearest the inlet; a pore volume 11.6 d', [0.29, 0.53, 0.75, 0.86]]])
            ok = await example('calcitefit', "/^Fitted in|could not/.test(document.getElementById('rtmStatus').textContent)")
            fitted = await page.ev("[document.querySelector('.rtm-tabs button.active').dataset.tab,"
                                   " [...document.querySelectorAll('#rtmFitResult tbody tr')].slice(0, 2)"
                                   ".map((tr) => [tr.children[0].textContent, Number(tr.children[2].textContent)])]")
            check(f'the calcite example fitted on the Fit tab: kc and its CO2 at the start from 1e-4 and 5e-4 to 5.1e-4 and '
                  f'1.0e-3 ({fitted})', isinstance(fitted, list) and fitted[0] == 'fit' and len(fitted[1]) == 2
                  and abs(fitted[1][0][1] / 5.1e-4 - 1) < 0.02 and abs(fitted[1][1][1] / 1.01e-3 - 1) < 0.02, True)
            # The run against what was measured, one to one, on the same example. The fit started from the text's own numbers
            # (kc 5e-4, CO2 1e-3): its first misfit is this run's, read exactly at the times measured, and the run on show,
            # read between its stored points, comes within 2e-3 of it; the fitted run's sum of squares is the fit's misfit to
            # the last digit, diamonds beside the run's circles. Then the run's own values at four stored points as <DATA>,
            # pH less 0.1 and Ca_mg twice and half by turns: pH's bias +0.1 and spread 0.1, Ca_mg's bias a factor of 1 and
            # spread a factor of 2, the sums of squares 0.04 and 4 (log10 2)^2, exactly; the fit, made against the old
            # measurements, left out and said. The run kept, and run again with kc doubled: the kept run's figures the first
            # run's, hollow. A table in distance: a tracer's profile at a stored time, twice over, at three cells and past
            # both ends: each residual -log10 2, the ends read as the end cells; a value after the run's end and an amount of
            # none, said.
            async def fit_csv(show):
                await page.ev("(() => { const s = document.getElementById('rtmFitShow'); s.value = %s;"
                              " s.dispatchEvent(new Event('change', { bubbles: true })); })()" % json.dumps(show))
                await asyncio.sleep(0.8)
                await page.ev("(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;"
                              " HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };"
                              " if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()")
                await page.ev("document.querySelector('[data-pane=\"fit\"][data-as=\"csv\"]').click()")
                await asyncio.sleep(1)
                await page.ev("HTMLAnchorElement.prototype.click = window.__click")
                got = await page.ev("(async () => { const r = window.__saved[0]; return r ? [r.name, (await r.body).split('\\n')] : null; })()")
                return got if isinstance(got, list) else [None, ['']]
            match_rows = "[...document.querySelectorAll('#rtmFitMatch tbody tr')].map((tr) => [...tr.children].map((td) => td.textContent).join(' | '))"
            calc_text = await page.ev("document.getElementById('rtmText').value")
            await page.ev("""(() => { const rows = document.querySelectorAll('#rtmFitParams input');
              rows[0].value = '5e-4'; rows[1].value = '1e-3'; rows[0].dispatchEvent(new Event('change', { bubbles: true })); })()""")
            await asyncio.sleep(0.3)
            await page.ev("document.getElementById('rtmFitGo').click()")
            await settle(page, "/^Fitted in|could not/.test(document.getElementById('rtmStatus').textContent)", True, tries=120, pause=0.5)
            history = await fit_csv('history')
            misfits = [float(row.split(',')[1]) for row in history[1][1:] if row]
            both = await fit_csv('match')
            pts = [row.split(',') for row in both[1][1:] if row]
            ss_run = sum(float(p[6]) ** 2 for p in pts)
            ss_fit = sum(float(p[8]) ** 2 for p in pts)
            seen = await page.ev("""[document.getElementById('rtmChartFit').data.filter((t) => t.mode === 'markers').map((t) => `${t.name} ${t.marker.symbol}`).join(' | '),
              document.querySelectorAll('#rtmFitMatch tbody tr').length, document.getElementById('rtmFitNote').textContent]""")
            check('  the run against what was measured beside the fit made from the text\'s own numbers: the run on show, read between '
                  'its stored points, within 2e-3 of the fit\'s first misfit; the fitted run\'s sum of squares the fit\'s misfit to the '
                  f'last digit; diamonds beside circles (this run {ss_run:.7g}, the fit\'s first {misfits[0] if misfits else None})',
                  [both[0], both[1][0], len(pts), bool(misfits) and abs(ss_run / misfits[0] - 1) < 2e-3,
                   bool(misfits) and abs(ss_fit / misfits[-1] - 1) < 1e-12, seen],
                  ['rtm_against_measured.csv', 'column,where,time,distance (m),measured,this run,"residual, this run",the fitted run,'
                   '"residual, the fitted run"', 10, True, True,
                   ['pH circle | Ca_mg (mg/kgw) circle | pH, fitted diamond | Ca_mg (mg/kgw), fitted diamond', 6,
                    '10 values measured, each column in its own unit; this run read between its stored points and cells, linearly; '
                    'the fitted run at the times measured, as the fit ran it']])
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")

            async def tick(value, on):
                await page.ev("""((v, on) => { const el = document.querySelector(`#rtmSeries input[value="${v}"]`);
                  if (el && el.checked !== on) { el.checked = on; el.dispatchEvent(new Event('change', { bubbles: true })); } })(%s, %s)"""
                              % (json.dumps(value), json.dumps(on)))
                await asyncio.sleep(0.3)
            # The two read off the time chart, ticked for it and unticked after: the ticks as the checks after this find them.
            await tick('pH', True)
            await tick('Ca_mg', True)
            await settle(page, "['pH', 'Ca_mg (mg/kgw)'].every((n) => (document.getElementById('rtmChartTime').data || []).some((t) => t.name === n))",
                         True, tries=40, pause=0.25)
            stored = await page.ev("""(() => { const d = document.getElementById('rtmChartTime').data;
              const ph = d.find((t) => t.name === 'pH'), ca = d.find((t) => t.name === 'Ca_mg (mg/kgw)'), n = ph.x.length;
              return [Math.round(n / 4), Math.round(n / 2), Math.round(3 * n / 4), n - 1].map((i) => [ph.x[i], ph.y[i], ca.x[i] === ph.x[i] ? ca.y[i] : null]); })()""")
            await tick('pH', False)
            await tick('Ca_mg', False)
            rows = '\n'.join(f'{t!r}  {ph - 0.1!r}  {ca * (2 if k % 2 == 0 else 0.5)!r}' for k, (t, ph, ca) in enumerate(stored))
            await set_text(page, calc_text[:calc_text.rindex('\n<DATA>') + 1] + f'<DATA>\ntime   pH     Ca_mg    cell = 0\n{rows}\n')
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 9 species')", True, tries=40, pause=0.25)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await page.ev("document.querySelector('[data-tab=\"fit\"]').click()")
            await settle(page, "document.querySelectorAll('#rtmFitMatch tbody tr').length", 3, tries=40, pause=0.25)
            shifted = await fit_csv('match')
            res = {}
            for row in shifted[1][1:]:
                if row:
                    f = row.split(',')
                    res.setdefault(f[0], []).append(float(f[6]))
            first = await page.ev(match_rows)
            check('  the run\'s own values as <DATA>, pH less 0.1, Ca_mg twice and half by turns: pH\'s bias +0.1 and spread 0.1, '
                  'Ca_mg\'s bias a factor of 1 and spread a factor of 2, the sums of squares 0.04 and 4 (log10 2)^2, exactly; the '
                  'fit, made against the old measurements, left out and said',
                  [[round(v, 12) for v in res.get('pH', [])], [round(v, 12) for v in res.get('Ca_mg (mg/kgw)', [])],
                   [r.split(' | ')[:6] for r in first], await page.ev("document.getElementById('rtmFitNote').textContent")],
                  [[0.1] * 4, [round(-math.log10(2), 12), round(math.log10(2), 12)] * 2,
                   [['pH', 'this run', '4', '+0.1', '0.1', '0.04'], ['Ca_mg (mg/kgw)', 'this run', '4', '+0.000 (× 1)', '0.301 (× 2)', '0.3625'],
                    ['all together, as the Fit sums them', 'this run', '8', '', '0.2243', '0.4025']],
                   '8 values measured, each column in its own unit; this run read between its stored points and cells, linearly; '
                   'the fit was made against other measurements: <DATA> has changed since'])
            await page.ev("document.getElementById('rtmKeep').click()")
            klabel = (await page.ev("document.getElementById('rtmBeside').selectedOptions[0].textContent")).split(',')[0]
            shifted_text = await page.ev("document.getElementById('rtmText').value")
            await set_text(page, shifted_text.replace('kc  all  5e-4', 'kc  all  1e-3'))
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 9 species')", True, tries=40, pause=0.25)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await settle(page, "document.querySelectorAll('#rtmFitMatch tbody tr').length", 6, tries=40, pause=0.25)
            beside = await page.ev(match_rows)
            kept_rows = [r.replace(f' | {klabel} | ', ' | this run | ') for r in beside if f' | {klabel} | ' in r]
            check('  the run kept and run again with kc doubled: the kept run\'s figures the first run\'s, hollow, this run further off',
                  [kept_rows == first, await page.ev("document.getElementById('rtmChartFit').data.filter((t) => t.mode === 'markers')"
                                                     ".map((t) => t.marker.symbol).join(' ')"),
                   float(beside[-2].split(' | ')[5]) > float(beside[-1].split(' | ')[5])],
                  [True, 'circle circle circle-open circle-open', True])
            await page.ev("(() => { const s = document.getElementById('rtmBeside'); s.value = '';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await set_text(page, tracer % ('0.002', '500'))
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 1 species')", True, tries=40, pause=0.25)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await tick('Tr', True)
            await settle(page, "(document.getElementById('rtmChartTime').data || []).some((t) => t.name === 'Tr')", True, tries=40, pause=0.25)
            t_at = await page.ev("(() => { const x = document.getElementById('rtmChartTime').data.find((t) => t.name === 'Tr').x; return x[Math.round(x.length / 2)]; })()")
            await tick('Tr', False)
            await page.ev("document.querySelector('[data-tab=\"profile\"]').click()")
            await page.ev("(() => { const s = document.getElementById('rtmProfileSpecies'); s.value = 'Tr';"
                          " s.dispatchEvent(new Event('change', { bubbles: true }));"
                          " const t = document.getElementById('rtmProfileTimes'); t.value = %s; t.dispatchEvent(new Event('change', { bubbles: true })); })()"
                          % json.dumps(repr(t_at)))
            await asyncio.sleep(0.6)
            prof, cx = await page.ev("[Array.from(document.getElementById('rtmChartProfile').data[0].y), Array.from(document.getElementById('rtmChartProfile').data[0].x)]")
            dist = '\n'.join(f'{x!r}  {2 * prof[c]!r}' for x, c in [(0.0, 0), (cx[4], 4), (cx[12], 12), (cx[24], 24), (0.5, 24)])
            await page.ev("(() => { const t = document.getElementById('rtmProfileTimes'); t.value = '';"
                          " t.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await set_text(page, (tracer % ('0.002', '500')) + f'\n<DATA>\ndistance   Tr    at = {t_at!r}\n{dist}\n\ntime   Tr   cell = 24\n600    0.5\n200    0\n')
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 1 species')", True, tries=40, pause=0.25)
            await page.ev("document.getElementById('rtmRun').click()")
            await wait_run(page)
            await page.ev("document.querySelector('[data-tab=\"fit\"]').click()")
            await settle(page, "document.querySelectorAll('#rtmFitMatch tbody tr').length", 2, tries=40, pause=0.25)
            along = await fit_csv('match')
            check('  a table in distance, a tracer\'s profile at a stored time twice over: each residual -log10 2, past both ends read '
                  'as the end cells; a value after the run\'s end and an amount of none, said',
                  [[round(float(row.split(',')[6]), 12) for row in along[1][1:] if row and row.split(',')[6]],
                   (await page.ev(match_rows))[0].split(' | ')[:5],
                   await page.ev("document.getElementById('rtmFitNote').textContent")],
                  [[round(-math.log10(2), 12)] * 5, ['Tr', 'this run', '5', '−0.301 (× 0.5)', '0.301 (× 2)'],
                   '6 values measured, each column in its own unit; this run read between its stored points and cells, linearly; '
                   '1 amount at or below zero left out; 1 after the run\'s end; '
                   'the fit was made against other measurements: <DATA> has changed since'])
            # Breakthrough numbers under Against time: a tracer X and Y held back with R = 4, in a column whose dispersion is a
            # dispersivity, for six pore volumes, at four cells. Y's semi-discrete equations are X's with time over 4, so it is
            # half-way at four times X's time at every cell, to the solver's tolerance (the outlet's Y still going at the end,
            # half-way of the 0.9987 it got to); X's retardation within 1 % of 1. Out of the column: six pore volumes of a
            # unit concentration came in, u T = 0.04 m/d x 150 d = 6; X's share gone out 5/6, Y's 1/3, what reactions made
            # next to nothing. Kept, and run again with Y's R = 2: this run's Y at twice X's time, the kept run's still four.
            btc_text = ('# A tracer and a species held back four times as much, through a column whose dispersion is a dispersivity.\n\n'
                        '<SETTINGS>\nMODE = transport\nCELLS = 100\nLENGTH = 1.0\nDIFFUSION = 1\nADVECTION = 1\nVELOCITY = 0.01\n'
                        'POROSITY = 0.25\nPECLET = 100\nLEFT = robin\nRIGHT = free\nTEND = 150\nTIME_UNIT = day\n\n<SPECIES>\n'
                        'X  0.0  left=1.0\nY  0.0  left=1.0  R=4\n\n<REACTIONS>\n')
            numbers_js = ("[...document.querySelectorAll('#rtmTimeNumbers tbody tr')].map((tr) => [tr.children[0].textContent,"
                          " ...[...tr.children].slice(1).map((td) => (td.dataset.v === undefined ? td.textContent : Number(td.dataset.v)))])")
            far_js = ("Object.fromEntries([...document.querySelectorAll('#rtmTimeNumbers tbody tr')].filter((tr) => tr.children.length === 6)"
                      ".map((tr) => [tr.children[0].textContent, tr.children[2].textContent.endsWith('at the end of the run')]))")

            async def numbers_after_run(text):
                await set_text(page, text)
                await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 2 species')", True, tries=40, pause=0.25)
                await page.ev("document.getElementById('rtmRun').click()")
                await wait_run(page)
                await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
                return await settle(page, "[...document.querySelectorAll('#rtmTimeNumbers tbody tr')].length >= 10", True, tries=60, pause=0.25)
            await set_text(page, btc_text)
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 2 species')", True, tries=40, pause=0.25)
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await tick('X', True)
            await tick('Y', True)
            await cells('24, 49, 74, end')
            await page.ev("(() => { const b = document.getElementById('rtmBtc'); b.checked = true; b.dispatchEvent(new Event('change', { bubbles: true })); })()")
            ok = await numbers_after_run(btc_text)
            rows = await page.ev(numbers_js)
            at_end = await page.ev(far_js)
            half = {r[0]: r for r in rows if isinstance(r, list) and ' at ' in r[0]}
            out_rows = {r[0]: r for r in rows if isinstance(r, list) and ' at ' not in r[0]}
            sites = ['0.245', '0.495', '0.745', '0.995']
            ratios = [half[f'Y at {c} m'][3] / half[f'X at {c} m'][3] for c in sites] if len(half) == 8 else []
            rx = [half[f'X at {c} m'][5] for c in sites] if len(half) == 8 else []
            x_out = out_rows.get('X', [None] * 8)
            y_out = out_rows.get('Y', [None] * 8)
            check('  breakthrough numbers: Y, held back with R = 4, half-way at four times the tracer\'s time at each of four cells, '
                  'the tracer\'s retardation within 1 % of 1, the outlet\'s Y still going at the end; six came in, 5/6 of the tracer '
                  f'gone out and 1/3 of Y, reactions next to nothing (ratios {ratios}, X\'s retardation {rx})',
                  [ok, len(ratios) == 4 and max(abs(q - 4) for q in ratios) < 1e-3, len(rx) == 4 and max(abs(v - 1) for v in rx) < 0.01,
                   [name for name, end in sorted(at_end.items()) if end] if isinstance(at_end, dict) else at_end,
                   isinstance(x_out[3], float) and abs(x_out[3] - 6) < 1e-12 and abs(x_out[7] - 5 / 6) < 1e-6 and abs(x_out[6]) < 1e-5,
                   isinstance(y_out[7], float) and abs(y_out[7] - 1 / 3) < 1e-3 and abs(y_out[6]) < 1e-3],
                  [True, True, True, ['Y at 0.995 m'], True, True])
            await page.ev("document.getElementById('rtmKeep').click()")
            klabel = (await page.ev("document.getElementById('rtmBeside').selectedOptions[0].textContent")).split(',')[0]
            await numbers_after_run(btc_text.replace('R=4', 'R=2'))
            rows2 = await page.ev(numbers_js)
            half2 = {r[0]: r for r in rows2 if isinstance(r, list) and r[0].count(' at ') >= 1 and r[0][:1] in 'XY'}
            mine2 = [half2[f'Y at {c} m'][3] / half2[f'X at {c} m'][3] for c in sites[:3]] if f'Y at 0.245 m' in half2 else []
            kept2 = [half2[f'Y at {c} m, {klabel}'][3] / half2[f'X at {c} m, {klabel}'][3] for c in sites[:3]] if f'Y at 0.245 m, {klabel}' in half2 else []
            check('  kept, and run again with Y\'s R = 2: this run\'s Y half-way at twice the tracer\'s time, the kept run\'s at four, each in '
                  'rows of its own; what has come out of the column for both runs',
                  [len(mine2) == 3 and max(abs(q - 2) for q in mine2) < 1e-3, len(kept2) == 3 and max(abs(q - 4) for q in kept2) < 1e-3,
                   sorted(r[1] for r in rows2 if isinstance(r, list) and r[0] in ('X', 'Y'))],
                  [True, True, sorted(['this run', 'this run', klabel, klabel])])
            # As the checks after find the time chart: nothing beside, one cell, no numbers, X and Y unticked.
            await page.ev("(() => { const s = document.getElementById('rtmBeside'); s.value = '';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev("(() => { const b = document.getElementById('rtmBtc'); b.checked = false; b.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await cells('')
            await tick('X', False)
            await tick('Y', False)
            ok = await example('frontuncertainty', "/runs done in|could not/.test(document.getElementById('rtmStatus').textContent)")
            bands = await page.ev("[document.querySelector('.rtm-tabs button.active').dataset.tab,"
                                  " document.getElementById('rtmStatus').textContent.slice(0, 20),"
                                  " [...new Set(document.getElementById('rtmChartUn').data.map((t) => t.name).filter(Boolean))].sort().join(' / '),"
                                  " document.getElementById('rtmChartUn').layout.yaxis.type]")
            check('the sorbing front\'s uncertainty: a hundred runs, the outlet\'s breakthrough as bands on a linear axis',
                  [ok, bands], [True, ['uncertainty', '100 of 100 runs done', '25 to 75 % / 5 to 95 % / the median / the model as written',
                                      'linear']])
            # What matters, by sensitivity indices of the same runs: the retardation the value's, the velocity's spread little.
            await page.ev("(() => { const s = document.getElementById('rtmUnShow'); s.value = 'indices';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await settle(page, "/the dummy/.test(document.getElementById('rtmUnNote').textContent)", True, tries=120, pause=0.25)
            idx = await page.ev("""(() => { const p = document.getElementById('rtmChartUn'), d = p.data;
              const of = (name) => d.find((t) => t.name === name);
              const s1 = of("first-order Sobol' index (EASI)"), dl = of("Borgonovo's δ"), pw = of('PAWN, the median KS distance');
              const row = (t, k) => t.x[t.y.indexOf(k)];
              const lo = (t, k) => row(t, k) - t.error_x.arrayminus[t.y.indexOf(k)];
              const hi = (t, k) => row(t, k) + t.error_x.array[t.y.indexOf(k)];
              const rf = 'Rf', v = 'VELOCITY', dm = 'a dummy: drawn, never used';
              return [d.length, s1.y.join(' | '), lo(s1, rf) > hi(s1, v), row(dl, rf) > hi(dl, v), row(pw, rf) > hi(pw, v),
                lo(dl, rf) > hi(dl, dm), row(s1, v) < 0.2, dl.x.every((x) => x > -0.2 && x <= 1),
                /^Sensitivity indices worked out from 100 runs/.test(document.getElementById('rtmStatus').textContent)]; })()""")
            check('  what matters, by sensitivity indices of the same runs: the retardation factor\'s first-order index clear of the '
                  'velocity\'s, its delta and PAWN above the velocity\'s intervals and its delta clear of the dummy\'s; the velocity\'s '
                  'first-order index under 0.2; every delta between 0 and 1, read off the normal scores', idx,
                  [3, 'Rf | VELOCITY | a dummy: drawn, never used', True, True, True, True, True, True, True])
            await page.ev("(() => { const s = document.getElementById('rtmUnShow'); s.value = 'time';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            # Four uncertain numbers of a decaying nuclide's column, three hundred runs, opened on the indices: the retardation
            # factor and the velocity clear of the dummy, the dispersivity and the concentration flowing in reaching it. The column
            # is steady by the end, so the exact indices are those of Wehner and Wilhelm's formula for its outlet -- C0 4a e^(Pe/2)
            # / ((1+a)^2 e^(a Pe/2) - (1-a)^2 e^(-a Pe/2)), a = sqrt(1 + 4 Da/Pe), Da = ln 2/30 Rf L/v -- 0.709, 0.230, 0.0085 and
            # 0.0040 by four million draws, and each first-order index's interval holds its own.
            ok = await example('nuclideindices', "/the dummy/.test(document.getElementById('rtmUnNote').textContent)")
            idx = await page.ev("""(() => { const d = document.getElementById('rtmChartUn').data;
              const of = (name) => d.find((t) => t.name === name);
              const s1 = of("first-order Sobol' index (EASI)"), dl = of("Borgonovo's δ");
              const at = (t, k) => t.y.indexOf(k);
              const lo = (t, k) => t.x[at(t, k)] - t.error_x.arrayminus[at(t, k)];
              const hi = (t, k) => t.x[at(t, k)] + t.error_x.array[at(t, k)];
              const keys = ['Rf', 'VELOCITY', 'PECLET', 'Nuclide flowing in'], dm = 'a dummy: drawn, never used';
              const exact = [0.709, 0.230, 0.0085, 0.0040];
              return [document.querySelector('.rtm-tabs button.active').dataset.tab, s1.y.join(' | '),
                /^Sensitivity indices worked out from 300 runs/.test(document.getElementById('rtmStatus').textContent),
                keys.slice(0, 2).map((k) => lo(s1, k) > hi(s1, dm) && lo(dl, k) > hi(dl, dm)),
                keys.slice(2).map((k) => lo(s1, k) < hi(s1, dm) && lo(dl, k) < hi(dl, dm)),
                lo(s1, 'Rf') > hi(s1, 'VELOCITY') && lo(dl, 'Rf') > hi(dl, 'VELOCITY'),
                keys.map((k, i) => lo(s1, k) <= exact[i] && exact[i] <= hi(s1, k))]; })()""")
            check('the decaying nuclide opens on its sensitivity indices from 300 runs: the retardation factor\'s and the velocity\'s '
                  'first-order indices and deltas clear of the dummy\'s, the retardation factor\'s clear of the velocity\'s; the '
                  'dispersivity\'s and the concentration flowing in\'s reaching the dummy\'s; each first-order index\'s interval '
                  'holding the steady column\'s exact one', [ok, idx],
                  [True, ['uncertainty', 'Rf | VELOCITY | PECLET | Nuclide flowing in | a dummy: drawn, never used', True, [True, True],
                          [True, True], True, [True, True, True, True]]])
            await page.ev("(() => { const s = document.getElementById('rtmUnShow'); s.value = 'time';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            # Redox zones: organic carbon at a hundredth of a millimole a day through a groundwater's oxidants, each drawn as its
            # element's total in a valence state, a day at most between points (MAX_STEP). Each oxidant lasts as long as its
            # electrons: the oxygen's 0.25 mM to day 25, the nitrate's 0.15 to N2 another 18.75 days, the pyrolusite's 0.1 mmol
            # 5 and the ferrihydrite's 0.2 another 5, the sulfate's 0.3 mM 60; then half the carbon goes to methane.
            ok = await example('redoxzones', "document.querySelector('.rtm-tabs button.active').dataset.tab === 'time'"
                                             " && (document.getElementById('rtmChartTime').data || []).length === 7")
            zones = await page.ev("""(() => { const d = document.getElementById('rtmChartTime').data;
              const of = (name) => d.find((t) => t.name === name);
              const when = (t, test) => { const i = t.y.findIndex(test); return i < 0 ? null : t.x[i]; };
              // At or after the day, within a step of it; a hundredth of a day early where a mineral's last goes at an event.
              const near = (x, at) => x !== null && x >= at - 0.01 && x <= at + 1.000001;
              const ch4 = of('C(-4), dissolved');
              return [d.map((t) => t.name).join(' | '), document.getElementById('rtmChartTime').layout.xaxis.title.text,
                of('O2').x.length > 160 && Math.max(...of('O2').x.slice(1).map((x, i) => x - of('O2').x[i])) <= 1.000001,
                near(when(of('O2'), (v) => v < 1e-9), 25), near(when(of('N(5), dissolved'), (v) => v < 1e-9), 43.75),
                near(when(of('Mn+2'), (v) => v > 0.9999e-4), 48.75), near(when(of('Fe(2), dissolved'), (v) => v > 1.9999e-4), 53.75),
                Math.abs(ch4.y[ch4.y.length - 1] / ((160 - 113.75) * 1e-5 / 2) - 1) < 0.01]; })()""")
            check('the redox zones example opens on the time chart: oxygen, nitrate, manganese(2), iron(2), sulfate, sulfide and '
                  'methane, a day at most between points; each oxidant gone when its electrons are -- the oxygen at day 25, the '
                  'nitrate at 43.75, the pyrolusite\'s manganese all dissolved at 48.75, the ferrihydrite\'s iron at 53.75, to the '
                  'day -- and methane half the carbon after the sulfate\'s, to 1 %', [ok, zones],
                  [True, ['O2 | N(5), dissolved | Mn+2 | Fe(2), dissolved | S(6), dissolved | S(-2), dissolved | C(-4), dissolved',
                          'time (d)', True, True, True, True, True, True]])
            # Redox zones along a plume: a leachate rich in organic carbon into an oxic aquifer, 30 cells over 40 days, every
            # stored point read back in a millisecond or two. It opens on Gradient, the pe as contours against time, not its
            # logarithm; at the end, from the inlet by the pe, methane below -2.5, iron below 3, manganese below 10, nitrate
            # below 12.5 and the oxygen ahead of them.
            ok = await example('redoxplume', "document.querySelector('.rtm-tabs button.active').dataset.tab === 'gradient'"
                                             " && ((document.getElementById('rtmChartGradient').data || [])[0] || {}).type === 'contour'"
                                             " && document.getElementById('rtmStatus').textContent.startsWith('Done')", tries=400)
            plume = await page.ev("""(() => { const d = document.getElementById('rtmChartGradient').data[0];
              const zone = (pe) => (pe < -2.5 ? 'methane' : pe < 3 ? 'iron' : pe < 10 ? 'manganese' : pe < 12.5 ? 'nitrate' : 'oxygen');
              const last = d.z.map((row) => zone(row[row.length - 1]));
              return [document.getElementById('rtmGradSpecies').value, document.getElementById('rtmGradLogT').checked,
                d.x[0] === 0 && d.x[d.x.length - 1] === 40, d.y.length,
                last.filter((v, c) => c === 0 || v !== last[c - 1]).join(' ')]; })()""")
            check('the plume example opens on Gradient: the pe as contours over the 40 days, time not on a log axis, the 30 cells '
                  'up; at the end, from the inlet by the pe, methane, iron, manganese, nitrate and the oxygen ahead of them',
                  [ok, plume], [True, ['pe', False, True, 30, 'methane iron manganese nitrate oxygen']])
            # Against distance, what is ticked against time together at the end, on a log axis from 1e-10: the pe on its own
            # axis on the right, its steps the zones; methane and siderite from the inlet, the ferrihydrite partly gone in the
            # iron zone, manganese(2) beyond it, the oxygen at the far end.
            await page.ev("document.querySelector('[data-tab=\"profile\"]').click()")
            n_prof = await settle(page, "(document.getElementById('rtmChartProfile').data || []).length", 9, tries=60, pause=0.5)
            dist = await page.ev("""(() => { const p = document.getElementById('rtmChartProfile'), d = p.data;
              const of = (name) => d.find((t) => t.name === name).y;
              return [document.getElementById('rtmProfileSpecies').value, d.map((t) => t.name).join(' | '),
                document.getElementById('rtmProfileNote').textContent, p.layout.yaxis.type, p.layout.yaxis.range[0],
                document.getElementById('rtmProfileYFrom').value,
                d.find((t) => t.name === 'pe').yaxis === 'y2' && p.layout.yaxis2.title.text === 'pe',
                of('pe')[0] < -2.5 && of('pe')[29] > 12.5,
                of('C(-4), dissolved')[5] > 1e-4 && of('Siderite')[5] > 4e-3 && of('Ferrihydrite')[5] === 0,
                of('Ferrihydrite')[12] > 0 && of('Ferrihydrite')[12] < 4.9e-3 && of('Siderite')[20] === 0,
                of('Mn+2')[18] > 1e-3 && of('O2')[29] > 1e-4 && of('O2')[20] < 1e-12]; })()""")
            check('  Against distance draws what is ticked against time together at the end, on a log axis from 1e-10, the pe on '
                  'its own axis on the right: methane and siderite from the inlet, the ferrihydrite partly gone in the iron zone, '
                  'manganese(2) beyond it, the oxygen at the far end', [n_prof, dist],
                  [9, ['*ticked', 'pe | O2 | N(5), dissolved | Mn+2 | Ferrihydrite | Siderite | S(6), dissolved | C(-4), dissolved | '
                       'C(0), dissolved', '30 cells over 30 m; at 40.0 d, the end of the run; the log axis from 1e-10', 'log', -10,
                       '1e-10', True, True, True, True, True]])
            check('  its legend under the axis\' title, not over it, though the chart was drawn while its tab was hidden', await page.ev(
                """(() => { const p = document.getElementById('rtmChartProfile');
                  return p.querySelector('.legend').getBoundingClientRect().top >= p.querySelector('.g-xtitle').getBoundingClientRect().bottom; })()"""),
                True)
            # At a time asked for, the first of Times alone: on day 20 methane at the inlet, and the iron zone still at 5.5 m.
            await page.ev("(() => { const t = document.getElementById('rtmProfileTimes'); t.value = '20, 30';"
                          " t.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.6)
            at20 = await page.ev("""(() => { const d = document.getElementById('rtmChartProfile').data;
              const pe = d.find((t) => t.name === 'pe').y;
              const note = document.getElementById('rtmProfileNote').textContent;
              return [note.startsWith('30 cells over 30 m; at 20.0 d'), note.includes('the first of Times alone'),
                pe[0] < -2.5 && pe[5] > -2.5 && pe[5] < 3]; })()""")
            check('  with Times, at the first of them alone: on day 20 methane at the inlet, the iron zone still at 5.5 m', at20,
                  [True, True, True])
            # Saved as CSV: the distance, and a column for each drawn.
            await page.ev("""(() => {
              window.__saved = [];
              window.__click = HTMLAnchorElement.prototype.click;
              HTMLAnchorElement.prototype.click = function () {
                const rec = { name: this.download };
                if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text());
                window.__saved.push(rec);
              };
            })()""")
            await page.ev("document.querySelector('[data-pane=\"profile\"][data-as=\"csv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            csv = await page.ev("(async () => { const r = window.__saved[0]; return r ? [r.name, (await r.body).trim().split('\\n')] : null; })()")
            check('  saved as CSV: the distance and a column for each drawn, a row for each cell, what a log axis cannot show there '
                  'too -- the oxygen at the inlet on day 20 under 1e-60, below the floor, and the ferrihydrite there none',
                  [csv[0], csv[1][0][:60], len(csv[1]), float(csv[1][1].split(',')[2]) < 1e-60, csv[1][1].split(',')[5]]
                  if isinstance(csv, list) else csv,
                  ['rtm_profile_ticked.csv', 'distance from the left-hand face (m),pe,O2,"N(5), dissolved"', 31, True, '0'])
            await page.ev("(() => { const t = document.getElementById('rtmProfileTimes'); t.value = '';"
                          " t.dispatchEvent(new Event('change', { bubbles: true })); })()")
            # Against time, the example's log axis from 1e-10 too; a floor above some curves names them, one not read says so,
            # and empty the axis reaches the least drawn, the oxygen at the inlet at 1e-73.
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await asyncio.sleep(0.6)

            async def time_floor(text):
                await page.ev("(() => { const t = document.getElementById('rtmYFrom'); t.value = %s;"
                              " t.dispatchEvent(new Event('change', { bubbles: true })); })()" % json.dumps(text))
                await asyncio.sleep(0.5)
                return await page.ev("(() => { const p = document.getElementById('rtmChartTime');"
                                     " return [p.layout.yaxis.range[0], document.getElementById('rtmTimeNote').textContent]; })()")
            opened = await page.ev("[document.getElementById('rtmYFrom').value, document.getElementById('rtmChartTime').layout.yaxis.range[0],"
                                   " document.getElementById('rtmTimeNote').textContent]")
            above = await time_floor('1e-3')
            unread = await time_floor('abc')
            cleared = await time_floor('')
            check('  Against time, the example\'s log axis from 1e-10 as well; from 1e-3 the note names the curves wholly below it; '
                  'one not read says so, the axis reaching the least drawn, as it does with none',
                  [opened, above[0], above[1], unread[1], unread[0] < -60, cleared[0] < -60, cleared[1]],
                  [['1e-10', -10, 'the log axis from 1e-10'], -3,
                   'the log axis from 1e-3, below it all through: O2, N(5), dissolved, Mn+2, S(6), dissolved, C(-4), dissolved',
                   'could not read "abc" as where the log axis starts', True, True, ''])
            check('  the floor waits while the axis is linear', await page.ev(
                "(() => { const b = document.getElementById('rtmLogY'); b.checked = false; b.dispatchEvent(new Event('change', { bubbles: true }));"
                " const off = [document.getElementById('rtmYFrom').disabled, document.getElementById('rtmChartTime').layout.yaxis.type];"
                " b.checked = true; b.dispatchEvent(new Event('change', { bubbles: true }));"
                " return [...off, document.getElementById('rtmYFrom').disabled]; })()"), [True, 'linear', False])
            # Gradient, methane by log concentration from 1e-10: the colour scale from it, below it in its colour; a surface's
            # value axis from it, below it out of the box; the CSV with every value, methane at 1e-144 where the water is oxic.
            await page.ev("document.querySelector('[data-tab=\"gradient\"]').click()")
            await asyncio.sleep(0.6)

            async def grad_floor(view):
                await page.ev("(() => { document.getElementById('rtmGradSpecies').value = 'CH4';"
                              " document.getElementById('rtmGradLogC').checked = true; document.getElementById('rtmGradCFrom').value = '1e-10';"
                              " const v = document.getElementById('rtmGradView'); v.value = %s;"
                              " v.dispatchEvent(new Event('change', { bubbles: true })); })()" % json.dumps(view))
                await asyncio.sleep(1.0)
                return await page.ev("(() => { const p = document.getElementById('rtmChartGradient'), d = p.data[0];"
                                     " return [d.type, d.zmin === undefined ? d.cmin : d.zmin, (d.zmax === undefined ? d.cmax : d.zmax) > -3.5,"
                                     " p.layout.scene ? p.layout.scene.zaxis.range[0] : null,"
                                     " document.getElementById('rtmGradNote').textContent.split('; ').pop()]; })()")
            g_map = await grad_floor('map')
            await page.ev("(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;"
                          " HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };"
                          " if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()")
            await page.ev("document.querySelector('[data-pane=\"gradient\"][data-as=\"csv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            g_least = await page.ev("(async () => { const r = window.__saved[0]; if (!r) return null;"
                                    " const rows = (await r.body).trim().split('\\n').slice(1);"
                                    " return Math.min(...rows.flatMap((l) => l.split(',').slice(1).map(Number).filter(Number.isFinite))); })()")
            g_surface = await grad_floor('surface')
            check('  Gradient, methane by log concentration from 1e-10: the colour scale from it, what lies below in its colour; a '
                  'surface\'s value axis from it, below it out of the box; the CSV with every value, 1e-144 where the water is oxic',
                  [g_map, isinstance(g_least, (int, float)) and g_least < -140, g_surface],
                  [['heatmap', -10, True, None, 'the colour scale from 1e-10, below it in its colour'], True,
                   ['surface', -10, True, -10, 'the colour scale from 1e-10, below it out of the box']])
            await page.ev("(() => { document.getElementById('rtmGradSpecies').value = 'pe'; document.getElementById('rtmGradLogC').checked = false;"
                          " document.getElementById('rtmGradCFrom').value = ''; const v = document.getElementById('rtmGradView'); v.value = 'contour';"
                          " v.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.5)
            # The redox zones on Gradient, first in Show in a model with the electron: each cell at each stored time by the
            # couple holding its pe, the most poising capacity n Tox Tred/(Tox + Tred), O2 2 Tox against the water. In the
            # order the couples turn over -- oxic, nitrate, manganese, iron, sulfate, methane -- the nitrite never holding it;
            # at the end from the inlet sulfate, methane, iron, manganese, nitrate and the oxygen ahead; a map, not contours,
            # log concentration and smooth not to be had; the CSV by name. And cell 15 at every stored time worked out by
            # hand from every species' concentration there, the time chart's CSV, with each couple's species written out.
            await page.ev("(() => { const s = document.getElementById('rtmGradSpecies'); s.value = '*zones';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(1.2)
            zmap = await page.ev("""(() => { const p = document.getElementById('rtmChartGradient'), d = p.data[0];
              const names = d.colorbar.ticktext;
              const last = d.z.map((row) => names[row[row.length - 1]]);
              return [document.getElementById('rtmGradSpecies').options[0].textContent, d.type, names.join(' | '),
                last.filter((v, c) => c === 0 || v !== last[c - 1]).join(' > '),
                document.getElementById('rtmGradNote').textContent.split('; ').slice(1).join('; '),
                document.getElementById('rtmGradLogC').disabled, document.getElementById('rtmGradSmooth').disabled]; })()""")
            await page.ev("(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;"
                          " HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };"
                          " if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()")
            await page.ev("document.querySelector('[data-pane=\"gradient\"][data-as=\"csv\"]').click()")
            await asyncio.sleep(1)
            # Every species at cell 15: nothing ticked against time, the CSV every species.
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await page.ev('document.querySelector(\'[data-on-click="rtm:clearSeries"]\').click()')
            await asyncio.sleep(0.3)
            await page.ev("(() => { const c = document.getElementById('rtmCell'); c.value = '15';"
                          " c.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            await page.ev("document.querySelector('[data-on-click=\"rtm:downloadCsv\"]').click()")
            await asyncio.sleep(1.5)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            saved = await page.ev("(async () => Promise.all(window.__saved.map(async (r) => [r.name, (await r.body).trim().split('\\n')])))()")
            zone_csv = saved[0] if isinstance(saved, list) and saved else ['', ['']]
            cell_csv = saved[1] if isinstance(saved, list) and len(saved) > 1 else ['', ['']]
            couples = [('O2/H2O', 2, {'O2': 2}, None), ('NO3-/NO2-', 2, {'NO3-': 1}, {'NO2-': 1}), ('NO3-/N2', 5, {'NO3-': 1}, {'N2': 2}),
                       ('SO4-2/HS-', 8, {'SO4-2': 1, 'HSO4-': 1}, {'HS-': 1, 'H2S': 1, 'FeS_ppt': 1}),
                       ('CO3-2/CH4', 8, {k: 1 for k in ('CO3-2', 'HCO3-', 'CO2', 'CaHCO3+', 'CaCO3', 'Calcite', 'Siderite')}, {'CH4': 1}),
                       ('Fe+3/Fe+2', 1, {k: 1 for k in ('Fe+3', 'FeOH+2', 'Fe(OH)2+', 'Fe(OH)3', 'Fe(OH)4-', 'Ferrihydrite')},
                        {k: 1 for k in ('Fe+2', 'FeOH+', 'FeS_ppt', 'Siderite')}),
                       ('Pyrolusite/Mn+2', 2, {'Pyrolusite': 1}, {'Mn+2': 1})]
            by_hand = []
            head = [h.rsplit(' @ cell 15', 1)[0] for h in cell_csv[1][0].split(',')]
            for line in cell_csv[1][1:]:
                v = dict(zip(head, [float(x) if x else 0.0 for x in line.split(',')]))
                tot = lambda terms: sum(n * max(0.0, v[k]) for k, n in terms.items())
                best, zone = 0.0, ''
                for name, n, ox, red in couples:
                    o = tot(ox)
                    beta = n * (o if red is None else (o * tot(red) / (o + tot(red)) if o + tot(red) > 0 else 0.0))
                    if beta > best:
                        best, zone = beta, name
                by_hand.append(zone)
            row15 = next((l.split(',')[1:] for l in zone_csv[1][1:] if l.split(',')[0] == '15.5'), [])
            check('  the redox zones on Gradient, first in Show with the electron: oxic, nitrate, manganese, iron, sulfate and '
                  'methane in the order they turn over, the nitrite never holding the pe; at the end from the inlet sulfate, '
                  'methane, iron, manganese, nitrate and the oxygen ahead; a map, log concentration and smooth not to be had; '
                  'cell 15 at all its stored times the couple worked out by hand from every species there, oxic, then nitrate, '
                  'manganese and iron as the plume reaches it',
                  [zmap, zone_csv[0], len(row15), row15 == by_hand, [z for j, z in enumerate(by_hand) if j == 0 or z != by_hand[j - 1]]],
                  [['The redox zones: the couple holding the pe', 'heatmap',
                    'O2/H2O | NO3-/N2 | Pyrolusite/Mn+2 | Fe+3/Fe+2 | SO4-2/HS- | CO3-2/CH4',
                    'SO4-2/HS- > CO3-2/CH4 > Fe+3/Fe+2 > Pyrolusite/Mn+2 > NO3-/N2 > O2/H2O',
                    'the redox zones by the couple holding the pe, oxidised first: O2/H2O 57.4 %, NO3-/N2 4.1 %, Pyrolusite/Mn+2 '
                    '14.2 %, Fe+3/Fe+2 12.6 %, SO4-2/HS- 2.7 %, CO3-2/CH4 9.0 % of the waters; never holding it: NO3-/NO2-; '
                    'drawn as a map: zones are no amount to draw contours of or raise into a surface', True, True],
                   'rtm_gradient__zones.csv', 3021, True, ['O2/H2O', 'NO3-/N2', 'Pyrolusite/Mn+2', 'Fe+3/Fe+2']])
            await page.ev("(() => { const c = document.getElementById('rtmCell'); c.value = '0';"
                          " c.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev("document.querySelector('[data-tab=\"gradient\"]').click()")
            await page.ev("(() => { const s = document.getElementById('rtmGradSpecies'); s.value = 'pe';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.5)
            # What each reaction does, at cell 5, where the plume passes. The plume's one line, the organic carbon oxidised,
            # has its rate and its extent in a group of the series. The rate goes on the right with the pH and the like,
            # kdoc [CH2O]: 0.05 of the CH2O drawn beside it at every stored point, to the last digit. The extent goes on the
            # left with the amounts: at each point the trapezoid of the rate's curve up to there, from 0 at the start, which
            # a linear axis draws.
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await page.ev("(() => { const c = document.getElementById('rtmCell'); c.value = '5';"
                          " c.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            rx_list = await page.ev("""(() => { const heads = [...document.querySelectorAll('#rtmSeries .rtm-series-head')];
              const h = heads.find((b) => b.dataset.group === 'reactions');
              return [heads.map((b) => b.dataset.group).join(' '), h ? h.textContent : null,
                [...document.querySelectorAll('#rtmSeries label[data-group="reactions"]')]
                  .map((l) => `${l.querySelector('input').value}: ${l.textContent}${l.hidden ? ' (hidden)' : ''}`).join(' | ')]; })()""")
            await page.ev("""(() => { const b = document.getElementById('rtmLogY'); b.checked = false;
              b.dispatchEvent(new Event('change', { bubbles: true }));
              for (const k of ['CH2O', 'rate(1)', 'extent(1)']) {
                const i = document.querySelector(`#rtmSeries input[value="${k}"]`); i.checked = true;
                i.dispatchEvent(new Event('change', { bubbles: true })); } })()""")
            await settle(page, "(document.getElementById('rtmChartTime').data || []).length", 3, tries=60, pause=0.25)
            rx = await page.ev("""(() => { const p = document.getElementById('rtmChartTime'), d = p.data;
              return [d.map((t) => t.name + (t.yaxis === 'y2' ? ' (right)' : '')).join(' | '), p.layout.yaxis2 ? p.layout.yaxis2.title.text : null,
                d[0].x, ...d.map((t) => t.y)]; })()""")
            t5, ch2o, rate5, ext5 = rx[2:6] if isinstance(rx, list) and len(rx) == 6 else [[0.0], [0.0], [1.0], [1.0]]
            # The worker's sum, step by step as it adds.
            trap, s = [0.0], 0.0
            for i in range(1, len(t5)):
                s += 0.5 * (rate5[i] + rate5[i - 1]) * (t5[i] - t5[i - 1])
                trap.append(s)
            check('  what each reaction does, a group of the series: the plume\'s one line, its rate and its extent; at cell 5 the '
                  'rate on the right, kdoc [CH2O] at every stored point to the last digit, and the extent on the left with the '
                  'amounts, at each point the trapezoid of the rate\'s curve up to there',
                  [rx_list, rx[0] if isinstance(rx, list) else rx, rx[1] if isinstance(rx, list) else None,
                   len(t5) == len(ch2o) == len(rate5) == len(ext5) > 100, max(abs(r - 0.05 * c) for r, c in zip(rate5, ch2o)),
                   max(abs(e - w) for e, w in zip(ext5, trap)), ext5[-1] > 1e-3],
                  [['species water totals saturation reactions activities', 'What each reaction does 2',
                    'rate(1): CH2O => CO3-2 + 6 H+ + 4 e-, rate | extent(1): CH2O => CO3-2 + 6 H+ + 4 e-, extent'],
                   'CH2O | CH2O => CO3-2 + 6 H+ + 4 e-, rate (right) | CH2O => CO3-2 + 6 H+ + 4 e-, extent',
                   'CH2O => CO3-2 + 6 H+ + 4 e-, rate', True, 0.0, 0.0, True])
            await page.ev('document.querySelector(\'[data-on-click="rtm:clearSeries"]\').click()')
            await page.ev("""(() => { const b = document.getElementById('rtmLogY'); b.checked = true;
              b.dispatchEvent(new Event('change', { bubbles: true }));
              const c = document.getElementById('rtmCell'); c.value = '0'; c.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            await asyncio.sleep(0.3)
            # In a diagram, the rate of the water held: cell 5 as the run ends, its pH from 5 to 9. CH2O is in no relation,
            # so the rate is the same at each pH, the run's last. The extent, a sum over the run and no value of one water,
            # is not offered.
            await page.ev("document.querySelector('[data-tab=\"diagram\"]').click()")
            await asyncio.sleep(0.3)
            dg_ids = ['rtmDgCell', 'rtmDgAt', 'rtmDgYKind', 'rtmDgXKind', 'rtmDgXFrom', 'rtmDgXTo', 'rtmDgXN']
            dg_before = await page.ev("%s.map((id) => document.getElementById(id).value)" % json.dumps(dg_ids))
            await dg(calc=list(zip(dg_ids, ['5', 'end', '', 'pH', '5', '9', '5'])), show=[['rtmDgShow', 'quantity'], ['rtmDgQ', 'rate(1)']])
            dg_rate = await page.ev("""(() => { const p = document.getElementById('rtmChartDg'), d = p.data;
              return [[...document.getElementById('rtmDgQ').options].map((o) => o.value).filter((v) => /^(rate|extent)\\(/.test(v)).join(' '),
                p.layout.yaxis.title.text, d.length, d[0].x, d[0].y]; })()""")
            check('  in a diagram the rate of the water held, mol/kgw a day: cell 5 as the run ends, its pH from 5 to 9, the run\'s '
                  'last rate at each, CH2O in no relation; the extent, a sum over the run, not offered',
                  [dg_rate[:4], [v == rate5[-1] for v in dg_rate[4]]] if isinstance(dg_rate, list) else dg_rate,
                  [['rate(1)', 'CH2O => CO3-2 + 6 H+ + 4 e-, rate (mol/kgw/d)', 1, [5, 6, 7, 8, 9]], [True] * 5])
            await page.ev(''.join("(() => { const e = document.getElementById('%s'); e.value = %s;"
                                  " e.dispatchEvent(new Event('change', { bubbles: true })); })();" % (k, json.dumps(v))
                                  for k, v in zip(dg_ids, dg_before or [])))
            # The budget by each reaction on the plume. CO3-2 over the whole column: the organic carbon's oxidation is all
            # that makes it and nothing takes it, and what no line accounts for is nearly all of it again, the relations
            # taking it on to the bicarbonate, CO2 and the minerals. Carbon, all of it: no line makes or takes any, the line
            # moving it from CH2O to the carbonate, the leftover the summing's. CH2O at cell 5: what the line took of it at
            # every stored point is the rate drawn against time above, and its sum the extent, to the last digit.
            await page.ev("document.querySelector('[data-tab=\"composition\"]').click()")
            comp_before = await page.ev("[document.getElementById('rtmCompView').value, document.getElementById('rtmCompBudgetOf').value]")
            await pick('rtmCompView', 'budget')
            await pick('rtmCompBudgetOf', 'species:CO3-2')
            await pick('rtmCompBudgetBy', 'lines')
            await pick('rtmCompBudgetAt', 'column')
            await settle(page, "/^CO3-2 over the whole column/.test(document.getElementById('rtmCompNote').textContent)", True, tries=80, pause=0.25)
            co3 = await page.ev("""(() => {
              const rows = [...document.querySelectorAll('#rtmCompLines tbody tr')].map((tr) => [...tr.children]);
              const v = (td) => (td.dataset.v === undefined ? null : Number(td.dataset.v));
              const first = rows[0];
              const every = v(rows.find((r) => r[0].textContent === 'every relation')[4]);
              const err = v(rows.find((r) => r[0].textContent === "the summing's error")[4]);
              return [rows.map((r) => r[0].textContent).join(' | '), first[1].textContent, v(first[2]) > 0, v(first[3]),
                every < -0.9 * v(first[2]), Math.abs(err) < 1e-6 * v(first[2]),
                /; the relations took [0-9.e+-]+ net, 7 of them, the most by Siderite <=> Fe\\+2 \\+ CO3-2 \\(-0\\.05[0-9]+\\); the summing's error [-0-9.e+]+, [0-9.e+-]+ of what was made and taken$/
                  .test(document.getElementById('rtmCompNote').textContent)]; })()""")
            plume_line = str(await page.ev("document.getElementById('rtmText').value.split('\\n').findIndex((l) => l.startsWith('CH2O => CO3-2')) + 1"))
            # HCO3-, which no line makes: the chart saying so, and the table its relation all that made it.
            await pick('rtmCompBudgetOf', 'species:HCO3-')
            await settle(page, "/makes or takes any HCO3-/.test(document.getElementById('rtmCompEmpty').textContent)", True, tries=80, pause=0.25)
            hco3 = await page.ev("""(() => {
              const rows = [...document.querySelectorAll('#rtmCompLines tbody tr')].map((tr) => [...tr.children]);
              const v = (td) => (td.dataset.v === undefined ? null : Number(td.dataset.v));
              const by = (name) => rows.find((r) => r[0].textContent === name);
              return [document.getElementById('rtmCompEmpty').textContent.replace(/of it, [-0-9.e+]+ by/, 'of it, X by'),
                !document.getElementById('rtmCompLines').hidden, rows.map((r) => r[0].textContent).join(' | '),
                v(by('CO3-2 + H+ <=> HCO3-')[4]) === v(by('made by reactions, net, as the budget has it')[4]),
                v(by("the summing's error")[4])]; })()""")
            await pick('rtmCompBudgetOf', 'element:C')
            await settle(page, "/makes or takes any C/.test(document.getElementById('rtmCompEmpty').textContent)", True, tries=80, pause=0.25)
            carbon = await page.ev("document.getElementById('rtmCompEmpty').textContent")
            await pick('rtmCompBudgetOf', 'species:CH2O')
            await pick('rtmCompBudgetAt', '5')
            await settle(page, "/^CH2O at cell 5/.test(document.getElementById('rtmCompNote').textContent)", True, tries=80, pause=0.25)
            await page.ev("(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;"
                          " HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };"
                          " if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()")
            await page.ev("document.querySelector('[data-pane=\"composition\"][data-as=\"csv\"]').click()")
            await asyncio.sleep(1)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            c5csv = await page.ev("(async () => { const r = window.__saved[0]; return r ? (await r.body).trim().split('\\n') : null; })()")
            c5rows = [[float(x) for x in line.split(',')] for line in c5csv[1:]] if isinstance(c5csv, list) else []
            check('  the budget by each reaction on the plume: of CO3-2 over the whole column the organic carbon\'s oxidation all '
                  'that makes it, nothing taking it, and the relations, relation by relation, taking nearly all of it on, the most '
                  'into siderite, the summing\'s error under 1e-6; HCO3-, which no line makes, all of it from its own relation; '
                  'carbon, all of it, made and taken by no line, the leftover the summing\'s; of CH2O at cell 5 what the line took '
                  'at every stored point the rate drawn against time, and its sum the extent, to the last digit',
                  [co3, hco3, carbon, len(c5rows) == len(rate5), all(row[2] == -r for row, r in zip(c5rows, rate5)),
                   all(row[3] == -e for row, e in zip(c5rows, ext5)), all(row[1] == 0 for row in c5rows)],
                  [['CH2O => CO3-2 + 6 H+ + 4 e- | every reaction | Each relation, over the run | Siderite <=> Fe+2 + CO3-2 | '
                    'CO3-2 + 2 H+ <=> CO2 + H2O | CO3-2 + H+ <=> HCO3- | CO3-2 + 10 H+ + 8 e- <=> CH4 + 3 H2O | '
                    'Ca+2 + CO3-2 + H+ <=> CaHCO3+ | Calcite <=> Ca+2 + CO3-2 | Ca+2 + CO3-2 <=> CaCO3 | every relation | '
                    'the summing\'s error | made by reactions, net, as the budget has it', plume_line, True, 0, True, True, True],
                   ['No <REACTIONS> line makes or takes any HCO3- over the whole column: what the reactions made of it, X by the end, '
                    'is what the relations moved, in the table.', True, 'every reaction | Each relation, over the run | '
                    'CO3-2 + H+ <=> HCO3- | every relation | the summing\'s error | made by reactions, net, as the budget has it', True, 0],
                   'No <REACTIONS> line makes or takes any C, all of it over the whole column: what the budget counts the reactions '
                   'as having made of it, ' + carbon.split('of it, ')[-1].split(' by the end')[0] + ' by the end, is the summing\'s '
                   'error, the relations only moving an element between its species.' if isinstance(carbon, str) else carbon,
                   True, True, True, True])
            await pick('rtmCompBudgetAt', 'column')
            await pick('rtmCompBudgetBy', 'where')
            await pick('rtmCompBudgetOf', comp_before[1])
            await pick('rtmCompView', comp_before[0])
            await asyncio.sleep(0.3)
            # An example that gives no floor: each axis from the least drawn again.
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
            await page.ev("(() => { const s = document.getElementById('rtmExample'); s.value = 'tracer';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.5)
            check('  an example that gives no floor leaves none: each log axis reaching the least drawn', await page.ev(
                "['rtmYFrom', 'rtmProfileYFrom', 'rtmGradCFrom'].map((id) => document.getElementById(id).value).join('|')"), '||')
            # The ticks put back as they were, one click: what follows reads the chart's first trace.
            await page.ev('document.querySelector(\'[data-on-click="rtm:clearSeries"]\').click()')
            await asyncio.sleep(0.3)
            await set_text(page, before)
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40)

            # --- the model fitted to what <DATA> measured: the Fit tab, on the calcite-at-a-rate example ---
            before = await page.ev("document.getElementById('rtmText').value")
            # The example's text, not the example: choosing it would set its view, the time chart's log boxes with it.
            await set_text(page, await page.ev("RTM_EXAMPLES.find((e) => e.id === 'calciterate').text"))
            await page.ev("document.querySelector('[data-on-click=\"rtm:applyModel\"]').click()")
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 9 species')", True, tries=40, pause=0.25)
            # The rows of the model before are the user's; a text typed in keeps them, so they are put to this model's first.
            await page.ev("document.querySelector('[data-tab=\"fit\"]').click()")
            await asyncio.sleep(0.4)
            await page.ev("(() => { const s = document.querySelector('#rtmFitParams select'); s.value = 'parameter:kc';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.4)
            check('the Fit tab offers the parameter, from the value the text gives it, and every column of <DATA> ticked', await page.ev(
                "[[...document.querySelectorAll('#rtmFitParams select')].map((s) => s.value + ' from '"
                " + s.parentElement.querySelector('input').value).join(' / '),"
                " [...document.querySelectorAll('#rtmFitCols input')].map((i) => i.value + (i.checked ? '+' : '-')).join(' ')]"),
                ['parameter:kc from 0.0005', 'pH+ Ca_mg+'])
            check('  and among what can be fitted, a relation\'s log K and a reaction\'s constant are offered', await page.ev(
                "[...document.querySelectorAll('#rtmFitParams select optgroup')].map((g) => g.label)"
                ".filter((l) => /log K|constant/.test(l)).join(' | ')"), "A relation's log K")
            await page.ev("document.getElementById('rtmFitGo').click()")
            fitted = await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Fitted in', tries=60, pause=0.5)
            check(f'kc fitted to the pH and the calcium measured ({fitted})', fitted, 'Fitted in')
            res = await page.ev("""(() => { const t = document.querySelector('#rtmFitResult table tbody tr');
              const v = Number(t.children[2].textContent);
              return [t.children[0].textContent, v > 4e-4 && v < 6e-4, /× or ÷/.test(t.children[3].textContent),
                document.getElementById('rtmChartFit').data.map((d) => d.name).join(' / ')]; })()""")
            check('  the table gives the fitted kc and its error as a factor; the chart the run at it beside what was measured', res,
                  ['kc', True, True, 'pH / pH, measured / Ca_mg (mg/kgw) / Ca_mg (mg/kgw), measured'])
            await page.ev("document.getElementById('rtmFitApply').click()")
            applied = await settle(page, "/^kc\\s+all\\s+0\\.000\\d+/m.test(document.getElementById('rtmText').value)"
                                         " && document.getElementById('rtmStatus').textContent.startsWith('The fitted values are in')", True, tries=40)
            check('  and Put the fitted values in the model writes kc into its line in <PARAMETERS>', applied, True)
            await page.ev("document.querySelector('[data-tab=\"uncertainty\"]').click()")
            await asyncio.sleep(0.3)
            await page.ev("document.getElementById('rtmUnFromFit').click()")
            await asyncio.sleep(0.3)
            fromfit = await page.ev("[...document.querySelectorAll('#rtmUnRows [data-row]')].map((e) => e.value)")
            check('  From the fit, on the Uncertainty tab: kc as a lognormal about its fitted value, times or over its standard '
                  'error, alone, so no correlations to draw it with', isinstance(fromfit, list) and fromfit[:2] == ['parameter:kc', 'lognormal']
                  and 4e-4 < float(fromfit[2]) < 6e-4 and 1 < float(fromfit[3]) < 1.2 and len(fromfit) == 4
                  and await page.ev("document.getElementById('rtmUnCorrWrap').hidden"), True)
            await set_text(page, before)
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40)

            # --- the model run for draws of what is uncertain: the Uncertainty tab ---
            before = await page.ev("document.getElementById('rtmText').value")
            await set_text(page, UNCERTAIN_MODEL)
            await page.ev("document.querySelector('[data-on-click=\"rtm:applyModel\"]').click()")
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled: 2 species')", True, tries=40, pause=0.25)
            await page.ev("document.querySelector('[data-tab=\"uncertainty\"]').click()")
            await asyncio.sleep(0.4)
            # Rows the model before left are the user's: this check starts its own.
            await page.ev("(() => { const s = document.querySelector('#rtmUnRows select[data-field=\"what\"]'); s.value = 'parameter:kk';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            check('a number drawn starts as a lognormal about the value the text gives it, times or over 2', await page.ev(
                "[...document.querySelectorAll('#rtmUnRows [data-row=\"0\"]')].map((e) => e.value).join(' / ')"),
                'parameter:kk / lognormal / 0.25 / 2')
            await page.ev("""(() => { const set = (sel, v) => { const e = document.querySelector(sel); e.value = v;
              e.dispatchEvent(new Event('change', { bubbles: true })); };
              set('#rtmUnRows input[data-row="0"][data-field="b"]', '1.5'); set('#rtmUnN', '101'); set('#rtmUnSeed', '1');
              set('#rtmUnScheme', 'lhs'); })()""")
            await page.ev("(() => { while (document.querySelectorAll('#rtmUnRows .rtm-fit-row').length > 1)"
                          " document.querySelector('#rtmUnRows .rtm-fit-x[data-row=\"1\"]').click(); })()")
            await page.ev("document.getElementById('rtmUnAdd').click()")
            await asyncio.sleep(0.3)
            check('  and another takes the next parameter, not a setting', await page.ev(
                "document.querySelector('#rtmUnRows select[data-row=\"1\"][data-field=\"what\"]').value"), 'parameter:zz')
            await page.ev("document.getElementById('rtmUnGo').click()")
            done = await settle(page, "/^101 of 101 runs done/.test(document.getElementById('rtmStatus').textContent)", True, tries=80, pause=0.5)
            check('101 runs, the model as written beside them', done, True)
            check('  the reactions\' rates among what the bands can be drawn of; their extents, sums over the run, not', await page.ev(
                "[...document.getElementById('rtmUnKey').options].map((o) => o.value).filter((v) => /^(rate|extent)\\(/.test(v)).join(' ')"),
                'rate(1) rate(2)')
            await page.ev("""(() => { window.__saved = []; window.__click = HTMLAnchorElement.prototype.click;
              HTMLAnchorElement.prototype.click = function () { const rec = { name: this.download };
                if (this.href.startsWith('blob:')) rec.body = fetch(this.href).then((r) => r.text()); window.__saved.push(rec); }; })()""")
            for show in ['matters', 'time']:
                await page.ev("(() => { const s = document.getElementById('rtmUnShow'); s.value = %s;"
                              " s.dispatchEvent(new Event('change', { bubbles: true })); })()" % json.dumps(show))
                await asyncio.sleep(0.5)
                await page.ev("document.querySelector('[data-pane=\"uncertainty\"][data-as=\"csv\"]').click()")
                await asyncio.sleep(0.6)
            await page.ev("HTMLAnchorElement.prototype.click = window.__click")
            csvs = await page.ev("(async () => Promise.all(window.__saved.map(async (r) => (await r.body).split('\\n'))))()")
            runs_csv = [[float(x) for x in line.split(',')] for line in csvs[0][1:]]
            ks = [r[1] for r in runs_csv]
            # The same draws as distributions.html's engine makes from seed 1, the first stream, by Latin hypercube.
            engine = await page.ev("""(async () => { const b = new URL('resources/js/distributions/', document.baseURI).href;
              const [d, s] = await Promise.all([import(b + 'dist.js'), import(b + 'sampling.js')]);
              const D = d.makeDistribution({ family: 'lognormal', params: { mu: Math.log(0.25), sigma: Math.log(1.5) } });
              const w = s.uniforms('lhs', 101, 1, 'A');
              return Array.from(w.u, (u, i) => D.at(u, w.uc[i])); })()""")
            check('  kk drawn as distributions.html draws it: the same 101 values, by Latin hypercube from seed 1',
                  isinstance(engine, list) and len(engine) == 101 and all(abs(a - b) <= 1e-12 * abs(b) for a, b in zip(ks, engine)), True)
            band = [float(x) for x in csvs[1][-1].split(',')]
            ko = sorted(ks)
            want = [math.exp(-10 * ko[95]), math.exp(-10 * ko[50]), math.exp(-10 * ko[5])]
            check('  the bands at the end: 5 %, the median and 95 % of A are exp(-10 kk) at kk\'s 95th, 51st and 6th of 101, '
                  'to the solver\'s tolerance', [band[0] == 10] + [abs(band[i] / w - 1) < 1e-4 for i, w in zip([1, 3, 5], want)],
                  [True, True, True, True])
            rho = await page.ev("document.getElementById('rtmUnNote').textContent")
            matters = await page.ev("(() => { const s = document.getElementById('rtmUnShow'); s.value = 'matters';"
                                    " s.dispatchEvent(new Event('change', { bubbles: true }));"
                                    " return document.getElementById('rtmChartUn').data[0].x; })()")
            check('  what matters: A at the end falls with kk, a rank correlation of -1, and zz, which nothing reads, near 0',
                  isinstance(matters, list) and abs(matters[0] + 1) < 1e-12 and abs(matters[1]) < 0.3, True)
            await set_text(page, before)
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40)

            # --- the Jacobian check ------------------------------------------
            await page.ev("document.getElementById('rtmVerify').click()")
            verdict = await settle(page, "(() => { const s = document.getElementById('rtmStatus')"
                                         ".textContent; return s.includes('agree') || s.includes('disagree'); })()",
                                   True, tries=120)
            check('Check Jacobian answers', verdict, True)
            check('and finds nothing wrong with the built-in model', await page.ev(
                "document.getElementById('rtmStatus').textContent"
                ".startsWith('The Jacobian agrees')"), True)
            check('drawing the pattern as it goes', await page.ev(
                "document.getElementById('rtmJacCanvas').width > 0"), True)
            # Not a solid block per cell, which is what it used to draw: count
            # the painted pixels and compare against the pattern's density.
            painted = await page.ev(PAINTED)
            # 8286 entries as one pixel each in a 620-pixel canvas is about 2 %.
            # A filled block per cell would be 100 %, which is what it drew
            # before, and is the thing this is here to catch.
            check(f'and drawing the pattern, not a filled square ({painted:.4f} of the canvas)',
                  isinstance(painted, float) and 0.002 < painted < 0.10, True)
            check('the caption counts the chemistry block', await page.ev(
                "document.getElementById('rtmJacNote').textContent"
                ".includes('363 of the 1296')"), True)

            # --- batch mode ---------------------------------------------------
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
            await asyncio.sleep(0.5)
            await page.ev("""(() => {
              const t = document.getElementById('rtmText');
              t.value = t.value.replace(/^MODE.*$/m, 'MODE = batch');
              t.dispatchEvent(new Event('input', { bubbles: true }));
            })()""")
            await settle(page, "document.getElementById('rtmFacts')"
                               ".textContent.startsWith('batch')", True, tries=40)
            check('switching to batch recompiles to one cell', await page.ev(
                "document.getElementById('rtmCell').options.length"), 1)
            # A batch is one cell, so the whole canvas is that one block: it has
            # to show the chemistry's own pattern or it shows nothing at all.
            await page.ev("document.querySelector('[data-tab=\"jacobian\"]').click()")
            await asyncio.sleep(0.6)
            solid = await page.ev(PAINTED)
            # 363 of 1296 cells of the block, each a 5-pixel dot in a 200-pixel
            # canvas: about 23 %. One solid square would be 100 %.
            check(f'and a batch draws its chemistry, not one solid square ({solid:.4f} painted)',
                  isinstance(solid, float) and 0.10 < solid < 0.40, True)
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('and a batch run finishes', isinstance(run, str) and run.startswith('Done'), True)
            await page.ev("document.querySelector('[data-tab=\"profile\"]').click()")
            await asyncio.sleep(1.0)
            check('the profile tab says a batch has no distance', await page.ev(
                "document.getElementById('rtmProfileEmpty').textContent.includes('batch')"), True)
            await page.ev("document.querySelector('[data-tab=\"gradient\"]').click()")
            await asyncio.sleep(1.0)
            check('and so does the gradient tab', await page.ev(
                "document.getElementById('rtmGradEmpty').textContent.includes('batch')"), True)
            check('with the chart itself put away', await page.ev(
                "document.getElementById('rtmChartGradient').hidden"), True)

            # --- a model that does not compile --------------------------------
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
            await set_text(page, '<SETTINGS>\nMODE = batch\n\n<SPECIES>\nA 1\n\n<REACTIONS>\nA => Q, k = 1\n')
            said = await settle(page, "document.getElementById('rtmStatus')"
                                      ".textContent.slice(0, 26)", 'The model does not compile')
            check('a species that is not declared is refused', said, 'The model does not compile')
            check('and the message names it', await page.ev(
                "document.getElementById('rtmStatus').textContent.includes('\"Q\"')"), True)

            # --- a small model of the reader's own, end to end -----------------
            await set_text(page, '<SETTINGS>\nMODE = batch\nTEND = 10\n\n<SPECIES>\nA 1.0\nB 0.0\n'
                                 '\n<REACTIONS>\nA => B, k = 0.5\n')
            await settle(page, "document.getElementById('rtmStatus')"
                               ".textContent.slice(0, 9)", 'Compiled:')
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('a model typed from scratch runs', isinstance(run, str) and run.startswith('Done'), True)
            # A -> B with k = 0.5 over 10 s leaves A at exp(-5).
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await page.ev("""(() => {
              const el = document.querySelector('#rtmSeries input[value="A"]');
              el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await asyncio.sleep(1.2)
            final = await page.ev(
                "(() => { const d = document.getElementById('rtmChartTime');"
                " const y = d.data[0].y; return y[y.length - 1]; })()")
            # check() takes (label, got, want); the third argument is not a
            # note, which is how this one managed to fail on a correct answer.
            ok = isinstance(final, (int, float)) and abs(final - 0.006737947) < 1e-5
            check(f'and the chart shows the right answer (A ended at {final}, exp(-5) '
                  f'is 0.006737947)', ok, True)

            # --- parameters, a mass coefficient and an equilibrium -------------
            await set_text(page, (
                '<SETTINGS>\nMODE = transport\nCELLS = 8\nLENGTH = 1E-4\n'
                'DIFFUSION = 1\nLEFT = neumann\nRIGHT = neumann\nTEND = 100\n'
                'EQUILIBRATE = 1\n\n'
                '<SPECIES>\nH+ 1E-3 D=9.3E-9\nOH- 1E-3 D=5.3E-9\nP 0 D=1E-9 R=2.5\n\n'
                '<PARAMETERS>\nDOSE all 0.64*exp(-x/3.0E-5)\n\n'
                '<EQUILIBRIUM>\n <=> H+ + OH-, logK = -14\n\n'
                '<REACTIONS>\n=> P, k = G*DOSE, G = 2.0\n'))
            said = await settle(page, "document.getElementById('rtmStatus')"
                                      ".textContent.slice(0, 9)", 'Compiled:', tries=40)
            check('a model with a parameter, an R= and an equilibrium compiles', said, 'Compiled:')
            facts = await page.ev("document.getElementById('rtmFacts').textContent")
            check('the panel reports the equilibrium and its conserved total',
                  isinstance(facts, str) and '1 equilibrium, 1 conserved total' in facts, True)
            check('and says the initial state was equilibrated',
                  isinstance(facts, str) and 'initial state equilibrated' in facts, True)
            check('and names the parameter',
                  isinstance(facts, str) and '1 parameter: DOSE' in facts, True)
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('a model using all three runs', isinstance(run, str) and run.startswith('Done'), True)
            await page.ev("document.getElementById('rtmVerify').click()")
            await settle(page, "(() => { const s = document.getElementById('rtmStatus')"
                               ".textContent; return s.includes('agree') || s.includes('disagree'); })()",
                         True, tries=120)
            check('and its Jacobian is right too', await page.ev(
                "document.getElementById('rtmStatus').textContent"
                ".startsWith('The Jacobian agrees')"), True)
            # EQUILIBRATE ran, so the H+ the chart starts from is 1E-7, not the
            # 1E-3 that was written down.
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await page.ev("""(() => {
              const el = document.querySelector('#rtmSeries input[value="H+"]');
              el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await asyncio.sleep(1.2)
            h0 = await page.ev(
                "(() => { const d = document.getElementById('rtmChartTime');"
                " return d.data[0].y[0]; })()")
            check(f'the chart starts from the speciated state (H+ at {h0}, not 1E-3)',
                  isinstance(h0, (int, float)) and abs(h0 - 1e-7) / 1e-7 < 1e-4, True)
            # P is retarded by 2.5 and fed a dose that dies away, so cell 0 has
            # much more of it than cell 7, and the first cell is at k*t/R.
            await page.ev("document.querySelector('[data-tab=\"profile\"]').click()")
            await asyncio.sleep(1.0)
            # The profile has its own species picker, separate from the ticks.
            await page.ev("""(() => {
              const s = document.getElementById('rtmProfileSpecies');
              s.value = 'P'; s.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await asyncio.sleep(1.2)
            check('the profile species picker offers every species', await page.ev(
                "document.querySelector('#rtmProfileSpecies optgroup').children.length"), 3)
            prof = await page.ev(
                "(() => { const d = document.getElementById('rtmChartProfile');"
                " return d.data[d.data.length - 1].y; })()")
            ok = isinstance(prof, list) and len(prof) == 8
            check('the profile falls away from the surface',
                  ok and all(prof[i] > prof[i + 1] for i in range(7)), True)
            # Neumann at both ends, so the column holds everything the source
            # put in: the mean has to be t/R times the mean of G*DOSE. This is
            # the parameter, the R= and the boundaries checked at once. It is
            # not the profile of the source — sqrt(D*t/R) is 2E-4 m against a
            # column of 1E-4, so by 100 s P is very nearly mixed.
            centres = [(i + 0.5) * 1.25e-5 for i in range(8)]
            want = 2.0 * 0.64 * 100 / 2.5 * sum(math.exp(-x / 3.0e-5) for x in centres) / 8
            got = sum(prof) / 8 if ok else None
            check(f'and holds G*DOSE*t/R in the mean ({got} against {want})',
                  ok and abs(got - want) / want < 2e-3, True)

            # --- a Julia port, and with no worker at all -----------------------
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
            await set_text(page, '<SETTINGS>\nMODE = batch\nTEND = 10\n\n<SPECIES>\nA 1.0\nB 0.0\n'
                                 '\n<REACTIONS>\nA => B, k = 0.5\n')
            # Not just "Compiled:" -- that is still true of the model before
            # this one, and clicking Run against a pending compile is how the
            # run's own status line used to get overwritten a second later.
            await settle(page, "document.getElementById('rtmStatus')"
                               ".textContent.startsWith('Compiled: 2 species')", True, tries=40)
            await page.ev("""(() => {
              const m = document.getElementById('rtmMethod');
              m.value = 'julia_fbdf'; m.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('a ported solver runs', isinstance(run, str) and run.startswith('Done'), True)
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await page.ev("""(() => {
              const el = document.querySelector('#rtmSeries input[value="A"]');
              el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await asyncio.sleep(1.2)
            fb = await page.ev(
                "(() => { const d = document.getElementById('rtmChartTime');"
                " const y = d.data[0].y; return y[y.length - 1]; })()")
            check(f'and gets the same answer as the built-in one ({fb} against exp(-5))',
                  isinstance(fb, (int, float)) and abs(fb - 0.006737947) < 1e-5, True)

            # QNDF has the BDF formulas switch, which makes it QBDF -- the same
            # switch the NDF has, where it makes the NDF the BDF. It is off.
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
            check('the BDF formulas switch is off', await page.ev(
                "document.getElementById('rtmBdf').checked"), False)
            await page.ev("""(() => {
              const m = document.getElementById('rtmMethod');
              m.value = 'julia_qndf'; m.dispatchEvent(new Event('change', { bubbles: true }));
              const b = document.getElementById('rtmBdf');
              b.checked = true; b.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            check('QNDF with the switch on is called QBDF', await page.ev(
                "document.getElementById('rtmSolverNote').textContent.split(' ')[0]"), 'QBDF')
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('and runs', isinstance(run, str) and run.startswith('Done'), True)
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await asyncio.sleep(1.2)
            qb = await page.ev(
                "(() => { const d = document.getElementById('rtmChartTime');"
                " const y = d.data[0].y; return y[y.length - 1]; })()")
            check(f'to the same answer ({qb} against exp(-5))',
                  isinstance(qb, (int, float)) and abs(qb - 0.006737947) < 1e-5, True)
            await page.ev("""(() => {
              const b = document.getElementById('rtmBdf');
              b.checked = false; b.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")

            # --- Kompartment's solvers: the menu, Auto, and the rows each reads -
            check('Kompartment’s solvers are on the menu', await page.ev(
                "[...document.getElementById('rtmMethod').options].map(o => o.value).join(',')"),
                'ndf,auto,ros23,dp45,julia_auto,julia_fbdf,julia_fbdf_krylov,julia_qndf,julia_kencarp4,'
                'julia_radau5,julia_rodas5p,julia_rosenbrock23,julia_trbdf2,julia_tsit5,julia_vern7')
            shown = ("[...document.querySelectorAll('#sec-solver [data-solver-opt]')]"
                     ".filter(el => !el.hidden).map(el => el.dataset.solverOpt).join(' ')")
            for method, rows in (
                    ('ndf', 'rtol atol bdf norm normControl maxOrder hmax h0 matrix jacobian belowTolRun '
                            'maxSteps stagnationTol autoAtol nonNegative'),
                    ('dp45', 'rtol atol hmax h0 maxSteps nonNegative'),
                    ('ros23', 'rtol atol hmax h0 jacobian maxSteps nonNegative'),
                    ('julia_tsit5', 'rtol atol norm hmax h0 belowTolRun maxSteps autoAtol nonNegative')):
                await page.ev("""(() => {
                  const m = document.getElementById('rtmMethod');
                  m.value = '%s'; m.dispatchEvent(new Event('change', { bubbles: true }));
                })()""" % method)
                check(f'{method} shows the settings it reads', await page.ev(shown), rows)
            # A -> B is not stiff: Auto stays explicit, and the status line says so.
            await page.ev("""(() => {
              const m = document.getElementById('rtmMethod');
              m.value = 'auto'; m.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('Auto runs', isinstance(run, str) and run.startswith('Done'), True)
            check('and says which method took the steps', isinstance(run, str)
                  and bool(re.search(r'\): (Tsit5|Vern7) \d+ steps?; 0 switches', run)), True)
            check('and that it formed no matrix', isinstance(run, str) and 'no iteration matrix' in run, True)
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await asyncio.sleep(1.2)
            au = await page.ev(
                "(() => { const d = document.getElementById('rtmChartTime');"
                " const y = d.data[0].y; return y[y.length - 1]; })()")
            check(f'to the same answer ({au} against exp(-5))',
                  isinstance(au, (int, float)) and abs(au - 0.006737947) < 1e-5, True)
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")

            # --- the progress bar, on a run long enough to see it --------------
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
            await page.ev("""(() => {
              const m = document.getElementById('rtmMethod');
              m.value = 'ndf'; m.dispatchEvent(new Event('change', { bubbles: true }));
              const t = document.getElementById('rtmText');
              t.value = RTM_DEFAULT_MODEL.replace(/^CELLS.*$/m, 'CELLS = 200');
              t.dispatchEvent(new Event('input', { bubbles: true }));
            })()""")
            await settle(page, "document.getElementById('rtmStatus')"
                               ".textContent.slice(0, 9)", 'Compiled:', tries=60)
            await page.ev("document.getElementById('rtmRun').click()")
            seen = False
            for _ in range(600):
                await asyncio.sleep(0.1)
                st = await page.ev("(() => ({ bar: !document.getElementById('rtmProgress').hidden,"
                                   " w: document.getElementById('rtmProgressFill').style.width,"
                                   " s: document.getElementById('rtmStatus').textContent }))()")
                if isinstance(st, dict) and st['bar']:
                    seen = True
                    break
                if isinstance(st, dict) and st['s'].startswith(('Done', 'The run failed')):
                    break
            check('the progress bar shows while a run is going', seen, True)
            told = False
            for _ in range(600):
                st = await page.ev("document.getElementById('rtmStatus').textContent")
                if isinstance(st, str) and 'steps' in st and st.startswith('Running'):
                    told = True
                    break
                if isinstance(st, str) and st.startswith(('Done', 'The run failed')):
                    break
                await asyncio.sleep(0.1)
            check('and the status says how far it has got while it runs', told, True)
            run = await wait_run(page)
            check('the long run finishes', isinstance(run, str) and run.startswith('Done'), True)
            check('and the bar is put away afterwards', await page.ev(
                "document.getElementById('rtmProgress').hidden"), True)

            # --- the Run button stays where it is ------------------------------
            # It sits at the bottom of the side panel, so anything that changes
            # the height of the status line below it used to move it: between
            # a short message and a long one it travelled 127 px, under the
            # pointer as it was being clicked.
            tops = []
            for text in ['Ready.', 'x ' * 220, 'Done in 0.62 s — 887 steps (25 rejected).']:
                await page.ev("document.getElementById('rtmStatus').textContent = %s"
                              % json.dumps(text))
                await asyncio.sleep(0.25)
                tops.append(await page.ev(
                    "Math.round(document.getElementById('rtmRun').getBoundingClientRect().top)"))
            await page.ev("document.getElementById('rtmProgress').hidden = false")
            await asyncio.sleep(0.25)
            tops.append(await page.ev(
                "Math.round(document.getElementById('rtmRun').getBoundingClientRect().top)"))
            await page.ev("document.getElementById('rtmProgress').hidden = true")
            check(f'the Run button does not move with the status below it ({tops})',
                  len(set(tops)) == 1, True)
            # With the long message back: it has to scroll inside a box of the
            # same height, not make the box taller.
            await page.ev("document.getElementById('rtmStatus').textContent = %s"
                          % json.dumps('x ' * 220))
            await asyncio.sleep(0.25)
            check('and the status scrolls instead of growing', await page.ev(
                "(() => { const el = document.getElementById('rtmStatus');"
                " return el.scrollHeight > el.clientHeight + 20; })()"), True)
            await page.ev("document.getElementById('rtmStatus').textContent = 'Ready.'")

            # --- the window does not scroll, and the text box fills the pane ---
            # The page is one screen: the panel and the work area scroll inside
            # themselves. The hidden checkbox in a species cell is absolutely
            # placed, and with no positioned ancestor of its own it takes
            # .content as its containing block, escapes every clip and adds the
            # cell's static position to the page's scrollable height.
            check('the window itself does not scroll', await page.ev(
                "(() => { const de = document.documentElement;"
                " return de.scrollHeight - de.clientHeight; })()"), 0)
            await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
            await asyncio.sleep(0.4)
            # The model text takes what the pane has left, so its foot lines up
            # with the foot of the status box in the panel beside it.
            check('the model text reaches the foot of the panel beside it', await page.ev(
                "(() => { const ta = document.getElementById('rtmText').getBoundingClientRect();"
                " const st = document.getElementById('rtmStatus').getBoundingClientRect();"
                " return Math.abs(ta.bottom - st.bottom) <= 2; })()"), True)

            # --- the syntax colouring -----------------------------------------
            # The coloured copy is a second rendering of the same characters
            # under a transparent textarea, so the one thing that must never
            # drift is the text itself: a span too many or an escape too few
            # and the caret sits over the wrong letter.
            check('the coloured copy is the text, character for character', await page.ev(
                "(() => { const ta = document.getElementById('rtmText');"
                " const pre = document.getElementById('rtmHighlight');"
                " return pre.textContent === ta.value + '\\n'; })()"), True)
            check('and lies exactly over the box being typed in', await page.ev(
                "(() => { const a = document.getElementById('rtmText').getBoundingClientRect();"
                " const b = document.getElementById('rtmHighlight').getBoundingClientRect();"
                " const ta = document.getElementById('rtmText');"
                " const pre = document.getElementById('rtmHighlight');"
                " return Math.round(a.top - b.top) === 0 && Math.round(a.left - b.left) === 0"
                " && ta.scrollWidth === pre.scrollWidth && ta.scrollHeight === pre.scrollHeight; })()"), True)
            # The box keeps the edge every input on the site has. The rule that
            # sizes the two boxes together paints a transparent border to do
            # it, and it is the more specific selector, so asking for the real
            # one by class alone left the model text in the pane with no edge.
            check('and the box still has its border, in both states', await page.ev(
                "(() => { const ta = document.getElementById('rtmText');"
                " const box = document.getElementById('rtmCodeBox');"
                " const edge = () => { const cs = getComputedStyle(ta);"
                "   return [cs.borderTopWidth, cs.borderTopStyle, cs.borderTopColor].join(' '); };"
                " const on = edge(); box.classList.remove('hl'); const off = edge();"
                " box.classList.add('hl');"
                " const clear = /transparent|rgba\\(0, 0, 0, 0\\)|^0px/;"
                " return on === off && !clear.test(on); })()"), True)
            check('a section heading, a comment and a setting are coloured', await page.ev(
                "(() => { const pre = document.getElementById('rtmHighlight');"
                " const kinds = new Set([...pre.querySelectorAll('span')].map((s) => s.className));"
                " return ['hl-sec', 'hl-com', 'hl-key', 'hl-num'].every((k) => kinds.has(k)); })()"), True)
            # Every example, not just the built-in one: the tokeniser has a
            # rule for charges and one for arrows, and either can eat a
            # character it should have passed through.
            check('every example survives the tokeniser unchanged', await page.ev(
                "(() => { const ta = document.getElementById('rtmText');"
                " const pre = document.getElementById('rtmHighlight'); const bad = [];"
                " const was = ta.value;"
                " for (const e of RTM_EXAMPLES) { ta.value = e.text;"
                "   ta.dispatchEvent(new Event('input', { bubbles: true }));"
                "   if (pre.textContent !== e.text + '\\n') bad.push(e.id); }"
                " ta.value = was; ta.dispatchEvent(new Event('input', { bubbles: true }));"
                " return bad; })()"), [])
            await page.ev("(() => { const c = document.getElementById('rtmSyntax');"
                          " c.checked = false; c.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            check('turning it off puts the copy away', await page.ev(
                "document.getElementById('rtmHighlight').textContent === ''"
                " && !document.getElementById('rtmCodeBox').classList.contains('hl')"), True)
            check('and the choice is remembered', await page.ev(
                "JSON.parse(localStorage.getItem('kvot-rtm-v1')).syntax"), False)
            await page.ev("(() => { const c = document.getElementById('rtmSyntax');"
                          " c.checked = true; c.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            check('and turning it back on paints it again', await page.ev(
                "document.getElementById('rtmHighlight').textContent.length > 100"), True)

            # --- the run as an HDF5 file --------------------------------------
            # The bytes are checked against the real library in test-hdf5.py;
            # what is checked here is that the page can build them at all --
            # the writer and the tree are loaded, and the result is a file of
            # a plausible size -- and that it says so where the reader looks.
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await asyncio.sleep(0.4)
            check('the page carries the HDF5 writer', await page.ev(
                "typeof RtmHDF5 === 'object' && typeof KvotHDF5 === 'object'"), True)
            await page.ev("[...document.querySelectorAll('[data-on-click=\"rtm:downloadHdf5\"]')][0].click()")
            # The file is some 60 MB: on a busy machine writing it takes longer
            # than any fixed wait, so the status line is watched for a minute.
            await settle(page, "/ written \\(/.test(document.getElementById('rtmStatus').textContent)",
                         True, tries=120, pause=0.5)
            written = await page.ev("document.getElementById('rtmStatus').textContent")
            check(f'writing the file says what it wrote ({written!r})',
                  bool(re.match(r'^rtm[\w.-]*\.h5 written \(\d+\.\d MB\)\.$', str(written))), True)
            check('and says it went well', await page.ev(
                "document.getElementById('rtmStatus').className"), 'rtm-status ok')

            # --- a file dropped on the page, and skbrtm's databases -----------
            # A DataTransfer built in the page goes down the same path a user's
            # drop does: dragenter shows the outline, drop reads the files.
            drop_js = """((files) => {
              const dt = new DataTransfer();
              for (const [name, text] of files) dt.items.add(new File([text], name, { type: 'text/plain' }));
              const target = document.querySelector('.rtm-main');
              target.dispatchEvent(new DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer: dt }));
              const shown = document.querySelector('.rtm').classList.contains('dropping');
              target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
              return shown;
            })(%s)"""
            model = ('<SETTINGS>\nMODE = transport\nCELLS = 8\nLENGTH = 1e-4\nGRID = powerlaw\n'
                     'LEFT = neumann\nRIGHT = neumann\nTEND = 100\n\n<SPECIES>\nFe(OH)3 0 D=1e-9\nX 1\n\n'
                     '<TABLE prof log>\n0 1\n1e-4 0.01\n\n<PARAMETERS>\nP all prof(x)\n\n'
                     '<INITIAL>\nX 1-7 0 fixed\n\n'
                     '<REACTIONS>\nX => Fe(OH)3, r = k*P*[X]^(2/3), k = 1.33*10**-2\n')
            shown = await page.ev(drop_js % json.dumps([['dropped.rtm', model]]))
            check('a file held over the page outlines it', shown, True)
            await settle(page, "document.getElementById('rtmText').value.includes('Fe(OH)3')", True, tries=20)
            check('dropping a model file loads its text', await page.ev(
                "document.getElementById('rtmText').value"), model)
            check('  the outline goes when it lands', await page.ev(
                "document.querySelector('.rtm').classList.contains('dropping')"), False)
            check('  and the Model tab is shown', await page.ev(
                "document.querySelector('.rtm-tabs button.active').dataset.tab"), 'model')
            await settle(page, "document.getElementById('rtmFacts').textContent.includes('power-law')", True, tries=40)
            facts = await page.ev("document.getElementById('rtmFacts').textContent")
            check('the panel describes the power-law grid', 'power-law grid, exponent 3' in facts, True)
            check('  names the table', '1 table: prof' in facts, True)
            check('  and says where X is held', 'X held in cells 1–7' in facts, True)
            check('the colouring passes a <TABLE>, Fe(OH)3 and (2/3) through unchanged', await page.ev(
                "document.getElementById('rtmHighlight').textContent === document.getElementById('rtmText').value + '\\n'"),
                True)
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            check('and the dropped model runs', isinstance(run, str) and run.startswith('Done'), True)

            skb = [
                ['run.py', "pm = parent_directory() + '/databases/'\np0 = pm + 'reaction.in'\n"
                           "p1 = pm + 'solutions.in'\npaths = [p0, p1]\n"
                           "solver = Solver(processes = (*db.reaction,), solutions = (*db.solution,),\n"
                           "                t_span = (0, 10, 'seconds'))\n"],
                ['reaction.in', 'REACTION;r\nSTOICHIOMETRY;EXPRESSION;ARGUMENTS\n'
                                'A = B;r = (kr/kh)*[A]*1e-15;kr = 1.33*10**12, kh = 1.3*10**-3\n'],
                ['solutions.in', 'SOLUTION;s\nunits;mol/L\nSPECIES;CONCENTRATION\nA;1\nB;0\n'],
                ['notes.md', '# not a database\n'],
            ]
            await page.ev(drop_js % json.dumps(skb))
            await settle(page, "document.getElementById('rtmExampleAbout').textContent.startsWith('Opened')",
                         True, tries=20)
            check("dropping skbrtm's files opens them as one model, the notes passed over", await page.ev(
                "document.getElementById('rtmExampleAbout').textContent.startsWith("
                "'Opened 3 skbrtm files as one model.')"), True)
            check('  with what skbrtm reads differently at the top of the text', await page.ev(
                "document.getElementById('rtmText').value.includes('1.000e-6 times')"), True)
            await settle(page, "document.getElementById('rtmStatus').textContent.startsWith('Compiled')",
                         True, tries=40)
            check('  and it compiles, with the script\'s time span', await page.ev(
                "document.getElementById('rtmFacts').textContent.includes('TEND 10.0 s')"), True)

            # --- the full window ----------------------------------------------
            # The page without the site's header, menu and footer, by the button
            # at the right end of the tab bar. There the kvot mark at the left of
            # the bar goes to the home page and the site's theme switch is beside
            # the button. The choice is kept, and the next visit is in the full
            # window from the page's head.
            FULL = """(() => { const shown = (s) => { const e = document.querySelector(s); return !!e && getComputedStyle(e).display !== 'none' && e.getClientRects().length > 0; };
              const c = document.querySelector('.content').getBoundingClientRect(), b = document.getElementById('rtmFull');
              return { on: document.documentElement.classList.contains('rtm-full'), site: [shown('body > header'), shown('body > footer'), shown('body > .nav-toggle')],
                top: Math.round(c.top), fills: Math.round(c.height) === innerHeight, mine: [shown('.rtm-homelink'), shown('.rtm-tabbar .theme-toggle')],
                pressed: b.getAttribute('aria-pressed'), stored: localStorage.getItem('kvot.rtm.full') }; })()"""
            THEME = ("[document.documentElement.dataset.theme, document.querySelector('.rtm-tabbar .theme-toggle').textContent,"
                     " localStorage.getItem('kvot-theme')]")
            # The page as the parser inserts the <script> of rtm-ui.js. The
            # scripts are classic, so by readyState 'interactive' rtm-ui.js has
            # run; but the parser lets the observer's callback run before it
            # runs a script, so here the page's own script has not run yet (the
            # button is not marked pressed), and only the head's can have put
            # the page in the full window.
            EARLY = """new MutationObserver((records, observer) => {
              if (window.__rtmEarly || !document.querySelector('script[src*="rtm-ui.js"]')) return;
              const h = document.querySelector('body > header'), b = document.getElementById('rtmFull');
              window.__rtmEarly = { full: document.documentElement.classList.contains('rtm-full'), header: h ? getComputedStyle(h).display : null,
                top: Math.round(document.querySelector('.content').getBoundingClientRect().top),
                icon: [...b.querySelectorAll('path')].map((x) => getComputedStyle(x).display), pressed: b.getAttribute('aria-pressed') };
              observer.disconnect();
            }).observe(document, { childList: true, subtree: true });"""
            r = await page.ev(FULL)
            check('the site\'s header, menu and footer around the page, the full-window button not pressed',
                  (r['on'], r['site'], r['top'], r['mine'], r['pressed']), (False, [True, True, True], 43, [False, False], 'false'))
            # The line under the tabs is the bar's background, which the open
            # tab covers by reaching the bar's foot in its pane's colour.
            check('the open tab stands on the line under the tabs, in the colour of its pane', await page.ev(
                "(() => { const a = document.querySelector('.rtm-tabs button.active'), bar = document.querySelector('.rtm-tabbar');"
                " return [Math.round(a.getBoundingClientRect().bottom) === Math.round(bar.getBoundingClientRect().bottom),"
                " getComputedStyle(a).backgroundColor === getComputedStyle(document.querySelector('.rtm-pane:not([hidden])')).backgroundColor]; })()"),
                [True, True])
            await press(page, '#rtmFull')
            r = await page.ev(FULL)
            check('the full-window button: no site header, menu or footer, the page fills the window, the choice kept',
                  (r['on'], r['site'], r['top'], r['fills'], r['pressed'], r['stored']), (True, [False, False, False], 0, True, 'true', '1'))
            check('  the kvot mark at the left of the tab bar goes to the home page, the theme switch beside the button',
                  (r['mine'], await page.ev("""(() => { const a = document.querySelector('.rtm-homelink'), img = a.querySelector('img');
                    const first = document.querySelector('.rtm-tabs button').getBoundingClientRect(), end = document.querySelector('.rtm-tabend'), bar = document.querySelector('.rtm-tabbar');
                    return [a.getAttribute('href'), img.complete && img.naturalWidth > 0, a.getBoundingClientRect().right <= first.left,
                      end.firstElementChild.classList.contains('theme-toggle') && end.lastElementChild.id === 'rtmFull',
                      Math.abs(end.getBoundingClientRect().right - bar.getBoundingClientRect().right) <= 1]; })()""")),
                  ([True, True], ['./index.html', True, True, True, True]))
            before = await page.ev(THEME)
            await press(page, '.rtm-tabbar .theme-toggle')
            mid = await page.ev(THEME)
            await press(page, '.rtm-tabbar .theme-toggle')
            end = await page.ev(THEME)
            if before[2] is None:
                await page.ev("localStorage.removeItem('kvot-theme')")
            flip = {'light': 'dark', 'dark': 'light'}
            check('  its theme switch changes the theme and keeps it, as the footer\'s does',
                  [mid[0] == flip.get(before[0]), mid[1] == ('☀️' if mid[0] == 'dark' else '🌙'), mid[2] == mid[0],
                   end[0] == before[0], end[2] == end[0]], [True] * 5)
            await press(page, '.rtm-tabs button[data-tab="gradient"]')
            check('  the tabs work as before, and the bar\'s two buttons are not among them', await page.ev(
                "[!document.querySelector('.rtm-pane[data-pane=\"gradient\"]').hidden,"
                " [...document.querySelectorAll('.rtm-tabbar button.active')].map((b) => b.dataset.tab),"
                " [...document.querySelector('[role=tablist]').children].map((b) => b.dataset.tab).join(' ')]"),
                [True, ['gradient'], 'time profile gradient composition diagram sweep fit uncertainty phreeqc model jacobian help'])
            await page.ev("document.querySelector('[data-info=\"set:rtol\"]').click()")
            check('  an (i) opens its panel from the top of the window to the bottom', await page.ev(
                "(() => { const p = document.getElementById('kvot-info-panel').getBoundingClientRect();"
                " return [Math.round(p.top), Math.round(p.bottom) === innerHeight]; })()"), [0, True])
            await page.ev("document.querySelector('#kvot-info-panel .info-panel-close').click()")
            # Page.navigate to the same address does not load the page again: a
            # real reload, told apart from the old page by a marker.
            early = await page.call('Page.addScriptToEvaluateOnNewDocument', {'source': EARLY}, session=page.sid)
            await page.ev('window.__rtmOld = true')
            await page.call('Page.reload', {'ignoreCache': True}, session=page.sid)
            await settle(page, "!window.__rtmOld && document.getElementById('rtmStatus').textContent.startsWith('Compiled')",
                         True, tries=120, pause=0.25)
            await page.call('Page.removeScriptToEvaluateOnNewDocument', {'identifier': early['result']['identifier']},
                            session=page.sid)
            check('the next visit is in the full window before the page\'s script runs: no header while it loads',
                  await page.ev('window.__rtmEarly || null'),
                  {'full': True, 'header': 'none', 'top': 0, 'icon': ['none', 'inline'], 'pressed': 'false'})
            r = await page.ev(FULL)
            check('  and once it has run, its button is pressed', (r['on'], r['pressed'], r['fills']), (True, 'true', True))
            # A phone: the mark, the switch and the button stay at the ends of
            # the bar while the tabs scroll between them.
            await page.call('Emulation.setDeviceMetricsOverride',
                            {'width': 390, 'height': 844, 'deviceScaleFactor': 2, 'mobile': True}, session=page.sid)
            await asyncio.sleep(0.6)
            BAR = """(() => { document.querySelector('.rtm-tabbar').scrollIntoView(); const bar = document.querySelector('.rtm-tabbar').getBoundingClientRect(),
              tabs = document.querySelector('.rtm-tabs'), t = tabs.getBoundingClientRect(), end = document.querySelector('.rtm-tabend').getBoundingClientRect(),
              mark = document.querySelector('.rtm-homelink'), help = document.querySelector('.rtm-tabs button[data-tab="help"]');
              const left = mark.getClientRects().length ? mark.getBoundingClientRect().right : bar.left;
              const scrolls = tabs.scrollWidth > tabs.clientWidth;
              tabs.scrollLeft = tabs.scrollWidth;
              const reached = help.getBoundingClientRect().right <= tabs.getBoundingClientRect().right;
              tabs.scrollLeft = 0;
              return [Math.round(bar.left), Math.round(bar.right) === innerWidth, left <= t.left + 0.5, end.left >= t.right - 0.5,
                Math.abs(end.right - bar.right) <= 1, scrolls, reached, document.documentElement.scrollWidth <= innerWidth + 1]; })()"""
            check('phone: the full window\'s bar keeps the mark at its left and the switch and button at its right, '
                  'the tabs scrolling between them to the last', await page.ev(BAR), [0, True, True, True, True, True, True, True])
            await press(page, '#rtmFull')
            r = await page.ev(FULL)
            check('the button again: the site\'s header, menu and footer back, the choice kept',
                  (r['on'], r['site'], r['pressed'], r['stored']), (False, [True, True, True], 'false', '0'))
            check('  and on a phone the tabs scroll to the last of them there too, with no sideways scroll of the page',
                  await page.ev(BAR), [0, True, True, True, True, True, True, True])
            await page.ev("localStorage.removeItem('kvot.rtm.full')")
            await page.call('Emulation.setDeviceMetricsOverride',
                            {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)

            check('no console errors throughout', page.errors[:3], [])
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})

        # --- and with no Worker at all, which is what file:// gives you ------
        tid2 = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        page.sid = (await page.call('Target.attachToTarget',
                                    {'targetId': tid2, 'flatten': True}))['result']['sessionId']
        await page.call('Runtime.enable', session=page.sid)
        await page.call('Page.enable', session=page.sid)
        await page.call('Network.setCacheDisabled', {'cacheDisabled': True}, session=page.sid)
        await page.call('Page.addScriptToEvaluateOnNewDocument',
                        {'source': "try{localStorage.removeItem('kvot-rtm-v1')}catch(e){}"
                                   "try{delete window.Worker}catch(e){window.Worker=undefined}"},
                        session=page.sid)
        await page.call('Page.navigate', {'url': URL}, session=page.sid)
        try:
            await asyncio.sleep(5)
            check('with no Worker the page still compiles', await page.ev(
                "document.getElementById('rtmStatus').textContent.slice(0, 9)"), 'Compiled:')
            await set_text(page, '<SETTINGS>\nMODE = batch\nTEND = 10\n\n<SPECIES>\nA 1.0\nB 0.0\n'
                                 '\n<REACTIONS>\nA => B, k = 0.5\n')
            await settle(page, "document.getElementById('rtmStatus')"
                               ".textContent.startsWith('Compiled: 2 species')", True, tries=40)
            await page.ev("""(() => {
              const m = document.getElementById('rtmMethod');
              m.value = 'julia_radau5'; m.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await page.ev("document.getElementById('rtmRun').click()")
            run = await wait_run(page)
            # This used to be refused outright: the ported solvers are on the
            # page as ordinary scripts and run there perfectly well.
            check(f'a ported solver runs with no worker ({str(run)[:70]})',
                  isinstance(run, str) and run.startswith('Done'), True)
            await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
            await page.ev("""(() => {
              const el = document.querySelector('#rtmSeries input[value="A"]');
              el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await asyncio.sleep(1.2)
            v = await page.ev("(() => { const y = document.getElementById('rtmChartTime')"
                              ".data[0].y; return y[y.length - 1]; })()")
            check(f'and gets the right answer ({v} against exp(-5))',
                  isinstance(v, (int, float)) and abs(v - 0.006737947) < 1e-5, True)
            check('no console errors with no worker', page.errors[:3], [])
        finally:
            await page.call('Target.closeTarget', {'targetId': tid2})

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
