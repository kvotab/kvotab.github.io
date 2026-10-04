#!/usr/bin/env python3
"""ensdf.html in a real browser: does the page do what it says.

test-parse.js proves the reading and the chains. This proves the wiring: the
built-in release loads, a nuclide can be reached by address, by search, by
clicking the chart and by the arrow keys, every colour mode draws its legend,
the decay-chain chart draws with no label on top of a box, the options change
the chain, the chain runs up to the parents as well, the Levels, Radiation and
Data sets tabs fill, a user's ENSDF zip
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

    async def reload(self):
        # Page.navigate to the same address, or one that differs only after the #, does not load the page again
        await self.ev("window.nzOldPage = true; 'ok'")
        await self.call('Page.reload', {'ignoreCache': True}, session=self.sid)
        await settle(self, "!window.nzOldPage && !!(window.ENSDFPage && ENSDFPage.state.idx && ENSDFPage.state.source)", True, tries=80)


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
            localStorage.removeItem('kvot.ensdf.full');
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

        # ---------------------------------------------------------- the tab icon
        # scripts/gen-ensdf-icon.py draws it. An SVG whose comment holds "--" is
        # not XML, and the browser drops it without a word, leaving the tab blank.
        icon = json.loads(await page.ev("""(async () => {
          const links = Object.fromEntries([...document.querySelectorAll('link[rel~="icon"], link[rel="apple-touch-icon"]')]
            .map((l) => [l.rel, [l.getAttribute('href'), l.type || '', l.getAttribute('sizes') || '']]));
          const load = (src) => new Promise((ok) => { const i = new Image(); i.onload = () => ok([i.naturalWidth, i.naturalHeight]); i.onerror = () => ok(null); i.src = src; });
          const svg = await (await fetch(links.icon[0], { cache: 'no-store' })).text();
          const doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
          return JSON.stringify({ links, svg: await load(links.icon[0]), png: await load(links['alternate icon'][0]), touch: await load(links['apple-touch-icon'][0]),
            xml: !doc.querySelector('parsererror'), title: doc.querySelector('svg > title')?.textContent, viewBox: doc.documentElement.getAttribute('viewBox'),
            fills: [...new Set([...svg.matchAll(/fill="(#[0-9a-f]{6})"/gi)].map((m) => m[1].toLowerCase()))].sort(),
            other: /<(linearGradient|radialGradient|path|rect|circle|image|text)\\b|stroke=/.test(svg) }); })()"""))
        check('the tab icon: the SVG first, a 32-pixel PNG for what will not take one, and a touch icon', icon['links'], {
              'icon': ['./resources/images/ensdf-icon.svg', 'image/svg+xml', ''],
              'alternate icon': ['./resources/images/ensdf-icon-32.png', 'image/png', '32x32'],
              'apple-touch-icon': ['./resources/images/ensdf-icon-180.png', '', '']})
        check('... each decodes as a picture of its size', (icon['svg'] is not None, icon['png'], icon['touch']), (True, [32, 32], [180, 180]))
        check('... the SVG is XML, in the 64-unit square, and named for the page', (icon['xml'], icon['viewBox'], icon['title']), (True, '0 0 64 64', 'Chart of Nuclides (ENSDF)'))
        check('... drawn in the kvot mark’s three tones only: polygons, no strokes, no gradients', (icon['fills'], icon['other']), (['#344126', '#bb6c5d', '#f3b87b'], False))

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
        # The main area's tab row and the panel's end at one line, whether the chain
        # settings stand beside the view tabs or, where they do not fit, above them.
        lines = []
        for w in (1280, 1600):
            await page.call('Emulation.setDeviceMetricsOverride', {'width': w, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
            await asyncio.sleep(0.3)
            lines.append(json.loads(await page.ev("""JSON.stringify((() => {
              const r = (s) => document.querySelector(s).getBoundingClientRect();
              return [r('.nz-views').bottom, r('.nz-tabs').bottom, r('.nz-views [data-view].active').bottom, r('.nz-tabs button.active').bottom,
                r('.nz-chainopts').top < r('.nz-viewtabs').top - 8]; })())""")))
        await page.call('Emulation.setDeviceMetricsOverride', {'width': 1280, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
        check('the tab rows of the main area and the panel end at one line, with the chain settings above the view tabs (1280 px) or beside them (1600 px)',
              [[abs(r[0] - r[1]) < 0.5, abs(r[2] - r[3]) < 0.5, r[4]] for r in lines], [[True, True, True], [True, True, False]])
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

        # ---------------------------------------------------------- parents
        par = json.loads(await page.ev("""(async () => {
          document.querySelector('[data-view=chart]').click();
          const row = () => { const dt = [...document.querySelectorAll('#nzPaneNuclide .nz-facts dt')].find(d => d.textContent === 'Parents'); return dt && dt.nextElementSibling; };
          ENSDFPage.select('Cl-36'); await new Promise(r => setTimeout(r, 100));
          const out = { none: row().textContent };
          ENSDFPage.select('Ra-226'); await new Promise(r => setTimeout(r, 150));
          const r = row();
          out.items = [...r.querySelectorAll('li')].map(li => li.textContent);
          out.links = [...r.querySelectorAll('a.nz-nuc')].map(a => a.getAttribute('href'));
          out.sups = r.querySelectorAll('a.nz-nuc sup').length;
          /* The chain the chart is given, caught on its way. */
          const ch = ENSDFPage.chart, set = ch.setChain; let overlay = null;
          ch.setChain = function (o) { overlay = o; return set.call(this, o); };
          const s = document.getElementById('nzChainDir'); s.value = 'up'; s.dispatchEvent(new Event('change', {bubbles: true}));
          await new Promise(r => setTimeout(r, 300));
          ch.setChain = set;
          out.tab = document.querySelector('[data-view=chain]').textContent;
          out.cells = overlay ? [88226, 90230, 92234, 92238].map(id => overlay.cells.has(id)) : null;
          out.into = overlay ? overlay.arrows.filter(a => a.z1 === 88 && a.n1 === 138).map(a => `${a.z0},${a.n0}`).sort() : null;
          out.card = document.querySelector('#nzPaneNuclide .nz-card h3').textContent;
          out.pressed = document.querySelector('#nzPaneNuclide .nz-card [data-dir=up]').getAttribute('aria-pressed');
          out.saved = JSON.parse(localStorage.getItem('kvot-ensdf-v1')).chainOpt.dir;
          return JSON.stringify(out); })()"""))
        check('a nuclide nothing decays to says so (36Cl)', par['none'], 'none: nothing in this database decays to it')
        check('the Nuclide tab lists the parents of 226Ra by mode, the longest-lived first, each with its share',
              par['items'], ['α ← 230Th 100 %', 'EC ← 226Ac 17 %', 'β− ← 226Fr 100 %'])
        check('... each a link, its mass number set as <sup>', (par['links'], par['sups']), (['#230Th', '#226Ac', '#226Fr'], 3))
        check('the chain set to parents: the view tab says so', par['tab'], 'Parents of 226Ra')
        check('... the chart rings 226Ra, 230Th, 234U and 238U', par['cells'], [True, True, True, True])
        check('... and draws an arrow into 226Ra from each parent', par['into'], ['87,139', '89,137', '90,140'])
        check('... the Nuclide tab\'s card follows, its parents button pressed, and the setting is kept', (par['card'], par['pressed'], par['saved']), ('Parents', 'true', 'up'))
        pv = json.loads(await page.ev("""(async () => {
          document.querySelector('[data-view=chain]').click(); await new Promise(r => setTimeout(r, 500));
          const svg = document.getElementById('nzChainSvg');
          const nodes = [...svg.querySelectorAll('.nz-node')];
          const boxes = nodes.map(g => g.querySelector('rect').getBoundingClientRect());
          const labels = [...svg.querySelectorAll('.nz-edge-label rect')].map(r => r.getBoundingClientRect());
          const hit = (p, q) => p.left < q.right - 1 && p.right > q.left + 1 && p.top < q.bottom - 1 && p.bottom > q.top + 1;
          const view = document.querySelector('.nz-chain-scroll').getBoundingClientRect();
          const ra = svg.querySelector('.nz-node[data-key="88,226,0"] rect').getBoundingClientRect();
          const cells = (z, a, k) => { const l = document.querySelector(`#nzChainTable a[data-z="${z}"][data-a="${a}"][data-k="${k}"]`); return l ? [...l.closest('tr').children].map(td => td.textContent) : null; };
          return JSON.stringify({ keys: nodes.map(g => g.dataset.key), covered: labels.filter(l => boxes.some(b => hit(l, b))).length,
            raInView: ra.top >= view.top - 1 && ra.bottom <= view.bottom + 1,
            head: [...document.querySelectorAll('#nzChainTable th')].map(th => th.textContent), ac: cells(89, 226, 0), u: cells(92, 238, 0),
            title: svg.querySelector('.nz-node[data-key="92,238,0"] title').textContent,
            note: document.getElementById('nzChainNote').textContent }); })()"""))
        check('the parents of 226Ra are drawn: 230Th, 234U, 238U, 226Ac and 226Fr', all(k in pv['keys'] for k in ('90,230,0', '92,234,0', '92,238,0', '89,226,0', '87,226,0')), True)
        check('... but not 226Th, where 226Ac\'s other branch goes, which never reaches 226Ra', '90,226,0' in pv['keys'], False)
        check('... no label on a box, and the view opens on 226Ra, at the foot of the drawing', (pv['covered'], pv['raInView']), (0, True))
        check('the table gives the share of each member\'s decays that reaches 226Ra', (pv['head'][2], pv['head'][3], pv['ac'][3], pv['u'][3]),
              ('Decays toward 226Ra by', 'Reaches 226Ra (% of its decays)', '17 %', '100 %'))
        check('... and so does a box\'s tooltip', pv['title'], lambda t: t.startswith('238U: T½ 4.468E9 y') and t.endswith('100 % of its decays reach 226Ra.'))
        check('... and the note says only the branches that lead to it are drawn', 'Only the branches that lead to it are drawn' in pv['note'], True)
        y1 = json.loads(await page.ev("""(async () => {
          const s = document.getElementById('nzMinLife'); s.value = '1y'; s.dispatchEvent(new Event('change', {bubbles: true}));
          await new Promise(r => setTimeout(r, 300));
          const out = { keys: [...document.querySelectorAll('#nzChainSvg .nz-node')].map(g => g.dataset.key),
            labels: [...document.querySelectorAll('#nzChainSvg .nz-edge-label text')].map(t => t.textContent),
            short: ENSDFPage.state.chain.nodes.filter(n => n !== ENSDFPage.state.chain.root && !(n.st.ts >= 31557600)).length,
            note: document.getElementById('nzChainNote').textContent };
          s.value = 'iso'; s.dispatchEvent(new Event('change', {bubbles: true})); await new Promise(r => setTimeout(r, 300));
          return JSON.stringify(out); })()"""))
        check('T½ ≥ 1 y: the parents of 226Ra keep 230Th, 234U, 238U, 238Pu and 242Pu, and none that lives less',
              (all(k in y1['keys'] for k in ('90,230,0', '92,234,0', '92,238,0', '94,238,0', '94,242,0')), y1['short']), (True, 0))
        check('... 238U goes to 234U by an arrow marked via 234Th, 234mPa', 'via 234Th, 234mPa' in y1['labels'], True)
        check('... and the note names what was left out, the nearest first: 226Fr, and 238Pa (2.3 min, nothing drawn above it)',
              ('Left out, as members that live less than 1 y: 226Fr' in y1['note'], '238Pa' in y1['note']), (True, True))
        up = json.loads(await page.ev("""(async () => {
          window.__saved = []; HTMLAnchorElement.prototype.click = function () {
            if (this.download) fetch(this.href).then(r => r.blob()).then(b => window.__saved.push([this.download, b.size])); };
          const g = document.querySelector('#nzChainSvg .nz-node[data-key="92,234,0"]');
          g.dispatchEvent(new MouseEvent('click', {bubbles: true})); await new Promise(r => setTimeout(r, 250));
          const out = { sel: ENSDFPage.state.sel, root: ENSDFPage.state.root, up: ENSDFPage.state.chain.up };
          ['nz:chainSvg', 'nz:chainPng', 'nz:chainCsv'].forEach(a => document.querySelector(`[data-on-click="${a}"]`).click());
          for (let i = 0; i < 40 && window.__saved.length < 3; i++) await new Promise(r => setTimeout(r, 100));
          out.files = window.__saved.map(f => f[0]).sort(); out.sizes = window.__saved.map(f => f[1]);
          return JSON.stringify(out); })()"""))
        check('a box among the parents opens that member, and the chain keeps its start', (up['sel'], up['root'], up['up']), ({'z': 92, 'a': 234, 'k': 0}, {'z': 88, 'a': 226, 'k': 0}, True))
        check('... and the parents save as SVG, PNG and CSV', (up['files'], all(s > 200 for s in up['sizes'])), (['parents-226Ra.csv', 'parents-226Ra.png', 'parents-226Ra.svg'], True))
        pi = json.loads(await page.ev("""(async () => {
          ENSDFPage.select('Ra-226'); document.querySelector('[data-tab=inventory]').click(); await new Promise(r => setTimeout(r, 500));
          const pane = document.getElementById('nzPaneInventory');
          const out = { head: pane.querySelector('.nz-pane-head').textContent, empty: document.getElementById('nzInvChart').textContent,
            set: [...pane.querySelectorAll('.nz-inv-table input')].filter(i => i.value).length };
          const th = pane.querySelector('input[data-key="90,230,0"]'); th.value = '1'; th.parentNode.querySelector('select').value = 'g';
          th.dispatchEvent(new Event('input', {bubbles: true})); await new Promise(r => setTimeout(r, 900));
          out.lines = document.querySelectorAll('#nzInvChart path').length;
          const r = document.querySelector('#nzInvChart svg').getBoundingClientRect();
          out.at = { x: r.left + r.width * 0.88, y: r.top + r.height * 0.45 };
          return JSON.stringify(out); })()"""))
        check('the Inventory tab takes the parents too, and none of them has an amount until one is given', (pi['head'], pi['set'], 'give one of the parents an amount' in pi['empty']),
              ('Inventory of the parents of 226Ra', 0, True))
        await page.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': pi['at']['x'], 'y': pi['at']['y']}, session=page.sid)
        await asyncio.sleep(0.2)
        grown = json.loads(await page.ev("""(() => {
          const num = (t) => { const m = /^([\\d.]+)(?:×10(−?\\d+))?$/.exec(t.trim()); return m ? +m[1] * Math.pow(10, m[2] ? +m[2].replace('−', '-') : 0) : NaN; };
          const v = (k) => num(document.querySelector(`#nzPaneInventory .nz-inv-now[data-key="${k}"]`).textContent);
          return JSON.stringify({ ra: v('88,226,0'), th: v('90,230,0'), at: document.getElementById('nzInvAt').textContent }); })()"""))
        await page.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 5, 'y': 5}, session=page.sid)
        # Long after 1600 y, 226Ra stands in transient equilibrium with 230Th: A(Ra)/A(Th) = 1/(1 - 1600/75400) = 1.02.
        check('1 g of 230Th grows 226Ra in: thousands of years on, in equilibrium with it', (pi['lines'] >= 2, grown['th'] > 1e8, 0.99 < grown['ra'] / grown['th'] < 1.05),
              (True, True, True))
        back = json.loads(await page.ev("""(async () => {
          document.querySelector('[data-tab=nuclide]').click();
          ENSDFPage.select('Pb-206'); await new Promise(r => setTimeout(r, 300));
          const card = () => document.querySelector('#nzPaneNuclide .nz-card');
          const out = { up: [card().querySelector('h3').textContent, card().textContent.includes('decay to 206Pb, directly or through others')] };
          card().querySelector('[data-dir=down]').click(); await new Promise(r => setTimeout(r, 300));
          out.down = [card().querySelector('h3').textContent, card().textContent.includes('206Pb is stable: no chain follows from it.'),
            document.getElementById('nzChainDir').value, document.querySelector('[data-view=chain]').textContent];
          return JSON.stringify(out); })()"""))
        check('a stable nuclide has parents (206Pb), and the card turns the chain back down', (back['up'], back['down']),
              (['Parents', True], ['Decay chain', True, 'down', 'Decay chain 206Pb']))

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

        # ---------------------------------------------------------- the full window
        # The toolbar's last button takes the site's header and footer away and puts
        # them back; in the full window the kvot mark leads home and the theme switch
        # is in the toolbar. The choice is kept, and the page's head applies it again
        # before the first paint.
        FULL = """JSON.stringify((() => {
          const shown = (s) => { const e = document.querySelector(s); return !!e && getComputedStyle(e).display !== 'none'; };
          const b = document.getElementById('nzFull'), home = document.querySelector('.nz-homelink');
          return { full: document.documentElement.classList.contains('nz-full'), header: shown('body > header'), footer: shown('body > footer'),
            home: shown('.nz-homelink'), href: home.getAttribute('href'), theme: shown('.nz-barend .theme-toggle'),
            pressed: b.getAttribute('aria-pressed'), title: b.title, corners: shown('#nzFull .nz-full-in') ? 'in' : 'out',
            last: b === [...document.querySelectorAll('.nz-bar button')].pop(),
            content: [document.querySelector('.content').getBoundingClientRect().top, document.querySelector('.content').getBoundingClientRect().height, innerHeight],
            body: document.querySelector('.nz-body').getBoundingClientRect().height, key: localStorage.getItem('kvot.ensdf.full') }; })())"""
        before = json.loads(await page.ev(FULL))
        check('the full-window button ends the toolbar; the header and footer are there, the mark and the toolbar’s theme switch are not',
              (before['last'], before['full'], before['header'], before['footer'], before['home'], before['theme'], before['pressed'], before['corners']),
              (True, False, True, True, False, False, 'false', 'out'))
        await page.ev("document.getElementById('nzFull').click(); 'ok'")
        await asyncio.sleep(0.4)
        full = json.loads(await page.ev(FULL))
        check('in the full window the header and footer are gone and the page has the whole height',
              (full['full'], full['header'], full['footer'], full['content'][0], full['content'][1] == full['content'][2]), (True, False, False, 0, True))
        check('... the chart and the panel grow into the room', full['body'] - before['body'], lambda d: d > 60)
        check('... the kvot mark leads home and the theme switch is in the toolbar', (full['home'], full['href'], full['theme']), (True, './index.html', True))
        check('... the button says it puts them back, its corners point in, and the choice is kept',
              (full['pressed'], full['title'], full['corners'], full['key']), ('true', 'Show the site’s header and footer again', 'in', '1'))
        themes = json.loads(await page.ev("""(async () => {
          const t = () => document.documentElement.getAttribute('data-theme'), b = document.querySelector('.nz-barend .theme-toggle');
          const out = [t()]; b.click(); await new Promise(r => setTimeout(r, 200)); out.push(t(), b.title);
          b.click(); await new Promise(r => setTimeout(r, 200)); out.push(t()); return JSON.stringify(out); })()"""))
        check('... where the theme switch changes the theme, and back', themes, ['light', 'dark', 'Switch to light mode', 'light'])
        await page.reload()
        again = json.loads(await page.ev(FULL))
        check('after a reload the page opens in the full window, button and all', (again['full'], again['header'], again['pressed'], again['corners']), (True, False, 'true', 'in'))
        await page.ev("document.getElementById('nzFull').click(); 'ok'")
        await asyncio.sleep(0.4)
        back = json.loads(await page.ev(FULL))
        check('the button brings the header and footer back, and that is kept too', (back['full'], back['header'], back['footer'], back['pressed'], back['key']),
              (False, True, True, 'false', '0'))
        await page.ev("localStorage.removeItem('kvot.ensdf.full'); 'ok'")

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
        await page.ev("localStorage.setItem('kvot.ensdf.full', '1'); 'ok'")
        await page.reload()
        wide = json.loads(await page.ev("""JSON.stringify((() => {
          const r = (s) => document.querySelector(s).getBoundingClientRect();
          return { sw: document.documentElement.scrollWidth, iw: innerWidth, full: document.documentElement.classList.contains('nz-full'),
            right: Math.max(...[...document.querySelectorAll('.nz-bar > *:not([hidden]), .nz-barend > *, .nz-main, .nz-panel')].map(e => e.getBoundingClientRect().right)),
            homeLine: Math.abs(r('.nz-homelink').top - r('.nz-search').top) < 8 }; })())"""))
        await page.ev("localStorage.removeItem('kvot.ensdf.full'); 'ok'")
        check('... nor in the full window, where the mark shares the search’s line', (wide['full'], wide['sw'] <= wide['iw'] and wide['right'] <= wide['iw'] + 0.5, wide['homeLine']),
              (True, True, True))

        check('no error reached the console', page.errors, [])
        await page.call('Target.closeTarget', {'targetId': tid})
        pump.cancel()

    print(f'\n{checks - len(failures)} of {checks} checks pass')
    if failures:
        print('failed:\n  ' + '\n  '.join(failures))
        sys.exit(1)


asyncio.run(main())
