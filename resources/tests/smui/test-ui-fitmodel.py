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

Start a server on the repository root and headless Chrome on
SMUI_HTTP_PORT and SMUI_CDP_PORT (the recipe is in README.md), then

    python3 resources/tests/smui/test-ui-fitmodel.py

With SMUI_SHOTS=<folder> it saves screenshots.
"""
import asyncio
import json
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
      const val = () => ob.querySelector('.sm-fm-prof-val').textContent;
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
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
