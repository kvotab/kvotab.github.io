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
plot, stacked and interpolated curves, By, the example). Then the Python
under every graph (graph.code): each block, run in the page's own Python,
draws the graph above it (Graph Builder's elements and zones, and every
other Graph platform), checked against the Plotly graph. The dark theme and
phone width at the end.

Start a server on the repository root and headless Chrome (the recipe is in
README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-graph.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime

import websockets

import cdp
from cdp import BASE, Checks, open_report_js, wait_engine
from test_charts import GRAPHS_JS, more_from_outputs, page_probe_more, strip_show

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


# ---- the Python under each graph ----------------------------------------------------------------------------
# Every graph of the Graph menu has a code block right under it (graph.code) that draws the
# same graph with matplotlib from the table's CSV export. The checks below run each block in
# the page's own Python (the notebook's runner) and compare the figure it draws with the
# Plotly graph above it: its points, curves, bands, bars, boxes, violins, cells, slices and
# tiles, their colours, the axis titles, the levels' order, the legend.

# The Graph Builder report's graph as the page drew it: its traces (the overlays that show
# the selected share marked), annotations and shapes, axis titles and ticks, size, the plan,
# and the code block right under it.
GB_JS = r'''
window.__gbq = async (rep) => {
  rep = rep || window._rep;
  const gb = rep.body.querySelector('.sm-gb')._gb;
  await gb.idle(); await new Promise((r) => setTimeout(r, 150));
  const p = gb.plot(); if (!p) return null;
  if (!p.drawn) { p.box.scrollIntoView({ block: 'center' }); await p.draw(); }
  const fig = gb.figure();
  const next = p.box.nextElementSibling;
  const code = next && next.matches('details.sm-code') ? next.querySelector('code').textContent : null;
  const skip = new Set((fig.links || []).filter((l) => l.overlay != null).map((l) => l.overlay));
  const arr = (v) => (v == null ? null : Array.isArray(v) ? v : [v]);
  const traces = p.traces.map((t, i) => ({ i, type: t.type || 'scatter', mode: t.mode || null, x: t.x ?? null, y: t.y ?? null, z: t.z ?? null, base: t.base ?? null, width: t.width ?? null,
    orientation: t.orientation || null, q1: t.q1 || null, median: t.median || null, q3: t.q3 || null, lowerfence: t.lowerfence || null, upperfence: t.upperfence || null,
    fill: t.fill || null, stackgroup: t.stackgroup || null, xaxis: t.xaxis || 'x', yaxis: t.yaxis || 'y', rows: p.rows[i] || null, values: t.values || null, labels: t.labels || null,
    contours: t.contours || null, ex: t.error_x ? { a: t.error_x.array, m: t.error_x.arrayminus } : null, ey: t.error_y ? { a: t.error_y.array, m: t.error_y.arrayminus } : null,
    color: t.line ? t.line.color || null : null, lw: t.line ? t.line.width ?? null : null, dash: t.line ? t.line.dash || null : null, shape: t.line ? t.line.shape || null : null,
    mcolor: t.marker ? arr(t.marker.color) : null, msize: t.marker ? arr(t.marker.size) : null, symbol: t.marker ? t.marker.symbol || null : null, fillcolor: t.fillcolor || null,
    name: t.name ?? null, showlegend: t.showlegend ?? null, legendgroup: t.legendgroup || null, text: t.text ?? null, hole: t.hole ?? null, overlay: skip.has(i),
    textinfo: t.textinfo || null, el: fig.traceEl[i] || null }));
  const L = p.userLayout || {};
  const axes = {};
  for (const k of Object.keys(L)) if (/^[xy]axis\d*$/.test(k)) axes[k] = { title: L[k].title ? L[k].title.text : null, ticktext: L[k].ticktext || null, tickvals: L[k].tickvals || null, range: L[k].range || null, type: L[k].type || null };
  return { traces, annotations: (L.annotations || []).map((a, j) => ({ text: a.text, x: a.x, y: a.y, xref: a.xref, yref: a.yref, el: fig.noteEl[j] || null })), shapes: (L.shapes || []).map((s) => ({ x0: s.x0, x1: s.x1, y0: s.y0, y1: s.y1, xref: s.xref, yref: s.yref, dash: s.line && s.line.dash })),
    axes, title: L.title ? L.title.text : null, legend: !!L.showlegend, plan: fig.plan, code, w: p.ownWidth, h: p.height, notes: fig.notes.slice(), script: rep.pythonScript() };
};
'''

# A seeded table for the code of Graph Builder's graphs: continuous X and Y with a missing
# value each, a grouping column in its own level order, a two-level one with a missing value,
# an ordinal, whole and fractional counts, a date, a third continuous column.
CODE_TABLE = r'''(() => {
  const R = SM.util.rng('graph code'); const n = 150;
  const c = { x: [], y: [], g: [], h: [], a: [], f: [], wf: [], d: [], z: [] };
  for (let i = 0; i < n; i++) {
    const a = 1 + (i % 4), h = R.u() < 0.5 ? 'p' : 'q';
    const x = +(40 + R.u() * 60).toFixed(1);
    const y = +(10 + 0.5 * x + (h === 'q' ? 6 : 0) + 2 * a + R.normal(0, 6)).toFixed(2);
    c.x.push(i === 7 ? NaN : x); c.y.push(i === 11 ? NaN : y); c.g.push(['lo', 'mid', 'hi'][(i * 7) % 3]); c.h.push(i === 13 ? null : h); c.a.push(a);
    c.f.push(1 + (i % 3)); c.wf.push(+(0.5 + 1.5 * R.u()).toFixed(2)); c.d.push(Date.UTC(2020, 0, 6) + i * 7 * 86400000); c.z.push(+(100 * R.u()).toFixed(2));
  }
  const t = new SM.Table({ name: 'Graph code', source: 'simulated', columns: [{ name: 'x', values: c.x }, { name: 'y', values: c.y },
    { name: 'g', dataType: 'character', values: c.g, valueOrder: ['lo', 'mid', 'hi'] }, { name: 'h', dataType: 'character', values: c.h },
    { name: 'a', values: c.a, modelingType: 'ordinal' }, { name: 'f', values: c.f }, { name: 'wf', values: c.wf }, { name: 'd', values: c.d, format: { kind: 'date' } }, { name: 'z', values: c.z }] });
  SM.app.addTable(t);
  const rep = SM.app.openReport(SM.platforms.get('graphbuilder'), { roles: {}, options: {} }, t);
  window._crep = rep;
  return new Promise((res) => rep.on('done', () => res(t.nrows)));
})()'''

GB_CODE_CASES = [   # [what, zones, elements, properties, (the builder's state)]: every element and zone, dates, a log axis, the legend at the bottom
    ["points and smoother", {"x": ["x"], "y": ["y"]}, ["points", "smoother"], {}],
    ["overlay, lowess, the band", {"x": ["x"], "y": ["y"], "overlay": ["h"]}, ["points", "smoother"], {"smoother": {"method": "lowess", "width": 0.5, "robust": 2}}],
    ["spline confidence", {"x": ["x"], "y": ["y"]}, ["points", "smoother"], {"smoother": {"conf": True, "lambda": 0.3}}],
    ["fit quadratic with texts, Group X", {"x": ["x"], "y": ["y"], "groupX": ["h"]}, ["points", "fit"], {"fit": {"degree": 2, "confPred": True, "equation": True, "r2": True, "rmse": True, "ftest": True}}],
    ["robust fit, wrap", {"x": ["x"], "y": ["y"], "wrap": ["g"]}, ["points", "fit"], {"fit": {"fitType": "robust", "equation": True, "rmse": True}}],
    ["ellipse, Group Y, overlay", {"x": ["x"], "y": ["y"], "groupY": ["h"], "overlay": ["g"]}, ["ellipse"], {"ellipse": {"coverage": 0.9, "shaded": True, "correlation": True, "meanPoint": True}}],
    ["contour", {"x": ["x"], "y": ["y"]}, ["contour"], {"contour": {"levels": 5}}],
    ["contour overlay lines", {"x": ["x"], "y": ["y"], "overlay": ["h"]}, ["contour"], {"contour": {"fill": False, "bw": 1.5}}],
    ["violins", {"x": ["g"], "y": ["y"], "overlay": ["h"]}, ["contour"], {}],
    ["jitter uniform", {"x": ["g"], "y": ["y"]}, ["points"], {}],
    ["jitter normal", {"x": ["g"], "y": ["y"], "overlay": ["h"]}, ["points"], {"points": {"jitter": "normal", "jitterLimit": 1.5}}],
    ["jitter grid", {"x": ["g"], "y": ["y"]}, ["points"], {"points": {"jitter": "grid"}}],
    ["jitter packed", {"x": ["g"], "y": ["y"], "overlay": ["h"]}, ["points"], {"points": {"jitter": "packed"}}],
    ["points summary", {"x": ["g"], "y": ["y"], "overlay": ["h"]}, ["points"], {"points": {"summary": "mean", "interval": "ci"}}],
    ["line se", {"x": ["a"], "y": ["y"], "overlay": ["h"]}, ["line"], {"line": {"interval": "se"}}],
    ["line band curve", {"x": ["a"], "y": ["y"]}, ["line"], {"line": {"connection": "curve", "summary": "median", "interval": "iqr", "style": "band"}}],
    ["line step", {"x": ["a"], "y": ["y"]}, ["line"], {"line": {"connection": "step", "summary": "max", "interval": "range"}}],
    ["line row order", {"x": ["x"], "y": ["y"]}, ["line"], {"line": {"ordering": "row"}}],
    ["bar ci labels", {"x": ["g"], "y": ["y"], "overlay": ["h"]}, ["bar"], {"bar": {"interval": "ci", "label": "value"}}],
    ["bar stacked percent", {"x": ["g"], "y": ["y"], "overlay": ["h"]}, ["bar"], {"bar": {"barStyle": "stacked", "summary": "sum", "label": "percent"}}],
    ["bar counts", {"x": ["g"]}, ["bar"], {}],
    ["bar horizontal needle", {"x": ["y"], "y": ["g"]}, ["bar"], {"bar": {"barStyle": "needle", "summary": "median", "interval": "iqr"}}],
    ["bar pct", {"x": ["a"], "y": ["y"], "overlay": ["g"]}, ["bar"], {"bar": {"summary": "pct"}}],
    ["area", {"x": ["a"], "y": ["y"], "overlay": ["h"]}, ["area"], {}],
    ["area stacked", {"x": ["a"], "y": ["y"], "overlay": ["g"]}, ["area"], {"area": {"areaStyle": "stacked", "summary": "sum"}}],
    ["box", {"x": ["g"], "y": ["y"], "overlay": ["h"]}, ["box"], {"box": {"diamond": True}}],
    ["box quantile solid", {"x": ["y"], "y": ["g"]}, ["box"], {"box": {"boxType": "quantile", "boxStyle": "solid", "width": 0.8}}],
    ["bean", {"x": ["g"], "y": ["y"]}, ["bean"], {}],
    ["bean jitter overlay", {"x": ["g"], "y": ["y"], "overlay": ["h"]}, ["bean"], {"bean": {"beans": "jitter", "cutoff": True, "bw": 1.3}}],
    ["bean split", {"x": ["g"], "y": ["y"], "overlay": ["h"]}, ["bean"], {"bean": {"split": True}}],
    ["histogram", {"x": ["x"]}, ["histogram"], {"histogram": {"counts": True}}],
    ["histogram kernel percent", {"y": ["x"], "overlay": ["h"]}, ["histogram"], {"histogram": {"histStyle": "kernel", "scale": "percent"}}],
    ["histogram band", {"x": ["x"], "y": ["g"]}, ["histogram"], {"histogram": {"binWidth": 10}}],
    ["heatmap", {"x": ["x"], "y": ["g"]}, ["heatmap"], {"heatmap": {"label": "value"}}],
    ["heatmap mean of color", {"x": ["x"], "y": ["y"], "color": ["z"], "groupX": ["h"]}, ["heatmap"], {"heatmap": {"bins": 8, "label": "value"}}],
    ["mosaic", {"x": ["g"], "y": ["h"]}, ["mosaic"], {"mosaic": {"cellLabel": "count", "chisq": True}}],
    ["caption", {"x": ["g"], "y": ["y"], "overlay": ["h"]}, ["points", "caption"], {"caption": {"stats": ["mean", "n", "range"]}}],
    ["caption per factor", {"x": ["g"], "y": ["y"]}, ["points", "caption"], {"caption": {"stats": ["median", "sd"], "location": "factor"}}],
    ["pie ring", {"x": ["g"], "y": ["z"]}, ["pie"], {"pie": {"pieStyle": "ring"}}],
    ["pie counts Group X", {"x": ["g"], "groupX": ["h"]}, ["pie"], {"pie": {"label": "value"}}],
    ["freq whole", {"x": ["g"], "y": ["y"], "freq": ["f"]}, ["bar", "points"], {"bar": {"interval": "sd"}}],
    ["freq fractional", {"x": ["g"], "y": ["y"], "freq": ["wf"]}, ["bar", "box"], {"bar": {"summary": "median", "interval": "iqr"}}],
    ["freq models", {"x": ["x"], "y": ["y"], "freq": ["f"]}, ["points", "smoother", "fit", "ellipse", "contour"], {"smoother": {"conf": True}}],
    ["color continuous, size", {"x": ["x"], "y": ["y"], "color": ["z"], "size": ["z"]}, ["points"], {}],
    ["color categorical with overlay", {"x": ["x"], "y": ["y"], "color": ["g"], "overlay": ["h"]}, ["points"], {}],
    ["Y merged", {"x": ["x"], "y": ["y", "z"]}, ["points", "smoother"], {}, {"yMode": "merge"}],
    ["Y side by side", {"x": ["g"], "y": ["y", "z"]}, ["points", "box"], {}],
    ["X side by side, Group X", {"x": ["x", "z"], "y": ["y"], "groupX": ["h"]}, ["points"], {}],
    ["Group X by Group Y", {"x": ["g"], "y": ["y"], "groupX": ["h"], "groupY": ["a"]}, ["box"], {}],
    ["binned overlay", {"x": ["x"], "y": ["y"], "overlay": ["z"]}, ["points", "smoother"], {}],
    ["bar over a continuous factor", {"x": ["a"], "y": ["y"]}, ["bar"], {}],
    ["date on X, smoother", {"x": ["d"], "y": ["y"]}, ["points", "smoother", "fit"], {}],
    ["date on Y", {"x": ["x"], "y": ["d"]}, ["points", "smoother"], {}],
    ["log X", {"x": ["z"], "y": ["y"]}, ["points"], {}, {"log": {"x": True}}],
    ["legend at the bottom", {"x": ["x"], "y": ["y"], "overlay": ["g"]}, ["points"], {}, {"legendPos": "bottom"}],
    ["wrap binned", {"x": ["x"], "y": ["y"], "wrap": ["z"]}, ["points", "fit"], {}],
    ["color categorical alone", {"x": ["x"], "y": ["y"], "color": ["h"]}, ["points", "smoother"], {}],
    ["histogram of dates", {"x": ["d"]}, ["histogram"], {}],
    ["histogram with Freq", {"x": ["x"], "freq": ["f"]}, ["histogram"], {}],
    ["size alone", {"x": ["x"], "y": ["y"], "size": ["wf"]}, ["points"], {}],
    ["rows excluded", {"x": ["x"], "y": ["y"], "overlay": ["h"]}, ["points", "smoother", "fit"], {}, {"excluded": [0, 3, 5, 8, 21]}],
]

DAY = 86400000.0


def unesc(s):
    return None if s is None else str(s).replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('<b>', '').replace('</b>', '')


def panel_of(t, axis='x'):
    s = (t.get(f'{axis}axis') or axis)[1:]
    return int(s) - 1 if s else 0



def md(a, b):
    """The largest difference of two lists of numbers (None as a gap), inf when they differ in length or gaps."""
    a, b = list(a or []), list(b or [])
    if len(a) != len(b):
        return float('inf')
    d = 0.0
    for x, y in zip(a, b):
        if x is None or y is None:
            if (x is None) != (y is None):
                return float('inf')
            continue
        d = max(d, abs(float(x) - float(y)))
    return d


def rel(a, b):
    """md relative to the size of the numbers."""
    scale = max([abs(float(v)) for v in list(a or []) + list(b or []) if v is not None] + [1.0])
    return md(a, b) / scale


def hexrgb(c):
    """A colour as #rrggbb from #rrggbb[aa] or rgb(r, g, b) or rgba(...)."""
    if c is None:
        return None
    c = str(c).strip()
    if c.startswith('#'):
        return c[:7].lower()
    if c.startswith('rgb'):
        v = [float(q) for q in c[c.index('(') + 1:c.index(')')].split(',')[:3]]
        return '#%02x%02x%02x' % tuple(int(round(q)) for q in v)
    return c


def close_rgb(a, b, tol=2):
    a, b = hexrgb(a), hexrgb(b)
    if not a or not b or not a.startswith('#') or not b.startswith('#'):
        return a == b
    return all(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) <= tol for i in (1, 3, 5))


def to_days(v, date):
    if not date:
        return v
    return [None if q is None else q / DAY for q in v]


class GB:
    """One Graph Builder graph and the figure its code drew."""

    def __init__(self, G, R):
        self.G, self.R = G, R
        self.plan = G['plan']
        self.F = R['figures'][0] if R and R.get('figures') else None
        self.V = (R or {}).get('vars', {}) or {}
        self.axes = [A for A in (self.F or {}).get('axes', []) if not A.get('colorbar')]
        ax = G['axes']
        self.date = {'x': any(v['type'] == 'date' for k, v in ax.items() if k.startswith('x')),
                     'y': any(v['type'] == 'date' for k, v in ax.items() if k.startswith('y'))}

    def traces(self, el, **kw):
        out = []
        for t in self.G['traces']:
            if t['overlay'] or t['el'] != el:
                continue
            if all((v(t.get(k)) if callable(v) else t.get(k) == v) for k, v in kw.items()):
                out.append(t)
        return out

    def ax(self, t):
        i = panel_of(t)
        return self.axes[i] if i < len(self.axes) else {'lines': [], 'xy_lines': [], 'scatter': [], 'bars': [], 'polys': [], 'polygons': [], 'segments': [],
                                                        'meshes': [], 'wedges': [], 'annotations': []}

    def days(self, v, axis):
        return to_days(v, self.date[axis])


def open_xy(P):
    """A polygon's vertices without the first one repeated at the end (matplotlib's fill closes its path)."""
    v = P['xy']
    return v[:-1] if len(v) > 1 and v[0] == v[-1] else v


