#!/usr/bin/env python3
"""smui.html in a real browser: Fit Model's mixed models (smui-p-mixed.js).

The launch dialog by real clicks: the Mixed Model personality's own controls
(Unbounded Variance Components, DF, Repeated Structure, the spatial Type)
and roles (Repeated, Subject), Attributes > Nest Random Coefficients; the
Mixed Model report's outlines, its Fixed Effects Tests against the exact
split-plot F tests computed in the page, Unbounded Variance Components on
and off (a negative component, then one on the boundary with its note);
Standard Least Squares with random effects (Summary of Fit, REML Variance
Component Estimates, Effect Details: LS means, Tukey HSD, Test Slices, the
LSMeans Plot with its overlay and intervals); the red triangle's Multiple
Comparisons dialog; random coefficients (the Random Coefficients report);
a repeated structure (AR(1): the Repeated Effects table and the variogram;
Compare Structures; Unstructured's Repeated Measures Covariance Diagnostics
with its heat map); a spatial structure's variogram; a generalized linear
mixed model (binomial); Save Columns (the conditional prediction formula
against the report's conditional predictions); Simulate (its dialog,
progress, the power table, Stop); By groups; a saved project; every graph
with its code block after it; both themes and phone width. A hostile table
(levels and subjects carrying a line of Python behind a line break, a
closing quote, braces, a backslash or triple quotes) through the mixed
personalities with every sub-report on (LS means, slices, contrasts, BLUPs,
the repeated diagnostics, Compare Structures, profile intervals, the
profilers, the indicator parameterization, the Skeleton ANOVA, a binomial
GLMM with such a target level): every code block and the script parse, and
no name from the table is code. A long fit (a spatial field of 1500 points):
after a second the report's bar shows the REML iteration and its −2 Residual
Log Likelihood, counting up, and Stop, which restarts the engine; the report
says it was stopped, and Redo fits it to the end; a quick fit shows nothing.
A spatial range beyond the data (a field of wide bumps): the report's warning
and its suggestions. The launch dialog's hint for a Validation column cast
with a random effect.

    SMUI_HTTP_PORT=8822 SMUI_CDP_PORT=9322 python3 resources/tests/smui/test-ui-mixed.py
"""
import ast
import asyncio
import json
import os
import re
import sys

from cdp import BASE, Checks, open_page, wait_engine
from test_charts import GRAPHS_JS, close, find_line, maxdiff, points_of, run_graph

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


HELPERS = '''
window.__mx = {
  rep: () => SM.app.reports[SM.app.reports.length - 1],
  state: (rep) => ({ title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
    errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 600)), warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)),
    notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent.slice(0, 300)), plots: rep.plots.length }),
  outline: (title, rep) => { const r = rep || __mx.rep(); const h = [...r.body.querySelectorAll('.sm-ob-head')].find(x => x.querySelector('h2, h3, h4').textContent === title); return h ? h.parentElement : null; },
  table: (title, n = 0, rep) => { const ob = __mx.outline(title, rep); if (!ob) return null; const t = ob.querySelector(':scope > .sm-ob-body').querySelectorAll('table.sm-rt, table.sm-kv')[n]; return t ? [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent.trim())) : null; },
  kv: (title) => Object.fromEntries((__mx.table(title) || []).map(r => [r[0], r[r.length - 1]])),
  col: (title, name, n = 0) => { const t = __mx.table(title, n); if (!t) return null; const i = t[0].indexOf(name); return t.slice(1).map(r => r[i]); },
  dlg: () => document.querySelector('.sm-launch-dialog'),
  form: () => [...document.querySelectorAll('.sm-dialog')].pop(),
  pick: (...names) => { const d = __mx.dlg(); const items = [...d.querySelectorAll('.sm-pick-list li')];
    names.forEach((n, i) => { const li = items.find(x => x.textContent === n); if (!li) throw new Error('no column in the dialog ' + n); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, metaKey: i > 0 })); }); },
  btn: (label, root) => { const b = [...(root || __mx.dlg()).querySelectorAll('button')].find(x => x.textContent === label); if (!b) throw new Error('no button ' + label); b.click(); },
  role: (label) => { const b = [...__mx.dlg().querySelectorAll('.sm-role .sm-btn')].find(x => x.textContent === label); if (!b) throw new Error('no role ' + label); b.click(); },
  roleShown: (label) => { const r = [...__mx.dlg().querySelectorAll('.sm-role')].find(x => x.querySelector('.sm-btn').textContent === label); return r ? !r.hidden : null; },
  effects: () => [...__mx.dlg().querySelectorAll('.sm-fm-effects li')].map(li => li.textContent),
  selEff: (...idx) => { const lis = [...__mx.dlg().querySelectorAll('.sm-fm-effects li')]; idx.forEach((i, k) => lis[i].dispatchEvent(new MouseEvent('click', { bubbles: true, metaKey: k > 0 }))); },
  labelShown: (text) => { const l = [...__mx.dlg().querySelectorAll('.sm-fm-pers label')].find(x => x.textContent.startsWith(text)); return l ? !l.hidden : null; },
  sel: (label, value) => { const s = __mx.dlg().querySelector(`select[aria-label="${label}"]`); s.value = value; s.dispatchEvent(new Event('change')); },
  menuItem: async (...path) => {
    for (let i = 0; i < path.length; i++) {
      const menus = [...document.querySelectorAll('.sm-menu')];
      const m = menus[menus.length - 1];
      const b = m && [...m.querySelectorAll('button')].find(x => x.querySelector('.sm-label').textContent === path[i]);
      if (!b) throw new Error('no menu item ' + path[i] + ' in ' + (m ? [...m.querySelectorAll('.sm-label')].map(x => x.textContent).join('|') : 'no menu'));
      if (i < path.length - 1) b.dispatchEvent(new MouseEvent('mouseenter')); else b.click();
      await __mx.tick();
    }
  },
  topMenu: async (...path) => { __mx.rep().body.querySelector('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu').click(); await __mx.tick(); await __mx.menuItem(...path); },
  obMenu: async (title, ...path) => { __mx.outline(title).querySelector(':scope > .sm-ob-head .sm-ob-menu').click(); await __mx.tick(); await __mx.menuItem(...path); },
  tick: () => new Promise(r => setTimeout(r, 40)),
  done: (rep) => new Promise(res => rep.on('done', res)),
  idle: async () => { let calm = 0; for (let i = 0; i < 4800 && calm < 12; i++) { await new Promise(r => setTimeout(r, 25)); calm = SM.app.reports.some(x => x.body.classList.contains('is-running')) ? 0 : calm + 1; } },
  num: (s) => Number(String(s).replace('−', '-').replace('<', '').replace('*', '')),
  // every graph of a report with its code block right after it (the chart tests' rule)
  graphsWithCode: (rep) => [...(rep || __mx.rep()).body.querySelectorAll('.sm-plot')].map(p => { const n = p.nextElementSibling; return !!(n && n.matches('details.sm-code, .sm-code')); }),
};
'''

OPEN = '''
(async (y, effects, options, extra) => {
  const t = SM.app.current; const P = SM.platforms.get('fitmodel');
  const col = (n) => { const c = t.col(n); if (!c) throw new Error('no column ' + n); return c; };
  const eff = effects.map(e => ({ cols: e.names.map(n => col(n).id), names: e.names, nest: (e.nest || []).map(n => col(n).id), nestNames: e.nest || [], random: !!e.random, ...(e.rc ? { rc: e.rc } : {}) }));
  const roles = { y: (Array.isArray(y) ? y : [y]).map(n => col(n).id) };
  for (const [k, v] of Object.entries(extra || {})) roles[k] = v.map(n => col(n).id);
  const rep = SM.app.openReport(P, { roles, options: options || {}, effects: eff }, t);
  await new Promise(res => rep.on('done', res));
  return __mx.state(rep);
})
'''

