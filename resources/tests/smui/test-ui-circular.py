#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Specialized Modeling > Circular
Statistics.

The platform is in the menu after the others of Specialized Modeling; the
simulated wind example opens (and its truth shows in the numbers); the
launch dialog casts angles and chooses their units; the summary, the
Rayleigh and V tests, the circular-linear and circular-circular
correlations and the group means agree with the same statistics computed
here in the page's JavaScript from the table; the circular dot plot is
linked to the rows both ways and the rose diagram's bars hold every row;
the red triangles change the units (a 24-hour clock), add the V test, the
von Mises fit and the correlations of several angles, and save columns;
By, exclusion and Redo, a project, Bootstrap, the dark theme and phone
width work; every (i) has a topic; a large table stays quick; no script
errors.

Start a server on the repository root and headless Chrome (the recipe is in
README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-circular.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import math
import os
import sys
import time

from cdp import BASE, Checks, open_page, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


HELPERS = r'''
window.__ci = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  rep: () => SM.app.reports[SM.app.reports.length - 1],
  table(name) { return SM.app.tables.find((t) => t.name === name); },
  async open(tableName, roles, options) {
    const t = this.table(tableName);
    SM.app.showTab(SM.app.tabOf(t));
    const ids = {};
    for (const [k, names] of Object.entries(roles)) ids[k] = names.map((n) => { const c = t.col(n); if (!c) throw new Error('no column ' + n); return c.id; });
    const rep = SM.app.openReport(SM.platforms.get('circular'), { roles: ids, options: options || {} }, t);
    await new Promise((res) => rep.on('done', res));
    await this.sleep(300);
    return rep;
  },
  heads(rep) { return [...(rep || this.rep()).body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map((h) => h.textContent); },
  errors(rep) { return [...(rep || this.rep()).body.querySelectorAll('.sm-ob-error, .sm-ob-warn')].map((e) => e.textContent.slice(0, 400)); },
  head(title, rep, n = 0) { return [...(rep || this.rep()).body.querySelectorAll('.sm-ob-head')].filter((h) => h.querySelector('h2, h3, h4').textContent === title)[n]; },
  async pick(title, path, rep, n = 0) {
    rep = rep || this.rep();
    const h = this.head(title, rep, n);
    if (!h) throw new Error('no outline ' + title);
    const done = new Promise((res) => rep.on('done', res));
    h.querySelector('.sm-ob-menu').click();
    for (const label of path) {
      await this.sleep(60);
      const m = [...document.querySelectorAll('.sm-menu')].pop();
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
  tableUnder(title, n = 0, rep, k = 0) {
    const h = this.head(title, rep, k);
    if (!h) return null;
    const body = h.parentElement.querySelector(':scope > .sm-ob-body');
    const t = body.querySelectorAll(':scope > table.sm-rt, :scope > table.sm-kv, :scope > .sm-ob-row table')[n];
    return t ? [...t.querySelectorAll('tr')].map((tr) => [...tr.children].map((c) => c.textContent.trim())) : null;
  },
  kvOf(title, rep, n = 0) { const t = this.tableUnder(title, 0, rep, n); return t ? Object.fromEntries(t.map((r) => [r[0], this.num(r[1])])) : null; },
  num(s) { return SM.table.toNumber(String(s).replace(/−/g, '-').replace(/[<*]/g, '').replace(/°/g, '')); },
  // the circular mean, R̄ and circular SD of angles in units of period P, computed here
  circ(vals, P) {
    let C = 0, S = 0; for (const v of vals) { const a = 2 * Math.PI * v / P; C += Math.cos(a); S += Math.sin(a); }
    C /= vals.length; S /= vals.length; const R = Math.hypot(C, S);
    let m = Math.atan2(S, C); if (m < 0) m += 2 * Math.PI;
    return { mean: m * P / (2 * Math.PI), R, sd: Math.sqrt(-2 * Math.log(R)) * P / (2 * Math.PI), n: vals.length };
  },
  corr(a, b) { const n = a.length; const ma = a.reduce((x, y) => x + y, 0) / n, mb = b.reduce((x, y) => x + y, 0) / n; let sab = 0, saa = 0, sbb = 0;
    for (let i = 0; i < n; i++) { sab += (a[i] - ma) * (b[i] - mb); saa += (a[i] - ma) ** 2; sbb += (b[i] - mb) ** 2; } return sab / Math.sqrt(saa * sbb); },
  col(t, name, rows) { const v = t.col(name).values; return (rows || t.includedRows()).map((r) => v[r]); },
};
'''


async def main():
    page = await open_page(f'{BASE}/smui.html?example=wind')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.map(f => f.module + ": " + f.error)')
    check('circular imports', [f for f in failed if f.startswith('circular')], [])
    check('the backend names are there', await page.ev('["circular.summary", "circular.vonmises", "circular.linear", "circular.circular", "circular.groups"].every(n => SM.engine.has(n))'), True)
    await page.ev(HELPERS)
    num = lambda s: float(str(s).replace('−', '-').replace('°', ''))

    # ---- the menu and the example
    sub = await page.ev('(() => { const it = SM.app.menuItems("Analyze").find(i => i.label === "Specialized Modeling"); const s = typeof it.submenu === "function" ? it.submenu() : it.submenu; return s.map(i => i.label).filter(Boolean); })()')
    check('Specialized Modeling ends with Circular Statistics, after Gaussian Process', sub[-2:], ['Gaussian Process…', 'Circular Statistics…'])
    r = await page.ev('''(() => { const t = SM.app.current; return { name: t.name, n: t.nrows, cols: t.columns.map((c) => [c.name, c.modelingType]), ex: !!SM.io.EXAMPLES.wind, notes: t.notes }; })()''')
    check('?example=wind opens the simulated wind table', (r['name'], r['n'], r['ex']), ('Wind', 240, True))
    check('its columns', r['cols'], [['day', 'continuous'], ['season', 'nominal'], ['direction (°)', 'continuous'], ['speed (m/s)', 'continuous'], ['direction B (°)', 'continuous'], ['hour of peak gust', 'continuous']])
    check('its notes give the truth', all(s in r['notes'] for s in ('220°', '280°', 'κ = 2.5', '15:00')), True)
    r = await page.ev('(() => { const a = SM.io.example("wind"), b = SM.io.example("wind"); return JSON.stringify(a.col("direction (°)").values) === JSON.stringify(b.col("direction (°)").values); })()')
    check('the example is the same every time (seeded)', r, True)

    # ---- the launch dialog
    r = await page.ev('''(async () => {
      SM.app.launch('circular');
      await __ci.sleep(200);
      const dlg = document.querySelector('.sm-launch-dialog');
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map((b) => b.textContent);
      const selects = [...dlg.querySelectorAll('.sm-launch-opts select')].map((s) => [...s.options].map((o) => o.value));
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => items.find((li) => li.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      const btn = (label) => [...dlg.querySelectorAll('.sm-role .sm-btn')].find((b) => b.textContent === label);
      pick('direction (°)'); btn('Y, Angle').click();
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find((b) => b.textContent === 'OK').click();
      const rep = __ci.rep();
      await new Promise((res) => rep.on('done', res)); await __ci.sleep(500);
      return { roles, selects, title: rep.title, heads: __ci.heads(rep), plots: rep.plots.map((p) => p.traces[0].type), errors: __ci.errors(rep) };
    })()''')
    check('the roles', r['roles'], ['Y, Angle', 'X', 'Freq', 'By'])
    check('the units and the orientation to choose', r['selects'], [['degrees', 'radians', 'clock'], ['auto', 'compass', 'math']])
    check('the report', (r['title'], r['heads']), ('Circular Statistics', ['Circular Statistics', 'direction (°)', 'Summary Statistics', 'Confidence Intervals for the Mean Direction', 'Tests of Uniformity']))
    check('a circular dot plot and a rose diagram', r['plots'], ['scatter', 'barpolar'])
    check('no errors (the report)', r['errors'], [])

    # ---- the numbers against the page's own computations
    r = await page.ev('''(() => {
      const rep = __ci.rep(); const t = rep.table; const v = __ci.col(t, 'direction (°)');
      const c = __ci.circ(v, 360); const kv = __ci.kvOf('Summary Statistics', rep);
      const un = __ci.tableUnder('Tests of Uniformity', 0, rep); const ci = __ci.tableUnder('Confidence Intervals for the Mean Direction', 0, rep);
      return { c, kv, un, ci };
    })()''')
    kv, c = r['kv'], r['c']
    check('N', kv['N'], 240)
    check.near('the mean direction = the one computed in the page', kv['Mean Direction'], c['mean'], 1e-6)
    check.near('R̄ = the one computed in the page', kv['Mean Resultant Length (R̄)'], c['R'], 1e-6)
    check.near('circular variance 1 − R̄', kv['Circular Variance (1 − R̄)'], 1 - c['R'], 1e-5)
    check.near('circular SD √(−2 ln R̄), in degrees', kv['Circular Std Dev'], c['sd'], 1e-6)
    check.near('Rayleigh Z = nR̄² computed in the page', num(r['un'][1][1]), 240 * c['R'] ** 2, 1e-6)
    check('the truth: a mixture of 220° and 280° means about 250°', 235 < c['mean'] < 265, True)
    lo, hi = num(r['ci'][1][1]), num(r['ci'][1][2])
    check('the von Mises interval holds the mean direction', lo < c['mean'] < hi, True)
    check('the intervals: von Mises (Upton) and large-sample (Fisher)', [row[0] for row in r['ci'][1:]], ['von Mises (Upton 1986)', 'Any unimodal, large n (Fisher 1993)'])

    # ---- the graphs: every row in the rose; the dot plot linked both ways
    r = await page.ev('''(async () => {
      const rep = __ci.rep(); const t = rep.table;
      const dot = rep.plots[0], rose = rep.plots[1];
      const pts = dot.traces.findIndex((tr) => tr.mode === 'markers');
      const sq = rose.traces[0].r.reduce((a, b) => a + b * b, 0);
      dot._click({ points: [{ curveNumber: pts, pointNumber: 7 }], event: {} });
      const sel = t.selectedRows();
      t.select([3, 4, 5, 6]); await __ci.sleep(250);
      const sp = dot.box.data[pts].selectedpoints; t.select([]);
      const arrow = (dot.userLayout.annotations || []).filter((a) => a.showarrow).length;
      const polar = rose.userLayout.polar;
      return { rows: dot.rows[pts].length, sel, row: dot.rows[pts][7], sp: sp ? sp.length : null, sq, bins: rose.traces[0].r.length, arrow,
        dir: polar.angularaxis.direction, rot: polar.angularaxis.rotation, cart: !!rose.box.querySelector('.cartesianlayer .xy') };
    })()''')
    check('the dot plot has a point per row', r['rows'], 240)
    check('a click on a point selects its row', r['sel'], [r['row']])
    check('selected rows light up in the dot plot', r['sp'], 4)
    check.near('the rose\'s bars hold every row (radius √count: Σ r² = n)', r['sq'], 240, 1e-9)
    check('24 bins by default, clockwise from the top (a compass)', (r['bins'], r['dir'], r['rot']), (24, 'clockwise', 90))
    check('the mean vector is an arrow', r['arrow'], 1)
    check('the rose is polar only, no stray axes', r['cart'], False)
    r = await page.ev('''(async () => { const rep = __ci.rep(); await __ci.pick('Circular Statistics', ['Zero and Direction', 'Counterclockwise from the right (mathematical)'], rep);
      const t = rep.table; const v = t.col('direction (°)').values; const dot = rep.plots[0]; const pts = dot.traces.findIndex((tr) => tr.mode === 'markers');
      const k = dot.rows[pts].findIndex((row) => Math.abs(v[row] - 90) < 30);   // an angle near 90°: straight up in the mathematical orientation
      const out = { dir: rep.plots[1].userLayout.polar.angularaxis.direction, rot: rep.plots[1].userLayout.polar.angularaxis.rotation, x: dot.traces[pts].x[k], y: dot.traces[pts].y[k], v: v[dot.rows[pts][k]] };
      await __ci.pick('Circular Statistics', ['Zero and Direction', 'Automatic (clockwise from the top; radians counterclockwise from the right)'], rep); return out; })()''')
    check('Zero and Direction ▸ mathematical: the rose turns counterclockwise from the right', (r['dir'], r['rot']), ('counterclockwise', 0))
    check.near('and a point of the dot plot sits at (r cos θ, r sin θ)', math.atan2(r['y'], r['x']) * 180 / math.pi % 360, r['v'], 1e-6)
    r = await page.ev('''(async () => { const rep = __ci.rep(); await __ci.pick('direction (°)', ['Rose Area Proportional to Count'], rep);
      return rep.plots[1].traces[0].r.reduce((a, b) => a + b, 0); })()''')
    check.near('Rose Area Proportional to Count off: the radius is the count (Σ r = n)', r, 240, 1e-9)
    await shot(page, '01-report.png')

    # ---- V Test…, Fit von Mises, Save from the column's red triangle
    r = await page.ev('''(async () => {
      const rep = __ci.rep(); const t = rep.table;
      const p = __ci.pick('direction (°)', ['V Test…'], rep); await __ci.dialogOK((d) => { d.querySelector('input').value = '240'; }); await p;
      await __ci.pick('direction (°)', ['Fit von Mises'], rep);
      const v = __ci.col(t, 'direction (°)'); const c = __ci.circ(v, 360);
      const n0 = t.columns.length;
      __ci.head('direction (°)', rep).querySelector('.sm-ob-menu').click(); await __ci.sleep(60);
      [...document.querySelectorAll('.sm-menu button')].find((b) => b.textContent === 'Save').click(); await __ci.sleep(60);
      [...document.querySelectorAll('.sm-menu button')].find((b) => b.textContent.includes('Deviation from the Mean Direction')).click(); await __ci.sleep(900);
      const dev = t.columns[t.columns.length - 1];
      return { un: __ci.tableUnder('Tests of Uniformity', 0, rep), c, heads: __ci.heads(rep), est: __ci.tableUnder('Fitted von Mises Distribution', 0, rep),
        rose: rep.plots[1].traces.length, added: t.columns.length - n0, dev: dev.name, dv: dev.values[10], v10: t.col('direction (°)').values[10], vdir: Object.entries(rep.spec.options).find(([k]) => k.endsWith('|vdir'))[1], errors: __ci.errors(rep) };
    })()''')
    check('V Test…: its dialog sets the direction', r['vdir'], 240)
    vrow = r['un'][2]
    check('the V test row', vrow[0], 'V test, mean direction 240°')
    check.near('V = nR̄ cos(mean − 240°) computed in the page', num(vrow[1]), 240 * r['c']['R'] * math.cos(math.radians(r['c']['mean'] - 240)), 1e-6)
    check('Fit von Mises: its outline', 'Fitted von Mises Distribution' in r['heads'], True)
    check('the fit gives μ and κ', [row[0] for row in r['est'][1:]], ['μ (mean direction)', 'κ (concentration)'])
    check.near('μ̂ is the mean direction', num(r['est'][1][1]), r['c']['mean'], 1e-6)
    check('the fitted density is drawn on the rose', r['rose'], 3)
    want = ((r['v10'] - r['c']['mean'] + 180) % 360) - 180
    check('Save ▸ Deviation from the Mean Direction adds a column', (r['added'], r['dev']), (1, 'Deviation[direction (°)]'))
    check.near('the saved deviation, −180 to 180', r['dv'], want, 1e-6)
    check('no errors (V test, von Mises, Save)', r['errors'], [])
    await page.ev("__ci.head('Fitted von Mises Distribution').scrollIntoView({ block: 'start' })")
    await asyncio.sleep(0.4)
    await shot(page, '02-vonmises.png')

    # ---- a clock: the hour of the peak gust, from the report's red triangle
    r = await page.ev('''(async () => {
      const rep = await __ci.open('Wind', { y: ['hour of peak gust'] });
      const p = __ci.pick('Circular Statistics', ['Units', 'Clock…'], rep); await __ci.dialogOK((d) => { d.querySelector('input').value = '24'; }); await p;
      const v = __ci.col(rep.table, 'hour of peak gust'); const c = __ci.circ(v, 24);
      return { c, kv: __ci.kvOf('Summary Statistics', rep), units: rep.spec.options.units, period: rep.spec.options.period, bins: rep.plots[1].traces[0].r.length,
        ticks: rep.plots[1].userLayout.polar.angularaxis.ticktext, errors: __ci.errors(rep) };
    })()''')
    check('Units ▸ Clock…: a 24-hour clock', (r['units'], r['period']), ('clock', 24))
    check.near('the mean hour = the one computed in the page', r['kv']['Mean Direction'], r['c']['mean'], 1e-6)
    check.near('the circular SD in hours', r['kv']['Circular Std Dev'], r['c']['sd'], 1e-6)
    check('the truth: the gusts peak around 15:00', 13.5 < r['c']['mean'] < 16.5, True)
    check('an hour a bin, and the hours around the rose', (r['bins'], r['ticks'][:3]), (24, ['0', '2', '4']))
    check('no errors (a clock)', r['errors'], [])
    await shot(page, '03-clock.png')

    # ---- with X: groups, a covariate, a second angle
    r = await page.ev('''(async () => {
      const rep = await __ci.open('Wind', { y: ['direction (°)'], x: ['season'] });
      const t = rep.table; const s = t.col('season').values, v = t.col('direction (°)').values;
      const g = ['winter', 'summer'].map((lv) => __ci.circ(v.filter((_, i) => s[i] === lv), 360));
      const tb = __ci.tableUnder('Comparison of season Groups', 0, rep); const tests = __ci.tableUnder('Comparison of season Groups', 1, rep);
      const dot = rep.plots[0]; const names = dot.traces.filter((tr) => tr.mode === 'markers').map((tr) => tr.name);
      return { g, tb, tests, names, errors: __ci.errors(rep) };
    })()''')
    check('groups: a row per season, in the table\'s order', [row[0] for row in r['tb'][1:]], ['winter', 'summer'])
    check.near('winter\'s mean direction computed in the page', num(r['tb'][1][2]), r['g'][0]['mean'], 1e-6)
    check.near('summer\'s R̄', num(r['tb'][2][3]), r['g'][1]['R'], 1e-6)
    check('the truth: winter near 220°, summer near 280°', (abs(r['g'][0]['mean'] - 220) < 12, abs(r['g'][1]['mean'] - 280) < 15), (True, True))
    check('Watson-Williams and the uniform-scores test', [row[0] for row in r['tests'][1:]], ['Watson-Williams (mean directions)', 'Uniform scores (distributions)'])
    check('the seasons differ (the truth: 60° apart)', r['tests'][1][4].startswith('<.0001'), True)
    check('the dot plot: a coloured trace per season', r['names'], ['winter', 'summer'])
    check('no errors (groups)', r['errors'], [])
    await page.ev("__ci.head('Comparison of season Groups').scrollIntoView({ block: 'start' })")
    await asyncio.sleep(0.4)
    await shot(page, '04-groups.png')
    r = await page.ev('''(async () => {
      const rep = await __ci.open('Wind', { y: ['direction (°)'], x: ['speed (m/s)'] });
      const t = rep.table; const a = __ci.col(t, 'direction (°)').map((d) => d * Math.PI / 180), x = __ci.col(t, 'speed (m/s)');
      const cs = a.map(Math.cos), sn = a.map(Math.sin);
      const rxc = __ci.corr(x, cs), rxs = __ci.corr(x, sn), rcs = __ci.corr(cs, sn);
      const R = Math.sqrt((rxc ** 2 + rxs ** 2 - 2 * rxc * rxs * rcs) / (1 - rcs ** 2));
      const p = rep.plots[2]; p._click({ points: [{ curveNumber: 0, pointNumber: 12 }], event: {} }); const sel = t.selectedRows(); t.select([]);
      return { kv: __ci.kvOf('Circular-Linear Correlation', rep), R, sel, row: p.rows[0][12], errors: __ci.errors(rep) };
    })()''')
    check.near('circular-linear R from the correlations of X, cos and sin computed in the page', r['kv']['Correlation R'], r['R'], 1e-6)
    check('the truth: the speed depends on the direction', r['kv']['Correlation R'] > 0.5, True)
    check('the scatter of the angle by X selects its rows', r['sel'], [r['row']])
    check('no errors (circular-linear)', r['errors'], [])
    r = await page.ev('''(async () => {
      const rep = await __ci.open('Wind', { y: ['direction (°)'], x: ['direction B (°)'] }, { xAngle: true });
      const t = rep.table; const a = __ci.col(t, 'direction (°)'), b = __ci.col(t, 'direction B (°)');
      const ma = __ci.circ(a, 360).mean * Math.PI / 180, mb = __ci.circ(b, 360).mean * Math.PI / 180;
      const sa = a.map((v) => Math.sin(v * Math.PI / 180 - ma)), sb = b.map((v) => Math.sin(v * Math.PI / 180 - mb));
      let num_ = 0, da = 0, db = 0; for (let i = 0; i < a.length; i++) { num_ += sa[i] * sb[i]; da += sa[i] ** 2; db += sb[i] ** 2; }
      return { kv: __ci.kvOf('Circular-Circular Correlation', rep), r: num_ / Math.sqrt(da * db), errors: __ci.errors(rep) };
    })()''')
    check.near('circular-circular r (Jammalamadaka and SenGupta) computed in the page', r['kv']['Circular Correlation r'], r['r'], 1e-6)
    check('the truth: station B follows station A', r['kv']['Circular Correlation r'] > 0.6, True)
    check('no errors (circular-circular)', r['errors'], [])
    r = await page.ev('''(async () => {
      const rep = await __ci.open('Wind', { y: ['direction (°)', 'direction B (°)'] });
      await __ci.pick('Circular Statistics', ['Circular Correlations'], rep);
      return { tb: __ci.tableUnder('Circular-Circular Correlations', 0, rep), heads: __ci.heads(rep).filter((h) => /direction|Correlations/.test(h)), errors: __ci.errors(rep) };
    })()''')
    check('two angles: an outline each and their correlation', r['heads'], ['direction (°)', 'direction B (°)', 'Circular-Circular Correlations'])
    check('the correlations table', [row[:2] for row in r['tb']], [['Angle', 'by Angle'], ['direction (°)', 'direction B (°)']])
    check('no errors (several angles)', r['errors'], [])

    # ---- By, exclusion and Redo, a project, Bootstrap
    r = await page.ev('''(async () => {
      const rep = await __ci.open('Wind', { y: ['direction (°)'], by: ['season'] });
      const t = rep.table; const s = t.col('season').values;
      const tops = __ci.heads(rep).filter((h) => h.startsWith('Circular Statistics'));
      const kvW = __ci.kvOf('Summary Statistics', rep, 0);
      const want = __ci.circ(t.col('direction (°)').values.filter((_, i) => s[i] === 'winter'), 360);
      return { tops, mean: kvW['Mean Direction'], want: want.mean, errors: __ci.errors(rep) };
    })()''')
    check('By: a report per season', r['tops'], ['Circular Statistics season=winter', 'Circular Statistics season=summer'])
    check.near('By: winter\'s mean direction', r['mean'], r['want'], 1e-6)
    check('no errors (By)', r['errors'], [])
    r = await page.ev('''(async () => {
      const rep = await __ci.open('Wind', { y: ['direction (°)'] }); const t = rep.table;
      t.setState([0, 1, 2, 3, 4], 'excluded', true); const stale = !rep.staleEl.hidden;
      rep.run(); await new Promise((res) => rep.on('done', res)); const n = __ci.kvOf('Summary Statistics', rep)['N'];
      t.setState([0, 1, 2, 3, 4], 'excluded', false); return { stale, n };
    })()''')
    check('an exclusion makes the report stale; Redo uses the rest', (r['stale'], r['n']), (True, 235))
    r = await page.ev('''(async () => {
      const t = __ci.table('Wind'); const d = t.col('direction (°)').id;
      const o = { units: 'degrees' }; o[d + '|vdir'] = 225; o[d + '|vm'] = true; o[d + '|roseArea'] = false;
      const rep = await __ci.open('Wind', { y: ['direction (°)'], x: ['season'] }, o);
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const rep2 = SM.app.reports[SM.app.reports.length - 1]; await new Promise((res) => rep2.on('done', res)); await __ci.sleep(300);
      const out = { newIds: rep2.spec.roles.y[0] !== d, heads: __ci.heads(rep2).filter((h) => /von Mises|Comparison|Uniformity/.test(h)), v: (__ci.tableUnder('Tests of Uniformity', 0, rep2) || [])[2],
        sq: rep2.plots[1].traces[0].r.reduce((a, b) => a + b, 0), errors: __ci.errors(rep2) };
      const t2 = rep2.table; SM.app.closeReport(rep2); SM.app.closeTable(t2);
      return out;
    })()''')
    check('a project: the columns get new ids', r['newIds'], True)
    check('and keeps the V test, the von Mises fit and the groups', (r['heads'], r['v'][0] if r['v'] else None), (['Tests of Uniformity', 'Fitted von Mises Distribution', 'Comparison of season Groups'], 'V test, mean direction 225°'))
    check.near('and the rose\'s radius option', r['sq'], 240, 1e-9)
    check('no errors (project)', r['errors'], [])
    r = await page.ev('''(async () => {
      const rep = await __ci.open('Wind', { y: ['direction (°)'] });
      const tbl = __ci.head('Summary Statistics', rep).parentElement.querySelector(':scope > .sm-ob-body table.sm-kv');
      const t = await SM.bootstrap.run(tbl, tbl._rt.columns[1], { B: 5, seed: 4, show: false });
      const rows = SM.bootstrap.sampler(rep.groups()[0].rows, 4)();
      const v = rep.table.col('direction (°)').values;
      return { cols: t.columns.map((c) => c.name).slice(0, 4), R1: t.col('Mean Resultant Length (R̄)').values[1], want: __ci.circ(rows.map((r) => v[r]), 360).R, heads: __ci.heads(rep).length, errors: __ci.errors(rep) };
    })()''', timeout=300)
    check('Bootstrap of the Summary Statistics', r['cols'], ['BootID', 'N', 'Mean Direction', 'Mean Resultant Length (R̄)'])
    check.near('Bootstrap: sample 1\'s R̄ = R̄ of the rows drawn, computed in the page', r['R1'], r['want'], 1e-9)
    check('Bootstrap leaves the report as it was', r['errors'], [])

    # ---- a table is untrusted: names that look like markup reach Plotly escaped
    r = await page.ev('''(async () => {
      const g = SM.util.rng('circular-names'); const a = [], b = [], s = [];
      for (let i = 0; i < 50; i++) { a.push(g.u() * 360); b.push(g.normal(0, 1)); s.push(i % 2 ? '<img src=x onerror=alert(1)>' : '%{y}<b>'); }
      SM.app.addTable(new SM.Table({ name: 'Names', columns: [{ name: '<b>dir</b>', values: a }, { name: '<i>x</i>%{x}', values: b }, { name: 'g<br>', dataType: 'character', values: s }] }));
      const r1 = await __ci.open('Names', { y: ['<b>dir</b>'], x: ['<i>x</i>%{x}'] });
      const p = r1.plots[2]; const titles = [p.userLayout.xaxis.title.text, p.userLayout.yaxis.title.text];
      const r2 = await __ci.open('Names', { y: ['<b>dir</b>'], x: ['g<br>'] });
      const names = r2.plots[0].traces.filter((tr) => tr.mode === 'markers').map((tr) => tr.name);
      return { titles, names, imgs: document.querySelectorAll('.sm-plot img, .sm-ob img').length, errors: [r1, r2].flatMap((x) => __ci.errors(x)) };
    })()''')
    check('column names go into Plotly\'s axis titles escaped', all('<' not in t and '%{' not in t for t in r['titles']), True)
    check('level names go into the legend escaped', all('<' not in t and '%{' not in t for t in r['names']), True)
    check('no element was made from a name', r['imgs'], 0)
    check('no errors (names that look like markup)', r['errors'], [])

    # ---- (i) topics, the script
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    r = await page.ev("SM.app.reports.find(r => r.platform.id === 'circular' && (r.spec.roles.x || []).length && r.table.col(r.spec.roles.x[0]).name === 'season').pythonScript()")
    check('the Python script holds the code of the results', all(s in r for s in ('stats.circmean', 'Rayleigh', 'Watson-Williams')), True)

    # ---- dark theme, phone width
    light = await page.ev('SM.util.themeColors().text')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === 'circular')))")
    await asyncio.sleep(1.5)
    r = await page.ev('''(() => { const rep = SM.app.reports.find(r => r.platform.id === 'circular'); const rose = rep.plots.find((p) => p.traces[0].type === 'barpolar');
      return { axis: rose.userLayout.polar.angularaxis.color, text: SM.util.themeColors().text, errors: SM.app.reports.filter(r => r.platform.id === 'circular').map(r => r.body.querySelectorAll('.sm-ob-error').length) }; })()''')
    check('dark theme: the rose is drawn again with the dark theme\'s text colour', (r['axis'] == r['text'], r['text'] != light), (True, True))
    check('dark theme: the reports redraw without errors', all(v == 0 for v in r['errors']), True)
    await shot(page, '05-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    r = await page.ev('''(async () => { const rep = SM.app.reports.find(r => r.platform.id === 'circular'); rep.run(); await new Promise((res) => rep.on('done', res)); await __ci.sleep(600);
      return { bw: rep.body.clientWidth, widths: rep.plots.map((p) => p.width), scroll: document.documentElement.scrollWidth <= innerWidth + 1 }; })()''')
    check('at phone width the graphs fit the report', all(w <= r['bw'] for w in r['widths']), True)
    check('and the page does not scroll sideways', r['scroll'], True)
    await shot(page, '06-phone.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")

    # ---- a large table stays quick
    t0 = time.time()
    r = await page.ev('''(async () => {
      const g = SM.util.rng('circular-large'); const n = 30000; const a = [], h = [];
      for (let i = 0; i < n; i++) { a.push(((g.normal(200, 40) % 360) + 360) % 360); h.push(g.u() * 24); }
      SM.app.addTable(new SM.Table({ name: 'Large angles', columns: [{ name: 'a', values: a }, { name: 'k', dataType: 'character', values: a.map((_, i) => 'ABC'[i % 3]) }] }));
      const start = performance.now();
      const o = {}; const rep = await __ci.open('Large angles', { y: ['a'], x: ['k'] }, o);
      return { ms: performance.now() - start, n: __ci.kvOf('Summary Statistics', rep)['N'], errors: __ci.errors(rep), gl: rep.plots[0].traces.some((tr) => tr.type === 'scattergl') || !SM.report.hasWebGL() };
    })()''', timeout=600)
    check('30 000 angles in three groups: no errors', r['errors'], [])
    check('30 000 angles: every one used', r['n'], 30000)
    check('30 000 angles: done within 60 s', r['ms'] < 60000, True)
    print(f'   (30 000 angles took {r["ms"] / 1000:.1f} s)')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
