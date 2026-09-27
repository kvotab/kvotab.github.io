#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Predictive Modeling > Neural.

The simulated Reactor example opens from the URL and File > Examples, and
Neural sits in Analyze > Predictive Modeling; its launch dialog has JMP's
roles (Y, X, Freq, Validation, By: no Weight) and options; the report opens
with JMP's Model Launch and its defaults, and a bad setting is refused; the
first Go loads scikit-learn and adds Model NTanH(3), whose measures are the
engine's (called here) and whose RSquare is the one computed here from the
plotted points; points select their rows and table selections highlight
them; the model's red triangle shows the Diagram (its inputs, nodes, outputs
and the Estimates' weights on its lines), Estimates, Profiler, Actual and
Residual by Predicted and Fitting Details; every red triangle opens; more
models from the Model Launch (ReLU with two layers, KFold, boosting) get
JMP's names and a Model Comparison; Remove Fit; a categorical response has
its confusion matrix and ROC curve, two responses one network; Save Columns
(predicteds, probabilities, hidden layer values, validation) match the
engine's; Excluded Rows Holdback and a Validation column make their sets; By
gives one analysis per group; Redo and a project keep the models; the Python
script holds scikit-learn's calls; Bootstrap reruns the report headless;
every (i) has a topic; the launch dialog's (i) gives every role and option
its help, and the Model Launch's (i) names each of its fields; the reports
draw in the dark theme and at phone width without a sideways page scroll,
the diagram scrolling in its own box.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-neural.py

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
Y = 'yield (%)'
XS = ['temperature (°C)', 'pressure (bar)', 'time (min)', 'catalyst (%)', 'feed rate', 'supplier']


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('%', '').replace('*', '').replace('<', ''))


# Pick an item from an outline's red triangle: path is the labels down the
# submenus; wait: wait for the report to run again. which: the n-th outline
# with that title.
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


# Set the Model Launch's controls (by their labels) and press Go.
GO = '''
(async (settings, wait) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const body = rep.body.querySelector('.sm-nn-launch').closest('.sm-ob-body');
  for (const [label, value] of Object.entries(settings)) {
    const input = body.querySelector(`[aria-label="${label}"]`);
    if (!input) throw new Error('no control ' + label);
    if (input.type === 'checkbox') input.checked = !!value; else input.value = String(value);
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }
  const done = wait ? new Promise(res => rep.on('done', res)) : null;
  body.querySelector('.sm-nn-go').click();
  if (done) await done; else await new Promise(r => setTimeout(r, 100));
  return { msg: body.querySelector('.sm-nn-msg').textContent, models: (rep.spec.options.models || []).map(m => m.id),
           outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
           errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 500)) };
})
'''


