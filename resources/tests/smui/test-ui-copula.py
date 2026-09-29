#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Multivariate Methods > Copulas.

The simulated Drought example opens from the URL and File > Examples, and
the platform sits in Analyze > Multivariate Methods after Multidimensional
Scaling; the launch dialog's own part picks the copulas, the rotations, the
estimation and the margins (and strikes out the one-pair families for
three columns); the report's Kendall's tau and pseudo-observations are the
ones computed here from the table, Clayton (the example's true copula) has
the smallest AIC and its interval covers the true θ = 2; points select
their rows (one by a real mouse click) and table selections highlight
them; every red triangle opens; the red triangles change the estimation,
the standard errors, the copula shown, the scale and the pair (Redo keeps
them); the joint-probability calculator gives C(F1(x), F2(y)) computed
here from the engine's own fit; goodness of fit, Simulate (a new table
equal to the engine's draws, and the comparison outline) and Save work;
By gives one analysis per group with combined tables; three columns give
the scatterplot matrix and the elliptical copulas only; negative
dependence brings the 90° and 270° rotations and the corner tails; a
project keeps the options with the column ids remapped; the Python script
holds the statsmodels calls; every (i) has a topic; the reports draw in the
dark theme and at phone width without a sideways page scroll.

Start a server on the repository root and headless Chrome (README.md) on
SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-copula.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import math
import os
import sys
from statistics import NormalDist

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine
from test_charts import GRAPHS_JS, more_from_outputs, page_probe_more

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
X, Y = 'soil moisture (%)', 'stream flow (m³/s)'


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.8)
        await page.shot(os.path.join(SHOTS, name))


def num(s):
    return float(str(s).replace('−', '-').replace('%', '').replace('*', '').replace('<', ''))


# Pick an item from an outline's red triangle: path is the labels down the
# submenus; wait: wait for the report to run again. which: the n-th outline
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


# The same, for an item that opens a form: fill(dialog) runs on the form,
# then OK, then the report runs again.
PICK_FORM = '''
(async (title, path, fill) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await (%s)(title, path, false, 0);
  for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 100));
  const dlgs = [...document.querySelectorAll('.sm-dialog')];
  const d = dlgs[dlgs.length - 1];
  const done = new Promise(res => rep.on('done', res));
  (new Function('d', fill))(d);
  d.querySelector('.sm-dialog-foot .primary').click();
  await done;
  return [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
})
''' % PICK


def pick_form_js(title, path, fill):
    return f'({PICK_FORM})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(fill)})'


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

# The table of the drought example computed here: Kendall's tau-b of the two
# columns, and each row's average rank over n + 1.
PAGE_STATS = '''
(() => {
  const t = SM.app.tables.find(t => t.name === 'Drought');
  const x = t.col('%s').values, y = t.col('%s').values;
  const n = x.length;
  let S = 0, tx = 0, ty = 0;
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
    const a = Math.sign(x[i] - x[j]), b = Math.sign(y[i] - y[j]);
    S += a * b; if (a === 0) tx++; if (b === 0) ty++;
  }
  const n0 = n * (n - 1) / 2;
  const rx = SM.util.ranks(x).map(r => r / (n + 1)), ry = SM.util.ranks(y).map(r => r / (n + 1));
  return { tau: S / Math.sqrt((n0 - tx) * (n0 - ty)), rx, ry, n };
})()
''' % (X, Y)

# The drought table's last report's plot of pseudo-observations: its trace.
PSEUDO = '''
(() => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const p = rep.plots.find(p => /^Pseudo-observations of/.test(p.opts.title));
  if (!p) return null;
  return { x: p.traces[0].x, y: p.traces[0].y, rows: p.rows[0], contours: p.traces.filter(t => t.type === 'contour').length, title: p.opts.title,
           names: p.traces.filter(t => t.type === 'contour').map(t => t.name), labels: p.traces.filter(t => t.type === 'contour').every(t => t.contours.showlabels),
           xtitle: p.userLayout.xaxis.title.text, range: p.userLayout.xaxis.range, color: (p.traces.find(t => t.type === 'contour') || {}).line?.color };
})()
'''


async def triangles(page, name, least):
    r = await page.ev(TRIANGLES)
    ok = isinstance(r, dict) and not r['errors'] and r['triangles'] >= least and r['items'] > r['triangles']
    check(f'every red triangle of {name} opens, with its submenus', ok, True)
    if not ok:
        print('   ', r)


async def rerun(page):
    await page.ev('(async () => { const rep = SM.app.reports[SM.app.reports.length - 1]; const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')


