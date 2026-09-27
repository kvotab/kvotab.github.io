#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Multivariate Methods > Multivariate
Embedding.

The simulated Cell profiles example opens from the URL and File > Examples,
and the platform sits in Analyze > Multivariate Methods after
Multidimensional Scaling; the launch dialog casts the columns and the Color
column and offers t-SNE alone (UMAP needs numba); the first fit loads
scikit-learn and shows its progress, iteration by iteration; the map is the
engine's, one point per row, coloured by the cell types, which it keeps
apart; points select their rows (one by a real mouse click) and table
selections light them up; every red triangle opens; Color By uses the rows'
colours or another column; Save Embedding writes the coordinates; the
perplexity from the red triangle changes the map and Redo keeps it; three
dimensions draw in pairs without WebGL, and as a turning plot whose points
follow the table's selection and hidden rows; above 3000 rows the report
asks first and runs when told, above 10 000 it refuses; missing values are
left out; By gives one map per donor; a project keeps the options with the
Color column's id remapped; every (i) has a topic; the launch dialog's (i)
gives every role and option its help, and the red triangle's forms' (i) each
of their fields; the reports draw in the dark theme and at phone width
without a sideways page scroll, and no script error happens.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-embedding.py

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
M = [f'm{j:02d}' for j in range(1, 13)]


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace(',', ''))


PICK = '''
(async (title, path, wait, which) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
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
'''


def pick_js(title, path, wait=True, which=0):
    return f'({PICK})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(wait)}, {which})'


PICK_FORM = '''
(async (title, path, fill) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await (%s)(title, path, false, 0);
  for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 100));
  const d = [...document.querySelectorAll('.sm-dialog')].pop();
  const done = new Promise(res => rep.on('done', res));
  const i = d.querySelector('.sm-form input');
  i.value = fill;
  d.querySelector('.sm-dialog-foot .primary').click();
  await done;
  return [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
})
''' % PICK


def pick_form_js(title, path, value):
    return f'({PICK_FORM})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(value)})'


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

STATE = '''
(() => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  return { title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
           errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 400)),
           warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 400)), options: rep.spec.options,
           notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent) };
})()
'''

# The map the report shows: its plot's first trace and rows.
MAP = '''
(() => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const p = rep.plots.find(p => /^t-SNE map/.test(p.opts.title));
  if (!p) return null;
  const t0 = p.traces[0];
  return { title: p.opts.title, type: t0.type, n: p.rows[0].length, rows: p.rows[0], x: t0.x, y: t0.y, z: t0.z || null, colors: Array.isArray(t0.marker.color) ? t0.marker.color : null, rowColors: p.rowColors,
           traces: p.traces.length, legend: p.traces.filter(t => t.showlegend).map(t => t.name), drawn: p.drawn };
})()
'''

# The fit from the engine with the report's own payload.
ENGINE = '''
(async () => {
  const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table; const o = rep.spec.options;
  const seed = (o.seed !== undefined && o.seed !== '' && o.seed !== null) ? Math.trunc(Number(o.seed)) : o.seedDrawn;
  return await SM.engine.call('embedding.fit', { table: t.id, rows: null, columns: rep.spec.roles.y.map(id => t.col(id).name), dimension: Number(o.dimension ?? 2) === 3 ? 3 : 2,
    perplexity: Number(o.perplexity ?? 30), max_iter: Number(o.iterations ?? 1000), learning_rate: String(o.learningRate ?? 'auto'), init: o.init || 'pca', standardize: o.standardize ?? true, seed }, t);
})()
'''


async def rerun(page):
    await page.ev('(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()', timeout=600)


async def details(page):
    kv = await page.ev(table_under_js('Fit Details', 0))
    return {row[0]: row[1] for row in kv} if kv else {}



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


