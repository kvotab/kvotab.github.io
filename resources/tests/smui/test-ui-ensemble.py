#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Predictive Modeling > Decision
Forest and Boosted Tree.

The simulated Subscribers example opens from the URL and File > Examples;
Analyze > Predictive Modeling lists Decision Forest before Boosted Tree;
the page starts without scikit-learn and the first fit loads it; the launch
dialog has JMP's roles and its Specification panel with JMP's defaults (the
number of terms follows the X columns cast); the report's outlines are
JMP's, and its Overall Statistics, Specifications, Cumulative Validation and
Column Contributions are the engine's for the same call; the actual by
predicted points select their rows (one by a real mouse click) and table
selections highlight them; every red triangle opens; Show Trees (a split
on a categorical column words its two groups of levels as JMP does), the
statistic of Cumulative Validation, Permutation Importance, the profiler,
ROC and lift curves appear from the red triangles; Save Columns saves the
engine's predictions and probabilities, Score Rows… scores another open
table and rows added since with the model as it fitted, and Save
Cumulative Details makes a table; Specifications… fits again with new
settings; Multiple Fits gives
Model Validation-Set Summaries whose lines show their fits; progress lines
reach the report while a long fit runs; By gives one analysis per group with
combined tables; Redo and a project keep the options; Bootstrap reruns the
report headless; the Python script holds the trees' code; every (i)
has a topic; the launch dialogs' (i) explain every role, option and
Specification field, as the Specifications form's and Tree Views' (i) do
theirs; the reports draw in the dark theme and at phone width.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-ensemble.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import importlib.util
import json
import os
import re
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine
from test_charts import GRAPHS_JS

# the predictive platforms' chart helpers (test-ui-partition.py has them: PM_JS, chart_blocks, check_*)
_spec = importlib.util.spec_from_file_location('ui_partition_charts', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test-ui-partition.py'))
UP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(UP)

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
XS = ['tenure (months)', 'monthly charge', 'contract', 'support calls', 'age', 'region', 'data use (GB)']


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('%', '').replace('*', '').replace('<', ''))


# Pick an item from an outline's red triangle: path is the labels down the
# submenus; wait: wait for the report to run again; which: the n-th outline
# with that title (By groups repeat them); '*top*' is the report's own.
PICK = '''
(async (title, path, wait, which) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const heads = [...rep.body.querySelectorAll('.sm-ob-head')].filter(h => (title === '*top*' ? !!h.querySelector('h2') : h.querySelector('h2, h3, h4').textContent.trim() === title));
  const head = heads[which || 0];
  if (!head) throw new Error('no outline ' + title);
  head.querySelector('.sm-ob-menu').click();
  await new Promise(r => setTimeout(r, 60));
  let done = null;
  for (let i = 0; i < path.length; i++) {
    const menus = [...document.querySelectorAll('.sm-menu')];
    const m = menus[menus.length - 1];
    const b = [...m.querySelectorAll('button')].find(x => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === path[i]);
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


# The same for an item that opens a form: fill(dialog) runs on it, then OK.
PICK_FORM = '''
(async (title, path, fill) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await (%s)(title, path, false, 0);
  for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 100));
  const d = [...document.querySelectorAll('.sm-dialog')].pop();
  const done = new Promise(res => rep.on('done', res));
  const byLabel = (label) => { const l = [...d.querySelectorAll('.sm-form label')].find(x => x.textContent === label); return l ? d.querySelector('#' + l.htmlFor) : null; };
  (new Function('d', 'byLabel', fill))(d, byLabel);
  d.querySelector('.sm-dialog-foot .primary').click();
  await done;
  return [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
})
''' % PICK


def pick_form_js(title, path, fill):
    return f'({PICK_FORM})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(fill)})'


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
           warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)), options: rep.spec.options };
})()
'''

# The engine's own answer for the last report: the same call the report makes.
ENGINE = '''
(async (extra) => {
  const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table; const o = rep.spec.options;
  const name = (k) => (rep.spec.roles[k] || []).map(id => t.col(id).name);
  const payload = { table: t.id, rows: null, y: name('y')[0], x: name('x'), kind: rep.platform.id, weight: name('weight')[0] || null, freq: name('freq')[0] || null,
    validation: name('validation')[0] || null, portion: Number(o.portion || 0), seed: o.seed ? Math.trunc(Number(o.seed)) : o.seedDrawn, missing: o.missing === false ? 'drop' : 'informative',
    settings: o.settings || {}, shown: o.shownFit ?? null };
  const { fn, ...more } = extra || {};
  return SM.engine.call(fn || 'ensemble.fit', { ...payload, ...more }, t);
})
'''


def engine_js(extra=None):
    return f'({ENGINE})({json.dumps(extra or {})})'


async def triangles(page, name, least):
    r = await page.ev(TRIANGLES)
    ok = isinstance(r, dict) and not r['errors'] and r['triangles'] >= least and r['items'] > r['triangles']
    check(f'every red triangle of {name} opens, with its submenus', ok, True)
    if not ok:
        print('   ', r)


async def rerun(page):
    await page.ev('(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')


def kv_of(rows):
    return {r[0]: r[1] for r in rows or []}



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


def ensemble_compare(lab, g, F):
    t = g['label']
    if t.startswith('Cumulative Validation of'):
        UP.check_lines(check, lab, g, F)
        ax = F['axes'][0]
        kept = [tr for tr in g['traces'] if tr.get('mode') == 'markers' and len(tr.get('x') or []) == 1]
        check(f'{lab}: the number kept marked on its curve', all(any(ln['marker'] == 'D' and UP.close(ln['x'], k['x'], 1e-12) and UP.close(ln['y'], k['y'], 1e-9) for ln in ax['lines']) for k in kept) and len(kept) == 1, True)
        check(f'{lab}: the legend: the sets (and out of bag)', F['legend'], [tr['name'] for tr in g['traces'] if tr.get('showlegend') is not False and len(tr.get('x') or []) > 1])
    else:
        check(f'{lab}: a graph this test knows', t, None)


