"""Plotting: figures and axes, the plot functions, and get/set on
graphics objects. The objects are made here; the page draws them when a
command ends, or at drawnow and pause."""
import math

import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, sval, ival, num, is_str, bool_out,
                    like_class, cellstr_list)
from ..values import (MError, NOVAL, Char, Cell, Struct, Str, FH, Obj, F64, C128, class_of, shape_of, numel,
                      _2d, EMPTY, py_str, share, text_list)
from ..graphics_base import (STORE, ROOT, GObj, Figure, Axes, Line, Surface, Patch, Image, Text, Legend, Colorbar,
                             Light, Series, HArr, parse_linespec, to_color, COLOR_ORDER, MARKERS, MARKER_WORDS,
                             serialize_figure, gerr)
from ..colormaps import colormap_by_name, as_colormap, NAMES as CMAP_NAMES
from .. import glayout as GL
from .. import runtime as R


# ---- current figure and axes ---------------------------------------------------------------

def new_figure(number=None):
    if number is None:
        number = 1
        while number in STORE.figures:
            number += 1
    f = Figure(number)
    STORE.current = f
    return f


def gcf_():
    f = STORE.current
    if f is None or not f.valid:
        f = new_figure()
    return f


def gca_(fig=None):
    f = fig or gcf_()
    a = f.props.get('CurrentAxes')
    if a is None or not a.valid:
        axs = f.axes_list()
        if axs:
            a = axs[0]
        else:
            a = Axes(f)
        f.props['CurrentAxes'] = a
    if a.yy is not None and a.yy['side'] == 'right' and a.yy.get('right') is not None:
        return a.yy['right']
    return a


def set_current_axes(a):
    f = a.figure()
    if a.yy_owner is not None:
        f.props['CurrentAxes'] = a.yy_owner
    else:
        f.props['CurrentAxes'] = a
    STORE.current = f


def is_axes(v):
    return isinstance(v, Axes) and v.valid


def split_axes_arg(args):
    """plot(ax, ...): the axes given first, or None."""
    if args and is_axes(args[0]):
        return args[0], list(args[1:])
    if args and isinstance(args[0], HArr) and args[0].a.size == 1 and is_axes(args[0].a.flat[0]):
        return args[0].a.flat[0], list(args[1:])
    return None, list(args)


def set3d(ax):
    """A 3-D view of fresh axes: the default angle and the grid on the
    walls."""
    ax.props['View'] = np.array([[-37.5, 30.0]])
    ax.props['XGrid'] = ax.props['YGrid'] = ax.props['ZGrid'] = True


def newplot(ax=None, box=True):
    """The axes a plot goes into: held axes keep what they have. A fresh
    2-D plot has its box drawn all round."""
    if ax is None:
        f = gcf_()
        ax = gca_(f)
    if ax.props['NextPlot'] == 'replace':
        ax.reset_for_plot()
        ax.props['Box'] = bool(box)
    elif not ax.children:
        ax.props['Box'] = bool(box) or ax.props['Box']
    elif ax.props['NextPlot'] == 'replacechildren':
        for c in list(ax.children):
            c.delete_handle()
        ax.props['ColorOrderIndex'] = 1.0
    set_current_axes(ax)
    return ax


def name_value(args, start, valid=None):
    """Trailing name-value pairs: (dict of name -> value, index where they
    start)."""
    i = start
    pairs = []
    while i < len(args):
        s = opt_str(args[i])
        if s is None or i + 1 >= len(args):
            break
        pairs.append((s, args[i + 1]))
        i += 2
    return pairs


def apply_props(h, pairs):
    for k, v in pairs:
        if k.lower() == 'parent':
            continue
        h.setprop(k, v)


def handles_out(hs, col=True):
    if not hs:
        return HArr(np.empty((0, 1), object))
    if len(hs) == 1:
        return hs[0]
    return HArr.of(hs, col=col)


# ---- figure, axes, hold ---------------------------------------------------------------------

@bi('figure', arr=False)
def figure(nargout, *args):
    if args and not is_str(args[0]):
        a = args[0]
        if isinstance(a, Figure):
            if not a.valid:
                raise err('MATLAB:figure:invalid', 'Invalid figure handle.', 'figure')
            STORE.current = a
            a.order = next(__import__('plab.graphics_base', fromlist=['_order'])._order)
            R.EVENT_HOOK[0] and R.EVENT_HOOK[0]({'type': 'raise', 'figure': a.id})
            return a if nargout else None
        n = int(num(a))
        if n < 1:
            raise err('MATLAB:figure:SingleIntegerArgument', 'Figure number must be a positive integer.', 'figure')
        f = STORE.figures.get(n)
        if f is None:
            f = new_figure(n)
        else:
            STORE.current = f
            R.EVENT_HOOK[0] and R.EVENT_HOOK[0]({'type': 'raise', 'figure': f.id})
        rest = args[1:]
    else:
        f = new_figure()
        rest = args
    apply_props(f, name_value(rest, 0))
    f.touch()
    return f if nargout else None


@bi('gcf', arr=False)
def gcf(nargout, *args):
    return gcf_()


@bi('gca', arr=False)
def gca(nargout, *args):
    return gca_()


@bi('groot', arr=False)
def groot(nargout, *args):
    return ROOT


@bi('gco', arr=False)
def gco(nargout, *args):
    return EMPTY()


@bi('clf', arr=False)
def clf(nargout, *args):
    f = args[0] if args and isinstance(args[0], Figure) else gcf_()
    for c in list(f.children):
        c.delete_handle()
    f.props['CurrentAxes'] = None
    f.layout = None
    f.sgtitle = None
    f.touch()
    return f if nargout else None


@bi('close', arr=False)
def close(nargout, *args):
    if not args:
        f = STORE.current
        if f is not None and f.valid:
            f.delete_handle()
        return None
    a = args[0]
    s = opt_str(a)
    if s is not None:
        if s.lower() in ('all', 'all hidden', 'all force'):
            for f in list(STORE.figures.values()):
                f.delete_handle()
            return True if nargout else None
        for f in list(STORE.figures.values()):
            if f.props['Name'] == s:
                f.delete_handle()
        return None
    items = a.a.reshape(-1) if isinstance(a, HArr) else ([a] if isinstance(a, Figure) else [STORE.figures.get(int(x)) for x in arr(a).reshape(-1)])
    for f in items:
        if f is not None and f.valid:
            f.delete_handle()
    return True if nargout else None


@bi('hold', arr=False)
def hold(nargout, *args):
    ax, rest = split_axes_arg(args)
    if ax is None:
        ax = gca_()
    if not rest:
        ax.props['NextPlot'] = 'replace' if ax.props['NextPlot'] == 'add' else 'add'
        return None
    s = sval(rest[0], 'option', 'hold').lower()
    if s in ('on', 'all'):
        ax.props['NextPlot'] = 'add'
        f = ax.figure()
        f.props['NextPlot'] = 'add'
    elif s == 'off':
        ax.props['NextPlot'] = 'replace'
    else:
        raise err('MATLAB:hold:UnknownOption', f"Unknown option '{s}'.", 'hold')
    return None


@bi('ishold')
def ishold(nargout, *args):
    f = STORE.current
    if f is None or not f.valid:
        return False
    ax = args[0] if args and is_axes(args[0]) else gca_(f)
    return ax.props['NextPlot'] == 'add'


SUB_GX = 0.3155
SUB_GY = 0.3886


def subplot_position(m, n, p, cols=None):
    """The position of subplot(m, n, p) (p may span several cells)."""
    left, bottom, W, H = 0.13, 0.11, 0.775, 0.815
    w = W / (n + (n - 1) * SUB_GX)
    h = H / (m + (m - 1) * SUB_GY)
    cells = p if isinstance(p, (list, tuple)) else [p]
    rects = []
    for q in cells:
        r = (q - 1) // n
        c = (q - 1) % n
        x = left + c * w * (1 + SUB_GX)
        y = bottom + (m - 1 - r) * h * (1 + SUB_GY)
        rects.append((x, y, x + w, y + h))
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[2] for r in rects)
    y1 = max(r[3] for r in rects)
    return [x0, y0, x1 - x0, y1 - y0]


@bi('subplot', arr=False)
def subplot(nargout, *args):
    nargchk(args, 1, None, 'subplot')
    f = gcf_()
    rest = list(args)
    if len(rest) == 1 and numel(rest[0]) == 1 and not is_str(rest[0]) and not is_axes(rest[0]):
        code = int(num(rest[0]))
        m, n, p = code // 100, (code // 10) % 10, code % 10
        pos = subplot_position(m, n, p)
    elif is_axes(rest[0]):
        set_current_axes(rest[0])
        return rest[0] if nargout else None
    elif opt_str(rest[0]) == 'Position':
        pos = list(darr(rest[1]).reshape(-1))
    else:
        m, n = int(num(rest[0])), int(num(rest[1]))
        pv = [int(x) for x in arr(rest[2]).reshape(-1)]
        if any(q < 1 or q > m * n for q in pv):
            raise err('MATLAB:subplot:SubplotIndexTooLarge', f'Index exceeds number of subplots.', 'subplot')
        pos = subplot_position(m, n, pv if len(pv) > 1 else pv[0])
        rest = rest[3:]
    # reuse axes already in that place
    for a in f.axes_list():
        ap = np.asarray(a.props['Position'], float).reshape(-1)
        if np.allclose(ap, pos, atol=1e-6):
            set_current_axes(a)
            return a if nargout else None
    # axes that overlap the new one are removed
    for a in f.axes_list():
        ap = np.asarray(a.props['Position'], float).reshape(-1)
        if (ap[0] < pos[0] + pos[2] - 1e-6 and pos[0] < ap[0] + ap[2] - 1e-6 and
                ap[1] < pos[1] + pos[3] - 1e-6 and pos[1] < ap[1] + ap[3] - 1e-6):
            a.delete_handle()
    a = Axes(f)
    a.props['Position'] = np.array([pos])
    set_current_axes(a)
    a.touch()
    return a if nargout else None


@bi('axes', arr=False)
def axes(nargout, *args):
    if args and is_axes(args[0]):
        set_current_axes(args[0])
        return args[0] if nargout else None
    f = gcf_()
    pairs = name_value(args, 0)
    parent = next((v for k, v in pairs if k.lower() == 'parent'), None)
    if isinstance(parent, Figure):
        f = parent
    a = Axes(f)
    apply_props(a, pairs)
    set_current_axes(a)
    a.touch()
    return a


@bi('cla', arr=False)
def cla(nargout, *args):
    ax = args[0] if args and is_axes(args[0]) else gca_()
    reset = any(opt_str(a) == 'reset' for a in args)
    for c in list(ax.children):
        c.delete_handle()
    ax.props['ColorOrderIndex'] = 1.0
    if reset:
        ax.reset_for_plot()
    ax.touch()
    return None


@bi('tiledlayout', arr=False)
def tiledlayout(nargout, *args):
    f = gcf_()
    for c in list(f.children):
        c.delete_handle()
    if args and opt_str(args[0]) in ('flow', 'vertical', 'horizontal'):
        m, n = 0, 0
        flow = opt_str(args[0])
    else:
        m, n = (int(num(args[0])), int(num(args[1]))) if len(args) >= 2 else (1, 1)
        flow = None
    spacing = 'loose'
    pairs = name_value(args, 1 if flow else 2)
    for k, v in pairs:
        if k.lower() in ('tilespacing', 'padding'):
            spacing = py_str(v).lower()
    f.layout = {'m': m, 'n': n, 'next': 1, 'flow': flow, 'spacing': spacing, 'count': 0}
    f.props['CurrentAxes'] = None
    f.touch()
    return Struct.scalar({'GridSize': np.array([[float(m), float(n)]])}) if nargout else None


def _tile_positions(f):
    L = f.layout
    m, n = L['m'], L['n']
    if L['flow']:
        k = max(L['count'], 1)
        if L['flow'] == 'vertical':
            m, n = k, 1
        elif L['flow'] == 'horizontal':
            m, n = 1, k
        else:
            n = int(math.ceil(math.sqrt(k)))
            m = int(math.ceil(k / n))
    gap = {'compact': 0.06, 'tight': 0.02, 'none': 0.0}.get(L['spacing'], 0.1)
    left, bottom, W, H = 0.08, 0.08, 0.86, 0.84
    w = (W - gap * (n - 1)) / n
    h = (H - gap * (m - 1)) / m
    return m, n, w, h, gap, left, bottom, H


