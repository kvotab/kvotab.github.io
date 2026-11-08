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
            check('fixed at this water: conditional constants, the water left out of the relations',
                  isinstance(fixed, str) and 'ACTIVITY' not in fixed and ' <=> OH- + H+,' in fixed
                  and 'logK = -14.1398953203' in fixed, True)
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
