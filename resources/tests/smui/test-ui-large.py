#!/usr/bin/env python3
"""smui.html in a real browser: the platforms on tables of 300,000 rows.

An array spread into one call (Math.min(...values), rows.push(...more))
runs past the stack at some 125,000 values. Where a platform did that with
a table's values or rows, a big table failed: "Maximum call stack size
exceeded" in the report, or nothing at all where a click spread them. Each
check here failed so once:

- Distribution's Normal Quantile Plot (the range of every value's quantile);
- the Control Chart of individuals (each limit's and value's range);
- Life Distribution (the probability plot's and the CDF's ranges);
- Process Capability's box plots (every value, scaled);
- Fit Model's Influence Plot (each row's Cook's D);
- Discriminant's scores (each row's -log probability);
- the Variability Chart's S control limits (one for each cell);
- a click on a Partition or an Uplift tree's node (the rows of its leaves);
- a selection in the Bubble Plot (the rows of each bubble picked);
- Text Analysis's Sentiment Analysis with an ID (the rows of a document);
- a paste of 130,000 lines into a table of three rows (the rows added, and
  the widest line, for the toast).

Start a server on the repository root and headless Chrome (the recipe is in
../rb/README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT (defaults 8791, 9291),
then

    python3 resources/tests/smui/test-ui-large.py

Sentiment Analysis fetches vaderSentiment from PyPI, as test-ui-text.py
does. Exit status 0 when every check passes.
"""
import asyncio
import json
import sys

from cdp import BASE, Checks, open_page, wait_engine

check = Checks()

# Three tables made in the page: Big (300,000 rows: x, y normal, g by x,
# t > 0, c a censor code, w the treatment, id two bubbles, txt), Parts
# (300,000 measurements of 150,000 parts), Texts (130,000 rows of one ID,
# a text on every thousandth: one document of 130,000 rows, short to score)
# and Small (three rows, to paste into).
MAKE = r"""(() => {
  let s = 12345;
  const rnd = () => { s = (s * 1103515245 + 12345) % 2147483648; return (s + 0.5) / 2147483648; };
  const norm = () => Math.sqrt(-2 * Math.log(rnd())) * Math.cos(2 * Math.PI * rnd());
  const words = ['good service', 'bad app', 'slow phone line', 'great web shop', 'friendly staff', 'long wait'];
  const n = 300000, x = [], y = [], g = [], t = [], c = [], w = [], id = [];
  for (let i = 0; i < n; i++) {
    const a = norm();
    x.push(a); y.push(0.5 * a + norm()); g.push(a > 0.3 ? 'hi' : 'lo');
    t.push(Math.exp(1 + 0.5 * norm())); c.push(rnd() < 0.2 ? 1 : 0);
    w.push(rnd() < 0.5 ? 'treat' : 'control'); id.push(i % 2 ? 'q' : 'p');
  }
  SM.app.addTable(new SM.Table({ name: 'Big', columns: [
    { name: 'x', dataType: 'numeric', values: x }, { name: 'y', dataType: 'numeric', values: y },
    { name: 'g', dataType: 'character', values: g }, { name: 't', dataType: 'numeric', values: t },
    { name: 'c', dataType: 'numeric', values: c }, { name: 'w', dataType: 'character', values: w },
    { name: 'id', dataType: 'character', values: id }] }));
  const part = [], m = [];
  for (let i = 0; i < n; i++) { part.push(i >> 1); m.push(norm()); }
  SM.app.addTable(new SM.Table({ name: 'Parts', columns: [{ name: 'part', dataType: 'numeric', modelingType: 'nominal', values: part },
    { name: 'y', dataType: 'numeric', values: m }] }));
  const k = 130000, txt = [], one = [];
  for (let i = 0; i < k; i++) { txt.push(i % 1000 ? '' : words[Math.floor(rnd() * words.length)]); one.push('one'); }
  SM.app.addTable(new SM.Table({ name: 'Texts', columns: [{ name: 'txt', dataType: 'character', values: txt }, { name: 'id', dataType: 'character', values: one }] }));
  SM.app.addTable(new SM.Table({ name: 'Small', columns: [{ name: 'a', dataType: 'numeric', values: [1, 2, 3] }, { name: 'b', dataType: 'character', values: ['x', 'y', 'z'] }] }));
  return SM.app.tables.map((t) => t.nrows);
})()"""

