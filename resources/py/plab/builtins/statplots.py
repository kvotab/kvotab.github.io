"""Statistical plots: boxplot, scatterhist, gscatter, gplotmatrix,
plotmatrix, histfit, normplot, qqplot, cdfplot, lsline, refline and
refcurve, and the plots the statistics functions draw when they are asked
for no outputs (ecdf, ksdensity, anova1, kruskalwallis, multcompare).

Each is made of the ordinary graphics objects (lines, patches, histograms
and bars), so get, set, findobj and legend work on its parts. The parts of
a box plot carry Tags: 'Box', 'Median', 'Upper Whisker', 'Lower Whisker',
'Upper Adjacent Value', 'Lower Adjacent Value' and 'Outliers'. The plots
made of several axes (scatterhist, gplotmatrix, plotmatrix) fill the
current figure.
"""
import math

import numpy as np

from . import bi
from ._util import err, nargchk, darr, out, opt_str, opt_lower, sval, num, is_str
from ..values import Char, Cell, Struct, Str, text_list
from ..graphics_base import Line, Patch, Series, Text, Legend, Axes, HArr, parse_linespec, to_color, COLOR_ORDER, MARKERS
from .graphics import gcf_, gca_, newplot, new_figure, split_axes_arg, set_current_axes, is_axes, clf, bar
from .statdesc import groups, _count
from .datafun import _quantiles, nice_edges


def _st():
    import scipy.stats as st
    return st


BLACK, RED, BLUE, WHITE = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 1.0, 1.0)


def _given(v):
    """An argument that is there and not empty ([] or '')."""
    if v is None:
        return False
    if type(v) in (Char, Cell, Str):
        return v.a.size > 0
    return np.size(v) > 0


def _nv(args, fn, known):
    """Name-value pairs: {lowercase name: value}; other names are errors."""
    opts = {}
    i = 0
    while i < len(args):
        s = opt_str(args[i])
        if s is None or i + 1 >= len(args):
            raise err('stats:NameValue', 'Options must come in name-value pairs.', fn)
        if s.lower() not in known:
            raise err('stats:BadOption', f"'{s}' is not an option of {fn}.", fn)
        opts[s.lower()] = args[i + 1]
        i += 2
    return opts


def _names(v):
    """Labels from text (a char matrix, a cellstr, a string array) or numbers."""
    if type(v) in (Char, Cell, Str):
        return [s.rstrip() for s in text_list(v)]
    return [f'{x:g}' for x in darr(v).real.reshape(-1)]


def _colors(spec, n, fn):
    """n colors: the axes' color order, color letters ('rgb', one for each
    group), a color name, a cell of names, or an m-by-3 matrix; cycled."""
    if not _given(spec):
        rows = [tuple(float(v) for v in r) for r in COLOR_ORDER]
    elif type(spec) in (Cell, Str) and not is_str(spec):
        rows = [to_color(Char.of(s)) for s in text_list(spec)]
    elif is_str(spec):
        s = sval(spec).strip()
        rows = [parse_linespec(c)[0] for c in s] if all(c in 'rgbcmykw' for c in s) else [to_color(spec)]
    else:
        a = darr(spec).real.astype(float)
        if a.ndim != 2 or a.shape[1] != 3 or np.any((a < 0) | (a > 1)):
            raise err('stats:BadColor', 'Colors must be color letters, color names or an m-by-3 matrix of values '
                      'between 0 and 1.', fn)
        rows = [tuple(float(v) for v in r) for r in a]
    return [rows[i % len(rows)] for i in range(n)]


def _markers(spec, n, default, fn):
    s = sval(spec) if _given(spec) and is_str(spec) else default
    if any(c not in MARKERS for c in s):
        raise err('stats:BadSymbol', f"'{s}' is not a string of marker symbols.", fn)
    return [s[i % len(s)] for i in range(n)]


def _sizes(spec, n, markers):
    if _given(spec):
        a = darr(spec).real.astype(float).reshape(-1)
        return [float(a[i % a.size]) for i in range(n)]
    return [15.0 if m == '.' else 6.0 for m in markers]


def _line(ax, x, y, color, style='-', marker='none', width=0.5, size=6.0, face='none', tag='', name=''):
    h = Line(ax)
    p = h.props
    p['XData'] = np.asarray(x, float).reshape(1, -1)
    p['YData'] = np.asarray(y, float).reshape(1, -1)
    p['Color'] = tuple(float(v) for v in color)
    p['LineStyle'] = style
    p['Marker'] = marker
    p['LineWidth'] = float(width)
    p['MarkerSize'] = float(size)
    p['MarkerFaceColor'] = face
    p['Tag'] = tag
    p['DisplayName'] = name
    return h


def _bars(ax, left, right, top, base, color, alpha=0.6):
    """Bars as one patch, a rectangle for each."""
    n = len(left)
    h = Patch(ax)
    h.props['XData'] = np.vstack([left, left, right, right]).astype(float)
    h.props['YData'] = np.vstack([np.full(n, base), top, top, np.full(n, base)]).astype(float)
    h.props['FaceColor'] = tuple(color)
    h.props['FaceAlpha'] = alpha
    h.props['EdgeColor'] = (0.15, 0.15, 0.15)
    return h


def _ticks(ax, which, ticks, labels):
    ax.props[which + 'Tick'] = np.asarray(ticks, float).reshape(1, -1)
    ax.props[which + 'TickMode'] = 'manual'
    ax.props[which + 'TickLabel'] = list(labels)
    ax.props[which + 'TickLabelMode'] = 'manual'


def _no_labels(ax, which):
    ax.props[which + 'TickLabel'] = []
    ax.props[which + 'TickLabelMode'] = 'manual'


def _lim(ax, which, lo, hi):
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return
    if hi <= lo:
        lo, hi = lo - 0.5, hi + 0.5
    ax.props[which + 'Lim'] = np.array([[float(lo), float(hi)]])
    ax.props[which + 'LimMode'] = 'manual'