@bi('nexttile', arr=False)
def nexttile(nargout, *args):
    f = gcf_()
    if f.layout is None:
        tiledlayout(0, 'flow')
    L = f.layout
    idx = int(num(args[0])) if args and not is_str(args[0]) else L['next']
    span = [int(x) for x in darr(args[1]).reshape(-1)] if len(args) > 1 and not is_str(args[1]) else [1, 1]
    if L['flow']:
        L['count'] = max(L['count'], idx)
    L['next'] = idx + 1
    _relayout_tiles(f)
    m, n, w, h, gap, left, bottom, H = _tile_positions(f)
    r = (idx - 1) // n
    c = (idx - 1) % n
    x = left + c * (w + gap)
    y = bottom + H - (r + span[0]) * h - (r + span[0] - 1) * gap
    pos = [x, y, w * span[1] + gap * (span[1] - 1), h * span[0] + gap * (span[0] - 1)]
    for a in f.axes_list():
        if getattr(a, 'layout_cell', None) == idx:
            set_current_axes(a)
            return a
    a = Axes(f)
    a.layout_cell = idx
    a.props['Position'] = np.array([pos])
    set_current_axes(a)
    a.touch()
    return a


def _relayout_tiles(f):
    if not f.layout or not f.layout['flow']:
        return
    m, n, w, h, gap, left, bottom, H = _tile_positions(f)
    for a in f.axes_list():
        idx = getattr(a, 'layout_cell', None)
        if idx is None:
            continue
        r = (idx - 1) // n
        c = (idx - 1) % n
        x = left + c * (w + gap)
        y = bottom + H - (r + 1) * h - r * gap
        a.props['Position'] = np.array([[x, y, w, h]])


# ---- line plots ------------------------------------------------------------------------------------

LINE_PROPS = {'color', 'linestyle', 'linewidth', 'marker', 'markersize', 'markerfacecolor', 'markeredgecolor', 'displayname',
              'visible', 'tag', 'userdata', 'markerindices', 'clipping', 'seriesindex', 'parent', 'xdata', 'ydata', 'zdata',
              'xdatasource', 'ydatasource', 'linejoin', 'alignvertexcenters', 'buttondownfcn', 'hittest', 'pickableparts',
              'datatiptemplate', 'colormode', 'linestylemode', 'contextmenu', 'uicontextmenu', 'createfcn', 'deletefcn'}


def _plot_groups(args, is3d=False):
    """plot's arguments as (x, y[, z], linespec) groups and trailing
    name-value pairs."""
    groups = []
    i = 0
    n = len(args)
    pairs = []
    while i < n:
        a = args[i]
        s = opt_str(a)
        if s is not None:
            spec = parse_linespec(s)
            if spec is not None and groups and groups[-1]['spec'] is None and not (s.lower() in LINE_PROPS):
                groups[-1]['spec'] = spec
                i += 1
                continue
            # name-value pairs from here
            while i + 1 < n and opt_str(args[i]) is not None:
                pairs.append((opt_str(args[i]), args[i + 1]))
                i += 2
            if i < n:
                raise err('MATLAB:plot:InvalidData' if True else '', f"Invalid data argument.", 'plot')
            break
        k = 3 if is3d else 2
        data = []
        while len(data) < k and i < n and opt_str(args[i]) is None:
            data.append(args[i])
            i += 1
        if not is3d and len(data) == 1:
            y = data[0]
            ya = arr(y)
            if ya.dtype.kind == 'c':
                groups.append({'x': out(ya.real), 'y': out(ya.imag), 'z': None, 'spec': None})
            else:
                groups.append({'x': None, 'y': y, 'z': None, 'spec': None})
        elif is3d and len(data) < 3:
            raise err('MATLAB:plot3:NotEnoughInputs' if True else '', 'Not enough input arguments.', 'plot3')
        else:
            groups.append({'x': data[0], 'y': data[1], 'z': data[2] if is3d else None, 'spec': None})
    return groups, pairs


def _columns(x, y, z=None):
    """Matching x/y(/z) columns for the lines one group makes."""
    Y = np.asarray(arr(y), float) if arr(y).dtype.kind != 'c' else np.real(arr(y)).astype(float)
    if Y.ndim > 2:
        Y = Y.reshape(Y.shape[0], -1)
    if x is None:
        if Y.ndim == 2 and (Y.shape[0] == 1 or Y.shape[1] == 1):
            yv = Y.reshape(-1)
            return [(np.arange(1, yv.size + 1, dtype=float), yv, None)]
        X = np.arange(1, Y.shape[0] + 1, dtype=float)
        return [(X, Y[:, j], None) for j in range(Y.shape[1])]
    X = np.asarray(arr(x), float) if arr(x).dtype.kind != 'c' else np.real(arr(x)).astype(float)
    Z = None
    if z is not None:
        Z = np.asarray(arr(z), float)
    xv = X.ndim == 2 and (X.shape[0] == 1 or X.shape[1] == 1)
    yv = Y.ndim == 2 and (Y.shape[0] == 1 or Y.shape[1] == 1)
    if Z is not None:
        zv = Z.ndim == 2 and (Z.shape[0] == 1 or Z.shape[1] == 1)
        if xv and yv and zv:
            if not (X.size == Y.size == Z.size):
                raise err('MATLAB:plot3:XYZLengthMismatch', 'Vectors must be the same length.', 'plot3')
            return [(X.reshape(-1), Y.reshape(-1), Z.reshape(-1))]
        if X.shape == Y.shape == Z.shape:
            return [(X[:, j], Y[:, j], Z[:, j]) for j in range(X.shape[1])]
        raise err('MATLAB:plot3:XYZLengthMismatch', 'Data dimensions must agree.', 'plot3')
    if xv and yv:
        if X.size != Y.size:
            raise err('MATLAB:samelen', 'Vectors must be the same length.', 'plot')
        return [(X.reshape(-1), Y.reshape(-1), None)]
    if xv and not yv:
        n = X.size
        if Y.shape[0] == n:
            return [(X.reshape(-1), Y[:, j], None) for j in range(Y.shape[1])]
        if Y.shape[1] == n:
            return [(X.reshape(-1), Y[i, :], None) for i in range(Y.shape[0])]
        raise err('MATLAB:samelen', 'Vectors must be the same length.', 'plot')
    if yv and not xv:
        n = Y.size
        if X.shape[0] == n:
            return [(X[:, j], Y.reshape(-1), None) for j in range(X.shape[1])]
        if X.shape[1] == n:
            return [(X[i, :], Y.reshape(-1), None) for i in range(X.shape[0])]
        raise err('MATLAB:samelen', 'Vectors must be the same length.', 'plot')
    if X.shape != Y.shape:
        raise err('MATLAB:samelen', 'Data dimensions must agree.', 'plot')
    return [(X[:, j], Y[:, j], None) for j in range(Y.shape[1])]


def _make_lines(ax, groups, pairs, is3d=False):
    hs = []
    for g in groups:
        cols = _columns(g['x'], g['y'], g['z'])
        spec = g['spec']
        for x, y, z in cols:
            h = Line(ax)
            color = spec[0] if spec and spec[0] else None
            style = spec[1] if spec else None
            marker = spec[2] if spec else None
            if spec and marker and not style:
                style = 'none'
            h.props['XData'] = np.asarray(x, float).reshape(1, -1)
            h.props['YData'] = np.asarray(y, float).reshape(1, -1)
            if z is not None:
                h.props['ZData'] = np.asarray(z, float).reshape(1, -1)
            h.props['Color'] = color if color else ax.next_color()
            if color:
                # an explicit color still moves the color order on
                pass
            if style:
                h.props['LineStyle'] = style
            if marker:
                h.props['Marker'] = marker
            hs.append(h)
    for h in hs:
        apply_props(h, pairs)
    return hs


def _plot(args, nargout, is3d=False, scales=None, fn='plot'):
    ax, rest = split_axes_arg(args)
    groups, pairs = _plot_groups(rest, is3d)
    parent = next((v for k, v in pairs if k.lower() == 'parent'), None)
    if parent is not None and is_axes(parent):
        ax = parent
    ax = newplot(ax, box=not is3d)
    if scales:
        for k, v in scales.items():
            ax.props[k] = v
    if is3d and ax.props['NextPlot'] != 'add' or (is3d and not ax.is3d()):
        set3d(ax)
    hs = _make_lines(ax, groups, pairs, is3d)
    ax.touch()
    if nargout:
        return handles_out(hs)
    return None


@bi('plot', arr=False)
def plot(nargout, *args):
    nargchk(args, 1, None, 'plot')
    return _plot(args, nargout)


@bi('plot3', arr=False)
def plot3(nargout, *args):
    return _plot(args, nargout, is3d=True, fn='plot3')


@bi('semilogx', arr=False)
def semilogx(nargout, *args):
    return _plot(args, nargout, scales={'XScale': 'log'})


@bi('semilogy', arr=False)
def semilogy(nargout, *args):
    return _plot(args, nargout, scales={'YScale': 'log'})


@bi('loglog', arr=False)
def loglog(nargout, *args):
    return _plot(args, nargout, scales={'XScale': 'log', 'YScale': 'log'})


@bi('line', arr=False)
def line(nargout, *args):
    ax, rest = split_axes_arg(args)
    if ax is None:
        f = gcf_()
        ax = gca_(f)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 3:
        data.append(rest.pop(0))
    pairs = name_value(rest, 0)
    hs = []
    if data:
        groups = [{'x': data[0], 'y': data[1], 'z': data[2] if len(data) > 2 else None, 'spec': None}]
        cols = _columns(groups[0]['x'], groups[0]['y'], groups[0]['z'])
        for x, y, z in cols:
            h = Line(ax)
            h.props['XData'] = np.asarray(x, float).reshape(1, -1)
            h.props['YData'] = np.asarray(y, float).reshape(1, -1)
            if z is not None:
                h.props['ZData'] = np.asarray(z, float).reshape(1, -1)
            h.props['Color'] = ax.next_color()
            hs.append(h)
    else:
        h = Line(ax)
        h.props['Color'] = ax.next_color()
        hs.append(h)
    for h in hs:
        apply_props(h, pairs)
    ax.touch()
    return handles_out(hs) if nargout else None


@bi('fplot', 'ezplot', arr=False)
def fplot(nargout, *args):
    ax, rest = split_axes_arg(args)
    f = rest[0]
    if is_str(f):
        f = R.call  # not used
        raise err('MATLAB:fplot:FunctionText', 'Give fplot a function handle, such as @(x) sin(x).', 'fplot')
    lims = [-5.0, 5.0]
    spec_args = []
    if len(rest) > 1 and opt_str(rest[1]) is None and not isinstance(rest[1], FH):
        lims = list(darr(rest[1]).reshape(-1))[:2]
        spec_args = rest[2:]
    elif len(rest) > 1 and isinstance(rest[1], FH):
        fy = rest[1]
        lims = list(darr(rest[2]).reshape(-1))[:2] if len(rest) > 2 and opt_str(rest[2]) is None else [-5.0, 5.0]
        t = np.linspace(lims[0], lims[1], 400)
        x = np.array([float(arr(f.scall(1, float(v))).reshape(-1)[0]) for v in t])
        y = np.array([float(arr(fy.scall(1, float(v))).reshape(-1)[0]) for v in t])
        return _plot(([ax] if ax else []) + [out(x.reshape(1, -1)), out(y.reshape(1, -1))] + spec_args, nargout)
    else:
        spec_args = rest[1:]
    t = np.linspace(lims[0], lims[1], 400)
    try:
        y = arr(f.scall(1, out(t.reshape(1, -1)))).astype(float).reshape(-1)
        if y.size != t.size:
            raise MError('', 'scalar')
    except MError:
        y = np.array([float(arr(f.scall(1, float(v))).reshape(-1)[0]) for v in t])
    r = _plot(([ax] if ax else []) + [out(t.reshape(1, -1)), out(y.reshape(1, -1))] + spec_args, nargout)
    a = gca_()
    a.props['XLim'] = np.array([[lims[0], lims[1]]])
    a.props['XLimMode'] = 'manual'
    return r


# ---- scatter, bar, histogram and other series ------------------------------------------------------------

def _series_color(ax, given=None):
    return given if given is not None else ax.next_color()


