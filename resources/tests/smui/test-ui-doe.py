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
alpha. The rest of DOE's browser checks are in test-ui-quality.py.

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
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
