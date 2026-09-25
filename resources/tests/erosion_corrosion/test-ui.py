#!/usr/bin/env python3
"""erosion_corrosion.html in a real browser: does the page do the thing.

test-model.js proves the arithmetic. This proves the wiring: that the page
loads without a script error, that the panel is built from the catalogue,
that SKB's code test case, dropped on the panel with the SR-Site settings,
runs and puts the documented numbers in the summary, that every tab draws,
that a parameter change re-runs, and that a dropped CSV of unknown shape is
refused with a message rather than a silence.

The test file is SKB's and not in the repository: the checks that need it
drop the local copy that make-local-fixtures.py writes, and are skipped
without it.

Start the server and the browser as in ../rb/README.md (other ports with
EC_HTTP_PORT and EC_CDP_PORT), then

    python3 resources/tests/erosion_corrosion/test-ui.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import os
import sys
import urllib.request

import websockets

HTTP = int(os.environ.get('EC_HTTP_PORT', '8765'))
CDP = int(os.environ.get('EC_CDP_PORT', '9222'))
URL = f'http://127.0.0.1:{HTTP}/erosion_corrosion.html'
CASE = './resources/tests/erosion_corrosion/local/TestCaseHydro_2_0.csv'
# Drops the local copy of the test file on the panel, under the given name.
DROP_CASE = """(async (name) => {
  const text = await (await fetch(%s)).text();
  const f = new File([text], name, { type: 'text/csv' });
  const dt = new DataTransfer(); dt.items.add(f);
  document.querySelector('.ec').dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
})(%%s)""" % json.dumps(CASE)

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
        r = await self.call('Runtime.evaluate',
                            {'expression': expr, 'returnByValue': True, 'awaitPromise': True},
                            session=self.sid)
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:300]
        return res.get('result', {}).get('value')


async def settle(page, expr, want, tries=60, pause=0.5):
    got = None
    for _ in range(tries):
        got = await page.ev(expr)
        if got == want:
            return got
        await asyncio.sleep(pause)
    return got


async def status_starts(page, prefix):
    return await settle(page, f"document.getElementById('ecStatus').textContent.startsWith({json.dumps(prefix)})", True)


async def main():
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        page = Page(bws)
        asyncio.create_task(page.pump())
        tid = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        page.sid = (await page.call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
        await page.call('Runtime.enable', session=page.sid)
        await page.call('Page.enable', session=page.sid)
        await page.call('Emulation.setDeviceMetricsOverride',
                        {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
        await page.call('Network.setCacheDisabled', {'cacheDisabled': True}, session=page.sid)
        # A clean slate: the page keeps its settings in localStorage.
        await page.call('Page.addScriptToEvaluateOnNewDocument',
                        {'source': "try{localStorage.removeItem('kvot-ec-v1')}catch(e){}"}, session=page.sid)
        await page.call('Page.navigate', {'url': URL}, session=page.sid)
        try:
            await asyncio.sleep(3)
            check('the page loads and asks for hydro data', await status_starts(page, 'Load hydro data'), True)
            check('no script errors on load', page.errors, [])
            n_params = await page.ev("ECModel.PARAMS.length")
            check('the panel has a control per catalogue parameter',
                  await page.ev("document.querySelectorAll('#ecParamSections [data-key]:not(label):not(div)').length"), n_params)
            check('and a section per group with parameters',
                  await page.ev("document.querySelectorAll('#ecParamSections details.ec-sec').length"), 6)
            check('the parameter reference on the Help tab is filled',
                  await page.ev("document.querySelectorAll('#ecParamRef tbody tr').length") > n_params, True)
            check('the sulphide note describes HSForsmark',
                  await page.ev("document.getElementById('ecHsNote').textContent.startsWith('46 values')"), True)

            # --- the code test case ----------------------------------------
            # SKB's test file (SKBdoc 1895160) is not part of the page: set the
            # SR-Site settings on the panel and drop the local copy.
            have_case = await page.ev(f"fetch({json.dumps(CASE)}, {{ method: 'HEAD' }}).then((r) => r.ok, () => false)")
            if not have_case:
                print('skip  the code test case and everything that needs hydro data: no local copy of the test file'
                      ' (python3 resources/tests/erosion_corrosion/make-local-fixtures.py <folder>)')
            else:
                await page.ev("(() => { const s = document.querySelector('select[data-key=\"buffModel\"]'); s.value = 'OldKTH';"
                              " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
                await page.ev("(() => { const el = document.querySelector('input[data-key=\"fTDilute\"]'); el.value = '0.25';"
                              " el.dispatchEvent(new Event('change', { bubbles: true })); })()")
                await page.ev("(() => { const s = document.getElementById('ecHsTable'); s.value = 'HSTest';"
                              " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
                await page.ev(DROP_CASE % json.dumps('TestCaseHydro_2_0.csv'))
                check('the dropped test case runs', await status_starts(page, 'Done'), True)
                check('with the SR-Site settings applied',
                      await page.ev("ECPage.getState().params.buffModel + ':' + ECPage.getState().params.fTDilute + ':' + ECPage.getState().hs.table"),
                      'OldKTH:0.25:HSTest')
                check('the buffer-model control shows it',
                      await page.ev("document.querySelector('select[data-key=\"buffModel\"]').value"), 'OldKTH')
                check('and is marked as changed from the default',
                      await page.ev("document.querySelector('.ec-row[data-key=\"buffModel\"]').classList.contains('changed')"), True)
                key = await page.ev("JSON.stringify(ECPage.getState().result.results[0].key)")
                k = json.loads(key)
                check('35 failure times', k['nFailRows'], 35)
                check('17 rejected', k['nReject'], 17)
                check('corrected mean 3.5', k['meanFailedCorrected'], 3.5)
                check('four advective positions', k['nAdvAtLim'], 4)
                check('the file list shows one realisation with 6017 holes',
                      await page.ev("document.querySelector('#ecFiles .ec-file-meta').textContent.includes('6,017 holes')"), True)
                check('the summary cards show the corrected mean',
                      await page.ev("document.querySelector('#ecSummary .ec-card-value').textContent"), '3.5')
                check('the key-output table has a row per key output',
                      await page.ev("document.querySelectorAll('#ecSummary table.ec-key tbody tr').length"), 17)
                check('the status says 35 failure times',
                      await page.ev("document.getElementById('ecStatus').textContent.includes('35 failure times')"), True)

                # --- the failure table ------------------------------------------
                await page.ev("document.querySelector('[data-tab=\"failures\"]').click()")
                await asyncio.sleep(0.5)
                check('the failure table has 35 rows', await page.ev("document.querySelectorAll('#ecFailTable tbody tr').length"), 35)
                check('the first row is hole 1 at 850,000 years',
                      await page.ev("(() => { const c = document.querySelectorAll('#ecFailTable tbody tr')[0].children; return c[1].textContent + '@' + c[2].textContent; })()"),
                      '1@850,000')
                await page.ev("document.querySelector('#ecFailTable th[data-key=\"tFail\"]').click()")
                await asyncio.sleep(0.3)
                check('sorting by tFail puts 85,000 first',
                      await page.ev("document.querySelectorAll('#ecFailTable tbody tr')[0].children[2].textContent"), '85,000')

                # --- the charts --------------------------------------------------
                await page.ev("document.querySelector('[data-tab=\"time\"]').click()")
                await asyncio.sleep(1.5)
                check('the time chart has three traces',
                      await page.ev("(() => { const d = document.getElementById('ecChartTime'); return d.data ? d.data.length : 'none'; })()"), 3)
                check('and its failed-canister curve ends at the corrected mean',
                      await page.ev("(() => { const y = document.getElementById('ecChartTime').data[0].y; return Math.abs(y[y.length - 1] - 3.5) < 1e-9; })()"), True)
                await page.ev("document.querySelector('[data-tab=\"distributions\"]').click()")
                await asyncio.sleep(1.5)
                check('the Qeq distribution draws four curves plus a line',
                      await page.ev("(() => { const d = document.getElementById('ecChartDist'); return d.data ? d.data.length : 'none'; })()"), 5)
                await page.ev("(() => { const s = document.getElementById('ecDistWhich'); s.value = 'erosion';"
                              " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
                await asyncio.sleep(1.2)
                check('switching to the erosion plot draws two curves and two lines',
                      await page.ev("(() => { const d = document.getElementById('ecChartDist'); return d.data ? d.data.length : 'none'; })()"), 4)
                check('with the SR-Site model named in the title',
                      await page.ev("document.getElementById('ecChartDist').layout.title.text.includes('SR-Site')"), True)

                # --- the per-hole table -----------------------------------------
                await page.ev("document.querySelector('[data-tab=\"holes\"]').click()")
                await asyncio.sleep(0.8)
                check('the hole table shows the first 300 of 6017',
                      await page.ev("document.getElementById('ecHoleNote').textContent"), 'Showing 300 of 6,017 holes; the CSV has them all.')
                await page.ev("(() => { const s = document.getElementById('ecHoleFilter'); s.value = 'rejected';"
                              " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
                await asyncio.sleep(0.5)
                check('filtering to rejected holes gives 17 rows',
                      await page.ev("document.querySelectorAll('#ecHoleTable tbody tr').length"), 17)
                check('the first of them names FPC as the reason',
                      await page.ev("(() => { const tds = document.querySelectorAll('#ecHoleTable tbody tr')[0].children; return tds[0].textContent + ':' + tds[18].textContent; })()"), '11:FPC')

                # --- a parameter change re-runs ---------------------------------
                await page.ev("(() => { const el = document.querySelector('input[data-key=\"tFailFilteringLim\"]'); el.value = '100000';"
                              " el.dispatchEvent(new Event('change', { bubbles: true })); })()")
                await asyncio.sleep(1.0)
                # Hole 2 fails at 85,000 to 94,000 years: all ten rows survive a
                # 100,000-year limit, and the documented "1 canister at 100,000
                # years" is those ten over the ten sulphide values.
                check('an assessment time of 100,000 years leaves the ten rows of hole 2',
                      await page.ev("ECPage.getState().result.results[0].key.nFailRows"), 10)
                check('and the status says so',
                      await page.ev("document.getElementById('ecStatus').textContent.includes('10 failure times in the table')"), True)
                await page.ev("document.querySelector('[data-on-click=\"ec:resetParams\"]').click()")
                await asyncio.sleep(1.0)
                check('reset puts every parameter back',
                      await page.ev("ECModel.PARAMS.every((d) => ECPage.getState().params[d.key] === d.def)"), True)
                # With the PSAR defaults (NewKTH, 50 % dilute) holes 3 and 4 become
                # advective at 39,277 and 70,672 years, so the table grows to 38 rows.
                check('and the run follows (NewKTH, 0.5 dilute, HSTest: 38 rows)',
                      await page.ev("ECPage.getState().result.results[0].key.nFailRows"), 38)

                # --- a second realisation, and pooling -------------------------
                await page.ev(DROP_CASE % json.dumps('copy.csv'))
                await asyncio.sleep(2.5)
                check('a dropped file becomes a second realisation',
                      await page.ev("ECPage.getState().result ? ECPage.getState().result.results.length : 0"), 2)
                check('the status says two realisations',
                      await page.ev("document.getElementById('ecStatus').textContent.includes('2 realisations')"), True)
                await page.ev("document.querySelector('[data-tab=\"summary\"]').click()")
                await asyncio.sleep(0.5)
                check('the key-output table gains min, mean and max columns',
                      await page.ev("document.querySelectorAll('#ecSummary table.ec-key thead th').length"), 6)

            # --- refusals ----------------------------------------------------
            await page.ev("""(() => {
              const f = new File(['a,b,c\\n1,2,3\\n'], 'junk.csv', { type: 'text/csv' });
              const dt = new DataTransfer(); dt.items.add(f);
              document.querySelector('.ec').dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
            })()""")
            await asyncio.sleep(1.0)
            check('a file that is not a hydro table is refused by name',
                  await page.ev("document.getElementById('ecStatus').textContent.startsWith('junk.csv: Not a hydro table')"), True)
            check('and the loaded realisations are untouched',
                  await page.ev("ECPage.getState().hydro.length"), 2 if have_case else 0)

            # --- case file round trip ---------------------------------------
            await page.ev("""(() => {
              const doc = { app: 'kvot-erosion-corrosion', version: 1, params: { mBuffAdv: 600, pessCorrGeo: true, bogus: 1 }, hs: { table: 'HSLaxemar' } };
              const f = new File([JSON.stringify(doc)], 'case.json', { type: 'application/json' });
              const dt = new DataTransfer(); dt.items.add(f);
              document.querySelector('.ec').dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
            })()""")
            await asyncio.sleep(1.5)
            check('a dropped case file applies its settings',
                  await page.ev("ECPage.getState().params.mBuffAdv + ':' + ECPage.getState().params.pessCorrGeo + ':' + ECPage.getState().hs.table"),
                  '600:true:HSLaxemar')
            check('and reports the unknown key',
                  await page.ev("document.getElementById('ecStatus').textContent.includes('bogus')"), True)

            check('no script errors during the session', page.errors, [])
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})

    print(f'\n{checks} checks, {len(failures)} failed')
    if failures:
        print('\n'.join(f'  - {f}' for f in failures))
        sys.exit(1)


asyncio.run(main())
