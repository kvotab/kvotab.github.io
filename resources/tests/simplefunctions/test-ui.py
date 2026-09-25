#!/usr/bin/env python3
"""SimpleFunctions.html in a real browser: does the page do the thing.

test-model.js proves the arithmetic. This proves the wiring: that the page
loads without a script error and runs the built-in example on a first visit
(in the worker), that every tab draws, that Version A on the TR-10-61
example water gives the report's uranium solubility, that an edit of the
data marks the results stale and a broken reaction is reported, that the
downloads come out, that a written CSOL MAT file can be read back as a
reference and compares equal, and that the (i) panel opens and closes.

Start the server and the browser as in ../rb/README.md (other ports with
SF_HTTP_PORT and SF_CDP_PORT), then

    python3 resources/tests/simplefunctions/test-ui.py

Exit status is 0 when every check passes.
"""
import asyncio
import base64
import json
import os
import sys
import tempfile
import urllib.request

import websockets

HTTP = int(os.environ.get('SF_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SF_CDP_PORT', '9222'))
URL = f'http://127.0.0.1:{HTTP}/SimpleFunctions.html'

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

    async def set_file(self, selector, path):
        doc = await self.call('DOM.getDocument', {}, session=self.sid)
        node = await self.call('DOM.querySelector', {'nodeId': doc['result']['root']['nodeId'], 'selector': selector}, session=self.sid)
        await self.call('DOM.setFileInputFiles', {'nodeId': node['result']['nodeId'], 'files': [path]}, session=self.sid)


async def settle(page, expr, want, tries=80, pause=0.25):
    got = None
    for _ in range(tries):
        got = await page.ev(expr)
        if got == want:
            return got
        await asyncio.sleep(pause)
    return got


