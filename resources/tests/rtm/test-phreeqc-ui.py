#!/usr/bin/env python3
"""PHREEQC in rtm.html, in a real browser.

test-phreeqc.js proves the hand-off on PHREEQC compiled to WebAssembly, in
Node. This proves the page: that the panel on the Model tab writes a model
from a water through PHREEQC's worker, that the model compiles and lands on
PHREEQC, that a run is looked at through PHREEQC on its own tab and starts at
the water's own pH, that a database can be opened, that an earlier look says
it is of an earlier run, and that all of it works with no worker -- and from
the disk, where PHREEQC is loaded as scripts.

Start the server and the browser as for test-ui.py (ports in RTM_HTTP_PORT and
RTM_CDP_PORT, 8765 and 9222 unless set), then

    python3 resources/tests/rtm/test-phreeqc-ui.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import os
import re
import sys
import tempfile
import urllib.request

import websockets

HTTP = int(os.environ.get('RTM_HTTP_PORT', '8765'))
CDP = int(os.environ.get('RTM_CDP_PORT', '9222'))
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
URL = f'http://127.0.0.1:{HTTP}/rtm.html'
FILE_URL = 'file://' + os.path.join(ROOT, 'rtm.html')

# The browser's save dialog off, so that a file saved is downloaded and caught as the tests catch it.
CLEAN = ("try{localStorage.removeItem('kvot-rtm-v1');localStorage.removeItem('kvot-rtm-phreeqc-v1');"
         "localStorage.removeItem('kvot.rtm.full');localStorage.removeItem('kvot-rtm-aside-v1');"
         "localStorage.removeItem('kvot-rtm-opened-v1')}catch(e){}"
         "window.showSaveFilePicker=undefined;")

failures = []
checks = 0


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

    async def ev(self, expr):
        r = await self.call('Runtime.evaluate',
                            {'expression': expr, 'returnByValue': True, 'awaitPromise': True}, session=self.sid)
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:200]
        return res.get('result', {}).get('value')

    async def open(self, url, first_script):
        tid = (await self.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        self.sid = (await self.call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
        for m in ('Runtime.enable', 'Page.enable', 'Network.enable', 'DOM.enable'):
            await self.call(m, session=self.sid)
        # PHREEQC's worker fetches its scripts by itself, and a cache the page has
        # turned off still serves it yesterday's copy: the whole cache goes.
        await self.call('Network.clearBrowserCache', session=self.sid)
        await self.call('Network.setCacheDisabled', {'cacheDisabled': True}, session=self.sid)
        await self.call('Emulation.setDeviceMetricsOverride',
                        {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=self.sid)
        await self.call('Page.addScriptToEvaluateOnNewDocument', {'source': first_script}, session=self.sid)
        await self.call('Page.navigate', {'url': url}, session=self.sid)
        return tid

    async def set_files(self, selector, paths):
        doc = await self.call('DOM.getDocument', {}, session=self.sid)
        node = await self.call('DOM.querySelector', {'nodeId': doc['result']['root']['nodeId'],
                                                     'selector': selector}, session=self.sid)
        await self.call('DOM.setFileInputFiles', {'nodeId': node['result']['nodeId'], 'files': paths},
                        session=self.sid)


async def settle(page, expr, want, tries=240, pause=0.5):
    got = None
    for _ in range(tries):
        got = await page.ev(expr)
        if got == want:
            return got
        await asyncio.sleep(pause)
    return got


async def until(page, expr, tries=360, pause=0.5):
    """The first truthy value of expr, or the last value seen."""
    got = None
    for _ in range(tries):
        got = await page.ev(expr)
        if got and not (isinstance(got, str) and got.startswith('EXCEPTION')):
            return got
        await asyncio.sleep(pause)
    return got


STATUS = "document.getElementById('rtmStatus').textContent"
REPORT = "document.getElementById('rtmPqReport').textContent"
CLICK = "document.querySelector(%s).click()"


async def write_from_example(page):
    await page.ev(CLICK % json.dumps('[data-tab="model"]'))
    if await page.ev("document.getElementById('rtmPq').hidden"):
        await page.ev(CLICK % json.dumps('#rtmPqToggle'))
    await page.ev(CLICK % json.dumps('[data-on-click="rtm:pqExample"]'))
    await page.ev("document.getElementById('rtmPqReport').innerHTML = ''")
    await page.ev(CLICK % json.dumps('#rtmPqWrite'))
    return await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                             f"t.startsWith('PHREEQC could not') ? t : ''; }})()")


async def main():
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        page = Page(bws)
        asyncio.create_task(page.pump())
        await page.call('Browser.setDownloadBehavior', {'behavior': 'deny'})

        # ================= over http, with PHREEQC's worker =================
        tid = await page.open(URL, CLEAN)
        try:
            status = await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('the page compiles its built-in model', status, 'Compiled:')
            check('a PHREEQC tab beside the others, and the Batch tab after it', await page.ev(
                "[...document.querySelector('[role=tablist]').children].map((b) => b.dataset.tab).join(' ')"),
                'model time profile gradient composition diagram phreeqc batch sweep fit uncertainty jacobian help')
            check('PHREEQC is not fetched until it is used', await page.ev(
                "performance.getEntriesByType('resource').some((r) => /phreeqc/.test(r.name))"), False)

            # --- the panel ---
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))
            await page.ev(CLICK % json.dumps('#rtmPqToggle'))
            check('From PHREEQC… opens the panel', await page.ev(
                "[!document.getElementById('rtmPq').hidden, "
                "document.getElementById('rtmPqToggle').getAttribute('aria-expanded')]"), [True, 'true'])
            check('the database is phreeqc.dat, and others can be opened', await page.ev(
                "[...document.getElementById('rtmPqDb').options].map((o) => o.value).join(' ')"), 'builtin __open')
            audit = await page.ev("KvotInfo.audit()")
            check('every (i) of the panel and the tab has a topic, and its Help heading exists',
                  [audit.get('noTopic'), audit.get('brokenMore')] if isinstance(audit, dict) else audit, [[], []])
            empty = await page.ev("(() => { document.getElementById('rtmPqWater').value = '';"
                                  " document.getElementById('rtmPqWrite').click();"
                                  f" return {REPORT}; }})()")
            check('with no water it says what to give', isinstance(empty, str) and empty.startswith('Give PHREEQC a water'),
                  True)

            report = await write_from_example(page)
            check('the example water is written as a model through PHREEQC',
                  isinstance(report, str) and report.startswith('Written into the text below: 51 species and 41 '
                                                                'equilibria'), True)
            check('and rtm.html\'s own speciation, its own activity coefficients and all, lands on PHREEQC\'s',
                  isinstance(report, str) and 'from the database\'s constants and its own activity coefficients, '
                  'lands on PHREEQC\'s molalities to' in report, True)
            text = await page.ev("document.getElementById('rtmText').value")
            check('the text has its equilibria, held exactly through the run', isinstance(text, str)
                  and '<EQUILIBRIUM>' in text and 'EQUILIBRATE = always' in text and 'kf = ' not in text, True)
            check('and what PHREEQC works its conductance, density and viscosity out from: <CONDUCTANCE>, a solute\'s gfw, '
                  '-dw and -viscosity to a line, and <VOLUMES> for the density', isinstance(text, str)
                  and re.search(r'^<CONDUCTANCE>$', text, re.M) is not None and re.search(r'^<VOLUMES>$', text, re.M) is not None
                  and re.search(r'^Na\+\s+gfw 22\.9898  dw 1\.33e-9 .*  viscosity ', text, re.M) is not None
                  and isinstance(report, str) and 'in <CONDUCTANCE> and their molar volumes in <VOLUMES>' in report, True)
            check('in activities that follow the ionic strength, the water in the relations', isinstance(text, str)
                  and 'ACTIVITY = debye-huckel' in text and 'TEMPERATURE = 15' in text
                  and 'H2O <=> OH- + H+,' in text, True)
            status = await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('and it compiles', status, 'Compiled:')
            check('with the relations held, in activities: the model facts say so', await page.ev(
                "/All are held exactly at every step of the run: 52 species worked out from the totals in every cell\\..*"
                "The relations hold between activities, by Debye–Hückel at 15\\s°C, for 33 ions\\./"
                ".test(document.getElementById('rtmFacts').textContent)"), True)
            check('its couples tied to the electron, the water PHREEQC\'s next step: the report and the model facts say so',
                  isinstance(report, str)
                  and "Redox: 4 species tied to the electron e- by the database's reactions (HS-, H2, CH4 and Fe+3)" in report
                  and "The water is PHREEQC's next step, its valence states put on one pe: -2.95, where it was given -3." in report
                  and await page.ev("/4 relations tied to the electron e-, pe −?-?2\\.95 at the start/"
                                    ".test(document.getElementById('rtmFacts').textContent)"), True)
            await page.ev(CLICK % json.dumps('[data-tab="jacobian"]'))
            jac = await page.ev("document.getElementById('rtmJacNote').textContent")
            check('the Jacobian tab draws the species\' part and says the totals are not drawn',
                  True if isinstance(jac, str) and jac.startswith("the species' 52 × 52 of the 63 × 63 the solver works with")
                  and 'the 11 totals the held equilibria conserve are not drawn' in jac else jac, True)
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))

            # As fast pairs instead: the rate they relax at is asked for, and each gets its kf.
            check('the rate pairs relax at is asked only for pairs', await page.ev(
                "document.getElementById('rtmPqRelaxWrap').hidden"), True)
            await page.ev("(() => { const s = document.getElementById('rtmPqHold'); s.value = 'pairs';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            check('... and shown when they are chosen', await page.ev(
                "document.getElementById('rtmPqRelaxWrap').hidden"), False)
            first = await page.ev("document.getElementById('rtmText').value")
            await write_from_example(page)
            pairs = await page.ev("document.getElementById('rtmText').value")
            check('a second water written puts the first one\'s model aside, the line under the toolbar offering it back',
                  await page.ev("[!document.getElementById('rtmAsideNote').hidden,"
                                " JSON.parse(localStorage.getItem('kvot-rtm-aside-v1'))[0].text === %s]" % json.dumps(first)),
                  [True, True])
            check('as fast pairs, every relation has its kf and the start alone is speciated', isinstance(pairs, str)
                  and pairs.count('kf = ') == 30 and 'EQUILIBRATE = 1' in pairs, True)
            await page.ev("(() => { const s = document.getElementById('rtmPqHold'); s.value = 'exact';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            # Fixed at this water: conditional constants, and no water in the relations.
            await page.ev("(() => { const s = document.getElementById('rtmPqAct'); s.value = 'fixed';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await write_from_example(page)
            fixed = await page.ev("document.getElementById('rtmText').value")
            # The water's dissociation is the database's analytic expression, moved to the conditional constant here.
            kw_here = await page.ev("(() => { const m = RtmModel.compile(document.getElementById('rtmText').value);"
                                    " const eq = m.equilibria.find((e) => /^\\s*<=> OH- \\+ H\\+,/.test(e.text));"
                                    " return eq ? eq.lnK / Math.LN10 : null; })()")
            check('fixed at this water: conditional constants, the water left out of the relations',
                  isinstance(fixed, str) and 'ACTIVITY' not in fixed and ' <=> OH- + H+,' in fixed
                  and re.search(r'^ <=> OH- \+ H\+, +analytic = ', fixed, re.M) is not None
                  and isinstance(kw_here, (int, float)) and abs(kw_here + 14.1398953203) < 1e-9, True)
            await page.ev("(() => { const s = document.getElementById('rtmPqAct'); s.value = 'follow';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await write_from_example(page)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('PHREEQC ran in a worker of its own', await page.ev(
                "performance.getEntriesByType('resource').some((r) => /rtm-phreeqc-worker\\.js/.test(r.name))"), True)

            # A bad water is answered with PHREEQC's own words, and the text is left alone.
            before = await page.ev("document.getElementById('rtmText').value.length")
            await page.ev("document.getElementById('rtmPqWater').value = 'SOLUTION 1\\n  pH seven\\nEND\\n';"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click()")
            bad = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('PHREEQC could not') ? t : ''; }})()")
            check('a water PHREEQC refuses is answered in its words', isinstance(bad, str)
                  and 'Concentration data error for ph' in bad, True)
            check('and the model text is left as it was', await page.ev(
                "document.getElementById('rtmText').value.length"), before)

            # --- a run, then a look at it through PHREEQC ---
            await page.ev("""(() => {
              const t = document.getElementById('rtmText');
              t.value = t.value.replace('TEND = 1\\n', 'TEND = 1e5\\n') + '=> H+ + Cl-, k = 1.5e-8\\n';
              t.dispatchEvent(new Event('input', { bubbles: true }));
            })()""")
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            await page.ev(CLICK % json.dumps('#rtmRun'))
            done = await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            check('the model runs', done, 'Done')
            # The look takes up to 100 of the waters the run kept, and how many
            # it kept is the solver's business: read off the run's own status.
            kept = re.search(r'([\d,]+) points kept', await page.ev(STATUS) or '')
            waters = min(100, int(kept.group(1).replace(',', ''))) if kept else 100
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            check('the PHREEQC tab waits to be asked', await page.ev(
                "[!document.getElementById('rtmPqEmpty').hidden, document.getElementById('rtmChartPq').hidden]"),
                [True, True])
            await page.ev("document.getElementById('rtmPqLogT').checked = false;"
                          " document.getElementById('rtmPqLogT').dispatchEvent(new Event('change', { bubbles: true }))")
            await page.ev(CLICK % json.dumps('#rtmPqLook'))
            looked = await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                                       f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            check('the run is looked at through PHREEQC', isinstance(looked, str)
                  and looked.startswith(f'PHREEQC looked at {waters} waters'), True)
            chart = await page.ev("(() => { const d = document.getElementById('rtmChartPq').data || [];"
                                  " return d.length ? [d[0].name, d[0].x[0], d[0].y[0], d.length > 1,"
                                  " d.slice(1).some((t) => t.name === 'Calcite')] : null; })()")
            check('the chart starts at the water\'s own pH, 7.4, with the saturation indices below', chart and
                  [chart[0], chart[1], round(chart[2], 6), chart[3], chart[4]],
                  ['pH, −log a(H+)', 0, 7.4, True, True])
            summary = await page.ev("document.getElementById('rtmPqSummary').textContent")
            check('the summary says what was supersaturated and how far the constants moved',
                  isinstance(summary, str) and 'Supersaturated: ' in summary and 'Quartz, saturation index up to' in summary
                  and 'The model works its activity coefficients out as the run goes (ACTIVITY = debye-huckel). '
                      'PHREEQC\'s moved by up to ' in summary
                  and re.search(r"the model's own are within [0-9.e−-]+ of PHREEQC's in log K", summary) is not None, True)
            check('at the temperature the model was written at, read from the top of its text',
                  isinstance(summary, str) and 'at 15 °C, as the top of the model text has it' in summary
                  and 'Counted (51)' in summary, True)
            m_re = re.search(r'The electron e-, pe .+? over the waters\. Given each water at its pe, with ([A-Za-z, ]+) '
                             r'each one total, PHREEQC shares the valence states out to within ([0-9.e+−-]+)', summary or '')
            check('the electron is PHREEQC\'s pe, and PHREEQC shares each element out at it as the run has it',
                  m_re is not None and m_re.group(1) == 'C, Fe, S'
                  and float(m_re.group(2).replace('−', '-')) < 1e-6, True)

            # Filled in from a water PHREEQC refuses (the bad one is still in the panel):
            # said, and the look goes on without it.
            await page.ev("document.getElementById('rtmPqFill').checked = true;"
                          " document.getElementById('rtmPqFill').dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmStatus').textContent = '';"
                          " document.getElementById('rtmPqLook').click()")
            await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                              f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            summary = await page.ev("document.getElementById('rtmPqSummary').textContent")
            check('a water PHREEQC will not take is said, and the run is looked at without it',
                  isinstance(summary, str) and 'PHREEQC would not take the water' in summary
                  and 'Concentration data error' in summary, True)
            # The example water itself fills in nothing: the model carries every element of it.
            await page.ev(CLICK % json.dumps('[data-on-click="rtm:pqExample"]'))
            await page.ev("document.getElementById('rtmStatus').textContent = '';"
                          " document.getElementById('rtmPqLook').click()")
            await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                              f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            summary = await page.ev("document.getElementById('rtmPqSummary').textContent")
            check('filled in from the water it was written from, nothing is missing to fill',
                  isinstance(summary, str) and 'From the water' not in summary and 'the water’s' in summary
                  and 'would not take' not in summary, True)

            # The same run's last water listed on the Composition tab beside PHREEQC: given to PHREEQC as the PHREEQC tab gives
            # a run's waters; every species within 1e-5 in log molality (the hand-off's log K at 15 C) and 1e-9 in log gamma.
            await page.ev(CLICK % json.dumps('[data-tab="composition"]'))
            await page.ev("(() => { const v = document.getElementById('rtmCompView'); v.value = 'listing';"
                          " document.getElementById('rtmCompBeside').checked = true;"
                          " v.dispatchEvent(new Event('change', { bubbles: true })); })()")
            beside = await until(page, "(() => { const t = document.getElementById('rtmCompNote').textContent;"
                                       " return /beside PHREEQC \\(|could not take/.test(t) ? t : ''; })()")
            # The species named in brackets can have brackets of its own: Fe(OH)4-.
            m_b = re.search(r'beside PHREEQC \(phreeqc\.dat, [^)]+\): the species within ([0-9.e+-]+) in log molality \(.+?\) '
                            r'and ([0-9.e+-]+) in log gamma', beside or '')
            cols = await page.ev("(() => { const t = [...document.querySelectorAll('#rtmCompListing table')][2];"
                                 " return t ? t.querySelector('thead').textContent : ''; })()")
            check('the run\'s last water listed beside PHREEQC on the Composition tab: PHREEQC\'s molality and log gamma beside '
                  'each species, every one within 1e-5 in log molality, the hand-off\'s log K at 15 °C, and 1e-9 in log gamma',
                  [m_b is not None and float(m_b.group(1)) < 1e-5 and float(m_b.group(2)) < 1e-9,
                   'PHREEQC molality' in (cols or '') and 'Δ log molality' in (cols or '')], [True, True])
            if m_b is None:
                print('    the note:', beside)
            await page.ev("(() => { const v = document.getElementById('rtmCompView'); v.value = 'where';"
                          " document.getElementById('rtmCompBeside').checked = false;"
                          " v.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))

            # The CSV, caught on its way to the disk.
            await page.ev("""(() => {
              window.__csv = null;
              const make = URL.createObjectURL, click = HTMLAnchorElement.prototype.click;
              URL.createObjectURL = (b) => { window.__csv = b; return 'blob:caught'; };
              HTMLAnchorElement.prototype.click = function () {};
              document.querySelector('[data-on-click="rtm:pqCsv"]').click();
              URL.createObjectURL = make; HTMLAnchorElement.prototype.click = click;
            })()""")
            csv = await page.ev("window.__csv ? window.__csv.text() : null")
            lines = csv.strip().split('\n') if isinstance(csv, str) else []
            check('CSV: a row for each water, with the ionic strength and the saturation indices',
                  [len(lines), lines[0].split(',')[:5] if lines else None, 'SI Calcite' in (lines[0] if lines else '')],
                  [waters + 1, ['t (s)', 'cell', 'layer', 'ionic strength (mol/kgw)', 'pH (-log a H+)'], True])

            # --- a run after the look: the look stays, and says it is the earlier one ---
            await page.ev(CLICK % json.dumps('#rtmRun'))
            await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            check('after another run the look stays, saying it is of the run before', await page.ev(
                "[!document.getElementById('rtmPqStale').hidden, !document.getElementById('rtmChartPq').hidden,"
                " document.getElementById('rtmPqStale').textContent.startsWith('This is the run before')]"),
                [True, True, True])

            # --- a database of one's own ---
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.set_files('#rtmPqDbFile', [os.path.join(ROOT, 'vendors', 'phreeqc', 'phreeqc.dat')])
            opened = await until(page, f"(() => {{ const t = {STATUS}; return / is loaded: |cannot read/.test(t) ? t : ''; }})()")
            check('a database opened is read by PHREEQC at once', isinstance(opened, str)
                  and opened.startswith('phreeqc.dat is loaded:') and 'aqueous species' in opened, True)
            check('and is offered in both places', await page.ev(
                "['rtmPqDb', 'rtmPqViewDb'].map((id) => [...document.getElementById(id).options].length)"), [3, 3])
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.set_files('#rtmPqDbFile', [os.path.join(ROOT, 'rtm.html')])
            refused = await until(page, f"(() => {{ const t = {STATUS}; return / is loaded: |cannot read/.test(t) ? t : ''; }})()")
            check('a file that is no database is refused, with PHREEQC\'s reason', isinstance(refused, str)
                  and refused.startswith('PHREEQC cannot read rtm.html as a database'), True)

            # --- the phases kept at saturation ---
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))
            await page.ev("(() => { const s = document.getElementById('rtmPqDb'); s.value = 'builtin';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev("(() => { const s = document.getElementById('rtmPqHold'); s.value = 'start';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            check('the phases can be kept only with the equilibria held exactly', await page.ev(
                "document.getElementById('rtmPqMinerals').disabled"), True)
            await page.ev("(() => { const s = document.getElementById('rtmPqHold'); s.value = 'exact';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev("(() => { const c = document.getElementById('rtmPqMinerals'); c.checked = true;"
                          " c.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev(CLICK % json.dumps('[data-on-click="rtm:pqExample"]'))
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          " w.value = w.value.replace(/\\nEND\\s*$/, '\\nEQUILIBRIUM_PHASES 1\\n  Calcite 0 0.001\\nEND\\n');"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            kept = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                     f"t.startsWith('PHREEQC could not') ? t : ''; }})()")
            minerals_text = await page.ev("document.getElementById('rtmText').value")
            check('with them kept, calcite becomes a mineral of the model, and the report says so', isinstance(kept, str)
                  and 'Kept at saturation: Calcite (' in kept and isinstance(minerals_text, str)
                  and re.search(r'^Calcite +[0-9.e-]+ +mineral$', minerals_text, re.M) is not None, True)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('and the model facts count it', await page.ev(
                "/1 mineral at saturation while there is any/.test(document.getElementById('rtmFacts').textContent)"), True)

            # --- an exchanger in the water: carried, run, and looked at through PHREEQC ---
            await page.ev(CLICK % json.dumps('[data-on-click="rtm:pqExample"]'))
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          " w.value = w.value.replace(/\\nEND\\s*$/, '\\nEXCHANGE 1\\n  -equilibrate 1\\n  X 0.002\\nEND\\n');"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            onx = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                    f"t.startsWith('PHREEQC could not') ? t : ''; }})()")
            ex_text = await page.ev("document.getElementById('rtmText').value")
            check('an exchanger in the water is carried: its sites and the species PHREEQC put on them, and the report says so',
                  isinstance(onx, str) and 'On the exchanger X-: ' in onx and isinstance(ex_text, str)
                  and re.search(r'^X- +exchanger$', ex_text, re.M) is not None
                  and re.search(r'^CaX2 +[0-9.e-]+ +exchange +a=5 +b=0\.165$', ex_text, re.M) is not None, True)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('and the model facts count the species on it', await page.ev(
                "/species on the exchanger X-, by Gaines–Thomas\\./.test(document.getElementById('rtmFacts').textContent)"), True)
            await page.ev(CLICK % json.dumps('#rtmRun'))
            await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.ev(CLICK % json.dumps('#rtmPqLook'))
            await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                              f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            ex_summary = await page.ev("document.getElementById('rtmPqSummary').textContent")
            m_gap = re.search(r'The exchanger \(X\): loaded by PHREEQC from each water at the capacity the run has there, '
                              r'every species on it is within ([0-9.e+-]+)', ex_summary or '')
            check('looked at through PHREEQC, the run\'s exchanger is the one PHREEQC loads from its water',
                  m_gap is not None and float(m_gap.group(1)) < 1e-6, True)
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))

            # --- a TRANSPORT in the input: its column written, compiled and run ---
            column_input = ('SOLUTION 0\\n  units mmol/kgw\\n  pH 7 charge\\n  Na 1\\n  Cl 1\\n'
                            'SOLUTION 1-5\\n  units mmol/kgw\\n  pH 7 charge\\n  K 1\\n  Br 1\\nEND\\n'
                            'TRANSPORT\\n  -cells 5\\n  -shifts 5\\n  -time_step 3600\\n  -lengths 0.01\\n'
                            '  -dispersivities 0.002\\nEND\\n')
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          f" w.value = '{column_input}';"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            col = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                    f"t.startsWith('PHREEQC could not') || /TRANSPORT block, and/.test(t) ? t : ''; }})()")
            col_text = await page.ev("document.getElementById('rtmText').value")
            check('a TRANSPORT in the input becomes a column: its cells, the water crossing one a time step, SOLUTION 0 '
                  'flowing in, and the report says so', isinstance(col, str)
                  and "A column, the input's TRANSPORT: 5 cells, 0.05 m" in col and isinstance(col_text, str)
                  and re.search(r'^MODE = transport$', col_text, re.M) is not None
                  and re.search(r'^CELLS = 5$', col_text, re.M) is not None
                  and re.search(r'^LEFT = robin$', col_text, re.M) is not None
                  and re.search(r'^Na\+ .*left=0\.001', col_text, re.M) is not None, True)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            await page.ev(CLICK % json.dumps('#rtmRun'))
            ran = await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            check('  and the page runs it', ran, 'Done')

            # --- a column whose cells start apart: zones, the second in <INITIAL> ---
            zoned_input = column_input.replace(
                'SOLUTION 1-5\\n  units mmol/kgw\\n  pH 7 charge\\n  K 1\\n  Br 1\\n',
                'SOLUTION 1-2\\n  units mmol/kgw\\n  pH 7 charge\\n  K 1\\n  Br 1\\n'
                'SOLUTION 3-5\\n  units mmol/kgw\\n  pH 7 charge\\n  K 0.5\\n  Br 0.5\\n')
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          f" w.value = '{zoned_input}';"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            zoned = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                      f"t.startsWith('PHREEQC could not') || /TRANSPORT block, and/.test(t) ? t : ''; }})()")
            zoned_text = await page.ev("document.getElementById('rtmText').value")
            zones_ok = (isinstance(zoned, str) and 'in 2 zones — 1-2, 3-5 — the first as the water above' in zoned
                        and isinstance(zoned_text, str) and re.search(r'^<INITIAL>$', zoned_text, re.M) is not None
                        and re.search(r'^K\+ +2-4 +[0-9.e-]+$', zoned_text, re.M) is not None)
            check('a column whose cells start apart: two zones, the first as the water above and the second in <INITIAL>, '
                  'its cells counted from 0, and the report says so', zones_ok or zoned)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            await page.ev(CLICK % json.dumps('#rtmRun'))
            ran = await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            check('  and the page runs it', ran, 'Done')

            # --- a pH-stat and a bounded phase: EQUILIBRIUM_PHASES as PHREEQC reads a line ---
            stat_input = ('PHASES\\nFix_H+\\n  H+ = H+\\n  log_k 0\\nSOLUTION 1\\n  units mmol/kgw\\n  pH 7.5\\n  Na 1\\n'
                          '  Ca 2\\n  Cl 1 charge\\n  C(4) 3\\nEQUILIBRIUM_PHASES 1\\n  Fix_H+ -7.5 NaOH 0.01\\n'
                          '  Calcite 0 0.001 dissolve_only\\nEND\\n')
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          f" w.value = '{stat_input}';"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            stat = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                     f"t.startsWith('PHREEQC could not') ? t : ''; }})()")
            stat_text = await page.ev("document.getElementById('rtmText').value")
            stat_ok = (isinstance(stat, str) and 'NaOH added or taken away to hold Fix_H+ at SI -7.5' in stat
                       and ', dissolve_only)' in stat and isinstance(stat_text, str)
                       and re.search(r'^NaOH_Fix_H +[0-9.e-]+ +mineral$', stat_text, re.M) is not None
                       and re.search(r'^Calcite +[0-9.e-]+ +mineral +dissolve_only$', stat_text, re.M) is not None
                       and re.search(r'SI\(Fix_H\+\) = -7\.5', stat_text) is not None
                       and re.search(r'^<PHASES>$', stat_text, re.M) is not None)
            check('a pH-stat (Fix_H+ -7.5 NaOH) and calcite dissolve_only: the reagent a mineral held at SI(Fix_H+), the '
                  'phase written, the bound on the calcite, and the report says so', stat_ok or stat)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            await page.ev(CLICK % json.dumps('#rtmRun'))
            ran = await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            check('  and the page runs it', ran, 'Done')

            # --- stagnant cells: a rock matrix of one layer, the stagnant water in <INITIAL> aimed at it ---
            stag_input = column_input.replace(
                'END\\nTRANSPORT', 'SOLUTION 7-11\\n  units mmol/kgw\\n  pH 7 charge\\n  K 0.5\\n  Br 0.5\\nEND\\nTRANSPORT').replace(
                '  -dispersivities 0.002\\n', '  -dispersivities 0.002\\n  -stagnant 1 5e-6 0.25 0.15\\n')
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          f" w.value = '{stag_input}';"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            stagged = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                        f"t.startsWith('PHREEQC could not') || /TRANSPORT block, and/.test(t) ? t : ''; }})()")
            stag_text = await page.ev("document.getElementById('rtmText').value")
            stag_ok = (isinstance(stagged, str) and 'Stagnant water behind every cell' in stagged
                       and 'behind cells 1-5 in <INITIAL>' in stagged and isinstance(stag_text, str)
                       and re.search(r'^MATRIX_CELLS = 1$', stag_text, re.M) is not None
                       and re.search(r'^MATRIX_POROSITY = 0\.15$', stag_text, re.M) is not None
                       and re.search(r'^WETTED_SURFACE = 4$', stag_text, re.M) is not None
                       and re.search(r'^K\+ .*Dm=0\.0000025', stag_text, re.M) is not None
                       and re.search(r'^K\+ +0-4 +0\.0005\S* +matrix$', stag_text, re.M) is not None)
            check('stagnant cells (-stagnant 1 alpha theta_m theta_im): a rock matrix of one layer, every species\' Dm alpha/2, '
                  'the stagnant water in <INITIAL> aimed at the matrix, and the report says so', stag_ok or stagged)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            await page.ev(CLICK % json.dumps('#rtmRun'))
            ran = await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            check('  and the page runs it', ran, 'Done')

            # --- multicomponent diffusion: each species its own D, the ions coupled, each down its activity ---
            md_input = column_input.replace('  -dispersivities 0.002\\n', '  -dispersivities 0.002\\n  -multi_D true 1e-9 0.3 0 1\\n')
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          f" w.value = '{md_input}';"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            mdr = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                    f"t.startsWith('PHREEQC could not') || /TRANSPORT block, and/.test(t) ? t : ''; }})()")
            md_text = await page.ev("document.getElementById('rtmText').value")
            md_ok = (isinstance(mdr, str) and 'Multicomponent diffusion, -multi_D: each species at its Dw in the database' in mdr
                     and 'each down its activity, DIFFUSION_GRADIENT = activity' in mdr and isinstance(md_text, str)
                     and re.search(r'^DIFFUSION = nernst-planck$', md_text, re.M) is not None
                     and re.search(r'^DIFFUSION_GRADIENT = activity$', md_text, re.M) is not None
                     and re.search(r'^K\+ .*\bD=5\.88\d*e-10\b', md_text, re.M) is not None)
            check('multicomponent diffusion (-multi_D): each species its Dw times the porosity, the ions coupled and each down '
                  'its activity, and the report says so', md_ok or mdr)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            await page.ev(CLICK % json.dumps('#rtmRun'))
            ran = await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            check('  and the page runs it', ran, 'Done')

            # --- a surface in the water, with its double layer: carried, run, and looked at through PHREEQC ---
            await page.ev(CLICK % json.dumps('[data-on-click="rtm:pqExample"]'))
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          " w.value = w.value.replace(/\\nEND\\s*$/, '\\nSURFACE 1\\n  -equilibrate 1\\n"
                          "  Hfo_sOH 5e-6 600 0.09\\n  Hfo_wOH 2e-4\\nEND\\n');"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            onsf = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                     f"t.startsWith('PHREEQC could not') ? t : ''; }})()")
            sf_text = await page.ev("document.getElementById('rtmText').value")
            check('a surface in the water is carried with its double layer: its sites, the species PHREEQC put on them '
                  'and its potential, and the report says so',
                  isinstance(onsf, str) and 'On the surface, the sites Hfo_sOH, Hfo_wOH: ' in onsf
                  and 'with the diffuse double layer: Hfo_psi, the potential of Hfo' in onsf
                  and isinstance(sf_text, str)
                  and re.search(r'^Hfo_wOH +[0-9.e-]+ +surface$', sf_text, re.M) is not None
                  and re.search(r'^Hfo_psi +[0-9.e-]+ +potential +area=600 +grams=0\.09$', sf_text, re.M) is not None
                  and re.search(r'^Hfo_sOH \+ H\+ <=> Hfo_sOH2\+, +logK = 7\.29', sf_text, re.M) is not None, True)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('and the model facts count the species on its two kinds of site, and give the potential', await page.ev(
                "/species on 2 kinds of surface site \\(Hfo_sOH, Hfo_wOH\\).*the double layer's potential Hfo_psi at -?[0-9.]+ mV/"
                ".test(document.getElementById('rtmFacts').textContent)"), True)
            await page.ev(CLICK % json.dumps('#rtmRun'))
            await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.ev(CLICK % json.dumps('#rtmPqLook'))
            await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                              f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            sf_summary = await page.ev("document.getElementById('rtmPqSummary').textContent")
            m_sf = re.search(r'The surface \(sites Hfo_sOH, Hfo_wOH\): loaded by PHREEQC from each water with the sites '
                             r'the run has there, with its double layer, every species on it is within ([0-9.e+-]+).*'
                             r'and the potential within ([0-9.e+-]+) mV', sf_summary or '')
            check('looked at through PHREEQC, the run\'s surface and potential are the ones PHREEQC loads from its water',
                  m_sf is not None and float(m_sf.group(1)) < 1e-6 and float(m_sf.group(2)) < 1e-3, True)
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))

            # --- a SIT database: followed, run, and looked at through PHREEQC ---
            # phreeqc.dat with a SIT block of our own in front (PHREEQC reads a database to its first END).
            with open(os.path.join(ROOT, 'vendors', 'phreeqc', 'phreeqc.dat'), encoding='latin-1') as fh:
                pqdat = fh.read()
            with tempfile.TemporaryDirectory() as tmp:
                sit_path = os.path.join(tmp, 'sit-test.dat')
                with open(sit_path, 'w', encoding='latin-1') as fh:
                    fh.write('SIT\n-epsilon\n  Na+ Cl- 0.05\n  Ca+2 Cl- 0.1\n  Mg+2 Cl- 0.2\n  H+ Cl- 0.1\n'
                             '  Na+ HCO3- 0.0\n  Na+ CO3-2 -0.05\n  Na+ SO4-2 -0.1\n  Na+ OH- 0.05\n' + pqdat)
                await page.ev("document.getElementById('rtmStatus').textContent = ''")
                await page.set_files('#rtmPqDbFile', [sit_path])
                loaded = await until(page, f"(() => {{ const t = {STATUS}; return / is loaded: |cannot read/.test(t) ? t : ''; }})()")
            check('a SIT database opened is read by PHREEQC', isinstance(loaded, str)
                  and loaded.startswith('sit-test.dat is loaded:'), True)
            sit_report = await write_from_example(page)
            sit_text = await page.ev("document.getElementById('rtmText').value")
            check('with it, the water is written following SIT: ACTIVITY = sit and the database\'s coefficients in <SIT>, '
                  'and the report says so',
                  isinstance(sit_report, str) and "The activity coefficients are SIT's" in sit_report
                  and isinstance(sit_text, str) and re.search(r'^ACTIVITY = sit$', sit_text, re.M) is not None
                  and re.search(r'^Na\+ +Cl- +0\.05$', sit_text, re.M) is not None
                  and re.search(r'^Na\+ +[0-9.e-]+ +a=', sit_text, re.M) is None, True)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('and the model facts give SIT and its pairs', await page.ev(
                "/between activities, by SIT at [0-9.]+\\s°C, for [0-9]+ ions, with [0-9]+ pairs in <SIT>\\./"
                ".test(document.getElementById('rtmFacts').textContent)"), True)
            await page.ev(CLICK % json.dumps('#rtmRun'))
            await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.ev(CLICK % json.dumps('#rtmPqLook'))
            await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                              f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            sit_summary = await page.ev("document.getElementById('rtmPqSummary').textContent")
            m_sit = re.search(r'\(ACTIVITY = sit\)\. PHREEQC\'s .*?, and the model\'s own are within ([0-9.e+-]+) of '
                              r'PHREEQC\'s in log K', sit_summary or '')
            check('looked at through PHREEQC on the same database, the model\'s own SIT coefficients are PHREEQC\'s',
                  m_sit is not None and float(m_sit.group(1)) < 1e-6, True)
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))
            await page.ev("(() => { const s = document.getElementById('rtmPqDb'); s.value = 'builtin';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")

            # --- a Pitzer database: followed, run, and looked at through PHREEQC ---
            # phreeqc.dat with a PITZER block of our own in front, round numbers, K+ and Cl- for the MacInnes scaling.
            with tempfile.TemporaryDirectory() as tmp:
                pz_path = os.path.join(tmp, 'pitzer-test.dat')
                with open(pz_path, 'w', encoding='latin-1') as fh:
                    fh.write('PITZER\n-B0\n  Na+ Cl- 0.08 -700 -4 0.009 -3e-6\n  K+ Cl- 0.05\n  Ca+2 Cl- 0.3\n  Mg+2 Cl- 0.35\n'
                             '  Na+ SO4-2 0.02\n  Ca+2 SO4-2 0.2\n-B1\n  Na+ Cl- 0.27\n  K+ Cl- 0.21\n  Ca+2 Cl- 1.6\n'
                             '  Mg+2 Cl- 1.7\n  Na+ SO4-2 1.1\n  Ca+2 SO4-2 3.2\n-C0\n  Na+ Cl- 0.001\n  K+ Cl- -0.0008\n'
                             '-THETA\n  Ca+2 Na+ 0.07\n  Cl- SO4-2 0.03\n-PSI\n  Ca+2 Na+ Cl- -0.007\n' + pqdat)
                await page.ev("document.getElementById('rtmStatus').textContent = ''")
                await page.set_files('#rtmPqDbFile', [pz_path])
                loaded = await until(page, f"(() => {{ const t = {STATUS}; return / is loaded: |cannot read/.test(t) ? t : ''; }})()")
            check('a Pitzer database opened is read by PHREEQC', isinstance(loaded, str)
                  and loaded.startswith('pitzer-test.dat is loaded:'), True)
            pz_report = await write_from_example(page)
            pz_text = await page.ev("document.getElementById('rtmText').value")
            check('with it, the water is written following Pitzer: ACTIVITY = pitzer, the database\'s parameters in <PITZER> '
                  'with their terms in the temperature, the electron held where PHREEQC\'s Pitzer model holds it, and the '
                  'report says so',
                  isinstance(pz_report, str) and "The activity coefficients are Pitzer's" in pz_report
                  and isinstance(pz_text, str) and re.search(r'^ACTIVITY = pitzer$', pz_text, re.M) is not None
                  and re.search(r'^B0 +Na\+ +Cl- +0\.08 +-700 +-4 +0\.009 +-0\.000003$', pz_text, re.M) is not None
                  and re.search(r'^e- +electron +pe=-?[0-9.]+ +fixed$', pz_text, re.M) is not None
                  and re.search(r'^Na\+ +[0-9.e-]+ +a=', pz_text, re.M) is None, True)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('and the model facts give Pitzer, its parameters and the MacInnes scaling', await page.ev(
                "/between activities, by Pitzer at [0-9.]+\\s°C, for [0-9]+ ions, with [0-9]+ parameters in <PITZER>, MacInnes scaled\\./"
                ".test(document.getElementById('rtmFacts').textContent)"), True)
            await page.ev(CLICK % json.dumps('#rtmRun'))
            await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.ev(CLICK % json.dumps('#rtmPqLook'))
            await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                              f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            pz_summary = await page.ev("document.getElementById('rtmPqSummary').textContent")
            m_pz = re.search(r'\(ACTIVITY = pitzer\)\. PHREEQC\'s .*?, and the model\'s own are within ([0-9.e+-]+) of '
                             r'PHREEQC\'s in log K', pz_summary or '')
            check('looked at through PHREEQC on the same database, the model\'s own Pitzer coefficients are PHREEQC\'s',
                  m_pz is not None and float(m_pz.group(1)) < 1e-6, True)
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))
            await page.ev("(() => { const s = document.getElementById('rtmPqDb'); s.value = 'builtin';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")

            # --- an LLNL database: followed, run, and looked at through PHREEQC ---
            # The tests' own (test-phreeqc.js, OWN_LLNL): LLNL's tables, -llnl_gamma and -co2_llnl_gamma, and a water of
            # what it knows.
            with open(os.path.join(ROOT, 'resources', 'tests', 'rtm', 'test-phreeqc.js'), encoding='utf-8') as fh:
                own_llnl = re.search(r'const OWN_LLNL = `(.*?)`;', fh.read(), re.S).group(1)
            with tempfile.TemporaryDirectory() as tmp:
                ll_path = os.path.join(tmp, 'llnl-test.dat')
                with open(ll_path, 'w', encoding='latin-1') as fh:
                    fh.write(own_llnl)
                await page.ev("document.getElementById('rtmStatus').textContent = ''")
                await page.set_files('#rtmPqDbFile', [ll_path])
                loaded = await until(page, f"(() => {{ const t = {STATUS}; return / is loaded: |cannot read/.test(t) ? t : ''; }})()")
            check('an LLNL database opened is read by PHREEQC', isinstance(loaded, str)
                  and loaded.startswith('llnl-test.dat is loaded:'), True)
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          " w.value = 'SOLUTION 1\\n  temp 40\\n  units mol/kgw\\n  pH 7.5\\n  Na 1\\n  Cl 1 charge\\n"
                          "  Ca 0.02\\n  C(4) 0.01\\nEND\\n';"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            ll_report = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                          f"t.startsWith('PHREEQC could not') ? t : ''; }})()")
            ll_text = await page.ev("document.getElementById('rtmText').value")
            check('with it, the water is written following LLNL\'s model: ACTIVITY = llnl, -llnl_gamma as a=, drummond and the '
                  'tables in <LLNL>, and the report says so',
                  isinstance(ll_report, str) and 'The activity coefficients are LLNL\u2019s' in ll_report
                  and isinstance(ll_text, str) and re.search(r'^ACTIVITY = llnl$', ll_text, re.M) is not None
                  and re.search(r'^Na\+ +[0-9.e-]+ +a=4$', ll_text, re.M) is not None
                  and re.search(r'^CO2 +[0-9.e-]+ +drummond$', ll_text, re.M) is not None
                  and re.search(r'^TEMPERATURES +0\.01 +25 +60 +100 +150$', ll_text, re.M) is not None, True)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('and the model facts give LLNL\'s B-dot', await page.ev(
                "/between activities, by LLNL\u2019s B-dot at [0-9.]+\\s°C/.test(document.getElementById('rtmFacts').textContent)"), True)
            await page.ev(CLICK % json.dumps('#rtmRun'))
            await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.ev(CLICK % json.dumps('#rtmPqLook'))
            await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                              f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            ll_summary = await page.ev("document.getElementById('rtmPqSummary').textContent")
            m_ll = re.search(r'\(ACTIVITY = llnl\)\. PHREEQC\'s .*?, and the model\'s own are within ([0-9.e+-]+) of '
                             r'PHREEQC\'s in log K', ll_summary or '')
            check('looked at through PHREEQC on the same database, the model\'s own LLNL coefficients are PHREEQC\'s',
                  m_ll is not None and float(m_ll.group(1)) < 1e-6, True)
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))
            await page.ev("(() => { const s = document.getElementById('rtmPqDb'); s.value = 'builtin';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")

            # --- the example water at 300 atm: PRESSURE and <VOLUMES> written, run, and looked at through PHREEQC ---
            await page.ev(CLICK % json.dumps('[data-on-click="rtm:pqExample"]'))
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          " w.value = w.value.replace(/^(SOLUTION[^\\n]*)$/m, '$1\\n  pressure 300');"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            onp = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                    f"t.startsWith('PHREEQC could not') ? t : ''; }})()")
            p_text = await page.ev("document.getElementById('rtmText').value")
            check('a water at 300 atm is written with its pressure and the database\'s molar volumes, the log K at one '
                  'atmosphere, and the report says so',
                  isinstance(onp, str) and 'The water is at 300 atm, written as PRESSURE: PHREEQC corrects each log K' in onp
                  and isinstance(p_text, str) and re.search(r'^PRESSURE = 300$', p_text, re.M) is not None
                  and re.search(r'^<VOLUMES>$', p_text, re.M) is not None
                  and re.search(r'^Na\+ +2\.28 +-4\.38 +-4\.1 +-0\.586 +0\.09 +4 +0\.3 +52 +-0\.00333 +0\.566$', p_text, re.M)
                  is not None, True)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('and the model facts give the log K at the pressure', await page.ev(
                "/log K at the pressure from [0-9]+ molar volumes in <VOLUMES>/"
                ".test(document.getElementById('rtmFacts').textContent)"), True)
            await page.ev(CLICK % json.dumps('#rtmRun'))
            await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.ev(CLICK % json.dumps('#rtmPqLook'))
            await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                              f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            p_summary = await page.ev("document.getElementById('rtmPqSummary').textContent")
            m_p = re.search(r'\(ACTIVITY = debye-huckel\)\. PHREEQC\'s .*?, and the model\'s own are within ([0-9.e+-]+) of '
                            r'PHREEQC\'s in log K', p_summary or '')
            check('looked at through PHREEQC at the model\'s pressure, the model\'s own coefficients and log K at 300 atm are '
                  'PHREEQC\'s', m_p is not None and float(m_p.group(1)) < 1e-6, True)
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))

            # --- a CD-MUSIC surface: written by CD-MUSIC, run, and looked at through PHREEQC ---
            # phreeqc.dat with the tests' own goethite-like block in front (test-phreeqc.js, OWN_CD).
            cd_block = ('SURFACE_MASTER_SPECIES\n  Goe_uni  Goe_uniOH-0.5\n  Goe_tri  Goe_triO-0.5\nSURFACE_SPECIES\n'
                        '  Goe_uniOH-0.5 = Goe_uniOH-0.5\n    log_k 0\n'
                        '  Goe_uniOH-0.5 + H+ = Goe_uniOH2+0.5\n    log_k 9.2\n    -cd_music 1 0 0 0 0\n'
                        '  Goe_uniOH-0.5 + Na+ = Goe_uniOHNa+0.5\n    log_k -0.6\n    -cd_music 0 1 0 0 0\n'
                        '  Goe_triO-0.5 = Goe_triO-0.5\n    log_k 0\n'
                        '  Goe_triO-0.5 + H+ = Goe_triOH+0.5\n    log_k 9.2\n    -cd_music 1 0 0 0 0\n')
            with tempfile.TemporaryDirectory() as tmp:
                cd_path = os.path.join(tmp, 'cd-test.dat')
                with open(cd_path, 'w', encoding='latin-1') as fh:
                    fh.write(cd_block + pqdat)
                await page.ev("document.getElementById('rtmStatus').textContent = ''")
                await page.set_files('#rtmPqDbFile', [cd_path])
                loaded = await until(page, f"(() => {{ const t = {STATUS}; return / is loaded: |cannot read/.test(t) ? t : ''; }})()")
            check('a database with a CD-MUSIC surface opened is read by PHREEQC', isinstance(loaded, str)
                  and loaded.startswith('cd-test.dat is loaded:'), True)
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          " w.value = 'SOLUTION 1\\n  pH 7\\n  units mol/kgw\\n  Na 0.01\\n  Cl 0.01 charge\\n"
                          "SURFACE 1\\n  -cd_music\\n  Goe_uniOH 3.45e-3 98 1\\n  -capacitances 0.9 0.74\\n"
                          "  Goe_triO 2.7e-3\\n  -equilibrate 1\\nEND\\n';"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            oncd = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                     f"t.startsWith('PHREEQC could not') ? t : ''; }})()")
            cd_text = await page.ev("document.getElementById('rtmText').value")
            check('a CD-MUSIC surface in the water is written by CD-MUSIC: its three potentials, the first with its '
                  'capacitances, each species\' planes and half charges, and the report says so',
                  isinstance(oncd, str) and 'by CD-MUSIC: the planes 0, 1 and 2 of Goe' in oncd and isinstance(cd_text, str)
                  and re.search(r'^Goe_psi +[0-9.e-]+ +potential +area=98 +grams=1 +c0=0\.9 +c1=0\.74$', cd_text, re.M) is not None
                  and re.search(r'^Goe_psib +[0-9.e-]+ +potential$', cd_text, re.M) is not None
                  and re.search(r'^Goe_uniOHNa_0_5 +[0-9.e-]+ +surface +z=0\.5 +dz1=1$', cd_text, re.M) is not None, True)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('and the model facts give CD-MUSIC\'s planes', await page.ev(
                "/CD-MUSIC's plane 0 potential Goe_psi.*CD-MUSIC's plane 2 potential Goe_psid/"
                ".test(document.getElementById('rtmFacts').textContent)"), True)
            await page.ev(CLICK % json.dumps('#rtmRun'))
            await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.ev(CLICK % json.dumps('#rtmPqLook'))
            await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                              f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            cd_summary = await page.ev("document.getElementById('rtmPqSummary').textContent")
            m_cd = re.search(r'loaded by PHREEQC from each water with the sites the run has there, by CD-MUSIC, every species '
                             r'on it is within ([0-9.e+-]+).*and every potential within ([0-9.e+-]+) mV', cd_summary or '')
            check('looked at through PHREEQC, the run\'s CD-MUSIC surface and its three potentials are the ones PHREEQC loads '
                  'from its water', m_cd is not None and float(m_cd.group(1)) < 1e-6 and float(m_cd.group(2)) < 1e-3, True)
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))
            await page.ev("(() => { const s = document.getElementById('rtmPqDb'); s.value = 'builtin';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")

            # --- a gas phase in the water: carried as real gases, run, and looked at through PHREEQC ---
            await page.ev(CLICK % json.dumps('[data-on-click="rtm:pqExample"]'))
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          " w.value = w.value.replace(/\\nEND\\s*$/, '\\nGAS_PHASE 1\\n  -fixed_volume\\n  -volume 0.5\\n"
                          "  CO2(g) 0\\nEND\\n');"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            ongas = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                      f"t.startsWith('PHREEQC could not') ? t : ''; }})()")
            gas_text = await page.ev("document.getElementById('rtmText').value")
            check('a gas phase in the water is carried: a real gas in a fixed volume, the water at its pressure, and the '
                  'report says so',
                  isinstance(ongas, str) and 'A gas phase in a fixed volume of ' in ongas and isinstance(gas_text, str)
                  and re.search(r'^GAS_VOLUME = 0\.(?:5|49999)[0-9]*$', gas_text, re.M) is not None
                  and re.search(r'^PRESSURE = [0-9.e-]+$', gas_text, re.M) is not None
                  and re.search(r'^CO2\(g\) +[0-9.e-]+ +gas +Tc=304\.2 +Pc=72\.86 +omega=0\.225$', gas_text, re.M) is not None,
                  True)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('and the model facts give the gas phase', await page.ev(
                "/CO2\\(g\\) in a gas phase of 0\\.5 L to each kg of water/.test(document.getElementById('rtmFacts').textContent)"),
                True)
            await page.ev(CLICK % json.dumps('#rtmRun'))
            await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.ev(CLICK % json.dumps('#rtmPqLook'))
            await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                              f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            gas_summary = await page.ev("document.getElementById('rtmPqSummary').textContent")
            m_gas = re.search(r"The gas phase \(CO2\(g\), in 0\.5 L per kgw\): each gas's partial pressure in the run is "
                              r"within ([0-9.e+-]+) in log", gas_summary or '')
            check('looked at through PHREEQC, the run\'s gas is at the pressure PHREEQC finds the water holds it at',
                  m_gas is not None and float(m_gas.group(1)) < 1e-4, True)
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))

            # --- a solid solution in the water: aragonite and strontianite, run, and looked at through PHREEQC ---
            await page.ev(CLICK % json.dumps('[data-on-click="rtm:pqExample"]'))
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          " w.value = w.value.replace(/^( *Mg +5)$/m, '$1\\n  Sr     0.5').replace(/\\nEND\\s*$/, '\\nSOLID_SOLUTIONS 1\\n"
                          "  CaSrCO3\\n  -comp1 Aragonite 0\\n  -comp2 Strontianite 0\\n  -Gugg_nondimensional 3.43 -1.82\\nEND\\n');"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            onss = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                     f"t.startsWith('PHREEQC could not') ? t : ''; }})()")
            ss_text = await page.ev("document.getElementById('rtmText').value")
            check('a solid solution in the water is carried: aragonite and strontianite as minerals, Guggenheim\'s a0 and a1, '
                  'and the report says so',
                  isinstance(onss, str) and 'A solid solution, CaSrCO3: Aragonite (' in onss
                  and 'a0 3.43 and a1 -1.82 at 25 °C' in onss and isinstance(ss_text, str)
                  and re.search(r'^CaSrCO3 +Aragonite +Strontianite +a0=3\.43 +a1=-1\.82$', ss_text, re.M) is not None
                  and re.search(r'^Aragonite +[0-9.e-]+ +mineral$', ss_text, re.M) is not None, True)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('and the model facts give the solid solution and its miscibility gap', await page.ev(
                "/The solid solution CaSrCO3 \\(Aragonite, Strontianite\\), a0 3\\.43 and a1 -1\\.82 at 25 °C, a miscibility gap, "
                "there while the water is saturated in it/.test(document.getElementById('rtmFacts').textContent)"), True)
            await page.ev(CLICK % json.dumps('#rtmRun'))
            await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.ev(CLICK % json.dumps('#rtmPqLook'))
            await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                              f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            ss_summary = await page.ev("document.getElementById('rtmPqSummary').textContent")
            m_ss = re.search(r"The solid solution CaSrCO3 \(Aragonite, Strontianite\): each member's saturation index PHREEQC "
                             r"finds in the water is log10 of its activity in the run's solid, its mole fraction times lambda, "
                             r"to within ([0-9.e+-]+)", ss_summary or '')
            check('looked at through PHREEQC, each member\'s activity in the run\'s solid is the one PHREEQC finds the water '
                  'holds the pure member at', m_ss is not None and float(m_ss.group(1)) < 1e-6, True)
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))

            # --- a kinetic reactant: calcite at phreeqc.dat's rate, written as a rate law by the page's worker, and run ---
            await page.ev(CLICK % json.dumps('[data-on-click="rtm:pqExample"]'))
            await page.ev("(() => { const w = document.getElementById('rtmPqWater');"
                          " w.value = w.value.replace(/\\nEND\\s*$/, '\\nKINETICS 1\\nCalcite\\n -m 1e-3\\n -parms 50 0.6\\n"
                          " -steps 86400 in 4\\nEND\\n');"
                          " w.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmPqReport').innerHTML = '';"
                          " document.getElementById('rtmPqWrite').click(); })()")
            onkin = await until(page, f"(() => {{ const t = {REPORT}; return t.startsWith('Written') || "
                                      f"t.startsWith('PHREEQC could not') ? t : ''; }})()")
            kin_text = await page.ev("document.getElementById('rtmText').value")
            check('a kinetic reactant in the water is carried: calcite a mineral at its -m, its dissolution in <REACTIONS> at '
                  'the rate its RATES program comes to, the program above it, the run as long as PHREEQC\'s steps, and the '
                  'report says so',
                  isinstance(onkin, str) and 'Kinetics: Calcite (0.001 mol/kgw)' in onkin and isinstance(kin_text, str)
                  and re.search(r'^Calcite => CO3-2 \+ Ca\+2, r = ', kin_text, re.M) is not None
                  and re.search(r'^#\s+130 moles = rate \* 0\.001 \* TIME', kin_text, re.M) is not None
                  and re.search(r'^TEND = 86400$', kin_text, re.M) is not None
                  and re.search(r'^Calcite +0\.001 +mineral$', kin_text, re.M) is not None, True)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            await page.ev(CLICK % json.dumps('#rtmRun'))
            kin_done = await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            check('and it runs', kin_done, 'Done')

            # --- inverse models: PHREEQC's INVERSE_MODELING between the water as it starts and as the run ends ---
            # What the run did to its calcite, off the time chart: PHREEQC's model must give it back.
            await page.ev(CLICK % json.dumps('[data-tab="time"]'))
            await page.ev("""(() => {
              const el = document.querySelector('#rtmSeries input[value="Calcite"]');
              el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            calcite = await until(page, "(() => { const t = (document.getElementById('rtmChartTime').data || [])"
                                        ".find((d) => d.name === 'Calcite'); return t ? [t.y[0], t.y[t.y.length - 1]] : ''; })()")
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            await asyncio.sleep(0.3)
            inv_set = await page.ev("[document.getElementById('rtmPqInvFrom').value, document.getElementById('rtmPqInvFromAt').value,"
                                    " document.getElementById('rtmPqInvTo').value, document.getElementById('rtmPqInvToAt').value,"
                                    " document.getElementById('rtmPqInvFromAtWrap').hidden]")
            check('inverse models offer a batch\'s one water, from as it starts to as the run ends', inv_set,
                  ['0', 'start', '0', 'end', False])

            async def inverse(phases, u):
                await page.ev("(() => { const p = document.getElementById('rtmPqInvPhases'); p.value = %s;"
                              " p.dispatchEvent(new Event('change', { bubbles: true }));"
                              " const u = document.getElementById('rtmPqInvU'); u.value = %s;"
                              " u.dispatchEvent(new Event('change', { bubbles: true }));"
                              " document.getElementById('rtmStatus').textContent = '';"
                              " document.getElementById('rtmPqInvGo').click(); })()" % (json.dumps(phases), json.dumps(u)))
                return await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC found') "
                                         f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")

            # At 5 %, the calcite is within the uncertainty of the water's calcium: the minimal model needs no phase.
            loose = await inverse('Calcite', '0.05')
            loose_out = await page.ev("[document.getElementById('rtmPqInvOut').textContent, document.getElementById('rtmChartPqInv').hidden]")
            check('at 5 %, a day of the calcite is within the calcium\'s uncertainty: one minimal model, of no phase, and no bars',
                  isinstance(loose, str) and loose.startswith('PHREEQC found 1 inverse model') and isinstance(loose_out, list)
                  and 'none: the waters are the same to within the uncertainty' in loose_out[0] and loose_out[1], True)
            tight = await inverse('Calcite', '1e-6')
            bars = await page.ev("(() => { const d = document.getElementById('rtmChartPqInv').data || [];"
                                 " return d.map((t) => [t.name, t.x, t.y, t.error_y ? [t.error_y.array, t.error_y.arrayminus] : null]); })()")
            moved = (calcite[0] - calcite[1]) if isinstance(calcite, list) else None
            got = bars[0][2][0] if bars and bars[0][2] else None
            check('at 1e-6, PHREEQC\'s model is the calcite the run formed, to the four figures it prints: '
                  f'{got} for {moved}', isinstance(tight, str) and tight.startswith('PHREEQC found 1 inverse model')
                  and moved is not None and got is not None and moved < 0
                  and abs(got - moved) <= 5e-4 * abs(moved) and bars[0][0] == 'model 1' and bars[0][1] == ['Calcite']
                  and bars[0][3] is not None and bars[0][3][0][0] > 0 and bars[0][3][1][0] > 0, True)
            note = await page.ev("document.getElementById('rtmPqInvNote').textContent")
            check('  and the note says between which waters, what was balanced and to what',
                  isinstance(note, str) and note.startswith('1 model, minimal ones only: from the water as it starts to the water as '
                                                            'the run ends, C, Ca, Cl, Fe, K, Mg, Na, S, Si balanced to 0.0001 %'), True)
            await page.ev("""(() => {
              window.__csv = null;
              const make = URL.createObjectURL, click = HTMLAnchorElement.prototype.click;
              URL.createObjectURL = (b) => { window.__csv = b; return 'blob:caught'; };
              HTMLAnchorElement.prototype.click = function () {};
              document.querySelector('[data-on-click="rtm:pqInvCsv"]').click();
              URL.createObjectURL = make; HTMLAnchorElement.prototype.click = click;
            })()""")
            inv_csv = await page.ev("window.__csv ? window.__csv.text() : null")
            inv_lines = inv_csv.strip().split('\n') if isinstance(inv_csv, str) else []
            check('  CSV: every number of the model, the calcite\'s transfer and its range among them',
                  bool(inv_lines) and inv_lines[0] == 'model,minimal,what,name,value,minimum,maximum'
                  and any(ln.startswith('1,true,phase mole transfer (mol),Calcite,') for ln in inv_lines)
                  and any(ln.startswith('1,true,sum of residuals,') for ln in inv_lines), True)
            bad = await inverse('Calcitee', '0.05')
            check('  a phase the database does not have is said', isinstance(bad, str)
                  and bad.startswith('PHREEQC could not work out inverse models: The database has no phase Calcitee.'), True)

            # The example of it: water with CO2 through calcite and gypsum, opening once run on PHREEQC's inverse model.
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))
            await page.ev("(() => { const s = document.getElementById('rtmExample'); s.value = 'inversecolumn';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.ev(CLICK % json.dumps('#rtmRun'))
            inv_ex = await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC found') "
                                       f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            inv_ex_out = await page.ev("[document.querySelector('.rtm-tabs button.active').dataset.tab,"
                                       " document.getElementById('rtmPqInvNote').textContent, document.getElementById('rtmPqInvOut').textContent]")
            check('the example of it opens once run on the PHREEQC tab: from the water flowing in to the outlet as the run ends, '
                  f'calcite and gypsum, 1.268e-3 and 1.470e-2 mol, what the column dissolved ({inv_ex} | {str(inv_ex_out)[:300]})',
                  isinstance(inv_ex, str)
                  and inv_ex.startswith('PHREEQC found 1 inverse model') and isinstance(inv_ex_out, list) and inv_ex_out[0] == 'phreeqc'
                  and inv_ex_out[1].startswith('1 model, minimal ones only: from the water flowing in to cell 9 as the run ends')
                  and 'Calcite 1.268e-3' in inv_ex_out[2] and 'Gypsum 1.470e-2' in inv_ex_out[2], True)
            check('  on the database it was written from, the built-in phreeqc.dat, nothing filled in from the panel\'s water',
                  await page.ev("[document.getElementById('rtmPqViewDb').value, document.getElementById('rtmPqFill').checked]"),
                  ['builtin', False])

            # --- the temperature: the example water warmed along a table, run, and looked at through PHREEQC ---
            warm_report = await write_from_example(page)
            check('the hand-off says the relations\' log K go with temperature, as the database\'s do',
                  isinstance(warm_report, str) and re.search(r"[0-9]+ of the [0-9]+ relations’ log K goes with temperature "
                                                              r"as the database’s does", warm_report) is not None, True)
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            await page.ev("""(() => {
              document.getElementById('rtmStatus').textContent = '';
              const t = document.getElementById('rtmText');
              t.value = t.value.replace(/^TEMPERATURE = 15$/m, 'TEMPERATURE = warm(t)')
                .replace('TEND = 1\\n', 'TEND = 1e5\\n').replace('<SPECIES>', '<TABLE warm>\\n0 15\\n1e5 35\\n\\n<SPECIES>');
              t.dispatchEvent(new Event('input', { bubbles: true }));
            })()""")
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            await until(page, "/warm\\(t\\)/.test(document.getElementById('rtmFacts').textContent) || ''")
            check('and with TEMPERATURE a table read at the clock the model facts say so', await page.ev(
                "/The temperature is warm\\(t\\): 15\\s°C at the start, and it goes with time; [0-9]+ log K follow it/"
                ".test(document.getElementById('rtmFacts').textContent)"), True)
            await page.ev(CLICK % json.dumps('#rtmRun'))
            await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            await page.ev("document.getElementById('rtmStatus').textContent = ''")
            await page.ev(CLICK % json.dumps('#rtmPqLook'))
            await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                              f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            warm = await page.ev("document.getElementById('rtmPqSummary').textContent")
            m_warm = re.search(r"the model's own are within ([0-9.e−+-]+) of PHREEQC's in log K", warm or '')
            check('looked at through PHREEQC, each water at its own temperature in the run, 15 to 35 °C, and the model\'s '
                  'own activity coefficients PHREEQC\'s at it',
                  isinstance(warm, str) and 'each at its own temperature in the run, 15 to 35 °C' in warm
                  and m_warm is not None and float(m_warm.group(1).replace('−', '-')) < 1e-6, True)
            await page.ev(CLICK % json.dumps('[data-tab="model"]'))

            # --- a column, looked at against distance ---
            column = ('<SETTINGS>\\nMODE = transport\\nCELLS = 5\\nLENGTH = 0.05\\nDIFFUSION = 1\\nTEND = 1e4\\n'
                      'EQUILIBRATE = always\\n\\n<SPECIES>\\nH+      1e-7   D=1e-9\\nOH-     1e-7   D=1e-9\\n'
                      'CO2     1e-4   D=1e-9\\nHCO3-   2e-3   D=1e-9\\nCO3-2   1e-5   D=1e-9\\nCa+2    1e-3   D=1e-9\\n'
                      'Cl-     2.2e-4 D=1e-9\\n\\n<INITIAL>\\nH+ 0 1e-4\\nCl- 0 3.2e-4\\n\\n<EQUILIBRIUM>\\n'
                      ' <=> H+ + OH-,          logK = -14\\nCO2 <=> H+ + HCO3-,     logK = -6.35\\n'
                      'HCO3- <=> H+ + CO3-2,   logK = -10.33\\n')
            await page.ev(f"""(() => {{ const t = document.getElementById('rtmText'); t.value = '{column}';
              t.dispatchEvent(new Event('input', {{ bubbles: true }})); }})()""")
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            await page.ev(CLICK % json.dumps('#rtmRun'))
            await settle(page, f"{STATUS}.slice(0, 4)", 'Done', tries=600)
            await page.ev(CLICK % json.dumps('[data-tab="phreeqc"]'))
            await page.ev("(() => { const f = document.getElementById('rtmPqTimes'); f.value = '4';"
                          " f.dispatchEvent(new Event('change', { bubbles: true }));"
                          " document.getElementById('rtmStatus').textContent = ''; })()")
            await page.ev(CLICK % json.dumps('#rtmPqLook'))
            await until(page, f"(() => {{ const t = {STATUS}; return t.startsWith('PHREEQC looked at') "
                              f"|| t.startsWith('PHREEQC could not') ? t : ''; }})()")
            check('a column offers the view against distance', await page.ev(
                "!document.getElementById('rtmPqModeWrap').hidden"), True)
            await page.ev("(() => { const s = document.getElementById('rtmPqMode'); s.value = 'distance';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            across = await page.ev("(() => { const d = document.getElementById('rtmChartPq').data || [];"
                                   " return d.length ? [d[0].x.map((x) => +x.toFixed(4)),"
                                   " !document.getElementById('rtmPqTimeWrap').hidden,"
                                   " document.getElementById('rtmPqCellWrap').hidden,"
                                   " document.getElementById('rtmPqTime').options.length] : null; })()")
            check('against distance: each cell at its centre down the column, at one of the times looked at',
                  across, [[0.005, 0.015, 0.025, 0.035, 0.045], True, True, 4])
            # ---- a batch over a table of waters ----
            # A CSV of our own, semicolons and decimal commas, made in the page and handed to the file input: three waters,
            # the second with no number for its pH. Opened with the box empty, the input starts: a SOLUTION with pH, Na and
            # Cl under it, commented. Run with them in: each row's pH as given and its ionic strength the salt's, the second
            # refused with what PHREEQC said; Rows 1, 3 runs those two. A name the table has not, and an input with no
            # SELECTED_OUTPUT, are said before anything runs. An Excel workbook of two sheets, made by the page's own writer:
            # the second chosen, its rows run. The CSV saved: the table's values the input asked for, PHREEQC's, what it said.
            await page.ev(CLICK % json.dumps('[data-tab="batch"]'))
            await asyncio.sleep(0.3)
            check('the batch, a tab of its own: its database one choice with the PHREEQC tab, Open a database… among them; '
                  'its Export menu in groups, the map\'s hidden until there is a map',
                  await page.ev("""(() => { const b = document.getElementById('rtmPqBatchDb'), v = document.getElementById('rtmPqViewDb');
                    return [b.value === v.value, [...b.options].slice(-1)[0].value, !!document.querySelector('.rtm-pane[data-pane="batch"] #rtmPqBatchBar'),
                      !document.querySelector('.rtm-pane[data-pane="phreeqc"] #rtmPqBatchBar'),
                      [...document.querySelectorAll('#rtmExportPqBatch .rtm-menu-head')].filter((h) => !h.hidden).map((h) => h.textContent)]; })()"""),
                  [True, '__open', True, True, ['All of it', 'The numbers', 'The spread', 'Against a column']])
            FEED = """(async (name, text, sheets) => { const input = document.getElementById('rtmPqBatchFile');
              let data = text;
              if (sheets) { const x = new XlsxWriter(name); for (const [nm, head, rows] of sheets) x.writeData(rows, nm, { header: head });
                data = await x.save(); }
              const dt = new DataTransfer(); dt.items.add(new File([data], name)); input.files = dt.files;
              input.dispatchEvent(new Event('change', { bubbles: true })); })(%s, %s, %s)"""
            BATCH_STATUS = "document.getElementById('rtmStatus').textContent"
            await page.ev(FEED % (json.dumps('waters.csv'), json.dumps('pH;Na;Cl\n7,0;10;10\nx;1;1\n8,5;1;2\n'), 'null'))
            opened = await settle(page, f"{BATCH_STATUS}.startsWith('waters.csv: 3 rows and 3 columns')", True, tries=40)
            started = await page.ev("document.getElementById('rtmPqBatchText').value")
            check('a batch over a table: a CSV of three waters opened, semicolons and decimal commas read; the input started from it',
                  [opened, await page.ev("document.getElementById('rtmPqBatchTable').textContent"),
                   started.split('\n')[1:6] if isinstance(started, str) else started],
                  [True, 'waters.csv: 3 rows; columns pH, Na, Cl.', ['SOLUTION 1', ' units mol/kgw', ' pH {pH}', '# Na {Na}', '# Cl {Cl}']])
            SET_INPUT = """((text, rows) => { const ta = document.getElementById('rtmPqBatchText'); ta.value = text;
              ta.dispatchEvent(new Event('change', { bubbles: true }));
              const r = document.getElementById('rtmPqBatchRows'); r.value = rows; r.dispatchEvent(new Event('change', { bubbles: true })); })(%s, %s)"""
            NACL = ('SOLUTION 1\n units mmol/kgw\n pH {pH}\n Na {Na}\n Cl {Cl}\nSELECTED_OUTPUT 1\n -reset false\n -pH true\n'
                    ' -ionic_strength true\nEND\n')
            BATCH_ROWS = """[...document.querySelectorAll('#rtmPqBatchOut tbody tr')].map((tr) => [...tr.cells].map((c) => c.textContent))"""

            async def batch(text, rows=''):
                await page.ev(SET_INPUT % (json.dumps(text), json.dumps(rows)))
                await page.ev("document.getElementById('rtmStatus').textContent = ''")
                await page.ev(CLICK % json.dumps('#rtmPqBatchGo'))
                return await until(page, f"(() => {{ const s = {BATCH_STATUS}; return / run through PHREEQC|could not be run|^The input|^Solids|^Uncertain|^Draws|^Seed|^Rows:|^Open a table/.test(s) ? s : null; }})()",
                                   tries=120, pause=0.25)

            said = await batch(started)
            check('  the input as started runs as it is: pure water at each row\'s pH, the row with no number refused',
                  [said.startswith('3 of 3 rows run through PHREEQC') and said.endswith('; 1 refused by PHREEQC, each with what it said.')
                   if isinstance(said, str) else said, [r[:2] for r in await page.ev(BATCH_ROWS)]],
                  [True, [['1', '7'], ['2', 'ERROR: Concentration data error for ph in solution input.'], ['3', '8.5']]])
            said = await batch(NACL)
            rows = await page.ev(BATCH_ROWS)
            check('  run: each row\'s pH as given and its ionic strength the salt\'s; the second refused with what PHREEQC said',
                  [said, rows, await page.ev("document.getElementById('rtmPqBatchNote').textContent"),
                   await page.ev("[...document.querySelectorAll('#rtmPqBatchOut thead th')].map((th) => th.textContent)")],
                  [said if isinstance(said, str) and said.startswith('3 of 3 rows run through PHREEQC') and 'with phreeqc.dat' in said
                   and said.endswith('; 1 refused by PHREEQC, each with what it said.') else 'a status of 3 rows, 1 refused',
                   [['1', '7', '0.01'], ['2', 'ERROR: Concentration data error for ph in solution input.'], ['3', '8.5', '0.001502']],
                   '3 rows of waters.csv; 2 columns of selected output; 1 refused.', ['row', 'pH', 'mu']])
            said = await batch(NACL, '1, 3')
            check('  Rows 1, 3: those two run, the button saying so',
                  [said.startswith('2 of 2 rows run through PHREEQC') if isinstance(said, str) else said,
                   [r[0] for r in await page.ev(BATCH_ROWS)], await page.ev("document.getElementById('rtmPqBatchGo').textContent")],
                  [True, ['1', '3'], 'Run the rows asked for'])
            unknown = await batch(NACL.replace('{Cl}', '{K}'), '')
            no_output = await batch(NACL.split('SELECTED_OUTPUT')[0], '')
            check('  a name the table has not, and an input with no SELECTED_OUTPUT, said before anything runs',
                  [unknown, no_output],
                  ['The input asks for {K}, but the table has no column so named; its columns: pH, Na, Cl.',
                   "The input has no SELECTED_OUTPUT: say there what to keep of each row's run, -totals, -pH and the like, or a USER_PUNCH."])
            await page.ev(FEED % (json.dumps('book.xlsx'), 'null', json.dumps(
                [['notes', ['about'], [['two waters of salt']]], ['waters', ['pH', 'Na', 'Cl'], [[7.5, 5, 5], [8, 1, 1]]]])))
            await settle(page, f"{BATCH_STATUS}.startsWith('book.xlsx, sheet notes:')", True, tries=60)
            await page.ev("(() => { const s = document.getElementById('rtmPqBatchSheet'); s.value = 'waters';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            described = await page.ev("document.getElementById('rtmPqBatchTable').textContent")
            said = await batch(NACL, '')
            check('  an Excel workbook of two sheets: the second chosen, its rows run',
                  [described, said.startswith('2 of 2 rows run through PHREEQC') if isinstance(said, str) else said,
                   [r[:2] for r in await page.ev(BATCH_ROWS)]],
                  ['book.xlsx, sheet waters: 2 rows; columns pH, Na, Cl.', True, [['1', '7.5'], ['2', '8']]])
            await page.ev("""(() => {
              window.__csv = null;
              const make = URL.createObjectURL, click = HTMLAnchorElement.prototype.click;
              URL.createObjectURL = (b) => { window.__csv = b; return 'blob:caught'; };
              HTMLAnchorElement.prototype.click = function () {};
              window.__restore = () => { URL.createObjectURL = make; HTMLAnchorElement.prototype.click = click; };
              document.querySelector('[data-on-click="rtm:pqBatchSave"][data-as="csv"]').click();
            })()""")
            await settle(page, "!!window.__csv", True, tries=40, pause=0.1)
            await page.ev("window.__restore()")
            batch_csv = await page.ev("window.__csv ? window.__csv.text() : null")
            check('  saved as CSV: the table\'s values the input asked for, PHREEQC\'s pH apart from the table\'s, what it said',
                  batch_csv.strip().split('\n')[:2] if isinstance(batch_csv, str) else batch_csv,
                  ['row,pH,Na,Cl,"pH, PHREEQC",mu,refused', batch_csv.strip().split('\n')[1] if isinstance(batch_csv, str)
                   and batch_csv.strip().split('\n')[1].startswith('1,7.5,5,5,7.5,0.005') else '1,7.5,5,5,7.5,0.005...'])
            # ---- several solids, the lowest kept ----
            # Three waters of 20 mM calcium: one with carbonate, one with sulfate, one with no number for its pH; Calcite,
            # Gypsum and a solid the database has not, each in turn as {solid} 0 10. Lowest in calcium, the first total of
            # an element: Calcite's run in the first water, Gypsum's in the second, every solid refused in the third, and
            # above them how each solid fared. Lowest in si_Gypsum, which only Gypsum's runs give: Gypsum in both. A list
            # with no {solid} in the input, and {solid} with no list, are said before anything runs. Saved: the lowest for
            # each row with the solids refused in it, and every run.
            await page.ev(FEED % (json.dumps('salts.csv'), json.dumps('pH;C;S\n8;10;0,1\n7;0,01;50\nx;1;1\n'), 'null'))
            await settle(page, f"{BATCH_STATUS}.startsWith('salts.csv: 3 rows and 3 columns')", True, tries=40)
            SET_SOLIDS = """((v) => { const s = document.getElementById('rtmPqBatchSolids'); s.value = v;
              s.dispatchEvent(new Event('change', { bubbles: true })); })(%s)"""
            SOLIDS_IN = ('SOLUTION 1\n units mmol/kgw\n pH {pH}\n Ca 20\n C(4) {C}\n S(6) {S}\nEQUILIBRIUM_PHASES 1\n {solid} 0 10\n'
                         'SELECTED_OUTPUT 1\n -reset false\n -pH true\n -totals Ca C(4) S(6)\n -saturation_indices {solid}\nEND\n')
            await page.ev(SET_SOLIDS % json.dumps('Calcite, Gypsum Nosuch'))
            await asyncio.sleep(0.2)
            check('several solids: the list read, and the runs it makes said under the table',
                  await page.ev("document.getElementById('rtmPqBatchTable').textContent"),
                  'salts.csv: 3 rows; columns pH, C, S. 3 rows to run, each with 3 solids: 9 runs.')
            no_solid = await batch(SOLIDS_IN.replace('{solid}', 'Calcite'))
            said = await batch(SOLIDS_IN)
            SOLID_ROWS = """[...document.querySelectorAll('#rtmPqBatchOut table')].map((tb) => [...tb.querySelectorAll('tbody tr')]
              .map((tr) => [...tr.cells].map((c) => c.textContent)))"""
            tables = await page.ev(SOLID_ROWS)
            PH_ERR = 'ERROR: Concentration data error for ph in solution input.'
            check('  run: each row with each solid; the lowest calcium Calcite\'s in the carbonate water and Gypsum\'s in the sulfate one, '
                  'the third refused with every solid; above them how each solid fared',
                  [no_solid, said.startswith('3 of 3 rows, each with 3 solids, run through PHREEQC') and said.endswith(
                      '; 5 runs refused by PHREEQC, each with what it said.') if isinstance(said, str) else said, tables,
                   await page.ev("[...document.querySelectorAll('#rtmPqBatchOut table:last-child thead th')].map((th) => th.textContent)"),
                   await page.ev("document.querySelector('#rtmPqBatchOut th.rtm-pq-batch-key').textContent"),
                   await page.ev("document.getElementById('rtmPqBatchLowest').value"),
                   await page.ev("[document.getElementById('rtmPqBatchLowestWrap').hidden, document.getElementById('rtmPqBatchRunsItem').hidden]"),
                   await page.ev("document.getElementById('rtmPqBatchNote').textContent")],
                  ['Solids are listed, but the input has no {solid}: write it where each solid goes, as {solid} 0 10 under EQUILIBRIUM_PHASES.',
                   True,
                   [[['Calcite', '1 of 3 rows', '1 of 3 runs', PH_ERR], ['Gypsum', '1 of 3 rows', '1 of 3 runs', PH_ERR],
                     ['Nosuch', '0 of 3 rows', '3 of 3 runs', 'ERROR: Phase not found in database, Nosuch.']],
                    [['1', 'Calcite', '6.409', '0.01674', '0.006742', '1.000e-4', '0', '', 'Nosuch'],
                     ['2', 'Gypsum', '7.009', '0.009062', '1.000e-5', '0.03907', '', '0', 'Nosuch'],
                     ['3', f'every solid refused: {PH_ERR}', 'Calcite, Gypsum, Nosuch']]],
                   ['row', 'solid', 'pH', 'Ca(mol/kgw)', 'C(4)(mol/kgw)', 'S(6)(mol/kgw)', 'si_Calcite', 'si_Gypsum', 'refused'],
                   'Ca(mol/kgw)', 'Ca(mol/kgw)', [False, False],
                   '3 rows of salts.csv, each with 3 solids: 9 runs; 5 runs refused.'])
            LOWEST_IN = """((v) => { const s = document.getElementById('rtmPqBatchLowest'); s.value = v;
              s.dispatchEvent(new Event('change', { bubbles: true })); })(%s)"""
            await page.ev(LOWEST_IN % json.dumps('si_Gypsum'))
            await asyncio.sleep(0.2)
            tables = await page.ev(SOLID_ROWS)
            check('  Lowest in si_Gypsum, which only Gypsum\'s runs give: Gypsum the lowest in both waters',
                  [[r[1] for r in tables[1]], [r[1] for r in tables[0]] if tables else tables],
                  [['Gypsum', 'Gypsum', f'every solid refused: {PH_ERR}'], ['0 of 3 rows', '2 of 3 rows', '0 of 3 rows']])
            await page.ev(LOWEST_IN % json.dumps('Ca(mol/kgw)'))
            await asyncio.sleep(0.2)
            STATS = """[document.querySelector('#rtmPqBatchStats caption').textContent,
              [...document.querySelectorAll('#rtmPqBatchStats tbody tr')].map((tr) => [tr.cells[0].textContent, tr.cells[1].textContent])]"""
            check('  the spread over the waters of each row\'s lowest calcium: two waters, the third left out',
                  [await page.ev(STATS), await page.ev("document.getElementById('rtmChartPqBatch').layout.xaxis.type"),
                   await page.ev("document.getElementById('rtmPqBatchLowestLabel').textContent")],
                  [['Ca(mol/kgw), the lowest of each row',
                    [['waters', '2'], ['smallest', '0.009062'], ['5th percentile', '0.009446'], ['median', '0.0129'],
                     ['95th percentile', '0.01636'], ['largest', '0.01674'], ['left out, refused or with no number', '1']]],
                   'linear', 'Lowest in'])

            async def saved_csv(selector):
                await page.ev("""(() => {
                  window.__csv = null;
                  const make = URL.createObjectURL, click = HTMLAnchorElement.prototype.click;
                  URL.createObjectURL = (b) => { window.__csv = b; return 'blob:caught'; };
                  HTMLAnchorElement.prototype.click = function () {};
                  window.__restore = () => { URL.createObjectURL = make; HTMLAnchorElement.prototype.click = click; };
                  document.querySelector(%s).click();
                })()""" % json.dumps(selector))
                await settle(page, "!!window.__csv", True, tries=40, pause=0.1)
                await page.ev("window.__restore()")
                got = await page.ev("window.__csv ? window.__csv.text() : null")
                return got.strip().split('\n') if isinstance(got, str) else got

            lowest = await saved_csv('#rtmPqBatchCsvItem')
            runs = await saved_csv('#rtmPqBatchRunsItem')
            HEAD = 'row,pH,C,S,solid,"pH, PHREEQC",Ca(mol/kgw),C(4)(mol/kgw),S(6)(mol/kgw),si_Calcite,si_Gypsum,refused'
            check('  saved: the lowest for each row with the solids refused in it, and every run',
                  [lowest[0], lowest[1].startswith('1,8,10,0.1,Calcite,6.4085') and lowest[1].endswith(
                      ',0,,"Nosuch: ERROR: Phase not found in database, Nosuch."'), lowest[3], len(runs), runs[0], runs[3]]
                  if isinstance(lowest, list) and isinstance(runs, list) else [lowest, runs],
                  [HEAD, True, f'3,x,1,1,,,,,,,,Calcite: {PH_ERR}; Gypsum: {PH_ERR}; Nosuch: {PH_ERR}', 10, HEAD,
                   '1,8,10,0.1,Nosuch,,,,,,,"ERROR: Phase not found in database, Nosuch."'])
            await page.ev(SET_SOLIDS % json.dumps(''))
            check('  {solid} in the input with no solids listed: said before anything runs', await batch(SOLIDS_IN),
                  'The input asks for {solid}: list under Solids the solids to try, each in turn.')
            # ---- the spread over the waters ----
            # Twenty waters of NaCl, 1 to 20 mmol/kgw, and one with no number among them, without solids: Spread of the
            # sodium, the first total of an element. Twenty waters, the 5th percentile 0.00195, the median 0.0105 and the
            # 95th 0.01905, between the nearest values as Excel's PERCENTILE.INC has them; the water with no number left
            # out and counted. The chart: a step a water from nought to 100 %, on a log axis (0.001 to 0.02), the median
            # and the 95th percentile marked and labelled. Saved: the chart as SVG, PNG and a page with the input under
            # it, and the workbook with the spread on a sheet of its own.
            waters = 'Na\n' + '\n'.join(['1', '2', '3', '4', '5', '6', '7', 'x'] + [str(i) for i in range(8, 21)]) + '\n'
            await page.ev(FEED % (json.dumps('spread.csv'), json.dumps(waters), 'null'))
            await settle(page, f"{BATCH_STATUS}.startsWith('spread.csv: 21 rows and 1 column')", True, tries=40)
            said = await batch('SOLUTION 1\n units mmol/kgw\n pH 7\n Na {Na}\n Cl {Na}\nSELECTED_OUTPUT 1\n -reset false\n -totals Na\nEND\n')
            chart = await page.ev("""(() => { const p = document.getElementById('rtmChartPqBatch'); if (!p.data) return null;
              const [s, m, q] = p.data; const log = p.layout.xaxis.type === 'log';
              return [s.x.length, s.y[0], s.y[s.y.length - 1], p.layout.xaxis.type,
              Number(m.x[0].toPrecision(6)), Number(q.x[0].toPrecision(6)), p.layout.annotations.map((a) => a.text),
              p.layout.annotations.map((a) => Number((log ? 10 ** a.x : a.x).toPrecision(6))),
              p.layout.yaxis.title.text, p.layout.xaxis.title.text]; })()""")
            check('the spread over the waters, without solids: Spread of the sodium, its numbers beside the chart, the water '
                  'with no number left out',
                  [said.startswith('21 of 21 rows run through PHREEQC') if isinstance(said, str) else said,
                   await page.ev(STATS), await page.ev("document.getElementById('rtmPqBatchLowestLabel').textContent"),
                   await page.ev("document.getElementById('rtmPqBatchLowestWrap').hidden"), chart],
                  [True, ['Na(mol/kgw)', [['waters', '20'], ['smallest', '0.001'], ['5th percentile', '0.00195'], ['median', '0.0105'],
                                          ['95th percentile', '0.01905'], ['largest', '0.02'], ['left out, refused or with no number', '1']]],
                   'Spread of', False,
                   [21, 0, 100, 'log', 0.0105, 0.01905, ['median 0.0105', '95 %: 0.01905'], [0.0105, 0.01905],
                    'waters at or below (%)', 'Na(mol/kgw)']])

            # Caught at the link the page clicks, not at URL.createObjectURL, which Plotly itself uses to make a PNG of its SVG.
            async def saved_blob(selector, how):
                await page.ev("""(() => {
                  window.__blob = null;
                  const click = HTMLAnchorElement.prototype.click;
                  HTMLAnchorElement.prototype.click = function () { window.__blob = fetch(this.href).then((r) => r.blob()); };
                  window.__restore = () => { HTMLAnchorElement.prototype.click = click; };
                  document.querySelector(%s).click();
                })()""" % json.dumps(selector))
                await settle(page, "!!window.__blob", True, tries=80, pause=0.1)
                await page.ev("window.__restore()")
                return await page.ev("window.__blob ? window.__blob.then((b) => (%s)(b)) : null" % how)

            svg = await saved_blob('[data-pane="batch"][data-as="svg"]', '(b) => b.text().then((t) => t.slice(0, 4))')
            png = await saved_blob('[data-pane="batch"][data-as="png"]', '(b) => [b.type, b.size > 2000]')
            html = await saved_blob('[data-pane="batch"][data-as="html"]',
                                    "(b) => b.text().then((t) => [t.includes('The PHREEQC input each row was run with'), t.includes(' Na {Na}')])")
            sheets = await saved_blob('[data-on-click="rtm:pqBatchSave"][data-as="xlsx"]',
                                      "(b) => JSZip.loadAsync(b).then((z) => z.file('xl/workbook.xml').async('string'))"
                                      ".then((x) => [...x.matchAll(/<sheet [^>]*name=\"([^\"]+)\"/g)].map((m) => m[1]))")
            check('  saved: the chart as SVG, PNG and a page with the input under it; the workbook with the spread on a sheet of its own',
                  [svg, png, html, sheets], ['<svg', ['image/png', True], [True, True], ['batch', 'spread', 'input']])
            # ---- uncertain values, drawn at random ----
            # Three waters, their pH from the table and their salt drawn: dNa uniform 1 2 (mmol/kgw), 20 draws each from
            # seed 7. Each run's sodium is the value it drew, to the last digit; every value between 1 and 2; the spread
            # over the 60 waters × draws. A row run on its own draws what it drew among the others; another seed draws
            # other values. A normal and a triangular, 400 draws of one water, read back through PHREEQC's USER_PUNCH:
            # PHREEQC's numbers the values drawn, the mean and spread of each what its distribution has. With solids,
            # every solid of a draw on the same values: the lowest calcium Calcite's in both draws of the carbonate water
            # and Gypsum's in both of the sulfate water. A misspelt distribution, a value the input has not, a value named
            # as a column, and draws of none, said before anything runs.
            SET_FIELD = """((id, v) => { const s = document.getElementById(id); s.value = v;
              s.dispatchEvent(new Event('change', { bubbles: true })); })(%s, %s)"""

            async def field(name, value):
                await page.ev(SET_FIELD % (json.dumps(name), json.dumps(value)))
                await asyncio.sleep(0.1)

            await page.ev(FEED % (json.dumps('draws.csv'), json.dumps('pH\n7\n7.5\n8\n'), 'null'))
            await settle(page, f"{BATCH_STATUS}.startsWith('draws.csv: 3 rows and 1 column')", True, tries=40)
            hidden_before = await page.ev("document.getElementById('rtmPqBatchDrawsWrap').hidden")
            await field('rtmPqBatchUncertain', 'dNa uniform 1 2')
            await field('rtmPqBatchDraws', '20')
            await field('rtmPqBatchSeed', '7')
            NA_IN = 'SOLUTION 1\n units mmol/kgw\n pH {pH}\n Na {dNa}\n Cl {dNa}\nSELECTED_OUTPUT 1\n -reset false\n -totals Na\nEND\n'
            described = await page.ev("document.getElementById('rtmPqBatchTable').textContent")
            said = await batch(NA_IN)
            head = await page.ev("[...document.querySelectorAll('#rtmPqBatchOut thead th')].map((th) => th.textContent)")
            note = await page.ev("document.getElementById('rtmPqBatchNote').textContent")
            stats_first = await page.ev("[...document.querySelectorAll('#rtmPqBatchStats tbody tr')][0].textContent")
            every = await saved_csv('#rtmPqBatchCsvItem')
            rows = [ln.split(',') for ln in every[1:]] if isinstance(every, list) else []
            exact = all(abs(float(r[4]) * 1000 / float(r[3]) - 1) < 1e-9 for r in rows) if rows else False
            within = all(1 <= float(r[3]) <= 2 for r in rows) if rows else False
            check('uncertain values: each row run 20 times, its salt drawn afresh; each run\'s sodium the value it drew',
                  [hidden_before, await page.ev("document.getElementById('rtmPqBatchDrawsWrap').hidden"), described,
                   said.startswith('3 of 3 rows, 20 draws each, run through PHREEQC') if isinstance(said, str) else said,
                   head, note, stats_first, every[0] if isinstance(every, list) else every, len(rows),
                   [r[:3] for r in rows[:2]] + [r[:3] for r in rows[-1:]], exact, within, len({r[3] for r in rows})],
                  [True, False, 'draws.csv: 3 rows; columns pH. 3 rows to run, 20 draws each: 60 runs.', True,
                   ['row', 'draw', 'dNa', 'Na(mol/kgw)'], '3 rows of draws.csv, 20 draws each: 60 runs, seed 7.', 'waters × draws60',
                   'row,pH,draw,dNa,Na(mol/kgw),refused', 60, [['1', '7', '1'], ['1', '7', '2'], ['3', '8', '20']], True, True, 60])
            row2 = [r[3] for r in rows if r[0] == '2']
            await field('rtmPqBatchRows', '2')
            await batch(NA_IN, '2')
            alone = await saved_csv('#rtmPqBatchCsvItem')
            await field('rtmPqBatchSeed', '8')
            await batch(NA_IN, '2')
            other = await saved_csv('#rtmPqBatchCsvItem')
            check('  a row run on its own draws what it drew among the others; another seed draws other values',
                  [[ln.split(',')[3] for ln in alone[1:]] == row2 if isinstance(alone, list) else alone,
                   len(set(ln.split(',')[3] for ln in other[1:]) & set(row2)) if isinstance(other, list) else other],
                  [True, 0])
            await field('rtmPqBatchSeed', '1')
            await field('rtmPqBatchUncertain', 'z normal 0 1; tri triangular 0 1 4')
            await field('rtmPqBatchDraws', '400')
            PUNCH_IN = 'SOLUTION 1\n pH {pH}\nSELECTED_OUTPUT 1\n -reset false\nUSER_PUNCH 1\n -headings z tri\n 10 PUNCH {z}, {tri}\nEND\n'
            said = await batch(PUNCH_IN, '1')
            punched = await saved_csv('#rtmPqBatchCsvItem')
            got = [ln.split(',') for ln in punched[1:]] if isinstance(punched, list) else []

            def moments(xs):
                m = sum(xs) / len(xs)
                return m, (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5

            zs = [float(r[3]) for r in got]
            ts = [float(r[4]) for r in got]
            zm, zsd = moments(zs) if zs else (None, None)
            tm, tsd = moments(ts) if ts else (None, None)
            check('  a normal and a triangular, 400 draws read back through USER_PUNCH: PHREEQC\'s numbers the values drawn, '
                  'their mean and spread their distributions\'',
                  [said.startswith('1 of 1 row, 400 draws each, run through PHREEQC') if isinstance(said, str) else said,
                   punched[0] if isinstance(punched, list) else punched, len(got),
                   all(float(r[3]) == float(r[5]) and float(r[4]) == float(r[6]) for r in got),
                   abs(zm) < 0.15 if zs else zs, 0.85 < zsd < 1.15 if zs else zs,
                   all(0 <= t <= 4 for t in ts), abs(tm - 5 / 3) < 0.13 if ts else ts, abs(tsd - (13 / 18) ** 0.5) < 0.1 if ts else ts],
                  [True, 'row,pH,draw,z,tri,"z, PHREEQC","tri, PHREEQC",refused', 400, True, True, True, True, True, True])
            await page.ev(FEED % (json.dumps('salts.csv'), json.dumps('pH;C;S\n8;10;0,1\n7;0,01;50\nx;1;1\n'), 'null'))
            await settle(page, f"{BATCH_STATUS}.startsWith('salts.csv: 3 rows and 3 columns')", True, tries=40)
            await field('rtmPqBatchUncertain', 'dCa uniform 15 25')
            await field('rtmPqBatchDraws', '2')
            await page.ev(SET_SOLIDS % json.dumps('Calcite, Gypsum'))
            await asyncio.sleep(0.1)
            await page.ev(LOWEST_IN % json.dumps('Ca(mol/kgw)'))
            said = await batch(SOLIDS_IN.replace(' Ca 20\n', ' Ca {dCa}\n').replace(' -saturation_indices {solid}\n', ''))
            tables = await page.ev(SOLID_ROWS)
            check('  with solids, every solid of a draw on the same values: Calcite the lowest in both draws of the carbonate water, '
                  'Gypsum in both of the sulfate one',
                  [said.startswith('3 of 3 rows, 2 draws each, each draw with 2 solids, run through PHREEQC') and said.endswith(
                      '; 4 runs refused by PHREEQC, each with what it said.') if isinstance(said, str) else said,
                   [r[:3] for r in tables[0]] if tables else tables, [[r[0], r[1], r[3]] for r in tables[1]] if tables else tables,
                   await page.ev("[...document.querySelectorAll('#rtmPqBatchOut table:last-child thead th')].map((th) => th.textContent)")],
                  [True, [['Calcite', '2 of 6 draws', '2 of 6 runs'], ['Gypsum', '2 of 6 draws', '2 of 6 runs']],
                   [['1', '1', 'Calcite'], ['1', '2', 'Calcite'], ['2', '1', 'Gypsum'], ['2', '2', 'Gypsum'],
                    ['3', '1', f'every solid refused: {PH_ERR}'], ['3', '2', f'every solid refused: {PH_ERR}']],
                   ['row', 'draw', 'dCa', 'solid', 'pH', 'Ca(mol/kgw)', 'C(4)(mol/kgw)', 'S(6)(mol/kgw)', 'refused']])
            await page.ev(SET_SOLIDS % json.dumps(''))
            await field('rtmPqBatchUncertain', 'dU normall 0 1')
            misspelt = await batch(NA_IN)
            await field('rtmPqBatchUncertain', 'dX normal 0 1')
            missing = await batch('SOLUTION 1\n pH {pH}\nSELECTED_OUTPUT 1\n -reset false\n -pH true\nEND\n')
            await field('rtmPqBatchUncertain', 'pH normal 7 0.1')
            column = await batch('SOLUTION 1\n pH {pH}\nSELECTED_OUTPUT 1\n -reset false\n -pH true\nEND\n')
            await field('rtmPqBatchUncertain', 'dX normal 0 1')
            await field('rtmPqBatchDraws', '0')
            none = await batch('SOLUTION 1\n pH {pH}\n # {dX}\nSELECTED_OUTPUT 1\n -reset false\n -pH true\nEND\n')
            check('  a misspelt distribution, a value the input has not, one named as a column, and draws of none: said before anything runs',
                  [misspelt, missing, column, none],
                  ['Uncertain: "dU normall 0 1": say how it varies, normal, uniform or triangular, as dU normal 0 0.5.',
                   'The input has no {dX}: write it where the value drawn goes, in a log_k or after -add_logk.',
                   'Uncertain: pH is a column of the table too; name the value drawn otherwise.',
                   'Draws: a whole number from 1, as 10.'])
            await field('rtmPqBatchUncertain', '')
            await field('rtmPqBatchDraws', '')
            # ---- several PHREEQCs at once ----
            # Thirty waters, each drawn twenty times: 600 runs in three parts. The browser saying it has two cores, one
            # PHREEQC runs the parts one after another; saying eight, three run at once, and the status says so. What
            # comes back is the same to the last character: every water's twenty draws in turn, each run's sodium the
            # value it drew.
            await page.ev(FEED % (json.dumps('thirty.csv'), json.dumps('pH\n' + '7\n' * 30), 'null'))
            await settle(page, f"{BATCH_STATUS}.startsWith('thirty.csv: 30 rows and 1 column')", True, tries=40)
            await field('rtmPqBatchUncertain', 'dNa uniform 1 2')
            await field('rtmPqBatchDraws', '20')
            await field('rtmPqBatchSeed', '3')
            CORES = "Object.defineProperty(navigator, 'hardwareConcurrency', { value: %d, configurable: true })"
            await page.ev(CORES % 2)
            alone = await batch(NA_IN)
            alone_csv = await saved_csv('#rtmPqBatchCsvItem')
            await page.ev(CORES % 8)
            at_once = await batch(NA_IN)
            at_once_csv = await saved_csv('#rtmPqBatchCsvItem')
            await page.ev("delete navigator.hardwareConcurrency")
            lines = [ln.split(',') for ln in at_once_csv[1:]] if isinstance(at_once_csv, list) else []
            check('several PHREEQCs at once: 600 runs in three parts, one PHREEQC and three at once, the same to the last character',
                  [alone.startswith('30 of 30 rows, 20 draws each, run through PHREEQC') and ' at a time' not in alone
                   if isinstance(alone, str) else alone,
                   at_once.startswith('30 of 30 rows, 20 draws each, run through PHREEQC') and ', 3 at a time, in ' in at_once
                   if isinstance(at_once, str) else at_once,
                   alone_csv == at_once_csv, len(lines),
                   [(int(r[0]), int(r[2])) for r in lines] == [(w, d) for w in range(1, 31) for d in range(1, 21)],
                   all(abs(float(r[4]) * 1000 / float(r[3]) - 1) < 1e-9 for r in lines) if lines else False],
                  [True, True, True, 600, True, True])
            await field('rtmPqBatchUncertain', '')
            await field('rtmPqBatchDraws', '')
            await field('rtmPqBatchSeed', '')
            # ---- a batch's input as a file ----
            # A file with its settings above it as comments, saved for another table: opened, the box has the input
            # without them, its own comment kept; Rows, Solids, Uncertain, Draws and Seed are filled, and the status
            # says which table it was saved for. Saved again, the settings are written afresh above the text, once,
            # with the table open. A plain input opened empties every setting.
            FEED_INPUT = """(async (name, text) => { const input = document.getElementById('rtmPqBatchInputFile');
              const dt = new DataTransfer(); dt.items.add(new File([text], name)); input.files = dt.files;
              input.dispatchEvent(new Event('change', { bubbles: true })); })(%s, %s)"""
            BODY = '# my own comment\nSOLUTION 1\n pH {pH}\nSELECTED_OUTPUT 1\n -reset false\n -pH true\nEND'
            SETTINGS = ('# Rows: 1-2\n# Solids: Calcite, Gypsum\n# Uncertain: dK normal 0 0.3\n# Draws: 5\n# Seed: 9\n'
                        '# Lowest in: Ca(mol/kgw)\n')
            await page.ev(FEED_INPUT % (json.dumps('saved.txt'), json.dumps(
                '# rtm.html batch settings:\n# Table: other.csv\n# Database: phreeqc.dat\n' + SETTINGS + '\n' + BODY + '\n')))
            opened = await settle(page, f"{BATCH_STATUS}.startsWith('saved.txt opened')", True, tries=40)
            FIELDS = "['rtmPqBatchText', 'rtmPqBatchRows', 'rtmPqBatchSolids', 'rtmPqBatchUncertain', 'rtmPqBatchDraws', 'rtmPqBatchSeed'].map((id) => document.getElementById(id).value)"
            got = await page.ev(FIELDS)
            said = await page.ev(BATCH_STATUS)
            again = await saved_blob('[data-on-click="rtm:pqBatchSaveInput"]', '(b) => b.text()')
            check('a batch\'s input as a file: opened, its settings in their fields and out of the text; the table it was saved for said',
                  [opened, got, said],
                  [True, [BODY + '\n', '1-2', 'Calcite, Gypsum', 'dK normal 0 0.3', '5', '9'],
                   'saved.txt opened: the input and its Rows, Solids, Uncertain, Draws, Seed, Lowest in. It was saved for the table '
                   'other.csv; have it open before running.'])
            check('  saved again: the settings written afresh above the text, once, with the table open',
                  again, '# rtm.html batch settings:\n# Table: thirty.csv\n# Database: phreeqc.dat\n' + SETTINGS + '\n' + BODY + '\n')
            # Without solids the column is Spread of, in the status and in the file saved.
            await page.ev(FEED_INPUT % (json.dumps('spread.txt'), json.dumps('# Spread of: pH\n' + BODY)))
            await settle(page, f"{BATCH_STATUS}.startsWith('spread.txt opened')", True, tries=40)
            spread_said = await page.ev(BATCH_STATUS)
            spread_saved = await saved_blob('[data-on-click="rtm:pqBatchSaveInput"]', '(b) => b.text()')
            check('  without solids the column is Spread of, opened and saved',
                  [spread_said, spread_saved.split('\n')[:4] if isinstance(spread_saved, str) else spread_saved],
                  ['spread.txt opened: the input and its Spread of.',
                   ['# rtm.html batch settings:', '# Table: thirty.csv', '# Database: phreeqc.dat', '# Spread of: pH']])
            await page.ev(FEED_INPUT % (json.dumps('plain.txt'), json.dumps('SOLUTION 1\n pH 7\nEND\n')))
            await settle(page, f"{BATCH_STATUS}.startsWith('plain.txt opened')", True, tries=40)
            check('  a plain input opened: every setting left empty',
                  [await page.ev(FIELDS), await page.ev(BATCH_STATUS),
                   await page.ev("document.getElementById('rtmPqBatchDrawsWrap').hidden")],
                  [['SOLUTION 1\n pH 7\nEND\n', '', '', '', '', ''], 'plain.txt opened: the input.', True])
            # ---- several elements at once ----
            # Two waters with barium and strontium, one rich in sulfate and one in carbonate, the solids listed under
            # each element. Barium lowest with barite in the sulfate water and witherite in the carbonate one, strontium
            # with celestite and strontianite; above, element by element, each solid the lowest in one of two rows.
            # Barium with witherite alone: its lowest is witherite's, though the strontium solids leave barium lower,
            # where it was. An element whose total the input does not give is said after the run; a solid under no
            # element, and a name that is no element, before it. Saved: each element's lowest and its solid.
            BASR = 'name,pH,Ba,Sr,SO4,CO3\nsulfate water,7,0.1,1,10,0.1\ncarbonate water,9,0.1,1,0.01,10\n'
            await page.ev(FEED % (json.dumps('basr.csv'), json.dumps(BASR), 'null'))
            await settle(page, f"{BATCH_STATUS}.startsWith('basr.csv: 2 rows and 6 columns')", True, tries=40)
            BASR_IN = ('SOLUTION 1 {name}\n units mmol/kgw\n pH {pH}\n Ba {Ba}\n Sr {Sr}\n S(6) {SO4}\n C(4) {CO3}\n Na 20\n Cl 20\n'
                       'EQUILIBRIUM_PHASES 1\n {solid} 0 10\nSELECTED_OUTPUT 1\n -reset false\n -pH true\n -totals Ba Sr\nEND\n')
            await page.ev(SET_SOLIDS % json.dumps('Ba: Barite, Witherite; Sr: Celestite, Strontianite'))
            await asyncio.sleep(0.1)
            said = await batch(BASR_IN)
            tables = await page.ev(SOLID_ROWS)
            check('several elements at once: each element\'s lowest among its own solids, every solid run once for each row',
                  [said.startswith('2 of 2 rows, each with 4 solids for Ba and Sr, run through PHREEQC') and said.endswith(' s.')
                   if isinstance(said, str) else said, tables,
                   await page.ev("[...document.querySelectorAll('#rtmPqBatchOut table:last-child thead th')].map((th) => th.textContent)"),
                   await page.ev("[...document.getElementById('rtmPqBatchLowest').options].map((o) => o.value)"),
                   await page.ev("document.getElementById('rtmPqBatchLowestLabel').textContent"),
                   await page.ev("document.querySelector('#rtmPqBatchStats caption').textContent"),
                   await page.ev("document.getElementById('rtmPqBatchNote').textContent")],
                  [True, [[['Ba', 'Barite', '1 of 2 rows', '0 of 2 runs'], ['Ba', 'Witherite', '1 of 2 rows', '0 of 2 runs'],
                           ['Sr', 'Celestite', '1 of 2 rows', '0 of 2 runs'], ['Sr', 'Strontianite', '1 of 2 rows', '0 of 2 runs']],
                          [['1', 'Barite', '1.418e-7', 'Celestite', '1.500e-4'], ['2', 'Witherite', '1.775e-5', 'Strontianite', '4.071e-5']]],
                   ['row', 'Ba: solid', 'Ba(mol/kgw)', 'Sr: solid', 'Sr(mol/kgw)'], ['Ba(mol/kgw)', 'Sr(mol/kgw)'], 'Spread of',
                   'Ba(mol/kgw), the lowest of each row', '2 rows of basr.csv, each with 4 solids for Ba and Sr: 8 runs.'])
            lowest = await saved_csv('#rtmPqBatchCsvItem')
            check('  saved: each element\'s lowest and the solid that gave it',
                  lowest[:2] if isinstance(lowest, list) else lowest,
                  ['row,name,pH,Ba,Sr,SO4,CO3,Ba: solid,Ba(mol/kgw),Sr: solid,Sr(mol/kgw),refused',
                   lowest[1] if isinstance(lowest, list) and lowest[1].startswith('1,sulfate water,7,0.1,1,10,0.1,Barite,1.418')
                   and ',Celestite,' in lowest[1] else 'the sulfate water: Barite, then Celestite'])
            await page.ev(SET_SOLIDS % json.dumps('Ba: Witherite; Sr: Celestite, Strontianite'))
            await asyncio.sleep(0.1)
            await batch(BASR_IN)
            tables = await page.ev(SOLID_ROWS)
            check('  barium with witherite alone: its lowest is witherite\'s, not where the strontium solids leave it',
                  tables[1][0] if tables else tables, ['1', 'Witherite', '2.769e-4', 'Celestite', '1.500e-4'])
            await page.ev(SET_SOLIDS % json.dumps('Ba: Barite; Sr: Celestite'))
            await asyncio.sleep(0.1)
            missing = await batch(BASR_IN.replace(' -totals Ba Sr\n', ' -totals Ba\n'))
            await page.ev(SET_SOLIDS % json.dumps('Ba: Barite; Celestite'))
            loose = await batch(BASR_IN)
            await page.ev(SET_SOLIDS % json.dumps('Xx: Barite'))
            not_one = await batch(BASR_IN)
            check('  a total the input does not give said after the run; a solid under no element and a name that is no element, before',
                  [missing.endswith('; the selected output has no Sr(mol/kgw): add Sr to its -totals.') if isinstance(missing, str) else missing,
                   loose, not_one],
                  [True, 'Solids: "Celestite" is under no element: with solids listed for an element, list each under its own, as Ba: Barite, '
                         'Witherite; Sr: Celestite.', 'Solids: "Xx: Barite": Xx is no element.'])
            await page.ev(SET_SOLIDS % json.dumps(''))
            # ---- the result against a column ----
            # Barium and strontium with their solids: against the table's pH unless another is chosen, a series a solid
            # with a legend, barite's point at pH 7 and witherite's at 9. Against PHREEQC's own pH, of the run kept; the
            # choice saved with the input. Twenty waters of NaCl without solids: against the table's Na, every point's
            # result its Na over 1000, the water with no number left out and counted. With draws: against the value drawn.
            AGAINST = """(() => { const p = document.getElementById('rtmChartPqBatchX'); const s = document.getElementById('rtmPqBatchX');
              return [s.value, [...s.querySelectorAll('optgroup')].map((g) => g.label), document.getElementById('rtmPqBatchAgainst').hidden,
                p.data ? p.data.map((t) => [t.name, t.x, t.y.map((y) => Number(y.toPrecision(4)))]) : null,
                p.layout ? [p.layout.showlegend, p.layout.xaxis.type, p.layout.yaxis.type, p.layout.xaxis.title.text] : null,
                document.getElementById('rtmPqBatchAgainstNote').hidden ? '' : document.getElementById('rtmPqBatchAgainstNote').textContent]; })()"""
            await page.ev(FEED % (json.dumps('basr.csv'), json.dumps(BASR), 'null'))
            await settle(page, f"{BATCH_STATUS}.startsWith('basr.csv: 2 rows and 6 columns')", True, tries=40)
            await page.ev(SET_SOLIDS % json.dumps('Ba: Barite, Witherite; Sr: Celestite, Strontianite'))
            await page.ev(LOWEST_IN % json.dumps('Ba(mol/kgw)'))
            await page.ev("""((v) => { const s = document.getElementById('rtmPqBatchX'); const o = document.createElement('option');
              o.value = v; s.appendChild(o); s.value = v; s.dispatchEvent(new Event('change', { bubbles: true })); })('')""")
            await batch(BASR_IN)
            got = await page.ev(AGAINST)
            check('the result against a column: against the table\'s pH unless chosen, a series a solid with its legend',
                  got, ['table:pH', ['the table', 'PHREEQC'], False,
                        [['Barite', [7], [1.418e-7]], ['Witherite', [9], [1.775e-5]]],
                        [True, 'linear', 'log', 'pH'], ''])
            await page.ev(LOWEST_IN.replace('rtmPqBatchLowest', 'rtmPqBatchX') % json.dumps('out:pH'))
            await asyncio.sleep(0.3)
            got = await page.ev(AGAINST)
            saved = await saved_blob('[data-on-click="rtm:pqBatchSaveInput"]', '(b) => b.text()')
            svg = await saved_blob('[data-pane="batchx"][data-as="svg"]', '(b) => b.text().then((t) => t.slice(0, 4))')
            check('  against PHREEQC\'s own pH, of the run kept; the choice saved with the input; saved as SVG',
                  [got[0], [[t[0], [round(x, 3) for x in t[1]]] for t in got[3]] if got[3] else got[3],
                   '# Against: out:pH' in saved if isinstance(saved, str) else saved, svg],
                  ['out:pH', [['Barite', [7.0]], ['Witherite', [8.957]]], True, '<svg'])
            await page.ev(SET_SOLIDS % json.dumps(''))
            waters = 'Na\n' + '\n'.join(['1', '2', '3', '4', '5', '6', '7', 'x'] + [str(i) for i in range(8, 21)]) + '\n'
            await page.ev(FEED % (json.dumps('spread.csv'), json.dumps(waters), 'null'))
            await settle(page, f"{BATCH_STATUS}.startsWith('spread.csv: 21 rows and 1 column')", True, tries=40)
            await batch('SOLUTION 1\n units mmol/kgw\n pH 7\n Na {Na}\n Cl {Na}\nSELECTED_OUTPUT 1\n -reset false\n -totals Na\nEND\n')
            got = await page.ev(AGAINST)
            pts = list(zip(got[3][0][1], got[3][0][2])) if got[3] else []
            check('  without solids: against the table\'s Na, each result its Na over 1000; the water with no number counted',
                  [got[0], len(pts), all(abs(y * 1000 / x - 1) < 1e-3 for x, y in pts), got[4], got[5]],
                  ['table:Na', 20, True, [False, 'log', 'log', 'Na'], '1 of 21 rows left out: no number for Na or Na(mol/kgw).'])
            await page.ev(FEED % (json.dumps('draws.csv'), json.dumps('pH\n7\n7.5\n8\n'), 'null'))
            await settle(page, f"{BATCH_STATUS}.startsWith('draws.csv: 3 rows and 1 column')", True, tries=40)
            await field('rtmPqBatchUncertain', 'dNa uniform 1 2')
            await field('rtmPqBatchDraws', '20')
            await field('rtmPqBatchSeed', '7')
            await batch(NA_IN)
            got = await page.ev(AGAINST)
            pts = list(zip(got[3][0][1], got[3][0][2])) if got[3] else []
            check('  with draws: against the value drawn, each run\'s sodium the value it drew',
                  [got[0], got[1], len(pts), all(abs(y * 1000 / x - 1) < 1e-3 for x, y in pts), got[4][3] if got[4] else got[4]],
                  ['drawn:dNa', ['the table', 'drawn', 'PHREEQC'], 60, True, 'dNa, drawn'])
            await field('rtmPqBatchUncertain', '')
            await field('rtmPqBatchDraws', '')
            await field('rtmPqBatchSeed', '')
            # ---- one water in full ----
            # The draws just run: the first row of the table clicked, that water's first draw run again with what PHREEQC
            # prints of it, its species and the sodium it drew; a point of the chart against a column clicked, the second
            # water's fifth draw. Saved as text; closed, the hint back. With solids, the solid that gave the lowest is the
            # one run again; a water every solid of which was refused shows what PHREEQC said and the input as filled.
            LOOK = """[document.getElementById('rtmPqBatchLook').hidden, document.getElementById('rtmPqBatchLookTitle').textContent,
              document.getElementById('rtmPqBatchLookText').textContent, document.getElementById('rtmPqBatchLookHint').hidden]"""
            hint = await page.ev("document.getElementById('rtmPqBatchLookHint').hidden")
            await page.ev("document.querySelector('#rtmPqBatchOut table:last-child tbody tr').querySelector('td').click()")
            await settle(page, "document.getElementById('rtmPqBatchLookTitle').textContent.includes('row 1, draw 1')", True, tries=60)
            first = await page.ev(LOOK)
            drew = await page.ev("document.querySelector('#rtmPqBatchOut table:last-child tbody tr').cells[2].dataset.v")
            check('one water in full: a row clicked, its draw run again, with what PHREEQC prints of it',
                  [hint, first[0], first[1], 'Distribution of species' in first[2], f' Na {drew}' in first[2], first[3]],
                  [False, False, "PHREEQC's output for row 1, draw 1", True, True, True])
            await page.ev("document.getElementById('rtmChartPqBatchX').emit('plotly_click', { points: [{ customdata: ['row 2, draw 5', 1, 4] }] })")
            await settle(page, "document.getElementById('rtmPqBatchLookTitle').textContent.includes('row 2, draw 5')", True, tries=60)
            saved = await saved_blob('[data-on-click="rtm:pqBatchLookSave"]', '(b) => b.text()')
            await page.ev(CLICK % json.dumps('[data-on-click="rtm:pqBatchLookClose"]'))
            closed = await page.ev(LOOK)
            check('  a point of a chart clicked, its water instead; saved as text; closed, the hint back',
                  [(await page.ev("document.getElementById('rtmPqBatchLookTitle').textContent")),
                   'Distribution of species' in saved if isinstance(saved, str) else saved, closed[0], closed[3]],
                  ["PHREEQC's output for row 2, draw 5", True, True, False])
            await page.ev(FEED % (json.dumps('salts.csv'), json.dumps('pH;C;S\n8;10;0,1\n7;0,01;50\nx;1;1\n'), 'null'))
            await settle(page, f"{BATCH_STATUS}.startsWith('salts.csv: 3 rows and 3 columns')", True, tries=40)
            await page.ev(SET_SOLIDS % json.dumps('Calcite, Gypsum'))
            await asyncio.sleep(0.1)
            await batch(SOLIDS_IN)
            await page.ev("document.querySelector('#rtmPqBatchOut table:last-child tbody tr').querySelector('td').click()")
            await settle(page, "document.getElementById('rtmPqBatchLookTitle').textContent.includes('row 1, Calcite')", True, tries=60)
            calcite = await page.ev(LOOK)
            await page.ev("document.querySelectorAll('#rtmPqBatchOut table:last-child tbody tr')[2].querySelector('td').click()")
            await settle(page, "document.getElementById('rtmPqBatchLookTitle').textContent.includes('row 3')", True, tries=60)
            refused = await page.ev(LOOK)
            check('  with solids, the solid that gave the lowest run again; a water every run of which was refused, what PHREEQC said',
                  [calcite[1], 'Phase assemblage' in calcite[2] and 'Calcite' in calcite[2],
                   refused[1], refused[2].startswith('PHREEQC refused this run, and said:'),
                   'Concentration data error for ph' in refused[2], ' pH x' in refused[2]],
                  ["PHREEQC's output for row 1, Calcite", True, "PHREEQC's output for row 3, Calcite", True, True, True])
            await page.ev(CLICK % json.dumps('[data-on-click="rtm:pqBatchLookClose"]'))
            await page.ev(SET_SOLIDS % json.dumps(''))
            # ---- a batch kept beside ----
            # Twenty waters of NaCl run and kept; the same with a millimole of NaCl more by a REACTION run beside it. The
            # spread: the kept curve behind, the legend shown, the numbers in two columns -- the new median 0.0115 beside
            # the kept 0.0105. Against the table's Na, the kept points behind. The line under the bar says what is kept;
            # the workbook has the kept batch's table and input; Forget it, one curve again.
            await page.ev(FEED % (json.dumps('spread.csv'), json.dumps(
                'Na\n' + '\n'.join(['1', '2', '3', '4', '5', '6', '7', 'x'] + [str(i) for i in range(8, 21)]) + '\n'), 'null'))
            await settle(page, f"{BATCH_STATUS}.startsWith('spread.csv: 21 rows and 1 column')", True, tries=40)
            NA1 = 'SOLUTION 1\n units mmol/kgw\n pH 7\n Na {Na}\n Cl {Na}\nSELECTED_OUTPUT 1\n -reset false\n -totals Na\nEND\n'
            await batch(NA1)
            await page.ev(CLICK % json.dumps('#rtmPqBatchKeep'))
            KEPT = """[document.getElementById('rtmPqBatchKeep').textContent, document.getElementById('rtmPqBatchKeep').disabled,
              document.getElementById('rtmPqBatchKept').hidden, document.getElementById('rtmPqBatchKeptText').textContent]"""
            kept_now = await page.ev(KEPT)
            await batch(NA1.replace('SELECTED_OUTPUT', 'REACTION 1\n NaCl 1\n 0.001 moles\nSELECTED_OUTPUT'))
            beside = await page.ev(KEPT)
            SPREADS = """(() => { const p = document.getElementById('rtmChartPqBatch'); const q = document.getElementById('rtmChartPqBatchX');
              return [p.data.slice(0, 2).map((t) => [t.name || '', t.showlegend !== false]), p.layout.showlegend, q.data.map((t) => t.name), q.layout.showlegend,
                [...document.querySelectorAll('#rtmPqBatchStats tbody tr')].map((tr) => [...tr.children].map((c) => c.textContent))]; })()"""
            got = await page.ev(SPREADS)
            sheets = await saved_blob('[data-on-click="rtm:pqBatchSave"][data-as="xlsx"]',
                                      "(b) => JSZip.loadAsync(b).then((z) => z.file('xl/workbook.xml').async('string'))"
                                      ".then((x) => [...x.matchAll(/<sheet [^>]*name=\"([^\"]+)\"/g)].map((m) => m[1]))")
            check('a batch kept beside: kept, then the next drawn beside it, its spread and points, its numbers in a column',
                  [kept_now, beside, got[0], got[1], got[2], got[3], got[4], sheets],
                  [['Kept', True, False, 'This batch is kept: the next one you run is drawn beside it.'],
                   ['Keep this batch', False, False, 'Beside it, the batch kept: 21 rows of spread.csv, with phreeqc.dat.'],
                   [['kept', True], ['this batch', True]], True, ['kept', 'this batch'], True,
                   [['waters', '20', '20'], ['smallest', '0.002', '0.001'], ['5th percentile', '0.00295', '0.00195'],
                    ['median', '0.0115', '0.0105'], ['95th percentile', '0.02005', '0.01905'], ['largest', '0.021', '0.02'],
                    ['left out, refused or with no number', '1', '1']],
                   ['batch', 'spread', 'input', 'kept', 'kept input']])
            await page.ev(CLICK % json.dumps('[data-on-click="rtm:pqBatchForget"]'))
            await asyncio.sleep(0.2)
            forgot = await page.ev(KEPT)
            check('  forgot: the line gone, one curve and one column again',
                  [forgot[2], await page.ev("document.getElementById('rtmChartPqBatch').data.length"),
                   await page.ev("document.querySelector('#rtmPqBatchStats tbody tr').children.length")],
                  [True, 3, 2])
            # ---- the map ----
            # Nine waters on a three by three grid of X(km) and Y(km), their sodium doubling from 1 to 256 mmol/kgw:
            # mapped over X(km) and Y(km) unaided, the same scale both ways, each water at its place with its sodium,
            # the key logarithmic, ticked at 1e-3, 1e-2 and 1e-1. No column for Y: no map. With draws, one point a
            # water, its colour the median of its draws, a click looking at the draw nearest it.
            GRID = 'X(km),Y(km),Na\n' + ''.join(f'{i % 3},{i // 3},{2 ** i}\n' for i in range(9))
            await page.ev(FEED % (json.dumps('grid.csv'), json.dumps(GRID), 'null'))
            await settle(page, f"{BATCH_STATUS}.startsWith('grid.csv: 9 rows and 3 columns')", True, tries=40)
            await batch(NA1)
            MAP = """(() => { const p = document.getElementById('rtmChartPqBatchMap');
              return [document.getElementById('rtmPqBatchMap').hidden, p.hidden, document.getElementById('rtmPqBatchMapX').value,
                document.getElementById('rtmPqBatchMapY').value, p.data ? [p.data[0].x, p.data[0].y,
                p.data[0].customdata.map((c) => Number(c[3].toPrecision(4))), p.data[0].marker.colorbar.tickvals,
                p.data[0].marker.colorbar.title.text, p.layout.yaxis.scaleanchor] : null]; })()"""
            got = await page.ev(MAP)
            check('the map: each water at its place over X(km) and Y(km), coloured by its sodium on a logarithmic key',
                  got, [False, False, 'X(km)', 'Y(km)',
                        [[0, 1, 2, 0, 1, 2, 0, 1, 2], [0, 0, 0, 1, 1, 1, 2, 2, 2],
                         [0.001, 0.002, 0.004, 0.008, 0.016, 0.032, 0.064, 0.128, 0.256], [-3, -2, -1], 'Na(mol/kgw)', 'x']])
            await page.ev("""(() => { const s = document.getElementById('rtmPqBatchMapY'); s.value = '-';
              s.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            await asyncio.sleep(0.2)
            none = await page.ev(MAP)
            await page.ev("""(() => { const s = document.getElementById('rtmPqBatchMapY'); s.value = 'Y(km)';
              s.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            await field('rtmPqBatchUncertain', 'dNa uniform 1 2')
            await field('rtmPqBatchDraws', '5')
            await field('rtmPqBatchSeed', '3')
            await batch(NA_IN.replace(' pH {pH}\n', ' pH 7\n'))
            drawn = await page.ev(MAP)
            await page.ev("document.getElementById('rtmChartPqBatchMap').emit('plotly_click', { points: [{ customdata: document.getElementById('rtmChartPqBatchMap').data[0].customdata[4] }] })")
            await settle(page, "document.getElementById('rtmPqBatchLookTitle').textContent.includes('row 5, draw')", True, tries=60)
            looked = await page.ev("document.getElementById('rtmPqBatchLookTitle').textContent")
            check('  no column for Y, no map; with draws, a point a water, its colour the median of its draws, a click its nearest draw',
                  [none[1], none[3], drawn[1], len(drawn[4][0]) if drawn[4] else drawn[4], drawn[4][4] if drawn[4] else drawn[4],
                   all(1e-3 <= x <= 2e-3 for x in drawn[4][2]) if drawn[4] else drawn[4], looked.startswith("PHREEQC's output for row 5, draw ")],
                  [True, '-', False, 9, 'Na(mol/kgw), the median of its draws', True, True])
            await page.ev(CLICK % json.dumps('[data-on-click="rtm:pqBatchLookClose"]'))
            await field('rtmPqBatchUncertain', '')
            await field('rtmPqBatchDraws', '')
            await field('rtmPqBatchSeed', '')
            # ---- the batch as one page ----
            # The draws batch over the grid just run, saved as a report: its title the table's; what was run -- the
            # values drawn, the draws and seed, the database, the input in full; the spread's numbers and the rows; its
            # three charts live, the spread, against the value drawn and the map; nothing of the page's click handles.
            report = await saved_blob('[data-on-click="rtm:pqBatchReport"]', '(b) => b.text()')
            check('the batch as one page: what was run, the numbers and the rows, its three charts live',
                  [report.count("Plotly.newPlot('chart") if isinstance(report, str) else report,
                   '<title>A batch over grid.csv</title>' in report, '<dt>Uncertain</dt><dd>dNa uniform 1 2</dd>' in report,
                   '<dt>Draws</dt><dd>5 a row, from seed 3</dd>' in report, '<dt>Database</dt><dd>phreeqc.dat</dd>' in report,
                   ' Na {dNa}' in report, 'id="rtmPqBatchStats"' in report, 'data-on-click' not in report,
                   'The map over X(km) and Y(km)' in report, 'against dNa' in report] if isinstance(report, str) else report,
                  [3, True, True, True, True, True, True, True, True, True])
            check('no console errors', page.errors[:3], [])
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})

        # ================= with no Worker at all =================
        page.errors = []
        tid = await page.open(URL, CLEAN + "try{delete window.Worker}catch(e){window.Worker=undefined}")
        try:
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            report = await write_from_example(page)
            check('with no Worker, PHREEQC runs on the page and writes the same model',
                  isinstance(report, str) and report.startswith('Written into the text below: 51 species and 41 '
                                                                'equilibria'), True)
            check('loaded as scripts', await page.ev("typeof createPhreeqc === 'function' && "
                                                     "typeof PHREEQC_DAT === 'string'"), True)
            check('no console errors with no worker', page.errors[:3], [])
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})

        # ================= from the disk =================
        page.errors = []
        tid = await page.open(FILE_URL, CLEAN)
        try:
            await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            report = await write_from_example(page)
            check('opened from the disk, PHREEQC loads and writes the model', isinstance(report, str)
                  and report.startswith('Written into the text below: 51 species'), True)
            check('no console errors from the disk', page.errors[:3], [])
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