@bi('scatter', 'scatter3', arr=False)
def scatter(nargout, *args):
    ax, rest = split_axes_arg(args)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 5:
        data.append(rest.pop(0))
    filled = False
    marker = 'o'
    pairs = []
    i = 0
    while i < len(rest):
        s = opt_str(rest[i])
        if s == 'filled':
            filled = True
            i += 1
            continue
        if s is not None and s in MARKERS and len(s) == 1:
            marker = s
            i += 1
            continue
        if s is not None and i + 1 < len(rest):
            pairs.append((s, rest[i + 1]))
            i += 2
            continue
        i += 1
    three = len(data) >= 3 and numel(data[2]) == numel(data[0]) and numel(data[0]) > 1 and (len(data) >= 4 or False) or (len(data) >= 3 and _caller_is3(args))
    x = darr(data[0]).reshape(-1)
    y = darr(data[1]).reshape(-1)
    z = None
    k = 2
    if three:
        z = darr(data[2]).reshape(-1)
        k = 3
    sz = data[k] if len(data) > k else None
    c = data[k + 1] if len(data) > k + 1 else None
    ax = newplot(ax, box=z is None)
    if z is not None and ax.props['NextPlot'] != 'add':
        set3d(ax)
    h = Series(ax, 'scatter')
    h.props['XData'] = x.reshape(1, -1)
    h.props['YData'] = y.reshape(1, -1)
    if z is not None:
        h.props['ZData'] = z.reshape(1, -1)
    if sz is not None and numel(sz):
        h.props['SizeData'] = np.asarray(darr(sz), float).reshape(1, -1) if numel(sz) > 1 else float(num(sz))
    color = None
    if c is not None and numel(c):
        if is_str(c):
            color = to_color(c)
        else:
            ca = darr(c)
            if ca.size == 3 and x.size != 3:
                color = tuple(float(v) for v in ca.reshape(-1))
            elif ca.ndim == 2 and ca.shape[1] == 3 and ca.shape[0] == x.size:
                h.extra['rgb'] = ca
            else:
                h.props['CData'] = ca.reshape(1, -1)
    if color is None and not np.size(h.props['CData']) and 'rgb' not in h.extra:
        color = ax.next_color()
    if color is not None:
        h.props['Color'] = color
    h.props['Marker'] = MARKER_WORDS.get(marker, marker)
    h.props['MarkerFaceColor'] = 'flat' if filled else 'none'
    h.props['MarkerEdgeColor'] = 'flat'
    apply_props(h, pairs)
    ax.touch()
    return h if nargout else None


def _caller_is3(args):
    return False


@bi('scatter3', arr=False)
def scatter3(nargout, *args):
    ax, rest = split_axes_arg(args)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 5:
        data.append(rest.pop(0))
    x, y, z = (darr(d).reshape(-1) for d in data[:3])
    sz = data[3] if len(data) > 3 else None
    c = data[4] if len(data) > 4 else None
    filled = any(opt_str(r) == 'filled' for r in rest)
    marker = next((opt_str(r) for r in rest if opt_str(r) in MARKERS), 'o')
    pairs = [(opt_str(rest[i]), rest[i + 1]) for i in range(len(rest) - 1) if opt_str(rest[i]) not in (None, 'filled') and opt_str(rest[i]) not in MARKERS]
    ax = newplot(ax, box=False)
    if ax.props['NextPlot'] != 'add' or not ax.is3d():
        set3d(ax)
    h = Series(ax, 'scatter')
    h.props['XData'] = x.reshape(1, -1)
    h.props['YData'] = y.reshape(1, -1)
    h.props['ZData'] = z.reshape(1, -1)
    if sz is not None and numel(sz):
        h.props['SizeData'] = darr(sz).reshape(1, -1) if numel(sz) > 1 else float(num(sz))
    if c is not None and numel(c):
        if is_str(c):
            h.props['Color'] = to_color(c)
        else:
            ca = darr(c)
            if ca.ndim == 2 and ca.shape[1] == 3 and ca.shape[0] == x.size:
                h.extra['rgb'] = ca
            elif ca.size == 3 and x.size != 3:
                h.props['Color'] = tuple(float(v) for v in ca.reshape(-1))
            else:
                h.props['CData'] = ca.reshape(1, -1)
    else:
        h.props['Color'] = ax.next_color()
    h.props['Marker'] = MARKER_WORDS.get(marker, marker)
    h.props['MarkerFaceColor'] = 'flat' if filled else 'none'
    apply_props(h, pairs)
    ax.touch()
    return h if nargout else None


def _bar(args, nargout, horizontal):
    ax, rest = split_axes_arg(args)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 3:
        data.append(rest.pop(0))
    layout = 'grouped'
    color = None
    pairs = []
    i = 0
    while i < len(rest):
        s = opt_str(rest[i])
        if s in ('grouped', 'stacked', 'hist', 'histc'):
            layout = s
            i += 1
            continue
        spec = parse_linespec(s) if s else None
        if spec and spec[0] and not spec[1] and not spec[2] and (i + 1 >= len(rest) or opt_str(rest[i + 1]) is not None and len(s) == 1):
            color = spec[0]
            i += 1
            continue
        if s is not None and i + 1 < len(rest):
            pairs.append((s, rest[i + 1]))
            i += 2
            continue
        i += 1
    width = 0.8
    if len(data) == 1:
        Y = darr(data[0])
        X = None
    elif len(data) == 2:
        if numel(data[1]) == 1 and numel(data[0]) > 1:
            Y = darr(data[0])
            X = None
            width = float(num(data[1]))
        else:
            X = darr(data[0]).reshape(-1)
            Y = darr(data[1])
    else:
        X = darr(data[0]).reshape(-1)
        Y = darr(data[1])
        width = float(num(data[2]))
    if Y.ndim == 2 and (Y.shape[0] == 1 or Y.shape[1] == 1):
        Y = Y.reshape(-1, 1)
    elif X is not None and Y.shape[0] != X.size and Y.shape[1] == X.size:
        Y = Y.T
    n, k = Y.shape
    if X is None:
        X = np.arange(1, n + 1, dtype=float)
    ax = newplot(ax)
    hs = []
    dx = float(np.min(np.diff(np.sort(X)))) if X.size > 1 else 1.0
    bottoms_pos = np.zeros(n)
    bottoms_neg = np.zeros(n)
    group_w = width * dx
    for j in range(k):
        h = Series(ax, 'bar')
        y = Y[:, j]
        h.props['XData'] = X.reshape(1, -1)
        h.props['YData'] = y.reshape(1, -1)
        h.props['BarWidth'] = width
        h.props['Horizontal'] = horizontal
        if layout == 'stacked':
            base = np.where(y >= 0, bottoms_pos, bottoms_neg)
            top = base + y
            bottoms_pos = np.where(y >= 0, top, bottoms_pos)
            bottoms_neg = np.where(y < 0, top, bottoms_neg)
            xs = X
            w = group_w
        else:
            base = np.zeros(n)
            top = y
            if k > 1:
                w = group_w / k * 0.9 if True else group_w / k
                off = (j - (k - 1) / 2) * (group_w / k)
                xs = X + off
                w = group_w / k * 0.9
            else:
                xs = X
                w = group_w
        h.extra.update(xs=xs.astype(float), bottom=base.astype(float), top=top.astype(float), width=float(w))
        c = color if color is not None else tuple(float(v) for v in COLOR_ORDER[(int(ax.props['ColorOrderIndex']) - 1) % 7])
        if color is None:
            ax.next_color()
        h.props['FaceColor'] = c
        h.extra['fc'] = c
        h.props['EdgeColor'] = (0.0, 0.0, 0.0)
        hs.append(h)
    for h in hs:
        apply_props(h, pairs)
    ax.touch()
    return handles_out(hs, col=False) if nargout else None


@bi('bar', arr=False)
def bar(nargout, *args):
    return _bar(args, nargout, False)


@bi('barh', arr=False)
def barh(nargout, *args):
    return _bar(args, nargout, True)


@bi('histogram', arr=False)
def histogram(nargout, *args):
    from .datafun import nice_edges, bin_counts
    ax, rest = split_axes_arg(args)
    x = darr(rest.pop(0)).reshape(-1).real
    nbins = None
    edges = None
    if rest and opt_str(rest[0]) is None:
        e = darr(rest.pop(0)).reshape(-1)
        if e.size == 1:
            nbins = int(e[0])
        else:
            edges = e
    pairs = name_value(rest, 0)
    norm = 'count'
    binwidth = None
    limits = None
    display = 'bar'
    orient = 'vertical'
    keep = []
    for k, v in pairs:
        kl = k.lower()
        if kl == 'normalization':
            norm = py_str(v).lower()
        elif kl == 'numbins':
            nbins = int(num(v))
        elif kl == 'binwidth':
            binwidth = num(v)
        elif kl == 'binedges':
            edges = darr(v).reshape(-1)
        elif kl == 'binlimits':
            limits = tuple(darr(v).reshape(-1))
        elif kl == 'displaystyle':
            display = py_str(v).lower()
        elif kl == 'orientation':
            orient = py_str(v).lower()
        else:
            keep.append((k, v))
    if edges is None:
        xx = x if limits is None else x[(x >= limits[0]) & (x <= limits[1])]
        edges = nice_edges(xx, nbins, binwidth, limits)
    counts, _, _ = bin_counts(x, edges)
    w = np.diff(edges)
    n = max(np.sum(np.isfinite(x)), 1)
    vals = {'count': counts, 'probability': counts / n, 'pdf': counts / n / w, 'countdensity': counts / w,
            'cumcount': np.cumsum(counts), 'cdf': np.cumsum(counts) / n}.get(norm, counts)
    ax = newplot(ax)
    h = Series(ax, 'histogram')
    h.extra.update(edges=edges.astype(float), values=vals.astype(float), display=display)
    c = ax.next_color()
    h.props['FaceColor'] = c
    h.extra['fc'] = c
    h.props['FaceAlpha'] = 0.6
    h.props['EdgeColor'] = (0.0, 0.0, 0.0)
    h.props['Horizontal'] = orient == 'horizontal'
    h.props['Normalization'] = norm
    h.props['NumBins'] = float(edges.size - 1)
    h.props['BinWidth'] = float(w[0]) if w.size and np.allclose(w, w[0]) else 0.0
    h.props['XData'] = x.reshape(1, -1)
    apply_props(h, keep)
    ax.touch()
    return h if nargout else None


@bi('hist', nout=2, arr=False)
def hist(nargout, *args):
    y = darr(args[0])
    vec = y.ndim == 2 and (y.shape[0] == 1 or y.shape[1] == 1)
    data = y.reshape(-1) if vec else y
    nb = 10
    centers = None
    if len(args) > 1:
        a = darr(args[1]).reshape(-1)
        if a.size == 1:
            nb = int(a[0])
        else:
            centers = a
    lo = float(np.nanmin(data)) if np.size(data) else 0.0
    hi = float(np.nanmax(data)) if np.size(data) else 1.0
    if centers is None:
        if lo == hi:
            lo, hi = lo - 0.5, hi + 0.5
        w = (hi - lo) / nb
        centers = lo + w * (np.arange(nb) + 0.5)
    edges = np.concatenate([[-np.inf], (centers[:-1] + centers[1:]) / 2, [np.inf]])

    def count(v):
        v = v[np.isfinite(v)]
        idx = np.searchsorted(edges, v, side='right') - 1
        idx = np.clip(idx, 0, centers.size - 1)
        return np.bincount(idx, minlength=centers.size).astype(float)
    if vec:
        n = count(data)
    else:
        n = np.column_stack([count(data[:, j]) for j in range(data.shape[1])])
    if nargout:
        nn = out(n.reshape(1, -1)) if vec else out(n)
        return (nn, out(centers.reshape(1, -1))) if nargout >= 2 else nn
    return bar(0, out(centers.reshape(1, -1)), out(n.reshape(1, -1) if vec else n), 1.0)


@bi('area', arr=False)
def area(nargout, *args):
    ax, rest = split_axes_arg(args)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 3:
        data.append(rest.pop(0))
    if len(data) == 1:
        Y = darr(data[0])
        X = None
    else:
        X = darr(data[0]).reshape(-1)
        Y = darr(data[1])
    base = float(num(data[2])) if len(data) > 2 else 0.0
    if Y.ndim == 2 and (Y.shape[0] == 1 or Y.shape[1] == 1):
        Y = Y.reshape(-1, 1)
    if X is None:
        X = np.arange(1, Y.shape[0] + 1, dtype=float)
    ax = newplot(ax)
    hs = []
    cum = np.full(Y.shape[0], base)
    for j in range(Y.shape[1]):
        h = Series(ax, 'area')
        top = cum + Y[:, j] - (base if j == 0 else 0)
        if j == 0:
            top = Y[:, j]
        h.props['XData'] = X.reshape(1, -1)
        h.props['YData'] = Y[:, j].reshape(1, -1)
        h.props['BaseValue'] = base
        h.extra.update(top=top.astype(float), bottom=cum.astype(float))
        cum = top
        c = ax.next_color()
        h.props['FaceColor'] = c
        h.extra['fc'] = c
        hs.append(h)
    apply_props_all(hs, name_value(rest, 0))
    ax.touch()
    return handles_out(hs, col=False) if nargout else None


def apply_props_all(hs, pairs):
    for h in hs:
        apply_props(h, pairs)


@bi('stairs', arr=False)
def stairs(nargout, *args):
    return _simple_series(args, nargout, 'stair')


@bi('stem', arr=False)
def stem(nargout, *args):
    return _simple_series(args, nargout, 'stem')


