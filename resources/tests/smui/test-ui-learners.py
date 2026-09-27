#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Predictive Modeling > K Nearest
Neighbors, Naive Bayes and Support Vector Machines.

The simulated Orchard example opens from the URL and File > Examples, and
the three platforms sit in Analyze > Predictive Modeling in that order;
scikit-learn is not loaded at the start and comes with the first call. The
launch dialogs have their roles (no Weight or Freq for K Nearest Neighbors,
a nominal or ordinal Y for Naive Bayes) and options, and refuse bad values.
K Nearest Neighbors: the misclassification rates of K = 1 and K = 5 are the
ones computed here by brute force on the standardized factors (a training
row not its own neighbour, a tied vote to the first level), the best K is
marked, a click on a line of the table or a point of the plot shows another
K, Save Predicteds agrees with the Measures of Fit and Save Near Neighbor
Rows with the neighbours found here; a continuous response gives RASE.
Naive Bayes: the saved probabilities are the ones computed here from the
engine's class parameters (normal densities, smoothed level shares), the
Smoothing dialog changes alpha. Support Vector Machines: Gamma defaults to
one over the columns of X, the saved most likely levels agree with Fit
Details, the decision boundary's points select their rows (one by a real
mouse click) and table selections highlight them, the tuning design and the
linear kernel come from the red triangle, a continuous response saves
predictions and residuals. Every red triangle opens; the profiler draws and
answers a new value; Bootstrap reruns the platforms headless; By gives one
analysis per group with combined tables; Redo and a project keep the
options; every (i) has a topic and every Help link a target; the reports
draw in the dark theme and at phone width without a sideways page scroll.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-learners.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
W, S, F = 'weight (g)', 'sugar (°Bx)', 'firmness (N)'
XS = [W, S, F, 'skin']


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('%', '').replace('*', '').replace('<', ''))


# Pick an item from an outline's red triangle: path is the labels down the
# submenus; wait: wait for the report to run again; which: the n-th outline
# with that title (By groups repeat them).
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


# The same for an item that opens a form: values fill the form's fields in
# order (a boolean ticks a check box), then OK, then the report runs again.
PICK_FORM = '''
(async (title, path, values) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await (%s)(title, path, false, 0);
  for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 100));
  const d = [...document.querySelectorAll('.sm-dialog')].pop();
  const inputs = [...d.querySelectorAll('.sm-form input, .sm-form select')];
  values.forEach((v, i) => { if (v === null) return; if (typeof v === 'boolean') inputs[i].checked = v; else inputs[i].value = String(v); });
  const done = new Promise(res => rep.on('done', res));
  d.querySelector('.sm-dialog-foot .primary').click();
  await done;
  return [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
})
''' % PICK


def pick_form_js(title, path, values):
    return f'({PICK_FORM})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(values)})'


# Open every red triangle of the last report and every submenu in it, as a
# click does: their items are built, none is run.
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

# K nearest neighbours by brute force on the Orchard table: the continuous
# factors standardized by the training rows (n - 1), skin a 0/1 column per
# level, a training row not its own neighbour, a tied vote to the first level.
BRUTE = '''
(() => {
  const t = SM.app.tables.find(t => t.name === 'Orchard');
  const n = t.nrows, v = t.col('Validation').values, y = t.col('variety').values, skin = t.col('skin').values;
  const tr = [...Array(n).keys()].filter(i => v[i] === 0);
  const z = ['%s', '%s', '%s'].map(nm => {
    const c = t.col(nm).values, xs = tr.map(i => c[i]);
    const m = xs.reduce((a, b) => a + b, 0) / xs.length;
    const sd = Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length - 1));
    return c.map(x => (x - m) / sd);
  });
  const F = [...Array(n).keys()].map(i => [...z.map(c => c[i]), ...['green', 'yellow', 'red'].map(l => (skin[i] === l ? 1 : 0))]);
  const d2 = (a, b) => a.reduce((s, x, k) => s + (x - b[k]) ** 2, 0);
  const near = (i, K) => tr.filter(j => j !== i).map(j => [d2(F[i], F[j]), j]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).slice(0, K).map(c => c[1]);
  const L = ['Early', 'Mid', 'Late'];
  const rate = (set, K) => {
    const rows = [...Array(n).keys()].filter(i => v[i] === set);
    let wrong = 0;
    for (const i of rows) { const nb = near(i, K); const votes = L.map(l => nb.filter(j => y[j] === l).length); if (L[votes.indexOf(Math.max(...votes))] !== y[i]) wrong++; }
    return wrong / rows.length;
  };
  const val = [...Array(n).keys()].filter(i => v[i] === 1).slice(0, 25);
  return { t1: rate(0, 1), v1: rate(1, 1), t5: rate(0, 5), v5: rate(1, 5), first: val.map(i => [i, near(i, 1)[0] + 1]) };
})()
''' % (W, S, F)