def pts(t):
    return [(a, b) for a, b in zip(t['x'] or [], t['y'] or []) if a is not None and b is not None]


def line_match(g, t, lines, rel_tol=False):
    """How far the nearest of the axes' lines is from a trace's points."""
    wx, wy = g.days(t['x'], 'x'), g.days(t['y'], 'y')
    f = rel if rel_tol else md
    return min((max(f([p[0] for p in ln], wx), f([p[1] for p in ln], wy)) for ln in lines), default=float('inf'))


def check_gb(check, tag, G, R, err):
    """Everything the code's figure must share with the page's graph."""
    check(f'{tag}: the code runs in the page', err, None)
    if not R or not R.get('figures'):
        return None
    g = GB(G, R)
    F, plan = g.F, g.plan
    check(f'{tag}: one figure, the graph\'s size', (len(R['figures']), F['size']), (1, [G['w'] / 100, G['h'] / 100]))
    pies = [t for t in G['traces'] if t.get('type') == 'pie']
    nP = len(pies) if pies else 1 + max([panel_of(t) for t in G['traces']] + [0])
    shown = [A for A in g.axes if A['shown']]
    check(f'{tag}: a panel for each of the page\'s', len(shown), nP)
    if plan.get('title'):
        check(f'{tag}: the title', F['suptitle'] or (g.axes[0]['title'] if g.axes else ''), unesc(G['title']))
    check_axes(check, tag, g)
    for e in plan['elements']:
        fn = globals().get(f'el_{e["type"]}')
        if fn:
            fn(check, tag, g, e)
    return g


def el_points(check, tag, g, e):
    if e.get('summary', 'none') != 'none':
        return el_summary(check, tag, g, e, 'points')
    tr = [t for t in g.traces('points') if t['mode'] == 'markers']
    by = {}
    for t in tr:
        by.setdefault(panel_of(t), []).append(t)
    worst, n, cols, sizes = 0.0, 0, True, True
    for i, ts in by.items():
        sc = g.axes[i]['scatter'] if i < len(g.axes) else []
        if len(sc) < len(ts):
            worst = float('inf')
            continue
        for t, S in zip(ts, sc):
            want = [q for a, b in pts(t) for q in (g.days([a], 'x')[0], g.days([b], 'y')[0])]
            got = [q for p in S['xy'] for q in p]
            worst = max(worst, md(got, want))
            n += len(S['xy'])
            mc, fc = t['mcolor'] or [], S['colors']
            if len(mc) == 1:
                cols = cols and all(close_rgb(c, mc[0]) for c in fc)
            elif len(mc) == len(fc):
                cols = cols and all(close_rgb(a, b) for a, b in zip(fc, mc))
            else:
                cols = False
            want_s = [(0.72 * float(v)) ** 2 for v in (t['msize'] or [])]
            got_s = S['sizes']
            if len(want_s) == 1:
                sizes = sizes and all(abs(q - want_s[0]) <= 0.01 * want_s[0] for q in got_s)
            else:
                sizes = sizes and len(want_s) == len(got_s) and md(got_s, want_s) <= 0.01 * max(want_s)
    check.near(f'{tag}: Points: each point where the page draws it (jitter included)', worst, 0, 1e-9)
    check(f'{tag}: Points: every point, in the page\'s colours and sizes', (n, cols, sizes), (sum(len(pts(t)) for t in tr), True, True))


def errorbars_ok(g, t, key, bases=None):
    """Whether each of a trace's error bars (Plotly's array and arrayminus) is a segment of the axes."""
    A = g.ax(t)
    segs = [s for c in A['segments'] for s in c['segs']]
    horiz = key == 'ex'
    vals = t['x'] if horiz else t['y']
    j = 0 if horiz else 1
    ok = True
    for k, v in enumerate(vals):
        if v is None or t[key]['a'][k] is None:
            continue
        top = v + ((bases or [0] * len(vals))[k] or 0)
        lo, hi = top - t[key]['m'][k], top + t[key]['a'][k]
        lo, hi = (lo / DAY, hi / DAY) if g.date['x' if horiz else 'y'] else (lo, hi)
        tol = 1e-9 * max(1, abs(lo), abs(hi))
        ok = ok and any(abs(min(s[0][j], s[1][j]) - lo) < tol and abs(max(s[0][j], s[1][j]) - hi) < tol for s in segs)
    return ok


def el_summary(check, tag, g, e, el):
    """Points with a Summary Statistic, a summarized Line, an overlaid Area: the statistic at each place."""
    tr = [t for t in g.traces(el) if t['type'] in ('scatter', 'scattergl') and t['fill'] != 'toself']
    worst, ok = 0.0, True
    for t in tr:
        A = g.ax(t)
        if el == 'points':
            wx, wy = g.days(t['x'], 'x'), g.days(t['y'], 'y')
            best = min((max(md([p[0] for p in S['xy']], wx), md([p[1] for p in S['xy']], wy)) for S in A['scatter']), default=float('inf'))
        else:
            best = line_match(g, t, A['xy_lines'])
        worst = max(worst, best)
        for key in ('ey', 'ex'):
            if t[key]:
                ok = ok and errorbars_ok(g, t, key)
    check.near(f'{tag}: {el}: the statistic at each place', worst, 0, 1e-9)
    check(f'{tag}: {el}: the error bars span the page\'s intervals', ok, True)
    bands = [t for t in g.traces(el) if t['fill'] == 'toself']
    for t in bands:
        A = g.ax(t)
        ys = [v for v in g.days(t['y'], 'y') if v is not None]
        spans = [(min(q[1] for q in pp), max(q[1] for q in pp)) for P in A['polys'] if 'contour' not in P for pp in P['paths'] if pp]
        check(f'{tag}: {el}: the Error Band spans the page\'s', any(abs(lo - min(ys)) < 1e-9 * max(1, abs(lo)) and abs(hi - max(ys)) < 1e-9 * max(1, abs(hi)) for lo, hi in spans), True)


def el_line(check, tag, g, e):
    if e.get('ordering') == 'row':
        worst = max([line_match(g, t, g.ax(t)['xy_lines']) for t in g.traces('line')] + [0.0])
        check.near(f'{tag}: Line: through every row in the table\'s order', worst, 0, 1e-9)
        return
    if e.get('shape') == 'spline':   # the vertices as markers, and a curve through them
        worst, through = 0.0, True
        for t in g.traces('line', fill=lambda f: f != 'toself'):
            A = g.ax(t)
            marks = [ln for ln, L in zip(A['xy_lines'], A['lines']) if L['marker'] == 'o']
            worst = max(worst, line_match(g, t, marks))
            curves = [ln for ln, L in zip(A['xy_lines'], A['lines']) if L['marker'] in ('None', 'none', '')]
            wx, wy = g.days(t['x'], 'x'), g.days(t['y'], 'y')
            through = through and all(any(min(abs(p[0] - a) + abs(p[1] - b) for p in ln) < 1e-9 * max(1, abs(a), abs(b)) for ln in curves) for a, b in zip(wx, wy) if a is not None and b is not None)
        check.near(f'{tag}: Line (Curve): the vertices', worst, 0, 1e-9)
        check(f'{tag}: Line (Curve): the curve passes through every vertex', through, True)
        return
    el_summary(check, tag, g, e, 'line')


def el_area(check, tag, g, e):
    if e.get('areaStyle') != 'stacked':
        return el_summary(check, tag, g, e, 'area')
    tr = g.traces('area', fill=lambda f: f != 'toself')
    by = {}
    for t in tr:
        by.setdefault(panel_of(t), []).append(t)
    worst = 0.0
    for i, ts in by.items():
        A = g.axes[i]
        horiz = ts[0]['orientation'] == 'h'
        pos = (lambda t: t['y']) if horiz else (lambda t: t['x'])
        val = (lambda t: t['x']) if horiz else (lambda t: t['y'])
        places = sorted({q for t in ts for q in pos(t)})
        acc = {q: 0.0 for q in places}
        for t in ts:
            vals = dict(zip(pos(t), val(t)))
            for q in places:
                acc[q] += vals.get(q, 0.0) or 0.0
            top = [acc[q] for q in places]
            lines = [[p[0 if horiz else 1] for p in ln] for ln in A['xy_lines']]
            worst = max(worst, min((md(ln, top) for ln in lines), default=float('inf')))
    check.near(f'{tag}: Area, stacked: the top of each group\'s area', worst, 0, 1e-9)


def bars_of(g, el):
    tr = g.traces(el, type='bar')
    worst, n = 0.0, 0
    for t in tr:
        A = g.ax(t)
        horiz = t['orientation'] == 'h'
        pos = t['y'] if horiz else t['x']
        val = t['x'] if horiz else t['y']
        wid = t['width'] if isinstance(t['width'], list) else [t['width']] * len(pos)
        base = t['base'] if isinstance(t['base'], list) else [t['base'] or 0] * len(pos)
        for q, v, w_, b0 in zip(pos, val, wid, base):
            n += 1
            if horiz and g.date['y'] or (not horiz and g.date['x']):
                q, w_ = q / DAY, w_ / DAY
            best = float('inf')
            for b in A['bars']:
                if horiz:
                    d = max(abs(b['y'] + b['h'] / 2 - q), abs(b['h'] - w_), abs(b['x'] - (b0 or 0)), abs(b['w'] - (v or 0)))
                else:
                    d = max(abs(b['x'] + b['w'] / 2 - q), abs(b['w'] - w_), abs(b['y'] - (b0 or 0)), abs(b['h'] - (v or 0)))
                best = min(best, d)
            worst = max(worst, best)
    return tr, worst, n


def el_bar(check, tag, g, e, el='bar'):
    tr, worst, n = bars_of(g, el)
    check.near(f'{tag}: {el}: every bar where the page draws it: its place, width, base and length ({n})', worst, 0, 1e-9)
    ok = True
    for t in tr:
        for key in ('ey', 'ex'):
            if t[key]:
                ok = ok and errorbars_ok(g, t, key, t['base'] if isinstance(t['base'], list) else None)
    check(f'{tag}: {el}: the error bars span the page\'s intervals', ok, True)
    texts = [t for t in tr if t['text']]
    if texts:
        want = sorted(str(x) for t in texts for x in t['text'] if x not in (None, ''))
        got = sorted(a['s'] for A in g.axes for a in A['annotations'] if a['s'])
        check(f'{tag}: {el}: the labels on the bars as the page writes them', [x for x in got if x in want], want)


def el_box(check, tag, g, e):
    tr = g.traces('box', type='box')
    ok, n = True, 0
    for t in tr:
        A = g.ax(t)
        horiz = t['orientation'] == 'h'
        pos = t['y'] if horiz else t['x']
        j = 0 if horiz else 1
        close = lambda a, b: abs(a - b) < 1e-9 * max(1, abs(b))
        for k, q in enumerate(pos):
            n += 1
            med, q1, q3, lf, uf = t['median'][k], t['q1'][k], t['q3'][k], t['lowerfence'][k], t['upperfence'][k]
            segs = [ln for ln in A['xy_lines'] if len(ln) == 2 and None not in (ln[0][0], ln[0][1], ln[1][0], ln[1][1])]
            has_med = any(close(ln[0][j], med) and close(ln[1][j], med) and abs((ln[0][1 - j] + ln[1][1 - j]) / 2 - q) < 1e-9 for ln in segs)
            has_lo = any(abs(ln[0][1 - j] - q) < 1e-9 and abs(ln[1][1 - j] - q) < 1e-9 and sorted([ln[0][j], ln[1][j]]) == sorted([q1, lf]) for ln in segs) or close(q1, lf)
            has_hi = any(abs(ln[0][1 - j] - q) < 1e-9 and abs(ln[1][1 - j] - q) < 1e-9 and sorted([ln[0][j], ln[1][j]]) == sorted([q3, uf]) for ln in segs) or close(q3, uf)
            ok = ok and has_med and has_lo and has_hi
    check(f'{tag}: Box Plot: every box\'s median, quartiles and whiskers ({n})', ok, True)
    outl = [t for t in g.traces('box', type='scatter', mode='markers') if t['rows']]
    if outl:
        horiz = any(t['orientation'] == 'h' for t in tr)
        want = sorted(round(v, 9) for t in outl for v in (t['x'] if horiz else t['y']))
        got = sorted(round(p[0 if horiz else 1], 9) for A in g.axes for ln, L in zip(A['xy_lines'], A['lines']) if L['marker'] == 'o' and L['ls'] in ('None', 'none', '') for p in ln)
        check(f'{tag}: Box Plot: the outliers', got, want)
    dia = g.traces('box', mode='lines')
    if dia:
        want = sorted(round(v, 9) for t in dia for v in (t['y'] if not any(tt['orientation'] == 'h' for tt in tr) else t['x']) if v is not None)
        horiz = any(tt['orientation'] == 'h' for tt in tr)
        got = sorted(round(p[0 if horiz else 1], 9) for A in g.axes for ln in A['xy_lines'] if len(ln) == 5 for p in ln)
        check(f'{tag}: Box Plot: the confidence diamonds', got, want)


def el_histogram(check, tag, g, e):
    if e.get('kernel'):
        worst = 0.0
        for t in g.traces('histogram'):
            A = g.ax(t)
            cands = [open_xy(P) for P in A['polygons']] if e.get('band') else A['xy_lines']
            worst = max(worst, line_match(g, t, cands))
        check.near(f'{tag}: Histogram (kernel density): every curve', worst, 0, 1e-9)
        return
    el_bar(check, tag, g, e, 'histogram')


def el_mosaic(check, tag, g, e):
    el_bar(check, tag, g, e, 'mosaic')
    texts = [unesc(a['text']) for a in g.G['annotations'] if a['el'] == 'mosaic']
    if texts:
        got = [A['title'].split('\n')[-1] for A in g.axes if A['title']]
        check(f'{tag}: Mosaic: the chi-square test above each panel', [x for x in got if x in texts], texts)


def el_heatmap(check, tag, g, e):
    tr = g.traces('heatmap', type='heatmap')
    worst = 0.0
    for t in tr:
        A = g.ax(t)
        M = A['meshes'][0] if A['meshes'] else None
        worst = max(worst, rel(M['z'] if M else [], [v for row in t['z'] for v in row]))
    check.near(f'{tag}: Heatmap: every cell\'s value', worst, 0, 1e-12)
    zs = [v for t in tr for row in t['z'] for v in row if v is not None]
    clims = {tuple(round(v, 9) for v in A['meshes'][0]['clim']) for A in g.axes if A['meshes']}
    check(f'{tag}: Heatmap: one colour scale, from the smallest cell to the largest', clims, {(round(min(zs), 9), round(max(zs), 9))} if zs else set())


def el_pie(check, tag, g, e):
    ok, clockwise = True, True
    for i, t in enumerate(g.traces('pie', type='pie')):
        A = g.axes[i] if i < len(g.axes) else {'wedges': []}
        vals = [max(0.0, v or 0.0) for v in t['values']]
        tot = sum(vals)
        want = [360 * v / tot for v in vals if v > 0] if tot else []
        W = [w for w in A['wedges'] if (w['theta2'] - w['theta1']) % 360 > 1e-9]
        got = [(w['theta2'] - w['theta1']) % 360 or 360.0 for w in W]
        ok = ok and md(got, want) < 1e-4          # matplotlib keeps the angles in single precision
        clockwise = clockwise and bool(W) and abs(W[0]['theta2'] - 90) < 1e-4 and all(abs(a['theta1'] - b['theta2']) < 1e-4 for a, b in zip(W, W[1:]))
    check(f'{tag}: Pie: each slice\'s angle is its share', ok, True)
    check(f'{tag}: Pie: the slices in the page\'s order, clockwise from the top', clockwise, True)


def el_smoother(check, tag, g, e):
    worst, bands = 0.0, True
    for t in g.traces('smoother'):
        A = g.ax(t)
        wy = g.days(t['y'], 'y')
        if t['fill'] == 'toself':
            ys = [v for v in wy if v is not None]
            spans = [(min(q[1] for q in pp), max(q[1] for q in pp)) for P in A['polys'] if 'contour' not in P for pp in P['paths'] if pp]
            bands = bands and any(abs(lo - min(ys)) < 1e-9 * max(1, abs(lo)) and abs(hi - max(ys)) < 1e-9 * max(1, abs(hi)) for lo, hi in spans)
            continue
        if e.get('method') == 'lowess':   # the page thins its curve to at most 480 points: each is on the code's
            wx = g.days(t['x'], 'x')
            best = float('inf')
            for ln in A['xy_lines']:
                at = {round(p[0], 12): p[1] for p in ln}
                try:
                    best = min(best, md([at[round(a, 12)] for a in wx], wy))
                except KeyError:
                    continue
            worst = max(worst, best)
        else:
            worst = max(worst, line_match(g, t, A['xy_lines']))
    check.near(f'{tag}: Smoother: the curve', worst, 0, 1e-9)
    check(f'{tag}: Smoother: the Confidence of Fit spans the page\'s band', bands, True)


def el_fit(check, tag, g, e):
    worst, bands = 0.0, True
    for t in g.traces('fit'):
        A = g.ax(t)
        if t['fill'] == 'toself':
            ys = [v for v in g.days(t['y'], 'y') if v is not None]
            spans = [(min(q[1] for q in pp), max(q[1] for q in pp)) for P in A['polys'] if 'contour' not in P for pp in P['paths'] if pp]
            bands = bands and any(abs(lo - min(ys)) < 1e-7 * max(1, abs(lo)) and abs(hi - max(ys)) < 1e-7 * max(1, abs(hi)) for lo, hi in spans)
            continue
        worst = max(worst, line_match(g, t, A['xy_lines'], rel_tol=True))
    check.near(f'{tag}: Line of Fit: the line and the prediction limits', worst, 0, 1e-7)
    check(f'{tag}: Line of Fit: the Confidence of Fit spans the page\'s band', bands, True)
    texts = [unesc(a['text']).replace('<br>', '\n') for a in g.G['annotations'] if a['el'] == 'fit']
    if texts:
        got = [a['s'] for A in g.axes for a in A['annotations']]
        check(f'{tag}: Line of Fit: the equation, R², RMSE and F test as the page writes them', sorted(x for x in got if x in texts), sorted(texts))


def el_ellipse(check, tag, g, e):
    worst = max([line_match(g, t, g.ax(t)['xy_lines'], rel_tol=True) for t in g.traces('ellipse', mode='lines')] + [0.0])
    check.near(f'{tag}: Ellipse: every ellipse', worst, 0, 1e-9)
    texts = [unesc(a['text']) for a in g.G['annotations'] if a['el'] == 'ellipse']
    if texts:
        got = [a['s'] for A in g.axes for a in A['annotations']]
        check(f'{tag}: Ellipse: the correlations', sorted(x for x in got if x in texts), sorted(texts))


