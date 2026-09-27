#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Specialized Modeling > Gaussian Process.

The simulated Borehole example opens from the URL and File > Examples; the
platform sits last in Analyze > Specialized Modeling; the first call loads
scikit-learn; the launch dialog has JMP's roles and options with their
defaults and refuses a column that is both Y and X; the report's Model
Report (Theta, the sensitivities, Mu, Sigma², -2 LogLikelihood) and the
jackknife points are the engine's own numbers, and the borehole's known
structure shows (rw dominates, r, Tu, Tl do nothing); points select their
rows (one by a real mouse click) and table selections highlight them;
every red triangle opens; Correlation Type (Matérn), Estimate Nugget
Parameter and Fit Settings change the model and Redo keeps them; the
profiler shows the engine's prediction and band; Save Prediction, Std
Error and Jackknife Predicted Values make the engine's columns; Rows to Fit
caps a large table (the other rows predicted); several Y's get an outline
each; By gives an analysis per group with combined tables; a project keeps
the options with the column ids remapped; Bootstrap reruns the report
headless; the Python script holds the scikit-learn calls; every (i) has a
topic; dark theme and phone width.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-gaussproc.py

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
XS = ['rw', 'r', 'Tu', 'Hu', 'Tl', 'Hl', 'L', 'Kw']
Y = 'log10 flow'


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('*', '').replace('<', ''))


