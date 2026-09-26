#!/usr/bin/env python3
"""FARF31.html in a real browser: does the page do the thing.

test-model.js proves the arithmetic. This proves the wiring:
  - a first visit runs the built-in example in the worker, without a script
    error, and every tab draws; the build stamp is at the foot of Help;
  - FARF31's in.dat, in.par, in.ts and casename31.prm dropped together (a
    trusted drag and drop, Input.dispatchDragEvent) become the case and run;
    the worker's result equals the model run on the page;
  - the release plot, the table and the CSV export; out.ts, out.response and
    the three input files come out, and read back the same;
  - the page's own out.ts dropped back compares to rounding;
  - editing Kd of one uranium isotope moves the other (one FARF31 key), marks
    the result stale; so does Ka, the sorption on the fracture surfaces, which
    shows in the side panel, the Summary and the KA_ lines of in.par; a bad
    series line is refused; a shape builds a series;
  - the (i) panel opens and closes (clicks, not Escape: see the CDP note in
    the README); the dark theme declares its colour scheme;
  - a case file with a sharp front and a long slow tail (tail-30-1 of
    ref/mpmath-ref.json, whose step input once gave an all-zero release) runs
    to its release, and the Summary holds its response to its mass balance;
  - with the reference cases present ($FARF31_REF), their chain case dropped
    on the page gives, at the original program's times, the 40-digit solution
    of ref/mpmath-ref.json, and chain-dense with its out.ts reproduces it.

Start a server in the repository and a headless Chrome (see README.md), then

    F31_HTTP_PORT=8794 F31_CDP_PORT=9294 python3 resources/tests/farf31/test-ui.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import os
import sys
import urllib.request

import websockets

HTTP = int(os.environ.get('F31_HTTP_PORT', '8794'))
CDP = int(os.environ.get('F31_CDP_PORT', '9294'))
URL = f'http://127.0.0.1:{HTTP}/FARF31.html'
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, 'fixture')
REF = os.environ.get('FARF31_REF', os.path.expanduser('~/Downloads/Farf31-SKB-new/reference-cases'))

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
        return await asyncio.wait_for(fut, 120)

    async def pump(self):
        async for raw in self.bws:
            r = json.loads(raw)
            if r.get('method') == 'Runtime.exceptionThrown':
                d = r['params']['exceptionDetails']
                self.errors.append(str(d.get('exception', {}).get('description') or d.get('text', ''))[:300])
            if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                self.pending[r['id']].set_result(r)

    async def ev(self, expr):
        r = await self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True}, session=self.sid)
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:300]
        return res.get('result', {}).get('value')

    async def drop(self, files, x=160, y=120):
        """A trusted file drop at (x, y): the drop box in the settings column."""
        data = {'items': [], 'files': files, 'dragOperationsMask': 1}
        for t in ('dragEnter', 'dragOver', 'drop'):
            await self.call('Input.dispatchDragEvent', {'type': t, 'x': x, 'y': y, 'data': data}, session=self.sid)

    async def click(self, selector):
        box = await self.ev(f"(() => {{ const el = document.querySelector({json.dumps(selector)}); el.scrollIntoView({{ block: 'center' }}); const r = el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()")
        for t in ('mousePressed', 'mouseReleased'):
            await self.call('Input.dispatchMouseEvent', {'type': t, 'x': box[0], 'y': box[1], 'button': 'left', 'clickCount': 1}, session=self.sid)


async def settle(page, expr, want, tries=120, pause=0.25):
    got = None
    for _ in range(tries):
        got = await page.ev(expr)
        if got == want:
            return got
        await asyncio.sleep(pause)
    return got


DONE = "(() => { const s = F31Page.getState(); return !s.running && !!s.result && !s.result.stale; })()"
STATUS = "document.getElementById('f31Status').textContent"

# Downloads: keep the blob and its name instead of saving (see ../rb/README.md).
CAPTURE = """(() => {
  window.__dl = [];
  const make = URL.createObjectURL, click = HTMLAnchorElement.prototype.click;
  URL.createObjectURL = (b) => { window.__blob = b; return 'blob:captured'; };
  URL.revokeObjectURL = () => {};
  HTMLAnchorElement.prototype.click = function () { window.__dl.push({ name: this.download, blob: window.__blob }); };
  window.__restore = () => { URL.createObjectURL = make; HTMLAnchorElement.prototype.click = click; };
  return true;
})()"""


async def main():
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        page = Page(bws)
        asyncio.create_task(page.pump())
        tid = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        page.sid = (await page.call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
        for m in ('Runtime.enable', 'Page.enable', 'Network.enable', 'DOM.enable'):
            await page.call(m, session=page.sid)
        await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
        # Network.enable first, or the cache is not disabled; a reused profile serves stale scripts otherwise
        await page.call('Network.clearBrowserCache', session=page.sid)
        await page.call('Network.setCacheDisabled', {'cacheDisabled': True}, session=page.sid)
        await page.call('Page.addScriptToEvaluateOnNewDocument', {'source': "try{localStorage.removeItem('kvot-farf31-v1');localStorage.setItem('kvot-theme','dark')}catch(e){}"}, session=page.sid)
        await page.call('Page.navigate', {'url': URL}, session=page.sid)
        try:
            # ---- first visit
            check('a first visit runs the built-in example', await settle(page, DONE, True), True)
            check('in the worker', await page.ev("F31Page.getState().result.timing.total > 0 && typeof Worker === 'function'"), True)
            check('no script errors on load', page.errors, [])
            check('the status says done', (await page.ev(STATUS)).startswith('Done in'), True)
            await page.ev("F31Page.showTab('help')")
            check('the build stamp is at the foot of Help', await page.ev("document.getElementById('f31Build').textContent.startsWith('Build ' + F31Page.build)"), True)
            check('Help has the sections the (i) panels link to', await page.ev("['help-model','help-laplace','help-inversion','help-convolution','help-inputs','help-files','help-differences','help-refs'].every((id) => !!document.getElementById(id))"), True)
            check('the dark theme declares its colour scheme', await page.ev("getComputedStyle(document.documentElement).colorScheme"), 'dark')

            # ---- FARF31's files, dropped together
            files = [os.path.join(FIXTURE, f) for f in ('in.ts', 'uchain31.prm', 'in.par', 'in.dat')]
            await page.drop(files)
            await asyncio.sleep(0.3)
            check('the dropped files become the case and run', await settle(page, "(() => { const s = F31Page.getState(); return !s.running && !!s.result && !s.result.stale && s.kase.casename; })()", 'uchain'), 'uchain')
            check('three nuclides, the chain and the sources from in.dat', await page.ev("JSON.stringify(F31Page.getState().kase.nuclides.map((n) => [n.name, n.daughter, n.source]))"), json.dumps([['U238', True, True], ['U234', True, True], ['Th230', False, False]]).replace(' ', ''))
            check('Kd from KDR_U2 on both uranium isotopes', await page.ev("F31Page.getState().kase.nuclides.map((n) => n.kd).join()"), '0.03,0.03,0.3')
            check('the parameters from in.par', await page.ev("(() => { const p = F31Page.getState().kase.params; return [p.tw, p.Pe, p.aw, p.eps, p.de, p.x0].join(); })()"), '60,12,1500,0.004,0.000003,2')
            check('the method from the .prm', await page.ev("F31Page.getState().kase.settings.method"), 'talbot')
            check('the series from in.ts, with its step', await page.ev("F31Page.getState().kase.series.U238.length"), 3)
            check('no script errors after the drop', page.errors, [])
            # the worker's result equals the model on the page
            same = await page.ev("""(() => { const R = F31Page.getState().result; const r2 = Farf31Model.run(R.input);
              if (r2.times.length !== R.times.length) return 'lengths ' + r2.times.length + ' ' + R.times.length;
              let w = 0; for (let i = 0; i < R.out.length; i++) for (let k = 0; k < R.times.length; k++) w = Math.max(w, Math.abs(r2.out[i][k] - R.out[i][k]));
              return w; })()""")
            check('the worker gives what the page gives', same, 0)

            # ---- charts, table, summary
            await page.ev("F31Page.showTab('release')")
            check('the release plot has a line per nuclide', await page.ev("document.getElementById('f31ChartRelease').data.filter((t) => t.mode === 'lines').length"), 3)
            check('on log axes', await page.ev("[document.getElementById('f31ChartRelease').layout.xaxis.type, document.getElementById('f31ChartRelease').layout.yaxis.type].join()"), 'log,log')
            await page.click('#f31Units')
            await page.ev("(() => { const s = document.getElementById('f31Units'); s.value = 'bq'; s.dispatchEvent(new Event('change', { bubbles: true })); return true; })()")
            check('in Bq/a on request', await page.ev("document.getElementById('f31ChartRelease').layout.yaxis.title.text"), 'release (Bq/a)')
            await page.ev("F31Page.showTab('responses')")
            check('the unit responses: a pair per chain member below each source', await page.ev("document.getElementById('f31ChartResp').data.length"), 6)
            await page.ev("F31Page.showTab('table')")
            nrows = await page.ev("document.querySelectorAll('#f31Table tbody tr').length")
            ntimes = await page.ev("F31Page.getState().result.times.length")
            check('the table shows the first 400 times', nrows, min(400, ntimes))
            check('with a column per nuclide and unit', await page.ev("document.querySelectorAll('#f31Table thead th').length"), 7)
            await page.ev("F31Page.showTab('summary')")
            check('the summary lists the peaks', await page.ev("Array.from(document.querySelectorAll('#f31Summary table')).length >= 3"), True)
            check('and the check against de Hoog', await page.ev("document.getElementById('f31Summary').textContent.includes('de Hoog')"), True)

            # ---- downloads
            await page.ev(CAPTURE)
            await page.ev("F31Page.showTab('table')")
            await page.click('[data-pane="table"] [data-kind="csv"]')
            csv = await page.ev("window.__dl[window.__dl.length - 1].blob.text()")
            name = await page.ev("window.__dl[window.__dl.length - 1].name")
            lines = csv.strip().split('\n')
            check('the CSV is named after the case', name, 'uchain_release.csv')
            # text cells go through the site's kvotCsvCell, which quotes them; the case comes first
            head = next(k for k, l in enumerate(lines) if l.startswith('"time (a)"'))
            check('the CSV header', lines[head], '"time (a)","U238 (mol/a)","U238 (Bq/a)","U234 (mol/a)","U234 (Bq/a)","Th230 (mol/a)","Th230 (Bq/a)"')
            check('the CSV starts with the case, Ka and Rf per nuclide', any(l.startswith('"# nuclide"') and '"Ka (m)"' in l and '"Rf"' in l for l in lines[:head]) and sum(1 for l in lines[:head] if l.startswith('"# U2') or l.startswith('"# Th')) == 3, True)
            check('a CSV row per output time', len(lines) - head - 1, ntimes)
            first = [float(x) for x in lines[head + 1].split(',')]
            want = await page.ev("(() => { const R = F31Page.getState().result; return [R.times[0], R.out[0][0], R.bq[0][0]]; })()")
            check('the CSV holds the numbers', first[:3] == want, True)
            await page.click('[data-pane="table"] [data-kind="outts"]')
            outts = await page.ev("window.__dl[window.__dl.length - 1].blob.text()")
            check('out.ts in FARF31\'s layout', outts.split('\n')[2:7], ['  Output migration rate from stream tube:', '  ', '      Time (a)                  Rate', '                       (mol/a)         (Bq/a)', '  Nuclide'])
            check('out.ts reads back with three blocks', await page.ev(f"Object.keys(Farf31IO.readOutTs({json.dumps(outts)})).join()"), 'U238,U234,TH230')
            await page.ev("F31Page.showTab('responses')")
            await page.click('[data-kind="outresponse"]')
            resp = await page.ev("window.__dl[window.__dl.length - 1].blob.text()")
            check('out.response has a block per pair', await page.ev(f"Farf31IO.readOutResponse({json.dumps(resp)}).length"), 6)
            for kind, fname in (('dat', 'in.dat'), ('par', 'in.par'), ('ts', 'in.ts')):
                await page.click(f'[data-on-click="f31:writeFile"][data-kind="{kind}"]')
                check(f'{fname} is written', await page.ev("window.__dl[window.__dl.length - 1].name"), fname)
            rt = await page.ev("""(async () => { const d = window.__dl.slice(-3); const t = await Promise.all(d.map((x) => x.blob.text()));
              const dat = Farf31IO.readDat(t[0]), par = Farf31IO.readPar(t[1]), ts = Farf31IO.readTs(t[2]); Farf31IO.applyPar(dat, par);
              const k = F31Page.getState().kase;
              return JSON.stringify(dat.nuclides.map((n) => [n.name, n.kd, n.daughter, n.source])) === JSON.stringify(k.nuclides.map((n) => [n.name, n.kd, n.daughter, n.source]))
                && par.TW === k.params.tw && JSON.stringify(ts.series.U234) === JSON.stringify(k.series.U234); })()""")
            check('the three input files read back to the same case', rt, True)
            await page.click('[data-on-click="f31:saveCase"]')
            case_json = await page.ev("window.__dl[window.__dl.length - 1].blob.text()")
            check('the case file is JSON of this page', json.loads(case_json)['app'], 'kvot-farf31')
            await page.ev("window.__restore()")

            # ---- the page's own out.ts dropped back: it compares to its rounding
            tmp = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'farf31-test-out.ts')
            with open(tmp, 'w') as f:
                f.write(outts)
            await page.drop([tmp])
            await asyncio.sleep(0.5)
            check('an out.ts dropped is drawn as markers', await settle(page, "F31Page.getState().reference ? F31Page.getState().reference.name : null", 'farf31-test-out.ts'), 'farf31-test-out.ts')
            # out.ts rounds the times to 7 digits as well as the rates: 5e-7 of t, times d ln(rate)/d ln t,
            # which is a few on a rising edge even above 1e-3 of the peak
            worst = await page.ev("Math.max(...F31Page.getState().reference.comparison.map((r) => r.w3))")
            print(f'      the page against its own out.ts, above 1e-3 of each peak: {worst:.2e}')
            check('the page\'s own out.ts agrees with the page to its 7 digits', worst < 1e-5, True)
            os.remove(tmp)

            # ---- editing on the Input tab
            await page.ev("F31Page.showTab('input')")
            await page.ev("(() => { const el = document.querySelector('[data-field=\"kd\"][data-i=\"1\"]'); el.value = '0.07'; el.dispatchEvent(new Event('change', { bubbles: true })); return true; })()")
            check('Kd of U234 moves U238 (one FARF31 key, U2)', await page.ev("F31Page.getState().kase.nuclides.map((n) => n.kd).join()"), '0.07,0.07,0.3')
            check('and marks the result stale', await page.ev("F31Page.getState().result.stale && document.getElementById('f31Status').textContent.includes('press Run')"), True)
            check('the nuclide table has a Ka column', await page.ev("Array.from(document.querySelectorAll('#f31NucTable thead th')).some((th) => th.textContent === 'Ka (m)') && document.querySelectorAll('[data-field=\"ka\"]').length === 3"), True)
            await page.ev("(() => { const el = document.querySelector('[data-field=\"ka\"][data-i=\"1\"]'); el.value = '0.002'; el.dispatchEvent(new Event('change', { bubbles: true })); return true; })()")
            check('Ka of U234 moves U238 too, not Th230', await page.ev("F31Page.getState().kase.nuclides.map((n) => n.ka).join()"), '0.002,0.002,0')
            check('the side panel gives Rf = 1 + Ka aw', await page.ev("document.getElementById('f31KaNote').textContent"), 'Rf = 1 + Ka·aw: U238 4')
            await page.ev(CAPTURE)
            await page.click('[data-on-click="f31:writeFile"][data-kind="par"]')
            par = await page.ev("window.__dl[window.__dl.length - 1].blob.text()")
            await page.ev("window.__restore()")
            check('in.par gets KA_ lines once a Ka is not zero', 'KA_U2 0.002' in par and 'KA_TH 0.0' in par, True)
            await page.ev("(() => { const t = document.getElementById('f31SeriesText'); t.value = '0 1\\n10 2\\n5 3'; t.dispatchEvent(new Event('change', { bubbles: true })); return true; })()")
            check('a series with a time going back is refused', await page.ev("document.getElementById('f31SeriesText').classList.contains('bad') && document.getElementById('f31SeriesNote').textContent.startsWith('Not applied')"), True)
            await page.ev("""(() => { const k = document.getElementById('f31ShapeKind'); k.value = 'pulse'; k.dispatchEvent(new Event('change', { bubbles: true }));
              document.getElementById('f31ShapeA').value = '100'; document.getElementById('f31ShapeB').value = '10'; document.getElementById('f31ShapeC').value = '5'; return true; })()""")
            await page.click('[data-on-click="f31:shapeApply"][data-mode="replace"]')
            check('a pulse shape becomes the series', await page.ev("JSON.stringify(F31Page.getState().kase.series[F31Page.getState().srcSel])"), '[[100,0],[100,0.5],[110,0.5],[110,0]]')
            await page.click('#f31Run')
            check('Run runs the edited case', await settle(page, DONE, True), True)
            check('the model got Ka', await page.ev("F31Page.getState().result.input.nuclides.map((n) => n.ka).join()"), '0.002,0.002,0')
            await page.ev("F31Page.showTab('summary')")
            check('the Summary shows Rf', await page.ev("(() => { const t = document.querySelector('#f31Summary table'); const h = Array.from(t.querySelectorAll('thead th')).map((x) => x.textContent); const k = h.indexOf('Rf'); return k >= 0 ? t.querySelector('tbody tr').children[k].textContent : null; })()"), '4')

            # ---- the (i) panel
            await page.click('[data-info="set:x0"]')
            check('an (i) opens the panel', await settle(page, "document.querySelector('.info-panel-title') ? document.querySelector('.info-panel-title').textContent : null", 'Penetration depth x0'), 'Penetration depth x0')
            await asyncio.sleep(0.4)   # the panel slides in for 140 ms; the × is not under the pointer before
            await page.click('.info-panel-close')
            check('the × closes it', await settle(page, "!document.querySelector('.info-panel')", True), True)
            check('every (i) slot got its button', await page.ev("Array.from(document.querySelectorAll('.f31-info-slot[data-info-key]')).every((s) => s.querySelector('.info-btn'))"), True)

            # ---- a built-in example from the select
            await page.ev("(() => { const s = document.getElementById('f31Example'); s.value = 'radium'; s.dispatchEvent(new Event('change', { bubbles: true })); return true; })()")
            check('an example loads and runs', await settle(page, "(() => { const s = F31Page.getState(); return !s.running && !!s.result && s.kase.casename; })()", 'example3'), 'example3')

            # ---- a sharp front and a long slow tail: a step input once gave an
            #      all-zero release here; the Summary holds every response to
            #      its mass balance
            tail = json.load(open(os.path.join(HERE, 'ref', 'mpmath-ref.json')))['cases']['tail-30-1']['input']
            kase = {'app': 'kvot-farf31', 'casename': 'tail', 'diffusivity': 'SINGLE',
                    'params': dict(tail['params'], de=tail['nuclides'][0]['de'], rho=2700),
                    'nuclides': tail['nuclides'], 'series': tail['series'], 'settings': {}}
            tmp = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'farf31-test-tail.json')
            with open(tmp, 'w') as f:
                json.dump(kase, f)
            await page.drop([tmp])
            await asyncio.sleep(0.3)
            check('the tail case dropped as a case file runs', await settle(page, "(() => { const s = F31Page.getState(); return !s.running && !!s.result && !s.result.stale && s.kase.casename; })()", 'tail'), 'tail')
            os.remove(tmp)
            peak = await page.ev("Math.max(...F31Page.getState().result.out[0])")
            check('its step input gives its release, not zeros (peak near 1 mol/a)', 0.99 < peak < 1.0001, True)
            check('the status line does not warn', await page.ev("document.getElementById('f31Status').className.includes('warn')"), False)
            await page.ev("F31Page.showTab('summary')")
            row = await page.ev("""(() => { const t = Array.from(document.querySelectorAll('#f31Summary table')).find((x) => Array.from(x.querySelectorAll('thead th')).some((h) => h.textContent === 'by the last time'));
              if (!t) return null; const h = Array.from(t.querySelectorAll('thead th')).map((x) => x.textContent); const r = t.querySelector('tbody tr');
              return [r.children[h.indexOf('by the last time')].textContent, r.children[h.indexOf('integral')].textContent, r.className]; })()""")
            check('the Summary gives what leaves by the last time beside the integral, the same', row is not None and row[0] == row[1] and 'f31-bad' not in row[2], True)
            check('and no note of a response that misses', await page.ev("F31Page.getState().result.balance.failed.length"), 0)

            # ---- the reference cases, when they are here
            if os.path.exists(os.path.join(REF, 'chain', 'in.dat')):
                mp = json.load(open(os.path.join(HERE, 'ref', 'mpmath-ref.json')))['cases']['chain']
                await page.drop([os.path.join(REF, 'chain', f) for f in ('in.dat', 'in.par', 'in.ts')])
                await asyncio.sleep(0.3)
                check('the reference chain case dropped runs', await settle(page, "(() => { const s = F31Page.getState(); return !s.running && !!s.result && !s.result.stale && s.kase.nuclides.length; })()", 4), 4)
                worst = 0
                for nuc, vals in mp['outputs'].items():
                    pk = max(v[1] for v in vals)
                    if pk <= 0:
                        continue
                    i = ['Am241', 'Np237', 'U233', 'Th229'].index(nuc)
                    got = await page.ev(f"{json.dumps([v[0] for v in vals])}.map((t) => F31Page.outputAt({i}, t))")
                    for g, (t, v) in zip(got, vals):
                        if v > 1e-6 * pk:
                            worst = max(worst, abs(g - v) / v)
                print(f'      the page against the 40-digit solution at FARF31\'s times: {worst:.2e}')
                check('the page gives the 40-digit solution at FARF31\'s times', worst < 2e-8, True)
                if os.path.exists(os.path.join(REF, 'chain-dense', 'out.ts')):
                    await page.ev("F31Page.showTab('release')")
                    await page.drop([os.path.join(REF, 'chain-dense', f) for f in ('in.dat', 'in.par', 'in.ts')])
                    await asyncio.sleep(0.3)
                    await settle(page, "(() => { const s = F31Page.getState(); return !s.running && !!s.result && !s.result.stale; })()", True)
                    await page.drop([os.path.join(REF, 'chain-dense', 'out.ts')])
                    await asyncio.sleep(0.5)
                    note = await settle(page, "document.querySelectorAll('#f31RefNote li').length", 4)
                    check('the original program\'s out.ts is compared, nuclide by nuclide', note, 4)
                    near = await page.ev("""(() => { const s = F31Page.getState(), R = s.result, d = s.reference.data; let w = 0;
                      R.names.forEach((n, i) => { const pts = d[n.toUpperCase()] || []; const pk = Math.max(0, ...pts.map((p) => p[1]));
                        for (const [t, v] of pts) if (v > 0.5 * pk && pk > 0) w = Math.max(w, Math.abs(F31Page.outputAt(i, t) - v) / v); });
                      return w; })()""")
                    check('and reproduced above half of each peak', near < 5e-3, True)
            else:
                print(f'      (no reference cases in {REF}: skipped)')
            check('no script errors at the end', page.errors, [])
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})
    print(f'\n{checks - len(failures)} of {checks} checks passed' + (f'; FAILED: {"; ".join(failures)}' if failures else '.'))
    sys.exit(1 if failures else 0)


asyncio.run(main())
