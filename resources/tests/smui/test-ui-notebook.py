#!/usr/bin/env python3
"""smui.html in a real browser: the Python notebook and the reports'
editable code.

Python > New Notebook opens a tab; code typed with real keys runs on
Shift+Enter in the page's engine, and its output shows under the cell. The
open tables are the CSV files the reports' code reads (a report's code
gives the report's numbers in a cell) and smui.table() DataFrames with the
modeling types as dtypes; smui.new_table() makes a table in the page.
Figures come as images, HTML as sanitised elements (a script in an output
never runs), errors as tracebacks; Run All stops at an error; text cells
are Markdown; Restart forgets the variables; top-level await works; the
IPython lines notebooks carry are handled. A notebook goes to .ipynb and
.py and back (an .ipynb from elsewhere runs nothing and its HTML is
sanitised), and a project keeps it. In a report, Edit turns a code block
into an editor whose Run shows the output under it, Reset puts the code
back, and the report's layout holds; Notebook sends a block to a notebook,
Save > Open Script in Notebook the whole script. The editor's keys (Tab,
Shift+Tab, Enter after a colon, Backspace in an indent, Ctrl+/), closing a
notebook with changes, the dark theme and phone width.

Start a server on the repository root and headless Chrome (the recipe is in
../rb/README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT (defaults 8791, 9291),
then

    python3 resources/tests/smui/test-ui-notebook.py

Exit status 0 when every check passes.
"""
import asyncio
import json
import sys

from cdp import BASE, Checks, open_page, open_report_js, wait_engine

check = Checks()
SHIFT, CTRL, ALT = 8, 2, 1

NB = 'SM.notebook.notebooks[SM.notebook.notebooks.length - 1]'

# The editor of a report's code block: the computed styles of its two layers.
LAYERS = r"""(async () => { const rep = SM.app.reports[0]; SM.app.showTab(SM.app.tabOf(rep)); const d = rep.codeBlocks().find(d => /print\(d\.mean/.test(d.textContent)); d.open = true;
  if (!d.querySelector('textarea')) [...d.parentElement.querySelectorAll('.sm-code-btns button')].find(b => b.textContent === 'Edit').click();
  await new Promise(r => setTimeout(r, 200));
  const hl = d.querySelector('.sm-ed-hl'), ta = d.querySelector('.sm-ed-ta'), a = getComputedStyle(hl), b = getComputedStyle(ta);
  const keys = ['fontSize', 'lineHeight', 'fontFamily', 'paddingLeft', 'paddingTop', 'letterSpacing', 'whiteSpace', 'borderLeftWidth', 'marginTop'];
  return { diff: keys.filter(k => a[k] !== b[k]).map(k => `${k}: ${a[k]} / ${b[k]}`), numbers: getComputedStyle(hl.querySelector('.ln'), '::before').content !== 'none',
    same: Math.abs(hl.getBoundingClientRect().height - ta.getBoundingClientRect().height) < 1 }; })()"""

# Graph Maker's smoother and a Bivariate graph on the Business cycle table's date column, their code run.
DATES = r"""(async () => {
  const t = SM.app.openExample('cycles');
  const rep = SM.app.openReport(SM.platforms.get('graphmaker'), { roles: {}, options: {} }, t);
  await new Promise(res => { if (rep.body.querySelector('.sm-gm')) res(); else rep.on('done', res); });
  let gm = rep.body.querySelector('.sm-gm')._gm; await gm.idle();
  await gm.update(S => { for (const k of Object.keys(S.zones)) S.zones[k] = []; S.zones.x = [{ id: t.col('output').id, name: 'output' }]; S.zones.y = [{ id: t.col('quarter').id, name: 'quarter' }]; S.auto = false; S.elements = []; });
  await gm.elements(['points', 'smoother']);
  await gm.idle(); await new Promise(r => setTimeout(r, 300));
  gm = rep.body.querySelector('.sm-gm')._gm;
  const code = rep.pyCode.find(c => /make_smoothing_spline/.test(c)) || '';
  const trace = gm.plot().traces.find(tr => tr.mode === 'lines');
  const res = await SM.notebook.exec('dates', code + '\nfirst = float(spline((grid[0] - m) / s))\nfirst', { label: 'code', fresh: true });
  const got = res.outputs.find(o => o.type === 'result');
  const bv = SM.app.openReport(SM.platforms.get('bivariate'), { roles: { y: [t.col('output').id], x: [t.col('quarter').id] }, options: {} }, t);
  await new Promise(res => bv.on('done', res));
  const graphCode = bv.codeBlocks().map(d => d.querySelector('code') ? d.querySelector('code').textContent : '').find(c => /plt\.show\(\)/.test(c)) || '';
  const res2 = await SM.notebook.exec('dates2', graphCode, { label: 'code', fresh: true });
  return { conv: /pd\.to_datetime\(df\["quarter"\]\)/.test(code), errors: res.outputs.filter(o => o.type === 'error').map(o => o.evalue), first: got ? +got.data['text/plain'] : null, page: trace ? trace.y[0] : null,
    conv2: /pd\.to_datetime\(df\["quarter"\]\)/.test(graphCode), errors2: res2.outputs.filter(o => o.type === 'error').map(o => o.evalue),
    fig2: res2.outputs.some(o => o.data && (o.data['image/svg+xml'] || o.data['image/png'])) };
})()"""


