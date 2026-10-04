#!/usr/bin/env python3
"""The matplotlib code under the graphs of Distribution, Fit Y by X and Fit
Model: every snippet the backend writes is run on a CSV export of its table
(as the notebook runs it, with matplotlib's Agg backend here), and the figure
it draws is checked against the report's numbers: bar heights against the
counts, curves against the fits' predictions, box plots against the
quartiles and whiskers, the mosaic's rectangles against the cell
proportions, the axis labels and titles against the page's.

The graphs whose numbers the page works out (the histogram's bins, the
jittered points, the scatterplot with its fits) have their code written in
the page: test-ui-distribution.py, test-ui-fitybyx.py and test-ui-fitmodel.py
run those snippets in the page's own Python and compare the figures with the
page's Plotly graphs, with PROBE and the helpers here.

    python3 resources/tests/smui/test_charts.py

This file imports nothing beyond the standard library at the top, so that the
browser tests (whose Python need not have numpy or statsmodels) can take
PROBE and the comparison helpers from it.
"""
import contextlib
import io
import json
import math
import os
import sys
import tempfile

# Appended to a snippet (after its plt.show(), or instead of it in the page,
# where plt.show() hands the figures over and closes them): every open figure
# as plain data.
PROBE = r'''
def _smui_figures():
    import numpy as _np
    import matplotlib.pyplot as _plt
    from matplotlib.colors import to_hex as _hex
    from matplotlib.collections import PathCollection as _PC, PolyCollection as _Poly, LineCollection as _LC
    from matplotlib.patches import Rectangle as _Rect, Ellipse as _Ell, Polygon as _Pg, PathPatch as _PP

    def num(a):
        a = _np.asarray(a, dtype=float).ravel()
        return [float(v) if _np.isfinite(v) else None for v in a]

    def col(c):
        try:
            return _hex(c, keep_alpha=True)
        except Exception:
            return None

    out = []
    for n in _plt.get_fignums():
        fig = _plt.figure(n)
        F = {'suptitle': fig._suptitle.get_text() if getattr(fig, '_suptitle', None) is not None else '', 'size': num(fig.get_size_inches()), 'axes': [],
             'legend': [t.get_text() for lg in fig.legends for t in lg.get_texts()]}
        for ax in fig.axes:
            A = {'title': ax.get_title(), 'xlabel': ax.get_xlabel(), 'ylabel': ax.get_ylabel(), 'xlim': num(ax.get_xlim()), 'ylim': num(ax.get_ylim()),
                 'xticks': num(ax.get_xticks()), 'yticks': num(ax.get_yticks()),
                 'xticklabels': [t.get_text() for t in ax.get_xticklabels()], 'yticklabels': [t.get_text() for t in ax.get_yticklabels()],
                 'xscale': ax.get_xscale(), 'yscale': ax.get_yscale(), 'visible': ax.axison, 'yinverted': bool(ax.yaxis_inverted()),
                 'lines': [], 'bars': [], 'patches': [], 'scatter': [], 'polys': [], 'segments': [], 'texts': [], 'legend': [], 'images': []}
            for im in ax.images:
                arr = _np.asarray(im.get_array(), dtype=float)
                A['images'].append({'shape': list(arr.shape), 'data': num(arr)})
            for ln in ax.lines:
                try:
                    lx, ly = num(ln.get_xdata()), num(ln.get_ydata())
                except (TypeError, ValueError):   # categories on an axis: their places
                    xy = ln.get_xydata()
                    lx, ly = num(xy[:, 0]), num(xy[:, 1])
                A['lines'].append({'x': lx, 'y': ly, 'color': col(ln.get_color()), 'ls': str(ln.get_linestyle()),
                                   'lw': float(ln.get_linewidth()), 'marker': str(ln.get_marker()), 'label': str(ln.get_label()), 'drawstyle': str(ln.get_drawstyle())})
            for p in ax.patches:
                if isinstance(p, _Rect):
                    A['bars'].append({'x': float(p.get_x()), 'y': float(p.get_y()), 'w': float(p.get_width()), 'h': float(p.get_height()), 'fc': col(p.get_facecolor()), 'label': str(p.get_label())})
                elif isinstance(p, _Ell):
                    A['patches'].append({'type': 'ellipse', 'center': num(p.center), 'w': float(p.width), 'h': float(p.height), 'ec': col(p.get_edgecolor())})
                else:
                    try:
                        v = p.get_path().vertices if isinstance(p, _PP) else p.get_xy()
                        v = p.get_patch_transform().transform(v) if isinstance(p, _PP) else v
                    except Exception:
                        v = []
                    A['patches'].append({'type': type(p).__name__, 'xy': [num(q) for q in v], 'fc': col(p.get_facecolor()), 'ec': col(p.get_edgecolor())})
            for c in ax.collections:
                if isinstance(c, _PC):
                    A['scatter'].append({'xy': [num(q) for q in c.get_offsets()], 'sizes': num(c.get_sizes()), 'colors': [col(q) for q in c.get_facecolors()], 'label': str(c.get_label())})
                elif isinstance(c, _LC):
                    A['segments'].append({'segs': [[num(q) for q in s] for s in c.get_segments()], 'label': str(c.get_label())})
                elif isinstance(c, _Poly):
                    A['polys'].append({'paths': [[num(q) for q in p.vertices] for p in c.get_paths()], 'colors': [col(q) for q in c.get_facecolors()], 'label': str(c.get_label())})
                elif hasattr(c, 'levels'):
                    A['polys'].append({'contour': num(c.levels), 'paths': [[num(q) for q in p.vertices] for p in c.get_paths()], 'label': str(c.get_label())})
            for t in ax.texts:
                xy = t.get_position()
                A['texts'].append({'x': float(xy[0]) if _np.isfinite(xy[0]) else None, 'y': float(xy[1]) if _np.isfinite(xy[1]) else None, 's': t.get_text()})
            for t in ax.containers:
                pass
            lg = ax.get_legend()
            if lg is not None:
                A['legend'] = [t.get_text() for t in lg.get_texts()]
            F['axes'].append(A)
        out.append(F)
    return out
'''


# PROBE and more, for the Graph menu's code (test_graph.py, test-ui-graph.py):
# each axes' heatmaps (QuadMesh), pie wedges, polygons and lines in the axes'
# own units (a date axis in days), 3D scatters and the Z label, whether it is
# shown; the figure's subfigures' titles and texts, its sup-labels, its colour
# bars' labels; and those of the code's own variables it is asked for (names),
# as lists of numbers. A contour set keeps its levels, not its paths.
PROBE_MORE = PROBE + r'''
def _smui_figures_more(names=()):
    import numpy as _np
    import matplotlib.pyplot as _plt
    from matplotlib.collections import QuadMesh as _QM, Collection as _Coll
    from matplotlib.patches import Wedge as _W, Polygon as _Pg
    from matplotlib.colors import to_hex as _hex

    def num(a):
        a = _np.ma.filled(_np.ma.asarray(a, dtype=float), _np.nan).ravel()
        return [float(v) if _np.isfinite(v) else None for v in a]

    def subs(f):
        out = []
        for sf in getattr(f, 'subfigs', []):
            out.append({'suptitle': sf._suptitle.get_text() if getattr(sf, '_suptitle', None) is not None else '',
                        'texts': [t.get_text() for t in sf.texts]})
            out += subs(sf)
        return out
    for n in _plt.get_fignums():
        _plt.figure(n).canvas.draw()   # colours mapped from values, the layout: as the figure is drawn
    figs = _smui_figures()
    for F, n in zip(figs, _plt.get_fignums()):
        fig = _plt.figure(n)
        F['subfigs'] = subs(fig)
        F['supx'] = fig._supxlabel.get_text() if getattr(fig, '_supxlabel', None) is not None else ''
        F['supy'] = fig._supylabel.get_text() if getattr(fig, '_supylabel', None) is not None else ''
        F['colorbars'] = [ax.get_ylabel() for ax in fig.axes if getattr(ax, '_colorbar', None) is not None]
        for ax, A in zip(fig.axes, F['axes']):
            for c in A['polys']:   # a contour set's levels, and how many paths (their points, and a 3D surface's
                if 'contour' in c or hasattr(ax, 'get_zlabel'):   # facets, would outgrow a cell's output)
                    c['npaths'] = len(c.pop('paths'))
            A['shown'] = bool(ax.get_visible())
            A['colorbar'] = getattr(ax, '_colorbar', None) is not None
            A['meshes'] = [{'shape': list(m.get_array().shape), 'z': num(m.get_array()), 'clim': num(m.get_clim()),
                            'x': num(m.get_coordinates()[0, :, 0]), 'y': num(m.get_coordinates()[:, 0, 1])} for m in ax.collections if isinstance(m, _QM)]
            A['wedges'] = [{'theta1': float(p.theta1), 'theta2': float(p.theta2), 'r': float(p.r), 'width': None if p.width is None else float(p.width),
                            'fc': _hex(p.get_facecolor(), keep_alpha=True)} for p in ax.patches if isinstance(p, _W)]
            A['polygons'] = [{'xy': [num(q) for q in p.get_xy()], 'fc': _hex(p.get_facecolor(), keep_alpha=True), 'ec': _hex(p.get_edgecolor(), keep_alpha=True)}
                             for p in ax.patches if isinstance(p, _Pg)]
            A['xy_lines'] = [[num(q) for q in ln.get_xydata()] for ln in ax.lines]
            A['annotations'] = [{'s': t.get_text(), 'xy': num(getattr(t, 'xy', t.get_position())), 'color': _hex(t.get_color())} for t in ax.texts]
            A['xaxis_date'] = 'Date' in type(ax.xaxis.get_major_formatter()).__name__ or 'Date' in type(ax.xaxis.get_major_locator()).__name__
            A['yaxis_date'] = 'Date' in type(ax.yaxis.get_major_formatter()).__name__ or 'Date' in type(ax.yaxis.get_major_locator()).__name__
            # mplot3d: the Z label, and each 3D scatter's points and colours in the data's order (not the drawing's)
            A['zlabel'] = ax.get_zlabel() if hasattr(ax, 'get_zlabel') else None
            A['scatter3d'] = []
            for c in ax.collections:
                if hasattr(c, '_offsets3d'):   # Collection's own colours: the 3D ones come sorted by depth
                    A['scatter3d'].append({'xyz': [num(q) for q in c._offsets3d], 'sizes': num(c.get_sizes()),
                                           'colors': [_hex(q, keep_alpha=True) for q in _Coll.get_facecolor(c)]})
    g = globals()
    V = {}
    for k in names:
        if k in g:
            try:
                V[k] = num(g[k])
            except Exception:
                V[k] = None
    return {'figures': figs, 'vars': V}
'''