# ---- help for every input: the (i) of the launch dialog, of the forms and of the report's controls
HELP_JS = r'''
window.__hp = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  async waitNew(n0, sel) {
    for (let i = 0; i < 300; i++) { const d = [...document.querySelectorAll(sel)]; if (d.length > n0) return d[d.length - 1]; await this.sleep(50); }
    return null;
  },
  // The open (i) panel: its title and sections, each a heading with its [name, text] entries.
  panel() {
    const p = document.getElementById('kvot-info-panel');
    if (!p) return null;
    const sections = [{ heading: null, entries: [] }];
    for (const node of p.querySelector('.info-panel-body').children) {
      if (node.tagName === 'H3') sections.push({ heading: node.textContent, entries: [] });
      else if (node.matches('dl.info-choices')) {
        const dt = [...node.children].filter((x) => x.tagName === 'DT'), dd = [...node.children].filter((x) => x.tagName === 'DD');
        dt.forEach((t, i) => sections[sections.length - 1].entries.push([t.textContent, dd[i] ? dd[i].textContent : '']));
      }
    }
    return { title: p.querySelector('.info-panel-title').textContent, headings: sections.map((s) => s.heading).filter(Boolean), sections: sections.filter((s) => s.heading || s.entries.length) };
  },
  // Click an (i), read its panel, close it.
  async open(btn) {
    if (!btn) return null;
    btn.click();
    await this.sleep(80);
    const out = { key: btn.dataset.info, ...this.panel() };
    KvotInfo.close();
    return out;
  },
  audit() { const a = KvotInfo.audit(); return { noTopic: a.noTopic, brokenMore: a.brokenMore }; },
  showTable(name) { const t = SM.app.tables.find((x) => x.name === name); if (t) SM.app.showTab(SM.app.tabOf(t)); return !!t; },
  // Cast columns into a role of a launch dialog.
  cast(d, names, role) {
    const items = [...d.querySelectorAll('.sm-pick-list li')];
    names.forEach((n, i) => {
      const li = items.find((x) => x.textContent === n);
      if (!li) throw new Error('no column ' + n);
      li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, ctrlKey: i > 0 }));
    });
    [...d.querySelectorAll('.sm-role .sm-btn')].find((b) => b.textContent === role).click();
  },
  choose(d, aria, value) { const s = d.querySelector(`select[aria-label="${aria}"]`); s.value = value; s.dispatchEvent(new Event('change', { bubbles: true })); },
  // A launch dialog's (i) after prep(dialog), audited while the dialog is open; then Cancel.
  async launch(id, prep) {
    const n0 = document.querySelectorAll('.sm-launch-dialog').length;
    SM.app.launch(id);
    const d = await this.waitNew(n0, '.sm-launch-dialog');
    if (!d) throw new Error('no launch dialog');
    if (prep) { await prep(d); await this.sleep(80); }
    const info = await this.open(d.querySelector('.sm-dialog-head .info-btn'));
    const audit = this.audit();
    const L = SM.platforms.get(id).launch;
    [...d.querySelectorAll('.sm-actions .sm-btn')].find((b) => b.textContent === 'Cancel').click();
    await this.sleep(60);
    return { info, audit, roles: (L.roles || []).map((r) => r.label), options: (L.options || []).map((o) => o.label) };
  },
  head(rep, title) { return [...rep.body.querySelectorAll('.sm-ob-head')].find((h) => { const t = h.querySelector('h2, h3, h4'); return t && t.textContent === title; }); },
  // Pick from the red triangle of an outline (null: the top one), without waiting for a redraw.
  async menu(rep, title, path) {
    const h = title == null ? (rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head') || rep.body.querySelector('.sm-ob-head')) : this.head(rep, title);
    if (!h) throw new Error('no outline ' + title);
    h.querySelector('.sm-ob-menu').click();
    for (const label of path) {
      await this.sleep(40);
      const m = [...document.querySelectorAll('.sm-menu')].pop();
      const b = m && [...m.querySelectorAll('button')].find((x) => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === label);
      if (!b) { SM.ui.closeMenus(0); throw new Error('no menu item ' + label); }
      b.click();
    }
  },
  // A form that open() brings up: its fields' labels and its (i), audited while open; then closed.
  async form(open) {
    const n0 = document.querySelectorAll('.sm-dialog').length;
    await open();
    const d = await this.waitNew(n0, '.sm-dialog');
    if (!d) throw new Error('no form opened');
    const info = await this.open(d.querySelector('.sm-dialog-head .info-btn'));
    const audit = this.audit();
    const out = { title: d.querySelector('.sm-dialog-head h2').textContent, labels: [...d.querySelectorAll('.sm-form label')].map((l) => l.textContent), info, audit };
    d.querySelector('.sm-dialog-x').click();
    await this.sleep(60);
    return out;
  },
  // An outline's own (i).
  async outline(rep, title) { const h = this.head(rep, title); return h ? this.open(h.querySelector('.kvot-info-slot .info-btn')) : null; },
};
true
'''


def help_section(info, heading):
    """The [name, text] entries of a section of an (i) panel, as a dict; None when there is none."""
    for s in (info or {}).get('sections', []):
        if s['heading'] == heading:
            return dict(s['entries'])
    return None


async def check_launch_help(page, pid, settings=None, prep='null', what=None):
    """A launch dialog's (i): every role and option with its help, the fields
    of the platform's own part (settings), and a topic for every (i) while the
    dialog is open."""
    what = what or f'{pid}: the launch dialog'
    r = await page.ev(f'__hp.launch({json.dumps(pid)}, {prep})', timeout=300)
    if not isinstance(r, dict):
        check(f'{what}: opens', r, 'a dialog')
        return None
    info = r['info'] or {}
    roles = help_section(info, 'Roles') or {}
    check(f'{what}: its (i) lists every role', list(roles), r['roles'])
    check(f'{what}: every role has help beyond what it takes', [k for k, t in roles.items() if t.startswith('(') or len(t) < 80], [])
    check(f'{what}: one Roles section (the topic\'s gives way to it)', info.get('headings', []).count('Roles'), 1)
    opts = help_section(info, 'Options') or {}
    check(f'{what}: its (i) lists every option', list(opts), r['options'])
    check(f'{what}: every option has help', [k for k, t in opts.items() if len(t) < 60], [])
    if settings is not None:
        got = help_section(info, 'Settings') or {}
        check(f'{what}: its (i) explains the fields of the platform\'s own part', list(got), settings)
        check(f'{what}: none of them in a word', [k for k, t in got.items() if len(t) < 30], [])
    check(f'{what}: every (i) has a topic while it is open', r['audit']['noTopic'], [])
    check(f'{what}: every Help link has a target', r['audit']['brokenMore'], [])
    return info


async def check_form_help(page, open_js, fields, what):
    """A form's (i) lists every field with its help, in order (fields: the names shown)."""
    r = await page.ev(f'__hp.form(async () => {{ {open_js} }})', timeout=300)
    if not isinstance(r, dict):
        check(f'{what}: opens', r, 'a dialog')
        return None
    got = help_section(r['info'], 'Fields') or {}
    check(f'{what}: its (i) explains every field', list(got), fields)
    check(f'{what}: none of them in a word', [k for k, t in got.items() if len(t) < 30], [])
    check(f'{what}: every (i) has a topic while it is open', r['audit']['noTopic'], [])
    return r


async def check_controls_help(page, rep_js, title, names, what, heading='In the report'):
    """An outline's (i) explains the controls inside the report, in a section of choices."""
    info = await page.ev(f'__hp.outline({rep_js}, {json.dumps(title)})')
    got = help_section(info, heading) or {}
    check(f'{what}: its (i) explains the controls in the report', list(got), names)
    check(f'{what}: none of them in a word', [k for k, t in got.items() if len(t) < 30], [])
    return info


