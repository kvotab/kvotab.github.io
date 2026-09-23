#!/usr/bin/env python3
"""ensdf.html in a real browser: does the page do what it says.

test-parse.js proves the reading and the chains. This proves the wiring: the
built-in release loads, a nuclide can be reached by address, by search, by
clicking the chart and by the arrow keys, every colour mode draws its legend,
the decay-chain chart draws with no label on top of a box, the options change
the chain, the Levels, Radiation and Data sets tabs fill, a user's ENSDF zip
opens in the worker, is remembered across a reload and can be forgotten, the
downloads produce files, the theme switch recolours the chart, the phone
layout does not overflow -- and nothing reaches the console as an error.

Start the server and the browser as in ../rb/README.md, then

    python3 resources/tests/ensdf/test-ui.py

Exit status is 0 when every check passes.
"""
import asyncio
import base64
import io
import json
import os
import sys
import urllib.request
import zipfile

import websockets

BASE = 'http://127.0.0.1:8765/ensdf.html'
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixture', 'ensdf.003')

failures = []
checks = 0
SUPERSCRIPTS = '\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207a\u207b\u1d50'


def check(label, got, want=True):
    global checks
    checks += 1
    ok = want(got) if callable(want) else got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r}' + ('' if callable(want) else f' (expected {want!r})')))
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
            m = r.get('method')
            if m == 'Runtime.exceptionThrown':
                d = r['params']['exceptionDetails']
                self.errors.append(str(d.get('exception', {}).get('description') or d.get('text', ''))[:300])
            if m == 'Runtime.consoleAPICalled' and r['params']['type'] == 'error':
                self.errors.append(' '.join(str(a.get('value', a.get('description', ''))) for a in r['params']['args'])[:300])
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

    async def mouse(self, x, y):
        for typ in ('mouseMoved', 'mousePressed', 'mouseReleased'):
            await self.call('Input.dispatchMouseEvent', {'type': typ, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1}, session=self.sid)

    async def key(self, key, code):
        for typ in ('keyDown', 'keyUp'):
            await self.call('Input.dispatchKeyEvent', {'type': typ, 'key': key, 'code': key, 'windowsVirtualKeyCode': code}, session=self.sid)

    async def goto(self, url, width=1280, height=900):
        await self.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': width < 600}, session=self.sid)
        await self.call('Page.navigate', {'url': url}, session=self.sid)
        await settle(self, "!!(window.ENSDFPage && ENSDFPage.state.idx && ENSDFPage.state.source)", True, tries=80)


async def settle(page, expr, want, tries=40, pause=0.25):
    got = None
    for _ in range(tries):
        got = await page.ev(expr)
        if got == want:
            return got
        await asyncio.sleep(pause)
    return got


def fixture_zip_b64():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(FIXTURE, 'ensdf.003')
    return base64.b64encode(buf.getvalue()).decode()


