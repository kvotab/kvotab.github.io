#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Predictive Modeling > Partition.

The simulated Churn example opens from the URL and File > Examples, and
Partition is the first item of Analyze > Predictive Modeling; the launch
dialog has JMP's roles and options (Minimum Size Split 5, Informative
Missing and Ordinal Restricts Order on); the report starts with the root and
no scikit-learn; Split (a real mouse click), Prune, Shift-Split and Go grow
and cut the tree; the node boxes' counts, rates, probabilities (JMP's
smoothing), the candidates' G² and the summary's entropy RSquare are the
ones computed here from the table; a click on a node selects its rows, a
selection in the table shows on the nodes, points select their rows; a
node's red triangle splits it by a column chosen in a form and prunes below
it; every red triangle opens and its outlines draw (Leaf Report, Column
Contributions, Split History, Small Tree View, Fit Details, ROC, Lift,
Crossvalidation, Profiler); Save Columns writes the engine's predictions,
leaf numbers and labels; a continuous response's first split is the
example's true one and it has Actual by Predicted and Save Residuals; By
keeps each group's own splits; Redo and a project keep the splits (the
column of a node's split remapped); CART loads scikit-learn; every (i) has a
topic; the launch dialog's (i) gives every role and option its help, and the
(i) of the forms and of the buttons explain each of their inputs; the
reports draw in the dark theme and at phone width, where the tree scrolls in
its own box.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-partition.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import math
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine
from test_charts import GRAPHS_JS, close, find_line, maxdiff, run_graph

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
XS = ['region', 'contract', 'tenure (months)', 'support calls', 'internet', 'satisfaction']
REP = 'SM.app.reports[SM.app.reports.length - 1]'


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('*', '').replace('<', ''))


PICK = '''
(async (title, path, wait, which) => {
  const rep = %s;
  const heads = [...rep.body.querySelectorAll('.sm-ob-head')].filter(h => h.querySelector('h2, h3, h4').textContent.trim() === title || (title === '*top*' && h.querySelector('h2')));
  const head = heads[which || 0];
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
''' % REP


def pick_js(title, path, wait=True, which=0):
    return f'({PICK})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(wait)}, {which})'


# a form opened by fn (JS that opens it), filled by fill(dialog), then OK; waits for the report
FORM = '''
(async (open, fill) => {
  const rep = %s;
  await (new Function('return (async () => {' + open + '})()'))();
  for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 100));
  const d = [...document.querySelectorAll('.sm-dialog')].pop();
  const done = new Promise(res => rep.on('done', res));
  (new Function('d', fill))(d);
  d.querySelector('.sm-dialog-foot .primary').click();
  await done;
  return true;
})
''' % REP


def form_js(open_js, fill):
    return f'({FORM})({json.dumps(open_js)}, {json.dumps(fill)})'


TRIANGLES = '''
(async () => {
  const rep = %s;
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
''' % REP

STATE = '''
(() => {
  const rep = %s;
  return { title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
           errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 400)),
           warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)), options: rep.spec.options,
           nodes: rep.body.querySelectorAll('.sm-part-tree:not(.is-small) .sm-part-node').length };
})()
''' % REP

# the node boxes of the last report's tree: path, label, and their texts parsed
NODES = '''
(() => {
  const rep = %s;
  return [...rep.body.querySelectorAll('.sm-part-tree:not(.is-small) .sm-part-node')].map(g => {
    const t = [...g.querySelectorAll('text')].map(x => x.textContent);
    const after = (k) => { const i = t.indexOf(k); return i >= 0 ? t[i + 1] : null; };
    const h = t.indexOf('Level');
    const levels = [];
    if (h >= 0) for (let i = h + 4; i + 3 < t.length + 1; i += 4) levels.push(t.slice(i, i + 4));
    return { path: g.dataset.path, label: g.querySelector('title').textContent.replace(/ \\(leaf \\d+\\)$/, ''), count: after('Count'), g2: after('G^2'), logworth: after('LogWorth'), mean: after('Mean'), levels };
  });
})()
''' % REP

BUTTON = '''
(async (label) => {
  const rep = %s;
  const b = [...rep.body.querySelectorAll('.sm-part-buttons button')].find(x => x.textContent === label);
  if (!b) return 'no button ' + label;
  if (b.disabled) return 'disabled';
  const d = new Promise(res => rep.on('done', res));
  b.click();
  await d;
  return rep.body.querySelectorAll('.sm-part-tree:not(.is-small) .sm-part-node').length;
})
''' % REP


def button_js(label):
    return f'({BUTTON})({json.dumps(label)})'


async def triangles(page, name, least):
    r = await page.ev(TRIANGLES)
    ok = isinstance(r, dict) and not r['errors'] and r['triangles'] >= least and r['items'] > r['triangles']
    check(f'every red triangle of {name} opens, with its submenus', ok, True)
    if not ok:
        print('   ', r)


async def rerun(page):
    await page.ev(f'(async () => {{ const rep = {REP}; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; }})()')


# the payload the report sends, built here from its spec, for calls to the engine
PAYLOAD = '''
((rep) => {
  const t = rep.table, o = rep.spec.options, n = (k) => (rep.spec.roles[k] || []).map(id => t.col(id).name);
  const scope = null;
  const steps = (o.steps || []).map(s => (s.col ? { ...s, col: t.col(s.col).name } : s));
  return { table: t.id, rows: null, y: n('y')[0], x: n('x'), weight: n('weight')[0] || null, freq: n('freq')[0] || null, validation: n('validation')[0] || null,
           portion: Number(o.portion || 0), seed: o.seed !== '' && o.seed != null ? Number(o.seed) : o.seedDrawn, missing: o.missing === false ? 'drop' : 'informative',
           minsize: o.minsize || 5, ordinal_order: o.ordinalOrder !== false, steps, group: null };
})
'''



# ---- the (i) of a launch dialog, a form or an outline: its sections, as
# { headings, sections: { heading: [[name, text], ...] } }. kind 'dialog':
# arg is JS that opens the dialog (clickPath(rep, title, path) and wait(ms)
# are at hand; it is not awaited, as a form resolves only when it closes);
# kind 'slot': arg is JS giving the element that holds the (i).
INFO = r'''
(async (kind, arg, part) => {
  const wait = (ms) => new Promise(r => setTimeout(r, ms));
  const clickPath = async (rep, title, path) => {
    SM.app.showTab(SM.app.tabOf(rep));
    const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => { const t = h.querySelector('h2, h3, h4'); return t && (title === '*top*' ? t.tagName === 'H2' : t.textContent.trim() === title); });
    if (!head) throw new Error('no outline ' + title);
    head.querySelector('.sm-ob-menu').click();
    await wait(60);
    for (const label of path) {
      const menus = [...document.querySelectorAll('.sm-menu')];
      const b = [...menus[menus.length - 1].querySelectorAll('button')].find(x => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === label);
      if (!b) throw new Error('no item ' + label);
      b.click();
      await wait(80);
    }
  };
  const read = () => {
    const p = document.querySelector('.info-panel');
    if (!p) return null;
    const out = { title: p.querySelector('.info-panel-title').textContent, headings: [], sections: {} };
    let cur = '';
    for (const n of p.querySelector('.info-panel-body').children) {
      if (n.tagName === 'H3') { cur = n.textContent; out.headings.push(cur); }
      else if (n.tagName === 'DL') (out.sections[cur] = out.sections[cur] || []).push(...[...n.querySelectorAll(':scope > dt')].map(dt => [dt.textContent, dt.nextElementSibling ? dt.nextElementSibling.textContent : '']));
    }
    return out;
  };
  let dlg = null, btn = null;
  window.__infoError = null;
  if (kind === 'slot') {
    const node = (new Function('return ' + arg))();
    btn = node && (node.matches('.info-btn') ? node : node.querySelector('.info-btn'));
  } else {
    const before = new Set(document.querySelectorAll('.sm-dialog'));
    (new Function('clickPath', 'wait', 'return (async () => {' + arg + '})()'))(clickPath, wait).catch((e) => { window.__infoError = String(e); });
    for (let i = 0; i < 100 && !dlg && !window.__infoError; i++) { await wait(50); dlg = [...document.querySelectorAll('.sm-dialog')].find(d => !before.has(d)) || null; }
    if (!dlg) { SM.ui.closeMenus(0); return { error: window.__infoError || 'no dialog' }; }
    await wait(120);
    btn = dlg.querySelector('.sm-dialog-head .info-btn');
  }
  if (!btn) { if (dlg) dlg.querySelector('.sm-dialog-x').click(); return { error: 'no (i)' }; }
  // the inputs of a part (JS giving an element; a dialog's is dlg): each one's aria-label and label text
  const box = part ? (new Function('dlg', 'return ' + part))(dlg) : null;
  const inputs = box ? [...box.querySelectorAll('input, select, textarea')].map(e => [e.getAttribute('aria-label') || '', e.closest('label') ? e.closest('label').textContent.trim() : '']) : [];
  btn.click();
  await wait(150);
  const out = read() || { error: 'no panel' };
  out.inputs = inputs;
  out.key = KvotInfo.current();
  out.noTopic = KvotInfo.audit().noTopic;
  KvotInfo.close();
  if (dlg) { dlg.querySelector('.sm-dialog-x').click(); await wait(120); }
  return out;
})
'''


def info_js(kind, arg, part=None):
    return f'({INFO})({json.dumps(kind)}, {json.dumps(arg)}, {json.dumps(part)})'


def unexplained(info, heading=None):
    """The inputs of the part that no entry of the panel (of one section) names."""
    secs = info.get('sections') or {}
    names = [n for h, cs in secs.items() if heading is None or h == heading for n, _ in cs]
    return [a or t for a, t in info.get('inputs', []) if not any(a.startswith(n) or t.startswith(n) for n in names)]


async def dialog_help(page, opener, platform_id, name):
    """A launch dialog's (i): one Roles and one Options section, every role and
    option with its help (a role's followed by what it takes), and no (i)
    without a topic while the dialog is open. Returns the panel."""
    d = await page.ev(info_js('dialog', opener))
    if not isinstance(d, dict) or 'sections' not in d:
        check(f'{name}: the launch dialog\'s (i) opens', d, 'a panel')
        return {'headings': [], 'sections': {}}
    want = await page.ev(f'(() => {{ const L = SM.platforms.get({json.dumps(platform_id)}).launch; return {{ roles: L.roles.map(r => [r.label, r.help || ""]), options: (L.options || []).map(o => [o.label, o.help || ""]) }}; }})()')
    roles, opts = dict(d['sections'].get('Roles', [])), dict(d['sections'].get('Options', []))
    check(f'{name}: the launch dialog\'s (i) has one Roles and one Options section', (d['headings'].count('Roles'), d['headings'].count('Options')), (1, 1 if want['options'] else 0))
    check('... every role with its help, then what it takes', [(lab, bool(h) and roles.get(lab, '').startswith(h) and roles[lab].endswith(')')) for lab, h in want['roles']], [(lab, True) for lab, _ in want['roles']])
    check('... every option with its help', [(lab, bool(h) and opts.get(lab) == h) for lab, h in want['options']], [(lab, True) for lab, _ in want['options']])
    check('... and every (i) has a topic while it is open', d['noTopic'], [])
    return d


