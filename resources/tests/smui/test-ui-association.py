#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Screening > Association Analysis.

The simulated market-baskets example opens from the URL and File >
Examples, and the platform sits in Analyze > Screening; the launch dialog
has JMP's roles and options with JMP's defaults (one Item column without an
ID or a delimiter is refused); the Frequent Item Sets and the Rules are the
engine's, and their supports and confidences are the ones counted here in
the page from the table; a real click on a rule or an item set selects the
rows of the transactions that hold it; a click on a heading sorts; Make
into Data Table makes the table; the bubble plot has a bubble per rule at
its confidence and lift, a real click on one selects its rows and rows
selected in the table mark the rules; every red triangle opens; the
Transaction Listing and FP-growth; the same results from several Item
columns and from delimited items; By Store; a project keeps the options
with the column ids remapped; hostile items stay text; Bootstrap reruns
the report headless; the bubble plot's matplotlib code runs in the page and
draws its bubbles; every (i) has a topic and the launch dialog's (i) gives
every role and option its help; the report draws in the dark theme and at
phone width without a sideways page scroll, and without script errors.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-association.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine
from test_charts import GRAPHS_JS, maxdiff, points_of, run_graph

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def pct(s):
    return float(s.replace('%', '')) / 100


# The baskets counted in the page from the table itself: each basket's products,
# and a set's support and rows (every row of every basket that holds the set).
COUNT = r'''
((sets) => {
  const t = SM.app.tables.find(t => t.name === 'Market baskets');
  const ids = t.col('Basket ID').values, prod = t.col('Product').values;
  const baskets = new Map();
  ids.forEach((b, i) => { if (!baskets.has(b)) baskets.set(b, { items: new Set(), rows: [] }); baskets.get(b).items.add(prod[i]); baskets.get(b).rows.push(i); });
  const out = {};
  for (const s of sets) {
    let n = 0; const rows = [];
    for (const b of baskets.values()) if (s.every(x => b.items.has(x))) { n++; rows.push(...b.rows); }
    out[s.join('|')] = { n, support: n / baskets.size, rows: rows.sort((a, b) => a - b) };
  }
  return { baskets: baskets.size, out };
})
'''

# A row of a report table (by its first cells), its centre on the screen.
ROW_AT = r'''
((outline, cells) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h2, h3, h4').textContent.trim() === outline);
  const tbl = head.parentElement.querySelector(':scope > .sm-ob-body table.sm-rt');
  const tr = [...tbl.tBodies[0].rows].find(tr => cells.every((c, k) => tr.cells[k].textContent === c));
  if (!tr) return null;
  tr.scrollIntoView({ block: 'center' });
  const b = tr.cells[0].getBoundingClientRect();
  return { x: b.left + Math.min(20, b.width / 2), y: b.top + b.height / 2 };
})
'''

TRIANGLES = '''
(async () => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  let items = 0;
  const errors = [];
  const btns = [...rep.body.querySelectorAll('.sm-ob-menu')];
  for (const btn of btns) {
    try {
      btn.click();
      await new Promise(r => setTimeout(r, 30));
      const menus = [...document.querySelectorAll('.sm-menu')];
      const top = menus[menus.length - 1];
      if (!top) { errors.push('no menu'); continue; }
      const bs = [...top.querySelectorAll('button')];
      items += bs.length;
      for (const b of bs.filter(x => x.classList.contains('sm-sub'))) { b.click(); await new Promise(r => setTimeout(r, 30)); }
    } catch (e) { errors.push(String(e)); }
    SM.ui.closeMenus(0);
  }
  return { triangles: btns.length, items, errors };
})()
'''

