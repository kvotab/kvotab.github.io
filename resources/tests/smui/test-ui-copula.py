#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Multivariate Methods > Copulas.

The simulated Drought example opens from the URL and File > Examples, and
the platform sits in Analyze > Multivariate Methods after Multidimensional
Scaling; the launch dialog's own part picks the copulas, the rotations, the
estimation and the margins (and strikes out the one-pair families for
three columns); the report's Kendall's tau and pseudo-observations are the
ones computed here from the table, Clayton (the example's true copula) has
the smallest AIC and its interval covers the true θ = 2; points select
their rows (one by a real mouse click) and table selections highlight
them; every red triangle opens; the red triangles change the estimation,
the standard errors, the copula shown, the scale and the pair (Redo keeps
them); the joint-probability calculator gives C(F1(x), F2(y)) computed
here from the engine's own fit; goodness of fit, Simulate (a new table
equal to the engine's draws, and the comparison outline) and Save work;
By gives one analysis per group with combined tables; three columns give
the scatterplot matrix and the elliptical copulas only; negative
dependence brings the 90° and 270° rotations and the corner tails; a
project keeps the options with the column ids remapped; the Python script
holds the statsmodels calls; every (i) has a topic; the reports draw in the
dark theme and at phone width without a sideways page scroll.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-copula.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import math
import os
import sys
from statistics import NormalDist

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
X, Y = 'soil moisture (%)', 'stream flow (m³/s)'


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('%', '').replace('*', '').replace('<', ''))


# Pick an item from an outline's red triangle: path is the labels down the
# submenus; wait: wait for the report to run again. which: the n-th outline
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


# The same, for an item that opens a form: fill(dialog) runs on the form,
# then OK, then the report runs again.
PICK_FORM = '''
(async (title, path, fill) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await (%s)(title, path, false, 0);
  for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 100));
  const dlgs = [...document.querySelectorAll('.sm-dialog')];
  const d = dlgs[dlgs.length - 1];
  const done = new Promise(res => rep.on('done', res));
  (new Function('d', fill))(d);
  d.querySelector('.sm-dialog-foot .primary').click();
  await done;
  return [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
})
''' % PICK


def pick_form_js(title, path, fill):
    return f'({PICK_FORM})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(fill)})'


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

# The table of the drought example computed here: Kendall's tau-b of the two
# columns, and each row's average rank over n + 1.
PAGE_STATS = '''
(() => {
  const t = SM.app.tables.find(t => t.name === 'Drought');
  const x = t.col('%s').values, y = t.col('%s').values;
  const n = x.length;
  let S = 0, tx = 0, ty = 0;
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
    const a = Math.sign(x[i] - x[j]), b = Math.sign(y[i] - y[j]);
    S += a * b; if (a === 0) tx++; if (b === 0) ty++;
  }
  const n0 = n * (n - 1) / 2;
  const rx = SM.util.ranks(x).map(r => r / (n + 1)), ry = SM.util.ranks(y).map(r => r / (n + 1));
  return { tau: S / Math.sqrt((n0 - tx) * (n0 - ty)), rx, ry, n };
})()
''' % (X, Y)

# The drought table's last report's plot of pseudo-observations: its trace.
PSEUDO = '''
(() => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const p = rep.plots.find(p => /^Pseudo-observations of/.test(p.opts.title));
  if (!p) return null;
  return { x: p.traces[0].x, y: p.traces[0].y, rows: p.rows[0], contours: p.traces.filter(t => t.type === 'contour').length, title: p.opts.title,
           names: p.traces.filter(t => t.type === 'contour').map(t => t.name), labels: p.traces.filter(t => t.type === 'contour').every(t => t.contours.showlabels),
           xtitle: p.userLayout.xaxis.title.text, range: p.userLayout.xaxis.range, color: (p.traces.find(t => t.type === 'contour') || {}).line?.color };
})()
'''


