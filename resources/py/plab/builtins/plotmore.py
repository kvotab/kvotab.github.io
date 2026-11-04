"""More of the graphics core: rectangle, hggroup and hgtransform with
makehgtform, rotate, refreshdata, tick formats and angles, polar axes'
ticks and limits, gplot and trees (treelayout, treeplot, etreeplot),
colours (validatecolor, rgb2hex, hex2rgb, brighten, rgbplot, spinmap) and
3-D helpers (surfnorm, shrinkfaces, isocolors, lightangle)."""
import math

import numpy as np

from . import bi as _register
from . import REG
from ._util import err, nargchk, out, num, opt_str, opt_lower, is_str, darr, arr
from ..values import MError, Char, Cell, Struct, Str, Obj, Sparse, numel, py_str, text_list, EMPTY, F64
from ..graphics_base import (HArr, GObj, Axes, Figure, Line, Surface, Patch, Text, Light, Rectangle, Group, Transform,
                             to_color, NAMED)
from .. import runtime as R
from .graphics import split_axes_arg, newplot, apply_props, name_value, gca_, gcf_, set3d, parse_linespec


def bi(*names, **kw):
    def deco(fn):
        if kw.get('aw'):
            async def wrapped(*a):
                try:
                    return await fn(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, KeyError, OverflowError, ZeroDivisionError) as e:
                    raise err(f'MATLAB:{names[0]}:InvalidInput', str(e) or 'The input is not valid.', names[0]) from None
        else:
            def wrapped(*a):
                try:
                    return fn(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, KeyError, OverflowError, ZeroDivisionError) as e:
                    raise err(f'MATLAB:{names[0]}:InvalidInput', str(e) or 'The input is not valid.', names[0]) from None
        wrapped.__name__ = fn.__name__
        wrapped.__doc__ = fn.__doc__
        return _register(*names, **kw)(wrapped)
    return deco


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


def _target_axes(args, fn):
    """(axes, the rest) for f(ax, ...) or f(...) on the current axes."""
    a = list(args)
    if a and isinstance(a[0], Axes):
        return a[0], a[1:]
    if a and isinstance(a[0], HArr) and a[0].a.size == 1 and isinstance(a[0].a.flat[0], Axes):
        return a[0].a.flat[0], a[1:]
    return gca_(), a


def _parent_of(rest):
    """The axes, or a group, a primitive goes in: 'Parent' among the pairs, or the current axes."""
    for i in range(0, len(rest) - 1):
        if (opt_lower(rest[i]) or '') == 'parent':
            return rest[i + 1]
    return None


# ---- rectangle, groups and transforms ---------------------------------------------------------------------------

@bi('rectangle', arr=False)
def rectangle(nargout, *args):
    """r = rectangle('Position', [x y w h], 'Curvature', [cx cy], ...): a box in
    the current axes (or the axes given first), its corners rounded by
    Curvature (1 makes an ellipse); FaceColor 'none' and EdgeColor black
    unless set."""
    ax, rest = split_axes_arg(args)
    ax = ax if ax is not None else gca_()
    if len(rest) % 2:
        raise err('MATLAB:rectangle:nargin', "rectangle takes names and values ('Position', 'Curvature', 'FaceColor', ...).", 'rectangle')
    h = Rectangle(ax)
    h.outline()
    apply_props(h, name_value(rest, 0))
    ax.touch()
    return h if nargout else None


def _group(cls, args, fn):
    a = list(args)
    parent = None
    if a and isinstance(a[0], (Axes, Group)):
        parent = a.pop(0)
    if len(a) % 2:
        raise err(f'MATLAB:{fn}:nargin', f'{fn} takes an axes or a group, then names and values.', fn)
    parent = parent if parent is not None else gca_()
    h = cls(parent)
    apply_props(h, name_value(a, 0))
    if isinstance(h.parent, GObj):
        h.parent.touch()
    return h


@bi('hggroup', arr=False)
def hggroup(nargout, *args):
    """g = hggroup(ax, ...): a group in the axes; objects made with 'Parent', g join it, shown and hidden together."""
    return _group(Group, args, 'hggroup')


@bi('hgtransform', arr=False)
def hgtransform(nargout, *args):
    """t = hgtransform(ax, ...): a group whose children are drawn through its Matrix (4-by-4, makehgtform)."""
    return _group(Transform, args, 'hgtransform')


def _rot(axis, t):
    c, s = math.cos(t), math.sin(t)
    x, y, z = axis
    C = 1 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s, 0],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s, 0],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C, 0],
                     [0, 0, 0, 1.0]])