def _padded(v, frac=0.05):
    """The range of v with a margin."""
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    if not v.size:
        return 0.0, 1.0
    lo, hi = float(v.min()), float(v.max())
    if hi == lo:
        d = 0.5 if lo == 0 else abs(lo) * 0.1
        return lo - d, hi + d
    return lo - (hi - lo) * frac, hi + (hi - lo) * frac


def _label(ax, title=None, xlabel=None, ylabel=None):
    """Titles and axis labels where the axes have none (held axes keep the user's)."""
    for t, s in ((ax.title, title), (ax.xlabel, xlabel), (ax.ylabel, ylabel)):
        if s is not None and not t.props.get('String'):
            t.set_value('String', s)


def _legend(ax, objs, location=None):
    if ax.legend is not None:
        ax.legend.delete_handle()
    lg = Legend(ax, list(objs))
    ax.legend = lg
    if location:
        lg.props['Location'] = location
    return lg


def _columns(v):
    """The columns of a matrix (a row vector is one column)."""
    a = darr(v).real.astype(float)
    if a.ndim == 2 and a.shape[0] == 1:
        a = a.reshape(-1, 1)
    a = a.reshape(a.shape[0], -1)
    return [a[:, j] for j in range(a.shape[1])]


def _grouping(g, n, fn):
    """(labels, index) of a grouping variable, or one group without a name."""
    if _given(g):
        return groups(g, n, fn)
    return [''], np.zeros(n, int)


# ---- box plots ------------------------------------------------------------------------------------------

BOX_TAGS = ('Upper Whisker', 'Lower Whisker', 'Upper Adjacent Value', 'Lower Adjacent Value', 'Box', 'Median', 'Outliers')
BOX_OPTS = {'notch', 'labels', 'orientation', 'whisker', 'symbol', 'widths', 'colors', 'boxstyle', 'medianstyle',
            'outliersize', 'positions', 'grouporder', 'plotstyle', 'jitter', 'labelorientation'}


def box_numbers(v, whisker=1.5):
    """One group's box: the quartiles, the adjacent values (the most extreme
    data within whisker times the interquartile range of the box), the
    outliers beyond them, and the half-height of the notch about the median
    (1.57 IQR / sqrt(n), McGill, Tukey and Larsen's comparison interval)."""
    v = np.asarray(v, float)
    v = v[~np.isnan(v)]
    if v.size == 0:
        return None
    q1, med, q3 = (float(q) for q in _quantiles(v.reshape(-1, 1), [0.25, 0.5, 0.75], 0).reshape(-1))
    d = q3 - q1
    lo, hi = (-math.inf, math.inf) if math.isinf(whisker) else (q1 - whisker * d, q3 + whisker * d)
    keep = (v >= lo) & (v <= hi)
    inside = v[keep]
    return {'q1': q1, 'median': med, 'q3': q3, 'outliers': v[~keep], 'n': v.size, 'notch': 1.57 * d / math.sqrt(v.size),
            'upper': max(float(inside.max()), q3) if inside.size else q3,
            'lower': min(float(inside.min()), q1) if inside.size else q1}


def _box_data(X, g, fn):
    """The groups of a box plot: X's columns, X's columns named by g, or
    X's values grouped by g: (list of arrays, labels)."""
    if X.ndim == 2 and X.shape[0] == 1:
        X = X.reshape(-1, 1)
    X = X.reshape(X.shape[0], -1)
    if not _given(g):
        return [X[:, j] for j in range(X.shape[1])], [str(j + 1) for j in range(X.shape[1])]
    if X.shape[1] > 1 and _count(g) == X.shape[1]:
        return [X[:, j] for j in range(X.shape[1])], _names(g)
    x = X.reshape(-1, order='F')
    labels, idx = groups(g, x.size, fn)
    return [x[idx == k] for k in range(len(labels))], labels


