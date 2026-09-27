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
report's Python script is the code of its results; Distribution's interval
methods and Test Rate show what the page computes; dialogs move by their
title bar, a disabled menu item opens no submenu, the tab strip has no
scroll bar; a dialog's (i) explains its roles, options and fields; Print
prints the report as a document from a hidden frame, Save Report as Word
writes a .docx of the open outlines, tables and graphs, and the page's own
print leaves the site around the report out; the page draws in the dark
theme (documents keep the light one) and at phone width.

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
    r = await page.ev('''(() => { const s = document.querySelector('.sm-tabs'); return { h: s.scrollHeight - s.clientHeight, bar: s.offsetHeight - s.clientHeight - parseFloat(getComputedStyle(s).borderTopWidth) - parseFloat(getComputedStyle(s).borderBottomWidth) }; })()''')
    check('the tab strip does not scroll vertically', r['h'], 0)
    check('and shows no scroll bar', r['bar'], 0)

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
      const tables = [...rep.content.querySelectorAll('table.sm-rt, table.sm-kv')].filter(tb => !tb.closest('.sm-ob.is-closed') && tb.offsetParent !== null).length;
      const plots = rep.plots.filter(p => !p.box.closest('.sm-ob.is-closed')).length;
      SM.app.closeReport(rep);
      return { heads, plain, coded, tables, plots, title: rep.title };
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


asyncio.run(main())
sys.exit(check.done())
