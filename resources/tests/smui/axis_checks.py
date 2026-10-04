"""A shared helper of the browser suites: Axis Settings (smui-axis.js) checks
for a platform's own graphs. test-ui-distribution.py (the histogram, whose
value axis the box plot shares) and test-ui-quality.py (the Pareto plot's
Cum Percent axis) use it; a platform whose graph passes opts.axisCode or
opts.axisAlso can check it the same way. It is not a suite of its own.

A graph's axis window opened by a real double-click on the axis (its drag
box, where Plotly puts the tick labels) or from the report's red triangle;
its fields set; the graph read back (the axis's range, type and ticks, the
reference lines as shapes, their labels); its code block run in the page's
own Python (the notebook's runner) and its figure read with test_charts'
PROBE_MORE; Redo, a saved project and the dark theme. The suites give the
platform's own cases (test-ui-distribution.py, test-ui-quality.py).

This file imports only the standard library and test_charts at the top, as
the browser suites do.
"""
import asyncio
import json

from test_charts import more_from_outputs, page_probe_more

AXIS_JS = r'''
window.__axc = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  plot(rep, title) { return (rep.plots || []).find((p) => (p.opts.title || '') === title) || null; },
  // the graph titled so, drawn and in view, once the report has run
  async shown(rep, title) {
    for (let i = 0; i < 400 && rep.body.classList.contains('is-running'); i++) await this.sleep(25);
    await this.sleep(60);
    const p = this.plot(rep, title);
    if (!p) return null;
    SM.app.showTab(SM.app.tabOf(rep));
    p.box.scrollIntoView({ block: 'center' });
    for (let i = 0; i < 200 && !p.drawn; i++) { await p.draw(); await this.sleep(25); }
    await this.sleep(150);
    return p;
  },
  // the middle of an axis's drag box: sub the subplot ('xy', 'xy2', 'x2y'), which 'ns' (y) or 'ew' (x)
  async at(rep, title, sub, which) {
    const p = await this.shown(rep, title);
    const r = p && p.box.querySelector(`.draglayer .${sub} rect.${which}drag`);
    if (!r) return null;
    const b = r.getBoundingClientRect();
    return [b.x + b.width / 2, b.y + b.height / 2];
  },
  dialog() { return [...document.querySelectorAll('.sm-dialog')].pop() || null; },
  // the window's fields: { scale, min, max, inc, reverse, refs: [{ value, to, label, color, dash }] }; OK, and the report run again
  async fill(rep, v) {
    const d = this.dialog();
    if (!d) return null;
    const title = d.querySelector('h2').textContent;
    const set = (root, k, x) => { const i = root.querySelector(`[data-ax="${k}"]`); if (!i) return; if (i.type === 'checkbox') i.checked = !!x; else i.value = String(x); i.dispatchEvent(new Event('change', { bubbles: true })); };
    for (const k of ['scale', 'min', 'max', 'inc', 'reverse']) if (v[k] != null) set(d, k, v[k]);
    for (const r of v.refs || []) {
      d.querySelector('[data-ax="addref"]').click();
      const row = [...d.querySelectorAll('.sm-ax-ref')].pop();
      set(row, 'ref', r.value);
      if (r.to != null) set(row, 'refto', r.to);
      if (r.label) set(row, 'reflabel', r.label);
      if (r.color) set(row, 'refcolor', r.color);
      if (r.dash) set(row, 'refdash', r.dash);
    }
    const done = new Promise((res) => rep.on('done', res));
    [...d.querySelectorAll('.sm-dialog-foot button')].find((b) => b.textContent === 'OK').click();
    await done;
    return title;
  },
  // the red triangle's Axis Settings ▸ an axis (by its item's label)
  async fromMenu(rep, label) {
    rep.body.querySelector('.sm-ob.level-0 > .sm-ob-head .sm-ob-menu').click(); await this.sleep(80);
    const item = (m, text) => m && [...m.querySelectorAll('button')].find((b) => b.textContent.replace(/^✓/, '') === text);
    const top = [...document.querySelectorAll('.sm-menu')][0];
    const ax = item(top, 'Axis Settings');
    if (!ax) { SM.ui.closeMenus(0); return null; }
    ax.dispatchEvent(new MouseEvent('mouseenter')); await this.sleep(80);
    const sub = [...document.querySelectorAll('.sm-menu')][1];
    const labels = sub ? [...sub.querySelectorAll('button')].map((b) => b.textContent) : [];
    const b = item(sub, label);
    if (b) b.click(); else SM.ui.closeMenus(0);
    await this.sleep(120);
    return { labels, opened: !!this.dialog() };
  },
  // the graph as drawn: every axis's type, range and ticks, the reference lines and ranges, the labels, the code under it
  state(p) {
    const fl = p.box._fullLayout;
    const axes = {};
    for (const k of Object.keys(fl)) if (/^[xy]axis\d*$/.test(k)) axes[k] = { type: fl[k].type, range: fl[k].range.slice(), ticks: (fl[k]._vals || []).map((t) => t.x) };
    const n = p.box.nextElementSibling;
    return { axes, shapes: (fl.shapes || []).map((q) => ({ type: q.type, xref: q.xref, yref: q.yref, x0: q.x0, x1: q.x1, y0: q.y0, y1: q.y1, color: q.type === 'line' ? q.line.color : q.fillcolor })),
      labels: (fl.annotations || []).map((a) => a.text), code: n && n.matches('details.sm-code, .sm-code-box') ? n.querySelector('code').textContent : null };
  },
  // the report saved in a project and opened again: its graph's state there
  async reopened(rep, title) {
    const t = rep.table;
    const proj = { format: 'smui-project', version: 1, tables: [{ id: t.id, ...t.toJSON() }], reports: [rep.toJSON()] };
    SM.app.loadProject(JSON.parse(JSON.stringify(proj)));
    const again = SM.app.reports[SM.app.reports.length - 1];
    await new Promise((res) => { if (again.plots.length && !again.body.classList.contains('is-running')) res(); else again.on('done', res); });
    const p = await this.shown(again, title);
    const out = p ? this.state(p) : null;
    SM.app.closeReport(again); SM.app.closeTable(again.table); SM.app.showTab(SM.app.tabOf(rep));
    return out;
  },
};
'''


async def dbl(page, x, y):
    """A real double-click: two presses and releases, as a mouse makes them."""
    await page.mouse('mouseMoved', x, y)
    for n in (1, 2):
        await page.mouse('mousePressed', x, y, clicks=n)
        await page.mouse('mouseReleased', x, y, clicks=n)
    await asyncio.sleep(0.5)


async def run_code(page, code, table_js):
    """The code run in the page's Python: the figures as PROBE_MORE reads them, or an error."""
    out = await page.ev(f'__gr.run({json.dumps(page_probe_more(code or "", []))}, {table_js})', timeout=300)
    return more_from_outputs(out.get('outputs') if isinstance(out, dict) else None)


def red_lines(A, letter, color='#b0413e'):
    """A figure's axes' reference lines of that colour across the plot: the value of each (a horizontal line for y)."""
    out = []
    for L in A.get('lines', []):
        if not (L.get('color') or '').startswith(color):
            continue
        xs, ys = L['x'], L['y']
        if letter == 'y' and len(ys) == 2 and ys[0] == ys[1] and xs == [0.0, 1.0]:
            out.append(ys[0])
        elif letter == 'x' and len(xs) == 2 and xs[0] == xs[1] and ys == [0.0, 1.0]:
            out.append(xs[0])
    return out


def r9(v):
    return [round(x, 9) for x in v] if isinstance(v, (list, tuple)) else round(v, 9)