def _draw_boxes(ax, data, labels, opts, fn):
    """Box plots of data (a list of arrays) in ax: the 7-by-k handles."""
    k = len(data)
    compact = 'plotstyle' in opts and sval(opts['plotstyle']).lower() == 'compact'
    notch = sval(opts['notch']).lower() if 'notch' in opts else 'off'
    if notch not in ('on', 'off', 'marker'):
        raise err(f'stats:{fn}:BadNotch', "Notch must be 'on', 'off' or 'marker'.", fn)
    horizontal = 'orientation' in opts and sval(opts['orientation']).lower().startswith('h')
    whisker = float(num(opts['whisker'])) if 'whisker' in opts else 1.5
    if not whisker >= 0:
        raise err(f'stats:{fn}:BadWhisker', 'Whisker must be a nonnegative number.', fn)
    pos = darr(opts['positions']).real.astype(float).reshape(-1) if 'positions' in opts else np.arange(1.0, k + 1)
    if pos.size != k:
        raise err(f'stats:{fn}:BadPositions', f'Positions must have one value for each box ({k}).', fn)
    w = darr(opts['widths']).real.astype(float).reshape(-1) if 'widths' in opts else np.array([0.3 if compact else 0.5])
    widths = [float(w[i % w.size]) for i in range(k)]
    colors = _colors(opts['colors'], k, fn) if 'colors' in opts else [BLUE] * k
    filled = sval(opts['boxstyle']).lower() == 'filled' if 'boxstyle' in opts else compact
    target = sval(opts['medianstyle']).lower() == 'target' if 'medianstyle' in opts else compact
    sym = sval(opts['symbol']) if 'symbol' in opts else ('o' if compact else 'r+')
    spec = parse_linespec(sym) if sym else (None, None, None)
    if spec is None:
        raise err(f'stats:{fn}:BadSymbol', f"'{sym}' is not a marker symbol.", fn)
    ocolor, omarker = spec[0], (spec[2] or '+') if sym else 'none'
    osize = float(num(opts['outliersize'])) if 'outliersize' in opts else (4.0 if compact else 6.0)
    jitter = float(num(opts['jitter'])) if 'jitter' in opts else 0.0
    rs = np.random.RandomState(0)       # the jitter is the same each time, and leaves rng alone

    def L(gx, gy, **kw):
        # gx runs along the groups, gy along the values
        return _line(ax, gy, gx, **kw) if horizontal else _line(ax, gx, gy, **kw)

    H = np.empty((7, k), object)
    for j, v in enumerate(data):
        b = box_numbers(v, whisker)
        p, wd, col = float(pos[j]), widths[j], colors[j]
        if b is None:
            for r, tag in enumerate(BOX_TAGS):
                H[r, j] = L([], [], color=col, tag=tag)
            continue
        q1, med, q3 = b['q1'], b['median'], b['q3']
        wcol, wsty = (col, '-') if compact else (BLACK, '--')
        H[0, j] = L([p, p], [q3, b['upper']], color=wcol, style=wsty, tag='Upper Whisker')
        H[1, j] = L([p, p], [b['lower'], q1], color=wcol, style=wsty, tag='Lower Whisker')
        cap = 0.0 if compact else wd / 4
        H[2, j] = L([p - cap, p + cap], [b['upper']] * 2, color=wcol, tag='Upper Adjacent Value')
        H[3, j] = L([p - cap, p + cap], [b['lower']] * 2, color=wcol, tag='Lower Adjacent Value')
        a, c = p - wd / 2, p + wd / 2
        if notch == 'on':
            nl, nh = med - b['notch'], med + b['notch']
            gx = [a, a, p - wd / 4, a, a, c, c, p + wd / 4, c, c, a]
            gy = [q1, nl, med, nh, q3, q3, nh, med, nl, q1, q1]
            mx = [p - wd / 4, p + wd / 4]
        else:
            gx, gy = [a, a, c, c, a], [q1, q3, q3, q1, q1]
            mx = [a, c]
        if filled:
            h = Patch(ax)
            px, py = (gy, gx) if horizontal else (gx, gy)
            h.props['XData'] = np.asarray(px[:-1], float).reshape(-1, 1)
            h.props['YData'] = np.asarray(py[:-1], float).reshape(-1, 1)
            h.props['FaceColor'] = col
            h.props['EdgeColor'] = col
            h.props['FaceAlpha'] = 0.5
            h.props['Tag'] = 'Box'
            H[4, j] = h
        else:
            H[4, j] = L(gx, gy, color=col, tag='Box')
        if target:
            H[5, j] = L([p], [med], color=BLACK, style='none', marker='o', size=6.0, face=WHITE, tag='Median')
        else:
            H[5, j] = L(mx, [med, med], color=RED, tag='Median')
        if notch == 'marker':
            for side, m in ((a, '>'), (c, '<')):
                L([side, side], [med - b['notch'], med + b['notch']], color=col, style='none', marker=m, size=5.0,
                  face=col, tag='Notch')
        o = b['outliers']
        ox = p + (rs.uniform(-1, 1, o.size) * jitter * wd / 2 if jitter else np.zeros(o.size))
        H[6, j] = L(ox, o, color=ocolor or (col if compact else RED), style='none', marker=omarker, size=osize,
                    tag='Outliers')
    G, V = ('Y', 'X') if horizontal else ('X', 'Y')
    if k:
        pad = 0.5 * max(widths)
        _lim(ax, G, min(pos[j] - widths[j] / 2 for j in range(k)) - pad, max(pos[j] + widths[j] / 2 for j in range(k)) + pad)
        order = np.argsort(pos, kind='stable')
        _ticks(ax, G, pos[order], [labels[i] for i in order])
    if horizontal:
        ax.props['YDir'] = 'reverse'        # the first group on top
    lo = sval(opts['labelorientation']).lower() if 'labelorientation' in opts else ('inline' if compact else 'horizontal')
    if lo == 'inline' and not horizontal:
        ax.props['XTickLabelRotation'] = 90.0
    ax.touch()
    return H


@bi('boxplot', arr=False)
def boxplot(nargout, *args):
    ax, rest = split_axes_arg(args)
    nargchk(rest, 1, None, 'boxplot')
    X = darr(rest.pop(0)).real.astype(float)
    g = None
    if rest and not (opt_str(rest[0]) is not None and opt_lower(rest[0]) in BOX_OPTS):
        g = rest.pop(0)
    opts = _nv(rest, 'boxplot', BOX_OPTS)
    data, labels = _box_data(X, g, 'boxplot')
    if 'grouporder' in opts:
        order = _names(opts['grouporder'])
        missing = [s for s in order if s not in labels]
        if missing:
            raise err('stats:boxplot:BadGroupOrder', f"'{missing[0]}' is not a group.", 'boxplot')
        data, labels = [data[labels.index(s)] for s in order], order
    if 'labels' in opts:
        labels = _names(opts['labels'])
        if len(labels) != len(data):
            raise err('stats:boxplot:BadLabels', f'There must be one label for each box ({len(data)}).', 'boxplot')
    ax = newplot(ax)
    H = _draw_boxes(ax, data, labels, opts, 'boxplot')
    return HArr(H) if nargout else None


def boxplot_groups(cols, labels, title='', ylabel=''):
    """A new figure with box plots of the groups (anova1, kruskalwallis)."""
    f = new_figure()
    ax = newplot(gca_(f))
    _draw_boxes(ax, cols, labels, {}, 'boxplot')
    _label(ax, title=title or None, ylabel=ylabel or None)
    return f


# ---- scatter plots by group ------------------------------------------------------------------------------

@bi('gscatter', arr=False)
def gscatter(nargout, *args):
    ax, rest = split_axes_arg(args)
    nargchk(rest, 3, 9, 'gscatter')
    x = darr(rest[0]).real.astype(float).reshape(-1)
    y = darr(rest[1]).real.astype(float).reshape(-1)
    if x.size != y.size:
        raise err('stats:gscatter:InputSizeMismatch', 'X and Y must have the same length.', 'gscatter')
    labels, idx = _grouping(rest[2], x.size, 'gscatter')
    G = len(labels)
    arg = lambda i: rest[i] if len(rest) > i else None   # noqa: E731
    colors = _colors(arg(3), G, 'gscatter')
    markers = _markers(arg(4), G, '.', 'gscatter')
    sizes = _sizes(arg(5), G, markers)
    show = not (_given(arg(6)) and sval(arg(6)).lower() == 'off')
    ax = newplot(ax)
    hs = [_line(ax, x[idx == k], y[idx == k], colors[k], style='none', marker=markers[k], size=sizes[k], name=labels[k])
          for k in range(G)]
    if _given(arg(7)):
        ax.xlabel.set_value('String', arg(7))
    if _given(arg(8)):
        ax.ylabel.set_value('String', arg(8))
    if show and labels != ['']:
        _legend(ax, hs)
    ax.touch()
    return HArr.of(hs, col=True) if nargout else None


