#!/usr/bin/env python3
"""Bootstrap on a report table (smui-bootstrap.js, bootstrap.py) in a real
browser: the right-click item (enabled on a numeric column, not on a text
one, not in the Bootstrap report itself), the dialog, the progress and
Stop, the Bootstrap Results table (BootID 0 the report, each sample the
platform run again on the rows the seeded sampler draws, checked against
the backend called directly on those rows), the Bootstrap report against
bootstrap.report, a two-column table (Distribution's Summary Statistics)
with BCa limits, a By group resampled within itself, the report left as it
was (no plots, cache entries or code from the reruns), a project round
trip, the dark theme and phone width.

    python3 resources/tests/smui/test-ui-bootstrap.py
"""
import asyncio
import json
import math
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, wait_engine
from test_charts import GRAPHS_JS, maxdiff, run_graph

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()

OPEN_FM = '''(async () => {
  const t = SM.app.current; const P = SM.platforms.get('fitmodel');
  const h = t.col('height (cm)'), w = t.col('weight (kg)');
  const rep = SM.app.openReport(P, { roles: { y: [w.id] }, options: {}, effects: [{ cols: [h.id], names: [h.name], nest: [], nestNames: [], random: false }] }, t);
  await new Promise(res => rep.on('done', res));
  return true;
})()'''

# the report table under an outline of the last report, and a right click on a cell of a column
RIGHT = '''((title, colLabel) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim() === title);
  const tbls = [...h.parentElement.querySelectorAll('table.sm-rt, table.sm-kv')];
  const tbl = colLabel == null ? tbls[0] : tbls.find(t => [...t.querySelectorAll('thead th')].some(th => th.textContent === colLabel));
  const ci = colLabel == null ? 1 : [...tbl.querySelectorAll('thead th')].findIndex(th => th.textContent === colLabel);
  const td = tbl.querySelector('tbody tr').children[ci];
  const r = td.getBoundingClientRect();
  td.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: r.left + 3, clientY: r.top + 3 }));
  const items = [...document.querySelectorAll('.sm-menu button')].map(b => [b.textContent.replace(/^[✓ ]*/, ''), b.disabled]);
  return items.filter(([l]) => /Bootstrap/.test(l));
})'''


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


