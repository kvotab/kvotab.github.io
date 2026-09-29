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
import re
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine
from test_charts import GRAPHS_JS, close, maxdiff, run_graph

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

    # ---- the graphs' matplotlib code, run in the page
    await chart_code(page)
    check('no script errors from the graphs\' code', page.errors, [])

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



# ---- the graphs' matplotlib code ------------------------------------------------------------
# Each graph has a code block right under it (details.sm-code, ending in
# plt.show()); the block runs in the page's own Python (the notebook's
# runner, SM.engine.runCell) with test_charts.PROBE in place of plt.show(),
# and its figure is compared with the Plotly graph above it: the traces'
# points, lines, bars and colours, the shapes, the annotations, the axes'
# ranges and ticks, the size. Rows excluded, a By group and a date subgroup
# are among the cases.
QG_JS = r'''
window.__qg = {
  table(name) { return SM.app.tables.find((t) => t.name === name); },
  async open(tableName, platform, roles, options) {
    const t = this.table(tableName);
    SM.app.showTab(SM.app.tabOf(t));
    const ids = {};
    for (const [k, names] of Object.entries(roles)) ids[k] = names.map((n) => t.col(n).id);
    const rep = SM.app.openReport(SM.platforms.get(platform), { roles: ids, options: options || {} }, t);
    await new Promise((res) => rep.on('done', res));
    return rep;
  },
  errors(rep) { return [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent.slice(0, 300)); },
  // what GRAPHS_JS does not pick: the layout's axes, annotations and shapes, the box plots' statistics, the markers' symbols and colours
  details(rep) {
    return [...rep.body.querySelectorAll('.js-plotly-plot')].map((p) => {
      const L = p.layout || {};
      const axes = {};
      for (const k of Object.keys(L)) if (/^[xy]axis\d*$/.test(k)) axes[k] = { range: L[k].range || null, type: L[k].type || null, tickvals: L[k].tickvals || null, ticktext: L[k].ticktext || null };
      const full = p._fullLayout || {};
      const ranges = {};
      for (const k of Object.keys(full)) if (/^[xy]axis\d*$/.test(k) && full[k] && full[k].range) ranges[k] = full[k].range.slice();
      return {
        label: p.getAttribute('aria-label'), axes, ranges,
        annotations: (L.annotations || []).map((a) => ({ text: a.text, x: a.x, y: a.y, xref: a.xref, yref: a.yref })),
        shapes: (L.shapes || []).map((s) => ({ x0: s.x0, x1: s.x1, y0: s.y0, y1: s.y1, xref: s.xref, yref: s.yref, color: s.line && s.line.color, dash: s.line && s.line.dash })),
        boxes: (p.calcdata || []).map((cd, i) => (p.data[i] && p.data[i].type === 'box' ? cd.map((c) => ({ q1: c.q1, med: c.med, q3: c.q3, lf: c.lf, uf: c.uf })) : null)),
        traces: (p.data || []).map((d) => ({ symbol: d.marker ? d.marker.symbol : null, mcolors: d.marker && Array.isArray(d.marker.color) ? d.marker.color : null, lwidth: d.line ? d.line.width : null, showlegend: d.showlegend })),
      };
    });
  },
};
'''

