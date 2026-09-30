#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Specialized Modeling >
Time Series, on the Monthly sales example.

The platform is in the menu; the launch dialog casts sales, month and the
inputs; the report shows the mean, SD and N and the lag 1 autocorrelation
computed in the page, a date axis, the ADF and KPSS tests; ARIMA, seasonal
ARIMA, ARIMA Model Group, a smoothing model, state space smoothing and a
transfer function are added through the red triangle and their dialogs,
and land in the Model Comparison table; forecasts continue the months; the
Report and Graph boxes and the model red triangles do what they say; Save
Columns makes a new table; a click on a point selects its row and a table
selection shows in the graph; excluded rows count as missing values; By
gives a report per level; the models survive a saved and reopened project;
the report draws in the dark theme and at phone width.

Then what JMP does not have, on the Business cycle and Monthly sales
examples: the Zivot-Andrews test in Stationarity Tests with its break date
and options; Regime Switching through its dialog (regimes, transition
matrix, durations, the shaded series and the linked probabilities, the
starts, Save Regime Probabilities); the Hodrick-Prescott, Baxter-King and
Christiano-Fitzgerald filters with Save Columns; ARDL with the long run and
the bounds test at the model's k, forecasts from the future inputs, and
Fit New with fixed orders; the seasonal subseries plot, linked; a
structural model with its components and Save Components; the Theta model
and statsmodels' own intervals; all of them in reopened projects, the
script, the dark theme and at phone width.

