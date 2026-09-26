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

Start a server on the repository root and headless Chrome on SMUI_HTTP_PORT
and SMUI_CDP_PORT (see README.md), then

    python3 resources/tests/smui/test-ui-timeseries.py

SMUI_SHOTS=<folder> saves screenshots. Exit status 0 when every check passes.
"""
import asyncio
import json
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()

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


async def shot(page, name, title=None):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    if title:   # scroll the report down to the outline (only vertically: the report body also scrolls sideways)
        await page.ev(f'''(() => {{ const rep = SM.app.reports.find(r => r.platform.id === 'timeseries'); const h = __ts.head(rep, {json.dumps(title)});
          if (h) rep.body.scrollTop = h.getBoundingClientRect().top - rep.body.getBoundingClientRect().top + rep.body.scrollTop - 8; }})()''')
    await asyncio.sleep(1.0)
    await page.shot(os.path.join(SHOTS, name))


async def act(page, js, timeout=600):
    """Run an action that redraws the last report and wait until it is done."""
    return await page.ev(f'''(async () => {{ const rep = __ts.rep(); const d = __ts.done(rep); const out = await (async () => {{ {js} }})(); await d; return out; }})()''', timeout=timeout)


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
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