async def form_help(page, opener, fields, name):
    """A form's (i) lists each of its fields with what it is for."""
    f = await page.ev(info_js('dialog', opener))
    got = dict((f.get('sections') or {}).get('Fields', [])) if isinstance(f, dict) else {}
    check(f'{name}: the form\'s (i) lists its fields, each with its help', [(x, len(got.get(x, '')) > 30) for x in fields], [(x, True) for x in fields])
    check('... and every (i) has a topic while it is open', f.get('noTopic') if isinstance(f, dict) else f, [])
    return f


# ---- the graphs' matplotlib code ---------------------------------------------------------------------
# Every graph has a code block right under it (details.sm-code, ending in plt.show()). The block
# runs in the page's own Python (the notebook's runner: test_charts.GRAPHS_JS.run) with
# test_charts.PROBE in place of plt.show(), and the figure it draws is compared with the graph
# above it: a Plotly graph's points, lines, bars, reference lines, ticks, legend and titles, or an
# SVG diagram's boxes, texts and lines (the tree; the network of test-ui-neural.py). The other
# predictive platforms' suites load these helpers from this file (see test-ui-ensemble.py).

PM_JS = r'''
window.__pm = {
  // __gr.graphs (every Plotly graph drawn, with the block under it) and more of each: the
  // traces' markers and opacity, the axes' ticks and ranges, the layout's title; profiler: a
  // graph of the Prediction Profiler (interactive: no block)
  async graphs(rep) {
    const gs = await __gr.graphs(rep);
    const els = [...rep.body.querySelectorAll('.js-plotly-plot')];
    return gs.map((g, i) => {
      const p = els[i], L = p.layout || {};
      const ax = (a) => (L[a] ? { tickvals: L[a].tickvals || null, ticktext: L[a].ticktext || null, range: L[a].range || null, type: L[a].type || null,
        autorange: L[a].autorange ?? null, showticklabels: L[a].showticklabels ?? null } : null);
      return { ...g, profiler: !!p.closest('.sm-prof'), title: L.title ? (typeof L.title === 'string' ? L.title : L.title.text) : null,
        axes: { x: ax('xaxis'), y: ax('yaxis') }, showlegend: L.showlegend ?? null, annotations: (L.annotations || []).map((a) => a.text),
        more: (p.data || []).map((d) => ({ opacity: d.marker ? d.marker.opacity ?? d.opacity ?? null : d.opacity ?? null, symbol: d.marker ? d.marker.symbol ?? null : null,
          size: d.marker ? d.marker.size ?? null : null, lw: d.line ? d.line.width ?? null : null, mode: d.mode ?? null, zmin: d.zmin ?? null, zmax: d.zmax ?? null })) };
    });
  },
  // the SVG diagrams (a tree, a network), each with the code block right under it: its boxes,
  // texts, lines and circles in the SVG's own pixels (the transforms applied)
  svgs(rep) {
    return [...rep.body.querySelectorAll('.sm-part-treebox, .sm-nn-diagram')].map((box) => {
      const s = box.querySelector('svg'), n = box.nextElementSibling;
      const pt = (el, x, y) => { const q = new DOMPoint(x, y).matrixTransform(el.getCTM()); return [q.x, q.y]; };
      const num = (el, a) => Number(el.getAttribute(a) || 0);
      const rects = [...s.querySelectorAll('rect')].filter((r) => !r.closest('.sm-part-menu')).map((r) => { const [x, y] = pt(r, num(r, 'x'), num(r, 'y')); return { cls: r.getAttribute('class') || '', x, y, w: num(r, 'width'), h: num(r, 'height') }; });
      const texts = [...s.querySelectorAll('text')].map((t) => { const [x, y] = pt(t, num(t, 'x'), num(t, 'y')); return { s: t.textContent, x, y, anchor: t.getAttribute('text-anchor') || 'start', cls: t.getAttribute('class') || '' }; });
      const paths = [...s.querySelectorAll('.sm-part-links path')].map((p) => p.getAttribute('d'));
      const circles = [...s.querySelectorAll('circle')].map((c) => { const [x, y] = pt(c, num(c, 'cx'), num(c, 'cy')); return { x, y, r: num(c, 'r') }; });
      const lines = [...s.querySelectorAll('line')].map((l) => { const [x1, y1] = pt(l, num(l, 'x1'), num(l, 'y1')); const [x2, y2] = pt(l, num(l, 'x2'), num(l, 'y2')); return [x1, y1, x2, y2]; });
      return { label: s.getAttribute('aria-label'), w: num(s, 'width'), h: num(s, 'height'), rects, texts, paths, circles, lines,
        code: n && n.matches('details.sm-code, .sm-code-box') ? n.querySelector('code').textContent : null };
    });
  },
};
'''

PALETTE = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#7f7f7f', '#17becf', '#9467bd']


def flat(pts):
    return [v for p in pts for v in p]


def curve_pts(t):
    """A Plotly trace's points, gaps (None) left out."""
    return [(a, b) for a, b in zip(t.get('x') or [], t.get('y') or []) if a is not None and b is not None]


def subset_in_order(want, got, tol=1e-9):
    """Every point of want is a point of got, in the same order (a curve the page thinned)."""
    i = 0
    for w_ in want:
        while i < len(got) and not (abs(got[i][0] - w_[0]) <= tol * max(1, abs(w_[0])) and abs(got[i][1] - w_[1]) <= tol * max(1, abs(w_[1]))):
            i += 1
        if i == len(got):
            return False
        i += 1
    return True


def scatter_pts(ax):
    """Every point of every scatter of an axes, in the order drawn."""
    return [tuple(p) for sc in ax['scatter'] for p in sc['xy']]


def check_titles(check, lab, g, F, ax=None):
    ax = ax or F['axes'][0]
    check(f'{lab}: the titles', (ax['xlabel'], ax['ylabel'], ax['title'] or F['suptitle']), (g['titles']['x'] or '', g['titles']['y'] or '', g['label']))
    check(f'{lab}: the graph\'s size, 100 pixels an inch', F['size'], [g['w'] / 100, g['h'] / 100])


def check_shared(check, lab, g, F):
    """The graphs every predictive platform shows (smui-predict.js): ROC and lift curves, actual by
    predicted, the column contributions (or permutation importance). False: not one of them."""
    ax = F['axes'][0]
    t0 = g['label']
    curves = [t for t in g['traces'] if t.get('type') == 'scatter' and t.get('mode') == 'lines' and t.get('showlegend') is not False and len(t.get('x') or []) > 2]
    if t0.startswith('ROC ') or t0.startswith('Lift '):
        roc = t0.startswith('ROC ')
        ok = []
        for i, t in enumerate(curves):
            ln = next((q for q in ax['lines'] if q['label'] == t['name']), None)
            got = list(zip(ln['x'], ln['y'])) if ln else []
            ok.append(bool(ln) and subset_in_order(curve_pts(t), got) and (ln['color'] or '')[:7] == (t.get('color') or PALETTE[i % len(PALETTE)]))
        check(f'{lab}: every curve (the page\'s points on it), named and coloured as the page\'s', (len(curves) > 0, ok), (True, [True] * len(curves)))
        # the legend in the axes, or beside them (Model Screening's, on the last graph of a row only)
        check(f'{lab}: the legend', ax['legend'] or F['legend'], [t['name'] for t in curves] if g.get('showlegend') is not False else [])
        check(f'{lab}: the dotted reference', find_line(ax, [0, 1], [0, 1] if roc else [1, 1]) is not None, True)
        check_titles(check, lab, g, F)
        return True
    if t0.startswith('Actual by predicted') or t0.startswith('Residual by predicted'):
        pts = [t for t in g['traces'] if 'markers' in (t.get('mode') or '')]
        check.near(f'{lab}: the rows\' points', maxdiff(flat(scatter_pts(ax)), flat(curve_pts(pts[0]))), 0, 1e-9)
        ref = [t for t in g['traces'] if t.get('mode') == 'lines'][0]
        check(f'{lab}: the dotted reference', find_line(ax, ref['x'], ref['y'], rel=1e-9) is not None, True)
        check_titles(check, lab, g, F)
        return True
    if t0 in ('Column Contributions', 'Permutation Importance'):
        bar = [t for t in g['traces'] if t.get('type') == 'bar' and t.get('x')][0]
        check(f'{lab}: a bar per column, in the page\'s order', [x for x in ax['yticklabels'] if x], bar['y'])
        check.near(f'{lab}: the portions', maxdiff([b['w'] for b in ax['bars']], [v if v is not None else 0.0 for v in bar['x']]), 0, 1e-12)
        check(f'{lab}: the largest at the top, the portion from 0 to 1', (ax['yinverted'], ax['xlim']), (True, [0.0, 1.0]))
        check_titles(check, lab, g, F)
        return True
    return False


def check_tree(check, lab, s, F):
    """A tree's SVG against the figure: its size, the node boxes, the rate bars, every text, the lines."""
    ax = F['axes'][0]
    check(f'{lab}: the size of the page\'s tree (and a line for the title)', F['size'], [s['w'] / 100, (s['h'] + 30) / 100])
    check(f'{lab}: the title', ax['title'], s['label'])

    def key(r):
        return (round(r['x'], 3), round(r['y'], 3), round(r['w'], 3), round(r['h'], 3))
    for cls, fc, what in (('sm-part-box', '#fcf7f2ff', 'a box per node'), ('sm-part-track', '#e0d7ceff', 'the rate bars\' tracks')):
        check(f'{lab}: {what}, where the page draws them', sorted(key(b) for b in ax['bars'] if b['fc'] == fc), sorted(key(r) for r in s['rects'] if cls in r['cls'].split()))
    rates = sorted(key(b) for b in ax['bars'] if b['fc'] and b['fc'][:7] in PALETTE and b['fc'][7:] == 'ff')
    check(f'{lab}: the level rates as bars', rates, sorted(key(r) for r in s['rects'] if 'sm-part-rate' in r['cls'].split()))
    tx = sorted((t['s'], round(t['x'], 2), round(t['y'], 2)) for t in ax['texts'])
    want = sorted((t['s'], round(t['x'], 2), round(t['y'], 2)) for t in s['texts'])
    check(f'{lab}: every text of the boxes, in its place', tx, want)
    segs = []
    for d in s['paths']:
        v = [float(q) for q in d.replace('M', ' ').replace('V', ' ').replace('H', ' ').split()]
        x0, y0, ym, x1, y1 = v
        segs.append(((x0, y0), (x0, ym), (x1, ym), (x1, y1)))
    got = sorted(tuple((round(a, 6), round(b, 6)) for a, b in zip(ln['x'], ln['y'])) for ln in ax['lines'])
    check(f'{lab}: the lines from each split to its children', got, sorted(tuple((round(a, 6), round(b, 6)) for a, b in sg) for sg in segs))


