#!/usr/bin/env python3
"""smui.html in a real browser: table scripts (smui-scripts.js) and names
on one line (SM.table.cleanName).

A table that keeps a design's Model as a script, as the DOE platforms make
it (a launch by column names, a split plot's whole plots a random effect):
the Table panel lists it, and a real click opens Fit Model's dialog filled
in, OK runs it. Report > Save > Save Script to Data Table keeps a report
(its options and closed outlines) and a click runs it back, the same;
saved again under its name it is replaced. The panel's right click
(Rename…, Delete) with Edit > Undo and Redo; a column renamed in the
scripts; a column missing: a message names it, and the dialog opens with
the others. A project and Save Table keep the scripts, and the report
script runs on the table opened again (new column ids). A hostile table
file: its scripts checked (bad names, platforms, specs, prototype keys
dropped). A CSV header "a\\nb", a JSON table's name with a line separator
and a rename with a pasted line break all come out as "a b". The dark
theme and phone width.

Start a server on the repository root and headless Chrome (see README.md)
on SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-scripts.py

Exit status 0 when every check passes.
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
  set(input, v) { if (input.type === 'checkbox') input.checked = !!v; else input.value = v; input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true })); },
  done: (rep) => new Promise((res) => { rep.on('done', res); }),
  menuButton(label) { return [...document.querySelectorAll('.sm-menu button')].find((b) => b.querySelector('.sm-label') && b.querySelector('.sm-label').textContent === label) || null; },
  script: (name) => [...document.querySelectorAll('.sm-panel-table .sm-script')].find((b) => b.querySelector('.sm-scriptname').textContent === name) || null,
  scripts: () => [...document.querySelectorAll('.sm-panel-table .sm-script .sm-scriptname')].map((x) => x.textContent),
  // a report's text: its outline titles and its tables' cells
  text(rep) {
    return { heads: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map((h) => h.textContent.trim()),
      closed: [...rep.body.querySelectorAll('.sm-ob.is-closed > .sm-ob-head, .sm-ob.closed > .sm-ob-head')].map((h) => h.textContent.trim()),
      cells: [...rep.body.querySelectorAll('table.sm-rt td')].map((td) => td.textContent.trim()).join('|') };
  },
  roles(d) { return Object.fromEntries([...d.querySelectorAll('.sm-role')].filter((row) => !row.hidden).map((row) => [row.querySelector('.sm-btn').textContent, [...row.querySelectorAll('.sm-role-list li')].map((li) => li.textContent)])); },
};
'''

# a design's Model, as smui-p-doe.js keeps it: by column names, the effects beside roles and options
MODEL = {'name': 'Model', 'platform': 'fitmodel', 'spec': {
    'roles': {'y': ['yield (g)']}, 'options': {'personality': 'standard'},
    'effects': [{'names': ['fertilizer'], 'nest': [], 'nestNames': [], 'random': False}, {'names': ['water'], 'nest': [], 'nestNames': [], 'random': False},
                {'names': ['fertilizer', 'water'], 'nest': [], 'nestNames': [], 'random': False}, {'names': ['plot'], 'nest': [], 'nestNames': [], 'random': True}]}}
# and Recall's own shape, the effects in extra
MODEL_EXTRA = {'name': 'Model 2', 'platform': 'fitmodel', 'spec': {'roles': {'y': ['yield (g)']}, 'options': {}, 'extra': {'effects': [{'names': ['light (h)']}, {'names': ['plot'], 'random': True}]}}}


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


async def js(page, body, label):
    r = await page.ev(f'(async () => {{ {body} }})()', timeout=240)
    if isinstance(r, str) and r.startswith('EXCEPTION'):
        check(label, r, None)
        return None
    return r


async def click_el(page, expr):
    """A real click on the element expr finds (after scrolling it into view)."""
    xy = await page.ev(f'(() => {{ const e = {expr}; if (!e) return null; e.scrollIntoView({{ block: "nearest" }}); const b = e.getBoundingClientRect(); return [b.x + Math.min(30, b.width / 2), b.y + b.height / 2]; }})()')
    if not xy:
        return False
    await page.click(xy[0], xy[1])
    return True


async def right_click_el(page, expr):
    xy = await page.ev(f'(() => {{ const e = {expr}; if (!e) return null; e.scrollIntoView({{ block: "nearest" }}); const b = e.getBoundingClientRect(); return [b.x + Math.min(30, b.width / 2), b.y + b.height / 2]; }})()')
    if not xy:
        return False
    await page.mouse('mouseMoved', xy[0], xy[1])
    await page.mouse('mousePressed', xy[0], xy[1], button='right')
    await page.mouse('mouseReleased', xy[0], xy[1], button='right')
    return True


async def main():
    page = await open_page(f'{BASE}/smui.html?example=plants')
    check('engine ready', await wait_engine(page), 'ready')
    await page.ev(HELPERS)
    check('no script errors at load', page.errors, [])

    # ---- a design's Model: listed in the Table panel; a real click opens Fit Model filled in; OK runs it ------------------------------
    r = await js(page, f"""
      const t = SM.app.current;
      t.scripts = [{json.dumps(MODEL)}];    // as the DOE platforms set it on the table they make
      SM.app.panels.renderTable();
      return {{ listed: T.scripts(), head: !!document.querySelector('.sm-panel-table .sm-scripthead .info-btn') }};
    """, 'a table with a Model script')
    if r:
        check('the Table panel lists the script, with an (i)', (r['listed'], r['head']), (['Model'], True))
    check('a real click on it', await click_el(page, "T.script('Model')"), True)
    await asyncio.sleep(0.4)
    r = await js(page, r"""
      const d = T.dlg();
      if (!d) return { open: false };
      const roles = T.roles(d);
      const effects = [...d.querySelectorAll('.sm-fm-effbox li')].map((li) => li.textContent);
      const pers = d.querySelector('.sm-fm-pers select') ? d.querySelector('.sm-fm-pers select').value : null;
      const title = d.querySelector('.sm-dialog-head h2').textContent;
      const n0 = SM.app.reports.length;
      T.button(d.querySelector('.sm-actions'), 'OK').click();
      await T.until(() => SM.app.reports.length > n0);
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await T.done(rep);
      const tx = T.text(rep);
      return { open: true, title, roles, effects, pers, heads: tx.heads.slice(0, 12), errors: [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent.slice(0, 200)), random: rep.spec.effects.filter((e) => e.random).map((e) => e.names.join('*')) };
    """, 'running the Model script')
    if r:
        check('it opens Fit Model\'s launch dialog', (r['open'], r.get('title')), (True, 'Fit Model'))
        check('filled in: the Y and the model\'s effects, the whole plots random', (r['roles'].get('Y'), r['effects']), (['yield (g)'], ['fertilizer', 'water', 'fertilizer*water', 'plot&Random']))
        check('the personality as the script has it', r['pers'], 'standard')
        check('OK runs the model with plot random, without an error', (r['random'], r['errors']), (['plot'], []))

    r = await js(page, f"""
      const t = SM.app.current;
      t.setScripts([...t.scripts, {json.dumps(MODEL_EXTRA)}]);
      T.script('Model 2').click();
      await T.sleep(300);
      const d = T.dlg();
      const eff = d ? [...d.querySelectorAll('.sm-fm-effbox li')].map((li) => li.textContent) : null;
      if (d) T.button(d.querySelector('.sm-actions'), 'Cancel').click();
      t.setScripts(t.scripts.filter((x) => x.name !== 'Model 2'));
      return {{ eff, listed: T.scripts() }};
    """, 'a script in Recall\'s own shape')
    if r:
        check('a script with its effects in extra (Recall\'s shape) opens filled in too', (r['eff'], r['listed']), (['light (h)', 'plot&Random'], ['Model']))

    # ---- a real split plot from DOE > Full Factorial Design: its table keeps the Model, which opens Fit Model filled in ---------------------
    r = await js(page, r"""
      const home = SM.app.current;
      const cmd = SM.commands.all().find((x) => x.label === 'Full Factorial Design…');
      if (!cmd) return { skipped: 'no Full Factorial Design' };
      cmd.action(SM.app);
      await T.sleep(150);
      const d = T.dlg();
      const ch = d.querySelector('select[aria-label="Changes"]');
      T.set(ch, 'hard');
      const n0 = SM.app.tables.length;
      T.button(d, 'Make Table').click();
      await T.until(() => SM.app.tables.length > n0, 60000);
      const t = SM.app.tables[SM.app.tables.length - 1];
      SM.app.showTab(SM.app.tabOf(t));
      await T.sleep(100);
      const listed = T.scripts();
      T.script('Model').click();
      await T.sleep(400);
      const f = T.dlg();
      const eff = f ? [...f.querySelectorAll('.sm-fm-effbox li')].map((li) => li.textContent) : null;
      const y = f ? T.roles(f).Y : null;
      if (f) T.button(f.querySelector('.sm-actions'), 'Cancel').click();
      const cols = t.columns.map((c) => c.name);
      SM.app.closeTable(t);
      SM.app.showTab(SM.app.tabOf(home));
      return { listed, eff, y, cols };
    """, 'a split plot from DOE')
    if r and not r.get('skipped'):
        check('a split-plot design table from DOE keeps its Model, listed in the Table panel', r['listed'], ['Model'])
        check('... which opens Fit Model with the design\'s Y and effects, the whole plots random', (r['y'], 'Whole Plots&Random' in (r['eff'] or []), len(r['eff'] or []) > 1), (['Y'], True, True))
    elif r:
        print('   (skipped: %s)' % r['skipped'])

    # ---- Save Script to Data Table from a report, and run it back ------------------------------------------------------------------------
    r = await js(page, r"""
      const t = SM.app.current;
      const P = SM.platforms.get('distribution');
      const y = t.col('yield (g)'), l = t.col('light (h)');
      const rep = SM.app.openReport(P, { roles: { y: [y.id, l.id] }, options: {} }, t);
      await T.done(rep);
      // an option of one column, and an outline closed: both come back
      const p1 = T.done(rep); rep.spec.options[`${y.id}|quantiles`] = false; rep.run(); await p1;
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find((h) => h.textContent.trim() === 'Summary Statistics');
      head.querySelector('h4, h3').click();
      await T.sleep(80);
      const before = T.text(rep);
      // Save ▾ > Save Script to Data Table…
      [...rep.el.querySelectorAll('.sm-btn')].find((b) => b.textContent.startsWith('Save')).click();
      await T.sleep(60);
      const item = T.menuButton('Save Script to Data Table…');
      const itemOk = !!item && !item.disabled;
      item.click();
      await T.sleep(80);
      let d = T.dlg();
      const name0 = d.querySelector('.sm-form input').value;
      T.set(d.querySelector('.sm-form input'), 'Yield and light');
      T.button(d, 'OK').click();
      await T.sleep(80);
      const sc = t.scripts.find((x) => x.name === 'Yield and light');
      SM.app.closeReport(rep);
      SM.app.showTab(SM.app.tabOf(t));
      await T.sleep(60);
      return { itemOk, name0, listed: T.scripts(), kind: sc && sc.kind, idNames: sc ? Object.values(sc.idNames).sort() : null, before };
    """, 'Save Script to Data Table')
    if r:
        check('the report\'s Save menu has Save Script to Data Table…', r['itemOk'], True)
        check('its name starts as the platform\'s', r['name0'], 'Distribution')
        check('the report is a script of the table, with the names of its columns', (r['listed'], r['kind'], r['idNames']), (['Model', 'Yield and light'], 'report', ['light (h)', 'yield (g)']))
        before = r['before']
    check('a real click runs it', await click_el(page, "T.script('Yield and light')"), True)
    r = await js(page, r"""
      await T.until(() => SM.app.reports.find((x) => x.platform.id === 'distribution'));
      const rep = SM.app.reports.find((x) => x.platform.id === 'distribution');
      await T.done(rep);
      await T.sleep(120);
      return { text: T.text(rep), dialog: !!T.dlg() };
    """, 'running a report script')
    if r and before:
        check('the report comes back, without a dialog', r['dialog'], False)
        check('... the same outlines, the column\'s option kept', r['text']['heads'], before['heads'])
        check('... the outline closed as it was', r['text']['closed'], before['closed'])
        check('... the same numbers', r['text']['cells'], before['cells'])
    r = await js(page, r"""
      const t = SM.app.current;
      const rep = SM.app.reports.find((x) => x.platform.id === 'distribution');
      [...rep.el.querySelectorAll('.sm-btn')].find((b) => b.textContent.startsWith('Save')).click();
      await T.sleep(60);
      T.menuButton('Save Script to Data Table…').click();
      await T.sleep(80);
      const d = T.dlg();
      T.set(d.querySelector('.sm-form input'), 'Yield and light');
      T.button(d, 'OK').click();
      await T.sleep(60);
      SM.app.closeReport(rep);
      SM.app.showTab(SM.app.tabOf(t));
      return { listed: T.scripts(), n: t.scripts.filter((x) => x.name === 'Yield and light').length };
    """, 'saving a script again under its name')
    if r:
        check('saved again under its name: replaced, not added', (r['listed'], r['n']), (['Model', 'Yield and light'], 1))

    # ---- the right click: Rename… and Delete, each one Undo step; Redo ----------------------------------------------------------------------
    check('a real right click on a script', await right_click_el(page, "T.script('Yield and light')"), True)
    await asyncio.sleep(0.2)
    r = await js(page, r"""
      const t = SM.app.current;
      const menu = [...document.querySelectorAll('.sm-menu')].pop();
      const items = [...menu.querySelectorAll('.sm-label')].map((x) => x.textContent);
      T.menuButton('Rename…').click();
      await T.sleep(80);
      let d = T.dlg();
      T.set(d.querySelector('.sm-form input'), 'Model');
      T.button(d, 'OK').click();
      await T.sleep(40);
      const refused = d.querySelector('.sm-launch-msg').textContent;
      T.set(d.querySelector('.sm-form input'), 'Growth report');
      T.button(d, 'OK').click();
      await T.sleep(60);
      const renamed = T.scripts();
      SM.app.undo();
      await T.sleep(40);
      const undone = T.scripts();
      SM.app.redo();
      await T.sleep(40);
      const redone = T.scripts();
      // Delete, and Undo
      T.script('Growth report').dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 60, clientY: 200 }));
      await T.sleep(40);
      T.menuButton('Delete').click();
      await T.sleep(40);
      const deleted = T.scripts();
      SM.app.undo();
      await T.sleep(40);
      return { items, refused, renamed, undone, redone, deleted, back: T.scripts() };
    """, 'Rename and Delete')
    if r:
        check('the right click: Run Script, Rename…, Delete', r['items'], ['Run Script', 'Rename…', 'Delete'])
        check('a name another script has is refused', r['refused'], 'Pants and crops has a script Model already'.replace('Pants and crops', 'Plant trial'))
        check('renamed (a line separator made a space)', r['renamed'], ['Model', 'Growth report'])
        check('Edit > Undo takes the rename back, Redo does it again', (r['undone'], r['redone']), (['Model', 'Yield and light'], ['Model', 'Growth report']))
        check('Delete, and Undo brings the script back', (r['deleted'], r['back']), (['Model'], ['Model', 'Growth report']))

    # ---- a column renamed in the scripts; a column missing ----------------------------------------------------------------------------------
    r = await js(page, r"""
      const t = SM.app.current;
      t.renameColumn(t.col('water'), 'irrigation');
      const m = t.scripts.find((x) => x.name === 'Model'), g = t.scripts.find((x) => x.name === 'Growth report');
      const out = { effects: m.spec.effects.map((e) => e.names.join('*')), names: Object.values(g.idNames).sort() };
      // the report script still runs, on the renamed columns
      T.script('Growth report').click();
      await T.until(() => SM.app.reports.find((x) => x.platform.id === 'distribution'));
      const rep = SM.app.reports.find((x) => x.platform.id === 'distribution');
      await T.done(rep);
      out.cols = rep.spec.roles.y.map((id) => t.col(id).name);
      SM.app.closeReport(rep);
      // a script whose column is not there: a message names it, the dialog has the others
      SM.app.showTab(SM.app.tabOf(t));
      const u0 = SM.app.undoStack.length;
      t.setScripts([...t.scripts, { name: 'Gone', platform: 'fitmodel', spec: { roles: { y: ['yield (g)', 'no such column'] }, options: {}, extra: { effects: [{ names: ['fertilizer'] }, { names: ['vanished'] }] } } }]);
      T.script('Gone').click();
      await T.sleep(250);
      const toast = (document.querySelector('.sm-toast') || {}).textContent || '';
      const d = T.dlg();
      out.toast = toast;
      out.roles = d ? T.roles(d).Y : null;
      out.eff = d ? [...d.querySelectorAll('.sm-fm-effbox li')].map((li) => li.textContent) : null;
      if (d) T.button(d.querySelector('.sm-actions'), 'Cancel').click();
      t.setScripts(t.scripts.filter((x) => x.name !== 'Gone'));
      t.renameColumn(t.col('irrigation'), 'water');
      return out;
    """, 'renamed and missing columns')
    if r:
        check('renaming a column renames it in the scripts: the Model\'s effects', r['effects'], ['fertilizer', 'irrigation', 'fertilizer*irrigation', 'plot'])
        check('... and the report script\'s names', r['names'], ['light (h)', 'yield (g)'])
        check('the report script runs on the renamed table', r['cols'], ['yield (g)', 'light (h)'])
        check('a missing column: the message names it', 'no such column and vanished are not in Plant trial' in r['toast'], True)
        check('... and the dialog opens with the columns that are', (r['roles'], r['eff']), (['yield (g)'], ['fertilizer']))

    # ---- a project and Save Table keep the scripts; the report script runs on the table opened again ---------------------------------------
    r = await js(page, r"""
      const t = SM.app.current;
      const j = { format: 'smui-project', version: 1, tables: [{ id: 'p1', ...t.toJSON(), name: 'Plant trial again' }], reports: [] };
      const n0 = SM.app.tables.length;
      SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const t2 = SM.app.tables.slice(n0).find((x) => x.name === 'Plant trial again');
      SM.app.showTab(SM.app.tabOf(t2));
      await T.sleep(60);
      const out = { listed: T.scripts(), ids: t2.columns.some((c) => t.columns.some((d) => d.id === c.id)) };
      T.script('Growth report').click();
      await T.until(() => SM.app.reports.find((x) => x.table === t2));
      const rep = SM.app.reports.find((x) => x.table === t2);
      await T.done(rep);
      out.cols = rep.spec.roles.y.map((id) => (t2.col(id) || { name: null }).name);
      out.errors = [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent.slice(0, 200));
      SM.app.closeReport(rep);
      const tj = SM.Table.fromJSON(JSON.parse(JSON.stringify(t.toJSON())));
      out.table = tj.scripts.map((x) => [x.name, x.kind]);
      SM.app.closeTable(t2);
      SM.app.showTab(SM.app.tabOf(t));
      return out;
    """, 'a project and Save Table')
    if r:
        check('a project keeps the scripts', r['listed'], ['Model', 'Growth report'])
        check('the table opened again has new column ids', r['ids'], False)
        check('... and the report script finds its columns by name', (r['cols'], r['errors']), (['yield (g)', 'light (h)'], []))
        check('Save Table keeps them too', r['table'], [['Model', 'launch'], ['Growth report', 'report']])

    # ---- a hostile table file: its scripts checked --------------------------------------------------------------------------------------------
    r = await js(page, r"""
      const cols = [{ name: 'x', dataType: 'numeric', values: [1, 2, 3] }];
      const bad = [
        { name: 'ok', platform: 'distribution', spec: { roles: { y: ['x'] }, options: { a: { __proto__: { polluted: 1 }, constructor: 2, prototype: 3, b: 4 } }, extra: {} }, junk: 'dropped' },
        { name: 'no platform', platform: 'nope', spec: { roles: {} } },
        { name: 'a\nb', platform: 'distribution', spec: { roles: {} } },
        { name: 'z'.repeat(500), platform: 'distribution', spec: { roles: {} } },
        { name: 5, platform: 'distribution', spec: { roles: {} } },
        'a string', null, [1, 2],
        { name: 'array spec', platform: 'distribution', spec: [1, 2] },
        { name: 'ok', platform: 'distribution', spec: { roles: {} } },
        { name: 'rep', platform: 'distribution', kind: 'report', spec: { roles: { y: ['c9'] } }, idNames: { c9: 'x', 'bad key!': 'y', c10: 5 } },
        { name: 'odd kind', platform: 'distribution', kind: 'eval', spec: { roles: {} } },
      ];
      const text = JSON.stringify({ format: 'smui-table', version: 1, name: 'Hostile', columns: cols, scripts: bad }).replace('"a":{"polluted":1', '"a":{"__proto__":{"polluted":1}');
      const t = SM.Table.fromJSON(JSON.parse(text));
      const ok = t.scripts.find((x) => x.name === 'ok');
      return { names: t.scripts.map((x) => x.name.length > 60 ? `${x.name.slice(0, 3)}…${x.name.length}` : x.name), kinds: t.scripts.map((x) => x.kind), okKeys: Object.keys(ok), aKeys: Object.keys(ok.spec.options.a), proto: Object.getPrototypeOf(ok.spec.options.a) === Object.prototype, polluted: ({}).polluted, idNames: t.scripts.find((x) => x.name === 'rep').idNames };
    """, 'a hostile table file')
    if r:
        check('only scripts it can trust: a name cleaned, a long one cut at 200, a repeat, a bad platform or spec left out', r['names'], ['ok', 'a b', 'zzz…200', 'rep', 'odd kind'])
        check('an unknown kind is a launch', r['kinds'], ['launch', 'launch', 'launch', 'report', 'launch'])
        check('only the script\'s own keys', r['okKeys'], ['name', 'platform', 'kind', 'spec'])
        check('no __proto__, constructor or prototype key in a spec, and nothing polluted', (r['aKeys'], r['proto'], r.get('polluted')), (['b'], True, None))
        check('a report script\'s idNames: only ids with names', r['idNames'], {'c9': 'x'})

    # ---- names on one line: a CSV header, a JSON table, a rename with a pasted line break -----------------------------------------------
    r = await js(page, r"""
      const csv = SM.io.tableFromText('"a\nb",c\n1,2\n3,4\n', 'lines');
      const j = SM.Table.fromJSON({ format: 'smui-table', version: 1, name: 'one two', columns: [{ name: 'a b', dataType: 'numeric', values: [1] }, { name: 'a b', dataType: 'numeric', values: [2] }] });
      const t = SM.app.current;
      const c = t.col('light (h)');
      // Column Info's name: a line separator survives a text field (a line feed the field itself drops)
      SM.app.columnInfo(c);
      await T.sleep(80);
      const d = T.dlg();
      T.set(d.querySelector('input[type="text"]'), 'a b');
      T.button(d, 'OK').click();
      await T.sleep(60);
      const viaInfo = c.name;
      t.renameColumn(c, 'x\r\ny');
      const viaApi = c.name;
      SM.app.undo();          // (Column Info's step: the name before both renames)
      const back = c.name;
      SM.app.renameTable(csv, 'my\ntable');
      return { csv: csv.columns.map((x) => x.name), json: [j.name, j.columns.map((x) => x.name)], viaInfo, viaApi, back, table: csv.name };
    """, 'names on one line')
    if r:
        check('a CSV header "a\\nb" (quoted) is a b', r['csv'], ['a b', 'c'])
        check('a JSON table\'s names with line separators: a b, and a second a b is a b 2', r['json'], ['one two', ['a b', 'a b 2']])
        check('a rename in Column Info with a pasted line separator is a b', r['viaInfo'], 'a b')
        check('a rename with a pasted line break is x y', r['viaApi'], 'x y')
        check('Undo takes the renames back', r['back'], 'light (h)')
        check('a table renamed with a line break', r['table'], 'my table')

    # ---- the dark theme and phone width ---------------------------------------------------------------------------------------------------------
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(0.5)
    dark = await page.ev("(() => { const b = T.script('Model'); const m = b.querySelector('.sm-scriptrun'); return [getComputedStyle(b).color !== 'rgb(0, 0, 0)', getComputedStyle(m).color]; })()")
    check('dark theme: the scripts\' text and run marks take the dark theme\'s colours', (dark[0], dark[1] not in ('rgb(0, 0, 0)', '')), (True, True))
    await shot(page, 's01-scripts-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.6)
    await page.ev("document.querySelector('.sm-sidetoggle').click()")
    await asyncio.sleep(0.4)
    ph = await page.ev("""(() => { const box = document.querySelector('.sm-panel-table .sm-scriptbox'); const side = document.querySelector('.sm-side'); const b = box.getBoundingClientRect(), s = side.getBoundingClientRect();
      return [document.documentElement.scrollWidth <= innerWidth + 1, b.right <= s.right + 1, b.width > 0, [...box.querySelectorAll('.sm-scriptname')].every((x) => x.scrollWidth <= x.clientWidth + 1 || getComputedStyle(x).textOverflow === 'ellipsis')]; })()""")
    check('phone width: the scripts in the side panel fit, a long name cut with an ellipsis', ph, [True, True, True, True])
    await shot(page, 's02-scripts-phone.png')
    await page.ev("document.querySelector('.sm-sidetoggle').click()")
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