# Tables made in the page (SM.util.rng): a balanced split plot, a one-way design with a negative variance
# component, batches over time (random coefficients), repeated measures, a spatial field, a binomial response.
TABLES = r'''
window.__mxTables = {
  split() { const r = SM.util.rng('mixed-ui-split'); const blk = [], A = [], B = [], y = [];
    const u = Array.from({ length: 6 }, () => r.normal(0, 1)), w = Array.from({ length: 18 }, () => r.normal(0, 0.8));
    for (let b = 0; b < 6; b++) for (let a = 0; a < 3; a++) for (let c = 0; c < 4; c++) { blk.push('b' + b); A.push('a' + a); B.push('c' + c); y.push(+(20 + 0.6 * a + 0.3 * (c === 1) + u[b] + w[b * 3 + a] + r.normal(0, 1)).toFixed(4)); }
    const t = new SM.Table({ name: 'Split plot', source: 'simulated', columns: [{ name: 'blk', dataType: 'character', values: blk }, { name: 'A', dataType: 'character', values: A },
      { name: 'B', dataType: 'character', values: B }, { name: 'y', dataType: 'numeric', values: y }] }); SM.app.addTable(t); return t.nrows; },
  negative() { for (let s = 0; s < 400; s++) { const r = SM.util.rng('mixed-ui-neg-' + s); const g = [], y = [];
      const u = Array.from({ length: 8 }, () => r.normal(0, 0.2));
      for (let i = 0; i < 8; i++) for (let j = 0; j < 5; j++) { g.push('G' + i); y.push(+(3 + u[i] + r.normal(0, 1)).toFixed(5)); }
      const m = Array.from({ length: 8 }, (_, i) => y.slice(i * 5, i * 5 + 5).reduce((a, b) => a + b) / 5), gm = y.reduce((a, b) => a + b) / 40;
      const msb = 5 * m.reduce((a, v) => a + (v - gm) ** 2, 0) / 7, mse = y.reduce((a, v, k) => a + (v - m[Math.floor(k / 5)]) ** 2, 0) / 32;
      if (msb < mse) { const t = new SM.Table({ name: 'Negative component', source: 'simulated', columns: [{ name: 'g', dataType: 'character', values: g }, { name: 'y', dataType: 'numeric', values: y }] }); SM.app.addTable(t); return { msb, mse }; } }
    return null; },
  batches() { const r = SM.util.rng('mixed-ui-rc'); const b = [], x = [], y = [];
    for (let i = 0; i < 10; i++) { const u0 = r.normal(0, 1.4), u1 = -0.2 * u0 + r.normal(0, 0.4); for (let j = 0; j < 6; j++) { const xv = j * 3; b.push('batch' + i); x.push(xv); y.push(+(100 + u0 - (0.5 + u1) * xv / 3 + r.normal(0, 0.6)).toFixed(4)); } }
    const t = new SM.Table({ name: 'Batches', source: 'simulated', columns: [{ name: 'batch', dataType: 'character', values: b }, { name: 'month', dataType: 'numeric', values: x },
      { name: 'strength', dataType: 'numeric', values: y }] }); SM.app.addTable(t); return t.nrows; },
  repeated() { const r = SM.util.rng('mixed-ui-rep'); const p = [], d = [], h = [], hr = [], y = [];
    for (let i = 0; i < 18; i++) { const drug = ['A', 'C', 'P'][i % 3]; let e = r.normal(0, 1); for (let j = 0; j < 5; j++) { e = 0.7 * e + r.normal(0, 0.7); p.push('p' + i); d.push(drug); h.push('h' + (j + 1)); hr.push(j + 1); y.push(+(3 + (drug === 'C') * 0.4 - 0.05 * j + e).toFixed(4)); } }
    const t = new SM.Table({ name: 'Repeated', source: 'simulated', columns: [{ name: 'patient', dataType: 'character', values: p }, { name: 'drug', dataType: 'character', values: d },
      { name: 'hour', dataType: 'character', values: h, valueOrder: ['h1', 'h2', 'h3', 'h4', 'h5'] }, { name: 'hours', dataType: 'numeric', values: hr }, { name: 'fev', dataType: 'numeric', values: y }] }); SM.app.addTable(t); return t.nrows; },
  spatial() { const r = SM.util.rng('mixed-ui-sp'); const n = 49, e = [], nn = [], s = [], y = [];
    for (let i = 0; i < 7; i++) for (let j = 0; j < 7; j++) { e.push(i * 1.5); nn.push(j * 1.5); s.push(+(r.u() * 5).toFixed(3)); }
    const z = Array.from({ length: n }, () => r.normal(0, 1)), L = [];
    for (let i = 0; i < n; i++) { let v = 0; for (let k = 0; k < n; k++) { const dd = Math.hypot(e[i] - e[k], nn[i] - nn[k]); v += Math.exp(-dd / 2) * z[k] / 3; } L.push(v); }
    for (let i = 0; i < n; i++) y.push(+(1 - 0.3 * s[i] + L[i] + r.normal(0, 0.3)).toFixed(4));
    const t = new SM.Table({ name: 'Field', source: 'simulated', columns: [{ name: 'east', dataType: 'numeric', values: e }, { name: 'north', dataType: 'numeric', values: nn },
      { name: 'salt', dataType: 'numeric', values: s }, { name: 'logt', dataType: 'numeric', values: y }] }); SM.app.addTable(t); return t.nrows; },
  binomial() { const r = SM.util.rng('mixed-ui-glmm'); const blk = [], trt = [], ev = [], nt = [], ok = [];
    for (let b = 0; b < 12; b++) { const u = r.normal(0, 0.7); for (let k = 0; k < 3; k++) { const eta = -0.3 + 0.5 * k + u; const p0 = 1 / (1 + Math.exp(-eta)); let e = 0; for (let i = 0; i < 20; i++) e += r.u() < p0 ? 1 : 0;
      blk.push('B' + b); trt.push('t' + k); ev.push(e); nt.push(20); ok.push(r.u() < p0 ? 'yes' : 'no'); } }
    const t = new SM.Table({ name: 'Binomial', source: 'simulated', columns: [{ name: 'block', dataType: 'character', values: blk }, { name: 'trt', dataType: 'character', values: trt },
      { name: 'events', dataType: 'numeric', values: ev }, { name: 'trials', dataType: 'numeric', values: nt }, { name: 'mated', dataType: 'character', values: ok, valueOrder: ['yes', 'no'] }] }); SM.app.addTable(t); return t.nrows; },
};
'''

# the exact split-plot F tests from the table (balanced): MS_A / MS_wholeplot and MS_B / MSE
EXACT = '''(() => {
  const t = SM.app.current; const blk = t.col('blk').values, A = t.col('A').values, B = t.col('B').values, y = t.col('y').values;
  const lv = (v) => [...new Set(v)]; const bl = lv(blk), al = lv(A), cl = lv(B); const nb = bl.length, na = al.length, nc = cl.length;
  const mean = (f) => { let s = 0, k = 0; y.forEach((v, i) => { if (f(i)) { s += v; k++; } }); return s / k; };
  const gm = mean(() => true);
  const mA = al.map((a) => mean((i) => A[i] === a)), mB = cl.map((c) => mean((i) => B[i] === c)), mb = bl.map((b) => mean((i) => blk[i] === b));
  const mba = bl.map((b) => al.map((a) => mean((i) => blk[i] === b && A[i] === a)));
  const mab = al.map((a) => cl.map((c) => mean((i) => A[i] === a && B[i] === c)));
  const ssA = nb * nc * mA.reduce((s, v) => s + (v - gm) ** 2, 0), ssB = nb * na * mB.reduce((s, v) => s + (v - gm) ** 2, 0);
  let ssWP = 0; bl.forEach((b, i) => al.forEach((a, j) => { ssWP += nc * (mba[i][j] - mb[i] - mA[j] + gm) ** 2; }));
  let ssAB = 0; al.forEach((a, j) => cl.forEach((c, k) => { ssAB += nb * (mab[j][k] - mA[j] - mB[k] + gm) ** 2; }));
  let sst = 0; y.forEach((v) => { sst += (v - gm) ** 2; });
  const ssBlk = na * nc * mb.reduce((s, v) => s + (v - gm) ** 2, 0);
  const sse = sst - ssA - ssB - ssAB - ssWP - ssBlk;
  const dfWP = (nb - 1) * (na - 1), dfE = na * nb * nc - 1 - (na - 1) - (nc - 1) - (na - 1) * (nc - 1) - (nb - 1) - dfWP;
  return { FA: (ssA / (na - 1)) / (ssWP / dfWP), dfWP, FB: (ssB / (nc - 1)) / (sse / dfE), dfE };
})()'''


def open_js(y, effects, options=None, extra=None):
    return f'({OPEN})({json.dumps(y)}, {json.dumps(effects)}, {json.dumps(options or {})}, {json.dumps(extra or {})})'


def E(*effects):
    return [{'names': e} if isinstance(e, list) else e for e in effects]


SPLIT = E(['A'], ['B'], ['A', 'B'], {'names': ['blk'], 'random': True}, {'names': ['blk', 'A'], 'random': True})