def _matrix(X, Y, labels, idx, colors, markers, sizes, diag, xnames, ynames, show_legend):
    """A matrix of scatter plots filling the current figure: Y's columns
    (the rows) against X's (the columns), each group in its own color and
    marker; with Y None, X against itself and diag on the diagonal.
    (axes, handles rows x cols x groups, big axes)."""
    f = gcf_()
    clf(0, f)
    same = Y is None
    Yv = X if same else Y
    rows, cols, G = Yv.shape[1], X.shape[1], len(labels)
    legend = show_legend and G > 1
    x0, y0, x1, y1 = 0.1, 0.1, (0.8 if legend else 0.95), 0.92
    gap = 0.012
    w = (x1 - x0 - gap * (cols - 1)) / cols
    h = (y1 - y0 - gap * (rows - 1)) / rows
    xl = [_padded(X[:, j]) for j in range(cols)]
    yl = [_padded(Yv[:, i]) for i in range(rows)]
    AX = np.empty((rows, cols), object)
    Hs = np.empty((rows, cols, G), object)
    for i in range(rows):
        for j in range(cols):
            a = Axes(f)
            a.props['Position'] = np.array([[x0 + j * (w + gap), y0 + (rows - 1 - i) * (h + gap), w, h]])
            a.props['Box'] = True
            _lim(a, 'X', *xl[j])
            _lim(a, 'Y', *yl[i])
            if i < rows - 1:
                _no_labels(a, 'X')
            if j > 0:
                _no_labels(a, 'Y')
            AX[i, j] = a
            if same and i == j:
                for k, hk in enumerate(_diagonal(a, X[:, j], idx, labels, colors, diag, xnames[j] if xnames else '', yl[i])):
                    Hs[i, j, k] = hk
            else:
                for k in range(G):
                    sel = idx == k
                    Hs[i, j, k] = _line(a, X[sel, j], Yv[sel, i], colors[k], style='none', marker=markers[k], size=sizes[k],
                                        name=labels[k])
            a.touch()
    if xnames:
        for j in range(cols):
            AX[rows - 1, j].xlabel.set_value('String', xnames[j])
    names = xnames if same else ynames
    if names:
        for i in range(rows):
            AX[i, 0].ylabel.set_value('String', names[i])
    big = Axes(f)
    big.props['Position'] = np.array([[x0, y0, x1 - x0, y1 - y0]])
    big.props['Visible'] = False
    if legend:
        lax = Axes(f)
        lax.props['Position'] = np.array([[x1 + 0.015, y0, 0.98 - x1 - 0.015, y1 - y0]])
        lax.props['Visible'] = False
        i, j = (0, cols - 1) if not (same and cols == 1) else (0, 0)
        _legend(lax, [Hs[i, j, k] for k in range(G)], 'northwest')
    set_current_axes(big)
    f.touch()
    return AX, Hs, big


def _diagonal(a, v, idx, labels, colors, diag, name, ylim):
    """A diagonal cell of a scatter matrix: histograms of v drawn to the
    cell's height ('hist' all together, 'stairs' or 'grpbars' by group),
    the variable's name ('variable'), or nothing ('none')."""
    G = len(labels)
    lo, hi = ylim
    fin = np.isfinite(v)
    if diag in ('hist', 'stairs', 'grpbars'):
        edges = nice_edges(v[fin])
        counts = [np.histogram(v[(idx == k) & fin], edges)[0].astype(float) for k in range(G)]
        total = np.sum(counts, axis=0)
        top = float(total.max() if diag == 'hist' else max(c.max() for c in counts))

        def scale(c):
            return lo + c / top * (hi - lo) * 0.95 if top > 0 else np.full(c.shape, lo)
        if diag == 'hist':
            h = _bars(a, edges[:-1], edges[1:], scale(total), lo, colors[0] if G == 1 else tuple(float(c) for c in COLOR_ORDER[0]))
            return [h] * G
        if diag == 'stairs':
            return [_line(a, np.repeat(edges, 2), np.concatenate([[lo], np.repeat(scale(counts[k]), 2), [lo]]), colors[k],
                          name=labels[k]) for k in range(G)]
        bw = np.diff(edges)
        return [_bars(a, edges[:-1] + bw * k / G, edges[:-1] + bw * (k + 1) / G, scale(counts[k]), lo, colors[k], 0.8)
                for k in range(G)]
    if diag == 'variable':
        t = Text(a, String=name, Position=np.array([[0.5, 0.5, 0.0]]), Units='normalized', HorizontalAlignment='center',
                 FontWeight='bold')
        return [t] * G
    return [_line(a, [], [], colors[0])] * G


DIAG = ('hist', 'stairs', 'grpbars', 'variable', 'none')


