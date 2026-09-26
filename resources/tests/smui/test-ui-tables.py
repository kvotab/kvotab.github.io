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
    menus = await page.ev('JSON.stringify(["Tables", "Cols", "Analyze", "File"].map(m => SM.app.menuItems(m).map(i => i.label || "—")))')
    tables, cols, analyze, filem = json.loads(menus)
    check('the Tables menu', tables, ['Summary…', 'Subset…', 'Sort…', 'Stack…', 'Split…', 'Transpose…', 'Concatenate…', 'Join…', 'Update…', '—', 'Missing Data Pattern…'])
    check('the Cols menu has Formula, New Formula Column, Recode, Columns Viewer and Utilities', [c for c in cols if c in ('Formula…', 'New Formula Column', 'Recode…', 'Columns Viewer', 'Utilities')], ['Formula…', 'New Formula Column', 'Recode…', 'Columns Viewer', 'Utilities'])
    check('Analyze has Tabulate after Distribution', analyze.index('Tabulate') > analyze.index('Distribution…'), True)
    check('File has Python Script…', 'Python Script…' in filem, True)

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
      T.cmd('File', 'Python Script…');
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await T.done(rep);
      const warnHidden = rep.body.querySelector('.sm-ob-warn').hidden;
      const ta = rep.body.querySelector('textarea.smp-code');
      T.set(ta, 'print(df.shape, df["sex"].dtype)\nresult = df.groupby("sex", observed=True)["height (cm)"].mean().reset_index()');
      // Tab indents
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
      return { warnHidden, indented, dedented, out, want: `(${t.nrows}, ${t.columns.length}) category`, made: [made.name, made.columns.map((c) => c.name), made.col('sex').modelingType, made.nrows], err, warn2, ran };
    ''', 'Python script')
    if r:
        check('a script opened from the menu has no warning', r['warnHidden'], True)
        check('Tab indents and shift+Tab dedents', (r['indented'], r['dedented']), (True, True))
        check('Run shows what the script prints', r['out'].strip(), r['want'])
        check('result becomes a data table', r['made'], ['Python result', ['sex', 'height (cm)'], 'nominal', 2])
        check('an error shows with its line', 'IndexError: list index out of range (line 2)' in r['err'], True)
        check('a script from a project shows a warning and does not run', (r['warn2'], r['ran']), (True, False))
    await shot(page, 't05-python.png')

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
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
