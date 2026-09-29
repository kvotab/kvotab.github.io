#!/usr/bin/env python3
"""smui.html in a real browser: Analyze > Multivariate Methods,
Clustering and Screening (resources/js/smui-p-multivariate.js).

A table is simulated in the page from a fixed seed: five correlated columns
with one missing value, a three-level group, a frequency. Every platform
opens with its options on and without an error; the numbers shown agree
with numbers computed here in the page (correlations, eigenvalues, counts);
graphs link to the table both ways; saved columns land in the table; row
colours follow the clusters; By gives one report per level; Response
Screening opens Fit Y by X when that platform is loaded; the distance
correlations agree with the doubly centred distances computed in the page;
Item Reliability's intraclass correlations and Kendall's W agree with an ANOVA
and ranks computed in the page, and Bootstrap reruns them; every graph's
matplotlib code (a block right under it) runs in the page's Python and draws
that graph (with By and excluded rows, the code keeps the group's rows and
leaves out the excluded ones); the statistics code of Discriminant, K Means,
Response Screening, Factor Analysis and Hierarchical Cluster gives the numbers
their reports show, the clusters those of Save Clusters; the dark theme and
phone width draw.

Start a server on the repository root and headless Chrome on
SMUI_HTTP_PORT and SMUI_CDP_PORT (see README.md), then

    python3 resources/tests/smui/test-ui-multivariate.py

With SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every
check passes.
"""
import asyncio
import bisect
import json
import os
import re
import sys

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine
from test_charts import GRAPHS_JS, PROBE, close, figures_from_outputs, strip_show

SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()

MAKE = r'''
(() => {
  const r = SM.util.rng('smui-multivariate-test'); const n = 150;
  const c = { a: [], b: [], c: [], d: [], e: [], grp: [], f: [], u: [], v: [], q1: [], q2: [] };
  for (let i = 0; i < n; i++) {
    const z1 = r.normal(), z2 = r.normal();
    c.a.push(+(z1 + 0.3 * r.normal()).toFixed(4)); c.b.push(+(z1 + 0.5 * r.normal()).toFixed(4));
    c.c.push(+(z2 + 0.4 * r.normal()).toFixed(4)); c.d.push(+(z2 - 0.3 * z1 + 0.6 * r.normal()).toFixed(4));
    c.e.push(+(0.5 * z1 + 0.5 * z2 + 0.7 * r.normal()).toFixed(4));
    c.grp.push(z1 > 0.4 ? 'hi' : (z2 > 0 ? 'mid' : 'lo')); c.f.push(1 + (i % 3));
    const k = i % 3;   // three well separated clusters in u, v
    c.u.push(+([0, 6, 0][k] + r.normal()).toFixed(3)); c.v.push(+([0, 0, 6][k] + r.normal()).toFixed(3));
    c.q1.push(r.u() < 0.7 ? ['A', 'B', 'C'][k] : r.pick(['A', 'B', 'C'])); c.q2.push(r.u() < 0.6 ? ['x', 'y', 'y'][k] : r.pick(['x', 'y']));
  }
  c.b[7] = NaN;
  const t = new SM.Table({ name: 'Multivariate test', source: 'simulated', columns: [
    { name: 'id', dataType: 'character', values: Array.from({ length: n }, (_, i) => `R${i + 1}`), role: 'label' },
    ...['a', 'b', 'c', 'd', 'e'].map((k) => ({ name: k, dataType: 'numeric', values: c[k] })),
    { name: 'grp', dataType: 'character', values: c.grp },
    { name: 'f', dataType: 'numeric', values: c.f },
    { name: 'u', dataType: 'numeric', values: c.u }, { name: 'v', dataType: 'numeric', values: c.v },
    { name: 'q1', dataType: 'character', values: c.q1 }, { name: 'q2', dataType: 'character', values: c.q2 },
  ] });
  SM.app.addTable(t);
  return t.nrows;
})()
'''

# The report open last, its plots, and a fresh context for menu actions.
LAST = 'SM.app.reports[SM.app.reports.length - 1]'
CTX = f'(() => {{ const rep = {LAST}; return new SM.report.Ctx(rep, {{ rows: rep.table.includedRows() }}, rep.content || rep.body, ""); }})()'


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


# The (i) of a launch dialog, of a form and of an outline: open it, read the
# sections of its panel ([{heading, choices: [[name, text]]}]), close it; and
# the labels of the controls in an outline (the inputs' labels, the buttons).
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
  // an outline of the report by its title, or by the start of it
  head(rep, title) { return [...rep.body.querySelectorAll('.sm-ob-head')].find((x) => { const t = x.querySelector('h2, h3, h4').textContent; return t === title || (title.endsWith('…') && t.startsWith(title.slice(0, -1))); }); },
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
  // the (i) of an outline, and the labels of the controls in it
  async outline(rep, title) {
    const h = this.head(rep, title);
    if (!h) return { error: `no outline ${title}` };
    const body = h.parentElement.querySelector(':scope > .sm-ob-body');
    const controls = [];
    body.querySelectorAll(':scope > .mv-controls').forEach((box) => {
      box.querySelectorAll(':scope > .mv-control > span').forEach((s) => controls.push(s.textContent));
      box.querySelectorAll(':scope > button').forEach((b) => controls.push(b.textContent));
    });
    return { info: await this.read(h.querySelector(':scope .info-btn')), controls };
  },
};
'''


def section(info, heading):
    """The choices of the last section of an (i) panel with this heading."""
    secs = [s for s in (info or {}).get('secs', []) if s['heading'] == heading]
    return secs[-1]['choices'] if secs else []


def check_launch(r, name):
    check(f'{name} launch dialog: every (i) has a topic while it is open', r.get('noTopic'), [])
    roles = section(r.get('info'), 'Roles')
    check(f'{name} launch (i): the Roles list every role', [n for n, _ in roles], r.get('roles'))
    check(f'{name} launch (i): each role says what it is for before what it takes', [n for n, t in roles if t.startswith('(') or len(t) < 60], [])
    opts = section(r.get('info'), 'Options')
    check(f'{name} launch (i): the Options list every option, each with its help', ([n for n, _ in opts], [n for n, t in opts if len(t) < 40]), (r.get('options'), []))


def check_form(r, name, title=None, expect=None):
    """A form's (i) explains every field: under its label, or under the name
    (helpLabel) that stands for fields repeated per item (expect)."""
    check(f'{name}: the form opens, every (i) has a topic while it is open', (r.get('error'), r.get('noTopic')), (None, []))
    fields = section(r.get('info'), 'Fields')
    names = [n for n, _ in fields]
    if expect is not None:
        check(f'{name}: its (i) explains the fields repeated per item once', (names, len(r.get('labels') or []) > len(names)), (expect, True))
    else:
        missing = [lab for lab in r.get('labels') or [] if lab not in names and not any(n.lower() in lab.lower() for n in names)]
        check(f'{name}: its (i) explains every field', (bool(names), missing), (True, []))
    check(f'{name}: ... each with what it is for', [n for n, t in fields if len(t) < 30], [])
    if title:
        check(f'{name}: the (i) builds on the topic {title}', (r.get('info') or {}).get('title'), title)


def names_of(choices):
    """The controls a list of choices explains: 'x, y' and '− and +' name two."""
    out = set()
    for n, _ in choices:
        out.update(p.strip() for p in n.replace(' and ', ', ').split(', '))
        out.add(n)
    return out


async def run_menu(page, label, sub=None):
    """Run an item of the top red triangle of the report open last."""
    return await page.ev(f'''(async () => {{
      const rep = {LAST}; const ctx = {CTX};
      let items = rep.platform.triangle(ctx).filter(Boolean);
      let it = items.find(x => x.label === {json.dumps(label)});
      if (!it) return 'no item ' + {json.dumps(label)};
      if ({json.dumps(sub)} !== null) {{ const s = typeof it.submenu === 'function' ? it.submenu() : it.submenu; it = s.find(x => x.label === {json.dumps(sub)}); if (!it) return 'no subitem'; }}
      const done = new Promise(res => rep.on('done', res));
      const before = rep.seq;
      await it.action();
      await new Promise(r => setTimeout(r, 30));
      if (rep.seq !== before) await Promise.race([done, new Promise(r => setTimeout(r, 60000))]);
      return 'ok';
    }})()''')


# ---- the graphs' matplotlib code --------------------------------------------------------------------------------------
# Every graph of these reports has a code block right under it; each block is
# run in the page's own Python (the notebook's runner, as test_charts' GRAPHS_JS
# runs it) and its figure is compared with the Plotly graph: every line (split
# at its gaps), every point, the bars, the heatmap cells, the texts and
# annotations, the reference lines and the unit circle, the colours of points
# coloured one by one and of the lines, the axis titles, the fixed ranges and
# the tick labels, the legend, the title and the size.

# The probe of test_charts, and per axes whether it is shown, the colours of its
# line collections, and its images' colour scales.
MV_PROBE = PROBE + r'''
def _mv_figures():
    import matplotlib.pyplot as _plt
    from matplotlib.collections import LineCollection as _LC
    from matplotlib.colors import to_hex as _hex
    figs = _smui_figures()
    for F, n in zip(figs, _plt.get_fignums()):
        fig = _plt.figure(n)
        for A, ax in zip(F['axes'], fig.axes):
            A['shown'] = bool(ax.get_visible())
            A['segcolors'] = [[_hex(c) for c in coll.get_colors()] for coll in ax.collections if isinstance(coll, _LC)]
            A['imscale'] = [{'lo': _hex(im.cmap(0.0)), 'mid': _hex(im.cmap(0.5)), 'hi': _hex(im.cmap(1.0)), 'clim': [float(v) for v in im.get_clim()]} for im in ax.images]
            A['polygons'] = sum(1 for p in ax.patches if type(p).__name__ == 'Polygon')
    return figs
