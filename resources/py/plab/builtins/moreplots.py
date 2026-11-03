"""More plots: compass, feather, rose, pareto, stem3, comet, comet3, bar3,
bar3h, histogram2, pie3, ribbon, isosurface, slice, stream2, stream3,
streamline, camorbit, campos."""
import math

import numpy as np

from . import bi
from ._util import err, nargchk, arr, darr, out, opt_str, num, is_str
from ..values import Char, Cell, Struct, F64, class_of, shape_of, numel, py_str
from .. import runtime as R


def _g():
    from . import graphics as G
    return G


def _gb():
    from .. import graphics_base as GB
    return GB


def _spec(rest):
    """A line spec among the trailing inputs: (color, linestyle, marker) or None."""
    GB = _gb()
    for i, a in enumerate(rest):
        if is_str(a):
            s = py_str(a)
            p = GB.parse_linespec(s)
            if p is not None and len(s) <= 4:
                del rest[i]
                return p
    return None


def _line(ax, x, y, z=None, color=None, style='-', marker='none', **props):
    GB = _gb()
    h = GB.Line(ax)
    h.props['XData'] = np.asarray(x, F64).reshape(1, -1)
    h.props['YData'] = np.asarray(y, F64).reshape(1, -1)
    if z is not None:
        h.props['ZData'] = np.asarray(z, F64).reshape(1, -1)
    h.props['Color'] = color if color is not None else ax.next_color()
    h.props['LineStyle'] = style
    h.props['Marker'] = marker
    for k, v in props.items():
        h.props[k] = v
    return h


def _arrow_xy(u, v, x0=0.0, y0=0.0):
    """An arrow from (x0, y0) by (u, v) with a two-stroke head, as one
    polyline with NaN breaks."""
    L = math.hypot(u, v)
    if L == 0:
        return [x0, np.nan], [y0, np.nan]
    a = math.atan2(v, u)
    h = 0.25 * L
    tipx, tipy = x0 + u, y0 + v
    lx, ly = tipx - h * math.cos(a - 0.35), tipy - h * math.sin(a - 0.35)
    rx, ry = tipx - h * math.cos(a + 0.35), tipy - h * math.sin(a + 0.35)
    return [x0, tipx, lx, np.nan, tipx, rx, np.nan], [y0, tipy, ly, np.nan, tipy, ry, np.nan]


def _uv(args, fn):
    rest = list(args)
    a = darr(rest.pop(0))
    if np.iscomplexobj(a) and (not rest or is_str(rest[0])):
        return a.real.reshape(-1), a.imag.reshape(-1), rest
    if not rest or is_str(rest[0]):
        return a.real.reshape(-1), np.zeros(a.size), rest
    b = darr(rest.pop(0))
    return a.reshape(-1, order='F'), b.reshape(-1, order='F'), rest


@bi('compass', arr=False)
def compass(nargout, *args):
    """compass(U, V) or compass(Z): arrows from the origin in polar axes."""
    nargchk(args, 1, 4, 'compass')
    u, v, rest = _uv(args, 'compass')
    xs, ys = [], []
    for a, b in zip(u, v):
        x, y = _arrow_xy(a, b)
        xs += x
        ys += y
    xs, ys = np.array(xs), np.array(ys)
    th, r = np.arctan2(ys, xs), np.hypot(xs, ys)
    h = R.BUILTINS['polarplot'].fn(1, out(th.reshape(-1, 1)), out(r.reshape(-1, 1)), *rest)
    return h if nargout else None


@bi('feather', arr=False)
def feather(nargout, *args):
    """feather(U, V) or feather(Z): arrows from equally spaced points on the x-axis."""
    nargchk(args, 1, 4, 'feather')
    G = _g()
    u, v, rest = _uv(args, 'feather')
    spec = _spec(rest)
    ax = G.newplot(None)
    xs, ys = [], []
    for k, (a, b) in enumerate(zip(u, v)):
        x, y = _arrow_xy(a, b, k + 1.0, 0.0)
        xs += x
        ys += y
    c = spec[0] if spec and spec[0] is not None else ax.next_color()
    h = _line(ax, xs, ys, color=c)
    base = _line(ax, [1, max(len(u), 1)], [0, 0], color=(0.0, 0.0, 0.0), style=':')
    ax.touch()
    return G.handles_out([h, base]) if nargout else None


