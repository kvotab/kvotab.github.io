#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Predictive Modeling > Model Comparison.

The platform sits in Analyze > Predictive Modeling before Fit Many Models;
its launch dialog, driven by real mouse clicks, lists the models the cast
columns make (probability columns grouped by their names and the reports
their notes name: this page's Prob[level], Fit Many Models' Prob[yes]
Discriminant, a prefix LR_, JMP's Prob(cls==yes), a column of predicted
levels) and finds the saved predictions of Y when Y, Predictors is empty;
the Measures of Fit hold the engine's numbers (and a misclassification rate
and an RSquare computed here from the table), the best of each measure is
bold within its group; every red triangle opens; ROC, AUC Comparison,
Lift, Cum Gains, Confusion Matrix and Decision Threshold (WP3's shared
report, every model) show; Level picks another level; Model Averaging adds
the mean as a model and Save Model Average writes live formula columns
(their values the mean of the models, the most likely level; a new
comparison of them gives the report's numbers); a continuous Y's Actual by
Predicted and Residual by Row, linked to the rows both ways; every graph's
code block run in the page's own Python gives the graph; By, a project, the
dark theme, phone width, the (i) topics and Help, and no script errors.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-compare.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import math
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine
from test_charts import GRAPHS_JS, figures_from_outputs, find_line, maxdiff, page_probe

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
REP = 'SM.app.reports[SM.app.reports.length - 1]'
LIGHT = ['#2f6690', '#c46a12', '#3a7d44', '#b0413e', '#6c5b7b', '#1a8a78', '#8f7600', '#8c564b', '#b8428f', '#666666', '#107f8f', '#7b5bb5']


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('*', '').replace('<', ''))


# A simulated table: a continuous y and a two-level cls, the models' saved predictions of both as the
# page's Save commands write them (names and notes), a validation column V, a numeric one Vn with value
# labels, a frequency f, a By column g.
MAKE = r'''
((n) => {
  const r = SM.util.rng('model comparison test');
  const sig = (z) => 1 / (1 + Math.exp(-z));
  const c = { y: [], cls: [], x1: [], x2: [], V: [], Vn: [], f: [], g: [] };
  const P = { lin: [], tree: [], pa: [], pb: [], pd: [], plr: [], pj: [] };
  for (let i = 0; i < n; i++) {
    const x1 = r.normal(), x2 = r.u() * 4 - 2, u = r.u();
    const eta = 1.2 * x1 - 0.7 * x2;
    c.x1.push(x1); c.x2.push(x2);
    c.y.push(1 + eta + r.normal());
    c.cls.push(eta + Math.log(1 / r.u() - 1) > 0 ? 'yes' : 'no');
    const s = u < 0.6 ? 0 : u < 0.8 ? 1 : 2;
    c.Vn.push(s); c.V.push(['Training', 'Validation', 'Test'][s]);
    c.f.push(1 + Math.floor(r.u() * 3));
    c.g.push(r.u() < 0.5 ? 'north' : 'south');
    P.lin.push(1 + 1.1 * x1 - 0.65 * x2 + 0.3 * r.normal());
    P.tree.push(Math.round(1 + eta + 0.8 * r.normal()));
    P.pa.push(sig(1.1 * eta + 0.3 * r.normal()));
    P.pb.push(sig(0.6 * x1 + 0.9 * r.normal()));
    P.pd.push(sig(0.9 * eta + 0.6 * r.normal()));
    P.plr.push(sig(0.8 * x1 - 0.2 * x2));
    P.pj.push(sig(eta + r.normal()));
  }
  const cols = Object.entries(c).map(([name, values]) => ({ name, values, dataType: typeof values[0] === 'string' ? 'character' : 'numeric',
    modelingType: name === 'Vn' ? 'nominal' : undefined, valueOrder: name === 'V' ? ['Training', 'Validation', 'Test'] : undefined }));
  const t = new SM.Table({ name: 'Compare', source: 'simulated', columns: cols });
  const add = (name, values, notes, extra = {}) => t.addColumn({ name, dataType: 'numeric', values, notes, ...extra });
  add('Predicted y', P.lin, 'saved from Fit Least Squares for y');
  add('Predicted y 2', P.tree, 'from Partition for y');
  add('Prob[no]', P.pa.map((p) => 1 - p), 'from Nominal Logistic Fit for cls');
  add('Prob[yes]', P.pa, 'from Nominal Logistic Fit for cls');
  add('Prob[no] 2', P.pb.map((p) => 1 - p), 'from Decision Forest for cls');
  add('Prob[yes] 2', P.pb, 'from Decision Forest for cls');
  add('Prob[yes] Discriminant', P.pd, 'from Fit Many Models for cls');
  add('LR_Prob[no]', P.plr.map((p) => 1 - p), '');
  add('LR_Prob[yes]', P.plr, '');
  add('Prob(cls==yes)', P.pj, '');   // JMP's own name, from a JMP table: no notes
  t.addColumn({ name: 'Most Likely cls', dataType: 'character', modelingType: 'nominal', values: P.pa.map((p) => (p >= 0.5 ? 'yes' : 'no')), valueOrder: ['no', 'yes'], notes: 'from Nominal Logistic Fit for cls' });
  if (t.setValueLabels) t.setValueLabels('Vn', { 0: 'Training', 1: 'Validation', 2: 'Test' });
  SM.app.addTable(t);
  return t.nrows;
})
'''