@bi('gplotmatrix', nout=3, arr=False)
def gplotmatrix(nargout, *args):
    nargchk(args, 1, 10, 'gplotmatrix')
    arg = lambda i: args[i] if len(args) > i else None   # noqa: E731
    X = np.column_stack(_columns(args[0]))
    Y = np.column_stack(_columns(arg(1))) if _given(arg(1)) else None
    if Y is not None and Y.shape[0] != X.shape[0]:
        raise err('stats:gplotmatrix:InputSizeMismatch', 'X and Y must have the same number of rows.', 'gplotmatrix')
    labels, idx = _grouping(arg(2), X.shape[0], 'gplotmatrix')
    G = len(labels)
    colors = _colors(arg(3), G, 'gplotmatrix')
    markers = _markers(arg(4), G, '.', 'gplotmatrix')
    sizes = _sizes(arg(5), G, markers)
    show = not (_given(arg(6)) and sval(arg(6)).lower() == 'off')
    diag = sval(arg(7)).lower() if _given(arg(7)) else 'stairs'
    if diag not in DIAG:
        raise err('stats:gplotmatrix:BadDispopt', "DISPOPT must be 'stairs', 'hist', 'grpbars', 'variable' or 'none'.", 'gplotmatrix')
    xnames = _names(arg(8)) if _given(arg(8)) else None
    ynames = _names(arg(9)) if _given(arg(9)) else None
    if xnames is not None and len(xnames) != X.shape[1]:
        raise err('stats:gplotmatrix:BadNames', f'XNAM must have one name for each column of X ({X.shape[1]}).', 'gplotmatrix')
    if ynames is not None and Y is not None and len(ynames) != Y.shape[1]:
        raise err('stats:gplotmatrix:BadNames', f'YNAM must have one name for each column of Y ({Y.shape[1]}).', 'gplotmatrix')
    if diag == 'variable' and xnames is None:
        xnames = [f'x{j + 1}' for j in range(X.shape[1])]
    AX, Hs, big = _matrix(X, Y, labels, idx, colors, markers, sizes, diag, xnames, ynames, show)
    if not nargout:
        return None
    res = (HArr(Hs), HArr(AX), big)
    return res[:nargout] if nargout > 1 else res[0]


@bi('plotmatrix', nout=5, arr=False)
def plotmatrix(nargout, *args):
    nargchk(args, 1, 3, 'plotmatrix')
    rest = list(args)
    spec = '.'
    if rest and is_str(rest[-1]):
        spec = sval(rest.pop())
    ls = parse_linespec(spec)
    if ls is None:
        raise err('MATLAB:plotmatrix:BadLineSpec', f"'{spec}' is not a line specification.", 'plotmatrix')
    X = np.column_stack(_columns(rest[0]))
    Y = np.column_stack(_columns(rest[1])) if len(rest) > 1 and _given(rest[1]) else None
    if Y is not None and Y.shape[0] != X.shape[0]:
        raise err('MATLAB:plotmatrix:InputSizeMismatch', 'X and Y must have the same number of rows.', 'plotmatrix')
    color = ls[0] or tuple(float(v) for v in COLOR_ORDER[0])
    marker = ls[2] or ('none' if ls[1] else '.')
    AX, Hs, big = _matrix(X, Y, [''], np.zeros(X.shape[0], int), [color], [marker], [15.0 if marker == '.' else 6.0],
                          'hist', None, None, False)
    if ls[1]:
        for h in Hs[..., 0].reshape(-1):
            if isinstance(h, Line):
                h.props['LineStyle'] = ls[1]
    if not nargout:
        return None
    S = Hs[..., 0]
    n = AX.shape[1]
    diag = [i for i in range(n)] if Y is None else []
    H = HArr.of([S[i, i] for i in diag]) if diag else HArr(np.empty((0, 0), object))
    HAx = HArr.of([AX[i, i] for i in diag]) if diag else HArr(np.empty((0, 0), object))
    res = (HArr(S), HArr(AX), big, H, HAx)
    return res[:nargout] if nargout > 1 else res[0]


# ---- scatter plot with marginal histograms ---------------------------------------------------------------------

SH_OPTS = {'group', 'nbins', 'location', 'direction', 'kernel', 'bandwidth', 'legend', 'color', 'linestyle', 'linewidth',
           'marker', 'markersize', 'style', 'plotgroup'}