async def main():
    page = await open_page(f'{BASE}/smui.html?example=students', width=1400, height=1000)
    check('engine ready', await wait_engine(page), 'ready')
    check('the Bootstrap platform is registered, in no menu', await page.ev("!!SM.platforms.get('bootstrap') && !JSON.stringify(SM.app.menuItems('Analyze')).includes('\"Bootstrap')"), True)
    await page.ev(OPEN_FM)
    items = await page.ev(f'({RIGHT})("Parameter Estimates", "Estimate")')
    check('right click on Estimate: Bootstrap Estimate…, enabled', items, [['Bootstrap Estimate…', False]])
    await page.ev("SM.ui.closeMenus()")
    items = await page.ev(f'({RIGHT})("Parameter Estimates", "Term")')
    check('on the Term column: disabled', [i[1] for i in items], [True])
    await page.ev("SM.ui.closeMenus()")

    # ---- the dialog: 30 samples, seed 5
    before = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; window.__rep = rep;
      return { plots: rep.plots.length, cache: rep.cache.size, code: rep.pythonScript(), reports: SM.app.reports.length, tables: SM.app.tables.length }; })()''')
    await page.ev(f'({RIGHT})("Parameter Estimates", "Estimate")')
    r = await page.ev('''(async () => {
      [...document.querySelectorAll('.sm-menu button')].find(b => /Bootstrap Estimate/.test(b.textContent)).click();
      await new Promise(r => setTimeout(r, 250));
      const dlg = [...document.querySelectorAll('.sm-dialog')].pop();
      const title = dlg.querySelector('h2').textContent;
      const inputs = [...dlg.querySelectorAll('input')];
      inputs[0].value = '30'; inputs[1].value = '5';
      [...dlg.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'OK').click();
      const n0 = SM.app.reports.length;
      for (let i = 0; i < 600 && SM.app.reports.length === n0; i++) await new Promise(r => setTimeout(r, 100));
      const b = SM.app.reports[SM.app.reports.length - 1];
      if (b.body.classList.contains('is-running') || !b.body.querySelector('.sm-ob')) await new Promise(res => b.on('done', res));
      return { title, lead: dlg.querySelector('.sm-dialog-lead').textContent };
    })()''', timeout=300)
    check('the dialog is Bootstrap, and says what it will do', (r['title'], 'collect Estimate' in r['lead'] and '60 rows' in r['lead']), ('Bootstrap', True))
    res = await page.ev('''(async () => {
      const rep = window.__rep, b = SM.app.reports[SM.app.reports.length - 1], t = b.table;
      const rows = SM.bootstrap.sampler(rep.groups()[0].rows, 5)();
      const direct = await SM.engine.call('fitmodel.ls', { y: ['weight (kg)'], effects: [['height (cm)']], rows }, rep.table);
      const est = direct.estimates.rows || direct.estimates;
      const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim() === 'Parameter Estimates');
      const orig = h.parentElement.querySelector('table.sm-rt')._rt.rows.map(r => r.estimate);
      const own = await SM.engine.call('bootstrap.report', { columns: ['Intercept', 'height (cm)'] }, t);
      const lim = [...b.body.querySelectorAll('.sm-ob')].find(o => o.querySelector('.sm-ob-head').textContent.trim() === 'height (cm)').querySelector('table.sm-rt')._rt.rows;
      return { name: t.name, cols: t.columns.map(c => c.name), n: t.nrows, boot: t.col('BootID').values.slice(0, 3), row0: [t.col('Intercept').values[0], t.col('height (cm)').values[0]], orig,
        row1: [t.col('Intercept').values[1], t.col('height (cm)').values[1]], direct: est.map(e => e.estimate), title: b.title,
        limits: lim, want: own.stats[1].limits, outlines: [...b.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent), errors: [...b.body.querySelectorAll('.sm-ob-error')].length,
        after: { plots: rep.plots.length, cache: rep.cache.size, code: rep.pythonScript() }, notes: t.notes };
    })()''', timeout=300)
    check('Bootstrap Results: BootID and a column per term, 31 rows', (res['cols'], res['n'], res['boot']), (['BootID', 'Intercept', 'height (cm)'], 31, [0, 1, 2]))
    check('BootID 0 is the report\'s own estimates', res['row0'], res['orig'])
    check('sample 1 is the model fitted to the rows the sampler draws', all(abs(a - b) < 1e-9 * max(1, abs(b)) for a, b in zip(res['row1'], res['direct'])), True)
    check('the Bootstrap report: a section per term, no errors', (res['title'], res['outlines'], res['errors']), ('Bootstrap of Estimate', ['Intercept', 'height (cm)'], 0))
    check('its limits are bootstrap.report\'s', all(abs(res['limits'][k][c] - res['want'][k][c]) < 1e-12 for k in range(3) for c in ('pct_lower', 'pct_upper', 'bc_lower', 'bc_upper')), True)
    check('the table notes say what it holds', 'seed 5' in res['notes'] and 'Parameter Estimates' in res['notes'], True)
    check('the report bootstrapped is untouched: plots, cache and Python script', (res['after']['plots'], res['after']['cache'], res['after']['code']), (before['plots'], before['cache'], before['code']))
    await shot(page, 'bootstrap-report.png')
    await histogram_code(page)
    items = await page.ev(f'({RIGHT})("height (cm)", "Pct Lower")')
    check('no Bootstrap of the Bootstrap report', [i[1] for i in items], [True])
    await page.ev("SM.ui.closeMenus()")

    # ---- a two-column table, BCa, and a By group
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables[0]))')   # the Students table again
    await page.ev(open_report_js('distribution', {'y': ['height (cm)'], 'by': ['sex']}))
    items = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1];
      const tbl = [...rep.body.querySelectorAll('.sm-ob')].filter(o => o.querySelector('.sm-ob-head').textContent.trim() === 'Summary Statistics')[1].querySelector('table.sm-kv');
      const td = tbl.querySelector('td:nth-child(2)'); const r = td.getBoundingClientRect();
      td.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: r.left + 3, clientY: r.top + 3 }));
      const it = [...document.querySelectorAll('.sm-menu button')].map(b => [b.textContent.replace(/^[✓ ]*/, ''), b.disabled]).filter(([l]) => /Bootstrap|Make into/.test(l));
      SM.ui.closeMenus(); return it; })()''')
    check('Summary Statistics (a two-column table) has Make into Data Table and Bootstrap…', items, [['Make into Data Table', False], ['Bootstrap…', False]])
    res = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const ob = [...rep.body.querySelectorAll('.sm-ob')].filter(o => o.querySelector('.sm-ob-head').textContent.trim() === 'Summary Statistics')[1];
      const tbl = ob.querySelector('table.sm-kv');
      const group = SM.bootstrap.locate(tbl).titles[0];
      const t = await SM.bootstrap.run(tbl, tbl._rt.columns[1], { B: 40, seed: 9, bca: true });
      const g = rep.groups().find(g => `${rep.title} ${g.label}` === group);
      const rows = SM.bootstrap.sampler(g.rows, 9)();
      const h = rep.table.col('height (cm)').values, sex = rep.table.col('sex').values;
      await new Promise(r => setTimeout(r, 800));
      const b = SM.app.reports[SM.app.reports.length - 1];
      const heads = [...b.body.querySelectorAll('.sm-ob')].find(o => o.querySelector('.sm-ob-head').textContent.trim() === 'Mean').querySelector('table.sm-rt')._rt.columns.map(c => c.label);
      return { group, cols: t.columns.map(c => c.name), mean1: t.col('Mean').values[1], want: rows.reduce((a, r) => a + h[r], 0) / rows.length,
        sexes: [...new Set(rows.map(r => sex[r]))], label: g.label, n: g.rows.length, title: b.title, heads, jack: (b.spec.options.jackknife || {}).Mean?.length };
    })()''', timeout=300)
    check('the rows of a two-column table become the columns', res['cols'], ['BootID', 'Mean', 'Std Dev', 'Std Err Mean', 'Upper 95% Mean', 'Lower 95% Mean', 'N'])
    check('a By group is resampled within itself', (res['sexes'], res['label']), ([res['label'].split('=')[1]], res['label']))
    check.near('sample 1\'s mean is the mean of the rows drawn', res['mean1'], res['want'], 1e-12)
    check('named by the table: Bootstrap of Summary Statistics, with BCa limits', (res['title'], res['heads'][-2:], res['jack']), ('Bootstrap of Summary Statistics', ['BCa Lower', 'BCa Upper'], res['n']))

    # ---- Stop keeps what is done
    res = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'fitmodel');
      const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim() === 'Parameter Estimates');
      const tbl = h.parentElement.querySelector('table.sm-rt');
      const p = SM.bootstrap.run(tbl, tbl._rt.columns.find(c => c.label === 'Estimate'), { B: 5000, seed: 1, show: false });
      await new Promise(r => setTimeout(r, 700));
      const stop = [...document.querySelectorAll('.sm-dialog .sm-btn')].find(b => b.textContent === 'Stop');
      stop.click();
      const t = await p;
      return { n: t.nrows, open: !!document.querySelector('.sm-boot-progress') };
    })()''', timeout=300)
    check('Stop ends it early and keeps the samples done', (1 < res['n'] < 5001, res['open']), (True, False))

    # ---- a project keeps the Bootstrap report
    res = await page.ev('''(async () => {
      const b = SM.app.reports.find(r => r.platform.id === 'bootstrap' && r.spec.options.jackknife);
      const t = b.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [b.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      if (back.body.classList.contains('is-running') || !back.body.querySelector('.sm-ob')) await new Promise(res => back.on('done', res));
      const out = { title: back.title, heads: [...back.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent).slice(0, 2), bca: back.body.innerText.includes('BCa Lower'), newTable: back.table !== t };
      SM.app.closeReport(back); SM.app.closeTable(back.table);
      return out;
    })()''', timeout=300)
    check('a project opens the Bootstrap report again, BCa and all', (res['title'], res['heads'], res['bca'], res['newTable']), ('Bootstrap of Summary Statistics', ['Mean', 'Std Dev'], True, True))

    # ---- dark theme and phone width
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === 'bootstrap')))")
    await asyncio.sleep(1.2)
    await shot(page, 'bootstrap-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    check('phone width: no sideways scroll', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    check('no script errors', page.errors, [])
    await page.close()


# ---- the histograms' matplotlib code --------------------------------------------------------------
# Under each histogram of the Bootstrap report a block that draws it: run in the page's own Python
# (the notebook's runner), its bars are the page's bins' counts of the bootstrap values, its lines
# the original estimate and the 95% percentile limits; then with rows of the Bootstrap Results table
# excluded, which the code leaves out too.
BINS = '''(() => { const b = SM.app.reports[SM.app.reports.length - 1];
  // each histogram's bins, and its bars as Plotly counted them (calcdata: each bar's centre p and count s)
  return b.plots.filter((p) => p.box.isConnected).map((p) => [p.opts.title, { ...p.traces[0].xbins, bars: (p.box.calcdata[0] || []).map((c) => [c.p, c.s]) }]); })()'''


def expected_counts(xs, bins):
    start, size = bins['start'], bins['size']
    nb = max(1, round((bins['end'] - start) / size))
    counts = [0] * nb
    for v in xs:
        if v is None or not math.isfinite(v):
            continue
        k = math.floor((v - start) / size + 1e-9)
        if 0 <= k < nb:
            counts[k] += 1
    return [start + (i + 0.5) * size for i in range(nb)], counts


async def check_histograms(page, tag):
    r = await page.ev('(async () => { const b = SM.app.reports[SM.app.reports.length - 1]; return { g: await __gr.graphs(b), undrawn: __gr.take() }; })()', timeout=300)
    bins = dict((t, b) for t, b in await page.ev(BINS))
    check(f'{tag}: a histogram per term, each drawn, each with its code block under it ending in plt.show()',
          ([g['label'] for g in r['g']], r['undrawn'], [bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()' for g in r['g']]),
          (['Intercept bootstrap values', 'height (cm) bootstrap values'], [], [True, True]))
    for g in r['g']:
        lab = f'{tag}: {g["label"]}'
        F, err = await run_graph(page, g, 'SM.app.reports[SM.app.reports.length - 1].table')
        check(f'{lab}: the code runs in the page', err, None)
        if not F:
            continue
        F = F[0]
        ax = F['axes'][0]
        mids, counts = expected_counts(g['traces'][0]['x'], bins[g['label']])
        check(f'{lab}: a bar for each of the page\'s bins, as high as its count of the bootstrap values',
              (len(ax['bars']), [b['h'] for b in ax['bars']]), (len(counts), [float(c) for c in counts]))
        drawn = {round(p_, 9): c for p_, c in bins[g['label']]['bars'] if c}
        check(f'{lab}: the bars Plotly draws, the same counts at the same places',
              {round(b['x'] + b['w'] / 2, 9): b['h'] for b in ax['bars'] if b['h']}, {k: float(v) for k, v in drawn.items()})
        check.near(f'{lab}: the bars\' centres', maxdiff([b['x'] + b['w'] / 2 for b in ax['bars']], mids), 0, 1e-9)
        check.near(f'{lab}: the bars\' width (the bin less the gap)', ax['bars'][0]['w'] if ax['bars'] else None, 0.98 * bins[g['label']]['size'], 1e-12)
        vl = sorted(ln['x'][0] for ln in ax['lines'] if len(ln['x']) == 2 and ln['x'][0] == ln['x'][1])
        check.near(f'{lab}: the lines at the original estimate and the 95% percentile limits', maxdiff(vl, sorted(s['x0'] for s in g['shapes'])), 0, 1e-12)
        check(f'{lab}: solid at the original, dashed at the limits', sorted(ln['ls'] for ln in ax['lines']), sorted(['-' if s['dash'] == 'solid' else '--' for s in g['shapes']]))
        check(f'{lab}: the titles and the size', (ax['title'], ax['xlabel'], ax['ylabel'], F['size']), (g['label'], g['titles']['x'], g['titles']['y'], [g['w'] / 100, g['h'] / 100]))
    return r['g']


async def histogram_code(page):
    await page.ev(GRAPHS_JS)
    await check_histograms(page, 'the Bootstrap report\'s code')
    await page.ev('''(async () => { const b = SM.app.reports[SM.app.reports.length - 1]; b.table.setState([2, 5, 11], 'excluded', true);
      const d = new Promise((res) => b.on('done', res)); b.run(); await d; })()''', timeout=300)
    gs = await check_histograms(page, 'rows of Bootstrap Results excluded')
    check('rows excluded: the code drops them', all('df = df.drop(index=[2, 5, 11])   # the rows the report leaves out' in g['code'] for g in gs) and len(gs) == 2, True)
    back = await page.ev('''(async () => { const b = SM.app.reports[SM.app.reports.length - 1];
      const own = await SM.engine.call('bootstrap.report', { columns: ['Intercept', 'height (cm)'], rows: b.groups()[0].rows }, b.table);
      return own.code; })()''')
    check('rows excluded: the report\'s own code drops them too', 'df = df.drop(index=[2, 5, 11])   # the rows the report leaves out' in back, True)
    await page.ev('''(async () => { const b = SM.app.reports[SM.app.reports.length - 1]; b.table.setState([2, 5, 11], 'excluded', false);
      const d = new Promise((res) => b.on('done', res)); b.run(); await d; })()''', timeout=300)


asyncio.run(main())
sys.exit(check.done())
