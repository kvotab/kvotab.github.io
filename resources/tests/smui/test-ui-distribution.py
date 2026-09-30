#!/usr/bin/env python3
"""smui.html in a real browser: Distribution's effect size and Bayes
factors (Test Mean ▸ Effect Size and Bayes Factor…, Test Probabilities ▸
Bayes Factor… for two levels). Distribution's older checks are in
test-ui-core.py.

The red-triangle items and their dialogs; Cohen's d against the mean and
standard deviation computed here in the page, BF10 against the backend and
the binomial Bayes factor against its closed form computed here; BF01 =
1/BF10; the item is disabled for more than two levels; By, a project, the
dark theme and phone width; every (i) has a topic; no script errors.

Start a server on the repository root and headless Chrome (the recipe is in
README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-distribution.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import os
import sys

from axis_checks import AXIS_JS, dbl, r9, red_lines, run_code
from cdp import BASE, Checks, open_page, wait_engine
from test_charts import GRAPHS_JS, close, find_line, lines_labelled, maxdiff, run_graph

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


HELPERS = r'''
window.__dt = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  rep: () => SM.app.reports[SM.app.reports.length - 1],
  table(name) { return SM.app.tables.find((t) => t.name === name); },
  async open(tableName, roles, options) {
    const t = this.table(tableName);
    SM.app.showTab(SM.app.tabOf(t));
    const ids = {};
    for (const [k, names] of Object.entries(roles)) ids[k] = names.map((n) => t.col(n).id);
    const rep = SM.app.openReport(SM.platforms.get('distribution'), { roles: ids, options: options || {} }, t);
    await new Promise((res) => rep.on('done', res));
    await this.sleep(200);
    return rep;
  },
  heads(rep) { return [...(rep || this.rep()).body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map((h) => h.textContent); },
  errors(rep) { return [...(rep || this.rep()).body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent.slice(0, 400)); },
  head(title, rep, n = 0) { return [...(rep || this.rep()).body.querySelectorAll('.sm-ob-head')].filter((h) => h.querySelector('h2, h3, h4').textContent === title)[n]; },
  // the labels (and disabled states) of an outline's red triangle
  async menuOf(title, rep) {
    this.head(title, rep).querySelector('.sm-ob-menu').click(); await this.sleep(60);
    const m = [...document.querySelectorAll('.sm-menu')].pop();
    const out = [...m.querySelectorAll('button')].map((b) => [b.querySelector('.sm-label') ? b.querySelector('.sm-label').textContent : b.textContent, b.disabled]);
    SM.ui.closeMenus(0); return out;
  },
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
      if (!b) { SM.ui.closeMenus(0); throw new Error('no menu item ' + label); }
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
  num(s) { return SM.table.toNumber(String(s).replace(/−/g, '-').replace(/[<*]/g, '')); },
  meanSd(v) { const m = v.reduce((a, b) => a + b, 0) / v.length; return [m, Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / (v.length - 1)), v.length]; },
  lfact(n) { let s = 0; for (let i = 2; i <= n; i++) s += Math.log(i); return s; },
};
'''


async def main():
    page = await open_page(f'{BASE}/smui.html?example=students')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    check('the backend names are there', await page.ev('["distribution.effect", "distribution.bayes_t", "distribution.bayes_binom"].every(n => SM.engine.has(n))'), True)
    await page.ev(HELPERS)
    num = lambda s: float(str(s).replace('−', '-'))

    # ---- Test Mean from its dialog, then its red triangle: Effect Size
    r = await page.ev('''(async () => {
      const rep = await __dt.open('Students', { y: ['height (cm)'] });
      const p = __dt.pick('height (cm)', ['Test Mean…'], rep);
      await __dt.dialogOK((d) => { d.querySelectorAll('input')[0].value = '165'; });
      await p;
      const menu = await __dt.menuOf('Test Mean', rep);
      await __dt.pick('Test Mean', ['Effect Size'], rep);
      const t = rep.table; const [m, s, n] = __dt.meanSd(t.col('height (cm)').values.filter(Number.isFinite));
      return { menu: menu.map((x) => x[0]), heads: __dt.heads(rep), es: __dt.tableUnder('Effect Size', 0, rep), m, s, n, errors: __dt.errors(rep) };
    })()''')
    check('Test Mean\'s red triangle: Effect Size and Bayes Factor…', r['menu'][:2], ['Effect Size', 'Bayes Factor…'])
    check('Effect Size sits under Test Mean', [h for h in r['heads'] if h in ('Test Mean', 'Effect Size')], ['Test Mean', 'Effect Size'])
    es = {row[0]: row for row in r['es'][1:]}
    check('Cohen\'s d and Hedges\' g with the exact interval', (list(es), es["Cohen's d"][4]), (["Cohen's d", "Hedges' g"], 'noncentral t'))
    d = (r['m'] - 165) / r['s']
    check.near("Cohen's d = (mean − 165)/s computed in the page", num(es["Cohen's d"][1]), d, 1e-5)
    check("Hedges' g is J·d, a little smaller", 0 < abs(num(es["Hedges' g"][1])) < abs(num(es["Cohen's d"][1])), True)
    check('the interval holds d', num(es["Cohen's d"][2]) < num(es["Cohen's d"][1]) < num(es["Cohen's d"][3]), True)
    check('no errors (Test Mean effect size)', r['errors'], [])

    # ---- Bayes Factor…: its dialog sets the prior scale
    r = await page.ev('''(async () => {
      const rep = __dt.rep(); const p = __dt.pick('Test Mean', ['Bayes Factor…'], rep);
      await __dt.dialogOK((d) => { d.querySelector('input').value = '1'; });
      await p;
      const back = await SM.engine.call('distribution.bayes_t', { column: 'height (cm)', mu: 165, r: 1, rows: null }, rep.table);
      const opt = Object.entries(rep.spec.options).find(([k]) => k.endsWith('|tmBf'))[1];
      return { bf: __dt.tableUnder('Bayes Factor', 0, rep), kv: __dt.tableUnder('Bayes Factor', 1, rep), back: back.table.rows.map((x) => x.bf10), opt,
        info: !!__dt.head('Bayes Factor', rep).querySelector('.info-btn'), errors: __dt.errors(rep) };
    })()''')
    check('the dialog sets the scale r of the Cauchy prior', r['opt'], {'r': 1})
    check('BF10 and BF01 for the three alternatives', ([row[0] for row in r['bf'][1:]], r['bf'][0]), (['mean ≠ 165', 'mean > 165', 'mean < 165'], ['Alternative', 'BF10', 'BF01']))
    for i, lab in enumerate(('two-sided', 'mean above', 'mean below')):
        check.near(f'BF10 ({lab}) = the backend with r = 1', num(r['bf'][i + 1][1]), r['back'][i], 1e-6)
        check.near(f'BF01 ({lab}) = 1/BF10', num(r['bf'][i + 1][2]), 1 / r['back'][i], 1e-5)
    check('the facts: t, DF, N and the prior', [row[0] for row in r['kv']], ['t', 'DF', 'N', 'Prior scale r'])
    check('the Bayes Factor outline has an (i)', r['info'], True)
    check('no errors (Test Mean Bayes factor)', r['errors'], [])
    await page.ev("__dt.head('Test Mean').scrollIntoView({ block: 'start' })")
    await asyncio.sleep(0.4)
    await shot(page, '01-test-mean.png')

    # ---- Test Probabilities of two levels: the binomial Bayes factor
    r = await page.ev('''(async () => {
      const rep = await __dt.open('Students', { y: ['sex', 'age'] });
      const p = __dt.pick('sex', ['Test Probabilities…'], rep);
      await __dt.dialogOK((d) => { const i = d.querySelectorAll('input'); i[0].value = '0.4'; i[1].value = '0.6'; });
      await p;
      const p2 = __dt.pick('age', ['Test Probabilities…'], rep); await __dt.dialogOK(); await p2;
      const menuSex = await __dt.menuOf('Test Probabilities', rep);
      const menuAge = [...rep.body.querySelectorAll('.sm-ob-head')].filter((h) => h.textContent.trim() === 'Test Probabilities').length;
      const p3 = __dt.pick('Test Probabilities', ['Bayes Factor…'], rep); await __dt.dialogOK(); await p3;
      const t = rep.table; const sx = t.col('sex').values.filter((v) => v != null); const lv = t.levels(t.col('sex'));
      const k = sx.filter((v) => v === lv[0]).length, n = sx.length;
      // BF10 with a uniform prior: B(k + 1, n − k + 1)/(p₀ᵏ(1 − p₀)ⁿ⁻ᵏ) = k!(n − k)!/(n + 1)! / (p₀ᵏ(1 − p₀)ⁿ⁻ᵏ)
      const lbf = __dt.lfact(k) + __dt.lfact(n - k) - __dt.lfact(n + 1) - k * Math.log(0.4) - (n - k) * Math.log(0.6);
      const ageHead = __dt.head('Test Probabilities', rep, 1); ageHead.querySelector('.sm-ob-menu').click(); await __dt.sleep(60);
      const m = [...document.querySelectorAll('.sm-menu')].pop();
      const ageItem = [...m.querySelectorAll('button')].find((b) => b.querySelector('.sm-label') && b.querySelector('.sm-label').textContent === 'Bayes Factor…');
      const ageDisabled = ageItem ? ageItem.disabled : 'missing'; SM.ui.closeMenus(0);
      return { menuSex: menuSex.map((x) => x[0]), tps: menuAge, bf: __dt.tableUnder('Bayes Factor', 0, rep), kv: __dt.tableUnder('Bayes Factor', 1, rep), want: Math.exp(lbf), k, n, lv, ageDisabled,
        heads: __dt.heads(rep), errors: __dt.errors(rep) };
    })()''')
    check('Test Probabilities\' red triangle has Bayes Factor…', 'Bayes Factor…' in r['menuSex'], True)
    check('a Test Probabilities outline for each column', r['tps'], 2)
    check('Bayes Factor… is disabled for a column of more than two levels (age)', r['ageDisabled'], True)
    lv0 = r['lv'][0]
    check('its alternatives: the first level\'s probability against 0.4', [row[0] for row in r['bf'][1:]], [f'P({lv0}) ≠ 0.4', f'P({lv0}) > 0.4', f'P({lv0}) < 0.4'])
    check.near('the binomial BF10 = k!(n − k)!/(n + 1)! / (p₀ᵏ(1 − p₀)ⁿ⁻ᵏ) computed in the page', num(r['bf'][1][1]), r['want'], 1e-6)
    check.near('its BF01', num(r['bf'][1][2]), 1 / r['want'], 1e-5)
    kv = {row[0]: row[1] for row in r['kv']}
    check('the facts: the count, N, p₀ and the prior', (num(kv[f'Count {lv0}']), num(kv['N']), kv[f'Hypothesized P({lv0})'], kv['Prior a'], kv['Prior b']), (r['k'], r['n'], '0.4', '1', '1'))
    check('no errors (binomial Bayes factor)', r['errors'], [])
    await page.ev("__dt.head('Test Probabilities').scrollIntoView({ block: 'start' })")
    await asyncio.sleep(0.4)
    await shot(page, '02-test-probabilities.png')

    # ---- By, and a project keeps the options (the columns get new ids)
    r = await page.ev('''(async () => {
      const t = __dt.table('Students'); const h = t.col('height (cm)').id;
      const o = {}; o[h + '|testMean'] = { mu: 165 }; o[h + '|tmEffect'] = true; o[h + '|tmBf'] = { r: 0.707 };
      const rep = await __dt.open('Students', { y: ['height (cm)'], by: ['sex'] }, o);
      const hs = __dt.heads(rep);
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const rep2 = SM.app.reports[SM.app.reports.length - 1]; await new Promise((res) => rep2.on('done', res));
      const back = __dt.heads(rep2).filter((x) => x === 'Effect Size' || x === 'Bayes Factor').length;
      const out = { es: hs.filter((x) => x === 'Effect Size').length, bf: hs.filter((x) => x === 'Bayes Factor').length, back, newTable: rep2.table !== t, errors: [rep, rep2].flatMap((x) => __dt.errors(x)) };
      const t2 = rep2.table; SM.app.closeReport(rep2); SM.app.closeTable(t2);
      return out;
    })()''')
    check('By: an Effect Size and a Bayes Factor in each group', (r['es'], r['bf']), (2, 2))
    check('a project keeps them', (r['newTable'], r['back']), (True, 4))
    check('no errors (By, project)', r['errors'], [])

    # ---- the graphs' Python code: a block under each graph, run in the page
    await chart_code(page)

    # ---- help for every input: the launch dialog's (i), the red-triangle forms' (i)
    await help_inputs(page)

    # ---- Axis Settings on the histogram: its value axis serves the box plot beside it too
    await axis_settings(page)

    # ---- (i) topics, dark theme, phone width
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.title === 'Distribution' && !r.spec.roles.by)))")
    await asyncio.sleep(1.5)
    await page.ev("__dt.head('Test Mean', SM.app.reports.find(r => r.title === 'Distribution' && !r.spec.roles.by)).scrollIntoView({ block: 'start' })")
    await asyncio.sleep(0.4)
    await shot(page, '03-dark.png')
    r = await page.ev("SM.app.reports.map(r => r.body.querySelectorAll('.sm-ob-error').length)")
    check('dark theme: the reports redraw without errors', all(v == 0 for v in r), True)
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    check('no horizontal page scroll at phone width', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, '04-phone.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    # ---- the tolerance interval keeps its own confidence level when a
    # prediction interval at another level is shown too
    r = await page.ev('''(async () => {
      const t = __dt.table('Students'); const h = t.col('height (cm)').id;
      const read = (rep) => { const tr = __dt.head('Tolerance Intervals', rep).parentElement.querySelector('table.sm-rt tbody tr'); return [tr.children[1].textContent, tr.children[2].textContent]; };
      const both = {}; both[h + '|pi'] = { level: 0.95, k: 1 }; both[h + '|ti'] = { level: 0.99, coverage: 0.9 };
      const alone = {}; alone[h + '|ti'] = { level: 0.99, coverage: 0.9 };
      const r1 = await __dt.open('Students', { y: ['height (cm)'] }, both); const a = read(r1);
      const r2 = await __dt.open('Students', { y: ['height (cm)'] }, alone); const b = read(r2);
      const code = [r1.body.querySelectorAll('details.sm-code').length, r2.body.querySelectorAll('details.sm-code').length];
      const errors = [r1, r2].flatMap((x) => __dt.errors(x)); SM.app.closeReport(r1); SM.app.closeReport(r2);
      return { a, b, code, errors };
    })()''')
    check('with a 95% prediction interval, the 99% tolerance interval is the one it has alone', (r['a'], r['errors']), (r['b'], []))
    check('each interval then shows its own Python', r['code'][0] - r['code'][1], 1)
    check('no script errors', page.errors, [])
    await page.close()


# ---- Axis Settings on the histogram ------------------------------------------
# The histogram's value axis is the box plot's too (Plotly: y with x2 beside it,
# or x with y2 under it; the code: ax and bx, sharing it): set by a real
# double-click on it, its range and a reference line are the histogram's and
# the box plot's, and the code block draws them on both (ax and bx).
async def axis_settings(page):
    await page.ev(AXIS_JS)
    await page.ev(GRAPHS_JS)
    title = 'height (cm) histogram'
    for label, opts, sub, which, letter, across in (('vertical', {}, 'xy', 'ns', 'y', 'x2 domain'), ('horizontal', {'horizontal': True}, 'xy', 'ew', 'x', 'y2 domain')):
        tag = f'Axis Settings, a {label} histogram'
        await page.ev(f"(async () => {{ window.__ar = await __dt.open('Students', {{ y: ['height (cm)'] }}, {json.dumps(opts)}); }})()")
        xy = await page.ev(f'__axc.at(__ar, {json.dumps(title)}, {json.dumps(sub)}, {json.dumps(which)})')
        await dbl(page, *xy)
        got = await page.ev("__axc.fill(__ar, { min: 145, max: 175, refs: [{ value: 160, label: 'one sixty', color: 'red' }] })")
        check(f'{tag}: a double-click on the value axis opens its window', got, f'{letter.upper()} Axis Settings')
        st = await page.ev(f'(async () => __axc.state(await __axc.shown(__ar, {json.dumps(title)})))()')
        ax = f'{letter}axis'
        lines = sorted((q['xref'] if letter == 'y' else q['yref'], q[f'{letter}0']) for q in st['shapes'] if q['color'] == '#b0413e')
        check(f'{tag}: the value axis from 145 to 175', r9(st['axes'][ax]['range']), [145, 175])
        check(f'{tag}: the reference line at 160 across the histogram and the box plot, labelled once', (lines, st['labels'].count('one sixty')), (sorted([(f'{"x" if letter == "y" else "y"} domain', 160), (across, 160)]), 1))
        code = st['code'] or ''
        check(f'{tag}: the code sets the axis on ax and draws the line on ax and bx', ('target = ax' in code, 'for a in (target, bx):' in code, f'a.ax{"h" if letter == "y" else "v"}line(160, color="#b0413e"' in code), (True, True, True))
        R, err = await run_code(page, code, '__ar.table')
        A = [q for q in (R['figures'][0]['axes'] if R else [])]
        check(f'{tag}: its code runs in the page\'s Python', (err, len(A)), (None, 2))
        if len(A) == 2:
            lim = f'{letter}lim'
            check(f'{tag}: ... and draws the histogram and the box plot from 145 to 175, the line at 160 on both', ([A[0][lim], A[1][lim]], red_lines(A[0], letter), red_lines(A[1], letter)), ([[145.0, 175.0]] * 2, [160.0], [160.0]))
        st2 = await page.ev(f'(async () => {{ const done = new Promise((res) => __ar.on("done", res)); __ar.run(); await done; return __axc.state(await __axc.shown(__ar, {json.dumps(title)})); }})()')
        check(f'{tag}: Redo keeps them', (r9(st2['axes'][ax]['range']), len([q for q in st2['shapes'] if q['color'] == '#b0413e'])), ([145, 175], 2))
        st3 = await page.ev(f'__axc.reopened(__ar, {json.dumps(title)})')
        check(f'{tag}: a saved project keeps them', (r9(st3['axes'][ax]['range']) if st3 else None, len([q for q in (st3 or {}).get('shapes', []) if q['color'] == '#b0413e'])), ([145, 175], 2))
    # the dark theme: the line in its red; the code in the light theme's
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(1.2)
    st = await page.ev(f'(async () => __axc.state(await __axc.shown(__ar, {json.dumps(title)})))()')
    check('Axis Settings, dark theme: the reference line in the dark theme\'s red, the code in the light theme\'s', (sorted({q['color'] for q in st['shapes'] if q['type'] == 'line' and q['x0'] == 160}), 'color="#b0413e"' in (st['code'] or '')), (['#f08a80'], True))
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await asyncio.sleep(1.2)
    # Histograms Only: no box plot, the line on the histogram alone
    await page.ev("(async () => { window.__ar = await __dt.open('Students', { y: ['height (cm)'] }, { histOnly: true }); })()")
    xy = await page.ev(f'__axc.at(__ar, {json.dumps(title)}, "xy", "ns")')
    await dbl(page, *xy)
    await page.ev("__axc.fill(__ar, { refs: [{ value: 160, color: 'red' }] })")
    st = await page.ev(f'(async () => __axc.state(await __axc.shown(__ar, {json.dumps(title)})))()')
    code = st['code'] or ''
    check('Axis Settings, Histograms Only: the line on the histogram alone, and so in the code', ([(q['xref'], q['y0']) for q in st['shapes'] if q['color'] == '#b0413e'], 'bx' in code, 'target.axhline(160' in code), ([('x domain', 160)], False, True))
    for rep in ('__ar',):
        await page.ev(f'SM.app.closeReport({rep})')


# ---- the graphs' matplotlib code --------------------------------------------
# Each graph has a code block right under it (details.sm-code, ending in
# plt.show()); the block runs in the page's own Python (the notebook's
# runner, SM.engine.runCell) with test_charts.PROBE in place of plt.show(),
# and the figure it draws is compared with the Plotly graph above it.
def tr_named(g, name, kind=None):
    return [t for t in g['traces'] if t.get('name') == name and (kind is None or t.get('type') == kind)]


def check_histogram(label, g, F, horizontal, fits=()):
    """The histogram and its box plots against the Plotly graph above the code."""
    check(f'{label}: the title and the size', (F['suptitle'], F['size']), (g['label'], [g['w'] / 100, g['h'] / 100]))
    ax = F['axes'][0]
    bars = tr_named(g, 'Histogram', 'bar')
    if bars:
        b = bars[0]
        centers, heights = (b['x'], b['y']) if horizontal else (b['y'], b['x'])
        got_c = [(r['x'] + r['w'] / 2) if horizontal else (r['y'] + r['h'] / 2) for r in ax['bars']]
        got_h = [r['h'] if horizontal else r['w'] for r in ax['bars']]
        check(f'{label}: a bar for each bin', len(ax['bars']), len(centers))
        check.near(f'{label}: the bins\' centres', maxdiff(got_c, centers), 0, 1e-9)
        check.near(f'{label}: the bars\' heights', maxdiff(got_h, heights), 0, 1e-9)
        check.near(f'{label}: the bin width', (ax['bars'][0]['w'] if horizontal else ax['bars'][0]['h']) if ax['bars'] else None, b['width'], 1e-12)
    for f in fits:
        t = [x for x in g['traces'] if x.get('name') == f and x.get('type') == 'scatter']
        ln = lines_labelled(ax, f)
        ok = bool(t and ln)
        if ok:
            gx, gy = (ln[0]['x'], ln[0]['y'])
            ok = close(gx, t[0]['x'], 1e-4, 1e-9) and close(gy, t[0]['y'], 1e-4, 1e-9)
        check(f'{label}: the fitted {f} curve', ok, True)
    check(f'{label}: the axis titles', (ax['xlabel'], ax['ylabel']), (g['titles']['x'], g['titles']['y']))
    boxes = [t for t in g['traces'] if t.get('type') == 'box']
    if boxes:
        bx = F['axes'][1]
        box = boxes[0]
        q1, med, q3, lo, hi = box['q1'][0], box['median'][0], box['q3'][0], box['lowerfence'][0], box['upperfence'][0]
        pos = (lambda ln: ln['x']) if horizontal else (lambda ln: ln['y'])
        vals = [pos(ln) for ln in bx['lines']]
        check(f'{label}: the median', any(close(v, [med, med]) for v in vals), True)
        check(f'{label}: the whiskers to the fences', (any(close(v, [q1, lo]) for v in vals), any(close(v, [q3, hi]) for v in vals)), (True, True))
        verts = [q for p in bx['patches'] for q in p.get('xy', [])]
        check(f'{label}: the box from Q1 to Q3', sorted({round(q[0 if horizontal else 1], 9) for q in verts})[:1] + sorted({round(q[0 if horizontal else 1], 9) for q in verts})[-1:], [round(q1, 9), round(q3, 9)])
        out = tr_named(g, 'Outliers')
        fl = [ln for ln in bx['lines'] if ln['marker'] == 'o']
        want = sorted((out[0]['x'] if horizontal else out[0]['y']) if out else [])
        check(f'{label}: the outliers', sorted(pos(fl[0]) if fl else []), want)
        for name, key in (('Mean', 'the mean diamond'), ('Shortest half', 'the shortest half')):
            t = tr_named(g, name)
            if t:
                check(f'{label}: {key}', find_line(bx, t[0]['x'], t[0]['y']) is not None, True)
        qb = tr_named(g, 'Quantile box')
        if qb:
            marks = qb[0]['x'] if horizontal else qb[0]['y']
            check(f'{label}: the quantile box\'s marks', any(close(pos(ln), marks) for ln in bx['lines']), True)
    for s in g['shapes']:
        v = s['x0'] if horizontal else s['y0']
        check(f'{label}: the spec limit at {v}', any(close(ln['x' if horizontal else 'y'], [v, v]) for ln in ax['lines']), True)


async def chart_code(page):
    await page.ev(GRAPHS_JS)
    await page.ev('__gr.idle()')   # the reports run again by a change of theme are done
    # the students, with the options of the continuous column's red triangle; then By with excluded rows and a Freq
    r = await page.ev('''(async () => {
      const t = __dt.table('Students'); const h = t.col('height (cm)').id, s = t.col('sex').id;
      const o = {}; o[h + '|fits'] = ['normal', 'kde', 'weibull']; o[h + '|qq'] = true; o[h + '|qqProb'] = true; o[h + '|cdf'] = true;
      o[s + '|order'] = 'desc'; o[s + '|mosaic'] = true; o[s + '|showCounts'] = true;
      const rep = await __dt.open('Students', { y: ['height (cm)', 'sex'] }, o);
      const o2 = {}; o2[h + '|horizontal'] = true; o2[h + '|axis'] = 'density'; o2[h + '|qbox'] = true; o2[h + '|cap'] = { lsl: 150, target: 160, usl: 175 }; o2[h + '|showCounts'] = true; o2[h + '|showPercents'] = true; o2[h + '|binWidth'] = 4;
      o2[h + '|fits'] = ['lognormal']; o2[s + '|horizontal'] = true; o2[s + '|axis'] = 'prob';
      const rep2 = await __dt.open('Students', { y: ['height (cm)', 'sex'] }, o2);
      return { g1: await __gr.graphs(rep), g2: await __gr.graphs(rep2), errors: [rep, rep2].flatMap((x) => __dt.errors(x)), undrawn: __gr.take() };
    })()''')
    check('no errors (the graphs with their options)', r['errors'], [])
    check('every graph of the reports drawn (none in a closed outline)', r['undrawn'], [])
    names = [g['label'] for g in r['g1']]
    check('the graphs of the first report', names, ['height (cm) histogram', 'height (cm) normal quantile plot', 'height (cm) CDF', 'sex bar chart', 'sex mosaic'])
    for g in r['g1'] + r['g2']:
        check(f'{g["label"]}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
    tbl = "__dt.table('Students')"
    figs = {}
    for tag, gs in (('', r['g1']), (' (second)', r['g2'])):
        for g in gs:
            if not g['code']:
                continue
            F, err = await run_graph(page, g, tbl)
            check(f'{g["label"]}{tag}: the code runs in the page', err, None)
            figs[g['label'] + tag] = (g, F[0] if F else None)
    g, F = figs['height (cm) histogram']
    if F:
        check_histogram('histogram', g, F, False, fits=('Normal', 'Smooth Curve', 'Weibull'))
    g, F = figs['height (cm) histogram (second)']
    if F:
        check_histogram('histogram (horizontal, density, bin width 4, quantile box, spec limits)', g, F, True, fits=('Lognormal',))
        texts = [t['s'] for t in F['axes'][0]['texts'] if t['s'].strip() not in ('LSL', 'Target', 'USL')]
        want = [t for t in (tr_named(g, 'Histogram', 'bar')[0].get('text') or [])]
        check('histogram: Show Counts and Show Percents on the bars', [t.replace('−', '-') for t in texts], [t.replace('−', '-') for t in want])
    g, F = figs['height (cm) normal quantile plot']
    if F:
        ax = F['axes'][0]
        pts = ax['scatter'][0]['xy'] if ax['scatter'] else []
        t0, t1 = g['traces'][0], g['traces'][1]
        check.near('normal quantile plot: the points', max(maxdiff([p[0] for p in pts], t0['x']), maxdiff([p[1] for p in pts], t0['y'])), 0, 1e-6)
        check('normal quantile plot: the normal line', find_line(ax, t1['x'], t1['y'], rel=1e-6) is not None, True)
        check('normal quantile plot: the probability axis, the titles', (ax['xticklabels'][:2], ax['xlabel'], ax['ylabel'], ax['title']), (['0.01', '0.05'], g['titles']['x'], g['titles']['y'], g['label']))
    g, F = figs['height (cm) CDF']
    if F:
        ax = F['axes'][0]
        t0 = g['traces'][0]
        check('CDF plot: the steps', (find_line(ax, t0['x'], t0['y']) or {}).get('drawstyle'), 'steps-post')
        check('CDF plot: the titles', (ax['xlabel'], ax['ylabel'], ax['title']), (g['titles']['x'], g['titles']['y'], g['label']))
    for key, horizontal, prob in (('sex bar chart', False, False), ('sex bar chart (second)', True, True)):
        g, F = figs[key]
        if not F:
            continue
        ax = F['axes'][0]
        t0 = [t for t in g['traces'] if t['type'] == 'bar' and t.get('name') == 'sex'][0]
        cats, hs = (t0['x'], t0['y']) if horizontal else (t0['y'], t0['x'])
        check(f'{key}: the levels in the page\'s order', [t for t in (ax['xticklabels'] if horizontal else ax['yticklabels']) if t], cats)
        check.near(f'{key}: the bars', maxdiff([b['h'] if horizontal else b['w'] for b in ax['bars']], hs), 0, 1e-12)
        check(f'{key}: the titles', (ax['xlabel'], ax['ylabel'], ax['title']), (g['titles']['x'], g['titles']['y'], g['label']))
        if t0.get('text'):
            check(f'{key}: Show Counts', [x['s'] for x in ax['texts']], t0['text'])
    g, F = figs['sex mosaic']
    if F:
        ax = F['axes'][0]
        bars = [t for t in g['traces'] if t['type'] == 'bar' and t.get('showlegend') is not False and t.get('name')]
        tops = [b['y'] + b['h'] for b in ax['bars']]
        acc, want = 0, []
        for t in bars:
            acc += t['y'][0]
            want.append(acc)
        check.near('mosaic: the stacked probabilities, in the page\'s order', maxdiff(tops, want), 0, 1e-12)
        check('mosaic: the legend', ax['legend'], [t['name'] for t in bars][::-1])
    # By, rows excluded, a Freq column, and Histograms Only
    r = await page.ev('''(async () => {
      const t = new SM.Table({ name: 'Chart rows', columns: [
        { name: 'x', dataType: 'numeric', values: Array.from({ length: 48 }, (_, i) => Math.round(100 * (20 + 6 * Math.sin(i * 1.7) + (i % 5))) / 100) },
        { name: 'grp', dataType: 'character', values: Array.from({ length: 48 }, (_, i) => (i % 3 === 0 ? 'u' : 'v')) },
        { name: 'k', dataType: 'character', values: Array.from({ length: 48 }, (_, i) => ['p', 'q', 'r'][i % 4 === 0 ? 2 : i % 2]) },
        { name: 'n', dataType: 'numeric', values: Array.from({ length: 48 }, (_, i) => (i === 4 ? 0 : 1 + (i % 3))) }] });
      SM.app.addTable(t);
      t.setState([2, 7, 11], 'excluded', true);
      const o1 = {}; o1[t.col('x').id + '|fits'] = ['normal', 'gamma'];
      const rep = await __dt.open('Chart rows', { y: ['x', 'k'], freq: ['n'], by: ['grp'] }, o1);
      const o = { histOnly: true };
      const rep2 = await __dt.open('Chart rows', { y: ['x', 'k'] }, o);
      return { g: await __gr.graphs(rep), g2: await __gr.graphs(rep2), errors: [rep, rep2].flatMap((x) => __dt.errors(x)), undrawn: __gr.take() };
    })()''')
    check('no errors (By, excluded rows, Freq)', r['errors'], [])
    check('every graph of the reports drawn (By, Histograms Only)', r['undrawn'], [])
    check('By: the graphs of each group, each with its code', [(g['label'], bool(g['code'])) for g in r['g']], [('x histogram', True), ('k bar chart', True)] * 2)
    check('Histograms Only: the two graphs with their code', [(g['label'], bool(g['code'])) for g in r['g2']], [('x histogram', True), ('k bar chart', True)])
    for i, g in enumerate(r['g'] + r['g2']):
        F, err = await run_graph(page, g, "__dt.table('Chart rows')")
        tag = f'{g["label"]} ({"group " + str(i // 2 + 1) if i < 4 else "Histograms Only"})'
        check(f'{tag}: the code runs in the page', err, None)
        if not F:
            continue
        F = F[0]
        if g['label'].endswith('histogram'):
            check_histogram(tag, g, F, False, fits=('Normal', 'Gamma') if i < 4 else ())
            if i >= 4:
                check(f'{tag}: the histogram alone', len(F['axes']), 1)
        else:
            ax = F['axes'][0]
            t0 = [t for t in g['traces'] if t['type'] == 'bar' and t.get('name') == 'k'][0]
            check(f'{tag}: the Freq-weighted counts of the group', ([t for t in ax['yticklabels'] if t], [b['w'] for b in ax['bars']]), (t0['y'], t0['x']))
    await page.ev("for (const r of SM.app.reports.filter((x) => x.table && ['Chart rows'].includes(x.table.name))) SM.app.closeReport(r); SM.app.closeTable(__dt.table('Chart rows'));")


# Read the (i) panels: the open panel's title and sections, each with its
# heading, its choices [name, text] and its paragraphs.
HELP_JS = r"""
window.__help = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  panel() {
    const p = document.querySelector('.info-panel');
    if (!p) return null;
    const out = { title: p.querySelector('.info-panel-title').textContent, sections: [] };
    let cur = { heading: '', choices: [], text: [] };
    out.sections.push(cur);
    for (const n of p.querySelector('.info-panel-body').children) {
      if (n.tagName === 'H3') { cur = { heading: n.textContent, choices: [], text: [] }; out.sections.push(cur); }
      else if (n.tagName === 'DL' && n.classList.contains('info-choices')) for (const dt of n.querySelectorAll('dt')) cur.choices.push([dt.textContent, dt.nextElementSibling ? dt.nextElementSibling.textContent : '']);
      else cur.text.push(n.textContent);
    }
    return out;
  },
  async read(btn) { if (!btn) return null; btn.click(); await this.sleep(150); const r = this.panel(); KvotInfo.close(); await this.sleep(40); return r; },
  names(p, heading) { const s = p && p.sections.find((x) => x.heading === heading); return s ? s.choices.map((c) => c[0]) : null; },
  // the shortest text of a section's choices, without what a role takes '(required, ...)'
  shortest(p, heading) { const s = p && p.sections.find((x) => x.heading === heading); return s && s.choices.length ? Math.min(...s.choices.map((c) => c[1].replace(/\s*\([^()]*\)$/, '').length)) : 0; },
  dialog() { return [...document.querySelectorAll('.sm-dialog')].pop(); },
  async launch(id, setup) {
    SM.app.launch(id); await this.sleep(350);
    const d = [...document.querySelectorAll('.sm-launch-dialog')].pop();
    if (setup) await setup(d);
    await this.sleep(100);
    const audit = KvotInfo.audit();
    const p = await this.read(d.querySelector('.sm-dialog-head .info-btn'));
    return { d, p, noTopic: audit.noTopic };
  },
  async menu(title, path, rep, n = 0) {
    rep = rep || SM.app.reports[SM.app.reports.length - 1];
    const h = [...rep.body.querySelectorAll('.sm-ob-head')].filter((x) => x.querySelector('h2, h3, h4').textContent === title)[n];
    if (!h) throw new Error('no outline ' + title);
    h.querySelector('.sm-ob-menu').click();
    for (const label of path) {
      await this.sleep(60);
      const m = [...document.querySelectorAll('.sm-menu')].pop();
      const b = m && [...m.querySelectorAll('button')].find((x) => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === label);
      if (!b) { SM.ui.closeMenus(0); throw new Error('no menu item ' + label); }
      b.click();
    }
  },
  async form() {
    let d = null;
    for (let i = 0; i < 60 && !(d && d.querySelector('.sm-form')); i++) { await this.sleep(50); d = this.dialog(); }
    if (!d) throw new Error('no form');
    const labels = [...d.querySelectorAll('.sm-form label')].map((l) => l.textContent);
    const audit = KvotInfo.audit();
    const p = await this.read(d.querySelector('.sm-dialog-head .info-btn'));
    [...d.querySelectorAll('.sm-dialog-foot .sm-btn')].find((b) => b.textContent === 'Cancel').click();
    await this.sleep(60);
    return { labels, title: p && p.title, fields: this.names(p, 'Fields'), shortest: this.shortest(p, 'Fields'), headings: p ? p.sections.map((x) => x.heading) : null, noTopic: audit.noTopic };
  },
};
"""


async def help_inputs(page):
    """The launch dialog's (i) lists every role and option with what it is
    for; each red-triangle form's (i) lists its fields."""
    await page.ev(HELP_JS)
    r = await page.ev('''(async () => {
      const a = await __help.launch('distribution');
      const out = { roles: __help.names(a.p, 'Roles'), rolesShort: __help.shortest(a.p, 'Roles'), opts: __help.names(a.p, 'Options'), optsShort: __help.shortest(a.p, 'Options'), noTopic: a.noTopic };
      a.d.querySelector('.sm-dialog-x').click();
      return out; })()''')
    check('the launch dialog\'s (i) lists every role', r['roles'], ['Y, Columns', 'Weight', 'Freq', 'By'])
    check('... each with what it is for, beyond what it takes', r['rolesShort'] > 60, True)
    check('... and the option, explained', (r['opts'], r['optsShort'] > 60), (['Histograms Only'], True))
    check('every (i) of the open launch dialog has a topic', r['noTopic'], [])
    r = await page.ev('''(async () => {
      const t = __dt.table('Students'); const h = t.col('height (cm)').id;
      const o = {}; o[h + '|testMean'] = { mu: 165 };
      const rep = await __dt.open('Students', { y: ['height (cm)', 'sex'] }, o);
      const out = {};
      const run = async (title, path, key, n) => { await __help.menu(title, path, rep, n); out[key] = await __help.form(); };
      await run('height (cm)', ['Test Mean…'], 'mean');
      await run('height (cm)', ['Test Std Dev…'], 'sd');
      await run('height (cm)', ['Test Equivalence…'], 'equiv');
      await run('height (cm)', ['Confidence Interval', 'Other…'], 'ci');
      await run('height (cm)', ['Prediction Interval…'], 'pi');
      await run('height (cm)', ['Tolerance Interval…'], 'ti');
      await run('height (cm)', ['Capability Analysis…'], 'cap');
      await run('height (cm)', ['Histogram Options', 'Set Bin Width…'], 'bin');
      await run('height (cm)', ['Display Options', 'Customize Summary Statistics…'], 'stats');
      await run('Test Mean', ['Bayes Factor…'], 'bf');
      await run('sex', ['Test Probabilities…'], 'probs');
      await run('sex', ['Confidence Interval', 'Other…'], 'cicat');
      await run('Distributions', ['Arrange in Rows…'], 'rows');
      SM.app.closeReport(rep);
      return out; })()''')
    if isinstance(r, str):
        print(r)
    want = {'mean': ['Specify hypothesized mean', 'True standard deviation, for a z test (optional)'], 'sd': ['Specify hypothesized standard deviation'],
            'equiv': ['Lower bound', 'Upper bound'], 'ci': ['1 − α'], 'pi': ['1 − α', 'Number of future values'], 'ti': ['Confidence, 1 − α', 'Proportion covered'],
            'cap': ['Lower spec limit', 'Target', 'Upper spec limit'], 'bin': ['Bin width (empty: automatic)'], 'bf': ['Scale r of the Cauchy prior on δ'],
            'cicat': ['1 − α'], 'rows': ['Plots per row (0: as many as fit)']}
    for k, fields in want.items():
        check(f'the {k} form\'s (i) lists its fields, explained', (r[k]['fields'], r[k]['shortest'] > 40), (fields, True))
    check('Customize Summary Statistics: every statistic explained', (r['stats']['fields'] == r['stats']['labels'], len(r['stats']['fields']), r['stats']['shortest'] > 10), (True, 29, True))
    check('Test Probabilities: one entry for the levels\' probabilities', (r['probs']['labels'], r['probs']['fields']), (['F', 'M'], ['Each level']))
    check('the Bayes Factor form\'s (i) builds on its topic', (r['bf']['title'], r['bf']['headings'][-1]), ('Bayes Factor', 'Fields'))
    check('every (i) of the open forms has a topic', [x['noTopic'] for x in r.values()], [[]] * len(r))
    # Test Rate, on a column of counts
    r = await page.ev('''(async () => {
      const t = new SM.Table({ name: 'Help counts', columns: [{ name: 'events', dataType: 'numeric', values: [0, 1, 3, 2, 0, 4, 1, 2] }, { name: 'years', dataType: 'numeric', values: [1, 2, 3, 2, 1, 4, 2, 3] }] });
      SM.app.addTable(t);
      const rep = await __dt.open('Help counts', { y: ['events'] });
      await __help.menu('events', ['Test Rate…'], rep);
      const f = await __help.form();
      SM.app.closeReport(rep); SM.app.closeTable(t);
      return f; })()''')
    if isinstance(r, str):
        print(r)
    check('Test Rate\'s (i): its topic, then its fields', (r['title'], r['fields'], r['shortest'] > 60, r['noTopic']),
          ('Test Rate', ['Hypothesized rate (events per unit of exposure)', 'Exposure', 'Test', 'Confidence interval'], True, []))


asyncio.run(main())
sys.exit(check.done())
