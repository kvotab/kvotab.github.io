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

CLEAN = ("try{localStorage.removeItem('kvot-rtm-v1');localStorage.removeItem('kvot-rtm-phreeqc-v1');"
         "localStorage.removeItem('kvot.rtm.full')}catch(e){}")

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
            check('a PHREEQC tab beside the others', await page.ev(
                "[...document.querySelector('[role=tablist]').children].map((b) => b.dataset.tab).join(' ')"),
                'time profile gradient phreeqc model jacobian help')
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
            check('in activities that follow the ionic strength, the water in the relations', isinstance(text, str)
                  and 'ACTIVITY = debye-huckel' in text and 'TEMPERATURE = 15' in text
                  and 'H2O <=> OH- + H+,' in text, True)
            status = await settle(page, f"{STATUS}.slice(0, 9)", 'Compiled:')
            check('and it compiles', status, 'Compiled:')
            check('with the relations held, in activities: the model facts say so', await page.ev(
                "/all held throughout the run, 52 species algebraic in every cell · in activities, "
                "Debye–Hückel at 15 °C \\(33 ions\\)/.test(document.getElementById('rtmFacts').textContent)"), True)
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
            await write_from_example(page)
            pairs = await page.ev("document.getElementById('rtmText').value")
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
                "/species on the exchanger X-, Gaines/.test(document.getElementById('rtmFacts').textContent)"), True)
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
                "/in activities, SIT at [0-9.]+ °C \\([0-9]+ ions, [0-9]+ pairs in <SIT>\\)/"
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
                "/in activities, Pitzer at [0-9.]+ °C \\([0-9]+ ions, [0-9]+ parameters in <PITZER>, MacInnes scaled\\)/"
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
                "/in activities, LLNL\u2019s B-dot at [0-9.]+ °C/.test(document.getElementById('rtmFacts').textContent)"), True)
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
                "/the solid solution CaSrCO3 \\(Aragonite, Strontianite\\), a0 3\\.43 and a1 -1\\.82 at 25 °C, a miscibility gap, "
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
                "/the temperature TEMPERATURE = warm\\(t\\): 15 °C at the start, and it goes with time · [0-9]+ log K go with it/"
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
