#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Quality and Process and
the DOE menu.

Control Chart Builder from its launch dialog on the Process example: the
limits against numbers computed in the page (X̿ ± 3R̄/(d₂√n), d₂ by
quadrature here), a click on a subgroup's point selects its five rows and a
table selection rings the subgroup, the tests, phases, By, Save Limits, and
the capability from the column's Spec Limits property. Process Capability
from its launch dialog (spec limits defaulted from the property), the goal
plot selecting its column. Pareto Plot, the Variability chart with variance
components and Gauge R&R, the attribute gauge. The DOE dialogs make their
design tables; Evaluate Design and Sample Size and Power report; the dark
theme and phone width.

Start a server on the repository root and headless Chrome (see README.md)
on SMUI_HTTP_PORT and SMUI_CDP_PORT, then

    python3 resources/tests/smui/test-ui-quality.py

With SMUI_SHOTS=<folder> it saves screenshots.
"""
import asyncio
import json
import os
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


# d2(n) by Simpson's rule on the page's normal distribution function.
D2 = '''((n) => { const P = SM.util.pnorm; const a = -9, b = 9, m = 3600, h = (b - a) / m; let s = 0;
  for (let i = 0; i <= m; i++) { const x = a + i * h, f = 1 - P(x) ** n - (1 - P(x)) ** n; s += f * (i === 0 || i === m ? 1 : i % 2 ? 4 : 2); } return s * h / 3; })'''

LAUNCH = '''(async (platform, casts, opts) => {
  SM.app.launch(platform);
  await new Promise(r => setTimeout(r, 250));
  const dlg = document.querySelector('.sm-launch-dialog');
  const items = [...dlg.querySelectorAll('.sm-pick-list li')];
  for (const [role, names] of casts) {
    items.forEach(li => li.classList.remove('is-selected'));
    let first = true;
    for (const nm of names) { const li = items.find(x => x.textContent === nm); li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, metaKey: !first })); first = false; }
    [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === role).click();
  }
  for (const [label, value] of Object.entries(opts || {})) {
    const lab = [...dlg.querySelectorAll('.sm-launch-opts label')].find(l => l.textContent.startsWith(label));
    const i = lab.querySelector('input, select'); if (i.type === 'checkbox') i.checked = !!value; else i.value = value;
  }
  await new Promise(r => setTimeout(r, 60));
  const extra = dlg.querySelector('.sm-q-speclist') ? dlg.querySelector('.sm-q-speclist').textContent : null;
  const n0 = SM.app.reports.length;
  [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK').click();
  const msg = dlg.querySelector('.sm-launch-msg').textContent;
  if (SM.app.reports.length === n0) return { msg, extra, open: true };
  const rep = SM.app.reports[SM.app.reports.length - 1];
  await new Promise(res => rep.on('done', res));
  return { msg, extra, open: !!document.querySelector('.sm-launch-dialog'), title: rep.title,
    outlines: [...rep.body.querySelectorAll('.sm-ob-head h2, .sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent),
    errors: [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent.slice(0, 400)) };
})'''


def launch_js(platform, casts, opts=None):
    return f'({LAUNCH})({json.dumps(platform)}, {json.dumps(casts)}, {json.dumps(opts or {})})'


# The (i) of a launch dialog, of a form or design dialog and of an outline:
# open it, read the sections of its panel ([{heading, choices: [[name,
# text]]}]), close it.
HELP_JS = r'''
window.__hlp = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  async read(btn) {
    if (!btn) return null;
    btn.click();
    await this.sleep(120);
    const p = document.querySelector('.info-panel');
    if (!p) return null;
    const secs = [];
    let cur = null;
    for (const node of p.querySelector('.info-panel-body').children) {
      if (node.tagName === 'H3') { cur = { heading: node.textContent, choices: [] }; secs.push(cur); }
      else if (node.matches('dl.info-choices')) {
        if (!cur) { cur = { heading: '', choices: [] }; secs.push(cur); }
        node.querySelectorAll(':scope > dt').forEach((dt) => cur.choices.push([dt.textContent, dt.nextElementSibling ? dt.nextElementSibling.textContent : '']));
      }
    }
    const out = { title: p.querySelector('.info-panel-title').textContent, secs };
    KvotInfo.close();
    await this.sleep(30);
    return out;
  },
  async launch(id) {
    SM.app.launch(id);
    await this.sleep(300);
    const dlg = [...document.querySelectorAll('.sm-launch-dialog')].pop();
    if (!dlg) return { error: `no launch dialog for ${id}` };
    const noTopic = KvotInfo.audit().noTopic;
    const info = await this.read(dlg.querySelector('.sm-dialog-head .info-btn'));
    dlg.querySelector('.sm-dialog-x').click();
    const L = SM.platforms.get(id).launch;
    return { noTopic, info, roles: L.roles.map((r) => r.label), options: (L.options || []).map((o) => o.label) };
  },
  async dialog(run) {
    const n0 = SM.ui.dialogs.length;
    run();
    let d = null;
    for (let i = 0; i < 80 && !d; i++) { await this.sleep(50); if (SM.ui.dialogs.length > n0) d = SM.ui.dialogs[SM.ui.dialogs.length - 1].el; }
    if (!d) return { error: 'no dialog opened' };
    await this.sleep(100);
    const labels = [...d.querySelectorAll('.sm-form label')].map((l) => l.textContent);
    const noTopic = KvotInfo.audit().noTopic;
    const info = await this.read(d.querySelector('.sm-dialog-head .info-btn'));
    d.querySelector('.sm-dialog-x').click();
    await this.sleep(60);
    return { labels, noTopic, info };
  },
  head(rep, title) { return [...rep.body.querySelectorAll('.sm-ob-head')].find((x) => x.querySelector('h2, h3, h4').textContent === title); },
  async form(rep, title, path) {
    const h = this.head(rep, title);
    if (!h) return { error: `no outline ${title}` };
    return this.dialog(() => {
      h.querySelector('.sm-ob-menu').click();
      for (const label of path) {
        const menus = document.querySelectorAll('.sm-menu');
        const b = [...menus[menus.length - 1].querySelectorAll('button')].find((x) => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === label);
        if (!b) { SM.ui.closeMenus(0); throw new Error(`no menu item ${label}`); }
        b.click();
      }
    });
  },
  async outline(rep, title) {
    const h = this.head(rep, title);
    if (!h) return { error: `no outline ${title}` };
    return this.read(h.querySelector('.info-btn'));
  },
};
'''


def section(info, heading):
    """The choices of the last section of an (i) panel with this heading."""
    secs = [s for s in (info or {}).get('secs', []) if s['heading'] == heading]
    return secs[-1]['choices'] if secs else []


def all_names(info):
    """Every name a panel explains; 'Proportion 1, Proportion 2' names two."""
    out = set()
    for s in (info or {}).get('secs', []):
        for n, _ in s['choices']:
            out.add(n)
            out.update(p.strip() for p in n.split(', '))
    return out


def check_launch(r, name):
    check(f'{name} launch dialog: every (i) has a topic while it is open', r.get('noTopic'), [])
    roles = section(r.get('info'), 'Roles')
    check(f'{name} launch (i): the Roles list every role', [n for n, _ in roles], r.get('roles'))
    check(f'{name} launch (i): each role says what it is for before what it takes', [n for n, t in roles if t.startswith('(') or len(t) < 60], [])
    opts = section(r.get('info'), 'Options')
    check(f'{name} launch (i): the Options list every option, each with its help', ([n for n, _ in opts], [n for n, t in opts if len(t) < 40]), (r.get('options'), []))


def check_form(r, name, title=None):
    """A form's (i) explains every field, under its label or under the name
    (helpLabel) that stands for fields repeated per column."""
    check(f'{name}: the form opens, every (i) has a topic while it is open', (r.get('error'), r.get('noTopic')), (None, []))
    fields = section(r.get('info'), 'Fields')
    names = [n for n, _ in fields]
    missing = [lab for lab in r.get('labels') or [] if lab not in names and not any(n.lower() in lab.lower() for n in names)]
    check(f'{name}: its (i) explains every field', (bool(names), missing), (True, []))
    check(f'{name}: ... each with what it is for', [n for n, t in fields if len(t) < 30], [])
    if title:
        check(f'{name}: the (i) builds on the topic {title}', (r.get('info') or {}).get('title'), title)


async def settle(page, s=0.8):
    await asyncio.sleep(s)


async def main():
    page = await open_page(f'{BASE}/smui.html?example=process')
    check('engine ready', await wait_engine(page), 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => ["quality", "power", "doe"].includes(f.module)).map(f => f.module + ": " + f.error)')
    check('quality, power and doe import in Pyodide', failed, [])
    names = await page.ev('["quality.control_chart", "quality.capability", "quality.pareto", "quality.variability", "quality.attribute_gauge", "doe.full_factorial", "doe.screening", "doe.rsm", "doe.space_filling", "doe.evaluate", "power.compute"].filter(n => !SM.engine.has(n))')
    check('every backend entry point is registered', names, [])
    check('no script errors at load', page.errors, [])
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    menu = await page.ev('(() => { const q = SM.app.menuItems("Analyze").find(i => i.label === "Quality and Process"); return q ? q.submenu().map(i => i.label || "—") : null; })()')
    check('Analyze > Quality and Process', [m for m in menu if m != '—'][:4], ['Control Chart Builder…', 'Process Capability…', 'Variability / Attribute Gauge Chart…', 'Pareto Plot…'])
    doe = await page.ev('SM.app.menuItems("DOE").filter(i => i.submenu).map(i => [i.label, i.submenu().map(s => s.label).filter(Boolean)])')
    check('the DOE menu', doe, [['Classical', ['Screening Design…', 'Full Factorial Design…', 'Response Surface Design…']], ['Special Purpose', ['Space Filling Design…']],
                                ['Design Diagnostics', ['Evaluate Design…']], ['Sample Size Explorers', ['Sample Size and Power']]])
    help_rows = await page.ev('["controlchart", "capability", "pareto", "variability", "evaldesign", "power"].filter(id => !document.getElementById("help-p-" + id))')
    check('a Help row for every platform', help_rows, [])

    # ---- Control Chart Builder from its launch dialog
    r = await page.ev(launch_js('controlchart', [['Y, Process', ['diameter (mm)']], ['Subgroup', ['subgroup']]]))
    check('control chart: dialog closes, report opens', (r['open'], r['title']), (False, 'Control Chart Builder'))
    check('control chart outlines', r['outlines'][:3], ['Control Chart Builder', 'XBar & R chart of diameter (mm)', 'Limit Summaries'])
    check('Process Capability Analysis from the column\'s Spec Limits property', 'Process Capability Analysis of diameter (mm)' in r['outlines'], True)
    check('no errors in the report', r['errors'], [])
    lim = await page.ev(table_under_js('Limit Summaries'))
    js = await page.ev(f'''(() => {{ const t = SM.app.current; const d2 = ({D2})(5); const g = new Map();
      t.col('subgroup').values.forEach((s, i) => {{ if (!g.has(s)) g.set(s, []); g.get(s).push(t.col('diameter (mm)').values[i]); }});
      const xs = [...g.values()]; const all = xs.flat(); const xbb = all.reduce((a, b) => a + b, 0) / all.length;
      const rbar = xs.map(v => Math.max(...v) - Math.min(...v)).reduce((a, b) => a + b, 0) / xs.length;
      const f = (v) => SM.util.fmt(v, {{ sig: 7 }});
      return {{ lcl: f(xbb - 3 * rbar / (d2 * Math.sqrt(5))), avg: f(xbb), ucl: f(xbb + 3 * rbar / (d2 * Math.sqrt(5))), rbar: f(rbar), rucl: xbb, d2 }}; }})()''')
    check('XBar limits = X̿ ± 3R̄/(d₂√5), computed in the page', lim[1][1:4], [js['lcl'], js['avg'], js['ucl']])
    check('R chart center = R̄', lim[2][2], js['rbar'])
    check('d₂(5) by quadrature in the page', abs(js['d2'] - 2.3259289) < 1e-6, True)
    await settle(page, 1.2)
    await shot(page, 'q01-xbar-r.png')

    # linking: a click on a subgroup's point selects its rows; a selection rings the point
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table;
      const p = rep.plots[0]; const i = p.rows.findIndex((x) => Array.isArray(x) && Array.isArray(x[0]));
      p._click({ points: [{ curveNumber: i, pointNumber: 3 }], event: {} });
      const sel = t.selectedRows();
      await new Promise(r => setTimeout(r, 250));
      const ringIdx = p.traces.findIndex(tr => tr.name === 'selected');
      const ring1 = p.box.data[ringIdx].x.slice();
      t.select([0, 1, 60]);
      await new Promise(r => setTimeout(r, 250));
      const ring2 = p.box.data[ringIdx].x.slice();
      t.select([]);
      await new Promise(r => setTimeout(r, 150));
      const ring3 = p.box.data[ringIdx].x.length;
      return { sel, ring1, ring2, ring3, sub: sel.map(r => t.col('subgroup').values[r]) };
    })()''')
    check('a click on subgroup 4 selects its five rows', (r['sel'], r['sub']), ([15, 16, 17, 18, 19], [4, 4, 4, 4, 4]))
    check('the selected subgroup is ringed', r['ring1'], [4])
    check('a table selection rings subgroups 1 and 13', r['ring2'], [1, 13])
    check('no selection, no rings', r['ring3'], 0)

    # all tests; a line of the Tests table selects its rows
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      rep.spec.options.tests = [1, 2, 3, 4, 5, 6, 7, 8]; rep.run(); await new Promise(res => rep.on('done', res));
      const head = [...rep.body.querySelectorAll('.sm-ob-head')].find(h => h.textContent.startsWith('Tests'));
      const tbl = head.parentElement.querySelector('table.sm-rt');
      const tr = tbl.querySelector('tbody tr'); const sub = tr.children[1].textContent; tr.click();
      const t = rep.table; const sel = t.selectedRows(); t.select([]);
      return { head: head.textContent, sub, subs: [...new Set(sel.map(r => String(t.col('subgroup').values[r])))], n: sel.length,
        red: rep.plots[0].traces.some(tr => tr.mode === 'text' && tr.text && tr.text.length) };
    })()''')
    check('the tests flag points', r['head'].startswith('Tests (') and r['red'], True)
    check('a Tests line selects its subgroup\'s rows', (r['subs'], r['n']), ([r['sub']], 5))

    # phases, By, Save Limits
    await page.ev("(() => { const t = SM.app.current; const s = t.col('subgroup').values; t.addColumn({ name: 'phase', dataType: 'character', values: s.map(v => v <= 18 ? 'before' : 'after'), valueOrder: ['before', 'after'] }); })()")
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.current))")
    r = await page.ev(open_report_js('controlchart', {'y': ['diameter (mm)'], 'subgroup': ['subgroup'], 'phase': ['phase']}))
    lim = await page.ev(table_under_js('Limit Summaries'))
    check('phases: limits of their own', [row[1] for row in lim[1:]], ['before', 'after', 'before', 'after'])
    check('phases: the centers differ', lim[1][3] != lim[2][3], True)
    await settle(page, 1.0)
    await shot(page, 'q02-phases.png')
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const n0 = SM.app.tables.length;
      const menu = [...rep.body.querySelectorAll('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu')][0];
      menu.click(); await new Promise(r => setTimeout(r, 100));
      const save = [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent.includes('Save Limits'));
      save.dispatchEvent(new MouseEvent('mouseenter')); await new Promise(r => setTimeout(r, 100));
      [...document.querySelectorAll('.sm-menu button')].find(b => b.textContent.includes('in New Table')).click();
      await new Promise(r => setTimeout(r, 300));
      const t = SM.app.tables[SM.app.tables.length - 1];
      return { n: SM.app.tables.length - n0, name: t.name, cols: t.columns.map(c => c.name), keys: t.col('_LimitsKey').values.slice(0, 8), mean: t.col('diameter (mm)').values[0] };
    })()''')
    check('Save Limits in New Table', (r['n'], r['cols'], r['keys'][:3]), (1, ['_LimitsKey', 'phase', 'diameter (mm)'], ['_Mean', '_LCL', '_UCL']))
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'Process')))")
    r = await page.ev(open_report_js('controlchart', {'y': ['diameter (mm)'], 'subgroup': ['subgroup'], 'by': ['operator']}, {'chart': 'xbar_r'}))
    check('By: one chart per operator', [o for o in r['outlines'] if o.startswith('Control Chart Builder')], ['Control Chart Builder operator=Ann', 'Control Chart Builder operator=Bo', 'Control Chart Builder operator=Cy'])
    check('By: no errors (a subgroup of one is left out of R)', r['errors'], [])
    for chart in ('xbar_s', 'ir', 'lj', 'run', 'ewma', 'cusum'):
        r = await page.ev(open_report_js('controlchart', {'y': ['diameter (mm)'], 'subgroup': ['subgroup']}, {'chart': chart}))
        check(f'{chart} chart: report without errors', (r['errors'], r['plots']), ([], 1))
    # a subgroup size of 1 is every row a point: Automatic is the individuals chart
    r = await page.ev(open_report_js('controlchart', {'y': ['diameter (mm)']}, {'subgroupSize': 1}))
    check('Automatic with a subgroup size of 1: Individual & Moving Range, without errors', (r['errors'], r['plots'], any('Individual' in o for o in r['outlines'])), ([], 1, True))

    # ---- Process Capability from its launch dialog, spec limits from the column property
    r = await page.ev(launch_js('capability', [['Y, Process', ['diameter (mm)']], ['Subgroup', ['subgroup']]]))
    check('the launch shows the column\'s spec limits', r['extra'], 'diameter (mm): LSL 9.4, Target 10, USL 10.6')
    check('capability outlines', r['outlines'], ['Process Capability', 'Goal Plot', 'Capability Box Plots', 'Capability Summary Report', 'Individual Detail Reports', 'diameter (mm) Capability'])
    summ = await page.ev(table_under_js('Capability Summary Report'))
    hdr = summ[0]
    row = dict(zip(hdr, summ[1]))
    js = await page.ev(f'''(() => {{ const t = SM.app.current; const d2 = ({D2})(5); const g = new Map();
      t.col('subgroup').values.forEach((s, i) => {{ if (!g.has(s)) g.set(s, []); g.get(s).push(t.col('diameter (mm)').values[i]); }});
      const xs = [...g.values()], all = xs.flat(), n = all.length, m = all.reduce((a, b) => a + b, 0) / n;
      const sd = Math.sqrt(all.reduce((a, b) => a + (b - m) ** 2, 0) / (n - 1));
      const sw = xs.map(v => Math.max(...v) - Math.min(...v)).reduce((a, b) => a + b, 0) / xs.length / d2;
      const f = (v) => SM.util.fmt(v, {{ sig: 7 }});
      return {{ cpk: f(Math.min(10.6 - m, m - 9.4) / (3 * sw)), ppk: f(Math.min(10.6 - m, m - 9.4) / (3 * sd)), cp: f(1.2 / (6 * sw)), pp: f(1.2 / (6 * sd)) }}; }})()''')
    check('Cpk, Ppk, Cp, Pp as computed in the page', [row['Cpk'], row['Ppk'], row['Cp'], row['Pp']], [js['cpk'], js['ppk'], js['cp'], js['pp']])
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      const p = rep.plots.find(p => p.opts.title === 'Goal plot');
      await p.draw();
      p.box.emit('plotly_click', { points: [{ curveNumber: 1, pointNumber: 0 }], event: {} });
      await new Promise(r => setTimeout(r, 200));
      const g = SM.app.grids.get(rep.table.id);
      const sel = [...g.colSel].map(id => rep.table.col(id).name);
      const size = p.box.data[1].marker.size;
      g.colSel.clear(); g.refresh(); SM.app.emit('columnselection', []);
      return { sel, size };
    })()''')
    check('a click on the goal plot selects the column', r['sel'], ['diameter (mm)'])
    check('and marks its point', r['size'], [12])
    await settle(page, 1.0)
    await shot(page, 'q03-capability.png')
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const id = rep.table.col('diameter (mm)').id;
      rep.spec.options[id + '|dist'] = 'weibull'; rep.run(); await new Promise(res => rep.on('done', res));
      return [...rep.body.querySelectorAll('.sm-ob-error')].map(e => e.textContent); })()''')
    check('a Weibull fit: no errors', r, [])
    detail = await page.ev(table_under_js('diameter (mm) Capability', 1))
    check('a nonnormal fit reports the percentile indices', detail is not None and any(rw[0] == 'P99.865' for rw in detail), True)

    # ---- Pareto Plot
    await page.ev('''(() => { const r = SM.util.rng('pareto'); const causes = ['scratch', 'dent', 'crack', 'stain', 'burr'], p = [.45, .25, .15, .1, .05]; const c = [], sh = [];
      for (let i = 0; i < 200; i++) { let u = r.u(), k = 0; while (u > p[k] && k < 4) { u -= p[k]; k++; } c.push(causes[k]); sh.push(i % 2 ? 'day' : 'night'); }
      SM.app.addTable(new SM.Table({ name: 'Defects', columns: [{ name: 'cause', dataType: 'character', values: c }, { name: 'shift', dataType: 'character', values: sh }] })); })()''')
    r = await page.ev(launch_js('pareto', [['Y, Cause', ['cause']]]))
    check('Pareto: report', (r['title'], r['errors']), ('Pareto Plot', []))
    fr = await page.ev(table_under_js('Frequencies'))
    js = await page.ev('''(() => { const t = SM.app.current; const m = new Map(); for (const v of t.col('cause').values) m.set(v, (m.get(v) || 0) + 1);
      return [...m.entries()].sort((a, b) => b[1] - a[1]).map(([k, v]) => [k, String(v)]); })()''')
    check('Pareto: causes by count, largest first', [row[:2] for row in fr[1:]], js)
    check('Pareto: cumulative percent ends at 100%', fr[-1][3], '100.0%')
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1]; const t = rep.table; const p = rep.plots[0];
      await p.draw();
      p._click({ points: [{ curveNumber: 0, pointNumber: 0 }], event: {} });
      const sel = t.selectedRows(); const vals = [...new Set(sel.map(r => t.col('cause').values[r]))];
      await new Promise(r => setTimeout(r, 200));
      const comp = p.box.data[p.companions[0].at]; const shown = comp.y.reduce((a, b) => a + b, 0); t.select([]);
      return { n: sel.length, vals, shown };
    })()''')
    check('Pareto: a bar selects the rows of its cause, drawn over the bar', (r['vals'], r['shown']), (['scratch'], r['n']))
    await settle(page)
    await shot(page, 'q04-pareto.png')
    r = await page.ev(open_report_js('pareto', {'y': ['cause'], 'x': ['shift']}, {'testRates': True, 'percent': True, 'combine': {'below': 8}}))
    check('Pareto by shift, percent scale, combined causes, rate test', ('Test Rates Across Groups' in r['outlines'], r['plots'], r['errors']), (True, 2, []))

    # ---- Variability chart, Gauge R&R
    await page.ev('''(() => { const r = SM.util.rng('gauge'); const op = [], part = [], y = []; const pe = Array.from({ length: 10 }, () => r.normal(0, 2)), oe = [0.3, -0.2, 0.1];
      for (let o = 0; o < 3; o++) for (let q = 0; q < 10; q++) for (let k = 0; k < 3; k++) { op.push(['Ann', 'Bo', 'Cy'][o]); part.push(q + 1); y.push(+(10 + pe[q] + oe[o] + r.normal(0, 0.4)).toFixed(3)); }
      SM.app.addTable(new SM.Table({ name: 'Gauge', columns: [{ name: 'Operator', dataType: 'character', values: op }, { name: 'Part', dataType: 'numeric', modelingType: 'nominal', values: part }, { name: 'Y', dataType: 'numeric', values: y }] })); })()''')
    r = await page.ev(launch_js('variability', [['Y, Response', ['Y']], ['X, Grouping', ['Operator', 'Part']]]))
    check('variability: report', (r['title'], r['errors']), ('Variability Gauge', []))
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      rep.spec.options.gauge = { k: 6, tolerance: 24 }; rep.run(); await new Promise(res => rep.on('done', res));
      const heads = [...rep.body.querySelectorAll('.sm-ob-head h3, .sm-ob-head h4')].map(h => h.textContent);
      const kv = [...rep.body.querySelectorAll('.sm-kv')].map(k => k.textContent).find(s => s.includes('Gauge R&R'));
      const p = rep.plots[0]; await p.draw(); const t = rep.table;
      const i = p.rows.findIndex((x) => Array.isArray(x) && Array.isArray(x[0]));
      p._click({ points: [{ curveNumber: i, pointNumber: 12 }], event: {} });
      const sel = t.selectedRows().map(r => [t.col('Operator').values[r], t.col('Part').values[r]]); t.select([]);
      return { heads, kv, sel };
    })()''')
    check('variance components and Gauge R&R', ['Variance Components' in r['heads'], 'Gauge R&R' in r['heads']], [True, True])
    check('a std dev point selects its cell\'s rows (Bo, part 3)', r['sel'], [['Bo', 3]] * 3)
    comp = await page.ev(table_under_js('Variance Components'))
    check('variance components: Operator, Part, Operator*Part, Within, Total', [row[0] for row in comp[1:]], ['Operator', 'Part', 'Operator*Part', 'Within', 'Total'])
    await settle(page, 1.0)
    await shot(page, 'q05-variability.png')
    await page.ev('''(() => { const r = SM.util.rng('attr'); const ap = [], ar = [], av = [];
      for (let q = 0; q < 12; q++) { const truth = q % 2 ? 'good' : 'bad'; for (const rr of ['A', 'B', 'C']) for (let k = 0; k < 2; k++) { ap.push(q + 1); ar.push(rr); av.push(r.u() > 0.15 ? truth : (truth === 'good' ? 'bad' : 'good')); } }
      SM.app.addTable(new SM.Table({ name: 'Ratings', columns: [{ name: 'part', dataType: 'numeric', modelingType: 'nominal', values: ap }, { name: 'rater', dataType: 'character', values: ar }, { name: 'rating', dataType: 'character', values: av }] })); })()''')
    r = await page.ev(open_report_js('variability', {'y': ['rating'], 'x': ['rater'], 'part': ['part']}))
    check('attribute gauge: report', (r['title'], 'Agreement Report' in r['outlines'], r['errors']), ('Attribute Gauge', True, []))

    # ---- DOE: the dialogs make their tables
    DLG = '''(async (label, edit) => {
      SM.commands.all().find(c => c.label === label).action(SM.app);
      await new Promise(r => setTimeout(r, 900));
      const dlg = [...document.querySelectorAll('.sm-dialog')].pop();
      if (edit) {
        const rows = [...dlg.querySelectorAll('.sm-doe-factors tbody tr')];
        const set = (i, v) => { i.value = v; i.dispatchEvent(new Event('change')); };
        for (const [k, name, lo, hi] of edit.factors || []) { const inp = rows[k].querySelectorAll('input'); set(inp[0], name); set(inp[1], lo); set(inp[2], hi); }
        for (const [label, v] of edit.options || []) { const lab = [...dlg.querySelectorAll('.sm-form label')].find(l => l.textContent === label); set(lab.nextElementSibling, v); }
      }
      const designs = [...dlg.querySelectorAll('.sm-doe-design')].map(l => l.textContent);
      const n0 = SM.app.tables.length;
      [...dlg.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Make Table').click();
      for (let i = 0; i < 150 && SM.app.tables.length === n0; i++) await new Promise(r => setTimeout(r, 100));
      const t = SM.app.tables[SM.app.tables.length - 1];
      return { made: SM.app.tables.length - n0, designs, name: t.name, rows: t.nrows, cols: t.columns.map(c => [c.name, c.modelingType]), notes: t.notes,
        values: Object.fromEntries(t.columns.map(c => [c.name, c.values.map(v => (typeof v === 'number' && Number.isNaN(v) ? null : v))])) };
    })'''
    r = await page.ev(f'({DLG})("Full Factorial Design…", {json.dumps({"factors": [[0, "Temp", "150", "200"], [1, "Time", "10", "20"]], "options": [["Number of Center Points", "2"], ["Random Seed", "7"]]})})')
    check('Full Factorial: a table of 2³ + 2 runs', (r['made'], r['rows']), (1, 10))
    check('Full Factorial: columns and modeling types', r['cols'], [['Pattern', 'nominal'], ['Temp', 'continuous'], ['Time', 'continuous'], ['X3', 'continuous'], ['Y', 'continuous']])
    combos = sorted(zip(r['values']['Temp'], r['values']['Time'], r['values']['X3']))
    check('Full Factorial: every combination and two center points', combos, sorted([(t, m, x) for t in (150, 200) for m in (10, 20) for x in (-1, 1)] + [(175, 15, 0)] * 2))
    check('Full Factorial: the response is empty', all(v is None for v in r['values']['Y']), True)
    check('Full Factorial: the seed in the notes', 'seed 7' in r['notes'], True)
    first = r['values']['Temp']
    r2 = await page.ev(f'({DLG})("Full Factorial Design…", {json.dumps({"options": [["Random Seed", "7"]]})})')
    check('the dialog remembers the factors, and the seed repeats the order', r2['values']['Temp'], first)
    r = await page.ev(f'({DLG})("Screening Design…", null)')
    check('Screening: the design list for five factors', r['designs'][:3], ['8Fractional FactorialIII', '12Plackett-BurmanIII', '16Fractional FactorialV'])
    check('Screening: the resolution V half fraction, its aliases in the notes', (r['rows'], 'resolution V' in r['notes'], 'X5 = X1*X2*X3*X4' in r['notes']), (16, True, True))
    X = [[v for v in r['values'][f'X{j}']] for j in range(1, 6)]
    check('Screening: orthogonal columns', all(sum(a * b for a, b in zip(X[i], X[j])) == 0 for i in range(5) for j in range(i + 1, 5)), True)
    r = await page.ev(f'({DLG})("Response Surface Design…", null)')
    check('Response Surface: rotatable CCD of 3 factors, 20 runs', (r['rows'], 'α = 1.68179' in r['notes']), (20, True))
    r = await page.ev(f'({DLG})("Space Filling Design…", {json.dumps({"options": [["Number of Runs", "12"], ["Random Seed", "3"]]})})')
    strata = all(sorted(int((v + 1) / 2 * 12 - 1e-9) for v in r['values'][f'X{j}']) == list(range(12)) for j in (1, 2, 3))
    check('Space Filling: a Latin hypercube, one point per stratum', (r['rows'], strata), (12, True))
    await shot(page, 'q06-doe-table.png')
    # Evaluate Design on the full factorial
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name.startsWith('Full Factorial'))))")
    r = await page.ev(launch_js('evaldesign', [['X, Factor', ['Temp', 'Time', 'X3']]]))
    check('Evaluate Design: report', (r['title'], r['errors']), ('Evaluate Design', []))
    diag = await page.ev(table_under_js('Design Diagnostics'))
    check('a full factorial with center points: D efficiency below 100, from the coding in the notes', float(diag[0][1]) < 100 and float(diag[0][1]) > 80, True)
    fac = await page.ev(table_under_js('Factors'))
    check('the coding comes from the column notes', fac[1][2], '150 to 200')
    await settle(page, 1.0)
    await shot(page, 'q07-evaldesign.png')

    # ---- Sample Size and Power: a report without a table
    r = await page.ev('''(async () => {
      SM.app.launch('power'); const rep = SM.app.reports[SM.app.reports.length - 1];
      await new Promise(res => rep.on('done', res)); await new Promise(r => setTimeout(r, 200));
      const inp = (k) => rep.body.querySelector(`input[data-key="${k}"]`);
      const first = inp('n').placeholder;
      const set = async (k, v) => { inp(k).value = v; inp(k).dispatchEvent(new Event('change')); await new Promise(r => setTimeout(r, 400)); };
      await set('power', ''); await set('n', '34');
      const power = inp('power').placeholder;
      const stored = JSON.stringify(rep.spec.options['in:one_mean']);
      rep.run(); await new Promise(res => rep.on('done', res));
      const kept = rep.body.querySelector('input[data-key="n"]').value;
      const plots = rep.plots.filter(p => p.box.isConnected).length;
      return { table: rep.table, first, power, stored, kept, plots, text: rep.body.querySelector('.sm-pw-results').textContent.slice(0, 200) };
    })()''')
    check('power: a report with no table', r['table'], None)
    check('power: the sample size for d = 0.5 (33.37)', r['first'], '= 33.3671')
    check('power: the power at n = 34', r['power'], '= 0.807778')
    check('power: the inputs are kept with the report', ('"n":34' in r['stored'], r['kept']), (True, '34'))
    check('power: two power curves', r['plots'], 2)
    r = await page.ev('''(async () => {
      const rep = SM.app.reports[SM.app.reports.length - 1];
      [...rep.body.querySelectorAll('.sm-pw-sits .sm-btn')].find(b => b.textContent === 'Two Sample Proportions').click();
      await new Promise(res => rep.on('done', res)); await new Promise(r => setTimeout(r, 300));
      return { heads: [...rep.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent), n: rep.body.querySelector('input[data-key="n"]').placeholder };
    })()''')
    check('power: two proportions, n per group for 0.6 against 0.5', (r['heads'][0], r['n']), ('Two Sample Proportions', '= 387.338'))
    await settle(page, 1.0)
    await shot(page, 'q08-power.png')
    check('no script errors so far', page.errors, [])

    # ---- the launch's Spec Limits form, for a column without the property
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'Gauge')))")
    r = await page.ev('''(async () => {
      SM.app.launch('capability'); await new Promise(r => setTimeout(r, 250));
      const dlg = document.querySelector('.sm-launch-dialog');
      const li = [...dlg.querySelectorAll('.sm-pick-list li')].find(x => x.textContent === 'Y');
      li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      [...dlg.querySelectorAll('.sm-role .sm-btn')].find(b => b.textContent === 'Y, Process').click();
      const ok = () => [...dlg.querySelectorAll('.sm-actions .sm-btn')].find(b => b.textContent === 'OK');
      ok().click();
      const refused = dlg.querySelector('.sm-launch-msg').textContent;
      [...dlg.querySelectorAll('.sm-q-launch .sm-btn')][0].click(); await new Promise(r => setTimeout(r, 250));
      const form = [...document.querySelectorAll('.sm-dialog')].pop();
      const inputs = form.querySelectorAll('input'); inputs[0].value = '4'; inputs[2].value = '16';
      [...form.querySelectorAll('.sm-dialog-foot .sm-btn')].find(b => b.textContent === 'OK').click();
      await new Promise(r => setTimeout(r, 100));
      const listed = dlg.querySelector('.sm-q-speclist').textContent;
      const n0 = SM.app.reports.length; ok().click();
      const rep = SM.app.reports[SM.app.reports.length - 1]; await new Promise(res => rep.on('done', res));
      return { refused, listed, made: SM.app.reports.length - n0, specs: rep.spec.options.specs, errors: [...rep.body.querySelectorAll('.sm-ob-error')].length };
    })()''')
    check('the launch refuses a column without spec limits', r['refused'], 'Give spec limits (Spec Limits…) for at least one process column')
    check('the Spec Limits form fills the launch', (r['listed'], r['made'], r['specs']), ('Y: LSL 4, Target ·, USL 16', 1, {'Y': {'lsl': 4, 'target': None, 'usl': 16}}))

    # ---- every red triangle and its submenus build
    r = await page.ev('''(async () => {
      const mine = ['controlchart', 'capability', 'pareto', 'variability', 'evaldesign', 'power']; let n = 0, items = 0;
      for (const rep of SM.app.reports.filter(r => mine.includes(r.platform.id))) {
        SM.app.showTab(SM.app.tabOf(rep)); await new Promise(r => setTimeout(r, 60));
        for (const btn of rep.body.querySelectorAll('.sm-ob-menu')) {
          btn.click(); await new Promise(r => setTimeout(r, 15)); n++;
          const menu = document.querySelector('.sm-menu'); items += menu ? menu.querySelectorAll('button').length : 0;
          for (const b of menu ? menu.querySelectorAll('button.sm-sub') : []) { b.dispatchEvent(new MouseEvent('mouseenter')); await new Promise(r => setTimeout(r, 5)); items += (document.querySelectorAll('.sm-menu')[1] || { querySelectorAll: () => [] }).querySelectorAll('button').length; }
          SM.ui.closeMenus(0);
        }
      }
      return { n, items };
    })()''')
    check(f'every red triangle opens ({r["n"]} menus, {r["items"]} items)', r['n'] > 40 and r['items'] > 300, True)
    check('no script errors from the menus', page.errors, [])

    # ---- help for every input: the launch dialogs, the forms, the design dialogs, the controls in the reports
    await page.ev(HELP_JS)
    mine = ['controlchart', 'capability', 'pareto', 'variability', 'evaldesign']
    r = await page.ev(f'''{json.dumps(mine)}.flatMap((id) => {{ const L = SM.platforms.get(id).launch;
      return [...L.roles, ...(L.options || [])].filter((f) => !f.help).map((f) => `${{id}}: ${{f.label}}`); }})''')
    check('every role and option of the quality platforms and Evaluate Design has its help', r, [])
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.col('diameter (mm)'))))")
    for pid in mine:
        r = await page.ev(f'__hlp.launch({json.dumps(pid)})')
        check_launch(r, pid)
        if pid == 'capability':
            check('capability launch (i): the Spec Limits part explains its button', [n for n, t in section(r.get('info'), 'Spec Limits') if len(t) > 60], ['Spec Limits…'])
    # the launch's Spec Limits form: its fields repeat per column, explained once each
    r = await page.ev('''(async () => {
      SM.app.launch('capability'); await __hlp.sleep(300);
      const dlg = document.querySelector('.sm-launch-dialog');
      [...dlg.querySelectorAll('.sm-pick-list li')].find((x) => x.textContent === 'diameter (mm)').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      [...dlg.querySelectorAll('.sm-role .sm-btn')].find((b) => b.textContent === 'Y, Process').click();
      const out = await __hlp.dialog(() => dlg.querySelector('.sm-q-launch .sm-btn').click());
      dlg.querySelector('.sm-dialog-x').click();
      return out; })()''')
    check_form(r, 'the launch\'s Spec Limits form')
    check('... under the names LSL, Target, USL', [n for n, _ in section(r.get('info'), 'Fields')], ['LSL', 'Target', 'USL'])
    await page.ev('''(async () => {
      const open = async (tableOf, id, roles, options) => { const t = SM.app.tables.find(tableOf); SM.app.showTab(SM.app.tabOf(t));
        const ids = {}; for (const [k, names] of Object.entries(roles)) ids[k] = names.map((n) => t.col(n).id);
        const rep = SM.app.openReport(SM.platforms.get(id), { roles: ids, options: options || {} }, t); await new Promise((res) => rep.on('done', res)); return rep; };
      const proc = (t) => t.col('diameter (mm)');
      window.__cc = await open(proc, 'controlchart', { y: ['diameter (mm)'], subgroup: ['subgroup'] });
      window.__ir = await open(proc, 'controlchart', { y: ['diameter (mm)'] }, { chart: 'ir' });
      window.__ew = await open(proc, 'controlchart', { y: ['diameter (mm)'], subgroup: ['subgroup'] }, { chart: 'ewma' });
      window.__cu = await open(proc, 'controlchart', { y: ['diameter (mm)'], subgroup: ['subgroup'] }, { chart: 'cusum' });
      window.__cap = await open(proc, 'capability', { y: ['diameter (mm)'], subgroup: ['subgroup'] });
      window.__par = await open((t) => t.name === 'Defects', 'pareto', { y: ['cause'] });
      window.__var = await open((t) => t.name === 'Gauge', 'variability', { y: ['Y'], x: ['Operator', 'Part'] });
      window.__ev = await open((t) => t.name.startsWith('Full Factorial'), 'evaldesign', { x: ['Temp', 'Time', 'X3'] }); })()''', timeout=300)
    cc = 'Control Chart Builder'
    forms = [('__cc', cc, ['K Sigma…'], 'K Sigma'), ('__cc', cc, ['Specify Stats…'], 'Specify Stats'), ('__cc', cc, ['Moving Range Span…'], 'Moving Range Span'),
             ('__cc', cc, ['Tests', 'Customize Tests…'], 'Customize Tests'), ('__cc', cc, ['Spec Limits…'], 'the chart\'s Spec Limits'),
             ('__ir', cc, ['Subgroup Size…'], 'Subgroup Size'), ('__ew', cc, ['EWMA Parameters…'], 'EWMA Parameters'), ('__cu', cc, ['CUSUM Parameters…'], 'CUSUM Parameters'),
             ('__cap', 'Process Capability', ['Spec Limits…'], 'the capability\'s Spec Limits'), ('__cap', 'Goal Plot', ['Goal Ppk…'], 'Goal Ppk'),
             ('__cap', 'diameter (mm) Capability', ['Historical Sigma…'], 'Historical Sigma'), ('__par', 'Pareto Plot', ['Causes', 'Combine Causes…'], 'Combine Causes'),
             ('__var', 'Variability Gauge', ['Gauge Studies', 'Gauge RR…'], 'Gauge R&R'), ('__ev', 'Evaluate Design', ['Power Settings…'], 'Power Settings')]
    for var, title_, path, name in forms:
        check_form(await page.ev(f'__hlp.form(window.{var}, {json.dumps(title_)}, {json.dumps(path)})'), name)
    r = await page.ev("__hlp.outline(__cap, 'Goal Plot')")
    check('the Goal Plot\'s (i) explains its slider and its points', [n for n, t in section(r, 'In the report') if len(t) > 30], ['Goal', 'A point'])
    # the design dialogs: every field and button of theirs is in their (i)
    for label in ('Screening Design…', 'Full Factorial Design…', 'Response Surface Design…', 'Space Filling Design…'):
        r = await page.ev(f'__hlp.dialog(() => SM.commands.all().find((c) => c.label === {json.dumps(label)}).action(SM.app))')
        names = all_names(r.get('info'))
        check(f'{label} every (i) has a topic while it is open', (r.get('error'), r.get('noTopic')), (None, []))
        check(f'{label} its (i) explains every field of its forms', [x for x in r.get('labels') or [] if x not in names], [])
        check(f'{label} ... and the responses, the factors and Make Table', [x for x in ('Response name', 'Goal', 'Add Response', 'Name', 'Role', 'Values', 'Add N', 'Make Table') if x not in names], [])
    # Sample Size and Power: every field of every situation is in the (i) of its outline
    r = await page.ev('''(async () => {
      SM.app.launch('power'); const rep = SM.app.reports[SM.app.reports.length - 1]; await new Promise((res) => rep.on('done', res));
      const labels = new Set(); const sits = [...rep.body.querySelectorAll('.sm-pw-sits .sm-btn')].map((b) => b.textContent);
      for (const s of sits) {
        const b = [...rep.body.querySelectorAll('.sm-pw-sits .sm-btn')].find((x) => x.textContent === s);
        if (!b.classList.contains('is-on')) { b.click(); await new Promise((res) => rep.on('done', res)); }
        rep.body.querySelectorAll('.sm-pw-form label').forEach((l) => labels.add(l.textContent.replace(/ ◦$/, '')));
      }
      const info = await __hlp.outline(rep, sits[sits.length - 1]);
      SM.app.closeReport(rep);
      return { sits: sits.length, labels: [...labels], info }; })()''', timeout=300)
    names = all_names(r['info'])
    check(f'Sample Size and Power: the fields of all {r["sits"]} situations are in the (i)', (r['sits'], [x for x in r['labels'] if x not in names]), (8, []))
    check('... with the situation buttons, the ◦ fields and Continue', [x for x in ('The situation buttons', 'Fields marked ◦', 'Test', 'Continue') if x not in names], [])
    r = await page.ev('(async () => { for (const rep of [__cc, __ir, __ew, __cu, __cap, __par, __var, __ev]) SM.app.closeReport(rep); return { dialogs: SM.ui.dialogs.length, audit: KvotInfo.audit().noTopic }; })()')
    check('the forms closed with their ×, and every (i) left has a topic', (r['dialogs'], r['audit']), (0, []))
    check('no script errors from the help checks', page.errors, [])

    # ---- projects keep the reports; the Python script holds their code
    r = await page.ev('''(async () => {
      const keep = SM.app.reports.filter(r => ['controlchart', 'power'].includes(r.platform.id)).slice(-2);
      const j = { format: 'smui-project', version: 1, tables: SM.app.tables.filter(t => keep.some(r => r.table === t)).map(t => ({ id: t.id, ...t.toJSON() })), reports: keep.map(r => r.toJSON()) };
      const n0 = SM.app.reports.length; SM.app.loadProject(JSON.parse(JSON.stringify(j)));
      const fresh = SM.app.reports.slice(n0);
      await Promise.all(fresh.map(r => new Promise(res => { if (r.body.querySelector('.sm-ob')) res(); else r.on('done', res); })));
      await new Promise(r => setTimeout(r, 400));
      const pw = fresh.find(r => r.platform.id === 'power');
      const cc = fresh.find(r => r.platform.id === 'controlchart');
      return { n: fresh.length, situation: pw && pw.spec.options.situation, heads: cc ? [...cc.body.querySelectorAll('.sm-ob-head h3')].map(h => h.textContent).slice(0, 2) : null,
        script: cc ? cc.pythonScript() : '' };
    })()''')
    check('a project brings back the control chart and the power report', (r['n'], r['situation']), (2, 'two_props'))
    check('the reloaded control chart', r['heads'][0].endswith('chart of diameter (mm)'), True)
    check('the Python script holds the chart\'s code', 'def d2(n)' in r['script'] and 'sigma = ' in r['script'], True)

    # ---- dark theme and phone width
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === 'controlchart')))")
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await asyncio.sleep(1.6)
    await shot(page, 'q09-dark-chart.png')
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === 'capability')))")
    await asyncio.sleep(1.2)
    await shot(page, 'q10-dark-capability.png')
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === 'variability')))")
    await asyncio.sleep(1.2)
    await shot(page, 'q11-dark-variability.png')
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === 'power')))")
    await asyncio.sleep(1.0)
    await shot(page, 'q12-dark-power.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    check('no horizontal page scroll at phone width (power)', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, 'q13-phone-power.png')
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.reports.find(r => r.platform.id === 'controlchart')))")
    await asyncio.sleep(0.8)
    check('no horizontal page scroll at phone width (control chart)', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, 'q14-phone-chart.png')
    r = await page.ev('''(async () => { SM.commands.all().find(c => c.label === 'Full Factorial Design…').action(SM.app); await new Promise(r => setTimeout(r, 400));
      const d = [...document.querySelectorAll('.sm-dialog')].pop(); const w = d.getBoundingClientRect().width; return { w, fits: d.getBoundingClientRect().right <= innerWidth + 1 }; })()''')
    check('the design dialog fits the phone', r['fits'], True)
    await shot(page, 'q15-phone-dialog.png')
    # the graphs fit the phone
    r = await page.ev('''(async () => {
      SM.ui.dialogs.slice().forEach(d => d.close(null));
      const rep = SM.app.reports.find(r => r.platform.id === 'controlchart'); SM.app.showTab(SM.app.tabOf(rep));
      await new Promise(r => setTimeout(r, 100)); rep.run(); await new Promise(res => rep.on('done', res));
      const w = rep.body.clientWidth; const p = rep.plots[0];
      return { body: w, plot: p.width };
    })()''')
    check('the control chart fits a phone', r['plot'] <= r['body'], True)
    await asyncio.sleep(1.0)
    await shot(page, 'q16-phone-chart-fitted.png')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
