#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Specialized Modeling >
Generalized Additive Model.

The simulated ozone example opens; the launch dialog casts the roles and
its own part keeps the link, the smoothing and the basis in step with the
distribution; the report shows JMP's outlines and no errors. Its numbers
hang together with the columns it saves (the deviance is the sum of the
squared residuals, the linear predictor the intercept plus the partial
effects plus the linear part, the profiler at a row's values its saved
prediction) and with the truth the example was simulated from (the saved
partial effects close to the true functions). The partial effect plots
are linked to the table both ways. The penalty slider previews a refit as
it moves and refits the report when let go; the term's red triangle
changes the basis, the degree and the size, the residuals and the
intercept; the distributions, the smoothing choices, the surface, the
comparison with the linear model, By, exclusions and Redo work; a saved
project reopens with the per-term choices; the report reads in the dark
theme and at phone width.

Start a server on the repository root and headless Chrome on
SMUI_HTTP_PORT and SMUI_CDP_PORT (the recipe is in README.md), then

    python3 resources/tests/smui/test-ui-gam.py

With SMUI_SHOTS=<folder> it saves screenshots.
"""
import asyncio
import json
import os
import sys

from cdp import BASE, Checks, open_page, wait_engine
from test_charts import GRAPHS_JS, more_from_outputs, page_probe_more

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


HELPERS = '''
window.__g = {
  T: 'temperature (°C)', W: 'wind (m/s)', D: 'day of year', Y: 'ozone (ppb)',
  rep: () => SM.app.reports[SM.app.reports.length - 1],
  state: (rep) => ({ title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
    errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 700)), warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 300)), plots: rep.plots.length }),
  outline: (title, rep) => { const r = rep || __g.rep(); const h = [...r.body.querySelectorAll('.sm-ob-head')].find(x => x.querySelector('h2, h3, h4').textContent === title); return h ? h.parentElement : null; },
  term: (name, rep) => { const r = rep || __g.rep(); const h = [...r.body.querySelectorAll('.sm-ob-head h4')].find(x => x.textContent.startsWith('s(' + name + ')')); return h ? h.closest('.sm-ob') : null; },
  table: (title, n = 0, rep) => { const ob = __g.outline(title, rep); if (!ob) return null; const t = ob.querySelector(':scope > .sm-ob-body').querySelectorAll('table.sm-rt, table.sm-kv')[n]; return t ? [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent.trim())) : null; },
  kv: (title, rep) => Object.fromEntries((__g.table(title, 0, rep) || []).map(r => [r[0], r[r.length - 1]])),
  // a term's line of the Smooth Terms table (Term, Basis, Basis Size, Degree, Nparm, Penalty α, EDF)
  trow: (name, rep) => (__g.table('Model Summary', 1, rep) || []).find(r => r[0] === 's(' + name + ')'),
  num: (s) => Number(String(s).replace(/−/g, '-').replace('<', '').replace('*', '').replace('%', '')),
  plot: (title, rep) => (rep || __g.rep()).plots.find(p => p.opts.title === title),
  tick: () => new Promise(r => setTimeout(r, 40)),
  done: (rep) => new Promise(res => rep.on('done', res)),
  settled: async (rep) => { for (let i = 0; i < 1200 && (rep.body.classList.contains('is-running') || !rep.content.querySelector('.sm-ob')); i++) await new Promise(r => setTimeout(r, 25)); },
  open: async (roles, options) => {
    const t = SM.app.current; const ids = {};
    for (const [k, names] of Object.entries(roles)) ids[k] = names.map(n => { const c = t.col(n); if (!c) throw new Error('no column ' + n); return c.id; });
    const o = { family: 'normal', smoothing: 'aic', df: 10, degree: 3, folds: 5, penalty: 1, ...(options || {}) };
    for (const [k, v] of Object.entries(o)) if (k.includes('|')) { const [n, key] = k.split('|'); delete o[k]; o[t.col(n).id + '|' + key] = v; }
    const rep = SM.app.openReport(SM.platforms.get('gam'), { roles: ids, options: o }, t);
    await __g.done(rep);
    return __g.state(rep);
  },
  menuItem: async (...path) => {
    for (let i = 0; i < path.length; i++) {
      const menus = [...document.querySelectorAll('.sm-menu')];
      const m = menus[menus.length - 1];
      const b = m && [...m.querySelectorAll('button')].find(x => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === path[i]);
      if (!b) throw new Error('no menu item ' + path[i]);
      if (i < path.length - 1) b.dispatchEvent(new MouseEvent('mouseenter')); else b.click();
      await __g.tick();
    }
  },
  topMenu: async (...path) => { __g.rep().body.querySelector('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu').click(); await __g.tick(); await __g.menuItem(...path); },
  termMenu: async (name, ...path) => { __g.term(name).querySelector(':scope > .sm-ob-head .sm-ob-menu').click(); await __g.tick(); await __g.menuItem(...path); },
  formOK: async (value) => { await __g.tick(); const d = [...document.querySelectorAll('.sm-dialog')].pop(); const i = d.querySelector('input'); i.value = String(value); [...d.querySelectorAll('button')].find(b => b.textContent === 'OK').click(); await __g.tick(); },
  dlg: () => document.querySelector('.sm-launch-dialog'),
  pick: (...names) => { const d = __g.dlg(); const items = [...d.querySelectorAll('.sm-pick-list li')];
    names.forEach((n, i) => { const li = items.find(x => x.textContent === n); if (!li) throw new Error('no column in the dialog ' + n); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, metaKey: i > 0 })); }); },
  role: (label) => { const b = [...__g.dlg().querySelectorAll('.sm-role .sm-btn')].find(x => x.textContent === label); b.click(); },
  btn: (label, root) => { const b = [...(root || __g.dlg()).querySelectorAll('button')].find(x => x.textContent === label); if (!b) throw new Error('no button ' + label); b.click(); },
  sel: (label) => __g.dlg().querySelector(`select[aria-label="${label}"]`),
  col: (name) => SM.app.current.col(name),
};
'''

BASE3 = {'y': ['ozone (ppb)'], 'smooth': ['temperature (°C)', 'wind (m/s)', 'day of year'], 'linear': ['weekend']}


def open_js(roles, options=None):
    return f'__g.open({json.dumps(roles)}, {json.dumps(options or {})})'


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
    page = await open_page(f'{BASE}/smui.html?example=ozone')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    check('gam imports in Pyodide', await page.ev('SM.engine.failed.filter(f => f.module === "gam").map(f => f.error)'), [])
    check('the engine has the gam functions', await page.ev('SM.engine.names.filter(n => n.startsWith("gam.")).sort()'), ['gam.compare', 'gam.fit', 'gam.importance', 'gam.marginal', 'gam.maximize', 'gam.plot_code', 'gam.profile', 'gam.shapley', 'gam.surface', 'gam.term'])
    await page.ev(HELPERS)
    t = await page.ev('({ name: SM.app.current.name, rows: SM.app.current.nrows, cols: SM.app.current.columns.map(c => c.name), listed: !!SM.io.EXAMPLES.ozone, date: SM.app.current.col("date").format.kind })')
    check('?example=ozone opens the simulated table', (t['name'], t['rows'], t['listed'], t['date']), ('Ozone', 365, True, 'date'))
    check('its columns', t['cols'], ['date', 'day of year', 'weekend', 'temperature (°C)', 'wind (m/s)', 'ozone (ppb)', 'alert', 'clinic visits'])
    v = await page.ev('({ oz: Math.min(...SM.app.current.col("ozone (ppb)").values), alert: [...new Set(SM.app.current.col("alert").values)].sort(), visits: SM.app.current.col("clinic visits").values.every(x => Number.isInteger(x) && x >= 0) })')
    check('ozone above zero (a Gamma Y), alert 0/1, visits counts', (v['oz'] > 0, v['alert'], v['visits']), (True, [0, 1], True))
    sub = await page.ev('''(() => { const m = SM.app.menuItems('Analyze').find(i => i.label === 'Specialized Modeling'); if (!m) return null;
      return (typeof m.submenu === 'function' ? m.submenu() : m.submenu).filter(i => i.label).map(i => i.label); })()''')
    check('Analyze > Specialized Modeling lists the platform', 'Generalized Additive Model…' in (sub or []), True)

    # ---- the launch dialog
    r = await page.ev('''(async () => {
      SM.app.launch('gam'); await new Promise(r => setTimeout(r, 300));
      const out = {};
      out.roles = [...__g.dlg().querySelectorAll('.sm-role .sm-btn')].map(b => b.textContent);
      const fam = __g.sel('Distribution'), link = __g.sel('Link Function'), sm = __g.sel('Smoothing');
      const opt = (s, v) => [...s.options].find(o => o.value === v);
      out.links0 = [...link.options].map(o => o.textContent);
      fam.value = 'binomial'; fam.dispatchEvent(new Event('change'));
      out.linksB = [...link.options].map(o => o.textContent);
      out.kfoldB = opt(sm, 'kfold').disabled;
      fam.value = 'poisson'; fam.dispatchEvent(new Event('change'));
      out.gcvP = opt(sm, 'gcv').disabled;
      fam.value = 'normal'; fam.dispatchEvent(new Event('change'));
      out.kfoldN = opt(sm, 'kfold').disabled;
      sm.value = 'fixed'; sm.dispatchEvent(new Event('change'));
      out.penShown = !__g.dlg().querySelector('input[aria-label="Penalty α"]').closest('label').hidden;
      sm.value = 'aic'; sm.dispatchEvent(new Event('change'));
      out.penHidden = __g.dlg().querySelector('input[aria-label="Penalty α"]').closest('label').hidden;
      // a categorical Y with the Normal: refused
      __g.pick('weekend'); __g.role('Y, Response'); __g.pick(__g.T); __g.role('Smooth Terms'); __g.btn('OK'); await __g.tick();
      out.catY = __g.dlg().querySelector('.sm-launch-msg').textContent;
      __g.btn('Cancel');
      SM.app.launch('gam'); await new Promise(r => setTimeout(r, 300));
      __g.pick(__g.Y); __g.role('Y, Response');
      __g.pick(__g.T, __g.W, __g.D); __g.role('Smooth Terms');
      __g.pick('weekend'); __g.role('Linear Terms');
      const n0 = SM.app.reports.length;
      __g.btn('OK');
      const rep = SM.app.reports[n0]; await __g.done(rep);
      out.state = __g.state(rep);
      out.options = rep.spec.options;
      return out; })()''')
    check('the roles', r['roles'], ['Y, Response', 'Smooth Terms', 'Linear Terms', 'Weight', 'Freq', 'By'])
    check('the Normal\'s links', r['links0'], ['Identity', 'Log', 'Reciprocal'])
    check('the Binomial\'s links, logit first', r['linksB'], ['Logit', 'Probit', 'Comp LogLog', 'Log'])
    check('k-fold is for the Normal with the identity link', (r['kfoldB'], r['kfoldN']), (True, False))
    check('GCV is not offered for the Poisson', r['gcvP'], True)
    check('the penalty box shows for Fixed only', (r['penShown'], r['penHidden']), (True, True))
    check('a categorical Y with the Normal is refused', 'takes the Binomial' in r['catY'], True)
    s = r['state']
    check('the report', s['title'], 'Generalized Additive Model for ozone (ppb)')
    for o in ['Smooth Terms', 's(temperature (°C))', 's(wind (m/s))', 's(day of year)', 'Model Summary', 'Smooth Term Tests', 'Parameter Estimates',
              'Actual by Predicted Plot', 'Residual by Predicted Plot', 'Deviance Residual Normal Quantile Plot', 'Prediction Profiler']:
        check(f'outline {o}', o in s['outlines'], True)
    check('no errors in the report', s['errors'], [])
    check('no warnings or messages from statsmodels', (s['warnings'], 'Messages from statsmodels' in s['outlines']), ([], False))
    check('the launch options are the report\'s', {k: r['options'][k] for k in ('family', 'link', 'smoothing', 'df', 'degree')},
          {'family': 'normal', 'link': 'identity', 'smoothing': 'aic', 'df': 10, 'degree': 3})
    await asyncio.sleep(1)
    await shot(page, 'gam-01-report.png')

    # ---- the numbers against the saved columns and the truth
    r = await page.ev('''(async () => {
      const rep = __g.rep(); const t = rep.table;
      const kv = __g.kv('Model Summary');
      await __g.topMenu('Save Columns', 'Predicted Values');
      await __g.topMenu('Save Columns', 'Linear Predictor');
      await __g.topMenu('Save Columns', 'Partial Effects', 'All Smooth Terms');
      const y = t.col(__g.Y).values, pred = t.col('Pred ' + __g.Y).values, lp = t.col('Linear Predictor ' + __g.Y).values;
      const s = [__g.T, __g.W, __g.D].map(n => t.col('s(' + n + ') ' + __g.Y).values);
      let sse = 0; for (let i = 0; i < t.nrows; i++) sse += (y[i] - pred[i]) ** 2;
      // the linear predictor less the three partial effects: the intercept plus the weekend effect, two values
      const rest = new Map(); const wk = t.col('weekend').values;
      for (let i = 0; i < t.nrows; i++) { const v = lp[i] - s[0][i] - s[1][i] - s[2][i]; const k = wk[i]; if (!rest.has(k)) rest.set(k, []); rest.get(k).push(v); }
      const spread = [...rest.values()].map(a => Math.max(...a) - Math.min(...a));
      const est = __g.table('Parameter Estimates');
      const b0 = __g.num(est[1][1]), bno = __g.num(est[2][1]);
      // the truth of the example, centred over the rows
      const T = t.col(__g.T).values, W = t.col(__g.W).values, D = t.col(__g.D).values;
      const truth = [T.map(v => 30 / (1 + Math.exp(-(v - 20) / 3))), W.map(v => 25 * Math.exp(-v / 3)), D.map(v => 8 * Math.sin(2 * Math.PI * (v - 80) / 365))];
      const rel = truth.map((f, j) => { const m = f.reduce((a, b) => a + b) / f.length; const c = f.map(v => v - m); const sd = Math.sqrt(c.reduce((a, b) => a + b * b, 0) / c.length);
        return Math.sqrt(c.reduce((a, v, i) => a + (s[j][i] - v) ** 2, 0) / c.length) / sd; });
      const sums = s.map(a => a.reduce((x, y2) => x + y2, 0));
      const tests = __g.table('Smooth Term Tests').slice(1).map(r => ({ term: r[0], edf: __g.num(r[1]), nparm: __g.num(r[2]) }));
      const terms = __g.table('Model Summary', 1).slice(1).map(r => __g.num(r[6]));
      return { dev: __g.num(kv['Deviance']), sse, spread, b0, bno, lpNo: rest.get('no')[0], lpYes: rest.get('yes')[0], rel, sums, edf: __g.num(kv['Total EDF']), tests, terms,
        line: rep.body.querySelector('.sm-gam-modelline').textContent };
    })()''')
    check.near('Deviance = the sum of the squared residuals of the saved predictions', r['dev'], r['sse'], 1e-6)
    check('the linear predictor = intercept + partial effects + the weekend effect (two values)', max(r['spread']) < 1e-8, True)
    check.near('weekend no: the intercept plus weekend[no]', r['lpNo'], r['b0'] + r['bno'], 1e-6)
    check.near('weekend yes: the intercept less weekend[no] (effect coding)', r['lpYes'], r['b0'] - r['bno'], 1e-6)
    check('the partial effects are centred (sum to zero over the rows)', all(abs(v) < 1e-6 for v in r['sums']), True)
    for name, e in zip(['temperature', 'wind', 'day of year'], r['rel']):
        check(f'truth: s({name}) within 25% of the true function\'s SD (RMSE/SD {e:.3f})', e < 0.25, True)
    check('the EDF of the tests are the Smooth Terms table\'s', [round(x['edf'], 3) for x in r['tests']], [round(x, 3) for x in r['terms']])
    check('a centred term of 10 basis functions has 9 parameters', [x['nparm'] for x in r['tests']], [9, 9, 9])
    check('the model line shows the smoothing', 'Smoothing: AIC' in r['line'], True)
    await page.ev('''(() => { const t = SM.app.current; for (const c of t.columns.filter(c => /^(Pred |Linear Predictor |s\\()/.test(c.name))) t.removeColumn(c.id); })()''')

    # ---- linking, both ways
    r = await page.ev('''(async () => {
      const rep = __g.rep(); const t = rep.table;
      __g.term(__g.T).scrollIntoView(); await new Promise(r => setTimeout(r, 600));
      const p = __g.plot(__g.T + ' partial effect');
      const ri = p.traces.findIndex(tr => tr.name === 'Partial residuals');
      const rug = p.traces.findIndex(tr => tr.name === 'Rug');
      p._click({ points: [{ curveNumber: ri, pointNumber: 7 }], event: {} });
      const sel = t.selectedRows();
      t.select([3, 4, 5]); await new Promise(r => setTimeout(r, 200));
      const sp = p.drawn ? p.box.data[ri].selectedpoints : null;
      const spRug = p.drawn ? p.box.data[rug].selectedpoints : null;
      p._selected({ points: [{ curveNumber: ri, pointNumber: 1 }, { curveNumber: ri, pointNumber: 2 }], event: {} });
      const box = t.selectedRows();
      t.select([]);
      return { sel, want: p.rows[ri][7], sp, spRug, box, drawn: p.drawn }; })()''')
    check('a click on a partial residual selects its row', r['sel'], [r['want']])
    check('a table selection highlights the partial residuals', sorted(r['sp'] or []), [3, 4, 5])
    check('and the rug', sorted(r['spRug'] or []), [3, 4, 5])
    check('a drag over points selects their rows', r['box'], [1, 2])

    # ---- the penalty slider: a preview while it moves, a refit when let go
    r = await page.ev('''(async () => {
      const rep = __g.rep();
      const ob = __g.term(__g.T); const sl = ob.querySelector('input.sm-gam-slider');
      const edf0 = ob.querySelector('.sm-gam-edf').textContent, a0 = ob.querySelector('.sm-gam-aval').textContent;
      const p = __g.plot(__g.T + ' partial effect'); const ci = p.traces.findIndex(tr => tr.name && tr.name.startsWith('s('));
      const y0 = p.box.data[ci].y.slice();
      sl.value = String(Number(sl.value) + 1.5); sl.dispatchEvent(new Event('input'));
      const t0 = performance.now();
      for (let k = 0; k < 500 && ob.querySelector('.sm-gam-edf').textContent === edf0; k++) await new Promise(r => setTimeout(r, 10));
      const ms = performance.now() - t0;
      const edf1 = __g.num(ob.querySelector('.sm-gam-edf').textContent);
      const moved = p.box.data[ci].y.some((v, i) => Math.abs(v - y0[i]) > 1e-9);
      const crit = ob.querySelector('.sm-gam-crit').textContent;
      const want = +(10 ** Number(sl.value)).toPrecision(6);
      const d = __g.done(rep); sl.dispatchEvent(new Event('change')); await d;
      const alpha = __g.num(__g.trow(__g.T)[5]), edf2 = __g.num(__g.trow(__g.T)[6]);
      const line = rep.body.querySelector('.sm-gam-modelline').textContent;
      const pen = Object.entries(rep.spec.options).filter(([k]) => k.startsWith('pen:'));
      const d2 = __g.done(rep); rep.run(); await d2;
      const kept = __g.num(__g.trow(__g.T)[5]);
      return { edf0: __g.num(edf0), edf1, ms, moved, crit, want, alpha, edf2, line, pen: pen.length, kept }; })()''')
    check('moving the slider refits the term (a larger α: fewer EDF)', r['edf1'] < r['edf0'], True)
    check('the preview answers quickly (< 1500 ms)', r['ms'] < 1500, True)
    print(f'      slider preview: {r["ms"]:.0f} ms')
    check('the curve moves with it', r['moved'], True)
    check('the preview shows the criteria', r['crit'].startswith('AIC '), True)
    check.near('letting go refits the report at that α', r['alpha'], r['want'], 1e-5)
    check.near('with the EDF of the preview', r['edf2'], r['edf1'], 0.006)
    check('the model line: penalties set by hand', 'penalties set by hand' in r['line'], True)
    check('kept in the option pen:<group>', r['pen'], 1)
    check.near('Redo keeps the penalty', r['kept'], r['want'], 1e-5)
    r2 = await page.ev('''(async () => { const rep = __g.rep(); const d = __g.done(rep); await __g.termMenu(__g.T, 'Choose Penalties Automatically'); await d;
      return { line: rep.body.querySelector('.sm-gam-modelline').textContent, pen: Object.keys(rep.spec.options).filter(k => k.startsWith('pen:')).length }; })()''')
    check('Choose Penalties Automatically goes back to AIC', ('Smoothing: AIC' in r2['line'], r2['pen']), (True, 0))
    r = await page.ev('''(async () => { const rep = __g.rep(); const d = __g.done(rep); await __g.termMenu(__g.W, 'Penalty α…'); await __g.formOK(1234.5); await d;
      return __g.trow(__g.W)[5]; })()''')
    check('Penalty α… sets the term\'s penalty', r, '1234.5')

    # ---- the term's red triangle: basis, degree, size, residuals, intercept
    r = await page.ev('''(async () => {
      const rep = __g.rep(); const out = {};
      let d = __g.done(rep); await __g.termMenu(__g.D, 'Basis', 'Cyclic Cubic'); await d;
      out.title = __g.term(__g.D).querySelector('h4').textContent;
      const p = __g.plot(__g.D + ' partial effect'); const c = p.traces.find(tr => tr.name && tr.name.startsWith('s('));
      out.ends = [c.y[0], c.y[c.y.length - 1]];
      out.pen = Object.keys(rep.spec.options).filter(k => k.startsWith('pen:')).length;
      d = __g.done(rep); await __g.termMenu(__g.W, 'Degree', '2'); await d;
      d = __g.done(rep); await __g.termMenu(__g.T, 'Basis Size (df)…'); await __g.formOK(8); await d;
      out.table = [__g.T, __g.W, __g.D].map(n => __g.trow(n).slice(0, 5));
      const n0 = __g.plot(__g.T + ' partial effect').traces.length;
      d = __g.done(rep); await __g.termMenu(__g.T, 'Partial Residuals'); await d;
      out.traces = [n0, __g.plot(__g.T + ' partial effect').traces.length];
      const f0 = __g.plot(__g.W + ' partial effect').traces.find(tr => tr.name && tr.name.startsWith('s(')).y[0];
      d = __g.done(rep); await __g.termMenu(__g.W, 'Include Intercept'); await d;
      const f1 = __g.plot(__g.W + ' partial effect').traces.find(tr => tr.name && tr.name.startsWith('s(')).y[0];
      out.shift = f1 - f0; out.b0 = __g.num(__g.table('Parameter Estimates')[1][1]);
      out.errors = __g.state(rep).errors;
      return out; })()''')
    check('Basis > Cyclic Cubic', r['title'], 's(day of year), cyclic')
    check.near('the cyclic curve joins up at the ends', r['ends'][0], r['ends'][1], 1e-7)
    check('Degree 2, Basis Size 8 in the Smooth Terms table', r['table'], [['s(temperature (°C))', 'B-Spline', '8', '3', '7'], ['s(wind (m/s))', 'B-Spline', '10', '2', '9'], ['s(day of year)', 'Cyclic Cubic', '10', '.', '9']])
    check('a new basis chooses the penalties again', r['pen'], 0)
    check('Partial Residuals off: one trace fewer', r['traces'][1], r['traces'][0] - 1)
    check.near('Include Intercept shifts the curve by the intercept', r['shift'], r['b0'], 1e-4)
    check('no errors after the term changes', r['errors'], [])
    await shot(page, 'gam-02-terms.png')

    # ---- the profiler at a row's values predicts its saved Predicted value
    r = await page.ev(open_js(BASE3, {'day of year|basis': 'cc'}))
    check('a fresh report opens', r['errors'], [])
    r = await page.ev('''(async () => {
      const rep = __g.rep(); const t = rep.table; const row = 40;
      await __g.topMenu('Save Columns', 'Predicted Values');
      const saved = t.col('Pred ' + __g.Y).values[row];
      const ob = __g.outline('Prediction Profiler'); ob.scrollIntoView(); await new Promise(r => setTimeout(r, 900));
      const val = () => ob.querySelector('.sm-prof-val').textContent;
      const set = async (sel, v) => { const was = val(); const i = ob.querySelector(sel); i.value = v; i.dispatchEvent(new Event('change')); for (let k = 0; k < 400 && val() === was; k++) await new Promise(r => setTimeout(r, 5)); };
      await set(`input[aria-label="${__g.T} current value"]`, '10');   // the first call refits: saving a column made a new table version
      const t0 = performance.now();
      await set(`input[aria-label="${__g.T} current value"]`, String(t.col(__g.T).values[row]));
      const ms = performance.now() - t0;
      await set(`input[aria-label="${__g.W} current value"]`, String(t.col(__g.W).values[row]));
      await set(`input[aria-label="${__g.D} current value"]`, String(t.col(__g.D).values[row]));
      const ws = ob.querySelector('select[aria-label="weekend current value"]'); ws.value = String(['no', 'yes'].indexOf(t.col('weekend').values[row])); ws.dispatchEvent(new Event('change')); await new Promise(r => setTimeout(r, 400));
      const pred = __g.num(val());
      const gd = ob.querySelectorAll('.sm-plot')[0]; const was = val();
      gd.emit('plotly_relayout', { 'shapes[0].x0': 25, 'shapes[0].x1': 25 });
      for (let k = 0; k < 400 && val() === was; k++) await new Promise(r => setTimeout(r, 5));
      const dragged = ob.querySelector(`input[aria-label="${__g.T} current value"]`).value;
      const cur = rep.spec.options['prof:'];
      const d = __g.done(rep); rep.run(); await d;
      const kept = __g.outline('Prediction Profiler').querySelector(`input[aria-label="${__g.T} current value"]`).value;
      t.removeColumn(t.col('Pred ' + __g.Y).id);
      return { saved, pred, ms, dragged, cur, kept }; })()''')
    check.near('the profiler at a row\'s values = its saved prediction', r['pred'], r['saved'], 1e-5)
    check('a profiler update answers quickly (< 400 ms)', r['ms'] < 400, True)
    print(f'      profiler update: {r["ms"]:.0f} ms')
    check('dragging the line sets the value', r['dragged'], '25')
    check('Redo keeps the profiler\'s settings', (r['cur']['temperature (°C)'], r['kept']), (25, '25'))

    # ---- the other options: surface, comparison with the linear model, the Python code
    r = await page.ev('''(async () => {
      const rep = __g.rep(); let d = __g.done(rep); await __g.topMenu('Surface Plot'); await d;
      d = __g.done(rep); await __g.topMenu('Compare with Linear Model'); await d;
      const out = { state: __g.state(rep) };
      const surf = rep.plots.find(p => p.opts.title === __g.T + ' and ' + __g.W + ' surface');
      out.contour = surf ? surf.traces[0].type : null;
      out.zlen = surf ? [surf.traces[0].z.length, surf.traces[0].z[0].length] : null;
      const ob = [...rep.body.querySelectorAll('.sm-ob-head h3')].find(h => h.textContent.startsWith('Surface Plot')).closest('.sm-ob');
      const vs = ob.querySelector('select[aria-label="Vertical"]'); vs.value = '2'; d = __g.done(rep); vs.dispatchEvent(new Event('change')); await d;
      out.title2 = [...rep.body.querySelectorAll('.sm-ob-head h3')].find(h => h.textContent.startsWith('Surface Plot')).textContent;
      out.compare = __g.table('Compare with Linear Model').slice(1).map(r => r[0]);
      out.test = __g.table('Compare with Linear Model', 1)[0];
      out.code = rep.pythonScript();
      return out; })()''')
    check('Surface Plot and Compare with Linear Model open without errors', r['state']['errors'], [])
    check('the surface is a contour of 40 × 40', (r['contour'], r['zlen']), ('contour', [40, 40]))
    check('its Vertical select changes the second term', r['title2'], 'Surface Plot: s(temperature (°C)) + s(day of year)')
    check('the comparison has both models', r['compare'], ['Linear (GLM)', 'Additive (GAM)'])
    check('and an F test (the Normal)', 'F Ratio' in r['test'], True)
    check('the Python script fits GLMGam and chooses α by select_penweight', ('GLMGam(' in r['code'], 'select_penweight' in r['code'], 'UnivariateCubicCyclicSplines' in r['code']), (True, True, True))
    await shot(page, 'gam-03-options.png')

    # ---- distributions and smoothing choices
    runs = [
        ('Binomial (0/1)', {'y': ['alert'], 'smooth': ['temperature (°C)', 'wind (m/s)']}, {'family': 'binomial', 'link': 'logit'}),
        ('Poisson', {'y': ['clinic visits'], 'smooth': ['temperature (°C)', 'wind (m/s)', 'day of year'], 'linear': ['weekend']}, {'family': 'poisson', 'link': 'log', 'day of year|basis': 'cc'}),
        ('Gamma', {'y': ['ozone (ppb)'], 'smooth': ['temperature (°C)', 'wind (m/s)']}, {'family': 'gamma', 'link': 'log'}),
        ('BIC', BASE3, {'smoothing': 'bic'}),
        ('GCV', BASE3, {'smoothing': 'gcv'}),
        ('K-fold', BASE3, {'smoothing': 'kfold'}),
        ('Fixed α', BASE3, {'smoothing': 'fixed', 'penalty': 50}),
        ('probit link', {'y': ['alert'], 'smooth': ['temperature (°C)']}, {'family': 'binomial', 'link': 'probit'}),
    ]
    for label, roles, opts in runs:
        ms = await page.ev(f'(async () => {{ const t0 = performance.now(); await {open_js(roles, opts)}; return performance.now() - t0; }})()', timeout=300)
        st = await page.ev('__g.state(__g.rep())')
        check(f'{label}: no errors', st['errors'], [])
        check(f'{label}: no messages from statsmodels', 'Messages from statsmodels' in st['outlines'], False)
        kv = await page.ev('__g.kv("Model Summary")')
        print(f'      {label}: {ms:.0f} ms, smoothing {kv.get("Smoothing")}, EDF {kv.get("Total EDF")}')
        if label == 'Binomial (0/1)':
            b = await page.ev('''(() => { const ob = __g.outline('Prediction Profiler'); const v = __g.num(ob.querySelector('.sm-prof-val').textContent);
              const p = __g.plot(__g.T + ' partial effect'); return { v, name: ob.querySelector('.sm-prof-name').textContent, resid: p.traces.some(t => t.name === 'Partial residuals') }; })()''')
            check('Binomial: the profiler predicts a probability', 0 < b['v'] < 1 and b['name'] == 'Prob[alert = 1]', True)
            check('Binomial: partial residuals hidden by default', b['resid'], False)
        if label == 'K-fold':
            check('K-fold: the Model Summary says so', kv.get('Smoothing'), 'K-Fold Cross-Validation')
        if label == 'Fixed α':
            a = await page.ev('[__g.T, __g.W, __g.D].map(n => __g.trow(n)[5])')
            check('Fixed α: every term at 50', a, ['50', '50', '50'])
    r = await page.ev(open_js({'y': ['weekend'], 'smooth': ['temperature (°C)']}, {'family': 'binomial', 'link': 'logit'}))
    check('a two-level categorical Y opens', r['errors'], [])
    r = await page.ev('''(async () => { const rep = __g.rep(); const a = rep.body.querySelector('.sm-gam-modelline').textContent;
      const d = __g.done(rep); await __g.topMenu('Target Level', 'yes'); await d; return [a, rep.body.querySelector('.sm-gam-modelline').textContent]; })()''')
    check('its event is the first level; Target Level picks the other', ('event: no' in r[0], 'event: yes' in r[1]), (True, True))
    r = await page.ev('''(async () => { const rep = __g.rep(); let d = __g.done(rep); await __g.topMenu('Distribution', 'Poisson'); await d; const st = __g.state(rep);
      d = __g.done(rep); await __g.topMenu('Distribution', 'Binomial'); await d; return { st, back: __g.state(rep) }; })()''')
    check('Distribution > Poisson for a categorical Y: a warning that says why, no error', (r['st']['errors'], any('needs a continuous Y' in w for w in r['st']['warnings'])), ([], True))
    check('and back to the Binomial it fits again', (r['back']['errors'], 'Smooth Terms' in r['back']['outlines']), ([], True))

    # ---- By, exclusions, Redo; a slider in one group
    r = await page.ev(open_js({**BASE3, 'linear': [], 'by': ['weekend']}, {'day of year|basis': 'cc'}))
    check('By: one report per level', [o for o in r['outlines'] if o.startswith('Generalized Additive Model')], ['Generalized Additive Model for ozone (ppb) weekend=no', 'Generalized Additive Model for ozone (ppb) weekend=yes'])
    check('no errors with By', r['errors'], [])
    r = await page.ev('''(async () => {
      const rep = __g.rep(); const sl = rep.body.querySelector('input.sm-gam-slider');
      sl.value = String(Number(sl.value) + 1); sl.dispatchEvent(new Event('input'));
      const d = __g.done(rep); sl.dispatchEvent(new Event('change')); await d;
      const lines = [...rep.body.querySelectorAll('.sm-gam-modelline')].map(x => x.textContent.includes('penalties set by hand'));
      const t = rep.table; t.setState([0, 1, 2, 3, 4, 5, 6, 7, 8, 9], 'excluded', true);
      const stale = !rep.staleEl.hidden;
      const d2 = __g.done(rep); rep.run(); await d2;
      const n = [...rep.body.querySelectorAll('.sm-gam-modelline')].map(x => x.textContent.match(/Observations: (\\d+)/)[1]);
      t.setState([0, 1, 2, 3, 4, 5, 6, 7, 8, 9], 'excluded', false);
      return { keys: Object.keys(rep.spec.options).filter(k => k.startsWith('pen:')), lines, stale, n, total: t.nrows }; })()''')
    check('a slider in the first group sets that group\'s penalties only', (r['keys'], r['lines']), (['pen:weekend=no'], [True, False]))
    check('an exclusion makes the report stale', r['stale'], True)
    check('Redo fits the included rows', sum(int(x) for x in r['n']), 355)

    # ---- a saved project reopens with the per-term choices
    r = await page.ev(open_js(BASE3, {'day of year|basis': 'cc', 'wind (m/s)|degree': 2}))
    r = await page.ev('''(async () => {
      const rep = __g.rep(); const d = __g.done(rep); await __g.termMenu(__g.W, 'Penalty α…'); await __g.formOK(77); await d;
      const t = SM.app.current;
      const j = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
      const n = SM.app.reports.length;
      SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const again = SM.app.reports[n]; await __g.settled(again);
      const out = { title: again.title, errors: __g.state(again).errors, table: [__g.T, __g.W, __g.D].map(n => { const r = __g.trow(n, again); return [r[1], r[3], r[5]]; }),
        line: again.body.querySelector('.sm-gam-modelline').textContent, other: again.table !== t };
      SM.app.showTab(SM.app.tabOf(t));
      return out; })()''')
    check('a project reopens the report', (r['title'], r['errors'], r['other']), ('Generalized Additive Model for ozone (ppb)', [], True))
    check('with its bases, degrees and penalties (column ids remapped)', [x[:2] for x in r['table']], [['B-Spline', '3'], ['B-Spline', '2'], ['Cyclic Cubic', '.']])
    check('the penalty set by hand survives', (r['table'][1][2], 'penalties set by hand' in r['line']), ('77', True))

    # ---- (i) topics and Help
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) of the report has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    help_row = await page.ev('''(async () => { SM.app.showHelp('p-gam'); await new Promise(r => setTimeout(r, 300)); const row = document.getElementById('help-p-gam'); return row ? row.textContent.includes('GLMGam') : null; })()''')
    check('the Help tab lists the platform with its statsmodels functions', help_row, True)

    # ---- dark theme; phone width
    await page.ev("SM.app.showTab(SM.app.tabOf(__g.rep()))")
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(1.5)
    await page.ev("__g.rep().body.scrollTop = 0")
    await asyncio.sleep(0.8)
    await shot(page, 'gam-04-dark.png')
    r = await page.ev('''(() => { const p = __g.plot(__g.T + ' partial effect'); const c = p.traces.find(tr => tr.name && tr.name.startsWith('s('));
      return { fill: p.traces[1].fillcolor, curve: c.line.color }; })()''')
    check('the dark theme draws the curve and band in its own colours', (r['curve'], r['fill']), ('#ff7a6b', 'rgba(255,122,107,0.18)'))
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    r = await page.ev('''(async () => { const rep = __g.rep(); const d = __g.done(rep); rep.run(); await d; await new Promise(r => setTimeout(r, 800));
      const body = rep.body.getBoundingClientRect();
      const boxes = [...rep.body.querySelectorAll('.sm-gam-terms .sm-plot')].map(p => p.getBoundingClientRect().right);
      return { page: document.documentElement.scrollWidth <= innerWidth + 1, plots: boxes.every(x => x <= body.right + 1), n: boxes.length }; })()''')
    check('no horizontal page scroll at phone width', r['page'], True)
    check('the partial effect plots fit the phone\'s width', (r['plots'], r['n']), (True, 3))
    await shot(page, 'gam-05-phone.png')

    # ---- help for every input: the launch dialog's (i) in each of its states, the forms' (i), the report's controls
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev(HELP_JS)
    check('help: back on the Ozone table', await page.ev('__hp.showTable("Ozone")'), True)
    model = ['Distribution', 'Link Function', 'Smoothing']
    basis = ['Basis Size (df)', 'Degree']
    await check_launch_help(page, 'gam', settings=model + basis, what='gam: the launch dialog (AIC)')
    await check_launch_help(page, 'gam', settings=model + ['Penalty α'] + basis, prep='async (d) => __hp.choose(d, "Smoothing", "fixed")', what='gam: the launch dialog (Fixed Penalty α)')
    await check_launch_help(page, 'gam', settings=model + ['Folds'] + basis, prep='async (d) => __hp.choose(d, "Smoothing", "kfold")', what='gam: the launch dialog (K-Fold Cross-Validation)')
    rep = "SM.app.reports.find((r) => r.platform.id === 'gam' && r.spec.options.smoothing === 'kfold')"
    await page.ev(f'SM.app.showTab(SM.app.tabOf({rep}))')
    await check_form_help(page, f"await __hp.menu({rep}, null, ['Smoothing', 'Number of Folds…'])", ['Folds'], 'gam: Number of Folds…')
    await check_form_help(page, f"await __hp.menu({rep}, null, ['Smoothing', 'Fixed Penalty α…'])", ['Penalty α'], 'gam: Fixed Penalty α…')
    await check_form_help(page, f"await __hp.menu({rep}, null, ['Basis for All Terms', 'Basis Size (df)…'])", ['Basis size (df)'], 'gam: Basis Size for All Terms')
    await check_form_help(page, f"await __hp.menu({rep}, 's(temperature (°C))', ['Basis Size (df)…'])", ['Basis size (df)'], 'gam: a term\'s Basis Size (df)…')
    await check_form_help(page, f"await __hp.menu({rep}, 's(temperature (°C))', ['Penalty α…'])", ['Penalty α'], 'gam: a term\'s Penalty α…')
    info = await check_controls_help(page, rep, 'Smooth Terms', ['B-Spline', 'Cyclic Cubic', 'Penalty α slider', 'EDF, Penalty α', 'Partial residuals', 'Include Intercept'], 'gam: Smooth Terms', heading=None)
    check('gam: Smooth Terms (i) keeps its sections', (info or {}).get('headings'), ['Identifiability', 'Surface Plot'])
    check('gam: ... and explains the Surface Plot\'s two lists', list(help_section(info, 'Surface Plot') or {}), ['Horizontal, Vertical'])
    await check_controls_help(page, rep, 'Prediction Profiler', ['The value box under a plot', 'The slider', 'The red dashed line', 'A desirability plot', 'Remembered Settings'], 'gam: Prediction Profiler')
    await chart_code(page)
    check('no script errors', page.errors, [])
    check('no errors in the console', [c for c in page.console if 'Error' in c], [])
    await page.close()


# ---- the graphs' matplotlib code -------------------------------------------------------------------------------------
# Each graph has a code block right under it (details.sm-code, ending in
# plt.show()); the block runs in the page's own Python (SM.engine.runCell, as
# test_charts.GRAPHS_JS.run does) with test_charts.PROBE_MORE in place of
# plt.show(), and the figure it draws is compared with the Plotly graph above
# it. The profiler's graphs are interactive and have no block. __gc adds the
# contour levels Plotly chose (its full data), which GRAPHS_JS does not
# collect.
CHART_JS = r'''
window.__gc = {
  levels(rep) {
    return [...rep.body.querySelectorAll('.js-plotly-plot')].map((p) => {
      const c = (p._fullData || []).find((d) => d.type === 'contour');
      return c ? { start: c.contours.start, end: c.contours.end, size: c.contours.size } : null;
    });
  },
};
'''
PROFILER = (' profile over ', ' desirability', 'Desirability over ', ' variable importance')


async def run_more(page, g, table_js):
    out = await page.ev(f'__gr.run({json.dumps(page_probe_more(g["code"]))}, {table_js})', timeout=900)
    if isinstance(out, str):
        return None, out
    got, err = more_from_outputs(out.get('outputs'))
    return (got['figures'] if got else None), err


def near_list(a, b, rel=1e-6, abs_=1e-9):
    a, b = list(a or []), list(b or [])
    return len(a) == len(b) and all(x is not None and y is not None and abs(x - y) <= max(abs_, rel * max(abs(x), abs(y))) for x, y in zip(a, b))


def band_edges(poly):
    """A fill_between polygon's lower and upper edge at each x (its vertices grouped by x)."""
    edges = {}
    for x, y in poly:
        if x is None or y is None:
            continue
        lo, hi = edges.get(round(x, 9), (y, y))
        edges[round(x, 9)] = (min(lo, y), max(hi, y))
    xs = sorted(edges)
    return xs, [edges[x][0] for x in xs], [edges[x][1] for x in xs]


