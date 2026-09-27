#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Multivariate Methods,
Clustering and Screening (resources/js/smui-p-multivariate.js).

A table is simulated in the page from a fixed seed: five correlated columns
with one missing value, a three-level group, a frequency. Every platform
opens with its options on and without an error; the numbers shown agree
with numbers computed here in the page (correlations, eigenvalues, counts);
graphs link to the table both ways; saved columns land in the table; row
colours follow the clusters; By gives one report per level; Response
Screening opens Fit Y by X when that platform is loaded; the distance
correlations agree with the doubly centred distances computed in the page;
Item Reliability's intraclass correlations and Kendall's W agree with an ANOVA
and ranks computed in the page, and Bootstrap reruns them; the dark theme and
phone width draw.

Start a server on the repository root and headless Chrome on
SMUI_HTTP_PORT and SMUI_CDP_PORT (see README.md), then

    python3 resources/tests/smui/test-ui-multivariate.py

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

MAKE = r'''
(() => {
  const r = SM.util.rng('smui-multivariate-test'); const n = 150;
  const c = { a: [], b: [], c: [], d: [], e: [], grp: [], f: [], u: [], v: [], q1: [], q2: [] };
  for (let i = 0; i < n; i++) {
    const z1 = r.normal(), z2 = r.normal();
    c.a.push(+(z1 + 0.3 * r.normal()).toFixed(4)); c.b.push(+(z1 + 0.5 * r.normal()).toFixed(4));
    c.c.push(+(z2 + 0.4 * r.normal()).toFixed(4)); c.d.push(+(z2 - 0.3 * z1 + 0.6 * r.normal()).toFixed(4));
    c.e.push(+(0.5 * z1 + 0.5 * z2 + 0.7 * r.normal()).toFixed(4));
    c.grp.push(z1 > 0.4 ? 'hi' : (z2 > 0 ? 'mid' : 'lo')); c.f.push(1 + (i % 3));
    const k = i % 3;   // three well separated clusters in u, v
    c.u.push(+([0, 6, 0][k] + r.normal()).toFixed(3)); c.v.push(+([0, 0, 6][k] + r.normal()).toFixed(3));
    c.q1.push(r.u() < 0.7 ? ['A', 'B', 'C'][k] : r.pick(['A', 'B', 'C'])); c.q2.push(r.u() < 0.6 ? ['x', 'y', 'y'][k] : r.pick(['x', 'y']));
  }
  c.b[7] = NaN;
  const t = new SM.Table({ name: 'Multivariate test', source: 'simulated', columns: [
    { name: 'id', dataType: 'character', values: Array.from({ length: n }, (_, i) => `R${i + 1}`), role: 'label' },
    ...['a', 'b', 'c', 'd', 'e'].map((k) => ({ name: k, dataType: 'numeric', values: c[k] })),
    { name: 'grp', dataType: 'character', values: c.grp },
    { name: 'f', dataType: 'numeric', values: c.f },
    { name: 'u', dataType: 'numeric', values: c.u }, { name: 'v', dataType: 'numeric', values: c.v },
    { name: 'q1', dataType: 'character', values: c.q1 }, { name: 'q2', dataType: 'character', values: c.q2 },
  ] });
  SM.app.addTable(t);
  return t.nrows;
})()
'''

# The report open last, its plots, and a fresh context for menu actions.
LAST = 'SM.app.reports[SM.app.reports.length - 1]'
CTX = f'(() => {{ const rep = {LAST}; return new SM.report.Ctx(rep, {{ rows: rep.table.includedRows() }}, rep.content || rep.body, ""); }})()'


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


async def run_menu(page, label, sub=None):
    """Run an item of the top red triangle of the report open last."""
    return await page.ev(f'''(async () => {{
      const rep = {LAST}; const ctx = {CTX};
      let items = rep.platform.triangle(ctx).filter(Boolean);
      let it = items.find(x => x.label === {json.dumps(label)});
      if (!it) return 'no item ' + {json.dumps(label)};
      if ({json.dumps(sub)} !== null) {{ const s = typeof it.submenu === 'function' ? it.submenu() : it.submenu; it = s.find(x => x.label === {json.dumps(sub)}); if (!it) return 'no subitem'; }}
      const done = new Promise(res => rep.on('done', res));
      const before = rep.seq;
      await it.action();
      await new Promise(r => setTimeout(r, 30));
      if (rep.seq !== before) await Promise.race([done, new Promise(r => setTimeout(r, 60000))]);
      return 'ok';
    }})()''')


