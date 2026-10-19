#!/usr/bin/env python3
"""erosion_corrosion.html in a real browser: does the page do the thing.

test-model.js proves the arithmetic. This proves the wiring: that the page
loads without a script error, that the panel is built from the catalogue,
that every setting, section heading and tab toolbar has its (i) and the
panel it opens says the right thing and closes, that SKB's code test case,
dropped on the panel with the SR-Site settings, runs and puts the documented
numbers in the summary, that every tab draws, that a parameter change
re-runs, and that a dropped CSV of unknown shape is refused with a message
rather than a silence.

The test file is SKB's and not in the repository: the checks that need it
drop the local copy that make-local-fixtures.py writes, and are skipped
without it. The failure histogram, its legend, its canister table and the
paging of a long failure table are checked on a layout of the test's own
(synthetic_csv), with or without that copy.

Start the server and the browser as in ../rb/README.md (other ports with
EC_HTTP_PORT and EC_CDP_PORT), then

    python3 resources/tests/erosion_corrosion/test-ui.py

Exit status is 0 when every check passes.
"""
import asyncio
import csv
import io
import json
import os
import sys
import urllib.request

import websockets

HTTP = int(os.environ.get('EC_HTTP_PORT', '8765'))
CDP = int(os.environ.get('EC_CDP_PORT', '9222'))

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
URL = f'http://127.0.0.1:{HTTP}/erosion_corrosion.html'
CASE = './resources/tests/erosion_corrosion/local/TestCaseHydro_2_0.csv'
# Drops the local copy of the test file on the panel, under the given name.
DROP_CASE = """(async (name) => {
  const text = await (await fetch(%s)).text();
  const f = new File([text], name, { type: 'text/csv' });
  const dt = new DataTransfer(); dt.items.add(f);
  document.querySelector('.ec').dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
})(%%s)""" % json.dumps(CASE)


def synthetic_csv(n=200):
    """A layout of our own: n holes whose fracture flow rises from 1e-6 to
    10^-2.8 m/yr through an aperture of 0.1 mm, the last two rejected. With
    a generated sulphide table of 1000 values about 40 canisters fail, for
    one value to a few dozen each."""
    lines = ['POINT,OKFLAG,U0,QEQ,TW,F,TRAPP,FPC,EFPC,FLEN']
    for i in range(n):
        u0 = 10 ** (-6 + 3.2 * i / (n - 1))
        lines.append(','.join(str(x) for x in [i + 1, 0, f'{u0:.6e}', 1e-5, 100 + i, 1e5 * (i + 1), 1e-4,
                                                  1 if i == n - 1 else 0, 5 if i == n - 2 else 0, 20]))
    return '\n'.join(lines) + '\n'


