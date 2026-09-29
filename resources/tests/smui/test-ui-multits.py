#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Specialized Modeling >
Multivariate Time Series, on the platform's Quarterly macro example and on
statsmodels' macrodata.

The platform is in the menu after Time Series and its example on the Home
tab; the launch dialog casts the series, the Time ID and an exogenous
column and refuses a single Y; the report shows the stationarity summary
(mean and SD as computed in the page), the lag order table with its minima,
and a VAR whose coefficients equal least squares computed in the page; the
documented statsmodels example (macrodata, Log and Difference) shows the
published coefficients; the red triangles choose the lag, the transform,
the bands (Monte Carlo, seeded), the Cholesky ordering and the parts; the
Granger matrix, the impulse response grid, the variance decomposition
(shares adding to 1) and the forecasts that continue the quarters draw;
Save Forecasts makes a table and Save Residuals columns; the cointegration
part finds the example's cointegrated pair; a click on a point selects its
row and a table selection shows in the graph; excluded rows are filled and
noted; By gives a report per level; the options survive a saved and
reopened project; the report draws in the dark theme and at phone width.

Start a server on the repository root and headless Chrome on SMUI_HTTP_PORT
and SMUI_CDP_PORT (see README.md), then

    python3 resources/tests/smui/test-ui-multits.py

SMUI_SHOTS=<folder> saves screenshots. Exit status 0 when every check passes.
"""
import asyncio
import json
import math
import os
import re
import sys
from datetime import datetime

from cdp import BASE, Checks, open_page, table_under_js, wait_engine
from test_charts import GRAPHS_JS, close, more_from_outputs, page_probe_more

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


# ---- the graphs' matplotlib code --------------------------------------------------------------
# Every graph of a report has a code block under it, ending in plt.show(); the
# block runs in the page's own Python (SM.engine.runCell, as
# test_charts.GRAPHS_JS.run does it) with PROBE_MORE in place of plt.show(), and
# the figure it draws is compared with the Plotly graph: every line and set of
# points in its panel (dates in days), the bands, the heatmaps' cells and their
# texts, the stacked bars, the reference lines, the cells' labels, the legend,
# the axis titles, the size.
MTG_JS = r'''
window.__mtg = {
  openAll(rep) { rep.body.querySelectorAll('.sm-ob.is-closed').forEach((s) => s._outline && s._outline.setOpen(true)); },
  extra(rep) {
    return [...rep.body.querySelectorAll('.js-plotly-plot')].map((p) => {
      const L = p.layout || {};
      const axes = {};
      for (const k of Object.keys(L)) if (/^[xy]axis\d*$/.test(k)) axes[k] = { type: L[k].type || null };
      return { widths: (p.data || []).map((d) => (d.line && d.line.width != null ? d.line.width : null)), axes, showlegend: !!L.showlegend, barmode: L.barmode || null,
        annotations: (L.annotations || []).map((a) => a.text), shapes: (L.shapes || []).map((s) => ({ type: s.type, xref: s.xref || 'x', yref: s.yref || 'y', x0: s.x0, x1: s.x1, y0: s.y0, y1: s.y1 })) };
    });
  },
};
true
'''
EPOCH = datetime(1970, 1, 1)


def to_days(v):
    """A value of a Plotly date axis (ISO text, or milliseconds) in matplotlib's units, days since 1970."""
    if isinstance(v, str):
        return (datetime.fromisoformat(v.replace(' ', 'T')) - EPOCH).total_seconds() / 86400
    return None if v is None else v / 86400000


def axis_at(ref):
    """The panel of a Plotly axis reference: y → 0, y2 or 'y2 domain' → 1."""
    m = re.match(r'^[xy](\d*)', ref or 'y')
    return int(m.group(1)) - 1 if m and m.group(1) else 0


def finite_pairs(xs, ys):
    return [(a, b) for a, b in zip(xs, ys) if isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.isfinite(a) and math.isfinite(b)]


def same_points(p, q, rel=1e-6):
    return len(p) == len(q) and all(close(a, c, rel, 1e-9) and close(b, d, rel, 1e-9) for (a, b), (c, d) in zip(p, q))


def mpl_sets(A):
    out = [finite_pairs([q[0] for q in xy], [q[1] for q in xy]) for xy in A['xy_lines']]
    return out + [finite_pairs([q[0] for q in s['xy']], [q[1] for q in s['xy']]) for s in A['scatter']]


def check_graph(tag, g, ex, F, rel=1e-6):
    """A Plotly graph against the figure its code draws."""
    date = (ex['axes'].get('xaxis') or {}).get('type') == 'date'
    X = to_days if date else (lambda v: v)
    axes = [A for A in F['axes'] if not A.get('colorbar')]
    check(f'{tag}: the figure has the graph\'s size', F['size'], [g['w'] / 100, g['h'] / 100])
    check(f'{tag}: the graph\'s title', g['label'] in [F['suptitle']] + [A['title'] for A in axes], True)
    missing, fills, bars = [], [0] * len(axes), [[] for _ in axes]
    for tr, width in zip(g['traces'], ex['widths']):
        kind = tr.get('type') or 'scatter'
        if kind == 'heatmap':
            A = axes[0]
            z = [v for row in tr['z'] for v in row]
            check(f'{tag}: the colour map\'s cells', (A['images'][0]['shape'] if A['images'] else None, close(A['images'][0]['data'] if A['images'] else [], z, 1e-9, 1e-12)),
                  ([len(tr['z']), len(tr['z'][0])], True))
            check(f'{tag}: the cells\' texts, as the page writes them', [t['s'] for t in A['texts']], [s for row in tr['text'] for s in row if s])
            check(f'{tag}: the rows and columns named', (A['xticklabels'], A['yticklabels']), (tr['x'], tr['y']))
            continue
        if kind == 'bar':
            i = axis_at(tr.get('yaxis'))
            bars[i].append(tr)
            continue
        pts = finite_pairs([X(v) for v in tr.get('x') or []], tr.get('y') or [])
        if not pts:
            continue
        A = axes[axis_at(tr.get('yaxis'))]
        if tr.get('fill') in ('tonexty', 'tozeroy', 'toself'):
            fills[axis_at(tr.get('yaxis'))] += 1
        if width == 0:
            continue
        if not any(same_points(pts, p, rel) for p in mpl_sets(A)):
            missing.append(tr.get('name'))
    check(f'{tag}: every line and set of points, in its panel', missing, [])
    check(f'{tag}: every band, in its panel', [len(A['polys']) for A in axes], fills)
    if any(bars):
        stacked = ex['barmode'] == 'stack'
        for i, trs in enumerate(bars):
            want, base = [], {}
            for tr in trs:
                for x, h in zip(tr['x'], tr['y']):
                    b0 = base.get(x, 0.0) if stacked else 0.0
                    want.append((x, b0, h))
                    base[x] = b0 + h
            got = [(b['x'] + b['w'] / 2, b['y'], b['h']) for b in axes[i]['bars']]
            check(f'{tag}: panel {i + 1}: the bars{", stacked" if stacked else ""}', (len(got), all(close(list(a), list(b), 1e-9, 1e-12) for a, b in zip(got, want))), (len(want), True))
    wrong = []
    for s in ex['shapes']:
        A = axes[axis_at(s['yref'])] if s['yref'] != 'paper' else axes[0]
        if s['x0'] == s['x1'] and (s['yref'] == 'paper' or s['yref'].endswith('domain')):
            ok = any(same_points(p, [(X(s['x0']), 0), (X(s['x0']), 1)], 1e-9) for p in mpl_sets(A))
        elif s['xref'] == 'paper':
            ok = any(same_points(p, [(0, s['y0']), (1, s['y0'])], 1e-6) for p in mpl_sets(A))
        else:
            ok = any(same_points(p, [(X(s['x0']), s['y0']), (X(s['x1']), s['y1'])], 1e-6) for p in mpl_sets(A))
        if not ok:
            wrong.append(s)
    check(f'{tag}: every reference line of the graph', wrong, [])
    words = [A['title'] for A in axes] + [t['s'] for A in axes for t in A['texts']]
    check(f'{tag}: the cells\' labels', [a for a in ex['annotations'] if a.replace('<br>', ' ') not in words], [])
    if ex['showlegend']:
        check(f'{tag}: the legend', F['legend'], [tr.get('name') for tr in g['traces'] if tr.get('showlegend') is not False and tr.get('name')])
    if g['titles']['x']:
        check(f'{tag}: the x axis title', g['titles']['x'] in [A['xlabel'] for A in axes], True)
    if g['titles']['y'] is not None:
        check(f'{tag}: the y axis title', axes[0]['ylabel'], g['titles']['y'])


