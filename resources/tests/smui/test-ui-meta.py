#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Specialized Modeling >
Meta-Analysis.

The simulated Trials example opens from the URL and File > Examples; the
launch dialog opens on the binary layout for it, shows the roles of the
chosen layout only, moves a double-clicked column out of a hidden role,
names the roles it still needs, keeps the casting across layouts and
recalls it; the report's pooled estimates, Q, tau^2 and I^2 are the ones an
inverse-variance and DerSimonian-Laird computation written here gives;
squares, funnel points and leave-one-out points select their rows (one by
a real mouse click) and table selections highlight them; the red
triangles change the method (Redo keeps it), add Hartung-Knapp, switch the
effect size, sort the studies, add a cumulative meta-analysis and a
meta-regression through their dialogs, and save columns; By, Group, the
continuous layout (Hedges' g checked here) and published effects with
their standard errors work; a project keeps the options with the column
ids remapped; the Python script holds the statsmodels calls; every (i)
has a topic; the reports draw in the dark theme and at phone width, where
the forest plot scrolls inside the report.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-meta.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import math
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
BIN = {'events1': ['events (treatment)'], 'total1': ['n (treatment)'], 'events2': ['events (control)'], 'total2': ['n (control)'], 'label': ['study']}
BIN_OPTS = {'layout': 'bin', 'measure': 'or', 'cc': 0.5}


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('%', '').replace('*', ''))


