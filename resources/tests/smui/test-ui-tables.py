#!/usr/bin/env python3
"""smui.html in a real browser: the Tables menu, Analyze > Tabulate,
formulas, the Cols utilities, the Columns Viewer, Explore Missing Values and
the Python Script window.

Each command runs through its dialog as a user would: columns cast into
roles, options set, OK. The results are checked against numbers computed in
the page from the table itself: group means and JMP's quantiles for
Summary, the rows of Subset and Sort, Stack and Split back again, Join and
Update, the patterns of missing values; the Summary and Missing Data
Pattern tables are linked to their source; Tabulate is built by dragging
columns into its drop zones and with the buttons; the formula editor
previews, refuses a wrong formula and makes a live formula column; the
column menu's New Formula Column submenu and Recode make their columns;
Edit > Undo takes back what changed a table in place; the Python script
runs only on Run and its result becomes a table; everything draws in the
dark theme and at phone width without a script error.

And (wp5): the column properties typed in Column Info (Missing Value
Codes missing to the grid, a formula, the engine, Distribution and its
code run on the CSV; Value Labels in the grid and the report; a Profit
Matrix with Undecided; Undo, Save Table, a project; Cols > Column
Properties), Cols > Preselect Role filling a launch dialog, New Column
adding several, a launch dialog's right click making a transform column
and casting it, Keep dialog open, New Formula Column's Date Time items,
Lag Multiple, Moving Average and Scale Offset, Subset's equal counts per
level with probabilities and weights, Recode's Group and Group Similar
Values by edit distance, the grid's Fill (a real right click) and Header
Graphs (a real click), Tabulate's bins, levels and Show Chart, Missing
Value Clustering (its code run in the page) with the SVD and shrunk
imputations, and File > Import Multiple Files.

Start a server on the repository root and headless Chrome on SMUI_HTTP_PORT
and SMUI_CDP_PORT (see README.md), then

    python3 resources/tests/smui/test-ui-tables.py

SMUI_SHOTS=<folder> saves screenshots. Exit status 0 when every check passes.
"""
import asyncio
import json
import os
import sys

from cdp import BASE, Checks, open_page, wait_engine
from test_charts import GRAPHS_JS, points_of, run_graph

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()

HELPERS = r'''
window.T = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  async until(fn, ms = 30000) { const t0 = Date.now(); for (;;) { let v = null; try { v = fn(); } catch (e) { v = null; } if (v) return v; if (Date.now() - t0 > ms) throw new Error('timed out'); await T.sleep(40); } },
  dlg: () => [...document.querySelectorAll('.sm-dialog')].pop() || null,
  button: (root, text) => [...root.querySelectorAll('button')].find((b) => b.textContent.trim() === text) || null,
  pick(dlg, names) {
    const items = [...dlg.querySelectorAll('.sm-pick-list li')];
    names.forEach((n, i) => { const li = items.find((x) => x.textContent === n); if (!li) throw new Error('no column ' + n); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, metaKey: i > 0 })); });
  },
  role(dlg, label) { const b = [...dlg.querySelectorAll('.sm-role .sm-btn')].find((x) => x.textContent === label); if (!b) throw new Error('no role ' + label); b.click(); },
  cast(dlg, names, label) { T.pick(dlg, names); T.role(dlg, label); },
  opt(dlg, label) { const l = [...dlg.querySelectorAll('.sm-launch-opts label, .sm-form label, .smt-form label')].find((x) => x.textContent.trim().startsWith(label)); if (!l) throw new Error('no option ' + label); return l.querySelector('input, select') || document.getElementById(l.htmlFor); },
  set(input, v) { if (input.type === 'checkbox') input.checked = !!v; else input.value = v; input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true })); },
  ok(dlg, text = 'OK') { const b = T.button(dlg.querySelector('.sm-actions') || dlg, text) || T.button(dlg, text); if (!b) throw new Error('no ' + text); b.click(); },
  cmd(menu, label, ...args) { const c = SM.commands.all().find((x) => x.menu === menu && x.label === label); if (!c) throw new Error('no command ' + label); return c.action(SM.app, ...args); },
  last: () => SM.app.tables[SM.app.tables.length - 1],
  async newTable(n0) { await T.until(() => SM.app.tables.length > n0); return T.last(); },
  drop(target, ids) {
    const dt = new DataTransfer();
    dt.setData(SM.launch.MIME, JSON.stringify(ids));
    const over = new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt });
    target.dispatchEvent(over);
    target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
    return over.defaultPrevented;
  },
  // (no unsubscribing: a report's off() is its list of table listeners)
  done: (rep) => new Promise((res) => { rep.on('done', res); }),
  weibull(v, p) { const s = v.filter(Number.isFinite).sort((a, b) => a - b); const n = s.length; const h = (n + 1) * p; if (h <= 1) return s[0]; if (h >= n) return s[n - 1]; const k = Math.floor(h); return s[k - 1] + (h - k) * (s[k] - s[k - 1]); },
  mean: (v) => { const s = v.filter(Number.isFinite); return s.reduce((a, b) => a + b, 0) / s.length; },
  near: (a, b, tol = 1e-9) => Math.abs(a - b) <= tol * Math.max(1, Math.abs(b)),
  menuButton(label) { return [...document.querySelectorAll('.sm-menu button')].find((b) => b.querySelector('.sm-label') && b.querySelector('.sm-label').textContent === label) || null; },
  // The (i) panel as it reads: its title, its section headings and the choices under each ([name, text]).
  info() {
    const p = document.querySelector('.info-panel'); if (!p) return null;
    const out = { title: p.querySelector('.info-panel-title').textContent, heads: [], choices: {} };
    let head = '';
    for (const n of p.querySelector('.info-panel-body').children) {
      if (n.tagName === 'H3') { head = n.textContent; out.heads.push(head); }
      else if (n.matches('dl.info-choices')) { const dd = [...n.querySelectorAll('dd')]; out.choices[head] = [...n.querySelectorAll('dt')].map((dt, i) => [dt.textContent, dd[i] ? dd[i].textContent : '']); }
    }
    return out;
  },
  async infoOf(root) { const b = root && root.querySelector('.info-btn'); if (!b) return null; b.click(); await T.sleep(60); const r = T.info(); r.audit = KvotInfo.audit().noTopic; KvotInfo.close(); return r; },
  names: (info, head) => ((info && info.choices[head]) || []).map((c) => c[0]),
  // entries whose explanation is missing or only says what a role takes
  thin: (info, heads) => heads.flatMap((h) => ((info && info.choices[h]) || []).filter((c) => c[1].startsWith('(') || c[1].length < 30).map((c) => `${h}: ${c[0]}`)),
};
'''


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


async def js(page, body, label=None):
    """Run an async function body in the page; an exception fails the check."""
    r = await page.ev(f'(async () => {{ {body} }})()', timeout=180)
    if isinstance(r, str) and r.startswith('EXCEPTION'):
        check(label or 'page code ran', r, None)
        return None
    return r