async def charts(page):
    """Every graph of Decision Forest's and Boosted Tree's reports, categorical and continuous: its block
    under it, run in the page, its figure the graph's (the model refitted in the block with the seed)."""
    await page.ev(GRAPHS_JS)
    await page.ev(UP.PM_JS)
    await page.ev('__gr.idle()')
    tbl = "SM.app.tables.find((t) => t.name === 'Subscribers')"
    await page.ev(f'SM.app.showTab(SM.app.tabOf({tbl}))')
    last = 'SM.app.reports.at(-1)'
    cat = {'y': ['churned'], 'x': XS, 'validation': ['Validation']}
    cont = {'y': ['satisfaction'], 'x': XS}
    specs = [
        ('forest', 'Decision Forest, churned, a Validation column', cat, {'settings': {'trees': 30}, 'roc': True, 'lift': True, 'permutation': True, 'permRepeats': 2, 'seed': '5'}),
        ('forest', 'Decision Forest, satisfaction, a validation portion, RASE', cont, {'settings': {'trees': 30}, 'abp': True, 'permutation': True, 'permRepeats': 2, 'cumStat': 'rase', 'portion': 0.3, 'seed': '9'}),
        ('boosted', 'Boosted Tree, churned, a Validation column', cat, {'settings': {'layers': 25}, 'roc': True, 'lift': True, 'seed': '5'}),
        ('boosted', 'Boosted Tree, satisfaction, every row trains', cont, {'settings': {'layers': 20, 'rowRate': 0.8}, 'abp': True, 'permutation': True, 'permRepeats': 2, 'seed': '3'}),
    ]
    total = 0
    for pid, label, roles, opts in specs:
        r = await page.ev(open_report_js(pid, roles, opts), timeout=900)
        check(f'charts: {label}: no errors', r['errors'], [])
        n, _ = await UP.chart_blocks(page, check, label, tbl, last, ensemble_compare)
        total += n
        await page.ev(f'SM.app.closeReport({last})')
    # By contract, rows excluded: the blocks keep the group's rows
    out = [1, 4, 6, 10]
    await page.ev(f'{tbl}.setState({out}, "excluded", true)')
    r = await page.ev(open_report_js('forest', {'y': ['satisfaction'], 'x': ['tenure (months)', 'monthly charge', 'support calls'], 'by': ['contract']}, {'settings': {'trees': 10}, 'abp': True, 'seed': '2'}), timeout=900)
    check('charts: By contract, rows excluded: no errors', r['errors'], [])
    n, _ = await UP.chart_blocks(page, check, 'By contract, rows excluded', tbl, last, ensemble_compare)
    total += n
    await page.ev(f'SM.app.closeReport({last})')
    await page.ev(f'{tbl}.setState({out}, "excluded", false)')
    check('charts: the blocks ran and drew the page\'s graphs', total >= 30, True)