def el_contour(check, tag, g, e):
    if e.get('violin'):
        worst = max([min((max(md([p[0] for p in open_xy(P)], g.days(t['x'], 'x')), md([p[1] for p in open_xy(P)], g.days(t['y'], 'y'))) for P in g.ax(t)['polygons']), default=float('inf'))
                     for t in g.traces('contour')] + [0.0])
        check.near(f'{tag}: Contour (violins): every violin', worst, 0, 1e-9)
        return
    tr = g.traces('contour', type='contour')
    L = int(e['levels'])
    ok = True
    for t in tr:
        levels = [P['contour'] for P in g.ax(t)['polys'] if 'contour' in P]
        if e.get('line'):
            ok = ok and any(md(lv, [k / L for k in range(L)]) < 1e-12 for lv in levels)
        if e.get('fill'):
            ok = ok and any(md(lv, [k / L for k in range(L + 1)]) < 1e-12 for lv in levels)
    check(f'{tag}: Contour: the page\'s {L} levels', ok, True)
    z = g.V.get('inner')
    if z is not None and len(tr) == 1:
        check.near(f'{tag}: Contour: the share of the points inside each density contour, on the page\'s grid', rel(z, [v for row in tr[0]['z'] for v in row]), 0, 1e-9)


def el_bean(check, tag, g, e):
    worst = 0.0
    for t in g.traces('bean', fill='toself'):
        A = g.ax(t)
        worst = max(worst, min((max(md([p[0] for p in open_xy(P)], g.days(t['x'], 'x')), md([p[1] for p in open_xy(P)], g.days(t['y'], 'y'))) for P in A['polygons']), default=float('inf')))
    check.near(f'{tag}: Bean: every violin', worst, 0, 1e-9)
    beans = [t for t in g.traces('bean', mode='markers') if t['rows'] and t['symbol'] in ('line-ew-open', 'line-ns-open')]
    if beans:
        horiz = beans[0]['symbol'] == 'line-ns-open'
        want = sorted(round(v, 9) for t in beans for v in (t['x'] if horiz else t['y']))
        got = sorted(round(s[0][0 if horiz else 1], 9) for A in g.axes for c in A['segments'] for s in c['segs'])
        check(f'{tag}: Bean: a line for each row', got, want)
    dots = [t for t in g.traces('bean', mode='markers') if t['rows'] and t['symbol'] not in ('line-ew-open', 'line-ns-open', 'cross-thin-open')]
    if dots:
        worst = 0.0
        for t in dots:
            A = g.ax(t)
            worst = max(worst, min((max(md([p[0] for p in S['xy']], g.days(t['x'], 'x')), md([p[1] for p in S['xy']], g.days(t['y'], 'y'))) for S in A['scatter']), default=float('inf')))
        check.near(f'{tag}: Bean: a dot for each row, jittered as the page', worst, 0, 1e-9)
    means = [t for t in g.traces('bean', mode='lines') if not t['fill']]
    if means:
        horiz = any(t['symbol'] == 'line-ns-open' for t in beans)
        want = sorted(round(v, 9) for t in means for v in (t['x'] if horiz else t['y']) if v is not None)
        got = sorted(round(p[0 if horiz else 1], 9) for A in g.axes for ln, L in zip(A['xy_lines'], A['lines']) if L['marker'] in ('None', 'none', '') and len(ln) == 2 for p in ln)
        check(f'{tag}: Bean: the mean lines', [v for v in want if v in got], want)
    meds = g.traces('bean', symbol='cross-thin-open')
    if meds:
        horiz = any(t['symbol'] == 'line-ns-open' for t in beans)
        want = sorted(round(v, 9) for t in meds for v in (t['x'] if horiz else t['y']))
        got = sorted(round(p[0 if horiz else 1], 9) for A in g.axes for ln, L in zip(A['xy_lines'], A['lines']) if L['marker'] == '+' for p in ln)
        check(f'{tag}: Bean: the medians', got, want)


def el_caption(check, tag, g, e):
    texts = [unesc(a['text']).replace('<br>', '\n') for a in g.G['annotations'] if a['el'] == 'caption']
    got = [a['s'] for A in g.axes for a in A['annotations']]
    check(f'{tag}: Caption Box: the statistics as the page writes them', sorted(x for x in got if x in texts), sorted(texts))


def check_axes(check, tag, g):
    """The axis titles, the categorical axes' levels in the page's order, date axes as dates, the legend."""
    G, F = g.G, g.F
    if g.plan.get('exclusive') == 'pie':   # no axes
        return
    for a in ('x', 'y'):
        shared = {t for t in (g.plan['titles'].get(a) or []) if t}   # a title the page writes once for several panels, as a note
        want = sorted({unesc(v['title']) for k, v in G['axes'].items() if k.startswith(a) and v.get('title')}
                      | {unesc(n['text']) for n in G['annotations'] if not n['el'] and unesc(n['text']) in shared})
        got = sorted({A[f'{a}label'] for A in g.axes if A['shown'] and A[f'{a}label']} | ({F[f'sup{a}']} if F.get(f'sup{a}') else set()))
        check(f'{tag}: the {a.upper()} axis titles, the page\'s', got, want)
        want = sorted({tuple(unesc(q) for q in v['ticktext']) for k, v in G['axes'].items() if k.startswith(a) and v.get('ticktext')})
        if want:
            got = sorted({tuple(A[f'{a}ticklabels']) for A in g.axes if A['shown'] and A[f'{a}ticklabels'] and any(A[f'{a}ticklabels'])})
            check(f'{tag}: the {a.upper()} axis levels in the page\'s order', [w for w in want if w in got], want)
        if g.date[a]:
            check(f'{tag}: the {a.upper()} axis shows dates', all(A[f'{a}axis_date'] for A in g.axes if A['shown']), True)
    want = [unesc(t['name']) for t in G['traces'] if t.get('showlegend') and t.get('name') and not t['overlay']]
    if G.get('legend') and want:
        got = F['legend'] + [q for A in g.axes for q in A['legend']]
        check(f'{tag}: the legend: the page\'s entries', [w for w in want if w in got], want)


# The other Graph platforms' graphs as the page drew them, for the checks of their code; and
# options set on the last report by column name, the report run again.
OTHERS_JS = r'''
window.__oq = async (rep) => {
  rep = rep || SM.app.reports[SM.app.reports.length - 1];
  await __gr.graphs(rep);
  const keys = ['type', 'mode', 'name', 'x', 'y', 'z', 'a', 'b', 'c', 'values', 'labels', 'ids', 'parents', 'width', 'xaxis', 'yaxis', 'fill', 'showlegend',
    'hovertemplate', 'contours', 'zmin', 'zmax', 'colorscale', 'direction', 'rotation', 'sort', 'hole', 'orientation'];
  return rep.plots.map((p) => {
    const gd = p.box, L = gd._fullLayout || {};
    const n = gd.nextElementSibling;
    const tr = (gd.data || []).map((t, i) => {
      const o = {};
      for (const k of keys) if (t[k] !== undefined) o[k] = t[k];
      if (t.marker) o.marker = { color: t.marker.color, size: t.marker.size, colors: t.marker.colors, opacity: t.marker.opacity };
      if (t.line) o.line = { color: t.line.color, width: t.line.width, dash: t.line.dash, shape: t.line.shape };
      if (t.colorbar && t.colorbar.title) o.colorbar = t.colorbar.title.text;
      const cd = gd.calcdata && gd.calcdata[i];
      if (cd && t.type === 'scatter' && (t.mode || '').includes('markers')) o.mrc = cd.map((q) => (q.mrc == null ? null : q.mrc));
      return o;
    });
    // the axes the page laid out (Plotly leaves those without a trace out of its own layout): their titles as the
    // page set them, and the ranges, types and ticks Plotly drew
    const U = gd.layout || {}, axes = {};
    const title = (a) => (a && a.title ? (typeof a.title === 'string' ? a.title : a.title.text) || null : null);
    for (const k of new Set([...Object.keys(U), ...Object.keys(L)])) {
      if (!/^[xy]axis\d*$/.test(k)) continue;
      const u = U[k] || {}, f = L[k] || {};
      axes[k] = { title: title(u), range: f.range || u.range || null, type: f.type || u.type || null, ticktext: u.ticktext || f.ticktext || null, domain: u.domain || f.domain || null };
    }
    const scene = L.scene ? ['xaxis', 'yaxis', 'zaxis'].map((a) => L.scene[a].title.text) : null;
    const ternary = L.ternary ? ['aaxis', 'baxis', 'caxis'].map((a) => L.ternary[a].title.text) : null;
    const tiles = [...gd.querySelectorAll('g.slice')].map((g) => g.__data__).filter(Boolean)
      .map((d) => ({ id: d.data && d.data.data ? d.data.data.id : null, x0: d.x0, x1: d.x1, y0: d.y0, y1: d.y1 }));
    return { title: p.opts.title, code: n && n.matches('details.sm-code') ? n.querySelector('code').textContent : null, tr, axes, scene, ternary, tiles, area: L._size ? [L._size.w, L._size.h] : null,
      size: [p.width, p.height], w: p.ownWidth, h: p.height, legend: (gd.data || []).filter((t) => t.showlegend !== false && t.name).map((t) => t.name),
      legendTitle: L.legend && L.legend.title ? L.legend.title.text : null, showlegend: !!L.showlegend, annotations: (L.annotations || []).map((a) => a.text) };
  });
};
'''
OPTS_JS = r'''
window.__optRun = async (opts) => {   // options of the last report set by column name ('z|fill') or alone, and the report run again
  const rep = SM.app.reports[SM.app.reports.length - 1];
  for (const [k, v] of Object.entries(opts)) { const [a, b] = k.includes('|') ? k.split('|') : [null, k]; rep.spec.options[a ? `${rep.table.col(a).id}|${b}` : b] = v; }
  const done = new Promise((res) => rep.on('done', res)); rep.run(); await done;
};
'''


def gaps_split(xs, ys):
    """A trace's x and y split at its gaps (None) into polylines."""
    out, cur = [], []
    for a, b in zip(xs or [], ys or []):
        if a is None or b is None:
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append((float(a), float(b)))
    if cur:
        out.append(cur)
    return out


def same_points(got, want, tol=1e-9):
    """Two lists of points the same, in any order."""
    g = sorted(tuple(round(v / tol) * tol for v in p) for p in got)
    w = sorted(tuple(round(v / tol) * tol for v in p) for p in want)
    if len(g) != len(w):
        return float('inf')
    return max([max(abs(a - b) for a, b in zip(p, q)) for p, q in zip(g, w)] + [0.0])


def pts_of(t):
    return [(a, b) for a, b in zip(t.get('x') or [], t.get('y') or []) if a is not None and b is not None]


def arr(v, n):
    return list(v) if isinstance(v, list) else [v] * n


def fig_of(check, tag, R, err, P):
    check(f'{tag}: its code runs in the page', err, None)
    if not R or not R.get('figures'):
        return None
    F = R['figures'][0]
    check(f'{tag}: one figure, the graph\'s size', (len(R['figures']), F['size']), (1, [P['size'][0] / 100, P['size'][1] / 100]))
    return F


# ---- Scatterplot Matrix -----------------------------------------------------------------
def matrix_cells(P):
    """The page's cells: {(row, column): (xaxis, yaxis)}, from the axes' domains; and the rows and columns."""
    xs = sorted({round(v['domain'][0], 9) for k_, v in P['axes'].items() if k_.startswith('x')})
    ys = sorted({round(v['domain'][0], 9) for k_, v in P['axes'].items() if k_.startswith('y')})
    cells = {}
    for k_, v in P['axes'].items():
        if k_.startswith('x'):
            n = k_[5:]
            yv = P['axes'].get(f'yaxis{n}')
            cells[(len(ys) - 1 - ys.index(round(yv['domain'][0], 9)), xs.index(round(v['domain'][0], 9)))] = (f'x{n}', f'y{n}')
    return cells, len(ys), len(xs)


def plat_matrix(check, tag, P, R, err):
    F = fig_of(check, tag, R, err, P)
    if not F:
        return
    A = F['axes']
    cells, k, m = matrix_cells(P)
    check(f'{tag}: the page\'s cells shown, the others left out', sorted((i, j) for i in range(k) for j in range(m) if A[i * m + j]['shown']), sorted(cells))
    worst = {'hist': 0.0, 'pts': 0.0, 'ell': 0.0, 'fit': 0.0, 'band': 0.0}
    colours, contours = True, True
    for (i, j), (xa, ya) in cells.items():
        a = A[i * m + j]
        mine = [t for t in P['tr'] if t.get('xaxis', 'x') == xa and t.get('yaxis', 'y') == ya and t.get('showlegend') is not True]
        bars = [t for t in mine if t['type'] == 'bar']
        if bars:   # the diagonal
            got = sorted((b['x'] + b['w'] / 2, b['h']) for b in a['bars'])
            worst['hist'] = max(worst['hist'], same_points(got, list(zip(bars[0]['x'], bars[0]['y']))))
            continue
        pt = next((t for t in mine if t['type'] == 'scatter' and t['mode'] == 'markers'), None)
        if pt is None:
            continue
        S = a['scatter'][0]
        worst['pts'] = max(worst['pts'], same_points(S['xy'], pts_of(pt)))
        want_c = sorted(zip(pts_of(pt), [hexrgb(c) for c in arr(pt['marker']['color'], len(pt['x']))]))
        cs_ = S['colors'] * len(S['xy']) if len(S['colors']) == 1 else S['colors']
        got_c = sorted(zip([tuple(p) for p in S['xy']], [hexrgb(c) for c in cs_]))
        colours = colours and [c for _, c in got_c] == [c for _, c in want_c]
        for t in mine:
            if t['type'] == 'contour':   # Nonpar Density: the contours holding 100, 75, 50 and 25% of the points
                contours = contours and any([round(v, 9) for v in c['contour']] == [0.0, 0.25, 0.5, 0.75] for c in a['polys'] if 'contour' in c)
                continue
            if t['type'] != 'scatter' or t['mode'] != 'lines':
                continue
            col = (t.get('line') or {}).get('color')
            xy = list(zip(t['x'], t['y']))
            if t.get('fill') == 'toself' and not (t.get('hovertemplate') or '').startswith('r = '):   # a fit's band: the same highs and lows
                ys = [q[1] for q in xy]
                best = min((max(abs(max(ys) - max(v[1] for v in p)), abs(min(ys) - min(v[1] for v in p))) for c in a['polys'] if 'paths' in c for p in c['paths']), default=float('inf'))
                worst['band'] = max(worst['band'], best / max(1.0, max(abs(v) for v in ys)))
                continue
            key = 'ell' if (t.get('hovertemplate') or '').startswith('r = ') else 'fit'
            best = min((max(md([p[0] for p in ln], [q[0] for q in xy]), md([p[1] for p in ln], [q[1] for q in xy]))
                        for ln, L in zip(a['xy_lines'], a['lines']) if close_rgb(L['color'], col)), default=float('inf'))
            worst[key] = max(worst[key], best)
    check.near(f'{tag}: the histograms\' bars, the page\'s', worst['hist'], 0, 1e-9)
    check.near(f'{tag}: every cell\'s points, the page\'s', worst['pts'], 0, 1e-9)
    check(f'{tag}: the points in their group\'s colour', colours, True)
    for key, what in (('ell', 'the density ellipses'), ('fit', 'the fit lines')):
        if any((t.get('hovertemplate') or '').startswith('r = ') == (key == 'ell') and t['type'] == 'scatter' and t['mode'] == 'lines' and t.get('fill') != 'toself' for t in P['tr']):
            check.near(f'{tag}: {what}, the page\'s', worst[key], 0, 1e-9)
    if any(t.get('fill') == 'toself' and not (t.get('hovertemplate') or '').startswith('r = ') for t in P['tr']):
        check.near(f'{tag}: the fit lines\' bands reach as far as the page\'s', worst['band'], 0, 1e-9)
    if any(t['type'] == 'contour' for t in P['tr']):
        check(f'{tag}: Nonpar Density: the contours holding 100, 75, 50 and 25% of the points in each cell', contours, True)
    for a_ in ('x', 'y'):
        check(f'{tag}: the {a_.upper()} titles, the page\'s', sorted({x[f'{a_}label'] for x in A if x['shown'] and x[f'{a_}label']}), sorted({v['title'] for k_, v in P['axes'].items() if k_.startswith(a_) and v['title'] and not v['title'].startswith('Click to enter')}))
    check(f'{tag}: the legend: the groups', F['legend'], P['legend'])


# ---- Scatterplot 3D, Surface Plot ------------------------------------------------------------
def pts3(t):
    return [(a, b, c) for a, b, c in zip(t['x'], t['y'], t['z']) if a is not None and b is not None and c is not None]


def plat_scatter3d(check, tag, P, R, err, levels=None):
    """levels: a categorical Coloring's levels (the page lists them under the graph); None: a continuous one, its colour bar."""
    F = fig_of(check, tag, R, err, P)
    if not F:
        return
    a = next(A for A in F['axes'] if not A['colorbar'])
    S = a['scatter3d'][0] if a['scatter3d'] else {'xyz': [[], [], []], 'colors': []}
    t = P['tr'][0]
    got = list(zip(*S['xyz']))
    check.near(f'{tag}: every point where the page draws it', same_points(got, pts3(t)), 0, 1e-9)
    want_c = sorted(zip(pts3(t), [hexrgb(c) for c in arr(t['marker']['color'], len(t['x']))]))
    got_c = sorted(zip(got, [hexrgb(c) for c in S['colors']]))
    check(f'{tag}: each in the page\'s colour (within 3 of 255 on a gradient: matplotlib\'s 256 colours)', len(got_c) == len(want_c) and all(close_rgb(g_[1], w_[1], 0 if levels else 3) for g_, w_ in zip(got_c, want_c)), True)
    check(f'{tag}: the axis titles, the page\'s', [a['xlabel'], a['ylabel'], a['zlabel']], P['scene'])
    check(f'{tag}: the legend: the levels, as the page lists them under the graph (none for a gradient)', F['legend'], list(levels or []))


def grid_diff(got, want_rows):
    """A grid the code computed (flattened, row by row) against the page's rows."""
    want = [v for row in want_rows for v in row]
    return md(got, want) if got is not None else float('inf')


