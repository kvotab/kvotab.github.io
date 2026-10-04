#!/usr/bin/env python3
"""distributions.html in headless Chrome.

The page loads with its two example distributions drawn and no script error;
every (i) has a topic and no control sits inside a <summary>; a
parameterisation converts without moving the distribution; a bad field is
marked and explained; a change of family keeps the mean and SD; known values
are solved and impossible ones refused; truncation, visibility, adding,
duplicating and removing behave; the Statistics table says "undefined" and
"∞" where it should; a pasted sample is fitted and ranked, its best fit and
an empirical distribution are added, and the diagnostics draw; a table and a
Monte Carlo distribution are made; the Calculate tab's numbers are right; a
random sample goes to the Fit tab; the page comes back after a reload and
starts again on request; the dark theme reaches the charts; and a phone has
no sideways scroll. Then what a review found: known values follow the
distribution after a detour through other numbers, the fit's family choices
are kept per kind, outdated fit results are dimmed and an answer for old
data is dropped, a Monte Carlo draw stopped with the fits is drawn again, a
hypergeometric with a million in its population draws at once, and a
damaged stored state does not stop the page. And the samples: truncation at
percentiles (and switching to values and back keeps the bounds), the Sample
tab drawing every distribution by itself, a seed bringing back the same
draws, Latin hypercube and Sobol means, the power-of-two note, draws in the
chart, CSV and Excel files of them, Fit these, and a large sample that waits
for Draw. Then a shift (the mean moves, the SD stays, a change of family
keeps both, a count takes a whole number only), the numbers under the chart
with the draws' below them, the histograms' bins in the chart and in the
Fit tab, and a Monte Carlo sum by the Sobol sequence.

Start a server on the repository root and headless Chrome first, on ports
8851 and 9351 unless DS_HTTP_PORT and DS_CDP_PORT say otherwise (README.md
has the commands). Exit status 0 when every check passes. With
DS_SHOTS=<folder> it saves screenshots as it goes.
"""
import asyncio
import base64
import json
import math
import os
import sys
import urllib.request

import websockets

HTTP = int(os.environ.get('DS_HTTP_PORT', '8851'))
CDP = int(os.environ.get('DS_CDP_PORT', '9351'))
URL = f'http://127.0.0.1:{HTTP}/distributions.html'
SHOTS = os.environ.get('DS_SHOTS')

# Chrome's rule for a control inside a <summary>: the summaries that break it, or ''.
NO_CONTROL_IN_SUMMARY = (
    "[...document.querySelectorAll('summary')].filter((s) => s.querySelector('a[href], audio[controls], button,"
    " details, embed, iframe, img[usemap], input:not([type=hidden]), label, object[usemap], select, textarea,"
    " video[controls], [tabindex], [contenteditable]')).map((s) => s.textContent.trim()).join(' | ')")

SET = ("(sel, v) => { const e = document.querySelector(sel); if (!e) throw new Error('no ' + sel);"
       " e.value = v; e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true})); }")
CHOOSE = ("(sel, v) => { const e = document.querySelector(sel); if (!e) throw new Error('no ' + sel);"
          " e.value = v; e.dispatchEvent(new Event('change', {bubbles: true})); }")

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


def near(a, b, rel=1e-6):
    try:
        return abs(float(a) - float(b)) <= rel * max(abs(float(b)), 1e-300)
    except (TypeError, ValueError):
        return False


class Page:
    def __init__(self, ws):
        self.ws = ws
        self.n = 0
        self.pending = {}
        self.sid = None
        self.errors = []
        self.scripts = []

    async def call(self, method, params=None, session=True, timeout=120):
        self.n += 1
        i = self.n
        msg = {'id': i, 'method': method, 'params': params or {}}
        if session and self.sid:
            msg['sessionId'] = self.sid
        fut = asyncio.get_event_loop().create_future()
        self.pending[i] = fut
        await self.ws.send(json.dumps(msg))
        return await asyncio.wait_for(fut, timeout)

    async def pump(self):
        async for raw in self.ws:
            r = json.loads(raw)
            if r.get('method') == 'Runtime.exceptionThrown':
                d = r['params']['exceptionDetails']
                self.errors.append(str(d.get('exception', {}).get('description') or d.get('text', ''))[:400])
            if r.get('method') == 'Runtime.consoleAPICalled' and r['params'].get('type') == 'error':
                self.errors.append('console: ' + ' '.join(str(a.get('value', a.get('description', ''))) for a in r['params'].get('args', []))[:400])
            if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                self.pending[r['id']].set_result(r)

    async def ev(self, expr, timeout=120):
        r = await self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True}, timeout=timeout)
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:400]
        return res.get('result', {}).get('value')

    async def until(self, expr, timeout=30):
        for _ in range(int(timeout / 0.1)):
            if await self.ev(expr) is True:
                return True
            await asyncio.sleep(0.1)
        return False

    async def size(self, w, h, mobile=False):
        await self.call('Emulation.setDeviceMetricsOverride', {'width': w, 'height': h, 'deviceScaleFactor': 1, 'mobile': mobile})

    async def on_new_document(self, source):
        for s in self.scripts:
            await self.call('Page.removeScriptToEvaluateOnNewDocument', {'identifier': s})
        r = await self.call('Page.addScriptToEvaluateOnNewDocument', {'source': source})
        self.scripts = [r['result']['identifier']]

    async def load(self, theme='light', clear=False):
        src = f"try{{localStorage.setItem('kvot-theme', {json.dumps(theme)})}}catch(e){{}};"
        if clear:
            src += "try{if(!sessionStorage.getItem('dsCleared')){localStorage.removeItem('kvot-distributions');sessionStorage.setItem('dsCleared','1')}}catch(e){};"
        await self.on_new_document(src)
        await self.call('Page.navigate', {'url': URL})
        await self.until("document.readyState === 'complete' && !!document.querySelector('#dsList .ds-item') && !!document.getElementById('dsPlotTop').data", 40)
        await asyncio.sleep(0.4)

    async def shot(self, name):
        if not SHOTS:
            return
        os.makedirs(SHOTS, exist_ok=True)
        r = await self.call('Page.captureScreenshot', {'format': 'png'})
        with open(os.path.join(SHOTS, name + '.png'), 'wb') as f:
            f.write(base64.b64decode(r['result']['data']))

    async def tab(self, name):
        await self.ev(f"document.querySelector('.ds-tabs [data-tab=\"{name}\"]').click()")
        await asyncio.sleep(0.4)

    async def active_desc(self):
        return await self.ev("(document.querySelector('#dsList .ds-item.active .ds-item-desc') || {}).textContent")

    async def facts(self):
        return await self.ev("(document.getElementById('dsEditorFacts') || {}).innerText")

    async def stat(self, key):
        """A statistic of the selected distribution, from the page's own engine."""
        return await self.ev(f"""(async () => {{
          const ui = await import(document.querySelector('script[type=module][src*="distributions/ui.js"]').src);
          const it = ui.items().find((x) => x.key === ui.app.state.active);
          return it && it.D ? it.D.stats()[{json.dumps(key)}] : null;
        }})()""")