def check_network(check, lab, s, F):
    """A network's SVG against the figure: its size and name, the X and response boxes, the hidden
    nodes' circles, every connection's line, every text."""
    ax = F['axes'][0]
    check(f'{lab}: the size of the page\'s diagram (and a line for the title)', F['size'], [s['w'] / 100, (s['h'] + 30) / 100])
    check(f'{lab}: the title, the page\'s name of the diagram', ax['title'], s['label'])

    def r6(v):
        return round(v, 6)
    check(f'{lab}: the X columns\' and the responses\' boxes', sorted((r6(b['x']), r6(b['y']), r6(b['w']), r6(b['h'])) for b in ax['bars']), sorted((r6(r['x']), r6(r['y']), r6(r['w']), r6(r['h'])) for r in s['rects']))
    check(f'{lab}: a circle per hidden node', sorted((r6(p['center'][0]), r6(p['center'][1]), r6(p['w'] / 2)) for p in ax['patches'] if p['type'] == 'ellipse'), sorted((r6(c['x']), r6(c['y']), r6(c['r'])) for c in s['circles']))
    check(f'{lab}: a line per connection', sorted(tuple(r6(v) for q in sg for v in q) for c in ax['segments'] for sg in c['segs']), sorted(tuple(r6(v) for v in ln) for ln in s['lines']))
    check(f'{lab}: every text in its place', sorted((t['s'], r6(t['x']), r6(t['y'])) for t in ax['texts']), sorted((t['s'], r6(t['x']), r6(t['y'])) for t in s['texts']))


def check_partition(check, lab, g, F):
    """The partition graph: the rows in their leaves' bands, the leaf means (or the rates stacked), the
    bands' edges, the leaf numbers."""
    ax = F['axes'][0]
    bars = [t for t in g['traces'] if t.get('type') == 'bar' and t.get('x')]
    pts = [t for t in g['traces'] if 'markers' in (t.get('mode') or '')]
    edges = sorted(s['x0'] for s in g['shapes'])
    check(f'{lab}: the leaves\' edges', sorted(ln['x'][0] for ln in ax['lines'] if ln['ls'] == ':' and ln['x'][0] == ln['x'][1]), edges)
    ticks = g['axes']['x']
    if ticks and ticks['tickvals']:
        check.near(f'{lab}: the leaf numbers at the bands\' centres', maxdiff(ax['xticks'], ticks['tickvals']), 0, 1e-12)
        check(f'{lab}: ... numbered as the Leaf Report', [t for t in ax['xticklabels'] if t], ticks['ticktext'])
    if not bars:
        if pts:
            check.near(f'{lab}: the training rows, in their leaves\' bands in order', maxdiff(flat(scatter_pts(ax)), flat(curve_pts(pts[0]))), 0, 1e-9)
        means = [t for t in g['traces'] if t.get('mode') == 'lines'][0]
        segs, cur = [], []
        for a, b in zip(means['x'], means['y']):
            if a is None:
                segs.append(cur)
                cur = []
            else:
                cur.append((a, b))
        want = sorted(tuple(round(v, 9) for p in sg for v in p) for sg in segs if sg)
        got = sorted(tuple(round(v, 9) for p in zip(ln['x'], ln['y']) for v in p) for ln in ax['lines'] if ln['ls'] == '-')
        check(f'{lab}: each leaf\'s mean across its band', got, want)
    else:
        want = []
        for t in bars:
            for c, h, b, w_ in zip(t['x'], t['y'], t['base'], t['width']):
                want.append((round(c - w_ / 2, 9), round(b, 9), round(w_, 9), round(h, 9)))
        got = [(round(q['x'], 9), round(q['y'], 9), round(q['w'], 9), round(q['h'], 9)) for q in ax['bars']]
        check(f'{lab}: each leaf\'s level rates stacked in its band', sorted(got), sorted(want))
        check(f'{lab}: the levels in the legend', F['legend'], [t['name'] for t in bars])
        if pts:
            # the rows at random in their level's part of their band: the counts in each part, and within it
            L = len(bars)
            parts = [(b['x'][k] - b['width'][k] / 2, b['x'][k] + b['width'][k] / 2, b['base'][k], b['base'][k] + b['y'][k]) for b in bars for k in range(len(b['x']))]

            def part_of(x, y):
                for i, (lo, hi, b0, b1) in enumerate(parts):
                    if lo + 0.08 * (hi - lo) - 1e-9 <= x <= lo + 0.92 * (hi - lo) + 1e-9 and b0 + 0.1 * (b1 - b0) - 1e-9 <= y <= b0 + 0.9 * (b1 - b0) + 1e-9:
                        return i
                return -1
            cnt_w = [0] * len(parts)
            cnt_g = [0] * len(parts)
            for x, y in curve_pts(pts[0]):
                cnt_w[part_of(x, y)] += 1
            for x, y in scatter_pts(ax):
                cnt_g[part_of(x, y)] += 1
            check(f'{lab}: every row inside its level\'s part of its leaf, as many in each as the page\'s', (cnt_g, sum(cnt_g)), (cnt_w, sum(cnt_w)))
            check(f'{lab}: ... {L} levels, no point outside', cnt_g.count(0) <= len(parts), True)
    check_titles(check, lab, g, F)


def check_lines(check, lab, g, F, rel=1e-9):
    """A graph of lines (and markers): every trace of more than one point is a line of the figure, every
    vertical or horizontal reference too; the titles."""
    ax = F['axes'][0]
    for t in g['traces']:
        if (t.get('type') or 'scatter') not in ('scatter', 'scattergl') or not t.get('x'):
            continue
        pts = curve_pts(t)
        if len(pts) > 1 and 'lines' in (t.get('mode') or ''):
            check(f'{lab}: the line {t.get("name") or ""} ({len(pts)} points)', find_line(ax, [p[0] for p in pts], [p[1] for p in pts], rel=rel, abs_=1e-12) is not None, True)
    for s in g['shapes']:
        if s.get('yref') == 'paper' and s['x0'] == s['x1']:
            check(f'{lab}: the vertical line at {s["x0"]}', any(ln['x'][:2] == [s['x0'], s['x0']] for ln in ax['lines']), True)
        elif s.get('xref') == 'paper' and s['y0'] == s['y1']:
            check(f'{lab}: the horizontal line at {s["y0"]:.4g}', any(close(ln['y'][:2], [s['y0'], s['y0']], rel, 1e-12) for ln in ax['lines']), True)
    check_titles(check, lab, g, F)


def check_hbars(check, lab, g, F, stacked=False):
    """Horizontal bars by category (the leaf report): the categories top down, each bar's length and start."""
    ax = F['axes'][0]
    bars = [t for t in g['traces'] if t.get('type') == 'bar' and t.get('x')]
    check(f'{lab}: the categories, the first at the top', ([x for x in ax['yticklabels'] if x], ax['yinverted']), (bars[0]['y'], True))
    want = [(round(t['base'][k] if t.get('base') else 0.0, 9), round(v, 9)) for t in bars for k, v in enumerate(t['x'])]
    got = [(round(b['x'], 9), round(b['w'], 9)) for b in ax['bars']]
    check(f'{lab}: each bar\'s start and length', got, want)
    if stacked:
        check(f'{lab}: the levels in the legend', F['legend'], [t['name'] for t in bars])
    check_titles(check, lab, g, F)


async def chart_blocks(page, check, label, table_js, rep_js, compare):
    """Every graph of a report: its code block right under it, ending in plt.show(); the block run in
    the page's own Python; its figure compared with the graph (check_shared, or compare(lab, g, F) for
    the platform's own graphs; the SVG diagrams by compare(lab, svg, F) too)."""
    gs = await page.ev(f'__pm.graphs({rep_js})', timeout=600)
    check(f'charts: {label}: every graph of the report drawn (none in a closed outline)', (await page.ev('__gr.take()'), len(gs) > 0), ([], True))
    prof = [g['label'] for g in gs if g['profiler']]
    check(f'charts: {label}: the profiler\'s graphs are interactive and have no block', [g['label'] for g in gs if g['profiler'] and g['code']], [])
    gs = [g for g in gs if not g['profiler']]
    svgs = await page.ev(f'__pm.svgs({rep_js})')
    shown = [g['label'] for g in gs + svgs]
    blocks = [g['label'] for g in gs + svgs if g['code'] and g['code'].rstrip().split('\n')[-1] == 'plt.show()']
    check(f'charts: {label}: every graph has its code block right under it, ending in plt.show()', [t for t in shown if t not in blocks], [])
    n = 0
    for g in gs + svgs:
        if not g['code']:
            continue
        F, err = await run_graph(page, g, table_js)
        lab = f'charts: {label}: {g["label"]}'
        check(f'{lab}: the code runs in the page', err, None)
        if not F:
            continue
        check(f'{lab}: one figure', len(F), 1)
        n += 1
        if 'traces' in g and check_shared(check, lab, g, F[0]):
            continue
        compare(lab, g, F[0])
    return n, prof


def partition_compare(lab, g, F):
    t = g['label']
    if 'rects' in g:
        check_tree(check, lab, g, F)
    elif t.startswith('Partition of'):
        check_partition(check, lab, g, F)
    elif t in ('Split history', 'AICc by number of splits'):
        check_lines(check, lab, g, F)
    elif t.startswith('Leaf '):
        check_hbars(check, lab, g, F, stacked=t == 'Leaf probabilities')
    else:
        check(f'{lab}: a graph this test knows', t, None)