async def check_report_graphs(page, rep_js, table_js, what):
    """Every graph of a report: its block, run in the page's Python, against the page."""
    await page.ev(f'__mtg.openAll({rep_js})')
    r = await page.ev(f'(async () => {{ const rep = {rep_js}; const g = await __gr.graphs(rep); return {{ g, ex: __mtg.extra(rep), undrawn: __gr.take() }}; }})()', timeout=900)
    check(f'{what}: every graph of the report drawn', r['undrawn'], [])
    check(f'{what}: every graph with its code block under it, ending in plt.show()', [g['label'] for g in r['g'] if not (g['code'] and g['code'].rstrip().split('\n')[-1] == 'plt.show()')], [])
    for g, ex in zip(r['g'], r['ex']):
        if not g['code']:
            continue
        out = await page.ev(f'__gr.run({json.dumps(page_probe_more(g["code"]))}, {table_js})', timeout=900)
        F, err = (None, out) if isinstance(out, str) else more_from_outputs(out.get('outputs'))
        F = F['figures'] if F else None
        check(f'{what}: {g["label"]}: the code runs in the page, one figure', (err, len(F or [])), (None, 1))
        if F:
            check_graph(f'{what}: {g["label"]}', g, ex, F[0])
    return r


def open_js(table, roles, options, before='', after='', more='{}'):
    """JS that opens a Multivariate Time Series report on the table named so
    (before: JS run first, with t the table and id(); after: JS run once it is
    done, with rep; more: a JS object of options that name columns by id),
    keeps it as window.__mtc and returns its title and problems."""
    return f'''(async () => {{ const t = SM.app.tables.find((x) => x.name === {json.dumps(table)}); SM.app.showTab(SM.app.tabOf(t));
      const id = (n) => t.col(n).id; const roles = {{}};
      for (const [k, names] of Object.entries({json.dumps(roles)})) roles[k] = names.map(id);
      {before}
      const rep = SM.app.openReport(SM.platforms.get('multits'), {{ roles, options: Object.assign({json.dumps(options)}, {more}) }}, t);
      await __mts.done(rep);
      {after}
      window.__mtc = rep;
      return {{ title: rep.title, ...__mts.problems(rep) }}; }})()'''


async def chart_code(page):
    """Reports that between them draw every kind of graph of the platform, with
    their options; every graph checked against its code's figure."""
    await page.ev(GRAPHS_JS)
    await page.ev(MTG_JS)
    await page.ev('__gr.idle()')   # the reports run again by a change of theme are done
    rep, tbl, close_js = 'window.__mtc', 'window.__mtc.table', 'SM.app.closeReport(window.__mtc)'
    macro = "SM.app.tables.find((x) => x.name === 'Quarterly macro')"
    # the VAR of the example with every part, two rows excluded (gaps in the graph, filled for the VAR)
    r = await page.ev(open_js('Quarterly macro', {'y': ['growth', 'inflation', 'interest rate'], 'time': ['quarter']}, {'forecast': 8},
                              before="t.setState([40, 41], 'excluded', true);"), timeout=900)
    check('charts: the VAR report opens without errors', r['errors'], [])
    g = await check_report_graphs(page, rep, tbl, 'charts: VAR')
    check('charts: VAR: its graphs', [x['label'] for x in g['g']], ['Time Series Graph', 'Residual correlation colour map', 'Companion matrix eigenvalues', 'Granger causality p-values',
                                                                  'Impulse responses', 'Variance decomposition', 'VAR forecasts'])
    await page.ev(f"{close_js}; {macro}.setState([40, 41], 'excluded', false)")
    # the cointegrated pair: Difference (forecasts in the units of the table), Small Multiples, Monte Carlo
    # bands of cumulative responses to unit shocks, the Cholesky ordering reversed, the VECM's forecasts
    r = await page.ev(open_js('Quarterly macro', {'y': ['income', 'consumption'], 'time': ['quarter']},
                              {'forecast': 8, 'diff': True, 'multiples': True, 'coint': True, 'irfBands': 'mc', 'mcRepl': 200, 'irfCum': True, 'irfOrth': False},
                              more="{ order: [id('consumption'), id('income')] }"), timeout=900)
    check('charts: the cointegration report opens without errors', r['errors'], [])
    g = await check_report_graphs(page, rep, tbl, 'charts: cointegration')
    check('charts: cointegration: the VECM forecasts too', 'VECM forecasts' in [x['label'] for x in g['g']], True)
    await page.ev(close_js)
    # Log, the forecasts of the series as analysed, an exogenous column (its future values held)
    r = await page.ev(open_js('Quarterly macro', {'y': ['income', 'consumption'], 'time': ['quarter'], 'exog': ['growth']},
                              {'forecast': 6, 'log': True, 'fcTransformed': True, 'granger': False, 'fevd': False}), timeout=900)
    check('charts: the report of the logarithms opens without errors', r['errors'], [])
    await check_report_graphs(page, rep, tbl, 'charts: logarithms')
    await page.ev(close_js)
    # By, a Local Data Filter and an excluded row, no Time ID
    r = await page.ev('''(() => { const rng = SM.util.rng('mts-charts'); const n = 160; let a = 0, b = 0; const A = [], B = [];
      for (let i = 0; i < n; i++) { const a1 = 0.5 * a + 0.2 * b + rng.normal(0, 1); b = 0.3 * a + 0.4 * b + rng.normal(0, 1); a = a1;
        A.push(Math.round(1000 * a) / 1000); B.push(Math.round(1000 * b) / 1000); }
      const t = new SM.Table({ name: 'MTS chart rows', columns: [
        { name: 'region', dataType: 'character', values: A.map((_, i) => (i % 2 ? 'South' : 'North')) },
        { name: 'keep', dataType: 'character', values: A.map((_, i) => ([30, 32, 34].includes(i) ? 'no' : 'yes')) },
        { name: 'a', dataType: 'numeric', values: A }, { name: 'b', dataType: 'numeric', values: B }] });
      SM.app.addTable(t); t.setState([50], 'excluded', true); return t.nrows; })()''')
    check('charts: a table of our own for By and a filter', r, 160)
    r = await page.ev(open_js('MTS chart rows', {'y': ['a', 'b'], 'by': ['region']}, {'forecast': 4, 'maxlags': 4},
                              after="rep.toggleFilter(true); await __mts.done(rep); rep.spec.filter.push({ col: t.col('keep').id, levels: ['yes'] }); { const d = __mts.done(rep); rep.run(); await d; }"),
                      timeout=900)
    check('charts: By with a Local Data Filter opens without errors', r['errors'], [])
    g = await check_report_graphs(page, rep, tbl, 'charts: By and a filter')
    codes = [x['code'] for x in g['g'] if x['label'] == 'Time Series Graph']
    check('charts: By and a filter: each group\'s graph keeps its group; the filtered rows are dropped, the excluded one missing',
          [('df = df[df["region"] == \'North\']' in c_, 'df = df.drop(index=[30, 32, 34])   # the rows the report leaves out' in c_, 'Y.iloc[' in c_) for c_ in codes],
          [(True, True, True), (False, False, False)])
    await page.ev(f"{close_js}; SM.app.closeTable(SM.app.tables.find((x) => x.name === 'MTS chart rows')); document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach((b) => b.click());")