@bi('rose', nout=2, arr=False)
def rose(nargout, *args):
    """rose(theta, nbins): an angle histogram in polar axes, nbins (20) bins
    over the circle, or bins centred at the angles of a vector;
    [tout, rout] = rose(...) gives the outline instead."""
    nargchk(args, 1, 2, 'rose')
    t = np.mod(darr(args[0]).reshape(-1), 2 * math.pi)
    t = t[np.isfinite(t)]
    if len(args) > 1 and numel(args[1]) > 1:
        centres = np.sort(np.mod(darr(args[1]).reshape(-1), 2 * math.pi))
        mids = (centres[:-1] + centres[1:]) / 2
        edges = np.concatenate([[0.0], mids, [2 * math.pi]])
    else:
        nb = int(num(args[1])) if len(args) > 1 else 20
        edges = np.linspace(0, 2 * math.pi, nb + 1)
    counts = np.histogram(t, bins=edges)[0].astype(F64)
    tout = np.column_stack([edges[:-1], edges[:-1], edges[1:], edges[1:]]).reshape(-1)
    rout = np.column_stack([np.zeros_like(counts), counts, counts, np.zeros_like(counts)]).reshape(-1)
    if nargout >= 1:
        return (out(tout.reshape(1, -1)), out(rout.reshape(1, -1)))[:max(nargout, 1)] if nargout > 1 else out(tout.reshape(1, -1))
    R.BUILTINS['polarplot'].fn(0, out(tout.reshape(-1, 1)), out(rout.reshape(-1, 1)))
    return None


@bi('pareto', nout=2, arr=False)
def pareto(nargout, *args):
    """pareto(y, names, threshold): bars of the values in descending order (as
    many as reach the threshold, 0.95, of the total) and their cumulative
    percentage as a line on a right y-axis."""
    nargchk(args, 1, 3, 'pareto')
    G = _g()
    y = darr(args[0]).reshape(-1).astype(F64)
    labels = None
    thr = 0.95
    for a in args[1:]:
        if isinstance(a, Cell) or (is_str(a) and numel(a) > 1) or class_of(a) == 'string':
            from ..values import text_list
            labels = text_list(a)
        elif numel(a) == 1:
            thr = float(num(a))
        else:
            labels = [f'{x:g}' for x in darr(a).reshape(-1)]
    if labels is None:
        labels = [f'{k + 1}' for k in range(y.size)]
    order = np.argsort(-y, kind='stable')
    ys = y[order]
    total = ys.sum()
    cum = np.cumsum(ys) / total if total else np.zeros_like(ys)
    k = int(np.searchsorted(cum, thr - 1e-12) + 1) if total else ys.size
    k = min(max(k, 1), ys.size)
    ax = G.newplot(None)
    bar = R.BUILTINS['bar'].fn(1, out(np.arange(1, k + 1, dtype=F64).reshape(1, -1)), out(ys[:k].reshape(1, -1)))
    R.BUILTINS['xticks'].fn(0, out(np.arange(1, k + 1, dtype=F64).reshape(1, -1)))
    R.BUILTINS['xticklabels'].fn(0, Cell.of_list([Char.of(labels[i]) for i in order[:k]]))
    R.BUILTINS['yyaxis'].fn(0, Char.of('right'))
    line = R.BUILTINS['plot'].fn(1, out(np.arange(1, k + 1, dtype=F64).reshape(1, -1)), out(100 * cum[:k].reshape(1, -1)), Char.of('-o'))
    R.BUILTINS['ylim'].fn(0, out(np.array([[0.0, 100.0]])))
    R.BUILTINS['yyaxis'].fn(0, Char.of('left'))
    if nargout:
        return (G.handles_out([bar, line]), G.gca_())[:max(nargout, 1)] if nargout > 1 else G.handles_out([bar, line])
    return None


@bi('stem3', arr=False)
def stem3(nargout, *args):
    """stem3(X, Y, Z) or stem3(Z): a line from z = 0 to each value and a
    marker on its end, in 3-D; 'filled' fills the markers."""
    nargchk(args, 1, None, 'stem3')
    G = _g()
    rest = list(args)
    filled = False
    for i, a in enumerate(rest):
        if is_str(a) and py_str(a).lower() == 'filled':
            filled = True
            del rest[i]
            break
    data = []
    while rest and not is_str(rest[0]) and len(data) < 3:
        data.append(darr(rest.pop(0)))
    spec = _spec(rest)
    if len(data) not in (1, 3):
        raise err('MATLAB:stem3:nargin', 'stem3 takes Z, or X, Y and Z.', 'stem3')
    if len(data) == 1:
        Z = data[0]
        if Z.ndim == 2 and 1 in Z.shape:
            X, Y = np.arange(1, Z.size + 1, dtype=F64), np.ones(Z.size)
        else:
            Y, X = np.meshgrid(np.arange(1, Z.shape[0] + 1), np.arange(1, Z.shape[1] + 1), indexing='ij')
    else:
        X, Y, Z = data
    x, y, z = (np.asarray(a, F64).reshape(-1, order='F') for a in (X, Y, Z))
    ax = G.newplot(None)
    c = spec[0] if spec and spec[0] is not None else ax.next_color()
    sx = np.column_stack([x, x, np.full(x.size, np.nan)]).reshape(-1)
    sy = np.column_stack([y, y, np.full(y.size, np.nan)]).reshape(-1)
    sz = np.column_stack([np.zeros(z.size), z, np.full(z.size, np.nan)]).reshape(-1)
    stems = _line(ax, sx, sy, sz, color=c)
    marker = spec[2] if spec and spec[2] not in (None, 'none') else 'o'
    heads = _line(ax, x, y, z, color=c, style='none', marker=marker, MarkerFaceColor=c if filled else 'none')
    R.BUILTINS['view'].fn(0, ax, 3.0)
    ax.touch()
    return G.handles_out([stems, heads]) if nargout else None