async def triangles(page, name, least):
    r = await page.ev(TRIANGLES)
    ok = isinstance(r, dict) and not r['errors'] and r['triangles'] >= least and r['items'] > r['triangles']
    check(f'every red triangle of {name} opens, with its submenus', ok, True)
    if not ok:
        print('   ', r)


async def rerun(page):
    await page.ev('(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')


# The launch dialog of a platform: roles filled by name, options by label, then OK.
LAUNCH = '''
(async (id, roles, opts) => {
  SM.app.launch(id);
  await new Promise(r => setTimeout(r, 250));
  const dlg = [...document.querySelectorAll('.sm-launch-dialog')].pop();
  const items = [...dlg.querySelectorAll('.sm-pick-list li')];
  const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); const li = items.find(x => x.textContent === name); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
  const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
  const msgs = [];
  for (const [label, names] of roles) for (const nm of names) { pick(nm); role(label).querySelector('.sm-btn').click(); msgs.push(dlg.querySelector('.sm-launch-msg').textContent); }
  const labels = [...dlg.querySelectorAll('.sm-launch-opts label')];
  for (const [label, value] of opts) {
    const lab = labels.find(l => l.textContent.trim().startsWith(label));
    const i = lab.querySelector('input, select');
    if (typeof value === 'boolean') i.checked = value; else i.value = String(value);
  }
  const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
  const before = SM.app.reports.length;
  ok.click();
  // the report is made at once and runs asynchronously: listen before anything is awaited
  const opened = SM.app.reports.length > before;
  const done = opened ? new Promise(res => SM.app.reports[SM.app.reports.length - 1].on('done', res)) : null;
  const msg = dlg.querySelector('.sm-launch-msg').textContent;
  const shown = [...dlg.querySelectorAll('.sm-role')].filter(r => !r.hidden).map(r => r.querySelector('.sm-btn').textContent);
  const optLabels = labels.map(l => l.textContent.trim());
  if (!opened) { [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'Cancel').click(); return { opened, msg, msgs, shown, optLabels }; }
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await done;
  return { opened, msg, msgs, shown, optLabels, options: rep.spec.options, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
           errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 300)) };
})
'''


def launch_js(pid, roles, opts=()):
    return f'({LAUNCH})({json.dumps(pid)}, {json.dumps(roles)}, {json.dumps(list(opts))})'


# A Save Columns item of the top red triangle, and the columns it added.
SAVE = '''
(async (path) => {
  const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
  const before = t.columns.length;
  await (%s)('*top*', path, false, 0);
  for (let i = 0; i < 80 && t.columns.length === before; i++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 200));
  return t.columns.slice(before).map(c => ({ name: c.name, type: c.modelingType, values: c.values }));
})
''' % PICK


def save_js(path):
    return f'({SAVE})({json.dumps(path)})'