def check_gam_graph(lab, g, F, lev):
    ax = F['axes'][0]
    t0 = g['traces']
    check(f'{lab}: the title', ax['title'], g['label'])
    if g['label'].endswith('partial effect'):
        curve = [t for t in t0 if t.get('mode') == 'lines' and (t.get('name') or '').startswith('s(')]
        ln = [x for x in ax['lines'] if x['color'].startswith('#c0392b') and len(x['x']) > 2]
        check(f'{lab}: the curve, the page\'s', bool(curve and ln) and near_list(ln[0]['x'], curve[0]['x'], 1e-12) and near_list(ln[0]['y'], curve[0]['y']), True)
        fills = [t for t in t0 if t.get('mode') == 'lines' and t.get('fill') == 'tonexty']
        if fills:
            lower = [t for t in t0 if t.get('mode') == 'lines' and not t.get('fill') and not t.get('name')][0]
            poly = [p_ for p_ in ax['polys'] if p_.get('paths')]
            xs, lo, hi = band_edges(poly[0]['paths'][0]) if poly else ([], [], [])
            check(f'{lab}: the band, the page\'s', near_list(xs, [round(v, 9) for v in fills[0]['x']], 1e-9) and near_list(lo, lower['y']) and near_list(hi, fills[0]['y']), True)
        else:
            check(f'{lab}: no band, as the page', [p_ for p_ in ax['polys'] if p_.get('paths')], [])
        res = [t for t in t0 if t.get('name') == 'Partial residuals']
        sc = [x for x in ax['scatter'] if x['label'] == 'Partial residuals']
        check(f'{lab}: the partial residuals (or none), the page\'s', (len(res), bool(res) and bool(sc) and near_list([p_[0] for p_ in sc[0]['xy']], res[0]['x'], 1e-12)
                                                                     and near_list([p_[1] for p_ in sc[0]['xy']], res[0]['y'])), (len(sc), bool(res)))
        rug = [t for t in t0 if t.get('name') == 'Rug']
        rl = [x for x in ax['lines'] if x['marker'] == '|']
        check(f'{lab}: the rug (or none), the page\'s', (len(rl), bool(rug) and bool(rl) and near_list(rl[0]['x'], rug[0]['x'], 1e-12)), (len(rug), bool(rug)))
    elif g['label'].endswith('surface'):
        con = [t for t in t0 if t.get('type') == 'contour'][0]
        mesh = ax['meshes'][0] if ax['meshes'] else None
        check(f'{lab}: the heatmap, the page\'s grid', bool(mesh) and near_list(mesh['z'], [v for row in con['z'] for v in row]) and near_list(mesh['x'], con['x'], 1e-12) and near_list(mesh['y'], con['y'], 1e-12), True)
        lv = [p_['contour'] for p_ in ax['polys'] if 'contour' in p_]
        want = []
        if lev:
            v = lev['start']
            while v <= lev['end'] + lev['size'] * 1e-6:
                want.append(v)
                v += lev['size']
        check(f'{lab}: the contour levels Plotly drew', bool(lv) and near_list(lv[0], want, 1e-9, 1e-12), True)
        pts = [t for t in t0 if t.get('mode') == 'markers'][0]
        check(f'{lab}: the rows\' points', bool(ax['scatter']) and near_list([p_[0] for p_ in ax['scatter'][0]['xy']], pts['x'], 1e-12) and near_list([p_[1] for p_ in ax['scatter'][0]['xy']], pts['y'], 1e-12), True)
    else:
        pts = t0[0]
        sc = ax['scatter'][0]['xy'] if ax['scatter'] else []
        check(f'{lab}: the points, the page\'s', near_list([p_[0] for p_ in sc], pts['x'], 1e-8) and near_list([p_[1] for p_ in sc], pts['y'], 1e-7, 1e-9), True)
        lines = [t for t in t0[1:] if t.get('mode') == 'lines']
        if lines:
            ln = [x for x in ax['lines'] if len(x['x']) == 2]
            check(f'{lab}: the line, the page\'s', bool(ln) and near_list(ln[0]['x'], lines[0]['x'], 1e-8) and near_list(ln[0]['y'], lines[0]['y'], 1e-7, 1e-9), True)
        else:
            check(f'{lab}: the zero line', [x['y'] for x in ax['lines']], [[s['y0'], s['y1']] for s in g['shapes']])
    check(f'{lab}: the axis titles', (ax['xlabel'], ax['ylabel']), (g['titles']['x'], g['titles']['y']))