@bi('scatterhist', nout=1, arr=False)
def scatterhist(nargout, *args):
    nargchk(args, 2, None, 'scatterhist')
    from .statdesc import kde
    from .distributions import default_bandwidth
    x = darr(args[0]).real.astype(float).reshape(-1)
    y = darr(args[1]).real.astype(float).reshape(-1)
    if x.size != y.size:
        raise err('stats:scatterhist:InputSizeMismatch', 'X and Y must be vectors of the same length.', 'scatterhist')
    opts = _nv(args[2:], 'scatterhist', SH_OPTS)
    labels, idx = _grouping(opts.get('group'), x.size, 'scatterhist')
    G = len(labels)
    if 'plotgroup' in opts and sval(opts['plotgroup']).lower() == 'off':
        mlabels, midx = [''], np.where(idx >= 0, 0, -1)       # the margins of all the data together
    else:
        mlabels, midx = labels, idx
    loc = sval(opts['location']).lower() if 'location' in opts else 'southwest'
    if loc not in ('southwest', 'southeast', 'northwest', 'northeast'):
        raise err('stats:scatterhist:BadLocation', "Location must be 'SouthWest', 'SouthEast', 'NorthWest' or 'NorthEast'.", 'scatterhist')
    inward = not ('direction' in opts and sval(opts['direction']).lower() == 'out')
    kernel = sval(opts['kernel']).lower() if 'kernel' in opts else 'off'
    if kernel not in ('on', 'off', 'overlay'):
        raise err('stats:scatterhist:BadKernel', "Kernel must be 'on', 'off' or 'overlay'.", 'scatterhist')
    style = sval(opts['style']).lower() if 'style' in opts else ('stairs' if len(mlabels) > 1 else 'bar')
    nb = darr(opts['nbins']).real.reshape(-1) if 'nbins' in opts else None
    colors = _colors(opts.get('color'), G, 'scatterhist')
    markers = _markers(opts.get('marker'), G, '.', 'scatterhist')
    sizes = _sizes(opts.get('markersize'), G, markers)
    lstyles = [s for s in (text_list(opts['linestyle']) if 'linestyle' in opts else ['-'])] or ['-']
    lw = darr(opts['linewidth']).real.reshape(-1) if 'linewidth' in opts else np.array([1.0])
    bw_opt = darr(opts['bandwidth']).real.astype(float) if 'bandwidth' in opts else None
    show = not ('legend' in opts and sval(opts['legend']).lower() == 'off')

    f = gcf_()
    clf(0, f)
    m, s, gap, size = 0.1, 0.17, 0.02, 0.66
    west, south = loc.endswith('west'), loc.startswith('south')
    mx = m + s + gap if west else m
    my = m + s + gap if south else m
    main = Axes(f)
    main.props['Position'] = np.array([[mx, my, size, size]])
    main.props['Box'] = True
    hs = [_line(main, x[idx == k], y[idx == k], colors[k], style='none', marker=markers[k], size=sizes[k], name=labels[k])
          for k in range(G)]
    from ..glayout import auto_limits
    lims = auto_limits(main)
    _lim(main, 'X', *lims['XLim'])
    _lim(main, 'Y', *lims['YLim'])
    xh = Axes(f)
    xh.props['Position'] = np.array([[mx, m if south else my + size + gap, size, s]])
    yh = Axes(f)
    yh.props['Position'] = np.array([[m if west else mx + size + gap, my, s, size]])
    for a in (xh, yh):
        a.props['Box'] = True
    _lim(xh, 'X', *lims['XLim'])
    _lim(yh, 'Y', *lims['YLim'])
    xh.props['YDir'] = 'normal' if south == inward else 'reverse'
    yh.props['XDir'] = 'normal' if west == inward else 'reverse'
    _no_labels(xh, 'Y')
    _no_labels(yh, 'X')
    # the data axis's numbers go on the outside: on the histogram where it is there
    _no_labels(main if south else xh, 'X')
    _no_labels(main if west else yh, 'Y')
    for a, v, horiz, which in ((xh, x, False, 0), (yh, y, True, 1)):
        fin = np.isfinite(x) & np.isfinite(y)
        lim = lims['YLim' if horiz else 'XLim']
        if nb is not None and nb.size:
            n_ = int(nb[min(which, nb.size - 1)])
            edges = np.linspace(float(v[fin].min()), float(v[fin].max()), n_ + 1) if fin.any() else np.array([0.0, 1.0])
        else:
            edges = nice_edges(v[fin])
        grid = np.linspace(lim[0], lim[1], 200)
        for k, lab in enumerate(mlabels):
            sel = fin & (midx == k)
            vk = v[sel]
            col = colors[k] if len(mlabels) == G else tuple(float(c) for c in COLOR_ORDER[0])
            if kernel != 'on':
                counts = np.histogram(vk, edges)[0].astype(float)
                vals = counts / max(vk.size, 1) / np.diff(edges) if kernel == 'overlay' else counts
                h = Series(a, 'histogram')
                h.extra.update(edges=edges.astype(float), values=vals, display='stairs' if style == 'stairs' else 'bar')
                h.props['FaceColor'] = col
                h.extra['fc'] = col
                h.props['FaceAlpha'] = 0.6
                h.props['EdgeColor'] = (0.0, 0.0, 0.0)
                h.props['Horizontal'] = horiz
                h.props['Normalization'] = 'pdf' if kernel == 'overlay' else 'count'
                h.props['NumBins'] = float(edges.size - 1)
                h.props['XData'] = vk.reshape(1, -1)
                h.props['DisplayName'] = lab
            if kernel != 'off' and vk.size > 1:
                bw = float(bw_opt.reshape(-1)[min(which, bw_opt.size - 1)]) if bw_opt is not None and bw_opt.size else default_bandwidth(vk)
                dens = kde(vk, grid, bw, 'normal', 'pdf', 'unbounded')
                st_ = lstyles[k % len(lstyles)]
                wd = float(lw[k % lw.size])
                if horiz:
                    _line(a, dens, grid, col, style=st_, width=wd, name=lab)
                else:
                    _line(a, grid, dens, col, style=st_, width=wd, name=lab)
        a.touch()
    if show and G > 1:
        _legend(main, hs)
    set_current_axes(main)
    main.touch()
    f.touch()
    if not nargout:
        return None
    return HArr.of([main, xh, yh])


# ---- distributions of data --------------------------------------------------------------------------------

@bi('histfit', arr=False)
def histfit(nargout, *args):
    ax, rest = split_axes_arg(args)
    nargchk(rest, 1, 3, 'histfit')
    from .distributions import find_dist, fit_dist, ProbDist, KernelDist, _key
    x = darr(rest[0]).real.astype(float).reshape(-1)
    x = x[~np.isnan(x)]
    n = x.size
    if n == 0:
        raise err('stats:histfit:NoData', 'There are no data.', 'histfit')
    nbins = int(num(rest[1])) if len(rest) > 1 and _given(rest[1]) else max(1, math.ceil(math.sqrt(n)))
    name = sval(rest[2]) if len(rest) > 2 else 'normal'
    if _key(name) == 'kernel':
        pd, discrete = KernelDist(x), False
    else:
        d = find_dist(name, 'histfit')
        values, _, _ = fit_dist(d, x, 0.05, 'histfit')
        pd, discrete = ProbDist(d, values), d.discrete
    ax = newplot(ax)
    if discrete:
        centers = np.arange(math.floor(x.min()), math.ceil(x.max()) + 1, dtype=float)
        counts = np.array([np.sum(x == c) for c in centers], float)
        hb = bar(1, ax, centers.reshape(1, -1), counts.reshape(1, -1), 1.0)
        xs = np.arange(centers[0], centers[-1] + 1)
        hl = _line(ax, xs, n * np.asarray(pd.pdf(xs), float), RED, marker='.', width=2.0, size=15.0)
    else:
        lo, hi = float(x.min()), float(x.max())
        if lo == hi:
            lo, hi = lo - 0.5, hi + 0.5
        edges = np.linspace(lo, hi, nbins + 1)
        counts = np.histogram(x, edges)[0].astype(float)
        w = edges[1] - edges[0]
        hb = bar(1, ax, ((edges[:-1] + edges[1:]) / 2).reshape(1, -1), counts.reshape(1, -1), 1.0)
        xs = np.linspace(lo - w, hi + w, 200)
        hl = _line(ax, xs, n * w * np.asarray(pd.pdf(xs), float), RED, width=2.0)
    ax.touch()
    return HArr.of([hb, hl], col=True) if nargout else None