def _comet(nargout, args, is3d):
    G = _g()
    data = [darr(a).reshape(-1).astype(F64) for a in args if not is_str(a)]
    if is3d:
        if len(data) < 3:
            raise err('MATLAB:comet3:nargin', 'comet3 takes x, y and z (or z alone).', 'comet3')
        x, y, z = data[:3]
    else:
        if not data:
            raise err('MATLAB:minrhs', 'Not enough input arguments.', 'comet')
        if len(data) == 1:
            y = data[0]
            x = np.arange(1, y.size + 1, dtype=F64)
        else:
            x, y = data[:2]
        z = None
    ax = G.newplot(None)
    c = ax.next_color()
    body = _line(ax, x, y, z, color=c)
    head = _line(ax, x[-1:], y[-1:], None if z is None else z[-1:], color=c, style='none', marker='o', MarkerFaceColor=c)
    if is3d:
        R.BUILTINS['view'].fn(0, ax, 3.0)
    ax.touch()
    return G.handles_out([body, head]) if nargout else None


@bi('comet', arr=False)
def comet(nargout, *args):
    """comet(x, y): the path of a point with its head (drawn whole: the page
    shows the figure as it ends)."""
    nargchk(args, 1, 3, 'comet')
    return _comet(nargout, args, False)


@bi('comet3', arr=False)
def comet3(nargout, *args):
    """comet3(x, y, z): the path of a point in 3-D with its head."""
    nargchk(args, 1, 4, 'comet3')
    return _comet(nargout, args, True)


# ---- 3-D bars -------------------------------------------------------------------------------------------

def _cuboids(boxes):
    """Faces and vertices of boxes (x0, x1, y0, y1, z0, z1): six quads each."""
    V, F = [], []
    for x0, x1, y0, y1, z0, z1 in boxes:
        b = len(V)
        V += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        F += [(b, b + 1, b + 2, b + 3), (b + 4, b + 5, b + 6, b + 7), (b, b + 1, b + 5, b + 4),
              (b + 1, b + 2, b + 6, b + 5), (b + 2, b + 3, b + 7, b + 6), (b + 3, b, b + 4, b + 7)]
    return np.array(F, F64).reshape(-1, 4) + 1, np.array(V, F64).reshape(-1, 3)


def _bar3(nargout, args, horizontal):
    G, GB = _g(), _gb()
    rest = list(args)
    data = []
    while rest and not is_str(rest[0]) and len(data) < 3:
        data.append(rest.pop(0))
    style = 'detached'
    for i, a in enumerate(list(rest)):
        if is_str(a) and py_str(a).lower() in ('detached', 'grouped', 'stacked'):
            style = py_str(a).lower()
            rest.remove(a)
            break
    if not data:
        raise err('MATLAB:minrhs', 'Not enough input arguments.')
    if len(data) >= 2 and numel(data[1]) > 1:
        yv = darr(data[0]).reshape(-1).astype(F64)
        Z = darr(data[1]).astype(F64)
        width = float(num(data[2])) if len(data) > 2 else 0.8
        if yv.size != (Z.shape[0] if Z.ndim == 2 and 1 not in Z.shape else Z.size):
            raise err('MATLAB:bar3:LengthMismatch', 'There must be one y for each row of Z.')
    else:
        Z = darr(data[0]).astype(F64)
        width = float(num(data[1])) if len(data) > 1 else 0.8
        yv = None
    if Z.ndim == 2 and Z.shape[0] == 1:
        Z = Z.reshape(-1, 1)
    m, n = Z.shape
    if yv is None:
        yv = np.arange(1, m + 1, dtype=F64)
    ax = G.newplot(None)
    hs = []
    base = np.zeros(m)
    for j in range(n):
        boxes = []
        for i in range(m):
            zval = Z[i, j]
            if not np.isfinite(zval):
                continue
            if style == 'detached':
                x0, x1 = j + 1 - width / 2, j + 1 + width / 2
                z0, z1 = 0.0, zval
            elif style == 'grouped':
                w = width / n
                x0 = 1 - width / 2 + j * w
                x1 = x0 + w
                z0, z1 = 0.0, zval
            else:
                x0, x1 = 1 - width / 2, 1 + width / 2
                z0, z1 = base[i], base[i] + zval
            y0, y1 = yv[i] - width / 2, yv[i] + width / 2
            boxes.append((x0, x1, y0, y1, z0, z1))
        if style == 'stacked':
            base = base + np.nan_to_num(Z[:, j])
        F, V = _cuboids(boxes)
        h = GB.Patch(ax)
        h.props['Faces'] = F
        # bar3h: the values along x, the series along y, the rows up z
        h.props['Vertices'] = np.column_stack([V[:, 2], V[:, 0], V[:, 1]]) if horizontal else V
        h.props['FaceColor'] = ax.next_color()
        h.props['EdgeColor'] = (0.0, 0.0, 0.0)
        hs.append(h)
    R.BUILTINS['view'].fn(0, ax, 3.0)
    ax.touch()
    return G.handles_out(hs) if nargout else None