CHART_TABLES = r'''(() => {
  const r = SM.util.rng('quality-charts');
  const sub = [], day = [], d = [], ph = [], op = [], n = [], bad = [], c2 = [];
  for (let g = 1; g <= 20; g++) for (let k = 0; k < 5; k++) {
    sub.push(g); day.push(Date.UTC(2026, 2, 1 + g)); ph.push(g <= 14 ? 'before' : 'after'); op.push(r.u() < 0.5 ? 'Ann' : 'Bo');
    d.push(+(10 + (g > 14 ? 0.3 : 0) + r.normal(0, 0.14)).toFixed(3)); const m = 80 + Math.floor(40 * r.u()); n.push(m);
    let b = 0; for (let i = 0; i < m; i++) if (r.u() < 0.06) b++; bad.push(b); c2.push(+Math.exp(r.normal(1, 0.3)).toFixed(3));
  }
  SM.app.addTable(new SM.Table({ name: 'Chart process', columns: [
    { name: 'subgroup', dataType: 'numeric', modelingType: 'ordinal', values: sub }, { name: 'day', dataType: 'numeric', format: { kind: 'date' }, values: day },
    { name: 'd', dataType: 'numeric', values: d, specLimits: { lsl: 9.5, target: 10, usl: 10.7 } }, { name: 'phase', dataType: 'character', values: ph, valueOrder: ['before', 'after'] },
    { name: 'operator', dataType: 'character', values: op }, { name: 'n', dataType: 'numeric', values: n }, { name: 'bad', dataType: 'numeric', values: bad },
    { name: 'c2', dataType: 'numeric', values: c2, specLimits: { lsl: 0.8, usl: 7.5 } }] }));
  const causes = ['scratch', 'dent', 'crack', 'stain', 'burr', 'chip'], p = [.4, .25, .15, .1, .06, .04];
  const cause = [], shift = [], cnt = [];
  for (let i = 0; i < 240; i++) { let u = r.u(), k = 0; while (u > p[k] && k < 5) { u -= p[k]; k++; } cause.push(causes[k]); shift.push(r.u() < 0.5 ? 'night' : 'day'); cnt.push(Math.floor(4 * r.u())); }
  SM.app.addTable(new SM.Table({ name: 'Chart defects', columns: [{ name: 'cause', dataType: 'character', values: cause }, { name: 'shift', dataType: 'character', values: shift, valueOrder: ['night', 'day'] },
    { name: 'count', dataType: 'numeric', values: cnt }] }));
  const opn = [], part = [], y = [], week = [];
  const pe = Array.from({ length: 6 }, () => r.normal(0, 2));
  for (const o of ['Cy', 'Ann', 'Bo']) for (let q = 0; q < 6; q++) for (let k = 0; k < 3; k++) { opn.push(o); part.push(q + 1); week.push(Date.UTC(2026, 0, 5 + 7 * q)); y.push(+(10 + pe[q] + r.normal(0, 0.4)).toFixed(3)); }
  SM.app.addTable(new SM.Table({ name: 'Chart gauge', columns: [{ name: 'Operator', dataType: 'character', values: opn, valueOrder: ['Cy', 'Ann', 'Bo'] },
    { name: 'Part', dataType: 'numeric', modelingType: 'nominal', values: part }, { name: 'week', dataType: 'numeric', format: { kind: 'date' }, values: week }, { name: 'Y', dataType: 'numeric', values: y }] }));
  const ap = [], ar = [], av = [];
  for (let q = 0; q < 10; q++) { const truth = ['good', 'bad', 'fair'][q % 3]; for (const rr of ['C', 'A', 'B']) for (let k = 0; k < 2; k++) { ap.push(q + 1); ar.push(rr); av.push(r.u() > 0.2 ? truth : ['good', 'bad', 'fair'][Math.floor(3 * r.u())]); } }
  SM.app.addTable(new SM.Table({ name: 'Chart ratings', columns: [{ name: 'part', dataType: 'numeric', modelingType: 'nominal', values: ap }, { name: 'rater', dataType: 'character', values: ar, valueOrder: ['C', 'A', 'B'] },
    { name: 'rating', dataType: 'character', values: av }] }));
})()'''


def mplc(c):
    """A Plotly colour as the start of matplotlib's hex (#rrggbb, and the alpha when it has one)."""
    m = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)', c or '')
    if not m:
        return (c or '').lower()
    hexc = '#%02x%02x%02x' % (int(m[1]), int(m[2]), int(m[3]))
    return hexc + ('%02x' % round(float(m[4]) * 255) if m[4] is not None and float(m[4]) < 1 else '')


def mline(ax, x, y, color=None, ls=None, rel=1e-9, abs_=1e-12):
    for ln in ax['lines']:
        if color and not (ln['color'] or '').startswith(color):
            continue
        if ls is not None and ln['ls'] != ls:
            continue
        if close(ln['x'], x, rel, abs_) and close(ln['y'], y, rel, abs_):
            return ln
    return None


def jmp_q(v, p):
    """JMP's quantile, written out: the (n + 1)p-th of the sorted values, interpolated; before the first or after the last, that value."""
    s_ = sorted(float(x) for x in v)
    h = (len(s_) + 1) * p
    if h <= 1:
        return s_[0]
    if h >= len(s_):
        return s_[-1]
    k = int(h)
    return s_[k - 1] + (h - k) * (s_[k] - s_[k - 1])


def hazen_q(v, p):
    """Hazen's quantile (Plotly's own for a box of raw values): the (np + 1/2)-th value."""
    s_ = sorted(float(x) for x in v)
    h = len(s_) * p + 0.5
    if h <= 1:
        return s_[0]
    if h >= len(s_):
        return s_[-1]
    k = int(h)
    return s_[k - 1] + (h - k) * (s_[k] - s_[k - 1])


def jmp_box(v):
    """A box as JMP draws it: (q1, median, q3, the whiskers to the furthest values within 1.5 IQR of the box)."""
    q1, med, q3 = jmp_q(v, 0.25), jmp_q(v, 0.5), jmp_q(v, 0.75)
    iqr = q3 - q1
    return [q1, med, q3, min(x for x in v if x >= q1 - 1.5 * iqr), max(x for x in v if x <= q3 + 1.5 * iqr)]