@bi('makehgtform', arr=False)
def makehgtform(nargout, *args):
    """M = makehgtform('translate', [tx ty tz], 'scale', s or [sx sy sz],
    'xrotate', t, 'yrotate', t, 'zrotate', t, 'axisrotate', [ax ay az], t):
    a 4-by-4 transform, the steps multiplied in order (the last applied
    first); angles in radians."""
    M = np.eye(4)
    a = list(args)
    i = 0
    while i < len(a):
        k = opt_lower(a[i])
        if k is None:
            raise err('MATLAB:makehgtform:BadOption', 'Each step is named by text.', 'makehgtform')
        if k == 'translate':
            v = np.asarray(darr(a[i + 1]), F64).reshape(-1)
            if v.size == 1:
                v = np.array([v[0], v[0], v[0]])
            T = np.eye(4)
            T[:3, 3] = v[:3]
            i += 2
        elif k == 'scale':
            v = np.asarray(darr(a[i + 1]), F64).reshape(-1)
            if v.size == 1:
                v = np.array([v[0], v[0], v[0]])
            T = np.diag([v[0], v[1], v[2], 1.0])
            i += 2
        elif k in ('xrotate', 'yrotate', 'zrotate'):
            ax_ = {'xrotate': (1, 0, 0), 'yrotate': (0, 1, 0), 'zrotate': (0, 0, 1)}[k]
            T = _rot(ax_, float(num(a[i + 1])))
            i += 2
        elif k == 'axisrotate':
            u = np.asarray(darr(a[i + 1]), F64).reshape(-1)
            n = np.linalg.norm(u)
            if n == 0:
                raise err('MATLAB:makehgtform:ZeroAxis', 'The axis of rotation is not zero.', 'makehgtform')
            T = _rot(u / n, float(num(a[i + 2])))
            i += 3
        else:
            raise err('MATLAB:makehgtform:BadOption', f"'{k}' is not a step: translate, scale, xrotate, yrotate, zrotate or axisrotate.", 'makehgtform')
        M = M @ T
    return M


def _direction(v):
    a = np.asarray(darr(v), F64).reshape(-1)
    if a.size == 2:
        th, ph = math.radians(a[0]), math.radians(a[1])
        a = np.array([math.cos(ph) * math.cos(th), math.cos(ph) * math.sin(th), math.sin(ph)])
    if a.size != 3 or not np.linalg.norm(a) > 0:
        raise err('MATLAB:rotate:BadDirection', 'The direction is [theta phi] in degrees, or a vector [x y z].', 'rotate')
    return a / np.linalg.norm(a)


@bi('rotate', arr=False)
def rotate(nargout, *args):
    """rotate(h, direction, alpha, origin): the data of lines, surfaces,
    patches and text turned by alpha degrees about the axis through origin
    (the middle of the axes' limits) along direction ([theta phi] in degrees
    or [x y z]), by the right-hand rule."""
    nargchk(args, 3, 4, 'rotate')
    hs = list(args[0].a.reshape(-1)) if isinstance(args[0], HArr) else [args[0]]
    if not all(isinstance(h, GObj) for h in hs):
        raise err('MATLAB:rotate:BadHandle', 'The first input is graphics objects.', 'rotate')
    u = _direction(args[1])
    alpha = math.radians(float(num(args[2])))
    M = _rot(u, alpha)[:3, :3]
    for h in hs:
        if len(args) > 3:
            o = np.asarray(darr(args[3]), F64).reshape(-1)
        else:
            ax = h.parent
            while ax is not None and not isinstance(ax, Axes):
                ax = ax.parent
            o = np.array([float(np.mean(np.asarray(ax.get_value(k), float))) for k in ('XLim', 'YLim', 'ZLim')]) if ax is not None else np.zeros(3)
        o = np.concatenate([o, np.zeros(3 - o.size)])[:3] if o.size < 3 else o[:3]

        def turn(x, y, z):
            P = np.vstack([x.reshape(-1) - o[0], y.reshape(-1) - o[1], z.reshape(-1) - o[2]])
            Q = M @ P
            return (Q[0] + o[0]).reshape(x.shape), (Q[1] + o[1]).reshape(x.shape), (Q[2] + o[2]).reshape(x.shape)
        p = h.props
        if h.TYPE == 'text':
            pos = np.asarray(p['Position'], float).reshape(-1)
            pos = np.concatenate([pos, np.zeros(3 - pos.size)])[:3]
            x, y, z = turn(pos[:1], pos[1:2], pos[2:3])
            p['Position'] = np.array([[x[0], y[0], z[0]]])
        elif h.TYPE == 'patch' and numel(p.get('Vertices')) and not isinstance(h, Rectangle):
            V = np.asarray(p['Vertices'], float)
            z = V[:, 2] if V.shape[1] > 2 else np.zeros(V.shape[0])
            x, y, z = turn(V[:, 0], V[:, 1], z)
            p['Vertices'] = np.column_stack([x, y, z])
        elif h.TYPE in ('line', 'surface', 'patch'):
            X, Y = np.asarray(p['XData'], float), np.asarray(p['YData'], float)
            Z = np.asarray(p['ZData'], float) if numel(p['ZData']) else None
            if h.TYPE == 'surface' and Z is not None and X.size != Z.size:
                X, Y = np.meshgrid(X.reshape(-1), Y.reshape(-1))
            x, y, z = turn(X, Y, Z if Z is not None else np.zeros(X.shape))
            p['XData'], p['YData'], p['ZData'] = x, y, z
        else:
            raise err('MATLAB:rotate:BadType', f"rotate turns lines, surfaces, patches and text, not a {h.TYPE}.", 'rotate')
        h.touch()
    return None