'''


async def run_mv(page, code, table_js):
    """A graph's code run in the page's Python, with the probe: (figures, error)."""
    probe = strip_show(code) + '\n' + MV_PROBE + '\nimport json as _json\nprint("SMUI-FIGURES " + _json.dumps(_mv_figures()))\n'
    out = await page.ev(f'__gr.run({json.dumps(probe)}, {table_js})', timeout=300)
    if isinstance(out, str):
        return None, out
    return figures_from_outputs(out.get('outputs'))


# The table for the graphs' code: correlated columns with a missing value, a
# date column, groups, clusters, categories, a weight and a frequency (with a
# zero); each report's graphs with more of their layout than __gr.graphs gives.
CHART_TABLE = r'''
(() => {
  const r = SM.util.rng('mv-charts'); const n = 72;
  const c = { id: [], a: [], b: [], c: [], d: [], e: [], dt: [], grp: [], yb: [], u: [], v: [], q1: [], q2: [], q3: [], w: [], f: [] };
  for (let i = 0; i < n; i++) {
    const z1 = r.normal(), z2 = r.normal();
    c.id.push(`P${i + 1}`);
    c.a.push(+(z1 + 0.3 * r.normal()).toFixed(4)); c.b.push(+(z1 + 0.5 * r.normal()).toFixed(4));
    c.c.push(+(z2 + 0.4 * r.normal()).toFixed(4)); c.d.push(+(z2 - 0.3 * z1 + 0.6 * r.normal()).toFixed(4));
    c.e.push(+(0.5 * z1 + 0.5 * z2 + 0.7 * r.normal()).toFixed(4));
    c.dt.push(Date.UTC(2024, 0, 1) + 86400000 * Math.round(30 * z1 + 2 * i));
    c.grp.push(z1 > 0.3 ? 'hi' : (z2 > 0 ? 'mid' : 'lo')); c.yb.push(z1 + 0.5 * r.normal() > 0 ? 'yes' : 'no');
    const k = i % 3;
    c.u.push(+([0, 6, 0][k] + r.normal()).toFixed(3)); c.v.push(+([0, 0, 6][k] + r.normal()).toFixed(3));
    c.q1.push(r.u() < 0.7 ? ['A', 'B', 'C'][k] : r.pick(['A', 'B', 'C'])); c.q2.push(r.u() < 0.6 ? ['x', 'y', 'y'][k] : r.pick(['x', 'y']));
    c.q3.push(1 + ((i + (r.u() < 0.3 ? 1 : 0)) % 2));
    c.w.push(+(0.5 + 1.5 * r.u()).toFixed(3)); c.f.push(i === 11 ? 0 : 1 + (i % 3));
  }
  c.b[7] = NaN;
  const t = new SM.Table({ name: 'MV charts', source: 'simulated', columns: [
    { name: 'id', dataType: 'character', values: c.id, role: 'label' },
    ...['a', 'b', 'c', 'd', 'e'].map((k) => ({ name: k, dataType: 'numeric', values: c[k] })),
    { name: 'dt', dataType: 'numeric', format: { kind: 'date' }, values: c.dt },
    { name: 'grp', dataType: 'character', values: c.grp }, { name: 'yb', dataType: 'character', values: c.yb },
    { name: 'u', dataType: 'numeric', values: c.u }, { name: 'v', dataType: 'numeric', values: c.v },
    { name: 'q1', dataType: 'character', values: c.q1 }, { name: 'q2', dataType: 'character', values: c.q2 },
    { name: 'q3', dataType: 'numeric', modelingType: 'nominal', values: c.q3 },
    { name: 'w', dataType: 'numeric', values: c.w }, { name: 'f', dataType: 'numeric', values: c.f },
  ] });
  SM.app.addTable(t);
  return t.nrows;
})()
'''

MVG_JS = r'''
window.__mvg = {
  table(name) { return SM.app.tables.find((t) => t.name === name); },
  async open(tname, platform, roles, options) {
    const t = this.table(tname);
    SM.app.showTab(SM.app.tabOf(t));
    const ids = {};
    for (const [k, names] of Object.entries(roles)) ids[k] = names.map((n) => { const c = t.col(n); if (!c) throw new Error('no column ' + n); return c.id; });
    const rep = SM.app.openReport(SM.platforms.get(platform), { roles: ids, options: options || {} }, t);
    await new Promise((res) => rep.on('done', res));
    return rep;
  },
  // the closed outlines that hold graphs opened (a K Means fit other than the one shown)
  openAll(rep) { rep.body.querySelectorAll('.sm-ob.is-closed').forEach((s) => { if (s.querySelector('.sm-plot') && s._outline) s._outline.setOpen(true); }); },
  errors(rep) { return [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => e.textContent.slice(0, 300)); },
  // each graph's layout (every axis, the annotations, the shapes) and its traces as drawn
  more(rep) {
    const txt = (a) => (a && a.title ? (typeof a.title === 'string' ? a.title : a.title.text) : null);
    const arr = (v) => (v == null ? v : Array.isArray(v) ? v.map((x) => (Array.isArray(x) ? [...x] : x)) : ArrayBuffer.isView(v) ? Array.from(v) : v);
    return [...rep.body.querySelectorAll('.js-plotly-plot')].map((p) => {
      const L = p.layout || {};
      const axes = {};
      const full = p._fullLayout || {};
      for (const k of Object.keys(L)) if (/^[xy]axis\d*$/.test(k)) { const a = L[k]; axes[k] = { title: txt(a), range: a.range ? [...a.range] : null, autorange: full[k] ? full[k].autorange : a.autorange, scaleanchor: a.scaleanchor || null, domain: a.domain ? [...a.domain] : null, type: a.type, ticktext: arr(a.ticktext), tickvals: arr(a.tickvals) }; }
      return { axes, showlegend: !!L.showlegend,
        annotations: (L.annotations || []).map((a) => ({ text: a.text, x: a.x, y: a.y, xref: a.xref, yref: a.yref })),
        shapes: (L.shapes || []).map((s) => ({ type: s.type, x0: s.x0, x1: s.x1, y0: s.y0, y1: s.y1, xref: s.xref, yref: s.yref, dash: s.line && s.line.dash, color: s.line && s.line.color })),
        traces: (p.data || []).map((d) => ({ type: d.type || 'scatter', mode: d.mode, name: d.name, showlegend: d.showlegend, xaxis: d.xaxis, yaxis: d.yaxis, x: arr(d.x), y: arr(d.y), z: arr(d.z), text: arr(d.text),
          texttemplate: d.texttemplate, base: arr(d.base), width: arr(d.width), orientation: d.orientation, fill: d.fill, zmin: d.zmin, zmax: d.zmax, zmid: d.zmid,
          colorscale: Array.isArray(d.colorscale) ? d.colorscale : null, mcolor: d.marker ? arr(d.marker.color) : null, lcolor: d.line ? d.line.color : null, dash: d.line ? d.line.dash : null })) };
    });
  },
};
'''


def hexc(c):
    """A colour as #rrggbb: from #rgb, #rrggbb(aa), rgb() or rgba(); None for anything else."""
    if not isinstance(c, str):
        return None
    c = c.strip().lower()
    m = re.match(r'^#([0-9a-f]{6})', c)
    if m:
        return '#' + m.group(1)
    m = re.match(r'^#([0-9a-f])([0-9a-f])([0-9a-f])$', c)
    if m:
        return '#' + ''.join(x * 2 for x in m.groups())
    m = re.match(r'^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)', c)
    if m:
        return '#' + ''.join(f'{int(round(float(x))):02x}' for x in m.groups())
    return None


def near(a, b, tol):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def pieces(xs, ys):
    """The points of a trace or a line, split at its gaps: lists of two or more (x, y)."""
    out, cur = [], []
    for a, b in zip(xs or [], ys or []):
        if a is None or b is None:
            if len(cur) > 1:
                out.append(cur)
            cur = []
        else:
            cur.append((float(a), float(b)))
    if len(cur) > 1:
        out.append(cur)
    return out


def same_piece(p, q, tol):
    return len(p) == len(q) and all(near(a[0], b[0], tol) and near(a[1], b[1], tol) for a, b in zip(p, q))


def fig_pieces(ax):
    """The figure's lines (split at gaps) and line collections' segments, each with its colour."""
    out = [(pc, hexc(ln['color'])) for ln in ax['lines'] for pc in pieces(ln['x'], ln['y'])]
    for c, cols in zip(ax['segments'], ax.get('segcolors') or [[]] * len(ax['segments'])):
        for k, s in enumerate(c['segs']):
            col = cols[k % len(cols)] if cols else None
            out += [(pc, hexc(col)) for pc in pieces([q[0] for q in s], [q[1] for q in s])]
    return out


def fig_points(ax):
    """Every point the figure marks: its scatters' points and the vertices of its lines with markers."""
    P = [(q[0], q[1]) for s in ax['scatter'] for q in s['xy'] if q[0] is not None and q[1] is not None]
    for ln in ax['lines']:
        if ln['marker'] not in ('None', 'none', '', ' ', 'nothing'):
            P += [(a, b) for a, b in zip(ln['x'], ln['y']) if a is not None and b is not None]
    return sorted(P)


def missing_points(want, have, tol):
    """How many of the wanted points the figure does not mark."""
    xs = [p[0] for p in have]
    miss = 0
    for a, b in want:
        k = bisect.bisect_left(xs, a - tol * max(1.0, abs(a)))
        found = False
        while k < len(have) and have[k][0] <= a + tol * max(1.0, abs(a)):
            if near(have[k][1], b, tol):
                found = True
                break
            k += 1
        miss += not found
    return miss


def fig_texts(ax):
    return [t['s'].strip() for t in ax['texts'] if t['s'] and t['s'].strip()]


def trace_points(t, xcats=None):
    xs = [xcats.index(v) if xcats and isinstance(v, str) else v for v in (t.get('x') or [])]
    return xs, list(t.get('y') or [])


def check_plot(lab, g, M, F, ax_index=0, tol=1e-8, xcats=None, size=True):
    """The figure of a graph against its Plotly graph: see the section's comment."""
    ax = F['axes'][ax_index]
    check(f'{lab}: the title', ax['title'] or F['suptitle'], g['label'])
    if size:
        check(f'{lab}: the size, at 100 pixels an inch', F['size'], [g['w'] / 100, g['h'] / 100])
    xa, ya = M['axes'].get('xaxis') or {}, M['axes'].get('yaxis') or {}
    check(f'{lab}: the axis titles', (ax['xlabel'], ax['ylabel']), (xa.get('title') or '', ya.get('title') or ''))
    anchored = any(a_.get('scaleanchor') for a_ in M['axes'].values())   # Plotly widens one of those ranges to keep the aspect
    for key, lim, name in ((xa, 'xlim', 'x'), (ya, 'ylim', 'y')):
        if key.get('autorange') is False and key.get('range') and not anchored:
            check(f'{lab}: the {name} axis over the page\'s range', close(ax[lim], key['range'], 1e-9, 1e-12), True)
        if key.get('ticktext') is not None and len(key.get('ticktext') or []):
            check(f'{lab}: the {name} axis\'s tick labels', [t for t in ax[f'{name}ticklabels'] if t], [str(t) for t in key['ticktext']])
    lines, points, texts, colored, line_colors = [], [], [], [], []
    for t in M['traces']:
        if t['type'] in ('scatter', 'scattergl'):
            xs, ys = trace_points(t, xcats)
            mode = t.get('mode') or 'markers'
            if 'lines' in mode:
                for pc in pieces(xs, ys):
                    lines.append(pc)
                    line_colors.append(hexc(t.get('lcolor')))
            if 'markers' in mode:
                pts = [(float(a), float(b)) for a, b in zip(xs, ys) if a is not None and b is not None]
                points += pts
                if isinstance(t.get('mcolor'), list) and pts:
                    colored.append((pts, [hexc(c) for c, a, b in zip(t['mcolor'], xs, ys) if a is not None and b is not None]))
            if 'text' in mode and t.get('text'):
                texts += [str(s).strip() for s in (t['text'] if isinstance(t['text'], list) else [t['text']]) if s is not None and str(s).strip()]
    fl = fig_pieces(ax)
    miss = [pc for pc in lines if not any(same_piece(q, pc, tol) for q, _ in fl)]
    check(f'{lab}: every line of the graph ({len(lines)}) in the figure', len(miss), 0)
    wrong = [i for i, pc in enumerate(lines) if line_colors[i] and not any(same_piece(q, pc, tol) and c == line_colors[i] for q, c in fl)]
    check(f'{lab}: ... in its colour', len(wrong), 0)
    check(f'{lab}: every point of the graph ({len(points)}) in the figure', missing_points(points, fig_points(ax), tol), 0)
    marks = sorted((q[0], q[1], hexc(s['colors'][k if len(s['colors']) > 1 else 0]) if s['colors'] else None)
                   for s in ax['scatter'] for k, q in enumerate(s['xy']) if q[0] is not None and q[1] is not None)
    for pts, cols in colored:      # points coloured one by one: each where the figure marks it, in its colour
        xs_ = [m_[0] for m_ in marks]
        bad = 0
        for (a, b), c in zip(pts, cols):
            k = bisect.bisect_left(xs_, a - tol * max(1.0, abs(a)))
            ok = False
            while k < len(marks) and marks[k][0] <= a + tol * max(1.0, abs(a)):
                if near(marks[k][1], b, tol) and marks[k][2] == c:
                    ok = True
                    break
                k += 1
            bad += not ok
        check(f'{lab}: {len(pts)} points coloured one by one, each in its colour', bad, 0)
    for t in M['traces']:
        if t['type'] == 'bar' and t.get('x') and t.get('y'):
            base = t.get('base')
            want = [(float(a), float(b), float(base[i] if isinstance(base, list) else (base or 0))) for i, (a, b) in enumerate(zip(t['x'], t['y']))]
            got = [(b_['x'] + b_['w'] / 2, b_['h'], b_['y']) for b_ in ax['bars']]
            check(f'{lab}: the bars (their places, heights and bottoms)', len(got) == len(want) and all(near(p[0], q[0], tol) and near(p[1], q[1], tol) and near(p[2], q[2], tol) for p, q in zip(got, want)), True)
    ann = [str(a['text']).strip() for a in M['annotations'] if a.get('text') and str(a['text']).strip()]
    have = fig_texts(ax)
    check(f'{lab}: the texts and annotations of the graph in the figure', [s for s in texts + ann if s not in have], [])
    for s in M['shapes']:
        if s['type'] == 'line' and s['x0'] == s['x1'] and s.get('xref') != 'paper':
            ok = any(close(ln['x'], [s['x0'], s['x0']], 1e-9, 1e-12) for ln in ax['lines'])
            check(f'{lab}: the vertical line at {s["x0"]:.6g}', ok, True)
        elif s['type'] == 'line' and s['y0'] == s['y1'] and s.get('yref') != 'paper':
            ok = any(close(ln['y'], [s['y0'], s['y0']], 1e-9, 1e-12) for ln in ax['lines'])
            check(f'{lab}: the horizontal line at {s["y0"]:.6g}', ok, True)
        elif s['type'] == 'circle':
            ok = any(p['type'] == 'ellipse' and close(p['center'], [(s['x0'] + s['x1']) / 2, (s['y0'] + s['y1']) / 2], 1e-9, 1e-12) and close([p['w'], p['h']], [s['x1'] - s['x0'], s['y1'] - s['y0']], 1e-9, 1e-12) for p in ax['patches'])
            check(f'{lab}: the circle', ok, True)
    shown = [t['name'] for t in M['traces'] if M['showlegend'] and t.get('showlegend') is not False and t['type'] in ('scatter', 'scattergl', 'bar') and (t.get('x') or []) and t.get('name')]
    check(f'{lab}: the legend', ax['legend'] or F['legend'], shown)


def check_heat(lab, g, M, F):
    """A heatmap (a colour map, two-way clustering): the cells, the names, the texts, the colour scale."""
    ax = F['axes'][0]
    t = M['traces'][0]
    z = [None if v is None else float(v) for row in t['z'] for v in row]
    im = ax['images'][0] if ax['images'] else {'shape': [], 'data': []}
    ok = im['shape'] == [len(t['z']), len(t['z'][0])] and len(im['data']) == len(z) and all(
        (a is None) == (b is None) and (a is None or near(a, b, 1e-12)) for a, b in zip(im['data'], z))
    check(f'{lab}: the cells are the page\'s, row by row', ok, True)
    check(f'{lab}: the title and the size', (ax['title'], F['size']), (g['label'], [g['w'] / 100, g['h'] / 100]))
    check(f'{lab}: the columns along the bottom', [s for s in ax['xticklabels'] if s], [str(s) for s in t['x']])
    ya = M['axes'].get('yaxis') or {}
    want_y = [str(s) for s in ya['ticktext']] if ya.get('ticktext') is not None else [str(s) for s in t['y']]
    check(f'{lab}: the rows down the side, the first at the top', ([s for s in ax['yticklabels'] if s], ax['yinverted']), (want_y, True))
    if t.get('texttemplate'):
        check(f'{lab}: the values written in the cells', [s['s'] for s in ax['texts']], [str(s) for row in t['text'] for s in row])
    else:
        check(f'{lab}: no values written in the cells (more than twelve columns)', ax['texts'], [])
    sc = ax['imscale'][0] if ax.get('imscale') else {}
    if t.get('colorscale'):
        cs = t['colorscale']
        mid = hexc(cs[len(cs) // 2][1])
        mid_ok = bool(sc.get('mid')) and all(abs(int(sc['mid'][k:k + 2], 16) - int(mid[k:k + 2], 16)) <= 3 for k in (1, 3, 5))   # (256 steps: the middle one a step off)
        check(f'{lab}: the page\'s colour scale', (sc.get('lo'), mid_ok, sc.get('hi')), (hexc(cs[0][1]), True, hexc(cs[-1][1])))
    if t.get('zmin') is not None:
        check(f'{lab}: its range', sc.get('clim'), [t['zmin'], t['zmax']])
    elif t.get('zmid') == 0:
        check(f'{lab}: centred at 0', close(sc.get('clim', [0, 1])[0], -sc.get('clim', [0, 1])[1], 1e-12, 1e-12) and sc['clim'][1] > 0, True)
    check(f'{lab}: a colour bar', len(F['axes']), 2)


def splom_cells(fmt_, p):
    if fmt_ == 'lower':
        return [(i, j, i - 1, j) for i in range(1, p) for j in range(i)]
    if fmt_ == 'upper':
        return [(i, j, i, j - 1) for i in range(p - 1) for j in range(i + 1, p)]
    return [(i, j, i, j) for i in range(p) for j in range(p)]


def check_splom(lab, g, M, F, fmt_, names, opts):
    """The scatterplot matrix: every cell's points, ellipse, fit line and
    correlation, the diagonal's names and histograms, each axis's range, the
    cells the format leaves out hidden."""
    p = len(names)
    cells = splom_cells(fmt_, p)
    G = p if fmt_ == 'square' else p - 1
    check(f'{lab}: a grid of {G} × {G} cells, the title and the size', (len(F['axes']), F['suptitle'], F['size']), (G * G, 'Scatterplot Matrix', [g['w'] / 100, g['h'] / 100]))
    if len(F['axes']) != G * G:
        return
    used = set()
    worst, bad_ranges, bad_titles, bad_text, bad_bars = [], [], [], [], []
    for k, (i, j, gi, gj) in enumerate(cells):
        a = k + 1
        xa, ya = ('x' if a == 1 else f'x{a}'), ('y' if a == 1 else f'y{a}')
        ax = F['axes'][gi * G + gj]
        used.add(gi * G + gj)
        X, Y = M['axes'][f'xaxis{"" if a == 1 else a}'], M['axes'][f'yaxis{"" if a == 1 else a}']
        if not (close(ax['xlim'], X['range'], 1e-9, 1e-12) and close(ax['ylim'], Y['range'], 1e-9, 1e-12)):
            bad_ranges.append((i, j))
        if (ax['xlabel'] or None) != (X['title'] or None) or (ax['ylabel'] or None) != (Y['title'] or None):
            bad_titles.append((i, j, ax['xlabel'], X['title'], ax['ylabel'], Y['title']))
        trs = [t for t in M['traces'] if (t.get('xaxis') or 'x') == xa and (t.get('yaxis') or 'y') == ya]
        anns = [str(an['text']) for an in M['annotations'] if an.get('xref') == f'{xa} domain']
        if sorted(fig_texts(ax)) != sorted(s.strip() for s in anns):
            bad_text.append((i, j, fig_texts(ax), anns))
        if i == j:
            for t in [t for t in trs if t['type'] == 'bar' and t.get('x')]:
                want = [(float(x_), float(h_), float(t['base']), float(t['width'])) for x_, h_ in zip(t['x'], t['y'])]
                got = [(b['x'] + b['w'] / 2, b['h'], b['y'], b['w']) for b in ax['bars']]
                if not (len(got) == len(want) and all(all(near(u, v, 1e-9) for u, v in zip(p_, q_)) for p_, q_ in zip(got, want))):
                    bad_bars.append((i, len(got), len(want)))
            continue
        for t in trs:
            mode = t.get('mode') or ''
            if 'markers' in mode and (t.get('x') or [None])[0] is not None:
                pts = [(float(x_), float(y_)) for x_, y_ in zip(t['x'], t['y'])]
                got = [tuple(q) for s in ax['scatter'] for q in s['xy']]
                worst.append(max((max(abs(u[0] - v[0]), abs(u[1] - v[1])) for u, v in zip(got, pts)), default=0.0) if len(got) == len(pts) else float('inf'))
            if mode == 'lines':
                pc = pieces(t['x'], t['y'])[0]
                hit = [ln for ln in ax['lines'] if same_piece(pieces(ln['x'], ln['y'])[0] if pieces(ln['x'], ln['y']) else [], pc, 1e-8)]
                worst.append(0.0 if hit and hexc(hit[0]['color']) == hexc(t['lcolor']) else float('inf'))
                if t.get('fill') == 'toself':
                    worst.append(0.0 if any(pp['type'] == 'Polygon' and len(pp['xy']) >= len(pc) for pp in ax['patches']) else float('inf'))
    check.near(f'{lab}: every cell\'s points, ellipse and fit line as the page draws them (in their colours)', max(worst, default=0.0), 0.0, 1e-8)
    check(f'{lab}: each cell\'s axes over the page\'s ranges', bad_ranges, [])
    check(f'{lab}: the columns named along the bottom and the left', bad_titles, [])
    check(f'{lab}: the diagonal\'s names{" and the correlations" if opts.get("corr") else ""}', bad_text, [])
    if opts.get('hist'):
        check(f'{lab}: the histograms on the diagonal, in the page\'s bins', bad_bars, [])
    check(f'{lab}: the cells the format leaves out are hidden', [k for k in range(G * G) if (k in used) != F['axes'][k].get('shown', True)], [])


def check_code_block(lab, g):
    check(f'{lab}: its code block is right under it, ending in plt.show()', bool(g.get('code')) and g['code'].rstrip().split('\n')[-1] == 'plt.show()', True)


async def graphs_of(page, js):
    """Open reports (js returns them in a list, and may change the table after
    taking their graphs), every graph drawn: their graphs, each with its layout."""
    return await page.ev(f'''(async () => {{
      const take = async (rep) => {{ __mvg.openAll(rep); const g = await __gr.graphs(rep); const m = __mvg.more(rep); return g.map((x, i) => ({{ ...x, more: m[i] }})); }};
      const out = await ({js})(take);
      return {{ ...out, undrawn: __gr.take() }};
    }})()''', timeout=600)


async def chart_code(page):
    await page.ev(GRAPHS_JS)
    await page.ev(MVG_JS)
    await page.ev('__gr.idle()')
    check('charts: the table for the graphs\' code', await page.ev(CHART_TABLE), 72)
    tbl = "__mvg.table('MV charts')"
    await page.ev("__mvg.table('MV charts').clearRowStates && __mvg.table('MV charts').clearRowStates()")
    names5 = ['a', 'b', 'c', 'dt', 'e']
    splom_all = {'spHist': True, 'spCorr': True, 'spFit': True, 'spShaded': True, 'spLevel': 0.9}
    cases = [
        ('Multivariate (every graph)', "(t) => __mvg.open('MV charts', 'multivariate', { y: " + json.dumps(names5) + " }, " + json.dumps({**splom_all, 'cmCorr': True, 'cmP': True, 'cmCluster': True, 'mahal': True, 'jack': True, 't2': True}) + ")",
         {'splom': ('square', names5, {'hist': True, 'corr': True})}),
        ('Multivariate (pairwise, Weight and Freq, lower triangular)', "(t) => __mvg.open('MV charts', 'multivariate', { y: ['a', 'b', 'c', 'e'], weight: ['w'], freq: ['f'] }, { method: 'pairwise', matrixFormat: 'lower', cmCorr: true, cmP: true, mahal: true })",
         {'splom': ('lower', ['a', 'b', 'c', 'e'], {})}),
        ('Principal Components (on correlations, Prin2 by Prin3, varimax)', "(t) => __mvg.open('MV charts', 'pca', { y: " + json.dumps(names5) + " }, { scree: true, score: true, loadplot: true, biplot: true, ellipse: true, pcx: 1, pcy: 2, rotation: { k: 2, method: 'varimax', kaiser: true } })", {}),
        ('Principal Components (on covariances, Freq, promax of 3)', "(t) => __mvg.open('MV charts', 'pca', { y: ['a', 'b', 'c', 'e'], freq: ['f'] }, { on: 'covariances', scree: true, biplot: true, rotation: { k: 3, method: 'promax', kaiser: true } })", {}),
        ('Principal Components (unscaled, Weight)', "(t) => __mvg.open('MV charts', 'pca', { y: ['a', 'b', 'c', 'e'], weight: ['w'] }, { on: 'unscaled', loadplot: true })", {}),
        ('Factor Analysis (two fits)', "(t) => __mvg.open('MV charts', 'factor', { y: ['a', 'b', 'c', 'd', 'e'] }, { fits: [{ method: 'ml', prior: 'smc', k: 2, rotation: 'varimax', kaiser: true }, { method: 'pa', prior: 'smc', k: 3, rotation: 'promax', kaiser: true, id: 1 }], 'fa0|scoreplot': true, 'fa1|scoreplot': true, 'fa1|fx': 2, 'fa1|fy': 0 })", {}),
        ('Discriminant (three groups, the 50% contours)', "(t) => __mvg.open('MV charts', 'discriminant', { y: ['a', 'c', 'd', 'e'], x: ['grp'] }, { cp50: true })", {}),
        ('Discriminant (quadratic, Freq, proportional priors)', "(t) => __mvg.open('MV charts', 'discriminant', { y: ['a', 'c', 'd'], x: ['grp'], freq: ['f'] }, { method: 'quadratic', priors: 'proportional' })", {}),
        ('Discriminant (two groups, priors given)', "(t) => __mvg.open('MV charts', 'discriminant', { y: ['a', 'c', 'd'], x: ['yb'] }, { priors: 'other', priorValues: { no: 1, yes: 2 } })", {}),
        ('Hierarchical Cluster (4 clusters chosen, coloured, two-way, criterion)', "(t) => __mvg.open('MV charts', 'hcluster', { y: ['u', 'v', 'a'] }, { method: 'ward', standardize: 'none', criterion: true, twoWay: true, colorClusters: true, ncluster: 4 })", {}),
        ('Hierarchical Cluster (average, the default number)', "(t) => __mvg.open('MV charts', 'hcluster', { y: ['u', 'v'] }, { method: 'average', twoWay: true })", {}),
        ('K Means (2 to 4 clusters, every graph)', "(t) => __mvg.open('MV charts', 'kmeans', { y: ['u', 'v', 'a'] }, { k: 2, kRange: 4, scaled: false, 'k2|pcp': true, 'k3|pcp': true, 'k3|splom': true, 'k3|rays': false, 'k4|splom': true })",
         {'splom': ('lower', ['u', 'v', 'a'], {'points_only': True})}),
        ('K Means (3 clusters, scaled, Weight)', "(t) => __mvg.open('MV charts', 'kmeans', { y: ['u', 'v'], weight: ['w'] }, { k: 3, 'k3|pcp': true, 'k3|splom': true })",
         {'splom': ('lower', ['u', 'v'], {'points_only': True})}),
        ('Response Screening (every graph)', "(t) => __mvg.open('MV charts', 'respscreen', { y: ['a', 'b', 'grp', 'yb', 'q3'], x: ['c', 'grp', 'd', 'q3'] }, { lwR2: true })", {}),
        ('Response Screening (Freq)', "(t) => __mvg.open('MV charts', 'respscreen', { y: ['a', 'yb'], x: ['c', 'q1'], freq: ['f'] }, { lwR2: true })", {}),
        ('Explore Outliers', "(t) => __mvg.open('MV charts', 'outliers', { y: ['a', 'c', 'd'] }, { mro: true, knn: true, knnK: 5, qro: true })", {}),
        ('Multiple Correspondence Analysis (c3 by c2, the rows)', "(t) => __mvg.open('MV charts', 'mca', { y: ['grp', 'q1', 'q2', 'q3'] }, { rowplot: true, dx: 2, dy: 1 })", {}),
        ('Multiple Correspondence Analysis (Freq)', "(t) => __mvg.open('MV charts', 'mca', { y: ['grp', 'q1'], freq: ['f'] }, { rowplot: true })", {}),
        ('Multidimensional Scaling (the rows named)', "(t) => __mvg.open('MV charts', 'mds', { y: ['a', 'c', 'd', 'e'] }, {})", {}),
        ('Multidimensional Scaling (in their units)', "(t) => __mvg.open('MV charts', 'mds', { y: ['u', 'v'] }, { standardize: false })", {}),
    ]
    total = 0
    for name, opener, spec in cases:
        r = await graphs_of(page, f'''async (take) => {{ const rep = await ({opener})(); const g = await take(rep); const errors = __mvg.errors(rep);
          const script = rep.pythonScript(); const inScript = g.map((x) => !!x.code && script.includes(x.code));
          await __mvg.table('MV charts').clearRowStates(); SM.app.closeReport(rep); return {{ g, errors, inScript }}; }}''')
        if not isinstance(r, dict):
            check(f'charts, {name}: the report opens', r, 'a report')
            continue
        check(f'charts, {name}: no errors, every graph drawn', (r['errors'], r['undrawn']), ([], []))
        check(f'charts, {name}: every graph\'s code in Save Python Script', all(r['inScript']), True)
        for k, g in enumerate(r['g']):
            lab = f'{name}: {g["label"]} ({k + 1})'
            check_code_block(lab, g)
            if not g.get('code'):
                continue
            F, err = await run_mv(page, g['code'], tbl)
            check(f'{lab}: the code runs in the page', err, None)
            if not F:
                continue
            total += 1
            F, M = F[0], g['more']
            label = g['label']
            if label == 'Scatterplot Matrix':
                fmt_, cols_, opts_ = spec['splom']
                check_splom(lab, g, M, F, fmt_, cols_, opts_)
            elif label in ('Color Map On Correlations', 'Color Map On p-values', 'Cluster the Correlations', 'Two way clustering'):
                check_heat(lab, g, M, F)
            elif label.startswith('Parallel coordinates'):
                cats = [v for v in dict.fromkeys(v for t in M['traces'] for v in (t.get('x') or []) if isinstance(v, str))]
                check_plot(lab, g, M, F, xcats=cats)
                check(f'{lab}: the columns along the axis', [s for s in F['axes'][0]['xticklabels'] if s], cats)
            else:
                check_plot(lab, g, M, F)
    check('charts: the graphs checked', total >= 60, True)

    # ---- By, with rows excluded: each group's graphs keep the group's rows and leave out the excluded ones
    r = await graphs_of(page, '''async (take) => {
      const t = __mvg.table('MV charts'); const hi = []; for (let i = 0; i < t.nrows; i++) if (t.col('grp').values[i] === 'hi') hi.push(i);
      const ex = [hi[0], hi[2], 5, 9].filter((v, i, a) => a.indexOf(v) === i);
      t.setState(ex, 'excluded', true);
      const rep = await __mvg.open('MV charts', 'multivariate', { y: ['a', 'c', 'dt'], by: ['grp'] }, { matrixFormat: 'upper', mahal: true, cmCorr: true });
      const rep2 = await __mvg.open('MV charts', 'kmeans', { y: ['u', 'v'], by: ['grp'] }, { k: 2, 'k2|splom': true });
      const rep3 = await __mvg.open('MV charts', 'hcluster', { y: ['u', 'v'], by: ['grp'] }, {});
      const g = [...await take(rep), ...await take(rep2), ...await take(rep3)];
      const errors = [rep, rep2, rep3].flatMap((x) => __mvg.errors(x));
      const groups = [rep, rep2, rep3].map((x) => x.groups().map((q) => ({ label: q.label, rows: q.rows, where: q.where })));
      t.setState(ex, 'excluded', false);
      for (const x of [rep, rep2, rep3]) SM.app.closeReport(x);
      return { g, errors, groups, ex, hi };
    }''')
    check('charts, By with excluded rows: no errors, every graph drawn', (r['errors'], r['undrawn']), ([], []))
    labels = [g['label'] for g in r['g']]
    check('charts, By: each group\'s graphs', (labels.count('Scatterplot Matrix'), labels.count('Mahalanobis Distances'), labels.count('Color Map On Correlations'), labels.count('Biplot, 2 clusters'), labels.count('Dendrogram')),
          (6, 3, 3, 3, 3))
    groups = r['groups'][0]
    where_lines = {q['label']: f'df = df[df["grp"] == {json.dumps(q["where"][0]["value"])}]   # only the rows where grp is {q["where"][0]["value"]}' for q in groups}
    hi_drop = sorted(set(r['hi']) & set(r['ex']))
    drop_hi = f'df = df.drop(index={json.dumps(hi_drop)})   # the rows the report leaves out'
    for g in r['g']:
        check_code_block(f'By: {g["label"]}', g)
    for k, g in enumerate(r['g']):
        code = g.get('code') or ''
        grp = next((lab_ for lab_, line in where_lines.items() if line in code), None)
        lab = f'By: {g["label"]} ({grp})'
        check(f'{lab}: the code keeps its group', grp is not None, True)
        if grp == 'grp=hi':
            check(f'{lab}: ... and leaves out the group\'s excluded rows', drop_hi in code, True)
        if not code:
            continue
        F, err = await run_mv(page, code, tbl)
        check(f'{lab}: the code runs in the page', err, None)
        if not F:
            continue
        F, M = F[0], g['more']
        if g['label'] == 'Scatterplot Matrix':
            cols_ = ['a', 'c', 'dt'] if len(F['axes']) == 4 else ['u', 'v']
            check_splom(lab, g, M, F, 'upper' if cols_[0] == 'a' else 'lower', cols_, {})
        elif g['label'] == 'Color Map On Correlations':
            check_heat(lab, g, M, F)
        else:
            check_plot(lab, g, M, F)
    check('charts, By: a date column\'s code turns it back into the page\'s number', all('df["dt"] = (pd.to_datetime(df["dt"]) - pd.Timestamp(0)) / pd.Timedelta(milliseconds=1)' in g['code'] for g in r['g'] if g['label'] in ('Scatterplot Matrix', 'Mahalanobis Distances', 'Color Map On Correlations') and '"dt"' in g['code']), True)
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'Multivariate test')))")


# ---- the statistics' code of five reports, run in the page ---------------------------------------------------------
# Discriminant, K Means, Response Screening, Factor Analysis and Hierarchical
# Cluster: each report's own code (its Save Python Script part) runs in the
# page's Python on the table's CSV, and gives the numbers the report shows (to
# the digits it shows them), its clusters those of Save Clusters.
STATS_JS = r'''
window.__mvs = {
  // the report's code that holds this text, from what Save Python Script collects
  code(rep, marker) { return rep.pyCode.find((c) => c.includes(marker)) || null; },
  // a report table under an outline (its title, or the start of it), as cell texts
  table(rep, title, n = 0) {
    const h = [...rep.body.querySelectorAll('.sm-ob-head')].find((x) => { const t = x.querySelector('h2, h3, h4').textContent; return t === title || t.startsWith(title); });
    if (!h) return null;
    const t = h.parentElement.querySelector(':scope > .sm-ob-body').querySelectorAll('table.sm-rt, table.sm-kv')[n];
    return t ? this.cells(t) : null;
  },
  cells(t) { return [...t.querySelectorAll('tr')].map((tr) => [...tr.children].map((c) => c.textContent.trim())); },
  // a report table by its caption
  captioned(rep, caption) { const t = [...rep.body.querySelectorAll('table.sm-rt')].find((x) => x.caption && x.caption.textContent.trim() === caption); return t ? this.cells(t) : null; },
};
'''


def page_num(s):
    """A number as the page shows it: − for minus, <.0001 as 0.0001."""
    s = str(s).strip().replace('−', '-').replace('*', '')
    if s.startswith('<'):
        return float(s[1:])
    return float(s)


def shown(got, text, digits=None):
    """A number as the report shows it: to its digits (fixed), or to seven significant ones."""
    if text in ('.', '', None):
        return got is None or got != got
    want = page_num(text)
    if str(text).strip().startswith('<'):
        return got < want
    if digits is not None:
        return abs(got - want) <= 0.5 * 10 ** -digits + 1e-12
    return abs(got - want) <= 5e-7 * max(1.0, abs(want))


async def run_stats(page, code, probe, table_js):
    """A report's code run in the page's Python, then probe (a Python expression) printed as JSON."""
    src = code + '\nimport json as _json\nprint("MV-STATS " + _json.dumps(' + probe + ', default=lambda o: o.tolist() if hasattr(o, "tolist") else float(o)))\n'
    out = await page.ev(f'__gr.run({json.dumps(src)}, {table_js})', timeout=300)
    if isinstance(out, str):
        return None, out
    text = ''.join(o.get('text', '') for o in out.get('outputs') or [] if o.get('type') == 'stream' and o.get('name') == 'stdout')
    errs = [f"{o.get('ename')}: {o.get('evalue')}" for o in out.get('outputs') or [] if o.get('type') == 'error']
    for line in text.split('\n'):
        if line.startswith('MV-STATS '):
            return json.loads(line[len('MV-STATS '):]), None
    return None, errs[0] if errs else 'the probe printed nothing'


async def stats_code(page):
    await page.ev(STATS_JS)
    tbl = "__mvg.table('MV charts')"
    ex = [5, 17, 30]
    await page.ev(f"__mvg.table('MV charts').setState({json.dumps(ex)}, 'excluded', true)")
    # ---- Discriminant (quadratic, proportional priors, Weight and Freq): the Score Summaries and the confusion matrix
    r = await page.ev('''(async () => { const rep = await __mvg.open('MV charts', 'discriminant', { y: ['a', 'c', 'd'], x: ['grp'], weight: ['w'], freq: ['f'] }, { method: 'quadratic', priors: 'proportional' });
      const out = { code: __mvs.code(rep, 'tests = MANOVA('), summary: __mvs.table(rep, 'Score Summaries', 0), conf: __mvs.table(rep, 'Score Summaries', 1), errors: __mvg.errors(rep) }; SM.app.closeReport(rep); return out; })()''')
    check('Discriminant\'s code: the report\'s, without errors', (bool(r['code']), r['errors']), (True, []))
    got, err = await run_stats(page, r['code'], '{"mis": float(w[mis].sum()), "pct": float(100 * w[mis].sum() / w.sum()), "er2": float(1 - ll / ll0), "m2ll": float(-2 * ll), "conf": conf, "labels": labels}', tbl)
    check('Discriminant\'s code runs in the page', err, None)
    if got:
        row = r['summary'][1]
        check('Discriminant\'s code: the Score Summaries as the report shows them (misclassified, percent, entropy RSquare, −2LogLikelihood)',
              (shown(got['mis'], row[1]), shown(got['pct'], row[2], 4), shown(got['er2'], row[3], 4), shown(got['m2ll'], row[4], 5)), (True, True, True, True))
        conf = r['conf']
        check('Discriminant\'s code: the confusion matrix, in the table\'s order of the categories', ([c[0] for c in conf[1:]], all(shown(v, t, 0) for vr, tr in zip(got['conf'], conf[1:]) for v, t in zip(vr, tr[1:]))), (got['labels'], True))
    # ---- K Means (2 to 4 clusters, Weight): the Cluster Comparison and each fit's clusters
    r = await page.ev('''(async () => { const rep = await __mvg.open('MV charts', 'kmeans', { y: ['u', 'v', 'a'], weight: ['w'] }, { k: 2, kRange: 4, restarts: 5, seed: 99 });
      __mvg.openAll(rep);
      const sizes = [2, 3, 4].map((k) => { const h = [...rep.body.querySelectorAll('.sm-ob-head h3')].find((x) => x.textContent === `K Means NCluster=${k}`); const t = h.closest('.sm-ob').querySelector('table.sm-rt'); return [...t.querySelectorAll('tbody tr')].map((tr) => tr.children[1].textContent); });
      const out = { code: __mvs.code(rep, 'comparison, fits = [], {}'), comparison: __mvs.table(rep, 'Cluster Comparison'), sizes, errors: __mvg.errors(rep) }; SM.app.closeReport(rep); return out; })()''')
    check('K Means\' code: the report\'s own seeded k-means with its restarts, without errors', (bool(r['code']) and 'default_rng(99)' in r['code'] and 'for _ in range(5):' in r['code'] and 'kmeans2' not in r['code'], r['errors']), (True, []))
    got, err = await run_stats(page, r['code'], '{"comparison": [{k: (None if v != v else v) for k, v in c.items()} for c in comparison], "counts": {str(k): [float(w[lab == c].sum()) for c in range(k)] for k, lab in fits.items()}}', tbl)
    check('K Means\' code runs in the page', err, None)
    if got:
        head, rows = r['comparison'][0], r['comparison'][1:]
        col = {h: i for i, h in enumerate(head)}
        ok = len(rows) == len(got['comparison']) and all(
            int(tr[col['NCluster']]) == c['NCluster'] and shown(c['CCC'], tr[col['CCC']], 4) and shown(c['Pseudo F'], tr[col['Pseudo F']], 5)
            and shown(c['RSquare'], tr[col['RSquare']], 4) and shown(c['Within SS'], tr[col['Within SS']], 6) for tr, c in zip(rows, got['comparison']))
        check('K Means\' code: the Cluster Comparison as the report shows it (CCC, pseudo F, RSquare, within SS)', ok, True)
        check('K Means\' code: each fit\'s cluster sizes (Weight summed)', [[shown(v, t) for v, t in zip(got['counts'][str(k)], r['sizes'][i])] for i, k in enumerate((2, 3, 4))],
              [[True] * k for k in (2, 3, 4)])
    # ---- Response Screening (Weight and Freq): the PValues table
    r = await page.ev('''(async () => { const rep = await __mvg.open('MV charts', 'respscreen', { y: ['a', 'b', 'grp', 'yb'], x: ['c', 'q1', 'd'], weight: ['w'], freq: ['f'] }, {});
      const out = { code: __mvs.code(rep, 'print(res.sort_values("FDR_LogWorth"'), table: __mvs.table(rep, 'PValues'), errors: __mvg.errors(rep) }; SM.app.closeReport(rep); return out; })()''')
    check('Response Screening\'s code: Weight and Freq as frequency weights, without errors', (bool(r['code']) and 'frequency weights: Weight times Freq' in r['code'], r['errors']), (True, []))
    got, err = await run_stats(page, r['code'], '[{"y": a, "x": b, "p": None if p_ != p_ else p_, "fdr": None if q_ != q_ else q_, "lw": None if l_ != l_ else l_, "e": None if e_ != e_ else e_, "n": c_} for a, b, p_, q_, l_, e_, c_ in zip(res["Y"], res["X"], res["PValue"], res["FDR_PValue"], res["FDR_LogWorth"], res["Effect_Size"], res["Count"])]', tbl)
    check('Response Screening\'s code runs in the page', err, None)
    if got:
        head, rows = r['table'][0], r['table'][1:]
        col = {h: i for i, h in enumerate(head)}
        by = {(x['y'], x['x']): x for x in got}
        ok = len(rows) == len(got) and all(
            (tr[col['Y']], tr[col['X']]) in by and shown(by[(tr[col['Y']], tr[col['X']])]['p'], tr[col['PValue']], 4) and shown(by[(tr[col['Y']], tr[col['X']])]['fdr'], tr[col['FDR PValue']], 4)
            and shown(by[(tr[col['Y']], tr[col['X']])]['lw'], tr[col['FDR LogWorth']], 4) and shown(by[(tr[col['Y']], tr[col['X']])]['e'], tr[col['Effect Size']], 4)
            and shown(by[(tr[col['Y']], tr[col['X']])]['n'], tr[col['Count']]) for tr in rows)
        check('Response Screening\'s code: every test as the PValues table shows it (p, FDR p, FDR LogWorth, effect size, count)', ok, True)
    # ---- Factor Analysis (ML, promax with Kaiser's normalization, Freq): the communalities and the rotated loadings
    r = await page.ev('''(async () => { const rep = await __mvg.open('MV charts', 'factor', { y: ['a', 'b', 'c', 'd', 'e'], freq: ['f'] }, { fits: [{ method: 'ml', prior: 'smc', k: 2, rotation: 'promax', kaiser: true }] });
      const out = { code: __mvs.code(rep, "coef = np.asarray(res.factor_score_params(method=\\"regression\\"))   # Thurstone's regression scores (Save Rotated Components)"),
        comm: __mvs.captioned(rep, 'Final Communality Estimates'), load: __mvs.captioned(rep, 'Rotated Factor Loading'),
        errors: __mvg.errors(rep) }; SM.app.closeReport(rep); return out; })()''')
    check('Factor Analysis\' code: the report\'s rotation with Kaiser\'s normalization, without errors', (bool(r['code']) and "Kaiser's normalization" in r['code'] and 'promax' in r['code'], r['errors']), (True, []))
    got, err = await run_stats(page, r['code'], '{"names": names, "comm": comm, "L": L}', tbl)
    check('Factor Analysis\' code runs in the page', err, None)
    if got and r['load']:
        comm = {row[0]: row[1] for row in (r['comm'] or [])[1:]}
        check('Factor Analysis\' code: the Final Communality Estimates as the report shows them', all(shown(v, comm.get(nm), 4) for nm, v in zip(got['names'], got['comm'])), True)
        load = {row[0]: row[1:] for row in r['load'][1:]}
        check('Factor Analysis\' code: the rotated factor loadings', all(shown(v, t, 4) for nm, lr in zip(got['names'], got['L']) for v, t in zip(lr, load.get(nm, []))) and len(load) == 5, True)
    # ---- Hierarchical Cluster: the clusters at the number chosen, and at the page's default
    for opts, what in (({'ncluster': 5}, 'the number of clusters chosen (5)'), ({}, 'the page\'s default number of clusters')):
        r = await page.ev(f'''(async () => {{ const rep = await __mvg.open('MV charts', 'hcluster', {{ y: ['u', 'v', 'a'] }}, {json.dumps({'method': 'average', **opts})});
          const legend = [...rep.body.querySelectorAll('.mv-legend button')].map((b) => b.textContent);
          const t = rep.table; const before = t.columns.length; const ctx = new SM.report.Ctx(rep, {{ rows: rep.groups()[0].rows, where: [] }}, rep.content, '');
          await rep.platform.triangle(ctx).find((i) => i.label === 'Save Clusters').action();
          const c = t.columns[t.columns.length - 1]; const saved = t.columns.length > before ? c.values.slice() : null; if (saved) t.removeColumn(c.id);
          const out = {{ code: __mvs.code(rep, 'cluster = np.array([number[root[i]] + 1 for i in range(n)])'), legend, saved, errors: __mvg.errors(rep) }}; SM.app.closeReport(rep); return out; }})()''')
        check(f'Hierarchical Cluster\'s code ({what}): the report\'s, without errors', (bool(r['code']), r['errors']), (True, []))
        got, err = await run_stats(page, r['code'], '{"k": int(k), "rows": X.index.tolist(), "cluster": cluster}', tbl)
        check(f'Hierarchical Cluster\'s code ({what}) runs in the page', err, None)
        if got:
            check(f'Hierarchical Cluster\'s code ({what}): the report\'s number of clusters', got['k'], len(r['legend']))
            sizes = [sum(1 for c in got['cluster'] if c == j + 1) for j in range(got['k'])]
            check(f'Hierarchical Cluster\'s code ({what}): the clusters\' sizes as the legend shows them', [f'{j + 1}: {s}' for j, s in enumerate(sizes)], r['legend'])
            saved = r['saved'] or []
            check(f'Hierarchical Cluster\'s code ({what}): each row\'s cluster is Save Clusters\'', [saved[i] if i < len(saved) else None for i in got['rows']], got['cluster'])
            check(f'Hierarchical Cluster\'s code ({what}): it leaves out the excluded rows', ('df = df.drop(index=[5, 17, 30])   # the rows the report leaves out' in r['code'], any(i in ex for i in got['rows'])), (True, False))
    await page.ev(f"__mvg.table('MV charts').setState({json.dumps(ex)}, 'excluded', false)")


async def main():
    page = await open_page(f'{BASE}/smui.html')
    st = await wait_engine(page)
    check('engine ready', st, 'ready')
    failed = await page.ev('SM.engine.failed.filter(f => f.module === "multivariate").map(f => f.error)')
    check('the multivariate module imports in Pyodide', failed, [])
    names = await page.ev('SM.engine.names.filter(n => /^(multivariate|pca|factor|discriminant|hcluster|kmeans|respscreen|outliers|mca|mds)\\./.test(n)).length')
    check('the 22 backend names are there', names, 22)
    check('no script errors at load', page.errors, [])
    menus = await page.ev('''(() => {
      const sub = (path) => { const top = SM.app.menuItems('Analyze'); const m = top.find(i => i.label === path); if (!m) return null; return (typeof m.submenu === 'function' ? m.submenu() : m.submenu).filter(i => i.label).map(i => i.label); };
      return { mv: sub('Multivariate Methods'), cl: sub('Clustering'), sc: sub('Screening') };
    })()''')
    mine = ('Multivariate…', 'Principal Components…', 'Discriminant…', 'Multiple Correspondence Analysis…', 'Factor Analysis…', 'Multidimensional Scaling…')
    check('Multivariate Methods menu', [x for x in menus['mv'] if x in mine], list(mine))
    check('Clustering menu', [x for x in menus['cl'] if x in ('Hierarchical Cluster…', 'K Means Cluster…')], ['Hierarchical Cluster…', 'K Means Cluster…'])
    check('Screening menu', [x for x in menus['sc'] if x in ('Response Screening…', 'Explore Outliers…')], ['Response Screening…', 'Explore Outliers…'])
    check('the example table', await page.ev(MAKE), 150)

    # ---- Multivariate: every option ------------------------------------------------------
    opts = {'corrProb': True, 'ci': True, 'inverse': True, 'partial': True, 'partialP': True, 'cov': True, 'pairwise': True, 'simpleUni': True, 'simpleMulti': True,
            'np:spearman': True, 'np:kendall': True, 'np:hoeffding': True, 'cmCorr': True, 'cmP': True, 'cmCluster': True, 'mahal': True, 'jack': True, 't2': True,
            'alpha:raw': True, 'alpha:std': True, 'spCorr': True, 'spHist': True, 'cmCells': True, 'dcor': True}
    r = await page.ev(open_report_js('multivariate', {'y': ['a', 'b', 'c', 'd', 'e']}, opts), timeout=240)
    check('Multivariate: no errors', r['errors'], [])
    want = ['Correlations', 'Correlation Probability', 'CI of Correlation', 'Inverse Corr', 'Partial Corr', 'Covariance Matrix', 'Pairwise Correlations', 'Simple Statistics',
            "Nonparametric: Spearman's ρ", "Nonparametric: Kendall's τ", "Nonparametric: Hoeffding's D", 'Scatterplot Matrix', 'Color Map On Correlations', 'Color Map On p-values',
            'Cluster the Correlations', 'Mahalanobis Distances', 'Jackknife Distances', 'T²', "Cronbach's α", 'Standardized α', 'Distance Correlations']
    check('Multivariate: the outlines of every option', [o for o in want if o not in r['outlines']], [])
    corr = await page.ev(table_under_js('Correlations'))
    js = await page.ev('''(() => {
      const t = SM.app.current; const a = t.col('a').values, d = t.col('d').values, b = t.col('b').values;
      const ok = a.map((_, i) => [a, b, t.col('c').values, d, t.col('e').values].every(v => Number.isFinite(v[i])));
      const x = a.filter((_, i) => ok[i]), y = d.filter((_, i) => ok[i]);
      const mx = x.reduce((s, v) => s + v, 0) / x.length, my = y.reduce((s, v) => s + v, 0) / y.length;
      let sxy = 0, sxx = 0, syy = 0; for (let i = 0; i < x.length; i++) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) ** 2; syy += (y[i] - my) ** 2; }
      return SM.util.fmt(sxy / Math.sqrt(sxx * syy), { digits: 4 });
    })()''')
    check('Multivariate: r(a, d) as computed in the page, row-wise', corr[1][4], js)
    check('Multivariate: row-wise uses 149 rows', 'Variance estimation: Row-wise. 149 observations; 1 row with a missing value left out.' in await page.ev(f'{LAST}.content.textContent'), True)
    # Distance Correlations: dCor of a and d by the doubly centred distances, computed in the page
    js = await page.ev('''(() => {
      const t = SM.app.current; const x = t.col('a').values, y = t.col('d').values; const n = x.length;
      const centred = (v) => { const D = v.map((p) => v.map((q) => Math.abs(p - q))); const rm = D.map((r) => r.reduce((s, z) => s + z, 0) / n); const gm = rm.reduce((s, z) => s + z, 0) / n;
        return D.map((r, i) => r.map((z, j) => z - rm[i] - rm[j] + gm)); };
      const A = centred(x), B = centred(y); let ab = 0, aa = 0, bb = 0;
      for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) { ab += A[i][j] * B[i][j]; aa += A[i][j] ** 2; bb += B[i][j] ** 2; }
      return Math.sqrt(ab / Math.sqrt(aa * bb));
    })()''')
    dm = await page.ev(table_under_js('Distance Correlations'))
    dp = await page.ev(table_under_js('Distance Correlations', 1))
    row_ad = [x for x in dp[1:] if x[0] == 'd' and x[1] == 'a'][0]
    check.near('Distance Correlations: dCor(a, d) as computed in the page', float(row_ad[2]), js, 2e-4)
    check('the dCor matrix holds it', dm[1][4], row_ad[2])
    check('the pairwise table: ten pairs, a p-value and where it comes from', (len(dp) - 1, dp[0][5:8]), (10, ['n·dCov²', 'Prob>n·dCov²', 'p-Value from']))
    check('150 rows: permutation p-values (or statsmodels\' asymptotic fallback)', all(x[7].startswith(('permutation (B = 233)', 'asymptotic: no permutation of 233')) for x in dp[1:]), True)
    dcells = await page.ev(f'''(() => {{ const h = [...{LAST}.content.querySelectorAll('.sm-ob-head')].find(h => h.textContent.trim() === 'Distance Correlations'); return h.parentElement.querySelectorAll('td.mv-cm').length; }})()''')
    check('the dCor matrix is colour mapped', dcells, 25)
    cells = await page.ev(f'[...{LAST}.content.querySelectorAll("td.mv-cm")].length')
    check('Multivariate: coloured correlation cells', cells >= 25, True)
    bars = await page.ev(f'[...{LAST}.content.querySelectorAll(".mv-bar")].length')
    check('Multivariate: bars in the pairwise and nonparametric tables', bars >= 40, True)
    # scatterplot matrix: selecting in one cell selects rows and lights the other cells
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const t = rep.table;
      const p = rep.plots.find(p => p.opts.title === 'Scatterplot Matrix');
      await p.draw();
      const i = p.kinds.findIndex(k => k === 'points');
      p._selected({{ points: [0, 1, 2, 3].map(k => ({{ curveNumber: i, pointNumber: k }})) }});
      await new Promise(r => setTimeout(r, 300));
      const sel = t.selectedRows();
      const other = p.kinds.findIndex((k, j) => k === 'points' && j > i);
      const lit = p.box.data[other].selectedpoints;
      t.select([]);
      return {{ n: sel.length, want: p.rows[i].slice(0, 4), sel, lit: lit ? lit.length : 0, hist: p.kinds.filter(k => k === 'bars').length }};
    }})()''')
    check('scatterplot matrix: a drag selects the rows', r['sel'], sorted(r['want']))
    check('scatterplot matrix: the other cells highlight them', r['lit'], 4)
    check('scatterplot matrix: linked histograms on the diagonal', r['hist'], 5)
    # an outlier plot: a click selects the row; save the distances
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const t = rep.table;
      const p = rep.plots.find(p => p.opts.title === 'Mahalanobis Distances');
      await p.draw();
      p._click({{ points: [{{ curveNumber: 0, pointNumber: 10 }}], event: {{}} }});
      const sel = t.selectedRows();
      t.select([]);
      return {{ sel, want: p.rows[0][10] }};
    }})()''')
    check('outlier plot: a click selects its row', r['sel'], [r['want']])
    r = await run_menu(page, 'Save', 'Mahalanobis Distances')
    saved = await page.ev('''(() => { const t = SM.app.current; const c = t.columns[t.columns.length - 1]; return { name: c.name, n: c.values.filter(Number.isFinite).length, miss: Number.isNaN(c.values[7]) }; })()''')
    check('Save Mahalanobis distances: a column for the complete rows', (r, saved['name'], saved['n'], saved['miss']), ('ok', 'Mahal. Distances', 149, True))
    await page.ev('(() => { const t = SM.app.current; t.removeColumn(t.columns[t.columns.length - 1].id); })()')
    await asyncio.sleep(0.5)
    await shot(page, 'mv-01-multivariate.png')
    # the Principal Components item opens the PCA platform on the same columns
    n_rep = await page.ev('SM.app.reports.length')
    await run_menu(page, 'Principal Components')
    await page.ev(f'Promise.race([new Promise(res => {LAST}.on("done", res)), new Promise(res => setTimeout(res, 4000))])')
    r = await page.ev(f'({{ n: SM.app.reports.length, id: {LAST}.platform.id, title: {LAST}.title }})')
    check('Principal Components from Multivariate', (r['n'], r['id'], r['title']), (n_rep + 1, 'pca', 'Principal Components: on Correlations'))
    await page.ev(f'SM.app.closeReport({LAST})')

    # ---- By ----------------------------------------------------------------------------------
    r = await page.ev(open_report_js('multivariate', {'y': ['a', 'c', 'e'], 'by': ['grp']}, {'mahal': True}), timeout=240)
    check('By: one Multivariate per level', [o for o in r['outlines'] if o.startswith('Multivariate ')], ['Multivariate grp=hi', 'Multivariate grp=lo', 'Multivariate grp=mid'])
    check('By: no errors', r['errors'], [])

    # ---- Principal Components ------------------------------------------------------------------
    r = await page.ev(open_report_js('pca', {'y': ['a', 'b', 'c', 'd', 'e']}, {'bartlett': True, 'eigvec': True, 'loadmat': True, 'fmtload': True, 'corrmat': True, 'covmat': True, 'scree': True, 'score': True, 'loadplot': True, 'biplot': True, 'ellipse': True, 'rotation': {'k': 2, 'method': 'varimax', 'kaiser': True}}), timeout=240)
    check('PCA: no errors', r['errors'], [])
    check('PCA: outlines', [o for o in ['Summary Plots', 'Eigenvalues', 'Eigenvectors', 'Loading Matrix', 'Formatted Loading Matrix', 'Correlations', 'Scree Plot', 'Score Plot', 'Loading Plot', 'Biplot', 'Rotated Components: Varimax'] if o not in r['outlines']], [])
    ev = await page.ev(table_under_js('Eigenvalues'))
    check('PCA: the eigenvalues sum to 5', round(sum(float(x[1].replace('−', '-')) for x in ev[1:]), 3), 5.0)
    check('PCA: Bartlett df 14, 9, 5, 2', [x[6] for x in ev[1:]], ['14', '9', '5', '2', '.'])
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const t = rep.table;
      const p = rep.plots.find(p => p.opts.title === 'Score Plot');
      await p.draw();
      t.select([0, 1, 2]);
      await new Promise(r => setTimeout(r, 200));
      const sp = p.box.data[0].selectedpoints; t.select([]);
      return sp.length;
    }})()''')
    check('PCA: a table selection shows in the score plot', r, 3)
    await page.ev(f'''(async () => {{
      const rep = {LAST}; const ctx = {CTX};
      const items = rep.platform.triangle(ctx); const save = items.find(i => i.label === 'Save Columns').submenu().find(i => i.label === 'Save Principal Components…');
      save.action(); await new Promise(r => setTimeout(r, 400));
      const dlg = [...document.querySelectorAll('.sm-dialog')].pop(); dlg.querySelector('input').value = '2';
      [...dlg.querySelectorAll('.sm-btn')].find(b => b.textContent === 'OK').click();
      await new Promise(r => setTimeout(r, 400));
    }})()''')
    r = await page.ev('''(() => { const t = SM.app.current; const cols = t.columns.slice(-2); const v = cols[0].values.filter(Number.isFinite); const m = v.reduce((a, b) => a + b, 0) / v.length;
      const s2 = v.reduce((a, b) => a + (b - m) ** 2, 0) / (v.length - 1); const out = { names: cols.map(c => c.name), mean: Math.abs(m) < 1e-9, var: s2 }; cols.forEach(c => t.removeColumn(c.id)); return out; })()''')
    check('PCA: Save Principal Components writes Prin1, Prin2', r['names'], ['Prin1', 'Prin2'])
    check('PCA: Prin1 has mean 0 and variance the first eigenvalue', (r['mean'], round(r['var'], 3)), (True, round(float(ev[1][1].replace('−', '-')), 3)))
    await shot(page, 'mv-02-pca.png')

    # ---- Factor Analysis -------------------------------------------------------------------------
    r = await page.ev(open_report_js('factor', {'y': ['a', 'b', 'c', 'd', 'e']}, {'sphericity': True, 'kmo': True, 'fits': [{'method': 'ml', 'prior': 'smc', 'k': 2, 'rotation': 'varimax', 'kaiser': True}, {'method': 'pa', 'prior': 'smc', 'k': 2, 'rotation': 'promax', 'kaiser': True}], 'fa0|fitm': True, 'fa0|scoreplot': True}), timeout=240)
    check('Factor: no errors', r['errors'], [])
    check('Factor: the two fits', [o for o in r['outlines'] if o.startswith('Factor Analysis on')], ['Factor Analysis on Correlations with 2 Factors: Maximum Likelihood, Varimax Rotation', 'Factor Analysis on Correlations with 2 Factors: Principal Axis, Promax Rotation'])
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const b = rep.content;
      const go = [...b.querySelectorAll('.sm-btn')].find(x => x.textContent === 'Go');
      const k = [...b.querySelectorAll('input')].find(i => i.getAttribute('aria-label') === 'Number of factors');
      k.value = '1'; k.dispatchEvent(new Event('change'));
      go.click(); await new Promise(res => rep.on('done', res));
      return [...rep.content.querySelectorAll('.sm-ob-head h3')].filter(h => h.textContent.startsWith('Factor Analysis on')).map(h => h.textContent);
    }})()''')
    check('Factor: Model Launch Go adds a fit', r[-1], 'Factor Analysis on Correlations with 1 Factor: Maximum Likelihood, Varimax Rotation')

    # ---- Discriminant ------------------------------------------------------------------------------
    r = await page.ev(open_report_js('discriminant', {'y': ['a', 'b', 'c', 'd', 'e'], 'x': ['grp']}, {'stepwise': True, 'candetails': True, 'canstruct': True, 'groupmeans': True, 'withincov': True, 'dist': True, 'probs': True, 'cp50': True}), timeout=240)
    check('Discriminant: no errors', r['errors'], [])
    check('Discriminant: outlines', [o for o in ['Column Selection', 'Canonical Plot', 'Discriminant Scores', 'Score Summaries', 'Canonical Details', 'Canonical Structure', 'Group Means', 'Covariance Matrices'] if o not in r['outlines']], [])
    conf = await page.ev(table_under_js('Score Summaries', 1))
    total = sum(float(v) for row in conf[1:] for v in row[1:])
    check('Discriminant: the confusion matrix counts the 149 complete rows', total, 149.0)
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const ctx = {CTX}; const t = rep.table; const before = t.columns.length;
      const so = rep.platform.triangle(ctx).find(i => i.label === 'Score Options').submenu();
      await so.find(i => i.label === 'Save Formulas').action();
      const added = t.columns.slice(before).map(c => [c.name, c.modelingType, c.dataType]);
      const probs = t.columns.slice(before).filter(c => c.name.startsWith('Prob['));
      const s = probs.reduce((acc, c) => acc + c.values[0], 0);
      for (const c of t.columns.slice(before)) t.removeColumn(c.id);
      await so.find(i => i.label === 'Select Misclassified Rows').action();
      const mis = t.selectedRows().length; t.select([]);
      return {{ added, s, mis }};
    }})()''')
    check('Discriminant: Save Formulas', [x[0] for x in r['added']], ['SqDist[hi]', 'SqDist[lo]', 'SqDist[mid]', 'Prob[hi]', 'Prob[lo]', 'Prob[mid]', 'Pred grp'])
    check('Discriminant: the probabilities of a row sum to 1', round(r['s'], 9), 1.0)
    check('Discriminant: the predicted group is nominal character', r['added'][-1][1:], ['nominal', 'character'])
    nm = await page.ev(table_under_js('Score Summaries', 0))
    check('Discriminant: Select Misclassified Rows = Number Misclassified', str(r['mis']), nm[1][1])
    await shot(page, 'mv-03-discriminant.png')

    # ---- Hierarchical Cluster ------------------------------------------------------------------------
    r = await page.ev(open_report_js('hcluster', {'y': ['u', 'v']}, {'method': 'ward', 'standardize': 'none', 'criterion': True, 'summary': True, 'twoWay': True}), timeout=240)
    check('Hierarchical: no errors', r['errors'], [])
    legend = await page.ev(f'[...{LAST}.content.querySelectorAll(".mv-legend button")].map(b => b.textContent)')
    check('Hierarchical: the default is the three simulated clusters', legend, ['1: 50', '2: 50', '3: 50'])
    await run_menu(page, 'Color Clusters')
    colors = await page.ev('(() => { const t = SM.app.current; const s = new Set(); for (let i = 0; i < t.nrows; i++) s.add(t.color[i]); return [...s].sort(); })()')
    check('Hierarchical: Color Clusters gives the rows three colours', colors, [0, 1, 2])
    same = await page.ev('(() => { const t = SM.app.current; for (let i = 0; i + 3 < t.nrows; i++) if (t.color[i] !== t.color[i + 3]) return false; return true; })()')
    check('Hierarchical: the colours follow the simulated clusters', same, True)
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const ctx = {CTX};
      ctx.set('ncluster', 5); await new Promise(res => rep.on('done', res));
      return [...rep.content.querySelectorAll('.mv-legend button')].length;
    }})()''')
    check('Hierarchical: five clusters on request', r, 5)
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const ctx = {CTX};
      ctx.set('ncluster', 3); await new Promise(res => rep.on('done', res));
      const t = rep.table; const before = t.columns.length;
      await rep.platform.triangle(ctx).find(i => i.label === 'Save Clusters').action();
      const c = t.columns[t.columns.length - 1]; const out = {{ name: c.name, type: c.modelingType, levels: t.levels(c) }}; t.removeColumn(c.id); return out;
    }})()''')
    check('Hierarchical: Save Clusters', (r['name'], r['type'], r['levels']), ('Cluster', 'nominal', [1, 2, 3]))
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const p = rep.plots.find(p => p.opts.title === 'Dendrogram'); await p.draw();
      const t = rep.table; t.select([4]); await new Promise(r => setTimeout(r, 150));
      const leaf = p.kinds.findIndex(k => k === 'points'); const sp = p.box.data[leaf].selectedpoints; t.select([]); return sp.length;
    }})()''')
    check('Hierarchical: a selected row lights its leaf', r, 1)
    await page.ev('SM.app.current.clearRowStates()')
    await shot(page, 'mv-04-hcluster.png')

    # ---- K Means -----------------------------------------------------------------------------------------
    r = await page.ev(open_report_js('kmeans', {'y': ['u', 'v']}, {'k': 2, 'kRange': 5, 'scaled': False}), timeout=240)
    check('K Means: no errors', r['errors'], [])
    check('K Means: a report per number of clusters', [o for o in r['outlines'] if o.startswith('K Means NCluster')], ['K Means NCluster=2', 'K Means NCluster=3', 'K Means NCluster=4', 'K Means NCluster=5'])
    comp = await page.ev(table_under_js('Cluster Comparison'))
    best = [row for row in comp[1:] if row[3] == 'Optimal CCC']
    check('K Means: the optimal CCC is at 3 clusters', best[0][1] if best else None, '3')
    summ = await page.ev(f'''(() => {{ const rep = {LAST}; const h = [...rep.content.querySelectorAll('.sm-ob-head h3')].find(h => h.textContent === 'K Means NCluster=3'); const t = h.closest('.sm-ob').querySelector('table.sm-rt'); return [...t.querySelectorAll('tbody tr')].map(tr => tr.children[1].textContent); }})()''')
    check('K Means: the three clusters of 50', summ, ['50', '50', '50'])
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const p = rep.plots.find(p => p.opts.title === 'Biplot, 3 clusters'); await p.draw();
      p._click({{ points: [{{ curveNumber: 0, pointNumber: 3 }}], event: {{}} }});
      const sel = rep.table.selectedRows(); rep.table.select([]); return [sel, p.rows[0][3]];
    }})()''')
    check('K Means: a click on the biplot selects the row', r[0], [r[1]])

    # ---- Response Screening --------------------------------------------------------------------------------
    r = await page.ev(open_report_js('respscreen', {'y': ['a', 'b', 'c', 'grp'], 'x': ['d', 'e', 'grp']}, {'lwR2': True}), timeout=240)
    check('Response Screening: no errors', r['errors'], [])
    pv = await page.ev(table_under_js('PValues'))
    check('Response Screening: 11 pairs (grp is not tested against itself)', len(pv) - 1, 11)
    lw = [float(x[6].replace('−', '-')) for x in pv[1:]]
    check('Response Screening: sorted by FDR LogWorth', lw == sorted(lw, reverse=True), True)
    has = await page.ev('!!SM.platforms.get("fitybyx")')
    r = await page.ev(f'''(async () => {{
      const n = SM.app.reports.length; const rep = {LAST};
      const tr = [...rep.content.querySelectorAll('table.sm-rt')].pop().querySelector('tbody tr'); tr.click();
      await new Promise(r => setTimeout(r, 500));
      const top = SM.app.reports[SM.app.reports.length - 1];
      return {{ opened: SM.app.reports.length - n, platform: top.platform.id, y: top.spec.roles && top.spec.roles.y && SM.app.current.col(top.spec.roles.y[0]).name }};
    }})()''')
    if has:
        check('Response Screening: a line opens Fit Y by X for its pair', (r['opened'], r['platform'], r['y']), (1, 'fitybyx', pv[1][0]))
        await page.ev(f'SM.app.closeReport({LAST})')
    else:
        check('Response Screening: without Fit Y by X a line opens nothing', r['opened'], 0)

    # ---- Explore Outliers ---------------------------------------------------------------------------------------
    await page.ev('(() => { const t = SM.app.current; t.setCell(20, "a", 9999, { silent: true }); t.setCell(30, "c", -40); })()')
    r = await page.ev(open_report_js('outliers', {'y': ['a', 'b', 'c', 'd', 'e']}, {'qro': True, 'rfo': True, 'mro': True, 'knn': True}), timeout=240)
    check('Explore Outliers: no errors', r['errors'], [])
    q = await page.ev(table_under_js('Quantile Range Outliers'))
    rows = {x[0]: x for x in q[1:]}
    check('Quantile range: the planted 9999 in a', (rows['a'][5], rows['a'][6]), ('1', '9999'))
    check('Quantile range: the planted −40 in c', (rows['c'][5], rows['c'][6]), ('1', '−40'))
    nines = await page.ev(f'[...{LAST}.content.querySelectorAll(".sm-ob-head h4")].map(h => h.textContent).includes("Nines")')
    check('Quantile range: 9999 listed as a probable missing value code', nines, True)
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const b = [...rep.content.querySelectorAll('.sm-btn')].find(x => x.textContent === 'Select Rows'); b.click();
      await new Promise(r => setTimeout(r, 100)); const sel = rep.table.selectedRows(); rep.table.select([]); return sel;
    }})()''')
    check('Quantile range: Select Rows selects the two rows', r, [20, 30])
    mro = await page.ev(f'''(() => {{ const rep = {LAST}; const p = rep.plots.find(p => p.opts.title === 'Robust distances by row'); const i = p.rows[0].indexOf(20); return i >= 0 && p.traces[0].y[i] > 100; }})()''')
    check('Multivariate robust: row 21 far out', mro, True)
    await page.ev('(() => { const t = SM.app.current; t.setCell(20, "a", 0.1, { silent: true }); t.setCell(30, "c", 0.1); })()')
    await shot(page, 'mv-05-outliers.png')

    # ---- Multiple Correspondence Analysis, Multidimensional Scaling ----------------------------------------------------
    r = await page.ev(open_report_js('mca', {'y': ['grp', 'q1', 'q2']}, {'rowplot': True, 'adjusted': True, 'coords': True, 'summary': True, 'cross': True}), timeout=240)
    check('MCA: no errors', r['errors'], [])
    check('MCA: outlines', [o for o in ['Correspondence Analysis', 'Row Plot', 'Details', 'Adjusted Inertia', 'Coordinates', 'Summary Statistics', 'Cross Table (Burt)'] if o not in r['outlines']], [])
    det = await page.ev(table_under_js('Details'))
    check('MCA: J − Q = 5 dimensions', len(det) - 1, 5)
    check('MCA: the portions sum to 1', round(sum(float(x[3]) for x in det[1:]), 3), 1.0)
    r = await page.ev(open_report_js('mds', {'y': ['u', 'v']}, {'standardize': False, 'eigen': True}), timeout=240)
    check('MDS: no errors', r['errors'], [])
    fit = await page.ev(table_under_js('Fit Details'))
    check('MDS of two columns: the map is exact (stress 0)', abs(float(fit[0][1].replace('−', '-'))) < 1e-6, True)
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const p = rep.plots.find(p => p.opts.title === 'Multidimensional Scaling Plot'); await p.draw();
      p._click({{ points: [{{ curveNumber: 0, pointNumber: 5 }}], event: {{}} }});
      const sel = rep.table.selectedRows(); rep.table.select([]);
      const ctx = {CTX}; const t = rep.table; const before = t.columns.length;
      await rep.platform.triangle(ctx).find(i => i.label === 'Save Coordinates').action();
      const added = t.columns.slice(before).map(c => c.name); for (const c of t.columns.slice(before)) t.removeColumn(c.id);
      return {{ sel, want: p.rows[0][5], added }};
    }})()''')
    check('MDS: a click on the map selects the row', r['sel'], [r['want']])
    check('MDS: Save Coordinates', r['added'], ['MDS Dimension 1', 'MDS Dimension 2'])

    # ---- Item Reliability: intraclass correlations and Kendall's W ------------------------------------------------------
    await page.ev("SM.app.showTab(SM.app.tabOf(SM.app.tables.find(t => t.name === 'Multivariate test')))")
    r = await page.ev(open_report_js('multivariate', {'y': ['a', 'b', 'c', 'd', 'e']}, {'icc': True, 'kendallw': True, 'splom': False}), timeout=240)
    check('Item Reliability: no errors', r['errors'], [])
    check('Item Reliability: Intraclass Correlations and Kendall\'s W', [o for o in ('Intraclass Correlations', "Kendall's W") if o in r['outlines']], ['Intraclass Correlations', "Kendall's W"])
    items = await page.ev(f'''(() => {{ const rep = {LAST}; const ctx = {CTX}; const it = rep.platform.triangle(ctx).find(i => i.label === 'Item Reliability');
      return it.submenu().map(i => i.separator ? '—' : i.label); }})()''')
    check('the Item Reliability submenu', items, ["Cronbach's α", 'Standardized α', '—', 'Intraclass Correlations', "Kendall's W"])
    js = await page.ev('''(() => {
      const t = SM.app.current; const X = ['a', 'b', 'c', 'd', 'e'].map(n => t.col(n).values);
      const rows = [...Array(t.nrows).keys()].filter(i => X.every(v => Number.isFinite(v[i])));
      const n = rows.length, k = X.length;
      const g = rows.reduce((s, i) => s + X.reduce((a, v) => a + v[i], 0), 0) / (n * k);
      let ssr = 0, ssc = 0, sst = 0;
      for (const i of rows) { const m = X.reduce((a, v) => a + v[i], 0) / k; ssr += k * (m - g) ** 2; for (const v of X) sst += (v[i] - g) ** 2; }
      for (const v of X) { const m = rows.reduce((a, i) => a + v[i], 0) / n; ssc += n * (m - g) ** 2; }
      const sse = sst - ssr - ssc, msr = ssr / (n - 1), msc = ssc / (k - 1), mse = sse / ((n - 1) * (k - 1)), msw = (ssc + sse) / (n * (k - 1));
      const rank = (vals) => { const idx = vals.map((v, i) => [v, i]).sort((p, q) => p[0] - q[0]); const r = new Array(vals.length); let j = 0, T = 0;
        while (j < idx.length) { let e = j; while (e + 1 < idx.length && idx[e + 1][0] === idx[j][0]) e++; for (let q = j; q <= e; q++) r[idx[q][1]] = (j + e) / 2 + 1; T += (e - j + 1) ** 3 - (e - j + 1); j = e + 1; }
        return { r, T }; };
      let T = 0; const Rs = new Array(n).fill(0);
      for (const v of X) { const o = rank(rows.map(i => v[i])); T += o.T; o.r.forEach((x, q) => { Rs[q] += x; }); }
      const mean = Rs.reduce((a, b) => a + b) / n, S = Rs.reduce((a, b) => a + (b - mean) ** 2, 0);
      return { n, one: (msr - msw) / (msr + (k - 1) * msw), c1: (msr - mse) / (msr + (k - 1) * mse), a1: (msr - mse) / (msr + (k - 1) * mse + k * (msc - mse) / n), ck: (msr - mse) / msr,
        fr: msr / mse, w: 12 * S / (k * k * (n ** 3 - n) - k * T) };
    })()''')
    num = lambda s: float(str(s).replace('−', '-').replace('<', '').replace('*', ''))  # noqa: E731
    it = await page.ev(table_under_js('Intraclass Correlations', 2))
    icc = {row[0]: row for row in it[1:]}
    check('the ICC table: its columns', it[0], ['Form', 'Shrout–Fleiss', 'Model', 'ICC', 'F Ratio', 'NumDF', 'DenDF', 'Prob > F', 'Lower 95%', 'Upper 95%'])
    check('... the six forms', list(icc), ['ICC(1,1)', 'ICC(A,1)', 'ICC(C,1)', 'ICC(1,k)', 'ICC(A,k)', 'ICC(C,k)'])
    check.near('ICC(1,1) = the one-way ANOVA computed in the page', num(icc['ICC(1,1)'][3]), js['one'], 1e-4)
    check.near('ICC(C,1) = the two-way ANOVA computed in the page', num(icc['ICC(C,1)'][3]), js['c1'], 1e-4)
    check.near('ICC(A,1) = the page\'s', num(icc['ICC(A,1)'][3]), js['a1'], 1e-4)
    check.near('ICC(C,k) = the page\'s', num(icc['ICC(C,k)'][3]), js['ck'], 1e-4)
    check.near('its F = MSR/MSE', num(icc['ICC(C,1)'][4]), js['fr'], 1e-6)
    check('... on 148 and 592 DF (149 complete rows, 5 raters)', (icc['ICC(C,1)'][5], icc['ICC(C,1)'][6]), ('148', '592'))
    av = await page.ev(table_under_js('Intraclass Correlations', 1))
    check('the ANOVA table: Between Targets, Between Raters, Residual, Within Targets, Total', [row[0] for row in av[1:]], ['Between Targets', 'Between Raters', 'Residual', 'Within Targets', 'Total'])
    kv = dict((row[0], row[1]) for row in await page.ev(table_under_js("Kendall's W")))
    check.near("Kendall's W = the page's own ranks (ties corrected)", num(kv["Kendall's W"]), js['w'], 1e-6)
    check.near('its ChiSquare = m (n − 1) W', num(kv['ChiSquare']), 5 * (js['n'] - 1) * js['w'], 1e-6)
    check("Kendall's W: DF and the objects", (kv['DF'], kv['Objects (rows)'], kv['Raters (columns)']), ('148', '149', '5'))
    txt = await page.ev(f'{LAST}.content.textContent')
    check('the notes say which rows count', ('rated by every rater (149 of them)' in txt, '1 row without a rating from every rater' in txt), (True, True))
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const t = rep.table;
      const h = [...rep.content.querySelectorAll('.sm-ob-head')].find(x => x.textContent.trim() === 'Intraclass Correlations');
      const tbl = h.parentElement.querySelectorAll('table.sm-rt')[1];
      const col = tbl._rt.columns.find(c => c.label === 'ICC');
      const res = await SM.bootstrap.run(tbl, col, {{ B: 3, seed: 13, show: false }});
      const rows = SM.bootstrap.sampler(rep.groups()[0].rows, 13)();
      const own = await SM.engine.call('multivariate.icc', {{ columns: ['a', 'b', 'c', 'd', 'e'], rows }}, t);
      const out = {{ cols: res.columns.map(c => c.name).slice(0, 3), b0: res.col('ICC(C,1) ICC(3,1) Two-way, consistency, one rater').values[0], b1: res.col('ICC(C,1) ICC(3,1) Two-way, consistency, one rater').values[1],
        own: own.icc.find(x => x.form === 'ICC(C,1)').icc, report: tbl._rt.rows.find(x => x.form === 'ICC(C,1)').icc }};
      SM.app.closeTable(res); return out;
    }})()''', timeout=300)
    check('Bootstrap of the ICC column: its rows are the forms', r['cols'], ['BootID', 'ICC(1,1) ICC(1,1) One-way random, one rater', 'ICC(A,1) ICC(2,1) Two-way, absolute agreement, one rater'])
    check.near('... sample 0 is the report', r['b0'], r['report'], 1e-12)
    check.near('... sample 1 is multivariate.icc on its rows (the render has no side effects)', r['b1'], r['own'], 1e-12)
    r = await run_menu(page, 'Item Reliability', 'Intraclass Correlations')
    outl = await page.ev(f'[...{LAST}.content.querySelectorAll(".sm-ob-head h3")].map(h => h.textContent)')
    check('the submenu item turns Intraclass Correlations off', (r, 'Intraclass Correlations' in outl, "Kendall's W" in outl), ('ok', False, True))
    await shot(page, 'mv-08-reliability.png')

    # ---- every (i) of these reports has a topic, every Help link a target -------------------------------------------
    audit = json.loads(await page.ev('JSON.stringify(KvotInfo.audit())'))
    check('every (i) in the reports has a topic', audit.get('noTopic'), [])
    check('every Help link has a target', audit.get('brokenMore'), [])
    helprows = await page.ev('["multivariate", "pca", "factor", "discriminant", "hcluster", "kmeans", "respscreen", "outliers", "mca", "mds"].filter(id => !document.getElementById("help-p-" + id))')
    check('the Help tab lists the ten platforms', helprows, [])

    # ---- help for every input: the launch dialogs, the forms, the controls in the reports ---------------------------
    await page.ev(HELP_JS)
    mine = ['multivariate', 'pca', 'factor', 'discriminant', 'hcluster', 'kmeans', 'respscreen', 'outliers', 'mca', 'mds']
    r = await page.ev(f'''{json.dumps(mine)}.flatMap((id) => {{ const L = SM.platforms.get(id).launch;
      return [...L.roles, ...(L.options || [])].filter((f) => !f.help).map((f) => `${{id}}: ${{f.label}}`); }})''')
    check('every role and option of the ten platforms has its help', r, [])
    for pid in mine:
        check_launch(await page.ev(f'__hlp.launch({json.dumps(pid)})'), pid)
    specs = [('pca', {'y': ['a', 'b', 'c', 'd', 'e']}, {'fmtload': True}), ('factor', {'y': ['a', 'b', 'c', 'd', 'e']}, {'fits': [{'method': 'ml', 'prior': 'smc', 'k': 2, 'rotation': 'varimax', 'kaiser': True}]}),
             ('discriminant', {'y': ['a', 'b', 'c', 'd', 'e'], 'x': ['grp']}, {'stepwise': True}), ('hcluster', {'y': ['u', 'v']}, {}), ('kmeans', {'y': ['u', 'v']}, {}),
             ('respscreen', {'y': ['a', 'b'], 'x': ['c', 'grp']}, {}), ('outliers', {'y': ['a', 'c']}, {'qro': True, 'rfo': True, 'mro': True, 'knn': True}),
             ('mca', {'y': ['grp', 'q1', 'q2']}, {}), ('multivariate', {'y': ['a', 'c', 'e']}, {})]
    for pid, roles, opts in specs:
        r = await page.ev(open_report_js(pid, roles, opts), timeout=240)
        check(f'{pid}: a report for the help checks, without errors', r['errors'], [])
        await page.ev(f'window.__rep_{pid} = {LAST}')
    forms = [('pca', 'Principal Components: on Correlations', ['Factor Rotation…'], 'Factor Rotation', None), ('pca', 'Principal Components: on Correlations', ['Save Columns', 'Save Principal Components…'], 'Save Principal Components', None),
             ('discriminant', 'Discriminant Analysis', ['Discriminant Method', 'Regularized, Compromise Method…'], 'Regularization Parameters', None),
             ('discriminant', 'Discriminant Analysis', ['Score Options', 'Select Uncertain Rows…'], 'Select Uncertain Rows', None),
             ('discriminant', 'Discriminant Analysis', ['Specify Priors', 'Other…'], 'Specify Priors (a field per group)', ['Each group']),
             ('hcluster', 'Hierarchical Clustering', ['Number of Clusters…'], 'Number of Clusters', None), ('respscreen', 'Response Screening', ['Max Logworth…'], 'Max Logworth', None),
             ('multivariate', 'Multivariate', ['Set α Level', 'Other…'], 'Set α Level', None)]
    for pid, title_, path, name, expect in forms:
        check_form(await page.ev(f'__hlp.form(window.__rep_{pid}, {json.dumps(title_)}, {json.dumps(path)})'), name, expect=expect)
    # the controls in the reports: each is explained in its outline's (i)
    # (the outline, the heading of its section on the controls, how many controls it has: inputs and buttons)
    panels = [('pca', 'Summary Plots', 'In the report', 2), ('pca', 'Formatted Loading Matrix', 'In the report', 2), ('factor', 'Model Launch', 'The controls', 7),
              ('factor', 'Factor Analysis on Correlations with 2 Factors…', 'In the report', 2), ('discriminant', 'Column Selection', 'In the report', 5),
              ('hcluster', 'Dendrogram', 'In the report', 3), ('kmeans', 'Iterative Clustering', 'The controls', 6), ('kmeans', 'K Means NCluster=3', 'In the report', 0),
              ('outliers', 'Quantile Range Outliers', 'In the report', 8), ('outliers', 'Robust Fit Outliers', 'In the report', 6), ('outliers', 'Multivariate Robust Outliers', 'In the report', 4),
              ('outliers', 'Multivariate k-Nearest Neighbor Outliers', 'In the report', 1), ('mca', 'Correspondence Analysis', 'In the report', 2)]
    for pid, title_, heading, n in panels:
        r = await page.ev(f'__hlp.outline(window.__rep_{pid}, {json.dumps(title_)})')
        choices = section((r or {}).get('info'), heading)
        controls = (r or {}).get('controls', [])
        check(f'{pid}, {title_}: its (i) explains the {n} controls in it', (bool(choices), len(controls), [c for c in controls if c not in names_of(choices)]), (True, n, []))
        check(f'{pid}, {title_}: ... each with what it does', [n for n, t in choices if len(t) < 12], [])
    r = await page.ev('''(async () => { const b = __rep_outliers.body.querySelector('.mv-methods .info-btn'); const info = await __hlp.read(b); return info && [info.title, info.secs.map((s) => s.heading)]; })()''')
    check('Explore Outliers: the method buttons have an (i) that explains them', (r or [None, []])[0], 'Explore Outliers')
    check('... with a section on the buttons', 'The method buttons' in (r or [None, []])[1], True)
    r = await page.ev(f'''(async () => {{ for (const id of {json.dumps([s[0] for s in specs])}) SM.app.closeReport(window['__rep_' + id]); return {{ dialogs: SM.ui.dialogs.length, audit: KvotInfo.audit().noTopic }}; }})()''')
    check('the forms closed with their ×, and every (i) left has a topic', (r['dialogs'], r['audit']), (0, []))

    # ---- By, for every platform ------------------------------------------------------------------------------------------
    await page.ev('SM.app.current.setType("f", { modelingType: "nominal" })')
    by_specs = [('multivariate', {'y': ['a', 'c', 'e']}, {'mahal': True, 'alpha:raw': True, 'dcor': True, 'icc': True, 'kendallw': True}), ('pca', {'y': ['a', 'c', 'e']}, {}),
                ('factor', {'y': ['a', 'b', 'c', 'd', 'e']}, {'fits': [{'method': 'ml', 'prior': 'smc', 'k': 1, 'rotation': 'none'}]}),
                ('discriminant', {'y': ['a', 'c'], 'x': ['grp']}, {}), ('hcluster', {'y': ['u', 'v']}, {}), ('kmeans', {'y': ['u', 'v']}, {'k': 3}),
                ('respscreen', {'y': ['a', 'b'], 'x': ['c', 'grp']}, {}), ('outliers', {'y': ['a', 'c']}, {'qro': True, 'mro': True}),
                ('mca', {'y': ['grp', 'q1']}, {}), ('mds', {'y': ['a', 'c']}, {})]
    for pid, roles, opts in by_specs:
        r = await page.ev(open_report_js(pid, {**roles, 'by': ['f']}, opts), timeout=240)
        tops = [o for o in r['outlines'] if o.endswith(('f=1', 'f=2', 'f=3'))]
        check(f'By: {pid} gives three groups without an error', (len(tops), r['errors']), (3, []))
        await page.ev(f'SM.app.closeReport({LAST})')
    await page.ev('SM.app.current.setType("f", { modelingType: "continuous" })')

    # ---- exclusion and Redo ---------------------------------------------------------------------------------------
    r = await page.ev(open_report_js('multivariate', {'y': ['a', 'c']}, {}), timeout=240)
    r = await page.ev(f'''(async () => {{
      const rep = {LAST}; const t = rep.table; t.setState([0, 1, 2, 3, 4, 5], 'excluded', true);
      rep.run(); await new Promise(res => rep.on('done', res));
      const txt = rep.content.textContent; t.setState([0, 1, 2, 3, 4, 5], 'excluded', false); return txt.includes('144 observations');
    }})()''')
    check('exclude rows and Redo: 144 observations', r, True)

    # ---- the graphs' matplotlib code, and five reports' statistics code, run in the page -------------------------------
    await chart_code(page)
    await stats_code(page)

    # ---- dark theme, phone width ------------------------------------------------------------------------------------
    r = await page.ev(open_report_js('multivariate', {'y': ['a', 'b', 'c', 'd', 'e']}, {'cmCells': True, 'pairwise': True, 'mahal': True, 'dcor': True, 'icc': True, 'kendallw': True}), timeout=240)
    await page.ev("KVOT.setTheme ? KVOT.setTheme('dark') : document.documentElement.setAttribute('data-theme', 'dark')")
    await page.ev(f'new Promise(res => {LAST}.on("done", res))')
    await asyncio.sleep(1.2)
    ink = await page.ev(f'''(() => {{
      const td = {LAST}.content.querySelector('td.mv-cm'); const cs = getComputedStyle(td);
      const rgb = (s) => s.match(/\\d+/g).slice(0, 3).map(Number); const lum = ([r, g, b]) => (0.299 * r + 0.587 * g + 0.114 * b) / 255;
      return Math.abs(lum(rgb(cs.color)) - lum(rgb(cs.backgroundColor)));
    }})()''')
    check('dark theme: coloured cells keep their contrast', ink > 0.4, True)
    check('dark theme: no errors', (await page.ev(f'[...{LAST}.content.querySelectorAll(".sm-ob-error")].length'), page.errors), (0, []))
    await shot(page, 'mv-06-dark.png')
    await page.call('Emulation.setDeviceMetricsOverride', {'width': 400, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True}, session=page.sid)
    await asyncio.sleep(0.8)
    check('phone width: no horizontal page scroll', await page.ev('document.documentElement.scrollWidth <= innerWidth + 1'), True)
    await shot(page, 'mv-07-phone.png')
    check('no script errors', page.errors, [])
    await page.close()


asyncio.run(main())
sys.exit(check.done())
