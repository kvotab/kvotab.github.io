#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Consumer Research > Uplift.

The simulated Offer example opens from the URL and File > Examples, and
Uplift is in Analyze > Consumer Research; the launch dialog has JMP's roles
(Y, Treatment, X, Weight, Freq, Validation, By) and options (Minimum Size
Split empty for JMP's default), and the Treatment role takes only a nominal
or ordinal column; the report starts with the root; Split (a real mouse
click), Shift-Split, Prune and Go grow and cut the tree; the node boxes'
rates, counts and Trt Diff are the ones worked out here from the table, and
the engine's on the same rows; a click on a node selects its rows and shows
its Candidates; a node's red triangle splits it by a column chosen in a form
and prunes below it; every red triangle opens, and the Leaf Report, Uplift
Graph, Split History, Column Uplift Contributions, the Qini curve and the
Decision Threshold draw; Save Difference, Save Predicteds, Save Leaf Numbers
and Labels write the engine's values, and Save Difference Formula and Save
Prediction Formula make live formula columns with the same values on every
row, worked out again when a cell changes; Treatment Level and Response
Level change the groups; every graph's code block runs in the page's Python
and draws the graph above it; By keeps each group's own splits; Redo and a
project keep the splits; every (i) has a topic and the launch dialog's (i)
gives every role and option its help; the report draws in the dark theme
and at phone width, where the tree scrolls in its own box.

    python3 resources/tests/smui/test-ui-uplift.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import importlib.util
import json
import math
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine
from test_charts import GRAPHS_JS, close, find_line, maxdiff

# the predictive platforms' chart helpers (test-ui-partition.py has them: PM_JS, chart_blocks, check_*)
_spec = importlib.util.spec_from_file_location('ui_partition_charts', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test-ui-partition.py'))
UP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(UP)

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
XS = ['age', 'member', 'visits last quarter', 'region', 'email opt-in']
REP = 'SM.app.reports[SM.app.reports.length - 1]'
ROLES = {'y': ['bought'], 'treatment': ['offer'], 'x': XS, 'validation': ['validation']}


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


STATE = '''
(() => {
  const rep = %s;
  return { title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
           errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 400)),
           warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)), options: rep.spec.options,
           nodes: rep.body.querySelectorAll('.sm-upl-node').length };
})()
''' % REP

# the node boxes: path, label, and their texts
NODES = '''
(() => {
  const rep = %s;
  return [...rep.body.querySelectorAll('.sm-upl-node')].map(g => {
    const t = [...g.querySelectorAll('text')].map(x => x.textContent);
    const after = (k) => { const i = t.indexOf(k); return i >= 0 ? t[i + 1] : null; };
    const h = t.indexOf('Treatment');
    return { path: g.dataset.path, label: g.querySelector('title').textContent.replace(/ \\(leaf \\d+\\)$/, ''), diff: after('Trt Diff'), t: after('t Ratio'), logworth: after('LogWorth'),
             groups: h >= 0 ? [t.slice(h + 3, h + 6), t.slice(h + 6, h + 9)] : [] };
  });
})()
''' % REP

BUTTON = '''
(async (label, shift) => {
  const rep = %s;
  const b = [...rep.body.querySelectorAll('.sm-part-buttons button')].find(x => x.textContent === label);
  if (!b) return 'no button ' + label;
  if (b.disabled) return 'disabled';
  const d = new Promise(res => rep.on('done', res));
  b.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: !!shift }));
  await d;
  return rep.body.querySelectorAll('.sm-upl-node').length;
})
''' % REP


def button_js(label, shift=False):
    return f'({BUTTON})({json.dumps(label)}, {json.dumps(shift)})'


# the payload the report sends, built here from its spec
PAYLOAD = '''
((rep) => {
  const t = rep.table, o = rep.spec.options, n = (k) => (rep.spec.roles[k] || []).map(id => t.col(id).name);
  const steps = (o.steps || []).map(s => (s.col ? { ...s, col: t.col(s.col).name } : s));
  return { table: t.id, rows: null, y: n('y')[0], treatment: n('treatment')[0], x: n('x'), weight: n('weight')[0] || null, freq: n('freq')[0] || null, validation: n('validation')[0] || null,
           portion: Number(o.portion || 0), seed: o.seed !== '' && o.seed != null ? Number(o.seed) : o.seedDrawn, missing: o.missing === false ? 'drop' : 'informative',
           minsize: o.minsize || null, ordinal_order: o.ordinalOrder !== false, steps, treat_level: o.treatLevel || null, response_level: o.responseLevel || null, group: null };
})
'''


async def engine(page, fn='uplift.fit', extra=None):
    return await page.ev(f'(async () => {{ const rep = {REP}; const p = ({PAYLOAD})(rep); Object.assign(p, {json.dumps(extra or {})}); return await SM.engine.call({json.dumps(fn)}, p, rep.table); }})()', timeout=300)


async def rerun(page):
    await page.ev(f'(async () => {{ const rep = {REP}; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; }})()', timeout=300)


# ---- the graphs: each block run in the page, its figure against the graph ----------------------------------------
def check_model(lab, g, F):
    """The uplift model's graph: each group's mean (or rate) across its part of each leaf, the rows, the leaves'
    edges and numbers, the treatment and the control in the legend."""
    ax = F['axes'][0]
    lines = [t for t in g['traces'] if t.get('mode') == 'lines']
    want = []
    for t in lines:
        seg = []
        for a, b in zip(t['x'], t['y']):
            if a is None:
                if seg:
                    want.append(tuple(round(v, 9) for p in seg for v in p))
                seg = []
            else:
                seg.append((a, b))
    got = [tuple(round(v, 9) for p in zip(ln['x'], ln['y']) for v in p) for ln in ax['lines'] if ln['ls'] == '-' and len(ln['x']) == 2]
    check(f'{lab}: each group\'s mean (or rate) across its part of each leaf', sorted(got), sorted(want))
    edges = sorted(s['x0'] for s in g['shapes'])
    check(f'{lab}: the leaves\' edges', sorted(ln['x'][0] for ln in ax['lines'] if ln['ls'] == ':'), edges)
    pts = [t for t in g['traces'] if 'markers' in (t.get('mode') or '')]
    bars = [t for t in g['traces'] if t.get('type') == 'bar' and t.get('width')]   # the parts' bars (not the page's selection overlays)
    if pts and not bars:
        want_pts = sorted((round(a, 9), round(b, 9)) for t in pts for a, b in zip(t['x'], t['y']))
        check(f'{lab}: every training row, evenly across its part', sorted((round(a, 9), round(b, 9)) for a, b in UP.scatter_pts(ax)), want_pts)
    if bars:
        wb = sorted((round(c - w_ / 2, 9), round(h, 9)) for t in bars for c, h, w_ in zip(t['x'], t['y'], t['width']))
        check(f'{lab}: each part\'s rate as a bar', sorted((round(b['x'], 9), round(b['h'], 9)) for b in ax['bars']), wb)
        if pts:
            check(f'{lab}: as many rows as the page\'s', len(UP.scatter_pts(ax)), sum(len(t['x']) for t in pts))
    tick = g['axes']['x']
    if tick and tick['tickvals']:
        check.near(f'{lab}: the leaf numbers at the leaves\' centres', maxdiff(ax['xticks'], tick['tickvals']), 0, 1e-12)
    check(f'{lab}: the treatment and the control in the legend', F['legend'][:2], [t['name'] for t in g['traces'] if t.get('showlegend') is not False][:2])
    UP.check_titles(check, lab, g, F)


def check_uplift_tree(lab, s, F):
    """The uplift tree's SVG against the figure: its size and title, a box per node, the groups' colour marks,
    every text in its place, the lines from each split to its children."""
    ax = F['axes'][0]
    check(f'{lab}: the size of the page\'s tree (and a line for the title)', F['size'], [s['w'] / 100, (s['h'] + 30) / 100])
    check(f'{lab}: the title', ax['title'], s['label'])

    def key(r):
        return (round(r['x'], 3), round(r['y'], 3), round(r['w'], 3), round(r['h'], 3))
    check(f'{lab}: a box per node, where the page draws them', sorted(key(b) for b in ax['bars'] if b['fc'] == '#fcf7f2ff'), sorted(key(r) for r in s['rects'] if 'sm-part-box' in r['cls'].split()))
    check(f'{lab}: the groups\' colour marks', sorted(key(b) for b in ax['bars'] if b['w'] == 3), sorted(key(r) for r in s['rects'] if 'sm-upl-swatch' in r['cls'].split()))
    tx = sorted((t['s'], round(t['x'], 2), round(t['y'], 2)) for t in ax['texts'])
    check(f'{lab}: every text of the boxes, in its place', tx, sorted((t['s'], round(t['x'], 2), round(t['y'], 2)) for t in s['texts']))
    segs = []
    for d in s['paths']:
        v = [float(q) for q in d.replace('M', ' ').replace('V', ' ').replace('H', ' ').split()]
        x0, y0, ym, x1, y1 = v
        segs.append(((x0, y0), (x0, ym), (x1, ym), (x1, y1)))
    got = sorted(tuple((round(a, 6), round(b, 6)) for a, b in zip(ln['x'], ln['y'])) for ln in ax['lines'])
    check(f'{lab}: the lines from each split to its children', got, sorted(tuple((round(a, 6), round(b, 6)) for a, b in sg) for sg in segs))


def check_bars(lab, g, F):
    """The Uplift Graph: each leaf's bar (its left edge, width and height), the validation lines, the leaf numbers."""
    ax = F['axes'][0]
    bar = [t for t in g['traces'] if t.get('type') == 'bar'][0]
    want = sorted((round(c - w_ / 2, 9), round(w_, 9), round(h, 9)) for c, h, w_ in zip(bar['x'], bar['y'], bar['width']))
    check(f'{lab}: each leaf\'s uplift, as wide as its share of the rows', sorted((round(b['x'], 9), round(b['w'], 9), round(b['h'], 9)) for b in ax['bars']), want)
    vl = [t for t in g['traces'] if t.get('mode') == 'lines']
    if vl:
        segs = []
        cur = []
        for a, b in zip(vl[0]['x'], vl[0]['y']):
            if a is None:
                if cur:
                    segs.append(tuple(round(v, 9) for p in cur for v in p))
                cur = []
            else:
                cur.append((a, b))
        got = sorted(tuple(round(v, 9) for p in zip(ln['x'], ln['y']) for v in p) for ln in ax['lines'] if (ln['color'] or '').startswith('#1c1c1c'))
        check(f'{lab}: each leaf\'s validation uplift across its bar', got, sorted(segs))
    check(f'{lab}: the leaves\' numbers under their bars', [t for t in ax['xticklabels'] if t], g['axes']['x']['ticktext'])
    UP.check_titles(check, lab, g, F)


def uplift_compare(lab, g, F):
    t = g['label']
    if 'rects' in g:
        check_uplift_tree(lab, g, F)
    elif t.startswith('Uplift model of'):
        check_model(lab, g, F)
    elif t == 'Uplift graph':
        check_bars(lab, g, F)
    elif t in ('Split history', 'AICc by number of splits', 'Qini curve'):
        UP.check_lines(check, lab, g, F)
        if t == 'Qini curve':
            check(f'{lab}: the legend, each set with its Qini coefficient', F['axes'][0]['legend'], [q['name'] for q in g['traces'] if q.get('showlegend') is not False])
    elif t == 'Column Uplift Contributions':
        bar = [q for q in g['traces'] if q.get('type') == 'bar'][0]
        ax = F['axes'][0]
        check(f'{lab}: a bar per column, in the page\'s order', [x for x in ax['yticklabels'] if x], bar['y'])
        check.near(f'{lab}: the portions', maxdiff([b['w'] for b in ax['bars']], [v if v is not None else 0.0 for v in bar['x']]), 0, 1e-12)
    elif t.startswith('Probabilities') or 'threshold' in t.lower() or t.startswith('Fitted') or t.startswith('Metric'):
        pass   # the Decision Threshold's graphs: smui-predict.js's (test-ui-screening.py checks them)
    else:
        check(f'{lab}: a graph this test knows', t, None)


async def charts(page):
    await page.ev(GRAPHS_JS)
    await page.ev(UP.PM_JS)
    await page.ev('__gr.idle()')
    tbl = "SM.app.tables.find((t) => t.name === 'Offer')"
    await page.ev(f'{tbl}.select([])')   # no row selected: a selection draws its share over the bars
    every = {'leafReport': True, 'upliftGraph': True, 'history': True, 'contrib': True, 'qini': True}
    specs = [
        ('bought, Go on the validation column', ROLES, {**every, 'steps': [{'op': 'split', 'n': 2}, {'op': 'go'}]}),
        ('bought, the points and the Show Split options off', ROLES, {**every, 'showPoints': False, 'splitStats': False, 'splitCount': False, 'steps': [{'op': 'split', 'n': 3}]}),
        ('spend, a validation portion', {'y': ['spend (€)'], 'treatment': ['offer'], 'x': XS}, {**every, 'portion': 0.3, 'seed': '5', 'steps': [{'op': 'split', 'n': 3}]}),
    ]
    total = 0
    for label, roles, opts in specs:
        r = await page.ev(open_report_js('uplift', roles, opts), timeout=600)
        check(f'charts: {label}: no errors', r['errors'], [])
        n, _ = await UP.chart_blocks(page, check, label, tbl, REP, uplift_compare)
        total += n
        await page.ev(f'SM.app.closeReport({REP})')
    check('charts: the blocks ran and drew the page\'s graphs', total >= 18, True)


async def main():
    page = await open_page(f'{BASE}/smui.html?example=offer', height=1300)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    check('uplift.py imports in Pyodide', await page.ev('SM.engine.failed.filter(f => f.module === "uplift").map(f => f.error)'), [])
    check('no script errors at load', page.errors, [])

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const exs = SM.app.menuItems('File').find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const cr = SM.app.menuItems('Analyze').find(i => i.label === 'Consumer Research');
      const items = cr ? (typeof cr.submenu === 'function' ? cr.submenu() : cr.submenu).filter(i => !i.separator).map(i => i.label) : [];
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => [c.name, c.modelingType]), order: t.col('offer').valueOrder, about: SM.io.EXAMPLES.offer.about, inFile: labels.includes(SM.io.EXAMPLES.offer.label), items };
    })()''')
    check('?example=offer opens the simulated offer table', (ex['name'], ex['rows'], len(ex['cols'])), ('Offer', 4000, 10))
    check('... the offer\'s first level is the treatment', ex['order'][:1], ['Offer'])
    check('it is simulated, and its notes give the true uplifts', ex['about'].startswith('Simulated') and 'adds 22 points for members under 35' in ex['about'] and 'Region and email opt-in change nothing' in ex['about'], True)
    check('it is in File > Examples', ex['inFile'], True)
    check('Uplift is in Analyze > Consumer Research', 'Uplift…' in ex['items'], True)

    # ---- the launch dialog
    r = await page.ev('''(async (xs) => {
      SM.app.launch('uplift');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      const opts = [...dlg.querySelectorAll('.sm-launch-opts label')].map(l => { const i = l.querySelector('input, select'); return [[...l.childNodes].filter(x => x.nodeType === 3).map(x => x.textContent).join('').trim(), i.type === 'checkbox' ? i.checked : i.value]; });
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); items.find(x => x.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      pick('age'); role('Treatment').querySelector('.sm-btn').click();
      const refused = dlg.querySelector('.sm-launch-msg').textContent;
      const inTreat = role('Treatment').querySelectorAll('li').length;
      pick('bought'); role('Y, Response').querySelector('.sm-btn').click();
      ok.click();
      const needT = dlg.querySelector('.sm-launch-msg').textContent;
      pick('offer'); role('Treatment').querySelector('.sm-btn').click();
      for (const x of xs) { pick(x); role('X, Factor').querySelector('.sm-btn').click(); }
      pick('validation'); role('Validation').querySelector('.sm-btn').click();
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { roles, opts, refused, inTreat, needT, options: rep.spec.options, title: rep.title };
    })(%s)''' % json.dumps(XS), timeout=300)
    check('the launch dialog has JMP\'s roles', r['roles'], ['Y, Response', 'Treatment', 'X, Factor', 'Weight', 'Freq', 'Validation', 'By'])
    check('... and its options, Minimum Size Split empty for JMP\'s default', r['opts'], [['Validation Portion', '0'], ['Informative Missing', True], ['Random Seed', ''], ['Minimum Size Split', ''], ['Ordinal Restricts Order', True]])
    check('the Treatment role refuses a continuous column, and says why', (r['inTreat'], 'nominal or ordinal' in r['refused']), (0, True))
    check('a treatment is required', 'Treatment' in r['needT'], True)
    check('the report is Uplift Model for bought', r['title'], 'Uplift Model for bought')
    st = await page.ev(STATE)
    check('the report starts with the root alone, no errors', (st['nodes'], st['errors']), (1, []))
    check('... its outlines', st['outlines'], ['Uplift Model for bought', 'Candidates'])
    note = await page.ev(f'{REP}.body.querySelector(".sm-ob-note").textContent')
    check('the report says which level is the treatment and which the control', 'Treatment: offer = Offer; control: No offer' in note, True)
    check('scikit-learn is not loaded', await page.ev("SM.engine.versions['scikit-learn'] || null"), None)

    # ---- Split with a real mouse click
    pos = await page.ev(f'''(() => {{ const rep = {REP}; const b = [...rep.body.querySelectorAll('.sm-part-buttons button')].find(x => x.textContent === 'Split'); b.scrollIntoView({{ block: 'center' }}); const r = b.getBoundingClientRect(); return {{ x: r.left + r.width / 2, y: r.top + r.height / 2 }}; }})()''')
    done = page.ev(f'(async () => {{ const rep = {REP}; await new Promise(res => rep.on("done", res)); return rep.body.querySelectorAll(".sm-upl-node").length; }})()')
    await asyncio.sleep(0.2)
    await page.click(pos['x'], pos['y'])
    check('a mouse click on Split splits the root: three nodes', await done, 3)
    nodes = await page.ev(NODES)
    eng = await engine(page)
    by = {nd['path']: nd for nd in eng['nodes']}
    f4 = lambda v: f'{v:.4f}'.replace('-', '−')
    ok = [(nd['path'], nd['groups'][0][1] == f4(by[nd['path']]['means'][1]) and nd['groups'][1][1] == f4(by[nd['path']]['means'][0]) and nd['diff'] == f4(by[nd['path']]['diff'])
           and nd['groups'][0][2] == str(int(by[nd['path']]['counts'][1])) and nd['groups'][1][2] == str(int(by[nd['path']]['counts'][0]))) for nd in nodes]
    check('each node box: each group\'s rate and count and the Trt Diff, the engine\'s on the same rows', ok, [(nd['path'], True) for nd in nodes])
    own = await page.ev(f'''(() => {{
      const rep = {REP}; const t = rep.table;
      const v = t.col('validation').values, y = t.col('bought').values, off = t.col('offer').values;
      const tr = [...Array(t.nrows).keys()].filter(i => v[i] === 'Training');
      const g = (rows, lv) => {{ const r = rows.filter(i => off[i] === lv); return [r.filter(i => y[i] === 'Yes').length / r.length, r.length]; }};
      return {{ treat: g(tr, 'Offer'), control: g(tr, 'No offer') }};
    }})()''')
    root = next(nd for nd in nodes if nd['path'] == '')
    check('the root\'s rates and counts, worked out here from the table\'s training rows', (root['groups'][0][1:], root['groups'][1][1:]),
          ([f4(own['treat'][0]), str(own['treat'][1])], [f4(own['control'][0]), str(own['control'][1])]))
    check('... its Trt Diff the treatment\'s rate less the control\'s', root['diff'], f4(own['treat'][0] - own['control'][0]))
    check('the first split is by age, the column of the true uplifts', by['']['split']['column'], 'age')
    # Candidates of the root, and a click on a node
    cands = await page.ev(table_under_js('Candidates', 0))
    check('Candidates: each column\'s ChiSquare, LogWorth and Gamma, the best marked', (cands[0][:5], len(cands) - 1), (['', 'Term', 'ChiSquare', 'LogWorth', 'Gamma'], len(XS)))
    pos = await page.ev(f'''(() => {{ const g = {REP}.body.querySelector('.sm-upl-node[data-path="L"] .sm-part-box'); g.scrollIntoView({{ block: 'center' }}); const r = g.getBoundingClientRect(); return {{ x: r.left + r.width / 2, y: r.top + r.height / 2 }}; }})()''')
    await page.click(pos['x'], pos['y'])
    await asyncio.sleep(0.4)
    sel = await page.ev(f'''(() => {{ const rep = {REP}; const t = rep.table; let k = 0; for (let i = 0; i < t.nrows; i++) if (t.state[i] & 1) k++;
      const cap = [...rep.body.querySelectorAll('.sm-ob')].find(o => o.querySelector('h3') && o.querySelector('h3').textContent === 'Candidates').querySelector('caption').textContent;
      return {{ k, cap }}; }})()''')
    lnode = by['L']
    check('a click on a node selects its rows (every set) and shows its Candidates', (sel['k'], sel['cap'].startswith(lnode['label'])), (len([i for i, l in enumerate(eng['assign']['leaf']) if l <= by['L']['hi'] and l >= by['L']['lo']]), True))

    # ---- Shift-Split, Prune, Go
    r = await page.ev(UP.form_js(f"const rep = {REP}; [...rep.body.querySelectorAll('.sm-part-buttons button')].find(x => x.textContent === 'Split').dispatchEvent(new MouseEvent('click', {{ bubbles: true, shiftKey: true }}));",
                                 "d.querySelector('.sm-form input').value = '2';"), timeout=300)
    st = await page.ev(STATE)
    check('Shift-click on Split asks how many: two more splits', (st['nodes'], st['options']['steps']), (7, [{'op': 'split', 'n': 3}]))
    check('Prune takes back one split', await page.ev(button_js('Prune')), 5)
    n_go = await page.ev(button_js('Go'))
    eng = await engine(page)
    check('Go splits until the validation RSquare has not improved for 10 splits and keeps the best', (n_go, eng['go'] is not None and eng['go']['best'] == eng['splits']), (2 * eng['splits'] + 1, True))

    # ---- a node's red triangle: Split Specific, Prune Below
    await page.ev(f"(async () => {{ const rep = {REP}; const d = new Promise(res => rep.on('done', res)); rep.spec.options.steps = []; rep.run(); await d; }})()")
    r = await page.ev(UP.form_js(f"const g = {REP}.body.querySelector('.sm-upl-node[data-path=\"\"] .sm-part-menu'); g.dispatchEvent(new MouseEvent('click', {{ bubbles: true, clientX: 10, clientY: 10 }})); await new Promise(r => setTimeout(r, 80)); [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === 'Split Specific…').click();",
                                 "const s = d.querySelector('select'); s.value = [...s.options].find(o => o.textContent.startsWith('member')).value; s.dispatchEvent(new Event('change'));"), timeout=300)
    nodes = await page.ev(NODES)
    check('Split Specific… in the root\'s red triangle splits it by the column chosen (member)', sorted(nd['label'] for nd in nodes if nd['path']), ['member(No)', 'member(Yes)'])
    r = await page.ev(f"(async () => {{ const rep = {REP}; const g = rep.body.querySelector('.sm-upl-node[data-path=\"\"] .sm-part-menu'); g.dispatchEvent(new MouseEvent('click', {{ bubbles: true, clientX: 10, clientY: 10 }})); await new Promise(r => setTimeout(r, 80)); const d = new Promise(res => rep.on('done', res)); [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === 'Prune Below').click(); await d; return rep.body.querySelectorAll('.sm-upl-node').length; }})()", timeout=300)
    check('Prune Below the root takes every split back', r, 1)

    # ---- the red triangle's outlines
    await page.ev(f"(async () => {{ const rep = {REP}; const d = new Promise(res => rep.on('done', res)); rep.spec.options.steps = [{{ op: 'split', n: 3 }}]; rep.run(); await d; }})()", timeout=300)
    for path in (['Leaf Report'], ['Uplift Graph'], ['Split History'], ['Column Uplift Contributions'], ['Qini Curve'], ['Decision Threshold']):
        await page.ev(UP.pick_js('*top*', path), timeout=300)
    st = await page.ev(STATE)
    for o in ('Leaf Report', 'Uplift Graph', 'Split History', 'Split History Details', 'Column Uplift Contributions', 'Qini Curve', 'Decision Threshold'):
        check(f'the red triangle adds {o}', o in st['outlines'], True)
    check('... without errors', st['errors'], [])
    tri = await page.ev(UP.TRIANGLES)
    check('every red triangle of the report opens, with its submenus', isinstance(tri, dict) and not tri['errors'] and tri['triangles'] >= 7 and tri['items'] > tri['triangles'], True)
    eng = await engine(page)
    lr = await page.ev(table_under_js('Leaf Report', 0))
    check('Leaf Report: a line per leaf, its label, rule and Trt Diff the engine\'s', [[rw[1], rw[2], rw[7]] for rw in lr[1:]], [[lf['label'], lf['rule'], f4(lf['diff'])] for lf in eng['leaves']])
    check('... and each group\'s rate and count', [[rw[3], rw[4], rw[5], rw[6]] for rw in lr[1:]], [[f4(lf['means'][1]), str(int(lf['counts'][1])), f4(lf['means'][0]), str(int(lf['counts'][0]))] for lf in eng['leaves']])
    qt = await page.ev(table_under_js('Qini Curve', 0))
    check('Qini Curve: each set\'s Qini coefficient, the engine\'s', [rw[0] for rw in qt[1:]], [q['set'] for q in eng['qini']])
    cu = await page.ev(table_under_js('Column Uplift Contributions', 0))
    check('Column Uplift Contributions: the columns by their ChiSquare, largest first', [rw[0] for rw in cu[1:]], [r_['column'] for r_ in eng['contributions']['rows']])
    await shot(page, 'uplift-01-report.png')

    # ---- Save Columns: values, formulas that follow the table
    SAVE = '''
    (async (items) => {
      const rep = %s;
      const t = rep.table;
      const before = t.columns.length;
      for (const label of items) {
        const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h2'));
        h.querySelector('.sm-ob-menu').click();
        await new Promise(r => setTimeout(r, 60));
        [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === 'Save Columns').click();
        await new Promise(r => setTimeout(r, 60));
        [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === label).click();
        for (let i = 0; i < 100 && t.columns.length === before; i++) await new Promise(r => setTimeout(r, 50));
        await new Promise(r => setTimeout(r, 300));
      }
      await new Promise(r => setTimeout(r, 400));
      return t.columns.slice(before).map(c => ({ name: c.name, formula: c.formula ? c.formula.expr : null, type: c.dataType, mt: c.modelingType,
        values: Array.from(c.values, v => (typeof v === 'number' && !Number.isFinite(v) ? null : v)) }));
    })
    ''' % REP
    saved = await page.ev(f'({SAVE})({json.dumps(["Save Difference", "Save Difference Formula", "Save Predicteds", "Save Prediction Formula", "Save Leaf Numbers", "Save Leaf Labels"])})', timeout=300)
    names = [c['name'] for c in saved]
    check('Save Columns makes the Difference, its formula, the probabilities, their formula, the leaf numbers and labels', names,
          ['Difference bought', 'Difference bought 2', 'Prob[Yes]', 'Prob[No]', 'Most Likely bought', 'Prob[Yes] 2', 'Leaf Number', 'Leaf Label'])
    sd = await engine(page, 'uplift.save', {'what': 'difference'})
    col = {c['name']: c for c in saved}
    at = dict(zip(sd['rows'], sd['values']))
    diff_ok = all((at.get(i) is None and v is None) or (at.get(i) is not None and v is not None and math.isclose(v, at[i], rel_tol=1e-12)) for i, v in enumerate(col['Difference bought']['values']))
    check('Save Difference: every row\'s leaf\'s uplift, the engine\'s', diff_ok, True)
    check('Save Difference Formula: a formula column with the same value on every row', (col['Difference bought 2']['formula'] is not None, all(close(a, b, 1e-12) for a, b in zip(col['Difference bought 2']['values'], col['Difference bought']['values']))), (True, True))
    check('Save Prediction Formula: a formula column, Save Predicteds\' Prob[Yes] on every row', (col['Prob[Yes] 2']['formula'] is not None, all(close(a, b, 1e-12) for a, b in zip(col['Prob[Yes] 2']['values'], col['Prob[Yes]']['values']))), (True, True))
    check('... the most likely level, nominal', (col['Most Likely bought']['mt'], sorted(set(v for v in col['Most Likely bought']['values'] if v))), ('nominal', ['No', 'Yes'][:len(set(v for v in col['Most Likely bought']['values'] if v))]))
    lv = await engine(page, 'uplift.leaves')
    check('Save Leaf Numbers and Labels: the engine\'s', (col['Leaf Number']['values'][:50], col['Leaf Label']['values'][:50]), ([float(v) for v in lv['numbers'][:50]], lv['labels'][:50]))
    # a cell changes: the formulas follow it
    ch = await page.ev(f'''(async () => {{
      const rep = {REP}; const t = rep.table; const age = t.col('age');
      const i = t.col('Difference bought 2').values.findIndex((v, k) => Number.isFinite(v) && t.col('age').values[k] < 30);
      const old = [age.values[i], t.col('Difference bought 2').values[i]];
      t.setCell(i, age.id, 70);
      await new Promise(r => setTimeout(r, 400));
      return {{ i, old, now: t.col('Difference bought 2').values[i], saved: t.col('Difference bought').values[i] }};
    }})()''')
    older = next((lf['diff'] for lf in eng['leaves'] if lf['rule'].startswith('age>=')), None)
    check('a cell changed: the Difference Formula is worked out again (the leaf of an age of 70), the saved values stay', (ch['now'] != ch['old'][1], ch['saved'] == ch['old'][1]), (True, True))
    await page.ev(f"{REP}.table.setCell({ch['i']}, {REP}.table.col('age').id, {ch['old'][0]})")

    # ---- Treatment Level, Response Level
    d0 = (await engine(page))['nodes'][0]['diff']
    await page.ev(UP.pick_js('*top*', ['Treatment Level', 'No offer']), timeout=300)
    e1 = await engine(page)
    check('Treatment Level: No offer as the treatment turns the uplift\'s sign', (e1['treat'], math.isclose(e1['nodes'][0]['diff'], -d0, rel_tol=1e-9)), ('No offer', True))
    await page.ev(UP.pick_js('*top*', ['Treatment Level', 'Offer']), timeout=300)
    await page.ev(UP.pick_js('*top*', ['Response Level', 'No']), timeout=300)
    e2 = await engine(page)
    check('Response Level: the rate of No, whose uplift is the negative of Yes\'s', (e2['interest'], math.isclose(e2['nodes'][0]['diff'], -d0, rel_tol=1e-9)), ('No', True))
    await page.ev(UP.pick_js('*top*', ['Response Level', 'Yes']), timeout=300)

    # ---- Redo, a project
    before = await page.ev(STATE)
    await rerun(page)
    after = await page.ev(STATE)
    check('Redo keeps the splits', (after['nodes'], after['options']['steps']), (before['nodes'], before['options']['steps']))
    await page.ev(f"(async () => {{ const rep = {REP}; const d = new Promise(res => rep.on('done', res)); rep.spec.options.steps = [{{ op: 'specific', col: rep.table.col('member').id }}, {{ op: 'split' }}]; rep.run(); await d; }})()", timeout=300)
    r = await page.ev(f'''(async () => {{
      const rep = {REP}; const t = rep.table;
      const j = JSON.parse(JSON.stringify({{ format: 'smui-project', version: 1, tables: [{{ id: t.id, ...t.toJSON() }}], reports: [rep.toJSON()] }}));
      const before = [...rep.body.querySelectorAll('.sm-upl-node')].map(g => g.querySelector('title').textContent);
      SM.app.loadProject(j);
      const rep2 = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => {{ if (!rep2.body.classList.contains('is-running') && rep2.body.querySelector('.sm-ob')) res(); else rep2.on('done', res); }});
      for (let i = 0; i < 100 && rep2.body.querySelectorAll('.sm-upl-node').length === 0; i++) await new Promise(r => setTimeout(r, 100));
      const after = [...rep2.body.querySelectorAll('.sm-upl-node')].map(g => g.querySelector('title').textContent);
      const s = rep2.spec.options.steps[0];
      const out = {{ same: JSON.stringify(before) === JSON.stringify(after), newTable: rep2.table !== t, colName: rep2.table.col(s.col) ? rep2.table.col(s.col).name : null, n: after.length }};
      SM.app.closeTable(rep2.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      await new Promise(r => setTimeout(r, 100));
      return out;
    }})()''', timeout=300)
    check('a project opens with its own table and the same tree, the split\'s column found by its new id', (r['same'], r['newTable'], r['colName'], r['n'] >= 5), (True, True, 'member', True))
    await page.ev(f'SM.app.closeReport({REP})')

    # ---- By: each group its own splits
    r = await page.ev(open_report_js('uplift', {'y': ['bought'], 'treatment': ['offer'], 'x': ['age', 'visits last quarter'], 'by': ['member']}, {}), timeout=300)
    check('By member: a report per group, no errors', (r['errors'], len([o for o in r['outlines'] if o.startswith('Uplift Model for bought member=')])), ([], 2))
    r = await page.ev(f'''(async () => {{
      const rep = {REP};
      const b = [...rep.body.querySelectorAll('.sm-part-buttons')][1].querySelector('button');
      const d = new Promise(res => rep.on('done', res)); b.click(); await d;
      const trees = [...rep.body.querySelectorAll('.sm-part-tree')].map(s => s.querySelectorAll('.sm-upl-node').length);
      return {{ trees, keys: Object.keys(rep.spec.options).filter(k => k.endsWith('|steps')) }};
    }})()''', timeout=300)
    check('... a split in the second group splits only that group\'s tree', (r['trees'], len(r['keys'])), ([1, 3], 1))
    await page.ev(f'SM.app.closeReport({REP})')

    # ---- a K-fold Validation column: Go by the crossvalidated RSquare of its folds
    r = await page.ev(f'''(async (xs) => {{
      const src = SM.app.tables.find(t => t.name === 'Offer');
      const cols = src.columns.filter(c => !/^(Prob|Most Likely|Predicted|Difference|Leaf|Uplift)/.test(c.name)).map(c => ({{ name: c.name, dataType: c.dataType, values: c.values.slice(), ...(c.valueOrder ? {{ valueOrder: c.valueOrder.slice() }} : {{}}) }}));
      cols.push({{ name: 'Fold ID', dataType: 'numeric', values: src.columns[0].values.map((_, i) => 1 + (i * 7919) %% 5) }});
      const t = new SM.Table({{ name: 'Offer folds', source: 'test', columns: cols }});
      SM.app.addTable(t);
      const ids = (names) => names.map(n => t.col(n).id);
      const rep = SM.app.openReport(SM.platforms.get('uplift'), {{ roles: {{ y: ids(['bought']), treatment: ids(['offer']), x: ids(xs), validation: ids(['Fold ID']) }}, options: {{ history: true }} }}, t);
      await new Promise(res => rep.on('done', res));
      const go = [...rep.body.querySelectorAll('.sm-part-buttons button')].find(b => b.textContent === 'Go');
      const title = go ? go.title : null;
      const d = new Promise(res => rep.on('done', res)); go.click(); await d;
      const hp = rep.plots.find(p => /history/i.test(p.opts.title));
      const cv = hp ? hp.traces.find(tr => tr.name === 'Crossvalidation') : null;
      const eng = await SM.engine.call('uplift.fit', {{ y: 'bought', treatment: 'offer', x: xs, validation: 'Fold ID', steps: [{{ op: 'go' }}] }}, t);
      const out = {{ title, cv: cv ? cv.y.length : null, best: eng.go.best, splits: rep.spec.options.steps, errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent), engSplits: eng.splits }};
      SM.app.closeReport(rep);
      SM.app.closeTable(t);                   // the graphs below open on the Offer table again (a closed report shows the last table)
      await new Promise(r => setTimeout(r, 150));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      await new Promise(r => setTimeout(r, 150));
      SM.app.showTab(SM.app.tabOf(src));
      out.current = SM.app.current === src && !SM.app.tables.includes(t);
      return out;
    }})(%s)''' % json.dumps(XS), timeout=900)
    check('a K-fold Validation column: Go by the RSquare crossvalidated by its 5 folds, drawn in the Split History, no errors',
          ((r['title'] or '').startswith('Split until the RSquare crossvalidated by the 5 folds of Fold ID'), r['cv'], r['engSplits'], r['errors'], r['current']), (True, r['best'] + 1, r['best'], [], True))

    # ---- the graphs' code blocks
    await charts(page)

    # ---- (i): topics, the launch dialog's help, the forms' fields
    r = await page.ev(open_report_js('uplift', ROLES, {'steps': [{'op': 'split'}], 'leafReport': True, 'upliftGraph': True, 'qini': True, 'history': True}), timeout=300)
    audit = await page.ev('KvotInfo.audit()')
    check('every (i) of the report has a topic', audit['noTopic'], [])
    await UP.dialog_help(page, "SM.app.launch('uplift');", 'uplift', 'Uplift')
    await UP.form_help(page, f"const rep = {REP}; [...rep.body.querySelectorAll('.sm-part-buttons button')].find(x => x.textContent === 'Split').dispatchEvent(new MouseEvent('click', {{ bubbles: true, shiftKey: true }}));", ['Number of splits'], 'Split')
    await UP.form_help(page, "await clickPath(%s, '*top*', ['Minimum Size Split…']);" % REP, ['Minimum size'], 'Minimum Size Split')
    help_ = await page.ev(f'''(() => {{ const t = SM.info.get('p:uplift'); return {{ heads: t.sections.map(s => s.heading), about: SM.platforms.get('uplift').about.length }}; }})()''')
    check('the platform\'s (i) has Roles, Options, the split rule, the summary and the differences from JMP', help_['heads'], ['Roles', 'Options', 'How a split is chosen', 'The summary', 'Differences from JMP'])

    # ---- dark theme and phone width
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev('__gr.idle()')
    r = await page.ev(f'''(() => {{
      const rep = {REP};
      const box = rep.body.querySelector('.sm-upl-node .sm-part-box'), text = rep.body.querySelector('.sm-upl-node .sm-part-v');
      const cs = getComputedStyle(document.documentElement);
      return {{ errors: [...rep.body.querySelectorAll('.sm-ob-error')].length, dark: document.documentElement.getAttribute('data-theme'),
               box: getComputedStyle(box).fill, text: getComputedStyle(text).fill }};
    }})()''')
    check('the dark theme redraws the report without errors', (r['dark'], r['errors']), ('dark', 0))
    check('... the node boxes and their text change with it', r['box'] != 'rgb(252, 247, 242)' and r['text'] != 'rgb(53, 41, 33)', True)
    await shot(page, 'uplift-02-dark.png')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 2, 'mobile': True}, session=page.sid)
    await asyncio.sleep(1.2)
    await page.ev('__gr.idle()')
    r = await page.ev(f'''(() => {{
      const rep = {REP};
      const doc = document.scrollingElement;
      const tree = rep.body.querySelector('.sm-part-treebox');
      const plots = [...rep.body.querySelectorAll('.js-plotly-plot')].filter(p => p.offsetParent);
      return {{ page: doc.scrollWidth <= doc.clientWidth + 1, n: plots.length, plots: plots.every(p => p.getBoundingClientRect().right <= innerWidth + 1),
               treeScrolls: tree.scrollWidth > tree.clientWidth, treeInside: tree.getBoundingClientRect().right <= innerWidth + 1, body: rep.body.getBoundingClientRect().right <= innerWidth + 1 }};
    }})()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the graphs fit the phone\'s width', (r['plots'], r['n'] >= 3), (True, True))
    check('the tree scrolls in its own box, inside the report', (r['treeInside'], r['body']), (True, True))
    await shot(page, 'uplift-03-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


if __name__ == '__main__':
    asyncio.run(main())
    sys.exit(check.done())