@bi('refreshdata', ws=True, aw=True, arr=False)
async def refreshdata(W, nargout, *args):
    """refreshdata(h, workspace): each object's XDataSource, YDataSource and
    ZDataSource evaluated again (in the caller's workspace, or 'base') and
    their values made its data; h is the current figure when not given, and
    every object in it is looked at."""
    nargchk(args, 0, 2, 'refreshdata')
    a = list(args)
    where = 'caller'
    if a and is_str(a[-1]):
        where = opt_lower(a.pop())
        if where not in ('caller', 'base'):
            raise err('MATLAB:refreshdata:BadWorkspace', "The workspace is 'caller' or 'base'.", 'refreshdata')
    roots = (list(a[0].a.reshape(-1)) if isinstance(a[0], HArr) else [a[0]]) if a else [gcf_()]
    ws = R.BASE if where == 'base' else W
    found = []

    def walk(o):
        found.append(o)
        for c in getattr(o, 'children', []):
            if c.valid:
                walk(c)
    for r in roots:
        walk(r)
    for o in found:
        for k in ('XDataSource', 'YDataSource', 'ZDataSource'):
            src = o.props.get(k) if hasattr(o, 'props') else None
            if not src:
                continue
            expr = src if isinstance(src, str) else py_str(src)
            fn, _ = R.compile_command(f'plabRefreshValue__ = {expr};', ws)
            try:
                await fn(ws)
                v = ws['plabRefreshValue__']
            finally:
                try:
                    del ws['plabRefreshValue__']
                except KeyError:
                    pass
            o.setprop(k[:5], v)
    return None


# ---- ticks ---------------------------------------------------------------------------------------------------------

def _tickformat(which):
    def f(nargout, *args):
        from ..glayout import tick_format
        ax, rest = _target_axes(args, f'{which.lower()}tickformat')
        fmts = getattr(ax, 'tickfmt', None)
        if fmts is None:
            fmts = ax.tickfmt = {}
        if not rest:
            return Char.of(fmts.get(which) or '%g')
        s = opt_str(rest[0])
        if s is None:
            raise err(f'MATLAB:{which.lower()}tickformat:BadFormat', "The format is text: a pattern such as '%.2f', or usd, eur, gbp, jpy, degrees, percentage or auto.", f'{which.lower()}tickformat')
        fmts[which] = tick_format(s)
        ax.touch()
        return None
    f.__doc__ = (f'{which.lower()}tickformat(fmt) or {which.lower()}tickformat(ax, fmt): the {which} tick labels written by a pattern '
                 "('%.2f', '%,d', '$%,.2f', ...) or 'usd', 'eur', 'gbp', 'jpy', 'degrees', 'percentage'; 'auto' as before; "
                 f'fmt = {which.lower()}tickformat gives it.')
    return f


for _w in 'XYZ':
    bi(f'{_w.lower()}tickformat', arr=False)(_tickformat(_w))


@bi('ztickangle', arr=False)
def ztickangle(nargout, *args):
    """ztickangle(angle) or ztickangle(ax, angle): the z tick labels' rotation in degrees; a = ztickangle gives it."""
    ax, rest = _target_axes(args, 'ztickangle')
    if not rest:
        return float(ax.props.get('ZTickLabelRotation', 0.0))
    ax.props['ZTickLabelRotation'] = float(num(rest[0]))
    ax.touch()
    return None


def _polar_axes(args, fn):
    ax, rest = _target_axes(args, fn)
    if ax.kind != 'polar':
        raise err(f'MATLAB:{fn}:NotPolar', f'{fn} is for polar axes (polarplot, polaraxes).', fn)
    return ax, rest


def _polar_prop(fn, prop, kind):
    def f(nargout, *args):
        ax, rest = _polar_axes(args, fn)
        if not rest:
            return ax.getprop(prop)
        v = rest[0]
        s = opt_lower(v) if is_str(v) and kind != 'labels' else None
        if s in ('auto', 'manual'):
            ax.setprop(prop + 'Mode', Char.of(s))
            ax.touch()
            return None
        if s == 'mode' or (is_str(v) and opt_lower(v) == 'mode' and kind != 'labels'):
            return Char.of(ax.props[prop + 'Mode'])
        ax.setprop(prop, v)
        ax.touch()
        return None
    f.__doc__ = f"{fn}(values) or {fn}(pax, values): the polar axes' {prop}; 'auto' gives it back to the axes; v = {fn} reads it."
    return f