async def main():
    page = await open_page(f'{BASE}/smui.html?example=dependence', height=1200)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "copula").map(f => f.module + ": " + f.error)')
    check('copula.py imports in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])

    # ---- the example and the menu
    ex = await page.ev('''(() => {
      const t = SM.app.current;
      const file = SM.app.menuItems('File');
      const exs = file.find(i => i.label === 'Examples');
      const labels = (typeof exs.submenu === 'function' ? exs.submenu() : exs.submenu).map(i => i.label);
      const an = SM.app.menuItems('Analyze');
      const mm = an.find(i => i.label === 'Multivariate Methods');
      const items = (typeof mm.submenu === 'function' ? mm.submenu() : mm.submenu).filter(i => !i.separator).map(i => i.label);
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), about: SM.io.EXAMPLES.dependence.about, inFile: labels.includes(SM.io.EXAMPLES.dependence.label), items };
    })()''')
    check('?example=dependence opens the simulated drought table', (ex['name'], ex['rows'], ex['cols']), ('Drought', 500, ['day', 'region', X, Y]))
    check('it is simulated, and its notes give the true copula', ex['about'].startswith('Simulated') and 'Clayton copula with θ = 2' in ex['about'], True)
    check('it is in File > Examples', ex['inFile'], True)
    check('Analyze > Multivariate Methods lists Copulas after Multidimensional Scaling', 'Copulas…' in ex['items'] and ex['items'].index('Copulas…') > ex['items'].index('Multidimensional Scaling…'), True)

    # ---- the launch dialog
    r = await page.ev('''(async () => {
      SM.app.launch('copula');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const checks = [...dlg.querySelectorAll('.sm-cop-check input')];
      const fam = [...dlg.querySelectorAll('.sm-cop-checks .sm-cop-check')].map(l => [l.textContent, l.querySelector('input').checked]);
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const pick = (name) => { items.forEach(li => li.classList.remove('is-selected')); items.find(x => x.textContent === name).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); };
      const role = (label) => [...dlg.querySelectorAll('.sm-role')].find(r => r.querySelector('.sm-btn').textContent === label);
      const ok = [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      pick('%s'); role('Y, Columns').querySelector('.sm-btn').click();
      ok.click();
      const needTwo = dlg.querySelector('.sm-launch-msg').textContent;
      pick('%s'); role('Y, Columns').querySelector('.sm-btn').click();
      pick('day'); role('Y, Columns').querySelector('.sm-btn').click();
      const struck3 = [...dlg.querySelectorAll('.sm-cop-checks .sm-cop-check.is-off')].map(l => l.textContent);
      const hint3 = dlg.querySelector('.sm-cop-hint').textContent;
      // take day out again: double click it in the role
      [...role('Y, Columns').querySelectorAll('li')].find(li => li.textContent === 'day').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      const struck2 = dlg.querySelectorAll('.sm-cop-checks .sm-cop-check.is-off').length;
      const boxes = [...dlg.querySelectorAll('.sm-cop-checks input')];
      boxes.forEach(b => { b.checked = false; });
      ok.click();
      const noFamily = dlg.querySelector('.sm-launch-msg').textContent;
      boxes.forEach(b => { b.checked = true; });
      const marg = [...dlg.querySelectorAll('.sm-cop-opts .sm-cop-check input')][0];
      marg.checked = true;
      const selects = [...dlg.querySelectorAll('.sm-cop-opts select')];
      ok.click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { fam, needTwo, struck3, hint3, struck2, noFamily, selects: selects.map(s => [s.getAttribute('aria-label'), s.value]), options: rep.spec.options, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent) };
    })()''' % (X, Y))
    check('the launch dialog offers the six copulas, all ticked', r['fam'], [['Gaussian', True], ['Student t', True], ['Clayton', True], ['Frank', True], ['Gumbel', True], ['Independence', True]])
    check('one column is not enough', 'at least 2' in r['needTwo'], True)
    check('with three columns Clayton, Frank and Gumbel are struck out', (r['struck3'], 'only the Gaussian, Student t' in r['hint3']), (['Clayton', 'Frank', 'Gumbel'], True))
    check('and back with two', r['struck2'], 0)
    check('no copula ticked: an error', 'choose at least one' in r['noFamily'], True)
    check('the rotations and estimation start on their defaults', r['selects'], [['Rotations of Clayton and Gumbel', 'auto'], ['Estimation method', 'mpl']])
    check('the options reach the report', (r['options']['families'], r['options']['rotations'], r['options']['method'], r['options']['margins']), (['gaussian', 't', 'clayton', 'frank', 'gumbel', 'indep'], 'auto', 'mpl', True))
    check('the report\'s outlines', r['outlines'], [f'Copulas of {X} and {Y}', 'Pseudo-Observations', 'Dependence', 'Copula Comparison', 'Margins', X, Y])
    st = await page.ev(STATE)
    check('no errors in the report', st['errors'], [])
    await shot(page, 'copula-01-report.png')

    # ---- the numbers against the table
    ps = await page.ev(PAGE_STATS)
    rc = await page.ev(table_under_js('Dependence', 0))
    check.near('Kendall\'s τb = the one computed here', num(rc[1][2]), round(ps['tau'], 4), tol=1e-9)
    pp = await page.ev(PSEUDO)
    rows = pp['rows']
    check('the pseudo-observations are the ranks over n + 1 computed here', max(max(abs(a - ps['rx'][r_]), abs(b - ps['ry'][r_])) for a, b, r_ in zip(pp['x'], pp['y'], rows)) < 1e-12, True)
    check('one point per row, on the unit square', (len(rows), pp['range']), (500, [0, 1]))
    check('the contours are the copula\'s density at 1/2, 2 and 4 at least, labelled', all(n_ in pp['names'] for n_ in ('density 1/2', 'density 2', 'density 4')) and pp['labels'], True)
    cmp_ = await page.ev(table_under_js('Copula Comparison', 0))
    fams = [row[0] for row in cmp_[1:]]
    aics = [num(row[3]) for row in cmp_[1:]]
    check('Clayton, the true copula, has the smallest AIC', fams[0], 'Clayton')
    check('the fits are sorted by AIC', aics == sorted(aics), True)
    check('survival copulas join for a positive τ', ('Survival Gumbel (180°)' in fams, 'Survival Clayton (180°)' in fams, any('90°' in f for f in fams)), (True, True, False))
    pe = await page.ev(table_under_js('Copula Comparison', 1))
    cl = next(row for row in pe[1:] if row[0] == 'Clayton')
    check(f'the Clayton interval covers the true θ = 2 ({cl[2]}, {cl[4]} to {cl[5]})', num(cl[4]) < 2 < num(cl[5]), True)
    impl = await page.ev(table_under_js('Dependence', 1))
    clm = next(row for row in impl[1:] if row[0] == 'Clayton')
    th = num(cl[2])
    check.near('the implied τ is θ/(θ + 2)', num(clm[1]), round(th / (th + 2), 4), tol=2e-4)
    check.near('and λL = 2^(−1/θ)', num(clm[3]), round(2 ** (-1 / th), 4), tol=2e-4)

    # ---- linking
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => /^Pseudo-observations of/.test(p.opts.title));
      p._click({ points: [{ curveNumber: 0, pointNumber: 7 }], event: {} });
      const sel = t.selectedRows();
      t.select([p.rows[0][3], p.rows[0][11]]);
      const sp = p.box.data[0].selectedpoints;
      const j = rep.plots.find(p => / with the joint model$/.test(p.opts.title));
      const spj = j.box.data[0].selectedpoints;
      t.select([]);
      return { sel, want: [p.rows[0][7]], sp, spj };
    })()''')
    check('a click on a pseudo-observation selects its row', r['sel'], r['want'])
    check('rows selected in the table highlight their points, in both graphs', (r['sp'], r['spj']), ([3, 11], [3, 11]))
    pos = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => /^Pseudo-observations of/.test(p.opts.title));
      p.box.scrollIntoView({ block: 'center' });
      await new Promise(r => setTimeout(r, 300));
      for (let n = 0; n < 40 && !p.drawn; n++) await new Promise(r => setTimeout(r, 100));
      const gd = p.box, xa = gd._fullLayout.xaxis, ya = gd._fullLayout.yaxis;
      // the point furthest from the others, so that the click hits it alone
      const xs = p.traces[0].x, ys = p.traces[0].y;
      let best = 0, bestD = -1;
      for (let k = 0; k < xs.length; k++) { let d = Infinity; for (let m = 0; m < xs.length; m++) if (m !== k) d = Math.min(d, (xs[k] - xs[m]) ** 2 + (ys[k] - ys[m]) ** 2); if (d > bestD) { bestD = d; best = k; } }
      const b = gd.getBoundingClientRect();
      return { x: b.left + xa._offset + xa.l2p(xs[best]), y: b.top + ya._offset + ya.l2p(ys[best]), row: p.rows[0][best] };
    })()''')
    await page.click(pos['x'], pos['y'])
    await asyncio.sleep(0.4)
    sel = await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()')
    check('a mouse click on a point selects that row', sel, [pos['row']])
    await page.mouse('mouseMoved', 2, 2)   # out of the way of the menus opened below
    await page.ev('SM.app.reports[SM.app.reports.length - 1].table.select([])')

    await triangles(page, 'the report', 7)

    # ---- the red triangles change what is computed; Redo keeps it
    await page.ev(pick_js('Copula Comparison', ['Standard Errors', 'Rank-Corrected (Genest, Ghoudi and Rivest)']))
    pe2 = await page.ev(table_under_js('Copula Comparison', 1))
    cl2 = next(row for row in pe2[1:] if row[0] == 'Clayton')
    check('rank-corrected standard errors are larger than the Hessian\'s', num(cl2[3]) > num(cl[3]), True)
    await page.ev(pick_js('Copula Comparison', ['Estimation Method', 'Inversion of Kendall\'s τ']))
    pe3 = await page.ev(table_under_js('Copula Comparison', 1))
    cl3 = next(row for row in pe3[1:] if row[0] == 'Clayton')
    tau4 = ps['tau']
    check.near('by τ inversion Clayton\'s θ = 2τ/(1 − τ)', num(cl3[2]), 2 * tau4 / (1 - tau4), tol=1e-6)
    await rerun(page)
    st = await page.ev(STATE)
    check('Redo keeps the method and the standard errors', (st['options'].get('method'), st['options'].get('se')), ('itau', 'rank'))
    await page.ev(pick_js('Copula Comparison', ['Estimation Method', 'Maximum Pseudo-Likelihood']))
    # a click on a comparison line shows that copula
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim().startsWith('Copula Comparison'));
      const tr = [...head.parentElement.querySelectorAll('table.sm-rt')][0].querySelectorAll('tbody tr');
      const line = [...tr].find(x => x.cells[0].textContent === 'Gaussian');
      const done = new Promise(res => rep.on('done', res));
      line.click();
      await done;
      const p = rep.plots.find(p => /^Pseudo-observations of/.test(p.opts.title));
      const bold = [...rep.body.querySelectorAll('td.sm-cop-shown')].map(td => td.textContent).filter(t => /^[A-Z]/.test(t));
      return { shown: rep.spec.options.shown, note: p.box.closest('.sm-ob-body').textContent.includes('fitted Gaussian copula'), bold: [...new Set(bold)] };
    })()''')
    check('a click on the Gaussian line shows the Gaussian copula', (r['shown'], r['note']), ('gaussian', True))
    check('and marks it in the tables', 'Gaussian' in r['bold'] and 'Clayton' not in r['bold'], True)
    await page.ev(pick_js('Pseudo-Observations', ['Scale', 'Normal Scores']))
    pp2 = await page.ev(PSEUDO)
    check.near('normal scores: Φ⁻¹ of the pseudo-observations', pp2['x'][0], NormalDist().inv_cdf(pp['x'][0]), tol=1e-6)
    check('on the normal-score axes', (pp2['xtitle'], pp2['range']), (f'{X}: normal score', [-3.3, 3.3]))
    await page.ev(pick_js('Pseudo-Observations', ['Contours Of', 'Clayton']))
    await page.ev(pick_js('Pseudo-Observations', ['Scale', 'Uniform (u, v)']))

    # ---- margins and the joint probabilities
    mg = await page.ev(table_under_js(X, 0))
    check('soil moisture: Weibull (its true margin) has the smallest AICc', [row[1] for row in mg[1:] if row[0] == '✓'], ['Weibull'])
    mg2 = await page.ev(table_under_js(Y, 0))
    check('stream flow: lognormal (its true margin)', [row[1] for row in mg2[1:] if row[0] == '✓'], ['Lognormal'])
    await page.ev(pick_js(f'Copulas of {X} and {Y}', ['Joint Probabilities']))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim().startsWith('Joint Probabilities'));
      const box = head.parentElement;
      const [ix, iy] = box.querySelectorAll('.sm-cop-input');
      ix.value = '20'; iy.value = '3.5';
      const done = new Promise(res => rep.on('done', res));
      [...box.querySelectorAll('button')].find(b => b.textContent === 'Compute').click();
      await done;
      const box2 = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim().startsWith('Joint Probabilities')).parentElement;
      const cells = [...box2.querySelectorAll('table.sm-rt tbody tr')].map(tr => [...tr.cells].map(c => c.textContent));
      // the engine's own fit and margins, and the Clayton copula and the Weibull and lognormal cdfs written here
      const t = rep.table;
      const fit = await SM.engine.call('copula.fit', { table: t.id, rows: null, columns: ['%s', '%s'], families: rep.spec.options.families, method: 'mpl', rotations: 'auto', se: rep.spec.options.se }, t);
      const m = await SM.engine.call('copula.margins', { table: t.id, rows: null, columns: ['%s', '%s'] }, t);
      const th = fit.fits.find(f => f.family === 'clayton').values[0];
      const [wb, ln] = m.columns.map(c => c.chosen.values);
      const u = 1 - Math.exp(-((20 / wb[0]) ** wb[1]));
      const v = SM.util.pnorm((Math.log(3.5) - ln[0]) / ln[1]);
      const C = (u ** -th + v ** -th - 1) ** (-1 / th);
      const x = t.col('%s').values, y = t.col('%s').values;
      let obs = 0; for (let i = 0; i < x.length; i++) if (x[i] <= 20 && y[i] <= 3.5) obs++;
      return { cells, u, v, C, gt: (1 - u - v + C) / (1 - u), obs: obs / x.length, at: rep.spec.options.calcAt, dists: m.columns.map(c => c.chosen.dist) };
    })()''' % (X, Y, X, Y, X, Y))
    check('the calculator keeps its point', r['at'], {'x': 20, 'y': 3.5})
    check('the margins it uses: Weibull and lognormal', r['dists'], ['weibull', 'lognormal'])
    cells = {row[0]: row for row in r['cells']}
    check.near('P(X ≤ x) = the Weibull cdf', num(cells[f'P({X} ≤ x)'][1]), round(r['u'], 4), tol=1e-9)
    check.near('P(Y ≤ y) = the lognormal cdf', num(cells[f'P({Y} ≤ y)'][1]), round(r['v'], 4), tol=1e-6)
    check.near('P(both ≤) = C(u, v) of the fitted Clayton copula, computed here', num(cells[f'P({X} ≤ x and {Y} ≤ y)'][1]), r['C'], tol=6e-4)
    check.near('P(Y > y | X > x) = (1 − u − v + C)/(1 − u)', num(cells[f'P({Y} > y | {X} > x)'][1]), r['gt'], tol=6e-4)
    check.near('independence: uv', num(cells[f'P({X} ≤ x and {Y} ≤ y)'][2]), r['u'] * r['v'], tol=6e-4)
    check.near('the observed share', num(cells[f'P({X} ≤ x and {Y} ≤ y)'][3]), r['obs'], tol=1e-9)

    # ---- tail concentration, goodness of fit
    await page.ev(pick_js('Dependence', ['Tail Concentration Function']))
    st = await page.ev(STATE)
    check('the tail concentration function, one panel per copula', 'Tail Concentration Function' in st['outlines'], True)
    await page.ev(pick_form_js('Copula Comparison', ['Goodness of Fit…'], "const i = d.querySelectorAll('.sm-form input'); i[0].value = '30'; i[1].value = '3';"), timeout=900)
    gf = await page.ev(table_under_js('Goodness of Fit', 0))
    ps_ = {row[0]: num(row[2]) for row in gf[1:]}
    check('goodness of fit: Clayton is not rejected, independence is', (ps_['Clayton'] > 0.05, ps_['Independence'] < 0.05), (True, True))
    check('in the order of the comparison', gf[1][0], 'Clayton')
    st = await page.ev(STATE)
    check('Redo keeps the bootstrap settings', st['options'].get('gof'), {'B': 30, 'seed': 3})
    await shot(page, 'copula-02-options.png')

    # ---- Simulate: a new table, the same as the engine's draws
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await (%s)('*top*', ['Simulate…'], false, 0);
      for (let i = 0; i < 60 && !document.querySelector('.sm-dialog'); i++) await new Promise(r => setTimeout(r, 100));
      const d = [...document.querySelectorAll('.sm-dialog')].pop();
      const inputs = d.querySelectorAll('.sm-form input');
      inputs[0].value = '600'; inputs[1].value = '5';
      const nt = SM.app.tables.length;
      const done = new Promise(res => rep.on('done', res));
      d.querySelector('.sm-dialog-foot .primary').click();
      await done;
      for (let i = 0; i < 60 && SM.app.tables.length === nt; i++) await new Promise(r => setTimeout(r, 100));
      const t = SM.app.tables[SM.app.tables.length - 1];
      const src = rep.table;
      const fit = await SM.engine.call('copula.fit', { table: src.id, rows: null, columns: ['%s', '%s'], families: rep.spec.options.families, method: 'mpl', rotations: 'auto', se: rep.spec.options.se }, src);
      const m = await SM.engine.call('copula.margins', { table: src.id, rows: null, columns: ['%s', '%s'] }, src);
      const f = fit.fits.find(f => f.family === 'clayton');
      const sim = await SM.engine.call('copula.simulate', { table: src.id, rows: null, columns: ['%s', '%s'], family: 'clayton', params: f.values, margins: m.columns.map(c => ({ dist: c.chosen.dist, values: c.chosen.values })), n: 600, seed: 5, scale: 'data' }, src);
      const same = t.columns.every((c, k) => c.values.every((v, i) => v === sim.values[k][i]));
      SM.app.showTab(SM.app.tabOf(rep));
      return { name: t.name, rows: t.nrows, cols: t.columns.map(c => c.name), notes: t.notes, same, outlines: [...rep.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent), sc: rep.spec.options.simCompare };
    })()''' % (PICK, X, Y, X, Y, X, Y), timeout=600)
    check('Simulate makes a table of 600 rows with the two columns', (r['name'], r['rows'], r['cols']), ('Drought simulated', 600, [X, Y]))
    check('its notes say how it was made', all(s in r['notes'] for s in ('Clayton copula', 'Weibull', 'Lognormal', 'seed 5')), True)
    check('its values are the engine\'s draws for that seed', r['same'], True)
    check('and the report compares them with the data', ('Simulated and Observed' in r['outlines'], r['sc']), (True, {'n': 600, 'seed': 5, 'scale': 'data'}))

    # ---- Save
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      await (%s)('*top*', ['Save', 'Pseudo-Observations'], false, 0);
      await new Promise(r => setTimeout(r, 400));
      const c = t.col('Pseudo[%s]');
      return c ? { v: [c.values[0], c.values[123]], n: t.nrows } : null;
    })()''' % (PICK, X))
    check.near('Save Pseudo-Observations: the ranks over n + 1', r['v'][1], ps['rx'][123], tol=1e-12)

    script = await page.ev('SM.app.reports[SM.app.reports.length - 1].pythonScript()')
    check('the script holds the statsmodels calls', all(s in script for s in ('ClaytonCopula', 'approx_hess', 'stats.rankdata', 'CopulaDistribution.rvs', 'def fit1(')), True)

    # ---- a project keeps the options, the column ids remapped
    await page.ev(pick_js(X, ['Gamma']))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports.find(r => r.platform.id === 'copula' && r.spec.options.calc);
      const t = rep.table;
      const j = JSON.parse(JSON.stringify({ format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] }));
      SM.app.loadProject(j);
      const back = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => { if (!back.body.classList.contains('is-running') && back.body.querySelector('.sm-ob')) res(); else back.on('done', res); });
      const x = back.table.col('%s');
      const mg = [...back.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === '%s');
      const chosen = mg ? [...mg.parentElement.querySelectorAll('table.sm-rt tbody tr')].filter(tr => tr.cells[0].textContent === '✓').map(tr => tr.cells[1].textContent) : null;
      const out = { newTable: back.table !== t, margin: back.spec.options[x.id + '|marginFamily'], chosen, calcAt: back.spec.options.calcAt, gof: back.spec.options.gof, errors: [...back.body.querySelectorAll('.sm-ob-error')].length,
                    heads: [...back.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent) };
      SM.app.closeTable(back.table);
      await new Promise(r => setTimeout(r, 100));
      const dl = [...document.querySelectorAll('.sm-dialog')].pop();
      const yes = dl && [...dl.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Close');
      if (yes) yes.click();
      return out;
    })()''' % (X, X), timeout=900)
    check('an opened project has its own table', r['newTable'], True)
    check('and keeps the margin chosen for soil moisture by its new column id', (r['margin'], r['chosen']), ('gamma', ['Gamma']))
    check('and the calculator\'s point and the bootstrap', (r['calcAt'], r['gof']), ({'x': 20, 'y': 3.5}, {'B': 30, 'seed': 3}))
    check('and draws the same outlines without errors', ('Joint Probabilities' in r['heads'], 'Goodness of Fit' in r['heads'], r['errors']), (True, True, 0))

    # ---- By: one analysis per region, combined tables
    rep = await page.ev(open_report_js('copula', {'y': [X, Y], 'by': ['region']}, {}), timeout=300)
    check('By region: one analysis per region', [o for o in rep['outlines'] if o.startswith('Copulas of')], [f'Copulas of {X} and {Y} region=North', f'Copulas of {X} and {Y} region=South'])
    r = await page.ev('''(() => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const tbls = [...rep.body.querySelectorAll('table.sm-rt')].filter(t => t.dataset.rtKey === 'comparison');
      const combined = SM.report.combineRT(tbls, 'x');
      const t = rep.table; const reg = t.col('region').values;
      return { n: tbls.length, groups: tbls.map(t => t.dataset.group), rows: combined.nrows, each: tbls.map(t => t._rt.rows.length), north: reg.filter(v => v === 'North').length,
               notes: [...rep.body.querySelectorAll('.sm-ob-note')].map(e => e.textContent).filter(t => /rows with a value in every column/.test(t)) };
    })()''')
    check('each group has its comparison, which combine into one table', (r['n'], r['groups'], r['rows']), (2, ['region=North', 'region=South'], sum(r['each'])))
    check('each group fits its own rows', r['notes'][0].startswith(f"{r['north']} rows"), True)

    # ---- three columns: the scatterplot matrix and the elliptical copulas
    await page.ev('''(() => {
      const r = SM.util.rng('three columns');
      const n = 300, a = [], b = [], c = [];
      for (let i = 0; i < n; i++) { const z1 = r.normal(), z2 = 0.6 * z1 + 0.8 * r.normal(), z3 = -0.5 * z1 + Math.sqrt(0.75) * r.normal(); a.push(z1); b.push(Math.exp(z2)); c.push(z3 * 3 + 10); }
      SM.app.addTable(new SM.Table({ name: 'Three', source: 'simulated', columns: [{ name: 'a', dataType: 'numeric', values: a }, { name: 'b', dataType: 'numeric', values: b }, { name: 'c', dataType: 'numeric', values: c }] }));
    })()''')
    rep = await page.ev(open_report_js('copula', {'y': ['a', 'b', 'c']}, {}), timeout=300)
    check('three columns: a scatterplot matrix, no errors', ('Scatterplot Matrix' in rep['outlines'], rep['errors']), (True, []))
    cmp3 = await page.ev(table_under_js('Copula Comparison', 0))
    check('three columns: the Gaussian, t and independence copulas only', sorted(row[0] for row in cmp3[1:]), ['Gaussian', 'Independence', 'Student t'])
    check('the Gaussian copula (the truth) has the smallest BIC', min(cmp3[1:], key=lambda row: num(row[-1]))[0], 'Gaussian')
    pe3 = await page.ev(table_under_js('Copula Comparison', 1))
    rho = {row[1]: num(row[2]) for row in pe3[1:] if row[0] == 'Gaussian'}
    check('its correlations near the truth (0.6, −0.5, −0.3)', max(abs(rho['ρ(a, b)'] - 0.6), abs(rho['ρ(a, c)'] + 0.5), abs(rho['ρ(b, c)'] + 0.3)) < 0.1, True)
    got = await page.ev(pick_js('Pseudo-Observations', ['Pair', 'b and c']))
    pp3 = await page.ev(PSEUDO)
    if not check('Pair picks the pair drawn', pp3['title'], 'Pseudo-observations of b and c'):
        print('   ', got)
    await triangles(page, 'the three-column report', 4)
    await shot(page, 'copula-03-three.png')

    # ---- negative dependence: the 90° and 270° rotations, the corner tails
    await page.ev('''(() => {
      const t = SM.app.tables.find(t => t.name === 'Drought');
      const y = t.col('%s').values;
      t.addColumn({ name: 'dryness', dataType: 'numeric', values: y.map(v => -v) });
    })()''' % Y)
    await page.ev('SM.app.showTable(SM.app.tables.find(t => t.name === "Drought").id)')
    rep = await page.ev(open_report_js('copula', {'y': [X, 'dryness']}, {}), timeout=300)
    cmpn = await page.ev(table_under_js('Copula Comparison', 0))
    famn = [row[0] for row in cmpn[1:]]
    check('negative τ: Clayton turned by 90° or 270° is best (the example\'s Clayton, flipped)', famn[0] in ('Clayton (90°)', 'Clayton (270°)'), True)
    check('and no unrotated Clayton or Gumbel', ('Clayton' in famn, 'Gumbel' in famn), (False, False))
    hd = await page.ev(table_under_js('Dependence', 1))
    check('the corner tails are shown', ('λ Upper Left' in hd[0], 'λ Lower Right' in hd[0]), (True, True))
    await shot(page, 'copula-04-negative.png')

    # ---- the (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helps = await page.ev('(() => { SM.app.showHelp("p-copula"); const row = document.getElementById("help-p-copula"); return row ? row.textContent : null; })()')
    check('the platform has its line in Help, with statsmodels\' copulas', bool(helps) and 'statsmodels.distributions.copula' in helps, True)
    topics = await page.ev('Object.keys(SM.platforms.get("copula").topics)')
    check('its topics', sorted(topics), sorted(['p:copula', 'p:copula:pseudo', 'p:copula:dependence', 'p:copula:tails', 'p:copula:comparison', 'p:copula:gof', 'p:copula:margins', 'p:copula:joint', 'p:copula:simulate']))

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "copula" && r.spec.options.calc)))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(2.5)
    st = await page.ev('''(() => { const rs = SM.app.reports.filter(r => r.platform.id === 'copula'); return { errors: rs.flatMap(r => [...r.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent)) }; })()''')
    check('the dark theme redraws the reports without errors', st['errors'], [])
    col = await page.ev('(() => { const rep = SM.app.reports.find(r => r.platform.id === "copula" && r.spec.options.calc); const p = rep.plots.find(p => /^Pseudo-observations of/.test(p.opts.title)); return p.traces.find(t => t.type === "contour").line.color; })()')
    check('the contours take the dark theme\'s colour', col, '#9085e9')
    await shot(page, 'copula-05-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    await page.ev('(async () => { const rep = SM.app.reports.find(r => r.platform.id === "copula" && r.spec.options.calc); const d = new Promise(res => rep.on("done", res)); rep.run(); await d; })()')
    await asyncio.sleep(1.0)
    r = await page.ev('''(() => {
      const rep = SM.app.reports.find(r => r.platform.id === "copula" && r.spec.options.calc);
      const body = rep.body.getBoundingClientRect();
      const boxes = rep.plots.filter(p => p.drawn).map(p => p.box.getBoundingClientRect().right);
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length,
               body: rep.body.scrollWidth <= rep.body.clientWidth + 1, scrollers: [...rep.body.querySelectorAll('.sm-cop-scroll, table.sm-rt, table.sm-kv')].some(s => s.scrollWidth > s.clientWidth) };   // the core's tables scroll in their own box too
    })()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the graphs fit the phone\'s width', (r['plots'], r['n'] >= 2), (True, True))
    check('wide tables scroll inside their own boxes, not the whole report', (r['body'], r['scrollers']), (True, True))
    await shot(page, 'copula-06-phone.png')

    # ---- help for every input: the launch dialog's (i), the forms' (i), the report's controls
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 1200, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await page.ev(HELP_JS)
    check('help: back on the Drought table', await page.ev('__hp.showTable("Drought")'), True)
    await check_launch_help(page, 'copula', settings=['Copulas to Fit', 'Rotations', 'Estimation', 'Fit Margins'], what='copula: the launch dialog')
    await page.ev(f'''(async () => {{ const t = SM.app.tables.find((x) => x.name === 'Drought'); const rep = SM.app.openReport(SM.platforms.get('copula'), {{ roles: {{ y: [t.col({json.dumps(X)}).id, t.col({json.dumps(Y)}).id] }}, options: {{ margins: true, calc: true }} }}, t);
      await new Promise((r) => rep.on('done', r)); SM.app.showTab(SM.app.tabOf(rep)); return rep.title; }})()''', timeout=300)
    rep = 'SM.app.reports[SM.app.reports.length - 1]'
    await check_form_help(page, f"await __hp.menu({rep}, null, ['Goodness of Fit…'])", ['Bootstrap samples', 'Random seed'], 'copula: Goodness of Fit…')
    await check_form_help(page, f"await __hp.menu({rep}, null, ['Simulate…'])", ['Number of rows', 'Random seed', 'Values', 'Compare with the data in this report'], 'copula: Simulate…')
    await check_controls_help(page, rep, 'Copula Comparison', ['A line of the Fits table', 'Right click a table'], 'copula: Copula Comparison')
    await check_controls_help(page, rep, 'Margins', ['A line of Fitted Distributions', 'A column\'s red triangle'], 'copula: Margins')
    await check_controls_help(page, rep, 'Joint Probabilities', ['x and y', 'Compute'], 'copula: Joint Probabilities')
    await chart_code(page)
    check('no script errors', page.errors, [])
    await page.close()


