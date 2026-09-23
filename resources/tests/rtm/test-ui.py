#!/usr/bin/env python3
"""rtm.html in a real browser: does the page actually do the thing.

test-model.js proves the mathematics. This proves the wiring — that the text
compiles through the worker, that a run reaches the charts, that the two chart
tabs draw what they claim to, and that a model which does not compile says so
instead of failing silently.

Start the server and the browser as in ../rb/README.md, then

    python3 resources/tests/rtm/test-ui.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import math
import re
import sys
import urllib.request

import websockets

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

URL = 'http://127.0.0.1:8765/rtm.html'

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


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        page = Page(bws)
        asyncio.create_task(page.pump())
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
        await page.call('Page.navigate', {'url': URL}, session=page.sid)
        try:
            await asyncio.sleep(5)
            status = await settle(page, "document.getElementById('rtmStatus')"
                                        ".textContent.slice(0, 9)", 'Compiled:')
            check('the built-in model compiles on load', status, 'Compiled:')
            check('and the panel says what is being solved', await page.ev(
                "document.getElementById('rtmFacts').textContent.startsWith('transport')"), True)
            check('the species picker is filled', await page.ev(
                "document.querySelectorAll('#rtmSeries .rtm-item').length"), 36)
            check('and there is a cell to choose', await page.ev(
                "document.getElementById('rtmCell').options.length"), 20)

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
                " + ':' + s.querySelectorAll('optgroup').length; })()"), '11:5')
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
                "document.getElementById('rtmProfileSpecies').options.length"), 3)
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
            await asyncio.sleep(3)
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