def page_boxes(g):
    """The boxes the page gave Plotly: [q1, median, q3, lower fence, upper fence] for each box."""
    out = []
    for t in g['traces']:
        if t.get('type') == 'box':
            out += [list(q) for q in zip(t['q1'], t['median'], t['q3'], t['lowerfence'], t['upperfence'])]
    return out


def bxp_boxes(ax, width):
    """The boxes of matplotlib's bxp (patch_artist) in drawing order: [q1, median, q3, lower whisker, upper whisker]."""
    meds = [ln['y'][0] for ln in ax['lines'] if len(ln['y']) == 2 and ln['y'][0] == ln['y'][1] and abs(ln['x'][1] - ln['x'][0] - width) < 1e-9]
    pats = [sorted({p[1] for p in pa['xy'] if p[1] is not None}) for pa in ax['patches'] if pa['type'] == 'PathPatch']
    whisk = [ln['y'] for ln in ax['lines'] if len(ln['x']) == 2 and ln['x'][0] == ln['x'][1] and len(ln['y']) == 2]
    return [[b[0], m, b[-1], min(lo), max(hi)] for m, b, lo, hi in zip(meds, pats, whisk[0::2], whisk[1::2])]


def check_control(lab, g, D, F):
    """A control chart's figure against its Plotly graph."""
    check(f'{lab}: the size', F['size'], [g['w'] / 100, g['h'] / 100])
    two = D['axes'].get('yaxis2') is not None
    axes = F['axes']
    check(f'{lab}: a plot for each chart', len(axes), 2 if two else 1)
    for k, ax in enumerate(axes):
        on = 'y' if k == 0 else 'y2'
        tr = [(t, d) for t, d in zip(g['traces'], D['traces']) if (t.get('yaxis') or 'y') == on]
        lines = [t for t, d in tr if t.get('mode') == 'lines' and t.get('color') and d.get('lwidth') != 0]
        ok = all(mline(ax, t['x'], t['y'], mplc(t['color']), {'dot': ':', 'dash': '--'}.get(t.get('dash'), '-')) is not None for t in lines)
        check(f'{lab} ({on}): every line (limits, center, zones, the points joined) where the page draws it, in its colour', (len(lines) > 0, ok), (True, True))
        shades = [t for t, d in tr if t.get('fill') == 'tonexty']
        check(f'{lab} ({on}): the shaded zones', len(ax['polys']), len(shades))
        pts = [(t, d) for t, d in tr if t.get('mode') == 'markers' and t.get('x') and d.get('mcolors')]
        sc = [s for s in ax['scatter'] if s['colors']]
        for (t, d), s in zip(pts, sc):
            check(f'{lab} ({on}): the points of {t["name"]}, red where they fail a test', (close([q for p in s['xy'] for q in p], [q for p in zip(t['x'], t['y']) for q in p], 1e-12, 1e-12),
                                                                                         [c[:7] for c in s['colors']] == [mplc(c) for c in d.get('mcolors')] or len(set(d.get('mcolors'))) == 1 and {c[:7] for c in s['colors']} == {mplc(d.get('mcolors')[0])}), (True, True))
        check(f'{lab} ({on}): a scatter for each marked trace', len(sc), len(pts))
        means = [t for t, d in tr if t.get('mode') == 'markers' and t.get('x') and not d.get('mcolors') and d.get('symbol') == 'circle-open']
        if means:
            check(f'{lab} ({on}): the subgroup means', any(close([p[1] for p in s['xy']], means[0]['y'], 1e-12, 1e-12) for s in ax['scatter'] if not s['colors']), True)
        texts = [t for t, d in tr if t.get('mode') == 'text']
        want = sorted((round(a, 9), round(b, 9), s) for t in texts for a, b, s in zip(t['x'], t['y'], t['text']))
        check(f'{lab} ({on}): the tests\' numbers', sorted((round(t['x'], 9), round(t['y'], 9), t['s']) for t in ax['texts'] if t['s'][:1].isdigit()), want)
        right = [a['text'] for a in D['annotations'] if a.get('xref') == 'paper' and a.get('yref') == on]
        check(f'{lab} ({on}): the limits\' values at the right', [t['s'] for t in ax['texts'] if t['x'] is not None and abs(t['x'] - 1.004) < 1e-12], right)
        rng_ = D['axes']['yaxis' if k == 0 else 'yaxis2']['range']
        check(f'{lab} ({on}): the y range', close(ax['ylim'], rng_, 1e-9, 1e-12), True)
    xa = D['axes']['xaxis']
    check(f'{lab}: the x range', close(axes[-1]['xlim'], xa['range'], 1e-12), True)
    if xa.get('ticktext'):
        check(f'{lab}: the subgroups on the axis, as the page labels them', [t for t in axes[-1]['xticklabels'] if t], xa['ticktext'])
    phases = [a['text'] for a in D['annotations'] if a.get('yref') == 'paper']
    check(f'{lab}: the phases, named above, a dashed line between them', ([t['s'] for t in axes[0]['texts'] if t['y'] == 1.0],
                                                                       sorted(ln['x'][0] for ln in axes[0]['lines'] if ln['ls'] == '--' and ln['color'][:7] == '#786b5d')),
          (phases, sorted(s['x0'] for s in D['shapes'])))