def _simple_series(args, nargout, kind):
    ax, rest = split_axes_arg(args)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 2:
        data.append(rest.pop(0))
    spec = None
    filled = False
    if rest and opt_str(rest[0]) == 'filled':
        filled = True
        rest.pop(0)
    if rest and opt_str(rest[0]) is not None and parse_linespec(opt_str(rest[0])) is not None and opt_str(rest[0]).lower() not in LINE_PROPS:
        spec = parse_linespec(opt_str(rest.pop(0)))
    if len(data) == 1:
        Y = darr(data[0])
        X = None
    else:
        X = darr(data[0])
        Y = darr(data[1])
    cols = _columns(out(X) if X is not None else None, out(Y))
    ax = newplot(ax)
    hs = []
    for x, y, _ in cols:
        h = Series(ax, kind)
        h.props['XData'] = np.asarray(x, float).reshape(1, -1)
        h.props['YData'] = np.asarray(y, float).reshape(1, -1)
        c = spec[0] if spec and spec[0] else ax.next_color()
        h.props['Color'] = c
        if spec and spec[1]:
            h.props['LineStyle'] = spec[1]
        if kind == 'stem':
            h.props['Marker'] = spec[2] if spec and spec[2] else 'o'
            h.props['MarkerFaceColor'] = 'flat' if filled else 'none'
        elif spec and spec[2]:
            h.props['Marker'] = spec[2]
        hs.append(h)
    apply_props_all(hs, name_value(rest, 0))
    ax.touch()
    return handles_out(hs) if nargout else None


@bi('errorbar', arr=False)
def errorbar(nargout, *args):
    ax, rest = split_axes_arg(args)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 6:
        data.append(rest.pop(0))
    orient = 'vertical'
    spec = None
    while rest:
        s = opt_str(rest[0])
        if s in ('horizontal', 'vertical', 'both'):
            orient = s
            rest.pop(0)
        elif s is not None and parse_linespec(s) is not None and s.lower() not in LINE_PROPS:
            spec = parse_linespec(s)
            rest.pop(0)
        else:
            break
    if len(data) == 2:
        y = darr(data[0]).reshape(-1)
        x = np.arange(1, y.size + 1, dtype=float)
        neg = pos = darr(data[1]).reshape(-1)
        xneg = xpos = None
    elif len(data) == 3:
        x, y = darr(data[0]).reshape(-1), darr(data[1]).reshape(-1)
        neg = pos = darr(data[2]).reshape(-1)
        xneg = xpos = None
        if orient == 'horizontal':
            xneg = xpos = neg
            neg = pos = None
    elif len(data) == 4:
        x, y = darr(data[0]).reshape(-1), darr(data[1]).reshape(-1)
        neg, pos = darr(data[2]).reshape(-1), darr(data[3]).reshape(-1)
        xneg = xpos = None
        if orient == 'horizontal':
            xneg, xpos = neg, pos
            neg = pos = None
    elif len(data) == 6:
        x, y = darr(data[0]).reshape(-1), darr(data[1]).reshape(-1)
        neg, pos = darr(data[2]).reshape(-1), darr(data[3]).reshape(-1)
        xneg, xpos = darr(data[4]).reshape(-1), darr(data[5]).reshape(-1)
    else:
        raise err('MATLAB:errorbar:InvalidInput', 'Invalid input arguments to errorbar.', 'errorbar')
    ax = newplot(ax)
    h = Series(ax, 'errorbar')
    h.props['XData'] = x.reshape(1, -1)
    h.props['YData'] = y.reshape(1, -1)
    if neg is not None:
        h.props['YNegativeDelta'] = np.resize(neg, y.size).reshape(1, -1)
        h.props['YPositiveDelta'] = np.resize(pos, y.size).reshape(1, -1)
    if xneg is not None:
        h.props['XNegativeDelta'] = np.resize(xneg, y.size).reshape(1, -1)
        h.props['XPositiveDelta'] = np.resize(xpos, y.size).reshape(1, -1)
    h.props['Color'] = spec[0] if spec and spec[0] else ax.next_color()
    if spec and spec[1]:
        h.props['LineStyle'] = spec[1]
    if spec and spec[2]:
        h.props['Marker'] = spec[2]
        if not spec[1]:
            h.props['LineStyle'] = 'none'
    apply_props(h, name_value(rest, 0))
    ax.touch()
    return h if nargout else None


@bi('pie', arr=False)
def pie(nargout, *args):
    ax, rest = split_axes_arg(args)
    x = darr(rest.pop(0)).reshape(-1).real
    explode = None
    labels = None
    if rest and type(rest[0]) in (Cell, Str):
        labels = text_list(rest.pop(0))
    elif rest and opt_str(rest[0]) is None:
        explode = darr(rest.pop(0)).reshape(-1)
        if rest and type(rest[0]) in (Cell, Str):
            labels = text_list(rest.pop(0))
    total = x.sum()
    frac = x / total if total > 1 else x
    ax = newplot(ax, box=False)
    h = Series(ax, 'pie')
    pcts = [f'{round(100 * f):d}%' if abs(100 * f - round(100 * f)) < 1e-9 or True else f'{100 * f:.1f}%' for f in frac]
    pct_text = []
    for f in frac:
        p = 100 * f
        if p < 1 and p > 0:
            pct_text.append('< 1%')
        else:
            pct_text.append(f'{round(p):d}%')
    h.extra.update(frac=frac.astype(float), explode=(explode if explode is not None else np.zeros(x.size)).astype(float),
                   labels=labels if labels else pct_text)
    cm = ax.get_value('Colormap')
    idx = np.round(np.linspace(0, cm.shape[0] - 1, max(x.size, 1))).astype(int)
    h.extra['colors'] = cm[idx].astype(float)
    ax.props['Visible'] = False
    ax.props['DataAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
    ax.props['DataAspectRatioMode'] = 'manual'
    ax.touch()
    return h if nargout else None


@bi('polarplot', 'polar', arr=False)
def polarplot(nargout, *args):
    ax, rest = split_axes_arg(args)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 2:
        data.append(rest.pop(0))
    if len(data) == 1:
        rho = darr(data[0]).reshape(-1)
        theta = np.linspace(0, 2 * np.pi, rho.size)
    else:
        theta, rho = darr(data[0]), darr(data[1])
    ax = newplot(ax, box=False)
    ax.kind = 'polar'
    ax.props['DataAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
    ax.props['DataAspectRatioMode'] = 'manual'
    groups = [{'x': out(theta), 'y': out(rho), 'z': None, 'spec': None}]
    pairs = []
    if rest and opt_str(rest[0]) is not None and parse_linespec(opt_str(rest[0])) is not None:
        groups[0]['spec'] = parse_linespec(opt_str(rest.pop(0)))
    pairs = name_value(rest, 0)
    hs = _make_lines(ax, groups, pairs)
    ax.touch()
    return handles_out(hs) if nargout else None


@bi('quiver', 'quiver3', arr=False)
def quiver(nargout, *args):
    ax, rest = split_axes_arg(args)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 5:
        data.append(rest.pop(0))
    spec = None
    if rest and opt_str(rest[0]) is not None and parse_linespec(opt_str(rest[0])) is not None and opt_str(rest[0]).lower() not in LINE_PROPS:
        spec = parse_linespec(opt_str(rest.pop(0)))
    scale = 0.9
    if len(data) in (2, 3):
        U, V = darr(data[0]), darr(data[1])
        m, n = U.shape
        X, Y = np.meshgrid(np.arange(1, n + 1, dtype=float), np.arange(1, m + 1, dtype=float))
        if len(data) == 3:
            scale = float(num(data[2]))
    else:
        X, Y, U, V = (darr(d) for d in data[:4])
        if len(data) == 5:
            scale = float(num(data[4]))
        if X.shape != U.shape and X.ndim == 2 and (X.shape[0] == 1 or X.shape[1] == 1):
            X, Y = np.meshgrid(X.reshape(-1), Y.reshape(-1))
    # scale arrows so that the longest fits the grid spacing
    s = 1.0
    if scale != 0:
        xs = np.unique(X.reshape(-1))
        ys = np.unique(Y.reshape(-1))
        dx = np.min(np.diff(xs)) if xs.size > 1 else 1.0
        dy = np.min(np.diff(ys)) if ys.size > 1 else 1.0
        n_ = max(X.size, 1)
        if xs.size > 1 and ys.size > 1:
            d = math.sqrt(dx * dy) if dx > 0 and dy > 0 else max(dx, dy, 1.0)
        else:
            rng = max((X.max() - X.min()) if X.size else 1.0, (Y.max() - Y.min()) if Y.size else 1.0, 1e-9)
            d = rng / math.sqrt(n_)
        L = np.sqrt(U ** 2 + V ** 2)
        mx = np.nanmax(L) if L.size else 0
        s = scale * d / mx if mx > 0 else 1.0
    ax = newplot(ax)
    h = Series(ax, 'quiver')
    h.props['XData'] = X.astype(float)
    h.props['YData'] = Y.astype(float)
    h.props['UData'] = U.astype(float)
    h.props['VData'] = V.astype(float)
    h.extra['scale'] = float(s)
    h.props['Color'] = spec[0] if spec and spec[0] else ax.next_color()
    apply_props(h, name_value(rest, 0))
    ax.touch()
    return h if nargout else None


# ---- contours ---------------------------------------------------------------------------------------

def marching_squares(X, Y, Z, level):
    """The contour lines of a level as a list of (xs, ys) polylines."""
    m, n = Z.shape
    if m < 2 or n < 2:
        return []
    above = Z >= level
    valid = np.isfinite(Z)
    segs = []
    # crossing points on edges: horizontal edges (i, j)-(i, j+1), vertical (i, j)-(i+1, j)

    def interp(i1, j1, i2, j2):
        z1, z2 = Z[i1, j1], Z[i2, j2]
        t = 0.5 if z2 == z1 else (level - z1) / (z2 - z1)
        x = X[i1, j1] + t * (X[i2, j2] - X[i1, j1])
        y = Y[i1, j1] + t * (Y[i2, j2] - Y[i1, j1])
        return x, y
    cell_ok = valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:] & valid[1:, 1:]
    code = (above[:-1, :-1].astype(np.int8) * 1 + above[:-1, 1:].astype(np.int8) * 2 +
            above[1:, 1:].astype(np.int8) * 4 + above[1:, :-1].astype(np.int8) * 8)
    cells = np.argwhere(cell_ok & (code != 0) & (code != 15))
    # edges of a cell: 0 bottom (i,j)-(i,j+1), 1 right (i,j+1)-(i+1,j+1), 2 top (i+1,j)-(i+1,j+1), 3 left (i,j)-(i+1,j)
    table = {1: [(3, 0)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)], 5: None, 6: [(0, 2)], 7: [(3, 2)],
             8: [(2, 3)], 9: [(2, 0)], 10: None, 11: [(2, 1)], 12: [(1, 3)], 13: [(1, 0)], 14: [(0, 3)]}

    def edge_key(i, j, e):
        if e == 0:
            return ('h', i, j)
        if e == 2:
            return ('h', i + 1, j)
        if e == 3:
            return ('v', i, j)
        return ('v', i, j + 1)

    def edge_point(key):
        k, i, j = key
        if k == 'h':
            return interp(i, j, i, j + 1)
        return interp(i, j, i + 1, j)
    for i, j in cells:
        c = int(code[i, j])
        pairs = table[c]
        if pairs is None:
            center = (Z[i, j] + Z[i, j + 1] + Z[i + 1, j] + Z[i + 1, j + 1]) / 4
            if c == 5:
                pairs = [(3, 2), (1, 0)] if center >= level else [(3, 0), (1, 2)]
            else:
                pairs = [(0, 1), (2, 3)] if center >= level else [(0, 3), (2, 1)]
        for a, b in pairs:
            segs.append((edge_key(i, j, a), edge_key(i, j, b)))
    # join segments that share an edge point into polylines
    ends = {}
    for k, (a, b) in enumerate(segs):
        ends.setdefault(a, []).append(k)
        ends.setdefault(b, []).append(k)
    used = [False] * len(segs)
    lines = []
    for k in range(len(segs)):
        if used[k]:
            continue
        used[k] = True
        a, b = segs[k]
        chain = [a, b]
        # extend forward from b, then backward from a
        for direction in (0, 1):
            while True:
                tip = chain[-1] if direction == 0 else chain[0]
                nxt = None
                for s in ends.get(tip, []):
                    if not used[s]:
                        nxt = s
                        break
                if nxt is None:
                    break
                used[nxt] = True
                p, q = segs[nxt]
                other = q if p == tip else p
                if direction == 0:
                    chain.append(other)
                else:
                    chain.insert(0, other)
                if other == (chain[0] if direction == 0 else chain[-1]):
                    break
        pts = [edge_point(key) for key in chain]
        lines.append((np.array([p[0] for p in pts]), np.array([p[1] for p in pts])))
    return lines


def contour_levels(z, n=None, fill=False):
    zf = z[np.isfinite(z)]
    if zf.size == 0:
        return []
    lo, hi = float(zf.min()), float(zf.max())
    if lo == hi:
        return [lo]
    if n is not None:
        return list(np.linspace(lo, hi, n + 2)[1:-1]) if not fill else list(np.linspace(lo, hi, n + 1)[:-1])
    ticks = GL.nice_ticks(lo, hi, 11)
    if fill:
        step = ticks[1] - ticks[0] if len(ticks) > 1 else 1.0
        if ticks and ticks[0] > lo:
            ticks = [ticks[0] - step] + ticks
        return [t for t in ticks if t < hi]
    return [t for t in ticks if lo < t < hi] or ticks


