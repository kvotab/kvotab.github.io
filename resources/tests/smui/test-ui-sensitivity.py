#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Screening > Sensitivity Analysis.

The simulated Monte Carlo sample opens from the URL and File > Examples; the
platform sits last in Analyze > Screening; sensitivity.py imports in
Pyodide; the launch dialog has its roles and options and refuses a column
that is both an output and an input; with two outputs each has its outline;
the Measures are the engine's numbers, the sample's known structure shows
(Ishigami's x2 seen by S1 and by no correlation; the dose monotone in Kd and
v; d nowhere), and the poor fits are said; the chart shows PRCC or S1 by the
fit, the largest at the top, and changes from either red triangle; the
scatterplots are linked to their rows; Log Output reads the output's
logarithm and draws a log axis; the Distribution-Based Measures and Settings
(resamples, seed) give the engine's numbers; Regional Sensitivity at the
mean, the median, a quantile and a value, with each input's two
distributions in the theme's colours; a sample with missing and non-positive
outputs says what it left out, and one too small is refused; every red
triangle opens; By gives an analysis per group whose tables combine; a
project keeps the options; Bootstrap reruns the Measures headless; the
Python script holds the estimators; every (i) has a topic, the launch
dialog's (i) gives every role and option its help and Settings' (i) its
fields; dark theme and phone width.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-sensitivity.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import importlib.util
import json
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, wait_engine

# the Gaussian Process suite's helpers: red triangles, the state, the (i)
_spec = importlib.util.spec_from_file_location('ui_gaussproc', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test-ui-gaussproc.py'))
GP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GP)

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
GP.check = check            # (its helpers' checks count here)
XS = ['x1', 'x2', 'x3', 'Kd', 'v', 'd']
YS = ['Ishigami', 'Dose']


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('*', '').replace('<', ''))


# The table n under the outline title, inside the outline of an output (or
# anywhere, out None), in the last report: rows of cell texts, header first.
UNDER = '''
((out, title, n) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const name = (h) => h.querySelector('h1, h2, h3, h4, h5, h6').textContent.trim();
  let scope = rep.body;
  if (out) { const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => name(h) === out); if (!h) return null; scope = h.parentElement; }
  const head = [...scope.querySelectorAll('.sm-ob-head')].find(h => name(h) === title);
  if (!head) return null;
  const t = head.parentElement.querySelector(':scope > .sm-ob-body').querySelectorAll('table.sm-rt, table.sm-kv')[n || 0];
  return t ? [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent.trim())) : null;
})
'''


def under_js(out, title, n=0):
    return f'({UNDER})({json.dumps(out)}, {json.dumps(title)}, {n})'


# The engine's own result for an output of the last report, as the page asks for it.
ENGINE = '''
(async (fn, y, extra) => {
  const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
  return await SM.engine.call(fn, { table: t.id, rows: null, y, x: %s, log_y: !!rep.spec.options.logY, ...(extra || {}) }, t);
})
''' % json.dumps(XS)


def engine_js(fn, y, extra=None):
    return f'({ENGINE})({json.dumps(fn)}, {json.dumps(y)}, {json.dumps(extra or {})})'


def rows_of(tbl):
    """A report table's rows by their first cell (the input)."""
    return {r[0]: r for r in tbl[1:]}


def same(tbl, res, cols, keys, tol=6e-5):
    """Every input's cells (shown to 4 decimals) are the engine's values."""
    head = tbl[0]
    rows = rows_of(tbl)
    bad = []
    for r in res['rows']:
        for c, k in zip(cols, keys):
            cell = rows[r['input']][head.index(c)]
            v = r[k]
            if v is None:
                if cell != '.':
                    bad.append((r['input'], c, cell, v))
            elif abs(num(cell) - v) > tol:
                bad.append((r['input'], c, cell, v))
    return bad


async def pick(page, title, path, wait=True, which=0):
    return await page.ev(GP.pick_js(title, path, wait, which), timeout=600)