for _fn, _prop, _kind in (('rticks', 'RTick', 'ticks'), ('thetaticks', 'ThetaTick', 'ticks'), ('rticklabels', 'RTickLabel', 'labels'),
                          ('thetaticklabels', 'ThetaTickLabel', 'labels'), ('rlim', 'RLim', 'lim')):
    bi(_fn, arr=False)(_polar_prop(_fn, _prop, _kind))


# ---- graphs and trees ------------------------------------------------------------------------------------------------

@bi('gplot', nout=2, arr=False)
def gplot(nargout, *args):
    """gplot(A, xy, LineSpec): the graph of the adjacency matrix A drawn with
    its nodes at the rows of xy, an edge for each nonzero A(i,j);
    [X, Y] = gplot(A, xy) gives the coordinates (an edge, then NaN) instead."""
    nargchk(args, 2, 3, 'gplot')
    A = args[0].m.toarray() if isinstance(args[0], Sparse) else np.asarray(darr(args[0]))
    xy = np.asarray(darr(args[1]), F64)
    n = A.shape[0]
    if A.ndim != 2 or A.shape[0] != A.shape[1] or xy.shape[0] != n or xy.shape[1] < 2:
        raise err('MATLAB:gplot:SizeMismatch', 'A is n-by-n and xy has a row (x y) for each of its n nodes.', 'gplot')
    i, j = np.nonzero(A)
    pairs = sorted({(min(a, b), max(a, b)) for a, b in zip(i.tolist(), j.tolist())})
    X = np.full(3 * len(pairs), np.nan)
    Y = np.full(3 * len(pairs), np.nan)
    for k, (a, b) in enumerate(pairs):
        X[3 * k:3 * k + 2] = xy[[a, b], 0]
        Y[3 * k:3 * k + 2] = xy[[a, b], 1]
    if nargout:
        return _outs(nargout, out(X.reshape(-1, 1)), out(Y.reshape(-1, 1)))
    extra = [args[2]] if len(args) > 2 else []
    REG['plot'].fn(0, out(X.reshape(-1, 1)), out(Y.reshape(-1, 1)), *extra)
    return None


def _children(parent):
    n = parent.size
    kids = [[] for _ in range(n)]
    roots = []
    for i, p in enumerate(parent):
        if p == 0:
            roots.append(i)
        elif 1 <= p <= n:
            kids[int(p) - 1].append(i)
        else:
            raise err('MATLAB:treelayout:BadParent', f'Each parent is a node from 1 to {n}, or 0 for a root.', 'treelayout')
    return kids, roots


@bi('treelayout', nout=4, arr=False)
def treelayout(nargout, *args):
    """[x, y, h, s] = treelayout(parent): positions for the nodes of the
    trees given by their parents (0 for a root): the leaves evenly across in
    the order a depth-first walk meets them, each parent above the middle of
    its children; y by depth (roots at the top), both inside (0, 1); h is the
    height (levels) and s how many nodes lie on the chain from the root down
    to the first node with other than one child (PyLAB's layout)."""
    nargchk(args, 1, 2, 'treelayout')
    parent = np.asarray(darr(args[0]), F64).reshape(-1)
    n = parent.size
    kids, roots = _children(parent)
    depth = np.zeros(n, int)
    x = np.zeros(n)
    leaves = [0]

    def place(v, d):
        stack = [(v, d, 0)]
        order = []
        while stack:
            node, dd, state = stack.pop()
            depth[node] = dd
            if state == 0:
                stack.append((node, dd, 1))
                for c in reversed(kids[node]):
                    stack.append((c, dd + 1, 0))
            else:
                if kids[node]:
                    x[node] = float(np.mean([x[c] for c in kids[node]]))
                else:
                    leaves[0] += 1
                    x[node] = leaves[0]
    for r in roots:
        place(r, 1)
    h = int(depth.max()) if n else 0
    nl = max(leaves[0], 1)
    xs = x / (nl + 1)
    ys = (h - depth + 1) / (h + 1) if h else np.zeros(n)
    s = 0
    if len(roots) == 1:
        v = roots[0]
        s = 1
        while len(kids[v]) == 1:
            v = kids[v][0]
            s += 1
    return _outs(nargout, out(xs.reshape(1, -1)), out(ys.reshape(1, -1)), float(h), float(s))