async def main():
    page = await open_page(f'{BASE}/smui.html')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "multivariate").map(f => f.error)')
    check('the multivariate module imports in Pyodide', failed, [])
    names = await page.ev('SM.engine.names.filter(n => /^(multivariate|pca|factor|discriminant|hcluster|kmeans|respscreen|outliers|mca|mds)\\./.test(n)).length')
    check('the 22 backend names are there', names, 22)
    check('no script errors at load', page.errors, [])
    menus = await page.ev('''(() => {
      const sub = (path) => { const top = SM.app.menuItems('Analyze'); const m = top.find(i => i.label === path); if (!m) return null; return (typeof m.submenu === 'function' ? m.submenu() : m.submenu).filter(i => i.label).map(i => i.label); };
      return { mv: sub('Multivariate Methods'), cl: sub('Clustering'), sc: sub('Screening') };
    })()''')
    mine = ('Multivariate…', 'Principal Components…', 'Discriminant…', 'Multiple Correspondence Analysis…', 'Factor Analysis…', 'Multidimensional Scaling…')
    check('Multivariate Methods menu', [x for x in menus['mv'] if x in mine], list(mine))
    check('Clustering menu', [x for x in menus['cl'] if x in ('Hierarchical Cluster…', 'K Means Cluster…')], ['Hierarchical Cluster…', 'K Means Cluster…'])
    check('Screening menu', [x for x in menus['sc'] if x in ('Response Screening…', 'Explore Outliers…')], ['Response Screening…', 'Explore Outliers…'])
    check('the example table', await page.ev(MAKE), 150)

    # ---- Multivariate: every option ------------------------------------------------------
    opts = {'corrProb': True, 'ci': True, 'inverse': True, 'partial': True, 'partialP': True, 'cov': True, 'pairwise': True, 'simpleUni': True, 'simpleMulti': True,
            'np:spearman': True, 'np:kendall': True, 'np:hoeffding': True, 'cmCorr': True, 'cmP': True, 'cmCluster': True, 'mahal': True, 'jack': True, 't2': True,
            'alpha:raw': True, 'alpha:std': True, 'spCorr': True, 'spHist': True, 'cmCells': True, 'dcor': True}
    r = await page.ev(open_report_js('multivariate', {'y': ['a', 'b', 'c', 'd', 'e']}, opts), timeout=240)
    check('Multivariate: no errors', r['errors'], [])
    want = ['Correlations', 'Correlation Probability', 'CI of Correlation', 'Inverse Corr', 'Partial Corr', 'Covariance Matrix', 'Pairwise Correlations', 'Simple Statistics',
            "Nonparametric: Spearman's ρ", "Nonparametric: Kendall's τ", "Nonparametric: Hoeffding's D", 'Scatterplot Matrix', 'Color Map On Correlations', 'Color Map On p-values',
            'Cluster the Correlations', 'Mahalanobis Distances', 'Jackknife Distances', 'T²', "Cronbach's α", 'Standardized α', 'Distance Correlations']
    check('Multivariate: the outlines of every option', [o for o in want if o not in r['outlines']], [])
    corr = await page.ev(table_under_js('Correlations'))
    js = await page.ev('''(() => {
      const t = SM.app.current; const a = t.col('a').values, d = t.col('d').values, b = t.col('b').values;
      const ok = a.map((_, i) => [a, b, t.col('c').values, d, t.col('e').values].every(v => Number.isFinite(v[i])));
      const x = a.filter((_, i) => ok[i]), y = d.filter((_, i) => ok[i]);
      const mx = x.reduce((s, v) => s + v, 0) / x.length, my = y.reduce((s, v) => s + v, 0) / y.length;
      let sxy = 0, sxx = 0, syy = 0; for (let i = 0; i < x.length; i++) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) ** 2; syy += (y[i] - my) ** 2; }
      return SM.util.fmt(sxy / Math.sqrt(sxx * syy), { digits: 4 });
    })()''')
    check('Multivariate: r(a, d) as computed in the page, row-wise', corr[1][4], js)
    check('Multivariate: row-wise uses 149 rows', 'Variance estimation: Row-wise. 149 observations; 1 row with a missing value left out.' in await page.ev(f'{LAST}.content.textContent'), True)
    # Distance Correlations: dCor of a and d by the doubly centred distances, computed in the page
    js = await page.ev('''(() => {
      const t = SM.app.current; const x = t.col('a').values, y = t.col('d').values; const n = x.length;
      const centred = (v) => { const D = v.map((p) => v.map((q) => Math.abs(p - q))); const rm = D.map((r) => r.reduce((s, z) => s + z, 0) / n); const gm = rm.reduce((s, z) => s + z, 0) / n;
        return D.map((r, i) => r.map((z, j) => z - rm[i] - rm[j] + gm)); };
      const A = centred(x), B = centred(y); let ab = 0, aa = 0, bb = 0;
      for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) { ab += A[i][j] * B[i][j]; aa += A[i][j] ** 2; bb += B[i][j] ** 2; }
      return Math.sqrt(ab / Math.sqrt(aa * bb));
    })()''')
    dm = await page.ev(table_under_js('Distance Correlations'))
    dp = await page.ev(table_under_js('Distance Correlations', 1))
    row_ad = [x for x in dp[1:] if x[0] == 'd' and x[1] == 'a'][0]
    check.near('Distance Correlations: dCor(a, d) as computed in the page', float(row_ad[2]), js, 2e-4)
    check('the dCor matrix holds it', dm[1][4], row_ad[2])
    check('the pairwise table: ten pairs, a p-value and where it comes from', (len(dp) - 1, dp[0][5:8]), (10, ['n·dCov²', 'Prob>n·dCov²', 'p-Value from']))
    check('150 rows: permutation p-values (or statsmodels\' asymptotic fallback)', all(x[7].startswith(('permutation (B = 233)', 'asymptotic: no permutation of 233')) for x in dp[1:]), True)
    dcells = await page.ev(f'''(() => {{ const h = [...{LAST}.content.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Distance Correlations'); return h.parentElement.querySelectorAll('td.mv-cm').length; }})()''')
    check('the dCor matrix is colour mapped', dcells, 25)
    cells = await page.ev(f'[...{LAST}.content.querySelectorAll("td.mv-cm")].length')
    check('Multivariate: coloured correlation cells', cells >= 25, True)
    bars = await page.ev(f'[...{LAST}.content.querySelectorAll(".mv-bar")].length')
    check('Multivariate: bars in the pairwise and nonparametric tables', bars >= 40, True)
    # scatterplot matrix: selecting in one cell selects rows and lights the other cells
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const t = rep.table;
      const p = rep.plots.find(p => p.opts.title === 'Scatterplot Matrix');
      await p.draw();
      const i = p.kinds.findIndex(k => k === 'points');
      p._selected({{ points: [0, 1, 2, 3].map(k => ({{ curveNumber: i, pointNumber: k }})) }});
      await new Promise(r => setTimeout(r, 300));
      const sel = t.selectedRows();
      const other = p.kinds.findIndex((k, j) => k === 'points' && j > i);
      const lit = p.box.data[other].selectedpoints;
      t.select([]);
      return {{ n: sel.length, want: p.rows[i].slice(0, 4), sel, lit: lit ? lit.length : 0, hist: p.kinds.filter(k => k === 'bars').length }};
    }})()''')
    check('scatterplot matrix: a drag selects the rows', r['sel'], sorted(r['want']))
    check('scatterplot matrix: the other cells highlight them', r['lit'], 4)
    check('scatterplot matrix: linked histograms on the diagonal', r['hist'], 5)
    # an outlier plot: a click selects the row; save the distances
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const t = rep.table;
      const p = rep.plots.find(p => p.opts.title === 'Mahalanobis Distances');
      await p.draw();
      p._click({{ points: [{{ curveNumber: 0, pointNumber: 10 }}], event: {{}} }});
      const sel = t.selectedRows();
      t.select([]);
      return {{ sel, want: p.rows[0][10] }};
    }})()''')
    check('outlier plot: a click selects its row', r['sel'], [r['want']])
    r = await run_menu(page, 'Save', 'Mahalanobis Distances')
    saved = await page.ev('''(() => { const t = SM.app.current; const c = t.columns[t.columns.length - 1]; return { name: c.name, n: c.values.filter(Number.isFinite).length, miss: Number.isNaN(c.values[7]) }; })()''')
    check('Save Mahalanobis distances: a column for the complete rows', (r, saved['name'], saved['n'], saved['miss']), ('ok', 'Mahal. Distances', 149, True))
    await page.ev('(() => { const t = SM.app.current; t.removeColumn(t.columns[t.columns.length - 1].id); })()')
    await asyncio.sleep(0.5)
    await shot(page, 'mv-01-multivariate.png')
    # the Principal Components item opens the PCA platform on the same columns
    n_rep = await page.ev('SM.app.reports.length')
    await run_menu(page, 'Principal Components')
    await page.ev(f'Promise.race([new Promise(res => {LAST}.on("done", res)), new Promise(res => setTimeout(res, 4000))])')
    r = await page.ev(f'({{ n: SM.app.reports.length, id: {LAST}.platform.id, title: {LAST}.title }})')
    check('Principal Components from Multivariate', (r['n'], r['id'], r['title']), (n_rep + 1, 'pca', 'Principal Components: on Correlations'))
    await page.ev(f'SM.app.closeReport({LAST})')

    # ---- By ----------------------------------------------------------------------------------
    r = await page.ev(open_report_js('multivariate', {'y': ['a', 'c', 'e'], 'by': ['grp']}, {'mahal': True}), timeout=240)
    check('By: one Multivariate per level', [o for o in r['outlines'] if o.startswith('Multivariate ')], ['Multivariate grp=hi', 'Multivariate grp=lo', 'Multivariate grp=mid'])
    check('By: no errors', r['errors'], [])

    # ---- Principal Components ------------------------------------------------------------------
    r = await page.ev(open_report_js('pca', {'y': ['a', 'b', 'c', 'd', 'e']}, {'bartlett': True, 'eigvec': True, 'loadmat': True, 'fmtload': True, 'corrmat': True, 'covmat': True, 'scree': True, 'score': True, 'loadplot': True, 'biplot': True, 'ellipse': True, 'rotation': {'k': 2, 'method': 'varimax', 'kaiser': True}}), timeout=240)
    check('PCA: no errors', r['errors'], [])
    check('PCA: outlines', [o for o in ['Summary Plots', 'Eigenvalues', 'Eigenvectors', 'Loading Matrix', 'Formatted Loading Matrix', 'Correlations', 'Scree Plot', 'Score Plot', 'Loading Plot', 'Biplot', 'Rotated Components: Varimax'] if o not in r['outlines']], [])
    ev = await page.ev(table_under_js('Eigenvalues'))
    check('PCA: the eigenvalues sum to 5', round(sum(float(x[1].replace('−', '-')) for x in ev[1:]), 3), 5.0)
    check('PCA: Bartlett df 14, 9, 5, 2', [x[6] for x in ev[1:]], ['14', '9', '5', '2', '.'])
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const t = rep.table;
      const p = rep.plots.find(p => p.opts.title === 'Score Plot');
      await p.draw();
      t.select([0, 1, 2]);
      await new Promise(r => setTimeout(r, 200));
      const sp = p.box.data[0].selectedpoints; t.select([]);
      return sp.length;
    }})()''')
    check('PCA: a table selection shows in the score plot', r, 3)
    await page.ev(f'''(async () => {{
      const rep = {LAST}; const ctx = {CTX};
      const items = rep.platform.triangle(ctx); const save = items.find(i => i.label === 'Save Columns').submenu().find(i => i.label === 'Save Principal Components…');
      save.action(); await new Promise(r => setTimeout(r, 400));
      const dlg = [...document.querySelectorAll('.sm-dialog')].pop(); dlg.querySelector('input').value = '2';
      [...dlg.querySelectorAll('.sm-btn')].find(b => b.textContent === 'OK').click();
      await new Promise(r => setTimeout(r, 400));
    }})()''')
    r = await page.ev('''(() => { const t = SM.app.current; const cols = t.columns.slice(-2); const v = cols[0].values.filter(Number.isFinite); const m = v.reduce((a, b) => a + b, 0) / v.length;
      const s2 = v.reduce((a, b) => a + (b - m) ** 2, 0) / (v.length - 1); const out = { names: cols.map(c => c.name), mean: Math.abs(m) < 1e-9, var: s2 }; cols.forEach(c => t.removeColumn(c.id)); return out; })()''')
    check('PCA: Save Principal Components writes Prin1, Prin2', r['names'], ['Prin1', 'Prin2'])
    check('PCA: Prin1 has mean 0 and variance the first eigenvalue', (r['mean'], round(r['var'], 3)), (True, round(float(ev[1][1].replace('−', '-')), 3)))
    await shot(page, 'mv-02-pca.png')

    # ---- Factor Analysis -------------------------------------------------------------------------
    r = await page.ev(open_report_js('factor', {'y': ['a', 'b', 'c', 'd', 'e']}, {'sphericity': True, 'kmo': True, 'fits': [{'method': 'ml', 'prior': 'smc', 'k': 2, 'rotation': 'varimax', 'kaiser': True}, {'method': 'pa', 'prior': 'smc', 'k': 2, 'rotation': 'promax', 'kaiser': True}], 'fa0|fitm': True, 'fa0|scoreplot': True}), timeout=240)
    check('Factor: no errors', r['errors'], [])
    check('Factor: the two fits', [o for o in r['outlines'] if o.startswith('Factor Analysis on')], ['Factor Analysis on Correlations with 2 Factors: Maximum Likelihood, Varimax Rotation', 'Factor Analysis on Correlations with 2 Factors: Principal Axis, Promax Rotation'])
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const b = rep.content;
      const go = [...b.querySelectorAll('.sm-btn')].find(x => x.textContent === 'Go');
      const k = [...b.querySelectorAll('input')].find(i => i.getAttribute('aria-label') === 'Number of factors');
      k.value = '1'; k.dispatchEvent(new Event('change'));
      go.click(); await new Promise(res => rep.on('done', res));
      return [...rep.content.querySelectorAll('.sm-ob-head h3')].filter(h => h.textContent.startsWith('Factor Analysis on')).map(h => h.textContent);
    }})()''')
    check('Factor: Model Launch Go adds a fit', r[-1], 'Factor Analysis on Correlations with 1 Factor: Maximum Likelihood, Varimax Rotation')

    # ---- Discriminant ------------------------------------------------------------------------------
    r = await page.ev(open_report_js('discriminant', {'y': ['a', 'b', 'c', 'd', 'e'], 'x': ['grp']}, {'stepwise': True, 'candetails': True, 'canstruct': True, 'groupmeans': True, 'withincov': True, 'dist': True, 'probs': True, 'cp50': True}), timeout=240)
    check('Discriminant: no errors', r['errors'], [])
    check('Discriminant: outlines', [o for o in ['Column Selection', 'Canonical Plot', 'Discriminant Scores', 'Score Summaries', 'Canonical Details', 'Canonical Structure', 'Group Means', 'Covariance Matrices'] if o not in r['outlines']], [])
    conf = await page.ev(table_under_js('Score Summaries', 1))
    total = sum(float(v) for row in conf[1:] for v in row[1:])
    check('Discriminant: the confusion matrix counts the 149 complete rows', total, 149.0)
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const ctx = {CTX}; const t = rep.table; const before = t.columns.length;
      const so = rep.platform.triangle(ctx).find(i => i.label === 'Score Options').submenu();
      await so.find(i => i.label === 'Save Formulas').action();
      const added = t.columns.slice(before).map(c => [c.name, c.modelingType, c.dataType]);
      const probs = t.columns.slice(before).filter(c => c.name.startsWith('Prob['));
      const s = probs.reduce((acc, c) => acc + c.values[0], 0);
      for (const c of t.columns.slice(before)) t.removeColumn(c.id);
      await so.find(i => i.label === 'Select Misclassified Rows').action();
      const mis = t.selectedRows().length; t.select([]);
      return {{ added, s, mis }};
    }})()''')
    check('Discriminant: Save Formulas', [x[0] for x in r['added']], ['SqDist[hi]', 'SqDist[lo]', 'SqDist[mid]', 'Prob[hi]', 'Prob[lo]', 'Prob[mid]', 'Pred grp'])
    check('Discriminant: the probabilities of a row sum to 1', round(r['s'], 9), 1.0)
    check('Discriminant: the predicted group is nominal character', r['added'][-1][1:], ['nominal', 'character'])
    nm = await page.ev(table_under_js('Score Summaries', 0))
    check('Discriminant: Select Misclassified Rows = Number Misclassified', str(r['mis']), nm[1][1])
    await shot(page, 'mv-03-discriminant.png')

    # ---- Hierarchical Cluster ------------------------------------------------------------------------
    r = await page.ev(open_report_js('hcluster', {'y': ['u', 'v']}, {'method': 'ward', 'standardize': 'none', 'criterion': True, 'summary': True, 'twoWay': True}), timeout=240)
    check('Hierarchical: no errors', r['errors'], [])
    legend = await page.ev(f'[...{LAST}.content.querySelectorAll(".mv-legend button")].map(b => b.textContent)')
    check('Hierarchical: the default is the three simulated clusters', legend, ['1: 50', '2: 50', '3: 50'])
    await run_menu(page, 'Color Clusters')
    colors = await page.ev('(() => { const t = SM.app.current; const s = new Set(); for (let i = 0; i < t.nrows; i++) s.add(t.color[i]); return [...s].sort(); })()')
    check('Hierarchical: Color Clusters gives the rows three colours', colors, [0, 1, 2])
    same = await page.ev('(() => { const t = SM.app.current; for (let i = 0; i + 3 < t.nrows; i++) if (t.color[i] !== t.color[i + 3]) return false; return true; })()')
    check('Hierarchical: the colours follow the simulated clusters', same, True)
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const ctx = {CTX};
      ctx.set('ncluster', 5); await new Promise(res => rep.on('done', res));
      return [...rep.content.querySelectorAll('.mv-legend button')].length;
    }})()''')
    check('Hierarchical: five clusters on request', r, 5)
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const ctx = {CTX};
      ctx.set('ncluster', 3); await new Promise(res => rep.on('done', res));
      const t = rep.table; const before = t.columns.length;
      await rep.platform.triangle(ctx).find(i => i.label === 'Save Clusters').action();
      const c = t.columns[t.columns.length - 1]; const out = {{ name: c.name, type: c.modelingType, levels: t.levels(c) }}; t.removeColumn(c.id); return out;
    }})()''')
    check('Hierarchical: Save Clusters', (r['name'], r['type'], r['levels']), ('Cluster', 'nominal', [1, 2, 3]))
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const p = rep.plots.find(p => p.opts.title === 'Dendrogram'); await p.draw();
      const t = rep.table; t.select([4]); await new Promise(r => setTimeout(r, 150));
      const leaf = p.kinds.findIndex(k => k === 'points'); const sp = p.box.data[leaf].selectedpoints; t.select([]); return sp.length;
    }})()''')
    check('Hierarchical: a selected row lights its leaf', r, 1)
    await page.ev('SM.app.current.clearRowStates()')
    await shot(page, 'mv-04-hcluster.png')

    # ---- K Means -----------------------------------------------------------------------------------------
    r = await page.ev(open_report_js('kmeans', {'y': ['u', 'v']}, {'k': 2, 'kRange': 5, 'scaled': False}), timeout=240)
    check('K Means: no errors', r['errors'], [])
    check('K Means: a report per number of clusters', [o for o in r['outlines'] if o.startswith('K Means NCluster')], ['K Means NCluster=2', 'K Means NCluster=3', 'K Means NCluster=4', 'K Means NCluster=5'])
    comp = await page.ev(table_under_js('Cluster Comparison'))
    best = [row for row in comp[1:] if row[3] == 'Optimal CCC']
    check('K Means: the optimal CCC is at 3 clusters', best[0][1] if best else None, '3')
    summ = await page.ev(f'''(() => {{ const rep = {LAST}; const h = [...rep.content.querySelectorAll('.sm-ob-head h3')].find(h => h.textContent === 'K Means NCluster=3'); const t = h.closest('.sm-ob').querySelector('table.sm-rt'); return [...t.querySelectorAll('tbody tr')].map(tr => tr.children[1].textContent); }})()''')
    check('K Means: the three clusters of 50', summ, ['50', '50', '50'])
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const p = rep.plots.find(p => p.opts.title === 'Biplot, 3 clusters'); await p.draw();
      p._click({{ points: [{{ curveNumber: 0, pointNumber: 3 }}], event: {{}} }});
      const sel = rep.table.selectedRows(); rep.table.select([]); return [sel, p.rows[0][3]];
    }})()''')
    check('K Means: a click on the biplot selects the row', r[0], [r[1]])

    # ---- Response Screening --------------------------------------------------------------------------------
    r = await page.ev(open_report_js('respscreen', {'y': ['a', 'b', 'c', 'grp'], 'x': ['d', 'e', 'grp']}, {'lwR2': True}), timeout=240)
    check('Response Screening: no errors', r['errors'], [])
    pv = await page.ev(table_under_js('PValues'))
    check('Response Screening: 11 pairs (grp is not tested against itself)', len(pv) - 1, 11)
    lw = [float(x[6].replace('−', '-')) for x in pv[1:]]
    check('Response Screening: sorted by FDR LogWorth', lw == sorted(lw, reverse=True), True)
    has = await page.ev('!!SM.platforms.get("fitybyx")')
    r = await page.ev(f'''(async () => {{
      const n = SM.app.reports.length; const rep = {LAST};
      const tr = [...rep.content.querySelectorAll('table.sm-rt')].pop().querySelector('tbody tr'); tr.click();
      await new Promise(r => setTimeout(r, 500));
      const top = SM.app.reports[SM.app.reports.length - 1];
      return {{ opened: SM.app.reports.length - n, platform: top.platform.id, y: top.spec.roles && top.spec.roles.y && SM.app.current.col(top.spec.roles.y[0]).name }};
    }})()''')
    if has:
        check('Response Screening: a line opens Fit Y by X for its pair', (r['opened'], r['platform'], r['y']), (1, 'fitybyx', pv[1][0]))
        await page.ev(f'SM.app.closeReport({LAST})')
    else:
        check('Response Screening: without Fit Y by X a line opens nothing', r['opened'], 0)

    # ---- Explore Outliers ---------------------------------------------------------------------------------------
    await page.ev('(() => { const t = SM.app.current; t.setCell(20, "a", 9999, { silent: true }); t.setCell(30, "c", -40); })()')
    r = await page.ev(open_report_js('outliers', {'y': ['a', 'b', 'c', 'd', 'e']}, {'qro': True, 'rfo': True, 'mro': True, 'knn': True}), timeout=240)
    check('Explore Outliers: no errors', r['errors'], [])
    q = await page.ev(table_under_js('Quantile Range Outliers'))
    rows = {x[0]: x for x in q[1:]}
    check('Quantile range: the planted 9999 in a', (rows['a'][5], rows['a'][6]), ('1', '9999'))
    check('Quantile range: the planted −40 in c', (rows['c'][5], rows['c'][6]), ('1', '−40'))
    nines = await page.ev(f'[...{LAST}.content.querySelectorAll(".sm-ob-head h4")].map(h => h.textContent).includes("Nines")')
    check('Quantile range: 9999 listed as a probable missing value code', nines, True)
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const b = [...rep.content.querySelectorAll('.sm-btn')].find(x => x.textContent === 'Select Rows'); b.click();
      await new Promise(r => setTimeout(r, 100)); const sel = rep.table.selectedRows(); rep.table.select([]); return sel;
    }})()''')
    check('Quantile range: Select Rows selects the two rows', r, [20, 30])
    mro = await page.ev(f'''(() => {{ const rep = {LAST}; const p = rep.plots.find(p => p.opts.title === 'Robust distances by row'); const i = p.rows[0].indexOf(20); return i >= 0 && p.traces[0].y[i] > 100; }})()''')
    check('Multivariate robust: row 21 far out', mro, True)
    await page.ev('(() => { const t = SM.app.current; t.setCell(20, "a", 0.1, { silent: true }); t.setCell(30, "c", 0.1); })()')
    await shot(page, 'mv-05-outliers.png')

    # ---- Multiple Correspondence Analysis, Multidimensional Scaling ----------------------------------------------------
    r = await page.ev(open_report_js('mca', {'y': ['grp', 'q1', 'q2']}, {'rowplot': True, 'adjusted': True, 'coords': True, 'summary': True, 'cross': True}), timeout=240)
    check('MCA: no errors', r['errors'], [])
    check('MCA: outlines', [o for o in ['Correspondence Analysis', 'Row Plot', 'Details', 'Adjusted Inertia', 'Coordinates', 'Summary Statistics', 'Cross Table (Burt)'] if o not in r['outlines']], [])
    det = await page.ev(table_under_js('Details'))
    check('MCA: J − Q = 5 dimensions', len(det) - 1, 5)
    check('MCA: the portions sum to 1', round(sum(float(x[3]) for x in det[1:]), 3), 1.0)
    r = await page.ev(open_report_js('mds', {'y': ['u', 'v']}, {'standardize': False, 'eigen': True}), timeout=240)
    check('MDS: no errors', r['errors'], [])
    fit = await page.ev(table_under_js('Fit Details'))
    check('MDS of two columns: the map is exact (stress 0)', abs(float(fit[0][1].replace('−', '-'))) < 1e-6, True)
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const p = rep.plots.find(p => p.opts.title === 'Multidimensional Scaling Plot'); await p.draw();
      p._click({{ points: [{{ curveNumber: 0, pointNumber: 5 }}], event: {{}} }});
      const sel = rep.table.selectedRows(); rep.table.select([]);
      const ctx = {CTX}; const t = rep.table; const before = t.columns.length;
      await rep.platform.triangle(ctx).find(i => i.label === 'Save Coordinates').action();
      const added = t.columns.slice(before).map(c => c.name); for (const c of t.columns.slice(before)) t.removeColumn(c.id);
      return {{ sel, want: p.rows[0][5], added }};
    }})()''')
    check('MDS: a click on the map selects the row', r['sel'], [r['want']])
    check('MDS: Save Coordinates', r['added'], ['MDS Dimension 1', 'MDS Dimension 2'])

    # ---- Item Reliability: intraclass correlations and Kendall's W ------------------------------------------------------
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'Multivariate test')))")
    r = await page.ev(open_report_js('multivariate', {'y': ['a', 'b', 'c', 'd', 'e']}, {'icc': True, 'kendallw': True, 'splom': False}), timeout=240)
    check('Item Reliability: no errors', r['errors'], [])
    check('Item Reliability: Intraclass Correlations and Kendall\'s W', [o for o in ('Intraclass Correlations', "Kendall's W") if o in r['outlines']], ['Intraclass Correlations', "Kendall's W"])
    items = await page.ev(f'''(() => {{ const rep = {LAST}; const ctx = {CTX}; const it = rep.platform.triangle(ctx).find(i => i.label === 'Item Reliability');
      return it.submenu().map(i => i.separator ? '—' : i.label); }})()''')
    check('the Item Reliability submenu', items, ["Cronbach's α", 'Standardized α', '—', 'Intraclass Correlations', "Kendall's W"])
    js = await page.ev('''(() => {
      const t = SM.app.current; const X = ['a', 'b', 'c', 'd', 'e'].map(n => t.col(n).values);
      const rows = [...Array(t.nrows).keys()].filter(i => X.every(v => Number.isFinite(v[i])));
      const n = rows.length, k = X.length;
      const g = rows.reduce((s, i) => s + X.reduce((a, v) => a + v[i], 0), 0) / (n * k);
      let ssr = 0, ssc = 0, sst = 0;
      for (const i of rows) { const m = X.reduce((a, v) => a + v[i], 0) / k; ssr += k * (m - g) ** 2; for (const v of X) sst += (v[i] - g) ** 2; }
      for (const v of X) { const m = rows.reduce((a, i) => a + v[i], 0) / n; ssc += n * (m - g) ** 2; }
      const sse = sst - ssr - ssc, msr = ssr / (n - 1), msc = ssc / (k - 1), mse = sse / ((n - 1) * (k - 1)), msw = (ssc + sse) / (n * (k - 1));
      const rank = (vals) => { const idx = vals.map((v, i) => [v, i]).sort((p, q) => p[0] - q[0]); const r = new Array(vals.length); let j = 0, T = 0;
        while (j < idx.length) { let e = j; while (e + 1 < idx.length && idx[e + 1][0] === idx[j][0]) e++; for (let q = j; q <= e; q++) r[idx[q][1]] = (j + e) / 2 + 1; T += (e - j + 1) ** 3 - (e - j + 1); j = e + 1; }
        return { r, T }; };
      let T = 0; const Rs = new Array(n).fill(0);
      for (const v of X) { const o = rank(rows.map(i => v[i])); T += o.T; o.r.forEach((x, q) => { Rs[q] += x; }); }
      const mean = Rs.reduce((a, b) => a + b) / n, S = Rs.reduce((a, b) => a + (b - mean) ** 2, 0);
      return { n, one: (msr - msw) / (msr + (k - 1) * msw), c1: (msr - mse) / (msr + (k - 1) * mse), a1: (msr - mse) / (msr + (k - 1) * mse + k * (msc - mse) / n), ck: (msr - mse) / msr,
        fr: msr / mse, w: 12 * S / (k * k * (n ** 3 - n) - k * T) };
    })()''')
    num = lambda s: float(str(s).replace('−', '-').replace('<', '').replace('*', ''))  # noqa: E731
    it = await page.ev(table_under_js('Intraclass Correlations', 2))
    icc = {row[0]: row for row in it[1:]}
    check('the ICC table: its columns', it[0], ['Form', 'Shrout–Fleiss', 'Model', 'ICC', 'F Ratio', 'NumDF', 'DenDF', 'Prob > F', 'Lower 95%', 'Upper 95%'])
    check('... the six forms', list(icc), ['ICC(1,1)', 'ICC(A,1)', 'ICC(C,1)', 'ICC(1,k)', 'ICC(A,k)', 'ICC(C,k)'])
    check.near('ICC(1,1) = the one-way ANOVA computed in the page', num(icc['ICC(1,1)'][3]), js['one'], 1e-4)
    check.near('ICC(C,1) = the two-way ANOVA computed in the page', num(icc['ICC(C,1)'][3]), js['c1'], 1e-4)
    check.near('ICC(A,1) = the page\'s', num(icc['ICC(A,1)'][3]), js['a1'], 1e-4)
    check.near('ICC(C,k) = the page\'s', num(icc['ICC(C,k)'][3]), js['ck'], 1e-4)
    check.near('its F = MSR/MSE', num(icc['ICC(C,1)'][4]), js['fr'], 1e-6)
    check('... on 148 and 592 DF (149 complete rows, 5 raters)', (icc['ICC(C,1)'][5], icc['ICC(C,1)'][6]), ('148', '592'))
    av = await page.ev(table_under_js('Intraclass Correlations', 1))
    check('the ANOVA table: Between Targets, Between Raters, Residual, Within Targets, Total', [row[0] for row in av[1:]], ['Between Targets', 'Between Raters', 'Residual', 'Within Targets', 'Total'])
    kv = dict((row[0], row[1]) for row in await page.ev(table_under_js("Kendall's W")))
    check.near("Kendall's W = the page's own ranks (ties corrected)", num(kv["Kendall's W"]), js['w'], 1e-6)
    check.near('its ChiSquare = m (n − 1) W', num(kv['ChiSquare']), 5 * (js['n'] - 1) * js['w'], 1e-6)
    check("Kendall's W: DF and the objects", (kv['DF'], kv['Objects (rows)'], kv['Raters (columns)']), ('148', '149', '5'))
    txt = await page.ev(f'{LAST}.content.textContent')
    check('the notes say which rows count', ('rated by every rater (149 of them)' in txt, '1 row without a rating from every rater' in txt), (True, True))
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const t = rep.table;
      const h = [...rep.content.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim() === 'Intraclass Correlations');
      const tbl = h.parentElement.querySelectorAll('table.sm-rt')[1];
      const col = tbl._rt.columns.find(c => c.label === 'ICC');
      const res = await SM.bootstrap.run(tbl, col, {{ B: 3, seed: 13, show: false }});
      const rows = SM.bootstrap.sampler(rep.groups()[0].rows, 13)();
      const own = await SM.engine.call('multivariate.icc', {{ columns: ['a', 'b', 'c', 'd', 'e'], rows }}, t);
      const out = {{ cols: res.columns.map(c => c.name).slice(0, 3), b0: res.col('ICC(C,1) ICC(3,1) Two-way, consistency, one rater').values[0], b1: res.col('ICC(C,1) ICC(3,1) Two-way, consistency, one rater').values[1],
        own: own.icc.find(x => x.form === 'ICC(C,1)').icc, report: tbl._rt.rows.find(x => x.form === 'ICC(C,1)').icc }};
      SM.app.closeTable(res); return out;
    }})()''', timeout=300)
    check('Bootstrap of the ICC column: its rows are the forms', r['cols'], ['BootID', 'ICC(1,1) ICC(1,1) One-way random, one rater', 'ICC(A,1) ICC(2,1) Two-way, absolute agreement, one rater'])
    check.near('... sample 0 is the report', r['b0'], r['report'], 1e-12)
    check.near('... sample 1 is multivariate.icc on its rows (the render has no side effects)', r['b1'], r['own'], 1e-12)
    r = await run_menu(page, 'Item Reliability', 'Intraclass Correlations')
    outl = await page.ev(f'[...{LAST}.content.querySelectorAll(".sm-ob-head h3")].map(h => h.textContent)')
    check('the submenu item turns Intraclass Correlations off', (r, 'Intraclass Correlations' in outl, "Kendall's W" in outl), ('ok', False, True))
    await shot(page, 'mv-08-reliability.png')

    # ---- every (i) of these reports has a topic, every Help link a target -------------------------------------------
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) in the reports has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helprows = await page.ev('["multivariate", "pca", "factor", "discriminant", "hcluster", "kmeans", "respscreen", "outliers", "mca", "mds"].filter(id => !document.getElementById("help-p-" + id))')
    check('the Help tab lists the ten platforms', helprows, [])

    # ---- By, for every platform ------------------------------------------------------------------------------------------
    await page.ev('SM.app.current.setType("f", { modelingType: "nominal" })')
    by_specs = [('multivariate', {'y': ['a', 'c', 'e']}, {'mahal': True, 'alpha:raw': True, 'dcor': True, 'icc': True, 'kendallw': True}), ('pca', {'y': ['a', 'c', 'e']}, {}),
                ('factor', {'y': ['a', 'b', 'c', 'd', 'e']}, {'fits': [{'method': 'ml', 'prior': 'smc', 'k': 1, 'rotation': 'none'}]}),
                ('discriminant', {'y': ['a', 'c'], 'x': ['grp']}, {}), ('hcluster', {'y': ['u', 'v']}, {}), ('kmeans', {'y': ['u', 'v']}, {'k': 3}),
                ('respscreen', {'y': ['a', 'b'], 'x': ['c', 'grp']}, {}), ('outliers', {'y': ['a', 'c']}, {'qro': True, 'mro': True}),
                ('mca', {'y': ['grp', 'q1']}, {}), ('mds', {'y': ['a', 'c']}, {})]
    for pid, roles, opts in by_specs:
        r = await page.ev(open_report_js(pid, {**roles, 'by': ['f']}, opts), timeout=240)
        tops = [o for o in r['outlines'] if o.endswith(('f=1', 'f=2', 'f=3'))]
        check(f'By: {pid} gives three groups without an error', (len(tops), r['errors']), (3, []))
        await page.ev(f'SM.app.closeReport({LAST})')
    await page.ev('SM.app.current.setType("f", { modelingType: "continuous" })')

    # ---- exclusion and Redo ---------------------------------------------------------------------------------------
    r = await page.ev(open_report_js('multivariate', {'y': ['a', 'c']}, {}), timeout=240)
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const t = rep.table; t.setState([0, 1, 2, 3, 4, 5], 'excluded', true);
      rep.run(); await new Promise(res => rep.on('done', res));
      const txt = rep.content.textContent; t.setState([0, 1, 2, 3, 4, 5], 'excluded', false); return txt.includes('144 observations');
    }})()''')
    check('exclude rows and Redo: 144 observations', r, True)

    # ---- dark theme, phone width ------------------------------------------------------------------------------------
    r = await page.ev(open_report_js('multivariate', {'y': ['a', 'b', 'c', 'd', 'e']}, {'cmCells': True, 'pairwise': True, 'mahal': True, 'dcor': True, 'icc': True, 'kendallw': True}), timeout=240)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev(f'new Promise(res => {LAST}.on("done", res))')
    await asyncio.sleep(1.2)
    ink = await page.ev(f'''(() => {{
      const td = {LAST}.content.querySelector('td.mv-cm'); const cs = getComputedStyle(td);
      const rgb = (s) => s.match(/\\d+/g).slice(0, 3).map(Number); const lum = ([r, g, b]) => (0.299 * r + 0.587 * g + 0.114 * b) / 255;
      return Math.abs(lum(rgb(cs.color)) - lum(rgb(cs.backgroundColor)));
    }})()''')
    check('dark theme: coloured cells keep their contrast', ink > 0.4, True)
    check('dark theme: no errors', (await page.ev(f'[...{LAST}.content.querySelectorAll(".sm-ob-error")].length'), page.errors), (0, []))
    await shot(page, 'mv-06-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    check('phone width: no horizontal page scroll', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, 'mv-07-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