# Open a report on a table (Fit Model's effects as lists of column names),
# wait for it, run `after` (a function of the report and the table, as text)
# and close the report.
RUN = r"""(async (tname, platform, roles, options, after, effects) => {
  const t = SM.app.tables.find((x) => x.name === tname);
  SM.app.showTable(t.id);
  const ids = {};
  for (const [k, names] of Object.entries(roles)) ids[k] = names.map((n) => t.col(n).id);
  for (const [k, v] of Object.entries(options)) if (k.startsWith('COL:')) { delete options[k]; options[t.col(k.slice(4).split('|')[0]).id + '|' + k.split('|')[1]] = v; }
  const spec = { roles: ids, options };
  if (effects) spec.effects = effects.map((names) => ({ cols: names.map((n) => t.col(n).id), names, nest: [], nestNames: [], random: false }));
  const rep = SM.app.openReport(SM.platforms.get(platform), spec, t);
  await new Promise((res) => rep.on('done', res));
  const out = { outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map((h) => h.textContent),
    errors: [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent.slice(0, 300)), plots: rep.plots.length };
  if (after) { try { out.after = await (eval(after))(rep, t); } catch (e) { out.after = `${e.name}: ${e.message}`; } }
  SM.app.closeReport(rep);
  return out;
})"""

# A click on the tree's first node, the root: all its rows selected.
CLICK_ROOT = r"""(async (rep, t) => {
  const g = rep.body.querySelector('g.sm-part-node');
  if (!g) return 'no node';
  t.select([], 'replace');
  g.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  await new Promise((r) => setTimeout(r, 300));
  return t.selectedRows().length;
})"""

# Both bubbles picked by a box or lasso selection: every row selected.
SELECT_BUBBLES = r"""(async (rep, t) => {
  for (let k = 0; k < 50 && !rep.plots.some((p) => p.box && p.box.emit); k++) await new Promise((r) => setTimeout(r, 100));
  const p = rep.plots.find((p) => p.box && p.box.emit);
  if (!p) return 'no drawn plot';
  t.select([], 'replace');
  p.box.emit('plotly_selected', { points: [{ curveNumber: 0, pointNumber: 0 }, { curveNumber: 0, pointNumber: 1 }] });
  await new Promise((r) => setTimeout(r, 300));
  return t.selectedRows().length;
})"""

# 130,000 lines pasted at a's first cell, as ctrl/⌘+V pastes them: the table
# grows to 130,000 rows, b's new cells missing.
PASTE = r"""(async () => {
  const t = SM.app.tables.find((x) => x.name === 'Small');
  SM.app.showTable(t.id);
  const g = SM.app.grids.get(t.id);
  g.cursor = { row: 0, col: 0 };
  const text = Array.from({ length: 130000 }, (_, i) => `${i / 2}`).join('\n');
  try { g._paste({ clipboardData: { getData: () => text }, preventDefault() {} }); } catch (e) { return `${e.name}: ${e.message}`; }
  const toast = document.querySelector('.sm-toast');
  const a = t.col('a').values, b = t.col('b').values;
  return [toast ? toast.textContent : null, t.nrows, a.length, a[0], a[129999], b.slice(0, 4), b.length, t.state.length];
})()"""


