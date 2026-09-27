#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Specialized Modeling > Count Regression.

The example table (simulated doctor visits) opens; the launch dialog casts
the count, the effects and the exposure and picks the models; the report
has JMP's outlines: Model Comparison, Rootogram, Count Distribution and one
outline a model. Its numbers are checked in the page: the observed
frequencies are the table's counts; the Poisson's saved predicted means
satisfy the Poisson's likelihood equations (the means sum to the counts,
overall and in every level of every factor), give the reported -2LL and the
expected frequencies of the table and of the rootogram's bars. Rootogram
bars, the table's lines and the zero-probability points select their rows,
and a selection lights up the bars. The red triangles add a model, switch
the rootogram's style and overlay, add rate ratios, likelihood-ratio effect
tests, marginal effects and the profiler (whose value box recomputes the
prediction), and save columns; By, exclusions and Redo work; a separated
zero part and a Y that is not a count give messages, not errors; the
launch dialog refuses what it must; the report reads in the dark theme and
at phone width.

Start a server on the repository root and headless Chrome on
SMUI_HTTP_PORT and SMUI_CDP_PORT (the recipe is in README.md), then

    python3 resources/tests/smui/test-ui-counts.py

With SMUI_SHOTS=<folder> it saves screenshots.
"""
import asyncio
import json
import os
import sys

from cdp import BASE, Checks, open_page, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


HELPERS = '''
window.__cr = {
  rep: () => SM.app.reports[SM.app.reports.length - 1],
  state: (rep) => ({ title: rep.title, outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
    errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 600)), warnings: [...rep.body.querySelectorAll('.sm-ob-warn')].map(e => e.textContent.slice(0, 400)), plots: rep.plots.length }),
  heads: (title, rep) => [...(rep || __cr.rep()).body.querySelectorAll('.sm-ob-head')].filter(h => h.querySelector('h2, h3, h4').textContent === title),
  outline: (title, n = 0, rep) => { const h = __cr.heads(title, rep)[n]; return h ? h.parentElement : null; },
  within: (ob, title) => { const h = [...ob.querySelectorAll('.sm-ob-head')].find(x => x.querySelector('h2, h3, h4').textContent === title); return h ? h.parentElement : null; },
  rows: (t) => t ? [...t.querySelectorAll('tr')].map(tr => [...tr.children].map(c => c.textContent.trim())) : null,
  table: (ob, n = 0) => { if (!ob) return null; const t = ob.querySelector(':scope > .sm-ob-body').querySelectorAll('table.sm-rt, table.sm-kv')[n]; return __cr.rows(t); },
  caption: (ob, cap) => { if (!ob) return null; const t = [...ob.querySelectorAll('table.sm-rt')].find(x => x.caption && x.caption.textContent === cap); return __cr.rows(t); },
  dlg: () => document.querySelector('.sm-launch-dialog'),
  pick: (...names) => { const d = __cr.dlg(); const items = [...d.querySelectorAll('.sm-pick-list li')];
    names.forEach((n, i) => { const li = items.find(x => x.textContent === n); if (!li) throw new Error('no column in the dialog ' + n); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, metaKey: i > 0 })); }); },
  role: (label) => { const b = [...__cr.dlg().querySelectorAll('.sm-role .sm-btn')].find(x => x.textContent === label); if (!b) throw new Error('no role ' + label); b.click(); },
  btn: (label, root) => { const b = [...(root || __cr.dlg()).querySelectorAll('button')].find(x => x.textContent === label); if (!b) throw new Error('no button ' + label); b.click(); },
  models: () => [...__cr.dlg().querySelectorAll('.sm-cr-models input')].filter(i => i.checked).map(i => i.value),
  msg: () => __cr.dlg().querySelector('.sm-launch-msg').textContent,
  tick: (ms = 40) => new Promise(r => setTimeout(r, ms)),
  settled: async (rep) => { rep = rep || __cr.rep(); await __cr.tick(60); for (let i = 0; i < 2400 && (rep.body.classList.contains('is-running') || !rep.content.querySelector('.sm-ob')); i++) await __cr.tick(25); await __cr.tick(80); },
  menuItem: async (...path) => {
    for (let i = 0; i < path.length; i++) {
      const menus = [...document.querySelectorAll('.sm-menu')];
      const m = menus[menus.length - 1];
      const b = m && [...m.querySelectorAll('button')].find(x => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === path[i]);
      if (!b) throw new Error('no menu item ' + path[i] + ' in ' + (m ? [...m.querySelectorAll('.sm-label')].map(x => x.textContent).join('|') : 'no menu'));
      if (i < path.length - 1) b.dispatchEvent(new MouseEvent('mouseenter')); else b.click();
      await __cr.tick();
    }
  },
  obMenu: async (ob, ...path) => { ob.querySelector(':scope > .sm-ob-head .sm-ob-menu').click(); await __cr.tick(); await __cr.menuItem(...path); },
  topMenu: async (...path) => { await __cr.obMenu(__cr.rep().body.querySelector('.sm-ob.level-0'), ...path); },
  plot: (title, rep) => (rep || __cr.rep()).plots.find(p => p.opts.title === title),
  num: (s) => Number(String(s).replace(/−/g, '-').replace('<', '').replace('*', '').replace('%', '')),
  logfact: (k) => { let s = 0; for (let j = 2; j <= k; j++) s += Math.log(j); return s; },
};
'''

OPEN = '''
(async (roles, options) => {
  const t = SM.app.current; const P = SM.platforms.get('counts');
  const ids = {};
  for (const [k, names] of Object.entries(roles)) ids[k] = names.map(n => { const c = t.col(n); if (!c) throw new Error('no column ' + n); return c.id; });
  const rep = SM.app.openReport(P, { roles: ids, options: options || {} }, t);
  await new Promise(res => rep.on('done', res));
  return __cr.state(rep);
})
'''


def open_js(roles, options=None):
    return f'({OPEN})({json.dumps(roles)}, {json.dumps(options or {})})'


ROLES = {'y': ['visits'], 'x': ['age', 'sex', 'chronic', 'insurance'], 'exposure': ['years']}


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
    page = await open_page(f'{BASE}/smui.html?example=visits')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "counts").map(f => f.error)')
    check('counts imports in Pyodide', failed, [])
    names = await page.ev('SM.engine.names.filter(n => n.startsWith("counts.")).sort()')
    check('the engine has the counts functions', names, ['counts.compare', 'counts.fit', 'counts.importance', 'counts.lr_effects', 'counts.margeff', 'counts.maximize', 'counts.profile'])
    await page.ev(HELPERS)
    menu = await page.ev('''(() => { const sub = SM.app.menuItems("Analyze").find(i => i.label === "Specialized Modeling");
      const items = typeof sub.submenu === "function" ? sub.submenu() : sub.submenu; return items.map(i => i.label).filter(Boolean); })()''')
    check('Analyze > Specialized Modeling lists Count Regression', 'Count Regression…' in menu, True)
    info = await page.ev('''(() => { const t = SM.app.current; return { name: t.name, rows: t.nrows, cols: t.columns.map(c => [c.name, c.modelingType]),
      counts: t.col('visits').values.every(v => Number.isInteger(v) && v >= 0), zeros: t.col('visits').values.filter(v => v === 0).length,
      label: SM.io.EXAMPLES.visits.label }; })()''')
    check('the example table', (info['name'], info['rows']), ('Doctor visits', 500))
    check('its columns', info['cols'], [['id', 'nominal'], ['age', 'continuous'], ['sex', 'nominal'], ['chronic', 'nominal'], ['insurance', 'nominal'], ['years', 'continuous'], ['visits', 'continuous']])
    check('visits are counts, with excess zeros', info['counts'] and info['zeros'] > 150, True)

    # ---- the launch dialog: roles, the models, what it refuses
    r = await page.ev('''(async () => {
      SM.app.launch('counts'); await __cr.tick(300);
      const out = { defaults: __cr.models() };
      __cr.pick('years'); __cr.role('Y, Count'); await __cr.tick();
      __cr.btn('OK'); await __cr.tick();
      out.notCount = __cr.msg();
      __cr.btn('Cancel'); await __cr.tick(100);
      SM.app.launch('counts'); await __cr.tick(300);
      __cr.pick('visits'); __cr.role('Y, Count');
      __cr.pick('age', 'sex', 'chronic', 'insurance'); __cr.role('X, Model Effects');
      __cr.pick('years'); __cr.role('Exposure');
      __cr.pick('age'); __cr.role('Offset');
      __cr.btn('OK'); await __cr.tick();
      out.both = __cr.msg();
      const off = [...__cr.dlg().querySelectorAll('.sm-role')].find(x => x.querySelector('.sm-btn').textContent === 'Offset');
      off.querySelector('li').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      [...__cr.dlg().querySelectorAll('.sm-cr-models input')].forEach(i => { i.checked = false; });
      __cr.btn('OK'); await __cr.tick();
      out.none = __cr.msg();
      for (const i of __cr.dlg().querySelectorAll('.sm-cr-models input')) i.checked = ['poisson', 'nb2', 'zip', 'zinb', 'hnb'].includes(i.value);
      __cr.btn('OK');
      const rep = __cr.rep(); await new Promise(res => rep.on('done', res));
      out.state = __cr.state(rep); out.spec = rep.spec.options.models;
      return out; })()''')
    check('the dialog starts with Poisson, NB2, ZIP and ZINB', r['defaults'], ['poisson', 'nb2', 'zip', 'zinb'])
    check('a Y that is not a count is refused', 'whole numbers' in r['notCount'], True)
    check('an exposure and an offset together are refused', 'not both' in r['both'], True)
    check('no model is refused', 'at least one model' in r['none'], True)
    check('the report is JMP\'s title', r['state']['title'], 'Count Regression for visits')
    for o in ['Model Comparison', 'Rootogram', 'Count Distribution', 'Poisson', 'Negative Binomial (NB2)', 'Zero-Inflated Poisson', 'Zero-Inflated Negative Binomial',
              'Hurdle Negative Binomial', 'Parameter Estimates', 'Effect Tests', 'Overdispersion', 'Zero Probability', 'Residual Plots']:
        check(f'outline {o}', o in r['state']['outlines'], True)
    check('no errors in the report', r['state']['errors'], [])
    check('no warnings in the report', r['state']['warnings'], [])
    check('the spec keeps the models', r['spec'], ['poisson', 'nb2', 'zip', 'zinb', 'hnb'])
    await asyncio.sleep(1.2)
    await shot(page, 'cr-01-report.png')
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])

    # ---- the numbers, checked in the page
    r = await page.ev('''(async () => {
      const t = SM.app.current; const y = t.col('visits').values;
      const cd = __cr.table(__cr.outline('Count Distribution'));
      const head = cd[0];
      const obs = cd.slice(1).filter(row => /^\\d+$/.test(row[0])).map(row => [Number(row[0]), __cr.num(row[1])]);
      const want = obs.map(([k]) => y.filter(v => v === k).length);
      const cmp = __cr.table(__cr.outline('Model Comparison'));
      const pois = cmp.find(row => row[0] === 'Poisson');
      return { head, obsOk: JSON.stringify(obs.map(o => o[1])) === JSON.stringify(want), cmpHead: cmp[0], m2ll: __cr.num(pois[2]), zerosObs: __cr.num(pois[7]),
        zeros: y.filter(v => v === 0).length, rows: cd.length };
    })()''')
    check('Count Distribution: observed, % and each model\'s expected frequency', r['head'], ['visits', 'Observed', 'Observed %', 'Poisson Expected', 'NB2 Expected', 'ZIP Expected', 'ZINB Expected', 'Hurdle NB Expected'])
    check('the observed frequencies are the table\'s counts', r['obsOk'], True)
    check('Model Comparison: JMP\'s columns', r['cmpHead'], ['Model', 'k', '−2LogLikelihood', 'AIC', 'AICc', 'AICc Weight', 'BIC', 'Zeros Observed', 'Zeros Predicted', 'Pearson χ²/DF'])
    check('zeros observed = the zeros of the table', r['zerosObs'], r['zeros'])
    # the Poisson's predicted means, saved: its likelihood equations, its -2LL, its expected frequencies
    r2 = await page.ev('''(async () => {
      const ob = __cr.outline('Poisson');
      await __cr.obMenu(ob, 'Save Columns', 'Predicted Mean'); await __cr.tick(100);
      const t = SM.app.current; const mu = t.col('Pred visits Poisson').values; const y = t.col('visits').values;
      const sum = (a) => a.reduce((s, v) => s + v, 0);
      const out = { total: [sum(mu), sum(y)], levels: [] };
      for (const f of ['sex', 'chronic', 'insurance']) {
        const c = t.col(f).values;
        for (const lv of [...new Set(c)]) out.levels.push([f + '=' + lv, sum(mu.filter((_, i) => c[i] === lv)), sum(y.filter((_, i) => c[i] === lv))]);
      }
      let ll = 0; for (let i = 0; i < y.length; i++) ll += y[i] * Math.log(mu[i]) - mu[i] - __cr.logfact(y[i]);
      out.m2ll = -2 * ll;
      const e = [0, 1, 2, 3].map(k => sum(mu.map(m => Math.exp(-m + k * Math.log(m) - __cr.logfact(k)))));
      const cd = __cr.table(__cr.outline('Count Distribution'));
      out.expected = e; out.table = [1, 2, 3, 4].map(i => __cr.num(cd[i][3]));
      const p = __cr.plot('visits hanging rootogram, Poisson');
      const O = [0, 1, 2, 3].map(k => y.filter(v => v === k).length);
      out.bars = { h: p.traces[0].y.slice(0, 4), base: p.traces[0].base.slice(0, 4), wantH: O.map(Math.sqrt), wantBase: e.map((v, i) => Math.sqrt(v) - Math.sqrt(O[i])), curve: p.traces[1].y.slice(0, 4), wantCurve: e.map(Math.sqrt) };
      return out; })()''')
    check.near('Poisson: the predicted means sum to the counts (its likelihood equation for the intercept)', r2['total'][0], r2['total'][1], 1e-6)
    for lab, a, b in r2['levels']:
        check.near(f'Poisson: and within {lab} (effect-coded factor)', a, b, 1e-6)
    check.near('Poisson: -2LL from the saved means = the Model Comparison\'s', r2['m2ll'], r['m2ll'], 1e-6)
    for k in range(4):
        check.near(f'Poisson: expected frequency of {k} = the sum of the rows\' Poisson probabilities', r2['table'][k], r2['expected'][k], 1e-5)
    b = r2['bars']
    for k in range(4):
        check.near(f'hanging rootogram, {k}: the bar is √observed', b['h'][k], b['wantH'][k], 1e-9)
        check.near(f'hanging rootogram, {k}: it hangs from √expected', b['base'][k], b['wantBase'][k], 1e-5)
        check.near(f'hanging rootogram, {k}: the curve is √expected', b['curve'][k], b['wantCurve'][k], 1e-5)

    # ---- linking
    r = await page.ev('''(async () => {
      const t = SM.app.current; const y = t.col('visits').values;
      const p = __cr.plot('visits hanging rootogram, ZINB');
      p._click({ points: [{ curveNumber: 0, pointNumber: 0 }], event: {} });
      const zeros = y.map((v, i) => [v, i]).filter(([v]) => v === 0).map(([, i]) => i);
      const out = { bar: JSON.stringify(t.selectedRows()) === JSON.stringify(zeros) };
      const twos = y.map((v, i) => [v, i]).filter(([v]) => v === 2).map(([, i]) => i);
      t.select(twos); await __cr.tick(250);
      const comp = p.box.data[p.companions[0].at];
      const k = comp.x.indexOf(2);
      out.lit = k >= 0 ? [comp.y[k], p.traces[0].y[2], comp.base[k], p.traces[0].base[2]] : null;
      t.select([]);
      const cd = __cr.outline('Count Distribution');
      const tr = [...cd.querySelectorAll('table.sm-rt tbody tr')].find(x => x.children[0].textContent === '1');
      tr.click();
      const ones = y.map((v, i) => [v, i]).filter(([v]) => v === 1).map(([, i]) => i);
      out.line = JSON.stringify(t.selectedRows()) === JSON.stringify(ones);
      t.select([]);
      const zo = __cr.within(__cr.outline('Zero-Inflated Negative Binomial'), 'Zero Probability');
      zo._outline.setOpen(true); await __cr.tick(400);
      const zp = __cr.plot('visits zero probability, ZINB');
      zp._click({ points: [{ curveNumber: 0, pointNumber: 7 }], event: {} });
      out.point = JSON.stringify(t.selectedRows()) === JSON.stringify([zp.rows[0][7]]);
      zp._click({ points: [{ curveNumber: 1, pointNumber: 0 }], event: {} });
      out.group = t.selectedRows().length === zp.rows[1][0].length && zp.rows[1][0].length > 10;
      t.select([]);
      return out; })()''')
    check('a rootogram bar selects the rows with that count', r['bar'], True)
    check('selected rows light up their bar, drawn inside it', r['lit'] is not None and abs(r['lit'][0] - r['lit'][1]) < 1e-9 and abs(r['lit'][2] - r['lit'][3]) < 1e-9, True)
    check('a line of the Count Distribution selects its rows', r['line'], True)
    check('a point of the zero-probability plot selects its row', r['point'], True)
    check('a square of the zero-probability plot selects its group', r['group'], True)

    # ---- red triangles
    r = await page.ev('''(async () => {
      const out = {};
      await __cr.topMenu('Fit Model', 'Hurdle Poisson'); await __cr.settled();
      out.added = __cr.state(__cr.rep()).outlines.includes('Hurdle Poisson');
      out.models = __cr.rep().spec.options.models;
      await __cr.topMenu('Rootogram', 'Suspended'); await __cr.settled();
      out.suspended = __cr.rep().plots.filter(p => (p.opts.title || '').includes('suspended rootogram')).length;
      await __cr.topMenu('Rootogram', 'Overlay Models'); await __cr.settled();
      const ov = __cr.plot('visits rootogram, the models overlaid');
      out.overlay = ov ? ov.traces.filter(t => t.mode === 'lines+markers').map(t => t.name) : null;
      await __cr.topMenu('Rootogram', 'Hanging'); await __cr.settled();
      await __cr.topMenu('Rootogram', 'Overlay Models'); await __cr.settled();
      await __cr.topMenu('Rate Ratios'); await __cr.settled();
      out.ratios = __cr.heads('Rate Ratios').length;
      await __cr.topMenu('Effect Tests', 'Likelihood Ratio (refit)'); await __cr.settled();
      const eff = __cr.within(__cr.outline('Zero-Inflated Negative Binomial'), 'Effect Tests');
      out.lr = __cr.table(eff)[0];
      await __cr.topMenu('Marginal Effects', 'Average Marginal Effects'); await __cr.settled();
      out.margeff = __cr.heads('Average Marginal Effects').length;
      out.meRows = __cr.table(__cr.within(__cr.outline('Poisson'), 'Average Marginal Effects'));
      out.state = __cr.state(__cr.rep());
      return out; })()''')
    check('Fit Model adds a model', (r['added'], r['models']), (True, ['poisson', 'nb2', 'zip', 'zinb', 'hp', 'hnb']))
    check('Rootogram > Suspended: one suspended rootogram a model', r['suspended'], 6)
    check('Overlay Models: one graph, a curve for each model', r['overlay'], ['Poisson', 'NB2', 'ZIP', 'ZINB', 'Hurdle P', 'Hurdle NB'])
    check('Rate Ratios: an outline a model', r['ratios'], 6)
    check('Effect Tests > Likelihood Ratio: refitted tests', r['lr'], ['Source', 'Nparm', 'DF', 'L-R ChiSquare', 'Prob>ChiSq'])
    check('Marginal Effects: for the Poisson, NB and GP only (statsmodels has none for the others)', r['margeff'], 2)
    check('Marginal Effects: a line a design column but the intercept (5), dy/dx', r['meRows'] is not None and len(r['meRows']) == 6 and r['meRows'][0][1] == 'dy/dx', True)
    check('still no errors', r['state']['errors'], [])
    await asyncio.sleep(1)
    await shot(page, 'cr-02-options.png')

    # the profiler of one model: the value box recomputes from the fit
    r = await page.ev('''(async () => {
      const ob = __cr.outline('Zero-Inflated Negative Binomial');
      await __cr.obMenu(ob, 'Prediction Profiler'); await __cr.settled();
      const pr = __cr.within(__cr.outline('Zero-Inflated Negative Binomial'), 'Prediction Profiler');
      const vals = () => [...pr.querySelectorAll('.sm-prof-val')].map(v => __cr.num(v.textContent));
      const before = vals();
      const input = pr.querySelector('input[aria-label="age current value"]');
      input.value = '70'; input.dispatchEvent(new Event('change'));
      for (let i = 0; i < 200; i++) { await __cr.tick(30); if (vals()[0] !== before[0]) break; }
      const after = vals();
      const t = SM.app.current;
      const direct = await SM.engine.call('counts.profile', { y: 'visits', x: ['age', 'sex', 'chronic', 'insurance'], degree: 1, zx: [], zero_same: true, exposure: 'years', offset: null, freq: null,
        model: 'zinb', current: __cr.rep().spec.options[Object.keys(__cr.rep().spec.options).find(k => k.includes('~zinb|prof:'))], alpha: 0.05 }, t);
      return { before, after, direct: [direct.responses[0].current.pred, direct.responses[1].current.pred], factors: [...pr.querySelectorAll('.sm-prof-fname')].map(e => e.textContent) };
    })()''')
    check('profiler: the factors, the exposure among them', r['factors'], ['age', 'sex', 'chronic', 'insurance', 'years'])
    check('profiler: a new age changes the prediction', r['after'][0] != r['before'][0], True)
    check.near('profiler: the mean shown = the backend\'s at those settings', r['after'][0], r['direct'][0], 1e-5)
    check.near('profiler: P(0) shown = the backend\'s', r['after'][1], r['direct'][1], 1e-5)

    # Save Columns: P(Y = 0) and the quantile residuals are the report's
    r = await page.ev('''(async () => {
      const ob = __cr.outline('Zero-Inflated Negative Binomial');
      await __cr.obMenu(ob, 'Save Columns', 'P(Y = 0)'); await __cr.tick(100);
      await __cr.obMenu(ob, 'Save Columns', 'Randomized Quantile Residuals'); await __cr.tick(100);
      const t = SM.app.current;
      const p0 = t.col('P(visits=0) ZINB').values, q = t.col('Quantile Residual visits ZINB').values;
      const zp = __cr.plot('visits zero probability, ZINB');
      const base = zp.traces[0].y;
      const rowsZ = zp.rows[0];
      const same = rowsZ.every((r, k) => Math.abs(p0[r] - base[k]) < 1e-12);
      const m = q.reduce((a, b) => a + b, 0) / q.length, sd = Math.sqrt(q.reduce((a, b) => a + (b - m) ** 2, 0) / (q.length - 1));
      return { same, n: p0.filter(Number.isFinite).length, m, sd };
    })()''')
    check('Save Columns > P(Y = 0): the plotted probabilities', (r['same'], r['n']), (True, 500))
    check('Save Columns > Randomized Quantile Residuals: about standard normal', abs(r['m']) < 0.2 and 0.8 < r['sd'] < 1.2, True)

    # the seed of the quantile residuals, from the top red triangle
    r = await page.ev('''(async () => {
      const rep = __cr.rep();
      const before = __cr.plot('visits quantile residuals normal quantile plot, ZINB');
      const y0 = before ? before.traces[0].y.slice(0, 5) : null;
      __cr.topMenu('Quantile Residual Seed…'); await __cr.tick(300);
      const dlg = [...document.querySelectorAll('.sm-dialog')].pop();
      dlg.querySelector('input').value = '7';
      [...dlg.querySelectorAll('button')].find(b => b.textContent === 'OK').click();
      await __cr.settled(rep);
      const r = __cr.within(__cr.outline('Zero-Inflated Negative Binomial'), 'Residual Plots');
      r._outline.setOpen(true); await __cr.tick(300);
      const after = __cr.plot('visits quantile residuals normal quantile plot, ZINB');
      return { seed: rep.spec.options.seed, changed: JSON.stringify(after.traces[0].y.slice(0, 5)) !== JSON.stringify(y0) };
    })()''')
    check('Quantile Residual Seed sets the seed', r['seed'], 7)
    check('... and the residuals are drawn anew', r['changed'], True)

    # the Python script of the report
    r = await page.ev('__cr.rep().pythonScript()')
    check('the script holds every model\'s code and the Vuong test', all(s in r for s in ('sm.Poisson(', 'sm.ZeroInflatedNegativeBinomialP(', 'TruncatedLFNegativeBinomialP(', 'def vuong(')), True)

    # ---- Model Dialog: the launch dialog opens with the report's models and effects; two responses
    r = await page.ev('''(async () => {
      await __cr.topMenu('Model Dialog'); await __cr.tick(300);
      const out = { models: __cr.models(), degree: __cr.dlg().querySelector('select[aria-label="Model effects"]').value,
        y: [...__cr.dlg().querySelectorAll('.sm-role-list')][0].textContent };
      __cr.dlg().querySelector('select[aria-label="Model effects"]').value = '2';
      for (const i of __cr.dlg().querySelectorAll('.sm-cr-models input')) i.checked = ['poisson', 'zinb'].includes(i.value);
      __cr.btn('OK'); await __cr.settled();
      const e = __cr.caption(__cr.outline('Zero-Inflated Negative Binomial'), 'Count part: log of the mean of the count distribution');
      out.cross = e ? e.slice(1).map(row => row[0]).filter(t => t.includes('*')) : null;
      out.state = __cr.state(__cr.rep());
      return out; })()''')
    check('Model Dialog recalls the report\'s models', r['models'], ['poisson', 'nb2', 'zip', 'zinb', 'hp', 'hnb'])
    check('... its effects and Y', (r['degree'], r['y']), ('1', 'visits'))
    check('Full factorial to degree 2: the six crossings of four factors, 9 terms, JMP\'s names', (len(r['cross']), all(t.count('*') == 1 for t in r['cross']), sorted({t.split('[')[0].split('*')[0] for t in r['cross'] if t.startswith('sex')})), (9, True, ['sex']))
    check('... fitted without errors', r['state']['errors'], [])
    r = await page.ev('''(async () => { const t = SM.app.current;
      t.addColumn({ name: 'visits later', dataType: 'numeric', values: t.col('visits').values.map((v, i) => (i % 3 ? v : v + 1)) });
      return true; })()''')
    r = await page.ev(open_js({'y': ['visits', 'visits later'], 'x': ['age', 'chronic']}, {'models': ['poisson', 'nb2']}))
    check('two responses: an outline each', [o for o in r['outlines'] if o.startswith('Count Regression')], ['Count Regression', 'Count Regression for visits', 'Count Regression for visits later'])
    check('two responses: no errors', r['errors'], [])

    # ---- By, exclusion, Redo
    r = await page.ev(open_js({**ROLES, 'by': ['sex']}, {'models': ['poisson', 'zinb']}))
    check('By gives a report for each level', [o for o in r['outlines'] if o.startswith('Count Regression')], ['Count Regression for visits sex=F', 'Count Regression for visits sex=M'])
    check('no errors with By', r['errors'], [])
    r = await page.ev('''(async () => {
      const t = SM.app.current; const rep = __cr.rep();
      t.select([...Array(20).keys()]); t.setState(t.selectedRows(), 'excluded', true);
      const stale = !rep.staleEl.hidden;
      rep.run(); await new Promise(res => rep.on('done', res));
      const line = rep.body.querySelector('.sm-cr-modelline').textContent;
      t.setState([...Array(20).keys()], 'excluded', false); t.select([]);
      return { stale, note: rep.noteEl.textContent, line };
    })()''')
    check('an exclusion makes the report stale', r['stale'], True)
    check('Redo uses the included rows', r['note'].startswith('Doctor visits: 480 of 500 rows, 20 excluded'), True)

    # ---- messages, not errors: a separated zero part, a Y that is not a count
    r = await page.ev('''(async () => {
      const n = 300, g = [], y = [];
      const rng = SM.util.rng('separation');
      for (let i = 0; i < n; i++) { const lv = i < 60 ? 'A' : i < 180 ? 'B' : 'C'; g.push(lv); let k = 0, p = Math.exp(-2), s = p; const u = rng.u(); while (u > s) { k++; p *= 2 / k; s += p; } y.push(lv === 'A' ? 0 : k); }
      SM.app.addTable(new SM.Table({ name: 'Separated', columns: [{ name: 'g', dataType: 'character', values: g }, { name: 'y', dataType: 'numeric', values: y }, { name: 'half', dataType: 'numeric', values: y.map(v => v + 0.5) }] }));
      await __cr.tick(200);
      return true; })()''')
    r = await page.ev(open_js({'y': ['y'], 'zx': ['g']}, {'models': ['zip', 'hp']}))
    check('a separated zero part: no error', r['errors'], [])
    check('... but a warning', any('beyond ±12' in w or 'Hessian' in w for w in r['warnings']), True)
    r = await page.ev(open_js({'y': ['half']}, {'models': ['poisson']}))
    check('a Y that is not a count: no error', r['errors'], [])
    check('... but the message', any('whole numbers' in w for w in r['warnings']), True)

    # ---- the dark theme and phone width
    await page.ev('''(async () => { const t = SM.app.tables.find(x => x.name === 'Doctor visits'); SM.app.showTab(SM.app.tabOf(t)); })()''')
    await page.ev(open_js(ROLES, {'models': ['poisson', 'nb2', 'zinb']}))
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(1.5)
    r = await page.ev('__cr.state(__cr.rep())')
    check('the dark theme redraws without errors', r['errors'], [])
    await shot(page, 'cr-03-dark.png')
    await page.ev('''(() => { const rep = __cr.rep(); const h = __cr.heads('Rootogram')[0]; rep.body.scrollTop = h.getBoundingClientRect().top - rep.body.getBoundingClientRect().top + rep.body.scrollTop; })()''')
    await asyncio.sleep(1)
    await shot(page, 'cr-04-dark-rootogram.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(1)
    wide = await page.ev('document.documentElement.scrollWidth <= innerWidth + 1')
    check('no horizontal page scroll at phone width', wide, True)
    r = await page.ev('''(() => { const rep = __cr.rep(); const w = rep.body.getBoundingClientRect().width;
      const over = [...rep.body.querySelectorAll('.sm-plot')].filter(p => p.getBoundingClientRect().width > w + 1).length;
      return { w: Math.round(w), over }; })()''')
    check('no graph wider than the report at phone width', r['over'], 0)
    await page.ev("document.documentElement.setAttribute('data-theme', 'light')")
    await asyncio.sleep(1)
    await shot(page, 'cr-05-phone.png')

    # ---- help for every input: the launch dialog's (i), the forms' (i), the report's controls
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 950, 'deviceScaleFactor': 1, 'mobile': False}, session=page.sid)
    await page.ev(HELP_JS)
    check('help: back on the Doctor visits table', await page.ev('__hp.showTable("Doctor visits")'), True)
    await check_launch_help(page, 'counts', settings=['Models', 'Poisson', 'Negative Binomial (NB2)', 'Negative Binomial (NB1)', 'Generalized Poisson', 'ZI Poisson', 'ZI Negative Binomial',
                                                      'ZI Generalized Poisson', 'Hurdle Poisson', 'Hurdle Negative Binomial', 'X, Model Effects', 'Zero part when no Zero-Inflation Effects are cast'],
                            what='counts: the launch dialog')
    await page.ev('''(async () => { const t = SM.app.tables.find((x) => x.name === 'Doctor visits'); const id = (n) => t.col(n).id;
      const rep = SM.app.openReport(SM.platforms.get('counts'), { roles: { y: [id('visits')], x: ['age', 'chronic'].map(id), exposure: [id('years')] }, options: { models: ['poisson'], profiler: true } }, t);
      await new Promise((r) => rep.on('done', r)); SM.app.showTab(SM.app.tabOf(rep)); return rep.title; })()''', timeout=300)
    rep = 'SM.app.reports[SM.app.reports.length - 1]'
    await check_form_help(page, f"await __hp.menu({rep}, null, ['Quantile Residual Seed…'])", ['Seed'], 'counts: Quantile Residual Seed…')
    await check_controls_help(page, rep, 'Rootogram', ['A bar of a rootogram', 'A line of Count Distribution'], 'counts: Rootogram')
    await check_controls_help(page, rep, 'Zero Probability', ['A point', 'A square of Zero Probability'], 'counts: Zero Probability')
    await check_controls_help(page, rep, 'Prediction Profiler', ['The value box under a plot', 'The slider', 'The red dashed line', 'A desirability plot', 'Remembered Settings'], 'counts: Prediction Profiler', heading='In the profiler')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