@bi('treeplot', arr=False)
def treeplot(nargout, *args):
    """treeplot(parent, nodeSpec, edgeSpec): the trees drawn by treelayout:
    nodes as circles ('o'), edges as lines ('-'), the height below."""
    nargchk(args, 1, 3, 'treeplot')
    parent = np.asarray(darr(args[0]), F64).reshape(-1)
    x, y, h, _ = treelayout(4, args[0])
    x, y = np.asarray(x).reshape(-1), np.asarray(y).reshape(-1)
    ex, ey = [], []
    for i, p in enumerate(parent):
        if p > 0:
            ex += [x[int(p) - 1], x[i], np.nan]
            ey += [y[int(p) - 1], y[i], np.nan]
    node = args[1] if len(args) > 1 and numel(args[1]) else Char.of('o')
    edge = args[2] if len(args) > 2 and numel(args[2]) else Char.of('-')
    REG['plot'].fn(0, out(x.reshape(-1, 1)), out(y.reshape(-1, 1)), node, out(np.array(ex).reshape(-1, 1)), out(np.array(ey).reshape(-1, 1)), edge)
    ax = gca_()
    ax.setprop('XLim', np.array([[0.0, 1.0]]))
    ax.setprop('YLim', np.array([[0.0, 1.0]]))
    ax.setprop('XTick', EMPTY())
    ax.setprop('YTick', EMPTY())
    REG['xlabel'].fn(0, Char.of(f'height = {int(h)}'))
    return None


@bi('etreeplot', arr=False)
def etreeplot(nargout, *args):
    """etreeplot(A, nodeSpec, edgeSpec): the elimination tree of A + A' drawn by treeplot."""
    nargchk(args, 1, 3, 'etreeplot')
    import scipy.sparse as sp
    from .. import sparsemat as SPM
    M = args[0].m if isinstance(args[0], Sparse) else sp.csc_matrix(np.asarray(darr(args[0])))
    S = (abs(M) + abs(M.T)).tocsc()
    p = REG['etree'].fn(1, SPM.make(S))
    return treeplot(0, p, *args[1:])


# ---- colours ------------------------------------------------------------------------------------------------------------

def _hex_of(rgb, short=False):
    v = [int(round(float(c) * 255)) for c in rgb]
    s = ''.join(f'{x:02X}' for x in v)
    if short and all(s[i] == s[i + 1] for i in (0, 2, 4)):
        s = s[0] + s[2] + s[4]
    return '#' + s


def _colors_of(v, fn):
    """The colours of names, hex codes or RGB rows, as an n-by-3 double array."""
    if isinstance(v, (Char, Str, Cell)):
        names = text_list(v) if isinstance(v, (Str, Cell)) else ([py_str(Char(v.a[i:i + 1, :])) for i in range(v.a.shape[0])] if v.a.shape[0] > 1 else [py_str(v)])
        rows = []
        for s in names:
            try:
                rows.append(to_color(Char.of(str(s).strip())))
            except MError:
                raise err(f'MATLAB:{fn}:invalidColor', f"'{s}' is not a colour name or a hex code.", fn) from None
        return np.array(rows, F64).reshape(-1, 3)
    a = np.asarray(arr(v, fn))
    if a.ndim != 2 or a.shape[1] != 3:
        raise err(f'MATLAB:{fn}:invalidColor', 'RGB colours are rows of three values.', fn)
    if a.dtype.kind in 'iu':
        info = np.iinfo(a.dtype)
        return (a.astype(F64) - info.min) / (info.max - info.min) if info.min < 0 else a.astype(F64) / info.max
    a = a.astype(F64)
    if np.any(a < 0) or np.any(a > 1) or not np.all(np.isfinite(a)):
        raise err(f'MATLAB:{fn}:invalidColor', 'Double RGB values run from 0 to 1.', fn)
    return a


@bi('validatecolor', arr=False)
def validatecolor(nargout, *args):
    """RGB = validatecolor(colors, 'one' or 'multiple'): colour names, hex
    codes ('#FF8800', '#F80') or RGB rows (doubles 0 to 1, or integers over
    their range) checked and given as RGB rows of doubles; 'one' (default)
    wants exactly one colour."""
    nargchk(args, 1, 2, 'validatecolor')
    many = (opt_lower(args[1]) if len(args) > 1 else 'one')
    if many not in ('one', 'multiple'):
        raise err('MATLAB:validatecolor:BadSize', "The second input is 'one' or 'multiple'.", 'validatecolor')
    c = _colors_of(args[0], 'validatecolor')
    if many == 'one' and c.shape[0] != 1:
        raise err('MATLAB:validatecolor:wrongColorSize', 'Specify one color only.', 'validatecolor')
    return c