async def main():
    page = await open_page(f'{BASE}/smui.html')
    for _ in range(120):
        if await page.ev('!!(window.SM && SM.app && SM.Table && SM.platforms)'):
            break
        await asyncio.sleep(0.5)
    check('the engine starts', await wait_engine(page), 'ready')
    sizes = await page.ev(MAKE, timeout=300)

    async def run(tname, platform, roles, options=None, after=None, effects=None):
        page.errors.clear()
        return await page.ev(f'({RUN})({json.dumps(tname)}, {json.dumps(platform)}, {json.dumps(roles)}, {json.dumps(options or {})}, '
                             f'{json.dumps(after)}, {json.dumps(effects)})', timeout=600)

    check('the tables: 300,000, 300,000, 130,000 and 3 rows', sizes[-4:], [300000, 300000, 130000, 3])

    r = await run('Big', 'distribution', {'y': ['x']}, {'qq': True})
    check('Distribution: the Normal Quantile Plot of 300,000 values', (r['errors'], 'Normal Quantile Plot' in r['outlines']), ([], True))

    r = await run('Big', 'controlchart', {'y': ['x']}, {'subgroupSize': 1})
    check('Control Chart: individuals and moving ranges of 300,000 values, drawn', (r['errors'], r['plots'] > 0), ([], True))

    r = await run('Big', 'lifedist', {'y': ['t'], 'censor': ['c']}, {'censorCode': '1'})
    check('Life Distribution of 300,000 times: the probability plot and the CDFs drawn', (r['errors'], r['plots'] > 0), ([], True))

    r = await run('Big', 'capability', {'y': ['x']}, {'specs': {'x': {'lsl': -3, 'target': 0, 'usl': 3}}})
    check('Process Capability of 300,000 values: its box plots', (r['errors'], 'Capability Box Plots' in r['outlines']), ([], True))

    r = await run('Big', 'fitmodel', {'y': ['y']}, {'personality': 'standard', 'influence': True}, effects=[['x']])
    check('Fit Model of 300,000 rows: its Influence Plot', (r['errors'], 'Influence Plot' in r['outlines']), ([], True))

    r = await run('Big', 'discriminant', {'y': ['x', 'y'], 'x': ['g']})
    check('Discriminant of 300,000 rows: its scores', (r['errors'], 'Discriminant Scores' in r['outlines']), ([], True))

    r = await run('Parts', 'variability', {'y': ['y'], 'x': ['part']}, {'sLimits': True})
    check('Variability Chart of 150,000 parts with its S control limits', (r['errors'], r['plots'] > 0), ([], True))

    r = await run('Big', 'partition', {'y': ['g'], 'x': ['x', 'y']}, {}, CLICK_ROOT)
    check('Partition: a click on the root selects its 300,000 rows', (r['errors'], r['after'], page.errors[:1]), ([], 300000, []))

    r = await run('Big', 'uplift', {'y': ['y'], 'treatment': ['w'], 'x': ['x']}, {}, CLICK_ROOT)
    check('Uplift: a click on the root selects its 300,000 rows', (r['errors'], r['after'], page.errors[:1]), ([], 300000, []))

    r = await run('Big', 'bubble', {'y': ['y'], 'x': ['x'], 'id': ['id']}, {}, SELECT_BUBBLES)
    check('Bubble Plot: both bubbles selected, their 300,000 rows', (r['errors'], r['after'], page.errors[:1]), ([], 300000, []))

    r = await run('Texts', 'text', {'text': ['txt'], 'id': ['id']}, {'COL:txt|sentiment': True})
    check('Text Analysis: Sentiment Analysis of a document of 130,000 rows', (r['errors'], 'Sentiment Analysis' in r['outlines']), ([], True))

    page.errors.clear()
    check('a paste of 130,000 lines into a table of three rows: the rows added, the values in place, the toast that says so',
          (await page.ev(PASTE, timeout=300), page.errors[:1]),
          (['Pasted 130000 × 1 cells at row 1', 130000, 130000, 0, 64999.5, ['x', 'y', 'z', None], 130000, 130000], []))

    await page.close()
    return check.done()


sys.exit(asyncio.run(main()))