# Pick an item from an outline's red triangle (the top one: '*top*').
PICK = '''
(async (title, path, wait) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => { const t = h.querySelector('h2, h3, h4'); return t && (title === '*top*' ? t.tagName === 'H2' : t.textContent.trim() === title); });
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


def pick_js(title, path, wait=True):
    return f'({PICK})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(wait)})'


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

# The engine's own comparison of the last report, from its spec and SM.compare's grouping.
ENGINE = '''
(async (extra) => {
  const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table; const o = rep.spec.options;
  const col = (k) => (rep.spec.roles[k] || []).map((id) => t.col(id)).filter(Boolean);
  const y = col('y')[0];
  let cols = col('pred');
  if (!cols.length) cols = SM.compare.findPredictors(t, y, new Set([...(rep.spec.roles.group || []), ...(rep.spec.roles.freq || [])]));
  const G = SM.compare.modelsOf(t, y, cols);
  const pay = { table: t.id, rows: null, y: y.name, models: G.models, group: col('group')[0] ? col('group')[0].name : null, freq: col('freq')[0] ? col('freq')[0].name : null,
    average: !!o.average, alpha: 0.05, ...extra };
  return await SM.engine.call('compare.fit', pay, t);
})
'''


def engine_js(extra=None):
    return f'({ENGINE})({json.dumps(extra or {})})'


def rows_of(tbl, key_cols=2):
    """A report table (header first) as {(first cells): {column: text}}."""
    head = tbl[0]
    return {tuple(r[:key_cols]): dict(zip(head, r)) for r in tbl[1:]}


# The center of an element, for a real mouse click.
AT = '''
((sel, text, within) => {
  const root = within ? (new Function('return ' + within))() : document;
  const els = [...root.querySelectorAll(sel)].filter(e => text == null || e.textContent.trim() === text);
  const e = els[els.length - 1];
  if (!e) return null;
  e.scrollIntoView({ block: 'center' });
  const b = e.getBoundingClientRect();
  return [b.left + b.width / 2, b.top + b.height / 2];
})
'''


async def click(page, sel, text=None, within=None):
    xy = await page.ev(f'({AT})({json.dumps(sel)}, {json.dumps(text)}, {json.dumps(within)})')
    if not xy:
        return False
    await page.click(xy[0], xy[1])
    await asyncio.sleep(0.12)
    return True


# ---- the (i) of a launch dialog, a form or an outline: its sections
INFO = r'''
(async (kind, arg) => {
  const wait = (ms) => new Promise(r => setTimeout(r, ms));
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
  if (kind === 'slot') {
    const node = (new Function('return ' + arg))();
    btn = node && (node.matches('.info-btn') ? node : node.querySelector('.info-btn'));
  } else {
    const before = new Set(document.querySelectorAll('.sm-dialog'));
    (new Function('return (async () => {' + arg + '})()'))();
    for (let i = 0; i < 100 && !dlg; i++) { await wait(50); dlg = [...document.querySelectorAll('.sm-dialog')].find(d => !before.has(d)) || null; }
    if (!dlg) return { error: 'no dialog' };
    await wait(120);
    btn = dlg.querySelector('.sm-dialog-head .info-btn');
  }
  if (!btn) { if (dlg) dlg.querySelector('.sm-dialog-x').click(); return { error: 'no (i)' }; }
  btn.click();
  await wait(150);
  const out = read() || { error: 'no panel' };
  out.noTopic = KvotInfo.audit().noTopic;
  KvotInfo.close();
  if (dlg) { dlg.querySelector('.sm-dialog-x').click(); await wait(120); }
  return out;
})
'''


def info_js(kind, arg):
    return f'({INFO})({json.dumps(kind)}, {json.dumps(arg)})'


async def run_graph(page, code, table_js):
    out = await page.ev(f'__gr.run({json.dumps(page_probe(code))}, {table_js})', timeout=300)
    if isinstance(out, str):
        return None, out
    return figures_from_outputs(out.get('outputs'))


def curve_pts(t):
    return [(a, b) for a, b in zip(t.get('x') or [], t.get('y') or []) if a is not None and b is not None]


def subset_in_order(want, got, tol=1e-9):
    i = 0
    for w_ in want:
        while i < len(got) and not (abs(got[i][0] - w_[0]) <= tol * max(1, abs(w_[0])) and abs(got[i][1] - w_[1]) <= tol * max(1, abs(w_[1]))):
            i += 1
        if i == len(got):
            return False
        i += 1
    return True


def compare_graph(lab, g, F):
    """A Model Comparison graph (its Plotly traces) against the figure its code draws."""
    ax = F['axes'][0]
    t0 = g['label']
    check(f'{lab}: the titles, the size (100 pixels an inch)', (ax['xlabel'], ax['ylabel'], ax['title'], F['size']), (g['titles']['x'] or '', g['titles']['y'] or '', t0, [g['w'] / 100, g['h'] / 100]))
    if t0.startswith(('ROC ', 'Lift ', 'Cum Gains ', 'Precision Recall ')):
        curves = [t for t in g['traces'] if t.get('mode') == 'lines' and t.get('showlegend') is not False]
        ok = []
        for t in curves:
            ln = next((q for q in ax['lines'] if q['label'] == t['name']), None)
            ok.append(bool(ln) and subset_in_order(curve_pts(t), list(zip(ln['x'], ln['y']))) and (ln['color'] or '')[:7] == t['color'])
        check(f'{lab}: every model\'s curve holds the page\'s points, in the page\'s colour', (len(curves) > 1, ok), (True, [True] * len(curves)))
        check(f'{lab}: the legend, every model', F['legend'], [t['name'] for t in curves])
        if t0.startswith('Precision Recall '):
            y0 = g['shapes'][0]['y0']
            check(f'{lab}: the dotted line at the level\'s rate', any(q['ls'] == ':' and q['y'][:2] == [y0, y0] for q in ax['lines']), True)
        else:
            ref = [0, 1] if not t0.startswith('Lift ') else [1, 1]
            check(f'{lab}: the dotted reference', find_line(ax, [0, 1], ref) is not None, True)
    elif t0.startswith(('Actual by predicted', 'Residual by row')):
        pts = [t for t in g['traces'] if 'markers' in (t.get('mode') or '')]
        got = [tuple(p) for sc in ax['scatter'] for p in sc['xy']]
        want = [p for t in pts for p in curve_pts(t)]
        check.near(f'{lab}: every model\'s points', maxdiff([v for p in got for v in p], [v for p in want for v in p]), 0, 1e-9)
        check(f'{lab}: a colour per model, the page\'s', [sc['colors'][0][:7] for sc in ax['scatter']], [t['mcolor'] for t in pts])
        check(f'{lab}: the legend', F['legend'], [t['name'] for t in pts])
    else:
        return False
    return True


async def charts(page, name):
    """Every graph of the last report: its block right under it, run in the page, its figure the graph's."""
    gs = await page.ev(f'__gr.graphs({REP})', timeout=600)
    check(f'charts: {name}: every graph drawn', (await page.ev('__gr.take()'), len(gs) > 0), ([], True))
    n = 0
    for g in gs:
        if g['label'] and (g['label'].startswith(('Fitted probabilities', 'Profit')) or ' by threshold' in g['label']):
            # the Decision Threshold's graphs: SM.predict's (WP3's suites check their figures); their code runs on this report's head
            F, err = await run_graph(page, g['code'], 'SM.app.tables.find((t) => t.name === "Compare")') if g['code'] else (None, 'no code')
            check(f'charts: {name}: {g["label"]}: the Decision Threshold\'s block runs on the comparison\'s head', err, None)
            continue
        check(f'charts: {name}: {g["label"]}: its code block right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
        if not g['code']:
            continue
        F, err = await run_graph(page, g['code'], 'SM.app.tables.find((t) => t.name === "Compare")')
        check(f'charts: {name}: {g["label"]}: the code runs in the page', err, None)
        if not F:
            continue
        check(f'charts: {name}: {g["label"]}: a graph this test knows', compare_graph(f'charts: {name}: {g["label"]}', g, F[0]), True)
        n += 1
    return n


async def main():
    page = await open_page(f'{BASE}/smui.html', height=1200)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    check('compare.py imports in Pyodide', await page.ev('SM.engine.failed.filter(f => f.module === "compare").map(f => f.error)'), [])
    check('no script errors at load', page.errors, [])
    pm = await page.ev('''(() => { const it = SM.app.menuItems('Analyze').find(i => i.label === 'Predictive Modeling'); const s = (typeof it.submenu === 'function' ? it.submenu() : it.submenu).filter(i => !i.separator).map(i => i.label); return s; })()''')
    check('Analyze > Predictive Modeling: Model Comparison… right before Fit Many Models…', ('Model Comparison…' in pm, pm.index('Model Comparison…') + 1 == pm.index('Fit Many Models…') if 'Model Comparison…' in pm and 'Fit Many Models…' in pm else False), (True, True))
    check('the table', await page.ev(f'({MAKE})(900)'), 900)

    # ---- the launch dialog, by real clicks
    await page.ev("SM.app.launch('compare')")
    await asyncio.sleep(0.4)
    dlg = "[...document.querySelectorAll('.sm-launch-dialog')].pop()"
    list_ = f"{dlg}.querySelector('.sm-pick-list')"

    async def cast(names, role):
        for i, nm in enumerate(names):
            xy = await page.ev(f'({AT})(".sm-pick-list li", {json.dumps(nm)}, {json.dumps(dlg)})')
            await page.click(xy[0], xy[1], modifiers=0 if i == 0 else 4)   # 4: ⌘ (meta), adding to the selection
            await asyncio.sleep(0.05)
        await click(page, '.sm-role .sm-btn', role, dlg)

    models_now = f"[...{dlg}.querySelectorAll('.sm-mc-models li')].map(li => li.textContent)"
    check('the dialog\'s Models part asks for a response first', 'Cast the response' in await page.ev(f"{dlg}.querySelector('.sm-mc-hint').textContent"), True)
    await cast(['cls'], 'Y, Response')
    found = await page.ev(models_now)
    check('Y cast, Y, Predictors empty: the saved predictions found, grouped into models', found,
          ['Nominal Logistic Fit Prob[no], Prob[yes]', 'Decision Forest Prob[no] 2, Prob[yes] 2', 'Discriminant Prob[yes] Discriminant', 'LR LR_Prob[no], LR_Prob[yes]',
           'Prob(cls==yes) Prob(cls==yes)', 'Most Likely cls Most Likely cls'])
    await cast(['Prob[no]', 'Prob[yes]', 'Prob[no] 2', 'Prob[yes] 2', 'Prob[yes] Discriminant', 'LR_Prob[no]', 'LR_Prob[yes]'], 'Y, Predictors')
    check('columns cast in Y, Predictors: the models they make (by names and notes)', await page.ev(models_now),
          ['Nominal Logistic Fit Prob[no], Prob[yes]', 'Decision Forest Prob[no] 2, Prob[yes] 2', 'Discriminant Prob[yes] Discriminant', 'LR LR_Prob[no], LR_Prob[yes]'])
    hint = await page.ev(f"{dlg}.querySelector('.sm-mc-hint').textContent")
    check('... the dialog offers no validation column the table lacks', 'as Group to measure' in hint, False)
    await cast(['V'], 'Group')
    await cast(['f'], 'Freq')
    r = await page.ev(f'''(async () => {{
      const d = {dlg}; const n0 = SM.app.reports.length;
      return {{ roles: [...d.querySelectorAll('.sm-role')].map(r => [r.querySelector('.sm-btn').textContent, [...r.querySelectorAll('li')].map(li => li.textContent)]) }};
    }})()''')
    check('the roles as clicked', dict(r['roles']), {'Y, Response': ['cls'], 'Y, Predictors': ['Prob[no]', 'Prob[yes]', 'Prob[no] 2', 'Prob[yes] 2', 'Prob[yes] Discriminant', 'LR_Prob[no]', 'LR_Prob[yes]'],
                                                     'Group': ['V'], 'Freq': ['f'], 'By': []})
    n0 = await page.ev('SM.app.reports.length')
    await click(page, '.sm-actions .sm-btn', 'OK', dlg)
    for _ in range(200):
        if await page.ev(f'SM.app.reports.length > {n0} && !{REP}.body.classList.contains("is-running") && !!{REP}.body.querySelector(".sm-ob")'):
            break
        await asyncio.sleep(0.1)
    st = await page.ev(STATE)
    check('OK: the report', (st['title'], st['outlines'], st['errors']), ('Model Comparison for cls', ['Model Comparison for cls', 'Predictors', 'Measures of Fit for cls'], []))
    await shot(page, 'compare-01-report.png')

    # ---- the numbers against the engine, and two computed here
    eng = await page.ev(engine_js(), timeout=300)
    tbl = rows_of(await page.ev(table_under_js('Measures of Fit for cls', 0)))
    worst = 0.0
    for m in eng['measures']:
        row = tbl[(m['group'], m['label'])]
        for k, lab in (('entropy_rsquare', 'Entropy RSquare'), ('generalized_rsquare', 'Generalized RSquare'), ('mean_neg_log_p', 'Mean -Log p'), ('rase', 'RASE'),
                       ('mad', 'Mean Abs Dev'), ('misclassification', 'Misclassification Rate'), ('auc', 'AUC')):
            worst = max(worst, abs(num(row[lab]) - m[k]))
    check('the Measures of Fit hold the engine\'s numbers (4 decimals), every model and group', worst < 5.1e-5, True)
    check('... the rows: every group, every model', sorted(tbl), sorted((m['group'], m['label']) for m in eng['measures']))
    mine = await page.ev('''(() => {
      const t = SM.app.current; const v = t.col('V').values, f = t.col('f').values, y = t.col('cls').values, p = t.col('Prob[yes] 2').values;
      let bad = 0, tot = 0; for (let i = 0; i < t.nrows; i++) if (v[i] === 'Validation') { tot += f[i]; if ((p[i] > 0.5 ? 'yes' : 'no') !== y[i]) bad += f[i]; }
      return bad / tot; })()''')
    check.near('Decision Forest\'s validation misclassification rate = computed here from the table (rows by Freq)', num(tbl[('Validation', 'Decision Forest')]['Misclassification Rate']), round(mine, 4), 1e-9)
    bold = await page.ev('''(() => { const rep = SM.app.reports.at(-1); const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim() === 'Measures of Fit for cls');
      const tb = h.parentElement.querySelector('table.sm-rt'); const heads = [...tb.querySelectorAll('thead th')].map(t => t.textContent);
      const j = heads.indexOf('AUC'); return [...tb.querySelectorAll('tbody tr')].filter(tr => tr.cells[j].classList.contains('sm-mc-best')).map(tr => [tr.cells[0].textContent, tr.cells[1].textContent]); })()''')
    want = [[g, m['label']] for gi, g in enumerate(eng['groups']) for m in eng['models'] if m['key'] in eng['best'][str(gi)]['auc']]
    check('the best AUC of each group is bold', sorted(bold), sorted(want))
    fw = await page.ev('''(() => { const rep = SM.app.reports.at(-1); const tb = [...rep.body.querySelectorAll('table.sm-rt')].find(t => t.querySelector('td.sm-mc-best'));
      const td = tb.querySelector('td.sm-mc-best'); const cs = getComputedStyle(td); return [cs.fontWeight, td.textContent]; })()''')
    check('... bold as Fit Many Models marks it', int(fw[0]) >= 700, True)

    # ---- the red triangles and every comparison
    top = await page.ev('''(() => { const rep = SM.app.reports.at(-1); const h = rep.body.querySelector('.sm-ob-head h2').parentElement; h.querySelector('.sm-ob-menu').click();
      const m = [...document.querySelectorAll('.sm-menu')].pop(); const out = [...m.querySelectorAll('.sm-label')].map(x => x.textContent); SM.ui.closeMenus(0); return out; })()''')
    want_top = ['Model Averaging', 'Save Model Average', 'ROC Curve', 'AUC Comparison', 'Precision Recall Curve', 'Lift Curve', 'Cum Gains Curve', 'Confusion Matrix', 'Decision Threshold', 'Level']
    check('the top red triangle: JMP\'s items for a categorical response', [x for x in top if x in want_top], want_top)
    items = ('ROC Curve', 'AUC Comparison', 'Precision Recall Curve', 'Lift Curve', 'Cum Gains Curve', 'Confusion Matrix', 'Decision Threshold')
    for item in items:
        await page.ev(pick_js('*top*', [item]), timeout=300)
    st = await page.ev(STATE)
    check('each comparison shows, with no error', ([o for o in items if o in st['outlines']], st['errors']), (list(items), []))
    roc = await page.ev(f'{REP}.plots.filter(p => /^ROC /.test(p.opts.title)).map(p => ({{ title: p.opts.title, names: p.traces.map(t => t.name).filter(Boolean), colors: p.traces.map(t => t.line && t.line.color).filter(Boolean) }}))')
    check('ROC Curve: a graph per group, a curve per model, the level yes', [p_['title'] for p_ in roc], ['ROC Training yes', 'ROC Validation yes', 'ROC Test yes'])
    check('... the models in their colours', [n_.split(' (')[0] for n_ in roc[1]['names']], ['Nominal Logistic Fit', 'Decision Forest', 'Discriminant', 'LR'])
    check('... each curve its model\'s colour, the same in every graph', [p_['colors'][:4] for p_ in roc], [LIGHT[:4]] * 3)
    auc = rows_of(await page.ev(table_under_js('ROC Curve', 0)), 1)
    want = {m['label']: next(c['auc'] for c in eng['roc'][m['key']] if c['set'] == 'Validation' and c['level'] == 'yes') for m in eng['models']}
    check('... the AUC table is the engine\'s', max(abs(num(auc[(k,)]['Validation AUC']) - v) for k, v in want.items()) < 5.1e-5, True)
    ac = await page.ev(table_under_js('AUC Comparison', 0))
    check('AUC Comparison: each model\'s AUC, its standard error and interval', (ac[0], [r_[0] for r_ in ac[1:]]), (['Predictor', 'AUC', 'Std Error', 'Lower 95%', 'Upper 95%'], ['Nominal Logistic Fit', 'Decision Forest', 'Discriminant', 'LR']))
    e = next(a for a in eng['auc'] if a['group'] == 'Training')['levels'][1]
    check.near('... the engine\'s (DeLong) standard error', num(ac[1][2]), round(e['each'][0]['se'], 4), 1e-9)
    pairs = await page.ev(table_under_js('AUC Comparison', 1))
    check('... every pair, with its chi-square test', (len(pairs) - 1, pairs[0][-2:]), (6, ['ChiSquare', 'Prob>ChiSq']))
    await page.ev(pick_js('ROC Curve', ['Level', 'no']))
    roc = await page.ev(f'{REP}.plots.filter(p => /^ROC /.test(p.opts.title)).map(p => p.opts.title)')
    check('Level (red triangle) ▸ no: the curves of the other level', roc, ['ROC Training no', 'ROC Validation no', 'ROC Test no'])
    await page.ev(pick_js('ROC Curve', ['Level', 'yes']))
    cm = await page.ev(f'''(() => {{ const rep = {REP}; const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim() === 'Confusion Matrix'); return [...h.parentElement.querySelectorAll(':scope > .sm-ob-body > .sm-ob > .sm-ob-head h4, :scope > .sm-ob-body > .sm-ob > .sm-ob-head h3')].map(x => x.textContent); }})()''')
    check('Confusion Matrix: one per model', cm, ['Nominal Logistic Fit', 'Decision Forest', 'Discriminant', 'LR'])
    th = await page.ev(f'''(() => {{ const rep = {REP}; const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim() === 'Decision Threshold');
      const b = h.parentElement; return {{ input: !!b.querySelector('input[aria-label="Probability threshold"]'), text: b.textContent.slice(0, 4000) }}; }})()''')
    check('Decision Threshold: WP3\'s report, its threshold field', th['input'], True)
    check('... every model with probabilities in it', all(m_ in th['text'] for m_ in ('Nominal Logistic Fit', 'Decision Forest', 'Discriminant', 'LR')), True)
    tr = await page.ev(TRIANGLES)
    check('every red triangle opens, with its submenus', (tr['errors'], tr['triangles'] >= 7, tr['items'] > tr['triangles'], tr['subs'] > 0), ([], True, True, True))
    await shot(page, 'compare-02-comparisons.png')

    # ---- Model Averaging and Save Model Average
    await page.ev(pick_js('*top*', ['Model Averaging']))
    eng = await page.ev(engine_js(), timeout=300)
    tbl = rows_of(await page.ev(table_under_js('Measures of Fit for cls', 0)))
    avg = next(m for m in eng['measures'] if m['label'] == 'Model Average' and m['group'] == 'Validation')
    check('Model Averaging: the Model Average is one more model, the engine\'s numbers', ('Validation', 'Model Average') in tbl and abs(num(tbl[('Validation', 'Model Average')]['Entropy RSquare']) - avg['entropy_rsquare']) < 5.1e-5, True)
    await page.ev(pick_js('*top*', ['Save Model Average'], wait=False))
    await asyncio.sleep(0.6)
    sv = await page.ev('''(() => { const t = SM.app.current; const names = ['Prob[no] Model Average', 'Prob[yes] Model Average', 'Most Likely cls Model Average']; const cs = names.map(n => t.col(n));
      if (cs.some(c => !c)) return { missing: names.filter((n, i) => !cs[i]) };
      const P = (n) => t.col(n).values; const a = P('Prob[yes]'), b = P('Prob[yes] 2'), d = P('Prob[yes] Discriminant'), l = P('LR_Prob[yes]');
      let worst = 0, badMost = 0; for (let i = 0; i < t.nrows; i++) { const m = (a[i] + b[i] + d[i] + l[i]) / 4; worst = Math.max(worst, Math.abs(cs[1].values[i] - m), Math.abs(cs[0].values[i] - (1 - m)));
        if (cs[2].values[i] !== (cs[0].values[i] >= cs[1].values[i] ? 'no' : 'yes')) badMost++; }
      return { formulas: cs.map(c => !!c.formula), expr: cs[1].formula.expr, worst, badMost, type: [cs[2].dataType, cs[2].modelingType] }; })()''')
    check('Save Model Average: three live formula columns', sv.get('formulas'), [True, True, True])
    check('... Prob[yes] Model Average is the Mean of the models\' columns (Discriminant\'s no is 1 − its yes)', (sv.get('expr', '').startswith('Mean('), sv.get('worst', 1) < 1e-12), (True, True))
    check('... the most likely level, a nominal text column', (sv.get('badMost'), sv.get('type')), (0, ['character', 'nominal']))
    r = await page.ev(open_report_js('compare', {'y': ['cls'], 'pred': ['Prob[no] Model Average', 'Prob[yes] Model Average'], 'group': ['V'], 'freq': ['f']}, {}), timeout=300)
    t2 = rows_of(await page.ev(table_under_js('Measures of Fit for cls', 0)))
    check('... compared again, the saved Model Average (named by its suffix) gives the report\'s numbers', (('Validation', 'Model Average') in t2, t2.get(('Validation', 'Model Average'), {}).get('Entropy RSquare')), (True, tbl[('Validation', 'Model Average')]['Entropy RSquare']))
    await page.ev(f'SM.app.closeReport({REP})')

    # ---- a continuous response: actual by predicted and residual by row, linked both ways
    r = await page.ev(open_report_js('compare', {'y': ['y'], 'pred': ['Predicted y', 'Predicted y 2'], 'group': ['Vn']}, {'abp': True, 'resid': True, 'average': True}), timeout=300)
    check('continuous: the report, value labels naming the groups of Vn', (r['errors'], [o for o in r['outlines'] if o.endswith('Plot')]), ([], ['Actual by Predicted Plot', 'Residual by Row Plot']))
    eng = await page.ev(engine_js(), timeout=300)
    tbl = rows_of(await page.ev(table_under_js('Measures of Fit for y', 0)))
    check('... the groups by their labels', sorted({k[0] for k in tbl}), sorted(['Training', 'Validation', 'Test']))
    worst = max(abs(num(tbl[(m['group'], m['label'])][lab]) - m[k]) for m in eng['measures'] for k, lab in (('rsquare', 'RSquare'), ('rase', 'RASE'), ('mad', 'AAE'), ('mse', 'MSE'), ('mape', 'MAPE'), ('corr', 'Correlation')))
    check('... the engine\'s numbers (4 decimals)', worst < 5.1e-5, True)
    r2 = await page.ev('''(() => { const t = SM.app.current; const y = t.col('y').values, p = t.col('Predicted y').values, v = t.col('Vn').values; let sse = 0, n = 0, s = 0;
      for (let i = 0; i < t.nrows; i++) if (v[i] === 1) { n++; s += y[i]; } const mean = s / n; let sst = 0; for (let i = 0; i < t.nrows; i++) if (v[i] === 1) { sse += (y[i] - p[i]) ** 2; sst += (y[i] - mean) ** 2; } return 1 - sse / sst; })()''')
    check.near('... the validation RSquare of Predicted y = 1 − SSE/SST computed here', num(tbl[('Validation', 'Predicted y')]['RSquare']), round(r2, 4), 1e-9)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.at(-1); const t = rep.table;
      const ps = rep.plots.filter(p => /^Actual by predicted /.test(p.opts.title));
      const p = ps[1]; p.box.scrollIntoView({ block: 'center' });
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      p._click({ points: [{ curveNumber: 1, pointNumber: 4 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[0][2], p.rows[0][9]]);
      await new Promise(r => setTimeout(r, 200));
      const sp = p.box.data.slice(0, 3).map(d => d.selectedpoints);
      t.select([]);
      return { titles: ps.map(q => q.opts.title), sel, want: [p.rows[1][4]], sp };
    })()''')
    check('Actual by Predicted: a graph per group, every model on it', r['titles'], ['Actual by predicted Training', 'Actual by predicted Validation', 'Actual by predicted Test'])
    check('... a click on a point selects its row', r['sel'], r['want'])
    check('... rows selected in the table are highlighted in every model\'s points', r['sp'], [[2, 9]] * 3)
    await page.ev(pick_js('*top*', ['Save Model Average'], wait=False))
    await asyncio.sleep(0.6)
    r = await page.ev('''(() => { const t = SM.app.current; const c = t.col('Predicted y Model Average'); if (!c) return null;
      const a = t.col('Predicted y').values, b = t.col('Predicted y 2').values; let worst = 0; for (let i = 0; i < t.nrows; i++) worst = Math.max(worst, Math.abs(c.values[i] - (a[i] + b[i]) / 2));
      return { expr: c.formula && c.formula.expr, worst, notes: c.notes }; })()''')
    check('continuous: Save Model Average writes Mean() of the models\' columns, a live formula', (r and r['expr'], r and r['worst'] < 1e-12, r and 'Model Averaging' in r['notes']), ('Mean(:"Predicted y", :"Predicted y 2")', True, True))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'compare' && r.title === 'Model Comparison for y');
      const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim() === 'Measures of Fit for y');
      const tbl = h.parentElement.querySelector('table.sm-rt');
      const col = tbl._rt.all.find(c => c.label === 'RSquare');
      const t = await SM.bootstrap.run(tbl, col, { B: 3, seed: 1, show: false });
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), finite: t.columns.slice(1).every(c => c.values.every(Number.isFinite)) };
    })()''', timeout=900)
    check('Bootstrap of a Measures of Fit column: the comparison again on resampled rows, a column per group and model', (r['name'], r['rows'], len(r['cols']) - 1, r['finite']),
          ('Bootstrap Results of Model Comparison for y', 4, 9, True))
    await shot(page, 'compare-03-continuous.png')

    # ---- every graph's code, run in the page's own Python
    await page.ev(GRAPHS_JS)
    n1 = await charts(page, 'continuous')
    r = await page.ev(open_report_js('compare', {'y': ['cls'], 'pred': ['Prob[no]', 'Prob[yes]', 'Prob[yes] 2', 'Prob[yes] Discriminant'], 'group': ['V'], 'freq': ['f']},
                                     {'roc': True, 'lift': True, 'gains': True, 'pr': True, 'average': True}), timeout=300)
    n2 = await charts(page, 'categorical')
    r = await page.ev(open_report_js('compare', {'y': ['cls'], 'pred': ['Prob[no]', 'Prob[yes]', 'Prob[yes] 2'], 'group': ['V'], 'freq': ['f']}, {'threshold': True}), timeout=300)
    await charts(page, 'Decision Threshold')
    codes = await page.ev(f'''(() => {{ const rep = {REP}; const h = [...rep.body.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim() === 'Decision Threshold');
      return [...h.parentElement.querySelectorAll('details.sm-code code')].map(c => c.textContent).filter(c => !/plt\\.show\\(\\)\\s*$/.test(c)); }})()''')
    errs = []
    for code in codes:
        out = await page.ev(f'__gr.run({json.dumps(code)}, SM.app.tables.find((t) => t.name === "Compare"))', timeout=300)
        errs += [f"{o.get('ename')}: {o.get('evalue')}" for o in (out or {}).get('outputs', []) if o.get('type') == 'error'] if isinstance(out, dict) else [str(out)]
    check('Decision Threshold: its tables\' code blocks run on the comparison\'s head too', (len(codes) > 0, errs), (True, []))
    check('charts: the blocks ran and drew the page\'s graphs', (n1, n2), (6, 12))

    # ---- By, a project
    r = await page.ev(open_report_js('compare', {'y': ['cls'], 'pred': ['Prob[no]', 'Prob[yes]', 'Prob[yes] 2'], 'group': ['V'], 'by': ['g']}, {'roc': True, 'level': 0}), timeout=300)
    check('By g: a comparison per level', [o for o in r['outlines'] if o.startswith('Model Comparison')], ['Model Comparison for cls g=north', 'Model Comparison for cls g=south'])
    r = await page.ev('''(() => { const rep = SM.app.reports.at(-1); const tbls = [...rep.body.querySelectorAll('table.sm-rt')].filter(t => t.dataset.rtKey === 'measures');
      const c = SM.report.combineRT(tbls, 'x'); return { n: tbls.length, groups: tbls.map(t => t.dataset.group), rows: c.nrows }; })()''')
    check('... their Measures of Fit combine into one table', (r['n'], r['groups'], r['rows']), (2, ['g=north', 'g=south'], 12))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.at(-1); const t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports.at(-1);
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const cell = (r0) => [...r0.body.querySelectorAll('table.sm-rt')].filter(x => x.dataset.rtKey === 'measures').map(x => x.textContent).join('|');
      const out = { newTable: back.table !== t, pred: back.spec.roles.pred.map(id => back.table.col(id).name), opts: [back.spec.options.roc, back.spec.options.level], same: cell(back) === cell(rep),
        rocTitles: back.plots.filter(p => /^ROC /.test(p.opts.title)).map(p => p.opts.title).slice(0, 1), errors: back.body.querySelectorAll('.sm-ob-error').length };
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop(); const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close'); if (yes) yes.click();
      return out;
    })()''', timeout=300)
    check('a project: its own table, the columns found again, the options kept, the same tables', (r['newTable'], r['pred'], r['opts'], r['same'], r['rocTitles'], r['errors']),
          (True, ['Prob[no]', 'Prob[yes]', 'Prob[yes] 2'], [True, 0], True, ['ROC Training no'], 0))

    # ---- (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic, every Help link a target', (audit.get('noTopic'), audit.get('brokenMore')), ([], []))
    d = await page.ev(info_js('dialog', "SM.app.launch('compare')"))
    want = await page.ev('SM.platforms.get("compare").launch.roles.map(r => [r.label, r.help])')
    roles = dict((d.get('sections') or {}).get('Roles', []))
    check('the launch dialog\'s (i): every role with its help', [(lab, bool(h) and roles.get(lab, '').startswith(h)) for lab, h in want], [(lab, True) for lab, _ in want])
    check('... the platform\'s topic first, with its Differences from JMP', ('Differences from JMP' in d.get('headings', []), d.get('noTopic')), (True, []))
    for title in ('Measures of Fit for cls', 'ROC Curve', 'AUC Comparison'):
        s = await page.ev(info_js('slot', f"[...SM.app.reports.find(r => r.platform.id === 'compare' && r.title === 'Model Comparison for cls').body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === {json.dumps(title)})"))
        check(f'the {title} outline\'s (i) opens its topic', bool(s.get('title')) and 'error' not in s, True)
    helps = await page.ev('(() => { SM.app.showHelp("p-compare"); const row = document.getElementById("help-p-compare"); return row ? row.textContent : null; })()')
    check('Help lists the platform, its about and what it uses', bool(helps) and 'Model Comparison' in helps and 'DeLong' in helps, True)

    # ---- the dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "compare" && r.spec.options.gains)))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(3)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => r.platform.id === 'compare'); return rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)); })()''')
    check('the dark theme redraws the reports without errors', st, [])
    col = await page.ev('(() => { const rep = SM.app.reports.find(r => r.platform.id === "compare" && r.spec.options.gains); const p = rep.plots.find(p => /^ROC /.test(p.opts.title)); return p.traces[0].line.color; })()')
    check('... the curves take the dark theme\'s colours', col, '#6fa3d6')
    await shot(page, 'compare-04-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports.find(r => r.platform.id === "compare" && r.spec.options.gains); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()', timeout=300)
    await asyncio.sleep(1.0)
    r = await page.ev('''(() => {
      const rep = SM.app.reports.find(r => r.platform.id === "compare" && r.spec.options.gains);
      const body = rep.body.getBoundingClientRect();
      const boxes = rep.plots.filter(p => p.drawn && p.opts.fit !== false).map(p => p.box.getBoundingClientRect().right);
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length, body: rep.body.scrollWidth <= rep.body.clientWidth + 1 };
    })()''')
    check('phone width: no horizontal page scroll, the graphs fit, wide tables scroll in their own boxes', (r['page'], r['plots'], r['n'] >= 1, r['body']), (True, True, True, True))
    await shot(page, 'compare-05-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


if __name__ == '__main__':
    asyncio.run(main())
    sys.exit(check.done())