@bi('rgb2hex', arr=False)
def rgb2hex(nargout, *args):
    """hex = rgb2hex(RGB, 'Shorthand', tf): RGB rows (or an m-by-n-by-3 image)
    as hex codes '#RRGGBB', a string for each; 'Shorthand' true gives '#RGB'
    where it can."""
    nargchk(args, 1, 3, 'rgb2hex')
    short = False
    if len(args) == 3:
        if (opt_lower(args[1]) or '') != 'shorthand':
            raise err('MATLAB:rgb2hex:BadOption', "rgb2hex's option is 'Shorthand'.", 'rgb2hex')
        v = args[2]
        short = (opt_lower(v) in ('on', 'true')) if is_str(v) else bool(np.all(np.asarray(darr(v)) != 0))
    a = np.asarray(arr(args[0], 'rgb2hex'))
    if a.ndim == 3 and a.shape[2] == 3:
        shape = a.shape[:2]
        rows = np.stack([a[:, :, k].reshape(-1, order='F') for k in range(3)], axis=1)
    elif a.ndim == 2 and a.shape[1] == 3:
        shape = (a.shape[0], 1)
        rows = a
    else:
        raise err('MATLAB:rgb2hex:invalidColor', 'RGB is an m-by-3 matrix or an m-by-n-by-3 array.', 'rgb2hex')
    c = _colors_of(rows, 'rgb2hex')
    S = np.array([_hex_of(r, short) for r in c], object).reshape(shape, order='F')
    return Str(S)


@bi('hex2rgb', arr=False)
def hex2rgb(nargout, *args):
    """RGB = hex2rgb(hex): hex codes ('#RRGGBB' or '#RGB') as RGB rows of
    doubles from 0 to 1; an array of n strings gives n rows (a 2-D string
    array, an m-by-n-by-3 array)."""
    nargchk(args, 1, 1, 'hex2rgb')
    v = args[0]
    if isinstance(v, Str):
        shape = v.a.shape
        codes = [s or '' for s in v.a.reshape(-1, order='F')]
    else:
        codes = [str(s) for s in text_list(v)] if isinstance(v, Cell) else [py_str(v)]
        shape = (len(codes), 1)
    rows = []
    for s in codes:
        h = s.strip()
        h = h[1:] if h.startswith('#') else h
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        if len(h) != 6 or any(c not in '0123456789abcdefABCDEF' for c in h):
            raise err('MATLAB:hex2rgb:invalidHex', f"'{s}' is not a hex colour code like '#FF8800' or '#F80'.", 'hex2rgb')
        rows.append([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])
    R_ = np.array(rows, F64).reshape(-1, 3)
    if len(shape) == 2 and shape[0] > 1 and shape[1] > 1:
        return np.stack([R_[:, k].reshape(shape, order='F') for k in range(3)], axis=2)
    return R_


def _current_map(target):
    if isinstance(target, Axes):
        return np.asarray(target.get_value('Colormap'), F64)
    f = target if isinstance(target, Figure) else gcf_()
    return np.asarray(f.props['Colormap'], F64)


@bi('brighten', arr=False)
def brighten(nargout, *args):
    """brighten(beta), brighten(map, beta) or brighten(f, beta): the colours
    raised to the power 1 - beta (beta > 0, brighter) or 1/(1 + beta)
    (beta < 0, darker), -1 < beta < 1; newmap = brighten(beta) gives the
    current colormap brightened without setting it."""
    nargchk(args, 1, 2, 'brighten')
    target, mapv = None, None
    if len(args) == 2:
        if isinstance(args[0], (Figure, Axes)):
            target = args[0]
        else:
            mapv = np.asarray(darr(args[0]), F64)
        beta = float(num(args[1]))
    else:
        beta = float(num(args[0]))
    if not -1 < beta < 1:
        raise err('MATLAB:brighten:BadBeta', 'beta is between -1 and 1.', 'brighten')
    g = 1 - beta if beta > 0 else 1 / (1 + beta)
    base = mapv if mapv is not None else _current_map(target)
    new = np.clip(base, 0, 1) ** g
    if nargout or mapv is not None:
        return new
    REG['colormap'].fn(0, *( [target] if target is not None else []), new)
    return None


@bi('rgbplot', arr=False)
def rgbplot(nargout, *args):
    """rgbplot(map): the red, green and blue columns of a colormap drawn as lines in their colours."""
    nargchk(args, 1, 1, 'rgbplot')
    m = np.asarray(darr(args[0]), F64)
    if m.ndim != 2 or m.shape[1] != 3:
        raise err('MATLAB:rgbplot:BadMap', 'The colormap has three columns.', 'rgbplot')
    k = out(np.arange(1, m.shape[0] + 1, dtype=F64).reshape(-1, 1))
    REG['plot'].fn(0, k, out(m[:, :1]), Char.of('r'), k, out(m[:, 1:2]), Char.of('g'), k, out(m[:, 2:]), Char.of('b'))
    return None


@bi('spinmap', aw=True, arr=False)
async def spinmap(nargout, *args):
    """spinmap(t, inc): the current figure's colormap turned round by inc
    rows (2) every few hundredths of a second for t seconds (3); spinmap('inf')
    until Ctrl+C."""
    nargchk(args, 0, 2, 'spinmap')
    t = 3.0
    if args:
        t = math.inf if is_str(args[0]) and opt_lower(args[0]) == 'inf' else float(num(args[0]))
    inc = int(num(args[1])) if len(args) > 1 else 2
    f = gcf_()
    m = np.asarray(f.props['Colormap'], F64)
    import time
    t0 = time.monotonic()
    while time.monotonic() - t0 < t:
        m = np.roll(m, -inc, axis=0)
        REG['colormap'].fn(0, f, m)
        await REG['pause'].fn(0, 0.05)
    return None