# the probabilities a normal probability plot marks: in pairs about 0.5,
# the more telling first (those that fit at least 14 pixels apart are kept)
PROB_PAIRS = ((0.25, 0.75), (0.1, 0.9), (0.05, 0.95), (0.01, 0.99), (0.001, 0.999), (0.02, 0.98), (0.003, 0.997),
              (1e-4, 0.9999), (1e-5, 0.99999))


def _prob_label(p):
    s = f'{p:.6f}'.rstrip('0')
    return f'{p:.2f}' if len(s.split('.')[1]) < 2 else s


def _reference(ax, tx, t1, t3, q1, q3, color):
    """The line through the quartiles (t1, q1) and (t3, q3): solid between
    them, dashed out to the ends of the data."""
    if not (q3 > q1 and t3 > t1) or not tx.size:
        return _line(ax, [], [], color), _line(ax, [], [], color, style='--')
    slope = (q3 - q1) / (t3 - t1)
    ends = np.array([tx[0], tx[-1]])
    return (_line(ax, [t1, t3], [q1, q3], color),
            _line(ax, ends, q1 + slope * (ends - t1), color, style='--'))


@bi('normplot', arr=False)
def normplot(nargout, *args):
    ax, rest = split_axes_arg(args)
    nargchk(rest, 1, 1, 'normplot')
    st = _st()
    cols = _columns(rest[0])
    ax = newplot(ax)
    z1, z3 = (float(v) for v in st.norm.ppf([0.25, 0.75]))
    pts, solid, dashed = [], [], []
    zlo = 0.0
    for v in cols:
        v = np.sort(v[~np.isnan(v)])
        n = v.size
        c = ax.next_color()
        z = st.norm.ppf((np.arange(1, n + 1) - 0.5) / n) if n else np.zeros(0)
        pts.append(_line(ax, v, z, c, style='none', marker='+'))
        lc = RED if len(cols) == 1 else c
        if n:
            q1, q3 = (float(q) for q in _quantiles(v.reshape(-1, 1), [0.25, 0.75], 0).reshape(-1))
            zlo = min(zlo, float(z[0]))
            if q3 > q1:
                slope = (z3 - z1) / (q3 - q1)
                solid.append(_line(ax, [q1, q3], [z1, z3], lc))
                dashed.append(_line(ax, [v[0], v[-1]], [z1 + slope * (v[0] - q1), z1 + slope * (v[-1] - q1)], lc, style='--'))
                continue
        solid.append(_line(ax, [], [], lc))
        dashed.append(_line(ax, [], [], lc, style='--'))
    lim = max(abs(zlo), 1.0) * 1.05
    _lim(ax, 'Y', -lim, lim)
    from ..glayout import axis_pixels
    per = axis_pixels(ax, 'Y') / (2 * lim)          # pixels for each unit of z
    kept = [0.0]
    for pair in PROB_PAIRS:
        z = float(st.norm.ppf(pair[1]))
        if z <= lim and all(abs(z - k) * per >= 14 for k in kept):
            kept += [-z, z]
    kept.sort()
    _ticks(ax, 'Y', kept, [_prob_label(float(st.norm.cdf(z))) for z in kept])
    ax.props['XGrid'] = ax.props['YGrid'] = True
    _label(ax, 'Normal probability plot', 'Data', 'Probability')
    ax.touch()
    return HArr.of(pts + solid + dashed, col=True) if nargout else None


@bi('qqplot', arr=False)
def qqplot(nargout, *args):
    ax, rest = split_axes_arg(args)
    nargchk(rest, 1, 3, 'qqplot')
    st = _st()
    from .distributions import is_dist
    X = _columns(rest[0])
    second = rest[1] if len(rest) > 1 and (is_dist(rest[1]) or _given(rest[1])) else None
    pvec = darr(rest[2]).real.astype(float).reshape(-1) / 100 if len(rest) > 2 else None
    ax = newplot(ax)
    pts, solid, dashed = [], [], []
    if second is None or is_dist(second):
        quant = (lambda p: st.norm.ppf(p)) if second is None else (lambda p: np.asarray(second.icdf(np.asarray(p, float)), float))
        t1, t3 = (float(v) for v in quant(np.array([0.25, 0.75])))
        for v in X:
            v = np.sort(v[~np.isnan(v)])
            n = v.size
            t = quant((np.arange(1, n + 1) - 0.5) / n) if n else np.zeros(0)
            c = ax.next_color()
            pts.append(_line(ax, t, v, c, style='none', marker='+'))
            q1, q3 = (float(q) for q in _quantiles(v.reshape(-1, 1), [0.25, 0.75], 0).reshape(-1)) if n else (math.nan, math.nan)
            a, b = _reference(ax, t, t1, t3, q1, q3, RED if len(X) == 1 else c)
            solid.append(a)
            dashed.append(b)
        _label(ax, 'Q-Q plot', 'Standard normal quantiles' if second is None else 'Quantiles of the distribution',
               'Quantiles of the sample')
    else:
        Y = _columns(second)
        if len(X) != len(Y) and len(X) > 1 and len(Y) > 1:
            raise err('stats:qqplot:InputSizeMismatch', 'X and Y must have the same number of columns, or one of them '
                      'must be a vector.', 'qqplot')
        pairs = [(X[j if len(X) > 1 else 0], Y[j if len(Y) > 1 else 0]) for j in range(max(len(X), len(Y)))]
        for xv, yv in pairs:
            xs, ys = np.sort(xv[~np.isnan(xv)]), np.sort(yv[~np.isnan(yv)])

            def q(v, p):
                return _quantiles(v.reshape(-1, 1), list(p), 0).reshape(-1)
            if pvec is not None:
                qx, qy = q(xs, pvec), q(ys, pvec)
            elif xs.size == ys.size:
                qx, qy = xs, ys
            elif xs.size < ys.size:
                qx, qy = xs, q(ys, (np.arange(1, xs.size + 1) - 0.5) / xs.size)
            else:
                qx, qy = q(xs, (np.arange(1, ys.size + 1) - 0.5) / ys.size), ys
            c = ax.next_color()
            pts.append(_line(ax, qx, qy, c, style='none', marker='+'))
            x1, x3 = q(xs, [0.25, 0.75]) if xs.size else (math.nan, math.nan)
            y1, y3 = q(ys, [0.25, 0.75]) if ys.size else (math.nan, math.nan)
            a, b = _reference(ax, qx, float(x1), float(x3), float(y1), float(y3), RED if len(pairs) == 1 else c)
            solid.append(a)
            dashed.append(b)
        _label(ax, 'Q-Q plot', 'Quantiles of X', 'Quantiles of Y')
    ax.touch()
    return HArr.of(pts + solid + dashed, col=True) if nargout else None


