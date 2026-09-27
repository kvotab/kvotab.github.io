#!/usr/bin/env python3
"""smui.html in a real browser: the Graph menu.

Graph Builder opens without a launch dialog; columns reach its zones by a
real drag and drop (from the page's Columns panel and from the builder's own
list), by click-to-add and from the keyboard; elements come from the palette
and their properties change the graph at once; bars, boxes, cells, slices and
points are linked to the rows both ways; statsmodels' Bean (a beanplot's
violins, beans linked to their rows, split for two groups); Undo, Done,
Redo, a saved project and an edited title keep the state; row states apply;
it stays quick with 10,000 rows. Then every other Graph platform, checked
against numbers computed in the page: Scatterplot Matrix, Scatterplot 3D,
Contour Plot, Surface Plot, Bubble Plot, Parallel Plot, Cell Plot, Ternary
Plot, Treemap, the legacy Chart and Overlay Plot, and the Functional Data
Plot (its launch dialog's two data formats, band depths against their
definition, fboxplot's regions and outliers, curves linked by curve, Select
Outliers, Save Columns, the HDR boxplot and its score plot, the rainbow
plot, stacked and interpolated curves, By, the example). The dark theme and
phone width at the end.

Start a server on the repository root and headless Chrome (the recipe is in
README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-graph.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import os
import sys
import time
import urllib.request

import websockets

import cdp
from cdp import BASE, Checks, open_report_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


class GPage(cdp.Page):
    """cdp.Page that also keeps the drags Chrome intercepts (Input.dragIntercepted)."""

    def __init__(self, bws):
        super().__init__(bws)
        self.drags = []

    async def pump(self):
        try:
            async for raw in self.bws:
                r = json.loads(raw)
                m = r.get('method')
                if m == 'Input.dragIntercepted':
                    self.drags.append(r['params'])
                elif m == 'Runtime.exceptionThrown':
                    d = r['params']['exceptionDetails']
                    self.errors.append(str(d.get('exception', {}).get('description') or d.get('text', ''))[:600])
                elif m == 'Runtime.consoleAPICalled' and r['params'].get('type') == 'error':
                    self.console.append(' '.join(str(a.get('value', a.get('description', ''))) for a in r['params'].get('args', []))[:400])
                if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                    self.pending[r['id']].set_result(r)
        except websockets.ConnectionClosed:
            pass


async def open_page(url, width=1500, height=950):
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{cdp.CDP}/json/version'))
    bws = await websockets.connect(ver['webSocketDebuggerUrl'], max_size=400 * 1024 * 1024)
    page = GPage(bws)
    asyncio.create_task(page.pump())
    page.tid = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
    page.sid = (await page.call('Target.attachToTarget', {'targetId': page.tid, 'flatten': True}))['result']['sessionId']
    for m in ('Runtime.enable', 'Page.enable', 'Network.enable'):
        await page.call(m, session=page.sid)
    await page.call('Network.setCacheDisabled', {'cacheDisabled': True}, session=page.sid)
    await page.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.call('Page.addScriptToEvaluateOnNewDocument', {'source': "try{localStorage.setItem('kvot-theme','light')}catch(e){}"}, session=page.sid)
    await page.call('Page.navigate', {'url': url}, session=page.sid)
    return page


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.6)
        await page.shot(os.path.join(SHOTS, name))


async def drag(page, src, dst):
    """A real drag: Chrome starts it from a press and a move on src, hands the
    drag data over (drag interception), and it is dropped on dst."""
    xy = await page.ev(f'''(() => {{ const a = document.querySelector({json.dumps(src)}), b = document.querySelector({json.dumps(dst)});
      if (!a || !b) return null; a.scrollIntoView({{ block: 'center' }}); b.scrollIntoView({{ block: 'nearest' }});
      const r = a.getBoundingClientRect(), q = b.getBoundingClientRect(); return [r.x + 12, r.y + r.height / 2, q.x + q.width / 2, q.y + q.height / 2]; }})()''')
    if not xy:
        return 'no element'
    x0, y0, x1, y1 = xy
    await page.call('Input.setInterceptDrags', {'enabled': True}, session=page.sid)
    page.drags.clear()
    await page.mouse('mouseMoved', x0, y0)
    await page.mouse('mousePressed', x0, y0)
    for k in range(1, 8):
        await page.mouse('mouseMoved', x0 + 6 * k, y0 + 3 * k)
        await asyncio.sleep(0.05)
        if page.drags:
            break
    if not page.drags:
        await page.mouse('mouseReleased', x0, y0)
        await page.call('Input.setInterceptDrags', {'enabled': False}, session=page.sid)
        return 'no drag'
    data = page.drags[-1]['data']
    for kind in ('dragEnter', 'dragOver', 'drop'):
        await page.call('Input.dispatchDragEvent', {'type': kind, 'x': x1, 'y': y1, 'data': data}, session=page.sid)
    await page.mouse('mouseReleased', x1, y1)
    await page.call('Input.setInterceptDrags', {'enabled': False}, session=page.sid)
    await page.ev('window._gb && _gb.idle()')
    return 'dropped'


async def click_on(page, selector, modifiers=0):
    xy = await page.ev(f'''(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return null; e.scrollIntoView({{ block: 'nearest' }}); const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()''')
    if not xy:
        return False
    await page.click(xy[0], xy[1], modifiers)
    await asyncio.sleep(0.05)
    await page.ev('window._gb && _gb.idle()')
    return True


# Helpers in the page: the report's builder, a set-up of zones and elements, a click on a trace.
HELPERS = '''
window.gbSet = async (zones, els, props, extra) => {
  const t = _rep.table;
  await _gb.update(S => { for (const k of Object.keys(S.zones)) S.zones[k] = []; for (const [k, names] of Object.entries(zones)) S.zones[k] = names.map(n => ({ id: t.col(n).id, name: n })); S.auto = !els; if (els) S.elements = []; Object.assign(S, extra || {}); });
  if (els) await _gb.elements(els);
  for (const [type, kv] of Object.entries(props || {})) for (const [k, v] of Object.entries(kv)) await _gb.prop(type, k, v);
  return _gb.plot();
};
window.clickTrace = (p, curveNumber, pointNumber, extra) => p.box.emit('plotly_click', { points: [{ curveNumber, pointNumber, ...(extra || {}) }], event: {} });
window.rowsWhere = (t, fn) => [...Array(t.nrows).keys()].filter(fn);
window.jmpQ = (vals, p) => { const s = vals.slice().sort((a, b) => a - b), n = s.length, h = (n + 1) * p; if (h <= 1) return s[0]; if (h >= n) return s[n - 1]; const k = Math.floor(h); return s[k - 1] + (h - k) * (s[k] - s[k - 1]); };
window.meanOf = (v) => v.reduce((a, b) => a + b, 0) / v.length;
window.settle = () => new Promise(r => setTimeout(r, 120));
// The report's builder as it is now: a Redo (or Automatic Recalc) makes a new one.
Object.defineProperty(window, '_gb', { configurable: true, get: () => SM.platforms.get('graphbuilder').builder(window._rep) });
window.drawn = async (p) => { for (let i = 0; i < 150 && !p.drawn; i++) await new Promise(r => setTimeout(r, 20)); return p; };
window.lastPlot = async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; await drawn(rep.plots[0]); return [rep, rep.plots[0]]; };
window.rerun = async (fn) => { const done = new Promise(res => _rep.on('done', res)); await fn(); await done; await settle(); await _gb.idle(); };
// The (i) panel as it reads: its title, its section headings and the choices under each ([name, text, current]).
window.infoRead = () => {
  const p = document.querySelector('.info-panel'); if (!p) return null;
  const out = { title: p.querySelector('.info-panel-title').textContent, heads: [], choices: {} };
  let head = '';
  for (const n of p.querySelector('.info-panel-body').children) {
    if (n.tagName === 'H3') { head = n.textContent; out.heads.push(head); }
    else if (n.matches('dl.info-choices')) { const dd = [...n.querySelectorAll('dd')]; out.choices[head] = [...n.querySelectorAll('dt')].map((dt, i) => [dt.textContent, dd[i] ? dd[i].textContent : '', dt.classList.contains('is-current')]); }
  }
  return out;
};
window.infoClick = async (root) => { const b = root && root.querySelector('.info-btn'); if (!b) return null; b.click(); await settle(); return infoRead(); };
// A dialog from a menu item: the report's top red triangle, then the item.
window.menuDialog = async (rep, label) => {
  rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu').click(); await settle();
  const item = [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent.replace(/^✓/, '') === label);
  if (!item) return null; item.click(); await settle();
  return [...document.querySelectorAll('.sm-dialog')].pop() || null;
};
window.cancelDialog = async (dlg) => { [...dlg.querySelectorAll('button')].find(b => b.textContent === 'Cancel').click(); await settle(); };
'''

# A seeded table for the platforms that want continuous coordinates, IDs and times, and mixtures.
MAKE = '''(() => {
  const R = SM.util.rng('graph tests'); const n = 240;
  const c = { x: [], y: [], z: [], a: [], b: [], w: [], id: [], year: [], g: [], s: [] };
  for (let i = 0; i < n; i++) {
    const x = R.u() * 10, y = R.u() * 10;
    c.x.push(+x.toFixed(3)); c.y.push(+y.toFixed(3)); c.z.push(+(Math.sin(x / 1.5) * Math.cos(y / 2) * 10 + R.normal(0, 0.3)).toFixed(3));
    c.a.push(+(R.u() + 0.2).toFixed(3)); c.b.push(+(R.u() * 2).toFixed(3)); c.w.push(+R.u().toFixed(3));
    c.id.push(['Alpha', 'Beta', 'Gamma', 'Delta'][i % 4]); c.year.push(2000 + Math.floor(i / 4) % 6);
    c.g.push(i % 3 ? 'p' : 'q'); c.s.push(+(R.u() * 50 + 5).toFixed(1));
  }
  const t = new SM.Table({ name: 'Graph data', source: 'simulated', columns: [
    { name: 'x', values: c.x }, { name: 'y', values: c.y }, { name: 'z', values: c.z },
    { name: 'A', values: c.a }, { name: 'B', values: c.b }, { name: 'C', values: c.w },
    { name: 'country', dataType: 'character', values: c.id }, { name: 'year', values: c.year, modelingType: 'ordinal' },
    { name: 'g', dataType: 'character', values: c.g }, { name: 'pop', values: c.s } ] });
  SM.app.addTable(t);
  return t.nrows;
})()'''


# A seeded table of 40 curves at 16 points (t0 ... t15), without ties; row 5 much higher, row 11 of another shape.
FD_MAKE = '''(() => {
  const R = SM.util.rng('functional tests'); const n = 40, p = 16;
  const cols = [...Array(p)].map(() => []), name = [], grp = [];
  for (let i = 0; i < n; i++) {
    const level = R.normal(10, 1), amp = R.normal(3, 0.4), ph = R.normal(0, 0.3);
    let e = 0;
    for (let j = 0; j < p; j++) { e = 0.6 * e + R.normal(0, 0.2); let v = level + amp * Math.sin(2 * Math.PI * j / p + ph) + e; if (i === 5) v += 6; if (i === 11) v = 10 + 3 * Math.sin(4 * Math.PI * j / p); cols[j].push(v); }
    name.push(`C${String(i + 1).padStart(2, '0')}`); grp.push(i % 2 ? 'B' : 'A');
  }
  const t = new SM.Table({ name: 'FD test', source: 'simulated', columns: [{ name: 'name', dataType: 'character', values: name }, { name: 'grp', dataType: 'character', values: grp }, ...cols.map((v, j) => ({ name: 't' + j, values: v }))] });
  SM.app.addTable(t);
  return [t.nrows, t.columns.length - 1];
})()'''
FD_HELPERS = '''
// The modified band depth from its definition: the share of each band between two curves that holds the curve, averaged over the points.
window.mbdRef = (Y) => { const n = Y.length, p = Y[0].length, C2 = (k) => k * (k - 1) / 2; const out = new Array(n).fill(0);
  for (let t = 0; t < p; t++) for (let i = 0; i < n; i++) { let b = 0, a = 0; for (let j = 0; j < n; j++) { if (j === i) continue; if (Y[j][t] < Y[i][t]) b++; else if (Y[j][t] > Y[i][t]) a++; } out[i] += C2(n - 1) - C2(b) - C2(a); }
  return out.map((s) => (s / p + (n - 1)) / C2(n)); };
// What a Functional Data Plot report computed, for its first By group.
window.fdState = (rep, i) => SM.platforms.get('functional').state(rep, i || 0);
'''
# The same curves stacked (id, x, y), the rows shuffled.
FD_LONG = '''(() => {
  const w = SM.app.tables.find(t => t.name === 'FD test'); const R = SM.util.rng('shuffle');
  const rows = [];
  for (let i = 0; i < w.nrows; i++) for (let j = 0; j < 16; j++) rows.push([w.col('name').values[i], j, w.col('t' + j).values[i]]);
  for (let k = rows.length - 1; k > 0; k--) { const q = Math.floor(R.u() * (k + 1)); [rows[k], rows[q]] = [rows[q], rows[k]]; }
  const t = new SM.Table({ name: 'FD long', columns: [{ name: 'id', dataType: 'character', values: rows.map(r => r[0]) }, { name: 'x', values: rows.map(r => r[1]) }, { name: 'y', values: rows.map(r => r[2]) }] });
  SM.app.addTable(t); return t.nrows;
})()'''
# Stacked curves measured at different X: 20 of them, 20 points each.
FD_IRREGULAR = '''(() => {
  const R = SM.util.rng('irregular'); const id = [], x = [], y = [];
  for (let i = 0; i < 20; i++) { const xs = [...Array(20)].map(() => R.u() * 10).sort((a, b) => a - b); for (const v of xs) { id.push(`k${i}`); x.push(v); y.push(Math.sin(v / 2) + 0.2 * i + R.normal(0, 0.05)); } }
  const t = new SM.Table({ name: 'FD irregular', columns: [{ name: 'id', dataType: 'character', values: id }, { name: 'x', values: x }, { name: 'y', values: y }] });
  SM.app.addTable(t); return t.nrows;
})()'''


async def main():
    page = await open_page(f'{BASE}/smui.html?example=students')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "graph").map(f => f.error)')
    check('graph.py imports in Pyodide', failed, [])
    names = await page.ev('SM.engine.names.filter(n => n.startsWith("graph."))')
    check('the graph functions are registered', sorted(names), ['graph.bean', 'graph.chisq', 'graph.density', 'graph.ellipse', 'graph.fbox', 'graph.fit', 'graph.hdr', 'graph.interp', 'graph.kde1', 'graph.smoother', 'graph.summary'])
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    menu = await page.ev('''(() => { const items = SM.app.menuItems("Graph"); const leg = items.find(i => i.label === "Legacy");
      return { top: items.map(i => i.label || (i.separator ? "—" : "")), legacy: leg ? (typeof leg.submenu === "function" ? leg.submenu() : leg.submenu).map(i => i.label) : null }; })()''')
    check('the Graph menu in JMP\'s order, statsmodels\' Functional Data Plot among them', [m for m in menu['top'] if m != '—'], ['Graph Builder', 'Scatterplot Matrix…', 'Scatterplot 3D…', 'Contour Plot…', 'Bubble Plot…', 'Parallel Plot…', 'Cell Plot…', 'Ternary Plot…', 'Treemap…', 'Functional Data Plot…', 'Surface Plot…', 'Legacy'])
    check('Graph > Legacy', menu['legacy'], ['Chart…', 'Overlay Plot…'])
    help_rows = await page.ev('["graphbuilder","scattermatrix","scatter3d","contour","surface","bubble","parallel","cellplot","ternary","treemap","functional","chart","overlay"].filter(id => !document.getElementById("help-p-" + id))')
    check('every Graph platform has its row in Help', help_rows, [])

    # ---- Graph Builder: no launch dialog, the builder in the report
    r = await page.ev('''(async () => {
      SM.app.launch('graphbuilder');
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      window._rep = rep;
      return { dialog: !!document.querySelector('.sm-launch-dialog'), title: rep.title, active: SM.app.activeTab.report === rep,
        cols: [...rep.body.querySelectorAll('.sm-gb-collist li .sm-colname')].map(e => e.textContent),
        zones: [...rep.body.querySelectorAll('.sm-gb-zone .sm-gb-zlabel')].map(e => e.textContent),
        palette: [...rep.body.querySelectorAll('.sm-gb-el .sm-gb-elname')].map(e => e.textContent),
        empty: !!rep.body.querySelector('.sm-gb-empty'), auto: rep.spec.autoRecalc };
    })()''')
    await page.ev(HELPERS)
    check('Graph Builder opens without a launch dialog', (r['dialog'], r['title'], r['active']), (False, 'Graph Builder', True))
    check('its column list', r['cols'], ['id', 'age', 'sex', 'height (cm)', 'weight (kg)'])
    check('the drop zones', sorted(r['zones']), sorted(['X', 'Y', 'Group X', 'Group Y', 'Wrap', 'Overlay', 'Color', 'Size', 'Freq']))
    check('the element palette, with statsmodels\' Bean', r['palette'], ['Points', 'Smoother', 'Line of Fit', 'Ellipse', 'Contour', 'Line', 'Bar', 'Area', 'Box Plot', 'Bean', 'Histogram', 'Heatmap', 'Mosaic', 'Caption Box', 'Pie'])
    check('an empty graph asks for columns', r['empty'], True)
    check('Graph Builder follows the table (Automatic Recalc)', r['auto'], True)
    await shot(page, 'g01-empty.png')

    # ---- real drag and drop: from the page's Columns panel and from the builder's list
    d1 = await drag(page, '.sm-collist li[data-id]:nth-child(5) .sm-colname', '.sm-gb-z-y')
    d2 = await drag(page, '.sm-gb-collist li[data-id]:nth-child(4)', '.sm-gb-z-x')
    r = await page.ev('''(() => { const S = _gb.state(); const p = _gb.plot(); return { y: S.zones.y.map(z => z.name), x: S.zones.x.map(z => z.name), els: S.elements.map(e => e.type),
      types: p.traces.map(t => t.type + ':' + t.mode), n: p.rows[0] ? p.rows[0].length : 0, grid: p.traces[1] ? p.traces[1].x.length : 0, code: _rep.pythonScript() }; })()''')
    check('drag from the Columns panel onto Y', (d1, r['y']), ('dropped', ['weight (kg)']))
    check('drag from the builder\'s list onto X', (d2, r['x']), ('dropped', ['height (cm)']))
    check('two continuous columns: Points and Smoother, as JMP', r['els'], ['points', 'smoother'])
    check('the points are linked, a row each', r['n'], 60)
    check('the smoother is a curve over X', (r['types'][1], r['grid']), ('scatter:lines', 120))
    check('the script holds the smoothing spline', 'make_smoothing_spline' in r['code'] and 'lam=0.05' in r['code'], True)
    await shot(page, 'g02-scatter.png')

    # ---- click-to-add (touch, keyboard): select a column, then a zone
    await click_on(page, '.sm-gb-collist li[data-id]:nth-child(3)')
    picked = await page.ev('_rep.body.querySelector(".sm-gb").classList.contains("has-pick")')
    await click_on(page, '.sm-gb-z-overlay')
    r = await page.ev('''(() => { const p = _gb.plot(); return { ov: _gb.state().zones.overlay.map(z => z.name), legend: p.traces.filter(t => t.showlegend).map(t => t.name), curves: p.traces.filter(t => t.mode === 'lines').length }; })()''')
    check('a picked column shows the zones as targets', picked, True)
    check('click a column, then Overlay', r['ov'], ['sex'])
    check('the legend has the levels', r['legend'], ['F', 'M'])
    check('a smoother for each level', r['curves'], 2)
    # the keyboard: Enter on a column lists the zones
    r = await page.ev('''(async () => {
      const li = [..._rep.body.querySelectorAll('.sm-gb-collist li[data-id]')].find(l => l.textContent === 'age');
      li.focus(); li.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      await settle();
      const items = [...document.querySelectorAll('.sm-menu button')].map(b => b.textContent);
      const gx = [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent === 'Group X');
      gx.click();
      await settle(); await _gb.idle();
      const p = _gb.plot(); const L = p.userLayout;
      return { items, gx: _gb.state().zones.groupX.map(z => z.name), panels: Object.keys(L).filter(k => /^xaxis\\d*$/.test(k)).length, matches: Object.keys(L).filter(k => /^xaxis\\d+$/.test(k)).map(k => L[k].matches).filter(Boolean).length };
    })()''')
    check('Enter on a column lists the zones', [i for i in r['items'] if i in ('X', 'Y', 'Group X', 'Freq')], ['X', 'Y', 'Group X', 'Freq'])
    check('age in Group X', r['gx'], ['age'])
    check('a panel per age, sharing the Y axis', (r['panels'], r['matches']), (6, 0))
    await shot(page, 'g03-groupx.png')
    # a column's menu in its zone: Remove
    r = await page.ev('''(async () => {
      const chip = _rep.body.querySelector('.sm-gb-z-groupX .sm-gb-chip'); chip.click(); await settle();
      [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent === 'Remove').click();
      await settle(); await _gb.idle();
      return _gb.state().zones.groupX.length;
    })()''')
    check('Remove from a zone\'s column menu', r, 0)

    # ---- Bar: summary statistics, linking both ways
    r = await page.ev('''(async () => {
      const t = _rep.table;
      await gbSet({ x: ['sex'], y: ['weight (kg)'] });
      const auto = _gb.state().elements.map(e => e.type);
      _rep.body.querySelector('.sm-gb-el[data-el="bar"]').click(); await _gb.idle();
      const p = _gb.plot();
      const sex = t.col('sex'), w = t.col('weight (kg)');
      const want = ['F', 'M'].map(s => meanOf(rowsWhere(t, r => sex.values[r] === s).map(r => w.values[r])));
      return { auto, els: _gb.state().elements.map(e => e.type), heights: p.traces[0].y, want, x: p.traces[0].x };
    })()''')
    check('categorical X and continuous Y: Points', r['auto'], ['points'])
    check('the palette shows Bar alone', r['els'], ['bar'])
    check.near('the mean of each level, F', r['heights'][0], r['want'][0], 1e-9)
    check.near('the mean of each level, M', r['heights'][1], r['want'][1], 1e-9)
    r = await page.ev('''(async () => {
      const t = _rep.table;
      const sel = _rep.body.querySelector('.sm-gb-prop[data-el="bar"] select[data-gbkey="prop:bar:summary"]');
      sel.value = 'n'; sel.dispatchEvent(new Event('change', { bubbles: true })); await _gb.idle();
      const p = _gb.plot();
      const sex = t.col('sex');
      const counts = ['F', 'M'].map(s => rowsWhere(t, r => sex.values[r] === s).length);
      clickTrace(p, 0, 1);
      const want = rowsWhere(t, r => sex.values[r] === 'M');
      const selOk = JSON.stringify(t.selectedRows()) === JSON.stringify(want);
      t.select([0, 1, 2, 3, 4, 5, 6, 7]); await settle();
      const ov = p.box.data[1].y;
      const f8 = rowsWhere(t, r => r < 8 && sex.values[r] === 'F').length;
      t.select([]);
      return { heights: p.traces[0].y, counts, selOk, ov, f8 };
    })()''')
    check('Summary Statistic N from the properties', r['heights'], r['counts'])
    check('a click on a bar selects its rows', r['selOk'], True)
    check('selected rows show as the selected share of each bar', r['ov'], [r['f8'], 8 - r['f8']])
    r = await page.ev('''(async () => {
      await _gb.prop('bar', 'summary', 'mean'); await _gb.prop('bar', 'interval', 'ci');
      const p = _gb.plot(); const e = p.traces[0].error_y;
      return { has: !!e && e.array.length === 2 && e.array.every(v => v > 0), code: _rep.pythonScript().includes('stats.t.interval') };
    })()''')
    check('Error Interval: the confidence interval of the mean (from Python)', (r['has'], r['code']), (True, True))
    # shift-click adds an element
    await click_on(page, '.sm-gb-el[data-el="points"]', modifiers=8)
    r = await page.ev('''(() => { const p = _gb.plot(); const pts = p.traces.find(t => t.mode === 'markers' && Array.isArray(p.rows[p.traces.indexOf(t)]));
      return { els: _gb.state().elements.map(e => e.type), jitter: pts ? pts.x.every(v => Math.abs(v - Math.round(v)) <= 0.41) : null }; })()''')
    check('shift-click adds Points to Bar', r['els'], ['bar', 'points'])
    check('points jittered within their level', r['jitter'], True)
    # Packed jitter: side by side at each level, none on another (measured on the drawn axes)
    r = await page.ev('''(async () => {
      const p = await drawn(await gbSet({ x: ['sex'], y: ['height (cm)'] }, ['points'], { points: { jitter: 'packed' } }));
      const gd = p.box;
      const ti = p.traces.findIndex((t, i) => t.mode === 'markers' && Array.isArray(p.rows[i]));
      const tr = gd.data[ti], xa = gd._fullLayout.xaxis, ya = gd._fullLayout.yaxis;
      const px = tr.x.map(v => xa.l2p(v)), py = tr.y.map(v => ya.l2p(v));
      let overlaps = 0, pairs = 0, closest = Infinity;
      for (let i = 0; i < px.length; i++) for (let j = i + 1; j < px.length; j++) {
        if (Math.round(tr.x[i]) !== Math.round(tr.x[j])) continue;
        pairs++; const d = Math.hypot(px[i] - px[j], py[i] - py[j]); closest = Math.min(closest, d); if (d < 0.9 * tr.marker.size) overlaps++;
      }
      const offs = tr.x.map(v => v - Math.round(v));
      return { overlaps, pairs, closest, size: tr.marker.size, within: offs.every(o => Math.abs(o) <= 0.41), centred: Math.abs(offs.reduce((a, b) => a + b, 0) / offs.length) < 0.05, n: p.rows[ti].length, jitter: _gb.state().elements[0].jitter };
    })()''')
    check('Packed jitter: no two points of a level overlap on the drawn graph', (r['jitter'], r['overlaps'], r['pairs'] > 300), ('packed', 0, True))
    check('... they stay within their level, around its middle', (r['within'], r['centred']), (True, True))

    # ---- Box Plot: JMP's quantiles; outliers linked point by point
    r = await page.ev('''(async () => {
      const t = _rep.table;
      await gbSet({ x: ['sex'], y: ['height (cm)'] }, ['box']);
      const p = _gb.plot(); const b = p.traces[0];
      const sex = t.col('sex'), h = t.col('height (cm)');
      const v = rowsWhere(t, r => sex.values[r] === 'F').map(r => h.values[r]);
      clickTrace(p, 0, 0, { x: 0, y: 150 });
      const n = t.selectedRows().length; t.select([]);
      return { q1: b.q1[0], med: b.median[0], q3: b.q3[0], w: [jmpQ(v, 0.25), jmpQ(v, 0.5), jmpQ(v, 0.75)], n, nF: v.length };
    })()''')
    check.near('box: first quartile ((n+1)p)', r['q1'], r['w'][0], 1e-9)
    check.near('box: median', r['med'], r['w'][1], 1e-9)
    check.near('box: third quartile', r['q3'], r['w'][2], 1e-9)
    check('a click on a box selects its rows', r['n'], r['nF'])

    # ---- Bean: statsmodels' beanplot, the beans linked to their rows
    r = await page.ev('''(async () => {
      const t = _rep.table;
      const p = await gbSet({ x: ['age'], y: ['height (cm)'] }, ['bean']);
      const age = t.col('age'), h = t.col('height (cm)');
      const lv = t.levels(age);
      const vio = p.traces.filter(tr => tr.fill === 'toself');
      const beans = p.traces.map((tr, i) => [tr, i]).filter(([tr, i]) => Array.isArray(p.rows[i]) && tr.marker && tr.marker.symbol === 'line-ew-open');
      const widths = vio.map((tr, k) => Math.max(...tr.x.map(v => Math.abs(v - k))));
      const means = lv.map(a => meanOf(rowsWhere(t, r => age.values[r] === a).map(r => h.values[r])));
      const medians = lv.map(a => jmpQ(rowsWhere(t, r => age.values[r] === a).map(r => h.values[r]), 0.5));
      const meanTr = p.traces.find(tr => tr.mode === 'lines' && tr.line && tr.line.width === 2.6);
      const medTr = p.traces.find(tr => tr.marker && tr.marker.symbol === 'cross-thin-open');
      const overall = p.userLayout.shapes.filter(sh => sh.line && sh.line.dash === 'dot').map(sh => sh.y0);
      const [bt, bi] = beans[2];
      clickTrace(p, bi, 1);
      const sel = t.selectedRows(), want = p.rows[bi][1];
      t.select([want]); await settle();
      const hl = p.box.data[bi].selectedpoints;
      t.select([]);
      return { nVio: vio.length, widths, nBeans: beans.reduce((a, [, i]) => a + p.rows[i].length, 0), means, gotMeans: meanTr.y.filter((v, k) => k % 3 === 0), medians, gotMed: medTr.y,
        overall, want: meanOf(h.values), sel, wantSel: [want], hl, notes: _gb.notes().join(' '), code: _rep.pythonScript() };
    })()''')
    check('bean: a violin for each age', r['nVio'], 6)
    check('bean: every violin drawn to one width (statsmodels\' beanplot)', all(abs(w - 0.4) < 1e-9 for w in r['widths']), True)
    check('bean: a bean for every row, linked', r['nBeans'], 60)
    check('bean: the mean line of each level', all(abs(a - b) < 1e-9 for a, b in zip(r['gotMeans'], r['means'])) and len(r['gotMeans']) == 6, True)
    check('bean: the median mark of each level (the middle value)', all(abs(a - b) < 1e-9 for a, b in zip(r['gotMed'], r['medians'])), True)
    check.near('bean: the overall mean dotted across the panel', r['overall'][0] if r['overall'] else None, r['want'], 1e-9)
    check('bean: a click on a bean selects its row', r['sel'], r['wantSel'])
    check('bean: a selected row shows on its bean', r['hl'], [1])
    check('bean: the notes and the Python say it is statsmodels\' beanplot', ('statsmodels\' beanplot' in r['notes'], 'gaussian_kde' in r['code'] and 'beanplot' in r['code']), (True, True))
    r = await page.ev('''(async () => {
      const p = await gbSet({ x: ['age'], y: ['height (cm)'], overlay: ['sex'] }, ['bean'], { bean: { split: true } });
      const vio = p.traces.filter(tr => tr.fill === 'toself');
      const sides = vio.map(tr => { const pos = Math.round(tr.x.reduce((a, b) => a + b, 0) / tr.x.length); const lo = Math.min(...tr.x), hi = Math.max(...tr.x); return [tr.legendgroup, lo >= pos - 1e-9 ? 'right' : hi <= pos + 1e-9 ? 'left' : 'both']; });
      const legend = p.traces.filter(tr => tr.showlegend).map(tr => tr.name);
      const q = await gbSet({ x: ['height (cm)'], y: ['weight (kg)'] }, ['bean']);
      const refused = _gb.notes().some(n => n.startsWith('Bean needs')), why = _rep.body.querySelector('.sm-gb-el[data-el="bean"]').getAttribute('aria-disabled');
      const horiz = await gbSet({ x: ['weight (kg)'], y: ['sex'] }, ['bean'], { bean: { beans: 'jitter' } });
      const hb = horiz.traces.find((tr, i) => Array.isArray(horiz.rows[i]));
      return { sides, legend, refused, why, n: q.traces.length,
        horizOk: !!hb && hb.x.every(v => Number.isFinite(v)) && hb.y.every(v => Math.abs(v - Math.round(v)) < 0.41) };
    })()''')
    check('bean: Split Two Groups draws F on the left and M on the right of each bean', ({sd for g_, sd in r['sides'] if g_ == 'g0'}, {sd for g_, sd in r['sides'] if g_ == 'g1'}, len(r['sides']) >= 10), ({'left'}, {'right'}, True))
    check('bean: two continuous columns are refused, as JMP\'s elements say why', (r['refused'], r['why']), (True, 'true'))
    check('bean: the Overlay\'s levels in the legend', r['legend'], ['F', 'M'])
    check('bean: horizontal with jittered points within the violins', r['horizOk'], True)
    await shot(page, 'g03b-bean.png')

    # ---- Histogram, Heatmap, Mosaic, Pie, Caption Box, Line of Fit
    r = await page.ev('''(async () => {
      const t = _rep.table;
      const p = await gbSet({ x: ['height (cm)'] }, ['histogram']);
      const tot = p.traces[0].y.reduce((a, b) => a + b, 0);
      const m = await gbSet({ x: ['age'], y: ['sex'] }, ['mosaic'], { mosaic: { chisq: true } });
      const age = t.col('age'), sex = t.col('sex');
      const n12 = rowsWhere(t, r => age.values[r] === 12).length, f12 = rowsWhere(t, r => age.values[r] === 12 && sex.values[r] === 'F').length;
      const ann = m.userLayout.annotations.map(a => a.text).find(s => s.startsWith('Pearson'));
      const h = await gbSet({ x: ['age'], y: ['sex'] }, ['heatmap']);
      clickTrace(h, 0, [1, 0]);
      const cell = t.selectedRows().length; t.select([]);
      const m12 = rowsWhere(t, r => age.values[r] === 12 && sex.values[r] === 'M').length;
      const pie = await gbSet({ x: ['age'] }, ['pie']);
      clickTrace(pie, 0, 2); await settle();
      const pull = pie.box.data[0].pull; t.select([]);
      return { tot, mosaicF12: m.traces[0].y[0], wantF12: f12 / n12, ann, cell, m12, pieVals: pie.traces[0].values, pull };
    })()''')
    check('histogram: the bins hold every row', r['tot'], 60)
    check.near('mosaic: the share of F at age 12', r['mosaicF12'], r['wantF12'], 1e-12)
    check('mosaic: the chi-square test on the graph', bool(r['ann']) and 'df 5' in r['ann'], True)
    check('heatmap: a cell click selects its rows', r['cell'], r['m12'])
    check('pie: a slice per age, the selected one pulled out', (len(r['pieVals']), r['pull'][2] > 0, sum(r['pull']) == r['pull'][2]), (6, True, True))
    r = await page.ev('''(async () => {
      const t = _rep.table;
      const p = await gbSet({ x: ['height (cm)'], y: ['weight (kg)'] }, ['points', 'fit'], { fit: { equation: true, r2: true } });
      const x = t.col('height (cm)').values, y = t.col('weight (kg)').values;
      const mx = meanOf(x), my = meanOf(y);
      let sxy = 0, sxx = 0; for (let i = 0; i < x.length; i++) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) ** 2; }
      const slope = sxy / sxx;
      const ann = p.userLayout.annotations.map(a => a.text).join(' | ');
      const cap = await gbSet({ x: ['sex'], y: ['height (cm)'] }, ['points', 'caption'], { caption: { stats: ['mean', 'n'] } });
      const capText = cap.userLayout.annotations.map(a => a.text);
      return { slope, ann, band: p.traces.some(t => t.fill === 'toself'), capText, mean: SM.util.fmt(meanOf(t.col('height (cm)').values), { sig: 5 }) };
    })()''')
    check('Line of Fit: the least-squares slope in its equation', SM_fmt4(r['slope']) in r['ann'], True)
    check('Line of Fit: R² and the confidence band', ('R²' in r['ann'], r['band']), (True, True))
    check('Caption Box: the mean and N of the panel', any('Mean:' in t and 'N: 60' in t for t in r['capText']), True)

    # ---- Wrap, Color (continuous and categorical), Size, Freq, several Y
    r = await page.ev('''(async () => {
      const t = _rep.table;
      const w = await gbSet({ x: ['height (cm)'], y: ['weight (kg)'], wrap: ['age'] }, ['points']);
      const wrapPanels = Object.keys(w.userLayout).filter(k => /^xaxis\\d*$/.test(k)).length;
      const c = await gbSet({ x: ['height (cm)'], y: ['weight (kg)'], color: ['height (cm)'], size: ['weight (kg)'] }, ['points']);
      const bar = c.traces.some(tr => tr.marker && tr.marker.showscale);
      const sizes = c.traces[0].marker.size;
      const m = await gbSet({ x: ['age'], y: ['height (cm)', 'weight (kg)'] }, ['points'], {}, { yMode: 'merge' });
      const merged = m.traces.filter(tr => tr.showlegend).map(tr => tr.name);
      const s = await gbSet({ x: ['age'], y: ['height (cm)', 'weight (kg)'] }, ['points'], {}, { yMode: 'side' });
      const sideRows = Object.keys(s.userLayout).filter(k => /^yaxis\\d*$/.test(k)).length;
      return { wrapPanels, bar, sizeVaries: Array.isArray(sizes) && Math.max(...sizes) > Math.min(...sizes) + 5, merged, sideRows };
    })()''')
    check('Wrap: a panel per level', r['wrapPanels'], 6)
    check('Color by a continuous column: a gradient with its colour bar', r['bar'], True)
    check('Size: the points\' size follows the column', r['sizeVaries'], True)
    check('several Y merged on one axis, with a legend', r['merged'], ['height (cm)', 'weight (kg)'])
    check('several Y side by side: a panel row each', r['sideRows'], 2)
    r = await page.ev('''(async () => {
      const t = _rep.table;
      const c = t.addColumn({ name: 'count', dataType: 'numeric', values: Array.from({ length: t.nrows }, (_, i) => 1 + (i % 3)) });
      await settle();
      const listed = [..._rep.body.querySelectorAll('.sm-gb-collist li .sm-colname')].map(e => e.textContent).includes('count');
      const p = await gbSet({ x: ['sex'], freq: ['count'] }, ['bar']);
      const sex = t.col('sex');
      const want = ['F', 'M'].map(s => rowsWhere(t, r => sex.values[r] === s).reduce((a, r) => a + c.values[r], 0));
      await rerun(() => t.removeColumn(c.id));
      return { got: p.traces[0].y, want, freq: _gb.state().zones.freq.length, listed };
    })()''')
    check('a new column shows in the builder\'s list at once', r['listed'], True)
    check('Freq: N is the sum of the counts', r['got'], r['want'])
    check('a deleted column leaves its zone', r['freq'], 0)

    # ---- row states: hidden, labeled, colours (the Color zone wins)
    r = await page.ev('''(async () => {
      const t = _rep.table;
      const p = await gbSet({ x: ['height (cm)'], y: ['weight (kg)'] }, ['points']);
      t.setState([4], 'hidden', true); t.setState([5], 'labeled', true); t.setColor([6], 3); await settle();
      const d = p.box.data[0]; const k4 = p.rows[0].indexOf(4), k5 = p.rows[0].indexOf(5), k6 = p.rows[0].indexOf(6);
      const out = { hidden: d.y[k4], label: d.text ? d.text[k5] : null, color: Array.isArray(d.marker.color) ? d.marker.color[k6] : d.marker.color };
      const c = await gbSet({ x: ['height (cm)'], y: ['weight (kg)'], color: ['sex'] }, ['points']);
      const i = c.rows.findIndex((rs) => Array.isArray(rs) && rs.includes(6));
      const q = c.box.data[i];
      out.masked = Array.isArray(q.marker.color) ? q.marker.color[c.rows[i].indexOf(6)] : q.marker.color;
      t.clearRowStates(); await settle();
      return out;
    })()''')
    if not isinstance(r, dict):
        print('   row states:', r)
        r = {}
    check('a hidden row is not drawn', r.get('hidden', 'missing'), None)
    check('a labeled row shows its label', r.get('label'), 'S06')
    check('a row\'s colour shows', r.get('color'), '#b0413e')
    check('with a Color column the zone\'s colours win', r.get('masked') not in (None, '#b0413e'), True)

    # ---- Undo, Done, Redo, a saved project, an edited title
    r = await page.ev('''(async () => {
      await gbSet({ x: ['sex'], y: ['height (cm)'] }, ['box']);
      await _gb.add('overlay', 'age');
      const before = _gb.state().zones.overlay.length;
      _rep.body.querySelector('[data-gbkey="undo"]').click(); await _gb.idle();
      const after = _gb.state().zones.overlay.length;
      _rep.body.querySelector('[data-gbkey="done"]').click(); await _gb.idle();
      const hidden = _rep.body.querySelector('.sm-gb-left').offsetParent === null && _rep.body.querySelector('.sm-gb-palette').offsetParent === null;
      const plotShown = _gb.plot().box.offsetParent !== null;
      return { before, after, hidden, plotShown };
    })()''')
    check('Undo steps back', (r['before'], r['after']), (1, 0))
    check('Done hides the control panel and leaves the graph', (r['hidden'], r['plotShown']), (True, True))
    await shot(page, 'g04-done.png')
    r = await page.ev('''(async () => {
      const top = _rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu'); top.click(); await settle();
      [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent === 'Show Control Panel').click(); await settle(); await _gb.idle();
      const back = _rep.body.querySelector('.sm-gb-left').offsetParent !== null;
      _gb.plot().box.emit('plotly_relayout', { 'title.text': 'Heights by sex' });
      await rerun(() => _rep.run());
      const p = _gb.plot();
      return { back, title: p.userLayout.title.text, els: _gb.state().elements.map(e => e.type), zones: _gb.state().zones.x.map(z => z.name) };
    })()''')
    check('Show Control Panel brings it back', r['back'], True)
    check('Redo keeps the state and the edited title', (r['title'], r['els'], r['zones']), ('Heights by sex', ['box'], ['sex']))
    r = await page.ev('''(async () => {
      const t = _rep.table;
      const proj = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [_rep.toJSON()] };
      const n0 = SM.app.reports.length;
      SM.app.loadProject(JSON.parse(JSON.stringify(proj)));
      const rep = SM.app.reports[SM.app.reports.length - 1];
      SM.app.showTab(SM.app.tabOf(rep));
      await new Promise(res => { if (rep.body.querySelector('.sm-gb')) res(); else rep.on('done', res); });
      const gb = rep.body.querySelector('.sm-gb')._gb; await gb.idle();
      const S = gb.state();
      const ok = S.zones.x.every(z => rep.table.col(z.id) && rep.table.col(z.id).name === z.name) && rep.table !== t;
      const out = { n: SM.app.reports.length - n0, x: S.zones.x.map(z => z.name), y: S.zones.y.map(z => z.name), ok, traces: gb.plot() ? gb.plot().traces.length : 0 };
      SM.app.closeReport(rep); SM.app.closeTable(rep.table);
      SM.app.showTab(SM.app.tabOf(_rep));
      return out;
    })()''')
    check('a saved project opens the builder on the new table\'s columns', (r['n'], r['x'], r['y'], r['ok']), (1, ['sex'], ['height (cm)'], True))
    check('and draws the graph', r['traces'] > 0, True)

    # ---- the (i): what every zone, element and property is for, following the graph on show
    r = await page.ev('''(async () => {
      KvotInfo.close();
      await gbSet({ x: ['height (cm)'], y: ['weight (kg)'] }, ['points', 'smoother']);
      const main = await infoClick(_rep.body.querySelector('.sm-gb-bar'));
      const props = await infoClick(_rep.body.querySelector('.sm-gb-props h4'));
      // the controls the Properties panel shows, element by element
      const shown = [..._rep.body.querySelectorAll('.sm-gb-prop')].map(fs => [fs.querySelector('legend').textContent.replace('×', '').trim(),
        [...fs.querySelectorAll(':scope > .sm-gb-field')].map(f => (f.querySelector(':scope > span') || f.querySelector(':scope > label')).textContent)]);
      // a change while the (i) is open: the Local Kernel's settings come first
      await _gb.prop('smoother', 'method', 'lowess');
      const after = infoRead();
      KvotInfo.close();
      return { main, props, shown, after, audit: KvotInfo.audit().noTopic };
    })()''')
    check('Graph Builder\'s (i): zones, builder, elements, the properties of the elements in the graph, red triangle', [h for h in r['main']['heads'] if h in ('Zones', 'The builder', 'Elements', 'Properties: Points', 'Properties: Smoother', 'The red triangle')], ['Zones', 'The builder', 'Elements', 'Properties: Points', 'Properties: Smoother', 'The red triangle'])
    check('... every zone explained', [c[0] for c in r['main']['choices']['Zones']], ['X, Y', 'Group X, Group Y', 'Wrap', 'Overlay', 'Color', 'Size', 'Freq'])
    check('... the elements in the graph marked', [c[0] for c in r['main']['choices']['Elements'] if c[2]], ['Points', 'Smoother'])
    check('... the builder\'s buttons', [c[0] for c in r['main']['choices']['The builder'] if c[0] in ('Undo', 'Start Over', 'Done')], ['Undo', 'Start Over', 'Done'])
    shown = dict(r['shown'])
    check('the Properties heading has its own (i), a section per element', (r['props']['title'], r['props']['heads']), ('Properties', ['Points', 'Smoother']))
    check('... listing the controls the panel shows, in its order, first', {k: [c[0] for c in r['props']['choices'][k]][:len(v)] for k, v in shown.items()}, shown)
    check('... then those that come with another choice, saying when', [c[1].split('.')[0] for c in r['props']['choices']['Points'][len(shown['Points']):]], ['Shown with a Summary Statistic'])
    check('... every control with a real explanation', all(len(c[1]) > 40 for k in r['props']['choices'] for c in r['props']['choices'][k]), True)
    check('an open (i) follows a change: Local Kernel\'s settings first', [c[0] for c in r['after']['choices']['Smoother']][:3], ['Method', 'Local Width', 'Local Robustness'])
    check('(i) audit with the builder: every slot has a topic', r['audit'], [])
    r = await page.ev('''(async () => {
      await _gb.elements(['points', 'smoother', 'fit', 'ellipse', 'contour', 'line', 'bar', 'area', 'box', 'bean', 'histogram', 'heatmap', 'mosaic', 'caption', 'pie']);
      const all = SM.info.get('p:graphbuilder:props');
      const bad = [];
      for (const s of all.sections) { if (!s.text) bad.push(s.heading + ': what it draws'); for (const [n, d] of s.choices) if (!d || /undefined|null/.test(d) || d.length < 30) bad.push(s.heading + ' / ' + n); }
      SM.app.showTab(SM.app.tabOf(_rep.table));
      const away = SM.info.get('p:graphbuilder');
      SM.app.showTab(SM.app.tabOf(_rep));
      const dlg = await menuDialog(_rep, 'Graph Size…');
      const form = await infoClick(dlg.querySelector('.sm-dialog-head'));
      const audit = KvotInfo.audit().noTopic;
      KvotInfo.close(); await cancelDialog(dlg);
      await gbSet({ x: ['sex'], y: ['height (cm)'] }, ['box']);
      return { n: all.sections.map(s => s.heading), props: all.sections.reduce((a, s) => a + s.choices.length, 0), bad,
        away: away.sections.filter(s => s.heading.startsWith('Properties: ')).length, form: form && form.choices.Fields, audit, closed: !document.querySelector('.sm-dialog') };
    })()''')
    check('every element\'s properties explained (15 elements, 63 properties)', (len(r['n']), r['props'], r['bad']), (15, 63, []))
    check('with no builder on show, the (i) explains every element\'s properties', r['away'], 15)
    check('a form\'s (i) lists its fields: Graph Size', [f[0] for f in r['form'] or []], ['Width', 'Height'])
    check('... with the form open, every (i) has a topic', (r['audit'], r['closed']), ([], True))

    # ---- 10,000 rows stay quick
    r = await page.ev('''(async () => {
      const R = SM.util.rng('big graph'); const n = 10000; const x = [], y = [], g = [];
      for (let i = 0; i < n; i++) { const a = R.normal(); x.push(a); y.push(0.6 * a + Math.sin(2 * a) + R.normal(0, 0.7)); g.push('abcd'[i % 4]); }
      const t = new SM.Table({ name: 'Big', columns: [{ name: 'x', values: x }, { name: 'y', values: y }, { name: 'g', dataType: 'character', values: g }] });
      SM.app.addTable(t);
      const rep = SM.app.openReport(SM.platforms.get('graphbuilder'), { roles: {}, options: {} }, t);
      await new Promise(res => rep.on('done', res));
      const gb = rep.body.querySelector('.sm-gb')._gb;
      const T = {};
      let t0 = performance.now(); await gb.add('y', 'y'); await gb.add('x', 'x'); T.scatter = performance.now() - t0;
      t0 = performance.now(); await gb.add('overlay', 'g'); T.overlay = performance.now() - t0;
      t0 = performance.now(); await gb.elements(['points', 'contour']); T.contour = performance.now() - t0;
      t0 = performance.now(); t.select([...Array(4000).keys()]); await new Promise(r => setTimeout(r, 0)); T.select = performance.now() - t0;
      const pts = gb.plot().rows.filter(Boolean).reduce((a, r) => a + r.length, 0);
      SM.app.closeReport(rep); SM.app.closeTable(t);
      SM.app.showTab(SM.app.tabOf(_rep));
      return { T, pts };
    })()''', timeout=300)
    print('   10,000 rows (ms):', {k: round(v) for k, v in r['T'].items()})
    check('10,000 rows: every point drawn and linked', r['pts'], 10000)
    check('10,000 rows: points and smoother within 3 s, a selection within 1 s', r['T']['scatter'] < 3000 and r['T']['overlay'] < 3000 and r['T']['contour'] < 3000 and r['T']['select'] < 1000, True)

    # ---- the other platforms, on a seeded table
    check('the seeded table', await page.ev(MAKE), 240)
    # every launch dialog's (i): each role and option with what it is for
    r = await page.ev('''(async () => {
      const out = {};
      for (const id of ['scattermatrix', 'scatter3d', 'contour', 'surface', 'bubble', 'parallel', 'cellplot', 'ternary', 'treemap', 'functional', 'chart', 'overlay']) {
        SM.app.launch(id); await settle();
        const dlg = document.querySelector('.sm-launch-dialog');
        const info = await infoClick(dlg.querySelector('.sm-dialog-head'));
        const audit = KvotInfo.audit().noTopic;
        KvotInfo.close();
        // the roles the dialog shows (a Data Format hides some): one row per role, in order
        const rows = [...dlg.querySelectorAll('.sm-role')];
        [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'Cancel').click(); await settle();
        const L = SM.platforms.get(id).launch;
        out[id] = { roles: (info.choices.Roles || []).map(c => c[0]), wantRoles: L.roles.filter((x, i) => rows.length !== L.roles.length || !rows[i].hidden).map(x => x.label), options: (info.choices.Options || []).map(c => c[0]), wantOptions: (L.options || []).map(x => x.label),
          thin: [...(info.choices.Roles || []).filter(c => c[1].startsWith('(') || c[1].length < 40), ...(info.choices.Options || []).filter(c => c[1].length < 30)].map(c => c[0]),
          settings: (info.choices.Settings || []).map(c => c[0]), audit };
      }
      return { out, open: !!document.querySelector('.sm-dialog') };
    })()''')
    for pid, v in r['out'].items():
        check(f'{pid}: the launch dialog\'s (i) explains every role and option', (v['roles'], v['options'], v['thin'], v['audit']), (v['wantRoles'], v['wantOptions'], [], []))
    check('functional: the (i) explains the Data Format as well', r['out']['functional']['settings'], ['Data Format'])
    check('the launch dialogs are closed again', r['open'], False)
    async def run(pid, roles, options=None):
        res = await page.ev(open_report_js(pid, roles, options))
        check(f'{pid}: opens without errors', (res['errors'], res['plots'] >= 1), ([], True))
        return res
    await run('scattermatrix', {'y': ['x', 'y', 'z'], 'group': ['g']}, {'ellipses': True, 'fit': True, 'hist': True})
    r = await page.ev('''(async () => {
      const [rep, p] = await lastPlot(); const t = rep.table;
      const pts = p.traces.map((tr, i) => [tr, i]).filter(([tr, i]) => p.kinds[i] === 'points');
      t.select([1, 2, 3]); await settle();
      const sel = pts.map(([, i]) => (p.box.data[i].selectedpoints || []).length);
      t.select([]);
      return { cells: pts.length, sel, ellipses: p.traces.filter(tr => tr.hovertemplate && tr.hovertemplate.startsWith('r = ')).length, bars: p.traces.filter(tr => tr.type === 'bar').length };
    })()''')
    check('scatterplot matrix: three pairs, every cell linked', (r['cells'], r['sel']), (3, [3, 3, 3]))
    check('scatterplot matrix: an ellipse per pair and group, histograms on the diagonal', (r['ellipses'], r['bars']), (6, 6))
    await shot(page, 'g05-matrix.png')
    await run('scatter3d', {'y': ['x', 'y', 'z'], 'color': ['g']})
    r = await page.ev('''(async () => {
      const [rep, p] = await lastPlot(); const t = rep.table;
      p._click({ points: [{ curveNumber: 0, pointNumber: 7 }], event: {} });
      const sel = t.selectedRows(); await settle();
      const col = p.box.data && p.box.data[0] ? p.box.data[0].marker.color[7] : null;
      t.select([]);
      return { type: p.traces[0].type, n: p.rows[0].length, sel, want: p.rows[0][7], col, sels: rep.body.querySelectorAll('.sm-graph-pick select').length };
    })()''')
    check('scatter 3D: a point per row, axes to choose', (r['type'], r['n'], r['sels']), ('scatter3d', 240, 3))
    check('scatter 3D: a click selects the row, drawn in orange', (r['sel'], r['col']), ([r['want']], '#d9822b'))
    r = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const info = await infoClick(rep.body.querySelector('.sm-graph-pick')); KvotInfo.close();
      return info ? (info.choices['In the report'] || []).map(c => c[0]) : null; })()''')
    check('scatter 3D: an (i) by the axis menus explains them', r[:1] if r else r, ['X Axis, Y Axis, Z Axis'])
    await run('contour', {'y': ['z'], 'x': ['x', 'y']})
    r = await page.ev('''(async () => { const [rep, p] = await lastPlot(); const z = p.traces[0].z;
      return { rows: z.length, cols: z[0].length, holes: z.flat().some(v => v == null), linked: p.rows[1] ? p.rows[1].length : 0, code: rep.pythonScript().includes('griddata') }; })()''')
    check('contour plot: a 70 × 70 grid, missing outside the hull', (r['rows'], r['cols'], r['holes']), (70, 70, True))
    check('contour plot: the data points linked, the Python shown', (r['linked'], r['code']), (240, True))
    await run('surface', {'y': ['z'], 'x': ['x', 'y']})
    r = await page.ev('(() => { const p = SM.app.reports[SM.app.reports.length - 1].plots[0]; return p.traces.map(t => t.type); })()')
    check('surface plot: the surface and the linked points', r, ['surface', 'scatter3d'])
    await run('bubble', {'y': ['y'], 'x': ['x'], 'id': ['country'], 'time': ['year'], 'size': ['pop']})
    r = await page.ev('''(async () => {
      const [rep, p] = await lastPlot(); const t = rep.table; const B = p.box._bubble;
      const cn = t.col('country'), yr = t.col('year'), x = t.col('x');
      const k = B.labels.indexOf('Gamma');
      const want = meanOf(rowsWhere(t, r => cn.values[r] === 'Gamma' && yr.values[r] === 2000).map(r => x.values[r]));
      p.box.emit('plotly_click', { points: [{ curveNumber: 0, pointNumber: k }], event: {} });
      const n = t.selectedRows().length; await settle();
      const lw = p.box.data[0].marker.line.width[k]; t.select([]);
      return { frames: B.frames.length, bubbles: B.labels.length, got: B.frames[0].x[k], want, n, all: rowsWhere(t, r => cn.values[r] === 'Gamma').length, lw, slider: !!p.userLayout.sliders };
    })()''')
    if not isinstance(r, dict):
        print('   bubble:', r)
        r = {'bubbles': None, 'frames': None, 'slider': None, 'got': 0, 'want': 1, 'n': 0, 'all': 1, 'lw': 0}
    check('bubble plot: a bubble per ID, a frame per time, a slider', (r['bubbles'], r['frames'], r['slider']), (4, 6, True))
    check.near('bubble plot: a bubble at its rows\' mean', r['got'], r['want'], 1e-12)
    check('bubble plot: a click selects the ID\'s rows, ringed', (r['n'], r['lw']), (r['all'], 3))
    await shot(page, 'g06-bubble.png')
    await run('parallel', {'y': ['x', 'y', 'z', 'pop'], 'x': ['g']})
    r = await page.ev('''(async () => {
      const [rep, p] = await lastPlot(); const t = rep.table;
      t.select([3, 9]); await settle();
      const ov = p.box.data[p.traces.length - 1].x.length; t.select([]);
      return { lines: p.traces.filter((tr, i) => p.rows[i]).length, ov, top: Math.max(...p.traces[0].y.filter(v => v != null)) };
    })()''')
    check('parallel plot: a trace per group, linked; selected lines redrawn', (r['lines'], r['ov']), (2, 10))
    check.near('parallel plot: each axis on its range (0 to 1)', r['top'], 1.0, 1e-12)
    r = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const dlg = await menuDialog(rep, 'Reverse Axes…');
      const info = await infoClick(dlg.querySelector('.sm-dialog-head')); const audit = KvotInfo.audit().noTopic; KvotInfo.close(); await cancelDialog(dlg);
      return { fields: info ? (info.choices.Fields || []).map(c => c[0]) : null, boxes: dlg.querySelectorAll('input[type=checkbox]').length, audit }; })()''')
    check('parallel plot: the (i) of Reverse Axes explains its column boxes once', (r['fields'], r['boxes'], r['audit']), (['A column'], 4, []))
    await run('cellplot', {'y': ['x', 'z', 'g']})
    r = await page.ev('''(async () => {
      const [rep, p] = await lastPlot(); const t = rep.table;
      clickTrace(p, 1, [10, 0]); const sel = t.selectedRows(); await settle();
      const strip = p.box.data[3].z[10][0]; t.select([]);
      return { sel, strip, traces: p.traces.map(tr => tr.type) };
    })()''')
    check('cell plot: a click selects the row, the strip marks it', (r['sel'], r['strip']), ([10], 1))
    await run('ternary', {'y': ['A', 'B', 'C']})
    r = await page.ev('''(async () => { const [rep, p] = await lastPlot(); const tr = p.traces[0];
      const worst = Math.max(...tr.a.map((v, i) => Math.abs(v + tr.b[i] + tr.c[i] - 1)));
      p._click({ points: [{ curveNumber: 0, pointNumber: 2 }], event: {} }); const sel = rep.table.selectedRows(); rep.table.select([]);
      return { worst, sel, want: p.rows[0][2], type: tr.type }; })()''')
    check('ternary plot: shares sum to one', r['worst'] < 1e-12, True)
    check('ternary plot: a click selects the row', (r['type'], r['sel']), ('scatterternary', [r['want']]))
    await run('treemap', {'x': ['country', 'g'], 'size': ['pop']})
    r = await page.ev('''(async () => {
      const [rep, p] = await lastPlot(); const t = rep.table; const tr = p.traces[0];
      const cn = t.col('country'), g = t.col('g'), pop = t.col('pop');
      const k = tr.ids.indexOf('L0:Beta');
      const want = rowsWhere(t, r => cn.values[r] === 'Beta').reduce((a, r) => a + pop.values[r], 0);
      const kids = tr.ids.map((id, i) => [id, i]).filter(([id]) => id.startsWith('L0:Beta/')).reduce((a, [, i]) => a + tr.values[i], 0);
      p.box.emit('plotly_treemapclick', { points: [{ id: 'L0:Beta/L1:q' }], event: {} });
      const n = t.selectedRows().length; await settle();
      const lw = p.box.data[0].marker.line.width[tr.ids.indexOf('L0:Beta/L1:q')]; t.select([]);
      return { got: tr.values[k], want, kids, n, bq: rowsWhere(t, r => cn.values[r] === 'Beta' && g.values[r] === 'q').length, lw };
    })()''')
    check.near('treemap: a tile\'s area is the sum of Sizes', r['got'], r['want'], 1e-9)
    check.near('treemap: the tiles inside sum to their parent', r['kids'], r['want'], 1e-9)
    check('treemap: a click selects the tile\'s rows, outlined', (r['n'], r['lw']), (r['bq'], 3.5))
    await run('chart', {'y': ['pop'], 'x': ['country']}, {'stat': 'mean', 'kind': 'bar'})
    r = await page.ev('''(async () => {
      const [rep, p] = await lastPlot(); const t = rep.table;
      const cn = t.col('country'), pop = t.col('pop'); const lv = t.levels(cn);
      const want = lv.map(l => meanOf(rowsWhere(t, r => cn.values[r] === l).map(r => pop.values[r])));
      clickTrace(p, 0, 2); const n = t.selectedRows().length; t.select([]);
      return { got: p.traces[0].y, want, n, lv2: rowsWhere(t, r => cn.values[r] === lv[2]).length };
    })()''')
    check('chart: the mean of each category', all(abs(a - b) < 1e-9 for a, b in zip(r['got'], r['want'])) and len(r['got']) == 4, True)
    check('chart: a click on a bar selects its rows', r['n'], r['lv2'])
    await run('chart', {'y': ['pop'], 'x': ['country']}, {'stat': 'max', 'kind': 'pie'})
    r = await page.ev('''(async () => {
      const [rep, p] = await lastPlot(); const t = rep.table;
      const cn = t.col('country'), pop = t.col('pop'); const lv = t.levels(cn);
      return { got: p.traces[0].values, want: lv.map(l => Math.max(...rowsWhere(t, r => cn.values[r] === l).map(r => pop.values[r]))) };
    })()''')
    check('chart: a Pie Chart of the Max has slices of the maxima (not of the means)', all(abs(a - b) < 1e-9 for a, b in zip(r['got'], r['want'])) and len(r['got']) == 4, True)
    await run('overlay', {'y': ['z', 'pop'], 'x': ['x']})
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const c = rep.table.col('pop');
      rep.spec.options[c.id + '|right'] = true; rep.run(); await new Promise(res => rep.on('done', res));
      const p = rep.plots[0];
      return { right: p.userLayout.yaxis2 && p.userLayout.yaxis2.side, axes: p.traces.map(t => t.yaxis || 'y'), sorted: p.traces[0].x.every((v, i, a) => !i || a[i - 1] <= v) };
    })()''')
    check('overlay plot: a Y on the right axis, connected in X order', (r['right'], r['axes'], r['sorted']), ('right', ['y', 'y2'], True))
    await shot(page, 'g07-overlay.png')

    # ---- Functional Data Plot: statsmodels' functional graphics, curves linked to their rows
    r = await page.ev(FD_MAKE)
    check('the seeded table of curves: 40 rows, 16 points and two more columns', r, [40, 17])
    await page.ev(FD_HELPERS)
    r = await page.ev('''(async () => {
      SM.app.launch('functional'); await settle();
      const dlg = document.querySelector('.sm-launch-dialog');
      const vis = () => [...dlg.querySelectorAll('.sm-roles > .sm-role')].map(row => row.hidden ? '-' : row.querySelector('.sm-btn').textContent);
      const wide = vis();
      const radio = dlg.querySelector('input[data-fdformat="long"]'); radio.checked = true; radio.dispatchEvent(new Event('change', { bubbles: true })); await settle();
      const long = vis(), idReq = [...dlg.querySelectorAll('.sm-roles > .sm-role')][2].querySelector('.sm-btn').classList.contains('required');
      const head = dlg.querySelector('.sm-fd-launch h4').textContent;
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'Cancel').click(); await settle();
      return { wide, long, idReq, head, closed: !document.querySelector('.sm-launch-dialog') };
    })()''')
    check('Functional Data Plot: Rows as Functions takes Y, Output (columns), an ID and By', r['wide'], ['Y, Output', '-', 'ID, Function', '-', 'By'])
    check('Stacked takes Y, Output (one), ID, Function (required) and X, Input', (r['long'], r['idReq']), (['-', 'Y, Output', 'ID, Function', 'X, Input', 'By'], True))
    check('the launch dialog asks for the data format first', (r['head'].startswith('Data Format'), r['closed']), (True, True))
    res = await run('functional', {'y': [f't{j}' for j in range(16)], 'id': ['name']})
    check('functional: the functional boxplot and the depths by default', res['outlines'], ['Functional Data Plot', 'Functional Boxplot', 'Curve Depths'])
    r = await page.ev('''(async () => {
      const [rep, p] = await lastPlot(); const t = rep.table; const ctx = null;
      const S = fdState(rep);
      const cols = [...Array(16).keys()].map(j => t.col('t' + j));
      const Y = [...Array(t.nrows).keys()].map(r => cols.map(c => c.values[r]));
      const ref = mbdRef(Y);
      const got = S.fb.depth;
      const worst = Math.max(...ref.map((v, i) => Math.abs(v - got[i])));
      const med = ref.indexOf(Math.max(...ref));
      const order = ref.map((v, i) => i).sort((a, b) => ref[b] - ref[a]);
      const central = order.slice(0, 20);
      const lower = cols.map((_, j) => Math.min(...central.map(i => Y[i][j]))), upper = cols.map((_, j) => Math.max(...central.map(i => Y[i][j])));
      const med0 = cols.map((_, j) => { const v = central.map(i => Y[i][j]).sort((a, b) => a - b); return (v[9] + v[10]) / 2; });
      const lo = med0.map((m, j) => m - 1.5 * (m - lower[j])), hi = med0.map((m, j) => m + 1.5 * (upper[j] - m));
      const out = Y.map(y => y.some((v, j) => v < lo[j] || v > hi[j]));
      const bandY = p.traces[1].y;
      const tableRows = [...rep.body.querySelectorAll('table.sm-rt')].map(tb => tb.querySelectorAll('tbody tr').length);
      return { worst, med, gotMed: S.fb.median, out: out.map((o, i) => o ? i : -1).filter(i => i >= 0), gotOut: S.fb.outlier.map((o, i) => o ? i : -1).filter(i => i >= 0),
        central: Math.max(...upper.map((u, j) => Math.abs(u - bandY[j]))), names: p.traces.filter(tr => tr.showlegend !== false && tr.name).map(tr => tr.name).slice(0, 3), tableRows, x: S.fb.x.slice(0, 3) };
    })()''')
    check.near('functional: the modified band depths are statsmodels\' (against the definition, in the page)', r['worst'], 0.0, 1e-12)
    check('functional: the median is the deepest curve', r['gotMed'], r['med'])
    check('functional: fboxplot\'s outliers (the central region stretched 1.5 times about its median)', r['gotOut'], r['out'])
    check.near('functional: the 50% central region is the envelope of the 20 deepest', r['central'], 0.0, 1e-12)
    check('functional: X from the numbers in the column names', r['x'], [0, 1, 2])
    check('functional: the legend names the regions, the median and the outliers', r['names'][:2], ['Non-outlying envelope', '50% central region'])
    check('functional: the outlying curves listed, and every curve\'s depth', r['tableRows'], [len(r['gotOut']), 40])
    # linking: a curve is its row
    r = await page.ev('''(async () => {
      const [rep, p] = await lastPlot(); const t = rep.table; const S = fdState(rep); const C = p.box._curves;
      const mi = p.traces.findIndex(tr => tr.name && tr.name.startsWith('Median'));
      clickTrace(p, mi, 7); const a = t.selectedRows();
      t.select([3, 7]); await settle();
      const ov = p.box.data[C.overlay].x.length, per = C.F.dx.length + 1;
      t.select([]); await settle();
      const cleared = p.box.data[C.overlay].x.length;
      const oc = S.fb.outlier.indexOf(true);
      const oi = p.traces.findIndex(tr => tr.name === C.F.labels[oc]);
      t.setState([oc], 'hidden', true); await settle();
      const hid = p.box.data[oi].y.every(v => v == null);
      t.setState([oc], 'hidden', false); await settle();
      const back = p.box.data[oi].y.some(v => v != null);
      return { a, want: [S.fb.median], ov, per, cleared, hid, back };
    })()''')
    check('functional: a click on a curve selects its row', r['a'], r['want'])
    check('functional: rows selected in the table draw their curves over the others', (r['ov'], r['cleared']), (2 * r['per'], 0))
    check('functional: a hidden row\'s curve is not drawn, and comes back', (r['hid'], r['back']), (True, True))
    # a real mouse click on a curve, where Plotly draws it
    xy = await page.ev('''(async () => {
      const [rep, p] = await lastPlot(); const S = fdState(rep); const gd = p.box;
      gd.scrollIntoView({ block: 'center' }); await settle();
      const oc = S.fb.outlier.indexOf(true);
      const L = gd._fullLayout, j = 9, r = gd.getBoundingClientRect();
      return [r.left + L.xaxis._offset + L.xaxis.l2p(S.fb.x[j]), r.top + L.yaxis._offset + L.yaxis.l2p(S.fb.curves[oc][j]), oc];
    })()''')
    await page.click(xy[0], xy[1])
    await asyncio.sleep(0.4)
    check('functional: a mouse click on an outlying curve selects its row', await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()'), [xy[2]])
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table; const S = fdState(rep);
      rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu').click(); await settle();
      const items = [...document.querySelectorAll('.sm-menu button')].map(b => b.textContent.replace(/^[✓ ]+/, ''));
      [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent.includes('Select Outliers')).click(); await settle();
      const sel = t.selectedRows(), want = S.fb.outlier.map((o, i) => o ? i : -1).filter(i => i >= 0);
      t.select([]);
      rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu').click(); await settle();
      [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent.includes('Save Columns')).click(); await settle();
      const menus = document.querySelectorAll('.sm-menu');
      [...menus[menus.length - 1].querySelectorAll('button')].find(b => b.textContent.trim() === 'Depth').click(); await settle();
      const c = t.col('Depth (MBD)');
      const saved = c ? Math.max(...S.fb.depth.map((d, i) => Math.abs(c.values[i] - d))) : null;
      if (c) t.removeColumn(c.id);
      return { items, sel, want, saved };
    })()''')
    check('functional: the red triangle\'s views and options', [i for i in r['items'] if i in ('Functional Boxplot', 'HDR Boxplot', 'Rainbow Plot', 'Curve Depths', 'Depth', 'Outlier Rule', 'Outlier Factor…', 'X Values', 'Select Outliers', 'Save Columns')], ['Functional Boxplot', 'HDR Boxplot', 'Rainbow Plot', 'Curve Depths', 'Depth', 'Outlier Rule', 'Outlier Factor…', 'X Values', 'Select Outliers', 'Save Columns'])
    check('functional: Select Outliers selects the outlying curves\' rows', r['sel'], r['want'])
    check.near('functional: Save Columns > Depth writes each curve\'s depth to its row', r['saved'], 0.0, 1e-15)
    # the HDR boxplot, the score plot and the rainbow plot, turned on in the red triangle
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const done = new Promise(res => rep.on('done', res));
      rep.spec.options.fdHdr = true; rep.spec.options.fdRainbow = true; rep.run('redo'); await done; await settle();
      for (const p of rep.plots) await drawn(p);
      const S = fdState(rep); const H = S.hd;
      const heads = [...rep.body.querySelectorAll('.sm-ob-head h3, .sm-fd-sub')].map(h => h.textContent);
      const up50 = H.hdr50[0], lo50 = H.hdr50[1], up90 = H.hdr90[0], lo90 = H.hdr90[1];
      const nested = up50.every((u, j) => u <= up90[j] + 1e-9 && lo50[j] >= lo90[j] - 1e-9);
      const modal = H.modal.every((v, j) => v <= up50[j] + 1e-9 && v >= lo50[j] - 1e-9);
      const dens = H.density.slice().sort((a, b) => a - b);
      const outs = H.outlier.map((o, i) => o ? i : -1).filter(i => i >= 0);
      const lowest = H.density.map((d, i) => [d, i]).sort((a, b) => a[0] - b[0]).slice(0, outs.length).map(q => q[1]).sort((a, b) => a - b);
      const sp = rep.plots.find(p => p.opts.title === 'HDR score plot');
      const si = sp.traces.findIndex((tr, i) => Array.isArray(sp.rows[i]));
      t.select([outs[0]]); await settle();
      const hl = sp.box.data[si].selectedpoints; t.select([]);
      const rb = rep.plots.find(p => p.opts.title === 'Rainbow plot');
      const medC = rb.box._curves.specs.find(s => s.vtx[0] === S.fb.median);
      return { heads, nested, modal, outs, lowest, hl, want: [outs[0]], medColor: medC ? rb.traces[medC.trace].line.color : null, notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(n => n.textContent).join(' ') };
    })()''')
    check('functional: HDR Boxplot, its score plot and the Rainbow Plot', [h for h in r['heads'] if h in ('Functional Boxplot', 'HDR Boxplot', 'Score Plot', 'Rainbow Plot', 'Curve Depths')], ['Functional Boxplot', 'HDR Boxplot', 'Score Plot', 'Rainbow Plot', 'Curve Depths'])
    check('HDR: the 50% band inside the 90% band, the modal curve inside the 50% band', (r['nested'], r['modal']), (True, True))
    check('HDR: the outliers are the curves of lowest density, 5% of them', (r['outs'], len(r['outs'])), (r['lowest'], 2))
    check('HDR: the score plot\'s points are linked to the rows', r['hl'], r['want'])
    check('rainbow: the median in the deepest colour (dark on a light page)', r['medColor'], 'rgb(68, 1, 84)')
    check('the report says how statsmodels\' HDR boxplot is computed, and that JMP has no functional boxplot', ('KDEMultivariate' in r['notes'] and 'differential evolution' in r['notes'], 'JMP (standard) has no functional boxplots' in r['notes']), (True, True))
    await shot(page, 'g07b-functional.png')
    # stacked: an ID, X and Y; the same depths, a curve is all of an ID's rows
    r = await page.ev(FD_LONG)
    res = await run('functional', {'yl': ['y'], 'id': ['id'], 'x': ['x']}, {'format': 'long'})
    r = await page.ev('''(async () => {
      const [rep, p] = await lastPlot(); const t = rep.table; const S = fdState(rep);
      const wide = SM.app.reports.find(q => q.table && q.table.name === 'FD test' && q.platform.id === 'functional');
      const W = fdState(wide);
      const byName = new Map(W.F.labels.map((l, i) => [l, W.fb.depth[i]]));
      const worst = Math.max(...S.F.labels.map((l, i) => Math.abs(byName.get(l) - S.fb.depth[i])));
      const mi = p.traces.findIndex(tr => tr.name && tr.name.startsWith('Median'));
      clickTrace(p, mi, 3); const n = t.selectedRows().length; t.select([]);
      return { worst, n, curves: S.F.n, interp: S.fb.interp, note: rep.body.querySelector('.sm-ob-note').textContent };
    })()''')
    check.near('stacked: the same depths as the rows as functions', r['worst'], 0.0, 1e-12)
    check('stacked: a click on a curve selects all its rows', (r['curves'], r['n'], r['interp']), (40, 16, None))
    await page.ev(FD_IRREGULAR)
    res = await run('functional', {'yl': ['y'], 'id': ['id'], 'x': ['x']}, {'format': 'long', 'fdHdr': True})
    r = await page.ev('(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; return { note: rep.body.querySelector(".sm-ob-note").textContent, S: fdState(rep).fb.interp }; })()')
    check('stacked at different X: interpolated, and the report says how', ('interpolated linearly (numpy.interp)' in r['note'], r['S']['points'] if r['S'] else None), (True, 20))
    # By: a report for each group, the depths within it
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'FD test')))")
    res = await run('functional', {'y': [f't{j}' for j in range(16)], 'by': ['grp']})
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const tops = [...rep.body.querySelectorAll('.sm-ob.level-0 > .sm-ob-head h2')].map(h => h.textContent);
      const tb = [...rep.body.querySelectorAll('table.sm-rt')].filter(x => x.dataset.rtKey === 'fd:depths');
      const cols = [...Array(16).keys()].map(j => t.col('t' + j));
      const A = rowsWhere(t, r => t.col('grp').values[r] === 'A');
      const ref = mbdRef(A.map(r => cols.map(c => c.values[r])));
      const got = tb[0]._rt.rows.map(q => q.depth);
      return { tops, n: tb.length, worst: Math.max(...ref.map((v, i) => Math.abs(v - got[i]))), code: rep.pythonScript().includes('for key, g in df.dropna(subset=["grp"]).groupby(["grp"], observed=True)') };
    })()''')
    check('By: a Functional Data Plot for each group', (r['tops'], r['n']), (['Functional Data Plot grp=A', 'Functional Data Plot grp=B'], 2))
    check.near('By: the depths within the group', r['worst'], 0.0, 1e-12)
    check('By: the Python loops over the groups', r['code'], True)
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('functional: every (i) of its outlines has a topic, every Help link a target', (audit.get('noTopic'), audit.get('brokenMore')), ([], []))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(q => q.table && q.table.name === 'FD test' && q.platform.id === 'functional' && q.spec.options.fdHdr);
      const t = rep.table;
      const proj = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      SM.app.loadProject(JSON.parse(JSON.stringify(proj)));
      const again = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => again.on('done', res));
      const heads = [...again.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent);
      const S = fdState(again), W = fdState(rep);
      const out = { heads, same: S && W ? Math.max(...S.fb.depth.map((d, i) => Math.abs(d - W.fb.depth[i]))) : null, other: again.table !== t };
      SM.app.closeReport(again); SM.app.closeTable(again.table);
      return out;
    })()''')
    check('a saved project reopens the Functional Data Plot with its views', ([h for h in r['heads'] if h in ('HDR Boxplot', 'Rainbow Plot')], r['other']), (['HDR Boxplot', 'Rainbow Plot'], True))
    check.near('and the same depths', r['same'], 0.0, 1e-15)
    # the example
    r = await page.ev('''(async () => {
      const ex = SM.io.EXAMPLES.curves;
      SM.app.openExample('curves'); await settle();
      const t = SM.app.current;
      const P = SM.platforms.get('functional');
      const rep = SM.app.openReport(P, { roles: { y: [...Array(24).keys()].map(h => t.col(String(h)).id) }, options: { fdRule: 'sungenton', fdHdr: true } }, t);
      await new Promise(res => rep.on('done', res));
      const S = fdState(rep);
      const lab = (arr) => arr.map((o, i) => o ? S.F.labels[i] : null).filter(Boolean);
      return { label: ex && ex.label, name: t.name, n: t.nrows, cols: t.columns.length, sg: lab(S.fb.outlier), hdr: lab(S.hd.outlier), errors: [...rep.body.querySelectorAll('.sm-ob-error')].length };
    })()''')
    check('the example: temperature curves, 60 days by 24 hours', (r['name'], r['n'], r['cols'], r['errors']), ('Temperature curves', 60, 26, 0))
    check('the example: Sun and Genton\'s fences find the heat, cold, front and night days', r['sg'], ['Day 07', 'Day 14', 'Day 24', 'Day 31'])
    check('the example: the HDR boxplot finds a shape outlier the others miss (Day 31) and two magnitude ones', r['hdr'], ['Day 07', 'Day 31', 'Day 42'])
    await page.ev("SM.app.showTab(SM.app.tabOf(_rep))")

    # ---- dark theme and phone width, with Graph Builder
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev('SM.app.showTab(SM.app.tabOf(_rep))')
    await asyncio.sleep(1.2)
    r = await page.ev('''(async () => { await _gb.idle(); await gbSet({ x: ['height (cm)'], y: ['weight (kg)'], overlay: ['sex'] }, ['points', 'fit']);
      const bg = getComputedStyle(_rep.body.querySelector('.sm-gb-zone')).backgroundColor; return { bg, font: _gb.plot().box.layout && _gb.plot().box.layout.font.color }; })()''')
    check('dark theme: the graph takes the theme\'s text colour', r['font'] not in (None, '#352921'), True)
    await shot(page, 'g08-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    r = await page.ev('''(async () => { await rerun(() => _rep.run());
      const w = document.documentElement.scrollWidth <= innerWidth + 1;
      const cols = getComputedStyle(_rep.body.querySelector('.sm-gb-work')).gridTemplateColumns.split(' ').length;
      return { w, cols, plotW: _gb.plot() ? _gb.plot().width : 0 }; })()''')
    check('phone width: no horizontal page scroll', r['w'], True)
    check('phone width: the builder stacks its parts in one column', r['cols'], 1)
    await shot(page, 'g09-phone.png')
    # the Functional Data Plot in the dark theme, at phone width
    r = await page.ev('''(async () => {
      const t = SM.app.tables.find(x => x.name === 'FD test');
      const rep = SM.app.openReport(SM.platforms.get('functional'), { roles: { y: [...Array(16).keys()].map(j => t.col('t' + j).id) }, options: { fdRainbow: true, fdHdr: true } }, t);
      await new Promise(res => rep.on('done', res));
      const S = fdState(rep);
      const rb = rep.plots.find(p => p.opts.title === 'Rainbow plot');
      rb.box.scrollIntoView({ block: 'center' }); await drawn(rb); await settle();
      const medC = rb.box._curves.specs.find(s => s.vtx[0] === S.fb.median);
      return { color: rb.traces[medC.trace].line.color, fits: document.documentElement.scrollWidth <= innerWidth + 1, widths: rep.plots.map(p => p.width), errors: rep.body.querySelectorAll('.sm-ob-error').length };
    })()''')
    check('dark theme: the rainbow plot\'s deepest curves are the brightest', r['color'], 'rgb(253, 231, 37)')
    check('phone width: the Functional Data Plot fits, no horizontal page scroll', (r['fits'], max(r['widths']) <= 400, r['errors']), (True, True, 0))
    await shot(page, 'g10-functional-phone.png')
    check('no script errors', page.errors, [])
    check('no console errors from the Graph code', [m for m in page.console if 'graph' in m.lower()], [])
    await page.close()


def SM_fmt4(v):
    """The page's fmt(v, {sig: 4}) for a positive number of moderate size."""
    s = f'{v:.4g}'
    return s


asyncio.run(main())
sys.exit(check.done())