# ---- 3-D helpers -----------------------------------------------------------------------------------------------------

def _grid_xyz(args, fn):
    if len(args) == 1:
        Z = np.asarray(darr(args[0]), F64)
        X, Y = np.meshgrid(np.arange(1, Z.shape[1] + 1, dtype=F64), np.arange(1, Z.shape[0] + 1, dtype=F64))
        return X, Y, Z
    X, Y, Z = (np.asarray(darr(a), F64) for a in args[:3])
    if X.shape != Z.shape:
        if X.size == Z.shape[1] and Y.size == Z.shape[0]:
            X, Y = np.meshgrid(X.reshape(-1), Y.reshape(-1))
        else:
            raise err(f'MATLAB:{fn}:SizeMismatch', 'X, Y and Z are the same size (or X and Y vectors along its columns and rows).', fn)
    return X, Y, Z


@bi('surfnorm', nout=3, arr=False)
def surfnorm(nargout, *args):
    """[Nx, Ny, Nz] = surfnorm(X, Y, Z) or surfnorm(Z): the surface's unit
    normals at its vertices, the cross product of its tangents along the
    columns and along the rows (upward for z = f(x, y) on an increasing
    grid); with no output the surface is drawn with its normals."""
    nargchk(args, 1, 3, 'surfnorm')
    X, Y, Z = _grid_xyz(args, 'surfnorm')
    if Z.shape[0] < 2 or Z.shape[1] < 2:
        raise err('MATLAB:surfnorm:TooSmall', 'The surface is at least 2-by-2.', 'surfnorm')
    Pc = [np.gradient(A, axis=1) for A in (X, Y, Z)]
    Pr = [np.gradient(A, axis=0) for A in (X, Y, Z)]
    N = np.cross(np.stack(Pc, axis=-1), np.stack(Pr, axis=-1))
    nrm = np.linalg.norm(N, axis=-1, keepdims=True)
    with np.errstate(invalid='ignore', divide='ignore'):
        N = N / nrm
    if nargout:
        return _outs(nargout, out(N[..., 0]), out(N[..., 1]), out(N[..., 2]))
    REG['surf'].fn(0, out(X), out(Y), out(Z))
    REG['hold'].fn(0, Char.of('on'))
    L = 0.1 * max(float(np.ptp(X)), float(np.ptp(Y)), float(np.ptp(Z)), 1e-12)
    REG['quiver3'].fn(0, out(X), out(Y), out(Z), out(N[..., 0] * L), out(N[..., 1] * L), out(N[..., 2] * L), 0.0, Char.of('r'))
    REG['hold'].fn(0, Char.of('off'))
    return None


def _faces_verts(args, fn):
    """(F, V, rest, patch) from a patch, a struct with faces and vertices, or F and V."""
    a = list(args)
    if a and isinstance(a[0], Patch):
        p = a.pop(0)
        F, V = np.asarray(p.props['Faces'], F64), np.asarray(p.props['Vertices'], F64)
        if not F.size:
            X, Y = np.asarray(p.props['XData'], F64), np.asarray(p.props['YData'], F64)
            Z = np.asarray(p.props['ZData'], F64) if numel(p.props['ZData']) else np.zeros(X.shape)
            X, Y, Z = (np.atleast_2d(q).reshape(-1, max(1, X.shape[1] if X.ndim == 2 else 1), order='F') for q in (X, Y, Z))
            V = np.column_stack([X.reshape(-1, order='F'), Y.reshape(-1, order='F'), Z.reshape(-1, order='F')])
            F = np.arange(1, V.shape[0] + 1, dtype=F64).reshape(X.shape[1], X.shape[0])
        return F, V, a, p
    if a and isinstance(a[0], Struct):
        s = a.pop(0)
        keys = {k.lower(): k for k in s.keys}
        if 'faces' not in keys or 'vertices' not in keys:
            raise err(f'MATLAB:{fn}:BadStruct', 'The struct has faces and vertices.', fn)
        return np.asarray(darr(s.get1(keys['faces'])), F64), np.asarray(darr(s.get1(keys['vertices'])), F64), a, None
    if len(a) >= 2:
        return np.asarray(darr(a[0]), F64), np.asarray(darr(a[1]), F64), a[2:], None
    raise err(f'MATLAB:{fn}:nargin', f'{fn} takes a patch, a struct of faces and vertices, or faces and vertices.', fn)


