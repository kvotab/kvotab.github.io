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
                ".map((i) => i.value).join(' ')]"), [36, 'pH I charge tot(C) alk(CO3)'])
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
                " + ':' + s.querySelectorAll('optgroup').length; })()"), '31:12')
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
                'Species|The water|Totals in the water')
            await grad("""const s = document.getElementById('rtmGradSpecies');
              s.value = 'H2O2'; s.dispatchEvent(new Event('change', { bubbles: true }));""")

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
                'species:true water:true saturation:true outputs:true activities:false')
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
            await page.ev("(() => { const s = document.getElementById('rtmSwShow'); s.value = 'time';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.4)
            check('  and against time, a curve per run, named for its value', await page.ev(
                "document.getElementById('rtmChartSw').data.map((t) => t.name).join(' / ')"),
                'kk = 0.1 / kk = 0.2 / kk = 0.3 / kk = 0.4')
            await set_text(page, before)
            await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40)

            # --- the examples that show a way of reading results open on it, once they have run ---
            before = await page.ev("document.getElementById('rtmText').value")

            async def example(ex, done):
                await page.ev("document.querySelector('[data-tab=\"model\"]').click()")
                await page.ev("(() => { const s = document.getElementById('rtmExample'); s.value = %s;"
                              " s.dispatchEvent(new Event('change', { bubbles: true })); })()" % json.dumps(ex))
                await settle(page, "document.getElementById('rtmStatus').textContent.slice(0, 9)", 'Compiled:', tries=40, pause=0.25)
                await page.ev("document.getElementById('rtmRun').click()")
                return await settle(page, done, True, tries=120, pause=0.5)

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
            # The box as the other examples find it.
            await page.ev("(() => { const b = document.getElementById('rtmCompLogT'); b.checked = true;"
                          " b.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            ok = await example('calcitefit', "/^Fitted in|could not/.test(document.getElementById('rtmStatus').textContent)")
            fitted = await page.ev("[document.querySelector('.rtm-tabs button.active').dataset.tab,"
                                   " [...document.querySelectorAll('#rtmFitResult tbody tr')].slice(0, 2)"
                                   ".map((tr) => [tr.children[0].textContent, Number(tr.children[2].textContent)])]")
            check(f'the calcite example fitted on the Fit tab: kc and its CO2 at the start from 1e-4 and 5e-4 to 5.1e-4 and '
                  f'1.0e-3 ({fitted})', isinstance(fitted, list) and fitted[0] == 'fit' and len(fitted[1]) == 2
                  and abs(fitted[1][0][1] / 5.1e-4 - 1) < 0.02 and abs(fitted[1][1][1] / 1.01e-3 - 1) < 0.02, True)
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