async def main():
    info = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    ws = await websockets.connect(info['webSocketDebuggerUrl'], max_size=2 ** 28)
    p = Page(ws)
    pump = asyncio.ensure_future(p.pump())
    r = await p.call('Target.createTarget', {'url': 'about:blank'}, session=False)
    tid = r['result']['targetId']
    r = await p.call('Target.attachToTarget', {'targetId': tid, 'flatten': True}, session=False)
    p.sid = r['result']['sessionId']
    for m in ('Runtime.enable', 'Page.enable', 'Network.enable'):
        await p.call(m)
    await p.call('Network.setCacheDisabled', {'cacheDisabled': True})
    await p.size(1440, 900)
    try:
        await run(p)
    finally:
        try:
            await p.call('Target.closeTarget', {'targetId': tid}, session=False)
        except Exception:
            pass
        pump.cancel()
        await ws.close()


async def run(p):
    # ---- the first visit -------------------------------------------------------------------
    await p.load(clear=True)
    await p.shot('load')
    check('no script error at load', p.errors, [])
    check('two example distributions', await p.ev("document.querySelectorAll('#dsList .ds-item').length"), 2)
    check('the density chart draws both (a curve each)', await p.ev("document.getElementById('dsPlotTop').data.filter((t) => t.showlegend !== false && t.visible !== 'legendonly').length"), 2)
    check('the cumulative chart below draws too', await p.ev("!!document.getElementById('dsPlotBottom').data && !document.getElementById('dsPlotBottom').hidden"), True)
    audit = await p.ev("JSON.stringify(KvotInfo.audit())")
    a = json.loads(audit)
    check('every (i) slot has a topic', a['noTopic'], [])
    check('every Read more has its Help heading', a['brokenMore'], [])
    check('no (i) inside a summary', a['inSummary'], [])
    check('no control inside a summary', await p.ev(NO_CONTROL_IN_SUMMARY), '')
    check('the example lognormal has median 10', near(await p.stat('median'), 10, 1e-12), True)

    # ---- a parameterisation converts without moving anything ----------------------------------
    await p.ev(f"({CHOOSE})('#dsParam', 'mean-sd')")
    await asyncio.sleep(0.3)
    mean = await p.ev("document.querySelector('[data-path=\"values.mean-sd.mean\"]').value")
    check('mean-sd shows the mean of GM 10, GSD 2', near(mean, 10 * math.exp(math.log(2) ** 2 / 2), 1e-10), True)
    check('and the median is still 10', near(await p.stat('median'), 10, 1e-10), True)
    await p.ev(f"({CHOOSE})('#dsParam', 'gm-gsd')")
    await asyncio.sleep(0.3)
    check('back to GM and GSD: 10', await p.ev("document.querySelector('[data-path=\"values.gm-gsd.gm\"]').value"), '10')

    # ---- a bad field ----------------------------------------------------------------------------
    await p.ev(f"({SET})('[data-path=\"values.gm-gsd.gsd\"]', '0.5')")
    await asyncio.sleep(0.4)
    check('a GSD below 1 is marked', await p.ev("document.querySelector('[data-path=\"values.gm-gsd.gsd\"]').getAttribute('aria-invalid')"), 'true')
    check('and explained', await p.ev("document.getElementById('dsEditorError').textContent"), 'Geometric SD must be greater than 1.')
    check('and the list shows it', await p.ev("document.querySelector('#dsList .ds-item.active').classList.contains('invalid')"), True)
    await p.ev(f"({SET})('[data-path=\"values.gm-gsd.gsd\"]', '2')")
    await asyncio.sleep(0.4)
    check('fixed again', await p.ev("document.getElementById('dsEditorError').hidden"), True)

    # ---- a change of family keeps the mean and SD ------------------------------------------------
    m0 = await p.stat('mean')
    s0 = await p.stat('sd')
    await p.ev(f"({CHOOSE})('#dsFamily', 'weibull')")
    await asyncio.sleep(0.6)
    check('the Weibull starts at the same mean', near(await p.stat('mean'), m0, 1e-8), True)
    check('and the same SD', near(await p.stat('sd'), s0, 1e-8), True)

    # ---- known values -------------------------------------------------------------------------------
    await p.ev(f"({CHOOSE})('#dsParam', 'known')")
    await asyncio.sleep(0.5)
    rows = await p.ev("Array.from(document.querySelectorAll('#dsKnown .ds-known-row select')).map((s) => s.value).join(',')")
    check('known values start with the median and the 95th percentile', rows, 'median,q')
    await p.ev(f"({SET})('[data-path=\"known.0.value\"]', '4')")
    await p.ev(f"({SET})('[data-path=\"known.1.value\"]', '20')")
    await asyncio.sleep(1.0)
    check('solved: the median is 4', near(await p.stat('median'), 4, 1e-9), True)
    q95 = await p.ev("""(async () => { const ui = await import(document.querySelector('script[type=module][src*="distributions/ui.js"]').src);
      const it = ui.items().find((x) => x.key === ui.app.state.active); return it.D.quantile(0.95); })()""")
    check('and the 95th percentile 20', near(q95, 20, 1e-9), True)
    await p.ev(f"({SET})('[data-path=\"known.1.value\"]', '3')")
    await asyncio.sleep(1.0)
    check('a 95th percentile below the median is refused', 'No weibull distribution has exactly these values.' in (await p.ev("document.getElementById('dsEditorError').textContent") or ''), True)
    await p.ev(f"({SET})('[data-path=\"known.1.value\"]', '20')")
    await asyncio.sleep(0.8)
    await p.shot('known')
    # after a detour through other numbers the rows take the distribution as it is
    await p.ev(f"({CHOOSE})('#dsParam', 'shape-scale')")
    await asyncio.sleep(0.4)
    await p.ev(f"({SET})('[data-path=\"values.shape-scale.k\"]', '3')")
    await asyncio.sleep(0.5)
    med = await p.stat('median')
    await p.ev(f"({CHOOSE})('#dsParam', 'known')")
    await asyncio.sleep(0.8)
    check('back on known values after a change, the distribution has not moved', near(await p.stat('median'), med, 1e-9), True)
    check('and the rows show its median, not the 4 typed before', near(await p.ev("document.querySelector('[data-path=\"known.0.value\"]').value"), med, 1e-9), True)
    check('with no error', await p.ev("document.getElementById('dsEditorError').hidden"), True)

    # ---- truncation ----------------------------------------------------------------------------------
    await p.ev("document.getElementById('dsTruncBox').open = true")
    await p.ev(f"({SET})('[data-path=\"trunc.lo\"]', '2')")
    await p.ev(f"({SET})('[data-path=\"trunc.hi\"]', '10')")
    await asyncio.sleep(0.6)
    check('the truncation says how much it keeps', (await p.ev("document.getElementById('dsTruncNote').textContent") or '').startswith('The bounds hold'), True)
    check('the truncated median is inside the bounds', 2 < (await p.stat('median') or 0) < 10, True)
    await p.ev(f"({SET})('[data-path=\"trunc.lo\"]', '')")
    await p.ev(f"({SET})('[data-path=\"trunc.hi\"]', '')")
    await asyncio.sleep(0.4)
    # bounds as percentiles: the quartiles of the distribution before truncation
    quart = await p.ev("""(async () => { const ui = await import(document.querySelector('script[type=module][src*="distributions/ui.js"]').src);
      const it = ui.items().find((x) => x.key === ui.app.state.active); return [it.D.quantile(0.25), it.D.quantile(0.5), it.D.quantile(0.75)]; })()""")
    await p.ev("document.querySelector('input[name=dsTruncBy][value=percentile]').click()")
    await asyncio.sleep(0.4)
    check('the bounds can be percentiles', await p.ev("document.querySelector('#dsTruncBox .ds-field span').textContent"), 'Lower percentile (%)')
    await p.ev(f"({SET})('[data-path=\"trunc.lo\"]', '25')")
    await p.ev(f"({SET})('[data-path=\"trunc.hi\"]', '75')")
    await asyncio.sleep(0.6)
    note = await p.ev("document.getElementById('dsTruncNote').textContent") or ''
    check('the note gives the values the percentiles cut at', note.startswith('The bounds are ') and note.endswith('they hold 50 % of the distribution before truncation.'), True)
    check('cut at the quartiles, the median stays where it was', near(await p.stat('median'), quart[1], 1e-9), True)
    await p.ev("document.querySelector('input[name=dsTruncBy][value=value]').click()")
    await asyncio.sleep(0.5)
    lo_v = await p.ev("document.querySelector('[data-path=\"trunc.lo\"]').value")
    hi_v = await p.ev("document.querySelector('[data-path=\"trunc.hi\"]').value")
    check('switched to values, the bounds are the quartiles', near(lo_v, quart[0], 1e-10) and near(hi_v, quart[2], 1e-10), True)
    await p.ev("document.querySelector('input[name=dsTruncBy][value=percentile]').click()")
    await asyncio.sleep(0.5)
    check('and back to percentiles, 25 and 75', [await p.ev("document.querySelector('[data-path=\"trunc.lo\"]').value"), await p.ev("document.querySelector('[data-path=\"trunc.hi\"]').value")], ['25', '75'])
    await p.ev(f"({SET})('[data-path=\"trunc.lo\"]', '75')")
    await asyncio.sleep(0.5)
    check('a lower percentile above the upper one is refused', 'below the upper one' in (await p.ev("document.getElementById('dsEditorError').textContent") or ''), True)
    await p.ev(f"({SET})('[data-path=\"trunc.lo\"]', '')")
    await p.ev(f"({SET})('[data-path=\"trunc.hi\"]', '')")
    await p.ev("document.querySelector('input[name=dsTruncBy][value=value]').click()")
    await asyncio.sleep(0.4)

    # ---- visibility, adding, duplicating, removing ------------------------------------------------------
    await p.ev("document.querySelectorAll('#dsList .ds-swatch')[1].click()")
    await asyncio.sleep(0.5)
    check('the dot hides B in the chart', await p.ev("document.getElementById('dsPlotTop').data.filter((t) => t.visible === 'legendonly').length"), 1)
    await p.ev("document.querySelectorAll('#dsList .ds-swatch')[1].click()")
    await asyncio.sleep(0.4)
    await p.ev("document.getElementById('dsAdd').click()")
    await asyncio.sleep(0.4)
    await p.ev("document.getElementById('dsDuplicate').click()")
    await asyncio.sleep(0.4)
    letters = await p.ev("Array.from(document.querySelectorAll('#dsList .ds-letter')).map((e) => e.textContent).join('')")
    check('add and duplicate give C and D', letters, 'ABCD')
    await p.ev("document.querySelectorAll('#dsList .ds-remove')[1].click()")
    await asyncio.sleep(0.4)
    letters = await p.ev("Array.from(document.querySelectorAll('#dsList .ds-letter')).map((e) => e.textContent).join('')")
    check('removing B leaves C and D as they were', letters, 'ACD')
    await p.ev("document.getElementById('dsAdd').click()")
    await asyncio.sleep(0.4)
    check('the next one takes the free B', await p.ev("document.querySelector('#dsList .ds-item.active .ds-letter').textContent"), 'B')

    # ---- moments that do not exist ------------------------------------------------------------------------
    await p.ev(f"({CHOOSE})('#dsFamily', 'cauchy')")
    await asyncio.sleep(0.4)
    await p.ev("document.getElementById('dsAdd').click()")
    await asyncio.sleep(0.3)
    await p.ev(f"({CHOOSE})('#dsFamily', 'pareto')")
    await asyncio.sleep(0.4)
    await p.ev(f"({SET})('[data-path=\"values.scale-shape.xm\"]', '1')")
    await p.ev(f"({SET})('[data-path=\"values.scale-shape.alpha\"]', '3')")
    await asyncio.sleep(0.5)
    await p.tab('stats')
    await asyncio.sleep(0.4)
    table = await p.ev("""(() => { const t = document.getElementById('dsStatsTable'); const heads = Array.from(t.tHead.rows[0].cells).map((c) => c.textContent);
      const rows = {}; for (const tr of t.tBodies[0].rows) rows[tr.cells[0].textContent] = Array.from(tr.cells).slice(1).map((c) => c.textContent);
      return JSON.stringify({heads, rows}); })()""")
    t = json.loads(table)
    cauchy = next(i for i, h in enumerate(t['heads'][1:]) if 'Cauchy' in h)
    pareto = next(i for i, h in enumerate(t['heads'][1:]) if 'Pareto' in h)
    check('a Cauchy mean is undefined', t['rows']['Mean'][cauchy], 'undefined')
    check('a Pareto with α = 3 has an infinite skewness', t['rows']['Skewness'][pareto], '∞')
    check('and a finite variance', t['rows']['Variance'][pareto], '0.75')
    await p.shot('stats')

    # ---- fitting ------------------------------------------------------------------------------------------------
    data = await p.ev("""(async () => {
      const m = await import('./resources/js/distributions/dist.js');
      const r = await import('./resources/js/distributions/rng.js');
      const D = m.makeDistribution({family: 'gamma', params: {k: 3, theta: 2}});
      return Array.from(D.sample(400, r.makeRng(11))).map((v) => +v.toPrecision(8)).join('\\n');
    })()""")
    await p.tab('fit')
    await p.ev(f"({SET})('#dsFitText', {json.dumps(data)})")
    ok = await p.until("!document.getElementById('dsFitResults').hidden && document.querySelectorAll('#dsFitTable tbody tr').length > 10", 60)
    check('a pasted sample is fitted by itself', ok, True)
    check('400 values read', await p.ev("document.getElementById('dsFitParse').textContent"), '400 values read.')
    top = await p.ev("Array.from(document.querySelectorAll('#dsFitTable tbody tr')).slice(0, 5).map((tr) => tr.cells[2].textContent).join(' | ')")
    check('the gamma ranks in the top five by AIC', 'Gamma (MLE)' in (top or ''), True)
    check('standard errors are shown', '±' in (await p.ev("document.querySelector('#dsFitTable tbody tr').cells[3].textContent") or ''), True)
    await p.ev(f"({CHOOSE})('#dsFitCriterion', 'ks')")
    await asyncio.sleep(0.4)
    check('ranking by K–S marks its column', await p.ev("document.querySelector('#dsFitTable th.sorted').textContent"), 'K–S D (p)')
    await p.ev("document.querySelector('input[name=dsFitPlot][value=qq]').click()")
    await asyncio.sleep(0.5)
    check('the Q–Q plot draws three fits and the diagonal', await p.ev("document.getElementById('dsFitPlot').data.length"), 4)
    n0 = await p.ev("document.querySelectorAll('#dsList .ds-item').length")
    await p.ev("document.querySelector('[data-on-click=\"ds:fitAddBest\"]').click()")
    await asyncio.sleep(0.5)
    check('the best fit is added', await p.ev("document.querySelectorAll('#dsList .ds-item').length"), n0 + 1)
    check('with its data', await p.ev("""(async () => { const ui = await import(document.querySelector('script[type=module][src*="distributions/ui.js"]').src); return ui.app.activeDist().data.length; })()"""), 400)
    await p.ev("document.querySelector('[data-on-click=\"ds:fitEmpirical\"][data-method=\"kde\"]').click()")
    await asyncio.sleep(0.5)
    check('a kernel density of the data is added', (await p.active_desc() or '').startswith('n = 400'), True)
    await p.ev(f"({CHOOSE})('#dsEmpMethod', 'histogram')")
    await asyncio.sleep(0.4)
    check('its method can change to a histogram', 'Bins' in (await p.facts() or ''), True)
    await p.shot('fit')

    # a CSV of the fits, caught on its way out
    csv = await p.ev("""(() => { let got = null; const orig = URL.createObjectURL; const click = HTMLAnchorElement.prototype.click;
      URL.createObjectURL = (b) => { got = b; return 'blob:x'; }; HTMLAnchorElement.prototype.click = function () {};
      document.querySelector('[data-on-click="ds:fitCsv"]').click();
      URL.createObjectURL = orig; HTMLAnchorElement.prototype.click = click; return got ? got.text() : null; })()""")
    check('the fits save as CSV', (csv or '').lstrip('﻿').startswith('"Rank","Family"'), True)

    # the families chosen are kept for each kind apart
    weibull = "document.querySelector('#dsFitFamilies input[data-family=\"weibull\"]')"
    await p.ev(f"{weibull}.click()")
    await asyncio.sleep(0.3)
    await p.ev("document.querySelector('input[name=dsFitKind][value=discrete]').click()")
    await asyncio.sleep(0.3)
    count = (await p.ev("document.getElementById('dsFitFamiliesCount').textContent") or '').split(' of ')
    check('a continuous family left out leaves every discrete one chosen', len(count) == 2 and count[0] == count[1], True)
    await p.ev("document.querySelector('input[name=dsFitKind][value=auto]').click()")
    await asyncio.sleep(0.3)
    check('and the continuous choice is still there', await p.ev(f"{weibull}.checked"), False)
    await p.ev(f"{weibull}.click()")

    # results that no longer belong to the data are dimmed until the next fit replaces them
    results = "document.getElementById('dsFitResults')"
    await p.until(f"!{results}.hidden && !{results}.classList.contains('stale')", 60)
    await p.ev(f"({SET})('#dsFitText', document.getElementById('dsFitText').value + '\\n7.5')")
    check('changed data dim the old results at once', await p.ev(f"{results}.classList.contains('stale') && {results}.inert && !{results}.hidden"), True)
    ok = await p.until(f"!{results}.classList.contains('stale') && !{results}.inert && /fits? in/.test(document.getElementById('dsFitState').textContent)", 60)
    check('and the new fit replaces them', ok, True)
    check('of 401 values', await p.ev("document.getElementById('dsFitParse').textContent"), '401 values read.')
    # an answer for data that changed while it ran is dropped
    await p.ev(f"({SET})('#dsFitText', {json.dumps(data)})")
    await p.until("/^Fitting/.test(document.getElementById('dsFitState').textContent)", 10)
    await p.ev(f"({SET})('#dsFitText', document.getElementById('dsFitText').value + '\\n9.25\\n0.75')")
    ok = await p.until(f"!{results}.hidden && !{results}.classList.contains('stale') && /fits? in/.test(document.getElementById('dsFitState').textContent)", 60)
    n1 = await p.ev("document.querySelectorAll('#dsList .ds-item').length")
    await p.ev("document.querySelector('[data-on-click=\"ds:fitAddBest\"]').click()")
    await asyncio.sleep(0.5)
    check('the fit on screen is of the data in the box (402 values)', ok and await p.ev("""(async () => { const ui = await import(document.querySelector('script[type=module][src*="distributions/ui.js"]').src); return ui.app.activeDist().data.length; })()""") == 402, True)
    await p.ev("document.querySelector('#dsList .ds-item.active .ds-remove').click()")
    await asyncio.sleep(0.4)
    check('(and that fit removed again)', await p.ev("document.querySelectorAll('#dsList .ds-item').length"), n1)
    # too many to fit by themselves: the results go, and the page says how to fit them
    await p.ev(f"({SET})('#dsFitText', Array.from({{length: 20001}}, (_, i) => String(1 + (i % 97) + i / 1e5)).join('\\n'))")
    await asyncio.sleep(0.5)
    check('20,001 values: no results left from other data', await p.ev(f"{results}.hidden"), True)
    check('and the page says how to fit them', 'press Fit and rank' in (await p.ev("document.getElementById('dsFitState').textContent") or ''), True)
    await p.ev(f"({SET})('#dsFitText', '')")
    await asyncio.sleep(0.4)
    check('no data: no results and no message', await p.ev(f"{results}.hidden && document.getElementById('dsFitState').textContent === ''"), True)
    await p.ev(f"({SET})('#dsFitText', {json.dumps(data)})")
    await p.until(f"!{results}.hidden && !{results}.classList.contains('stale')", 60)

    # ---- a table and a Monte Carlo distribution ---------------------------------------------------------------------
    await p.ev("document.getElementById('dsAdd').click()")
    await asyncio.sleep(0.3)
    await p.ev(f"({CHOOSE})('#dsFamily', 'kind:table')")
    await asyncio.sleep(0.4)
    await p.ev(f"({SET})('#dsTableText', '0 0\\n1 0.5\\n3 1')")
    await asyncio.sleep(0.5)
    check('a cumulative table has the mean of its pieces', near(await p.stat('mean'), 1.25, 1e-12), True)
    await p.ev(f"({SET})('#dsTableText', '0 0\\n1 0.7\\n2 0.6\\n3 1')")
    await asyncio.sleep(0.5)
    check('a decreasing F is refused', await p.ev("document.getElementById('dsEditorError').textContent"), 'F(x) must not decrease as x grows.')
    await p.ev(f"({SET})('#dsTableText', '0 0\\n1 0.5\\n3 1')")
    await asyncio.sleep(0.3)
    await p.tab('calc')
    letters = await p.ev("Array.from(document.querySelectorAll('#dsList .ds-letter')).map((e) => e.textContent).join(',')")
    await p.ev(f"({SET})('#dsCalcMcExpr', 'A + 1')")
    await p.ev("document.querySelector('[data-on-click=\"ds:mcAdd\"]').click()")
    ok = await p.until("!(document.querySelector('#dsList .ds-item.active .ds-item-desc').textContent || '').includes('drawing')", 30)
    desc = await p.active_desc()
    check('a Monte Carlo distribution is drawn', ok and (desc or '').startswith('n = 10,000'), True)
    a_mean = await p.ev("""(async () => { const ui = await import(document.querySelector('script[type=module][src*="distributions/ui.js"]').src); const it = ui.items().find((x) => x.letter === 'A'); return it.D.stats().mean; })()""")
    check('A + 1 has the mean of A plus one', abs((await p.stat('mean') or 0) - (a_mean + 1)) < 0.05 * abs(a_mean + 1), True)
    await p.ev(f"({SET})('#dsMcExpr', 'A * B * Q')")
    await asyncio.sleep(0.6)
    check('an unknown letter is refused', 'There is no distribution “Q”' in (await p.ev("document.getElementById('dsEditorError').textContent") or ''), True)
    await p.ev(f"({SET})('#dsMcExpr', 'A + 1')")
    await asyncio.sleep(0.6)
    # a Monte Carlo draw stopped together with the fits is drawn again
    desc = "(document.querySelector('#dsList .ds-item.active .ds-item-desc').textContent || '')"
    await p.ev(f"({SET})('[data-path=\"mc.n\"]', '400000')")
    await p.until(f"{desc}.includes('drawing')", 10)
    await p.ev("""(async () => { const ui = await import(document.querySelector('script[type=module][src*="distributions/ui.js"]').src); ui.app.stopJobs(); })()""")
    ok = await p.until(f"{desc}.startsWith('n = 400,000')", 60)
    check('a Monte Carlo draw stopped with the fits is drawn again', ok, True)
    await p.ev(f"({SET})('[data-path=\"mc.n\"]', '10000')")
    await p.until(f"{desc}.startsWith('n = 10,000')", 30)

    # a hypergeometric with a million in its population: every curve at once
    await p.tab('chart')
    await p.ev("document.getElementById('dsAdd').click()")
    await asyncio.sleep(0.3)
    await p.ev(f"({CHOOSE})('#dsFamily', 'hypergeometric')")
    await asyncio.sleep(0.4)
    await p.ev(f"({CHOOSE})('#dsBottom', 'hazard')")
    for key, v in (('N', '1000000'), ('K', '400000'), ('n', '200000')):
        await p.ev(f"({SET})('[data-path=\"values.N-K-n.{key}\"]', '{v}')")
    ok = await p.until("(document.getElementById('dsPlotBottom').data || []).some((t) => (t.x || []).length > 1000) && (document.getElementById('dsPlotTop').data || []).some((t) => (t.x || []).length > 1000)", 20)
    check('a hypergeometric with N = 10^6 draws its probabilities and hazard at once', ok, True)
    check('its median is 80,000', near(await p.stat('median'), 80000, 1e-12), True)
    await p.ev(f"({CHOOSE})('#dsBottom', 'cdf')")
    ok = await p.until("(document.getElementById('dsPlotBottom').data || []).some((t) => (t.x || []).length > 1000 && t.line && t.line.shape === 'hv')", 20)
    check('and its cumulative curve', ok, True)
    await p.ev("document.querySelector('#dsList .ds-item.active .ds-remove').click()")
    await asyncio.sleep(0.4)

    # ---- the Calculate tab -----------------------------------------------------------------------------------------------
    await p.ev("document.querySelectorAll('#dsList .ds-item-main')[0].click()")
    await asyncio.sleep(0.4)
    await p.ev(f"({CHOOSE})('#dsFamily', 'normal')")
    await asyncio.sleep(0.4)
    await p.ev(f"({SET})('[data-path=\"values.mu-sigma.mu\"]', '0')")
    await p.ev(f"({SET})('[data-path=\"values.mu-sigma.sigma\"]', '1')")
    await asyncio.sleep(0.5)
    await p.tab('calc')
    await p.ev(f"({SET})('#dsCalcX', '1.959963984540054')")
    await asyncio.sleep(0.6)
    cell = await p.ev("document.querySelector('#dsCalcProbTable tbody tr').cells[1].textContent")
    check('P(X ≤ 1.96) of N(0, 1) is 0.975', cell, '0.975')
    await p.ev(f"({SET})('#dsCalcT', '1')")
    await asyncio.sleep(0.5)
    cell = await p.ev("document.querySelector('#dsCalcTailTable tbody tr').cells[2].textContent")
    check('E[X | X > 1] of N(0, 1) is φ(1)/S(1)', near(cell, 1.5251352761609809, 1e-5), True)
    await p.shot('calc')

    # ---- samples --------------------------------------------------------------------------------------------------------
    table = "document.getElementById('dsSampleTable')"
    drawn = f"!/drawing|not drawn/.test({table}.innerText) && {table}.querySelectorAll('tbody tr').length > 5"
    await p.tab('sample')
    ok = await p.until(drawn, 40)
    check('the Sample tab draws every distribution by itself', ok, True)
    cols = await p.ev(f"{table}.tHead.rows[0].cells.length - 1")
    check('a column for each distribution', cols, await p.ev("document.querySelectorAll('#dsList .ds-item').length"))
    check('1,000 draws of A', await p.ev(f"{table}.tBodies[0].rows[0].cells[1].textContent"), '1,000')
    first = "document.querySelector('#dsSamplePreview tbody tr').cells[1].textContent"
    f1 = await p.ev(first)
    await p.ev(f"({SET})('#dsSampleSeed', '2')")
    await p.until(f"{first} !== {json.dumps(f1)}", 20)
    f2 = await p.ev(first)
    await p.ev(f"({SET})('#dsSampleSeed', '1')")
    await p.until(f"{first} === {json.dumps(f1)}", 20)
    check('another seed draws others, and the seed again the same draws', f2 != f1 and await p.ev(first) == f1, True)
    mean_a = f"""(async () => {{ const ui = await import(document.querySelector('script[type=module][src*="distributions/ui.js"]').src);
      const t = {table}; const cell = t.tBodies[0].rows[1].cells[1]; return [parseFloat(cell.firstChild.textContent), parseFloat(cell.lastChild.textContent)]; }})()"""
    await p.ev(f"({CHOOSE})('#dsSampleScheme', 'lhs')")
    await asyncio.sleep(0.4)
    await p.until(drawn, 20)
    m = await p.ev(mean_a)
    check('a Latin hypercube of N(0, 1): mean within 0.002 of 0', abs(m[0]) < 0.002 and m[1] == 0, True)
    await p.ev(f"({CHOOSE})('#dsSampleScheme', 'sobol')")
    await asyncio.sleep(0.4)
    await p.until(drawn, 20)
    check('a Sobol sample of 1,000 notes that a power of two is balanced', 'power of two' in (await p.ev("document.getElementById('dsSampleNote').textContent") or ''), True)
    await p.ev(f"({SET})('#dsSampleN', '1024')")
    await asyncio.sleep(0.4)
    await p.until(drawn + f" && {table}.tBodies[0].rows[0].cells[1].textContent === '1,024'", 20)
    check('and 1,024 draws need no note', await p.ev("document.getElementById('dsSampleNote').hidden"), True)
    m = await p.ev(mean_a)
    check('a Sobol sample of N(0, 1): mean within 0.002 of 0', abs(m[0]) < 0.002, True)
    check('the K–S row gives D and its p-value', bool(__import__('re').match(r'^[0-9.e−-]+ \([0-9.]+\)$', await p.ev(f"{table}.tBodies[0].rows[{table}.tBodies[0].rows.length - 1].cells[1].textContent") or '')), True)
    await p.ev("document.getElementById('dsSampleShow').click()")
    await asyncio.sleep(0.4)
    check('show in the chart ticks the chart\'s samples box', await p.ev("document.getElementById('dsShowSamples').checked"), True)
    await p.tab('chart')
    await asyncio.sleep(0.8)
    check('the chart draws the samples, dotted', await p.ev("document.getElementById('dsPlotTop').data.filter((t) => t.name === 'sample' && t.line && t.line.dash === 'dot').length > 0"), True)
    check('and beside the cumulative curves', await p.ev("document.getElementById('dsPlotBottom').data.some((t) => t.name === 'sample')"), True)
    await p.ev("document.getElementById('dsShowSamples').click()")
    await asyncio.sleep(0.5)
    check('the chart\'s box takes them away again', await p.ev("document.getElementById('dsPlotTop').data.some((t) => t.name === 'sample')"), False)
    await p.tab('sample')
    await asyncio.sleep(0.4)
    csv = await p.ev("""(() => { let got = null; const orig = URL.createObjectURL; const click = HTMLAnchorElement.prototype.click;
      URL.createObjectURL = (b) => { got = b; return 'blob:x'; }; HTMLAnchorElement.prototype.click = function () {};
      document.querySelector('[data-on-click="ds:sampleCsv"]').click();
      URL.createObjectURL = orig; HTMLAnchorElement.prototype.click = click; return got ? got.text() : null; })()""")
    lines = (csv or '').lstrip('\ufeff').strip().split('\n')
    check('the draws save as CSV: the names, then 1,024 rows', len(lines) == 1025 and lines[0].startswith('"A: '), True)
    xlsx = await p.ev("""(async () => {
      const orig = URL.createObjectURL; const click = HTMLAnchorElement.prototype.click;
      let resolve; const got = new Promise((r) => { resolve = r; });
      URL.createObjectURL = (b) => { resolve(b); return 'blob:x'; };
      HTMLAnchorElement.prototype.click = function () {};
      document.querySelector('[data-on-click="ds:sampleExcel"]').click();
      const blob = await Promise.race([got, new Promise((r) => setTimeout(() => r(null), 30000))]);
      URL.createObjectURL = orig; HTMLAnchorElement.prototype.click = click;
      if (!blob) return null;
      const zip = await JSZip.loadAsync(blob);
      const sheet = await zip.file('xl/worksheets/sheet1.xml').async('string');
      return [blob.size, (sheet.match(/<row /g) || []).length];
    })()""", timeout=90)
    check('and as an Excel workbook: a header and 1,024 rows', isinstance(xlsx, list) and xlsx[1] == 1025, True)
    await p.ev(f"({CHOOSE})('#dsSampleFitWhich', document.querySelector('#dsSampleFitWhich').options[0].value)")
    await p.ev("document.querySelector('[data-on-click=\"ds:sampleToFit\"]').click()")
    await asyncio.sleep(0.6)
    check('Fit these takes a sample to the Fit tab', await p.ev("document.getElementById('dsFitParse').textContent"), '1,024 values read.')
    await p.tab('sample')
    await p.ev("document.querySelector('[data-on-click=\"ds:sampleNone\"]').click()")
    await asyncio.sleep(0.3)
    await p.ev("document.querySelectorAll('#dsSampleWhich input')[0].click()")
    await p.ev("document.querySelectorAll('#dsSampleWhich input')[1].click()")
    await p.ev(f"({CHOOSE})('#dsSampleScheme', 'random')")
    await p.ev(f"({SET})('#dsSampleN', '150000')")
    await asyncio.sleep(0.8)
    check('300,000 draws wait for Draw', 'press Draw' in (await p.ev("document.getElementById('dsSampleNote').textContent") or ''), True)
    await p.ev("document.getElementById('dsSampleDraw').click()")
    ok = await p.until(drawn + f" && {table}.tBodies[0].rows[0].cells[1].textContent === '150,000'", 60)
    check('and Draw takes them', ok, True)
    await p.shot('sample')
    await p.ev(f"({SET})('#dsSampleN', '1000')")
    await p.ev("document.querySelector('[data-on-click=\"ds:sampleAll\"]').click()")
    await asyncio.sleep(0.4)

    # ---- a Monte Carlo sum by the Sobol sequence ------------------------------------------------------------------------
    ui = "await import(document.querySelector('script[type=module][src*=\"distributions/ui.js\"]').src)"
    # what the engine itself draws for A * 2 + 1 with seed 1, by Sobol and at random
    means = await p.ev(f"""(async () => {{ const ui = {ui}; const mc = await import('./resources/js/distributions/mc.js');
      const spec = ui.app.derived(ui.items()[0].key).spec;
      const m = (scheme) => {{ const r = mc.runMonteCarlo({{ A: spec }}, 'A * 2 + 1', 10000, 1, scheme); return r.values.reduce((x, y) => x + y, 0) / r.values.length; }};
      return [m('sobol'), m('random')]; }})()""")
    await p.tab('calc')
    await p.ev(f"({SET})('#dsCalcMcExpr', 'A * 2 + 1')")
    await p.ev(f"({CHOOSE})('#dsCalcMcScheme', 'sobol')")
    await p.ev("document.querySelector('[data-on-click=\"ds:mcAdd\"]').click()")
    ok = await p.until("!(document.querySelector('#dsList .ds-item.active .ds-item-desc').textContent || '').includes('drawing')", 30)
    check('a Monte Carlo expression drawn by the Sobol sequence', ok and await p.ev("document.getElementById('dsMcScheme').value") == 'sobol', True)
    got = await p.stat('mean')
    check('its draws are the Sobol draws, not random ones', near(got, means[0], 1e-12) and not near(got, means[1], 1e-6), True)
    await p.ev("document.querySelector('#dsList .ds-item.active .ds-remove').click()")
    await asyncio.sleep(0.4)

    # ---- a shift ------------------------------------------------------------------------------------------------------------
    await p.tab('chart')
    await p.ev("document.querySelectorAll('#dsList .ds-item-main')[0].click()")
    await asyncio.sleep(0.4)
    m0 = await p.stat('mean')
    s0 = await p.stat('sd')
    await p.ev("document.getElementById('dsShiftBox').open = true")
    await p.ev(f"({SET})('[data-path=\"shift\"]', '5')")
    await asyncio.sleep(0.6)
    check('a shift of 5 moves the mean by 5', near(await p.stat('mean'), m0 + 5, 1e-12), True)
    check('and leaves the SD as it was', near(await p.stat('sd'), s0, 1e-12), True)
    check('the list says it is shifted', 'shifted by 5' in (await p.active_desc() or ''), True)
    fam0 = await p.ev("document.getElementById('dsFamily').value")
    await p.ev(f"({CHOOSE})('#dsFamily', 'gamma')")
    await asyncio.sleep(0.6)
    check('a change of family keeps the shift, the mean and the SD', await p.ev("document.querySelector('[data-path=\"shift\"]').value") == '5' and near(await p.stat('mean'), m0 + 5, 1e-8) and near(await p.stat('sd'), s0, 1e-8), True)
    await p.tab('stats')
    await asyncio.sleep(0.3)
    row = await p.ev("(() => { const tr = Array.from(document.querySelectorAll('#dsStatsTable tbody tr')).find((r) => r.cells[0].textContent === 'Shift'); return tr ? tr.cells[1].textContent : null; })()")
    check('the Statistics tab has a row for the shift', row, '5')
    await p.tab('chart')
    await p.ev("document.getElementById('dsAdd').click()")
    await asyncio.sleep(0.3)
    await p.ev(f"({CHOOSE})('#dsFamily', 'poisson')")
    await asyncio.sleep(0.4)
    await p.ev("document.getElementById('dsShiftBox').open = true")
    await p.ev(f"({SET})('[data-path=\"shift\"]', '0.5')")
    await asyncio.sleep(0.5)
    check('a count refuses a shift that is not whole', 'whole number' in (await p.ev("document.getElementById('dsEditorError').textContent") or ''), True)
    await p.ev(f"({SET})('[data-path=\"shift\"]', '-1')")
    await asyncio.sleep(0.5)
    info = await p.ev(f"(async () => {{ const ui = {ui}; const it = ui.items().find((x) => x.key === ui.app.state.active); return [it.D.support[0], it.D.params.lambda, it.D.stats().mean]; }})()")
    check('and takes a whole one: Poisson(λ) − 1 starts at −1, its mean λ − 1', await p.ev("document.getElementById('dsEditorError').hidden") and info[0] == -1 and near(info[2], info[1] - 1, 1e-12), True)
    await p.ev("document.querySelector('#dsList .ds-item.active .ds-remove').click()")
    await asyncio.sleep(0.4)

    # ---- the numbers under the chart, with the draws' -------------------------------------------------------------------
    below = "document.getElementById('dsBelowTable')"
    shown = await p.ev(f"(async () => {{ const ui = {ui}; return ui.items().filter((it) => it.visible && it.D).length; }})()")
    check('under the chart, a row for each distribution it shows', await p.ev(f"{below}.tBodies[0].rows.length"), shown)
    active_name = await p.ev(f"(async () => {{ const ui = {ui}; return ui.items().find((x) => x.key === ui.app.state.active).name; }})()")
    check('the selected one in bold', await p.ev(f"{below}.querySelector('tr.active') && {below}.querySelector('tr.active').cells[0].textContent"), active_name)
    await p.ev("document.getElementById('dsShowSamples').click()")
    ok = await p.until(f"{below}.querySelectorAll('tr.ds-below-draws').length === {shown}", 40)
    missing = await p.ev(f"""(() => {{ const rows = Array.from({below}.tBodies[0].rows); return rows.filter((r, i) => !r.classList.contains('ds-below-draws') && !(rows[i + 1] && rows[i + 1].classList.contains('ds-below-draws'))).map((r) => r.cells[0].textContent).join(' | '); }})()""")
    check('with samples shown, a row for each one\'s draws', missing, '')
    check('which says how many and how', bool(__import__('re').match(r'^its 1,000 draws \(', await p.ev(f"{below}.querySelector('tr.ds-below-draws').cells[0].textContent") or '')), True)

    # ---- the histograms' bins ------------------------------------------------------------------------------------------------
    await p.ev(f"({CHOOSE})('#dsBins', 'count')")
    await p.ev(f"({SET})('#dsBinsValue', '10')")
    await asyncio.sleep(0.6)
    check('ten bins: each histogram a stepped line of 22 points', await p.ev("document.getElementById('dsPlotTop').data.filter((t) => t.name === 'sample' && t.fill === 'tozeroy').every((t) => t.x.length === 22) && document.getElementById('dsPlotTop').data.some((t) => t.name === 'sample')"), True)
    await p.ev(f"({CHOOSE})('#dsBins', 'width')")
    await p.ev(f"({SET})('#dsBinsValue', '2')")
    await asyncio.sleep(0.6)
    check('a width of 2: the edges at its multiples', await p.ev("document.getElementById('dsPlotTop').data.filter((t) => t.name === 'sample' && t.fill === 'tozeroy').every((t) => Math.abs(t.x[0] / 2 - Math.round(t.x[0] / 2)) < 1e-9)"), True)
    await p.ev(f"({CHOOSE})('#dsBins', 'fd')")
    await p.ev("document.getElementById('dsShowSamples').click()")
    await asyncio.sleep(0.4)
    await p.tab('fit')
    await p.until("!document.getElementById('dsFitResults').hidden", 30)
    await p.ev("document.querySelector('input[name=dsFitPlot][value=pdf]').click()")
    await p.ev(f"({CHOOSE})('#dsFitBins', 'count')")
    await p.ev(f"({SET})('#dsFitBinsValue', '8')")
    await asyncio.sleep(0.6)
    check('the Fit tab\'s histogram has bins of its own: eight, 18 points', await p.ev("(document.getElementById('dsFitPlot').data.find((t) => t.name === 'data' && t.fill === 'tozeroy') || {x: []}).x.length"), 18)
    await p.ev(f"({CHOOSE})('#dsFitBins', 'fd')")

    # ---- a reload, and starting again -------------------------------------------------------------------------------------
    names = await p.ev("Array.from(document.querySelectorAll('#dsList .ds-item-name')).map((e) => e.textContent).join(' | ')")
    await asyncio.sleep(0.8)
    await p.load()
    check('a reload brings the distributions back', await p.ev("Array.from(document.querySelectorAll('#dsList .ds-item-name')).map((e) => e.textContent).join(' | ')"), names)
    check('no script error after the reload', p.errors, [])
    await p.ev("window.confirm = () => true")
    await p.tab('help')
    await p.ev("document.querySelector('[data-on-click=\"ds:reset\"]').click()")
    await asyncio.sleep(0.6)
    check('start again leaves the two examples', await p.ev("document.querySelectorAll('#dsList .ds-item').length"), 2)
    check('the Help lists every family', await p.ev("document.querySelectorAll('#dsHelpFamilies .ds-fam').length"), 38)

    # a damaged stored state is repaired, not left to stop the page
    damaged = json.dumps({
        'v': 1, 'active': 99, 'tab': 'nope', 'sideWidth': 'wide', 'chart': 'x',
        'stats': {'digits': 1e9, 'percentiles': {}},
        'fit': {'families': ['gamma'], 'kind': 42, 'text': 5, 'column': -3, 'plot': {}, 'mle': 'yes'},
        'calc': {'x': {}, 'cover': 95, 'shade': 'no', 'cx': 4},
        'sample': {'n': {}, 'scheme': 'bogus', 'seed': [], 'skip': 'x'},
        'dists': [
            {'slot': 0, 'id': 7, 'kind': 'family', 'family': 'nonexistent', 'values': 5, 'known': 'abc', 'trunc': 7, 'name': {}, 'mc': [], 'emp': None, 'data': 'x'},
            {'slot': 1, 'kind': 'mc', 'mc': {'expr': {'a': 1}, 'n': [], 'seed': None}},
            {'slot': 1, 'kind': 'family', 'family': 'gamma'},
            'not a distribution',
        ]})
    await p.on_new_document("try{localStorage.setItem('kvot-theme','light');if(!sessionStorage.getItem('dsDamaged')){localStorage.setItem('kvot-distributions'," + json.dumps(damaged) + ");sessionStorage.setItem('dsDamaged','1')}}catch(e){};")
    before = len(p.errors)
    await p.call('Page.navigate', {'url': URL})
    ok = await p.until("document.readyState === 'complete' && !!document.querySelector('#dsList .ds-item')", 40)
    await asyncio.sleep(0.8)
    check('a damaged stored state does not stop the page', ok and p.errors[before:] == [], True)
    check('its two distributions with a place are repaired', await p.ev("document.querySelectorAll('#dsList .ds-item').length"), 2)
    check('the unknown family is a normal', await p.ev("document.querySelector('#dsList .ds-item .ds-item-name').textContent.includes('Normal')"), True)
    check('the settings are their defaults', await p.ev("JSON.stringify([document.getElementById('dsDigits').value, document.getElementById('dsCalcX').value, document.getElementById('dsTop').value])"), '["5","","pdf"]')
    check('and the chart draws', await p.ev("!!document.getElementById('dsPlotTop').data"), True)
    await p.ev("window.confirm = () => true")
    await p.tab('help')
    await p.ev("document.querySelector('[data-on-click=\"ds:reset\"]').click()")
    await asyncio.sleep(0.6)

    # ---- the dark theme reaches the charts ---------------------------------------------------------------------------------
    await p.load(theme='dark')
    await p.tab('chart')
    bg = await p.ev("document.getElementById('dsPlotTop').layout.paper_bgcolor")
    want = await p.ev("getComputedStyle(document.documentElement).getPropertyValue('--bg-primary').trim()")
    check('the chart is drawn on the dark background', bg, want)
    check('in the dark steps of the palette', await p.ev("document.getElementById('dsPlotTop').data.find((t) => t.showlegend !== false).line.color"), '#3987e5')
    await p.shot('dark')

    # ---- a phone ------------------------------------------------------------------------------------------------------------
    await p.size(390, 664, mobile=True)
    await p.load(theme='light')
    check('no sideways scroll on a phone', await p.ev("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), True)
    # iOS zooms into a text field or a select under 16px, not into a box or a radio button
    small = await p.ev("Array.from(document.querySelectorAll('#dsEditor input:not([type=checkbox]):not([type=radio]), #dsEditor select, #dsEditor textarea')).filter((e) => e.offsetParent && parseFloat(getComputedStyle(e).fontSize) < 16).length")
    check('no field under 16px on a phone (iOS zoom)', small, 0)
    await p.tab('sample')
    check('the Sample tab has no sideways scroll on a phone', await p.ev("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), True)
    small = await p.ev("Array.from(document.querySelectorAll('#pane-sample input:not([type=checkbox]), #pane-sample select')).filter((e) => e.offsetParent && parseFloat(getComputedStyle(e).fontSize) < 16).length")
    check('nor a field under 16px there', small, 0)
    small = await p.ev("Array.from(document.querySelectorAll('#pane-chart select, #pane-chart input[type=text], #pane-fit select, #pane-fit input[type=text], #pane-calc select, #pane-calc input[type=text]')).filter((e) => parseFloat(getComputedStyle(e).fontSize) < 16).map((e) => e.id || e.name).join(', ')")
    check('nor in the chart, fit and calculate tabs (the bins, the schemes)', small, '')
    await p.shot('phone')
    await p.size(1440, 900)
    check('no script error at all', p.errors, [])


if __name__ == '__main__':
    asyncio.run(main())
    print(f'\n{checks - len(failures)} of {checks} checks passed')
    sys.exit(1 if failures else 0)