def plat_contour(check, tag, P, R, err):
    F = fig_of(check, tag, R, err, P)
    if not F:
        return
    a = next(A for A in F['axes'] if not A['colorbar'])
    t = next(q for q in P['tr'] if q['type'] == 'contour')
    check.near(f'{tag}: the grid of interpolated values, the page\'s (griddata)', grid_diff(R['vars'].get('gz'), t['z']), 0, 1e-9)
    lv = next((c['contour'] for c in a['polys'] if 'contour' in c), None)
    C = t['contours']
    want = [C['start'] + q * C['size'] for q in range(int(round((C['end'] - C['start']) / C['size'])) + 1)]
    check(f'{tag}: the contours at the page\'s levels', lv and [round(v, 9) for v in lv], [round(v, 9) for v in want])
    dots = next(q for q in P['tr'] if q['type'] == 'scatter')
    check.near(f'{tag}: the data points', same_points(a['scatter'][0]['xy'] if a['scatter'] else [], pts_of(dots)), 0, 1e-9)
    check(f'{tag}: the axis titles and the colour bar\'s', (a['xlabel'], a['ylabel'], F['colorbars']), (P['axes']['xaxis']['title'], P['axes']['yaxis']['title'], [t.get('colorbar')]))


def plat_surface(check, tag, P, R, err):
    F = fig_of(check, tag, R, err, P)
    if not F:
        return
    a = F['axes'][0]
    t = next(q for q in P['tr'] if q['type'] == 'surface')
    check.near(f'{tag}: the surface, the page\'s grid (griddata)', grid_diff(R['vars'].get('gz'), t['z']), 0, 1e-9)
    dots = next(q for q in P['tr'] if q['type'] == 'scatter3d')
    got = list(zip(*a['scatter3d'][0]['xyz'])) if a['scatter3d'] else []
    check.near(f'{tag}: the data points', same_points(got, pts3(dots)), 0, 1e-9)
    check(f'{tag}: the axis titles, the page\'s', [a['xlabel'], a['ylabel'], a['zlabel']], P['scene'])


# ---- Bubble Plot -------------------------------------------------------------------------------
def plat_bubble(check, tag, P, R, err):
    F = fig_of(check, tag, R, err, P)
    if not F:
        return
    a = F['axes'][0]
    t = P['tr'][0]
    S = a['scatter'][0]
    check.near(f'{tag}: the first frame\'s bubbles, where the page draws them', md([q for p in S['xy'] for q in p], [q for p in zip(t['x'], t['y']) for q in p]), 0, 1e-9)
    px = [math.sqrt(s) / 0.72 for s in S['sizes']]
    check.near(f'{tag}: each bubble as wide as Plotly draws it (its diameter in pixels)', md(px, [2 * r for r in t['mrc']]), 0, 1e-6)
    want = [hexrgb(c) for c in arr(t['marker']['color'], len(t['x']))]
    check(f'{tag}: each in the page\'s colour (within 3 of 255 on a gradient)', len(S['colors']) == len(want) and all(close_rgb(a_, b_, 3) for a_, b_ in zip(S['colors'], want)), True)
    check.near(f'{tag}: the page\'s axis ranges', md(a['xlim'] + a['ylim'], P['axes']['xaxis']['range'] + P['axes']['yaxis']['range']), 0, 1e-6)
    check(f'{tag}: the axis titles', (a['xlabel'], a['ylabel']), (P['axes']['xaxis']['title'], P['axes']['yaxis']['title']))


# ---- Parallel Plot ------------------------------------------------------------------------------
def plat_parallel(check, tag, P, R, err):
    F = fig_of(check, tag, R, err, P)
    if not F:
        return
    a = F['axes'][0]
    got = sorted((hexrgb(L['color']), tuple(round(v, 9) for v in L['y'])) for L in a['lines'] if L['marker'] == 'o')
    want = []
    for t in P['tr']:
        if 'markers' not in (t.get('mode') or ''):   # (the selected rows' lines are drawn again, without markers)
            continue
        for line in gaps_split(t['x'], t['y']):
            want.append((hexrgb(t['marker']['color']), tuple(round(q[1], 9) for q in line)))
    check(f'{tag}: a line for each row, where the page draws it, in its group\'s colour', (len(got), got == sorted(want)), (len(want), True))
    k = len(a['xticklabels'])
    check(f'{tag}: the axes named as the page\'s', a['xticklabels'], P['annotations'][-k:])
    check(f'{tag}: each axis\'s range written at its ends, as the page\'s', [x['s'] for x in a['annotations']], P['annotations'][:-k])
    check(f'{tag}: the legend: the groups', F['legend'], P['legend'])


# ---- Cell Plot ------------------------------------------------------------------------------------
def plat_cell(check, tag, P, R, err):
    F = fig_of(check, tag, R, err, P)
    if not F:
        return
    a = next(A for A in F['axes'] if not A['colorbar'])
    names = [c for c in P['axes']['xaxis']['ticktext'] or [] if c]   # the selection strip's column has no name
    k = len(names)
    hm = [t for t in P['tr'] if t['type'] == 'heatmap'][:k]
    Z = R['vars'].get('Z')
    worst = max(md(Z[j::k], [row[0] for row in t['z']]) for j, t in enumerate(hm)) if Z else float('inf')
    check.near(f'{tag}: each cell\'s value, the page\'s (standardized, or the level\'s number)', worst, 0, 1e-9)
    check(f'{tag}: a cell for each row and column', a['images'][0]['shape'][:2] if a['images'] else None, [len(hm[0]['z']), k])
    check(f'{tag}: the columns named, the rows counted, as the page', (a['xticklabels'], a['ylabel']), (names, P['axes']['yaxis']['title']))


# ---- Ternary Plot ------------------------------------------------------------------------------------
def plat_ternary(check, tag, P, R, err):
    F = fig_of(check, tag, R, err, P)
    if not F:
        return
    a = F['axes'][0]
    t = P['tr'][0]
    want = []
    for A_, B_, C_ in zip(t['a'], t['b'], t['c']):
        s = A_ + B_ + C_
        want.append((0.5 * A_ / s + C_ / s, math.sqrt(3) / 2 * A_ / s))
    check.near(f'{tag}: each point at its shares (a at the top, b bottom left, c bottom right)', same_points(a['scatter'][0]['xy'], want), 0, 1e-9)
    check(f'{tag}: the corners named as the page\'s', [x['s'] for x in a['annotations']][:3], P['ternary'])


# ---- Treemap ---------------------------------------------------------------------------------------
def plat_treemap(check, tag, P, R, err):
    F = fig_of(check, tag, R, err, P)
    if not F:
        return
    a = F['axes'][0]
    H = P['area'][1]
    got = sorted((b['x'], H - b['y'] - b['h'], b['x'] + b['w'], H - b['y']) for b in a['bars'])
    want = sorted((d['x0'], d['y0'], d['x1'], d['y1']) for d in P['tiles'][1:])
    check(f'{tag}: a tile for each of the page\'s', len(got), len(want))
    check.near(f'{tag}: every tile where Plotly lays it out (squarified, padded)', same_points(got, want, 1e-9), 0, 1e-6)


# ---- Chart -------------------------------------------------------------------------------------------
def plat_chart(check, tag, P, R, err):
    F = fig_of(check, tag, R, err, P)
    if not F:
        return
    a = F['axes'][0]
    t = P['tr'][0]
    titles = (unesc(P['axes']['xaxis']['title']), unesc(P['axes']['yaxis']['title']))
    if t['type'] == 'pie':
        W = a['wedges']
        tot = sum(t['values'])
        check.near(f'{tag}: each slice\'s share, the page\'s', md([(w['theta2'] - w['theta1']) / 360 for w in W], [v / tot for v in t['values']]), 0, 1e-6)
        check(f'{tag}: each in the page\'s colour, clockwise from the top', ([hexrgb(w['fc']) for w in W], round(W[0]['theta2'], 6) if W else None), ([hexrgb(c) for c in t['marker']['colors']], 90.0))
        check(f'{tag}: the legend: the levels', F['legend'], t['labels'])
        return
    horiz = t.get('orientation') == 'h'
    cats = 'y' if horiz else 'x'
    check(f'{tag}: the levels in the page\'s order, the axis titles', (a[f'{cats}ticklabels'], a['xlabel'], a['ylabel']), (P['axes'][f'{cats}axis']['ticktext'],) + titles)
    if t['type'] == 'scatter':   # Line and Point charts: each line's (or points') statistics
        want = sorted(tuple(round(v, 9) for v in q['y']) for q in P['tr'] if q['type'] == 'scatter' and q.get('y') and q.get('showlegend') is not False)
        got = sorted(tuple(round(v, 9) for v in L['y']) for L in a['lines'] if len(L['y']) == len(t['y']))
        check(f'{tag}: each line through the page\'s statistics', [w_ for w_ in want if w_ in got], want)
        return
    bars = sorted(a['bars'], key=lambda b: b['y'] if horiz else b['x'])
    check.near(f'{tag}: the bars, the page\'s', md([b['w'] if horiz else b['h'] for b in bars], t['x'] if horiz else t['y']), 0, 1e-9)


# ---- Overlay Plot ------------------------------------------------------------------------------------------
def plat_overlay(check, tag, P, R, err):
    F = fig_of(check, tag, R, err, P)
    if not F:
        return
    AX = F['axes']
    lines = {L['label']: L for A in AX for L in A['lines']}
    tr = [t for t in P['tr'] if t.get('name')]
    worst = max([md(lines[t['name']]['x'], t['x']) + md(lines[t['name']]['y'], t['y']) if t['name'] in lines else float('inf') for t in tr] + [0.0])
    check.near(f'{tag}: each Y\'s line, the page\'s (X in order)', worst, 0, 1e-9)
    steps = [(t['name'], (t.get('line') or {}).get('shape') == 'hv') for t in tr]
    check(f'{tag}: a step where the page steps', [(n, lines[n]['drawstyle'] == 'steps-post') for n, _ in steps if n in lines], steps)
    needles = [t for t in P['tr'] if not t.get('name') and t.get('mode') == 'lines' and (t.get('line') or {}).get('width') == 1]
    if needles:
        want = sorted(round(seg[-1][1], 9) for t in needles for seg in gaps_split(t['x'], t['y']))
        got = sorted(round(s_[1][1], 9) for A in AX for c in A['segments'] for s_ in c['segs'])
        check(f'{tag}: a needle from 0 to each point', got == want and len(got) > 0, True)
    for a_ in ('x', 'y'):
        check(f'{tag}: the {a_.upper()} titles, the page\'s', sorted({A[f'{a_}label'] for A in AX if A[f'{a_}label']}), sorted({unesc(v['title']) for k_, v in P['axes'].items() if k_.startswith(a_) and v['title']}))
    check(f'{tag}: the legend, the page\'s', F['legend'], [t['name'] for t in tr])


# ---- Functional Data Plot ------------------------------------------------------------------------------------
def at_x(t, xs):
    """A trace's y at the curves' points (the page draws its curves with more points between)."""
    m = {round(float(a), 9): b for a, b in zip(t['x'], t['y']) if a is not None}
    return [m.get(round(float(v), 9)) for v in xs]


def plat_functional(check, tag, P, R, err, xs):
    F = fig_of(check, tag, R, err, P)
    if not F:
        return
    a = next(A for A in F['axes'] if not A['colorbar'])
    named = {t['name']: t for t in P['tr'] if t.get('name')}
    lines = {L['label']: L for L in a['lines']}
    view = P['title']
    if view == 'HDR score plot':
        S = a['scatter'][0]
        pt = named['Curves']
        check.near(f'{tag}: each curve\'s scores, the page\'s', same_points(S['xy'], pts_of(pt)), 0, 1e-9)
        mode = named['Mode: the modal curve']
        ml = next((L for L in a['lines'] if L['marker'] == 'x'), None)
        check.near(f'{tag}: the mode, the page\'s', md([ml['x'][0], ml['y'][0]] if ml else [], [mode['x'][0], mode['y'][0]]), 0, 1e-7)
        lv = sorted({round(v, 12) for c in a['polys'] if 'contour' in c for v in c['contour'] if v is not None and math.isfinite(v)})
        want = sorted({round(t['contours']['value'], 12) for t in P['tr'] if t['type'] == 'contour'})
        check.near(f'{tag}: the regions\' density levels, the page\'s', md(lv, want), 0, 1e-12)
        check(f'{tag}: the axis titles', (a['xlabel'], a['ylabel']), (P['axes']['xaxis']['title'], P['axes']['yaxis']['title']))
        return
    check(f'{tag}: the axis titles', (a['xlabel'], a['ylabel']), (P['axes']['xaxis']['title'], P['axes']['yaxis']['title']))
    if view == 'Rainbow plot':
        want = sorted((tuple(round(v, 9) for v in at_x(t, xs)), hexrgb(t['line'].get('color'))) for t in P['tr'] if t['type'] == 'scatter' and t['mode'] == 'lines' and t.get('x') and len(t['x']) > 1 and t['line'].get('color') != '#d9822b')
        got = sorted((tuple(round(v, 9) for v in L['y']), hexrgb(L['color'])) for L in a['lines'])
        same = len(got) == len(want) and all(g[0] == w[0] and close_rgb(g[1], w[1], 3) for g, w in zip(got, want))
        check(f'{tag}: each curve in its depth\'s colour (within 3 of 255: matplotlib\'s 256 colours)', (len(got), same), (len(want), True))
        return
    worst = 0.0
    for name, t in named.items():
        if t.get('fill') == 'toself' or name.endswith('more outliers') or name == 'Curves':
            continue
        L = lines.get(name)
        worst = max(worst, md(L['y'], at_x(t, xs)) if L else float('inf'))
    check.near(f'{tag}: the median (or modal) curve and each named outlier, the page\'s', worst, 0, 1e-7)
    bands = [t for t in P['tr'] if t.get('fill') == 'toself']
    ok = 0.0
    for t in bands:
        ys = [v for v in t['y'] if v is not None]
        best = min((max(abs(max(ys) - max(v[1] for v in p)), abs(min(ys) - min(v[1] for v in p))) for c in a['polys'] for p in c['paths']), default=float('inf'))
        ok = max(ok, best)
    check.near(f'{tag}: its regions reach as far as the page\'s', ok, 0, 1e-7)
    more = [n for n in named if n.endswith('more outliers')]
    check(f'{tag}: the legend, the page\'s', F['legend'], [n for n in P['legend'] if n != 'Curves' or 'Curves' in lines])
    if more:
        dots = [L for L in a['lines'] if L['ls'] == ':']
        check(f'{tag}: the other outliers dotted', len(dots), int(more[0].split()[0]))


# [platform, roles, options, options by column set after it opens (column|option), the check, the code's variables it reads]
PLAT_CODE_CASES = [
    ('scattermatrix', {'y': ['x', 'y', 'z'], 'group': ['g']}, {'ellipses': True, 'fit': True, 'hist': True}, {}, plat_matrix, []),
    ('scattermatrix', {'y': ['x', 'y', 'z']}, {'format': 'square', 'nonpar': True, 'shaded': True, 'ellipses': True}, {}, plat_matrix, []),
    ('scattermatrix', {'y': ['x', 'y'], 'x': ['z', 'pop']}, {'fit': True}, {}, plat_matrix, []),
    ('scatter3d', {'y': ['x', 'y', 'z'], 'color': ['g']}, {}, {}, lambda *a: plat_scatter3d(*a, levels=('p', 'q')), []),
    ('scatter3d', {'y': ['x', 'y', 'z'], 'color': ['pop']}, {'drop': True}, {}, plat_scatter3d, []),
    ('contour', {'y': ['z'], 'x': ['x', 'y']}, {}, {}, plat_contour, ['gz']),
    ('contour', {'y': ['z'], 'x': ['x', 'y']}, {}, {'z|fill': True, 'z|labels': True, 'z|theme': 'spectral', 'z|method': 'cubic'}, plat_contour, ['gz']),
    ('surface', {'y': ['z'], 'x': ['x', 'y']}, {}, {}, plat_surface, ['gz']),
    ('surface', {'y': ['z'], 'x': ['x', 'y']}, {}, {'z|theme': 'viridis', 'z|contours': True}, plat_surface, ['gz']),
    ('bubble', {'y': ['y'], 'x': ['x'], 'id': ['country'], 'time': ['year'], 'size': ['pop']}, {}, {}, plat_bubble, []),
    ('bubble', {'y': ['y'], 'x': ['x'], 'id': ['country'], 'color': ['pop']}, {'label': True}, {}, plat_bubble, []),
    ('parallel', {'y': ['x', 'y', 'z', 'pop'], 'x': ['g']}, {}, {}, plat_parallel, []),
    ('parallel', {'y': ['x', 'y', 'z']}, {'scale': 'std'}, {}, plat_parallel, []),
    ('cellplot', {'y': ['x', 'z', 'g']}, {}, {}, plat_cell, ['Z']),
    ('cellplot', {'y': ['x', 'z']}, {'uniform': True, 'center': True}, {}, plat_cell, ['Z']),
    ('ternary', {'y': ['A', 'B', 'C']}, {}, {}, plat_ternary, []),
    ('ternary', {'y': ['A', 'B', 'C'], 'color': ['g']}, {}, {}, plat_ternary, []),
    ('treemap', {'x': ['country', 'g'], 'size': ['pop']}, {}, {}, plat_treemap, []),
    ('treemap', {'x': ['country'], 'color': ['z']}, {}, {}, plat_treemap, []),
    ('chart', {'y': ['pop'], 'x': ['country']}, {'stat': 'mean', 'kind': 'bar'}, {}, plat_chart, []),
    ('chart', {'y': ['pop'], 'x': ['country']}, {'stat': 'max', 'kind': 'pie'}, {}, plat_chart, []),
    ('chart', {'y': ['pop', 'z'], 'x': ['country', 'g']}, {'kind': 'line', 'interval': 'se', 'stat': 'mean'}, {}, plat_chart, []),
    ('chart', {'x': ['country']}, {'kind': 'bar', 'stat': 'n', 'horizontal': True}, {}, plat_chart, []),
    ('overlay', {'y': ['z', 'pop'], 'x': ['x']}, {}, {}, plat_overlay, []),
    ('overlay', {'y': ['z', 'pop'], 'x': ['x'], 'group': ['g']}, {'overlayY': False}, {'pop|step': True, 'z|needle': True}, plat_overlay, []),
]
# the Functional Data Plot on the table of curves: every view, and By
FD_CODE_CASES = [
    ({'y': [f't{j}' for j in range(16)], 'id': ['name']}, {'fdHdr': True, 'fdRainbow': True}),
    ({'y': [f't{j}' for j in range(16)], 'by': ['grp']}, {'fdRule': 'sungenton'}),
]