PICK = '''
(async (title, path) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => { const t = h.querySelector('h2, h3, h4'); return title === '*top*' ? t.tagName === 'H2' : t.textContent.trim() === title; });
  head.querySelector('.sm-ob-menu').click();
  await new Promise(r => setTimeout(r, 60));
  const done = new Promise(res => rep.on('done', res));
  for (const label of path) {
    const menus = [...document.querySelectorAll('.sm-menu')];
    const b = [...menus[menus.length - 1].querySelectorAll('button')].find(x => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === label);
    if (!b) throw new Error('no item ' + label);
    b.click();
    await new Promise(r => setTimeout(r, 80));
  }
  await done;
  return [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
})
'''


def pick_js(title, path):
    return f'({PICK})({json.dumps(title)}, {json.dumps(path)})'


STATE = '''
(() => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  return { title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
           errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 400)),
           warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)), options: rep.spec.options, roles: rep.spec.roles };
})()
'''

ENGINE = '''(async (payload) => { const t = SM.app.tables.find(t => t.name === 'Market baskets');
  return await SM.engine.call('association.fit', { table: t.id, rows: null, ...payload }, t); })'''


def engine_js(payload):
    return f'({ENGINE})({json.dumps(payload)})'


async def main():
    page = await open_page(f'{BASE}/smui.html?example=market-baskets', height=1300)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "association").map(f => f.module + ": " + f.error)')
    check('association.py imports in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const file = SM.app.menuItems('File');
      const exs = file.find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const an = SM.app.menuItems('Analyze');
      const scr = an.find(i => i.label === 'Screening');
      const sub = scr ? (typeof scr.submenu === 'function' ? scr.submenu() : scr.submenu).filter(i => !i.separator).map(i => i.label) : [];
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), about: SM.io.EXAMPLES['market-baskets'].about, inFile: labels.includes(SM.io.EXAMPLES['market-baskets'].label), sub };
    })()''')
    check('?example=market-baskets opens the simulated baskets, stacked', (ex['name'], ex['cols']), ('Market baskets', ['Basket ID', 'Store', 'Product', 'Quantity']))
    check('it is simulated, in File > Examples', (ex['about'].startswith('Simulated'), ex['inFile']), (True, True))
    check('Analyze > Screening lists Association Analysis', 'Association Analysis…' in ex['sub'] or 'Association Analysis' in ex['sub'], True)

    # ---- the launch dialog, by clicks
    r = await page.ev('''(async () => {
      SM.app.launch('association');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); items.find(x => x.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      const opts = [...dlg.querySelectorAll('.sm-launch-opts label')].map(l => [[...l.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim(), (l.querySelector('select') || l.querySelector('input')).value]);
      ok.click();
      const needOne = dlg.querySelector('.sm-launch-msg').textContent;
      pick('Product'); role('Item').querySelector('.sm-btn').click();
      ok.click();
      const stacked = dlg.querySelector('.sm-launch-msg').textContent;
      pick('Basket ID'); role('ID').querySelector('.sm-btn').click();
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { roles, opts, needOne, stacked, title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent) };
    })()''', timeout=600)
    check('the launch roles are JMP\'s: Item, ID, Freq, By', r['roles'], ['Item', 'ID', 'Freq', 'By'])
    check('the options with JMP\'s defaults', r['opts'], [['Minimum Support', '0.1'], ['Minimum Confidence', '0.4'], ['Minimum Lift', '1.2'], ['Maximum Antecedents', '3'], ['Maximum Rule Size', '4'],
                                                        ['Multiple Response Delimiter', ''], ['Algorithm', 'apriori']])
    check('an Item column is needed', 'Item' in r['needOne'], True)
    check('one Item column without an ID or a delimiter is refused, saying what to do', 'give an ID' in r['stacked'], True)
    check('the report and its outlines (Frequent Item Sets first, closed as in JMP)', (r['title'], r['outlines']), ('Association Analysis', ['Association Analysis', 'Frequent Item Sets', 'Rules', 'Rule Bubble Plot']))
    st = await page.ev(STATE)
    check('no errors in the report', (st['errors'], st['warnings']), ([], []))
    await shot(page, 'assoc-01-report.png')

    # ---- the numbers: the engine's, and counts made here in the page
    eng = await page.ev(engine_js({'items': ['Product'], 'id_col': 'Basket ID'}))
    rules = await page.ev(table_under_js('Rules', 0))
    check('the Rules\' columns', rules[0], ['Condition', 'Consequent', 'Confidence', 'Lift', 'Support', 'Conviction', 'Leverage', 'FDR p'])
    check('the Rules are the engine\'s, the highest confidence first', [row[:2] for row in rules[1:]], [[x['condition'], x['consequent']] for x in eng['rules']][:1000])
    conf = [pct(row[2]) for row in rules[1:]]
    check('... sorted by confidence', conf == sorted(conf, reverse=True), True)
    sets = [x['condition'].split(', ') + x['consequent'].split(', ') for x in eng['rules'][:6]] + [x['condition'].split(', ') for x in eng['rules'][:6]] + [['bread'], ['bread', 'butter']]
    here = await page.ev(f'({COUNT})({json.dumps(sets)})')
    check('1,200 baskets, as counted here', (here['baskets'], eng['n_transactions']), (1200, 1200))
    k6 = eng['rules'][:6]
    check.near('the first six rules\' support = the share of baskets with all their items, counted here',
               maxdiff([x['support'] for x in k6], [here['out']['|'.join(x['condition'].split(', ') + x['consequent'].split(', '))]['support'] for x in k6]), 0, 1e-12)
    check.near('... and their confidence = that over the baskets with the condition',
               maxdiff([x['confidence'] for x in k6], [here['out']['|'.join(x['condition'].split(', ') + x['consequent'].split(', '))]['n'] / here['out']['|'.join(x['condition'].split(', '))]['n'] for x in k6]), 0, 1e-12)
    bb = {x['set']: x for x in eng['item_sets']}
    check.near('the support of {bread, butter}, counted here', bb['{bread, butter}']['support'], here['out']['bread|butter']['support'], 1e-12)
    check('the planted rules are found: buns ⇒ burgers, salsa ⇒ tortilla chips, pasta ⇒ tomato sauce', all((a, b) in {(x['condition'], x['consequent']) for x in eng['rules']} for a, b in (('buns', 'burgers'), ('salsa', 'tortilla chips'), ('pasta', 'tomato sauce'))), True)

    # ---- a real click on a rule selects the rows of its baskets
    first = eng['rules'][0]
    at = await page.ev(f'({ROW_AT})("Rules", {json.dumps([first["condition"], first["consequent"]])})')
    await page.click(at['x'], at['y'])
    await asyncio.sleep(0.3)
    sel = await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()')
    check('a click on a rule selects every row of the baskets that hold all its items', sel, here['out']['|'.join(first['condition'].split(', ') + first['consequent'].split(', '))]['rows'])
    # the bubbles of the selected rows' rules are marked
    marked = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => /^Rules: confidence/.test(p.opts.title)); return p && p.box.data ? (p.box.data[0].selectedpoints || []) : null; })()''')
    check('rows selected elsewhere mark the rules whose baskets hold them (the rule clicked among them)', isinstance(marked, list) and 0 in marked, True)
    # the Frequent Item Sets: open the outline, click {bread, butter}
    await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Frequent Item Sets'); h.querySelector('.sm-ob-toggle').click(); })()''')
    await asyncio.sleep(0.3)
    fis = await page.ev(table_under_js('Frequent Item Sets', 0))
    check('the Frequent Item Sets: Item Set, Support, N Items, the engine\'s, the highest support first', (fis[0], [row[0] for row in fis[1:]]), (['Item Set', 'Support', 'N Items'], [x['set'] for x in eng['item_sets']]))
    at = await page.ev(f'({ROW_AT})("Frequent Item Sets", ["{{bread, butter}}"])')
    await page.click(at['x'], at['y'])
    await asyncio.sleep(0.3)
    sel = await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()')
    check('a click on an item set selects the rows of its baskets', sel, here['out']['bread|butter']['rows'])
    # a real click on the Lift heading sorts the rules
    hd = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Rules');
      const th = [...h.parentElement.querySelectorAll('table.sm-rt thead th')].find(th => th.textContent === 'Lift'); th.scrollIntoView({ block: 'center' }); const b = th.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; })()''')
    await page.click(hd['x'], hd['y'])
    await asyncio.sleep(0.2)
    await page.click(hd['x'], hd['y'])
    await asyncio.sleep(0.2)
    rs = await page.ev(table_under_js('Rules', 0))
    lifts = [float(row[3]) for row in rs[1:]]
    check('two clicks on the Lift heading sort the rules by lift, highest first', lifts == sorted(lifts, reverse=True), True)
    # Make into Data Table
    made = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const n = SM.app.tables.length;
      const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Rules');
      const tbl = h.parentElement.querySelector('table.sm-rt');
      tbl.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, clientX: 300, clientY: 300 }));
      await new Promise(r => setTimeout(r, 60));
      const m = [...document.querySelectorAll('.sm-menu')].pop();
      [...m.querySelectorAll('button')].find(b => b.textContent.includes('Make into Data Table')).click();
      await new Promise(r => setTimeout(r, 300));
      const t = SM.app.tables[SM.app.tables.length - 1];
      const out = { made: SM.app.tables.length === n + 1, name: t.name, cols: t.columns.map(c => c.name), n: t.nrows, conf: t.col('Confidence').values.slice(0, 3) };
      SM.app.showTab(SM.app.tabOf(rep));
      return out; })()''')
    check('Make into Data Table: a table of the rules, every column', (made['made'], made['name'], made['cols'], made['n']), (True, 'Rules', rules[0], len(eng['rules'])))
    await page.ev('SM.app.reports[SM.app.reports.length - 1].table.select([])')

    # ---- the bubble plot: a bubble per rule, a real click selects its rows
    bub = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => /^Rules: confidence/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' }); for (let i = 0; i < 60 && !p.drawn; i++) await new Promise(r => setTimeout(r, 100));
      await new Promise(r => setTimeout(r, 300));
      const gd = p.box, L = gd._fullLayout, tr = gd.data[0];
      const b = gd.getBoundingClientRect();
      const k = tr.x.map((x, i) => i).sort((a, c) => tr.marker.size[c] - tr.marker.size[a])[0];
      return { x: tr.x, y: tr.y, sizes: tr.marker.size, at: { x: b.left + L._size.l + L.xaxis.l2p(tr.x[k]), y: b.top + L._size.t + L.yaxis.l2p(tr.y[k]) }, k, rows: p.rows[0][k] }; })()''')
    check.near('a bubble per rule at its confidence and lift', maxdiff([q for pt in zip(bub['x'], bub['y']) for q in pt], [q for x in eng['rules'] for q in (x['confidence'], x['lift'])]), 0, 1e-12)
    smax = max(x['support'] for x in eng['rules'])
    check.near('... its size following its support (28 px across for the largest)', maxdiff(bub['sizes'], [max(5, 28 * (x['support'] / smax) ** 0.5) for x in eng['rules']]), 0, 1e-9)
    await page.click(bub['at']['x'], bub['at']['y'])
    await asyncio.sleep(0.4)
    sel = await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()')
    kr = eng['rules'][bub['k']]
    check('a real click on the largest bubble selects the rows of the baskets that hold its rule', sel, here['out'].get('|'.join(kr['condition'].split(', ') + kr['consequent'].split(', ')), {}).get('rows', bub['rows']))
    await page.ev('SM.app.reports[SM.app.reports.length - 1].table.select([])')
    await shot(page, 'assoc-02-bubbles.png')

    # ---- red triangles, the Transaction Listing, FP-growth
    tri = await page.ev(TRIANGLES)
    check('every red triangle opens, with its submenus', (tri['errors'], tri['triangles'] >= 1, tri['items'] >= 5), ([], True, True))
    await page.ev(pick_js('*top*', ['Transaction Listing']))
    tl = await page.ev(table_under_js('Transaction Listing', 0))
    check('Transaction Listing: a line per basket, sorted by the ID (the first 1000 shown)', (tl[0], len(tl) - 2, [row[0] for row in tl[1:4]], tl[-1][0]), (['Basket ID', 'Items', 'N Items'], 1000, ['1', '2', '3'], '… 200 more rows (right click: Make into Data Table)'))
    await page.ev(pick_js('*top*', ['Algorithm', 'FP-growth']))
    fp = await page.ev(table_under_js('Rules', 0))
    st = await page.ev(STATE)
    check('Algorithm, FP-growth: the same rules as Apriori', (st['options'].get('algorithm'), sorted(map(tuple, fp[1:])) == sorted(map(tuple, rules[1:]))), ('fpgrowth', True))

    # ---- the same from several Item columns and from delimited items, made here from the stacked table
    fmts = await page.ev('''(async () => {
      const t = SM.app.tables.find(t => t.name === 'Market baskets');
      const ids = t.col('Basket ID').values, prod = t.col('Product').values;
      const by = new Map(); ids.forEach((b, i) => { if (!by.has(b)) by.set(b, []); by.get(b).push(prod[i]); });
      const baskets = [...by.values()];
      const width = Math.max(...baskets.map(b => b.length));
      const wide = new SM.Table({ name: 'Wide baskets', columns: Array.from({ length: width }, (_, k) => ({ name: 'Item ' + (k + 1), dataType: 'character', values: baskets.map(b => b[k] ?? null) })) });
      const del = new SM.Table({ name: 'Delimited baskets', columns: [{ name: 'Products', dataType: 'character', values: baskets.map(b => b.join(', ')) }] });
      SM.app.addTable(wide); SM.app.addTable(del);
      const run = async (t, roles, options) => { const rep = SM.app.openReport(SM.platforms.get('association'), { roles, options }, t); await new Promise(res => rep.on('done', res));
        const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Rules');
        return { rules: [...h.parentElement.querySelector('table.sm-rt').tBodies[0].rows].map(tr => [...tr.cells].map(c => c.textContent)), errors: rep.body.querySelectorAll('.sm-ob-error, .sm-ob-warn').length }; };
      const a = await run(wide, { item: wide.columns.map(c => c.id) }, {});
      const b = await run(del, { item: [del.col('Products').id] }, { delimiter: ',' });
      return { a, b };
    })()''', timeout=600)
    check('several Item columns (a row a basket) give the stacked table\'s rules', (fmts['a']['errors'], fmts['a']['rules'] == [list(x) for x in rules[1:]]), (0, True))
    check('items between a delimiter (Multiple Response) give them too', (fmts['b']['errors'], fmts['b']['rules'] == [list(x) for x in rules[1:]]), (0, True))

    # ---- By Store
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Market baskets").id)')
    rep = await page.ev(open_report_js('association', {'item': ['Product'], 'id': ['Basket ID'], 'by': ['Store']}, {}), timeout=600)
    check('By Store: one analysis per store', [o for o in rep['outlines'] if o.startswith('Association Analysis')], ['Association Analysis Store=North', 'Association Analysis Store=South'])
    wn = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1];
      return [...rep.body.querySelectorAll('.sm-ob')].filter(o => /^Association Analysis Store=/.test(o.querySelector('.sm-ob-head').textContent.trim())).map(o =>
        [...o.querySelectorAll('table.sm-rt')].filter(t => t.dataset.rtKey === 'rules').map(t => [...t.tBodies[0].rows].map(tr => tr.cells[0].textContent + ' ⇒ ' + tr.cells[1].textContent)).flat()); })()''')
    check('the North store alone has wine ⇒ cheese', (any(r == 'wine ⇒ cheese' for r in wn[0]), any(r == 'wine ⇒ cheese' for r in wn[1])), (True, False))
    check('no errors in the By report', (await page.ev(STATE))['errors'], [])

    # ---- a project keeps the options, the column ids remapped
    await page.ev(open_report_js('association', {'item': ['Product'], 'id': ['Basket ID']}, {'minSupport': 0.08, 'minLift': 1.5, 'listing': True}), timeout=600)
    pj = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const heads = (r) => [...r.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
      const rt = (r) => { const h = [...r.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Rules'); return [...h.parentElement.querySelector('table.sm-rt').tBodies[0].rows].map(tr => tr.textContent); };
      const out = { newTable: back.table !== t, newId: back.spec.roles.item[0] !== rep.spec.roles.item[0], opts: [back.spec.options.minSupport, back.spec.options.minLift, back.spec.options.listing],
                    same: JSON.stringify(heads(back)) === JSON.stringify(heads(rep)) && JSON.stringify(rt(back)) === JSON.stringify(rt(rep)), errors: back.body.querySelectorAll('.sm-ob-error').length };
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })()''', timeout=900)
    check('a project: its own table with new column ids, the options kept, the same report', (pj['newTable'], pj['newId'], pj['opts'], pj['same'], pj['errors']), (True, True, [0.08, 1.5, True], True, 0))

    # ---- hostile items stay text
    hz = await page.ev(r'''(async () => {
      window.__pwned = 0;
      const items = ['<img src=x onerror="window.__pwned=1">', '<b>bold</b>', '%{x}', 'plain'];
      const ids = [], vals = [];
      for (let b = 0; b < 40; b++) for (const it of items) if (b % 4 !== items.indexOf(it)) { ids.push(b); vals.push(it); }
      SM.app.addTable(new SM.Table({ name: 'Hostile', columns: [{ name: 'id', dataType: 'numeric', modelingType: 'nominal', values: ids }, { name: 'item', dataType: 'character', values: vals }] }));
      const t = SM.app.tables[SM.app.tables.length - 1];
      const rep = SM.app.openReport(SM.platforms.get('association'), { roles: { item: [t.col('item').id], id: [t.col('id').id] }, options: { minLift: 0, listing: true } }, t);
      await new Promise(res => rep.on('done', res));
      const p = rep.plots.find(p => /^Rules: confidence/.test(p.opts.title));
      return { injected: rep.body.querySelectorAll('img, b, script').length, pwned: window.__pwned, cells: [...rep.body.querySelectorAll('table.sm-rt td')].map(td => td.textContent),
               hover: p ? p.traces[0].hovertext : [], errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent) };
    })()''', timeout=600)
    check('hostile items: no element made from them, nothing run', (hz['injected'], hz['pwned'], hz['errors']), (0, 0, []))
    check('... they show as typed in the tables', all(any(x in c for c in hz['cells']) for x in ('<b>bold</b>', '%{x}', '<img src=x')), True)
    check('... and Plotly gets them escaped', (any('&lt;b&gt;bold&lt;/b&gt;' in h for h in hz['hover']), any('<b>bold' in h for h in hz['hover'])), (True, False))
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Market baskets").id)')

    # ---- Bootstrap reruns the report headless
    await page.ev(open_report_js('association', {'item': ['Product'], 'id': ['Basket ID']}, {}), timeout=600)
    b = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const tbl = [...rep.body.querySelectorAll('table.sm-rt')].find(t => t._rt && t._rt.columns.some(c => c.label === 'Lift'));
      const col = tbl._rt.columns.find(c => c.label === 'Lift');
      const n0 = rep.plots.length;
      const out = await SM.bootstrap.run(tbl, col, { B: 4, seed: 3, show: false });
      return { rows: out ? out.nrows : null, notes: out ? out.notes : '', plots: rep.plots.length === n0, errors: rep.body.querySelectorAll('.sm-ob-error').length };
    })()''', timeout=900)
    check('Bootstrap of a rule\'s lift: 4 samples of the baskets\' rows, the report untouched', (b['rows'] is not None and b['rows'] >= 1, b['plots'], b['errors']), (True, True, 0))

    # ---- the bubble plot's matplotlib code, run in the page
    await page.ev(GRAPHS_JS)
    g = await page.ev('(async () => (await __gr.graphs(SM.app.reports[SM.app.reports.length - 1])).filter(g => /^Rules: confidence/.test(g.label)))()')
    if check('the bubble plot has its code right under it, ending in plt.show()', len(g) == 1 and bool(g[0]['code']) and g[0]['code'].rstrip().split('\n')[-1] == 'plt.show()', True):
        F, err = await run_graph(page, g[0], "SM.app.tables.find((x) => x.name === 'Market baskets')")
        check('... it runs in the page', err, None)
        if F:
            ax = F[0]['axes'][0]
            check.near('... and draws a bubble per rule at its confidence and lift', maxdiff([q for p in ax['scatter'][0]['xy'] for q in p], [q for p in points_of(g[0]['traces'][0]) for q in p]), 0, 1e-9)
            check('... with the page\'s titles and size', (ax['xlabel'], ax['ylabel'], ax['title'], F[0]['size']), ('Confidence', 'Lift', 'Rules: confidence, lift and support', [5.2, 4.0]))

    # ---- the (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-association"); const row = document.getElementById("help-p-association"); return row ? row.textContent : null; })()')
    check('the platform has its line in Help', bool(helps) and 'Apriori' in helps, True)
    d = await page.ev('''(async () => {
      SM.app.launch('association');
      await new Promise(r => setTimeout(r, 300));
      const dlg = [...document.querySelectorAll('.sm-dialog')].pop();
      dlg.querySelector('.sm-dialog-head .info-btn').click();
      await new Promise(r => setTimeout(r, 200));
      const p = document.querySelector('.info-panel');
      const secs = {}; let cur = '';
      for (const n of p.querySelector('.info-panel-body').children) {
        if (n.tagName === 'H3') cur = n.textContent;
        else if (n.tagName === 'DL') (secs[cur] = secs[cur] || []).push(...[...n.querySelectorAll(':scope > dt')].map(dt => [dt.textContent, dt.nextElementSibling ? dt.nextElementSibling.textContent : '']));
      }
      const noTopic = KvotInfo.audit().noTopic;
      KvotInfo.close();
      dlg.querySelector('.sm-dialog-x').click();
      const L = SM.platforms.get('association').launch;
      return { secs, noTopic, roles: L.roles.map(r => [r.label, r.help]), options: L.options.map(o => [o.label, o.help]) };
    })()''')
    roles = dict(d['secs'].get('Roles', []))
    opts = dict(d['secs'].get('Options', []))
    check('the launch dialog\'s (i): every role with its help', [(lab, roles.get(lab, '').startswith(h)) for lab, h in d['roles']], [(lab, True) for lab, _ in d['roles']])
    check('... every option with its help', [(lab, opts.get(lab) == h) for lab, h in d['options']], [(lab, True) for lab, _ in d['options']])
    check('... and every (i) has a topic while it is open', d['noTopic'], [])

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports[SM.app.reports.length - 1]))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2.5)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => r.platform.id === 'association'); return rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)); })()''')
    check('the dark theme redraws the reports without errors', st, [])
    await shot(page, 'assoc-03-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')
    await asyncio.sleep(1.0)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => /^Rules: confidence/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' }); for (let i = 0; i < 60 && !p.drawn; i++) await new Promise(r => setTimeout(r, 100));
      const body = rep.body.getBoundingClientRect();
      const boxes = [...rep.body.querySelectorAll('.sm-as-scroll')].map(l => l.getBoundingClientRect().right);
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plot: p.box.getBoundingClientRect().right <= body.right + 1, drawn: p.drawn, tables: boxes.every(x => x <= body.right + 1), n: boxes.length,
               body: rep.body.scrollWidth <= rep.body.clientWidth + 1 };
    })()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the bubble plot and the tables fit the phone\'s width', (r['plot'], r['drawn'], r['tables'], r['n'] >= 1, r['body']), (True, True, True, True, True))
    await shot(page, 'assoc-04-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