# Pick an item from an outline's red triangle: path is the labels down the
# submenus. wait: wait for the report to run again.
PICK = '''
(async (title, path, wait) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h2, h3, h4').textContent.trim() === title);
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


def pick_js(title, path, wait=True):
    return f'({PICK})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(wait)})'


# The same, for an item that opens a form: fill(dialog) is JavaScript run on
# the form's dialog, then OK, then the report runs again.
PICK_FORM = '''
(async (title, path, fill) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await (%s)(title, path, false);
  await new Promise(r => setTimeout(r, 150));
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

REPORT_STATE = '''
(() => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  return { title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
           errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 400)),
           warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)) };
})()
'''

# The forest plot of the last report: its studies' trace, the texts of its
# effect [CI] column and of the labels.
FOREST = '''
(() => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const p = rep.plots.find(p => /^Forest plot/.test(p.opts.title));
  if (!p) return null;
  const i = p.traces.findIndex(tr => tr.name === 'Studies');
  const texts = p.traces.filter(tr => tr.mode === 'text').map(tr => ({ axis: tr.xaxis, y: tr.y, text: tr.text }));
  return { i, rows: p.rows[i], x: p.traces[i].x, y: p.traces[i].y, texts, xtype: p.userLayout.xaxis.type || 'linear', width: p.width };
})()
'''

# The meta-analysis of the example computed here: log odds ratios with 0.5 in
# every cell of a study with a zero cell, inverse-variance weights,
# DerSimonian and Laird's tau^2.
PAGE_META = '''
(() => {
  const t = SM.app.tables.find(t => t.name === 'Trials');
  const E1 = t.col('events (treatment)').values, N1 = t.col('n (treatment)').values, E2 = t.col('events (control)').values, N2 = t.col('n (control)').values;
  const y = [], v = [], zero = [];
  for (let i = 0; i < t.nrows; i++) {
    let a = E1[i], b = N1[i] - E1[i], c = E2[i], d = N2[i] - E2[i];
    if (!(a && b && c && d)) { a += 0.5; b += 0.5; c += 0.5; d += 0.5; zero.push(i); }
    y.push(Math.log(a * d / (b * c))); v.push(1 / a + 1 / b + 1 / c + 1 / d);
  }
  const sum = (a) => a.reduce((s, x) => s + x, 0);
  const w = v.map(x => 1 / x), W = sum(w);
  const fe = sum(w.map((x, i) => x * y[i])) / W;
  const Q = sum(w.map((x, i) => x * (y[i] - fe) ** 2));
  const C = W - sum(w.map(x => x * x)) / W;
  const k = y.length;
  const tau2 = Math.max(0, (Q - (k - 1)) / C);
  const wr = v.map(x => 1 / (x + tau2)), Wr = sum(wr);
  const re = sum(wr.map((x, i) => x * y[i])) / Wr;
  return { y, v, zero, fe, se_fe: Math.sqrt(1 / W), Q, tau2, re, se_re: Math.sqrt(1 / Wr), i2: Math.max(0, (Q - (k - 1)) / Q), k, wr: wr.map(x => x / Wr) };
})()
'''


async def triangles(page, name, least):
    r = await page.ev(TRIANGLES)
    ok = isinstance(r, dict) and not r['errors'] and r['triangles'] >= least and r['items'] > r['triangles']
    check(f'every red triangle of {name} opens, with its submenus', ok, True)
    if not ok:
        print('   ', r)


async def main():
    page = await open_page(f'{BASE}/smui.html?example=studies', height=1100)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "meta").map(f => f.module + ": " + f.error)')
    check('meta.py imports in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const file = SM.app.menuItems('File');
      const exs = file.find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const an = SM.app.menuItems('Analyze');
      const smi = an.find(i => i.label === 'Specialized Modeling');
      const sm = (typeof smi.submenu === 'function' ? smi.submenu() : smi.submenu).filter(i => !i.separator).map(i => i.label);
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), label: SM.io.EXAMPLES.studies.label, about: SM.io.EXAMPLES.studies.about, inFile: labels.includes(SM.io.EXAMPLES.studies.label), sm };
    })()''')
    check('?example=studies opens the simulated trials', (ex['name'], ex['rows'], len(ex['cols'])), ('Trials', 14, 8))
    check('its columns', ex['cols'], ['study', 'year', 'events (treatment)', 'n (treatment)', 'events (control)', 'n (control)', 'dose (mg)', 'quality'])
    check('it is simulated, and says so', ex['about'].startswith('Simulated'), True)
    check('it is in File > Examples', ex['inFile'], True)
    check('Analyze > Specialized Modeling lists Meta-Analysis after Matched Pairs', 'Meta-Analysis…' in ex['sm'] and ex['sm'].index('Meta-Analysis…') > ex['sm'].index('Matched Pairs…'), True)

    # ---- the launch dialog
    r = await page.ev('''(async () => {
      SM.app.launch('meta');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const visible = () => [...dlg.querySelectorAll('.sm-roles > .sm-role')].filter(r => !r.hidden).map(r => r.querySelector('.sm-btn').textContent);
      const radio = (v) => [...dlg.querySelectorAll('.sm-meta-radio input')].find(i => i.value === v);
      const layout = [...dlg.querySelectorAll('.sm-meta-radio input')].find(i => i.checked).value;
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); const li = items.find(x => x.textContent === name); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const cast = (name, role) => { pick(name); [...dlg.querySelectorAll('.sm-role')].find(r => !r.hidden && r.querySelector('.sm-btn').textContent === role).querySelector('.sm-btn').click(); };
      const bin = visible();
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      ok.click();
      const msg = dlg.querySelector('.sm-launch-msg').textContent;
      const missing = dlg.querySelectorAll('.sm-role.is-missing').length;
      items.find(x => x.textContent === 'events (treatment)').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      await new Promise(r => setTimeout(r, 20));
      const roleOf = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => !r.hidden && r.querySelector('.sm-btn').textContent === label).querySelector('.sm-role-list').textContent;
      const dbl = roleOf('Events (Treatment)');
      cast('n (treatment)', 'N (Treatment)'); cast('events (control)', 'Events (Control)'); cast('n (control)', 'N (Control)'); cast('study', 'Study Label');
      radio('cont').checked = true; radio('cont').dispatchEvent(new Event('change'));
      const cont = visible();
      radio('es').checked = true; radio('es').dispatchEvent(new Event('change'));
      const sel = dlg.querySelector('.sm-meta-opts:not([hidden]) select');
      sel.value = 'var'; sel.dispatchEvent(new Event('change'));
      const es = visible();
      sel.value = 'se'; sel.dispatchEvent(new Event('change'));
      radio('bin').checked = true; radio('bin').dispatchEvent(new Event('change'));
      const kept = ['Events (Treatment)', 'N (Treatment)', 'Events (Control)', 'N (Control)'].map(roleOf);
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { layout, bin, msg, missing, dbl, cont, es, kept, title: rep.title, spec: rep.spec.options,
               outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
               errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent), warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent),
               notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent) };
    })()''')
    check('the dialog opens on the binary layout for a table with events', r['layout'], 'bin')
    check('it shows the roles of that layout only', r['bin'], ['Events (Treatment)', 'N (Treatment)', 'Events (Control)', 'N (Control)', 'Study Label', 'Group', 'Covariates', 'By'])
    check('OK with nothing cast names the roles it needs', r['msg'], 'Two groups, binary outcome: cast a column into Events (Treatment), N (Treatment), Events (Control), N (Control)')
    check('and marks them', r['missing'], 4)
    check('a double click casts into the first shown role, not a hidden one', r['dbl'], 'events (treatment)')
    check('the continuous layout shows its roles', r['cont'], ['N (Treatment)', 'Mean (Treatment)', 'Std Dev (Treatment)', 'N (Control)', 'Mean (Control)', 'Std Dev (Control)', 'Study Label', 'Group', 'Covariates', 'By'])
    check('the effect layout, with variances, relabels its role', r['es'], ['Effect', 'Variance', 'Study Label', 'Group', 'Covariates', 'By'])
    check('back on the binary layout its columns are still cast', r['kept'], ['events (treatment)', 'n (treatment)', 'events (control)', 'n (control)'])
    check('the report\'s title', r['title'], 'Meta-Analysis of Odds Ratios')
    check('the launch options are the report\'s', (r['spec'].get('layout'), r['spec'].get('measure'), r['spec'].get('cc')), ('bin', 'or', 0.5))
    check('the outlines', r['outlines'], ['Meta-Analysis of Odds Ratios', 'Forest Plot', 'Summary Estimates', 'Heterogeneity', 'Study Effects', 'Funnel Plot', "Egger's Regression Test", "Begg's Rank Correlation", 'Leave-One-Out'])
    check('no errors', r['errors'], [])
    check('no warnings (fourteen studies are enough for the small-study tests)', r['warnings'], [])
    check('the zero-cell study is named with its correction', any(n.startswith('Row 6 has a zero cell: 0.5 added to every cell') for n in r['notes']), True)
    await shot(page, 'meta-01-report.png')

    # Recall fills a new dialog with the last launch
    r = await page.ev('''(async () => {
      SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'Trials')));
      SM.app.launch('meta');
      await new Promise(r => setTimeout(r, 200));
      const dlg = document.querySelectorAll('.sm-launch-dialog');
      const d = dlg[dlg.length - 1];
      [...d.querySelectorAll('.sm-radio, .sm-meta-radio input')].forEach(i => { if (i.value === 'es') { i.checked = true; i.dispatchEvent(new Event('change')); } });
      [...d.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'Recall').click();
      await new Promise(r => setTimeout(r, 50));
      const layout = [...d.querySelectorAll('.sm-meta-radio input')].find(i => i.checked).value;
      const roles = [...d.querySelectorAll('.sm-role')].filter(r => !r.hidden).map(r => r.querySelector('.sm-role-list').textContent);
      [...d.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'Cancel').click();
      SM.app.showTab(SM.app.tabOf(SM.app.reports[SM.app.reports.length - 1]));
      return { layout, roles };
    })()''')
    check('Recall brings back the layout', r['layout'], 'bin')
    check('and the columns', r['roles'][:5], ['events (treatment)', 'n (treatment)', 'events (control)', 'n (control)', 'study'])
    # Redo > Relaunch Analysis opens the dialog as the report was launched
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      rep.relaunch();
      await new Promise(r => setTimeout(r, 300));
      const ds = document.querySelectorAll('.sm-launch-dialog'); const d = ds[ds.length - 1];
      const layout = [...d.querySelectorAll('.sm-meta-radio input')].find(i => i.checked).value;
      const box = d.querySelector('.sm-meta-launch');
      const top = box.classList.contains('is-top') && box.compareDocumentPosition(d.querySelector('.sm-roles')) === Node.DOCUMENT_POSITION_FOLLOWING;
      const roles = [...d.querySelectorAll('.sm-role')].filter(r => !r.hidden).map(r => r.querySelector('.sm-role-list').textContent);
      const done = new Promise(res => rep.on('done', res));
      [...d.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
      await done;
      return { layout, top, roles, title: rep.title, errors: rep.body.querySelectorAll('.sm-ob-error').length };
    })()''')
    check('Relaunch opens on the report\'s layout, the layout part above the roles', (r['layout'], r['top']), ('bin', True))
    check('with its columns cast', r['roles'][:5], ['events (treatment)', 'n (treatment)', 'events (control)', 'n (control)', 'study'])
    check('and OK redraws the same report', (r['title'], r['errors']), ('Meta-Analysis of Odds Ratios', 0))

    # ---- the numbers against a computation in the page
    js = await page.ev(PAGE_META)
    log_t = await page.ev(table_under_js('Summary Estimates', 1))
    rows = {(row[0], row[1]): row for row in log_t[1:]}
    fe = rows[('Fixed effect', 'Inverse variance')]
    dl = rows[('Random effects ◆', 'DerSimonian–Laird')]
    check.near('fixed effect = Σwy/Σw of the log odds ratios computed here', num(fe[2]), js['fe'], 1e-6)
    check.near('its standard error 1/√Σw', num(fe[3]), js['se_fe'], 1e-6)
    check.near('DerSimonian–Laird random effects as computed here', num(dl[2]), js['re'], 1e-6)
    check.near('its standard error', num(dl[3]), js['se_re'], 1e-6)
    ratio_t = await page.ev(table_under_js('Summary Estimates', 0))
    check('the ratio table first, in odds ratios', ratio_t[0][:5], ['Model', 'Method', 'Odds Ratio', 'Lower 95%', 'Upper 95%'])
    check.near('the pooled odds ratio is exp of the log', num([row for row in ratio_t[1:] if row[1] == 'DerSimonian–Laird'][0][2]), math.exp(js['re']), 1e-6)
    check('five pooled rows: fixed (inverse variance, Mantel–Haenszel), DL, PM, REML', [row[1] for row in ratio_t[1:]], ['Inverse variance', 'Mantel–Haenszel', 'DerSimonian–Laird', 'Paule–Mandel', 'REML'])
    q_t = await page.ev(table_under_js('Heterogeneity', 0))
    check.near('Cochran\'s Q as computed here', num(q_t[1][1]), js['Q'], 1e-6)
    h_t = await page.ev(table_under_js('Heterogeneity', 1))
    hm = {row[0]: row for row in h_t[1:]}
    check.near('I² as computed here', num(hm['I² (%)'][1]) / 100, js['i2'], 1e-6)
    check.near('τ² (DerSimonian–Laird) as computed here', num(hm['τ² (DerSimonian–Laird)'][1]), js['tau2'], 1e-6)
    f = await page.ev(FOREST)
    ci_texts = [t for t in f['texts'] if t['axis'] == 'x3' and len(t['text']) > 1][0]['text']
    y0 = js['y'][0]
    z = 1.959963984540054
    se0 = math.sqrt(js['v'][0])
    check('the forest plot writes each study\'s odds ratio [95% CI]', ci_texts[0], f'{math.exp(y0):.2f} [{math.exp(y0 - z * se0):.2f}, {math.exp(y0 + z * se0):.2f}]'.replace('-', '−'))
    wtexts = [t for t in f['texts'] if t['axis'] == 'x5' and len(t['text']) > 1][0]['text']
    check.near('its random weights of the studies sum to 100%', sum(num(x) for x in wtexts[:js['k']]), 100.0, 2e-3)
    check.near('and are the weights computed here', num(wtexts[1]), round(100 * js['wr'][1], 1), 1e-9)
    check('ratios on a log axis', f['xtype'], 'log')
    check('the squares are linked, one row each, in table order', f['rows'], list(range(14)))

    # ---- linking both ways
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => /^Forest plot/.test(p.opts.title));
      const i = p.traces.findIndex(tr => tr.name === 'Studies');
      p._click({ points: [{ curveNumber: i, pointNumber: 3 }], event: {} });
      const sel = t.selectedRows();
      t.select([0, 5]);
      await new Promise(r => setTimeout(r, 150));
      const sp = p.box.data[i].selectedpoints;
      t.select([]);
      return { sel, sp };
    })()''')
    check('a click on a square selects its row', r['sel'], [3])
    check('rows selected in the table highlight their squares', r['sp'], [0, 5])
    # a real mouse click on a square
    pos = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => /^Forest plot/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      await new Promise(r => setTimeout(r, 300));
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      const gd = p.box, i = p.traces.findIndex(tr => tr.name === 'Studies');
      const xa = gd._fullLayout.xaxis, ya = gd._fullLayout.yaxis;
      const k = 10, b = gd.getBoundingClientRect();
      return { x: b.left + xa._offset + xa.l2p(xa.d2l(p.traces[i].x[k])), y: b.top + ya._offset + ya.l2p(ya.d2l(p.traces[i].y[k])), row: p.rows[i][k] };
    })()''')
    await page.click(pos['x'], pos['y'])
    await asyncio.sleep(0.4)
    sel = await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()')
    check('a mouse click on a square selects that study\'s row', sel, [pos['row']])
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const fu = rep.plots.find(p => /^Funnel plot/.test(p.opts.title));
      const i = fu.traces.findIndex(tr => tr.name === 'Studies');
      fu._click({ points: [{ curveNumber: i, pointNumber: 7 }], event: {} });
      const a = t.selectedRows();
      const lo = rep.plots.find(p => p.opts.title === 'Leave-one-out estimates');
      const j = lo.traces.findIndex(tr => tr.name === 'Estimates');
      lo._click({ points: [{ curveNumber: j, pointNumber: 2 }], event: {} });
      const b = t.selectedRows();
      t.select([4]);
      await new Promise(r => setTimeout(r, 150));
      const fsp = fu.box.data[i].selectedpoints, lsp = lo.box.data[j].selectedpoints;
      const tr = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Study Effects').parentElement.querySelectorAll('tbody tr')[9];
      tr.click();
      const c = t.selectedRows();
      t.select([]);
      return { a, b, fsp, lsp, c };
    })()''')
    check('a funnel point selects its row', r['a'], [7])
    check('a leave-one-out point selects the study left out', r['b'], [2])
    check('selected rows light up in the funnel and leave-one-out plots', (r['fsp'], r['lsp']), ([4], [4]))
    check('a line of Study Effects selects its row', r['c'], [9])

    # ---- the red triangles
    await triangles(page, 'the report', 5)
    out = await page.ev(pick_js('Meta-Analysis of Odds Ratios', ['Random-Effects Method', 'REML']))
    mark = await page.ev(table_under_js('Summary Estimates', 0))
    check('Random-Effects Method > REML moves the ◆', [row[1] for row in mark[1:] if '◆' in row[0]], ['REML'])
    await page.ev('(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')
    mark = await page.ev(table_under_js('Summary Estimates', 0))
    check('Redo keeps the method', [row[1] for row in mark[1:] if '◆' in row[0]], ['REML'])
    out = await page.ev(pick_js('Meta-Analysis of Odds Ratios', ['Hartung–Knapp Intervals']))
    hk = await page.ev(table_under_js('Summary Estimates', 2))
    check('Hartung–Knapp adds its table with t and DF', (hk[0][:1], 't Ratio' in hk[0], 'DF' in hk[0]), (['Model'], True, True))
    f = await page.ev(FOREST)
    labs = [t for t in f['texts'] if t['axis'] == 'x2' and len(t['text']) > 1][0]['text']
    check('and the forest plot says so', any('Random effects (REML, HK)' in s for s in labs), True)
    out = await page.ev(pick_js('Forest Plot', ['Sort Studies', 'By Effect']))
    f = await page.ev(FOREST)
    check('Sort Studies > By Effect puts the smallest effect first', f['x'][0] == min(f['x']) and f['x'] == sorted(f['x']), True)
    out = await page.ev(pick_js('Forest Plot', ['Mantel–Haenszel Fixed Effect']))
    f = await page.ev(FOREST)
    labs = [t for t in f['texts'] if t['axis'] == 'x2' and len(t['text']) > 1][0]['text']
    mh_row = [row for row in (await page.ev(table_under_js('Summary Estimates', 0)))[1:] if row[1] == 'Mantel–Haenszel'][0]
    cis = [t for t in f['texts'] if t['axis'] == 'x3' and len(t['text']) > 1][0]['text']
    check('Mantel–Haenszel Fixed Effect: the fixed diamond is the Mantel–Haenszel estimate', ('<b>Fixed effect (Mantel–Haenszel)</b>' in labs, any(c.startswith(f'<b>{num(mh_row[2]):.2f} [') for c in cis)), (True, True))
    wf = [t for t in f['texts'] if t['axis'] == 'x4' and len(t['text']) > 1][0]['text']
    check.near('and the fixed weights of the studies are the Mantel–Haenszel ones, summing to 100%', sum(num(x) for x in wf[:14]), 100.0, 2e-3)
    out = await page.ev(pick_js('Meta-Analysis of Odds Ratios', ['Effect Size', 'Risk Ratio']))
    st = await page.ev(REPORT_STATE)
    check('Effect Size > Risk Ratio retitles the report', st['title'], 'Meta-Analysis of Risk Ratios')
    check('without errors', st['errors'], [])
    year_id = await page.ev('SM.app.tables.find(t => t.name === "Trials").col("year").id')
    out = await page.ev(pick_form_js('Meta-Analysis of Risk Ratios', ['Cumulative Meta-Analysis…'], f'd.querySelector(".sm-form select").value = {json.dumps(year_id)};'))
    check('Cumulative Meta-Analysis… by year, from its dialog', 'Cumulative Meta-Analysis by year' in out, True)
    cu = await page.ev(table_under_js('Cumulative Meta-Analysis by year', 0))
    years = [int(num(row[1])) for row in cu[1:]]
    check('its studies come in by year', years == sorted(years) and len(years) == 14, True)
    out = await page.ev(pick_form_js('Meta-Analysis of Risk Ratios', ['Meta-Regression…'], '''const l = [...d.querySelectorAll('.sm-form label')].find(x => x.textContent.startsWith('dose (mg)')); document.getElementById(l.htmlFor).checked = true;'''))
    check('Meta-Regression… on the dose, from its dialog', 'Meta-Regression' in out, True)
    pe = await page.ev(table_under_js('Meta-Regression', 1))
    check('its terms', [row[0] for row in pe[1:]], ['Intercept', 'dose (mg)'])
    bub = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => /^Bubble plot/.test(p.opts.title)); if (!p) return null; const i = p.traces.findIndex(t => t.name === 'Studies'); return { title: p.opts.title, rows: p.rows[i].length, sizes: new Set(p.traces[i].marker.size).size }; })()''')
    check('a bubble plot of the risk ratio by dose, every study linked', (bub['title'], bub['rows']), ('Bubble plot of Risk Ratio by dose (mg)', 14))
    check('bubbles sized by weight', bub['sizes'] > 3, True)
    await shot(page, 'meta-02-options.png')
    await triangles(page, 'the report with every outline', 7)
    ncol = await page.ev('SM.app.tables.find(t => t.name === "Trials").columns.length')
    await page.ev(pick_js('Meta-Analysis of Risk Ratios', ['Save Columns', 'Effect Size'], wait=False))
    await page.ev(pick_js('Meta-Analysis of Risk Ratios', ['Save Columns', 'Weights, Random Effects'], wait=False))
    await asyncio.sleep(0.8)
    sv = await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === "Trials"); const c = t.columns.slice(-2); return { names: c.map(x => x.name), n: t.columns.length, first: c[0].values[0], w: c[1].values.reduce((a, b) => a + b, 0) }; })()''')
    se_t = await page.ev(table_under_js('Study Effects', 0))
    check('Save Columns adds the effect size and the weights', (sv['n'] - ncol, sv['names']), (2, ['Log Risk Ratio', 'Weight % Random (REML)']))
    check.near('the saved log risk ratio is the study\'s', sv['first'], num(se_t[1][1]), 1e-6)
    check.near('the saved weights sum to 100', sv['w'], 100.0, 1e-9)

    # ---- By and Group
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Trials")))')
    r = await page.ev(open_report_js('meta', {**BIN, 'by': ['quality']}, BIN_OPTS))
    tops = [o for o in r['outlines'] if o.startswith('Meta-Analysis of Odds Ratios')]
    check('By: a report per level', tops, ['Meta-Analysis of Odds Ratios quality=low', 'Meta-Analysis of Odds Ratios quality=moderate', 'Meta-Analysis of Odds Ratios quality=high'])
    check('By: no errors, even for a level with one study', r['errors'], [])
    r = await page.ev(open_report_js('meta', {**BIN, 'group': ['quality']}, BIN_OPTS))
    check('Group: a Subgroups outline', 'Subgroups' in r['outlines'], True)
    sgt = await page.ev(table_under_js('Subgroups', 1))
    check('with the test of subgroup differences, fixed and random', [row[0] for row in sgt[1:]], ['Fixed effect', 'Random effects (DerSimonian–Laird)'])
    f = await page.ev(FOREST)
    labs = [t for t in f['texts'] if t['axis'] == 'x2' and len(t['text']) > 1][0]['text']
    check('the forest plot lists the studies by subgroup, with subtotals', ('<b>low</b>' in labs, 'Subtotal, random effects' in labs), (True, True))
    await shot(page, 'meta-03-subgroups.png')

    # ---- two groups, continuous: Hedges' g
    await page.ev('''(() => {
      const r = SM.util.rng('meta-test-means');
      const k = 9, c = { study: [], n1: [], m1: [], s1: [], n2: [], m2: [], s2: [] };
      for (let i = 0; i < k; i++) {
        c.study.push('S' + (i + 1)); c.n1.push(r.int(15, 80)); c.n2.push(r.int(15, 80));
        c.m1.push(+(10.5 + r.normal(0, 0.4)).toFixed(2)); c.m2.push(+(10 + r.normal(0, 0.4)).toFixed(2));
        c.s1.push(+(1.5 + r.u()).toFixed(2)); c.s2.push(+(1.5 + r.u()).toFixed(2));
      }
      SM.app.addTable(new SM.Table({ name: 'Means', columns: [{ name: 'study', dataType: 'character', values: c.study },
        { name: 'n T', dataType: 'numeric', values: c.n1 }, { name: 'mean T', dataType: 'numeric', values: c.m1 }, { name: 'sd T', dataType: 'numeric', values: c.s1 },
        { name: 'n C', dataType: 'numeric', values: c.n2 }, { name: 'mean C', dataType: 'numeric', values: c.m2 }, { name: 'sd C', dataType: 'numeric', values: c.s2 }] }));
    })()''')
    lay = await page.ev('''(async () => { SM.app.launch('meta'); await new Promise(r => setTimeout(r, 200)); const ds = document.querySelectorAll('.sm-launch-dialog'); const d = ds[ds.length - 1];
      const v = [...d.querySelectorAll('.sm-meta-radio input')].find(i => i.checked).value; [...d.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'Cancel').click(); return v; })()''')
    check('a table of means opens the dialog on the continuous layout', lay, 'cont')
    r = await page.ev(open_report_js('meta', {'n1': ['n T'], 'mean1': ['mean T'], 'sd1': ['sd T'], 'n2': ['n C'], 'mean2': ['mean C'], 'sd2': ['sd C'], 'label': ['study']}, {'layout': 'cont', 'measure': 'smd'}))
    check('Hedges\' g: the report', (r['title'], r['errors']), ('Meta-Analysis of Standardized Mean Differences', []))
    g = await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Means'); const v = (n) => t.col(n).values[0];
      const n1 = v('n T'), n2 = v('n C'), N = n1 + n2; const sp = Math.sqrt(((n1 - 1) * v('sd T') ** 2 + (n2 - 1) * v('sd C') ** 2) / (N - 2));
      return (1 - 3 / (4 * N - 9)) * (v('mean T') - v('mean C')) / sp; })()''')
    se_t = await page.ev(table_under_js('Study Effects', 0))
    check('the columns of Study Effects', se_t[0][:2], ['Study', "Hedges' g"])
    check.near('Hedges\' g of the first study, J·(m₁ − m₂)/s_pooled computed here', num(se_t[1][1]), g, 1e-6)
    f = await page.ev(FOREST)
    check('a linear axis for g', f['xtype'], 'linear')

    # ---- published effects: log hazard ratios and standard errors, one row unusable
    await page.ev('''SM.app.addTable(new SM.Table({ name: 'Hazards', columns: [
      { name: 'trial', dataType: 'character', values: ['H1', 'H2', 'H3', 'H4', 'H5', 'H6'] },
      { name: 'log HR', dataType: 'numeric', values: [-0.31, -0.12, -0.45, 0.05, -0.22, -0.4] },
      { name: 'SE', dataType: 'numeric', values: [0.12, 0.2, 0.18, 0.25, 0, 0.15] }] }))''')
    r = await page.ev(open_report_js('meta', {'effect': ['log HR'], 'se': ['SE'], 'label': ['trial']}, {'layout': 'es', 'logRatio': True}))
    check('log ratios: the report', (r['title'], r['errors']), ('Meta-Analysis of Ratios', []))
    check('the row with a zero standard error is left out, and named', any('row 5 (the standard error is not above zero)' in w for w in r['warnings']), True)
    f = await page.ev(FOREST)
    check('ratios on a log axis', f['xtype'], 'log')
    check('five studies in the plot', len(f['rows']), 5)
    check('with five studies the small-study tests warn of their low power', any('little power' in w for w in r['warnings']), True)

    # ---- a project keeps the options, the column ids remapped
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'meta' && r.spec.options.cum);
      const t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const heads = [...back.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3')].map(h => h.textContent);
      const out = { newTable: back.table !== t, heads, method: back.spec.options.method, hksj: back.spec.options.hksj, cumCol: back.table.col(back.spec.options.cum.by)?.name,
                    mreg: (back.spec.options.mreg || []).map(id => back.table.col(id)?.name), errors: [...back.body.querySelectorAll('.sm-ob-error')].length };
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();   // closing a table with a report asks first
      out.closed = !SM.app.tables.includes(back.table);
      return out;
    })()''')
    check('an opened project has its own table', r['newTable'], True)
    check('and keeps the method and Hartung–Knapp', (r['method'], r['hksj']), ('reml', True))
    check('and finds the ordering and covariate columns by their new ids', (r['cumCol'], r['mreg']), ('year', ['dose (mg)']))
    check('and draws the same outlines', ('Cumulative Meta-Analysis by year' in r['heads'], 'Meta-Regression' in r['heads'], r['errors']), (True, True, 0))
    check('the opened table closes again', r['closed'], True)

    # ---- help for every input: the launch dialog (by layout), the red-triangle forms
    await help_inputs(page)

    # ---- the Python script, the (i) topics and Help
    script = await page.ev('SM.app.reports.find(r => r.platform.id === "meta").pythonScript()')
    check('the script holds the statsmodels calls', all(s in script for s in ('combine_effects(', 'effectsize_2proportions(', 'sm.OLS(')), True)
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-meta"); return !!document.getElementById("help-p-meta"); })()')
    check('the platform has its line in Help', helps, True)

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "meta" && r.spec.roles.group && r.spec.roles.group.length)))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2.0)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => r.platform.id === 'meta'); return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)), running: rs.some(r => r.body.classList.contains('is-running')) }; })()''')
    check('the dark theme redraws the reports without errors', st['errors'], [])
    await shot(page, 'meta-04-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports.find(r => r.platform.id === "meta" && r.spec.roles.group && r.spec.roles.group.length); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')
    await asyncio.sleep(0.8)
    wide = await page.ev('document.documentElement.scrollWidth <= innerWidth + 1')
    check('no horizontal page scroll at phone width', wide, True)
    sc = await page.ev('''(() => { const rep = SM.app.reports.find(r => r.platform.id === "meta" && r.spec.roles.group && r.spec.roles.group.length); const s = rep.body.querySelector('.sm-meta-scroll'); return { sw: s.scrollWidth, cw: s.clientWidth, style: getComputedStyle(s).overflowX }; })()''')
    check('the forest plot scrolls sideways inside the report', sc['sw'] > sc['cw'] and sc['style'] == 'auto', True)
    await shot(page, 'meta-05-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


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
  names(p, heading) { const s = p && p.sections.find((x) => x.heading === heading); return s && s.choices.length ? s.choices.map((c) => c[0]) : null; },
  // the shortest text of a section's choices, without what a role takes '(required, ...)'
  shortest(p, heading) { const s = p && p.sections.find((x) => x.heading === heading); return s && s.choices.length ? Math.min(...s.choices.map((c) => c[1].replace(/\s*\([^()]*\)$/, '').length)) : 0; },
  dialog() { return [...document.querySelectorAll('.sm-dialog')].pop(); },
  async menu(title, path, rep) {
    rep = rep || SM.app.reports[SM.app.reports.length - 1];
    const h = [...rep.body.querySelectorAll('.sm-ob-head')].find((x) => x.querySelector('h2, h3, h4').textContent === title);
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
    return { labels, title: p && p.title, fields: this.names(p, 'Fields'), shortest: this.shortest(p, 'Fields'), noTopic: audit.noTopic };
  },
};
"""


async def help_inputs(page):
    """What every input is for, in the (i) panels: the launch dialog's roles
    and its Input Layout part, whose fields follow the chosen layout; the
    Cumulative Meta-Analysis and Meta-Regression forms' fields."""
    await page.ev(HELP_JS)
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Trials")))')
    r = await page.ev('''(async () => {
      SM.app.launch('meta'); await __help.sleep(350);
      const d = [...document.querySelectorAll('.sm-launch-dialog')].pop();
      const info = () => __help.read(d.querySelector('.sm-dialog-head .info-btn'));
      const layout = async (k) => { const rb = d.querySelector(`.sm-meta-radios input[value="${k}"]`); rb.checked = true; rb.dispatchEvent(new Event('change')); await __help.sleep(60); const q = await info(); out[k + 'Roles'] = __help.names(q, 'Roles'); return __help.names(q, 'Input Layout'); };
      let out = {};
      const audit = KvotInfo.audit();
      const p = await info();
      out = { roles: __help.names(p, 'Roles'), rolesShort: __help.shortest(p, 'Roles'), bin: __help.names(p, 'Input Layout'), short: __help.shortest(p, 'Input Layout'), noTopic: audit.noTopic, slots: audit.slots };
      out.es = await layout('es'); out.cont = await layout('cont');
      d.querySelector('.sm-dialog-x').click();
      return out; })()''')
    if isinstance(r, str):
        print(r)
    # the roles of the layout on show: binary at first, then the other two
    rest = ['Study Label', 'Group', 'Covariates', 'By']
    check('the launch dialog\'s (i) lists the roles of the layout on show', r['roles'], ['Events (Treatment)', 'N (Treatment)', 'Events (Control)', 'N (Control)'] + rest)
    check('... the effect and standard error layout\'s', r['esRoles'], ['Effect', 'Std Error'] + rest)
    check('... the continuous layout\'s', r['contRoles'], ['N (Treatment)', 'Mean (Treatment)', 'Std Dev (Treatment)', 'N (Control)', 'Mean (Control)', 'Std Dev (Control)'] + rest)
    check('... each with what it is for, and the layout it belongs to', r['rolesShort'] > 60, True)
    check('the Input Layout fields of the binary layout', (r['bin'], r['short'] > 60), (['Input Layout', 'Effect size', 'Zero cells'], True))
    check('... of the effect and standard error layout', r['es'], ['Input Layout', 'The Std Error column holds', 'Effects are log ratios'])
    check('... of the continuous layout', r['cont'], ['Input Layout', 'Effect size'])
    check('every (i) of the open launch dialog has a topic', (r['noTopic'], r['slots'] >= 2), ([], True))
    r = await page.ev(open_report_js('meta', BIN, BIN_OPTS))
    check('a meta-analysis to work on', r['errors'], [])
    r = await page.ev('''(async () => {
      const top = SM.app.reports[SM.app.reports.length - 1].title;
      const out = {};
      await __help.menu(top, ['Cumulative Meta-Analysis…']); out.cum = await __help.form();
      await __help.menu(top, ['Meta-Regression…']); out.reg = await __help.form();
      return out; })()''')
    if isinstance(r, str):
        print(r)
    check('Cumulative Meta-Analysis: its topic, then its fields', (r['cum']['title'], r['cum']['fields'], r['cum']['shortest'] > 40), ('Cumulative Meta-Analysis', ['Order by', 'Descending'], True))
    check('Meta-Regression: one entry for the columns it lists', (r['reg']['title'], r['reg']['fields'], len(r['reg']['labels']) > 1), ('Meta-Regression', ['Each column'], True))
    check('every (i) of the open forms has a topic', (r['cum']['noTopic'], r['reg']['noTopic']), ([], []))


asyncio.run(main())
sys.exit(check.done())
