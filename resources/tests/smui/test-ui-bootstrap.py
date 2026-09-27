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
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, wait_engine

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


asyncio.run(main())
sys.exit(check.done())