def status_has(needle):
    return f"document.getElementById('sfStatus').textContent.includes({json.dumps(needle)})"


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
        # Network.enable first, or the cache is not disabled (see ../rb/README.md).
        await page.call('Network.setCacheDisabled', {'cacheDisabled': True}, session=page.sid)
        await page.call('Page.addScriptToEvaluateOnNewDocument', {'source': "try{localStorage.removeItem('kvot-sf-v1')}catch(e){}"}, session=page.sid)
        await page.call('Page.navigate', {'url': URL}, session=page.sid)
        try:
            check('a first visit loads the TR-10-61 waters in range and runs', await settle(page, status_has('6,916 realisations in'), True), True)
            check('no script errors on load', page.errors, [])
            check('six waters', await page.ev("SFPage.getState().table.rawWaters.length"), 6)
            check('the summary has a row per element', await page.ev("document.querySelectorAll('#sfSummary .sf-el-table tbody tr').length"), 20)
            check('and a box plot', await page.ev("(() => { const d = document.getElementById('sfChartBox'); return d && d.data ? d.data.length : 'none'; })()"), 3)
            check('every (i) slot of the panel has its button', await page.ev("document.querySelectorAll('.sf-side .sf-info-slot[data-info-key]').length === document.querySelectorAll('.sf-side .sf-info-slot [data-info]').length"), True)

            await page.ev("document.querySelector('[data-on-click=\"sf:split\"]').click()")
            check('the variability split runs its two extra runs', await settle(page, status_has('Variability split'), True), True)
            check('and tabulates the three spreads for every element', await page.ev("document.querySelectorAll('#sfSummary table.sf-table')[1].querySelectorAll('tbody tr').length"), 20)
            check('with two more boxes per element in the plot', await page.ev("document.getElementById('sfChartBox').data.filter((t) => t.type === 'box').length"), 3)
            check('uranium’s spread is the constants’', await page.ev("(() => { const tr = Array.from(document.querySelectorAll('#sfSummary table.sf-table')[1].querySelectorAll('tbody tr')).find((r) => r.children[0].textContent === 'U'); return tr.children[5].textContent; })()"), 'the constants')

            for tab in ['water', 'dist', 'sens', 'sweep', 'compare', 'data', 'samples', 'help']:
                await page.ev(f"document.querySelector('[data-tab=\"{tab}\"]').click()")
                await asyncio.sleep(0.8)
                check(f'the {tab} tab draws without an error', page.errors, [])
            await page.ev("document.querySelector('[data-tab=\"dist\"]').click()")
            await asyncio.sleep(0.8)
            check('the distribution of U is drawn', await page.ev("(() => { const d = document.getElementById('sfChartDist'); return !!(d.data && d.data.length); })()"), True)
            await page.ev("document.querySelector('[data-tab=\"sens\"]').click()")
            await asyncio.sleep(1.0)
            check('the sensitivity of U is led by U(OH)4(aq) or UO2·2H2O(am)',
                  await page.ev("['U(OH)4(aq)', 'UO2·2H2O(am)'].includes(document.querySelector('#sfSensTable tbody tr td').textContent)"), True)

            # --- Version A on the TR-10-61 example --------------------------
            await page.ev("(() => { const s = document.getElementById('sfExample'); s.value = 'tr1061ex'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev("(() => { const s = document.getElementById('sfVersion'); s.value = 'A'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev("SFPage.showTab('water')")
            await asyncio.sleep(0.8)
            check('Version A, TR-10-61 table 3-2: U is −8.13 under UO2·2H2O(am)',
                  await page.ev("(() => { const tr = document.querySelector('.sf-water-table tr[data-el=\"U\"]'); return tr.children[1].textContent + ' ' + tr.children[3].textContent; })()"), '−8.13 UO2·2H2O(am)')
            await page.ev("(() => { const s = document.getElementById('sfVersion'); s.value = 'B'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")

            # --- data edits ------------------------------------------------
            await page.ev("(() => { const s = document.getElementById('sfExample'); s.value = 'tr1061range'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev("SFPage.run()")
            await settle(page, status_has('realisations in'), True)
            await page.ev("SFPage.getState().dataEl = 'Sm'; SFPage.showTab('data')")
            await asyncio.sleep(0.5)
            await page.ev("(() => { const el = document.querySelector('#sfDataTable input[data-kind=\"solid\"][data-i=\"2\"][data-field=\"logK\"]'); el.value = '-8.0'; el.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.5)
            check('an edited constant marks the results stale', await page.ev("SFPage.getState().result.stale"), True)
            check('and is counted in the panel', await page.ev("document.getElementById('sfDataCount').textContent"), '1 edited')
            await page.ev("(() => { const el = document.querySelector('#sfDataTable input[data-kind=\"species\"][data-i=\"0\"][data-field=\"rx\"]'); el.value = 'Sm+3 + H2O = SmOH+2'; el.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.5)
            check('a reaction that does not balance is reported', await page.ev("document.getElementById('sfDataIssues').textContent.includes('charge does not balance')"), True)
            await page.ev("KVOT_ACTIONS['sf:resetData'](new Event('click'), document.body)")
            await asyncio.sleep(0.3)
            check('reset puts the SR-Site data back', await page.ev("document.getElementById('sfDataCount').textContent"), '')
            await page.ev("SFPage.run()")
            check('and a run brings the results up to date', await settle(page, "SFPage.getState().result && !SFPage.getState().result.stale && !SFPage.getState().running", True), True)

            # --- downloads -------------------------------------------------
            await page.ev("(() => { window.__dl = []; const o = URL.createObjectURL; URL.createObjectURL = (b) => { window.__dl.push(b); return o.call(URL, b); }; })()")
            for act in ['sf:samplesCsv', 'sf:samplesMat', 'sf:samplesJson', 'sf:inputsCsv', 'sf:saveCase', 'sf:saveData']:
                await page.ev(f"KVOT_ACTIONS['{act}'](new Event('click'), document.body)")
                await asyncio.sleep(0.2)
            await page.ev("KVOT_ACTIONS['sf:samplesExcel'](new Event('click'), document.body)")
            await asyncio.sleep(1.5)
            heads = await page.ev("Promise.all(window.__dl.map(async (b) => (await b.slice(0, 20).text()).replace(/[^\\x20-\\x7e]/g, '.')))")
            check('seven downloads', len(heads or []), 7)
            check('the CSV starts with the header', (heads or [''])[0].startswith('realisation,water_ro'), True)
            check('the MAT file is level 5', (heads or ['', ''])[1].startswith('MATLAB 5.0 MAT-file'), True)
            check('the Excel file is a zip', (heads or [''] * 7)[6].startswith('PK'), True)
            mat_b64 = await page.ev("(async () => { const b = window.__dl[1]; const a = new Uint8Array(await b.arrayBuffer()); let s = ''; for (let i = 0; i < a.length; i += 8192) s += String.fromCharCode.apply(null, a.subarray(i, i + 8192)); return btoa(s); })()")
            with tempfile.NamedTemporaryFile(suffix='.mat', delete=False) as f:
                f.write(base64.b64decode(mat_b64))
                mat_path = f.name

            # --- the written MAT file as a reference compares equal --------
            await page.set_file('#sfRefFile', mat_path)
            check('the CSOL MAT file reads back as a reference', await settle(page, status_has('reference loaded'), True), True)
            await page.ev("SFPage.showTab('compare')")
            await asyncio.sleep(1.0)
            check('with 20 elements compared', await page.ev("document.querySelectorAll('#sfCompareTable tbody tr').length"), 20)
            check('every KS distance 0 against itself', await page.ev("Array.from(document.querySelectorAll('#sfCompareTable tbody tr')).every((tr) => tr.children[9].textContent === '0.0000')"), True)
            os.unlink(mat_path)

            # --- the (i) panel ---------------------------------------------
            await page.ev("document.querySelector('[data-info=\"set:draw\"]').click()")
            await asyncio.sleep(0.3)
            check('an (i) opens its panel', await page.ev("document.querySelector('.info-panel-title').textContent"), 'Groundwater draw')
            check('the chosen draw is marked', await page.ev("document.querySelector('.info-choices dt.is-current').textContent.startsWith('at random, with replacement')"), True)
            await page.ev("document.querySelector('[data-info=\"set:draw\"]').click()")
            await asyncio.sleep(0.2)
            check('the same (i) closes it', await page.ev("!document.querySelector('.info-panel')"), True)
            check('no script errors along the way', page.errors, [])
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})
    print(f'{checks} checks, {len(failures)} failed')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    asyncio.run(main())