@bi('bar3', arr=False)
def bar3(nargout, *args):
    """bar3(Z), bar3(y, Z, width, style): 3-D bars, a column of Z per row of
    bars ('detached', the default, 'grouped' or 'stacked')."""
    nargchk(args, 1, 5, 'bar3')
    return _bar3(nargout, args, False)


@bi('bar3h', arr=False)
def bar3h(nargout, *args):
    """bar3h(Z): 3-D bars along the x-axis."""
    nargchk(args, 1, 5, 'bar3h')
    return _bar3(nargout, args, True)


@bi('histogram2', arr=False)
def histogram2(nargout, *args):
    """histogram2(X, Y, nbins or Xedges, Yedges, ...): the counts of
    histcounts2 drawn as 3-D bars over their bins."""
    nargchk(args, 2, None, 'histogram2')
    G, GB = _g(), _gb()
    N, xe, ye = R.BUILTINS['histcounts2'].fn(3, *args)[:3]
    xe, ye = np.asarray(xe, F64).reshape(-1), np.asarray(ye, F64).reshape(-1)
    N = np.asarray(N, F64).reshape(xe.size - 1, ye.size - 1)          # one bin comes back as a number
    boxes = [(xe[i], xe[i + 1], ye[j], ye[j + 1], 0.0, N[i, j]) for i in range(N.shape[0]) for j in range(N.shape[1]) if N[i, j] > 0]
    ax = G.newplot(None)
    F, V = _cuboids(boxes)
    h = GB.Patch(ax)
    h.props['Faces'] = F
    h.props['Vertices'] = V
    h.props['FaceColor'] = ax.next_color()
    h.props['EdgeColor'] = (0.0, 0.0, 0.0)
    R.BUILTINS['view'].fn(0, ax, 3.0)
    ax.touch()
    return h if nargout else None


@bi('pie3', arr=False)
def pie3(nargout, *args):
    """pie3(x, explode, labels): a pie of extruded wedges, each labelled by
    its percentage (or the labels given); parts that sum to less than 1 leave
    a gap."""
    nargchk(args, 1, 3, 'pie3')
    G, GB = _g(), _gb()
    from ..values import text_list
    x = darr(args[0]).reshape(-1).astype(F64)
    explode = np.zeros(x.size)
    labels = None
    for a in args[1:]:
        if isinstance(a, Cell) or class_of(a) == 'string' or is_str(a):
            labels = text_list(a)
        else:
            explode = np.asarray(arr(a), F64).reshape(-1)
    total = x.sum()
    frac = x / total if total >= 1 else x          # parts summing to less than 1 leave a gap
    ax = G.newplot(None)
    hs = []
    start = math.pi / 2
    h0 = 0.35
    for k, f in enumerate(frac):
        a0, a1 = start, start - 2 * math.pi * f
        mid = (a0 + a1) / 2
        off = 0.1 * (explode[k] if k < explode.size else 0) * np.array([math.cos(mid), math.sin(mid)])
        ts = np.linspace(a0, a1, max(int(abs(a1 - a0) / 0.05), 2))
        ring = np.column_stack([np.cos(ts), np.sin(ts)]) + off
        cpt = off
        top = np.vstack([cpt, ring])
        nv = top.shape[0]
        V = np.vstack([np.column_stack([top, np.full(nv, h0)]), np.column_stack([top, np.zeros(nv)])])
        c = ax.next_color()
        for faces in ([list(range(nv))], [list(range(nv, 2 * nv))]):
            p = GB.Patch(ax)
            p.props['Faces'] = np.array(faces, F64) + 1
            p.props['Vertices'] = V
            p.props['FaceColor'] = c
            p.props['EdgeColor'] = (0.0, 0.0, 0.0)
            hs.append(p)
        side = [[i, i + 1, nv + i + 1, nv + i] for i in range(nv - 1)] + [[nv - 1, 0, nv, 2 * nv - 1]]
        p = GB.Patch(ax)
        p.props['Faces'] = np.array(side, F64) + 1
        p.props['Vertices'] = V
        p.props['FaceColor'] = c
        p.props['EdgeColor'] = 'none'
        hs.append(p)
        label = labels[k] if labels and k < len(labels) else (f'{round(100 * f):g}%' if 100 * f >= 1 or f == 0 else '< 1%')
        t = GB.Text(ax)
        pos = 1.2 * np.array([math.cos(mid), math.sin(mid)]) + off
        t.props['Position'] = np.array([[pos[0], pos[1], h0]])
        t.set_value('String', Char.of(label))
        t.props['HorizontalAlignment'] = 'center'
        hs.append(t)
        start = a1
    R.BUILTINS['view'].fn(0, ax, 3.0)
    R.BUILTINS['axis'].fn(0, Char.of('equal'))
    R.BUILTINS['axis'].fn(0, Char.of('off'))
    ax.touch()
    return G.handles_out(hs) if nargout else None


