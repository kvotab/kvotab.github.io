#!/usr/bin/env python3
"""smui.html in a real browser: JSL to Python.

Python > JSL to Python opens the converter. The page's own sample (for the
Students example) converts: the data-table work as pandas, each analysis
as the page's own code for it (a report run out of sight on the table),
and a note, with its line, for what did not convert; a click on a note's
line shows it in the JSL. The Python runs in a notebook without an error
and gives the reports' numbers; Open the Reports Here opens the analyses,
their options mapped (Fit Line, Means, t Test). A launch on a table that is
not open, and one on a column the script makes, stay notes; a syntax error
is a note and the lines after it still convert; a Where() narrows the
analysis's rows. A dropped .jsl file opens the converter; Ctrl+Enter
converts. Phone width.

Start a server on the repository root and headless Chrome (the recipe is in
../rb/README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT (defaults 8791, 9291),
then

    python3 resources/tests/smui/test-ui-jsl.py

Exit status 0 when every check passes.
"""
import asyncio
import json
import sys

from cdp import BASE, Checks, open_page, wait_engine

check = Checks()
CONV = 'SM.app.tabs.find(t => t.converter).converter'


async def main():
    page = await open_page(f'{BASE}/smui.html?example=students')
    check('the engine starts', await wait_engine(page), 'ready')

    async def convert(jsl):
        return await page.ev(f'''(async () => {{ const c = {CONV}; c.jsl.value = {json.dumps(jsl)}; const r = await c.convert();
          return {{ py: c.out.value, notes: r ? r.notes : [], status: c.statusEl.textContent, opened: c.opened.length }}; }})()''', timeout=400)

    # ---- the menu and the sample ----------------------------------------------------------------------
    labels = await page.ev("SM.app.menuItems('Python').filter(i => i.label).map(i => i.label)")
    check('the Python menu has JSL to Python…', 'JSL to Python…' in labels, True)
    await page.ev("SM.app.menuItems('Python').find(i => i.label === 'JSL to Python…').action()")
    await asyncio.sleep(0.4)
    check('it opens a tab of its own, the cursor in the JSL', await page.ev(f"[SM.app.activeTab.kind, document.activeElement === {CONV}.jsl.ta]"), ['jsl', True])
    r = await page.ev(f'''(async () => {{ const c = {CONV}; c.sample(); for (let i = 0; i < 600 && !/Converted|could not/.test(c.statusEl.textContent); i++) await new Promise(r => setTimeout(r, 100));
      return {{ py: c.out.value, status: c.statusEl.textContent, notes: [...c.notesEl.children].map(li => li.textContent), opened: c.opened.length }}; }})()''', timeout=400)
    py = r['py']
    check('Sample: the sample script converts, its analyses with this page\'s code', ('4 analyses' in r['status'], r['opened']), (True, 4))
    check('... the table as the reports\' code reads it, the formula column as pandas', ('dt = pd.read_csv("Students.csv", float_precision="round_trip")' in py, 'dt["BMI"] = dt["weight (kg)"] / (dt["height (cm)"] / 100) ** 2' in py), (True, True))
    check("... each analysis as its report's code, on the script's table", (py.count('df = dt.copy()\n') >= 4, 'DescrStatsW(x, ddof=1)' in py, 'smf.ols(' in py, '(line 13: Fit Model' in py), (True, True, True, True))
    check('... the imports once, at the top', (py.count('import numpy as np') == 1, py.index('import numpy as np') < py.index('dt = pd.read_csv')), (True, True))
    check('... what did not convert: a comment where it was, and a note with its line', ('# NOT CONVERTED (line 21): New Window(' in py, any(n.startswith('⚠line 21') and 'New Window' in n for n in r['notes'])), (True, True))
    sel = await page.ev(f'''(() => {{ const c = {CONV}; const b = [...c.notesEl.querySelectorAll('.sm-jsl-line')].find(b => b.textContent === 'line 21'); b.click(); const ta = c.jsl.ta; return ta.value.slice(ta.selectionStart, ta.selectionEnd); }})()''')
    check('a click on the note\'s line shows it in the JSL', sel.startswith('New Window( "Notes"'), True)

    # ---- the Python runs, and gives the reports' numbers --------------------------------------------------
    r = await page.ev(f'''(async () => {{ {CONV}.toNotebook(); const nb = SM.notebook.notebooks[SM.notebook.notebooks.length - 1]; await nb.runAll();
      const errs = nb.cells.flatMap(c => c.outputs.filter(o => o.type === 'error').map(o => (o.traceback || []).slice(-1)[0]));
      const out = nb.cells.map(c => c.outputs.filter(o => o.type === 'stream').map(o => o.text).join('')).join('\\n');
      const figs = nb.cells.reduce((n, c) => n + c.outputs.filter(o => o.data && (o.data['image/svg+xml'] || o.data['image/png'])).length, 0);
      return {{ cells: nb.cells.length, errs, out, figs }}; }})()''', timeout=600)
    check('Open in Notebook: a cell per analysis, and Run All runs them all without an error', (r['cells'] >= 5, r['errs']), (True, []))
    check('... the graphs\' code draws them too', r['figs'] >= 4, True)
    first = next((ln for ln in r['out'].split('\n') if ln.strip()), '').split()
    await page.ev(f'{CONV}.openReports()')
    await asyncio.sleep(1.5)
    await page.ev('Promise.all(SM.app.reports.map(r => r.running || Promise.resolve()))')
    rep = await page.ev('''(() => SM.app.reports.map(r => ({ title: r.title, heads: [...r.body.querySelectorAll('.sm-ob-head')].map(h => h.textContent.trim()),
      mean: (() => { const tr = [...r.body.querySelectorAll('table.sm-kv tr')].find(tr => tr.children[0].textContent === 'Mean'); return tr ? tr.children[1].textContent : null; })() })))()''')
    titles = [x['title'] for x in rep]
    check('Open the Reports Here opens the four analyses', (len(rep), titles[0]), (4, 'Distributions'))
    check('... the Distribution\'s mean is the one the Python printed', (rep[0]['mean'] or 'none')[:8], first[0][:8] if first else 'no output')
    heads = [h for x in rep for h in x['heads']]
    check('... the options mapped: Fit Line, Means/Anova, the t test', ('Linear Fit' in heads, any(h.startswith('Oneway Anova') or h == 'Means for Oneway Anova' for h in heads), any(h == 't Test' or h.startswith('t Test') for h in heads)), (True, True, True))

    # ---- what stays a note ----------------------------------------------------------------------------------------
    await page.ev(f'SM.app.showTab(SM.app.tabs.find(t => t.converter))')
    r = await convert('dt = Open( "$SAMPLE_DATA/Big Class.jmp" );\nDistribution( Y( :height ) );')
    check('a launch on a table that is not open: a note that says to open it, a comment in the Python', (any('not open here' in n['text'] and n['line'] == 2 for n in r['notes']), '# NOT CONVERTED (line 2): Distribution' in r['py'], r['opened']), (True, True, 0))
    r = await convert('dt = Data Table( "Students" );\ndt << New Column( "BMI2", Numeric, Formula( :Name( "weight (kg)" ) * 2 ) );\nDistribution( Y( :BMI2 ) );')
    check('a launch on a column the script makes: a note that says so', any('which the script makes' in n['text'] and n['line'] == 3 for n in r['notes']), True)
    r = await convert('x = 1;\ny = (2 + ;\nShow( x );')
    check('a syntax error is a note with its line, and the lines after it still convert', (any(n['line'] == 2 and n['severity'] == 'error' for n in r['notes']), 'print("x =", x)' in r['py']), (True, True))
    r = await convert('dt = Data Table( "Students" );\nDistribution( Y( :Name( "height (cm)" ) ), Where( :sex == "F" ) );')
    check('a Where() narrows the analysis\'s rows in the Python', 'df = dt.loc[' in r['py'] and '"F"' in r['py'], True)
    r2 = await page.ev(f'''(async () => {{ const nb = SM.notebook.open(SM.app, {{ name: 'Where', cells: [{{ type: 'code', source: {CONV}.out.value }}, {{ type: 'code', source: 'import pandas as pd\\nprint(pd.read_csv("Students.csv").query("sex == \\'F\\'")["height (cm)"].mean())' }}] }});
      await nb.runAll(); const o = nb.cells.map(c => c.outputs.filter(o => o.type === 'stream').map(o => o.text).join('')); const err = nb.cells.flatMap(c => c.outputs.filter(o => o.type === 'error')); nb.dirty = false; SM.notebook.close(SM.app, nb); return {{ o, err: err.length }}; }})()''', timeout=400)
    check('... and its mean is the mean of those rows', (r2['err'], r2['o'][0].split()[0][:8], r2['o'][1].strip()[:8]), (0, r2['o'][1].strip()[:8], r2['o'][0].split()[0][:8]))

    # ---- a dropped file, Ctrl+Enter ------------------------------------------------------------------------------------
    r = await page.ev('''(async () => { const f = new File(['Show( 1 + 2 );'], 'three.jsl', { type: 'text/plain' }); await SM.app.openFiles([f]);
      const tab = SM.app.activeTab; const c = tab.converter; for (let i = 0; i < 200 && !/Converted/.test(c.statusEl.textContent); i++) await new Promise(r => setTimeout(r, 100));
      return { kind: tab.kind, title: tab.title, py: c.out.value }; })()''', timeout=200)
    check('a .jsl file opens the converter with its text, converted', (r['kind'], r['title'], 'print("1 + 2 =", 1 + 2)' in r['py'] or 'print("1 + 2 =", 3)' in r['py'] or 'Show' not in r['py']), ('jsl', 'three', True))
    await page.ev('(() => { const c = SM.app.activeTab.converter; c.jsl.value = "Show( 40 + 2 );"; c.out.value = ""; c.jsl.focus(); })()')
    await page.key('Enter', 'Enter', modifiers=2)
    ok = False
    for _ in range(100):
        v = await page.ev('SM.app.activeTab.converter.out.value')
        if '40' in v:
            ok = True
            break
        await asyncio.sleep(0.1)
    check('Ctrl+Enter in the JSL converts', ok, True)
    check('no script errors', page.errors, [])
    await page.close()

    # ---- phone width ------------------------------------------------------------------------------------------------------
    page = await open_page(f'{BASE}/smui.html?example=students', width=400, height=820)
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 820, 'deviceScaleFactor': 2, 'mobile': True}, session=page.sid)
    await wait_engine(page)
    r = await page.ev('''(async () => { const c = SM.jsl.open(SM.app); c.jsl.value = SM.jsl.SAMPLE; await c.convert();
      const cols = [...c.el.querySelectorAll('.sm-jsl-col')].map(e => e.getBoundingClientRect());
      return { stacked: cols[1].top > cols[0].bottom - 1, over: document.documentElement.scrollWidth > innerWidth + 1 }; })()''', timeout=400)
    check('phone: the JSL above the Python, no side scrolling', (r['stacked'], r['over']), (True, False))
    check('phone: no script errors', page.errors, [])
    await page.close()
    sys.exit(check.done())


asyncio.run(main())