# ---- the graphs' matplotlib code -------------------------------------------------------------------------------------
# Each graph has a code block right under it (details.sm-code, ending in
# plt.show()); the block runs in the page's own Python (SM.engine.runCell, as
# test_charts.GRAPHS_JS.run does) with test_charts.PROBE_MORE in place of
# plt.show() (and the code's density grid z asked for), and the figure it
# draws is compared with the Plotly graph above it. __kc adds the tail
# panels' titles (annotations), which GRAPHS_JS does not collect.
CHART_JS = r'''
window.__kc = {
  ann(rep) { return [...rep.body.querySelectorAll('.js-plotly-plot')].map((p) => ((p.layout || {}).annotations || []).map((a) => a.text)); },
};
'''


async def run_more(page, g, table_js, names=()):
    out = await page.ev(f'__gr.run({json.dumps(page_probe_more(g["code"], names))}, {table_js})', timeout=900)
    if isinstance(out, str):
        return None, None, out
    got, err = more_from_outputs(out.get('outputs'))
    return (got['figures'] if got else None), (got['vars'] if got else None), err


def rgap(a, b):
    """The largest relative difference of two lists of numbers (inf when their lengths or gaps differ)."""
    a, b = list(a or []), list(b or [])
    if len(a) != len(b):
        return float('inf')
    worst = 0.0
    for x, y in zip(a, b):
        if (x is None) != (y is None):
            return float('inf')
        if x is None:
            continue
        worst = max(worst, abs(x - y) / max(1e-300, abs(x), abs(y)))
    return worst


