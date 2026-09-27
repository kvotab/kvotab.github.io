#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Predictive Modeling > Model
Screening, and Make Validation Column.

The platform and the command sit in Analyze > Predictive Modeling (the
command in Cols > Modeling Utilities too), and scikit-learn loads on the
first call only; the launch dialog's own part lists JMP's methods (Fit
Stepwise off), strikes out Naive Bayes and Discriminant for a continuous Y,
names the linear method by the Y's type, and turns K-fold off with a
Validation column; the Summary Across the Models and the set tables hold
the engine's numbers, and Fit Least Squares' training RSquare is the one
computed here by least squares; the best of each column is marked, a click
selects a method, Select Dominant selects the dominant ones and Run
Selected opens the methods' own platforms (disabled while none is here);
every red triangle opens; ROC and lift curves, Decision Threshold (the
engine's counts, a new threshold), Actual by Predicted (linked both ways),
the Prediction Profiler and Save Columns of one method work; K-fold gives
the Crossvalidation tables; Make Validation Column makes a stratified
column exact to the proportions, which Model Screening then takes (a Test
outline); By, Redo, a project round trip, the dark theme, phone width, the
(i) topics and Help, and no script errors.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-screening.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import math
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
X = ['x1', 'x2', 'x3', 'g', 'x5', 'x6', 'x7', 'x8', 'x9']


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('*', '').replace('<', ''))


# A simulated table: y continuous, cls two levels, three ordinal, nine factors (g nominal).
MAKE = '''
((n) => {
  const r = SM.util.rng('model screening test');
  const c = { y: [], cls: [], three: [], x1: [], x2: [], x3: [], g: [], x5: [], x6: [], x7: [], x8: [], x9: [], day: [] };
  for (let i = 0; i < n; i++) {
    const x1 = r.normal(), x2 = r.u() * 4 - 2, x3 = r.normal(), g = ['a', 'b', 'c'][Math.floor(r.u() * 3)];
    const eta = x1 - 0.8 * x2 + 0.6 * x1 * x3 + (g === 'b' ? 0.7 : 0);
    c.y.push(eta + r.normal());
    c.cls.push(eta + Math.log(1 / r.u() - 1) > 0 ? 'yes' : 'no');
    const e3 = eta + Math.log(1 / r.u() - 1);
    c.three.push(e3 < -1 ? 'lo' : e3 < 1 ? 'mid' : 'hi');
    c.x1.push(x1); c.x2.push(x2); c.x3.push(x3); c.g.push(g);
    for (const k of ['x5', 'x6', 'x7', 'x8', 'x9']) c[k].push(r.normal());
    c.day.push(1 + Math.floor(i / 4));
  }
  const cols = Object.entries(c).map(([name, values]) => ({ name, values, dataType: typeof values[0] === 'string' ? 'character' : 'numeric',
    modelingType: name === 'three' ? 'ordinal' : undefined, valueOrder: name === 'three' ? ['lo', 'mid', 'hi'] : undefined }));
  SM.app.addTable(new SM.Table({ name: 'Screen', source: 'simulated', columns: cols }));
  return SM.app.current.nrows;
})
'''

