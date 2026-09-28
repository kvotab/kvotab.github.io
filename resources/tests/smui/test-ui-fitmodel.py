#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Fit Model.

The launch dialog builds a model (Full Factorial, Add, Cross, Nest, the
Random Effect attribute), picks the personality from the Y, recalls the
last model; the Standard Least Squares report shows JMP's outlines, its
numbers agree with a regression computed in the page, its least squares
means with the cell means of a balanced design, its graphs are linked to
the table; the Effect Summary removes an effect and Undo brings it back;
the red triangle adds the Prediction Profiler, whose drag and value boxes
recompute the prediction from the remembered fit; Save Columns adds the
predictions; By, exclusions and Redo work; every other personality opens
without an error; a saved project reopens with its model; the report reads
in the dark theme and at phone width.

Beyond JMP: the Generalized Estimating Equations personality on the simulated
longitudinal example (the dialog's roles and options, the report's outlines,
its numbers against each other, linking, the red triangle's working
correlations, covariances, Odds Ratios and Compare Working Correlations, Save
Columns against the profiler, By, a nested fit, a project), Robust Standard
Errors (HC0 against the page's own sandwich, Cluster through its dialog, the
GLM's sandwich) and Regression Diagnostics (every test, Jarque-Bera against the
page's own, a test's controls, the Influence Plot's selection, the Component +
Residual plot); on the simulated schooling example Instrumental Variables (the
dialog's Endogenous and Instruments roles, the report, a just-identified 2SLS
and its first-stage F against the page's own, linking, Robust Standard Errors,
OLS beside 2SLS, Save Columns, a weak instrument, By, the profiler, a project),
Quantile Regression (the dialog's quantile, Model Launch, Powell's sandwich,
the saved quantile against the share of rows below it, the process and its
table, the quantile lines, By) and Recursive and Rolling Regression (the last
recursive estimates against the Parameter Estimates, the CUSUM's crossing of
the example's break, a CUSUM point and a rolling window selecting their rows,
Order by, Rolling Window), in both themes and at phone width.

Generalized Regression (JMP Pro's): the launch dialog's Validation role (its
Validation Column; another personality says it ignores it), the Model
Launch's Estimation and Validation Methods, the Model Summary's sets against
the table's Validation column, KFold's folds and the seed kept by Redo, the
Solution Path's red line dragged and clicked and Reset to the Best Model,
Holdback's share and Save Columns > Validation Column, a Random Seed of one's
own, Forward Selection against the page's own least squares, the binomial
profiler against Save Columns, Diagnostic Plots by set and their linking, By,
a project, that it needs no scikit-learn, both themes and phone width.

MANOVA's Repeated Measures: Choose Response and its dialog (Y Name, Univariate
Tests Also, Cancel), JMP's Between and Within Subjects outlines and rows against
the backend, the between test against a one-way ANOVA of the subjects' sums and
the univariate within test against a subjects-by-levels ANOVA computed in the
page, the Sphericity Test, the red triangle, a project, By, Bootstrap on
resampled subjects, both themes and phone width; the Effect Tests' optional
Partial η² and Partial ω² columns from the right-click menu, against the tables'
own sums of squares, and Bootstrap of a hidden column.

Start a server on the repository root and headless Chrome on
SMUI_HTTP_PORT and SMUI_CDP_PORT (the recipe is in README.md), then

    python3 resources/tests/smui/test-ui-fitmodel.py

