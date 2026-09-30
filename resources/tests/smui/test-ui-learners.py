#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Predictive Modeling > K Nearest
Neighbors, Naive Bayes and Support Vector Machines.

The simulated Orchard example opens from the URL and File > Examples, and
the three platforms sit in Analyze > Predictive Modeling in that order;
scikit-learn is not loaded at the start and comes with the first call. The
launch dialogs have their roles (no Weight or Freq for K Nearest Neighbors,
a nominal or ordinal Y for Naive Bayes) and options, and refuse bad values.
K Nearest Neighbors: the misclassification rates of K = 1 and K = 5 are the
ones computed here by brute force on the standardized factors (a training
row not its own neighbour, a tied vote at random from the report's seed), the best K is
marked, a click on a line of the table or a point of the plot shows another
K, Save Predicteds agrees with the Measures of Fit and Save Near Neighbor
Rows with the neighbours found here; a continuous response gives RASE. Naive
Bayes: the saved probabilities are the ones computed here from the engine's
class parameters (normal densities, smoothed level shares), the Smoothing
dialog changes alpha. Support Vector Machines: Gamma defaults to one over
the columns of X, the saved most likely levels agree with Fit Details, the
decision boundary's points select their rows (one by a real mouse click) and
table selections highlight them, the tuning design and the linear kernel
come from the red triangle, a continuous response saves predictions and
residuals. The shared parts (decisions()): the Decision Threshold's numbers
against its code and predictive.py, its stacked bars of the classifications,
the threshold typed, slid, dragged with the mouse and clicked, Set Threshold
to, the target level, a true event rate, Save Threshold Formula; By groups,
each group's own threshold and target level (typed in one, the other left
alone; its confusion matrices; Save Threshold Formula and Save Profit
Columns within the group on its own probabilities; a project, and an older
one with a single threshold); the ROC Table; the decile table; the Naive
Model; a Profit Matrix with its table, code, Most Profit and Save Profit
Columns; Group Metrics with equal false positive rates and Save Decision
Column; a project; the mosaic's links; Distance Weights and Standardize;
Score Rows into another table; Naive Bayes' Save Prediction Formula, live;
the dark theme and phone width. Every red triangle opens; the profiler draws and answers a new
value; Bootstrap reruns the platforms headless; By gives one analysis per
group with combined tables; Redo and a project keep the options; every (i)
has a topic and every Help link a target; the launch dialogs' (i) give every
role and option its help, and the forms' (i) each of their fields; the
reports draw in the dark theme and at phone width without a sideways page
scroll.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-learners.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import importlib.util
import json
import os
import re
import sys

import numpy as np

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine
from test_charts import GRAPHS_JS

# the predictive platforms' chart helpers (test-ui-partition.py has them: PM_JS, chart_blocks, check_*)
_spec = importlib.util.spec_from_file_location('ui_partition_charts', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test-ui-partition.py'))
UP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(UP)

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
W, S, F = 'weight (g)', 'sugar (°Bx)', 'firmness (N)'
XS = [W, S, F, 'skin']


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('%', '').replace('*', '').replace('<', ''))


# Pick an item from an outline's red triangle: path is the labels down the
# submenus; wait: wait for the report to run again; which: the n-th outline
# with that title (By groups repeat them).
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
    // the last menu open that has the item (a submenu the pointer happens to open is passed over)
    const menus = [...document.querySelectorAll('.sm-menu')];
    const has = (mm) => [...mm.querySelectorAll('button')].some(x => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === path[i]);
    const m = [...menus].reverse().find(has) || menus[menus.length - 1];
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


# The same for an item that opens a form: values fill the form's fields in
# order (a boolean ticks a check box), then OK, then the report runs again.
PICK_FORM = '''
(async (title, path, values) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await (%s)(title, path, false, 0);
  for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 100));
  const d = [...document.querySelectorAll('.sm-dialog')].pop();
  const inputs = [...d.querySelectorAll('.sm-form input, .sm-form select')];
  values.forEach((v, i) => { if (v === null) return; if (typeof v === 'boolean') inputs[i].checked = v; else inputs[i].value = String(v); });
  const done = new Promise(res => rep.on('done', res));
  d.querySelector('.sm-dialog-foot .primary').click();
  await done;
  return [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
})
''' % PICK


def pick_form_js(title, path, values):
    return f'({PICK_FORM})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(values)})'


# Open every red triangle of the last report and every submenu in it, as a
# click does: their items are built, none is run.
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

# K nearest neighbours by brute force on the Orchard table: the continuous
# factors standardized by the training rows (n - 1), skin a 0/1 column per
# level, a training row not its own neighbour; a tied vote is broken in Python here, by the seed.
BRUTE = '''
(() => {
  const t = SM.app.tables.find(t => t.name === 'Orchard');
  const n = t.nrows, v = t.col('Validation').values, y = t.col('variety').values, skin = t.col('skin').values;
  const tr = [...Array(n).keys()].filter(i => v[i] === 0);
  const z = ['%s', '%s', '%s'].map(nm => {
    const c = t.col(nm).values, xs = tr.map(i => c[i]);
    const m = xs.reduce((a, b) => a + b, 0) / xs.length;
    const sd = Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length - 1));
    return c.map(x => (x - m) / sd);
  });
  const F = [...Array(n).keys()].map(i => [...z.map(c => c[i]), ...['green', 'yellow', 'red'].map(l => (skin[i] === l ? 1 : 0))]);
  const d2 = (a, b) => a.reduce((s, x, k) => s + (x - b[k]) ** 2, 0);
  const near = (i, K) => tr.filter(j => j !== i).map(j => [d2(F[i], F[j]), j]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).slice(0, K).map(c => c[1]);
  const L = ['Early', 'Mid', 'Late'];
  const rate = (set, K) => {
    const rows = [...Array(n).keys()].filter(i => v[i] === set);
    let wrong = 0;
    for (const i of rows) { const nb = near(i, K); const votes = L.map(l => nb.filter(j => y[j] === l).length); if (L[votes.indexOf(Math.max(...votes))] !== y[i]) wrong++; }
    return wrong / rows.length;
  };
  const val = [...Array(n).keys()].filter(i => v[i] === 1).slice(0, 25);
  // the votes of the 5 nearest (a tie is broken in Python, by the report's seeded numbers)
  const votes5 = (set) => [...Array(n).keys()].filter(i => v[i] === set).map(i => { const nb = near(i, 5); return [i, L.map(l => nb.filter(j => y[j] === l).length), L.indexOf(y[i])]; });
  return { t1: rate(0, 1), v1: rate(1, 1), t5: rate(0, 5), v5: rate(1, 5), first: val.map(i => [i, near(i, 1)[0] + 1]), votes5t: votes5(0), votes5v: votes5(1) };
})()
''' % (W, S, F)


async def triangles(page, name, least):
    r = await page.ev(TRIANGLES)
    ok = isinstance(r, dict) and not r['errors'] and r['triangles'] >= least and r['items'] > r['triangles']
    check(f'every red triangle of {name} opens, with its submenus', ok, True)
    if not ok:
        print('   ', r)


async def rerun(page):
    await page.ev('(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')


# The launch dialog of a platform: roles filled by name, options by label, then OK.
LAUNCH = '''
(async (id, roles, opts) => {
  SM.app.launch(id);
  await new Promise(r => setTimeout(r, 250));
  const dlg = [...document.querySelectorAll('.sm-launch-dialog')].pop();
  const items = [...dlg.querySelectorAll('.sm-pick-list li')];
  const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); const li = items.find(x => x.textContent === name); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
  const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
  const msgs = [];
  for (const [label, names] of roles) for (const nm of names) { pick(nm); role(label).querySelector('.sm-btn').click(); msgs.push(dlg.querySelector('.sm-launch-msg').textContent); }
  const labels = [...dlg.querySelectorAll('.sm-launch-opts label')];
  for (const [label, value] of opts) {
    const lab = labels.find(l => l.textContent.trim().startsWith(label));
    const i = lab.querySelector('input, select');
    if (typeof value === 'boolean') i.checked = value; else i.value = String(value);
  }
  const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
  const before = SM.app.reports.length;
  ok.click();
  // the report is made at once and runs asynchronously: listen before anything is awaited
  const opened = SM.app.reports.length > before;
  const done = opened ? new Promise(res => SM.app.reports[SM.app.reports.length - 1].on('done', res)) : null;
  const msg = dlg.querySelector('.sm-launch-msg').textContent;
  const shown = [...dlg.querySelectorAll('.sm-role')].filter(r => !r.hidden).map(r => r.querySelector('.sm-btn').textContent);
  const optLabels = labels.map(l => l.textContent.trim());
  if (!opened) { [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'Cancel').click(); return { opened, msg, msgs, shown, optLabels }; }
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await done;
  return { opened, msg, msgs, shown, optLabels, options: rep.spec.options, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
           errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 300)) };
})
'''


def launch_js(pid, roles, opts=()):
    return f'({LAUNCH})({json.dumps(pid)}, {json.dumps(roles)}, {json.dumps(list(opts))})'


# A Save Columns item of the top red triangle, and the columns it added.
SAVE = '''
(async (path) => {
  const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
  const before = t.columns.length;
  await (%s)('*top*', path, false, 0);
  for (let i = 0; i < 80 && t.columns.length === before; i++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 200));
  return t.columns.slice(before).map(c => ({ name: c.name, type: c.modelingType, values: c.values }));
})
''' % PICK


def save_js(path):
    return f'({SAVE})({json.dumps(path)})'



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


def decision_compare(check, lab, g, F):
    """The graphs of the shared Decision Threshold, lift and group parts (smui-predict.js), against their code's
    figure: False when the graph is not one of them. Used by test-ui-screening.py too."""
    t = g['label'] or ''
    ax = F['axes'][0]
    if t.startswith('Fitted probabilities'):
        pts = [p for tr in g['traces'] if 'markers' in (tr.get('mode') or '') for p in UP.curve_pts(tr)]
        check.near(f'{lab}: every row at its probability, jittered in its actual level\'s band', UP.maxdiff(UP.flat(UP.scatter_pts(ax)), UP.flat(pts)), 0, 1e-12)
        cut = g['shapes'][0]['x0']
        check(f'{lab}: the threshold dashed', any(ln['x'][:2] == [cut, cut] and ln['ls'] == '--' for ln in ax['lines']), True)
        UP.check_titles(check, lab, g, F)
        return True
    if t.startswith('Classification at the threshold'):
        # a bar per actual level (the first at the bottom), cut into the shares called each level, stacked in the levels' order
        bars = [tr for tr in g['traces'] if tr.get('type') == 'bar']
        want, left = [], [0.0] * len(bars[0]['x'])
        for tr in bars:
            want += [(round(left[k], 9), round(v, 9)) for k, v in enumerate(tr['x'])]
            left = [a_ + b_ for a_, b_ in zip(left, tr['x'])]
        check(f'{lab}: each actual level\'s bar cut into the shares called each level', [(round(q['x'], 9), round(q['w'], 9)) for q in ax['bars']], want)
        check(f'{lab}: the actual levels up the axis, the levels called in the legend, their colours', ([x for x in ax['yticklabels'] if x], F['legend'] or ax['legend'], sorted({q['fc'][:7] for q in ax['bars']})),
              (bars[0]['y'], [tr['name'] for tr in bars], sorted({tr['mcolor'] for tr in bars})))
        UP.check_titles(check, lab, g, F)
        return True
    if ' by threshold' in t:
        # every curve at every threshold, its gaps (a measure with nothing to divide) where the page has them
        ok = [UP.find_line(ax, tr['x'], tr['y'], rel=1e-12, abs_=1e-12) is not None for tr in g['traces'] if 'lines' in (tr.get('mode') or '') and len(tr.get('x') or []) > 2]
        check(f'{lab}: every curve at every threshold (gaps where a measure has nothing to divide)', (len(ok) > 0, ok), (True, [True] * len(ok)))
        cut = g['shapes'][0]['x0']
        check(f'{lab}: the threshold in use dashed', any(ln['x'][:2] == [cut, cut] and ln['ls'] == '--' for ln in ax['lines']), True)
        names = [tr['name'] for tr in g['traces'] if tr.get('showlegend') is not False and tr.get('name')]
        if len(names) > 1:
            check(f'{lab}: the legend', F['legend'] or ax['legend'], names)
        UP.check_titles(check, lab, g, F)
        return True
    if t.startswith('Profit ') or t.startswith('Gains '):
        tr0 = [tr for tr in g['traces'] if tr.get('mode') == 'lines' and len(tr.get('x') or []) > 2]
        ok = []
        for i, tr in enumerate(tr0):
            ln = next((q for q in ax['lines'] if q['label'] == tr['name']), None) if tr.get('name') else None
            ln = ln or (ax['lines'][i] if i < len(ax['lines']) else None)
            ok.append(bool(ln) and UP.subset_in_order(UP.curve_pts(tr), list(zip(ln['x'], ln['y'])), tol=1e-9))
        check(f'{lab}: every curve through the page\'s points', (len(ok) > 0, ok), (True, [True] * len(ok)))
        ref = [tr for tr in g['traces'] if tr.get('mode') == 'lines' and len(tr.get('x') or []) == 2]
        check(f'{lab}: the dotted reference', all(UP.find_line(ax, tr['x'], tr['y'], rel=1e-9) is not None for tr in ref), True)
        UP.check_titles(check, lab, g, F)
        return True
    if t.startswith('Mosaic '):
        want = []
        for tr in g['traces']:
            if tr.get('type') != 'bar':
                continue
            for c, w_, h, b0 in zip(tr['x'], tr['width'], tr['y'], tr['base']):
                want.append((round(c - w_ / 2, 9), round(b0, 9), round(w_, 9), round(h, 9)))
        got = [(round(q['x'], 9), round(q['y'], 9), round(q['w'], 9), round(q['h'], 9)) for q in ax['bars']]
        check(f'{lab}: each actual level\'s bar cut by the shares called', sorted(got), sorted(want))
        check(f'{lab}: the levels in the legend', F['legend'], [tr['name'] for tr in g['traces'] if tr.get('type') == 'bar'])
        UP.check_titles(check, lab, g, F)
        return True
    if t.startswith('False positive rates by') or t.startswith('False negative rates by'):
        # Model Screening's Group Metrics: a bar per method in each group (the methods' bars one after another)
        bars = [tr for tr in g['traces'] if tr.get('type') == 'bar']
        want = [v for tr in bars for v in tr['y']]
        got = [q['h'] for q in ax['bars']]
        same = len(got) == len(want) and all((v is None and (h is None or h != h)) or (v is not None and h is not None and abs(h - v) < 1e-12) for h, v in zip(got, want))
        check(f'{lab}: each method\'s rate in each group, a bar each', same, True)
        check(f'{lab}: the groups, the methods in the legend, each method\'s colour', ([x for x in ax['xticklabels'] if x], ax['legend'], [q['fc'][:7] for q in ax['bars']][::max(1, len(bars[0]['y']))]),
              (bars[0]['x'], [tr['name'] for tr in bars], [tr['mcolor'] for tr in bars]))
        UP.check_titles(check, lab, g, F)
        return True
    if t.startswith('False positive and negative rates by'):
        want = [v for tr in g['traces'] if tr.get('type') == 'bar' for v in tr['y']]
        check.near(f'{lab}: each group\'s false positive and negative rates', UP.maxdiff([q['h'] for q in ax['bars']], want), 0, 1e-12)
        check(f'{lab}: the groups, the legend', ([x for x in ax['xticklabels'] if x], ax['legend']), (g['traces'][0]['x'], [tr['name'] for tr in g['traces']]))
        UP.check_titles(check, lab, g, F)
        return True
    return False


