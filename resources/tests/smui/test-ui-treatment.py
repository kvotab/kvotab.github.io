#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Specialized Modeling > Treatment
Effects.

treatment.py imports in Pyodide; the platform is in the menu and its
example table (Job training, simulated with a known effect) in File >
Examples and on the Home tab; the launch dialog casts the roles and offers
the treated level; the report has its outlines and no errors; the
difference in means, the IPW estimate and a standardized mean difference
shown are the ones formulas written in the page give from the table and the
report's propensity scores; the adjusted estimates are near the true effect
and the difference in means is not; a histogram bar of the overlap selects
its rows and a table selection lights up the bars; a line of the largest
weights selects its row; the red triangles change the estimators, the
effect on the treated, the treatment model, the treated level and the
trimming, add the outcome models, and save the propensity scores and the
weights; every red triangle opens with its submenus; By gives a report per
level; a 0/1 outcome is said to be one; a three-level treatment is refused
in the dialog; the options survive a project saved and opened; every (i)
has a topic and Help has the platform; the report draws in the dark theme
and at phone width.

Start a server on the repository root and headless Chrome (the recipe is in
README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-treatment.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import json
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
TOP = 'Treatment Effects of program on earnings'
COVS = ['age', 'education', 'prior earnings', 'region']


async def shot(page, name, scroll=None):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        if scroll is not None:
            await page.ev(f'(() => {{ const rep = SM.app.reports.find(r => r.el.offsetParent !== null); const h = rep && [...rep.body.querySelectorAll(".sm-ob-head h3")].find(h => h.textContent === {json.dumps(scroll)}); if (h) rep.body.scrollTop = h.closest(".sm-ob").offsetTop - 10; }})()')
        await asyncio.sleep(0.9)
        await page.shot(os.path.join(SHOTS, name))


# Pick an item from an outline's red triangle: path is the labels down the
# submenus. wait: wait for the report to run again.
PICK = '''
(async (title, path, wait) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.querySelector('h2, h3, h4').textContent.trim() === title);
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


def pick_js(title, path, wait=True):
    return f'({PICK})({json.dumps(title)}, {json.dumps(path)}, {json.dumps(wait)})'


# Fill the open form dialog (its first input) and press OK; wait for the report.
FORM = '''
(async (value) => {
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await new Promise(r => setTimeout(r, 120));
  const dlgs = [...document.querySelectorAll('.sm-dialog')];
  const d = dlgs[dlgs.length - 1];
  const inp = d.querySelector('input');
  inp.value = value;
  const done = new Promise(res => rep.on('done', res));
  [...d.querySelectorAll('.sm-dialog-foot button')].find(b => b.textContent === 'OK').click();
  await done;
  return true;
})
'''

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

# The report's propensity scores, from the engine as the report asked for them.
SCORES = '''
(async (extra) => {
  const t = SM.app.tables.find(t => t.name === 'Job training');
  const r = await SM.engine.call('treatment.fit', { rows: null, y: 'earnings', treatment: 'program', treated: 1, outcome: %s, ...(extra || {}) }, t);
  return r.scores;
})
''' % json.dumps(COVS)


def number(s):
    return float(s.replace('−', '-').replace('*', '').replace('<', ''))


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
    page = await open_page(f'{BASE}/smui.html?example=program', height=1100)
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "treatment").map(f => f.module + ": " + f.error)')
    check('treatment.py imports in Pyodide', failed, [])
    check('no script errors at load', page.errors, [])

    # ---- the menu, the example, Help
    menus = await page.ev('''(() => {
      const an = SM.app.menuItems('Analyze');
      const it = an.find(i => i.label === 'Specialized Modeling');
      const sm = (typeof it.submenu === 'function' ? it.submenu() : it.submenu).filter(i => !i.separator).map(i => i.label);
      const file = SM.app.menuItems('File').find(i => i.label === 'Examples');
      const ex = (typeof file.submenu === 'function' ? file.submenu() : file.submenu).map(i => i.label);
      const home = [...document.querySelectorAll('.sm-exitem strong')].map(x => x.textContent);
      return { sm, ex, home };
    })()''')
    check('Analyze > Specialized Modeling lists Treatment Effects', 'Treatment Effects…' in menus['sm'], True)
    check('File > Examples has the job-training table', 'Job training (1000 people): program, earnings' in menus['ex'], True)
    check('and the Home tab', 'Job training (1000 people): program, earnings' in menus['home'], True)
    ex = await page.ev('''(() => { const t = SM.app.current; return { name: t.name, n: t.nrows, cols: t.columns.map(c => c.name + ':' + c.modelingType), notes: t.notes, truth: SM.io.EXAMPLES.program.truth }; })()''')
    check('the example table', (ex['name'], ex['n']), ('Job training', 1000))
    check('its columns', ex['cols'], ['id:nominal', 'age:continuous', 'education:continuous', 'prior earnings:continuous', 'region:nominal', 'program:nominal', 'earnings:continuous', 'employed:nominal'])
    truth = ex['truth']
    check('its notes state the true ATE, computed from the simulation', f'{round(truth["ate"]):,}'.replace(',', '') in ex['notes'].replace(',', ''), True)
    check('and the true ATT', f'{round(truth["att"])}' in ex['notes'].replace(',', ''), True)
    helps = await page.ev('(() => { const h = document.getElementById("help-p-treatment"); return h ? h.textContent : null; })()')
    check('Help has the platform, with statsmodels\' TreatmentEffect', bool(helps) and 'TreatmentEffect' in helps, True)

    # ---- the launch dialog
    r = await page.ev('''(async () => {
      SM.app.launch('treatment');
      await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const items = [...dlg.querySelectorAll('.sm-pick-list li')];
      const cast = (name, role) => {
        items.forEach(li => li.classList.remove('is-selected'));
        const li = items.find(x => x.textContent === name);
        li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === role).click();
      };
      const sel = dlg.querySelector('.sm-te-launch select');
      const before = sel.disabled;
      cast('earnings', 'Y, Outcome'); cast('program', 'Treatment');
      for (const c of ['age', 'education', 'prior earnings', 'region']) cast(c, 'Outcome Covariates');
      const levels = [...sel.options].map(o => o.textContent);
      const chosen = sel.value;
      const roles = [...dlg.querySelectorAll('.sm-role-list')].map(u => [...u.querySelectorAll('li')].map(li => li.textContent));
      return { before, levels, chosen, roles };
    })()''')
    await shot(page, 'treatment-00-launch.png')
    r2 = await page.ev('''(async () => {
      const dlg = document.querySelector('.sm-launch-dialog');
      [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
      const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res));
      return { title: rep.title, treated: rep.spec.options.treated, link: rep.spec.options.link,
               outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
               errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent), warns: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent) };
    })()''', timeout=300)
    r.update(r2)
    check('the treated level waits for the treatment', r['before'], True)
    check('then offers its levels', r['levels'], ['0', '1'])
    check('the last level is the treated one by default', r['chosen'], '1')
    check('the roles cast', r['roles'][:3], [['earnings'], ['program'], COVS])
    check('the options: treated level and treatment model', (r['treated'], r['link']), (1, 'logit'))
    check('report title', r['title'], TOP)
    check('the outlines', r['outlines'], [TOP, 'Treatment Effect Estimates', 'Propensity Score Model', 'Overlap', 'Covariate Balance', 'Weights', 'Assumptions and Estimators'])
    check('no errors or warnings in the report', (r['errors'], r['warns']), ([], []))
    await shot(page, 'treatment-01-estimates.png')

    # ---- the numbers, against formulas in the page
    ate = await page.ev(table_under_js('Treatment Effect Estimates', 0))
    check('ATE table: the unadjusted difference and the five estimators', [row[0] for row in ate[1:]], ['Difference in Means (unadjusted)', 'IPW', 'AIPW', 'AIPW (WLS)', 'RA', 'IPW-RA'])
    js = await page.ev('''(async () => {
      const t = SM.app.tables.find(t => t.name === 'Job training');
      const y = t.col('earnings').values, T = t.col('program').values, age = t.col('age').values;
      const m = (f) => { let s = 0, n = 0; for (let i = 0; i < t.nrows; i++) if (f(i)) { s += y[i]; n++; } return s / n; };
      const naive = m(i => T[i] === 1) - m(i => T[i] === 0);
      const sc = await (%s)();
      let a1 = 0, b1 = 0, a0 = 0, b0 = 0;
      sc.rows.forEach((r, k) => { const p = sc.ps[k]; if (T[r] === 1) { a1 += y[r] / p; b1 += 1 / p; } else { a0 += y[r] / (1 - p); b0 += 1 / (1 - p); } });
      const g = (v) => { const x = sc.rows.filter(r => T[r] === v).map(r => age[r]); const mu = x.reduce((a, b) => a + b, 0) / x.length; return [mu, x.reduce((a, b) => a + (b - mu) ** 2, 0) / (x.length - 1)]; };
      const [m1, v1] = g(1), [m0, v0] = g(0);
      return { naive: SM.util.fmt(naive), ipw: SM.util.fmt(a1 / b1 - a0 / b0), smd: (m1 - m0) / Math.sqrt((v1 + v0) / 2) };
    })()''' % SCORES)
    check('the difference in means is the one computed in the page', ate[1][1], js['naive'])
    check('IPW = sum(t y/p)/sum(t/p) - sum((1-t) y/(1-p))/sum((1-t)/(1-p)), in the page from the report\'s scores', ate[2][1], js['ipw'])
    bal = await page.ev(table_under_js('Covariate Balance', 0))
    check('the SMD of age, computed in the page', bal[1][1], f'{js["smd"]:.3f}'.replace('-', '−'))
    est = {row[0]: row for row in ate[1:]}
    for name in ('IPW', 'AIPW', 'RA', 'IPW-RA', 'AIPW (WLS)'):
        e, se = number(est[name][1]), number(est[name][2])
        check(f'{name} ({e:.0f}) is within 3 standard errors of the true ATE {truth["ate"]:.0f}', abs(e - truth['ate']) < 3 * se, True)
    nv, nse = number(est['Difference in Means (unadjusted)'][1]), number(est['Difference in Means (unadjusted)'][2])
    check(f'the unadjusted difference ({nv:.0f}) is far from it (more than 5 standard errors)', abs(nv - truth['ate']) > 5 * nse, True)
    att = await page.ev(table_under_js('Treatment Effect Estimates', 1))
    check('ATT table: IPW, RA, IPW-RA', [row[0] for row in att[1:]], ['IPW', 'RA', 'IPW-RA'])
    for row in att[1:]:
        check(f'ATT {row[0]} is within 3 standard errors of the true ATT {truth["att"]:.0f}', abs(number(row[1]) - truth['att']) < 3 * number(row[2]), True)
    pom = await page.ev(table_under_js('Treatment Effect Estimates', 2))
    check('Potential Outcome Means: observed, then the estimators', [row[0] for row in pom[1:]], ['Observed (unadjusted)', 'IPW', 'AIPW', 'AIPW (WLS)', 'RA', 'IPW-RA'])
    check('the POM columns name the levels', (pom[0][1], pom[0][3]), ('POM(program = 0)', 'POM(program = 1)'))
    ps = await page.ev(table_under_js('Propensity Score Model', 2))   # after the Whole Model Test and the fit statistics
    check('propensity model terms, effect coded in the table\'s level order', [row[0] for row in ps[1:8]], ['Intercept', 'region[North]', 'region[South]', 'region[East]', 'age', 'education', 'prior earnings'])
    code = await page.ev('SM.app.reports[SM.app.reports.length - 1].pythonScript()')
    check('the Python script has TreatmentEffect, the slice patch and the standardized designs', all(s in code for s in ('TreatmentEffect', 'params[2 * k + 1:]', 'standardize(Z)', 'sm.Logit(t, Z)')), True)

    # ---- linking
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots.find(p => p.opts.title === 'propensity score overlap');
      const counts = p.traces[0].y; let j = 0; counts.forEach((c, k) => { if (c > counts[j]) j = k; });
      p._click({ points: [{ curveNumber: 0, pointNumber: j }], event: {} });
      const sel = t.selectedRows();
      const sc = await (%s)();
      const ps = new Map(sc.rows.map((r, k) => [r, sc.ps[k]]));
      const size = 0.05, lo = j * size, hi = (j + 1) * size;
      const inBin = sel.every(r => ps.get(r) >= lo - 1e-12 && ps.get(r) < hi + 1e-12);
      const treated = sel.every(r => t.col('program').values[r] === 1);
      t.select([sc.rows[0], sc.rows[1], sc.rows[2]]);
      await new Promise(r => setTimeout(r, 200));
      const comp = p.companions.map(c => p.box.data[c.at].x.length);
      t.select([]);
      return { n: sel.length, count: counts[j], inBin, treated, comp };
    })()''' % SCORES)
    check('a click on an overlap bar selects its rows', r['n'], r['count'])
    check('... treated rows with a propensity score in that bin', (r['inBin'], r['treated']), (True, True))
    check('a table selection lights up the bars (both groups\' selected shares)', all(x > 0 for x in r['comp']) or sum(r['comp']) > 0, True)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const tb = [...rep.body.querySelectorAll('table.sm-rt')].find(x => x.querySelector('caption') && /Largest Weights/.test(x.querySelector('caption').textContent));
      const tr = tb.querySelector('tbody tr');
      const row = Number(tr.children[0].textContent) - 1;
      const w = Number(tr.children[3].textContent);
      tr.click();
      const sel = t.selectedRows();
      t.select([]);
      return { row, sel, w };
    })()''')
    check('a line of the largest weights selects its row', r['sel'], [r['row']])
    sc = await page.ev(f'({SCORES})()')
    check.near('it is the row with the largest IPW weight', r['w'], max(sc['w_ate']), 1e-4)
    await shot(page, 'treatment-02-overlap.png', 'Propensity Score Model')
    await shot(page, 'treatment-03-balance.png', 'Covariate Balance')

    # ---- the red triangles
    out = await page.ev(pick_js(TOP, ['Estimators', 'IPW']))
    ate2 = await page.ev(table_under_js('Treatment Effect Estimates', 0))
    check('Estimators: IPW off', [row[0] for row in ate2[1:]], ['Difference in Means (unadjusted)', 'AIPW', 'AIPW (WLS)', 'RA', 'IPW-RA'])
    await page.ev(pick_js(TOP, ['Estimators', 'IPW']))
    await page.ev(pick_js('Treatment Effect Estimates', ['Effect on the Treated (ATT)']))
    caps = await page.ev('[...SM.app.reports[SM.app.reports.length - 1].body.querySelectorAll("table.sm-rt caption")].map(c => c.textContent)')
    check('ATT off: no ATT table', any('ATT' in c for c in caps), False)
    await page.ev(pick_js('Treatment Effect Estimates', ['Effect on the Treated (ATT)']))
    out = await page.ev(pick_js(TOP, ['Treatment Model', 'Probit']))
    foot = await page.ev('(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; return [...rep.body.querySelectorAll("table.sm-rt tfoot")].map(f => f.textContent); })()')
    check('Treatment Model > Probit: the propensity model is a probit', any(f.startswith('Probit') for f in foot), True)
    ate3 = await page.ev(table_under_js('Treatment Effect Estimates', 0))
    check('... and the estimates change', ate3[2][1] != ate[2][1], True)
    await page.ev(pick_js(TOP, ['Treatment Model', 'Logit']))
    await page.ev(pick_js(TOP, ['Treated Level', '0']))
    ate4 = await page.ev(table_under_js('Treatment Effect Estimates', 0))
    check('Treated Level > 0: the effect turns round', ate4[1][1], ate[1][1][1:] if ate[1][1].startswith('−') else '−' + ate[1][1])
    await page.ev(pick_js(TOP, ['Treated Level', '1']))
    await page.ev(pick_js(TOP, ['Trim Propensity Scores…'], wait=False))
    await page.ev(f'({FORM})("0.05")')
    summ = await page.ev(table_under_js(TOP, 0))
    trimmed = [row for row in summ if row[0] == 'Rows trimmed']
    check('Trim at 0.05: the summary says how many rows go', bool(trimmed) and trimmed[0][1].startswith('4:'), True)
    sc_t = await page.ev(f'({SCORES})({{ trim: 0.05 }})')
    check('... and the rest are analysed', len(sc_t['rows']), 996)
    await page.ev(pick_js('Overlap', ['Select Trimmed Rows (4)'], wait=False))
    sel = await page.ev('SM.app.reports[SM.app.reports.length - 1].table.selectedRows()')
    full = await page.ev(f'({SCORES})()')
    ps_full = dict(zip(full['rows'], full['ps']))
    check('Select Trimmed Rows selects the rows outside [0.05, 0.95]', (len(sel), all(ps_full[x] < 0.05 or ps_full[x] > 0.95 for x in sel)), (4, True))
    await page.ev('SM.app.reports[SM.app.reports.length - 1].table.select([])')
    await shot(page, 'treatment-04-trimmed.png', 'Overlap')
    await page.ev(pick_js('Overlap', ['Remove Trimming']))
    await page.ev(pick_js('Overlap', ['Overlaid']))
    ov = await page.ev('(() => { const rep = SM.app.reports[SM.app.reports.length - 1]; const p = rep.plots.find(p => p.opts.title === "propensity score overlap"); return Math.min(...p.traces[1].y); })()')
    check('Overlaid: the controls are counted upwards', ov >= 0, True)
    await page.ev(pick_js('Overlap', ['Mirrored']))
    out = await page.ev(pick_js(TOP, ['Outcome Models']))
    check('Outcome Models: one per group', [o for o in out if o.startswith('Control:') or o.startswith('Treated:')], ['Control: program = 0', 'Treated: program = 1'])
    om = await page.ev(table_under_js('Control: program = 0', 1))
    check('their parameter estimates, with robust z ratios', (om[0][:4], om[1][0]), (['Term', 'Estimate', 'Std Error', 'z Ratio'], 'Intercept'))
    await shot(page, 'treatment-05-outcome.png', 'Outcome Models')
    n0 = await page.ev('SM.app.tables.find(t => t.name === "Job training").columns.length')
    await page.ev(pick_js(TOP, ['Save Columns', 'Propensity Score'], wait=False))
    await page.ev(pick_js(TOP, ['Save Columns', 'IPW Weight'], wait=False))
    saved = await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === "Job training"); const c = t.columns.slice(-2);
      return { n: t.columns.length, names: c.map(x => x.name), finite: c.map(x => x.values.filter(Number.isFinite).length), ps: c[0].values, w: c[1].values }; })()''')
    check('Save Columns adds the propensity score and the IPW weight', (saved['n'] - n0, saved['names']), (2, ['Propensity Score', 'IPW Weight']))
    check('for every row', saved['finite'], [1000, 1000])
    check.near('the saved scores are the report\'s', max(abs(a - b) for a, b in zip(saved['ps'], full['ps'])), 0.0, 1e-12)
    check.near('the saved weights are the report\'s', max(abs(a - b) for a, b in zip(saved['w'], full['w_ate'])), 0.0, 1e-9)
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports[SM.app.reports.length - 1]))')
    tri = await page.ev(TRIANGLES)
    check('every red triangle opens, with its submenus', (tri['errors'], tri['triangles'] >= 8, tri['items'] > tri['triangles']), ([], True, True))
    if tri['errors']:
        print('   ', tri)

    # ---- the options survive a project saved and opened
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      rep.spec.options.trim = 0.05; await rep.run();
      const text = (r) => [...r.body.querySelectorAll('table.sm-rt')][0].textContent;
      const t = rep.table;
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      const nrep = SM.app.reports.length;
      SM.app.loadProject(j);
      const r2 = SM.app.reports[nrep];
      await new Promise(res => r2.on('done', res));
      return { same: text(r2) === text(rep), opts: [r2.spec.options.treated, r2.spec.options.trim, r2.spec.options.outcomeModels] };
    })()''', timeout=300)
    check('a project keeps the options (treated level, trimming, outcome models)', r['opts'], [1, 0.05, True])
    check('... and gives the same estimates', r['same'], True)

    # ---- By, a 0/1 outcome, a three-level treatment
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === "Job training")))')
    r = await page.ev(open_report_js('treatment', {'y': ['earnings'], 'treatment': ['program'], 'outcome': ['age', 'education', 'prior earnings'], 'by': ['region']}, {'treated': 1}), timeout=300)
    check('By: a report per region', [o for o in r['outlines'] if o.startswith(TOP)], [f'{TOP} region={g}' for g in ('North', 'South', 'East', 'West')])
    check('By: no errors', r['errors'], [])
    r = await page.ev(open_report_js('treatment', {'y': ['employed'], 'treatment': ['program'], 'outcome': COVS}, {'treated': 1}), timeout=300)
    notes = await page.ev('[...SM.app.reports[SM.app.reports.length - 1].body.querySelectorAll(".sm-ob-note")].map(n => n.textContent).join(" ")')
    check('a 0/1 outcome: the effects are differences in proportions', 'employed is 0/1' in notes, True)
    check('no errors', r['errors'], [])
    v = await page.ev('''(() => { const t = SM.app.tables.find(t => t.name === "Job training"); const P = SM.platforms.get('treatment');
      const id = (n) => t.col(n).id;
      return [P.launch.validate({ roles: { y: [id('earnings')], treatment: [id('region')], outcome: [id('age')], covariates: [] } }, t),
              P.launch.validate({ roles: { y: [id('earnings')], treatment: [id('program')], outcome: [], covariates: [] } }, t),
              P.launch.validate({ roles: { y: [id('earnings')], treatment: [id('program')], outcome: [id('earnings')], covariates: [] } }, t)]; })()''')
    check('the dialog refuses a three-level treatment', v[0], 'Treatment takes a column with two levels; region has 4.')
    check('... no covariates', v[1].startswith('Give covariates'), True)
    check('... the outcome as a covariate', v[2], 'earnings is the outcome: take it out of the covariates.')

    # ---- separation: everyone in the East takes part
    r = await page.ev('''(async () => {
      const t = SM.app.tables.find(t => t.name === "Job training");
      const reg = t.col('region').values, prog = t.col('program').values.map((v, i) => (reg[i] === 'East' ? 1 : v));
      SM.app.addTable(new SM.Table({ name: 'Job training, East all in', columns: t.columns.filter(c => !['Propensity Score', 'IPW Weight'].includes(c.name)).map(c => ({ ...c, id: undefined, values: c.name === 'program' ? prog : c.values.slice() })) }));
      return SM.app.current.name;
    })()''')
    r = await page.ev(open_report_js('treatment', {'y': ['earnings'], 'treatment': ['program'], 'outcome': COVS}, {'treated': 1}), timeout=300)
    check('separation: the propensity model says which level', any('Quasi-complete separation' in w and 'region = East' in w for w in r['warnings']), True)
    check('... and the estimators that need the outcome model say why they cannot', any('singular' in w for w in r['warnings']), True)
    await shot(page, 'treatment-11-separation.png', 'Propensity Score Model')

    # ---- (i) topics
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])

    # ---- dark theme and phone width
    await page.ev('SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === "treatment" && !(r.spec.roles.by || []).length && r.title === "Treatment Effects of program on earnings")))')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(1.8)
    dark = await page.ev('(() => { const rep = SM.app.reports.find(r => r.platform.id === "treatment"); const p = rep.plots.find(p => p.opts.title === "propensity score overlap"); return [document.documentElement.getAttribute("data-theme"), p.traces[0].marker.color]; })()')
    check('the dark theme redraws the groups in its colours', dark, ['dark', '#d1528f'])
    await shot(page, 'treatment-06-dark.png')
    await shot(page, 'treatment-07-dark-overlap.png', 'Propensity Score Model')
    await shot(page, 'treatment-08-dark-balance.png', 'Covariate Balance')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    wide = await page.ev('document.documentElement.scrollWidth <= innerWidth + 1')
    check('no horizontal page scroll at phone width', wide, True)
    await shot(page, 'treatment-09-phone.png')
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await asyncio.sleep(1.2)
    await shot(page, 'treatment-10-phone-light.png', 'Overlap')

    # ---- help for every input: the launch dialog's (i), the forms' (i), the report's controls
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 1100, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev(HELP_JS)
    check('help: back on the Job training table', await page.ev('__hp.showTable("Job training")'), True)
    await check_launch_help(page, 'treatment', settings=['Treated Level'], what='treatment: the launch dialog')
    await page.ev(f'''(async () => {{ const t = SM.app.tables.find((x) => x.name === 'Job training'); const id = (n) => t.col(n).id;
      const rep = SM.app.openReport(SM.platforms.get('treatment'), {{ roles: {{ y: [id('earnings')], treatment: [id('program')], outcome: {json.dumps(COVS)}.map(id) }}, options: {{}} }}, t);
      await new Promise((r) => rep.on('done', r)); SM.app.showTab(SM.app.tabOf(rep)); return rep.title; }})()''', timeout=300)
    rep = 'SM.app.reports[SM.app.reports.length - 1]'
    await check_form_help(page, f"await __hp.menu({rep}, 'Overlap', ['Set Bin Width…'])", ['Bin width of the propensity scores'], 'treatment: Set Bin Width…')
    await check_form_help(page, f"await __hp.menu({rep}, null, ['Trim Propensity Scores…'])", ['ε'], 'treatment: Trim Propensity Scores…')
    await check_form_help(page, f"await __hp.menu({rep}, 'Covariate Balance', ['Set Threshold…'])", ['Largest |SMD| taken as balanced'], 'treatment: Set Threshold…')
    await check_form_help(page, f"await __hp.menu({rep}, 'Weights', ['Show Largest…'])", ['How many to list'], 'treatment: Show Largest…')
    await check_controls_help(page, rep, 'Weights', ['Effective N', 'Largest weights', 'The histogram', 'Save'], 'treatment: Weights', heading=None)
    check('no script errors', page.errors, [])
    check('no console errors', [c for c in page.console if 'error' in c.lower() and 'favicon' not in c.lower()], [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