@bi('ribbon', arr=False)
def ribbon(nargout, *args):
    """ribbon(Y), ribbon(X, Y, width): each column of Y as a ribbon (a strip of
    surface) of the width (0.75) at x = its column number."""
    nargchk(args, 1, 3, 'ribbon')
    G, GB = _g(), _gb()
    data = [darr(a).astype(F64) for a in args]
    if len(data) == 1:
        Y = data[0]
        X = None
        width = 0.75
    elif len(data) == 2 and numel(args[1]) == 1:
        Y, X, width = data[0], None, float(num(args[1]))
    else:
        X, Y = data[0], data[1]
        width = float(num(args[2])) if len(args) > 2 else 0.75
    if Y.ndim == 2 and Y.shape[0] == 1:
        Y = Y.reshape(-1, 1)
    m, n = Y.shape
    if X is None:
        X = np.arange(1, m + 1, dtype=F64)
    X = np.asarray(X, F64).reshape(m, -1) if X.size == m * n else np.tile(np.asarray(X, F64).reshape(-1, 1), (1, n))
    ax = G.newplot(None)
    hs = []
    for j in range(n):
        s = GB.Surface(ax)
        s.props['XData'] = np.column_stack([np.full(m, j + 1 - width / 2), np.full(m, j + 1 + width / 2)])
        s.props['YData'] = np.column_stack([X[:, j], X[:, j]])
        s.props['ZData'] = np.column_stack([Y[:, j], Y[:, j]])
        s.props['CData'] = np.full((m, 2), float(j + 1))
        hs.append(s)
    R.BUILTINS['view'].fn(0, ax, 3.0)
    ax.touch()
    return G.handles_out(hs) if nargout else None


# ---- volumes: isosurface, slice, streamlines -----------------------------------------------------------------

_TETS = [(0, 5, 1, 6), (0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6)]
_CORNERS = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]


def _volume_args(args, fn):
    """X, Y, Z, V (meshgrid layout) and the rest; X, Y, Z from 1:n when not given."""
    rest = list(args)
    if len(rest) >= 4 and all(not is_str(a) for a in rest[:4]) and darr(rest[3]).ndim == 3:
        grids = [darr(rest.pop(0)).astype(F64) for _ in range(3)]
        V = darr(rest.pop(0)).astype(F64)
    else:
        grids = [np.zeros(0)] * 3
        V = darr(rest.pop(0)).astype(F64)
    if V.ndim != 3:
        raise err(f'MATLAB:{fn}:NotVolume', 'V must be a 3-D array.', fn)
    ny, nx, nz = V.shape
    # each grid as a full array in meshgrid's layout: given so, as a vector, or empty for 1:n
    vecs = []
    for G, n, k, name in zip(grids, (nx, ny, nz), (1, 0, 2), 'XYZ'):
        if G.size == 0:
            vecs.append(np.arange(1, n + 1, dtype=F64))
        elif G.ndim == 3:
            if G.shape != V.shape:
                raise err(f'MATLAB:{fn}:SizeMismatch', f'{name} must match the size of V.', fn)
            idx = [0, 0, 0]
            idx[k] = slice(None)
            vecs.append(G[tuple(idx)])
        else:
            if G.size != n:
                raise err(f'MATLAB:{fn}:SizeMismatch', f'{name} must match the size of V (a vector of {n} values, or an array of its size).', fn)
            vecs.append(G.reshape(-1))
    X, Y, Z = np.meshgrid(*vecs)
    return X, Y, Z, V, rest


