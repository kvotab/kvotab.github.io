#!/usr/bin/env python3
"""smui.html in a real browser: the matplotlib code under DOE's graphs.

Evaluate Design on a full factorial made by its dialog (two continuous
factors, one coded by its column notes, and a categorical one; a row
excluded; two models and power settings): every graph (the prediction
variance profile of each factor, the fraction of design space, the colour
map on correlations) has its code block right under it, ending in
plt.show(); the block runs in the page's own Python (the notebook's runner)
and its figure is the Plotly graph's: the curves, the levels, the
correlations and the line before the alias terms, the titles and the size.
Sample Size and Power: every situation with curves, with the field it
computes by default and with others, each curve's block gives the report's
power along its grid, the exact power, the report's point and the line at
alpha. A split plot from the Full Factorial dialog (a factor that is hard to
change): the Changes column, the run count, Simulate Responses' form and its
formula column (the whole plots' draws shared by their runs; the model's
part exact), the table's Model scripts (run from the Table panel), and Fit
Model's Recall opening the design's model with Whole Plots random, fitted by
REML with the split plot's degrees of freedom; Evaluate Design of the split
plot (without the whole plots, a note; with them in the Whole Plots role or
among the factors: the whole-plot and within-plot DFDen, less power for the
hard-to-change factor, the graphs' code run in the page, a variance ratio of
4); the dialog at phone width. The rest of DOE's browser checks are in test-ui-quality.py.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-doe.py

Exit status 0 when every check passes.
"""
import asyncio
import json
import sys

from cdp import BASE, Checks, open_page, wait_engine
from test_charts import GRAPHS_JS, figures_from_outputs, maxdiff, page_probe, run_graph

check = Checks()

MAKE_DESIGN = r'''(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  SM.commands.all().find((c) => c.label === 'Full Factorial Design…').action(SM.app);
  await sleep(900);
  const dlg = [...document.querySelectorAll('.sm-dialog')].pop();
  const rows = [...dlg.querySelectorAll('.sm-doe-factors tbody tr')];
  const set = (i, v) => { i.value = v; i.dispatchEvent(new Event('change')); };
  let inp = rows[0].querySelectorAll('input'); set(inp[0], 'Temp'); set(inp[1], '150'); set(inp[2], '200');
  inp = rows[1].querySelectorAll('input'); set(inp[0], 'Time'); set(inp[1], '10'); set(inp[2], '20');
  const role = rows[2].querySelector('select'); role.value = 'categorical'; role.dispatchEvent(new Event('change'));
  inp = rows[2].querySelectorAll('input'); set(inp[0], 'Cat'); set(inp[1], 'a, b, c');
  for (const [label, v] of [['Number of Center Points', '3'], ['Random Seed', '7']]) { const lab = [...dlg.querySelectorAll('.sm-form label')].find((l) => l.textContent === label); set(lab.nextElementSibling, v); }
  const n0 = SM.app.tables.length;
  [...dlg.querySelectorAll('.sm-dialog-foot .sm-btn')].find((b) => b.textContent === 'Make Table').click();
  for (let i = 0; i < 150 && SM.app.tables.length === n0; i++) await sleep(100);
  const t = SM.app.tables[SM.app.tables.length - 1];
  // Time's notes lose their coding: Evaluate Design then takes the data's range
  t.col('Time').notes = 'Factor.';
  return { name: t.name, rows: t.nrows, cols: t.columns.map((c) => [c.name, c.modelingType]) };
})()'''