HELPERS = r'''
window.__mts = {
  rep() { return SM.app.reports[SM.app.reports.length - 1]; },
  done(rep) { return new Promise((res) => { let once = false; rep.on('done', () => { if (!once) { once = true; res(); } }); }); },
  head(rep, title) {   // the outline of that title, else the first whose title starts so
    const hs = [...rep.body.querySelectorAll('.sm-ob-head')];
    const text = (h) => (h.querySelector('h2, h3, h4') || h).textContent.trim();
    return hs.find((h) => text(h) === title) || hs.find((h) => text(h).startsWith(title));
  },
  async pick(btn, path) {
    btn.click();
    for (let i = 0; i < path.length; i++) {
      const menus = [...document.querySelectorAll('.sm-menu')];
      const m = menus[menus.length - 1];
      const b = [...m.querySelectorAll('button')].find((x) => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === path[i]);
      if (!b) throw new Error('no menu item ' + path[i] + ' in ' + [...m.querySelectorAll('.sm-label')].map((x) => x.textContent).join(' | '));
      b.click();
    }
    await new Promise((r) => setTimeout(r, 60));
  },
  async menu(rep, title, path) {
    const h = title == null ? rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head') : this.head(rep, title);
    if (!h) throw new Error('no outline ' + title);
    await this.pick(h.querySelector('.sm-ob-menu'), path);
  },
  labels(rep, title) {
    const h = title == null ? rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head') : this.head(rep, title);
    h.querySelector('.sm-ob-menu').click();
    const m = [...document.querySelectorAll('.sm-menu')].pop();
    const out = [...m.querySelectorAll('.sm-label')].map((x) => x.textContent);
    SM.ui.closeMenus(0);
    return out;
  },
  async form(values, button) {
    await new Promise((r) => setTimeout(r, 120));
    const dlg = [...document.querySelectorAll('.sm-dialog')].pop();
    if (!dlg) throw new Error('no dialog');
    const title = dlg.querySelector('.sm-dialog-head h2').textContent;
    for (const [label, v] of Object.entries(values)) {
      const lab = [...dlg.querySelectorAll('.sm-form label')].find((l) => l.textContent === label);
      if (!lab) throw new Error('no field ' + label + ' in ' + title);
      const inp = document.getElementById(lab.htmlFor);
      if (inp.type === 'checkbox') inp.checked = !!v; else inp.value = String(v);
    }
    const b = [...dlg.querySelectorAll('.sm-dialog-foot .sm-btn')].find((x) => x.textContent === button);
    if (!b) throw new Error('no button ' + button);
    b.click();
    return title;
  },
  outlines(rep) { return [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map((h) => h.textContent); },
  problems(rep) { return { errors: [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent.slice(0, 300)), warns: [...rep.body.querySelectorAll('.sm-ob-warn')].map((e) => e.textContent.slice(0, 200)) }; },
  rtRows(rep, title, n = 0) {
    const h = this.head(rep, title);
    if (!h) return null;
    const t = h.parentElement.querySelectorAll(':scope > .sm-ob-body table.sm-rt')[n] || h.parentElement.querySelectorAll('table.sm-rt')[n];
    return t && t._rt ? t._rt.rows : null;
  },
  note(rep, title, text) { const h = this.head(rep, title); return !!h && h.parentElement.textContent.includes(text); },
  plot(rep, title) { return rep.plots.find((p) => p.opts.title === title); },
};
/* Least squares in the page, for one equation of a VAR(p) with a constant:
   y_t on 1, y_t-1 (every series), ..., y_t-p. Normal equations, Gaussian
   elimination with partial pivoting. */
window.__ols = (series, eq, p) => {
  const n = series[0].length, k = series.length;
  const X = [], y = [];
  for (let t = p; t < n; t++) {
    const row = [1];
    for (let l = 1; l <= p; l++) for (let j = 0; j < k; j++) row.push(series[j][t - l]);
    X.push(row); y.push(series[eq][t]);
  }
  const m = X[0].length;
  const A = Array.from({ length: m }, (_, i) => Array.from({ length: m + 1 }, (_, j) => (j < m ? X.reduce((s, r) => s + r[i] * r[j], 0) : X.reduce((s, r, q) => s + r[i] * y[q], 0))));
  for (let c = 0; c < m; c++) {
    let piv = c;
    for (let r = c + 1; r < m; r++) if (Math.abs(A[r][c]) > Math.abs(A[piv][c])) piv = r;
    [A[c], A[piv]] = [A[piv], A[c]];
    for (let r = 0; r < m; r++) if (r !== c) { const f = A[r][c] / A[c][c]; for (let j = c; j <= m; j++) A[r][j] -= f * A[c][j]; }
  }
  return A.map((row, i) => row[m] / row[i]);
};
true
'''


async def shot(page, name, title=None):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    if title:
        await page.ev(f'''(() => {{ const rep = __mts.rep(); const h = __mts.head(rep, {json.dumps(title)});
          if (h) rep.body.scrollTop = h.getBoundingClientRect().top - rep.body.getBoundingClientRect().top + rep.body.scrollTop - 8; }})()''')
    await asyncio.sleep(1.0)
    await page.shot(os.path.join(SHOTS, name))


async def act(page, js, timeout=600):
    """Run an action that redraws the last report and wait until it is done."""
    return await page.ev(f'''(async () => {{ const rep = __mts.rep(); const d = __mts.done(rep); const out = await (async () => {{ {js} }})(); await d; return out; }})()''', timeout=timeout)


async def open_report(page, roles, options=None):
    return await page.ev(f'''(async () => {{
      const t = SM.app.current; const P = SM.platforms.get('multits'); const ids = {{}};
      for (const [k, names] of Object.entries({json.dumps(roles)})) ids[k] = names.map((n) => t.col(n).id);
      const rep = SM.app.openReport(P, {{ roles: ids, options: {json.dumps(options or {})} }}, t);
      await __mts.done(rep);
      return {{ outlines: __mts.outlines(rep), ...__mts.problems(rep) }};
    }})()''', timeout=600)


