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
the tests beyond JMP (Brunner-Munzel, Compare Rates, the Two Sample Test
for Proportions, Breslow-Day, Cochran's Q and McNemar) agree with the same
numbers computed in the page and keep their options in By and projects;
the reports draw in the dark theme and at phone width; a 60 000-row table
stays quick. The effect sizes (η², ε², ω², d, g, d*, d_z) agree with the
same numbers computed in the page and with Bootstrap reruns, the Bayes
factors with the backend, Games-Howell with its formulas; they are kept by
By and projects.

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
from test_charts import GRAPHS_JS, close, find_line, lines_labelled, maxdiff, points_of, run_graph

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
  // scroll an outline of the report open last to the top of its view (for a screenshot)
  async scrollTo(title, rep) { const h = this.head(title, rep); if (h) h.scrollIntoView({ block: 'start' }); await this.sleep(400); return !!h; },
};
'''

# The (i) of a launch dialog, of a form and of an outline: open it, read the
# sections of its panel ([{heading, choices: [[name, text]]}]), close it.
HELP_JS = r'''
window.__hlp = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  async read(btn) {
    if (!btn) return null;
    btn.click();
    await this.sleep(120);
    const p = document.querySelector('.info-panel');
    if (!p) return null;
    const secs = [];
    let cur = null;
    for (const node of p.querySelector('.info-panel-body').children) {
      if (node.tagName === 'H3') { cur = { heading: node.textContent, choices: [] }; secs.push(cur); }
      else if (node.matches('dl.info-choices')) {
        if (!cur) { cur = { heading: '', choices: [] }; secs.push(cur); }
        node.querySelectorAll(':scope > dt').forEach((dt) => cur.choices.push([dt.textContent, dt.nextElementSibling ? dt.nextElementSibling.textContent : '']));
      }
    }
    const out = { title: p.querySelector('.info-panel-title').textContent, secs };
    KvotInfo.close();
    await this.sleep(30);
    return out;
  },
  // a launch dialog: KvotInfo.audit() while it is open, its (i), the platform's roles and options
  async launch(id) {
    SM.app.launch(id);
    await this.sleep(300);
    const dlg = [...document.querySelectorAll('.sm-launch-dialog')].pop();
    if (!dlg) return { error: `no launch dialog for ${id}` };
    const noTopic = KvotInfo.audit().noTopic;
    const info = await this.read(dlg.querySelector('.sm-dialog-head .info-btn'));
    dlg.querySelector('.sm-dialog-x').click();
    const L = SM.platforms.get(id).launch;
    return { noTopic, info, roles: L.roles.map((r) => r.label), options: (L.options || []).map((o) => o.label) };
  },
  // the dialog run() opens: its field labels, the audit while it is open, its (i)
  async dialog(run) {
    const n0 = SM.ui.dialogs.length;
    run();
    let d = null;
    for (let i = 0; i < 80 && !d; i++) { await this.sleep(50); if (SM.ui.dialogs.length > n0) d = SM.ui.dialogs[SM.ui.dialogs.length - 1].el; }
    if (!d) return { error: 'no dialog opened' };
    await this.sleep(100);
    const labels = [...d.querySelectorAll('.sm-form label')].map((l) => l.textContent);
    const noTopic = KvotInfo.audit().noTopic;
    const info = await this.read(d.querySelector('.sm-dialog-head .info-btn'));
    d.querySelector('.sm-dialog-x').click();
    await this.sleep(60);
    return { labels, noTopic, info };
  },
  head(rep, title) { return [...rep.body.querySelectorAll('.sm-ob-head')].find((x) => x.querySelector('h2, h3, h4').textContent === title); },
  // a red-triangle item of an outline that opens a form, by the labels of its path
  async form(rep, title, path) {
    const h = this.head(rep, title);
    if (!h) return { error: `no outline ${title}` };
    return this.dialog(() => {
      h.querySelector('.sm-ob-menu').click();
      for (const label of path) {
        const menus = document.querySelectorAll('.sm-menu');
        const b = [...menus[menus.length - 1].querySelectorAll('button')].find((x) => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === label);
        if (!b) { SM.ui.closeMenus(0); throw new Error(`no menu item ${label}`); }
        b.click();
      }
    });
  },
  async outline(rep, title) {
    const h = this.head(rep, title);
    if (!h) return { error: `no outline ${title}` };
    return this.read(h.querySelector('.info-btn'));
  },
};
'''


def section(info, heading):
    """The choices of the last section of an (i) panel with this heading."""
    secs = [s for s in (info or {}).get('secs', []) if s['heading'] == heading]
    return secs[-1]['choices'] if secs else []


def check_launch(r, name):
    check(f'{name} launch dialog: every (i) has a topic while it is open', r.get('noTopic'), [])
    roles = section(r.get('info'), 'Roles')
    check(f'{name} launch (i): the Roles list every role', [n for n, _ in roles], r.get('roles'))
    check(f'{name} launch (i): each role says what it is for before what it takes', [n for n, t in roles if t.startswith('(') or len(t) < 60], [])
    opts = section(r.get('info'), 'Options')
    check(f'{name} launch (i): the Options list every option, each with its help', ([n for n, _ in opts], [n for n, t in opts if len(t) < 40]), (r.get('options'), []))


def check_form(r, name, title=None):
    """A form's (i) explains every field, under its label (or under the name,
    helpLabel, that stands for fields repeated per item)."""
    check(f'{name}: the form opens, every (i) has a topic while it is open', (r.get('error'), r.get('noTopic')), (None, []))
    fields = section(r.get('info'), 'Fields')
    names = [n for n, _ in fields]
    missing = [lab for lab in r.get('labels') or [] if lab not in names and not any(n.lower() in lab.lower() for n in names)]
    check(f'{name}: its (i) explains every field', (bool(names), missing), (True, []))
    check(f'{name}: ... each with what it is for', [n for n, t in fields if len(t) < 30], [])
    if title:
        check(f'{name}: the (i) builds on the topic {title}', (r.get('info') or {}).get('title'), title)


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

    # ---- beyond JMP: Brunner-Munzel, Compare Rates (Oneway of the adverse event counts) ----------------
    r = await page.ev('''(async () => { const rep = await __fyx.open('Clinical study', 'fitybyx', { y: ['adverse events'], x: ['treatment'] }, {});
      await __fyx.pick(rep.title, ['Nonparametric', 'Brunner-Munzel Test'], rep);
      const t = rep.table; const y = t.col('adverse events').values, x = t.col('treatment').values;
      const a = y.filter((v, i) => x[i] === 'drug'), b = y.filter((v, i) => x[i] === 'placebo');
      let s = 0; for (const u of a) for (const v of b) s += u > v ? 1 : (u === v ? 0.5 : 0);
      const tb = __fyx.tableUnder('Brunner-Munzel Test (Probability of Superiority)', 0, rep);
      return { title: rep.title, row: tb[1], head: tb[0], want: s / (a.length * b.length), errors: __fyx.errors(rep) }; })()''')
    check('a count Y by treatment is a Oneway', r['title'], 'Oneway Analysis of adverse events By treatment')
    check('Brunner-Munzel: drug against placebo', r['row'][:2], ['drug', 'placebo'])
    check.near('P(drug > placebo) + ½P(=) = the pairs counted in the page', float(r['row'][2]), r['want'], 1e-6)
    check('Brunner-Munzel columns', r['head'], ['Level', 'vs Level', 'P(Level>vs Level)', 'Std Err', 'Lower 95%', 'Upper 95%', 'Brunner-Munzel t', 'DF', 'Prob>|t|'])
    check('no errors (Brunner-Munzel)', r['errors'], [])
    ow2 = 'Oneway Analysis of adverse events By treatment'
    r = await page.ev(f'''(async () => {{
      const p = __fyx.pick({json.dumps(ow2)}, ['Equivalence Test', 'Probability of Superiority…']);
      await __fyx.dialogOK((d) => {{ const i = d.querySelectorAll('input'); i[0].value = '0.3'; i[1].value = '0.7'; }});
      await p;
      const tb = __fyx.tableUnder('Equivalence Test (Probability of Superiority)', 1);
      const bm = __fyx.tableUnder('Brunner-Munzel Test (Probability of Superiority)', 0);
      return {{ has: __fyx.heads().includes('Equivalence Test (Probability of Superiority)'), p: tb ? tb[1][2] : null, prob: bm[1][2], opt: Object.entries(__fyx.rep().spec.options).find(([k]) => k.endsWith('|bmTost'))[1] }};
    }})()''')
    check('Equivalence Test ▸ Probability of Superiority: the dialog sets the bounds', (r['has'], r['opt']), (True, {'low': 0.3, 'upp': 0.7}))
    check('the equivalence table shows the same P', r['p'], r['prob'])
    r = await page.ev(f'''(async () => {{
      const p = __fyx.pick({json.dumps(ow2)}, ['Compare Rates…']);
      await __fyx.dialogOK((d) => {{ const s = d.querySelector('select'); s.value = [...s.options].find(o => o.textContent === 'months').value; }});
      await p;
      const rep = __fyx.rep(); const t = rep.table; const y = t.col('adverse events').values, x = t.col('treatment').values, m = t.col('months').values;
      const tot = (lv, v) => v.reduce((acc, z, i) => acc + (x[i] === lv ? z : 0), 0);
      const rates = ['placebo', 'drug'].map(lv => tot(lv, y) / tot(lv, m));
      const tb = __fyx.head('Compare Rates').parentElement.querySelector(':scope > .sm-ob-body table.sm-rt');
      const rows = [...tb.querySelectorAll('tbody tr')].map(tr => [...tr.children].map(c => c.textContent));
      const rr = __fyx.tableUnder('Rate Ratios'); const lr = __fyx.tableUnder('Likelihood Ratio Test');
      return {{ rows, rates, ratio: rr[1], lr: lr[1], heads: __fyx.heads().filter(h => /Rate|Likelihood/.test(h)), errors: __fyx.errors() }};
    }})()''')
    check('Compare Rates: its outlines', r['heads'], ['Compare Rates', 'Rate Ratios', 'Likelihood Ratio Test'])
    check.near('the placebo rate = its events over its months, computed here', float(r['rows'][0][4]), r['rates'][0], 1e-6)
    check.near('the drug rate', float(r['rows'][1][4]), r['rates'][1], 1e-6)
    check('the ratio is drug / placebo', r['ratio'][:2], ['drug', 'placebo'])
    check.near('the rate ratio = the ratio of the rates', float(r['ratio'][2]), r['rates'][1] / r['rates'][0], 1e-6)
    check('the likelihood-ratio test of the treatment, 1 DF', r['lr'][:2], ['treatment', '1'])
    check('no errors (Compare Rates)', r['errors'], [])
    r = await page.ev('''(async () => { const rep = SM.app.reports.find(r => r.title === 'Oneway Analysis of yield (g) By fertilizer');
      const ctx = new SM.report.Ctx(rep, { rows: rep.table.includedRows() }, rep.content, '');
      const it = rep.platform.triangle(ctx).find(i => i.label === 'Compare Rates…'); return it ? it.disabled : 'missing'; })()''')
    check('Compare Rates is for counts: not for a yield in grams', r, True)
    await page.ev("__fyx.scrollTo('Brunner-Munzel Test (Probability of Superiority)')")
    await shot(page, '10-brunner.png')
    await page.ev("__fyx.scrollTo('Compare Rates')")
    await shot(page, '10-rates.png')

    # ---- beyond JMP: the Two Sample Test for Proportions, Breslow-Day -------------------------------------
    r = await page.ev('''(async () => { const t = __fyx.table('Clinical study'); const o = {};
      const y = t.col('response').id, x = t.col('treatment').id; o[y + '~' + x + '|cmh'] = t.col('sex').id;
      const rep = await __fyx.open('Clinical study', 'fitybyx', { y: ['response'], x: ['treatment'] }, o);
      await __fyx.pick(rep.title, ['Two Sample Test for Proportions'], rep);
      const X = t.col('treatment').values, Y = t.col('response').values;
      const c = (xl, yl) => X.filter((v, i) => v === xl && (yl == null || Y[i] === yl)).length;
      const c1 = c('placebo', 'no'), n1 = c('placebo'), c2 = c('drug', 'no'), n2 = c('drug');
      const p1 = (c1 + 1) / (n1 + 2), p2 = (c2 + 1) / (n2 + 2), z = SM.util.qnorm(0.975), se = Math.sqrt(p1 * (1 - p1) / (n1 + 2) + p2 * (1 - p2) / (n2 + 2));
      const tp = __fyx.tableUnder('Two Sample Test for Proportions', 2);
      const ac = tp.find(r => r[0].startsWith('Agresti-Caffo'));
      const kv = __fyx.tableUnder('Two Sample Test for Proportions', 0);
      const cmh = __fyx.tableUnder('Cochran Mantel Haenszel', 0); const bs = __fyx.tableUnder('Odds Ratios by Stratum', 0);
      const S = t.col('sex').values; const cs = (xl, yl) => X.filter((v, i) => v === xl && Y[i] === yl && S[i] === 'F').length;
      const orF = (cs('placebo', 'no') * cs('drug', 'yes')) / (cs('placebo', 'yes') * cs('drug', 'no'));
      return { desc: kv[0][1], diff: kv[3][1], want: c1 / n1 - c2 / n2, lo: ac[1], hi: ac[2], wantLo: p1 - p2 - z * se, wantHi: p1 - p2 + z * se,
        methods: tp.slice(1).map(r => r[0]), tests: cmh.slice(1).map(r => r[0]), orF: bs[1][2], wantOrF: orF, errors: __fyx.errors(rep) }; })()''')
    check('Two Sample Test for Proportions: the description', r['desc'], 'P(no|placebo) − P(no|drug)')
    check.near('the proportion difference computed here', float(r['diff']), r['want'], 1e-6)
    check.near('the adjusted Wald (Agresti-Caffo) lower limit computed here', float(r['lo'].replace('−', '-')), r['wantLo'], 1e-6)
    check.near('and its upper limit', float(r['hi']), r['wantHi'], 1e-6)
    check('every method statsmodels has for a difference', r['methods'], ['Wald', 'Agresti-Caffo (adjusted Wald, as JMP)', 'Newcombe (hybrid score)', 'Miettinen-Nurminen (score)'])
    check('Breslow-Day beside the Cochran Mantel Haenszel test', r['tests'], ['Cochran Mantel Haenszel (odds ratio is 1)', 'Cochran Mantel Haenszel, continuity corrected', 'Breslow-Day (odds ratios are equal)', 'Breslow-Day-Tarone (odds ratios are equal)'])
    check.near('the odds ratio of the women (ad/bc) computed here', float(r['orF']), r['wantOrF'], 1e-6)
    check('no errors (two proportions, strata)', r['errors'], [])
    r = await page.ev('''(async () => { const rep = __fyx.rep(); await __fyx.pick('Two Sample Test for Proportions', ['Odds Ratio'], rep);
      const t = rep.table; const X = t.col('treatment').values, Y = t.col('response').values;
      const c = (xl, yl) => X.filter((v, i) => v === xl && Y[i] === yl).length;
      const want = (c('placebo', 'no') / c('placebo', 'yes')) / (c('drug', 'no') / c('drug', 'yes'));
      const kv = __fyx.tableUnder('Two Sample Test for Proportions', 0); const tp = __fyx.tableUnder('Two Sample Test for Proportions', 1);
      return { desc: kv[0][1], or: kv[3][1], want, methods: tp.slice(1).map(r => r[0]) }; })()''')
    check('the Odds Ratio item: the description', r['desc'], 'Odds(no|placebo) / Odds(no|drug)')
    check.near('the odds ratio computed here', float(r['or']), r['want'], 1e-6)
    check('the odds-ratio methods', r['methods'], ['Woolf (logit)', 'Gart (adjusted logit, 0.5 added)', 'Independence-smoothed logit', 'Miettinen-Nurminen (score)'])
    await page.ev("__fyx.scrollTo('Cochran Mantel Haenszel')")
    await shot(page, '11-two-proportions.png')

    # ---- beyond JMP: Matched Pairs of binary responses, Cochran's Q and McNemar ---------------------------
    await page.ev(r'''(() => {
      const r = SM.util.rng('smui-binary-pairs'); const n = 80; const c = { t1: [], t2: [], t3: [], u: [], v: [] };
      for (let i = 0; i < n; i++) { const p = r.u(); c.t1.push(r.u() < 0.3 + 0.4 * p ? 'yes' : 'no'); c.t2.push(r.u() < 0.45 + 0.4 * p ? 'yes' : 'no'); c.t3.push(r.u() < 0.6 + 0.3 * p ? 'yes' : 'no'); c.u.push(r.u() < 0.5 ? 1 : 0); c.v.push(r.u() < 0.6 ? 1 : 0); }
      c.t2[5] = null;
      SM.app.addTable(new SM.Table({ name: 'Ratings', source: 'simulated', columns: [{ name: 't1', dataType: 'character', values: c.t1 }, { name: 't2', dataType: 'character', values: c.t2 }, { name: 't3', dataType: 'character', values: c.t3 }, { name: 'u', dataType: 'numeric', values: c.u }, { name: 'v', dataType: 'numeric', values: c.v }] }));
    })()''')
    r = await page.ev('''(async () => { const rep = await __fyx.open('Ratings', 'matchedpairs', { y: ['t1', 't2', 't3'] }, {});
      const t = rep.table; const cols = ['t1', 't2', 't3'].map(n => t.col(n).values);
      const rows = []; for (let i = 0; i < t.nrows; i++) if (cols.every(v => v[i] != null)) rows.push(cols.map(v => (v[i] === 'yes' ? 1 : 0)));
      const k = 3, C = [0, 1, 2].map(j => rows.reduce((a, r) => a + r[j], 0)), R = rows.map(r => r[0] + r[1] + r[2]), N = R.reduce((a, b) => a + b, 0);
      const q = (k - 1) * (k * C.reduce((a, c) => a + c * c, 0) - N * N) / (k * N - R.reduce((a, r) => a + r * r, 0));
      let b = 0, c2 = 0; for (let i = 0; i < t.nrows; i++) { if (cols[0][i] == null || cols[2][i] == null) continue; if (cols[0][i] === 'yes' && cols[2][i] === 'no') b++; if (cols[0][i] === 'no' && cols[2][i] === 'yes') c2++; }
      const kv = __fyx.tableUnder("Cochran's Q Test", 1); const mc = __fyx.tableUnder('McNemar Tests', 0);
      const p13 = mc.find(r => r[0] === 't1' && r[1] === 't3');
      return { title: rep.title, heads: __fyx.heads(rep), q: kv[0][1], wantQ: q, n: kv[3][1], wantN: rows.length, chi: p13[8], wantChi: (b - c2) ** 2 / (b + c2), bc: [p13[3], p13[4]], wantBc: [String(b), String(c2)], head: mc[0], errors: __fyx.errors(rep) }; })()''')
    check('binary responses: Cochran\'s Q and McNemar, no paired t tests', [h for h in r['heads'] if h.startswith(('Cochran', 'McNemar', 'Difference'))], ["Cochran's Q Test", 'McNemar Tests'])
    check.near('Cochran\'s Q by its formula in the page', float(r['q']), r['wantQ'], 1e-6)
    check('on the rows with every response', r['n'], str(r['wantN']))
    check('McNemar t1-t3: the discordant counts', r['bc'], r['wantBc'])
    check.near('McNemar χ² = (b − c)²/(b + c) computed here', float(r['chi']), r['wantChi'], 1e-6)
    check('the exact test is on by default', r['head'][-1], 'Exact Prob')
    check('no errors (binary Matched Pairs)', r['errors'], [])
    r = await page.ev('''(async () => { await __fyx.pick('McNemar Tests', ['Continuity Correction']);
      const mc = __fyx.tableUnder('McNemar Tests', 0); const p13 = mc.find(r => r[0] === 't1' && r[1] === 't3'); const b = +p13[3], c = +p13[4];
      return { chi: p13[8], want: (Math.abs(b - c) - 1) ** 2 / (b + c) }; })()''')
    check.near('Continuity Correction: (|b − c| − 1)²/(b + c)', float(r['chi']), r['want'], 1e-6)
    q_yes = await page.ev('''__fyx.tableUnder("Cochran's Q Test", 1)[0][1]''')
    r = await page.ev('''(async () => { await __fyx.pick("Cochran's Q Test", ['Success Level', 'no']); const tb = __fyx.tableUnder("Cochran's Q Test", 0); const kv = __fyx.tableUnder("Cochran's Q Test", 1);
      return { head: tb[0][2], q: kv[0][1] }; })()''')
    check('Success Level no: the counts of no, the same Q', (r['head'], r['q']), ('Count no', q_yes))
    r = await page.ev('''(async () => { const rep = await __fyx.open('Ratings', 'matchedpairs', { y: ['u', 'v'] }, {});
      const P = SM.platforms.get('matchedpairs'); const t = rep.table;
      const bad = P.launch.validate({ roles: { y: [t.col('t1').id, t.col('u').id] } }, t);
      const tStud = __fyx.table('Students'); const bad2 = P.launch.validate({ roles: { y: [tStud.col('sex').id, tStud.col('age').id] } }, tStud);
      return { heads: __fyx.heads(rep).filter(h => /Cochran|McNemar|Difference/.test(h)), bad, bad2, errors: __fyx.errors(rep) }; })()''')
    check('0/1 numeric responses: the binary tests and the paired t test', r['heads'], ["Cochran's Q Test", 'McNemar Tests', 'Difference: v-u'])
    check('yes/no with 0/1 is three values: refused at launch', isinstance(r['bad'], str) and 'binary' in r['bad'], True)
    check('an ordinal age is not binary: refused at launch', isinstance(r['bad2'], str), True)
    check('no errors (0/1 Matched Pairs)', r['errors'], [])
    await asyncio.sleep(0.3)
    await shot(page, '12-binary-pairs.png')

    # ---- the new options with By, and kept by a project (their column ids change on loading)
    r = await page.ev('''(async () => { const t = __fyx.table('Clinical study'); const y = t.col('adverse events').id, x = t.col('treatment').id, m = t.col('months').id;
      const o = {}; o[y + '~' + x + '|bm'] = true; o[y + '~' + x + '|rates'] = { exposure: m, compare: 'diff', method: 'wald', ci: 'wald', control: null };
      const rep = await __fyx.open('Clinical study', 'fitybyx', { y: ['adverse events'], x: ['treatment'], by: ['sex'] }, o);
      const hs = __fyx.heads(rep);
      const tr = t.col('response').id; const o2 = {}; o2[tr + '~' + x + '|twoProp'] = true;
      const rep2 = await __fyx.open('Clinical study', 'fitybyx', { y: ['response'], x: ['treatment'], by: ['sex'] }, o2);
      const rep3 = await __fyx.open('Ratings', 'matchedpairs', { y: ['t1', 't2', 't3'], by: ['u'] }, {});
      return { rates: hs.filter(h => h === 'Compare Rates').length, bm: hs.filter(h => h.startsWith('Brunner')).length, diffs: hs.filter(h => h === 'Rate Differences').length,
        tp: __fyx.heads(rep2).filter(h => h === 'Two Sample Test for Proportions').length, q: __fyx.heads(rep3).filter(h => h === "Cochran's Q Test").length,
        errors: [rep, rep2, rep3].flatMap(r => __fyx.errors(r)) }; })()''')
    check('By: Brunner-Munzel and Compare Rates (a difference) in each group', (r['bm'], r['rates'], r['diffs']), (2, 2, 2))
    check('By: the Two Sample Test and Cochran\'s Q in each group', (r['tp'], r['q']), (2, 2))
    check('By: no errors', r['errors'], [])
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.title === 'Oneway Analysis of adverse events By treatment' && !r.spec.roles.by);
      const t = rep.table; const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const rep2 = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep2.on('done', res));
      const h = __fyx.head('Compare Rates', rep2); const tb = h ? h.parentElement.querySelector(':scope > .sm-ob-body table.sm-rt') : null;
      const out = { newTable: rep2.table !== t, heads: __fyx.heads(rep2).filter(h => /Brunner|Equivalence|Compare Rates/.test(h)), exposure: tb ? tb.querySelectorAll('thead th')[3].textContent : null, errors: __fyx.errors(rep2) };
      const t2 = rep2.table; SM.app.closeReport(rep2); SM.app.closeTable(t2);   // no report left: no dialog
      return out; })()''')
    check('a project keeps Brunner-Munzel, its equivalence test and Compare Rates', (r['newTable'], r['heads']), (True, ['Brunner-Munzel Test (Probability of Superiority)', 'Equivalence Test (Probability of Superiority)', 'Compare Rates']))
    check('and the exposure column of Compare Rates', r['exposure'], 'Total months')
    check('the loaded report has no errors (new options)', r['errors'], [])

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

    # ---- round 5: Effect Size, Bayes Factor, Games-Howell (not in JMP) ---------------------------
    await page.ev(r'''(() => {
      // every table under every outline of a title, in the order of the report
      __fyx.tablesUnder = (title, rep) => [...(rep || __fyx.rep()).body.querySelectorAll('.sm-ob-head')].filter((h) => h.querySelector('h2, h3, h4').textContent === title)
        .map((h) => [...h.parentElement.querySelector(':scope > .sm-ob-body').querySelectorAll(':scope > table.sm-rt, :scope > .sm-ob-row table')].map((t) => [...t.querySelectorAll('tr')].map((tr) => [...tr.children].map((c) => c.textContent.trim()))));
      // η² of y by g from the rows given (the ANOVA's sums of squares)
      __fyx.eta2 = (t, yName, xName, rows) => { const g = __fyx.groups(t, yName, xName, rows); const all = g.flat(); const m = all.reduce((a, b) => a + b, 0) / all.length;
        let ssb = 0, sst = 0; for (const v of g) { const gm = v.reduce((a, b) => a + b, 0) / v.length; ssb += v.length * (gm - m) ** 2; } for (const v of all) sst += (v - m) ** 2; return ssb / sst; };
      __fyx.meanVar = (v) => { const m = v.reduce((a, b) => a + b, 0) / v.length; return [m, v.reduce((a, b) => a + (b - m) ** 2, 0) / (v.length - 1), v.length]; };
    })()''')
    r = await page.ev('''(async () => {
      const rep = await __fyx.open('Plant trial', 'fitybyx', { y: ['yield (g)'], x: ['fertilizer'] }, {});
      await __fyx.pick(rep.title, ['Effect Size'], rep);
      const t = rep.table;
      return { heads: __fyx.heads(rep), aov: __fyx.tableUnder('Analysis of Variance', 0, rep), es: __fyx.tableUnder('Effect Size', 0, rep), want: __fyx.eta2(t, 'yield (g)', 'fertilizer'),
        info: !!__fyx.head('Effect Size', rep).querySelector('.info-btn'), errors: __fyx.errors(rep) };
    })()''')
    check('Effect Size on its own turns Means/Anova on, and sits under the Analysis of Variance', [h for h in r['heads'] if h in ('Oneway Anova', 'Analysis of Variance', 'Effect Size', 'Means for Oneway Anova')], ['Oneway Anova', 'Analysis of Variance', 'Effect Size', 'Means for Oneway Anova'])
    num = lambda s: float(str(s).replace('−', '-'))
    ss_x, df_x, ss_e, df_e = num(r['aov'][1][2]), num(r['aov'][1][1]), num(r['aov'][2][2]), num(r['aov'][2][1])
    ms_e = ss_e / df_e
    es = {row[0]: row for row in r['es'][1:]}
    check('η², ε², ω² with their interval', (r['es'][0], list(es)), (['Effect Size', 'Estimate', 'Lower 95%', 'Upper 95%', 'Interval'], ['η² (eta²)', 'ε² (epsilon²)', 'ω² (omega²)']))
    check.near('η² = SS(X)/SS(total) from the Analysis of Variance shown', num(es['η² (eta²)'][1]), ss_x / (ss_x + ss_e), 1e-5)
    check.near('η² = the sums of squares computed in the page', num(es['η² (eta²)'][1]), r['want'], 1e-5)
    check.near('ε² = (SS(X) − df·MSE)/SS(total)', num(es['ε² (epsilon²)'][1]), (ss_x - df_x * ms_e) / (ss_x + ss_e), 1e-5)
    check.near('ω² = (SS(X) − df·MSE)/(SS(total) + MSE)', num(es['ω² (omega²)'][1]), (ss_x - df_x * ms_e) / (ss_x + ss_e + ms_e), 1e-5)
    check('one interval, of the population proportion, for the three', len({(v[2], v[3]) for v in es.values()}), 1)
    check('the Effect Size outline has an (i)', r['info'], True)
    check('no errors (Effect Size)', r['errors'], [])
    # Games-Howell
    r = await page.ev('''(async () => {
      const rep = __fyx.rep(); await __fyx.pick(rep.title, ['Compare Means', 'All Pairs, Games-Howell'], rep);
      const t = rep.table; const g = __fyx.groups(t, 'yield (g)', 'fertilizer').map(__fyx.meanVar);
      const od = __fyx.tableUnder('Ordered Differences Report', 0, rep); const hs = __fyx.heads(rep);
      const circles = rep.plots[0].traces.filter((tr) => tr.xaxis === 'x2').length;
      return { hs: hs.filter((h) => /Games-Howell|Letters|Ordered/.test(h)), od, g, circles, lv: t.levels(t.col('fertilizer')), errors: __fyx.errors(rep) };
    })()''')
    check('Games-Howell outlines', r['hs'], ['Comparisons for all pairs using Games-Howell', 'Games-Howell Threshold Matrix', 'Connecting Letters Report', 'Ordered Differences Report'])
    check('its Ordered Differences Report has each pair\'s DF', r['od'][0], ['Level', '- Level', 'Difference', 'Std Err Dif', 'DF', 'Lower CL', 'Upper CL', 'p-Value'])
    row0 = r['od'][1]
    ia, ib = r['lv'].index(row0[0]), r['lv'].index(row0[1])
    (ma, va, na), (mb, vb, nb) = r['g'][ia], r['g'][ib]
    check.near('Games-Howell: the difference computed in the page', num(row0[2]), ma - mb, 1e-6)
    check.near('Games-Howell: its SE √(s²ᵢ/nᵢ + s²ⱼ/nⱼ) computed in the page', num(row0[3]), (va / na + vb / nb) ** 0.5, 1e-6)
    check.near('Games-Howell: its Welch-Satterthwaite DF', num(row0[4]), (va / na + vb / nb) ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)), 1e-6)
    check('no comparison circles for Games-Howell (each pair has its own quantile)', r['circles'], 0)
    check('no errors (Games-Howell)', r['errors'], [])
    # Bootstrap reruns the report headless: an effect size of resampled rows
    r = await page.ev('''(async () => {
      const rep = __fyx.rep(); const h = __fyx.head('Effect Size', rep);
      const tbl = h.parentElement.querySelector(':scope > .sm-ob-body table.sm-rt');
      const t = await SM.bootstrap.run(tbl, tbl._rt.columns.find((c) => c.label === 'Estimate'), { B: 6, seed: 5, show: false });
      const rows = SM.bootstrap.sampler(rep.groups()[0].rows, 5)();
      const n0 = SM.app.tables.length;
      return { cols: t.columns.map((c) => c.name), v1: t.col('η² (eta²) noncentral F').values[1], want: __fyx.eta2(rep.table, 'yield (g)', 'fertilizer', rows), same: __fyx.heads(rep).includes('Effect Size'), errors: __fyx.errors(rep) };
    })()''', timeout=300)
    check('Bootstrap of the Effect Size table: a column per estimate (named by its text columns)', r['cols'], ['BootID', 'η² (eta²) noncentral F', 'ε² (epsilon²) noncentral F', 'ω² (omega²) noncentral F'])
    check.near('Bootstrap: sample 1\'s η² = η² of the rows drawn, computed in the page', r['v1'], r['want'], 1e-9)
    check('Bootstrap leaves the report as it was', (r['same'], r['errors']), (True, []))

    # two levels: Cohen's d and Hedges' g of the pooled t test, d* of the unequal-variance t test, the Bayes factor
    r = await page.ev('''(async () => {
      const t = __fyx.table('Clinical study'); const y = t.col('adverse events').id, x = t.col('treatment').id;
      const o = {}; o[y + '~' + x + '|anova'] = true; o[y + '~' + x + '|ttest'] = true; o[y + '~' + x + '|effect'] = true;
      const rep = await __fyx.open('Clinical study', 'fitybyx', { y: ['adverse events'], x: ['treatment'] }, o);
      const lv = t.levels(t.col('treatment')); const vals = lv.map((l) => { const Y = t.col('adverse events').values, X = t.col('treatment').values; return Y.filter((v, i) => X[i] === l && Number.isFinite(v)); });
      return { es: __fyx.tablesUnder('Effect Size', rep), g: vals.map(__fyx.meanVar), heads: __fyx.heads(rep), errors: __fyx.errors(rep) };
    })()''')
    check('two levels: an Effect Size under the pooled t test, the ANOVA and the unequal-variance t test', len(r['es']), 3)
    (m1, v1, n1), (m2, v2, n2) = r['g']
    sp = (((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2)) ** 0.5
    pooled = {row[0]: row for row in r['es'][0][0][1:]}
    welch = {row[0]: row for row in r['es'][2][0][1:]}
    check.near("Cohen's d = (mean₂ − mean₁)/s_pooled computed in the page", num(pooled["Cohen's d"][1]), (m2 - m1) / sp, 1e-5)
    check("Hedges' g is a little smaller than d", abs(num(pooled["Hedges' g"][1])) < abs(num(pooled["Cohen's d"][1])), True)
    check.near("d* = (mean₂ − mean₁)/√((s₁² + s₂²)/2) computed in the page", num(welch["Cohen's d*"][1]), (m2 - m1) / ((v1 + v2) / 2) ** 0.5, 1e-5)
    check('the intervals: noncentral t (pooled), Bonett (unequal variances)', (pooled["Cohen's d"][4], welch["Cohen's d*"][4]), ('noncentral t', 'Bonett (2008)'))
    check('no errors (two-level effect sizes)', r['errors'], [])
    ow2 = 'Oneway Analysis of adverse events By treatment'
    r = await page.ev(f'''(async () => {{
      const rep = __fyx.rep(); const p = __fyx.pick({json.dumps(ow2)}, ['Bayes Factor…'], rep);
      await __fyx.dialogOK((d) => {{ d.querySelector('input').value = '0.5'; }});
      await p;
      const bf = __fyx.tableUnder('Bayes Factor', 0, rep); const kv = __fyx.tableUnder('Bayes Factor', 1, rep);
      const back = await SM.engine.call('fitybyx.oneway_bf', {{ y: 'adverse events', x: 'treatment', r: 0.5, rows: null }}, rep.table);
      const opt = Object.entries(rep.spec.options).find(([k]) => k.endsWith('|bf'))[1];
      return {{ bf, kv, back: back.table.rows.map((x) => x.bf10), opt, errors: __fyx.errors(rep) }};
    }})()''')
    check('Bayes Factor…: the dialog sets the prior scale', r['opt'], {'r': 0.5})
    check('the Bayes Factor table: two-sided and each one-sided alternative', ([row[0] for row in r['bf'][1:]], r['bf'][0]), (['δ ≠ 0', 'δ > 0 (drug higher)', 'δ < 0 (drug lower)'], ['Alternative', 'BF10', 'BF01']))
    for i, lab in enumerate(('two-sided', 'δ > 0', 'δ < 0')):
        check.near(f'BF10 ({lab}) = the backend with r = 0.5', num(r['bf'][i + 1][1]), r['back'][i], 1e-6)
        check.near(f'BF01 ({lab}) = 1/BF10', num(r['bf'][i + 1][2]), 1 / r['back'][i], 1e-5)
    check('its facts: the pooled t and the prior', [row[0] for row in r['kv']], ['t (pooled)', 'DF', 'N placebo', 'N drug', 'Prior scale r'])
    check('no errors (Bayes factor)', r['errors'], [])
    await page.ev("__fyx.scrollTo('Bayes Factor')")
    await shot(page, '17-bayes-factor.png')
    r = await page.ev('''(async () => { const rep = SM.app.reports.find(r => r.title === 'Oneway Analysis of yield (g) By fertilizer' && !r.spec.roles.by);
      const ctx = new SM.report.Ctx(rep, { rows: rep.table.includedRows() }, rep.content, '');
      const it = rep.platform.triangle(ctx).find(i => i.label === 'Bayes Factor…'); return it ? it.disabled : 'missing'; })()''')
    check('Bayes Factor… is for two levels: not for three', r, True)

    # Bivariate: the Bayes factor of the correlation
    r = await page.ev('''(async () => {
      const rep = await __fyx.open('Students', 'fitybyx', { y: ['weight (kg)'], x: ['height (cm)'] }, {});
      const p = __fyx.pick(rep.title, ['Bayes Factor for the Correlation…'], rep); await __fyx.dialogOK(); await p;
      const t = rep.table; const X = t.col('height (cm)').values, Y = t.col('weight (kg)').values; const n = X.length;
      const mx = X.reduce((a, b) => a + b, 0) / n, my = Y.reduce((a, b) => a + b, 0) / n;
      let sxy = 0, sxx = 0, syy = 0; for (let i = 0; i < n; i++) { sxy += (X[i] - mx) * (Y[i] - my); sxx += (X[i] - mx) ** 2; syy += (Y[i] - my) ** 2; }
      const back = await SM.engine.call('fitybyx.bivariate_bf', { y: 'weight (kg)', x: 'height (cm)', kappa: 1, rows: null }, t);
      return { bf: __fyx.tableUnder('Bayes Factor', 0, rep), kv: __fyx.tableUnder('Bayes Factor', 1, rep), r: sxy / Math.sqrt(sxx * syy), back: back.table.rows.map((x) => x.bf10), errors: __fyx.errors(rep) };
    })()''')
    kv = {row[0]: row[1] for row in r['kv']}
    check.near('the correlation r shown = Pearson r computed in the page', num(kv['Correlation r']), r['r'], 1e-6)
    check('its alternatives', [row[0] for row in r['bf'][1:]], ['ρ ≠ 0', 'ρ > 0', 'ρ < 0'])
    check.near('BF10 of the correlation = the backend', num(r['bf'][1][1]), r['back'][0], 1e-6)
    check('no errors (the correlation\'s Bayes factor)', r['errors'], [])

    # Matched Pairs: d_z, g_z, d_av and the paired Bayes factor
    r = await page.ev('''(async () => {
      const rep = await __fyx.open('Students', 'matchedpairs', { y: ['height (cm)', 'weight (kg)'] }, {});
      const title = 'Difference: weight (kg)-height (cm)';
      await __fyx.pick(title, ['Effect Size'], rep);
      const p = __fyx.pick(title, ['Bayes Factor…'], rep); await __fyx.dialogOK(); await p;
      const t = rep.table; const a = t.col('height (cm)').values, b = t.col('weight (kg)').values; const d = b.map((v, i) => v - a[i]);
      const [md, vd] = __fyx.meanVar(d);
      const back = await SM.engine.call('matchedpairs.bayes', { y1: 'height (cm)', y2: 'weight (kg)', r: Math.SQRT1_2, rows: null }, t);
      return { es: __fyx.tableUnder('Effect Size', 0, rep), bf: __fyx.tableUnder('Bayes Factor', 0, rep), dz: md / Math.sqrt(vd), back: back.table.rows.map((x) => x.bf10), heads: __fyx.heads(rep), errors: __fyx.errors(rep) };
    })()''')
    es = {row[0]: row for row in r['es'][1:]}
    check('Matched Pairs: d_z, g_z and d_av', list(es), ["Cohen's d_z", "Hedges' g_z", "Cohen's d_av"])
    check.near('d_z = mean difference/SD of the differences, computed in the page', num(es["Cohen's d_z"][1]), r['dz'], 1e-5)
    check.near('the paired BF10 = the backend', num(r['bf'][1][1]), r['back'][0], 1e-6)
    check('no errors (Matched Pairs effect size and Bayes factor)', r['errors'], [])

    # By and a project keep them
    r = await page.ev('''(async () => { const t = __fyx.table('Clinical study'); const y = t.col('adverse events').id, x = t.col('treatment').id;
      const o = {}; o[y + '~' + x + '|anova'] = true; o[y + '~' + x + '|effect'] = true; o[y + '~' + x + '|bf'] = { r: 0.707 }; o[y + '~' + x + '|compare'] = [{ method: 'gameshowell', control: null }];
      const rep = await __fyx.open('Clinical study', 'fitybyx', { y: ['adverse events'], x: ['treatment'], by: ['sex'] }, o);
      const hs = __fyx.heads(rep);
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const rep2 = SM.app.reports[SM.app.reports.length - 1]; await new Promise(res => rep2.on('done', res));
      const out = { es: hs.filter((h) => h === 'Effect Size').length, bf: hs.filter((h) => h === 'Bayes Factor').length, gh: hs.filter((h) => /Games-Howell/.test(h) && /Comparisons/.test(h)).length,
        back: __fyx.heads(rep2).filter((h) => h === 'Effect Size' || h === 'Bayes Factor' || /using Games-Howell/.test(h)).length, newTable: rep2.table !== t, errors: [rep, rep2].flatMap((x) => __fyx.errors(x)) };
      const t2 = rep2.table; SM.app.closeReport(rep2); SM.app.closeTable(t2);
      return out; })()''')
    check('By: an Effect Size (ANOVA and pooled t), a Bayes factor and Games-Howell in each group', (r['es'], r['bf'], r['gh']), (4, 2, 2))
    check('a project keeps them (its columns get new ids)', (r['newTable'], r['back']), (True, 8))
    check('no errors (By, project)', r['errors'], [])

    # ---- (i) topics, the Help links, the script
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    r = await page.ev('SM.app.reports.find(r => r.title === "Oneway Analysis of yield (g) By fertilizer").pythonScript()')
    check('the Python script holds the code of the results', all(s in r for s in ('anova_lm', 'pairwise_tukeyhsd', 'stats.kruskal', 'anova_oneway')), True)

    # ---- help for every input: the launch dialogs' (i) and the red-triangle forms' (i)
    await page.ev(HELP_JS)
    r = await page.ev('''['fitybyx', 'matchedpairs'].flatMap((id) => { const L = SM.platforms.get(id).launch;
      return [...L.roles, ...(L.options || [])].filter((f) => !f.help).map((f) => `${id}: ${f.label}`); })''')
    check('every role and option of Fit Y by X and Matched Pairs has its help', r, [])
    await page.ev("SM.app.showTab(SM.app.tabOf(__fyx.table('Students')))")
    check_launch(await page.ev("__hlp.launch('fitybyx')"), 'Fit Y by X')
    check_launch(await page.ev("__hlp.launch('matchedpairs')"), 'Matched Pairs')
    await page.ev('''(async () => { const t = __fyx.table('Students'); const sc = t.col('weight (kg)').id + '~' + t.col('height (cm)').id;
      const o = {}; o[sc + '|fits'] = [{ id: 'f1', kind: 'spline', lam: 1 }, { id: 'f2', kind: 'quantile', tau: 0.5 }];
      window.__biv = await __fyx.open('Students', 'fitybyx', { y: ['weight (kg)'], x: ['height (cm)'] }, o);
      window.__many = await __fyx.open('Students', 'fitybyx', { y: ['height (cm)', 'weight (kg)'], x: ['sex'] }, {});
      window.__mp = await __fyx.open('Students', 'matchedpairs', { y: ['height (cm)', 'weight (kg)'] }, {});
      window.__ow = await __fyx.open('Clinical study', 'fitybyx', { y: ['adverse events'], x: ['treatment'] }, {});
      window.__lg = await __fyx.open('Clinical study', 'fitybyx', { y: ['response'], x: ['dose (mg)'] }, {});
      window.__ct = await __fyx.open('Clinical study', 'fitybyx', { y: ['response'], x: ['treatment'] }, {}); })()''')
    biv = 'Bivariate Fit of weight (kg) By height (cm)'
    ow = 'Oneway Analysis of adverse events By treatment'
    forms = [('__biv', biv, ['Fit Special…'], 'Fit Special', None), ('__biv', biv, ['Flexible', 'Fit Spline', 'Other…'], 'Fit Spline Other', None),
             ('__biv', biv, ['Fit Orthogonal', 'Specified Variance Ratio…'], 'Fit Orthogonal ratio', None), ('__biv', biv, ['Density Ellipse', 'Other…'], 'Density Ellipse Other', None),
             ('__biv', biv, ['Fit Quantile', 'Other…'], 'Fit Quantile Other', None), ('__biv', biv, ['Group By…'], 'Group By', None),
             ('__biv', biv, ['Bayes Factor for the Correlation…'], 'the correlation\'s Bayes factor', 'Bayes Factor'),
             ('__biv', 'Smoothing Spline Fit, lambda=1', ['Change Lambda…'], 'Change Lambda', None), ('__biv', 'Quantile Fit, τ=0.5', ['Change Quantile…'], 'Change Quantile', None),
             ('__many', 'Fit Y by X', ['Arrange in Rows…'], 'Arrange in Rows', None), ('__mp', 'Matched Pairs', ['Bayes Factor…'], 'the paired Bayes factor', 'Bayes Factor'),
             ('__ow', ow, ['Compare Rates…'], 'Compare Rates', 'Compare Rates'), ('__ow', ow, ['Power…'], 'Power Details', None),
             ('__ow', ow, ['Equivalence Test', 'Means…'], 'Equivalence Test of means', None), ('__ow', ow, ['Equivalence Test', 'Probability of Superiority…'], 'Equivalence Test of the probability of superiority', 'Brunner-Munzel and the probability of superiority'),
             ('__ow', ow, ['Compare Means', 'With Control, Dunnett\'s…'], 'Dunnett\'s control level', None), ('__ow', ow, ['Set α Level', 'Other…'], 'Set α Level', None),
             ('__lg', 'Logistic Fit of response By dose (mg)', ['Inverse Prediction…'], 'Inverse Prediction', None),
             ('__ct', 'Contingency Analysis of response By treatment', ['Cochran Mantel Haenszel…'], 'Cochran Mantel Haenszel', None)]
    for var, title_, path, name, topic in forms:
        r = await page.ev(f'__hlp.form(window.{var}, {json.dumps(title_)}, {json.dumps(path)})')
        check_form(r, name, topic)
    r = await page.ev('(async () => { for (const rep of [__biv, __many, __mp, __ow, __lg, __ct]) SM.app.closeReport(rep); return SM.ui.dialogs.length; })()')
    check('the forms closed with their ×', r, 0)

    # ---- dark theme, phone width
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.title === 'Oneway Analysis of yield (g) By fertilizer')))")
    await asyncio.sleep(1.5)
    await shot(page, '06-dark-oneway.png')
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.title === 'Contingency Analysis of response By treatment')))")
    await asyncio.sleep(1.2)
    await shot(page, '07-dark-contingency.png')
    # the reports of the tests beyond JMP, in the dark theme
    for title_, outline_, name_ in (('Oneway Analysis of adverse events By treatment', 'Compare Rates', '13-dark-rates.png'), ('Matched Pairs (every pair)', "Cochran's Q Test", '14-dark-binary.png')):
        await page.ev(f"SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.title === {json.dumps(title_)})))")
        await asyncio.sleep(1.0)
        await page.ev(f"__fyx.scrollTo({json.dumps(outline_)}, SM.app.reports.find(r => r.title === {json.dumps(title_)}))")
        await shot(page, name_)
    r = await page.ev("SM.app.reports.filter(r => ['Oneway Analysis of adverse events By treatment', 'Matched Pairs (every pair)'].includes(r.title)).map(r => r.body.querySelectorAll('.sm-ob-error').length)")
    check('dark theme: the new reports redraw without errors', (len(r) >= 2, all(v == 0 for v in r)), (True, True))
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
    for title_, name_ in (('Matched Pairs (every pair)', '15-phone-binary.png'), ('Oneway Analysis of adverse events By treatment', '16-phone-rates.png')):
        await page.ev(f"SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.title === {json.dumps(title_)})))")
        await asyncio.sleep(0.8)
        check(f'no horizontal page scroll at phone width ({title_})', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
        await shot(page, name_)
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")

    # ---- the graphs' Python code: a block under each graph, run in the page
    await chart_code(page)
    await matched_pairs_charts(page)

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


# ---- the graphs' matplotlib code --------------------------------------------
# Each graph has a code block right under it (details.sm-code, ending in
# plt.show()); the block runs in the page's own Python (the notebook's
# runner) with test_charts.PROBE in place of plt.show(), and the figure it
# draws is compared with the Plotly graph above it.
CHART_TABLE = r'''(() => {
  const g = SM.util.rng('fitybyx-charts'); const n = 84;
  const x = [], y = [], w = [], f = [], grp = [], k = [], o = [], by = [], blk = [];
  for (let i = 0; i < n; i++) {
    const xi = Math.round(10 * (1 + 9 * g.u())) / 10, gi = ['lo', 'mid', 'hi'][i % 3];
    x.push(i === 4 ? NaN : xi); y.push(Math.round(100 * (3 + 0.8 * xi - 0.05 * xi * xi + (gi === 'hi' ? 1.2 : gi === 'mid' ? 0.5 : 0) + g.normal(0, 0.8))) / 100);
    w.push(Math.round(100 * (0.5 + 1.5 * g.u())) / 100); f.push(i === 6 ? 0 : 1 + (i % 3)); grp.push(gi);
    k.push(g.u() < 1 / (1 + Math.exp(-(xi - 5))) ? 'yes' : 'no'); o.push(xi < 4 ? 'low' : xi > 7 ? 'high' : 'middle'); by.push(i % 2 ? 'u' : 'v'); blk.push(['b1', 'b2', 'b3', 'b4'][Math.floor(i / 3) % 4]);
  }
  const t = new SM.Table({ name: 'Chart pairs', columns: [{ name: 'x', values: x }, { name: 'y', values: y }, { name: 'w', values: w }, { name: 'n', values: f },
    { name: 'g', dataType: 'character', values: grp, valueOrder: ['lo', 'mid', 'hi'] }, { name: 'k', dataType: 'character', values: k },
    { name: 'o', dataType: 'character', values: o, valueOrder: ['low', 'middle', 'high'], modelingType: 'ordinal' }, { name: 'by', dataType: 'character', values: by }, { name: 'blk', dataType: 'character', values: blk }] });
  SM.app.addTable(t);
  return t.nrows;
})()'''


def curve_ok(ln, t, rel=1e-9):
    """An mpl line with the trace's points (the page's thinned curve lies on it)."""
    if not ln:
        return False
    if close(ln['x'], t['x'], rel, 1e-12) and close(ln['y'], t['y'], rel, 1e-12):
        return True
    try:   # the page's curve thinned (lowess): each of its points on the code's curve
        xs, ys = ln['x'], ln['y']
        for a, b in points_of(t):
            i = min(range(len(xs)), key=lambda j: abs(xs[j] - a))
            if abs(xs[i] - a) > 1e-9 * max(1, abs(a)) or abs(ys[i] - b) > 1e-6 * max(1, abs(b)):
                return False
        return True
    except (TypeError, ValueError):
        return False


def seg_match(ax, x0, x1, y0, y1):
    segs = [s for c in ax['segments'] for s in c['segs']]
    return any(close(s[0], [x0, y0], 1e-9, 1e-9) and close(s[1], [x1, y1], 1e-9, 1e-9) for s in segs)


def check_bivariate(label, g, F):
    ax = F['axes'][0]
    check(f'{label}: the title and the size', ((ax['title'] or F['suptitle']), F['size']), (g['label'], [g['w'] / 100, g['h'] / 100]))
    check(f'{label}: the axis titles', (ax['xlabel'], ax['ylabel']), (g['titles']['x'], g['titles']['y']))
    pts = [t for t in g['traces'] if t.get('name') == 'Points']
    if pts:
        got = ax['scatter'][0]['xy'] if ax['scatter'] else []
        check.near(f'{label}: the points', maxdiff([q for p in got for q in p], [q for p in points_of(pts[0]) for q in p]), 0, 1e-12)
    named = [t for t in g['traces'] if t.get('type') == 'scatter' and t.get('showlegend') and t.get('name') and t['name'] != 'Points']
    for t in named:
        lns = lines_labelled(ax, t['name'])
        spline_gcv = 'lambda by GCV' in t['name']
        check(f'{label}: the curve of {t["name"]}', curve_ok(lns[0] if lns else None, t, 1e-4 if spline_gcv else 1e-9), True)
    for t in [t for t in g['traces'] if t.get('type') == 'scatter' and t.get('mode') == 'lines' and not t.get('showlegend') and t.get('dash') in ('dash', 'dot') and not t.get('fill')]:
        ls = '--' if t['dash'] == 'dash' else ':'
        check(f'{label}: a confidence curve ({t["dash"]})', any(ln['ls'] == ls and close(ln['x'], t['x'], 1e-9, 1e-12) and close(ln['y'], t['y'], 1e-9, 1e-12) for ln in ax['lines']), True)
    shades = [t for t in g['traces'] if t.get('fill') == 'toself']
    check(f'{label}: the shaded bands', len(ax['polys']) - sum(1 for p in ax['polys'] if 'contour' in p), len(shades))
    for t, p in zip(shades, [p for p in ax['polys'] if 'contour' not in p]):
        ys = [q[1] for q in p['paths'][0] if q[1] is not None]
        tys = [v for v in t['y'] if v is not None]
        check.near(f'{label}: a shaded band spans the report\'s', max(abs(min(ys) - min(tys)), abs(max(ys) - max(tys))), 0, 1e-9)
    contours = [t for t in g['traces'] if t.get('type') == 'contour']
    if contours:
        got = sorted(v for p in ax['polys'] if 'contour' in p for v in p['contour'])
        check.near(f'{label}: the density contours\' levels', maxdiff(got, sorted(t['contours']['start'] for t in contours)), 0, 1e-12)
    bars = [t for t in g['traces'] if t.get('type') == 'bar' and t.get('x') and t.get('y') and t.get('hoverinfo') == 'skip' and t.get('showlegend') is False and t.get('width')]
    if bars:
        top, side = F['axes'][1], F['axes'][2]
        bx = [t for t in bars if t.get('yaxis') == 'y2'][0]
        by = [t for t in bars if t.get('xaxis') == 'x2'][0]
        check.near(f'{label}: the histogram border of X', maxdiff([b['h'] for b in top['bars']], bx['y']), 0, 1e-12)
        check.near(f'{label}: the histogram border of Y', maxdiff([b['w'] for b in side['bars']], by['x']), 0, 1e-12)


async def chart_code(page):
    await page.ev(GRAPHS_JS)
    await page.ev('__gr.idle()')   # the reports run again by a change of theme are done
    await page.ev(CHART_TABLE)
    tbl = "__fyx.table('Chart pairs')"
    # ---- Bivariate: every fit, the bands, the histogram borders
    r = await page.ev('''(async () => {
      const t = __fyx.table('Chart pairs'); const sc = t.col('y').id + '~' + t.col('x').id;
      const o = {}; o[sc + '|hist'] = true;
      o[sc + '|fits'] = [{ id: 'f1', kind: 'line', cfit: true, cind: true, sfit: true, sind: true }, { id: 'f2', kind: 'poly', degree: 3 }, { id: 'f3', kind: 'spline', lam: 1 },
        { id: 'f4', kind: 'lowess', frac: 0.5, it: 1 }, { id: 'f5', kind: 'each' }, { id: 'f6', kind: 'robust', method: 'huber' }, { id: 'f7', kind: 'orth', mode: 'univariate' },
        { id: 'f8', kind: 'ellipse', p: 0.9 }, { id: 'f9', kind: 'kde' }, { id: 'f10', kind: 'quantile', tau: 0.5 }, { id: 'f11', kind: 'mean' },
        { id: 'f12', kind: 'special', ytr: 'log', xtr: 'sqrt', degree: 2, cfit: true }, { id: 'f13', kind: 'spline', lam: null, standardize: true }];
      const rep = await __fyx.open('Chart pairs', 'fitybyx', { y: ['y'], x: ['x'] }, o);
      const o2 = {}; o2[sc + '|groupBy'] = t.col('g').id; o2[sc + '|fits'] = [{ id: 'f1', kind: 'line', resid: true, sfit: true }, { id: 'f2', kind: 'poly', degree: 2, cfit: true }];
      const rep2 = await __fyx.open('Chart pairs', 'fitybyx', { y: ['y'], x: ['x'], weight: ['w'], freq: ['n'] }, o2);
      // each report's graphs before the change to the rows runs it again
      const g1 = await __gr.graphs(rep), g2 = await __gr.graphs(rep2);
      t.setState([10, 11, 12, 13], 'excluded', true);
      const o3 = {}; o3[sc + '|fits'] = [{ id: 'f1', kind: 'line', resid: true }];
      const rep3 = await __fyx.open('Chart pairs', 'fitybyx', { y: ['y'], x: ['x'], by: ['by'] }, o3);
      const g3 = await __gr.graphs(rep3), errors = [rep, rep2, rep3].flatMap((x) => __fyx.errors(x));
      t.setState([10, 11, 12, 13], 'excluded', false);
      return { g1, g2, g3, errors, undrawn: __gr.take() };
    })()''')
    check('charts: no errors (Bivariate with every fit, Group By with weights, By with excluded rows)', r['errors'], [])
    check('charts: every graph of the Bivariate reports drawn (none in a closed outline)', r['undrawn'], [])
    diag = ['Residual by Predicted', 'Actual by Predicted', 'Residual by Row', 'Residual by x', 'Residual Normal Quantile Plot']
    check('charts: the graphs of the Group By report (the scatterplot, a line fit\'s diagnostics for each group)', [g['label'] for g in r['g2']], ['y by x'] + diag * 3)
    for g in r['g1'] + r['g2'] + r['g3']:
        check(f'charts: {g["label"]}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
    for tag, gs in (('Bivariate', r['g1'][:1]), ('Bivariate (Group By, Weight, Freq)', r['g2']), ('Bivariate (By, excluded rows)', r['g3'])):
        for i, g in enumerate(gs):
            F, err = await run_graph(page, g, tbl)
            lab = f'{tag}: {g["label"]}' + (f' ({i})' if g['label'] != 'y by x' else '')
            check(f'{lab}: the code runs in the page', err, None)
            if not F:
                continue
            F = F[0]
            if g['label'] == 'y by x':
                check_bivariate(lab, g, F)
            else:
                ax = F['axes'][0]
                got = ax['scatter'][0]['xy'] if ax['scatter'] else []
                # the page's normal quantiles are its own approximation (relative error below 1.2e-9)
                check.near(f'{lab}: the points', maxdiff([q for p in got for q in p], [q for p in points_of(g['traces'][0]) for q in p]), 0, 1e-8)
                check(f'{lab}: the titles', (ax['title'], ax['xlabel'], ax['ylabel']), (g['label'], g['titles']['x'], g['titles']['y']))
    # ---- Oneway: every overlay, the comparison circles, ANOM, the quantile, CDF and density plots; a block
    r = await page.ev('''(async () => {
      const t = __fyx.table('Chart pairs'); const sc = t.col('y').id + '~' + t.col('g').id;
      const o = {}; for (const k of ['points', 'jitter', 'box', 'diamonds', 'meanLines', 'errorBars', 'sdLines', 'ciLines', 'grandMean', 'connect', 'anova', 'anom', 'cdf']) o[sc + '|' + k] = true;
      o[sc + '|compare'] = [{ method: 'tukey', control: null }]; o[sc + '|nqp'] = { orient: 'aq' }; o[sc + '|densities'] = 'composition';
      const rep = await __fyx.open('Chart pairs', 'fitybyx', { y: ['y'], x: ['g'], freq: ['n'] }, o);
      const o2 = {}; o2[sc + '|anova'] = true; o2[sc + '|compare'] = [{ method: 'dunnett', control: 'mid' }]; o2[sc + '|nqp'] = { orient: 'qa' }; o2[sc + '|densities'] = 'proportion';
      const rep2 = await __fyx.open('Chart pairs', 'fitybyx', { y: ['y'], x: ['g'], weight: ['w'] }, o2);
      const o3 = {}; o3[sc + '|anova'] = true; o3[sc + '|meansd'] = true; o3[sc + '|densities'] = 'compare';
      const rep3 = await __fyx.open('Chart pairs', 'fitybyx', { y: ['y'], x: ['g'], block: ['blk'] }, o3);
      return { g1: await __gr.graphs(rep), g2: await __gr.graphs(rep2), g3: await __gr.graphs(rep3), errors: [rep, rep2, rep3].flatMap((x) => __fyx.errors(x)), undrawn: __gr.take() };
    })()''')
    check('charts: no errors (Oneway with its overlays and plots)', r['errors'], [])
    check('charts: every graph of the Oneway reports drawn', r['undrawn'], [])
    check('charts: the Oneway graphs', [g['label'] for g in r['g1']], ['y by g', 'Analysis of Means', 'Normal Quantile Plot', 'CDF Plot', 'Densities'])
    for g in r['g1'] + r['g2'] + r['g3']:
        check(f'charts: {g["label"]}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
    for tag, gs in (('Oneway (Freq, Tukey)', r['g1']), ('Oneway (Weight, Dunnett)', r['g2']), ('Oneway (block)', r['g3'])):
        for g in gs:
            F, err = await run_graph(page, g, tbl)
            lab = f'{tag}: {g["label"]}'
            check(f'{lab}: the code runs in the page', err, None)
            if not F:
                continue
            F = F[0]
            ax = F['axes'][0]
            if g['label'] == 'y by g':
                check_oneway(lab, g, F)
            elif g['label'] in ('Analysis of Means',):
                lims = [(a, b) for t in g['traces'] if t.get('name') in ('LDL', 'UDL') for a, b in zip(points_of(t)[::2], points_of(t)[1::2])]
                check(f'{lab}: the decision limits', all(seg_match(ax, p0[0], p1[0], p0[1], p1[1]) for p0, p1 in lims) and len(lims) > 0, True)
                means = [t for t in g['traces'] if t.get('name') == 'Means'][0]
                check.near(f'{lab}: the means', maxdiff([q[1] for q in ax['scatter'][0]['xy']], means['y']), 0, 1e-12)
            elif g['label'] == 'Normal Quantile Plot':   # the page's normal quantiles are its own approximation (relative error below 1.2e-9)
                for t in [t for t in g['traces'] if t.get('mode') == 'markers']:
                    sc = [s for s in ax['scatter'] if s['label'] == t['name']]
                    check.near(f'{lab}: the points of {t["name"]}', maxdiff([q for p in (sc[0]['xy'] if sc else []) for q in p], [q for p in points_of(t) for q in p]), 0, 1e-8)
                for t in [t for t in g['traces'] if t.get('mode') == 'lines']:
                    check(f'{lab}: a normal line', find_line(ax, t['x'], t['y'], rel=1e-8, abs_=1e-8) is not None, True)
            elif g['label'] == 'CDF Plot':
                for t in g['traces']:
                    ln = lines_labelled(ax, t['name'])
                    check(f'{lab}: the steps of {t["name"]}', bool(ln) and close(ln[0]['x'], t['x'], 1e-12) and close(ln[0]['y'], t['y'], 1e-12) and ln[0]['drawstyle'] == 'steps-post', True)
            elif g['label'] == 'Densities':
                if any(t.get('stackgroup') for t in g['traces']):
                    acc = None
                    tops = []
                    for t in g['traces']:
                        acc = list(t['y']) if acc is None else [a + b for a, b in zip(acc, t['y'])]
                        tops.append(max(acc))
                    check.near(f'{lab}: the stacked shares', maxdiff([max(q[1] for q in p['paths'][0]) for p in ax['polys']], tops), 0, 1e-9)
                else:
                    for t in g['traces']:
                        ln = lines_labelled(ax, t['name'])
                        check(f'{lab}: the density of {t["name"]}', bool(ln) and close(ln[0]['x'], t['x'], 1e-12) and close(ln[0]['y'], t['y'], 1e-9, 1e-12), True)
            check(f'{lab}: the titles', ((ax['title'] or F['suptitle']), ax['xlabel'], ax['ylabel']), (g['label'], g['titles']['x'] or '', g['titles']['y'] or ''))
    # ---- Logistic and Contingency
    r = await page.ev('''(async () => {
      const t = __fyx.table('Chart pairs'); const s1 = t.col('k').id + '~' + t.col('x').id, s2 = t.col('g').id + '~' + t.col('x').id;
      const o = {}; o[s1 + '|roc'] = true; o[s1 + '|lift'] = true; o[s2 + '|roc'] = true;
      const rep = await __fyx.open('Chart pairs', 'fitybyx', { y: ['k', 'g'], x: ['x'], freq: ['n'] }, o);
      const s3 = t.col('k').id + '~' + t.col('g').id, s4 = t.col('o').id + '~' + t.col('blk').id;
      const o2 = {}; o2[s3 + '|anomp'] = true; o2[s4 + '|ca'] = true;
      const rep2 = await __fyx.open('Chart pairs', 'fitybyx', { y: ['k', 'o'], x: ['g', 'blk'], weight: ['w'] }, o2);
      return { g1: await __gr.graphs(rep), g2: await __gr.graphs(rep2), errors: [rep, rep2].flatMap((x) => __fyx.errors(x)), undrawn: __gr.take() };
    })()''')
    check('charts: no errors (Logistic, Contingency)', r['errors'], [])
    check('charts: every graph of the Logistic and Contingency reports drawn', r['undrawn'], [])
    for g in r['g1'] + r['g2']:
        check(f'charts: {g["label"]}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
    for i, g in enumerate(r['g1'] + r['g2']):
        F, err = await run_graph(page, g, tbl)
        lab = f'{g["label"]} ({i})'
        check(f'{lab}: the code runs in the page', err, None)
        if not F:
            continue
        F = F[0]
        ax = F['axes'][0]
        if g['label'].endswith('logistic plot'):
            curves = [t for t in g['traces'] if t.get('mode') == 'lines']
            check(f'{lab}: the cumulative probability curves', all(find_line(ax, t['x'], t['y'], rel=1e-6, abs_=1e-9) is not None for t in curves) and len(curves) > 0, True)
            pts = [t for t in g['traces'] if t.get('name') == 'Points'][0]
            got = ax['scatter'][0]['xy'] if ax['scatter'] else []
            check.near(f'{lab}: the points at their X', maxdiff([p[0] for p in got], pts['x']), 0, 1e-12)
            check(f'{lab}: the titles', (ax['title'], ax['xlabel'], ax['ylabel']), (g['label'], g['titles']['x'], g['titles']['y']))
        elif g['label'] in ('ROC Curve', 'Lift Curve'):
            curves = [t for t in g['traces'] if t.get('showlegend') is not False]
            for t in curves:
                check(f'{lab}: the curve of {t["name"]}', find_line(ax, t['x'], t['y'], rel=1e-9, abs_=1e-12) is not None, True)
            check(f'{lab}: the legend', F['legend'], [t['name'] for t in curves])
        elif g['label'].endswith('mosaic'):
            cells = [t for t in g['traces'] if t.get('type') == 'bar' and t.get('x') and len(t['x']) == 1 and t.get('y') and len(t['y']) == 1 and t.get('base')]
            want = sorted((round(t['x'][0], 9), round(t['base'][0], 9), round(t['y'][0], 9), round(t['width'] if not isinstance(t['width'], list) else t['width'][0], 9)) for t in cells)
            got = sorted((round(b['x'] + b['w'] / 2, 9), round(b['y'], 9), round(b['h'], 9), round(b['w'], 9)) for b in ax['bars'])
            check(f'{lab}: every cell, where the page draws it', got, want)
            check(f'{lab}: the titles', (ax['title'], ax['xlabel'], ax['ylabel']), (g['label'], g['titles']['x'], g['titles']['y']))
        elif g['label'] == 'Analysis of Means for Proportions':
            lims = [(a, b) for t in g['traces'] if t.get('name') in ('LDL', 'UDL') for a, b in zip(points_of(t)[::2], points_of(t)[1::2])]
            check(f'{lab}: the decision limits', all(seg_match(ax, p0[0], p1[0], p0[1], p1[1]) for p0, p1 in lims) and len(lims) > 0, True)
            props = [t for t in g['traces'] if t.get('name') == 'Proportions'][0]
            check.near(f'{lab}: the proportions', maxdiff([q[1] for q in ax['scatter'][0]['xy']], props['y']), 0, 1e-12)
            check(f'{lab}: the titles', (ax['title'], ax['xlabel'], ax['ylabel']), (g['label'], g['titles']['x'], g['titles']['y']))
        elif g['label'] == 'Correspondence Analysis':
            for t, sc in zip(g['traces'], ax['scatter']):
                check.near(f'{lab}: the coordinates of {t["name"]}\'s levels', maxdiff([q for p in sc['xy'] for q in p], [q for p in points_of(t) for q in p]), 0, 1e-9)
            check(f'{lab}: the axis titles', (ax['xlabel'], ax['ylabel']), (g['titles']['x'], g['titles']['y']))
    await page.ev("for (const r of SM.app.reports.filter((x) => x.table && x.table.name === 'Chart pairs')) SM.app.closeReport(r); SM.app.closeTable(__fyx.table('Chart pairs'));")


def check_oneway(lab, g, F):
    ax = F['axes'][0]
    check(f'{lab}: the levels on the axis', [t for t in ax['xticklabels'] if t], g['ticks'])
    pts = [t for t in g['traces'] if t.get('name') == 'Points'][0]
    got = ax['scatter'][0]['xy'] if ax['scatter'] else []
    same = len(got) == len(pts['y']) and all(round(a[0]) == round(b) and abs(a[0] - round(a[0])) <= 0.23 + 1e-9 and abs(a[1] - c) < 1e-12 for a, b, c in zip(got, pts['x'], pts['y']))
    check(f'{lab}: each point at its level (jittered) and its value', same, True)
    ys = [ln['y'] for ln in ax['lines']]
    for t in [t for t in g['traces'] if t.get('type') == 'box']:
        ok = any(close(v, [t['median'][0]] * 2) for v in ys) and any(close(v, [t['q1'][0], t['lowerfence'][0]]) for v in ys) and any(close(v, [t['q3'][0], t['upperfence'][0]]) for v in ys)
        check(f'{lab}: the box plot of {t["name"]}', ok, True)
    for t in [t for t in g['traces'] if t.get('type') == 'scatter' and t.get('mode') == 'lines' and t.get('x') and len(t['x']) == 14]:
        check(f'{lab}: a means diamond', find_line(ax, t['x'][:5], t['y'][:5], rel=1e-9) is not None, True)
    for s in g['shapes']:
        if s.get('xref') in (None, 'x'):
            check(f'{lab}: a mean, error-bar, std dev or CI line at {s["y0"]:.4g}', seg_match(ax, s['x0'], s['x1'], s['y0'], s['y1']), True)
        else:
            check(f'{lab}: the grand mean', find_line(ax, None, [s['y0'], s['y0']], rel=1e-12) is not None, True)
    conn = [t for t in g['traces'] if t.get('mode') == 'lines+markers']
    if conn:
        check(f'{lab}: the connected means', find_line(ax, conn[0]['x'], conn[0]['y'], rel=1e-12) is not None, True)
    circles = [t for t in g['traces'] if t.get('xaxis') == 'x2']
    if circles:
        cx = F['axes'][1]
        ells = [p for p in cx['patches'] if p['type'] == 'ellipse']
        want = [((max(t['y']) + min(t['y'])) / 2, (max(t['y']) - min(t['y'])) / 2) for t in circles]
        check.near(f'{lab}: the comparison circles\' centres and radii', maxdiff([q for e in ells for q in (e['center'][1], e['h'] / 2)], [q for c in want for q in c]), 0, 1e-6)


# ---- Matched Pairs: the two graphs' matplotlib code ---------------------------------------------
# A group colouring the pairs; then a pair of date columns (text in the CSV, milliseconds in the
# page) in a By group with rows excluded. Every graph has its block under it, and the figure the
# block draws in the page's Python is the Plotly graph's: the points and their colours, the lines
# at 0, the mean difference and its limits, the titles and the size.
MP_TABLE = r'''(() => {
  const g = SM.util.rng('matchedpairs-charts'); const n = 45;
  const b = [], a = [], grp = [], s = [], e = [], by = [];
  for (let i = 0; i < n; i++) {
    const x = Math.round(100 * g.normal(60, 9)) / 100; b.push(x); a.push(i === 3 ? NaN : Math.round(100 * (x + 2.5 + g.normal(0, 4))) / 100);
    grp.push(i === 8 ? null : ['lo', 'mid', 'hi'][i % 3]); const d0 = Date.UTC(2024, 0, 1) + Math.floor(g.u() * 300) * 86400000;
    s.push(d0); e.push(d0 + (1 + Math.floor(g.u() * 30)) * 86400000); by.push(i % 4 ? 'u' : 'v');
  }
  SM.app.addTable(new SM.Table({ name: 'MP charts', columns: [{ name: 'before', values: b }, { name: 'after', values: a },
    { name: 'grp', dataType: 'character', values: grp, valueOrder: ['lo', 'mid', 'hi'] },
    { name: 'start', dataType: 'numeric', format: { kind: 'date' }, values: s }, { name: 'end', dataType: 'numeric', format: { kind: 'date' }, values: e },
    { name: 'by', dataType: 'character', values: by }] }));
  return n;
})()'''


async def matched_pairs_charts(page):
    await page.ev(GRAPHS_JS)
    await page.ev(MP_TABLE)
    r = await page.ev('''(async () => {
      const t = __fyx.table('MP charts'); const sc = t.col('before').id + '~' + t.col('after').id;
      const o = {}; o[sc + '|plotRow'] = true;
      const rep = await __fyx.open('MP charts', 'matchedpairs', { y: ['before', 'after'], x: ['grp'] }, o);
      const g1 = await __gr.graphs(rep);
      t.setState([5, 8, 13], 'excluded', true);
      const sc2 = t.col('start').id + '~' + t.col('end').id; const o2 = {}; o2[sc2 + '|plotRow'] = true; o2.alpha = 0.1;
      const rep2 = await __fyx.open('MP charts', 'matchedpairs', { y: ['start', 'end'], by: ['by'] }, o2);
      const g2 = await __gr.graphs(rep2);
      t.setState([5, 8, 13], 'excluded', false);
      return { g1, g2, errors: [rep, rep2].flatMap((x) => __fyx.errors(x)), undrawn: __gr.take() };
    })()''', timeout=300)
    check('Matched Pairs charts: no errors (a group; dates in a By group with rows excluded)', r['errors'], [])
    check('Matched Pairs charts: every graph drawn', r['undrawn'], [])
    check('Matched Pairs charts: the graphs of each report', ([g['label'] for g in r['g1']], [g['label'] for g in r['g2']]),
          (['after-before by mean', 'after-before by row'], ['end-start by mean', 'end-start by row'] * 2))
    for g in r['g1'] + r['g2']:
        check(f'Matched Pairs charts: {g["label"]}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
    for i, g in enumerate(r['g1'] + r['g2']):
        F, err = await run_graph(page, g, "__fyx.table('MP charts')")
        lab = f'Matched Pairs charts: {g["label"]} ({"a group" if i < 2 else "By group " + str((i - 2) // 2 + 1)})'
        check(f'{lab}: the code runs in the page', err, None)
        if not F:
            continue
        F = F[0]
        ax = F['axes'][0]
        t0 = g['traces'][0]
        got = ax['scatter'][0]['xy'] if ax['scatter'] else []
        check.near(f'{lab}: the points', maxdiff([q for p in got for q in p], [q for p in points_of(t0) for q in p]), 0, 1e-9)
        if isinstance(t0.get('mcolor'), list):
            check(f'{lab}: each pair in its group\'s colour', [c[:7] for c in ax['scatter'][0]['colors']], t0['mcolor'])
        hl = sorted(ln['y'][0] for ln in ax['lines'] if len(ln['y']) == 2 and ln['y'][0] == ln['y'][1])
        check.near(f'{lab}: the lines (0, the mean difference and its limits; by row the mean difference)', maxdiff(hl, sorted(s['y0'] for s in g['shapes'])), 0, 1e-9)
        check(f'{lab}: the titles and the size', (ax['title'], ax['xlabel'], ax['ylabel'], F['size']), (g['label'], g['titles']['x'], g['titles']['y'], [g['w'] / 100, g['h'] / 100]))
        if i >= 2:
            check(f'{lab}: the dates turned back into milliseconds, the group\'s rows kept, the excluded ones dropped',
                  ('pd.to_datetime(df["start"])' in g['code'], 'df = df[df["by"] ==' in g['code'], 'df = df.drop(index=' in g['code']), (True, True, True))
    await page.ev("for (const r of SM.app.reports.filter((x) => x.table && x.table.name === 'MP charts')) SM.app.closeReport(r); SM.app.closeTable(__fyx.table('MP charts'));")


asyncio.run(main())
sys.exit(check.done())