def pts_gap(xy, t, abs_=0.0):
    """The points of a probe's scatter against a Plotly trace's: the largest
    relative difference, differences below abs_ counted as none."""
    if not xy or len(xy) != len(t['x'] or []):
        return float('inf')
    worst = 0.0
    for (a, b), x, y in zip(xy, t['x'], t['y']):
        for p, q in ((a, x), (b, y)):
            if abs(p - q) > abs_:
                worst = max(worst, abs(p - q) / max(1e-300, abs(p), abs(q)))
    return worst


def levels_of(ax):
    return [p['contour'][0] for p in ax['polys'] if 'contour' in p]


def flat(z):
    return [v for row in z for v in row]


async def chart_code(page):
    await page.ev(GRAPHS_JS)
    await page.ev(CHART_JS)
    await page.ev('__gr.idle()')
    await page.ev('''(() => {
      const r = SM.util.rng('three columns for the charts');
      const n = 240, a = [], b = [], c = [];
      for (let i = 0; i < n; i++) { const z1 = r.normal(), z2 = 0.6 * z1 + 0.8 * r.normal(), z3 = -0.5 * z1 + Math.sqrt(0.75) * r.normal(); a.push(z1); b.push(Math.exp(z2)); c.push(z3 * 3 + 10); }
      SM.app.addTable(new SM.Table({ name: 'Three charts', source: 'simulated', columns: [{ name: 'a', dataType: 'numeric', values: a }, { name: 'b', dataType: 'numeric', values: b }, { name: 'c', dataType: 'numeric', values: c }] }));
    })()''')
    runs = [
        ('Drought, Clayton shown, two rows excluded', 'Drought', [X, Y], [1, 4], {'margins': True, 'tails': True, 'shown': 'clayton', 'simCompare': {'n': 300, 'seed': 3, 'scale': 'data'}}, {}),
        ('Drought, normal scores, survival Gumbel, a normal and an empirical margin', 'Drought', [X, Y], [], {'margins': True, 'scale': 'normal', 'shown': 'gumbel180', 'simCompare': {'n': 200, 'seed': 5, 'scale': 'uniform'}},
         {X: 'normal', Y: 'empirical'}),
        ('Drought, from Kendall\'s τ, the t copula shown', 'Drought', [X, Y], [], {'method': 'itau', 'tails': True, 'shown': 't', 'margins': True, 'simCompare': {'n': 150, 'seed': 2, 'scale': 'data'}}, {}),
        ('three columns, the pair b and c', 'Three charts', ['a', 'b', 'c'], [], {'pair': [1, 2], 'margins': True, 'shown': 'gaussian'}, {}),
    ]
    for label, tname, ys, excl, options, margins in runs:
        tj = f"SM.app.tables.find((t) => t.name === {json.dumps(tname)})"
        if excl:
            await page.ev(f"{tj}.setState({json.dumps(excl)}, 'excluded', true)")
        r = await page.ev(f'''(async () => {{ const t = {tj}; SM.app.showTab(SM.app.tabOf(t)); const o = {json.dumps(options)};
          for (const [n, v] of Object.entries({json.dumps(margins)})) o[t.col(n).id + '|marginFamily'] = v;
          const rep = SM.app.openReport(SM.platforms.get('copula'), {{ roles: {{ y: {json.dumps(ys)}.map((n) => t.col(n).id) }}, options: o }}, t);
          await new Promise((res) => rep.on('done', res)); SM.app.showTab(SM.app.tabOf(rep));
          return {{ g: await __gr.graphs(rep), ann: __kc.ann(rep), errors: [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent), undrawn: __gr.take() }}; }})()''', timeout=1200)
        if excl:
            await page.ev(f"{tj}.setState({json.dumps(excl)}, 'excluded', false)")
        if not isinstance(r, dict):
            check(f'charts: {label}: the report', r, 'opens')
            continue
        check(f'charts: {label}: no errors', r['errors'], [])
        check(f'charts: {label}: every graph of the report drawn', r['undrawn'], [])
        labels = [g['label'] for g in r['g']]
        want = (['Scatterplot matrix of the pseudo-observations'] if len(ys) > 2 else []) + [f'Pseudo-observations of {ys[options.get("pair", [0, 1])[0]]} and {ys[options.get("pair", [0, 1])[1]]}']
        check(f'charts: {label}: the graphs begin as the page\'s', labels[:len(want)], want)
        for g, ann in zip(r['g'], r['ann']):
            lab = f'charts: {label}: {g["label"]}'
            check(f'{lab}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
            if not g['code']:
                continue
            if excl:
                check(f'{lab}: the code leaves out the excluded rows', f'df = df.drop(index={excl})' in g['code'], True)
            F, V, err = await run_more(page, g, tj, ('z',))
            check(f'{lab}: the code runs in the page', err, None)
            if not F:
                continue
            F = F[0]
            t0 = g['traces']
            if g['label'].startswith('Pseudo-observations') or g['label'].endswith('with the joint model'):
                ax = F['axes'][0]
                pts = [t for t in t0 if t.get('mode') == 'markers' and t.get('name') in ('Pseudo-observations', 'Data')][0]
                # normal scores: the page's Φ⁻¹ is Acklam's approximation (relative error 1.2e-9), the code's scipy's
                check(f'{lab}: the points, the page\'s', pts_gap(ax['scatter'][0]['xy'], pts, 1e-8) < 1e-9, True)
                cons = [t for t in t0 if t.get('type') == 'contour']
                tol = 1e-3 if g['label'].endswith('joint model') else 1e-7   # the joint model's margins: scipy's fit against the report's refinement of it
                check(f'{lab}: the contour levels, the page\'s', rgap(levels_of(ax), [t['contours']['start'] for t in cons]) < tol, True)
                if cons:
                    check(f'{lab}: the density grid under them, the page\'s', rgap(V.get('z'), flat(cons[0]['z'])) < tol, True)
                check(f'{lab}: the axis titles and the title', (ax['xlabel'], ax['ylabel'], ax['title']), (g['titles']['x'], g['titles']['y'], g['label']))
            elif g['label'].startswith('Scatterplot matrix'):
                cells = [a for a in F['axes'] if a['shown']]
                sc = [t for t in t0 if t.get('mode') == 'markers']
                check(f'{lab}: a cell for each pair', len(cells), len(sc))
                ok_p = all(pts_gap(a['scatter'][0]['xy'], t, 1e-8) < 1e-9 for a, t in zip(cells, sc))
                check(f'{lab}: each cell\'s points, the page\'s', ok_p, True)
                ok_l = True
                for a, t in zip(cells, sc):
                    cons = [c for c in t0 if c.get('type') == 'contour' and c.get('xaxis') == t.get('xaxis') and c.get('yaxis') == t.get('yaxis')]
                    ok_l &= rgap(levels_of(a), [c['contours']['start'] for c in cons]) < 1e-7
                check(f'{lab}: each cell\'s contour levels, the page\'s', ok_l, True)
                check(f'{lab}: the title', F['suptitle'], g['label'])
            elif g['label'].startswith('Tail concentration'):
                panels = [a for a in F['axes'] if a['shown']]
                check(f'{lab}: a panel for each copula, titled as the page\'s', [a['title'] for a in panels], ann)
                data_t = [t for t in t0 if t.get('name') == 'Data']
                line_t = [t for t in t0 if t.get('mode') == 'lines']
                ok_d = all(pts_gap(a['scatter'][0]['xy'], d) < 1e-12 for a, d in zip(panels, data_t))
                check(f'{lab}: the data\'s dots in each panel, the page\'s', ok_d, True)
                ok_l = all(rgap([ln for ln in a['lines'] if ln['color'].startswith('#b0413e')][0]['y'], t['y']) < 1e-7 for a, t in zip(panels, line_t))
                check(f'{lab}: each copula\'s line, the page\'s', ok_l, True)
                check(f'{lab}: the title', F['suptitle'], g['label'])
            elif g['label'].endswith('histogram with its margin'):
                ax = F['axes'][0]
                b = [t for t in t0 if t.get('type') == 'bar' and t.get('name')][0]
                check(f'{lab}: the bars, the page\'s', rgap([q['x'] + q['w'] / 2 for q in ax['bars']], b['x']) < 1e-9 and [q['h'] for q in ax['bars']] == list(b['y']) and rgap([ax['bars'][0]['w']], [b['width']]) < 1e-12, True)
                cv = [t for t in t0 if t.get('mode') == 'lines']
                check(f'{lab}: the margin\'s curve, the page\'s', bool(cv) and rgap(ax['lines'][0]['x'], cv[0]['x']) < 1e-9 and rgap(ax['lines'][0]['y'], cv[0]['y']) < 1e-3, True)
                check(f'{lab}: the axis titles and the title', (ax['xlabel'], ax['ylabel'], ax['title']), (g['titles']['x'], g['titles']['y'], g['label']))
            else:
                ax = F['axes'][0]
                sim = [t for t in t0 if t.get('name') == 'Simulated'][0]
                obs = [t for t in t0 if t.get('name') == 'Observed'][0]
                got = {x['label']: x['xy'] for x in ax['scatter']}
                uniform = options['simCompare']['scale'] == 'uniform'
                check(f'{lab}: the draws, the page\'s (the same seed)', pts_gap(got.get('Simulated'), sim) < (1e-9 if uniform else 1e-3), True)
                check(f'{lab}: the observed rows, the page\'s', pts_gap(got.get('Observed'), obs) < 1e-12, True)
                check(f'{lab}: the legend, the axis titles, the title', (F['legend'], ax['xlabel'], ax['ylabel'], ax['title']), (['Simulated', 'Observed'], g['titles']['x'], g['titles']['y'], g['label']))
        await page.ev('SM.app.closeReport(SM.app.reports[SM.app.reports.length - 1])')


asyncio.run(main())
sys.exit(check.done())
