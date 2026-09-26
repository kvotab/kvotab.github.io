#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Fit Y by X and
Specialized Modeling > Matched Pairs.

The platforms load and are in the menus; the launch dialog casts columns
and shows which analysis each pair of modeling types gets; the red
triangles add fits and tests, and the numbers they show agree with the
same statistics computed here in the page's JavaScript from the table
(least squares, the one-way F, Kruskal-Wallis, Levene, the Pearson
chi-square, the paired t); points, bars and mosaic cells select their
rows and selected rows light up; saved columns hold the fit's values; By,
Group By, several pairs, exclusion and Redo work; every (i) has a topic;
the reports draw in the dark theme and at phone width; a 60 000-row table
stays quick.

Start a server on the repository root and headless Chrome (the recipe is in
README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-fitybyx.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import os
import sys
import time

from cdp import BASE, Checks, open_page, table_under_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


# Helpers put into the page once: open a report, pick red-triangle items,
# read the tables under an outline, statistics computed in JavaScript.
HELPERS = r'''
window.__fyx = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  rep: () => SM.app.reports[SM.app.reports.length - 1],
  table(name) { return SM.app.tables.find((t) => t.name === name); },
  async open(tableName, platform, roles, options) {
    const t = this.table(tableName);
    SM.app.showTab(SM.app.tabOf(t));
    const ids = {};
    for (const [k, names] of Object.entries(roles)) ids[k] = names.map((n) => { const c = t.col(n); if (!c) throw new Error('no column ' + n); return c.id; });
    const rep = SM.app.openReport(SM.platforms.get(platform), { roles: ids, options: options || {} }, t);
    await new Promise((res) => rep.on('done', res));
    await this.sleep(300);
    return rep;
  },
  heads(rep) { return [...(rep || this.rep()).body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map((h) => h.textContent); },
  errors(rep) { return [...(rep || this.rep()).body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent.slice(0, 400)); },
  head(title, rep) { return [...(rep || this.rep()).body.querySelectorAll('.sm-ob-head')].find((h) => h.querySelector('h2, h3, h4').textContent === title); },
  async pick(title, path, rep) {
    rep = rep || this.rep();
    const h = this.head(title, rep);
    if (!h) throw new Error('no outline ' + title);
    const done = new Promise((res) => rep.on('done', res));
    h.querySelector('.sm-ob-menu').click();
    for (const label of path) {
      await this.sleep(60);
      const menus = document.querySelectorAll('.sm-menu');
      const m = menus[menus.length - 1];
      const b = [...m.querySelectorAll('button')].find((x) => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === label);
      if (!b) { SM.ui.closeMenus(0); throw new Error('no menu item ' + label + ' in ' + [...m.querySelectorAll('.sm-label')].map((x) => x.textContent).join('|')); }
      b.click();
    }
    return done;
  },
  async dialogOK(fill) {
    let d = null;
    for (let i = 0; i < 60 && !d; i++) { await this.sleep(50); d = [...document.querySelectorAll('.sm-dialog')].pop(); }
    if (!d) throw new Error('no dialog opened');
    if (fill) fill(d);
    d.querySelector('.sm-dialog-foot .primary').click();
  },
  tableUnder(title, n = 0, rep) {
    const h = this.head(title, rep);
    if (!h) return null;
    const body = h.parentElement.querySelector(':scope > .sm-ob-body');
    const t = body.querySelectorAll(':scope > table.sm-rt, :scope > table.sm-kv, :scope > .sm-ob-row table, :scope > .sm-fyx-scroll > table')[n];
    if (!t) return null;
    // a cell of stacked numbers (the contingency table) reads as its numbers joined by spaces
    return [...t.querySelectorAll('tr')].map((tr) => [...tr.children].map((c) => (c.querySelector('.sm-fyx-stack') ? [...c.querySelectorAll('.sm-fyx-stack > div')].map((x) => x.textContent.trim()).join(' ') : c.textContent.trim())));
  },
  num(s) { return SM.table.toNumber(String(s).replace(/−/g, '-').replace(/[<*]/g, '')); },
  // least squares of y on x
  line(xs, ys) {
    const n = xs.length; const mx = xs.reduce((a, b) => a + b, 0) / n; const my = ys.reduce((a, b) => a + b, 0) / n;
    let sxy = 0, sxx = 0, syy = 0; for (let i = 0; i < n; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) ** 2; syy += (ys[i] - my) ** 2; }
    const b = sxy / sxx; return { a: my - b * mx, b, r2: sxy * sxy / (sxx * syy), n };
  },
  groups(t, yName, xName, rows) {
    const y = t.col(yName), x = t.col(xName); const g = new Map();
    for (const r of rows || t.includedRows()) { const v = y.values[r], k = x.values[r]; if (!Number.isFinite(v) || SM.table.isMissing(k)) continue; if (!g.has(k)) g.set(k, []); g.get(k).push(v); }
    return [...g.entries()].sort((a, b) => SM.table.collator.compare(String(a[0]), String(b[0]))).map((e) => e[1]);
  },
  anovaF(groups) {
    const all = groups.flat(); const N = all.length, k = groups.length; const m = all.reduce((a, b) => a + b, 0) / N;
    let ssb = 0, ssw = 0; for (const g of groups) { const gm = g.reduce((a, b) => a + b, 0) / g.length; ssb += g.length * (gm - m) ** 2; for (const v of g) ssw += (v - gm) ** 2; }
    return (ssb / (k - 1)) / (ssw / (N - k));
  },
  kruskal(groups) {
    const all = groups.flat(); const N = all.length; const r = SM.util.ranks(all); let at = 0, h = 0; const rbar = (N + 1) / 2;
    let ss = 0; for (const v of r) ss += (v - rbar) ** 2;
    for (const g of groups) { const rs = r.slice(at, at + g.length); at += g.length; const m = rs.reduce((a, b) => a + b, 0) / g.length; h += g.length * (m - rbar) ** 2; }
    return (N - 1) * h / ss;
  },
  levene(groups) { return this.anovaF(groups.map((g) => { const m = g.reduce((a, b) => a + b, 0) / g.length; return g.map((v) => Math.abs(v - m)); })); },
};
'''


async def main():
    page = await open_page(f'{BASE}/smui.html?example=students')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.map(f => f.module + ": " + f.error)')
    check('fit_y_by_x imports', [f for f in failed if f.startswith('fit_y_by_x')], [])
    check('the backend names are there', await page.ev('["fitybyx.fit_poly", "fitybyx.oneway", "fitybyx.logistic", "fitybyx.contingency", "matchedpairs.analyze"].every(n => SM.engine.has(n))'), True)
    await page.ev(HELPERS)
    await page.ev("SM.app.openExample('plants'); SM.app.openExample('clinical'); SM.app.showTab(SM.app.tabOf(SM.app.tables[0]))")
    menu = await page.ev('SM.app.menuItems("Analyze").map(i => i.label || (i.separator ? "—" : ""))')
    check('Analyze lists Fit Y by X after Distribution', menu[:2], ['Distribution…', 'Fit Y by X…'])
    sub = await page.ev('(() => { const it = SM.app.menuItems("Analyze").find(i => i.label === "Specialized Modeling"); if (!it) return null; const s = typeof it.submenu === "function" ? it.submenu() : it.submenu; return s.map(i => i.label); })()')
    check('Specialized Modeling lists Matched Pairs', 'Matched Pairs…' in (sub or []), True)

    # ---- the launch dialog
    r = await page.ev('''(async () => {
      SM.app.showTab(SM.app.tabOf(__fyx.table('Students')));
      SM.app.launch('fitybyx');
      await __fyx.sleep(200);
      const dlg = document.querySelector('.sm-launch-dialog');
      const map = [...dlg.querySelectorAll('.sm-fyx-map-cell strong')].map(s => s.textContent);
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => items.find(li => li.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      const btn = (label) => [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === label);
      pick('weight (kg)'); btn('Y, Response').click();
      pick('height (cm)'); btn('X, Factor').click();
      const infos = dlg.querySelectorAll('.sm-role .kvot-info-slot .info-btn').length;
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
      const rep = __fyx.rep();
      await new Promise(res => rep.on('done', res));
      return { map, infos, title: rep.title, heads: __fyx.heads(rep), plots: rep.plots.length };
    })()''')
    check('the launch dialog shows the four analyses', r['map'], ['Bivariate', 'Oneway', 'Logistic', 'Contingency'])
    check('Weight and Freq have an (i)', r['infos'], 2)
    check('a continuous pair is a Bivariate', r['title'], 'Bivariate Fit of weight (kg) By height (cm)')
    check('the scatterplot', r['plots'], 1)

    # ---- Bivariate: Fit Line from the red triangle; the numbers; confidence curves
    await page.ev("__fyx.pick('Bivariate Fit of weight (kg) By height (cm)', ['Fit Line'])")
    r = await page.ev('''(() => {
      const t = __fyx.table('Students'); const L = __fyx.line(t.col('height (cm)').values, t.col('weight (kg)').values);
      const pe = __fyx.tableUnder('Parameter Estimates'); const sof = __fyx.tableUnder('Summary of Fit');
      return { heads: __fyx.heads(), a: __fyx.num(pe[1][1]), b: __fyx.num(pe[2][1]), term: pe[2][0], r2: __fyx.num(sof[0][1]), n: __fyx.num(sof[4][1]), want: L,
               eq: document.querySelector('.sm-fyx-eq').textContent, traces: __fyx.rep().plots[0].traces.length, errors: __fyx.errors() };
    })()''')
    check('Fit Line adds its outline', [h for h in r['heads'] if h in ('Linear Fit', 'Summary of Fit', 'Analysis of Variance', 'Parameter Estimates')], ['Linear Fit', 'Summary of Fit', 'Analysis of Variance', 'Parameter Estimates'])
    check.near('the slope = least squares in the page', r['b'], r['want']['b'], 1e-6)
    check.near('the intercept', r['a'], r['want']['a'], 1e-6)
    check.near('RSquare', r['r2'], r['want']['r2'], 1e-6)
    check('Observations', r['n'], 60)
    check('the term is the X column', r['term'], 'height (cm)')
    check('the equation', r['eq'].startswith('weight (kg) = −') and '*height (cm)' in r['eq'], True)
    before = r['traces']
    await page.ev("__fyx.pick('Linear Fit', ['Confid Curves Fit'])")
    r = await page.ev('__fyx.rep().plots[0].traces.length')
    check('Confid Curves Fit adds two curves', r, before + 2)
    # the fit's options are kept by Redo
    r = await page.ev('''(async () => { const rep = __fyx.rep(); rep.run(); await new Promise(res => rep.on('done', res));
      const f = Object.entries(rep.spec.options).find(([k]) => k.endsWith('|fits'))[1]; return { n: rep.plots[0].traces.length, fit: f[0] }; })()''')
    check('Redo keeps the fit and its confidence curves', (r['n'], r['fit']['kind'], r['fit']['cfit']), (before + 2, 'line', True))
    # Save Residuals: the residuals of the line
    r = await page.ev('''(async () => {
      const t = __fyx.table('Students'); const n0 = t.columns.length;
      __fyx.head('Linear Fit').querySelector('.sm-ob-menu').click(); await __fyx.sleep(60);
      [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent.includes('Save Residuals')).click();
      await __fyx.sleep(900);
      const c = t.columns[t.columns.length - 1];
      const L = __fyx.line(t.col('height (cm)').values, t.col('weight (kg)').values);
      const want = t.col('weight (kg)').values[7] - (L.a + L.b * t.col('height (cm)').values[7]);
      return { added: t.columns.length - n0, name: c.name, v: c.values[7], want };
    })()''')
    check('Save Residuals adds a column', (r['added'], r['name']), (1, 'Residuals weight (kg)'))
    check.near('the saved residual', r['v'], r['want'], 1e-6)
    # Polynomial, density ellipse from the submenus
    await page.ev("__fyx.pick('Bivariate Fit of weight (kg) By height (cm)', ['Fit Polynomial', '2, quadratic'])")
    await page.ev("__fyx.pick('Bivariate Fit of weight (kg) By height (cm)', ['Density Ellipse', '0.90'])")
    r = await page.ev('({ heads: __fyx.heads(), errors: __fyx.errors(), legend: [...__fyx.rep().plots[0].box.querySelectorAll(".legendtext")].map(e => e.textContent) })')
    check('Fit Polynomial and Density Ellipse', [h for h in r['heads'] if h.startswith('Polynomial') or h.startswith('Bivariate Normal')], ['Polynomial Fit Degree=2', 'Bivariate Normal Ellipse P=0.900'])
    check('the legend names the fits', r['legend'], ['Linear Fit', 'Polynomial Fit Degree=2', 'Bivariate Normal Ellipse P=0.900'])
    check('no errors in the Bivariate report', r['errors'], [])
    # Select Points Inside: the rows within the ellipse, computed here
    r = await page.ev('''(async () => {
      const t = __fyx.table('Students'); const x = t.col('height (cm)').values, y = t.col('weight (kg)').values; const n = x.length;
      const mx = x.reduce((a, b) => a + b, 0) / n, my = y.reduce((a, b) => a + b, 0) / n;
      let sxx = 0, syy = 0, sxy = 0; for (let i = 0; i < n; i++) { sxx += (x[i] - mx) ** 2; syy += (y[i] - my) ** 2; sxy += (x[i] - mx) * (y[i] - my); }
      sxx /= n - 1; syy /= n - 1; sxy /= n - 1; const det = sxx * syy - sxy * sxy; const c = -2 * Math.log(0.1);
      const want = []; for (let i = 0; i < n; i++) { const dx = x[i] - mx, dy = y[i] - my; if ((syy * dx * dx - 2 * sxy * dx * dy + sxx * dy * dy) / det <= c) want.push(i); }
      __fyx.head('Bivariate Normal Ellipse P=0.900').querySelector('.sm-ob-menu').click(); await __fyx.sleep(60);
      [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent.includes('Select Points Inside')).click(); await __fyx.sleep(200);
      const got = t.selectedRows(); t.select([]);
      return { same: JSON.stringify(got) === JSON.stringify(want), n: got.length };
    })()''')
    check('Select Points Inside selects the rows inside the ellipse', r['same'], True)
    # linking: a point click selects its row; a table selection shows on the plot
    r = await page.ev('''(async () => {
      const rep = __fyx.rep(); const p = rep.plots[0]; const t = rep.table;
      p._click({ points: [{ curveNumber: 0, pointNumber: 5 }], event: {} });
      const sel = t.selectedRows();
      t.select([10, 11, 12]); await __fyx.sleep(200);
      const sp = p.box.data[0].selectedpoints; t.select([]);
      return { sel, row: p.rows[0][5], sp: sp ? sp.length : null };
    })()''')
    check('a point click selects its row', r['sel'], [r['row']])
    check('selected rows are highlighted in the scatterplot', r['sp'], 3)
    await asyncio.sleep(0.5)
    await shot(page, '01-bivariate.png')

    # Group By, By
    r = await page.ev('''(async () => {
      const t = __fyx.table('Students'); const y = t.col('weight (kg)').id, x = t.col('height (cm)').id;
      const o = {}; o[y + '~' + x + '|fits'] = [{ id: 'f1', kind: 'line' }, { id: 'f2', kind: 'ellipse', p: 0.9 }]; o[y + '~' + x + '|groupBy'] = t.col('sex').id;
      const rep = await __fyx.open('Students', 'fitybyx', { y: ['weight (kg)'], x: ['height (cm)'] }, o);
      const rows = SM.app.current.includedRows().filter(r => t.col('sex').values[r] === 'F');
      const L = __fyx.line(rows.map(r => t.col('height (cm)').values[r]), rows.map(r => t.col('weight (kg)').values[r]));
      const hs = __fyx.heads(rep); const pe = __fyx.tableUnder('Parameter Estimates', 0, rep);
      __fyx.head('Bivariate Normal Ellipse P=0.900 sex==M', rep).querySelector('.sm-ob-menu').click(); await __fyx.sleep(60);
      [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent.includes('Select Points Inside')).click(); await __fyx.sleep(200);
      const sel = t.selectedRows(); t.select([]);
      return { hs: hs.filter(h => h.startsWith('Linear Fit')), b: __fyx.num(pe[2][1]), want: L.b, selM: sel.length > 0 && sel.every(r => t.col('sex').values[r] === 'M') };
    })()''')
    check('Group By: a fit for each level', r['hs'], ['Linear Fit sex==F', 'Linear Fit sex==M'])
    check.near('Group By: the first level\'s slope', r['b'], r['want'], 1e-6)
    check('Group By: a level\'s ellipse selects rows of that level', r['selM'], True)
    r = await page.ev('''(async () => { const rep = await __fyx.open('Students', 'fitybyx', { y: ['weight (kg)'], x: ['height (cm)'], by: ['sex'] }, {});
      return { tops: __fyx.heads(rep).filter(h => h.startsWith('Bivariate')), errors: __fyx.errors(rep) }; })()''')
    check('By: one analysis per level', r['tops'], ['Bivariate Fit of weight (kg) By height (cm) sex=F', 'Bivariate Fit of weight (kg) By height (cm) sex=M'])
    check('By: no errors', r['errors'], [])

    # ---- Oneway: Means/Anova, Tukey, Wilcoxon, Unequal Variances, linking, save
    r = await page.ev('''(async () => { const rep = await __fyx.open('Plant trial', 'fitybyx', { y: ['yield (g)'], x: ['fertilizer'] }, {}); return rep.title; })()''')
    check('a continuous Y by a nominal X is a Oneway', r, 'Oneway Analysis of yield (g) By fertilizer')
    title = 'Oneway Analysis of yield (g) By fertilizer'
    await page.ev(f"__fyx.pick({json.dumps(title)}, ['Means/Anova'])")
    r = await page.ev('''(() => { const t = __fyx.table('Plant trial'); const g = __fyx.groups(t, 'yield (g)', 'fertilizer');
      const aov = __fyx.tableUnder('Analysis of Variance'); const means = __fyx.tableUnder('Means for Oneway Anova');
      const dia = __fyx.rep().plots[0].traces.filter(tr => tr.line && tr.line.color === '#3a7d44').length;
      return { F: __fyx.num(aov[1][4]), src: aov[1][0], want: __fyx.anovaF(g), means: means.slice(1).map(r => [r[0], __fyx.num(r[2])]), wantMeans: g.map(v => v.reduce((a, b) => a + b, 0) / v.length), dia }; })()''')
    check.near('Oneway ANOVA F = the F computed here', r['F'], r['want'], 1e-6)
    check('the ANOVA source is X', r['src'], 'fertilizer')
    check('Means for Oneway Anova levels', [m[0] for m in r['means']], ['A', 'B', 'C'])
    check.near('a level mean', r['means'][2][1], r['wantMeans'][2], 1e-6)
    check('mean diamonds drawn', r['dia'], 3)
    await page.ev(f"__fyx.pick({json.dumps(title)}, ['Compare Means', 'All Pairs, Tukey HSD'])")
    r = await page.ev('''(() => { const hs = __fyx.heads(); const od = __fyx.tableUnder('Ordered Differences Report'); const cl = __fyx.tableUnder('Connecting Letters Report');
      const circles = __fyx.rep().plots[0].traces.filter(tr => tr.xaxis === 'x2').length;
      return { hs: hs.filter(h => /Tukey|Letters|Ordered|Threshold/.test(h)), pairs: od ? od.length - 1 : 0, letters: cl ? cl.slice(1).map(r => r[1]) : null, circles, errors: __fyx.errors() }; })()''')
    check('Tukey HSD outlines', r['hs'], ['Comparisons for all pairs using Tukey-Kramer HSD', 'HSD Threshold Matrix', 'Connecting Letters Report', 'Ordered Differences Report'])
    check('three ordered differences', r['pairs'], 3)
    check('every level has letters', all(bool(v.strip()) for v in r['letters']), True)
    check('comparison circles, one per level', r['circles'], 3)
    await page.ev(f"__fyx.pick({json.dumps(title)}, ['Nonparametric', 'Wilcoxon / Kruskal-Wallis Tests'])")
    await page.ev(f"__fyx.pick({json.dumps(title)}, ['Unequal Variances'])")
    r = await page.ev('''(() => { const t = __fyx.table('Plant trial'); const g = __fyx.groups(t, 'yield (g)', 'fertilizer');
      const kw = __fyx.tableUnder('1-Way Test, ChiSquare Approximation'); const uv = __fyx.tableUnder('Tests that the Variances are Equal', 1);
      const lev = uv.find(r => r[0] === 'Levene');
      return { H: __fyx.num(kw[1][0]), wantH: __fyx.kruskal(g), lev: __fyx.num(lev[1]), wantLev: __fyx.levene(g), errors: __fyx.errors() }; })()''')
    check.near('Kruskal-Wallis = the H computed here', r['H'], r['wantH'], 1e-6)
    check.near('Levene F = the ANOVA of |y − mean| computed here', r['lev'], r['wantLev'], 1e-6)
    check('no errors in the Oneway report', r['errors'], [])
    # With Control, Dunnett's: the dialog asks for the control
    r = await page.ev(f'''(async () => {{
      const p = __fyx.pick({json.dumps(title)}, ['Compare Means', "With Control, Dunnett's…"]);
      await __fyx.dialogOK((d) => {{ const s = d.querySelector('select'); s.value = '1'; }});
      await p;
      const hs = __fyx.heads(); const tb = __fyx.tableUnder('Comparisons with a control');
      return {{ has: hs.includes("Comparisons with a control using Dunnett's Method"), rows: tb ? tb.slice(1).map(r => r[1]) : null }};
    }})()''')
    check('Dunnett\'s with the control chosen in the dialog', (r['has'], r['rows']) if isinstance(r, dict) else r, (True, ['B', 'B']))
    r = await page.ev('''(async () => { const rep = __fyx.rep(); const p = rep.plots[0]; const t = rep.table;
      p._click({ points: [{ curveNumber: 0, pointNumber: 3 }], event: {} }); const sel = t.selectedRows(); t.select([]);
      return { sel, row: p.rows[0][3] }; })()''')
    check('a Oneway point selects its row', r['sel'], [r['row']])
    r = await page.ev(f'''(async () => {{
      const t = __fyx.table('Plant trial'); const n0 = t.columns.length;
      __fyx.head({json.dumps(title)}).querySelector('.sm-ob-menu').click(); await __fyx.sleep(60);
      [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent === 'Save').click(); await __fyx.sleep(60);
      [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent.includes('Save Centered')).click(); await __fyx.sleep(300);
      const c = t.columns[t.columns.length - 1]; const g = t.col('fertilizer').values, y = t.col('yield (g)').values;
      const ys = y.filter((v, i) => g[i] === g[4]); const m = ys.reduce((a, b) => a + b, 0) / ys.length;
      return {{ added: t.columns.length - n0, v: c.values[4], want: y[4] - m }};
    }})()''')
    check('Save Centered adds a column', r['added'], 1)
    check.near('the centered value', r['v'], r['want'], 1e-9)
    await asyncio.sleep(0.4)
    await shot(page, '02-oneway.png')
    r = await page.ev('''(async () => { const rep = await __fyx.open('Plant trial', 'fitybyx', { y: ['yield (g)'], x: ['fertilizer'], block: ['water'] }, {});
      await __fyx.pick(rep.title, ['Means/Anova'], rep); const aov = __fyx.tableUnder('Analysis of Variance', 0, rep); return { src: aov.slice(1).map(r => r[0]), bm: __fyx.heads(rep).includes('Block Means') }; })()''')
    check('Block: the randomized block ANOVA', r['src'], ['fertilizer', 'water', 'Error', 'C. Total'])
    check('Block Means', r['bm'], True)

    # ---- Logistic
    r = await page.ev('''(async () => { const rep = await __fyx.open('Clinical study', 'fitybyx', { y: ['response'], x: ['dose (mg)'] }, {});
      await __fyx.pick(rep.title, ['ROC Curve'], rep); await __fyx.pick(rep.title, ['Odds Ratios'], rep);
      const pe = __fyx.tableUnder('Parameter Estimates', 0, rep); const wm = __fyx.tableUnder('Whole Model Test', 0, rep);
      const note = [...__fyx.head('Parameter Estimates', rep).parentElement.querySelectorAll('.sm-ob-note')].map(n => n.textContent);
      const auc = __fyx.tableUnder('ROC Curve', 0, rep);
      return { title: rep.title, a: __fyx.num(pe[1][1]), b: __fyx.num(pe[2][1]), chisq: __fyx.num(wm[1][3]), note, auc: auc ? __fyx.num(auc[1][1]) : null, heads: __fyx.heads(rep), errors: __fyx.errors(rep), plots: rep.plots.length }; })()''')
    check('a nominal Y by a continuous X is a Logistic', r['title'], 'Logistic Fit of response By dose (mg)')
    check('the log odds of the first level', 'For log odds of no/yes' in r['note'], True)
    check('more dose, fewer no: a negative slope', r['b'] < 0, True)
    check('the likelihood ratio chi-square', r['chisq'] > 0, True)
    check('ROC area between 0.5 and 1', 0.5 < r['auc'] < 1, True)
    check('Odds Ratios', 'Odds Ratios' in r['heads'], True)
    check('no errors in the Logistic report', r['errors'], [])
    # Save Probability Formula: the probabilities from the estimates shown
    r = await page.ev('''(async () => {
      const rep = __fyx.rep(); const t = rep.table; const n0 = t.columns.length;
      __fyx.head(rep.title).querySelector('.sm-ob-menu').click(); await __fyx.sleep(60);
      [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent.includes('Save Probability Formula')).click(); await __fyx.sleep(900);
      const pe = __fyx.tableUnder('Parameter Estimates', 0, rep); const a = __fyx.num(pe[1][1]), b = __fyx.num(pe[2][1]);
      const c = t.col('Prob[no]'); const d = t.col('dose (mg)').values[9];
      return { added: t.columns.length - n0, v: c ? c.values[9] : null, want: 1 / (1 + Math.exp(-(a + b * d))), ml: t.columns[t.columns.length - 1].name };
    })()''')
    check('Save Probability Formula adds Prob[no], Prob[yes], Most Likely', (r['added'], r['ml']), (3, 'Most Likely response'))
    check.near('the saved probability = the estimates shown', r['v'], r['want'], 1e-5)
    r = await page.ev('''(async () => { const rep = __fyx.rep(); const p = rep.plots[0]; const t = rep.table; p._click({ points: [{ curveNumber: 0, pointNumber: 2 }], event: {} }); const s = t.selectedRows(); t.select([]); return { s, row: p.rows[0][2] }; })()''')
    check('a logistic point selects its row', r['s'], [r['row']])
    await asyncio.sleep(0.4)
    await shot(page, '03-logistic.png')

    # ---- Contingency: counts, Pearson, mosaic linking
    r = await page.ev('''(async () => { const rep = await __fyx.open('Clinical study', 'fitybyx', { y: ['response'], x: ['treatment'] }, {});
      const t = rep.table; const X = t.col('treatment').values, Y = t.col('response').values;
      const lx = ['placebo', 'drug'], ly = ['no', 'yes']; const n = lx.map(() => ly.map(() => 0));
      X.forEach((v, i) => { n[lx.indexOf(v)][ly.indexOf(Y[i])]++; });
      const N = X.length; const rs = n.map(r => r[0] + r[1]), cs = [0, 1].map(j => n[0][j] + n[1][j]); let chi = 0;
      for (let i = 0; i < 2; i++) for (let j = 0; j < 2; j++) { const e = rs[i] * cs[j] / N; chi += (n[i][j] - e) ** 2 / e; }
      const ct = __fyx.tableUnder('Contingency Table', 0, rep); const tests = __fyx.tableUnder('Tests', 1, rep);
      return { title: rep.title, cell: ct[1][1].split(/\\s+/)[0], want: n[0][0], pearson: __fyx.num(tests.find(r => r[0] === 'Pearson')[1]), wantChi: chi, heads: __fyx.heads(rep), errors: __fyx.errors(rep) }; })()''')
    check('two nominal columns are a Contingency', r['title'], 'Contingency Analysis of response By treatment')
    check('the count of a cell', int(r['cell']), r['want'])
    check.near('Pearson chi-square = the one computed here', r['pearson'], r['wantChi'], 1e-6)
    check('Mosaic Plot, Contingency Table, Tests, Fisher', [h for h in r['heads'] if h in ('Mosaic Plot', 'Contingency Table', 'Tests', 'Fisher\'s Exact Test')], ['Mosaic Plot', 'Contingency Table', 'Tests', 'Fisher\'s Exact Test'])
    r = await page.ev('''(async () => { const rep = __fyx.rep(); const p = rep.plots[0]; const t = rep.table;
      p._click({ points: [{ curveNumber: 1, pointNumber: 0 }], event: {} }); const sel = t.selectedRows();
      const X = t.col('treatment').values, Y = t.col('response').values; const want = X.map((v, i) => i).filter(i => X[i] === 'placebo' && Y[i] === 'yes');
      await __fyx.sleep(250);
      const comp = p.companions.find(c => c.of === 1); const cd = p.box.data[comp.at]; const src = p.box.data[1];
      const out = { same: JSON.stringify(sel) === JSON.stringify(want), n: sel.length, compBase: cd.base ? cd.base[0] : null, srcBase: src.base[0], compY: cd.y[0], srcY: src.y[0] };
      t.select([]);
      return out; })()''')
    check('a mosaic cell selects its rows', r['same'], True)
    check.near('the selected part sits in the cell', r['compBase'], r['srcBase'], 1e-12)
    check.near('the whole cell selected fills it', r['compY'], r['srcY'], 1e-9)
    await page.ev("__fyx.pick(__fyx.rep().title, ['Analysis of Means for Proportions'])")
    r = await page.ev('''(() => { const t = __fyx.table('Clinical study'); const X = t.col('treatment').values, Y = t.col('response').values;
      const p = ['placebo', 'drug'].map(lv => { const ys = Y.filter((v, i) => X[i] === lv); return ys.filter(v => v === 'no').length / ys.length; });
      const tb = __fyx.tableUnder('Analysis of Means for Proportions', 0); return { got: tb.slice(1).map(r => __fyx.num(r[2])), want: p, errors: __fyx.errors() }; })()''')
    check.near('ANOM for proportions: a level\'s proportion', r['got'][1], r['want'][1], 1e-6)
    await page.ev("__fyx.pick(__fyx.rep().title, ['Measures of Association'])")
    await page.ev("__fyx.pick(__fyx.rep().title, ['Relative Risk'])")
    r = await page.ev('({ heads: __fyx.heads(), errors: __fyx.errors() })')
    check('Measures of Association and Relative Risk', [h for h in r['heads'] if h in ('Measures of Association', 'Relative Risk')], ['Relative Risk', 'Measures of Association'])
    check('no errors in the Contingency report', r['errors'], [])
    await asyncio.sleep(0.4)
    await shot(page, '04-contingency.png')

    # ---- Matched Pairs
    r = await page.ev('''(async () => { const t = __fyx.table('Students');
      const rep = await __fyx.open('Students', 'matchedpairs', { y: ['height (cm)', 'weight (kg)'] }, {});
      const a = t.col('height (cm)').values, b = t.col('weight (kg)').values; const d = b.map((v, i) => v - a[i]); const n = d.length;
      const m = d.reduce((x, y) => x + y, 0) / n; const s = Math.sqrt(d.reduce((x, y) => x + (y - m) ** 2, 0) / (n - 1));
      const k1 = __fyx.tableUnder('Difference: weight (kg)-height (cm)', 0, rep); const k2 = __fyx.tableUnder('Difference: weight (kg)-height (cm)', 1, rep);
      const md = __fyx.num(k1.find(r => r[0] === 'Mean Difference')[1]); const tr = __fyx.num(k2.find(r => r[0] === 't-Ratio')[1]);
      const p = rep.plots[0]; p._click({ points: [{ curveNumber: 0, pointNumber: 4 }], event: {} }); const sel = t.selectedRows(); t.select([]);
      return { title: rep.title, md, want: m, t: tr, wantT: m / (s / Math.sqrt(n)), sel, row: p.rows[0][4], errors: __fyx.errors(rep) }; })()''')
    check('Matched Pairs report', r['title'], 'Matched Pairs')
    check.near('the mean difference = the one computed here', r['md'], r['want'], 1e-6)
    check.near('the paired t ratio', r['t'], r['wantT'], 1e-6)
    check('a pair\'s point selects its row', r['sel'], [r['row']])
    await page.ev("__fyx.pick('Difference: weight (kg)-height (cm)', ['Wilcoxon Signed Rank'])")
    await page.ev("__fyx.pick('Difference: weight (kg)-height (cm)', ['Sign Test'])")
    r = await page.ev('({ heads: __fyx.heads(), errors: __fyx.errors() })')
    check('Wilcoxon Signed Rank and Sign Test', [h for h in r['heads'] if h in ('Wilcoxon Signed Rank', 'Sign Test')], ['Wilcoxon Signed Rank', 'Sign Test'])
    check('no errors in Matched Pairs', r['errors'], [])
    await shot(page, '05-matchedpairs.png')

    # ---- several pairs, exclusion and Redo
    r = await page.ev('''(async () => { const rep = await __fyx.open('Students', 'fitybyx', { y: ['height (cm)', 'sex'], x: ['age', 'weight (kg)'] }, {});
      return { title: rep.title, pairs: __fyx.heads(rep).filter(h => / By /.test(h)), errors: __fyx.errors(rep) }; })()''')
    check('several pairs: Fit Y by X', r['title'], 'Fit Y by X')
    check('every Y with every X, the analysis by type', r['pairs'], ['Oneway Analysis of height (cm) By age', 'Bivariate Fit of height (cm) By weight (kg)', 'Contingency Analysis of sex By age', 'Logistic Fit of sex By weight (kg)'])
    check('several pairs: no errors', r['errors'], [])
    r = await page.ev('''(async () => { const rep = await __fyx.open('Students', 'fitybyx', { y: ['weight (kg)'], x: ['height (cm)'] }, {});
      await __fyx.pick(rep.title, ['Fit Line'], rep);
      const t = rep.table; t.setState([0, 1, 2, 3], 'excluded', true); const stale = !rep.staleEl.hidden;
      rep.run(); await new Promise(res => rep.on('done', res)); const sof = __fyx.tableUnder('Summary of Fit', 0, rep);
      t.setState([0, 1, 2, 3], 'excluded', false); return { stale, n: __fyx.num(sof[4][1]) }; })()''')
    check('an exclusion makes the report stale', r['stale'], True)
    check('Redo fits the included rows', r['n'], 56)

    # ---- a project keeps the options: the columns get new ids, the report finds its options again
    r = await page.ev('''(async () => {
      const t = __fyx.table('Students'); const y = t.col('weight (kg)').id, x = t.col('height (cm)').id;
      const o = {}; o[y + '~' + x + '|fits'] = [{ id: 'f1', kind: 'line', cfit: true }]; o[y + '~' + x + '|groupBy'] = t.col('sex').id; o[y + '~' + x + '|summary'] = true;
      const rep = await __fyx.open('Students', 'fitybyx', { y: ['weight (kg)'], x: ['height (cm)'] }, o);
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      const n0 = SM.app.reports.length;
      SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const rep2 = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep2.on('done', res));
      const newIds = rep2.spec.roles.y[0] !== y;
      return { added: SM.app.reports.length - n0, newIds, heads: __fyx.heads(rep2).filter(h => h.startsWith('Linear Fit') || h === 'Summary Statistics'), errors: __fyx.errors(rep2) };
    })()''')
    check('a loaded project opens the report', r['added'], 1)
    check('its columns have new ids', r['newIds'], True)
    check('and it keeps the fits, Group By and Summary Statistics', r['heads'], ['Summary Statistics', 'Linear Fit sex==F', 'Linear Fit sex==M'])
    check('the loaded report has no errors', r['errors'], [])

    # ---- (i) topics, the Help links, the script
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    r = await page.ev('SM.app.reports.find(r => r.title === "Oneway Analysis of yield (g) By fertilizer").pythonScript()')
    check('the Python script holds the code of the results', all(s in r for s in ('anova_lm', 'pairwise_tukeyhsd', 'stats.kruskal', 'anova_oneway')), True)

    # ---- dark theme, phone width
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.title === 'Oneway Analysis of yield (g) By fertilizer')))")
    await asyncio.sleep(1.5)
    await shot(page, '06-dark-oneway.png')
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.title === 'Contingency Analysis of response By treatment')))")
    await asyncio.sleep(1.2)
    await shot(page, '07-dark-contingency.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    check('no horizontal page scroll at phone width (Contingency)', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.title === 'Bivariate Fit of weight (kg) By height (cm)')))")
    await asyncio.sleep(0.8)
    check('no horizontal page scroll at phone width (Bivariate)', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    # redo the report at phone width: its graphs take the width there is
    r = await page.ev('''(async () => { const rep = SM.app.reports.find(r => r.title === 'Bivariate Fit of weight (kg) By height (cm)'); rep.run(); await new Promise(res => rep.on('done', res)); await __fyx.sleep(500);
      const bw = rep.body.clientWidth; return { bw, widths: rep.plots.map(p => p.width), scroll: document.documentElement.scrollWidth <= innerWidth + 1 }; })()''')
    check('at phone width the graphs fit the report', all(w <= r['bw'] for w in r['widths']), True)
    check('and the page does not scroll sideways', r['scroll'], True)
    await shot(page, '08-phone.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")

    # ---- a large table stays quick
    t0 = time.time()
    r = await page.ev('''(async () => {
      const g = SM.util.rng('fitybyx-large'); const n = 60000; const x = [], y = [], k = [], c = [];
      for (let i = 0; i < n; i++) { const xi = g.normal(50, 10); x.push(xi); y.push(2 + 0.5 * xi + g.normal(0, 4)); k.push('ABCDE'[i % 5]); c.push(g.u() < 1 / (1 + Math.exp(-(xi - 50) / 5)) ? 'yes' : 'no'); }
      const t = new SM.Table({ name: 'Large', columns: [{ name: 'x', values: x }, { name: 'y', values: y }, { name: 'k', dataType: 'character', values: k }, { name: 'c', dataType: 'character', values: c }] });
      SM.app.addTable(t);
      const start = performance.now();
      const ys = t.col('y').id, xs = t.col('x').id, ks = t.col('k').id, cs = t.col('c').id;
      const o1 = {}; o1[ys + '~' + xs + '|fits'] = [{ id: 'f1', kind: 'line', cfit: true }, { id: 'f2', kind: 'lowess' }];
      const r1 = await __fyx.open('Large', 'fitybyx', { y: ['y'], x: ['x'] }, o1);
      const o2 = {}; o2[ys + '~' + ks + '|anova'] = true; o2[ys + '~' + ks + '|compare'] = [{ method: 'tukey', control: null }]; o2[ys + '~' + ks + '|np'] = ['wilcoxon'];
      const r2 = await __fyx.open('Large', 'fitybyx', { y: ['y'], x: ['k'] }, o2);
      const r3 = await __fyx.open('Large', 'fitybyx', { y: ['c'], x: ['x'] }, {});
      const r4 = await __fyx.open('Large', 'fitybyx', { y: ['c'], x: ['k'] }, {});
      return { ms: performance.now() - start, errors: [r1, r2, r3, r4].flatMap(r => __fyx.errors(r)), n: __fyx.num(__fyx.tableUnder('Summary of Fit', 0, r1)[4][1]) };
    })()''', timeout=600)
    check('60 000 rows: four analyses without errors', r['errors'], [])
    check('60 000 rows: all rows used', r['n'], 60000)
    check('60 000 rows: done within 90 s', r['ms'] < 90000, True)
    print(f'   (the four large analyses took {r["ms"] / 1000:.1f} s; this test ran {time.time() - t0:.1f} s for them)')
    await shot(page, '09-large.png')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