async def main():
    page = await open_page(f'{BASE}/smui.html?example=students')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "graph").map(f => f.error)')
    check('graph.py imports in Pyodide', failed, [])
    names = await page.ev('SM.engine.names.filter(n => n.startsWith("graph."))')
    check('the graph functions are registered', sorted(names), ['graph.bean', 'graph.chisq', 'graph.code', 'graph.density', 'graph.ellipse', 'graph.fbox', 'graph.fit', 'graph.hdr', 'graph.interp', 'graph.kde1', 'graph.smoother', 'graph.summary'])
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
    check('the drop zones, Map Shape among them', sorted(r['zones']), sorted(['X', 'Y', 'Group X', 'Group Y', 'Wrap', 'Overlay', 'Color', 'Size', 'Freq', 'Map Shape']))
    check('the element palette, with statsmodels\' Bean, and Map Shapes', r['palette'], ['Points', 'Smoother', 'Line of Fit', 'Ellipse', 'Contour', 'Line', 'Bar', 'Area', 'Box Plot', 'Bean', 'Histogram', 'Heatmap', 'Mosaic', 'Caption Box', 'Pie', 'Map Shapes'])
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
    check('... every zone explained', [c[0] for c in r['main']['choices']['Zones']], ['X, Y', 'Group X, Group Y', 'Wrap', 'Overlay', 'Color', 'Size', 'Freq', 'Map Shape'])
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
    check('with no builder on show, the (i) explains every element\'s properties (16 elements, Map Shapes among them)', r['away'], 16)
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
    WALLS = '''(async () => { const [rep, p] = await lastPlot(); const sc = p.userLayout.scene; const m = /ax\\.scatter\\([^\\n]*\\bs=([0-9.e+-]+)/.exec(rep.pythonScript());
      const ms = p.traces[0].marker.size; return { walls: ['xaxis', 'yaxis', 'zaxis'].map((k) => [sc[k].showbackground, String(sc[k].backgroundcolor).replace(/\\s+/g, '')]), size: Array.isArray(ms) ? ms[0] : ms, s: m ? Number(m[1]) : null }; })()'''
    r = await page.ev(WALLS)
    check('scatter 3D in the light theme: the three walls tinted, so the points stand out against them', r['walls'], [[True, '#f3eee8']] * 3)
    check('scatter 3D: points of 4.5 px for its 240 rows (WebGL draws them small), and the code\'s the same (s = (4.5 × 0.72)²)', (r['size'], r['s']), (4.5, 10.5))
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(0.4)
    await run('scatter3d', {'y': ['x', 'y', 'z'], 'color': ['g']})
    r = await page.ev(WALLS)
    check('scatter 3D in the dark theme: the walls open (Plotly\'s 3-D walls take no transparency)', r['walls'], [[False, 'rgba(0,0,0,0)']] * 3)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await asyncio.sleep(0.4)
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
      const code = rep.codeBlocks().map((d) => d.querySelector('code').textContent);
      return { tops, n: tb.length, worst: Math.max(...ref.map((v, i) => Math.abs(v - got[i]))), code: ['A', 'B'].map((v) => code.filter((c) => c.includes(`df = df[df["grp"] == "${v}"]`)).length) };
    })()''')
    check('By: a Functional Data Plot for each group', (r['tops'], r['n']), (['Functional Data Plot grp=A', 'Functional Data Plot grp=B'], 2))
    check.near('By: the depths within the group', r['worst'], 0.0, 1e-12)
    check('By: each group\'s graph has its Python, on the group\'s rows', r['code'], [1, 1])
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

    # ---- the Python under each graph draws that graph: each block run in the page's Python, its figure against the Plotly graph
    for js in (GRAPHS_JS, GB_JS, OTHERS_JS, OPTS_JS):
        await page.ev(js)
    check('the seeded table for the code of the graphs', await page.ev(CODE_TABLE), 150)
    await page.ev('window._rep0 = window._rep; window._rep = window._crep;')   # gbSet and _gb work on _rep
    for what, zones, els, props, *state in GB_CODE_CASES:
        tag = f"Graph Builder's code ({what})"
        state = dict(state[0]) if state else {}
        excluded = state.pop('excluded', None)   # rows the report leaves out, for this graph
        if excluded:   # (the report runs again on the included rows)
            await page.ev(f'rerun(() => _crep.table.setState({json.dumps(excluded)}, "excluded", true))', timeout=300)
        G = await page.ev(f'''(async () => {{ await gbSet({json.dumps(zones)}, {json.dumps(els)}, {json.dumps(props)}, {json.dumps(state)});
          return await __gbq(_crep); }})()''', timeout=300)
        code = G.get('code') if isinstance(G, dict) else None
        check(f'{tag}: a code block right under the graph, ending in plt.show()', code.rstrip().split('\n')[-1] if code else G, 'plt.show()')
        if excluded:
            await page.ev(f'rerun(() => _crep.table.setState({json.dumps(excluded)}, "excluded", false))', timeout=300)
            check(f'{tag}: the code leaves them out as the report does', f'df = df.drop(index={excluded})   # the rows the report leaves out' in (code or ''), True)
        if not code:
            continue
        out = await page.ev(f'__gr.run({json.dumps(page_probe_more(code, ["inner"]))}, _crep.table)', timeout=300)
        R, err = more_from_outputs(out.get('outputs') if isinstance(out, dict) else None)
        check_gb(check, tag, G, R, err)
    # Packed jitter packs up to 20000 points in a panel; with more the page (and its code) jitters them at random
    n = await page.ev('''(async () => {
      const R = SM.util.rng('many packed'); const n = 20001, lv = [], y = [];
      for (let i = 0; i < n; i++) { lv.push(i % 3 ? 'b' : 'a'); y.push(R.normal(0, 1)); }
      const t = new SM.Table({ name: 'Many packed', columns: [{ name: 'lv', dataType: 'character', values: lv }, { name: 'y', values: y }] });
      SM.app.addTable(t);
      const rep = SM.app.openReport(SM.platforms.get('graphbuilder'), { roles: {}, options: {} }, t);
      await new Promise((res) => rep.on('done', res));
      window._rep = rep;
      await gbSet({ x: ['lv'], y: ['y'] }, ['points'], { points: { jitter: 'packed' } });
      return t.nrows; })()''', timeout=300)
    G = await page.ev('__gbq(_rep)', timeout=300)
    # (too many points for the probe's output: the code's figure compared with the page's points in the page's Python)
    want = sorted([a, b] for t in G['traces'] if t['el'] == 'points' and t['mode'] == 'markers' and not t['overlay'] for a, b in zip(t['x'], t['y']))
    probe = strip_show(G['code']) + f'''