def page_probe_more(code, names=()):
    """The snippet, then PROBE_MORE's figures and variables printed as one JSON line."""
    return strip_show(code) + '\n' + PROBE_MORE + f'\nimport json as _json\nprint("SMUI-FIGURES " + _json.dumps(_smui_figures_more({list(names)!r})))\n'


def more_from_outputs(outputs):
    """PROBE_MORE's figures and variables from the outputs of the page's runner
    (an error when they do not fit in one output, which the notebook cuts at
    400,000 characters)."""
    try:
        got, err = figures_from_outputs(outputs)
    except ValueError:
        return None, 'the figures do not fit in one output of the page\'s runner'
    return (got, None) if got is not None else (None, err)


def run_snippet_more(code, frame, name, tmp, names=(), files=None):
    """As run_snippet, with PROBE_MORE: ({figures, vars}, error). files: more
    CSV exports ({name: frame}) the code reads."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import warnings
    plt.close('all')
    frame.to_csv(os.path.join(tmp, f'{name}.csv'), index=False)
    for other, f in (files or {}).items():
        f.to_csv(os.path.join(tmp, f'{other}.csv'), index=False)
    ns = {'__name__': '__main__'}
    here = os.getcwd()
    os.chdir(tmp)
    try:
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter('ignore')
            exec(strip_show(code), ns)
            exec(PROBE_MORE, ns)
            out = ns['_smui_figures_more'](names)
        return out, None
    except Exception as e:  # reported as a failed check
        import traceback
        return None, f'{type(e).__name__}: {e}\n{traceback.format_exc(limit=-3)}'
    finally:
        os.chdir(here)
        plt.close('all')


def strip_show(code):
    """The snippet without its last line, plt.show() (the page's plt.show()
    shows the figures and closes them, before a probe could read them)."""
    lines = code.rstrip('\n').split('\n')
    if lines and lines[-1].strip() == 'plt.show()':
        lines = lines[:-1]
    return '\n'.join(lines)


def page_probe(code):
    """The snippet, and then the probe's figures printed as one JSON line."""
    return strip_show(code) + '\n' + PROBE + '\nimport json as _json\nprint("SMUI-FIGURES " + _json.dumps(_smui_figures()))\n'


def figures_from_outputs(outputs):
    """The probe's figures from the outputs of the page's notebook runner."""
    text = ''.join(o.get('text', '') for o in outputs or [] if o.get('type') == 'stream' and o.get('name') == 'stdout')
    errs = [f"{o.get('ename')}: {o.get('evalue')}" for o in outputs or [] if o.get('type') == 'error']
    for line in text.split('\n'):
        if line.startswith('SMUI-FIGURES '):
            return json.loads(line[len('SMUI-FIGURES '):]), None
    return None, (errs[0] if errs else 'the probe printed nothing')


# For the browser tests: every graph of a report with its traces, layout
# shapes, axis titles and size, and the code block right under it; and the
# notebook's runner, to run a block in the page's own Python.
GRAPHS_JS = r'''
window.__gr = {
  // A graph draws when it comes near the view: draw the report's other graphs
  // first (those that can be seen: not in a closed outline), so that none is
  // left out of the checks.
  async drawAll(rep) {
    const tab = SM.app.tabOf(rep), was = SM.app.activeTab;
    if (tab && tab !== was) SM.app.showTab(tab);   // a report in a tab behind another draws nothing
    for (let i = 0; i < 400; i++) {
      const left = (rep.plots || []).filter((q) => !q.drawn && q.box.isConnected && q.box.offsetParent !== null);
      if (!left.length) break;
      for (const q of left) await q.draw();
      await new Promise((r) => setTimeout(r, 25));
    }
    if (tab && tab !== was && was) SM.app.showTab(was);
  },
  // The report's graphs that are not drawn: their titles, and why.
  undrawn(rep) {
    return (rep.plots || []).filter((q) => !q.drawn).map((q) => `${q.opts.title || '(untitled)'} (${!q.box.isConnected ? 'not in the page'
      : q.box.offsetParent === null ? 'hidden' : q.drawing ? 'drawing' : 'not drawn'}${rep.body.classList.contains('is-running') ? ', the report running' : ''}; ${rep.title}, run ${rep.seq})`);
  },
  // The titles of the graphs that graphs() found undrawn since the last take().
  missed: [],
  take() { const m = this.missed; this.missed = []; return m; },
  // Until no report has run for 300 ms: a change of theme runs every report
  // again, a little later, and a report opened meanwhile would be run twice
  // at once.
  async idle() {
    let calm = 0;
    for (let i = 0; i < 4800 && calm < 12; i++) {
      await new Promise((r) => setTimeout(r, 25));
      calm = SM.app.reports.some((x) => x.body.classList.contains('is-running')) ? 0 : calm + 1;
    }
  },
  // Until the report has finished running (a change to the table runs it again).
  async settle(rep) { for (let i = 0; i < 2400 && rep.body.classList.contains('is-running'); i++) await new Promise((r) => setTimeout(r, 25)); },
  async graphs(rep) {
    for (let i = 0; i < 20; i++) {   // again if the report ran again meanwhile (its graphs are new)
      await this.settle(rep);
      const plots = rep.plots;
      await this.drawAll(rep);
      if (rep.plots === plots && !rep.body.classList.contains('is-running')) break;
    }
    this.missed.push(...this.undrawn(rep));
    return [...rep.body.querySelectorAll('.js-plotly-plot')].map((p) => {
      const n = p.nextElementSibling;
      const L = p.layout || {};
      const t = (a) => (L[a] && L[a].title ? (typeof L[a].title === 'string' ? L[a].title : L[a].title.text) : null);
      const pick = (d) => { const o = {}; for (const k of ['type', 'name', 'mode', 'orientation', 'x', 'y', 'base', 'width', 'q1', 'median', 'q3', 'lowerfence', 'upperfence', 'xaxis', 'yaxis', 'text', 'fill', 'z', 'contours', 'showlegend', 'hoverinfo', 'stackgroup']) if (d[k] !== undefined) o[k] = d[k];
        o.color = d.line && d.line.color; o.dash = d.line && d.line.dash; o.shape = d.line && d.line.shape; o.mcolor = d.marker && d.marker.color; return o; };
      return { label: p.getAttribute('aria-label'), code: n && n.matches('details.sm-code, .sm-code-box') ? n.querySelector('code').textContent : null,
        traces: (p.data || []).map(pick), shapes: (L.shapes || []).map((s) => ({ x0: s.x0, x1: s.x1, y0: s.y0, y1: s.y1, xref: s.xref, yref: s.yref, dash: s.line && s.line.dash })),
        titles: { x: t('xaxis'), y: t('yaxis'), x2: t('xaxis2'), y2: t('yaxis2') }, ticks: L.xaxis && L.xaxis.ticktext ? L.xaxis.ticktext : null,
        w: p._plot ? p._plot.ownWidth : null, h: p._plot ? p._plot.height : null };
    });
  },
  async run(code, table) { return SM.engine.runCell('charts', code, { tables: [table], current: table, label: 'chart', fresh: true }); },
};
'''


async def run_graph(page, g, table_js):
    """Run a graph's code block in the page (the notebook's runner); its
    figures, as PROBE gives them, or an error."""
    out = await page.ev(f'__gr.run({json.dumps(page_probe(g["code"]))}, {table_js})', timeout=300)
    if isinstance(out, str):
        return None, out
    return figures_from_outputs(out.get('outputs'))


def points_of(trace):
    """A Plotly trace's (x, y) points, without the gaps (None)."""
    return [(a, b) for a, b in zip(trace.get('x') or [], trace.get('y') or []) if a is not None and b is not None]


def close(a, b, rel=1e-9, abs_=1e-12):
    """Two numbers (or equal-length lists of numbers) equal within rel/abs."""
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        a, b = list(a or []), list(b or [])
        return len(a) == len(b) and all(close(x, y, rel, abs_) for x, y in zip(a, b))
    if a is None or b is None:
        return a is None and b is None
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def maxdiff(a, b):
    """The largest difference of two equal-length lists (inf when they differ in length or have gaps)."""
    a, b = list(a or []), list(b or [])
    if len(a) != len(b) or not a:
        return float('inf')
    d = 0.0
    for x, y in zip(a, b):
        if x is None or y is None:
            if (x is None) != (y is None):
                return float('inf')
            continue
        d = max(d, abs(float(x) - float(y)))
    return d


def find_line(ax, x=None, y=None, rel=1e-6, abs_=1e-9, **props):
    """The first line of an axes (from the probe) with these data and properties."""
    for ln in ax['lines']:
        if x is not None and not close(ln['x'], x, rel, abs_):
            continue
        if y is not None and not close(ln['y'], y, rel, abs_):
            continue
        if any(ln.get(k) != v for k, v in props.items()):
            continue
        return ln
    return None


def lines_labelled(ax, label):
    return [ln for ln in ax['lines'] if ln['label'] == label]