def learners_compare(lab, g, F):
    t = g['label']
    ax = F['axes'][0]
    if decision_compare(check, lab, g, F):
        return
    if t.endswith(' by K'):
        UP.check_lines(check, lab, g, F)
        check(f'{lab}: the best K named', [x['s'].strip() for x in ax['texts']], g['annotations'])
        check(f'{lab}: the sets in the legend', F['legend'], [tr['name'] for tr in g['traces'] if tr.get('mode') == 'lines+markers'])
    elif t == 'Tuning design':
        design = next(tr for tr in g['traces'] if tr.get('name') == 'Design')
        best = next(tr for tr in g['traces'] if tr.get('name') == 'Best')
        if design.get('mode') == 'markers':
            check.near(f'{lab}: every point of the design at its Cost and Gamma', UP.maxdiff(UP.flat(ax['scatter'][0]['xy']), UP.flat(UP.curve_pts(design))), 0, 1e-9)
            check.near(f'{lab}: ... coloured by its criterion: the best marked', UP.maxdiff(ax['scatter'][1]['xy'][0], [best['x'][0], best['y'][0]]), 0, 1e-9)
            check(f'{lab}: log axes, the titles', (ax['xscale'], ax['yscale'], ax['xlabel'], ax['ylabel'], ax['title']), ('log', 'log', 'Cost', 'Gamma', t))
        else:
            check(f'{lab}: the criterion by Cost', UP.find_line(ax, design['x'], design['y'], rel=1e-9) is not None, True)
            check(f'{lab}: the best marked', any(ln['marker'] == 'o' and UP.close(ln['x'], best['x'], 1e-9) and UP.close(ln['y'], best['y'], 1e-9) for ln in ax['lines']), True)
            check(f'{lab}: a log axis, the titles', (ax['xscale'], ax['xlabel'], ax['ylabel'], ax['title']), ('log', 'Cost', g['titles']['y'], t))
        check(f'{lab}: the graph\'s size', F['size'], [g['w'] / 100, g['h'] / 100])
    elif t.startswith('Decision boundary over') or t.startswith('Prediction surface over'):
        surf = next(tr for tr in g['traces'] if tr.get('type') in ('heatmap', 'contour') and tr.get('z') is not None)
        z = [v for row in surf['z'] for v in row]
        check.near(f'{lab}: the model over the grid (the shading), the other factors held', UP.maxdiff(ax['images'][0]['data'] if ax['images'] else [], z), 0, 1e-6)
        levels = sorted(v for c in ax['polys'] if 'contour' in c for v in c['contour'])
        if t.startswith('Decision boundary') and any(tr.get('name') == 'Boundary' for tr in g['traces']):
            check(f'{lab}: the boundary (0) and the margins (±1)', levels, [-1.0, 0.0, 1.0])
        pts = sorted((round(a, 9), round(b, 9)) for tr in g['traces'] if tr.get('type') == 'scatter' and tr.get('name') != 'Support vectors' for a, b in UP.curve_pts(tr))
        got = sorted((round(a, 9), round(b, 9)) for sc in ax['scatter'] if sc['sizes'][:1] != [100.0] for a, b in sc['xy'])
        check(f'{lab}: every row at its two factors\' values', (len(got), got == pts), (len(pts), True))
        rings = [tr for tr in g['traces'] if tr.get('name') == 'Support vectors']
        got_r = sorted((round(a, 9), round(b, 9)) for sc in ax['scatter'] if sc['sizes'][:1] == [100.0] for a, b in sc['xy'])
        check(f'{lab}: the support vectors ringed (when the page rings them)', got_r, sorted((round(a, 9), round(b, 9)) for tr in rings for a, b in UP.curve_pts(tr)))
        check(f'{lab}: the legend', F['legend'], [tr['name'] for tr in g['traces'] if tr.get('showlegend')])
        check(f'{lab}: the grid\'s range, the titles', (ax['xlim'], ax['ylim'], ax['xlabel'], ax['ylabel'], ax['title']),
              ([surf['x'][0], surf['x'][-1]], [surf['y'][0], surf['y'][-1]], g['titles']['x'], g['titles']['y'], t))
        check(f'{lab}: the graph\'s size', F['size'], [g['w'] / 100, g['h'] / 100])
    else:
        check(f'{lab}: a graph this test knows', t, None)


async def charts(page):
    """Every graph of K Nearest Neighbors', Naive Bayes' and Support Vector Machines' reports: its block
    under it, run in the page, its figure the graph's."""
    await page.ev(GRAPHS_JS)
    await page.ev(UP.PM_JS)
    await page.ev('__gr.idle()')
    tbl = "SM.app.tables.find((t) => t.name === 'Orchard')"
    await page.ev(f'SM.app.showTab(SM.app.tabOf({tbl}))')
    last = 'SM.app.reports.at(-1)'
    val = {'validation': ['Validation']}
    specs = [
        ('knn', 'K Nearest Neighbors, variety', {'y': ['variety'], 'x': XS, **val}, {'k': 8, 'roc': True, 'lift': True}),
        ('knn', 'K Nearest Neighbors, shelf life, K = 3 picked', {'y': ['shelf life (days)'], 'x': XS, **val}, {'k': 6, 'knnK': 3}),
        ('naivebayes', 'Naive Bayes, grade', {'y': ['grade'], 'x': XS, **val}, {'roc': True, 'lift': True}),
        ('svm', 'Support Vector Machines, grade, a tuning design', {'y': ['grade'], 'x': XS, **val}, {'tune': True, 'points': 8, 'roc': True, 'lift': True, 'seed': '4'}),
        ('svm', 'Support Vector Machines, variety, linear, no support vectors ringed', {'y': ['variety'], 'x': [W, S], **val}, {'kernel': 'linear', 'tune': True, 'points': 5, 'svmSV': False, 'roc': True, 'seed': '4'}),
        ('svm', 'Support Vector Machines, shelf life', {'y': ['shelf life (days)'], 'x': [W, F, S, 'skin']}, {'svmPair': None, 'portion': 0.3, 'seed': '6'}),
    ]
    total = 0
    for pid, label, roles, opts in specs:
        r = await page.ev(open_report_js(pid, roles, opts), timeout=900)
        check(f'charts: {label}: no errors', r['errors'], [])
        n, _ = await UP.chart_blocks(page, check, label, tbl, last, learners_compare)
        total += n
        await page.ev(f'SM.app.closeReport({last})')
    check('charts: the blocks ran and drew the page\'s graphs', total >= 25, True)


# ---- the shared Decision Threshold, ROC Table, gains, deciles, profit and Group Metrics (smui-predict.js) ----------
PYDIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'py'))
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)


async def run_json(page, code, expr, table_js="SM.app.tables.find((t) => t.name === 'Orchard')"):
    """A code block run in the page's own Python (the notebook's runner), and the value of expr after it, as JSON."""
    full = f'{code}\nimport json as _json\nprint("SMUI-JSON " + _json.dumps({expr}, default=lambda o: o.tolist() if hasattr(o, "tolist") else float(o)))\n'
    out = await page.ev(f'__gr.run({json.dumps(full)}, {table_js})', timeout=600)
    if isinstance(out, str):
        return None, out
    text = ''.join(o.get('text', '') for o in out.get('outputs') or [] if o.get('type') == 'stream' and o.get('name') == 'stdout')
    for line in text.split('\n'):
        if line.startswith('SMUI-JSON '):
            return json.loads(line[len('SMUI-JSON '):]), None
    errs = [f"{o.get('ename')}: {o.get('evalue')}" for o in out.get('outputs') or [] if o.get('type') == 'error']
    return None, (errs[0] if errs else text[-400:])


# The last report's fit (the engine's result, from the report's cache) and the page's own numbers at a threshold:
# SM.predict.thresholdState over the rows' probabilities, as the Decision Threshold computes them.
FIT = '''
(async (fn) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const e = [...rep.cache.entries()].filter(([k]) => k.startsWith(fn + '\\u0001')).pop();
  return e ? await e[1] : null;
})
'''

STATE_AT = '''
(async (fn, lv, cut, rate) => {
  const r = await (%s)(fn);
  const D = r.fit ? r.fit.threshold : r;
  const S = SM.predict.thresholdState(D, lv, rate);
  return D.sets.map((set) => ({ set, ...S.at(D.models[0], set, cut) }));
})
''' % FIT

# The text of the report tables under an outline (the first with that title), each as rows of cells, header first.
TABLES = '''
((title) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h2, h3, h4').textContent.trim() === title);
  if (!head) return null;
  const body = head.parentElement.querySelector(':scope > .sm-ob-body');
  return [...body.querySelectorAll(':scope > table.sm-rt, :scope > * table.sm-rt')].filter(t => t.closest('.sm-ob') === head.parentElement).map(t => ({ caption: t.querySelector('caption') ? t.querySelector('caption').textContent : '', rows: [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent.trim())) }));
})
'''

CODES = '''
((title) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h2, h3, h4').textContent.trim() === title);
  if (!head) return [];
  // the outline's own code blocks first (its tables'), then those beside its graphs (not a sub-outline's)
  const body = head.parentElement.querySelector(':scope > .sm-ob-body');
  const own = [...body.querySelectorAll(':scope > details.sm-code code')];
  const nested = [...body.querySelectorAll('details.sm-code code')].filter(c => c.closest('.sm-ob') === head.parentElement && !own.includes(c));
  return [...own, ...nested].map(c => c.textContent);
})
'''


def as_rows(tbl):
    """A report table's text rows as dicts by the header's labels."""
    head = tbl['rows'][0]
    return [dict(zip(head, r)) for r in tbl['rows'][1:]]


def near4(text, v, tol=5.01e-5):
    """A table cell shown to 4 decimals (or to 7 figures) against the value."""
    if v is None:
        return text == '.'
    try:
        return abs(num(text) - v) <= max(tol, 1e-6 * abs(v))
    except ValueError:
        return False


METRIC_COLS = [('accuracy', 'Accuracy'), ('misclassification', 'Misclassification Rate'), ('sensitivity', 'Sensitivity'), ('specificity', 'Specificity'), ('fpr', 'False Positive Rate'),
               ('fnr', 'False Negative Rate'), ('precision', 'Precision'), ('f1', 'F1 Score'), ('mcc', 'MCC')]