With SMUI_SHOTS=<folder> it saves screenshots.
"""
import asyncio
import json
import math
import os
import sys

from cdp import BASE, Checks, open_page, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


# Open a Fit Model report from JavaScript: y, effects [{names, nest, random}], options, other roles.
OPEN = '''
(async (y, effects, options, extra) => {
  const t = SM.app.current; const P = SM.platforms.get('fitmodel');
  const col = (n) => { const c = t.col(n); if (!c) throw new Error('no column ' + n); return c; };
  const eff = effects.map(e => ({ cols: e.names.map(n => col(n).id), names: e.names, nest: (e.nest || []).map(n => col(n).id), nestNames: e.nest || [], random: !!e.random }));
  const roles = { y: (Array.isArray(y) ? y : [y]).map(n => col(n).id) };
  for (const [k, v] of Object.entries(extra || {})) roles[k] = v.map(n => col(n).id);
  const rep = SM.app.openReport(P, { roles, options: options || {}, effects: eff }, t);
  await new Promise(res => rep.on('done', res));
  return __fm.state(rep);
})
'''

HELPERS = '''
window.__fm = {
  rep: () => SM.app.reports[SM.app.reports.length - 1],
  state: (rep) => ({ title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
    errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 600)), warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)), plots: rep.plots.length }),
  outline: (title, rep) => { const r = rep || __fm.rep(); const h = [...r.body.querySelectorAll('.sm-ob-head')].find(x => x.querySelector('h2, h3, h4').textContent === title); return h ? h.parentElement : null; },
  table: (title, n = 0, rep) => { const ob = __fm.outline(title, rep); if (!ob) return null; const t = ob.querySelector(':scope > .sm-ob-body').querySelectorAll('table.sm-rt, table.sm-kv')[n]; return t ? [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent.trim())) : null; },
  kv: (title) => Object.fromEntries((__fm.table(title) || []).map(r => [r[0], r[r.length - 1]])),
  dlg: () => document.querySelector('.sm-launch-dialog'),
  pick: (...names) => { const d = __fm.dlg(); const items = [...d.querySelectorAll('.sm-pick-list li')];
    names.forEach((n, i) => { const li = items.find(x => x.textContent === n); if (!li) throw new Error('no column in the dialog ' + n); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, metaKey: i > 0 })); }); },
  btn: (label, root) => { const b = [...(root || __fm.dlg()).querySelectorAll('button')].find(x => x.textContent === label); if (!b) throw new Error('no button ' + label); b.click(); },
  role: (label) => { const b = [...__fm.dlg().querySelectorAll('.sm-role .sm-btn')].find(x => x.textContent === label); b.click(); },
  effects: () => [...__fm.dlg().querySelectorAll('.sm-fm-effects li')].map(li => li.textContent),
  selEff: (...idx) => { const lis = [...__fm.dlg().querySelectorAll('.sm-fm-effects li')]; idx.forEach((i, k) => lis[i].dispatchEvent(new MouseEvent('click', { bubbles: true, metaKey: k > 0 }))); },
  menuItem: async (...path) => {
    for (let i = 0; i < path.length; i++) {
      const menus = [...document.querySelectorAll('.sm-menu')];
      const m = menus[menus.length - 1];
      const b = m && [...m.querySelectorAll('button')].find(x => x.querySelector('.sm-label').textContent === path[i]);
      if (!b) throw new Error('no menu item ' + path[i]);
      if (i < path.length - 1) b.dispatchEvent(new MouseEvent('mouseenter')); else b.click();
      await __fm.tick();
    }
  },
  topMenu: async (...path) => { __fm.rep().body.querySelector('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu').click(); await __fm.tick(); await __fm.menuItem(...path); },
  pers: () => __fm.dlg().querySelector('select[aria-label="Personality"]').value,
  tick: () => new Promise(r => setTimeout(r, 40)),
  done: (rep) => new Promise(res => rep.on('done', res)),
  // A report opened by a menu item may be done before a listener is on: wait until it has settled.
  settled: async (rep) => { for (let i = 0; i < 1200 && (rep.body.classList.contains('is-running') || !rep.content.querySelector('.sm-ob')); i++) await new Promise(r => setTimeout(r, 25)); },
  // Until no report has run for 300 ms (a theme change redraws every report, a little later).
  idle: async () => { let calm = 0; for (let i = 0; i < 4800 && calm < 12; i++) { await new Promise(r => setTimeout(r, 25)); calm = SM.app.reports.some(x => x.body.classList.contains('is-running')) ? 0 : calm + 1; } },
  num: (s) => Number(String(s).replace('−', '-').replace('<', '').replace('*', '')),
};
'''


def open_js(y, effects, options=None, extra=None):
    return f'({OPEN})({json.dumps(y)}, {json.dumps(effects)}, {json.dumps(options or {})}, {json.dumps(extra or {})})'


def E(*effects):
    return [{'names': e} if isinstance(e, list) else e for e in effects]


async def main():
    page = await open_page(f'{BASE}/smui.html?example=plants')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "fit_model").map(f => f.error)')
    check('fit_model imports in Pyodide', failed, [])
    await page.ev(HELPERS)
    menu = await page.ev('SM.app.menuItems("Analyze").map(i => i.label)')
    check('Analyze lists Fit Model', 'Fit Model…' in menu, True)
    names = await page.ev('SM.engine.names.filter(n => n.startsWith("fitmodel.")).length')
    check('the engine has the fitmodel functions', names >= 14, True)

    # ---- the launch dialog: Full Factorial, Add, Cross, Nest, Random Effect, No Intercept, OK
    r = await page.ev('''(async () => {
      SM.app.launch('fitmodel'); await new Promise(r => setTimeout(r, 300));
      const out = {};
      __fm.pick('yield (g)'); __fm.role('Y'); await __fm.tick();
      out.pers = __fm.pers();
      __fm.pick('fertilizer', 'water'); __fm.btn('Macros ▾'); await __fm.tick(); await __fm.menuItem('Full Factorial');
      out.ff = __fm.effects();
      __fm.pick('light (h)'); __fm.btn('Add'); __fm.selEff(3); __fm.pick('light (h)'); __fm.btn('Cross');
      out.cross = __fm.effects();
      __fm.pick('plot'); __fm.btn('Add'); __fm.selEff(5); __fm.pick('fertilizer'); __fm.btn('Nest');
      out.nest = __fm.effects();
      __fm.selEff(5); __fm.btn('Attributes ▾'); await __fm.tick(); await __fm.menuItem('Random Effect');
      out.random = __fm.effects();
      __fm.btn('Remove');   // the effect is still selected
      out.removed = __fm.effects();
      const off = [...__fm.dlg().querySelectorAll('.sm-role')].find(x => x.querySelector('.sm-btn').textContent === 'Offset');
      out.offset = off.hidden;
      const ps = __fm.dlg().querySelector('select[aria-label="Personality"]');
      ps.value = 'glm'; ps.dispatchEvent(new Event('change'));
      out.offsetGlm = off.hidden;
      ps.value = 'standard'; ps.dispatchEvent(new Event('change'));
      __fm.btn('OK');
      const rep = __fm.rep(); await __fm.done(rep);
      out.state = __fm.state(rep);
      out.effectsSpec = rep.spec.effects.map(e => e.names.join('*'));
      return out;
    })()''')
    check('Y continuous: Standard Least Squares', r['pers'], 'standard')
    check('Full Factorial of two columns', r['ff'], ['fertilizer', 'water', 'fertilizer*water'])
    check('Cross a column with an effect: its square', r['cross'][-2:], ['light (h)', 'light (h)*light (h)'])
    check('Nest: plot within fertilizer', r['nest'][-1], 'plot[fertilizer]')
    check('Attributes > Random Effect', r['random'][-1], 'plot[fertilizer]&Random')
    check('Remove takes the selected effect out', r['removed'], ['fertilizer', 'water', 'fertilizer*water', 'light (h)', 'light (h)*light (h)'])
    check('Offset shows for the generalized linear model only', (r['offset'], r['offsetGlm']), (True, False))
    check('the report is JMP\'s Response outline', r['state']['title'], 'Response yield (g)')
    for o in ['Effect Summary', 'Actual by Predicted Plot', 'Summary of Fit', 'Analysis of Variance', 'Parameter Estimates', 'Effect Tests', 'Effect Details', 'Residual by Predicted Plot']:
        check(f'outline {o}', o in r['state']['outlines'], True)
    check('no errors in the report', r['state']['errors'], [])
    check('the spec keeps the model', r['effectsSpec'], ['fertilizer', 'water', 'fertilizer*water', 'light (h)', 'light (h)*light (h)'])
    await asyncio.sleep(1)
    await shot(page, 'fm-01-sls.png')

    # ---- Recall and the personality of a nominal Y
    r = await page.ev('''(async () => {
      SM.app.launch('fitmodel'); await new Promise(r => setTimeout(r, 300));
      __fm.btn('Recall'); await __fm.tick();
      const out = { recalled: __fm.effects(), y: [...__fm.dlg().querySelectorAll('.sm-role-list')][0].textContent };
      __fm.btn('Cancel');
      SM.app.launch('fitmodel'); await new Promise(r => setTimeout(r, 300));
      __fm.pick('fertilizer'); __fm.role('Y'); await __fm.tick();
      out.pers = __fm.pers();
      out.target = !__fm.dlg().querySelector('select[aria-label="Target Level"]').closest('label').hidden;
      __fm.pick('water'); __fm.role('Y'); await __fm.tick();
      __fm.btn('Cancel');
      return out; })()''')
    check('Recall restores the effects', r['recalled'], ['fertilizer', 'water', 'fertilizer*water', 'light (h)', 'light (h)*light (h)'])
    check('Recall restores the Y', r['y'], 'yield (g)')
    check('a nominal Y: Nominal Logistic, with a Target Level', (r['pers'], r['target']), ('nominal', True))

    # ---- the numbers: a simple regression against the page's own least squares
    r = await page.ev(open_js('yield (g)', E(['light (h)'])))
    check('simple regression opens', r['errors'], [])
    js = await page.ev('''(() => { const t = SM.app.current; const x = t.col('light (h)').values, y = t.col('yield (g)').values; const n = x.length;
      const mx = x.reduce((a, b) => a + b) / n, my = y.reduce((a, b) => a + b) / n;
      let sxy = 0, sxx = 0, syy = 0; for (let i = 0; i < n; i++) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) ** 2; syy += (y[i] - my) ** 2; }
      const b = sxy / sxx, a = my - b * mx, sse = syy - b * sxy, rmse = Math.sqrt(sse / (n - 2));
      return { a, b, rsq: 1 - sse / syy, rmse, f: (syy - sse) / (sse / (n - 2)) }; })()''')
    sof = await page.ev('__fm.kv("Summary of Fit")')
    est = await page.ev('__fm.table("Parameter Estimates")')
    an = await page.ev('__fm.table("Analysis of Variance")')
    num = lambda s: float(str(s).replace('−', '-'))
    check.near('RSquare = the page\'s least squares', num(sof['RSquare']), js['rsq'], 1e-6)
    check.near('Root Mean Square Error', num(sof['Root Mean Square Error']), js['rmse'], 1e-6)
    check.near('slope', num(est[2][1]), js['b'], 1e-6)
    check.near('intercept', num(est[1][1]), js['a'], 1e-6)
    check.near('F Ratio', num(an[1][4]), js['f'], 1e-6)
    rp = await page.ev('''(() => { const rep = __fm.rep(); const p = rep.plots.find(p => p.opts.title === 'yield (g) regression plot'); if (!p) return null;
      const fit = p.traces.find(t => t.name === 'Fit'); return { x0: fit.x[0], y0: fit.y[0], x1: fit.x[fit.x.length - 1], y1: fit.y[fit.y.length - 1] }; })()''')
    check('one continuous regressor: a Regression Plot', rp is not None, True)
    if rp:
        check.near('its line is the page\'s least squares line (left end)', rp['y0'], js['a'] + js['b'] * rp['x0'], 1e-6)
        check.near('and at the right end', rp['y1'], js['a'] + js['b'] * rp['x1'], 1e-6)
    lev = await page.ev('''(() => { const rep = __fm.rep(); const p = rep.plots.find(p => p.opts.title === 'light (h) leverage plot'); return p ? p.traces[0].x.slice(0, 3) : null; })()''')
    xs = await page.ev("SM.app.current.col('light (h)').values.slice(0, 3)")
    check('the leverage plot of a regressor is in its units (here its own values)', lev is not None and max(abs(a - b) for a, b in zip(lev, xs)) < 1e-9, True)

    # ---- least squares means of a balanced design are the cell means
    r = await page.ev(open_js('yield (g)', E(['fertilizer'], ['water'], ['fertilizer', 'water'])))
    ls = await page.ev('__fm.table("fertilizer")')
    means = await page.ev('''(() => { const t = SM.app.current; const f = t.col('fertilizer').values, y = t.col('yield (g)').values; const out = {};
      for (const lv of ['A', 'B', 'C']) { const v = y.filter((_, i) => f[i] === lv); out[lv] = v.reduce((a, b) => a + b) / v.length; } return out; })()''')
    for row in ls[1:]:
        check.near(f'LS mean {row[0]} = the mean of its rows (balanced)', num(row[1]), means[row[0]], 1e-6)

    # ---- linking: a click on a point selects its row; a table selection shows in the plots
    r = await page.ev('''(async () => {
      const rep = __fm.rep(); const t = rep.table;
      const p = rep.plots.find(p => p.opts.title === 'yield (g) actual by predicted');
      p._click({ points: [{ curveNumber: 0, pointNumber: 7 }], event: {} });
      const sel = t.selectedRows();
      t.select([3, 4]); await new Promise(r => setTimeout(r, 150));
      const lp = rep.plots.find(q => q.opts.title === 'fertilizer leverage plot');
      const sp = lp && lp.drawn ? lp.box.data[0].selectedpoints : null;
      t.select([]);
      return { sel, sp, want: p.rows[0][7] }; })()''')
    check('a click on a point selects its row', r['sel'], [r['want']])
    check('a table selection shows in a leverage plot', r['sp'] is None or sorted(r['sp']) == [3, 4], True)

    # ---- Effect Summary: Remove an effect, Undo
    r = await page.ev('''(async () => {
      const rep = __fm.rep(); const ob = __fm.outline('Effect Summary');
      const tr = [...ob.querySelectorAll('tbody tr')].find(x => x.firstChild.textContent === 'fertilizer*water');
      tr.click(); __fm.btn('Remove', ob); await __fm.done(rep);
      const after = rep.spec.effects.map(e => e.names.join('*'));
      __fm.btn('Undo', __fm.outline('Effect Summary')); await __fm.done(rep);
      return { after, undone: rep.spec.effects.map(e => e.names.join('*')), tests: __fm.table('Effect Tests').slice(1).map(r => r[0]) }; })()''')
    check('Remove refits without the effect', r['after'], ['fertilizer', 'water'])
    check('Undo brings it back', r['undone'], ['fertilizer', 'water', 'fertilizer*water'])

    # ---- the red triangle: Profiler, its drag and value boxes; Save Columns
    r = await page.ev(open_js('yield (g)', E(['fertilizer'], ['water'], ['light (h)'], ['fertilizer', 'water'])))
    r = await page.ev('''(async () => {
      const rep = __fm.rep();
      let d = __fm.done(rep); await __fm.topMenu('Factor Profiling', 'Profiler'); await d;
      const ob = __fm.outline('Prediction Profiler'); ob.scrollIntoView(); await new Promise(r => setTimeout(r, 1200));
      const val = () => ob.querySelector('.sm-prof-val').textContent;
      const t = rep.table; const row = 20;
      const set = async (sel, v) => { const was = val(); const i = ob.querySelector(sel); i.value = v; i.dispatchEvent(new Event('change')); for (let k = 0; k < 400 && val() === was; k++) await new Promise(r => setTimeout(r, 5)); };
      const t0 = performance.now();
      await set('input[aria-label="light (h) current value"]', String(t.col('light (h)').values[row]));
      const ms = performance.now() - t0;
      const fsel = ob.querySelector('select[aria-label="fertilizer current value"]'); fsel.value = String(['A', 'B', 'C'].indexOf(t.col('fertilizer').values[row])); fsel.dispatchEvent(new Event('change')); await new Promise(r => setTimeout(r, 300));
      const wsel = ob.querySelector('select[aria-label="water current value"]'); wsel.value = String(['low', 'high'].indexOf(t.col('water').values[row])); wsel.dispatchEvent(new Event('change')); await new Promise(r => setTimeout(r, 300));
      const pred = val();
      // the drag: the line of the first factor moved to its third level
      const gd = ob.querySelectorAll('.sm-plot')[0];
      const was = val(); gd.emit('plotly_relayout', { 'shapes[0].x0': 2.1, 'shapes[0].x1': 2.1 });
      for (let k = 0; k < 400 && val() === was; k++) await new Promise(r => setTimeout(r, 5));
      const dragged = ob.querySelector('select[aria-label="fertilizer current value"]').value;
      // Save Columns > Predicted Values
      await __fm.topMenu('Save Columns', 'Predicted Values'); await __fm.tick();
      const pc = t.col('Predicted yield (g)');
      const saved = pc ? pc.values[row] : null;
      const cur = rep.spec.options[Object.keys(rep.spec.options).find(k => k.endsWith('|prof:'))];
      d = __fm.done(rep); rep.run(); await d;
      const kept = __fm.outline('Prediction Profiler').querySelector('select[aria-label="fertilizer current value"]').value;
      if (pc) t.removeColumn(pc.id);
      return { pred, saved, ms, dragged, cur, kept }; })()''')
    check.near('the profiler at a row\'s values predicts its saved Predicted value', num(r['pred']), r['saved'], 1e-5)
    check('a profiler update answers quickly (< 400 ms)', r['ms'] < 400, True)
    print(f'      profiler update: {r["ms"]:.0f} ms')
    check('dragging the line of a categorical factor picks the level', r['dragged'], '2')
    check('Redo keeps the profiler\'s current values', (r['cur']['fertilizer'], r['kept']), ('C', '2'))
    await shot(page, 'fm-02-profiler.png')

    # ---- every red-triangle option at once: no errors
    r = await page.ev('''(async () => {
      const rep = __fm.rep(); const y = rep.table.col('yield (g)').id;
      for (const k of ['contour', 'interaction', 'boxcox', 'plotResidRow', 'plotStudent', 'plotResidQQ', 'press', 'dw', 'sequential', 'corr', 'expression', 'sortedEst', 'showCI', 'aicc', 'vif', 'lsmPlot:fertilizer', 'tukey:fertilizer*water', 'student:fertilizer', 'lsmPlot:fertilizer*water']) rep.spec.options[y + '|' + k] = true;
      rep.spec.options[y + '|contrast:fertilizer'] = [[1, -1, 0]];
      rep.run(); await __fm.done(rep);
      return __fm.state(rep); })()''')
    for o in ['Box-Cox Transformations', 'Interaction Plots', 'Contour Profiler', 'LSMeans Differences Tukey HSD', 'Connecting Letters Report', 'Contrast', 'Durbin-Watson', 'Press', 'Studentized Residuals', 'Correlation of Estimates', 'Sequential (Type 1) Tests', 'Prediction Expression', 'Sorted Parameter Estimates']:
        check(f'option outline {o}', o in r['outlines'], True)
    check('no errors with every option', r['errors'], [])
    ci = await page.ev('__fm.table("Parameter Estimates")[0]')
    check('Show All Confidence Intervals and VIF add their columns', ('Lower 95%' in ci, 'VIF' in ci), (True, True))

    # ---- several responses: Fit Group, one Response outline each; Box-Cox's Refit with Transform
    await page.ev(HELPERS)
    r = await page.ev(open_js(['yield (g)', 'light (h)'], E(['fertilizer'], ['water'])))
    check('two Y: Fit Group', r['title'], 'Fit Group')
    check('with a Response outline each', [o for o in r['outlines'] if o.startswith('Response')], ['Response yield (g)', 'Response light (h)'])
    check('no errors with two Y', r['errors'], [])
    r = await page.ev(open_js('yield (g)', E(['fertilizer'], ['light (h)']), {'personality': 'standard'}))
    r = await page.ev('''(async () => {
      const rep = __fm.rep(); let d = __fm.done(rep);
      await __fm.topMenu('Factor Profiling', 'Box Cox Y Transformation'); await d;
      const ob = __fm.outline('Box-Cox Transformations');
      const best = __fm.kv('Box-Cox Transformations')['Best λ'];
      const n = SM.app.reports.length;
      ob.querySelector('.sm-ob-menu').click(); await __fm.tick(); await __fm.menuItem('Refit with Transform');
      const made = SM.app.reports[n]; if (made) await __fm.settled(made);
      const col = made ? made.table.col(made.spec.roles.y[0]) : null;
      const out = { best, made: made ? made.title : null, col: col ? col.name : null, errors: made ? __fm.state(made).errors : null };
      if (col) { SM.app.closeReport(made); made.table.removeColumn(col.id); }
      return out; })()''')
    check('Box-Cox: Refit with Transform fits the transformed Y', (r['made'] or '').startswith('Response yield (g) Box-Cox('), True)
    check('the refit has no errors', r['errors'], [])

    # ---- By, exclusion and Redo
    r = await page.ev(open_js('yield (g)', E(['light (h)']), None, {'by': ['water']}))
    check('By: one report per level', [o for o in r['outlines'] if o.startswith('Response')], ['Response yield (g) water=low', 'Response yield (g) water=high'])
    check('no errors with By', r['errors'], [])
    r = await page.ev('''(async () => {
      const rep = __fm.rep(); const t = rep.table;
      t.setState([0, 1, 2, 3], 'excluded', true);
      const stale = !rep.staleEl.hidden;
      rep.run(); await __fm.done(rep);
      const n = __fm.kv('Summary of Fit')['Observations (or Sum Wgts)'];
      t.setState([0, 1, 2, 3], 'excluded', false);
      return { stale, n }; })()''')
    check('an exclusion makes the report stale', r['stale'], True)
    check('Redo fits the included rows (36 of the low group, less 4)', r['n'], '32')

    # ---- the other personalities
    await page.ev("SM.app.openExample('clinical')")
    await page.ev(HELPERS)
    runs = [
        ('Generalized Linear Model', 'adverse events', E(['dose (mg)'], ['sex'], ['age']), {'personality': 'glm', 'dist': 'poisson', 'link': 'log'},
         ['Whole Model Test', 'Goodness Of Fit Statistic', 'Effect Tests', 'Parameter Estimates', 'Studentized Deviance Residual by Predicted']),
        ('Nominal Logistic', 'response', E(['dose (mg)'], ['age'], ['sex']), {'personality': 'nominal'},
         ['Whole Model Test', 'Fit Details', 'Parameter Estimates', 'Effect Likelihood Ratio Tests']),
        ('Generalized Regression', 'months', E(['dose (mg)'], ['age'], ['sex'], ['treatment'], ['adverse events']), {'personality': 'genreg'},
         ['Model Launch', 'Lasso with AICc Validation', 'Solution Path']),
        ('Stepwise', 'months', E(['dose (mg)'], ['age'], ['sex'], ['treatment']), {'personality': 'stepwise'},
         ['Stepwise Regression Control', 'Current Estimates', 'Step History']),
    ]
    for label, y, eff, opts, want in runs:
        r = await page.ev(open_js(y, eff, opts))
        check(f'{label}: no errors', r['errors'], [])
        check(f'{label}: its outlines', [o for o in want if o in r['outlines']], want)
    # stepwise: Go, then Run Model
    r = await page.ev('''(async () => {
      const rep = __fm.rep(); const ctl = __fm.outline('Stepwise Regression Control');
      __fm.btn('Go', ctl); await __fm.done(rep);
      const hist = __fm.table('Step History');
      const entered = [...__fm.outline('Current Estimates').querySelectorAll('tbody tr')].filter(tr => tr.querySelector('input[aria-label^="Entered"]') && tr.querySelector('input[aria-label^="Entered"]').checked).map(tr => tr.children[2].textContent);
      const n = SM.app.reports.length;
      __fm.btn('Run Model', __fm.outline('Stepwise Regression Control'));
      const made = SM.app.reports[n]; if (made) await __fm.done(made);
      return { hist: hist ? hist.length - 1 : 0, entered, made: made ? made.title : null, madeEffects: made ? made.spec.effects.map(e => e.names.join('*')) : null, errors: made ? __fm.state(made).errors : null }; })()''')
    if isinstance(r, str):
        print(r)
    check('stepwise Go enters effects', r['hist'] > 0 and len(r['entered']) > 0, True)
    sw_entered = r['entered']
    check('Run Model fits the entered effects by least squares', (r['made'], r['madeEffects']), ('Response months', r['entered']))
    check('the model it made has no errors', r['errors'], [])
    # the Entered box of the stepwise report takes an effect in
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(x => x.title === 'Stepwise Fit for months');
      SM.app.showTab(SM.app.tabOf(rep)); await new Promise(r => setTimeout(r, 100));
      const box = [...__fm.outline('Current Estimates', rep).querySelectorAll('input[aria-label^="Entered"]')].find(i => !i.checked);
      const name = box.getAttribute('aria-label').replace('Entered ', '');
      const d = __fm.done(rep); box.click(); await d;
      const now = [...__fm.outline('Current Estimates', rep).querySelectorAll('tbody tr')].filter(tr => { const i = tr.querySelector('input[aria-label^="Entered"]'); return i && i.checked; }).map(tr => tr.children[2].textContent);
      const hist = __fm.table('Step History', 0, rep);
      return { name, now, last: hist[hist.length - 1].slice(1, 3) }; })()''')
    if isinstance(r, str):
        print(r)
    check('an Entered box enters the effect', r['name'] in r['now'], True)
    check('and the step history says so', r['last'], [r['name'], 'Entered'])
    # the logistic fit's misclassification rate against its saved probabilities
    r = await page.ev(open_js('response', E(['dose (mg)'], ['age']), {'personality': 'nominal'}))
    r = await page.ev('''(async () => {
      const rep = __fm.rep(); const t = rep.table;
      await __fm.topMenu('Save Probability Formula'); await __fm.tick();
      const pno = t.col('Prob[no]'), ml = t.col('Most Likely response'), y = t.col('response');
      let wrong = 0; for (let i = 0; i < t.nrows; i++) if (ml.values[i] !== y.values[i]) wrong++;
      const rate = wrong / t.nrows;
      const table = __fm.kv('Fit Details')['Misclassification Rate'];
      const sums = [...Array(t.nrows).keys()].every(i => Math.abs(pno.values[i] + t.col('Prob[yes]').values[i] - 1) < 1e-9);
      for (const n of ['Lin[no]', 'Prob[no]', 'Prob[yes]', 'Most Likely response']) { const c = t.col(n); if (c) t.removeColumn(c.id); }
      return { rate, table, sums }; })()''')
    check.near('Misclassification Rate = the share of rows whose Most Likely level is wrong', num(r['table']), r['rate'], 1e-9)
    check('the saved probabilities of the levels sum to one', r['sums'], True)
    await page.ev("SM.app.openExample('students')")
    await page.ev(HELPERS)
    runs = [
        ('Ordinal Logistic', 'age', E(['height (cm)'], ['sex']), {'personality': 'ordinal'}, ['Whole Model Test', 'Parameter Estimates', 'Effect Likelihood Ratio Tests']),
        ('Mixed Model', 'weight (kg)', E(['height (cm)'], {'names': ['sex'], 'random': True}), {'personality': 'mixed'}, ['Fit Statistics', 'Random Effects Covariance Parameter Estimates', 'Fixed Effects Parameter Estimates', 'Fixed Effects Tests']),
        ('MANOVA', ['height (cm)', 'weight (kg)'], E(['sex'], ['age']), {'personality': 'manova'}, ['Response Specification', 'Whole Model', 'sex', 'age']),
    ]
    for label, y, eff, opts, want in runs:
        r = await page.ev(open_js(y, eff, opts))
        check(f'{label}: no errors', r['errors'], [])
        check(f'{label}: its outlines', [o for o in want if o in r['outlines']], want)

    # ---- a saved project reopens with its model (the columns found by name)
    r = await page.ev('''(async () => {
      const t = SM.app.current;
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [__fm.rep().toJSON()] };
      const n = SM.app.reports.length;
      SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const rep = SM.app.reports[n]; await __fm.done(rep);
      const cols = rep.spec.effects.map(e => e.names.join('*'));
      SM.app.showTab(SM.app.tabOf(t));   // loading a project shows its first table
      return { title: rep.title, errors: __fm.state(rep).errors, cols, sameTable: rep.table !== t }; })()''')
    check('a project reopens the report', (r['title'], r['errors']), ('Manova Fit', []))
    check('with its model effects', r['cols'], ['sex', 'age'])

    # ---- Model Dialog relaunches with the model
    r = await page.ev(open_js('weight (kg)', E(['height (cm)'], ['sex'], ['height (cm)', 'sex'])))
    check('a model with a crossing opens', r['errors'] if isinstance(r, dict) else r, [])
    r = await page.ev('''(async () => {
      await __fm.topMenu('Model Dialog'); await new Promise(r => setTimeout(r, 300));
      const eff = __fm.effects(); __fm.btn('Cancel'); return eff; })()''')
    check('Model Dialog opens the launch dialog with the model', r, ['height (cm)', 'sex', 'height (cm)*sex'])

    # ---- the dialog at phone width
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    r = await page.ev('''(async () => { SM.app.launch('fitmodel'); await new Promise(r => setTimeout(r, 400));
      const d = __fm.dlg(); const box = d.getBoundingClientRect(); const eff = d.querySelector('.sm-fm-effects').getBoundingClientRect();
      const out = { dialog: box.right <= innerWidth + 1, effects: eff.right <= box.right + 1 && eff.width > 150 };
      return out; })()''')
    await shot(page, 'fm-05-dialog-phone.png')
    await page.ev("__fm.btn('Cancel')")
    check('the launch dialog fits a phone', r, {'dialog': True, 'effects': True})
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)

    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) of the Fit Model reports has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])

    # ---- dark theme, phone width
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev('''(async () => { const rep = __fm.rep(); const d = __fm.done(rep); await __fm.topMenu('Factor Profiling', 'Profiler'); await d; })()''')
    await asyncio.sleep(1.5)
    await shot(page, 'fm-03-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(1)
    wide = await page.ev('document.documentElement.scrollWidth <= innerWidth + 1')
    check('no horizontal page scroll at phone width', wide, True)
    await shot(page, 'fm-04-phone.png')
    # ==== Generalized Estimating Equations, Robust Standard Errors, Regression Diagnostics, on the longitudinal example ====
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    r = await page.ev('''(() => { const ex = SM.io.EXAMPLES.longitudinal; SM.app.openExample('longitudinal'); const t = SM.app.current;
      return { label: ex ? ex.label : null, name: t.name, rows: t.nrows, subjects: new Set(t.col('subject').values).size, cols: t.columns.map(c => c.name),
        sorted: t.col('subject').values.every((s, i, a) => i === 0 || a[i - 1] < s || (a[i - 1] === s && t.col('visit').values[i - 1] < t.col('visit').values[i])) }; })()''')
    check('the longitudinal example (File > Examples): 240 rows, 60 subjects', (r['name'], r['rows'], r['subjects'], bool(r['label'])), ('Longitudinal trial', 240, 60, True))
    check('its columns', r['cols'], ['subject', 'clinic', 'treatment', 'visit', 'baseline', 'improved', 'symptoms', 'score'])
    await page.ev(HELPERS)
    r = await page.ev('''(async () => {
      SM.app.launch('fitmodel'); await new Promise(r => setTimeout(r, 300));
      const d = __fm.dlg(); const out = {};
      const role = (lab) => [...d.querySelectorAll('.sm-role')].find(x => x.querySelector('.sm-btn').textContent === lab);
      const shown = () => ['Offset', 'Subject', 'Time', 'Subgroup'].filter(l => !role(l).hidden);
      const ps = d.querySelector('select[aria-label="Personality"]');
      out.sls = shown();
      ps.value = 'glm'; ps.dispatchEvent(new Event('change')); out.glm = shown();
      ps.value = 'gee'; ps.dispatchEvent(new Event('change')); out.gee = shown();
      out.opts = [...d.querySelectorAll('.sm-fm-pers > label')].filter(l => !l.hidden).map(l => l.firstChild.textContent);
      __fm.pick('improved'); __fm.role('Y'); await __fm.tick();
      out.target = !d.querySelector('select[aria-label="Target Level"]').closest('label').hidden;
      __fm.pick('treatment', 'visit', 'baseline'); __fm.btn('Add');
      const dist = d.querySelector('select[aria-label="Distribution"]'); dist.value = 'binomial'; dist.dispatchEvent(new Event('change'));
      out.link = d.querySelector('select[aria-label="Link Function"]').value;
      out.scale = d.querySelector('select[aria-label="Scale"]').value;
      out.dists = [...dist.options].map(o => o.value);
      __fm.btn('OK'); await __fm.tick(); out.noSubject = d.querySelector('.sm-launch-msg').textContent;
      __fm.pick('subject'); __fm.role('Subject');
      d.querySelector('select[aria-label="Working Correlation"]').value = 'ar1';
      __fm.btn('OK'); await __fm.tick(); out.noTime = d.querySelector('.sm-launch-msg').textContent;
      __fm.pick('visit'); __fm.role('Time');
      __fm.btn('OK');
      const rep = __fm.rep(); await __fm.settled(rep);
      out.state = __fm.state(rep);
      const o = rep.spec.options;
      out.opt = { corr: o.workCorr, cov: o.geeCov, scale: o.geeScale, dist: o.dist };
      return out; })()''')
    check('Offset shows for the GLM and GEE, Subject, Time and Subgroup for GEE only', (r['sls'], r['glm'], r['gee']), ([], ['Offset'], ['Offset', 'Subject', 'Time', 'Subgroup']))
    check('the GEE options of the dialog', [o for o in ['Distribution', 'Link Function', 'Working Correlation', 'Covariance', 'Scale'] if o in r['opts']], ['Distribution', 'Link Function', 'Working Correlation', 'Covariance', 'Scale'])
    check('GEE offers the Tweedie', 'tweedie' in r['dists'], True)
    check('a two-level Y has a Target Level', r['target'], True)
    check('binomial: the logit link and the scale fixed at 1', (r['link'], r['scale']), ('logit', 'fixed'))
    check('GEE needs a Subject', 'Subject' in r['noSubject'], True)
    check('AR(1) needs a Time', 'Time' in r['noTime'], True)
    check('the GEE report', r['state']['title'], 'Generalized Estimating Equations for improved')
    for o in ['Effect Summary', 'Model Summary', 'Parameter Estimates', 'Effect Tests', 'QIC', 'Working Correlation', 'Residual by Predicted', 'Actual by Predicted Plot', 'Residuals by Subject']:
        check(f'GEE outline {o}', o in r['state']['outlines'], True)
    check('no errors in the GEE report', r['state']['errors'], [])
    check('the spec keeps the GEE options', r['opt'], {'corr': 'ar1', 'cov': 'robust', 'scale': 'fixed', 'dist': 'binomial'})
    await asyncio.sleep(1)
    await shot(page, 'fm-06-gee.png')
    r = await page.ev('''(() => ({ kv: __fm.kv('Model Summary'), pe: __fm.table('Parameter Estimates'), et: __fm.table('Effect Tests'), q: __fm.kv('QIC'),
      wc: __fm.table('Working Correlation') }))()''')
    kv = r['kv']
    check('Model Summary: 240 rows, 60 subjects of 4, AR(1), robust', (kv['Number of Rows'], kv['Number of Subjects'], kv['Rows per Subject, Max'], kv['Working Correlation'], kv['Covariance']),
          ('240', '60', '4', 'Autoregressive AR(1)', 'Robust (sandwich)'))
    check('Parameter Estimates: z tests', r['pe'][0][:5], ['Term', 'Estimate', 'Std Error', 'z Ratio', 'Prob>|z|'])
    pe = {row[0]: row for row in r['pe'][1:]}
    et = {row[0]: row for row in r['et'][1:]}
    check.near('Effect Tests: the Wald chi-square of visit = its z squared', num(et['visit'][3]), num(pe['visit'][3]) ** 2, 1e-5)
    q = r['q']
    check.near('QIC = -2 Q + 2 trace(Ω_I V_R)', num(q['QIC']), -2 * num(q['Quasi-Likelihood']) + 2 * num(q['Penalty trace(Ω_I V_R)']), 1e-5)
    check('the working correlation\'s parameter', r['wc'][1][0], 'Correlation of adjacent rows (lag 1)')
    r = await page.ev('''(async () => { const rep = __fm.rep(); const t = rep.table;
      const p = rep.plots.find(p => p.opts.title === 'improved residuals by subject');
      p._click({ points: [{ curveNumber: 0, pointNumber: 5 }], event: {} });
      const sel = t.selectedRows();
      t.select([7, 8]); await new Promise(r => setTimeout(r, 150));
      const q = rep.plots.find(p => p.opts.title === 'improved residual by predicted');
      const sp = q && q.drawn ? q.box.data[0].selectedpoints : null;
      t.select([]);
      return { sel, want: p.rows[0][5], sp, spWant: q ? q.rows[0].map((r, k) => [r, k]).filter(([r]) => r === 7 || r === 8).map(([, k]) => k).sort((a, b) => a - b) : null }; })()''')
    check('a click in Residuals by Subject selects its row', r['sel'], [r['want']])
    check('a table selection shows in Residual by Predicted', r['sp'] is None or sorted(r['sp']) == r['spWant'], True)
    r = await page.ev('''(async () => { const rep = __fm.rep(); let d = __fm.done(rep);
      await __fm.topMenu('Correlation Structure', 'Exchangeable'); await d;
      const corr = __fm.kv('Model Summary')['Working Correlation'];
      d = __fm.done(rep); await __fm.topMenu('Covariance', 'Naive (model-based)'); await d;
      const cap = __fm.outline('Parameter Estimates').querySelector('caption').textContent;
      d = __fm.done(rep); await __fm.topMenu('Covariance', 'Robust (sandwich)'); await d;
      d = __fm.done(rep); await __fm.topMenu('Odds Ratios'); await d;
      const odds = __fm.table('Odds Ratios');
      d = __fm.done(rep); await __fm.topMenu('Compare Working Correlations'); await d;
      const cmp = __fm.table('Compare Working Correlations');
      const tr = [...__fm.outline('Compare Working Correlations').querySelectorAll('tbody tr')].find(x => x.firstChild.textContent.startsWith('Unstructured'));
      d = __fm.done(rep); tr.click(); await d;
      return { corr, cap, odds, cmp, after: __fm.kv('Model Summary')['Working Correlation'], errors: __fm.state(rep).errors }; })()''')
    check('Correlation Structure > Exchangeable refits', r['corr'], 'Exchangeable')
    check('Covariance > Naive: the estimates say so', r['cap'], 'Standard errors: naive (model-based)')
    check('Odds Ratios for the logit link', r['odds'][0][:2], ['Term', 'Odds Ratio'])
    check('Compare Working Correlations: a line for each structure the roles allow', [row[0].split('  ')[0] for row in r['cmp'][1:]], ['Independence', 'Exchangeable', 'Autoregressive AR(1)', 'Unstructured'])
    check('Compare: it marks the current one and the smallest QIC', (sum('(current)' in row[0] for row in r['cmp'][1:]), sum('(smallest QIC)' in row[0] for row in r['cmp'][1:])), (1, 1))
    check('a click on a line refits with that working correlation', r['after'], 'Unstructured')
    check('no errors after the red triangle', r['errors'], [])
    r = await page.ev('''(async () => { const rep = __fm.rep(); const t = rep.table; const row = 17;
      await __fm.topMenu('Save Columns', 'Predicted Values (marginal)'); await __fm.tick();
      await __fm.topMenu('Save Columns', 'Pearson Residuals'); await __fm.tick();
      const pc = t.col('Pred improved'), pr = t.col('Pearson Residual improved');
      const d = __fm.done(rep); await __fm.topMenu('Profilers', 'Profiler'); await d;
      const ob = __fm.outline('Prediction Profiler'); ob.scrollIntoView(); await new Promise(r => setTimeout(r, 1000));
      const val = () => ob.querySelector('.sm-prof-val').textContent;
      const set = async (sel, v) => { const was = val(); const i = ob.querySelector(sel); i.value = v; i.dispatchEvent(new Event('change')); for (let k = 0; k < 400 && val() === was; k++) await new Promise(r => setTimeout(r, 5)); };
      await set('input[aria-label="visit current value"]', String(t.col('visit').values[row]));
      await set('input[aria-label="baseline current value"]', String(t.col('baseline').values[row]));
      const fsel = ob.querySelector('select[aria-label="treatment current value"]'); fsel.value = String(['placebo', 'active'].indexOf(t.col('treatment').values[row])); fsel.dispatchEvent(new Event('change'));
      await new Promise(r => setTimeout(r, 500));
      const out = { pred: val(), name: ob.querySelector('.sm-prof-name').textContent, saved: pc ? pc.values[row] : null, pears: pr ? pr.values[row] : null, y: t.col('improved').values[row] };
      for (const c of [pc, pr]) if (c) t.removeColumn(c.id);
      return out; })()''')
    check('the GEE profiler predicts Prob[yes]', r['name'], 'Prob[yes]')
    check.near('the profiler at a row\'s values predicts its saved marginal prediction', num(r['pred']), r['saved'], 1e-5)
    check.near('the saved Pearson residual is (y - p)/sqrt(p (1 - p))', r['pears'], ((1 if r['y'] == 'yes' else 0) - r['saved']) / math.sqrt(r['saved'] * (1 - r['saved'])), 1e-8)
    r = await page.ev(open_js('symptoms', E(['visit'], ['baseline']), {'personality': 'gee', 'dist': 'poisson', 'link': 'log', 'workCorr': 'exchangeable'}, {'subject': ['subject'], 'by': ['treatment']}))
    check('GEE with By: one report per level', [o for o in r['outlines'] if o.startswith('Generalized Estimating')],
          ['Generalized Estimating Equations for symptoms treatment=placebo', 'Generalized Estimating Equations for symptoms treatment=active'])
    check('GEE with By: no errors', r['errors'], [])
    r = await page.ev(open_js('symptoms', E(['treatment'], ['visit'], ['baseline']), {'personality': 'gee', 'dist': 'poisson', 'link': 'log', 'workCorr': 'nested'}, {'subject': ['clinic'], 'subgroup': ['subject']}))
    check('GEE nested: no errors', r['errors'], [])
    wc = await page.ev('__fm.table("Working Correlation")')
    check('GEE nested: its variance components', [row[0] for row in wc[1:3]], ['Variance component: clinic', 'Variance component: subject within clinic'])
    # Robust Standard Errors in Standard Least Squares, against the page's own sandwich
    r = await page.ev(open_js('score', E(['baseline'])))
    js_ls = '''const t = rep.table; const x = t.col('baseline').values, y = t.col('score').values; const n = x.length;
      const mx = x.reduce((a, b) => a + b) / n, my = y.reduce((a, b) => a + b) / n;
      let sxy = 0, sxx = 0; for (let i = 0; i < n; i++) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) ** 2; }
      const b = sxy / sxx, a = my - b * mx; const e = y.map((v, i) => v - a - b * x[i]);'''
    r = await page.ev('''(async () => { const rep = __fm.rep(); const d = __fm.done(rep);
      await __fm.topMenu('Robust Standard Errors', 'HC0 (White)'); await d;
      ''' + js_ls + '''
      let meat = 0; for (let i = 0; i < n; i++) meat += (x[i] - mx) ** 2 * e[i] * e[i];
      return { pe: __fm.table('Parameter Estimates'), cap: __fm.outline('Parameter Estimates').querySelector('caption').textContent, hc0: Math.sqrt(meat) / sxx, errors: __fm.state(rep).errors }; })()''')
    pe = {row[0]: row for row in r['pe'][1:]}
    check.near('HC0: the slope\'s robust std error = the page\'s own sandwich', num(pe['baseline'][2]), r['hc0'], 1e-6)
    check('HC0: the estimates say which covariance they use', r['cap'].startswith('Robust standard errors: HC0'), True)
    check('HC0: no errors', r['errors'], [])
    r = await page.ev('''(async () => { const rep = __fm.rep();
      await __fm.topMenu('Robust Standard Errors', 'Cluster…'); await new Promise(r => setTimeout(r, 250));
      const dlg = [...document.querySelectorAll('.sm-dialog')].find(x => x.getAttribute('aria-label') === 'Cluster-Robust Standard Errors');
      dlg.querySelector('select').value = rep.table.col('subject').id;
      const d = __fm.done(rep); dlg.querySelector('.sm-dialog-foot .primary').click(); await d;
      return { cap: __fm.outline('Parameter Estimates').querySelector('caption').textContent, et: __fm.table('Effect Tests')[0], errors: __fm.state(rep).errors }; })()''')
    check('Cluster…: the column and the number of clusters', r['cap'], 'Robust standard errors: Cluster by subject (60 clusters); t tests on 59 DF')
    check('Cluster…: Effect Tests are robust Wald F tests with a DFDen', ('DFDen' in r['et'], 'Sum of Squares' in r['et']), (True, False))
    check('Cluster…: no errors', r['errors'], [])
    r = await page.ev('''(async () => { const rep = __fm.rep(); let d = __fm.done(rep);
      await __fm.topMenu('Robust Standard Errors', 'None'); await d;
      d = __fm.done(rep); await __fm.topMenu('Regression Diagnostics', 'All Tests'); await d;
      ''' + js_ls + '''
      const m2 = e.reduce((s, v) => s + v * v, 0) / n, m3 = e.reduce((s, v) => s + v ** 3, 0) / n, m4 = e.reduce((s, v) => s + v ** 4, 0) / n;
      const S = m3 / m2 ** 1.5, K = m4 / m2 ** 2;
      return { st: __fm.state(rep), jb: __fm.table('Jarque–Bera Test'), js: (n / 6) * (S * S + (K - 3) ** 2 / 4), cap: __fm.outline('Parameter Estimates').querySelector('caption') }; })()''')
    for o in ['Regression Diagnostics', 'Breusch–Pagan Test', 'White Test', 'Goldfeld–Quandt Test', 'Ramsey RESET Test', 'Harvey–Collier Test', 'Rainbow Test', 'Breusch–Godfrey Test', 'Jarque–Bera Test', 'Omnibus Normality Test']:
        check(f'diagnostics outline {o}', o in r['st']['outlines'], True)
    check('no errors with every test', r['st']['errors'], [])
    check('Robust Standard Errors > None: the usual estimates again', r['cap'], None)
    check.near('Jarque–Bera = the page\'s own from the least squares residuals', num(r['jb'][1][1]), r['js'], 1e-5)
    r = await page.ev('''(async () => { const rep = __fm.rep(); const ob = __fm.outline('Goldfeld–Quandt Test');
      const before = __fm.table('Goldfeld–Quandt Test')[1][1];
      const s = ob.querySelector('select[aria-label="Sort by"]'); s.value = 'row'; const d = __fm.done(rep); s.dispatchEvent(new Event('change')); await d;
      return { before, after: __fm.table('Goldfeld–Quandt Test')[1][1], note: __fm.outline('Goldfeld–Quandt Test').querySelector('.sm-ob-note').textContent }; })()''')
    check('Goldfeld–Quandt: Sort by changes the test', r['before'] != r['after'], True)
    check('... and its note says the order', 'in the order of the table' in r['note'], True)
    r = await page.ev('''(async () => { const rep = __fm.rep(); let d = __fm.done(rep);
      await __fm.topMenu('Regression Diagnostics', 'Influence Plot'); await d;
      d = __fm.done(rep); await __fm.topMenu('Regression Diagnostics', 'Component + Residual Plots'); await d;
      ''' + js_ls + '''
      const p = rep.plots.find(q => q.opts.title === 'score influence plot');
      const tr = p.traces[0]; const nn = tr.x.length;
      const want = p.rows[0].filter((r, k) => Math.abs(tr.y[k]) > 2 || tr.x[k] > 4 / nn).sort((u, v) => u - v);
      const ob = __fm.outline('Influence Plot'); ob.querySelector('.sm-ob-menu').click(); await __fm.tick();
      const item = [...document.querySelectorAll('.sm-menu button')].find(bt => bt.querySelector('.sm-label').textContent.startsWith('Select Influential Rows'));
      item.click(); await __fm.tick();
      const sel = rep.table.selectedRows().slice().sort((u, v) => u - v);
      rep.table.select([]);
      const cp = rep.plots.find(q => q.opts.title === 'baseline component plus residual');
      const ccprOk = !!cp && cp.traces[0].y.every((v, k) => Math.abs(v - (y[cp.rows[0][k]] - a)) < 1e-6);
      return { want, sel, ccprOk, errors: __fm.state(rep).errors }; })()''')
    check('Influence Plot: Select Influential Rows selects the rows beyond ±2 or 2p/n', r['sel'], r['want'])
    check('... there are some', len(r['want']) > 0, True)
    check('Component + Residual: residual + b·x (for one regressor: y − the intercept)', r['ccprOk'], True)
    check('no errors with the plots', r['errors'], [])
    await shot(page, 'fm-07-diagnostics.png')
    r = await page.ev(open_js('symptoms', E(['treatment'], ['visit'], ['baseline']), {'personality': 'glm', 'dist': 'poisson', 'link': 'log'}))
    r = await page.ev('''(async () => { const rep = __fm.rep(); const d = __fm.done(rep);
      await __fm.topMenu('Robust Standard Errors', 'Sandwich (HC0)'); await d;
      return { cap: __fm.outline('Parameter Estimates').querySelector('caption').textContent, et: __fm.table('Effect Tests')[0], errors: __fm.state(rep).errors }; })()''')
    check('GLM Robust Standard Errors: the sandwich, and Wald tests', (r['cap'], 'Wald ChiSquare' in r['et']), ('Robust standard errors: Sandwich (HC0)', True))
    check('GLM robust: no errors', r['errors'], [])
    # a GEE report saved in a project reopens with its roles and options
    r = await page.ev(open_js('improved', E(['treatment'], ['visit']), {'personality': 'gee', 'dist': 'binomial', 'link': 'logit', 'workCorr': 'ar1', 'geeCov': 'bias_reduced'}, {'subject': ['subject'], 'time': ['visit']}))
    r = await page.ev('''(async () => { const t = SM.app.current;
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [__fm.rep().toJSON()] };
      const n = SM.app.reports.length; SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const rep = SM.app.reports[n]; await __fm.done(rep);
      const kv = __fm.kv('Model Summary');
      const out = { title: rep.title, errors: __fm.state(rep).errors, corr: kv['Working Correlation'], cov: kv['Covariance'], subject: kv['Subject'], time: kv['Time'], other: rep.table !== t };
      SM.app.showTab(SM.app.tabOf(t)); return out; })()''')
    check('a GEE project reopens with its roles and options', (r['title'], r['errors'], r['corr'], r['cov'], r['subject'], r['time']),
          ('Generalized Estimating Equations for improved', [], 'Autoregressive AR(1)', 'Bias-reduced (Mancl and DeRouen)', 'subject', 'visit'))
    r = await page.ev(open_js('improved', E(['treatment'], ['visit'], ['baseline']), {'personality': 'gee', 'dist': 'binomial', 'link': 'logit', 'workCorr': 'ar1'}, {'subject': ['subject'], 'time': ['visit']}))
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) of the GEE report has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(1.5)
    await page.ev('''(() => { const ob = __fm.outline('Working Correlation'); if (ob) ob.scrollIntoView({ block: 'start' }); })()''')
    await asyncio.sleep(1)
    await shot(page, 'fm-08-gee-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(1)
    wide = await page.ev('document.documentElement.scrollWidth <= innerWidth + 1')
    check('the GEE report: no horizontal page scroll at phone width', wide, True)
    await shot(page, 'fm-09-gee-phone.png')
    # ==== Instrumental Variables, Quantile Regression, Recursive and Rolling Regression, on the schooling example ====
    await schooling(page)
    # ==== Generalized Regression: the validation methods, the adaptive methods, forward selection ====
    await genreg(page)
    # ==== MANOVA's Repeated Measures; the Effect Tests' effect sizes ====
    await repeated(page)
    # ==== help for every input: the launch dialog, the red-triangle forms, the controls in the reports ====
    await help_inputs(page)
    # columns dragged onto Construct Model Effects, with the mouse: main effects, as Add makes them
    r = await page.ev('''(async () => {
      SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'Plants') || SM.app.tables[0]));
      SM.app.launch('fitmodel'); await new Promise(r => setTimeout(r, 300));
      __fm.pick('yield (g)'); __fm.role('Y'); await __fm.tick();
      __fm.pick('fertilizer', 'water');
      return 'open';
    })()''')
    check('the Fit Model dialog for the drags', r, 'open')
    xy = await page.ev('''(() => {
      const d = __fm.dlg(); const src = [...d.querySelectorAll('.sm-pick-list li')].find(li => li.textContent === 'water');
      const dst = d.querySelector('.sm-fm-effects'); src.scrollIntoView({ block: 'nearest' }); dst.scrollIntoView({ block: 'nearest' });
      const a = src.getBoundingClientRect(), b = dst.getBoundingClientRect();
      return [a.x + 20, a.y + a.height / 2, b.x + b.width / 2, b.y + b.height / 2];
    })()''')
    began = await page.drag_to(*xy)
    await asyncio.sleep(0.2)
    first = await page.ev('__fm.effects()')
    xy = await page.ev('''(() => {
      const d = __fm.dlg(); const src = [...d.querySelectorAll('.sm-pick-list li')].find(li => li.textContent === 'light (h)');
      const dst = d.querySelector('.sm-fm-effects'); const a = src.getBoundingClientRect(), b = dst.getBoundingClientRect();
      return [a.x + 20, a.y + a.height / 2, b.x + b.width / 2, b.y + b.height / 2];
    })()''')
    await page.drag_to(*xy)     # an unselected column: the press selects it, and it goes alone
    await asyncio.sleep(0.2)
    second = await page.ev('__fm.effects()')
    await page.drag_to(*xy)     # again: it is in the model already
    await asyncio.sleep(0.2)
    third = await page.ev('({ effects: __fm.effects(), msg: __fm.dlg().querySelector(".sm-launch-msg").textContent })')
    await page.ev("__fm.btn('Cancel')")
    check('a drag began from the column list', began, True)
    check('two selected columns dropped on Construct Model Effects: two main effects', first, ['fertilizer', 'water'])
    check('an unselected column dragged there goes in alone', second, ['fertilizer', 'water', 'light (h)'])
    check('... and once only', (third['effects'], third['msg']), (['fertilizer', 'water', 'light (h)'], 'Those effects are in the model already.'))

    # the model effects list: a click, shift for a sweep, ctrl/⌘ for one more, Remove
    r = await page.ev('''(async () => {
      SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'Plants') || SM.app.tables[0]));
      SM.app.launch('fitmodel'); await new Promise(r => setTimeout(r, 300));
      __fm.pick('yield (g)'); __fm.role('Y'); await __fm.tick();
      __fm.pick('fertilizer', 'water', 'light (h)', 'plot'); __fm.btn('Add'); await __fm.tick();
      const lis = () => [...__fm.dlg().querySelectorAll('.sm-fm-effects li')];
      const sel = () => lis().filter(li => li.classList.contains('is-selected')).map(li => li.textContent);
      const click = (i, o = {}) => lis()[i].dispatchEvent(new MouseEvent('click', { bubbles: true, ...o }));
      const all = __fm.effects();
      click(0); const a = sel(); click(2, { shiftKey: true }); const b = sel(); click(3, { metaKey: true }); const c = sel();
      __fm.btn('Remove'); await __fm.tick();
      const left = __fm.effects();
      __fm.btn('Cancel');
      return { all, a, b, c, left };
    })()''')
    effs = r['all']
    check('effects list: a click selects one, shift-click the third the sweep', (r['a'], r['b']), (effs[:1], effs[:3]))
    check('... ctrl/⌘ adds the fourth, and Remove takes all four out', (r['c'], r['left']), (effs[:4], effs[4:]))
    # a random effect in a personality that fits fixed effects only is refused,
    # not left out without a word
    r = await page.ev('''(() => {
      const t = SM.app.current; const v = SM.platforms.get('fitmodel').launch.validate;
      const y = t.columns.find(c => !c.isCategorical), x = t.columns.find(c => c.isCategorical);
      const spec = (personality, extra) => ({ roles: { y: [y.id] }, options: { personality, dist: 'normal', ...extra }, effects: [{ cols: [x.id], random: true }] });
      return ['glm', 'standard', 'mixed'].map(p => v(spec(p), t)).concat([v({ roles: { y: [x.id] }, options: { personality: 'nominal' }, effects: [{ cols: [y.id], random: true }] }, t)]);
    })()''')
    check('GLM refuses a random effect', (r[0] or '').startswith('Generalized Linear Model takes fixed effects only'), True)
    check('Standard Least Squares and Mixed Model take it', (r[1], r[2]), (None, None))
    check('Nominal Logistic refuses it', (r[3] or '').startswith('Nominal Logistic takes fixed effects only'), True)

    check('no script errors', page.errors, [])
    await page.close()


async def schooling(page):
    """Instrumental Variables, Quantile Regression and Recursive and Rolling
    Regression on the simulated schooling example."""
    num = lambda s: float(str(s).replace('−', '-').replace('<', '').replace('*', ''))  # noqa: E731
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    r = await page.ev('''(() => { const ex = SM.io.EXAMPLES.schooling; SM.app.openExample('schooling'); const t = SM.app.current;
      const yr = t.col('year').values;
      return { label: ex ? ex.label : null, name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), first: yr[0], last: yr[t.nrows - 1],
        sorted: yr.every((v, i) => i === 0 || yr[i - 1] <= v), lab: t.labelColumn() ? t.labelColumn().name : null }; })()''')
    check('the schooling example (File > Examples): 1500 people, 1995 to 2024, in interview order', (r['name'], r['rows'], r['first'], r['last'], r['sorted'], bool(r['label'])), ('Schooling', 1500, 1995, 2024, True, True))
    check('its columns', r['cols'], ['person', 'year', 'region', 'sex', 'birth quarter', 'experience', 'distance (km)', 'lottery', 'education', 'log wage'])
    await page.ev(HELPERS)

    # ---- the launch dialog: the roles and options of the two personalities
    r = await page.ev('''(async () => {
      SM.app.launch('fitmodel'); await new Promise(r => setTimeout(r, 300));
      const d = __fm.dlg(); const out = {};
      const role = (lab) => [...d.querySelectorAll('.sm-role')].find(x => x.querySelector('.sm-btn').textContent === lab);
      const shown = () => ['Endogenous', 'Instruments', 'Offset', 'Subject'].filter(l => !role(l).hidden);
      const tau = () => !d.querySelector('input[aria-label="Quantile"]').closest('label').hidden;
      // one column: a click after the mousedown (a mousedown on a selected column keeps the selection, for a drag)
      const one = (n) => { const li = [...d.querySelectorAll('.sm-pick-list li')].find(x => x.textContent === n); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); li.dispatchEvent(new MouseEvent('click', { bubbles: true })); };
      const ps = d.querySelector('select[aria-label="Personality"]');
      out.sls = [shown(), tau()];
      ps.value = 'quantreg'; ps.dispatchEvent(new Event('change')); out.qr = [shown(), tau()];
      ps.value = 'iv'; ps.dispatchEvent(new Event('change')); out.iv = [shown(), tau()];
      out.pers = [...ps.options].map(o => o.textContent).slice(-2);
      __fm.pick('log wage'); __fm.role('Y'); await __fm.tick();
      __fm.pick('education', 'experience', 'sex', 'region'); __fm.btn('Add');
      __fm.btn('OK'); await __fm.tick(); out.noEndog = d.querySelector('.sm-launch-msg').textContent;
      one('education'); __fm.role('Endogenous');
      __fm.btn('OK'); await __fm.tick(); out.noInst = d.querySelector('.sm-launch-msg').textContent;
      one('experience'); __fm.role('Instruments');
      __fm.btn('OK'); await __fm.tick(); out.inModel = d.querySelector('.sm-launch-msg').textContent;
      const ins = [...role('Instruments').querySelectorAll('li')][0]; ins.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      __fm.pick('distance (km)', 'lottery'); __fm.role('Instruments');
      __fm.btn('OK');
      const rep = __fm.rep(); await __fm.settled(rep);
      out.state = __fm.state(rep);
      out.roles = { endog: rep.spec.roles.endog.map(id => rep.table.col(id).name), inst: rep.spec.roles.instruments.map(id => rep.table.col(id).name) };
      return out; })()''')
    check('Standard Least Squares shows neither the IV roles nor the quantile', r['sls'], [[], False])
    check('Quantile Regression: the Quantile τ box, no IV roles', r['qr'], [[], True])
    check('Instrumental Variables: the Endogenous and Instruments roles', r['iv'], [['Endogenous', 'Instruments'], False])
    check('the two personalities are in the list', r['pers'], ['Instrumental Variables', 'Quantile Regression'])
    check('IV needs Endogenous columns', 'Endogenous' in r['noEndog'], True)
    check('... and Instruments', 'Instruments' in r['noInst'], True)
    check('... an instrument may not be a model effect', 'model effect' in r['inModel'], True)
    check('the IV report', r['state']['title'], 'Instrumental Variables Fit for log wage')
    for o in ['Actual by Predicted Plot', 'Summary of Fit', 'First Stage', 'First Stage for education', 'Second Stage Parameter Estimates', 'Effect Tests', 'Endogeneity Test', 'Overidentification Test', 'Residual by Predicted Plot']:
        check(f'IV outline {o}', o in r['state']['outlines'], True)
    check('no errors in the IV report', r['state']['errors'], [])
    check('the spec keeps the roles', r['roles'], {'endog': ['education'], 'inst': ['distance (km)', 'lottery']})
    await asyncio.sleep(1)
    await shot(page, 'fm-10-iv.png')
    r = await page.ev('''(() => ({ pe: __fm.table('Second Stage Parameter Estimates'), fs: __fm.table('First Stage'), en: __fm.table('Endogeneity Test'), ov: __fm.table('Overidentification Test') }))()''')
    pe = {row[0]: row for row in r['pe'][1:]}
    check('2SLS estimates education near the truth 0.080 (within 2 standard errors)', abs(num(pe['education'][1]) - 0.08) < 2 * num(pe['education'][2]), True)
    check('the first stage of education is strong', (r['fs'][0][3], num(r['fs'][1][3]) > 50, r['fs'][1][-1]), ('F Ratio', True, ''))
    check('the Durbin–Wu–Hausman test rejects exogeneity of education', (r['en'][1][0], num(r['en'][1][4]) < 0.01), ('Wu–Hausman F', True))
    check('one overidentifying restriction: Sargan', (r['ov'][1][0], r['ov'][1][2]), ('Sargan χ²', '1'))

    # ---- the numbers of a just-identified IV against the page's own: b = cov(z, y) / cov(z, x), the first-stage F = t²
    r = await page.ev(open_js('log wage', E(['education']), {'personality': 'iv'}, {'endog': ['education'], 'instruments': ['distance (km)']}))
    check('a just-identified IV opens', r['errors'], [])
    js = await page.ev('''(() => { const t = SM.app.current; const z = t.col('distance (km)').values, x = t.col('education').values, y = t.col('log wage').values; const n = x.length;
      const m = (a) => a.reduce((s, v) => s + v, 0) / n; const mz = m(z), mx = m(x), my = m(y);
      let szy = 0, szx = 0, szz = 0, sxx = 0; for (let i = 0; i < n; i++) { szy += (z[i] - mz) * (y[i] - my); szx += (z[i] - mz) * (x[i] - mx); szz += (z[i] - mz) ** 2; sxx += (x[i] - mx) ** 2; }
      const b = szy / szx, a = my - b * mx, r2 = szx * szx / (szz * sxx);
      return { a, b, f: (n - 2) * r2 / (1 - r2), r2 }; })()''')
    r = await page.ev('''(() => ({ pe: __fm.table('Second Stage Parameter Estimates'), fs: __fm.table('First Stage'), cd: __fm.table('First Stage', 1), ov: __fm.outline('Overidentification Test').querySelector('.sm-ob-note').textContent }))()''')
    pe = {row[0]: row for row in r['pe'][1:]}
    check.near('the 2SLS slope = the page\'s cov(z, y)/cov(z, x)', num(pe['education'][1]), js['b'], 1e-6)
    check.near('the intercept = mean(y) − b mean(x)', num(pe['Intercept'][1]), js['a'], 1e-6)
    check.near('the first-stage F = the page\'s (n − 2) r²/(1 − r²)', num(r['fs'][1][3]), js['f'], 1e-6)
    check.near('... and the Cragg–Donald statistic is that F', num(r['cd'][0][1]), js['f'], 1e-6)
    check.near('... and its RSquare', num(r['fs'][1][1]), js['r2'], 1e-6)
    check('exactly identified: no overidentification test', 'Exactly identified' in r['ov'], True)
    r = await page.ev('''(async () => { const rep = __fm.rep(); const t = rep.table;
      const p = rep.plots.find(q => q.opts.title === 'log wage residual by predicted');
      p._click({ points: [{ curveNumber: 0, pointNumber: 12 }], event: {} });
      const sel = t.selectedRows(); const want = p.rows[0][12];
      t.select([5, 6]); await new Promise(r => setTimeout(r, 150));
      const q = rep.plots.find(x => x.opts.title === 'log wage actual by predicted');
      const sp = q && q.drawn ? q.box.data[0].selectedpoints : null; t.select([]);
      let d = __fm.done(rep); await __fm.topMenu('Robust Standard Errors', 'HC1'); await d;
      const cap = __fm.outline('Second Stage Parameter Estimates').querySelector('caption').textContent;
      const fcap = __fm.outline('First Stage').querySelector('caption').textContent;
      d = __fm.done(rep); await __fm.topMenu('OLS Beside 2SLS'); await d;
      const ols = __fm.table('OLS and 2SLS');
      await __fm.topMenu('Save Columns', 'Predicted Values'); await __fm.tick();
      const pc = t.col('Predicted log wage'); const x = t.col('education').values;
      const saved = pc ? [pc.values[3], pc.values[700]] : null; const xs = [x[3], x[700]];
      if (pc) t.removeColumn(pc.id);
      return { sel, want, sp, cap, fcap, ols, saved, xs, errors: __fm.state(rep).errors }; })()''')
    check('IV: a click on a residual point selects its row', r['sel'], [r['want']])
    check('IV: a table selection shows in Actual by Predicted', r['sp'] is None or sorted(r['sp']) == [5, 6], True)
    check('IV: Robust Standard Errors > HC1, and the report says so', r['cap'].startswith('Robust standard errors: HC1'), True)
    check('... the first stage\'s F tests are robust too', 'robust Wald F' in r['fcap'], True)
    check('IV: OLS Beside 2SLS', r['ols'][0][:5] if r['ols'] else None, ['Term', 'OLS Estimate', 'OLS Std Error', '2SLS Estimate', '2SLS Std Error'])
    if r['saved']:
        check.near('IV: Save Columns > Predicted Values is a + b x', r['saved'][0], js['a'] + js['b'] * r['xs'][0], 1e-6)
        check.near('... for another row', r['saved'][1], js['a'] + js['b'] * r['xs'][1], 1e-6)
    check('IV with the red triangle: no errors', r['errors'], [])
    r = await page.ev(open_js('log wage', E(['education'], ['experience'], ['sex']), {'personality': 'iv'}, {'endog': ['education'], 'instruments': ['birth quarter']}))
    check('a weak instrument (birth quarter): the report warns', any('Weak instruments' in w for w in r['warnings']), True)
    wf = await page.ev('__fm.table("First Stage")')
    check('... its first-stage F is below 10', (num(wf[1][3]) < 10, 'weak' in wf[1][-1]), (True, True))
    r = await page.ev(open_js('log wage', E(['education'], ['experience']), {'personality': 'iv'}, {'endog': ['education'], 'instruments': ['distance (km)', 'lottery'], 'by': ['sex']}))
    check('IV with By: one report per level', [o for o in r['outlines'] if o.startswith('Instrumental Variables Fit')], ['Instrumental Variables Fit for log wage sex=female', 'Instrumental Variables Fit for log wage sex=male'])
    check('IV with By: no errors', r['errors'], [])
    r = await page.ev(open_js('log wage', E(['education'], ['experience'], ['sex']), {'personality': 'iv'}, {'endog': ['education'], 'instruments': ['distance (km)', 'lottery']}))
    r = await page.ev('''(async () => { const rep = __fm.rep(); const d = __fm.done(rep); await __fm.topMenu('Factor Profiling', 'Profiler'); await d;
      return { st: __fm.state(rep), val: __fm.outline('Prediction Profiler') ? __fm.outline('Prediction Profiler').querySelector('.sm-prof-val').textContent : null }; })()''')
    check('the IV profiler opens', ('Prediction Profiler' in r['st']['outlines'], r['st']['errors'], r['val'] is not None), (True, [], True))
    r = await page.ev('''(async () => { const t = SM.app.current;
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [__fm.rep().toJSON()] };
      const n = SM.app.reports.length; SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const rep = SM.app.reports[n]; await __fm.done(rep);
      const out = { title: rep.title, errors: __fm.state(rep).errors, endog: rep.spec.roles.endog.map(id => rep.table.col(id).name), inst: rep.spec.roles.instruments.map(id => rep.table.col(id).name),
        line: rep.body.querySelector('.sm-fm-modelline').textContent, other: rep.table !== t };
      SM.app.showTab(SM.app.tabOf(t)); return out; })()''')
    check('an IV project reopens with its roles (the columns found again)', (r['title'], r['errors'], r['endog'], r['inst'], r['other']),
          ('Instrumental Variables Fit for log wage', [], ['education'], ['distance (km)', 'lottery'], True))

    # ---- Quantile Regression
    r = await page.ev('''(async () => {
      SM.app.launch('fitmodel'); await new Promise(r => setTimeout(r, 300));
      const d = __fm.dlg();
      const ps = d.querySelector('select[aria-label="Personality"]'); ps.value = 'quantreg'; ps.dispatchEvent(new Event('change'));
      __fm.pick('log wage'); __fm.role('Y'); await __fm.tick();
      __fm.pick('education', 'experience', 'sex'); __fm.btn('Add');
      const tau = d.querySelector('input[aria-label="Quantile"]'); tau.value = '1.5'; __fm.btn('OK'); await __fm.tick();
      const bad = d.querySelector('.sm-launch-msg').textContent;
      tau.value = '0.25'; __fm.btn('OK');
      const rep = __fm.rep(); await __fm.settled(rep);
      return { bad, st: __fm.state(rep), kv: __fm.kv('Summary of Fit'), opt: rep.spec.options.qrTau }; })()''')
    check('Quantile Regression refuses τ = 1.5', 'strictly between 0 and 1' in r['bad'], True)
    check('the quantile regression report', (r['st']['title'], r['opt']), ('Quantile Regression Fit for log wage', 0.25))
    for o in ['Model Launch', 'Actual by Predicted Plot', 'Summary of Fit', 'Parameter Estimates', 'Quantile Process']:
        check(f'QR outline {o}', o in r['st']['outlines'], True)
    check('no errors in the QR report', r['st']['errors'], [])
    check('... the quantile of the dialog', r['kv']['Quantile (τ)'], '0.25')
    check.near('... about a quarter of the rows below the fit', num(r['kv']['Share of Rows Below the Fit']), 0.25, 0.01)
    await asyncio.sleep(1)
    await shot(page, 'fm-11-quantreg.png')
    r = await page.ev('''(async () => { const rep = __fm.rep(); const t = rep.table;
      const before = __fm.table('Parameter Estimates');
      const inp = __fm.outline('Model Launch').querySelector('input[aria-label="Quantile"]');
      let d = __fm.done(rep); inp.value = '0.75'; inp.dispatchEvent(new Event('change')); await d;
      const after = __fm.table('Parameter Estimates');
      const sel = __fm.outline('Model Launch').querySelector('select[aria-label="Standard Errors"]');
      d = __fm.done(rep); sel.value = 'powell'; sel.dispatchEvent(new Event('change')); await d;
      const cap = __fm.outline('Parameter Estimates').querySelector('caption').textContent;
      await __fm.topMenu('Save Columns', 'Predicted Quantile'); await __fm.tick();
      const pc = t.col('Pred Quantile(0.75) log wage'); const y = t.col('log wage').values;
      let below = 0; if (pc) for (let i = 0; i < t.nrows; i++) if (y[i] < pc.values[i]) below++;
      if (pc) t.removeColumn(pc.id);
      d = __fm.done(rep); await __fm.topMenu('Quantile Process Estimates'); await d;
      const proc = __fm.table('Quantile Process Estimates');
      const plots = rep.plots.filter(p => /quantile process$/.test(p.opts.title || '')).length;
      return { before: before[2][1], after: after[2][1], tau: rep.spec.options.qrTau, cap, below: below / t.nrows, proc: proc ? [proc[0].slice(0, 3), proc.length - 1] : null, plots, errors: __fm.state(rep).errors }; })()''')
    check('Model Launch: a new quantile refits (the estimates change)', (r['tau'], r['before'] != r['after']), (0.75, True))
    check('Model Launch: Powell\'s sandwich, and the report says so', 'powell sandwich' in r['cap'], True)
    check.near('Save Columns > Predicted Quantile: three quarters of the rows below their saved 0.75 quantile', r['below'], 0.75, 0.01)
    check('the quantile process table: a line for each of the 19 quantiles', r['proc'], [['Quantile', 'Pseudo RSquare', 'Intercept'], 19])
    check('the quantile process: a plot for each of the 4 terms', r['plots'], 4)
    check('QR with the red triangle: no errors', r['errors'], [])
    r = await page.ev(open_js('log wage', E(['experience']), {'personality': 'quantreg', 'qrTau': 0.5}))
    check('one continuous X: the Quantile Regression Plot', ('Quantile Regression Plot' in r['outlines'], r['errors']), (True, []))
    ql = await page.ev('''(() => { const rep = __fm.rep(); const p = rep.plots.find(q => q.opts.title === 'log wage quantile lines');
      const names = p.traces.filter(t => t.mode === 'lines').map(t => t.name);
      const pe = __fm.table('Parameter Estimates'); const med = p.traces.find(t => t.name === 'τ = 0.5');
      return { names, slope: (med.y[med.y.length - 1] - med.y[0]) / (med.x[med.x.length - 1] - med.x[0]), est: pe[2][1] }; })()''')
    check('... lines for 0.1, 0.25, 0.5, 0.75, 0.9 and least squares', ql['names'], ['τ = 0.1', 'τ = 0.25', 'τ = 0.5', 'τ = 0.75', 'τ = 0.9', 'Least squares'])
    check.near('... the median line has the reported slope', ql['slope'], num(ql['est']), 1e-6)
    r = await page.ev(open_js('log wage', E(['education'], ['experience']), {'personality': 'quantreg', 'qrTau': 0.5}, {'by': ['sex']}))
    check('QR with By: no errors', (len([o for o in r['outlines'] if o.startswith('Quantile Regression Fit')]), r['errors']), (2, []))

    # ---- Recursive and Rolling Regression in Standard Least Squares
    r = await page.ev(open_js('log wage', E(['education'], ['experience'], ['sex'], ['region']), {'personality': 'standard'}))
    r = await page.ev('''(async () => { const rep = __fm.rep(); const d = __fm.done(rep);
      await __fm.topMenu('Recursive and Rolling Regression', 'All Four'); await d;
      const st = __fm.state(rep);
      const pe = Object.fromEntries(__fm.table('Parameter Estimates').slice(1).map(r => [r[0], __fm.num(r[1])]));
      const last = {}; for (const p of rep.plots) { const m = /^(.*) recursive estimate$/.exec(p.opts.title || ''); if (m) { const tr = p.traces[2]; last[m[1]] = tr.y[tr.y.length - 1]; } }
      return { st, pe, last, cusum: __fm.kv('CUSUM'), sq: __fm.kv('CUSUM of Squares') }; })()''')
    cus0 = r['cusum']
    for o in ['Recursive and Rolling Regression', 'Recursive Estimates', 'CUSUM', 'CUSUM of Squares', 'Rolling Regression, Window 150']:
        check(f'recursive outline {o}', o in r['st']['outlines'], True)
    check('no errors in the recursive and rolling reports', r['st']['errors'], [])
    check('the last recursive estimates are the Parameter Estimates', all(abs(r['last'][k] - r['pe'][k]) < 1e-6 * max(1, abs(r['pe'][k])) for k in r['pe']), True)
    check('the CUSUM crosses its bounds after the 2008 break (row 651 on)', r['cusum']['Crosses the bounds'] == 'Yes' and int(r['cusum']['First crossing, observation']) > 651, True)
    await asyncio.sleep(1)
    await page.ev('''(() => { const ob = __fm.outline('CUSUM'); if (ob) ob.scrollIntoView({ block: 'start' }); })()''')
    await asyncio.sleep(1)
    await shot(page, 'fm-12-cusum.png')
    r = await page.ev('''(async () => { const rep = __fm.rep(); const t = rep.table;
      const p = rep.plots.find(q => q.opts.title === 'log wage CUSUM');
      p._click({ points: [{ curveNumber: 2, pointNumber: 100 }], event: {} });
      const sel = t.selectedRows(); const want = p.rows[2][100];
      const q = rep.plots.find(x => x.opts.title === 'experience rolling estimate');
      q._click({ points: [{ curveNumber: 2, pointNumber: 10 }], event: {} });
      const win = t.selectedRows().slice().sort((a, b) => a - b);
      t.select([]);
      const ob = __fm.outline('Recursive and Rolling Regression');
      const s = ob.querySelector('select[aria-label="Order by"]'); let d = __fm.done(rep);
      s.value = t.col('year').id; s.dispatchEvent(new Event('change')); await d;
      const year = { cusum: __fm.kv('CUSUM'), title: rep.plots.find(x => x.opts.title === 'log wage CUSUM').userLayout.xaxis.title.text };
      const s2 = __fm.outline('Recursive and Rolling Regression').querySelector('select[aria-label="Order by"]'); d = __fm.done(rep);
      s2.value = t.col('experience').id; s2.dispatchEvent(new Event('change')); await d;
      const expr = __fm.kv('CUSUM');
      d = __fm.done(rep); await __fm.topMenu('Recursive and Rolling Regression', 'Rolling Window…'); await new Promise(r => setTimeout(r, 250));
      const dlg = [...document.querySelectorAll('.sm-dialog')].find(x => x.getAttribute('aria-label') === 'Rolling Window');
      dlg.querySelector('input').value = '100'; dlg.querySelector('.sm-dialog-foot .primary').click(); await d;
      return { sel, want, win, year, expr, st: __fm.state(rep) }; })()''')
    check('a click on a CUSUM point selects the row it adds', r['sel'], [r['want']])
    check('a click on a rolling point selects its window\'s 150 rows (consecutive in the order)', (len(r['win']), r['win'][-1] - r['win'][0]), (150, 149))
    check('Order by year: the table\'s order again (it is in interview order), and the axis says so', (r['year']['cusum']['First crossing, observation'], 'sorted by year' in r['year']['title']), (cus0['First crossing, observation'], True))
    check('Order by experience: another order, another CUSUM', r['expr'] != r['year']['cusum'], True)
    check('Rolling Window… 100', 'Rolling Regression, Window 100' in r['st']['outlines'], True)
    check('no errors after the controls', r['st']['errors'], [])
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) of the new reports has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2)
    await page.ev('''(() => { const ob = __fm.outline('Recursive Estimates'); if (ob) ob.scrollIntoView({ block: 'start' }); })()''')
    await asyncio.sleep(1)
    await shot(page, 'fm-13-recursive-dark.png')
    r = await page.ev(open_js('log wage', E(['education'], ['experience'], ['sex']), {'personality': 'quantreg', 'qrTau': 0.9}))
    await asyncio.sleep(1.5)
    await page.ev('''(() => { const ob = __fm.outline('Quantile Process'); if (ob) ob.scrollIntoView({ block: 'start' }); })()''')
    await asyncio.sleep(1)
    await shot(page, 'fm-14-process-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(1.2)
    check('the quantile regression report: no horizontal page scroll at phone width', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, 'fm-15-quantreg-phone.png')
    r = await page.ev(open_js('log wage', E(['education'], ['experience'], ['sex']), {'personality': 'iv'}, {'endog': ['education'], 'instruments': ['distance (km)', 'lottery']}))
    await asyncio.sleep(1.2)
    check('the IV report: no horizontal page scroll at phone width', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, 'fm-16-iv-phone.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")


# A table for Generalized Regression: y (normal), yb (two levels), a Validation column as numbers (v) and as names (vt).
GR_TABLE = """((n) => { const r = SM.util.rng('genreg-ui'); const cols = [];
  const X = []; for (let j = 0; j < 6; j++) X.push(Array.from({ length: n }, () => +r.normal(0, 1).toFixed(4)));
  const eta = X[0].map((v, i) => 1.5 * v - 1.0 * X[1][i] + 0.6 * X[4][i]);
  for (let j = 0; j < 6; j++) cols.push({ name: 'x' + j, dataType: 'numeric', values: X[j] });
  cols.push({ name: 'y', dataType: 'numeric', values: eta.map((e) => +(1 + e + r.normal(0, 1)).toFixed(4)) });
  cols.push({ name: 'yb', dataType: 'character', values: eta.map((e) => (r.u() < 1 / (1 + Math.exp(-e)) ? 'yes' : 'no')), valueOrder: ['yes', 'no'] });
  const vv = Array.from({ length: n }, () => { const u = r.u(); return u < 0.6 ? 0 : u < 0.85 ? 1 : 2; });
  cols.push({ name: 'v', dataType: 'numeric', values: vv });
  cols.push({ name: 'vt', dataType: 'character', values: vv.map((k) => ['Training', 'Validation', 'Test'][k]) });
  cols.push({ name: 'sex', dataType: 'character', values: Array.from({ length: n }, () => (r.u() < 0.5 ? 'F' : 'M')) });
  const t = new SM.Table({ name: 'GenReg test', source: 'simulated', columns: cols }); SM.app.addTable(t); return t.nrows; })"""

# Set report options of the response and wait for the redraw.
GR_SET = """(async (pairs) => { const rep = __fm.rep(); const y = rep.table.col(rep.spec.roles.y[0]).id; const d = __fm.done(rep);
  for (const [k, v] of pairs) rep.spec.options[y + '|' + k] = v; rep.run(); await d; return __fm.state(rep); })"""


def gr_set(**kw):
    return f'({GR_SET})({json.dumps([[k.replace("_", ":", 1), v] for k, v in kw.items()])})'


async def genreg(page):
    """Generalized Regression (JMP Pro's): the Validation role, the Model
    Launch's methods, the Model Summary per set, the Solution Path's draggable
    line, Save Columns, the profiler, By, Redo, a project, both themes."""
    num = lambda s: float(str(s).replace('−', '-').replace('<', '').replace('*', ''))  # noqa: E731
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    check('the GenReg test table', await page.ev(f'({GR_TABLE})(400)'), 400)
    await page.ev(HELPERS)
    sk0 = await page.ev("!!(SM.engine.versions && SM.engine.versions['scikit-learn'])")

    # ---- the launch dialog: the Validation role; Generalized Regression takes it as its Validation Column
    r = await page.ev('''(async () => {
      SM.app.launch('fitmodel'); await new Promise(r => setTimeout(r, 300));
      const d = __fm.dlg(); const out = {};
      const role = (lab) => [...d.querySelectorAll('.sm-role')].find(x => x.querySelector('.sm-btn').textContent === lab);
      out.role = !!role('Validation') && !role('Validation').hidden;
      __fm.pick('y'); __fm.role('Y'); await __fm.tick();
      __fm.pick('x0', 'x1', 'x2', 'x3', 'x4', 'x5'); __fm.btn('Add');
      __fm.pick('v'); __fm.role('Validation');
      const ps = d.querySelector('select[aria-label="Personality"]'); ps.value = 'genreg'; ps.dispatchEvent(new Event('change'));
      __fm.btn('OK');
      const rep = __fm.rep(); await __fm.settled(rep);
      const vm = __fm.outline('Model Launch').querySelector('select[aria-label="Validation Method"]');
      const t = rep.table; const v = t.col('v').values;
      return { ...out, st: __fm.state(rep), vm: vm.value, choices: [...vm.options].map(o => o.textContent), sum: __fm.table('Model Summary', 1),
        counts: [0, 1, 2].map(k => v.filter(x => x === k).length), roles: rep.spec.roles.validation.map(id => t.col(id).name) }; })()''')
    check('Fit Model\'s launch has a Validation role', r['role'], True)
    check('Generalized Regression takes it: Validation Column', (r['st']['title'], r['vm'], r['roles']), ('Generalized Regression for y', 'validation', ['v']))
    check('... with a Validation column the methods are AICc, BIC, Validation Column', r['choices'], ['AICc', 'BIC', 'Validation Column'])
    for o in ['Model Launch', 'Lasso with Validation Column', 'Model Summary', 'Solution Path', 'Parameter Estimates for Centered and Scaled Predictors', 'Parameter Estimates for Original Predictors']:
        check(f'GenReg outline {o}', o in r['st']['outlines'], True)
    check('no errors in the GenReg report', r['st']['errors'], [])
    sm_ = {row[0]: row for row in r['sum']}
    check('the Model Summary: a column per set', r['sum'][0], ['Measure', 'Training', 'Validation', 'Test'])
    check('... their rows are the Validation column\'s 0, 1 and 2', [int(num(x)) for x in sm_['Number of rows'][1:]], r['counts'])
    cur = await page.ev('''(() => { const p = __fm.rep().plots.find(q => q.opts.title === 'Scaled -LogLikelihood path'); return p.traces[1].y[0]; })()''')
    check.near('... the curve at the model is the Validation Scaled -LogLikelihood', cur, num(sm_['Scaled -LogLikelihood'][2]), 1e-6)
    await asyncio.sleep(1)
    await shot(page, 'fm-17-genreg-validation.png')

    # ---- another personality with the Validation role says it ignores it
    r = await page.ev(open_js('y', E(['x0'], ['x1']), {'personality': 'standard'}, {'validation': ['v']}))
    notes = await page.ev('[...__fm.rep().body.querySelectorAll(".sm-ob-note")].map(n => n.textContent)')
    check('Standard Least Squares with a Validation column says only Generalized Regression uses it', any('only Generalized Regression uses' in n for n in notes), True)
    check('... and fits every row', (await page.ev('__fm.kv("Summary of Fit")'))['Observations (or Sum Wgts)'], '400')

    # ---- no Validation column: AICc, BIC, KFold, Holdback, Leave-One-Out
    E6 = E(*[[f'x{j}'] for j in range(6)])
    r = await page.ev(open_js('y', E6, {'personality': 'genreg'}))
    r = await page.ev('''(() => { const ml = __fm.outline('Model Launch'); const q = (l) => ml.querySelector(`select[aria-label="${l}"]`);
      return { vm: [...q('Validation Method').options].map(o => o.textContent), em: [...q('Estimation Method').options].map(o => o.textContent),
        adaptive: !!ml.querySelector('input[aria-label="Adaptive"]') }; })()''')
    check('without a Validation column: AICc, BIC, KFold, Holdback, Leave-One-Out', r['vm'], ['AICc', 'BIC', 'KFold', 'Holdback', 'Leave-One-Out'])
    check('the Estimation Methods', r['em'], ['Lasso', 'Elastic Net', 'Ridge', 'Forward Selection', 'Pruned Forward Selection'])
    check('the lasso has an Adaptive box', r['adaptive'], True)
    r = await page.ev('''(async () => { const rep = __fm.rep();
      const s = __fm.outline('Model Launch').querySelector('select[aria-label="Validation Method"]'); const d = __fm.done(rep); s.value = 'kfold'; s.dispatchEvent(new Event('change')); await d;
      const m2 = __fm.outline('Model Launch');
      return { st: __fm.state(rep), folds: m2.querySelector('input[aria-label="Number of Folds"]').value, seed: m2.querySelector('input[aria-label="Random Seed"]').placeholder,
        drawn: rep.spec.options.seedDrawn, sum: __fm.table('Model Summary', 1), notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(n => n.textContent) }; })()''')
    sm_ = {row[0]: row for row in r['sum']}
    check('KFold: the report, the Number of Folds, the seed drawn and kept', ('Lasso with KFold Validation' in r['st']['outlines'], r['folds'], r['drawn'] is not None and r['seed'] == str(r['drawn'])), (True, '5', True))
    check('... the final model\'s Training and Validation sets: four folds and one', (int(num(sm_['Number of rows'][1])) + int(num(sm_['Number of rows'][2])), int(num(sm_['Number of rows'][2]))), (400, 80))
    check('... the notes say which fold, as JMP chooses it', any('As JMP does, the model reported is the fold model' in n for n in r['notes']), True)
    check('no errors with KFold', r['st']['errors'], [])
    kf_sum = r['sum']
    r = await page.ev('''(async () => { const rep = __fm.rep(); const d = __fm.done(rep); rep.run(); await d; return __fm.table('Model Summary', 1); })()''')
    check('Redo draws the same folds (the seed kept with the report)', r, kf_sum)
    # the red line dragged to another point of the path, a click, Reset to the Best Model
    r = await page.ev('''(async () => { const rep = __fm.rep();
      const key = () => rep.spec.options[Object.keys(rep.spec.options).find(k2 => k2.endsWith('|gr:choose:'))];
      const lamOf = () => __fm.table('Model Summary', 1).find(r => r[0] === 'Lambda Penalty')[1];
      const drawn = async (title) => { __fm.outline('Solution Path').scrollIntoView({ block: 'start' }); let q = null;
        for (let i = 0; i < 200; i++) { q = rep.plots.find(q2 => q2.opts.title === title); if (q && q.drawn) break; await new Promise(r => setTimeout(r, 25)); } return q; };
      const p = await drawn('Scaled -LogLikelihood path'); const x = p.traces[0].x;
      const lam0 = lamOf(); const best = x.indexOf(p.traces[1].x[0]); const k = best > 10 ? best - 8 : best + 8;
      let d = __fm.done(rep); p.box.emit('plotly_relayout', { 'shapes[0].x0': x[k] + 1e-9, 'shapes[0].x1': x[k] + 1e-9 }); await d;
      const q = await drawn('Scaled -LogLikelihood path');
      const after = { lam: lamOf(), at: q.traces[1].x[0], x: x[k], shapes: q.userLayout.shapes.length, chosen: key() };
      d = __fm.done(rep); q.box.emit('plotly_click', { points: [{ curveNumber: 0, pointNumber: k + 1, data: q.traces[0] }] }); await d;
      const clicked = key();
      d = __fm.done(rep); __fm.outline('Solution Path').querySelector('.sm-ob-menu').click(); await __fm.tick(); await __fm.menuItem('Reset to the Best Model'); await d;
      return { lam0, best, k, after, clicked, reset: { lam: lamOf(), chosen: key() }, errors: __fm.state(rep).errors }; })()''')
    check('dragging the red line shows the model at that point of the path', (r['after']['chosen'], r['after']['at'] == r['after']['x'], r['after']['lam'] != r['lam0']), (r['k'], True, True))
    check('... and the best one stays marked (a dotted line)', r['after']['shapes'], 2)
    check('a click on a point shows that model', r['clicked'], r['k'] + 1)
    check('Reset to the Best Model', (r['reset']['chosen'], r['reset']['lam']), (None, r['lam0']))
    check('no errors after the drag', r['errors'], [])
    await page.ev('''(() => { const ob = __fm.outline('Solution Path'); if (ob) ob.scrollIntoView({ block: 'start' }); })()''')
    await asyncio.sleep(1)
    await shot(page, 'fm-18-genreg-kfold.png')

    # ---- Holdback: the share of rows, Save Columns > Validation Column, another seed
    r = await page.ev(gr_set(gr_crit='holdback'))
    check('Holdback: the report', ('Lasso with Holdback Validation' in r['outlines'], r['errors']), (True, []))
    r = await page.ev('''(async () => { const rep = __fm.rep(); const t = rep.table;
      const sum = __fm.table('Model Summary', 1); const nv = __fm.num(sum.find(r => r[0] === 'Number of rows')[2]);
      await __fm.topMenu('Save Columns', 'Validation Column'); await __fm.tick();
      const c = t.col('Validation'); const ones = c ? c.values.filter(v => v === 1).length : null; const mt = c ? c.modelingType : null;
      if (c) t.removeColumn(c.id);
      const s = __fm.outline('Model Launch').querySelector('input[aria-label="Random Seed"]');
      const d = __fm.done(rep); s.value = '4242'; s.dispatchEvent(new Event('change')); await d;
      return { nv, ones, mt, seed: rep.spec.options.seed, kv: __fm.kv('Model Summary')['Random Seed'], changed: JSON.stringify(__fm.table('Model Summary', 1)) !== JSON.stringify(sum),
        prop: __fm.outline('Model Launch').querySelector('input[aria-label="Holdback Proportion"]').value }; })()''')
    check('... 0.3 of the rows held back (the Holdback Proportion)', (r['prop'], r['nv']), ('0.3', 120))
    check('Save Columns > Validation Column: its 1s are the held-back rows', (r['ones'], r['mt']), (120, 'nominal'))
    check('a Random Seed of one\'s own draws other rows, and the Model Summary says it', (r['seed'], r['kv'], r['changed']), ('4242', '4242', True))
    r = await page.ev('''(async () => { const tbl = __fm.outline('Parameter Estimates for Original Predictors').querySelector('table.sm-rt');
      const t = await SM.bootstrap.run(tbl, tbl._rt.columns.find(c => c.key === 'estimate'), { B: 4, seed: 3, show: false });
      return { n: t.nrows, failed: / failed/.test(t.notes), finite: t.columns.slice(1).every(c => c.values.every(Number.isFinite)), cols: t.columns.length - 1 }; })()''')
    check('Bootstrap of the estimates reruns the fit headless on resampled rows (repeats and all)', (r['n'], r['failed'], r['finite'], r['cols']), (5, False, True, 7))

    # ---- Forward Selection: each step a least squares fit, against the page's own
    r = await page.ev(gr_set(gr_crit='aicc', gr_method='forward'))
    adapt = await page.ev("!!__fm.outline('Model Launch').querySelector('input[aria-label=\"Adaptive\"]')")
    check('Forward Selection with AICc: the report, no Adaptive box', ('Forward Selection with AICc Validation' in r['outlines'], adapt), (True, False))
    js = await page.ev('''(() => { const t = SM.app.current; const n = t.nrows;
      const pe = __fm.table('Parameter Estimates for Centered and Scaled Predictors').slice(1).map(r => [r[0], __fm.num(r[1])]);
      const inn = pe.filter(([k, v]) => k !== 'Intercept' && v !== 0).map(([k]) => k);
      const z = inn.map(k => { const x = t.col(k).values; const m = x.reduce((a, b) => a + b) / n; const sd = Math.sqrt(x.reduce((a, b) => a + (b - m) ** 2, 0) / n); return x.map(v => (v - m) / sd); });
      const y = t.col('y').values; const A = [Array(n).fill(1), ...z]; const p = A.length;
      const M = A.map((a) => [...A.map(b => a.reduce((s, v, i) => s + v * b[i], 0)), a.reduce((s, v, i) => s + v * y[i], 0)]);
      for (let k = 0; k < p; k++) for (let i = 0; i < p; i++) if (i !== k) { const f = M[i][k] / M[k][k]; for (let j = k; j <= p; j++) M[i][j] -= f * M[k][j]; }
      const b = M.map((r, i) => r[p] / r[i]);
      const got = [pe.find(([k]) => k === 'Intercept')[1], ...inn.map(k => pe.find(([q]) => q === k)[1])];
      const sp = __fm.rep().plots.find(q => q.opts.title === 'solution path');
      return { inn, err: Math.max(...b.map((v, i) => Math.abs(v - got[i]) / Math.max(1, Math.abs(v)))), x0: sp.traces[0].x[0], x1: sp.traces[0].x[1], xlab: sp.userLayout.xaxis.title.text }; })()''')
    check('Forward Selection: the true terms are in', all(k in js['inn'] for k in ['x0', 'x1', 'x4']), True)
    check.near('... the chosen step is least squares on its terms (the page\'s own normal equations)', js['err'], 0.0, 1e-5)
    check('... the path runs by step', (js['xlab'], js['x0'], js['x1']), ('Step', 0, 1))
    r = await page.ev(gr_set(gr_method='pruned'))
    check('Pruned Forward Selection: no errors', ('Pruned Forward Selection with AICc Validation' in r['outlines'], r['errors']), (True, []))
    r = await page.ev(gr_set(gr_method='enet', gr_adaptive=True, gr_crit='loo'))
    check('Adaptive Elastic Net with Leave-One-Out', ('Adaptive Elastic Net with Leave-One-Out Validation' in r['outlines'], r['errors']), (True, []))
    check('... Elastic Net Alpha in the Model Launch', await page.ev("__fm.outline('Model Launch').querySelector('input[aria-label=\"Elastic Net Alpha\"]').value"), '0.9')

    # ---- binomial: KFold, the profiler against Save Columns
    r = await page.ev(open_js('yb', E6, {'personality': 'genreg'}))
    r = await page.ev(gr_set(gr_crit='kfold'))
    dist = (await page.ev('__fm.kv("Model Summary")'))['Distribution']
    check('a two-level Y: binomial, with KFold', ('Lasso with KFold Validation' in r['outlines'], r['errors'], dist), (True, [], 'Binomial'))
    r = await page.ev('''(async () => { const rep = __fm.rep(); const t = rep.table; const row = 11;
      await __fm.topMenu('Save Columns', 'Predicted Values'); await __fm.tick();
      const pc = t.col('Pred yb');
      const d = __fm.done(rep); await __fm.topMenu('Profilers', 'Profiler'); await d;
      const ob = __fm.outline('Prediction Profiler'); ob.scrollIntoView(); await new Promise(r => setTimeout(r, 800));
      const val = () => ob.querySelector('.sm-prof-val').textContent;
      for (let j = 0; j < 6; j++) { const i = ob.querySelector(`input[aria-label="x${j} current value"]`); const was = val(); i.value = String(t.col('x' + j).values[row]); i.dispatchEvent(new Event('change')); for (let k = 0; k < 400 && val() === was; k++) await new Promise(r => setTimeout(r, 5)); }
      await new Promise(r => setTimeout(r, 300));
      const out = { pred: val(), name: ob.querySelector('.sm-prof-name').textContent, saved: pc ? pc.values[row] : null, all01: pc ? pc.values.every(v => v > 0 && v < 1) : null };
      if (pc) t.removeColumn(pc.id);
      return out; })()''')
    check('the profiler predicts Prob[yes]', r['name'], 'Prob[yes]')
    check.near('... at a row\'s values it gives its saved prediction', num(r['pred']), r['saved'], 1e-5)
    check('... probabilities strictly inside (0, 1)', r['all01'], True)
    t0 = await page.ev('performance.now()')
    await page.ev(f'({GR_TABLE})(2000)')
    await page.ev(HELPERS)
    r = await page.ev(open_js('yb', E6, {'personality': 'genreg'}))
    r = await page.ev(gr_set(gr_crit='kfold'))
    ms = await page.ev('performance.now()') - t0
    check('2000 rows, binomial lasso with KFold: a few seconds', (r['errors'], ms < 15000), ([], True))
    print(f'      GenReg binomial KFold, 2000 rows: {ms / 1000:.1f} s (with the table and the default AICc report)')
    check('Generalized Regression needs no scikit-learn (no extra download)', (sk0, await page.ev("!!(SM.engine.versions && SM.engine.versions['scikit-learn'])")), (False, False))

    # ---- Diagnostic Plots (normal), linked; By; a project
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'GenReg test' && t.nrows === 400)))")
    await page.ev(HELPERS)
    r = await page.ev(open_js('y', E6, {'personality': 'genreg'}, {'validation': ['vt']}))
    r = await page.ev(gr_set(gr_diag=True))
    check('Diagnostic Plots: Actual by Predicted for each set', ('Actual by Predicted Plot' in r['outlines'], r['errors']), (True, []))
    r = await page.ev('''(async () => { const rep = __fm.rep(); const t = rep.table;
      const ps = rep.plots.filter(p => /^Actual by predicted/.test(p.opts.title || ''));
      const p = ps.find(q => q.opts.title === 'Actual by predicted Validation'); p._click({ points: [{ curveNumber: 0, pointNumber: 3 }], event: {} });
      const sel = t.selectedRows(); const want = p.rows[0][3]; t.select([]);
      return { titles: ps.map(q => q.opts.title), sel, want, set: t.col('vt').values[want] }; })()''')
    check('... one plot per set', r['titles'], ['Actual by predicted Training', 'Actual by predicted Validation', 'Actual by predicted Test'])
    check('... a click on a point selects its row, a Validation row', (r['sel'], r['set']), ([r['want']], 'Validation'))
    r = await page.ev(open_js('y', E6, {'personality': 'genreg'}, {'by': ['sex']}))
    r = await page.ev(gr_set(gr_crit='kfold', gr_method='enet'))
    check('GenReg with By: one report per level, no errors', ([o for o in r['outlines'] if o.startswith('Generalized Regression for')], r['errors']),
          (['Generalized Regression for y sex=F', 'Generalized Regression for y sex=M'], []))
    r = await page.ev(open_js('yb', E6, {'personality': 'genreg'}, {'validation': ['v']}))
    r = await page.ev(gr_set(gr_method='lasso', gr_adaptive=True, gr_crit='bic'))
    r = await page.ev('''(async () => { const t = SM.app.current; const before = __fm.table('Model Summary', 1);
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [__fm.rep().toJSON()] };
      const n = SM.app.reports.length; SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const rep = SM.app.reports[n]; await __fm.done(rep);
      const out = { title: rep.title, errors: __fm.state(rep).errors, outlines: __fm.state(rep).outlines, same: JSON.stringify(__fm.table('Model Summary', 1, rep)) === JSON.stringify(before),
        v: rep.spec.roles.validation.map(id => rep.table.col(id).name), other: rep.table !== t };
      SM.app.showTab(SM.app.tabOf(t)); return out; })()''')
    check('a GenReg project reopens with its Validation column and options', (r['title'], r['errors'], 'Adaptive Lasso with BIC Validation' in r['outlines'], r['v'], r['other']),
          ('Generalized Regression for yb', [], True, ['v'], True))
    check('... and the same Model Summary', r['same'], True)
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) of the GenReg reports has a topic', audit.get('noTopic'), [])
    # ---- dark theme, phone width
    r = await page.ev(open_js('y', E6, {'personality': 'genreg'}))
    r = await page.ev(gr_set(gr_crit='holdback', gr_method='enet'))
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(1.5)
    await page.ev('''(() => { const ob = __fm.outline('Model Summary'); if (ob) ob.scrollIntoView({ block: 'start' }); })()''')
    await asyncio.sleep(1)
    await shot(page, 'fm-19-genreg-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(1.2)
    check('the GenReg report: no horizontal page scroll at phone width', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, 'fm-20-genreg-phone.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")


# A repeated-measures table: 36 subjects in three groups and two sites, measured four times (one missing).
RM_TABLE = r'''(() => {
  const r = SM.util.rng('smui-repeated-test'); const n = 36;
  const c = { subject: [], group: [], site: [], t1: [], t2: [], t3: [], t4: [] };
  for (let i = 0; i < n; i++) {
    const g = ['control', 'low', 'high'][i % 3], u = r.normal(0, 1.2), eff = { control: 0, low: 0.4, high: 0.9 }[g];
    c.subject.push(`S${i + 1}`); c.group.push(g); c.site.push(i < 18 ? 'A' : 'B');
    c.t1.push(+(10 + u + r.normal(0, 0.6)).toFixed(3)); c.t2.push(+(10.3 + u + 0.5 * eff + r.normal(0, 0.9)).toFixed(3));
    c.t3.push(+(10.5 + u + eff + r.normal(0, 1.3)).toFixed(3)); c.t4.push(+(10.4 + u + 1.4 * eff + r.normal(0, 1.8)).toFixed(3));
  }
  c.t3[5] = NaN;
  SM.app.addTable(new SM.Table({ name: 'Repeated test', source: 'simulated', columns: [
    { name: 'subject', dataType: 'character', values: c.subject, role: 'label' },
    { name: 'group', dataType: 'character', values: c.group, valueOrder: ['control', 'low', 'high'] },
    { name: 'site', dataType: 'character', values: c.site },
    ...['t1', 't2', 't3', 't4'].map((k) => ({ name: k, dataType: 'numeric', values: c[k] })),
  ] }));
  return SM.app.current.nrows;
})()'''

RM_PAYLOAD = "{ y: ['t1', 't2', 't3', 't4'], effects: [{ names: ['group'], nest: [], random: false }], response: 'repeated' }"


async def repeated(page):
    """MANOVA's Repeated Measures (Choose Response and its dialog, Between and
    Within Subjects against the backend and the page's own ANOVA, Univariate
    Tests Also, Y Name, the red triangle, a project, By, Bootstrap, both
    themes, phone width) and the optional effect-size columns of the Effect
    Tests."""
    num = lambda s: float(str(s).replace('−', '-').replace('<', '').replace('*', ''))  # noqa: E731
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    check('the repeated-measures test table', await page.ev(RM_TABLE), 36)
    await page.ev(HELPERS)
    await page.ev('__fm.idle()', timeout=300)
    ys = ['t1', 't2', 't3', 't4']
    r = await page.ev(open_js(ys, E(['group']), {'personality': 'manova'}))
    await page.ev('__fm.idle()', timeout=300)
    check('MANOVA opens as before (Identity)', ([o for o in ('Response Specification', 'Whole Model', 'Intercept', 'group') if o in r['outlines']], 'Between Subjects' in r['outlines'], r['errors']),
          (['Response Specification', 'Whole Model', 'Intercept', 'group'], False, []))
    dlg_js = '''const s = __fm.outline('Response Specification').querySelector('select[aria-label="Choose Response"]');
      s.value = 'repeated'; s.dispatchEvent(new Event('change')); await new Promise(r => setTimeout(r, 300));
      const dlg = [...document.querySelectorAll('.sm-dialog')].find(x => x.getAttribute('aria-label') === 'Repeated Measures');'''
    r = await page.ev('''(async () => { const rep = __fm.rep(); const seq = rep.seq;
      ''' + dlg_js + '''
      const out = { opts: [...s.options].map(o => o.textContent), dlg: !!dlg, name: dlg && dlg.querySelector('input[type="text"]').value, uni: dlg && dlg.querySelector('input[type="checkbox"]').checked,
        labels: dlg ? [...dlg.querySelectorAll('.sm-form label')].map(l => l.textContent) : null, info: !!(dlg && dlg.querySelector('.info-btn')) };
      [...dlg.querySelectorAll('button')].find(b => b.textContent === 'Cancel').click(); await new Promise(r => setTimeout(r, 250));
      out.after = s.value; out.reran = rep.seq !== seq; out.open = !!document.querySelector('.sm-dialog[aria-label="Repeated Measures"]');
      return out; })()''')
    check('Choose Response lists Repeated Measures first, as JMP', r['opts'], ['Repeated Measures', 'Sum', 'Identity', 'Contrast', 'Polynomial', 'Mean'])
    check('Repeated Measures asks for the Y Name (Time) and Univariate Tests Also', (r['dlg'], r['name'], r['uni'], r['labels'], r['info']), (True, 'Time', False, ['Y Name', 'Univariate Tests Also'], True))
    check('Cancel keeps the response design and does not rerun', (r['after'], r['reran'], r['open']), ('identity', False, False))
    r = await page.ev('''(async () => { const rep = __fm.rep();
      ''' + dlg_js + '''
      dlg.querySelector('input[type="text"]').value = 'Visit'; dlg.querySelector('input[type="checkbox"]').checked = true;
      const d = __fm.done(rep); dlg.querySelector('.sm-dialog-foot .primary').click(); await d;
      const o = rep.spec.options; return { state: __fm.state(rep), opt: [o['manova|response'], o['manova|rmName'], o['manova|univariate']] }; })()''')
    want = ['Response Specification', 'Between Subjects', 'All Between', 'Intercept', 'group', 'Within Subjects', 'Sphericity Test', 'All Within Interactions', 'Visit', 'Visit*group']
    check('Repeated Measures: Between and Within Subjects, JMP\'s outlines', [o for o in r['state']['outlines'] if o in want], want)
    check('... no errors, and the options kept in the spec', (r['state']['errors'], r['opt']), ([], ['repeated', 'Visit', True]))
    r = await page.ev('''(async () => { const rep = __fm.rep(); const t = rep.table;
      const res = await SM.engine.call('fitmodel.manova', { ...''' + RM_PAYLOAD + ''', within: 'Visit' }, t);
      const ys = ['t1', 't2', 't3', 't4'].map(n => t.col(n).values), g = t.col('group').values;
      const rows = [...Array(t.nrows).keys()].filter(i => ys.every(v => Number.isFinite(v[i])));
      const s = rows.map(i => ys.reduce((a, v) => a + v[i], 0)), m = s.reduce((a, b) => a + b) / s.length;
      let ssb = 0, ssw = 0; const lv = [...new Set(rows.map(i => g[i]))];
      for (const l of lv) { const v = rows.map((i, k) => (g[i] === l ? s[k] : null)).filter(x => x != null); const ml = v.reduce((a, b) => a + b) / v.length; ssb += v.length * (ml - m) ** 2; for (const x of v) ssw += (x - ml) ** 2; }
      return { res, visit: __fm.table('Visit'), vg: __fm.table('Visit*group'), awi: __fm.table('All Within Interactions'), grp: __fm.table('group'), sph: __fm.kv('Sphericity Test'),
        notes: [...__fm.outline('Within Subjects').querySelectorAll(':scope > .sm-ob-body > .sm-ob-note')].map(x => x.textContent),
        spec: __fm.outline('Response Specification').querySelector('.sm-ob-note').textContent, oneway: (ssb / (lv.length - 1)) / (ssw / (s.length - lv.length)), n: rows.length }; })()''')
    res = r['res']
    wt = {t['effect']: t for t in res['within_tests']}
    check('Visit: an exact F Test and the three univariate rows, as JMP', [row[0] for row in r['visit']], ['Test', 'F Test', 'Univar unadj Epsilon', 'Univar G-G Epsilon', 'Univar H-F Epsilon'])
    check('... under JMP\'s headings', r['visit'][0], ['Test', 'Value', 'Exact F', 'NumDF', 'DenDF', 'Prob>F'])
    for k_, row in enumerate(wt['Visit']['rows'] + wt['Visit']['univariate']):
        check.near(f'Visit, {row["test"]}: the F shown = the backend\'s', num(r['visit'][k_ + 1][2]), row['f'], 1e-6)
        check.near(f'Visit, {row["test"]}: Value (λ; a univariate row\'s epsilon)', num(r['visit'][k_ + 1][1]), row['value'], 1e-6)
    check.near('Visit, G-G: the DenDF is the epsilon times ν p', num(r['visit'][3][4]), res['epsilon']['gg'] * res['dfe'] * 3, 1e-6)
    check('Visit*group: the four statistics (Approx. F) and the univariate rows', ([row[0] for row in r['vg']][1:], r['vg'][0][2]),
          (["Wilks' Lambda", "Pillai's Trace", 'Hotelling-Lawley', "Roy's Max Root", 'Univar unadj Epsilon', 'Univar G-G Epsilon', 'Univar H-F Epsilon'], 'Approx. F'))
    check('All Within Interactions = Visit*group with one effect', r['awi'][1], r['vg'][1])
    check.near('Between group: the Exact F = the one-way ANOVA of the subjects\' sums, computed in the page', num(r['grp'][1][2]), r['oneway'], 1e-6)
    check('... on 2 and 32 DF (35 subjects with every measurement)', (r['grp'][1][3], r['grp'][1][4], r['n']), ('2', '32', 35))
    check.near('Sphericity Test: Mauchly Criterion = the backend\'s', num(r['sph']['Mauchly Criterion']), res['sphericity']['w'], 1e-6)
    check('Sphericity Test: JMP\'s rows', list(r['sph']), ['Mauchly Criterion', 'ChiSquare', 'DF', 'Prob > Chisq'])
    check('the epsilon note gives Lecoutre\'s correction and the lower bound', any('Lecoutre' in x and 'lower bound' in x for x in r['notes']), True)
    check('the Response Specification says what is tested', ('the 4 levels of Visit' in r['spec'], '35 rows with every response' in r['spec']), (True, True))
    # the page's own univariate test of Visit, without between effects
    r = await page.ev(open_js(ys, [], {'personality': 'manova', 'manova|response': 'repeated', 'manova|rmName': 'Visit', 'manova|univariate': True}))
    js = await page.ev('''(() => { const t = SM.app.current; const ys = ['t1', 't2', 't3', 't4'].map(n => t.col(n).values);
      const rows = [...Array(t.nrows).keys()].filter(i => ys.every(v => Number.isFinite(v[i]))); const n = rows.length, k = 4;
      const g = rows.reduce((a, i) => a + ys.reduce((b, v) => b + v[i], 0), 0) / (n * k);
      const cm = ys.map(v => rows.reduce((a, i) => a + v[i], 0) / n), rm = rows.map(i => ys.reduce((a, v) => a + v[i], 0) / k);
      let sst = 0, sse = 0; ys.forEach((v, j) => { sst += n * (cm[j] - g) ** 2; rows.forEach((i, q) => { sse += (v[i] - rm[q] - cm[j] + g) ** 2; }); });
      return (sst / (k - 1)) / (sse / ((n - 1) * (k - 1))); })()''')
    vt = await page.ev("__fm.table('Visit')")
    check('no between effects: only the Intercept between, Visit within', ([o for o in r['outlines'] if o in ('All Between', 'Intercept', 'All Within Interactions', 'Visit')], r['errors']), (['Intercept', 'Visit'], []))
    check.near('Visit\'s univariate F = the two-way (subjects by visits) ANOVA computed in the page', num(vt[2][2]), js, 1e-6)
    await page.ev("SM.app.closeReport(__fm.rep())")
    # Univariate Tests Also off from the Response Specification; Y Name; the red triangle turns it on again
    r = await page.ev('''(async () => { const rep = __fm.rep(); let d = __fm.done(rep);
      const cb = __fm.outline('Response Specification').querySelector('input[aria-label="Univariate Tests Also"]'); cb.checked = false; cb.dispatchEvent(new Event('change')); await d;
      const off = { outlines: __fm.state(rep).outlines, visit: __fm.table('Visit').map(x => x[0]) };
      d = __fm.done(rep); const inp = __fm.outline('Response Specification').querySelector('input[aria-label="Y Name"]'); inp.value = 'Week'; inp.dispatchEvent(new Event('change')); await d;
      const named = __fm.state(rep).outlines;
      d = __fm.done(rep); await __fm.topMenu('Univariate Tests Also'); await d;
      return { off, named, on: __fm.state(rep).outlines, week: __fm.table('Week').map(x => x[0]), errors: __fm.state(rep).errors }; })()''')
    check('Univariate Tests Also off: no Sphericity Test, only the F Test', ('Sphericity Test' in r['off']['outlines'], r['off']['visit']), (False, ['Test', 'F Test']))
    check('a new Y Name renames the within tests', [o for o in r['named'] if o.startswith('Week')], ['Week', 'Week*group'])
    check('the red triangle\'s Univariate Tests Also turns them on again', ('Sphericity Test' in r['on'], r['week'][-1], r['errors']), (True, 'Univar H-F Epsilon', []))
    # a project keeps the design; By gives each level its repeated measures
    r = await page.ev('''(async () => { const t = SM.app.current; const before = __fm.table('Week');
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [__fm.rep().toJSON()] };
      const n = SM.app.reports.length; SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const rep = SM.app.reports[n]; await __fm.done(rep);
      const out = { title: rep.title, errors: __fm.state(rep).errors, same: JSON.stringify(__fm.table('Week', 0, rep)) === JSON.stringify(before), sph: !!__fm.outline('Sphericity Test', rep) };
      SM.app.showTab(SM.app.tabOf(t)); return out; })()''')
    check('a project reopens the repeated measures with its Y Name and univariate tests', (r['title'], r['errors'], r['same'], r['sph']), ('Manova Fit', [], True, True))
    r = await page.ev(open_js(ys, E(['group']), {'personality': 'manova', 'manova|response': 'repeated', 'manova|univariate': True}, {'by': ['site']}))
    check('By site: a repeated-measures report per level, no errors', ([o for o in r['outlines'] if o.startswith('Manova Fit')], r['outlines'].count('Sphericity Test'), r['errors']),
          (['Manova Fit site=A', 'Manova Fit site=B'], 2, []))
    await page.ev("SM.app.closeReport(__fm.rep())")
    # Bootstrap reruns the report on resampled subjects: sample 1 is the backend on its rows
    r = await page.ev('''(async () => { const rep = SM.app.reports.filter(x => x.platform.id === 'fitmodel' && x.table.name === 'Repeated test').pop();
      SM.app.showTab(SM.app.tabOf(rep)); await new Promise(r => setTimeout(r, 100));
      const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim() === 'Week');
      const tbl = h.parentElement.querySelector('table.sm-rt');
      const res = await SM.bootstrap.run(tbl, tbl._rt.columns.find(c => c.label === 'Exact F'), { B: 3, seed: 21, show: false });
      const rows = SM.bootstrap.sampler(rep.groups()[0].rows, 21)();
      const own = await SM.engine.call('fitmodel.manova', { ...''' + RM_PAYLOAD + ''', within: 'Week', rows }, rep.table);
      const w = own.within_tests.find(x => x.effect === 'Week');
      const out = { cols: res.columns.map(c => c.name), b0: res.col('F Test').values[0], b1: res.col('F Test').values[1], gg1: res.col('Univar G-G Epsilon').values[1],
        own: w.rows[0].f, ownU: w.univariate[1].f, report: tbl._rt.rows[0].f };
      SM.app.closeTable(res); return out; })()''', timeout=300)
    check('Bootstrap of a within test: its rows are the tests', r['cols'], ['BootID', 'F Test', 'Univar unadj Epsilon', 'Univar G-G Epsilon', 'Univar H-F Epsilon'])
    check.near('... sample 0 is the report', r['b0'], r['report'], 1e-12)
    check.near('... sample 1 is fitmodel.manova on its rows (the render has no side effects)', r['b1'], r['own'], 1e-12)
    check.near('... and its univariate F', r['gg1'], r['ownU'], 1e-12)
    await asyncio.sleep(0.5)
    await shot(page, 'fm-21-repeated.png')
    # dark theme, phone width
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev('__fm.idle()', timeout=300)
    await shot(page, 'fm-22-repeated-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(1)
    check('the repeated-measures report: no horizontal page scroll at phone width', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, 'fm-23-repeated-phone.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await page.ev('__fm.idle()', timeout=300)

    # ---- the Effect Tests' optional effect sizes (right click, Columns) ----------------------------------------------
    await page.ev("SM.app.openExample('plants')")
    await page.ev(HELPERS)
    r = await page.ev(open_js('yield (g)', E(['fertilizer'], ['water'], ['light (h)'])))
    await page.ev('__fm.idle()', timeout=300)
    col_js = '''const ob = __fm.outline('Effect Tests'); const tbl = ob.querySelector('table.sm-rt');
      const note = [...ob.querySelectorAll('.sm-ob-note')].find(x => x.textContent.startsWith('Partial η²'));
      const pick = async (label) => { tbl.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 300, clientY: 300 })); await __fm.tick(); await __fm.menuItem('Columns', label); await __fm.tick();
        if (!tbl.isConnected) throw new Error('the report was redrawn under the test'); };'''
    r = await page.ev('''(async () => { ''' + col_js + '''
      const out = { head: __fm.table('Effect Tests')[0], hidden: note ? note.hidden : 'no note', info: !!ob.querySelector(':scope > .sm-ob-head .info-btn') };
      tbl.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 300, clientY: 300 })); await __fm.tick();
      const cols = [...document.querySelectorAll('.sm-menu button')].find(b => b.querySelector('.sm-label').textContent === 'Columns'); cols.dispatchEvent(new MouseEvent('mouseenter')); await __fm.tick();
      const menus = [...document.querySelectorAll('.sm-menu')]; out.items = [...menus[menus.length - 1].querySelectorAll('button .sm-label')].map(x => x.textContent); SM.ui.closeMenus();
      await pick('Partial η²'); out.eta = { head: __fm.table('Effect Tests')[0], rows: __fm.table('Effect Tests').slice(1), shown: !note.hidden };
      await pick('Partial ω²'); out.both = __fm.table('Effect Tests')[0];
      out.anova = __fm.table('Analysis of Variance'); out.n = __fm.kv('Summary of Fit')['Observations (or Sum Wgts)'];
      out.omega = __fm.table('Effect Tests').slice(1);
      await pick('Partial η²'); await pick('Partial ω²'); out.again = { head: __fm.table('Effect Tests')[0], hidden: note.hidden };
      out.text = note.textContent; return out; })()''')
    check('Effect Tests look as before: no effect sizes shown, the note hidden', (r['head'], r['hidden']), (['Source', 'Nparm', 'DF', 'Sum of Squares', 'F Ratio', 'Prob > F'], True))
    check('Effect Tests has an (i)', r['info'], True)
    check('the right-click Columns menu offers Partial η² and Partial ω²', r['items'], ['Partial η²', 'Partial ω²'])
    check('Columns > Partial η² shows it, and the note on the definitions', (r['eta']['head'][-1], r['eta']['shown']), ('Partial η²', True))
    sse = num([row for row in r['anova'] if row[0] == 'Error'][0][2])
    for row in r['eta']['rows']:
        ss = num(row[3])
        check.near(f'{row[0]}: Partial η² = SS/(SS + SSE) from the tables', num(row[-1]), ss / (ss + sse), 2e-4)
    nobs = num(r['n'])
    check('Partial ω² beside it', r['both'][-2:], ['Partial η²', 'Partial ω²'])
    for row in r['omega']:
        df, f = num(row[2]), num(row[4])
        check.near(f'{row[0]}: Partial ω² = DF(F − 1)/(DF(F − 1) + N)', num(row[-1]), df * (f - 1) / (df * (f - 1) + nobs), 2e-4)
    check('hiding both hides the note again', (r['again']['head'], r['again']['hidden']), (['Source', 'Nparm', 'DF', 'Sum of Squares', 'F Ratio', 'Prob > F'], True))
    check('the note names the references', ('Cohen 1973' in r['text'], 'Olejnik and Algina 2003' in r['text']), (True, True))
    r = await page.ev('''(async () => { const rep = __fm.rep(); const ob = __fm.outline('Effect Tests'); const tbl = ob.querySelector('table.sm-rt');
      const res = await SM.bootstrap.run(tbl, tbl._rt.all.find(c => c.key === 'pes'), { B: 3, seed: 5, show: false });
      const rows = SM.bootstrap.sampler(rep.groups()[0].rows, 5)();
      const own = await SM.engine.call('fitmodel.ls', { y: 'yield (g)', effects: ['fertilizer', 'water', 'light (h)'].map(n => ({ names: [n], nest: [], random: false })), rows }, rep.table);
      const out = { b1: res.col('water').values[1], own: own.effect_tests.rows.find(x => x.source === 'water').pes, b0: res.col('water').values[0], report: tbl._rt.rows.find(x => x.source === 'water').pes };
      SM.app.closeTable(res); return out; })()''', timeout=300)
    check.near('Bootstrap of Partial η² (a hidden column): sample 0 is the report', r['b0'], r['report'], 1e-12)
    check.near('... sample 1 is fitmodel.ls on its rows', r['b1'], r['own'], 1e-12)
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) of the repeated-measures and effect-test reports has a topic', audit.get('noTopic'), [])


# Read the (i) panels: the open panel's title and sections, each with its
# heading, its choices [name, text] and its paragraphs.
HELP_JS = r"""
window.__help = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  panel() {
    const p = document.querySelector('.info-panel');
    if (!p) return null;
    const out = { title: p.querySelector('.info-panel-title').textContent, sections: [] };
    let cur = { heading: '', choices: [], text: [] };
    out.sections.push(cur);
    for (const n of p.querySelector('.info-panel-body').children) {
      if (n.tagName === 'H3') { cur = { heading: n.textContent, choices: [], text: [] }; out.sections.push(cur); }
      else if (n.tagName === 'DL' && n.classList.contains('info-choices')) for (const dt of n.querySelectorAll('dt')) cur.choices.push([dt.textContent, dt.nextElementSibling ? dt.nextElementSibling.textContent : '']);
      else cur.text.push(n.textContent);
    }
    return out;
  },
  async read(btn) { if (!btn) return null; btn.click(); await this.sleep(150); const r = this.panel(); KvotInfo.close(); await this.sleep(40); return r; },
  names(p, heading) { const s = p && p.sections.find((x) => x.heading === heading); return s ? s.choices.map((c) => c[0]) : null; },
  // the shortest text of a section's choices, without what a role takes '(required, ...)'
  shortest(p, heading) { const s = p && p.sections.find((x) => x.heading === heading); return s && s.choices.length ? Math.min(...s.choices.map((c) => c[1].replace(/\s*\([^()]*\)$/, '').length)) : 0; },
  dialog() { return [...document.querySelectorAll('.sm-dialog')].pop(); },
  // the launch dialog's (i), with the audit while it is open
  async launch(id, setup) {
    SM.app.launch(id); await this.sleep(350);
    const d = [...document.querySelectorAll('.sm-launch-dialog')].pop();
    if (setup) await setup(d);
    await this.sleep(100);
    const audit = KvotInfo.audit();
    const p = await this.read(d.querySelector('.sm-dialog-head .info-btn'));
    return { d, p, noTopic: audit.noTopic, slots: audit.slots };
  },
  // an outline's red triangle down a path of labels (the last one is clicked)
  async menu(title, path, rep) {
    rep = rep || SM.app.reports[SM.app.reports.length - 1];
    const h = [...rep.body.querySelectorAll('.sm-ob-head')].find((x) => x.querySelector('h2, h3, h4').textContent === title);
    if (!h) throw new Error('no outline ' + title);
    h.querySelector('.sm-ob-menu').click();
    for (const label of path) {
      await this.sleep(60);
      const m = [...document.querySelectorAll('.sm-menu')].pop();
      const b = m && [...m.querySelectorAll('button')].find((x) => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === label);
      if (!b) { SM.ui.closeMenus(0); throw new Error('no menu item ' + label); }
      b.click();
    }
  },
  // the form a menu item opened: its field labels, its (i) and the audit while it is open; then Cancel
  async form() {
    let d = null;
    for (let i = 0; i < 60 && !(d && d.querySelector('.sm-form')); i++) { await this.sleep(50); d = this.dialog(); }
    if (!d) throw new Error('no form');
    const labels = [...d.querySelectorAll('.sm-form label')].map((l) => l.textContent);
    const audit = KvotInfo.audit();
    const p = await this.read(d.querySelector('.sm-dialog-head .info-btn'));
    [...d.querySelectorAll('.sm-dialog-foot .sm-btn')].find((b) => b.textContent === 'Cancel').click();
    await this.sleep(60);
    return { labels, p, fields: this.names(p, 'Fields'), shortest: this.shortest(p, 'Fields'), noTopic: audit.noTopic };
  },
  // an outline's (i) in the last report
  async outline(title, rep) {
    rep = rep || SM.app.reports[SM.app.reports.length - 1];
    const h = [...rep.body.querySelectorAll('.sm-ob-head')].find((x) => x.querySelector('h2, h3, h4').textContent === title);
    return h ? this.read(h.querySelector('.kvot-info-slot .info-btn')) : null;
  },
};
"""


async def help_inputs(page):
    """What every input is for, in the (i) panels: the launch dialog's roles
    and its Construct Model Effects part (as the personality shows its
    fields), the red-triangle forms' fields, and the controls inside the
    reports (Effect Summary, Stepwise, Regression Diagnostics, Recursive and
    Rolling Regression, the profilers, MANOVA, Generalized Regression and
    Quantile Regression's Model Launch)."""
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await page.ev("SM.app.openExample('students')")
    await page.ev(HELPERS)
    await page.ev(HELP_JS)
    # the roles the dialog shows: a personality shows its own (GEE's Subject, Time, Subgroup)
    roles = ['Y', 'Weight', 'Freq', 'Validation', 'By']
    effects = ['Model effects', 'Add', 'Cross', 'Nest', 'Macros', 'Degree', 'Attributes', 'Remove', 'No Intercept']
    r = await page.ev('''(async () => {
      const heading = 'Personality and model effects';
      const pers = (d, v) => { const ps = d.querySelector('select[aria-label="Personality"]'); ps.value = v; ps.dispatchEvent(new Event('change')); };
      const a = await __help.launch('fitmodel', async (d) => { __fm.pick('height (cm)'); __fm.role('Y'); });
      const out = { roles: __help.names(a.p, 'Roles'), rolesShort: __help.shortest(a.p, 'Roles'), sls: __help.names(a.p, heading), short: __help.shortest(a.p, heading), noTopic: a.noTopic, slots: a.slots };
      pers(a.d, 'gee'); await __help.sleep(50);
      const gp = await __help.read(a.d.querySelector('.sm-dialog-head .info-btn'));
      out.gee = __help.names(gp, heading);
      out.geeRoles = __help.names(gp, 'Roles');
      const dist = a.d.querySelector('select[aria-label="Distribution"]'); dist.value = 'tweedie'; dist.dispatchEvent(new Event('change')); await __help.sleep(50);
      out.tweedie = __help.names(await __help.read(a.d.querySelector('.sm-dialog-head .info-btn')), heading);
      pers(a.d, 'quantreg'); await __help.sleep(50);
      out.qr = __help.names(await __help.read(a.d.querySelector('.sm-dialog-head .info-btn')), heading);
      pers(a.d, 'ordinal'); await __help.sleep(50);
      out.ordinal = __help.names(await __help.read(a.d.querySelector('.sm-dialog-head .info-btn')), heading);
      out.noTopic2 = KvotInfo.audit().noTopic;
      __fm.btn('Cancel', a.d);
      return out; })()''')
    if isinstance(r, str):
        print(r)
    check('the launch dialog\'s (i) lists every role it shows', r['roles'], roles)
    check('... and GEE\'s roles once GEE is the personality', [x for x in r['geeRoles'] if x in ('Subject', 'Time', 'Subgroup', 'Endogenous')], ['Subject', 'Time', 'Subgroup'])
    check('... each with what it is for, beyond what it takes', r['rolesShort'] > 60, True)
    check('... and the personality and model-effects fields of Standard Least Squares', r['sls'], ['Personality', 'Emphasis'] + effects)
    check('... each explained', r['short'] > 30, True)
    check('GEE: its fields as they show', r['gee'], ['Personality', 'Distribution', 'Link Function', 'Working Correlation', 'Covariance', 'Scale'] + effects)
    check('GEE with the Tweedie: its power', r['tweedie'][:3], ['Personality', 'Distribution', 'Power'])
    check('Quantile Regression: the quantile', r['qr'], ['Personality', 'Quantile τ'] + effects)
    check('Ordinal Logistic: the link', r['ordinal'], ['Personality', 'Link'] + effects)
    check('every (i) of the open launch dialog has a topic (three of its own)', (r['noTopic'], r['noTopic2'], r['slots'] >= 3), ([], [], True))

    # ---- red-triangle forms: Newey–West HAC, Cluster, LSMeans Contrast; the Effect Summary's controls
    r = await page.ev(open_js('weight (kg)', E(['height (cm)'], ['sex'])))
    check('a least squares report to work on', r['errors'] if isinstance(r, dict) else r, [])
    r = await page.ev('''(async () => {
      const top = __fm.rep().body.querySelector('.sm-ob.level-0 > .sm-ob-head h2, .sm-ob.level-0 > .sm-ob-head h3').textContent;
      const out = {};
      await __help.menu(top, ['Robust Standard Errors', 'Newey–West HAC…']); out.hac = await __help.form();
      await __help.menu(top, ['Robust Standard Errors', 'Cluster…']); out.cluster = await __help.form();
      await __help.menu('sex', ['LSMeans Contrast…']); out.contrast = await __help.form();
      out.summary = __help.names(await __help.outline('Effect Summary'), 'Editing the model');
      return out; })()''')
    if isinstance(r, str):
        print(r)
    check('Newey–West HAC\'s (i): the robust topic, then its field', (r['hac']['p']['title'], r['hac']['fields'], r['hac']['shortest'] > 60), ('Robust Standard Errors', ['Maximum lag'], True))
    check('Cluster\'s (i): its field', (r['cluster']['fields'], r['cluster']['shortest'] > 60), (['Cluster by'], True))
    check('LSMeans Contrast: one entry for the weights of the levels', (r['contrast']['labels'], r['contrast']['fields']), (['F', 'M'], ['The weight of each level']))
    check('every (i) of the open forms has a topic', [x['noTopic'] for x in (r['hac'], r['cluster'], r['contrast'])], [[], [], []])
    check('the Effect Summary\'s (i) explains its controls', r['summary'], ['An effect\'s line', 'Remove', 'Edit', 'Undo', 'FDR'])

    # ---- Regression Diagnostics' settings, Recursive and Rolling Regression's, the profilers'
    r = await page.ev('''(async () => {
      const rep = __fm.rep();
      const top = rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head h2, .sm-ob.level-0 > .sm-ob-head h3').textContent;
      let d = __fm.done(rep); await __help.menu(top, ['Regression Diagnostics', 'Goldfeld–Quandt Test']); await d;
      d = __fm.done(rep); await __help.menu(top, ['Recursive and Rolling Regression', 'Recursive Estimates']); await d;
      d = __fm.done(rep); await __help.menu(top, ['Factor Profiling', 'Profiler']); await d;
      const rd = await __help.outline('Regression Diagnostics'), rr = await __help.outline('Recursive and Rolling Regression'), pr = await __help.outline('Prediction Profiler');
      const out = { rd: __help.names(rd, 'The settings above a test'), rr: __help.names(rr, 'The settings above the plots'), prof: __help.names(pr, 'Prediction Profiler'),
        shared: pr ? pr.sections.map((s) => s.heading) : null, contour: __help.names(pr, 'Contour Profiler'), maximize: (__help.names(pr, 'Its red triangle') || []).includes('Maximize Desirability') };
      await __help.menu('Recursive and Rolling Regression', ['Order Rows By…']); out.order = await __help.form();
      await __help.menu('Recursive and Rolling Regression', ['Rolling Window…']); out.window = await __help.form();
      out.noTopic = KvotInfo.audit().noTopic;
      return out; })()''')
    if isinstance(r, str):
        print(r)
    check('Regression Diagnostics\' (i): the settings above the tests', r['rd'], ['Sort by (Goldfeld–Quandt)', 'Leave out the middle', 'Alternative', 'Powers of the predicted (RESET)', 'Order (Harvey–Collier)', 'Central rows by (Rainbow)', 'Central fraction', 'Lags (Breusch–Godfrey)'])
    check('Recursive and Rolling Regression\'s (i): its settings', r['rr'], ['Order by', 'Significance', 'Window'])
    check('... and its forms\' fields', (r['order']['fields'], r['window']['fields']), (['Order by'], ['Rows in a window']))
    check('the Prediction Profiler\'s (i): its controls', r['prof'], ['The red dashed line', 'A click in a plot', 'The value box', 'The slider', 'The desirability plots'])
    check('... then the shared profiler\'s red triangle, the Contour Profiler\'s controls', (r['maximize'], r['contour']), (True, ['Horizontal, Vertical', 'Response', 'The other factors']))
    check('every (i) of these reports has a topic', r['noTopic'], [])

    # ---- Stepwise's controls; MANOVA's Response Specification and the Repeated Measures form
    r = await page.ev(open_js('weight (kg)', E(['height (cm)'], ['sex'], ['age']), {'personality': 'stepwise'}))
    check('a stepwise report', r['errors'] if isinstance(r, dict) else r, [])
    r = await page.ev('''(async () => {
      const c = await __help.outline('Stepwise Regression Control'), e = await __help.outline('Current Estimates');
      return { ctl: __help.names(c, 'Stepwise Regression Control'), cur: __help.names(e, 'Current Estimates') }; })()''')
    check('Stepwise Regression Control\'s (i): every control', r['ctl'], ['Stopping Rule', 'Direction', 'Rules', 'Prob to Enter', 'Prob to Leave', 'Go', 'Step', 'Enter All', 'Remove All', 'Make Model', 'Run Model'])
    check('Current Estimates has an (i) for its boxes', r['cur'], ['Lock', 'Entered', 'F Ratio, Prob>F'])
    r = await page.ev(open_js(['height (cm)', 'weight (kg)'], E(['sex']), {'personality': 'manova'}))
    r = await page.ev('''(async () => {
      const spec = __help.names(await __help.outline('Response Specification'), 'Response Specification');
      const s = __fm.outline('Response Specification').querySelector('select[aria-label="Choose Response"]');
      s.value = 'repeated'; s.dispatchEvent(new Event('change'));
      const f = await __help.form();
      return { spec, form: f.fields, back: s.value }; })()''')
    check('Response Specification\'s (i): its controls', r['spec'], ['Choose Response', 'Y Name', 'Univariate Tests Also'])
    check('the Repeated Measures form lists its fields; Cancel keeps the response', (r['form'], r['back']), (['Y Name', 'Univariate Tests Also'], 'identity'))

    # ---- Generalized Regression's and Quantile Regression's Model Launch
    r = await page.ev(open_js('weight (kg)', E(['height (cm)'], ['sex'], ['age']), {'personality': 'genreg'}))
    check('a Generalized Regression report', r['errors'] if isinstance(r, dict) else r, [])
    r = await page.ev('''(async () => ({ launch: __help.names(await __help.outline('Model Launch'), 'Model Launch'), path: __help.names(await __help.outline('Solution Path'), 'Choosing a model') }))()''')
    check('Generalized Regression\'s Model Launch (i): every control', r['launch'], ['Distribution', 'Estimation Method', 'Adaptive', 'Validation Method', 'Elastic Net Alpha', 'Number of Folds', 'Holdback Proportion', 'Random Seed'])
    check('the Solution Path\'s (i): how to choose a model', r['path'], ['The red line', 'A point', 'The dotted line', 'Reset to the Best Model'])
    r = await page.ev(open_js('weight (kg)', E(['height (cm)']), {'personality': 'quantreg', 'qrTau': 0.5}))
    check('a Quantile Regression report', r['errors'] if isinstance(r, dict) else r, [])
    r = await page.ev('''(async () => __help.names(await __help.outline('Model Launch'), 'Model Launch'))()''')
    check('Quantile Regression\'s Model Launch (i): every control', r, ['Quantile τ', 'Standard Errors', 'Kernel', 'Bandwidth', 'Quantile Process'])
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', (audit.get('noTopic'), audit.get('brokenMore')), ([], []))


asyncio.run(main())
sys.exit(check.done())
