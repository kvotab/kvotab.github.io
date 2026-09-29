#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Multivariate Methods > Partial Least Squares.

The simulated Spectra example opens from the URL and File > Examples; the
platform sits between Discriminant and Multiple Correspondence Analysis in
Analyze > Multivariate Methods; the first call loads scikit-learn; the
launch dialog has JMP's roles and options with their defaults; the report
has JMP's outlines and its Cross Validation, Percent Variation Explained,
coefficients and VIP are the engine's numbers; the Model Comparison Summary
counts the VIPs above the threshold; X-Y score points select their rows and
table selections highlight them; every red triangle opens; Model Launch's Go
adds a fit and Remove Fit takes it away; the red triangle's plots (VIP vs
Coefficients, Loadings, Distances, T², Percent Variation) and the profiler
draw the engine's numbers, and Set VIP Threshold changes the count; Save
Predicteds, X Scores and Y Scores make the engine's columns; a Validation
column, Centering and Scaling off and By work; a project keeps the fits with
the column ids remapped; Bootstrap reruns the report headless; the Python
script holds the scikit-learn calls; every (i) has a topic; the launch
dialog's (i) gives every role and option its help, and the Model Launch's
and Set VIP Threshold's (i) each of their fields; dark theme and phone
width.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-pls.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import importlib.util
import json
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
WAVES = [f'nm {1100 + 40 * j}' for j in range(30)]
YS = ['A (%)', 'B (%)']


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('*', '').replace('<', ''))


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
           warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)), options: rep.spec.options,
           notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent) };
})()
'''

# The engine's own fit of a fit of the last report (the same payload the page sends).
ENGINE = '''
(async (i, extra) => {
  const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table; const o = rep.spec.options;
  const fits = o.fits || [{ method: o.method || 'kfold', folds: o.folds ?? 7, holdback: o.holdback ?? 0.2, factors: o.factors ?? 15 }];
  const f = fits[i || 0];
  const names = (k) => (rep.spec.roles[k] || []).map(id => t.col(id).name);
  const payload = { table: t.id, rows: null, y: names('y'), x: names('x'), validation: names('validation')[0] || null, method: f.method, folds: f.folds, holdback: f.holdback, factors: f.factors,
                    center: o.center !== false, scale: o.scale !== false, seed: o.seed ? Number(o.seed) : o.seedDrawn, alpha: o.alpha || 0.05, ...(extra || {}) };
  if (extra && extra.what) { delete payload.alpha; return await SM.engine.call('pls.save', payload, t); }
  return await SM.engine.call('pls.fit', payload, t);
})
'''


def engine_js(i=0, extra=None):
    return f'({ENGINE})({i}, {json.dumps(extra or {})})'


async def triangles(page, name, least):
    r = await page.ev(TRIANGLES)
    ok = isinstance(r, dict) and not r['errors'] and r['triangles'] >= least and r['items'] > r['triangles']
    check(f'every red triangle of {name} opens, with its submenus', ok, True)
    if not ok:
        print('   ', r)


async def rerun(page):
    await page.ev('(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')



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


def hline(ax, y, dash=None):
    """A horizontal line of the figure at y (dashed when dash)."""
    return any(len(q['y']) == 2 and close(q['y'], [y, y], 1e-9) and (dash is None or q['ls'] == '--') for q in ax['lines'])


def pls_compare(lab, g, F):
    t = g['label']
    ax = F['axes'][0]
    if t == 'Root Mean PRESS by number of factors':
        UP.check_lines(check, lab, g, F)
        ring = g['traces'][1]
        check(f'{lab}: the minimum ringed', find_line(ax, ring['x'], ring['y'], rel=1e-9) is not None, True)
    elif t.startswith('X-Y scores of factor') or t.startswith('Distance to the') or t == 'T² by row':
        pts = [tr for tr in g['traces'] if 'markers' in (tr.get('mode') or '')]
        check(f'{lab}: a set of points per set', len(ax['scatter']), len(pts))
        for sc, tr in zip(ax['scatter'], pts):
            check.near(f'{lab}: {tr["name"]}: every row at its values', maxdiff(UP.flat(sc['xy']), UP.flat(UP.curve_pts(tr))), 0, 1e-9)
            check(f'{lab}: {tr["name"]}: in the set\'s colour', sc['colors'][0][:7], tr['mcolor'])
        for tr in g['traces']:
            if tr.get('mode') == 'lines':
                check(f'{lab}: the dotted inner relation', find_line(ax, tr['x'], tr['y'], rel=1e-9) is not None, True)
        for sh in g['shapes']:
            check(f'{lab}: the dashed limit', hline(ax, sh['y0'], '--'), True)
        check(f'{lab}: the legend (when there are several sets)', F['legend'], [tr['name'] for tr in pts] if g['showlegend'] else [])
        UP.check_titles(check, lab, g, F)
    elif t in ('X Effect', 'Y Effect'):
        bar = [tr for tr in g['traces'] if tr.get('type') == 'bar'][0]
        check.near(f'{lab}: a bar per factor, its percent', maxdiff([b['h'] for b in ax['bars']], bar['y']), 0, 1e-9)
        check(f'{lab}: the percent scale', close(ax['ylim'], g['axes']['y']['range'], 1e-12), True)
        UP.check_lines(check, lab, g, F)
    elif t == 'Variable importance':
        tr = g['traces'][0]
        check.near(f'{lab}: each X\'s VIP', maxdiff(ax['lines'][0]['y'], tr['y']), 0, 1e-9)
        check(f'{lab}: the points grey below the threshold', [c[:7] for c in ax['scatter'][0]['colors']], tr['mcolor'])
        check(f'{lab}: the X\'s named in their order', [x for x in ax['xticklabels'] if x], tr['x'])
        check(f'{lab}: the dashed threshold', hline(ax, g['shapes'][0]['y0'], '--'), True)
        UP.check_titles(check, lab, g, F)
    elif t.startswith('VIP vs coefficients for '):
        tr = g['traces'][0]
        check.near(f'{lab}: each X at its coefficient and VIP', maxdiff(UP.flat(ax['scatter'][0]['xy']), UP.flat(UP.curve_pts(tr))), 0, 1e-9)
        check(f'{lab}: each named', [q['s'] for q in ax['texts']], tr['text'])
        check(f'{lab}: the range, symmetric about 0; the dashed threshold', (close(ax['xlim'], g['axes']['x']['range'], 1e-12), hline(ax, g['shapes'][0]['y0'], '--')), (True, True))
        UP.check_titles(check, lab, g, F)
    elif t in ('X Loadings', 'Y Loadings'):
        lines = [q for q in ax['lines'] if q['label'].startswith('Factor ')]
        check(f'{lab}: a line per factor', len(lines), len(g['traces']))
        for q, tr in zip(lines, g['traces']):
            check.near(f'{lab}: {tr["name"]}: its loadings, in its colour', maxdiff(q['y'], tr['y']) + (0 if q['color'][:7] == tr['color'] else 1), 0, 1e-9)
        check(f'{lab}: the names, the legend', ([x for x in ax['xticklabels'] if x], F['legend']), (g['traces'][0]['x'], [tr['name'] for tr in g['traces']]))
        UP.check_titles(check, lab, g, F)
    else:
        check(f'{lab}: a graph this test knows', t, None)


async def charts(page):
    """Every graph of Partial Least Squares' reports: its block under it, run in the page, its figure the
    graph's (the model refitted in the block: the cross validation from the seed, the scores, VIP, the
    loadings, the distances and T²)."""
    await page.ev(GRAPHS_JS)
    await page.ev(UP.PM_JS)
    await page.ev('__gr.idle()')
    tbl = "SM.app.tables.find((t) => t.name === 'Spectra')"
    await page.ev(f'SM.app.showTab(SM.app.tabOf({tbl}))')
    await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Spectra'); const g = SM.util.rng('pls sets');
      if (!t.col('set')) t.addColumn({ name: 'set', dataType: 'numeric', values: t.col('sample').values.map(() => { const u = g.u(); return u < 0.6 ? 0 : u < 0.85 ? 1 : 2; }) });
      if (!t.col('batch')) t.addColumn({ name: 'batch', dataType: 'character', values: t.col('sample').values.map((_, i) => (i % 2 ? 'odd' : 'even')) }); })()''')
    last = 'SM.app.reports.at(-1)'
    every = {'pctPlots': True, 'vipCoef': True, 'loadings': True, 'distance': True, 't2': True}
    specs = [
        ('A and B on the 30 wavelengths, KFold, every graph, VIP threshold 1', {'y': YS, 'x': WAVES}, {**every, 'factors': 8, 'vipThreshold': 1.0, 'seed': '4'}),
        ('A on 10 wavelengths, a Validation column', {'y': ['A (%)'], 'x': WAVES[:10], 'validation': ['set']}, {**every, 'factors': 6}),
        ('not centred or scaled, as many factors as X\'s (no DModX)', {'y': YS, 'x': WAVES[:3]}, {**every, 'method': 'none', 'factors': 3, 'center': False, 'scale': False}),
    ]
    total = 0
    for label, roles, opts in specs:
        r = await page.ev(open_report_js('pls', roles, opts), timeout=900)
        check(f'charts: {label}: no errors', r['errors'], [])
        n, _ = await UP.chart_blocks(page, check, label, tbl, last, pls_compare)
        total += n
        await page.ev(f'SM.app.closeReport({last})')
    # By batch, rows excluded, Holdback: the blocks keep the group's rows and draw its sets
    out = [2, 5, 11]
    await page.ev(f'{tbl}.setState({out}, "excluded", true)')
    r = await page.ev(open_report_js('pls', {'y': YS, 'x': WAVES[:8], 'by': ['batch']}, {'method': 'holdback', 'holdback': 0.25, 'distance': True, 't2': True, 'seed': '6'}), timeout=900)
    check('charts: By batch, rows excluded, Holdback: no errors', r['errors'], [])
    n, _ = await UP.chart_blocks(page, check, 'By batch, rows excluded, Holdback', tbl, last, pls_compare)
    total += n
    await page.ev(f'SM.app.closeReport({last})')
    await page.ev(f'{tbl}.setState({out}, "excluded", false)')
    check('charts: the blocks ran and drew the page\'s graphs', total >= 40, True)