async def triangles(page, name, least):
    r = await page.ev(TRIANGLES)
    ok = isinstance(r, dict) and not r['errors'] and r['triangles'] >= least and r['items'] > r['triangles']
    check(f'every red triangle of {name} opens, with its submenus', ok, True)
    if not ok:
        print('   ', r)


async def rerun(page):
    await page.ev('(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')


async def main():
    page = await open_page(f'{BASE}/smui.html?example=dependence', height=1200)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "copula").map(f => f.module + ": " + f.error)')
    check('copula.py imports in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const file = SM.app.menuItems('File');
      const exs = file.find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const an = SM.app.menuItems('Analyze');
      const mm = an.find(i => i.label === 'Multivariate Methods');
      const items = (typeof mm.submenu === 'function' ? mm.submenu() : mm.submenu).filter(i => !i.separator).map(i => i.label);
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), about: SM.io.EXAMPLES.dependence.about, inFile: labels.includes(SM.io.EXAMPLES.dependence.label), items };
    })()''')
    check('?example=dependence opens the simulated drought table', (ex['name'], ex['rows'], ex['cols']), ('Drought', 500, ['day', 'region', X, Y]))
    check('it is simulated, and its notes give the true copula', ex['about'].startswith('Simulated') and 'Clayton copula with θ = 2' in ex['about'], True)
    check('it is in File > Examples', ex['inFile'], True)
    check('Analyze > Multivariate Methods lists Copulas after Multidimensional Scaling', 'Copulas…' in ex['items'] and ex['items'].index('Copulas…') > ex['items'].index('Multidimensional Scaling…'), True)

    # ---- the launch dialog
    r = await page.ev('''(async () => {
      SM.app.launch('copula');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const checks = [...dlg.querySelectorAll('.sm-cop-check input')];
      const fam = [...dlg.querySelectorAll('.sm-cop-checks .sm-cop-check')].map(l => [l.textContent, l.querySelector('input').checked]);
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); items.find(x => x.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      pick('%s'); role('Y, Columns').querySelector('.sm-btn').click();
      ok.click();
      const needTwo = dlg.querySelector('.sm-launch-msg').textContent;
      pick('%s'); role('Y, Columns').querySelector('.sm-btn').click();
      pick('day'); role('Y, Columns').querySelector('.sm-btn').click();
      const struck3 = [...dlg.querySelectorAll('.sm-cop-checks .sm-cop-check.is-off')].map(l => l.textContent);
      const hint3 = dlg.querySelector('.sm-cop-hint').textContent;
      // take day out again: double click it in the role
      [...role('Y, Columns').querySelectorAll('li')].find(li => li.textContent === 'day').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      const struck2 = dlg.querySelectorAll('.sm-cop-checks .sm-cop-check.is-off').length;
      const boxes = [...dlg.querySelectorAll('.sm-cop-checks input')];
      boxes.forEach(b => { b.checked = false; });
      ok.click();
      const noFamily = dlg.querySelector('.sm-launch-msg').textContent;
      boxes.forEach(b => { b.checked = true; });
      const marg = [...dlg.querySelectorAll('.sm-cop-opts .sm-cop-check input')][0];
      marg.checked = true;
      const selects = [...dlg.querySelectorAll('.sm-cop-opts select')];
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { fam, needTwo, struck3, hint3, struck2, noFamily, selects: selects.map(s => [s.getAttribute('aria-label'), s.value]), options: rep.spec.options, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent) };
    })()''' % (X, Y))
    check('the launch dialog offers the six copulas, all ticked', r['fam'], [['Gaussian', True], ['Student t', True], ['Clayton', True], ['Frank', True], ['Gumbel', True], ['Independence', True]])
    check('one column is not enough', 'at least 2' in r['needTwo'], True)
    check('with three columns Clayton, Frank and Gumbel are struck out', (r['struck3'], 'only the Gaussian, Student t' in r['hint3']), (['Clayton', 'Frank', 'Gumbel'], True))
    check('and back with two', r['struck2'], 0)
    check('no copula ticked: an error', 'choose at least one' in r['noFamily'], True)
    check('the rotations and estimation start on their defaults', r['selects'], [['Rotations of Clayton and Gumbel', 'auto'], ['Estimation method', 'mpl']])
    check('the options reach the report', (r['options']['families'], r['options']['rotations'], r['options']['method'], r['options']['margins']), (['gaussian', 't', 'clayton', 'frank', 'gumbel', 'indep'], 'auto', 'mpl', True))
    check('the report\'s outlines', r['outlines'], [f'Copulas of {X} and {Y}', 'Pseudo-Observations', 'Dependence', 'Copula Comparison', 'Margins', X, Y])
    st = await page.ev(STATE)
    check('no errors in the report', st['errors'], [])
    await shot(page, 'copula-01-report.png')

    # ---- the numbers against the table
    ps = await page.ev(PAGE_STATS)
    rc = await page.ev(table_under_js('Dependence', 0))
    check.near('Kendall\'s τb = the one computed here', num(rc[1][2]), round(ps['tau'], 4), tol=1e-9)
    pp = await page.ev(PSEUDO)
    rows = pp['rows']
    check('the pseudo-observations are the ranks over n + 1 computed here', max(max(abs(a - ps['rx'][r_]), abs(b - ps['ry'][r_])) for a, b, r_ in zip(pp['x'], pp['y'], rows)) < 1e-12, True)
    check('one point per row, on the unit square', (len(rows), pp['range']), (500, [0, 1]))
    check('the contours are the copula\'s density at 1/2, 2 and 4 at least, labelled', all(n_ in pp['names'] for n_ in ('density 1/2', 'density 2', 'density 4')) and pp['labels'], True)
    cmp_ = await page.ev(table_under_js('Copula Comparison', 0))
    fams = [row[0] for row in cmp_[1:]]
    aics = [num(row[3]) for row in cmp_[1:]]
    check('Clayton, the true copula, has the smallest AIC', fams[0], 'Clayton')
    check('the fits are sorted by AIC', aics == sorted(aics), True)
    check('survival copulas join for a positive τ', ('Survival Gumbel (180°)' in fams, 'Survival Clayton (180°)' in fams, any('90°' in f for f in fams)), (True, True, False))
    pe = await page.ev(table_under_js('Copula Comparison', 1))
    cl = next(row for row in pe[1:] if row[0] == 'Clayton')
    check(f'the Clayton interval covers the true θ = 2 ({cl[2]}, {cl[4]} to {cl[5]})', num(cl[4]) < 2 < num(cl[5]), True)
    impl = await page.ev(table_under_js('Dependence', 1))
    clm = next(row for row in impl[1:] if row[0] == 'Clayton')
    th = num(cl[2])
    check.near('the implied τ is θ/(θ + 2)', num(clm[1]), round(th / (th + 2), 4), tol=2e-4)
    check.near('and λL = 2^(−1/θ)', num(clm[3]), round(2 ** (-1 / th), 4), tol=2e-4)

    # ---- linking
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => /^Pseudo-observations of/.test(p.opts.title));
      p._click({ points: [{ curveNumber: 0, pointNumber: 7 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[0][3], p.rows[0][11]]);
      const sp = p.box.data[0].selectedpoints;
      const j = rep.plots.find(p => / with the joint model$/.test(p.opts.title));
      const spj = j.box.data[0].selectedpoints;
      t.select([]);
      return { sel, want: [p.rows[0][7]], sp, spj };
    })()''')
    check('a click on a pseudo-observation selects its row', r['sel'], r['want'])
    check('rows selected in the table highlight their points, in both graphs', (r['sp'], r['spj']), ([3, 11], [3, 11]))
    pos = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => /^Pseudo-observations of/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      await new Promise(r => setTimeout(r, 300));
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      const gd = p.box, xa = gd._fullLayout.xaxis, ya = gd._fullLayout.yaxis;
      // the point furthest from the others, so that the click hits it alone
      const xs = p.traces[0].x, ys = p.traces[0].y;
      let best = 0, bestD = -1;
      for (let k = 0; k < xs.length; k++) { let d = Infinity; for (let m = 0; m < xs.length; m++) if (m !== k) d = Math.min(d, (xs[k] - xs[m]) ** 2 + (ys[k] - ys[m]) ** 2); if (d > bestD) { bestD = d; best = k; } }
      const b = gd.getBoundingClientRect();
      return { x: b.left + xa._offset + xa.l2p(xs[best]), y: b.top + ya._offset + ya.l2p(ys[best]), row: p.rows[0][best] };
    })()''')
    await page.click(pos['x'], pos['y'])
    await asyncio.sleep(0.4)
    sel = await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()')
    check('a mouse click on a point selects that row', sel, [pos['row']])
    await page.mouse('mouseMoved', 2, 2)   # out of the way of the menus opened below
    await page.ev('SM.app.reports[SM.app.reports.length - 1].table.select([])')

    await triangles(page, 'the report', 7)

    # ---- the red triangles change what is computed; Redo keeps it
    await page.ev(pick_js('Copula Comparison', ['Standard Errors', 'Rank-Corrected (Genest, Ghoudi and Rivest)']))
    pe2 = await page.ev(table_under_js('Copula Comparison', 1))
    cl2 = next(row for row in pe2[1:] if row[0] == 'Clayton')
    check('rank-corrected standard errors are larger than the Hessian\'s', num(cl2[3]) > num(cl[3]), True)
    await page.ev(pick_js('Copula Comparison', ['Estimation Method', 'Inversion of Kendall\'s τ']))
    pe3 = await page.ev(table_under_js('Copula Comparison', 1))
    cl3 = next(row for row in pe3[1:] if row[0] == 'Clayton')
    tau4 = ps['tau']
    check.near('by τ inversion Clayton\'s θ = 2τ/(1 − τ)', num(cl3[2]), 2 * tau4 / (1 - tau4), tol=1e-6)
    await rerun(page)
    st = await page.ev(STATE)
    check('Redo keeps the method and the standard errors', (st['options'].get('method'), st['options'].get('se')), ('itau', 'rank'))
    await page.ev(pick_js('Copula Comparison', ['Estimation Method', 'Maximum Pseudo-Likelihood']))
    # a click on a comparison line shows that copula
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim().startsWith('Copula Comparison'));
      const tr = [...head.parentElement.querySelectorAll('table.sm-rt')][0].querySelectorAll('tbody tr');
      const line = [...tr].find(x => x.cells[0].textContent === 'Gaussian');
      const done = new Promise(res => rep.on('done', res));
      line.click();
      await done;
      const p = rep.plots.find(p => /^Pseudo-observations of/.test(p.opts.title));
      const bold = [...rep.body.querySelectorAll('td.sm-cop-shown')].map(td => td.textContent).filter(t => /^[A-Z]/.test(t));
      return { shown: rep.spec.options.shown, note: p.box.parentElement.parentElement.textContent.includes('fitted Gaussian copula'), bold: [...new Set(bold)] };
    })()''')
    check('a click on the Gaussian line shows the Gaussian copula', (r['shown'], r['note']), ('gaussian', True))
    check('and marks it in the tables', 'Gaussian' in r['bold'] and 'Clayton' not in r['bold'], True)
    await page.ev(pick_js('Pseudo-Observations', ['Scale', 'Normal Scores']))
    pp2 = await page.ev(PSEUDO)
    check.near('normal scores: Φ⁻¹ of the pseudo-observations', pp2['x'][0], NormalDist().inv_cdf(pp['x'][0]), tol=1e-6)
    check('on the normal-score axes', (pp2['xtitle'], pp2['range']), (f'{X}: normal score', [-3.3, 3.3]))
    await page.ev(pick_js('Pseudo-Observations', ['Contours Of', 'Clayton']))
    await page.ev(pick_js('Pseudo-Observations', ['Scale', 'Uniform (u, v)']))

    # ---- margins and the joint probabilities
    mg = await page.ev(table_under_js(X, 0))
    check('soil moisture: Weibull (its true margin) has the smallest AICc', [row[1] for row in mg[1:] if row[0] == '✓'], ['Weibull'])
    mg2 = await page.ev(table_under_js(Y, 0))
    check('stream flow: lognormal (its true margin)', [row[1] for row in mg2[1:] if row[0] == '✓'], ['Lognormal'])
    await page.ev(pick_js(f'Copulas of {X} and {Y}', ['Joint Probabilities']))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim().startsWith('Joint Probabilities'));
      const box = head.parentElement;
      const [ix, iy] = box.querySelectorAll('.sm-cop-input');
      ix.value = '20'; iy.value = '3.5';
      const done = new Promise(res => rep.on('done', res));
      [...box.querySelectorAll('button')].find(b => b.textContent === 'Compute').click();
      await done;
      const box2 = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim().startsWith('Joint Probabilities')).parentElement;
      const cells = [...box2.querySelectorAll('table.sm-rt tbody tr')].map(tr => [...tr.cells].map(c => c.textContent));
      // the engine's own fit and margins, and the Clayton copula and the Weibull and lognormal cdfs written here
      const t = rep.table;
      const fit = await SM.engine.call('copula.fit', { table: t.id, rows: null, columns: ['%s', '%s'], families: rep.spec.options.families, method: 'mpl', rotations: 'auto', se: rep.spec.options.se }, t);
      const m = await SM.engine.call('copula.margins', { table: t.id, rows: null, columns: ['%s', '%s'] }, t);
      const th = fit.fits.find(f => f.family === 'clayton').values[0];
      const [wb, ln] = m.columns.map(c => c.chosen.values);
      const u = 1 - Math.exp(-((20 / wb[0]) ** wb[1]));
      const v = SM.util.pnorm((Math.log(3.5) - ln[0]) / ln[1]);
      const C = (u ** -th + v ** -th - 1) ** (-1 / th);
      const x = t.col('%s').values, y = t.col('%s').values;
      let obs = 0; for (let i = 0; i < x.length; i++) if (x[i] <= 20 && y[i] <= 3.5) obs++;
      return { cells, u, v, C, gt: (1 - u - v + C) / (1 - u), obs: obs / x.length, at: rep.spec.options.calcAt, dists: m.columns.map(c => c.chosen.dist) };
    })()''' % (X, Y, X, Y, X, Y))
    check('the calculator keeps its point', r['at'], {'x': 20, 'y': 3.5})
    check('the margins it uses: Weibull and lognormal', r['dists'], ['weibull', 'lognormal'])
    cells = {row[0]: row for row in r['cells']}
    check.near('P(X ≤ x) = the Weibull cdf', num(cells[f'P({X} ≤ x)'][1]), round(r['u'], 4), tol=1e-9)
    check.near('P(Y ≤ y) = the lognormal cdf', num(cells[f'P({Y} ≤ y)'][1]), round(r['v'], 4), tol=1e-6)
    check.near('P(both ≤) = C(u, v) of the fitted Clayton copula, computed here', num(cells[f'P({X} ≤ x and {Y} ≤ y)'][1]), r['C'], tol=6e-4)
    check.near('P(Y > y | X > x) = (1 − u − v + C)/(1 − u)', num(cells[f'P({Y} > y | {X} > x)'][1]), r['gt'], tol=6e-4)
    check.near('independence: uv', num(cells[f'P({X} ≤ x and {Y} ≤ y)'][2]), r['u'] * r['v'], tol=6e-4)
    check.near('the observed share', num(cells[f'P({X} ≤ x and {Y} ≤ y)'][3]), r['obs'], tol=1e-9)

    # ---- tail concentration, goodness of fit
    await page.ev(pick_js('Dependence', ['Tail Concentration Function']))
    st = await page.ev(STATE)
    check('the tail concentration function, one panel per copula', 'Tail Concentration Function' in st['outlines'], True)
    await page.ev(pick_form_js('Copula Comparison', ['Goodness of Fit…'], "const i = d.querySelectorAll('.sm-form input'); i[0].value = '30'; i[1].value = '3';"), timeout=900)
    gf = await page.ev(table_under_js('Goodness of Fit', 0))
    ps_ = {row[0]: num(row[2]) for row in gf[1:]}
    check('goodness of fit: Clayton is not rejected, independence is', (ps_['Clayton'] > 0.05, ps_['Independence'] < 0.05), (True, True))
    check('in the order of the comparison', gf[1][0], 'Clayton')
    st = await page.ev(STATE)
    check('Redo keeps the bootstrap settings', st['options'].get('gof'), {'B': 30, 'seed': 3})
    await shot(page, 'copula-02-options.png')

    # ---- Simulate: a new table, the same as the engine's draws
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await (%s)('*top*', ['Simulate…'], false, 0);
      for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
      const d = [...document.querySelectorAll('.sm-dialog')].pop();
      const inputs = d.querySelectorAll('.sm-form input');
      inputs[0].value = '600'; inputs[1].value = '5';
      const nt = SM.app.tables.length;
      const done = new Promise(res => rep.on('done', res));
      d.querySelector('.sm-dialog-foot .primary').click();
      await done;
      for (let i = 0; i < 60 && SM.app.tables.length === nt; i++) await new Promise(r => setTimeout(r, 100));
      const t = SM.app.tables[SM.app.tables.length - 1];
      const src = rep.table;
      const fit = await SM.engine.call('copula.fit', { table: src.id, rows: null, columns: ['%s', '%s'], families: rep.spec.options.families, method: 'mpl', rotations: 'auto', se: rep.spec.options.se }, src);
      const m = await SM.engine.call('copula.margins', { table: src.id, rows: null, columns: ['%s', '%s'] }, src);
      const f = fit.fits.find(f => f.family === 'clayton');
      const sim = await SM.engine.call('copula.simulate', { table: src.id, rows: null, columns: ['%s', '%s'], family: 'clayton', params: f.values, margins: m.columns.map(c => ({ dist: c.chosen.dist, values: c.chosen.values })), n: 600, seed: 5, scale: 'data' }, src);
      const same = t.columns.every((c, k) => c.values.every((v, i) => v === sim.values[k][i]));
      SM.app.showTab(SM.app.tabOf(rep));
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), notes: t.notes, same, outlines: [...rep.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent), sc: rep.spec.options.simCompare };
    })()''' % (PICK, X, Y, X, Y, X, Y), timeout=600)
    check('Simulate makes a table of 600 rows with the two columns', (r['name'], r['rows'], r['cols']), ('Drought simulated', 600, [X, Y]))
    check('its notes say how it was made', all(s in r['notes'] for s in ('Clayton copula', 'Weibull', 'Lognormal', 'seed 5')), True)
    check('its values are the engine\'s draws for that seed', r['same'], True)
    check('and the report compares them with the data', ('Simulated and Observed' in r['outlines'], r['sc']), (True, {'n': 600, 'seed': 5, 'scale': 'data'}))

    # ---- Save
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      await (%s)('*top*', ['Save', 'Pseudo-Observations'], false, 0);
      await new Promise(r => setTimeout(r, 400));
      const c = t.col('Pseudo[%s]');
      return c ? { v: [c.values[0], c.values[123]], n: t.nrows } : null;
    })()''' % (PICK, X))
    check.near('Save Pseudo-Observations: the ranks over n + 1', r['v'][1], ps['rx'][123], tol=1e-12)

    script = await page.ev('SM.app.reports[SM.app.reports.length - 1].pythonScript()')
    check('the script holds the statsmodels calls', all(s in script for s in ('ClaytonCopula', 'approx_hess', 'stats.rankdata', 'CopulaDistribution.rvs', 'def fit1(')), True)

    # ---- a project keeps the options, the column ids remapped
    await page.ev(pick_js(X, ['Gamma']))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'copula' && r.spec.options.calc);
      const t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const x = back.table.col('%s');
      const mg = [...back.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === '%s');
      const chosen = mg ? [...mg.parentElement.querySelectorAll('table.sm-rt tbody tr')].filter(tr => tr.cells[0].textContent === '✓').map(tr => tr.cells[1].textContent) : null;
      const out = { newTable: back.table !== t, margin: back.spec.options[x.id + '|marginFamily'], chosen, calcAt: back.spec.options.calcAt, gof: back.spec.options.gof, errors: [...back.body.querySelectorAll('.sm-ob-error')].length,
                    heads: [...back.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent) };
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })()''' % (X, X), timeout=900)
    check('an opened project has its own table', r['newTable'], True)
    check('and keeps the margin chosen for soil moisture by its new column id', (r['margin'], r['chosen']), ('gamma', ['Gamma']))
    check('and the calculator\'s point and the bootstrap', (r['calcAt'], r['gof']), ({'x': 20, 'y': 3.5}, {'B': 30, 'seed': 3}))
    check('and draws the same outlines without errors', ('Joint Probabilities' in r['heads'], 'Goodness of Fit' in r['heads'], r['errors']), (True, True, 0))

    # ---- By: one analysis per region, combined tables
    rep = await page.ev(open_report_js('copula', {'y': [X, Y], 'by': ['region']}, {}), timeout=300)
    check('By region: one analysis per region', [o for o in rep['outlines'] if o.startswith('Copulas of')], [f'Copulas of {X} and {Y} region=North', f'Copulas of {X} and {Y} region=South'])
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const tbls = [...rep.body.querySelectorAll('table.sm-rt')].filter(t => t.dataset.rtKey === 'comparison');
      const combined = SM.report.combineRT(tbls, 'x');
      const t = rep.table; const reg = t.col('region').values;
      return { n: tbls.length, groups: tbls.map(t => t.dataset.group), rows: combined.nrows, each: tbls.map(t => t._rt.rows.length), north: reg.filter(v => v === 'North').length,
               notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent).filter(t => /rows with a value in every column/.test(t)) };
    })()''')
    check('each group has its comparison, which combine into one table', (r['n'], r['groups'], r['rows']), (2, ['region=North', 'region=South'], sum(r['each'])))
    check('each group fits its own rows', r['notes'][0].startswith(f"{r['north']} rows"), True)

    # ---- three columns: the scatterplot matrix and the elliptical copulas
    await page.ev('''(() => {
      const r = SM.util.rng('three columns');
      const n = 300, a = [], b = [], c = [];
      for (let i = 0; i < n; i++) { const z1 = r.normal(), z2 = 0.6 * z1 + 0.8 * r.normal(), z3 = -0.5 * z1 + Math.sqrt(0.75) * r.normal(); a.push(z1); b.push(Math.exp(z2)); c.push(z3 * 3 + 10); }
      SM.app.addTable(new SM.Table({ name: 'Three', source: 'simulated', columns: [{ name: 'a', dataType: 'numeric', values: a }, { name: 'b', dataType: 'numeric', values: b }, { name: 'c', dataType: 'numeric', values: c }] }));
    })()''')
    rep = await page.ev(open_report_js('copula', {'y': ['a', 'b', 'c']}, {}), timeout=300)
    check('three columns: a scatterplot matrix, no errors', ('Scatterplot Matrix' in rep['outlines'], rep['errors']), (True, []))
    cmp3 = await page.ev(table_under_js('Copula Comparison', 0))
    check('three columns: the Gaussian, t and independence copulas only', sorted(row[0] for row in cmp3[1:]), ['Gaussian', 'Independence', 'Student t'])
    check('the Gaussian copula (the truth) has the smallest BIC', min(cmp3[1:], key=lambda row: num(row[-1]))[0], 'Gaussian')
    pe3 = await page.ev(table_under_js('Copula Comparison', 1))
    rho = {row[1]: num(row[2]) for row in pe3[1:] if row[0] == 'Gaussian'}
    check('its correlations near the truth (0.6, −0.5, −0.3)', max(abs(rho['ρ(a, b)'] - 0.6), abs(rho['ρ(a, c)'] + 0.5), abs(rho['ρ(b, c)'] + 0.3)) < 0.1, True)
    got = await page.ev(pick_js('Pseudo-Observations', ['Pair', 'b and c']))
    pp3 = await page.ev(PSEUDO)
    if not check('Pair picks the pair drawn', pp3['title'], 'Pseudo-observations of b and c'):
        print('   ', got)
    await triangles(page, 'the three-column report', 4)
    await shot(page, 'copula-03-three.png')

    # ---- negative dependence: the 90° and 270° rotations, the corner tails
    await page.ev('''(() => {
      const t = SM.app.tables.find(t => t.name === 'Drought');
      const y = t.col('%s').values;
      t.addColumn({ name: 'dryness', dataType: 'numeric', values: y.map(v => -v) });
    })()''' % Y)
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Drought").id)')
    rep = await page.ev(open_report_js('copula', {'y': [X, 'dryness']}, {}), timeout=300)
    cmpn = await page.ev(table_under_js('Copula Comparison', 0))
    famn = [row[0] for row in cmpn[1:]]
    check('negative τ: Clayton turned by 90° or 270° is best (the example\'s Clayton, flipped)', famn[0] in ('Clayton (90°)', 'Clayton (270°)'), True)
    check('and no unrotated Clayton or Gumbel', ('Clayton' in famn, 'Gumbel' in famn), (False, False))
    hd = await page.ev(table_under_js('Dependence', 1))
    check('the corner tails are shown', ('λ Upper Left' in hd[0], 'λ Lower Right' in hd[0]), (True, True))
    await shot(page, 'copula-04-negative.png')

    # ---- the (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-copula"); const row = document.getElementById("help-p-copula"); return row ? row.textContent : null; })()')
    check('the platform has its line in Help, with statsmodels\' copulas', bool(helps) and 'statsmodels.distributions.copula' in helps, True)
    topics = await page.ev('Object.keys(SM.platforms.get("copula").topics)')
    check('its topics', sorted(topics), sorted(['p:copula', 'p:copula:pseudo', 'p:copula:dependence', 'p:copula:tails', 'p:copula:comparison', 'p:copula:gof', 'p:copula:margins', 'p:copula:joint', 'p:copula:simulate']))

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "copula" && r.spec.options.calc)))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2.5)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => r.platform.id === 'copula'); return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)) }; })()''')
    check('the dark theme redraws the reports without errors', st['errors'], [])
    col = await page.ev('(() => { const rep = SM.app.reports.find(r => r.platform.id === "copula" && r.spec.options.calc); const p = rep.plots.find(p => /^Pseudo-observations of/.test(p.opts.title)); return p.traces.find(t => t.type === "contour").line.color; })()')
    check('the contours take the dark theme\'s colour', col, '#9085e9')
    await shot(page, 'copula-05-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports.find(r => r.platform.id === "copula" && r.spec.options.calc); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')
    await asyncio.sleep(1.0)
    r = await page.ev('''(() => {
      const rep = SM.app.reports.find(r => r.platform.id === "copula" && r.spec.options.calc);
      const body = rep.body.getBoundingClientRect();
      const boxes = rep.plots.filter(p => p.drawn).map(p => p.box.getBoundingClientRect().right);
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length,
               body: rep.body.scrollWidth <= rep.body.clientWidth + 1, scrollers: [...rep.body.querySelectorAll('.sm-cop-scroll')].some(s => s.scrollWidth > s.clientWidth) };
    })()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the graphs fit the phone\'s width', (r['plots'], r['n'] >= 2), (True, True))
    check('wide tables scroll inside their own boxes, not the whole report', (r['body'], r['scrollers']), (True, True))
    await shot(page, 'copula-06-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