def _isosurface(X, Y, Z, V, iso, colors=None):
    """Triangles where V crosses iso: each grid cube cut into six tetrahedra,
    each tetrahedron's crossing as one or two triangles, the points by linear
    interpolation along the edges; shared points merged."""
    ny, nx, nz = V.shape
    verts, faces, index, cols = [], [], {}, []

    def point(p, q):
        key = (min(p, q), max(p, q))
        if key in index:
            return index[key]
        vp, vq = V[p], V[q]
        t = 0.5 if vq == vp else (iso - vp) / (vq - vp)
        pt = tuple((1 - t) * A[p] + t * A[q] for A in (X, Y, Z))
        index[key] = len(verts)
        verts.append(pt)
        if colors is not None:
            cols.append((1 - t) * colors[p] + t * colors[q])
        return index[key]
    above = V > iso
    for i in range(ny - 1):
        for j in range(nx - 1):
            for k in range(nz - 1):
                cube = [(i + c[1], j + c[0], k + c[2]) for c in _CORNERS]
                flags = [above[c] for c in cube]
                if all(flags) or not any(flags):
                    continue
                for tet in _TETS:
                    pts = [cube[t] for t in tet]
                    ins = [p for p in pts if above[p]]
                    outs = [p for p in pts if not above[p]]
                    if len(ins) in (0, 4):
                        continue
                    if len(ins) == 1 or len(ins) == 3:
                        lone, others = (ins[0], outs) if len(ins) == 1 else (outs[0], ins)
                        faces.append([point(lone, o) for o in others])
                    else:
                        a, b = ins
                        c, d = outs
                        p1, p2, p3, p4 = point(a, c), point(a, d), point(b, d), point(b, c)
                        faces.append([p1, p2, p3])
                        faces.append([p1, p3, p4])
    return np.array(faces, F64).reshape(-1, 3) + 1, np.array(verts, F64).reshape(-1, 3), np.array(cols, F64).reshape(-1, 1)


@bi('isosurface', nout=3, arr=False)
def isosurface(nargout, *args):
    """fv = isosurface(X, Y, Z, V, isovalue) or isosurface(V, isovalue): the
    surface where V equals the value, as faces and vertices (marching
    tetrahedra); with no output, drawn as a patch."""
    nargchk(args, 1, 7, 'isosurface')
    G, GB = _g(), _gb()
    X, Y, Z, V, rest = _volume_args(args, 'isosurface')
    nums = [a for a in rest if not is_str(a)]
    if nums and numel(nums[0]) == 1:
        iso = float(num(nums.pop(0)))
    else:
        fin = V[np.isfinite(V)]
        iso = float(np.mean(fin)) if fin.size else 0.0
    colors = darr(nums[0]).astype(F64) if nums and darr(nums[0]).shape == V.shape else None
    if nums and colors is None:
        raise err('MATLAB:isosurface:SizeMismatch', 'The colours must be an array of the size of V.', 'isosurface')
    if nargout >= 3 and colors is None:
        raise err('MATLAB:isosurface:NoColors', 'Give the colours to get the third output.', 'isosurface')
    F, P, Cv = _isosurface(X, Y, Z, V, iso, colors)
    if nargout >= 2:
        return (out(F), out(P), out(Cv))[:nargout]
    if nargout == 1:
        fv = {'vertices': out(P), 'faces': out(F)}
        if colors is not None:
            fv['facevertexcdata'] = out(Cv)
        return Struct.scalar(fv)
    ax = G.newplot(None)
    h = GB.Patch(ax)
    h.props['Faces'] = F
    h.props['Vertices'] = P
    h.props['FaceColor'] = ax.next_color()
    h.props['EdgeColor'] = 'none'
    R.BUILTINS['view'].fn(0, ax, 3.0)
    ax.touch()
    return None