async def chart_code(page):
    await page.ev(GRAPHS_JS)
    await page.ev(CHART_JS)
    # the code draws in the light theme's colours: compare with the page in it
    await page.ev("KVOT.setTheme ? KVOT.setTheme('light') : document.documentElement.setAttribute('data-theme', 'light')")
    await asyncio.sleep(1.2)
    await page.ev('__gr.idle()')
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find((t) => t.name === 'Ozone')))")
    tbl = "SM.app.tables.find((t) => t.name === 'Ozone')"
    await page.ev(f"{tbl}.setState([2, 3, 40], 'excluded', true)")
    T, Wn, D = 'temperature (°C)', 'wind (m/s)', 'day of year'
    runs = [
        ('fixed penalties, the surface, three rows excluded', BASE3, {'smoothing': 'fixed', 'surface': True}, 7),
        ('penalties by AIC, a term with the intercept, one without residuals or rug', {'y': ['ozone (ppb)'], 'smooth': [T, Wn]},
         {f'{T}|constant': True, f'{Wn}|resid': False, f'{Wn}|rug': False, f'{Wn}|band': False}, 5),
        ('a 0/1 alert, binomial', {'y': ['alert'], 'smooth': [T, D]}, {'family': 'binomial', 'link': 'logit', 'smoothing': 'fixed'}, 5),
        ('By weekend', {**BASE3, 'linear': [], 'by': ['weekend']}, {'smoothing': 'fixed'}, 12),
    ]
    for label, roles, options, want in runs:
        r = await page.ev(f'''(async () => {{ const st = await {open_js(roles, options)}; const rep = __g.rep();
          return {{ st, g: await __gr.graphs(rep), lev: __gc.levels(rep), undrawn: __gr.take() }}; }})()''', timeout=1200)
        if not isinstance(r, dict):
            check(f'charts: {label}: the report', r, 'opens')
            continue
        check(f'charts: {label}: no errors', r['st']['errors'], [])
        check(f'charts: {label}: every graph of the report drawn', r['undrawn'], [])
        gs = [(g, lv) for g, lv in zip(r['g'], r['lev']) if not any(k in g['label'] for k in PROFILER)]
        check(f'charts: {label}: the graphs', len(gs), want)
        for g, lv in gs:
            lab = f'charts: {label}: {g["label"]}'
            check(f'{lab}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
            if not g['code']:
                continue
            if 'excluded' in label:
                check(f'{lab}: the code leaves out the excluded rows', 'df = df.drop(index=[2, 3, 40])' in g['code'], True)
            if 'AIC' in label:
                check(f'{lab}: the code searches the penalties as the report does', 'select_penweight' in g['code'], True)
            F, err = await run_more(page, g, tbl)
            check(f'{lab}: the code runs in the page', err, None)
            if F:
                check_gam_graph(lab, g, F[0], lv)
        await page.ev('SM.app.closeReport(__g.rep())')
    await page.ev(f"{tbl}.setState([2, 3, 40], 'excluded', false)")


asyncio.run(main())
sys.exit(check.done())