async def main():
    page = await open_page(f'{BASE}/smui.html?example=cellprofiles', height=1300)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    check('embedding.py imports in Pyodide', await page.ev('SM.engine.failed.filter(f => f.module === "embedding").map(f => f.module + ": " + f.error)'), [])
    check('no script errors at load', page.errors, [])
    check('scikit-learn is not loaded at the start', await page.ev("SM.engine.versions['scikit-learn'] || null"), None)

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const file = SM.app.menuItems('File');
      const exs = file.find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const an = SM.app.menuItems('Analyze');
      const mm = an.find(i => i.label === 'Multivariate Methods');
      const items = (typeof mm.submenu === 'function' ? mm.submenu() : mm.submenu).filter(i => !i.separator).map(i => i.label);
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), about: SM.io.EXAMPLES.cellprofiles.about, inFile: labels.includes(SM.io.EXAMPLES.cellprofiles.label), items,
               types: [...new Set(t.col('type (true)').values)].sort() };
    })()''')
    check('?example=cellprofiles opens the simulated cells', (ex['name'], ex['rows'], ex['cols']), ('Cell profiles', 900, ['donor', 'type (true)'] + M))
    check('it is simulated, of five types', (ex['about'].startswith('Simulated'), ex['types']), (True, [f'type {i}' for i in range(1, 6)]))
    check('it is in File > Examples', ex['inFile'], True)
    check('Analyze > Multivariate Methods lists Multivariate Embedding after Multidimensional Scaling', 'Multivariate Embedding…' in ex['items'] and ex['items'].index('Multivariate Embedding…') > ex['items'].index('Multidimensional Scaling…'), True)

    # ---- the launch dialog, and the run with its progress
    r = await page.ev('''(async (M) => {
      SM.app.launch('embedding');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      const opts = [...dlg.querySelectorAll('.sm-launch-opts label')].map(l => [...l.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim());
      const method = [...dlg.querySelectorAll('.sm-launch-opts select')][0];
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (names) => { items.forEach(li => li.classList.remove('is-selected')); names.forEach((n, i) => items.find(x => x.textContent === n).dispatchEvent(new MouseEvent('mousedown', { bubbles: true, metaKey: i > 0 }))); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      pick(['m01']); role('Y, Columns').querySelector('.sm-btn').click();
      ok.click();
      const needTwo = dlg.querySelector('.sm-launch-msg').textContent;
      pick(M.slice(1)); role('Y, Columns').querySelector('.sm-btn').click();
      pick(['type (true)']); role('Color').querySelector('.sm-btn').click();
      const seen = [];
      const off = SM.engine.on('progress', (p) => seen.push([p.what, p.done, p.total]));
      const statusTexts = new Set();
      const mo = new MutationObserver(() => { const s = document.querySelector('.sm-emb-progress'); if (s) statusTexts.add(s.textContent); });
      mo.observe(document.body, { subtree: true, childList: true, characterData: true });
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      off(); mo.disconnect();
      return { roles, opts, methods: [...method.options].map(o => o.textContent), needTwo, seen, status: [...statusTexts], options: rep.spec.options,
               outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent), sk: SM.engine.versions['scikit-learn'] || null };
    })(%s)''' % json.dumps(M), timeout=600)
    check('the launch roles: Y, Columns, Color and By', r['roles'], ['Y, Columns', 'Color', 'By'])
    check('the launch options', r['opts'], ['Method', 'Dimensions', 'Perplexity', 'Iterations', 'Learning Rate', 'Initialization', 'Standardize Columns', 'Random Seed'])
    check('the method: t-SNE alone (UMAP needs numba)', r['methods'], ['t-SNE'])
    check('one column is not enough', 'at least 2' in r['needTwo'], True)
    check('the defaults reach the report', (r['options']['perplexity'], r['options']['iterations'], r['options']['learningRate'], r['options']['init'], r['options']['standardize'], r['options']['dimension']), (30, 1000, 'auto', 'pca', True, '2'))
    check('the report\'s outlines', r['outlines'], ['Multivariate Embedding', 't-SNE', 'Fit Details'])
    check('the first fit loaded scikit-learn 1.8.0', r['sk'], '1.8.0')
    prog = [s for s in r['seen'] if s[0] == 'tsne']
    check('progress events: the start and every 50 iterations to 1000', [s[1] for s in prog], [0] + list(range(50, 1001, 50)))
    check('... shown in the report while it runs', any('iteration 500 of 1000' in s for s in r['status']) and any('nearest neighbours' in s for s in r['status']), True)
    st = await page.ev(STATE)
    check('no errors or warnings in the report', (st['errors'], st['warnings']), ([], []))
    await shot(page, 'emb-01-report.png')

    # ---- the map against the engine
    mp = await page.ev(MAP)
    eng = await page.ev(ENGINE, timeout=600)
    check('one point per row, the rows the engine mapped', (mp['n'], mp['rows'] == eng['rows']), (900, True))
    check('the map is the engine\'s, point by point', max(max(abs(a - b[0]), abs(c - b[1])) for a, c, b in zip(mp['x'], mp['y'], eng['coords'])), 0.0)
    d = await details(page)
    check.near('Fit Details: the final KL divergence is the engine\'s', num(d['Final KL Divergence']), eng['kl'], tol=1e-6)
    check('... 1000 iterations, perplexity 30, the learning rate "auto" = max(900/48, 50) = 50, 900 rows, 12 columns, the PCA start', (d['Iterations'], d['Perplexity'], d['Learning Rate'], d['Rows'], d['Columns'], d['Initialization']), ('1000', '30', '50', '900', '12', 'PCA'))
    r = await page.ev('''((x, y) => {
      const t = SM.app.reports[SM.app.reports.length - 1].table; const ty = t.col('type (true)').values;
      const rows = SM.app.reports[SM.app.reports.length - 1].plots.find(p => /^t-SNE map/.test(p.opts.title)).rows[0];
      let same = 0;
      for (let i = 0; i < x.length; i++) { let best = -1, bd = Infinity; for (let j = 0; j < x.length; j++) if (j !== i) { const dd = (x[i] - x[j]) ** 2 + (y[i] - y[j]) ** 2; if (dd < bd) { bd = dd; best = j; } } if (ty[rows[best]] === ty[rows[i]]) same++; }
      return same / x.length;
    })''' + f'({json.dumps(mp["x"])}, {json.dumps(mp["y"])})')
    check(f'the map keeps the cell types apart: each row\'s nearest neighbour in the map is of its type ({r:.3f})', r > 0.95, True)
    check('the points are coloured by type (five colours, a legend of the types; not the rows\' colours)', (len(set(mp['colors'])), mp['legend'], mp['rowColors']), (5, [f'type {i}' for i in range(1, 6)], False))

    # ---- linking
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => /^t-SNE map/.test(p.opts.title));
      p._click({ points: [{ curveNumber: 0, pointNumber: 7 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[0][3], p.rows[0][11]]);
      const sp = p.box.data[0].selectedpoints;
      t.select([]);
      return { sel, want: [p.rows[0][7]], sp };
    })()''')
    check('a click on a point selects its row', r['sel'], r['want'])
    check('rows selected in the table light up their points', r['sp'], [3, 11])
    pos = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => /^t-SNE map/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      await new Promise(r => setTimeout(r, 300));
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      const gd = p.box, xa = gd._fullLayout.xaxis, ya = gd._fullLayout.yaxis;
      const xs = p.traces[0].x, ys = p.traces[0].y;
      let best = 0, bestD = -1;
      for (let k = 0; k < xs.length; k++) { let d = Infinity; for (let m = 0; m < xs.length; m++) if (m !== k) d = Math.min(d, (xs[k] - xs[m]) ** 2 + (ys[k] - ys[m]) ** 2); if (d > bestD) { bestD = d; best = k; } }
      const b = gd.getBoundingClientRect();
      return { x: b.left + xa._offset + xa.l2p(xs[best]), y: b.top + ya._offset + ya.l2p(ys[best]), row: p.rows[0][best] };
    })()''')
    await page.click(pos['x'], pos['y'])
    await asyncio.sleep(0.4)
    check('a mouse click on a point selects that row', await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()'), [pos['row']])
    await page.mouse('mouseMoved', 2, 2)
    await page.ev('SM.app.reports[SM.app.reports.length - 1].table.select([])')
    r = await page.ev(TRIANGLES)
    check('every red triangle opens, with its submenus', (r['errors'], r['triangles'], r['items'] > r['triangles'], r['subs'] > 0), ([], 2, True, True))

    # ---- Color By: the rows' colours, another column
    await page.ev(pick_js('t-SNE', ['Color By', 'Row Colors']))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const donor = t.col('donor').values;
      t.setColor([...Array(t.nrows).keys()].filter(r => donor[r] === 'A'), 3);
      await new Promise(r => setTimeout(r, 300));
      const p = rep.plots.find(p => /^t-SNE map/.test(p.opts.title));
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      const c = p.box.data[0].marker.color;
      const rows = p.rows[0];
      const ok = rows.every((r, k) => (donor[r] === 'A' ? c[k] === SM.util.colorOf(3) : c[k] !== SM.util.colorOf(3)));
      t.clearRowStates();
      return { ok, rowColors: p.rowColors, legend: p.traces.filter(t => t.showlegend).length };
    })()''')
    check('Color By Row Colors: the points take the rows\' colours (donor A coloured here)', (r['ok'], r['rowColors'], r['legend']), (True, True, 0))
    await page.ev(pick_js('t-SNE', ['Color By', 'donor']))
    mp = await page.ev(MAP)
    check('Color By donor: two colours and their legend', (len(set(mp['colors'])), mp['legend']), (2, ['A', 'B']))
    await page.ev(pick_js('t-SNE', ['Color By', 'type (true)']))

    # ---- Save Embedding
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      await (%s)('t-SNE', ['Save Embedding'], false, 0);
      await new Promise(r => setTimeout(r, 300));
      const a = t.col('t-SNE 1'), b = t.col('t-SNE 2');
      const p = rep.plots.find(p => /^t-SNE map/.test(p.opts.title));
      return { have: !!a && !!b, same: p.rows[0].every((r, k) => a.values[r] === p.traces[0].x[k] && b.values[r] === p.traces[0].y[k]), notes: a ? a.notes : '' };
    })()''' % PICK)
    check('Save Embedding: t-SNE 1 and t-SNE 2, the map\'s coordinates', (r['have'], r['same']), (True, True))
    check('... with a note of how they were made', 'perplexity 30' in r['notes'] and 'Multivariate Embedding' in r['notes'], True)

    # ---- the perplexity from the red triangle; Redo keeps it
    await page.ev(pick_form_js('*top*', ['Perplexity…'], '10'), timeout=600)
    d10 = await details(page)
    st = await page.ev(STATE)
    check('Perplexity… 10: the Fit Details say so, the KL divergence changes', (d10['Perplexity'], d10['Final KL Divergence'] != d['Final KL Divergence']), ('10', True))
    script = await page.ev('SM.app.reports[SM.app.reports.length - 1].pythonScript()')
    check('the Python script holds the TSNE call with perplexity 10', 'TSNE(n_components=2, perplexity=10.0' in script, True)
    await rerun(page)
    st = await page.ev(STATE)
    check('Redo keeps the perplexity', (st['options'].get('perplexity'), (await details(page))['Perplexity']), (10, '10'))
    await shot(page, 'emb-02-perplexity.png')

    # ---- three dimensions: in pairs without WebGL, and the turning plot
    await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; rep.spec.options.iterations = 400; rep.spec.options.perplexity = 30; })()''')
    await page.ev(pick_js('*top*', ['Dimensions', '3']), timeout=600)
    webgl = await page.ev('SM.report.hasWebGL()')
    mp = await page.ev(MAP)
    st = await page.ev(STATE)
    if not webgl:
        check('three dimensions without WebGL: the three pairs of axes, each linked, said so', (mp['title'], mp['traces'] >= 3, any('no WebGL' in n for n in st['notes'])), ('t-SNE map, three dimensions in pairs', True, True))
        r = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table; const p = rep.plots.find(p => /^t-SNE map/.test(p.opts.title));
          p.box.scrollIntoView({ block: 'center' });
          for (let n = 0; n < 50 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
          t.select([p.rows[0][5]]); const s = [0, 1, 2].map(i => p.box.data[i] ? p.box.data[i].selectedpoints : null); t.select([]); return s; })()''')
        check('... a table selection lights up the point in every pair', r, [[5], [5], [5]])
    d3 = await details(page)
    check('three dimensions: Fit Details say 3, 400 iterations', (d3['Dimensions'], d3['Iterations']), ('3', '400'))
    await page.ev(pick_js('t-SNE', ['3-D View', 'Turning Plot (needs WebGL)']))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => /^t-SNE map/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      p._click({ points: [{ curveNumber: 0, pointNumber: 7 }], event: {} });
      await new Promise(r => setTimeout(r, 200));
      const sel = t.selectedRows();
      const c = p.box.data[0].marker.color;
      const colors = [c[7], c[8]];
      const sizes = [p.box.data[0].marker.size[7], p.box.data[0].marker.size[8]];
      t.select([]);
      const r0 = p.rows[0][2];
      t.setState([r0], 'hidden', true);
      await new Promise(r => setTimeout(r, 200));
      const hidden = p.box.data[0].x[2];
      t.setState([r0], 'hidden', false);
      return { type: p.traces[0].type, n: p.rows[0].length, sel, want: [p.rows[0][7]], colors, sizes, hidden, legend: rep.body.querySelectorAll('.sm-emb-legend [role=listitem]').length, z: p.traces[0].z.length };
    })()''')
    check('the turning plot: scatter3d, a point per row', (r['type'], r['n'], r['z']), ('scatter3d', 900, 900))
    check('... a click selects the row, drawn larger in the selection colour, the others faded', (r['sel'], r['colors'][0], r['colors'][1].startswith('rgba('), r['sizes'][0] > r['sizes'][1]), (r['want'], '#d9822b', True, True))
    check('... a hidden row is not drawn', r['hidden'], None)
    check('... the colours of the types in a legend under it', r['legend'], 5)
    await page.ev(pick_js('*top*', ['Dimensions', '2']), timeout=600)

    # ---- many rows: ask first; more than 10 000: refused
    await page.ev('''(() => {
      const r = SM.util.rng('many rows');
      const n = 3500, cols = [];
      for (let j = 0; j < 4; j++) cols.push({ name: 'v' + j, dataType: 'numeric', values: Array.from({ length: n }, (_, i) => (i % 3) * 4 + r.normal()) });
      SM.app.addTable(new SM.Table({ name: 'Many', source: 'simulated', columns: cols }));
      const cols2 = [];
      for (let j = 0; j < 2; j++) cols2.push({ name: 'w' + j, dataType: 'numeric', values: Array.from({ length: 10001 }, () => r.normal()) });
      SM.app.addTable(new SM.Table({ name: 'Too many', source: 'simulated', columns: cols2 }));
    })()''')
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Many").id)')
    rep = await page.ev(open_report_js('embedding', {'y': ['v0', 'v1', 'v2', 'v3']}, {'iterations': 250}), timeout=300)
    st = await page.ev(STATE)
    check('3500 rows: the report asks first, with the time it takes, and fits nothing yet', (rep['outlines'], any('3,500 rows: t-SNE takes about' in w or '3500 rows: t-SNE takes about' in w for w in st['warnings'])), (['Multivariate Embedding', 't-SNE'], True))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const b = [...rep.body.querySelectorAll('.sm-emb-ask button')][0];
      const text = b.textContent;
      const done = new Promise(res => rep.on('done', res));
      b.click();
      await done;
      return { text, run: rep.spec.options.runLarge, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent) };
    })()''', timeout=900)
    check('... and runs when told (the answer kept with the report)', (r['text'], r['run'], r['outlines']), ('Run t-SNE on 3,500 rows' if '3,500' in r['text'] else 'Run t-SNE on 3500 rows', True, ['Multivariate Embedding', 't-SNE', 'Fit Details']))
    check('... all 3500 rows mapped', (await details(page))['Rows'].replace(',', ''), '3500')
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Too many").id)')
    rep = await page.ev(open_report_js('embedding', {'y': ['w0', 'w1']}, {}), timeout=300)
    check('10 001 rows: refused', any('at most 10000' in w for w in rep['warnings']), True)

    # ---- missing values; By; a project
    await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Cell profiles'); t.setCell(4, 'm03', NaN); SM.app.showTable(t.id); })()''')
    rep = await page.ev(open_report_js('embedding', {'y': M, 'color': ['type (true)']}, {'iterations': 300}), timeout=600)
    st = await page.ev(STATE)
    check('a row with a missing value is left out, and said so', (any('1 row with a missing value left out' in n for n in st['notes']), (await details(page))['Rows']), (True, '899'))
    # Bootstrap reruns t-SNE headless on resamples (rows drawn again, some twice)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const options = JSON.stringify(rep.spec.options), ncol = t.columns.length, plots = rep.plots.length;
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Fit Details');
      const kv = head.parentElement.querySelector('table.sm-kv');
      const res = await SM.bootstrap.run(kv, kv._rt.columns[1], { B: 2, seed: 3, show: false });
      const col = (n) => res.columns.find(c => c.name === n);
      return { names: res.columns.map(c => c.name).slice(0, 4), kl: col('Final KL Divergence').values, rows: col('Rows').values,
               options: JSON.stringify(rep.spec.options) === options, ncol: t.columns.length === ncol, plots: rep.plots.length === plots };
    })()''', timeout=900)
    check('Bootstrap of the Fit Details: a column per line, the report\'s first', r['names'], ['BootID', 'Final KL Divergence', 'Iterations', 'Perplexity'])
    check('... every resample mapped (a KL divergence each; the row with the missing value drawn 0, 1 or more times)', (all(isinstance(v, (int, float)) and v > 0 for v in r['kl']), r['rows'][0], all(894 <= v <= 900 for v in r['rows'][1:])), (True, 899, True))
    check('... and the reruns change nothing in the report or the table', (r['options'], r['ncol'], r['plots']), (True, True, True))
    rep = await page.ev(open_report_js('embedding', {'y': M, 'by': ['donor']}, {'iterations': 300}), timeout=900)
    heads = [o for o in rep['outlines'] if o.startswith('Multivariate Embedding')]
    check('By donor: one map per donor', heads, ['Multivariate Embedding donor=A', 'Multivariate Embedding donor=B'])
    r = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table; const don = t.col('donor').values; const m3 = t.col('m03').values;
      return { maps: rep.plots.filter(p => /^t-SNE map/.test(p.opts.title)).map(p => p.rows[0].length), a: don.filter((v, i) => v === 'A' && Number.isFinite(m3[i])).length, b: don.filter((v, i) => v === 'B' && Number.isFinite(m3[i])).length }; })()''')
    check('each donor\'s map holds its own rows', r['maps'], [r['a'], r['b']])
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.filter(r => r.platform.id === "embedding")[0]))')
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.filter(r => r.platform.id === 'embedding')[0]; const t = rep.table;
      const d0 = new Promise(res => rep.on('done', res)); rep.run(); await d0;
      const before = rep.plots.find(p => /^t-SNE map/.test(p.opts.title)).traces[0].x.slice(0, 50);
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const p = back.plots.find(p => /^t-SNE map/.test(p.opts.title));
      const cc = back.table.col(back.spec.options.colorCol);
      const out = { newTable: back.table !== t, perplexity: back.spec.options.perplexity, colorCol: cc ? cc.name : null, remapped: back.spec.options.colorCol !== rep.spec.options.colorCol,
                    same: p ? p.traces[0].x.slice(0, 50).every((v, k) => v === before[k]) : false, errors: back.body.querySelectorAll('.sm-ob-error').length };
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })()''', timeout=900)
    check('an opened project has its own table, the perplexity, and the Color By column by its new id', (r['newTable'], r['perplexity'], r['colorCol'], r['remapped']), (True, 30, 'type (true)', True))
    check('... and draws the same map without errors', (r['same'], r['errors']), (True, 0))

    # ---- the (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-embedding"); const row = document.getElementById("help-p-embedding"); return row ? row.textContent : null; })()')
    check('the platform has its line in Help, with scikit-learn\'s TSNE, and says UMAP is not available', bool(helps) and 'sklearn.manifold.TSNE' in helps and 'UMAP' in helps, True)
    topics = await page.ev('Object.keys(SM.platforms.get("embedding").topics)')
    check('its topics', sorted(topics), sorted(['p:embedding', 'emb:map', 'emb:details', 'emb:large']))
    umap = await page.ev('SM.platforms.get("embedding").topics["p:embedding"].sections.find(s => s.heading === "UMAP").text')
    check('the (i) says why UMAP is not here', 'numba' in umap, True)

    # ---- the (i) explains every input: the launch dialog, the red triangle's forms, the Run button
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Cell profiles").id)')
    await dialog_help(page, "SM.app.launch('embedding')", 'embedding', 'Multivariate Embedding')
    first = 'SM.app.reports.filter(r => r.platform.id === "embedding")[0]'
    for item, field in (('Perplexity…', 'Perplexity (about the number of neighbours of each row)'), ('Iterations…', 'Iterations (at least 250)'),
                        ('Learning Rate…', 'Learning rate (a positive number, or auto)'), ('Random Seed…', "Seed (empty: the report's own)")):
        await form_help(page, f"await clickPath({first}, '*top*', [{json.dumps(item)}]);", [field], item)
    large = await page.ev('SM.info.get("emb:large")')
    check('Many rows\' (i) says what its Run t-SNE button does', [c[0] for sec in large['sections'] for c in sec.get('choices', [])], ['Run t-SNE on … rows'])

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.filter(r => r.platform.id === "embedding")[0]))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2.5)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => r.platform.id === 'embedding'); return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)) }; })()''')
    check('the dark theme redraws the reports without errors', st['errors'], [])
    await shot(page, 'emb-03-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports.filter(r => r.platform.id === "embedding")[0]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()', timeout=600)
    await asyncio.sleep(1.0)
    r = await page.ev('''(() => {
      const rep = SM.app.reports.filter(r => r.platform.id === "embedding")[0];
      const body = rep.body.getBoundingClientRect();
      const boxes = rep.plots.filter(p => p.drawn).map(p => p.box.getBoundingClientRect().right);
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length, body: rep.body.scrollWidth <= rep.body.clientWidth + 1 };
    })()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the map fits the phone\'s width, the report does not scroll sideways', (r['plots'], r['n'] >= 1, r['body']), (True, True, True))
    await shot(page, 'emb-04-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