def contour_matrix(lines_by_level):
    cols = []
    for lev, polys in lines_by_level:
        for xs, ys in polys:
            cols.append(np.array([[lev], [float(xs.size)]]))
            cols.append(np.vstack([xs, ys]))
    if not cols:
        return np.zeros((2, 0))
    return np.hstack(cols)


def _grid_xyz(data):
    if len(data) == 1:
        Z = darr(data[0]).real
        m, n = Z.shape
        X, Y = np.meshgrid(np.arange(1, n + 1, dtype=float), np.arange(1, m + 1, dtype=float))
    else:
        X, Y, Z = darr(data[0]).real, darr(data[1]).real, darr(data[2]).real
        if X.ndim == 2 and (X.shape[0] == 1 or X.shape[1] == 1) and Z.ndim == 2 and Z.shape != X.shape:
            X, Y = np.meshgrid(X.reshape(-1), Y.reshape(-1))
    return X.astype(float), Y.astype(float), Z.astype(float)


def _contour(args, nargout, fill=False, is3d=False):
    ax, rest = split_axes_arg(args)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 4:
        data.append(rest.pop(0))
    levels = None
    nlev = None
    if len(data) in (2, 4):
        lv = darr(data[-1]).reshape(-1)
        data = data[:-1]
        if lv.size == 1:
            nlev = int(lv[0])
        else:
            levels = list(lv)
            if len(levels) == 2 and levels[0] == levels[1]:
                levels = [levels[0]]
    spec = None
    if rest and opt_str(rest[0]) is not None and parse_linespec(opt_str(rest[0])) is not None and opt_str(rest[0]).lower() not in ('linewidth', 'linestyle', 'levellist', 'showtext', 'labelspacing', 'linecolor', 'fill', 'facealpha', 'edgecolor', 'levelstep'):
        spec = parse_linespec(opt_str(rest.pop(0)))
    pairs = name_value(rest, 0)
    show_text = False
    linecolor = None
    keep = []
    for k, v in pairs:
        kl = k.lower()
        if kl == 'levellist':
            levels = list(darr(v).reshape(-1))
        elif kl == 'showtext':
            show_text = py_str(v).lower() == 'on' if is_str(v) else bool(num(v))
        elif kl in ('linecolor', 'edgecolor'):
            linecolor = to_color(v, ('flat', 'none', 'auto'))
        elif kl == 'levelstep':
            pass
        else:
            keep.append((k, v))
    X, Y, Z = _grid_xyz(data)
    if levels is None:
        levels = contour_levels(Z, nlev, fill)
    lines = [(lev, marching_squares(X, Y, Z, lev)) for lev in levels]
    ax = newplot(ax, box=not is3d)
    if is3d and (ax.props['NextPlot'] != 'add' or not ax.is3d()):
        set3d(ax)
    h = Series(ax, 'contour')
    h.props['XData'] = X
    h.props['YData'] = Y
    h.props['ZData'] = Z
    h.props['LevelList'] = np.array([levels], float)
    h.props['Fill'] = fill
    h.props['ShowText'] = show_text
    flat = []
    lev_of = []
    for lev, polys in lines:
        for xs, ys in polys:
            flat.append(np.column_stack([xs, ys]))
            flat.append(np.array([[np.nan, np.nan]]))
            lev_of.append(lev)
    h.extra['levels'] = np.array(levels, float)
    h.extra['paths'] = [{'level': float(lev), 'xy': None} for lev, _ in lines]
    h.extra['lines'] = np.vstack(flat) if flat else np.zeros((0, 2))
    h.extra['lineLevels'] = np.array(lev_of, float)
    h.extra['is3d'] = bool(is3d)
    h.extra['matrix'] = contour_matrix(lines)
    if spec and spec[0]:
        h.props['EdgeColor'] = spec[0]
    elif linecolor is not None:
        h.props['EdgeColor'] = linecolor
    else:
        h.props['EdgeColor'] = 'flat' if not fill else (0.0, 0.0, 0.0)
    if spec and spec[1]:
        h.props['LineStyle'] = spec[1]
    h.props['FaceColor'] = 'flat' if fill else 'none'
    apply_props(h, keep)
    ax.touch()
    C = out(h.extra['matrix'])
    if nargout >= 2:
        return C, h
    if nargout == 1:
        return C
    return None


@bi('contour', nout=2, arr=False)
def contour(nargout, *args):
    return _contour(args, nargout)


@bi('contourf', nout=2, arr=False)
def contourf(nargout, *args):
    return _contour(args, nargout, fill=True)


@bi('contour3', nout=2, arr=False)
def contour3(nargout, *args):
    return _contour(args, nargout, is3d=True)


@bi('contourc')
def contourc(nargout, *args):
    data = list(args)
    levels = None
    nlev = None
    if len(data) in (2, 4):
        lv = darr(data[-1]).reshape(-1)
        data = data[:-1]
        if lv.size == 1:
            nlev = int(lv[0])
        else:
            levels = list(lv)
    X, Y, Z = _grid_xyz(data)
    if levels is None:
        levels = contour_levels(Z, nlev)
    return out(contour_matrix([(lev, marching_squares(X, Y, Z, lev)) for lev in levels]))


@bi('clabel', arr=False)
def clabel(nargout, *args):
    h = args[1] if len(args) > 1 and isinstance(args[1], Series) else None
    if h is not None:
        h.props['ShowText'] = True
        h.touch()
    return None


# ---- surfaces and images ---------------------------------------------------------------------------

def _surface_data(args):
    ax, rest = split_axes_arg(args)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 4:
        data.append(rest.pop(0))
    if len(data) in (1, 2):
        Z = darr(data[0]).real
        m, n = Z.shape
        X, Y = np.meshgrid(np.arange(1, n + 1, dtype=float), np.arange(1, m + 1, dtype=float))
        C = darr(data[1]).real if len(data) == 2 else None
    else:
        X, Y, Z = darr(data[0]).real, darr(data[1]).real, darr(data[2]).real
        if X.ndim == 2 and (X.shape[0] == 1 or X.shape[1] == 1) and Z.shape != X.shape:
            X, Y = np.meshgrid(X.reshape(-1), Y.reshape(-1))
        C = darr(data[3]) if len(data) == 4 else None
        if Z.shape != X.shape:
            raise err('MATLAB:surf:XYZMismatch' if True else '', 'Data dimensions must agree.', 'surf')
    return ax, rest, X.astype(float), Y.astype(float), Z.astype(float), C


def _surf(args, nargout, kind='surf'):
    ax, rest, X, Y, Z, C = _surface_data(args)
    ax = newplot(ax, box=kind == 'pcolor')
    if ax.props['NextPlot'] != 'add' or not ax.is3d():
        if kind != 'pcolor':
            set3d(ax)
    h = Surface(ax)
    if kind == 'pcolor':
        h.props['XData'] = X
        h.props['YData'] = Y
        h.props['ZData'] = np.zeros_like(Z)
        h.props['CData'] = Z if C is None else C
        ax.props['View'] = np.array([[0.0, 90.0]])
        ax.props['Box'] = True
        ax.axis_tight = True
    else:
        h.props['XData'] = X
        h.props['YData'] = Y
        h.props['ZData'] = Z
        h.props['CData'] = (C if C is not None else Z).astype(float) if (C is None or C.ndim == 2) else C
    if kind == 'mesh':
        h.props['FaceColor'] = (1.0, 1.0, 1.0)
        h.props['EdgeColor'] = 'flat'
    elif kind == 'meshz':
        h.props['FaceColor'] = (1.0, 1.0, 1.0)
        h.props['EdgeColor'] = 'flat'
    apply_props(h, name_value(rest, 0))
    if kind in ('surfc', 'meshc'):
        hold_state = ax.props['NextPlot']
        ax.props['NextPlot'] = 'add'
        zmin = float(np.nanmin(Z))
        c = Series(ax, 'contour')
        levels = contour_levels(Z)
        lines = [(lev, marching_squares(X, Y, Z, lev)) for lev in levels]
        flat = []
        lev_of = []
        for lev, polys in lines:
            for xs, ys in polys:
                flat.append(np.column_stack([xs, ys]))
                flat.append(np.array([[np.nan, np.nan]]))
                lev_of.append(lev)
        c.props['XData'] = X
        c.props['YData'] = Y
        c.props['ZData'] = Z
        c.extra.update(levels=np.array(levels, float), lines=np.vstack(flat) if flat else np.zeros((0, 2)),
                       lineLevels=np.array(lev_of, float), is3d=False, zplane=zmin, matrix=contour_matrix(lines))
        c.props['EdgeColor'] = 'flat'
        c.props['FaceColor'] = 'none'
        ax.props['NextPlot'] = hold_state
    ax.touch()
    return h if nargout else None


@bi('surf', arr=False)
def surf(nargout, *args):
    return _surf(args, nargout)


@bi('surfc', arr=False)
def surfc(nargout, *args):
    return _surf(args, nargout, 'surfc')


@bi('mesh', arr=False)
def mesh(nargout, *args):
    return _surf(args, nargout, 'mesh')


@bi('meshc', arr=False)
def meshc(nargout, *args):
    return _surf(args, nargout, 'meshc')


@bi('meshz', 'waterfall', arr=False)
def meshz(nargout, *args):
    return _surf(args, nargout, 'meshz')


@bi('surfl', arr=False)
def surfl(nargout, *args):
    r = _surf(args, 1)
    r.props['FaceLighting'] = 'gouraud'
    ax = gca_()
    if not any(c.TYPE == 'light' for c in ax.children):
        Light(ax)
    return r if nargout else None


@bi('pcolor', arr=False)
def pcolor(nargout, *args):
    return _surf(args, nargout, 'pcolor')


@bi('surface', arr=False)
def surface(nargout, *args):
    ax, rest, X, Y, Z, C = _surface_data(args)
    if ax is None:
        ax = gca_()
    h = Surface(ax)
    h.props['XData'] = X
    h.props['YData'] = Y
    h.props['ZData'] = Z
    h.props['CData'] = C if C is not None else Z
    apply_props(h, name_value(rest, 0))
    ax.touch()
    return h if nargout else None


def _image(args, nargout, scaled):
    ax, rest = split_axes_arg(args)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 3:
        data.append(rest.pop(0))
    clim = None
    if len(data) == 3:
        x, y, C = data
    elif len(data) == 2 and scaled and numel(data[1]) == 2 and numel(data[0]) > 2:
        C, x, y = data[0], None, None
        clim = list(darr(data[1]).reshape(-1))
    elif len(data) == 1:
        C, x, y = data[0], None, None
    else:
        raise err('MATLAB:image:InvalidInput', 'Invalid input arguments.', 'image')
    a = arr(C)
    if type(C) is Char:
        a = a.astype(float)
    if a.ndim == 2 and len(rest) and numel(rest[0]) == 2 and scaled and opt_str(rest[0]) is None:
        clim = list(darr(rest.pop(0)).reshape(-1))
    m, n = a.shape[0], a.shape[1]
    xd = darr(x).reshape(-1) if x is not None else np.array([1.0, float(n)])
    yd = darr(y).reshape(-1) if y is not None else np.array([1.0, float(m)])
    xd = np.array([xd[0], xd[-1]])
    yd = np.array([yd[0], yd[-1]])
    ax = newplot(ax)
    h = Image(ax)
    h.props['CData'] = a if a.dtype.kind != 'b' else a.astype(float)
    h.props['XData'] = xd.reshape(1, -1)
    h.props['YData'] = yd.reshape(1, -1)
    h.props['CDataMapping'] = 'scaled' if scaled else 'direct'
    if ax.props['NextPlot'] != 'add':
        ax.props['YDir'] = 'reverse'
        ax.props['View'] = np.array([[0.0, 90.0]])
        ax.props['Box'] = True
        ax.props['Layer'] = 'top'
    if clim is not None:
        ax.props['CLim'] = np.array([clim])
        ax.props['CLimMode'] = 'manual'
    apply_props(h, name_value(rest, 0))
    ax.touch()
    return h if nargout else None


@bi('image', arr=False)
def image(nargout, *args):
    return _image(args, nargout, False)


@bi('imagesc', arr=False)
def imagesc(nargout, *args):
    return _image(args, nargout, True)