async def chart_code(page):
    await page.ev(GRAPHS_JS)
    await page.ev(QG_JS)
    await page.ev('__gr.idle()')
    await page.ev(CHART_TABLES)
    # ---- control charts: every kind, phases, zones, tests; rows excluded, By, a date subgroup
    r = await page.ev('''(async () => {
      const t = __qg.table('Chart process'); t.setState([3, 17, 44], 'excluded', true);
      const all = [1, 2, 3, 4, 5, 6, 7, 8];
      const specs = [
        [{ y: ['d'], subgroup: ['subgroup'], phase: ['phase'] }, { zones: true, shade: true, tests: all, dispTests: true }],
        [{ y: ['d'] }, { chart: 'ir', zones: true, tests: all }], [{ y: ['d'], subgroup: ['subgroup'] }, { chart: 'xbar_s', tests: [1, 2, 5, 6] }],
        [{ y: ['d'], subgroup: ['subgroup'] }, { chart: 'ewma', tests: [1] }], [{ y: ['d'], subgroup: ['subgroup'] }, { chart: 'cusum', cusum: { h: 4, k: 0.5, target: 10 } }],
        [{ y: ['d'], subgroup: ['subgroup'] }, { chart: 'run', tests: [2, 3, 4] }], [{ y: ['bad'], subgroup: ['subgroup'], ntrials: ['n'] }, { chart: 'p', zones: true }],
        [{ y: ['bad'], subgroup: ['subgroup'] }, { chart: 'c', showCenter: false }], [{ y: ['d'], subgroup: ['day'] }, { chart: 'xbar_r' }],
        [{ y: ['d'], subgroup: ['subgroup'], by: ['operator'] }, { chart: 'xbar_r', shade: true }]];
      const out = [];
      for (const [roles, opts] of specs) {
        const rep = await __qg.open('Chart process', 'controlchart', roles, opts);
        out.push({ title: rep.title, graphs: await __gr.graphs(rep), details: __qg.details(rep), errors: __qg.errors(rep) });
      }
      return { reps: out, undrawn: __gr.take() };
    })()''', timeout=600)
    check('control chart code: no errors in the reports', [x['errors'] for x in r['reps']], [[]] * len(r['reps']))
    check('control chart code: every graph drawn', r['undrawn'], [])
    tbl = "__qg.table('Chart process')"
    for i, rep in enumerate(r['reps']):
        for g, D in zip(rep['graphs'], rep['details']):
            lab = f'control chart code {i + 1}: {g["label"]}'
            check(f'{lab}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
            if not g['code']:
                continue
            F, err = await run_graph(page, g, tbl)
            check(f'{lab}: the code runs in the page', err, None)
            if F:
                check_control(lab, g, D, F[0])
    check('the date subgroup: the page labels the points with their dates, and so does the code', r['reps'][8]['details'][0]['axes']['xaxis']['ticktext'][:2], ['2026-03-02', '2026-03-03'])
    check('By: a chart for each operator, each with its code', [g['label'] for g in r['reps'][9]['graphs']], ['XBar & R chart of d'] * 2)
    # ---- Process Capability: the goal plot, the box plots, the index plot, the histograms (a normal and a lognormal fit)
    r = await page.ev('''(async () => {
      const t = __qg.table('Chart process'); const o = { indexPlot: true, goalWithin: true, goalPpk: 1.3 }; o[t.col('c2').id + '|dist'] = 'lognormal';
      const rep = await __qg.open('Chart process', 'capability', { y: ['d', 'c2'], subgroup: ['subgroup'] }, o);
      const rep2 = await __qg.open('Chart process', 'capability', { y: ['d'], by: ['operator'] }, {});
      const out = { g1: await __gr.graphs(rep), d1: __qg.details(rep), g2: await __gr.graphs(rep2), d2: __qg.details(rep2), errors: [rep, rep2].flatMap((x) => __qg.errors(x)), undrawn: __gr.take() };
      t.setState([3, 17, 44], 'excluded', false);
      return out;
    })()''', timeout=600)
    check('capability code: no errors (two columns, a lognormal fit, subgroups; By)', r['errors'], [])
    check('capability code: every graph drawn', r['undrawn'], [])
    check('capability code: the graphs', [g['label'] for g in r['g1']], ['Goal plot', 'Capability box plots', 'Capability index plot', 'd capability histogram', 'c2 capability histogram'])
    for g, D in list(zip(r['g1'], r['d1'])) + list(zip(r['g2'], r['d2'])):
        lab = f'capability code: {g["label"]}'
        check(f'{lab}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
        if not g['code']:
            continue
        F, err = await run_graph(page, g, tbl)
        check(f'{lab}: the code runs in the page', err, None)
        if not F:
            continue
        F = F[0]
        ax = F['axes'][0]
        check(f'{lab}: the size', F['size'], [g['w'] / 100, g['h'] / 100])
        if g['label'] == 'Goal plot':
            tri, pts = g['traces'][0], g['traces'][1]
            poly = [p for p in ax['patches'] if p['type'] == 'Polygon'][0]['xy'][:3]
            check(f'{lab}: the triangle', close([q for p in poly for q in p], [q for p in zip(tri['x'], tri['y']) for q in p], 1e-12, 1e-15), True)
            check(f'{lab}: the columns\' points', close([q for p in ax['scatter'][0]['xy'] for q in p], [q for p in zip(pts['x'], pts['y']) for q in p], 1e-9, 1e-12), True)
            check(f'{lab}: the ranges, the axis titles', (close(ax['xlim'], D['axes']['xaxis']['range'], 1e-12), close(ax['ylim'], D['axes']['yaxis']['range'], 1e-12), ax['xlabel'], ax['ylabel']),
                  (True, True, g['titles']['x'], g['titles']['y']))
        elif g['label'] == 'Capability box plots':
            check(f'{lab}: each box, quartiles and whiskers, as the page gives them to Plotly', close([a for b in bxp_boxes(ax, 0.5) for a in b], [a for b in page_boxes(g) for a in b], 1e-9, 1e-12), True)
            outl = [sorted(t['y']) for t in g['traces'] if t.get('type') == 'scatter' and (t.get('name') or '').endswith(' outliers')]
            check(f'{lab}: the values beyond the whiskers, as the page marks them', [sorted(ln['y']) for ln in ax['lines'] if ln['marker'] == 'o' and ln['y']], outl)
            check(f'{lab}: the limits and the target', sorted(round(ln['y'][0], 12) for ln in ax['lines'] if ln['x'] == [0.0, 1.0]), sorted(round(s['y0'], 12) for s in D['shapes']))
        elif g['label'] == 'Capability index plot':
            for t in [t for t in g['traces'] if t.get('type') == 'bar' and t.get('name') in ('Ppk', 'Cpk')]:
                got = [None if b['h'] != b['h'] else b['h'] for b in ax['bars'] if b['fc'][:7] == ('#b0413e' if t['name'] == 'Ppk' else '#2e7d32')]
                check(f'{lab}: the bars of {t["name"]}', close(got, t['y'], 1e-9, 1e-12), True)
            check(f'{lab}: the line at 1', any(ln['y'] == [1.0, 1.0] and ln['ls'] == ':' for ln in ax['lines']), True)
        else:
            bar = [t for t in g['traces'] if t.get('type') == 'bar' and t.get('name') == 'Histogram'][0]
            check(f'{lab}: the bars, the page\'s bins and counts', (close([b['x'] + b['w'] / 2 for b in ax['bars']], bar['x'], 1e-9, 1e-12), [b['h'] for b in ax['bars']], close([b['w'] for b in ax['bars']], [bar['width']] * len(bar['x']), 1e-12)),
                  (True, bar['y'], True))
            for t in [t for t in g['traces'] if t.get('type') == 'scatter' and t.get('mode') == 'lines']:
                ln = [q for q in ax['lines'] if q['label'] == t['name']]
                check(f'{lab}: the {t["name"]} curve', bool(ln) and close(ln[0]['x'], t['x'], 1e-9, 1e-12) and maxdiff(ln[0]['y'], t['y']) <= 1e-6 * max(t['y']), True)
            check(f'{lab}: the spec limits', sorted(ln['x'][0] for ln in ax['lines'] if len(set(ln['x'])) == 1 and len(ln['x']) == 2), sorted(s['x0'] for s in D['shapes']))
            check(f'{lab}: the range, the titles', (close(ax['xlim'], D['axes']['xaxis']['range'], 1e-12), ax['xlabel'], ax['ylabel']), (True, g['titles']['x'], g['titles']['y']))
    # ---- Pareto: the counts with every option, and a plot for each shift
    r = await page.ev('''(async () => {
      const rep = await __qg.open('Chart defects', 'pareto', { y: ['cause'], freq: ['count'] }, { percent: true, legend: true, nLegend: true, cumLabels: true, combine: { below: 6 } });
      const rep2 = await __qg.open('Chart defects', 'pareto', { y: ['cause'], x: ['shift'] }, { cumAxis: false });
      return { g1: await __gr.graphs(rep), d1: __qg.details(rep), g2: await __gr.graphs(rep2), d2: __qg.details(rep2), errors: [rep, rep2].flatMap((x) => __qg.errors(x)), undrawn: __gr.take() };
    })()''', timeout=600)
    check('Pareto code: no errors, every graph drawn', (r['errors'], r['undrawn']), ([], []))
    check('Pareto code: a plot for each shift, in the order of its levels', [g['label'].split(' (N ')[0] for g in r['g2']], ['Pareto plot shift = night', 'Pareto plot shift = day'])
    for g, D in list(zip(r['g1'], r['d1'])) + list(zip(r['g2'], r['d2'])):
        lab = f'Pareto code: {g["label"]}'
        check(f'{lab}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
        if not g['code']:
            continue
        F, err = await run_graph(page, g, "__qg.table('Chart defects')")
        check(f'{lab}: the code runs in the page', err, None)
        if not F:
            continue
        F = F[0]
        ax = F['axes'][0]
        bars = [t for t in g['traces'] if t.get('type') == 'bar' and t.get('hoverinfo') != 'skip']
        heights = [v for t in bars for v in t['y']]
        check(f'{lab}: the bars', close([b['h'] for b in ax['bars']], heights, 1e-9, 1e-12), True)
        check(f'{lab}: the causes', [t for t in ax['xticklabels'] if t], [v for t in bars for v in t['x']])
        cum = [t for t in g['traces'] if t.get('name') == 'Cum Percent'][0]
        on_right = cum.get('yaxis') == 'y2'
        cx = F['axes'][1] if on_right else ax
        check(f'{lab}: the cumulative percent{" on its own axis" if on_right else ""}', close(cx['lines'][0]['y'], cum['y'], 1e-9, 1e-12), True)
        check(f'{lab}: the y range, the title, the size', (close(ax['ylim'], D['axes']['yaxis']['range'], 1e-9), ax['ylabel'], F['size']), (True, g['titles']['y'], [g['w'] / 100, g['h'] / 100]))
        check(f'{lab}: the bars\' colours (the Category Legend\'s palette, or the page\'s bar colour)', [b['fc'][:7] for b in ax['bars']], [mplc(t['mcolor']) for t in bars for _ in t['y']])
        if [a for a in D['annotations'] if a['text'].startswith('N = ')]:
            check(f'{lab}: the N Legend', [t['s'] for t in ax['texts'] if t['s'].startswith('N = ')], [a['text'] for a in D['annotations'] if a['text'].startswith('N = ')])
        labels_ = [s for s in (cum.get('text') or []) if s]
        if labels_:
            check(f'{lab}: the cumulative percents labelled', [t['s'] for t in cx['texts'] if t['s'].endswith('%')], labels_)
    # ---- the variability chart (every option; a date factor) and the attribute gauge
    r = await page.ev('''(async () => {
      const all = { points: true, rangeBars: true, cellMeans: true, connect: true, groupMeans: true, grandMean: true, grandMedian: true, boxes: true, jitter: true, sdChart: true, meanSd: true, sLimits: true };
      const rep = await __qg.open('Chart gauge', 'variability', { y: ['Y'], x: ['Operator', 'Part'] }, all);
      const rep2 = await __qg.open('Chart gauge', 'variability', { y: ['Y'], x: ['week'] }, {});
      const rep3 = await __qg.open('Chart ratings', 'variability', { y: ['rating'], x: ['rater'], part: ['part'] }, {});
      return { g: [await __gr.graphs(rep), await __gr.graphs(rep2), await __gr.graphs(rep3)], d: [__qg.details(rep), __qg.details(rep2), __qg.details(rep3)],
        errors: [rep, rep2, rep3].flatMap((x) => __qg.errors(x)), undrawn: __gr.take() };
    })()''', timeout=600)
    check('variability and attribute gauge code: no errors, every graph drawn', (r['errors'], r['undrawn']), ([], []))
    for k, (gs, ds) in enumerate(zip(r['g'], r['d'])):
        tname = "__qg.table('Chart ratings')" if k == 2 else "__qg.table('Chart gauge')"
        for g, D in zip(gs, ds):
            lab = f'{"attribute gauge" if k == 2 else "variability"} code: {g["label"]}{" (a date factor)" if k == 1 else ""}'
            check(f'{lab}: its code block is right under it, ending in plt.show()', bool(g['code']) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)
            if not g['code']:
                continue
            F, err = await run_graph(page, g, tname)
            check(f'{lab}: the code runs in the page', err, None)
            if not F:
                continue
            F = F[0]
            ax = F['axes'][0]
            check(f'{lab}: the size', F['size'], [g['w'] / 100, g['h'] / 100])
            if k == 2:
                t = g['traces'][0]
                got = ax['lines'][0]['y'] if g['label'] == 'Agreement by part' else [p[1] for p in ax['scatter'][0]['xy']]
                check(f'{lab}: the agreements', close(got, t['y'], 1e-12, 1e-12), True)
                check(f'{lab}: the ticks, the range', ([s for s in ax['xticklabels'] if s], close(ax['ylim'], [-5, 105])), (D['axes']['xaxis']['ticktext'], True))
                continue
            tr = g['traces']
            sym = [d.get('symbol') for d in D['traces']]
            pts = [t for t in tr if t.get('mode') == 'markers' and t.get('name') == 'Y' and t.get('x')]
            if pts:
                got = ax['scatter'][0]['xy']
                check(f'{lab}: each point at its cell (jittered as the page jitters, with numbers of its own) and its value',
                      len(got) == len(pts[0]['y']) and all(round(a[0]) == round(b) and abs(a[0] - round(a[0])) <= 0.18 + 1e-9 and abs(a[1] - c) < 1e-12 for a, b, c in zip(got, pts[0]['x'], pts[0]['y'])), True)
            means = [t for t, sy in zip(tr, sym) if sy == 'line-ew']
            cm = [q for q in ax['lines'] if q['marker'] == '_']
            if means:
                check(f'{lab}: the cell means, joined when the page joins them', (bool(cm) and close(cm[0]['y'], means[0]['y'], 1e-12), cm[0]['ls'] if cm else None),
                      (True, '-' if 'lines' in (means[0].get('mode') or '') else 'None'))
            rb = [t for t in tr if t.get('mode') == 'lines' and (t.get('yaxis') or 'y') == 'y' and t.get('color') == '#786b5d']
            if rb:
                want = sorted((a, b, c) for a, b, c in zip(rb[0]['x'][0::3], rb[0]['y'][0::3], rb[0]['y'][1::3]))
                segs = sorted((s[0][0], s[0][1], s[1][1]) for c_ in ax['segments'] for s in c_['segs'])
                check(f'{lab}: the range bars', segs, want)
            gm = [t for t in tr if t.get('mode') == 'lines' and t.get('color') == '#8c6d00']
            if gm:
                pairs = [(gm[0]['x'][i:i + 2], gm[0]['y'][i:i + 2]) for i in range(0, len(gm[0]['x']), 3)]
                check(f'{lab}: the group means', all(mline(ax, x2, y2, '#8c6d00') is not None for x2, y2 in pairs), True)
            for s in D['shapes']:
                if s.get('xref') == 'paper':
                    check(f'{lab}: the grand {"median" if s.get("dash") == "dash" else "mean"}', mline(ax, [0.0, 1.0], [s['y0']] * 2, ls='--' if s.get('dash') == 'dash' else '-') is not None, True)
            if page_boxes(g):
                check(f'{lab}: each cell\'s box, quartiles and whiskers, as the page gives them to Plotly', close([a for b in bxp_boxes(ax, 0.5) for a in b], [a for b in page_boxes(g) for a in b], 1e-9, 1e-12), True)
            check(f'{lab}: the y range', close(ax['ylim'], D['axes']['yaxis']['range'], 1e-9, 1e-12), True)
            bottom = F['axes'][-1]
            check(f'{lab}: the inner levels on the axis, as the page labels them (a date as a date)', [t for t in bottom['xticklabels'] if t], D['axes']['xaxis']['ticktext'])
            outer = [a['text'] for a in D['annotations']]
            check(f'{lab}: the outer levels under the inner ones', [t['s'] for t in bottom['texts']], outer)
            if len(F['axes']) > 1:
                bx = F['axes'][1]
                sd = [t for t in tr if t.get('yaxis') == 'y2' and t.get('mode') == 'lines+markers'][0]
                check(f'{lab}: the standard deviations', close([q for q in bx['lines'] if q['marker'] == 'o'][0]['y'], sd['y'], 1e-12), True)
                for t in [t for t in tr if t.get('yaxis') == 'y2' and t.get('mode') == 'lines']:
                    check(f'{lab}: the {"mean of the standard deviations" if t.get("color") == "#2e7d32" else "S chart limit"}', mline(bx, t['x'], t['y'], rel=1e-9) is not None, True)
                check(f'{lab}: the std dev chart\'s range', close(bx['ylim'], D['axes']['yaxis2']['range'], 1e-9, 1e-12), True)
    # ---- JMP's quartiles, on a small case where Hazen's rule (Plotly's own for raw values) gives others
    x10 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 30]
    ya, yb = [1, 2, 3, 4, 20], [5, 6, 7, 8, 9]
    r = await page.ev(f'''(async () => {{
      SM.app.addTable(new SM.Table({{ name: 'Chart small', columns: [{{ name: 'x', dataType: 'numeric', values: {json.dumps(x10)}, specLimits: {{ lsl: 0, target: 20, usl: 40 }} }},
        {{ name: 'g', dataType: 'character', values: {json.dumps(['a'] * 5 + ['b'] * 5)} }}, {{ name: 'y', dataType: 'numeric', values: {json.dumps(ya + yb)} }}] }}));
      const rep = await __qg.open('Chart small', 'capability', {{ y: ['x'] }}, {{}});
      const rep2 = await __qg.open('Chart small', 'variability', {{ y: ['y'], x: ['g'] }}, {{ boxes: true }});
      const out = {{ g1: await __gr.graphs(rep), g2: await __gr.graphs(rep2), errors: [rep, rep2].flatMap((x) => __qg.errors(x)), undrawn: __gr.take() }};
      const p = rep.plots.find((q) => q.opts.title === 'Capability box plots'); await p.draw();   // a click on the outlier selects its row
      const i = p.traces.findIndex((tr) => (tr.name || '').endsWith(' outliers'));
      p._click({{ points: [{{ curveNumber: i, pointNumber: 0 }}], event: {{}} }});
      out.selected = rep.table.selectedRows(); rep.table.select([]);
      return out;
    }})()''', timeout=600)
    check('the small case: no errors, every graph drawn', (r['errors'], r['undrawn']), ([], []))
    check('the small case: Hazen\'s quartiles are other than JMP\'s here', ([hazen_q(x10, 0.25), hazen_q(x10, 0.75)], [jmp_q(x10, 0.25), jmp_q(x10, 0.75)]), ([3.0, 8.0], [2.75, 8.25]))
    boxg = [g for g in r['g1'] if g['label'] == 'Capability box plots'][0]
    sc = lambda v: (v - 20) / 40  # noqa: E731
    check('the small case: the capability box as JMP draws it, worked out by the (n + 1)p rule (quartiles 2.75, 5.5, 8.25; whiskers 1 and 9)',
          close(page_boxes(boxg)[0], [sc(v) for v in jmp_box(x10)], 1e-12, 1e-15), True)
    check('the small case: 30, beyond the upper whisker, is a point, and a click on it selects its row', ([t['y'] for t in boxg['traces'] if (t.get('name') or '').endswith(' outliers')], r['selected']), ([[sc(30)]], [9]))
    varg = r['g2'][0]
    check('the small case: each cell\'s box as JMP draws it (a: quartiles 1.5, 3, 12, whiskers 1 and 20)', close([a for b in page_boxes(varg) for a in b], jmp_box(ya) + jmp_box(yb), 1e-12, 1e-15), True)
    check('... where Hazen\'s rule would give other quartiles of a', [hazen_q(ya, 0.25), hazen_q(ya, 0.75)] != [jmp_q(ya, 0.25), jmp_q(ya, 0.75)], True)
    for g, want in ((boxg, [[sc(v) for v in jmp_box(x10)]]), (varg, [jmp_box(ya), jmp_box(yb)])):
        F, err = await run_graph(page, g, "__qg.table('Chart small')")
        check(f'the small case: {g["label"]}: the code runs in the page', err, None)
        if F:
            check(f'the small case: {g["label"]}: the code draws the same boxes (np.quantile, method="weibull")', close([a for b in bxp_boxes(F[0]['axes'][0], 0.5) for a in b], [a for b in want for a in b], 1e-12, 1e-15), True)
    await page.ev("for (const r of SM.app.reports.filter((x) => x.table && x.table.name.startsWith('Chart '))) SM.app.closeReport(r); for (const n of ['Chart process', 'Chart defects', 'Chart gauge', 'Chart ratings', 'Chart small']) SM.app.closeTable(__qg.table(n));")


asyncio.run(main())
sys.exit(check.done())