async def charts(page):
    """Every graph of Partition's reports, categorical and continuous, the Show Split options on and off,
    rows excluded and By: its block under it, run in the page, its figure the graph's."""
    await page.ev(GRAPHS_JS)
    await page.ev(PM_JS)
    await page.ev('__gr.idle()')
    tbl = "SM.app.tables.find((t) => t.name === 'Churn')"
    await page.ev(f'SM.app.showTab(SM.app.tabOf({tbl}))')
    every = {'smallTree': True, 'leafReport': True, 'contrib': True, 'history': True}
    charge = {'y': ['monthly charge (€)'], 'x': ['internet', 'streaming channels', 'region', 'tenure (months)']}
    specs = [
        ('churn, Go on the validation column', {'y': ['churn'], 'x': XS, 'validation': ['validation']}, {**every, 'roc': True, 'lift': True, 'steps': [{'op': 'split', 'n': 2}, {'op': 'go'}]}),
        ('churn, the Show Split options and the points off', {'y': ['churn'], 'x': XS}, {**every, 'splitStats': False, 'splitBar': False, 'splitProb': False, 'splitCount': False, 'showPoints': False, 'roc': True, 'steps': [{'op': 'split', 'n': 3}]}),
        ('monthly charge, a validation portion', charge, {**every, 'abp': True, 'portion': 0.3, 'seed': '11', 'steps': [{'op': 'split', 'n': 3}]}),
        ('monthly charge, Show Split Stats off', charge, {'splitStats': False, 'smallTree': True, 'steps': [{'op': 'split', 'n': 2}]}),
        ('CART: churn, Go on the validation column', {'y': ['churn'], 'x': XS, 'validation': ['validation']}, {**every, 'method': 'cart', 'roc': True, 'lift': True, 'steps': [{'op': 'split', 'n': 2}, {'op': 'go'}]}),
        ('CART: monthly charge, a validation portion', charge, {**every, 'method': 'cart', 'abp': True, 'portion': 0.3, 'seed': '11', 'steps': [{'op': 'split', 'n': 3}]}),
    ]
    total = 0
    for label, roles, opts in specs:
        r = await page.ev(open_report_js('partition', roles, opts), timeout=600)
        check(f'charts: {label}: no errors', r['errors'], [])
        n, _ = await chart_blocks(page, check, label, tbl, REP, partition_compare)
        total += n
        await page.ev(f'SM.app.closeReport({REP})')
    # rows excluded, and By: the blocks keep the report's rows
    out = [2, 3, 5, 8, 13]
    await page.ev(f'{tbl}.setState({out}, "excluded", true)')
    r = await page.ev(open_report_js('partition', {'y': ['churn'], 'x': ['contract', 'tenure (months)', 'support calls'], 'by': ['internet']}, {'contrib': True, 'leafReport': True, 'roc': True, 'steps': [{'op': 'split', 'n': 2}]}), timeout=600)
    check('charts: By internet, 5 rows excluded: no errors', r['errors'], [])
    grp = await page.ev(f'''(() => {{ const rep = {REP}; const t = rep.table; const net = t.col('internet').values;
      const codes = [...rep.body.querySelectorAll('details.sm-code code')].map((c) => c.textContent).filter((s) => s.endsWith('plt.show()'));
      return {{ codes, groups: ['None', 'DSL', 'Fiber'].map((v) => [...Array(t.nrows).keys()].filter((i) => net[i] === v && !{json.dumps(out)}.includes(i))) }}; }})()''')
    kept = []
    for c in grp['codes']:
        line = next((ln for ln in c.split('\n') if ln.startswith('df = df.loc[')), '')
        kept.append(json.loads(line[len('df = df.loc['):line.index(']]') + 1]) if line else None)
    check('charts: By internet: each block keeps the rows of its group, without the excluded ones', (len(kept) > 0, all(k in grp['groups'] for k in kept)), (True, True))
    n, _ = await chart_blocks(page, check, 'By internet, rows excluded', tbl, REP, partition_compare)
    total += n
    await page.ev(f'SM.app.closeReport({REP})')
    await page.ev(f'{tbl}.setState({out}, "excluded", false)')
    check('charts: the blocks ran and drew the page\'s graphs', total >= 40, True)