async def main():
    page = await open_page(f'{BASE}/smui.html?example=orchard', height=1200)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "learners").map(f => f.module + ": " + f.error)')
    check('learners.py imports in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])
    check('scikit-learn is not loaded at the start', await page.ev("SM.engine.versions['scikit-learn'] || null"), None)

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const file = SM.app.menuItems('File');
      const exs = file.find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const an = SM.app.menuItems('Analyze');
      const pm = an.find(i => i.label === 'Predictive Modeling');
      const items = (typeof pm.submenu === 'function' ? pm.submenu() : pm.submenu).filter(i => !i.separator).map(i => i.label);
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), about: SM.io.EXAMPLES.orchard.about, inFile: labels.includes(SM.io.EXAMPLES.orchard.label), items,
               val: t.col('Validation').modelingType, counts: [0, 1, 2].map(k => t.col('Validation').values.filter(v => v === k).length) };
    })()''')
    check('?example=orchard opens the simulated orchard', (ex['name'], ex['rows'], ex['cols']), ('Orchard', 600, ['variety', W, S, F, 'skin', 'shelf life (days)', 'grade', 'orchard', 'Validation']))
    check('it is simulated, says how, and is in File > Examples', (ex['about'].startswith('Simulated'), ex['inFile']), (True, True))
    check('its Validation column holds 0, 1 and 2', sum(ex['counts']), 600)
    its = ex['items']
    check('Analyze > Predictive Modeling lists K Nearest Neighbors, Naive Bayes and Support Vector Machines, in that order',
          all(x in its for x in ('K Nearest Neighbors…', 'Naive Bayes…', 'Support Vector Machines…')) and its.index('K Nearest Neighbors…') < its.index('Naive Bayes…') < its.index('Support Vector Machines…'), True)

    # ======================================================================= K NEAREST NEIGHBORS
    r = await page.ev(launch_js('knn', [['Y, Response', ['variety']], ['X, Factor', XS], ['Validation', ['Validation']]], [['Number of Neighbors, K', 0]]))
    check('the K Nearest Neighbors dialog: Y, X, Validation and By; no Weight or Freq', r['shown'], ['Y, Response', 'X, Factor', 'Validation', 'By'])
    check('... the Number of Neighbors (10), then the validation portion, Informative Missing and the seed', [x.split('\n')[0] for x in r['optLabels']][:1] == ['Number of Neighbors, K'] and any('Random Seed' in x for x in r['optLabels']), True)
    check('... K = 0 is refused', (r['opened'], 'whole number from 1 to 1000' in r['msg']), (False, True))
    r = await page.ev(launch_js('knn', [['Y, Response', ['variety']], ['X, Factor', XS], ['Validation', ['Validation']]]), timeout=600)
    check('the first call loads scikit-learn 1.8.0', await page.ev("SM.engine.versions['scikit-learn'] || null"), '1.8.0')
    check('the report\'s outlines', r['outlines'], ['K Nearest Neighbors for variety', 'Model Selection', 'Chosen Model', 'Measures of Fit', 'Confusion Matrix'])
    check('no errors in the report', r['errors'], [])
    check('K = 10 reaches the report', r['options'].get('k'), 10)
    await shot(page, 'learners-01-knn.png')
    sel = await page.ev(table_under_js('Model Selection', 0))
    head = sel[0]
    check('Model Selection: K and the misclassification rate of each set (the counts optional)', head, ['K', 'Training Misclassification Rate', 'Validation Misclassification Rate', 'Test Misclassification Rate'])
    bf = await page.ev(BRUTE, timeout=120)
    check.near('K = 1: the training rate is the one computed here (each training row left out of its own neighbours)', num(sel[1][1]), bf['t1'], tol=1e-6)
    check.near('K = 1: the validation rate is the one computed here', num(sel[1][2]), bf['v1'], tol=1e-6)
    check.near('K = 5: training (a tied vote to the first level)', num(sel[5][1]), bf['t5'], tol=1e-6)
    check.near('K = 5: validation', num(sel[5][2]), bf['v5'], tol=1e-6)
    vrates = [num(row[2]) for row in sel[1:]]
    best = vrates.index(min(vrates)) + 1
    marks = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1];
      const tb = [...rep.body.querySelectorAll('table.sm-rt')].find(t => t.closest('.sm-ob').querySelector('.sm-ob-head').textContent.trim() === 'Model Selection');
      const trs = [...tb.querySelectorAll('tbody tr')];
      return { best: trs.findIndex(tr => tr.querySelector('.sm-lrn-best')) + 1, chosen: trs.findIndex(tr => tr.querySelector('.sm-lrn-chosen')) + 1,
               k: [...rep.body.querySelectorAll('table.sm-kv')].map(t => [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent))) }; })()''')
    check('the best K (the smallest validation rate) is marked, and shown', (marks['best'], marks['chosen']), (best, best))
    kv = dict((a, b) for a, b in marks['k'][0])
    check('Chosen Model: K and the best K', (kv.get('K'), kv.get('Best K')), (str(best), str(best)))
    meas = await page.ev(table_under_js('Measures of Fit', 0))
    mv = {row[0]: row for row in meas[1:]}
    check.near('the Measures of Fit are the chosen K\'s: its validation misclassification rate', num(mv['Validation'][meas[0].index('Misclassification Rate')]), vrates[best - 1], tol=1e-6)
    # a click on a line of the table shows that K
    r = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1];
      const tb = [...rep.body.querySelectorAll('table.sm-rt')].find(t => t.closest('.sm-ob').querySelector('.sm-ob-head').textContent.trim() === 'Model Selection');
      const done = new Promise(res => rep.on('done', res)); tb.querySelectorAll('tbody tr')[2].click(); await done;
      const kv = [...rep.body.querySelectorAll('table.sm-kv')][0];
      return { k: rep.spec.options.knnK, text: [...kv.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent)) }; })()''')
    check('a click on the K = 3 line shows K = 3', (r['k'], r['text'][0]), (3, ['K', '3']))
    meas3 = await page.ev(table_under_js('Measures of Fit', 0))
    check.near('... and its Measures of Fit', num({row[0]: row for row in meas3[1:]}['Validation'][meas3[0].index('Misclassification Rate')]), vrates[2], tol=1e-6)
    await rerun(page)
    check('Redo keeps the chosen K', (await page.ev(STATE))['options'].get('knnK'), 3)
    r = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => /by K$/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      for (let i = 0; i < 40 && !p.drawn; i++) await new Promise(r => setTimeout(r, 100));
      const done = new Promise(res => rep.on('done', res)); p.box.emit('plotly_click', { points: [{ x: 7, curveNumber: 1, pointNumber: 6 }] }); await done;
      return rep.spec.options.knnK; })()''')
    check('a click on a point of the plot shows that K', r, 7)
    await page.ev(pick_js('Model Selection', ['Select K', f'Best K ({best})']))
    check('Select K > Best K goes back to the best', (await page.ev(STATE))['options'].get('knnK'), None)
    await triangles(page, 'K Nearest Neighbors', 3)
    await page.ev(pick_js('*top*', ['ROC Curve']))
    await page.ev(pick_js('*top*', ['Profiler']))
    st = await page.ev(STATE)
    check('ROC Curve and Profiler from the red triangle', ('ROC Curve' in st['outlines'], 'Prediction Profiler' in st['outlines'], st['errors']), (True, True, []))
    prof = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1];
      const ob = [...rep.body.querySelectorAll('.sm-ob')].find(o => o.querySelector('.sm-ob-head').textContent.trim() === 'Prediction Profiler');
      const vals = () => [...ob.querySelectorAll('.sm-prof-val')].map(e => e.textContent);
      const before = vals();
      const inp = ob.querySelector('.sm-prof-x input[type="text"]');
      inp.value = '210'; inp.dispatchEvent(new Event('change'));
      for (let i = 0; i < 50 && vals().join() === before.join(); i++) await new Promise(r => setTimeout(r, 100));
      return { before, after: vals(), n: before.length }; })()''')
    check('the profiler: a probability per level, and a new weight moves them', (prof['n'], prof['after'] != prof['before']), (3, True))
    await shot(page, 'learners-02-knn-options.png')
    # Save Columns
    cols = await page.ev(save_js(['Save Columns', 'Save Predicteds']))
    check('Save Predicteds: Prob[Early], Prob[Mid], Prob[Late] and Most Likely variety', [c['name'] for c in cols], ['Prob[Early]', 'Prob[Mid]', 'Prob[Late]', 'Most Likely variety'])
    agree = await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Orchard');
      const v = t.col('Validation').values, y = t.col('variety').values, m = t.col('Most Likely variety').values;
      const pr = ['Early', 'Mid', 'Late'].map(l => t.col('Prob[' + l + ']').values);
      const rows = [...Array(t.nrows).keys()].filter(i => v[i] === 1);
      const ok = [...Array(t.nrows).keys()].every(i => { const p = pr.map(c => c[i]); return p.every(x => x > 0 && x < 1) && Math.abs(p.reduce((a, b) => a + b) - 1) < 1e-12; });
      return { rate: rows.filter(i => m[i] !== y[i]).length / rows.length, ok }; })()''')
    meas_now = await page.ev(table_under_js('Measures of Fit', 0))
    check.near('... the saved most likely levels miss the validation rows at the Measures of Fit\'s rate', agree['rate'], num({row[0]: row for row in meas_now[1:]}['Validation'][meas_now[0].index('Misclassification Rate')]), tol=1e-6)
    check('... every probability strictly between 0 and 1, summing to 1', agree['ok'], True)
    cols = await page.ev(save_js(['Save Columns', 'Save Near Neighbor Rows']))
    check('Save Near Neighbor Rows: RowNear 1 … RowNear 10', [c['name'] for c in cols], [f'RowNear {j}' for j in range(1, 11)])
    first = {i: rn for i, rn in bf['first']}
    got = {i: cols[0]['values'][i] for i in first}
    check('... RowNear 1 of each validation row is its nearest training row found here (a row number from 1)', got == first, True)
    # a continuous response
    rc = await page.ev(open_report_js('knn', {'y': ['shelf life (days)'], 'x': XS, 'validation': ['Validation']}, {'k': 8}), timeout=300)
    check('a continuous response: RASE by K, Actual by Predicted', ('Actual by Predicted Plot' in rc['outlines'], rc['errors']), (True, []))
    selc = await page.ev(table_under_js('Model Selection', 0))
    check('... the table gives each set\'s RASE for K = 1 to 8', (selc[0], len(selc) - 1), (['K', 'Training RASE', 'Validation RASE', 'Test RASE'], 8))
    cols = await page.ev(save_js(['Save Columns', 'Save Residuals']))
    check('... Save Residuals', [c['name'] for c in cols], ['Residual shelf life (days)'])

    # ======================================================================= NAIVE BAYES
    r = await page.ev(launch_js('naivebayes', [['Y, Response', ['shelf life (days)', 'variety']], ['X, Factor', XS], ['Validation', ['Validation']]]), timeout=300)
    check('the Naive Bayes dialog refuses a continuous Y', 'takes nominal or ordinal columns' in r['msgs'][0], True)
    check('... has Weight and Freq', ('Weight' in r['shown'], 'Freq' in r['shown']), (True, True))
    check('the report\'s outlines', r['outlines'], ['Naive Bayes for variety', 'Fit Details', 'Confusion Matrix'])
    await page.ev(pick_js('*top*', ['Class Parameters']))
    st = await page.ev(STATE)
    check('Class Parameters from the red triangle', 'Class Parameters' in st['outlines'], True)
    cols = await page.ev(save_js(['Save Columns', 'Save Predicteds']))
    check('Save Predicteds: the probabilities and the most likely level', [c['name'] for c in cols][-1], 'Most Likely variety 2')
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const o = rep.spec.options;
      const fit = await SM.engine.call('naivebayes.fit', { table: t.id, rows: null, y: 'variety', x: %s, weight: null, freq: null, validation: 'Validation', portion: 0, seed: o.seedDrawn, missing: 'informative', alpha: 1, var_smoothing: 1e-9 }, t);
      const L = fit.priors.map(p => p.level);
      const probs = [...Array(40).keys()].map(i => {
        const lp = fit.priors.map(p => Math.log(p.share));
        for (const f of fit.parameters) {
          const x = t.col(f.factor).values[i];
          if (f.kind === 'normal') f.rows.forEach((q, c) => { lp[c] += -0.5 * Math.log(2 * Math.PI * q.sd * q.sd) - (x - q.mean) ** 2 / (2 * q.sd * q.sd); });
          else { const j = f.labels.indexOf(String(x)); f.rows.forEach((q, c) => { lp[c] += Math.log(q['p' + j]); }); }
        }
        const m = Math.max(...lp); const e = lp.map(v => Math.exp(v - m)); const s = e.reduce((a, b) => a + b); return e.map(v => v / s);
      });
      const saved = [...Array(40).keys()].map(i => L.map(l => t.columns.filter(c => c.name.startsWith('Prob[' + l + ']')).pop().values[i]));
      let worst = 0; probs.forEach((p, i) => p.forEach((x, c) => { worst = Math.max(worst, Math.abs(x - saved[i][c])); }));
      return { worst, L };
    })()''' % json.dumps(XS))
    check.near('the saved probabilities are the class shares times the normal densities and level shares of the engine\'s parameters, computed here', r['worst'], 0.0, tol=1e-9)
    shares0 = await page.ev(table_under_js('Class Parameters', 4))
    await page.ev(pick_form_js('*top*', ['Smoothing…'], [0.5, None]))
    st = await page.ev(STATE)
    shares1 = await page.ev(table_under_js('Class Parameters', 4))
    check('Smoothing: α = 0.5 reaches the report and the level shares', (st['options'].get('nbAlpha'), shares0 != shares1), (0.5, True))
    await triangles(page, 'Naive Bayes', 2)
    await page.ev(pick_js('*top*', ['Profiler']))
    check('the profiler of Naive Bayes', 'Prediction Profiler' in (await page.ev(STATE))['outlines'], True)
    await shot(page, 'learners-03-nb.png')

    # ======================================================================= SUPPORT VECTOR MACHINES
    r = await page.ev(launch_js('svm', [['Y, Response', ['variety']], ['X, Factor', XS], ['Validation', ['Validation']]], [['Cost', -1]]))
    check('the Support Vector Machines dialog: its options', all(any(x.startswith(k) for x in r['optLabels']) for k in ('Kernel Function', 'Cost', 'Gamma', 'Tuning Design', 'Design Points')), True)
    check('... a negative Cost is refused', (r['opened'], 'Cost: a positive number' in r['msg']), (False, True))
    r = await page.ev(launch_js('svm', [['Y, Response', ['variety']], ['X, Factor', XS], ['Validation', ['Validation']]]), timeout=600)
    check('the report\'s outlines', r['outlines'], ['Support Vector Machines for variety', 'Model Summary', 'Fit Details', 'Confusion Matrix', 'Decision Boundary'])
    ms = await page.ev(table_under_js('Model Summary', 0))
    msd = {row[0]: row[1] for row in ms}
    check('Model Summary: the radial basis function, Cost 1, Gamma one over the 6 columns of X', (msd.get('Kernel Function'), msd.get('Cost'), msd.get('Gamma (1/columns of X)'), msd.get('Columns of X')), ('Radial Basis Function', '1', '0.166667', '6'))
    cols = await page.ev(save_js(['Save Columns', 'Save Predicteds']))
    agree = await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Orchard');
      const v = t.col('Validation').values, y = t.col('variety').values, m = t.columns[t.columns.length - 1].values;
      const rows = [...Array(t.nrows).keys()].filter(i => v[i] === 2);
      return rows.filter(i => m[i] !== y[i]).length / rows.length; })()''')
    fd = await page.ev(table_under_js('Fit Details', 0))
    check.near('Save Predicteds: the most likely levels miss the test rows at Fit Details\' rate', agree, num({row[0]: row for row in fd[1:]}['Test'][fd[0].index('Misclassification Rate')]), tol=1e-6)
    # the decision boundary of a two-level response, linked to the rows
    r = await page.ev(open_report_js('svm', {'y': ['grade'], 'x': [W, S], 'validation': ['Validation']}, {}), timeout=300)
    check('grade by weight and sugar: a decision boundary', ('Decision Boundary' in r['outlines'], r['errors']), (True, []))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => /^Decision boundary over/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      for (let n = 0; n < 60 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      const names = p.traces.map(tr => tr.name);
      const ci = p.rows.findIndex(x => x && x.length);
      p._click({ points: [{ curveNumber: ci, pointNumber: 3 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[ci][5], p.rows[ci][9]]);
      const sp = p.box.data[ci].selectedpoints;
      t.select([]);
      return { names, sel, want: [p.rows[ci][3]], sp, n: p.rows.filter(Boolean).reduce((a, x) => a + x.length, 0), color: p.traces[ci].marker.color };
    })()''')
    check('the boundary, the margins, a trace per level and the support vectors', r['names'], ['Decision function', 'Boundary', 'Margins (±1)', 'export', 'local', 'Support vectors'])
    check('a point per row of the report', r['n'], 600)
    check('a click on a point selects its row', r['sel'], r['want'])
    check('rows selected in the table highlight their points', sorted(r['sp']), [5, 9])
    check('the first level takes the first colour (light theme)', r['color'], '#2a78d6')
    pos = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => /^Decision boundary over/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      await new Promise(r => setTimeout(r, 300));
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      const gd = p.box, xa = gd._fullLayout.xaxis, ya = gd._fullLayout.yaxis;
      let best = null, bestD = -1;
      p.traces.forEach((tr, ci) => { if (!p.rows[ci]) return; tr.x.forEach((x, k) => {
        let d = Infinity;
        p.traces.forEach((t2, c2) => { if (!p.rows[c2]) return; t2.x.forEach((x2, m) => { if (c2 === ci && m === k) return; d = Math.min(d, ((x - x2) / (xa.range[1] - xa.range[0])) ** 2 + ((tr.y[k] - t2.y[m]) / (ya.range[1] - ya.range[0])) ** 2); }); });
        if (d > bestD) { bestD = d; best = { ci, k }; } }); });
      const b = gd.getBoundingClientRect();
      return { x: b.left + xa._offset + xa.l2p(p.traces[best.ci].x[best.k]), y: b.top + ya._offset + ya.l2p(p.traces[best.ci].y[best.k]), row: p.rows[best.ci][best.k] };
    })()''')
    await page.click(pos['x'], pos['y'])
    await asyncio.sleep(0.5)
    check('a mouse click on a point over the shaded decision function selects that row', await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()'), [pos['row']])
    await page.mouse('mouseMoved', 2, 2)
    await page.ev('SM.app.reports[SM.app.reports.length - 1].table.select([])')
    await shot(page, 'learners-04-boundary.png')
    # the tuning design and the linear kernel from the red triangle
    await page.ev(pick_form_js('*top*', ['Tuning Design…'], [True, 6]), timeout=600)
    st = await page.ev(STATE)
    check('Tuning Design… adds the design (6 points), judged by the validation rows', ('Tuning Design' in st['outlines'], st['options'].get('tune'), st['options'].get('points')), (True, True, 6))
    td = await page.ev(table_under_js('Tuning Design', 0))
    crits = [num(row[2]) for row in td[1:]]
    ms = {row[0]: row[1] for row in await page.ev(table_under_js('Model Summary', 0))}
    bi = crits.index(min(crits))
    check('... the best point (the smallest validation rate) is the model\'s Cost and Gamma',
          (abs(num(ms.get('Cost (tuned)')) / num(td[bi + 1][0]) - 1) < 1e-4, abs(num(ms.get('Gamma (tuned)')) / num(td[bi + 1][1]) - 1) < 1e-4), (True, True))
    await page.ev(pick_js('*top*', ['Kernel Function', 'Linear']), timeout=600)
    ms = {row[0]: row[1] for row in await page.ev(table_under_js('Model Summary', 0))}
    check('Kernel Function > Linear: the linear kernel, no Gamma', (ms.get('Kernel Function'), any(k.startswith('Gamma') for k in ms)), ('Linear', False))
    await rerun(page)
    st = await page.ev(STATE)
    check('Redo keeps the kernel and the design', (st['options'].get('kernel'), st['options'].get('tune')), ('linear', True))
    await triangles(page, 'Support Vector Machines', 4)
    await page.ev(pick_js('*top*', ['Profiler']))
    check('the profiler of Support Vector Machines', 'Prediction Profiler' in (await page.ev(STATE))['outlines'], True)
    # a continuous response
    r = await page.ev(open_report_js('svm', {'y': ['shelf life (days)'], 'x': [W, S, F], 'validation': ['Validation']}, {}), timeout=300)
    check('SVR: Actual by Predicted and the prediction surface', ('Actual by Predicted Plot' in r['outlines'], 'Prediction Surface' in r['outlines'], r['errors']), (True, True, []))
    cols = await page.ev(save_js(['Save Columns', 'Save Predicteds']))
    cols2 = await page.ev(save_js(['Save Columns', 'Save Residuals']))
    check('... Save Predicteds and Save Residuals', ([c['name'] for c in cols], [c['name'] for c in cols2]), (['Predicted shelf life (days)'], ['Residual shelf life (days) 2']))

    # ======================================================================= BOOTSTRAP, BY, PROJECTS
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'naivebayes');
      SM.app.showTab(SM.app.tabOf(rep));
      const tb = [...rep.body.querySelectorAll('table.sm-rt')].find(t => t.closest('.sm-ob').querySelector('.sm-ob-head').textContent.trim() === 'Fit Details');
      const col = tb._rt.columns.find(c => c.label === 'Misclassification Rate');
      const res = await SM.bootstrap.run(tb, col, { B: 3, seed: 2, show: false });
      const knn = SM.app.reports.find(r => r.platform.id === 'knn');
      const kv = [...knn.body.querySelectorAll('table.sm-kv')][0];
      const res2 = await SM.bootstrap.run(kv, kv._rt.columns[1], { B: 3, seed: 2, show: false });
      return { n: res.nrows, cols: res.columns.map(c => c.name), first: res.columns[1].values, ks: res2.columns.find(c => c.name === 'K').values };
    })()''', timeout=600)
    check('Bootstrap reruns Naive Bayes headless: a row per sample, a column per set', (r['n'], r['cols']), (4, ['BootID', 'Training', 'Validation', 'Test']))
    check('... every sample gives its misclassification rate', all(isinstance(v, (int, float)) for v in r['first']), True)
    check('... and K Nearest Neighbors\' chosen K, from each sample\'s own validation rates', all(isinstance(v, (int, float)) and 1 <= v <= 10 for v in r['ks']), True)
    rep = await page.ev(open_report_js('knn', {'y': ['variety'], 'x': XS, 'validation': ['Validation'], 'by': ['orchard']}, {}), timeout=300)
    check('By orchard: one analysis per orchard', [o for o in rep['outlines'] if o.startswith('K Nearest Neighbors')], ['K Nearest Neighbors for variety orchard=North', 'K Nearest Neighbors for variety orchard=South'])
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const tbls = [...rep.body.querySelectorAll('table.sm-rt')].filter(t => t.dataset.rtKey === 'knnsel');
      const combined = SM.report.combineRT(tbls, 'x');
      return { n: tbls.length, groups: tbls.map(t => t.dataset.group), rows: combined.nrows, each: tbls.map(t => t._rt.rows.length) };
    })()''')
    check('... each group has its Model Selection, which combine into one table', (r['n'], r['groups'], r['rows']), (2, ['orchard=North', 'orchard=South'], sum(r['each'])))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'svm' && r.spec.options.kernel === 'linear');
      const knn = SM.app.reports.find(r => r.platform.id === 'knn' && !(r.spec.roles.by || []).length);
      const done = new Promise(res => knn.on('done', res)); knn.spec.options.knnK = 4; knn.run(); await done;
      const t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON(), knn.toJSON()] }));
      SM.app.loadProject(j);
      const backs = SM.app.reports.slice(-2);
      for (const b of backs) await new Promise(res => { if (!b.body.classList.contains('is-running') && b.body.querySelector('.sm-ob')) res(); else b.on('done', res); });
      const out = backs.map(b => ({ id: b.platform.id, newTable: b.table !== t, kernel: b.spec.options.kernel, tune: b.spec.options.tune, k: b.spec.options.knnK,
        heads: [...b.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent), errors: b.body.querySelectorAll('.sm-ob-error').length,
        kv: [...b.body.querySelectorAll('table.sm-kv')].slice(0, 1).map(t => [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent))) }));
      SM.app.closeTable(backs[0].table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })()''', timeout=900)
    svm_back, knn_back = r[0], r[1]
    check('a project: the SVM keeps its linear kernel and tuning design, on its own table', (svm_back['newTable'], svm_back['kernel'], svm_back['tune'], 'Tuning Design' in svm_back['heads'], svm_back['errors']), (True, 'linear', True, True, 0))
    check('... and K Nearest Neighbors its chosen K', (knn_back['k'], knn_back['kv'][0][0] if knn_back['kv'] else None, knn_back['errors']), (4, ['K', '4'], 0))

    # ======================================================================= (i), Help, themes, phone
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-knn"); return ["knn", "naivebayes", "svm"].map(id => { const row = document.getElementById("help-p-" + id); return row ? row.textContent : null; }); })()')
    check('Help names the scikit-learn classes', ('KNeighborsClassifier' in (helps[0] or ''), 'GaussianNB' in (helps[1] or ''), 'SVC' in (helps[2] or '')), (True, True, True))
    topics = await page.ev('[...Object.keys(SM.platforms.get("knn").topics), ...Object.keys(SM.platforms.get("naivebayes").topics), ...Object.keys(SM.platforms.get("svm").topics)]')
    check('their topics', sorted(topics), sorted(['p:knn', 'p:knn:selection', 'p:knn:fit', 'p:naivebayes', 'p:naivebayes:params', 'p:svm', 'p:svm:summary', 'p:svm:tuning', 'p:svm:boundary']))
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "svm" && r.title === "Support Vector Machines for grade")))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(3.0)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => ['knn', 'naivebayes', 'svm'].includes(r.platform.id));
      const rep = rs.find(r => r.title === 'Support Vector Machines for grade');
      const p = rep.plots.find(p => /^Decision boundary over/.test(p.opts.title));
      return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)), color: p ? p.traces[p.rows.findIndex(x => x && x.length)].marker.color : null }; })()''')
    check('the dark theme redraws the reports without errors', st['errors'], [])
    check('... the first level takes the dark theme\'s colour', st['color'], '#3987e5')
    await shot(page, 'learners-05-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    for pid, title in (('knn', 'K Nearest Neighbors for variety'), ('svm', 'Support Vector Machines for grade')):
        await page.ev('(async () => { const rep = SM.app.reports.filter(r => r.title === "%s").pop(); SM.app.showTab(SM.app.tabOf(rep)); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()' % title, timeout=300)
        await asyncio.sleep(1.0)
        r = await page.ev('''(() => {
          const rep = SM.app.reports.filter(r => r.title === "%s").pop();
          const body = rep.body.getBoundingClientRect();
          const boxes = rep.plots.filter(p => p.drawn && p.opts.fit !== false).map(p => p.box.getBoundingClientRect().right);
          return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length,
                   body: rep.body.scrollWidth <= rep.body.clientWidth + 1, scrollers: [...rep.body.querySelectorAll('table.sm-rt, .sm-lrn-scroll')].some(s => s.scrollWidth > s.clientWidth + 1) };
        })()''' % title)
        check(f'{pid} at phone width: no horizontal page scroll', r['page'], True)
        check(f'{pid} at phone width: the graphs fit', (r['plots'], r['n'] >= 1), (True, True))
        check(f'{pid} at phone width: wide tables scroll inside their own boxes', (r['body'], r['scrollers']), (True, True))
    await shot(page, 'learners-06-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
