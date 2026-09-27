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
import os
import sys

from cdp import BASE, Checks, open_page, table_under_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()

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
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
