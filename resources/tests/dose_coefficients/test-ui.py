#!/usr/bin/env python3
"""dose_coefficients.html in a real browser: does the page do the thing.

test-engine.mjs proves the arithmetic. This proves the wiring: that the page
loads without a script error, that its tab icon decodes and keeps to the kvot
mark's tones, that the catalogue of each system fills the
nuclide list, that every (i) opens its panel and closes it, that a
calculation in each system puts the coefficients in the table, that every
tab draws (charts, the model diagram, the decay chain), that a link with the
choices in its hash calculates on load, that the decay data can be the
system's own or ENSDF's (the release on the site, NNDC's archive, and a
file opened: ensdf.137 of a release, DC_ENSDF_137, checked when it is
there), that a phone-width window does not scroll sideways, and that the
full window (no site header or footer) comes and goes with its button and
is kept for the next visit.

Start a server and a browser on ports of your choice (check them first with
lsof -nP -iTCP:<port> -sTCP:LISTEN; other sessions may use 8765 and 9222):

    python3 -m http.server 8791 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
      --headless=new --remote-debugging-port=9241 --no-first-run \\
      --user-data-dir=/tmp/dctest --disable-gpu about:blank

then

    DC_HTTP_PORT=8791 DC_CDP_PORT=9241 python3 resources/tests/dose_coefficients/test-ui.py

Exit status is 0 when every check passes.
"""
import asyncio
import re
import csv
import io
import json
import os
import sys
import tempfile
import urllib.request
import zipfile

import websockets

HTTP = int(os.environ.get('DC_HTTP_PORT', '8765'))
CDP = int(os.environ.get('DC_CDP_PORT', '9222'))
URL = f'http://127.0.0.1:{HTTP}/dose_coefficients.html'

failures = []
checks = 0

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


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


def workbook_styles(styles_xml, sheet_xml):
    """Whether the first sheet's header cells are bold and its first value is in 0.0E+00."""
    import xml.etree.ElementTree as ET
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    st, sh = ET.fromstring(styles_xml), ET.fromstring(sheet_xml)
    fonts = [f.find('m:b', ns) is not None for f in st.find('m:fonts', ns)]
    nf = st.find('m:numFmts', ns)
    codes = {f.get('numFmtId'): f.get('formatCode') for f in (list(nf) if nf is not None else [])}
    xfs = [(int(x.get('fontId', 0)), x.get('numFmtId', '0')) for x in st.find('m:cellXfs', ns)]
    rows = sh.find('m:sheetData', ns).findall('m:row', ns)
    style = lambda c: xfs[int(c.get('s', 0))]
    head = rows[0].findall('m:c', ns)
    value = next(c for c in rows[1].findall('m:c', ns) if c.get('t') is None and c.find('m:v', ns) is not None)
    return all(fonts[style(c)[0]] for c in head) and codes.get(style(value)[1]) == '0.0E+00' and not fonts[style(value)[0]]


class Page:
    def __init__(self, ws):
        self.ws = ws
        self.n = 0
        self.pending = {}
        self.errors = []
        self.issues = []  # Audits.issueAdded, such as a control inside a <summary>

    async def pump(self):
        async for raw in self.ws:
            r = json.loads(raw)
            if 'id' in r and r['id'] in self.pending:
                self.pending.pop(r['id']).set_result(r)
            elif r.get('method') == 'Runtime.exceptionThrown':
                d = r['params']['exceptionDetails']
                self.errors.append(d.get('exception', {}).get('description') or d.get('text'))
            elif r.get('method') == 'Audits.issueAdded':
                self.issues.append(r['params']['issue'])
            elif r.get('method') == 'Runtime.consoleAPICalled' and r['params'].get('type') == 'error':
                # the page's action dispatcher reports a failing handler here
                self.errors.append(' '.join(str(a.get('value', a.get('description', ''))) for a in r['params']['args']))

    async def call(self, method, params=None):
        self.n += 1
        fut = asyncio.get_event_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send(json.dumps({'id': self.n, 'method': method, 'params': params or {}}))
        return await asyncio.wait_for(fut, 300)

    async def ev(self, expr, wait=False):
        r = await self.call('Runtime.evaluate', {'expression': expr, 'awaitPromise': wait, 'returnByValue': True})
        return r['result'].get('result', {}).get('value')

    async def until(self, expr, seconds=120):
        for _ in range(int(seconds * 10)):
            if await self.ev(expr):
                return True
            await asyncio.sleep(0.1)
        return False