@bi('slice', arr=False)
def slice_(nargout, *args):
    """slice(X, Y, Z, V, xslice, yslice, zslice) or slice(V, xs, ys, zs): the
    volume's values on planes x = xs, y = ys, z = zs, as surfaces coloured by
    them (interp3)."""
    nargchk(args, 4, 8, 'slice')
    G, GB = _g(), _gb()
    rest = list(args)
    method = 'linear'
    if rest and is_str(rest[-1]):
        method = py_str(rest.pop()).lower()
    if len(rest) == 7:
        X, Y, Z, V = (darr(rest[k]).astype(F64) for k in range(4))
        planes = rest[4:]
    else:
        V = darr(rest[0]).astype(F64)
        ny, nx, nz = V.shape
        X, Y, Z = np.meshgrid(np.arange(1, nx + 1, dtype=F64), np.arange(1, ny + 1, dtype=F64), np.arange(1, nz + 1, dtype=F64))
        planes = rest[1:]
    xs, ys, zs = (darr(p).reshape(-1).astype(F64) if numel(p) else np.zeros(0) for p in planes)
    xv, yv, zv = X[0, :, 0], Y[:, 0, 0], Z[0, 0, :]
    interp3 = R.BUILTINS['interp3'].fn
    ax = G.newplot(None)
    hs = []

    def surface(PX, PY, PZ):
        C = np.asarray(arr(interp3(1, out(X), out(Y), out(Z), out(V), out(PX), out(PY), out(PZ), Char.of(method))), F64).reshape(PX.shape)
        s = GB.Surface(ax)
        s.props['XData'], s.props['YData'], s.props['ZData'], s.props['CData'] = PX, PY, PZ, C
        hs.append(s)
    for x0 in xs:
        PY, PZ = np.meshgrid(yv, zv, indexing='ij')
        surface(np.full(PY.shape, x0), PY, PZ)
    for y0 in ys:
        PX, PZ = np.meshgrid(xv, zv, indexing='ij')
        surface(PX, np.full(PX.shape, y0), PZ)
    for z0 in zs:
        PY, PX = np.meshgrid(yv, xv, indexing='ij')
        surface(PX, PY, np.full(PX.shape, z0))
    R.BUILTINS['view'].fn(0, ax, 3.0)
    ax.touch()
    return G.handles_out(hs) if nargout else None


def _stream(fields, grids, starts, step, maxvert):
    """Streamlines by fourth-order Runge-Kutta through the velocity field
    (linear interpolation on the grid), steps of step cells, ending at the
    grid's edge, where the speed is 0, or after maxvert points."""
    from scipy.interpolate import RegularGridInterpolator
    d = len(fields)
    fs = [RegularGridInterpolator(grids, F, bounds_error=False, fill_value=np.nan) for F in fields]
    cell = np.array([np.mean(np.diff(g)) if g.size > 1 else 1.0 for g in grids])
    lo = np.array([g[0] for g in grids])
    hi = np.array([g[-1] for g in grids])
    lines = []
    for s in starts:
        p = np.asarray(s, F64)
        pts = [p.copy()]

        def vel(q):
            v = np.array([f(q[None, :])[0] for f in fs])
            sp = np.linalg.norm(v / cell)
            return None if not np.all(np.isfinite(v)) or sp == 0 else v / sp
        for _ in range(int(maxvert) - 1):
            if np.any(p < lo) or np.any(p > hi):
                break
            k1 = vel(p)
            if k1 is None:
                break
            k2 = vel(p + 0.5 * step * k1)
            k3 = vel(p + 0.5 * step * k2) if k2 is not None else None
            k4 = vel(p + step * k3) if k3 is not None else None
            if k4 is None:
                break
            p = p + step * (k1 + 2 * k2 + 2 * k3 + k4) / 6
            if np.any(p < lo) or np.any(p > hi):
                break
            pts.append(p.copy())
        lines.append(np.array(pts))
    return lines


def _stream_args(args, d, fn):
    rest = list(args)
    opts = None
    if len(rest) in (3 * d + 1, 2 * d + 1):
        opts = darr(rest.pop()).reshape(-1)
    if len(rest) == 3 * d:
        grids = [darr(rest[i]).astype(F64) for i in range(d)]
        fields = [darr(rest[d + i]).astype(F64) for i in range(d)]
        starts = [darr(rest[2 * d + i]).reshape(-1).astype(F64) for i in range(d)]
    elif len(rest) == 2 * d:
        fields = [darr(rest[i]).astype(F64) for i in range(d)]
        starts = [darr(rest[d + i]).reshape(-1).astype(F64) for i in range(d)]
        shp = fields[0].shape
        axes = [np.arange(1, n + 1, dtype=F64) for n in (shp[1], shp[0]) + ((shp[2],) if d == 3 else ())]
        grids = list(np.meshgrid(*axes))
    else:
        raise err(f'MATLAB:{fn}:nargin', 'Give the grid (or not), the velocities and the starting points.', fn)
    # meshgrid layout: x varies along the second dimension, y along the first
    def axis_vec(G, k):
        """The grid vector along dimension k of a full grid (or the vector given)."""
        G = np.asarray(G)
        if G.ndim == 1 or (G.ndim == 2 and min(G.shape) == 1):
            return G.reshape(-1)
        idx = [0] * G.ndim
        idx[k] = slice(None)
        return G[tuple(idx)]
    xv, yv = axis_vec(grids[0], 1), axis_vec(grids[1], 0)
    vecs = [yv, xv] + ([axis_vec(grids[2], 2)] if d == 3 else [])
    fields_ij = [fields[1], fields[0]] + ([fields[2]] if d == 3 else [])
    step = float(opts[0]) if opts is not None and opts.size else 0.1
    maxvert = float(opts[1]) if opts is not None and opts.size > 1 else 10000
    st = list(zip(*([starts[1], starts[0]] + ([starts[2]] if d == 3 else []))))
    lines = _stream(fields_ij, tuple(vecs), st, step, maxvert)
    back = []
    for L in lines:
        cols = [L[:, 1], L[:, 0]] + ([L[:, 2]] if d == 3 else [])
        back.append(np.column_stack(cols) if L.size else np.zeros((0, d)))
    return back


