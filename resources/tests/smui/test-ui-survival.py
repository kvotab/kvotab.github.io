#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Reliability and Survival
(Life Distribution, Survival, Fit Parametric Survival, Fit Proportional
Hazards) and Analyze > Specialized Modeling (Fit Curve, Nonlinear).

The menus list the platforms in JMP's order; Survival's launch dialog casts
the columns; its report shows the counts and the median that a product-limit
estimate written in the page gives; a click on a censored tick selects its
row and a table selection lights up the ticks; the red triangle adds plots
and fits and Save Estimates makes a table; By gives a report per level; Fit
Proportional Hazards saves risk scores; Life Distribution's check boxes,
scale and calculator redraw it; Fit Curve adds a model from its red triangle
and saves predictions that are the curve; Nonlinear's dialog takes a typed
model, finds its parameters and reproduces NIST's certified Misra1a values;
every red-triangle item of these reports is built without an error; every
(i) has a topic; the reports draw in the dark theme and at phone width.

Start a server on the repository root and headless Chrome (the recipe is in
README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-survival.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import math
import os
import re
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine
from test_charts import GRAPHS_JS, close, maxdiff, run_graph

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


# Pick an item from an outline's red triangle: path is the labels down the
# submenus. wait: wait for the report to run again.
PICK = '''
(async (title, path, wait) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h2, h3, h4').textContent.trim() === title);
  if (!head) throw new Error('no outline ' + title);
  head.querySelector('.sm-ob-menu').click();
  await new Promise(r => setTimeout(r, 60));
  let done = null;
  for (let i = 0; i < path.length; i++) {
    const menus = [...document.querySelectorAll('.sm-menu')];
    const m = menus[menus.length - 1];
    const b = [...m.querySelectorAll('button')].find(x => x.querySelector('.sm-label').textContent === path[i]);
    if (!b) throw new Error('no item ' + path[i] + ' in ' + [...m.querySelectorAll('.sm-label')].map(x => x.textContent).join(' | '));
    if (i === path.length - 1 && wait) done = new Promise(res => rep.on('done', res));
    b.click();
    await new Promise(r => setTimeout(r, 80));
  }
  if (done) await done;
  return [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
})
'''


def pick_js(title, path, wait=True):
    return f'({PICK})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(wait)})'


# Open every red triangle of the last report and every submenu in it, as
# a click does: their items are built, none is run.
TRIANGLES = '''
(async () => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  let items = 0, subs = 0;
  const errors = [];
  const btns = [...rep.body.querySelectorAll('.sm-ob-menu')];
  for (const btn of btns) {
    try {
      btn.click();
      await new Promise(r => setTimeout(r, 20));
      const menus = [...document.querySelectorAll('.sm-menu')];
      const top = menus[menus.length - 1];
      if (!top) { errors.push('no menu'); continue; }
      const bs = [...top.querySelectorAll('button')];
      items += bs.length;
      for (const b of bs.filter(x => x.classList.contains('sm-sub'))) {
        b.click();
        await new Promise(r => setTimeout(r, 20));
        const all = [...document.querySelectorAll('.sm-menu')];
        subs += all[all.length - 1].querySelectorAll('button').length;
      }
    } catch (e) { errors.push(String(e)); }
    SM.ui.closeMenus(0);
  }
  return { triangles: btns.length, items, subs, errors };
})()
'''


async def triangles(page, name, least):
    r = await page.ev(TRIANGLES)
    ok = isinstance(r, dict) and not r['errors'] and r['triangles'] >= least and r['items'] > r['triangles']
    check(f'every red triangle of {name} opens, with its submenus', ok, True)
    if not ok:
        print('   ', r)


async def main():
    page = await open_page(f'{BASE}/smui.html?example=clinical', height=1100)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => ["survival", "nonlinear"].includes(f.module)).map(f => f.module + ": " + f.error)')
    check('survival.py and nonlinear.py import in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])

    # ---- the menus
    menus = await page.ev('''(() => {
      const an = SM.app.menuItems('Analyze');
      const sub = (label) => { const it = an.find(i => i.label === label); return it ? (typeof it.submenu === 'function' ? it.submenu() : it.submenu).map(i => i.separator ? '—' : i.label) : null; };
      return { rs: sub('Reliability and Survival'), sm: sub('Specialized Modeling') };
    })()''')
    check('Reliability and Survival, in JMP\'s order', [x for x in menus['rs'] if x != '—'][:4] == ['Life Distribution…', 'Survival…', 'Fit Parametric Survival…', 'Fit Proportional Hazards…'], True)
    check('Specialized Modeling lists Fit Curve and Nonlinear', [x for x in (menus['sm'] or []) if x in ('Fit Curve…', 'Nonlinear…')], ['Fit Curve…', 'Nonlinear…'])

    # ---- Survival through its launch dialog
    r = await page.ev('''(async () => {
      SM.app.launch('survival');
      await new Promise(r => setTimeout(r, 200));
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const cast = (name, role) => {
        items.forEach(li => li.classList.remove('is-selected'));
        const li = items.find(x => x.textContent === name);
        li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === role).click();
      };
      cast('months', 'Y, Time to Event'); cast('treatment', 'Grouping'); cast('censored', 'Censor');
      const code = [...dlg.querySelectorAll('.sm-launch-opts label')].find(l => l.textContent.startsWith('Censor Code')).querySelector('input').value;
      const roles = [...dlg.querySelectorAll('.sm-role-list')].map(u => u.textContent);
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { code, roles, title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3')].map(h => h.textContent),
               errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent) };
    })()''')
    check('Censor Code defaults to 1', r['code'], '1')
    check('roles cast', r['roles'][:3], ['months', 'treatment', 'censored'])
    check('report title', r['title'], 'Product-Limit Survival Fit')
    check('Survival outlines', r['outlines'], ['Product-Limit Survival Fit', 'Survival Plot', 'Summary', 'Tests Between Groups', 'Product-Limit Survival Estimates'])
    check('no errors in the report', r['errors'], [])
    # the counts and the median, from a product-limit estimate written here
    js = await page.ev('''(() => {
      const t = SM.app.current; const T = t.col('months').values, C = t.col('censored').values, G = t.col('treatment').values;
      const km = (rows) => {
        const d = rows.map(r => [T[r], C[r] === 1 ? 0 : 1]).sort((a, b) => a[0] - b[0]);
        let n = d.length, s = 1, med = null, i = 0;
        while (i < d.length) { const u = d[i][0]; let dd = 0, m = 0; while (i < d.length && d[i][0] === u) { dd += d[i][1]; m++; i++; } if (dd) { s *= 1 - dd / n; if (med == null && s < 0.5) med = u; } n -= m; }
        return { failed: rows.filter(r => C[r] !== 1).length, censored: rows.filter(r => C[r] === 1).length, median: SM.util.fmt(med) };
      };
      const all = Array.from({ length: t.nrows }, (_, i) => i);
      return ['placebo', 'drug'].map(g => km(all.filter(r => G[r] === g)));
    })()''')
    summ = await page.ev(table_under_js('Summary', 0))
    quant = await page.ev(table_under_js('Summary', 1))
    check('Summary rows: Combined, then the groups', [row[0] for row in summ[1:]], ['Combined', 'placebo', 'drug'])
    check('numbers failed and censored as counted in the page', [[row[1], row[2]] for row in summ[2:]], [[str(g['failed']), str(g['censored'])] for g in js])
    check('medians as a product-limit estimate in the page gives', [row[1] for row in quant[2:]], [g['median'] for g in js])
    tests = await page.ev(table_under_js('Tests Between Groups'))
    check('tests between groups', [row[0] for row in tests[1:]], ['Log-Rank', 'Wilcoxon', 'Tarone-Ware', 'Fleming-Harrington (ρ = 1)'])
    await shot(page, 'survival-01.png')

    # ---- linking: a censored tick selects its row, a table selection shows on the ticks
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => p.opts.title === 'months survival plot');
      const i = p.traces.findIndex(tr => tr.name === 'placebo censored');
      const row = p.rows[i][0];
      p._click({ points: [{ curveNumber: i, pointNumber: 0 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[i][1], p.rows[i][2]]);
      await new Promise(r => setTimeout(r, 150));
      const sp = p.box.data[i].selectedpoints;
      const cens = t.col('censored').values[row];
      t.select([]);
      return { sel, row, cens, sp };
    })()''')
    check('a click on a censored tick selects that row', r['sel'], [r['row']])
    check('the tick is a censored row', r['cens'], 1)
    check('a table selection highlights the ticks', r['sp'], [1, 2])

    # ---- the red triangle: plots, fits, estimates; Save Estimates
    out = await page.ev(pick_js('Product-Limit Survival Fit', ['Weibull Fit']))
    check('Weibull Fit from the red triangle', 'Weibull Fit' in out, True)
    out = await page.ev(pick_js('Product-Limit Survival Fit', ['Weibull Plot']))
    check('Weibull Plot from the red triangle', 'Weibull Plot' in out, True)
    out = await page.ev(pick_js('Product-Limit Survival Fit', ['Plot Options', 'Show Confid Interval']))
    wf = await page.ev(table_under_js('Weibull Fit', 0))
    check('Weibull parameters per group', [row[1] for row in wf[1:5]], ['α (scale)', 'β (shape)', 'λ (extreme value location)', 'δ (extreme value scale)'])
    band = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => p.opts.title === 'months survival plot'); return p.traces.filter(t => t.fill === 'tonexty').length; })()''')
    check('Show Confid Interval draws a band per group', band, 2)
    n0 = await page.ev('SM.app.tables.length')
    await page.ev(pick_js('Product-Limit Survival Fit', ['Save Estimates'], wait=False))
    saved = await page.ev('(() => { const t = SM.app.tables[SM.app.tables.length - 1]; return { n: SM.app.tables.length, name: t.name, cols: t.columns.map(c => c.name), rows: t.nrows }; })()')
    check('Save Estimates makes a table', saved['n'], n0 + 1)
    check('its columns', saved['cols'], ['treatment', 'months', 'Survival', 'Failure', 'SurvStdErr', 'Lower 95%', 'Upper 95%', 'Number failed', 'Number censored', 'At Risk'])
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports[SM.app.reports.length - 1]))')
    await shot(page, 'survival-02-options.png')
    await triangles(page, 'Survival', 2)

    # ---- By
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Clinical study")))')
    r = await page.ev(open_report_js('survival', {'y': ['months'], 'censor': ['censored'], 'by': ['sex']}, {'censorCode': '1'}))
    check('By: one report per level', [o for o in r['outlines'] if o.startswith('Product-Limit Survival Fit')], ['Product-Limit Survival Fit sex=F', 'Product-Limit Survival Fit sex=M'])
    check('By: no errors', r['errors'], [])

    # ---- Fit Proportional Hazards
    r = await page.ev(open_report_js('phreg', {'y': ['months'], 'censor': ['censored'], 'x': ['treatment', 'age']}, {'censorCode': '1'}))
    check('Proportional Hazards outlines', r['outlines'], ['Proportional Hazards Fit', 'Whole Model', 'Parameter Estimates', 'Effect Likelihood Ratio Tests', 'Risk Ratios', 'Baseline Survival'])
    check('no errors', r['errors'], [])
    pe = await page.ev(table_under_js('Parameter Estimates'))
    check('terms, effect coded', [row[0] for row in pe[1:]], ['treatment[placebo]', 'age'])
    await page.ev(pick_js('Proportional Hazards Fit', ['Save Risk Scores'], wait=False))
    rs = await page.ev('(() => { const t = SM.app.tables.find(t => t.name === "Clinical study"); const c = t.columns[t.columns.length - 1]; return { name: c.name, n: c.values.filter(Number.isFinite).length }; })()')
    check('Save Risk Scores adds a column for every row', rs, {'name': 'Risk Score months', 'n': 200})
    await triangles(page, 'Proportional Hazards', 3)

    # ---- Life Distribution
    r = await page.ev(open_report_js('lifedist', {'y': ['months'], 'censor': ['censored']}, {'censorCode': '1'}))
    check('Life Distribution title', r['title'], 'Life Distribution - months')
    check('its outlines', [o for o in r['outlines'] if not o.startswith('Covariance')][:8], ['Life Distribution - months', 'Compare Distributions', 'Statistics', 'Summary of Data', 'Nonparametric Estimate',
                                                                                              'Parametric Estimate - Weibull', 'Parametric Estimate - Lognormal', 'Model Comparisons'])
    check('no errors', r['errors'], [])
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const box = [...rep.body.querySelectorAll('.sm-life-dists input[type=checkbox]')].find(i => i.getAttribute('aria-label') === 'Show Loglogistic');
      let done = new Promise(res => rep.on('done', res));
      box.checked = true; box.dispatchEvent(new Event('change'));
      await done;
      const radio = [...rep.body.querySelectorAll('.sm-life-dists input[type=radio]')].find(i => i.getAttribute('aria-label') === 'Lognormal scale');
      done = new Promise(res => rep.on('done', res));
      radio.checked = true; radio.dispatchEvent(new Event('change'));
      await done;
      const inp = rep.body.querySelector('.sm-life-calc input[aria-label="Times"]');
      done = new Promise(res => rep.on('done', res));
      inp.value = '12, 24'; inp.dispatchEvent(new Event('change'));
      await done;
      const p = rep.plots.find(p => /probability plot/.test(p.opts.title));
      return { dists: rep.spec.options.dists, scale: rep.spec.options.scale, title: p.opts.title, lines: p.traces.filter(t => t.mode === 'lines' && t.name).map(t => t.name),
               heads: [...rep.body.querySelectorAll('.sm-ob-head h4')].map(h => h.textContent) };
    })()''')
    check('a check box adds a distribution', r['dists'], ['weibull', 'lognormal', 'loglogistic'])
    check('a radio button sets the scale', (r['scale'], r['title']), ('lognormal', 'months Lognormal probability plot'))
    check('the fitted lines on the plot', r['lines'], ['Weibull', 'Lognormal', 'Loglogistic'])
    calc = await page.ev(table_under_js('Distribution Calculator', 0))
    check('the calculator: two times for three distributions', len(calc) - 1, 6)
    await shot(page, 'survival-03-life.png')
    await page.ev(pick_js('Life Distribution - months', ['Fit All Distributions']))
    comp = await page.ev(table_under_js('Model Comparisons'))
    check('Fit All Distributions: nine in the comparison', len(comp) - 1, 9)
    await triangles(page, 'Life Distribution', 10)

    # ---- Fit Parametric Survival
    r = await page.ev(open_report_js('parametric', {'y': ['months'], 'censor': ['censored'], 'x': ['treatment', 'age']}, {'censorCode': '1', 'dist': 'weibull'}))
    check('Parametric Survival outlines', r['outlines'], ['Parametric Survival Fit: Weibull', 'Whole Model Test', 'Parameter Estimates', 'Effect Likelihood Ratio Tests'])
    out = await page.ev(pick_js('Parametric Survival Fit: Weibull', ['Distribution', 'Lognormal']))
    check('Distribution switches the family', out[0], 'Parametric Survival Fit: Lognormal')

    # ---- Fit Curve on a table made here
    await page.ev('''(() => {
      const r = SM.util.rng('fit-curve-test');
      const dose = [], resp = [], batch = [];
      const shift = { A: 4, B: 5, C: 6.5 };
      for (const g of ['A', 'B', 'C']) for (let i = 0; i < 25; i++) { const x = 10 * i / 24; dose.push(x); batch.push(g); resp.push(2 + 10 / (1 + Math.exp(-1.2 * (x - shift[g]))) + r.normal(0, 0.3)); }
      SM.app.addTable(new SM.Table({ name: 'Dose response', columns: [{ name: 'dose', dataType: 'numeric', values: dose }, { name: 'response', dataType: 'numeric', values: resp }, { name: 'batch', dataType: 'character', values: batch }] }));
    })()''')
    r = await page.ev(open_report_js('fitcurve', {'y': ['response'], 'x': ['dose'], 'group': ['batch']}, {'first': 'logistic4'}))
    check('Fit Curve with a first model', [o for o in r['outlines'] if o in ('Plot', 'Model Comparison', 'Logistic 4P', 'Parameter Estimates')], ['Plot', 'Model Comparison', 'Logistic 4P', 'Parameter Estimates'])
    check('no errors', r['errors'], [])
    out = await page.ev(pick_js('Fit Curve', ['Sigmoid Curves', 'Gompertz 4P']))
    check('a second model from the red triangle', 'Gompertz 4P' in out, True)
    out = await page.ev(pick_js('Logistic 4P', ['Test Parallelism']))
    par = await page.ev(table_under_js('Test Parallelism', 0))
    check('Test Parallelism: an F ratio and its p-value', [row[0] for row in par[:4]], ['F Ratio', 'DF Num', 'DF Den', 'Prob > F'])
    await page.ev(pick_js('Logistic 4P', ['Save Prediction'], wait=False))
    r = await page.ev('''(() => {
      const t = SM.app.tables.find(t => t.name === 'Dose response'); const c = t.columns[t.columns.length - 1];
      return { name: c.name, n: c.values.filter(Number.isFinite).length, first: c.values[0] };
    })()''')
    check('Save Prediction: a column for every row', (r['name'], r['n']), ('Predicted response (Logistic 4P)', 75))
    pe = await page.ev(table_under_js('Parameter Estimates'))
    a, b, c_, d = (float(row[2].replace('−', '-')) for row in pe[1:5])   # group A: Group, Parameter, Estimate, ...
    check.near('the saved prediction is the curve at row 1', r['first'], c_ + (d - c_) / (1 + math.exp(-a * (0 - b))), 1e-5)
    await shot(page, 'survival-04-fitcurve.png')
    await triangles(page, 'Fit Curve', 4)

    # ---- Nonlinear through its launch dialog, on NIST's Misra1a
    await page.ev('''(() => {
      const y = [10.07, 14.73, 17.94, 23.93, 29.61, 35.18, 40.02, 44.82, 50.76, 55.05, 61.01, 66.40, 75.47, 81.78];
      const x = [77.6, 114.9, 141.1, 190.8, 239.9, 289.0, 332.8, 378.4, 434.8, 477.3, 536.8, 593.1, 689.1, 760.0];
      SM.app.addTable(new SM.Table({ name: 'Misra1a', columns: [{ name: 'y', dataType: 'numeric', values: y }, { name: 'x (volume)', dataType: 'numeric', values: x }] }));
    })()''')
    r = await page.ev('''(async () => {
      SM.app.launch('nonlinear');
      await new Promise(r => setTimeout(r, 200));
      const dlg = document.querySelector('.sm-launch-dialog');
      const li = [...dlg.querySelectorAll('.sm-pick-list li')].find(x => x.textContent === 'y');
      li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === 'Y, Response').click();
      dlg.querySelector('.sm-nl-model').value = 'b1 * (1 - exp(-b2 * :"x (volume)"))';
      [...dlg.querySelectorAll('.sm-btn')].find(b => b.textContent === 'Find Parameters').click();
      for (let i = 0; i < 50 && !dlg.querySelector('.sm-nl-start').value; i++) await new Promise(r => setTimeout(r, 100));
      const found = dlg.querySelector('.sm-nl-start').value;
      dlg.querySelector('.sm-nl-start').value = 'b1 = 500, b2 = 0.0001';
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { found, title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3')].map(h => h.textContent),
               errors: [...rep.body.querySelectorAll('.sm-ob-error, .sm-ob-warn')].map(e => e.textContent) };
    })()''')
    check('Find Parameters lists the parameters', r['found'], 'b1 = 1, b2 = 1')
    check('Nonlinear outlines', r['outlines'], ['Nonlinear Fit', 'Model', 'Plot', 'Solution', 'Parameter Estimates', 'Correlation of Estimates'])
    check('no errors or warnings', r['errors'], [])
    est = await page.ev(table_under_js('Parameter Estimates'))
    check('Misra1a b1 = 238.94213 (NIST certified 2.3894212918E+02)', est[1][1], '238.9421')
    check('Misra1a b2 = 0.00055015643 (certified 5.5015643181E-04)', est[2][1], '0.0005501565')
    check('ApproxStdErr of b1 = 2.7070075 (certified 2.7070075241E+00)', est[1][2], '2.707007')
    await shot(page, 'survival-05-nonlinear.png')
    out = await page.ev(pick_js('Nonlinear Fit', ['Use Estimates as Starting Values']))
    start = await page.ev('SM.app.reports[SM.app.reports.length - 1].spec.options.start')
    check('Use Estimates as Starting Values', start.startswith('b1 = 238.94212'), True)
    await triangles(page, 'Nonlinear', 2)
    # a model that is not in the language is refused, and says why
    r = await page.ev(open_report_js('nonlinear', {'y': ['y']}, {'model': "__import__('os').getcwd()", 'start': ''}))
    check('a model outside the language is refused', any('quotes' in w for w in r['warnings']), True)

    # ---- the graphs' matplotlib code, run in the page
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Clinical study")))')
    await chart_code(page)
    check('no script errors from the graphs\' code', page.errors, [])

    # ---- help for every input: the launch dialogs, the red-triangle forms, the controls in the reports
    await help_inputs(page)

    # ---- (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('["lifedist", "survival", "parametric", "phreg", "fitcurve", "nonlinear"].map(id => !!document.getElementById("help-p-" + id))')
    check('each platform has its line in Help', helps, [True] * 6)

    # ---- dark theme and phone width
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "survival")))')
    await asyncio.sleep(1.5)
    await shot(page, 'survival-06-dark.png')
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "lifedist")))')
    await asyncio.sleep(1.2)
    await shot(page, 'survival-07-dark-life.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    wide = await page.ev('document.documentElement.scrollWidth <= innerWidth + 1')
    check('no horizontal page scroll at phone width', wide, True)
    await shot(page, 'survival-08-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


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
  names(p, heading) { const s = p && p.sections.find((x) => x.heading === heading); return s && s.choices.length ? s.choices.map((c) => c[0]) : null; },
  // the shortest text of a section's choices, without what a role takes '(required, ...)'
  shortest(p, heading) { const s = p && p.sections.find((x) => x.heading === heading); return s && s.choices.length ? Math.min(...s.choices.map((c) => c[1].replace(/\s*\([^()]*\)$/, '').length)) : 0; },
  dialog() { return [...document.querySelectorAll('.sm-dialog')].pop(); },
  async launch(id) {
    SM.app.launch(id); await this.sleep(350);
    const d = [...document.querySelectorAll('.sm-launch-dialog')].pop();
    const audit = KvotInfo.audit();
    const p = await this.read(d.querySelector('.sm-dialog-head .info-btn'));
    return { d, p, noTopic: audit.noTopic };
  },
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
  async form() {
    let d = null;
    for (let i = 0; i < 60 && !(d && d.querySelector('.sm-form')); i++) { await this.sleep(50); d = this.dialog(); }
    if (!d) throw new Error('no form');
    const labels = [...d.querySelectorAll('.sm-form label')].map((l) => l.textContent);
    const audit = KvotInfo.audit();
    const p = await this.read(d.querySelector('.sm-dialog-head .info-btn'));
    [...d.querySelectorAll('.sm-dialog-foot .sm-btn')].find((b) => b.textContent === 'Cancel').click();
    await this.sleep(60);
    return { labels, title: p && p.title, fields: this.names(p, 'Fields'), shortest: this.shortest(p, 'Fields'), noTopic: audit.noTopic };
  },
  async outline(title, rep) {
    rep = rep || SM.app.reports[SM.app.reports.length - 1];
    const h = [...rep.body.querySelectorAll('.sm-ob-head')].find((x) => x.querySelector('h2, h3, h4').textContent === title);
    return h ? this.read(h.querySelector('.kvot-info-slot .info-btn')) : null;
  },
};
"""


async def help_inputs(page):
    """What every input is for, in the (i) panels: each launch dialog's roles,
    options and the Nonlinear model fields; the red-triangle forms' fields;
    Life Distribution's check boxes, scale and calculator."""
    await page.ev(HELP_JS)
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Clinical study")))')
    r = await page.ev('''(async () => {
      const out = {};
      for (const id of ['lifedist', 'survival', 'parametric', 'phreg', 'fitcurve', 'nonlinear']) {
        const a = await __help.launch(id);
        out[id] = { roles: __help.names(a.p, 'Roles'), rolesShort: __help.shortest(a.p, 'Roles'), opts: __help.names(a.p, 'Options'), optsShort: __help.shortest(a.p, 'Options'),
          model: __help.names(a.p, 'The model'), modelShort: __help.shortest(a.p, 'The model'), noTopic: a.noTopic };
        a.d.querySelector('.sm-dialog-x').click(); await __help.sleep(60);
      }
      return out; })()''')
    if isinstance(r, str):
        print(r)
    want = {'lifedist': (['Y, Time to Event', 'Censor', 'Freq', 'By'], ['Censor Code']),
            'survival': (['Y, Time to Event', 'Grouping', 'Censor', 'Freq', 'By'], ['Censor Code', 'Plot Failure instead of Survival']),
            'parametric': (['Time to Event', 'Censor', 'Model Effects', 'Freq', 'By'], ['Censor Code', 'Distribution']),
            'phreg': (['Time to Event', 'Censor', 'Model Effects', 'Freq', 'By'], ['Censor Code', 'Ties']),
            'fitcurve': (['Y, Response', 'X, Regressor', 'Group', 'Weight', 'Freq', 'By'], ['Fit']),
            'nonlinear': (['Y, Response', 'Weight', 'Freq', 'By'], None)}
    for k, (roles, opts) in want.items():
        x = r[k]
        check(f'{k}: the launch dialog\'s (i) lists every role and option', (x['roles'], x['opts']), (roles, opts))
        check(f'{k}: each explained, beyond what a role takes', x['rolesShort'] > 30 and (opts is None or x['optsShort'] > 60), True)
        check(f'{k}: every (i) of the open dialog has a topic', x['noTopic'], [])
    check('Nonlinear: the model\'s fields', (r['nonlinear']['model'], r['nonlinear']['modelShort'] > 60), (['Model', 'Parameters and starting values', 'Find Parameters'], True))

    # ---- the red-triangle forms
    r = await page.ev(open_report_js('survival', {'y': ['months'], 'censor': ['censored'], 'group': ['treatment']}, {'censorCode': '1'}))
    check('a survival report to work on', r['errors'], [])
    r = await page.ev('''(async () => {
      const out = {};
      await __help.menu('Product-Limit Survival Fit', ['Estimate Survival Probability…']); out.times = await __help.form();
      await __help.menu('Product-Limit Survival Fit', ['Estimate Time Quantile…']); out.probs = await __help.form();
      return out; })()''')
    check('Estimate Survival Probability: its field, explained', (r['times']['fields'], r['times']['shortest'] > 60), (['Times (months), separated by commas'], True))
    check('Estimate Time Quantile: its field, explained', (r['probs']['fields'], r['probs']['shortest'] > 60), (['Failure probabilities between 0 and 1, separated by commas'], True))
    r = await page.ev(open_report_js('parametric', {'y': ['months'], 'censor': ['censored'], 'x': ['treatment', 'age']}, {'censorCode': '1', 'dist': 'weibull'}))
    r = await page.ev('''(async () => {
      const out = {};
      await __help.menu('Parametric Survival Fit: Weibull', ['Save Quantiles…']); out.q = await __help.form();
      await __help.menu('Parametric Survival Fit: Weibull', ['Save Survival Probabilities…']); out.s = await __help.form();
      return out; })()''')
    check('Save Quantiles and Save Survival Probabilities: their fields', (r['q']['fields'], r['s']['fields'], min(r['q']['shortest'], r['s']['shortest']) > 60),
          (['Failure probability (0 to 1)'], ['Time (months)'], True))
    r = await page.ev(open_report_js('fitcurve', {'y': ['months'], 'x': ['age']}, {'first': 'linear'}))
    r = await page.ev('''(async () => { await __help.menu('Fit Linear', ['Custom Inverse Prediction…']); return __help.form(); })()''')
    if isinstance(r, str):
        print(r)
    check('Custom Inverse Prediction: its field', (r['fields'], r['shortest'] > 60), (['Values of months, separated by commas'], True))
    r = await page.ev(open_report_js('nonlinear', {'y': ['months']}, {'model': 'a + b * :age', 'start': 'a = 1, b = 1'}))
    r = await page.ev('''(async () => {
      const out = {};
      await __help.menu('Nonlinear Fit', ['Edit Model…']); out.edit = await __help.form();
      await __help.menu('Nonlinear Fit', ['Fit Options…']); out.opts = await __help.form();
      return out; })()''')
    check('Edit Model: the model language topic, then its fields', (r['edit']['title'], r['edit']['fields']), ('The model language', ['Model', 'Parameters and starting values']))
    check('Fit Options: its fields, explained', (r['opts']['fields'], r['opts']['shortest'] > 60), (['Method', 'Maximum function evaluations (empty: automatic)'], True))
    check('every (i) of the open forms has a topic', [x['noTopic'] for x in (r['edit'], r['opts'])], [[], []])

    # ---- Life Distribution: the check boxes and the scale, the calculator
    r = await page.ev(open_report_js('lifedist', {'y': ['months'], 'censor': ['censored']}, {'censorCode': '1'}))
    r = await page.ev('''(async () => ({ compare: __help.names(await __help.outline('Compare Distributions'), 'The table beside the plot'),
      calc: __help.names(await __help.outline('Distribution Calculator'), ''), noTopic: KvotInfo.audit().noTopic }))()''')
    check('Compare Distributions\' (i): its check boxes and scale buttons', r['compare'], ['Show', 'Scale'])
    check('the Distribution Calculator has an (i) for its boxes', r['calc'], ['Probability of failure by the time', 'Time by which a fraction has failed'])
    check('every (i) of these reports has a topic', r['noTopic'], [])



# ---- the graphs' matplotlib code ------------------------------------------------------------
# Each graph has a code block right under it (details.sm-code, ending in
# plt.show()); the block runs in the page's own Python (SM.engine.runCell)
# with test_charts.PROBE in place of plt.show(), and its figure is compared
# with the Plotly graph above it. Rows excluded and By are among the cases.
SG_JS = r'''
window.__sg = {
  table(name) { return SM.app.tables.find((t) => t.name === name); },
  async open(tableName, platform, roles, options) {
    const t = this.table(tableName);
    SM.app.showTab(SM.app.tabOf(t));
    const ids = {};
    for (const [k, names] of Object.entries(roles)) ids[k] = names.map((n) => t.col(n).id);
    const rep = SM.app.openReport(SM.platforms.get(platform), { roles: ids, options: options || {} }, t);
    await new Promise((res) => rep.on('done', res));
    return rep;
  },
  errors(rep) { return [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent.slice(0, 300)); },
  details(rep) {
    return [...rep.body.querySelectorAll('.js-plotly-plot')].map((p) => {
      const L = p.layout || {};
      const axes = {};
      for (const k of Object.keys(L)) if (/^[xy]axis\d*$/.test(k)) axes[k] = { range: L[k].range || null, type: L[k].type || null, tickvals: L[k].tickvals || null, ticktext: L[k].ticktext || null };
      return { axes, traces: (p.data || []).map((d) => ({ lwidth: d.line ? d.line.width : null, symbol: d.marker ? d.marker.symbol : null, showlegend: d.showlegend, fill: d.fill || null })),
        legend: (p.data || []).filter((d) => d.showlegend !== false && d.name && L.showlegend !== false).map((d) => d.name) };
    });
  },
};
'''

CURVE_TABLES = r'''(() => {
  const r = SM.util.rng('survival-charts');
  const dose = [], resp = [], batch = [], n = [], w = [];
  const shift = { A: 4, B: 5, C: 6.5 };
  for (const g of ['A', 'B', 'C']) for (let i = 0; i < 25; i++) { const x = 0.2 + 10 * i / 24; dose.push(x); batch.push(g); resp.push(2 + 10 / (1 + Math.exp(-1.2 * (x - shift[g]))) + r.normal(0, 0.3)); n.push(1 + i % 3); w.push(0.5 + (i % 4) / 2); }
  SM.app.addTable(new SM.Table({ name: 'Chart curves', columns: [{ name: 'dose', dataType: 'numeric', values: dose }, { name: 'response', dataType: 'numeric', values: resp },
    { name: 'batch', dataType: 'character', values: batch }, { name: 'n', dataType: 'numeric', values: n }, { name: 'w', dataType: 'numeric', values: w }] }));
  const y = [10.07, 14.73, 17.94, 23.93, 29.61, 35.18, 40.02, 44.82, 50.76, 55.05, 61.01, 66.40, 75.47, 81.78];
  const x = [77.6, 114.9, 141.1, 190.8, 239.9, 289.0, 332.8, 378.4, 434.8, 477.3, 536.8, 593.1, 689.1, 760.0];
  SM.app.addTable(new SM.Table({ name: 'Chart misra', columns: [{ name: 'y', dataType: 'numeric', values: y }, { name: 'x (volume)', dataType: 'numeric', values: x },
    { name: 'part', dataType: 'character', values: x.map((_, i) => (i % 2 ? 'b' : 'a')) }] }));
})()'''


def mplc(c):
    """A Plotly colour as the start of matplotlib's hex (#rrggbb, and the alpha when it has one)."""
    m = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)', c or '')
    if not m:
        return (c or '').lower()
    return '#%02x%02x%02x' % (int(m[1]), int(m[2]), int(m[3])) + ('%02x' % round(float(m[4]) * 255) if m[4] is not None and float(m[4]) < 1 else '')


def mline(ax, x, y, color=None, ls=None, rel=1e-9, abs_=1e-12, drawstyle=None):
    for ln in ax['lines']:
        if color and not (ln['color'] or '').startswith(color):
            continue
        if ls is not None and ln['ls'] != ls:
            continue
        if drawstyle is not None and ln['drawstyle'] != drawstyle:
            continue
        if close(ln['x'], x, rel, abs_) and close(ln['y'], y, rel, abs_):
            return ln
    return None


def near_line(ax, x, y, tol, color=None, ls=None):
    """A line with these x and y within tol of the largest |y| (a fit the code makes itself, against the report's)."""
    scale = max([abs(v) for v in y if v is not None] or [1.0])
    for ln in ax['lines']:
        if color and not (ln['color'] or '').startswith(color):
            continue
        if ls is not None and ln['ls'] != ls:
            continue
        if close(ln['x'], x, 1e-9, 1e-12) and maxdiff(ln['y'], y) <= tol * max(1.0, scale):
            return ln
    return None


def pts_of(t):
    return sorted((a, b) for a, b in zip(t.get('x') or [], t.get('y') or []) if a is not None and b is not None)


def same_points(a, b, rel=1e-8):
    """Two sets of points alike within rel (the page's normal quantiles are its own approximation, relative error below 1.2e-9)."""
    return len(a) == len(b) and all(abs(p[0] - q[0]) <= rel * max(1.0, abs(q[0])) and abs(p[1] - q[1]) <= rel * max(1.0, abs(q[1])) for p, q in zip(a, b))


def check_generic(lab, g, D, F, fit_tol=None):
    """Every visible line of the Plotly graph (steps, curves, limits) as a line of the figure, the fills as fills,
    the markers as points; the axes' titles; the size."""
    ax = F['axes'][0]
    check(f'{lab}: the size, the axis titles', (F['size'], ax['xlabel'], ax['ylabel']), ([g['w'] / 100, g['h'] / 100], g['titles']['x'], g['titles']['y']))
    for t, d in zip(g['traces'], D['traces']):
        if t.get('type') != 'scatter':
            continue
        mode = t.get('mode') or ''
        if mode == 'lines' and d.get('lwidth') != 0:
            ls = {'dot': ':', 'dash': '--'}.get(t.get('dash'), '-')
            ds = 'steps-post' if t.get('shape') == 'hv' else None
            x = t.get('x') or []
            y = t.get('y') or []
            if fit_tol and not ds:
                ok = near_line(ax, x, y, fit_tol, mplc(t.get('color')), ls) is not None
                check(f'{lab}: the {"dotted limit" if ls == ":" else "line"} of {t.get("name") or "a fit"} (the code\'s own fit, within {fit_tol:g})', ok, True)
            else:
                ok = mline(ax, x, y, mplc(t.get('color')), ls, 1e-9, 1e-12, ds) is not None
                check(f'{lab}: the {"steps" if ds else "line"} of {t.get("name") or "a line"}{", " + {":": "dotted", "--": "dashed"}[ls] if ls != "-" else ""}', ok, True)
        elif mode.startswith('markers') and t.get('x'):
            want = pts_of(t)
            got = [sorted((a, b) for a, b in s['xy']) for s in ax['scatter']] + \
                  [sorted((a, b) for a, b in zip(ln['x'], ln['y']) if a is not None and b is not None) for ln in ax['lines'] if ln['marker'] not in ('None', '')]
            check(f'{lab}: the points of {t.get("name") or "a trace"}', any(same_points(q, want) for q in got), True)
    check(f'{lab}: the legend', ax['legend'], D['legend'])
    fills = [t for t in g['traces'] if t.get('fill') in ('tonexty', 'toself')]
    check(f'{lab}: the shaded bands', len(ax['polys']), len(fills))
    for t, p in zip(fills, ax['polys']):
        ys = [q[1] for q in p['paths'][0] if q[1] is not None]
        prev = g['traces'][g['traces'].index(t) - 1]
        both = [v for v in (t.get('y') or []) + (prev.get('y') or []) if v is not None]
        tol = 1e-12 if not fit_tol else fit_tol * max(1.0, max(abs(v) for v in both))
        check(f'{lab}: a band spans the page\'s', bool(ys) and max(abs(min(ys) - min(both)), abs(max(ys) - max(both))) <= tol, True)


async def chart_code(page):
    await page.ev(GRAPHS_JS)
    await page.ev(SG_JS)
    await page.ev('__gr.idle()')
    await page.ev(CURVE_TABLES)
    tbl = "__sg.table('Clinical study')"
    r = await page.ev('''(async () => {
      const t = __sg.table('Clinical study'); t.setState([2, 9, 57, 120], 'excluded', true);
      const cc = { censorCode: '1' };
      const reps = [
        await __sg.open('Clinical study', 'survival', { y: ['months'], censor: ['censored'], group: ['treatment'] },
          { ...cc, showCI: true, showPoints: true, showCombined: true, simCI: true, failPlot: true, 'plot:weibull': true, 'fit:weibull': true, 'plot:exponential': true, 'fit:exponential': true, 'plot:lognormal': true }),
        await __sg.open('Clinical study', 'survival', { y: ['months'], censor: ['censored'], by: ['sex'] }, { ...cc, failure: true, showCI: true }),
        await __sg.open('Clinical study', 'phreg', { y: ['months'], censor: ['censored'], x: ['treatment', 'age'] }, cc),
        await __sg.open('Clinical study', 'phreg', { y: ['months'], censor: ['censored'], x: ['age'], by: ['sex'] }, cc),
        await __sg.open('Clinical study', 'lifedist', { y: ['months'], censor: ['censored'] }, { ...cc, dists: ['weibull', 'lognormal', 'loglogistic'], scale: 'lognormal' }),
        await __sg.open('Clinical study', 'lifedist', { y: ['months'], censor: ['censored'] }, { ...cc, dists: ['normal', 'exponential', 'sev', 'lev', 'logistic', 'frechet'], scale: 'exponential' }),
        await __sg.open('Clinical study', 'lifedist', { y: ['months'], censor: ['censored'] }, { ...cc, dists: ['weibull'], scale: 'nonparametric', showNP: true })];
      const out = [];
      for (const rep of reps) out.push({ title: rep.title, graphs: await __gr.graphs(rep), details: __sg.details(rep), errors: __sg.errors(rep) });
      return { reps: out, undrawn: __gr.take() };
    })()''', timeout=900)
    check('survival code: no errors in the reports', [x['errors'] for x in r['reps']], [[]] * len(r['reps']))
    check('survival code: every graph drawn', r['undrawn'], [])
    check('survival code: the graphs of the first report', [g['label'] for g in r['reps'][0]['graphs']],
          ['months survival plot', 'months failure plot', 'months Exponential Plot', 'months Weibull Plot', 'months Lognormal Plot'])
    for i, rep in enumerate(r['reps']):
        for g, D in zip(rep['graphs'], rep['details']):
            lab = f'survival code {i + 1}: {g["label"]}'
            check(f'{lab}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
            if not g['code']:
                continue
            F, err = await run_graph(page, g, tbl)
            check(f'{lab}: the code runs in the page', err, None)
            if not F:
                continue
            F = F[0]
            ax = F['axes'][0]
            if g['label'].endswith('probability plot'):
                # the fitted lines and their limits come from the code's own maximum likelihood fits (BFGS), within 1e-4
                check_generic(lab, g, D, F, fit_tol=1e-4)
                ya, xa = D['axes']['yaxis'], D['axes']['xaxis']
                check(f'{lab}: the probability axis: its range and ticks', (close(ax['ylim'], ya['range'], 1e-9, 1e-12), [t for t in ax['yticklabels'] if t], close(ax['yticks'], ya['tickvals'], 1e-8, 1e-10)),
                      (True, ya['ticktext'], True))
                logx = xa.get('type') == 'log'
                check(f'{lab}: the time axis{" (log)" if logx else ""}: its range and ticks', (ax['xscale'], close(ax['xlim'], [10 ** v for v in xa['range']] if logx else xa['range'], 1e-9, 1e-12),
                                                                                              [t for t in ax['xticklabels'] if t] if logx else None),
                      ('log' if logx else 'linear', True, xa['ticktext'] if logx else None))
            elif g['label'].endswith('distribution'):
                check_generic(lab, g, D, F, fit_tol=1e-4)
                check(f'{lab}: the range', close(ax['xlim'], D['axes']['xaxis']['range'], 1e-12), True)
            elif g['label'].endswith('Plot') and not g['label'].endswith('survival plot'):
                # the fitted lines are scipy's censored fits in the code, statsmodels' in the report: within 2e-4
                check_generic(lab, g, D, F, fit_tol=2e-4)
            else:
                check_generic(lab, g, D, F)
                if g['label'].endswith(('survival plot', 'failure plot')):
                    check(f'{lab}: the range', close(ax['ylim'], [-0.02, 1.02]), True)
    check('By: a failure plot for each sex, each with its code', [g['label'] for g in r['reps'][1]['graphs']], ['months failure plot'] * 2)
    # ---- Fit Curve (groups, two models, confidence curves; Weight and Freq) and Nonlinear
    r = await page.ev('''(async () => {
      __sg.table('Clinical study').setState([2, 9, 57, 120], 'excluded', false);
      const t = __sg.table('Chart curves'); t.setState([4, 30], 'excluded', true);
      const reps = [
        await __sg.open('Chart curves', 'fitcurve', { y: ['response'], x: ['dose'], group: ['batch'] }, { first: 'logistic4', models: ['logistic4', 'gompertz4'], 'ci:logistic4': true }),
        await __sg.open('Chart curves', 'fitcurve', { y: ['response'], x: ['dose'], weight: ['w'], freq: ['n'] }, { first: 'logistic4', models: ['logistic4', 'probit4'], 'ci:probit4': true }),
        await __sg.open('Chart misra', 'nonlinear', { y: ['y'] }, { model: 'b1 * (1 - exp(-b2 * :"x (volume)"))', start: 'b1 = 500, b2 = 0.0001', ci: true }),
        await __sg.open('Chart misra', 'nonlinear', { y: ['y'], by: ['part'] }, { model: 'b1 * (1 - exp(-b2 * :"x (volume)"))', start: 'b1 = 500, b2 = 0.0001' })];
      const out = [];
      for (const rep of reps) out.push({ title: rep.title, graphs: await __gr.graphs(rep), details: __sg.details(rep), errors: __sg.errors(rep), table: rep.table.name });
      return { reps: out, undrawn: __gr.take() };
    })()''', timeout=900)
    check('Fit Curve and Nonlinear code: no errors in the reports', [x['errors'] for x in r['reps']], [[]] * len(r['reps']))
    check('Fit Curve and Nonlinear code: every graph drawn', r['undrawn'], [])
    check('Fit Curve: the plot of every fit, and a plot for each', [g['label'] for g in r['reps'][0]['graphs']], ['response by dose', 'response by dose Logistic 4P', 'response by dose Gompertz 4P'])
    for i, rep in enumerate(r['reps']):
        for g, D in zip(rep['graphs'], rep['details']):
            lab = f'{"Fit Curve" if i < 2 else "Nonlinear"} code {i + 1}: {g["label"]}'
            check(f'{lab}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
            if not g['code']:
                continue
            F, err = await run_graph(page, g, f"__sg.table({json.dumps(rep['table'])})")
            check(f'{lab}: the code runs in the page', err, None)
            if not F:
                continue
            # the curves are refitted in the code (curve_fit, least_squares) from the report's estimates or starting values: within 1e-6, the bands 1e-5
            check_generic(lab, g, D, F[0], fit_tol=1e-5)
    await page.ev("__sg.table('Chart curves').setState([4, 30], 'excluded', false); for (const r of SM.app.reports.filter((x) => x.table && x.table.name.startsWith('Chart '))) SM.app.closeReport(r); for (const n of ['Chart curves', 'Chart misra']) SM.app.closeTable(__sg.table(n));")


asyncio.run(main())
sys.exit(check.done())