async def main():
    page = await open_page(f'{BASE}/smui.html?example=students')
    check('engine ready', await wait_engine(page), 'ready')
    await page.ev(HELPERS)
    check('no script errors at load', page.errors, [])
    failed = await page.ev('SM.engine.failed.filter(f => f.error !== "not written yet").map(f => f.module + ": " + f.error)')
    check('tables.py imports in the engine', [f for f in failed if f.startswith('tables')], [])
    menus = await page.ev('JSON.stringify(["Tables", "Cols", "Analyze", "File", "Python"].map(m => SM.app.menuItems(m).map(i => i.label || "—")))')
    tables, cols, analyze, filem, pythonm = json.loads(menus)
    check('the Tables menu', tables, ['Summary…', 'Subset…', 'Sort…', 'Stack…', 'Split…', 'Transpose…', 'Concatenate…', 'Join…', 'Update…', '—', 'Missing Data Pattern…'])
    check('the Cols menu has Formula, New Formula Column, Recode, Columns Viewer and Utilities', [c for c in cols if c in ('Formula…', 'New Formula Column', 'Recode…', 'Columns Viewer', 'Utilities')], ['Formula…', 'New Formula Column', 'Recode…', 'Columns Viewer', 'Utilities'])
    check('Analyze has Tabulate after Distribution', analyze.index('Tabulate') > analyze.index('Distribution…'), True)
    check('Python has Script…, after the notebooks; File has it no more',
          (pythonm[:4], 'Python Script…' in filem), (['New Notebook', 'Open Notebook…', 'Report Script in Notebook', 'Script…'], False))

    # ---- Summary through its dialog, linked to the source ----------------------------------------------
    r = await js(page, r'''
      const t = SM.app.current; const n0 = SM.app.tables.length;
      T.cmd('Tables', 'Summary…');
      const d = T.dlg();
      T.cast(d, ['height (cm)', 'weight (kg)'], 'Statistics Columns');
      T.cast(d, ['sex'], 'Group');
      const grid = d.querySelector('.smt-statgrid');
      for (const lab of grid.querySelectorAll('label')) { const s = lab.textContent.trim(); const cb = lab.querySelector('input'); if (['N', 'Median', 'Quantiles'].includes(s) && !cb.checked) { cb.checked = true; cb.dispatchEvent(new Event('change')); } }
      T.set(T.opt(d, 'Quantiles (%)'), '10, 90');
      T.ok(d);
      const s = await T.newTable(n0);
      const cols = s.columns.map((c) => c.name);
      const h = t.col('height (cm)').values, sx = t.col('sex').values;
      const lv = t.levels('sex');
      const want = lv.map((L) => T.mean(h.filter((v, i) => sx[i] === L)));
      const got = s.col('Mean(height (cm))').values;
      const med = lv.map((L) => T.weibull(h.filter((v, i) => sx[i] === L), 0.5));
      const q90 = lv.map((L) => T.weibull(h.filter((v, i) => sx[i] === L), 0.9));
      // linking: select the second summary row
      s.select([1]);
      const selected = t.selectedRows();
      const wantRows = sx.map((v, i) => (v === lv[1] ? i : -1)).filter((i) => i >= 0);
      t.select([]);
      return { name: s.name, cols, levels: s.col('sex').values, nrows: s.col('N Rows').values, meanOk: got.every((v, i) => T.near(v, want[i])), medOk: s.col('Median(height (cm))').values.every((v, i) => T.near(v, med[i])),
        q90Ok: s.col('Quantiles90(height (cm))').values.every((v, i) => T.near(v, q90[i])), linked: JSON.stringify(selected) === JSON.stringify(wantRows), nsel: selected.length, sexType: s.col('sex').modelingType };
    ''', 'Summary')
    if r:
        check('Summary makes a table named by its groups', r['name'], 'Students By (sex)')
        check('Summary columns', r['cols'], ['sex', 'N Rows', 'N(height (cm))', 'Mean(height (cm))', 'Median(height (cm))', 'Quantiles10(height (cm))', 'Quantiles90(height (cm))', 'N(weight (kg))', 'Mean(weight (kg))', 'Median(weight (kg))', 'Quantiles10(weight (kg))', 'Quantiles90(weight (kg))'])
        check('a row per level of sex, in value order', r['levels'], ['F', 'M'])
        check('N Rows add up to the table', sum(r['nrows']), 60)
        check('the group means equal the page\'s own', r['meanOk'], True)
        check('the medians and the 90% quantiles are JMP\'s (weibull)', (r['medOk'], r['q90Ok']), (True, True))
        check('selecting a summary row selects its rows in the source', r['linked'], True)
        check('the group column keeps its modeling type', r['sexType'], 'nominal')
    await shot(page, 't01-summary.png')

    # ---- Subset: selected rows, a seeded random sample, stratified -------------------------------------
    r = await js(page, r'''
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      t.select([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
      let n0 = SM.app.tables.length;
      T.cmd('Tables', 'Subset…'); let d = T.dlg(); T.ok(d);
      const a = await T.newTable(n0);
      const aIds = a.col('id').values.slice();
      const lab = a.columns.find((c) => c.role === 'label');
      t.select([]);
      const sampleOf = async (seed, stratify) => {
        SM.app.showTab(SM.app.tabOf(t));
        const n = SM.app.tables.length;
        T.cmd('Tables', 'Subset…'); const dd = T.dlg();
        if (stratify) T.cast(dd, ['sex'], 'Stratify');
        T.set(T.opt(dd, 'Rows'), stratify ? 'rate' : 'size'); T.set(T.opt(dd, 'Sample size'), '12'); T.set(T.opt(dd, 'Sampling rate'), '0.5'); T.set(T.opt(dd, 'Seed'), seed);
        T.ok(dd);
        const x = await T.newTable(n);
        return x;
      };
      const s1 = await sampleOf('42'), s2 = await sampleOf('42'), s3 = await sampleOf('43');
      const st = await sampleOf('7', true);
      const sx = t.col('sex').values;
      const nF = sx.filter((v) => v === 'F').length, nM = sx.filter((v) => v === 'M').length;
      return { aRows: a.nrows, aIds, label: lab ? lab.name : null, s1: s1.col('id').values, s2: s2.col('id').values, s3: s3.col('id').values, strat: st.nrows, wantStrat: Math.round(nF / 2) + Math.round(nM / 2),
        stratF: st.col('sex').values.filter((v) => v === 'F').length, wantF: Math.round(nF / 2), ordered: s1.col('id').values.every((v, i, arr) => i === 0 || arr[i - 1] < v) };
    ''', 'Subset')
    if r:
        check('Subset of the selected rows', (r['aRows'], r['aIds'][:3]), (10, ['S01', 'S02', 'S03']))
        check('the subset keeps the label column', r['label'], 'id')
        check('a random sample of 12', len(r['s1']), 12)
        check('the same seed draws the same rows', r['s1'], r['s2'])
        check('another seed other rows', r['s1'] != r['s3'], True)
        check('the sample keeps the table\'s order', r['ordered'], True)
        check('a stratified sample takes half of each level', (r['strat'], r['stratF']), (r['wantStrat'], r['wantF']))

    # ---- Sort: two columns, one descending; a new table, and in place with Undo ----------------------------
    r = await js(page, r'''
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      const n0 = SM.app.tables.length;
      T.cmd('Tables', 'Sort…'); const d = T.dlg();
      T.cast(d, ['sex', 'height (cm)'], 'By');
      await T.sleep(60);
      const arrows = [...d.querySelectorAll('.smt-dir')];
      arrows[1].click();
      const pressed = arrows.map((b) => b.getAttribute('aria-pressed'));
      T.ok(d);
      const s = await T.newTable(n0);
      const sx = s.col('sex').values, h = s.col('height (cm)').values;
      let ok = true;
      for (let i = 1; i < s.nrows; i++) { if (sx[i - 1] === sx[i] && h[i - 1] < h[i]) ok = false; if (sx[i - 1] === 'M' && sx[i] === 'F') ok = false; }
      // in place, then Undo
      SM.app.showTab(SM.app.tabOf(t));
      const before = t.col('id').values.slice();
      T.cmd('Tables', 'Sort…'); const d2 = T.dlg();
      T.cast(d2, ['weight (kg)'], 'By');
      T.set(T.opt(d2, 'Replace table'), true);
      T.ok(d2);
      await T.sleep(50);
      const w = t.col('weight (kg)').values;
      const sorted = w.every((v, i) => i === 0 || w[i - 1] <= v);
      SM.app.undo();
      const back = JSON.stringify(t.col('id').values) === JSON.stringify(before);
      return { arrows: arrows.length, pressed, ok, first: sx[0], rows: s.nrows, sorted, back, tables: SM.app.tables.length - n0 };
    ''', 'Sort')
    if r:
        check('the Sort dialog has an arrow beside each By column', (r['arrows'], r['pressed']), (2, ['false', 'true']))
        check('sorted by sex, then height descending', (r['ok'], r['first'], r['rows']), (True, 'F', 60))
        check('Replace table sorts the table itself', (r['sorted'], r['tables']), (True, 1))
        check('Edit > Undo takes the sort back', r['back'], True)

    # ---- Stack, and Split back again --------------------------------------------------------------------------
    r = await js(page, r'''
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      let n0 = SM.app.tables.length;
      T.cmd('Tables', 'Stack…'); let d = T.dlg();
      T.cast(d, ['height (cm)', 'weight (kg)'], 'Stack Columns');
      T.ok(d);
      const st = await T.newTable(n0);
      const cols = st.columns.map((c) => c.name);
      const lab = st.col('Label');
      const okData = st.col('Data').values.every((v, i) => v === t.col(lab.values[i]).values[st.col('ID').values[i] - 1]);
      SM.app.showTab(SM.app.tabOf(st));
      n0 = SM.app.tables.length;
      T.cmd('Tables', 'Split…'); d = T.dlg();
      T.cast(d, ['Data'], 'Split Columns'); T.cast(d, ['Label'], 'Split By'); T.cast(d, ['ID'], 'Group');
      T.ok(d);
      const sp = await T.newTable(n0);
      const same = ['height (cm)', 'weight (kg)'].every((nm) => JSON.stringify(sp.col(nm).values) === JSON.stringify(t.col(nm).values));
      return { rows: st.nrows, cols, label: [lab.modelingType, lab.valueOrder], okData, splitCols: sp.columns.map((c) => c.name), same, splitRows: sp.nrows };
    ''', 'Stack and Split')
    if r:
        check('Stack: a row per value', r['rows'], 120)
        check('Stack keeps the other columns, then ID, Label and Data', r['cols'], ['id', 'age', 'sex', 'ID', 'Label', 'Data'])
        check('the Label column is nominal, in the stacked columns\' order', r['label'], ['nominal', ['height (cm)', 'weight (kg)']])
        check('each Data value is its column\'s value in its row', r['okData'], True)
        check('Split undoes Stack', (r['splitCols'], r['splitRows'], r['same']), (['ID', 'height (cm)', 'weight (kg)'], 60, True))

    # ---- Transpose, Concatenate ----------------------------------------------------------------------------
    r = await js(page, r'''
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      t.select([0, 1, 2]);
      let n0 = SM.app.tables.length;
      T.cmd('Tables', 'Transpose…'); let d = T.dlg();
      T.cast(d, ['height (cm)', 'weight (kg)'], 'Transpose Columns'); T.cast(d, ['id'], 'Label');
      T.set(T.opt(d, 'Transpose selected rows only'), true);
      T.ok(d);
      const tr = await T.newTable(n0);
      t.select([]);
      const trCols = tr.columns.map((c) => c.name);
      const okT = tr.col('S02').values[0] === t.col('height (cm)').values[1] && tr.col('S03').values[1] === t.col('weight (kg)').values[2];
      SM.app.showTab(SM.app.tabOf(t));
      n0 = SM.app.tables.length;
      T.cmd('Tables', 'Concatenate…'); d = T.dlg();
      const boxes = [...d.querySelectorAll('.smt-tablelist input')];
      boxes.forEach((b, i) => { b.checked = i === 0 || i === 1; });
      T.set(T.opt(d, 'Create source column'), true);
      T.ok(d);
      const ct = await T.newTable(n0);
      const second = SM.app.tables.filter((x) => x !== t)[0];
      return { trCols, okT, rows: ct.nrows, want: t.nrows + second.nrows, src: ct.col('Source Table').values[ct.nrows - 1], second: second.name, cols: ct.columns.length };
    ''', 'Transpose and Concatenate')
    if r:
        check('Transpose: the Label column\'s values name the columns', r['trCols'], ['Label', 'S01', 'S02', 'S03'])
        check('Transpose puts rows into columns', r['okT'], True)
        check('Concatenate: the rows of both tables', r['rows'], r['want'])
        check('the source column says where a row came from', r['src'], r['second'])

    # ---- Join with the summary, Update from a small table ------------------------------------------------------
    r = await js(page, r'''
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      const s = SM.app.tables.find((x) => x.name === 'Students By (sex)');
      const n0 = SM.app.tables.length;
      T.cmd('Tables', 'Join…'); let d = T.dlg();
      const sel = d.querySelector('select');
      sel.value = s.id; sel.dispatchEvent(new Event('change'));
      const pairs = [...d.querySelectorAll('.smt-pairs li')].map((li) => li.firstChild.textContent);
      T.ok(d);
      const j = await T.newTable(n0);
      const sx = j.col('sex').values, m = j.col('Mean(height (cm))').values;
      const means = new Map(s.col('sex').values.map((v, i) => [v, s.col('Mean(height (cm))').values[i]]));
      const okJ = sx.every((v, i) => m[i] === means.get(v));
      // Update: new weights for two students
      const u = new SM.Table({ name: 'fixes', columns: [{ name: 'id', dataType: 'character', values: ['S02', 'S05', 'S99'] }, { name: 'weight (kg)', dataType: 'numeric', values: [99, NaN, 1] }, { name: 'note', dataType: 'character', values: ['a', 'b', 'c'] }] });
      SM.app.addTable(u, { show: false });
      SM.app.showTab(SM.app.tabOf(t));
      const w5 = t.col('weight (kg)').values[4];
      T.cmd('Tables', 'Update…'); d = T.dlg();
      const sel2 = d.querySelector('select'); sel2.value = u.id; sel2.dispatchEvent(new Event('change'));
      T.ok(d);
      await T.until(() => t.col('note'));
      const upd = [t.col('weight (kg)').values[1], t.col('weight (kg)').values[4] === w5, t.col('note').values.slice(0, 5)];
      SM.app.undo();
      await T.sleep(30);
      return { pairs, rows: j.nrows, okJ, upd, undone: !t.col('note') && t.col('weight (kg)').values[1] !== 99 };
    ''', 'Join and Update')
    if r:
        check('Join matches the column both tables have', r['pairs'], ['sex = sex'])
        check('Join gives every student the mean of their sex', (r['rows'], r['okJ']), (60, True))
        check('Update: a value replaced, a missing one ignored, a column added', r['upd'], [99, True, [None, 'a', None, None, 'b']])
        check('Edit > Undo takes the update back', r['undone'], True)

    # ---- Missing Data Pattern, linked ------------------------------------------------------------------------------
    r = await js(page, r'''
      const t = SM.app.tables[0];
      const m = SM.tables.copyTable(t, Array.from({ length: t.nrows }, (_, i) => i), t.columns, { name: 'Students with gaps' });
      SM.app.addTable(m);
      [2, 5, 9, 11].forEach((i) => m.setCell(i, 'height (cm)', NaN));
      [5, 9, 30].forEach((i) => m.setCell(i, 'weight (kg)', NaN));
      m.setCell(40, 'sex', null);
      const n0 = SM.app.tables.length;
      T.cmd('Tables', 'Missing Data Pattern…'); const d = T.dlg();
      T.cast(d, ['sex', 'height (cm)', 'weight (kg)'], 'Add Columns');
      T.ok(d);
      const p = await T.newTable(n0);
      const pats = p.col('Patterns').values, counts = p.col('Count').values;
      const k = pats.indexOf('011');
      p.select([k]);
      const sel = m.selectedRows();
      m.select([]);
      return { cols: p.columns.map((c) => c.name), pats, counts, sel };
    ''', 'Missing Data Pattern')
    if r:
        check('Missing Data Pattern columns', r['cols'], ['Count', 'Number of columns missing', 'Patterns', 'sex', 'height (cm)', 'weight (kg)'])
        check('the patterns and their counts', list(zip(r['pats'], r['counts'])), [('000', 54), ('001', 1), ('010', 2), ('011', 2), ('100', 1)])
        check('selecting a pattern selects its rows', r['sel'], [5, 9])

    # ---- Explore Missing Values: reports, selection, imputation, undo ----------------------------------------------
    r = await js(page, r'''
      const m = SM.app.tables.find((x) => x.name === 'Students with gaps');
      SM.app.showTab(SM.app.tabOf(m));
      const P = SM.platforms.get('missing');
      const ids = ['sex', 'height (cm)', 'weight (kg)'].map((n) => m.col(n).id);
      const rep = SM.app.openReport(P, { roles: { y: ids }, options: {} }, m);
      await T.done(rep);
      const heads = [...rep.body.querySelectorAll('.sm-ob-head')].map((h) => h.textContent.trim());
      const colTable = [...rep.body.querySelectorAll('.sm-ob')].find((o) => o.querySelector('.sm-ob-head').textContent.trim() === 'Missing Columns Report').querySelector('table.sm-rt');
      const colRows = [...colTable.querySelectorAll('tbody tr')].map((tr) => [...tr.children].map((td) => td.textContent));
      colTable.querySelectorAll('tbody tr')[1].click();
      const selH = m.selectedRows();
      const snap = rep.plots.find((p) => p.opts.title === 'Missing value snapshot');
      T.button(rep.body, 'Select Rows with Missing').click();
      const selAny = m.selectedRows().length;
      m.select([]);
      // impute the mean, as new columns
      const before = m.columns.length;
      T.button(rep.body, 'Impute ▾').click();
      T.menuButton('Mean').click();
      await T.sleep(100);
      let f = T.dlg(); T.set(T.opt(f, 'Save'), 'new'); T.ok(f);
      await T.until(() => m.col('Imputed[height (cm)]'));
      const imp = m.col('Imputed[height (cm)]').values;
      const h = m.col('height (cm)').values;
      const mean = T.mean(h);
      const okMean = [2, 5, 9, 11].every((i) => T.near(imp[i], mean)) && imp[0] === h[0];
      // multivariate normal, in place, then Undo
      T.button(rep.body, 'Impute ▾').click();
      T.menuButton('Multivariate Normal Imputation').click();
      await T.sleep(100);
      f = T.dlg(); T.set(T.opt(f, 'Save'), 'inplace'); T.ok(f);
      await T.until(() => !Number.isNaN(m.col('weight (kg)').values[5]));
      const filled = m.col('weight (kg)').values.filter(Number.isNaN).length + m.col('height (cm)').values.filter(Number.isNaN).length;
      SM.app.undo();
      const back = Number.isNaN(m.col('weight (kg)').values[5]);
      return { heads, colRows, selH, snapPoints: snap ? snap.traces[0].x.length : null, selAny, added: m.columns.length - before, okMean, filled, back, errors: [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent) };
    ''', 'Explore Missing Values')
    if r:
        check('Explore Missing Values outlines', [h for h in r['heads'] if h in ('Missing Columns Report', 'Missing Value Report', 'Missing Value Snapshot')], ['Missing Columns Report', 'Missing Value Report', 'Missing Value Snapshot'])
        check('the missing columns report', [row[:2] for row in r['colRows']], [['sex', '1'], ['height (cm)', '4'], ['weight (kg)', '3']])
        check('a click on a column\'s line selects its missing rows', r['selH'], [2, 5, 9, 11])
        check('the snapshot marks each missing cell', r['snapPoints'], 8)
        check('Select Rows with Missing', r['selAny'], 6)
        check('mean imputation as new columns', (r['added'], r['okMean']), (2, True))
        check('multivariate normal imputation in place fills the numeric columns', r['filled'], 0)
        check('Edit > Undo takes the imputation back', r['back'], True)
        check('no errors in the report', r['errors'], [])
    await shot(page, 't02-missing.png')
    await snapshot_code(page)

    # ---- Tabulate: drag into the drop zones, nest, buttons, Done ---------------------------------------------------------
    r = await js(page, r'''
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      SM.app.grid.colSel.clear();
      SM.app.launch('tabulate');
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await T.done(rep);
      const zone = (k) => rep.body.querySelector(`.smt-zone[data-zone="${k}"]`);
      const empty = !rep.body.querySelector('table.smt-table');
      let p = T.done(rep); const accepted = T.drop(zone('rows'), [t.col('sex').id]); await p;
      p = T.done(rep); T.drop(rep.body.querySelector('.smt-zone[data-zone="rows"] .smt-chain'), [t.col('age').id]); await p;
      p = T.done(rep); T.drop(zone('analysis'), [t.col('height (cm)').id]); await p;
      const chips = [...zone('rows').querySelectorAll('.smt-chip')].map((c) => c.textContent.replace('×', '').trim());
      const stats = [...rep.body.querySelectorAll('.smt-statbtn.is-on')].map((b) => b.textContent);
      // click-to-add: weight as an analysis column with the buttons
      const li = [...rep.body.querySelectorAll('.smt-cols li')].find((x) => x.textContent === 'weight (kg)');
      li.click();
      p = T.done(rep); T.button(rep.body, 'Analysis Column').click(); await p;
      p = T.done(rep); T.button(rep.body, 'Std Dev').click(); await p;
      const tbl = rep.body.querySelector('table.smt-table');
      const rt = tbl._rt;
      const head = [...tbl.querySelectorAll('thead tr')].map((tr) => [...tr.children].map((c) => c.textContent));
      // F, age 12: N, mean and std dev of height against the page's own
      const sx = t.col('sex').values, ag = t.col('age').values, h = t.col('height (cm)').values;
      const pick = h.filter((v, i) => sx[i] === 'F' && ag[i] === 12);
      const m = T.mean(pick);
      const sd = Math.sqrt(pick.reduce((a, b) => a + (b - m) ** 2, 0) / (pick.length - 1));
      const row = rt.rows.find((x) => x.r0 === 'F' && x.r1 === '12');
      const keys = rt.columns.map((c) => c.label);
      const val = (lab) => row[rt.columns[keys.indexOf(lab)].key];
      const okCell = val('N(height (cm))') === pick.length && T.near(val('Mean(height (cm))'), m) && T.near(val('Std Dev(height (cm))'), sd);
      const rep0 = [...tbl.querySelectorAll('tbody tr')][1].children[0].classList.contains('smt-rep');
      // All row, then Done hides the builder; the red triangle brings it back
      p = T.done(rep); const allBox = [...rep.body.querySelectorAll('.smt-opts label')].find((l) => l.textContent.startsWith('All row')).querySelector('input'); allBox.checked = true; allBox.dispatchEvent(new Event('change')); await p;
      const last = rep.body.querySelector('table.smt-table')._rt.rows.slice(-1)[0];
      const allMean = last[rep.body.querySelector('table.smt-table')._rt.columns[keys.indexOf('Mean(height (cm))')].key];
      p = T.done(rep); T.button(rep.body, 'Done').click(); await p;
      const hidden = !rep.body.querySelector('.smt-builder') && !!rep.body.querySelector('table.smt-table');
      const nt0 = SM.app.tables.length;
      SM.report.tableFromRT && SM.app.addTable(SM.report.tableFromRT(rep.body.querySelector('table.smt-table')._rt, 'Tabulate table'));
      const made = SM.app.tables[SM.app.tables.length - 1];
      return { empty, accepted, chips, stats, head: head.slice(0, 2), okCell, rep0, all: [last.r0, T.near(allMean, T.mean(h))], hidden, made: [made.name, made.columns.slice(0, 3).map((c) => c.name), made.nrows], title: rep.title };
    ''', 'Tabulate')
    if r:
        check('Tabulate opens empty, with its drop zones', r['empty'], True)
        check('the rows zone takes a dragged column', r['accepted'], True)
        check('age dropped on sex is nested under it', r['chips'], ['sex', 'age'])
        check('an analysis column brings the mean', r['stats'], ['N', 'Mean'])
        check('the header shows the analysis columns over their statistics', r['head'][1][2:], ['N', 'Mean', 'Std Dev', 'N', 'Mean', 'Std Dev'])
        check('a cell: N, mean and std dev of height for F aged 12', r['okCell'], True)
        check('a repeated outer level is not written twice', r['rep0'], True)
        check('the All row is the whole table', r['all'], ['All', True])
        check('Done hides the control panel and keeps the table', r['hidden'], True)
        check('the table makes a data table', r['made'][1], ['sex', 'age', 'N(height (cm))'])
    await shot(page, 't03-tabulate.png')

    # ---- the formula editor ---------------------------------------------------------------------------------------------
    r = await js(page, r'''
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      SM.app.grid.colSel.clear();
      const pr = SM.formula.edit(t, null, { name: 'bmi' });
      await T.sleep(60);
      const d = T.dlg();
      const ta = d.querySelector('textarea.smf-expr');
      T.set(ta, ':"weight (kg)" / (:"height (cm)" / 100)^');
      await T.sleep(400);
      const err = d.querySelector('.smf-error');
      const errText = err ? err.textContent : null;
      const mark = err && err.querySelector('mark') ? err.querySelector('mark').textContent : null;
      T.ok(d);
      await T.sleep(50);
      const stillOpen = !!T.dlg() && T.dlg() === d;
      const msg = d.querySelector('.smf-msg').textContent;
      // a function from the palette wraps the selection
      T.set(ta, ':"weight (kg)" / (:"height (cm)" / 100)^2');
      await T.sleep(400);
      const preview = [...d.querySelectorAll('.smf-rows tbody tr')].slice(0, 2).map((tr) => tr.children[1].textContent);
      ta.setSelectionRange(0, ta.value.length);
      [...d.querySelectorAll('.smf-item')].find((b) => b.dataset.fn === 'Round').click();
      const wrapped = ta.value;
      T.set(ta, 'Round(' + ':"weight (kg)" / (:"height (cm)" / 100)^2' + ', 1)');
      T.ok(d);
      const c = await pr;
      const w = t.col('weight (kg)').values, h = t.col('height (cm)').values;
      const want = Math.round((w[0] / (h[0] / 100) ** 2) * 10) / 10;
      const v0 = c.values[0];
      SM.app.recordCells(t, 'Edit Cell', [[0, t.col('weight (kg)').id]]);
      t.setCell(0, 'weight (kg)', 90);
      const v1 = c.values[0];
      const want1 = Math.round((90 / (h[0] / 100) ** 2) * 10) / 10;
      SM.app.undo();
      const v2 = c.values[0];
      // Column Info shows the formula, and Edit Formula… opens it
      SM.app.columnInfo(c);
      await T.sleep(60);
      const ci = T.dlg();
      const shown = ci.querySelector('code') ? ci.querySelector('code').textContent : null;
      T.button(ci, 'Edit Formula…').click();
      await T.sleep(80);
      const ed = T.dlg();
      const edExpr = ed.querySelector('textarea.smf-expr').value;
      T.button(ed, 'Cancel').click();
      return { errText, mark, stillOpen, msg, preview, wrapped, name: c.name, expr: c.formula.expr, v0, want, v1, want1, v2, shown, edExpr, flag: SM.app.grid.head.textContent.includes('ƒ') };
    ''', 'Formula editor')
    if r:
        check('a formula that is not finished shows where', ('Not a formula yet' in (r['errText'] or ''), r['mark']), (True, ' '))
        check('OK refuses it and says why', (r['stillOpen'], 'expected a value' in r['msg']), (True, True))
        check('the preview shows the first rows', len(r['preview']), 2)
        check('a function from the palette wraps the selected text', r['wrapped'], 'Round(:"weight (kg)" / (:"height (cm)" / 100)^2)')
        check('OK makes the formula column', (r['name'], r['expr']), ('bmi', 'Round(:"weight (kg)" / (:"height (cm)" / 100)^2, 1)'))
        check('its values are the formula\'s', r['v0'], r['want'])
        check('it follows an edit of a column it uses', r['v1'], r['want1'])
        check('and Undo of that edit', r['v2'], r['v0'])
        check('Column Info shows the formula and Edit Formula… opens it', (r['shown'], r['edExpr']), (r['expr'], r['expr']))
        check('the grid marks a formula column', r['flag'], True)
    await shot(page, 't04-formula.png')

    # ---- New Formula Column from the column's right-click menu, through the menus themselves --------------------------------
    r = await js(page, r'''
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      await T.sleep(80);
      const hc = [...document.querySelectorAll('.sm-view:not([hidden]) .sm-hcell')].find((x) => x.textContent.includes('height (cm)'));
      const r0 = hc.getBoundingClientRect();
      hc.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: r0.left + 10, clientY: r0.top + 10 }));
      await T.sleep(60);
      const nfc = T.menuButton('New Formula Column');
      const isSub = nfc && nfc.classList.contains('sm-sub');
      nfc.dispatchEvent(new MouseEvent('mouseenter'));
      await T.sleep(40);
      const tr = T.menuButton('Transform');
      tr.dispatchEvent(new MouseEvent('mouseenter'));
      await T.sleep(40);
      const labels = [...document.querySelectorAll('.sm-menu')].pop().textContent;
      T.menuButton('Log').click();
      await T.until(() => t.col('Log[height (cm)]'));
      const c = t.col('Log[height (cm)]');
      const h = t.col('height (cm)').values;
      const ok = c.values.every((v, i) => T.near(v, Math.log(h[i])));
      const at = t.colIndex(c) === t.colIndex('height (cm)') + 1;
      // Combine two selected columns: the command's own submenu
      const g = SM.app.grid; g.colSel.clear(); g.colSel.add(t.col('height (cm)').id); g.colSel.add(t.col('weight (kg)').id);
      const items = SM.tables.nfcItems(SM.app, SM.app.selectedColumns());
      const ratio = items.find((x) => x.label === 'Combine').submenu().find((x) => x.label === 'Ratio');
      await ratio.action();
      const rc = t.columns.find((x) => x.name.startsWith('Ratio['));
      const okR = rc && rc.values.every((v, i) => T.near(v, h[i] / t.col('weight (kg)').values[i]));
      const rank = SM.tables.nfcItems(SM.app, [t.col('weight (kg)')]).find((x) => x.label === 'Distributional').submenu().find((x) => x.label === 'Normal Quantile');
      await rank.action();
      const nq = t.col('Normal Quantile[weight (kg)]');
      g.colSel.clear();
      // as Distribution's Save > Normal Quantiles: Φ⁻¹(r/(n+1)) of the averaged ranks
      const wv = t.col('weight (kg)').values, rk = SM.util.ranks(wv);
      const okQ = nq && nq.values.every((v, i) => Math.abs(v - SM.util.qnorm(rk[i] / (wv.length + 1))) < 1e-7);
      return { isSub, labels, ok, at, expr: c.formula.expr, ratio: rc ? [rc.name, rc.formula.expr, okR] : null, nq: nq ? [nq.formula.expr, okQ] : null };
    ''', 'New Formula Column')
    if r:
        check('New Formula Column is a submenu of the column menu', r['isSub'], True)
        check('Transform lists JMP\'s transforms', all(x in r['labels'] for x in ['Log', 'Log10', 'Square Root', 'Square', 'Reciprocal', 'Exp', 'Standardize', 'Center', 'Absolute Value']), True)
        check('Log makes Log[height (cm)] next to it', (r['expr'], r['ok'], r['at']), ('Log(:"height (cm)")', True, True))
        check('Combine > Ratio of two selected columns', r['ratio'], ['Ratio[height (cm), weight (kg)]', ':"height (cm)" / :"weight (kg)"', True])
        check('Distributional > Normal Quantile', r['nq'], ['Normal Quantile(Col Rank(:"weight (kg)", <<Tie("average")) / (Col Number(:"weight (kg)") + 1))', True])

    # ---- Recode, the utilities ------------------------------------------------------------------------------------------------
    r = await js(page, r'''
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      T.cmd('Cols', 'Recode…', t.col('sex'));
      let d = T.dlg();
      const inputs = [...d.querySelectorAll('.smr-new')];
      T.set(inputs[0], 'female'); T.set(inputs[1], 'male');
      T.button(d, 'Title Case').click();
      T.ok(d, 'Recode');
      await T.sleep(30);
      const s2 = t.col('sex 2');
      const sx = t.col('sex').values;
      const okNew = s2 && s2.values.every((v, i) => v === (sx[i] === 'F' ? 'Female' : 'Male'));
      const order = s2 ? s2.valueOrder : null;
      // as a formula column
      T.cmd('Cols', 'Recode…', t.col('age'));
      d = T.dlg();
      const ins = [...d.querySelectorAll('.smr-new')];
      T.set(ins[0], '11'); T.set(ins[1], '11');
      T.set(d.querySelector('.smr-out select'), 'formula');
      T.ok(d, 'Recode');
      await T.sleep(30);
      const a2 = t.col('age 2');
      const ag = t.col('age').values;
      const okA = a2 && a2.values.every((v, i) => v === (ag[i] <= 13 ? 11 : ag[i]));
      // Make Indicator Columns, Binning, Standardize
      const g = SM.app.grid; g.colSel.clear(); g.colSel.add(t.col('sex').id);
      T.cmd('Cols/Utilities', 'Make Indicator Columns…');
      await T.sleep(50); d = T.dlg(); T.ok(d);
      await T.until(() => t.col('sex[F]'));
      const ind = t.col('sex[F]').values.every((v, i) => v === (sx[i] === 'F' ? 1 : 0));
      g.colSel.clear(); g.colSel.add(t.col('height (cm)').id);
      await SM.tables.makeBinning(t, t.col('height (cm)'), { method: 'custom', cuts: '150, 160', style: 'interval', formula: true, name: 'height bins' });
      const hb = t.col('height bins');
      const h = t.col('height (cm)').values;
      const okB = hb.values.every((v, i) => v === (h[i] < 150 ? hb.valueOrder[0] : h[i] < 160 ? hb.valueOrder[1] : hb.valueOrder[2]));
      T.cmd('Cols/Utilities', 'Standardize');
      await T.until(() => t.col('Standardize[height (cm)]'));
      const z = t.col('Standardize[height (cm)]').values;
      const zm = T.mean(z), zs = Math.sqrt(z.reduce((a, b) => a + (b - zm) ** 2, 0) / (z.length - 1));
      g.colSel.clear();
      return { okNew, order, formula: a2 ? a2.formula.expr : null, okA, ind, bins: [hb.modelingType, hb.valueOrder, okB, hb.formula ? hb.formula.expr.slice(0, 40) : null], z: [Math.abs(zm) < 1e-12, T.near(zs, 1)] };
    ''', 'Recode and utilities')
    if r:
        check('Recode with Title Case makes sex 2', r['okNew'], True)
        check('the recoded column keeps the value order', r['order'], ['Female', 'Male'])
        check('Recode as a formula column', (r['formula'], r['okA']), ('Match(:age, 12, 11, 13, 11, :age)', True))
        check('Make Indicator Columns', r['ind'], True)
        check('Make Binning Column: ordinal, labelled, as a formula', r['bins'][:3], ['ordinal', r['bins'][1], True])
        check('the bins are labelled by interval', r['bins'][1][0].startswith('[') and r['bins'][1][-1].endswith(']'), True)
        check('Standardize: mean 0, std dev 1', r['z'], [True, True])

    # ---- Columns Viewer ------------------------------------------------------------------------------------------------------
    r = await js(page, r'''
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      SM.app.launch('colviewer');
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await T.done(rep);
      const trs = [...rep.body.querySelectorAll('table.smt-cv tbody tr')];
      const line = (name) => trs.find((tr) => tr.firstChild.textContent === name);
      const hRow = [...line('height (cm)').children].map((td) => td.textContent);
      line('height (cm)').click(); line('weight (kg)').click();
      const gridSel = SM.app.selectedColumns().map((c) => c.name);
      const n0 = SM.app.reports.length;
      T.button(rep.body, 'Distribution').click();
      const dist = SM.app.reports[SM.app.reports.length - 1];
      await T.done(dist);
      const h = t.col('height (cm)').values;
      return { hRow, want: [SM.util.fmt(T.mean(h)), SM.util.fmt(T.weibull(h, 0.25)), SM.util.fmt(T.weibull(h, 0.75))], gridSel, opened: SM.app.reports.length - n0, distCols: dist.platform.id === 'distribution' ? dist.spec.roles.y.map((id) => t.col(id).name) : null };
    ''', 'Columns Viewer')
    if r:
        check('Columns Viewer: the mean and the quartiles of height', [r['hRow'][6], r['hRow'][9], r['hRow'][10]], r['want'])
        check('clicking lines selects the columns in the table', r['gridSel'], ['height (cm)', 'weight (kg)'])
        check('Distribution opens with them', (r['opened'], r['distCols']), (1, ['height (cm)', 'weight (kg)']))

    # ---- the Python script window ---------------------------------------------------------------------------------------------
    r = await js(page, r'''
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      const n0 = SM.app.reports.length;
      T.cmd('Python', 'Script…');
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await T.done(rep);
      const warnHidden = rep.body.querySelector('.sm-ob-warn').hidden;
      const ta = rep.body.querySelector('.smp-editor textarea');
      T.set(ta, 'print(df.shape, df["sex"].dtype)\nresult = df.groupby("sex", observed=True)["height (cm)"].mean().reset_index()');
      // in colour, as the notebook's editor shows it: a built-in, a string, a keyword
      const hl = rep.body.querySelector('.smp-editor .sm-ed-hl');
      const colours = ['t-b', 't-s', 't-k'].map((c) => [...hl.querySelectorAll('.' + c)].map((x) => x.textContent)[0] || null);
      // Tab indents
      ta.focus();
      ta.setSelectionRange(0, 0);
      ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }));
      const indented = ta.value.startsWith('    print');
      ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }));
      const dedented = ta.value.startsWith('print');
      T.button(rep.body, 'Run').click();
      await T.until(() => rep.body.querySelector('.smp-stdout'));
      const out = rep.body.querySelector('.smp-stdout').textContent;
      const nt0 = SM.app.tables.length;
      T.button(rep.body, 'Make into Data Table').click();
      const made = await T.newTable(nt0);
      SM.app.showTab(SM.app.tabOf(rep));
      T.set(ta, 'x = 1\ny = [1][3]\n');
      T.button(rep.body, 'Run').click();
      await T.until(() => rep.body.querySelector('.sm-ob-error'));
      const err = rep.body.querySelector('.sm-ob-error').textContent;
      // a script that came with a project: shown with a warning, not run
      const p2 = SM.app.openReport(SM.platforms.get('pyscript'), { roles: {}, options: { code: 'print("from a file")' } }, t);
      await T.done(p2);
      const warn2 = !p2.body.querySelector('.sm-ob-warn').hidden;
      const ran = !!p2.body.querySelector('.smp-stdout');
      return { warnHidden, colours, indented, dedented, out, want: `(${t.nrows}, ${t.columns.length}) category`, made: [made.name, made.columns.map((c) => c.name), made.col('sex').modelingType, made.nrows], err, warn2, ran };
    ''', 'Python script')
    if r:
        check('a script opened from the menu has no warning', r['warnHidden'], True)
        check('the script is in colour: print a built-in, "sex" a string, True a keyword', r['colours'], ['print', '"sex"', 'True'])
        check('Tab indents and shift+Tab dedents', (r['indented'], r['dedented']), (True, True))
        check('Run shows what the script prints', r['out'].strip(), r['want'])
        check('result becomes a data table', r['made'], ['Python result', ['sex', 'height (cm)'], 'nominal', 2])
        check('an error shows with its line', 'IndexError: list index out of range (line 2)' in r['err'], True)
        check('a script from a project shows a warning and does not run', (r['warn2'], r['ran']), (True, False))
    await shot(page, 't05-python.png')

    # ---- the (i) of every dialog: each role, option and field with what it is for -------------------------------------------------------
    r = await js(page, r'''
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t)); t.select([]);
      const out = {};
      for (const label of ['Summary…', 'Subset…', 'Sort…', 'Stack…', 'Split…', 'Transpose…', 'Missing Data Pattern…']) {
        T.cmd('Tables', label); const d = T.dlg();
        const roles = [...d.querySelectorAll('.sm-role .sm-btn')].map((b) => b.textContent);
        const nopts = d.querySelectorAll('.sm-launch-opts label').length;
        const info = await T.infoOf(d.querySelector('.sm-dialog-head'));
        T.ok(d, 'Cancel');
        out[label] = { roles: T.names(info, 'Roles'), want: roles, opts: T.names(info, 'Options').length, nopts, thin: T.thin(info, ['Roles', 'Options', 'Settings', 'Each statistic']), settings: T.names(info, 'Settings'), stats: T.names(info, 'Each statistic').length, audit: info.audit, title: info.title };
      }
      SM.app.launch('missing'); let d = T.dlg();
      const mv = await T.infoOf(d.querySelector('.sm-dialog-head')); T.ok(d, 'Cancel');
      out.missing = { roles: T.names(mv, 'Roles'), thin: T.thin(mv, ['Roles']), audit: mv.audit };
      return { out, open: !!T.dlg() };
    ''', 'launch dialogs\' (i)')
    if r:
        for label, v in r['out'].items():
            if label == 'missing':
                continue
            check(f'{label} the (i) explains every role and option', (v['roles'], v['opts'], v['thin'], v['audit']), (v['want'], v['nopts'], [], []))
        check('Summary: the (i) explains every statistic', r['out']['Summary…']['stats'], 17)
        check('Sort: the (i) explains the arrows beside the By columns', r['out']['Sort…']['settings'], ['▲ ▼ beside a By column'])
        check('Explore Missing Values: the (i) explains its roles', (r['out']['missing']['roles'], r['out']['missing']['thin'], r['out']['missing']['audit']), (['Y, Columns', 'By'], [], []))
        check('the dialogs are closed again', r['open'], False)
    r = await js(page, r'''
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      const g = SM.app.grid; g.colSel.clear(); g.colSel.add(t.col('sex').id);
      const form = async (open) => { open(); await T.sleep(60); const d = T.dlg(); const info = await T.infoOf(d.querySelector('.sm-dialog-head')); T.button(d, 'Cancel').click(); await T.sleep(30); return info; };
      const ind = await form(() => T.cmd('Cols/Utilities', 'Make Indicator Columns…'));
      const bin = await form(() => T.cmd('Cols/Utilities', 'Make Binning Column…'));
      g.colSel.clear();
      const dlg = async (open) => { open(); await T.sleep(60); const d = T.dlg(); const info = await T.infoOf(d.querySelector('.sm-dialog-head')); T.button(d, 'Cancel').click(); await T.sleep(30); return info; };
      const concat = await dlg(() => T.cmd('Tables', 'Concatenate…'));
      const join = await dlg(() => T.cmd('Tables', 'Join…'));
      const upd = await dlg(() => T.cmd('Tables', 'Update…'));
      const rec = await dlg(() => T.cmd('Cols', 'Recode…', t.col('sex')));
      const m = SM.app.reports.find((x) => x.platform.id === 'missing');
      const bar = await T.infoOf(m.body.querySelector('.smt-mvbar'));
      const imp = await form(() => { T.button(m.body, 'Impute ▾').click(); T.menuButton('Chained Equations (MICE)').click(); });
      const tab = SM.app.reports.find((x) => x.platform.id === 'tabulate');
      const p = T.done(tab); tab.spec.options.panel = true; tab.run(); await p;
      const tb = await T.infoOf(tab.body.querySelector('.smt-left h4'));
      const head = (id) => [...SM.app.reports.find((x) => x.platform.id === id).body.querySelectorAll('.sm-ob-head')].find((h) => h.querySelector('.info-btn'));
      const cv = await T.infoOf(head('colviewer'));
      const py = await T.infoOf(head('pyscript'));
      const f = (info) => ({ fields: T.names(info, 'Fields'), thin: T.thin(info, ['Fields']), audit: info.audit });
      return { ind: f(ind), indTitle: ind.title, bin: f(bin), imp: f(imp), concat: f(concat), join: f(join), upd: f(upd), rec: { dialog: T.names(rec, 'The dialog'), done: T.names(rec, 'Done'), audit: rec.audit },
        bar: T.names(bar, 'Buttons'), tab: T.names(tab ? tb : null, 'The control panel'), cv: T.names(cv, 'In the report'), py: T.names(py, 'In the report'), open: !!T.dlg() };
    ''', 'forms and dialogs\' (i)')
    if r:
        check('Make Indicator Columns: the form\'s (i) lists its fields', (r['ind']['fields'], r['ind']['thin'], r['ind']['audit'], r['indTitle']), (['Append column name (sex[F] rather than F)', 'As formula columns'], [], [], 'Make Indicator Columns'))
        check('Make Binning Column: the form\'s (i) lists its fields', (len(r['bin']['fields']), r['bin']['thin'], r['bin']['audit']), (9, [], []))
        check('Impute (MICE): the form\'s (i) lists its fields', (r['imp']['fields'], r['imp']['thin'], r['imp']['audit']), (['Save', 'Seed', 'Cycles'], [], []))
        check('Concatenate: the dialog\'s (i) explains its fields', (r['concat']['fields'], r['concat']['audit']), (['Data tables to be concatenated', 'Create source column', 'Append to first table', 'Output table name'], []))
        check('Join: the dialog\'s (i) explains its fields', (r['join']['fields'], r['join']['thin'], r['join']['audit']), (['Join with', 'Matching', 'Matching columns', 'Include non-matches', 'Drop multiples', 'Match flag', 'Merge same name columns', 'Output table name'], [], []))
        check('Update: the dialog\'s (i) explains its fields', (r['upd']['fields'], r['upd']['thin'], r['upd']['audit']), (['Update with data from', 'Matching', 'Matching columns', 'Ignore missing', 'Replace columns in main table', 'Add columns from update table'], [], []))
        check('Recode: the dialog\'s (i) explains its buttons and fields', (len(r['rec']['dialog']), r['rec']['done'], r['rec']['audit']), (12, ['New Column', 'In Place', 'Formula Column'], []))
        check('Explore Missing Values: an (i) by its buttons', r['bar'], ['Select Rows with Missing', 'Exclude Rows with Missing', 'Impute ▾'])
        check('Tabulate: the control panel\'s (i) explains its buttons', [n for n in r['tab'] if n in ('Add to Rows', 'Nest in Rows', 'Add to Columns', 'Analysis Column', 'Clear', 'Done')], ['Add to Rows', 'Nest in Rows', 'Add to Columns', 'Analysis Column', 'Clear', 'Done'])
        check('Columns Viewer: its outline\'s (i) explains the buttons', r['cv'], ['A line of the table', 'Distribution', 'Clear Select', 'Select All'])
        check('Python Script: its outline\'s (i) explains the editor and Run', [n for n in r['py'] if n in ('The editor', 'Run', 'Examples ▾')], ['The editor', 'Run', 'Examples ▾'])
        check('the forms and dialogs are closed again', r['open'], False)

    await wp5(page)

    # ---- the (i) topics and Help links, then the dark theme and phone width ----------------------------------------------------------
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    r = await js(page, r'''
      const keys = ['cmd:summary', 'cmd:subset', 'cmd:sort', 'cmd:stack', 'cmd:split', 'cmd:transpose', 'cmd:concatenate', 'cmd:join', 'cmd:update', 'cmd:missingpattern', 'cmd:formula', 'cmd:recode', 'cmd:indicator', 'cmd:binning', 'cmd:pyscript', 'p:tabulate', 'p:colviewer', 'p:missing'];
      const help = ['help-p-tabulate', 'help-p-colviewer', 'help-p-missing'].map((id) => !!document.getElementById(id));
      return { help };
    ''')
    if r:
        check('the platforms have rows in Help', r['help'], [True, True, True])
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    r = await js(page, r'''
      const rep = SM.app.reports.find((x) => x.platform.id === 'tabulate');
      SM.app.showTab(SM.app.tabOf(rep));
      await T.sleep(300);
      const ctx = rep; rep.spec.options.panel = true; rep.run(); await T.done(rep);
      return true;
    ''')
    await asyncio.sleep(0.6)
    await shot(page, 't06-tabulate-dark.png')
    await page.ev("(() => { const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t)); SM.formula.edit(t, t.col('bmi')); })()")
    await asyncio.sleep(0.6)
    await shot(page, 't07-formula-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    wide = await page.ev('document.documentElement.scrollWidth <= innerWidth + 1')
    check('no horizontal page scroll at phone width, with the formula editor open', wide, True)
    await shot(page, 't08-phone-formula.png')
    await page.ev("T.button(T.dlg(), 'Cancel').click()")
    await page.ev("(() => { const rep = SM.app.reports.find((x) => x.platform.id === 'tabulate'); SM.app.showTab(SM.app.tabOf(rep)); })()")
    await asyncio.sleep(0.6)
    wide = await page.ev('document.documentElement.scrollWidth <= innerWidth + 1')
    check('no horizontal page scroll at phone width, with Tabulate', wide, True)
    await shot(page, 't09-phone-tabulate.png')
    # ---- a column dragged into the formula with the mouse lands where it is let go
    await page.ev('''(() => { const t = SM.app.tables.find(x => x.name === 'Students') || SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t)); window.__fpr = SM.formula.edit(t, null, { name: 'dragged' }); })()''')
    await asyncio.sleep(0.3)
    geo = '''(() => { const d = [...document.querySelectorAll('.sm-dialog')].pop();
      const src = [...d.querySelectorAll('.smf-item')].find(b => b.textContent === 'height (cm)'), ta = d.querySelector('textarea.smf-expr');
      src.scrollIntoView({ block: 'nearest' }); ta.scrollIntoView({ block: 'nearest' });
      const a = src.getBoundingClientRect(), b = ta.getBoundingClientRect();
      return [a.x + 24, a.y + a.height / 2, b.x + b.width - 12, b.y + 12]; })()'''
    began = await page.drag_to(*(await page.ev(geo)))
    await asyncio.sleep(0.5)
    one = await page.ev('''(() => { const d = [...document.querySelectorAll('.sm-dialog')].pop(); return { value: d.querySelector('textarea.smf-expr').value, rows: d.querySelectorAll('.smf-rows tbody tr').length, error: !!d.querySelector('.smf-error') }; })()''')
    await page.ev('''(() => { const d = [...document.querySelectorAll('.sm-dialog')].pop(); const ta = d.querySelector('textarea.smf-expr'); ta.value = '2 * '; ta.dispatchEvent(new Event('input')); })()''')
    await asyncio.sleep(0.2)
    await page.drag_to(*(await page.ev(geo)))
    await asyncio.sleep(0.5)
    two = await page.ev('''(() => { const d = [...document.querySelectorAll('.sm-dialog')].pop(); const v = d.querySelector('textarea.smf-expr').value;
      [...d.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Cancel').click(); return v; })()''')
    check('a drag began from the formula editor\'s columns', began, True)
    check('dropped into the empty formula: the column\'s reference, and the preview shows its rows', (one['value'], one['rows'] > 0, one['error']), (':"height (cm)"', True, False))
    check('dropped after text: it goes where it is let go', two, '2 * :"height (cm)"')
    check('no script errors', page.errors, [])
    await page.close()


# ---- the column properties, transforms from a list, Keep dialog open, Preselect Role, the grid's
# Fill and Header Graphs, Subset's balanced samples and weights, Recode's Group, Tabulate's Show Chart
# and binned columns, Missing Value Clustering and the SVD and shrunk imputations, Import Multiple Files
async def wp5(page):
    await page.ev(GRAPHS_JS)
    await js(page, r"""
      const r = SM.util.rng('wp5');
      const n = 24, score = [], grp = [], resp = [], seq = [], txt = [];
      for (let i = 0; i < n; i++) {
        score.push([3, 7, 10].includes(i) ? 999 : i === 15 ? -1 : +(50 + 10 * r.normal()).toFixed(1));
        grp.push(1 + (i % 3)); resp.push(i % 4 === 0 ? 'yes' : 'no'); seq.push(i < 2 ? i + 1 : NaN); txt.push(i < 3 ? ['a', 'b', 'c'][i] : null);
      }
      const t = new SM.Table({ name: 'Props', columns: [
        { name: 'score', dataType: 'numeric', values: score }, { name: 'grp', dataType: 'numeric', modelingType: 'nominal', values: grp },
        { name: 'resp', dataType: 'character', values: resp }, { name: 'seq', dataType: 'numeric', values: seq }, { name: 'txt', dataType: 'character', values: txt }] });
      SM.app.addTable(t);
      return true;
    """, 'the table of the column-property checks')

    # ---- Column Info: Missing Value Codes, typed; the grid, a formula, the engine, the report and its code
    r = await js(page, r"""
      const t = SM.app.tables.find((x) => x.name === 'Props');
      SM.app.showTab(SM.app.tabOf(t));
      const c = t.col('score');
      SM.app.columnInfo(c);
      await T.sleep(60);
      let d = T.dlg();
      const input = d.querySelector('input.smc-codes');
      T.set(input, '999, -1');
      const note = d.querySelector('.smc-note').textContent;
      const labels = [...d.querySelectorAll('.smc-label')].map((l) => l.textContent.trim());
      T.button(d, 'OK').click();
      await T.sleep(60);
      const out = { note, labels, codes: c.missingCodes, miss: c.values.map((v, i) => (Number.isNaN(v) ? i : -1)).filter((i) => i >= 0), stored: t.storedValues(c).filter((v) => v === 999 || v === -1).length };
      await T.sleep(80);
      out.gridCoded = [...document.querySelectorAll('.sm-view:not([hidden]) .sm-grid .sm-cell.coded')].map((x) => x.textContent);
      out.flag = [...document.querySelectorAll('.sm-collist li')].filter((li) => li.querySelector('.sm-colname').textContent === 'score').map((li) => !!li.querySelector('.smc-star'))[0];
      const f = t.addColumn({ name: 'twice', dataType: 'numeric', values: [] });
      SM.formula.apply(t, f, ':score * 2');
      out.formula = f.values.map((v, i) => (Number.isNaN(v) ? i : -1)).filter((i) => i >= 0);
      // what the engine has: the colviewer's N and mean
      const cv = await SM.engine.call('tables.colviewer', { columns: ['score'] }, t);
      const vals = t.storedValues(c).filter((v) => v !== 999 && v !== -1);
      out.engine = [cv.rows[0].n, cv.rows[0].n_missing, T.near(cv.rows[0].mean, T.mean(vals))];
      // Distribution's report and its Python code, run in the page's Python on the CSV (which keeps 999)
      const rep = SM.app.openReport(SM.platforms.get('distribution'), { roles: { y: [c.id] }, options: {} }, t);
      await T.done(rep);
      const sum = [...rep.body.querySelectorAll('.sm-ob')].find((o) => o.querySelector('.sm-ob-head').textContent.trim() === 'Summary Statistics');
      const cells = sum ? [...sum.querySelectorAll('tr')].map((tr) => [...tr.children].map((x) => x.textContent.trim())) : [];
      const nrow = cells.find((x) => x[0] === 'N');
      out.reportN = nrow ? nrow[1] : null;
      const code = [...rep.body.querySelectorAll('details.sm-code code')].map((x) => x.textContent).find((x) => x.includes('pd.read_csv('));
      out.maskLine = code ? code.split('\n').find((l) => l.includes('.mask(')) : null;
      const run = await __gr.run(`${code}\nprint("SMUI-CHECK", df["score"].count(), repr(float(df["score"].mean())))`, t);
      const line = (run.outputs || []).filter((o) => o.type === 'stream').map((o) => o.text).join('').split('\n').find((l) => l.startsWith('SMUI-CHECK'));
      out.codeRun = line ? [Number(line.split(' ')[1]), T.near(Number(line.split(' ')[2]), T.mean(vals))] : (run.outputs || []).map((o) => o.evalue || '').join(' ');
      out.csv999 = SM.io.toCsv(t).split('\r\n').filter((l) => l.startsWith('999,')).length;
      out.errors = [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent);
      SM.app.closeReport(rep);
      t.removeColumn(f.id);
      return out;
    """, 'Missing Value Codes')
    if r:
        check('Column Info has the three property editors, each with an (i)', r['labels'], ['Missing Value Codes', 'Value Labels', 'Profit Matrix'])
        check('the editor counts the cells that hold the codes', r['note'], '4 cells hold these codes: missing to every analysis')
        check('Missing Value Codes 999, -1 typed in Column Info', r['codes'], [999, -1])
        check('those cells are missing to the analyses, and keep their codes', (r['miss'], r['stored']), ([3, 7, 10, 15], 4))
        check('the grid shows them as stored, greyed', r['gridCoded'], ['999', '999', '999', '−1'])
        check('the Columns panel marks the column with properties', r['flag'], True)
        check('a formula sees them as missing', r['formula'], [3, 7, 10, 15])
        check('the engine sees them as missing: N 20, N Missing 4, the mean of the others', r['engine'], [20, 4, True])
        check('Distribution: N leaves them out', r['reportN'], '20')
        check('the report\'s code has the line that makes them missing', r['maskLine'], 'df["score"] = df["score"].mask(df["score"].isin([999, -1]))   # 999, -1 are missing value codes of score (Column Info): missing here, as in the page')
        check('... run on the CSV, which keeps 999, it gives the report\'s N and mean', r['codeRun'], [20, True])
        check('Export CSV keeps the stored 999', r['csv999'], 3)
        check('no errors in the report', r['errors'], [])

    # ---- Value Labels and a Profit Matrix in Column Info; Undo; Save Table and a project ------------
    r = await js(page, r"""
      const t = SM.app.tables.find((x) => x.name === 'Props');
      const g = t.col('grp');
      SM.app.columnInfo(g);
      await T.sleep(60);
      let d = T.dlg();
      T.button(d, 'Add Levels').click();
      const lv = [...d.querySelectorAll('input.smc-lv')].map((i) => i.value);
      const ll = [...d.querySelectorAll('input.smc-ll')];
      T.set(ll[0], 'Low'); T.set(ll[1], 'High');
      T.button(d, 'OK').click();
      await T.sleep(80);
      const out = { lv, pairs: SM.table.labelPairs(g), cell: SM.grid.cellText(g, 1), raw: SM.grid.valueText(g, 1) };
      out.gridText = [...document.querySelectorAll('.sm-view:not([hidden]) .sm-grid .sm-grow')].slice(0, 3).map((row) => row.children[1 + t.colIndex(g)].textContent);
      // a report writes the labels for the levels
      const rep = SM.app.openReport(SM.platforms.get('distribution'), { roles: { y: [g.id] }, options: {} }, t);
      await T.done(rep);
      const fr = [...rep.body.querySelectorAll('.sm-ob')].find((o) => o.querySelector('.sm-ob-head').textContent.trim() === 'Frequencies');
      out.freq = fr ? [...fr.querySelectorAll('tbody tr')].map((tr) => tr.children[0].textContent.trim()) : null;
      SM.app.closeReport(rep);
      // the profit matrix of resp, with Undecided
      const c = t.col('resp');
      SM.app.columnInfo(c);
      await T.sleep(60);
      d = T.dlg();
      const box = [...d.querySelectorAll('.smc-profit')].length;
      const use = [...d.querySelectorAll('label')].find((l) => l.textContent.trim() === 'Use a profit matrix').querySelector('input');
      T.set(use, true);
      const und = [...d.querySelectorAll('label')].find((l) => l.textContent.trim() === 'Undecided decision').querySelector('input');
      T.set(und, true);
      const cells = [...d.querySelectorAll('input.smc-pv')];
      out.start = cells.map((i) => i.value);
      T.set(cells[1], '-5'); T.set(cells[5], '2.5');
      T.button(d, 'OK').click();
      await T.sleep(60);
      out.pm = c.profitMatrix;
      out.aligned = SM.table.profitAligned(t, c);
      SM.app.undo();
      out.undone = c.profitMatrix;
      SM.app.redo();
      out.redone = !!(c.profitMatrix && c.profitMatrix.matrix[0][1] === -5);
      // Save Table and a project: the stored values and every property
      const back = SM.Table.fromJSON(JSON.parse(JSON.stringify(t.toJSON())));
      out.json = [back.col('score').missingCodes, back.storedValues('score').filter((v) => v === 999).length, back.col('score').values.filter(Number.isNaN).length, SM.table.labelOf(back.col('grp'), 2), back.col('resp').profitMatrix.matrix];
      const n0 = SM.app.tables.length;
      SM.app.loadProject({ format: 'smui-project', version: 1, tables: [{ id: 'x', ...t.toJSON(), name: 'Props again' }], reports: [] });
      const p2 = SM.app.tables.slice(n0).find((x) => x.name === 'Props again');
      out.project = p2 ? [p2.col('score').missingCodes, SM.table.labelOf(p2.col('grp'), 1), p2.col('resp').profitMatrix.decisions] : null;
      if (p2) SM.app.closeTable(p2);
      SM.app.showTab(SM.app.tabOf(t));
      // Cols > Column Properties > Missing Value Codes…, the dialog of its own
      const cmd = SM.commands.all().find((x) => x.label === 'Column Properties');
      const items = cmd.submenu(SM.app, t.col('txt'));
      items[0].action();
      await T.sleep(60);
      d = T.dlg();
      out.title = d.querySelector('.sm-dialog-head h2').textContent;
      T.set(d.querySelector('input.smc-codes'), '"c", b');
      T.button(d, 'OK').click();
      await T.sleep(40);
      out.txt = [t.col('txt').missingCodes, t.col('txt').values.slice(0, 3)];
      return out;
    """, 'Value Labels and Profit Matrix')
    if r:
        check('Add Levels: a row for each level', r['lv'], ['1', '2', '3'])
        check('Value Labels typed: 1 Low, 2 High (3 left without)', r['pairs'], [[1, 'Low'], [2, 'High']])
        check('SM.grid.cellText gives the label, valueText the value', (r['cell'], r['raw']), ('Low', '1'))
        check('the grid shows the labels', r['gridText'], ['Low', 'High', '3'])
        check('Distribution\'s Frequencies write the levels with their labels', r['freq'][:3] if r['freq'] else None, ['Low', 'High', '3'])
        check('a new profit matrix: 1 right, -1 wrong, 0 Undecided', r['start'], ['1', '-1', '0', '-1', '1', '0'])
        check('the profit matrix as typed, with Undecided', r['pm'], {'levels': ['no', 'yes'], 'decisions': ['no', 'yes', 'Undecided'], 'matrix': [[1, -5, 0], [-1, 1, 2.5]]})
        check('profitAligned gives it for the levels now', r['aligned'], r['pm'])
        check('Edit > Undo takes Column Info back, Redo brings it again', (r['undone'], r['redone']), (None, True))
        check('Save Table keeps the codes, the stored values, the labels and the profit matrix', r['json'], [[999, -1], 3, 4, 'High', [[1, -5, 0], [-1, 1, 2.5]]])
        check('... and a project too', r['project'], [[999, -1], 'Low', ['no', 'yes', 'Undecided']])
        check('Cols > Column Properties > Missing Value Codes…: its own dialog', r['title'], 'Missing Value Codes: txt')
        check('codes of a character column, one in quotes', r['txt'], [['c', 'b'], ['a', None, None]])

    # ---- Cols > Preselect Role, and a launch dialog that fills it in -------------------------------------------------------------------------
    r = await js(page, r"""
      const t = SM.app.tables.find((x) => x.name === 'Props');
      SM.app.showTab(SM.app.tabOf(t));
      const g = SM.app.grid;
      g.colSel.clear(); g.colSel.add(t.col('score').id); g.refresh();
      const pre = SM.commands.all().find((x) => x.label === 'Preselect Role');
      pre.submenu(SM.app).find((i) => i.label === 'Y').action();
      g.colSel.clear(); g.colSel.add(t.col('grp').id); g.refresh();
      pre.submenu(SM.app).find((i) => i.label === 'X').action();
      g.colSel.clear(); g.refresh(); SM.app.panels.renderColumns();
      const flags = [...document.querySelectorAll('.sm-collist .smc-role')].map((x) => x.textContent);
      SM.app.launch('fitybyx');
      await T.sleep(80);
      const d = T.dlg();
      const roles = Object.fromEntries([...d.querySelectorAll('.sm-role')].map((row) => [row.querySelector('.sm-btn').textContent, [...row.querySelectorAll('.sm-role-list li')].map((li) => li.textContent)]));
      T.button(d.querySelector('.sm-actions'), 'Cancel').click();
      const keep = [t.col('score').preselectRole, t.col('grp').preselectRole];
      const J = t.toJSON().columns.filter((c) => c.preselectRole).map((c) => [c.name, c.preselectRole]);
      for (const nm of ['score', 'grp']) t.setPreselectRole(nm, null);
      return { flags, roles, keep, J };
    """, 'Preselect Role')
    if r:
        check('Preselect Role Y and X: the Columns panel marks them', r['flags'], ['Y', 'X'])
        check('Bivariate Analysis opens with them in their roles', (r['roles'].get('Y, Response'), r['roles'].get('X, Factor')), (['score'], ['grp']))
        check('the roles are kept with the table', (r['keep'], r['J']), (['Y', 'X'], [['score', 'Y'], ['grp', 'X']]))

    # ---- Cols > New Column: several columns at once, in one Undo step; a launch dialog's (i) on its right click and Keep dialog open ------
    r = await js(page, r"""
      const t = SM.app.tables.find((x) => x.name === 'Props');
      SM.app.showTab(SM.app.tabOf(t));
      // from an empty history: a full one (30 steps; closing a report is one too) would not grow
      SM.app.undoStack.length = 0;
      const n0 = t.columns.length, u0 = SM.app.undoStack.length;
      const p = SM.app.newColumn();
      await T.sleep(80);
      let d = T.dlg();
      T.set(T.opt(d, 'Column name'), 'extra'); T.set(T.opt(d, 'Initial values'), 'sequence'); T.set(T.opt(d, 'Number of columns to add'), '3');
      T.ok(d); await p;
      const made = t.columns.slice(n0).map((c) => [c.name, c.values.slice(0, 3)]);
      const steps = SM.app.undoStack.length - u0;
      SM.app.undo();
      const back = t.columns.length === n0;
      SM.app.launch('distribution');
      await T.sleep(100);
      d = T.dlg();
      const info = await T.infoOf(d.querySelector('.sm-dialog-head'));
      T.button(d.querySelector('.sm-actions'), 'Cancel').click();
      return { made, steps, back, dialog: T.names(info, 'The dialog') };
    """, 'New Column: several at once')
    if r:
        check('New Column with Number of columns 3: extra, extra 2, extra 3', r['made'], [['extra', [1, 2, 3]], ['extra 2', [1, 2, 3]], ['extra 3', [1, 2, 3]]])
        check('... in one Undo step', (r['steps'], r['back']), (1, True))
        check('a launch dialog\'s (i) explains the right click, Keep dialog open and preselected roles', r['dialog'], ['A column\'s right click', 'Keep dialog open', 'Preselected roles'])

    # ---- a launch dialog's column list: right click, Transform > Log (the real right click), cast; Keep dialog open -----
    await js(page, "const t = SM.app.tables.find((x) => x.name === 'Props'); for (const c of t.columns) t.setPreselectRole(c.id, null); SM.app.showTab(SM.app.tabOf(t)); SM.app.grid.colSel.clear(); SM.app.launch('distribution'); await T.sleep(100); return true;")
    xy = await page.ev("(() => { const d = T.dlg(); const li = [...d.querySelectorAll('.sm-pick-list li')].find((x) => x.textContent === 'score'); li.scrollIntoView({ block: 'nearest' }); const b = li.getBoundingClientRect(); return [b.x + 20, b.y + b.height / 2]; })()")
    await page.mouse('mouseMoved', xy[0], xy[1])
    await page.mouse('mousePressed', xy[0], xy[1], button='right')
    await page.mouse('mouseReleased', xy[0], xy[1], button='right')
    await asyncio.sleep(0.2)
    r = await js(page, r"""
      const menu = [...document.querySelectorAll('.sm-menu')].pop();
      const items = menu ? [...menu.querySelectorAll('.sm-label')].map((x) => x.textContent) : [];
      T.menuButton('Transform').click();
      await T.sleep(60);
      const sub = [...document.querySelectorAll('.sm-menu')].pop();
      const subItems = [...sub.querySelectorAll('.sm-label')].map((x) => x.textContent);
      const dt = T.menuButton('Date Time');
      T.menuButton('Log').click();
      await T.until(() => SM.app.current.col('Log[score]'));
      await T.sleep(60);
      const d = T.dlg();
      const t = SM.app.current;
      const nc = t.col('Log[score]');
      const sel = [...d.querySelectorAll('.sm-pick-list li.is-selected')].map((li) => li.textContent);
      T.role(d, 'Y, Columns');
      const cast = [...d.querySelectorAll('.sm-role-list li')].map((li) => li.textContent);
      const okLog = nc.values.every((v, i) => { const s = t.col('score').values[i]; return Number.isNaN(s) ? Number.isNaN(v) : T.near(v, Math.log(s)); });
      // Keep dialog open: OK twice, two reports, the dialog still there
      const n0 = SM.app.reports.length;
      const keep = d.querySelector('input.sm-keepopen');
      T.set(keep, true);
      T.ok(d);
      await T.until(() => SM.app.reports.length === n0 + 1);
      const still = !!T.dlg() && T.dlg() === d;
      T.ok(d);
      await T.until(() => SM.app.reports.length === n0 + 2);
      const msg = d.querySelector('.sm-launch-msg').textContent;
      T.button(d.querySelector('.sm-actions'), 'Cancel').click();
      const reps = SM.app.reports.slice(n0);
      for (const rp of reps) await T.done(rp).catch(() => null);
      const titles = reps.map((rp) => rp.spec.roles.y.map((id) => t.col(id).name));
      for (const rp of reps) SM.app.closeReport(rp);
      // the next launch remembers the box, for this visit
      SM.app.launch('distribution'); await T.sleep(80);
      const again = T.dlg().querySelector('input.sm-keepopen').checked;
      T.set(T.dlg().querySelector('input.sm-keepopen'), false);
      T.button(T.dlg().querySelector('.sm-actions'), 'Cancel').click();
      t.removeColumn(nc.id);
      return { items, subItems, dateOff: dt ? dt.disabled : null, formula: nc.formula.expr, sel, cast, okLog, still, msg, titles, again, open: !!T.dlg() };
    """, 'transform from a launch dialog')
    if r:
        check('the list\'s right click: the modeling types, then Transform, Distributional, Date Time', r['items'], ['Continuous', 'Ordinal', 'Nominal', 'Transform', 'Distributional', 'Date Time'])
        check('Transform has Scale Offset', 'Scale Offset…' in r['subItems'], True)
        check('Date Time is off for a column that is not a date', r['dateOff'], True)
        check('Transform > Log makes a formula column, selected in the list', (r['formula'], r['sel']), ('Log(:score)', ['Log[score]']))
        check('its values are the logs of score (a missing value code missing)', r['okLog'], True)
        check('a role\'s button casts it', r['cast'], ['Log[score]'])
        check('Keep dialog open: OK runs the analysis and the dialog stays', (r['still'], r['titles']), (True, [['Log[score]'], ['Log[score]']]))
        check('... and says so', 'Keep dialog open' in r['msg'], True)
        check('the box is kept for the next dialog of the platform', r['again'], True)
        check('the dialogs are closed', r['open'], False)

    # ---- New Formula Column: Date Time, Lag Multiple, Moving Average, Scale Offset ---------------------------------------------------------
    r = await js(page, r"""
      const s = SM.app.openExample('sales');
      const m = s.col('month');
      const menu = SM.tables.nfcItems(SM.app, [m]);
      const dt = menu.find((x) => x.label === 'Date Time').submenu();
      const labels = dt.map((x) => x.label);
      for (const lab of ['Month Abbr.', 'Year Quarter', 'Year Month', 'Day of Week', 'Quarter']) await dt.find((x) => x.label === lab).action();
      await T.until(() => s.col('Quarter[month]'));
      const ab = s.col('Month Abbr.[month]'), yq = s.col('Year Quarter[month]'), ym = s.col('Year Month[month]'), dw = s.col('Day of Week[month]'), q = s.col('Quarter[month]');
      const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      const okAb = m.values.every((v, i) => ab.values[i] === MON[new Date(v).getUTCMonth()]);
      const okYq = m.values.every((v, i) => yq.values[i] === `${new Date(v).getUTCFullYear()} Q${Math.floor(new Date(v).getUTCMonth() / 3) + 1}`);
      const okYm = m.values.every((v, i) => ym.values[i] === new Date(v).toISOString().slice(0, 7));
      const okDw = m.values.every((v, i) => dw.values[i] === new Date(v).getUTCDay() + 1);
      const out = { labels, ab: [ab.modelingType, ab.valueOrder, okAb, s.levels(ab)], yq: [yq.modelingType, okYq, yq.values[0]], ym: [ym.modelingType, okYm], okDw, q: q.values.slice(0, 7) };
      // Lag Multiple, through its dialog
      const row = SM.tables.nfcItems(SM.app, [s.col('sales')]).find((x) => x.label === 'Row').submenu();
      out.row = row.map((x) => x.label);
      const p = row.find((x) => x.label === 'Lag Multiple…').action();
      await T.sleep(80);
      let d = T.dlg(); T.set(T.opt(d, 'First Lag'), '1'); T.set(T.opt(d, 'Last Lag'), '3'); T.ok(d); await p;
      const sv = s.col('sales').values;
      out.lags = [1, 2, 3].map((k) => { const c = s.col(`Lag ${k}[sales]`); return !!c && c.values.every((v, i) => (i < k ? Number.isNaN(v) : v === sv[i - k])) && c.formula.expr === `Lag(:sales, ${k})`; });
      SM.app.undoStack.length = 0;   // from an empty history: a full one would not grow
      const u0 = SM.app.undoStack.length;
      // Moving Average: equal weights over the two rows before and this one
      const p2 = row.find((x) => x.label === 'Moving Average…').action();
      await T.sleep(80);
      d = T.dlg(); T.set(T.opt(d, 'Items Before'), '2'); T.ok(d); await p2;
      const ma = s.col('Moving Average[sales]');
      out.ma = [ma.formula.expr, ma.values.every((v, i) => { const w = sv.slice(Math.max(0, i - 2), i + 1); return T.near(v, w.reduce((a, b) => a + b, 0) / w.length); })];
      // Scale Offset: Fahrenheit from Celsius
      const tr = SM.tables.nfcItems(SM.app, [s.col('temperature')]).find((x) => x.label === 'Transform').submenu();
      const p3 = tr.find((x) => x.label === 'Scale Offset…').action();
      await T.sleep(80);
      d = T.dlg(); T.set(T.opt(d, 'Scale'), '1.8'); T.set(T.opt(d, 'Offset'), '32'); T.ok(d); await p3;
      const so = s.col('Scale Offset[temperature]'), tv = s.col('temperature').values;
      out.so = [so.formula.expr, so.values.every((v, i) => T.near(v, tv[i] * 1.8 + 32))];
      // one Undo step for all three lags
      out.undo = SM.app.undoStack.length - u0;
      SM.app.closeTable(s);
      return out;
    """, 'New Formula Column: Date Time, Lag Multiple, Moving Average, Scale Offset')
    if r:
        check('Date Time: Year, Quarter, Month, Month Abbr., Day, Day of Week, Hour, Year Quarter, Year Month', r['labels'], ['Year', 'Quarter', 'Month', 'Month Abbr.', 'Day', 'Day of Week', 'Hour', 'Year Quarter', 'Year Month'])
        check('Month Abbr.: nominal, Jan to Dec in the calendar\'s order', r['ab'], ['nominal', ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], True, ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']])
        check('Year Quarter: ordinal text, 2016 Q1', r['yq'], ['ordinal', True, '2016 Q1'])
        check('Year Month: ordinal text, as 2016-01', r['ym'], ['ordinal', True])
        check('Day of Week: 1 for Sunday', r['okDw'], True)
        check('Quarter', r['q'], [1, 1, 1, 2, 2, 2, 3])
        check('Row has Lag Multiple and Moving Average', [x for x in r['row'] if x in ('Lag', 'Lag Multiple…', 'Moving Average…')], ['Lag', 'Lag Multiple…', 'Moving Average…'])
        check('Lag Multiple 1 to 3: three lag columns', r['lags'], [True, True, True])
        check('Moving Average, two rows before: Col Moving Average and its values', r['ma'], ['Col Moving Average(:sales, 1, 2, 0, 0)', True])
        check('Scale Offset 1.8, 32', r['so'], [':temperature * 1.8 + 32', True])
        check('each made in one Undo step', r['undo'], 2)

    # ---- Subset: equal counts per level (with replacement when short), selection probabilities and sampling weights ------------------
    r = await js(page, r"""
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      const sx = t.col('sex').values;
      const N = { F: sx.filter((v) => v === 'F').length, M: sx.filter((v) => v === 'M').length };
      T.cmd('Tables', 'Subset…');
      await T.sleep(80);
      let d = T.dlg();
      T.set(T.opt(d, 'Rows'), 'balanced');
      T.set(T.opt(d, 'Sample size'), '40');
      T.ok(d);
      const refused = d.querySelector('.sm-launch-msg').textContent;
      T.cast(d, ['sex'], 'Stratify');
      T.set(T.opt(d, 'Save selection probabilities'), true);
      T.set(T.opt(d, 'Save sampling weights'), true);
      T.set(T.opt(d, 'Seed'), 'balanced');
      const n0 = SM.app.tables.length;
      T.ok(d);
      const nt = await T.newTable(n0);
      const s2 = nt.col('sex').values, w = nt.col('Sampling Weight').values, p = nt.col('Selection Probability').values, id = nt.col('id').values;
      const cnt = { F: s2.filter((v) => v === 'F').length, M: s2.filter((v) => v === 'M').length };
      const byLevel = (lv) => s2.map((v, i) => (v === lv ? i : -1)).filter((i) => i >= 0);
      const okW = ['F', 'M'].every((lv) => byLevel(lv).every((i) => T.near(w[i], N[lv] / 40) && T.near(p[i], 40 / N[lv])));
      const everyRow = ['F', 'M'].every((lv) => new Set(byLevel(lv).map((i) => id[i])).size === N[lv]);
      const sumW = ['F', 'M'].map((lv) => byLevel(lv).reduce((a, i) => a + w[i], 0));
      // stratified by rate: weights are N_h / n_h (of Students again: the new table is the current one now)
      SM.app.showTab(SM.app.tabOf(t));
      T.cmd('Tables', 'Subset…');
      await T.sleep(80);
      d = T.dlg();
      T.set(T.opt(d, 'Rows'), 'rate'); T.set(T.opt(d, 'Sampling rate'), '0.3');
      T.cast(d, ['sex'], 'Stratify');
      T.set(T.opt(d, 'Save sampling weights'), true);
      const n1 = SM.app.tables.length;
      T.ok(d);
      const nt2 = await T.newTable(n1);
      const s3 = nt2.col('sex').values, w3 = nt2.col('Sampling Weight').values;
      const okRate = ['F', 'M'].every((lv) => { const k = Math.round(0.3 * N[lv]); return s3.filter((v) => v === lv).length === k && s3.every((v, i) => v !== lv || T.near(w3[i], N[lv] / k)); });
      const noProb = !nt2.col('Selection Probability');
      const dbg = [nt2.name, nt2.nrows, nt2.columns.map((c) => c.name).join('|'), s3.join(''), w3.slice(0, 4)];
      SM.app.closeTable(nt); SM.app.closeTable(nt2);
      return { refused, N, cnt, okW, everyRow, sumW, okRate, noProb, dbg };
    """, 'Subset: balanced sampling and weights')
    if r:
        check('equal counts per level needs Stratify', r['refused'].startswith('Random: equal counts per level takes its levels from the Stratify columns'), True)
        check('equal counts per level: 40 rows of each sex', r['cnt'], {'F': 40, 'M': 40})
        check('a short level gives every one of its rows, the rest again with replacement', r['everyRow'], True)
        check('Sampling Weight N/40 and Selection Probability 40/N for each level', r['okW'], True)
        check('the weights of a level add up to its rows in the table', r['sumW'], [r['N']['F'], r['N']['M']])
        check('stratified by rate 0.3: weight N/n of each level', (r['okRate'], r['noProb']), (True, True)) or print('   ', r['dbg'])

    # ---- Recode: tick values and Group them; Group Similar Values a character apart ------------------------------------------------------
    r = await js(page, r"""
      const vals = ['New York', 'new york', 'Nwe York', 'Boston', 'Bostn', 'Boston', 'Chicago', 'Chicgo', 'Paris', 'Pairs', 'Rome'];
      const t = new SM.Table({ name: 'Cities', columns: [{ name: 'city', dataType: 'character', values: vals }] });
      SM.app.addTable(t);
      T.cmd('Cols', 'Recode…', t.col('city'));
      await T.sleep(60);
      let d = T.dlg();
      const row = (text) => [...d.querySelectorAll('.smr-table tbody tr')].find((tr) => tr.children[1].textContent === text);
      row('Paris').querySelector('.smr-pick').click();
      row('Rome').querySelector('.smr-pick').click();
      const groupOn = !T.button(d, 'Group').disabled;
      T.button(d, 'Group').click();
      const afterGroup = [...d.querySelectorAll('.smr-table tbody tr')].map((tr) => [tr.children[1].textContent, tr.querySelector('.smr-new').value]);
      // Group Similar Values, at most one character apart, for values of 4 characters or more
      T.set(d.querySelector('input[aria-label="Max character difference"]'), '1');
      T.button(d, 'Group Similar Values').click();
      const sim1 = [...d.querySelectorAll('.smr-table tbody tr')].map((tr) => tr.querySelector('.smr-new').value);
      T.set(d.querySelector('input[aria-label="Max character difference"]'), '2');
      T.button(d, 'Group Similar Values').click();
      const sim2 = [...d.querySelectorAll('.smr-table tbody tr')].map((tr) => tr.querySelector('.smr-new').value);
      T.ok(d, 'Recode');
      await T.sleep(40);
      const c2 = t.col('city 2');
      const ed = [SM.tables.editDistance('kitten', 'sitting'), SM.tables.editDistance('Nwe York', 'New York'), SM.tables.editDistance('abc', 'abc'), SM.tables.editDistance('abcdef', 'x', 2)];
      SM.app.closeTable(t);
      return { groupOn, afterGroup, sim1, sim2, levels: c2 ? [...new Set(c2.values)] : null, ed };
    """, 'Recode: Group and Group Similar Values')
    if r:
        check('ticking two values turns Group on', r['groupOn'], True)
        check('Group: the ticked values take one value, the commonest\'s (Paris and Rome: Paris, the first of the most common)', [x for x in r['afterGroup'] if x[0] in ('Paris', 'Rome')], [['Paris', 'Paris'], ['Rome', 'Paris']])
        check('Group Similar Values, at most 1 character apart: new york (case), Bostn, Chicgo join theirs; Nwe York and Pairs (2 apart) do not', r['sim1'], ['Boston', 'Boston', 'Chicago', 'Chicago', 'New York', 'New York', 'Nwe York', 'Pairs', 'Paris', 'Paris'])
        check('... at most 2 apart: they join too, the spelling with the most rows winning (Paris, with Rome grouped to it)', r['sim2'], ['Boston', 'Boston', 'Chicago', 'Chicago', 'New York', 'New York', 'New York', 'Paris', 'Paris', 'Paris'])
        check('the edit distance (Levenshtein): kitten–sitting 3, a swap 2', r['ed'], [3, 2, 0, 3])
        check('Recode with the groups: the new column\'s values', r['levels'], ['New York', 'Boston', 'Chicago', 'Paris'])


    # ---- the grid: Fill from a cell's right click (the real one), Header Graphs by the real button ----------------------------------
    r = await js(page, r"""
      const t = SM.app.tables.find((x) => x.name === 'Props');
      SM.app.showTab(SM.app.tabOf(t));
      await T.sleep(120);
      t.select([0, 1]);
      await T.sleep(60);
      const row = [...document.querySelectorAll('.sm-view:not([hidden]) .sm-grid .sm-grow')].find((x) => x.dataset.row === '1');
      const cell = row.children[1 + t.colIndex('seq')];
      cell.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      const b = cell.getBoundingClientRect();
      return [b.x + b.width / 2, b.y + b.height / 2];
    """, 'a cell to fill')
    if r:
        await page.mouse('mouseMoved', r[0], r[1])
        await page.mouse('mousePressed', r[0], r[1], button='right')
        await page.mouse('mouseReleased', r[0], r[1], button='right')
        await asyncio.sleep(0.2)
    r = await js(page, r"""
      const t = SM.app.tables.find((x) => x.name === 'Props');
      const first = [...document.querySelectorAll('.sm-menu')].pop();
      const top = first ? [...first.querySelectorAll('.sm-label')].map((x) => x.textContent).slice(0, 2) : [];
      T.menuButton('Fill').click();
      await T.sleep(60);
      const sub = [...document.querySelectorAll('.sm-menu')].pop();
      const items = [...sub.querySelectorAll('button')].map((x) => [x.querySelector('.sm-label').textContent, x.disabled]);
      T.menuButton('Continue Sequence to End of Table').click();
      await T.sleep(60);
      const seq = t.col('seq').values.slice();
      SM.app.undo();
      const undone = t.col('seq').values.slice(0, 4);
      // repeat a sequence of text, and fill to a row
      t.select([0, 1, 2]);
      SM.app.grid.fill(t.col('txt'), 'repeat', t.nrows - 1);
      const rep = t.storedValues('txt');      // (b and c are its missing value codes now: stored, and missing)
      t.select([0]);
      const p = SM.app.grid.fillToRow(t.col('grp'));
      await T.sleep(60);
      const d = T.dlg(); T.set(T.opt(d, 'Fill down to row'), '5'); T.ok(d); await p;
      const grp = t.col('grp').values.slice(0, 7);
      // a formula column fills itself
      const f = t.addColumn({ name: 'f', dataType: 'numeric', values: [] }); SM.formula.apply(t, f, 'Row()');
      const fz = SM.app.grid.fillItems(t.colIndex(f)).every((x) => x.disabled);
      t.removeColumn(f.id);
      t.select([]);
      return { top, items, seq, undone, rep, grp, fz };
    """, 'Fill')
    if r:
        check('a cell\'s right click starts with Fill', r['top'][0], 'Fill')
        check('Fill\'s items', [x[0] for x in r['items']], ['Fill to Row…', 'Fill to End of Table', 'Repeat Sequence to End of Table', 'Continue Sequence to End of Table'])
        check('Continue Sequence: 1, 2 go on 3, 4, … to the last row', r['seq'], list(range(1, 25)))
        check('Edit > Undo takes the fill back', r['undone'][:2] + [None if x != x else x for x in r['undone'][2:]], [1, 2, None, None])
        check('Repeat Sequence of text: a, b, c, a, b, c, …', r['rep'], ['a', 'b', 'c'] * 8)
        check('Fill to Row 5: the value down to row 5', r['grp'], [1, 1, 1, 1, 1, 3, 1])
        check('a formula column is not filled', r['fz'], True)
    xy = await page.ev("(() => { const b = [...document.querySelectorAll('.sm-view:not([hidden]) .sm-graphbtn')][0]; const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    await page.click(xy[0], xy[1])
    await asyncio.sleep(0.3)
    r = await js(page, r"""
      const t = SM.app.tables.find((x) => x.name === 'Props');
      const v = document.querySelector('.sm-view:not([hidden])');
      const head = v.querySelector('.sm-grid-head');
      const graphs = [...head.querySelectorAll('.sm-hcell')].map((h) => ({ name: h.querySelector('.sm-hname').textContent, bars: h.querySelectorAll('.sm-hgraph-bar').length, title: (h.querySelector('.sm-hgraph title') || {}).textContent || '' }));
      const pressed = v.querySelector('.sm-graphbtn').getAttribute('aria-pressed');
      const top = v.querySelector('.sm-grid-rows').style.top;
      const d = SM.app.grid.graphData(t.col('score'));
      const vals = t.col('score').values.filter(Number.isFinite);
      t.select([0, 1, 2, 4]);
      await T.sleep(100);
      const sel = [...head.querySelectorAll('.sm-hcell')].map((h) => h.querySelectorAll('.sm-hgraph-sel').length);
      const d2 = SM.app.grid.graphData(t.col('grp'));
      const selScore = SM.app.grid.graphData(t.col('score')).sel.reduce((a, b) => a + b, 0);
      t.select([]);
      await T.sleep(60);
      const grpCount = [1, 2, 3].map((k) => t.col('grp').values.filter((v) => v === k).length);
      return { graphs, pressed, top, sel, all: d.all.reduce((a, b) => a + b, 0), n: vals.length, k: d.k, grpAll: d2.all, grpCount, grpSel: d2.sel, selScore, withHead: head.classList.contains('with-graphs') };
    """, 'Header Graphs')
    if r:
        check('Header Graphs: the button pressed, the headings taller', (r['pressed'], r['withHead'], r['top']), ('true', True, '72px'))
        check('a graph under every heading', [g['name'] for g in r['graphs']], ['score', 'grp', 'resp', 'seq', 'txt'])
        check('a histogram of score: its bars count every value that is not missing (the codes left out)', (r['all'], r['n']), (20, 20))
        check('its title says what it shows', r['graphs'][0]['title'].startswith('score: a histogram of 20 values'), True)
        check('grp: a bar per level, its rows counted', (r['graphs'][1]['bars'], r['grpAll']), (3, r['grpCount']))
        check('selected rows drawn darker: the four selected rows in score\'s bars, a bar over each of their levels of grp and resp', (r['selScore'], r['sel'][1:3]), (4, [len([x for x in r['grpSel'] if x]), 2]))
    await page.click(xy[0], xy[1])
    await asyncio.sleep(0.2)
    off = await page.ev("(() => { const v = document.querySelector('.sm-view:not([hidden])'); return [v.querySelector('.sm-graphbtn').getAttribute('aria-pressed'), v.querySelectorAll('.sm-hgraph').length, v.querySelector('.sm-grid-rows').style.top]; })()")
    check('Header Graphs off again', off, ['false', 0, '26px'])

    # ---- Tabulate: a continuous column in bins and by its levels; Show Chart ------------------------------------------------------------
    r = await js(page, r"""
      const t = SM.app.tables[0]; SM.app.showTab(SM.app.tabOf(t));
      const h = t.col('height (cm)'), w = t.col('weight (kg)'), a = t.col('age');
      const rep = SM.app.openReport(SM.platforms.get('tabulate'), { roles: {}, options: { tab: { rows: [[{ id: h.id, name: h.name, as: 'bins', bins: 5 }]], cols: [], analysis: [{ id: w.id, name: w.name }], stats: ['N', 'Mean'], quantiles: [25, 75] } } }, t);
      await T.done(rep);
      const read = () => { const tbl = rep.body.querySelector('table.smt-table'); return [...tbl.querySelectorAll('tbody tr')].map((tr) => [...tr.children].map((c) => c.textContent)); };
      const rows1 = read();
      // the bins by hand: Make Binning Column's equal widths
      const b = SM.tables.binCuts(h.values, { method: 'width', k: 5 });
      const hv = h.values, wv = w.values;
      const bin = (x) => { let i = 0; while (i < b.cuts.length && x >= b.cuts[i]) i++; return i; };
      const want = []; for (let i = 0; i <= b.cuts.length; i++) { const ws = wv.filter((_, k) => Number.isFinite(hv[k]) && bin(hv[k]) === i && Number.isFinite(wv[k])); if (ws.length) want.push([String(ws.length), ws.reduce((x, y) => x + y, 0) / ws.length]); }
      const okBins = rows1.length === want.length && rows1.every((r, i) => r[1] === want[i][0] && T.near(Number(r[2].replace('−', '-')), want[i][1], 1e-6));
      const chip = rep.body.querySelector('.smt-chip-cont');
      const chipText = chip ? chip.textContent : null;
      // its right click: by its levels
      chip.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 50, clientY: 50 }));
      await T.sleep(40);
      const p = T.done(rep);
      T.menuButton('Group by Its Levels').click();
      await p;
      const rows2 = read();
      const distinct = [...new Set(hv.filter(Number.isFinite))].length;
      // Show Chart, from the red triangle's item
      const p2 = T.done(rep);
      rep.spec.options.chart = true; rep.run();
      await p2;
      const cells = [...rep.body.querySelectorAll('table.smt-table td.smt-barcell')];
      const bars = cells.map((c) => Number(c.dataset.bar));
      const codes = [...rep.body.querySelectorAll('details.sm-code')].length;
      const tri = rep.platform.triangle(rep.ctxFor ? rep.ctxFor() : { check: (l) => ({ label: l }), opt: () => null, table: t, set: () => null, report: rep }).map((x) => x && x.label);
      SM.app.closeReport(rep);
      return { rows1n: rows1.length, labels: rows1.map((r) => r[0]), cutLabels: b.cuts.length + 1, okBins, chipText, rows2: rows2.length, distinct, cells: cells.length, max: Math.max(...bars), codes, tri };
    """, 'Tabulate: bins, levels, Show Chart')
    if r:
        check('a continuous column in bins: a row per bin with rows, N and Mean by hand', r['okBins'], True)
        check('the bins are labelled by their ranges', all(' - ' in x for x in r['labels']), True)
        check('its chip says how it groups', r['chipText'], 'height (cm) (5 bins)×')
        check('Group by Its Levels: a row per distinct value', r['rows2'], r['distinct'])
        check('Show Chart: a bar in every cell, the largest of each column at 100%', (r['cells'], r['max']), (2 * r['distinct'], 100))
        check('... with the code that draws the bars under the table\'s', r['codes'], 2)
        check('Show Chart is in the red triangle', 'Show Chart' in r['tri'], True)

    # ---- Explore Missing Values: Missing Value Clustering (and its code, run), SVD imputation, shrinkage -------------------------------
    r = await js(page, r"""
      const m = SM.app.tables.find((x) => x.name === 'Students with gaps');
      SM.app.showTab(SM.app.tabOf(m));
      const P = SM.platforms.get('missing');
      const ids = ['sex', 'height (cm)', 'weight (kg)'].map((n) => m.col(n).id);
      const rep = SM.app.openReport(P, { roles: { y: ids }, options: { clustering: true } }, m);
      await T.done(rep);
      const g = await __gr.graphs(rep);
      const cl = g.find((x) => x.label === 'Missing value clustering');
      const heat = cl ? cl.traces.find((x) => x.type === 'heatmap') : null;
      const pats = [...rep.body.querySelectorAll('.sm-ob')].find((o) => o.querySelector('.sm-ob-head').textContent.trim() === 'Missing Value Report');
      const npat = pats ? pats.querySelectorAll('tbody tr').length : null;
      const plot = rep.plots.find((p) => p.opts.title === 'Missing value clustering');
      // a click on a pattern selects its rows
      const gd = plot.box;
      gd.emit('plotly_click', { points: [{ data: { type: 'heatmap' }, pointIndex: [0, 0], y: 0 }], event: {} });
      const sel = m.selectedRows();
      const mc = await SM.engine.call('tables.missing_clustering', { columns: ['sex', 'height (cm)', 'weight (kg)'], rows: rep.ctxRows || null }, m);
      const run = await __gr.run(cl.code, m);
      const errs = (run.outputs || []).filter((o) => o.type === 'error').map((o) => `${o.ename}: ${o.evalue}`);
      const figs = (run.outputs || []).filter((o) => o.type === 'display' || o.type === 'image' || (o.data && (o.data['image/svg+xml'] || o.data['image/png']))).length;
      m.select([]);
      // SVD imputation from the Impute menu, as new columns
      T.button(rep.body, 'Impute ▾').click();
      T.menuButton('Multivariate SVD Imputation').click();
      await T.sleep(100);
      let f = T.dlg();
      const svdFields = [...f.querySelectorAll('.sm-form > label')].map((l) => l.textContent);
      // (the columns an imputation adds: the table may have Imputed[x] columns from before)
      let had = new Set(m.columns.map((c) => c.id));
      const added = () => m.columns.filter((c) => !had.has(c.id));
      T.set(T.opt(f, 'Save'), 'new'); T.ok(f);
      await T.until(() => added().length === 2);
      const svdOk = added().every((c) => c.values.every(Number.isFinite));
      const svdNote = added()[1].notes;
      for (const c of added()) m.removeColumn(c.id);
      // multivariate normal, the covariances shrunk automatically
      T.button(rep.body, 'Impute ▾').click();
      T.menuButton('Multivariate Normal Imputation').click();
      await T.sleep(100);
      f = T.dlg();
      had = new Set(m.columns.map((c) => c.id));
      T.set(T.opt(f, 'Save'), 'new'); T.set(T.opt(f, 'Shrink the covariances'), 'auto'); T.ok(f);
      await T.until(() => added().length === 2);
      const shrinkNote = added()[1].notes;
      const mvnOk = added().every((c) => c.values.every(Number.isFinite));
      for (const c of added()) m.removeColumn(c.id);
      const tri = [...rep.body.querySelectorAll('.sm-ob-head')].map((h) => h.textContent.trim());
      SM.app.closeReport(rep);
      return { found: !!cl, rowsZ: heat ? heat.z.length : null, npat, colsZ: heat ? heat.z[0].length : null, codeLast: cl && cl.code ? cl.code.trim().split('\n').pop() : null, sel, rows0: mc.patterns[0].rows, errs, figs, svdFields, svdOk, svdNote, shrinkNote, mvnOk, tri };
    """, 'Missing Value Clustering, SVD and shrinkage')
    if r:
        check('Missing Value Clustering: a heat map, a row per pattern (as the Missing Value Report counts them), a column per column', (r['found'], r['rowsZ'], r['colsZ']), (True, r['npat'], 3))
        check('its code is under it, ending in plt.show()', r['codeLast'], 'plt.show()')
        check('... and runs in the page\'s Python, drawing a figure', (r['errs'], r['figs'] >= 1), ([], True))
        check('a click on a pattern selects its rows', r['sel'], sorted(r['rows0']))
        check('Multivariate SVD Imputation\'s dialog: rank, iterations, shrinkage', [x for x in r['svdFields'] if x in ('Number of singular vectors', 'Maximum iterations', 'Shrinkage (soft-impute)')], ['Number of singular vectors', 'Maximum iterations', 'Shrinkage (soft-impute)'])
        check('SVD imputation fills the columns and says its rank', (r['svdOk'], 'Multivariate SVD, rank 1' in r['svdNote']), (True, True))
        check('multivariate normal with the covariances shrunk: filled, λ in the note', (r['mvnOk'], 'covariances shrunk by λ = ' in r['shrinkNote']), (True, True))

    # ---- File > Import Multiple Files: files dropped on its dialog; a folder's paths; binary files left out ---------------------------------
    r = await js(page, r"""
      const mk = (name, text, path) => { const f = new File([text], name, { type: 'text/plain', lastModified: Date.UTC(2026, 0, 2) }); if (path) Object.defineProperty(f, 'webkitRelativePath', { value: path }); return f; };
      const files = [mk('b.txt', 'second file\nwith two lines'), mk('a.txt', 'the first'), mk('bin.txt', 'x\u0000y'), mk('skip.dat', 'no')];
      const r1 = await SM.io.filesTable(files, { filter: '*.txt', sizes: true, dates: true });
      const t1 = r1.table;
      const folder = await SM.io.filesTable([mk('x.txt', 'one', 'docs/x.txt'), mk('y.txt', 'two', 'docs/sub/y.txt')]);
      // the dialog: files dropped on it, Import
      const n0 = SM.app.tables.length;
      T.cmd('File', 'Import Multiple Files…');
      await T.sleep(80);
      const d = T.dlg();
      const dt = new DataTransfer(); for (const f of files) dt.items.add(f);
      d.querySelector('.smt-form').dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
      const note = d.querySelector('.smi-files').textContent;
      T.set(T.opt(d, 'Output table name'), 'Letters');
      T.button(d, 'Import').click();
      const nt = await T.newTable(n0);
      const out = { names: t1.col('File Name').values, text: t1.col('Text').values, cols: t1.columns.map((c) => c.name), size: t1.col('Size (bytes)').values, date: t1.col('Date Modified').values[0] === Date.UTC(2026, 0, 2), fmt: t1.col('Date Modified').format.kind, notes: t1.notes,
        folder: [folder.table.columns.map((c) => c.name), folder.table.col('Path').values], note, dialog: [nt.name, nt.nrows, nt.col('File Name').values] };
      SM.app.closeTable(nt);
      return out;
    """, 'Import Multiple Files')
    if r:
        check('a row per text file, in name order, the filter applied', r['names'], ['a.txt', 'b.txt'])
        check('each file\'s whole text', r['text'], ['the first', 'second file\nwith two lines'])
        check('File Name, Text, and the size and date when asked', (r['cols'], r['size'], r['date'], r['fmt']), (['File Name', 'Text', 'Size (bytes)', 'Date Modified'], [9, 26], True, 'datetime'))
        check('a file that is not text is left out, and the table\'s notes say so', 'bin.txt (not text)' in r['notes'], True)
        check('from a folder: a Path column with where each file is', r['folder'], [['File Name', 'Path', 'Text'], ['docs/sub/y.txt', 'docs/x.txt']])
        check('the dialog counts the files dropped on it and the ones the filter takes', r['note'], '4 files chosen, 3 matching the filter (< 0.1 MB)')
        check('Import makes the table', r['dialog'], ['Letters', 2, ['a.txt', 'b.txt']])

    # ---- the new parts in the dark theme and at phone width ----------------------------------------------------------------------------
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await js(page, "const t = SM.app.tables.find((x) => x.name === 'Props'); SM.app.showTab(SM.app.tabOf(t)); SM.app.grid.setGraphs(true); SM.app.columnInfo(t.col('resp')); await T.sleep(150); const d = T.dlg(); T.set([...d.querySelectorAll('label')].find((l) => l.textContent.trim() === 'Use a profit matrix').querySelector('input'), true); return true;")
    await asyncio.sleep(0.4)
    await shot(page, 't10-colprops-dark.png')
    dark = await page.ev("""(() => { const d = [...document.querySelectorAll('.sm-dialog')].pop(); const inp = d.querySelector('input.smc-pv'); const cs = getComputedStyle(inp); const h = document.querySelector('.sm-view:not([hidden]) .sm-hgraph-bar'); return [cs.backgroundColor !== 'rgb(255, 255, 255)', cs.color !== 'rgb(0, 0, 0)', !!h && getComputedStyle(h).fill !== 'rgb(0, 0, 0)']; })()""")
    check('dark theme: the profit matrix\'s cells and the header graphs take the dark colours', dark, [True, True, True])
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.6)
    ph = await page.ev("""(() => { const d = [...document.querySelectorAll('.sm-dialog')].pop(); const b = d.querySelector('.sm-dialog-body'); return [document.documentElement.scrollWidth <= innerWidth + 1, d.getBoundingClientRect().width <= innerWidth + 1, b.scrollWidth <= b.clientWidth + 2]; })()""")
    check('phone width: Column Info with its property editors fits the screen, without a sideways scroll', ph, [True, True, True])
    await shot(page, 't11-colprops-phone.png')
    await page.ev("T.button(T.dlg(), 'Cancel').click()")
    await asyncio.sleep(0.3)
    wide = await page.ev('document.documentElement.scrollWidth <= innerWidth + 1')
    check('phone width: the grid with Header Graphs, no sideways page scroll', wide, True)
    await shot(page, 't12-headergraphs-phone.png')
    await page.ev("SM.app.grid.setGraphs(false); try { localStorage.removeItem('smui.headerGraphs'); } catch (e) {}")
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await asyncio.sleep(0.4)
    check('no script errors in the new parts', page.errors, [])

# ---- Explore Missing Values: the snapshot's matplotlib code --------------------------------------------------------
# The block under the snapshot runs in the page's own Python (the notebook's runner): a mark for each
# missing cell of the report's rows at its row number and column, as the Plotly graph has them; with
# By groups and excluded rows the block keeps each group's rows and drops the excluded ones, and so
# does the report's own code.
async def snapshot_code(page):
    await page.ev(GRAPHS_JS)
    r = await js(page, r'''
      const m = SM.app.tables.find((x) => x.name === 'Students with gaps');
      SM.app.showTab(SM.app.tabOf(m));
      const P = SM.platforms.get('missing');
      const ids = (names) => names.map((n) => m.col(n).id);
      const rep = SM.app.openReport(P, { roles: { y: ids(['sex', 'height (cm)', 'weight (kg)']) }, options: {} }, m);
      await T.done(rep);
      const g1 = await __gr.graphs(rep);
      const sx = m.col('sex').values, ex = [sx.indexOf('F'), sx.indexOf('M'), 30];   // a row of each group, and one with a gap
      m.setState(ex, 'excluded', true);
      const rep2 = SM.app.openReport(P, { roles: { y: ids(['height (cm)', 'weight (kg)']), by: ids(['sex']) }, options: {} }, m);
      await T.done(rep2);
      const g2 = await __gr.graphs(rep2);
      const code2 = [...rep2.body.querySelectorAll('details.sm-code code')].map((c) => c.textContent);
      m.setState(ex, 'excluded', false);
      const out = { g1, g2, code2, undrawn: __gr.take(), errors: [rep, rep2].flatMap((x) => [...x.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent)) };
      SM.app.closeReport(rep); SM.app.closeReport(rep2);
      return out;
    ''', 'the snapshot\'s code')
    if not r:
        return
    check('the snapshot\'s code: no errors, every graph drawn', (r['errors'], r['undrawn']), ([], []))
    check('the snapshot\'s code: a snapshot in the report, one in each By group (F, M)', [g['label'] for g in r['g1'] + r['g2']], ['Missing value snapshot'] * 3)
    for g in r['g1'] + r['g2']:
        check('the snapshot\'s code: its block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
    for i, g in enumerate(r['g1'] + r['g2']):
        lab = 'the snapshot\'s code' + (' (every row)' if i == 0 else f' (By group {i}, rows excluded)')
        F, err = await run_graph(page, g, "SM.app.tables.find((x) => x.name === 'Students with gaps')")
        check(f'{lab}: runs in the page', err, None)
        if not F:
            continue
        F = F[0]
        ax = F['axes'][0]
        got = ax['scatter'][0]['xy'] if ax['scatter'] else []
        check(f'{lab}: a mark for each missing cell, at its column and row number', [tuple(p) for p in got], [tuple(p) for p in points_of(g['traces'][0])])
        check(f'{lab}: square marks in the text colour', (ax['scatter'][0]['colors'][0][:7] if ax['scatter'] else None), '#352921')
        check(f'{lab}: the columns on the axis, the first row at the top', ([t for t in ax['xticklabels'] if t], ax['yinverted']), (g['ticks'], True))
        check(f'{lab}: the titles and the size', (ax['title'], ax['ylabel'], F['size']), (g['label'], g['titles']['y'], [g['w'] / 100, g['h'] / 100]))
        if i:
            check(f'{lab}: the block keeps the group and drops the excluded rows', ('df = df[df["sex"] == ' in g['code'], 'df = df.drop(index=[' in g['code']), (True, True))
    reports = [c for c in r['code2'] if 'd.isna().sum()' in c]
    check('the Missing Value Report\'s code keeps each group\'s rows and drops the excluded ones', (len(reports), all('df = df[df["sex"] == ' in c and 'df = df.drop(index=[' in c for c in reports)), (2, True))


asyncio.run(main())
sys.exit(check.done())