# Drops a file with the given text and name on the panel.
DROP_TEXT = """((text, name) => {
  const f = new File([text], name, { type: 'text/csv' });
  const dt = new DataTransfer(); dt.items.add(f);
  document.querySelector('.ec').dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
})(%s, %s)"""
# The text a button would download, caught on its way out.
CAUGHT_DOWNLOAD = """(async (sel) => {
  const make = URL.createObjectURL, revoke = URL.revokeObjectURL, click = HTMLAnchorElement.prototype.click;
  let blob = null, name = null;
  URL.createObjectURL = (b) => { blob = b; return 'blob:caught'; };
  URL.revokeObjectURL = () => {};
  HTMLAnchorElement.prototype.click = function () { name = this.download; };
  try { document.querySelector(sel).click(); } finally {
    URL.createObjectURL = make; URL.revokeObjectURL = revoke; HTMLAnchorElement.prototype.click = click;
  }
  return blob ? [name, await blob.text()] : null;
})(%s)"""
# Whether the legend of the failure histogram is titled as given and every
# entry is "<label>: <its colour's share of the bars> %", the label as the
# function given says.
LEGEND_SHARES = """((title, label) => {
  const gd = document.getElementById('ecChartHist');
  const bars = gd.data.filter((t) => t.type === 'bar' && t.yaxis === 'y2');
  const h = ECPage.getState().histogram.h;
  const sum = new Map(bars.map((t) => [t.legendgroup, t.y.reduce((a, v) => a + (v || 0), 0)]));
  const total = [...sum.values()].reduce((a, b) => a + b, 0);
  const sums = h.groups.map((g) => sum.get(g.key));
  const texts = Array.from(document.querySelectorAll('#ecChartHist .legendtext')).map((e) => e.textContent.replace(/\\u200b/g, ''));
  const head = document.querySelector('#ecChartHist .legendtitletext');
  return !!head && head.textContent === title && texts.length === bars.length
    && texts.every((t, i) => t === label(i, h) + ': ' + ECPage.fmt(100 * sums[i] / total, 3) + ' %%');
})(%s, %s)"""
# The legend entries of the failure histogram, and the rows of the table of
# sulphide groups under it, as text (Plotly sets superscripts off with
# zero-width spaces).
LEGEND_TEXTS = """Array.from(document.querySelectorAll('#ecChartHist .legendtext')).map((e) => e.textContent.replace(/\\u200b/g, ''))"""
HS_ROWS = """Array.from(document.querySelectorAll('#ecDecadeTable tbody tr')).map((tr) => Array.from(tr.children).slice(1).map((td) => td.textContent.replace(/\\u200b/g, '')))"""
# What the bars of the failure histogram add up to.
BARS_SUM = """document.getElementById('ecChartHist').data.filter((t) => t.type === 'bar' && t.yaxis === 'y2')
  .reduce((s, t) => s + t.y.reduce((a, v) => a + (v || 0), 0), 0)"""

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
        # The cache off, which needs the Network domain on: a reused profile
        # otherwise serves yesterday's scripts, or a local file since removed.
        await page.call('Network.enable', session=page.sid)
        await page.call('Network.clearBrowserCache', session=page.sid)
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

            # --- the (i) and its panel --------------------------------------
            audit = json.loads(await page.ev("JSON.stringify(KvotInfo.audit())"))
            check('every (i) slot has a topic', audit['noTopic'], [])
            check('every topic has a title, and its Help link a heading in the page', audit['brokenMore'], [])
            check('every slot has its button', audit['buttons'], audit['slots'])
            check('every catalogue parameter has its (i)',
                  await page.ev("ECModel.PARAMS.filter((d) => !document.querySelector("
                                "`#ecParamSections .kvot-info-slot[data-info-key=\"p:${d.key}\"] .info-btn`)).map((d) => d.key)"), [])
            # A heading's (i) is in the slot before its <details>, not in the
            # summary: Chrome reports every control inside a <summary>.
            check('every section heading of the panel has one',
                  await page.ev("Array.from(document.querySelectorAll('.ec-side details.ec-sec'))"
                                ".filter((d) => !(d.previousElementSibling && d.previousElementSibling.matches('.kvot-info-slot')"
                                " && d.previousElementSibling.querySelector('.info-btn')))"
                                ".map((d) => d.querySelector('summary').textContent)"), [])
            check('no (i) slot is inside a <summary>', audit.get('inSummary'), [])
            check('nor any other control', await page.ev(NO_CONTROL_IN_SUMMARY), '')
            check('each heading\'s (i) is centred on its line, at its end', await page.ev(HEADING_I_OFF % '.kvot-info-sec'), '')
            check('and every result tab’s toolbar',
                  await page.ev("['failures', 'histogram', 'time', 'distributions', 'holes']"
                                ".filter((t) => !document.querySelector(`.ec-pane[data-pane=\"${t}\"] .ec-toolbar .info-btn`))"), [])
            # (A file name cut short keeps its title: the whole name, not a tooltip.)
            check('no hover tooltips left on the settings or the toolbars',
                  await page.ev("Array.from(document.querySelectorAll('.ec-side [title], .ec-toolbar [title]'))"
                                ".filter((el) => !el.matches('.ec-file-name')).map((el) => el.outerHTML.slice(0, 80))"), [])
            check('the (i)s of the side panel line up at the right',
                  await page.ev("""(() => {
                    for (const d of document.querySelectorAll('.ec-side details.ec-sec')) d.open = true;
                    const r = Array.from(document.querySelectorAll('.ec-side .info-btn'))
                      .filter((b) => b.getBoundingClientRect().width > 0 && !b.closest('.ec-inline'))
                      .map((b) => Math.round(b.getBoundingClientRect().right));
                    return r.length > 70 && Math.max(...r) - Math.min(...r) <= 1;
                  })()"""), True)
            await page.ev("document.querySelector('[data-info=\"p:mBuffAdv\"]').click()")
            await asyncio.sleep(0.3)
            check('a parameter’s (i) opens the panel with its title',
                  await page.ev("document.querySelector('.info-panel .info-panel-title').textContent"), 'Buffer loss for advection')
            fact = """((label) => {
              const dt = Array.from(document.querySelectorAll('.info-panel .info-facts dt')).find((d) => d.textContent === label);
              return dt ? dt.nextElementSibling.textContent : null;
            })(%s)"""
            check('and the current value', await page.ev(fact % json.dumps('Current value')), '1200')
            check('the workbook and Python names', await page.ev(fact % json.dumps('Workbook name')) + ' ' + await page.ev(fact % json.dumps('Python name')),
                  'MBuffAdv m_buffadv')
            check('and a Read more link to the Help',
                  await page.ev("document.querySelector('.info-panel .info-panel-more').textContent"), 'Read more in Help: Time to advective conditions →')
            check('the panel sits between the header and the footer',
                  await page.ev("""(() => {
                    const p = document.querySelector('.info-panel').getBoundingClientRect();
                    return Math.abs(p.top - document.querySelector('header').getBoundingClientRect().bottom) < 1.5
                      && Math.abs(p.bottom - document.querySelector('footer').getBoundingClientRect().top) < 1.5;
                  })()"""), True)
            await page.ev("(() => { const el = document.querySelector('input[data-key=\"mBuffAdv\"]'); el.value = '600';"
                          " el.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            check('an open panel follows a change of the value', await page.ev(fact % json.dumps('Current value')), '600 (changed)')
            await page.ev("document.querySelector('[data-on-click=\"ec:resetParams\"]').click()")
            await asyncio.sleep(0.3)
            check('the × closes it',
                  await page.ev("document.querySelector('.info-panel .info-panel-close').click(), !document.querySelector('.info-panel') && KvotInfo.current() === null"), True)
            await page.ev("document.querySelector('[data-info=\"p:buffModel\"]').click()")
            await asyncio.sleep(0.2)
            check('a choice lists its options with the one in force marked',
                  await page.ev("Array.from(document.querySelectorAll('.info-panel .info-choices dt.is-current')).map((d) => d.textContent)"),
                  ['NewKTH: erosion, TR-16-11 (PSAR)'])
            await page.ev("document.querySelector('[data-info=\"p:buffModel\"]').click()")
            await asyncio.sleep(0.2)
            check('the same (i) closes it', await page.ev("!document.querySelector('.info-panel')"), True)
            # Escape as a key press. (Chrome 153 headless can hang on a CDP Escape
            # that closes a modal <dialog>; this panel is not one, and closing it
            # this way was tried repeatedly without a hang.)
            async def escape():
                for kind in ('keyDown', 'keyUp'):
                    await page.call('Input.dispatchKeyEvent', {'type': kind, 'key': 'Escape', 'code': 'Escape',
                                                               'windowsVirtualKeyCode': 27, 'nativeVirtualKeyCode': 27}, session=page.sid)
            await page.ev("document.querySelector('[data-info=\"sec:hydro\"]').click()")
            await asyncio.sleep(0.2)
            await escape()
            await asyncio.sleep(0.2)
            check('Escape closes it', await page.ev("!document.querySelector('.info-panel')"), True)
            check('and the focus goes back to its (i)', await page.ev("document.activeElement.dataset.info || ''"), 'sec:hydro')
            await page.ev("document.querySelector('[data-info=\"sec:hydro\"]').click()")
            await asyncio.sleep(0.2)
            await page.ev("document.activeElement.blur()")
            await escape()
            await asyncio.sleep(0.2)
            check('also when the focus has left it for the page', await page.ev("!document.querySelector('.info-panel')"), True)
            # A tab's (i) marks the choice in force, and follows a change of it.
            await page.ev("(() => { const s = document.getElementById('ecDistWhich'); s.value = 'erosion';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await page.ev("document.querySelector('[data-info=\"pane:distributions\"]').click()")
            await asyncio.sleep(0.2)
            current = "Array.from(document.querySelectorAll('.info-panel .info-choices dt.is-current')).map((d) => d.textContent)"
            check('a tab’s (i) marks the quantity shown', await page.ev(current), ['Buffer loss rate (EroPlt)'])
            await page.ev("(() => { const s = document.getElementById('ecDistWhich'); s.value = 'qeq';"
                          " s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.2)
            check('and follows a change of it', await page.ev(current), ['Qeq from the hydro model (QeqPlt)'])
            # Read more in Help: the Help tab, at the heading.
            await page.ev("document.querySelector('[data-info=\"p:w\"]').click()")
            await asyncio.sleep(0.2)
            await page.ev("document.querySelector('.info-panel .info-panel-more').click()")
            await asyncio.sleep(0.4)
            check('Read more in Help opens the Help tab at the heading',
                  await page.ev("""(() => {
                    const pane = document.querySelector('.ec-pane[data-pane="help"]');
                    const h = document.getElementById('help-flow');
                    return ECPage.getState().tab === 'help' && !pane.hidden && !document.querySelector('.info-panel')
                      && Math.abs(h.getBoundingClientRect().top - pane.getBoundingClientRect().top) < 2;
                  })()"""), True)
            await page.ev("document.querySelector('[data-tab=\"summary\"]').click()")
            await asyncio.sleep(0.2)
            check('no script errors from the (i)s', page.errors, [])

            # --- the code test case ----------------------------------------
            # SKB's test file (SKBdoc 1895160) is not part of the page: set the
            # SR-Site settings on the panel and drop the local copy.
            have_case = await page.ev(f"fetch({json.dumps(CASE)}, {{ method: 'HEAD' }}).then((r) => r.ok, () => false)")
            if not have_case:
                print('skip  the code test case and the checks on its results: no local copy of the test file'
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
                await page.ev("document.querySelector('[data-tab=\"histogram\"]').click()")
                await asyncio.sleep(1.2)
                check('the failure histogram adds up to the corrected mean too', abs(await page.ev(BARS_SUM) - 3.5) < 1e-9, True)
                check('its canisters: holes 1 to 3 fail for every sulphide value, hole 4 for half',
                      await page.ev("Array.from(document.querySelectorAll('#ecCanisterTable tbody tr'))"
                                    ".map((tr) => tr.children[1].textContent + ':' + tr.children[2].textContent).sort().join(' ')"),
                      '1:100 % 2:100 % 3:100 % 4:50 %')
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
                check('a dropped file becomes a second realisation',
                      await settle(page, "ECPage.getState().result ? ECPage.getState().result.results.length : 0", 2), 2)
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

            # --- the failure histogram, on a layout of our own ---------------
            async def choose(sel, value):
                await page.ev("(() => { const s = document.querySelector(%s); s.value = %s;"
                              " s.dispatchEvent(new Event('change', { bubbles: true })); })()" % (json.dumps(sel), json.dumps(value)))
                await asyncio.sleep(0.6)

            async def set_sulphide(n):
                await page.ev("(() => { const s = document.getElementById('ecHsTable'); s.value = 'generic';"
                              " s.dispatchEvent(new Event('change', { bubbles: true }));"
                              " const el = document.getElementById('ecHsN'); el.value = %s;"
                              " el.dispatchEvent(new Event('change', { bubbles: true })); })()" % json.dumps(str(n)))

            async def sulphide_values(n):
                await set_sulphide(n)
                return await settle(page, "ECPage.getState().result && ECPage.getState().result.results[0].key.nHs", n)

            await page.ev("document.querySelector('[data-on-click=\"ec:resetParams\"]').click()")
            await page.ev("document.querySelector('[data-on-click=\"ec:clearHydro\"]').click()")
            await set_sulphide(1000)
            await page.ev(DROP_TEXT % (json.dumps(synthetic_csv()), json.dumps('synthetic.csv')))
            check('a layout of our own runs with a generated sulphide table of 1000 values',
                  await settle(page, "!!ECPage.getState().result && ECPage.getState().hydro.length === 1"
                                     " && ECPage.getState().result.results[0].key.nHs === 1000", True), True)
            await page.ev("document.querySelector('[data-tab=\"histogram\"]').click()")
            await asyncio.sleep(1.2)
            state = "ECPage.getState()"
            check('the failure histogram draws',
                  await page.ev("!document.getElementById('ecChartHist').hidden && document.getElementById('ecChartHist').data.length > 3"), True)
            def close(a, b, tol=1e-9):
                return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= tol * max(abs(b), 1e-300)
            mean_corr = await page.ev(f"{state}.result.summary.meanFailedCorrected.mean")
            n_rows = await page.ev(f"{state}.result.results[0].key.nFailRows")
            n_cans = await page.ev(f"{state}.histogram.h.canisters.length")
            n_rows_text, n_cans_text = f'{n_rows:,}', f'{n_cans:,}'
            check('its bars add up to the corrected mean', close(await page.ev(BARS_SUM), mean_corr), True)
            check('one colour per sulphide decade',
                  await page.ev(f"document.getElementById('ecChartHist').data.filter((t) => t.type === 'bar').length === {state}.histogram.h.bands.length"), True)
            # Each legend entry gives its colour's share of the bars, and under
            # it the share of the sulphide values in its decade.
            check('the legend gives each decade’s share of the bars, under the title Share of the failures',
                  await page.ev(LEGEND_SHARES % (json.dumps('Share of the failures'),
                                                 "(i, h) => { const p = (k) => '10' + (k < 0 ? '−' + -k : String(k)); const b = h.bands[i];"
                                                 " return b.below ? 'below ' + p(b.exp + 1) + ' M' : p(b.exp) + '–' + p(b.exp + 1) + ' M'; }")), True)
            # Under the chart: the share of the values in each decade, beside
            # the share of the failures they give.
            decades = await page.ev("""Array.from(document.querySelectorAll('#ecDecadeTable tbody tr'))
              .map((tr) => Array.from(tr.children).slice(1).map((td) => td.textContent))""")
            check('the table of decades has a row per decade', len(decades), await page.ev(f"{state}.histogram.h.bands.length"))
            check('with the share of the sulphide values in each',
                  [row[2] for row in decades],
                  await page.ev(f"{state}.histogram.h.bands.map((b) => ECPage.fmt(100 * b.n / 1000, 3) + ' %')"))
            check('beside its share of the failures, the part of the bars in its colour',
                  [row[3] for row in decades],
                  await page.ev("(() => { const bars = document.getElementById('ecChartHist').data.filter((t) => t.type === 'bar' && t.yaxis === 'y2');"
                                " const sum = new Map(bars.map((t) => [t.legendgroup, t.y.reduce((a, v) => a + (v || 0), 0)]));"
                                " const total = [...sum.values()].reduce((a, b) => a + b, 0);"
                                " return ECPage.getState().histogram.h.groups.map((g) => ECPage.fmt(100 * sum.get(g.key) / total, 3) + ' %'); })()"))
            check('the highest decade is on top of the stacks and first in the legend, as in the table',
                  await page.ev("(() => { const gd = document.getElementById('ecChartHist'); const h = ECPage.getState().histogram.h;"
                                " const bars = gd.data.filter((t) => t.type === 'bar' && t.yaxis === 'y2').map((t) => t.legendgroup);"
                                " const first = document.querySelector('#ecChartHist .legendtext').textContent.replace(/\\u200b/g, '');"
                                " return bars[bars.length - 1] === h.groups[0].key && bars[0] === h.groups[h.groups.length - 1].key"
                                " && first.startsWith('10' + (h.bands[0].exp < 0 ? '−' + -h.bands[0].exp : h.bands[0].exp) + '–'); })()"), True)
            check('and its canisters fewer the lower the decade',
                  all(int(a[6].replace(',', '')) >= int(b[6].replace(',', '')) for a, b in zip(decades, decades[1:]) if int(b[1].replace(',', '')) > 0), True)
            check('its total row: every value, every row, every canister',
                  await page.ev("Array.from(document.querySelector('#ecDecadeTable tfoot tr').children).slice(1).map((td) => td.textContent).join('|')"),
                  f'All|1,000|100 %|100 %|{await page.ev(f"ECPage.fmt({state}.result.summary.meanFailedCorrected.mean, 4)")}|{n_rows_text}|{n_cans_text}')
            check('several rows to a canister, more than eight canisters', n_rows > n_cans > 8, True)
            await choose('#ecHistCount', 'rows')
            check('counting rows, they add up to the rows of the failure table', close(await page.ev(BARS_SUM), n_rows), True)
            await choose('#ecHistCount', 'uncorrected')
            check('uncorrected, to the mean number of failed canisters',
                  close(await page.ev(BARS_SUM), await page.ev(f"{state}.result.results[0].key.meanFailed")), True)
            await choose('#ecHistCount', 'corrected')
            await choose('#ecHistBy', 'canister')
            check('by canister: eight on their own and the rest together',
                  await page.ev("Array.from(document.querySelectorAll('#ecChartHist .legendtext')).map((e) => e.textContent).pop()"),
                  f'{n_cans - 8} other canisters: {await page.ev("ECPage.fmt(100 * ECPage.getState().histogram.h.groups[8].total / ECPage.getState().histogram.h.total, 3)")} %')
            check('the legend gives each canister’s share of the bars',
                  await page.ev(LEGEND_SHARES % (json.dumps('Share of the failures'),
                                                 "(i, h) => i < 8 ? String(h.groups[i].canister.id) : h.groups[i].canisters + ' other canisters'")), True)
            check('and still adding up to the corrected mean', close(await page.ev(BARS_SUM), mean_corr), True)

            async def click_legend(i, clicks):
                # Plotly holds a single click back for its double-click delay, so
                # the checks below wait for the state rather than for a time. The
                # clicks go from inside the page, on the entry's toggle, so that the
                # two of a double click come within that delay however busy the
                # machine (sent one by one over CDP they can miss it).
                await page.ev("((i, clicks) => {"
                              " const t = document.querySelectorAll('#ecChartHist .legend .traces')[i].querySelector('.legendtoggle');"
                              " const r = t.getBoundingClientRect();"
                              " const o = { bubbles: true, cancelable: true, view: window, button: 0, clientX: r.left + 10, clientY: r.top + r.height / 2 };"
                              " for (let n = 1; n <= clicks; n++) {"
                              "  t.dispatchEvent(new MouseEvent('mousedown', { ...o, detail: n })); t.dispatchEvent(new MouseEvent('mouseup', { ...o, detail: n })); }"
                              "})(%d, %d)" % (i, clicks))
            shown = ("[...new Set(document.getElementById('ecChartHist')._fullData.filter((t) => t.visible === true)"
                     ".map((t) => t.legendgroup))].sort().join(' ')")
            groups = await page.ev(f"{state}.histogram.h.groups.map((g) => g.key)")
            hidden = ("document.getElementById('ecChartHist')._fullData.filter((t) => t.visible === 'legendonly')"
                      ".map((t) => t.legendgroup + ':' + t.type + ':' + t.xaxis).sort().join(' ')")
            await click_legend(0, 1)
            want = ' '.join(sorted(f'{groups[0]}:{t}' for t in ('bar:x', 'scatter:x', 'scatter:x2')))
            check('a click on a canister in the legend hides its bars, curve and dot', await settle(page, hidden, want), want)
            await click_legend(0, 1)
            await settle(page, hidden, '')
            await click_legend(1, 2)
            want = ' '.join(sorted([groups[1], 'hs-table']))
            check('a double click shows that canister alone, with the sulphide table', await settle(page, shown, want), want)
            await asyncio.sleep(0.4)
            await click_legend(1, 2)
            want = ' '.join(sorted(groups + ['hs-table']))
            check('and another shows them all again', await settle(page, shown, want), want)

            check('the canister table has a row per canister',
                  await page.ev("document.querySelectorAll('#ecCanisterTable tbody tr').length"), n_cans)
            check('its colours are the chart’s, for the eight',
                  await page.ev("document.querySelectorAll('#ecCanisterTable .ec-swatch').length"), 8)
            check('its corrected column adds up to the corrected mean',
                  await page.ev("document.querySelector('#ecCanisterTable tfoot').textContent.includes(ECPage.fmt(ECPage.getState().result.summary.meanFailedCorrected.mean, 4))"), True)
            await page.ev("document.querySelector('#ecCanisterTable th[data-key=\"earliest\"]').click()")
            await asyncio.sleep(0.3)
            check('sorting by earliest failure puts the first failure first',
                  await page.ev("document.querySelector('#ecCanisterTable tbody tr').children[5].textContent"
                                f" === ECPage.fmt(Math.round(Math.min(...{state}.histogram.h.canisters.map((x) => x.earliest))))"), True)
            dots = "document.getElementById('ecChartHist').data.filter((t) => t.mode === 'markers' && t.xaxis === 'x').length"
            check('no dots for the rows of a table of 1000 values', await page.ev(dots), 0)
            await choose('#ecHistScale', 'linear')
            check('a linear time axis offers bins in years',
                  await page.ev("Array.from(document.getElementById('ecHistBins').options).map((o) => o.textContent)"),
                  ['50,000 years', '20,000 years', '10,000 years'])
            check('and draws them from 0', await page.ev(f"{state}.histogram.h.edges[0] === 0 && {state}.histogram.h.edges.length === 51"), True)
            await choose('#ecHistScale', 'log')
            check('a logarithmic one, in tenths of a decade',
                  await page.ev("document.getElementById('ecHistBins').value + ':' + document.getElementById('ecHistBins').selectedOptions[0].textContent"),
                  'medium:1/10 decade')
            # Twice the sulphide values: twice the rows, the same bars.
            await sulphide_values(2000)
            await asyncio.sleep(0.6)
            rows2 = await page.ev(f"{state}.result.results[0].key.nFailRows")
            check('twice the sulphide values give about twice the rows', 1.8 < rows2 / n_rows < 2.3, True)
            check('and bars that still add up to the corrected mean',
                  close(await page.ev(BARS_SUM), await page.ev(f"{state}.result.summary.meanFailedCorrected.mean")), True)
            check('which moves by less than five per cent',
                  abs(await page.ev(f"{state}.result.summary.meanFailedCorrected.mean") / mean_corr - 1) < 0.05, True)
            # The saved bins and canisters.
            got = await page.ev(CAUGHT_DOWNLOAD % json.dumps('[data-on-click="ec:histCsv"]'))
            table = list(csv.reader(io.StringIO(got[1]))) if got else [[]]
            n_colours = await page.ev(f"{state}.histogram.h.groups.length")
            check('CSV saves the bins with a column per colour and a total', bool(got) and got[0] == 'erosion_corrosion_histogram.csv'
                  and table[0][:2] == ['From (yr)', 'To (yr)'] and len(table[0]) == n_colours + 3
                  and table[0][-1] == 'Total (failed canisters, corrected)', True)
            check('and the totals add up to the corrected mean',
                  close(sum(float(row[-1]) for row in table[1:]), await page.ev(f"{state}.histogram.h.total"), 1e-12), True)
            got = await page.ev(CAUGHT_DOWNLOAD % json.dumps('[data-on-click="ec:canistersCsv"]'))
            lines = got[1].strip().split('\n') if got else []
            check('the canisters’ CSV has a line per canister',
                  bool(lines) and lines[0].startswith('Realisation,ID,Rows,Share,FailedCorrected') and len(lines) - 1 == await page.ev(f"{state}.histogram.h.canisters.length"), True)
            # The (i) of the tab marks the choices in force.
            await page.ev("document.querySelector('[data-info=\"pane:histogram\"]').click()")
            await asyncio.sleep(0.3)
            check('the tab’s (i) opens on the histogram',
                  await page.ev("document.querySelector('.info-panel .info-panel-title').textContent"), 'Failure histogram')
            check('and marks the count and the colours in force', await page.ev(current), ['failed canisters, corrected', 'canister'])
            await choose('#ecHistBy', 'hs')
            check('following a change', await page.ev(current), ['failed canisters, corrected', '[HS⁻] decade'])
            await page.ev("document.querySelector('.info-panel .info-panel-more').click()")
            await asyncio.sleep(0.4)
            check('its Help link opens the section on the histogram',
                  await page.ev("""(() => {
                    const pane = document.querySelector('.ec-pane[data-pane="help"]');
                    const h = document.getElementById('help-histogram');
                    return ECPage.getState().tab === 'help' && Math.abs(h.getBoundingClientRect().top - pane.getBoundingClientRect().top) < 2;
                  })()"""), True)
            # A measured table: a dot for each row, on its canister's curve.
            await choose('#ecHsTable', 'HSForsmark')
            await settle(page, "ECPage.getState().result && ECPage.getState().result.results[0].key.nHs", 46)
            await page.ev("document.querySelector('[data-tab=\"histogram\"]').click()")
            await asyncio.sleep(1.0)
            check('with HSForsmark every row is a dot on a curve',
                  await page.ev("document.getElementById('ecChartHist').data.filter((t) => t.mode === 'markers' && t.xaxis === 'x')"
                                ".reduce((s, t) => s + t.x.length, 0)"), await page.ev(f"{state}.result.results[0].key.nFailRows"))
            # Equal shares of the failures: here every canister fails for the
            # highest value alone, which no cut can split.
            await choose('#ecHistBy', 'hsq')
            check('colouring by equal shares shows the Divisions', await page.ev("!document.getElementById('ecHistDiv').hidden"), True)
            check('one value gives every failure: one group, its legend entry that value and 100 %',
                  await page.ev(f"(() => {{ const l = {LEGEND_TEXTS}; const r = {HS_ROWS};"
                                " return l.length === 1 && l[0] === r[0][0] + ': 100 %' && r[0][1] === '1' && !r[0][0].includes('–'); })()"), True)
            check('and the table says why there are fewer groups than asked for',
                  await page.ev("document.getElementById('ecDecadeNote').textContent.startsWith('The sulphide values that fail a canister, in 1 group, not 5: a group cannot split a sulphide value')"), True)
            check('with the values that fail no canister in its last row',
                  await page.ev(f"(() => {{ const r = {HS_ROWS}; return r.length === 2 && r[1][0].endsWith('failing no canister') && r[1][3] === '0 %'"
                                " && r[0][3] === '100 %'; })()"), True)
            # By percentile: 46 values put the highest at P97.8, so P99 and up hold none.
            await choose('#ecHistBy', 'hsp')
            check('colouring by percentiles shows the Percentiles, not the Divisions',
                  await page.ev("[!document.getElementById('ecHistPctBox').hidden, document.getElementById('ecHistPctTextBox').hidden, document.getElementById('ecHistDiv').hidden].join()"),
                  'true,true,true')
            check('HSForsmark leaves P99.9–P100 and P99–P99.9 without values, and the table says why',
                  await page.ev(f"(() => {{ const r = {HS_ROWS}; return r.length === 5 && r[0][1] === 'no values' && r[1][1] === 'no values' && r[2][0] === 'P90–P99'; }})()")
                  and await page.ev("document.getElementById('ecDecadeNote').textContent.includes('2 of the groups hold no value: with 46 values the highest lies at P97.8')"), True)
            check('and the legend only the groups that hold values',
                  await page.ev(f"{LEGEND_TEXTS}.map((t) => t.split(':')[0]).join()"), 'P90–P99,P50–P90,P0–P50')
            # A long table of failure times shows its first rows.
            await sulphide_values(10000)
            await page.ev("document.querySelector('[data-tab=\"failures\"]').click()")
            await asyncio.sleep(0.8)
            n10 = await page.ev(f"{state}.result.table.length")
            check('a long failure table shows its first 300 rows',
                  await page.ev("document.querySelectorAll('#ecFailTable tbody tr').length") == 300 and n10 > 1000, True)
            check('and says how many there are',
                  await page.ev("document.getElementById('ecFailNote').textContent"),
                  f'Showing 300 of {n10:,} rows, in the order shown; the CSV and the Excel workbook have them all.')
            await page.ev("document.querySelector('[data-on-click=\"ec:failuresMore\"]').click()")
            await asyncio.sleep(0.4)
            check('Show more adds a thousand', await page.ev("document.querySelectorAll('#ecFailTable tbody tr').length"), min(1300, n10))
            await choose('#ecHistBy', 'hsq')
            # With 10,000 values the shares come out as even as whole values
            # allow: no value is split, so a share can miss its target by as
            # much as the largest value gives, the highest one here (it fails
            # the most canisters), about 5 % of the rows.
            await page.ev("document.querySelector('[data-tab=\"histogram\"]').click()")
            await asyncio.sleep(1.0)
            top = await page.ev("(() => { const r = ECPage.getState().result; const hi = r.results[0].key.hsMax;"
                                " return 100 * r.table.filter((f) => f.hs === hi).length / r.table.length; })()")
            for k in (5, 3):
                await choose('#ecHistDivisions', str(k))
                shares = [float(t.rsplit(': ', 1)[1].rstrip(' %')) for t in await page.ev(LEGEND_TEXTS)]
                check(f'{k} divisions of 10,000 values: {k} groups of {100 / k:.3g} % of the failures, each as near as whole values allow',
                      len(shares) == k and all(abs(x - 100 / k) <= top for x in shares) and abs(sum(shares) - 100) < 0.5, True)
            check('each legend entry is the range of its group and its share, as in the table',
                  await page.ev(f"(() => {{ const l = {LEGEND_TEXTS}; const r = {HS_ROWS}; return l.length === 3 && l.every((t, i) => t === r[i][0] + ': ' + r[i][3]); }})()"), True)
            check('the groups’ shares of the values grow as they go down the concentrations',
                  await page.ev(f"(() => {{ const r = {HS_ROWS}.slice(0, 3).map((x) => parseFloat(x[2])); return r[0] < r[1] && r[1] < r[2]; }})()"), True)
            await choose('#ecHistBy', 'hs')
            check('and the Divisions go with the colouring', await page.ev("document.getElementById('ecHistDiv').hidden"), True)
            # Percentiles of 10,000 values: the tail cuts, quintiles and cuts of one's own.
            await choose('#ecHistBy', 'hsp')
            check('the tail percentiles hold 0.1, 0.9, 9, 40 and 50 % of the values',
                  await page.ev(f"{HS_ROWS}.map((x) => x[3]).join(' | ')"), '0.1 % | 0.9 % | 9 % | 40 % | 50 %')
            check('each legend entry: the percentiles, the share of the failures, then the [HS⁻] range, as in the table',
                  await page.ev(f"(() => {{ const l = {LEGEND_TEXTS}; const r = {HS_ROWS};"
                                " return l.length === 5 && l.every((t, i) => t === r[i][0] + ': ' + r[i][4] + r[i][1]); })()"), True)
            await choose('#ecHistPct', 'quintiles')
            check('quintiles: five groups of a fifth of the values',
                  await page.ev(f"{HS_ROWS}.map((x) => x[0] + ' ' + x[3]).join(' | ')"), 'P80–P100 20 % | P60–P80 20 % | P40–P60 20 % | P20–P40 20 % | P0–P20 20 %')
            await choose('#ecHistPct', 'custom')
            check('other… brings up Cut at', await page.ev("!document.getElementById('ecHistPctTextBox').hidden"), True)
            await choose('#ecHistPctText', '90; 99,9')
            check('where a comma inside a number is its decimal mark',
                  await page.ev(f"{LEGEND_TEXTS}.map((t) => t.split(':')[0]).join()"), 'P99.9–P100,P90–P99.9,P0–P90')
            await page.ev("(() => { const el = document.getElementById('ecHistPctText'); el.value = '120 5';"
                          " el.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.4)
            check('a percentile of 100 or more is refused, and the cuts stay',
                  await page.ev("!document.getElementById('ecHistPctText').validity.valid && ECPage.getState().hist.pctText === '90; 99,9'"
                                " && ECPage.getState().histogram.h.percentiles.join() === '90,99.9'"), True)
            await page.ev("(() => { const el = document.getElementById('ecHistPctText'); el.value = '90; 99,9';"
                          " el.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await choose('#ecHistPct', 'tail')
            await choose('#ecHistBy', 'hs')

            check('no script errors during the session', page.errors, [])
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})

    print(f'\n{checks} checks, {len(failures)} failed')
    if failures:
        print('\n'.join(f'  - {f}' for f in failures))
        sys.exit(1)


asyncio.run(main())