def run_snippet(code, frame, name, tmp):
    """Write frame as the page exports it (File > Export CSV), run the snippet
    there with matplotlib's Agg backend, and return (figures, error)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import warnings
    plt.close('all')
    frame.to_csv(os.path.join(tmp, f'{name}.csv'), index=False)
    ns = {'__name__': '__main__'}
    here = os.getcwd()
    os.chdir(tmp)
    try:
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter('ignore')     # Agg's "non-interactive" note at plt.show(), convergence notes
            exec(code, ns)
            exec(PROBE, ns)
            figs = ns['_smui_figures']()
        return figs, None
    except Exception as e:  # reported as a failed check
        import traceback
        return None, f'{type(e).__name__}: {e}\n{traceback.format_exc(limit=-3)}'
    finally:
        os.chdir(here)
        plt.close('all')


# ---------------------------------------------------------------------------
# the native checks
# ---------------------------------------------------------------------------

def main():
    import numpy as np
    import pandas as pd
    from scipy import stats
    from backend import Checks, call, data, table

    check = Checks()
    tmp = tempfile.mkdtemp(prefix='smui-charts-')

    def frame_of(tid):
        """The table as File > Export CSV writes it: every column, by name."""
        t = data.TABLES[tid]
        cols = {}
        for name, v in t['cols'].items():
            m = t['meta'][name]
            cols[name] = np.asarray(v, dtype=float) if m.get('dataType') == 'numeric' else pd.Series(list(v), dtype=object)
        return pd.DataFrame(cols)

    def run(label, code, tid, name='data'):
        figs, err = run_snippet(code, frame_of(tid), name, tmp)
        check(f'{label}: the code runs', err, None)
        check(f'{label}: it ends with plt.show()', code.rstrip().split('\n')[-1], 'plt.show()')
        check(f'{label}: one figure', len(figs or []), 1)
        return figs[0] if figs else {'axes': [{'lines': [], 'bars': [], 'scatter': [], 'polys': [], 'patches': [], 'texts': [], 'segments': [], 'legend': [], 'title': '', 'xlabel': '', 'ylabel': '', 'xticklabels': [], 'yticklabels': []}], 'suptitle': ''}

    for section in (distribution_checks, fit_y_by_x_checks, fit_model_checks):
        section(check, run, np, pd, stats, call, table, data)
    return check.done()


# ---- Distribution ------------------------------------------------------------

def distribution_checks(check, run, np, pd, stats, call, table, data):
    rng = np.random.default_rng(20260928)
    x = rng.normal(50, 7, 83)
    x[5] = np.nan
    g = rng.choice(['b', 'a', 'c'], 83, p=[0.5, 0.3, 0.2]).tolist()
    g[7] = None
    w = rng.uniform(0.5, 2, 83)
    w[9] = 0.0
    tid = table({'x': x, 'g': g, 'w': w}, levels={'g': ['c', 'a', 'b']}, tid='charts1')
    rows = [r for r in range(83) if r not in (3, 11, 40)]          # three rows excluded in the page
    xs = x[rows]
    xs = xs[np.isfinite(xs)]

    # ---- Normal Quantile Plot
    for prob in (False, True):
        q = call('distribution.qq', table=tid, column='x', rows=rows, prob_axis=prob, table_name='data')
        F = run(f'normal quantile plot{" (probability axis)" if prob else ""}', q['plot_code'], tid)
        ax = F['axes'][0]
        pts = ax['scatter'][0]['xy'] if ax['scatter'] else []
        check.near('NQP: the points are the report\'s (z, x)', max(abs(a - b) for (a, b), za, xa in zip(pts, q['z'], q['x']) for a, b in [(a - za, b - xa)]) if len(pts) == len(q['z']) else 1e9, 0.0, abs_=1e-9)
        zmin, zmax = min(q['z']), max(q['z'])
        check('NQP: the normal line is mean ± sd·z', find_line(ax, [zmin, zmax], [q['mean'] + q['sd'] * zmin, q['mean'] + q['sd'] * zmax]) is not None, True)
        check('NQP: labels and title', (ax['xlabel'], ax['ylabel'], ax['title']), ('Normal Quantile Plot (probability)' if prob else 'Normal Quantile', 'x', 'x normal quantile plot'))
        if prob:
            check('NQP: the probability ticks', ax['xticklabels'][:3], ['0.01', '0.05', '0.1'])
            check.near('NQP: the tick of 0.5 at z = 0', ax['xticks'][4], 0.0, abs_=1e-12)

    # ---- the bar chart of a categorical column
    labels = ['c', 'a', 'b']
    for opts in ({'order': None, 'prob': False, 'horizontal': False}, {'order': 'desc', 'prob': True, 'horizontal': False, 'counts': True},
                 {'order': 'asc', 'prob': False, 'horizontal': True, 'percents': True}, {'order': None, 'prob': False, 'horizontal': False, 'weighted': True}):
        weighted = opts.pop('weighted', False)
        plot = {**opts, 'labels': labels}
        r = call('distribution.categorical', table=tid, column='g', rows=rows, weight='w' if weighted else None, plot=plot, table_name='data')
        lv = [(l['level'], l['count'], l['prob']) for l in r['levels']]
        if opts['order'] == 'desc':
            lv.sort(key=lambda t: -t[1])
        elif opts['order'] == 'asc':
            lv.sort(key=lambda t: t[1])
        tag = f'bar chart ({opts["order"] or "table order"}, {"prob" if opts["prob"] else "count"}, {"horizontal" if opts["horizontal"] else "vertical"}{", weighted" if weighted else ""})'
        F = run(tag, r['plot_code'], tid)
        ax = F['axes'][0]
        hs = [b['h'] if opts['horizontal'] else b['w'] for b in ax['bars']]
        want = [p if opts['prob'] else c for _, c, p in lv]
        check(f'{tag}: a bar for each level', len(hs), len(want))
        check.near(f'{tag}: the bars are the report\'s {"probabilities" if opts["prob"] else "counts"}', max(abs(a - b) for a, b in zip(hs, want)) if len(hs) == len(want) else 1e9, 0.0, abs_=1e-12)
        ticks = ax['xticklabels'] if opts['horizontal'] else ax['yticklabels']
        check(f'{tag}: the levels in the page\'s order', [t for t in ticks if t], [l for l, _, _ in lv])
        check(f'{tag}: labels and title', (ax['xlabel'], ax['ylabel'], ax['title']),
              ('g', 'Probability' if opts['prob'] else 'Count', 'g bar chart') if opts['horizontal'] else ('Probability' if opts['prob'] else 'Count', 'g', 'g bar chart'))
        if not opts['horizontal']:
            check(f'{tag}: the first level at the top', ax['yinverted'], True)
        if opts.get('counts') or opts.get('percents'):
            texts = [t['s'] for t in ax['texts']]
            wtxt = [f'{c:.7g}' for _, c, _ in lv] if opts.get('counts') else [f'{100 * p:.1f}%' for _, _, p in lv]
            check(f'{tag}: the text on the bars', texts, wtxt)
        # the mosaic of the same levels
        F = run(f'mosaic ({opts["order"] or "table order"})', r['mosaic_code'], tid)
        ax = F['axes'][0]
        tops = [b['y'] + b['h'] for b in ax['bars']]
        cum = list(np.cumsum([p for _, _, p in lv]))
        check.near(f'mosaic ({opts["order"] or "table order"}): the stacked probabilities', max(abs(a - b) for a, b in zip(tops, cum)) if len(tops) == len(cum) else 1e9, 0.0, abs_=1e-12)
        check(f'mosaic ({opts["order"] or "table order"}): the legend, top level first', ax['legend'], [l for l, _, _ in lv][::-1])
        check(f'mosaic ({opts["order"] or "table order"}): the colours of the palette', [b['fc'][:7] for b in ax['bars']], ['#2f6690', '#d9822b', '#3a7d44'][:len(lv)])

    # ---- the fitted curves' code (the histogram's own snippet is the page's)
    pos = rng.gamma(3, 2, 90)
    unit = rng.beta(2, 5, 90)
    mix = np.concatenate([rng.normal(10, 1, 50), rng.normal(16, 1.5, 40)])
    cnt = rng.negative_binomial(3, 0.4, 90).astype(float)
    tid2 = table({'pos': pos, 'unit': unit, 'mix': mix, 'cnt': cnt}, tid='charts2')
    vals = {'pos': pos, 'unit': unit, 'mix': mix, 'cnt': cnt}
    cases = [('pos', d) for d in ['normal', 'lognormal', 'weibull', 'exponential', 'gamma', 'logistic', 'cauchy', 't', 'johnsonsu', 'johnsonsb', 'kde']]
    cases += [('unit', 'beta'), ('mix', 'normal2'), ('mix', 'normal3'), ('cnt', 'poisson'), ('cnt', 'negbin')]
    from scipy import optimize
    import warnings
    for colname, dist in cases:
        r = call('distribution.fit', table=tid2, column=colname, dist=dist)
        ns = {'np': np, 'stats': stats, 'optimize': optimize, 'xf': vals[colname]}
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                exec('\n'.join(r['curve_code']), ns)
            err = None
        except Exception as e:  # noqa: BLE001
            err = f'{type(e).__name__}: {e}'
        check(f'fit {dist}: its curve code runs', err, None)
        want = r['curve'].get('pdf') or r['curve'].get('pmf')
        check.near(f'fit {dist}: the grid is the report\'s', float(np.max(np.abs(np.asarray(ns.get('g', [np.inf]), float) - np.asarray(r['curve']['x'], float)))), 0.0, abs_=1e-12)
        tol = 1e-4
        check.near(f'fit {dist}: the density is the report\'s curve', float(np.max(np.abs(np.asarray(ns.get('f', [np.inf]), float) - np.asarray(want, float))) / max(want)), 0.0, abs_=tol)


# ---- Fit Y by X ------------------------------------------------------------------

def fit_y_by_x_checks(check, run, np, pd, stats, call, table, data):
    import warnings
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    rng = np.random.default_rng(20260929)
    n = 90
    x = rng.uniform(1, 10, n).round(1)
    y = 3 + 0.8 * x - 0.05 * x ** 2 + rng.normal(0, 0.8, n)
    y[3] = np.nan
    w = rng.uniform(0.5, 2, n)
    f = rng.integers(1, 4, n).astype(float)
    f[5] = 0
    grp = rng.choice(['lo', 'mid', 'hi'], n).tolist()
    blk = rng.choice(['b1', 'b2', 'b3'], n).tolist()
    yy = [('yes' if rng.uniform() < 1 / (1 + np.exp(-(xi - 5))) else 'no') for xi in x]
    ord3 = [('low' if v < 4 else 'high' if v > 7 else 'middle') if rng.uniform() > 0.2 else 'middle' for v in x]
    tid = table({'x': x, 'y': y, 'w': w, 'f': f, 'grp': grp, 'blk': blk, 'resp': yy, 'lvl': ord3},
                types={'lvl': 'ordinal'}, levels={'grp': ['lo', 'mid', 'hi'], 'blk': ['b1', 'b2', 'b3'], 'resp': ['yes', 'no'], 'lvl': ['low', 'middle', 'high']}, tid='charts3')
    frame = pd.DataFrame({'x': x, 'y': y, 'w': w, 'f': f, 'grp': grp})

    def pair(weight, freq):
        cols = [c for c in ['x', 'y', weight, freq] if c]
        d = frame.dropna(subset=cols)
        wt = np.ones(len(d))
        for c in (weight, freq):
            if c:
                wt = wt * d[c]
        return d[wt > 0] if (weight or freq) else d

    def md(a, b):
        a, b = np.asarray(a, float), np.asarray(b, float)
        return float(np.nanmax(np.abs(a - b))) if a.shape == b.shape and a.size else float('inf')

    # ---- the Bivariate fits' fragments (the page puts the graph together): the curve, the bands and the predictions
    cases = [('fit_poly', {'degree': 1}, 'Linear Fit'), ('fit_poly', {'degree': 3}, 'Polynomial'), ('fit_mean', {}, 'Fit Mean'),
             ('fit_special', {'ytr': 'log', 'xtr': 'sqrt', 'degree': 2}, 'Transformed Log to Sqrt'), ('fit_special', {'ytr': 'reciprocal', 'xtr': 'none', 'degree': 1}, 'Transformed Recip'),
             ('fit_special', {'ytr': 'none', 'xtr': 'none', 'intercept': 1.0}, 'Constrained intercept'), ('fit_special', {'ytr': 'sqrt', 'xtr': 'log', 'slope': 0.5}, 'Constrained slope'),
             ('fit_special', {'ytr': 'none', 'xtr': 'square', 'intercept': 1.0, 'slope': 0.1}, 'Constrained both'),
             ('fit_spline', {'lam': 5.0}, 'Spline λ=5'), ('fit_spline', {'lam': None, 'standardize': True}, 'Spline by GCV, standardized'),
             ('fit_lowess', {'frac': 0.5, 'it': 1}, 'Kernel Smoother'), ('fit_each', {}, 'Fit Each Value'), ('fit_robust', {'method': 'huber'}, 'Robust'),
             ('fit_robust', {'method': 'bisquare'}, 'Robust Bisquare'), ('fit_orthogonal', {'mode': 'univariate'}, 'Orthogonal'),
             ('fit_orthogonal', {'mode': 'ratio', 'ratio': 2.5}, 'Orthogonal ratio 2.5'), ('density_ellipse', {'levels': [0.9]}, 'Density Ellipse'),
             ('nonpar_density', {}, 'Nonpar Density'), ('fit_quantile', {'tau': 0.25}, 'Quantile τ=0.25')]
    for weight, freq in ((None, None), ('w', 'f')):
        tag = ' (Weight and Freq)' if weight else ''
        for fn, args, label in cases:
            payload = dict(args)
            if fn not in ('fit_orthogonal', 'density_ellipse', 'nonpar_density'):
                payload['want_rows'] = True
            r = call(f'fitybyx.{fn}', table=tid, y='y', x='x', weight=weight, freq=freq, **payload)
            p = r.get('plot') or {'imports': [], 'fit': [], 'pred': []}
            ns = {'np': np, 'pd': pd, 'sm': sm, 'smf': smf, 's': pair(weight, freq)}
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    exec('\n'.join(p['imports'] + p['fit'] + p['pred']), ns)
                err = None
            except Exception as e:  # noqa: BLE001
                err = f'{type(e).__name__}: {e}'
            check(f'{label}{tag}: the fragment runs', err, None)
            tol = 1e-4 if fn == 'fit_spline' and args.get('lam') is None else 1e-9
            if 'curve' in r:
                cv = r['curve']
                if fn == 'fit_lowess':      # the report's curve is thinned to unique X
                    check.near(f'{label}{tag}: the curve is the report\'s', md(np.interp(cv['x'], ns.get('gx', [0]), ns.get('fy', [0])), cv['fit']), 0.0, abs_=1e-9)
                else:
                    check.near(f'{label}{tag}: the curve is the report\'s', max(md(ns.get('gx'), cv['x']), md(ns.get('fy'), cv['fit'])), 0.0, abs_=tol)
                bands = [k for k in ('lo_fit', 'hi_fit', 'lo_ind', 'hi_ind') if k in cv]
                if bands:
                    check.near(f'{label}{tag}: the confidence bands are the report\'s', max(md(ns.get(k), cv[k]) for k in bands), 0.0, abs_=1e-9)
            if 'ellipses' in r:
                e0 = r['ellipses'][0]
                check.near(f'{label}{tag}: the ellipse is the report\'s', max(md(ns.get('ex'), e0['x']), md(ns.get('ey'), e0['y'])), 0.0, abs_=1e-9)
            if fn == 'nonpar_density':
                check.near(f'{label}{tag}: the density grid and its levels are the report\'s', max(md(ns.get('Z'), r['z']), md(ns.get('levels'), [q['value'] for q in r['levels']])), 0.0, abs_=1e-12)
            if r.get('row_values') and p['pred']:
                check.near(f'{label}{tag}: the predictions (for the diagnostics plots) are the report\'s', md(ns.get('pred'), r['row_values']['predicted']), 0.0, abs_=tol)

    # ---- Oneway: the points by level and every overlay
    labels = ['lo', 'mid', 'hi']
    everything = {'points': True, 'jitter': True, 'box': True, 'diamonds': True, 'meanLines': True, 'errorBars': True, 'sdLines': True, 'ciLines': True,
                  'grandMean': True, 'connect': True, 'labels': labels, 'width': 600, 'height': 380}
    for weight, freq, block, circ in ((None, None, None, {'method': 'tukey'}), ('w', 'f', None, {'method': 'student'}), (None, 'f', None, {'method': 'dunnett', 'control': 'mid'}), (None, None, 'blk', None)):
        tag = f'Oneway ({", ".join(v for v in (weight, freq) if v) or "unweighted"}{", block" if block else ""}{", circles " + circ["method"] if circ else ""})'
        plot = {**everything, 'circles': circ}
        r = call('fitybyx.oneway', table=tid, y='y', x='grp', weight=weight, freq=freq, block=block, plot=plot, table_name='data')
        F = run(tag, r['plot_code'], tid)
        ax = F['axes'][0]
        L = r['levels']
        k = len(L)
        check(f'{tag}: the levels on the axis', ([t for t in ax['xticklabels'] if t], ax['xticks']), (labels, [0.0, 1.0, 2.0]))
        pts = ax['scatter'][0]['xy'] if ax['scatter'] else []
        check(f'{tag}: a point for each row', len(pts), r['n_rows'])
        check(f'{tag}: each point within its level\'s jitter', all(abs(px - round(px)) <= 0.23 + 1e-12 for px, _ in pts), True)
        vals = sorted(py for _, py in pts)
        want = sorted(frame.loc[pair(weight, freq).index.intersection(frame.dropna(subset=['y']).index), 'y'])
        check.near(f'{tag}: the points are the rows\' values', md(vals, want), 0.0, abs_=1e-12)
        # the box plots: bxp's medians, boxes and whiskers
        meds = [ln for ln in ax['lines'] if len(ln['y']) == 2 and ln['y'][0] == ln['y'][1] and abs((ln['x'][1] or 0) - (ln['x'][0] or 0) - 0.28) < 1e-9]
        check.near(f'{tag}: the medians of the box plots', md(sorted(m['y'][0] for m in meds), sorted(l['median'] for l in L)), 0.0, abs_=1e-12)
        ys = [ln['y'] for ln in ax['lines']]
        check(f'{tag}: the whiskers to the fences', all(any(close(v, [l['q25'], l['lo_fence']]) for v in ys) and any(close(v, [l['q75'], l['hi_fence']]) for v in ys) for l in L), True)
        # the means diamonds (least squares means with a block)
        for l in L:
            m, lo, hi = (l['lsmean'], l['lower_lsmean'], l['upper_lsmean']) if block else (l['mean'], l['lower_pooled'], l['upper_pooled'])
            wdt = 0.08 + 0.3 * l['n'] / max(q['n'] for q in L)
            i = l['index']
            check(f'{tag}: the diamond of {labels[i]}', find_line(ax, [i - wdt, i, i + wdt, i, i - wdt], [m, hi, m, lo, m], rel=1e-9) is not None, True)
        segs = [s for c in ax['segments'] for s in c['segs']]

        def has_seg(x0, x1, y0, y1):
            return any(close(s[0], [x0, y0], 1e-9, 1e-9) and close(s[1], [x1, y1], 1e-9, 1e-9) for s in segs)
        check(f'{tag}: the mean lines', all(has_seg(l['index'] - 0.3, l['index'] + 0.3, l['mean_raw'], l['mean_raw']) for l in L), True)
        check(f'{tag}: the error bars: ± one standard error', all(has_seg(l['index'] + 0.18, l['index'] + 0.18, l['mean_raw'] - l['se'], l['mean_raw'] + l['se']) for l in L), True)
        check(f'{tag}: the standard deviation lines', all(has_seg(l['index'] - 0.24, l['index'] + 0.24, l['mean_raw'] + l['sd'], l['mean_raw'] + l['sd']) for l in L), True)
        check(f'{tag}: the confidence interval lines', all(has_seg(l['index'] - 0.2, l['index'] + 0.2, l['upper_pooled'], l['upper_pooled']) for l in L), True)
        check(f'{tag}: the grand mean', find_line(ax, None, [r['grand_mean'], r['grand_mean']], rel=1e-12) is not None, True)
        check(f'{tag}: the connected means', find_line(ax, list(range(k)), [l['mean'] for l in L], rel=1e-12) is not None, True)
        check(f'{tag}: the title and the size', (F['suptitle'] if circ else ax['title'], F['size']), ('y by grp', [6.0, 3.8]))
        if circ:
            cmp = call('fitybyx.oneway_compare', table=tid, y='y', x='grp', weight=weight, freq=freq, method=circ['method'], control=circ.get('control'))
            cx = F['axes'][1]
            ells = [p for p in cx['patches'] if p['type'] == 'ellipse']
            want_r = [cmp['quantile']['value'] * math.sqrt(cmp['mse'] / cmp['n'][i]) for i in range(k)]
            check.near(f'{tag}: the circles\' radii, q*·√(MSE/n)', md([e['h'] / 2 for e in ells], want_r), 0.0, abs_=1e-9)
            check.near(f'{tag}: the circles\' centres, the level means', md([e['center'][1] for e in ells], cmp['means']), 0.0, abs_=1e-9)
            check(f'{tag}: the circles are round on the page', all(abs(e['w'] / e['h'] - ells[0]['w'] / ells[0]['h']) < 1e-9 for e in ells) and 0 < ells[0]['w'] < 2.1, True)

    # ---- Analysis of Means, Densities
    for weight, freq in ((None, None), (None, 'f')):
        r = call('fitybyx.oneway_anom', table=tid, y='y', x='grp', weight=weight, freq=freq, labels=labels)
        tag = f'ANOM{" (Freq)" if freq else ""}'
        F = run(tag, r['plot_code'], tid)
        ax = F['axes'][0]
        segs = [s for c in ax['segments'] for s in c['segs']]
        lims = sorted(s[0][1] for s in segs)
        check.near(f'{tag}: the decision limits', md(lims, sorted([l['ldl'] for l in r['levels']] + [l['udl'] for l in r['levels']])), 0.0, abs_=1e-7)
        pts = ax['scatter'][0]['xy'] if ax['scatter'] else []
        check.near(f'{tag}: the level means', md([q[1] for q in pts], [l['mean'] for l in r['levels']]), 0.0, abs_=1e-12)
        check(f'{tag}: the grand mean', find_line(ax, None, [r['grand_mean']] * 2, rel=1e-12) is not None, True)
        check(f'{tag}: the levels, the title', ([t for t in ax['xticklabels'] if t], ax['ylabel'], ax['title']), (labels, 'Mean', 'Analysis of Means'))
    for mode in ('compare', 'composition', 'proportion'):
        r = call('fitybyx.oneway_densities', table=tid, y='y', x='grp', freq='f', mode=mode, labels=labels)
        F = run(f'Densities ({mode})', r['plot_code'], tid)
        ax = F['axes'][0]
        Ls = [l for l in r['levels'] if l['density']]
        if mode == 'compare':
            got = [ln['y'] for ln in ax['lines']]
            check.near('Densities (compare): each level\'s density', max(md(g_, l['density']) for g_, l in zip(got, Ls)) if len(got) == len(Ls) else 1e9, 0.0, abs_=1e-12)
        else:
            parts = [np.asarray(l['share']) * np.asarray(l['density']) for l in Ls]
            tot = np.sum(parts, axis=0)
            if mode == 'proportion':
                parts = [np.where(tot > 0, p_ / tot, 0) for p_ in parts]
            cum = np.cumsum(parts, axis=0)
            tops = [max(q[1] for q in poly['paths'][0]) for poly in ax['polys']]
            check.near(f'Densities ({mode}): the stacked shares', md(tops, [c_.max() for c_ in cum]), 0.0, abs_=1e-9)
        check(f'Densities ({mode}): the titles', (ax['xlabel'], ax['ylabel'], ax['title']), ('y', 'Proportion' if mode == 'proportion' else 'Density', 'Densities'))

    # ---- Logistic: the logistic plot, ROC and lift
    for yname, weight, freq in (('resp', None, None), ('resp', 'w', 'f'), ('grp', None, 'f'), ('lvl', None, None)):
        r = call('fitybyx.logistic', table=tid, y=yname, x='x', weight=weight, freq=freq)
        tag = f'logistic {yname} ({r["kind"]}{", weighted" if weight or freq else ""})'
        F = run(f'{tag} plot', r['plot_code'], tid)
        ax = F['axes'][0]
        cum = np.asarray(r['curve']['cum'], float)
        got = [ln['y'] for ln in ax['lines']]
        check(f'{tag}: a curve for each level but the last', len(got), r['k'] - 1)
        check.near(f'{tag}: the cumulative probabilities are the report\'s', max(md(g_, c_) for g_, c_ in zip(got, cum)) if len(got) == len(cum) else 1e9, 0.0, abs_=1e-6)
        check(f'{tag}: the levels named at the right', [t['s'] for t in ax['texts']], [str(v) for v in r['levels']])
        # every point inside its level's band at its X
        pts = ax['scatter'][0]['xy'] if ax['scatter'] else []
        model = r['model']

        def probs_at(v):
            if model['kind'] == 'binary':
                a, b = model['coef']
                p0 = 1 / (1 + math.exp(-(a + b * v)))
                return [p0, 1 - p0]
            if model['kind'] == 'nominal':
                eta = [a + b * v for a, b in model['coef']] + [0.0]
                mx = max(eta)
                ex = [math.exp(e - mx) for e in eta]
                return [e / sum(ex) for e in ex]
            cm_ = [1 / (1 + math.exp(-(a + model['beta'] * v))) for a in model['alpha']] + [1.0]
            return [c_ - (cm_[i - 1] if i else 0) for i, c_ in enumerate(cm_)]
        colors = ax['scatter'][0]['colors'] if ax['scatter'] else []
        pal = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b']
        inside = True
        for (px, py), col_ in zip(pts, colors):
            j = pal.index(col_[:7]) if col_ and col_[:7] in pal else -1
            pr = probs_at(px)
            lo = sum(pr[:j])
            inside = inside and j >= 0 and lo + 0.06 * pr[j] - 1e-6 <= py <= lo + 0.94 * pr[j] + 1e-6
        check(f'{tag}: each row in its level\'s band, in its level\'s colour', (len(pts) > 0, inside), (True, True))
        check(f'{tag}: the titles', (ax['xlabel'], ax['ylabel'], ax['title'], ax['ylim']), ('x', yname, f'{yname} by x logistic plot', [0.0, 1.0]))
        F = run(f'{tag} ROC', r['roc_code'], tid)
        ax = F['axes'][0]
        for q, ln in zip(r['roc'], ax['lines']):
            ok = max(md(ln['x'], q['fpr']), md(ln['y'], q['tpr'])) < 1e-12     # fewer than 400 points: the report's curve is not thinned
            check(f'{tag} ROC of level {q["level"]}: the curve is the report\'s, AUC in the legend', (bool(ok), f'(AUC {q["auc"]:.4f})' in (F['legend'] or [''] * 9)[r['roc'].index(q)]), (True, True))
        F = run(f'{tag} lift', r['lift_code'], tid)
        ax = F['axes'][0]
        for q, ln in zip(r['lift'], [l_ for l_ in ax['lines'] if l_['label'] and not l_['label'].startswith('_')]):
            check.near(f'{tag} lift of level {q["level"]}: the curve is the report\'s', md(np.interp(q['portion'], ln['x'], ln['y']), q['lift']), 0.0, abs_=1e-9)

    # ---- Contingency: the mosaic, ANOM for proportions, correspondence analysis
    for weight, freq in ((None, None), ('w', 'f')):
        tag = f'mosaic{" (Weight and Freq)" if weight else ""}'
        r = call('fitybyx.contingency', table=tid, y='grp', x='blk', weight=weight, freq=freq)
        F = run(tag, r['plot_code'], tid)
        ax = F['axes'][0]
        cnt = np.asarray(r['counts'], float)
        R, C = cnt.shape
        N = cnt.sum()
        bars = ax['bars']
        cells = bars[:R * C]
        want_h = [cnt[i, j] / cnt[i].sum() for i in range(R) for j in range(C)]
        check.near(f'{tag}: the heights are the shares of Y in each X level', md([b['h'] for b in cells], want_h), 0.0, abs_=1e-12)
        avail = 1 - 0.012 * (R - 1)
        want_w = [avail * cnt[i].sum() / N for i in range(R) for j in range(C)]
        check.near(f'{tag}: the widths are the X levels\' shares of the rows', md([b['w'] for b in cells], want_w), 0.0, abs_=1e-12)
        check.near(f'{tag}: the column on the right: Y\'s overall shares', md([b['h'] for b in bars[R * C:]], cnt.sum(0) / N), 0.0, abs_=1e-12)
        check(f'{tag}: the levels, the legend, the titles', ([t for t in ax['xticklabels'] if t], ax['legend'], ax['xlabel'], ax['ylabel'], ax['title']),
              (['b1', 'b2', 'b3', 'all'], ['hi', 'mid', 'lo'], 'blk', 'grp', 'grp by blk mosaic'))
    r = call('fitybyx.contingency_anomp', table=tid, y='resp', x='grp', freq='f')
    F = run('ANOM for proportions', r['plot_code'], tid)
    ax = F['axes'][0]
    segs = [s for c in ax['segments'] for s in c['segs']]
    check.near('ANOM for proportions: the decision limits', md(sorted(s[0][1] for s in segs), sorted([l['ldl'] for l in r['levels']] + [l['udl'] for l in r['levels']])), 0.0, abs_=1e-7)
    check.near('ANOM for proportions: the proportions', md([q[1] for q in ax['scatter'][0]['xy']], [l['p'] for l in r['levels']]), 0.0, abs_=1e-12)
    check('ANOM for proportions: the titles', (ax['xlabel'], ax['ylabel'], ax['title']), ('grp', 'Proportion of yes', 'Analysis of Means for Proportions'))
    r = call('fitybyx.contingency_ca', table=tid, y='grp', x='lvl', weight='w')
    F = run('correspondence analysis', r['plot_code'], tid)
    ax = F['axes'][0]
    got_rows, got_cols = ax['scatter'][0]['xy'], ax['scatter'][1]['xy']
    check.near('correspondence analysis: the X levels\' coordinates', md(got_rows, [[q['c1'], q['c2']] for q in r['rows']]), 0.0, abs_=1e-9)
    check.near('correspondence analysis: the Y levels\' coordinates', md(got_cols, [[q['c1'], q['c2']] for q in r['cols']]), 0.0, abs_=1e-9)
    check('correspondence analysis: the axes\' shares of inertia', (ax['xlabel'], ax['ylabel']), (f'c1 ({100 * r["details"][0]["portion"]:.1f}%)', f'c2 ({100 * r["details"][1]["portion"]:.1f}%)'))

# ---- Fit Model ------------------------------------------------------------------

def fit_model_checks(check, run, np, pd, stats, call, table, data):
    rng = np.random.default_rng(20260930)
    n = 64
    x1 = rng.uniform(0, 10, n).round(2)
    x2 = rng.normal(5, 2, n).round(2)
    g = rng.choice(['a', 'b', 'c'], n).tolist()
    h = rng.choice(['p', 'q'], n).tolist()
    w = rng.uniform(0.5, 2, n).round(3)
    f = rng.integers(1, 4, n).astype(float)
    f[7] = 0      # a row that no fit takes
    y = 2 + 0.5 * x1 + np.where(np.array(g) == 'b', 1.0, np.where(np.array(g) == 'c', -0.7, 0)) + 0.3 * x2 + rng.normal(0, 1, n)
    y[2] = np.nan
    cnt = rng.poisson(np.exp(0.2 + 0.15 * x1)).astype(float)
    tid = table({'y': y, 'x1': x1, 'x2': x2, 'g': g, 'h': h, 'w': w, 'f': f, 'cnt': cnt}, levels={'g': ['a', 'b', 'c'], 'h': ['p', 'q']}, tid='charts4')
    rows = [r for r in range(n) if r not in (5, 9)]

    def md(a, b):
        a, b = np.asarray(a, float), np.asarray(b, float)
        return float(np.nanmax(np.abs(a - b))) if a.shape == b.shape and a.size else float('inf')

    def pts(ax, k=0):
        return np.asarray(ax['scatter'][k]['xy'], float) if len(ax['scatter']) > k else np.zeros((0, 2))

    def ptext(p):
        return '<.0001' if p < 0.0001 else f'={p:.4f}'

    # ---- Standard Least Squares: every graph of the report
    for label, kw, effects in (('LS', {}, [['x1'], ['g'], ['x1', 'g']]), ('LS (Weight, Freq, rows left out)', {'weight': 'w', 'freq': 'f', 'rows': rows}, [['x1'], ['g'], ['x1', 'g']]),
                               ('LS (robust HC3, two factors)', {'robust': {'type': 'HC3'}}, [['x1'], ['x2'], ['g'], ['h'], ['g', 'h']]),
                               ('LS (one factor, robust HC1)', {'robust': {'type': 'HC1'}}, [['x1'], ['x1', 'x1']]), ('LS (clusters by h)', {'robust': {'type': 'cluster', 'cluster': 'h'}}, [['x1']])):
        r = call('fitmodel.ls', table=tid, y='y', effects=effects, alpha=0.05, leverage=True, ccpr=True, table_name='data', **kw)
        pc, dg, wh = r['plot_code'], r['diag'], r['whole']
        F = run(f'{label}: actual by predicted', pc['actpred'], tid)
        ax = F['axes'][0]
        P = pts(ax)
        check.near(f'{label}: actual by predicted: the points', max(md(P[:, 0], dg['predicted']), md(P[:, 1], dg['actual'])), 0.0, abs_=1e-9)
        lo, hi = min(min(dg['predicted']), min(dg['actual'])), max(max(dg['predicted']), max(dg['actual']))
        check(f'{label}: actual by predicted: the line of fit and the mean', (find_line(ax, [lo, hi], [lo, hi]) is not None, find_line(ax, [lo, hi], [wh['mean']] * 2) is not None), (True, True))
        if wh.get('curve'):
            cv = wh['curve']
            check(f'{label}: actual by predicted: Sall\'s confidence curves', (find_line(ax, cv['x'], cv['lower'], rel=1e-7) is not None, find_line(ax, cv['x'], cv['upper'], rel=1e-7) is not None), (True, True))
        check(f'{label}: actual by predicted: the titles', (ax['xlabel'], ax['ylabel'], ax['title']),
              (f'y Predicted P{ptext(wh["p"])} RSq={wh["rsq"]:.2f} RMSE={wh["rmse"]:.5g}', 'y Actual', 'y actual by predicted'))
        for key, xs, ys, xl, yl, title in (('residpred', dg['predicted'], dg['residual'], 'y Predicted', 'y Residual', 'y residual by predicted'),
                                           ('residrow', [q + 1 for q in dg['rows']], dg['residual'], 'Row Number', 'y Residual', 'y residual by row'),
                                           ('student', [q + 1 for q in dg['rows']], dg['externally'], 'Row Number', 'Externally Studentized Residuals', 'y studentized residuals')):
            F = run(f'{label}: {title}', pc[key], tid)
            ax = F['axes'][0]
            P = pts(ax)
            check.near(f'{label}: {title}: the points', max(md(P[:, 0], xs), md(P[:, 1], ys)), 0.0, abs_=1e-8)
            check(f'{label}: {title}: the titles', (ax['xlabel'], ax['ylabel'], ax['title']), (xl, yl, title))
            if key == 'student':
                lim = dg['limits']
                got = sorted(round(v, 9) for ln in ax['lines'] for v in ln['y'][:1])
                check(f'{label}: studentized residuals: the individual and the Bonferroni limits', all(any(abs(v - q) < 1e-9 for v in got) for q in (lim['individual'], -lim['individual'], lim['bonferroni'], -lim['bonferroni'])), True)
        F = run(f'{label}: residual normal quantile plot', pc['residqq'], tid)
        ax = F['axes'][0]
        e = np.asarray(dg['residual'], float)
        o = np.argsort(e, kind='stable')
        z = stats.norm.ppf(stats.rankdata(e) / (len(e) + 1))[o]
        P = pts(ax)
        check.near(f'{label}: residual normal quantile plot: the points', max(md(P[:, 0], z), md(P[:, 1], e[o])), 0.0, abs_=1e-9)
        check(f'{label}: residual normal quantile plot: the normal line', find_line(ax, [z.min(), z.max()], [e.mean() + e.std(ddof=1) * z.min(), e.mean() + e.std(ddof=1) * z.max()]) is not None, True)
        for L in r['leverage']:
            F = run(f'{label}: {L["effect"]} leverage plot', pc['leverage'][L['effect']], tid)
            ax = F['axes'][0]
            P = pts(ax)
            check.near(f'{label}: {L["effect"]} leverage plot: the points', max(md(P[:, 0], L['x']), md(P[:, 1], L['y'])), 0.0, abs_=1e-8)
            check(f'{label}: {L["effect"]} leverage plot: the line of fit and the mean', (find_line(ax, L['line']['x'], L['line']['y'], rel=1e-8) is not None, find_line(ax, L['line']['x'], [L['mean']] * 2, rel=1e-8) is not None), (True, True))
            if L.get('curve'):
                cv = L['curve']
                check(f'{label}: {L["effect"]} leverage plot: the confidence curves', (find_line(ax, cv['x'], cv['lower'], rel=1e-7) is not None, find_line(ax, cv['x'], cv['upper'], rel=1e-7) is not None), (True, True))
            check(f'{label}: {L["effect"]} leverage plot: the titles', (ax['xlabel'], ax['ylabel']), (f'{L["effect"]} Leverage, P{ptext(L["p"])}' + (' (usual F test)' if r.get('robust') else ''), 'y Leverage Residuals'))
        if 'regression' in pc:
            fac = [q for q in r['factors'] if q['type'] == 'continuous'][0]
            cat = [q for q in r['factors'] if q['type'] == 'categorical']
            F = run(f'{label}: regression plot', pc['regression'], tid)
            ax = F['axes'][0]
            base = {'y': 'y', 'effects': effects, **{k: v for k, v in kw.items() if k != 'rows'}}
            for i, lv in enumerate(cat[0]['levels'] if cat else [None]):
                prof = call('fitmodel.profile', table=tid, rows=kw.get('rows'), kind='ls', current={cat[0]['name']: lv} if cat else {}, alpha=0.05, grid=81, **base)
                tr = prof['responses'][0]['traces'][[q['name'] for q in r['factors']].index(fac['name'])]
                check(f'{label}: regression plot: the curve{" of " + str(lv) if cat else ""} is the profiler\'s', find_line(ax, tr['x'], tr['pred'], rel=1e-8) is not None, True)
                if not cat:
                    check(f'{label}: regression plot: the confidence band', (find_line(ax, tr['x'], tr['lower'], rel=1e-7) is not None, find_line(ax, tr['x'], tr['upper'], rel=1e-7) is not None), (True, True))
            check(f'{label}: regression plot: the rows', len(pts(ax)), len(dg['rows']))
        F = run(f'{label}: influence plot', pc['influence'], tid)
        ax = F['axes'][0]
        P = pts(ax)
        check.near(f'{label}: influence plot: the points (leverage, studentized residual)', max(md(P[:, 0], dg['hat']), md(P[:, 1], dg['externally'])), 0.0, abs_=1e-8)
        cd = np.nan_to_num(np.asarray(dg['cooks'], float))
        sizes = np.asarray(ax['scatter'][0]['sizes'], float)
        check.near(f'{label}: influence plot: the bubbles\' areas are Cook\'s D', md(sizes, np.maximum(599 * cd / cd.max(), 6.35)), 0.0, abs_=1e-6)
        for i, C in enumerate(r.get('ccpr') or []):
            F = run(f'{label}: {C["term"]} component plus residual', pc['ccpr'][i], tid)
            ax = F['axes'][0]
            P = pts(ax)
            check.near(f'{label}: {C["term"]} component plus residual: the points', max(md(P[:, 0], C['x']), md(P[:, 1], C['partial'])), 0.0, abs_=1e-9)
            check(f'{label}: {C["term"]} component plus residual: the line', find_line(ax, C['line']['x'], C['line']['y'], rel=1e-9) is not None, True)
        if 'sorted' in pc:
            F = run(f'{label}: sorted estimates', pc['sorted'], tid)
            ax = F['axes'][0]
            est = [q for q in r['estimates']['rows'] if q['term'] != 'Intercept']
            est = sorted(est, key=lambda q: -abs(q['t']))
            check(f'{label}: sorted estimates: the terms by |t|', [t_ for t_ in ax['yticklabels'] if t_], [q['term'] for q in est])
            check.near(f'{label}: sorted estimates: the t ratios', md([b['w'] for b in ax['bars']], [q['t'] for q in est]), 0.0, abs_=1e-9)
            check(f'{label}: sorted estimates: significant in red', [b['fc'][:7] for b in ax['bars']], ['#c0392b' if q['p'] < 0.05 else '#8fa9c2' for q in est])
        for eff, code in pc['lsmeans'].items():
            lsm = r['lsmeans'][eff]
            F = run(f'{label}: {eff} LS means plot', code, tid)
            ax = F['axes'][0]
            ys = sorted(v for ln in ax['lines'] if ln['marker'] == 'o' for v in ln['y'])
            check.near(f'{label}: {eff} LS means plot: the least squares means', md(ys, sorted(lsm['lsmean'])), 0.0, abs_=1e-9)
            bars = sorted(round(s_[1][1] - s_[0][1], 9) for c in ax['segments'] for s_ in c['segs'])
            check.near(f'{label}: {eff} LS means plot: the intervals, ± t·SE', md(bars, sorted(round(2 * r['tcrit'] * v, 9) for v in lsm['se'])), 0.0, abs_=1e-8)
            check(f'{label}: {eff} LS means plot: the titles', (ax['ylabel'], ax['title']), ('y LS Means', f'{eff} LS means plot'))

    # ---- Generalized Linear Model
    tidg = table({'cnt': cnt, 'x1': x1, 'g': g, 'w': w, 'f': f}, levels={'g': ['a', 'b', 'c']}, tid='charts5')
    for label, kw, effects in (('GLM Poisson', {'dist': 'poisson'}, [['x1']]), ('GLM Poisson (Weight, Freq, a factor)', {'dist': 'poisson', 'weight': 'w', 'freq': 'f'}, [['x1'], ['g']]),
                               ('GLM Poisson (robust HC0)', {'dist': 'poisson', 'robust': {'type': 'HC0'}}, [['x1']]), ('GLM negative binomial', {'dist': 'negbin'}, [['x1']])):
        r = call('fitmodel.glm', table=tidg, y='cnt', effects=effects, alpha=0.05, table_name='data', **kw)
        if r.get('error'):
            check(f'{label}: fits', r['error'], None)
            continue
        pc, dg = r['plot_code'], r['diag']
        for key, xs, ys in (('studDev', 'predicted', 'stud_dev'), ('studPearson', 'predicted', 'stud_pearson'), ('devPlot', 'predicted', 'resid_dev'),
                            ('pearPlot', 'predicted', 'resid_pearson'), ('actualPred', 'predicted', 'actual'), ('linPlot', 'linpred', 'actual')):
            F = run(f'{label}: {key}', pc[key], tidg)
            P = pts(F['axes'][0])
            check.near(f'{label}: {key}: the points', max(md(P[:, 0], dg[xs]), md(P[:, 1], dg[ys])), 0.0, abs_=1e-7)
        o = np.argsort(np.asarray(dg['linpred']), kind='stable')
        check(f'{label}: linear predictor plot: the fitted mean', find_line(F['axes'][0], list(np.asarray(dg['linpred'])[o]), list(np.asarray(dg['predicted'])[o]), rel=1e-7) is not None, True)
        if 'regression' in pc:
            F = run(f'{label}: regression plot', pc['regression'], tidg)
            ax = F['axes'][0]
            cat = [q for q in r['factors'] if q['type'] == 'categorical']
            base = {'y': 'cnt', 'effects': effects, **{k: v for k, v in kw.items()}}
            for lv in (cat[0]['levels'] if cat else [None]):
                prof = call('fitmodel.profile', table=tidg, kind='glm', current={cat[0]['name']: lv} if cat else {}, alpha=0.05, grid=81, link='log' if kw['dist'] in ('poisson', 'negbin') else None, **base)
                tr = prof['responses'][0]['traces'][[q['name'] for q in r['factors']].index('x1')]
                check(f'{label}: regression plot: the curve{" of " + str(lv) if cat else ""} is the profiler\'s', find_line(ax, tr['x'], tr['pred'], rel=1e-6) is not None, True)
                if not cat:
                    check(f'{label}: regression plot: the Wald band', (find_line(ax, tr['x'], tr['lower'], rel=1e-6) is not None, find_line(ax, tr['x'], tr['upper'], rel=1e-6) is not None), (True, True))
    # ---- Nominal and Ordinal Logistic
    yb = ['yes' if v > 3 + 0.4 * a else 'no' for v, a in zip(np.nan_to_num(y, nan=3.0), x1)]
    yo = ['low' if v < 3.5 else 'high' if v > 6 else 'mid' for v in np.nan_to_num(y, nan=4.0)]
    tidl = table({'yb': yb, 'yo': yo, 'g': g, 'x1': x1, 'f': f}, types={'yo': 'ordinal'}, levels={'yo': ['low', 'mid', 'high'], 'g': ['a', 'b', 'c'], 'yb': ['no', 'yes']}, tid='charts6')
    for label, yv, kw in (('logistic binary', 'yb', {}), ('logistic binary (Freq)', 'yb', {'freq': 'f'}), ('logistic nominal', 'g', {}), ('logistic ordinal', 'yo', {}), ('logistic ordinal (Freq)', 'yo', {'freq': 'f'})):
        r = call('fitmodel.logistic', table=tidl, y=yv, effects=[['x1']], alpha=0.05, table_name='data', **kw)
        pc = r['plot_code']
        F = run(f'{label}: logistic plot', pc['logistic'], tidl)
        ax = F['axes'][0]
        p = r['plot']
        for j, cv in enumerate(p['cum']):
            check(f'{label}: logistic plot: the curve of level {j + 1}', find_line(ax, p['x'], cv, rel=1e-7) is not None, True)
        P = pts(ax)
        check.near(f'{label}: logistic plot: the rows, placed as the report places them', max(md(P[:, 0], p['points']['x']), md(P[:, 1], p['points']['y'])), 0.0, abs_=1e-7)
        check(f'{label}: logistic plot: the levels at the right, the titles', ([t_['s'] for t_ in ax['texts']], ax['xlabel'], ax['ylabel'], ax['title']),
              (p['levels'], 'x1', f'{yv} (cumulative probability)', f'{yv} logistic plot'))
        F = run(f'{label}: ROC curve', pc['roc'], tidl)
        ax = F['axes'][0]
        for q, ln in zip(r['roc'], [l_ for l_ in ax['lines'] if not l_['label'].startswith('_')]):
            check.near(f'{label}: ROC of {q["level"]}', max(md(ln['x'], q['fpr']), md(ln['y'], q['tpr'])), 0.0, abs_=1e-9)
        check(f'{label}: ROC: the AUC in the legend', ax['legend'], [f'{q["level"]} (AUC {q["auc"]:.4f})' for q in r['roc']])
    # ---- Mixed Model, Instrumental Variables, Quantile Regression, GEE
    subj = [f's{i // 4:02d}' for i in range(n)]
    tt = [float(i % 4) for i in range(n)]
    ym = 1 + 0.8 * x1 + np.repeat(rng.normal(0, 0.7, n // 4), 4) + rng.normal(0, 0.5, n)
    zz = x2 + rng.normal(0, 0.5, n)
    xe = 0.7 * zz + rng.normal(0, 0.5, n)
    yiv = 1 + 0.5 * xe + 0.3 * x1 + rng.normal(0, 0.5, n)
    tidm = table({'ym': ym, 'x1': x1, 'g': g, 'subj': subj, 'tt': tt, 'zz': zz, 'xe': xe, 'yiv': yiv, 'yb': yb}, levels={'g': ['a', 'b', 'c'], 'yb': ['no', 'yes']}, tid='charts7')
    r = call('fitmodel.mixed', table=tidm, y='ym', effects=[{'names': ['x1']}, {'names': ['subj'], 'random': True}], alpha=0.05, table_name='data')
    pc, dg = r['plot_code'], r['diag']
    for key, xs, ys in (('actCond', 'predicted', 'actual'), ('actMarg', 'marginal', 'actual'), ('resCond', 'predicted', 'residual')):
        F = run(f'mixed: {key}', pc[key], tidm)
        P = pts(F['axes'][0])
        check.near(f'mixed: {key}: the points', max(md(P[:, 0], dg[xs]), md(P[:, 1], dg[ys])), 0.0, abs_=1e-6)
    r = call('fitmodel.iv', table=tidm, y='yiv', effects=[['xe'], ['x1']], endog=['xe'], instruments=['zz'], alpha=0.05, table_name='data')
    pc, dg = r['plot_code'], r['diag']
    for key, xs, ys in (('actual', dg['predicted'], dg['actual']), ('resid', dg['predicted'], dg['residual']), ('residRow', [q + 1 for q in dg['rows']], dg['residual'])):
        F = run(f'IV: {key}', pc[key], tidm)
        P = pts(F['axes'][0])
        check.near(f'IV: {key}: the points', max(md(P[:, 0], xs), md(P[:, 1], ys)), 0.0, abs_=1e-9)
    for label, kw, effects in (('QR', {'tau': 0.3}, [['x1']]), ('QR (Powell, a factor)', {'tau': 0.5, 'qr_cov': 'powell'}, [['x1'], ['g']])):
        r = call('fitmodel.quantreg', table=tidm, y='ym', effects=effects, taus=[0.25, 0.5, 0.75], alpha=0.05, table_name='data', **kw)
        pc, dg = r['plot_code'], r['diag']
        for key, ys in (('actual', dg['actual']), ('resid', dg['residual'])):
            F = run(f'{label}: {key}', pc[key], tidm)
            P = pts(F['axes'][0])
            check.near(f'{label}: {key}: the points', max(md(P[:, 0], dg['predicted']), md(P[:, 1], ys)), 0.0, abs_=1e-7)
        pr = r['process']
        for i, term in enumerate(pr['terms']):
            F = run(f'{label}: {term} quantile process', pc['process'][i], tidm)
            ax = F['axes'][0]
            est = [ln for ln in ax['lines'] if ln['marker'] == 'o'][0]
            check.near(f'{label}: {term} quantile process: the estimates', md(est['y'], pr['estimate'][i]), 0.0, abs_=1e-6)
            band = ax['polys'][0]['paths'][0]
            check.near(f'{label}: {term} quantile process: the band', max(abs(max(q_[1] for q_ in band) - max(pr['upper'][i])), abs(min(q_[1] for q_ in band) - min(pr['lower'][i]))), 0.0, abs_=1e-6)
            check.near(f'{label}: {term} quantile process: the least squares estimate', [ln['y'][0] for ln in ax['lines'] if ln['ls'] == '--'][0], r['ols']['estimate'][i], abs_=1e-9)
        if 'lines' in pc:
            F = run(f'{label}: quantile lines', pc['lines'], tidm)
            ax = F['axes'][0]
            L = r['lines']
            for q in L['lines']:
                ln = lines_labelled(ax, f'τ = {q["tau"]}')
                check.near(f'{label}: the line of τ = {q["tau"]}', md(ln[0]['y'] if ln else [], q['y']), 0.0, abs_=1e-6)
            check.near(f'{label}: the least squares line', md(lines_labelled(ax, 'Least squares')[0]['y'], L['ols']), 0.0, abs_=1e-9)
    for label, kw in (('GEE (AR(1))', {'y': 'ym', 'corr': 'ar1', 'time': 'tt'}), ('GEE (binomial, exchangeable)', {'y': 'yb', 'dist': 'binomial', 'corr': 'exchangeable'})):
        r = call('fitmodel.gee', table=tidm, effects=[['x1']], subject='subj', alpha=0.05, table_name='data', **kw)
        pc, dg = r['plot_code'], r['diag']

        def as_set(xs, ys):
            return sorted(zip(np.round(np.asarray(xs, float), 9), np.round(np.asarray(ys, float), 9)))
        for key, xs, ys in (('residPred', dg['predicted'], dg['residual']), ('actualPred', dg['predicted'], dg['actual'])):
            F = run(f'{label}: {key}', pc[key], tidm)
            P = pts(F['axes'][0])
            check(f'{label}: {key}: the points (in any order)', as_set(P[:, 0], P[:, 1]), as_set(xs, ys))
        for key in ('residSubject', 'residSubjectBoxes'):
            F = run(f'{label}: {key}', pc[key], tidm)
            ax = F['axes'][0]
            P = pts(ax)
            subjects = dg['subjects']
            check(f'{label}: {key}: each residual at its subject', as_set(P[:, 0], P[:, 1]), as_set([subjects.index(s_) for s_ in dg['subject']], dg['residual']))
            check(f'{label}: {key}: the subjects on the axis', [t_ for t_ in ax['xticklabels'] if t_], subjects)
        F = run(f'{label}: working correlation', pc['workcorr'], tidm)
        ax = F['axes'][0]
        M = r['dep']['matrix']
        got = [t_['s'] for t_ in ax['texts']]
        check(f'{label}: working correlation: the matrix of the subject the report shows', got, [f'{v:.2f}'.replace('-', '−') for row in M['values'] for v in row])
        check(f'{label}: working correlation: its labels', [t_ for t_ in ax['xticklabels'] if t_], M['labels'])
    # ---- Generalized Regression: the solution path and its curve
    Xg = rng.normal(0, 1, (n, 4)).round(3)
    yg = 1 + Xg @ np.array([1.0, 0.5, 0, -0.8]) + rng.normal(0, 1, n)
    wg = rng.uniform(0.5, 2, n).round(2)
    wg[[2, 7]] = 0   # rows the fit leaves out (a zero weight)
    tidr = table({**{f'z{i}': Xg[:, i] for i in range(4)}, 'yg': yg, 'wg': wg}, tid='charts8')
    for label, kw in (('GenReg lasso, AICc', {'method': 'lasso'}), ('GenReg elastic net, KFold', {'method': 'enet', 'criterion': 'kfold', 'folds': 4, 'seed': 5}),
                      ('GenReg forward, BIC', {'method': 'forward', 'criterion': 'bic'}), ('GenReg lasso, holdback', {'method': 'lasso', 'criterion': 'holdback', 'portion': 0.3, 'seed': 9}),
                      ('GenReg lasso, holdback, Weight with zeros', {'method': 'lasso', 'criterion': 'holdback', 'portion': 0.3, 'seed': 9, 'weight': 'wg'})):
        r = call('fitmodel.genreg', table=tidr, y='yg', effects=[[f'z{i}'] for i in range(4)], n_grid=20, table_name='data', **kw)
        p = r['path']
        F = run(f'{label}: solution path', r['plot_code']['path'], tidr)
        ax = F['axes'][0]
        got = [ln for ln in ax['lines'] if not ln['label'].startswith('_')]
        check.near(f'{label}: the estimates along the path', max(md(ln['y'], c['values']) for ln, c in zip(got, p['coefs'])) if len(got) == len(p['coefs']) else 1e9, 0.0, abs_=1e-6)
        check.near(f'{label}: the magnitude of the estimates (or the step)', md(got[0]['x'] if got else [], p['x']), 0.0, abs_=1e-6)
        vl = [ln['x'][0] for ln in ax['lines'] if ln['label'].startswith('_') and len(set(ln['x'])) == 1]
        check.near(f'{label}: the red line at the model shown', vl[0] if vl else 1e9, p['x'][r['chosen']], abs_=1e-6)
        F = run(f'{label}: {p["label"]} path', r['plot_code']['curve'], tidr)
        ax = F['axes'][0]
        check.near(f'{label}: the curve', md(ax['lines'][0]['y'], p['curve']) / max(1.0, max(abs(v) for v in p['curve'])), 0.0, abs_=1e-6)
        check(f'{label}: the titles', (ax['xlabel'], ax['ylabel'], ax['title']), (p['xlabel'], p['label'], f'{p["label"]} path'))
    # ---- Box-Cox, Recursive and Rolling Regression
    yp = np.exp(0.3 + 0.2 * x1 + rng.normal(0, 0.2, n))
    w0 = w.copy()
    w0[4] = 0   # a row the fit leaves out
    tidb = table({'yp': yp, 'x1': x1, 'g': g, 'w': w, 'w0': w0, 'o': rng.permutation(n).astype(float)}, levels={'g': ['a', 'b', 'c']}, tid='charts9')
    for kw in ({}, {'weight': 'w'}):
        r = call('fitmodel.boxcox', table=tidb, y='yp', effects=[['x1'], ['g']], alpha=0.05, table_name='data', **kw)
        F = run(f'Box-Cox{" (Weight)" if kw else ""}', r['plot_code'], tidb)
        ax = F['axes'][0]
        check.near(f'Box-Cox{" (Weight)" if kw else ""}: the SSE over λ', md(ax['lines'][0]['y'], r['sse']) / max(r['sse']), 0.0, abs_=1e-12)
        check.near(f'Box-Cox{" (Weight)" if kw else ""}: the best λ', ax['lines'][1]['x'][0], r['best'], abs_=1e-7)
        check.near(f'Box-Cox{" (Weight)" if kw else ""}: the interval of λ', md([ln['x'][0] for ln in ax['lines'][2:]], [v for v in r['ci'] if v is not None]), 0.0, abs_=1e-7)
    for label, kw in (('recursive', {}), ('recursive (sorted, 10%, rolling)', {'order_by': 'o', 'conf': 0.1, 'rolling': True, 'window': 16}),
                      ('recursive (Weight with a zero, rolling)', {'weight': 'w0', 'rolling': True, 'window': 16})):
        r = call('fitmodel.recursive', table=tidb, y='yp', effects=[['x1'], ['g']], alpha=0.05, table_name='data', **kw)
        pc = r['plot_code']
        for i, rec in enumerate(r['recursive']):
            F = run(f'{label}: {rec["term"]} recursive estimate', pc['recursive'][i], tidb)
            ax = F['axes'][0]
            est = [ln for ln in ax['lines'] if ln['marker'] == 'o'][0]
            check.near(f'{label}: {rec["term"]}: the recursive estimates', md(est['y'], rec['estimate']), 0.0, abs_=1e-9)
            check.near(f'{label}: {rec["term"]}: the estimate from all the rows', [ln['y'][0] for ln in ax['lines'] if ln['ls'] == '--'][0], rec['full'], abs_=1e-9)
        for key in ('cusum', 'cusumsq'):
            F = run(f'{label}: {key}', pc[key], tidb)
            ax = F['axes'][0]
            path_ = [ln for ln in ax['lines'] if ln['marker'] == 'o'][0]
            check.near(f'{label}: {key}: the path', md(path_['y'], r[key]['y']), 0.0, abs_=1e-9)
            bounds = [ln for ln in ax['lines'] if ln['ls'] == '--']
            check.near(f'{label}: {key}: the bounds', max(md(bounds[0]['y'], r[key]['upper']), md(bounds[1]['y'], r[key]['lower'])), 0.0, abs_=1e-9)
        for i, ro in enumerate((r.get('rolling') or {}).get('terms', [])):
            F = run(f'{label}: {ro["term"]} rolling estimate', pc['rolling'][i], tidb)
            ax = F['axes'][0]
            est = [ln for ln in ax['lines'] if ln['marker'] == 'o'][0]
            check.near(f'{label}: {ro["term"]}: the rolling estimates', md(est['y'], ro['estimate']), 0.0, abs_=1e-9)
    # ---- Interaction Plots: each personality's prediction, the other factors averaged
    # (tolerances: statsmodels' optimizers against the report's own fits)
    for label, kind, tbl, tol, kw in (
            ('LS (Weight, Freq with a zero)', 'ls', tid, 1e-9, {'y': 'y', 'effects': [['x1'], ['g'], ['h'], ['x1', 'g'], ['g', 'h']], 'weight': 'w', 'freq': 'f'}),
            ('LS (rows left out, two continuous)', 'ls', tid, 1e-9, {'y': 'y', 'effects': [['x1'], ['x2'], ['g'], ['x1', 'x2']], 'rows': rows}),
            ('GLM Poisson (Weight)', 'glm', tidg, 1e-7, {'y': 'cnt', 'effects': [['x1'], ['g'], ['x1', 'g']], 'dist': 'poisson', 'weight': 'w'}),
            ('GLM negative binomial', 'glm', tidg, 1e-5, {'y': 'cnt', 'effects': [['x1'], ['g']], 'dist': 'negbin'}),
            ('Logistic (two levels)', 'logistic', tidl, 1e-6, {'y': 'yb', 'effects': [['x1'], ['g']]}),
            ('Logistic (ordinal)', 'logistic', tidl, 1e-5, {'y': 'yo', 'effects': [['x1'], ['g']]}),
            ('Mixed', 'mixed', tidm, 1e-6, {'y': 'ym', 'effects': [{'names': ['x1']}, {'names': ['g']}, {'names': ['subj'], 'random': True}]}),
            ('GEE (exchangeable)', 'gee', tidm, 1e-7, {'y': 'ym', 'effects': [['x1'], ['g']], 'subject': 'subj', 'corr': 'exchangeable'}),
            ('GenReg lasso', 'genreg', tid, 1e-5, {'y': 'y', 'effects': [['x1'], ['x2'], ['g'], ['h']], 'n_grid': 20}),
            ('GenReg forward, holdback', 'genreg', tid, 1e-5, {'y': 'y', 'effects': [['x1'], ['g'], ['h']], 'method': 'forward', 'criterion': 'holdback', 'portion': 0.3, 'seed': 4})):
        r = call('fitmodel.interaction', table=tbl, kind=kind, table_name='data', **kw)
        k = len(r['factors'])
        F = run(f'interaction plots, {label}', r['plot_code'], tbl)
        axes = F['axes']
        check(f'interaction plots, {label}: a plot for each pair of factors, the names on the diagonal', (len(axes), [a['texts'][0]['s'] if a['texts'] and not a['visible'] else None for a in axes[::k + 1]]), (k * k, r['factors']))
        worst, labels, ticks = 0.0, [], []
        for cell in r['cells']:
            ax = axes[cell['row'] * k + cell['col']] if len(axes) == k * k else {'lines': [], 'texts': [], 'xticklabels': []}
            cat = r['types'][cell['col']] == 'categorical'
            xs = list(range(len(cell['x']))) if cat else cell['x']
            for q, ln in enumerate(cell['lines']):
                got = ax['lines'][q] if len(ax['lines']) > q else {'x': [], 'y': []}
                worst = max(worst, md(got['x'], xs), md(got['y'], ln['y']) / max(1.0, max(abs(v) for v in ln['y'])))
            labels.append([t['s'] for t in ax['texts']] == [ln['label'] for ln in cell['lines']])
            if cat:
                ticks.append([t for t in ax['xticklabels'] if t] == cell['x'])
        check.near(f'interaction plots, {label}: every line of every plot', worst, 0.0, abs_=tol)
        check(f'interaction plots, {label}: each line\'s label; the levels on a categorical axis', (all(labels), all(ticks)), (True, True))
        check(f'interaction plots, {label}: the title', F['suptitle'], 'interaction plots')


if __name__ == '__main__':
    sys.exit(main())