async def main():
    page = await open_page(f'{BASE}/smui.html')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "mixed" || f.module === "fit_model").map(f => f.error)')
    check('mixed and fit_model import in Pyodide', failed, [])
    names = await page.ev('SM.engine.names.filter(n => n.startsWith("mixed.") || n === "fitmodel.mixed" || n.startsWith("mixedcond.")).sort()')
    for nm in ('fitmodel.mixed', 'mixed.lsmeans', 'mixed.compare', 'mixed.contrast', 'mixed.slices', 'mixed.save', 'mixed.structures', 'mixed.variogram',
               'mixed.simulate', 'mixed.power', 'mixed.skeleton', 'mixed.profile_ci', 'mixed.lrt', 'mixedcond.profile'):
        check(f'the engine has {nm}', nm in names, True)
    await page.ev(HELPERS)
    await page.ev(TABLES)
    check('the split-plot table', await page.ev('__mxTables.split()'), 72)

    # ---- the launch dialog by clicks: the Mixed Model's own controls and roles
    r = await page.ev('''(async () => {
      SM.app.launch('fitmodel'); await new Promise(r => setTimeout(r, 300));
      const out = {};
      __mx.pick('y'); __mx.role('Y'); await __mx.tick();
      __mx.pick('A', 'B'); __mx.btn('Macros ▾'); await __mx.tick(); await __mx.menuItem('Full Factorial');
      __mx.pick('blk'); __mx.btn('Add'); __mx.selEff(3); __mx.pick('A'); __mx.btn('Cross');
      __mx.selEff(3); __mx.btn('Attributes ▾'); await __mx.tick(); await __mx.menuItem('Random Effect');
      __mx.selEff(4); __mx.btn('Attributes ▾'); await __mx.tick(); await __mx.menuItem('Random Effect');
      out.effects = __mx.effects();
      out.slsUnb = __mx.labelShown('Unbounded Variance Components');
      out.slsStruct = __mx.labelShown('Repeated Structure');
      __mx.sel('Personality', 'mixed'); await __mx.tick();
      out.unb = __mx.labelShown('Unbounded Variance Components');
      out.unbChecked = __mx.dlg().querySelector('input[aria-label="Unbounded Variance Components"]').checked;
      out.struct = __mx.labelShown('Repeated Structure');
      out.repRole = __mx.roleShown('Repeated');
      __mx.sel('Repeated Structure', 'un'); await __mx.tick();
      out.repRoleUN = __mx.roleShown('Repeated'); out.subRoleUN = __mx.roleShown('Subject');
      __mx.sel('Repeated Structure', 'sp'); await __mx.tick();
      out.type = __mx.labelShown('Type');
      __mx.sel('Repeated Structure', 'residual'); await __mx.tick();
      out.repRoleBack = __mx.roleShown('Repeated');
      __mx.btn('OK');
      const rep = __mx.rep(); await __mx.done(rep);
      out.state = __mx.state(rep);
      out.opts = { unb: rep.spec.options.mxUnbounded, ddfm: rep.spec.options.mxDdfm, st: rep.spec.options.mxStructure };
      return out;
    })()''')
    check('the dialog builds the split plot, the random effects marked', r['effects'], ['A', 'B', 'A*B', 'blk&Random', 'blk*A&Random'])
    check('Standard Least Squares with random effects: Unbounded Variance Components, no Repeated Structure', (r['slsUnb'], r['slsStruct']), (True, False))
    check('Mixed Model: Unbounded Variance Components, on by default (JMP\'s)', (r['unb'], r['unbChecked']), (True, True))
    check('Mixed Model: the Repeated Structure, the Repeated role hidden with Residual', (r['struct'], r['repRole']), (True, False))
    check('Unstructured: the Repeated and Subject roles shown', (r['repRoleUN'], r['subRoleUN']), (True, True))
    check('a spatial structure: its Type shown', r['type'], True)
    check('back to Residual: the Repeated role hidden', r['repRoleBack'], False)
    check('the report: Fit Mixed', r['state']['title'], 'Fit Mixed')
    for o in ['Fit Statistics', 'Random Effects Covariance Parameter Estimates', 'Fixed Effects Parameter Estimates', 'Fixed Effects Tests', 'Actual by Predicted Plot', 'Actual by Conditional Predicted Plot']:
        check(f'Mixed Model outline {o}', o in r['state']['outlines'], True)
    check('no errors', r['state']['errors'], [])
    check('the spec keeps the mixed options', r['opts'], {'unb': True, 'ddfm': 'kr', 'st': 'residual'})
    ex = await page.ev(EXACT)
    tests = await page.ev('__mx.table("Fixed Effects Tests")')
    row = {t[0]: t for t in tests[1:]}
    hdr = tests[0]
    fA, dA = float(row['A'][hdr.index('F Ratio')]), float(row['A'][hdr.index('DFDen')])
    check('Kenward-Roger: the whole-plot F = MS_A / MS_wholeplot computed in the page', abs(fA - ex['FA']) < 1e-4 * max(1, ex['FA']), True)
    check('... its DFDen = the whole-plot error df', abs(dA - ex['dfWP']) < 0.006, True)
    fB = float(row['B'][hdr.index('F Ratio')])
    check('... and the split-plot F = MS_B / MSE', abs(fB - ex['FB']) < 1e-4 * max(1, ex['FB']), True)
    check('every graph has its code block after it', all(await page.ev('__mx.graphsWithCode()')), True)
    await shot(page, 'mx-01-mixed.png')

    # ---- Unbounded Variance Components: a negative component; off, on the boundary with a note
    neg = await page.ev('__mxTables.negative()')
    check('a one-way table whose ANOVA component is negative', neg is not None, True)
    r = await page.ev(open_js('y', E({'names': ['g'], 'random': True}), {'personality': 'mixed'}))
    vc = await page.ev('__mx.table("Random Effects Covariance Parameter Estimates")')
    est = {row[0]: row for row in vc[1:]}
    ei = vc[0].index('Estimate')
    g_est = float(est['g'][ei].replace('−', '-'))
    check('unbounded: the component = (MSB - MSE)/n, below zero', abs(g_est - (neg['msb'] - neg['mse']) / 5) < 1e-5 * max(1, abs(g_est)) and g_est < 0, True)
    check('unbounded: a Wald p-Value column', 'Wald p-Value' in vc[0], True)
    check('a note says the estimate is negative', any('negative' in n for n in r['notes']), True)
    r = await page.ev(open_js('y', E({'names': ['g'], 'random': True}), {'personality': 'mixed', 'mxUnbounded': False}))
    vc = await page.ev('__mx.table("Random Effects Covariance Parameter Estimates")')
    est = {row[0]: row for row in vc[1:]}
    check('bounded: the component is 0 on the boundary', float(est['g'][vc[0].index('Estimate')]), 0.0)
    check('bounded: no Wald p-Value column', 'Wald p-Value' in vc[0], False)
    check('bounded: a note says it is on the boundary', any('boundary' in n for n in r['notes']), True)

    # ---- Standard Least Squares with random effects: JMP's REML report, Effect Details, slices, the LSMeans Plot
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Split plot")))')
    await asyncio.sleep(0.3)
    r = await page.ev(open_js('y', SPLIT, {'personality': 'standard'}))
    for o in ['Summary of Fit', 'Parameter Estimates', 'REML Variance Component Estimates', 'Fixed Effect Tests', 'Effect Details', 'A', 'B', 'A*B', 'Actual by Predicted Plot', 'Residual by Predicted Plot']:
        check(f'Standard Least Squares with random effects: outline {o}', o in r['outlines'], True)
    check('no errors', r['errors'], [])
    sof = await page.ev('__mx.kv("Summary of Fit")')
    check('Summary of Fit: JMP\'s rows', sorted(sof), sorted(['RSquare', 'RSquare Adj', 'Root Mean Square Error', 'Mean of Response', 'Observations (or Sum Wgts)']))
    vcr = await page.ev('__mx.table("REML Variance Component Estimates")')
    check('REML Variance Component Estimates: JMP\'s columns', vcr[0][:3], ['Random Effect', 'Var Ratio', 'Var Component'])
    rmse = float(sof['Root Mean Square Error'])
    resid = float({row[0]: row for row in vcr[1:]}['Residual'][2])
    check('Root Mean Square Error = sqrt of the residual component', abs(rmse ** 2 - resid) < 1e-4, True)
    r = await page.ev('''(async () => { const rep = __mx.rep(); const d = __mx.done(rep);
      await __mx.obMenu('A*B', 'Test Slices'); await d; await __mx.idle();
      const d2 = __mx.done(rep); await __mx.obMenu('A', 'LSMeans Tukey HSD'); await d2; await __mx.idle();
      const d3 = __mx.done(rep); await __mx.obMenu('A*B', 'LSMeans Plot'); await d3; await __mx.idle();
      return { state: __mx.state(rep), slices: __mx.table('Test Slices: A*B'), letters: __mx.table('Connecting Letters Report') }; })()''')
    check('Test Slices of A*B: a row per level of A and of B', len(r['slices']) - 1, 3 + 4)
    check('Tukey HSD of A: connecting letters for the three levels', len(r['letters']) - 1, 3)
    for o in ['Test Slices: A*B', 'LSMeans Differences Tukey HSD', 'Least Squares Means Plot']:
        check(f'Effect Details: {o}', o in r['state']['outlines'], True)
    check('no errors', r['state']['errors'], [])
    ov = await page.ev('''(async () => { const rep = __mx.rep(); const plot = __mx.outline('Least Squares Means Plot');
      const before = rep.plots.find(p => plot.contains(p.box)); const names0 = before.traces ? before.traces.map(t => t.name) : null;
      const d = __mx.done(rep); await __mx.obMenu('Least Squares Means Plot', 'Overlay', 'A'); await d; await __mx.idle();
      const after = rep.plots.find(p => __mx.outline('Least Squares Means Plot').contains(p.box));
      const d2 = __mx.done(rep); await __mx.obMenu('Least Squares Means Plot', 'Show Confidence Limits'); await d2; await __mx.idle();
      const again = rep.plots.find(p => __mx.outline('Least Squares Means Plot').contains(p.box));
      return { n0: names0 && names0.length, n1: after.traces.length, ci: again.traces[0].error_y.visible }; })()''')
    check('the LSMeans Plot of A*B: an overlay line per level of B, then of A', (ov['n0'], ov['n1']), (4, 3))
    check('... Show Confidence Limits turns the intervals off', ov['ci'], False)
    check('every graph has its code block after it', all(await page.ev('__mx.graphsWithCode()')), True)
    await shot(page, 'mx-02-sls.png')

    # ---- the Mixed Model's Multiple Comparisons dialog (the red triangle)
    r = await page.ev(open_js('y', SPLIT, {'personality': 'mixed'}))
    r = await page.ev('''(async () => { const rep = __mx.rep();
      await __mx.topMenu('Multiple Comparisons…'); await __mx.tick();
      const f = __mx.form(); const sel = f.querySelector('select'); sel.value = 'A'; sel.dispatchEvent(new Event('change'));
      const d = __mx.done(rep); __mx.btn('OK', f); await d; await __mx.idle();
      return { state: __mx.state(rep), ordered: __mx.table('Ordered Differences Report') }; })()''')
    for o in ['Multiple Comparisons for A', 'Least Squares Means Plot', 'LSMeans Differences Tukey HSD', 'Connecting Letters Report', 'Ordered Differences Report']:
        check(f'Multiple Comparisons: {o}', o in r['state']['outlines'], True)
    check('Ordered Differences: three pairs, with their DFDen', (len(r['ordered']) - 1, 'DFDen' in r['ordered'][0]), (3, True))

    # ---- random coefficients: Attributes > Nest Random Coefficients by clicks, the Random Coefficients report
    await page.ev('__mxTables.batches()')
    r = await page.ev('''(async () => {
      SM.app.launch('fitmodel'); await new Promise(r => setTimeout(r, 300));
      __mx.pick('strength'); __mx.role('Y'); await __mx.tick();
      __mx.pick('month'); __mx.btn('Add');
      __mx.sel('Personality', 'mixed'); await __mx.tick();
      __mx.selEff(0); __mx.pick('batch');
      __mx.btn('Attributes ▾'); await __mx.tick(); await __mx.menuItem('Nest Random Coefficients');
      const eff = __mx.effects();
      __mx.btn('OK'); const rep = __mx.rep(); await __mx.done(rep); await __mx.idle();
      return { eff, state: __mx.state(rep), vc: __mx.table('Random Effects Covariance Parameter Estimates'), rc: __mx.table('Random Coefficients') }; })()''')
    check('Nest Random Coefficients: the intercept and the slope per batch, one group', r['eff'], ['month', 'batch&Random Coefficients(1)', 'month[batch]&Random Coefficients(1)'])
    check('the covariance parameters of the random coefficients', [row[0] for row in r['vc'][1:]], ['Var(Intercept)', 'Cov(month,Intercept)', 'Var(month)', 'Residual'])
    check('... with their subject', r['vc'][0][1] == 'Subject' and r['vc'][1][1] == 'batch', True)
    check('Random Coefficients: a row per batch, a column per coefficient', (len(r['rc']) - 1, r['rc'][0][1:]), (10, ['Intercept', 'month']))
    check('no errors', r['state']['errors'], [])

    # ---- a repeated structure: AR(1) (a continuous time), its table and variogram; Compare Structures; Unstructured's diagnostics
    await page.ev('__mxTables.repeated()')
    r = await page.ev(open_js('fev', E(['drug'], ['hour'], ['drug', 'hour']), {'personality': 'mixed', 'mxStructure': 'ar1'}, {'repeated': ['hours'], 'subject': ['patient']}))
    for o in ['Fit Statistics', 'Repeated Effects Covariance Parameter Estimates', 'Fixed Effects Tests', 'Variogram']:
        check(f'AR(1): outline {o}', o in r['outlines'], True)
    check('AR(1): no errors', r['errors'], [])
    rep_t = await page.ev('__mx.table("Repeated Effects Covariance Parameter Estimates")')
    check('AR(1): its parameters', [row[0] for row in rep_t[1:]], ['AR(1) hours', 'Residual'])
    rho = float(rep_t[1][2])
    check('AR(1): the correlation is near the simulated 0.7', 0.4 < rho < 0.9, True)
    r = await page.ev('''(async () => { const rep = __mx.rep(); const d = __mx.done(rep);
      await __mx.topMenu('Compare Structures'); await d; await __mx.idle();
      return { state: __mx.state(rep), cs: __mx.table('Compare Structures') }; })()''')
    check('Compare Structures: the structures fitted', len(r['cs']) - 1 >= 4, True)
    check('... one marked as this report', any('this report' in row[-1] or 'this report' in ' '.join(row) for row in r['cs'][1:]), True)
    r = await page.ev(open_js('fev', E(['drug'], ['hour'], ['drug', 'hour']), {'personality': 'mixed', 'mxStructure': 'un', 'rmdiag': True}, {'repeated': ['hour'], 'subject': ['patient']}))
    check('Unstructured: J(J+1)/2 = 15 parameters', len(await page.ev('__mx.table("Repeated Effects Covariance Parameter Estimates")')) - 1, 15)
    r = await page.ev('''(async () => { const rep = __mx.rep(); const y = rep.table.col(rep.spec.roles.y[0]).id; const d = __mx.done(rep);
      rep.spec.options[y + '|rmdiag'] = true; rep.run(); await d; await __mx.idle();
      return { state: __mx.state(rep), cov: __mx.table('Repeated Measures Covariance Diagnostics', 0), heat: rep.plots.some(p => p.traces && p.traces[0] && p.traces[0].type === 'heatmap') }; })()''')
    check('Repeated Measures Covariance Diagnostics: the 5 x 5 covariance matrix', (len(r['cov']) - 1, len(r['cov'][0]) - 1), (5, 5))
    check('... and the correlation heat map', r['heat'], True)
    check('every graph has its code block after it', all(await page.ev('__mx.graphsWithCode()')), True)

    # ---- a spatial structure's variogram
    await page.ev('__mxTables.spatial()')
    r = await page.ev(open_js('logt', E(['salt']), {'personality': 'mixed', 'mxStructure': 'spn', 'mxSptype': 'exp'}, {'repeated': ['east', 'north']}))
    check('spatial: no errors', r['errors'], [])
    check('spatial: the variogram', 'Variogram' in r['outlines'], True)
    rt = await page.ev('__mx.table("Repeated Effects Covariance Parameter Estimates")')
    check('spatial: the range, the nugget and the residual (partial sill)', [row[0] for row in rt[1:]], ['Spatial Exponential', 'Nugget', 'Residual'])
    r = await page.ev('''(async () => { const rep = __mx.rep(); const d = __mx.done(rep);
      await __mx.obMenu('Variogram', 'Spatial Gaussian'); await d; await __mx.idle();
      const p = rep.plots.find(x => __mx.outline('Variogram').contains(x.box));
      return { curves: p.traces.map(t => t.name) }; })()''')
    check('the variogram: the empirical points, the fitted curve, a curve added from its red triangle', r['curves'][0] == 'Empirical' and 'Gaussian' in r['curves'], True)
    check('every graph has its code block after it', all(await page.ev('__mx.graphsWithCode()')), True)
    await shot(page, 'mx-03-spatial.png')

    # ---- a generalized linear mixed model: binomial events of trials, a random block
    await page.ev('__mxTables.binomial()')
    r = await page.ev(open_js(['events', 'trials'], E(['trt'], {'names': ['block'], 'random': True}), {'personality': 'glm', 'dist': 'binomial'}))
    check('GLMM: no errors', r['errors'], [])
    for o in ['Fit Statistics', 'Random Effects Covariance Parameter Estimates', 'Fixed Effects Parameter Estimates', 'Fixed Effects Tests']:
        check(f'GLMM: outline {o}', o in r['outlines'], True)
    fs = await page.ev('__mx.kv("Fit Statistics")')
    check('GLMM: the pseudo-likelihood and the generalized chi-square', ('-2 Residual Log Pseudo Likelihood' in fs, 'Gener. Chi-Square / DF' in fs), (True, True))
    r = await page.ev('''(async () => { const rep = __mx.rep();
      await __mx.topMenu('Multiple Comparisons…'); await __mx.tick();
      const f = __mx.form(); const d = __mx.done(rep); __mx.btn('OK', f); await d; await __mx.idle();
      return { lsm: __mx.table('Multiple Comparisons for trt'), od: __mx.table('Ordered Differences Report') }; })()''')
    check('GLMM: the LS means with their mean (a probability) beside them', 'Mean' in r['lsm'][0], True)
    check('GLMM: the differences as odds ratios', 'Odds Ratio' in r['od'][0], True)
    r = await page.ev(open_js('mated', E(['trt'], {'names': ['block'], 'random': True}), {'personality': 'glm', 'dist': 'binomial', 'target': 'yes'}))
    check('GLMM: a two-level Y (binary) fits too', r['errors'], [])
    v = await page.ev('''(() => { const t = SM.app.current; const v = SM.platforms.get('fitmodel').launch.validate;
      const spec = (dist) => ({ roles: { y: [t.col('events').id] }, options: { personality: 'glm', dist }, effects: [{ cols: [t.col('trt').id] }, { cols: [t.col('block').id], random: true }] });
      return [v(spec('normal'), t), v(spec('gamma'), t), v(spec('poisson'), t)]; })()''')
    check('GLM with random effects: the normal points to Mixed Model', (v[0] or '').startswith('A normal response with random effects'), True)
    check('... the gamma is refused, the Poisson taken', ((v[1] or '').startswith('With random effects the Generalized Linear Model takes'), v[2]), (True, None))

    # ---- Save Columns: the conditional prediction formula = the report's conditional predictions
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Split plot")))')
    await asyncio.sleep(0.3)
    r = await page.ev(open_js('y', SPLIT, {'personality': 'mixed'}))
    r = await page.ev('''(async () => { const rep = __mx.rep(); const t = rep.table; const n0 = t.columns.length;
      await __mx.topMenu('Save Columns', 'Conditional Prediction Formula'); for (let i = 0; i < 100 && t.columns.length === n0; i++) await new Promise(r => setTimeout(r, 50));
      const c = t.columns[t.columns.length - 1];
      const res = [...rep.cache.values()].map(v => v && v.diag).find(Boolean) || null;
      const n1 = t.columns.length;
      await __mx.topMenu('Save Columns', 'Save Simulation Formula'); for (let i = 0; i < 100 && t.columns.length === n1; i++) await new Promise(r => setTimeout(r, 50));
      const sim = t.columns[t.columns.length - 1];
      return { name: c.name, formula: !!c.formula, values: c.values.slice(0, 72), sim: sim.name, simFormula: !!sim.formula, simVals: sim.values.slice(0, 5) }; })()''')
    check('Save Columns > Conditional Prediction Formula: a live formula column', (r['name'], r['formula']), ('Cond Pred Formula y', True))
    diag = await page.ev('''(async () => { const rep = __mx.rep(); const t = rep.table;
      const res = await SM.engine.call('fitmodel.mixed', { y: 'y', effects: rep.spec.effects.map(e => ({ names: e.names, nest: e.nestNames || [], random: e.random })), mixed: { unbounded: true, ddfm: 'kr', structure: 'residual' }, alpha: 0.05 }, t);
      return res.diag; })()''')
    got = r['values']
    want = diag['predicted']
    check('... its values = the report\'s conditional predictions', max(abs(a - b) for a, b in zip(got, want)) < 1e-9, True)
    check('Save Simulation Formula: a formula column of random draws', (r['sim'], r['simFormula'], all(isinstance(x, (int, float)) for x in r['simVals'])), ('y Simulation Formula', True, True))

    # ---- Simulate: the dialog, progress, the power table; Stop
    r = await page.ev('''(async () => { const rep = __mx.rep();
      await __mx.topMenu('Simulate…'); await __mx.tick();
      const f = __mx.form(); const inp = [...f.querySelectorAll('input')]; inp[0].value = '30';
      __mx.btn('OK', f); await __mx.tick();
      const prog = [...document.querySelectorAll('.sm-dialog')].pop().querySelector('progress');
      const shown = !!prog;
      for (let i = 0; i < 4800 && !__mx.outline('Simulated Power'); i++) await new Promise(r => setTimeout(r, 50));
      await __mx.idle();
      return { shown, state: __mx.state(rep), power: __mx.table('Simulated Power', 0), cover: __mx.table('Interval Coverage'), samples: __mx.kv('Simulate')['Samples'] }; })()''', timeout=600)
    check('Simulate: a progress dialog while it runs', r['shown'], True)
    check('Simulate: the Simulated Power and Interval Coverage reports', ('Simulated Power' in r['state']['outlines'], 'Interval Coverage' in r['state']['outlines']), (True, True))
    check('... 30 samples', r['samples'], '30')
    check('... a row per test and alpha (3 tests x 4 levels)', len(r['power']) - 1, 12)
    check('no errors', r['state']['errors'], [])
    r = await page.ev('''(async () => { const rep = __mx.rep();
      await __mx.topMenu('Simulate…'); await __mx.tick();
      const f = __mx.form(); const inp = [...f.querySelectorAll('input')]; inp[0].value = '2000';
      __mx.btn('OK', f); await __mx.tick();
      const dlg = [...document.querySelectorAll('.sm-dialog')].pop();
      const prog = dlg.querySelector('progress');
      for (let i = 0; i < 1200 && Number(prog.value) < 25; i++) await new Promise(r => setTimeout(r, 50));
      [...dlg.querySelectorAll('button')].find(b => b.textContent === 'Stop').click();
      for (let i = 0; i < 2400 && !(__mx.kv('Simulate') || {})['Stopped']; i++) await new Promise(r => setTimeout(r, 50));
      await __mx.idle();
      return __mx.kv('Simulate'); })()''', timeout=600)
    check('Stop ends the run with the samples done so far', (r.get('Stopped'), int(r.get('Samples', '0')) < 2000), ('yes', True))
    await shot(page, 'mx-04-simulate.png')

    # ---- By groups, a project, the Skeleton ANOVA
    r = await page.ev('''(async () => { const t = SM.app.current; const P = SM.platforms.get('fitmodel'); const col = (n) => t.col(n);
      const eff = [{ cols: [col('B').id], names: ['B'], nest: [], nestNames: [], random: false }, { cols: [col('blk').id], names: ['blk'], nest: [], nestNames: [], random: true }];
      const rep = SM.app.openReport(P, { roles: { y: [col('y').id], by: [col('A').id] }, options: { personality: 'mixed' }, effects: eff }, t);
      await __mx.done(rep); await __mx.idle();
      return { groups: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3')].filter(h => h.textContent.startsWith('Fit Mixed')).length, errors: __mx.state(rep).errors }; })()''')
    check('By: a report per level of A, no errors', (r['groups'] >= 3, r['errors']), (True, []))
    r = await page.ev(open_js('y', SPLIT, {'personality': 'mixed', 'mxDdfm': 'sat', 'skeleton': True}))
    r = await page.ev('''(async () => { const rep = __mx.rep(); const y = rep.table.col(rep.spec.roles.y[0]).id; const d = __mx.done(rep);
      rep.spec.options[y + '|skeleton'] = true; rep.run(); await d; await __mx.idle();
      return { sk: __mx.table('Skeleton ANOVA'), state: __mx.state(rep) }; })()''')
    check('Skeleton ANOVA: a row per source, the residual and the total', [row[0] for row in r['sk'][1:]], ['A', 'B', 'A*B', 'blk', 'blk*A', 'Residual', 'Total'])
    r = await page.ev('''(async () => {
      const t = SM.app.current;
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [__mx.rep().toJSON()] };
      const n = SM.app.reports.length;
      SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const rep = SM.app.reports[n]; await __mx.done(rep); await __mx.idle();
      SM.app.showTab(SM.app.tabOf(t));
      return { title: rep.title, errors: __mx.state(rep).errors, ddfm: rep.spec.options.mxDdfm, sk: !!__mx.outline('Skeleton ANOVA', rep) }; })()''')
    check('a project reopens the mixed report with its options (Satterthwaite, the Skeleton ANOVA)', (r['title'], r['errors'], r['ddfm'], r['sk']), ('Fit Mixed', [], 'sat', True))

    # ---- every graph's code, run in the page, draws the report's graph (points, lines, titles)
    await chart_code(page)

    # ---- a hostile table: names and values never become code in any mixed-model report
    await hostile(page)

    # ---- a long fit: its progress in the report's bar, and Stop (the engine restarts)
    await long_fit(page)

    # ---- a spatial range beyond the data, and the launch dialog's hint for a Validation column
    await wide_range_and_hint(page)

    # ---- the dark theme and phone width
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev('__mx.idle()')
    st = await page.ev('__mx.state(__mx.rep())')
    check('dark theme: no errors', st['errors'], [])
    await shot(page, 'mx-05-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 2, 'mobile': True}, session=page.sid)
    await asyncio.sleep(1.2)
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Split plot")))')
    await asyncio.sleep(0.3)
    r = await page.ev(open_js('y', SPLIT, {'personality': 'mixed'}))
    await asyncio.sleep(1.2)
    check('phone width: the report without errors', r['errors'], [])
    check('phone width: no horizontal page scroll', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, 'mx-06-phone.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    check('no script errors', page.errors, [])
    await page.close()


LONG = r'''(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const P = SM.platforms.get('fitmodel');
  const out = {};
  // a quick fit: no progress box at all (none shows in the first second)
  const ts = SM.app.tables.find((x) => x.name === 'Split plot');
  SM.app.showTab(SM.app.tabOf(ts));
  const col = (t, n) => t.col(n).id;
  let seen = false;
  const quick = SM.app.openReport(P, { roles: { y: [col(ts, 'y')] }, options: { personality: 'mixed' }, effects: [{ cols: [col(ts, 'A')], names: ['A'], nest: [], nestNames: [], random: false }, { cols: [col(ts, 'blk')], names: ['blk'], nest: [], nestNames: [], random: true }] }, ts);
  const mo = new MutationObserver(() => { if (quick.bar.querySelector('.sm-mx-progress')) seen = true; });
  mo.observe(quick.bar, { childList: true, subtree: true });
  await new Promise((res) => quick.on('done', res));
  mo.disconnect();
  out.quick = { seen, errors: [...quick.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent) };
  SM.app.closeReport(quick);
  // a field of 1500 points: a spatial structure with a nugget takes some seconds in the browser
  const r = SM.util.rng('mixed-ui-long');
  const e = [], no = [], x = [], y = [];
  for (let i = 0; i < 1500; i++) { e.push(+(r.u() * 30).toFixed(4)); no.push(+(r.u() * 30).toFixed(4)); x.push(+r.normal(0, 1).toFixed(4)); }
  const bumps = Array.from({ length: 30 }, () => [r.u() * 30, r.u() * 30, r.normal(0, 1)]);
  for (let i = 0; i < 1500; i++) { let f = 0; for (const [a, b, h] of bumps) f += h * Math.exp(-((e[i] - a) ** 2 + (no[i] - b) ** 2) / 16); y.push(+(1 + 0.5 * x[i] + f + r.normal(0, 0.5)).toFixed(4)); }
  const t = new SM.Table({ name: 'Large field', source: 'simulated', columns: [{ name: 'east', values: e }, { name: 'north', values: no }, { name: 'x', values: x }, { name: 'y', values: y }] });
  SM.app.addTable(t);
  const spec = { roles: { y: [col(t, 'y')], repeated: [col(t, 'east'), col(t, 'north')] }, options: { personality: 'mixed', mxStructure: 'spn', mxSptype: 'exp' }, effects: [{ cols: [col(t, 'x')], names: ['x'], nest: [], nestNames: [], random: false }] };
  const rep = SM.app.openReport(P, spec, t);
  let done = false;
  rep.on('done', () => { done = true; });
  const texts = [];
  for (let i = 0; i < 200 && !done; i++) {
    await sleep(100);
    const b = rep.bar.querySelector('.sm-mx-progress');
    if (b) { const tx = b.querySelector('[role="status"]').textContent; if (!texts.length || texts[texts.length - 1] !== tx) texts.push(tx); }
    if (texts.filter((tx) => /REML iteration/.test(tx)).length >= 2) break;
  }
  out.texts = texts;
  out.button = !!rep.bar.querySelector('.sm-mx-progress button');
  const restarts = SM.engine.restarts;
  rep.bar.querySelector('.sm-mx-progress button').click();
  for (let i = 0; i < 300 && !done; i++) await sleep(100);
  out.stopped = { done, warn: [...rep.body.querySelectorAll('.sm-ob-warn')].map((w) => w.textContent), errors: [...rep.body.querySelectorAll('.sm-ob-error')].map((w) => w.textContent),
    box: !!rep.bar.querySelector('.sm-mx-progress'), restarted: SM.engine.restarts === restarts + 1 };
  for (let i = 0; i < 600 && SM.engine.state !== 'ready'; i++) await sleep(100);
  out.engine = SM.engine.state;
  // Redo: the fit runs to its end
  done = false;
  rep.run();
  for (let i = 0; i < 1200 && !done; i++) await sleep(100);
  out.redo = { done, warn: [...rep.body.querySelectorAll('.sm-ob-warn')].map((w) => w.textContent).filter((w) => /Stopped/.test(w)), errors: [...rep.body.querySelectorAll('.sm-ob-error')].map((w) => w.textContent),
    box: !!rep.bar.querySelector('.sm-mx-progress'), outlines: [...rep.body.querySelectorAll('.sm-ob-head h3, .sm-ob-head h2')].map((h) => h.textContent) };
  SM.app.closeReport(rep);
  return out;
})()'''

HOSTILE = r'''(async (runs) => {
  // levels that carry a line of Python behind a line break, a closing quote, braces, a trailing backslash or triple quotes
  const G = ['a\nINJECTED_nl = 1\n#', 'b\rINJECTED_cr = 1\r#', 'c"+INJECTED_dq+"', "d'+INJECTED_sq+'"];
  const H = ['e\\', '{INJECTED_fs}'];
  const TM = ['lo\nINJECTED_ord = 1\n#', 'mid\x27\x27\x27+INJECTED_tq+\x27\x27\x27', 'hi\x22\x22\x22+INJECTED_tq2+\x22\x22\x22'];
  const B = ['yes\nINJECTED_resp = 1\n#', "no'+INJECTED_resp2+'"];
  const r = SM.util.rng('mixed-ui-hostile');
  const c = { g: [], h: [], s: [], tm: [], x: [], y: [], yb: [] };
  for (let si = 0; si < 16; si++) {
    const gi = si % 4, hi = Math.floor(si / 4) % 2, u = r.normal(0, 1);
    for (let k = 0; k < 3; k++) {
      const x = r.u() * 4, y = 10 + 0.5 * gi + hi + 0.4 * k + 0.6 * x + u + r.normal(0, 1);
      c.g.push(G[gi]); c.h.push(H[hi]); c.s.push(`s${si}\nINJECTED_subj = 1\n#`); c.tm.push(TM[k]); c.x.push(+x.toFixed(3)); c.y.push(+y.toFixed(4));
      c.yb.push(r.u() < 1 / (1 + Math.exp(-(y - 11.5))) ? B[0] : B[1]);
    }
  }
  const t = new SM.Table({ name: 'mixed hostile', source: 'simulated', columns: [
    { name: 'g', dataType: 'character', values: c.g }, { name: 'h', dataType: 'character', values: c.h }, { name: 's', dataType: 'character', values: c.s },
    { name: 'tm', dataType: 'character', values: c.tm, valueOrder: TM }, { name: 'x', values: c.x }, { name: 'y', values: c.y }, { name: 'yb', dataType: 'character', values: c.yb, valueOrder: B }] });
  SM.app.addTable(t); SM.app.showTab(SM.app.tabOf(t));
  const P = SM.platforms.get('fitmodel');
  const out = [];
  for (const run of runs) {
    const col = (n) => t.col(n);
    const eff = run.effects.map((e) => ({ cols: e.names.map((n) => col(n).id), names: e.names, nest: (e.nest || []).map((n) => col(n).id), nestNames: e.nest || [], random: !!e.random, ...(e.rc ? { rc: e.rc } : {}) }));
    const roles = {};
    for (const [k, v] of Object.entries(run.roles)) roles[k] = v.map((n) => col(n).id);
    const options = { ...run.options };
    if (options.target === 'B0') options.target = B[0];
    const rep = SM.app.openReport(P, { roles, options, effects: eff }, t);
    await new Promise((res) => rep.on('done', res));
    await __mx.idle();
    const blocks = [...rep.body.querySelectorAll('details.sm-code')].filter((d) => !d.closest('.sm-ob-error'))
      .map((d) => (d._code ? d._code.get() : (d.querySelector('pre code') || d.querySelector('pre') || {}).textContent || ''));
    out.push({ name: run.name, want: run.want, errors: __mx.state(rep).errors, outlines: __mx.state(rep).outlines, blocks, script: rep.pythonScript ? rep.pythonScript() : '' });
    SM.app.closeReport(rep);
  }
  return out;
})'''

HOSTILE_RUNS = [
    {'name': 'Mixed Model, unstructured repeated covariance',
     'roles': {'y': ['y'], 'repeated': ['tm'], 'subject': ['s']},
     'effects': [{'names': ['h']}, {'names': ['tm']}, {'names': ['h', 'tm']}, {'names': ['g'], 'random': True}],
     'options': {'personality': 'mixed', 'mxStructure': 'un', 'blups': True, 'rmdiag': True, 'indicator': True, 'skeleton': True, 'iters': True, 'covfe': True, 'corfe': True,
                 'covcp': True, 'profiler': True, 'condprof': True, 'resCond': True, 'resMarg': True, 'interaction': True, 'structures': True, 'profci': True,
                 'mc': [{'effect': 'h*tm', 'method': 'tukey', 'plot': True, 'slices': True}, {'effect': 'tm', 'method': 'student', 'plot': True}],
                 'mc:1:contrast': [[1, -1, 0]]},
     'want': ['Repeated Effects Covariance Parameter Estimates', 'Random Effects Predictions', 'Repeated Measures Covariance Diagnostics', 'Indicator Parameterization Estimates',
              'Skeleton ANOVA', 'Compare Structures', 'Profile Likelihood Intervals', 'Multiple Comparisons for h*tm', 'Test Slices: h*tm', 'Marginal Model Profiler', 'Conditional Profiler']},
    {'name': 'Standard Least Squares with random effects, a random slope',
     'roles': {'y': ['y']},
     'effects': [{'names': ['h']}, {'names': ['tm']}, {'names': ['h', 'tm']}, {'names': ['x']}, {'names': ['g'], 'random': True}, {'names': ['x'], 'nest': ['g'], 'random': True}],
     'options': {'personality': 'standard', 'blups': True, 'indicator': True, 'skeleton': True, 'profiler': True, 'condprof': True, 'contour': True, 'actCond': True,
                 'lsplot:h*tm': True, 'student:h': True, 'tukey:tm': True, 'slices:h*tm': True, 'contrast:tm': [[1, 0, -1]], 'covcp': True},
     'want': ['REML Variance Component Estimates', 'Random Effect Predictions', 'Effect Details', 'Least Squares Means Plot', 'Test Slices: h*tm', 'Indicator Parameterization Estimates',
              'Skeleton ANOVA', 'Prediction Profiler', 'Conditional Profiler']},
    {'name': 'Mixed Model, correlated random coefficients, AR(1)',
     'roles': {'y': ['y'], 'repeated': ['tm'], 'subject': ['s']},
     'effects': [{'names': ['x']}, {'names': ['h']}, {'names': ['g'], 'random': True, 'rc': 1}, {'names': ['x'], 'nest': ['g'], 'random': True, 'rc': 1}],
     'options': {'personality': 'mixed', 'mxStructure': 'ar1', 'blups': True, 'rcoef': True, 'variogram': True, 'mc': [{'effect': 'h', 'method': 'student', 'plot': True}]},
     'want': ['Random Coefficients', 'Random Effects Predictions', 'Variogram', 'Multiple Comparisons for h', 'Connecting Letters Report']},
    {'name': 'Generalized Linear Mixed Model, binomial',
     'roles': {'y': ['yb']},
     'effects': [{'names': ['h']}, {'names': ['tm']}, {'names': ['g'], 'random': True}],
     'options': {'personality': 'glm', 'dist': 'binomial', 'link': 'logit', 'target': 'B0', 'blups': True, 'indicator': True, 'profiler': True,
                 'mc': [{'effect': 'tm', 'method': 'tukey', 'plot': True}]},
     'want': ['Random Effects Predictions', 'Indicator Parameterization Estimates', 'Multiple Comparisons for tm', 'Marginal Model Profiler']},
]

FLAGS = ast.PyCF_ONLY_AST | ast.PyCF_ALLOW_TOP_LEVEL_AWAIT


def injected(code):
    """None when the code parses and no INJECTED_* name is code in it; else what is wrong."""
    lines = re.split(r'\r\n|\r|\n', code)
    try:
        tree = compile(code, '<block>', 'exec', flags=FLAGS)
    except SyntaxError as e:
        at = lines[e.lineno - 1] if e.lineno and 0 < e.lineno <= len(lines) else ''
        return f'does not parse: {e.msg} (line {e.lineno}: {at.strip()[:160]!r})'
    bad = sorted({(n.id, n.lineno) for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id.startswith('INJECTED_')}, key=lambda x: x[1])
    if bad:
        return 'code from the table: ' + '; '.join(f'{name} on line {ln}, after {lines[ln - 2].strip()[:150]!r}' for name, ln in bad[:2])
    return None


async def hostile(page):
    res = await page.ev(f'({HOSTILE})({json.dumps(HOSTILE_RUNS)})', timeout=1200)
    if isinstance(res, str):
        check('the hostile table: the reports', res, None)
        return
    for r in res:
        tag = f'hostile table, {r["name"]}'
        check(f'{tag}: no errors', r['errors'], [])
        found = []
        n = 0
        for k, code in enumerate(r['blocks'] + [r['script']]):
            if not code.strip():
                continue
            n += 1
            what = injected(code)
            if what:
                found.append(f'{"the script" if k == len(r["blocks"]) else f"block {k + 1}"}: {what}')
        check(f'{tag}: its {n} code blocks and script parse, and nothing from the table is code', found, [])
        check(f'{tag}: the parts asked for ran, with their code', (n >= 5, [o for o in r['want'] if o not in r['outlines']]), (True, []))


WIDE = r'''(async (cols) => {
  const t = new SM.Table({ name: 'Wide bumps', source: 'simulated', columns: Object.entries(cols).map(([name, values]) => ({ name, values })) });
  SM.app.addTable(t);
  SM.app.showTab(SM.app.tabOf(t));
  const P = SM.platforms.get('fitmodel');
  const rep = SM.app.openReport(P, { roles: { y: [t.col('y').id], repeated: [t.col('east').id, t.col('north').id] }, options: { personality: 'mixed', mxStructure: 'spn', mxSptype: 'exp' },
    effects: [{ cols: [t.col('x').id], names: ['x'], nest: [], nestNames: [], random: false }] }, t);
  await new Promise((res) => rep.on('done', res));
  const out = { warn: [...rep.body.querySelectorAll('.sm-ob-warn')].map((w) => w.textContent), errors: [...rep.body.querySelectorAll('.sm-ob-error')].map((w) => w.textContent) };
  SM.app.closeReport(rep);
  // the launch dialog: a Validation column with a random effect
  const ts = SM.app.tables.find((x) => x.name === 'Split plot');
  SM.app.showTab(SM.app.tabOf(ts));
  if (!ts.col('v')) ts.addColumn({ name: 'v', dataType: 'numeric', values: Array.from({ length: ts.nrows }, (_, i) => (i % 4 === 0 ? 1 : 0)) });
  SM.app.launch('fitmodel'); await new Promise((r) => setTimeout(r, 300));
  const msg = () => { const m = __mx.dlg().querySelector('.sm-launch-msg'); return { text: m.textContent, info: m.classList.contains('is-info') }; };
  __mx.pick('y'); __mx.role('Y'); await __mx.tick();
  __mx.pick('A'); __mx.btn('Add'); __mx.pick('blk'); __mx.btn('Add'); await __mx.tick();
  __mx.pick('v'); __mx.role('Validation'); await __mx.tick(); await new Promise((r) => setTimeout(r, 100));
  out.fixedOnly = msg();
  __mx.selEff(1); __mx.btn('Attributes ▾'); await __mx.tick(); await __mx.menuItem('Random Effect'); await new Promise((r) => setTimeout(r, 150));
  out.random = msg();
  __mx.selEff(1); __mx.btn('Remove'); await new Promise((r) => setTimeout(r, 150));
  out.removed = msg();
  __mx.btn('Cancel');
  return out;
})'''


async def wide_range_and_hint(page):
    import numpy as np
    rg = np.random.default_rng(3)
    n = 300
    e_, n_ = rg.uniform(0, 30, n), rg.uniform(0, 30, n)
    x_ = rg.normal(size=n)
    bs = [(rg.uniform(0, 30), rg.uniform(0, 30), rg.normal()) for _ in range(30)]
    y_ = 1 + 0.5 * x_ + sum(h * np.exp(-((e_ - a) ** 2 + (n_ - b) ** 2) / 16) for a, b, h in bs) + rg.normal(0, 0.5, n)
    cols = {'east': e_.round(4).tolist(), 'north': n_.round(4).tolist(), 'x': x_.round(4).tolist(), 'y': y_.round(4).tolist()}
    r = await page.ev(f'({WIDE})({json.dumps(cols)})', timeout=600)
    if isinstance(r, str):
        check('a range beyond the data: the checks ran', r, None)
        return
    inf = [w for w in r['warn'] if 'runs off to infinity' in w]
    check('a spatial range beyond the data: the report says so, and suggests the coordinates as fixed effects and Compare Structures',
          (len(inf), bool(inf) and 'add the coordinates (east and north) as fixed effects' in inf[0] and 'Compare Structures' in inf[0], r['errors']), (1, True, []))
    check('the launch dialog: a Validation column with fixed effects only, no hint', 'Validation role' in r['fixedOnly']['text'], False)
    check('... with a random effect: the hint that the column is not used', (r['random']['info'], 'v is in the Validation role' in r['random']['text']), (True, True))
    check('... the random effect taken out: the hint goes', 'Validation role' in r['removed']['text'], False)


async def long_fit(page):
    r = await page.ev(LONG, timeout=600)
    if isinstance(r, str):
        check('a long fit: the checks ran', r, None)
        return
    check('a quick fit shows no progress (none in its first second)', (r['quick']['seen'], r['quick']['errors']), (False, []))
    its = [t for t in r['texts'] if 'REML iteration' in t]
    check('a long fit: the report\'s bar shows the REML iteration and -2 Residual Log Likelihood, and a Stop button',
          (len(its) >= 2, all(re.search(r'REML iteration \d+, −2 Residual Log Likelihood [\d.]+', t) for t in its), r['button']), (True, True, True))
    n = [int(re.search(r'iteration (\d+)', t).group(1)) for t in its]
    check('... the iterations count up', n == sorted(n) and n[-1] > n[0], True)
    st = r['stopped']
    check('Stop: the engine restarted, the report says the fit was stopped (no error), the progress gone',
          (st['done'], st['restarted'], len(st['warn']) == 1 and st['warn'][0].startswith('Stopped at REML iteration'), st['errors'], st['box']), (True, True, True, [], False))
    check('... and the engine is ready again', r['engine'], 'ready')
    rd = r['redo']
    check('Redo after Stop: the fit runs to its end', (rd['done'], rd['warn'], rd['errors'], rd['box'], 'Repeated Effects Covariance Parameter Estimates' in rd['outlines']), (True, [], [], False, True))


def pts_of(ax, k=0):
    return [tuple(p) for p in (ax['scatter'][k]['xy'] if len(ax['scatter']) > k else [])]


async def chart_code(page):
    """The mixed reports' graphs against their code's figures: a graph of rows
    (the points, the reference lines, the titles), the LS means plot (the
    means), the variogram (the empirical semivariances and the fitted curve),
    the correlation heat map (its matrix)."""
    await page.ev(GRAPHS_JS)
    await page.ev('__gr.idle()')
    cases = [
        ('Split plot', 'y', SPLIT, {'personality': 'mixed', 'resMarg': True, 'resCond': True, 'mc': [{'effect': 'A*B', 'method': 'none', 'plot': True}]}, {}),
        ('Split plot', 'y', SPLIT, {'personality': 'standard', 'lsplot:A': True}, {}),
        ('Repeated', 'fev', E(['drug'], ['hour'], ['drug', 'hour']), {'personality': 'mixed', 'mxStructure': 'un'}, {'repeated': ['hour'], 'subject': ['patient']}),
        ('Field', 'logt', E(['salt']), {'personality': 'mixed', 'mxStructure': 'spn', 'mxSptype': 'exp'}, {'repeated': ['east', 'north']}),
    ]
    for tname, y, eff, opts, extra in cases:
        tbl = f'SM.app.tables.find(t => t.name === {json.dumps(tname)})'
        await page.ev(f'SM.app.showTab(SM.app.tabOf({tbl}))')
        await asyncio.sleep(0.3)
        o = dict(opts)
        scoped = {k: o.pop(k) for k in list(o) if k in ('resMarg', 'resCond', 'mc', 'lsplot:A')}
        if tname == 'Repeated':
            scoped['rmdiag'] = True
        r = await page.ev(open_js(y, eff, o, extra))
        if scoped:
            r = await page.ev(f'''(async (pairs) => {{ const rep = __mx.rep(); const yid = rep.table.col(rep.spec.roles.y[0]).id; const d = __mx.done(rep);
              for (const [k, v] of pairs) rep.spec.options[yid + '|' + k] = v; rep.run(); await d; await __mx.idle(); return __mx.state(rep); }})({json.dumps(list(scoped.items()))})''')
        label = f'{tname} ({opts.get("personality")}{", " + opts["mxStructure"] if "mxStructure" in opts else ""})'
        check(f'charts: {label}: no errors', r['errors'], [])
        gs = await page.ev('__gr.graphs(__mx.rep())')
        check(f'charts: {label}: every graph has its code right under it, ending in plt.show()', [g['label'] for g in gs if not (g['code'] and g['code'].rstrip().split('\n')[-1] == 'plt.show()')], [])
        for g in gs:
            F, err = await run_graph(page, g, tbl)
            lab = f'{label}: {g["label"]}'
            check(f'{lab}: the code runs in the page', err, None)
            if not F:
                continue
            F = F[0]
            ax = F['axes'][0]
            t = g['label']
            if t.endswith('LS means plot'):
                ys = sorted(round(v, 9) for x in g['traces'] for v in (x.get('y') or []))
                got = sorted(round(v, 9) for ln in ax['lines'] if ln['marker'] == 'o' for v in ln['y'])
                check(f'{lab}: the least squares means', got, ys)
            elif t.endswith('variogram'):
                emp = [x for x in g['traces'] if x.get('name') == 'Empirical'][0]
                pts = [ln for ln in ax['lines'] if ln['marker'] == 'o']
                check.near(f'{lab}: the empirical semivariances', maxdiff(pts[0]['y'] if pts else [], emp['y']), 0, 1e-8)
                fit = [x for x in g['traces'] if (x.get('name') or '').endswith('(the fit)')]
                if fit:
                    # (a spatial range is often poorly determined: the code's own REML agrees with the report's to about 1e-6)
                    check(f'{lab}: the fitted curve', find_line(ax, fit[0]['x'], fit[0]['y'], rel=2e-5, abs_=1e-8) is not None, True)
            elif t.endswith('heat map'):
                hm = [x for x in g['traces'] if x.get('type') == 'heatmap'][0]
                check.near(f'{lab}: the correlation matrix', maxdiff(ax['images'][0]['data'] if ax['images'] else [], [v for row in hm['z'] for v in row]), 0, 1e-6)
            else:
                rows = [x for x in g['traces'] if x.get('name') == 'Rows']
                if rows:
                    check.near(f'{lab}: the rows\' points', maxdiff([q for p in pts_of(ax) for q in p], [q for p in points_of(rows[0]) for q in p]), 0, 1e-6)
                for x in [x for x in g['traces'] if x.get('type') == 'scatter' and x.get('mode') == 'lines' and len(x.get('x') or []) > 1]:
                    check(f'{lab}: a line of {len(x["x"])} points', find_line(ax, x['x'], x['y'], rel=1e-6, abs_=1e-9) is not None, True)
            check(f'{lab}: the titles', (ax['xlabel'], ax['ylabel'], ax['title'] or F['suptitle']), (g['titles']['x'] or '', g['titles']['y'] or '', g['label']))
    check('charts: every graph drawn', await page.ev('__gr.take()'), [])


if __name__ == '__main__':
    asyncio.run(main())
    sys.exit(check.done())