def go_js(settings=None, wait=True):
    return f'({GO})({json.dumps(settings or {})}, {json.dumps(wait)})'


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
           errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 500)),
           warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)), options: rep.spec.options,
           notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent) };
})()
'''

# The engine's own fit for the last report's model m (its payload rebuilt here).
ENGINE_FIT = '''
(async (id, extra) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const t = rep.table;
  const o = rep.spec.options;
  const m = o.models.find(x => x.id === id);
  const name = (k) => (rep.spec.roles[k] || []).map(c => t.col(c).name);
  const seed = o.seed !== undefined && o.seed !== '' ? Number(o.seed) : o.seedDrawn;
  const model = { method: m.method, portion: m.portion, folds: m.folds, activation: m.activation, n1: m.n1, n2: m.n2, boost: m.boost, rate: m.rate, transform: m.transform, penalty: m.penalty, tours: m.tours, max_iter: m.max_iter };
  if ((rep.spec.roles.validation || []).length) model.method = 'column';
  const p = { table: t.id, rows: null, y: name('y'), x: name('x'), freq: name('freq')[0] || null, validation: name('validation')[0] || null, seed, missing: o.missing === false ? 'drop' : 'informative', model, ...(extra || {}) };
  return await SM.engine.call('neural.fit', p, t);
})
'''


def engine_fit_js(mid, extra=None):
    return f'({ENGINE_FIT})({json.dumps(mid)}, {json.dumps(extra or {})})'


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


async def main():
    page = await open_page(f'{BASE}/smui.html?example=reactor', height=1300)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "neural").map(f => f.module + ": " + f.error)')
    check('neural.py imports in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])
    check('scikit-learn waits for its first use', await page.ev("(SM.engine.versions['scikit-learn'] || null)"), None)

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const file = SM.app.menuItems('File');
      const exs = file.find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const an = SM.app.menuItems('Analyze');
      const pm = an.find(i => i.label === 'Predictive Modeling');
      const items = (typeof pm.submenu === 'function' ? pm.submenu() : pm.submenu).filter(i => !i.separator).map(i => i.label);
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), about: SM.io.EXAMPLES.reactor.about, inFile: labels.includes(SM.io.EXAMPLES.reactor.label), items,
               grade: t.levels(t.col('grade')), gradeType: t.col('grade').modelingType };
    })()''')
    check('?example=reactor opens the simulated reactor table', (ex['name'], ex['rows'], len(ex['cols'])), ('Reactor', 600, 10))
    check('it is simulated, its notes give the true surface', ex['about'].startswith('Simulated') and 'exp(−((temperature − 205)/28)²)' in ex['about'], True)
    check('... grade is ordinal Low, Medium, High', (ex['gradeType'], ex['grade']), ('ordinal', ['Low', 'Medium', 'High']))
    check('it is in File > Examples', ex['inFile'], True)
    check('Analyze > Predictive Modeling lists Neural', 'Neural…' in ex['items'], True)

    # ---- the launch dialog
    r = await page.ev('''(async () => {
      SM.app.launch('neural');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      const opts = [...dlg.querySelectorAll('.sm-launch-opts label')].map(l => l.textContent.trim());
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (names) => { items.forEach(li => li.classList.remove('is-selected')); names.forEach((nm, i) => items.find(x => x.textContent === nm).dispatchEvent(new MouseEvent('mousedown', { bubbles: true, metaKey: i > 0 }))); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      pick(['%s']); role('Y, Response').querySelector('.sm-btn').click();
      ok.click();
      const needX = dlg.querySelector('.sm-launch-msg').textContent;
      pick(%s); role('X, Factor').querySelector('.sm-btn').click();
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      const body = rep.body;
      const val = (l) => { const i = body.querySelector(`[aria-label="${l}"]`); return i ? (i.type === 'checkbox' ? i.checked : i.value) : null; };
      const pen = body.querySelector('[aria-label="Penalty Method"]');
      return { roles, opts, needX, title: rep.title, outlines: [...body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
               notes: [...body.querySelectorAll('.sm-ob-note')].map(e => e.textContent),
               defaults: ['Validation Method', 'Holdback Proportion', 'Activation', 'First layer nodes', 'Second layer nodes', 'Number of Models', 'Learning Rate', 'Transform Covariates', 'Penalty Method', 'Number of Tours', 'Maximum Iterations'].map(val),
               robust: body.querySelector('[aria-label="Robust Fit (not in scikit-learn)"]').disabled,
               penalties: [...pen.options].map(o => [o.textContent, o.disabled]), folds: body.querySelector('.sm-nn-folds').hidden,
               activations: [...body.querySelector('[aria-label="Activation"]').options].map(o => o.textContent) };
    })()''' % (Y, json.dumps(XS)))
    check('JMP\'s roles: Y, X, Freq, Validation, By (no Weight)', r['roles'], ['Y, Response', 'X, Factor', 'Freq', 'Validation', 'By'])
    check('the launch options: Informative Missing and the Random Seed', r['opts'], ['Informative Missing', 'Random Seed'])
    check('no X: an error', 'X, Factor' in r['needX'], True)
    check('the report opens with the Model Launch and no model (JMP: Go fits one)', (r['title'], r['outlines']), ('Neural', ['Neural', 'Model Launch']))
    check('... and says to press Go', any('press Go' in t for t in r['notes']), True)
    check('JMP\'s Model Launch defaults', r['defaults'], ['holdback', '0.3333', 'tanh', '3', '0', '0', '0.1', False, 'squared', '1', '200'])
    check('Robust Fit, Absolute and Weight Decay are shown and off (not in scikit-learn)', (r['robust'], r['penalties']),
          (True, [['Squared', False], ['Absolute (not in scikit-learn)', True], ['Weight Decay (not in scikit-learn)', True], ['No Penalty', False]]))
    check('scikit-learn\'s four activations', r['activations'], ['TanH', 'Logistic', 'ReLU', 'Identity (Linear)'])
    check('Number of Folds shows with KFold only', r['folds'], True)
    g = await page.ev(go_js({'First layer nodes': 0}, wait=False))
    check('a bad setting is refused at Go', ('first layer' in g['msg'], g['models']), (True, []))

    # ---- Go: the first model, which loads scikit-learn
    g = await page.ev(go_js({'First layer nodes': 3}), timeout=900)
    check('Go adds Model NTanH(3), without errors', ('Model NTanH(3)' in g['outlines'], g['errors'], g['models']), (True, [], ['m1']))
    check('the first call loads scikit-learn 1.8', await page.ev("SM.engine.versions['scikit-learn']"), '1.8.0')
    st = await page.ev(STATE)
    check('the Model Launch closes after Go, as JMP\'s does', await page.ev('(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; return [...rep.body.querySelectorAll(".sm-ob")].find(o => { const h = o.querySelector(":scope > .sm-ob-head h3"); return h && h.textContent === "Model Launch"; }).classList.contains("is-closed"); })()'), True)
    check('the model\'s summary: Random Holdback, the penalty chosen', any(t.startswith('Validation: Random Holdback, 0.3333 of the rows') and 'Squared penalty alpha' in t for t in st['notes']), True)
    await shot(page, 'neural-01-model.png')
    eng = await page.ev(engine_fit_js('m1'), timeout=600)
    meas = await page.ev(table_under_js(f'Measures of Fit for {Y}', 0))
    head = meas[0]
    rows_ = {row[0]: row for row in meas[1:]}
    em = {m['set']: m for m in eng['responses'][0]['fit']['measures']}
    for sname in ('Training', 'Validation'):
        check.near(f'{sname} RSquare = the engine\'s (to the seven digits shown)', num(rows_[sname][head.index('RSquare')]), em[sname]['rsquare'], tol=5e-7)
        check.near(f'{sname} RASE = the engine\'s', num(rows_[sname][head.index('RASE')]), em[sname]['rase'], tol=5e-7)
    check('N: 400 training and 200 validation rows (0.3333 held back)', (rows_['Training'][-1], rows_['Validation'][-1]), ('400', '200'))

    # ---- the red triangle: every part of a model
    for item in ('Diagram', 'Show Estimates', 'Profiler', 'Plot Actual by Predicted', 'Plot Residual by Predicted', 'Fitting Details'):
        await page.ev(pick_js('Model NTanH(3)', [item]), timeout=300)
    st = await page.ev(STATE)
    check('the red triangle shows the Diagram, Estimates, Profiler, both plots and Fitting Details',
          all(t in st['outlines'] for t in ('Diagram', 'Estimates', 'Prediction Profiler', 'Actual by Predicted Plot', 'Residual by Predicted Plot', 'Fitting Details')), True)
    check('no errors in the report', st['errors'], [])
    # RSquare from the plotted points, computed here
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => p.opts.title === 'Actual by predicted Validation');
      const x = p.traces[0].x, y = p.traces[0].y;
      const m = y.reduce((a, b) => a + b, 0) / y.length;
      let sse = 0, sst = 0; for (let i = 0; i < y.length; i++) { sse += (y[i] - x[i]) ** 2; sst += (y[i] - m) ** 2; }
      const q = rep.plots.find(p => p.opts.title === 'Residual by predicted Validation');
      const res = q.traces[0].y, pr = q.traces[0].x;
      return { r2: 1 - sse / sst, n: y.length, rows: p.rows[0].length, resid: Math.max(...res.map((v, i) => Math.abs(v - (y[i] - x[i])))), same: pr.every((v, i) => v === x[i]) };
    })()''')
    check.near('the Validation RSquare computed here from the plotted points', r['r2'], em['Validation']['rsquare'], tol=1e-9)
    check('the residuals are actual minus predicted, point by point', (r['resid'] < 1e-9, r['same'], r['n'], r['rows']), (True, True, 200, 200))
    # the diagram: inputs, nodes, outputs, and the Estimates' weights on its lines
    dg = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const s = rep.body.querySelector('.sm-nn-diagram svg');
      const lines = [...s.querySelectorAll('line.sm-nn-edge')];
      const first = lines[0].querySelector('title').textContent;
      return { inputs: [...s.querySelectorAll('.sm-nn-in text')].map(t => t.textContent), hidden: s.querySelectorAll('.sm-nn-hid circle').length,
               outputs: [...s.querySelectorAll('.sm-nn-out text')].map(t => t.textContent), lines: lines.length, first, glyphs: s.querySelectorAll('.sm-nn-glyph').length,
               cat: lines.find(l => l.querySelector('title').textContent.startsWith('supplier')).querySelector('title').textContent };
    })()''')
    check('the Diagram: the six X columns, three TanH nodes, the response', (dg['inputs'], dg['hidden'], dg['outputs'], dg['glyphs']), (XS, 3, [Y], 3))
    check('... a line for every weight', dg['lines'], 6 * 3 + 3)
    est = {r_['parameter']: r_['estimate'] for r_ in eng['nets'][0]['estimates']}
    check.near('... the first line\'s title is the Estimate of H1_1:temperature', num(dg['first'].split(': ')[1].split(' ')[-1]), est['H1_1:temperature (°C)'], tol=5e-4)
    check('... a categorical input\'s line lists its level columns', all(f'supplier[{lv}]' in dg['cat'] for lv in 'ABC'), True)
    et = await page.ev(table_under_js('Estimates', 0))
    check('the Estimates: JMP\'s names, from H1_1:temperature to the output\'s intercept', (et[0], et[1][0], et[-1][0], len(et) - 1), (['Parameter', 'Estimate'], 'H1_1:temperature (°C)', f'{Y}:Intercept', 3 * 9 + 4))
    check.near('... H1_1:temperature', num(et[1][1]), est['H1_1:temperature (°C)'], tol=5e-7)
    pf = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const g = rep.body.querySelector('.sm-prof');
      return { plots: g.querySelectorAll('.sm-plot').length, names: [...g.querySelectorAll('.sm-prof-fname')].map(e => e.textContent), val: g.querySelector('.sm-prof-val').textContent }; })()''')
    check('the Prediction Profiler: a plot per factor', (pf['plots'], pf['names']), (6, XS))
    prof = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table; const o = rep.spec.options;
      const m = o.models[0];
      const r = await SM.engine.call('neural.profile', { table: t.id, rows: null, y: ['%s'], x: %s, freq: null, validation: null, seed: o.seedDrawn, missing: 'informative',
        model: { method: m.method, portion: m.portion, folds: m.folds, activation: m.activation, n1: m.n1, n2: m.n2, boost: m.boost, rate: m.rate, transform: m.transform, penalty: m.penalty, tours: m.tours, max_iter: m.max_iter }, current: {} }, t);
      return r.responses[0].current.pred; })()''' % (Y, json.dumps(XS)))
    check.near('... its current prediction is the engine\'s profile of the model', num(pf['val']), prof, tol=2e-6)
    dt = await page.ev(table_under_js('Fitting Details', 0))
    check('Fitting Details: the penalty path, its chosen alpha marked', (dt[0][:4], sum(1 for row in dt[1:] if row[-1] == 'chosen')), (['alpha', 'Iterations', 'Training -LogLikelihood', 'Validation -LogLikelihood'], 1))
    check.near('... the chosen alpha is the model\'s', num(next(row for row in dt[1:] if row[-1] == 'chosen')[0]), eng['nets'][0]['alpha'], tol=1e-12)
    await shot(page, 'neural-02-parts.png')

    # ---- linking
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => p.opts.title === 'Actual by predicted Training');
      p._click({ points: [{ curveNumber: 0, pointNumber: 7 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[0][3], p.rows[0][11]]);
      const sp = p.box.data[0].selectedpoints;
      const q = rep.plots.find(p => p.opts.title === 'Residual by predicted Training');
      const sq = q.box.data[0].selectedpoints;
      t.select([]);
      return { sel, want: [p.rows[0][7]], sp, sq };
    })()''')
    check('a click on a point of Actual by Predicted selects its row', r['sel'], r['want'])
    check('rows selected in the table highlight their points in both plots', (r['sp'], r['sq']), ([3, 11], [3, 11]))

    await triangles(page, 'the report', 6)

    # ---- more models from the Model Launch: JMP's names, a comparison
    g = await page.ev(go_js({'Activation': 'relu', 'First layer nodes': 4, 'Second layer nodes': 2}), timeout=900)
    check('ReLU with two layers: Model NReLU(4)NReLU2(2)', ('Model NReLU(4)NReLU2(2)' in g['outlines'], g['errors']), (True, []))
    g = await page.ev(go_js({'Validation Method': 'kfold', 'Number of Folds': 4, 'Activation': 'tanh', 'First layer nodes': 3, 'Second layer nodes': 0}), timeout=900)
    st = await page.ev(STATE)
    check('KFold: a third model, the fold it was chosen by said', (g['errors'], any(t.startswith('Validation: KFold, 4 folds') for t in st['notes'])), ([], True))
    g = await page.ev(go_js({'Validation Method': 'holdback', 'First layer nodes': 2, 'Number of Models': 5, 'Learning Rate': 0.2}), timeout=900)
    check('boosting: Model NTanH(2)NBoost(5)', ('Model NTanH(2)NBoost(5)' in g['outlines'], g['errors']), (True, []))
    check('the Model Comparison comes with several models', 'Model Comparison' in g['outlines'], True)
    cmp_ = await page.ev(table_under_js('Model Comparison', 0))
    check('... a line per model and set, in the order of the models, with their validation', [row[:3] for row in cmp_[1:]],
          [[m_, v_, s_] for m_, v_ in (('Model NTanH(3)', 'Holdback 0.3333'), ('Model NReLU(4)NReLU2(2)', 'Holdback 0.3333'), ('Model NTanH(3)', 'KFold 4'), ('Model NTanH(2)NBoost(5)', 'Holdback 0.3333')) for s_ in ('Training', 'Validation')])
    k3 = await page.ev(engine_fit_js('m3'), timeout=600)
    kv = next(m for m in k3['responses'][0]['fit']['measures'] if m['set'] == 'Validation')
    kline = [row for row in cmp_[1:] if row[0] == 'Model NTanH(3)' and row[1] == 'KFold 4' and row[2] == 'Validation']
    check.near('... the KFold model\'s validation RSquare is the engine\'s', num(kline[0][3]), kv['rsquare'], tol=5e-7)
    await page.ev(pick_js('Model NReLU(4)NReLU2(2)', ['Diagram']), timeout=300)
    dg2 = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1];
      const box = [...rep.body.querySelectorAll('.sm-ob')].find(o => { const h = o.querySelector(':scope > .sm-ob-head h3'); return h && h.textContent === 'Model NReLU(4)NReLU2(2)'; });
      const s = box.querySelector('.sm-nn-diagram svg');
      return { hidden: s.querySelectorAll('.sm-nn-hid circle').length, lines: s.querySelectorAll('line').length, caps: [...s.querySelectorAll('.sm-nn-layer')].map(t => t.textContent) }; })()''')
    check('the two-layer Diagram: H2 next to the inputs, then H1', (dg2['caps'], dg2['hidden'], dg2['lines']), (['Inputs', 'H2', 'H1', 'Outputs'], 6, 6 * 2 + 2 * 4 + 4))
    await shot(page, 'neural-03-models.png')
    await page.ev(pick_js('Model NTanH(2)NBoost(5)', ['Remove Fit']), timeout=300)
    st = await page.ev(STATE)
    check('Remove Fit removes the model', ('Model NTanH(2)NBoost(5)' in st['outlines'], [m['id'] for m in st['options']['models']]), (False, ['m1', 'm2', 'm3']))
    await rerun(page)
    st2 = await page.ev(STATE)
    check('Redo keeps the models and their parts', ([o for o in st2['outlines'] if o.startswith('Model ')], st2['errors']), ([o for o in st['outlines'] if o.startswith('Model ')], []))

    # ---- Save Columns
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const n0 = t.columns.length;
      for (const item of ['Save Predicteds', 'Save Residuals', 'Save Hidden Layer Values', 'Save Validation']) {
        await (%s)('Model NTanH(3)', ['Save Columns', item], false, 0);
        await new Promise(r => setTimeout(r, 500));
      }
      const added = t.columns.slice(n0).map(c => c.name);
      const o = rep.spec.options; const m = o.models[0];
      const model = { method: m.method, portion: m.portion, folds: m.folds, activation: m.activation, n1: m.n1, n2: m.n2, boost: m.boost, rate: m.rate, transform: m.transform, penalty: m.penalty, tours: m.tours, max_iter: m.max_iter };
      const base = { table: t.id, rows: null, y: ['%s'], x: %s, freq: null, validation: null, seed: o.seedDrawn, missing: 'informative', model };
      const sv = await SM.engine.call('neural.save', { ...base, what: 'predicteds' }, t);
      const hv = await SM.engine.call('neural.save', { ...base, what: 'hidden' }, t);
      const vv = await SM.engine.call('neural.save', { ...base, what: 'validation' }, t);
      const col = (nm) => t.col(nm).values;
      const same = (a, rows, vals) => rows.every((r, i) => Math.abs(a[r] - vals[i]) < 1e-12);
      return { added, pred: same(col('Predicted %s'), sv.responses[0].rows, sv.responses[0].values), resid: same(col('Residual %s'), sv.responses[0].rows, sv.responses[0].residuals),
               h: same(col('H1_2'), hv.rows, hv.columns[1].values), v: same(col('Validation'), vv.rows, vv.values), vtype: t.col('Validation').modelingType,
               nval: col('Validation').filter(x => x === 1).length };
    })()''' % (PICK, Y, json.dumps(XS), Y, Y))
    check('Save Columns: Predicted, Residual, H1_1 to H1_3 and Validation', r['added'], [f'Predicted {Y}', f'Residual {Y}', 'H1_1', 'H1_2', 'H1_3', 'Validation'])
    check('... the engine\'s predictions, residuals and hidden nodes\' values', (r['pred'], r['resid'], r['h']), (True, True, True))
    check('... Validation: 0 training, 1 validation (nominal), 200 held back', (r['v'], r['vtype'], r['nval']), (True, 'nominal', 200))

    # ---- a categorical response; two continuous responses in one network
    m1 = {'id': 'm1', 'method': 'holdback', 'portion': 0.3333, 'folds': 5, 'activation': 'tanh', 'n1': 3, 'n2': 0, 'boost': 0, 'rate': 0.1, 'transform': False, 'penalty': 'squared', 'tours': 1, 'max_iter': 200}
    rep = await page.ev(open_report_js('neural', {'y': ['grade'], 'x': XS}, {'models': [m1], 'seed': '77', 'm1|roc': True}), timeout=600)
    check('a categorical response: its measures, confusion matrix and ROC curve', (rep['errors'], all(t in rep['outlines'] for t in ('Measures of Fit for grade', 'Confusion Matrix', 'ROC Curve'))), ([], True))
    cm = await page.ev(table_under_js('Confusion Matrix', 0))
    engc = await page.ev(engine_fit_js('m1'), timeout=600)
    ctr = next(c for c in engc['responses'][0]['fit']['confusion'] if c['set'] == 'Training')
    check('... the confusion matrix is the engine\'s', [[num(v) for v in row[1:]] for row in cm[1:]], ctr['matrix'])
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      await (%s)('Model NTanH(3)', ['Save Columns', 'Save Predicteds'], false, 0);
      await new Promise(r => setTimeout(r, 500));
      const lv = t.col('Most Likely grade');
      const p = ['Low', 'Medium', 'High'].map(l => t.col('Prob[' + l + ']').values);
      return { mt: lv.modelingType, order: t.levels(lv), sums: p[0].every((v, i) => Math.abs(v + p[1][i] + p[2][i] - 1) < 1e-9), open: p.every(c => c.every(v => v > 0 && v < 1)),
               most: lv.values.every((v, i) => v === ['Low', 'Medium', 'High'][[p[0][i], p[1][i], p[2][i]].indexOf(Math.max(p[0][i], p[1][i], p[2][i]))]) };
    })()''' % PICK)
    check('Save Predicteds of a categorical response: Prob columns that add to 1, never 0 or 1', (r['sums'], r['open']), (True, True))
    check('... and the most likely level, ordinal as the response', (r['mt'], r['order'], r['most']), ('ordinal', ['Low', 'Medium', 'High'], True))
    await triangles(page, 'the categorical report', 2)
    rep = await page.ev(open_report_js('neural', {'y': [Y, 'purity (%)'], 'x': XS}, {'models': [m1], 'seed': '77', 'm1|estimates': True, 'm1|diagram': True}), timeout=600)
    check('two continuous responses: one network, an outline per response', (rep['errors'], [o for o in rep['outlines'] if o in (Y, 'purity (%)')]), ([], [Y, 'purity (%)']))
    r = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const s = rep.body.querySelector('.sm-nn-diagram svg');
      return { outs: [...s.querySelectorAll('.sm-nn-out text')].map(t => t.textContent), diagrams: rep.body.querySelectorAll('.sm-nn-diagram').length }; })()''')
    check('... one diagram with both outputs', (r['diagrams'], r['outs']), (1, [Y, 'purity (%)']))
    est2 = await page.ev(table_under_js('Estimates', 0))
    check('... the Estimates end with both outputs\' weights', [row[0] for row in est2[-8:]], [f'{Y}:H1_1', f'{Y}:H1_2', f'{Y}:H1_3', f'{Y}:Intercept', 'purity (%):H1_1', 'purity (%):H1_2', 'purity (%):H1_3', 'purity (%):Intercept'])

    # ---- Excluded Rows Holdback, a Validation column
    await page.ev('(() => { const t = SM.app.tables.find(t => t.name === "Reactor"); t.setState(Array.from({ length: 90 }, (_, i) => i), "excluded", true); })()')
    mx_ = dict(m1, method='excluded')
    rep = await page.ev(open_report_js('neural', {'y': [Y], 'x': XS}, {'models': [mx_], 'seed': '77'}), timeout=600)
    ms = await page.ev(table_under_js(f'Measures of Fit for {Y}', 0))
    check('Excluded Rows Holdback: the 90 excluded rows validate, the 510 others train', (rep['errors'], [(row[0], row[-1]) for row in ms[1:]]), ([], [('Training', '510'), ('Validation', '90')]))
    await page.ev('(() => { const t = SM.app.tables.find(t => t.name === "Reactor"); t.setState(Array.from({ length: 90 }, (_, i) => i), "excluded", false); })()')
    await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === "Reactor");
      t.addColumn({ name: 'Set', dataType: 'numeric', modelingType: 'nominal', values: Array.from({ length: t.nrows }, (_, i) => (i % 5 === 0 ? 1 : i % 5 === 1 ? 2 : 0)) }); })()''')
    rep = await page.ev(open_report_js('neural', {'y': [Y], 'x': XS, 'validation': ['Set']}, {'models': [m1], 'seed': '77'}), timeout=600)
    ms = await page.ev(table_under_js(f'Measures of Fit for {Y}', 0))
    st = await page.ev(STATE)
    check('a Validation column: its training, validation and test rows', (rep['errors'], [(row[0], row[-1]) for row in ms[1:]]), ([], [('Training', '360'), ('Validation', '120'), ('Test', '120')]))
    lv = await page.ev('(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; return [rep.body.querySelector(".sm-nn-vline").textContent, !rep.body.querySelector("[aria-label=\\"Validation Method\\"]")]; })()')
    check('... named at the top, and the Model Launch has no method to choose', lv, ['Validation Column: Set', True])

    # ---- By: one analysis per supplier
    rep = await page.ev(open_report_js('neural', {'y': [Y], 'x': XS[:5], 'by': ['supplier']}, {'models': [m1], 'seed': '77'}), timeout=900)
    check('By supplier: one analysis per group, each with the model', ([o for o in rep['outlines'] if o.startswith('Neural')], rep['outlines'].count('Model NTanH(3)'), rep['errors']),
          (['Neural supplier=A', 'Neural supplier=B', 'Neural supplier=C'], 3, []))
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      // the Measures of Fit of one model, in each group (the table key names the model)
      const tbls = [...rep.body.querySelectorAll('table.sm-rt')].filter(t => /^measures:/.test(t.dataset.rtKey || ''));
      const combined = SM.report.combineRT(tbls, 'x');
      const sup = rep.table.col('supplier').values;
      return { groups: tbls.map(t => t.dataset.group), rows: combined.nrows, n: tbls.map(t => t._rt.rows.reduce((a, r) => a + r.n, 0)), want: ['A', 'B', 'C'].map(s => sup.filter(v => v === s).length) };
    })()''')
    check('... each group fits its own rows, and the measures combine into one table', (r['groups'], r['n'], r['rows']), (['supplier=A', 'supplier=B', 'supplier=C'], r['want'], 6))

    # ---- a project keeps the models, the launch settings and the parts shown
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "neural" && (r.spec.options.models || []).length === 3)))')
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'neural' && (r.spec.options.models || []).length === 3);
      const t = rep.table;
      const before = [...rep.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent);
      const cell = [...rep.body.querySelectorAll('table.sm-rt')].find(x => x.dataset.rtKey === 'measures' || x.querySelector('caption') === null).querySelectorAll('tbody tr')[1].cells[1].textContent;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const after = [...back.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent);
      const cell2 = [...back.body.querySelectorAll('table.sm-rt')].find(x => x.dataset.rtKey === 'measures' || x.querySelector('caption') === null).querySelectorAll('tbody tr')[1].cells[1].textContent;
      const out = { newTable: back.table !== t, models: back.spec.options.models.map(m => m.id), launch: back.spec.options.launch, diagram: !!back.spec.options['m1|diagram'],
                    same: JSON.stringify(before) === JSON.stringify(after), cell, cell2, errors: [...back.body.querySelectorAll('.sm-ob-error')].length };
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })()''', timeout=900)
    check('an opened project has its own table and keeps the three models', (r['newTable'], r['models']), (True, ['m1', 'm2', 'm3']))
    check('... the Model Launch\'s last settings and the parts shown', (r['launch']['n1'], r['launch']['boost'], r['diagram']), (2, 5, True))
    check('... and draws the same outlines and numbers, without errors', (r['same'], r['cell'] == r['cell2'], r['errors']), (True, True, 0))

    script = await page.ev('SM.app.reports.find(r => r.platform.id === "neural" && (r.spec.options.models || []).length === 3).pythonScript()')
    check('the script holds scikit-learn\'s calls, read exactly from the CSV', all(s in script for s in ('MLPRegressor(hidden_layer_sizes=(3,)', 'warm_start=True', 'float_precision="round_trip"', 'np.random.default_rng', 'MLPRegressor(hidden_layer_sizes=(2, 4), activation="relu"')), True)

    # ---- Bootstrap reruns the report headless
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'neural' && (r.spec.options.models || []).length === 3);
      SM.app.showTab(SM.app.tabOf(rep));
      const tbl = [...rep.body.querySelectorAll('table.sm-rt')].find(x => x.dataset.rtKey === 'measures' || x.querySelector('caption') === null);
      const n0 = SM.app.tables.length;
      const outlines = [...rep.body.querySelectorAll('.sm-ob-head h3')].length;
      const res = await SM.bootstrap.run(tbl, tbl._rt.columns.find(c => c.label === 'RSquare'), { B: 3, seed: 2, show: false });
      return { rows: res ? res.nrows : null, cols: res ? res.columns.map(c => c.name) : null, finite: res ? res.columns[1].values.every(Number.isFinite) : null,
               same: [...rep.body.querySelectorAll('.sm-ob-head h3')].length === outlines, tables: SM.app.tables.length - n0 };
    })()''', timeout=900)
    check('Bootstrap reruns the model on resampled rows (headless): a row per sample', (r['rows'], r['cols'], r['finite']), (4, ['BootID', 'Training', 'Validation'], True))
    check('... leaving the report as it was', r['same'], True)

    # ---- the (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-neural"); const row = document.getElementById("help-p-neural"); return row ? row.textContent : null; })()')
    check('the platform has its line in Help, with scikit-learn\'s MLPs', bool(helps) and 'MLPRegressor' in helps and 'MLPClassifier' in helps, True)
    topics = await page.ev('Object.keys(SM.platforms.get("neural").topics)')
    check('its topics', sorted(topics), sorted(['p:neural', 'p:neural:launch', 'p:neural:model', 'p:neural:estimates', 'p:neural:diagram', 'p:neural:details', 'p:neural:residual', 'p:neural:compare']))

    # ---- the (i) explains every input: the launch dialog, and every field of the Model Launch in the report
    d = await dialog_help(page, "SM.app.launch('neural')", 'neural', 'Neural')
    check('... its Validation role says the Model Launch holds rows back without one (no Validation Portion here)', 'the Model Launch holds rows back' in dict(d['sections'].get('Roles', [])).get('Validation', ''), True)
    three = 'SM.app.reports.find(r => r.platform.id === "neural" && (r.spec.options.models || []).length === 3)'
    head = f"[...{three}.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Model Launch')"
    s = await page.ev(info_js('slot', head, f"{head}.parentElement.querySelector('.sm-nn-launch')"))
    check('the Model Launch\'s (i) names every one of its fields, in JMP\'s boxes, and Go', (len(s.get('inputs', [])), unexplained(s), s.get('headings')),
          (13, [], ['Validation Method', 'Hidden Layer Structure', 'Boosting', 'Fitting Options', 'Go']))
    check('... each with what it does', all(len(t) > 40 for cs in s['sections'].values() for _, t in cs), True)

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "neural" && (r.spec.options.models || []).length === 3)))')
    light = await page.ev('getComputedStyle(SM.app.reports.find(r => r.platform.id === "neural" && (r.spec.options.models || []).length === 3).body.querySelector(".sm-nn-in rect")).fill')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2.5)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => r.platform.id === 'neural'); return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)) }; })()''')
    check('the dark theme redraws the reports without errors', st['errors'], [])
    dark = await page.ev('getComputedStyle(SM.app.reports.find(r => r.platform.id === "neural" && (r.spec.options.models || []).length === 3).body.querySelector(".sm-nn-in rect")).fill')
    check('the diagram takes the dark theme\'s colours', (light, dark), ('rgb(220, 232, 244)', 'rgb(34, 58, 82)'))
    await shot(page, 'neural-04-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports.find(r => r.platform.id === "neural" && (r.spec.options.models || []).length === 3); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()', timeout=600)
    await asyncio.sleep(1.0)
    r = await page.ev('''(() => {
      const rep = SM.app.reports.find(r => r.platform.id === "neural" && (r.spec.options.models || []).length === 3);
      const body = rep.body.getBoundingClientRect();
      const boxes = rep.plots.filter(p => p.drawn && !p.box.closest('.sm-profwrap')).map(p => p.box.getBoundingClientRect().right);
      const dia = [...rep.body.querySelectorAll('.sm-nn-diagram')];
      const panel = rep.body.querySelector('.sm-nn-launch');
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length,
               body: rep.body.scrollWidth <= rep.body.clientWidth + 1, dia: dia.some(d => d.scrollWidth > d.clientWidth) && dia.every(d => d.getBoundingClientRect().right <= body.right + 1),
               stacked: getComputedStyle(panel).flexDirection };
    })()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the graphs fit the phone\'s width', (r['plots'], r['n'] >= 2), (True, True))
    check('the report does not scroll sideways; the wide diagram scrolls in its own box', (r['body'], r['dia']), (True, True))
    check('the Model Launch\'s boxes stack', r['stacked'], 'column')
    await shot(page, 'neural-05-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
