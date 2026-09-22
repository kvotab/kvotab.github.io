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
          const out = [fits()]; document.getElementById('nz').style.setProperty('--nz-panel-width', '300px');
          await new Promise(r => setTimeout(r, 100)); out.push(fits());
          document.getElementById('nz').style.removeProperty('--nz-panel-width'); return JSON.stringify(out); })()"""))
        check('the panel tabs fit with no scroll bar of their own, at full width and dragged to 300 px', tabs, [[True, True], [True, True]])
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

        # ---------------------------------------------------------- opening a file
        opened = await page.ev(f"""(async () => {{ const b = Uint8Array.from(atob('{fixture_zip_b64()}'), c => c.charCodeAt(0));
          await ENSDFPage.openFiles([new File([b], 'ensdf_990101.zip')]);
          const s = ENSDFPage.state; return JSON.stringify({{ label: s.source.label, key: s.source.key,
            h3: s.idx.get(1, 3).s[0].t, menu: [...document.querySelectorAll('#nzDb option')].length,
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
        back = await settle(page, "ENSDFPage.state.source.key.startsWith('b:') && document.querySelectorAll('#nzDb option').length === 1", True)
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