async def main():
    page = await open_page(f'{BASE}/smui.html?example=sensitivity', height=1200)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "sensitivity").map(f => f.module + ": " + f.error)')
    check('sensitivity.py imports in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const file = SM.app.menuItems('File');
      const exs = file.find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const an = SM.app.menuItems('Analyze');
      const sc = an.find(i => i.label === 'Screening');
      const items = (typeof sc.submenu === 'function' ? sc.submenu() : sc.submenu).filter(i => !i.separator).map(i => i.label);
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), about: SM.io.EXAMPLES.sensitivity.about, inFile: labels.includes(SM.io.EXAMPLES.sensitivity.label), items };
    })()''')
    check('?example=sensitivity opens the simulated Monte Carlo sample', (ex['name'], ex['rows'], ex['cols']), ('Monte Carlo sample', 1000, XS + YS))
    check('it is simulated, and its notes give the two functions', (ex['about'].startswith('Simulated'), 'Ishigami function' in ex['about'], 'v^1.5' in ex['about']), (True, True, True))
    check('it is in File > Examples', ex['inFile'], True)
    check('Analyze > Screening lists Sensitivity Analysis last', ex['items'][-1] if ex['items'] else None, 'Sensitivity Analysis…')
    ok = await page.ev('''(() => { const t = SM.app.current; const c = (n) => t.col(n).values;
      const [x1, x2, x3, kd, v] = ['x1', 'x2', 'x3', 'Kd', 'v'].map(c);
      return x1.every((_, i) => Math.abs(c('Ishigami')[i] - (Math.sin(x1[i]) + 7 * Math.sin(x2[i]) ** 2 + 0.1 * x3[i] ** 4 * Math.sin(x1[i]))) < 1e-7
        && Math.abs(c('Dose')[i] / (1e-6 * v[i] ** 1.5 / (1 + 1000 * kd[i])) - 1) < 1e-6); })()''')
    check('the outputs are the two functions of the inputs', ok, True)

    # ---- the launch dialog
    r = await page.ev('''(async (xs, ys) => {
      SM.app.launch('sensitivity');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); items.find(x => x.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      const opts = [...dlg.querySelectorAll('.sm-launch-opts label')].map(l => { const i = l.querySelector('input, select'); return [[...l.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim(), i.type === 'checkbox' ? i.checked : i.value]; });
      pick(ys[0]); role('Y, Output').querySelector('.sm-btn').click();
      pick(ys[0]); role('X, Input').querySelector('.sm-btn').click();
      ok.click();
      const both = dlg.querySelector('.sm-launch-msg').textContent;
      [...role('X, Input').querySelectorAll('li')].forEach(li => li.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })));
      pick(ys[1]); role('Y, Output').querySelector('.sm-btn').click();
      for (const x of xs) { pick(x); role('X, Input').querySelector('.sm-btn').click(); }
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { roles, opts, both, title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4, .sm-ob-head h5')].map(h => h.textContent) };
    })(%s, %s)''' % (json.dumps(XS), json.dumps(YS)), timeout=300)
    check('the launch dialog\'s roles: Y, Output; X, Input; By', r['roles'], ['Y, Output', 'X, Input', 'By'])
    check('its options and defaults: Log Output and Distribution-Based Measures off', dict((k, v) for k, v in r['opts']), {'Log Output': False, 'Distribution-Based Measures': False})
    check('a column in both roles is refused', 'both an output and an input' in r['both'], True)
    check('two outputs: an outline each, with its Measures, chart and Scatterplots', r['outlines'],
          ['Sensitivity Analysis', 'Ishigami', 'Measures', 'S1 Chart', 'Scatterplots', 'Dose', 'Measures', 'PRCC Chart', 'Scatterplots'])
    st = await page.ev(GP.STATE)
    check('no errors in the report', st['errors'], [])
    await shot(page, 'sensitivity-01-report.png')

    # ---- the Measures against the engine's
    res = {y: await page.ev(engine_js('sensitivity.measures', y)) for y in YS}
    cols = ['Pearson', 'Spearman', 'SRC', 'PCC', 'SRRC', 'PRCC', 'S1']
    keys = ['pearson', 'spearman', 'src', 'pcc', 'srrc', 'prcc', 's1']
    for y in YS:
        tbl = await page.ev(under_js(y, 'Measures'))
        check(f'{y}: the Measures table, Input then the seven measures', tbl[0], ['Input'] + cols)
        check(f'{y}: every input\'s measures are the engine\'s, to 4 decimals', same(tbl, res[y], cols, keys), [])
        kv = {row[0]: row[1] for row in await page.ev(under_js(y, 'Measures', 1))}
        check.near(f'{y}: R², the engine\'s', num(kv['R²']), res[y]['r2'], tol=1e-6)
        check.near(f'{y}: R² on Ranks, the engine\'s', num(kv['R² on Ranks']), res[y]['r2_rank'], tol=1e-6)
        check(f'{y}: 1000 realisations', kv['Realisations'], '1000')
    m = {y: {r['input']: r for r in res[y]['rows']} for y in YS}
    check('Ishigami: x2 matters most and no correlation sees it; x3 alone does nothing', (abs(m['Ishigami']['x2']['spearman']) < 0.1, m['Ishigami']['x2']['s1'] > 0.35, m['Ishigami']['x3']['s1'] < 0.05), (True, True, True))
    check('Dose: monotone in Kd (down) and v (up), PRCCs beyond 0.9', (m['Dose']['Kd']['prcc'] < -0.9, m['Dose']['v']['prcc'] > 0.9), (True, True))
    check('d does nothing for either', max(abs(m[y]['d'][k]) for y in YS for k in ('spearman', 'prcc', 's1')) < 0.1, True)
    warns = st['warnings']
    check('Ishigami\'s poor fit is said, pointing at S1', any(w.startswith('The regression explains 0.18 of the variance of Ishigami') and 'S1 and the distribution-based measures assume no shape' in w for w in warns), True)
    check('Dose\'s too, pointing at the rank forms', any(w.startswith('The regression explains 0.53 of the variance of Dose') and 'On ranks it explains 0.97: SRRC and PRCC say more' in w for w in warns), True)

    # ---- the chart: by the fit, the largest at the top, from either red triangle
    CH = '''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; return rep.plots.filter(p => / of each input on /.test(p.opts.title)).map(p => ({ title: p.opts.title, y: p.traces[0].y, x: p.traces[0].x })); })()'''
    ch = await page.ev(CH)
    check('the charts: S1 for Ishigami (its ranks fit poorly), PRCC for Dose', [c['title'] for c in ch], ['S1 of each input on Ishigami', 'PRCC of each input on Dose'])
    check('... the largest at the top: x2 for Ishigami, v for Dose', [c['y'][-1] for c in ch], ['x2', 'v'])
    check('... the bars are the engine\'s values', max(abs(x - m[y][name][k]) for c, y, k in zip(ch, YS, ('s1', 'prcc')) for name, x in zip(c['y'], c['x'])), 0.0)
    await pick(page, '*top*', ['Chart', 'Spearman'])
    check('Chart > Spearman: both charts show Spearman', [c['title'] for c in await page.ev(CH)], ['Spearman of each input on Ishigami', 'Spearman of each input on Dose'])
    await pick(page, 'Spearman Chart', ['SRRC'], which=1)
    st = await page.ev(GP.STATE)
    check('the chart\'s own red triangle: SRRC, for every output', ([c['title'] for c in await page.ev(CH)], st['options'].get('chart')), (['SRRC of each input on Ishigami', 'SRRC of each input on Dose'], 'srrc'))
    await pick(page, '*top*', ['Chart', 'By the Fit (PRCC, or S1)'])
    check('By the Fit again', [c['title'] for c in await page.ev(CH)], ['S1 of each input on Ishigami', 'PRCC of each input on Dose'])

    # ---- the scatterplots, linked to their rows
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const ps = rep.plots.filter(p => / by (x1|x2|x3|Kd|v|d)$/.test(p.opts.title));
      const p = ps.find(p => p.opts.title === 'Dose by Kd');
      p.box.scrollIntoView({ block: 'center' });
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      p._click({ points: [{ curveNumber: 0, pointNumber: 7 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[0][3], p.rows[0][11]]);
      const sp = p.box.data[0].selectedpoints;
      t.select([]);
      return { titles: ps.map(p => p.opts.title), rows: p.rows[0].length, x: p.traces[0].x.slice(0, 3), want: [t.col('Kd').values[p.rows[0][0]], t.col('Kd').values[p.rows[0][1]], t.col('Kd').values[p.rows[0][2]]],
               sel, clicked: [p.rows[0][7]], sp, type: p.box._fullLayout.yaxis.type };
    })()''')
    check('a scatterplot per output and input', r['titles'], [f'{y} by {x}' for y in YS for x in XS])
    check('... each point a realisation, its row linked', (r['rows'], r['x'] == r['want']), (1000, True))
    check('a click on a point selects its row; rows selected in the table highlight their points', (r['sel'], r['sp']), (r['clicked'], [3, 11]))
    check('the output\'s axis is linear on the values', r['type'], 'linear')

    # ---- Log Output
    await pick(page, '*top*', ['Log Output'])
    lg = await page.ev(engine_js('sensitivity.measures', 'Dose'))
    tbl = await page.ev(under_js('Dose', 'Measures'))
    check('Log Output: the Dose\'s measures are the engine\'s on its logarithm', (lg['log_y'], same(tbl, lg, cols, keys)), (True, []))
    moved = max(abs(a[k] - m['Dose'][a['input']][k]) for a in lg['rows'] for k in ('pearson', 'src', 's1') if a[k] is not None)
    check('... Pearson, SRC and S1 move; the rank measures do not', (moved > 0.01, max(abs(a[k] - m['Dose'][a['input']][k]) for a in lg['rows'] for k in ('spearman', 'srrc', 'prcc'))), (True, 0.0))
    st = await page.ev(GP.STATE)
    check('... the notes say so', any('On the logarithm of Dose (Log Output)' in n for n in st['notes']), True)
    check('... a log axis for the output', await page.ev('SM.app.reports[SM.app.reports.length - 1].plots.find(p => p.opts.title === "Dose by Kd").box._fullLayout.yaxis.type'), 'log')
    await pick(page, '*top*', ['Log Output'])

    # ---- the distribution-based measures, and Settings
    await pick(page, '*top*', ['Distribution-Based Measures'])
    dcols = ['S1 (EASI)', 'δ', 'δ Lower', 'δ Upper', 'PAWN', 'MI Above Chance', 'Discrepancy']
    dkeys = ['easi', 'delta', 'delta_low', 'delta_high', 'pawn', 'mi_above', 'discrepancy']
    for y in YS:
        d = await page.ev(engine_js('sensitivity.distribution', y, {'boots': 100, 'seed': 1}), timeout=600)
        tbl = await page.ev(under_js(y, 'Distribution-Based Measures'))
        check(f'{y}: the distribution-based measures, each the engine\'s', (tbl[0], same(tbl, d, dcols, dkeys)), (['Input'] + dcols, []))
    dm = {r['input']: r for r in d['rows']}
    check('Dose: v and Kd move its distribution, d does not (δ, mutual information above chance)', (dm['v']['delta'] > 0.3, dm['Kd']['delta'] > 0.1, dm['d']['delta'] < 0.05, dm['d']['mi_above']), (True, True, True, 0))
    st = await page.ev(GP.STATE)
    check('the notes give the resamples and the seed', any('from 100 bootstrap resamples' in n and 'the seed 1' in n for n in st['notes']), True)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await (%s)('*top*', ['Settings…'], false, 0);
      for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const inputs = dl.querySelectorAll('.sm-form input');
      inputs[0].value = '30'; inputs[1].value = '7';
      const done = new Promise(res => rep.on('done', res));
      dl.querySelector('.sm-dialog-foot .primary').click();
      await done;
      return { boots: rep.spec.options.boots, seed: rep.spec.options.seed };
    })()''' % GP.PICK, timeout=600)
    check('Settings: 30 resamples and the seed 7', (r['boots'], r['seed']), (30, 7))
    d = await page.ev(engine_js('sensitivity.distribution', 'Dose', {'boots': 30, 'seed': 7}), timeout=600)
    check('... the Dose\'s measures are the engine\'s with them', same(await page.ev(under_js('Dose', 'Distribution-Based Measures')), d, dcols, dkeys), [])

    # ---- regional sensitivity
    await pick(page, '*top*', ['Regional Sensitivity'])
    g = await page.ev(engine_js('sensitivity.regional', 'Dose', {'split': 'mean', 'seed': 7}))
    tbl = await page.ev(under_js('Dose', 'Regional Sensitivity'))
    kv = {row[0]: row[1] for row in await page.ev(under_js('Dose', 'Regional Sensitivity', 1))}
    check('Regional Sensitivity: each input\'s KS, the engine\'s', (tbl[0], same(tbl, g, ['KS'], ['ks'])), (['Input', 'KS', 'Prob > KS'], []))
    check('... the threshold (the mean, shown to 5 digits), the two groups, the dummies\' level', (abs(num(kv['Threshold']) - g['threshold']) <= 1e-4 * g['threshold'], kv['Above'], kv['At or Below'], abs(num(kv["Dummy Inputs' KS"]) - g['dummy_mean']) < 1e-6),
          (True, str(g['above']), str(g['below']), True))
    gr = {r['input']: r for r in g['rows']}
    check('... v and Kd tell the high doses apart (p < .0001); d sits with the dummies', (rows_of(tbl)['v'][2], rows_of(tbl)['Kd'][2], gr['d']['ks'] < g['dummy_mean'] + 4 * g['dummy_sd']), ('<.0001*', '<.0001*', True))
    cdf = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1];
      const ps = rep.plots.filter(p => /above and at or below the threshold/.test(p.opts.title));
      const p = ps.find(p => /Dose .*: v$/.test(p.opts.title));
      return { n: ps.length, names: p.traces.map(t => t.name), sizes: p.traces.map(t => t.x.length), last: p.traces.map(t => t.y[t.y.length - 1]), color: p.traces[1].line.color }; })()''')
    check('... each input\'s two distributions, every realisation in one of them', (cdf['n'], cdf['names'], sum(cdf['sizes']), cdf['last']), (12, ['above', 'at or below'], 1000, [1, 1]))
    check('... the realisations at or below in the light theme\'s green', cdf['color'], '#3a7d44')
    ish = await page.ev(engine_js('sensitivity.regional', 'Ishigami', {'split': 'mean', 'seed': 7}))
    await pick(page, 'Regional Sensitivity', ['Median'], which=1)
    kv = {row[0]: row[1] for row in await page.ev(under_js('Dose', 'Regional Sensitivity', 1))}
    kvi = {row[0]: row[1] for row in await page.ev(under_js('Ishigami', 'Regional Sensitivity', 1))}
    check('the Dose\'s own threshold, Median: half its realisations above; Ishigami keeps the mean', (kv['Above'], kv['At or Below'], kvi['Above']), ('500', '500', str(ish['above'])))
    dose_id = await page.ev('SM.app.reports[SM.app.reports.length - 1].table.col("Dose").id')
    for kind, value, want in [('Quantile…', '0.9', ('100', '900')), ('Value…', '1e-6', None)]:
        r = await page.ev('''(async (kind, value, id) => {
          const rep = SM.app.reports[SM.app.reports.length - 1];
          await (%s)('Regional Sensitivity', [kind], false, 1);
          for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
          const dl = [...document.querySelectorAll('.sm-dialog')].pop();
          const lead = dl.querySelector('.sm-dialog-lead') ? dl.querySelector('.sm-dialog-lead').textContent : '';
          dl.querySelector('.sm-form input').value = value;
          const done = new Promise(res => rep.on('done', res));
          dl.querySelector('.sm-dialog-foot .primary').click();
          await done;
          return { split: rep.spec.options[id + '|split'], value: rep.spec.options[id + '|splitValue'], top: rep.spec.options.split ?? null, lead };
        })(%s, %s, %s)''' % (GP.PICK, json.dumps(kind), json.dumps(value), json.dumps(dose_id)), timeout=600)
        kv = {row[0]: row[1] for row in await page.ev(under_js('Dose', 'Regional Sensitivity', 1))}
        if want:
            check(f'the Dose\'s {kind} 0.9: the highest tenth above, for this output alone', (r['split'], r['top'], kv['Above'], kv['At or Below'], r['lead'].endswith('for this output.')), ('quantile', None, *want, True))
        else:
            g = await page.ev(engine_js('sensitivity.regional', 'Dose', {'split': 'value', 'value': 1e-6, 'seed': 7}))
            check(f'the Dose\'s {kind} 1e-6: the realisations above a dose of 1e-6', (r['split'], r['value'], abs(num(kv['Threshold']) - 1e-6) < 1e-12, kv['Above']), ('value', 1e-6, True, str(g['above'])))
    await pick(page, '*top*', ['Regional Threshold', 'Median'])
    kv2 = {row[0]: row[1] for row in await page.ev(under_js('Dose', 'Regional Sensitivity', 1))}
    kvi = {row[0]: row[1] for row in await page.ev(under_js('Ishigami', 'Regional Sensitivity', 1))}
    check('the report\'s Regional Threshold > Median is every output\'s, the Dose\'s own set aside', (kvi['Above'], kvi['At or Below'], kv2['Above'], kv2['At or Below']), ('500', '500', '500', '500'))
    await shot(page, 'sensitivity-02-options.png')

    # ---- every red triangle, and the Python script
    await GP.triangles(page, 'the report (the top, each output\'s chart and regional analysis)', 5)
    script = await page.ev('SM.app.reports[SM.app.reports.length - 1].pythonScript()')
    check('the Python script holds the estimators', all(s in script for s in ('def regression_measures(', 'def first_order_index(', 'def easi(', 'def delta_moment(', 'def mutual_information(', 'def pawn(', 'def discrepancy_shares(', 'def regional(')), True)

    # ---- what is left out, and too few
    r = await page.ev('''(async () => {
      const g = SM.util.rng('sens gaps');
      const n = 60, a = [], b = [], y = [];
      for (let i = 0; i < n; i++) { const x1 = g.u(), x2 = g.u(); a.push(x1); b.push(x2); y.push(i === 3 ? NaN : i === 5 ? 0 : i === 8 ? -2 : Math.exp(3 * x1) + x2); }
      const t = new SM.Table({ name: 'Gaps', source: 'simulated', columns: [{ name: 'y', dataType: 'numeric', values: y }, { name: 'a', dataType: 'numeric', values: a }, { name: 'b', dataType: 'numeric', values: b }] });
      SM.app.addTable(t);
      return t.id;
    })()''')
    rep = await page.ev(open_report_js('sensitivity', {'y': ['y'], 'x': ['a', 'b']}, {'logY': True}), timeout=300)
    st = await page.ev(GP.STATE)
    check('a sample with a missing output and two not above zero, on logarithms: what was left out is said', (rep['errors'], any('57 realisations' in n and 'left out: 1 with the output or an input missing; 2 with y not above zero, which has no logarithm' in n for n in st['notes'])), ([], True))
    small = await page.ev('''(async () => {
      const t = SM.app.tables.find(t => t.name === 'Gaps');
      const s = new SM.Table({ name: 'Few', source: 'simulated', columns: t.columns.map(c => ({ name: c.name, dataType: 'numeric', values: c.values.slice(10, 19) })) });
      SM.app.addTable(s);
      return s.nrows;
    })()''')
    rep = await page.ev(open_report_js('sensitivity', {'y': ['y'], 'x': ['a', 'b']}), timeout=300)
    check(f'a sample of {small} realisations is refused, saying why', rep['warnings'], ['y: 9 realisations with y and every input present: at least 10 are needed'])

    # ---- By, a project, Bootstrap
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Monte Carlo sample").id)')
    await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Monte Carlo sample'); if (!t.col('half')) t.addColumn({ name: 'half', dataType: 'character', values: t.col('x1').values.map((_, i) => (i < 500 ? 'first' : 'second')) }); })()''')
    rep = await page.ev(open_report_js('sensitivity', {'y': ['Dose'], 'x': XS, 'by': ['half']}, {}), timeout=300)
    check('By half: one analysis per group', [o for o in rep['outlines'] if o.startswith('Sensitivity Analysis')], ['Sensitivity Analysis of Dose half=first', 'Sensitivity Analysis of Dose half=second'])
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const tbls = [...rep.body.querySelectorAll('table.sm-rt')].filter(t => /^measures-/.test(t.dataset.rtKey || ''));
      const combined = SM.report.combineRT(tbls, 'x');
      return { n: tbls.length, groups: tbls.map(t => t.dataset.group), rows: combined.nrows, notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent).filter(t => /realisations with the output/.test(t)) };
    })()''')
    check('each group has its Measures, which combine into one table', (r['n'], r['groups'], r['rows']), (2, ['half=first', 'half=second'], 12))
    check('each group reads its own 500 realisations', [t.split(' ')[0] for t in r['notes']], ['500', '500'])
    r = await page.ev('''(async () => {
      const t = SM.app.tables.find(t => t.name === 'Monte Carlo sample');
      const rep = SM.app.openReport(SM.platforms.get('sensitivity'), { roles: { y: [t.col('Dose').id], x: %s.map(n => t.col(n).id) }, options: { logY: true, distribution: true, chart: 'srrc', boots: 20 } }, t);
      await new Promise(res => rep.on('done', res));
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.closeReport(rep);
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const out = { newTable: back.table !== t, o: back.spec.options, errors: [...back.body.querySelectorAll('.sm-ob-error')].length,
                    heads: [...back.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent) };
      SM.app.closeReport(back);
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })()''' % json.dumps(XS), timeout=600)
    check('an opened project has its own table and keeps the options', (r['newTable'], r['o'].get('logY'), r['o'].get('distribution'), r['o'].get('chart'), r['o'].get('boots')), (True, True, True, 'srrc', 20))
    check('... and draws them without errors', ('SRRC Chart' in r['heads'], 'Distribution-Based Measures' in r['heads'], r['errors']), (True, True, 0))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'sensitivity' && r.table.name === 'Monte Carlo sample' && r.spec.roles.y.length === 2);
      const name = (h) => h.querySelector('h1, h2, h3, h4, h5, h6').textContent.trim();
      const dose = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => name(h) === 'Dose').parentElement;
      const tbl = [...dose.querySelectorAll('.sm-ob-head')].find(h => name(h) === 'Measures').parentElement.querySelector('table.sm-rt');
      const col = tbl._rt.columns.find(c => c.label === 'PRCC');
      const t = await SM.bootstrap.run(tbl, col, { B: 6, seed: 1, show: false });
      const v = t.col('v').values;
      return { cols: t.columns.map(c => c.name), n: t.nrows, first: v[0], finite: v.every(Number.isFinite), spread: Math.max(...v) - Math.min(...v), errors: [...rep.body.querySelectorAll('.sm-ob-error')].length };
    })()''', timeout=900)
    check('Bootstrap of the Dose\'s PRCC: a column per input, a row per sample', (r['cols'][:3], r['n']), (['BootID', 'x1', 'x2'], 7))
    check('... sample 0 is the report, the resamples differ', (abs(r['first'] - m['Dose']['v']['prcc']) < 1e-9, r['finite'], r['spread'] > 0), (True, True, True))

    # ---- the (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-sensitivity"); const row = document.getElementById("help-p-sensitivity"); return row ? row.textContent : null; })()')
    check('the platform has its line in Help, with what it uses', bool(helps) and 'scipy.stats.qmc.discrepancy' in helps, True)
    topics = await page.ev('Object.keys(SM.platforms.get("sensitivity").topics)')
    check('its topics', sorted(topics), sorted(['p:sensitivity', 'p:sens:measures', 'p:sens:distribution', 'p:sens:regional', 'p:sens:scatter']))
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Monte Carlo sample").id)')
    await GP.dialog_help(page, "SM.app.launch('sensitivity')", 'sensitivity', 'Sensitivity Analysis')
    two = 'SM.app.reports.find(r => r.platform.id === "sensitivity" && r.table.name === "Monte Carlo sample" && r.spec.roles.y.length === 2)'
    await GP.form_help(page, f"await clickPath({two}, '*top*', ['Settings…']);", ['Bootstrap Resamples (and shuffles)', 'Random Seed'], 'Settings…')

    # ---- dark theme and phone width
    await page.ev(f'SM.app.showTab(SM.app.tabOf({two}))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(3)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => r.platform.id === 'sensitivity'); return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)) }; })()''')
    check('the dark theme redraws the reports without errors', st['errors'], [])
    col = await page.ev(f'(() => {{ const rep = {two}; const p = rep.plots.find(p => /above and at or below the threshold/.test(p.opts.title)); return p.traces[1].line.color; }})()')
    check('the realisations at or below the threshold take the dark theme\'s green', col, '#5fb36b')
    await shot(page, 'sensitivity-03-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev(f'(async () => {{ const rep = {two}; SM.app.showTab(SM.app.tabOf(rep)); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; }})()', timeout=600)
    await asyncio.sleep(1.0)
    r = await page.ev(f'''(() => {{
      const rep = {two};
      const body = rep.body.getBoundingClientRect();
      const boxes = rep.plots.filter(p => p.drawn).map(p => p.box.getBoundingClientRect().right);
      return {{ page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length, body: rep.body.scrollWidth <= rep.body.clientWidth + 1 }};
    }})()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the graphs fit the phone\'s width', (r['plots'], r['n'] >= 4), (True, True))
    check('the wide tables scroll inside their own boxes, not the whole report', r['body'], True)
    await shot(page, 'sensitivity-04-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


if __name__ == '__main__':
    asyncio.run(main())
    sys.exit(check.done())