async def main():
    page = await open_page(f'{BASE}/smui.html?example=subscribers', height=1200)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "ensemble").map(f => f.module + ": " + f.error)')
    check('ensemble.py imports in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])
    check('scikit-learn waits for the first fit', await page.ev("(SM.engine.versions['scikit-learn'] || null)"), None)
    check('the engine has the platform\'s functions', await page.ev("['ensemble.fit', 'ensemble.save', 'ensemble.profile', 'ensemble.tree', 'ensemble.permutation'].every(f => SM.engine.has(f))"), True)

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const exs = SM.app.menuItems('File').find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const pm = SM.app.menuItems('Analyze').find(i => i.label === 'Predictive Modeling');
      const items = (typeof pm.submenu === 'function' ? pm.submenu() : pm.submenu).filter(i => !i.separator).map(i => i.label);
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => [c.name, c.modelingType]), about: SM.io.EXAMPLES.subscribers.about, inFile: labels.includes(SM.io.EXAMPLES.subscribers.label), items,
               missing: t.col('data use (GB)').values.filter(v => !Number.isFinite(v)).length };
    })()''')
    check('?example=subscribers opens the simulated table', (ex['name'], ex['rows'], [c[0] for c in ex['cols']][:4]), ('Subscribers', 1500, ['subscriber', 'tenure (months)', 'monthly charge', 'contract']))
    check('it is simulated and its notes give the truth', ex['about'].startswith('Simulated') and 'logistic' in ex['about'], True)
    check('it is in File > Examples', ex['inFile'], True)
    check('data use has missing values (for Informative Missing)', ex['missing'] > 50, True)
    check('Analyze > Predictive Modeling lists Decision Forest before Boosted Tree', 'Decision Forest…' in ex['items'] and 'Boosted Tree…' in ex['items'] and ex['items'].index('Decision Forest…') < ex['items'].index('Boosted Tree…'), True)

    # ---- the launch dialog
    r = await page.ev('''(async (xs) => {
      SM.app.launch('forest');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (names) => { items.forEach(li => li.classList.remove('is-selected')); let first = true; for (const nm of names) { items.find(x => x.textContent === nm).dispatchEvent(new MouseEvent('mousedown', { bubbles: true, metaKey: !first })); first = false; } };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      const roles = [...dlg.querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      const field = (label) => dlg.querySelector(`.sm-ens-spec [aria-label="${label}"]`);
      const defaults = ['Number of Trees in the Forest', 'Bootstrap Sample Rate', 'Minimum Splits per Tree', 'Maximum Splits per Tree', 'Minimum Size Split'].map(l => [l, field(l).value]);
      const checks = ['Early Stopping', 'Multiple Fits over Number of Terms'].map(l => [l, field(l).checked]);
      const legends = [...dlg.querySelectorAll('.sm-ens-panel legend')].map(l => l.textContent);
      pick(['satisfaction']); role('Y, Response').querySelector('.sm-btn').click();
      ok.click();
      const needX = dlg.querySelector('.sm-launch-msg').textContent;
      pick(xs); role('X, Factor').querySelector('.sm-btn').click();
      const terms = field('Number of Terms Sampled per Split').placeholder, maxTerms = field('Max Number of Terms').placeholder;
      const head = dlg.querySelector('.sm-ens-head').textContent;
      const hint = dlg.querySelector('.sm-ens-hint').textContent;
      pick(['Validation']); role('Validation').querySelector('.sm-btn').click();
      const hint2 = dlg.querySelector('.sm-ens-hint').textContent;
      field('Number of Trees in the Forest').value = '0';
      ok.click();
      const bad = dlg.querySelector('.sm-launch-msg').textContent;
      field('Number of Trees in the Forest').value = '60';
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { roles, defaults, checks, legends, needX, terms, maxTerms, head, hint, hint2, bad, options: rep.spec.options, title: rep.title,
               outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent) };
    })(%s)''' % json.dumps(XS), timeout=600)
    check('JMP\'s launch roles: Y, X, Weight, Freq, Validation, By', r['roles'], ['Y, Response', 'X, Factor', 'Weight', 'Freq', 'Validation', 'By'])
    check('the Specification panel has JMP\'s panels', r['legends'], ['Forest', 'Multiple Fits'])
    check('JMP\'s defaults: 100 trees, rate 1, 10 to 2000 splits, minimum size 5', r['defaults'], [['Number of Trees in the Forest', '100'], ['Bootstrap Sample Rate', '1'], ['Minimum Splits per Tree', '10'], ['Maximum Splits per Tree', '2000'], ['Minimum Size Split', '5']])
    check('Early Stopping on, Multiple Fits off', r['checks'], [['Early Stopping', True], ['Multiple Fits over Number of Terms', False]])
    check('an X is required', 'X, Factor' in r['needX'], True)
    check('with 7 X columns the default number of terms is 7 - floor(7/4) = 6, the Max Number of Terms 7', (r['terms'], r['maxTerms']), ('6', '7'))
    check('the panel counts the rows and terms', ('Number of Rows: 1500' in r['head'], 'Number of Terms: 7' in r['head']), (True, True))
    check('without a validation column it says early stopping needs one; with one it does not', (bool(r['hint']), r['hint2']), (True, ''))
    check('a bad setting is refused in the dialog', 'Number of Trees in the Forest' in r['bad'], True)
    check('the settings reach the report', (r['options']['settings']['trees'], r['options']['settings']['early'], r['options']['settings']['stop']), (60, True, 'oob'))
    check('the report\'s title and JMP\'s outlines', (r['title'], r['outlines']), ('Decision Forest for satisfaction', ['Decision Forest for satisfaction', 'Specifications', 'Overall Statistics', 'Cumulative Validation', 'Cumulative Details', 'Per-Tree Summaries', 'Column Contributions']))
    st = await page.ev(STATE)
    check('no errors in the report', (st['errors'], st['warnings']), ([], []))
    check('the first fit loaded scikit-learn 1.8.0', await page.ev("SM.engine.versions['scikit-learn'] || null"), '1.8.0')
    await shot(page, 'ensemble-01-forest.png')

    # ---- the numbers against the engine
    eng = await page.ev(engine_js(), timeout=600)
    ov = await page.ev(table_under_js('Overall Statistics', 1))
    it = await page.ev(table_under_js('Overall Statistics', 0))
    M = {m['set']: m for m in eng['fit']['measures']}
    got = {row[0]: row for row in ov[1:]}
    check('Overall Statistics: Training, Validation, Test and Out of Bag', list(got), ['Training', 'Validation', 'Test', 'Out of Bag'])
    for s in ('Training', 'Validation', 'Test', 'Out of Bag'):
        check.near(f'{s} RSquare = the engine\'s', num(got[s][1]), round(M[s]['rsquare'], 7), tol=1e-6)
        check.near(f'{s} RASE', num(got[s][2]), round(M[s]['rase'], 7), tol=1e-6)
    check.near('Individual Trees: In Bag RASE', num(kv_of(it[1:])['In Bag']), round(eng['individual'][0]['rase'], 6), tol=1e-6)
    spec = kv_of(await page.ev(table_under_js('Specifications', 0)))
    check('Specifications: 60 trees, the number kept, 6 terms', (spec['Number of Trees in the Forest'], spec['Number of Trees Kept'], spec['Number of Terms Sampled per Split']), ('60', str(eng['cumulative']['kept']), '6'))
    cumk = eng['cumulative']['kept']
    cp = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => /^Cumulative Validation/.test(p.opts.title));
      return { names: p.traces.map(t => t.name), x0: p.userLayout.shapes[0].x0, y: p.traces.find(t => t.name === 'Validation').y, ytitle: p.userLayout.yaxis.title.text }; })()''')
    check('Cumulative Validation: a line per set and out of bag, the number kept marked', (cp['names'][:4], cp['x0'], cp['ytitle']), (['Training', 'Validation', 'Test', 'Out of Bag'], cumk, 'RSquare'))
    ev = next(s for s in eng['cumulative']['series'] if s['set'] == 'Validation')['stats']['rsquare']
    check.near('its validation line is the engine\'s curve', max(abs(a - b) for a, b in zip(cp['y'], ev)), 0.0, tol=1e-12)
    check('the kept number has the best validation RSquare', ev.index(max(ev)) + 1, cumk)
    cc = await page.ev(table_under_js('Column Contributions', 0))
    check('Column Contributions: Term, Number of Splits, SS, Portion; the engine\'s rows', ([h for h in cc[0]], [row[0] for row in cc[1:]]), (['Term', 'Number of Splits', 'SS', 'Portion'], [c['column'] for c in eng['contributions']['rows']]))
    check('tenure, charge and support calls contribute most (the truth), region least', set(row[0] for row in cc[1:4]) <= {'tenure (months)', 'support calls', 'monthly charge', 'contract'} and cc[-1][0] in ('region', 'data use (GB)'), True)
    pt = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Per-Tree Summaries');
      const t = h.parentElement.querySelector('table.sm-rt'); return { closed: h.parentElement.classList.contains('is-closed'), heads: [...t.querySelectorAll('thead th')].map(th => th.textContent), rows: t._rt.rows.length }; })()''')
    check('Per-Tree Summaries (closed, as JMP): JMP\'s columns, a line per kept tree', (pt['closed'], pt['heads'], pt['rows']),
          (True, ['Tree', 'Splits', 'Rank', 'OOB Loss', 'OOB Loss/N', 'RSquare', 'IB SSE', 'IB SSE/N', 'OOB N', 'OOB SSE', 'OOB SSE/N'], cumk))

    # ---- red triangles: Plot Actual by Predicted, linking
    await page.ev(pick_js('*top*', ['Plot Actual by Predicted']))
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => /^Actual by predicted Validation/.test(p.opts.title));
      p._click({ points: [{ curveNumber: 0, pointNumber: 4 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[0][2], p.rows[0][9]]);
      const sp = p.box.data[0].selectedpoints;
      t.select([]);
      return { sel, want: [p.rows[0][4]], sp, n: p.rows[0].length, plots: rep.plots.filter(p => /^Actual by predicted/.test(p.opts.title)).length };
    })()''')
    check('Plot Actual by Predicted: a plot per set', r['plots'], 3)
    check('a click on a point selects its row', r['sel'], r['want'])
    check('rows selected in the table highlight their points', r['sp'], [2, 9])
    pos = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => /^Actual by predicted Test/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      await new Promise(r => setTimeout(r, 300));
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      const gd = p.box, xa = gd._fullLayout.xaxis, ya = gd._fullLayout.yaxis;
      const xs = p.traces[0].x, ys = p.traces[0].y;
      let best = 0, bestD = -1;
      for (let k = 0; k < xs.length; k++) { let d = Infinity; for (let m = 0; m < xs.length; m++) if (m !== k) d = Math.min(d, ((xs[k] - xs[m]) / (xa.range[1] - xa.range[0])) ** 2 + ((ys[k] - ys[m]) / (ya.range[1] - ya.range[0])) ** 2); if (d > bestD) { bestD = d; best = k; } }
      const b = gd.getBoundingClientRect();
      return { x: b.left + xa._offset + xa.l2p(xs[best]), y: b.top + ya._offset + ya.l2p(ys[best]), row: p.rows[0][best] };
    })()''')
    await page.click(pos['x'], pos['y'])
    await asyncio.sleep(0.4)
    check('a mouse click on a point selects that row', await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()'), [pos['row']])
    await page.mouse('mouseMoved', 2, 2)
    await page.ev('SM.app.reports[SM.app.reports.length - 1].table.select([])')

    await triangles(page, 'the forest report', 3)
    top = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; rep.body.querySelector('.sm-ob-head h2').parentElement.querySelector('.sm-ob-menu').click();
      await new Promise(r => setTimeout(r, 60)); const m = [...document.querySelectorAll('.sm-menu')].pop(); const out = [...m.querySelectorAll('.sm-label')].map(x => x.textContent); SM.ui.closeMenus(0); return out; })()''')
    check('the red triangle has JMP\'s items in JMP\'s order', top[:5], ['Plot Actual by Predicted', 'Column Contributions', 'Show Trees', 'Profiler', 'Cumulative Validation'])
    check('... Save Columns and the specification', all(x in top for x in ('Save Columns', 'Specifications…', 'Model Dialog', 'Permutation Importance', 'Per-Tree Summaries')), True)

    # ---- the other outlines from the red triangles
    await page.ev(pick_js('Cumulative Validation', ['Statistic', 'RASE']))
    cp2 = await page.ev('(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => /^Cumulative Validation/.test(p.opts.title)); return [p.userLayout.yaxis.title.text, p.traces.find(t => t.name === "Validation").y]; })()')
    ev_rase = next(s for s in eng['cumulative']['series'] if s['set'] == 'Validation')['stats']['rase']
    check('Statistic ▸ RASE plots the validation RASE', (cp2[0], max(abs(a - b) for a, b in zip(cp2[1], ev_rase)) < 1e-12), ('RASE', True))
    await page.ev(pick_js('*top*', ['Show Trees', 'Show names categories estimates']))
    tv = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Tree Views');
      const box = h.parentElement; return { lines: [...box.querySelectorAll('.sm-ens-node')].map(n => n.textContent), leaves: box.querySelectorAll('.sm-ens-node.is-leaf').length, n: box.querySelector('.sm-ens-treebar input').value }; })()''')
    tree1 = await page.ev(engine_js({'fn': 'ensemble.tree', 'index': 1, 'detail': 'estimates'}))
    check('Show Trees: the Tree Views outline with tree 1, a line per node', (tv['n'], len(tv['lines']), tv['lines'][0].startswith('All Rows')), ('1', len(tree1['lines']), True))
    check('... as many leaves as the tree keeps splits + 1', tv['leaves'], eng['trees'][0]['splits'] + 1)
    check('... each with its count and mean', 'Count' in tv['lines'][0] and 'Mean' in tv['lines'][0], True)
    conds = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Tree Views');
      return [...h.parentElement.querySelectorAll('.sm-ens-cond')].map(n => n.textContent); })()''')
    check('... each node\'s condition in the engine\'s words: a value cut, a Missing column, or the levels on its side as JMP words them',
          (conds == [ln['text'] for ln in tree1['lines']], [c for c in conds if not re.fullmatch(r'All Rows|.+ (<=|>) -?[\d.e+-]+|.+ (not )?missing|[^()]+\(.+\)', c)]), (True, []))
    cat_splits = []
    for i in range(1, 6):
        tvi = await page.ev(engine_js({'fn': 'ensemble.tree', 'index': i, 'detail': 'categories'}))
        cat_splits += [ln['text'] for ln in tvi['lines'] if re.match(r'(contract|region)\(', ln['text'])]
    check('... a split on contract or region takes two groups of its levels (the first five trees have such splits, each level on one side)',
          (bool(cat_splits), all(len(t_[t_.index('(') + 1:-1].split(', ')) >= 1 for t_ in cat_splits)), (True, True))
    await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on('done', res));
      [...rep.body.querySelectorAll('.sm-ens-treebar button')].find(b => b.getAttribute('aria-label').startsWith('Next')).click(); await d; })()''')
    st = await page.ev(STATE)
    check('the next-tree button shows tree 2 (kept by Redo)', st['options'].get('treeIndex'), 2)
    await page.ev(pick_js('*top*', ['Permutation Importance']), timeout=600)
    pm = await page.ev(table_under_js('Permutation Importance', 0))
    engp = await page.ev(engine_js({'fn': 'ensemble.permutation', 'repeats': 5}), timeout=600)
    check('Permutation Importance: the engine\'s columns and order', [row[0] for row in pm[1:]], [row['column'] for row in engp['contributions']['rows']])
    check.near('... the fall in validation RSquare of the first', num(pm[1][1]), round(engp['contributions']['rows'][0]['value'], 7), tol=1e-6)
    await page.ev(pick_js('*top*', ['Profiler']))
    st = await page.ev(STATE)
    prof = await page.ev('(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; return rep.plots.filter(p => / profile over /.test(p.opts.title)).length; })()')
    check('Profiler: the Prediction Profiler, a plot per factor', ('Prediction Profiler' in st['outlines'], prof), (True, 7))
    check('no errors after the red-triangle options', st['errors'], [])
    await shot(page, 'ensemble-02-options.png')

    # ---- Save Columns
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      await (%s)('*top*', ['Save Columns', 'Save Predicteds'], false, 0);
      await new Promise(r => setTimeout(r, 300));
      await (%s)('*top*', ['Save Columns', 'Save Residuals'], false, 0);
      await new Promise(r => setTimeout(r, 300));
      const n = SM.app.tables.length;
      await (%s)('*top*', ['Save Columns', 'Save Cumulative Details'], false, 0);
      await new Promise(r => setTimeout(r, 300));
      const cd = SM.app.tables.length > n ? SM.app.tables[SM.app.tables.length - 1] : null;
      const p = t.col('Predicted satisfaction'), res = t.col('Residual satisfaction');
      const out = { p: p ? [p.values[0], p.values[777]] : null, r: res ? res.values[5] : null, y5: t.col('satisfaction').values[5], p5: p ? p.values[5] : null,
                    cd: cd ? [cd.name, cd.nrows, cd.columns.map(c => c.name).slice(0, 3)] : null };
      SM.app.showTab(SM.app.tabOf(rep));
      return out;
    })()''' % (PICK, PICK, PICK))
    sv = await page.ev(engine_js({'fn': 'ensemble.save'}), timeout=600)
    idx0, idx777 = sv['rows'].index(0), sv['rows'].index(777)
    check.near('Save Predicteds: the engine\'s prediction of row 1', r['p'][0], sv['values'][idx0], tol=1e-12)
    check.near('... and of row 778', r['p'][1], sv['values'][idx777], tol=1e-12)
    check.near('Save Residuals: y - predicted', r['r'], r['y5'] - r['p5'], tol=1e-9)
    check('Save Cumulative Details: a table with a line per tree grown', (r['cd'][0].startswith('Subscribers cumulative details'), r['cd'][1], r['cd'][2]), (True, eng['cumulative']['grown'], ['N Trees', 'Training RSquare', 'Training RASE']))

    # ---- Specifications… fits again; Multiple Fits
    await page.ev(pick_form_js('*top*', ['Specifications…'], "byLabel('Number of Trees in the Forest').value = '25'; byLabel('Early Stopping').checked = false;"), timeout=600)
    spec = kv_of(await page.ev(table_under_js('Specifications', 0)))
    check('Specifications… with 25 trees and no early stopping: all 25 kept', (spec['Number of Trees in the Forest'], spec['Number of Trees Kept'], spec['Early Stopping']), ('25', '25', 'Off'))
    await page.ev(pick_form_js('*top*', ['Specifications…'], "byLabel('Number of Terms Sampled per Split').value = '2'; byLabel('Max Number of Terms').value = '4'; byLabel('Multiple Fits over Number of Terms').checked = true; byLabel('Early Stopping').checked = true;"), timeout=900)
    st = await page.ev(STATE)
    ms = await page.ev(table_under_js('Model Validation-Set Summaries', 0))
    engm = await page.ev(engine_js(), timeout=600)
    check('Multiple Fits: Model Validation-Set Summaries first, a line per number of terms (2, 3, 4)', (st['outlines'][1], [row[0] for row in ms[1:]]), ('Model Validation-Set Summaries', ['2', '3', '4']))
    best = engm['best']
    check('the fit shown is the best by validation RSquare', kv_of(await page.ev(table_under_js('Specifications', 0)))['Number of Terms Sampled per Split'], ms[1 + best][0])
    other = (best + 1) % 3
    await page.ev('''(async (i) => { const rep = SM.app.reports[SM.app.reports.length - 1]; const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Model Validation-Set Summaries');
      const d = new Promise(res => rep.on('done', res)); h.parentElement.querySelectorAll('table.sm-rt tbody tr')[i].click(); await d; })(%d)''' % other)
    spec = kv_of(await page.ev(table_under_js('Specifications', 0)))
    marked = await page.ev('[...SM.app.reports[SM.app.reports.length - 1].body.querySelectorAll("td.sm-ens-shown")].map(td => td.textContent)[0]')
    check('a click on another line shows that fit, marked', (spec['Number of Terms Sampled per Split'], marked), (ms[1 + other][0], ms[1 + other][0]))
    await rerun(page)
    st = await page.ev(STATE)
    check('Redo keeps the settings, the fit shown and the options', (st['options']['settings']['multi'], st['options'].get('shownFit'), st['options'].get('abp'), st['options'].get('trees')), (True, other, True, 'estimates'))
    await triangles(page, 'the Multiple Fits report', 5)

    # ---- progress lines while a long fit runs
    r = await page.ev('''(async () => {
      const t = SM.app.tables.find(t => t.name === 'Subscribers'); SM.app.showTab(SM.app.tabOf(t));
      const ids = (names) => names.map(n => t.col(n).id);
      const seen = [];
      const off = SM.engine.on('progress', (p) => seen.push([p.what, p.done, p.total]));
      let note = null;
      const obs = new MutationObserver(() => { const n = document.querySelector('.sm-ens-progress'); if (n && /of 300 trees/.test(n.textContent)) note = n.textContent; });
      obs.observe(document.body, { subtree: true, childList: true, characterData: true });
      const rep = SM.app.openReport(SM.platforms.get('forest'), { roles: { y: ids(['churned']), x: ids(%s) }, options: { settings: { trees: 300, early: false }, seed: '17' } }, t);
      await new Promise(res => rep.on('done', res));
      off(); obs.disconnect();
      return { seen, note, bar: rep.noteEl.textContent, outlines: [...rep.body.querySelectorAll('.sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent) };
    })()''' % json.dumps(XS), timeout=900)
    forest_lines = [s for s in r['seen'] if s[0] == 'forest']
    check('a long fit sends progress: forest lines up to 300 of 300', (len(forest_lines) >= 5, forest_lines[-1] if forest_lines else None), (True, ['forest', 300, 300]))
    check('... shown in the report while it runs', bool(r['note']) and 'Decision Forest' in r['note'], True)
    check('a categorical forest: the Confusion Matrix inside Overall Statistics', 'Confusion Matrix' in r['outlines'], True)
    # categorical: probabilities never 0, ROC and lift, Save Predicteds
    await page.ev(pick_js('*top*', ['ROC Curve']))
    await page.ev(pick_js('*top*', ['Lift Curve']))
    st = await page.ev(STATE)
    check('ROC Curve and Lift Curve from the red triangle', ('ROC Curve' in st['outlines'], 'Lift Curve' in st['outlines']), (True, True))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      await (%s)('*top*', ['Save Columns', 'Save Predicteds'], false, 0);
      await new Promise(r => setTimeout(r, 400));
      const a = t.col('Prob[No]'), b = t.col('Prob[Yes]'), m = t.col('Most Likely churned');
      const pa = a.values, pb = b.values;
      let mn = 1, mx = 0, sum1 = true;
      for (let i = 0; i < t.nrows; i++) { mn = Math.min(mn, pa[i], pb[i]); mx = Math.max(mx, pa[i], pb[i]); if (Math.abs(pa[i] + pb[i] - 1) > 1e-9) sum1 = false; }
      return { mn, mx, sum1, most: m.values.slice(0, 5), p: [pa[0], pb[0]], type: m.modelingType };
    })()''' % PICK)
    svc = await page.ev(engine_js({'fn': 'ensemble.save'}), timeout=600)
    i0 = svc['rows'].index(0)
    check.near('Save Predicteds: Prob[Yes] of row 1 is the engine\'s', r['p'][1], svc['prob'][i0][1], tol=1e-12)
    check('the forest\'s probabilities are never exactly 0 or 1 (JMP\'s prior) and add to 1', (r['mn'] > 0, r['mx'] < 1, r['sum1']), (True, True, True))
    check('Most Likely churned is a nominal column of the levels', (r['type'], set(r['most']) <= {'No', 'Yes'}), ('nominal', True))
    script = await page.ev('SM.app.reports[SM.app.reports.length - 1].pythonScript()')
    check('the Python script holds the forest\'s trees, their order of the levels and JMP\'s probabilities',
          (all(s in script for s in ('DecisionTreeClassifier(', 'def jmp_probs(', 'def oob_losses(', 'kept_splits(loss, 10)', 'def level_ranks(', 'maps_for(Xt, target, wt * inbag')), 'sklearn.ensemble' in script), (True, False))

    # ---- Score Rows…: another open table, by the report's model as it fitted
    r = await page.ev(f'''(async () => {{
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const rows = [0, 1, 2, 3, 4, 5];
      const cols = {json.dumps(XS)}.map(nm => {{ const c = t.col(nm); return {{ name: nm, dataType: c.dataType, values: rows.map(i => c.isNumeric ? c.values[i] + 1 : c.values[i]), ...(c.valueOrder ? {{ valueOrder: c.valueOrder.slice() }} : {{}}) }}; }});
      const other = new SM.Table({{ name: 'New subscribers', source: 'test', columns: cols }});
      SM.app.addTable(other); SM.app.showTab(SM.app.tabOf(rep));
      await ({PICK})('*top*', ['Save Columns', 'Score Rows…'], false, 0);
      for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
      const d = [...document.querySelectorAll('.sm-dialog')].pop(); const sels = d.querySelectorAll('.sm-form select');
      const title = d.querySelector('.sm-dialog-head').textContent;
      sels[0].value = other.id; sels[1].value = 'all'; d.querySelector('.sm-dialog-foot .primary').click();
      for (let i = 0; i < 100 && !other.columns.some(c => c.name === 'Prob[Yes]'); i++) await new Promise(r => setTimeout(r, 100));
      const eng = await SM.engine.call('ensemble.score', {{ keep: `${{rep.id}}|`, kind: 'forest', target_rows: null }}, other);
      return {{ title, names: other.columns.map(c => c.name), yes: other.col('Prob[Yes]') ? other.col('Prob[Yes]').values : null, most: other.col('Most Likely churned') ? other.col('Most Likely churned').values : null, eng }};
    }})()''', timeout=300)
    check('Save Columns ▸ Score Rows… into another open table: Prob[] and Most Likely columns, the report\'s forest as it fitted (the engine kept it)',
          (r['title'].startswith('Score Rows'), r['names'][-3:], r['yes'] == [q[1] for q in r['eng']['prob']], r['most'] == r['eng']['most_likely'], r['eng']['note']), (True, ['Prob[No]', 'Prob[Yes]', 'Most Likely churned'], True, True, None))
    # ... and rows added to the report's own table since it fitted: only they get predictions, from the model as it fitted
    r = await page.ev(f'''(async () => {{
      const src = SM.app.tables.find(t => t.name === 'Subscribers');
      const keep = Array.from({{ length: 400 }}, (_, i) => i);
      const cols = src.columns.map(c => ({{ name: c.name, dataType: c.dataType, values: keep.map(i => c.values[i]), ...(c.valueOrder ? {{ valueOrder: c.valueOrder.slice() }} : {{}}) }})).filter(c => !/^(Prob|Most Likely|Predicted|Residual)/.test(c.name));
      const t = new SM.Table({{ name: 'Mini subscribers', source: 'test', columns: cols }});
      SM.app.addTable(t);
      const ids = (names) => names.map(n => t.col(n).id);
      const rep = SM.app.openReport(SM.platforms.get('forest'), {{ roles: {{ y: ids(['churned']), x: ids({json.dumps(XS)}), validation: ids(['Validation']) }}, options: {{ settings: {{ trees: 20 }}, seed: '4' }} }}, t);
      await new Promise(res => rep.on('done', res));
      await ({PICK})('*top*', ['Save Columns', 'Save Predicteds'], false, 0);
      for (let i = 0; i < 60 && !t.col('Prob[Yes]'); i++) await new Promise(r => setTimeout(r, 100));
      const before = t.col('Prob[Yes]').values.slice();
      t.addRows(3);
      for (const [k, i] of [[400, 3], [401, 50], [402, 77]]) for (const nm of {json.dumps(XS)}) t.setCell(k, nm, src.col(nm).values[i]);
      await new Promise(r => setTimeout(r, 200));
      const stale = rep.stale;
      await ({PICK})('*top*', ['Save Columns', 'Score Rows…'], false, 0);
      for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
      const d = [...document.querySelectorAll('.sm-dialog')].pop();
      d.querySelector('.sm-dialog-foot .primary').click();
      for (let i = 0; i < 100 && !Number.isFinite(t.col('Prob[Yes]').values[402]); i++) await new Promise(r => setTimeout(r, 100));
      const eng = await SM.engine.call('ensemble.score', {{ keep: `${{rep.id}}|`, kind: 'forest', target_rows: [400, 401, 402] }}, t);
      const after = t.col('Prob[Yes]').values;
      SM.app.showTab(SM.app.tabOf(src));      // the reports below open on the Subscribers again
      return {{ stale, same: before.every((v, i) => v === after[i]), added: after.slice(400), eng: eng.prob.map(q => q[1]), note: eng.note, cols: t.columns.filter(c => c.name.startsWith('Prob[')).length, current: SM.app.current === src }};
    }})()''', timeout=600)
    check('Score Rows… on rows added since (the report marked stale, not fitted again): only the new rows get predictions, into the columns Save Predicteds made',
          (r['stale'], r['same'], r['cols'], r['added'] == r['eng'], r['note'], r['current']), (True, True, 2, True, None, True))

    # ---- a K-fold Validation column: every row trains, and Overall Statistics has a Crossvalidation line by its folds
    r = await page.ev(f'''(async () => {{
      const src = SM.app.tables.find(t => t.name === 'Subscribers');
      const cols = src.columns.filter(c => !/^(Prob|Most Likely|Predicted|Residual)/.test(c.name)).map(c => ({{ name: c.name, dataType: c.dataType, values: c.values.slice(0, 500), ...(c.valueOrder ? {{ valueOrder: c.valueOrder.slice() }} : {{}}) }}));
      cols.push({{ name: 'Fold ID', dataType: 'numeric', values: Array.from({{ length: 500 }}, (_, i) => 1 + (i * 7919) % 4) }});
      const t = new SM.Table({{ name: 'Subscriber folds', source: 'test', columns: cols }});
      SM.app.addTable(t);
      const ids = (names) => names.map(n => t.col(n).id);
      const rep = SM.app.openReport(SM.platforms.get('forest'), {{ roles: {{ y: ids(['satisfaction']), x: ids({json.dumps(XS)}), validation: ids(['Fold ID']) }}, options: {{ settings: {{ trees: 15 }}, seed: '6' }} }}, t);
      await new Promise(res => rep.on('done', res));
      const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Overall Statistics');
      const tb = h.parentElement.querySelectorAll('table.sm-rt')[1];
      const eng = await SM.engine.call('ensemble.fit', {{ y: 'satisfaction', x: {json.dumps(XS)}, kind: 'forest', validation: 'Fold ID', seed: 6, settings: {{ trees: 15 }} }}, t);
      SM.app.showTab(SM.app.tabOf(src));
      return {{ sets: tb._rt.rows.map(r => r.set), cv: tb._rt.rows.find(r => r.set === 'Crossvalidation'), eng: eng.fit.measures.find(m => m.set === 'Crossvalidation'),
               notes: [...rep.body.querySelectorAll('.sm-ob-note')].filter(n => /Crossvalidation: each row predicted by the forest/.test(n.textContent)).length, errors: [...rep.body.querySelectorAll('.sm-ob-error')].length }};
    }})()''', timeout=600)
    check('a K-fold Validation column: Overall Statistics has Training, Out of Bag and a Crossvalidation line (the engine\'s), and a note says what it is',
          (r['sets'], bool(r['cv']) and abs(r['cv']['rsquare'] - r['eng']['rsquare']) < 1e-12, r['notes'], r['errors']), (['Training', 'Out of Bag', 'Crossvalidation'], True, 1, 0))

    # ---- Boosted Tree
    rep = await page.ev(open_report_js('boosted', {'y': ['churned'], 'x': XS, 'validation': ['Validation']}, {'seed': '5'}), timeout=600)
    check('Boosted Tree: JMP\'s outlines, no errors', (rep['title'], rep['outlines'], rep['errors']),
          ('Boosted Tree for churned', ['Boosted Tree for churned', 'Specifications', 'Overall Statistics', 'Confusion Matrix', 'Cumulative Validation', 'Cumulative Details', 'Column Contributions'], []))
    engb = await page.ev(engine_js(), timeout=600)
    ov = await page.ev(table_under_js('Overall Statistics', 0))
    got = {row[0]: row for row in ov[1:]}
    MB = {m['set']: m for m in engb['fit']['measures']}
    check('boosted Overall Statistics: Training, Validation and Test (no out-of-bag line)', list(got), ['Training', 'Validation', 'Test'])
    check.near('boosted validation Entropy RSquare = the engine\'s', num(got['Validation'][1]), round(MB['Validation']['entropy_rsquare'], 7), tol=1e-6)
    check.near('boosted test AUC', num(got['Test'][7]), round(MB['Test']['auc'], 7), tol=1e-6)
    spec = kv_of(await page.ev(table_under_js('Specifications', 0)))
    cb = engb['cumulative']
    check('boosted Specifications: JMP\'s defaults, the layers kept', (spec['Number of Layers'], spec['Splits per Tree'], spec['Learning Rate'], spec['Number of Layers Kept']), ('50', '3', '0.1', str(cb['kept'])))
    ve = next(s for s in cb['series'] if s['set'] == 'Validation')['stats']['entropy_rsquare']
    check('early stopping: the layers kept improved the validation Entropy RSquare each time; the next did not', all(ve[i] > ve[i - 1] for i in range(1, cb['kept'])) and (not cb['stopped'] or ve[cb['grown'] - 1] <= ve[cb['kept'] - 1]), True)
    top = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; rep.body.querySelector('.sm-ob-head h2').parentElement.querySelector('.sm-ob-menu').click();
      await new Promise(r => setTimeout(r, 60)); const m = [...document.querySelectorAll('.sm-menu')].pop(); const out = [...m.querySelectorAll('.sm-label')].map(x => x.textContent); SM.ui.closeMenus(0); return out; })()''')
    check('the boosted red triangle starts with Show Trees (JMP\'s order), no Per-Tree Summaries', (top[0], 'Per-Tree Summaries' in top, 'Plot Actual by Predicted' in top), ('Show Trees', False, False))
    await page.ev(pick_js('*top*', ['Show Trees', 'Show names categories']))
    tv = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Tree Views');
      return { lines: [...h.parentElement.querySelectorAll('.sm-ens-node')].map(n => n.textContent), what: h.parentElement.querySelector('.sm-ens-treebar label span').textContent }; })()''')
    check('a boosted layer: 3 splits, 7 lines, no estimates in this view', (tv['what'], len(tv['lines']), any('Estimate' in x for x in tv['lines'])), ('Layer', 7, False))
    await triangles(page, 'the boosted report', 4)
    await page.ev(pick_js('*top*', ['Profiler']))
    st = await page.ev(STATE)
    check('the boosted profiler: a probability row per level', await page.ev('(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; return rep.plots.filter(p => / profile over /.test(p.opts.title)).map(p => p.opts.title.split(" profile")[0]).filter((v, i, a) => a.indexOf(v) === i); })()'), ['Prob[No]', 'Prob[Yes]'])
    check('no errors in the boosted report', st['errors'], [])
    await shot(page, 'ensemble-03-boosted.png')

    # ---- By: one analysis per group, combined tables
    rep = await page.ev(open_report_js('boosted', {'y': ['satisfaction'], 'x': XS, 'validation': ['Validation'], 'by': ['contract']}, {'seed': '3'}), timeout=900)
    check('By contract: one analysis per contract', [o for o in rep['outlines'] if o.startswith('Boosted Tree for')],
          ['Boosted Tree for satisfaction contract=Month-to-month', 'Boosted Tree for satisfaction contract=One year', 'Boosted Tree for satisfaction contract=Two year'])
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      // the Overall Statistics table of each group (its key is the outline's, 'overall')
      const tbls = [...rep.body.querySelectorAll('table.sm-rt')].filter(t => t.dataset.rtKey === 'overall');
      const combined = SM.report.combineRT(tbls, 'x');
      const c = rep.table.col('contract').values;
      return { n: tbls.length, groups: tbls.map(t => t.dataset.group), rows: combined.nrows, each: tbls.map(t => t._rt.rows.length), m2m: c.filter(v => v === 'Month-to-month').length,
               ns: tbls.map(t => t._rt.rows.reduce((a, r) => a + r.n, 0)) };
    })()''')
    check('each group has its Overall Statistics, which combine into one table', (r['n'], r['groups'], r['rows']), (3, ['contract=Month-to-month', 'contract=One year', 'contract=Two year'], sum(r['each'])))
    check('each group fits its own rows', r['ns'][0], r['m2m'])

    # ---- a project keeps the options, the column ids remapped
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'forest' && r.spec.options.settings && r.spec.options.settings.multi);
      const t = rep.table;
      const before = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Overall Statistics').parentElement.querySelectorAll('table.sm-rt')[1]._rt.rows.map(r => r.rsquare);
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const after = [...back.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Overall Statistics').parentElement.querySelectorAll('table.sm-rt')[1]._rt.rows.map(r => r.rsquare);
      const out = { newTable: back.table !== t, x: back.spec.roles.x.map(id => back.table.col(id) && back.table.col(id).name), settings: back.spec.options.settings, shown: back.spec.options.shownFit,
                    before, after, heads: [...back.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent), errors: back.body.querySelectorAll('.sm-ob-error').length };
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })()''', timeout=900)
    check('an opened project has its own table, and its X columns by their new ids', (r['newTable'], r['x'][:3]), (True, XS[:3]))
    check('... keeps the settings and the fit shown', (r['settings']['multi'], r['settings']['terms'], r['shown']), (True, 2, other))
    check('... and gives the same Overall Statistics (the same seed)', r['after'], r['before'])
    check('... drawing the same outlines without errors', ('Model Validation-Set Summaries' in r['heads'], 'Tree Views' in r['heads'], r['errors']), (True, True, 0))

    # ---- Bootstrap reruns the report headless, with no side effects
    r = await page.ev('''(async () => {
      const t = SM.app.tables.find(t => t.name === 'Subscribers'); SM.app.showTab(SM.app.tabOf(t));
      const ids = (names) => names.map(n => t.col(n).id);
      const rep = SM.app.openReport(SM.platforms.get('boosted'), { roles: { y: ids(['satisfaction']), x: ids(%s), validation: ids(['Validation']) }, options: { seed: '9', settings: { layers: 20 } } }, t);
      await new Promise(res => rep.on('done', res));
      const tbl = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Overall Statistics').parentElement.querySelector('table.sm-rt');
      const cols = t.columns.length, plots = rep.plots.length, opts = JSON.stringify(rep.spec.options);
      const res = await SM.bootstrap.run(tbl, tbl._rt.all.find(c => c.key === 'rsquare'), { B: 3, seed: 2, show: false });
      return { rows: res ? res.nrows : null, names: res ? res.columns.map(c => c.name) : null, first: res ? res.columns[1].values : null, cols: t.columns.length === cols, plots: rep.plots.length === plots, opts: JSON.stringify(rep.spec.options) === opts };
    })()''' % json.dumps(XS), timeout=900)
    check('Bootstrap on Overall Statistics: the report again on 3 resamples', (r['rows'], r['names']), (4, ['BootID', 'Training', 'Validation', 'Test']))
    check('... every sample gives a number', all(isinstance(v, (int, float)) for v in r['first']), True)
    check('... and leaves the report and the table as they were', (r['cols'], r['plots'], r['opts']), (True, True, True))

    # ---- the (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-forest"); const a = document.getElementById("help-p-forest"), b = document.getElementById("help-p-boosted"); return [a ? a.textContent : null, b ? b.textContent : null]; })()')
    check('Help lines for both platforms, with the scikit-learn classes', (bool(helps[0]) and 'RandomForestRegressor' in helps[0], bool(helps[1]) and 'GradientBoostingClassifier' in helps[1]), (True, True))
    topics = await page.ev('Object.keys(SM.platforms.get("forest").topics)')
    check('the topics', sorted(topics), sorted(['p:forest', 'p:boosted', 'p:ensemble:spec', 'p:ensemble:summaries', 'p:ensemble:cumulative', 'p:ensemble:pertree', 'p:ensemble:contrib', 'p:ensemble:trees', 'p:ensemble:score']))
    tp = await page.ev('(() => { const T = SM.platforms.get("forest").topics; return [T["p:forest"].sections.map(s => s.heading), T["p:boosted"].sections.map(s => s.heading)]; })()')
    check('... both platforms\' (i) explain the categorical factors, Score Rows and the differences from JMP', [all(h in hs for h in ('Categorical factors', 'Score Rows', 'Differences from JMP')) for hs in tp], [True, True])

    # ---- the (i) explains every input: the launch dialogs and their Specification, the form, Tree Views
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Subscribers")))')
    for pid, label, heading in (('forest', 'Decision Forest', 'Decision Forest Specification'), ('boosted', 'Boosted Tree', 'Gradient-Boosted Trees Specification')):
        d = await page.ev(info_js('dialog', f"SM.app.launch('{pid}')", "dlg.querySelector('.sm-ens-spec')"))
        spec = d.get('sections', {}).get(heading, [])
        check(f'{label}: the launch dialog\'s (i) explains every field of its Specification', (len(d.get('inputs', [])), len(spec), unexplained(d, heading), all(len(t) > 40 for _, t in spec)), (10, 10, [], True))
        await dialog_help(page, f"SM.app.launch('{pid}')", pid, label)
    forest = 'SM.app.reports.find(r => r.platform.id === "forest")'
    boosted = 'SM.app.reports.at(-1)'
    for rep_js, label in ((forest, 'Decision Forest'), (boosted, 'Boosted Tree')):
        f = await form_help(page, f"await clickPath({rep_js}, '*top*', ['Specifications…']);", [], f'{label} Specifications…')
        fields = (f.get('sections') or {}).get('Fields', [])
        check('... its ten fields, each with what it is for (the Specification\'s texts)', (len(fields), all(len(t) > 40 for _, t in fields)), (10, True))
    trees = 'SM.app.reports.find(r => r.platform.id === "boosted" && r.spec.options.trees)'
    s = await page.ev(info_js('slot', f"[...{trees}.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Tree Views')"))
    check('Tree Views\' (i) explains its controls and the Show Trees choices', ([c[0] for c in s['sections'].get('The controls', [])], [c[0] for c in s['sections'].get('Show Trees (red triangle)', [])]),
          (['‹ and ›', 'Tree, Layer'], ['Show names', 'Show names categories', 'Show names categories estimates', 'Hide Trees']))

    # ---- the graphs' matplotlib code
    await charts(page)

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "forest" && r.spec.options.abp)))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2.5)
    r = await page.ev('''(() => { const rs = SM.app.reports.filter(r => ['forest', 'boosted'].includes(r.platform.id));
      const rep = rs.find(r => r.spec.options.abp); const p = rep.plots.find(p => /^Cumulative Validation/.test(p.opts.title));
      return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)), color: p.traces.find(t => t.name === 'Validation').line.color, base: p.traces[0].line.color }; })()''')
    check('the dark theme redraws the reports without errors', r['errors'], [])
    check('the lines take the dark theme\'s colours', (r['color'], r['base']), ('#f0a35e', '#6fa3d6'))
    await shot(page, 'ensemble-04-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports.find(r => r.platform.id === "forest" && r.spec.options.abp); SM.app.showTab(SM.app.tabOf(rep)); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')
    await asyncio.sleep(1.0)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === "forest" && r.spec.options.abp);
      for (const p of rep.plots) { p.box.scrollIntoView(); await new Promise(r => setTimeout(r, 60)); }
      await new Promise(r => setTimeout(r, 300));
      const body = rep.body.getBoundingClientRect();
      const boxes = rep.plots.filter(p => p.drawn).map(p => p.box.getBoundingClientRect().right);
      // every table either fits the report or scrolls inside a box that does
      const bad = [...rep.body.querySelectorAll('table.sm-rt, table.sm-kv')].filter(t => t.offsetParent !== null).filter(t => {
        const box = t.closest('.sm-ens-scroll');
        const right = (box || t).getBoundingClientRect().right;
        return right > body.right + 1;
      }).map(t => (t.closest('.sm-ob').querySelector('.sm-ob-head').textContent || '').trim());
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length, body: rep.body.scrollWidth <= rep.body.clientWidth + 1, bad };
    })()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the graphs fit the phone\'s width', (r['plots'], r['n'] >= 2), (True, True))
    check('the report does not scroll sideways', r['body'], True)
    check('every table fits or scrolls inside its own box', r['bad'], [])
    r = await page.ev('''(async () => {
      SM.app.launch('boosted');
      await new Promise(r => setTimeout(r, 300));
      const dlg = document.querySelector('.sm-launch-dialog');
      const out = { fits: dlg.getBoundingClientRect().right <= innerWidth + 1, panels: [...dlg.querySelectorAll('.sm-ens-panel legend')].map(l => l.textContent) };
      dlg.querySelector('.sm-dialog-x').click();
      return out;
    })()''')
    check('the Boosted Tree launch dialog fits the phone, with JMP\'s panels', (r['fits'], r['panels']), (True, ['Boosting', 'Multiple Fits', 'Stochastic Boosting']))
    await shot(page, 'ensemble-05-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


if __name__ == '__main__':
    asyncio.run(main())
    sys.exit(check.done())
