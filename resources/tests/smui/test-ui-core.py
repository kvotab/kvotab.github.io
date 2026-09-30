#!/usr/bin/env python3
"""smui.html in a real browser: the frame and Analyze > Distribution.

The page loads without a script error and the Python engine starts; every
(i) has a topic and every Help link a target; an example opens in the grid
with its modeling types and row counts; the Analyze menu lists
Distribution; the launch dialog casts columns into roles; the report shows
the moments and quantiles the backend computed; a click on a histogram bar
selects its rows and a selection in the table lights up the graphs; an
exclusion marks the report stale and Redo uses fewer rows; By gives one
report per level; the Local Data Filter narrows one report; a saved column
lands in the table; cell edits and modeling types do what they say; the
report's Python script is the code of its results; the Python code button
and Show Python Code show the code where it is seen, whatever was opened
or closed before, and a report without code says so; Distribution's interval
methods and Test Rate show what the page computes; dialogs move by their
title bar, a disabled menu item opens no submenu, the tab strip has no
scroll bar; a dialog's (i) explains its roles, options and fields; Print
prints the report as a document from a hidden frame, Save Report as Word
writes a .docx of the open outlines, tables and graphs, and the page's own
print leaves the site around the report out; the page draws in the dark
theme (documents keep the light one) and at phone width; the full window
(no site header or footer, the kvot mark and the theme switch in the menu
bar, kept for the next visit from before the workbench is made).

Start a server on the repository root and headless Chrome (the recipe is in
../rb/README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT (defaults 8791, 9291),
then

    python3 resources/tests/smui/test-ui-core.py

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


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


async def main():
    page = await open_page(f'{BASE}/smui.html?example=students')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    # The page's scripts are deferred and Plotly async: a stand-in in the
    # workbench's frame shows while they load, and the app replaces it
    r = await page.ev('''(async () => {
      const html = await (await fetch('smui.html', { cache: 'no-cache' })).text();
      const doc = new DOMParser().parseFromString(html, 'text/html');
      const own = [...doc.querySelectorAll('script[src*="resources/js/smui-"], script[src*="kvot-info"], script[src*="xlsxwrite"], script[src*="jszip"]')];
      const plotly = doc.querySelector('script[src*="plotly"]');
      return { standin: !!doc.querySelector('#smApp > .sm-boot'), n: own.length, deferred: own.filter(s => s.defer).length, plotlyAsync: !!(plotly && plotly.async),
        gone: !document.querySelector('.sm-boot'), built: !!document.querySelector('#smApp.sm > .sm-menubar') };
    })()''')
    check('the page has a stand-in in the frame while its scripts load', r['standin'], True)
    check('its scripts are deferred (fetched together), Plotly async', (r['deferred'] == r['n'] and r['n'] > 40, r['plotlyAsync']), (True, True))
    check('the app takes the stand-in away', (r['gone'], r['built']), (True, True))
    # The site is published as it is: GitHub Pages' default Jekyll build
    # leaves out files whose names start with an underscore, and without
    # resources/py/smui/__init__.py the engine stopped on every device
    # ("module 'smui' has no attribute 'names'"). The test server here
    # serves every file, so only this check sees it.
    repo = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
    check('the repository root has .nojekyll (GitHub Pages then publishes __init__.py)', os.path.isfile(os.path.join(repo, '.nojekyll')), True)
    failed = await page.ev('SM.engine.failed.filter(f => f.error !== "not written yet").map(f => f.module + ": " + f.error)')
    check('every analysis module that exists imports', failed, [])
    check('scikit-learn waits for its first use', await page.ev("(SM.engine.versions['scikit-learn'] || null)"), None)
    check('no script errors at load', page.errors, [])
    audit = await page.ev('JSON.stringify(KvotInfo.audit())')
    audit = json.loads(audit)
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])

    # ---- the table
    info = await page.ev('''(() => { const t = SM.app.current; return { name: t.name, rows: t.nrows, cols: t.columns.map(c => [c.name, c.modelingType]),
      gridRows: document.querySelectorAll('.sm-view:not([hidden]) .sm-grow').length, panel: [...document.querySelectorAll('.sm-collist li .sm-colname')].map(e => e.textContent),
      counts: [...document.querySelectorAll('.sm-rowcounts tr')].map(tr => tr.textContent) }; })()''')
    check('example table', (info['name'], info['rows']), ('Students', 60))
    check('modeling types', info['cols'], [['id', 'nominal'], ['age', 'ordinal'], ['sex', 'nominal'], ['height (cm)', 'continuous'], ['weight (kg)', 'continuous']])
    check('grid draws only the rows in view', 10 < info['gridRows'] < 60, True)
    check('columns panel', info['panel'], ['id', 'age', 'sex', 'height (cm)', 'weight (kg)'])
    check('rows panel', info['counts'][0], 'All rows60')
    # ---- Help: no tab at the start; Help > Help for This Page opens one with
    # an ×, which closes it; a Read more link opens it at its heading
    r = await page.ev('''(async () => {
      const helpTabs = () => [...document.querySelectorAll('.sm-tab')].filter(b => b.dataset.kind === 'help');
      const atStart = helpTabs().length;
      SM.app.menuItems('Help').find(i => i.label === 'Help for This Page').action();
      const tab = helpTabs()[0];
      const opened = !!tab && tab.classList.contains('is-active') && !SM.app.helpView.hidden;
      const hasX = !!(tab && tab.querySelector('.sm-tabclose'));
      tab.querySelector('.sm-tabclose').click();
      const closed = helpTabs().length === 0 && SM.app.helpView.hidden && !!document.getElementById('help-rowstates');
      KvotInfo.open('panel:rows');
      await new Promise(r => setTimeout(r, 100));
      document.querySelector('.info-panel .info-panel-more').click();
      await new Promise(r => setTimeout(r, 100));
      const again = helpTabs().length === 1 && helpTabs()[0].classList.contains('is-active');
      const h = document.getElementById('help-rowstates').getBoundingClientRect();
      const v = SM.app.helpView.getBoundingClientRect();
      helpTabs()[0].querySelector('.sm-tabclose').click();
      SM.app.showTab(SM.app.tabOf(SM.app.current));
      return { atStart, opened, hasX, closed, again, atHeading: h.top >= v.top - 1 && h.top < v.top + 80 };
    })()''')
    check('no Help tab at the start', r['atStart'], 0)
    check('Help for This Page opens the Help tab', r['opened'], True)
    check('the Help tab has an ×', r['hasX'], True)
    check('the × closes it, and the Help text stays for the links', r['closed'], True)
    check('Read more opens it again at its heading', (r['again'], r['atHeading']), (True, True))

    menu = await page.ev('SM.app.menuItems("Analyze").map(i => i.label || (i.separator ? "—" : ""))')
    check('Analyze lists Distribution first', menu[0], 'Distribution…')
    await shot(page, '01-table.png')

    # ---- the (i) of a dialog: its panel lies above the dimmed backdrop,
    # clicking in it leaves the dialog open, and the dialog moves clear of it
    r = await page.ev('''(async () => {
      SM.app.launch('distribution');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      dlg.querySelector('.sm-dialog-head .info-btn').click();
      await new Promise(r => setTimeout(r, 300));
      const panel = document.querySelector('.info-panel');
      const pr = panel.getBoundingClientRect();
      const top = document.elementFromPoint(pr.left + pr.width / 2, pr.top + pr.height / 2);
      panel.querySelector('.info-panel-body').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      await new Promise(r => setTimeout(r, 50));
      const open = !!document.querySelector('.sm-launch-dialog');
      const clear = dlg.getBoundingClientRect().right <= pr.left + 1;
      KvotInfo.close();
      document.querySelector('.sm-launch-dialog .sm-dialog-x').click();
      return { onTop: panel.contains(top), open, clear };
    })()''')
    check('an (i) panel opened from a dialog is not under its backdrop', r['onTop'], True)
    check('clicking in the panel leaves the dialog open', r['open'], True)
    check('on a wide window the dialog moves clear of the panel', r['clear'], True)

    # ---- the launch dialog: select two columns, press Y, OK
    r = await page.ev('''(async () => {
      SM.app.launch('distribution');
      await new Promise(r => setTimeout(r, 200));
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => items.find(li => li.textContent === name);
      pick('height (cm)').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      pick('sex').dispatchEvent(new MouseEvent('mousedown', { bubbles: true, metaKey: true }));
      const yBtn = [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === 'Y, Columns');
      yBtn.click();
      const cast = [...dlg.querySelectorAll('.sm-role-list')][0].textContent;
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { cast, title: rep.title, open: !!document.querySelector('.sm-launch-dialog'), outlines: [...rep.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent) };
    })()''')
    check('columns cast into Y', r['cast'], 'sexheight (cm)')
    check('dialog closed on OK', r['open'], False)
    check('report outlines', r['outlines'], ['sex', 'height (cm)'])
    stats = await page.ev(table_under_js('Summary Statistics'))
    js = await page.ev('''(() => { const c = SM.app.current.col('height (cm)'); const v = c.values; const n = v.length; const m = v.reduce((a, b) => a + b, 0) / n;
      const sd = Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / (n - 1)); return [SM.util.fmt(m), SM.util.fmt(sd), String(n)]; })()''')
    check('mean, std dev and N as computed in the page', [stats[0][1], stats[1][1], stats[5][1]], js)
    q = await page.ev(table_under_js('Quantiles'))
    check('quantile rows', [row[0] for row in q[1:]], ['100.0%', '99.5%', '97.5%', '90.0%', '75.0%', '50.0%', '25.0%', '10.0%', '2.5%', '0.5%', '0.0%'])
    await asyncio.sleep(1)
    await shot(page, '02-distribution.png')

    # ---- linking
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => p.opts.title === 'height (cm) histogram');
      const bars = p.traces[0];
      const k = bars.x.indexOf(Math.max(...bars.x));
      p._click({ points: [{ curveNumber: 0, pointNumber: k }], event: {} });
      const sel = t.selectedRows();
      const want = p.rows[0][k].slice().sort((a, b) => a - b);
      await new Promise(r => setTimeout(r, 200));
      const comp = p.box.data[p.companions[0].at];
      return { same: JSON.stringify(sel) === JSON.stringify(want), n: sel.length, compTotal: comp.x.reduce((a, b) => a + b, 0), grid: document.querySelectorAll('.sm-grow.is-selected').length >= 0 };
    })()''')
    check('a bar click selects the rows in the bin', r['same'], True)
    check('the selected part is drawn over the bars', r['compTotal'], r['n'])
    r = await page.ev('''(async () => {
      const t = SM.app.current; t.select([0, 1, 2]);
      await new Promise(r => setTimeout(r, 200));
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const sexPlot = rep.plots.find(p => p.opts.title === 'sex bar chart');
      const comp = sexPlot.box.data[sexPlot.companions[0].at];
      return comp.x.reduce((a, b) => a + b, 0);
    })()''')
    check('a table selection shows in the bar chart', r, 3)

    # ---- exclude, stale, redo
    r = await page.ev('''(async () => {
      const t = SM.app.current; const rep = SM.app.reports[SM.app.reports.length - 1];
      t.select([0, 1, 2, 3, 4]); t.setState(t.selectedRows(), 'excluded', true);
      const stale = !rep.staleEl.hidden;
      rep.run(); await new Promise(res => rep.on('done', res));
      const n = [...rep.body.querySelectorAll('.sm-kv')].map(k => k.textContent).find(s => s.includes('Std Err Mean'));
      t.setState([0, 1, 2, 3, 4], 'excluded', false); t.select([]);
      return { stale, note: rep.noteEl.textContent, n };
    })()''')
    check('an exclusion makes the report stale', r['stale'], True)
    check('redo uses the included rows', r['note'], 'Students: 55 of 60 rows, 5 excluded')
    check('N follows', r['n'].endswith('N55'), True)

    # ---- By
    r = await page.ev(open_report_js('distribution', {'y': ['weight (kg)'], 'by': ['sex']}))
    check('By gives one report per level', [o for o in r['outlines'] if o.startswith('Distribution')], ['Distribution sex=F', 'Distribution sex=M'])
    check('no errors in the By report', r['errors'], [])
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(r => requestAnimationFrame(() => setTimeout(r, 50)));
      const tbl = [...rep.body.querySelectorAll('table.sm-rt')].find(t => t.dataset.rtKey === 'Quantiles');
      tbl.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, clientX: 300, clientY: 300 }));
      const item = [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent.startsWith('Make Combined Data Table'));
      const label = item ? item.textContent : null;
      const n = SM.app.tables.length;
      item && item.click();
      await new Promise(r => setTimeout(r, 50));
      const t = SM.app.tables[SM.app.tables.length - 1];
      const out = { label, added: SM.app.tables.length - n, rows: t.nrows, first: t.columns[0].name, groups: [...new Set(t.columns[0].values)] };
      SM.app.closeTable(t);
      SM.app.showTab(SM.app.tabOf(rep));
      return out;
    })()''')
    check('Make Combined Data Table joins the By groups', (r['added'], r['rows'], r['first'], r['groups']), (1, 22, 'By', ['sex=F', 'sex=M']))

    # ---- options from the red triangle, saved columns
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table; const w = t.col('weight (kg)').id;
      rep.spec.options[w + '|qq'] = true; rep.spec.options[w + '|fits'] = ['normal'];
      rep.run(); await new Promise(res => rep.on('done', res));
      const heads = [...rep.body.querySelectorAll('.sm-ob-head h4')].map(h => h.textContent);
      const before = t.columns.length;
      const ctx = new SM.report.Ctx(rep, { rows: t.includedRows() }, rep.body, '');
      ctx.saveColumn('z', { rows: [0, 1], values: [1.5, -2] });
      const c = t.columns[t.columns.length - 1];
      const ok = t.columns.length === before + 1 && c.values[0] === 1.5 && Number.isNaN(c.values[5]);
      t.removeColumn(c.id);
      return { heads, ok };
    })()''')
    check('normal quantile plot and fit outlines', [h for h in r['heads'] if h in ('Normal Quantile Plot', 'Fitted Normal Distribution')], ['Normal Quantile Plot', 'Fitted Normal Distribution', 'Normal Quantile Plot', 'Fitted Normal Distribution'])
    check('a saved column holds its rows and missing elsewhere', r['ok'], True)

    # ---- the grid: edit a cell, Column Info, Select Where
    r = await page.ev('''(async () => {
      const t = SM.app.current; SM.app.showTab(SM.app.tabOf(t));
      const g = SM.app.grid; const j = t.colIndex('weight (kg)');
      g.startEdit(2, j, '99'); g.commitEdit();
      const v = t.col('weight (kg)').values[2];
      t.setType('age', { modelingType: 'continuous' });
      const mt = t.col('age').modelingType;
      t.setType('age', { modelingType: 'ordinal' });
      return { v, mt, stale: SM.app.reports.every(r => !r.staleEl.hidden) };
    })()''')
    check('typing in a cell sets the value', r['v'], 99)
    check('modeling type changes', r['mt'], 'continuous')
    check('every report of the table is stale after an edit', r['stale'], True)
    r = await page.ev('''(async () => {
      const t = SM.app.current; const g = SM.app.grid; const j = t.colIndex('weight (kg)');
      const before = t.col('weight (kg)').values[4];
      g.startEdit(4, j, '5'); g.commitEdit();
      const edited = t.col('weight (kg)').values[4];
      SM.app.undo();
      const undone = t.col('weight (kg)').values[4];
      SM.app.redo();
      const redone = t.col('weight (kg)').values[4];
      SM.app.undo();
      const n0 = t.nrows; const id0 = t.col('id').values[0];
      SM.app.record(t, 'Delete Rows'); t.deleteRows([0, 1, 2]);
      const n1 = t.nrows;
      SM.app.undo();
      t.select([7, 8]); const items = SM.app.rowsMenuItems(); items.find(i => i.label === 'Exclude/Unexclude').action();
      const ex = t.counts().excluded; SM.app.undo(); const ex2 = t.counts().excluded; t.select([]);
      return { ok: edited === 5 && undone === before && redone === 5, rows: [n0, n1, t.nrows], id: t.col('id').values[0] === id0, ex: [ex, ex2] };
    })()''')
    check('undo and redo a cell edit', r['ok'], True)
    check('undo brings deleted rows back', (r['rows'][1], r['rows'][2], r['id']), (r['rows'][0] - 3, r['rows'][0], True))
    check('undo an exclusion', r['ex'], [2, 0])
    await shot(page, '03-grid.png')

    # ---- a graph asked for before Plotly came is drawn when it does
    r = await page.ev('''(async () => {
      const P = window.Plotly; delete window.Plotly;
      const t = SM.app.tables[0];
      const rep = SM.app.openReport(SM.platforms.get('distribution'), { roles: { y: [t.col('height (cm)').id] }, options: {} }, t);
      await new Promise(res => rep.on('done', res)); await new Promise(res => setTimeout(res, 300));
      const before = rep.plots.filter(p => p.drawn).length;
      window.Plotly = P; document.querySelector('script[src*="plotly"]').dispatchEvent(new Event('load'));
      await new Promise(res => setTimeout(res, 600));
      const after = rep.plots.filter(p => p.drawn).length, n = rep.plots.length;
      SM.app.closeReport(rep);
      return { before, after, n };
    })()''')
    check('without Plotly the graphs wait', (r['before'], r['n'] > 0), (0, True))
    check('... and are drawn when it loads', r['after'], r['n'])

    # ---- the Local Data Filter
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[0]; const t = rep.table;
      const done = () => new Promise(res => rep.on('done', res));
      rep.toggleFilter(true); await done();
      const hasPanel = !rep.filterHost.hidden;
      rep.spec.filter.push({ col: t.col('sex').id, levels: ['F'] }); rep.run(); await done();
      const nF = t.includedRows().filter(r => t.col('sex').values[r] === 'F').length;
      const noteF = rep.noteEl.textContent;
      const kv = [...rep.body.querySelectorAll('.sm-kv')].map(k => k.textContent).find(s => s.includes('Std Err Mean'));
      rep.spec.filter.push({ col: t.col('height (cm)').id, lo: 150, hi: null }); rep.run(); await done();
      const want2 = t.includedRows().filter(r => t.col('sex').values[r] === 'F' && t.col('height (cm)').values[r] >= 150).length;
      const count2 = rep.filterHost.querySelector('.sm-filter-count').textContent;
      rep.toggleFilter(false); await done();
      return { hasPanel, nF, noteF, n: kv.endsWith('N' + nF), count2, want2, off: rep.filterHost.hidden, noteOff: rep.noteEl.textContent };
    })()''')
    check('the filter panel opens', r['hasPanel'], True)
    check('a level filter narrows the report', r['n'], True)
    check('the note says it is filtered', 'filtered' in r['noteF'], True)
    check('a range filter narrows it further', r['count2'].startswith(f"{r['want2']} matching rows"), True)
    check('closing the filter restores the rows', (r['off'], 'filtered' in r['noteOff']), (True, False))

    # ---- the levels of a filter: a click, ctrl/⌘ for one more, shift for a sweep
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[0]; const t = rep.table;
      const done = () => new Promise(res => rep.on('done', res));
      rep.toggleFilter(true); await done();
      rep.spec.filter.push({ col: t.col('age').id, levels: [] }); rep._renderFilter();
      const btns = () => [...rep.filterHost.querySelectorAll('.sm-filter-level')];
      const on = () => btns().filter(b => b.classList.contains('is-on')).map(b => b.firstChild.textContent);
      const click = async (i, o = {}) => { const d = done(); btns()[i].dispatchEvent(new MouseEvent('click', { bubbles: true, ...o })); await d; };
      const levels = btns().map(b => b.firstChild.textContent);
      await click(0); const a = on();
      await click(3, { shiftKey: true }); const b = on();
      await click(1, { metaKey: true }); const c = on();
      await click(4, { shiftKey: true, metaKey: true }); const d = on();
      await click(2, { shiftKey: true }); const e = on();
      rep.toggleFilter(false); await done();
      return { levels, a, b, c, d, e };
    })()''')
    L = r['levels']
    check('filter levels: a click keeps one level', r['a'], L[:1])
    check('... shift-click the fourth: the first four', r['b'], L[:4])
    check('... ctrl/⌘-click the second: it is taken away', r['c'], [L[0]] + L[2:4])
    check('... shift with ctrl/⌘ adds the sweep to the fifth (from the level clicked last)', r['d'], L[0:5])
    check('... shift alone: the sweep from there, the others let go', r['e'], L[1:3])

    # ---- the role lists of a launch dialog: the same rules, and Remove
    r = await page.ev('''(async () => {
      SM.app.launch('distribution');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name, o = {}) => items.find(li => li.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true, ...o }));
      pick('id'); pick('weight (kg)', { shiftKey: true });
      [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === 'Y, Columns').click();
      const ul = dlg.querySelector('.sm-role-list');
      const lis = () => [...ul.querySelectorAll('li')];
      const sel = () => lis().filter(li => li.classList.contains('is-selected')).map(li => li.textContent);
      const click = (i, o = {}) => lis()[i].dispatchEvent(new MouseEvent('click', { bubbles: true, ...o }));
      const cast = lis().map(li => li.textContent);
      click(1); const a = sel();
      click(3, { shiftKey: true }); const b = sel();
      click(2, { ctrlKey: true }); const c = sel();
      click(0, { shiftKey: true }); const d = sel();
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'Remove').click();
      const left = lis().map(li => li.textContent);
      dlg.querySelector('.sm-dialog-x').click();
      return { cast, a, b, c, d, left };
    })()''')
    C = r['cast']
    check('the column list: shift-click casts the sweep', C, ['id', 'age', 'sex', 'height (cm)', 'weight (kg)'])
    check('a role list: a click selects one', r['a'], C[1:2])
    check('... shift-click the fourth: the second to the fourth', r['b'], C[1:4])
    check('... ctrl-click the third: taken away', r['c'], [C[1], C[3]])
    check('... shift-click the first: the sweep from the one clicked last (the third)', r['d'], C[0:3])
    check('... and Remove takes those out of the role', r['left'], C[3:])

    # ---- the rule itself
    r = await page.ev('''(() => {
      const ids = ['a', 'b', 'c', 'd', 'e']; const s = new Set(); const m = { anchor: null }; const out = [];
      const go = (id, o = {}) => { SM.util.listClick(o, id, ids, s, m); out.push([...s].sort().join('')); };
      go('b', { shiftKey: true }); go('d', { shiftKey: true }); go('a', { shiftKey: true }); go('a'); go('a');
      return out;
    })()''')
    check('shift with nothing clicked before selects the one; the sweep keeps its start; a click on the only one clears it', r, ['b', 'bcd', 'ab', 'a', ''])

    # ---- the Column Switcher
    r = await page.ev('''(async () => {
      const t = SM.app.current;
      const rep = SM.app.openReport(SM.platforms.get('distribution'), { roles: { y: [t.col('height (cm)').id] } }, t);
      await new Promise(res => rep.on('done', res));
      rep.spec.switcher = { role: 'y', index: 0, list: [t.col('height (cm)').id, t.col('weight (kg)').id] };
      rep._renderSwitcher();
      const b = [...rep.switchHost.querySelectorAll('button')].find(x => x.textContent === 'weight (kg)');
      b.click();
      await new Promise(res => rep.on('done', res));
      const heads = [...rep.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent);
      SM.app.closeReport(rep);
      return heads;
    })()''')
    check('the column switcher swaps the column', r[:1], ['weight (kg)'])

    # ---- Rows > Data Filter
    r = await page.ev('''(async () => {
      const t = SM.app.current; SM.app.showTab(SM.app.tabOf(t));
      SM.app.toggleDataFilter(true);
      const panel = !SM.app.panels.pFilter.hidden;
      const df = t.dataFilter; df.include = true;
      df.entries.push({ col: t.col('sex').id, levels: [] });
      SM.app.panels.renderDataFilter();
      const lv = [...SM.app.panels.pFilter.querySelectorAll('.sm-filter-level')].find(b => b.textContent.startsWith('M'));
      lv.click();
      const nM = t.col('sex').values.filter(v => v === 'M').length;
      const sel = t.counts().selected, ex = t.counts().excluded;
      SM.app.toggleDataFilter(false);
      return { panel, sel, ex, nM, n: t.nrows, after: t.counts().excluded, closed: SM.app.panels.pFilter.hidden };
    })()''')
    check('the data filter docks in the side panels', r['panel'], True)
    check('a level click selects the matching rows', r['sel'], r['nM'])
    check('Include excludes the other rows', r['ex'], r['n'] - r['nM'])
    check('closing the data filter undoes its exclusions', (r['after'], r['closed']), (0, True))

    # ---- files the engine reads: a Stata file, a statsmodels dataset
    import base64
    import io as _io
    try:
        import pandas as pd
        buf = _io.BytesIO()
        pd.DataFrame({'a': [1.5, 2.5, None], 'g': pd.Categorical(['x', 'y', 'x'])}).to_stata(buf, write_index=False)
        b64 = base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        b64 = None
    if b64:
        r = await page.ev(f'''(async () => {{
          const bytes = Uint8Array.from(atob("{b64}"), c => c.charCodeAt(0));
          const n = SM.app.tables.length;
          await SM.app.openFiles([new File([bytes], 'demo.dta')]);
          const t = SM.app.tables[SM.app.tables.length - 1];
          return {{ added: SM.app.tables.length - n, name: t.name, cols: t.columns.map(c => [c.name, c.modelingType]), a: t.col('a').values.map(v => Number.isNaN(v) ? null : v) }};
        }})()''')
        check('a Stata file opens as a table', (r['added'], r['name'], r['cols']), (1, 'demo', [['a', 'continuous'], ['g', 'nominal']]))
        check('its missing value stays missing', r['a'], [1.5, 2.5, None])
    # a JMP data table (JMPReader.jl's example1, fetched by fetch-jmp-fixtures.py
    # into local/jmp/; skipped without it): its columns, dates as dates
    jmp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'local', 'jmp', 'example1.jmp')
    if os.path.isfile(jmp_path):
        with open(jmp_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
        r = await page.ev(f'''(async () => {{
          const bytes = Uint8Array.from(atob("{b64}"), c => c.charCodeAt(0));
          const n = SM.app.tables.length;
          await SM.app.openFiles([new File([bytes], 'example1.jmp')]);
          const t = SM.app.tables[SM.app.tables.length - 1];
          return {{ added: SM.app.tables.length - n, name: t.name, rows: t.nrows, cols: t.columns.map(c => [c.name, c.dataType, c.modelingType]),
            date: SM.grid.cellText(t.col('date'), t.col('date').values[0]), utf8: t.col('char utf8').values[1], notes: t.notes }};
        }})()''')
        check('a JMP table opens as a table', (r['added'], r['name'], r['rows']), (1, 'example1', 4))
        check('... its columns, numbers continuous and text nominal', r['cols'][:3], [['ints', 'numeric', 'continuous'], ['floats', 'numeric', 'continuous'], ['charconstwidth', 'character', 'nominal']])
        check('... a date shown as a date, UTF-8 text as it is', (r['date'], r['utf8']), ('2024-01-13', '🚴💨'))
        check('... and its notes say the modeling types were guessed', 'Modeling types' in (r['notes'] or ''), True)
    else:
        print('   (local/jmp/example1.jmp not fetched: the JMP table check is skipped)')
    r = await page.ev('''(async () => {
      const n = SM.app.tables.length;
      SM.app.datasetsDialog();
      for (let i = 0; i < 100 && !document.querySelector('.sm-dsitem'); i++) await new Promise(r => setTimeout(r, 100));
      const b = [...document.querySelectorAll('.sm-dsitem')].find(x => x.textContent.toLowerCase().includes('longley'));
      b.click();
      for (let i = 0; i < 100 && SM.app.tables.length === n; i++) await new Promise(r => setTimeout(r, 100));
      const t = SM.app.tables[SM.app.tables.length - 1];
      return { rows: t.nrows, first: t.columns[0].name, source: t.source.startsWith('statsmodels.datasets.longley') };
    })()''')
    check('a statsmodels dataset loads from the engine', (r['rows'], r['first'], r['source']), (16, 'TOTEMP', True))
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables[0]))')

    # ---- a project saved and opened again keeps per-column options
    r = await page.ev('''(async () => {
      const t = SM.app.tables[0];
      const rep = SM.app.openReport(SM.platforms.get('distribution'), { roles: { y: [t.col('height (cm)').id] }, options: { [t.col('height (cm)').id + '|qq']: true } }, t);
      await new Promise(res => rep.on('done', res));
      rep.spec.filter = [{ col: t.col('sex').id, levels: ['F'] }];
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.closeReport(rep);
      const n = SM.app.reports.length;
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      if (back.body.classList.contains('is-running')) await new Promise(res => back.on('done', res));
      const heads = [...back.body.querySelectorAll('.sm-ob-head h4')].map(h => h.textContent);
      const t2 = back.table;
      const out = { newTable: t2 !== t, heads, filterCol: t2.col(back.spec.filter[0].col)?.name, note: back.noteEl.textContent };
      SM.app.closeReport(back);   // closing a table with reports asks first
      SM.app.closeTable(t2);
      return out;
    })()''')
    check('an opened project has its own table', r['newTable'], True)
    check('and keeps a per-column option (the normal quantile plot)', 'Normal Quantile Plot' in r['heads'], True)
    check('and its filter finds its column', r['filterCol'], 'sex')

    # ---- the Python script of a report
    r = await page.ev('SM.app.reports[0].pythonScript()')
    check('the script holds the code of the results', 'DescrStatsW(x, ddof=1)' in r and 'proportion_confint' in r, True)

    # ---- the Python code button and the red triangle's Show Python Code go
    # by what is open: after the code was closed by its own heading a click
    # shows it again (it did nothing: the report still took it as shown).
    # An outline closed around the code opens; a report without code says so.
    LAST = 'SM.app.reports[SM.app.reports.length - 1]'
    CODE = f'''(() => {{ const rep = {LAST}, box = rep.body.getBoundingClientRect(), ds = rep.codeBlocks();
      return {{ n: ds.length, open: ds.filter(d => d.open).length, pressed: rep.codeBtn.getAttribute('aria-pressed'),
        seen: ds.filter(d => {{ const r = d.getBoundingClientRect(); return d.open && r.height > 0 && r.top >= box.top && r.top < box.bottom - 40; }}).length,
        toast: (document.querySelector('.sm-toast') || {{}}).textContent || '' }}; }})()'''

    # on the Students table (closing a report may leave another one current)
    def OPEN_ON_STUDENTS(platform, roles):
        return f'''(async () => {{ const t = SM.app.tables[0], roles = {{}};
          for (const [k, names] of Object.entries({json.dumps(roles)})) roles[k] = names.map(n => t.col(n).id);
          const rep = SM.app.openReport(SM.platforms.get({json.dumps(platform)}), {{ roles, options: {{}} }}, t);
          await new Promise(res => rep.on('done', res)); return rep.title; }})()'''

    async def click_on(expr):
        xy = await page.ev(f'(() => {{ const e = {expr}; const r = e.getBoundingClientRect(); return [r.left + Math.min(20, r.width / 2), r.top + r.height / 2]; }})()')
        await page.click(*xy)
        await asyncio.sleep(0.6)

    async def show_code_item():
        await click_on(f'{LAST}.body.querySelector(".sm-ob-head .sm-ob-menu")')
        was = await page.ev('[...document.querySelectorAll(".sm-menu button")].find(b => b.textContent.includes("Show Python Code")).getAttribute("aria-checked")')
        await click_on('[...document.querySelectorAll(".sm-menu button")].find(b => b.textContent.includes("Show Python Code"))')
        return was

    await page.ev(OPEN_ON_STUDENTS('distribution', {'y': ['height (cm)']}))
    await asyncio.sleep(0.4)
    await click_on(f'{LAST}.codeBtn')
    r = await page.ev(CODE)
    check('Python code: the code opens and is seen, the button pressed', (r['n'] > 0, r['open'] == r['n'], r['seen'] > 0, r['pressed']), (True, True, True, 'true'))
    await click_on(f'{LAST}.codeBlocks()[0].querySelector("summary")')
    r = await page.ev(CODE)
    check('... one closed by its own heading, the button no longer pressed', (r['open'], r['pressed']), (r['n'] - 1, 'false'))
    await click_on(f'{LAST}.codeBtn')
    r = await page.ev(CODE)
    check('... and the button shows it again', (r['open'] == r['n'], r['seen'] > 0, r['pressed']), (True, True, 'true'))
    was = await show_code_item()
    r = await page.ev(CODE)
    check("Show Python Code is ticked while the code shows, and hides it", (was, r['open'], r['pressed']), ('true', 0, 'false'))
    was = await show_code_item()
    r = await page.ev(CODE)
    check('... unticked, it shows it', (was, r['open'] == r['n'], r['pressed']), ('false', True, 'true'))
    await page.ev(f'(() => {{ const rep = {LAST}; rep.setCode(false); rep.codeBlocks()[0].closest(".sm-ob")._outline.setOpen(false); rep.body.scrollTop = 0; }})()')
    await click_on(f'{LAST}.codeBtn')
    r = await page.ev(CODE)
    check('code in a closed outline: the outline opens and the code is seen', (await page.ev(f'{LAST}.codeBlocks()[0].closest(".sm-ob").classList.contains("is-closed")'), r['seen'] > 0), (False, True))
    await page.ev(f'SM.app.closeReport({LAST})')
    # (an empty Graph Builder: every graph of the Graph menu has its code now)
    await page.ev(OPEN_ON_STUDENTS('graphbuilder', {}))
    await asyncio.sleep(0.4)
    await click_on(f'{LAST}.codeBtn')
    r = await page.ev(CODE)
    check('a report with no Python code says so', (r['n'], 'ran no Python' in r['toast'], r['pressed']), (0, True, 'true'))
    await page.ev(f'SM.app.closeReport({LAST}); document.querySelectorAll(".sm-toast").forEach(t => t.remove())')

    # ---- runs that overlap (a Redo, a theme change while one waits on Python): a
    # superseded run adds nothing to the newer run's graphs and code, and purges
    # only its own graphs (it used to leave its purged graphs in the list)
    r = await page.ev('''(async () => { const t = SM.app.tables[0]; const rep = SM.app.openReport(SM.platforms.get('distribution'), { roles: { y: [t.col('height (cm)').id, t.col('sex').id] }, options: {} }, t);
      await Promise.all([rep.run('redo'), rep.run('redo')]); await new Promise(r => setTimeout(r, 80));
      const out = { plots: rep.plots.length, inBody: rep.body.querySelectorAll('.sm-plot').length, connected: rep.plots.every(p => p.box.isConnected), code: rep.pyCode.length, uniq: new Set(rep.pyCode).size };
      SM.app.closeReport(rep); return out; })()''')
    check("overlapping runs: the report keeps only the last run's graphs, all in the page, and its code once", (r['plots'] == r['inBody'] and r['plots'] > 0, r['connected'], r['code'] == r['uniq']), (True, True, True))

    # ---- Distribution beyond JMP: the interval method of the level probabilities, Test Rate
    MENU = '''(async (rep, title, path) => {
      const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h2, h3, h4').textContent === title);
      h.querySelector('.sm-ob-menu').click();
      let items = null;
      for (const label of path) {
        await new Promise(r => setTimeout(r, 60));
        const menus = document.querySelectorAll('.sm-menu'); const m = menus[menus.length - 1];
        const b = [...m.querySelectorAll('button')].find(x => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === label);
        if (!b) { SM.ui.closeMenus(0); return 'no item ' + label; }
        items = [...m.querySelectorAll('button')].map(x => [x.querySelector('.sm-label') ? x.querySelector('.sm-label').textContent : '', x.getAttribute('aria-checked'), x.disabled]);
        b.click();
      }
      await new Promise(r => setTimeout(r, 60));
      const menus = document.querySelectorAll('.sm-menu'); const last = menus[menus.length - 1];
      const out = { at: items, last: last ? [...last.querySelectorAll('button')].map(x => [x.querySelector('.sm-label') ? x.querySelector('.sm-label').textContent : '', x.getAttribute('aria-checked'), x.disabled]) : [] };
      return out;
    })'''
    r = await page.ev(f'''(async () => {{
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      const sex = t.col('sex').id;
      const rep = SM.app.openReport(SM.platforms.get('distribution'), {{ roles: {{ y: [sex] }}, options: {{ [sex + '|ciCat']: 0.95, [sex + '|ciMethod']: 'agresti_coull' }} }}, t);
      await new Promise(res => rep.on('done', res));
      const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Confidence Intervals');
      const rows = [...h.parentElement.querySelectorAll('table.sm-rt tbody tr')].map(tr => [...tr.children].map(c => c.textContent));
      const note = h.parentElement.querySelector('.sm-ob-note').textContent;
      const v = t.col('sex').values; const n = v.filter(x => x != null).length; const k = v.filter(x => x === 'F').length; const z = SM.util.qnorm(0.975);
      const nc = n + z * z, pc = (k + z * z / 2) / nc, half = z * Math.sqrt(pc * (1 - pc) / nc);
      const menu = await ({MENU})(rep, 'sex', ['Confidence Interval', 'Confidence Interval Method']);
      const pick = menu.last.find(x => x[0] === 'Clopper-Pearson (exact)');
      const done = new Promise(res => rep.on('done', res));
      [...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')[menu.last.indexOf(pick)].click();
      await done;
      const note2 = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Confidence Intervals').parentElement.querySelector('.sm-ob-note').textContent;
      return {{ rows, note, lo: pc - half, hi: pc + half, methods: menu.last.map(x => [x[0], x[1]]), note2, errors: [...rep.body.querySelectorAll('.sm-ob-error')].length }};
    }})()''')
    check('Confidence Interval Method: the five methods, Agresti-Coull checked', r['methods'], [['Wilson Score (JMP)', 'false'], ['Agresti-Coull', 'true'], ['Jeffreys', 'false'], ['Clopper-Pearson (exact)', 'false'], ['Wald', 'false']])
    check.near('the Agresti-Coull lower limit of F as computed in the page', float(r['rows'][0][3]), r['lo'], 1e-6)
    check.near('and its upper limit', float(r['rows'][0][4]), r['hi'], 1e-6)
    check('the note names the method', r['note'].startswith('Agresti-Coull confidence intervals'), True)
    check('choosing Clopper-Pearson redraws with it', (r['note2'].startswith('Clopper-Pearson (exact) confidence intervals'), r['errors']), (True, 0))
    r = await page.ev(f'''(async () => {{
      SM.app.openExample('clinical'); const t = SM.app.current; const ae = t.col('adverse events').id, mo = t.col('months').id;
      const rep = SM.app.openReport(SM.platforms.get('distribution'), {{ roles: {{ y: [ae, mo] }} }}, t);
      await new Promise(res => rep.on('done', res));
      const off = (await ({MENU})(rep, 'months', ['Test Rate…'])).at.find(x => x[0] === 'Test Rate…');
      SM.ui.closeMenus(0);
      const done = new Promise(res => rep.on('done', res));
      const m = await ({MENU})(rep, 'adverse events', ['Test Rate…']);
      let d = null; for (let i = 0; i < 60 && !d; i++) {{ await new Promise(res => setTimeout(res, 50)); d = [...document.querySelectorAll('.sm-dialog')].pop(); }}
      d.querySelector('input').value = '0.1';
      const s = d.querySelector('select'); s.value = [...s.options].find(o => o.textContent === 'months').value;
      d.querySelector('.sm-dialog-foot .primary').click();
      await done;
      const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Test Rate');
      const kv = h ? [...h.parentElement.querySelectorAll('table.sm-kv')].map(tb => [...tb.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent))) : null;
      const y = t.col('adverse events').values, e = t.col('months').values;
      const total = y.reduce((a, b) => a + b, 0), expo = e.reduce((a, b) => a + b, 0);
      return {{ off: off ? off[2] : 'missing', on: m.at.find(x => x[0] === 'Test Rate…')[2], kv, total, expo, errors: [...rep.body.querySelectorAll('.sm-ob-error')].length }};
    }})()''')
    check('Test Rate is for counts: not for months', r['off'], True)
    check('Test Rate is enabled for the adverse event counts', r['on'], False)
    kv = {row[0]: row[1] for row in r['kv'][0]} if r['kv'] else {}
    check('Test Rate from its dialog: the hypothesized rate and the total count', (kv.get('Hypothesized Rate'), float(kv.get('Total adverse events', 'nan'))), ('0.1', float(r['total'])))
    check.near('the total months', float(kv.get('Total months', 'nan')), r['expo'], 1e-6)
    check.near('the rate = total events / total months computed in the page', float(kv.get('Rate Estimate', 'nan')), r['total'] / r['expo'], 1e-6)
    check('its tests are listed', [row[0] for row in r['kv'][1]][:4] if r['kv'] else None, ['Test Statistic', 'Prob, rate ≠ hypothesized', 'Prob, rate > hypothesized', 'Prob, rate < hypothesized'])
    check('no errors in the Test Rate report', r['errors'], 0)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      if (back.body.classList.contains('is-running')) await new Promise(res => back.on('done', res));
      const h = [...back.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Test Rate');
      const labels = h ? [...h.parentElement.querySelectorAll('table.sm-kv tr')].map(tr => tr.children[0].textContent) : [];
      const t2 = back.table; SM.app.closeReport(back); SM.app.closeTable(t2);
      return { newTable: t2 !== t, labels };
    })()''')
    check('a project keeps Test Rate and its exposure column', (r['newTable'], 'Total months' in r['labels']), (True, True))
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables[0]))')

    # ---- dialogs move by their title bar and stay within reach; the ×
    # and the (i) in the bar are buttons, not handles
    r = await page.ev('''(async () => {
      SM.app.launch('distribution');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const head = dlg.querySelector('.sm-dialog-head');
      const at = () => { const b = dlg.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top)]; };
      const drag = (from, dx, dy) => {
        const o = { bubbles: true, button: 0, pointerId: 7, isPrimary: true };
        from.dispatchEvent(new PointerEvent('pointerdown', { ...o, clientX: 300, clientY: 200 }));
        head.dispatchEvent(new PointerEvent('pointermove', { ...o, clientX: 300 + dx, clientY: 200 + dy }));
        head.dispatchEvent(new PointerEvent('pointerup', { ...o, clientX: 300 + dx, clientY: 200 + dy }));
      };
      const p0 = at();
      drag(head.querySelector('h2'), -150, 60);
      const p1 = at();
      drag(head.querySelector('h2'), 5000, 5000);
      const b = dlg.getBoundingClientRect();
      const reach = b.left <= innerWidth - 59 && b.top <= innerHeight - head.getBoundingClientRect().height + 1;
      drag(head.querySelector('h2'), -10000, -10000);
      const c = dlg.getBoundingClientRect();
      const back = c.right >= 59 && c.top >= -1;
      const p2 = at();
      drag(head.querySelector('.sm-dialog-x'), 80, 80);
      const still = JSON.stringify(at()) === JSON.stringify(p2) && !!document.querySelector('.sm-launch-dialog');
      const grip = head.classList.contains('sm-dialog-grip') && getComputedStyle(head).cursor;
      dlg.querySelector('.sm-dialog-x').click();
      return { moved: [p1[0] - p0[0], p1[1] - p0[1]], reach, back, still, grip };
    })()''')
    check('a dialog moves with its title bar', r['moved'], [-150, 60])
    check('dragged far right and down, its bar stays in the window', r['reach'], True)
    check('dragged far left and up, it stays within reach', r['back'], True)
    check('the × is a button, not a handle', r['still'], True)
    check('the title bar shows the move cursor', r['grip'], 'move')

    # ---- a click on the dimmed page beside a dialog leaves it open (it lost
    # the work in it too easily); the dialog flashes instead
    await page.ev("SM.app.launch('distribution')")
    await asyncio.sleep(0.3)
    xy = await page.ev('''(() => { const d = document.querySelector('.sm-launch-dialog').getBoundingClientRect();
      const x = Math.max(8, d.left / 2), y = innerHeight - 12; const hit = document.elementFromPoint(x, y);
      return { x, y, back: !!(hit && hit.classList.contains('sm-modal-back')) }; })()''')
    await page.click(xy['x'], xy['y'])
    await asyncio.sleep(0.1)
    r = await page.ev('''(() => { const d = document.querySelector('.sm-launch-dialog'); const out = { open: !!d, flash: !!(d && d.classList.contains('is-attention')) };
      if (d) d.querySelector('.sm-dialog-x').click(); return out; })()''')
    check('the test clicks the dimmed page', xy['back'], True)
    check('a click beside a dialog leaves it open, and it flashes', (r['open'], r['flash']), (True, True))
    check('its × still closes it', await page.ev("!document.querySelector('.sm-launch-dialog')"), True)

    # ---- a disabled item's submenu does not open; an enabled one's does
    # (the mouse moved by the browser, as a user's)
    r = await page.ev('''(() => {
      SM.ui.menu([{ label: 'Off', disabled: true, submenu: () => [{ label: 'hidden', action() {} }] }, { label: 'On', submenu: () => [{ label: 'shown', action() {} }] }], { x: 400, y: 300 });
      const menu = [...document.querySelectorAll('.sm-menu')].pop();
      return [...menu.querySelectorAll('button')].map(b => { const r = b.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; });
    })()''')
    count = 'document.querySelectorAll(".sm-menu").length'

    async def hover(xy):
        await page.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': xy[0], 'y': xy[1]}, session=page.sid)
        await asyncio.sleep(0.15)
    await hover(r[0])
    a = await page.ev(count)
    await hover(r[1])
    b = await page.ev(count)
    shown = await page.ev('[...document.querySelectorAll(".sm-menu")].pop().textContent')
    await hover(r[0])
    c = await page.ev(count)
    await page.ev('SM.ui.closeMenus(0)')
    check('hovering a disabled item opens no submenu', a, 1)
    check('hovering an enabled one opens its submenu', (b, shown), (2, 'shown'))
    check('hovering the disabled item again closes the other submenu', c, 1)

    # ---- the tab strip has no scroll bar of its own
    # (the slider once seen on its right; with many tabs it may scroll sideways)
    r = await page.ev('''(() => { const s = document.querySelector('.sm-tabs'), cs = getComputedStyle(s); return { h: s.scrollHeight - s.clientHeight, bar: s.offsetWidth - s.clientWidth - parseFloat(cs.borderLeftWidth) - parseFloat(cs.borderRightWidth) }; })()''')
    check('the tab strip does not scroll vertically', r['h'], 0)
    check('and shows no vertical scroll bar', r['bar'], 0)

    # ---- the (i) of a launch dialog explains its roles and options; the
    # platform's own Roles section gives way to the generated one; a form's
    # (i) lists its fields, each explanation once
    r = await page.ev('''(async () => {
      SM.app.launch('distribution');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      dlg.querySelector('.sm-dialog-head .info-btn').click();
      await new Promise(r => setTimeout(r, 250));
      const panel = document.querySelector('.info-panel');
      const heads = [...panel.querySelectorAll('h3, h4')].map(h => h.textContent);
      const text = panel.textContent;
      const audit = KvotInfo.audit().noTopic;
      KvotInfo.close();
      dlg.querySelector('.sm-dialog-x').click();
      const topic = SM.info.get('launch:distribution');
      const t = SM.app.current;
      const pending = SM.app.selectRandomly();
      await new Promise(r => setTimeout(r, 200));
      const form = [...document.querySelectorAll('.sm-dialog')].pop();
      form.querySelector('.sm-dialog-head .info-btn').click();
      await new Promise(r => setTimeout(r, 250));
      const fp = document.querySelector('.info-panel');
      const fheads = [...fp.querySelectorAll('h3, h4')].map(h => h.textContent);
      const fnames = [...fp.querySelectorAll('dt, .info-choice-name, strong')].map(e => e.textContent);
      const ftext = fp.textContent;
      KvotInfo.close();
      form.querySelector('.sm-dialog-x').click();
      await pending;
      return { heads, roles: heads.filter(h => h === 'Roles').length, y: text.includes('(required, one or more columns)'), weight: /Weight/.test(text), audit, fn: typeof topic === 'object' && topic.sections.some(s => s.heading === 'Options'), fheads, fnames, seed: ftext.includes('The same seed'), rate: ftext.includes('Sampling rate or number of rows') };
    })()''')
    check('a launch dialog (i) has Roles and Options sections', ('Roles' in r['heads'], 'Options' in r['heads']), (True, True))
    check('one Roles section: the generated one replaces the topic\'s own', r['roles'], 1)
    check('each role says what it takes', (r['y'], r['weight']), (True, True))
    check('the dialog\'s (i) has a topic', r['audit'], [])
    check('SM.info.get gives a topic built when asked', r['fn'], True)
    check('a form without a topic of its own gets an (i) with its Fields', 'Fields' in r['fheads'], True)
    check('its fields are explained under their short names', (r['rate'], r['seed']), (True, True))

    # ---- Save ▾ > Print… prints the report as a document (as Save Report
    # as HTML writes it), from a hidden frame: Graph Builder's chart without
    # its drop zones and palette; and Save Report as Word writes a .docx of
    # the open outlines, tables and graphs
    r = await page.ev('''(async () => {
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      const rep = SM.app.openReport(SM.platforms.get('graphbuilder'), { roles: {}, options: {} }, t);
      await new Promise(res => rep.on('done', res));
      const gb = rep.body.querySelector('.sm-gb')._gb;
      await gb.add('y', 'weight (kg)'); await gb.add('x', 'height (cm)');
      await new Promise(res => setTimeout(res, 300));
      const save = rep.saveMenu().map(i => [i.label, !!i.disabled]);
      // the frame's print() is replaced when the page reaches for it, as the
      // browser's print dialog (which would wait) closing at once
      let printed = 0, frameDoc = null;
      const desc = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
      Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', { configurable: true, get() {
        const w = desc.get.call(this);
        if (w && this.classList.contains('sm-print-frame') && this.srcdoc && !w.__spy) {
          w.__spy = true;
          w.print = () => { printed++; frameDoc = this.contentDocument; setTimeout(() => w.dispatchEvent(new Event('afterprint')), 20); };
        }
        return w;
      } });
      let frame;
      try { frame = await rep.printReport(); } finally { Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', desc); }
      const imgs = frameDoc ? [...frameDoc.images] : [];
      const out = { save, printed, hidden: frame.getBoundingClientRect().right <= 0,
        title: frameDoc && frameDoc.querySelector('h1').textContent, imgs: imgs.length, loaded: imgs.every(i => i.complete && i.naturalWidth > 0),
        controls: frameDoc ? frameDoc.querySelectorAll('button, input, select, .sm-gb-zone, .sm-gb-palette, .sm-gb-left').length : -1,
        page: frameDoc ? [...frameDoc.querySelectorAll('style')].some(s => s.textContent.includes('@page')) : false };
      await new Promise(res => setTimeout(res, 150));
      out.removed = !document.querySelector('.sm-print-frame');
      out.repTitle = rep.title;
      SM.app.closeReport(rep);
      return out;
    })()''')
    check('Save ▾ offers HTML, Word and Print', [x[0] for x in r['save'] if x[0] in ('Save Report as HTML', 'Save Report as Word', 'Print…')], ['Save Report as HTML', 'Save Report as Word', 'Print…'])
    check('Save Report as Word is enabled', [x[1] for x in r['save'] if x[0] == 'Save Report as Word'], [False])
    check('Print prints once, from a frame off the screen', (r['printed'], r['hidden']), (1, True))
    check("the printed document has the report's title", r['title'], r['repTitle'])
    check('the chart is in it as an image, loaded before printing', (r['imgs'], r['loaded']), (1, True))
    check("without the builder's zones, palette and buttons", r['controls'], 0)
    check('with page margins for paper', r['page'], True)
    check('the frame goes after printing', r['removed'], True)

    r = await page.ev('''(async () => {
      const t = SM.app.tables[0];
      const rep = SM.app.openReport(SM.platforms.get('distribution'), { roles: { y: [t.col('height (cm)').id, t.col('sex').id] }, options: {} }, t);
      await new Promise(res => rep.on('done', res));
      await new Promise(res => setTimeout(res, 300));
      const heads = [...rep.body.querySelectorAll('.sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent.trim());
      // close one outline: it is not in the document
      const q = [...rep.body.querySelectorAll('.sm-ob')].find(o => o.querySelector(':scope > .sm-ob-head h3, :scope > .sm-ob-head h4')?.textContent.trim() === 'Quantiles');
      q.classList.add('is-closed');
      const read = async (blob) => {
        const zip = await JSZip.loadAsync(blob);
        const files = Object.keys(zip.files).filter(f => !f.endsWith('/')).sort();
        const xml = await zip.file('word/document.xml').async('string');
        const doc = new DOMParser().parseFromString(xml, 'application/xml');
        const W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
        const paras = [...doc.getElementsByTagNameNS(W, 'p')].map(p => ({ style: p.getElementsByTagNameNS(W, 'pStyle')[0]?.getAttribute('w:val') || '', text: [...p.getElementsByTagNameNS(W, 't')].map(x => x.textContent).join('') }));
        const rels = await zip.file('word/_rels/document.xml.rels').async('string');
        return { files, bad: !!doc.querySelector('parsererror'), paras, tables: doc.getElementsByTagNameNS(W, 'tbl').length, pictures: doc.getElementsByTagNameNS(W, 'drawing').length, rels: (rels.match(/relationships\\/image/g) || []).length,
          png: files.filter(f => f.startsWith('word/media/')).length ? [...(await zip.file('word/media/image1.png').async('uint8array')).slice(0, 4)] : [] };
      };
      const plain = await read(await SM.docx.report(rep, { plotImage: (p) => rep.plotImage(p, 'png', 2) }));
      rep.spec.options.showCode = true;
      const coded = await read(await SM.docx.report(rep, { plotImage: (p) => rep.plotImage(p, 'png', 2) }));
      rep.spec.options.showCode = false;
      // one block opened by its own heading: that code goes along
      rep.codeBlocks()[0].open = true;
      const opened = await read(await SM.docx.report(rep, { plotImage: (p) => rep.plotImage(p, 'png', 2) }));
      rep.codeBlocks()[0].open = false;
      const tables = [...rep.content.querySelectorAll('table.sm-rt, table.sm-kv')].filter(tb => !tb.closest('.sm-ob.is-closed') && tb.offsetParent !== null).length;
      const plots = rep.plots.filter(p => !p.box.closest('.sm-ob.is-closed')).length;
      SM.app.closeReport(rep);
      return { heads, plain, coded, opened, tables, plots, title: rep.title };
    })()''')
    p = r['plain']
    check('the .docx has the parts Word needs', [f for f in p['files'] if not f.startswith('word/media/')], ['[Content_Types].xml', '_rels/.rels', 'docProps/core.xml', 'word/_rels/document.xml.rels', 'word/document.xml', 'word/styles.xml'])
    check('its document is well-formed XML', p['bad'], False)
    check("it starts with the report's title", (p['paras'][0]['style'], p['paras'][0]['text']), ('Title', r['title']))
    hs = [x['text'] for x in p['paras'] if x['style'].startswith('Heading')]
    check('the outlines are headings', [h for h in r['heads'] if h != 'Quantiles' and h in hs] == [h for h in r['heads'] if h != 'Quantiles'], True)
    check('a closed outline keeps its heading but not its body', ('Quantiles' in hs, sum(1 for x in p['paras'] if x['text'] == '97.5%')), (True, 0))
    check('the open tables are Word tables', p['tables'], r['tables'])
    check('each graph is a picture, with its image part', (p['pictures'], p['rels'], len([f for f in p['files'] if f.startswith('word/media/')])), (r['plots'], r['plots'], r['plots']))
    check('the pictures are PNG', p['png'], [137, 80, 78, 71])
    check('no Python code unless the report shows it', (sum(1 for x in p['paras'] if x['style'] == 'SmCode'), sum(1 for x in r['coded']['paras'] if x['style'] == 'SmCode') > 0), (0, True))
    n = sum(1 for x in r['opened']['paras'] if x['style'] == 'SmCode')
    check('... or that block was opened by its heading (and only that one)', 0 < n < sum(1 for x in r['coded']['paras'] if x['style'] == 'SmCode'), True)

    # ---- the page's own print (the browser's Print command): only the
    # report in view, flowing over pages
    r = await page.ev('''(async () => {
      const t = SM.app.tables[0];
      const rep = SM.app.openReport(SM.platforms.get('distribution'), { roles: { y: [t.col('height (cm)').id] }, options: {} }, t);
      await new Promise(res => rep.on('done', res));
      SM.app.showTab(SM.app.tabOf(rep));
      return rep.title;
    })()''')
    await page.call('Emulation.setEmulatedMedia', {'media': 'print'}, session=page.sid)
    await asyncio.sleep(0.3)
    r = await page.ev('''(() => {
      const shown = (sel) => [...document.querySelectorAll(sel)].some(e => getComputedStyle(e).display !== 'none' && e.getClientRects().length);
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const b = rep.body.getBoundingClientRect();
      return { header: shown('body > header'), footer: shown('body > footer'), toggle: shown('body > .nav-toggle'), menubar: shown('.sm-menubar'), tabs: shown('.sm-tabs'), side: shown('.sm-side'), bar: shown('.sm-reportbar'), menus: shown('.sm-reportbody .sm-ob-menu'), buttons: shown('.sm-reportbody button'),
        report: b.height > 100, flows: rep.body.scrollHeight <= rep.body.clientHeight + 1, grid: shown('.sm-view:not(.sm-report) .sm-grid') };
    })()''')
    await page.call('Emulation.setEmulatedMedia', {'media': ''}, session=page.sid)
    check('printing the page leaves out the site around it', (r['header'], r['footer'], r['toggle']), (False, False, False))
    check('and the menus, tabs, panels and report bar', (r['menubar'], r['tabs'], r['side'], r['bar']), (False, False, False, False))
    check('and the red triangles and buttons of the report', (r['menus'], r['buttons']), (False, False))
    check('the report in view is printed, flowing over pages', (r['report'], r['flows'], r['grid']), (True, True, False))
    await page.ev('SM.app.closeReport(SM.app.reports[SM.app.reports.length - 1])')
    # a graph wider than the paper is scaled to fit it for the print only,
    # and the box around it does not scroll
    w = await page.ev('''(async () => {
      const t = SM.app.tables[0];
      const rep = SM.app.openReport(SM.platforms.get('graphbuilder'), { roles: {}, options: {} }, t);
      await new Promise(res => rep.on('done', res));
      const gb = rep.body.querySelector('.sm-gb')._gb;
      await gb.add('y', 'weight (kg)'); await gb.add('x', 'height (cm)');
      SM.app.showTab(SM.app.tabOf(rep));
      await new Promise(res => setTimeout(res, 400));
      const p = rep.plots.find(p => p.drawn);
      const width = p.box.getBoundingClientRect().width;
      dispatchEvent(new Event('beforeprint'));
      return { width, screen: p.box.getBoundingClientRect().width };
    })()''')
    await page.call('Emulation.setEmulatedMedia', {'media': 'print'}, session=page.sid)
    await asyncio.sleep(0.3)
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => p.drawn);
      const b = rep.body.getBoundingClientRect(), g = p.box.getBoundingClientRect();
      const scrolls = [...rep.body.querySelectorAll('div')].filter(e => !e.closest('.js-plotly-plot') && e.scrollWidth > e.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(e).overflowX)).length;
      return { right: g.right - b.left, scrolls };
    })()''')
    await page.call('Emulation.setEmulatedMedia', {'media': ''}, session=page.sid)
    # (an emulated print lays out the page again, and the builder redraws at
    # the new width; a real print does not)
    after = await page.ev('''(() => { dispatchEvent(new Event('afterprint')); const rep = SM.app.reports[SM.app.reports.length - 1];
      const out = { n: document.querySelectorAll('.sm-print-zoom, .sm-print-flow').length, zoom: [...rep.body.querySelectorAll('*')].filter(e => e.style.getPropertyValue('--sm-print-zoom')).length }; SM.app.closeReport(rep); return out; })()''')
    check('the test graph is wider than the paper', w['width'] > 700, True)
    check('before printing the screen is left as it is', round(w['screen']), round(w['width']))
    check('on paper the graph fits the page width', r['right'] <= 702, True)
    check('and nothing around it scrolls', r['scrolls'], 0)
    check('after printing the scaling is taken off', (after['n'], after['zoom']), (0, 0))

    # ---- a box selection, then its edge moved (with the mouse, as a user
    # does): the rows are selected once each time, and the tab stays alive.
    # A redraw used to make Plotly announce the kept box again, which was
    # taken for a new selection and redrew again, without end. A selection
    # made elsewhere then takes the kept box away.
    box = await page.ev('''(async () => {
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      window.__selCalls = 0; const orig = t.select; t.select = function (...a) { __selCalls++; return orig.apply(this, a); }; window.__unsel = () => { delete t.select; };
      const rep = SM.app.openReport(SM.platforms.get('graphbuilder'), { roles: {}, options: {} }, t);
      await new Promise(res => rep.on('done', res));
      const gb = rep.body.querySelector('.sm-gb')._gb;
      await gb.add('y', 'weight (kg)'); await gb.add('x', 'height (cm)');
      SM.app.showTab(SM.app.tabOf(rep));
      await new Promise(res => setTimeout(res, 600));
      const p = rep.plots.find(p => p.drawn);
      p.box.scrollIntoView({ block: 'center' }); await new Promise(res => setTimeout(res, 200));
      const r = p.box.querySelector('.nsewdrag').getBoundingClientRect();
      return { left: r.left, top: r.top, w: r.width, h: r.height };
    })()''')

    async def mouse(kind, x, y):
        await page.call('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left', 'buttons': 0 if kind == 'mouseReleased' else 1, 'clickCount': 1}, session=page.sid)

    async def drag(x0, y0, x1, y1):
        await page.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x0, 'y': y0}, session=page.sid)
        await asyncio.sleep(0.1)
        await mouse('mousePressed', x0, y0)
        for i in range(1, 9):
            await mouse('mouseMoved', x0 + (x1 - x0) * i / 8, y0 + (y1 - y0) * i / 8)
            await asyncio.sleep(0.03)
        await mouse('mouseReleased', x1, y1)
        await asyncio.sleep(0.6)
    x1, y1 = box['left'] + box['w'] * 0.25, box['top'] + box['h'] * 0.15
    x2, y2 = box['left'] + box['w'] * 0.75, box['top'] + box['h'] * 0.85
    await drag(x1, y1, x2, y2)
    a = await page.ev('({ calls: __selCalls, n: SM.app.tables[0].selectedRows().length })')
    ym = (y1 + y2) / 2
    await drag(x1, ym, x1 + 60, ym)
    b = await asyncio.wait_for(page.ev('({ calls: __selCalls, n: SM.app.tables[0].selectedRows().length })'), 20)
    await drag(x2, ym, x2 - 60, ym)
    c = await asyncio.wait_for(page.ev('({ calls: __selCalls, n: SM.app.tables[0].selectedRows().length })'), 20)
    check('a box selection selects its rows once', (a['calls'], a['n'] > 0), (1, True))
    check('moving its left edge selects once more, fewer rows, and the tab answers', (b['calls'], 0 < b['n'] < a['n']), (2, True))
    check('moving its right edge too', (c['calls'], 0 < c['n'] < b['n']), (3, True))
    r = await page.ev('''(async () => {
      const t = SM.app.tables[0]; const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => p.drawn);
      const kept = (p.box.layout.selections || []).length;
      t.select([0, 1, 2]);
      await new Promise(res => setTimeout(res, 300));
      const out = { kept, after: (p.box.layout.selections || []).length, selected: t.selectedRows(), calls: __selCalls, sp: p.box.data[0].selectedpoints };
      __unsel(); t.select([]); SM.app.closeReport(rep);
      return out;
    })()''')
    check('the kept box goes when rows are selected elsewhere', (r['kept'], r['after']), (1, 0))
    check('... and that selection stands, in the graph too', (r['selected'], r['calls'], sorted(r['sp'] or [])), ([0, 1, 2], 4, [0, 1, 2]))

    # ---- dark theme and phone width
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports[0]))')
    await asyncio.sleep(1.2)
    await shot(page, '04-dark.png')
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[0]; const p = rep.plots.find(p => p.drawn);
      const img = await rep.plotImage(p, 'svg');
      const svg = decodeURIComponent(img.data.replace(/^data:image\\/svg\\+xml,/, ''));
      return { dark: SM.util.themeColors().dark, paper: /rgb\\(53, ?41, ?33\\)|#352921/i.test(svg) };
    })()''')
    check('dark theme: a graph for a document is drawn in the light theme', (r['dark'], r['paper']), (True, True))
    # a diagram drawn as SVG and styled by the page's CSS (Partition's tree,
    # say) keeps its paint in a document, in the light theme's colours, and
    # loses its buttons
    r = await page.ev('''(async () => {
      document.head.append(Object.assign(document.createElement('style'), { textContent: '.t-box { fill: var(--bg-surface); stroke: var(--text-muted); } .t-text { fill: var(--text-primary); }' }));
      const NS = 'http://www.w3.org/2000/svg', mk = (tag, a) => { const e = document.createElementNS(NS, tag); for (const k in a) e.setAttribute(k, a[k]); return e; };
      SM.platforms.register({ id: 'core-svg-test', label: 'SVG Test', render(ctx) {
        const s = mk('svg', { width: 120, height: 40, viewBox: '0 0 120 40' });
        const t = mk('text', { class: 't-text', x: 10, y: 25 }); t.textContent = 'node';
        const g = mk('g', { role: 'button' }); g.append(mk('path', { d: 'M0 0 L5 0 L2 4 Z' }));
        s.append(mk('rect', { class: 't-box', x: 1, y: 1, width: 118, height: 38 }), t, g);
        ctx.outline('Diagram').add(s);
      } });
      const rep = SM.app.openReport(SM.platforms.get('core-svg-test'), { roles: {}, options: {} }, SM.app.tables[0]);
      await new Promise(res => rep.on('done', res));
      const doc = new DOMParser().parseFromString(await rep.documentHtml(), 'text/html');
      const text = doc.querySelector('svg text'), box = doc.querySelector('svg rect');
      const zip = await JSZip.loadAsync(await SM.docx.report(rep, { plotImage: (p) => rep.plotImage(p, 'png', 2) }));
      const pics = Object.keys(zip.files).filter(f => /^word\\/media\\/.+\\.png$/.test(f)).length;
      SM.app.closeReport(rep);
      return { text: text && text.getAttribute('style'), box: box && box.getAttribute('style'), buttons: doc.querySelectorAll('svg [role="button"]').length, pics };
    })()''')
    check('a document keeps an SVG diagram\'s paint, in the light theme\'s colours', ('fill:rgb(53, 41, 33)' in (r['text'] or ''), 'stroke:rgb(120, 107, 93)' in (r['box'] or '')), (True, True))
    check('without its buttons', r['buttons'], 0)
    check('Word gets it as a picture', r['pics'], 1)
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    wide = await page.ev('document.documentElement.scrollWidth <= innerWidth + 1')
    check('no horizontal page scroll at phone width', wide, True)
    work = await page.ev("Math.round(document.querySelector('.sm-main').getBoundingClientRect().width)")
    check('the work area fills the phone width', work >= 380, True)
    await shot(page, '05-phone.png')

    # A graph put straight into an outline body fits the body's content box
    # (its padding is no room), points take the dark theme's colour, and code
    # a platform only shows goes into Save Python Script.
    r = await page.ev('''(async () => {
      SM.platforms.register({ id: 'core-width-test', label: 'Width Test', render(ctx) {
        const o = ctx.outline('Wide Graph');
        o.add(ctx.plot([{ type: 'scatter', mode: 'markers', x: [1, 2, 3], y: [3, 1, 2], rows: [0, 1, 2] }], {}, { width: 700, height: 200 }));
        o.add(ctx.code('# shown only, from no call'));
      } });
      const rep = SM.app.openReport(SM.platforms.get('core-width-test'), { roles: {}, options: {} }, SM.app.tables[0]);
      await new Promise(res => rep.on('done', res));
      await new Promise(res => setTimeout(res, 400));
      const p = rep.plots[0];
      if (!p.drawn) await p.draw();
      const body = p.box.parentElement, cs = getComputedStyle(body);
      const inner = body.getBoundingClientRect().right - parseFloat(cs.paddingRight);
      const out = { drawn: p.drawn, fits: p.box.getBoundingClientRect().right <= inner + 1, noScroll: rep.body.scrollWidth <= rep.body.clientWidth + 1,
        base: SM.report.BASE, point: p.base[0].color, script: rep.pythonScript().includes('# shown only, from no call') };
      SM.app.closeReport(rep);
      return out;
    })()''')
    check('phone: a graph in an outline body is drawn', r['drawn'], True)
    check('phone: the graph fits the body without its padding', r['fits'], True)
    check('phone: the report does not scroll sideways', r['noScroll'], True)
    check('dark theme: points take the lighter blue', (r['base'], r['point']), ('#6fa3d6', '#6fa3d6'))
    check('code shown with ctx.code goes into Save Python Script', r['script'], True)
    esc = await page.ev("SM.report.plotlyText('a <b> & %{x}')")
    check('plotlyText escapes tags, entities and a hovertemplate placeholder', esc, 'a &lt;b&gt; &amp; &#37;{x}')
    check('no script errors', page.errors, [])
    await page.close()

    # ---- a phone: a dialog is the whole screen (its title bar above the
    # site's header), the (i) panel too, and a column is dragged by touch:
    # held a moment, then moved (a swipe at once still scrolls). Onto a role,
    # Fit Model's model effects (the dialog scrolls to them), the formula
    # and Graph Builder's Y zone (the report scrolls to it).
    page = await open_page(f'{BASE}/smui.html?example=plants', width=400, height=820)
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 820, 'deviceScaleFactor': 2, 'mobile': True}, session=page.sid)
    await page.call('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 1}, session=page.sid)
    await wait_engine(page)

    async def touch(kind, pts):
        await page.call('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': pts}, session=page.sid)

    async def slide(x0, y0, x1, y1, steps=8):
        for i in range(1, steps + 1):
            await touch('touchMove', [{'x': x0 + (x1 - x0) * i / steps, 'y': y0 + (y1 - y0) * i / steps}])
            await asyncio.sleep(0.03)

    def rect(sel):
        return page.ev(f'''(() => {{ const e = {sel}; if (!e) return null; const r = e.getBoundingClientRect(); return [r.x + Math.min(40, r.width / 2), r.y + r.height / 2, r.top, r.bottom]; }})()''')

    async def drag_to(src, dst_sel, far_top=None):
        # held, then moved; to the bottom edge first when the target is below the screen
        await touch('touchStart', [{'x': src[0], 'y': src[1]}])
        await asyncio.sleep(0.45)
        if far_top is not None:
            await slide(src[0], src[1], src[0], 806)
            for _ in range(100):
                await touch('touchMove', [{'x': src[0], 'y': 806}])
                await asyncio.sleep(0.05)
                r = await rect(dst_sel)
                if r and r[2] < far_top:
                    break
            src = [src[0], 806]
        dst = await rect(dst_sel)
        await slide(src[0], src[1], dst[0], dst[1])
        await touch('touchEnd', [])
        await asyncio.sleep(0.4)

    await page.ev("SM.app.launch('fitmodel')")
    await asyncio.sleep(0.4)
    r = await page.ev('''(() => { const d = document.querySelector('.sm-launch-dialog'), b = d.getBoundingClientRect(), x = d.querySelector('.sm-dialog-x').getBoundingClientRect();
      const hit = document.elementFromPoint(x.left + x.width / 2, x.top + x.height / 2);
      return { box: [b.left, b.top, b.width, b.height].map(Math.round), vw: innerWidth, vh: innerHeight, xOnTop: !!(hit && hit.closest('.sm-dialog-x')) }; })()''')
    check('phone: a dialog is the whole screen', r['box'], [0, 0, r['vw'], r['vh']])
    check('phone: its title bar, with the ×, is above the site\'s header', r['xOnTop'], True)
    src = await rect("[...document.querySelectorAll('.sm-launch-dialog .sm-pick-list li')].find(li => li.textContent === 'yield (g)')")
    ydst = "[...document.querySelectorAll('.sm-launch-dialog .sm-role')].find(x => x.querySelector('.sm-btn').textContent === 'Y').querySelector('.sm-role-list')"
    await touch('touchStart', [{'x': src[0], 'y': src[1]}])
    await slide(src[0], src[1], src[0], src[1] + 60, 5)
    await touch('touchEnd', [])
    await asyncio.sleep(0.3)
    swiped = await page.ev(f"[...({ydst}).querySelectorAll('li')].map(li => li.textContent)")
    # held: the item cannot be selected as text, though its draggable is
    # "false" while the finger is down (an iPhone selected the text, and
    # the drag never began, while the CSS asked for draggable="true")
    await touch('touchStart', [{'x': src[0], 'y': src[1]}])
    await asyncio.sleep(0.45)
    held = await page.ev('''(() => { const li = [...document.querySelectorAll('.sm-launch-dialog .sm-pick-list li')].find(li => li.textContent === 'yield (g)');
      const cs = getComputedStyle(li); const e = new Event('selectstart', { bubbles: true, cancelable: true }); li.dispatchEvent(e);
      return { attr: li.getAttribute('draggable'), select: cs.userSelect || cs.webkitUserSelect, refused: e.defaultPrevented, ready: li.classList.contains('sm-touch-ready') }; })()''')
    await touch('touchEnd', [])
    await asyncio.sleep(0.2)
    check('phone: a held item shows it is ready, and cannot be selected as text', (held['attr'], held['select'], held['refused'], held['ready']), ('false', 'none', True, True))
    check('phone: its draggable comes back when the finger lifts', await page.ev("[...document.querySelectorAll('.sm-launch-dialog .sm-pick-list li')].find(li => li.textContent === 'yield (g)').getAttribute('draggable')"), 'true')
    # while it is dragged the item is seen under the finger, above the dialog
    # (it went behind it on an iPhone), and the places that take it are marked
    await touch('touchStart', [{'x': src[0], 'y': src[1]}])
    await asyncio.sleep(0.45)
    await slide(src[0], src[1], src[0] + 40, src[1] + 120, 6)
    mid = await page.ev('''(() => { const g = document.querySelector('.sm-touchghost'), back = document.querySelector('.sm-modal-back');
      if (!g) return null; const r = g.getBoundingClientRect();
      return { text: g.textContent, icon: !!g.querySelector('.sm-type'), above: +getComputedStyle(g).zIndex > +getComputedStyle(back).zIndex,
        seen: r.top >= 0 && r.bottom <= innerHeight && r.width > 40, marked: document.documentElement.classList.contains('sm-dragging'),
        faint: getComputedStyle(document.querySelectorAll('.sm-launch-dialog .sm-role-list')[1]).outlineStyle }; })()''')
    ydst_r = await rect(ydst)
    await slide(src[0] + 40, src[1] + 120, ydst_r[0], ydst_r[1], 6)
    await touch('touchEnd', [])
    await asyncio.sleep(0.4)
    after = await page.ev("({ ghost: !!document.querySelector('.sm-touchghost'), marked: document.documentElement.classList.contains('sm-dragging') })")
    check('phone: the dragged item is seen under the finger, with its type icon, above the dialog', (mid and mid['text'], mid and mid['icon'], mid and mid['above'], mid and mid['seen']), ('yield (g)', True, True, True))
    check('phone: while it is dragged the places that take it are marked', (mid and mid['marked'], mid and mid['faint']), (True, 'dashed'))
    check('phone: after the drop the item and the marks go', (after['ghost'], after['marked']), (False, False))
    ys = await page.ev(f"[...({ydst}).querySelectorAll('li')].map(li => li.textContent)")
    check('phone: a swipe over a column scrolls, it does not drag', swiped, [])
    check('phone: held, then dragged onto Y', ys, ['yield (g)'])
    src = await rect("(() => { const li = [...document.querySelectorAll('.sm-launch-dialog .sm-pick-list li')].find(li => li.textContent === 'water'); li.scrollIntoView({ block: 'center' }); return li; })()")
    await drag_to(src, "document.querySelector('.sm-launch-dialog .sm-fm-effects')", far_top=600)
    check('phone: dragged onto the model effects, the dialog scrolling to them', await page.ev("[...document.querySelectorAll('.sm-launch-dialog .sm-fm-effects li')].map(li => li.textContent)"), ['water'])
    await page.ev("document.querySelector('.sm-launch-dialog .sm-dialog-head .info-btn').click()")
    await asyncio.sleep(0.3)
    r = await page.ev("(() => { const b = document.querySelector('.info-panel').getBoundingClientRect(); return [b.left, b.top, b.width, b.height].map(Math.round); })()")
    check('phone: the (i) panel is the whole screen too', r, [0, 0, 400, 820])
    await page.ev("KvotInfo.close(); document.querySelector('.sm-launch-dialog .sm-dialog-x').click()")
    await asyncio.sleep(0.3)
    await page.ev("(() => { window.__fp = SM.formula.edit(SM.app.current, null, { name: 'f' }); return 1; })()")
    await asyncio.sleep(0.4)
    await page.ev("(() => { const ta = [...document.querySelectorAll('.sm-dialog')].pop().querySelector('textarea.smf-expr'); ta.value = '2 * '; ta.dispatchEvent(new Event('input')); ta.setSelectionRange(4, 4); })()")
    src = await rect("(() => { const b = [...[...document.querySelectorAll('.sm-dialog')].pop().querySelectorAll('.smf-item')].find(b => b.textContent === 'water'); b.scrollIntoView({ block: 'center' }); return b; })()")
    await drag_to(src, "[...document.querySelectorAll('.sm-dialog')].pop().querySelector('textarea.smf-expr')")
    check('phone: a column dragged into the formula goes in at its cursor', await page.ev("[...document.querySelectorAll('.sm-dialog')].pop().querySelector('textarea.smf-expr').value"), '2 * :water')
    await page.ev("[...[...document.querySelectorAll('.sm-dialog')].pop().querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Cancel').click()")
    await asyncio.sleep(0.3)
    await page.ev('''(async () => { const t = SM.app.current; const rep = SM.app.openReport(SM.platforms.get('graphbuilder'), { roles: {}, options: {} }, t); await new Promise(res => rep.on('done', res)); SM.app.showTab(SM.app.tabOf(rep)); })()''')
    await asyncio.sleep(0.8)
    src = await rect("(() => { const li = [...document.querySelectorAll('.sm-gb-collist li')].find(li => li.textContent.includes('yield (g)')); li.scrollIntoView({ block: 'center' }); return li; })()")
    await drag_to(src, "document.querySelector('.sm-gb-z-y')", far_top=450)
    check('phone: dragged onto Graph Builder\'s Y zone, the report scrolling to it', await page.ev("document.querySelector('.sm-gb-z-y').textContent.includes('yield (g)')"), True)
    # a tap on Python code: the code is far below the screen, the report scrolls to it
    await page.ev(open_report_js('distribution', {'y': ['yield (g)']}))
    await asyncio.sleep(0.6)
    b = await rect(f'{LAST}.codeBtn')
    before = await page.ev(CODE)
    await touch('touchStart', [{'x': b[0], 'y': b[1]}])
    await touch('touchEnd', [])
    await asyncio.sleep(1)
    r = await page.ev(CODE)
    # (the nearest block may be a graph's, in view already: then there is nothing to scroll)
    check('phone: a tap on Python code shows the code, scrolled to when below the screen', (before['seen'], r['n'] > 0 and r['open'] == r['n'], r['seen'] > 0), (0, True, True))
    check('phone: no script errors', page.errors, [])
    await page.close()

    # ---- the full window: the workbench without the site's header and
    # footer, by the button at the right end of the menu bar; there the kvot
    # mark goes to the home page and the site's theme switch is in the menu
    # bar; the choice is kept for the next visit, from before the workbench
    # is made; at phone width the two buttons stay at the right edge while
    # the menus scroll under them
    page = await open_page(f'{BASE}/smui.html?example=students')
    await wait_engine(page)
    await page.ev("localStorage.removeItem('smui.full')")
    FULL = """(() => { const shown = (s) => { const e = document.querySelector(s); return !!e && getComputedStyle(e).display !== 'none' && e.getClientRects().length > 0; };
      const c = document.querySelector('.content').getBoundingClientRect(), b = document.querySelector('.sm-fullbtn');
      return { on: document.documentElement.classList.contains('sm-full'), site: [shown('body > header'), shown('body > footer'), shown('body > .nav-toggle')],
        top: Math.round(c.top), fills: Math.round(c.height) === innerHeight, mine: [shown('.sm-homelink'), shown('.sm-menubar .theme-toggle')],
        pressed: b.getAttribute('aria-pressed'), stored: localStorage.getItem('smui.full') }; })()"""
    THEME = """[document.documentElement.dataset.theme, document.querySelector('.sm-menubar .theme-toggle').textContent, localStorage.getItem('kvot-theme')]"""
    MARK = """(() => { const a = document.querySelector('.sm-homelink'), img = a.querySelector('img');
      return [a.getAttribute('href'), img.complete && img.naturalWidth > 0, img.alt, a.getBoundingClientRect().left < 12]; })()"""
    EARLY = """document.addEventListener('readystatechange', () => {
      if (document.readyState !== 'interactive' || window.__early) return;
      const h = document.querySelector('body > header');
      window.__early = { full: document.documentElement.classList.contains('sm-full'), app: !!(window.SM && window.SM.app), header: h ? getComputedStyle(h).display : null };
    });"""
    EDGE = """(() => { const m = document.querySelector('.sm-menubar'), bar = m.getBoundingClientRect(), end = m.querySelector('.sm-menuend').getBoundingClientRect(), mark = m.querySelector('.sm-homelink').getBoundingClientRect();
      return { scrolls: m.scrollWidth > m.clientWidth, atRight: Math.abs(end.right - bar.right) <= 1, markAt: Math.round(mark.left - bar.left + m.scrollLeft) }; })()"""

    async def press(sel):
        x, y = await page.ev(f'(() => {{ const r = document.querySelector({json.dumps(sel)}).getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()')
        await page.click(x, y)
        await asyncio.sleep(0.3)

    try:
        r = await page.ev(FULL)
        check('the site\'s header, menu and footer around the workbench, as before', (r['on'], r['site'], r['top'], r['mine'], r['pressed']), (False, [True, True, True], 43, [False, False], 'false'))
        await press('.sm-fullbtn')
        r = await page.ev(FULL)
        check('the full-window button: no site header, menu or footer', (r['on'], r['site'], r['pressed'], r['stored']), (True, [False, False, False], 'true', '1'))
        check('... the workbench takes the whole window', (r['top'], r['fills']), (0, True))
        check('... and the kvot mark and the theme switch are in the menu bar', r['mine'], [True, True])
        check('the kvot mark, at the left, goes to the home page', await page.ev(MARK), ['./index.html', True, 'kvot ab: the home page', True])
        await press('.sm-menubar .theme-toggle')
        r = await page.ev(THEME)
        await press('.sm-menubar .theme-toggle')
        r2 = await page.ev(THEME)
        check('its theme switch changes the theme and keeps it, as the footer\'s does', (r, r2), (['dark', '☀️', 'dark'], ['light', '🌙', 'light']))
        # the next visit: in the full window before the workbench is made (no header shown while it loads)
        await page.call('Page.addScriptToEvaluateOnNewDocument', {'source': EARLY}, session=page.sid)
        await page.call('Page.reload', {}, session=page.sid)
        await asyncio.sleep(0.5)
        await wait_engine(page)
        check('the next visit is in the full window from the start, before the workbench is made', await page.ev('window.__early || null'), {'full': True, 'app': False, 'header': 'none'})
        r = await page.ev(FULL)
        check('... its button pressed', (r['on'], r['pressed'], r['fills']), (True, 'true', True))
        await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 820, 'deviceScaleFactor': 2, 'mobile': True}, session=page.sid)
        await asyncio.sleep(0.5)
        a = await page.ev(EDGE)
        await page.ev("document.querySelector('.sm-menubar').scrollLeft = 150")
        b = await page.ev(EDGE)
        r = await page.ev("({ fills: Math.round(document.querySelector('.content').getBoundingClientRect().height) === innerHeight, wide: document.documentElement.scrollWidth <= innerWidth + 1 })")
        check('phone: the menus scroll under the theme switch and the full-window button, at the right edge', (a['scrolls'], a['atRight'], b['atRight']), (True, True, True))
        check('phone: the kvot mark first in the menu bar, the workbench the whole screen and no wider', (a['markAt'] < 10, r['fills'], r['wide']), (True, True, True))
        await page.ev("document.querySelector('.sm-menubar').scrollLeft = 0")
        await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
        await asyncio.sleep(0.4)
        await press('.sm-fullbtn')
        r = await page.ev(FULL)
        check('pressed again: the header, menu and footer are back, and that is kept', (r['on'], r['site'], r['top'], r['mine'], r['pressed'], r['stored']), (False, [True, True, True], 43, [False, False], 'false', '0'))
        check('full window: no script errors', page.errors, [])
    finally:
        await page.ev("localStorage.removeItem('smui.full')")     # (the lane's later suites open pages in this browser)
        await page.close()

    # ---- an engine that goes on loading says what may be wrong (a colleague's
    # computer never got past the packages): its time on the status line and,
    # past 90 s, a note on the home page with Restart and What it is doing.
    # The download is slowed to a crawl once the page is up, and the start
    # moved 100 s back.
    page = await open_page(f'{BASE}/smui.html')
    for _ in range(200):
        await asyncio.sleep(0.1)
        if await page.ev('!!(window.SM && SM.app && SM.app.started)'):
            break
    await page.call('Network.emulateNetworkConditions', {'offline': False, 'latency': 50, 'downloadThroughput': 30e3, 'uploadThroughput': 30e3}, session=page.sid)
    await asyncio.sleep(1)
    r = await page.ev('''(async () => {
      const e = SM.engine; const btn = document.querySelector('.sm-engine');
      if (e.state !== 'loading') return { skipped: e.state };
      e.startedAt -= 100000;
      await new Promise(res => setTimeout(res, 1500));
      const out = { line: btn.textContent, flag: btn.dataset.slow, hint: document.querySelector('.sm-home-slow')?.textContent || '',
        buttons: [...document.querySelectorAll('.sm-home-slow button')].map(b => b.textContent) };
      [...document.querySelectorAll('.sm-home-slow button')].find(b => b.textContent === 'What it is doing').click();
      await new Promise(res => setTimeout(res, 200));
      const d = [...document.querySelectorAll('.sm-dialog')].pop();
      out.rows = d ? [...d.querySelectorAll('tr')].map(tr => tr.children[0].textContent) : [];
      if (d) d.querySelector('.sm-dialog-x').click();
      [...document.querySelectorAll('.sm-home-slow button')].find(b => b.textContent === 'Restart the engine').click();
      await new Promise(res => setTimeout(res, 300));
      out.after = { slow: e.slow, state: e.state, hint: !!document.querySelector('.sm-home-slow'), flag: btn.dataset.slow };
      return out;
    })()''')
    if isinstance(r, dict) and r.get('skipped'):
        print(f"   (the engine was {r['skipped']} already: the slow-loading checks are skipped)")
    else:
        check('a long load shows its time on the status line', '(1 min ' in r['line'], True)
        check('... is flagged there', r['flag'], '1')
        check('... and the home page says what may be wrong', ('cdn.jsdelivr.net' in r['hint'], 'firewall' in r['hint'], r['buttons']), (True, True, ['Restart the engine', 'What it is doing']))
        check('What it is doing: how long it has loaded, and when it last said anything', ('Loading for' in r['rows'], 'Last news from the engine' in r['rows']), (True, True))
        check('Restart starts it again, and the note goes', (r['after']['slow'], r['after']['state'], r['after']['hint'], r['after']['flag']), (False, 'loading', False, '0'))
    await page.close()


    # ---- a graph's size: the grip in its corner (a real drag, the arrow keys, a double-click), Size… and
    # Default Size in its right-click menu; kept with the report (Redo, a project), the code's figsize in
    # proportion, a narrower window and back, the HTML document without the grip, Graph Builder's own size
    page = await open_page(f'{BASE}/smui.html?example=students')
    await wait_engine(page)
    await page.ev(open_report_js('distribution', {'y': ['height (cm)']}))
    await asyncio.sleep(1)
    G = """(() => { const rep = SM.app.reports.at(-1), p = rep.plots[0], g = p.box.querySelector(':scope > .sm-plot-grip');
      const b = g ? g.getBoundingClientRect() : null, pb = p.box.getBoundingClientRect(), blk = p.box.nextElementSibling;
      const fig = (t) => { const m = /figsize=\\(([0-9.]+), ([0-9.]+)\\)/.exec(t || ''); return m ? [Number(m[1]), Number(m[2])] : null; };
      return { w: p.width, h: p.height, lw: p.box._fullLayout && p.box._fullLayout.width, lh: p.box._fullLayout && p.box._fullLayout.height, def: p.defaultSize,
        grip: g ? { x: b.x + b.width / 2, y: b.y + b.height / 2, label: g.getAttribute('aria-label') } : null, plot: [pb.x + pb.width / 2, pb.y + pb.height / 2],
        sizes: rep.spec.options.plotSizes || null, base: blk && blk._code ? fig(blk._code.base) : null, code: blk && blk._code ? fig(blk._code.get()) : null,
        script: fig(rep.pythonScript().split('\\n').filter((l) => l.includes('figsize=')).join('\\n')) }; })()"""
    g0 = await page.ev(G)
    check('a graph has a grip in its corner, named for its graph', (g0['grip'] is not None, (g0['grip'] or {}).get('label', '').startswith('Resize the graph')), (True, True))

    async def drag(g, dx, dy):
        await page.mouse('mouseMoved', g['x'], g['y'])
        await page.mouse('mousePressed', g['x'], g['y'])
        for k in range(1, 9):
            await page.mouse('mouseMoved', g['x'] + dx * k / 8, g['y'] + dy * k / 8)
            await asyncio.sleep(0.03)
        await page.mouse('mouseReleased', g['x'] + dx, g['y'] + dy)
        await asyncio.sleep(0.5)
    await drag(g0['grip'], 120, 70)
    g1 = await page.ev(G)
    key = next(iter((g1['sizes'] or {}).keys()), None)
    check('a real drag of the grip makes the graph 120 px wider and 70 px taller, and Plotly draws it so',
          (g1['w'] - g0['w'], g1['h'] - g0['h'], g1['lw'], g1['lh']), (120, 70, g1['w'], g1['h']))
    check('... kept with the report, by the graph', (g1['sizes'] or {}).get(key), [g1['w'], g1['h']])
    ok_fig = bool(g1['base'] and g1['code']) and abs(g1['code'][0] - round(g1['base'][0] * g1['w'] / g1['def'][0], 2)) < 0.011 and abs(g1['code'][1] - round(g1['base'][1] * g1['h'] / g1['def'][1], 2)) < 0.011
    check('... its code\'s figure in the same proportion (figsize), in Save Python Script too', (ok_fig, g1['script'] == g1['code']), (True, True))
    await page.ev("SM.app.reports.at(-1).plots[0].box.querySelector('.sm-plot-grip').focus()")
    await page.key('ArrowRight')
    await page.key('ArrowDown', modifiers=8)
    await asyncio.sleep(0.3)
    g2 = await page.ev(G)
    check('the grip\'s arrow keys: 10 px a step, 50 px with shift', (g2['w'] - g1['w'], g2['h'] - g1['h'], (g2['sizes'] or {}).get(key)), (10, 50, [g2['w'], g2['h']]))
    await page.ev('(async () => { const rep = SM.app.reports.at(-1); const d = new Promise((res) => rep.on("done", res)); rep.run(); await d; await new Promise((r) => setTimeout(r, 400)); })()')
    g3 = await page.ev(G)
    check('Redo keeps the size', (g3['w'], g3['h'], g3['lw'], g3['lh']), (g2['w'], g2['h'], g2['w'], g2['h']))
    # the right-click menu of the plot: Size… (a dialog), Default Size
    await page.mouse('mouseMoved', g3['plot'][0], g3['plot'][1])
    await page.mouse('mousePressed', g3['plot'][0], g3['plot'][1], button='right')
    await page.mouse('mouseReleased', g3['plot'][0], g3['plot'][1], button='right')
    await asyncio.sleep(0.3)
    items = await page.ev("[...document.querySelectorAll('.sm-menu button .sm-label')].map((x) => x.textContent)")
    check('a right-click in the plot has Size… and Default Size', ('Size…' in (items or []), 'Default Size' in (items or [])), (True, True))
    await page.ev("""(async () => { [...document.querySelectorAll('.sm-menu button')].find((b) => b.textContent.includes('Size…')).click();
      await new Promise((r) => setTimeout(r, 300)); const d = [...document.querySelectorAll('.sm-dialog')].pop();
      const [w, h] = [...d.querySelectorAll('input')]; w.value = '420'; w.dispatchEvent(new Event('input', { bubbles: true })); h.value = '300'; h.dispatchEvent(new Event('input', { bubbles: true }));
      d.querySelector('.sm-dialog-foot .primary').click(); await new Promise((r) => setTimeout(r, 400)); })()""")
    g4 = await page.ev(G)
    check('Size… sets the width and height typed', (g4['w'], g4['h'], (g4['sizes'] or {}).get(key)), (420, 300, [420, 300]))
    # narrower than the graph, then wide again: it follows the room and comes back to its size
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await asyncio.sleep(0.8)
    narrow = await page.ev(G)
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await asyncio.sleep(0.8)
    wide = await page.ev(G)
    check('a narrower window makes the graph narrower, and it comes back to its width', (narrow['w'] < 420, wide['w'], wide['h']), (True, 420, 300))
    html = await page.ev('SM.app.reports.at(-1).documentHtml()')
    check('Save Report as HTML leaves the grip out', 'sm-plot-grip' in (html or ''), False)
    # a project keeps it: the report's JSON, opened again as a project (the columns get new ids)
    r = await page.ev("""(async () => { const rep = SM.app.reports.at(-1), t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      const n0 = SM.app.reports.length; SM.app.loadProject(j);
      for (let i = 0; i < 100 && SM.app.reports.length <= n0; i++) await new Promise((res) => setTimeout(res, 50));
      const back = SM.app.reports.at(-1); SM.app.showTab(SM.app.tabOf(back));
      for (let i = 0; i < 100 && !(back.plots[0] && back.plots[0].drawn); i++) await new Promise((res) => setTimeout(res, 60));
      const p = back.plots[0]; const out = { w: p && p.width, h: p && p.height, sizes: back.spec.options.plotSizes || null };
      SM.app.closeReport(back); SM.app.showTab(SM.app.tabOf(rep)); await new Promise((res) => setTimeout(res, 300)); return out; })()""")
    check('a project keeps the size', (r['w'], r['h'], list((r['sizes'] or {}).values())), (420, 300, [[420, 300]]))
    # Default Size, and a double-click on the grip
    await page.mouse('mouseMoved', wide['plot'][0], wide['plot'][1])
    await page.mouse('mousePressed', wide['plot'][0], wide['plot'][1], button='right')
    await page.mouse('mouseReleased', wide['plot'][0], wide['plot'][1], button='right')
    await asyncio.sleep(0.3)
    await page.ev("[...document.querySelectorAll('.sm-menu button')].find((b) => b.textContent.includes('Default Size')).click()")
    await asyncio.sleep(0.4)
    g5 = await page.ev(G)
    check('Default Size puts the report\'s size back, and its code\'s', ([g5['w'], g5['h']], g5['sizes'], g5['code'] == g5['base']), (g5['def'], None, True))
    await drag(g5['grip'], 60, 40)
    g6 = await page.ev(G)
    await page.mouse('mouseMoved', g6['grip']['x'], g6['grip']['y'])
    await page.mouse('mousePressed', g6['grip']['x'], g6['grip']['y'], clicks=1)
    await page.mouse('mouseReleased', g6['grip']['x'], g6['grip']['y'], clicks=1)
    await page.mouse('mousePressed', g6['grip']['x'], g6['grip']['y'], clicks=2)
    await page.mouse('mouseReleased', g6['grip']['x'], g6['grip']['y'], clicks=2)
    await asyncio.sleep(0.4)
    g7 = await page.ev(G)
    check('a double-click on the grip: the report\'s size again', ([g6['w'] - g5['w'], g6['h'] - g5['h']], [g7['w'], g7['h']], g7['sizes']), ([60, 40], g7['def'], None))
    # Graph Builder: its grip sets its own Graph Size
    r = await page.ev("""(async () => { const t = SM.app.current; const rep = SM.app.openReport(SM.platforms.get('graphbuilder'), { roles: {}, options: {} }, t);
      await new Promise((res) => rep.on('done', res)); const gb = SM.platforms.get('graphbuilder').builder(rep);
      await gb.update((S) => { S.zones.x = [{ id: t.col('height (cm)').id, name: 'height (cm)' }]; S.zones.y = [{ id: t.col('weight (kg)').id, name: 'weight (kg)' }]; });
      SM.app.showTab(SM.app.tabOf(rep)); let p = null;
      for (let i = 0; i < 100 && !p; i++) { await new Promise((r) => setTimeout(r, 60)); p = rep.plots.find((x) => x.drawn && x.box.isConnected && x.box.querySelector('.sm-plot-grip')); }
      if (!p) return { error: 'no drawn Graph Builder graph with a grip' };
      const g = p.box.querySelector('.sm-plot-grip'); g.scrollIntoView({ block: 'nearest' }); const b = g.getBoundingClientRect();
      return { x: b.x + b.width / 2, y: b.y + b.height / 2, w: p.width, h: p.height }; })()""")
    check('Graph Builder\'s graph has its grip', r.get('error') if isinstance(r, dict) else r, None)
    await drag(r, -80, 50)
    await asyncio.sleep(1.2)
    gb = await page.ev("(async () => { const rep = SM.app.reports.at(-1); let p = null; for (let i = 0; i < 60; i++) { p = rep.plots.filter((x) => x.drawn && x.box.isConnected).at(-1); if (p && p.width !== %d) break; await new Promise((r) => setTimeout(r, 60)); } return { size: SM.platforms.get('graphbuilder').builder(rep).state().size || null, w: p ? p.width : null, h: p ? p.height : null, ghost: !!document.querySelector('.sm-plot-ghost'), stored: rep.spec.options.plotSizes || null }; })()" % r['w'])
    check('Graph Builder\'s grip sets its own Graph Size (an outline follows the drag), which draws the graph again', (gb['size'], gb['w'], gb['h'], gb['ghost'], gb['stored']), ({'w': r['w'] - 80, 'h': r['h'] + 50}, r['w'] - 80, r['h'] + 50, False, None))
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(0.5)
    dk = await page.ev("(() => { const g = document.querySelector('.sm-plot-grip'); const cs = getComputedStyle(g); return [cs.color, cs.cursor]; })()")
    check('dark theme: the grip in the dark theme\'s text colour, with the resize cursor', (dk[0] not in ('rgb(0, 0, 0)', ''), dk[1]), (True, 'nwse-resize'))
    check('graph sizes: no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
