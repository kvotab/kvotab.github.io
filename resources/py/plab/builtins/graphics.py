"""Plotting: figures and axes, the plot functions, and get/set on
graphics objects. The objects are made here; the page draws them when a
command ends, or at drawnow and pause."""
import math

import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, opt_lower, sval, ival, num, is_str, bool_out,
                    like_class, cellstr_list)
from ..values import (MError, NOVAL, Char, Cell, Struct, Str, FH, Obj, F64, C128, class_of, shape_of, numel,
                      _2d, EMPTY, py_str, share, text_list)
from ..graphics_base import (STORE, ROOT, GObj, Figure, Axes, Line, Surface, Patch, Image, Text, Legend, Colorbar,
                             Light, Series, HArr, parse_linespec, to_color, COLOR_ORDER, MARKERS, MARKER_WORDS,
                             serialize_figure, gerr, handle_of_number, NAMED)
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
    if f is None or not f.valid or (f.props['HandleVisibility'] != 'on' and not shown_test()(f)):
        # a figure whose handle is hidden is never current outside its callbacks
        shown = shown_test()
        rest = sorted((g for g in STORE.figures.values() if g.valid and shown(g)), key=lambda g: -g.order)
        f = rest[0] if rest else new_figure()
        STORE.current = f
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
            # a drawn object given other axes, or a group, goes there (axes, figures and controls see to their own parents)
            target = v.a.flat[0] if isinstance(v, HArr) and v.a.size == 1 else v
            from ..graphics_base import Group
            if isinstance(target, (Axes, Group)) and target is not h.parent and h.TYPE in _DRAWN_TYPES:
                if h.parent is not None:
                    h.parent.touch()
                h.reparent(target)
            continue
        h.setprop(k, v)


_DRAWN_TYPES = ('line', 'surface', 'patch', 'image', 'text', 'light', 'hggroup', 'hgtransform', 'series')


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
    f = args[0] if args and isinstance(args[0], Figure) else STORE.current
    o = f.props.get('CurrentObject') if f is not None and f.valid else None
    return o if o is not None and o.valid else EMPTY()


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


async def _close_one(f, force):
    """A figure closes as its CloseRequestFcn says (closereq deletes it);
    force deletes it all the same."""
    from .. import uievents as E
    crf = f.props['CloseRequestFcn']
    if force or (isinstance(crf, str) and crf.strip().rstrip(';').replace('()', '') == 'closereq'):
        f.delete_handle()
    else:
        await E.run_one(f, 'CloseRequestFcn', E.evdata(f, 'Close'))


@bi('close', aw=True, arr=False)
async def close(nargout, *args):
    words = [opt_lower(a) for a in args if opt_str(a) is not None]
    force = 'force' in words or 'all force' in words
    # 'force' closes the figures whose handles are hidden too
    hidden = force or 'hidden' in words or 'all hidden' in words
    rest = [a for a in args if opt_str(a) is None or opt_lower(a) not in ('force', 'hidden')]
    if not rest:
        f = STORE.current
        if f is not None and f.valid:
            await _close_one(f, force)
        return None
    a = rest[0]
    s = opt_str(a)
    if s is not None:
        if s.lower() in ('all', 'all hidden', 'all force'):
            for f in list(STORE.figures.values()):
                if f.valid and (hidden or f.props['HandleVisibility'] == 'on'):
                    await _close_one(f, force)
            return True if nargout else None
        for f in list(STORE.figures.values()):
            if f.valid and f.props['Name'] == s:
                await _close_one(f, force)
        return None
    items = a.a.reshape(-1) if isinstance(a, HArr) else ([a] if isinstance(a, Figure) else [STORE.figures.get(int(x)) for x in arr(a).reshape(-1)])
    for f in items:
        if f is not None and f.valid:
            await _close_one(f, force)
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


def _overlaps(a, pos):
    ap = np.asarray(a.props['Position'], float).reshape(-1)
    return (ap[0] < pos[0] + pos[2] - 1e-6 and pos[0] < ap[0] + ap[2] - 1e-6 and
            ap[1] < pos[1] + pos[3] - 1e-6 and pos[1] < ap[1] + ap[3] - 1e-6)


def _need(data, k, fn=None):
    """An error when fewer than k data inputs came before the options."""
    if len(data) < k:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', fn)


@bi('subplot', arr=False)
def subplot(nargout, *args):
    nargchk(args, 1, None, 'subplot')
    f = gcf_()
    rest = list(args)
    if len(rest) == 1 and numel(rest[0]) == 1 and not is_str(rest[0]) and not is_axes(rest[0]):
        x = float(num(rest[0]))
        code = int(x) if x == int(x) else 0
        m, n, p = code // 100, (code // 10) % 10, code % 10
        if not (100 <= code <= 999 and m >= 1 and n >= 1 and 1 <= p <= m * n):
            raise err('MATLAB:subplot:InvalidSubplot', 'A single input is three digits mnp: m rows, n columns, and p from 1 to m*n.', 'subplot')
        pos = subplot_position(m, n, p)
    elif is_axes(rest[0]):
        set_current_axes(rest[0])
        return rest[0] if nargout else None
    elif opt_str(rest[0]) == 'Position':
        _need(rest, 2, 'subplot')
        pos = list(darr(rest[1]).reshape(-1))
    else:
        _need(rest, 3, 'subplot')
        m, n = int(num(rest[0])), int(num(rest[1]))
        pv = [int(x) for x in arr(rest[2]).reshape(-1)]
        if any(q < 1 or q > m * n for q in pv):
            raise err('MATLAB:subplot:SubplotIndexTooLarge', f'Index exceeds number of subplots.', 'subplot')
        pos = subplot_position(m, n, pv if len(pv) > 1 else pv[0])
        rest = rest[3:]
        if rest and is_axes(rest[0]):
            # subplot(m, n, p, ax): the axes given (polaraxes, say) take the place
            target = rest[0]
            for a in target.figure().axes_list():
                if a is not target and _overlaps(a, pos):
                    a.delete_handle()
            target.props['Position'] = np.array([pos])
            set_current_axes(target)
            target.touch()
            return target if nargout else None
    # reuse axes already in that place
    for a in f.axes_list():
        ap = np.asarray(a.props['Position'], float).reshape(-1)
        if np.allclose(ap, pos, atol=1e-6):
            set_current_axes(a)
            return a if nargout else None
    # axes that overlap the new one are removed
    for a in f.axes_list():
        if _overlaps(a, pos):
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
    rest = list(args)
    parent = rest.pop(0) if rest and isinstance(rest[0], GObj) and rest[0].TYPE in ('figure', 'uipanel', 'uibuttongroup', 'uitab') else None
    pairs = name_value(rest, 0)
    parent = next((v for k, v in pairs if k.lower() == 'parent'), parent)
    if isinstance(parent, HArr) and parent.a.size == 1:
        parent = parent.a.flat[0]
    if isinstance(parent, GObj) and parent.TYPE in ('figure', 'uipanel', 'uibuttongroup', 'uitab'):
        f = parent
    a = Axes(f)
    apply_props(a, pairs)
    set_current_axes(a)
    a.touch()
    return a