async def decisions(page):
    """The shared parts of every classifier (smui-predict.js) on K Nearest Neighbors and Naive Bayes: the Decision
    Threshold (the page's counts and measures against its code's, run in the page's own Python, and against
    predictive.py here; the threshold typed, slid, dragged with the mouse, clicked on a curve, set to the best
    MCC; the target level; a true event rate; Save Threshold Formula), the ROC Table and the best point, the
    gains and decile table, the Naive Model and the optional measures, a Profit Matrix (the profit table, its
    code, Set Threshold to Most Profit, Save Profit Columns), Group Metrics (the engine's, its code, equal false
    positive rates by the menu, Save Decision Column), the mosaic's links, Score Rows into another table, Naive
    Bayes' Save Prediction Formula, KNN's Standardize and Distance Weights, a project, By groups (each group's own
    threshold and target level, its saved formulas within the group, a project and an older one), the stacked
    classification bars, the dark theme and phone width."""
    from smui import predictive as pv
    await page.ev(GRAPHS_JS)
    await page.ev(UP.PM_JS)
    tbl = "SM.app.tables.find((t) => t.name === 'Orchard')"
    await page.ev(f'SM.app.showTab(SM.app.tabOf({tbl}))')
    val = {'validation': ['Validation']}
    opts = {'k': 10, 'threshold': True, 'roc': True, 'rocTable': True, 'lift': True, 'gains': True, 'liftTable': True, 'naive': True, 'seed': '5'}
    r = await page.ev(open_report_js('knn', {'y': ['grade'], 'x': XS, **val}, opts), timeout=900)
    check('decisions: K Nearest Neighbors on grade with the Decision Threshold, the ROC Table, gains and deciles: no errors, the outlines',
          (r['errors'], all(t in r['outlines'] for t in ('Decision Threshold', 'Metrics by Threshold', 'ROC Table', 'Cumulative Gains', 'Decile Lift Table'))), ([], True))
    fit = (await page.ev(f'({FIT})("knn.fit")'))['fit']
    D = fit['threshold']
    check('decisions: the engine sends the Decision Threshold\'s data: two levels, the second the target, every row\'s probability', (D['levels'], D['target'], len(D['models'][0]['p']) == len(D['points']['rows'])), (['export', 'local'], 1, True))

    async def page_state(lv, cut, rate=None):
        return await page.ev(f'({STATE_AT})("knn.fit", {lv}, {cut}, {json.dumps(rate)})')

    # (1) the page's numbers at 0.5: the tables' text, predictive.py's cut tables here, and the code in the page
    st = await page_state(1, 0.5)
    y = np.asarray(D['points']['actual'])
    p1 = np.asarray(D['models'][0]['p'])
    sets = np.asarray(D['points']['set'])
    native = []
    for s_ in D['sets']:
        m = sets == pv.SETS.index(s_)
        native.append({'set': s_, **pv.rates_at(*pv.counts_at(pv.cut_table(p1[m], y[m] == 1), 0.5))})
    check('decisions: the page\'s counts and measures at 0.5 are predictive.py\'s (cut_table, counts_at, rates_at), every set, exactly', st == json.loads(json.dumps(native)), True)
    tabs = await page.ev(f'({TABLES})("Decision Threshold")')
    mt = next(t for t in tabs if t['caption'].startswith('local called when'))
    shown = as_rows(mt)
    okt = [all(near4(row[lab], s_[key]) for key, lab in METRIC_COLS) for row, s_ in zip(shown, st)]
    check('decisions: the metrics table shows them (Accuracy … MCC, each set)', ([row['Set'] for row in shown], okt), (D['sets'], [True] * len(D['sets'])))
    cm = next(t for t in tabs if t['caption'] == 'Validation: count at the threshold')
    vs = next(s_ for s_ in st if s_['set'] == 'Validation')
    check('decisions: the validation confusion matrix at the threshold (rows actual, columns called)', [[num(c) for c in row[1:]] for row in cm['rows'][1:]], [[vs['tn'], vs['fp']], [vs['fn'], vs['tp']]])
    bars = await page.ev('''(() => { const p = SM.app.reports.at(-1).plots.find(q => q.opts.title === 'Classification at the threshold Validation');
      return p ? p.traces.map(t => ({ name: t.name, x: t.x, y: t.y, n: t.customdata })) : null; })()''')
    t0_, t1_ = vs['tn'] + vs['fp'], vs['fn'] + vs['tp']
    want_b = [[vs['tn'] / t0_, vs['fn'] / t1_], [vs['fp'] / t0_, vs['tp'] / t1_]]
    check('decisions: Classification at the threshold (JMP\'s stacked bars) beside it: each actual level\'s bar cut into the shares called export and local, hovering the counts',
          (bars and [b_['name'] for b_ in bars], bars and [b_['y'] for b_ in bars], bool(bars) and all(abs(a_ - w_) < 1e-15 for b_, ww in zip(bars, want_b) for a_, w_ in zip(b_['x'], ww)), bars and [b_['n'] for b_ in bars]),
          (['called export', 'called local'], [['export', 'local']] * 2, True, [[vs['tn'], vs['fn']], [vs['fp'], vs['tp']]]))
    codes = await page.ev(f'({CODES})("Decision Threshold")')
    got, err = await run_json(page, codes[0], 'results')
    check('decisions: the tables\' code block runs in the page and gives the page\'s numbers', (err, got is not None and all(all(pv_close(a_.get(k), b_[k]) for k in ('tp', 'fp', 'fn', 'tn', 'accuracy', 'sensitivity', 'specificity', 'precision', 'f1', 'mcc', 'fpr', 'fnr')) for a_, b_ in zip(got, st))), (None, True))

    # (2) a threshold typed (real keys), the slider, a click on a curve, a drag of the dashed line with the mouse
    await page.ev('''(() => { const rep = SM.app.reports.at(-1); const i = rep.body.querySelector('input[aria-label="Probability threshold"]'); i.focus(); i.select(); })()''')
    for ch in '0.37':
        await page.key(ch, text=ch)
    await page.ev('(() => { window.__done = new Promise(res => SM.app.reports.at(-1).on("done", res)); return true; })()')
    await page.key('Enter', code='Enter')
    await page.ev('window.__done', timeout=120)
    opt = await page.ev('SM.app.reports.at(-1).spec.options.dtCut')
    tabs = await page.ev(f'({TABLES})("Decision Threshold")')
    check('decisions: a threshold typed and Enter: the option and the tables\' caption', (opt, any(t['caption'] == 'local called when Prob[local] ≥ 0.37' for t in tabs)), (0.37, True))
    r = await page.ev('''(async () => { const rep = SM.app.reports.at(-1); const s = rep.body.querySelector('input[aria-label="Probability threshold slider"]');
      const d = new Promise(res => rep.on('done', res)); s.value = '0.62'; s.dispatchEvent(new Event('input')); s.dispatchEvent(new Event('change')); await d; return rep.spec.options.dtCut; })()''')
    check('decisions: the slider moves it by 0.01', r, 0.62)
    xy = await page.ev('''(async () => { const rep = SM.app.reports.at(-1);
      await __gr.drawAll(rep);
      const p = rep.plots.find(q => q.opts.title === 'Fitted probabilities Validation'); p.box.scrollIntoView({ block: 'center' }); await new Promise(r => setTimeout(r, 400));
      const gd = p.box, L = gd._fullLayout, b = gd.getBoundingClientRect();
      const x0 = b.left + L._size.l + L.xaxis.l2p(0.62), x1 = b.left + L._size.l + L.xaxis.l2p(0.3), y = b.top + L._size.t + L._size.h / 2;
      return [x0, y, x1]; })()''')
    await page.ev('(() => { window.__done = new Promise(res => SM.app.reports.at(-1).on("done", res)); window.__moved = false; return true; })()')
    await page.mouse('mouseMoved', xy[0], xy[1])
    await page.mouse('mousePressed', xy[0], xy[1])
    for k in range(1, 11):
        await page.mouse('mouseMoved', xy[0] + (xy[2] - xy[0]) * k / 10, xy[1])
        await asyncio.sleep(0.03)
    await page.mouse('mouseReleased', xy[2], xy[1])
    await page.ev('Promise.race([window.__done, new Promise(r => setTimeout(r, 20000))])', timeout=60)
    opt = await page.ev('SM.app.reports.at(-1).spec.options.dtCut')
    check('decisions: the dashed line dragged with the mouse to 0.3 in the fitted-probability plot moves the threshold there', isinstance(opt, (int, float)) and abs(opt - 0.3) < 0.02, True)
    r = await page.ev('''(async () => { const rep = SM.app.reports.at(-1); await __gr.drawAll(rep);
      const p = rep.plots.find(q => /^Measures by threshold Validation/.test(q.opts.title)); const d = new Promise(res => rep.on('done', res));
      p.box.emit('plotly_click', { points: [{ x: 0.45, y: 0.5 }] }); await d; return rep.spec.options.dtCut; })()''')
    check('decisions: a click on a curve moves the threshold to it', r, 0.45)

    # (3) Set Threshold to ▸ Best MCC: the validation rows' distinct probability with the largest MCC, by brute force here
    await page.ev(pick_js('Decision Threshold', ['Set Threshold to', 'Best MCC']))
    opt = await page.ev('SM.app.reports.at(-1).spec.options.dtCut')
    mv = sets == 1
    cands = sorted(set(p1[mv].tolist()), reverse=True)
    best = max(cands, key=lambda t_: (pv.rates_at(*pv.counts_at(pv.cut_table(p1[mv], y[mv] == 1), t_))['mcc'] or -9, t_))
    mccs = [pv.rates_at(*pv.counts_at(pv.cut_table(p1[mv], y[mv] == 1), t_))['mcc'] or -9 for t_ in cands]
    check('decisions: Set Threshold to ▸ Best MCC: the validation probability with the largest MCC (of equal ones the highest)', opt, cands[int(np.argmax(mccs))])

    # (4) the target level, a true event rate: the page's numbers against the code's
    await page.ev(pick_js('Decision Threshold', ['Target Level', 'export']))
    await page.ev('(async () => { const rep = SM.app.reports.at(-1); const d = new Promise(res => rep.on("done", res)); rep.spec.options.dtCut = 0.4; rep.spec.options.dtTrueRate = 0.2; rep.run(); await d; })()')
    st0 = await page_state(0, 0.4, 0.2)
    codes = await page.ev(f'({CODES})("Decision Threshold")')
    got, err = await run_json(page, codes[0], 'results')
    tr_m = sets == 0
    rho = float(np.sum(y[tr_m] == 0) / tr_m.sum())
    a_, b_ = 0.2 / rho, 0.8 / (1 - rho)
    p0 = 1 - p1
    q0 = p0 * a_ / (p0 * a_ + (1 - p0) * b_)
    native0 = [{'set': s_, **pv.rates_at(*pv.counts_at(pv.cut_table(q0[sets == pv.SETS.index(s_)], y[sets == pv.SETS.index(s_)] == 0), 0.4))} for s_ in D['sets']]
    check('decisions: the target level export and a true event rate of 0.2: the probabilities rescaled, p a / (p a + (1 - p) b), before the threshold (the page, predictive.py here, and the code)',
          (err, all(all(pv_close(x_[k], z_[k], 1e-9) for k in ('tp', 'fp', 'accuracy', 'mcc')) for x_, z_ in zip(st0, native0)), got is not None and all(all(pv_close(g_[k], x_[k]) for k in ('tp', 'fp', 'accuracy', 'mcc')) for g_, x_ in zip(got, st0))), (None, True, True))
    # Save Threshold Formula: the probabilities saved first (the column was not there), then If(rescaled Prob >= cut, ...)
    cols_ = await page.ev(f'''(async () => {{ const rep = SM.app.reports.at(-1); const t = rep.table; const before = t.columns.length;
      await ({PICK})('Decision Threshold', ['Save Threshold Formula'], false, 0);
      for (let i = 0; i < 80 && t.columns.length < before + 3; i++) await new Promise(r => setTimeout(r, 100));
      return t.columns.slice(before).map(c => ({{ name: c.name, formula: c.formula ? c.formula.expr : null, values: c.values }})); }})()''', timeout=300)
    names = [c['name'] for c in cols_]
    check('decisions: Save Threshold Formula saves the probabilities first, then the formula column', (names[:2], len(names), names[-1].startswith('Called grade')), (['Prob[export]', 'Prob[local]'], 3, True))
    pe = np.array(cols_[0]['values'], dtype=float)
    want = ['export' if (v * a_) / (v * a_ + (1 - v) * b_) >= 0.4 else 'local' for v in pe]
    check('... a live If on Prob[export], rescaled to the true event rate, called at 0.4: every row', (cols_[-1]['formula'].startswith('If('), cols_[-1]['values'] == want), (True, True))
    await page.ev('(async () => { const rep = SM.app.reports.at(-1); const d = new Promise(res => rep.on("done", res)); rep.spec.options.dtTrueRate = null; rep.spec.options.dtLevel = 1; rep.spec.options.dtCut = 0.5; rep.run(); await d; })()')

    # (5) the ROC Table: a line per cut, the best starred, and the dot on the curve
    tabs = await page.ev(f'({TABLES})("ROC Table")')
    rt_v = next(t for t in tabs if t['caption'] == 'Validation: local')
    nat = pv.roc_table(pv.cut_table(p1[mv], y[mv] == 1))
    rows_ = as_rows(rt_v)
    ok_rt = len(rows_) == len(nat) and all(near4(r_['1-Specificity'], q['fpr']) and near4(r_['Sensitivity'], q['sens']) and num(r_['True Pos']) == q['tp'] and num(r_['False Neg']) == q['fn'] and (r_[''] == '*') == q['best'] for r_, q in zip(rows_, nat))
    check('decisions: the ROC Table of the validation rows: predictive.roc_table\'s lines, the largest Sens-(1-Spec) starred', (ok_rt, sum(1 for r_ in rows_ if r_[''] == '*')), (True, 1))
    b_roc = next(c for c in fit['roc'] if c['set'] == 'Validation' and c['level'] == 'local')['best']
    star = next(q for q in nat if q['best'])
    check('... the dot on the ROC curve at that line', (abs(b_roc['fpr'] - star['fpr']) < 1e-12, abs(b_roc['tpr'] - star['sens']) < 1e-12), (True, True))
    codes = await page.ev(f'({CODES})("ROC Table")')
    got, err = await run_json(page, codes[0], '{k: v.to_dict("records") for k, v in roc_tables.items()}')
    check('... its code block gives the same lines', (err, got is not None and len(got['Validation']) == len(nat) and all(abs(g_['sens'] - q['sens']) < 1e-12 and g_['best'] == q['best'] for g_, q in zip(got['Validation'], nat))), (None, True))

    # (6) the decile table, the Naive Model and the optional measures
    tabs = await page.ev(f'({TABLES})("Decile Lift Table")')
    dv = as_rows(next(t for t in tabs if t['caption'] == 'Validation: local'))
    want_d = next(c for c in fit['lift'] if c['set'] == 'Validation' and c['level'] == 'local')['deciles']
    check('decisions: the decile lift table: ten parts, each part\'s N, N local, rate, lift, cumulative lift and gains as the engine\'s',
          (len(dv), all(num(a_['N']) == b_['n'] and near4(a_['Lift'], b_['lift']) and near4(a_['Cumulative Gains'], b_['gains']) for a_, b_ in zip(dv, want_d))), (10, True))
    codes = await page.ev(f'({CODES})("Decile Lift Table")')
    got, err = await run_json(page, codes[0], '{k: v.to_dict("records") for k, v in deciles.items()}')
    check('... its code block gives the same table', (err, got is not None and all(abs(g_['lift'] - b_['lift']) < 1e-12 and abs(g_['gains'] - b_['gains']) < 1e-12 for g_, b_ in zip(got['Validation'], want_d))), (None, True))
    tabs = await page.ev(f'({TABLES})("Measures of Fit")')
    mrows = as_rows(tabs[0])
    naive = {q['set']: q for q in fit['naive']}
    check('decisions: Naive Model (red triangle) adds a line per set, the training shares\' measures (Entropy RSquare 0 on the training rows)',
          ([r_['Set'] for r_ in mrows][-3:], near4(next(r_ for r_ in mrows if r_['Set'] == 'Training (Naive)')['Entropy RSquare'], 0.0), near4(next(r_ for r_ in mrows if r_['Set'] == 'Validation (Naive)')['Misclassification Rate'], naive['Validation']['misclassification'])),
          (['Training (Naive)', 'Validation (Naive)', 'Test (Naive)'], True, True))

    # (7) a Profit Matrix (the column property): the profit table, its code, Most Profit, Save Profit Columns
    PM = [[1.0, -2.0, -0.2], [-4.0, 3.0, 0.0]]
    await page.ev(f'''(async () => {{ const rep = SM.app.reports.at(-1); const t = rep.table; const c = t.col('grade');
      t.setProfitMatrix(c.id, {{ levels: ['export', 'local'], decisions: ['export', 'local', 'Undecided'], matrix: {json.dumps(PM)} }});
      const d = new Promise(res => rep.on('done', res)); rep.run(); await d; }})()''', timeout=300)
    tabs = await page.ev(f'({TABLES})("Profit")')
    prow = as_rows(tabs[1])
    M_ = np.array(PM)

    def prof_native(s_, t_):
        m = sets == pv.SETS.index(s_)
        tp, fp, fn, tn = pv.counts_at(pv.cut_table(p1[m], y[m] == 1), t_)
        return (tp * M_[1, 1] + fn * M_[1, 0] + fp * M_[0, 1] + tn * M_[0, 0]) / (tp + fp + fn + tn)

    def bayes_native(s_):
        m = sets == pv.SETS.index(s_)
        pr = np.column_stack([1 - p1[m], p1[m]])
        dec = np.argmax(pr @ M_, 1)
        return float(np.mean(M_[y[m], dec]))
    okp = [near4(r_['Average Profit'], prof_native(r_['Set'], 0.5), 5.01e-7) and near4(r_['Most Profitable Decisions'], bayes_native(r_['Set']), 5.01e-7) for r_ in prow]
    d1, d0 = M_[1, 1] - M_[1, 0], M_[0, 0] - M_[0, 1]
    check('decisions: the Profit table: each set\'s average profit at the threshold and of the most profitable decisions (Undecided among them), by hand here',
          ([r_['Set'] for r_ in prow], okp, near4(prow[0]['Threshold from the Matrix'], d0 / (d1 + d0), 5.01e-7)), (D['sets'], [True] * len(prow), True))
    codes = await page.ev(f'({CODES})("Profit")')
    got, err = await run_json(page, codes[0], 'results')
    check('... its code block gives the same profits', (err, got is not None and all(abs(g_['average profit'] - prof_native(g_['set'], 0.5)) < 1e-12 and abs(g_['most profitable decisions'] - bayes_native(g_['set'])) < 1e-12 for g_ in got)), (None, True))
    await page.ev(pick_js('Decision Threshold', ['Set Threshold to', 'Most Profit']))
    opt = await page.ev('SM.app.reports.at(-1).spec.options.dtCut')
    cands = sorted(set(p1[mv].tolist()), reverse=True)
    profs = [prof_native('Validation', t_) for t_ in cands]
    check('decisions: Set Threshold to ▸ Most Profit: the validation probability with the largest average profit', opt, cands[int(np.argmax(profs))])
    await page.ev('(async () => { const rep = SM.app.reports.at(-1); const d = new Promise(res => rep.on("done", res)); rep.spec.options.dtCut = 0.5; rep.run(); await d; })()')
    cols_ = await page.ev(f'''(async () => {{ const rep = SM.app.reports.at(-1); const t = rep.table; const before = t.columns.length;
      await ({PICK})('Decision Threshold', ['Save Profit Columns'], false, 0);
      for (let i = 0; i < 80 && t.columns.length < before + 5; i++) await new Promise(r => setTimeout(r, 100));
      const pe = t.columns.find(c => c.name === 'Prob[export]'), pl = t.columns.find(c => c.name === 'Prob[local]');
      return {{ cols: t.columns.slice(before).map(c => ({{ name: c.name, values: c.values, formula: !!c.formula }})), pe: pe.values, pl: pl.values }}; }})()''', timeout=300)
    pnames = [c['name'] for c in cols_['cols']]
    check('decisions: Save Profit Columns: a formula per decision, Expected Profit and Most Profitable', (pnames, all(c['formula'] for c in cols_['cols'])),
          (['Profit[export]', 'Profit[local]', 'Profit[Undecided]', 'Expected Profit', 'Most Profitable grade'], True))
    PR = np.column_stack([cols_['pe'], cols_['pl']]).astype(float)
    EP = PR @ M_
    got_pf = np.column_stack([cols_['cols'][j]['values'] for j in range(3)]).astype(float)
    check.near('... Profit[d] = Σ Prob[level] × profit(level, d), every row', UP.maxdiff(got_pf.ravel().tolist(), EP.ravel().tolist()), 0, 1e-12)
    check('... Expected Profit the largest, Most Profitable its decision', (UP.maxdiff(cols_['cols'][3]['values'], EP.max(1).tolist()) < 1e-12, cols_['cols'][4]['values'] == [['export', 'local', 'Undecided'][int(j)] for j in EP.argmax(1)]), (True, True))
    graphs_ok = await page.ev('(() => { const rep = SM.app.reports.at(-1); return ["Profit Curve", "Profit"].map(t => [...rep.body.querySelectorAll(".sm-ob-head")].some(h => h.textContent.trim() === t)); })()')
    check('decisions: the Profit Curve beside the lift curves, the Profit outline in the Decision Threshold', graphs_ok, [True, True])
    n_ok, _ = await UP.chart_blocks(page, check, 'decisions: knn grade with a profit matrix', tbl, 'SM.app.reports.at(-1)', learners_compare)
    check('decisions: every graph of the report (fitted probabilities, measures, profit, gains, ROC with the best point, lift) drew its figure from its code', n_ok >= 16, True)

    # (8) Group Metrics by skin (not a factor... it is one here; orchard is not): the engine's numbers, equal FPR by the menu, Save Decision Column
    oid = await page.ev(f'{tbl}.col("orchard").id')
    await page.ev(f'(async () => {{ const rep = SM.app.reports.at(-1); const d = new Promise(res => rep.on("done", res)); rep.spec.options.groupMetrics = {json.dumps(oid)}; rep.run(); await d; }})()', timeout=300)
    await asyncio.sleep(1.0)
    tabs = await page.ev(f'({TABLES})("Group Metrics: orchard")')
    grows = as_rows(tabs[0])
    eng = await page.ev(f'''(async () => {{ const rep = SM.app.reports.at(-1); const r = await ({FIT})('knn.fit'); const D = r.fit.threshold;
      return await SM.engine.call('predict.groups', {{ group: 'orchard', at: D.points.rows, actual: D.points.actual, prob: D.models[0].p, sets: D.points.set, w: D.points.w, cut: 0.5, target: 1 }}, rep.table); }})()''')
    okg = [all(near4(r_[lab], e_[k]) for k, lab in (('base_rate', 'Base Rate'), ('selection_rate', 'Selection Rate'), ('accuracy', 'Accuracy'), ('auc', 'AUC'), ('fpr', 'False Positive Rate'), ('fnr', 'False Negative Rate'), ('precision', 'Precision'))) for r_, e_ in zip(grows, eng['rows'])]
    check('decisions: Group Metrics by orchard (not a factor of the model): each group\'s measures, the engine\'s', ([r_['orchard'] for r_ in grows], okg), (['North', 'South'], [True, True]))
    codes = await page.ev(f'({CODES})("Group Metrics: orchard")')
    got, err = await run_json(page, codes[0], 'rows')
    check('... its code block (with the bar chart) gives the same rows', (err, got is not None and all(abs(g_['fpr'] - e_['fpr']) < 1e-12 and abs(g_['auc'] - e_['auc']) < 1e-12 for g_, e_ in zip(got, eng['rows']))), (None, True))
    await page.ev(pick_js('Group Metrics: orchard', ['Thresholds', 'Equal False Positive Rates']))
    tabs = await page.ev(f'({TABLES})("Group Metrics: orchard")')
    grows2 = as_rows(tabs[0])
    eng2 = await page.ev(f'''(async () => {{ const rep = SM.app.reports.at(-1); const r = await ({FIT})('knn.fit'); const D = r.fit.threshold;
      return await SM.engine.call('predict.groups', {{ group: 'orchard', at: D.points.rows, actual: D.points.actual, prob: D.models[0].p, sets: D.points.set, w: D.points.w, cut: 0.5, target: 1, equal: 'fpr' }}, rep.table); }})()''')
    check('decisions: Thresholds ▸ Equal False Positive Rates (the menu): each group\'s threshold solved, the engine\'s', [num(r_['Threshold']) for r_ in grows2], [round(e_['cut'], 4) if e_['cut'] is not None else None for e_ in eng2['rows']])
    cols_ = await page.ev(f'''(async () => {{ const rep = SM.app.reports.at(-1); const t = rep.table; const before = t.columns.length;
      await ({PICK})('Group Metrics: orchard', ['Save Decision Column'], false, 0);
      for (let i = 0; i < 60 && t.columns.length === before; i++) await new Promise(r => setTimeout(r, 100));
      const c = t.columns[t.columns.length - 1]; return {{ name: c.name, values: c.values, formula: c.formula ? c.formula.expr : null, pl: t.col('Prob[local]').values, orch: t.col('orchard').values }}; }})()''', timeout=300)
    th = {e_['group']: e_['cut'] for e_ in eng2['rows']}
    want = ['local' if pl_ >= th.get(o_, 0.5) else 'export' for pl_, o_ in zip(cols_['pl'], cols_['orch'])]
    check('decisions: Save Decision Column: a live formula, each row called by its group\'s threshold', (cols_['name'], cols_['formula'] is not None and 'Match(' in cols_['formula'], cols_['values'] == want), ('Decision grade by orchard', True, True))

    # (9) a project keeps the options, and the report comes back the same
    r = await page.ev('''(async () => { const rep = SM.app.reports.at(-1); const t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j); const back = SM.app.reports.at(-1);
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const o = back.spec.options; const out = { cut: o.dtCut, level: o.dtLevel, mode: o.gmMode, group: !!o.groupMetrics, pm: !!back.table.col('grade').profitMatrix,
        heads: [...back.body.querySelectorAll('.sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent).filter(x => /Decision Threshold|Group Metrics|Profit/.test(x)) };
      SM.app.closeTable(back.table); await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop(); const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close'); if (yes) yes.click();
      return out; })()''', timeout=600)
    check('decisions: a project keeps the threshold, the target, Group Metrics\' mode, and the table its Profit Matrix', (r['cut'], r['level'], r['mode'], r['group'], r['pm'], 'Decision Threshold' in r['heads'], 'Group Metrics: orchard' in r['heads'], 'Profit' in r['heads']),
          (0.5, 1, 'fpr', True, True, True, True, True))
    await page.ev(f'(() => {{ const t = {tbl}; t.setProfitMatrix(t.col("grade").id, null); }})()')

    # (10) the mosaic of K Nearest Neighbors' variety: its parts select their rows
    r = await page.ev(open_report_js('knn', {'y': ['variety'], 'x': XS, **val}, {'k': 6, 'mosaic': True, 'distance': True, 'seed': '3'}), timeout=900)
    check('decisions: K Nearest Neighbors with Distance Weights and the Mosaic Plot: no errors', (r['errors'], 'Mosaic Plot' in r['outlines']), ([], True))
    sel = await page.ev('''(async () => { const rep = SM.app.reports.at(-1); await __gr.drawAll(rep);
      const p = rep.plots.find(q => q.opts.title === 'Mosaic Validation'); const tr = p.traces[1]; const rows = p.rows[1][0];
      p.box.emit('plotly_click', { points: [{ curveNumber: 1, pointNumber: 0 }], event: {} }); await new Promise(r => setTimeout(r, 200));
      return { want: rows.slice().sort((a, b) => a - b), got: rep.table.rowsWith('selected') }; })()''')
    check('decisions: a click on a part of the mosaic selects its rows (actual Early called Mid, the validation rows)', (len(sel['want']) >= 0, sel['got'] == sel['want']), (True, True))
    r = await page.ev(f'({FIT})("knn.fit")')
    check('decisions: Distance Weights and Standardize reach the engine', (r['weights'], r['standardize']), ('distance', True))
    await page.ev(pick_js('*top*', ['Standardize']))
    r = await page.ev(f'({FIT})("knn.fit")')
    check('decisions: Standardize off from the red triangle', (r['standardize'], r['scaled'], await page.ev('SM.app.reports.at(-1).spec.options.standardize')), (False, [], False))

    # (11) Score Rows: another open table with the same columns, by the report's model
    await page.ev(f'''(() => {{ const t = {tbl}; const rows = [0, 1, 2, 3, 4, 5, 6, 7];
      const cols = ['{W}', '{S}', '{F}', 'skin'].map(nm => {{ const c = t.col(nm); return {{ name: nm, dataType: c.dataType, values: rows.map(i => c.isNumeric ? c.values[i] + 1 : c.values[i]) }}; }});
      SM.app.addTable(new SM.Table({{ name: 'New apples', source: 'test', columns: cols }})); SM.app.showTab(SM.app.tabOf({tbl})); SM.app.showTab(SM.app.tabOf(SM.app.reports.at(-1))); }})()''')
    r = await page.ev(f'''(async () => {{ const rep = SM.app.reports.at(-1); const other = SM.app.tables.find(t => t.name === 'New apples');
      const menu = ({PICK})('*top*', ['Save Columns', 'Score Rows…'], false, 0);
      for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
      const d = [...document.querySelectorAll('.sm-dialog')].pop(); const sels = d.querySelectorAll('.sm-form select');
      sels[0].value = other.id; sels[1].value = 'all'; d.querySelector('.sm-dialog-foot .primary').click();
      for (let i = 0; i < 100 && !other.columns.some(c => c.name === 'Prob[Mid]'); i++) await new Promise(r => setTimeout(r, 100));
      const eng = await SM.engine.call('knn.score', {{ keep: `${{rep.id}}|`, target_rows: null }}, other);
      return {{ names: other.columns.map(c => c.name), mid: other.col('Prob[Mid]') ? other.col('Prob[Mid]').values : null, most: other.col('Most Likely variety') ? other.col('Most Likely variety').values : null, eng }}; }})()''', timeout=300)
    check('decisions: Score Rows into another open table: its Prob[] and Most Likely columns, the report\'s model\'s (the engine kept it)',
          (r['names'][-4:], r['mid'] == [q[1] for q in r['eng']['prob']], r['most'] == r['eng']['most_likely']), (['Prob[Early]', 'Prob[Mid]', 'Prob[Late]', 'Most Likely variety'], True, True))
    # ... and Support Vector Machines' Score Rows, the same dialog (SM.predict.scoreRows): every row of New apples, then a row
    # added to it, which alone gets predictions, into the columns the first scoring made
    await page.ev(open_report_js('svm', {'y': ['grade'], 'x': XS, **val}, {'seed': '3'}), timeout=900)
    r = await page.ev(f'''(async () => {{ const rep = SM.app.reports.at(-1); const other = SM.app.tables.find(t => t.name === 'New apples');
      const score = async (which) => {{ await ({PICK})('*top*', ['Save Columns', 'Score Rows…'], false, 0);
        for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
        const d = [...document.querySelectorAll('.sm-dialog')].pop(); const sels = d.querySelectorAll('.sm-form select');
        sels[0].value = other.id; sels[1].value = which; d.querySelector('.sm-dialog-foot .primary').click(); }};
      await score('all');
      for (let i = 0; i < 100 && !other.columns.some(c => c.name === 'Most Likely grade'); i++) await new Promise(r => setTimeout(r, 100));
      const n0 = other.columns.length, before = other.col('Prob[local]').values.slice();
      other.addRows(1); const k = other.nrows - 1;
      for (const nm of ['{W}', '{S}', '{F}', 'skin']) other.setCell(k, nm, other.col(nm).values[2]);
      await score('new');
      for (let i = 0; i < 100 && !Number.isFinite(other.col('Prob[local]').values[k]); i++) await new Promise(r => setTimeout(r, 100));
      const eng = await SM.engine.call('svm.score', {{ keep: `${{rep.id}}|`, target_rows: [k] }}, other);
      const after = other.col('Prob[local]').values;
      return {{ names: other.columns.slice(-3).map(c => c.name), same: before.every((v, i) => v === after[i]), cols: other.columns.length === n0, added: after[k], eng: eng.prob[0][1],
        most: other.col('Most Likely grade').values[k], engMost: eng.most_likely[0], note: eng.note || null }}; }})()''', timeout=300)
    check('decisions: Support Vector Machines\' Score Rows (the same dialog): every row of New apples, then a row added to it scored alone, into the columns the first scoring made',
          (r['names'], r['same'], r['cols'], r['added'] == r['eng'], r['most'] == r['engMost'], r['note']), (['Prob[export]', 'Prob[local]', 'Most Likely grade'], True, True, True, True, None))
    await page.ev('SM.app.closeReport(SM.app.reports.at(-1))')

    # (12) Naive Bayes: Save Prediction Formula, live, as Save Predicteds gives them (a missing factor left out)
    await page.ev(f'(() => {{ const t = {tbl}; t.setCell(3, "{S}", NaN); t.setCell(9, "skin", null); SM.app.showTab(SM.app.tabOf(t)); }})()')
    r = await page.ev(open_report_js('naivebayes', {'y': ['grade'], 'x': XS, **val}, {'seed': '2'}), timeout=900)
    r = await page.ev(f'''(async () => {{ const rep = SM.app.reports.at(-1); const t = rep.table; const before = t.columns.length;
      await ({PICK})('*top*', ['Save Columns', 'Save Prediction Formula'], false, 0);
      for (let i = 0; i < 80 && t.columns.length < before + 5; i++) await new Promise(r => setTimeout(r, 100));
      const made = t.columns.slice(before).map(c => ({{ name: c.name, formula: !!c.formula, values: c.values }}));
      const sv = await SM.engine.call('naivebayes.save', {{ y: 'grade', x: ['{W}', '{S}', '{F}', 'skin'], validation: 'Validation', seed: 2, missing: 'informative' }}, t);
      return {{ made, sv }}; }})()''', timeout=300)
    made = r['made']
    # the table has Prob[export] and the like from the parts above: the new ones get a number, as JMP names them
    import re as _re
    want_names = ['Log Score[export]', 'Log Score[local]', 'Prob[export]', 'Prob[local]', 'Most Likely grade']
    check('decisions: Naive Bayes\' Save Prediction Formula: Log Score and Prob per level, Most Likely, all formulas (a name the table has numbered)',
          ([bool(_re.fullmatch(_re.escape(w_) + r'( \d+)?', c['name'])) for w_, c in zip(want_names, made)], len(made), all(c['formula'] for c in made), any(c['name'] != w_ for w_, c in zip(want_names, made))),
          ([True] * 5, 5, True, True))
    sv = r['sv']
    pe_f = np.array(made[2]['values'], dtype=float)[sv['rows']]
    check.near('... the formulas\' probabilities are Save Predicteds\' (a row missing sugar and one missing skin among them)', UP.maxdiff(pe_f.tolist(), [q[0] for q in sv['prob']]), 0, 1e-12)
    check('... and the most likely levels', np.array(made[4]['values'], dtype=object)[sv['rows']].tolist(), sv['most_likely'])
    r = await page.ev(f'''(async () => {{ const t = {tbl}; const pc = t.col({json.dumps(made[2]['name'])}); const was = pc.values[0]; const most = t.col({json.dumps(made[4]['name'])});
      t.setCell(0, "{W}", 250); await new Promise(r => setTimeout(r, 300));
      const now = pc.values[0], other = t.col({json.dumps(made[3]['name'])}).values[0];
      return {{ was, now, sum: now + other, most: most.values[0], want: now >= other ? 'export' : 'local' }}; }})()''')
    check('... live: a cell edited, the formula columns follow (Prob[export] changes, the two still sum to 1, Most Likely reads the new ones)',
          (r['was'] != r['now'], abs(r['sum'] - 1) < 1e-12, r['most'] == r['want']), (True, True, True))

    # (12b) By groups: each group's report has its own Decision Threshold (JMP's): a threshold typed in one group leaves
    # the other alone; each group's confusion matrices at its own threshold; the target level the group's too; Save
    # Threshold Formula of a group reads the group's own probabilities (saved once) and gives the other group's rows no
    # value; a project keeps each group's; an older project with one threshold for the report gives it to every group
    r = await page.ev(open_report_js('knn', {'y': ['grade'], 'x': XS, 'by': ['orchard'], **val}, {'threshold': True, 'seed': '5'}), timeout=900)
    BY = """(async (cuts, lvs) => { const rep = SM.app.reports.at(-1); const orch = rep.table.col('orchard').values;
      await new Promise(res => { if (!rep.body.classList.contains('is-running')) res(); else rep.on('done', res); });
      const fits = await Promise.all([...rep.cache.entries()].filter(([k]) => k.startsWith('knn.fit\\u0001')).map(([, v]) => v));
      const title = (ob) => { const h = ob.querySelector(':scope > .sm-ob-head h2, :scope > .sm-ob-head h3, :scope > .sm-ob-head h4'); return h ? h.textContent.trim() : ''; };
      const groupOf = (h) => { let ob = h.parentElement; while (ob && !/^K Nearest Neighbors for/.test(title(ob))) ob = ob.parentElement ? ob.parentElement.closest('.sm-ob') : null; return ob ? title(ob).split('orchard=')[1] : null; };
      const heads = [...rep.body.querySelectorAll('.sm-ob-head')].filter(h => h.querySelector('h2, h3, h4').textContent.trim() === 'Decision Threshold');
      const tablesOf = (h) => [...h.parentElement.querySelectorAll('table.sm-rt')].filter(t => t.closest('.sm-ob') === h.parentElement)
        .map(t => ({ caption: t.querySelector('caption') ? t.querySelector('caption').textContent : '', rows: [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent.trim())) }));
      const shown = heads.map(h => ({ group: groupOf(h), tables: tablesOf(h) }));
      const states = {};
      for (const r of fits) { const D = r.fit.threshold; const g = orch[D.points.rows[0]]; if (!(g in cuts)) continue; const S = SM.predict.thresholdState(D, lvs[g], null);
        states[g] = { one: D.points.rows.every(i => orch[i] === g), level: D.levels[lvs[g]], at: D.sets.map(set => ({ set, ...S.at(D.models[0], set, cuts[g]) })), p: D.models[0].p, rows: D.points.rows }; }
      const opts = Object.fromEntries(Object.entries(rep.spec.options).filter(([k]) => /(^|\\|)(dtCut|dtLevel)$/.test(k)));
      return { shown, states, opts, errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent) }; })"""

    def by_ok(res, cuts):
        """Each group's tables at its own threshold: the caption, the measures of every set and the count matrices, its own fit's."""
        out = {}
        for sh in res['shown']:
            q = res['states'].get(sh['group'])
            if not q:
                out[sh['group']] = False
                continue
            lvn = q['level']
            mt = next((t_ for t_ in sh['tables'] if t_['caption'].startswith(f'{lvn} called when')), None)
            cap = bool(mt) and mt['caption'] == f'{lvn} called when Prob[{lvn}] ≥ {cuts[sh["group"]]:g}'
            meas = bool(mt) and len(as_rows(mt)) == len(q['at']) and all(all(near4(row[lab], a_[key]) for key, lab in METRIC_COLS) for row, a_ in zip(as_rows(mt), q['at']))
            cms = []
            for a_ in q['at']:
                cm = next((t_ for t_ in sh['tables'] if t_['caption'] == f"{a_['set']}: count at the threshold"), None)
                want_cm = [[a_['tn'], a_['fp']], [a_['fn'], a_['tp']]] if lvn == 'local' else [[a_['tp'], a_['fn']], [a_['fp'], a_['tn']]]
                cms.append(bool(cm) and [[num(c) for c in row[1:]] for row in cm['rows'][1:]] == want_cm)
            out[sh['group']] = bool(q['one'] and cap and meas and all(cms) and len(cms) == 3)
        return out

    async def type_cut(which, text):
        await page.ev(f"""(() => {{ const i = SM.app.reports.at(-1).body.querySelectorAll('input[aria-label="Probability threshold"]')[{which}]; i.focus(); i.select(); }})()""")
        for ch in text:
            await page.key(ch, text=ch)
        await page.ev('(() => { window.__done = new Promise(res => SM.app.reports.at(-1).on("done", res)); return true; })()')
        await page.key('Enter', code='Enter')
        await page.ev('window.__done', timeout=120)
        await asyncio.sleep(0.3)

    both = {'North': 1, 'South': 1}
    res = await page.ev(f'({BY})({json.dumps({"North": 0.5, "South": 0.5})}, {json.dumps(both)})', timeout=300)
    check('decisions: By orchard: a Decision Threshold under each group, each with its own group\'s rows, measures and count matrices at 0.5',
          (res['errors'], [sh['group'] for sh in res['shown']], by_ok(res, {'North': 0.5, 'South': 0.5})), ([], ['North', 'South'], {'North': True, 'South': True}))
    await type_cut(0, '0.4')
    cuts = {'North': 0.4, 'South': 0.5}
    res = await page.ev(f'({BY})({json.dumps(cuts)}, {json.dumps(both)})', timeout=300)
    check('... 0.4 typed in North\'s: North\'s tables at 0.4, South\'s still at 0.5 (each its own group\'s numbers); the option is North\'s alone',
          (by_ok(res, cuts), res['opts']), ({'North': True, 'South': True}, {'~orchard=North|dtCut': 0.4}))
    await type_cut(1, '0.6')
    cuts = {'North': 0.4, 'South': 0.6}
    res = await page.ev(f'({BY})({json.dumps(cuts)}, {json.dumps(both)})', timeout=300)
    check('... 0.6 typed in South\'s: South at 0.6, North still at 0.4, the confusion matrices of every set each at its group\'s threshold',
          (by_ok(res, cuts), res['opts']), ({'North': True, 'South': True}, {'~orchard=North|dtCut': 0.4, '~orchard=South|dtCut': 0.6}))
    fit_p = {g_: (q['rows'], q['p']) for g_, q in res['states'].items()}

    SAVE_TF = f"""(async (which) => {{ const rep = SM.app.reports.at(-1); const t = rep.table; const before = t.columns.length;
      await ({PICK})('Decision Threshold', ['Save Threshold Formula'], false, which);
      for (let i = 0; i < 100 && !t.columns.slice(before).some(c => c.formula); i++) await new Promise(r => setTimeout(r, 100));
      return {{ made: t.columns.slice(before).map(c => ({{ name: c.name, formula: c.formula ? c.formula.expr : null, values: c.values }})), orch: t.col('orchard').values }}; }})"""

    async def save_tf(which):
        await page.mouse('mouseMoved', 2, 2)   # the pointer out of the way of the menus
        out = await page.ev(f'({SAVE_TF})({which})', timeout=300)
        if not isinstance(out, dict):
            check(f'decisions: Save Threshold Formula in the By report\'s group {which + 1}', out, None)
            return {'made': [], 'orch': []}
        return out

    def called_ok(made, prob_vals, orch, group, cut):
        """The formula's value in every row: the group's rows called local at the cut on the group's Prob[local], the others missing."""
        want = [(None if pl is None else ('local' if pl >= cut else 'export')) if o_ == group else None for pl, o_ in zip(prob_vals, orch)]
        return made['values'] == want

    sv_s = await save_tf(1)
    ms = sv_s['made']
    prob_s = ms[1]['values'] if len(ms) == 3 else []
    rows_s, p_s = fit_p['South']
    check('decisions: By orchard, Save Threshold Formula in South\'s: South\'s Prob[] columns saved first (numbered: the table has those names), then the formula column named for South',
          ([bool(re.fullmatch(r'Prob\[(export|local)\]( \d+)?', c['name'])) for c in ms[:2]], len(ms), ms[-1]['name'] if ms else None),
          ([True, True], 3, f"Called grade orchard=South ({ms[1]['name'] if len(ms) == 3 else '?'} ≥ 0.6)"))
    check.near('... the Prob[local] saved is South\'s own model\'s (its fit\'s probabilities at its rows)', max(abs(prob_s[r_] - p_) for r_, p_ in zip(rows_s, p_s)) if prob_s else 1.0, 0, 1e-12)
    check('... the formula: If(:orchard == "South", If(Prob[local] ≥ 0.6, …), .): South\'s rows called at 0.6, North\'s missing, every row',
          (ms[-1]['formula'] is not None and ms[-1]['formula'].startswith('If(') and '"South"' in ms[-1]['formula'], called_ok(ms[-1], prob_s, sv_s['orch'], 'South', 0.6)), (True, True))
    sv_n = await save_tf(0)
    mn = sv_n['made']
    prob_n = mn[1]['values'] if len(mn) == 3 else []
    rows_n, p_n = fit_p['North']
    check('... Save Threshold Formula in North\'s: North\'s own Prob[] columns (another model than South\'s), its formula at 0.4, South\'s rows missing',
          (len(mn), mn[-1]['name'] if mn else None, bool(prob_n) and max(abs(prob_n[r_] - p_) for r_, p_ in zip(rows_n, p_n)) < 1e-12, bool(prob_n) and prob_n != prob_s, called_ok(mn[-1], prob_n, sv_n['orch'], 'North', 0.4)),
          (3, f"Called grade orchard=North ({mn[1]['name'] if len(mn) == 3 else '?'} ≥ 0.4)", True, True, True))
    sv_s2 = await save_tf(1)
    ps_name = ms[1]['name'] if len(ms) == 3 else '?'
    m2 = sv_s2['made']
    check('... again in South\'s: only the formula (its name numbered: the table has it), reading the Prob[local] saved for South before (saved once)',
          (len(m2), bool(m2) and bool(re.fullmatch(re.escape(f'Called grade orchard=South ({ps_name} ≥ 0.6)') + r'( \d+)?', m2[0]['name'])), bool(m2) and f':"{ps_name}"' in (m2[0]['formula'] or ''),
           bool(m2) and m2[0]['values'] == ms[-1]['values']), (1, True, True, True))
    # Save Profit Columns in South's (a Profit Matrix on grade): the Prob[] columns saved for South above read again (no new
    # ones), every formula within South, Expected Profit and Most Profitable reading the Profit[] columns just made
    await page.ev(f'''(async () => {{ const rep = SM.app.reports.at(-1); const t = rep.table;
      t.setProfitMatrix(t.col('grade').id, {{ levels: ['export', 'local'], decisions: ['export', 'local', 'Undecided'], matrix: {json.dumps(PM)} }});
      const d = new Promise(res => rep.on('done', res)); rep.run(); await d; }})()''', timeout=300)
    await page.mouse('mouseMoved', 2, 2)
    pc = await page.ev(f'''(async () => {{ const rep = SM.app.reports.at(-1); const t = rep.table; const before = t.columns.length;
      await ({PICK})('Decision Threshold', ['Save Profit Columns'], false, 1);
      for (let i = 0; i < 80 && t.columns.length < before + 5; i++) await new Promise(r => setTimeout(r, 100));
      return {{ cols: t.columns.slice(before).map(c => ({{ name: c.name, values: c.values, formula: c.formula ? c.formula.expr : null }})), orch: t.col('orchard').values }}; }})()''', timeout=300)
    cs = pc['cols']
    M_ = np.array(PM)
    pe_s = ms[0]['values'] if len(ms) == 3 else []
    exp_d = [[None if o_ != 'South' or a_ is None else a_ * M_[0, j] + b_ * M_[1, j] for a_, b_, o_ in zip(pe_s, prob_s, pc['orch'])] for j in range(3)]

    def same_vals(got, want):
        return len(got) == len(want) and all((g_ is None and w_ is None) or (g_ is not None and w_ is not None and abs(g_ - w_) < 1e-12) for g_, w_ in zip(got, want))
    exp_e = [None if d_[0] is None else max(d_) for d_ in zip(*exp_d)] if exp_d and exp_d[0] else []
    exp_m = [None if d_[0] is None else ['export', 'local', 'Undecided'][int(np.argmax(d_))] for d_ in zip(*exp_d)] if exp_d and exp_d[0] else []
    check('decisions: By orchard, Save Profit Columns in South\'s: Profit[d], Expected Profit and Most Profitable for South, reading South\'s Prob[] columns saved before (none new)',
          ([c['name'] for c in cs], all(f':"{ms[1]["name"] if len(ms) == 3 else "?"}"' in (c['formula'] or '') and '"South"' in (c['formula'] or '') for c in cs[:3])),
          (['Profit[export] orchard=South', 'Profit[local] orchard=South', 'Profit[Undecided] orchard=South', 'Expected Profit orchard=South', 'Most Profitable grade orchard=South'], True))
    check('... every row: South\'s Σ Prob × profit per decision, the largest, its decision; North\'s rows missing',
          (len(cs) == 5 and all(same_vals(cs[j]['values'], exp_d[j]) for j in range(3)), len(cs) == 5 and same_vals(cs[3]['values'], exp_e), len(cs) == 5 and cs[4]['values'] == exp_m), (True, True, True))
    await page.ev('''(async () => { const rep = SM.app.reports.at(-1); const t = rep.table; t.setProfitMatrix(t.col('grade').id, null);
      const d = new Promise(res => rep.on('done', res)); rep.run(); await d; })()''', timeout=300)
    await page.mouse('mouseMoved', 2, 2)
    await page.ev(pick_js('Decision Threshold', ['Target Level', 'export'], True, 1))
    lvs = {'North': 1, 'South': 0}
    res = await page.ev(f'({BY})({json.dumps(cuts)}, {json.dumps(lvs)})', timeout=300)
    check('... Target Level ▸ export in South\'s: South\'s tables of export at 0.6, North\'s of local at 0.4',
          (by_ok(res, cuts), res['opts']), ({'North': True, 'South': True}, {'~orchard=North|dtCut': 0.4, '~orchard=South|dtCut': 0.6, '~orchard=South|dtLevel': 0}))

    PROJ = """(async (edit) => { const rep = SM.app.reports.at(-1); const t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      if (edit) { const o = j.reports[0].spec.options; for (const k of Object.keys(o)) if (/\\|(dtCut|dtLevel)$/.test(k)) delete o[k]; o.dtCut = 0.3; }
      SM.app.loadProject(j); const back = SM.app.reports.at(-1);
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      return back.table !== t; })"""
    CLOSE = """(async () => { const back = SM.app.reports.at(-1); SM.app.closeTable(back.table); await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop(); const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close'); if (yes) yes.click(); return true; })()"""
    own = await page.ev(f'({PROJ})(false)', timeout=600)
    res = await page.ev(f'({BY})({json.dumps(cuts)}, {json.dumps(lvs)})', timeout=300)
    check('decisions: By orchard, a project: its own table, each group\'s threshold and target level again (North local at 0.4, South export at 0.6), the same numbers',
          (own, res['errors'], by_ok(res, cuts)), (True, [], {'North': True, 'South': True}))
    await page.ev(CLOSE)
    await page.ev(f'({PROJ})(true)', timeout=600)
    res = await page.ev(f'({BY})({json.dumps({"North": 0.3, "South": 0.3})}, {json.dumps(both)})', timeout=300)
    check('... an older project, with one threshold (0.3) for the whole report: every group at 0.3',
          (res['errors'], by_ok(res, {'North': 0.3, 'South': 0.3})), ([], {'North': True, 'South': True}))
    await page.ev(CLOSE)
    await page.ev('SM.app.closeReport(SM.app.reports.at(-1))')

    # (12c) what a Validation column holds (SM.predict.validationKind, as predictive.validation_codes reads it), and the
    # launch hints that follow it: Bootstrap Forest's and Boosted Tree's say that K folds turn Early Stopping off
    HINT = '''(async (kind) => {
      const n = 60; const c = { y: [], x1: [], F: [], S: [], B: [] };
      for (let i = 0; i < n; i++) { c.y.push(i % 3 ? 'a' : 'b'); c.x1.push(i * 0.1); c.F.push(1 + (i % 5)); c.S.push(['Training', 'Validation', 'Test'][i % 3]); c.B.push(i % 7 === 0 ? 2.5 : i % 2); }
      let t = SM.app.tables.find(q => q.name === 'Folds');
      if (!t) { t = new SM.Table({ name: 'Folds', source: 'test', columns: Object.entries(c).map(([name, values]) => ({ name, values, dataType: typeof values[0] === 'string' ? 'character' : 'numeric' })) }); SM.app.addTable(t); }
      SM.app.showTable(t.id);
      const kinds = ['F', 'S', 'B', 'y'].map(nm => SM.predict.validationKind(t.col(nm)));
      SM.app.launch(kind);
      await new Promise(r => setTimeout(r, 300));
      const dlg = [...document.querySelectorAll('.sm-launch-dialog')].pop();
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); items.find(x => x.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const unrole = (label, name) => [...role(label).querySelectorAll('li')].find(li => li.textContent === name).dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      pick('y'); role('Y, Response').querySelector('.sm-btn').click();
      pick('x1'); role('X, Factor').querySelector('.sm-btn').click();
      const hint = () => dlg.querySelector('.sm-ens-hint').textContent;
      pick('S'); role('Validation').querySelector('.sm-btn').click();
      const sets = hint();
      unrole('Validation', 'S');
      pick('F'); role('Validation').querySelector('.sm-btn').click();
      const folds = hint();
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'Cancel').click();
      return { kinds, sets, folds };
    })'''
    hf = await page.ev(f'({HINT})("forest")')
    hb = await page.ev(f'({HINT})("boosted")')
    check('decisions: SM.predict.validationKind: 1 to 5 folds, Training/Validation/Test sets, a numeric column neither (2.5 among 0 and 1), a character one of two values neither',
          hf['kinds'], ['folds', 'sets', 'bad', 'bad'])
    check('... Bootstrap Forest\'s and Boosted Tree\'s launch hints: nothing with a column of sets; with a K-fold column, Early Stopping off (every row trains)',
          (hf['sets'], 'K folds' in hf['folds'] and 'Early Stopping is off' in hf['folds'] and 'out-of-bag' in hf['folds'], hb['sets'], 'K folds' in hb['folds'] and 'Early Stopping is off' in hb['folds'] and 'one fit' in hb['folds']),
          ('', True, '', True))
    await page.ev(f'SM.app.showTab(SM.app.tabOf({tbl}))')

    # (13) the dark theme and phone width with the new parts open
    r = await page.ev(open_report_js('knn', {'y': ['grade'], 'x': XS, **val}, {'threshold': True, 'groupMetrics': oid, 'roc': True, 'rocTable': True, 'lift': True, 'gains': True, 'liftTable': True, 'seed': '5'}), timeout=900)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(3.0)
    st = await page.ev('(() => { const rep = SM.app.reports.at(-1); return { errors: [...rep.body.querySelectorAll(".sm-ob-error")].map(e => e.textContent), line: (rep.plots.find(p => /^Fitted probabilities/.test(p.opts.title)) || {}).userLayout.shapes[0].line.color }; })()')
    check('decisions: the dark theme redraws the Decision Threshold and Group Metrics without errors, the threshold in the dark theme\'s red', (st['errors'], st['line']), ([], '#ff7a6b'))
    await shot(page, 'learners-07-threshold-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await page.ev('(async () => { const rep = SM.app.reports.at(-1); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()', timeout=300)
    await asyncio.sleep(1.0)
    r = await page.ev('''(() => { const rep = SM.app.reports.at(-1); const body = rep.body.getBoundingClientRect();
      const boxes = rep.plots.filter(p => p.drawn && p.opts.fit !== false).map(p => p.box.getBoundingClientRect().right);
      const cut = rep.body.querySelector('.sm-pred-cut').getBoundingClientRect();
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), cut: cut.right <= body.right + 1 }; })()''')
    check('decisions at phone width: no sideways page scroll, the graphs and the threshold\'s controls fit', (r['page'], r['plots'], r['cut']), (True, True, True))
    await shot(page, 'learners-08-threshold-phone.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 1200, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await asyncio.sleep(2.0)
    await page.ev('SM.app.closeReport(SM.app.reports.at(-1))')


def pv_close(a, b, rel=1e-12):
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= rel * max(1.0, abs(float(b)))


async def main():
    page = await open_page(f'{BASE}/smui.html?example=orchard', height=1200)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "learners").map(f => f.module + ": " + f.error)')
    check('learners.py imports in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])
    check('scikit-learn is not loaded at the start', await page.ev("SM.engine.versions['scikit-learn'] || null"), None)

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const file = SM.app.menuItems('File');
      const exs = file.find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const an = SM.app.menuItems('Analyze');
      const pm = an.find(i => i.label === 'Predictive Modeling');
      const items = (typeof pm.submenu === 'function' ? pm.submenu() : pm.submenu).filter(i => !i.separator).map(i => i.label);
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), about: SM.io.EXAMPLES.orchard.about, inFile: labels.includes(SM.io.EXAMPLES.orchard.label), items,
               val: t.col('Validation').modelingType, counts: [0, 1, 2].map(k => t.col('Validation').values.filter(v => v === k).length) };
    })()''')
    check('?example=orchard opens the simulated orchard', (ex['name'], ex['rows'], ex['cols']), ('Orchard', 600, ['variety', W, S, F, 'skin', 'shelf life (days)', 'grade', 'orchard', 'Validation']))
    check('it is simulated, says how, and is in File > Examples', (ex['about'].startswith('Simulated'), ex['inFile']), (True, True))
    check('its Validation column holds 0, 1 and 2', sum(ex['counts']), 600)
    its = ex['items']
    check('Analyze > Predictive Modeling lists K Nearest Neighbors, Naive Bayes and Support Vector Machines, in that order',
          all(x in its for x in ('K Nearest Neighbors…', 'Naive Bayes…', 'Support Vector Machines…')) and its.index('K Nearest Neighbors…') < its.index('Naive Bayes…') < its.index('Support Vector Machines…'), True)

    # ======================================================================= K NEAREST NEIGHBORS
    r = await page.ev(launch_js('knn', [['Y, Response', ['variety']], ['X, Factor', XS], ['Validation', ['Validation']]], [['Number of Neighbors, K', 0]]))
    check('the K Nearest Neighbors dialog: Y, X, Validation and By; no Weight or Freq', r['shown'], ['Y, Response', 'X, Factor', 'Validation', 'By'])
    check('... the Number of Neighbors (10), then the validation portion, Informative Missing and the seed', [x.split('\n')[0] for x in r['optLabels']][:1] == ['Number of Neighbors, K'] and any('Random Seed' in x for x in r['optLabels']), True)
    check('... K = 0 is refused', (r['opened'], 'whole number from 1 to 1000' in r['msg']), (False, True))
    r = await page.ev(launch_js('knn', [['Y, Response', ['variety']], ['X, Factor', XS], ['Validation', ['Validation']]]), timeout=600)
    check('the first call loads scikit-learn 1.8.0', await page.ev("SM.engine.versions['scikit-learn'] || null"), '1.8.0')
    check('the report\'s outlines', r['outlines'], ['K Nearest Neighbors for variety', 'Model Selection', 'Chosen Model', 'Measures of Fit', 'Confusion Matrix'])
    check('no errors in the report', r['errors'], [])
    check('K = 10 reaches the report', r['options'].get('k'), 10)
    await shot(page, 'learners-01-knn.png')
    sel = await page.ev(table_under_js('Model Selection', 0))
    head = sel[0]
    check('Model Selection: K and the misclassification rate of each set (the counts optional)', head, ['K', 'Training Misclassification Rate', 'Validation Misclassification Rate', 'Test Misclassification Rate'])
    bf = await page.ev(BRUTE, timeout=120)
    check.near('K = 1: the training rate is the one computed here (each training row left out of its own neighbours)', num(sel[1][1]), bf['t1'], tol=1e-6)
    check.near('K = 1: the validation rate is the one computed here', num(sel[1][2]), bf['v1'], tol=1e-6)
    seed_ = await page.ev('SM.app.reports.at(-1).spec.options.seedDrawn')
    u_ = np.random.default_rng([int(seed_), 7]).random((600, 3))

    def tie_rate(rows_):
        wrong = 0
        for i_, votes, actual in rows_:
            vv = np.array(votes)
            top = vv == vv.max()
            wrong += int(int(np.argmax(np.where(top, u_[i_], -1.0))) != actual)
        return wrong / len(rows_)
    check.near('K = 5: training (a tied vote broken at random: the tied level with the largest of the report\'s seeded numbers)', num(sel[5][1]), tie_rate(bf['votes5t']), tol=1e-6)
    check.near('K = 5: validation', num(sel[5][2]), tie_rate(bf['votes5v']), tol=1e-6)
    check('K = 5: there are tied votes among them (so the rule is at work)', any(sorted(q[1])[-1] == sorted(q[1])[-2] for q in bf['votes5t'] + bf['votes5v']), True)
    vrates = [num(row[2]) for row in sel[1:]]
    best = vrates.index(min(vrates)) + 1
    marks = await page.ev('''(() => { const rep = SM.app.reports[SM.app.reports.length - 1];
      const tb = [...rep.body.querySelectorAll('table.sm-rt')].find(t => t.closest('.sm-ob').querySelector('.sm-ob-head').textContent.trim() === 'Model Selection');
      const trs = [...tb.querySelectorAll('tbody tr')];
      return { best: trs.findIndex(tr => tr.querySelector('.sm-lrn-best')) + 1, chosen: trs.findIndex(tr => tr.querySelector('.sm-lrn-chosen')) + 1,
               k: [...rep.body.querySelectorAll('table.sm-kv')].map(t => [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent))) }; })()''')
    check('the best K (the smallest validation rate) is marked, and shown', (marks['best'], marks['chosen']), (best, best))
    kv = dict((a, b) for a, b in marks['k'][0])
    check('Chosen Model: K and the best K', (kv.get('K'), kv.get('Best K')), (str(best), str(best)))
    meas = await page.ev(table_under_js('Measures of Fit', 0))
    mv = {row[0]: row for row in meas[1:]}
    check.near('the Measures of Fit are the chosen K\'s: its validation misclassification rate', num(mv['Validation'][meas[0].index('Misclassification Rate')]), vrates[best - 1], tol=1e-6)
    # a click on a line of the table shows that K
    r = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1];
      const tb = [...rep.body.querySelectorAll('table.sm-rt')].find(t => t.closest('.sm-ob').querySelector('.sm-ob-head').textContent.trim() === 'Model Selection');
      const done = new Promise(res => rep.on('done', res)); tb.querySelectorAll('tbody tr')[2].click(); await done;
      const kv = [...rep.body.querySelectorAll('table.sm-kv')][0];
      return { k: rep.spec.options.knnK, text: [...kv.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent)) }; })()''')
    check('a click on the K = 3 line shows K = 3', (r['k'], r['text'][0]), (3, ['K', '3']))
    meas3 = await page.ev(table_under_js('Measures of Fit', 0))
    check.near('... and its Measures of Fit', num({row[0]: row for row in meas3[1:]}['Validation'][meas3[0].index('Misclassification Rate')]), vrates[2], tol=1e-6)
    await rerun(page)
    check('Redo keeps the chosen K', (await page.ev(STATE))['options'].get('knnK'), 3)
    r = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => /by K$/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      for (let i = 0; i < 40 && !p.drawn; i++) await new Promise(r => setTimeout(r, 100));
      const done = new Promise(res => rep.on('done', res)); p.box.emit('plotly_click', { points: [{ x: 7, curveNumber: 1, pointNumber: 6 }] }); await done;
      return rep.spec.options.knnK; })()''')
    check('a click on a point of the plot shows that K', r, 7)
    await page.ev(pick_js('Model Selection', ['Select K', f'Best K ({best})']))
    check('Select K > Best K goes back to the best', (await page.ev(STATE))['options'].get('knnK'), None)
    await triangles(page, 'K Nearest Neighbors', 3)
    await page.ev(pick_js('*top*', ['ROC Curve']))
    await page.ev(pick_js('*top*', ['Profiler']))
    st = await page.ev(STATE)
    check('ROC Curve and Profiler from the red triangle', ('ROC Curve' in st['outlines'], 'Prediction Profiler' in st['outlines'], st['errors']), (True, True, []))
    prof = await page.ev('''(async () => { const rep = SM.app.reports[SM.app.reports.length - 1];
      const ob = [...rep.body.querySelectorAll('.sm-ob')].find(o => o.querySelector('.sm-ob-head').textContent.trim() === 'Prediction Profiler');
      const vals = () => [...ob.querySelectorAll('.sm-prof-val')].map(e => e.textContent);
      const before = vals();
      const inp = ob.querySelector('.sm-prof-x input[type="text"]');
      inp.value = '210'; inp.dispatchEvent(new Event('change'));
      for (let i = 0; i < 50 && vals().join() === before.join(); i++) await new Promise(r => setTimeout(r, 100));
      return { before, after: vals(), n: before.length }; })()''')
    check('the profiler: a probability per level, and a new weight moves them', (prof['n'], prof['after'] != prof['before']), (3, True))
    await shot(page, 'learners-02-knn-options.png')
    # Save Columns
    cols = await page.ev(save_js(['Save Columns', 'Save Predicteds']))
    check('Save Predicteds: Prob[Early], Prob[Mid], Prob[Late] and Most Likely variety', [c['name'] for c in cols], ['Prob[Early]', 'Prob[Mid]', 'Prob[Late]', 'Most Likely variety'])
    agree = await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Orchard');
      const v = t.col('Validation').values, y = t.col('variety').values, m = t.col('Most Likely variety').values;
      const pr = ['Early', 'Mid', 'Late'].map(l => t.col('Prob[' + l + ']').values);
      const rows = [...Array(t.nrows).keys()].filter(i => v[i] === 1);
      const ok = [...Array(t.nrows).keys()].every(i => { const p = pr.map(c => c[i]); return p.every(x => x > 0 && x < 1) && Math.abs(p.reduce((a, b) => a + b) - 1) < 1e-12; });
      return { rate: rows.filter(i => m[i] !== y[i]).length / rows.length, ok }; })()''')
    meas_now = await page.ev(table_under_js('Measures of Fit', 0))
    check.near('... the saved most likely levels miss the validation rows at the Measures of Fit\'s rate', agree['rate'], num({row[0]: row for row in meas_now[1:]}['Validation'][meas_now[0].index('Misclassification Rate')]), tol=1e-6)
    check('... every probability strictly between 0 and 1, summing to 1', agree['ok'], True)
    cols = await page.ev(save_js(['Save Columns', 'Save Near Neighbor Rows']))
    check('Save Near Neighbor Rows: RowNear 1 … RowNear 10', [c['name'] for c in cols], [f'RowNear {j}' for j in range(1, 11)])
    first = {i: rn for i, rn in bf['first']}
    got = {i: cols[0]['values'][i] for i in first}
    check('... RowNear 1 of each validation row is its nearest training row found here (a row number from 1)', got == first, True)
    # a continuous response
    rc = await page.ev(open_report_js('knn', {'y': ['shelf life (days)'], 'x': XS, 'validation': ['Validation']}, {'k': 8}), timeout=300)
    check('a continuous response: RASE by K, Actual by Predicted', ('Actual by Predicted Plot' in rc['outlines'], rc['errors']), (True, []))
    selc = await page.ev(table_under_js('Model Selection', 0))
    check('... the table gives each set\'s RASE for K = 1 to 8', (selc[0], len(selc) - 1), (['K', 'Training RASE', 'Validation RASE', 'Test RASE'], 8))
    cols = await page.ev(save_js(['Save Columns', 'Save Residuals']))
    check('... Save Residuals', [c['name'] for c in cols], ['Residual shelf life (days)'])

    # ======================================================================= NAIVE BAYES
    r = await page.ev(launch_js('naivebayes', [['Y, Response', ['shelf life (days)', 'variety']], ['X, Factor', XS], ['Validation', ['Validation']]]), timeout=300)
    check('the Naive Bayes dialog refuses a continuous Y', 'takes nominal or ordinal columns' in r['msgs'][0], True)
    check('... has Weight and Freq', ('Weight' in r['shown'], 'Freq' in r['shown']), (True, True))
    check('the report\'s outlines', r['outlines'], ['Naive Bayes for variety', 'Fit Details', 'Confusion Matrix'])
    await page.ev(pick_js('*top*', ['Class Parameters']))
    st = await page.ev(STATE)
    check('Class Parameters from the red triangle', 'Class Parameters' in st['outlines'], True)
    cols = await page.ev(save_js(['Save Columns', 'Save Predicteds']))
    check('Save Predicteds: the probabilities and the most likely level', [c['name'] for c in cols][-1], 'Most Likely variety 2')
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const o = rep.spec.options;
      const fit = await SM.engine.call('naivebayes.fit', { table: t.id, rows: null, y: 'variety', x: %s, weight: null, freq: null, validation: 'Validation', portion: 0, seed: o.seedDrawn, missing: 'informative', alpha: 1, var_smoothing: 1e-9 }, t);
      const L = fit.priors.map(p => p.level);
      const probs = [...Array(40).keys()].map(i => {
        const lp = fit.priors.map(p => Math.log(p.share));
        for (const f of fit.parameters) {
          const x = t.col(f.factor).values[i];
          if (f.kind === 'normal') f.rows.forEach((q, c) => { lp[c] += -0.5 * Math.log(2 * Math.PI * q.sd * q.sd) - (x - q.mean) ** 2 / (2 * q.sd * q.sd); });
          else { const j = f.labels.indexOf(String(x)); f.rows.forEach((q, c) => { lp[c] += Math.log(q['p' + j]); }); }
        }
        const m = Math.max(...lp); const e = lp.map(v => Math.exp(v - m)); const s = e.reduce((a, b) => a + b); return e.map(v => v / s);
      });
      const saved = [...Array(40).keys()].map(i => L.map(l => t.columns.filter(c => c.name.startsWith('Prob[' + l + ']')).pop().values[i]));
      let worst = 0; probs.forEach((p, i) => p.forEach((x, c) => { worst = Math.max(worst, Math.abs(x - saved[i][c])); }));
      return { worst, L };
    })()''' % json.dumps(XS))
    check.near('the saved probabilities are the class shares times the normal densities and level shares of the engine\'s parameters, computed here', r['worst'], 0.0, tol=1e-9)
    shares0 = await page.ev(table_under_js('Class Parameters', 4))
    await page.ev(pick_form_js('*top*', ['Smoothing…'], [0.5, None]))
    st = await page.ev(STATE)
    shares1 = await page.ev(table_under_js('Class Parameters', 4))
    check('Smoothing: α = 0.5 reaches the report and the level shares', (st['options'].get('nbAlpha'), shares0 != shares1), (0.5, True))
    await triangles(page, 'Naive Bayes', 2)
    await page.ev(pick_js('*top*', ['Profiler']))
    check('the profiler of Naive Bayes', 'Prediction Profiler' in (await page.ev(STATE))['outlines'], True)
    await shot(page, 'learners-03-nb.png')

    # ======================================================================= SUPPORT VECTOR MACHINES
    r = await page.ev(launch_js('svm', [['Y, Response', ['variety']], ['X, Factor', XS], ['Validation', ['Validation']]], [['Cost', -1]]))
    check('the Support Vector Machines dialog: its options', all(any(x.startswith(k) for x in r['optLabels']) for k in ('Kernel Function', 'Cost', 'Gamma', 'Tuning Design', 'Design Points')), True)
    check('... a negative Cost is refused', (r['opened'], 'Cost: a positive number' in r['msg']), (False, True))
    r = await page.ev(launch_js('svm', [['Y, Response', ['variety']], ['X, Factor', XS], ['Validation', ['Validation']]]), timeout=600)
    check('the report\'s outlines', r['outlines'], ['Support Vector Machines for variety', 'Model Summary', 'Fit Details', 'Confusion Matrix', 'Decision Boundary'])
    ms = await page.ev(table_under_js('Model Summary', 0))
    msd = {row[0]: row[1] for row in ms}
    check('Model Summary: the radial basis function, Cost 1, Gamma one over the 6 columns of X', (msd.get('Kernel Function'), msd.get('Cost'), msd.get('Gamma (1/columns of X)'), msd.get('Columns of X')), ('Radial Basis Function', '1', '0.166667', '6'))
    cols = await page.ev(save_js(['Save Columns', 'Save Predicteds']))
    agree = await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === 'Orchard');
      const v = t.col('Validation').values, y = t.col('variety').values, m = t.columns[t.columns.length - 1].values;
      const rows = [...Array(t.nrows).keys()].filter(i => v[i] === 2);
      return rows.filter(i => m[i] !== y[i]).length / rows.length; })()''')
    fd = await page.ev(table_under_js('Fit Details', 0))
    check.near('Save Predicteds: the most likely levels miss the test rows at Fit Details\' rate', agree, num({row[0]: row for row in fd[1:]}['Test'][fd[0].index('Misclassification Rate')]), tol=1e-6)
    # the decision boundary of a two-level response, linked to the rows
    r = await page.ev(open_report_js('svm', {'y': ['grade'], 'x': [W, S], 'validation': ['Validation']}, {}), timeout=300)
    check('grade by weight and sugar: a decision boundary', ('Decision Boundary' in r['outlines'], r['errors']), (True, []))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => /^Decision boundary over/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      for (let n = 0; n < 60 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      const names = p.traces.map(tr => tr.name);
      const ci = p.rows.findIndex(x => x && x.length);
      p._click({ points: [{ curveNumber: ci, pointNumber: 3 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[ci][5], p.rows[ci][9]]);
      const sp = p.box.data[ci].selectedpoints;
      t.select([]);
      return { names, sel, want: [p.rows[ci][3]], sp, n: p.rows.filter(Boolean).reduce((a, x) => a + x.length, 0), color: p.traces[ci].marker.color };
    })()''')
    check('the boundary, the margins, a trace per level and the support vectors', r['names'], ['Decision function', 'Boundary', 'Margins (±1)', 'export', 'local', 'Support vectors'])
    check('a point per row of the report', r['n'], 600)
    check('a click on a point selects its row', r['sel'], r['want'])
    check('rows selected in the table highlight their points', sorted(r['sp']), [5, 9])
    check('the first level takes the first colour (light theme)', r['color'], '#2a78d6')
    pos = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => /^Decision boundary over/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      await new Promise(r => setTimeout(r, 300));
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      const gd = p.box, xa = gd._fullLayout.xaxis, ya = gd._fullLayout.yaxis;
      let best = null, bestD = -1;
      p.traces.forEach((tr, ci) => { if (!p.rows[ci]) return; tr.x.forEach((x, k) => {
        let d = Infinity;
        p.traces.forEach((t2, c2) => { if (!p.rows[c2]) return; t2.x.forEach((x2, m) => { if (c2 === ci && m === k) return; d = Math.min(d, ((x - x2) / (xa.range[1] - xa.range[0])) ** 2 + ((tr.y[k] - t2.y[m]) / (ya.range[1] - ya.range[0])) ** 2); }); });
        if (d > bestD) { bestD = d; best = { ci, k }; } }); });
      const b = gd.getBoundingClientRect();
      return { x: b.left + xa._offset + xa.l2p(p.traces[best.ci].x[best.k]), y: b.top + ya._offset + ya.l2p(p.traces[best.ci].y[best.k]), row: p.rows[best.ci][best.k] };
    })()''')
    await page.click(pos['x'], pos['y'])
    await asyncio.sleep(0.5)
    check('a mouse click on a point over the shaded decision function selects that row', await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()'), [pos['row']])
    await page.mouse('mouseMoved', 2, 2)
    await page.ev('SM.app.reports[SM.app.reports.length - 1].table.select([])')
    await shot(page, 'learners-04-boundary.png')
    # the tuning design and the linear kernel from the red triangle
    await page.ev(pick_form_js('*top*', ['Tuning Design…'], [True, 6]), timeout=600)
    st = await page.ev(STATE)
    check('Tuning Design… adds the design (6 points), judged by the validation rows', ('Tuning Design' in st['outlines'], st['options'].get('tune'), st['options'].get('points')), (True, True, 6))
    td = await page.ev(table_under_js('Tuning Design', 0))
    crits = [num(row[2]) for row in td[1:]]
    ms = {row[0]: row[1] for row in await page.ev(table_under_js('Model Summary', 0))}
    bi = crits.index(min(crits))
    check('... the best point (the smallest validation rate) is the model\'s Cost and Gamma',
          (abs(num(ms.get('Cost (tuned)')) / num(td[bi + 1][0]) - 1) < 1e-4, abs(num(ms.get('Gamma (tuned)')) / num(td[bi + 1][1]) - 1) < 1e-4), (True, True))
    await page.ev(pick_js('*top*', ['Kernel Function', 'Linear']), timeout=600)
    ms = {row[0]: row[1] for row in await page.ev(table_under_js('Model Summary', 0))}
    check('Kernel Function > Linear: the linear kernel, no Gamma', (ms.get('Kernel Function'), any(k.startswith('Gamma') for k in ms)), ('Linear', False))
    await rerun(page)
    st = await page.ev(STATE)
    check('Redo keeps the kernel and the design', (st['options'].get('kernel'), st['options'].get('tune')), ('linear', True))
    await triangles(page, 'Support Vector Machines', 4)
    await page.ev(pick_js('*top*', ['Profiler']))
    check('the profiler of Support Vector Machines', 'Prediction Profiler' in (await page.ev(STATE))['outlines'], True)
    # a continuous response
    r = await page.ev(open_report_js('svm', {'y': ['shelf life (days)'], 'x': [W, S, F], 'validation': ['Validation']}, {}), timeout=300)
    check('SVR: Actual by Predicted and the prediction surface', ('Actual by Predicted Plot' in r['outlines'], 'Prediction Surface' in r['outlines'], r['errors']), (True, True, []))
    cols = await page.ev(save_js(['Save Columns', 'Save Predicteds']))
    cols2 = await page.ev(save_js(['Save Columns', 'Save Residuals']))
    check('... Save Predicteds and Save Residuals', ([c['name'] for c in cols], [c['name'] for c in cols2]), (['Predicted shelf life (days)'], ['Residual shelf life (days) 2']))

    # ======================================================================= BOOTSTRAP, BY, PROJECTS
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'naivebayes');
      SM.app.showTab(SM.app.tabOf(rep));
      const tb = [...rep.body.querySelectorAll('table.sm-rt')].find(t => t.closest('.sm-ob').querySelector('.sm-ob-head').textContent.trim() === 'Fit Details');
      const col = tb._rt.columns.find(c => c.label === 'Misclassification Rate');
      const res = await SM.bootstrap.run(tb, col, { B: 3, seed: 2, show: false });
      const knn = SM.app.reports.find(r => r.platform.id === 'knn');
      const kv = [...knn.body.querySelectorAll('table.sm-kv')][0];
      const res2 = await SM.bootstrap.run(kv, kv._rt.columns[1], { B: 3, seed: 2, show: false });
      return { n: res.nrows, cols: res.columns.map(c => c.name), first: res.columns[1].values, ks: res2.columns.find(c => c.name === 'K').values };
    })()''', timeout=600)
    check('Bootstrap reruns Naive Bayes headless: a row per sample, a column per set', (r['n'], r['cols']), (4, ['BootID', 'Training', 'Validation', 'Test']))
    check('... every sample gives its misclassification rate', all(isinstance(v, (int, float)) for v in r['first']), True)
    check('... and K Nearest Neighbors\' chosen K, from each sample\'s own validation rates', all(isinstance(v, (int, float)) and 1 <= v <= 10 for v in r['ks']), True)
    rep = await page.ev(open_report_js('knn', {'y': ['variety'], 'x': XS, 'validation': ['Validation'], 'by': ['orchard']}, {}), timeout=300)
    check('By orchard: one analysis per orchard', [o for o in rep['outlines'] if o.startswith('K Nearest Neighbors')], ['K Nearest Neighbors for variety orchard=North', 'K Nearest Neighbors for variety orchard=South'])
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const tbls = [...rep.body.querySelectorAll('table.sm-rt')].filter(t => t.dataset.rtKey === 'knnsel');
      const combined = SM.report.combineRT(tbls, 'x');
      return { n: tbls.length, groups: tbls.map(t => t.dataset.group), rows: combined.nrows, each: tbls.map(t => t._rt.rows.length) };
    })()''')
    check('... each group has its Model Selection, which combine into one table', (r['n'], r['groups'], r['rows']), (2, ['orchard=North', 'orchard=South'], sum(r['each'])))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'svm' && r.spec.options.kernel === 'linear');
      const knn = SM.app.reports.find(r => r.platform.id === 'knn' && !(r.spec.roles.by || []).length);
      const done = new Promise(res => knn.on('done', res)); knn.spec.options.knnK = 4; knn.run(); await done;
      const t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON(), knn.toJSON()] }));
      SM.app.loadProject(j);
      const backs = SM.app.reports.slice(-2);
      for (const b of backs) await new Promise(res => { if (!b.body.classList.contains('is-running') && b.body.querySelector('.sm-ob')) res(); else b.on('done', res); });
      const out = backs.map(b => ({ id: b.platform.id, newTable: b.table !== t, kernel: b.spec.options.kernel, tune: b.spec.options.tune, k: b.spec.options.knnK,
        heads: [...b.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent), errors: b.body.querySelectorAll('.sm-ob-error').length,
        kv: [...b.body.querySelectorAll('table.sm-kv')].slice(0, 1).map(t => [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent))) }));
      SM.app.closeTable(backs[0].table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })()''', timeout=900)
    svm_back, knn_back = r[0], r[1]
    check('a project: the SVM keeps its linear kernel and tuning design, on its own table', (svm_back['newTable'], svm_back['kernel'], svm_back['tune'], 'Tuning Design' in svm_back['heads'], svm_back['errors']), (True, 'linear', True, True, 0))
    check('... and K Nearest Neighbors its chosen K', (knn_back['k'], knn_back['kv'][0][0] if knn_back['kv'] else None, knn_back['errors']), (4, ['K', '4'], 0))

    # ---- the graphs' matplotlib code
    await charts(page)

    # ---- the shared Decision Threshold and the rest of smui-predict.js, K Nearest Neighbors' new options, Score Rows, Naive Bayes' formula
    await decisions(page)

    # ======================================================================= (i), Help, themes, phone
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-knn"); return ["knn", "naivebayes", "svm"].map(id => { const row = document.getElementById("help-p-" + id); return row ? row.textContent : null; }); })()')
    check('Help names the scikit-learn classes', ('KNeighborsClassifier' in (helps[0] or ''), 'GaussianNB' in (helps[1] or ''), 'SVC' in (helps[2] or '')), (True, True, True))
    topics = await page.ev('[...Object.keys(SM.platforms.get("knn").topics), ...Object.keys(SM.platforms.get("naivebayes").topics), ...Object.keys(SM.platforms.get("svm").topics)]')
    check('their topics', sorted(topics), sorted(['p:knn', 'p:knn:selection', 'p:knn:fit', 'p:knn:mosaic', 'p:learners:score', 'p:naivebayes', 'p:naivebayes:params', 'p:svm', 'p:svm:summary', 'p:svm:tuning', 'p:svm:boundary']))

    # ---- the (i) explains every input: the launch dialogs, the forms, Model Selection's clicks
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Orchard")))')
    for pid, label in (('knn', 'K Nearest Neighbors'), ('naivebayes', 'Naive Bayes'), ('svm', 'Support Vector Machines')):
        d = await dialog_help(page, f"SM.app.launch('{pid}')", pid, label)
        if pid == 'naivebayes':
            check("... its Informative Missing says a missing value is left out of the row's product", "left out of its row's product" in dict(d['sections'].get('Options', [])).get('Informative Missing', ''), True)
    knn = 'SM.app.reports.find(r => r.platform.id === "knn" && !(r.spec.roles.by || []).length)'
    nb = 'SM.app.reports.find(r => r.platform.id === "naivebayes")'
    svm = 'SM.app.reports.find(r => r.platform.id === "svm" && r.title === "Support Vector Machines for grade")'
    await form_help(page, f"await clickPath({knn}, '*top*', ['Number of Neighbors…']);", ['Number of Neighbors, K (every K up to it is fitted)'], 'K Nearest Neighbors\' Number of Neighbors…')
    await form_help(page, f"await clickPath({nb}, '*top*', ['Smoothing…']);", ["α, added to every count of a categorical factor's levels", 'Variance smoothing: the share of the largest variance added to each'], 'Naive Bayes\' Smoothing…')
    await form_help(page, f"await clickPath({svm}, '*top*', ['Cost and Gamma…']);", ['Cost', 'Gamma (empty: one over the columns of X)'], 'Support Vector Machines\' Cost and Gamma…')
    await form_help(page, f"await clickPath({svm}, '*top*', ['Tuning Design…']);", ['Fit a tuning design of Cost and Gamma', 'Number of design points'], '... and its Tuning Design…')
    s = await page.ev(info_js('slot', f"[...{knn}.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Model Selection')"))
    check('Model Selection\'s (i): a click on a line of the table or a point of the graph, Select K, Number of Neighbors', [c[0] for c in s['sections'].get('Choosing K', [])], ['A click on a line of the table or a point of the graph', 'Select K (red triangle)', 'Number of Neighbors… (red triangle)'])
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "svm" && r.title === "Support Vector Machines for grade")))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(3.0)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => ['knn', 'naivebayes', 'svm'].includes(r.platform.id));
      const rep = rs.find(r => r.title === 'Support Vector Machines for grade');
      const p = rep.plots.find(p => /^Decision boundary over/.test(p.opts.title));
      return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)), color: p ? p.traces[p.rows.findIndex(x => x && x.length)].marker.color : null }; })()''')
    check('the dark theme redraws the reports without errors', st['errors'], [])
    check('... the first level takes the dark theme\'s colour', st['color'], '#3987e5')
    await shot(page, 'learners-05-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    for pid, title in (('knn', 'K Nearest Neighbors for variety'), ('svm', 'Support Vector Machines for grade')):
        await page.ev('(async () => { const rep = SM.app.reports.filter(r => r.title === "%s").pop(); SM.app.showTab(SM.app.tabOf(rep)); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()' % title, timeout=300)
        await asyncio.sleep(1.0)
        r = await page.ev('''(() => {
          const rep = SM.app.reports.filter(r => r.title === "%s").pop();
          const body = rep.body.getBoundingClientRect();
          const boxes = rep.plots.filter(p => p.drawn && p.opts.fit !== false).map(p => p.box.getBoundingClientRect().right);
          return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length,
                   body: rep.body.scrollWidth <= rep.body.clientWidth + 1, scrollers: [...rep.body.querySelectorAll('table.sm-rt, .sm-lrn-scroll')].some(s => s.scrollWidth > s.clientWidth + 1) };
        })()''' % title)
        check(f'{pid} at phone width: no horizontal page scroll', r['page'], True)
        check(f'{pid} at phone width: the graphs fit', (r['plots'], r['n'] >= 1), (True, True))
        check(f'{pid} at phone width: wide tables scroll inside their own boxes', (r['body'], r['scrollers']), (True, True))
    await shot(page, 'learners-06-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


if __name__ == '__main__':
    asyncio.run(main())
    sys.exit(check.done())