async def main():
    ver = json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json/version').read())
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        page = Page(bws)
        pump = asyncio.ensure_future(page.pump())
        t = await page.call('Target.createTarget', {'url': 'about:blank'})
        tid = t['result']['targetId']
        a = await page.call('Target.attachToTarget', {'targetId': tid, 'flatten': True})
        page.sid = a['result']['sessionId']
        for m in ('Runtime.enable', 'Page.enable', 'Network.enable'):
            await page.call(m, session=page.sid)
        # Network.setCacheDisabled does nothing unless Network.enable came first.
        await page.call('Network.setCacheDisabled', {'cacheDisabled': True}, session=page.sid)
        # A clean start: no remembered settings, no remembered databases, light theme.
        await page.call('Page.addScriptToEvaluateOnNewDocument', {'source': """
          try { if (!sessionStorage.getItem('nz-test-started')) {
            sessionStorage.setItem('nz-test-started', '1');
            localStorage.removeItem('kvot-ensdf-v1'); localStorage.setItem('kvot-theme', 'light');
            indexedDB.deleteDatabase('kvot-ensdf');
          } } catch (e) {}"""}, session=page.sid)

        # ---------------------------------------------------------- loading
        await page.goto(BASE + '#60Co')
        info = await page.ev("""JSON.stringify({
          label: ENSDFPage.state.source.label, shown: ENSDFPage.state.idx.shown.length,
          legend: document.querySelectorAll('#nzLegend li').length,
          sel: ENSDFPage.state.sel, title: document.querySelector('#nzPaneNuclide .nz-big').textContent,
          canvas: !!document.querySelector('#nzChart canvas')})""")
        info = json.loads(info)
        check('the built-in release loads', info['label'].startswith('ENSDF '))
        check('the chart has the whole chart of nuclides', info['shown'], lambda n: n > 3300)
        check('the half-life legend has 13 entries', info['legend'], 13)
        check('the address selects a nuclide (#60Co)', info['sel'], {'z': 27, 'a': 60, 'k': 0})
        check('the panel names it', info['title'], '60Co')
        check('the chart is a canvas', info['canvas'])

        # ---------------------------------------------------------- search
        await page.ev("document.getElementById('nzSearch').value = 'Tc-99m'; document.getElementById('nzSearch').focus(); 'ok'")
        await page.key('Enter', 13)
        await asyncio.sleep(0.3)
        check('search "Tc-99m" selects the isomer', await page.ev('JSON.stringify(ENSDFPage.state.sel)'), json.dumps({'z': 43, 'a': 99, 'k': 1}, separators=(',', ':')))
        check('the address follows the selection', await page.ev('location.hash'), '#99mTc')
        await page.ev("document.getElementById('nzSearch').value = 'unobtainium-7'; 'ok'")
        await page.ev("document.querySelector('.nz-search .nz-btn').click(); 'ok'")
        await asyncio.sleep(0.3)
        check('an unknown name is answered, not ignored', await page.ev("(document.querySelector('.failure-banner.show') || {}).textContent || ''"), lambda t: 'No nuclide called' in t)

        # ---------------------------------------------------------- the hover card
        # Verdana has only the Latin-1 superscripts, so a Unicode "²³⁸" mixes two
        # fonts; the card must set its superscripts as <sup>.
        await page.ev('ENSDFPage.chart.centreOn(92, 238, 44); "ok"')
        await asyncio.sleep(0.3)
        rect = json.loads(await page.ev("JSON.stringify(document.querySelector('#nzChart canvas').getBoundingClientRect())"))
        await page.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': rect['x'] + rect['width'] / 2, 'y': rect['y'] + rect['height'] / 2}, session=page.sid)
        await asyncio.sleep(0.3)
        tip = json.loads(await page.ev("JSON.stringify({ shown: !document.getElementById('nzTip').hidden, sups: document.querySelectorAll('#nzTip sup').length, text: document.getElementById('nzTip').textContent })"))
        check('hovering 238U shows its card', tip['shown'] and tip['text'].startswith('238U'), True)
        check('the card sets the mass number and exponents as <sup>', tip['sups'], lambda n: n >= 2)
        check('... and draws no Unicode superscript characters', any(c in tip['text'] for c in SUPERSCRIPTS), False)

        # ---------------------------------------------------------- the chart
        await page.ev('ENSDFPage.chart.centreOn(28, 60, 30); "ok"')
        await asyncio.sleep(0.3)
        rect = json.loads(await page.ev("JSON.stringify(document.querySelector('#nzChart canvas').getBoundingClientRect())"))
        cx, cy = rect['x'] + rect['width'] / 2, rect['y'] + rect['height'] / 2
        await page.mouse(cx, cy)
        await asyncio.sleep(0.3)
        check('a click on the chart selects the cell under it (60Ni)', await page.ev('JSON.stringify(ENSDFPage.state.sel)'), json.dumps({'z': 28, 'a': 60, 'k': 0}, separators=(',', ':')))
        await page.ev("document.querySelector('#nzChart canvas').focus(); 'ok'")
        await page.key('ArrowRight', 39)
        await asyncio.sleep(0.3)
        check('ArrowRight steps to the next isotone (61Ni)', await page.ev('ENSDFPage.state.sel.a'), 61)
        await page.key('ArrowUp', 38)
        await asyncio.sleep(0.3)
        check('ArrowUp steps to Z + 1 (62Cu)', await page.ev('ENSDFPage.state.sel.z + "," + ENSDFPage.state.sel.a'), '29,62')

        for mode, want in (('mode', 9), ('qb', 1), ('year', 1), ('e2', 1), ('halflife', 13)):
            n = await page.ev(f"""(async () => {{ const s = document.getElementById('nzColour'); s.value = '{mode}';
              s.dispatchEvent(new Event('change', {{bubbles: true}})); await new Promise(r => setTimeout(r, 80));
              return document.querySelectorAll('#nzLegend li').length + (document.querySelector('#nzLegend .nz-ramp') ? ' ramp' : ''); }})()""")
            check(f'colour by {mode}: the legend follows', n, lambda v, w=want, m=mode: v.startswith(str(w)) and (m in ('mode', 'halflife') or v.endswith('ramp')))

        # ---------------------------------------------------------- the chain
        await page.ev("ENSDFPage.select('U-238'); document.querySelector('[data-view=chain]').click(); 'ok'")
        await asyncio.sleep(0.8)
        chain = json.loads(await page.ev("""(() => {
          const boxes = [...document.querySelectorAll('#nzChainSvg .nz-node')].map(g => g.querySelector('rect').getBoundingClientRect());
          const labels = [...document.querySelectorAll('#nzChainSvg .nz-edge-label rect')].map(r => r.getBoundingClientRect());
          const hit = (p, q) => p.left < q.right - 1 && p.right > q.left + 1 && p.top < q.bottom - 1 && p.bottom > q.top + 1;
          const covered = labels.filter(l => boxes.some(b => hit(l, b))).length;
          return JSON.stringify({ boxes: boxes.length, labels: labels.length, covered,
            rows: document.querySelectorAll('#nzChainTable tbody tr').length,
            tab: document.getElementById('nzChainTabName').textContent });
        })()"""))
        check('the 238U chain draws every member', chain['boxes'], lambda n: n >= 30)
        check('the chain table lists them', chain['rows'], lambda n: n >= 28)
        check('no branch label sits on a box', chain['covered'], 0)
        curves = json.loads(await page.ev("JSON.stringify({"
          "bent: [...document.querySelectorAll('#nzChainSvg path[marker-end]')].filter(p => /Q/.test(p.getAttribute('d'))).length,"
          "all: document.querySelectorAll('#nzChainSvg path[marker-end]').length,"
          "texts: [...document.querySelectorAll('#nzChainSvg text')].map(t => t.textContent).join(' ') })"))
        check('where a straight arrow would cross a box, it bends', curves['bent'], lambda n: 0 < n < curves['all'])
        check('the chain drawing has no Unicode superscripts either', any(c in curves['texts'] for c in SUPERSCRIPTS), False)
        check('the view tab names the start of the chain, mass number set as <sup>', await page.ev("document.getElementById('nzChainTabName').innerHTML"), '<sup>238</sup>U')
        few = await page.ev("""(async () => { const s = document.getElementById('nzMinBranch'); s.value = '1';
          s.dispatchEvent(new Event('change', {bubbles: true})); await new Promise(r => setTimeout(r, 200));
          const n = document.querySelectorAll('#nzChainSvg .nz-node').length; s.value = '0';
          s.dispatchEvent(new Event('change', {bubbles: true})); return n; })()""")
        check('branches under 1 % can be left out', few, lambda n: 10 <= n < chain['boxes'])
        cd = await page.ev("""(async () => { ENSDFPage.select('Cd-109'); await new Promise(r => setTimeout(r, 150));
          const s = document.getElementById('nzMinLife'); const count = async (v) => { s.value = v;
            s.dispatchEvent(new Event('change', {bubbles: true})); await new Promise(r => setTimeout(r, 150));
            return document.querySelectorAll('#nzChainSvg .nz-node').length; };
          const r = [s.value, await count('iso'), await count('1min')]; await count('iso'); return r.join(','); })()""")
        check('by default only isomers under a second are left out: 109mAg (40 s) is drawn, and left out at 1 min', cd, 'iso,3,2')
        opts = json.loads(await page.ev("JSON.stringify({ n: document.querySelectorAll('#nzMinLife option').length,"
                                        " first: document.querySelector('#nzMinLife option').textContent,"
                                        " last: [...document.querySelectorAll('#nzMinLife option')].pop().textContent })"))
        check('half-life thresholds run from all members to 1000 years', (opts['n'], opts['first'], opts['last']), (11, 'all members', 'T½ ≥ 1000 y'))
        u = json.loads(await page.ev("""(async () => { ENSDFPage.select('U-238'); await new Promise(r => setTimeout(r, 150));
          const s = document.getElementById('nzMinLife'); s.value = '1y'; s.dispatchEvent(new Event('change', {bubbles: true}));
          await new Promise(r => setTimeout(r, 250));
          const keys = [...document.querySelectorAll('#nzChainSvg .nz-node')].map(g => g.dataset.key);
          const out = { keys, labels: [...document.querySelectorAll('#nzChainSvg .nz-edge-label text')].map(t => t.textContent),
            note: document.getElementById('nzChainNote').textContent };
          s.value = 'iso'; s.dispatchEvent(new Event('change', {bubbles: true})); return JSON.stringify(out); })()"""))
        check('T½ ≥ 1 y: the 238U chain keeps 238U, 234U, 230Th, 226Ra, 210Pb, 206Pb and drops 234Th, 222Rn, 214Po, 210Po',
              all(k in u['keys'] for k in ('92,238,0', '92,234,0', '90,230,0', '88,226,0', '82,210,0', '82,206,0'))
              and not any(k in u['keys'] for k in ('90,234,0', '86,222,0', '84,214,0', '84,210,0')), True)
        check('... the arrows jump over them, marked via', [l for l in u['labels'] if l.startswith('via')],
              lambda v: 'via 234Th, 234mPa' in v and 'via 222Rn … 214Po' in v and 'via 210Bi, 210Po' in v)
        check('... and the note says what was left out', 'Left out, as members that live less than 1 y' in u['note'] and '222Rn' in u['note'], True)
        cs = json.loads(await page.ev("""(async () => { ENSDFPage.select('Cs-137'); await new Promise(r => setTimeout(r, 150));
          const s = document.getElementById('nzMinLife'); s.value = '1h'; s.dispatchEvent(new Event('change', {bubbles: true}));
          await new Promise(r => setTimeout(r, 150));
          const shot = () => ({ nodes: document.querySelectorAll('#nzChainSvg .nz-node').length,
            arrows: document.querySelectorAll('#nzChainSvg path[marker-end]').length,
            labels: [...document.querySelectorAll('#nzChainSvg .nz-edge-label text')].map(t => t.textContent),
            table: document.getElementById('nzChainTable').textContent });
          const out = { cs: shot() };
          ENSDFPage.select('Th-234'); await new Promise(r => setTimeout(r, 200));
          out.th = shot();
          const draw = document.getElementById('nzChainSvg').parentElement, u = document.querySelector('#nzChainSvg .nz-node[data-key="92,234,0"]');
          const v = draw.getBoundingClientRect(), b = u.getBoundingClientRect();
          out.th.uInView = b.left >= v.left - 1 && b.right <= v.right + 1;
          s.value = 'iso'; s.dispatchEvent(new Event('change', {bubbles: true})); return JSON.stringify(out); })()"""))
        check('T½ ≥ 1 h: 137mBa is left out of the 137Cs chain', cs['cs']['nodes'], 2)
        check('... shortcut through its IT: one beta-minus arrow of 100 %, unlabelled', (cs['cs']['arrows'], cs['cs']['labels']), (1, []))
        check('... and the table says how much went through the isomer', '(94.7 % via 137mBa)' in cs['cs']['table'], True)
        check('T½ ≥ 1 h: 234Th goes to 234U by an arrow marked via 234mPa', '99.69 % via 234mPa' in cs['th']['labels'], True)
        check('... and the view opens with 234Th and its daughters in it', cs['th']['uInView'], True)
        crowd = json.loads(await page.ev("""(async () => { ENSDFPage.select('Br-101'); await new Promise(r => setTimeout(r, 300));
          const labels = [...document.querySelectorAll('#nzChainSvg .nz-edge-label rect')].map(r => r.getBoundingClientRect());
          const boxes = [...document.querySelectorAll('#nzChainSvg .nz-node')].map(g => g.querySelector('rect').getBoundingClientRect());
          const hit = (p, q) => p.left < q.right - 1 && p.right > q.left + 1 && p.top < q.bottom - 1 && p.bottom > q.top + 1;
          let pairs = 0;
          labels.forEach((l, i) => labels.slice(i + 1).forEach(m => { if (hit(l, m)) pairs++; }));
          return JSON.stringify({ labels: labels.length, pairs, covered: labels.filter(l => boxes.some(b => hit(l, b))).length }); })()"""))
        check('a crowded chain (101Br, with beta-delayed neutrons) has its labels clear of each other and of the boxes', (crowd['pairs'], crowd['covered']), (0, 0))
        picked = await page.ev("""(async () => { ENSDFPage.select('U-238'); await new Promise(r => setTimeout(r, 200));
          const g = [...document.querySelectorAll('#nzChainSvg .nz-node')].find(n => n.dataset.key === '88,226,0');
          g.dispatchEvent(new MouseEvent('click', {bubbles: true})); await new Promise(r => setTimeout(r, 200));
          return JSON.stringify({ sel: ENSDFPage.state.sel, root: ENSDFPage.state.root }); })()""")
        picked = json.loads(picked)
        check('a box in the chain opens that member in the panel', picked['sel'], {'z': 88, 'a': 226, 'k': 0})
        check('... and the chain keeps its start', picked['root'], {'z': 92, 'a': 238, 'k': 0})

        # ---------------------------------------------------------- the tabs
        await page.ev("document.querySelector('[data-view=chart]').click(); ENSDFPage.select('Co-60'); 'ok'")
        shared = json.loads(await page.ev("JSON.stringify(['nzMinBranch', 'nzMinLife', 'nzOverlay'].map(id => {"
                                          " const r = document.getElementById(id).getBoundingClientRect(); return r.width > 0 && r.height > 0; }))"))
        check('the chain settings are there in the chart view too', shared, [True, True, True])
        tabs = json.loads(await page.ev("""(async () => { const t = document.querySelector('.nz-tabs');
          const fits = () => [t.scrollWidth <= t.clientWidth, t.scrollHeight <= t.clientHeight];
          const out = [fits()]; document.getElementById('nz').style.setProperty('--nz-panel-width', '330px');
          await new Promise(r => setTimeout(r, 100)); out.push(fits());
          document.getElementById('nz').style.removeProperty('--nz-panel-width'); return JSON.stringify(out); })()"""))
        check('the panel tabs, six of them, fit with no scroll bar of their own, at full width and dragged to 330 px', tabs, [[True, True], [True, True]])
        for tab, probe in (('levels', "t => t.includes('286 levels') && document.querySelector('#nzPaneLevels [data-on-click=\"nz:levelsAll\"]')"),
                           ('radiation', "t => t.includes('1332.492') && t.includes('1173.228')"),
                           ('datasets', "t => t.includes('ADOPTED LEVELS, GAMMAS') && t.includes('60CO IT DECAY')")):
            ok = await page.ev(f"""(async () => {{ document.querySelector('[data-tab={tab}]').click();
              for (let i = 0; i < 40; i++) {{ const t = document.querySelector('[data-pane={tab}]').textContent;
                if (({probe})(t)) return true; await new Promise(r => setTimeout(r, 100)); }} return false; }})()""")
            check(f'the {tab} tab fills for 60Co', ok, True)
        await page.ev("document.querySelector('[data-tab=nuclide]').click(); 'ok'")

        # ---------------------------------------------------------- downloads
        await page.ev("""window.__saved = []; HTMLAnchorElement.prototype.click = function () {
          if (this.download) fetch(this.href).then(r => r.blob()).then(b => window.__saved.push([this.download, b.size])); }; 'ok'""")
        await page.ev("document.querySelector('[data-on-click=\"nz:chartCsv\"]').click(); ENSDFPage.select('Th-232'); document.querySelector('[data-view=chain]').click(); 'ok'")
        await asyncio.sleep(0.5)
        await page.ev("['nz:chainSvg', 'nz:chainPng', 'nz:chainCsv'].forEach(a => document.querySelector(`[data-on-click=\"${a}\"]`).click()); 'ok'")
        saved = await settle(page, "window.__saved.length", 4, tries=40)
        files = json.loads(await page.ev('JSON.stringify(window.__saved)'))
        names = sorted(f[0] for f in files)
        check('four downloads: chart CSV, chain SVG, PNG and CSV', names, sorted(['ensdf-260901-ground-states.csv', 'decay-chain-232Th.svg', 'decay-chain-232Th.png', 'decay-chain-232Th.csv']))
        check('none of them empty', all(f[1] > 200 for f in files), True)
        await page.ev("document.querySelector('[data-view=chart]').click(); 'ok'")

        # ---------------------------------------------------------- the inventory
        invt = json.loads(await page.ev("""(async () => {
          ENSDFPage.select('U-238'); document.querySelector('[data-view=chain]').click();
          document.querySelector('[data-tab=inventory]').click();
          await new Promise(r => setTimeout(r, 600));
          const pane = document.getElementById('nzPaneInventory');
          const lvl = (k) => { const r = document.querySelector(`#nzChainSvg .nz-node[data-key="${k}"] .nz-level`); return r && r.getAttribute('visibility') === 'visible' ? +r.getAttribute('height') : 0; };
          const out = { lines: pane.querySelectorAll('#nzInvChart path').length, rows: pane.querySelectorAll('.nz-inv-table tbody tr').length,
            root: pane.querySelector('.nz-inv-table input[data-key="92,238,0"]').value, full: lvl('92,238,0'), other: lvl('90,230,0') };
          const ra = pane.querySelector('input[data-key="88,226,0"]');
          ra.value = '1'; ra.parentNode.querySelector('select').value = 'g';
          ra.dispatchEvent(new Event('input', {bubbles: true}));
          await new Promise(r => setTimeout(r, 800));
          out.ra = document.querySelector('#nzPaneInventory .nz-inv-now[data-key="88,226,0"]').textContent;
          const q = document.getElementById('nzInvQty'); q.value = 'total'; q.dispatchEvent(new Event('change', {bubbles: true}));
          await new Promise(r => setTimeout(r, 400));
          out.title = document.querySelector('#nzInvChart svg').textContent.includes('Total emitted energy (MeV/s)');
          /* A point on a line: a vertex of its path, in screen coordinates. */
          const svg = document.querySelector('#nzInvChart svg');
          const line = [...svg.querySelectorAll('path')].find((p) => p.getAttribute('stroke-width') === '2' && p.getAttribute('d').length > 200);
          const pts = line.getAttribute('d').split(/[ML]/).filter(Boolean).map((p) => p.split(',').map(Number));
          const mid = pts[Math.floor(pts.length * 0.6)];
          const r = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal;
          out.box = { x: r.left + mid[0] * r.width / vb.width, y: r.top + mid[1] * r.height / vb.height };
          return JSON.stringify(out); })()"""))
        check('the Inventory tab draws the 238U chain over time, the start with 1 Bq', (invt['lines'] >= 20, invt['rows'] >= 25, invt['root']), (True, True, '1'))
        check('... and fills the start\'s box, alone, as a bucket', (invt['full'] > 39, invt['other']), (True, 0))
        check('1 g of 226Ra is 3.66E10 Bq at the start (the curie: 1 g of radium)', invt['ra'], lambda t: t.startswith('3.66×10'))
        check('the chart shows the total emitted energy when asked', invt['title'], True)
        for x in (invt['box']['x'] - 2, invt['box']['x']):
            await page.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': invt['box']['y']}, session=page.sid)
            await asyncio.sleep(0.15)
        hov = json.loads(await page.ev("""JSON.stringify({ tip: !document.querySelector('.nz-inv-tip').hidden,
          ring: !!document.querySelector('#nzChainSvg .nz-hot-ring'),
          filled: [...document.querySelectorAll('#nzChainSvg .nz-level')].filter(r => r.getAttribute('visibility') === 'visible').length,
          at: document.getElementById('nzInvAt').textContent })"""))
        check('pointing at the chart: a tooltip, the nearest member ringed in the chain, its boxes filled to that time', (hov['tip'], hov['ring'], hov['filled'] >= 3, 'the start' not in hov['at']), (True, True, True, True))
        # The table's values change with the cursor; its columns must not move.
        cols = "JSON.stringify([...document.querySelectorAll('#nzPaneInventory .nz-inv-table tbody tr')].map(tr => [...tr.children].map(td => Math.round(td.getBoundingClientRect().left)).join(',')).concat([Math.round(document.querySelector('#nzPaneInventory .nz-inv-table').getBoundingClientRect().top)]))"
        chart = json.loads(await page.ev("(() => { const r = document.querySelector('#nzInvChart svg').getBoundingClientRect(); return JSON.stringify({ x: r.left, y: r.top, w: r.width, h: r.height }); })()"))
        seen = set()
        for f in (0.2, 0.45, 0.7, 0.93, None):
            x, y = (5, 5) if f is None else (chart['x'] + chart['w'] * f, chart['y'] + chart['h'] * 0.45)
            await page.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y}, session=page.sid)
            await asyncio.sleep(0.15)
            seen.add(await page.ev(cols))
        check('... and the table below keeps its columns and its place wherever the cursor is', len(seen), 1)
        await page.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 5, 'y': 5}, session=page.sid)
        row = json.loads(await page.ev("""(async () => {
          const tr = document.querySelector('#nzPaneInventory .nz-inv-table tr[data-key="86,222,0"]');
          tr.dispatchEvent(new PointerEvent('pointerenter'));
          await new Promise(r => setTimeout(r, 50));
          const thick = [...document.querySelectorAll('#nzInvChart path')].filter(p => p.getAttribute('stroke-width') === '3.5').length;
          const ring = document.querySelector('#nzChainSvg .nz-hot-ring');
          const out = { thick, ringOn: ring ? ring.parentNode.dataset.key : null };
          tr.dispatchEvent(new PointerEvent('pointerleave'));
          document.getElementById('nzInvPlay').click();
          await new Promise(r => setTimeout(r, 7600));
          out.cursor = ENSDFPage.state.inv.cursor; out.button = document.getElementById('nzInvPlay').textContent;
          document.querySelector('[data-on-click="nz:invCsv"]').click();
          await new Promise(r => setTimeout(r, 400));
          out.csv = window.__saved.filter(f => f[0].startsWith('inventory-')).map(f => f[0]);
          document.querySelector('[data-tab=nuclide]').click();
          out.after = [...document.querySelectorAll('#nzChainSvg .nz-level')].filter(r => r.getAttribute('visibility') === 'visible').length;
          return JSON.stringify(out); })()"""))
        check('pointing at a row of the table picks out its line and its box', (row['thick'], row['ringOn']), (1, '86,222,0'))
        check('Run through takes the cursor from start to end', (row['cursor'], row['button']), (240, 'Run through'))
        check('the values save as CSV', row['csv'], ['inventory-238U-total.csv'])
        check('leaving the tab puts the boxes back', row['after'], 0)

        # ---------------------------------------------------------- the NNDC archive
        nn = json.loads(await page.ev("""(async () => {
          for (let i = 0; i < 50 && !document.querySelector('#nzDb optgroup[label^="At NNDC"]'); i++) await new Promise(r => setTimeout(r, 100));
          const g = document.querySelector('#nzDb optgroup[label^="At NNDC"]');
          const s = document.getElementById('nzDb'), d = document.getElementById('nzGet'), before = ENSDFPage.state.source.key;
          const pick = (v) => { s.value = v; s.dispatchEvent(new Event('change', {bubbles: true})); };
          const out = { n: g ? g.children.length : 0, values: g ? [...g.children].map(o => o.value) : [] };
          pick('n:250101');
          out.one = { open: d.open, title: document.getElementById('nzGetTitle').textContent, links: [...d.querySelectorAll('#nzGetBody a')].map(a => a.href),
            value: s.value, source: ENSDFPage.state.source.key === before };
          document.querySelector('[data-on-click="nz:getClose"]').click();
          out.closed = !d.open;
          pick('n:120307');
          out.parts = { links: [...d.querySelectorAll('#nzGetBody a')].map(a => a.href.split('/').pop()), text: document.getElementById('nzGetBody').textContent,
            button: document.getElementById('nzGetOpen').textContent };
          pick('n:170501');
          out.partial = !!document.querySelector('#nzGetBody .nz-note-warn');
          /* "Open the downloaded file" closes the dialog and brings up the file picker. */
          const click = HTMLInputElement.prototype.click; let picked = '';
          HTMLInputElement.prototype.click = function () { picked = this.id; };
          document.getElementById('nzGetOpen').click();
          HTMLInputElement.prototype.click = click;
          out.picker = { closed: !d.open, picked };
          return JSON.stringify(out); })()"""))
        check('the menu lists the NNDC archive, back to 2004, less what is on this site', (nn['n'] >= 100, 'n:0403' in nn['values'], 'n:260901' in nn['values']), (True, True, False))
        check('choosing a release that is not here offers its download, and stays on the database in use',
              (nn['one']['open'], nn['one']['title'], nn['one']['links'], nn['one']['value'], nn['one']['source']),
              (True, 'ENSDF 2025-01-01 from NNDC', ['https://www.nndc.bnl.gov/ensdfarchivals/distributions/dist25/ensdf_250101.zip'], 'b:260901', True))
        check('... and Close closes it', nn['closed'], True)
        check('a release in parts lists every part with its mass numbers', (nn['parts']['links'], 'A = 1–99' in nn['parts']['text'], nn['parts']['button']),
              (['ensdf_120307_099.zip', 'ensdf_120307_199.zip', 'ensdf_120307_299.zip'], True, 'Open the downloaded files…'))
        check('an incomplete one says what it lacks', nn['partial'], True)
        check('"Open the downloaded files" closes the dialog and brings up the file picker', nn['picker'], {'closed': True, 'picked': 'nzFile'})

        # ---------------------------------------------------------- opening a file
        opened = await page.ev(f"""(async () => {{ const b = Uint8Array.from(atob('{fixture_zip_b64()}'), c => c.charCodeAt(0));
          await ENSDFPage.openFiles([new File([b], 'ensdf_990101.zip')]);
          const s = ENSDFPage.state; return JSON.stringify({{ label: s.source.label, key: s.source.key,
            h3: s.idx.get(1, 3).s[0].t, menu: [...document.querySelectorAll('#nzDb option:not([value^="n:"])')].length,
            forget: !document.getElementById('nzForget').hidden }}); }})()""")
        opened = json.loads(opened)
        check('an ENSDF zip opens, named after its release date', opened['label'], 'ENSDF 2099-01-01')
        check('... read from the file, not the built-in data', opened['h3'], '12.32 Y')
        check('... and joins the database menu', opened['menu'], 2)
        check('... with a way to forget it', opened['forget'], True)
        await page.goto(BASE)
        again = json.loads(await page.ev("JSON.stringify({ label: ENSDFPage.state.source.label, menu: [...document.querySelectorAll('#nzDb option')].map(o => o.value) })"))
        check('after a reload the opened database is still the one in use', again['label'], 'ENSDF 2099-01-01')
        check('... and the built-in one is still in the menu', any(v.startswith('b:') for v in again['menu']), True)
        await page.ev("document.getElementById('nzForget').click(); 'ok'")
        back = await settle(page, "ENSDFPage.state.source.key.startsWith('b:') && document.querySelectorAll('#nzDb option:not([value^=\"n:\"])').length === 1", True)
        check('forgetting it goes back to the built-in release', back, True)

        # ---------------------------------------------------------- theme and phone
        swatch = "getComputedStyle(document.querySelector('#nzLegend li[data-cls=\"-2\"] .nz-sw')).backgroundColor"
        light = await page.ev(swatch)
        await page.ev("document.querySelector('footer .theme-toggle').click(); 'ok'")
        await asyncio.sleep(0.3)
        dark = await page.ev(swatch)
        check('the theme switch recolours the chart (stable is dark, then light)', (light, dark), ('rgb(27, 21, 17)', 'rgb(251, 246, 238)'))
        await page.ev("document.querySelector('footer .theme-toggle').click(); 'ok'")
        await page.goto(BASE + '#Cs-137', 390, 844)
        wide = json.loads(await page.ev("JSON.stringify({ sw: document.documentElement.scrollWidth, iw: innerWidth, right: Math.max(...[...document.querySelectorAll('.nz-bar > *:not([hidden]), .nz-main, .nz-panel')].map(e => e.getBoundingClientRect().right)) })"))
        check('on a phone nothing is wider than the screen', wide['sw'] <= wide['iw'] and wide['right'] <= wide['iw'] + 0.5, True)

        check('no error reached the console', page.errors, [])
        await page.call('Target.closeTarget', {'targetId': tid})
        pump.cancel()

    print(f'\n{checks - len(failures)} of {checks} checks pass')
    if failures:
        print('failed:\n  ' + '\n  '.join(failures))
        sys.exit(1)


asyncio.run(main())