def _steps(x, f, start):
    """The corners of a step function that is f[i] from x[i] to x[i+1] and
    start before x[0]."""
    return np.repeat(x, 2), np.concatenate([[start], np.repeat(f, 2)[:-1]])


@bi('cdfplot', nout=2, arr=False)
def cdfplot(nargout, *args):
    ax, rest = split_axes_arg(args)
    nargchk(rest, 1, 1, 'cdfplot')
    x = darr(rest[0]).real.astype(float).reshape(-1)
    x = x[~np.isnan(x)]
    if x.size == 0:
        raise err('stats:cdfplot:NoData', 'There are no data.', 'cdfplot')
    xs, counts = np.unique(x, return_counts=True)
    sx, sy = _steps(xs, np.cumsum(counts) / x.size, 0.0)
    ax = newplot(ax)
    h = _line(ax, sx, sy, ax.next_color())
    ax.props['XGrid'] = ax.props['YGrid'] = True
    _label(ax, 'Empirical CDF', 'x', 'F(x)')
    ax.touch()
    if not nargout:
        return None
    stats = Struct.scalar({'min': float(x.min()), 'max': float(x.max()), 'mean': float(x.mean()),
                           'median': float(np.median(x)), 'std': float(np.std(x, ddof=1)) if x.size > 1 else 0.0})
    return (h, stats)[:nargout] if nargout > 1 else h


# ---- lines over a plot ----------------------------------------------------------------------------------------

@bi('lsline', arr=False)
def lsline(nargout, *args):
    ax = args[0] if args and is_axes(args[0]) else gca_()
    hs = []
    for c in reversed(list(ax.children)):
        if not c.valid or getattr(c, 'hidden', False):
            continue
        points = (c.TYPE == 'line' and c.props['LineStyle'] == 'none' and c.props['Marker'] != 'none') or \
                 (isinstance(c, Series) and c.kind == 'scatter')
        if not points:
            continue
        x = np.asarray(c.props['XData'], float).reshape(-1)
        y = np.asarray(c.props['YData'], float).reshape(-1)
        ok = np.isfinite(x) & np.isfinite(y)
        if ok.sum() < 2 or np.ptp(x[ok]) == 0:
            continue
        b, a = np.polyfit(x[ok], y[ok], 1)
        ends = np.array([x[ok].min(), x[ok].max()])
        col = c.props['Color'] if isinstance(c.props['Color'], tuple) else BLACK
        hs.append(_line(ax, ends, a + b * ends, col))
    ax.touch()
    return HArr.of(hs, col=True) if nargout else None


@bi('refline', arr=False)
def refline(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    if not rest:
        return lsline(nargout, ax)
    if len(rest) == 1:
        mb = darr(rest[0]).real.astype(float).reshape(-1)
        m, b = float(mb[0]), (float(mb[1]) if mb.size > 1 else 0.0)
    else:
        m, b = float(num(rest[0])), float(num(rest[1]))
    xl = np.asarray(ax.get_value('XLim'), float).reshape(-1)
    h = _line(ax, xl, m * xl + b, ax.next_color())
    ax.touch()
    return h if nargout else None


@bi('refcurve', arr=False)
def refcurve(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    nargchk(rest, 1, 1, 'refcurve')
    p = darr(rest[0]).real.astype(float).reshape(-1)
    xl = np.asarray(ax.get_value('XLim'), float).reshape(-1)
    xs = np.linspace(xl[0], xl[1], 200)
    h = _line(ax, xs, np.polyval(p, xs), ax.next_color())
    ax.touch()
    return h if nargout else None


# ---- the plots of other statistics functions ---------------------------------------------------------------

def stairs_plot(x, f, xlabel=None, ylabel=None):
    """ecdf with no outputs: the function as steps in the current axes."""
    ax = newplot(None)
    sx, sy = _steps(np.asarray(x, float)[1:], np.asarray(f, float)[1:], float(np.asarray(f, float)[0]))
    h = _line(ax, sx, sy, ax.next_color())
    _label(ax, xlabel=xlabel, ylabel=ylabel)
    ax.touch()
    return h


def line_plot(x, y):
    """ksdensity with no outputs: the estimate as a line in the current axes."""
    ax = newplot(None)
    h = _line(ax, x, y, ax.next_color())
    ax.touch()
    return h


def comparison_plot(means, half, names, title='', xlabel=''):
    """multcompare's figure: each group's estimate with an interval that
    misses another group's interval where the two differ significantly."""
    f = new_figure()
    ax = newplot(gca_(f))
    k = len(means)
    ys = np.arange(k, 0, -1, dtype=float)
    c = tuple(float(v) for v in COLOR_ORDER[0])
    for i in range(k):
        _line(ax, [means[i] - half[i], means[i] + half[i]], [ys[i], ys[i]], c, width=1.5)
        _line(ax, [means[i]], [ys[i]], c, style='none', marker='o', face=c)
    _lim(ax, 'Y', 0.5, k + 0.5)
    _ticks(ax, 'Y', ys[::-1], list(reversed(names)))
    ax.props['XGrid'] = True
    _label(ax, title or None, xlabel or None)
    ax.touch()
    return f