@bi('shrinkfaces', nout=2, arr=False)
def shrinkfaces(nargout, *args):
    """shrinkfaces(p, sf), nfv = shrinkfaces(fv, sf), [f, v] = shrinkfaces(f, v, sf):
    each face drawn smaller about its centroid, its area sf times as large
    (0.3), on vertices of its own; a patch given with no output is changed."""
    nargchk(args, 1, 3, 'shrinkfaces')
    F, V, rest, p = _faces_verts(args, 'shrinkfaces')
    sf = float(num(rest[0])) if rest else 0.3
    k = math.sqrt(sf)
    newV, newF = [], []
    for row in F.astype(float):
        ids = [int(x) - 1 for x in row if np.isfinite(x)]
        P = V[ids]
        c = P.mean(axis=0)
        start = len(newV)
        newV += list(c + k * (P - c))
        r = [start + j + 1.0 for j in range(len(ids))] + [np.nan] * (F.shape[1] - len(ids))
        newF.append(r)
    NV = np.array(newV, F64).reshape(-1, V.shape[1])
    NF = np.array(newF, F64).reshape(-1, F.shape[1])
    if p is not None and not nargout:
        p.props['Faces'], p.props['Vertices'] = NF, NV
        p.props['XData'] = p.props['YData'] = p.props['ZData'] = EMPTY()
        p.touch()
        return None
    if nargout >= 2:
        return out(NF), out(NV)
    s = Struct.scalar({'faces': out(NF), 'vertices': out(NV)})
    return s


@bi('isocolors', arr=False)
def isocolors(nargout, *args):
    """nc = isocolors(X, Y, Z, C, vertices) or (X, Y, Z, R, G, B, vertices),
    or without X, Y, Z: the volume's colours interpolated (linearly) at the
    vertices; a patch in place of vertices gets them as FaceVertexCData."""
    nargchk(args, 2, 7, 'isocolors')
    from scipy.interpolate import RegularGridInterpolator
    a = list(args)
    last = a.pop()
    patch = last if isinstance(last, Patch) else None
    if patch is not None:
        V = np.asarray(patch.props['Vertices'], F64)
    elif isinstance(last, Struct):
        V = np.asarray(darr(last.get1('vertices')), F64)
    else:
        V = np.asarray(darr(last), F64)
    vols = [np.asarray(darr(x), F64) for x in a]
    if len(vols) in (4, 6):
        X, Y, Z = vols[:3]
        cols = vols[3:]
        xs, ys, zs = X[0, :, 0], Y[:, 0, 0], Z[0, 0, :]
    elif len(vols) in (1, 3):
        cols = vols
        m, n, q = cols[0].shape
        xs, ys, zs = np.arange(1, n + 1, dtype=F64), np.arange(1, m + 1, dtype=F64), np.arange(1, q + 1, dtype=F64)
    else:
        raise err('MATLAB:isocolors:nargin', 'isocolors takes X, Y, Z (or none), the colours C or R, G, B, and the vertices.', 'isocolors')
    res = []
    for C in cols:
        f = RegularGridInterpolator((ys, xs, zs), C, method='linear', bounds_error=False, fill_value=np.nan)
        res.append(f(np.column_stack([V[:, 1], V[:, 0], V[:, 2]])))
    nc = np.column_stack(res) if len(res) > 1 else res[0].reshape(-1, 1)
    if patch is not None:
        patch.props['FaceVertexCData'] = nc
        if patch.props.get('FaceColor') not in ('interp', 'flat'):
            patch.props['FaceColor'] = 'interp'
        patch.touch()
        return out(nc) if nargout else None
    return out(nc)


def _light_dir(az, el):
    a, e = math.radians(az), math.radians(el)
    return np.array([[math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)]])


@bi('lightangle', nout=2, arr=False)
def lightangle(nargout, *args):
    """h = lightangle(az, el) or lightangle(h, az, el): a light (or the light
    given) from azimuth az and elevation el in degrees, as view counts them;
    [az, el] = lightangle(h) reads them back."""
    nargchk(args, 1, 3, 'lightangle')
    a = list(args)
    h = None
    if a and isinstance(a[0], Light):
        h = a.pop(0)
    if h is not None and not a:
        p = np.asarray(h.props['Position'], F64).reshape(-1)
        r = np.linalg.norm(p) or 1.0
        el = math.degrees(math.asin(max(-1.0, min(1.0, p[2] / r))))
        az = math.degrees(math.atan2(p[0], -p[1]))
        return _outs(nargout, az, el)
    if len(a) != 2:
        raise err('MATLAB:lightangle:nargin', 'lightangle takes az and el (after a light, to move it).', 'lightangle')
    pos = _light_dir(float(num(a[0])), float(num(a[1])))
    if h is None:
        h = REG['light'].fn(1, Char.of('Position'), pos, Char.of('Style'), Char.of('infinite'))
    else:
        h.setprop('Position', pos)
        h.touch()
    return h if nargout else None