# Pick an item from an outline's red triangle (copied from the copula test).
PICK = '''
(async (title, path, wait, which) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const heads = [...rep.body.querySelectorAll('.sm-ob-head')].filter(h => h.querySelector('h2, h3, h4').textContent.trim() === title || (title === '*top*' && h.querySelector('h2')));
  const head = heads[which || 0];
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


def pick_js(title, path, wait=True, which=0):
    return f'({PICK})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(wait)}, {which})'


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

STATE = '''
(() => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  return { title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
           errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 400)),
           warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)), options: rep.spec.options };
})()
'''

# The engine's own screening of the last report, from its spec.
ENGINE = '''
(async (extra) => {
  const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table; const o = rep.spec.options;
  const name = (k) => { const id = (rep.spec.roles[k] || [])[0]; return id ? t.col(id).name : null; };
  const pay = { table: t.id, rows: null, y: name('y'), x: rep.spec.roles.x.map((id) => t.col(id).name), weight: name('weight'), freq: name('freq'), validation: name('validation'),
    portion: Number(o.portion || 0), seed: o.seed ? Number(o.seed) : o.seedDrawn, missing: o.missing === false ? 'drop' : 'informative', ...extra };
  return await SM.engine.call(extra.fn || 'screening.fit', pay, t);
})
'''


def engine_js(extra):
    return f'({ENGINE})({json.dumps(extra)})'


async def triangles(page, name, least):
    r = await page.ev(TRIANGLES)
    ok = isinstance(r, dict) and not r['errors'] and r['triangles'] >= least and r['items'] > r['triangles']
    check(f'every red triangle of {name} opens, with its submenus', ok, True)
    if not ok:
        print('   ', r)


async def rerun(page):
    await page.ev('(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')


def rows_of(tbl):
    """A report table (header first) as {method: {column: text}}."""
    head = tbl[0]
    return {r[0]: dict(zip(head, r)) for r in tbl[1:]}


async def main():
    page = await open_page(f'{BASE}/smui.html', height=1200)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    check('screening.py imports in Pyodide', await page.ev('SM.engine.failed.filter(f => f.module === "screening").map(f => f.error)'), [])
    check('no script errors at load', page.errors, [])
    check('scikit-learn is not loaded at the start', await page.ev("SM.engine.versions['scikit-learn'] || null"), None)
    menus = await page.ev('''(() => {
      const sub = (menu, label) => { const it = SM.app.menuItems(menu).find(i => i.label === label); return it ? (typeof it.submenu === 'function' ? it.submenu() : it.submenu).filter(i => !i.separator).map(i => i.label) : []; };
      return { pm: sub('Analyze', 'Predictive Modeling'), mu: sub('Cols', 'Modeling Utilities') };
    })()''')
    check('Analyze > Predictive Modeling lists Model Screening and Make Validation Column', ('Model Screening…' in menus['pm'], 'Make Validation Column…' in menus['pm']), (True, True))
    check('Cols > Modeling Utilities lists Make Validation Column', 'Make Validation Column…' in menus['mu'], True)
    check('the table', await page.ev(f'({MAKE})(1000)'), 1000)

    # ---- the launch dialog
    r = await page.ev('''(async () => {
      SM.app.launch('screening');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const checks = () => [...dlg.querySelectorAll('.sm-scr-checks .sm-scr-check')].map(l => [l.textContent, l.querySelector('input').checked, l.classList.contains('is-off')]);
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); items.find(x => x.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const unrole = (label, name) => [...role(label).querySelectorAll('li')].find(li => li.textContent === name).dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      const start = checks();
      pick('y'); role('Y, Response').querySelector('.sm-btn').click();
      const cont = checks();
      unrole('Y, Response', 'y'); pick('three'); role('Y, Response').querySelector('.sm-btn').click();
      const ord = checks();
      unrole('Y, Response', 'three'); pick('cls'); role('Y, Response').querySelector('.sm-btn').click();
      const nomi = checks();
      for (const x of ['x1', 'x2', 'x3', 'g', 'x5', 'x6', 'x7', 'x8', 'x9']) { pick(x); role('X, Factor').querySelector('.sm-btn').click(); }
      const kf = dlg.querySelector('.sm-scr-opts input[type=checkbox]');
      const [folds, reps] = [...dlg.querySelectorAll('.sm-scr-opts .sm-scr-input')];
      const foldsOff = folds.disabled;
      kf.checked = true; kf.dispatchEvent(new Event('change'));
      const foldsOn = !folds.disabled;
      pick('day'); role('Validation').querySelector('.sm-btn').click();
      const kfOff = kf.disabled, hint = dlg.querySelector('.sm-scr-hint').textContent;
      unrole('Validation', 'day');
      kf.checked = false; kf.dispatchEvent(new Event('change'));
      const boxes = [...dlg.querySelectorAll('.sm-scr-checks input')];
      const was = boxes.map(b => b.checked);
      boxes.forEach(b => { b.checked = false; });
      ok.click();
      const none = dlg.querySelector('.sm-launch-msg').textContent;
      boxes.forEach((b, i) => { b.checked = was[i]; });
      const opts = [...dlg.querySelectorAll('.sm-launch-opts label')].map(l => [l.textContent.trim(), (l.querySelector('input') || {}).type === 'checkbox' ? l.querySelector('input').checked : (l.querySelector('input') || {}).value]);
      const t0 = performance.now();
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { start, cont, ord, nomi, foldsOff, foldsOn, kfOff, hint, none, opts, seconds: (performance.now() - t0) / 1000, options: rep.spec.options,
               outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent) };
    })()''', timeout=900)
    labels = [c[0] for c in r['start']]
    check('the launch dialog lists JMP\'s methods', labels, ['Decision Tree', 'Bootstrap Forest', 'Boosted Tree', 'K Nearest Neighbors', 'Naive Bayes', 'Neural', 'Support Vector Machines', 'Discriminant', 'Fit Least Squares',
                                                        'Generalized Regression Lasso', 'Generalized Regression Elastic Net', 'Fit Stepwise'])
    check('... every one ticked but Fit Stepwise', [c[0] for c in r['start'] if not c[1]], ['Fit Stepwise'])
    check('a continuous Y strikes out Naive Bayes and Discriminant', [c[0] for c in r['cont'] if c[2]], ['Naive Bayes', 'Discriminant'])
    check('the linear method is named by the Y: Ordinal Logistic, Logistic Regression', (r['ord'][8][0], r['nomi'][8][0], [c[0] for c in r['nomi'] if c[2]]), ('Ordinal Logistic', 'Logistic Regression', []))
    check('K Fold Crossvalidation turns Folds on; a Validation column turns it off', (r['foldsOff'], r['foldsOn'], r['kfOff'], 'Validation column gives the sets' in r['hint']), (True, True, True, True))
    check('no method ticked: an error', 'choose at least one' in r['none'], True)
    check('the options: Validation Portion 0.2, Informative Missing, Random Seed empty', r['opts'], [['Validation Portion', '0.2'], ['Informative Missing', True], ['Random Seed', '']])
    check('the options reach the report', (r['options']['methods'], r['options']['kfold'], r['options']['portion']), ([k for k in ('tree', 'forest', 'boosted', 'knn', 'nb', 'neural', 'svm', 'lda', 'linear', 'lasso', 'enet')], False, 0.2))
    check('the report\'s outlines', r['outlines'], ['Model Screening for cls', 'Summary Across the Models', 'Training', 'Validation', 'Method Details'])
    print(f'      (1000 rows, 9 factors, 11 methods, scikit-learn loaded on the way: {r["seconds"]:.1f} s)')
    check('the first report, scikit-learn loaded on the way, in under a minute', r['seconds'] < 60, True)
    check('scikit-learn is loaded by the first call', await page.ev("SM.engine.versions['scikit-learn']"), '1.8.0')
    st = await page.ev(STATE)
    check('no errors in the report', st['errors'], [])
    await shot(page, 'screening-01-report.png')

    # ---- the numbers against the engine
    eng_methods = r['options']['methods']
    eng = await page.ev(engine_js({'methods': eng_methods, 'kfold': 0, 'repeats': 1}), timeout=300)
    summ = rows_of(await page.ev(table_under_js('Summary Across the Models', 0)))
    worst = 0.0
    for m in eng['methods']:
        row = summ[m['label']]
        for s in ('Training', 'Validation'):
            for key, lab in (('entropy_rsquare', 'Entropy RSquare'), ('misclassification', 'Misclassification Rate'), ('auc', 'AUC')):
                worst = max(worst, abs(num(row[f'{s} {lab}']) - m['measures'][s][key]))
    check('the Summary holds the engine\'s numbers (4 decimals)', worst < 5.1e-5, True)
    check('... best first by the validation Entropy RSquare', list(summ), [next(m['label'] for m in eng['methods'] if m['key'] == k) for k in eng['order']])
    vt = rows_of(await page.ev(table_under_js('Validation', 0)))
    check('the Validation table: every measure of every method', (sorted(vt), list(next(iter(vt.values())))), (sorted(m['label'] for m in eng['methods']), ['Method', 'Entropy RSquare', 'Generalized RSquare', 'Mean -Log p', 'RASE', 'Mean Abs Dev', 'Misclassification Rate', 'AUC', 'N']))
    best = await page.ev('''(() => { const rep = SM.app.reports.at(-1); const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim() === 'Validation');
      const tbl = h.parentElement.querySelector('table.sm-rt'); const heads = [...tbl.querySelectorAll('thead th')].map(t => t.textContent);
      const j = heads.indexOf('Entropy RSquare'); return [...tbl.querySelectorAll('tbody tr')].filter(tr => tr.cells[j].classList.contains('sm-scr-best')).map(tr => tr.cells[0].textContent); })()''')
    check('the best of a column is marked', best, [next(m['label'] for m in eng['methods'] if m['key'] == k) for k in eng['best']['Validation']['entropy_rsquare']])

    # ---- selecting, Select Dominant, Run Selected
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.at(-1);
      const rowsOf = () => { const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim().startsWith('Summary Across')); return [...h.parentElement.querySelectorAll('table.sm-rt tbody tr')]; };
      let d = new Promise(res => rep.on('done', res));
      rowsOf().find(x => x.cells[0].textContent === 'Decision Tree').click();
      await d;
      const sel1 = rep.spec.options.selected.slice();
      const marked = rowsOf().filter(tr => tr.cells[0].classList.contains('sm-scr-sel')).map(tr => tr.cells[0].textContent);
      const btn = () => [...rep.body.querySelectorAll('.sm-scr-actions button')].find(b => b.textContent === 'Run Selected');
      const treeOnly = btn().disabled;
      d = new Promise(res => rep.on('done', res));
      [...rep.body.querySelectorAll('.sm-scr-actions button')].find(b => b.textContent === 'Select Dominant').click();
      await d;
      return { sel1, marked, treeOnly, partition: !!SM.platforms.get('partition'), dominant: rep.spec.options.selected };
    })()''')
    check('a click on a method selects it, and marks its line', (r['sel1'], r['marked']), (['tree'], ['Decision Tree']))
    check('Run Selected is off while the method\'s platform (Partition) is not here', r['treeOnly'], not r['partition'])
    check('Select Dominant selects the dominant methods', r['dominant'], eng['dominant'])

    # ---- the red triangles; ROC, Lift, Decision Threshold, the profiler
    await triangles(page, 'the report', 3)
    await page.ev(pick_js('*top*', ['ROC Curve']))
    roc = await page.ev('''(() => { const rep = SM.app.reports.at(-1); return rep.plots.filter(p => /^ROC /.test(p.opts.title)).map(p => ({ title: p.opts.title, n: p.traces.length, names: p.traces.map(t => t.name).filter(Boolean), colors: p.traces.map(t => t.line && t.line.color) })); })()''')
    check('ROC Curve: a graph per set, a curve per method and the diagonal', ([p_['title'] for p_ in roc], [p_['n'] for p_ in roc]), (['ROC Training yes', 'ROC Validation yes'], [len(eng['methods']) + 1] * 2))
    auc = rows_of(await page.ev(table_under_js('ROC Curve', 0)))
    want = {m['label']: next(c['auc'] for c in eng['roc'][m['key']] if c['set'] == 'Validation' and c['level'] == 'yes') for m in eng['methods']}
    check('... its AUC table is the engine\'s, for the level yes', max(abs(num(auc[k]['Validation AUC']) - v) for k, v in want.items()) < 5.1e-5, True)
    await page.ev(pick_js('*top*', ['Lift Curve']))
    await page.ev(pick_js('*top*', ['Decision Threshold']))
    th = await page.ev(engine_js({'fn': 'screening.threshold', 'methods': eng_methods, 'kfold': 0, 'repeats': 1, 'cut': 0.5, 'level': 1}))
    tv = await page.ev(table_under_js('Decision Threshold', 1))
    thr = rows_of(tv)
    lin = next(m for m in th['methods'] if m['key'] == 'linear')
    check.near('Decision Threshold: the engine\'s sensitivity at 0.5, Validation', num(thr['Nominal Logistic']['Sensitivity']), round(lin['sets']['Validation']['sensitivity'], 4), tol=1e-9)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.at(-1);
      const box = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Decision Threshold').parentElement;
      const inp = box.querySelector('.sm-scr-cut input'); inp.value = '0.3';
      const d = new Promise(res => rep.on('done', res));
      [...box.querySelectorAll('button')].find(b => b.textContent === 'Apply').click();
      await d;
      const box2 = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Decision Threshold').parentElement;
      return { cut: rep.spec.options.cut, captions: [...box2.querySelectorAll('caption')].map(c => c.textContent) };
    })()''')
    check('a new threshold from its field: the option and the tables', (r['cut'], r['captions']), (0.3, ['Training: yes when its probability ≥ 0.3', 'Validation: yes when its probability ≥ 0.3']))
    await page.ev(pick_js('*top*', ['Profiler', 'Boosted Tree']))
    pr = await page.ev(engine_js({'fn': 'screening.profile', 'method': 'boosted', 'kfold': 0, 'current': None}))
    prof = await page.ev('''(() => { const rep = SM.app.reports.at(-1); const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim().startsWith('Prediction Profiler'));
      return h ? { title: h.textContent.trim(), vals: [...h.parentElement.querySelectorAll('.sm-prof-val')].map(v => v.textContent), factors: [...h.parentElement.querySelectorAll('.sm-prof-fname')].map(v => v.textContent) } : null; })()''')
    check('Profiler ▸ Boosted Tree: the Prediction Profiler of that model, every factor', (prof['title'], prof['factors']), ('Prediction Profiler: Boosted Tree', X))
    check.near('... the prediction at the current values is the engine\'s', num(prof['vals'][1]), pr['responses'][1]['current']['pred'], tol=1e-5)
    st = await page.ev(STATE)
    check('the comparisons draw without errors', (st['errors'], [o for o in st['outlines'] if o in ('ROC Curve', 'Lift Curve', 'Decision Threshold')]), ([], ['ROC Curve', 'Lift Curve', 'Decision Threshold']))
    await shot(page, 'screening-02-comparisons.png')

    # ---- Save Columns of one method
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.at(-1); const t = rep.table;
      await (%s)('*top*', ['Save Columns', 'Discriminant', 'Save Predicteds'], false, 0);
      await new Promise(r => setTimeout(r, 1500));
      const c = t.col('Prob[yes] Discriminant'), m = t.col('Most Likely cls Discriminant');
      return c && m ? { v: c.values.slice(0, 5), m: m.values.slice(0, 5), mt: m.modelingType } : null;
    })()''' % PICK, timeout=120)
    sv = await page.ev(engine_js({'fn': 'screening.save', 'method': 'lda', 'kfold': 0}))
    check('Save Columns ▸ Discriminant ▸ Save Predicteds: the probabilities and the most likely level', (r is not None and max(abs(a - b[1]) for a, b in zip(r['v'], sv['prob'][:5])) < 1e-12, r and r['m'] == sv['most_likely'][:5], r and r['mt']), (True, True, 'nominal'))

    # ---- a continuous Y, every row training: Fit Least Squares against least squares here
    rep = await page.ev(open_report_js('screening', {'y': ['y'], 'x': ['x1', 'x2', 'x3', 'g']}, {'portion': 0, 'seed': '5', 'methods': ['tree', 'knn', 'linear', 'lasso'], 'abp': True}), timeout=600)
    check('continuous Y, no holdback: Training only, no errors', ([o for o in rep['outlines'] if o in ('Training', 'Validation')], rep['errors']), (['Training'], []))
    r = await page.ev('''(() => {
      const t = SM.app.reports.at(-1).table; const y = t.col('y').values; const n = y.length;
      const cols = [() => 1, (i) => t.col('x1').values[i], (i) => t.col('x2').values[i], (i) => t.col('x3').values[i], (i) => (t.col('g').values[i] === 'a' ? 1 : 0), (i) => (t.col('g').values[i] === 'b' ? 1 : 0)];
      const p = cols.length, A = Array.from({ length: p }, () => new Array(p + 1).fill(0));
      for (let i = 0; i < n; i++) { const x = cols.map((f) => f(i)); for (let a = 0; a < p; a++) { for (let b = 0; b < p; b++) A[a][b] += x[a] * x[b]; A[a][p] += x[a] * y[i]; } }
      for (let c = 0; c < p; c++) { let m = c; for (let r = c + 1; r < p; r++) if (Math.abs(A[r][c]) > Math.abs(A[m][c])) m = r; [A[c], A[m]] = [A[m], A[c]];
        for (let r = 0; r < p; r++) if (r !== c) { const f = A[r][c] / A[c][c]; for (let k = c; k <= p; k++) A[r][k] -= f * A[c][k]; } }
      const b = A.map((row, i) => row[p] / row[i]);
      const mean = y.reduce((s, v) => s + v, 0) / n;
      let sse = 0, sst = 0;
      for (let i = 0; i < n; i++) { const f = cols.reduce((s, fn, k) => s + b[k] * fn(i), 0); sse += (y[i] - f) ** 2; sst += (y[i] - mean) ** 2; }
      return { r2: 1 - sse / sst, rase: Math.sqrt(sse / n) };
    })()''')
    summ = rows_of(await page.ev(table_under_js('Summary Across the Models', 0)))
    check.near('Fit Least Squares\' training RSquare = least squares computed here', num(summ['Fit Least Squares']['Training RSquare']), round(r['r2'], 4), tol=1e-9)
    check.near('... and its RASE', num(summ['Fit Least Squares']['Training RASE']), round(r['rase'], 4), tol=1e-9)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.at(-1); const t = rep.table;
      const ps = rep.plots.filter(p => /^Actual by predicted /.test(p.opts.title));
      const p = ps[0];
      p.box.scrollIntoView({ block: 'center' });
      await new Promise(r => setTimeout(r, 300));
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      p._click({ points: [{ curveNumber: 0, pointNumber: 7 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[0][3], p.rows[0][11]]);
      const sp = ps.map(q => q.drawn ? q.box.data[0].selectedpoints : 'not drawn');
      t.select([]);
      return { n: ps.length, titles: ps.map(q => q.opts.title), sel, want: [p.rows[0][7]], sp: sp.filter(x => x !== 'not drawn') };
    })()''')
    check('Actual by Predicted: a graph per method, of the Training set', (r['n'], 'Actual by predicted Fit Least Squares Training' in r['titles']), (4, True))
    check('... a click on a point selects its row', r['sel'], r['want'])
    check('... rows selected in the table are highlighted in every graph', all(s == [3, 11] for s in r['sp']) and len(r['sp']) >= 1, True)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.at(-1);
      const d = new Promise(res => rep.on('done', res));
      const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim().startsWith('Summary Across'));
      [...h.parentElement.querySelectorAll('table.sm-rt tbody tr')].find(x => x.cells[0].textContent === 'Fit Least Squares').click();
      await d;
      const n0 = SM.app.reports.length;
      [...rep.body.querySelectorAll('.sm-scr-actions button')].find(b => b.textContent === 'Run Selected').click();
      await new Promise(r => setTimeout(r, 200));
      const nr = SM.app.reports.at(-1);
      if (nr !== rep) await new Promise(res => { if (!nr.body.classList.contains('is-running') && nr.body.querySelector('.sm-ob')) res(); else nr.on('done', res); });
      const out = { opened: SM.app.reports.length - n0, platform: nr.platform.id, personality: nr.spec.options.personality, effects: (nr.spec.effects || []).map(e => e.names[0]), y: nr.spec.roles.y.map(id => nr.table.col(id).name),
                    errors: [...nr.body.querySelectorAll('.sm-ob-error')].length };
      if (nr !== rep) SM.app.closeReport(nr);
      SM.app.showTab(SM.app.tabOf(rep));
      return out;
    })()''', timeout=300)
    check('Run Selected with Fit Least Squares: Fit Model, Standard Least Squares, the same Y and main effects', (r['opened'], r['platform'], r['personality'], r['y'], r['effects'], r['errors']), (1, 'fitmodel', 'standard', ['y'], ['x1', 'x2', 'x3', 'g'], 0))
    await shot(page, 'screening-03-continuous.png')

    # ---- K-fold crossvalidation
    rep = await page.ev(open_report_js('screening', {'y': ['three'], 'x': ['x1', 'x2', 'x3', 'g']}, {'portion': 0.2, 'seed': '9', 'methods': ['tree', 'knn', 'linear', 'nb'], 'kfold': True, 'folds': 3, 'repeats': 2}), timeout=600)
    check('K-fold: the Crossvalidation outline and its folds, no errors', ('Crossvalidation' in rep['outlines'], 'Crossvalidation Folds' in rep['outlines'], rep['errors']), (True, True, []))
    eng = await page.ev(engine_js({'methods': ['tree', 'knn', 'linear', 'nb'], 'kfold': 3, 'repeats': 2}), timeout=300)
    cv = rows_of(await page.ev(table_under_js('Crossvalidation', 0)))
    check('... the means over the 6 held-out folds are the engine\'s', max(abs(num(cv[m['label']]['Entropy RSquare']) - m['measures']['Crossvalidation']['entropy_rsquare']) for m in eng['methods']) < 5.1e-5, True)
    summ = rows_of(await page.ev(table_under_js('Summary Across the Models', 0)))
    check('... and the Summary compares on them', 'Crossvalidation Entropy RSquare' in next(iter(summ.values())), True)
    note = await page.ev('[...SM.app.reports.at(-1).body.querySelectorAll(".sm-ob-note")].map(e => e.textContent).find(t => /fold crossvalidation/.test(t)) || ""')
    check('... its note says how, and that the portion is not used', ('3-fold crossvalidation, repeated 2 times' in note, 'Validation Portion is not used' in note), (True, True))

    # ---- Make Validation Column, from the menu
    r = await page.ev('''(async () => {
      SM.app.showTable(SM.app.tables.find(t => t.name === 'Screen').id);
      SM.app.menuItems('Analyze').find(i => i.label === 'Predictive Modeling').submenu().find(i => i.label === 'Make Validation Column…').action();
      await new Promise(r => setTimeout(r, 300));
      const dlg = [...document.querySelectorAll('.sm-launch-dialog')].pop();
      const title = dlg.querySelector('.sm-dialog-head h2').textContent;
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); items.find(x => x.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      pick('g'); role('Stratification Columns').querySelector('.sm-btn').click();
      const hint = dlg.querySelector('.sm-scr-hint').textContent;
      const opts = Object.fromEntries([...dlg.querySelectorAll('.sm-launch-opts label')].map(l => [[...l.childNodes].find(x => x.nodeType === 3).textContent.trim(), l.querySelector('input, select')]));
      const defaults = [opts['Training Set'].value, opts['Validation Set'].value, opts['Test Set'].value, opts['Values'].value, opts['New Column Name'].value];
      opts['Random Seed'].value = '11';
      const t = SM.app.current;
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
      for (let i = 0; i < 100 && !t.col('Validation'); i++) await new Promise(r => setTimeout(r, 100));
      const c = t.col('Validation');
      const g = t.col('g').values;
      const per = {};
      c.values.forEach((v, i) => { per[g[i]] = per[g[i]] || { Training: 0, Validation: 0, Test: 0, n: 0 }; per[g[i]][v]++; per[g[i]].n++; });
      return { title, hint, defaults, type: [c.dataType, c.modelingType], order: c.valueOrder, counts: ['Training', 'Validation', 'Test'].map(k => c.values.filter(v => v === k).length), per, notes: c.notes };
    })()''', timeout=300)
    check('Make Validation Column: its dialog, Stratification Columns cast', (r['title'], 'Stratified random' in r['hint']), ('Make Validation Column', True))
    check('... JMP-like defaults: 0.6, 0.2, 0.2, the words, named Validation', r['defaults'], ['0.6', '0.2', '0.2', 'text', 'Validation'])
    check('... a nominal text column in the order Training, Validation, Test', (r['type'], r['order']), (['character', 'nominal'], ['Training', 'Validation', 'Test']))
    check('... exactly 600, 200, 200 rows', r['counts'], [600, 200, 200])
    ok = all(math.floor(p['n'] * q - 1e-9) <= p[k] <= math.ceil(p['n'] * q + 1e-9) for p in r['per'].values() for k, q in (('Training', 0.6), ('Validation', 0.2), ('Test', 0.2)))
    check('... within each level of g its share rounded down or up', ok, True)
    check('... the notes keep the method, the seed and the Python', all(s in r['notes'] for s in ('stratified by g', 'seed 11', 'def make_sets(', 'stratum_counts')), True)
    vc = await page.ev('(async () => { const t = SM.app.current; return await SM.engine.call("screening.validation_column", { training: 0.6, validation: 0.2, test: 0.2, strata: ["g"], seed: "11" }, t); })()')
    check('... the same assignment as the engine gives for that seed', await page.ev('SM.app.current.col("Validation").values'), vc['values'])
    r = await page.ev('''(async () => {
      SM.app.menuItems('Cols').find(i => i.label === 'Modeling Utilities').submenu().find(i => i.label === 'Make Validation Column…').action();
      await new Promise(r => setTimeout(r, 300));
      const dlg = [...document.querySelectorAll('.sm-launch-dialog')].pop();
      const opts = Object.fromEntries([...dlg.querySelectorAll('.sm-launch-opts label')].map(l => [[...l.childNodes].find(x => x.nodeType === 3).textContent.trim(), l.querySelector('input, select')]));
      opts['Values'].value = 'numeric'; opts['New Column Name'].value = 'V012'; opts['Training Set'].value = '0.7'; opts['Validation Set'].value = '0.3'; opts['Test Set'].value = '0';
      const t = SM.app.current;
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
      for (let i = 0; i < 100 && !t.col('V012'); i++) await new Promise(r => setTimeout(r, 100));
      const c = t.col('V012');
      return { type: [c.dataType, c.modelingType], counts: [0, 1, 2].map(k => c.values.filter(v => v === k).length) };
    })()''', timeout=300)
    check('Cols > Modeling Utilities: the same command; numeric 0/1/2, random, 700 and 300 rows', (r['type'], r['counts']), (['numeric', 'nominal'], [700, 300, 0]))
    rep = await page.ev(open_report_js('screening', {'y': ['y'], 'x': ['x1', 'x2', 'x3', 'g'], 'validation': ['Validation']}, {'seed': '3', 'methods': ['tree', 'linear', 'lasso']}), timeout=600)
    eng = await page.ev(engine_js({'methods': ['tree', 'linear', 'lasso'], 'kfold': 0, 'repeats': 1}), timeout=300)
    check('Model Screening takes the made column: Training, Validation and Test outlines', ([o for o in rep['outlines'] if o in ('Training', 'Validation', 'Test')], eng['n']), (['Training', 'Validation', 'Test'], {'Training': 600, 'Validation': 200, 'Test': 200}))
    note = await page.ev('[...SM.app.reports.at(-1).body.querySelectorAll(".sm-ob-note")].map(e => e.textContent).find(t => /Validation column/.test(t)) || ""')
    check('... and says the sets come from it', 'Sets from the Validation column Validation: Training 600, Validation 200, Test 200 rows.' in note, True)
    script = await page.ev('SM.app.reports.at(-1).pythonScript()')
    check('the Python script: the fitters, the measures, the round-trip CSV reading', all(t_ in script for t_ in ('def fit_tree(', 'def fit_genreg(', 'def measures(', 'float_precision="round_trip"', 'DecisionTreeRegressor')), True)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.at(-1);
      const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim().startsWith('Summary Across'));
      const tbl = h.parentElement.querySelector('table.sm-rt');
      const col = tbl._rt.all.find(c => c.label === 'Test RSquare');
      const t = await SM.bootstrap.run(tbl, col, { B: 2, seed: 1, show: false });
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), finite: t.columns.slice(1).every(c => c.values.every(Number.isFinite)) };
    })()''', timeout=900)
    check('Bootstrap of a Summary column: the screening again on resampled rows, a column per method', (r['name'], r['rows'], sorted(r['cols'][1:]), r['finite']),
          ('Bootstrap Results of Model Screening for y', 3, sorted(['Decision Tree', 'Fit Least Squares', 'Generalized Regression Lasso']), True))
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.at(-1)))')
    await shot(page, 'screening-04-validation.png')

    # ---- By, Redo, a project
    rep = await page.ev(open_report_js('screening', {'y': ['cls'], 'x': ['x1', 'x2', 'x3'], 'by': ['g']}, {'seed': '4', 'methods': ['tree', 'linear', 'nb'], 'roc': True}), timeout=600)
    check('By g: one screening per level', [o for o in rep['outlines'] if o.startswith('Model Screening for')], ['Model Screening for cls g=a', 'Model Screening for cls g=b', 'Model Screening for cls g=c'])
    r = await page.ev('''(() => { const rep = SM.app.reports.at(-1); const tbls = [...rep.body.querySelectorAll('table.sm-rt')].filter(t => t.dataset.rtKey === 'summary');
      const combined = SM.report.combineRT(tbls, 'x'); return { n: tbls.length, groups: tbls.map(t => t.dataset.group), rows: combined.nrows }; })()''')
    check('... their Summaries combine into one table', (r['n'], r['groups'], r['rows']), (3, ['g=a', 'g=b', 'g=c'], 9))
    await page.ev(pick_js('*top*', ['Profiler', 'Nominal Logistic']))
    await page.ev(pick_js('Summary Across the Models', ['Select Dominant']))
    await rerun(page)
    st = await page.ev(STATE)
    check('Redo keeps the options: ROC, the profiler, the selection', (st['options'].get('roc'), st['options'].get('profiler'), bool(st['options'].get('selected'))), (True, 'linear', True))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.at(-1); const t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const heads = [...back.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3')].map(h => h.textContent);
      const cell = (r0) => { const h = [...r0.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim().startsWith('Summary Across')); return h.parentElement.querySelector('table.sm-rt tbody tr').textContent; };
      const out = { newTable: back.table !== t, by: back.spec.roles.by.map(id => back.table.col(id).name), opts: [back.spec.options.roc, back.spec.options.profiler, back.spec.options.methods], same: cell(back) === cell(rep),
                    heads: heads.filter(h => /Prediction Profiler|ROC Curve/.test(h)).length, errors: [...back.body.querySelectorAll('.sm-ob-error')].length };
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })()''', timeout=900)
    check('a project: its own table, the By column found again', (r['newTable'], r['by']), (True, ['g']))
    check('... the options kept, the same Summary, no errors', (r['opts'], r['same'], r['heads'], r['errors']), ([True, 'linear', ['tree', 'linear', 'nb']], True, 6, 0))

    # ---- (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-screening"); const row = document.getElementById("help-p-screening"); return row ? row.textContent : null; })()')
    check('Help lists the platform with the scikit-learn it uses', bool(helps) and 'sklearn.ensemble' in helps and 'Model Screening' in helps, True)
    topics = await page.ev('Object.keys(SM.platforms.get("screening").topics)')
    check('its topics', sorted(topics), sorted(['p:screening', 'p:screening:summary', 'p:screening:sets', 'p:screening:cv', 'p:screening:methods', 'p:screening:curves', 'p:screening:abp', 'p:screening:threshold', 'cmd:makevalidation']))

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "screening" && r.spec.options.threshold)))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(3)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => r.platform.id === 'screening'); return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)) }; })()''')
    check('the dark theme redraws the reports without errors', st['errors'], [])
    col = await page.ev('(() => { const rep = SM.app.reports.find(r => r.platform.id === "screening" && r.spec.options.threshold); const p = rep.plots.find(p => /^ROC /.test(p.opts.title)); return p.traces.find(t => t.name && t.name.startsWith("Decision Tree")).line.color; })()')
    check('the curves take the dark theme\'s colours', col, '#6fa3d6')
    await shot(page, 'screening-05-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports.find(r => r.platform.id === "screening" && r.spec.options.threshold); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()', timeout=300)
    await asyncio.sleep(1.0)
    r = await page.ev('''(() => {
      const rep = SM.app.reports.find(r => r.platform.id === "screening" && r.spec.options.threshold);
      const body = rep.body.getBoundingClientRect();
      // the profiler's small plots keep their width (fit: false) and scroll inside its own box
      const boxes = rep.plots.filter(p => p.drawn && p.opts.fit !== false).map(p => p.box.getBoundingClientRect().right);
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length,
               body: rep.body.scrollWidth <= rep.body.clientWidth + 1, scrollers: [...rep.body.querySelectorAll('.sm-scr-scroll, table.sm-rt')].some(s => s.scrollWidth > s.clientWidth + 1) };
    })()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the graphs fit the phone\'s width', (r['plots'], r['n'] >= 1), (True, True))
    check('wide tables scroll inside their own boxes, not the whole report', (r['body'], r['scrollers']), (True, True))
    await shot(page, 'screening-06-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