import json as _json
import numpy as _np
_got = _np.array(sorted(tuple(p) for ax in plt.gcf().axes for c in ax.collections for p in c.get_offsets()))
_want = _np.array({json.dumps(want)})
print("SMUI-POINTS " + _json.dumps({{"n": len(_got), "gap": float(_np.max(_np.abs(_got - _want))) if _got.shape == _want.shape else None}}))
'''
    out = await page.ev(f'__gr.run({json.dumps(probe)}, _rep.table)', timeout=300)
    text = ''.join(o.get('text', '') for o in (out.get('outputs') or []) if o.get('type') == 'stream') if isinstance(out, dict) else ''
    got = next((json.loads(q[len('SMUI-POINTS '):]) for q in text.split('\n') if q.startswith('SMUI-POINTS ')), None)
    check(f"Graph Builder's code: Packed jitter of {n} points, one panel: at random as the page (it packs up to 20000), every point where the page draws it",
          (got or {}).get('n') == n and (got or {}).get('gap') is not None and got['gap'] < 1e-9, True)
    await page.ev('(() => { const big = _rep; window._rep = window._crep; SM.app.closeReport(big); SM.app.closeTable(big.table); })()')
    r = await page.ev('''(() => { const s = _crep.pythonScript(), b = _crep.codeBlocks();
      return { blocks: b.length, n: _crep.pyCode.length, same: _crep.pyCode[0] === b[0].querySelector('code').textContent, has: s.includes(_crep.pyCode[0]), prints: /\\bprint\\(/.test(s) }; })()''')
    check("Graph Builder's Save Python Script: the code under the graph, and no block that prints numbers", r, {'blocks': 1, 'n': 1, 'same': True, 'has': True, 'prints': False})
    await page.ev('window._rep = window._rep0; SM.app.showTab(SM.app.tabOf(_rep));')
    # the other platforms, on the seeded table of coordinates, IDs and times, then on the curves
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'Graph data')))")
    for pid, roles, opts, later, fn, names in PLAT_CODE_CASES:
        what = f'{pid} ({"; ".join(f"{k}: {chr(38).join(v)}" for k, v in roles.items())}{"; " + ", ".join(f"{k} {v}" for k, v in {**opts, **later}.items()) if opts or later else ""})'
        res = await page.ev(open_report_js(pid, roles, opts))
        if res['errors']:
            check(f'{what}: opens without errors', res['errors'], [])
            continue
        if later:
            await page.ev(f'__optRun({json.dumps(later)})')
        graphs = await page.ev('__oq()', timeout=300)
        for P in graphs:
            tag = f'{what}: {P["title"]}'
            check(f'{tag}: a code block right under the graph, ending in plt.show()', P['code'].rstrip().split('\n')[-1] if P['code'] else None, 'plt.show()')
            if not P['code']:
                continue
            out = await page.ev(f'__gr.run({json.dumps(page_probe_more(P["code"], names))}, SM.app.reports[SM.app.reports.length - 1].table)', timeout=300)
            R, err = more_from_outputs(out.get('outputs') if isinstance(out, dict) else None)
            fn(check, tag, P, R, err)
        n = await page.ev('SM.app.reports[SM.app.reports.length - 1].pyCode.length')
        check(f'{what}: Save Python Script: the graphs\' code, a block each', n, len(graphs))
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'FD test')))")
    for roles, opts in FD_CODE_CASES:
        res = await page.ev(open_report_js('functional', roles, opts))
        check(f'functional {json.dumps(opts)}: opens without errors', res['errors'], [])
        xs = await page.ev('fdState(SM.app.reports[SM.app.reports.length - 1]).F.x')
        graphs = await page.ev('__oq()', timeout=300)
        for k, P in enumerate(graphs):
            tag = f'functional{f" By grp, graph {k + 1}" if "by" in roles else ""}: {P["title"]}'
            check(f'{tag}: a code block right under the graph, ending in plt.show()', P['code'].rstrip().split('\n')[-1] if P['code'] else None, 'plt.show()')
            if not P['code']:
                continue
            out = await page.ev(f'__gr.run({json.dumps(page_probe_more(P["code"], []))}, SM.app.reports[SM.app.reports.length - 1].table)', timeout=300)
            R, err = more_from_outputs(out.get('outputs') if isinstance(out, dict) else None)
            plat_functional(check, tag, P, R, err, xs)
    await page.ev('SM.app.showTab(SM.app.tabOf(_rep))')

    await wp6(page)

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


# ---- WP6: Axis Settings, Levels, Order By, Marker Size and Transparency, maps, transform columns ------------------
# The page's helpers: an axis's drag box (where its tick labels are), the Axis Settings window's fields, menus.
WP6_JS = r"""
window.__ax = {
  at(p, which, sub = 'xy') { const r = p.box.querySelector(`.draglayer .${sub} rect.${which}drag`); if (!r) return null; const b = r.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; },
  inPlot(p) { const r = p.box.querySelector('.draglayer .xy rect.nsewdrag'); const b = r.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; },
  dialog() { return [...document.querySelectorAll('.sm-dialog')].pop() || null; },
  set(root, key, value) { const i = root.querySelector(`[data-ax="${key}"]`); if (!i) return false; if (i.type === 'checkbox') i.checked = !!value; else i.value = value; i.dispatchEvent(new Event('change', { bubbles: true })); return true; },
  button(d, label) { const b = [...d.querySelectorAll('.sm-dialog-foot button')].find((x) => x.textContent === label); if (b) b.click(); return !!b; },
  menus() { return [...document.querySelectorAll('.sm-menu')].map((m) => [...m.querySelectorAll('button')].map((b) => b.textContent)); },
  item(label, level) { const ms = [...document.querySelectorAll('.sm-menu')]; const m = level == null ? ms[ms.length - 1] : ms[level]; const b = m && [...m.querySelectorAll('button')].find((x) => x.textContent.replace(/^✓/, '') === label); if (b) b.click(); return !!b; },
  hover(label, level = 0) { const m = [...document.querySelectorAll('.sm-menu')][level]; const b = m && [...m.querySelectorAll('button')].find((x) => x.textContent.replace(/^✓/, '') === label); if (b) b.dispatchEvent(new MouseEvent('mouseenter')); return !!b; },
  axis(p, name = 'yaxis') { const A = p.box._fullLayout && p.box._fullLayout[name]; return A ? { type: A.type, range: A.range.slice(), ticks: (A._vals || []).map((v) => v.x), text: (A._vals || []).map((v) => v.text) } : null; },
  code(p) { const n = p.box.nextElementSibling; return n && n.matches('details.sm-code') ? n.querySelector('code').textContent : null; },
  // until the report has run again after a change to its table (Graph Builder follows it, 250 ms later) and is idle
  async calm(rep) { await new Promise((r) => setTimeout(r, 450)); for (let i = 0; i < 400 && rep.body.classList.contains('is-running'); i++) await new Promise((r) => setTimeout(r, 25)); const b = SM.platforms.get('graphbuilder').builder(rep); if (b) await b.idle(); await new Promise((r) => setTimeout(r, 100)); },
  // Graph Builder's graph as it is now (a change to the table makes a new one): an axis's drag box, or the plot's middle
  async gbAt(which) { await __ax.calm(_rep); const p = _gb.plot(); p.box.scrollIntoView({ block: 'center' }); await drawn(p); await settle(); window._gp = p; return which ? __ax.at(p, which) : __ax.inPlot(p); },
  async redrawn(rep) { for (let i = 0; i < 200 && rep.body.classList.contains('is-running'); i++) await new Promise((r) => setTimeout(r, 25)); await new Promise((r) => setTimeout(r, 120)); const p = rep.plots[0]; if (p && !p.drawn) { p.box.scrollIntoView({ block: 'center' }); await drawn(p); } return p; },
};
"""


async def dbl(page, x, y):
    """A real double-click: two presses and releases, as a mouse makes them."""
    await page.mouse('mouseMoved', x, y)
    for n in (1, 2):
        await page.mouse('mousePressed', x, y, clicks=n)
        await page.mouse('mouseReleased', x, y, clicks=n)
    await asyncio.sleep(0.5)


async def rclick(page, x, y):
    await page.mouse('mouseMoved', x, y)
    await page.mouse('mousePressed', x, y, button='right')
    await page.mouse('mouseReleased', x, y, button='right')
    await asyncio.sleep(0.25)


def jmp_q(s, p):
    """JMP's quantile of sorted values, the (n + 1)p-th, interpolated."""
    n = len(s)
    h = (n + 1) * p
    if h <= 1:
        return s[0]
    if h >= n:
        return s[-1]
    k = int(math.floor(h))
    return s[k - 1] + (h - k) * (s[k] - s[k - 1])


def bin_cuts(v, n=5, method='quantile'):
    """Make Binning Column's cuts from their definitions: JMP's quantiles, or bins of one round width (1, 2, 2.5, 5 or 10
    times a power of ten, the nearest to the range over n) from a whole multiple of it; a bin holds its lower cut."""
    s = sorted(v)
    lo, hi = s[0], s[-1]
    if method == 'quantile':
        cuts = [jmp_q(s, i / n) for i in range(1, n)]
    else:
        raw = (hi - lo) / n
        p = 10 ** math.floor(math.log10(raw))
        size = min((m * p for m in (1, 2, 2.5, 5, 10)), key=lambda q: abs(math.log(q / raw)))
        start = math.floor(lo / size) * size
        cuts, x = [], start + (size if start <= lo else 0)
        while x <= hi and len(cuts) < 1000:
            cuts.append(float(f'{x:.12g}'))
            x += size
    cuts = [c for c in sorted({float(f'{c:.12g}') for c in cuts}) if lo < c <= hi]
    if cuts and cuts[-1] == hi:
        cuts.pop()
    return cuts, lo, hi


def page_fmt(v):
    """The page's fmt() of a number (7 significant digits, integers as integers), with - for minus."""
    if float(v).is_integer() and abs(v) < 1e15:
        return str(int(v))
    t = f'{v:.7g}'
    if 'e' not in t and '.' in t:
        t = t.rstrip('0').rstrip('.')
    return t


def bin_labels(cuts, lo, hi):
    e = [lo] + cuts + [hi]
    return [f'{page_fmt(e[k])} - {page_fmt(e[k + 1])}' for k in range(len(e) - 1)]


async def wp6(page):
    await page.ev(WP6_JS)
    # ---- Axis Settings on any report's graph: Fit Y by X's bivariate plot, by real double-clicks and right-clicks
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'Students')))")
    res = await page.ev(open_report_js('fitybyx', {'y': ['weight (kg)'], 'x': ['height (cm)']}))
    check('Axis Settings: a Fit Y by X report to try them on', res['errors'], [])
    await page.ev('(async () => { window._fr = SM.app.reports[SM.app.reports.length - 1]; SM.app.showTab(SM.app.tabOf(_fr)); window._fp = _fr.plots[0]; _fp.box.scrollIntoView({ block: "center" }); await drawn(_fp); await settle(); })()')
    before = await page.ev('__ax.axis(_fp)')
    xy = await page.ev('__ax.at(_fp, "ns")')
    await dbl(page, *xy)
    r = await page.ev('(() => { const d = __ax.dialog(); return d ? { title: d.querySelector("h2").textContent, range: __ax.axis(_fp).range, fields: [...d.querySelectorAll("[data-ax]")].map(i => i.dataset.ax) } : null; })()')
    check('Axis Settings: a double-click on an axis opens its window, as in JMP', (r or {}).get('title'), 'Y Axis Settings')
    check('... and leaves the axis where it was (Plotly would have rescaled it)', [round(v, 9) for v in (r or {}).get('range', [])], [round(v, 9) for v in before['range']])
    check('... with the scale, minimum, maximum, increment, order and reference lines', (r or {}).get('fields'), ['scale', 'min', 'max', 'inc', 'reverse', 'addref'])
    r = await page.ev(r"""(async () => { const d = __ax.dialog();
      __ax.set(d, 'min', '90'); __ax.set(d, 'max', '40');
      __ax.button(d, 'OK'); await settle();
      const msg = d.querySelector('.sm-launch-msg').textContent, open = d.isConnected;
      __ax.set(d, 'scale', 'log'); __ax.set(d, 'min', '0'); __ax.set(d, 'max', '90');
      __ax.button(d, 'OK'); await settle();
      return { msg, open, msg2: d.querySelector('.sm-launch-msg').textContent, open2: d.isConnected }; })()""")
    check('Axis Settings: a minimum above the maximum is refused, the window stays', (r['msg'], r['open']), ('The minimum must be below the maximum', True))
    check('... and on a log scale, a minimum of 0', (r['msg2'], r['open2']), ('On a log scale the minimum and the maximum must be above 0', True))
    r = await page.ev(r"""(async () => { const d = __ax.dialog();
      __ax.set(d, 'scale', 'log'); __ax.set(d, 'min', '40'); __ax.set(d, 'max', '90'); __ax.set(d, 'inc', '1.25');
      const add = d.querySelector('[data-ax="addref"]'); add.click(); add.click();
      const R = d.querySelectorAll('.sm-ax-ref');
      __ax.set(R[0], 'ref', '60'); __ax.set(R[0], 'reflabel', 'sixty'); __ax.set(R[0], 'refcolor', 'red'); __ax.set(R[0], 'refdash', 'dash');
      __ax.set(R[1], 'ref', '70'); __ax.set(R[1], 'refto', '80'); __ax.set(R[1], 'refcolor', 'blue');
      const done = new Promise((res) => _fr.on('done', res));
      __ax.button(d, 'OK'); await done;
      const p = await __ax.redrawn(_fr); window._fp = p;
      const fl = p.box._fullLayout;
      return { spec: Object.values(_fr.spec.options.axisSettings || {}), keys: Object.keys(_fr.spec.options.axisSettings || {}).length, A: __ax.axis(p),
        shapes: fl.shapes.map((q) => ({ type: q.type, y0: q.y0, y1: q.y1, xref: q.xref, yref: q.yref, color: q.type === 'line' ? q.line.color : q.fillcolor, dash: q.line.dash })),
        ann: fl.annotations.map((a) => a.text), code: __ax.code(p), script: _fr.pythonScript() }; })()""")
    want_ticks = [math.log10(40 * 1.25 ** k) for k in range(4)]
    check('Axis Settings kept in the report\'s spec, by graph and axis', (r['keys'], r['spec'][0] if r['spec'] else None),
          (1, {'yaxis': {'log': True, 'min': 40, 'max': 90, 'inc': 1.25, 'refs': [{'value': 60, 'to': None, 'label': 'sixty', 'color': 'red', 'dash': 'dash'}, {'value': 70, 'to': 80, 'label': '', 'color': 'blue', 'dash': 'solid'}]}}))
    check('Axis Settings drawn: a log axis from 40 to 90, a tick every × 1.25 from the minimum', (r['A']['type'], [round(v, 9) for v in r['A']['range']], [round(v, 9) for v in r['A']['ticks']]),
          ('log', [round(math.log10(40), 9), round(math.log10(90), 9)], [round(v, 9) for v in want_ticks]))
    check('... the reference line at 60 across the plot, red and dashed, labelled; the range 70 to 80 shaded blue', (sorted((q['type'], round(q['y0'], 9), round(q['y1'], 9), q['xref'], q['yref'], q['color'], q.get('dash') if q['type'] == 'line' else None) for q in r['shapes']), 'sixty' in r['ann']),
          (sorted([('line', 60, 60, 'x domain', 'y', '#b0413e', 'dash'), ('rect', 70, 80, 'x domain', 'y', 'rgba(31, 78, 121, 0.16)', None)]), True))
    code = r['code'] or ''
    check('... and the graph\'s code sets the same axis before its plt.show()', all(t in code for t in ('target.set_yscale("log")', 'target.set_ylim(40, 90)', 'target.set_yticks(ticks_every(', 'target.axhline(60, color="#b0413e"', 'target.axhspan(70, 80, color="#1f4e79"')) and code.rstrip().endswith('plt.show()'), True)
    check('... as does Save Python Script', 'target.set_ylim(40, 90)' in r['script'], True)
    out = await page.ev(f'__gr.run({json.dumps(page_probe_more(code, []))}, _fr.table)', timeout=300)
    R, err = more_from_outputs(out.get('outputs') if isinstance(out, dict) else None)
    check('... which runs in the page\'s Python', err, None)
    if R:
        A = R['figures'][0]['axes'][0]
        spans = [[round(b['y'], 6), round(b['y'] + b['h'], 6)] for b in A['bars'] if (b['fc'] or '').startswith('#1f4e79')] + [sorted({round(q[1], 6) for q in P['xy']}) for P in A['polygons'] if (P['fc'] or '').startswith('#1f4e79')]
        check('... and draws the axis the graph has: log, 40 to 90, its ticks, the line and the range', (A['yscale'], [round(v, 6) for v in A['ylim']], [round(v, 6) for v in A['yticks']],
                                                                                                        [(L['color'][:7], L['ls']) for L in A['lines'] if L['y'] == [60.0, 60.0]], spans, any(a['s'] == 'sixty' for a in A['annotations'])),
              ('log', [40.0, 90.0], [40.0, 50.0, 62.5, 78.125], [('#b0413e', '--')], [[70.0, 80.0]], True))
    # the axis's right-click menu, Reverse Order, Redo, a saved project, Remove
    xy = await page.ev('__ax.at(_fp, "ns")')
    await rclick(page, *xy)
    items = await page.ev('__ax.menus()')
    check('Axis Settings: a right-click on the axis gives its menu', items[0] if items else None, ['Axis Settings…', '✓Log Scale', 'Reverse Order', 'Add Reference Line…', 'Remove Axis Settings'])
    r = await page.ev(r"""(async () => { const done = new Promise((res) => _fr.on('done', res)); __ax.item('Reverse Order'); await done; const p = await __ax.redrawn(_fr); window._fp = p;
      const A = __ax.axis(p);
      const d2 = new Promise((res) => _fr.on('done', res)); _fr.run(); await d2; const q = await __ax.redrawn(_fr);
      return { A, code: __ax.code(p), redo: __ax.axis(q) }; })()""")
    check('... Reverse Order: the axis runs from 90 down to 40', [round(v, 9) for v in r['A']['range']], [round(math.log10(90), 9), round(math.log10(40), 9)])
    check('... its code turns the axis round too', 'target.invert_yaxis()' in (r['code'] or '') and 'target.set_ylim(90, 40)' in (r['code'] or ''), True)
    check('Axis Settings: Redo keeps them', [round(v, 9) for v in r['redo']['range']], [round(math.log10(90), 9), round(math.log10(40), 9)])
    r = await page.ev(r"""(async () => {
      const t = _fr.table;
      const proj = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [_fr.toJSON()] };
      SM.app.loadProject(JSON.parse(JSON.stringify(proj)));
      const rep = SM.app.reports[SM.app.reports.length - 1];
      SM.app.showTab(SM.app.tabOf(rep));
      await new Promise((res) => { if (rep.plots.length && !rep.body.classList.contains('is-running')) res(); else rep.on('done', res); });
      const p = await __ax.redrawn(rep);
      const A = __ax.axis(p);
      SM.app.closeReport(rep); SM.app.closeTable(rep.table); SM.app.showTab(SM.app.tabOf(_fr));
      return A; })()""")
    check('Axis Settings: a saved project opens with them (log, reversed, 90 to 40)', (r['type'], [round(v, 9) for v in r['range']]), ('log', [round(math.log10(90), 9), round(math.log10(40), 9)]))
    await page.ev('(async () => { await __ax.redrawn(_fr); window._fp = _fr.plots[0]; _fp.box.scrollIntoView({ block: "center" }); await settle(); })()')
    xy = await page.ev('__ax.at(_fp, "ns")')
    await rclick(page, *xy)
    r = await page.ev(r"""(async () => { const done = new Promise((res) => _fr.on('done', res)); __ax.item('Remove Axis Settings'); await done; const p = await __ax.redrawn(_fr); window._fp = p;
      return { A: __ax.axis(p), spec: _fr.spec.options.axisSettings || null, code: __ax.code(p) }; })()""")
    check('Axis Settings: Remove Axis Settings, and the axis is the report\'s again', (r['A']['type'], [round(v, 9) for v in r['A']['range']], r['spec'], 'Axis Settings' in (r['code'] or '')), ('linear', [round(v, 9) for v in before['range']], None, False))
    # a double-click in the plot itself stays Plotly's; Cancel changes nothing
    await page.ev('(async () => { _fp.box.scrollIntoView({ block: "center" }); await settle(); })()')
    xy = await page.ev('__ax.inPlot(_fp)')
    await dbl(page, *xy)
    check('Axis Settings: a double-click in the plot (not on an axis) opens no window', await page.ev('!!__ax.dialog()'), False)
    xy = await page.ev('__ax.at(_fp, "ew")')
    await dbl(page, *xy)
    r = await page.ev(r"""(async () => { const d = __ax.dialog(); const t = d ? d.querySelector('h2').textContent : null; if (d) { __ax.set(d, 'min', '150'); __ax.button(d, 'Cancel'); } await settle(); return { t, spec: _fr.spec.options.axisSettings || null, x: __ax.axis(_fp, 'xaxis').range }; })()""")
    xb = await page.ev('__ax.axis(_fp, "xaxis").range')
    check('Axis Settings of X by a double-click; Cancel leaves the axis and the report as they were', (r['t'], r['spec'], [round(v, 6) for v in r['x']]), ('X Axis Settings', None, [round(v, 6) for v in xb]))
    # the red triangle's Axis Settings: every numeric axis of the report's graphs
    r = await page.ev(r"""(async () => { _fr.body.querySelector('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu').click(); await settle();
      __ax.hover('Axis Settings'); await settle(); const m = __ax.menus(); const got = m[1] || null;
      if (got) __ax.item(got[1], 1); await settle(); const d = __ax.dialog(); const t = d ? d.querySelector('h2').textContent : null; if (d) __ax.button(d, 'Cancel'); SM.ui.closeMenus(); await settle(); return { got, t }; })()""")
    check('Axis Settings in the red triangle: the graph\'s axes by name, for the keyboard and a phone', (r['got'], r['t']), (['X Axis: height (cm)…', 'Y Axis: weight (kg)…'], 'Y Axis Settings'))
    # By groups: the same graph of every group takes them
    res = await page.ev(open_report_js('fitybyx', {'y': ['weight (kg)'], 'x': ['height (cm)'], 'by': ['sex']}))
    r = await page.ev(r"""(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; SM.app.showTab(SM.app.tabOf(rep)); await __ax.redrawn(rep);
      const p = rep.plots[0]; p.box.scrollIntoView({ block: 'center' }); await drawn(p); await settle();
      const done = new Promise((res) => rep.on('done', res)); SM.axis.put(p, 'yaxis', { min: 20, max: 100 }); await done;
      for (const q of rep.plots) { q.box.scrollIntoView({ block: 'center' }); await drawn(q); }
      const out = rep.plots.map((q) => __ax.axis(q).range); SM.app.closeReport(rep); SM.app.showTab(SM.app.tabOf(_fr)); return out; })()""")
    check('Axis Settings with By: every group\'s graph from 20 to 100', r, [[20, 100], [20, 100]])

    # ---- Graph Builder: Axis Settings go with the column on the axis, on every panel, in its code
    r = await page.ev(r"""(async () => {
      const t = SM.app.tables.find((x) => x.name === 'Students');
      const rep = SM.app.openReport(SM.platforms.get('graphbuilder'), { roles: {}, options: {} }, t);
      await new Promise((res) => rep.on('done', res));
      window._rep6 = rep; window._rep0b = window._rep; window._rep = rep; SM.app.showTab(SM.app.tabOf(rep));
      const p = await gbSet({ x: ['height (cm)'], y: ['weight (kg)'], groupX: ['sex'] }, ['points']);
      p.box.scrollIntoView({ block: 'center' }); await drawn(p); await settle(); window._gp = p;
      return Object.keys(p.box._fullLayout).filter((k) => /^yaxis/.test(k)); })()""")
    check('Graph Builder with Group X: a Y axis for each panel', r, ['yaxis', 'yaxis2'])
    xy = await page.ev('__ax.gbAt("ns")')
    await dbl(page, *xy)
    r = await page.ev(r"""(async () => { const d = __ax.dialog(); if (!d) return null;
      __ax.set(d, 'min', '30'); __ax.set(d, 'max', '90'); __ax.set(d, 'inc', '15'); d.querySelector('[data-ax="addref"]').click();
      const R = d.querySelector('.sm-ax-ref'); __ax.set(R, 'ref', '60'); __ax.set(R, 'refto', '70'); __ax.set(R, 'reflabel', 'band');
      __ax.button(d, 'OK'); await _gb.idle(); await settle();
      const p = _gb.plot(); p.box.scrollIntoView({ block: 'center' }); await drawn(p); window._gp = p;
      let code = null; for (let i = 0; i < 80 && !code; i++) { code = __ax.code(p); if (!code) await settle(); }
      const fl = p.box._fullLayout;
      return { axes: _gb.state().axes, A: [__ax.axis(p, 'yaxis'), __ax.axis(p, 'yaxis2')].map((a) => [a.range, a.ticks]), rects: fl.shapes.filter((q) => q.type === 'rect').map((q) => [q.yref, q.y0, q.y1]), code, spec: _rep.spec.options.axisSettings || null }; })()""")
    check('Graph Builder: the window\'s settings kept by the column on the axis, in the builder\'s state', (r or {}).get('axes'), {'y:weight (kg)': {'min': 30, 'max': 90, 'inc': 15, 'refs': [{'value': 60, 'to': 70, 'label': 'band', 'color': 'gray', 'dash': 'solid'}]}})
    check('Graph Builder: every panel\'s Y from 30 to 90, a tick every 15, the band on each', (r['A'], sorted(r['rects'])), ([[[30, 90], [30, 45, 60, 75, 90]]] * 2, [['y', 60, 70], ['y2', 60, 70]]))
    check('... not in the report\'s own axis settings (the builder keeps them)', r['spec'], None)
    out = await page.ev(f'__gr.run({json.dumps(page_probe_more(r["code"] or "", []))}, _rep.table)', timeout=300)
    R, err = more_from_outputs(out.get('outputs') if isinstance(out, dict) else None)
    AX = [A for A in (R['figures'][0]['axes'] if R else []) if not A['colorbar']]
    check('... and its code (graph.code) draws them on every panel', (err, [(A['ylim'], A['yticks']) for A in AX]), (None, [([30.0, 90.0], [30.0, 45.0, 60.0, 75.0, 90.0])] * 2))
    r = await page.ev(r"""(async () => { const t = _rep.table;
      await _gb.update((S) => { S.zones.y = [{ id: t.col('height (cm)').id, name: 'height (cm)' }]; S.zones.x = [{ id: t.col('weight (kg)').id, name: 'weight (kg)' }]; });
      const a = __ax.axis(await drawn(_gb.plot()), 'yaxis').range;
      await _gb.update((S) => { S.zones.y = [{ id: t.col('weight (kg)').id, name: 'weight (kg)' }]; S.zones.x = [{ id: t.col('height (cm)').id, name: 'height (cm)' }]; });
      const b = __ax.axis(await drawn(_gb.plot()), 'yaxis').range; return { a, b }; })()""")
    check('Graph Builder: another column on Y has its own axis; the first one back, its settings too', (r['a'] != [30, 90], r['b']), (True, [30, 90]))
    r = await page.ev(r"""(async () => { await _gb.update((S) => { S.log = { y: true }; }); const p = await drawn(_gb.plot()); p.box.scrollIntoView({ block: 'center' }); await settle();
      SM.axis.open(p, 'yaxis'); await settle(); const d = __ax.dialog(); const was = d.querySelector('[data-ax="scale"]').value;
      __ax.set(d, 'scale', 'linear'); __ax.button(d, 'OK'); await _gb.idle(); await settle();
      return { was, log: _gb.state().log, axes: _gb.state().axes['y:weight (kg)'], type: __ax.axis(await drawn(_gb.plot()), 'yaxis').type }; })()""")
    check('Graph Builder: the zone\'s Log Scale and the window\'s Scale are one switch', (r['was'], r['log'], 'log' in (r['axes'] or {}), r['type']), ('log', {'y': False}, False, 'linear'))

    # ---- Levels of a continuous grouping column: bins as Make Binning Column cuts them; Save Transform Column
    wv = await page.ev("SM.app.tables.find((x) => x.name === 'Students').col('weight (kg)').values.filter(Number.isFinite)")
    r = await page.ev(r"""(async () => { const p = await gbSet({ x: ['age'], y: ['height (cm)'], groupX: ['weight (kg)'] }, ['points']);
      return { labels: _gb.figure().plan.gx.labels, panels: Object.keys(_gb.plot().userLayout).filter((k) => /^xaxis/.test(k)).length }; })()""")
    c5, lo_, hi_ = bin_cuts(wv, 5)
    check('Levels, automatic: five bins of about equal counts at JMP\'s quantiles, labelled by their ranges', (r['labels'], r['panels']), (bin_labels(c5, lo_, hi_), len(c5) + 1))
    xy = await page.ev(r"""(() => { const c = _rep.body.querySelector('.sm-gb-z-groupX .sm-gb-chip'); c.scrollIntoView({ block: 'center' }); const b = c.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()""")
    await rclick(page, *xy)
    r = await page.ev(r"""(async () => { const top = __ax.menus()[0]; __ax.hover('Levels'); await settle(); const sub = __ax.menus()[1];
      __ax.item('Number of Levels…', 1); await settle(); const d = [...document.querySelectorAll('.sm-dialog')].pop();
      d.querySelector('input').value = '3'; [...d.querySelectorAll('.sm-dialog-foot button')].find((b) => b.textContent === 'OK').click(); await _gb.idle(); await settle();
      return { top, sub, labels: _gb.figure().plan.gx.labels, bins: _gb.state().bins }; })()""")
    c3, lo_, hi_ = bin_cuts(wv, 3)
    check('Levels: a continuous column in a grouping zone has JMP\'s Levels in its menu', (r['top'][-1] if r['top'] else None, r['sub']), ('Levels', ['✓Automatic', 'Number of Levels…', 'Equal Counts (Quantiles)', 'Equal Width', 'Save Transform Column']))
    check('Levels: Number of Levels 3, three bins of about equal counts', (r['bins'], r['labels']), ({'weight (kg)': {'n': 3, 'method': 'quantile'}}, bin_labels(c3, lo_, hi_)))
    await rclick(page, *xy)
    r = await page.ev(r"""(async () => { __ax.hover('Levels'); await settle(); __ax.item('Equal Width', 1); await _gb.idle(); await settle(); return { labels: _gb.figure().plan.gx.labels, bins: _gb.state().bins }; })()""")
    cw, lo_, hi_ = bin_cuts(wv, 3, 'width')
    check('Levels: Equal Width, bins of one round width', (r['bins'], r['labels']), ({'weight (kg)': {'n': 3, 'method': 'width'}}, bin_labels(cw, lo_, hi_)))
    await rclick(page, *xy)
    r = await page.ev(r"""(async () => { const t = _rep.table; const n0 = t.columns.length; __ax.hover('Levels'); await settle(); __ax.item('Save Transform Column', 1); await settle(); await _gb.idle();
      const c = t.columns[t.columns.length - 1];
      const sel = (_rep.body.querySelector('.sm-gb-collist li.is-selected') || {}).textContent || null;
      await __ax.calm(_rep);
      return { n: t.columns.length - n0, name: c.name, type: c.modelingType, formula: !!c.formula, order: c.valueOrder, values: c.values, w: t.col('weight (kg)').values, sel }; })()""")
    labs = bin_labels(cw, lo_, hi_)
    want_v = [None if not (isinstance(v, (int, float)) and math.isfinite(v)) else labs[sum(1 for c in cw if v >= c)] for v in r['w']]
    check('Save Transform Column: a formula column of the bins, ordinal, in their order, selected in the list', (r['n'], r['name'], r['type'], r['formula'], r['order'], r['sel']), (1, 'weight (kg) Binned', 'ordinal', True, labs, 'weight (kg) Binned'))
    check('... each row in its bin (the lower cut in, the upper out)', r['values'] == want_v, True)

    # ---- Order By: a categorical axis's levels by a statistic of another column
    hv = await page.ev("(() => { const t = SM.app.tables.find((x) => x.name === 'Students'); return [t.col('age').values, t.col('height (cm)').values]; })()")
    ages = sorted({a for a in hv[0] if a is not None})
    mean_h = {a: sum(h for a_, h in zip(*hv) if a_ == a) / sum(1 for a_ in hv[0] if a_ == a) for a in ages}
    await page.ev("(async () => { const p = await gbSet({ x: ['age'], y: ['height (cm)'] }, ['bar']); p.box.scrollIntoView({ block: 'center' }); await drawn(p); await settle(); window._gp = p; })()")
    xy = await page.ev('__ax.gbAt("ew")')
    await rclick(page, *xy)
    r = await page.ev(r"""(async () => { const top = __ax.menus()[0]; __ax.hover('Order By'); await settle(); const sub = __ax.menus()[1];
      __ax.item('height (cm), Descending', 1); await _gb.idle(); await settle(); const p = await drawn(_gb.plot()); window._gp = p;
      let code = null; for (let i = 0; i < 80 && !code; i++) { code = __ax.code(p); if (!code) await settle(); }
      return { top, sub, ticks: p.userLayout.xaxis.ticktext, order: _gb.state().order, code }; })()""")
    check('Order By: a right-click on a categorical axis has JMP\'s Order By and Order Statistic', r['top'], ['Order By', 'Order Statistic'])
    check('... by the graph\'s numeric column, by the count, by another column, or back', r['sub'], ['height (cm), Ascending', 'height (cm), Descending', 'Count, Ascending', 'Count, Descending', 'Other Column', '✓Original Order'])
    want = [str(a) for a in sorted(ages, key=lambda a: (-mean_h[a], ages.index(a)))]
    check('Order By height, descending: the ages by their mean height', (r['order'], r['ticks']), ({'age': {'by': 'height (cm)', 'stat': 'mean', 'desc': True}}, want))
    out = await page.ev(f'__gr.run({json.dumps(page_probe_more(r["code"] or "", []))}, _rep.table)', timeout=300)
    R, err = more_from_outputs(out.get('outputs') if isinstance(out, dict) else None)
    check('... and the code sorts them so from the data', (err, [t for t in (R['figures'][0]['axes'][0]['xticklabels'] if R else []) if t]), (None, want))
    xy = await page.ev('__ax.gbAt("ew")')
    await rclick(page, *xy)
    r = await page.ev(r"""(async () => { __ax.hover('Order Statistic'); await settle(); __ax.item('Median', 1); await _gb.idle(); await settle(); return (await drawn(_gb.plot())).userLayout.xaxis.ticktext; })()""")
    med_h = {a: jmp_q(sorted(h for a_, h in zip(*hv) if a_ == a), 0.5) for a in ages}
    check('Order Statistic Median: the ages by their median height (JMP\'s quantile), descending', r, [str(a) for a in sorted(ages, key=lambda a: (-med_h[a], ages.index(a)))])
    xy = await page.ev('__ax.gbAt("ew")')
    await rclick(page, *xy)
    r = await page.ev(r"""(async () => { __ax.hover('Order By'); await settle(); __ax.item('Original Order', 1); await _gb.idle(); await settle(); return [(await drawn(_gb.plot())).userLayout.xaxis.ticktext, _gb.state().order]; })()""")
    check('Order By: Original Order puts back the table\'s', r, [[str(a) for a in ages], {}])

    # ---- Marker Size and Transparency: the red triangle, a right-click in the graph, the code, a project
    r = await page.ev(r"""(async () => { const p = await gbSet({ x: ['height (cm)'], y: ['weight (kg)'] }, ['points']); p.box.scrollIntoView({ block: 'center' }); await drawn(p);
      _rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu').click(); await settle(); __ax.hover('Marker Size'); await settle(); const sizes = __ax.menus()[1];
      __ax.item('3, Large', 1); await _gb.idle(); await settle(); const q = await drawn(_gb.plot()); q.box.scrollIntoView({ block: 'center' }); await settle(); window._gp = q;
      return { sizes, size: q.traces.find((t) => t.mode === 'markers').marker.size }; })()""")
    check('Marker Size in the red triangle: JMP\'s sizes 0 to 6', r['sizes'], ['✓Automatic', '0, Dot', '1, Small', '2, Medium', '3, Large', '4, XL', '5, XXL', '6, XXXL', 'Other…'])
    check('Marker Size 3, Large: the points 7 pixels across', r['size'], 7)
    xy = await page.ev('__ax.gbAt(null)')
    await rclick(page, *xy)
    r = await page.ev(r"""(async () => { const m = __ax.menus()[0]; __ax.hover('Transparency'); await settle(); __ax.item('0.4', 1); await _gb.idle(); await settle(); const q = await drawn(_gb.plot());
      let code = null; for (let i = 0; i < 80 && !code; i++) { code = __ax.code(q); if (!code) await settle(); }
      return { m, op: q.traces.find((t) => t.mode === 'markers').marker.opacity, marker: _gb.state().marker, code }; })()""")
    check('A right-click in the graph: Marker Size, Transparency, Background Map', r['m'], ['Marker Size', 'Transparency', 'Background Map'])
    check('Transparency 0.4: the points at opacity 0.4', (r['op'], r['marker']), (0.4, {'size': 7, 'alpha': 0.4}))
    out = await page.ev(f'__gr.run({json.dumps(page_probe_more(r["code"] or "", []))}, _rep.table)', timeout=300)
    R, err = more_from_outputs(out.get('outputs') if isinstance(out, dict) else None)
    S = R['figures'][0]['axes'][0]['scatter'][0] if R else {'sizes': [], 'colors': []}
    check('... and the code draws them so (7 pixels, 5.04 points across; alpha 0.4)', (err, sorted({round(v, 4) for v in S['sizes']}), sorted({c[-2:] for c in S['colors']})), (None, [float(f'{(7 * 0.72) ** 2:.3g}')], ['66']))

    # ---- transform columns from the builder's list (WP5's transform menu), then onto a zone
    await page.ev('SM.app.showTab(SM.app.tabOf(_rep))')
    xy = await page.ev(r"""(() => { const li = [..._rep.body.querySelectorAll('.sm-gb-collist li')].find((l) => l.textContent === 'weight (kg)'); li.scrollIntoView({ block: 'center' }); const b = li.getBoundingClientRect(); return [b.x + 30, b.y + b.height / 2]; })()""")
    await rclick(page, *xy)
    r = await page.ev(r"""(async () => { const top = __ax.menus()[0]; __ax.hover('Transform'); await settle(); const sub = __ax.menus()[1]; __ax.item('Log', 1); await settle(); await _gb.idle();
      const li = _rep.body.querySelector('.sm-gb-collist li.is-selected'); return { top, sub, sel: li ? li.textContent : null }; })()""")
    await page.ev('__ax.calm(_rep)')
    check('The column list\'s menu: the zones, then Transform, Distributional and Date Time', r['top'], ['X', 'Y', 'Group X', 'Group Y', 'Wrap', 'Overlay', 'Color', 'Size', 'Freq', 'Map Shape', 'Transform', 'Distributional', 'Date Time'])
    check('... Transform ▸ Log makes a formula column, selected in the list', r['sel'], 'Log[weight (kg)]')
    xy = await page.ev(r"""(() => { const z = _rep.body.querySelector('.sm-gb-z-color'); z.scrollIntoView({ block: 'center' }); const b = z.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()""")
    await page.click(*xy)
    await page.ev('_gb.idle()')
    r = await page.ev(r"""(async () => { await _gb.idle(); const t = _rep.table; const c = t.col('Log[weight (kg)]'); const w = t.col('weight (kg)');
      return { color: _gb.state().zones.color.map((z) => z.name), ok: c.values.every((v, i) => (Number.isFinite(w.values[i]) ? Math.abs(v - Math.log(w.values[i])) < 1e-12 : !Number.isFinite(v))), f: !!c.formula }; })()""")
    check('... and a click on a zone puts it there (Color); its values the logs of the column', (r['color'], r['ok'], r['f']), (['Log[weight (kg)]'], True, True))
    r = await page.ev(r"""(async () => { await __ax.calm(_rep); await _gb.update((S) => { S.order = { age: { by: 'height (cm)', stat: 'median', desc: false } }; S.map = 'usa'; });
      const want = _gb.state(); const t = _rep.table;
      const proj = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [_rep.toJSON()] };
      SM.app.loadProject(JSON.parse(JSON.stringify(proj)));
      const rep = SM.app.reports[SM.app.reports.length - 1]; SM.app.showTab(SM.app.tabOf(rep));
      await new Promise((res) => { if (rep.body.querySelector('.sm-gb')) res(); else rep.on('done', res); });
      const gb = rep.body.querySelector('.sm-gb')._gb; await gb.idle(); const got = gb.state();
      SM.app.closeReport(rep); SM.app.closeTable(rep.table); SM.app.showTab(SM.app.tabOf(_rep));
      await _gb.update((S) => { S.order = {}; S.map = null; });
      const pick = (S) => JSON.stringify({ axes: S.axes, bins: S.bins, order: S.order, marker: S.marker, map: S.map, shapeMode: S.shapeMode });
      return [pick(got), pick(want)]; })()""")
    check('a saved project keeps Graph Builder\'s axis settings, levels, orders, markers and map', r[0], r[1])

    # ---- maps: Map Shapes of countries (ISO codes, names) and US states, points on a Background Map; linked; their code
    MAP_TABLE = r"""(() => {
      const R = SM.util.rng('graph maps'); const iso = ['SWE', 'NOR', 'FIN', 'DNK', 'DEU', 'FRA', 'ESP', 'ITA', 'POL', 'GBR'];
      const names = ['Sweden', 'Norway', 'Finland', 'Denmark', 'Germany', 'France', 'Spain', 'Italy', 'Poland', 'Atlantis'];
      const states = ['California', 'Texas', 'New York', 'Florida', 'Washington', 'Ohio', 'Georgia', 'Colorado'];
      const c = { iso: [], name: [], state: [], v: [], lon: [], lat: [] };
      for (let i = 0; i < 120; i++) { const k = i % 10; c.iso.push(iso[k]); c.name.push(names[k]); c.state.push(states[i % 8]); c.v.push(i === 4 ? NaN : +(k * 3 + R.normal(0, 1)).toFixed(3)); c.lon.push(+(5 + 20 * R.u()).toFixed(3)); c.lat.push(+(45 + 15 * R.u()).toFixed(3)); }
      const t = new SM.Table({ name: 'Map test', source: 'simulated', columns: [{ name: 'iso', dataType: 'character', values: c.iso }, { name: 'name', dataType: 'character', values: c.name }, { name: 'state', dataType: 'character', values: c.state },
        { name: 'v', values: c.v }, { name: 'lon', values: c.lon }, { name: 'lat', values: c.lat }] });
      SM.app.addTable(t);
      const rep = SM.app.openReport(SM.platforms.get('graphbuilder'), { roles: {}, options: {} }, t);
      window._rep = rep;
      return new Promise((res) => rep.on('done', () => res(t.nrows)));
    })()"""
    check('the seeded table of regions for the maps', await page.ev(MAP_TABLE), 120)
    for col, zone in (('iso', 'shape'), ('v', 'color')):
        xy = await page.ev(f"""(() => {{ const li = [..._rep.body.querySelectorAll('.sm-gb-collist li')].find((l) => l.textContent === {json.dumps(col)}); li.scrollIntoView({{ block: 'center' }}); const b = li.getBoundingClientRect(); return [b.x + 30, b.y + b.height / 2]; }})()""")
        await page.click(*xy)
        xy = await page.ev(f"""(() => {{ const z = _rep.body.querySelector('.sm-gb-z-{zone}'); z.scrollIntoView({{ block: 'center' }}); const b = z.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; }})()""")
        await page.click(*xy)
        await page.ev('__ax.calm(_rep)')
    tv = await page.ev("(() => { const t = SM.app.tables.find((x) => x.name === 'Map test'); return Object.fromEntries(t.columns.map((c) => [c.name, c.values])); })()")
    MAP_Q = r"""(async () => { await __ax.calm(_rep); const p = _gb.plot(); p.box.scrollIntoView({ block: 'center' }); await drawn(p);
      let code = null; for (let i = 0; i < 120 && !code; i++) { code = __ax.code(p); if (!code) await settle(); }
      const fig = _gb.figure(), fl = p.box._fullLayout;
      const ci = p.traces.findIndex((t) => t.type === 'choropleth');
      const ch = ci >= 0 ? p.traces[ci] : null;
      const pts = p.traces.filter((t) => t.type === 'scattergeo' && t.lon && t.lon[0] != null);
      return { els: _gb.state().elements.map((e) => e.type), ci, locs: ch ? ch.locations : null, z: ch ? ch.z : null, mode: ch ? ch.locationmode : null, notes: fig.notes, ids: fig.plan.map && fig.plan.map.shape ? fig.plan.map.shape.ids : null,
        geo: fl.geo ? { proj: fl.geo.projection.type, scope: fl.geo.scope } : null, pts: pts.map((t) => [t.lon, t.lat]), code }; })()"""
    MAP_PROBE = r"""
import json as _json
import matplotlib as _mpl
from matplotlib.collections import PolyCollection as _PC, LineCollection as _LC, PathCollection as _Pt
_f = plt.gcf()
_f.canvas.draw()
_out = {'value': {str(k): v for k, v in (value.items() if 'value' in globals() else [])}, 'axes': []}
for _ax in _f.axes:
    if getattr(_ax, '_colorbar', None) is not None:
        continue
    _A = {'polys': [], 'lines': [], 'points': []}
    for _c in _ax.collections:
        if isinstance(_c, _PC):
            _A['polys'].append({'n': len(_c.get_paths()), 'colors': sorted({_mpl.colors.to_hex(q, keep_alpha=True) for q in _c.get_facecolors()})})
        elif isinstance(_c, _LC):
            _A['lines'].append(len(_c.get_segments()))
        elif isinstance(_c, _Pt):
            _A['points'].append([[float(a), float(b)] for a, b in _c.get_offsets()])
    _out['axes'].append(_A)
_out['colorbars'] = [a.get_ylabel() for a in _f.axes if getattr(a, '_colorbar', None) is not None]
print("SMUI-MAP " + _json.dumps(_out))
"""

    async def map_code(code):
        out = await page.ev(f'__gr.run({json.dumps(strip_show(code or "") + MAP_PROBE)}, _rep.table)', timeout=300)
        outs = out.get('outputs') if isinstance(out, dict) else []
        text = ''.join(o.get('text', '') for o in outs if o.get('type') == 'stream')
        errs = [f"{o.get('ename')}: {o.get('evalue')}" for o in outs if o.get('type') == 'error']
        got = next((json.loads(q[len('SMUI-MAP '):]) for q in text.split('\n') if q.startswith('SMUI-MAP ')), None)
        return got, (errs[0] if errs else None)

    r = await page.ev(MAP_Q, timeout=300)
    isos = list(dict.fromkeys(tv['iso']))
    mean_v = {k: sum(v for i_, v in zip(tv['iso'], tv['v']) if i_ == k and isinstance(v, (int, float)) and math.isfinite(v)) / sum(1 for i_, v in zip(tv['iso'], tv['v']) if i_ == k and isinstance(v, (int, float)) and math.isfinite(v)) for k in isos}
    check('Map Shape (by clicks): Graph Builder draws Map Shapes, a region for each ISO code', (r['els'], r['mode'], r['locs']), (['map'], 'ISO-3', isos))
    check.near('Map Shapes: each region the mean of v over its rows (a missing v left out)', max(abs(a - mean_v[k]) for a, k in zip(r['z'], isos)), 0.0, tol=1e-12)
    check('... on Plotly\'s natural earth map, every code matched to its country', (r['geo'], r['ids'], [n for n in r['notes'] if 'Map Shapes' in n]), ({'proj': 'natural earth', 'scope': 'world'}, {k: k for k in isos}, []))
    got, err = await map_code(r['code'])
    check('Map Shapes: its code runs in the page\'s Python, reading the same boundaries from cdn.plot.ly', err, None)
    if got:
        check.near('... and fills each region with the page\'s value', max(abs(got['value'][k] - mean_v[k]) for k in isos) if set(got['value']) == set(isos) else 1.0, 0.0, tol=1e-9)
        check('... drawn over the land and borders, with a colour bar', (len(got['axes'][0]['polys']), got['axes'][0]['polys'][-1]['n'] >= len(isos), len(got['axes'][0]['lines']), got['colorbars']), (2, True, 1, ['Mean(v)']))
    # linking: a click on a region selects its rows; rows selected elsewhere outline their regions
    r = await page.ev(r"""(async () => { const p = _gb.plot(); const ci = p.traces.findIndex((t) => t.type === 'choropleth'); const k = p.traces[ci].locations.indexOf('FRA');
      clickTrace(p, ci, k); await settle();
      const t = _rep.table; const sel = rowsWhere(t, (i) => t.state[i] & 1);
      t.select(rowsWhere(t, (i) => t.col('iso').values[i] === 'DEU')); await settle();
      const w = p.box.data[ci].marker.line.width; t.select([]); await settle();
      return { sel, k, dk: p.traces[ci].locations.indexOf('DEU'), w: Array.isArray(w) ? w : [w] }; })()""")
    check('Map Shapes linked: a click on France selects its rows', r['sel'], [i for i, v in enumerate(tv['iso']) if v == 'FRA'])
    check('... and Germany\'s rows selected outline Germany', [round(v, 3) for v in r['w']], [2.4 if k == r['dk'] else 0.6 for k in range(len(isos))])
    # by name (one not on the map), and US states by name, counted
    r = await page.ev(r"""(async () => { const t = _rep.table; await _gb.update((S) => { S.zones.shape = [{ id: t.col('name').id, name: 'name' }]; }); return null; })()""")
    r = await page.ev(MAP_Q, timeout=300)
    check('Map Shapes by country name: Plotly\'s matching; a name not on the map named in a note, left off it', (r['mode'], sorted(r['ids'].items()), [n for n in r['notes'] if 'Atlantis' in n] != []),
          ('country names', sorted(zip(['Sweden', 'Norway', 'Finland', 'Denmark', 'Germany', 'France', 'Spain', 'Italy', 'Poland'], isos[:9])), True))
    got, err = await map_code(r['code'])
    check('... its code fills the nine countries found, as the page', (err, sorted((got or {}).get('value', {}))), (None, sorted(isos[:9])))
    await page.ev(r"""(async () => { const t = _rep.table; await _gb.update((S) => { S.zones.shape = [{ id: t.col('state').id, name: 'state' }]; S.zones.color = []; }); })()""")
    r = await page.ev(MAP_Q, timeout=300)
    states = list(dict.fromkeys(tv['state']))
    codes = {'California': 'CA', 'Texas': 'TX', 'New York': 'NY', 'Florida': 'FL', 'Washington': 'WA', 'Ohio': 'OH', 'Georgia': 'GA', 'Colorado': 'CO'}
    check('Map Shapes of US states by name: their postal codes on Plotly\'s Albers USA map, filled by their counts', (r['mode'], r['locs'], r['z'], r['geo'], r['ids']),
          ('USA-states', [codes[q] for q in states], [tv['state'].count(q) for q in states], {'proj': 'albers usa', 'scope': 'usa'}, codes))
    got, err = await map_code(r['code'])
    check('... its code counts them the same, from the US file', (err, (got or {}).get('value')), (None, {codes[q]: float(tv['state'].count(q)) for q in states}))
    # points on a Background Map, linked point by point
    r = await page.ev(r"""(async () => { const t = _rep.table; await _gb.update((S) => { for (const k of Object.keys(S.zones)) S.zones[k] = []; S.zones.x = [{ id: t.col('lon').id, name: 'lon' }]; S.zones.y = [{ id: t.col('lat').id, name: 'lat' }]; S.auto = true; });
      await __ax.calm(_rep); _rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu').click(); await settle(); __ax.hover('Background Map'); await settle(); const sub = __ax.menus()[1]; __ax.item('World', 1); await _gb.idle(); return sub; })()""")
    check('Background Map in the red triangle: None, World, US States', r, ['✓None', 'World', 'US States'])
    r = await page.ev(MAP_Q, timeout=300)
    check('Points on a Background Map: Points alone, each row at its longitude and latitude, on a map', (r['els'], r['pts'], r['geo']), (['points'], [[tv['lon'], tv['lat']]], {'proj': 'natural earth', 'scope': 'world'}))
    got, err = await map_code(r['code'])
    check('... its code draws every point at its longitude and latitude over the land and borders', (err, sorted(tuple(q) for q in (got or {'axes': [{'points': [[]]}]})['axes'][0]['points'][0]), len((got or {'axes': [{'lines': []}]})['axes'][0]['lines'])),
          (None, sorted(zip(tv['lon'], tv['lat'])), 1))
    r = await page.ev(r"""(async () => { const p = _gb.plot(); const i = p.traces.findIndex((t) => t.type === 'scattergeo' && t.lon && t.lon[0] != null);
      clickTrace(p, i, 7); await settle(); const t = _rep.table; const sel = rowsWhere(t, (k) => t.state[k] & 1);
      t.setState([3], 'hidden', true); await settle(); const lon = p.box.data[i].lon.slice(0, 5); t.setState([3], 'hidden', false); t.select([]); await settle(); return { sel, lon }; })()""")
    check('... a click on a point selects its row; a hidden row is not drawn', (r['sel'], r['lon'][3], r['lon'][2] is not None), ([7], None, True))
    await page.ev(r"""(async () => { await _gb.update((S) => { S.map = null; }); })()""")

    # ---- a date on X stays a date axis when the page restyles a graph's traces (a Line's selection rings on drawing and
    # on a selection): Plotly guessed the axis type again from the milliseconds and made it a number axis
    r = await page.ev(r"""(async () => {
      const n = 40, d = [], y = [];
      for (let i = 0; i < n; i++) { d.push(Date.UTC(2021, 0, 4) + (i % 8) * 7 * 86400000); y.push((i % 5) + (i % 8)); }
      const t = new SM.Table({ name: 'Dated line', columns: [{ name: 'd', values: d, format: { kind: 'date' } }, { name: 'y', values: y }] });
      SM.app.addTable(t);
      const rep = SM.app.openReport(SM.platforms.get('graphbuilder'), { roles: {}, options: {} }, t); await new Promise((res) => rep.on('done', res));
      const gb = () => SM.platforms.get('graphbuilder').builder(rep);
      await gb().update((S) => { S.zones.x = [{ id: t.col('d').id, name: 'd' }]; S.zones.y = [{ id: t.col('y').id, name: 'y' }]; S.auto = false; S.elements = [{ type: 'line' }]; });
      const p = await drawn(gb().plot()); p.box.scrollIntoView({ block: 'center' }); await settle();
      const drawnType = p.box._fullLayout.xaxis.type;
      t.select([0, 8, 16]); await settle(); await settle();
      const selType = p.box._fullLayout.xaxis.type, ticks = p.box._fullLayout.xaxis._vals.map((v) => v.text);
      t.select([]); SM.app.closeReport(rep); SM.app.closeTable(t);
      return { drawnType, selType, datey: ticks.every((x) => /[A-Z][a-z]{2}|20\d\d/.test(x)) }; })()""")
    check('Graph Builder: a Line over a date X is on a date axis, after drawing and after a selection', (r['drawnType'], r['selType'], r['datey']), ('date', 'date', True))

    # ---- Axis Settings on a date axis in a browser that is not on UTC, over a daylight-saving change
    await stockholm_dates(page)

    # ---- the Graph menu's point plots: Marker Size and Transparency in the red triangle, and in their code
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'Graph data')))")
    res = await page.ev(open_report_js('scattermatrix', {'y': ['x', 'y', 'z']}))
    r = await page.ev(r"""(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; await __ax.calm(rep);
      rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu').click(); await settle(); __ax.hover('Marker Size'); await settle(); __ax.item('4, XL', 1);
      await new Promise((res) => rep.on('done', res)); rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu').click(); await settle(); __ax.hover('Transparency'); await settle(); __ax.item('0.6', 1);
      await new Promise((res) => rep.on('done', res)); const p = await __ax.redrawn(rep); const tr = p.traces.filter((t) => t.mode === 'markers' && t.x && t.x[0] != null);
      return { sizes: [...new Set(tr.map((t) => t.marker.size))], ops: [...new Set(tr.map((t) => t.marker.opacity))], code: __ax.code(p), spec: rep.spec.options.marker }; })()""")
    check('Scatterplot Matrix: Marker Size 4, XL and Transparency 0.6 in every cell, kept in the report', (r['sizes'], r['ops'], r['spec']), ([9], [0.6], {'size': 9, 'alpha': 0.6}))
    out = await page.ev(f'__gr.run({json.dumps(page_probe_more(r["code"] or "", []))}, SM.app.reports[SM.app.reports.length - 1].table)', timeout=300)
    R, err = more_from_outputs(out.get('outputs') if isinstance(out, dict) else None)
    got = sorted({(round(q, 4), c[-2:]) for A in (R['figures'][0]['axes'] if R else []) for S in A['scatter'] for q, c in zip(S['sizes'] * len(S['colors']) if len(S['sizes']) == 1 else S['sizes'], S['colors'])})
    check('... and its code draws them so', (err, got), (None, [(float(f'{(9 * 0.72) ** 2:.3g}'), '99')]))
    await page.ev('SM.app.closeReport(SM.app.reports[SM.app.reports.length - 1])')

    # ---- dark theme and phone width: the reference lines' colours, a map's land, the Axis Settings window
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(1.2)
    r = await page.ev(r"""(async () => { SM.app.showTab(SM.app.tabOf(_fr)); await __ax.calm(_fr); const p = await __ax.redrawn(_fr); p.box.scrollIntoView({ block: 'center' }); await drawn(p);
      const done = new Promise((res) => _fr.on('done', res)); SM.axis.put(p, 'yaxis', { refs: [{ value: 60, color: 'red', dash: 'solid' }] }); await done; const q = await __ax.redrawn(_fr);
      const line = q.box._fullLayout.shapes.find((s) => s.type === 'line'); return line ? line.line.color : null; })()""")
    check('dark theme: a red reference line takes the dark theme\'s red, which reads on it', r, '#f08a80')
    r = await page.ev(r"""(async () => { const p = _fr.plots[0]; const img = await _fr.plotImage(p, 'svg'); const svg = decodeURIComponent(img.data.replace(/^data:image\/svg\+xml,/, ''));
      return { light: svg.includes('rgb(176, 65, 62)'), dark: svg.includes('rgb(240, 138, 128)') }; })()""")
    check('... and on paper (Save Report as HTML or Word, Print), the light theme\'s red', (r['light'], r['dark']), (True, False))
    r = await page.ev(r"""(async () => { const t = SM.app.tables.find((x) => x.name === 'Map test'); SM.app.showTab(SM.app.tabOf(_rep)); await __ax.calm(_rep);
      await _gb.update((S) => { for (const k of Object.keys(S.zones)) S.zones[k] = []; S.zones.shape = [{ id: t.col('iso').id, name: 'iso' }]; S.auto = true; }); await __ax.calm(_rep);
      const p = await drawn(_gb.plot()); return { land: p.box._fullLayout.geo.landcolor, grid: getComputedStyle(document.documentElement).getPropertyValue('--border-color').trim() }; })()""")
    g_ = r['grid'].lstrip('#')
    g_ = ''.join(q * 2 for q in g_) if len(g_) == 3 else g_
    check('dark theme: the map\'s land is the dark theme\'s border colour, faint', r['land'].replace(' ', ''), f'rgba({int(g_[0:2], 16)},{int(g_[2:4], 16)},{int(g_[4:6], 16)},0.35)')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    r = await page.ev(r"""(async () => { SM.app.showTab(SM.app.tabOf(_fr)); await __ax.calm(_fr); const p = await __ax.redrawn(_fr);
      SM.axis.open(p, 'yaxis'); await settle(); const d = __ax.dialog(); d.querySelector('[data-ax="addref"]').click(); await settle();
      const b = d.getBoundingClientRect(), body = d.querySelector('.sm-dialog-body');
      const out = { w: Math.round(b.width), iw: innerWidth, fits: body.scrollWidth <= body.clientWidth + 1, rows: [...d.querySelectorAll('.sm-ax-ref')].map((q) => q.getBoundingClientRect().width <= body.clientWidth + 1) };
      __ax.button(d, 'Cancel'); await settle(); return out; })()""")
    check('phone width: the Axis Settings window is the whole screen, its reference lines fit it', (r['w'], r['fits'], all(r['rows'])), (r['iw'], True, True))
    await shot(page, 'g11-axis-phone.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await asyncio.sleep(1.2)
    await page.ev('(() => { if (window._rep0b) window._rep = window._rep0b; })()')

async def stockholm_dates(page):
    """Axis Settings on a date axis in a Europe/Stockholm browser, over the daylight-saving change of 2021-03-28: the page's
    dates are UTC milliseconds, Plotly reads a number given for a range or a shape in local time, so Axis Settings gives it
    the dates as text. The graph's range, ticks, reference line and range are then the data's dates exactly, the line
    where the point of its day is, and the code's figure has the same."""
    await page.call('Emulation.setTimezoneOverride', {'timezoneId': 'Europe/Stockholm'}, session=page.sid)
    DAY = 86400000
    day = lambda y, m, d: (datetime(y, m, d) - datetime(1970, 1, 1)).total_seconds() * 1000  # noqa: E731
    try:
        r = await page.ev(r"""(async () => {
          window.__mapRep = window._rep;
          const DAY = 86400000, d0 = Date.UTC(2021, 2, 20), d = [], v = [];
          for (let i = 0; i < 17; i++) { d.push(d0 + i * DAY); v.push(i % 4); }
          const t = new SM.Table({ name: 'DST dates', columns: [{ name: 'd', values: d, format: { kind: 'date' } }, { name: 'v', values: v }] }); SM.app.addTable(t);
          const rep = SM.app.openReport(SM.platforms.get('graphbuilder'), { roles: {}, options: {} }, t); await new Promise((res) => rep.on('done', res));
          window._rep = rep;
          await _gb.update((S) => { S.zones.x = [{ id: t.col('d').id, name: 'd' }]; S.zones.y = [{ id: t.col('v').id, name: 'v' }]; S.auto = false; S.elements = [{ type: 'points' }]; });
          return [new Date(Date.UTC(2021, 2, 20)).getTimezoneOffset(), new Date(Date.UTC(2021, 3, 1)).getTimezoneOffset()]; })()""")
        check('Stockholm: the browser\'s offset from UTC changes within the dates (CET, then CEST)', r, [-60, -120])
        xy = await page.ev('__ax.gbAt("ew")')
        await dbl(page, *xy)
        r = await page.ev(r"""(async () => { const d = __ax.dialog(); if (!d) return null; const title = d.querySelector('h2').textContent;
          __ax.set(d, 'min', '2021-03-25'); __ax.set(d, 'max', '2021-04-01'); __ax.set(d, 'inc', '1');
          const add = d.querySelector('[data-ax="addref"]'); add.click(); add.click();
          const R = d.querySelectorAll('.sm-ax-ref');
          __ax.set(R[0], 'ref', '2021-03-28'); __ax.set(R[0], 'reflabel', 'DST'); __ax.set(R[0], 'refcolor', 'red');
          __ax.set(R[1], 'ref', '2021-03-26'); __ax.set(R[1], 'refto', '2021-03-27'); __ax.set(R[1], 'refcolor', 'blue');
          __ax.button(d, 'OK'); await _gb.idle(); await settle();
          const p = await drawn(_gb.plot()); p.box.scrollIntoView({ block: 'center' }); await settle();
          let code = null; for (let i = 0; i < 120 && !code; i++) { code = __ax.code(p); if (!code) await settle(); }
          const fl = p.box._fullLayout, xa = fl.xaxis;
          const line = fl.shapes.find((q) => q.type === 'line'), rect = fl.shapes.find((q) => q.type === 'rect');
          const path = [...p.box.querySelectorAll('.shapelayer path')].map((q) => q.getAttribute('d')).find((q) => /^M[\d.]+,[\d.]+L[\d.]+,[\d.]+$/.test(q));
          const label = fl.annotations.find((a) => a.text === 'DST');
          return { title, range: xa.range.map((q) => xa.r2l(q)), ticks: xa._vals.map((q) => q.x), line: xa.r2l(line.x0), rect: [xa.r2l(rect.x0), xa.r2l(rect.x1)], label: label ? xa.r2l(label.x) : null,
            linePx: path ? Number(/^M([\d.]+),/.exec(path)[1]) : null, pointPx: xa._offset + xa.c2p(Date.UTC(2021, 2, 28)), state: _gb.state().axes['x:d'], code }; })()""")
        check('Stockholm: a double-click on the date axis opens its window, the dates typed as dates', (r or {}).get('title'), 'X Axis Settings')
        check('Stockholm: kept as the page keeps dates, UTC milliseconds', (r['state']['min'], r['state']['max'], [q['value'] for q in r['state']['refs']]), (day(2021, 3, 25), day(2021, 4, 1), [day(2021, 3, 28), day(2021, 3, 26)]))
        check('Stockholm: the graph\'s date axis from 2021-03-25 to 2021-04-01 exactly (not an hour on)', r['range'], [day(2021, 3, 25), day(2021, 4, 1)])
        check('... a tick at every midnight (UTC) from the minimum, across the change', r['ticks'], [day(2021, 3, 25) + k * DAY for k in range(8)])
        check('... the reference line at 2021-03-28, the shading from 2021-03-26 to -27, the label at its line', (r['line'], r['rect'], r['label']), (day(2021, 3, 28), [day(2021, 3, 26), day(2021, 3, 27)], day(2021, 3, 28)))
        check('... the line drawn where the point of 2021-03-28 is (to the pixel)', abs((r['linePx'] or 0) - r['pointPx']) < 0.01, True)
        out = await page.ev(f'__gr.run({json.dumps(page_probe_more(r["code"] or "", []))}, _rep.table)', timeout=300)
        R, err = more_from_outputs(out.get('outputs') if isinstance(out, dict) else None)
        A = R['figures'][0]['axes'][0] if R else {}
        dd = lambda ms: ms / DAY  # noqa: E731   (matplotlib's dates: days since 1970)
        spans = [[b['x'], b['x'] + b['w']] for b in A.get('bars', []) if (b['fc'] or '').startswith('#1f4e79')] + [sorted({q[0] for q in P['xy']}) for P in A.get('polygons', []) if (P['fc'] or '').startswith('#1f4e79')]
        pts = sorted({round(q[0], 9) for S_ in A.get('scatter', []) for q in S_['xy']})
        check('Stockholm: the code\'s figure: the same dates, ticks, line and shading, the point of the day on its line',
              (err, A.get('xlim'), A.get('xticks'), [L['x'] for L in A.get('lines', []) if (L['color'] or '').startswith('#b0413e')], spans, round(dd(day(2021, 3, 28)), 9) in pts),
              (None, [dd(day(2021, 3, 25)), dd(day(2021, 4, 1))], [dd(day(2021, 3, 25) + k * DAY) for k in range(8)], [[dd(day(2021, 3, 28))] * 2], [[dd(day(2021, 3, 26)), dd(day(2021, 3, 27))]], True))
    finally:
        await page.ev('(() => { const t = _rep.table; if (t && t.name === "DST dates") { SM.app.closeReport(_rep); SM.app.closeTable(t); } window._rep = window.__mapRep; })()')
        await page.call('Emulation.setTimezoneOverride', {'timezoneId': ''}, session=page.sid)


def SM_fmt4(v):
    """The page's fmt(v, {sig: 4}) for a positive number of moderate size."""
    s = f'{v:.4g}'
    return s


asyncio.run(main())
sys.exit(check.done())