SPLIT = r'''(async (sim) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  SM.commands.all().find((c) => c.label === 'Full Factorial Design…').action(SM.app);
  await sleep(900);
  const dlg = [...document.querySelectorAll('.sm-dialog')].pop();
  const rows = [...dlg.querySelectorAll('.sm-doe-factors tbody tr')];
  const set = (i, v) => { i.value = v; i.dispatchEvent(new Event('change')); };
  const field = (root, label) => { const lab = [...root.querySelectorAll('.sm-form label')].find((l) => l.textContent === label); return lab && (lab.control || lab.nextElementSibling); };
  const out = { heads: [...dlg.querySelectorAll('.sm-doe-factors th')].map((th) => th.textContent) };
  let inp = rows[0].querySelectorAll('input'); set(inp[0], 'Oven'); set(inp[1], '150'); set(inp[2], '200');
  inp = rows[1].querySelectorAll('input'); set(inp[0], 'Time');
  const role = rows[2].querySelector('select'); role.value = 'categorical'; role.dispatchEvent(new Event('change'));
  inp = rows[2].querySelectorAll('input'); set(inp[0], 'Recipe'); set(inp[1], 'a, b, c');
  const note = () => [...dlg.querySelectorAll('.sm-ob-note')].pop().textContent;
  set(field(dlg, 'Number of Center Points'), '0');   // (the dialog keeps the last design's settings)
  set(field(dlg, 'Number of Replicates'), '0');
  out.before = [note(), field(dlg, 'Number of Whole Plots').disabled];
  set(rows[0].querySelector('select[aria-label="Changes"]'), 'hard');
  out.after = [note(), field(dlg, 'Number of Whole Plots').disabled, field(dlg, 'Number of Whole Plots').placeholder, field(dlg, 'Replicates as Blocks').disabled];
  set(field(dlg, 'Number of Whole Plots'), '6');
  out.six = note();
  set(field(dlg, 'Number of Whole Plots'), '');
  set(field(dlg, 'Random Seed'), '11');
  const box = field(dlg, 'Simulate Responses'); box.checked = true; box.dispatchEvent(new Event('change'));
  const n0 = SM.app.tables.length;
  [...dlg.querySelectorAll('.sm-dialog-foot .sm-btn')].find((b) => b.textContent === 'Make Table').click();
  for (let i = 0; i < 150 && SM.app.tables.length === n0; i++) await sleep(100);
  const t = SM.app.tables[SM.app.tables.length - 1];
  out.name = t.name; out.rows = t.nrows; out.cols = t.columns.map((c) => c.name);
  out.scripts0 = (t.scripts || []).map((x) => [x.name, x.platform, x.spec.effects.filter((e) => e.random).map((e) => e.names.join('*'))]);
  let f = null;
  for (let i = 0; i < 60 && !f; i++) { await sleep(100); f = document.querySelector('.sm-dialog[aria-label="Simulate Responses"]'); }
  if (!f) return { ...out, error: 'no Simulate Responses form' };
  out.fields = [...f.querySelectorAll('.sm-form label')].map((l) => l.textContent);
  for (const [k, v] of Object.entries(sim)) set(field(f, k), String(v));
  const n1 = t.columns.length;
  [...f.querySelectorAll('.sm-dialog-foot .sm-btn')].find((b) => b.textContent === 'Make Column').click();
  for (let i = 0; i < 100 && t.columns.length === n1; i++) await sleep(100);
  const c = t.columns[t.columns.length - 1];
  out.sim = { name: c.name, formula: c.formula && c.formula.expr, values: t.columns.find((x) => x.id === c.id).values.slice(0, t.nrows) };
  out.data = Object.fromEntries(['Oven', 'Time', 'Recipe', 'Whole Plots'].map((n) => [n, Array.from({ length: t.nrows }, (_, r) => t.col(n).values[r])]));
  out.scripts = (t.scripts || []).map((x) => [x.name, x.spec.roles.y]);
  return out;
})'''

RECALL = r'''(async (name) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const t = SM.app.tables.find((x) => x.name === name);
  SM.app.showTab(SM.app.tabOf(t));
  SM.app.launch('fitmodel'); await sleep(400);
  const dlg = [...document.querySelectorAll('.sm-launch-dialog')].pop();
  [...dlg.querySelectorAll('button')].find((b) => b.textContent === 'Recall').click(); await sleep(100);
  const out = { effects: [...dlg.querySelectorAll('.sm-fm-effects li')].map((li) => li.textContent), y: [...dlg.querySelectorAll('.sm-role-list')][0].textContent };
  const n0 = SM.app.reports.length;
  [...dlg.querySelectorAll('button')].find((b) => b.textContent === 'OK').click();
  for (let i = 0; i < 100 && SM.app.reports.length === n0; i++) await sleep(50);
  const rep = SM.app.reports[SM.app.reports.length - 1];
  for (let i = 0; i < 2400 && (rep.body.classList.contains('is-running') || !rep.content.querySelector('.sm-ob')); i++) await sleep(25);
  const head = (title) => [...rep.body.querySelectorAll('.sm-ob-head')].find((x) => x.querySelector('h2, h3, h4').textContent === title);
  const rowsOf = (title) => { const h = head(title); const tb = h && h.parentElement.querySelector(':scope > .sm-ob-body table.sm-rt'); return tb ? [...tb.querySelectorAll('tr')].map((tr) => [...tr.children].map((x) => x.textContent.trim())) : null; };
  out.errors = [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent);
  out.vc = rowsOf('REML Variance Component Estimates');
  out.tests = rowsOf('Fixed Effect Tests');
  return out;
})'''