def _make_polar(ax):
    ax.kind = 'polar'
    ax.props['DataAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
    ax.props['DataAspectRatioMode'] = 'manual'


@bi('polaraxes', arr=False)
def polaraxes(nargout, *args):
    """Polar axes in the current figure (or the figure or panel given first),
    with the properties given; they are made current."""
    a = axes(1, *args)
    _make_polar(a)
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
    if len(span) != 2 or min(span) < 1 or idx < 1:
        raise err('MATLAB:nexttile:InvalidSpan', 'The tile number is a positive integer and the span [rows columns].', 'nexttile')
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
            return a if nargout else None
    a = Axes(f)
    a.layout_cell = idx
    a.props['Position'] = np.array([pos])
    set_current_axes(a)
    a.touch()
    # (the axes only when asked for, as subplot gives them: a bare nexttile shows nothing)
    return a if nargout else None


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
            # one x and several values (or the other way): a line of one point for each
            if X.size == 1:
                return [(X.reshape(-1), np.array([v]), None) for v in Y.reshape(-1)]
            if Y.size == 1:
                return [(np.array([v]), Y.reshape(-1), None) for v in X.reshape(-1)]
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
    if len(data) == 1:
        raise err('MATLAB:line:InvalidData', 'line takes x and y data (and z), or name-value pairs.', 'line')
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


@bi('fplot', arr=False)
def fplot(nargout, *args):
    ax, rest = split_axes_arg(args)
    _need(rest, 1, 'fplot')
    f = rest[0]
    if is_str(f):
        raise err('MATLAB:fplot:FunctionText', 'Give fplot a function handle, such as @(x) sin(x).', 'fplot')
    if not isinstance(f, FH):
        raise err('MATLAB:fplot:InvalidFunction', 'The first input must be a function handle.', 'fplot')
    if len(rest) > 1 and isinstance(rest[1], FH) and (len(rest) < 3 or opt_str(rest[2]) is not None or numel(rest[2]) != 2):
        if len(rest) > 2 and opt_str(rest[2]) is None:
            raise err('MATLAB:fplot:InvalidLimits', 'The limits are [tmin tmax].', 'fplot')
    elif len(rest) > 1 and opt_str(rest[1]) is None and not isinstance(rest[1], FH) and numel(rest[1]) != 2:
        raise err('MATLAB:fplot:InvalidLimits', 'The limits are [xmin xmax].', 'fplot')
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


@bi('fpolarplot', arr=False)
def fpolarplot(nargout, *args):
    """fpolarplot(f), fpolarplot(f, [a b]), then a line spec and name-value pairs: the curve r = f(theta) in polar axes."""
    ax, rest = split_axes_arg(args)
    _need(rest, 1, 'fpolarplot')
    f = rest[0]
    if not isinstance(f, FH):
        raise err('MATLAB:fpolarplot:InvalidFunction', 'The first input must be a function handle or a symbolic expression.', 'fpolarplot')
    rest = list(rest[1:])
    lims = [0.0, 2 * math.pi]
    if rest and opt_str(rest[0]) is None:
        v = darr(rest[0]).reshape(-1)
        if v.size != 2 or not np.all(np.isfinite(v.real)) or v.dtype.kind == 'c' or v[0] >= v[1]:
            raise err('MATLAB:fpolarplot:InvalidInterval', 'The interval is [thetamin thetamax], increasing and finite.', 'fpolarplot')
        lims = [float(v[0]), float(v[1])]
        rest = rest[1:]
    t = np.linspace(lims[0], lims[1], 1000)
    try:
        r = arr(f.scall(1, out(t.reshape(1, -1)))).astype(float).reshape(-1)
        if r.size != t.size:
            raise MError('', 'scalar')
    except MError:
        r = np.array([float(arr(f.scall(1, float(v))).reshape(-1)[0]) for v in t])
    return polarplot(nargout, *(([ax] if ax else []) + [out(t.reshape(1, -1)), out(r.reshape(1, -1))] + rest))


# ---- scatter, bar, histogram and other series ------------------------------------------------------------

def _series_color(ax, given=None):
    return given if given is not None else ax.next_color()


def _color_word(v):
    """A colour given by name or hex code, as scatter(x, y, sz, 'red')."""
    s = opt_str(v)
    s = s.strip().lower() if s is not None else ''
    return s in NAMED or (s.startswith('#') and len(s) in (4, 7))


@bi('scatter', 'scatter3', arr=False)
def scatter(nargout, *args):
    ax, rest = split_axes_arg(args)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 5:
        data.append(rest.pop(0))
    if len(data) == 3 and rest and _color_word(rest[0]):
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
    three = False          # scatter(x, y, sz, c): scatter3 has a function of its own
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


@bi('scatter3', arr=False)
def scatter3(nargout, *args):
    ax, rest = split_axes_arg(args)
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 5:
        data.append(rest.pop(0))
    if len(data) == 4 and rest and _color_word(rest[0]):
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
    _need(data, 1)
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
    for j in range(k):
        h = Series(ax, 'bar')
        y = Y[:, j]
        h.props['XData'] = X.reshape(1, -1)
        h.props['YData'] = y.reshape(1, -1)
        h.props['BarWidth'] = width
        h.props['Horizontal'] = horizontal
        h.group = hs
        h.layout = layout
        c = color if color is not None else tuple(float(v) for v in COLOR_ORDER[(int(ax.props['ColorOrderIndex']) - 1) % 7])
        if color is None:
            ax.next_color()
        h.props['FaceColor'] = c
        h.extra['fc'] = c
        h.props['EdgeColor'] = (0.0, 0.0, 0.0)
        hs.append(h)
    bar_layout(hs[0])
    for h in hs:
        apply_props(h, pairs)
    ax.touch()
    return handles_out(hs, col=False) if nargout else None


def _xy_pairs(h):
    """A series' XData and YData as vectors of one length (the shorter's)."""
    y = np.asarray(h.props['YData'], float).reshape(-1)
    x = np.asarray(h.props['XData'], float).reshape(-1)
    if x.size != y.size:
        x = x[:y.size] if x.size > y.size else np.arange(1, y.size + 1, dtype=float)
    return x, y


def bar_layout(h):
    """Where the bars of h's group stand: side by side about their x (or
    stacked), a group as wide as BarWidth of the spacing of x, from
    BaseValue. Worked out when they are made and again when XData, YData,
    BarWidth, BaseValue or Horizontal changes."""
    hs = [g for g in getattr(h, 'group', None) or [h] if g.valid]
    k = len(hs)
    stacked = getattr(h, 'layout', 'grouped') == 'stacked'
    pos = neg = None
    for j, g in enumerate(hs):
        X, y = _xy_pairs(g)
        n = y.size
        dx = float(np.min(np.diff(np.sort(X)))) if X.size > 1 else 1.0
        dx = dx if dx > 0 else 1.0
        group_w = float(g.props['BarWidth']) * dx
        base_value = float(np.asarray(g.props['BaseValue'], float).reshape(-1)[0]) if numel(g.props['BaseValue']) else 0.0
        if stacked:
            if pos is None or pos.size != n:
                pos = np.full(n, base_value)
                neg = np.full(n, base_value)
            base = np.where(y >= 0, pos, neg)
            top = base + y
            pos = np.where(y >= 0, top, pos)
            neg = np.where(y < 0, top, neg)
            xs, w = X, group_w
        else:
            base = np.full(n, base_value)
            top = y
            if k > 1:
                xs = X + (j - (k - 1) / 2) * (group_w / k)
                w = group_w / k * 0.9
            else:
                xs, w = X, group_w
        g.extra.update(xs=np.asarray(xs, float), bottom=base.astype(float), top=top.astype(float), width=float(w))
        g.touch()


Series.RELAYOUT['bar'] = (('XData', 'YData', 'BarWidth', 'BaseValue', 'Horizontal'), bar_layout)


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
    _need(rest, 1, 'histogram')
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
    _need(data, 1)
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
    for j in range(Y.shape[1]):
        h = Series(ax, 'area')
        h.props['XData'] = X.reshape(1, -1)
        h.props['YData'] = Y[:, j].reshape(1, -1)
        h.props['BaseValue'] = base
        h.group = hs
        c = ax.next_color()
        h.props['FaceColor'] = c
        h.extra['fc'] = c
        hs.append(h)
    area_layout(hs[0])
    apply_props_all(hs, name_value(rest, 0))
    ax.touch()
    return handles_out(hs, col=False) if nargout else None


def area_layout(h):
    """The areas of h's group stacked: the first from BaseValue up to its
    YData, each next one on the one before. Again when XData, YData or
    BaseValue changes."""
    hs = [g for g in getattr(h, 'group', None) or [h] if g.valid]
    cum = None
    for j, g in enumerate(hs):
        _, y = _xy_pairs(g)
        base = float(np.asarray(g.props['BaseValue'], float).reshape(-1)[0]) if numel(g.props['BaseValue']) else 0.0
        if cum is None or cum.size != y.size:
            cum = np.full(y.size, base)
        top = y.astype(float) if j == 0 else cum + y
        g.extra.update(top=np.asarray(top, float), bottom=cum.astype(float))
        cum = np.asarray(top, float)
        g.touch()


Series.RELAYOUT['area'] = (('XData', 'YData', 'BaseValue'), area_layout)


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
    if rest and opt_str(rest[0]) is not None and parse_linespec(opt_str(rest[0])) is not None and opt_lower(rest[0]) not in LINE_PROPS:
        spec = parse_linespec(opt_str(rest.pop(0)))
    _need(data, 1)
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
    _need(rest, 1, 'pie')
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
    h.props['Labels'] = list(labels if labels else pct_text)
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
    _need(data, 1)
    if len(data) == 1:
        rho = darr(data[0]).reshape(-1)
        theta = np.linspace(0, 2 * np.pi, rho.size)
    else:
        theta, rho = darr(data[0]), darr(data[1])
    ax = newplot(ax, box=False)
    _make_polar(ax)
    groups = [{'x': out(theta), 'y': out(rho), 'z': None, 'spec': None}]
    pairs = []
    if rest and opt_str(rest[0]) is not None and parse_linespec(opt_str(rest[0])) is not None:
        groups[0]['spec'] = parse_linespec(opt_str(rest.pop(0)))
    pairs = name_value(rest, 0)
    hs = _make_lines(ax, groups, pairs)
    ax.touch()
    return handles_out(hs) if nargout else None


@bi('polarscatter', arr=False)
def polarscatter(nargout, *args):
    """scatter in polar axes: the angles (in radians) and radii as scatter's
    x and y, with its sizes, colours, markers and 'filled'."""
    h = scatter(1, *args)
    ax = h.parent
    _make_polar(ax)
    ax.touch()
    return h if nargout else None


def _bubbles(nargout, args, name, three=False):
    """bubblechart, bubblechart3 and polarbubblechart: a BubbleChart whose
    bubbles' areas grow with the sizes, between the axes' BubbleSizeRange."""
    ax, rest = split_axes_arg(args)
    k = 4 if three else 3
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < k + 1:
        data.append(rest.pop(0))
    if len(data) == k and rest and _color_word(rest[0]):
        data.append(rest.pop(0))
    if len(data) < k:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', name)
    if len(rest) % 2:
        raise err('MATLAB:InputParser:ParamMissingValue', 'Name-value arguments must come in pairs.', name)
    xyz = [darr(d).reshape(-1) for d in data[:k - 1]]
    sz = np.asarray(darr(data[k - 1]), float).reshape(-1)
    n = xyz[0].size
    if any(v.size != n for v in xyz) or sz.size not in (1, n):
        what = 'X, Y, Z' if three else 'X, Y'
        raise err(f'MATLAB:{name}:DataLengthMismatch',
                  f'{what} and the sizes must have the same number of elements, or the size be one number for all.', name)
    ax = newplot(ax, box=not three)
    if three and (ax.props['NextPlot'] != 'add' or not ax.is3d()):
        set3d(ax)
    h = Series(ax, 'bubblechart')
    h.props['XData'] = xyz[0].reshape(1, -1)
    h.props['YData'] = xyz[1].reshape(1, -1)
    if three:
        h.props['ZData'] = xyz[2].reshape(1, -1)
    h.props['SizeData'] = sz.reshape(1, -1)
    c = data[k] if len(data) > k else None
    color = None
    if c is not None and numel(c):
        if is_str(c):
            color = to_color(c)
        else:
            ca = darr(c)
            if ca.size == 3 and n != 3:
                color = to_color(ca)
            elif ca.ndim == 2 and ca.shape[1] == 3 and ca.shape[0] == n:
                h.extra['rgb'] = ca
            else:
                h.props['CData'] = ca.reshape(1, -1)
    if color is None and not np.size(h.props['CData']) and 'rgb' not in h.extra:
        color = ax.next_color()
    if color is not None:
        h.props['Color'] = color
    h.props['MarkerFaceColor'] = 'flat'
    h.props['MarkerEdgeColor'] = 'flat'
    h.props['MarkerFaceAlpha'] = 0.6
    apply_props(h, [(opt_str(rest[i]), rest[i + 1]) for i in range(0, len(rest), 2)])
    ax.touch()
    return h


@bi('bubblechart', arr=False)
def bubblechart(nargout, *args):
    h = _bubbles(nargout, args, 'bubblechart')
    return h if nargout else None


@bi('bubblechart3', arr=False)
def bubblechart3(nargout, *args):
    h = _bubbles(nargout, args, 'bubblechart3', three=True)
    return h if nargout else None


@bi('polarbubblechart', arr=False)
def polarbubblechart(nargout, *args):
    """bubblechart in polar axes: angles in radians and radii as x and y."""
    h = _bubbles(nargout, args, 'polarbubblechart')
    _make_polar(h.parent)
    h.parent.touch()
    return h if nargout else None


@bi('bubblesize', arr=False)
def bubblesize(nargout, *args):
    ax, rest = split_axes_arg(args)
    nargchk(rest, 0, 1, 'bubblesize')
    ax = ax or gca_()
    if not rest:
        return ax.get_value('BubbleSizeRange')
    ax.set_value('BubbleSizeRange', darr(rest[0]))
    ax.touch()
    return None


@bi('bubblelim', arr=False)
def bubblelim(nargout, *args):
    return _lim(args, 'Bubble', nargout)


def quiver_scale(h):
    """How long the arrows are drawn: the longest as long as the grid's
    spacing times AutoScaleFactor (0: as given). Again when the data or
    AutoScaleFactor changes."""
    X, Y = np.asarray(h.props['XData'], float), np.asarray(h.props['YData'], float)
    U, V = np.asarray(h.props['UData'], float), np.asarray(h.props['VData'], float)
    W = np.asarray(h.props['WData'], float) if numel(h.props['WData']) else None
    scale = float(np.asarray(h.props['AutoScaleFactor'], float).reshape(-1)[0]) if numel(h.props['AutoScaleFactor']) else 0.9
    s = 1.0
    if scale != 0 and X.size and U.size == V.size and (W is None or W.size == U.size):
        xs = np.unique(X.reshape(-1))
        ys = np.unique(Y.reshape(-1))
        dx = np.min(np.diff(xs)) if xs.size > 1 else 1.0
        dy = np.min(np.diff(ys)) if ys.size > 1 else 1.0
        if xs.size > 1 and ys.size > 1 and xs.size * ys.size <= X.size:
            d = math.sqrt(dx * dy) if dx > 0 and dy > 0 else max(dx, dy, 1.0)
        elif xs.size > 1 and ys.size > 1:
            # points not on a grid (a mesh's nodes): the room each has in the area they cover; the smallest step
            # between x values, near nothing for scattered points, drew the arrows 1e-17 long
            d = math.sqrt((xs[-1] - xs[0]) * (ys[-1] - ys[0]) / X.size)
        else:
            rng = max(X.max() - X.min(), Y.max() - Y.min() if Y.size else 1.0, 1e-9)
            d = rng / math.sqrt(max(X.size, 1))
        L = np.sqrt(U ** 2 + V ** 2 + (W ** 2 if W is not None else 0))
        mx = np.nanmax(L) if L.size else 0
        s = scale * d / mx if mx > 0 else 1.0
    h.extra['scale'] = float(s)
    h.touch()


Series.RELAYOUT['quiver'] = (('XData', 'YData', 'ZData', 'UData', 'VData', 'WData', 'AutoScaleFactor'), quiver_scale)


def _quiver_data(data, fn):
    """quiver's X, Y, U, V or quiver3's X, Y, Z, U, V, W, each the size of
    U (X and Y given as vectors along U's columns and rows are spread over
    the grid), and the scale."""
    three = fn == 'quiver3'
    short, full = (4, 6) if three else (2, 4)
    if len(data) in (full, full + 1):
        grid = False
    elif len(data) in (short, short + 1):
        grid = True
    else:
        raise err(f'MATLAB:{fn}:nargin',
                  'quiver3 takes Z, U, V and W, or X, Y, Z, U, V and W, and then a scale.' if three
                  else 'quiver takes U and V, or X, Y, U and V, and then a scale.', fn)
    scale = 0.9
    if len(data) in (short + 1, full + 1):
        sc = data.pop()
        if isinstance(sc, (Char, Str, str)) and opt_lower(sc) == 'off':
            scale = 0.0
        elif numel(sc) != 1 or isinstance(sc, (Char, Str, str)):
            raise err(f'MATLAB:{fn}:BadScale', "The scale is a number, or 'off'.", fn)
        else:
            scale = float(num(sc))
    A = [darr(d) for d in data]
    names = ('X', 'Y', 'Z', 'U', 'V', 'W') if three else ('X', 'Y', 'U', 'V')
    if grid:
        ref = A[0]
        m, n = (ref.shape[0], int(np.prod(ref.shape[1:]))) if ref.ndim else (1, 1)
        X, Y = np.meshgrid(np.arange(1, n + 1, dtype=float), np.arange(1, m + 1, dtype=float))
        A = [X.reshape(ref.shape), Y.reshape(ref.shape)] + A
    U = A[3] if three else A[2]
    same = names[2:]                       # Z, U, V, W or U, V: all the size of U
    for nm, a in zip(same, A[2:]):
        if a.shape != U.shape:
            raise err(f'MATLAB:{fn}:SizeMismatch', f"{', '.join(same[:-1])} and {same[-1]} must be the same size.", fn)
    X, Y = A[0], A[1]
    if X.shape != U.shape or Y.shape != U.shape:
        vec = lambda a: a.ndim <= 2 and 1 in a.shape
        if vec(X) and vec(Y) and U.ndim == 2 and X.size == U.shape[1] and Y.size == U.shape[0]:
            X, Y = np.meshgrid(X.reshape(-1), Y.reshape(-1))
        elif X.size == U.size and Y.size == U.size and vec(X) and vec(Y) and vec(U):
            X, Y = X.reshape(U.shape), Y.reshape(U.shape)
        else:
            raise err(f'MATLAB:{fn}:SizeMismatch',
                      f"{', '.join(names[:-1])} and {names[-1]} must be the same size (X and Y may be vectors along U's columns and rows).", fn)
    return [X, Y] + A[2:], scale


@bi('quiver', arr=False)
def quiver(nargout, *args):
    return _quiver(nargout, 'quiver', args)


@bi('quiver3', arr=False)
def quiver3(nargout, *args):
    return _quiver(nargout, 'quiver3', args)


def _quiver(nargout, fn, args):
    """quiver(X, Y, U, V) and quiver3(X, Y, Z, U, V, W): arrows from each
    point, scaled so that they don't overlap (a scale, or 'off'); a LineSpec
    and name-value pairs follow, and 'filled' is taken."""
    ax, rest = split_axes_arg(args)
    rest = [r for r in rest if not (isinstance(r, (Char, Str)) and opt_lower(r) == 'filled')]
    most = 7 if fn == 'quiver3' else 5
    data = []
    while rest and len(data) < most and (opt_str(rest[0]) is None or (opt_lower(rest[0]) == 'off' and len(data) in ((4, 6) if fn == 'quiver3' else (2, 4)))):
        data.append(rest.pop(0))
    spec = None
    if rest and opt_str(rest[0]) is not None and parse_linespec(opt_str(rest[0])) is not None and opt_lower(rest[0]) not in LINE_PROPS:
        spec = parse_linespec(opt_str(rest.pop(0)))
    arrays, scale = _quiver_data(data, fn)
    three = fn == 'quiver3'
    ax = newplot(ax, box=not three)
    if three and (ax.props['NextPlot'] != 'add' or not ax.is3d()):
        set3d(ax)
    h = Series(ax, 'quiver')
    keys = ('XData', 'YData', 'ZData', 'UData', 'VData', 'WData') if three else ('XData', 'YData', 'UData', 'VData')
    for k, a in zip(keys, arrays):
        h.props[k] = a.astype(float)
    h.props['AutoScaleFactor'] = float(scale)
    quiver_scale(h)
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


def given_levels(v):
    """Levels given for contours, each once and in order: [v v] is the one level v (it traced every line twice)."""
    return sorted({float(x) for x in np.asarray(v, float).reshape(-1)})


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
    _need(data, 1)
    if len(data) == 2:
        raise err('MATLAB:contour:InvalidData', 'Give Z, or X, Y and Z.')
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
            levels = given_levels(lv)
    spec = None
    if rest and opt_str(rest[0]) is not None and parse_linespec(opt_str(rest[0])) is not None and opt_lower(rest[0]) not in ('linewidth', 'linestyle', 'levellist', 'showtext', 'labelspacing', 'linecolor', 'fill', 'facealpha', 'edgecolor', 'levelstep'):
        spec = parse_linespec(opt_str(rest.pop(0)))
    pairs = name_value(rest, 0)
    show_text = False
    linecolor = None
    keep = []
    for k, v in pairs:
        kl = k.lower()
        if kl == 'levellist':
            levels = given_levels(darr(v))
        elif kl == 'showtext':
            show_text = py_str(v).lower() == 'on' if is_str(v) else bool(num(v))
        elif kl in ('linecolor', 'edgecolor'):
            linecolor = to_color(v, ('flat', 'none', 'auto'))
        elif kl == 'levelstep':
            pass
        else:
            keep.append((k, v))
    X, Y, Z = _grid_xyz(data)
    given = levels is not None
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
    h.props['LevelListMode'] = 'manual' if given or nlev is not None else 'auto'
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


def contour_trace(h):
    """A contour's lines traced again at its levels: LevelList when set
    (LevelListMode manual), else levels chosen for ZData. When LevelList,
    LevelListMode, XData, YData, ZData or Fill changes."""
    Z = np.asarray(h.props['ZData'], float)
    if Z.ndim != 2 or Z.size == 0 or h.extra.get('lines') is None:
        return
    X = np.asarray(h.props['XData'], float)
    Y = np.asarray(h.props['YData'], float)
    if X.shape != Z.shape or Y.shape != Z.shape:
        X, Y = np.meshgrid(X.reshape(-1)[:Z.shape[1]] if X.size >= Z.shape[1] else np.arange(1, Z.shape[1] + 1.0),
                           Y.reshape(-1)[:Z.shape[0]] if Y.size >= Z.shape[0] else np.arange(1, Z.shape[0] + 1.0))
    if h.props.get('LevelListMode') == 'manual' and numel(h.props['LevelList']):
        levels = [float(v) for v in np.asarray(h.props['LevelList'], float).reshape(-1)]
    else:
        levels = contour_levels(Z, None, bool(h.props['Fill']))
        h.props['LevelList'] = np.array([levels], float)
    lines = [(lev, marching_squares(X, Y, Z, lev)) for lev in levels]
    flat, lev_of = [], []
    for lev, polys in lines:
        for xs, ys in polys:
            flat.append(np.column_stack([xs, ys]))
            flat.append(np.array([[np.nan, np.nan]]))
            lev_of.append(lev)
    h.extra.update(levels=np.array(levels, float), paths=[{'level': float(lev), 'xy': None} for lev, _ in lines],
                   lines=np.vstack(flat) if flat else np.zeros((0, 2)), lineLevels=np.array(lev_of, float),
                   matrix=contour_matrix(lines))
    h.touch()


Series.RELAYOUT['contour'] = (('LevelList', 'LevelListMode', 'XData', 'YData', 'ZData', 'Fill'), contour_trace)


def _pie_labels(h):
    labels = h.props.get('Labels')
    if isinstance(labels, list) and labels:
        h.extra['labels'] = list(labels)
        h.touch()


Series.RELAYOUT['pie'] = (('Labels',), _pie_labels)


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
            levels = given_levels(lv)
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
    _need(data, 1)
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
    # imshow(I, R) and imshow(I, [low high], R): the image placed where an imref2d says, its axes in world coordinates
    ref = next((v for v in args[1:] if getattr(v, 'cls', None) == 'imref2d'), None)
    args = tuple(v for v in args if v is not ref)
    a = arr(args[0])
    rng = None
    if len(args) > 1 and opt_str(args[1]) is None and a.ndim == 2:
        cmap = darr(args[1])
        if cmap.ndim == 2 and cmap.shape[1] == 3 and cmap.shape[0] >= 1 and cmap.size != 2:
            # imshow(X, map): an indexed image shown in its colours (indices from 0 in integer classes, from 1 in floating ones)
            k = a.astype(float) - (0.0 if a.dtype.kind in 'iub' else 1.0)
            k = np.clip(np.nan_to_num(np.floor(k), nan=0.0), 0, cmap.shape[0] - 1).astype(int)
            args = (out(np.asarray(cmap, float)[k]),) + tuple(args[2:])
            a = arr(args[0])
    if len(args) > 1 and opt_str(args[1]) is None:
        r = darr(args[1]).reshape(-1)
        rng = list(r) if r.size == 2 else None
        if r.size == 0:
            fin = a[np.isfinite(a)] if a.dtype.kind == 'f' else a
            rng = [float(fin.min()), float(fin.max())]
    if ref is not None:
        if tuple(a.shape[:2]) != tuple(ref.size):
            raise err('MATLAB:imshow:SizeMismatch', "The image's size is not the size the spatial reference was made for.", 'imshow')
        # the first and last pixels' centres
        place = [out(np.array([[ref.xl[0] + ref.dx / 2, ref.xl[1] - ref.dx / 2]])), out(np.array([[ref.yl[0] + ref.dy / 2, ref.yl[1] - ref.dy / 2]]))]
    else:
        place = []
    if a.ndim == 3:
        h = _image(place + [out(a.astype(float) / (255.0 if a.dtype == np.uint8 else 1.0)) if a.dtype != np.float64 else args[0]], 1, False)
    else:
        if a.dtype == np.uint8:
            rng = rng or [0.0, 255.0]
        elif a.dtype.kind == 'b':
            rng = [0.0, 1.0]
        else:
            rng = rng or [0.0, 1.0]
        h = _image(place + [out(a.astype(float))], 1, True)
        ax = gca_()
        ax.props['CLim'] = np.array([rng])
        ax.props['CLimMode'] = 'manual'
        ax.props['Colormap'] = colormap_by_name('gray', 256)
    ax = gca_()
    ax.props['DataAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
    ax.props['DataAspectRatioMode'] = 'manual'
    ax.props['Visible'] = ref is not None
    ax.touch()
    return h if nargout else None


@bi('fill', 'fill3', arr=False)
def fill(nargout, *args):
    return _fill(nargout, args, False)


@bi('patch', arr=False)
def patch(nargout, *args):
    return _fill(nargout, args, True)


def _fill(nargout, args, low):
    """fill and fill3 draw as plot does (into axes cleared unless held);
    patch, a low-level function, adds to the axes as they are."""
    ax, rest = split_axes_arg(args)
    hs = []
    pairs = []
    if low and rest and type(rest[0]) is Struct:
        # patch(fv): a struct of faces, vertices (and facevertexcdata or other properties), then name-value pairs
        fv = rest.pop(0)
        if ax is None:
            ax = gca_()
        h = Patch(ax)
        for k in fv.f:
            h.setprop(k, fv.get1(k))
        apply_props(h, name_value(rest, 0))
        ax.touch()
        return h if nargout else None
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
    if ax is None:
        ax = gca_() if low else newplot(None)
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

def _shared(ax):
    """The axes that hold what yyaxis's two sides share (the title, the x-axis): the left side's, when ax is the right."""
    return ax.yy_owner if ax.yy_owner is not None else ax


def _label(args, which, nargout):
    ax, rest = split_axes_arg(args)
    if ax is None:
        ax = gca_()
    if which != 'ylabel':
        ax = _shared(ax)
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
    ax = _shared(ax or gca_())
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
    if rest and opt_str(rest[0]) is not None and opt_lower(rest[0]) in ('off', 'hide', 'show', 'toggle', 'boxoff', 'boxon'):
        s = opt_lower(rest[0])
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
    plotted = [c for c in reversed(ax.plot_children()) if c.TYPE in ('line', 'surface', 'patch', 'bar', 'histogram', 'area', 'stair', 'stem', 'errorbar', 'scatter', 'bubblechart', 'contour', 'quiver')]
    if ax.yy is not None and ax.yy.get('right') is not None:
        plotted += [c for c in reversed(ax.yy['right'].plot_children())]
    # an object whose handle is hidden is left out of the legend made from the axes
    plotted = [c for c in plotted if c.props.get('HandleVisibility', 'on') == 'on']
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
    # a name given empty stays empty (the entry without text); only the unnamed get dataN
    for k, o in enumerate(objs):
        if k >= len(names) and not o.props.get('DisplayName'):
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
    if rest and opt_str(rest[0]) is not None and opt_lower(rest[0]) in ('north', 'south', 'east', 'west', 'northoutside', 'southoutside', 'eastoutside', 'westoutside'):
        loc = opt_lower(rest.pop(0))
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


# ---- transparency: alpha, alphamap, alim --------------------------------------------------------

_ALPHA_WORDS = {'opaque': 1.0, 'clear': 0.0}
_ALPHA_DATA = ('x', 'y', 'z', 'color', 'rand')


def _alpha_from(o, word):
    """Alpha data made from an object's own data: its x, y or z values, its colour values, or random numbers; a value at each
    vertex (a patch's as a column), or None where the object has no such data."""
    from .elmat import RNG
    if o.TYPE == 'surface':
        z = np.asarray(o.get_value('ZData'), float)
        if word == 'z':
            return z
        if word == 'rand':
            return RNG.uniform(z.shape)
        if word == 'color':
            c = np.asarray(o.get_value('CData'), float)
            return c if c.shape == z.shape else None
        d = np.asarray(o.get_value('XData' if word == 'x' else 'YData'), float)
        if d.shape == z.shape:
            return d
        v = d.reshape(-1)
        return np.tile(v, (z.shape[0], 1)) if word == 'x' else np.tile(v.reshape(-1, 1), (1, z.shape[1]))
    if o.TYPE == 'patch':
        V = np.asarray(o.get_value('Vertices'), float)
        if V.ndim != 2 or not V.size:
            # a patch given by XData and YData (a face in each column): its vertices a column after another
            cols = [np.asarray(o.get_value(k), float).reshape(-1, order='F') for k in ('XData', 'YData', 'ZData')]
            cols = [c for c in cols if c.size]
            if len(cols) < 2 or cols[0].size != cols[1].size:
                return None
            V = np.column_stack(cols[:3] if len(cols) == 3 and cols[2].size == cols[0].size else cols[:2])
            if word == 'color':
                c = np.asarray(o.get_value('CData'), float)
                return c.reshape(-1, 1, order='F') if c.size == V.shape[0] else None
        if word == 'rand':
            return RNG.uniform((V.shape[0], 1))
        if word == 'color':
            c = np.asarray(o.get_value('FaceVertexCData'), float)
            return c.reshape(-1, 1) if c.ndim == 2 and c.shape[1:] == (1,) and c.shape[0] == V.shape[0] else None
        k = 'xyz'.index(word)
        return V[:, k:k + 1].copy() if k < V.shape[1] else None
    c = np.asarray(o.get_value('CData'))
    rows, cols = c.shape[:2]
    if word == 'rand':
        return RNG.uniform((rows, cols))
    if word == 'color':
        return np.asarray(c, float) if c.ndim == 2 else None
    if word == 'x':
        return np.tile(np.arange(1.0, cols + 1), (rows, 1))
    if word == 'y':
        return np.tile(np.arange(1.0, rows + 1).reshape(-1, 1), (1, cols))
    return None


@bi('alpha', arr=False)
def alpha(nargout, *args):
    """alpha(v), alpha(h, v): the transparency of the current axes' surfaces, patches and images (or of h, an axes standing
    for those in it). A number, 'opaque' or 'clear' sets FaceAlpha (an image's AlphaData); 'flat' and 'interp' make the
    faces take their opacities from the alpha data; an array, or 'x', 'y', 'z', 'color' or 'rand', gives that data (an
    object whose FaceAlpha was a number turns 'flat'); 'scaled', 'direct' and 'none' set AlphaDataMapping."""
    nargchk(args, 1, 2, 'alpha')
    rest = list(args)
    if len(rest) == 2 or (not is_str(rest[0]) and isinstance(rest[0], (GObj, HArr))):
        objs = []
        for o in _handles(rest.pop(0)):
            objs += list(o.children) if isinstance(o, Axes) else [o]
    else:
        objs = list(gca_().children)
    objs = [o for o in objs if o.valid and getattr(o, 'TYPE', None) in ('surface', 'patch', 'image')]
    v = rest[0]
    word = py_str(v).lower() if is_str(v) else None
    if word is not None and word not in (*_ALPHA_WORDS, *_ALPHA_DATA, 'flat', 'interp', 'texturemap', 'scaled', 'direct', 'none'):
        raise err('MATLAB:alpha:InvalidInput', f"alpha does not take '{py_str(v)}': a number, 'opaque', 'clear', 'flat', "
                  "'interp', 'x', 'y', 'z', 'color', 'rand', 'scaled', 'direct', 'none' or an array.", 'alpha')
    if word is None and not numel(v):
        raise err('MATLAB:alpha:InvalidInput', 'alpha takes a number or an array, not an empty one.', 'alpha')
    for o in objs:
        img = o.TYPE == 'image'
        if word in ('scaled', 'direct', 'none'):
            o.props['AlphaDataMapping'] = word
        elif word in _ALPHA_WORDS or (word is None and numel(v) == 1):
            o.props['AlphaData' if img else 'FaceAlpha'] = _ALPHA_WORDS[word] if word else float(num(v))
        elif word in ('flat', 'interp', 'texturemap'):
            if not img:
                o.props['FaceAlpha'] = word
        else:
            data = _alpha_from(o, word) if word else np.asarray(darr(v), float)
            if data is None:
                continue
            if o.TYPE == 'patch':
                o.props['FaceVertexAlphaData'] = data.reshape(-1, 1)
            else:
                o.props['AlphaData'] = data
            if not img and not isinstance(o.props.get('FaceAlpha'), str):
                o.props['FaceAlpha'] = 'flat'
        o.touch()
    return None


def _alphamap_named(name, n, cur, delta):
    """A named alphamap of n entries, or the current one changed: 'increase' and 'decrease' move every entry by delta
    (kept within 0 and 1), 'spin' turns it round by delta places."""
    t = np.linspace(0.0, 1.0, n)
    if name in ('default', 'rampup'):
        return t
    if name == 'rampdown':
        return t[::-1].copy()
    if name == 'vup':
        return 1 - np.abs(2 * t - 1)
    if name == 'vdown':
        return np.abs(2 * t - 1)
    if name == 'increase':
        return np.clip(cur + delta, 0, 1)
    if name == 'decrease':
        return np.clip(cur - delta, 0, 1)
    return np.roll(cur, int(round(delta)))


@bi('alphamap', arr=False)
def alphamap(nargout, *args):
    """alphamap(map), alphamap(name), alphamap(name, n or delta), alphamap(target, ...), m = alphamap: the opacities that
    alpha data scaled by ALim (or given as indices) are mapped to, for the current figure and its axes, or for the axes or
    figure given."""
    rest = list(args)
    target = None
    if rest and isinstance(rest[0], (Axes, Figure)):
        target = rest.pop(0)
    elif rest and isinstance(rest[0], HArr) and rest[0].a.size == 1 and isinstance(rest[0].a.flat[0], (Axes, Figure)):
        target = rest.pop(0).a.flat[0]
    f = target if isinstance(target, Figure) else gcf_() if target is None else None
    # the map read: the axes' or figure's given, else the current axes' (the figure's when it has none)
    src = target
    if src is None:
        ca = f.props.get('CurrentAxes')
        src = ca if ca is not None and ca.valid else f
    cur = np.asarray(src.props['Alphamap'], float).reshape(-1)
    if not rest:
        return cur.reshape(1, -1)
    nargchk(rest, 1, 2, 'alphamap')
    v = rest[0]
    if is_str(v):
        name = py_str(v).lower()
        names = ('default', 'rampup', 'rampdown', 'vup', 'vdown', 'increase', 'decrease', 'spin')
        if name not in names:
            raise err('MATLAB:alphamap:InvalidInput', f"alphamap does not know '{py_str(v)}': " + ', '.join(f"'{x}'" for x in names) + '.', 'alphamap')
        extra = float(num(rest[1])) if len(rest) > 1 else None
        if name in ('increase', 'decrease', 'spin'):
            m = _alphamap_named(name, cur.size, cur, extra if extra is not None else (1.0 if name == 'spin' else 0.1))
        else:
            n = int(extra) if extra is not None else 64
            if n < 1:
                raise err('MATLAB:alphamap:InvalidInput', 'The number of entries must be a positive integer.', 'alphamap')
            m = _alphamap_named(name, n, cur, 0.0)
    else:
        if len(rest) > 1:
            raise err('MATLAB:alphamap:InvalidInput', 'alphamap takes one map: a vector of values from 0 to 1.', 'alphamap')
        m = np.asarray(darr(v), float).reshape(-1)
        if not m.size or not np.all(np.isfinite(m)):
            raise err('MATLAB:alphamap:InvalidInput', 'An alphamap is a vector of finite values from 0 to 1.', 'alphamap')
    m = np.asarray(m, float).reshape(1, -1)
    if isinstance(target, Axes):
        target.props['Alphamap'] = m
        target.touch()
    else:
        f.props['Alphamap'] = m
        for a in f.axes_list():
            a.props['Alphamap'] = m.copy()
            a.touch()
        f.touch()
    return out(m) if nargout else None


@bi('alim', arr=False)
def alim(nargout, *args):
    """alim([amin amax]), alim auto | manual, lims = alim, m = alim('mode'), alim(ax, ...): the alpha data mapped to the
    first and last entries of the alphamap (AlphaDataMapping 'scaled')."""
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    if not rest:
        return ax.get_value('ALim')
    s = opt_str(rest[0])
    if s is not None:
        s = s.lower()
        if s == 'mode':
            return Char.of(ax.props['ALimMode'])
        if s not in ('auto', 'manual'):
            raise err('MATLAB:alim:InvalidInput', f"alim takes [amin amax], 'auto', 'manual' or 'mode', not '{s}'.", 'alim')
        if s == 'manual':
            ax.props['ALim'] = np.asarray(ax.get_value('ALim'), float).reshape(1, 2)
        ax.props['ALimMode'] = s
    else:
        ax.setprop('ALim', rest[0])
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


@bi('camzoom', nout=0, arr=False)
def camzoom(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    nargchk(rest, 1, 1, 'camzoom')
    f = float(num(rest[0], 'zoom factor', 'camzoom'))
    if not f > 0:
        raise err('MATLAB:camzoom:factor', 'The zoom factor must be greater than 0.', 'camzoom')
    va = float(ax.get_value('CameraViewAngle'))
    ax.set_value('CameraViewAngle', math.degrees(2 * math.atan(math.tan(math.radians(va) / 2) / f)))
    ax.touch()
    return None


@bi('camva', nout=1, arr=False)
def camva(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    nargchk(rest, 0, 1, 'camva')
    if not rest:
        return float(ax.get_value('CameraViewAngle'))
    s = opt_str(rest[0])
    if s is not None:
        s = s.lower()
        if s == 'mode':
            return Char.of(ax.props['CameraViewAngleMode'])
        if s == 'manual':
            ax.set_value('CameraViewAngle', float(ax.get_value('CameraViewAngle')))     # kept at what it is now
        elif s == 'auto':
            ax.set_value('CameraViewAngleMode', 'auto')
        else:
            raise err('MATLAB:camva:option', f"Unknown option '{s}': use a view angle, 'mode', 'auto' or 'manual'.", 'camva')
    else:
        ax.set_value('CameraViewAngle', rest[0])
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
    if which != 'Y':
        ax = _shared(ax)
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
    if not rest:
        return float(ax.props.get('XTickLabelRotation', 0.0))
    ax.props['XTickLabelRotation'] = float(num(rest[0]))
    ax.touch()
    return None


@bi('ytickangle', arr=False)
def ytickangle(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    if not rest:
        return float(ax.props.get('YTickLabelRotation', 0.0))
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
    given = next((rest[i + 1] for i in range(len(rest) - 1) if opt_str(rest[i]) is not None and opt_lower(rest[i]) == 'parent'), None)
    if isinstance(given, HArr) and given.a.size == 1:
        given = given.a.flat[0]
    if is_axes(given):
        ax = given
    ax = ax or gca_()
    if rest and opt_str(rest[0]) is not None and opt_lower(rest[0]) in Text._lower and len(rest) % 2 == 0:
        # text('Name', value, ...): no position or string first
        t = Text(ax)
        apply_props(t, name_value(rest, 0))
        ax.touch()
        return t if nargout else None
    data = []
    while rest and opt_str(rest[0]) is None and type(rest[0]) not in (Cell,) and len(data) < 3:
        data.append(rest.pop(0))
    if not rest or len(data) < 2:
        raise err('MATLAB:text:invalidInput', 'Not enough input arguments.', 'text')
    s = rest.pop(0)
    xs = darr(data[0]).reshape(-1)
    ys = darr(data[1]).reshape(-1)
    zs = darr(data[2]).reshape(-1) if len(data) > 2 else np.zeros(xs.size)
    strs = text_list(s) if type(s) in (Cell, Str) and numel(s) == xs.size and xs.size > 1 else None
    pairs = name_value(rest, 0)
    # x and y are in the Units the call names: text(0.05, 0.9, s, 'Units', 'normalized')
    units = [v for k, v in pairs if k.lower() == 'units']
    pairs = [(k, v) for k, v in pairs if k.lower() != 'units']
    hs = []
    for i in range(xs.size):
        t = Text(ax)
        if units:
            t.set_value('Units', units[-1])
        t.set_value('String', Char.of(strs[i]) if strs else s)
        t.props['Position'] = np.array([[float(xs[i]), float(ys[i]), float(zs[i])]])
        apply_props(t, pairs)
        hs.append(t)
    ax.touch()
    return handles_out(hs) if nargout else None


@bi('annotation', arr=False)
def annotation(nargout, *args):
    """annotation(type, x, y, ...) for a line, arrow, double arrow or text
    arrow; annotation(type, [x y w h], ...) for a rectangle, ellipse or text
    box; the figure (or a panel in it) may come first."""
    from ..graphics_base import SHAPES
    rest = list(args)
    f = None
    if rest and not is_str(rest[0]):
        h = _handles(rest.pop(0))[0]
        f = h.figure() if isinstance(h, GObj) else None
        if f is None:
            raise err('MATLAB:annotation:BadParent', 'The first input must be a figure, or the type of annotation.', 'annotation')
    f = f or gcf_()
    kind = sval(rest.pop(0), 'type', 'annotation').lower() if rest else 'line'
    C = SHAPES.get(kind)
    if C is None:
        raise err('MATLAB:annotation:BadType', f"Unknown annotation type '{kind}': use line, arrow, doublearrow, textarrow, "
                  'rectangle, ellipse or textbox.', 'annotation')
    a = C(f)
    if C.LINEAR and len(rest) >= 2 and opt_str(rest[0]) is None and opt_str(rest[1]) is None:
        a.set_value('X', rest.pop(0))
        a.set_value('Y', rest.pop(0))
    elif not C.LINEAR and rest and opt_str(rest[0]) is None:
        a.set_value('Position', rest.pop(0))
    if len(rest) % 2:
        raise err('MATLAB:annotation:NameValue', 'Properties must come in name-value pairs.', 'annotation')
    try:
        for i in range(0, len(rest), 2):
            a.setprop(sval(rest[i], 'property name', 'annotation'), rest[i + 1])
    except MError:
        a.delete_handle()
        raise
    f.touch()
    return a if nargout else None


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
    k = opt_str(rest[0])
    if k is not None:
        k = k.lower()
        if k == 'mode':
            return Char.of(ax.props.get('DataAspectRatioMode', 'auto'))
        if k in ('auto', 'manual'):
            ax.props['DataAspectRatioMode'] = k
            ax.touch()
            return None
        raise err('MATLAB:daspect:InvalidInput', "Give three positive numbers, 'auto', 'manual' or 'mode'.", 'daspect')
    if numel(rest[0]) != 3:
        raise err('MATLAB:daspect:InvalidInput', 'The ratio has three elements.', 'daspect')
    ax.setprop('DataAspectRatio', rest[0])
    return None


@bi('pbaspect', arr=False)
def pbaspect(nargout, *args):
    ax, rest = split_axes_arg(args)
    ax = ax or gca_()
    if not rest:
        return ax.props['PlotBoxAspectRatio']
    k = opt_str(rest[0])
    if k is not None:
        k = k.lower()
        if k == 'mode':
            return Char.of(ax.props.get('PlotBoxAspectRatioMode', 'auto'))
        if k in ('auto', 'manual'):
            ax.props['PlotBoxAspectRatioMode'] = k
            ax.touch()
            return None
        raise err('MATLAB:pbaspect:InvalidInput', "Give three positive numbers, 'auto', 'manual' or 'mode'.", 'pbaspect')
    if numel(rest[0]) != 3:
        raise err('MATLAB:pbaspect:InvalidInput', 'The ratio has three elements.', 'pbaspect')
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


# material's reflectances: ambient, diffuse and specular strength, specular exponent, specular colour reflectance
_MATERIALS = {'shiny': (0.3, 0.6, 0.9, 20.0, 1.0), 'dull': (0.3, 0.8, 0.0, 10.0, 1.0), 'metal': (0.3, 0.3, 1.0, 25.0, 0.5)}
_REFLECT = ('AmbientStrength', 'DiffuseStrength', 'SpecularStrength', 'SpecularExponent', 'SpecularColorReflectance')


@bi('material', arr=False)
def material(nargout, *args):
    """material shiny | dull | metal | default, material([ka kd ks n sc]), material(h, ...): how the surfaces and patches of the
    current axes (or h) reflect light: their ambient, diffuse and specular strengths, specular exponent and specular colour
    reflectance (the first three to five of them given as numbers)."""
    nargchk(args, 1, 2, 'material')
    rest = list(args)
    objs = None
    if len(rest) == 2 or (rest and not is_str(rest[0]) and isinstance(rest[0], (GObj, HArr))):
        objs = _handles(rest.pop(0))
    if objs is None:
        objs = [c for c in gca_().children if c.TYPE in ('surface', 'patch')]
    v = rest[0]
    if is_str(v):
        name = py_str(v).lower()
        if name not in (*_MATERIALS, 'default'):
            raise err('MATLAB:material:InvalidInput', "material takes 'shiny', 'dull', 'metal', 'default' or [ka kd ks n sc].", 'material')
        vals = _MATERIALS.get(name)
    else:
        vals = tuple(float(x) for x in np.asarray(darr(v), float).reshape(-1))
        if not 3 <= len(vals) <= 5:
            raise err('MATLAB:material:InvalidInput', 'material takes three to five numbers: [ka kd ks n sc].', 'material')
    for o in objs:
        if getattr(o, 'TYPE', None) not in ('surface', 'patch'):
            continue
        for k, x in zip(_REFLECT, vals if vals is not None else (type(o).DEFAULTS[k] for k in _REFLECT)):
            o.props[k] = float(x)
        o.touch()
    return None


@bi('rotate3d', 'zoom', 'pan', 'datacursormode', 'brush', 'linkaxes', 'linkprop', 'hidden', 'whitebg', 'movegui', 'uistack', 'refresh', 'shg', arr=False)
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
            h = handle_of_number(x)
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


@bi('ishandle', 'isgraphics', 'ishghandle', 'isvalid')
def ishandle(nargout, *args):
    v = args[0]
    if isinstance(v, HArr):
        return out(np.array([getattr(h, 'valid', True) for h in v.a.reshape(-1)], bool).reshape(v.a.shape))
    if isinstance(v, GObj):
        return bool(v.valid)
    if isinstance(v, Obj):
        return bool(getattr(v, 'valid', True))
    if type(v) in (float, np.ndarray):
        a = np.asarray(v, float)
        res = [handle_of_number(x) is not None for x in a.reshape(-1)]
        return out(np.array(res, bool).reshape(a.shape)) if a.size != 1 else res[0]
    return False


@bi('findobj', arr=False)
def findobj(nargout, *args):
    return _find(args, False)


@bi('findall', arr=False)
def findall(nargout, *args):
    return _find(args, True)


def shown_test(hidden=False):
    """Whether findobj reaches an object: its HandleVisibility is 'on', or
    'callback' while a callback runs; findall, or the root's
    ShowHiddenHandles, reaches every object."""
    if hidden or ROOT.props.get('ShowHiddenHandles'):
        return lambda o: True
    from ..uievents import STACK
    in_callback = bool(STACK)

    def shown(o):
        hv = o.props.get('HandleVisibility', 'on')
        return hv == 'on' or (hv == 'callback' and in_callback)
    return shown


def _find(args, hidden):
    """The given objects (the root when none are) and those under them that
    pass the tests: property-value pairs, -regexp, -property and -function,
    joined by -and (between pairs too), -or and -xor from left to right, with
    -not turning the next one; flat or -depth d looks d levels down."""
    rest = list(args)
    shown = shown_test(hidden)
    if rest and (isinstance(rest[0], (GObj, HArr)) or type(rest[0]) in (float, np.ndarray)):
        roots = _handles(rest.pop(0))
    else:
        roots = [ROOT]
    depth = None
    terms = []
    i = 0
    while i < len(rest):
        s = opt_str(rest[i])
        low = s.lower() if s is not None else None
        if s is None:
            i += 1
        elif low == 'flat':
            depth = 0
            i += 1
        elif low == '-depth' and i + 1 < len(rest):
            d = num(rest[i + 1])
            depth = None if d == math.inf else int(d)
            i += 2
        elif low in ('-and', '-or', '-xor', '-not'):
            terms.append((low, None))
            i += 1
        elif low == '-regexp' and i + 2 < len(rest):
            terms.append(('test', _regexp_test(sval(rest[i + 1], 'property name', 'findobj'), rest[i + 2])))
            i += 3
        elif low == '-property' and i + 1 < len(rest):
            terms.append(('test', _has_test(sval(rest[i + 1], 'property name', 'findobj'))))
            i += 2
        elif low == '-function' and i + 1 < len(rest):
            if i + 2 < len(rest) and opt_str(rest[i + 1]) is not None:
                terms.append(('test', _function_test(rest[i + 2], py_str(rest[i + 1]))))
                i += 3
            else:
                terms.append(('test', _function_test(rest[i + 1], None)))
                i += 2
        else:
            if i + 1 < len(rest):
                terms.append(('test', _find_test(s, rest[i + 1])))
            i += 2

    found = []

    def walk(o, d):
        found.append(o)
        if depth is not None and d >= depth:
            return
        # other handle objects (meta.property lists, ...) have no children
        for c in (STORE.figures.values() if o is ROOT else getattr(o, 'children', ())):
            if c.valid and shown(c):
                walk(c, d + 1)
    for r in roots:
        walk(r, 0)
    tests = [t for kind, t in terms if kind == 'test']
    if len(tests) < len(terms):
        res = [h for h in found if _combine(terms, h)]
    elif len(tests) == 1:
        res = list(filter(tests[0], found))
    else:
        res = [h for h in found if all(test(h) for test in tests)]
    return HArr.of(res, col=True)


def _combine(terms, h):
    res = None
    op = '-and'
    negate = False
    for kind, test in terms:
        if kind == '-not':
            negate = not negate
        elif kind != 'test':
            op = kind
        else:
            v = bool(test(h)) != negate
            negate = False
            if res is None:
                res = v
            elif op == '-and':
                res = res and v
            elif op == '-or':
                res = res or v
            else:
                res = res != v
            op = '-and'
    return True if res is None else res


def _regexp_test(k, v):
    import re
    from .strfun import _py_pattern
    try:
        rx = re.compile(_py_pattern(py_str(v)))
    except re.error as e:
        raise err('MATLAB:regexp:badPattern', f'The regular expression is not valid: {e}.', 'findobj')

    def test(h):
        x = _safe_value(h, k)
        return x is not None and is_str(x) and rx.search(py_str(x)) is not None
    return test


def _has_test(k):
    return lambda h: _safe_value(h, k) is not None


def _function_test(f, k):
    from ..ops import truth
    if not isinstance(f, FH):
        raise err('MATLAB:findobj:InvalidFunction', 'The value after -function is a function handle.', 'findobj')

    def test(h):
        x = h if k is None else _safe_value(h, k)
        return x is not None and truth(f.scall(1, x))
    return test


def _safe_value(h, k):
    try:
        return h.getprop(k)
    except MError:
        return None


def _find_test(k, v):
    """findobj's test of one property: text against the text an object keeps
    is compared as it is (programs ask for Tags over and over), anything else
    as isequal would."""
    from .core import _equal
    if k.lower() == 'type':
        want = py_str(v)
        return lambda h: getattr(h, 'TYPE', None) == want or (getattr(h, 'TYPE', None) is not None and _safe_text(h, k) == want)
    text = py_str(v) if is_str(v) and numel(v) <= max(1, len(py_str(v))) else None
    names = {}

    def test(h):
        c = names.get(type(h), _MISSING)
        if c is _MISSING:
            c = names[type(h)] = h.canon(k) if hasattr(h, 'canon') else None
        if c is not None and text is not None:
            raw = h.props.get(c, _MISSING)
            if isinstance(raw, str):
                return raw == text
        try:
            return _equal(h.getprop(k), v, False)
        except MError:
            return False
    return test


_MISSING = object()


def _safe_text(h, k):
    try:
        return py_str(h.getprop(k))
    except MError:
        return None


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


def _copy_tree(o, parent, made, attach=True):
    """A copy of a graphics object and everything under it, in parent (made
    maps id(original) to (original, copy) for the references fixed after)."""
    import copy
    from .. import graphics_base as GB
    c = copy.copy(o)
    c.id = next(GB._ids)
    STORE.objects[c.id] = c
    c.props = {k: (v.copy() if isinstance(v, np.ndarray) else list(v) if isinstance(v, list) else share(v)) for k, v in o.props.items()}
    c.parent = parent
    c.children = []
    c.valid = True
    if isinstance(getattr(o, 'extra', None), dict):
        c.extra = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in o.extra.items()}
    made[id(o)] = (o, c)
    if attach and parent is not None:
        parent.children.insert(0, c)
    for ch in reversed(o.children):
        if ch.valid:
            _copy_tree(ch, c, made)
    # the texts an axes or a colorbar holds outside its children
    for name in ('title', 'xlabel', 'ylabel', 'zlabel', 'subtitle', 'label'):
        tx = o.__dict__.get(name)
        if isinstance(tx, GObj) and tx not in o.children:
            setattr(c, name, _copy_tree(tx, c, made, attach=False))
    return c


def _repoint(made):
    """References among the copies point at the copies; one to an object not
    copied is dropped where it would tie the copy to the original's figure."""
    def to(v):
        return made[id(v)][1] if id(v) in made else v
    for o, c in made.values():
        for k, v in list(c.__dict__.items()):
            if k in ('parent', 'children', 'props', 'extra'):
                continue
            if isinstance(v, GObj):
                setattr(c, k, to(v) if id(v) in made else (None if k in ('legend', 'colorbar', 'yy_owner') else v))
            elif isinstance(v, list) and v and all(isinstance(x, GObj) for x in v):
                setattr(c, k, [to(x) for x in v if id(x) in made])
            elif k == 'yy' and isinstance(v, dict):
                c.yy = {**v, 'right': to(v['right'])} if v.get('right') is not None and id(v['right']) in made else None
        for k, v in c.props.items():
            if isinstance(v, GObj) and id(v) in made:
                c.props[k] = to(v)


@bi('copyobj', arr=False)
def copyobj(nargout, *args):
    """Copies of graphics objects, each with everything under it, in the new
    parent(s): an axes, a figure, a panel or a tab."""
    nargchk(args, 2, 3, 'copyobj')
    hs = _handles(args[0])
    parents = _handles(args[1])
    if len(parents) not in (1, len(hs)):
        raise err('MATLAB:copyobj:ParentSize', 'There must be one parent, or one for each object copied.', 'copyobj')
    made = {}
    copies = []
    for i, h in enumerate(hs):
        par = parents[0] if len(parents) == 1 else parents[i]
        if not isinstance(h, GObj) or not h.valid or h.TYPE in ('figure', 'root'):
            raise err('MATLAB:copyobj:InvalidObject', 'copyobj copies the objects in a figure (axes, lines, text, controls ...), '
                      'not a figure itself.', 'copyobj')
        if not isinstance(par, GObj) or not par.valid or par.TYPE not in ('figure', 'axes', 'uipanel', 'uibuttongroup', 'uitab', 'hggroup'):
            raise err('MATLAB:copyobj:InvalidParent', 'The new parent must be an axes, a figure, a panel or a tab.', 'copyobj')
        if h.TYPE in ('legend', 'colorbar') and not any(x is h.axes for x in hs):
            raise err('MATLAB:copyobj:LegendWithoutAxes', f'A {h.TYPE} is copied together with its axes: copyobj([ax, {h.TYPE[:3]}], parent).', 'copyobj')
        target = par.figure() if h.TYPE in ('legend', 'colorbar') else par
        copies.append(_copy_tree(h, target, made))
    _repoint(made)
    for c in copies:
        c.touch()
    if len(copies) == 1 and not isinstance(args[0], HArr):
        return copies[0]
    shape = args[0].a.shape if isinstance(args[0], HArr) else (1, len(copies))
    a = np.empty(len(copies), object)
    for i, c in enumerate(copies):
        a[i] = c
    return HArr(a.reshape(shape))


@bi('drawnow', aw=True, arr=False)
async def drawnow(nargout, *args):
    if flush_figures():
        # the page draws what was sent before the program goes on: a loop of drawnow sent faster than the page could draw,
        # and the drawings waiting their turn filled the page's memory
        await R.ask_page({'type': 'drawn'})
    if not any(opt_str(a) == 'nocallbacks' for a in args):
        from .. import uievents as E
        await E.process()
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


def _fsample(f, xr, yr, n=35, fn='fsurf'):
    if not isinstance(f, FH):
        raise err(f'MATLAB:{fn}:InvalidFunction', 'The first input must be a function handle of x and y.', fn)
    if len(xr) != 2 or len(yr) != 2:
        raise err(f'MATLAB:{fn}:InvalidLimits', 'The limits are [min max] for both, or [xmin xmax ymin ymax].', fn)
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
    _need(rest, 1, 'fsurf')
    f = rest[0]
    lim = darr(rest[1]).reshape(-1) if len(rest) > 1 and opt_str(rest[1]) is None else np.array([-5.0, 5.0])
    xr = lim[:2]
    yr = lim[2:4] if lim.size >= 4 else lim[:2]
    X, Y, Z = _fsample(f, xr, yr)
    return _surf(([ax] if ax else []) + [out(X), out(Y), out(Z)], nargout)


@bi('fcontour', 'ezcontour', arr=False)
def fcontour(nargout, *args):
    ax, rest = split_axes_arg(args)
    _need(rest, 1, 'fcontour')
    f = rest[0]
    lim = darr(rest[1]).reshape(-1) if len(rest) > 1 and opt_str(rest[1]) is None else np.array([-5.0, 5.0])
    X, Y, Z = _fsample(f, lim[:2], lim[2:4] if lim.size >= 4 else lim[:2], 60, 'fcontour')
    return _contour(([ax] if ax else []) + [out(X), out(Y), out(Z)], nargout)


# ---- sending the figures to the page -----------------------------------------------------------

def flush_figures():
    """Tell the page about the figures that changed (and those closed); True when something was sent."""
    hook = R.EVENT_HOOK[0]
    dirty = [f for f in STORE.dirty if f.valid]
    closed = list(STORE.closed)
    STORE.dirty.clear()
    STORE.closed.clear()
    if hook is None:
        return False
    if not dirty and not closed:
        return False
    figs = []
    for f in sorted(dirty, key=lambda f: f.order):
        try:
            figs.append(serialize_figure(f))
        except Exception as e:
            R.write(f'Warning: Figure {int(f.props["Number"])} could not be drawn: {e}\n', 'warn')
    cur = STORE.current.id if STORE.current is not None and STORE.current.valid else None
    hook({'type': 'figures', 'figures': figs, 'closed': closed, 'current': cur})
    from .. import uievents as E
    for f in dirty:
        E.shown(f)
    return True


R.FLUSH_FIGURES = flush_figures


# ---- saving pictures -----------------------------------------------------------------------------

# the picture files by extension, and print's -d devices
PICTURES = {'png': 'png', 'jpg': 'jpg', 'jpeg': 'jpg', 'bmp': 'bmp', 'tif': 'tif', 'tiff': 'tif', 'svg': 'svg', 'pdf': 'pdf', 'eps': 'eps'}
DEVICES = {'png': 'png', 'jpeg': 'jpg', 'jpg': 'jpg', 'bmp': 'bmp', 'bmp16m': 'bmp', 'bmp256': 'bmp', 'tiff': 'tif', 'tiffn': 'tif',
           'tif': 'tif', 'svg': 'svg', 'pdf': 'pdf', 'eps': 'eps', 'epsc': 'eps', 'eps2': 'eps', 'epsc2': 'eps'}


@bi('saveas', 'print', 'exportgraphics', aw=True, arr=False)
async def saveas(nargout, *args):
    """The figure as a picture file (PNG, JPEG, BMP, TIFF) or a vector file
    (SVG, PDF, EPS), by the file's extension or print's -d device; the page
    draws it. A .fig name writes a figure file."""
    import os
    import re
    fn = 'saveas'
    rest = list(args)
    f = None
    if rest and isinstance(rest[0], (Figure, Axes)):
        h = rest.pop(0)
        f = h if isinstance(h, Figure) else h.figure()
    f = f or gcf_()
    name = None
    fmt = None
    dpi = None
    i = 0
    while i < len(rest):
        s = opt_str(rest[i])
        i += 1
        if s is None:
            continue
        low = s.lower()
        if low == 'resolution' and i < len(rest):
            dpi = float(num(rest[i]))
            i += 1
        elif low in ('contenttype', 'backgroundcolor', 'colorspace', 'append') and i < len(rest):
            i += 1
        elif low.startswith('-d'):
            fmt = low[2:]
        elif re.fullmatch(r'-r\d+(\.\d*)?', low):
            dpi = float(low[2:])
        elif s.startswith('-'):
            continue
        elif name is None:
            name = s
        elif fmt is None:
            fmt = low
    if name is None and fmt in ('meta', 'bitmap'):
        # print -dmeta (or -dbitmap) with no file: the figure goes to the clipboard
        flush_figures()
        if not await R.ask_page({'type': 'copyfig', 'figure': f.id}):
            R.warn('MATLAB:print:clipboard', 'The figure could not be copied to the clipboard here.')
        return None
    if name is None:
        name = f'figure{int(f.props["Number"])}' if not f.is_dialog else 'dialog'
    ext = os.path.splitext(name)[1].lower().lstrip('.')
    if ext == 'fig' or (fmt == 'fig' and not ext):
        # a figure file, to open again with openfig
        return await _write_fig([f, Char.of(name if ext == 'fig' else name + '.fig')], fn, 0)
    if ext in PICTURES:
        kind = PICTURES[ext]
    elif fmt in DEVICES or (fmt is None and not ext):
        kind = DEVICES.get(fmt, 'png')
        if not ext:
            name += '.' + kind
    else:
        raise err('MATLAB:print:UnknownFormat', f"Unable to write {'a .' + ext if ext else 'the ' + str(fmt)} file here: the formats are "
                  '.png, .jpg, .bmp, .tif, .svg, .pdf, .eps and .fig.', fn)
    # the size: twice the screen's unless a resolution is given (96 dots an inch on screen)
    scale = 2.0 if not dpi else max(0.25, min(8.0, dpi / 96.0))
    from .iofun import abspath, files_changed
    p = abspath(name)
    flush_figures()
    data = await R.ask_page({'type': 'render', 'figure': f.id, 'format': kind, 'scale': scale})
    if data is None:
        raise err('MATLAB:print:noRenderer', 'The figure could not be drawn to a file here.', fn)
    import base64
    with open(p, 'wb') as fh:
        fh.write(base64.b64decode(data))
    files_changed(os.path.dirname(p))
    return None


# ---- figure files (.fig) ---------------------------------------------------------------------------

def _fig_file(name, fn, must_exist=True):
    import os
    from .iofun import abspath
    p = abspath(name if os.path.splitext(name)[1] else name + '.fig')
    if must_exist and not os.path.isfile(p):
        raise err(f'MATLAB:{fn}:FileNotFound', f"File '{name}' not found.", fn)
    return p


async def _read_fig(p, fn, visible=None):
    from .. import matfile as MF
    from ..figfile import load
    from .iofun import _need_h5py
    try:
        if MF.kind(p) == 'v73':
            await _need_h5py(fn)
        objs = load(p, visible)
    except MF.MatError as e:
        raise err(f'MATLAB:{fn}:notAFigure', f'{p} is not a figure file: {e}.', fn)
    flush_figures()
    return objs


@bi('openfig', aw=True, arr=False)
async def openfig(nargout, *args):
    nargchk(args, 1, 3, 'openfig')
    p = _fig_file(sval(args[0], 'file name', 'openfig'), 'openfig')
    opts = [opt_lower(a) for a in args[1:] if opt_str(a) is not None]
    if 'reuse' in opts:
        # the figure opened from this file before, brought forward
        same = [f for f in STORE.figures.values() if f.valid and f.props.get('FileName') == p]
        if same:
            STORE.current = same[-1]
            R.EVENT_HOOK[0] and R.EVENT_HOOK[0]({'type': 'raise', 'figure': same[-1].id})
            return same[-1] if nargout else None
    visible = Char.of('off') if 'invisible' in opts else (Char.of('on') if 'visible' in opts else None)
    objs = await _read_fig(p, 'openfig', visible)
    return handles_out(objs) if nargout else None


@bi('hgload', aw=True, arr=False)
async def hgload(nargout, *args):
    nargchk(args, 1, 2, 'hgload')
    objs = await _read_fig(_fig_file(sval(args[0], 'file name', 'hgload'), 'hgload'), 'hgload')
    if len(args) > 1:
        if type(args[1]) is not Struct:
            raise err('MATLAB:hgload:InvalidPropertyStruct', 'The second input is a struct of properties to set.', 'hgload')
        for o in objs:
            for k in args[1].f:
                o.setprop(k, args[1].get1(k))
        flush_figures()
    return handles_out(objs) if nargout else None


async def _write_fig(args, fn, nargout):
    import os
    from ..figfile import save
    from .iofun import files_changed
    rest = [a for a in args if not (is_str(a) and opt_str(a) is not None and opt_lower(a) in ('compact', 'all') or
                                    is_str(a) and opt_str(a) is not None and opt_str(a).startswith('-'))]
    objs = _handles(rest.pop(0)) if rest and not is_str(rest[0]) else [gcf_()]
    name = sval(rest[0], 'file name', fn) if rest else 'Untitled.fig'
    if any(not isinstance(o, GObj) or not o.valid for o in objs):
        raise err('MATLAB:hg:InvalidHandle', 'Invalid or deleted object.', fn)
    p = _fig_file(name, fn, must_exist=False)
    flush_figures()
    dropped = save(objs, p)
    files_changed(os.path.dirname(p))
    if dropped:
        R.warn(f'MATLAB:{fn}:functionHandles', 'Callbacks given as function handles are not kept in figure files written '
               'here (' + ', '.join(dropped) + '); text callbacks are.')
    from ..graphics_base import Shape
    if any(isinstance(c, Shape) and c.valid for o in objs for c in o.children):
        R.warn(f'MATLAB:{fn}:annotations', 'Annotations (arrows, text boxes and the like) are not kept in figure files written here.')
    return None


@bi('savefig', aw=True, arr=False)
async def savefig(nargout, *args):
    return await _write_fig(args, 'savefig', nargout)


@bi('hgsave', aw=True, arr=False)
async def hgsave(nargout, *args):
    return await _write_fig(args, 'hgsave', nargout)


@bi('open', ws=True, aw=True, arr=False)
async def open_(W, nargout, *args):
    """open name: a figure file opens as a figure, a MAT-file loads (into a
    struct, given an output), the rest goes to the Editor."""
    import os
    names = [sval(a, 'file name', 'open') for a in args]
    exts = {os.path.splitext(n)[1].lower() for n in names}
    if names and exts == {'.fig'}:
        objs = []
        for n in names:
            objs += await _read_fig(_fig_file(n, 'open'), 'open')
        return handles_out(objs) if nargout else None
    from .iofun import edit, load
    if len(names) == 1 and exts == {'.mat'}:
        return await load(W, nargout, *args)
    return edit(nargout, *args)


@bi('getframe', aw=True, arr=False)
async def getframe(nargout, *args):
    """A movie frame of the figure or axes as drawn: cdata (rows x columns x 3,
    uint8) and colormap ([]). The current axes unless a figure or axes is
    given; rect [left bottom width height] in pixels from its lower left."""
    import base64
    nargchk(args, 0, 2, 'getframe')
    rest = list(args)
    h = _handles(rest.pop(0))[0] if rest else None
    if h is None:
        f = gcf_()
        h = gca_(f) if f.axes_list() else f
    if isinstance(h, Axes) and h.yy_owner is not None:
        h = h.yy_owner
    if not isinstance(h, (Figure, Axes)):
        raise err('MATLAB:getframe:BadHandle', 'getframe takes a figure or an axes.', 'getframe')
    rect = [float(v) for v in darr(rest[0]).reshape(-1)] if rest else None
    if rect is not None and (len(rect) != 4 or not all(math.isfinite(v) for v in rect)):
        raise err('MATLAB:getframe:BadRect', 'The rectangle must be [left bottom width height], in pixels.', 'getframe')
    f = h if isinstance(h, Figure) else h.figure()
    flush_figures()
    res = await R.ask_page({'type': 'frame', 'figure': f.id, 'axes': h.id if isinstance(h, Axes) else None, 'rect': rect})
    if not res:
        raise err('MATLAB:getframe:noPicture', 'The figure could not be drawn as a picture here.', 'getframe')
    w, hh = int(res['width']), int(res['height'])
    raw = base64.b64decode(res['data']) if w and hh else b''
    return Struct.scalar({'cdata': np.frombuffer(raw, np.uint8).reshape(hh, w, 3).copy(), 'colormap': EMPTY()})


def _frame_parts(F, fn):
    if type(F) is not Struct or 'cdata' not in F.f:
        raise err(f'MATLAB:{fn}:BadFrame', 'Frames are structs with the fields cdata and colormap, as getframe makes them.', fn)
    cdata = list(F.f['cdata'].reshape(-1, order='F'))
    cmaps = list(F.f['colormap'].reshape(-1, order='F')) if 'colormap' in F.f else [EMPTY()] * len(cdata)
    return cdata, cmaps


@bi('frame2im', nout=2)
def frame2im(nargout, *args):
    nargchk(args, 1, 1, 'frame2im')
    cdata, cmaps = _frame_parts(args[0], 'frame2im')
    if len(cdata) != 1:
        raise err('MATLAB:frame2im:OneFrame', 'frame2im takes one frame: index the movie, F(k).', 'frame2im')
    return (share(cdata[0]), share(cmaps[0])) if nargout > 1 else share(cdata[0])


@bi('im2frame')
def im2frame(nargout, *args):
    nargchk(args, 1, 2, 'im2frame')
    a = arr(args[0])
    cmap = args[1] if len(args) > 1 else EMPTY()
    if a.ndim == 3 and a.shape[2] == 3:
        if a.dtype.kind == 'f':
            a = np.round(np.clip(np.nan_to_num(a), 0.0, 1.0) * 255).astype(np.uint8)
        elif a.dtype != np.uint8:
            a = np.clip(a, 0, 255).astype(np.uint8)
        cdata = a
    elif a.ndim == 2:
        if not numel(cmap):
            raise err('MATLAB:im2frame:NeedColormap', 'An indexed image needs its colormap: im2frame(X, map).', 'im2frame')
        cdata = share(args[0])
    else:
        raise err('MATLAB:im2frame:BadImage', 'The image must be m-by-n (with a colormap) or m-by-n-by-3.', 'im2frame')
    return Struct.scalar({'cdata': cdata, 'colormap': share(cmap)})


@bi('movie', aw=True, arr=False)
async def movie(nargout, *args):
    """Plays a movie's frames in the current axes (or the axes or figure
    given): n times, fps frames a second."""
    rest = list(args)
    target = None
    if rest and isinstance(rest[0], (Figure, Axes)):
        target = rest.pop(0)
    if not rest:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'movie')
    cdata, cmaps = _frame_parts(rest.pop(0), 'movie')
    n = darr(rest[0]).reshape(-1) if rest else np.array([1.0])
    fps = float(num(rest[1])) if len(rest) > 1 else 12.0
    if not (math.isfinite(fps) and fps > 0):
        raise err('MATLAB:movie:BadFPS', 'The number of frames a second must be positive.', 'movie')
    order = list(range(len(cdata)))
    if n.size > 1:
        order = [int(k) - 1 for k in n[1:]]
        if any(k < 0 or k >= len(cdata) for k in order):
            raise err('MATLAB:movie:BadFrame', 'The frames to play must be numbers of the movie\'s frames.', 'movie')
    reps = int(n[0]) if n.size else 1
    if reps < 0:
        order = order + order[::-1]
    ax = target if isinstance(target, Axes) else gca_(target if isinstance(target, Figure) else None)
    ax = newplot(ax)
    img = Image(ax)
    ax.props['YDir'] = 'reverse'
    ax.props['View'] = np.array([[0.0, 90.0]])
    ax.props['DataAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
    ax.props['DataAspectRatioMode'] = 'manual'
    ax.props['Visible'] = False
    for _ in range(max(abs(reps), 1) if order else 0):
        for k in order:
            c = arr(cdata[k])
            img.props['CData'] = c
            img.props['CDataMapping'] = 'direct'
            img.props['XData'] = np.array([[1.0, float(c.shape[1])]])
            img.props['YData'] = np.array([[1.0, float(c.shape[0])]])
            if numel(cmaps[k]):
                ax.props['Colormap'] = as_colormap(arr(cmaps[k]))
            ax.touch()
            await R.sleep(1.0 / fps)
    return None


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