Then Forecast on Holdback from the launch dialog (the holdback columns
sorted by RMSE against the page's own arithmetic, the table's code run in
the page, the shaded span, Holdback Statistics, Save Columns with the Set
column and the forecast errors, Refit on All Rows), the benchmarks, the
moving average (its smoothed series and forecasts against the page's
arithmetic, Save Moving Average), Save Prediction Formula, Custom
constraints through their second dialog, Box-Cox, the averaged forecast,
the runs tests, rolling-origin cross-validation (every origin of Seasonal
Naive against the page's arithmetic), the multiplicative trends; a
reopened project, By, the dark theme, phone width and every new graph
against its code. And Time Series Forecast on the Store sales example:
the launch dialog, the value labels naming the series, the holdback RMSE
against the page's arithmetic, Forecasts, a row's click opening its
report, Save Results, BIC from the red triangle, a reopened project, By,
the graphs against their code, the dark theme and phone width.

Start a server on the repository root and headless Chrome on SMUI_HTTP_PORT
and SMUI_CDP_PORT (see README.md), then

    python3 resources/tests/smui/test-ui-timeseries.py

SMUI_SHOTS=<folder> saves screenshots. Exit status 0 when every check passes.
"""
import asyncio
import json
import math
import os
import re
import sys
from datetime import datetime

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine
from test_charts import GRAPHS_JS, PROBE_MORE, close, figures_from_outputs, strip_show

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


# ---- the graphs' matplotlib code --------------------------------------------------------------
# Every graph of a report (and every diagnostics chart, a table with a bar per
# row) has a code block under it, ending in plt.show(); the block runs in the
# page's own Python (SM.engine.runCell, as test_charts.GRAPHS_JS.run does it),
# with PROBE_MORE and the axes' left titles in place of plt.show(), and the
# figure it draws is compared with the Plotly graph: every line and set of
# points in its panel (dates in days), the bands, the reference lines, the
# shading, the panels' labels, the legend, the axis titles, the size.
LEFT = r'''
def _ts_left():
    import matplotlib.pyplot as _plt
    return [[ax.get_title(loc="left") for ax in _plt.figure(n).axes] for n in _plt.get_fignums()]
'''


def page_probe_ts(code):
    """The block, then its figures (PROBE_MORE, with each axes' left title) as one JSON line."""
    return (strip_show(code) + '\n' + PROBE_MORE + LEFT + '\nimport json as _json\n_f = _smui_figures_more()\n'
            'for _F, _L in zip(_f["figures"], _ts_left()):\n    for _A, _t in zip(_F["axes"], _L):\n        _A["left"] = _t\n'
            'print("SMUI-FIGURES " + _json.dumps(_f))\n')


# What else the graphs of a report hold (after __gr.graphs, in the same order):
# the line widths, the axes' types and ticks, the annotations, the legend;
# and the diagnostics charts, each with its rows and the block under it (under
# its row, for Cross Correlation's tables side by side).
TSG_JS = r'''
window.__tsg = {
  openAll(rep) { rep.body.querySelectorAll('.sm-ob.is-closed').forEach((s) => s._outline && s._outline.setOpen(true)); },
  extra(rep) {
    return [...rep.body.querySelectorAll('.js-plotly-plot')].map((p) => {
      const L = p.layout || {};
      const axes = {};
      for (const k of Object.keys(L)) if (/^[xy]axis\d*$/.test(k)) axes[k] = { type: L[k].type || null, ticktext: L[k].ticktext || null, title: L[k].title ? (typeof L[k].title === 'string' ? L[k].title : L[k].title.text) : null };
      return { widths: (p.data || []).map((d) => (d.line && d.line.width != null ? d.line.width : null)), axes, showlegend: !!L.showlegend,
        annotations: (L.annotations || []).map((a) => a.text), shapes: (L.shapes || []).map((s) => ({ type: s.type, xref: s.xref || 'x', yref: s.yref || 'y', x0: s.x0, x1: s.x1, y0: s.y0, y1: s.y1 })) };
    });
  },
  charts(rep) {
    return [...rep.body.querySelectorAll('table.sm-ts-corr')].map((t) => {
      const row = t.parentElement && t.parentElement.classList.contains('sm-ob-row') ? t.parentElement : null;
      const n = row ? row.nextElementSibling : t.nextElementSibling;
      return { caption: (t.querySelector('caption') || {}).textContent || '', rows: t._rt ? t._rt.rows : [], keys: t._rt ? t._rt.columns.map((c) => c.key) : [],
        code: n && n.matches('details.sm-code') ? n.querySelector('code').textContent : null };
    });
  },
};
true
'''
EPOCH = datetime(1970, 1, 1)
DATE_MIN, DATE_MAX = 1483228800000, 1764547200000   # 2017-01-01 and 2025-12-01 (UTC), a date window set with Axis Settings


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
    """Every line and scatter of an axes as finite points (x in the axis's units)."""
    out = [finite_pairs([q[0] for q in xy], [q[1] for q in xy]) for xy in A['xy_lines']]
    return out + [finite_pairs([q[0] for q in s['xy']], [q[1] for q in s['xy']]) for s in A['scatter']]


def check_graph(tag, g, ex, F, rel=1e-6):
    """A Plotly graph against the figure its code draws."""
    date = (ex['axes'].get('xaxis') or {}).get('type') == 'date'
    X = to_days if date else (lambda v: v)
    axes = [A for A in F['axes'] if not A.get('colorbar')]
    check(f'{tag}: the figure has the graph\'s size', F['size'], [g['w'] / 100, g['h'] / 100])
    check(f'{tag}: the graph\'s title', g['label'] in [F['suptitle']] + [A['title'] for A in axes], True)
    missing = []
    fills = [0] * len(axes)
    for tr, width in zip(g['traces'], ex['widths']):
        if tr.get('type') not in ('scatter', 'scattergl'):
            continue
        pts = finite_pairs([X(v) for v in tr.get('x') or []], tr.get('y') or [])
        if not pts:
            continue
        A = axes[axis_at(tr.get('yaxis'))]
        if tr.get('fill') in ('tonexty', 'tozeroy', 'toself'):
            fills[axis_at(tr.get('yaxis'))] += 1
        if width == 0:   # a band's edge that Plotly does not draw: the band is its fill
            continue
        if not any(same_points(pts, p, rel) for p in mpl_sets(A)):
            missing.append(tr.get('name'))
    check(f'{tag}: every line and set of points, in its panel', missing, [])
    check(f'{tag}: every band, in its panel', [len(A['polys']) for A in axes], fills)
    wrong = []
    for s in ex['shapes']:
        A = axes[axis_at(s['yref'])] if s['yref'] not in ('paper',) else axes[0]
        # a reference along y (Axis Settings) spans the panel: x in the axes' fractions ('x domain'), as matplotlib's axhline and axhspan
        xfrac = s['xref'] == 'paper' or s['xref'].endswith('domain')
        yfrac = s['yref'] == 'paper' or s['yref'].endswith('domain')
        if s['type'] == 'rect':
            ok = any(close([b['x'], b['x'] + b['w']], [s['x0'], s['x1']] if xfrac else [X(s['x0']), X(s['x1'])], 1e-9)
                     and (yfrac or close([b['y'], b['y'] + b['h']], [s['y0'], s['y1']], 1e-9)) for b in A['bars'])
        elif s['x0'] == s['x1'] and yfrac:
            ok = any(same_points(p, [(X(s['x0']), 0), (X(s['x0']), 1)], 1e-9) for p in mpl_sets(A))
        elif xfrac:
            ok = any(same_points(p, [(0, s['y0']), (1, s['y0'])], 1e-6) for p in mpl_sets(A))
        else:
            ok = any(same_points(p, [(X(s['x0']), s['y0']), (X(s['x1']), s['y1'])], 1e-6) for p in mpl_sets(A))
        if not ok:
            wrong.append(s)
    check(f'{tag}: every reference line and shading of the graph', wrong, [])
    words = [w for A in axes for w in (A['title'], A.get('left', ''))] + [t['s'] for A in axes for t in A['texts']]
    check(f'{tag}: the panels\' labels', [a for a in ex['annotations'] if a.replace('<br>', ' ') not in [w.replace('\n', ' ') for w in words]], [])
    if ex['showlegend']:
        want = [tr.get('name') for tr in g['traces'] if tr.get('showlegend') is not False and tr.get('name')]
        check(f'{tag}: the legend', F['legend'], want)
    if g['titles']['x']:
        check(f'{tag}: the x axis title', g['titles']['x'] in [A['xlabel'] for A in axes], True)
    if g['titles']['y'] is not None:
        check(f'{tag}: the y axis title', axes[0]['ylabel'], g['titles']['y'])
    if (ex['axes'].get('xaxis') or {}).get('type') == 'log':
        check(f'{tag}: a log axis', axes[0]['xscale'], 'log')
    tt = (ex['axes'].get('xaxis') or {}).get('ticktext')
    if tt:
        check(f'{tag}: the ticks, named', axes[0]['xticklabels'], tt)


CORR_CAPTIONS = ('Autocorrelation', 'Partial Autocorrelation', 'Residual Autocorrelation', 'Residual Partial Autocorrelation')


def check_chart(tag, c, F):
    """A diagnostics chart (a table with a bar per row) against its figure: the
    panel titled as the table's caption (Cross Correlation has one per input)."""
    A = next((a for a in F['axes'] if a['title'] == c['caption']), None)
    check(f'{tag}: a panel titled as the table', A is not None, True)
    if A is None:
        return
    key = next(k for k in ('r', 'v', 'c') if k in c['keys'])
    vals = [row.get(key) for row in c['rows']]
    check(f'{tag}: a bar per row, as long as the value', (len(A['bars']), close([b['w'] for b in A['bars']], vals, 1e-7, 1e-9)), (len(vals), True))
    check(f'{tag}: at the lags, lag by lag down', ([round(b['y'] + b['h'] / 2) for b in A['bars']], A['yinverted']), ([row['lag'] for row in c['rows']], True))
    if any('se' in row for row in c['rows']):
        # the correlations' marks from lag 1, cross correlations' at every lag (as the page draws them)
        every = c['caption'] not in CORR_CAPTIONS
        marks = sorted((round(y), x) for ln, xy in zip(A['lines'], A['xy_lines']) if ln['marker'] == '|' for x, y in xy)
        want = sorted((row['lag'], s * 2 * row['se']) for row in c['rows'] if row['lag'] or every for s in (1, -1))
        check(f'{tag}: the ±2 standard error marks', ([m[0] for m in marks] == [w[0] for w in want], close([m[1] for m in marks], [w[1] for w in want], 1e-7, 1e-12)), (True, True))


async def run_ts(page, code, table_js):
    """A block run in the page's Python: its figures, or an error."""
    out = await page.ev(f'__gr.run({json.dumps(page_probe_ts(code))}, {table_js})', timeout=600)
    if isinstance(out, str):
        return None, out
    try:
        got, err = figures_from_outputs(out.get('outputs'))
    except ValueError:
        return None, 'the figures do not fit in one output of the page\'s runner'
    return (got['figures'], None) if got is not None else (None, err)


def open_js(table, roles, options, before='', after=''):
    """JS that opens a Time Series report on the table named so (before: JS run
    first, with t the table; after: JS run once it is done, with rep), keeps it
    as window.__tsc and returns its title and problems."""
    return f'''(async () => {{ const t = SM.app.tables.find((x) => x.name === {json.dumps(table)}); SM.app.showTab(SM.app.tabOf(t));
      const id = (n) => t.col(n).id; const roles = {{}};
      for (const [k, names] of Object.entries({json.dumps(roles)})) roles[k] = names.map(id);
      {before}
      const rep = SM.app.openReport(SM.platforms.get('timeseries'), {{ roles, options: {json.dumps(options)} }}, t);
      await __ts.done(rep);
      {after}
      window.__tsc = rep;
      return {{ title: rep.title, ...__ts.problems(rep) }}; }})()'''


async def check_report_graphs(page, rep_js, table_js, what):
    """Every graph and diagnostics chart of a report: its block, run, against the page."""
    await page.ev(f'__tsg.openAll({rep_js})')
    r = await page.ev(f'(async () => {{ const rep = {rep_js}; const g = await __gr.graphs(rep); return {{ g, ex: __tsg.extra(rep), charts: __tsg.charts(rep), undrawn: __gr.take() }}; }})()', timeout=900)
    check(f'{what}: every graph of the report drawn', r['undrawn'], [])
    check(f'{what}: every graph with its code block under it, ending in plt.show()', [g['label'] for g in r['g'] if not (g['code'] and g['code'].rstrip().split('\n')[-1] == 'plt.show()')], [])
    check(f'{what}: every diagnostics chart with its code block under it', [c['caption'] for c in r['charts'] if not (c['code'] and c['code'].rstrip().split('\n')[-1] == 'plt.show()')], [])
    for g, ex in zip(r['g'], r['ex']):
        if not g['code']:
            continue
        F, err = await run_ts(page, g['code'], table_js)
        check(f'{what}: {g["label"]}: the code runs in the page, one figure', (err, len(F or [])), (None, 1))
        if F:
            check_graph(f'{what}: {g["label"]}', g, ex, F[0])
    for i, c in enumerate(r['charts']):
        if not c['code']:
            continue
        F, err = await run_ts(page, c['code'], table_js)
        check(f'{what}: chart {i + 1} ({c["caption"]}): the code runs in the page, one figure', (err, len(F or [])), (None, 1))
        if F:
            check_chart(f'{what}: chart {i + 1} ({c["caption"]})', c, F[0])
    return r


async def chart_code(page):
    """Reports that between them draw every kind of graph of the platform, with
    their options; every graph and chart checked against its code's figure."""
    await page.ev(GRAPHS_JS)
    await page.ev(TSG_JS)
    await page.ev('__gr.idle()')   # the reports run again by a change of theme are done
    rep, tbl = 'window.__tsc', 'window.__tsc.table'
    close_js = 'SM.app.closeReport(window.__tsc)'

    # the series and everything made from it: two rows excluded (gaps in the graphs), lines only, the Mean Line,
    # the variogram and AR coefficients, differences, the decompositions, the filters, the spectral density, a lag
    # plot, the subseries plot, cross correlations and the inputs' panel; the Zivot-Andrews test is on by default
    S = 'ts:sales|'
    opts = {'forecast': 12, S + 'points': False, S + 'meanLine': True, S + 'variogram': True, S + 'arcoef': True, S + 'spectral': True, S + 'lagPlot': 3,
            S + 'subseries': True, S + 'ccf': True,
            S + 'diffs': [{'id': 1, 'd': 1, 'D': 1, 's': 12, 'variogram': True, 'meanLine': True}, {'id': 2, 'd': 1, 'D': 0, 's': 12, 'lines': False}],
            S + 'decomps': [{'id': 1, 'kind': 'trend'}, {'id': 2, 'kind': 'cycle', 'units': 12, 'constant': True}, {'id': 3, 'kind': 'classical', 'period': 12, 'model': 'multiplicative'},
                            {'id': 4, 'kind': 'stl', 'period': 12, 'robust': True}],
            S + 'filters': [{'id': 1, 'kind': 'hp'}, {'id': 2, 'kind': 'bk'}, {'id': 3, 'kind': 'cf', 'drift': True}]}
    r = await page.ev(open_js('Monthly sales', {'y': ['sales'], 'time': ['month'], 'inputs': ['promotion', 'temperature']}, opts,
                              before="t.setState([30, 31], 'excluded', true);"), timeout=900)
    check('charts: the series report opens without errors', r['errors'], [])
    g = await check_report_graphs(page, rep, tbl, 'charts: series')
    labels = [x['label'] for x in g['g']]
    check('charts: series: its graphs', [x for x in ('sales time series', 'sales Zivot-Andrews breaks', 'sales spectral density by period', 'sales spectral density by frequency', 'sales lag plot',
                                                     'sales seasonal subseries', 'sales differenced time series', 'sales linear trend', 'Detrended sales time series', 'sales cycle',
                                                     'Decycled sales time series', 'Seasonal Decomposition (multiplicative, period 12)', 'STL Decomposition (period 12, robust)',
                                                     'Hodrick-Prescott Filter (λ = 129600)', 'promotion time series', 'temperature time series') if x not in labels], [])
    check('charts: series: its diagnostics charts', sorted({c['caption'] for c in g['charts']}),
          sorted({'Autocorrelation', 'Partial Autocorrelation', 'Variogram', 'AR Coefficients', 'sales with promotion', 'sales with temperature'}))
    await page.ev(f"{close_js}; SM.app.tables.find((x) => x.name === 'Monthly sales').setState([30, 31], 'excluded', false)")

    # the models, with their display options: no points, no interval, the residual variogram and AR coefficients,
    # the Theta model's own intervals, a model group's best; three of them on Model Comparison's plots
    arima = {'kind': 'arima', 'd': 0, 'P': 0, 'D': 0, 'Q': 0, 's': 0, 'intercept': True, 'constrain': True, 'level': 0.95}
    models = [{**arima, 'id': 1, 'p': 1, 'q': 1, 'points': False},
              {**arima, 'id': 2, 'p': 1, 'q': 0, 'D': 1, 'Q': 1, 's': 12, 'pi': False, 'rvario': True, 'rar': True, 'graph': False},
              {**arima, 'id': 3, 'p': 1, 'q': 0, 'inputs': [{'name': 'promotion', 'lag': 0, 'num': 1}], 'graph': False},
              {'id': 4, 'kind': 'smooth', 'method': 'winters', 's': 12, 'level': 0.95, 'multiplicative': False},
              {'id': 5, 'kind': 'smooth', 'method': 'double', 's': 0, 'level': 0.9, 'multiplicative': False, 'graph': False},
              {'id': 6, 'kind': 'ets', 'error': 'add', 'trend': 'N', 'seasonal': 'N', 's': 0, 'level': 0.95, 'group': 1, 'graph': False},
              {'id': 7, 'kind': 'ets', 'error': 'add', 'trend': 'A', 'seasonal': 'N', 's': 0, 'level': 0.95, 'group': 1, 'graph': False},
              {'id': 8, 'kind': 'uc', 'trend': 'local linear trend', 'seasonal': 12, 'inputs': ['promotion'], 'level': 0.95, 'graph': False},
              {'id': 9, 'kind': 'theta', 'theta': 2, 'deseasonalize': True, 'period': 12, 'level': 0.95, 'smpi': True}]
    r = await page.ev(open_js('Monthly sales', {'y': ['sales'], 'time': ['month'], 'inputs': ['promotion']},
                              {'forecast': 12, S + 'models': models, S + 'acf': False, S + 'pacf': False, S + 'stationarity': False, S + 'inputPanel': False}), timeout=900)
    check('charts: the models report opens without errors', r['errors'], [])
    g = await check_report_graphs(page, rep, tbl, 'charts: models')
    labels = [x['label'] for x in g['g']]
    want = ['sales model comparison forecasts', 'sales residual autocorrelation', 'sales residual partial autocorrelation', 'ARMA(1, 1) forecast', 'ARMA(1, 1) residuals',
            'Seasonal ARIMA(1, 0, 0)(0, 1, 1)12 forecast', 'Transfer Function AR(1) with promotion (lags 0–1) forecast', 'Winters Method (Additive)(12) forecast',
            'Double (Brown) Exponential Smoothing forecast', 'Structural: local linear trend + seasonal(12) + promotion components', 'Theta Model (θ = 2) forecast']
    check('charts: models: their graphs', [x for x in want if x not in labels], [])
    check('charts: models: the best of the group shows its report and its component states', sum(1 for x in labels if x.startswith('State Space Smoothing ETS(') and x.endswith(' forecast')), 1)
    check('charts: models: the residual variogram and AR coefficients of the seasonal ARIMA', sum(1 for c in g['charts'] if c['caption'] in ('Variogram', 'AR Coefficients')), 2)
    await page.ev(close_js)

    # beyond JMP on the Business cycle: regime switching (its predictions, regimes and probabilities, the
    # filtered ones), and ARDL with the future costs
    r = await page.ev(open_js('Business cycle', {'y': ['growth'], 'time': ['quarter']},
                              {'forecast': 8, 'ts:growth|models': [{'id': 1, 'kind': 'markov', 'k': 2, 'order': 1, 'trend': 'c', 'swTrend': True, 'swVar': False, 'swAr': False, 'starts': 0,
                                                                      'level': 0.95, 'fprob': True}]}), timeout=900)
    check('charts: the regime switching report opens without errors', r['errors'], [])
    g = await check_report_graphs(page, rep, tbl, 'charts: regimes')
    check('charts: regimes: the regimes and the probabilities', [x['label'] for x in g['g'] if x['label'].endswith(('regimes', 'smoothed probabilities'))],
          ['Regime Switching: 2 regimes, AR(1), switching mean regimes', 'Regime Switching: 2 regimes, AR(1), switching mean smoothed probabilities'])
    await page.ev(close_js)
    r = await page.ev(open_js('Business cycle', {'y': ['price'], 'time': ['quarter'], 'inputs': ['cost']},
                              {'forecast': 8, 'ts:price|models': [{'id': 1, 'kind': 'ardl', 'inputs': ['cost'], 'maxlag': 2, 'maxorder': 2, 'ic': 'aic', 'trend': 'c', 'level': 0.95}],
                               'ts:price|stationarity': False}), timeout=900)
    check('charts: the ARDL report opens without errors', r['errors'], [])
    await check_report_graphs(page, rep, tbl, 'charts: ARDL')
    await page.ev(close_js)

    # By, a Local Data Filter and an excluded row, no Time ID: the code drops the rows the filter takes out,
    # keeps the group, and draws on the row numbers as the page does
    r = await page.ev('''(() => { const rng = SM.util.rng('ts-charts'); const n = 96; let w = 20; const x = [], z = [];
      for (let i = 0; i < n; i++) { w += rng.normal(0, 1); x.push(Math.round(1000 * w) / 1000); z.push(Math.round(1000 * rng.normal(0, 1)) / 1000); }
      const t = new SM.Table({ name: 'TS chart rows', columns: [
        { name: 'region', dataType: 'character', values: x.map((_, i) => (i % 2 ? 'South' : 'North')) },
        { name: 'keep', dataType: 'character', values: x.map((_, i) => ([10, 12, 14].includes(i) ? 'no' : 'yes')) },
        { name: 'x', dataType: 'numeric', values: x }, { name: 'z', dataType: 'numeric', values: z }] });
      SM.app.addTable(t); t.setState([20], 'excluded', true); return t.nrows; })()''')
    check('charts: a table of our own for By and a filter', r, 96)
    r = await page.ev(open_js('TS chart rows', {'y': ['x'], 'inputs': ['z'], 'by': ['region']},
                              {'forecast': 5, 'ts:x|lagPlot': 1, 'ts:x|spectral': True, 'ts:x|ccf': True, 'ts:x|models': [{**arima, 'id': 1, 'p': 1, 'q': 0}]},
                              after="rep.toggleFilter(true); await __ts.done(rep); rep.spec.filter.push({ col: t.col('keep').id, levels: ['yes'] }); { const d = __ts.done(rep); rep.run(); await d; }"),
                      timeout=900)
    check('charts: By with a Local Data Filter opens without errors', r['errors'], [])
    g = await check_report_graphs(page, rep, tbl, 'charts: By and a filter')
    codes = [x['code'] for x in g['g'] if x['label'] == 'x time series']
    check('charts: By and a filter: each group\'s graph keeps its group; the filtered rows are dropped, the excluded one missing',
          [('df = df[df["region"] == \'North\']' in c_, 'df = df.drop(index=[10, 12, 14])   # the rows the report leaves out' in c_, 'y.iloc[' in c_) for c_ in codes],
          [(True, True, True), (False, False, False)])
    await page.ev(f"{close_js}; SM.app.closeTable(SM.app.tables.find((x) => x.name === 'TS chart rows')); document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach((b) => b.click());")

# Helpers in the page: pick from a red triangle, fill a form, wait for a report.
HELPERS = r'''
window.__ts = {
  rep() { return SM.app.reports[SM.app.reports.length - 1]; },
  // One-shot: the function rep.on returns cannot unsubscribe (Report's own
  // off field shadows Emitter.off), so a used listener just stays quiet.
  done(rep) { return new Promise((res) => { let once = false; rep.on('done', () => { if (!once) { once = true; res(); } }); }); },
  head(rep, title) { return [...rep.body.querySelectorAll('.sm-ob-head')].find((h) => h.textContent.trim().startsWith(title)); },
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
  async form(values, button) {
    await new Promise((r) => setTimeout(r, 120));
    const dlgs = [...document.querySelectorAll('.sm-dialog')];
    const dlg = dlgs[dlgs.length - 1];
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
  cmpRows(rep) {
    const t = rep.body.querySelector('table.sm-ts-cmp');
    if (!t) return null;
    return [...t.querySelectorAll('tbody tr')].map((tr) => ({ name: tr.children[2].textContent, report: tr.children[0].querySelector('input').checked, graph: tr.children[1].querySelector('input').checked, id: tr.dataset.model }));
  },
};
true
'''


def num(text):
    """A number as the page shows it: JMP's minus sign (−), a star on a significant p-value."""
    return float(str(text).replace('−', '-').rstrip('*'))


async def shot(page, name, title=None):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    if title:   # scroll the report on show down to the outline (only vertically: the report body also scrolls sideways)
        await page.ev(f'''(() => {{ const rep = SM.app.reports.find(r => r.platform.id === 'timeseries' && r.body.offsetParent !== null) || SM.app.reports.find(r => r.platform.id === 'timeseries');
          document.querySelectorAll('.sm-toast').forEach(t => t.remove()); const h = __ts.head(rep, {json.dumps(title)});
          if (h) rep.body.scrollTop = h.getBoundingClientRect().top - rep.body.getBoundingClientRect().top + rep.body.scrollTop - 8; }})()''')
    await asyncio.sleep(1.0)
    await page.shot(os.path.join(SHOTS, name))


async def act(page, js, timeout=600):
    """Run an action that redraws the last report and wait until it is done."""
    return await page.ev(f'''(async () => {{ const rep = __ts.rep(); const d = __ts.done(rep); const out = await (async () => {{ {js} }})(); await d; return out; }})()''', timeout=timeout)


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
    page = await open_page(f'{BASE}/smui.html?example=sales')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "timeseries").map(f => f.error)')
    check('the timeseries module imports', failed, [])
    check('its backend functions are there', await page.ev('["timeseries.series", "timeseries.arima", "timeseries.smooth", "timeseries.ets", "timeseries.spectral"].every(n => SM.engine.has(n))'), True)
    await page.ev(HELPERS)
    menu = await page.ev('''(() => { const it = SM.app.menuItems("Analyze").find(i => i.label === "Specialized Modeling"); const sub = typeof it.submenu === "function" ? it.submenu() : it.submenu; return sub.map(i => i.label); })()''')
    check('Analyze > Specialized Modeling lists Time Series', 'Time Series…' in (menu or []), True)
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    check('the Help tab lists the platform', await page.ev('!!document.getElementById("help-p-timeseries")'), True)

    # ---- the launch dialog
    r = await page.ev('''(async () => {
      SM.app.launch('timeseries');
      await new Promise(r => setTimeout(r, 200));
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { const li = items.find(li => li.textContent === name); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === label);
      pick('sales'); role('Y, Time Series').click();
      pick('month'); role('X, Time ID').click();
      pick('promotion'); role('Input List').click();
      pick('temperature'); role('Input List').click();
      const opt = (label) => [...dlg.querySelectorAll('.sm-launch-opts label')].find(l => l.textContent.startsWith(label)).querySelector('input');
      opt('Forecast Periods').value = '12';
      const lists = [...dlg.querySelectorAll('.sm-role-list')].map(u => u.textContent);
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
      const rep = __ts.rep();
      await __ts.done(rep);
      return { lists, roles, title: rep.title, open: !!document.querySelector('.sm-launch-dialog'), outlines: __ts.outlines(rep), ...__ts.problems(rep) };
    })()''', timeout=600)
    check("JMP's roles", r['roles'], ['Y, Time Series', 'Input List', 'X, Time ID', 'By'])
    check('cast', r['lists'][:3], ['sales', 'promotiontemperature', 'month'])
    check('report title', r['title'], 'Time Series sales')
    check('default outlines', [o for o in r['outlines'] if o in ('Time Series sales', 'Time Series Basic Diagnostics', 'Stationarity Tests', 'Input Time Series Panel')],
          ['Time Series sales', 'Time Series Basic Diagnostics', 'Stationarity Tests', 'Input Time Series Panel'])
    check('no errors', (r['errors'], r['warns']), ([], []))

    # ---- numbers against the page's own arithmetic
    js = await page.ev('''(() => { const v = SM.app.current.col('sales').values; const n = v.length; const m = v.reduce((a, b) => a + b, 0) / n;
      const c0 = v.reduce((a, b) => a + (b - m) ** 2, 0); let c1 = 0; for (let t = 1; t < n; t++) c1 += (v[t] - m) * (v[t - 1] - m);
      return { mean: SM.util.fmt(m), sd: SM.util.fmt(Math.sqrt(c0 / (n - 1))), n: String(n), r1: (c1 / c0).toFixed(4) }; })()''')
    kv = await page.ev('''(() => { const rep = __ts.rep(); const k = rep.body.querySelector('.sm-ob.level-0 > .sm-ob-body table.sm-kv'); return [...k.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent)); })()''')
    kvd = dict((a, b) for a, b in kv)
    check('Mean, SD and N as computed in the page', [kvd.get('Mean'), kvd.get('SD'), kvd.get('N')], [js['mean'], js['sd'], js['n']])
    check('the ADF tests are listed beside the graph', all(k in kvd for k in ('Zero Mean ADF', 'Single Mean ADF', 'Trend ADF')), True)
    acf = await page.ev(table_under_js('Time Series Basic Diagnostics'))
    check('Autocorrelation columns', acf[0][:2] + acf[0][3:], ['Lag', 'AutoCorr', 'Ljung-Box Q', 'p-Value'])
    check('lag 1 autocorrelation as computed in the page', acf[2][1], js['r1'])
    check('lags 0 to 25', (acf[1][0], acf[-1][0]), ('0', '25'))
    check('a bar in every row', await page.ev('__ts.rep().body.querySelectorAll("table.sm-ts-corr td.sm-ts-barcell svg rect.bar").length >= 52'), True)
    stt = await page.ev(table_under_js('Stationarity Tests'))
    check('stationarity tests', [row[0] for row in stt[1:]], ['Zero Mean ADF', 'Single Mean ADF', 'Trend ADF', 'KPSS Level', 'KPSS Trend'])
    ax = await page.ev('''(async () => { const rep = __ts.rep(); const p = rep.plots.find(p => p.opts.title === 'sales time series'); await p.draw(); return { type: p.box._fullLayout.xaxis.type, x0: p.traces[0].x[0], n: p.traces[0].x.length }; })()''')
    check('the Time ID gives a date axis', ax, {'type': 'date', 'x0': '2016-01-01', 'n': 120})
    check('the note gives the frequency', await page.ev('__ts.rep().body.textContent.includes("Monthly data; seasonal period 12.")'), True)
    await shot(page, 'ts-01-series.png')

    # ---- linking both ways
    r = await page.ev('''(async () => {
      const rep = __ts.rep(); const t = rep.table; const p = rep.plots.find(p => p.opts.title === 'sales time series');
      p._click({ points: [{ curveNumber: 0, pointNumber: 40 }], event: {} });
      const sel = t.selectedRows();
      t.select([5, 6, 7]);
      await new Promise(r => setTimeout(r, 150));
      const sp = p.box.data[0].selectedpoints;
      t.select([]);
      return { sel, sp: Array.from(sp || []) };
    })()''')
    check('a click on a point selects its row', r['sel'], [40])
    check('a table selection lights up the points', r['sp'], [5, 6, 7])

    # ---- ARIMA through the red triangle and its dialog
    r = await act(page, '''await __ts.menu(__ts.rep(), null, ['ARIMA…']); return await __ts.form({ 'p, Autoregressive Order': 1, 'q, Moving Average Order': 1 }, 'Estimate');''')
    check('the ARIMA Specification dialog', r, 'ARIMA Specification: sales')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('ARIMA adds the Model Comparison and the model report', ['Model Comparison' in outl, 'Model: ARMA(1, 1)' in outl], [True, True])
    check('the model report parts', [o for o in outl if o in ('Model Summary', 'Parameter Estimates', 'Forecast', 'Residuals', 'Iteration History')],
          ['Model Summary', 'Parameter Estimates', 'Forecast', 'Residuals', 'Iteration History'])
    pe = await page.ev(table_under_js('Parameter Estimates'))
    check('Parameter Estimates columns', pe[0], ['Term', 'Lag', 'Estimate', 'Std Error', 't Ratio', 'Prob>|t|'])
    check('terms', [row[0] for row in pe[1:]], ['Intercept', 'AR1', 'MA1'])
    ms = dict(tuple(x) for x in await page.ev(table_under_js('Model Summary')))
    check("JMP's Model Summary", all(k in ms for k in ('DF', 'Sum of Squared Innovations', 'Variance Estimate', 'Standard Deviation', "Akaike's 'A' Information Criterion",
                                                     "Schwarz's Bayesian Criterion", 'AICc', 'RSquare', 'RSquare Adj', 'MAPE', 'MAE', '−2LogLikelihood', 'Stable', 'Invertible')), True)
    check('DF = n - k', ms.get('DF'), '117')
    check('forecasts continue the months', await page.ev('__ts.rep().body.textContent.includes("12 periods ahead, from 2026-01-01 to 2026-12-01")'), True)
    fp = await page.ev('''(async () => { const rep = __ts.rep(); const p = rep.plots.find(p => p.opts.title === 'ARMA(1, 1) forecast'); await p.draw();
      const fc = p.traces.find(t => t.name === 'ARMA(1, 1) forecast'); const band = p.traces.find(t => t.name === 'ARMA(1, 1) lower');
      return { type: p.box._fullLayout.xaxis.type, last: fc.x[fc.x.length - 1], n: fc.x.length, fill: band.fill }; })()''')
    check('the forecast plot: dates, 12 periods, a band after the data', fp, {'type': 'date', 'last': '2026-12-01', 'n': 13, 'fill': 'tonexty'})
    await shot(page, 'ts-02-arima.png', 'Model: ARMA(1, 1)')

    # ---- seasonal ARIMA, a smoothing model, the group and state space smoothing, all through the menus
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Seasonal ARIMA…']); return await __ts.form({ 'p, Autoregressive Order': 1, 'Q, Seasonal Moving Average Order': 1, 'D, Seasonal Differencing Order': 1 }, 'Estimate');''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Smoothing Models', 'Winters Method…']); return await __ts.form({}, 'Estimate');''')
    rows = await page.ev('__ts.cmpRows(__ts.rep())')
    names = [x['name'] for x in rows]
    check('Model Comparison lists the three models', sorted(names), sorted(['ARMA(1, 1)', 'Seasonal ARIMA(1, 0, 0)(0, 1, 1)12', 'Winters Method (Additive)(12)']))
    cmp_ = await page.ev('''(() => { const t = __ts.rep().body.querySelector('table.sm-ts-cmp'); return [...t.querySelectorAll('thead th')].map(th => th.textContent); })()''')
    check('Model Comparison columns', cmp_, ['Report', 'Graph', 'Model', 'DF', 'Variance', 'AIC', 'SBC', 'AICc', 'RSquare', '−2LogLH', 'Weights', 'MAPE', 'MAE'])
    aic = await page.ev('''(() => { const t = __ts.rep().body.querySelector('table.sm-ts-cmp'); return [...t.querySelectorAll('tbody tr')].map(tr => Number(tr.children[5].textContent.replace('−', '-'))); })()''')
    check('sorted by AIC', aic == sorted(aic), True)
    r = await act(page, '''await __ts.menu(__ts.rep(), null, ['ARIMA Model Group…']); return await __ts.form({ 'p, Autoregressive Order (range)': '0-1', 'q, Moving Average Order (range)': '0-1', 'd, Differencing Order (range)': '1' }, 'Estimate');''')
    rows = await page.ev('__ts.cmpRows(__ts.rep())')
    group = [x for x in rows if x['name'] in ('I(1)', 'ARI(1, 1)', 'IMA(1, 1)', 'ARIMA(1, 1, 1)')]
    check('ARIMA Model Group fits every combination', len(group), 4)
    check('... and shows the report of one (the best by AIC)', sum(1 for x in group if x['report']), 1)
    await act(page, '''await __ts.menu(__ts.rep(), null, ['State Space Smoothing Models…']); return await __ts.form({ 'Error: Multiplicative (M)': false, 'Seasonal: Multiplicative (M)': false, 'Trend: Additive damped (Ad)': false }, 'OK');''')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('State Space Smoothing Model Selection', any(o.startswith('State Space Smoothing Model Selection') for o in outl), True)
    sel = await page.ev(table_under_js('State Space Smoothing Model Selection 2'))
    check('four ETS models, best by AICc first', (len(sel) - 1, sel[1][-1]), (4, '★ best'))
    check('the caution about comparing classes', await page.ev('__ts.problems(__ts.rep()).warns.some(w => w.startsWith("Caution: the state space"))'), True)
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Transfer Function…']); return await __ts.form({ 'Noise p, Autoregressive Order': 1 }, 'Estimate');''')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('the transfer function model', 'Model: Transfer Function AR(1) with promotion, temperature' in outl, True)
    pe = await page.ev('''(() => { const h = __ts.head(__ts.rep(), 'Model: Transfer Function'); const t = h.parentElement.querySelector('table.sm-rt'); return [...t.querySelectorAll('tbody tr')].map(tr => tr.children[0].textContent); })()''')
    check('... with a coefficient for each input', pe, ['Intercept', 'promotion', 'temperature', 'AR1'])
    await shot(page, 'ts-03-comparison.png', 'Model Comparison')
    pr = await page.ev('__ts.problems(__ts.rep())')
    check('no errors with nine models', pr['errors'], [])
    check('no deprecation noise in the messages', any('DeprecationWarning' in w for w in pr['warns']), False)

    # ---- the Report and Graph boxes, and a model's red triangle
    r = await act(page, '''const rep = __ts.rep(); const tr = [...rep.body.querySelectorAll('table.sm-ts-cmp tbody tr')].find(tr => tr.children[2].textContent === 'ARMA(1, 1)');
      const b = tr.children[0].querySelector('input'); b.checked = false; b.dispatchEvent(new Event('change')); return true;''')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('unchecking Report hides the model report', 'Model: ARMA(1, 1)' in outl, False)
    await act(page, '''const rep = __ts.rep(); const tr = [...rep.body.querySelectorAll('table.sm-ts-cmp tbody tr')].find(tr => tr.children[2].textContent === 'ARMA(1, 1)');
      const b = tr.children[0].querySelector('input'); b.checked = true; b.dispatchEvent(new Event('change')); return true;''')
    r = await page.ev('''(async () => { const rep = __ts.rep(); const p = rep.plots.find(p => p.opts.title === 'sales model comparison forecasts'); return p.traces.filter(t => t.showlegend).map(t => t.name); })()''')
    check('the Graph boxes put the models on the comparison plot', 'ARMA(1, 1)' in r and 'Seasonal ARIMA(1, 0, 0)(0, 1, 1)12' in r, True)
    await act(page, '''await __ts.menu(__ts.rep(), 'Model: ARMA(1, 1)', ['Show Points']); return true;''')
    r = await page.ev('''(() => { const p = __ts.rep().plots.find(p => p.opts.title === 'ARMA(1, 1) forecast'); return p.traces.some(t => t.mode === 'markers'); })()''')
    check('Show Points off takes the points away', r, False)
    await act(page, '''await __ts.menu(__ts.rep(), 'Model: ARMA(1, 1)', ['Show Prediction Interval']); return true;''')
    r = await page.ev('''(() => { const p = __ts.rep().plots.find(p => p.opts.title === 'ARMA(1, 1) forecast'); return p.traces.some(t => t.fill === 'tonexty'); })()''')
    check('Show Prediction Interval off takes the band away', r, False)
    await act(page, '''await __ts.menu(__ts.rep(), 'Model: ARMA(1, 1)', ['Residual Statistics', 'Variogram']); return true;''')
    r = await page.ev('''(() => { const h = __ts.head(__ts.rep(), 'Model: ARMA(1, 1)'); return [...h.parentElement.querySelectorAll('table.sm-ts-corr caption')].map(c => c.textContent); })()''')
    check('Residual Statistics: the residual correlations and the variogram', r, ['Residual Autocorrelation', 'Variogram', 'Residual Partial Autocorrelation'])
    r = await page.ev('''(async () => { const before = SM.app.tables.length; await __ts.menu(__ts.rep(), 'Model: ARMA(1, 1)', ['Save Columns']); await new Promise(r => setTimeout(r, 200));
      const t = SM.app.tables[SM.app.tables.length - 1]; const time = t.columns[0];
      return { added: SM.app.tables.length - before, name: t.name, cols: t.columns.map(c => c.name), rows: t.nrows, fmt: time.format && time.format.kind, last: time.values[t.nrows - 1], resid: t.columns[4].values[t.nrows - 1] }; })()''')
    check('Save Columns makes a new table', (r['added'], r['name'], r['rows']), (1, 'sales ARMA(1, 1)', 132))
    check('... with the time, actual, predicted, error, residual and limits', r['cols'], ['month', 'Actual sales', 'Predicted sales', 'Std Err Pred sales', 'Residual sales', 'Upper CL (0.95) sales', 'Lower CL (0.95) sales'])
    check('... the forecast dates continue monthly', (r['fmt'], r['last']), ('date', await page.ev('Date.UTC(2026, 11, 1)')))
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports[SM.app.reports.length - 1]))')
    n0 = len(await page.ev('__ts.cmpRows(__ts.rep())'))
    await act(page, '''await __ts.menu(__ts.rep(), 'Model: ARMA(1, 1)', ['Remove Fit']); return true;''')
    rows = await page.ev('__ts.cmpRows(__ts.rep())')
    check('Remove Fit takes the model out of the comparison', (len(rows), any(x['name'] == 'ARMA(1, 1)' for x in rows)), (n0 - 1, False))

    # ---- differencing, decomposition, the spectral density, the lag plot, cross correlation
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Difference…']); return await __ts.form({ 'Seasonal Differencing Order, D': '1' }, 'Estimate');''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Decomposition', 'STL Decomposition…']); return await __ts.form({}, 'OK');''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Decomposition', 'Remove Linear Trend']); return true;''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Spectral Density']); return true;''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Show Lag Plot']); return true;''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Cross Correlation']); return true;''')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    for o in ('Difference: (1 − B)(1 − B^12)', 'STL Decomposition (period 12)', 'Linear Trend', 'Time Series Detrended sales', 'Spectral Density', 'White Noise Test', 'Lag Plot (lag 1)', 'Cross Correlation'):
        check(f'outline {o}', o in outl, True)
    wn = dict(tuple(x) for x in await page.ev(table_under_js('White Noise Test')))
    check("Fisher's kappa and Bartlett's test", ("Fisher's Kappa" in wn, 'Prob > Kappa' in wn, "Bartlett's Kolmogorov-Smirnov" in wn), (True, True, True))
    lagn = await act(page, '''const i = __ts.rep().body.querySelector('.sm-ts-lagctl input'); i.value = '12'; i.dispatchEvent(new Event('change')); return true;''')
    check('the lag plot takes another lag', 'Lag Plot (lag 12)' in await page.ev('__ts.outlines(__ts.rep())'), True)
    ccf = await page.ev('''(() => { const h = __ts.head(__ts.rep(), 'Cross Correlation'); return [...h.parentElement.querySelectorAll('table.sm-ts-corr caption')].map(c => c.textContent); })()''')
    check('a cross correlation per input', ccf, ['sales with promotion', 'sales with temperature'])
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const before = t.columns.length; await __ts.menu(rep, 'Difference', ['Save']); await new Promise(r => setTimeout(r, 100));
      const c = t.columns[t.columns.length - 1]; const out = { added: t.columns.length - before, name: c.name, first: c.values[12], v13: Number.isFinite(c.values[13]) }; t.removeColumn(c.id); return out; })()''')
    check('Difference > Save writes the differenced column', (r['added'], r['first'], r['v13']), (1, None, True))
    await shot(page, 'ts-04-spectral.png', 'Spectral Density')
    pr = await page.ev('__ts.problems(__ts.rep())')
    check('still no errors', pr['errors'], [])

    # ---- the options survive Redo and a saved project
    spec = json.loads(await page.ev('JSON.stringify(__ts.rep().toJSON().spec.options)'))
    mkey = [k for k in spec if k.endswith('|models')]
    check('the models are stored in the options', len(spec[mkey[0]]) if mkey else 0, n0 - 1 + 0)
    r = await page.ev('''(async () => {
      const rep = __ts.rep(); const t = rep.table;
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      const n = SM.app.reports.length;
      SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const r2 = SM.app.reports[n];
      await __ts.done(r2);
      return { outlines: __ts.outlines(r2).filter(o => o.startsWith('Model: ') || o === 'Spectral Density' || o.startsWith('Difference')), n: SM.app.reports.length - n, ...__ts.problems(r2) };
    })()''', timeout=600)
    check('a reopened project redraws the models and the added reports', ('Model: Seasonal ARIMA(1, 0, 0)(0, 1, 1)12' in r['outlines'], 'Spectral Density' in r['outlines'], any(o.startswith('Difference') for o in r['outlines'])), (True, True, True))
    check('... without errors', r['errors'], [])
    await page.ev('(() => { const r = SM.app.reports[SM.app.reports.length - 1]; SM.app.closeReport(r); const t = SM.app.tables[SM.app.tables.length - 1]; SM.app.closeTable(t); })()')
    await page.ev('document.querySelectorAll(".sm-dialog .sm-btn.primary").forEach(b => b.click())')

    # ---- excluded rows count as missing values; Redo
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "timeseries")))')
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'timeseries'); const t = rep.table;
      t.setState([30, 31], 'excluded', true);
      const stale = !rep.staleEl.hidden;
      const d = __ts.done(rep); rep.run(); await d;
      const k = rep.body.querySelector('.sm-ob.level-0 > .sm-ob-body table.sm-kv');
      const kv = Object.fromEntries([...k.querySelectorAll('tr')].map(tr => [tr.children[0].textContent, tr.children[1].textContent]));
      const p = rep.plots.find(p => p.opts.title === 'sales time series');
      const out = { stale, n: kv['N'], miss: kv['N Missing'], slots: p.traces[0].x.length, gap: p.traces[0].y[30], note: rep.body.textContent.includes('2 excluded rows count as missing values') };
      t.setState([30, 31], 'excluded', false);
      const d2 = __ts.done(rep); rep.run(); await d2;
      return out;
    })()''', timeout=600)
    check('an exclusion makes the report stale', r['stale'], True)
    check('excluded rows are missing values in their place', (r['n'], r['miss'], r['slots'], r['gap']), ('118', '2', 120, None))
    check('... and the report says so', r['note'], True)

    # ---- By: one report per level of a stacked table
    r = await page.ev('''(async () => {
      const src = SM.app.tables.find(t => t.name === 'Monthly sales');
      const m = src.col('month').values, s = src.col('sales').values;
      const t = new SM.Table({ name: 'Two regions', columns: [
        { name: 'region', dataType: 'character', values: [...m.map(() => 'North'), ...m.map(() => 'South')] },
        { name: 'month', dataType: 'numeric', format: { kind: 'date' }, values: [...m, ...m] },
        { name: 'sales', dataType: 'numeric', values: [...s, ...s.map((v, i) => v * 0.8 + 5 * Math.sin(i))] } ] });
      SM.app.addTable(t);
      const P = SM.platforms.get('timeseries');
      const rep = SM.app.openReport(P, { roles: { y: [t.col('sales').id], time: [t.col('month').id], by: [t.col('region').id] }, options: { forecast: 6 } }, t);
      await __ts.done(rep);
      rep.spec.options['ts:sales|models'] = [{ id: 1, kind: 'arima', p: 1, d: 0, q: 0, P: 0, D: 1, Q: 1, s: 12, intercept: true, constrain: true, level: 0.95 }];
      const d = __ts.done(rep); rep.run(); await d;
      const tops = [...rep.body.querySelectorAll('.sm-ob.level-0 > .sm-ob-head h2')].map(h => h.textContent);
      return { tops, models: __ts.outlines(rep).filter(o => o.startsWith('Model: ')), ...__ts.problems(rep), note: rep.noteEl.textContent };
    })()''', timeout=600)
    check('By gives one report per level', r['tops'], ['Time Series sales region=North', 'Time Series sales region=South'])
    check('... each with the model', r['models'], ['Model: Seasonal ARIMA(1, 0, 0)(0, 1, 1)12', 'Model: Seasonal ARIMA(1, 0, 0)(0, 1, 1)12'])
    check('... without errors', r['errors'], [])
    check('... from 240 rows in two groups', r['note'], 'Two regions: 240 of 240 rows, 2 groups')

    # ---- the Python script
    script = await page.ev('SM.app.reports.find(r => r.platform.id === "timeseries").pythonScript()')
    check('the script has the fits', all(s in script for s in ('from statsmodels.tsa.arima.model import ARIMA', 'acorr_ljungbox', 'ExponentialSmoothing', 'ETSModel', 'asfreq(\'MS\')')), True)

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "timeseries")))')
    await page.ev('''(async () => { const rep = SM.app.reports.find(r => r.platform.id === 'timeseries'); const d = __ts.done(rep);
      KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark'); await d; })()''', timeout=600)
    await asyncio.sleep(1.0)
    await shot(page, 'ts-05-dark.png', 'Model Comparison')
    await shot(page, 'ts-06-dark-top.png', 'Time Series sales')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await page.ev('''(async () => { const rep = SM.app.reports.find(r => r.platform.id === 'timeseries'); const d = __ts.done(rep); rep.run(); await d; })()''', timeout=600)
    await asyncio.sleep(1.2)
    check('no horizontal page scroll at phone width', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, 'ts-07-phone.png', 'Model Comparison')
    # ==== beyond JMP: Zivot-Andrews, regime switching, filters, the subseries plot, structural, Theta and ARDL models ====
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev('document.documentElement.setAttribute("data-theme", "light")')
    await asyncio.sleep(0.8)
    r = await page.ev('''(() => { const t = SM.io.example('cycles'); SM.app.addTable(t);
      const p = t.col('price').values; return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), lastPrice: p.slice(-9).map(v => Number.isFinite(v)),
        listed: !!SM.io.EXAMPLES.cycles, date: t.col('quarter').format && t.col('quarter').format.kind }; })()''')
    check('the Business cycle example: simulated quarters with a price missing in the last 8', (r['name'], r['rows'], r['cols'], r['lastPrice'], r['listed'], r['date']),
          ('Business cycle', 184, ['quarter', 'growth', 'output', 'unemployment', 'cost', 'price'], [True] + [False] * 8, True, 'date'))

    async def open_ts(roles, options):
        return await page.ev(f'''(async () => {{ const t = SM.app.current; const P = SM.platforms.get('timeseries');
          const ids = {{}}; for (const [k, names] of Object.entries({json.dumps(roles)})) ids[k] = names.map(n => t.col(n).id);
          const rep = SM.app.openReport(P, {{ roles: ids, options: {json.dumps(options)} }}, t); await __ts.done(rep);
          return {{ title: rep.title, outlines: __ts.outlines(rep), ...__ts.problems(rep) }}; }})()''', timeout=600)

    # ---- Zivot-Andrews, in Stationarity Tests by default
    r = await open_ts({'y': ['unemployment'], 'time': ['quarter']}, {'forecast': 8})
    check('Stationarity Tests hold the Zivot-Andrews Test by default', ('Stationarity Tests' in r['outlines'], 'Zivot-Andrews Test' in r['outlines'], r['errors']), (True, True, []))
    za = await page.ev(table_under_js('Zivot-Andrews Test'))
    check('Zivot-Andrews: the three models and the break date', ([row[0] for row in za[1:]], za[0]),
          (['Break in intercept', 'Break in trend', 'Break in intercept and trend'], ['Model', 'Statistic', 'Prob', 'Lags', 'Break', '1%', '5%', '10%']))
    check('... the level shift after 2005 Q1 is found (a break in the intercept)', za[1][4] in ('2004-10-01', '2005-01-01', '2005-04-01'), True)
    check('... and the unit root is rejected', za[1][2].startswith('<') or num(za[1][2]) < 0.05, True)
    zp = await page.ev('''(() => { const p = __ts.rep().plots.find(p => p.opts.title === 'unemployment Zivot-Andrews breaks'); return p ? { shapes: p.userLayout.shapes.length, labels: p.userLayout.annotations.map(a => a.text.trim()), linked: !!p.rows[0] } : null; })()''')
    n_dates = len({row[4] for row in za[1:]})
    check('... a graph with a line at each break date, labelled with its models, its points linked to the rows', (zp['shapes'], len(zp['labels']), zp['linked'], any('intercept' in x for x in zp['labels'])), (n_dates, n_dates, True, True))
    t = await act(page, '''await __ts.menu(__ts.rep(), 'Zivot-Andrews Test', ['Zivot-Andrews Options…']); return await __ts.form({ 'Trimming at each end (0 to 1/3)': 0.25, 'Lags chosen by': 'BIC' }, 'OK');''')
    check('Zivot-Andrews Options: the dialog', t, 'Zivot-Andrews Test: unemployment')
    spec = json.loads(await page.ev('JSON.stringify(__ts.rep().spec.options)'))
    check('... the options are kept in the report (Redo and projects keep them)', (spec.get('ts:unemployment|zaTrim'), spec.get('ts:unemployment|zaAutolag')), (0.25, 'BIC'))
    check('... and the test is redrawn with them', await page.ev('__ts.rep().body.textContent.includes("trim=0.25") || [...__ts.rep().body.querySelectorAll("details.sm-code code")].some(c => c.textContent.includes("trim=0.25"))'), True)
    await shot(page, 'ts-08-zivot.png', 'Zivot-Andrews Test')
    await act(page, '''await __ts.menu(__ts.rep(), 'Stationarity Tests', ['Zivot-Andrews Test']); return true;''')
    check('the Stationarity Tests red triangle turns it off', 'Zivot-Andrews Test' in await page.ev('__ts.outlines(__ts.rep())'), False)
    r = await page.ev('''(async () => { const rng = SM.util.rng('long'); let x = 0; const v = []; for (let i = 0; i < 5001; i++) { x += rng.normal(); v.push(x); }
      const t = new SM.Table({ name: 'Long walk', columns: [{ name: 'x', dataType: 'numeric', values: v }] }); SM.app.addTable(t);
      const rep = SM.app.openReport(SM.platforms.get('timeseries'), { roles: { y: [t.col('x').id] }, options: {} }, t); await __ts.done(rep);
      const out = { za: __ts.outlines(rep).includes('Zivot-Andrews Test'), note: rep.body.textContent.includes('left out for a series of more than 5000 values'), ...__ts.problems(rep) };
      SM.app.closeReport(rep); SM.app.closeTable(t); document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach(b => b.click());
      const cyc = SM.app.tables.find(x => x.name === 'Business cycle'); if (cyc) SM.app.showTab(SM.app.tabOf(cyc));
      return out; })()''', timeout=600)
    check('a series of more than 5000 values leaves the Zivot-Andrews test out by default, and says so', (r['za'], r['note'], r['errors']), (False, True, []))

    # ---- Regime Switching on growth
    r = await open_ts({'y': ['growth'], 'time': ['quarter']}, {'forecast': 8})
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['Regime Switching…']); return await __ts.form({ 'Autoregressive Order (0: switching regression)': 1, 'Random Starts': 3 }, 'Estimate');''', timeout=900)
    check('Regime Switching: the dialog', t, 'Regime Switching Specification: growth')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('... the model report and its parts', [o for o in outl if o in ('Model: Regime Switching: 2 regimes, AR(1), switching mean', 'Model Comparison', 'Regimes', 'Regime Probabilities', 'Starts', 'One-Step-Ahead Predictions')],
          ['Model Comparison', 'Model: Regime Switching: 2 regimes, AR(1), switching mean', 'One-Step-Ahead Predictions', 'Regimes', 'Regime Probabilities', 'Starts'])
    pr = await page.ev('__ts.problems(__ts.rep())')
    check('... without errors', pr['errors'], [])
    rg = await page.ev(table_under_js('Regimes'))
    tp = await page.ev(table_under_js('Regimes', 1))
    check('Regimes: the probability of staying, the expected duration, how long each is most likely', rg[0], ['Regime', 'P(Stay)', 'Expected Duration', 'Periods Most Likely', 'Mean Probability'])
    check('... the transition matrix: each row sums to 1', all(abs(num(a) + num(b) - 1) < 2e-6 for _, a, b in tp[1:]), True)
    stay = [num(row[1]) for row in rg[1:]]
    dur = [num(row[2]) for row in rg[1:]]
    check('... the expected duration is 1/(1 − P(Stay))', all(abs(d - 1 / (1 - s_)) < 1e-3 * d for s_, d in zip(stay, dur)), True)
    pe = await page.ev(table_under_js('Parameter Estimates'))
    check('Parameter Estimates with a Regime column', (pe[0], [row[0] for row in pe[1:]]), (['Term', 'Regime', 'Estimate', 'Std Error', 'z Ratio', 'Prob>|z|'], ['P(0 → 0)', 'P(1 → 0)', 'Intercept', 'Intercept', 'Variance', 'AR1']))
    means = sorted(num(row[2]) for row in pe[1:] if row[0] == 'Intercept')
    check('... the two means near the simulated −0.6 and 0.8 (the quantile start finds them)', abs(means[0] + 0.6) < 0.5 and abs(means[1] - 0.8) < 0.4, True)
    rp = await page.ev('''(async () => { const rep = __ts.rep(); const p = rep.plots.find(p => /smoothed probabilities$/.test(p.opts.title)); const s = rep.plots.find(p => /regimes$/.test(p.opts.title));
      await p.draw(); await s.draw(); return { traces: p.traces.filter(t => t.rows || p.rows).length, names: p.traces.map(t => t.name), shapes: s.userLayout.shapes.length, rowsLinked: p.rows.filter(Boolean).length }; })()''')
    check('Regime Probabilities: a probability line per regime, linked to the rows', (rp['names'][:2], rp['rowsLinked']), (['Regime 0', 'Regime 1'], 2))
    check('... the series shaded where each regime is the most likely', rp['shapes'] > 2, True)
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const p = rep.plots.find(p => /smoothed probabilities$/.test(p.opts.title));
      p._click({ points: [{ curveNumber: 0, pointNumber: 50 }], event: {} }); const sel = t.selectedRows();
      t.select([7, 8]); await new Promise(r => setTimeout(r, 150)); const sp = Array.from(p.box.data[0].selectedpoints || []); t.select([]); return { sel, sp }; })()''')
    check('... a click on a probability selects its row; a selection shows in the graph', (r['sel'], r['sp']), ([50], [7, 8]))
    st = await page.ev(table_under_js('Starts'))
    check('Starts: statsmodels\' default, the quantile start and 3 random starts, one best', ([row[0] for row in st[1:]], sum(1 for row in st[1:] if row[3] == '★ best')),
          (["statsmodels' default", 'regimes at the quantiles', 'random 1', 'random 2', 'random 3'], 1))
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const before = t.columns.length; await __ts.menu(rep, 'Model: Regime Switching', ['Save Regime Probabilities']);
      await new Promise(r => setTimeout(r, 150)); const added = t.columns.slice(before); const out = { names: added.map(c => c.name), p0: added[0].values[10], p1: added[1].values[10], most: added[2].values[10] };
      for (const c of added) t.removeColumn(c.id); return out; })()''')
    check('Save Regime Probabilities: the smoothed probabilities and the most likely regime', (r['names'], abs(r['p0'] + r['p1'] - 1) < 1e-9, r['most'] == (0 if r['p0'] > r['p1'] else 1)),
          (['P(Regime 0) growth', 'P(Regime 1) growth', 'Most Likely Regime growth'], True, True))
    await shot(page, 'ts-09-regimes.png', 'Regime Probabilities')
    await act(page, '''await __ts.menu(__ts.rep(), 'Model: Regime Switching', ['Filtered Probabilities']); return true;''')
    check('Filtered Probabilities adds the dotted filtered lines', await page.ev('''(() => __ts.rep().plots.find(p => /smoothed probabilities$/.test(p.opts.title)).traces.filter(t => /filtered$/.test(t.name)).length)()'''), 2)

    # ---- Filters on output
    r = await open_ts({'y': ['output'], 'time': ['quarter']}, {'forecast': 8})
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['Filters', 'Hodrick-Prescott Filter…']); await new Promise(r => setTimeout(r, 250));
      const dlg = [...document.querySelectorAll('.sm-dialog')].pop(); const lab = [...dlg.querySelectorAll('.sm-form label')].find(l => l.textContent === 'λ, Smoothing');
      window.__lam = document.getElementById(lab.htmlFor).value; return await __ts.form({}, 'Estimate');''')
    check('Filters > Hodrick-Prescott: quarterly data propose λ = 1600', (t, await page.ev('window.__lam')), ('Hodrick-Prescott Filter: output', '1600'))
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Filters', 'Baxter-King Filter…']); return await __ts.form({}, 'Estimate');''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Filters', 'Christiano-Fitzgerald Filter…']); return await __ts.form({}, 'Estimate');''')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('... three filter reports', [o for o in outl if 'Filter' in o], ['Hodrick-Prescott Filter (λ = 1600)', 'Baxter-King Filter (6 to 32 periods, K = 12)', 'Christiano-Fitzgerald Filter (6 to 32 periods)'])
    kv = dict(tuple(x) for x in await page.ev(table_under_js('Baxter-King Filter (6 to 32 periods, K = 12)')))
    check('... Baxter-King loses K = 12 quarters at each end', kv.get('N (cycle)'), '160')
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const before = t.columns.length; await __ts.menu(rep, 'Hodrick-Prescott Filter', ['Save Columns']);
      await new Promise(r => setTimeout(r, 150)); const added = t.columns.slice(before); const out = { names: added.map(c => c.name), sum: added[0].values[20] + added[1].values[20], y: t.col('output').values[20] };
      for (const c of added) t.removeColumn(c.id); return out; })()''')
    check('... Save Columns writes the trend and the cycle, which add up to the series', (r['names'], abs(r['sum'] - r['y']) < 1e-9), (['output HP trend', 'output HP cycle'], True))
    await shot(page, 'ts-10-filters.png', 'Hodrick-Prescott Filter')

    # ---- ARDL on price and cost, with the future costs
    r = await open_ts({'y': ['price'], 'time': ['quarter'], 'inputs': ['cost']}, {'forecast': 8})
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['ARDL…']); return await __ts.form({}, 'Estimate');''', timeout=900)
    check('ARDL: the dialog', t, 'ARDL Specification: price')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    mname = [o for o in outl if o.startswith('Model: ARDL(')]
    check('... the model, named by its orders', (len(mname), mname[0].endswith('with cost') if mname else False), (1, True))
    check('... its parts', [o for o in outl if o in ('Lag Order Selection', 'Long-Run Coefficients', 'Bounds Test', 'Error Correction Form')],
          ['Lag Order Selection', 'Long-Run Coefficients', 'Bounds Test', 'Error Correction Form'])
    lr = await page.ev(table_under_js('Long-Run Coefficients'))
    lrd = {row[0]: row for row in lr[1:]}
    check('Long-Run Coefficients: cost near the simulated 0.75', abs(num(lrd['cost'][1]) - 0.75) < 0.1, True)
    bt = await page.ev('''(() => { const h = __ts.head(__ts.rep(), 'Bounds Test'); const b = h.parentElement; const v = b.querySelector('.sm-ts-verdict');
      return { kv: [...b.querySelectorAll('table.sm-kv tr')].map(tr => [...tr.children].map(c => c.textContent)), crit: [...b.querySelectorAll('table.sm-rt tr')].map(tr => [...tr.children].map(c => c.textContent)), verdict: v && v.className, text: v && v.textContent }; })()''')
    kvb = dict(tuple(x) for x in bt['kv'])
    check('Bounds Test: the F statistic, the case and k = 1 input', (kvb.get('Case'), kvb.get('Inputs (k)'), await page.ev('__ts.rep().body.textContent.includes("Case 3: unrestricted intercept, no trend.")')), ('3', '1', True))
    check('... the critical values of PSS (2001) for one input', (bt['crit'][0], [row[0] for row in bt['crit'][1:]]), (['Level', 'I(0) Bound', 'I(1) Bound'], ['10%', '5%', '1%', '0.1%']))
    check('... the 5% bounds are those of k = 1 (about 4.9 and 5.7), not statsmodels\' k + 1', [round(num(x), 1) for x in bt['crit'][2][1:]], [4.9, 5.7])
    check('... and the verdict: a level relationship', (bt['verdict'], bt['text'].startswith('At 5%, F = ')), ('sm-ts-verdict sm-ts-reject', True))
    check('ARDL forecasts continue the quarters with the 8 future costs', await page.ev('__ts.rep().body.textContent.includes("8 periods ahead, from 2024-01-01 to 2025-10-01")'), True)
    check('... and say where the future inputs came from', await page.ev('__ts.rep().body.textContent.includes("cost: the 8 future values come from the rows after the series in the table.")'), True)
    await shot(page, 'ts-11-ardl.png', 'Bounds Test')
    t = await act(page, '''await __ts.menu(__ts.rep(), 'Model: ARDL(', ['Fit New…']);
      return await __ts.form({ 'Or fixed orders p, q1, q2 … (- leaves an input out)': '2, 1', 'Deterministic Terms': 'ct' }, 'Estimate');''', timeout=900)
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('Fit New… with fixed orders and a trend: ARDL(2, 1)', 'Model: ARDL(2, 1) with cost' in outl, True)
    kv2 = await page.ev('''(() => [...__ts.rep().body.querySelectorAll('.sm-ob-head')].filter(h => h.textContent.trim() === 'Bounds Test').map(h => [...h.parentElement.querySelectorAll('table.sm-kv tr')].map(tr => [...tr.children].map(c => c.textContent)).find(x => x[0] === 'Case')[1]))()''')
    check('... its bounds test takes case 4 (the trend restricted)', (kv2, await page.ev('__ts.rep().body.textContent.includes("Case 4: unrestricted intercept, restricted trend.")')), (['3', '4'], True))

    # ---- the sales example: the subseries plot, a structural model with the promotion, the Theta model
    r = await page.ev(f'''(async () => {{ const t = SM.app.tables.find(t => t.name === 'Monthly sales'); const P = SM.platforms.get('timeseries');
      const rep = SM.app.openReport(P, {{ roles: {{ y: [t.col('sales').id], time: [t.col('month').id], inputs: [t.col('promotion').id] }}, options: {{ forecast: 12 }} }}, t); await __ts.done(rep);
      return {{ title: rep.title, ...__ts.problems(rep) }}; }})()''', timeout=600)
    check('a report on the Monthly sales', (r['title'], r['errors']), ('Time Series sales', []))
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Seasonal Subseries Plot']); return true;''')
    sp = await page.ev('''(async () => { const p = __ts.rep().plots.find(p => p.opts.title === 'sales seasonal subseries'); await p.draw();
      return { n: p.traces.filter(t => t.type === 'scatter').length, ticks: p.userLayout.xaxis.ticktext, means: p.userLayout.shapes.length, rows: p.rows[0].slice(0, 3) }; })()''')
    check('Seasonal Subseries Plot: a small series for each month with its mean line', (sp['n'], sp['ticks'], sp['means']), (12, ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 12))
    check('... January is the rows 0, 12, 24 …', sp['rows'], [0, 12, 24])
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const p = rep.plots.find(p => p.opts.title === 'sales seasonal subseries');
      p._click({ points: [{ curveNumber: 1, pointNumber: 2 }], event: {} }); const sel = t.selectedRows(); t.select([]); return sel; })()''')
    check('... a click selects the row (the third February)', r, [25])
    mt = await page.ev(table_under_js('Season Means'))
    check('... Season Means gives the numbers', (mt[0], len(mt) - 1), (['Season', 'N', 'Mean', 'Std Dev'], 12))
    await shot(page, 'ts-12-subseries.png', 'Seasonal Subseries Plot')
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['Structural Model…']); return await __ts.form({}, 'Estimate');''', timeout=900)
    check('Structural Model: the dialog', t, 'Structural Model Specification: sales')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('... the model with its seasonal and the promotion input (the dialog\'s defaults)', 'Model: Structural: local linear trend + seasonal(12) + promotion' in outl, True)
    check('... its parts', [o for o in outl if o in ('Model Summary', 'Parameter Estimates', 'Forecast', 'Residuals', 'Components', 'Iteration History')][:6],
          ['Model Summary', 'Parameter Estimates', 'Forecast', 'Residuals', 'Components', 'Iteration History'])
    pe = await page.ev(table_under_js('Parameter Estimates'))
    check('... the variances and the input coefficient', ([row[0] for row in pe[1:]], pe[0]),
          (['Irregular Variance (σ²ε)', 'Level Variance (σ²η)', 'Slope Variance (σ²ζ)', 'Seasonal Variance (σ²ω)', 'promotion'], ['Term', 'Estimate', 'Std Error', 'z Ratio', 'Prob>|z|']))
    cp = await page.ev('''(async () => { const p = __ts.rep().plots.find(p => /components$/.test(p.opts.title)); await p.draw();
      return { panels: p.userLayout.annotations.map(a => a.text), bands: p.traces.filter(t => t.fill === 'tonexty').length, linked: p.rows.filter(Boolean).length }; })()''')
    check('Components: level, trend, seasonal, regression and irregular panels, with bands', (cp['panels'], cp['bands']), (['Level', 'Trend (slope)', 'Seasonal', 'Regression effect', 'Irregular'], 4))
    check('... the data in the level panel, linked to the rows', cp['linked'], 1)
    check('... forecasts continue the months', await page.ev('__ts.rep().body.textContent.includes("12 periods ahead, from 2026-01-01 to 2026-12-01")'), True)
    await shot(page, 'ts-13-structural.png', 'Components')
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const before = t.columns.length; await __ts.menu(rep, 'Model: Structural', ['Save Components']);
      await new Promise(r => setTimeout(r, 150)); const added = t.columns.slice(before); const names = added.map(c => c.name); for (const c of added) t.removeColumn(c.id); return names; })()''')
    check('Save Components writes the smoothed components', r, ['Level sales', 'Trend (slope) sales', 'Seasonal sales', 'Regression effect sales', 'Irregular sales'])
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['Theta Model…']); return await __ts.form({}, 'Estimate');''', timeout=900)
    check('Theta Model: the dialog', t, 'Theta Model: sales')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('... the model report', 'Model: Theta Model (θ = 2)' in outl, True)
    rows = await page.ev('__ts.cmpRows(__ts.rep())')
    check('Model Comparison lists the structural and Theta models', sorted(x['name'] for x in rows), ['Structural: local linear trend + seasonal(12) + promotion', 'Theta Model (θ = 2)'])
    band = await page.ev('''(() => { const p = __ts.rep().plots.find(p => p.opts.title === 'Theta Model (θ = 2) forecast'); const u = p.traces.find(t => t.name === 'Theta Model (θ = 2) upper'); return u.y[u.y.length - 1]; })()''')
    await act(page, '''await __ts.menu(__ts.rep(), 'Model: Theta Model', ["statsmodels' Prediction Intervals"]); return true;''')
    band2 = await page.ev('''(() => { const p = __ts.rep().plots.find(p => p.opts.title === 'Theta Model (θ = 2) forecast'); const u = p.traces.find(t => t.name === 'Theta Model (θ = 2) upper'); return u.y[u.y.length - 1]; })()''')
    check("... statsmodels' own prediction intervals are wider than the IMA(1, 1) ones", band2 > band, True)
    check('... and the note says why', await page.ev('__ts.rep().body.textContent.includes("which is not that model\'s variance")'), True)
    pr = await page.ev('__ts.problems(__ts.rep())')
    check('no errors with the new models', pr['errors'], [])

    # ---- By: the new parts in every group
    r = await page.ev('''(async () => {
      const src = SM.app.tables.find(t => t.name === 'Monthly sales');
      const m = src.col('month').values, s = src.col('sales').values;
      const t = new SM.Table({ name: 'Two regions again', columns: [
        { name: 'region', dataType: 'character', values: [...m.map(() => 'North'), ...m.map(() => 'South')] },
        { name: 'month', dataType: 'numeric', format: { kind: 'date' }, values: [...m, ...m] },
        { name: 'sales', dataType: 'numeric', values: [...s, ...s.map((v, i) => v * 0.8 + 5 * Math.sin(i))] } ] });
      SM.app.addTable(t);
      const P = SM.platforms.get('timeseries');
      const rep = SM.app.openReport(P, { roles: { y: [t.col('sales').id], time: [t.col('month').id], by: [t.col('region').id] }, options: { forecast: 6,
        'ts:sales|models': [{ id: 1, kind: 'uc', trend: 'local level', seasonal: 12, level: 0.95 }, { id: 2, kind: 'theta', theta: 2, deseasonalize: true, period: 12, level: 0.95 }],
        'ts:sales|filters': [{ id: 1, kind: 'hp' }], 'ts:sales|subseries': true } }, t);
      await __ts.done(rep);
      const out = { tops: [...rep.body.querySelectorAll('.sm-ob.level-0 > .sm-ob-head h2')].map(h => h.textContent),
        outl: __ts.outlines(rep).filter(o => o.startsWith('Model: ') || o.includes('Filter') || o === 'Seasonal Subseries Plot' || o === 'Zivot-Andrews Test'), ...__ts.problems(rep),
        code: rep.pythonScript().includes('df = df[df["region"] == \\'North\\']') };
      SM.app.closeReport(rep); SM.app.closeTable(t); document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach(b => b.click());
      return out; })()''', timeout=900)
    per = ['Zivot-Andrews Test', 'Seasonal Subseries Plot', 'Hodrick-Prescott Filter (λ = 129600)', 'Model: Structural: local level + seasonal(12)', 'Model: Theta Model (θ = 2)']
    check('By: the new parts in each group', (r['tops'], r['outl']), (['Time Series sales region=North', 'Time Series sales region=South'], per + per))
    check('... without errors, and the code keeps the group', (r['errors'], r['code']), ([], True))

    # ---- a saved project redraws the new models, filters and options
    n_ts_before = await page.ev('SM.app.reports.filter(r => r.platform.id === "timeseries").length')
    r = await page.ev('''(async () => {
      const out = [];
      for (const rep of SM.app.reports.filter(r => r.platform.id === 'timeseries').slice(-4)) {
        const t = rep.table; const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
        const n = SM.app.reports.length; SM.app.loadProject(JSON.parse(JSON.stringify(j))); const r2 = SM.app.reports[n]; await __ts.done(r2);
        out.push({ outlines: __ts.outlines(r2).filter(o => o.startsWith('Model: ') || o.includes('Filter') || o === 'Seasonal Subseries Plot'), ...__ts.problems(r2) });
        const t2 = r2.table; SM.app.closeReport(r2); SM.app.closeTable(t2);   // the copies go again
        document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach(b => b.click());
      }
      return out;
    })()''', timeout=900)
    check('reopened projects redraw the regime model, the filters, ARDL and the sales models', [x['outlines'] for x in r], [
        ['Model: Regime Switching: 2 regimes, AR(1), switching mean'],
        ['Hodrick-Prescott Filter (λ = 1600)', 'Baxter-King Filter (6 to 32 periods, K = 12)', 'Christiano-Fitzgerald Filter (6 to 32 periods)'],
        [o for o in r[2]['outlines'] if o.startswith('Model: ARDL(')],
        ['Seasonal Subseries Plot', 'Model: Structural: local linear trend + seasonal(12) + promotion', 'Model: Theta Model (θ = 2)']])
    check('... without errors', [x['errors'] for x in r], [[], [], [], []])
    check('... ARDL with both its fits', len(r[2]['outlines']), 2)
    script = await page.ev('SM.app.reports.filter(r => r.platform.id === "timeseries").map(r => r.pythonScript()).join("\\n")')
    check('the Python script has the new fits', all(s_ in script for s_ in ('UnobservedComponents', 'MarkovAutoregression', 'hpfilter', 'bkfilter', 'cffilter', 'ThetaModel', 'zivot_andrews', 'ardl_select_order', 'bounds_test', 'month_plot')), True)

    # ---- the new reports in the dark theme and at phone width
    check('the reopened copies are closed again', await page.ev('SM.app.reports.filter(r => r.platform.id === "timeseries").length'), n_ts_before)
    await page.ev('SM.app.showTab(SM.app.tabOf(__ts.rep()))')
    await page.ev('''(async () => { const rep = __ts.rep(); const d = __ts.done(rep); KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark'); await d; })()''', timeout=600)
    await asyncio.sleep(1.0)
    await shot(page, 'ts-14-dark-structural.png', 'Components')
    await shot(page, 'ts-15-dark-subseries.png', 'Seasonal Subseries Plot')
    regime_rep = await page.ev('SM.app.reports.findIndex(r => r.title === "Time Series growth")')
    await page.ev(f'SM.app.showTab(SM.app.tabOf(SM.app.reports[{regime_rep}]))')
    await asyncio.sleep(1.0)
    colors = await page.ev(f'''(() => {{ const rep = SM.app.reports[{regime_rep}]; const p = rep.plots.find(p => /smoothed probabilities$/.test(p.opts.title)); return p.traces.slice(0, 2).map(t => t.line.color); }})()''')
    check('the regime colours are stepped for the dark theme', colors, ['#3987e5', '#d95926'])
    if SHOTS:
        await page.ev(f'''(() => {{ const rep = SM.app.reports[{regime_rep}]; const h = __ts.head(rep, 'Regime Probabilities'); rep.body.scrollTop = h.getBoundingClientRect().top - rep.body.getBoundingClientRect().top + rep.body.scrollTop - 8; }})()''')
        await asyncio.sleep(1.0)
        await page.shot(os.path.join(SHOTS, 'ts-16-dark-regimes.png'))
    ardl_rep = await page.ev('SM.app.reports.findIndex(r => r.title === "Time Series price")')
    await page.ev(f'SM.app.showTab(SM.app.tabOf(SM.app.reports[{ardl_rep}]))')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await page.ev(f'''(async () => {{ const rep = SM.app.reports[{ardl_rep}]; const d = __ts.done(rep); rep.run(); await d; }})()''', timeout=600)
    await asyncio.sleep(1.2)
    check('no horizontal page scroll at phone width (ARDL)', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    if SHOTS:
        await page.ev(f'''(() => {{ const rep = SM.app.reports[{ardl_rep}]; const h = __ts.head(rep, 'Bounds Test'); rep.body.scrollTop = h.getBoundingClientRect().top - rep.body.getBoundingClientRect().top + rep.body.scrollTop - 8; }})()''')
        await asyncio.sleep(1.0)
        await page.shot(os.path.join(SHOTS, 'ts-17-phone-ardl.png'))

    # ==== Forecast on Holdback, benchmarks, the moving average, constraints, Box-Cox, averages, runs tests, cross-validation ====
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await asyncio.sleep(0.6)
    # the launch dialog's Forecast on Holdback, by real clicks
    r = await page.ev('''(async () => {
      const t = SM.app.tables.find((x) => x.name === 'Monthly sales'); SM.app.showTab(SM.app.tabOf(t));
      SM.app.launch('timeseries');
      await new Promise(r => setTimeout(r, 250));
      const dlg = [...document.querySelectorAll('.sm-launch-dialog')].pop();
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { const li = items.find(li => li.textContent === name); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === label);
      pick('sales'); role('Y, Time Series').click();
      pick('month'); role('X, Time ID').click();
      const lab = (text) => [...dlg.querySelectorAll('.sm-launch-opts label')].find(l => l.textContent.startsWith(text));
      lab('Forecast Periods').querySelector('input').value = '12';
      const hb = lab('Forecast on Holdback').querySelector('input');
      hb.click();
      const checked = hb.checked;
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
      const rep = __ts.rep();
      await __ts.done(rep);
      return { checked, title: rep.title, holdback: rep.spec.options.holdback, ...__ts.problems(rep) };
    })()''', timeout=600)
    check('Forecast on Holdback: a launch option, checked by a click', (r['checked'], r['holdback'], r['errors']), (True, True, []))
    # models through the red triangle and their dialogs: ARIMA, Winters, the three benchmarks, a moving average
    await act(page, '''await __ts.menu(__ts.rep(), null, ['ARIMA…']); return await __ts.form({ 'p, Autoregressive Order': 1, 'q, Moving Average Order': 1 }, 'Estimate');''')
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Smoothing Models', 'Winters Method…']); return await __ts.form({}, 'Estimate');''')
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['Benchmark Models', 'All Three…']); return await __ts.form({}, 'Estimate');''')
    check('Benchmark Models > All Three: its dialog', t, 'Benchmark Models: sales')
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['Smoothing Models', 'Simple Moving Average…']);
      return await __ts.form({ 'Smoothing window width': 12, 'Centering': 'double' }, 'Estimate');''')
    check('Smoothing Models > Simple Moving Average: its dialog', t, 'Simple Moving Average: sales')
    hdr = await page.ev('''[...__ts.rep().body.querySelectorAll('table.sm-ts-cmp thead th')].map(th => th.textContent)''')
    check('holdback: Model Comparison shows the holdback statistics, JMP\'s RMSE, MSE, MAPE, MAE with the mean error and MASE', hdr,
          ['Report', 'Graph', 'Model', 'RMSE', 'MSE', 'MAPE', 'MAE', 'Mean Error', 'MASE', 'N'])
    rows = await page.ev('''[...__ts.rep().body.querySelectorAll('table.sm-ts-cmp tbody tr')].map(tr => [...tr.children].slice(2).map(c => c.textContent))''')
    names = [x[0] for x in rows]
    check('... the models, the benchmarks and the moving average', sorted(names), sorted(['ARMA(1, 1)', 'Winters Method (Additive)(12)', 'Naive', 'Seasonal Naive(12)', 'Drift',
                                                                                          'Simple Moving Average(12, centered and double smoothed)']))
    rm = [num(x[1]) for x in rows]
    check('... sorted by RMSE, as JMP sorts them', rm == sorted(rm), True)
    check('... N: the 12 held-back months', {x[7] for x in rows}, {'12'})
    # the numbers against the page's own arithmetic: the Naive and Seasonal Naive forecasts of the last 12 months
    js = await page.ev('''(() => { const v = SM.app.tables.find(t => t.name === 'Monthly sales').col('sales').values; const n = v.length, h = 12;
      const act = v.slice(n - h), last = v[n - h - 1], seas = v.slice(n - 2 * h, n - h);
      const stats = (f) => { const e = act.map((a, i) => a - f[i]); const mse = e.reduce((s, x) => s + x * x, 0) / h; const mae = e.reduce((s, x) => s + Math.abs(x), 0) / h;
        return { rmse: SM.util.fmt(Math.sqrt(mse)), mae: SM.util.fmt(mae), me: SM.util.fmt(e.reduce((s, x) => s + x, 0) / h), mape: SM.util.fmt(100 * e.reduce((s, x, i) => s + Math.abs(x / act[i]), 0) / h) }; };
      const tr = v.slice(0, n - h); let sc = 0; for (let i = 12; i < tr.length; i++) sc += Math.abs(tr[i] - tr[i - 12]); sc /= tr.length - 12;
      const naive = stats(new Array(h).fill(last)), sn = stats(seas);
      const maeN = act.reduce((s, a) => s + Math.abs(a - last), 0) / h;
      return { naive, sn, mase: SM.util.fmt(maeN / sc) }; })()''')
    got = {x[0]: x for x in rows}
    check('the Naive row: RMSE, MAPE, MAE, mean error of the last value as the forecast, computed in the page', [got['Naive'][i] for i in (1, 3, 4, 5)],
          [js['naive'][k] for k in ('rmse', 'mape', 'mae', 'me')])
    check('... its MASE: the MAE over the training values\' seasonal naive MAE (the calendar\'s period 12)', got['Naive'][6], js['mase'])
    check('the Seasonal Naive row: the same months a year before, computed in the page', [got['Seasonal Naive(12)'][i] for i in (1, 3, 4, 5)],
          [js['sn'][k] for k in ('rmse', 'mape', 'mae', 'me')])
    code_hb = await page.ev('''(() => { const h = __ts.head(__ts.rep(), 'Model Comparison'); const c = h.parentElement.querySelector('details.sm-code code'); return c ? c.textContent : null; })()''')
    check('... the table\'s code: each model on the training values, holdback_stats, sorted by RMSE', bool(code_hb) and 'def holdback_stats(' in code_hb and 'sort_values("RMSE")' in code_hb, True)
    await page.ev(GRAPHS_JS)
    out = await page.ev(f'__gr.run({json.dumps(code_hb)}, __ts.rep().table)', timeout=600)
    txt = json.dumps(out)
    check('... it runs in the page and prints the Naive row\'s RMSE', ('Naive' in txt, js['naive']['rmse'][:6] in txt.replace('\\n', ' ')), (True, True))
    # the holdback shaded in the graphs, the forecasts at the held-back months
    g = await page.ev('''(async () => { const rep = __ts.rep(); const p = rep.plots.find(p => p.opts.title === 'sales model comparison forecasts on the holdback'); await p.draw();
      const sh = p.userLayout.shapes; const fcs = p.traces.filter(t => / forecast$/.test(t.name)); return { rect: sh.filter(s => s.type === 'rect').map(s => [s.x0, s.x1]), line: sh.filter(s => s.type === 'line').map(s => s.x0),
        firstFc: fcs.length ? fcs[0].x[1] : null, lastFc: fcs.length ? fcs[0].x[fcs[0].x.length - 1] : null }; })()''')
    check('the comparison plot: the held-back months shaded, from the last training month to the last month', (g['rect'], g['line']), ([['2024-12-01', '2025-12-01']], ['2024-12-01']))
    check('... the forecasts at the held-back months', (g['firstFc'], g['lastFc']), ('2025-01-01', '2025-12-01'))
    hs = dict(tuple(x) for x in await page.ev(table_under_js('Holdback Statistics')))
    check('each model\'s report: Holdback Statistics under Forecast', all(k in hs for k in ('RMSE', 'MSE', 'MAPE', 'MAE', 'Mean Error', 'MASE', 'N')), True)
    # Save Columns: the training rows' predictions, the held-back rows' forecasts and errors, a Set column
    r = await page.ev('''(async () => { const before = SM.app.tables.length; await __ts.menu(__ts.rep(), 'Model: Naive', ['Save Columns']); await new Promise(r => setTimeout(r, 200));
      const t = SM.app.tables[SM.app.tables.length - 1]; const set = t.col('Set').values; const res = t.col('Residual sales').values; const pr = t.col('Predicted sales').values;
      const act = t.col('Actual sales').values; const n = t.nrows;
      const hold = [...Array(n).keys()].filter(i => set[i] === 'Holdback');
      const rmse = Math.sqrt(hold.reduce((s, i) => s + res[i] ** 2, 0) / hold.length);
      const out = { added: SM.app.tables.length - before, rows: n, sets: [...new Set(set)], nhold: hold.length, err: hold.every(i => Math.abs(res[i] - (act[i] - pr[i])) < 1e-9), rmse: SM.util.fmt(rmse),
        cols: t.columns.map(c => c.name) };
      SM.app.closeTable(t); document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach(b => b.click());
      SM.app.showTab(SM.app.tabOf(__ts.rep()));
      return out; })()''')
    check('Save Columns with values held back: a Set column, Training and Holdback, 120 rows', (r['added'], r['rows'], r['sets'], r['nhold'], r['cols'][-1]), (1, 120, ['Training', 'Holdback'], 12, 'Set'))
    check('... the held-back rows\' residuals are the forecast errors, actual − forecast, and give the table\'s RMSE', (r['err'], r['rmse']), (True, got['Naive'][1]))
    # Save Prediction Formula: the benchmarks' and the moving average's one-step predictions as live formula columns
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const before = t.columns.length; await __ts.menu(rep, 'Model: Naive', ['Save Prediction Formula']);
      await new Promise(r => setTimeout(r, 300)); const c = t.columns[t.columns.length - 1]; const v = t.col('sales').values;
      const out = { added: t.columns.length - before, formula: c.formula && c.formula.expr, first: c.values[0], ok: c.values.slice(1).every((x, i) => x === v[i]) }; t.removeColumn(c.id); return out; })()''')
    check('Save Prediction Formula (Naive): a live column Lag(:sales, 1), each row the value before', (r['added'], r['formula'], r['first'], r['ok']), (1, 'Lag(:sales, 1)', None, True))
    await act(page, '''const rep = __ts.rep(); rep.run(); return true;''')
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const p = rep.plots.find(p => p.opts.title === 'Simple Moving Average(12, centered and double smoothed) forecast'); await p.draw();
      const fit = p.traces.find(tr => tr.name === 'Predicted').y; await __ts.menu(rep, 'Model: Simple Moving Average', ['Save Prediction Formula']);
      await new Promise(r => setTimeout(r, 300)); const c = t.columns[t.columns.length - 1];
      const out = { formula: c.formula && c.formula.expr.slice(0, 40), ok: fit.every((x, i) => x == null ? !Number.isFinite(c.values[i]) : Math.abs(x - c.values[i]) < 1e-9 * Math.abs(x)) }; t.removeColumn(c.id); return out; })()''')
    check('Save Prediction Formula (moving average): the mean of the 12 lags, the report\'s one-step predictions', (r['formula'], r['ok']), ('(Lag(:sales, 1) + Lag(:sales, 2) + Lag(:', True))
    await act(page, '''const rep = __ts.rep(); rep.run(); return true;''')
    # Refit on All Rows, from the red triangle
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Refit on All Rows']); return true;''')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('Refit on All Rows: every model again on all the values, a plot of the forecasts after the end', ('Refit on All Rows' in outl, outl.count('Forecast, Refit on All Rows'), 6), (True, 6, 6))
    r = await page.ev('''(async () => { const rep = __ts.rep(); const p = rep.plots.find(p => p.opts.title === 'Naive forecast, refit on all rows'); await p.draw();
      const fc = p.traces.find(t => t.name === 'Naive forecast'); const v = rep.table.col('sales').values;
      return { first: fc.x[1], last: fc.x[fc.x.length - 1], value: fc.y[1], lastValue: v[v.length - 1] }; })()''')
    check('... the Naive refit forecasts the last value, from 2026-01-01', (r['first'], r['last'], abs(r['value'] - r['lastValue']) < 1e-9), ('2026-01-01', '2026-12-01', True))
    r = await page.ev('''(async () => { const before = SM.app.tables.length; await __ts.menu(__ts.rep(), 'Model: Naive', ['Save Columns']); await new Promise(r => setTimeout(r, 200));
      const t = SM.app.tables[SM.app.tables.length - 1]; const set = t.col('Set').values; const out = { rows: t.nrows, n: ['Training', 'Holdback', 'Forecast'].map(k => set.filter(x => x === k).length),
        lastTime: t.columns[0].values[t.nrows - 1] };
      SM.app.closeTable(t); document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach(b => b.click()); SM.app.showTab(SM.app.tabOf(__ts.rep())); return out; })()''')
    check('... Save Columns then adds the 12 forecasts after the end (Set Forecast)', (r['rows'], r['n'], r['lastTime']), (132, [108, 12, 12], await page.ev('Date.UTC(2026, 11, 1)')))
    # Custom constraints: Simple Exponential Smoothing with α fixed at 0.3, through both dialogs
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['Smoothing Models', 'Simple Exponential Smoothing…']);
      await __ts.form({ 'Constraints': 'custom' }, 'Estimate');
      await new Promise(r => setTimeout(r, 200));
      window.__custom = [...[...document.querySelectorAll('.sm-dialog')].pop().querySelectorAll('.sm-form label')].map(l => l.textContent);
      return await __ts.form({ 'α, Level Smoothing Weight': 'fix', 'α: fixed value': 0.3 }, 'Estimate');''')
    check('Custom constraints: a second dialog after OK, a line per weight', (t, await page.ev('window.__custom')),
          ('Custom Constraints: Simple Exponential Smoothing', ['α, Level Smoothing Weight', 'α: fixed value', 'α: lower bound', 'α: upper bound']))
    pe = await page.ev('''(() => { const h = __ts.head(__ts.rep(), 'Model: Simple Exponential Smoothing, α = 0.3'); if (!h) return null; const t = h.parentElement.querySelector('table.sm-rt');
      return [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent)); })()''')
    check('... the model, named by its constraint, α = 0.3 Fixed, with no standard error', pe and (pe[1][0], pe[1][1], pe[0][-1], pe[1][-1], pe[1][2]), ('Level Smoothing Weight', '0.3', 'Constraint', 'Fixed', '.'))
    # Box-Cox: Winters on the log scale
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Smoothing Models', 'Winters Method…']); return await __ts.form({ 'Box-Cox transformation': true, 'λ, Box-Cox': 0 }, 'Estimate');''')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('Box-Cox: Winters on the log scale, named so', 'Model: Winters Method (Additive)(12), Box-Cox λ = 0' in outl, True)
    # the moving average: the smoothed series and its forecasts against the page's arithmetic
    r = await page.ev('''(async () => { const rep = __ts.rep(); const v = rep.table.col('sales').values; const n = v.length - 12;
      const p = rep.plots.find(p => p.opts.title === 'Simple Moving Average(12, centered and double smoothed) smoothed series'); await p.draw();
      const sm = p.traces[1].y; const t = 60; let want = 0.5 * v[t - 6] + 0.5 * v[t + 6]; for (let j = t - 5; j <= t + 5; j++) want += v[j]; want /= 12;
      const f = rep.plots.find(p => p.opts.title === 'Simple Moving Average(12, centered and double smoothed) forecast').traces.find(t => / forecast$/.test(t.name)).y[1];
      const trail = v.slice(n - 12, n).reduce((s, x) => s + x, 0) / 12;
      return { sm: Math.abs(sm[t] - want) < 1e-9, f: Math.abs(f - trail) < 1e-9 }; })()''')
    check('Simple Moving Average: the centered and double smoothed series (1/24 at the ends, 1/12 inside) and the trailing forecast, computed in the page', r, {'sm': True, 'f': True})
    r = await page.ev('''(async () => { const rep = __ts.rep(); const t = rep.table; const before = t.columns.length; await __ts.menu(rep, 'Model: Simple Moving Average', ['Save Moving Average']);
      await new Promise(r => setTimeout(r, 150)); const c = t.columns[t.columns.length - 1]; const out = { added: t.columns.length - before, name: c.name, first: c.values[5], v6: Number.isFinite(c.values[6]) }; t.removeColumn(c.id); return out; })()''')
    check('... Save Moving Average writes the smoothed series, missing where the window is not whole', (r['added'], r['name'], r['first'], r['v6']),
          (1, 'sales Simple Moving Average(12, centered and double smoothed)', None, True))
    # the averaged forecast, through its dialog: ARMA(1, 1) and Winters
    t = await act(page, '''await __ts.menu(__ts.rep(), 'Model Comparison', ['Averaged Forecast…']);
      const dlg = [...document.querySelectorAll('.sm-dialog')].pop(); const labs = [...dlg.querySelectorAll('.sm-form label')].map(l => l.textContent);
      const vals = {}; for (const l of labs) if (l !== 'Prediction Interval') vals[l] = l === 'ARMA(1, 1)' || l === 'Winters Method (Additive)(12)';
      return await __ts.form(vals, 'Estimate');''')
    check('Averaged Forecast: its dialog lists the models', t, 'Averaged Forecast: sales')
    r = await page.ev('''(async () => { const rep = __ts.rep(); const fcOf = async (title) => { const p = rep.plots.find(p => p.opts.title === title); await p.draw(); return p.traces.find(t => / forecast$/.test(t.name)).y.slice(1); };
      const a = await fcOf('ARMA(1, 1) forecast'), w = await fcOf('Winters Method (Additive)(12) forecast'), m = await fcOf('Average of ARMA(1, 1), Winters Method (Additive)(12) forecast');
      return m.every((v, i) => Math.abs(v - (a[i] + w[i]) / 2) < 1e-9 * Math.abs(v)); })()''')
    check('... its forecasts of the held-back months are the mean of the two models\', computed in the page', r, True)
    # the runs test of the series (about the mean) and of a model's residuals
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Runs Test', 'About the Mean']); return true;''')
    rt = dict(tuple(x) for x in await page.ev(table_under_js('Runs Test')))
    js = await page.ev('''(() => { const v = __ts.rep().table.col('sales').values; const n = v.length; const m = v.reduce((s, x) => s + x, 0) / n;
      const up = v.map(x => x >= m); let R = 1; for (let i = 1; i < n; i++) if (up[i] !== up[i - 1]) R++; const n1 = up.filter(Boolean).length, n2 = n - n1;
      const E = 2 * n1 * n2 / n + 1, V = 2 * n1 * n2 * (2 * n1 * n2 - n) / (n * n * (n - 1)); return { R: String(R), E: SM.util.fmt(E), z: SM.util.fmt((R - E) / Math.sqrt(V)) }; })()''')
    check('Runs Test about the mean: the runs, their expectation and z, computed in the page', (rt.get('Runs'), rt.get('Expected Runs'), rt.get('z')), (js['R'], js['E'], js['z']))
    await act(page, '''await __ts.menu(__ts.rep(), 'Model: Naive', ['Residual Statistics', 'Runs Test']); return true;''')
    r = await page.ev('''(() => { const h = __ts.head(__ts.rep(), 'Model: Naive'); const caps = [...h.parentElement.querySelectorAll('table.sm-kv caption')].map(c => c.textContent); return caps; })()''')
    check('... a model\'s Residual Statistics > Runs Test: its residuals about zero', 'Residual Runs Test' in r, True)
    # rolling-origin cross-validation, from Model Comparison's red triangle
    t = await act(page, '''await __ts.menu(__ts.rep(), 'Model Comparison', ['Rolling-Origin Cross-Validation…']); return await __ts.form({ 'Number of origins': 3, 'Horizon (values forecast from each origin)': 6 }, 'OK');''', timeout=900)
    check('Rolling-Origin Cross-Validation: its dialog', t, 'Rolling-Origin Cross-Validation: sales')
    cvm = await page.ev(table_under_js('Rolling-Origin Cross-Validation'))
    check('... the means over the origins, a row per model, best RMSE first', (cvm[0], len(cvm) - 1, all(num(cvm[i][1]) <= num(cvm[i + 1][1]) for i in range(1, len(cvm) - 1))),
          (['Model', 'RMSE', 'MAE', 'MAPE', 'Origins'], 9, True))
    per = await page.ev(table_under_js('Per Origin'))
    sn = [row for row in per[1:] if row[0] == 'Seasonal Naive(12)']
    js = await page.ev('''(() => { const v = __ts.rep().table.col('sales').values; const n = v.length; const out = [];
      for (const cut of [12, 6, 0]) { const o = n - cut - 6; let s = 0; for (let i = 0; i < 6; i++) s += (v[o + i] - v[o + i - 12]) ** 2; out.push(SM.util.fmt(Math.sqrt(s / 6))); } return out; })()''')
    check('... Per Origin: Seasonal Naive\'s RMSE at each of 3 origins 6 apart, computed in the page', [row[4] for row in sn], js)
    check('... the origins\' last training months', [row[1] for row in sn], ['2024-06-01', '2024-12-01', '2025-06-01'])
    await shot(page, 'ts-18-holdback.png', 'Model Comparison')
    await shot(page, 'ts-19-cv.png', 'Rolling-Origin Cross-Validation')
    # State Space Smoothing: the multiplicative trends in the dialog
    t = await act(page, '''await __ts.menu(__ts.rep(), null, ['State Space Smoothing Models…']);
      window.__lead = [...document.querySelectorAll('.sm-dialog .sm-dialog-lead')].pop().textContent;
      return await __ts.form({ 'Error: Additive (A)': false, 'Trend: None (N)': false, 'Trend: Additive (A)': false, 'Trend: Additive damped (Ad)': false,
        'Trend: Multiplicative (M)': true, 'Trend: Multiplicative damped (Md)': true, 'Seasonal: Multiplicative (M)': false, 'Seasonal: None (N)': false }, 'OK');''', timeout=900)
    lead = await page.ev('window.__lead')
    check('State Space Smoothing: the lead no longer says statsmodels has no multiplicative trend; up to 30 models', ('no multiplicative trend' not in lead, 'up to 30' in lead), (True, True))
    sel = await page.ev(table_under_js('State Space Smoothing Model Selection 1'))
    check('... ETS(M,M,A) and ETS(M,Md,A), ranked by their holdback RMSE with values held back', (sorted(row[0] for row in sel[1:]), sel[0][-3:-1]),
          (['ETS(M,M,A)12', 'ETS(M,Md,A)12'], ['Holdback RMSE', 'Holdback MAPE']))
    pr = await page.ev('__ts.problems(__ts.rep())')
    check('no errors in the holdback report', pr['errors'], [])
    # a saved project keeps holdback, refit, the constrained, Box-Cox, moving average and averaged models, the runs test and the cross-validation
    r = await page.ev('''(async () => {
      const rep = __ts.rep(); const t = rep.table; const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      const n = SM.app.reports.length; SM.app.loadProject(JSON.parse(JSON.stringify(j))); const r2 = SM.app.reports[n]; await __ts.done(r2);
      const out = { outlines: __ts.outlines(r2).filter(o => o.startsWith('Model: ') || ['Runs Test', 'Rolling-Origin Cross-Validation', 'Refit on All Rows'].includes(o)),
        cols: [...r2.body.querySelectorAll('table.sm-ts-cmp thead th')].map(th => th.textContent).slice(3, 5), ...__ts.problems(r2) };
      const t2 = r2.table; SM.app.closeReport(r2); SM.app.closeTable(t2); document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach(b => b.click());
      SM.app.showTab(SM.app.tabOf(rep)); return out; })()''', timeout=900)
    for o in ('Model: Simple Exponential Smoothing, α = 0.3', 'Model: Winters Method (Additive)(12), Box-Cox λ = 0', 'Model: Simple Moving Average(12, centered and double smoothed)',
              'Model: Average of ARMA(1, 1), Winters Method (Additive)(12)', 'Runs Test', 'Rolling-Origin Cross-Validation', 'Refit on All Rows'):
        check(f'a reopened project: {o}', o in r['outlines'], True)
    check('... the holdback columns, and no errors', (r['cols'], r['errors']), (['RMSE', 'MSE'], []))
    # By: every group held back
    r = await page.ev('''(async () => {
      const src = SM.app.tables.find(t => t.name === 'Monthly sales'); const m = src.col('month').values, s = src.col('sales').values;
      const t = new SM.Table({ name: 'Two regions, held back', columns: [
        { name: 'region', dataType: 'character', values: [...m.map(() => 'North'), ...m.map(() => 'South')] },
        { name: 'month', dataType: 'numeric', format: { kind: 'date' }, values: [...m, ...m] },
        { name: 'sales', dataType: 'numeric', values: [...s, ...s.map((v, i) => v * 0.8 + 5 * Math.sin(i))] } ] });
      SM.app.addTable(t);
      const rep = SM.app.openReport(SM.platforms.get('timeseries'), { roles: { y: [t.col('sales').id], time: [t.col('month').id], by: [t.col('region').id] }, options: { forecast: 6, holdback: true,
        'ts:sales|models': [{ id: 1, kind: 'bench', method: 'naive', s: 0, level: 0.95 }, { id: 2, kind: 'sma', width: 4, centering: 'none', level: 0.95 }] } }, t);
      await __ts.done(rep);
      const out = { n: [...rep.body.querySelectorAll('table.sm-ts-cmp')].map(tb => [...tb.querySelectorAll('tbody tr')].map(tr => tr.children[tr.children.length - 1].textContent)), ...__ts.problems(rep),
        code: rep.pythonScript().includes('y_all = y; y, y_hold = y_all.iloc[:-6], y_all.iloc[-6:]') };
      SM.app.closeReport(rep); SM.app.closeTable(t); document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach(b => b.click()); return out; })()''', timeout=900)
    check('By: each group\'s models fitted without its last 6 values, N 6 in each', (r['n'], r['errors'], r['code']), ([['6', '6'], ['6', '6']], [], True))
    # the holdback report in the dark theme and at phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(__ts.rep()))')
    await page.ev('''(async () => { const rep = __ts.rep(); const d = __ts.done(rep); KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark'); await d; })()''', timeout=900)
    await asyncio.sleep(1.0)
    shade = await page.ev('''(() => { const p = __ts.rep().plots.find(p => p.opts.title === 'sales model comparison forecasts on the holdback'); return p.userLayout.shapes.find(s => s.type === 'rect').fillcolor; })()''')
    check('dark theme: the holdback shading in the dark theme\'s colours', shade, 'rgba(200, 190, 178, 0.14)')
    await shot(page, 'ts-20-dark-holdback.png', 'Model Comparison')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await page.ev('''(async () => { const rep = __ts.rep(); const d = __ts.done(rep); rep.run(); await d; })()''', timeout=900)
    await asyncio.sleep(1.2)
    check('no horizontal page scroll at phone width (holdback, cross-validation)', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, 'ts-21-phone-cv.png', 'Rolling-Origin Cross-Validation')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await page.ev('''(async () => { const rep = __ts.rep(); const d = __ts.done(rep); rep.run(); await d; })()''', timeout=900)
    # every graph of the holdback report against its code's figure
    await page.ev(TSG_JS)
    # the new models' reports and graphs only, and none of the series' own charts (the older kinds are checked above)
    await page.ev('''(async () => { const rep = __ts.rep(); const o = rep.spec.options; const k = 'ts:sales|models';
      const keep = (m) => m.kind === 'bench' && m.method === 'naive' || m.kind === 'sma' || m.kind === 'avg' || (m.kind === 'smooth' && m.boxcox != null);
      const members = new Set(o[k].filter((m) => m.kind === 'avg').flatMap((m) => m.members));   // the average's members stay, out of sight
      o[k] = o[k].filter((m) => keep(m) || members.has(m.id)).map((m) => ({ ...m, report: keep(m), graph: keep(m), racf: false, rpacf: false }));
      for (const x of ['acf', 'pacf', 'stationarity']) o[`ts:sales|${x}`] = false;
      const d = __ts.done(rep); rep.run(); await d; window.__tsc = rep; })()''', timeout=900)
    g = await check_report_graphs(page, 'window.__tsc', 'window.__tsc.table', 'charts: holdback')
    labels = [x['label'] for x in g['g']]
    check('charts: holdback: the comparison, refit, cross-validation, moving average and model graphs', [x for x in ('sales model comparison forecasts on the holdback', 'sales model comparison forecasts, refit on all rows',
          'sales cross-validation RMSE by origin', 'Simple Moving Average(12, centered and double smoothed) smoothed series', 'Naive forecast', 'Naive forecast, refit on all rows',
          'Average of ARMA(1, 1), Winters Method (Additive)(12) forecast', 'Winters Method (Additive)(12), Box-Cox λ = 0 forecast') if x not in labels], [])
    hb_id = await page.ev('SM.app.reports.indexOf(__ts.rep())')

    # ==== Save Columns: the one-step predictions of the missing values, against statsmodels in the page ====
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await page.ev(GRAPHS_JS)
    await page.ev(TSG_JS)
    r = await page.ev('''(async () => { const t = SM.app.tables.find(x => x.name === 'Monthly sales'); SM.app.showTab(SM.app.tabOf(t)); t.setState([30, 31], 'excluded', true);
      const rep = SM.app.openReport(SM.platforms.get('timeseries'), { roles: { y: [t.col('sales').id], time: [t.col('month').id] }, options: { forecast: 6,
        'ts:sales|models': [{ id: 1, kind: 'arima', p: 1, d: 0, q: 1, P: 0, D: 0, Q: 0, s: 0, intercept: true, constrain: true, level: 0.95 }, { id: 2, kind: 'bench', method: 'naive', s: 0, level: 0.95 }],
        'ts:sales|acf': false, 'ts:sales|pacf': false, 'ts:sales|stationarity': false } }, t);
      await __ts.done(rep);
      const save = async (title) => { await __ts.menu(rep, title, ['Save Columns']); await new Promise(r => setTimeout(r, 200));
        const s = SM.app.tables[SM.app.tables.length - 1]; const col = (n) => s.col(n).values;
        const out = { pred: [30, 31, 32].map(i => col('Predicted sales')[i]), se: col('Std Err Pred sales')[30], resid: [30, 31, 32].map(i => col('Residual sales')[i]),
          upper: col('Upper CL (0.95) sales')[30], actual: col('Actual sales')[30] };
        SM.app.closeTable(s); document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach(b => b.click()); SM.app.showTab(SM.app.tabOf(rep)); return out; };
      const a = await save('Model: ARMA(1, 1)'); const nv = await save('Model: Naive');
      const v = t.col('sales').values; t.setState([30, 31], 'excluded', false);
      const out = { a, nv, v29: v[29], ...__ts.problems(rep) }; SM.app.closeReport(rep); return out; })()''', timeout=900)
    check('Save Columns at excluded rows: no errors', r['errors'], [])
    code = '\n'.join(['import numpy as np', 'import pandas as pd', 'from statsmodels.tsa.arima.model import ARIMA',
                      'df = pd.read_csv("Monthly sales.csv", float_precision="round_trip")', 'y = df["sales"].to_numpy(dtype=float, copy=True); y[[30, 31]] = np.nan   # the excluded rows',
                      'res = ARIMA(y, order=(1, 0, 1), trend="c").fit()   # the Kalman filter predicts through them',
                      'se = res.get_prediction().se_mean',
                      'print("SMUI-FV", repr(float(res.fittedvalues[30])), repr(float(res.fittedvalues[31])), repr(float(se[30])))'])
    out = await page.ev(f'__gr.run({json.dumps(code)}, SM.app.tables.find(x => x.name === "Monthly sales"))', timeout=600)
    num_ = r'(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)'
    m = re.search(rf'SMUI-FV {num_} {num_} {num_}', json.dumps(out))
    fv = [float(m.group(i)) for i in (1, 2, 3)] if m else None
    check('ARMA(1, 1), Save Columns: the excluded months get the Kalman filter\'s own one-step predictions (statsmodels run in the page)', fv and close(r['a']['pred'][:2], fv[:2], 1e-5), True)
    check('... with its standard error, and limits from it', fv and (close(r['a']['se'], fv[2], 1e-5), close(r['a']['upper'], r['a']['pred'][0] + 1.959963984540054 * r['a']['se'], 1e-9)), (True, True))
    check('... their residuals and actual values stay empty; the next month is as before', (r['a']['resid'][:2], r['a']['actual'], r['a']['resid'][2] is not None), ([None, None], None, True))
    check('Naive: the first excluded month is predicted by the value before it; the second has none (its value before is missing too)', (r['nv']['pred'][0] == r['v29'], r['nv']['pred'][1]), (True, None))

    # ==== Axis Settings on the stacked graphs: a decomposition, a filter, a structural model's components ====
    r = await page.ev(open_js('Monthly sales', {'y': ['sales'], 'time': ['month']}, {
        'forecast': 6, 'ts:sales|acf': False, 'ts:sales|pacf': False, 'ts:sales|stationarity': False, 'ts:sales|graph': False,
        'ts:sales|decomps': [{'id': 1, 'kind': 'classical', 'period': 12, 'model': 'additive'}],
        'ts:sales|filters': [{'id': 1, 'kind': 'hp'}],
        'ts:sales|models': [{'id': 1, 'kind': 'uc', 'trend': 'local level', 'seasonal': 12, 'level': 0.95, 'graph': False, 'racf': False, 'rpacf': False}]}), timeout=900)
    check('stacked graphs: the report opens without errors', r['errors'], [])
    r = await page.ev('''(async () => { const rep = window.__tsc; await __gr.graphs(rep);
      const dec = rep.plots.find(p => p.opts.title === 'Seasonal Decomposition (additive, period 12)'), hp = rep.plots.find(p => /^Hodrick-Prescott Filter/.test(p.opts.title)),
        uc = rep.plots.find(p => / components$/.test(p.opts.title));
      const S = {};
      S[SM.axis.keyOf(dec)] = { yaxis2: { log: true, refs: [{ value: 140, label: 'target', color: 'red', dash: 'dash' }] },
        xaxis: { min: 1483228800000, max: 1764547200000, refs: [{ value: Date.UTC(2020, 0, 1), label: 'break', color: 'blue' }] },
        yaxis4: { refs: [{ value: -5, to: 5, color: 'green' }] } };
      S[SM.axis.keyOf(hp)] = { yaxis: { log: true }, yaxis2: { refs: [{ value: 0, label: 'zero' }] } };
      S[SM.axis.keyOf(uc)] = { yaxis: { log: true }, xaxis: { refs: [{ value: Date.UTC(2021, 5, 1), color: 'orange', dash: 'dot' }] } };
      rep.spec.options.axisSettings = S; const d = __ts.done(rep); rep.run(); await d; await __gr.graphs(rep);
      const L = (p) => p.box._fullLayout; const P = (f) => rep.plots.find(f);
      const d2 = P(p => p.opts.title === 'Seasonal Decomposition (additive, period 12)'), h2 = P(p => /^Hodrick-Prescott Filter/.test(p.opts.title)), u2 = P(p => / components$/.test(p.opts.title));
      // the panels the date reference line crosses on the graph: the y axes whose domains its shapes span
      // (a date axis's shapes are dates as text, UTC: the axis's own r2l turns them into the page's milliseconds)
      const xa = L(d2).xaxis;
      const across = (d2.box.layout.shapes || []).filter(x => x.type === 'line' && x.xref === 'x' && x.x0 === x.x1 && xa.r2l(x.x0) === Date.UTC(2020, 0, 1)).map(x => x.yref);
      const winMs = xa.range.map((v) => xa.r2l(v));
      return { dec: [L(d2).yaxis2.type, L(d2).yaxis.type, L(d2).xaxis.range], hp: [L(h2).yaxis.type, L(h2).yaxis2.type], uc: [L(u2).yaxis.type, L(u2).yaxis2.type], n: rep.plots.length, across, winMs }; })()''', timeout=900)
    check('Axis Settings on a stacked panel: the decomposition\'s Trend panel on a log scale, the others not', r['dec'][:2], ['log', 'linear'])
    check('... the filter\'s top panel, the components\' level panel', (r['hp'], r['uc']), (['log', 'linear'], ['log', 'linear']))
    g = await check_report_graphs(page, 'window.__tsc', 'window.__tsc.table', 'axis settings on stacked graphs')
    codes = {x['label']: x['code'] for x in g['g']}
    dec_code = codes.get('Seasonal Decomposition (additive, period 12)') or ''
    check('the decomposition\'s code: each panel\'s settings on its axes, the x axis on the bottom one',
          ('target = plt.gcf().axes[1]' in dec_code, 'target = plt.gcf().axes[3]' in dec_code, 'set_yscale("log")' in dec_code, '(the settings of' not in dec_code), (True, True, True, True))
    F, err = await run_ts(page, dec_code, 'window.__tsc.table')
    check('... it runs in the page', err, None)
    if F:
        A = F[0]['axes']
        check('... its figure: the Trend panel (the second axes) on a log scale, the others linear', [a['yscale'] for a in A], ['linear', 'log', 'linear', 'linear'])
        want = [to_days(DATE_MIN), to_days(DATE_MAX)]
        check('... the settings\' date window on every panel (shared x)', all(close(a['xlim'], want, 1e-12) for a in A), True)
        # the graph's own window exactly the settings' (Axis Settings gives a date axis its dates as UTC text, not milliseconds,
        # which Plotly read in the browser's local time), in Plotly's milliseconds and in the code's days
        check('... the graph\'s own date window, exactly the settings\' (and the code\'s)', (r['winMs'], all(close([to_days(g_) for g_ in r['dec'][2]], want, 1e-12) for _ in [0])), ([DATE_MIN, DATE_MAX], True))
        at = 18262.0   # 2020-01-01 in days since 1970, the x reference line
        on = [any(len(ln['x']) == 2 and ln['x'][0] is not None and abs(ln['x'][0] - at) < 1e-9 and ln['x'][0] == ln['x'][1] for ln in a['lines']) for a in A]
        want_on = [any(axis_at(y_) == i for y_ in r['across']) for i in range(4)]
        check('... the date reference line crosses the same panels in the code as on the graph (every panel: the x axis serves them all)', (on, want_on), ([True] * 4, [True] * 4))
        check('... its label once, on the bottom panel', [sum(1 for t_ in a['texts'] if t_['s'] == 'break') for a in A], [0, 0, 0, 1])
    for label, want in (('Hodrick-Prescott Filter (λ = 129600)', ['log', 'linear']), (next((k for k in codes if k.endswith(' components')), ''), ['log', 'linear'])):
        F, err = await run_ts(page, codes.get(label) or '', 'window.__tsc.table')
        check(f'{label}: its code runs, the first panel on a log scale as the graph\'s', (err, F and [a['yscale'] for a in F[0]['axes']][:2]), (None, want))
    await page.ev('SM.app.closeReport(window.__tsc)')

    # ==== Time Series Forecast: many series, the best ETS model of each ====
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    menu = await page.ev('''(() => { const it = SM.app.menuItems("Analyze").find(i => i.label === "Specialized Modeling"); const sub = typeof it.submenu === "function" ? it.submenu() : it.submenu; return sub.map(i => i.label); })()''')
    check('Analyze > Specialized Modeling lists Time Series Forecast', 'Time Series Forecast…' in (menu or []), True)
    r = await page.ev('''(() => { const t = SM.io.example('stores'); SM.app.addTable(t); const c = t.col('store');
      return { name: t.name, rows: t.nrows, labels: [1, 2, 3, 4].map(v => SM.grid.cellText(c, v)), listed: !!SM.io.EXAMPLES.stores }; })()''')
    check('the Store sales example: 4 stores × 72 months, stacked, the store a code with value labels', (r['name'], r['rows'], r['labels'], r['listed']),
          ('Store sales', 288, ['North', 'South', 'East', 'West'], True))
    # the launch dialog, by real clicks: sales stacked by store, a holdback criterion
    r = await page.ev('''(async () => {
      SM.app.launch('tsforecast');
      await new Promise(r => setTimeout(r, 250));
      const dlg = [...document.querySelectorAll('.sm-launch-dialog')].pop();
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { const li = items.find(li => li.textContent === name); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === label);
      pick('sales'); role('Y, Time Series').click();
      pick('store'); role('Grouping').click();
      pick('month'); role('Time').click();
      const lab = (text) => [...dlg.querySelectorAll('.sm-launch-opts label')].find(l => l.textContent.startsWith(text));
      lab('Forecast Periods').querySelector('input').value = '6';
      const sel = lab('Model Selection').querySelector('select'); sel.value = 'rmse'; sel.dispatchEvent(new Event('change', { bubbles: true }));
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
      const rep = __ts.rep();
      await __ts.done(rep);
      return { roles, title: rep.title, outlines: __ts.outlines(rep), ...__ts.problems(rep) };
    })()''', timeout=900)
    check("Time Series Forecast: JMP's roles", r['roles'], ['Y, Time Series', 'Grouping', 'Time', 'By'])
    check('... the report, without errors', (r['title'], r['errors']), ('Time Series Forecast', []))
    check('... Model Summary, Forecasts, and the first series\' report with its holdback forecasts', [o for o in r['outlines'] if o in ('Forecasts', 'Series: North', 'Model Selection', 'Forecast on Holdback')],
          ['Forecasts', 'Series: North', 'Model Selection', 'Forecast on Holdback'])
    summ = await page.ev(table_under_js('Model Summary'))
    check('Model Summary: a row per store, named by the value labels', [row[0] for row in summ[1:]], ['North', 'South', 'East', 'West'])
    check('... the holdback criterion\'s column', summ[0][:4], ['Series', 'N', 'Model', 'Holdback RMSE'])
    # the chosen model's holdback RMSE against the page's own arithmetic: its forecasts of North's last 6 months
    js = await page.ev('''(async () => { const rep = __ts.rep(); const p = rep.plots.find(p => p.opts.title === 'North forecast on the holdback'); await p.draw();
      const fc = p.traces.find(t => / forecast$/.test(t.name)).y.slice(1); const t = rep.table; const st = t.col('store').values, v = t.col('sales').values;
      const north = v.filter((x, i) => st[i] === 1); const act = north.slice(north.length - 6);
      const rmse = Math.sqrt(act.reduce((s, a, i) => s + (a - fc[i]) ** 2, 0) / 6); return SM.util.fmt(rmse); })()''')
    check('... North\'s Holdback RMSE is that of its chosen model\'s forecasts of the last 6 months, computed in the page', summ[1][3], js)
    fcs = await page.ev(table_under_js('Forecasts'))
    check('Forecasts: 6 months of each store, from 2025-01-01', (len(fcs) - 1, fcs[1][:2], fcs[6][:2], fcs[7][:2]), (24, ['North', '2025-01-01'], ['North', '2025-06-01'], ['South', '2025-01-01']))
    r = await page.ev('''(async () => { const rep = __ts.rep(); const p = rep.plots.find(p => p.opts.title === 'North forecast'); await p.draw();
      return p.traces.find(t => / forecast$/.test(t.name)).y.slice(1).map(v => SM.util.fmt(v)); })()''')
    check('... North\'s forecasts are those of its report (the chosen model on all 72 months)', [row[2] for row in fcs[1:7]], r)
    # a click on a row opens that series' report
    await act(page, '''const rep = __ts.rep(); const h = __ts.head(rep, 'Model Summary'); const tr = [...h.parentElement.querySelectorAll('table.sm-rt tbody tr')].find(tr => tr.children[0].textContent === 'East');
      tr.click(); return true;''')
    outl = await page.ev('__ts.outlines(__ts.rep())')
    check('a click on East\'s row opens its report too', ('Series: North' in outl, 'Series: East' in outl), (True, True))
    # Save Results
    r = await page.ev('''(async () => { const before = SM.app.tables.length; await __ts.menu(__ts.rep(), null, ['Save Results']); await new Promise(r => setTimeout(r, 200));
      const t = SM.app.tables[SM.app.tables.length - 1]; const set = t.col('Set').values, ser = t.col('Series').values;
      const out = { added: SM.app.tables.length - before, rows: t.nrows, cols: t.columns.map(c => c.name), hist: set.filter(x => x === 'History').length, fc: set.filter(x => x === 'Forecast').length,
        series: [...new Set(ser)], dated: t.col('month').format && t.col('month').format.kind };
      SM.app.closeTable(t); document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach(b => b.click()); SM.app.showTab(SM.app.tabOf(__ts.rep())); return out; })()''')
    check('Save Results: every store\'s values and one-step-ahead predictions, then its forecasts, stacked with a Set column', (r['added'], r['rows'], r['hist'], r['fc'], r['series'], r['dated']),
          (1, 312, 288, 24, ['North', 'South', 'East', 'West'], 'date'))
    check('... its columns', r['cols'], ['Series', 'month', 'Actual', 'Predicted', 'Lower CL (0.95)', 'Upper CL (0.95)', 'Set'])
    # the red triangle: BIC instead
    await act(page, '''await __ts.menu(__ts.rep(), null, ['Model Selection', 'BIC']); return true;''', timeout=900)
    summ = await page.ev(table_under_js('Model Summary'))
    check('Model Selection > BIC: the criterion column, and no holdback report', (summ[0][3], 'Forecast on Holdback' in await page.ev('__ts.outlines(__ts.rep())')), ('BIC', False))
    sel = await page.ev(table_under_js('Model Selection'))
    bics = [num(row[5]) for row in sel[1:] if row[5] not in ('.', '')]
    check('... North\'s Model Selection: best BIC first, marked as chosen', (bics == sorted(bics), sel[1][-1]), (True, '★ chosen'))
    # a saved project keeps the options and the series opened
    r = await page.ev('''(async () => {
      const rep = __ts.rep(); const t = rep.table; const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      const n = SM.app.reports.length; SM.app.loadProject(JSON.parse(JSON.stringify(j))); const r2 = SM.app.reports[n]; await __ts.done(r2);
      const out = { outlines: __ts.outlines(r2).filter(o => o.startsWith('Series: ')), head: [...r2.body.querySelectorAll('table.sm-rt')][0].querySelector('thead th:nth-child(4)').textContent, ...__ts.problems(r2) };
      const t2 = r2.table; SM.app.closeReport(r2); SM.app.closeTable(t2); document.querySelectorAll('.sm-dialog .sm-btn.primary').forEach(b => b.click());
      SM.app.showTab(SM.app.tabOf(rep)); return out; })()''', timeout=900)
    check('a reopened project: BIC, and the North and East reports', (r['outlines'], r['head'], r['errors']), (['Series: North', 'Series: East'], 'BIC', []))
    # the graphs of the series' reports against their code
    await page.ev('window.__tsc = __ts.rep()')
    await check_report_graphs(page, 'window.__tsc', 'window.__tsc.table', 'charts: Time Series Forecast')
    ns_code = await page.ev('''(() => { const h = __ts.head(__ts.rep(), 'Model Summary'); return h.parentElement.querySelector('details.sm-code code').textContent; })()''')
    out = await page.ev(f'__gr.run({json.dumps(ns_code)}, __ts.rep().table)', timeout=900)
    txt = json.dumps(out)
    check('the Model Summary code runs in the page and names every store\'s chosen model', ('"type": "error"' not in txt, all(row[2] in txt for row in summ[1:])), (True, True))
    # By, the dark theme and phone width
    r = await page.ev('''(async () => { const t = SM.app.tables.find(x => x.name === 'Store sales');
      const rep = SM.app.openReport(SM.platforms.get('tsforecast'), { roles: { y: [t.col('sales').id], time: [t.col('month').id], by: [t.col('store').id] }, options: { forecast: 3, models: 'additive' } }, t);
      await __ts.done(rep);
      const out = { tops: [...rep.body.querySelectorAll('.sm-ob.level-0 > .sm-ob-head h2')].map(h => h.textContent), n: [...rep.body.querySelectorAll('.sm-ob-head')].filter(h => h.textContent.trim() === 'Model Summary').length, ...__ts.problems(rep),
        code: rep.pythonScript().includes('df = df[df["store"] == 1') };
      SM.app.closeReport(rep); return out; })()''', timeout=900)
    check('By: a report per store, each with its Model Summary, the code keeping the group', (len(r['tops']), r['n'] >= 4, r['errors'], r['code']), (4, True, [], True))
    await page.ev('SM.app.showTab(SM.app.tabOf(__ts.rep()))')
    await page.ev('''(async () => { const rep = __ts.rep(); const d = __ts.done(rep); KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark'); await d; })()''', timeout=900)
    await asyncio.sleep(1.0)
    await shot(page, 'ts-22-dark-forecast.png', 'Model Summary')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await page.ev('''(async () => { const rep = __ts.rep(); const d = __ts.done(rep); rep.run(); await d; })()''', timeout=900)
    await asyncio.sleep(1.2)
    check('no horizontal page scroll at phone width (Time Series Forecast)', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, 'ts-23-phone-forecast.png', 'Series: North')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    tsf_id = await page.ev('SM.app.reports.indexOf(__ts.rep())')

    # ---- help for every input: the launch dialog's (i), every dialog of the red triangles, the report's controls
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await page.ev(HELP_JS)
    check('help: back on the Monthly sales table', await page.ev('__hp.showTable("Monthly sales")'), True)
    await check_launch_help(page, 'timeseries', what='timeseries: the launch dialog')
    await check_launch_help(page, 'tsforecast', what='tsforecast: the launch dialog')
    tsr = f'SM.app.reports[{tsf_id}]'
    await check_controls_help(page, tsr, 'Model Summary', ['Model Summary', 'Forecasts', 'Series: …', 'Save Results'], 'tsforecast: Model Summary')
    info = await page.ev(f'__hp.outline({tsr}, "Series: North")')
    check('tsforecast: a series\' report has its (i)', (info or {}).get('title'), 'A series\' report')
    for path, fields in ((['Set Forecast Periods…'], ['Forecast Periods']), (['Set Forecast Interval Level…'], ['Level'])):
        await check_form_help(page, f"await __hp.menu({tsr}, null, {json.dumps(path)})", fields, f'tsforecast: {path[0]}')
    models = [{'kind': 'arima', 'p': 1, 'd': 0, 'q': 0, 'P': 0, 'D': 0, 'Q': 0, 's': 0, 'intercept': True, 'constrain': True, 'level': 0.95, 'id': 1},
              {'kind': 'ets', 'error': 'add', 'trend': 'N', 'seasonal': 'N', 's': 0, 'level': 0.95, 'group': 1, 'id': 2},
              {'kind': 'ets', 'error': 'add', 'trend': 'A', 'seasonal': 'N', 's': 0, 'level': 0.95, 'group': 1, 'id': 3}]
    await page.ev(f'''(async () => {{ const t = SM.app.tables.find((x) => x.name === 'Monthly sales'); const id = (n) => t.col(n).id;
      const rep = SM.app.openReport(SM.platforms.get('timeseries'), {{ roles: {{ y: [id('sales')], time: [id('month')], inputs: ['promotion', 'temperature'].map(id) }}, options: {{ lagPlot: 1, models: {json.dumps(models)} }} }}, t);
      await new Promise((r) => rep.on('done', r)); SM.app.showTab(SM.app.tabOf(rep)); return rep.title; }})()''', timeout=600)
    rep = 'SM.app.reports[SM.app.reports.length - 1]'
    orders = ['p, Autoregressive Order', 'd, Differencing Order', 'q, Moving Average Order']
    seas = ['P, Seasonal Autoregressive Order', 'D, Seasonal Differencing Order', 'Q, Seasonal Moving Average Order', 'Observations per Period']
    fit = ['Prediction Interval', 'Intercept', 'Constrain fit']
    forms = [
        (None, ['Difference…'], ['Nonseasonal Differencing Order, d', 'Seasonal Differencing Order, D', 'Observations per Period, s']),
        (None, ['Decomposition', 'Remove Cycle…'], ['Units per Cycle', 'Subtract a constant']),
        (None, ['Decomposition', 'Seasonal Decomposition…'], ['Period', 'Decomposition Type']),
        (None, ['Decomposition', 'STL Decomposition…'], ['Period', 'Robust']),
        (None, ['Filters', 'Hodrick-Prescott Filter…'], ['λ, Smoothing']),
        (None, ['Filters', 'Baxter-King Filter…'], ['Shortest period in the band', 'Longest period in the band', 'K, Lead-lag length']),
        (None, ['Filters', 'Christiano-Fitzgerald Filter…'], ['Shortest period in the band', 'Longest period in the band', 'Remove the drift first']),
        (None, ['ARIMA…'], orders + fit),
        (None, ['Seasonal ARIMA…'], orders + seas + fit),
        (None, ['ARIMA Model Group…'], ['p, d, q, P, D, Q (ranges)', 'Observations per Period'] + fit),
        (None, ['Transfer Function…'], ['Noise p, d, q, P, D, Q', 'Observations per Period', 'Input (each column)', 'Input lag (dead time)', 'Numerator order (more lags)'] + fit),
        (None, ['Smoothing Models', 'Simple Exponential Smoothing…'], ['Prediction Interval', 'Constraints', 'Box-Cox transformation', 'λ, Box-Cox']),
        (None, ['Smoothing Models', 'Winters Method…'], ['Prediction Interval', 'Observations per Period', 'Seasonality', 'Constraints', 'Box-Cox transformation', 'λ, Box-Cox']),
        (None, ['Smoothing Models', 'Simple Moving Average…'], ['Smoothing window width', 'Centering', 'Prediction Interval']),
        (None, ['State Space Smoothing Models…'], ['Error: Additive (A)', 'Error: Multiplicative (M)', 'Trend: None (N)', 'Trend: Additive (A)', 'Trend: Additive damped (Ad)', 'Trend: Multiplicative (M)',
                                                   'Trend: Multiplicative damped (Md)', 'Seasonal: None (N)', 'Seasonal: Additive (A)', 'Seasonal: Multiplicative (M)', 'Period',
                                                   'Leave out additive errors with multiplicative seasonality', 'Prediction Interval']),
        (None, ['Benchmark Models', 'All Three…'], ['Prediction Interval', 'Observations per Period']),
        (None, ['Benchmark Models', 'Naive…'], ['Prediction Interval']),
        (None, ['Averaged Forecast…'], ['Each model', 'Prediction Interval']),
        (None, ['Rolling-Origin Cross-Validation…'], ['Number of origins', 'Horizon', 'Step between origins']),
        (None, ['Structural Model…'], ['Level and Trend', 'Seasonal', 'Seasonal Period', 'Harmonics', 'Stochastic seasonal', 'Cycle', 'Stochastic cycle', 'Damped cycle', 'Cycle period from',
                                       'Cycle period to', 'Autoregressive Order', 'Input (each column)', 'Exact diffuse initialization', 'Prediction Interval']),
        (None, ['Regime Switching…'], ['Number of Regimes', 'Autoregressive Order', 'Mean', 'Switching mean (and trend)', 'Switching variance', 'Switching AR coefficients', 'Random Starts']),
        (None, ['Theta Model…'], ['θ, Theta', 'Deseasonalize', 'Seasonal Period', 'Test for seasonality first', 'Deseasonalizing', 'Estimate by maximum likelihood', 'Prediction Interval']),
        (None, ['ARDL…'], ['Input (each column)', 'Largest lag of the series, p', 'Largest lag of the inputs, q', 'Choose the orders by', 'Search every subset of lags', 'Fixed orders',
                           'Deterministic Terms', 'Bounds Test Case', 'Causal', 'Seasonal dummies', 'Prediction Interval']),
        (None, ['Number of Forecast Periods…'], ['Forecast periods for every model']),
        (None, ['Maximum Iterations…'], ['Maximum iterations']),
        ('Stationarity Tests', ['Zivot-Andrews Options…'], ['Trimming at each end', 'Largest lag', 'Lags chosen by']),
    ]
    for title, path, fields in forms:
        await check_form_help(page, f"await __hp.menu({rep}, {json.dumps(title)}, {json.dumps(path)})", fields, f'timeseries: {" > ".join(path)}')
    await check_controls_help(page, rep, 'Lag Plot (lag 1)', ['Lag p', '− and +', 'A point'], 'timeseries: Lag Plot')
    await check_controls_help(page, rep, 'Model Comparison', ['Report', 'Graph', 'A column heading', 'Right click the table'], 'timeseries: Model Comparison')
    await check_controls_help(page, rep, 'State Space Smoothing Model Selection 1', ['A line of the selection table'], 'timeseries: State Space Smoothing Model Selection')
    hbr = f'SM.app.reports[{hb_id}]'
    await check_controls_help(page, hbr, 'Rolling-Origin Cross-Validation', ['Means over the Origins', 'RMSE by origin', 'Per Origin'], 'timeseries: Rolling-Origin Cross-Validation')
    await check_controls_help(page, hbr, 'Holdback Statistics', ['The graphs', 'Holdback Statistics', 'Save Columns', 'Refit on All Rows'], 'timeseries: Holdback Statistics')
    info = await page.ev(f'__hp.outline({hbr}, "Runs Test")')
    check('timeseries: Runs Test: its (i)', (info or {}).get('title'), 'Runs Test')
    r = await page.ev(f'''__hp.form(async () => {{ await __hp.menu({hbr}, null, ['Smoothing Models', 'Linear (Holt) Exponential Smoothing…']); await __hp.sleep(150);
      const d = [...document.querySelectorAll('.sm-dialog')].pop(); d.querySelector('select').value = 'custom';
      [...d.querySelectorAll('.sm-form label')].find(l => l.textContent === 'Constraints') && (document.getElementById([...d.querySelectorAll('.sm-form label')].find(l => l.textContent === 'Constraints').htmlFor).value = 'custom');
      [...d.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Estimate').click(); }})''', timeout=300)
    got = help_section((r or {}).get('info'), 'Fields') or {}
    check('timeseries: Custom Constraints: its (i) explains each weight\'s choice, the fixed value and the bounds', list(got), ['Each weight', 'Fixed value', 'Lower and upper bound'])
    await page.ev('document.querySelectorAll(".sm-dialog .sm-dialog-x").forEach((x) => x.click())')

    # ---- the graphs' matplotlib code, every graph of every kind
    await chart_code(page)

    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