# ---- help for every input: the (i) of the launch dialog, of the forms and of the report's controls
HELP_JS = r'''
window.__hp = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  async waitNew(n0, sel) {
    for (let i = 0; i < 300; i++) { const d = [...document.querySelectorAll(sel)]; if (d.length > n0) return d[d.length - 1]; await this.sleep(50); }
    return null;
  },
  // The open (i) panel: its title and sections, each a heading with its [name, text] entries.
  panel() {
    const p = document.getElementById('kvot-info-panel');
    if (!p) return null;
    const sections = [{ heading: null, entries: [] }];
    for (const node of p.querySelector('.info-panel-body').children) {
      if (node.tagName === 'H3') sections.push({ heading: node.textContent, entries: [] });
      else if (node.matches('dl.info-choices')) {
        const dt = [...node.children].filter((x) => x.tagName === 'DT'), dd = [...node.children].filter((x) => x.tagName === 'DD');
        dt.forEach((t, i) => sections[sections.length - 1].entries.push([t.textContent, dd[i] ? dd[i].textContent : '']));
      }
    }
    return { title: p.querySelector('.info-panel-title').textContent, headings: sections.map((s) => s.heading).filter(Boolean), sections: sections.filter((s) => s.heading || s.entries.length) };
  },
  // Click an (i), read its panel, close it.
  async open(btn) {
    if (!btn) return null;
    btn.click();
    await this.sleep(80);
    const out = { key: btn.dataset.info, ...this.panel() };
    KvotInfo.close();
    return out;
  },
  audit() { const a = KvotInfo.audit(); return { noTopic: a.noTopic, brokenMore: a.brokenMore }; },
  showTable(name) { const t = SM.app.tables.find((x) => x.name === name); if (t) SM.app.showTab(SM.app.tabOf(t)); return !!t; },
  // Cast columns into a role of a launch dialog.
  cast(d, names, role) {
    const items = [...d.querySelectorAll('.sm-pick-list li')];
    names.forEach((n, i) => {
      const li = items.find((x) => x.textContent === n);
      if (!li) throw new Error('no column ' + n);
      li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, ctrlKey: i > 0 }));
    });
    [...d.querySelectorAll('.sm-role .sm-btn')].find((b) => b.textContent === role).click();
  },
  choose(d, aria, value) { const s = d.querySelector(`select[aria-label="${aria}"]`); s.value = value; s.dispatchEvent(new Event('change', { bubbles: true })); },
  // A launch dialog's (i) after prep(dialog), audited while the dialog is open; then Cancel.
  async launch(id, prep) {
    const n0 = document.querySelectorAll('.sm-launch-dialog').length;
    SM.app.launch(id);
    const d = await this.waitNew(n0, '.sm-launch-dialog');
    if (!d) throw new Error('no launch dialog');
    if (prep) { await prep(d); await this.sleep(80); }
    const info = await this.open(d.querySelector('.sm-dialog-head .info-btn'));
    const audit = this.audit();
    const L = SM.platforms.get(id).launch;
    [...d.querySelectorAll('.sm-actions .sm-btn')].find((b) => b.textContent === 'Cancel').click();
    await this.sleep(60);
    return { info, audit, roles: (L.roles || []).map((r) => r.label), options: (L.options || []).map((o) => o.label) };
  },
  head(rep, title) { return [...rep.body.querySelectorAll('.sm-ob-head')].find((h) => { const t = h.querySelector('h2, h3, h4'); return t && t.textContent === title; }); },
  // Pick from the red triangle of an outline (null: the top one), without waiting for a redraw.
  async menu(rep, title, path) {
    const h = title == null ? (rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head') || rep.body.querySelector('.sm-ob-head')) : this.head(rep, title);
    if (!h) throw new Error('no outline ' + title);
    h.querySelector('.sm-ob-menu').click();
    for (const label of path) {
      await this.sleep(40);
      const m = [...document.querySelectorAll('.sm-menu')].pop();
      const b = m && [...m.querySelectorAll('button')].find((x) => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === label);
      if (!b) { SM.ui.closeMenus(0); throw new Error('no menu item ' + label); }
      b.click();
    }
  },
  // A form that open() brings up: its fields' labels and its (i), audited while open; then closed.
  async form(open) {
    const n0 = document.querySelectorAll('.sm-dialog').length;
    await open();
    const d = await this.waitNew(n0, '.sm-dialog');
    if (!d) throw new Error('no form opened');
    const info = await this.open(d.querySelector('.sm-dialog-head .info-btn'));
    const audit = this.audit();
    const out = { title: d.querySelector('.sm-dialog-head h2').textContent, labels: [...d.querySelectorAll('.sm-form label')].map((l) => l.textContent), info, audit };
    d.querySelector('.sm-dialog-x').click();
    await this.sleep(60);
    return out;
  },
  // An outline's own (i).
  async outline(rep, title) { const h = this.head(rep, title); return h ? this.open(h.querySelector('.kvot-info-slot .info-btn')) : null; },
};
true
'''


def help_section(info, heading):
    """The [name, text] entries of a section of an (i) panel, as a dict; None when there is none."""
    for s in (info or {}).get('sections', []):
        if s['heading'] == heading:
            return dict(s['entries'])
    return None


async def check_launch_help(page, pid, settings=None, prep='null', what=None):
    """A launch dialog's (i): every role and option with its help, the fields
    of the platform's own part (settings), and a topic for every (i) while the
    dialog is open."""
    what = what or f'{pid}: the launch dialog'
    r = await page.ev(f'__hp.launch({json.dumps(pid)}, {prep})', timeout=300)
    if not isinstance(r, dict):
        check(f'{what}: opens', r, 'a dialog')
        return None
    info = r['info'] or {}
    roles = help_section(info, 'Roles') or {}
    check(f'{what}: its (i) lists every role', list(roles), r['roles'])
    check(f'{what}: every role has help beyond what it takes', [k for k, t in roles.items() if t.startswith('(') or len(t) < 80], [])
    check(f'{what}: one Roles section (the topic\'s gives way to it)', info.get('headings', []).count('Roles'), 1)
    opts = help_section(info, 'Options') or {}
    check(f'{what}: its (i) lists every option', list(opts), r['options'])
    check(f'{what}: every option has help', [k for k, t in opts.items() if len(t) < 60], [])
    if settings is not None:
        got = help_section(info, 'Settings') or {}
        check(f'{what}: its (i) explains the fields of the platform\'s own part', list(got), settings)
        check(f'{what}: none of them in a word', [k for k, t in got.items() if len(t) < 30], [])
    check(f'{what}: every (i) has a topic while it is open', r['audit']['noTopic'], [])
    check(f'{what}: every Help link has a target', r['audit']['brokenMore'], [])
    return info


async def check_form_help(page, open_js, fields, what):
    """A form's (i) lists every field with its help, in order (fields: the names shown)."""
    r = await page.ev(f'__hp.form(async () => {{ {open_js} }})', timeout=300)
    if not isinstance(r, dict):
        check(f'{what}: opens', r, 'a dialog')
        return None
    got = help_section(r['info'], 'Fields') or {}
    check(f'{what}: its (i) explains every field', list(got), fields)
    check(f'{what}: none of them in a word', [k for k, t in got.items() if len(t) < 30], [])
    check(f'{what}: every (i) has a topic while it is open', r['audit']['noTopic'], [])
    return r


async def check_controls_help(page, rep_js, title, names, what, heading='In the report'):
    """An outline's (i) explains the controls inside the report, in a section of choices."""
    info = await page.ev(f'__hp.outline({rep_js}, {json.dumps(title)})')
    got = help_section(info, heading) or {}
    check(f'{what}: its (i) explains the controls in the report', list(got), names)
    check(f'{what}: none of them in a word', [k for k, t in got.items() if len(t) < 30], [])
    return info