async def main():
    req = urllib.request.Request(f'http://127.0.0.1:{CDP}/json/new?about:blank', method='PUT')
    tab = json.loads(urllib.request.urlopen(req).read())
    async with websockets.connect(tab['webSocketDebuggerUrl'], max_size=2 ** 27) as ws:
        p = Page(ws)
        asyncio.ensure_future(p.pump())
        for m in ('Runtime.enable', 'Page.enable', 'Network.enable', 'Audits.enable'):
            await p.call(m)
        await p.call('Network.setCacheDisabled', {'cacheDisabled': True})
        # The workers fetch their modules themselves, past the page's switch: an
        # earlier run's copies would otherwise stay in the profile's cache.
        await p.call('Network.clearBrowserCache')
        await p.call('Emulation.setDeviceMetricsOverride', {'width': 1400, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
        # Start from no saved settings: clear them on the page's own origin, then reload.
        await p.call('Page.navigate', {'url': URL})
        await p.until("document.readyState === 'complete'", 30)
        await p.ev("try { localStorage.removeItem('kvot.dose'); localStorage.removeItem('kvot.dose.full') } catch (e) {}")
        await p.call('Page.navigate', {'url': URL})
        loaded = await p.until("document.getElementById('dcNuclideCount') && /nuclides/.test(document.getElementById('dcNuclideCount').textContent)", 60)
        check('the ICRP 103 catalogue loads', loaded)
        n103 = await p.ev("parseInt(document.getElementById('dcNuclideCount').textContent)")
        check('it lists the 900-odd nuclides of 91 elements', (n103 or 0) >= 880)

        # The tab icon: the ICRP's letters in the kvot mark's language (scripts/gen-dose-icon.py), the SVG first with a
        # PNG for what will not take one and a touch icon. Each must decode as a picture (an SVG whose comment holds
        # "--" is not XML, and the browser silently drops it), and the drawing keeps to the mark's three tones.
        icon = await p.ev("""(async () => {
          const links = Object.fromEntries([...document.querySelectorAll('link[rel~="icon"], link[rel="apple-touch-icon"]')]
            .map((l) => [l.rel, [l.getAttribute('href'), l.type || '']]));
          const load = (src) => new Promise((ok) => { const i = new Image(); i.onload = () => ok([i.naturalWidth, i.naturalHeight]); i.onerror = () => ok(null); i.src = src; });
          const svg = await (await fetch(links.icon[0], { cache: 'no-store' })).text();
          const doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
          return { links, svg: await load(links.icon[0]), png: await load(links['alternate icon'][0]), touch: await load(links['apple-touch-icon'][0]),
            xml: !doc.querySelector('parsererror'), title: doc.querySelector('svg > title')?.textContent,
            fills: [...new Set([...svg.matchAll(/fill="(#[0-9a-f]{6})"/gi)].map((m) => m[1].toLowerCase()))].sort(),
            gradient: /<(linear|radial)Gradient/.test(svg) };
        })()""", wait=True)
        check('the tab icon: the SVG first, a 32-pixel PNG for what will not take one, and a touch icon; each decodes',
              (icon['links'], icon['svg'] is not None, icon['png'], icon['touch'], icon['xml']),
              ({'icon': ['./resources/images/dose-icon.svg', 'image/svg+xml'], 'alternate icon': ['./resources/images/dose-icon-32.png', 'image/png'],
                'apple-touch-icon': ['./resources/images/dose-icon-180.png', '']}, True, [32, 32], [180, 180], True))
        check('... drawn in the kvot mark’s three tones only, without gradients, and named for the page',
              (icon['fills'], icon['gradient'], icon['title']), (['#344126', '#bb6c5d', '#f3b87b'], False, 'Dose Coefficients'))

        # Every (i) opens a panel with a title and closes again.
        keys = await p.ev("[...document.querySelectorAll('.kvot-info-slot')].map(s => s.dataset.infoKey)")
        opened = 0
        for k in keys:
            ok = await p.ev(f"""(() => {{
              const b = document.querySelector('[data-info-key="{k}"] button');
              if (!b) return false;
              b.click();
              const panel = document.getElementById('kvot-info-panel');
              const t = panel && !panel.hidden && panel.querySelector('h2, h3, .kvot-info-title');
              const okk = !!(t && t.textContent.trim());
              b.click();
              return okk;
            }})()""")
            opened += 1 if ok else 0
        check(f'all {len(keys)} (i) open a titled panel', opened, len(keys))
        # Each panel says more than a line: facts or sections, and where Help goes on.
        thin = await p.ev("""(() => [...document.querySelectorAll('.kvot-info-slot')].map(s => s.dataset.infoKey).filter((k) => {
          const b = document.querySelector(`[data-info-key="${k}"] button`); b.click();
          const panel = document.getElementById('kvot-info-panel');
          const rich = panel.querySelectorAll('.info-panel-body li, .info-panel-body dt, .info-panel-body h3').length >= 3;
          const more = !!panel.querySelector('.info-panel-more');
          b.click(); return !(rich && more); }))()""")
        check('every (i) panel gives context (facts or sections) and a link to Help', thin, [])
        went = await p.ev("""(() => { document.querySelector('[data-info-key="set:amad"] button').click();
          document.querySelector('#kvot-info-panel .info-panel-more').click();
          return !document.getElementById('pane-help').hidden; })()""")
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"coef\"]').click()")
        check('a panel’s Help link opens the Help tab', went)
        # An open panel follows the settings: the system's current choice, the tolerance chosen.
        current = "(() => { const d = document.querySelector('#kvot-info-panel dt.is-current'); return d ? d.textContent : null; })()"
        await p.ev("document.querySelector('[data-info-key=\"sec:system\"] button').click()")
        before = await p.ev(current)
        await p.ev("(() => { const r = document.querySelector('input[name=\"dcSystem\"][value=\"60\"]'); r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); })()")
        await p.until("/ICRP 60 system/.test(document.getElementById('dcStatus').textContent)", 60)
        after = await p.ev(current)
        await p.ev("(() => { const r = document.querySelector('input[name=\"dcSystem\"][value=\"103\"]'); r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); })()")
        await p.until("/ICRP 103 system/.test(document.getElementById('dcStatus').textContent)", 60)
        back = await p.ev(current)
        await p.ev("document.querySelector('[data-info-key=\"set:rtol\"] button').click()")
        chosen = "(() => { const dt = [...document.querySelectorAll('#kvot-info-panel dt')].find((d) => d.textContent === 'Chosen'); return dt ? dt.nextElementSibling.textContent : null; })()"
        await p.ev("(() => { const s = document.getElementById('dcRtol'); s.value = '1e-4'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
        rtol = await p.ev(chosen)
        await p.ev("(() => { const s = document.getElementById('dcRtol'); s.value = '1e-6'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
        rtol_back = await p.ev(chosen)
        await p.ev("document.querySelector('[data-info-key=\"set:rtol\"] button').click()")
        check('an open panel follows the settings: the system’s current choice (103 → 60 → 103) and the tolerance chosen',
              [before, after, back, rtol, rtol_back] == ['ICRP 103', 'ICRP 60', 'ICRP 103', '1E-4', '1E-6'])

        # No control inside a <summary>, by Chrome's rule: a section heading's (i) is in the slot before its
        # <details>, centred on the heading's line at its end, opens its panel without folding the section,
        # and comes just before its heading in the tab order.
        check('no summary holds a control (Chrome: interactive element within a <summary>)', await p.ev(NO_CONTROL_IN_SUMMARY), '')
        check('KvotInfo.audit() finds no slot inside a summary', await p.ev("KvotInfo.audit().inSummary"), [])
        check('each heading’s (i) sits on its line, at its end', await p.ev(HEADING_I_OFF % '.kvot-info-sec'), '')
        summary_issues = [i for i in p.issues if i.get('code') == 'ElementAccessibilityIssue'
                          and (i.get('details', {}).get('elementAccessibilityIssueDetails', {}).get('elementAccessibilityIssueReason')) == 'InteractiveContentSummaryDescendant']
        check('Chrome reports no interactive element inside a summary (Audits)', len(summary_issues), 0)
        kept = await p.ev("""(() => { const d = document.querySelector('[data-info-key="sec:system"] + details'); const b = document.querySelector('[data-info-key="sec:system"] button');
          const was = d.open; b.click(); const panel = document.getElementById('kvot-info-panel'); const shown = panel && !panel.hidden;
          b.click(); return shown && d.open === was; })()""")
        check('a heading’s (i) opens its panel and leaves its section as it was', kept)
        await p.ev("document.querySelector('[data-info-key=\"sec:intake\"] button').focus()")
        await p.call('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Tab', 'code': 'Tab', 'windowsVirtualKeyCode': 9})
        await p.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Tab', 'code': 'Tab', 'windowsVirtualKeyCode': 9})
        await asyncio.sleep(0.2)
        check('Tab goes from a heading’s (i) to its heading', await p.ev("document.activeElement === document.querySelector('[data-info-key=\"sec:intake\"] + details > summary')"))

        # The Model tab's activity in the body: what its controls and boxes show.
        BUCKETS = """(() => { const nodes = [...document.querySelectorAll('#dcDiagram .node[data-share]')];
          return { row: !document.getElementById('dcBuckets').hidden, show: document.getElementById('dcModelShow').value,
            options: [...document.getElementById('dcModelShow').options].map((o) => [o.value, o.disabled, o.textContent]),
            doseShown: !document.getElementById('dcModelDose').hidden, fromShown: !document.getElementById('dcModelFrom').hidden,
            time: document.getElementById('dcBucketsTime').textContent, play: document.getElementById('dcBucketsPlay').textContent,
            note: document.getElementById('dcBucketsNote').textContent, filled: document.querySelector('#dcDiagram svg').classList.contains('buckets'),
            shares: Object.fromEntries(nodes.map((n) => [n.dataset.names, +n.dataset.share])),
            chips: Object.fromEntries([...document.querySelectorAll('#dcBucketsExtra .dc-chip')].map((c) => [c.dataset.place, +c.dataset.share])),
            levels: [...document.querySelectorAll('#dcDiagram .node .level')].filter((l) => l.getAttribute('d')).length,
            tip: [...document.querySelectorAll('#dcDiagram .node')].find((n) => n.dataset.names === 'Muscle')?.getAttribute('data-tip') || '' }; })()"""

        async def slide(i):
            await p.ev(f"(() => {{ const s = document.getElementById('dcBucketsT'); s.value = '{i}'; s.dispatchEvent(new Event('input', {{ bubbles: true }})); }})()")
            await asyncio.sleep(0.2)

        async def view(show, dose='received', frm='member'):
            await p.ev(f"""(() => {{ document.getElementById('dcModelDose').value = '{dose}'; document.getElementById('dcModelFrom').value = '{frm}';
              const s = document.getElementById('dcModelShow'); s.value = '{show}'; s.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()""")
            await asyncio.sleep(0.2)

        async def model_age(a):
            await p.ev(f"(() => {{ const s = document.getElementById('dcModelAge'); s.value = '{a}'; s.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()")
            await asyncio.sleep(0.2)

        def whole(got):
            return sum(got['shares'].values()) + sum(got['chips'].values()) if got else 0

        async def calculate(nuclide, route, form_match):
            await p.ev(f"""(() => {{
              const i = document.getElementById('dcNuclide'); i.value = {json.dumps(nuclide)};
              i.dispatchEvent(new Event('change', {{ bubbles: true }}));
              const r = document.querySelector('input[name="dcRoute"][value="{route}"]'); r.checked = true;
              r.dispatchEvent(new Event('change', {{ bubbles: true }}));
              const s = document.getElementById('dcForm');
              const o = [...s.options].find(o => {json.dumps(form_match)} === '' || o.textContent.includes({json.dumps(form_match)}));
              if (o) {{ s.value = o.value; s.dispatchEvent(new Event('change', {{ bubbles: true }})); }}
              document.getElementById('dcRun').click();
            }})()""")
            return await p.until("document.getElementById('dcStatus').classList.contains('ok') || document.getElementById('dcStatus').classList.contains('error')", 240)

        async def adult():
            return await p.ev("(() => { const rows = [...document.querySelectorAll('#dcETable tbody tr')]; const a = rows.find(r => r.cells[0].textContent.startsWith('Adult')); return a ? a.cells[1].textContent : null; })()")

        # Before any run: the foot of the settings sums up the model, each cut-off says how many nuclides it keeps,
        # and the Model and Decay chain tabs show the choice as it will be calculated.
        await p.ev("""(() => { const i = document.getElementById('dcNuclide'); i.value = 'Ra-226';
          i.dispatchEvent(new Event('change', { bubbles: true }));
          const r = document.querySelector('input[name="dcRoute"][value="ingestion"]'); r.checked = true;
          r.dispatchEvent(new Event('change', { bubbles: true })); })()""")
        shown = await p.until("!document.getElementById('dcSize').hidden && /12 nuclides/.test(document.getElementById('dcSizeSum').textContent)", 30)
        summ = await p.ev("document.getElementById('dcSizeSum').textContent")
        check(f'choosing Ra-226 sums up its model before any run: {summ}', shown and '610 compartments' in summ and '1,782 equations' in summ)
        opts = await p.ev("[...document.getElementById('dcCutoff').options].map(o => o.textContent)")
        check('each cut-off says how many nuclides it keeps (whole chain 14, 0.01 % 12)', bool(opts) and opts[0].endswith('(14 nuclides)') and any(o.startswith('0.01 %') and o.endswith('(12 nuclides)') for o in opts))
        body = await p.ev("(() => { document.getElementById('dcSize').open = true; return document.getElementById('dcSizeBody').innerText; })()")
        check('the details name the chain, the transfers, the equations and the runs', all(w in (body or '') for w in ('Po-210', '782 transfers', '293 groups', '43 target regions of each sex', '5,622 coefficients', 'integrations')))
        await p.ev("document.getElementById('dcSize').open = false")
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"model\"]').click()")
        await asyncio.sleep(0.6)
        check('the Model tab shows the chosen nuclide’s model before any run, and says so',
              await p.ev("!document.getElementById('dcModel').hidden && document.querySelectorAll('#dcDiagram svg .node').length >= 10 && /Ra-226/.test(document.getElementById('dcModelHead').textContent) && /not calculated yet/.test(document.getElementById('dcModelHead').textContent)"))
        got = await p.ev(BUCKETS)
        check('a model not yet calculated shows the model only: activity and dose wait for Calculate',
              bool(got) and not got['row'] and got['show'] == 'model' and [o[1] for o in got['options']] == [False, True, True] and all(o[2].endswith('(after Calculate)') for o in got['options'][1:]))
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"chain\"]').click()")
        await asyncio.sleep(0.6)
        check('the Decay chain tab lists its 12 nuclides before any run', await p.ev("document.querySelectorAll('#dcChainTable tbody tr').length"), 12)
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"coef\"]').click()")
        # Stop ends a run whose ages are in several workers at once; the next run (Cs-137) starts afresh.
        await p.ev("document.getElementById('dcRun').click()")
        await asyncio.sleep(0.5)
        await p.ev("document.getElementById('dcStop').click()")
        await asyncio.sleep(0.3)
        check('Stop ends a run of several workers at once', await p.ev("document.getElementById('dcStatus').textContent === 'Stopped.' && !document.getElementById('dcRun').disabled && document.getElementById('dcStop').hidden"))

        done = await calculate('Cs-137', 'ingestion', 'chloride')
        check('ICRP 103 Cs-137 ingestion calculates', done and await p.ev("document.getElementById('dcStatus').classList.contains('ok')"))
        check('six ages in the table', await p.ev("document.querySelectorAll('#dcETable tbody tr').length"), 6)
        a = await adult()
        check('adult e(50) is 1.4E-08 within rounding (ICRP 158: 1.4E-08)', a in ('1.3E-08', '1.4E-08'))
        check('equivalent doses for the tissues', (await p.ev("document.querySelectorAll('#dcHTable tbody tr').length") or 0) >= 30)
        # A changed setting marks the results as not of the current settings, and dims them, until they are again.
        stale = "(() => { const n = document.getElementById('dcCoefStale'); return n.hidden ? null : [n.textContent, document.getElementById('dcCoef').classList.contains('dc-stale')]; })()"
        check('the results are of the current settings', await p.ev(stale), None)
        await p.ev("(() => { const i = document.getElementById('dcNuclide'); i.value = 'Sr-90'; i.dispatchEvent(new Event('change', { bubbles: true })); })()")
        await asyncio.sleep(0.3)
        got = await p.ev(stale)
        check('changing the nuclide marks the coefficients as not of the current settings, and dims them', bool(got) and 'the radionuclide (now Sr-90)' in got[0] and got[1])
        await p.ev("document.querySelector('#dcAges input[value=\"100\"]').click()")
        await asyncio.sleep(0.2)
        got = await p.ev(stale)
        check('and an age at intake too', bool(got) and 'the radionuclide (now Sr-90) and the ages at intake have changed' in got[0])
        await p.ev("""(() => { const i = document.getElementById('dcNuclide'); i.value = 'Cs-137'; i.dispatchEvent(new Event('change', { bubbles: true }));
          const s = document.getElementById('dcForm'); const o = [...s.options].find(o => o.textContent.includes('chloride'));
          if (o) { s.value = o.value; s.dispatchEvent(new Event('change', { bubbles: true })); }
          document.querySelector('#dcAges input[value="100"]').click(); })()""")
        await asyncio.sleep(0.3)
        check('set back as they were, the results are of the current settings again', await p.ev(stale), None)

        for tab in ('retention', 'model', 'chain', 'help', 'coef'):
            await p.ev(f"document.querySelector('.dc-tabs button[data-tab=\"{tab}\"]').click()")
            await asyncio.sleep(0.8)
            check(f'the {tab} tab is shown', await p.ev(f"!document.getElementById('pane-{tab}').hidden"))
            if tab == 'retention':
                check('three charts with data', await p.ev("['dcPlotRet','dcPlotExc','dcPlotDose'].every(id => (document.getElementById(id).data || []).length > 0)"))
                # One nuclide at a time, per Bq of the parent taken in; the dose with the curves it is the sum of.
                nucs = await p.ev("[...document.getElementById('dcRetNuclide').options].map(o => o.textContent)")
                await p.ev("(() => { const s = document.getElementById('dcRetNuclide'); s.value = '1'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
                await asyncio.sleep(0.5)
                titles = await p.ev("['dcPlotRet', 'dcPlotExc'].map(id => document.getElementById(id).layout.title.text)")
                check('activity and excretion are of one nuclide at a time, per Bq of the parent: Ba-137m after Cs-137',
                      nucs == ['Cs-137, taken in', 'Ba-137m'] and bool(titles) and titles[0].startswith('Activity of Ba-137m') and 'of 1 Bq of Cs-137' in titles[0] and titles[1].startswith('Daily excretion of Ba-137m'))
                await p.ev("(() => { const s = document.getElementById('dcRetNuclide'); s.value = '0'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
                sums = {}
                for split in ('region', 'source', 'member', 'tissue'):
                    await p.ev(f"(() => {{ const s = document.getElementById('dcRetSplit'); s.value = '{split}'; s.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()")
                    await asyncio.sleep(0.4)
                    sums[split] = await p.ev("""(() => { const d = document.getElementById('dcPlotDose').data; const k = d[0].y.length - 1;
                      const parts = d.slice(1).reduce((a, t) => a + (t.y[k] || 0), 0); return [d.length - 1, Math.abs(parts / d[0].y[k] - 1)]; })()""")
                await p.ev("(() => { const s = document.getElementById('dcRetSplit'); s.value = 'region'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
                await asyncio.sleep(0.4)
                good = all(v and v[0] >= 1 and v[1] < 1e-9 for v in sums.values())
                if not good:
                    print('      dose parts:', sums)
                check('the effective dose comes with the curves it is the sum of: by body region, source region, chain member and tissue', good)
                # The values at the pointer: the page's own box, opaque, largest first (Plotly's lists the traces in their order).
                await p.ev("document.getElementById('dcPlotDose').scrollIntoView({block: 'center'})")
                await asyncio.sleep(0.3)
                xy = await p.ev("(() => { const r = document.querySelector('#dcPlotDose .nsewdrag').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
                await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': xy[0], 'y': xy[1]})
                await asyncio.sleep(0.6)
                fill = await p.ev("(() => { const t = document.querySelector('.dc-plot-tip.on'); return t ? getComputedStyle(t).backgroundColor : null; })()")
                bg = await p.ev("(() => { const s = document.createElement('span'); s.style.color = getComputedStyle(document.documentElement).getPropertyValue('--bg-primary'); document.body.append(s); const c = getComputedStyle(s).color; s.remove(); return c; })()")
                check('the hover box of the dose chart has the page background', fill, bg)
                check('Plotly’s own hover box is hidden', await p.ev("(() => { const l = document.querySelector('#dcPlotDose .hoverlayer .legend'); return !l || getComputedStyle(l).visibility === 'hidden'; })()"))
                await p.ev("document.getElementById('dcPlotRet').scrollIntoView({block: 'center'})")
                await asyncio.sleep(0.3)
                for frac in (0.15, 0.5, 0.85):
                    xy = await p.ev(f"(() => {{ const r = document.querySelector('#dcPlotRet .nsewdrag').getBoundingClientRect(); return [r.left + r.width * {frac}, r.top + r.height / 2]; }})()")
                    await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': xy[0], 'y': xy[1]})
                    await asyncio.sleep(0.4)
                    vals = await p.ev("[...document.querySelectorAll('.dc-plot-tip.on td.num')].map(td => Number(td.textContent))")
                    names = await p.ev("[...document.querySelectorAll('.dc-plot-tip.on tr td:nth-child(2)')].map(td => td.textContent)")
                    shares = await p.ev("[...document.querySelectorAll('.dc-plot-tip.on td.pct')].map(td => td.textContent)")
                    good = bool(vals) and len(vals) >= 3 and all(a >= b for a, b in zip(vals, vals[1:])) and names[0] == 'Whole body'
                    # The regions' shares of the whole body, dimmed in brackets; the whole body has none.
                    parsed = [float(x.strip('()% <')) for x in (shares or [])[1:] if x]
                    good = good and bool(shares) and shares[0] == '' and all(x.startswith('(') and x.endswith(' %)') for x in shares[1:]) and 98.5 <= sum(parsed) <= 101.5
                    good = good and await p.ev("getComputedStyle(document.querySelector('.dc-plot-tip.on td.pct')).color !== getComputedStyle(document.querySelector('.dc-plot-tip.on td.num')).color")
                    if not good:
                        print('      hover rows:', list(zip(names or [], vals or [], shares or [])))
                    check(f'the activity chart lists the values at the pointer largest first, with each region’s share of the whole body ({int(frac * 100)} % across)', good)
                await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 2, 'y': 2})
                await asyncio.sleep(0.3)
                check('the box goes when the pointer leaves the chart', await p.ev("!document.querySelector('.dc-plot-tip.on')"))
                for theme in ('dark', 'light'):
                    await p.ev(f"document.documentElement.setAttribute('data-theme', '{theme}'); document.documentElement.dispatchEvent(new CustomEvent('kvot-theme-change', {{detail: {{theme: '{theme}'}}}}))")
                    await asyncio.sleep(0.6)
                    check(f'the charts redraw in the {theme} theme\'s colours', await p.ev("(() => { const css = getComputedStyle(document.documentElement); const t = css.getPropertyValue('--text-primary').trim(), b = css.getPropertyValue('--bg-primary').trim(); return ['dcPlotRet','dcPlotExc','dcPlotDose'].every(id => { const l = document.getElementById(id).layout; return l.font.color === t && l.paper_bgcolor === b; }); })()"))
                    # The line that follows the pointer, and the band Plotly lays under it, in the theme's colours (not white).
                    await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 2, 'y': 2})
                    await p.ev("document.getElementById('dcPlotDose').scrollIntoView({block: 'center'})")
                    await asyncio.sleep(0.3)
                    xy = await p.ev("(() => { const r = document.querySelector('#dcPlotDose .nsewdrag').getBoundingClientRect(); return [r.left + r.width * 0.6, r.top + r.height / 2]; })()")
                    await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': xy[0], 'y': xy[1]})
                    await asyncio.sleep(0.5)
                    spikes = await p.ev("[...document.querySelectorAll('#dcPlotDose .spikeline')].map(l => getComputedStyle(l).stroke)")
                    good = bool(spikes) and (theme == 'light' or 'rgb(255, 255, 255)' not in spikes)
                    if not good:
                        print('      spike lines:', spikes)
                    check(f'the line at the pointer has no white band in the {theme} theme', good)
            if tab == 'model':
                nodes = await p.ev("document.querySelectorAll('#dcDiagram svg .node').length")
                if (nodes or 0) < 10:
                    print('      nodes', nodes, '| member', await p.ev("document.getElementById('dcModelMember').value"),
                          '| model text:', await p.ev("document.getElementById('dcModelText').textContent.slice(0, 160)"),
                          '| headline:', await p.ev("document.getElementById('dcHeadline').textContent.slice(0, 80)"))
                check('the model is drawn', (nodes or 0) >= 10)
                check('its transfers are tabulated', (await p.ev("document.querySelectorAll('#dcTransfers tbody tr').length") or 0) >= 20)
                onward = await p.ev("""(() => ({ dashed: [...document.querySelectorAll('#dcDiagram .edge-g.tract')].map((g) => g.dataset.t),
                  rows: [...document.querySelectorAll('#dcTransfers tr.tract')].map((r) => r.dataset.t),
                  dash: getComputedStyle(document.querySelector('#dcDiagram .edge.tract')).strokeDasharray }))()""")
                want = {'UB contents→Urine', 'RS contents→Faeces', 'SI contents→Blood'}
                check('after the systemic model, the alimentary tract and bladder are drawn dashed and tabulated (to faeces, to blood, to urine)',
                      bool(onward) and want <= set(onward['dashed']) and want <= set(onward['rows']) and onward['dash'] not in ('none', ''))
                check('after the run the Model tab no longer says it is not calculated', await p.ev("/Cs-137/.test(document.getElementById('dcModelHead').textContent) && !/not calculated/.test(document.getElementById('dcModelHead').textContent)"))
                check('the drawing\'s background is as wide as the drawing, not the pane',
                      await p.ev("(() => { const d = document.getElementById('dcDiagram'); return d.getBoundingClientRect().width <= d.querySelector('svg').getBoundingClientRect().width + 4; })()"))
                # The body: each numbered box has its number on a part of the body, and pointing at a box lights that part.
                pairs = await p.ev("""(() => {
                  const body = document.getElementById('dcBody'); if (body.hidden) return null;
                  const nums = [...body.querySelectorAll('.bp-num')].map(g => g.getAttribute('data-part') + '=' + g.textContent);
                  const boxes = [...document.querySelectorAll('#dcDiagram .node .badge')].map(b => b.closest('.node'));
                  const ok = boxes.every(n => n.getAttribute('data-part').split(' ').every(id => nums.some(x => x.startsWith(id + '='))));
                  return { parts: nums.length, boxes: boxes.length, key: body.querySelectorAll('.dc-body-key li').length, ok };
                })()""")
                good = bool(pairs) and pairs['ok'] and pairs['parts'] >= 8 and pairs['key'] == pairs['parts']
                if not good:
                    print('      body:', pairs)
                check('the body shows the parts of the model, numbered as its boxes and its key', good)
                await p.ev("document.querySelector('#dcDiagram .node[data-part~=\"liver\"]').scrollIntoView({block: 'center'})")
                await asyncio.sleep(0.3)
                xy = await p.ev("(() => { const r = document.querySelector('#dcDiagram .node[data-part~=\"liver\"] rect').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
                await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': xy[0], 'y': xy[1]})
                await asyncio.sleep(0.3)
                check('pointing at a liver box lights the liver and its line of the key',
                      await p.ev("document.querySelector('#dcBody .bp.liver').classList.contains('lit') && document.querySelector('#dcBody li[data-part=\"liver\"]').classList.contains('lit') && !document.querySelector('#dcBody .bp.kidneys').classList.contains('lit')"))
                # The page's own tooltip: up within 0.3 s (a native title waits about a second), in the page's colours.
                await asyncio.sleep(0.3)
                tip = await p.ev("""(() => { const t = document.querySelector('.dc-tip'), n = document.querySelector('#dcDiagram .node[data-part~="liver"]');
                  const s = document.createElement('span'); s.style.color = getComputedStyle(document.documentElement).getPropertyValue('--bg-primary'); document.body.append(s);
                  const bg = getComputedStyle(s).color; s.remove();
                  return { on: !!t && t.classList.contains('on'), text: t ? t.textContent : '', want: n.getAttribute('data-tip'), bg: t ? getComputedStyle(t).backgroundColor : '', page: bg,
                           native: document.querySelectorAll('#dcDiagram title, #dcBody title').length }; })()""")
                check('hovering a box shows its label at once in the page’s colours, and no native tooltip is left',
                      bool(tip) and tip['on'] and tip['text'] == tip['want'] and tip['bg'] == tip['page'] and tip['native'] == 0)
                await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 2, 'y': 2})
                # A row of the transfer table and its arrow light each other (and the boxes at its ends).
                lit = """(key) => ({ row: [...document.querySelectorAll('#dcTransfers tbody tr')].some(r => r.getAttribute('data-t') === key && r.classList.contains('tlit')),
                  arrow: [...document.querySelectorAll('#dcDiagram .edge-g')].some(g => g.getAttribute('data-t') === key && g.classList.contains('tlit')),
                  ends: document.querySelectorAll('#dcDiagram .node.tend').length,
                  others: [...document.querySelectorAll('[data-t].tlit')].filter(e => e.getAttribute('data-t') !== key).length })"""
                xy = await p.ev("""(() => {
                  const keys = new Set([...document.querySelectorAll('#dcDiagram .edge-g')].map(g => g.getAttribute('data-t')));
                  const r = [...document.querySelectorAll('#dcTransfers tbody tr')].find(r => keys.has(r.getAttribute('data-t')));
                  r.scrollIntoView({block: 'center'}); const b = r.getBoundingClientRect(); return [b.left + 20, b.top + b.height / 2, r.getAttribute('data-t')];
                })()""")
                await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': xy[0], 'y': xy[1]})
                await asyncio.sleep(0.3)
                got = await p.ev(f"({lit})({json.dumps(xy[2])})")
                check('pointing at a row of the transfer table lights its arrow and the boxes at its ends',
                      bool(got) and got['row'] and got['arrow'] and got['ends'] >= 1 and got['others'] == 0)
                xy = await p.ev("""(() => {
                  const d = document.getElementById('dcDiagram'); d.scrollIntoView({block: 'start'});
                  for (const g of document.querySelectorAll('#dcDiagram .edge-g')) {
                    const path = g.querySelector('.edge'), L = path.getTotalLength();
                    for (const f of [0.5, 0.4, 0.6, 0.3, 0.7]) {
                      const pt = path.getPointAtLength(L * f), m = path.getScreenCTM();
                      const x = pt.x * m.a + pt.y * m.c + m.e, y = pt.x * m.b + pt.y * m.d + m.f;
                      const hit = document.elementFromPoint(x, y)?.closest('[data-t]');
                      if (hit === g) return [x, y, g.getAttribute('data-t')];
                    }
                  }
                  return null;
                })()""")
                if xy:
                    await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': xy[0], 'y': xy[1]})
                    await asyncio.sleep(0.3)
                    got = await p.ev(f"({lit})({json.dumps(xy[2])})")
                check('pointing at an arrow lights its row of the transfer table', bool(xy) and bool(got) and got['row'] and got['arrow'] and got['others'] == 0)
                # Pointing at a box: its transfers in (blue) and out (the accent), arrows and rows alike, the rest dimmed.
                await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 2, 'y': 2})
                find = "[...document.querySelectorAll('#dcDiagram .node[data-names]')].find((n) => n.dataset.names.split('|').includes('SI contents'))"
                await p.ev(f"{find}.scrollIntoView({{block: 'center', inline: 'center'}})")
                await asyncio.sleep(0.3)
                xy = await p.ev(f"(() => {{ const r = {find}.querySelector('rect').getBoundingClientRect(); return [r.left + 24, r.top + r.height / 2]; }})()")
                await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': xy[0], 'y': xy[1]})
                await asyncio.sleep(0.4)
                box = await p.ev(f"""(() => {{
                  const name = 'SI contents', node = {find}, css = (e, k) => e ? getComputedStyle(e)[k] : '';
                  const keys = (sel) => [...document.querySelectorAll(sel)].map((e) => e.dataset.t).sort().join(',');
                  const want = (sel, side) => [...document.querySelectorAll(sel)].map((e) => e.dataset.t)
                    .filter((k) => {{ const [a, b] = k.split('→'); return side === 'in' ? b === name && a !== name : a === name && b !== name; }}).sort().join(',');
                  const s = document.createElement('span'); s.style.color = 'var(--text-primary)'; document.getElementById('dcModel').append(s);
                  const ink = getComputedStyle(s).color; s.remove();
                  const eIn = document.querySelector('#dcDiagram .edge-g.tin .edge'), eOut = document.querySelector('#dcDiagram .edge-g.tout .edge');
                  const other = document.querySelector('#dcDiagram .edge-g:not(.tin):not(.tout)');
                  const idle = [...document.querySelectorAll('#dcDiagram .node')].find((n) => !n.matches('.nsel, .nend, .lit, .sink'));
                  return {{ on: document.getElementById('dcModel').classList.contains('dc-nlit') && node.classList.contains('nsel'),
                    arrowsIn: keys('#dcDiagram .edge-g.tin'), wantArrowsIn: want('#dcDiagram .edge-g', 'in'),
                    arrowsOut: keys('#dcDiagram .edge-g.tout'), wantArrowsOut: want('#dcDiagram .edge-g', 'out'),
                    rowsIn: keys('#dcTransfers tr.tin'), wantRowsIn: want('#dcTransfers tr[data-t]', 'in'),
                    rowsOut: keys('#dcTransfers tr.tout'), wantRowsOut: want('#dcTransfers tr[data-t]', 'out'),
                    strokes: [css(eIn, 'stroke'), css(eOut, 'stroke')], markers: [css(eIn, 'markerEnd'), css(eOut, 'markerEnd')],
                    other: Number(css(other, 'opacity')), idle: Number(css(idle, 'opacity')),
                    ends: [...document.querySelectorAll('#dcDiagram .node.nend')].map((n) => Number(css(n, 'opacity'))),
                    outline: css(node.querySelector('rect'), 'stroke'), ink,
                    tip: document.querySelector('.dc-tip.on')?.textContent || '' }};
                }})()""")
                good = (bool(box) and box['on'] and box['arrowsIn'] and box['arrowsOut']
                        and box['arrowsIn'] == box['wantArrowsIn'] and box['arrowsOut'] == box['wantArrowsOut']
                        and box['rowsIn'] == box['wantRowsIn'] and box['rowsOut'] == box['wantRowsOut'])
                if not good:
                    print('      box:', box)
                check('pointing at a box lights every transfer into it and out of it, in the drawing and in the table', good)
                n_in, n_out = (len(box['arrowsIn'].split(',')), len(box['arrowsOut'].split(','))) if good else (0, 0)
                styled = (bool(box) and box['strokes'][0] != box['strokes'][1] and 'dcArrowIn' in box['markers'][0] and 'dcArrowLit' in box['markers'][1]
                          and box['other'] < 0.5 and box['idle'] < 1 and box['ends'] and min(box['ends']) == 1 and box['outline'] == box['ink']
                          and f'{n_in} transfers in (blue), {n_out} out (red)' in box['tip'])
                if not styled:
                    print('      box:', box)
                check('in and out differ in colour and arrowhead, the rest is dimmed, the box is outlined and its label counts both', styled)
                await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 2, 'y': 2})
                await asyncio.sleep(0.2)
                check('moving off the drawing clears the box\'s highlighting',
                      await p.ev("!document.getElementById('dcModel').classList.contains('dc-nlit') && !document.querySelector('#dcModel .tin, #dcModel .tout, #dcModel .nsel, #dcModel .nend')"))
                # After the run, Show can fill the boxes, as buckets, with the activity or the dose over time.
                got = await p.ev(BUCKETS)
                check('after a calculation Show offers the activity and the dose, and shows the model at first',
                      bool(got) and got['show'] == 'model' and not got['row'] and not got['filled'] and not got['shares'] and got['levels'] == 0
                      and [o[1] for o in got['options']] == [False, False, False] and not got['doseShown'])
                await view('activity')
                await slide(45)  # 10^1.4 d: the grid has ten outputs a decade from 1E-3 d, after t = 0
                got = await p.ev(BUCKETS)
                good = (bool(got) and got['row'] and got['filled'] and got['time'] == '25 days after intake' and max(got['shares'], key=got['shares'].get) == 'Muscle'
                        and got['shares']['Muscle'] > 0.7 and 0.995 < whole(got) < 1.000001 and got['levels'] >= 10
                        and 'Bq of Cs-137 in the body per Bq taken in' in got['note'] and 'of the Cs-137 in the body' in got['tip'])
                if not good:
                    print('      buckets:', json.dumps(got)[:600], whole(got))
                check('25 days after intake the boxes hold their shares of the Cs-137 in the body, muscle the most, and with what is listed make it whole', good)
                await slide(0)
                got = await p.ev(BUCKETS)
                check('at intake all of it is in the mouth, listed under the slider as not in the drawing',
                      bool(got) and got['time'] == 'At intake' and {k: v for k, v in got['chips'].items() if v > 0} == {'r:o-cavity': 1} and sum(got['shares'].values()) == 0)
                # The drawing keeps its place as the time moves: the list and the note keep their size.
                spots = []
                for i in (0, 3, 8, 16, 25, 35, 45, 60, 74):
                    await slide(i)
                    spots.append(await p.ev("Math.round(document.getElementById('dcDiagram').getBoundingClientRect().top + window.scrollY)"))
                if len(set(spots)) != 1:
                    print('      drawing top:', spots)
                check('the drawing keeps its place on the page as the time moves (the list of what is not drawn and the note keep their size)', len(set(spots)) == 1)
                await slide(45)
                await model_age(100)
                got = await p.ev(BUCKETS)
                check('another age at intake keeps the time', bool(got) and got['time'] == '25 days after intake' and 'for an intake at the age of 3 months' in got['note'])
                await p.ev("document.getElementById('dcBucketsPlay').click()")
                await asyncio.sleep(0.8)
                moving = await p.ev(BUCKETS)
                await p.ev("document.getElementById('dcBucketsPlay').click()")
                await asyncio.sleep(0.2)
                halted = await p.ev(BUCKETS)
                await asyncio.sleep(0.4)
                still = await p.ev(BUCKETS)
                check('Run through moves the time on, and Stop halts it',
                      bool(moving) and moving['play'] == 'Stop' and moving['time'] != '25 days after intake' and halted['play'] == 'Run through' and still['time'] == halted['time'])
                # The effective dose: from the member's activity, from the whole chain's, and its rate.
                await model_age(7300)
                await view('dose', 'received', 'member')
                await slide(45)
                got = await p.ev(BUCKETS)
                good = (bool(got) and got['doseShown'] and got['fromShown'] and got['filled'] and 0.995 < whole(got) < 1.000001
                        and 'Sv per Bq taken in received from the Cs-137 in the body so far' in got['note'] and 'of the effective dose received so far' in got['tip'])
                if not good:
                    print('      dose:', json.dumps(got)[:600], whole(got))
                check('the dose received from the member so far, shared out among the boxes and what is listed', good)
                last = await p.ev("document.getElementById('dcBucketsT').max")
                await view('dose', 'received', 'chain')
                await slide(last)
                got = await p.ev(BUCKETS)
                m = re.match(r'([0-9.E+-]+) Sv per Bq taken in received from the whole chain in the body so far, of a committed effective dose of ([0-9.E+-]+) Sv', got['note'] if got else '')
                spots = []
                for i in (0, 8, 25, 45, int(last)):
                    await slide(i)
                    spots.append(await p.ev("Math.round(document.getElementById('dcDiagram').getBoundingClientRect().top + window.scrollY)"))
                await slide(last)
                # Ba-137m formed in caesium's compartments counts in their boxes, and in its own model's compartments of the same
                # name (its blood: ICRP 158 para 450 sends it there); the rest of its own model is listed apart.
                good = (bool(m) and m.group(1) == m.group(2) and 0.995 < whole(got) < 1.000001 and 'Ba-137m' in got['tip'] and 'Cs-137' in got['tip']
                        and 'm:1' in got['chips'])
                if not good:
                    print('      chain:', json.dumps(got)[:700], whole(got))
                check('from the whole chain, at the end the boxes share out the committed effective dose, Ba-137m counted in caesium’s boxes too', good)
                if len(set(spots)) != 1:
                    print('      drawing top:', spots)
                check('and there too the drawing keeps its place as the time moves', len(set(spots)) == 1)
                await view('dose', 'rate', 'member')
                await slide(45)
                got = await p.ev(BUCKETS)
                check('and the dose rate at a time, in Sv per day, shared out as well',
                      bool(got) and 'Sv per day per Bq taken in from the Cs-137 in the body' in got['note'] and 0.995 < whole(got) < 1.000001 and 'of the effective dose rate' in got['tip'])
                await view('model')
                got = await p.ev(BUCKETS)
                check('Show Model puts the boxes back as drawn and hides the slider', bool(got) and not got['row'] and not got['filled'] and not got['shares'] and got['levels'] == 0 and not got['doseShown'])
                await model_age(1825)
                check('the age at intake also sets the age of the rates on the arrows', 'transfer coefficient at the age of 5 years' in (await p.ev("document.getElementById('dcModelText').textContent") or ''))
                await model_age(7300)
            if tab == 'chain':
                check('the chain lists Cs-137 and Ba-137m', await p.ev("[...document.querySelectorAll('#dcChainTable tbody tr td:first-child')].map(t => t.textContent).join(',')"), 'Cs-137,Ba-137m')

        # Injection, and progeny with the models of the OIR sections.
        done = await calculate('Pb-210', 'injection', '')
        check('ICRP 103 Pb-210 injection calculates', done and await p.ev("document.getElementById('dcStatus').classList.contains('ok')"))
        check('the headline says taken into blood', await p.ev("document.getElementById('dcHeadline').textContent.includes('taken into blood')"))
        check('adult e(50) is 1.6E-06 (the annex of Publication 158: 1.58E-06)', await adult(), '1.6E-06')
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"chain\"]').click()")
        await asyncio.sleep(0.8)
        kinds = await p.ev("[...document.querySelectorAll('#dcChainTable tbody tr')].map(r => r.cells[0].textContent + ': ' + r.cells[r.cells.length - 1].textContent).join(' | ')")
        check('Bi-210 and Po-210 follow the models of the lead section (OIR)', 'Bi-210' in (kinds or '') and (kinds or '').count('OIR section') >= 2)
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"model\"]').click()")
        await asyncio.sleep(0.5)
        await p.ev("(() => { const s = document.getElementById('dcModelMember'); s.value = [...s.options].findIndex(o => o.textContent.startsWith('Po-210')); s.dispatchEvent(new Event('change', { bubbles: true })); })()")
        await asyncio.sleep(0.8)
        check('the Po-210 model is the one for lead chains, entering at Plasma 2',
              await p.ev("/lead chains/.test(document.getElementById('dcModelText').textContent) && /Plasma 2/.test(document.getElementById('dcModelText').textContent)"))
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"coef\"]').click()")

        # The ICRP 60 system.
        await p.ev("(() => { const r = document.querySelector('input[name=\"dcSystem\"][value=\"60\"]'); r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); })()")
        check('the ICRP 60 catalogue loads', await p.until("/ICRP 60 system/.test(document.getElementById('dcStatus').textContent)", 60))
        got = await p.ev("(() => { const n = document.getElementById('dcCoefStale'); return n.hidden ? null : n.textContent; })()")
        check('another system keeps the results on the tab, marked as of the other system',
              bool(got) and 'Pb-210' in got and 'the system (now ICRP 60)' in got and await p.ev("document.querySelectorAll('#dcETable tbody tr').length > 0"))
        await p.ev("(() => { const i = document.getElementById('dcNuclide'); i.value = 'Sr-90'; i.dispatchEvent(new Event('change', { bubbles: true })); })()")
        check('injection is not offered in the ICRP 60 system', await p.ev("document.querySelector('input[name=\"dcRoute\"][value=\"injection\"]').disabled"))
        # A disabled route is a dimmed button with a reason, not a button with the radio showing on top.
        look = await p.ev("""(() => { const r = document.querySelector('input[name="dcRoute"][value="injection"]');
          return { radio: getComputedStyle(r).opacity, span: getComputedStyle(r.nextElementSibling).opacity, title: r.closest('label').getAttribute('data-tip') || '' }; })()""")
        check('the disabled Injection button is dimmed, its radio hidden, with a tooltip saying why',
              look['radio'] == '0' and float(look['span']) < 1 and 'Not available' in look['title'])

        # The nuclide field's own suggestions: under the field, filtered, picked with the keys.
        await p.ev("(() => { const i = document.getElementById('dcNuclide'); i.value = ''; i.focus(); })()")
        await p.call('Input.insertText', {'text': 'cs13'})
        await asyncio.sleep(0.3)
        sug = await p.ev("""(() => { const i = document.getElementById('dcNuclide'), l = document.getElementById('dcNuclideList');
          const a = i.getBoundingClientRect(), b = l.getBoundingClientRect();
          return { open: !l.hidden, first: l.firstElementChild?.dataset.value, all: [...l.children].every(li => li.dataset.value.startsWith('Cs-13')),
                   under: b.top >= a.bottom - 1 && b.top - a.bottom < 8 && Math.abs(b.left - a.left) < 2 }; })()""")
        check('typing cs13 lists Cs-13x right under the field', bool(sug) and sug['open'] and sug['all'] and sug['under'])
        await p.call('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'ArrowDown', 'code': 'ArrowDown', 'windowsVirtualKeyCode': 40})
        await p.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'ArrowDown', 'code': 'ArrowDown', 'windowsVirtualKeyCode': 40})
        await p.call('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13})
        await p.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13})
        await asyncio.sleep(0.3)
        check('arrow down and Enter pick it and close the list',
              await p.ev(f"document.getElementById('dcNuclide').value === {json.dumps(sug['first'] if sug else '')} && document.getElementById('dcNuclideList').hidden && !document.getElementById('dcRun').disabled"))

        async def click(expr):
            xy = await p.ev(f"(() => {{ const r = ({expr}).getBoundingClientRect(); return [r.left + Math.min(20, r.width / 2), r.top + r.height / 2]; }})()")
            for t in ('mousePressed', 'mouseReleased'):
                await p.call('Input.dispatchMouseEvent', {'type': t, 'x': xy[0], 'y': xy[1], 'button': 'left', 'clickCount': 1})
            await asyncio.sleep(0.3)
        # Something typed, a click elsewhere, a click back in the field: the list comes back.
        await p.ev("(() => { const i = document.getElementById('dcNuclide'); i.value = ''; i.focus(); })()")
        await p.call('Input.insertText', {'text': 'Sr'})
        await asyncio.sleep(0.3)
        await click("document.getElementById('dcStatus')")
        gone = await p.ev("document.getElementById('dcNuclideList').hidden && document.activeElement !== document.getElementById('dcNuclide')")
        await click("document.getElementById('dcNuclide')")
        back = await p.ev("!document.getElementById('dcNuclideList').hidden && document.getElementById('dcNuclideList').firstElementChild?.dataset.value.startsWith('Sr-')")
        check('the list closes on a click elsewhere and comes back on a click in the field', bool(gone) and bool(back))
        await p.call('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Escape', 'code': 'Escape', 'windowsVirtualKeyCode': 27})
        await p.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Escape', 'code': 'Escape', 'windowsVirtualKeyCode': 27})
        await asyncio.sleep(0.2)
        closed = await p.ev("document.getElementById('dcNuclideList').hidden")
        await click("document.getElementById('dcNuclide')")
        check('Escape closes it, and a click in the field opens it again', bool(closed) and await p.ev("!document.getElementById('dcNuclideList').hidden"))
        done = await calculate('Sr-90', 'inhalation', 'Type M')
        check('ICRP 60 Sr-90 Type M inhalation calculates', done and await p.ev("document.getElementById('dcStatus').classList.contains('ok')"))
        check('adult e(50) is 3.6E-08 (ICRP 72: 3.6E-08)', await adult(), '3.6E-08')
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"model\"]').click()")
        await asyncio.sleep(0.6)
        await view('activity')
        await slide(45)
        got = await p.ev(BUCKETS)
        good = bool(got) and got['chips'].get('l:Alveolar-interstitial (AI)', 0) > 0.05 and 0.995 < whole(got) < 1.000001
        if not good:
            print('      buckets:', json.dumps(got)[:600], whole(got))
        check('after an inhalation the airways are listed by region beside the boxes (ICRP 60, Sr-90 Type M, 25 days)', good)
        await view('dose', 'received', 'chain')
        await slide(await p.ev("document.getElementById('dcBucketsT').max"))
        got = await p.ev(BUCKETS)
        m = re.match(r'([0-9.E+-]+) Sv per Bq taken in received from the whole chain in the body so far, of a committed effective dose of ([0-9.E+-]+) Sv', got['note'] if got else '')
        check('and in the ICRP 60 system too the whole chain shares out the committed effective dose at the end',
              bool(m) and m.group(1) == m.group(2) and 0.995 < whole(got) < 1.000001)
        await view('model')
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"coef\"]').click()")

        # The Risk tab: the detriment-adjusted coefficients recalculated, beside the printed ones.
        cells = "[...document.querySelectorAll('#dcRisk .dc-risk-sum tbody tr')].map(r => [...r.cells].map(c => c.textContent))"
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"risk\"]').click()")
        await asyncio.sleep(0.5)
        t3 = await p.ev(cells)
        check('the Risk tab recalculates Publication 60 Table 3: 5.58 and 7.30 (printed 5.6 and 7.3)',
              bool(t3) and t3[0][7:9] == ['5.58', '5.6'] and t3[1][7:9] == ['7.30', '7.3'] and t3[1][1:3] == ['5.00', '5.0'])
        await p.ev("(() => { const r = document.querySelector('input[name=\"dcSystem\"][value=\"103\"]'); r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); })()")
        await p.until("/ICRP 103 system/.test(document.getElementById('dcStatus').textContent)", 60)
        await asyncio.sleep(0.3)
        t1 = await p.ev(cells)
        check('and in the ICRP 103 system Publication 103 Table 1: cancer 5.49, heritable 0.19, total 5.74 (printed 5.5, 0.2, 5.7; Publication 60 6.0, 1.3, 7.3)',
              bool(t1) and t1[0][1:] == ['5.49', '5.5', '6.0', '0.19', '0.2', '1.3', '5.74', '5.7', '7.3'] and t1[1][7:9] == ['4.22', '4.2'])
        whole_off = await p.ev("document.querySelectorAll('#dcRisk td.dc-off').length")
        await p.ev("(() => { const r = document.querySelector('input[name=\"dcRiskPop\"][value=\"adult\"]'); r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); })()")
        await asyncio.sleep(0.3)
        adult = await p.ev("({ title: [...document.querySelectorAll('#dcRisk h3')].map(x => x.textContent).find(x => x.startsWith('Tissue by tissue:')) || '', off: document.querySelectorAll('#dcRisk td.dc-off').length, rows: document.querySelectorAll('#dcRisk .dc-risk-steps tbody tr').length })")
        check('every tissue agrees with Table A.4.1a; for adults its whole-number risks show as marked differences',
              whole_off == 0 and 'working age' in adult['title'] and adult['off'] >= 1 and adult['rows'] == 15)
        await p.ev("(() => { const r = document.querySelector('input[name=\"dcRiskPop\"][value=\"whole\"]'); r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); })()")

        # A link calculates on load.
        await p.call('Page.navigate', {'url': URL + '#system=103&nuclide=I-131&route=ingestion&form=all'})
        # The same page with another hash may not reload, so the status may still say "ok" from the
        # last calculation: wait for the new headline.
        ok = await p.until("document.getElementById('dcHeadline').textContent.includes('I-131') && document.getElementById('dcStatus').classList.contains('ok')", 120)
        if not ok:
            print('      status:', await p.ev("document.getElementById('dcStatus').textContent"), '| hash:', await p.ev("location.hash"))
        check('a link with the choices calculates I-131 on load', ok)
        # Its nominal detriment per Bq: iodine gathers in the thyroid, whose detriment share (0.022) is about half its
        # weighting factor (0.04), so tissue by tissue gives well under e times 5.7 %.
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"risk\"]').click()")
        await asyncio.sleep(0.5)
        applied = await p.ev("""(() => { const t = [...document.querySelectorAll('#dcRisk table')].find(t => /Tissue by tissue/.test(t.tHead?.textContent || ''));
          if (!t) return null; const rows = [...t.tBodies[0].rows]; return { n: rows.length, ratio: parseFloat(rows[rows.length - 1].cells[5].textContent) }; })()""")
        check('the Risk tab applies the coefficients to I-131: six ages, tissue by tissue well under e × 5.7 % (thyroid)',
              bool(applied) and applied['n'] == 6 and 0.3 < applied['ratio'] < 0.8)

        # Decay data: the system's own, or made on the site from a release of ENSDF. The choice reloads the list,
        # marks the last result as not of it, goes with a result into its headline, its link and the Decay chain tab.
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"coef\"]').click()")
        # (the Risk checks above reuse the name `adult`)
        adult_e = "(() => { const rows = [...document.querySelectorAll('#dcETable tbody tr')]; const a = rows.find(r => r.cells[0].textContent.startsWith('Adult')); return a ? a.cells[1].textContent : null; })()"
        i131 = await p.ev(adult_e)
        await p.until("[...document.querySelectorAll('#dcDecay optgroup')].some((g) => /NNDC/.test(g.label))", 20)
        opts = await p.ev("[[...document.getElementById('dcDecay').options].slice(0, 2).map((o) => [o.value, o.textContent]), [...document.querySelectorAll('#dcDecay optgroup')].map((g) => g.label)]")
        check('the Decay data setting offers ICRP 107 (the system’s own), ENSDF 2026-09-01 on this site and NNDC’s archive',
              (opts[0], opts[1][0], opts[1][-1]), ([['', 'ICRP 107, the system’s own'], ['ensdf:260901', 'ENSDF 2026-09-01']], 'ENSDF on this site', 'ENSDF at NNDC: download, then open'))
        n107 = await p.ev("parseInt(document.getElementById('dcNuclideCount').textContent)")
        await p.ev("(() => { const s = document.getElementById('dcDecay'); s.value = 'ensdf:260901'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
        await p.until("parseInt(document.getElementById('dcNuclideCount').textContent) !== %d" % (n107 or 0), 60)
        n_ens = await p.ev("parseInt(document.getElementById('dcNuclideCount').textContent)")
        check(f'with ENSDF the ICRP 103 list grows by the states ICRP 107 lacks ({n107} → {n_ens})', (n_ens or 0) > (n107 or 0) + 40)
        note = await p.ev("[document.getElementById('dcDecayNote').textContent, document.getElementById('dcCoefStale').textContent]")
        check('... a note says where the decay data come from, and the I-131 result is marked as of other decay data',
              bool(note) and 'ENSDF 2026-09-01' in note[0] and 'the decay data (now ENSDF 2026-09-01)' in note[1])
        done = await calculate('I-131', 'ingestion', '')
        ens = await p.ev(adult_e)
        head = await p.ev("[...document.querySelectorAll('#dcHeadline .dc-tag')].map((t) => t.textContent)")
        check(f'I-131 calculates with ENSDF: adult e {ens}, with ICRP 107 {i131}; the headline names the decay data',
              (done, bool(ens) and bool(i131) and abs(float(ens) / float(i131) - 1) < 0.03, head), (True, True, ['ICRP 103', 'decay data ENSDF 2026-09-01']))
        check('... its link carries the decay data', await p.ev("new URLSearchParams(location.hash.slice(1)).get('decay')"), 'ensdf:260901')
        # A state that ENSDF 2026 names otherwise keeps the ICRP name; the Decay chain tab gives ENSDF's beside it.
        await p.ev("""(() => { const i = document.getElementById('dcNuclide'); i.value = 'Ta-178m'; i.dispatchEvent(new Event('change', { bubbles: true })); })()""")
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"chain\"]').click()")
        await p.until("/Ta-178m/.test(document.getElementById('dcChainHead').textContent) && document.querySelector('#dcChainTable tbody tr')", 30)
        chain = await p.ev("""[document.querySelector('#dcChainTable tbody tr td').textContent, !document.getElementById('dcChainDecay').hidden,
          document.getElementById('dcChainDecay').textContent]""")
        check('Ta-178m keeps its ICRP name with ENSDF, which calls it Ta-178; the tab names the decay data',
              bool(chain) and chain[0] == 'Ta-178m (Ta-178)' and chain[1] and 'ENSDF 2026-09-01' in chain[2])
        await p.ev("""(() => { const i = document.getElementById('dcNuclide'); i.value = 'Bi-212m'; i.dispatchEvent(new Event('change', { bubbles: true })); })()""")
        bi = await p.ev("!!document.getElementById('dcForm').options.length && !document.getElementById('dcRun').disabled")
        await p.ev("(() => { const s = document.getElementById('dcDecay'); s.value = ''; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
        await p.until("parseInt(document.getElementById('dcNuclideCount').textContent) === %d" % (n107 or 0), 60)
        gone = await p.ev("[document.getElementById('dcRun').disabled, document.getElementById('dcNuclideNote').textContent]")
        check('Bi-212m, which only ENSDF has, can be calculated with it, and is not covered with ICRP 107',
              (bi, bool(gone) and gone[0] and gone[1].startswith('Not covered')), (True, True))
        await p.ev("""(() => { const s = document.getElementById('dcDecay'); s.value = 'ensdf:260901'; s.dispatchEvent(new Event('change', { bubbles: true }));
          const r = document.querySelector('input[name="dcSystem"][value="60"]'); r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); })()""")
        await p.until("/ICRP 60 system/.test(document.getElementById('dcStatus').textContent)", 60)
        sixty = await p.ev("[[...document.getElementById('dcDecay').options].map((o) => o.textContent), document.getElementById('dcDecay').value, document.getElementById('dcStatus').textContent]")
        check('in the ICRP 60 system the setting offers ICRP 38 and keeps ENSDF chosen',
              bool(sixty) and sixty[0][:2] == ['ICRP 38, the system’s own', 'ENSDF 2026-09-01'] and sixty[1] == 'ensdf:260901' and 'ENSDF 2026-09-01' in sixty[2])
        await p.ev("document.querySelector('[data-info-key=\"set:decay\"] button').click()")
        panel = await p.ev("document.getElementById('kvot-info-panel').textContent")  # (innerText has the headings in capitals)
        await p.ev("document.querySelector('[data-info-key=\"set:decay\"] button').click()")
        check('its (i) says what is chosen and how ENSDF is read', bool(panel) and 'ENSDF 2026-09-01' in panel and 'How ENSDF becomes decay data here' in panel)
        await p.call('Page.reload')
        await p.until("document.getElementById('dcNuclideCount') && /nuclides/.test(document.getElementById('dcNuclideCount').textContent)", 60)
        check('the choice is kept for the next visit', await p.ev("document.getElementById('dcDecay').value"), 'ensdf:260901')
        # A link names its decay data, and the Batch and Radon at home tabs have the choice of their own.
        await p.call('Page.navigate', {'url': URL + '#system=103&decay=ensdf:260901&nuclide=Cs-137&route=ingestion&form=all'})
        ok = await p.until("document.getElementById('dcHeadline').textContent.includes('Cs-137') && document.getElementById('dcHeadline').textContent.includes('ENSDF') && document.getElementById('dcStatus').classList.contains('ok')", 120)
        check('a link with decay=ensdf:260901 calculates Cs-137 with ENSDF on load', ok)
        cs_site = await p.ev(adult_e)
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"batch\"]').click()")
        await asyncio.sleep(0.3)
        check('the Batch tab has its own Decay data choice',
              await p.ev("[...document.querySelectorAll('#dcBatchDecay option')].map((o) => o.value).slice(0, 2)"), ['', 'ensdf:260901'])
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"coef\"]').click()")
        check('so has Radon at home', await p.ev("[...document.querySelectorAll('#dcRadonDecay option')].map((o) => o.value).slice(0, 2)"), ['', 'ensdf:260901'])
        # A release of NNDC's archive says where to download it.
        got = await p.ev("""(() => { const s = document.getElementById('dcDecay'); const o = [...s.options].find((x) => x.value.startsWith('nndc:'));
          if (!o) return null; s.value = o.value; s.dispatchEvent(new Event('change', { bubbles: true }));
          const d = document.getElementById('dcGet'); return [d.open, d.querySelectorAll('#dcGetBody a[href^="https://www.nndc.bnl.gov/"]').length > 0, s.value]; })()""")
        await p.ev("document.querySelector('#dcGet .dc-get-actions .dc-btn.secondary').click()")
        check('an NNDC release opens a dialog with its download link and leaves the choice as it was; Close closes it',
              (got, await p.ev("document.getElementById('dcGet').open")), ([True, True, 'ensdf:260901'], False))
        # Opening ENSDF files: the decay data are made in the browser, offered, used, and forgotten again.
        ens137 = os.environ.get('DC_ENSDF_137', os.path.expanduser('~/Downloads/icrp-dc/ensdf-dose/ensdf_260901/ensdf.137'))
        if os.path.exists(ens137):
            doc = await p.call('DOM.getDocument')
            node = await p.call('DOM.querySelector', {'nodeId': doc['result']['root']['nodeId'], 'selector': '#dcDecayFile'})
            await p.call('DOM.setFileInputFiles', {'files': [ens137], 'nodeId': node['result']['nodeId']})
            made = await p.until("document.getElementById('dcDecay').value.startsWith('open:ensdf.137|') && /nuclides/.test(document.getElementById('dcNuclideCount').textContent)", 120)
            got = await p.ev("""[parseInt(document.getElementById('dcNuclideCount').textContent), !document.getElementById('dcDecayForget').hidden,
              [...document.querySelectorAll('#dcDecay optgroup')].find((g) => /opened/.test(g.label))?.textContent || '']""")
            check(f'opening ensdf.137 makes its decay data in the browser and chooses them: {got}', made and got[0] < 20 and got[1] and 'ensdf.137 (opened' in got[2])
            done = await calculate('Cs-137', 'ingestion', '')
            opened_e = await p.ev(adult_e)
            check(f'... Cs-137 calculates with them, as with the release on the site ({opened_e}, {cs_site})', done and opened_e == cs_site)
            check('... and the release is kept where the ENSDF pages find it',
                  await p.ev("KVOT_ENSDF_SOURCES.IDB.list().then((l) => l.some((r) => r.key.startsWith('ensdf.137|')))", wait=True), True)
            await p.ev("document.getElementById('dcDecayForget').click()")
            gone = await p.until("document.getElementById('dcDecay').value === '' && ![...document.getElementById('dcDecay').options].some((o) => o.value.startsWith('open:ensdf.137|'))", 60)
            check('Forget takes it out of the menus and of the browser', gone and await p.ev("KVOT_ENSDF_SOURCES.IDB.list().then((l) => !l.some((r) => r.key.startsWith('ensdf.137|')))", wait=True))
        else:
            print(f'      (opening ENSDF files not checked: {ens137} is not here)')
        # Back to the system's own decay data for the checks after these.
        await p.ev("""(() => { const s = document.getElementById('dcDecay'); s.value = ''; s.dispatchEvent(new Event('change', { bubbles: true })); })()""")
        await p.until("!/ENSDF/.test(document.getElementById('dcStatus').textContent) && /nuclides/.test(document.getElementById('dcNuclideCount').textContent)", 60)

        # Radon at home: the inhalations run once in the worker, then the doses per exposure recombine at once.
        main = """(() => { const rows = [...document.querySelectorAll('#dcRadon .dc-radon-main tbody tr')]; if (!rows.length) return null;
          const a = rows.find(r => r.cells[0].textContent === 'Adult'), rec = rows[rows.length - 1];
          return { e: a.cells[1].textContent, eec: a.cells[2].textContent, year: rec.cells[rec.cells.length - 1].textContent }; })()"""
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"radon\"]').click()")
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"radon\"]').focus()")
        await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 900, 'y': 400})  # off the side: pointing brings it back
        await asyncio.sleep(0.4)
        check('Radon at home dims the side’s settings too, and its note names the tab',
              await p.ev("document.getElementById('dcRoot').classList.contains('dc-side-away') && /Radon at home has its own/.test(document.getElementById('dcSideNote').textContent) && !document.getElementById('dcSideNote').hidden && Number(getComputedStyle(document.querySelector('.dc-side-scroll')).opacity) < 0.6"))
        ok = await p.until("document.querySelector('#dcRadon .dc-radon-main') !== null", 180)
        got = await p.ev(main)
        check('Radon at home: the adult’s progeny 4.19 mSv per mJ h m⁻³ (Publication 158: 4.19); 300 Bq m⁻³, 7000 h with the ICRP’s 3 mSv per mJ h m⁻³: 14.0 mSv',
              bool(ok) and bool(got) and got['e'] == '4.19' and got['year'] == '14.0')
        await p.ev("(() => { const i = document.getElementById('dcRadonF'); i.value = '0.5'; i.dispatchEvent(new Event('input', { bubbles: true })); })()")
        await asyncio.sleep(0.3)
        got = await p.ev(main)
        check('a different equilibrium factor recombines at once (F 0.5: 17.5 mSv)', bool(got) and got['year'] == '17.5')
        await p.ev("(() => { const r = document.querySelector('input[name=\"dcRadonKind\"][value=\"thoron\"]'); r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); })()")
        ok = await p.until("document.querySelector('#dcRadon .dc-radon-main') !== null && /Thoron/.test(document.querySelector('#dcRadon h3').textContent)", 120)
        got = await p.ev(main)
        check('and thoron: the adult’s progeny within 6 % of Publication 158’s 86 nSv per Bq h m⁻³ of EEC, the concentration 1 Bq m⁻³ EEC',
              bool(ok) and bool(got) and abs(float(got['eec']) / 86 - 1) <= 0.06 and await p.ev("document.getElementById('dcRadonC').value") == '1')

        # The Batch tab: two nuclides by ingestion, all their forms, the adult; the table, its files, and Stop.
        downloads = tempfile.mkdtemp(prefix='dc-batch-')
        await p.call('Browser.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': downloads})
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"batch\"]').click()")
        await p.until("document.getElementById('dcBatchText') !== null", 20)
        await p.ev("(() => { const r = document.querySelector('input[name=\"dcBatchSystem\"][value=\"103\"]'); if (!r.checked) r.click(); })()")
        await asyncio.sleep(0.3)
        dim = "(() => { const s = getComputedStyle(document.querySelector('.dc-side-scroll')); return [document.getElementById('dcRoot').classList.contains('dc-side-away'), !document.getElementById('dcSideNote').hidden, Number(s.opacity) < 0.6]; })()"
        # As a click on the tab would: the focus leaves the side (a focus in it brings it back).
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"batch\"]').focus()")
        await p.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 900, 'y': 400})
        await asyncio.sleep(0.4)
        away = await p.ev(dim)
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"coef\"]').click()")
        await asyncio.sleep(0.4)
        back = await p.ev(dim)
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"batch\"]').click()")
        await asyncio.sleep(0.3)
        check('the Batch tab dims the side’s settings, which are not its own, with a note; another tab brings them back',
              away == [True, True, True] and back == [False, False, False])
        order = await p.ev("[...document.getElementById('pane-batch').children].map(e => e.id).filter(Boolean)")
        check('what the table shows is set apart under the button and the bar, and nothing is offered to save before a run',
              bool(order) and order.index('dcBatchShow') == order.index('dcBatchForm') + 1 and await p.ev("getComputedStyle(document.getElementById('dcBatchTools')).display === 'none'"))
        check('the batch has its own decay chain cut-off and tolerance', await p.ev("document.getElementById('dcBatchCutoff')?.value === '1e-4' && document.getElementById('dcBatchRtol')?.value === '1e-6'"))
        sexes = "document.querySelector('input[name=\"dcBatchShown\"][value=\"sexes\"]').disabled"
        off = await p.ev(f"(() => {{ for (const i of document.querySelectorAll('input[name=\"dcBatchShown\"]')) if (i.checked !== (i.value === 'e')) i.click(); return {sexes}; }})()")
        await p.ev("document.querySelector('input[name=\"dcBatchShown\"][value=\"weighted\"]').click()")
        on = not await p.ev(sexes)
        await p.ev("document.querySelector('input[name=\"dcBatchShown\"][value=\"weighted\"]').click()")
        check('male and female are offered only with an equivalent dose ticked', off is True and on and await p.ev(sexes))
        # The picker: search and add, filters and add all shown, double-click to remove, Use these; Cancel changes nothing.
        await p.ev("document.getElementById('dcBatchPick').click()")
        opened = await p.until("document.querySelector('dialog.dc-picker[open]') !== null", 10)
        await p.ev("(() => { const s = document.getElementById('dcPickSearch'); s.value = 'cs13'; s.dispatchEvent(new Event('input', { bubbles: true })); })()")
        found = await p.ev("[...document.getElementById('dcPickLeft').options].map(o => o.value)")
        await p.ev("""(() => {
          document.querySelector('[data-pick="removeAll"]').click();
          const l = document.getElementById('dcPickLeft'); [...l.options].find(o => o.value === 'Cs-134').selected = true;
          document.querySelector('[data-pick="add"]').click();
          const s = document.getElementById('dcPickSearch'); s.value = ''; s.dispatchEvent(new Event('input', { bubbles: true }));
          const set = (id, v) => { const e = document.getElementById(id); e.value = v; e.dispatchEvent(new Event('change', { bubbles: true })); };
          set('dcPickElement', 'Pu'); set('dcPickFrom', '365.25'); set('dcPickMode', 'A');
          document.querySelector('[data-pick="addAll"]').click();
          const r = document.getElementById('dcPickRight'); [...r.options].find(o => o.value === 'Pu-244').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
          document.getElementById('dcPickUse').click(); })()""")
        await asyncio.sleep(0.3)
        text = await p.ev("document.getElementById('dcBatchText').value")
        check('the picker finds by search, filters by element, half-life and decay, and hands back what is chosen',
              opened and found and all(n.startswith('Cs-13') for n in found) and text == 'Cs-134, Pu-236, Pu-238, Pu-239, Pu-240, Pu-241, Pu-242'
              and await p.ev("document.querySelector('dialog.dc-picker') === null"))
        await p.ev("document.getElementById('dcBatchPick').click()")
        await p.until("document.querySelector('dialog.dc-picker[open]') !== null", 10)
        await p.ev("document.querySelector('[data-pick=\"removeAll\"]').click(); document.querySelector('.dc-picker-foot [data-pick=\"cancel\"]').click()")
        await asyncio.sleep(0.3)
        check('Cancel leaves the radionuclides as they were', await p.ev("document.getElementById('dcBatchText').value") == text)
        await p.ev("""(() => {
          document.querySelector('input[name="dcBatchRoute"][value="ingestion"]').click();
          document.querySelector('input[name="dcBatchForms"][value="all"]').click();
          for (const i of document.querySelectorAll('input[name="dcBatchAge"]')) if (i.checked !== (i.value === '7300')) i.click();
          for (const i of document.querySelectorAll('input[name="dcBatchShown"]')) if (i.checked !== (i.value === 'e')) i.click();
          const l = document.getElementById('dcBatchLayout'); l.value = 'ages'; l.dispatchEvent(new Event('change', { bubbles: true }));
          const t = document.getElementById('dcBatchText'); t.value = 'cs137, Sr-90'; t.dispatchEvent(new Event('input', { bubbles: true })); })()""")
        ok = await p.until("/= 4 calculations/.test(document.getElementById('dcBatchCount').textContent)", 20)
        check('the batch counts Cs-137 and Sr-90 by ingestion, all forms, one age: 4 calculations', ok)
        await p.ev("document.getElementById('dcBatchRun').click()")
        ok = await p.until("/^4 calculations in/.test(document.getElementById('dcBatchProgressText').textContent)", 120)
        rows = await p.ev("[...document.querySelectorAll('#dcBatchTable tbody tr')].map(r => [...r.cells].map(c => c.textContent))")
        cs = next((r for r in rows or [] if r[0] == 'Cs-137' and 'chloride' in r[2]), None)
        check('it fills a row for each nuclide and form, Cs-137 chloride as the single calculation (1.4E-08)', ok and len(rows) == 4 and cs is not None and cs[3] in ('1.3E-08', '1.4E-08'))
        await p.ev("document.querySelector('[data-on-click=\"dc:batchCsv\"]').click()")
        await p.ev("document.querySelector('[data-on-click=\"dc:batchExcel\"]').click()")
        files = {}
        for _ in range(100):
            await asyncio.sleep(0.2)
            names = [n for n in os.listdir(downloads) if not n.endswith('.crdownload')]
            if 'dose-batch-icrp103-ingestion.csv' in names and 'dose-batch-icrp103-ingestion.xlsx' in names:
                files = {n: open(os.path.join(downloads, n), 'rb').read() for n in names}
                break
        table = list(csv.reader(io.StringIO(files.get('dose-batch-icrp103-ingestion.csv', b'').decode('utf-8'))))
        good = len(table) == 5 and table[0][:5] == ['System', 'Route', 'Nuclide', 'Half-life', 'Form'] and table[0][5].startswith('e, Adult')
        good = good and all(float(r[5]) > 0 for r in table[1:])
        check('Save as CSV writes the table: a header and 4 rows of values in full', good)
        sheets, styled = [], False
        try:
            with zipfile.ZipFile(io.BytesIO(files.get('dose-batch-icrp103-ingestion.xlsx', b''))) as z:
                sheets = sorted(n for n in z.namelist() if n.startswith('xl/worksheets/sheet'))
                results = z.read('xl/worksheets/sheet1.xml').decode('utf-8')
                styled = workbook_styles(z.read('xl/styles.xml'), results)
        except zipfile.BadZipFile:
            results = ''
        check('Save as Excel writes a workbook of two sheets, the results and the settings', sheets == ['xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml'] and results.count('<row ') == 5)
        check('its header is bold and its values in the table’s digits (0.0E+00)', styled)
        await p.ev("""(() => {
          for (const i of document.querySelectorAll('input[name="dcBatchAge"]')) if (!i.checked) i.click();
          const t = document.getElementById('dcBatchText'); t.value = 'Ra-226 Th-232 U-238 Ac-227'; t.dispatchEvent(new Event('input', { bubbles: true })); })()""")
        await asyncio.sleep(0.5)
        await p.ev("document.getElementById('dcBatchRun').click()")
        running = await p.until("/calculations done/.test(document.getElementById('dcBatchProgressText').textContent) && /Batch · /.test(document.querySelector('.dc-tabs button[data-tab=\"batch\"]').textContent)", 20)
        await asyncio.sleep(1)
        await p.ev("document.getElementById('dcBatchStop').click()")
        stopped = await p.until("/^Stopped after/.test(document.getElementById('dcBatchProgressText').textContent)", 30)
        check('a running batch shows its progress (also on its tab) and Stop ends it, keeping what was done',
              running and stopped and await p.ev("document.getElementById('dcBatchStop').hidden && !document.getElementById('dcBatchRun').disabled && document.querySelector('.dc-tabs button[data-tab=\"batch\"]').textContent === 'Batch'"))

        # Phone width: no sideways scroll.
        await p.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 2, 'mobile': True})
        await asyncio.sleep(1)
        check('no horizontal scroll at 390 px', await p.ev("document.documentElement.scrollWidth <= window.innerWidth + 1"))
        # Help: the two tables of ratios with a column per age under an age row; on a phone each table scrolls, not the pane.
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"help\"]').click()")
        await asyncio.sleep(0.6)
        shape = await p.ev("""[...document.querySelectorAll('table.dc-ratios')].map((t) => [t.tHead.rows[1].textContent,
          [...t.tBodies[0].rows].every((r) => r.querySelectorAll('td.num').length === 6), t.parentElement.className])""")
        check('Help’s ratio tables give a column per age under the ages, each in a scroller',
              bool(shape) and len(shape) == 2 and all(a == '3 months1 year5 years10 years15 yearsAdult' and b and c == 'dc-table-wrap' for a, b, c in shape))
        check('nor does the Help pane at 390 px', await p.ev("(() => { const pane = document.getElementById('pane-help'); return pane.scrollWidth <= pane.clientWidth + 1; })()"))
        await p.ev("document.querySelector('.dc-tabs button[data-tab=\"model\"]').click()")
        await asyncio.sleep(0.8)
        check('nor in the Model tab, with the body drawn', await p.ev("document.documentElement.scrollWidth <= window.innerWidth + 1 && !document.getElementById('dcBody').hidden"))

        # The full window: the page without the site's header, menu and footer, by the button at the right end of
        # the tab bar; there the kvot mark at the left of the bar goes to the home page and the site's theme switch
        # is beside the button; the choice is kept, and the next visit is in the full window from the first paint.
        await p.call('Emulation.setDeviceMetricsOverride', {'width': 1400, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
        await asyncio.sleep(0.5)
        FULL = """(() => { const shown = (s) => { const e = document.querySelector(s); return !!e && getComputedStyle(e).display !== 'none' && e.getClientRects().length > 0; };
          const c = document.querySelector('.content').getBoundingClientRect(), b = document.getElementById('dcFull');
          return { on: document.documentElement.classList.contains('dc-full'), site: [shown('body > header'), shown('body > footer'), shown('body > .nav-toggle')],
            top: Math.round(c.top), fills: Math.round(c.height) === innerHeight, mine: [shown('.dc-homelink'), shown('.dc-tabbar .theme-toggle')],
            pressed: b.getAttribute('aria-pressed'), stored: localStorage.getItem('kvot.dose.full') }; })()"""
        THEME = "[document.documentElement.dataset.theme, document.querySelector('.dc-tabbar .theme-toggle').textContent, localStorage.getItem('kvot-theme')]"
        EARLY = """document.addEventListener('readystatechange', () => {
          if (document.readyState !== 'interactive' || window.__early) return;
          const h = document.querySelector('body > header');
          window.__early = { full: document.documentElement.classList.contains('dc-full'), header: h ? getComputedStyle(h).display : null,
            top: Math.round(document.querySelector('.content').getBoundingClientRect().top),
            icon: [...document.querySelectorAll('#dcFull path')].map((x) => getComputedStyle(x).display) };
        });"""

        async def press(sel):
            x, y = await p.ev(f"(() => {{ const e = document.querySelector({json.dumps(sel)}); e.scrollIntoView({{ block: 'nearest' }}); const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
            for t in ('mouseMoved', 'mousePressed', 'mouseReleased'):
                await p.call('Input.dispatchMouseEvent', {'type': t, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
            await asyncio.sleep(0.3)

        r = await p.ev(FULL)
        check('the site’s header, menu and footer around the page, the full-window button not pressed',
              (r['on'], r['site'], r['top'], r['mine'], r['pressed']), (False, [True, True, True], 43, [False, False], 'false'))
        await press('#dcFull')
        r = await p.ev(FULL)
        check('the full-window button: no site header, menu or footer, the page fills the window, the choice kept',
              (r['on'], r['site'], r['top'], r['fills'], r['pressed'], r['stored']), (True, [False, False, False], 0, True, 'true', '1'))
        check('... the kvot mark at the left of the tab bar goes to the home page, the theme switch beside the button',
              (r['mine'], await p.ev("""(() => { const a = document.querySelector('.dc-homelink'), img = a.querySelector('img');
                const first = document.querySelector('.dc-tabs button').getBoundingClientRect(), end = document.querySelector('.dc-tabend'), bar = document.querySelector('.dc-tabbar');
                return [a.getAttribute('href'), img.complete && img.naturalWidth > 0, img.alt, a.getBoundingClientRect().right <= first.left,
                  end.firstElementChild.classList.contains('theme-toggle') && end.lastElementChild.id === 'dcFull', Math.abs(end.getBoundingClientRect().right - bar.getBoundingClientRect().right) <= 1]; })()""")),
              ([True, True], ['./index.html', True, 'kvot ab: the home page', True, True, True]))
        before = await p.ev(THEME)
        await press('.dc-tabbar .theme-toggle')
        mid = await p.ev(THEME)
        await press('.dc-tabbar .theme-toggle')
        end = await p.ev(THEME)
        flip = {'light': 'dark', 'dark': 'light'}
        check('its theme switch changes the theme and keeps it, as the footer’s does',
              [mid[0] == flip.get(before[0]), mid[1] == ('☀️' if mid[0] == 'dark' else '🌙'), mid[2] == mid[0], end[0] == before[0], end[2] == end[0]], [True] * 5)
        await press('.dc-tabs button[data-tab="chain"]')
        check('the tabs work as before, and the bar’s buttons are not tabs',
              await p.ev("""[!document.getElementById('pane-chain').hidden, [...document.querySelectorAll('.dc-tabbar button.active')].map((b) => b.dataset.tab),
                document.querySelectorAll('[role=tablist] > :not([role=tab])').length]"""), [True, ['chain'], 0])
        early = await p.call('Page.addScriptToEvaluateOnNewDocument', {'source': EARLY})
        await p.call('Page.reload')
        await p.until("document.getElementById('dcNuclideCount') && /nuclides/.test(document.getElementById('dcNuclideCount').textContent)", 60)
        await p.call('Page.removeScriptToEvaluateOnNewDocument', {'identifier': early['result']['identifier']})
        check('the next visit is in the full window before the page’s script runs (no header shown while it loads)',
              await p.ev('window.__early || null'), {'full': True, 'header': 'none', 'top': 0, 'icon': ['none', 'inline']})
        r = await p.ev(FULL)
        check('... its button pressed', (r['on'], r['pressed'], r['fills']), (True, 'true', True))
        # A phone: the mark, the switch and the button stay in the bar's ends while the tabs scroll between them.
        await p.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 2, 'mobile': True})
        await asyncio.sleep(0.6)
        check('phone: the full window’s bar keeps the mark at its left and the switch and button at its right, the tabs scrolling between',
              await p.ev("""(() => { document.querySelector('.dc-tabbar').scrollIntoView(); const bar = document.querySelector('.dc-tabbar').getBoundingClientRect(),
                tabs = document.querySelector('.dc-tabs'), t = tabs.getBoundingClientRect(), mark = document.querySelector('.dc-homelink').getBoundingClientRect(),
                end = document.querySelector('.dc-tabend').getBoundingClientRect();
                return [Math.round(bar.left), Math.round(bar.right) === innerWidth, mark.right <= t.left + 0.5, end.left >= t.right - 0.5, Math.abs(end.right - bar.right) <= 1,
                  tabs.scrollWidth > tabs.clientWidth, document.documentElement.scrollWidth <= innerWidth + 1]; })()"""), [0, True, True, True, True, True, True])
        await press('#dcFull')
        r = await p.ev(FULL)
        check('the button again: the site’s header, menu and footer back, the choice kept', (r['on'], r['site'], r['pressed'], r['stored']), (False, [True, True, True], 'false', '0'))
        await p.ev("localStorage.removeItem('kvot.dose.full')")

        check('no script errors', p.errors, [])
    print(f'\n{checks - len(failures)} of {checks} checks passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