BLOCKS = r'''(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  SM.commands.all().find((c) => c.label === 'Full Factorial Design…').action(SM.app);
  await sleep(800);
  const dlg = [...document.querySelectorAll('.sm-dialog')].pop();
  const rows = [...dlg.querySelectorAll('.sm-doe-factors tbody tr')];
  const set = (i, v) => { i.value = v; i.dispatchEvent(new Event('change')); };
  const field = (label) => { const lab = [...dlg.querySelectorAll('.sm-form label')].find((l) => l.textContent === label); return lab && (lab.control || lab.nextElementSibling); };
  const note = () => [...dlg.querySelectorAll('.sm-ob-note')].pop().textContent;
  for (const tr of rows) set(tr.querySelector('select[aria-label="Changes"]'), 'easy');
  const box = field('Simulate Responses'); box.checked = false; box.dispatchEvent(new Event('change'));
  set(field('Number of Center Points'), '0'); set(field('Number of Replicates'), '0');
  const out = { none: field('Replicates as Blocks').disabled };
  set(field('Number of Replicates'), '1');
  out.one = field('Replicates as Blocks').disabled;
  const b = field('Replicates as Blocks'); b.checked = true; b.dispatchEvent(new Event('change'));
  out.runs = note();
  const n0 = SM.app.tables.length;
  [...dlg.querySelectorAll('.sm-dialog-foot .sm-btn')].find((x) => x.textContent === 'Make Table').click();
  for (let i = 0; i < 150 && SM.app.tables.length === n0; i++) await sleep(100);
  const t = SM.app.tables[SM.app.tables.length - 1];
  out.cols = t.columns.map((c) => c.name); out.rows = t.nrows;
  out.scripts = (t.scripts || []).map((x) => [x.name, x.spec.effects.filter((e) => e.random).map((e) => e.names.join('*'))]);
  return out;
})()'''

SCRIPT = r'''(async (name, script) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const t = SM.app.tables.find((x) => x.name === name);
  SM.app.showTab(SM.app.tabOf(t)); await sleep(300);
  const b = [...document.querySelectorAll('.sm-script')].find((x) => x.querySelector('.sm-scriptname').textContent === script);
  if (!b) return { error: `no ${script} script in the Table panel` };
  b.click(); await sleep(400);
  const dlg = [...document.querySelectorAll('.sm-launch-dialog')].pop();
  const out = { effects: [...dlg.querySelectorAll('.sm-fm-effects li')].map((li) => li.textContent), y: [...dlg.querySelectorAll('.sm-role-list')][0].textContent };
  [...dlg.querySelectorAll('button')].find((x) => x.textContent === 'Cancel').click();
  return out;
})'''

PHONE = r'''(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  SM.commands.all().find((c) => c.label === 'Full Factorial Design…').action(SM.app);
  await sleep(700);
  const dlg = [...document.querySelectorAll('.sm-dialog')].pop();
  const box = dlg.getBoundingClientRect();
  const out = { page: document.documentElement.scrollWidth <= innerWidth, dialog: box.right <= innerWidth + 0.5 && box.left >= -0.5,
    inside: [...dlg.querySelectorAll('.sm-doe-sec')].every((s) => s.getBoundingClientRect().right <= box.right + 0.5),
    changes: !!dlg.querySelector('select[aria-label="Changes"]') };
  [...dlg.querySelectorAll('.sm-dialog-foot .sm-btn')].find((b) => b.textContent === 'Cancel').click();
  return out;
})()'''