# Pick an item from an outline's red triangle: path is the labels down the
# submenus; wait: wait for the report to run again. which: the n-th outline
# with that title.
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
           warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)), options: rep.spec.options,
           notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent) };
})()
'''

# The engine's own fit of the last report (the same payload the page sends).
ENGINE = '''
(async (y, xs, extra) => {
  const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table; const o = rep.spec.options;
  const payload = { table: t.id, rows: null, y, x: xs, correlation: o.correlation || 'gaussian', nugget: !!o.nugget, max_rows: o.maxRows ?? 400,
                    restarts: o.restarts ?? null, seed: o.seed ? Number(o.seed) : o.seedDrawn, ...(extra || {}) };
  return await SM.engine.call('gaussproc.fit', payload, t);
})
'''


def engine_js(y, xs, extra=None):
    return f'({ENGINE})({json.dumps(y)}, {json.dumps(xs)}, {json.dumps(extra or {})})'


async def triangles(page, name, least):
    r = await page.ev(TRIANGLES)
    ok = isinstance(r, dict) and not r['errors'] and r['triangles'] >= least and r['items'] > r['triangles']
    check(f'every red triangle of {name} opens, with its submenus', ok, True)
    if not ok:
        print('   ', r)


async def rerun(page):
    await page.ev('(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')


async def main():
    page = await open_page(f'{BASE}/smui.html?example=borehole', height=1200)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "gaussproc").map(f => f.module + ": " + f.error)')
    check('gaussproc.py imports in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])
    check('scikit-learn is not loaded at the start', await page.ev('(SM.engine.versions || {})["scikit-learn"] || null'), None)

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const file = SM.app.menuItems('File');
      const exs = file.find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const an = SM.app.menuItems('Analyze');
      const sm = an.find(i => i.label === 'Specialized Modeling');
      const items = (typeof sm.submenu === 'function' ? sm.submenu() : sm.submenu).filter(i => !i.separator).map(i => i.label);
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), about: SM.io.EXAMPLES.borehole.about, inFile: labels.includes(SM.io.EXAMPLES.borehole.label), items };
    })()''')
    check('?example=borehole opens the simulated borehole table', (ex['name'], ex['rows'], ex['cols']), ('Borehole', 40, XS + ['flow', Y]))
    check('it is simulated, and its notes give the function', ex['about'].startswith('Simulated') and 'borehole function' in ex['about'], True)
    check('it is in File > Examples', ex['inFile'], True)
    check('Analyze > Specialized Modeling lists Gaussian Process after Mediation', 'Gaussian Process…' in ex['items'] and ex['items'].index('Gaussian Process…') > ex['items'].index('Mediation…'), True)
    ok_flow = await page.ev('''(() => { const t = SM.app.current; const c = (n) => t.col(n).values;
      const [rw, r, Tu, Hu, Tl, Hl, L, Kw] = ['rw', 'r', 'Tu', 'Hu', 'Tl', 'Hl', 'L', 'Kw'].map(c);
      return rw.every((_, i) => { const lr = Math.log(r[i] / rw[i]); const f = 2 * Math.PI * Tu[i] * (Hu[i] - Hl[i]) / (lr * (1 + 2 * L[i] * Tu[i] / (lr * rw[i] * rw[i] * Kw[i]) + Tu[i] / Tl[i]));
        return Math.abs(c('flow')[i] - f) < 1e-5 * f && Math.abs(c('log10 flow')[i] - Math.log10(f)) < 1e-6; }); })()''')
    check('the flow is the borehole function of the inputs', ok_flow, True)

    # ---- the launch dialog
    r = await page.ev('''(async (xs, y) => {
      SM.app.launch('gaussproc');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); items.find(x => x.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      const opts = [...dlg.querySelectorAll('.sm-launch-opts label')].map(l => { const i = l.querySelector('input, select'); return [[...l.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim(), i.type === 'checkbox' ? i.checked : i.value]; });
      pick(y); role('Y').querySelector('.sm-btn').click();
      pick(y); role('X').querySelector('.sm-btn').click();
      ok.click();
      const both = dlg.querySelector('.sm-launch-msg').textContent;
      [...role('X').querySelectorAll('li')].forEach(li => li.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })));
      for (const x of xs) { pick(x); role('X').querySelector('.sm-btn').click(); }
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { roles, opts, both, options: rep.spec.options, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent), sk: SM.engine.versions['scikit-learn'] };
    })(%s, %s)''' % (json.dumps(XS), json.dumps(Y)), timeout=300)
    check('the launch dialog\'s roles: Y, X, By', r['roles'], ['Y', 'X', 'By'])
    opts = dict((k, v) for k, v in r['opts'])
    check('its options and defaults: Gaussian, no nugget, 400 rows, restarts automatic, a seed drawn',
          (opts.get('Correlation Type'), opts.get('Estimate Nugget Parameter'), opts.get('Rows to Fit, at Most'), opts.get('Optimizer Restarts'), opts.get('Random Seed')), ('gaussian', False, '400', '', ''))
    check('a column in both Y and X is refused', 'both a Y and an X' in r['both'], True)
    check('the report\'s outlines', r['outlines'][:4], [f'Gaussian Process of {Y}', 'Actual by Predicted Plot', 'Model Report', 'Marginal Model Plots'])
    check('the first call loads scikit-learn 1.8.0', r['sk'], '1.8.0')
    st = await page.ev(STATE)
    check('no errors in the report', st['errors'], [])
    check('a seed is drawn and kept with the report', isinstance(st['options'].get('seedDrawn'), int), True)
    await shot(page, 'gaussproc-01-report.png')

    # ---- the numbers against the engine's
    res = await page.ev(engine_js(Y, XS))
    mr = await page.ev(table_under_js('Model Report', 0))
    check('the Model Report\'s columns: Column, Theta, Total Sensitivity, Main Effect and an Interaction per factor', mr[0], ['Column', 'Theta', 'Total Sensitivity', 'Main Effect'] + [f'{x} Interaction' for x in XS])
    rows = {row[0]: row for row in mr[1:]}
    worst = max(abs(num(rows[rr['column']][1]) - rr['theta']) / max(1e-300, abs(rr['theta'])) for rr in res['report'])
    check.near('Theta: the engine\'s, to the digits shown (five in exponent form)', worst, 0.0, tol=1e-4)
    check('Main Effect and Total Sensitivity: the engine\'s, to 4 decimals', all(abs(num(rows[rr['column']][3]) - rr['main']) < 6e-5 and abs(num(rows[rr['column']][2]) - rr['total']) < 6e-5 for rr in res['report']), True)
    kv = {row[0]: row[1] for row in (await page.ev(table_under_js('Model Report', 1)))}
    check.near('Mu', num(kv['Mu']), res['mu'], tol=1e-6)
    check.near('Sigma²', num(kv['Sigma²']), res['sigma2'], tol=1e-6)
    check.near('−2 LogLikelihood', num(kv['−2 LogLikelihood']), res['m2ll'], tol=1e-6)
    check('no Nugget without Estimate Nugget Parameter', 'Nugget' in kv, False)
    main = {rr['column']: rr['main'] for rr in res['report']}
    check('the borehole: rw has by far the largest Main Effect', max(main, key=main.get) == 'rw' and main['rw'] > 0.75, True)
    check('... r, Tu and Tl hardly any', max(abs(main['r']), abs(main['Tu']), abs(main['Tl'])) < 0.01, True)
    tr = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => /actual by jackknife predicted/.test(p.opts.title));
      return { x: p.traces[0].x, y: p.traces[0].y, rows: p.rows[0], n: p.traces.filter(t => t.mode === 'markers').length }; })()''')
    check('Actual by Predicted: the jackknife predictions against the actual values, linked to the rows fitted', (tr['rows'], tr['n']), (res['fit_rows'], 1))
    check.near('... the points are the engine\'s jackknife predictions', max(abs(a - b) for a, b in zip(tr['x'], res['jackknife'])), 0.0, tol=1e-12)
    jk = {row[0]: row[1] for row in (await page.ev(table_under_js('Actual by Predicted Plot', 0)))}
    check.near('... the jackknife RSquare beside it', num(jk['Jackknife RSquare']), res['jack_rsquare'], tol=1e-6)
    check('the borehole is smooth: the jackknife RSquare is above 0.99', res['jack_rsquare'] > 0.99, True)
    check('40 rows fitted: 2 optimizer restarts by default (at most 150 rows)', res['restarts'], 2)

    # ---- linking
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => /actual by jackknife predicted/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      p._click({ points: [{ curveNumber: 0, pointNumber: 7 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[0][3], p.rows[0][11]]);
      const sp = p.box.data[0].selectedpoints;
      t.select([]);
      return { sel, want: [p.rows[0][7]], sp };
    })()''')
    check('a click on a jackknife point selects its row', r['sel'], r['want'])
    check('rows selected in the table highlight their points', r['sp'], [3, 11])
    pos = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => /actual by jackknife predicted/.test(p.opts.title));
      const gd = p.box, xa = gd._fullLayout.xaxis, ya = gd._fullLayout.yaxis;
      const xs = p.traces[0].x, ys = p.traces[0].y;
      let best = 0, bestD = -1;
      for (let k = 0; k < xs.length; k++) { let d = Infinity; for (let m = 0; m < xs.length; m++) if (m !== k) d = Math.min(d, ((xs[k] - xs[m]) / (xa.range[1] - xa.range[0])) ** 2 + ((ys[k] - ys[m]) / (ya.range[1] - ya.range[0])) ** 2); if (d > bestD) { bestD = d; best = k; } }
      const b = gd.getBoundingClientRect();
      return { x: b.left + xa._offset + xa.l2p(xs[best]), y: b.top + ya._offset + ya.l2p(ys[best]), row: p.rows[0][best] };
    })()''')
    await page.click(pos['x'], pos['y'])
    await asyncio.sleep(0.4)
    sel = await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()')
    check('a mouse click on a point selects that row', sel, [pos['row']])
    await page.mouse('mouseMoved', 2, 2)
    await page.ev('SM.app.reports[SM.app.reports.length - 1].table.select([])')

    await triangles(page, 'the report (one Y: its items on the top red triangle)', 1)

    # ---- the red triangle changes the model; Redo keeps it
    await page.ev(pick_js('*top*', ['Correlation Type', 'Matérn ν = 5/2 (not JMP\'s Cubic)']))
    mr2 = await page.ev(table_under_js('Model Report', 0))
    st = await page.ev(STATE)
    check('Matérn 5/2: no Theta, the length scale instead', ('Theta' in mr2[0], 'Length Scale' in mr2[0]), (False, True))
    check('... and its sensitivities are quasi-Monte Carlo estimates, said so', any('pick-freeze quasi-Monte Carlo' in t for t in st['notes']), True)
    rm = await page.ev(engine_js(Y, XS, {'correlation': 'matern52'}))
    check('... the engine\'s Matérn kernel', rm['kernel'].count('Matern') == 1 and 'nu=2.5' in rm['kernel'], True)
    await page.ev(pick_js('*top*', ['Estimate Nugget Parameter']))
    kv2 = {row[0]: row[1] for row in (await page.ev(table_under_js('Model Report', 1)))}
    rn = await page.ev(engine_js(Y, XS, {'correlation': 'matern52', 'nugget': True}))
    check.near('Estimate Nugget Parameter: the Nugget, the engine\'s', num(kv2['Nugget']), rn['nugget'], tol=1e-6)
    await rerun(page)
    st = await page.ev(STATE)
    check('Redo keeps the correlation and the nugget', (st['options'].get('correlation'), st['options'].get('nugget')), ('matern52', True))
    await page.ev(pick_js('*top*', ['Correlation Type', 'Gaussian']))
    await page.ev(pick_js('*top*', ['Estimate Nugget Parameter']))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await (%s)('*top*', ['Fit Settings…'], false, 0);
      for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
      const d = [...document.querySelectorAll('.sm-dialog')].pop();
      const inputs = d.querySelectorAll('.sm-form input');
      inputs[1].value = '0'; inputs[2].value = '123';
      const done = new Promise(res => rep.on('done', res));
      d.querySelector('.sm-dialog-foot .primary').click();
      await done;
      return { restarts: rep.spec.options.restarts, seed: rep.spec.options.seed, notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent).filter(t => /by maximum likelihood/.test(t)) };
    })()''' % PICK)
    check('Fit Settings: no restarts and a seed of its own', (r['restarts'], r['seed'], 'starts' in r['notes'][0]), (0, '123', False))

    # ---- the profiler
    await page.ev(pick_js('*top*', ['Profiler']))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Prediction Profiler');
      const box = head.parentElement;
      const val = box.querySelector('.sm-prof-val').textContent, ci = box.querySelector('.sm-prof-ci').textContent;
      const o = rep.spec.options;
      const pr = await SM.engine.call('gaussproc.profile', { table: t.id, rows: null, y: 'log10 flow', x: %s, correlation: 'gaussian', nugget: false, max_rows: 400, restarts: 0, seed: 123, alpha: 0.05 }, t);
      return { val, ci, cur: pr.responses[0].current, n: pr.factors.length, plots: box.querySelectorAll('.sm-plot').length };
    })()''' % json.dumps(XS))
    check.near('the profiler shows the engine\'s prediction at the factors\' means', num(r['val']), r['cur']['pred'], tol=1e-5)
    lo, hi = [num(v) for v in r['ci'].strip('[]').split(',')]
    check.near('... and its band from the process\'s standard deviation', lo + hi, r['cur']['lower'] + r['cur']['upper'], tol=1e-4)
    check('... one plot per factor', r['plots'], r['n'])

    # ---- Save Columns
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      for (const it of ['Save Prediction', 'Save Std Error', 'Save Jackknife Predicted Values']) { await (%s)('*top*', ['Save Columns', it], false, 0); await new Promise(r => setTimeout(r, 700)); }
      const sv = await SM.engine.call('gaussproc.save', { table: t.id, rows: null, y: 'log10 flow', x: %s, correlation: 'gaussian', nugget: false, max_rows: 400, restarts: 0, seed: 123 }, t);
      const c = (n) => t.col(n) ? t.col(n).values : null;
      const p = c('Predicted log10 flow'), s = c('StdErr Pred log10 flow'), j = c('Jackknife Predicted log10 flow');
      return { have: [!!p, !!s, !!j], pred: p && sv.rows.every((r, k) => Math.abs(p[r] - sv.pred[k]) < 1e-12), sd: s && sv.rows.every((r, k) => Math.abs(s[r] - sv.std[k]) < 1e-15 + 1e-9 * sv.std[k]),
               jack: j && sv.jack_rows.every((r, k) => Math.abs(j[r] - sv.jack[k]) < 1e-12) };
    })()''' % (PICK, json.dumps(XS)))
    check('Save Columns: Predicted, StdErr Pred and Jackknife Predicted log10 flow', r['have'], [True, True, True])
    check('... the engine\'s predictions, standard deviations and jackknife values', (r['pred'], r['sd'], r['jack']), (True, True, True))
    script = await page.ev('SM.app.reports[SM.app.reports.length - 1].pythonScript()')
    check('the Python script holds the scikit-learn calls and the helpers', all(s in script for s in ('GaussianProcessRegressor(', 'def jackknife(', 'def fanova_rbf(', 'def indices(', 'normalize_y=True')), True)
    await shot(page, 'gaussproc-02-options.png')

    # ---- a Bootstrap of the Model Report reruns the report headless
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'gaussproc');
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Model Report');
      const tbl = head.parentElement.querySelector('table.sm-rt');
      const col = tbl._rt.columns.find(c => c.label === 'Main Effect');
      const n0 = SM.app.tables.length;
      const t = await SM.bootstrap.run(tbl, col, { B: 8, seed: 1, show: false });
      const rw = t.col('rw').values;
      return { cols: t.columns.map(c => c.name), n: t.nrows, first: rw[0], finite: rw.every(Number.isFinite), spread: Math.max(...rw) - Math.min(...rw), errors: [...rep.body.querySelectorAll('.sm-ob-error')].length };
    })()''', timeout=900)
    check('Bootstrap of the Main Effect: a column per factor, a row per sample', (r['cols'][:3], r['n']), (['BootID', 'rw', 'r'], 9))
    check('... sample 0 is the report, the resamples refit (their values differ)', (abs(r['first'] - main['rw']) < 0.05, r['finite'], r['spread'] > 0), (True, True, True))

    # ---- Rows to Fit caps a large table
    r = await page.ev('''(async () => {
      const g = SM.util.rng('gp cap');
      const n = 600, a = [], b = [], c = [], y = [];
      for (let i = 0; i < n; i++) { const x1 = g.u(), x2 = g.u(), x3 = g.u(); a.push(x1); b.push(x2); c.push(x3); y.push(Math.sin(4 * x1) + x2 * x2 + 0.05 * g.normal()); }
      const t = new SM.Table({ name: 'Cap', source: 'simulated', columns: [{ name: 'y', dataType: 'numeric', values: y }, { name: 'x1', dataType: 'numeric', values: a }, { name: 'x2', dataType: 'numeric', values: b }, { name: 'x3', dataType: 'numeric', values: c }] });
      SM.app.addTable(t);
      return t.id;
    })()''')
    rep = await page.ev(open_report_js('gaussproc', {'y': ['y'], 'x': ['x1', 'x2', 'x3']}, {'maxRows': 100, 'nugget': True}), timeout=300)
    check('a 600-row table with Rows to Fit 100: no errors', rep['errors'], [])
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const res = await SM.engine.call('gaussproc.fit', { table: t.id, rows: null, y: 'y', x: ['x1', 'x2', 'x3'], correlation: 'gaussian', nugget: true, max_rows: 100, restarts: null, seed: rep.spec.options.seedDrawn }, t);
      const p = rep.plots.find(p => /actual by jackknife predicted/.test(p.opts.title));
      const marks = p.traces.filter(t => t.mode === 'markers');
      return { n_fit: res.n_fit, other: res.other_rows.length, rows0: p.rows[0], fit: res.fit_rows, rows1: p.rows[1], other_rows: res.other_rows, marks: marks.length,
               note: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent).find(t => /fitted to/.test(t)) || '' };
    })()''')
    check('... the model is fitted to 100 rows drawn from the seed, the note says so', (r['n_fit'], r['other'], 'fitted to 100 of them' in r['note']), (100, 500, True))
    check('... Actual by Predicted: the 100 jackknife points and the 500 other rows predicted, each linked', (r['marks'], r['rows0'] == r['fit'], r['rows1'] == r['other_rows']), (2, True, True))

    # ---- several Y's, and By
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Borehole").id)')
    rep = await page.ev(open_report_js('gaussproc', {'y': ['flow', Y], 'x': XS}, {'nugget': True}), timeout=300)
    check('two Y\'s: an outline per response, each with its reports', ([o for o in rep['outlines'] if o.startswith('Response ')], rep['outlines'].count('Model Report'), rep['errors']), (['Response flow', f'Response {Y}'], 2, []))
    await triangles(page, 'the two-Y report', 3)
    await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Borehole'); if (!t.col('half')) t.addColumn({ name: 'half', dataType: 'character', values: t.col('rw').values.map((_, i) => (i < 20 ? 'first' : 'second')) }); })()''')
    rep = await page.ev(open_report_js('gaussproc', {'y': [Y], 'x': ['rw', 'Hu', 'Hl', 'L'], 'by': ['half']}, {}), timeout=300)
    check('By half: one analysis per group', [o for o in rep['outlines'] if o.startswith('Gaussian Process')], [f'Gaussian Process of {Y} half=first', f'Gaussian Process of {Y} half=second'])
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const tbls = [...rep.body.querySelectorAll('table.sm-rt')].filter(t => t.dataset.rtKey === 'gpreport');
      const combined = SM.report.combineRT(tbls, 'x');
      return { n: tbls.length, groups: tbls.map(t => t.dataset.group), rows: combined.nrows, notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent).filter(t => /rows with log10 flow/.test(t)) };
    })()''')
    check('each group has its Model Report, which combine into one table', (r['n'], r['groups'], r['rows']), (2, ['half=first', 'half=second'], 8))
    check('each group fits its own 20 rows', [t.split(' ')[0] for t in r['notes']], ['20', '20'])

    # ---- a project keeps the options, the column ids remapped
    r = await page.ev('''(async () => {
      const t = SM.app.tables.find(t => t.name === 'Borehole');
      const y = t.col('log10 flow');
      const rep = SM.app.openReport(SM.platforms.get('gaussproc'), { roles: { y: [y.id], x: ['rw', 'Hu', 'Hl', 'L'].map(n => t.col(n).id) }, options: { correlation: 'matern32', nugget: true, seed: '5', [y.id + '|profiler']: true, [y.id + '|marginal']: false } }, t);
      await new Promise(res => rep.on('done', res));
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.closeReport(rep);
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const y2 = back.table.col('log10 flow');
      const out = { newTable: back.table !== t, profiler: back.spec.options[y2.id + '|profiler'], corr: back.spec.options.correlation, errors: [...back.body.querySelectorAll('.sm-ob-error')].length,
                    heads: [...back.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3')].map(h => h.textContent) };
      SM.app.closeReport(back);
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })()''', timeout=600)
    check('an opened project has its own table', r['newTable'], True)
    check('and keeps a per-response option by the new column id (the profiler) and the correlation', (r['profiler'], r['corr']), (True, 'matern32'))
    check('and draws the same outlines without errors', ('Prediction Profiler' in r['heads'], 'Marginal Model Plots' in r['heads'], r['errors']), (True, False, 0))

    # ---- the (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-gaussproc"); const row = document.getElementById("help-p-gaussproc"); return row ? row.textContent : null; })()')
    check('the platform has its line in Help, with scikit-learn\'s GaussianProcessRegressor', bool(helps) and 'sklearn.gaussian_process.GaussianProcessRegressor' in helps, True)
    topics = await page.ev('Object.keys(SM.platforms.get("gaussproc").topics)')
    check('its topics', sorted(topics), sorted(['p:gaussproc', 'p:gaussproc:abp', 'p:gaussproc:report', 'p:gaussproc:marginal']))

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "gaussproc" && r.table.name === "Cap")))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2.5)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => r.platform.id === 'gaussproc'); return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)) }; })()''')
    check('the dark theme redraws the reports without errors', st['errors'], [])
    col = await page.ev('(() => { const rep = SM.app.reports.find(r => r.platform.id === "gaussproc" && r.table.name === "Cap"); const p = rep.plots.find(p => /actual by jackknife/.test(p.opts.title)); return p.traces[1].marker.color; })()')
    check('the rows not fitted take the dark theme\'s green', col, '#5fb36b')
    await shot(page, 'gaussproc-03-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports.find(r => r.platform.id === "gaussproc"); SM.app.showTab(SM.app.tabOf(rep)); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')
    await asyncio.sleep(1.0)
    r = await page.ev('''(() => {
      const rep = SM.app.reports.find(r => r.platform.id === "gaussproc");
      const body = rep.body.getBoundingClientRect();
      // a plot counts where it is seen: the profiler's grid scrolls in its own box
      const boxes = rep.plots.filter(p => p.drawn).map(p => (p.box.closest('.sm-profwrap') || p.box).getBoundingClientRect().right);
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Model Report');
      const tbl = head.parentElement.querySelector('table.sm-rt');
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length,
               body: rep.body.scrollWidth <= rep.body.clientWidth + 1, scrollers: tbl.scrollWidth > tbl.clientWidth + 1 };
    })()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the graphs fit the phone\'s width', (r['plots'], r['n'] >= 2), (True, True))
    check('the wide Model Report scrolls inside its own box, not the whole report', (r['body'], r['scrollers']), (True, True))
    await shot(page, 'gaussproc-04-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