@bi('stream2')
def stream2(nargout, *args):
    """XY = stream2(X, Y, U, V, startx, starty, options): streamlines of a 2-D
    vector field from the starting points, a cell of n-by-2 vertex arrays;
    options [step maxvert] (0.1 of a cell, 10000)."""
    nargchk(args, 4, 7, 'stream2')
    return Cell.of_list([out(L) for L in _stream_args(args, 2, 'stream2')])


@bi('stream3')
def stream3(nargout, *args):
    """XYZ = stream3(X, Y, Z, U, V, W, startx, starty, startz, options):
    streamlines of a 3-D vector field, a cell of n-by-3 vertex arrays."""
    nargchk(args, 6, 10, 'stream3')
    return Cell.of_list([out(L) for L in _stream_args(args, 3, 'stream3')])


@bi('streamline', arr=False)
def streamline(nargout, *args):
    """streamline(X, Y, U, V, startx, starty), its 3-D form, or
    streamline(XY) of stream2's (or stream3's) vertices: the streamlines as
    lines."""
    nargchk(args, 1, 10, 'streamline')
    G = _g()
    if len(args) == 1 and isinstance(args[0], Cell):
        lines = [darr(x) for x in args[0].a.reshape(-1)]
    else:
        # six inputs are a 2-D field with its grid or a 3-D one without: the field's dimensions decide
        n = len([a for a in args if not is_str(a)])
        d = 3 if n in (9, 10) or (n in (6, 7) and darr(args[0]).ndim == 3) else 2
        lines = _stream_args(args, d, 'streamline')
    ax = G.newplot(None)
    hs = []
    for L in lines:
        L = np.asarray(L, F64)
        if L.size == 0:
            continue
        hs.append(_line(ax, L[:, 0], L[:, 1], L[:, 2] if L.shape[1] > 2 else None))
    if any(np.asarray(L).shape[1] > 2 for L in lines if np.asarray(L).size):
        R.BUILTINS['view'].fn(0, ax, 3.0)
    ax.touch()
    return G.handles_out(hs) if nargout else None


# ---- camera ---------------------------------------------------------------------------------------------

@bi('camorbit', nout=0, arr=False)
def camorbit(nargout, *args):
    """camorbit(dtheta, dphi): turn the view about the axes' centre by dtheta
    degrees of azimuth and dphi of elevation."""
    nargchk(args, 2, 4, 'camorbit')
    G = _g()
    rest = list(args)
    ax = rest.pop(0) if rest and hasattr(rest[0], 'props') and 'View' in getattr(rest[0], 'props', {}) else G.gca_()
    dt, dp = float(num(rest[0])), float(num(rest[1]))
    az, el = R.BUILTINS['view'].fn(2, ax)
    R.BUILTINS['view'].fn(0, ax, out(np.array([[float(az) + dt, max(-90.0, min(90.0, float(el) + dp))]])))
    return None


@bi('campos', arr=False)
def campos(nargout, *args):
    """campos: where the camera is, from the view's azimuth and elevation, at
    a distance of ten times the axes' size from their centre; campos([x y z])
    turns the view to look from there."""
    nargchk(args, 0, 2, 'campos')
    G = _g()
    rest = list(args)
    ax = rest.pop(0) if rest and hasattr(rest[0], 'props') and 'View' in getattr(rest[0], 'props', {}) else G.gca_()
    lims = [np.asarray(arr(ax.get_value(k)), F64).reshape(-1) for k in ('XLim', 'YLim', 'ZLim')]
    centre = np.array([l.mean() for l in lims])
    if rest:
        p = darr(rest[0]).reshape(-1).astype(F64)
        if p.size != 3:
            raise err('MATLAB:campos:InvalidPosition', 'The camera position is [x y z].', 'campos')
        d = p - centre
        az = math.degrees(math.atan2(d[0], -d[1]))
        el = math.degrees(math.atan2(d[2], math.hypot(d[0], d[1])))
        R.BUILTINS['view'].fn(0, ax, out(np.array([[az, el]])))
        return None
    az, el = R.BUILTINS['view'].fn(2, ax)
    a, e = math.radians(float(az)), math.radians(float(el))
    size = max(float(np.ptp(np.concatenate(lims))), 1.0)
    dirn = np.array([math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)])
    return out((centre + 10 * size * dirn).reshape(1, -1))