async def main():
    page = await open_page(f'{BASE}/smui.html?example=spectra', height=1200)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "pls").map(f => f.module + ": " + f.error)')
    check('pls.py imports in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])
    check('scikit-learn is not loaded at the start', await page.ev('(SM.engine.versions || {})["scikit-learn"] || null'), None)

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const file = SM.app.menuItems('File');
      const exs = file.find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const an = SM.app.menuItems('Analyze');
      const mm = an.find(i => i.label === 'Multivariate Methods');
      const items = (typeof mm.submenu === 'function' ? mm.submenu() : mm.submenu).filter(i => !i.separator).map(i => i.label);
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), about: SM.io.EXAMPLES.spectra.about, inFile: labels.includes(SM.io.EXAMPLES.spectra.label), items };
    })()''')
    check('?example=spectra opens the simulated spectra', (ex['name'], ex['rows'], ex['cols']), ('Spectra', 60, ['sample'] + YS + ['water (%)'] + WAVES))
    check('it is simulated, and its notes say how', ex['about'].startswith('Simulated') and 'Gaussian bands' in ex['about'], True)
    check('it is in File > Examples', ex['inFile'], True)
    it = ex['items']
    check('Analyze > Multivariate Methods lists Partial Least Squares after Discriminant, before Multiple Correspondence Analysis (JMP\'s order)',
          it.index('Discriminant…') < it.index('Partial Least Squares…') < it.index('Multiple Correspondence Analysis…'), True)

    # ---- the launch dialog
    r = await page.ev('''(async (ys, xs) => {
      SM.app.launch('pls');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const down = (name, shift) => items.find(x => x.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true, shiftKey: !!shift }));
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      const opts = [...dlg.querySelectorAll('.sm-launch-opts label')].map(l => { const i = l.querySelector('input, select'); return [[...l.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim(), i.type === 'checkbox' ? i.checked : i.value]; });
      down(ys[0]); down(ys[1], true); role('Y').querySelector('.sm-btn').click();
      down(ys[0]); role('X').querySelector('.sm-btn').click();
      ok.click();
      const both = dlg.querySelector('.sm-launch-msg').textContent;
      for (let li; (li = role('X').querySelector('li'));) li.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      down(xs[0]); down(xs[xs.length - 1], true); role('X').querySelector('.sm-btn').click();
      const nx = role('X').querySelectorAll('li').length;
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { roles, opts, both, nx, options: rep.spec.options, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent), sk: SM.engine.versions['scikit-learn'] };
    })(%s, %s)''' % (json.dumps(YS), json.dumps(WAVES)), timeout=300)
    if not isinstance(r, dict):
        print('   ', r)
    check('the launch dialog\'s roles: Y, X, Validation, By', r['roles'], ['Y', 'X', 'Validation', 'By'])
    opts = dict((k, v) for k, v in r['opts'])
    check('its options and defaults: Centering, Scaling, NIPALS, KFold with 7 folds, Holdback 0.2, 15 factors',
          [opts.get(k) for k in ('Centering', 'Scaling', 'Method', 'Validation Method', 'Number of Folds', 'Holdback Portion', 'Initial Number of Factors', 'Random Seed')],
          [True, True, 'nipals', 'kfold', '7', '0.2', '15', ''])
    check('a column in both Y and X is refused', 'both a Y and an X' in r['both'], True)
    check('the 30 wavelengths are the X\'s', r['nx'], 30)
    st = await page.ev(STATE)
    check('no errors in the report', st['errors'], [])
    res = await page.ev(engine_js())
    k = res['factors']
    check('the report\'s outlines', st['outlines'][:10], ['Partial Least Squares', 'Model Launch', 'Model Comparison Summary', f'NIPALS Fit with {k} Factors', 'KFold Cross Validation with K=7 and Method=NIPALS',
                                                         'X-Y Scores Plots', 'Percent Variation Explained', 'Model Coefficients for Centered and Scaled Data', 'Model Coefficients for Original Data', 'Variable Importance Plot'])
    check('the first call loads scikit-learn 1.8.0', r['sk'], '1.8.0')
    await shot(page, 'pls-01-report.png')

    # ---- the numbers against the engine's
    cv = await page.ev(table_under_js('KFold Cross Validation with K=7 and Method=NIPALS', 0))
    check('Cross Validation\'s columns', cv[0], ['Number of Factors', 'Root Mean PRESS', 'van der Voet T²', 'Prob > van der Voet T²'])
    check('a line for 0 to 15 factors', [int(row[0]) for row in cv[1:]], list(range(16)))
    check('Root Mean PRESS: the engine\'s, to 5 decimals', all(abs(num(row[1]) - e['rmpress']) < 6e-6 for row, e in zip(cv[1:], res['cv']['rows'])), True)
    check('Prob > van der Voet T²: the engine\'s', all(abs(num(row[3]) - e['p']) < 6e-5 or (row[3].startswith('<') and e['p'] < 1e-4) for row, e in zip(cv[1:], res['cv']['rows'])), True)
    check('the fit takes the number with the minimum Root Mean PRESS', k, max(1, min(range(16), key=lambda a: res['cv']['rows'][a]['rmpress'])))
    check('the spectra\'s A, B, water and baseline need at least 4 factors', k >= 4, True)
    pv = await page.ev(table_under_js('Percent Variation Explained', 0))
    check('Percent Variation Explained: a line per factor with X and Y effects', (pv[0], len(pv) - 1), (['Number of Factors', 'X Effect', 'Cumulative X', 'Y Effect', 'Cumulative Y'], k))
    check.near('... Cumulative Y at the last factor is the engine\'s', num(pv[-1][4]), round(res['percent'][-1]['cumy'], 4), tol=1e-9)
    check('... and above 99%: the concentrations are predicted', res['percent'][-1]['cumy'] > 99, True)
    cs = await page.ev(table_under_js('Model Coefficients for Centered and Scaled Data', 0))
    check('the centred and scaled coefficients: a row per X, a column per Y', (cs[0], len(cs) - 1), (['Term'] + YS, 30))
    check.near('... the engine\'s', max(abs(num(cs[1 + j][1 + kk]) - res['coef'][j][kk]) for j in range(30) for kk in range(2)), 0.0, tol=1e-6)
    co = await page.ev(table_under_js('Model Coefficients for Original Data', 0))
    check.near('the original coefficients and intercepts: the engine\'s', max(abs(num(co[1][1]) - res['intercept'][0]) / max(1, abs(res['intercept'][0])), max(abs(num(co[2 + j][2]) - res['coef_orig'][j][1]) / max(1, abs(res['coef_orig'][j][1])) for j in range(30))), 0.0, tol=1e-6)
    vp = await page.ev(table_under_js('Variable Importance Plot', 0))
    check('VIP: the engine\'s, to 4 decimals', all(abs(num(row[1]) - v) < 6e-5 for row, v in zip(vp[1:], res['vip'])), True)
    sm = await page.ev(table_under_js('Model Comparison Summary', 0))
    check('Model Comparison Summary: JMP\'s columns', sm[0], ['Method', 'Validation Method', 'Number of rows', 'Number of factors', 'Percent Variation Explained for Cumulative X', 'Percent Variation Explained for Cumulative Y', 'Number of VIP>0.8'])
    check('... its line: NIPALS, KFold, 60 rows, the factors, the VIPs above 0.8', (sm[1][0], sm[1][2], int(sm[1][3]), int(sm[1][6])), ('NIPALS', '60', k, sum(v > 0.8 for v in res['vip'])))

    # ---- linking
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => p.opts.title === 'X-Y scores of factor 1');
      p.box.scrollIntoView({ block: 'center' });
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      p._click({ points: [{ curveNumber: 0, pointNumber: 5 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[0][2], p.rows[0][9]]);
      const sp = p.box.data[0].selectedpoints;
      t.select([]);
      return { sel, want: [p.rows[0][5]], sp, rows: p.rows[0].length, x0: p.traces[0].x[0] };
    })()''')
    check('a click on an X-Y score point selects its row', r['sel'], r['want'])
    check('rows selected in the table highlight their points', r['sp'], [2, 9])
    check.near('the points are the engine\'s X scores', r['x0'], res['scores']['t'][0][0], tol=1e-12)
    await triangles(page, 'the report', 2)

    # ---- Model Launch: Go adds a fit, Remove Fit takes it away
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Model Launch');
      const box = head.parentElement;
      const vm = box.querySelector('select[aria-label="Validation Method"]');
      vm.value = 'none'; vm.dispatchEvent(new Event('change'));
      const nf = box.querySelector('input[aria-label="Initial Number of Factors"]');
      nf.value = '3';
      const foldsHidden = box.querySelector('input[aria-label="Number of Folds"]').closest('label').hidden;
      const done = new Promise(res => rep.on('done', res));
      [...box.querySelectorAll('button')].find(b => b.textContent === 'Go').click();
      await done;
      return { fits: rep.spec.options.fits, heads: [...rep.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent), foldsHidden };
    })()''')
    check('Model Launch: None hides the folds', r['foldsHidden'], True)
    check('Go adds a fit with its settings', (len(r['fits']), r['fits'][1]['method'], r['fits'][1]['factors']), (2, 'none', 3))
    check('... its outline beside the first', [h for h in r['heads'] if h.startswith('NIPALS Fit')], [f'NIPALS Fit with {k} Factors', 'NIPALS Fit with 3 Factors'])
    sm = await page.ev(table_under_js('Model Comparison Summary', 0))
    check('... and a second line in the Model Comparison Summary', [(row[1], row[3]) for row in sm[1:]], [('KFold, 7 folds', str(k)), ('None', '3')])
    res3 = await page.ev(engine_js(1))
    check.near('... the engine\'s 3-factor fit', num(sm[2][5]), round(res3['percent'][-1]['cumy'], 4), tol=1e-9)
    await rerun(page)
    st = await page.ev(STATE)
    check('Redo keeps the two fits', len(st['options']['fits']), 2)
    await page.ev(pick_js('NIPALS Fit with 3 Factors', ['Remove Fit']))
    st = await page.ev(STATE)
    check('Remove Fit takes it away', ([h for h in st['outlines'] if h.startswith('NIPALS Fit')], len(st['options']['fits'])), ([f'NIPALS Fit with {k} Factors'], 1))

    # ---- the red triangle of a fit
    fit = f'NIPALS Fit with {k} Factors'
    for item in ('VIP vs Coefficients Plots', 'Loading Plots', 'Distance Plots', 'T Square Plot', 'Percent Variation Plots', 'Profiler'):
        await page.ev(pick_js(fit, [item]))
    st = await page.ev(STATE)
    check('the red triangle adds VIP vs Coefficients, Loading, Distance and T Square plots and the Profiler', all(o in st['outlines'] for o in ('VIP vs Coefficients Plots', 'Loading Plots', 'Distance Plots', 'T Square Plot', 'Prediction Profiler')), True)
    check('... without errors', st['errors'], [])
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const byTitle = (s) => rep.plots.find(p => p.opts.title === s);
      const d = byTitle('Distance to the Y model by row'), t2 = byTitle('T² by row'), vc = byTitle('VIP vs coefficients for A (%)'), xl = byTitle('X Loadings'), pv = byTitle('X Effect');
      return { dy: d.traces[0].y.slice(0, 3), drows: d.rows[0].slice(0, 3), t2: t2.traces[0].y.slice(0, 3), ucl: t2.userLayout.shapes[0].y0, vcx: vc.traces[0].x.slice(0, 3), vcy: vc.traces[0].y.slice(0, 3),
               xl: xl.traces.length, xl0: xl.traces[0].y.slice(0, 2), pv: pv.traces[0].y.length };
    })()''')
    check.near('Distance Plots: DModY of the rows, the engine\'s', max(abs(a - b) for a, b in zip(r['dy'], res['dist']['dmody'][:3])), 0.0, tol=1e-12)
    check('... linked to their rows', r['drows'], res['dist']['rows'][:3])
    check.near('T Square Plot: T² and its limit, the engine\'s', max(abs(a - b) for a, b in zip(r['t2'], res['dist']['t2'][:3])) + abs(r['ucl'] - res['ucl']), 0.0, tol=1e-12)
    check.near('VIP vs Coefficients: each X\'s centred and scaled coefficient and VIP', max(abs(r['vcx'][j] - res['coef'][j][0]) + abs(r['vcy'][j] - res['vip'][j]) for j in range(3)), 0.0, tol=1e-12)
    check('Loading Plots: a line per factor', r['xl'], k)
    check.near('... the X loadings', max(abs(r['xl0'][j] - res['x_loadings'][j][0]) for j in range(2)), 0.0, tol=1e-12)
    check('Percent Variation Plots: a bar per factor', r['pv'], k)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Prediction Profiler');
      const vals = [...head.parentElement.querySelectorAll('.sm-prof-val')].map(e => e.textContent);
      const o = rep.spec.options; const f = o.fits[0];
      const pr = await SM.engine.call('pls.profile', { table: t.id, rows: null, y: ['A (%%)', 'B (%%)'], x: %s, validation: null, method: f.method, folds: f.folds, holdback: f.holdback, factors: f.factors, center: true, scale: true, seed: o.seedDrawn }, t);
      return { vals, cur: pr.responses.map(r => r.current.pred), names: pr.responses.map(r => r.name) };
    })()''' % json.dumps(WAVES))
    check('the profiler: a row per Y', r['names'], YS)
    check.near('... the engine\'s predictions at the X\'s means', max(abs(num(v) - c) for v, c in zip(r['vals'], r['cur'])), 0.0, tol=1e-5)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await (%s)('%s', ['Set VIP Threshold…'], false, 0);
      for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
      const d = [...document.querySelectorAll('.sm-dialog')].pop();
      d.querySelector('.sm-form input').value = '1';
      const done = new Promise(res => rep.on('done', res));
      d.querySelector('.sm-dialog-foot .primary').click();
      await done;
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Model Comparison Summary');
      const tr = [...head.parentElement.querySelectorAll('table.sm-rt tr')].map(tr => [...tr.children].map(c => c.textContent));
      return { label: tr[0][6], count: tr[1][6] };
    })()''' % (PICK, fit))
    check('Set VIP Threshold 1: the summary counts the VIPs above 1', (r['label'], int(r['count'])), ('Number of VIP>1', sum(v > 1 for v in res['vip'])))
    await shot(page, 'pls-02-options.png')

    # ---- Save Columns
    r = await page.ev('''(async (fit) => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      for (const it of ['Save Predicteds', 'Save X Scores', 'Save Y Scores']) { await (%s)(fit, ['Save Columns', it], false, 0); await new Promise(r => setTimeout(r, 700)); }
      const eng = async (what) => await (%s)(0, { what });
      const pred = await eng('pred'), xs = await eng('xscores'), ys = await eng('yscores');
      const same = (sv, names) => names.every((nm, k) => { const c = t.col(nm); return c && sv.rows.every((r, i) => Math.abs(c.values[r] - sv.values[k][i]) < 1e-12); });
      return { pred: same(pred, pred.names), xs: same(xs, xs.names), ys: same(ys, ys.names), names: [pred.names, xs.names.length, ys.names.length] };
    })(%s)''' % (PICK, ENGINE, json.dumps(fit)))
    check('Save Predicteds: Predicted A (%) and B (%), the engine\'s', (r['names'][0], r['pred']), (['Predicted A (%)', 'Predicted B (%)'], True))
    check('Save X Scores and Y Scores: a column per factor, the engine\'s', (r['names'][1], r['names'][2], r['xs'], r['ys']), (k, k, True, True))
    script = await page.ev('SM.app.reports[SM.app.reports.length - 1].pythonScript()')
    check('the Python script holds the scikit-learn calls and the helpers', all(s in script for s in ('PLSRegression(', 'def pls_fit(', 'def van_der_voet(', 'def cv_residuals(', 'KFold(')), True)

    # ---- Bootstrap of VIP reruns the report headless
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'pls');
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Variable Importance Plot');
      const tbl = head.parentElement.querySelector('table.sm-rt');
      const t = await SM.bootstrap.run(tbl, tbl._rt.columns.find(c => c.label === 'VIP'), { B: 6, seed: 2, show: false });
      const v = t.col('nm 1100').values;
      return { cols: t.columns.map(c => c.name).slice(0, 3), n: t.nrows, first: v[0], finite: v.every(Number.isFinite), spread: Math.max(...v) - Math.min(...v) };
    })()''', timeout=900)
    check('Bootstrap of VIP: a column per X, a row per sample', (r['cols'], r['n']), (['BootID', 'nm 1100', 'nm 1140'], 7))
    check('... sample 0 is the report, the resamples refit', (abs(r['first'] - res['vip'][0]) < 1e-9, r['finite'], r['spread'] > 0), (True, True, True))

    # ---- a Validation column, Centering and Scaling off, By
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Spectra").id)')
    await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Spectra'); const g = SM.util.rng('pls sets');
      if (!t.col('set')) t.addColumn({ name: 'set', dataType: 'numeric', values: t.col('sample').values.map(() => { const u = g.u(); return u < 0.6 ? 0 : u < 0.85 ? 1 : 2; }) });
      if (!t.col('batch')) t.addColumn({ name: 'batch', dataType: 'character', values: t.col('sample').values.map((_, i) => (i % 2 ? 'odd' : 'even')) }); })()''')
    rep = await page.ev(open_report_js('pls', {'y': YS, 'x': WAVES, 'validation': ['set']}, {'factors': 8}), timeout=300)
    check('a Validation column: its cross validation, no errors', ('Validation Column Cross Validation with Method=NIPALS' in rep['outlines'], rep['errors']), (True, []))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const box = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Model Launch').parentElement;
      const vm = box.querySelector('select[aria-label="Validation Method"]');
      const res = await (%s)(0);
      return { vm: [vm.value, vm.disabled], sets: res.sets, method: res.method, n: res.n_train };
    })()''' % ENGINE)
    check('... Model Launch shows it, fixed', r['vm'], ['column', True])
    set_counts = await page.ev('(() => { const v = SM.app.tables.find(t => t.name === "Spectra").col("set").values; return [0, 1, 2].map(k => v.filter(x => x === k).length); })()')
    check('... the training rows fit the model, the validation rows choose', (r['method'], [r['sets']['Training'], r['sets']['Validation'], r['sets']['Test']], r['n']), ('column', set_counts, set_counts[0]))
    await page.ev(pick_js(rep['outlines'][3], ['Distance Plots']))
    r = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => p.opts.title === 'Distance to the Y model by row'); return p.traces.map(t => [t.name, t.x.length]); })()''')
    check('... the distances of the training, validation and test rows, each in its own markers', r, [['Training', set_counts[0]], ['Validation', set_counts[1]], ['Test', set_counts[2]]])
    rep = await page.ev(open_report_js('pls', {'y': ['A (%)'], 'x': WAVES}, {'center': False, 'scale': False, 'method': 'none', 'factors': 5}), timeout=300)
    co = await page.ev(table_under_js('Model Coefficients for Original Data', 0))
    st = await page.ev(STATE)
    check('Centering and Scaling off: said so, and no intercept', (any('not centred and not scaled' in t for t in st['notes']), num(co[1][1]), rep['errors']), (True, 0.0, []))
    rep = await page.ev(open_report_js('pls', {'y': YS, 'x': WAVES, 'by': ['batch']}, {'method': 'loo', 'factors': 6}), timeout=600)
    check('By batch: one analysis per group, Leave-One-Out', ([o for o in rep['outlines'] if o.startswith('Partial Least Squares')], 'Leave-One-Out Cross Validation with Method=NIPALS' in rep['outlines']),
          (['Partial Least Squares batch=even', 'Partial Least Squares batch=odd'], True))
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const tbls = [...rep.body.querySelectorAll('table.sm-rt')].filter(t => t.dataset.rtKey === 'plssummary');
      return { n: tbls.length, groups: tbls.map(t => t.dataset.group), rows: SM.report.combineRT(tbls, 'x').nrows, each: tbls.map(t => t._rt.rows[0].n) };
    })()''')
    check('each group has its summary, which combine into one table; each fits its own 30 rows', (r['n'], r['groups'], r['rows'], r['each']), (2, ['batch=even', 'batch=odd'], 2, [30, 30]))

    # ---- a project keeps the fits, the column ids remapped
    r = await page.ev('''(async (ys, xs) => {
      const t = SM.app.tables.find(t => t.name === 'Spectra');
      const rep = SM.app.openReport(SM.platforms.get('pls'), { roles: { y: ys.map(n => t.col(n).id), x: xs.map(n => t.col(n).id) },
        options: { seed: '4', fits: [{ id: 'f1', method: 'kfold', folds: 5, holdback: 0.2, factors: 8 }, { id: 'f2', method: 'none', folds: 7, holdback: 0.2, factors: 2 }], 'f2|vipCoef': true, 'f1|xyScores': false, 'f2|xyScores': false } }, t);
      await new Promise(res => rep.on('done', res));
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      const heads0 = [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
      SM.app.closeReport(rep);
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const out = { newTable: back.table !== t, fits: back.spec.options.fits.length, heads: [...back.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent), heads0,
                    errors: [...back.body.querySelectorAll('.sm-ob-error')].length, x: (back.spec.roles.x || []).map(id => back.table.col(id) && back.table.col(id).name) };
      SM.app.closeReport(back);
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })(%s, %s)''' % (json.dumps(YS), json.dumps(WAVES)), timeout=600)
    check('an opened project has its own table, its X\'s found by name', (r['newTable'], r['x'] == WAVES), (True, True))
    check('and keeps the two fits and their options: the same outlines', (r['fits'], r['heads'] == r['heads0'], 'VIP vs Coefficients Plots' in r['heads'], 'X-Y Scores Plots' in r['heads'], r['errors']), (2, True, True, False, 0))

    # ---- the graphs' matplotlib code
    await charts(page)

    # ---- the (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-pls"); const row = document.getElementById("help-p-pls"); return row ? row.textContent : null; })()')
    check('the platform has its line in Help, with scikit-learn\'s PLSRegression', bool(helps) and 'sklearn.cross_decomposition.PLSRegression' in helps, True)
    topics = await page.ev('Object.keys(SM.platforms.get("pls").topics)')
    check('its topics', sorted(topics), sorted(['p:pls', 'p:pls:launch', 'p:pls:summary', 'p:pls:fit', 'p:pls:cv', 'p:pls:percent', 'p:pls:coef', 'p:pls:vip', 'p:pls:scores', 'p:pls:loadings', 'p:pls:distance', 'p:pls:t2']))

    # ---- the (i) explains every input: the launch dialog, the Model Launch in the report, Set VIP Threshold…
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Spectra").id)')
    await dialog_help(page, "SM.app.launch('pls')", 'pls', 'Partial Least Squares')
    first = 'SM.app.reports.find(r => r.platform.id === "pls")'
    s = await page.ev(info_js('slot', f"[...{first}.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Model Launch')", f"{first}.body.querySelector('.sm-pls-launch')"))
    check('the Model Launch\'s (i) names each of its fields, and Go', (len(s.get('inputs', [])), unexplained(s), [c[0] for cs in s['sections'].values() for c in cs][-1:]), (5, [], ['Go']))
    fit = await page.ev(f"[...{first}.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent).find(t => t.startsWith('NIPALS Fit'))")
    await form_help(page, f"await clickPath({first}, {json.dumps(fit)}, ['Set VIP Threshold…']);", ['VIP threshold'], 'Set VIP Threshold…')

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "pls")))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2.5)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => r.platform.id === 'pls'); return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)) }; })()''')
    check('the dark theme redraws the reports without errors', st['errors'], [])
    col = await page.ev('(() => { const rep = SM.app.reports.find(r => r.platform.id === "pls" && r.spec.roles.validation && r.spec.roles.validation.length); const p = rep.plots.find(p => p.opts.title === "Distance to the Y model by row"); return p.traces[1].marker.color; })()')
    check('the validation rows take the dark theme\'s green', col, '#5fb36b')
    await shot(page, 'pls-03-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports.find(r => r.platform.id === "pls"); SM.app.showTab(SM.app.tabOf(rep)); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')
    await asyncio.sleep(1.0)
    r = await page.ev('''(() => {
      const rep = SM.app.reports.find(r => r.platform.id === "pls");
      const body = rep.body.getBoundingClientRect();
      const boxes = rep.plots.filter(p => p.drawn).map(p => (p.box.closest('.sm-profwrap') || p.box).getBoundingClientRect().right);
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Model Comparison Summary');
      const tbl = head.parentElement.querySelector('table.sm-rt');
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length,
               body: rep.body.scrollWidth <= rep.body.clientWidth + 1, scrollers: tbl.scrollWidth > tbl.clientWidth + 1 };
    })()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the graphs fit the phone\'s width', (r['plots'], r['n'] >= 2), (True, True))
    check('the wide summary scrolls inside its own box, not the whole report', (r['body'], r['scrollers']), (True, True))
    await shot(page, 'pls-04-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


if __name__ == '__main__':
    asyncio.run(main())
    sys.exit(check.done())