async def main():
    page = await open_page(f'{BASE}/smui.html?example=churn', height=1300)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    check('partition.py imports in Pyodide', await page.ev('SM.engine.failed.filter(f => f.module === "partition").map(f => f.error)'), [])
    check('no script errors at load', page.errors, [])

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const exs = SM.app.menuItems('File').find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const pm = SM.app.menuItems('Analyze').find(i => i.label === 'Predictive Modeling');
      const items = (typeof pm.submenu === 'function' ? pm.submenu() : pm.submenu).filter(i => !i.separator).map(i => i.label);
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => [c.name, c.modelingType]), about: SM.io.EXAMPLES.churn.about, inFile: labels.includes(SM.io.EXAMPLES.churn.label), items };
    })()''')
    check('?example=churn opens the simulated churn table', (ex['name'], ex['rows'], len(ex['cols'])), ('Churn', 2000, 11))
    check('... contract is ordinal, churn nominal', (dict(ex['cols'])['contract'], dict(ex['cols'])['churn']), ('ordinal', 'nominal'))
    check('it is simulated, and its notes give the true tree', ex['about'].startswith('Simulated') and 'churn 50% in the first year' in ex['about'] and 'Region changes nothing' in ex['about'], True)
    check('it is in File > Examples', ex['inFile'], True)
    check('Partition is the first item of Analyze > Predictive Modeling', ex['items'][:1], ['Partition…'])

    # ---- the launch dialog
    r = await page.ev('''(async (xs) => {
      SM.app.launch('partition');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      const opts = [...dlg.querySelectorAll('.sm-launch-opts label')].map(l => { const i = l.querySelector('input, select'); return [[...l.childNodes].filter(x => x.nodeType === 3).map(x => x.textContent).join('').trim(), i.type === 'checkbox' ? i.checked : i.value]; });
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); items.find(x => x.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      ok.click();
      const needY = dlg.querySelector('.sm-launch-msg').textContent;
      pick('churn'); role('Y, Response').querySelector('.sm-btn').click();
      for (const x of xs) { pick(x); role('X, Factor').querySelector('.sm-btn').click(); }
      pick('validation'); role('Validation').querySelector('.sm-btn').click();
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { roles, opts, needY, options: rep.spec.options, title: rep.title };
    })(%s)''' % json.dumps(XS), timeout=300)
    check('the launch dialog has JMP\'s roles', r['roles'], ['Y, Response', 'X, Factor', 'Weight', 'Freq', 'Validation', 'By'])
    check('... and its options, with JMP\'s defaults', r['opts'], [['Validation Portion', '0'], ['Informative Missing', True], ['Random Seed', ''], ['Minimum Size Split', '5'], ['Ordinal Restricts Order', True], ['Method', 'jmp']])
    check('a response is required', 'Y, Response' in r['needY'], True)
    check('the report is Partition for churn', r['title'], 'Partition for churn')
    st = await page.ev(STATE)
    check('the report starts with the root alone, no errors', (st['nodes'], st['errors']), (1, []))
    check('... its outlines', st['outlines'], ['Partition for churn', 'Candidates', 'Confusion Matrix'])
    check('scikit-learn is not loaded by the Decision Tree method', await page.ev("SM.engine.versions['scikit-learn'] || null"), None)

    # ---- Split with a real mouse click
    pos = await page.ev(f'''(() => {{ const rep = {REP}; const b = [...rep.body.querySelectorAll('.sm-part-buttons button')].find(x => x.textContent === 'Split'); b.scrollIntoView({{ block: 'center' }}); const r = b.getBoundingClientRect(); return {{ x: r.left + r.width / 2, y: r.top + r.height / 2 }}; }})()''')
    done = page.ev(f'(async () => {{ const rep = {REP}; await new Promise(res => rep.on("done", res)); return rep.body.querySelectorAll(".sm-part-tree:not(.is-small) .sm-part-node").length; }})()')
    await asyncio.sleep(0.2)
    await page.click(pos['x'], pos['y'])
    check('a mouse click on Split splits the root: three nodes', await done, 3)
    nodes = await page.ev(NODES)
    # counts, rates and smoothed probabilities from the table itself
    calc = await page.ev(f'''((labels) => {{
      const rep = {REP}; const t = rep.table;
      const v = t.col('validation').values, y = t.col('churn').values, ten = t.col('tenure (months)').values;
      const tr = [...Array(t.nrows).keys()].filter(i => v[i] === 'Training');
      const rate = (rows) => {{ const no = rows.filter(i => y[i] === 'No').length; return [no / rows.length, 1 - no / rows.length, no, rows.length - no]; }};
      const root = rate(tr);
      const out = {{ root, kids: [] }};
      for (const lab of labels) {{
        const m = /^tenure \\(months\\)(<|>=)(.+)$/.exec(lab);
        if (!m) {{ out.kids.push(null); continue; }}
        const c = Number(m[2]);
        const rows = tr.filter(i => (m[1] === '<' ? ten[i] < c : ten[i] >= c));
        const r = rate(rows);
        // JMP: Prob = (n + prior)/(N + 1), a child of the root has the root's rates as its prior
        const prob = [(r[2] + root[0]) / (rows.length + 1), (r[3] + root[1]) / (rows.length + 1)];
        const g2 = (a) => 2 * a.filter(x => x > 0).reduce((s, x) => s + x * Math.log(x), 0);
        out.kids.push({{ n: rows.length, rate: r, prob }});
      }}
      // the root split's G^2 from the two children's counts
      const H = (no, yes) => {{ const n = no + yes; return (no ? no * Math.log(no / n) : 0) + (yes ? yes * Math.log(yes / n) : 0); }};
      const k = out.kids;
      if (k[0] && k[1]) out.g2 = 2 * (H(k[0].rate[2], k[0].rate[3]) + H(k[1].rate[2], k[1].rate[3]) - H(root[2], root[3]));
      return out;
    }})({json.dumps([nd['label'] for nd in nodes[1:]])})''')
    check('the first split is on tenure, as the example\'s tree has it', all(nd['label'].startswith('tenure (months)') for nd in nodes[1:]), True)
    root = nodes[0]
    check('the root\'s count is the training rows', num(root['count']), 1231.0)
    check('... its rates are the table\'s', [lv[1] for lv in root['levels']], [f'{calc["root"][0]:.4f}', f'{calc["root"][1]:.4f}'])
    for nd, k in zip(nodes[1:], calc['kids']):
        check(f'{nd["label"]}: its count is the table\'s rows with that tenure', num(nd['count']), float(k['n']))
        check('... its rates', [lv[1] for lv in nd['levels']], [f'{k["rate"][0]:.4f}', f'{k["rate"][1]:.4f}'])
        check('... its Prob (n + prior)/(N + 1), the root\'s rates as prior (JMP\'s rule, computed here)', [lv[2] for lv in nd['levels']], [f'{k["prob"][0]:.4f}', f'{k["prob"][1]:.4f}'])
    await page.ev(f'{REP}.body.querySelector(\'.sm-part-tree:not(.is-small) .sm-part-node[data-path=""]\').dispatchEvent(new MouseEvent("click", {{ bubbles: true }}))')
    await page.ev(f'{REP}.table.select([])')
    cand = await page.ev(table_under_js('Candidates', 0))
    check('a click on the root shows its candidates', cand[0] and cand[1:] and (await page.ev(f'{REP}.spec.options.candNode')) == '', True)
    head = cand[0]
    row = next(rw for rw in cand[1:] if rw[1] == 'tenure (months)')
    check.near('the root\'s Candidate G² for tenure is the likelihood ratio computed here', num(row[head.index('Candidate G^2')]), calc['g2'], tol=1e-6)
    check('... and its LogWorth is the one in the root\'s box', row[head.index('LogWorth')], f'{num(root["logworth"]):.4f}')
    # the engine directly, with the report's payload
    eng = await page.ev(f'(async () => {{ const rep = {REP}; const p = ({PAYLOAD})(rep); return await SM.engine.call("partition.fit", p, rep.table); }})()')
    check.near('the root\'s LogWorth is the engine\'s', num(root['logworth']), eng['nodes'][0]['split']['logworth'], tol=1e-5)
    # the summary line: the entropy RSquare computed here from the leaves' probabilities
    er2 = await page.ev(f'''((labels) => {{
      const rep = {REP}; const t = rep.table;
      const v = t.col('validation').values, y = t.col('churn').values, ten = t.col('tenure (months)').values;
      const all = [...Array(t.nrows).keys()];
      const tr = all.filter(i => v[i] === 'Training');
      const share = tr.filter(i => y[i] === 'No').length / tr.length;
      const m = /^tenure \\(months\\)(<|>=)(.+)$/.exec(labels[0]); const c = Number(m[2]);
      const leafOf = (i) => ((m[1] === '<') === (ten[i] < c) ? 0 : 1);
      const kids = [0, 1].map(k => {{ const rows = tr.filter(i => leafOf(i) === k); const no = rows.filter(i => y[i] === 'No').length; return (no + share) / (rows.length + 1); }});
      const out = {{}};
      for (const [set, lab] of [['Training', 'Training'], ['Validation', 'Validation'], ['Test', 'Test']]) {{
        const rows = all.filter(i => v[i] === lab);
        let ll = 0, ll0 = 0;
        for (const i of rows) {{ const p = kids[leafOf(i)]; ll += Math.log(y[i] === 'No' ? p : 1 - p); ll0 += Math.log(y[i] === 'No' ? share : 1 - share); }}
        out[set] = 1 - ll / ll0;
      }}
      return out;
    }})({json.dumps([nodes[1]['label']])})''')
    summ = await page.ev(table_under_js('Partition for churn', 0))
    check('the summary line has a row per set', [rw[0] for rw in summ[1:]], ['Training', 'Validation', 'Test'])
    for rw in summ[1:]:
        check(f'{rw[0]}: the entropy RSquare computed here from the leaves\' probabilities', rw[1], f'{er2[rw[0]]:.3f}')
    check('Number of Splits', summ[1][4], '1')

    # ---- more splits: the button, Shift-Split's dialog, Prune, Go
    await page.ev(button_js('Split'))
    await page.ev(button_js('Split'))
    n4 = await page.ev(button_js('Split'))
    check('three more Splits: 4 splits, 9 nodes', n4, 9)
    n3 = await page.ev(button_js('Prune'))
    check('Prune takes one back: 7 nodes', n3, 7)
    ok = await page.ev(form_js(f"const rep = {REP}; const b = [...rep.body.querySelectorAll('.sm-part-buttons button')].find(x => x.textContent === 'Split'); b.dispatchEvent(new MouseEvent('click', {{ bubbles: true, shiftKey: true }}));", "d.querySelector('.sm-form input').value = '2';"))
    st = await page.ev(STATE)
    check('Shift-click Split asks how many: 2 more, 5 splits (11 nodes)', (ok, st['nodes']), (True, 11))
    check('... the steps are the report\'s (the four Splits in one step)', st['options']['steps'], [{'op': 'split', 'n': 4}, {'op': 'prune'}, {'op': 'split', 'n': 2}])
    await page.ev(button_js('Go'))
    st = await page.ev(STATE)
    eng = await page.ev(f'(async () => {{ const rep = {REP}; const p = ({PAYLOAD})(rep); return await SM.engine.call("partition.fit", p, rep.table); }})()')
    best = max(e['Validation'] for e in eng['go']['trace'])
    summ = await page.ev(table_under_js('Partition for churn', 0))
    check('Go keeps the tree with the best validation entropy RSquare the engine found', (summ[2][1], summ[1][4]), (f'{best:.3f}', str(eng['splits'])))
    check('... it looked 10 splits past it', eng['go']['trace'][-1]['splits'] - eng['go']['best'], 10)
    await shot(page, 'partition-01-tree.png')

    # ---- linking: a node selects its rows, a selection shows on the nodes, points select rows
    r = await page.ev(f'''(async () => {{
      const rep = {REP}; const t = rep.table;
      const g = [...rep.body.querySelectorAll('.sm-part-tree:not(.is-small) .sm-part-node')].find(x => x.dataset.path === 'R');
      g.scrollIntoView({{ block: 'center', inline: 'center' }});
      await new Promise(r => setTimeout(r, 300));
      const b = g.querySelector('.sm-part-box').getBoundingClientRect();
      return {{ x: b.left + b.width / 2, y: b.top + b.height * 0.6, label: g.querySelector('title').textContent.replace(/ \\(leaf \\d+\\)$/, '') }};
    }})()''')
    await page.click(r['x'], r['y'])
    await asyncio.sleep(0.4)
    sel = await page.ev(f'''((label) => {{
      const rep = {REP}; const t = rep.table;
      const ten = t.col('tenure (months)').values;
      const m = /^tenure \\(months\\)(<|>=)(.+)$/.exec(label);
      const want = m ? [...Array(t.nrows).keys()].filter(i => (m[1] === '<' ? ten[i] < Number(m[2]) : ten[i] >= Number(m[2]))) : null;
      const cap = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Candidates').parentElement.querySelector('caption').textContent;
      return {{ got: t.selectedRows(), want, cap, picked: rep.body.querySelector('.sm-part-node.is-picked')?.dataset.path, opt: rep.spec.options.candNode }};
    }})({json.dumps(r['label'])})''')
    check('a mouse click on a node selects its rows, every set (the table\'s rows with that tenure)', sel['want'] is not None and sel['got'] == sel['want'], True)
    check('... and shows its candidates, without a redraw', (sel['cap'].startswith(r['label']), sel['picked'], sel['opt']), (True, 'R', 'R'))
    r = await page.ev(f'''(async () => {{
      const rep = {REP}; const t = rep.table;
      const leaf = [...rep.body.querySelectorAll('.sm-part-tree:not(.is-small) .sm-part-node.is-leaf')][0];
      // the training rows of that leaf, from the graph's own points
      const p = rep.plots.find(p => /^Partition of/.test(p.opts.title));
      const tr = p.traces.findIndex(x => x.name === 'Rows');
      t.select([]);
      await new Promise(r => setTimeout(r, 50));
      const widths0 = [...rep.body.querySelectorAll('.sm-part-tree:not(.is-small) .sm-part-sel')].map(x => Number(x.getAttribute('width')));
      p._click({{ points: [{{ curveNumber: tr, pointNumber: 3 }}], event: {{}} }});
      const one = t.selectedRows();
      const want = [p.rows[tr][3]];
      const rootBar = Number(rep.body.querySelector('.sm-part-tree:not(.is-small) .sm-part-node[data-path=""] .sm-part-sel').getAttribute('width'));
      const rootW = Number(rep.body.querySelector('.sm-part-tree:not(.is-small) .sm-part-node[data-path=""] .sm-part-box').getAttribute('width')) - 1;
      t.select([...Array(t.nrows).keys()]);
      await new Promise(r => setTimeout(r, 50));
      const full = [...rep.body.querySelectorAll('.sm-part-tree:not(.is-small) .sm-part-sel')].every(x => Math.abs(Number(x.getAttribute('width')) - (Number(x.parentNode.querySelector('.sm-part-box').getAttribute('width')) - 1)) < 1e-6);
      t.select([]);
      return {{ widths0, one, want, rootBar, rootW, full, n: {REP}.body.querySelectorAll('.sm-part-node').length }};
    }})()''')
    check('with nothing selected the nodes show no selection', all(x == 0 for x in r['widths0']), True)
    check('a click on a point of the partition graph selects its row', r['one'], r['want'])
    check('... and the root\'s bar shows that one training row\'s share', math.isclose(r['rootBar'], r['rootW'] / 1231, rel_tol=1e-6), True)
    check('every row selected: every node\'s bar full', r['full'], True)

    # ---- a node's red triangle: Split Specific by a chosen column, Prune Below
    r = await page.ev(f'''(async () => {{
      const rep = {REP};
      const leaf = [...rep.body.querySelectorAll('.sm-part-tree:not(.is-small) .sm-part-node.is-leaf')][0];
      leaf.dispatchEvent(new MouseEvent('contextmenu', {{ bubbles: true, clientX: 200, clientY: 200 }}));
      await new Promise(r => setTimeout(r, 80));
      const m = [...document.querySelectorAll('.sm-menu')].pop();
      const items = [...m.querySelectorAll('button')].map(b => [b.querySelector('.sm-label').textContent, b.disabled]);
      SM.ui.closeMenus(0);
      return {{ items, path: leaf.dataset.path }};
    }})()''')
    check('a leaf\'s red triangle: JMP\'s node options', r['items'], [['Split Here', False], ['Split Best', False], ['Split Specific…', False], ['Prune Below', True], ['Prune Worst', True], ['Select Rows', False], ['Show Candidates', False]])
    leaf_path = r['path']
    ok = await page.ev(form_js(f'''const rep = {REP}; const leaf = rep.body.querySelector('.sm-part-tree:not(.is-small) .sm-part-node[data-path="{leaf_path}"]');
      leaf.dispatchEvent(new MouseEvent('contextmenu', {{ bubbles: true, clientX: 200, clientY: 200 }}));
      await new Promise(r => setTimeout(r, 80));
      const m = [...document.querySelectorAll('.sm-menu')].pop();
      [...m.querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === 'Split Specific…').click();''',
        "const s = d.querySelector('.sm-form select'); s.value = [...s.options].find(o => o.textContent.startsWith('region')).value;"), timeout=120)
    st = await page.ev(STATE)
    nodes = await page.ev(NODES)
    kids = [nd['label'] for nd in nodes if nd['path'] in (leaf_path + 'L', leaf_path + 'R')]
    region_id = await page.ev(f'{REP}.table.col("region").id')
    check('Split Specific: the leaf split by region, as chosen in the form', (ok, len(kids), all(k.startswith('region(') for k in kids)), (True, 2, True))
    check('... its step names the column by id', st['options']['steps'][-1], {'op': 'specific', 'node': leaf_path, 'col': region_id})
    await page.ev(f'''(async () => {{
      const rep = {REP}; const g = rep.body.querySelector('.sm-part-tree:not(.is-small) .sm-part-node[data-path="{leaf_path}"]');
      g.dispatchEvent(new MouseEvent('contextmenu', {{ bubbles: true, clientX: 200, clientY: 200 }}));
      await new Promise(r => setTimeout(r, 80));
      const d = new Promise(res => rep.on('done', res));
      [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === 'Prune Below').click();
      await d;
    }})()''')
    st2 = await page.ev(STATE)
    check('Prune Below takes the region split back', (st2['nodes'], st2['options']['steps'][-1]), (st['nodes'] - 2, {'op': 'below', 'node': leaf_path}))

    # ---- the red triangles and the outlines they add
    await triangles(page, 'the report', 2)
    for path in (['Leaf Report'], ['Column Contributions'], ['Split History'], ['Small Tree View'], ['Show Fit Details'], ['ROC Curve'], ['Lift Curve'], ['Profiler']):
        await page.ev(pick_js('*top*', path))
    await page.ev(form_js(f"const rep = {REP}; const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h2')); h.querySelector('.sm-ob-menu').click(); await new Promise(r => setTimeout(r, 60)); [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === 'K Fold Crossvalidation…').click();",
                          "d.querySelector('.sm-form input').value = '4';"), timeout=300)
    st = await page.ev(STATE)
    for o in ('Leaf Report', 'Column Contributions', 'Split History', 'Fit Details', 'ROC Curve', 'Lift Curve', 'Crossvalidation', 'Prediction Profiler'):
        check(f'the red triangle adds {o}', o in st['outlines'], True)
    check('... and the Small Tree View, without errors', (await page.ev(f'{REP}.body.querySelectorAll(".sm-part-tree.is-small").length'), st['errors']), (1, []))
    await triangles(page, 'the report with its outlines', 6)
    # the leaf report against the engine
    eng = await page.ev(f'(async () => {{ const rep = {REP}; const p = ({PAYLOAD})(rep); return await SM.engine.call("partition.fit", p, rep.table); }})()')
    lr = await page.ev(table_under_js('Leaf Report', 0))
    check('Leaf Report: a line per leaf, its probabilities the engine\'s', [[rw[1], rw[3], rw[4]] for rw in lr[1:]], [[lf['label'], f'{lf["probs"][0]:.4f}', f'{lf["probs"][1]:.4f}'] for lf in eng['leaves']])
    check('... and its rule, the label with the conditions on one column merged (the engine\'s)', [rw[2] for rw in lr[1:]], [lf['rule'] for lf in eng['leaves']])
    check('... a rule merges two conditions on one column into one', any(rw[1].count('contract(') == 2 and rw[2].count('contract(') == 1 for rw in lr[1:]), True)
    cc = await page.ev(table_under_js('Column Contributions', 0))
    check('Column Contributions: each column\'s G², adding to the splits\'', math.isclose(sum(num(rw[1]) for rw in cc[1:]), sum(nd['split']['stat'] for nd in eng['nodes'] if nd['split']), rel_tol=1e-6), True)
    kf = await page.ev(table_under_js('Crossvalidation', 0))
    check('Crossvalidation: K Fold (4 folds) and Overall', ([rw[0] for rw in kf[1:]], kf[1][1]), (['K Fold', 'Overall'], '4'))
    check('... Overall is the tree\'s training entropy RSquare', kf[2][2], f'{eng["summary"][0]["entropy_rsquare"]:.4f}')
    prof = await page.ev(f'''(async () => {{
      const rep = {REP}; const p = ({PAYLOAD})(rep);
      const r = await SM.engine.call('partition.profile', {{ ...p, current: null }}, rep.table);
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim().startsWith('Prediction Profiler'));
      const vals = [...head.parentElement.querySelectorAll('.sm-prof-val')].map(x => x.textContent);
      return {{ vals, want: r.responses.map(x => x.current.pred), names: [...head.parentElement.querySelectorAll('.sm-prof-name')].map(x => x.textContent) }};
    }})()''')
    check('the profiler: Prob[No] and Prob[Yes] at the current settings, the engine\'s', (prof['names'], [round(num(v), 4) for v in prof['vals']]), (['Prob[No]', 'Prob[Yes]'], [round(v, 4) for v in prof['want']]))
    await shot(page, 'partition-02-outlines.png')

    # ---- Save Columns
    r = await page.ev(f'''(async () => {{
      const rep = {REP}; const t = rep.table; const p = ({PAYLOAD})(rep);
      const n0 = t.columns.length;
      for (const item of ['Save Predicteds', 'Save Leaf Numbers', 'Save Leaf Labels']) {{
        const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h2')); h.querySelector('.sm-ob-menu').click();
        await new Promise(r => setTimeout(r, 60));
        const m1 = [...document.querySelectorAll('.sm-menu')].pop();
        [...m1.querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === 'Save Columns').click();
        await new Promise(r => setTimeout(r, 60));
        [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === item).click();
        for (let i = 0; i < 50 && t.columns.length === n0; i++) await new Promise(r => setTimeout(r, 100));
        await new Promise(r => setTimeout(r, 300));
      }}
      const names = t.columns.slice(n0).map(c => c.name);
      const sv = await SM.engine.call('partition.save', p, t);
      const lv = await SM.engine.call('partition.leaves', p, t);
      const prob = t.col('Prob[No]').values, most = t.col('Most Likely churn').values, num = t.col('Leaf Number').values, lab = t.col('Leaf Label').values;
      return {{ names, prob: sv.rows.every((r, k) => Math.abs(prob[r] - sv.prob[k][0]) < 1e-12), most: sv.rows.every((r, k) => most[r] === sv.most_likely[k]),
               numbers: lv.rows.every((r, k) => num[r] === lv.numbers[k]), labels: lv.rows.every((r, k) => lab[r] === lv.labels[k]), n: sv.rows.length, kinds: [t.col('Leaf Number').modelingType, t.col('Leaf Label').dataType] }};
    }})()''', timeout=120)
    check('Save Columns: the probabilities, the most likely level, leaf numbers and labels', r['names'], ['Prob[No]', 'Prob[Yes]', 'Most Likely churn', 'Leaf Number', 'Leaf Label'])
    check('... the engine\'s values for every row', (r['prob'], r['most'], r['numbers'], r['labels'], r['n']), (True, True, True, True, 2000))
    check('... Leaf Number nominal, Leaf Label text', r['kinds'], ['nominal', 'character'])

    # ---- Save Prediction Formula and the leaf formulas: live formula columns with Save Predicteds' values
    SAVEF = '''
    (async (items) => {
      const rep = %s; const t = rep.table; const n0 = t.columns.length;
      for (const item of items) {
        const k = t.columns.length;
        const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h2')); h.querySelector('.sm-ob-menu').click();
        await new Promise(r => setTimeout(r, 60));
        [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === 'Save Columns').click();
        await new Promise(r => setTimeout(r, 60));
        [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === item).click();
        for (let i = 0; i < 80 && t.columns.length === k; i++) await new Promise(r => setTimeout(r, 100));
        await new Promise(r => setTimeout(r, 400));
      }
      return t.columns.slice(n0).map(c => ({ name: c.name, formula: !!(c.formula && c.formula.expr), mt: c.modelingType, order: c.valueOrder || null,
        values: Array.from(c.values, v => (typeof v === 'number' && !Number.isFinite(v) ? null : v)) }));
    })
    ''' % REP
    made = await page.ev(f'({SAVEF})({json.dumps(["Save Prediction Formula", "Save Leaf Number Formula", "Save Leaf Label Formula"])})', timeout=300)
    old_cols = await page.ev(f'''(() => {{ const t = {REP}.table; const g = (n) => Array.from(t.col(n).values, v => (typeof v === 'number' && !Number.isFinite(v) ? null : v));
      return {{ no: g('Prob[No]'), yes: g('Prob[Yes]'), most: g('Most Likely churn'), num: g('Leaf Number'), lab: g('Leaf Label') }}; }})()''')
    fc = {c['name']: c for c in made}
    check('Save Prediction Formula: a formula column per level\'s probability and the most likely level; the leaf formulas',
          ([c['name'] for c in made], all(c['formula'] for c in made)), (['Prob[No] 2', 'Prob[Yes] 2', 'Most Likely churn 2', 'Leaf Number 2', 'Leaf Label 2'], True))
    check('... each probability\'s formula gives Save Predicteds\' probability on every row', (all(close(a, b, 1e-12) for a, b in zip(fc['Prob[No] 2']['values'], old_cols['no'])), all(close(a, b, 1e-12) for a, b in zip(fc['Prob[Yes] 2']['values'], old_cols['yes']))), (True, True))
    check('... the Most Likely formula the level of the largest probability, nominal in the levels\' order', (fc['Most Likely churn 2']['values'] == old_cols['most'], fc['Most Likely churn 2']['mt'], fc['Most Likely churn 2']['order']), (True, 'nominal', ['No', 'Yes']))
    check('... the leaf number and label formulas give Save Leaf Numbers\' and Labels\' values', (fc['Leaf Number 2']['values'] == old_cols['num'], fc['Leaf Label 2']['values'] == old_cols['lab']), (True, True))
    live = await page.ev(f'''(async () => {{
      const rep = {REP}; const t = rep.table; const ten = t.col('tenure (months)'), f = t.col('Leaf Number 2');
      const i = [...Array(t.nrows).keys()].find(k => ten.values[k] < 6);
      const before = f.values[i]; const old = ten.values[i];
      t.setCell(i, ten.id, 60);
      await new Promise(r => setTimeout(r, 400));
      const after = f.values[i];
      t.setCell(i, ten.id, old);
      await new Promise(r => setTimeout(r, 400));
      return {{ before, after, back: f.values[i], saved: t.col('Leaf Number').values[i] }};
    }})()''')
    check('... a cell changed: the formula columns are worked out again, the saved values stay', (live['before'] != live['after'], live['back'] == live['before'], live['saved'] == live['before']), (True, True, True))
    summ = await page.ev(table_under_js('Partition for churn', 0))
    check('the summary has JMP\'s AICc, on the training line', ('AICc' in summ[0], summ[1][summ[0].index('AICc')] not in ('', '.')), (True, True))

    # ---- the Python script, Bootstrap on the summary, the Local Data Filter
    script = await page.ev(f'{REP}.pythonScript()')
    check('the script holds the engine once, the tree\'s steps and the K Fold', (script.count('class Tree:'), 'tree.run([' in script, 'kfold(columns, X, y' in script), (1, True, True))
    r = await page.ev(f'''(async () => {{
      const rep = {REP};
      const tbl = rep.body.querySelector('.sm-part-summary table.sm-rt');
      const col = tbl._rt.columns.find(c => c.label === 'Entropy RSquare');
      const t = await SM.bootstrap.run(tbl, col, {{ B: 4, seed: 3, show: false }});
      const vals = t.columns.slice(1).map(c => c.values);
      return {{ rows: t.nrows, names: t.columns.map(c => c.name), finite: vals.every(v => v.every(Number.isFinite)), first: vals.map(v => v[0]), differ: vals.some(v => v.slice(1).some(x => x !== v[0])),
               errors: rep.body.querySelectorAll('.sm-ob-error').length }};
    }})()''', timeout=600)
    summ = await page.ev(table_under_js('Partition for churn', 0))
    check('Bootstrap of the summary\'s entropy RSquare: the report and 4 resamples, a column per set', (r['rows'], r['names']), (5, ['BootID', 'Training', 'Validation', 'Test']))
    check('... each resample regrows the tree (headless), the report\'s own values first', (r['finite'], r['differ'], [f'{v:.3f}' for v in r['first']], r['errors']), (True, True, [rw[1] for rw in summ[1:]], 0))
    r = await page.ev(f'''(async () => {{
      const rep = {REP}; const t = rep.table;
      const d = new Promise(res => rep.on('done', res));
      rep.spec.filter = [{{ col: t.col('region').id, levels: ['North'] }}];
      rep.run(); await d;
      const root = rep.body.querySelector('.sm-part-tree:not(.is-small) .sm-part-node[data-path=""]');
      const texts = [...root.querySelectorAll('text')].map(x => x.textContent);
      const v = t.col('validation').values, reg = t.col('region').values;
      const want = [...Array(t.nrows).keys()].filter(i => reg[i] === 'North' && v[i] === 'Training').length;
      const d2 = new Promise(res => rep.on('done', res));
      rep.spec.filter = null; rep.run(); await d2;
      return {{ count: texts[texts.indexOf('Count') + 1], want }};
    }})()''', timeout=300)
    check('the Local Data Filter: the tree grown on the North rows alone', num(r['count']), float(r['want']))

    # ---- Redo keeps the steps; a project keeps them with the column ids remapped
    before = await page.ev(STATE)
    await rerun(page)
    after = await page.ev(STATE)
    check('Redo keeps the splits', (after['nodes'], after['options']['steps']), (before['nodes'], before['options']['steps']))
    await page.ev(f'(async () => {{ const rep = {REP}; const g = rep.body.querySelector(".sm-part-tree:not(.is-small) .sm-part-node.is-leaf"); const path = g.dataset.path; const t = rep.table; const d = new Promise(res => rep.on("done", res)); rep.spec.options.steps = [...rep.spec.options.steps, {{ op: "specific", node: path, col: t.col("internet").id }}]; rep.run(); await d; }})()')
    r = await page.ev(f'''(async () => {{
      const rep = {REP}; const t = rep.table;
      const summ = [...rep.body.querySelectorAll('.sm-part-summary table tr')].map(tr => [...tr.children].map(c => c.textContent));
      const j = JSON.parse(JSON.stringify({{ format: 'smui-project', version: 1, tables: [{{ id: t.id, ...t.toJSON() }}], reports: [rep.toJSON()] }}));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => {{ if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); }});
      const last = back.spec.options.steps[back.spec.options.steps.length - 1];
      const out = {{ newTable: back.table !== t, colName: back.table.col(last.col) ? back.table.col(last.col).name : null, sameId: last.col === t.col('internet').id,
                     nodes: back.body.querySelectorAll('.sm-part-tree:not(.is-small) .sm-part-node').length, was: rep.body.querySelectorAll('.sm-part-tree:not(.is-small) .sm-part-node').length,
                     summ2: [...back.body.querySelectorAll('.sm-part-summary table tr')].map(tr => [...tr.children].map(c => c.textContent)), summ,
                     errors: [...back.body.querySelectorAll('.sm-ob-error')].length, heads: [...back.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent) }};
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    }})()''', timeout=300)
    check('a project opens with its own table, the node split\'s column found by its new id', (r['newTable'], r['colName'], r['sameId']), (True, 'internet', False))
    check('... the same tree and summary, no errors', (r['nodes'], r['summ2'], r['errors']), (r['was'], r['summ'], 0))
    check('... and the same outlines', all(o in r['heads'] for o in ('Leaf Report', 'Split History', 'Crossvalidation')), True)

    # ---- a continuous response
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Churn")))')
    rep = await page.ev(open_report_js('partition', {'y': ['monthly charge (€)'], 'x': ['internet', 'streaming channels', 'region', 'tenure (months)']}, {'steps': [{'op': 'split', 'n': 2}], 'abp': True}), timeout=300)
    check('a continuous response: Actual by Predicted, no errors', ('Actual by Predicted Plot' in rep['outlines'], rep['errors']), (True, []))
    nodes = await page.ev(NODES)
    # the example's model: 20 € with no internet, about 57 with DSL and 82 with fiber (the channels included): no
    # internet against the rest explains the most (0.2 × 0.8 × 49.5² against 0.4 × 0.6 × 36.3² for fiber)
    check('its first split is internet, none against DSL and fiber (the largest SS in the example\'s model)', sorted(nd['label'] for nd in nodes if nd['path'] in ('L', 'R')), ['internet(DSL, Fiber)', 'internet(None)'])
    m = await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Churn'); const net = t.col('internet').values, c = t.col('monthly charge (€)').values;
      const f = [...Array(t.nrows).keys()].filter(i => net[i] === 'None'); const mean = f.reduce((s, i) => s + c[i], 0) / f.length;
      const sd = Math.sqrt(f.reduce((s, i) => s + (c[i] - mean) ** 2, 0) / (f.length - 1)); return { n: f.length, mean, sd }; })()''')
    nn = next(nd for nd in nodes if nd['label'] == 'internet(None)')
    check('... the node\'s count and mean, computed here', (num(nn['count']), nn['mean']), (float(m['n']), f'{m["mean"]:.6g}'.replace('-', '−')))
    r = await page.ev(f'''(async () => {{
      const rep = {REP}; const t = rep.table; const n0 = t.columns.length;
      for (const item of ['Save Predicteds', 'Save Residuals']) {{
        const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h2')); h.querySelector('.sm-ob-menu').click();
        await new Promise(r => setTimeout(r, 60));
        [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === 'Save Columns').click();
        await new Promise(r => setTimeout(r, 60));
        [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label').textContent === item).click();
        for (let i = 0; i < 50 && t.columns.length === n0 + (item === 'Save Predicteds' ? 0 : 1); i++) await new Promise(r => setTimeout(r, 100));
      }}
      const p = t.col('Predicted monthly charge (€)').values, res = t.col('Residual monthly charge (€)').values, c = t.col('monthly charge (€)').values;
      return {{ names: t.columns.slice(n0).map(c => c.name), ok: [...Array(t.nrows).keys()].every(i => Math.abs(c[i] - p[i] - res[i]) < 1e-9), levels: new Set(p).size }};
    }})()''', timeout=120)
    check('Save Predicteds and Save Residuals: the leaf means and the response minus them', (r['names'], r['ok'], r['levels']), (['Predicted monthly charge (€)', 'Residual monthly charge (€)'], True, 3))
    made = await page.ev(f'({SAVEF})({json.dumps(["Save Prediction Formula"])})', timeout=300)
    pv_ = await page.ev(f"Array.from({REP}.table.col('Predicted monthly charge (€)').values, v => (Number.isFinite(v) ? v : null))")
    check('Save Prediction Formula (continuous): the leaf means as a formula, Save Predicteds\' on every row', ([c['name'] for c in made], all(close(a, b, 1e-12) for a, b in zip(made[0]['values'], pv_))), (['Predicted monthly charge (€) 2'], True))
    await shot(page, 'partition-03-continuous.png')

    # ---- By: each group its own splits
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Churn")))')
    rep = await page.ev(open_report_js('partition', {'y': ['churn'], 'x': ['contract', 'tenure (months)'], 'by': ['region']}, {}), timeout=300)
    check('By region: a tree per region', [o for o in rep['outlines'] if o.startswith('Partition for')], ['Partition for churn region=East', 'Partition for churn region=North', 'Partition for churn region=South', 'Partition for churn region=West'])
    r = await page.ev(f'''(async () => {{
      const rep = {REP};
      const b = [...rep.body.querySelectorAll('.sm-part-buttons')][1].querySelector('button');
      const d = new Promise(res => rep.on('done', res)); b.click(); await d;
      const per = [...rep.body.querySelectorAll('.sm-part-tree:not(.is-small)')].map(s => s.querySelectorAll('.sm-part-node').length);
      return {{ per, keys: Object.keys(rep.spec.options).filter(k => k.endsWith('steps')) }};
    }})()''')
    check('Split in the North tree splits that tree only', (r['per'], r['keys']), ([1, 3, 1, 1], ['by:region=North|steps']))
    tbls = await page.ev(f'(() => {{ const rep = {REP}; const t = [...rep.body.querySelectorAll("table.sm-rt")].filter(x => x.dataset.rtKey === "summary"); return {{ n: t.length, groups: t.map(x => x.dataset.group), rows: SM.report.combineRT(t, "x").nrows }}; }})()')
    check('... the summaries combine into one table', (tbls['n'], tbls['rows']), (4, 4))

    # ---- CART loads scikit-learn
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Churn")))')
    rep = await page.ev(open_report_js('partition', {'y': ['churn'], 'x': XS, 'validation': ['validation']}, {'steps': [{'op': 'split', 'n': 3}]}), timeout=300)
    await page.ev(pick_js('*top*', ['Method', 'CART (scikit-learn)']), timeout=600)
    st = await page.ev(STATE)
    ver = await page.ev("SM.engine.versions['scikit-learn'] || null")
    check('Method > CART: the first call loads scikit-learn', ver, '1.8.0')
    check('... a CART tree of 3 splits, no candidates, no errors', (st['nodes'], 'Candidates' in st['outlines'], st['errors']), (7, False, []))
    eng = await page.ev(f'(async () => {{ const rep = {REP}; const p = ({PAYLOAD})(rep); return await SM.engine.call("partition.cart_fit", p, rep.table); }})()')
    summ = await page.ev(table_under_js('Partition for churn', 0))
    check('... its summary is the engine\'s CART fit', summ[1][1], f'{eng["summary"][0]["entropy_rsquare"]:.3f}')
    check('... the splits are scikit-learn\'s (≤ conditions)', any('<=' in nd['label'] or '>' in nd['label'] for nd in eng['nodes']), True)
    await page.ev(pick_js('*top*', ['Method', 'Decision Tree (LogWorth, JMP)']))

    # ---- a K-fold Validation column: the Crossvalidation report by its folds, Go by the crossvalidated RSquare
    r = await page.ev(f'''(async (xs) => {{
      const src = SM.app.tables.find(t => t.name === 'Churn');
      const keepCol = (c) => !/^(Prob|Most Likely|Predicted|Residual|Leaf)/.test(c.name);
      const cols = src.columns.filter(keepCol).map(c => ({{ name: c.name, dataType: c.dataType, values: c.values.slice(), ...(c.valueOrder ? {{ valueOrder: c.valueOrder.slice() }} : {{}}), ...(c.modelingType ? {{ modelingType: c.modelingType }} : {{}}) }}));
      cols.push({{ name: 'Fold ID', dataType: 'numeric', values: src.columns[0].values.map((_, i) => 1 + (i * 7919) %% 5) }});
      const t = new SM.Table({{ name: 'Churn folds', source: 'test', columns: cols }});
      SM.app.addTable(t);
      const ids = (names) => names.map(n => t.col(n).id);
      const rep = SM.app.openReport(SM.platforms.get('partition'), {{ roles: {{ y: ids(['churn']), x: ids(xs), validation: ids(['Fold ID']) }}, options: {{ seed: '3', history: true }} }}, t);
      await new Promise(res => rep.on('done', res));
      const heads = () => [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
      const before = heads();
      const kfTable = () => {{ const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Crossvalidation'); return h ? [...h.parentElement.querySelectorAll('table.sm-rt')].map(tb => tb._rt.rows.length) : null; }};
      const k0 = kfTable();
      const goBtn = [...rep.body.querySelectorAll('.sm-part-buttons button')].find(b => b.textContent === 'Go');
      const title = goBtn ? goBtn.title : null;
      const d = new Promise(res => rep.on('done', res)); goBtn.click(); await d;
      const hp = rep.plots.find(p => p.opts.title === 'Split history');
      const cv = hp ? hp.traces.find(tr => tr.name === 'Crossvalidation') : null;
      const eng = await SM.engine.call('partition.fit', {{ y: 'churn', x: xs, validation: 'Fold ID', seed: 3, steps: [{{ op: 'go' }}] }}, t);
      const note = [...rep.body.querySelectorAll('.sm-ob-note')].map(n => n.textContent).find(x => /crossvalidated by the 5 folds/.test(x)) || null;
      const kf = kfTable();
      const eachHead = (() => {{ const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Crossvalidation'); const tb = h && h.parentElement.querySelectorAll('table.sm-rt')[1]; return tb ? [...tb.querySelectorAll('thead th')].map(th => th.textContent) : null; }})();
      return {{ before, k0, title, cv: cv ? {{ x: cv.x, y: cv.y }} : null, go: eng.go, splits: eng.splits, shown: rep.body.querySelectorAll('.sm-part-tree:not(.is-small) .sm-part-node').length, nodes: eng.nodes.length, note, kf, eachHead, errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent) }};
    }})(%s)''' % json.dumps(XS), timeout=600)
    check('a K-fold Validation column (5 values): the Crossvalidation report shows by itself, with the column\'s 5 folds and Overall', ('Crossvalidation' in r['before'], r['k0']), (True, [2, 5]))
    check('... Go is there, by the crossvalidated RSquare', (r['title'] or '').startswith('Split until the RSquare crossvalidated by the 5 folds of Fold ID'), True)
    upto = [e for e in (r['go'] or {}).get('trace', []) if e['splits'] <= r['go']['best']]
    check('... after Go: the engine\'s tree, and Split History draws the crossvalidated RSquare up to the size kept', (r['shown'], r['cv'] and r['cv']['x'] == [e['splits'] for e in upto] and all(abs(a - e['Crossvalidation']) < 1e-12 for a, e in zip(r['cv']['y'], upto))), (r['nodes'], True))
    check('... its note says what Go kept by, and no errors', (bool(r['note']), r['errors']), (True, []))
    check('... the Each Fold table names each fold by its value in the column', r['eachHead'][:2] if r['eachHead'] else None, ['Fold', 'Fold ID'])
    r2 = await page.ev('''(async () => {
      const rep = SM.app.reports.at(-1);
      const h = rep.body.querySelector('.sm-ob-head h2').parentElement.querySelector('.sm-ob-menu'); h.click();
      await new Promise(r => setTimeout(r, 60));
      const b = [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(x => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === 'K Fold Crossvalidation');
      const checked = b ? b.getAttribute('aria-checked') || (b.classList.contains('is-checked') ? 'true' : null) : null;
      const d = new Promise(res => rep.on('done', res)); b.click(); await d;
      const heads = [...rep.body.querySelectorAll('.sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
      const opt = rep.spec.options.kfold;
      SM.app.closeReport(rep);          // the checks below read the report before this one
      SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'Churn')));
      return { found: !!b, heads, opt };
    })()''')
    check('... its red triangle item (no number to ask) turns the Crossvalidation off', (r2['found'], 'Crossvalidation' in r2['heads'], r2['opt']), (True, False, False))

    # ---- the (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-partition"); const row = document.getElementById("help-p-partition"); return row ? row.textContent : null; })()')
    check('the platform has its line in Help, with numpy and scikit-learn', bool(helps) and 'numpy' in helps and 'DecisionTreeClassifier' in helps, True)
    topics = await page.ev('Object.keys(SM.platforms.get("partition").topics)')
    check('its topics', sorted(topics), sorted(['p:partition', 'p:partition:tree', 'p:partition:cands', 'p:partition:history', 'p:partition:leaves', 'p:partition:kfold']))

    # ---- the (i) explains every input: the launch dialog, the forms, the buttons
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Churn")))')
    d = await dialog_help(page, "SM.app.launch('partition')", 'partition', 'Partition')
    opts = dict(d['sections'].get('Options', []))
    check('... its Informative Missing says how the tree sends a missing value', 'sends a missing value of a continuous X to the side of each split where it fits better' in opts.get('Informative Missing', ''), True)
    last = 'SM.app.reports.at(-1)'
    await form_help(page, f"const b = [...{last}.body.querySelectorAll('.sm-part-buttons button')].find(x => x.textContent === 'Split'); b.dispatchEvent(new MouseEvent('click', {{ bubbles: true, shiftKey: true }}));", ['Number of splits'], 'Shift-click Split')
    await form_help(page, f"await clickPath({last}, '*top*', ['K Fold Crossvalidation…']);", ['Number of folds (k)'], 'K Fold Crossvalidation…')
    await form_help(page, f"await clickPath({last}, '*top*', ['Minimum Size Split…']);", ['Minimum size'], 'Minimum Size Split…')
    await form_help(page, f"const leaf = {last}.body.querySelector('.sm-part-tree:not(.is-small) .sm-part-node.is-leaf'); leaf.querySelector('.sm-part-menu').dispatchEvent(new MouseEvent('click', {{ bubbles: true }})); await wait(80); [...[...document.querySelectorAll('.sm-menu')].pop().querySelectorAll('button')].find(b => b.querySelector('.sm-label') && b.querySelector('.sm-label').textContent === 'Split Specific…').click();",
                    ['Column', 'Cut value (a continuous column; empty: the best cut)'], 'A node\'s Split Specific…')
    s = await page.ev(info_js('slot', f"{last}.body.querySelector('.sm-part-buttons')"))
    check('the buttons\' (i) explains Split, Prune, Go and Color Points, and a node\'s click and red triangle',
          ([c[0] for c in s['sections'].get('The buttons', [])], [c[0] for c in s['sections'].get('Clicking a node', [])]),
          (['Split', 'Prune', 'Go', 'Color Points'], ['A click', 'Split Here', 'Split Best', 'Split Specific…', 'Prune Below', 'Prune Worst', 'Select Rows, Show Candidates']))
    check('... and the report is as it was (the forms closed with nothing done)', (await page.ev(STATE))['nodes'], 7)

    # ---- the graphs' matplotlib code
    await charts(page)

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "partition" && r.spec.options.kfold)))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2.5)
    r = await page.ev('''(() => {
      const rep = SM.app.reports.find(r => r.platform.id === "partition" && r.spec.options.kfold);
      const css = getComputedStyle(document.documentElement);
      const box = rep.body.querySelector('.sm-part-tree:not(.is-small) .sm-part-box'), title = rep.body.querySelector('.sm-part-tree:not(.is-small) .sm-part-title'), tri = rep.body.querySelector('.sm-part-tri');
      const rgb = (v) => { const d = document.createElement('div'); d.style.color = v; document.body.append(d); const c = getComputedStyle(d).color; d.remove(); return c; };
      return { errors: SM.app.reports.filter(r => r.platform.id === 'partition').flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)),
               box: getComputedStyle(box).fill, surface: rgb(css.getPropertyValue('--bg-surface')), text: getComputedStyle(title).fill, primary: rgb(css.getPropertyValue('--text-primary')), tri: getComputedStyle(tri).fill,
               dark: document.documentElement.getAttribute('data-theme') };
    })()''')
    check('the dark theme redraws the reports without errors', (r['dark'], r['errors']), ('dark', []))
    check('... the node boxes take the dark surface, their text the dark text colour', (r['box'], r['text']), (r['surface'], r['primary']))
    check('... the node\'s red triangle the dark theme\'s red', r['tri'], 'rgb(255, 107, 92)')
    await shot(page, 'partition-04-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports.find(r => r.platform.id === "partition" && r.spec.options.kfold); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')
    await asyncio.sleep(1.0)
    r = await page.ev('''(() => {
      const rep = SM.app.reports.find(r => r.platform.id === "partition" && r.spec.options.kfold);
      const body = rep.body.getBoundingClientRect();
      // the profiler's small plots keep their width and scroll in the profiler's own box
      const boxes = rep.plots.filter(p => p.drawn && !p.box.closest('.sm-profwrap')).map(p => p.box.getBoundingClientRect().right);
      const tree = rep.body.querySelector('.sm-part-treebox:not(.is-small)');
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length,
               body: rep.body.scrollWidth <= rep.body.clientWidth + 1, treeScrolls: tree.scrollWidth > tree.clientWidth, treeInside: tree.getBoundingClientRect().right <= body.right + 1 };
    })()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the graphs fit the phone\'s width', (r['plots'], r['n'] >= 3), (True, True))
    check('the tree scrolls in its own box, inside the report', (r['treeScrolls'], r['treeInside'], r['body']), (True, True, True))
    await shot(page, 'partition-05-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


if __name__ == '__main__':
    asyncio.run(main())
    sys.exit(check.done())