OPEN = r'''(async (name, options) => {
  const t = SM.app.tables.find((x) => x.name === name);
  SM.app.showTab(SM.app.tabOf(t));
  const ids = ['Temp', 'Time', 'Cat'].map((n) => t.col(n).id);
  const rep = SM.app.openReport(SM.platforms.get('evaldesign'), { roles: { x: ids }, options }, t);
  await new Promise((res) => rep.on('done', res));
  return { g: await __gr.graphs(rep), undrawn: __gr.take(), errors: [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent), code: [...rep.body.querySelectorAll('details.sm-code code')].map((c) => c.textContent) };
})'''


def check_evaluate(tag, r, table_js):
    labels = [g['label'] for g in r['g']]
    check(f'{tag}: no errors, every graph drawn', (r['errors'], r['undrawn']), ([], []))
    check(f'{tag}: the graphs', labels, ['Prediction variance Temp', 'Prediction variance Time', 'Prediction variance Cat', 'Fraction of design space', 'Color map on correlations'])
    for g in r['g']:
        check(f'{tag}: {g["label"]}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
    return labels


async def run_evaluate(page, tag, r, table_js):
    check_evaluate(tag, r, table_js)
    for g in r['g']:
        lab = f'{tag}: {g["label"]}'
        F, err = await run_graph(page, g, table_js)
        check(f'{lab}: the code runs in the page', err, None)
        if not F:
            continue
        F = F[0]
        ax = F['axes'][0]
        t0 = g['traces'][0]
        check(f'{lab}: the titles and the size', (ax['title'], ax['xlabel'] or None, ax['ylabel'] or None, F['size']), (g['label'], g['titles']['x'], g['titles']['y'], [g['w'] / 100, g['h'] / 100]))
        if g['label'].startswith('Prediction variance'):
            ln = ax['lines'][0] if ax['lines'] else {'x': [], 'y': []}
            if all(isinstance(v, (int, float)) for v in t0['x']):
                check.near(f'{lab}: the curve', max(maxdiff(ln['x'], t0['x']), maxdiff(ln['y'], t0['y'])), 0, 1e-12)
            else:
                check.near(f'{lab}: the variance at each level', maxdiff(ln['y'], t0['y']), 0, 1e-12)
                check(f'{lab}: the levels on the axis, as markers', ([t for t in ax['xticklabels'] if t], ln['marker']), (t0['x'], 'o'))
        elif g['label'] == 'Fraction of design space':
            ln = ax['lines'][0] if ax['lines'] else {'x': [], 'y': []}
            check.near(f'{lab}: the curve (the same sample of the design space)', max(maxdiff(ln['x'], t0['x']), maxdiff(ln['y'], t0['y'])), 0, 1e-12)
        else:
            img = ax['images'][0] if ax['images'] else {'data': []}
            check.near(f'{lab}: the absolute correlations', maxdiff(img['data'], [v for row in t0['z'] for v in row]), 0, 1e-12)
            check(f'{lab}: the terms on both axes', ([t for t in ax['xticklabels'] if t], [t for t in ax['yticklabels'] if t]), (t0['x'], t0['y']))
            vl = [ln['x'][0] for ln in ax['lines'] if len(ln['x']) == 2 and ln['x'][0] == ln['x'][1]]
            check(f'{lab}: the dotted line before the alias terms', vl, [s['x0'] for s in g['shapes']])
            check(f'{lab}: the colour bar', F['axes'][1]['ylabel'] if len(F['axes']) > 1 else None, '|r|')


POWER = r'''(async (sit, values) => {
  let rep = SM.app.reports.find((r) => r.platform.id === 'power');
  if (!rep) { SM.app.launch('power'); rep = SM.app.reports[SM.app.reports.length - 1]; await new Promise((res) => rep.on('done', res)); }
  SM.app.showTab(SM.app.tabOf(rep));
  if (rep.spec.options.situation !== sit && !(sit === 'one_mean' && !rep.spec.options.situation)) {
    const d = new Promise((res) => rep.on('done', res));
    [...rep.body.querySelectorAll('.sm-pw-sits .sm-btn')].find((b) => b.dataset.sit === sit || b.textContent === ({ one_mean: 'One Sample Mean', two_means: 'Two Sample Means', k_means: 'k Sample Means', one_prop: 'One Sample Proportion', two_props: 'Two Sample Proportions', one_var: 'One Sample Variance', poisson: 'Counts per Unit' })[sit]).click();
    await d;
  }
  for (const [k, v] of Object.entries(values || {})) {
    const i = rep.body.querySelector(`input[data-key="${k}"]`); i.value = v; i.dispatchEvent(new Event('change'));
    for (let n = 0; n < 40; n++) await new Promise((r) => setTimeout(r, 50));
  }
  await new Promise((r) => setTimeout(r, 300));
  const g = await __gr.graphs(rep);
  return { g, undrawn: __gr.take(), errors: [...rep.body.querySelectorAll('.sm-ob-error, .sm-ob-warn')].map((e) => e.textContent),
           notes: [...rep.body.querySelectorAll('.sm-pw-results .sm-ob-note')].map((n) => n.textContent) };
})'''


async def run_tableless(page, g):
    """Run a graph's code block in the page's own Python with no table (the power curves read none)."""
    out = await page.ev(f'SM.engine.runCell("charts", {json.dumps(page_probe(g["code"]))}, {{ tables: [], current: null, label: "chart", fresh: true }})', timeout=300)
    if isinstance(out, str):
        return None, out
    return figures_from_outputs(out.get('outputs'))


async def run_power(page, sit, values):
    tag = f'Sample Size and Power, {sit}{" " + json.dumps(values) if values else ""}'
    r = await page.ev(f'({POWER})({json.dumps(sit)}, {json.dumps(values)})', timeout=300)
    if isinstance(r, str):
        check(f'{tag}: the report', r, None)
        return
    check(f'{tag}: no errors, every graph drawn, a graph for each curve', (r['errors'], r['undrawn'], len(r['g']) >= 1), ([], [], True))
    if 'null_diff' in values:
        margin = float(values['null_diff']) != 0
        check(f'{tag}: the note names the method: {"the unpooled normal approximation (Chow, Shao and Wang)" if margin else "the pooled z test"}',
              (any('Chow, Shao and Wang' in n for n in r['notes']), any('with the pooled variance under the null' in n for n in r['notes'])), (margin, not margin))
        check(f'{tag}: the graphs\' code is the {"formula" if margin else "pooled test"}\'s', all(('unpooled' in g['code']) == margin for g in r['g']), True)
    for g in r['g']:
        lab = f'{tag}: {g["label"]}'
        check(f'{lab}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
        F, err = await run_tableless(page, g)
        check(f'{lab}: the code runs in the page', err, None)
        if not F:
            continue
        F = F[0]
        ax = F['axes'][0]
        by = {ln['label']: ln for ln in ax['lines']}
        main = [t for t in g['traces'] if t.get('name') in ('Power', 'Normal approximation')][0]
        ln = by.get(main['name'], {'x': [], 'y': []})
        check.near(f'{lab}: the power along the report\'s grid', max(maxdiff(ln['x'], main['x']), maxdiff(ln['y'], main['y'])), 0, 1e-9)
        ex = [t for t in g['traces'] if t.get('name') == 'Exact']
        if ex:
            check.near(f'{lab}: the exact power', maxdiff(by.get('Exact', {'y': []})['y'], ex[0]['y']), 0, 1e-12)
            check(f'{lab}: in steps along n, the legend', (by.get('Exact', {}).get('drawstyle'), F['legend'][:2]), ('steps-post' if ex[0].get('shape') == 'hv' else 'default', ['Normal approximation', 'Exact']))
        here = [t for t in g['traces'] if t.get('name') == 'Here']
        if here:
            h = by.get('Here', {'x': [], 'y': []})
            check.near(f'{lab}: the report\'s point', maxdiff(h['x'] + h['y'], here[0]['x'] + here[0]['y']), 0, 1e-7)
        else:
            check(f'{lab}: no point', 'Here' in by, False)
        level = [x for x in ax['lines'] if x['ls'] == ':']
        check.near(f'{lab}: the line at α', level[0]['y'][0] if level else None, g['shapes'][0]['y0'], 1e-15)
        check(f'{lab}: the titles, the range and the size', (ax['title'], ax['xlabel'], ax['ylabel'], ax['ylim'], F['size']),
              (g['label'], g['titles']['x'], g['titles']['y'], [0.0, 1.02], [g['w'] / 100, g['h'] / 100]))


EVAL_SPLIT = r'''(async (name, roles, ratio) => {
  const t = SM.app.tables.find((x) => x.name === name);
  SM.app.showTab(SM.app.tabOf(t));
  const ids = Object.fromEntries(Object.entries(roles).map(([k, names]) => [k, names.map((n) => t.col(n).id)]));
  const rep = SM.app.openReport(SM.platforms.get('evaldesign'), { roles: ids, options: ratio == null ? {} : { wpRatio: ratio } }, t);
  await new Promise((res) => rep.on('done', res));
  const head = (title) => [...rep.body.querySelectorAll('.sm-ob-head')].find((x) => x.querySelector('h2, h3, h4').textContent === title);
  const rowsOf = (title) => { const h = head(title); const tb = h && h.parentElement.querySelector(':scope > .sm-ob-body table.sm-rt'); return tb ? [...tb.querySelectorAll('tr')].map((tr) => [...tr.children].map((x) => x.textContent.trim())) : null; };
  const out = { errors: [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent), notes: [...rep.body.querySelectorAll('.sm-ob-note')].map((n) => n.textContent),
    power: rowsOf('Power Analysis'), g: await __gr.graphs(rep), undrawn: __gr.take() };
  window.__evalSplit = rep;
  return out;
})'''


async def split_evaluate(page, tag, name):
    """Evaluate Design on the split plot: without the whole plots (a note), then with them (the Whole
    Plots role, and the column among the factors, as JMP takes it); every graph's code run in the page."""
    ev = await page.ev(f'({EVAL_SPLIT})({json.dumps(name)}, {{ "x": ["Oven", "Time", "Recipe"] }}, null)', timeout=300)
    check(f'{tag}: Evaluate Design without the whole plots: a note to cast them', (ev['errors'], any('cast it in the Whole Plots role' in n for n in ev['notes'])), ([], True))
    await page.ev('SM.app.closeReport(window.__evalSplit)')
    for how, roles in (('the Whole Plots role', {'x': ['Oven', 'Time', 'Recipe'], 'wp': ['Whole Plots']}), ('Whole Plots among the factors', {'x': ['Oven', 'Time', 'Recipe', 'Whole Plots']})):
        ev = await page.ev(f'({EVAL_SPLIT})({json.dumps(name)}, {json.dumps(roles)}, null)', timeout=300)
        lab = f'{tag}: Evaluate Design with {how}'
        check(f'{lab}: no errors, the split plot\'s note', (ev['errors'], any(n.startswith('A split plot: the whole plots (Whole Plots') for n in ev['notes'])), ([], True))
        head = ev['power'][0] if ev['power'] else []
        rows = {row[0]: row for row in (ev['power'] or [])[1:]}
        j = head.index('DFDen') if 'DFDen' in head else None
        num = lambda x: float(x.replace('−', '-'))
        # 24 runs, 4 whole plots of the 2 settings of Oven: the whole-plot terms (1, Oven) on 4 - 2 = 2 df, the others on 24 - 4 - 3 = 17
        check(f'{lab}: DFDen: Oven on the whole plots (2), Time and Recipe within them (17)',
              tuple(num(rows[k][j]) if j is not None and k in rows else None for k in ('Oven', 'Time', 'Recipe[a]')), (2.0, 17.0, 17.0))
        pw = {k: num(rows[k][-1]) for k in ('Oven', 'Time') if k in rows}
        check(f'{lab}: the hard-to-change factor has less power', pw.get('Oven', 1) < pw.get('Time', 0), True)
        if how == 'the Whole Plots role':
            for g in ev['g']:
                F, err = await run_graph(page, g, f'SM.app.tables.find((x) => x.name === {json.dumps(name)})')
                check(f'{lab}: {g["label"]}: the code runs in the page', err, None)
                if not F:
                    continue
                ax = F[0]['axes'][0]
                t0 = g['traces'][0]
                if g['label'].startswith('Prediction variance') or g['label'] == 'Fraction of design space':
                    ln = ax['lines'][0] if ax['lines'] else {'x': [], 'y': []}
                    check.near(f'{lab}: {g["label"]}: the GLS prediction variance, as the report\'s', maxdiff(ln['y'], t0['y']), 0, 1e-12)
        await page.ev('SM.app.closeReport(window.__evalSplit)')
    # the variance ratio: a larger one, less power for the whole-plot terms only
    ev = await page.ev(f'({EVAL_SPLIT})({json.dumps(name)}, {{ "x": ["Oven", "Time", "Recipe"], "wp": ["Whole Plots"] }}, 4)', timeout=300)
    rows = {row[0]: row for row in (ev['power'] or [])[1:]}
    check(f'{tag}: Split Plot Variance Ratio 4: the note says it', any('variance is 4 times the error' in n for n in ev['notes']), True)
    await page.ev('SM.app.closeReport(window.__evalSplit)')


async def run_split(page):
    tag = 'Full Factorial, a split plot'
    # every coefficient 0 but the intercept and Oven's; no error: each whole plot's draw alone
    sim = {'Intercept': 10, 'Oven': 2, 'Time': 0, 'Recipe[a]': 0, 'Recipe[b]': 0, 'Whole Plots σ': 3, 'Error σ': 0}
    r = await page.ev(f'({SPLIT})({json.dumps(sim)})', timeout=300)
    if isinstance(r, str):
        check(f'{tag}: the dialogs', r, None)
        return
    if r.get('error'):
        check(f'{tag}: the dialogs', r['error'], None)
        return
    check(f'{tag}: the factors have a Changes column', r['heads'], ['Name', 'Role', 'Changes', 'Values', ''])
    check(f'{tag}: before a factor is hard to change: the full factorial\'s runs, no whole plots', r['before'], ['Number of runs: 12 (12 combinations).', True])
    check(f'{tag}: Oven hard to change: the whole plots (each setting twice by default), no blocks',
          r['after'], ['Number of runs: 24 (a split plot: 4 whole plots of 6 runs, each of the 2 settings of the hard-to-change factors in 2).', False, '4', True])
    check(f'{tag}: 6 whole plots', r['six'], 'Number of runs: 36 (a split plot: 6 whole plots of 6 runs, each of the 2 settings of the hard-to-change factors in 3).')
    check(f'{tag}: the table', (r['rows'], r['cols'][:6]), (24, ['Pattern', 'Oven', 'Time', 'Recipe', 'Whole Plots', 'Y']))
    check(f'{tag}: the table\'s Model script: Fit Model, Whole Plots random', r['scripts0'], [['Model', 'fitmodel', ['Whole Plots']]])
    labels = r['fields']
    check(f'{tag}: Simulate Responses asks for the intercept, each term\'s coefficients and the σ\'s',
          (labels[:6], labels[-2:]), (['Intercept', 'Oven', 'Time', 'Recipe[a]', 'Recipe[b]', 'Oven*Time'], ['Whole Plots σ', 'Error σ']))
    sm_ = r['sim']
    check(f'{tag}: the simulated column: Y Simulated, a formula', (sm_['name'], bool(sm_['formula'])), ('Y Simulated', True))
    d = r['data']
    vals = sm_['values']
    base = [10 + 2 * (o - 175) / 25 for o in d['Oven']]
    wp_draw = {}
    ok = True
    for w, v, b in zip(d['Whole Plots'], vals, base):
        z = v - b
        if w in wp_draw and abs(wp_draw[w] - z) > 1e-9:
            ok = False
        wp_draw.setdefault(w, z)
    check(f'{tag}: the simulated values: the model\'s part, plus one draw for each whole plot shared by its runs', ok, True)
    draws = list(wp_draw.values())
    check(f'{tag}: the whole plots\' draws differ', len({round(x, 9) for x in draws}), 4)
    check(f'{tag}: the table\'s scripts: the Model and the simulated one', r['scripts'], [['Model', ['Y']], ['Model (Simulated)', ['Y Simulated']]])
    want = ['Oven', 'Time', 'Recipe', 'Oven*Time', 'Oven*Recipe', 'Time*Recipe', 'Oven*Time*Recipe', 'Whole Plots&Random']
    for script, y in (('Model', 'Y'), ('Model (Simulated)', 'Y Simulated')):
        sc = await page.ev(f'({SCRIPT})({json.dumps(r["name"])}, {json.dumps(script)})', timeout=120)
        check(f'{tag}: the Table panel\'s {script} script opens Fit Model with the design\'s model', sc if isinstance(sc, str) or sc.get('error') else (sc['y'], sc['effects']), (y, want))
    await split_evaluate(page, tag, r['name'])
    # again, with an error: Fit Model's Recall has the design's model, and REML tests it
    r = await page.ev(f'({SPLIT})({json.dumps({**sim, "Time": 1, "Error σ": 1})})', timeout=300)
    if isinstance(r, str) or r.get('error'):
        check(f'{tag}: the second design', r if isinstance(r, str) else r['error'], None)
        return
    f = await page.ev(f'({RECALL})({json.dumps(r["name"])})', timeout=300)
    check(f'{tag}: Fit Model\'s Recall opens the design\'s model', (f['y'], f['effects']), ('Y Simulated', want))
    check(f'{tag}: its report (REML), without errors', (f['errors'], bool(f['vc']), bool(f['tests'])), ([], True, True))
    if f['tests']:
        rows = {row[0]: row for row in f['tests'][1:]}
        head = f['tests'][0]
        j = head.index('DFDen') if 'DFDen' in head else None
        num = lambda x: float(str(x).replace('−', '-')) if x not in (None, '', '.', '∞') else x
        got = tuple(num(rows.get(k, [None] * 9)[j]) if j is not None else None for k in ('Oven', 'Time'))
        # 24 runs, 12 fixed parameters, 4 whole plots of 2 settings: 2 df between whole plots, 24 - 12 - 2 = 10 within
        check(f'{tag}: Oven is tested on the whole plots (4 - 2 = 2 df), Time within them (10 df)', got, (2.0, 10.0))
    b = await page.ev(BLOCKS, timeout=300)
    check('Full Factorial, replicates as blocks: offered only with replicates, the runs, the Block column and the model',
          b if isinstance(b, str) else (b['none'], b['one'], b['runs'], b['rows'], 'Block' in b['cols'], b['scripts']),
          (True, False, 'Number of runs: 24 (2 blocks of the 12 combinations).', 24, True, [['Model', ['Block']]]))
    # the dialog at phone width
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 2, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.5)
    ph = await page.ev(PHONE, timeout=60)
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await asyncio.sleep(0.3)
    check(f'{tag}: the dialog at phone width: no page scroll, the sections inside it, the Changes column there', ph, {'page': True, 'dialog': True, 'inside': True, 'changes': True})


async def main():
    page = await open_page(f'{BASE}/smui.html', width=1500, height=1000)
    check('engine ready', await wait_engine(page), 'ready')
    await page.ev(GRAPHS_JS)
    d = await page.ev(MAKE_DESIGN, timeout=300)
    check('the Full Factorial dialog makes the design table', (d['rows'], [c[0] for c in d['cols']]), (15, ['Pattern', 'Temp', 'Time', 'Cat', 'Y']))
    table_js = f"SM.app.tables.find((x) => x.name === {json.dumps(d['name'])})"
    await page.ev(f'{table_js}.setState([3], "excluded", true)')
    r = await page.ev(f'({OPEN})({json.dumps(d["name"])}, {{ "model": "2fi" }})', timeout=300)
    check('Evaluate Design (2FI): the Design Diagnostics\' code drops the excluded row', any('df = df.drop(index=[3])' in c and 'd_efficiency' in c for c in r['code']), True)
    await run_evaluate(page, 'Evaluate Design (two-factor interactions, a row excluded)', r, table_js)
    r = await page.ev(f'({OPEN})({json.dumps(d["name"])}, {{ "model": "main", "powerSettings": {{ "alpha": 0.1, "rmse": 2, "coefficient": 1.5 }} }})', timeout=300)
    await run_evaluate(page, 'Evaluate Design (main effects, power settings)', r, table_js)
    await page.ev(f'{table_js}.setState([3], "excluded", false)')
    for sit, values in (('one_mean', {}), ('one_mean', {'power': '', 'n': '34'}), ('one_mean', {'n': '40', 'diff': '', 'power': '0.9'}),
                        ('two_means', {}), ('k_means', {}), ('one_prop', {}), ('one_prop', {'n': '150', 'p1': ''}),
                        ('two_props', {}), ('two_props', {'null_diff': '0.05'}), ('two_props', {'null_diff': '-0.05', 'n': '300', 'power': ''}),
                        ('two_props', {'null_diff': '0', 'power': '0.8', 'n': ''}), ('one_var', {}), ('one_var', {'dvar': '-0.4', 'n': '30', 'power': ''}), ('poisson', {}), ('poisson', {'n': '40', 'power': ''})):
        await run_power(page, sit, values)
    await run_split(page)
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