@bi('imshow', arr=False)
def imshow(nargout, *args):
    a = arr(args[0])
    rng = None
    if len(args) > 1 and opt_str(args[1]) is None:
        r = darr(args[1]).reshape(-1)
        rng = list(r) if r.size == 2 else None
        if r.size == 0:
            fin = a[np.isfinite(a)] if a.dtype.kind == 'f' else a
            rng = [float(fin.min()), float(fin.max())]
    if a.ndim == 3:
        h = _image([out(a.astype(float) / (255.0 if a.dtype == np.uint8 else 1.0)) if a.dtype != np.float64 else args[0]], 1, False)
    else:
        if a.dtype == np.uint8:
            rng = rng or [0.0, 255.0]
        elif a.dtype.kind == 'b':
            rng = [0.0, 1.0]
        else:
            rng = rng or [0.0, 1.0]
        h = _image([out(a.astype(float))], 1, True)
        ax = gca_()
        ax.props['CLim'] = np.array([rng])
        ax.props['CLimMode'] = 'manual'
        ax.props['Colormap'] = colormap_by_name('gray', 256)
    ax = gca_()
    ax.props['DataAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
    ax.props['DataAspectRatioMode'] = 'manual'
    ax.props['Visible'] = False
    ax.touch()
    return h if nargout else None


@bi('fill', 'fill3', 'patch', arr=False)
def fill(nargout, *args):
    ax, rest = split_axes_arg(args)
    hs = []
    pairs = []
    # patch('Faces', F, 'Vertices', V, ...)
    if rest and opt_str(rest[0]) is not None:
        if ax is None:
            ax = gca_()
        h = Patch(ax)
        apply_props(h, name_value(rest, 0))
        if not np.size(h.props['Faces']) and np.size(h.props['XData']):
            pass
        ax.touch()
        return h if nargout else None
    groups = []
    while rest:
        data = []
        while rest and opt_str(rest[0]) is None and len(data) < 4:
            data.append(rest.pop(0))
        c = None
        if rest and opt_str(rest[0]) is not None and parse_linespec(opt_str(rest[0])) is not None and len(opt_str(rest[0])) <= 2:
            c = parse_linespec(opt_str(rest.pop(0)))[0]
        elif len(data) in (3, 4) and not is_str(data[-1]):
            last = data.pop()
            c = last
        if len(data) < 2:
            break
        groups.append((data, c))
        if rest and opt_str(rest[0]) is not None:
            pairs = name_value(rest, 0)
            break
    is_patch_low = ax is not None
    if ax is None:
        ax = newplot(None) if True else gca_()
    for data, c in groups:
        X = darr(data[0])
        Y = darr(data[1])
        Z = darr(data[2]) if len(data) > 2 else None
        if X.ndim == 2 and (X.shape[0] == 1 or X.shape[1] == 1):
            X = X.reshape(-1, 1)
            Y = Y.reshape(-1, 1)
            if Z is not None:
                Z = Z.reshape(-1, 1)
        h = Patch(ax)
        h.props['XData'] = X
        h.props['YData'] = Y
        if Z is not None:
            h.props['ZData'] = Z
        if c is None:
            h.props['FaceColor'] = ax.next_color()
        elif isinstance(c, tuple):
            h.props['FaceColor'] = c
        elif is_str(c):
            h.props['FaceColor'] = to_color(c)
        else:
            ca = darr(c)
            if ca.size == 3 and X.shape[0] != 3:
                h.props['FaceColor'] = tuple(float(v) for v in ca.reshape(-1))
            else:
                h.props['CData'] = ca
                h.props['FaceColor'] = 'flat' if ca.size == X.shape[1] or ca.size == 1 else 'interp'
        hs.append(h)
    for h in hs:
        apply_props(h, pairs)
    ax.touch()
    return handles_out(hs) if nargout else None


# ---- decorations -------------------------------------------------------------------------------

def _label(args, which, nargout):
    ax, rest = split_axes_arg(args)
    if ax is None:
        ax = gca_()
    t = {'title': ax.title, 'xlabel': ax.xlabel, 'ylabel': ax.ylabel, 'zlabel': ax.zlabel}[which]
    if not rest:
        return t
    text = rest.pop(0)
    t.set_value('String', text)
    if which == 'title' and rest and opt_str(rest[0]) is None or (which == 'title' and rest and type(rest[0]) in (Char, Str, Cell) and (len(rest) % 2 == 1)):
        ax.subtitle.set_value('String', rest.pop(0))
    apply_props(t, name_value(rest, 0))
    ax.touch()
    return t if nargout else None


@bi('title', arr=False)
def title(nargout, *args):
    return _label(args, 'title', nargout)


@bi('subtitle', arr=False)
def subtitle(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    ax.subtitle.set_value('String', rest[0])
    ax.touch()
    return ax.subtitle if nargout else None


@bi('xlabel', arr=False)
def xlabel(nargout, *args):
    return _label(args, 'xlabel', nargout)


@bi('ylabel', arr=False)
def ylabel(nargout, *args):
    return _label(args, 'ylabel', nargout)


@bi('zlabel', arr=False)
def zlabel(nargout, *args):
    return _label(args, 'zlabel', nargout)


@bi('sgtitle', 'suptitle', arr=False)
def sgtitle(nargout, *args):
    f = gcf_()
    t = Text(None, String='')
    t.set_value('String', args[0])
    t.props['FontSize'] = 11.0
    t.props['FontWeight'] = 'bold'
    apply_props(t, name_value(args, 1))
    t.parent = f
    t.hidden = True
    f.sgtitle = t
    f.touch()
    return t if nargout else None


@bi('legend', arr=False)
def legend(nargout, *args):
    ax, rest = split_axes_arg(args)
    if ax is None:
        f = gcf_()
        ax = gca_(f)
    if rest and opt_str(rest[0]) is not None and opt_str(rest[0]).lower() in ('off', 'hide', 'show', 'toggle', 'boxoff', 'boxon'):
        s = opt_str(rest[0]).lower()
        if s == 'off':
            if ax.legend is not None:
                ax.legend.delete_handle()
                ax.legend = None
        elif ax.legend is not None:
            if s == 'hide':
                ax.legend.props['Visible'] = False
            elif s == 'show':
                ax.legend.props['Visible'] = True
            elif s == 'toggle':
                ax.legend.props['Visible'] = not ax.legend.props['Visible']
            elif s == 'boxoff':
                ax.legend.props['Box'] = False
            elif s == 'boxon':
                ax.legend.props['Box'] = True
        elif s == 'show':
            rest = []
        else:
            ax.touch()
            return None
        if s != 'show' or ax.legend is not None:
            ax.touch()
            return ax.legend if nargout and ax.legend is not None else None
    objs = None
    if rest and (isinstance(rest[0], HArr) or (isinstance(rest[0], GObj) and not is_axes(rest[0]))):
        h = rest.pop(0)
        objs = list(h.a.reshape(-1)) if isinstance(h, HArr) else [h]
    names = []
    while rest and type(rest[0]) in (Char, Str, Cell):
        s = opt_str(rest[0])
        if s is not None and s.lower() in ('location', 'orientation', 'fontsize', 'box', 'textcolor', 'autoupdate', 'numcolumns', 'interpreter', 'color', 'edgecolor', 'title'):
            break
        v = rest.pop(0)
        if type(v) is Cell or (type(v) is Str and v.a.size != 1):
            names += text_list(v)
        elif type(v) is Char and v.a.shape[0] > 1:
            names += v.row_strs()
        else:
            names.append(py_str(v))
    pairs = name_value(rest, 0)
    plotted = [c for c in reversed(ax.plot_children()) if c.TYPE in ('line', 'surface', 'patch', 'bar', 'histogram', 'area', 'stair', 'stem', 'errorbar', 'scatter', 'contour', 'quiver')]
    if ax.yy is not None and ax.yy.get('right') is not None:
        plotted += [c for c in reversed(ax.yy['right'].plot_children())]
    if objs is None:
        if names:
            objs = plotted[:len(names)]
            if len(names) > len(plotted):
                R.warn('MATLAB:legend:IgnoringExtraEntries', 'Ignoring extra legend entries.')
                names = names[:len(plotted)]
        else:
            objs = plotted
    for o, nm in zip(objs, names):
        o.props['DisplayName'] = nm
    for k, o in enumerate(objs):
        if not o.props.get('DisplayName'):
            o.props['DisplayName'] = f'data{k + 1}'
    if ax.legend is not None:
        ax.legend.delete_handle()
    lg = Legend(ax, objs)
    ax.legend = lg
    for k, v in pairs:
        lg.setprop(k, v)
    ax.touch()
    return lg if nargout else None


@bi('colorbar', arr=False)
def colorbar(nargout, *args):
    ax, rest = split_axes_arg(args)
    if ax is None:
        ax = gca_()
    if rest and opt_str(rest[0]) in ('off', 'hide', 'delete'):
        if ax.colorbar is not None:
            ax.colorbar.delete_handle()
            ax.colorbar = None
        ax.touch()
        return None
    loc = 'eastoutside'
    if rest and opt_str(rest[0]) is not None and opt_str(rest[0]).lower() in ('north', 'south', 'east', 'west', 'northoutside', 'southoutside', 'eastoutside', 'westoutside'):
        loc = opt_str(rest.pop(0)).lower()
    if ax.colorbar is None or not ax.colorbar.valid:
        ax.colorbar = Colorbar(ax)
    cb = ax.colorbar
    cb.props['Location'] = loc
    for k, v in name_value(rest, 0):
        cb.setprop(k, v)
    ax.touch()
    return cb if nargout else None


@bi('colormap', arr=False)
def colormap(nargout, *args):
    target = None
    rest = list(args)
    if rest and (isinstance(rest[0], (Axes, Figure))):
        target = rest.pop(0)
    if not rest:
        t = target or gcf_()
        return t.get_value('Colormap') if isinstance(t, Axes) else t.props['Colormap']
    v = rest[0]
    s = opt_str(v)
    if s is not None and s.lower() == 'default':
        cm = colormap_by_name('parula', 256)
    elif s is not None:
        n = int(num(rest[1])) if len(rest) > 1 else 256
        cm = colormap_by_name(s, n)
    else:
        cm = as_colormap(v)
    if isinstance(target, Axes):
        target.props['Colormap'] = cm
        target.touch()
    else:
        f = target or gcf_()
        f.props['Colormap'] = cm
        for a in f.axes_list():
            a.props['Colormap'] = None
        f.touch()
    return out(cm) if nargout else None


def _cmap_fn(name):
    def f(nargout, *args):
        n = int(num(args[0])) if args else 256
        return out(colormap_by_name(name, n))
    f.__name__ = name
    bi(name)(f)


for _n in CMAP_NAMES:
    _cmap_fn(_n)


@bi('caxis', 'clim', arr=False)
def caxis(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    if not rest:
        return ax.get_value('CLim')
    s = opt_str(rest[0])
    if s is not None:
        ax.props['CLimMode'] = 'auto' if s == 'auto' else 'manual'
    else:
        ax.setprop('CLim', rest[0])
    ax.touch()
    return None


@bi('shading', arr=False)
def shading(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    mode = sval(rest[0], 'option', 'shading').lower()
    for c in ax.children:
        if c.TYPE in ('surface', 'patch'):
            if mode == 'flat':
                c.props['FaceColor'] = 'flat'
                c.props['EdgeColor'] = 'none'
            elif mode == 'interp':
                c.props['FaceColor'] = 'interp'
                c.props['EdgeColor'] = 'none'
            elif mode == 'faceted':
                c.props['FaceColor'] = 'flat'
                c.props['EdgeColor'] = (0.0, 0.0, 0.0)
    ax.touch()
    return None


@bi('view', nout=2, arr=False)
def view(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    if not rest:
        v = ax.props['View'].reshape(-1)
        if nargout >= 2:
            return float(v[0]), float(v[1])
        return np.array([[float(v[0]), float(v[1])]])
    if len(rest) == 2:
        az, el = float(num(rest[0])), float(num(rest[1]))
    else:
        a = darr(rest[0]).reshape(-1)
        if a.size == 1:
            az, el = (0.0, 90.0) if a[0] == 2 else (-37.5, 30.0)
        elif a.size == 2:
            az, el = float(a[0]), float(a[1])
        else:
            x, y, z = a[:3]
            az = math.degrees(math.atan2(x, -y))
            el = math.degrees(math.atan2(z, math.hypot(x, y)))
    ax.props['View'] = np.array([[az, el]])
    ax.touch()
    return None


@bi('axis', nout=1, arr=False)
def axis(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    if not rest:
        lims = [ax.get_value('XLim'), ax.get_value('YLim')]
        if ax.is3d():
            lims.append(ax.get_value('ZLim'))
        return out(np.concatenate([l.reshape(-1) for l in lims]).reshape(1, -1))
    for a in rest:
        s = opt_str(a)
        if s is None:
            v = darr(a).reshape(-1)
            if v.size >= 4:
                ax.set_value('XLim', v[0:2])
                ax.set_value('YLim', v[2:4])
            if v.size >= 6:
                ax.set_value('ZLim', v[4:6])
            continue
        s = s.lower()
        if s == 'equal':
            ax.props['DataAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
            ax.props['DataAspectRatioMode'] = 'manual'
        elif s == 'image':
            ax.props['DataAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
            ax.props['DataAspectRatioMode'] = 'manual'
            _tight(ax)
        elif s == 'square':
            ax.props['PlotBoxAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
            ax.props['PlotBoxAspectRatioMode'] = 'manual'
            ax.props['DataAspectRatioMode'] = 'auto'
        elif s in ('normal', 'fill'):
            ax.props['DataAspectRatioMode'] = 'auto'
            ax.props['PlotBoxAspectRatioMode'] = 'auto'
        elif s == 'tight':
            _tight(ax)
        elif s == 'padded':
            _tight(ax, pad=0.05)
        elif s == 'tickaligned':
            for k in 'XYZ':
                ax.props[k + 'LimMode'] = 'auto'
            ax.axis_tight = False
        elif s == 'auto':
            for k in 'XYZ':
                ax.props[k + 'LimMode'] = 'auto'
            ax.axis_tight = False
        elif s == 'manual':
            for k in 'XYZ':
                v = ax.get_value(k + 'Lim')
                ax.props[k + 'Lim'] = v
                ax.props[k + 'LimMode'] = 'manual'
        elif s == 'off':
            ax.props['Visible'] = False
        elif s == 'on':
            ax.props['Visible'] = True
        elif s == 'ij':
            ax.props['YDir'] = 'reverse'
        elif s == 'xy':
            ax.props['YDir'] = 'normal'
        elif s in ('vis3d', 'square'):
            pass
        else:
            raise err('MATLAB:axis:UnknownOption', f"Unknown command option '{s}'.", 'axis')
    ax.touch()
    return None


def _tight(ax, pad=0.0):
    bounds, _ = GL.data_bounds(ax)
    for k in 'XYZ':
        r = bounds[k]
        if r is None:
            continue
        lo, hi = r
        if lo == hi:
            lo, hi = lo - 0.5, hi + 0.5
        d = (hi - lo) * pad
        ax.props[k + 'Lim'] = np.array([[lo - d, hi + d]])
        ax.props[k + 'LimMode'] = 'manual'


def _lim(args, which, nargout):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    if not rest:
        return ax.get_value(which + 'Lim')
    s = opt_str(rest[0])
    if s is not None:
        s = s.lower()
        if s == 'mode':
            return Char.of(ax.props[which + 'LimMode'])
        if s in ('auto', 'manual'):
            if s == 'manual':
                ax.props[which + 'Lim'] = ax.get_value(which + 'Lim')
            ax.props[which + 'LimMode'] = s
        ax.touch()
        return None
    ax.set_value(which + 'Lim', rest[0])
    ax.touch()
    return None


@bi('xlim', arr=False)
def xlim(nargout, *args):
    return _lim(args, 'X', nargout)


@bi('ylim', arr=False)
def ylim(nargout, *args):
    return _lim(args, 'Y', nargout)


@bi('zlim', arr=False)
def zlim(nargout, *args):
    return _lim(args, 'Z', nargout)


def _ticks(args, which, nargout):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    if not rest:
        return ax.get_value(which + 'Tick')
    s = opt_str(rest[0])
    if s is not None:
        ax.props[which + 'TickMode'] = 'auto' if s == 'auto' else 'manual'
    else:
        ax.set_value(which + 'Tick', rest[0])
    ax.touch()
    return None


@bi('xticks', arr=False)
def xticks(nargout, *args):
    return _ticks(args, 'X', nargout)


@bi('yticks', arr=False)
def yticks(nargout, *args):
    return _ticks(args, 'Y', nargout)


@bi('zticks', arr=False)
def zticks(nargout, *args):
    return _ticks(args, 'Z', nargout)


def _ticklabels(args, which, nargout):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    if not rest:
        return ax.get_value(which + 'TickLabel')
    s = opt_str(rest[0])
    if s is not None and s in ('auto', 'manual'):
        ax.props[which + 'TickLabelMode'] = s
    else:
        ax.set_value(which + 'TickLabel', rest[0])
    ax.touch()
    return None


@bi('xticklabels', arr=False)
def xticklabels(nargout, *args):
    return _ticklabels(args, 'X', nargout)


@bi('yticklabels', arr=False)
def yticklabels(nargout, *args):
    return _ticklabels(args, 'Y', nargout)


@bi('zticklabels', arr=False)
def zticklabels(nargout, *args):
    return _ticklabels(args, 'Z', nargout)


@bi('xtickangle', arr=False)
def xtickangle(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    ax.props['XTickLabelRotation'] = float(num(rest[0]))
    ax.touch()
    return None


@bi('ytickangle', arr=False)
def ytickangle(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    ax.props['YTickLabelRotation'] = float(num(rest[0]))
    ax.touch()
    return None


def _onoff(args, props, fn, toggle_all=True):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    if not rest:
        cur = all(ax.props[p] for p in props)
        for p in props:
            ax.props[p] = not cur
    else:
        s = sval(rest[0], 'option', fn).lower()
        if s == 'minor' and fn == 'grid':
            for p in ('XMinorGrid', 'YMinorGrid', 'ZMinorGrid'):
                ax.props[p] = not ax.props[p]
        elif s in ('on', 'off'):
            for p in props:
                ax.props[p] = s == 'on'
            if fn == 'grid' and s == 'off':
                for p in ('XMinorGrid', 'YMinorGrid', 'ZMinorGrid'):
                    ax.props[p] = False
        else:
            raise err('MATLAB:' + fn + ':UnknownOption', f"Unknown option '{s}'.", fn)
    ax.touch()
    return None


@bi('grid', arr=False)
def grid(nargout, *args):
    return _onoff(args, ('XGrid', 'YGrid', 'ZGrid'), 'grid')


@bi('box', arr=False)
def box(nargout, *args):
    return _onoff(args, ('Box',), 'box')


@bi('text', arr=False)
def text(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    data = []
    while rest and opt_str(rest[0]) is None and type(rest[0]) not in (Cell,) and len(data) < 3:
        data.append(rest.pop(0))
    if not rest:
        raise err('MATLAB:text:invalidInput', 'Not enough input arguments.', 'text')
    s = rest.pop(0)
    xs = darr(data[0]).reshape(-1)
    ys = darr(data[1]).reshape(-1)
    zs = darr(data[2]).reshape(-1) if len(data) > 2 else np.zeros(xs.size)
    strs = text_list(s) if type(s) in (Cell, Str) and numel(s) == xs.size and xs.size > 1 else None
    pairs = name_value(rest, 0)
    hs = []
    for i in range(xs.size):
        t = Text(ax)
        t.set_value('String', Char.of(strs[i]) if strs else s)
        t.props['Position'] = np.array([[float(xs[i]), float(ys[i]), float(zs[i])]])
        apply_props(t, pairs)
        hs.append(t)
    ax.touch()
    return handles_out(hs) if nargout else None


@bi('annotation', arr=False)
def annotation(nargout, *args):
    f = gcf_()
    kind = sval(args[0], 'type', 'annotation').lower()
    rest = list(args[1:])
    t = Text(f)
    t.props['Units'] = 'normalized'
    if kind == 'textbox':
        pos = darr(rest.pop(0)).reshape(-1) if rest and opt_str(rest[0]) is None else np.array([0.3, 0.3, 0.1, 0.1])
        t.props['Position'] = np.array([[pos[0], pos[1] + pos[3], 0.0]])
        t.props['VerticalAlignment'] = 'top'
        t.props['EdgeColor'] = (0.0, 0.0, 0.0)
        t.kind = 'textbox'
    else:
        x = darr(rest.pop(0)).reshape(-1) if rest and opt_str(rest[0]) is None else np.array([0.3, 0.4])
        y = darr(rest.pop(0)).reshape(-1) if rest and opt_str(rest[0]) is None else np.array([0.3, 0.4])
        t.props['Position'] = np.array([[x[-1], y[-1], 0.0]])
        t.kind = kind
        t.arrow = (list(map(float, x)), list(map(float, y)))
    for k, v in name_value(rest, 0):
        if k.lower() == 'string':
            t.set_value('String', v)
        elif k.lower() in ('fitboxtotext', 'headstyle', 'headlength', 'headwidth', 'linestyle'):
            continue
        else:
            t.setprop(k, v)
    f.touch()
    return t if nargout else None


@bi('yyaxis', arr=False)
def yyaxis(nargout, *args):
    ax, rest = split_axes_arg(args)
    f = gcf_()
    base = ax or f.props.get('CurrentAxes')
    if base is None or not base.valid:
        base = gca_(f)
    if base.yy_owner is not None:
        base = base.yy_owner
    side = sval(rest[0], 'side', 'yyaxis').lower()
    if base.yy is None:
        right = Axes(f)
        right.yy_owner = base
        right.hidden = True
        right.props['Position'] = base.props['Position']
        right.props['YAxisLocation'] = 'right'
        right.props['Color'] = 'none'
        right.props['NextPlot'] = 'add'
        right.props['ColorOrderIndex'] = 2.0
        base.yy = {'side': side, 'right': right}
        base.props['YColor'] = tuple(float(v) for v in COLOR_ORDER[0])
        right.props['YColor'] = tuple(float(v) for v in COLOR_ORDER[1])
        right.props['ColorOrder'] = np.repeat(COLOR_ORDER[1:2], 7, axis=0)
        base.props['ColorOrder'] = np.repeat(COLOR_ORDER[0:1], 7, axis=0)
        base.props['NextPlot'] = 'add' if base.children else base.props['NextPlot']
    base.yy['side'] = side
    f.props['CurrentAxes'] = base
    base.touch()
    return None


@bi('daspect', arr=False)
def daspect(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    if not rest:
        return ax.props['DataAspectRatio']
    ax.setprop('DataAspectRatio', rest[0])
    return None


@bi('pbaspect', arr=False)
def pbaspect(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    if not rest:
        return ax.props['PlotBoxAspectRatio']
    ax.setprop('PlotBoxAspectRatio', rest[0])
    return None


@bi('light', 'camlight', arr=False)
def light(nargout, *args):
    ax = gca_()
    h = Light(ax)
    rest = list(args)
    if rest and opt_str(rest[0]) in ('headlight', 'right', 'left'):
        rest.pop(0)
    apply_props(h, name_value(rest, 0))
    for c in ax.children:
        if c.TYPE == 'surface' and c.props['FaceLighting'] == 'flat':
            c.props['FaceLighting'] = 'gouraud'
    ax.touch()
    return h if nargout else None


@bi('lighting', arr=False)
def lighting(nargout, *args):
    ax = gca_()
    mode = sval(args[0], 'mode', 'lighting').lower() if args else 'flat'
    for c in ax.children:
        if c.TYPE in ('surface', 'patch'):
            c.props['FaceLighting'] = mode if mode != 'phong' else 'gouraud'
    ax.touch()
    return None


@bi('material', arr=False)
def material(nargout, *args):
    return None


@bi('rotate3d', 'zoom', 'pan', 'datacursormode', 'brush', 'linkaxes', 'linkprop', 'alpha', 'hidden', 'whitebg', 'movegui', 'uistack', 'refresh', 'shg', arr=False)
def ui_noop(nargout, *args):
    return None


@bi('colororder', arr=False)
def colororder(nargout, *args):
    f = gcf_()
    if not args:
        return gca_(f).props['ColorOrder']
    v = args[-1]
    s = opt_str(v)
    co = colormap_by_name('lines', 7) if s else as_colormap(v)
    for a in f.axes_list():
        a.props['ColorOrder'] = co
    return None


# ---- get, set, find ----------------------------------------------------------------------------

def _handles(v):
    if isinstance(v, HArr):
        return list(v.a.reshape(-1))
    if isinstance(v, (GObj, Obj)):
        return [v]
    if type(v) is float or (type(v) is np.ndarray and v.dtype.kind in 'fiu'):
        hs = []
        for x in np.asarray(v, float).reshape(-1):
            if x == 0:
                hs.append(ROOT)
            else:
                f = STORE.figures.get(int(x))
                h = f if f is not None else STORE.objects.get(int(x))
                if h is None:
                    raise err('MATLAB:hg:InvalidHandle', 'Invalid or deleted object.', 'set')
                hs.append(h)
        return hs
    raise err('MATLAB:hg:InvalidHandle', 'Invalid or deleted object.')


@bi('set', arr=False)
def set_(nargout, *args):
    nargchk(args, 1, None, 'set')
    hs = _handles(args[0])
    rest = list(args[1:])
    if len(rest) == 1 and type(rest[0]) is Struct:
        s = rest[0]
        pairs = [(k, s.get1(k)) for k in s.f]
    elif len(rest) == 2 and type(rest[0]) is Cell and type(rest[1]) is Cell:
        names = cellstr_list(rest[0])
        vals = rest[1].a
        for i, h in enumerate(hs):
            for j, n in enumerate(names):
                h.setprop(n, vals[i if vals.shape[0] > 1 else 0, j])
        return None
    else:
        if len(rest) % 2:
            if len(rest) == 1:
                return None
            raise err('MATLAB:hg:set:InvalidNumberOfInputs', 'Invalid parameter/value pair arguments.', 'set')
        pairs = [(sval(rest[i], 'property name', 'set'), rest[i + 1]) for i in range(0, len(rest), 2)]
    for h in hs:
        for k, v in pairs:
            h.setprop(k, v)
    return None


@bi('get', arr=False)
def get(nargout, *args):
    nargchk(args, 1, 2, 'get')
    hs = _handles(args[0])
    if len(args) == 1:
        h = hs[0]
        names = h.propnames()
        d = {}
        for n in names:
            try:
                d[n] = h.getprop(n)
            except MError:
                pass
        if nargout:
            return Struct.scalar(d)
        from ..display import summary
        w = max(len(n) for n in d) if d else 0
        R.write('\n'.join('    ' + n.rjust(w) + ': ' + summary(v) for n, v in d.items()) + '\n\n')
        return None
    names = cellstr_list(args[1]) if type(args[1]) is Cell else [sval(args[1], 'property name', 'get')]
    if len(hs) == 1 and len(names) == 1 and type(args[1]) is not Cell:
        return hs[0].getprop(names[0])
    c = np.empty((len(hs), len(names)), object)
    for i, h in enumerate(hs):
        for j, n in enumerate(names):
            c[i, j] = h.getprop(n)
    return Cell(c)


@bi('ishandle', 'isgraphics', 'isvalid')
def ishandle(nargout, *args):
    v = args[0]
    if isinstance(v, HArr):
        return out(np.array([getattr(h, 'valid', True) for h in v.a.reshape(-1)], bool).reshape(v.a.shape))
    if isinstance(v, GObj):
        return bool(v.valid)
    if isinstance(v, Obj):
        return True
    if type(v) in (float, np.ndarray):
        a = np.asarray(v, float)
        res = [(x == 0) or (int(x) in STORE.figures) or (int(x) in STORE.objects) for x in a.reshape(-1)]
        return out(np.array(res, bool).reshape(a.shape)) if a.size != 1 else res[0]
    return False


@bi('findobj', 'findall', arr=False)
def findobj(nargout, *args):
    rest = list(args)
    roots = []
    if rest and (isinstance(rest[0], (GObj, HArr)) or (type(rest[0]) is float)):
        roots = _handles(rest.pop(0))
    else:
        roots = [f for f in STORE.figures.values()]

    def walk(o):
        yield o
        kids = list(o.children)
        if isinstance(o, Axes):
            kids = kids
        for c in kids:
            if c.valid:
                yield from walk(c)
    found = []
    for r in roots:
        if r is ROOT:
            for f in STORE.figures.values():
                found += list(walk(f))
        else:
            found += list(walk(r))
    conds = []
    i = 0
    while i < len(rest):
        s = opt_str(rest[i])
        if s is None:
            i += 1
            continue
        if s.startswith('-'):
            i += 1
            continue
        if i + 1 < len(rest):
            conds.append((s, rest[i + 1]))
        i += 2
    res = []
    for h in found:
        ok = True
        for k, v in conds:
            try:
                hv = h.getprop(k)
            except MError:
                ok = False
                break
            from .core import _equal
            if k.lower() == 'type':
                ok = py_str(hv) == py_str(v)
            elif not _equal(hv, v, False):
                ok = False
            if not ok:
                break
        if ok:
            res.append(h)
    return HArr.of(res, col=True)


@bi('allchild', arr=False)
def allchild(nargout, *args):
    h = _handles(args[0])[0]
    return HArr.of([c for c in h.children if c.valid], col=True)


@bi('gobjects', arr=False)
def gobjects(nargout, *args):
    from ._util import dims_from
    shape, _, _ = dims_from(args, 'gobjects', allow_class=False) if args else ((0, 0), None, None)
    a = np.empty(shape, object)
    return HArr(a)


@bi('ancestor', arr=False)
def ancestor(nargout, *args):
    h = args[0]
    kind = sval(args[1], 'type', 'ancestor').lower()
    o = h
    while o is not None and getattr(o, 'TYPE', None) != kind:
        o = getattr(o, 'parent', None)
    return o if o is not None else EMPTY()


@bi('drawnow', arr=False)
def drawnow(nargout, *args):
    flush_figures()
    return None


@bi('newplot', arr=False)
def newplot_fn(nargout, *args):
    return newplot()


# ---- shapes ------------------------------------------------------------------------------------

@bi('peaks', nout=3)
def peaks(nargout, *args):
    if not args:
        x = np.linspace(-3, 3, 49)
        X, Y = np.meshgrid(x, x)
    elif len(args) == 1:
        a = darr(args[0])
        if a.size == 1:
            x = np.linspace(-3, 3, int(a.reshape(-1)[0]))
        else:
            x = a.reshape(-1)
        X, Y = np.meshgrid(x, x)
    else:
        X, Y = darr(args[0]), darr(args[1])
    Z = 3 * (1 - X) ** 2 * np.exp(-X ** 2 - (Y + 1) ** 2) - 10 * (X / 5 - X ** 3 - Y ** 5) * np.exp(-X ** 2 - Y ** 2) - 1 / 3 * np.exp(-(X + 1) ** 2 - Y ** 2)
    if nargout <= 1:
        if nargout == 0:
            return _surf([out(X), out(Y), out(Z)], 0)
        return out(Z)
    return (out(X), out(Y), out(Z))[:nargout]


def _shape_out(X, Y, Z, nargout, ax=None):
    if nargout == 0:
        _surf(([ax] if ax else []) + [out(X), out(Y), out(Z)], 0)
        a = gca_()
        a.props['DataAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
        a.props['DataAspectRatioMode'] = 'manual'
        return None
    return (out(X), out(Y), out(Z))[:max(nargout, 1)] if nargout > 1 else out(X)


@bi('sphere', nout=3, arr=False)
def sphere(nargout, *args):
    ax, rest = split_axes_arg(args)
    n = int(num(rest[0])) if rest else 20
    theta = np.linspace(-np.pi, np.pi, n + 1)
    phi = np.linspace(-np.pi / 2, np.pi / 2, n + 1)
    T, Ph = np.meshgrid(theta, phi)
    X = np.cos(Ph) * np.cos(T)
    Y = np.cos(Ph) * np.sin(T)
    Z = np.sin(Ph)
    return _shape_out(X, Y, Z, nargout, ax)


@bi('cylinder', nout=3, arr=False)
def cylinder(nargout, *args):
    ax, rest = split_axes_arg(args)
    r = darr(rest[0]).reshape(-1) if rest else np.array([1.0, 1.0])
    n = int(num(rest[1])) if len(rest) > 1 else 20
    if r.size == 1:
        r = np.array([r[0], r[0]])
    theta = np.linspace(0, 2 * np.pi, n + 1)
    m = r.size
    X = np.outer(r, np.cos(theta))
    Y = np.outer(r, np.sin(theta))
    Z = np.outer(np.linspace(0, 1, m), np.ones(n + 1))
    return _shape_out(X, Y, Z, nargout, ax)


@bi('ellipsoid', nout=3, arr=False)
def ellipsoid(nargout, *args):
    xc, yc, zc, xr, yr, zr = (float(num(a)) for a in args[:6])
    n = int(num(args[6])) if len(args) > 6 else 20
    theta = np.linspace(-np.pi, np.pi, n + 1)
    phi = np.linspace(-np.pi / 2, np.pi / 2, n + 1)
    T, Ph = np.meshgrid(theta, phi)
    X = xc + xr * np.cos(Ph) * np.cos(T)
    Y = yc + yr * np.cos(Ph) * np.sin(T)
    Z = zc + zr * np.sin(Ph)
    return _shape_out(X, Y, Z, nargout)


def _fsample(f, xr, yr, n=35):
    x = np.linspace(xr[0], xr[1], n)
    y = np.linspace(yr[0], yr[1], n)
    X, Y = np.meshgrid(x, y)
    try:
        Z = darr(f.scall(1, out(X), out(Y)))
        if Z.shape != X.shape:
            raise MError('', 'shape')
    except MError:
        Z = np.array([[float(arr(f.scall(1, float(a), float(b))).reshape(-1)[0]) for a, b in zip(rx, ry)] for rx, ry in zip(X, Y)])
    return X, Y, Z


@bi('fsurf', 'ezsurf', 'fmesh', 'ezmesh', arr=False)
def fsurf(nargout, *args):
    ax, rest = split_axes_arg(args)
    f = rest[0]
    lim = darr(rest[1]).reshape(-1) if len(rest) > 1 and opt_str(rest[1]) is None else np.array([-5.0, 5.0])
    xr = lim[:2]
    yr = lim[2:4] if lim.size >= 4 else lim[:2]
    X, Y, Z = _fsample(f, xr, yr)
    return _surf(([ax] if ax else []) + [out(X), out(Y), out(Z)], nargout)


@bi('fcontour', 'ezcontour', arr=False)
def fcontour(nargout, *args):
    ax, rest = split_axes_arg(args)
    f = rest[0]
    lim = darr(rest[1]).reshape(-1) if len(rest) > 1 and opt_str(rest[1]) is None else np.array([-5.0, 5.0])
    X, Y, Z = _fsample(f, lim[:2], lim[2:4] if lim.size >= 4 else lim[:2], 60)
    return _contour(([ax] if ax else []) + [out(X), out(Y), out(Z)], nargout)


# ---- sending the figures to the page -----------------------------------------------------------

def flush_figures():
    """Tell the page about the figures that changed (and those closed)."""
    hook = R.EVENT_HOOK[0]
    dirty = [f for f in STORE.dirty if f.valid]
    closed = list(STORE.closed)
    STORE.dirty.clear()
    STORE.closed.clear()
    if hook is None:
        return
    if not dirty and not closed:
        return
    figs = []
    for f in sorted(dirty, key=lambda f: f.order):
        try:
            figs.append(serialize_figure(f))
        except Exception as e:
            R.write(f'Warning: Figure {int(f.props["Number"])} could not be drawn: {e}\n', 'warn')
    cur = STORE.current.id if STORE.current is not None and STORE.current.valid else None
    hook({'type': 'figures', 'figures': figs, 'closed': closed, 'current': cur})


R.FLUSH_FIGURES = flush_figures


# ---- saving pictures -----------------------------------------------------------------------------

@bi('saveas', 'print', 'exportgraphics', aw=True, arr=False)
async def saveas(nargout, *args):
    rest = list(args)
    f = None
    if rest and isinstance(rest[0], (Figure, Axes)):
        h = rest.pop(0)
        f = h if isinstance(h, Figure) else h.figure()
    f = f or gcf_()
    name = None
    fmt = None
    for a in rest:
        s = opt_str(a)
        if s is None:
            continue
        if s.startswith('-d'):
            fmt = s[2:].lower()
        elif s.startswith('-r') or s.startswith('-'):
            continue
        elif name is None:
            name = s
        elif fmt is None:
            fmt = s.lower()
    if name is None:
        name = f'figure{int(f.props["Number"])}'
    import os
    ext = os.path.splitext(name)[1].lower().lstrip('.')
    if not ext:
        ext = {'png': 'png', 'jpeg': 'jpg', 'jpg': 'jpg', 'svg': 'svg', 'pdf': 'pdf', 'epsc': 'eps'}.get(fmt or 'png', 'png')
        name += '.' + ext
    from .iofun import abspath, files_changed
    p = abspath(name)
    flush_figures()
    data = await R.ask_page({'type': 'render', 'figure': f.id, 'format': ext if ext in ('png', 'jpg', 'jpeg', 'svg') else 'png'})
    if data is None:
        raise err('MATLAB:print:noRenderer', 'The figure could not be drawn to a file here.', 'saveas')
    import base64
    with open(p, 'wb') as fh:
        fh.write(base64.b64decode(data))
    files_changed(os.path.dirname(p))
    return None


@bi('getframe', arr=False)
def getframe(nargout, *args):
    raise err('MATLAB:getframe:notAvailable', 'getframe is not available here: use saveas or exportgraphics to write a picture.', 'getframe')


@bi('ginput', nout=3, aw=True, arr=False)
async def ginput(nargout, *args):
    n = int(num(args[0])) if args else 1
    flush_figures()
    f = gcf_()
    res = await R.ask_page({'type': 'ginput', 'figure': f.id, 'n': n})
    pts = np.array(res or [], float).reshape(-1, 3) if res else np.zeros((0, 3))
    x = out(pts[:, 0:1])
    y = out(pts[:, 1:2])
    b = out(pts[:, 2:3])
    if nargout <= 1:
        return out(pts[:, :2])
    return (x, y, b)[:nargout]


@bi('waitforbuttonpress', aw=True)
async def waitforbuttonpress(nargout, *args):
    flush_figures()
    await R.ask_input('', 'key')
    return 0.0 if nargout else None