async def main():
    page = await open_page(f'{BASE}/smui.html?example=macro')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    check('the multits module imports', await page.ev('SM.engine.failed.filter(f => f.module === "multits").map(f => f.error)'), [])
    check('its backend functions are there', await page.ev('["multits.series", "multits.select_order", "multits.var", "multits.granger", "multits.irf", "multits.fevd", "multits.forecast", "multits.johansen", "multits.vecm", "multits.engle_granger"].every(n => SM.engine.has(n))'), True)
    await page.ev(HELPERS)
    menu = await page.ev('''(() => { const it = SM.app.menuItems("Analyze").find(i => i.label === "Specialized Modeling"); const sub = typeof it.submenu === "function" ? it.submenu() : it.submenu; return sub.map(i => i.label); })()''')
    menu = menu or []
    at = menu.index('Multivariate Time Series…') if 'Multivariate Time Series…' in menu else None
    check('Analyze > Specialized Modeling lists Multivariate Time Series after Time Series', at is not None and at > 0 and menu[at - 1] == 'Time Series…', True)
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    check('the Help tab lists the platform', await page.ev('!!document.getElementById("help-p-multits")'), True)
    ex = await page.ev('''(() => { const f = SM.app.menuItems("File").find(i => i.label === "Examples"); const sub = typeof f.submenu === "function" ? f.submenu() : f.submenu;
      return { file: sub.map(i => i.label).filter(l => l.startsWith('Quarterly macro')), home: [...document.querySelectorAll('.sm-exitem strong')].map(s => s.textContent).filter(l => l.startsWith('Quarterly macro')),
        t: SM.app.current.name, n: SM.app.current.nrows, cols: SM.app.current.columns.map(c => c.name), fmt: SM.app.current.col('quarter').format }; })()''')
    check('the example is in File > Examples and on the Home tab', (len(ex['file']), len(ex['home'])), (1, 1))
    check('?example=macro opens it: 160 quarters', (ex['t'], ex['n'], ex['cols'], ex['fmt']), ('Quarterly macro', 160, ['quarter', 'growth', 'inflation', 'interest rate', 'income', 'consumption'], {'kind': 'date'}))

    # ---- the launch dialog
    r = await page.ev('''(async () => {
      SM.app.launch('multits');
      await new Promise(r => setTimeout(r, 200));
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { const li = items.find(li => li.textContent === name); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === label);
      const ok = () => [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
      pick('growth'); role('Y, Time Series').click();
      ok();
      const one = dlg.querySelector('.sm-launch-msg').textContent;
      pick('inflation'); role('Y, Time Series').click();
      pick('interest rate'); role('Y, Time Series').click();
      pick('quarter'); role('X, Time ID').click();
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      const opts = [...dlg.querySelectorAll('.sm-launch-opts label')].map(l => l.textContent);
      const lists = [...dlg.querySelectorAll('.sm-role-list')].map(u => u.textContent);
      ok();
      const rep = __mts.rep();
      await __mts.done(rep);
      return { one, roles, opts, lists, title: rep.title, open: !!document.querySelector('.sm-launch-dialog'), outlines: __mts.outlines(rep), ...__mts.problems(rep) };
    })()''', timeout=600)
    check('one Y is refused', r['one'], 'Y, Time Series: choose at least 2 columns')
    check('the roles', r['roles'], ['Y, Time Series', 'X, Time ID', 'Exogenous', 'By'])
    check('the options', [o.split('\n')[0] for o in r['opts']][:3], ['Maximum Lag for Selection', 'Forecast Periods', 'IRF Horizon'])
    check('cast', r['lists'][:2], ['growthinflationinterest rate', 'quarter'])
    check('report title', r['title'], 'Multivariate Time Series')
    want = ['Stationarity Summary', 'Lag Order Selection', 'Vector Autoregression VAR(2)', 'Model Summary', 'Parameter Estimates', 'Equation growth',
            'Residual Correlation', 'Stability', 'Whiteness Test (Portmanteau)', 'Normality Test (Jarque-Bera)', 'Granger Causality', 'Instantaneous Causality',
            'Impulse Response', 'Forecast Error Variance Decomposition', 'Forecast']
    check('the default outlines, the lag by AIC', [o for o in want if o in r['outlines']], want)
    check('no errors, no warnings (the example is stationary)', (r['errors'], r['warns']), ([], []))
    await shot(page, 'mts-01-top.png')

    # ---- numbers against the page's own arithmetic
    js = await page.ev('''(() => { const t = SM.app.current; const v = t.col('growth').values; const n = v.length; const m = v.reduce((a, b) => a + b, 0) / n;
      return { mean: m, sd: Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / (n - 1)) }; })()''')
    st_rows = await page.ev('__mts.rtRows(__mts.rep(), "Stationarity Summary")')
    check.near('Stationarity Summary: growth mean as computed in the page', st_rows[0]['mean'], js['mean'], 1e-12)
    check.near('... and its SD', st_rows[0]['sd'], js['sd'], 1e-12)
    check('... all three stationary', [x['verdict'] for x in st_rows], ['stationary'] * 3)
    ols = await page.ev('''(() => { const t = SM.app.current; const s = ['growth', 'inflation', 'interest rate'].map(n => t.col(n).values);
      return [0, 1, 2].map(e => __ols(s, e, 2)); })()''')
    for e, name in enumerate(['growth', 'inflation', 'interest rate']):
        rows = await page.ev(f'__mts.rtRows(__mts.rep(), "Equation {name}")')
        got = [x['estimate'] for x in rows]
        check(f'VAR(2) equation {name}: the coefficients are least squares computed in the page', len(got) == 7 and all(abs(a - b) <= 1e-8 * max(1, abs(b)) for a, b in zip(got, ols[e])), True)
    terms = await page.ev('__mts.rtRows(__mts.rep(), "Equation growth").map(r => r.term)')
    check("JMP-style terms", terms, ['Intercept', 'growth(t−1)', 'inflation(t−1)', 'interest rate(t−1)', 'growth(t−2)', 'inflation(t−2)', 'interest rate(t−2)'])
    lag = await page.ev('''(() => { const rep = __mts.rep(); const h = __mts.head(rep, 'Lag Order Selection'); const t = h.parentElement.querySelector('table.sm-rt');
      return { heads: [...t.querySelectorAll('thead th')].map(th => th.textContent), mins: t.querySelectorAll('td.mts-min').length, chosen: [...t.querySelectorAll('tr.mts-chosen td')].map(td => td.textContent)[0], rows: t.querySelectorAll('tbody tr').length }; })()''')
    check('Lag Order Selection: lags 0 to 8, AIC BIC FPE HQIC, four minima marked, lag 2 in use', (lag['heads'], lag['mins'], lag['chosen'], lag['rows']), (['Lag', 'AIC', 'BIC', 'FPE', 'HQIC'], 4, '2', 9))
    ax = await page.ev('''(async () => { const p = __mts.plot(__mts.rep(), 'Time Series Graph'); await p.draw(); return { type: p.box._fullLayout.xaxis.type, x0: p.traces[0].x[0], n: p.traces[0].x.length, k: p.traces.filter(t => t.name).length }; })()''')
    check('the Time ID gives a date axis, the three series on it', ax, {'type': 'date', 'x0': '1986-01-01', 'n': 160, 'k': 3})
    check('forecasts continue the quarters', await page.ev('__mts.note(__mts.rep(), "Forecast", "12 periods ahead, from 2026-01-01 to 2028-10-01")'), True)

    # ---- linking both ways
    r = await page.ev('''(async () => {
      const rep = __mts.rep(); const t = rep.table; const p = __mts.plot(rep, 'Time Series Graph');
      p._click({ points: [{ curveNumber: 1, pointNumber: 40 }], event: {} });
      const sel = t.selectedRows();
      t.select([5, 6, 7]);
      await new Promise(r => setTimeout(r, 150));
      const sp = p.box.data[2].selectedpoints;
      t.select([]);
      return { sel, sp: Array.from(sp || []) };
    })()''')
    check('a click on a point selects its row', r['sel'], [40])
    check('a table selection lights up the points', r['sp'], [5, 6, 7])

    # ---- the lag: a click on a line fixes it, Choose Lag By picks the criterion
    await act(page, '''const rep = __mts.rep(); const t = __mts.head(rep, 'Lag Order Selection').parentElement.querySelector('table.sm-rt'); t.querySelectorAll('tbody tr')[1].click(); return true;''')
    outl = await page.ev('__mts.outlines(__mts.rep())')
    check('a click on lag 1 fits a VAR(1)', 'Vector Autoregression VAR(1)' in outl, True)
    await act(page, '''await __mts.menu(__mts.rep(), 'Lag Order Selection', ['Choose Lag By', 'BIC']); return true;''')
    bic = await page.ev('''(() => { const L = __mts.rtRows(__mts.rep(), 'Lag Order Selection'); let b = 0; L.forEach((r, i) => { if (r.bic < L[b].bic) b = i; }); return L[b].lag; })()''')
    outl = await page.ev('__mts.outlines(__mts.rep())')
    check('Choose Lag By > BIC fits the lag of the smallest BIC', f'Vector Autoregression VAR({max(1, bic)})' in outl, True)
    await act(page, '''await __mts.menu(__mts.rep(), null, ['Choose Lag By', 'AIC']); return true;''')
    check('... and back to AIC from the report\'s red triangle', 'Vector Autoregression VAR(2)' in await page.ev('__mts.outlines(__mts.rep())'), True)

    # ---- Granger causality
    g = await page.ev('''(async () => { const rep = __mts.rep(); const rows = __mts.rtRows(rep, 'Granger Causality'); const p = __mts.plot(rep, 'Granger causality p-values'); await p.draw();
      return { n: rows.length, others: rows.filter(r => r.causing === 'all the others').length, z: p.traces[0].z.length, heads: [...__mts.head(rep, 'Granger Causality').parentElement.querySelector('table.sm-rt').querySelectorAll('thead th')].map(th => th.textContent),
        gi: rows.find(r => r.causing === 'growth' && r.caused === 'inflation').p }; })()''')
    check('Granger: every ordered pair and all the others together, as a matrix and a table', (g['n'], g['others'], g['z']), (9, 3, 4))
    check('... F tests', g['heads'][:5], ['Causing', 'Caused', 'F Ratio', 'DF Num', 'DF Den'])
    check('... growth Granger-causes inflation in the example', g['gi'] < 0.001, True)
    await act(page, '''await __mts.menu(__mts.rep(), 'Granger Causality', ['Wald ChiSquare Test']); return true;''')
    check('... or Wald chi-square tests', await page.ev('''[...__mts.head(__mts.rep(), 'Granger Causality').parentElement.querySelector('table.sm-rt').querySelectorAll('thead th')].map(th => th.textContent)[2]'''), 'ChiSquare')
    await shot(page, 'mts-02-granger.png', 'Residual Correlation')

    # ---- impulse responses: bands, cumulative, orthogonalization, the Cholesky ordering
    ir = await page.ev('''(async () => { const p = __mts.plot(__mts.rep(), 'Impulse responses'); await p.draw(); return { cells: p.box._fullLayout.annotations.length, first: p.box._fullLayout.annotations[0].text, fills: p.traces.filter(t => t.fill === 'tonexty').length }; })()''')
    check('Impulse Response: a 3 × 3 grid, impulse → response, with bands', ir, {'cells': 9, 'first': 'growth → growth', 'fills': 9})
    check('... asymptotic bands, said so', await page.ev('__mts.note(__mts.rep(), "Impulse Response", "asymptotic bands")'), True)
    await act(page, '''await __mts.menu(__mts.rep(), 'Impulse Response', ['Confidence Bands', 'Monte Carlo']); return true;''', timeout=900)
    mc = await page.ev('''(() => { const rep = __mts.rep(); const rows = __mts.rtRows(rep, 'Impulse Response Table'); return { note: __mts.note(rep, 'Impulse Response', 'Monte Carlo bands') && __mts.note(rep, 'Impulse Response', '20260926'), width: Math.max(...rows.map(r => r.upper - r.lower)) }; })()''')
    check('Monte Carlo bands: said so, with the seed', mc['note'], True)
    check('... and with a width (statsmodels\' integer seed would give none)', mc['width'] > 0.01, True)
    await act(page, '''await __mts.menu(__mts.rep(), 'Impulse Response', ['Cumulative']); return true;''', timeout=900)
    check('Cumulative responses', await page.ev('__mts.note(__mts.rep(), "Impulse Response", "Cumulative responses")'), True)
    await act(page, '''await __mts.menu(__mts.rep(), 'Impulse Response', ['Orthogonalized (Cholesky)']); return true;''', timeout=900)
    check('... not orthogonalized', await page.ev('__mts.note(__mts.rep(), "Impulse Response", "Not orthogonalized")'), True)
    await act(page, '''await __mts.menu(__mts.rep(), 'Impulse Response', ['Orthogonalized (Cholesky)']); return true;''', timeout=900)
    await act(page, '''await __mts.menu(__mts.rep(), 'Impulse Response', ['Cumulative']); return true;''', timeout=900)
    await act(page, '''await __mts.menu(__mts.rep(), 'Impulse Response', ['Confidence Bands', 'Asymptotic']); return true;''', timeout=900)
    title = await act(page, '''await __mts.menu(__mts.rep(), 'Impulse Response', ['Cholesky Ordering…']); return await __mts.form({ '1st': 'interest rate', '2nd': 'growth', '3rd': 'inflation' }, 'OK');''')
    check('the Cholesky Ordering dialog', title, 'Cholesky Ordering')
    ordr = await page.ev('''(async () => { const rep = __mts.rep(); const p = __mts.plot(rep, 'Impulse responses'); await p.draw(); const t = SM.app.current;
      return { first: p.box._fullLayout.annotations[0].text, fevd: __mts.note(rep, 'Forecast Error Variance Decomposition', 'the Cholesky ordering interest rate, growth, inflation'),
        stored: rep.spec.options.order.map(id => t.col(id).name) }; })()''')
    check('the ordering reorders the grid and the decomposition, stored as column ids', ordr, {'first': 'interest rate → interest rate', 'fevd': True, 'stored': ['interest rate', 'growth', 'inflation']})
    h0 = await page.ev('''(() => { const rows = __mts.rtRows(__mts.rep(), 'Impulse Response Table'); return rows.filter(r => r.h === 0 && r.response === 'interest rate' && r.impulse !== 'interest rate').map(r => r.value); })()''')
    check('... the first series answers no other shock at impact', h0, [0, 0])
    fv = await page.ev('''(async () => { const p = __mts.plot(__mts.rep(), 'Variance decomposition'); await p.draw(); const k = 3, H = p.traces[0].x.length;
      let worst = 0; for (let i = 0; i < k; i++) for (let h = 0; h < H; h++) { let s = 0; for (let j = 0; j < k; j++) s += p.traces[i * k + j].y[h]; worst = Math.max(worst, Math.abs(s - 1)); } return { worst, H }; })()''')
    check('FEVD: the shares add to 1 at every step', (fv['worst'] < 1e-9, fv['H']), (True, 10))
    await shot(page, 'mts-03-irf.png', 'Impulse Response')

    # ---- Save Forecasts and Save Residuals
    r = await page.ev('''(async () => { const before = SM.app.tables.length; await __mts.menu(__mts.rep(), 'Forecast', ['Save Forecasts']); await new Promise(r => setTimeout(r, 200));
      const t = SM.app.tables[SM.app.tables.length - 1]; const time = t.columns[0];
      return { added: SM.app.tables.length - before, name: t.name, cols: t.columns.map(c => c.name).slice(0, 5), rows: t.nrows, fmt: time.format && time.format.kind, last: time.values[t.nrows - 1], lower: t.columns[3].values[t.nrows - 1] < t.columns[2].values[t.nrows - 1] }; })()''')
    check('Save Forecasts makes a new table', (r['added'], r['name'], r['rows']), (1, 'VAR(2) forecasts', 172))
    check('... with the time, data, predictions and limits', r['cols'], ['quarter', 'Actual growth', 'Predicted growth', 'Lower CL (0.95) growth', 'Upper CL (0.95) growth'])
    check('... the quarters continue as dates', (r['fmt'], r['last']), ('date', await page.ev('Date.UTC(2028, 9, 1)')))
    check('... the lower limit below the forecast', r['lower'], True)
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports[SM.app.reports.length - 1]))')
    r = await page.ev('''(async () => { const rep = __mts.rep(); const t = rep.table; const before = t.columns.length; await __mts.menu(rep, 'Vector Autoregression VAR(2)', ['Save Residuals']); await new Promise(r => setTimeout(r, 400));
      const cols = t.columns.slice(before); const out = { names: cols.map(c => c.name), n: cols.map(c => c.values.filter(Number.isFinite).length), first: cols[0].values[1], third: Number.isFinite(cols[0].values[2]) };
      for (const c of cols) t.removeColumn(c.id); return out; })()''')
    check('Save Residuals adds a column per equation, the first two rows empty', (r['names'], r['n'], r['first'], r['third']),
          (['Residual growth', 'Residual inflation', 'Residual interest rate'], [158, 158, 158], None, True))

    # ---- excluded rows are filled for the VAR, and the report says so
    r = await page.ev('''(async () => {
      const rep = __mts.rep(); const t = rep.table;
      t.setState([30, 31], 'excluded', true);
      const stale = !rep.staleEl.hidden;
      const d = __mts.done(rep); rep.run(); await d;
      const p = __mts.plot(rep, 'Time Series Graph');
      const out = { stale, gap: [p.traces[0].y[30], p.traces[0].y[31]], note: rep.body.textContent.includes('filled by linear interpolation'), note2: rep.body.textContent.includes('2 excluded rows count as missing values'), ...__mts.problems(rep) };
      t.setState([30, 31], 'excluded', false);
      const d2 = __mts.done(rep); rep.run(); await d2;
      return out;
    })()''', timeout=600)
    check('an exclusion makes the report stale', r['stale'], True)
    check('excluded rows are gaps in the graph, filled for the VAR, and said so', (r['gap'], r['note'], r['note2'], r['errors']), ([None, None], True, True, []))

    # ---- Transform > Difference and Log
    await act(page, '''await __mts.menu(__mts.rep(), null, ['Transform', 'Difference (d = 1)']); return true;''')
    r = await page.ev('''(() => { const rep = __mts.rep(); return { st: __mts.rtRows(rep, 'Stationarity Summary').map(r => r.series), n: __mts.rtRows(rep, 'Stationarity Summary')[0].n,
      eq: __mts.outlines(rep).filter(o => o.startsWith('Equation')), fc: __mts.note(rep, 'Forecast', 'In the units of the table'), ...__mts.problems(rep) }; })()''')
    check('Difference: the series as analysed are the differences', (r['st'], r['n']), (['Δ growth', 'Δ inflation', 'Δ interest rate'], 159))
    check('... the equations too', r['eq'], ['Equation Δ growth', 'Equation Δ inflation', 'Equation Δ interest rate'])
    check('... and the forecasts come back in the units of the table', (r['fc'], r['errors']), (True, []))
    await act(page, '''await __mts.menu(__mts.rep(), null, ['Transform', 'Difference (d = 1)']); return true;''')

    # ---- the options survive a saved and reopened project
    r = await page.ev('''(async () => {
      const rep = __mts.rep(); const t = rep.table;
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      const n = SM.app.reports.length;
      SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const r2 = SM.app.reports[n];
      await __mts.done(r2);
      const p = r2.plots.find(p => p.opts.title === 'Impulse responses');   // in a tab not shown: the layout, not the drawing
      const out = { first: p.userLayout.annotations[0].text, kind: r2.body.textContent.includes('Wald χ² test'), ...__mts.problems(r2) };
      SM.app.closeReport(r2); SM.app.closeTable(SM.app.tables[SM.app.tables.length - 1]);
      return out;
    })()''', timeout=600)
    await page.ev('document.querySelectorAll(".sm-dialog .sm-btn.primary").forEach(b => b.click())')
    check('a reopened project keeps the Cholesky ordering and the Wald tests', (r['first'], r['kind'], r['errors']), ('interest rate → interest rate', True, []))

    # ---- cointegration on the example's pair
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Quarterly macro")))')
    r = await open_report(page, {'y': ['income', 'consumption'], 'time': ['quarter']})
    check('income and consumption look nonstationary: the report says difference or cointegration', any('nonstationary' in w for w in r['warns']), True)
    await act(page, '''await __mts.menu(__mts.rep(), null, ['Cointegration']); return true;''')
    outl = await page.ev('__mts.outlines(__mts.rep())')
    for o in ('Cointegration', 'Johansen Cointegration Test', 'VECM (rank 1)', 'Loading Coefficients (α)', 'Cointegrating Vectors (β)', 'Short-Run Coefficients (Γ)', 'VECM Forecast', 'Engle-Granger Test'):
        check(f'outline {o}', o in outl, True)
    jt = await page.ev(table_under_js('Johansen Cointegration Test'))
    check('Johansen: trace and max-eigenvalue with their critical values', jt[0], ['H0: Rank', 'Eigenvalue', 'Trace', '90%', '95%', '99%', 'Max-Eigen', '90%', '95%', '99%'])
    kv = dict(tuple(x) for x in await page.ev(table_under_js('Johansen Cointegration Test', 1)))
    check('... rank 1 for the cointegrated pair', kv.get('Selected Rank'), '1')
    beta = await page.ev('__mts.rtRows(__mts.rep(), "Cointegrating Vectors (β)")')
    check('β normalised on income; consumption near −1/0.8', (beta[0]['estimate'], beta[0]['se'], abs(beta[1]['estimate'] + 1.25) < 0.05), (1, None, True))
    eg = await page.ev('__mts.rtRows(__mts.rep(), "Engle-Granger Test")')
    check('Engle-Granger rejects no cointegration both ways', [x['p'] < 0.01 for x in eg], [True, True])
    r = await page.ev('''(async () => { const before = SM.app.tables.length; await __mts.menu(__mts.rep(), 'Cointegration', ['Save VECM Forecasts']); await new Promise(r => setTimeout(r, 200));
      const t = SM.app.tables[SM.app.tables.length - 1]; return { added: SM.app.tables.length - before, name: t.name, rows: t.nrows, cols: t.columns.length }; })()''')
    check('Save VECM Forecasts makes a table', r, {'added': 1, 'name': 'VECM (rank 1) forecasts', 'rows': 172, 'cols': 9})
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports[SM.app.reports.length - 1]))')
    await act(page, '''await __mts.menu(__mts.rep(), 'Cointegration', ['Johansen Test Options…']); return await __mts.form({ 'Lagged differences (k_ar_diff)': 2, 'Choose the rank by': 'maxeig' }, 'OK');''')
    kv = dict(tuple(x) for x in await page.ev(table_under_js('Johansen Cointegration Test', 1)))
    check('Johansen Test Options: two lagged differences, the maximum eigenvalue test', (kv.get('Lagged Differences'), kv.get('Chosen By')), ('2', 'maximum eigenvalue test at 5%'))
    await shot(page, 'mts-04-coint.png', 'Cointegration')
    script = await page.ev('__mts.rep().pythonScript()')
    check('the Python script has the fits', all(s in script for s in ('from statsmodels.tsa.api import VAR', 'coint_johansen', 'VECM(', 'coint(', "asfreq('QS-OCT')")), True)

    # ---- an exogenous column
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Quarterly macro")))')
    r = await open_report(page, {'y': ['growth', 'inflation'], 'time': ['quarter'], 'exog': ['interest rate']})
    ms = dict(tuple(x) for x in await page.ev(table_under_js('Model Summary')))
    terms = await page.ev('__mts.rtRows(__mts.rep(), "Equation growth").map(r => r.term)')
    check('Exogenous: in the summary and a term of every equation', (ms.get('Exogenous'), terms[:3], r['errors']), ('interest rate', ['Intercept', 'interest rate', 'growth(t−1)'], []))
    check('... the forecasts hold its last value, and say so', await page.ev('__mts.note(__mts.rep(), "Forecast", "held for the remaining 12 periods")'), True)

    # ---- statsmodels' documented example: macrodata, log differences, VAR(2)
    r = await page.ev('''(async () => {
      const d = await SM.engine.call('datasets.load', { name: 'macrodata' });
      const col = (n) => d.columns.find(c => c.name === n).values;
      const year = col('year'), q = col('quarter');
      const t = new SM.Table({ name: 'macrodata', columns: [
        { name: 'date', dataType: 'numeric', format: { kind: 'date' }, values: year.map((y, i) => Date.UTC(y, 3 * (q[i] - 1), 1)) },
        ...['realgdp', 'realcons', 'realinv'].map(n => ({ name: n, dataType: 'numeric', values: col(n) })) ] });
      SM.app.addTable(t);
      return t.nrows; })()''', timeout=300)
    check('macrodata from statsmodels.datasets', r, 203)
    r = await open_report(page, {'y': ['realgdp', 'realcons', 'realinv'], 'time': ['date']}, {'log': True, 'diff': True, 'lagFixed': 2, 'maxlags': 15})
    check('the documented example: no errors', r['errors'], [])
    rows = await page.ev('__mts.rtRows(__mts.rep(), "Equation Δ log realgdp")')
    DOC = [0.001527, -0.279435, 0.675016, 0.033219, 0.008221, 0.290458, -0.007321]
    check('the realgdp equation shows the coefficients statsmodels\' documentation prints', all(abs(x['estimate'] - d) <= 5.01e-7 for x, d in zip(rows, DOC)), True)
    ms = dict(tuple(x) for x in await page.ev(table_under_js('Model Summary')))
    check('... and its summary (Log likelihood 1962.57, AIC −27.9293, FPE 7.42129e-13)', (ms.get('Observations Used'), ms.get('Log Likelihood'), ms.get('AIC'), ms.get('FPE')), ('200', '1962.571', '−27.92934', '7.4213e-13'))
    lags = await page.ev('__mts.rtRows(__mts.rep(), "Lag Order Selection")')
    check('... and the documented lag order table: AIC smallest at 3, BIC at 1', (min(lags, key=lambda x: x['aic'])['lag'], min(lags, key=lambda x: x['bic'])['lag'], round(lags[3]['aic'], 2)), (3, 1, -28.04))

    # ---- By: one report per level
    r = await page.ev('''(async () => {
      const src = SM.app.tables.find(t => t.name === 'Quarterly macro');
      const q = src.col('quarter').values, g = src.col('growth').values, i = src.col('inflation').values;
      const t = new SM.Table({ name: 'Two regions', columns: [
        { name: 'region', dataType: 'character', values: [...q.map(() => 'North'), ...q.map(() => 'South')] },
        { name: 'quarter', dataType: 'numeric', format: { kind: 'date' }, values: [...q, ...q] },
        { name: 'growth', dataType: 'numeric', values: [...g, ...g.map((v, k) => v + Math.sin(k))] },
        { name: 'inflation', dataType: 'numeric', values: [...i, ...i.map((v, k) => 0.9 * v + 0.3 * Math.cos(k))] } ] });
      SM.app.addTable(t);
      const rep = SM.app.openReport(SM.platforms.get('multits'), { roles: { y: [t.col('growth').id, t.col('inflation').id], time: [t.col('quarter').id], by: [t.col('region').id] }, options: { forecast: 4 } }, t);
      await __mts.done(rep);
      const tops = [...rep.body.querySelectorAll('.sm-ob.level-0 > .sm-ob-head h2')].map(h => h.textContent);
      return { tops, vars: __mts.outlines(rep).filter(o => o.startsWith('Vector Autoregression')).length, ...__mts.problems(rep), note: rep.noteEl.textContent };
    })()''', timeout=600)
    check('By gives one report per level', r['tops'], ['Multivariate Time Series region=North', 'Multivariate Time Series region=South'])
    check('... each with its VAR, without errors', (r['vars'], r['errors']), (2, []))
    check('... from 320 rows in two groups', r['note'], 'Two regions: 320 of 320 rows, 2 groups')

    # ---- small multiples, the dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "multits")))')
    await page.ev('''(async () => { const rep = SM.app.reports.find(r => r.platform.id === 'multits'); const d = __mts.done(rep); rep.spec.options.multiples = true; rep.run(); await d; })()''', timeout=600)
    mult = await page.ev('''(async () => { const rep = SM.app.reports.find(r => r.platform.id === 'multits'); const p = rep.plots.find(p => p.opts.title === 'Time Series Graph'); await p.draw(); return Object.keys(p.box._fullLayout).filter(k => /^yaxis\\d*$/.test(k)).length; })()''')
    check('Small Multiples: a graph per series', mult, 3)
    await page.ev('''(async () => { const rep = SM.app.reports.find(r => r.platform.id === 'multits'); const d = __mts.done(rep);
      KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark'); await d; })()''', timeout=600)
    await asyncio.sleep(1.0)
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "multits")))')
    pr = await page.ev('__mts.problems(SM.app.reports.find(r => r.platform.id === "multits"))')
    check('the dark theme redraws without errors', pr['errors'], [])
    await page.ev('SM.app.reports.find(r => r.platform.id === "multits").body.scrollTop = 0')
    await shot(page, 'mts-05-dark.png')
    await page.ev('''(() => { const rep = SM.app.reports.find(r => r.platform.id === 'multits'); const h = __mts.head(rep, 'Impulse Response'); rep.body.scrollTop = h.getBoundingClientRect().top - rep.body.getBoundingClientRect().top + rep.body.scrollTop - 8; })()''')
    await shot(page, 'mts-06-dark-irf.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await page.ev('''(async () => { const rep = SM.app.reports.find(r => r.platform.id === 'multits'); const d = __mts.done(rep); rep.run(); await d; })()''', timeout=600)
    await asyncio.sleep(1.2)
    check('no horizontal page scroll at phone width', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await page.ev('''(() => { const rep = SM.app.reports.find(r => r.platform.id === 'multits'); const h = __mts.head(rep, 'Lag Order Selection'); rep.body.scrollTop = h.getBoundingClientRect().top - rep.body.getBoundingClientRect().top + rep.body.scrollTop - 8; })()''')
    await shot(page, 'mts-07-phone.png')
    await page.ev('''(() => { const rep = SM.app.reports.find(r => r.platform.id === 'multits'); const h = __mts.head(rep, 'Impulse Response'); rep.body.scrollTop = h.getBoundingClientRect().top - rep.body.getBoundingClientRect().top + rep.body.scrollTop - 8; })()''')
    await shot(page, 'mts-08-phone-irf.png')

    # ---- help for every input: the launch dialog's (i), the forms' (i), the report's controls
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await page.ev(HELP_JS)
    check('help: back on the Quarterly macro table', await page.ev('__hp.showTable("Quarterly macro")'), True)
    await check_launch_help(page, 'multits', what='multits: the launch dialog')
    await page.ev('''(async () => { const t = SM.app.tables.find((x) => x.name === 'Quarterly macro'); const id = (n) => t.col(n).id;
      const rep = SM.app.openReport(SM.platforms.get('multits'), { roles: { y: ['income', 'consumption'].map(id), time: [id('quarter')] }, options: { coint: true } }, t);
      await new Promise((r) => rep.on('done', r)); SM.app.showTab(SM.app.tabOf(rep)); return rep.title; })()''', timeout=600)
    rep = 'SM.app.reports[SM.app.reports.length - 1]'
    var = f"[...{rep}.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].find((h) => h.textContent.startsWith('Vector Autoregression')).textContent"
    for path, fields, what in ((['Maximum Lag…'], ['Largest lag in the selection table'], 'Maximum Lag…'), (['Choose Lag By', 'Fixed Lag Order…'], ['Lag order p'], 'Fixed Lag Order…'),
                               (['Cholesky Ordering…'], ['1st, 2nd, …'], 'Cholesky Ordering…'), (['IRF Horizon…'], ['Periods after the shock'], 'IRF Horizon…'),
                               (['Number of Forecast Periods…'], ['Periods to forecast'], 'Number of Forecast Periods…')):
        await check_form_help(page, f"await __hp.menu({rep}, null, {json.dumps(path)})", fields, f'multits: {what}')
    await check_form_help(page, f"await __hp.menu({rep}, {var}, ['Whiteness Test Lags…'])", ['Residual autocorrelations up to lag h (more than p)'], 'multits: Whiteness Test Lags…')
    await check_form_help(page, f"await __hp.menu({rep}, 'Impulse Response', ['Monte Carlo Replications…'])", ['Simulated samples for the Monte Carlo bands'], 'multits: Monte Carlo Replications…')
    await check_form_help(page, f"await __hp.menu({rep}, 'Forecast Error Variance Decomposition', ['Horizon…'])", ['Forecast steps'], 'multits: the variance decomposition\'s Horizon…')
    await check_form_help(page, f"await __hp.menu({rep}, 'Cointegration', ['Johansen Test Options…'])", ['Deterministic terms (det_order)', 'Lagged differences (k_ar_diff)', 'Choose the rank by'], 'multits: Johansen Test Options…')
    await check_form_help(page, f"await __hp.menu({rep}, 'Cointegration', ['Cointegration Rank…'])", ['Rank of the VECM (1 to 1)'], 'multits: Cointegration Rank…')
    await check_controls_help(page, rep, 'Lag Order Selection', ['A line of the table'], 'multits: Lag Order Selection')

    # ---- the graphs' matplotlib code, every graph of every kind
    await chart_code(page)

    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