async def main():
    page = await open_page(f'{BASE}/smui.html?example=students')
    check('the engine starts', await wait_engine(page), 'ready')

    async def wait_for(expr, seconds=90):
        for _ in range(int(seconds * 10)):
            if await page.ev(expr):
                return True
            await asyncio.sleep(0.1)
        return False

    async def run_code(code, nb=NB, add=True):
        """A cell with this code, run; its outputs as {type, text, tags}."""
        return await page.ev(f'''(async () => {{ const nb = {nb}; const c = {'nb.add("code")' if add else 'nb.cells[nb.cells.length - 1]'};
          c.editor.value = {json.dumps(code)}; await nb.run(c);
          return {{ count: c.count, outs: c.outputs.map(o => ({{ type: o.type, text: o.text || (o.data && o.data['text/plain']) || (o.traceback || []).join('\\n'), mimes: Object.keys(o.data || {{}}) }})),
            tags: [...c.out.children].map(e => e.tagName.toLowerCase() + (e.className ? '.' + e.className.split(' ').join('.') : '')), html: c.out.innerHTML.slice(0, 3000) }}; }})()''', timeout=240)

    # ---- the menu, a new notebook, real keys --------------------------------------------------------
    r = await page.ev("SM.app.menuItems('Python').filter(i => i.label).map(i => i.label)")
    check('the Python menu: New Notebook, Open Notebook…, Report Script in Notebook', [x for x in r if x in ('New Notebook', 'Open Notebook…', 'Report Script in Notebook')], ['New Notebook', 'Open Notebook…', 'Report Script in Notebook'])
    await page.ev("SM.app.menuItems('Python').find(i => i.label === 'New Notebook').action()")
    await asyncio.sleep(0.5)
    r = await page.ev(f'''(() => {{ const nb = {NB}; const tab = SM.app.activeTab; return {{ kind: tab.kind, title: tab.title, cells: nb.cells.length, focused: document.activeElement === nb.cells[0].editor.ta }}; }})()''')
    check('New Notebook opens a tab with one code cell, the cursor in it', (r['kind'], r['title'].startswith('Notebook'), r['cells'], r['focused']), ('notebook', True, 1, True))
    await page.call('Input.insertText', {'text': 'import pandas as pd'}, session=page.sid)
    await page.key('Enter', 'Enter')
    await page.call('Input.insertText', {'text': 'df = pd.read_csv("Students.csv", float_precision="round_trip")'}, session=page.sid)
    await page.key('Enter', 'Enter')
    await page.call('Input.insertText', {'text': 'print(df.shape)'}, session=page.sid)
    await page.key('Enter', 'Enter', modifiers=SHIFT)
    ok = await wait_for(f'{NB}.cells[0].count === 1')
    r = await page.ev(f'''(() => {{ const nb = {NB}; return {{ out: nb.cells[0].out.textContent, cells: nb.cells.length, focused: document.activeElement === nb.cells[1].editor.ta, prompt: nb.cells[0].countEl.textContent }}; }})()''')
    check('typed code runs on Shift+Enter: the table is the file the reports\' code reads', (ok, r['out'].strip(), r['prompt']), (True, '(60, 5)', '[1]'))
    check('... and the cursor goes on to a new cell below', (r['cells'], r['focused']), (2, True))
    await page.call('Input.insertText', {'text': 'df.shape[0] * 2'}, session=page.sid)
    await page.key('Enter', 'Enter', modifiers=CTRL)
    await wait_for(f'{NB}.cells[1].count === 2')
    r = await page.ev(f'''(() => {{ const nb = {NB}; return {{ out: nb.cells[1].out.textContent, cells: nb.cells.length, focused: document.activeElement === nb.cells[1].editor.ta }}; }})()''')
    check('Ctrl+Enter runs and stays; the last line\'s value shows itself', (r['out'], r['cells'], r['focused']), ('120', 2, True))

    # ---- the tables ---------------------------------------------------------------------------------------
    r = await run_code('import smui\nt = smui.table("Students")\nsmui.table_names(), {c: str(t[c].dtype) for c in t}, t["age"].cat.ordered, list(t["sex"].cat.categories)')
    check('smui.table_names() names the open tables', "['Students']" in r['outs'][0]['text'], True)
    check('smui.table(): the modeling types as dtypes (ordinal ordered, in the value order)', ("'sex': 'category'" in r['outs'][0]['text'], "'height (cm)': 'float64'" in r['outs'][0]['text'], "True, ['F', 'M']" in r['outs'][0]['text']), (True, True, True))
    await page.ev('''(() => { const t = new SM.Table({ name: 'Days', columns: [{ name: 'd', dataType: 'numeric', modelingType: 'continuous', format: { kind: 'date' }, values: [0, 86400000] }, { name: 'n', dataType: 'numeric', modelingType: 'continuous', values: [1, 2] }] }); SM.app.addTable(t, { show: false }); })()''')
    r = await run_code('d = smui.table("days")\nstr(d["d"].dtype), str(d["d"].iloc[1].date()), open("Days.csv").read().split()')
    check('a date column comes as datetimes; a table opened since is there, as a file too', r['outs'][0]['text'], "('datetime64[ms]', '1970-01-02', ['d,n', '1970-01-01,1', '1970-01-02,2'])")
    r = await run_code('import pandas as pd\nout = pd.DataFrame({"g": pd.Categorical(["lo", "hi", "lo"], categories=["lo", "hi"], ordered=True), "x": [1.5, None, 3], "b": [True, False, True], "s": ["a", None, "c"]})\nsmui.new_table(out, "Made here")')
    t = await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Made here'); return t && { rows: t.nrows, cols: t.columns.map(c => [c.name, c.dataType, c.modelingType, c.valueOrder, c.values.map(v => (typeof v === 'number' && isNaN(v)) ? 'NaN' : v)]) }; })()''')
    check('smui.new_table() makes a table in the page', (t and t['rows'], r['outs'][0]['text']), (3, "'Made here: 3 rows, 4 columns, sent to the page'"))
    check('... ordered categoricals ordinal in their order, booleans nominal 0/1, missing kept', t and t['cols'], [['g', 'character', 'ordinal', ['lo', 'hi'], ['lo', 'hi', 'lo']], ['x', 'numeric', 'continuous', None, [1.5, 'NaN', 3]], ['b', 'numeric', 'nominal', None, [1, 0, 1]], ['s', 'character', 'nominal', None, ['a', None, 'c']]])

    # ---- a report's code, as it is ---------------------------------------------------------------------------
    rep = await page.ev(open_report_js('distribution', {'y': ['height (cm)']}))
    code = await page.ev('SM.app.reports[0].codeBlocks().find(d => /print\\(d\\.mean/.test(d.textContent)).querySelector("pre").textContent')
    mean = await page.ev('''(() => { const tr = [...SM.app.reports[0].body.querySelectorAll('table.sm-kv tr')].find(tr => tr.children[0].textContent === 'Mean'); return tr ? tr.children[1].textContent : null; })()''')
    await page.ev(f'SM.app.showTab(SM.app.tabs.find(t => t.notebook === {NB}))')
    r = await run_code(code)
    printed = r['outs'][0]['text'] if r['outs'] else ''
    check("a report's code runs in a cell as it is, and gives the report's mean", (bool(rep and rep.get('title')), printed.split()[0][:8] if printed else None), (True, mean[:8] if mean else 'no mean'))

    # ---- figures, HTML, errors, text, restart, await, magics ------------------------------------------------------
    r = await run_code('import matplotlib.pyplot as plt\nplt.hist(t["height (cm)"], bins=8)\nplt.title("height")\nplt.show()\nprint("after the figure")')
    check('a matplotlib figure shows where plt.show() is, as an SVG image', (r['tags'][:2], 'image/svg+xml' in r['outs'][0]['mimes']), (['img.sm-nb-img', 'pre.sm-nb-stream.stdout'], True))
    r = await run_code('import numpy as np\nx = np.random.default_rng(1).normal(size=5000)\nplt.scatter(x, x);')
    w = await page.ev(f'{NB}.cells[{NB}.cells.length - 1].out.querySelector("img").getAttribute("width")')
    check('a figure left open shows at the end; one of many points as a PNG, at half its pixels', (r['outs'][0]['mimes'][0], bool(w) and int(w) > 100), ('image/png', True))
    r = await run_code('class Evil:\n    def _repr_html_(self):\n        return \'<b>bold</b><script>window.__pwned = 1</script><img src=x onerror="window.__pwned = 2"><a href="javascript:window.__pwned = 3">x</a><table class="dataframe"><tr><td>1</td></tr></table>\'\nEvil()')
    evil = await page.ev(f'''(() => {{ const o = {NB}.cells[{NB}.cells.length - 1].out; return {{ b: !!o.querySelector('b'), script: !!o.querySelector('script'), img: !!o.querySelector('img'), jsLink: !!o.querySelector('a[href^="javascript"]'), table: !!o.querySelector('table'), cls: !!o.querySelector('[class="dataframe"]'), pwned: window.__pwned || 0 }}; }})()''')
    check('an HTML output is sanitised: its text and tables stay, scripts, images and javascript: links go', evil, {'b': True, 'script': False, 'img': False, 'jsLink': False, 'table': True, 'cls': False, 'pwned': 0})
    r = await run_code('def f():\n    return undefined_name\nf()')
    check('an error shows its traceback, the cell named after the notebook', (r['outs'][0]['type'], 'Notebook' in r['outs'][0]['text'] and "NameError: name 'undefined_name' is not defined" in r['outs'][0]['text']), ('error', True))
    r = await page.ev(f'''(async () => {{ const nb = SM.notebook.open(SM.app, {{ name: 'Run all', cells: [{{ type: 'code', source: 'ran_first = 1' }}] }});
      const a = nb.add('code'); a.editor.value = 'ran_a = 1';
      const b = nb.add('code'); b.editor.value = 'raise ValueError("stop here")';
      const c = nb.add('code'); c.editor.value = 'ran_c = 1';
      await nb.runAll(); const out = [a.count != null, b.outputs.map(o => o.type), c.count]; nb.dirty = false; SM.notebook.close(SM.app, nb); SM.app.showTab(SM.app.tabs.find(t => t.notebook === {NB})); return out; }})()''', timeout=300)
    check('Run All runs from the top and stops at the first error', r, [True, ['error'], None])
    r = await page.ev(f'''(async () => {{ const nb = {NB}; const c = nb.add('markdown'); c.editor.value = '# A heading\\nSome **bold**, `code`, a [link](https://kvotab.se) and [another](javascript:alert(1)).\\n\\n- one\\n- two\\n\\n| a | b |\\n|---|---|\\n| 1 | 2 |'; await nb.run(c);
      const m = c.md; return {{ h1: m.querySelector('h1')?.textContent, strong: m.querySelector('strong')?.textContent, code: m.querySelector('code')?.textContent, links: [...m.querySelectorAll('a')].map(a => a.getAttribute('href')), li: m.querySelectorAll('li').length, td: m.querySelectorAll('td').length, editing: !c.editor.el.hidden }}; }})()''')
    check('a text cell is Markdown: heading, bold, code, lists, a table, and only http(s) links', r, {'h1': 'A heading', 'strong': 'bold', 'code': 'code', 'links': ['https://kvotab.se'], 'li': 2, 'td': 2, 'editing': False})
    r = await run_code('import asyncio\nawait asyncio.sleep(0.01)\n"awaited"')
    check('top-level await works in a cell', r['outs'][0]['text'], "'awaited'")
    r = await run_code('%matplotlib inline\n%time x = 1\n%timeit y = 2\nx + 1')
    m = await page.ev('SM.notebook.magics("%pip install seaborn -q\\n  !pip install a b")')
    check("IPython's lines: %matplotlib goes quietly, %time runs its statement, %pip goes to micropip", (r['outs'][-1]['text'], m), ('2', 'import micropip; await micropip.install(["seaborn"])\n  import micropip; await micropip.install(["a","b"])'))
    await page.ev(f'{NB}.restart()')
    await asyncio.sleep(0.5)
    r = await run_code('t')
    check('Restart forgets the variables', (r['outs'][0]['type'], 'NameError' in r['outs'][0]['text']), ('error', True))

    # ---- files ----------------------------------------------------------------------------------------------------
    r = await page.ev(f'''(() => {{ const nb = {NB}; const j = SM.notebook.toIpynb(nb); const back = SM.notebook.fromIpynb(JSON.parse(JSON.stringify(j)), 'x');
      const kinds = j.cells.flatMap(c => (c.outputs || []).map(o => o.output_type));
      return {{ nbformat: j.nbformat, cells: j.cells.length, types: [...new Set(j.cells.map(c => c.cell_type))].sort(), kinds: [...new Set(kinds)].sort(), srcArray: Array.isArray(j.cells[0].source),
        same: JSON.stringify(back.cells.map(c => [c.type, c.source, (c.outputs || []).length])) === JSON.stringify(nb.cells.map(c => [c.type, c.source, c.type === 'code' ? c.outputs.length : 0])) }}; }})()''')
    check('.ipynb: format 4, code and markdown cells, Jupyter\'s output types', (r['nbformat'], r['types'], r['kinds'], r['srcArray']), (4, ['code', 'markdown'], ['display_data', 'error', 'execute_result', 'stream'], True))
    check('... and back: the same cells, sources and outputs', r['same'], True)
    r = await page.ev('''(() => { const nb = { name: 'P', cells: [{ type: 'markdown', source: '# Title\\nline two' }, { type: 'code', source: 'x = 1\\n\\nprint(x)' }, { type: 'code', source: 'y = 2' }] };
      const py = SM.notebook.toPy({ ...nb, cells: nb.cells.map(c => ({ ...c })) }); const back = SM.notebook.fromPy(py, 'P');
      const plain = SM.notebook.fromPy('import os\\nprint(1)\\n', 'Q');
      return { py, back: back.cells.map(c => [c.type, c.source]), plain: plain.cells.map(c => [c.type, c.source]) }; })()''')
    check('.py with # %% cells, and back', r['back'], [['markdown', '# Title\nline two'], ['code', 'x = 1\n\nprint(x)'], ['code', 'y = 2']])
    check('... a script without cell marks is one cell', r['plain'], [['code', 'import os\nprint(1)']])
    evil = {'nbformat': 4, 'nbformat_minor': 5, 'metadata': {'kernelspec': {'language': 'python'}}, 'cells': [
        {'cell_type': 'code', 'execution_count': 7, 'source': ['window.__ran = 1'], 'outputs': [
            {'output_type': 'display_data', 'data': {'text/html': ['<i>kept</i><script>window.__pwned = 4</script><iframe src="https://example.com"></iframe>'], 'text/plain': ['x']}, 'metadata': {}}]},
        {'cell_type': 'markdown', 'source': ['[bad](javascript:window.__pwned=5) *fine*']}]}
    busy = await page.ev('SM.engine.seq')
    await page.call('DOM.enable', session=page.sid)
    r = await page.ev(f'''(async () => {{ const f = new File([{json.dumps(json.dumps(evil))}], 'sent.ipynb', {{ type: 'application/json' }}); await SM.app.openFiles([f]);
      const nb = {NB}; const o = nb.cells[0].out;
      return {{ name: nb.name, cells: nb.cells.length, count: nb.cells[0].countEl.textContent, kept: o.querySelector('i')?.textContent, script: !!o.querySelector('script'), iframe: !!o.querySelector('iframe'),
        links: nb.cells[1].md.querySelectorAll('a').length, em: nb.cells[1].md.querySelector('em')?.textContent, pwned: window.__pwned || 0, ran: window.__ran || 0, dirty: nb.dirty }}; }})()''')
    seq = await page.ev('SM.engine.seq')
    check('File > Open reads an .ipynb: its cells and outputs, nothing run', (r['name'], r['cells'], r['count'], seq == busy, r['ran'], r['dirty']), ('sent', 2, '[7]', True, 0, False))
    check('... its HTML sanitised: no script, no frame, no javascript: link', (r['kept'], r['script'], r['iframe'], r['links'], r['em'], r['pwned']), ('kept', False, False, 0, 'fine', 0))
    r = await page.ev('''(() => { const nj = { name: 'Kept', cells: [{ type: 'code', source: 'kept = 1', outputs: [{ type: 'stream', name: 'stdout', text: 'hi\\n' }], count: 3 }] };
      const before = SM.notebook.notebooks.length; SM.app.loadProject({ format: 'smui-project', tables: [], reports: [], notebooks: [nj] });
      const nb = SM.notebook.notebooks[SM.notebook.notebooks.length - 1];
      return { added: SM.notebook.notebooks.length - before, name: nb.name, src: nb.cells[0].source, out: nb.cells[0].out.textContent, tab: !!SM.app.tabs.find(t => t.notebook === nb) }; })()''')
    check('a project reopens its notebooks, with their outputs', r, {'added': 1, 'name': 'Kept', 'src': 'kept = 1', 'out': 'hi\n', 'tab': True})

    # ---- a report's code block: Edit, Run, Reset, Close; Notebook; the whole script ----------------------------------------
    # the moments' block alone opened (a graph's code, open, would widen the graph's column by itself)
    orig = await page.ev('''(() => { SM.app.showTab(SM.app.tabOf(SM.app.reports[0])); const d = SM.app.reports[0].codeBlocks().find(d => /print\\(d\\.mean/.test(d.textContent)); d.open = true; return d.querySelector('pre').textContent; })()''')
    await asyncio.sleep(0.3)
    geo = '''(() => { const d = SM.app.reports[0].codeBlocks().find(d => /print\\(d\\.mean/.test(d.textContent)); const col = d.closest('.sm-ob-row').children; return [col[0].getBoundingClientRect().top, col[1].getBoundingClientRect().top].map(Math.round); })()'''
    top0 = await page.ev(geo)
    xy = await page.ev('''(() => { const b = [...SM.app.reports[0].codeBlocks().find(d => /print\\(d\\.mean/.test(d.textContent)).parentElement.querySelectorAll('.sm-code-btns button')].find(b => b.textContent === 'Edit'); b.scrollIntoView({ block: 'center' }); const r = b.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()''')
    await page.click(*xy)
    await asyncio.sleep(0.4)
    r = await page.ev('''(() => { const d = SM.app.reports[0].codeBlocks().find(d => /print\\(d\\.mean/.test(d.textContent)); const ta = d.querySelector('textarea'); return { editing: !!ta, focused: document.activeElement === ta, same: ta && ta.value === d.querySelector('.sm-ed-hl').textContent.replace(/\\u200b/g, '').replace(/\\n?$/, '') ? true : ta && ta.value.split('\\n').length === d.querySelectorAll('.sm-ed-hl .ln').length }; })()''')
    check('Edit turns the code into an editor, the cursor in it, the colours under the same lines', (r['editing'], r['focused'], r['same']), (True, True, True))
    await page.key('End', 'End', modifiers=CTRL)
    await page.key('Enter', 'Enter')
    await page.call('Input.insertText', {'text': 'print("the median is", np.median(x))'}, session=page.sid)
    await page.key('Enter', 'Enter', modifiers=SHIFT)
    ok = await wait_for('''(() => { const d = SM.app.reports[0].codeBlocks().find(d => /print\\(d\\.mean/.test(d.textContent)); return !/Running/.test(d.querySelector('.sm-code-status').textContent) && d.querySelector('.sm-code-out').textContent.length > 0; })()''')
    r = await page.ev('''(() => { const d = SM.app.reports[0].codeBlocks().find(d => /print\\(d\\.mean/.test(d.textContent)); return { out: d.querySelector('.sm-code-out').textContent, reset: d.querySelector('.sm-code-bar').children[1].disabled }; })()''')
    top1 = await page.ev(geo)
    check('Shift+Enter runs the edited code there: its output shows under it', (ok, 'the median is 157.0' in r['out'], r['reset']), (True, True, False))
    check('... and the report keeps its layout (the tables beside the graph)', (top0[0] == top0[1], top1[0] == top1[1]), (True, True))
    await page.ev('''(() => { const d = SM.app.reports[0].codeBlocks().find(d => /print\\(d\\.mean/.test(d.textContent)); d.querySelector('.sm-code-bar').children[1].click(); })()''')
    r = await page.ev('''(() => { const d = SM.app.reports[0].codeBlocks().find(d => /print\\(d\\.mean/.test(d.textContent)); return { back: d.querySelector('textarea').value, out: d.querySelector('.sm-code-out').hidden }; })()''')
    r['back'] = r['back'] == orig
    check("Reset puts the report's code back and clears the output", r, {'back': True, 'out': True})
    await page.ev('''(() => { const d = SM.app.reports[0].codeBlocks().find(d => /print\\(d\\.mean/.test(d.textContent)); const ta = d.querySelector('textarea'); ta.value += '\\n# mine'; ta.dispatchEvent(new Event('input', { bubbles: true })); d.querySelector('.sm-code-bar').children[2].click(); })()''')
    r = await page.ev('''(() => { const d = SM.app.reports[0].codeBlocks().find(d => /print\\(d\\.mean/.test(d.textContent)); return { pre: d.querySelector(':scope > pre')?.textContent.endsWith('# mine'), editor: !!d.querySelector('textarea'), edit: [...d.parentElement.querySelectorAll('.sm-code-btns button')].find(b => b.textContent === 'Edit').hidden }; })()''')
    check('Close goes back to the code as text, as edited', r, {'pre': True, 'editor': False, 'edit': False})
    n0 = await page.ev(f'{NB}.cells.length')
    await page.ev('''[...SM.app.reports[0].codeBlocks().find(d => /print\\(d\\.mean/.test(d.textContent)).parentElement.querySelectorAll('.sm-code-btns button')].find(b => b.textContent === 'Notebook').click()''')
    await asyncio.sleep(0.4)
    r = await page.ev(f'''(() => {{ const nb = SM.notebook.lastUsed; const cs = nb.cells; return {{ added: cs.length, last: cs[cs.length - 1].source.endsWith('# mine'), note: cs[cs.length - 2].type, shown: SM.app.activeTab.notebook === nb }}; }})()''')
    check('Notebook sends the block (as edited) to the notebook used last, with a line naming the report', (r['last'], r['note'], r['shown']), (True, 'markdown', True))
    r = await page.ev('''(async () => { const rep = SM.app.reports[0]; const item = rep.saveMenu().find(i => i.label === 'Open Script in Notebook'); const nb = await item.action(); const n = SM.notebook.notebooks[SM.notebook.notebooks.length - 1];
      await n.runAll(); return { name: n.name, cells: n.cells.map(c => c.type), errors: n.cells.flatMap(c => c.outputs.filter(o => o.type === 'error')).length, ran: n.cells.filter(c => c.count != null).length }; })()''', timeout=300)
    check("Save > Open Script in Notebook: the report's script, a cell per result, runs clean", (r['name'], r['cells'][0], r['errors'], r['ran'] >= 1), ('Distribution', 'markdown', 0, True))

    # ---- the editor's keys ----------------------------------------------------------------------------------------------------
    await page.ev(f'''(() => {{ const nb = {NB}; const c = nb.add('code'); c.editor.value = ''; c.focus(); }})()''')
    for text, key, mods in [('def f(x):', 'Enter', 0), ('if x:', 'Enter', 0), ('return 1', 'Enter', 0)]:
        await page.call('Input.insertText', {'text': text}, session=page.sid)
        await page.key(key, key, modifiers=mods)
    await page.call('Input.insertText', {'text': 'y = 2'}, session=page.sid)
    v = await page.ev(f'{NB}.cells[{NB}.cells.length - 1].editor.value')
    check('Enter keeps the indent, one level more after a colon, one less after return', v, 'def f(x):\n    if x:\n        return 1\n    y = 2')
    await page.ev(f'''(() => {{ const ta = {NB}.cells[{NB}.cells.length - 1].editor.ta; ta.setSelectionRange(0, ta.value.length); }})()''')
    await page.key('Tab', 'Tab')
    v1 = await page.ev(f'{NB}.cells[{NB}.cells.length - 1].editor.value')
    await page.key('Tab', 'Tab', modifiers=SHIFT)
    v2 = await page.ev(f'{NB}.cells[{NB}.cells.length - 1].editor.value')
    await page.key('/', 'Slash', modifiers=CTRL)
    v3 = await page.ev(f'{NB}.cells[{NB}.cells.length - 1].editor.value')
    await page.key('/', 'Slash', modifiers=CTRL)
    v4 = await page.ev(f'{NB}.cells[{NB}.cells.length - 1].editor.value')
    check('Tab indents the selected lines, Shift+Tab takes it back', (v1.split('\n')[0], v2 == v), ('    def f(x):', True))
    check('Ctrl+/ comments the lines out at their common indent, and in again', (v3.split('\n')[:2], v4 == v), (['# def f(x):', '#     if x:'], True))
    await page.ev(f'''(() => {{ const ta = {NB}.cells[{NB}.cells.length - 1].editor.ta; ta.value = 'if 1:\\n        '; ta.dispatchEvent(new Event('input')); ta.setSelectionRange(ta.value.length, ta.value.length); }})()''')
    await page.key('Backspace', 'Backspace')
    v5 = await page.ev(f'{NB}.cells[{NB}.cells.length - 1].editor.value')
    await page.ev("document.execCommand('undo')")          # the browser's own Undo (a key sent by the test is not bound to it)
    v6 = await page.ev(f'{NB}.cells[{NB}.cells.length - 1].editor.value')
    check('Backspace in an indent goes back a level; Undo takes it back', (v5, v6), ('if 1:\n    ', 'if 1:\n        '))
    r = await page.ev(f'''(() => {{ const c = {NB}.cells[{NB}.cells.length - 1]; c.editor.value = 'import numpy as np  # np\\nx = f"a{{1}}" + 2.5e3'; return [...c.editor.hl.querySelectorAll('[class^="t-"]')].map(s => s.className + ':' + s.textContent); }})()''')
    check('the colours: keywords, comments, strings, numbers', r, ['t-k:import', 't-k:as', 't-c:# np', 't-s:f"a{1}"', 't-n:2.5e3'])

    # ---- closing with changes -----------------------------------------------------------------------------------------------------
    r = await page.ev(f'''(async () => {{ const nb = {NB}; nb.dirty = true; const tab = SM.app.tabs.find(t => t.notebook === nb);
      SM.app.closeTab(tab); await new Promise(r => setTimeout(r, 200));
      const dlg = [...document.querySelectorAll('.sm-dialog')].pop(); const asked = !!dlg && /not saved/.test(dlg.textContent);
      [...dlg.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Cancel').click(); await new Promise(r => setTimeout(r, 200));
      const still = SM.notebook.notebooks.includes(nb);
      SM.app.closeTab(tab); await new Promise(r => setTimeout(r, 200));
      [...[...document.querySelectorAll('.sm-dialog')].pop().querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => /Close without/.test(b.textContent)).click(); await new Promise(r => setTimeout(r, 200));
      return {{ asked, still, gone: !SM.notebook.notebooks.includes(nb) && !SM.app.tabs.includes(tab) }}; }})()''')
    check('closing a notebook with changes asks first; Cancel keeps it, Close without saving closes it', r, {'asked': True, 'still': True, 'gone': True})

    # ---- the editor inside a report's code block: its two layers alike (the code
    # block's own pre rule once gave the coloured layer another size and padding,
    # and a selection sat beside the text, the line numbers gone)
    r = await page.ev(LAYERS)
    check("a report's code in the editor: the coloured layer and the text under the cursor alike, the line numbers shown", r, {'diff': [], 'numbers': True, 'same': True})

    # ---- a date column: text in the CSV, the page's number in the code (user report
    # 2026-09-28: Graph Maker's smoother code on the Business cycle table failed on its quarter)
    r = await page.ev(DATES, timeout=400)
    check("a date column: Graph Maker's smoother code turns it back into the page's number and runs", (r['conv'], r['errors']), (True, []))
    check("... and gives the page's curve", r['first'] is not None and r['page'] is not None and abs(r['first'] - r['page']) <= 1e-9 * abs(r['page']), True)
    check("... a Bivariate graph's code (put together in the page) on a date X runs and draws", (r['conv2'], r['errors2'], r['fig2']), (True, [], True))
    check('no script errors', page.errors, [])
    await page.close()

    # ---- dark theme and phone width -------------------------------------------------------------------------------------------------
    page = await open_page(f'{BASE}/smui.html?example=students', width=400, height=820, dark=True)
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 820, 'deviceScaleFactor': 2, 'mobile': True}, session=page.sid)
    await wait_engine(page)
    r = await page.ev('''(async () => { const nb = SM.notebook.open(SM.app); const c = nb.cells[0]; c.editor.value = 'import math  # a long comment that runs on and on past the width of a phone, to wrap'; await nb.run(c);
      await new Promise(r => requestAnimationFrame(r));
      const k = c.editor.hl.querySelector('.t-k'); const ta = c.editor.ta, hl = c.editor.hl;
      return { font: getComputedStyle(ta).fontSize, kw: getComputedStyle(k).color, sameH: Math.abs(ta.getBoundingClientRect().height - hl.getBoundingClientRect().height) < 1,
        wraps: hl.querySelector('.ln').getBoundingClientRect().height > 30, over: document.documentElement.scrollWidth > innerWidth + 1 }; })()''', timeout=200)
    check('phone: the editor\'s text is 16px (no zoom on focus), long lines wrap in both layers alike', (r['font'], r['wraps'], r['sameH']), ('16px', True, True))
    check('phone: no side scrolling; dark theme: keywords in the dark palette', (r['over'], r['kw']), (False, 'rgb(213, 150, 240)'))
    check('phone: no script errors', page.errors, [])
    await page.close()
    sys.exit(check.done())


asyncio.run(main())
