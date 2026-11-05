"""Plot fill-ins: the older ez functions (ezplot3, ezpolar, ezsurf, ezsurfc,
ezmesh, ezmeshc, ezcontour, ezcontourf), which take a function as text or a
handle over -2*pi to 2*pi and title the plot with it; camlookat;
streamribbon; the reflectance functions specular and diffuse; orient; and
copygraphics.
"""
import math
import re

import numpy as np

from . import bi, REG
from ._util import err, nargchk, darr, arr, out, opt_str, is_str, sval, num
from ..values import MError, Char, Cell, FH, F64, py_str, numel
from .. import runtime as R


def _g():
    from . import graphics
    return graphics


def _gb():
    from .. import graphics_base
    return graphics_base


# ---- functions given as text or handles ------------------------------------------------------------------------------------

_NOT_VARS = {'pi', 'e', 'i', 'j', 'inf', 'Inf', 'nan', 'NaN', 'eps'}


def _vectorize(text):
    """An expression made element-wise: * / ^ become .* ./ .^"""
    return re.sub(r'(?<![.\'])([*/^])', r'.\1', text)


def _vars_of(text):
    names = []
    for m in re.finditer(r'(?<![\w.])([A-Za-z]\w*)(?!\w)(\s*\()?', text):
        nm, call = m.group(1), m.group(2)
        if call or nm in _NOT_VARS or nm in names:
            continue
        if nm in R.BUILTINS and nm not in ('x', 'y', 't', 'r', 's', 'u', 'v', 'z'):
            continue
        names.append(nm)
    return sorted(names)


def _func(f, nvars, fn, defaults):
    """A function handle of nvars inputs and the text that names it, from a
    handle or from text such as 'x^2 + sin(y)' (its variables in alphabetical order)."""
    from .core import anon_from_text
    if isinstance(f, FH):
        t = f.text()
        m = re.match(r'^@\(([^)]*)\)\s*(.*)$', t, re.S)
        return f, (m.group(2) if m else t)
    if is_str(f):
        text = py_str(f).strip()
        if not text:
            raise err(f'MATLAB:{fn}:InvalidFunction', 'The function is a function handle or an expression as text.', fn)
        vs = _vars_of(text)
        if len(vs) > nvars:
            raise err(f'MATLAB:{fn}:TooManyVariables', f"'{text}' has {len(vs)} variables; {fn} takes {nvars}.", fn)
        for d in defaults:
            if len(vs) >= nvars:
                break
            if d not in vs:
                vs.append(d)
        vs = sorted(vs)[:nvars] if len(vs) == nvars else vs
        h = anon_from_text('@(' + ','.join(vs) + ') ' + _vectorize(text))
        return h, text
    if type(f).__name__ == 'Sym':
        h = REG['matlabFunction'].fn(1, f)
        return h, str(REG['char'].fn(1, f).str())
    raise err(f'MATLAB:{fn}:InvalidFunction', 'The function is a function handle or an expression as text.', fn)


def _values(h, *xs):
    """h at the points (element-wise, or one point at a time when it is not written for arrays)."""
    shape = np.broadcast(*xs).shape
    try:
        v = darr(h.scall(1, *(out(np.asarray(x, F64)) for x in xs)))
        if v.size == 1 and int(np.prod(shape)) > 1:
            v = np.full(shape, float(v.reshape(-1)[0]))
        if v.shape != shape:
            raise MError('', 'shape')
        return np.asarray(v, F64)
    except MError:
        flat = [np.broadcast_to(x, shape).reshape(-1) for x in xs]
        vals = [float(np.real(arr(h.scall(1, *(float(c[k]) for c in flat))).reshape(-1)[0])) for k in range(flat[0].size)]
        return np.array(vals, F64).reshape(shape)


def _domain(rest, k, n, fn, default=(-2 * math.pi, 2 * math.pi)):
    """The limits in rest[k] (2 values, or 4 for two variables), or the default."""
    if len(rest) > k and not is_str(rest[k]) and numel(rest[k]) in (2, 4):
        d = darr(rest[k]).reshape(-1).astype(F64)
        if d.size == 2:
            return [d[0], d[1]] * (n // 2 if n == 4 else 1)
        return list(d)
    return list(default) * (2 if n == 4 else 1)


def _title(ax, text):
    REG['title'].fn(0, ax, Char.of(text))


def _grid(rest, k, default=60):
    if len(rest) > k and not is_str(rest[k]) and numel(rest[k]) == 1:
        n = int(num(rest[k]))
        if n < 2:
            raise err('MATLAB:ezsurf:InvalidGrid', 'The grid has at least 2 points a side.', 'ezsurf')
        return n
    return default


def _ez2(fn, kind):
    """ezsurf, ezsurfc, ezmesh, ezmeshc, ezcontour, ezcontourf: f(x, y) on a grid."""
    def f(nargout, *args):
        G = _g()
        ax, rest = G.split_axes_arg(args)
        nargchk(rest, 1, 4, fn)
        h, text = _func(rest[0], 2, fn, ('x', 'y'))
        lim = _domain(rest, 1, 4, fn)
        k = 2 if len(rest) > 1 and not is_str(rest[1]) and numel(rest[1]) in (2, 4) else 1
        n = _grid(rest, k)
        x = np.linspace(lim[0], lim[1], n)
        y = np.linspace(lim[2], lim[3], n)
        X, Y = np.meshgrid(x, y)
        Z = _values(h, X, Y)
        data = ([ax] if ax else []) + [out(X), out(Y), out(Z)]
        if kind in ('surf', 'surfc', 'mesh', 'meshc'):
            r = G._surf(data, 1, kind)
        elif kind == 'contour':
            r = G._contour(data, 1)
        else:
            r = REG['contourf'].fn(1, *data)
        a = ax if ax is not None else G.gca_()
        _title(a, text)
        if kind in ('surf', 'surfc', 'mesh', 'meshc', 'contour', 'contourf'):
            REG['xlabel'].fn(0, a, Char.of('x'))
            REG['ylabel'].fn(0, a, Char.of('y'))
        return r if nargout else None
    f.__name__ = fn
    f.__doc__ = f"""{fn}(f), {fn}(f, [xmin xmax ymin ymax]), {fn}(..., n): f(x, y) (text or a handle) on an n-by-n grid (60) over -2*pi to 2*pi."""
    return f


for _fn, _kind in (('ezsurf', 'surf'), ('ezsurfc', 'surfc'), ('ezmesh', 'mesh'), ('ezmeshc', 'meshc'), ('ezcontour', 'contour'), ('ezcontourf', 'contourf')):
    bi(_fn, arr=False)(_ez2(_fn, _kind))


@bi('ezplot3', arr=False)
def ezplot3(nargout, *args):
    """ezplot3(x, y, z), ezplot3(x, y, z, [tmin tmax]), ezplot3(..., 'animate'):
    the curve (x(t), y(t), z(t)) over 0 to 2*pi; 'animate' draws it and a marker at its end."""
    G = _g()
    ax, rest = G.split_axes_arg(args)
    animate = bool(rest) and is_str(rest[-1]) and py_str(rest[-1]).lower() == 'animate'
    if animate:
        rest = rest[:-1]
    nargchk(rest, 3, 4, 'ezplot3')
    hs, texts = zip(*(_func(r, 1, 'ezplot3', ('t',)) for r in rest[:3]))
    lim = _domain(rest, 3, 2, 'ezplot3', (0.0, 2 * math.pi))
    t = np.linspace(lim[0], lim[1], 300)
    xyz = [_values(h, t).reshape(1, -1) for h in hs]
    r = REG['plot3'].fn(1, *(([ax] if ax else []) + [out(v) for v in xyz]))
    a = ax if ax is not None else G.gca_()
    if animate:
        REG['hold'].fn(0, a, Char.of('on'))
        REG['plot3'].fn(0, a, xyz[0][0, -1], xyz[1][0, -1], xyz[2][0, -1], Char.of('o'), Char.of('MarkerFaceColor'), Char.of('r'))
        REG['hold'].fn(0, a, Char.of('off'))
    _title(a, f'x = {texts[0]}, y = {texts[1]}, z = {texts[2]}')
    for lab, nm in (('xlabel', 'x'), ('ylabel', 'y'), ('zlabel', 'z')):
        REG[lab].fn(0, a, Char.of(nm))
    REG['grid'].fn(0, a, Char.of('on'))
    return r if nargout else None


@bi('ezplot', arr=False)
def ezplot(nargout, *args):
    """ezplot(f), ezplot(f, [a b]), ezplot(f, [xmin xmax ymin ymax]): f(x) over -2*pi to 2*pi, or the curve
    f(x, y) = 0 for a function of two variables; f as text or a handle, the plot titled with it."""
    G = _g()
    ax, rest = G.split_axes_arg(args)
    nargchk(rest, 1, 2, 'ezplot')
    f = rest[0]
    if isinstance(f, FH):
        m = re.match(r'^@\(([^)]*)\)', f.text())
        nv = len([v for v in m.group(1).split(',') if v.strip()]) if m else 1
    elif is_str(f):
        nv = 2 if len(_vars_of(py_str(f))) == 2 else 1
    else:
        nv = 1
    pre = [ax] if ax is not None else []
    if nv == 2:
        h, text = _func(f, 2, 'ezplot', ('x', 'y'))
        lim = _domain(rest, 1, 4, 'ezplot')
        r = REG['fimplicit'].fn(1, *(pre + [h, out(np.array([lim]))]))
        title = f'{text} = 0'
    else:
        h, text = _func(f, 1, 'ezplot', ('x',))
        lim = _domain(rest, 1, 2, 'ezplot')
        r = REG['fplot'].fn(1, *(pre + [h, out(np.array([lim]))]))
        title = text
    a = ax if ax is not None else G.gca_()
    _title(a, title)
    REG['xlabel'].fn(0, a, Char.of('x'))
    if nv == 2:
        REG['ylabel'].fn(0, a, Char.of('y'))
    return r if nargout else None


@bi('ezpolar', arr=False)
def ezpolar(nargout, *args):
    """ezpolar(f), ezpolar(f, [a b]): the curve r = f(theta) in polar axes, theta from 0 to 2*pi."""
    G = _g()
    ax, rest = G.split_axes_arg(args)
    nargchk(rest, 1, 2, 'ezpolar')
    h, text = _func(rest[0], 1, 'ezpolar', ('t',))
    lim = _domain(rest, 1, 2, 'ezpolar', (0.0, 2 * math.pi))
    th = np.linspace(lim[0], lim[1], 400)
    rho = _values(h, th)
    r = REG['polarplot'].fn(1, *(([ax] if ax else []) + [out(th.reshape(1, -1)), out(rho.reshape(1, -1))]))
    a = ax if ax is not None else G.gca_()
    _title(a, f'r = {text}')
    return r if nargout else None


# ---- camlookat ----------------------------------------------------------------------------------------------------------------

def _bounds(objs):
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for o in objs:
        p = o.props
        if 'Vertices' in p and np.asarray(p.get('Vertices')).size:
            V = np.asarray(p['Vertices'], F64)
            cols = [V[:, k] if k < V.shape[1] else np.zeros(len(V)) for k in range(3)]
        elif 'XData' in p:
            x = np.asarray(arr(p.get('XData')), F64).reshape(-1)
            y = np.asarray(arr(p.get('YData')), F64).reshape(-1)
            zd = p.get('ZData')
            z = np.asarray(arr(zd), F64).reshape(-1) if zd is not None and numel(zd) else np.zeros(1)
            cols = [x, y, z]
        elif 'Position' in p and getattr(o, 'TYPE', '') == 'text':
            pos = np.asarray(p['Position'], F64).reshape(-1)
            cols = [pos[0:1], pos[1:2], pos[2:3] if pos.size > 2 else np.zeros(1)]
        else:
            continue
        for k in range(3):
            c = cols[k][np.isfinite(cols[k])]
            if c.size:
                lo[k], hi[k] = min(lo[k], c.min()), max(hi[k], c.max())
    return lo, hi


@bi('camlookat', arr=False)
def camlookat(nargout, *args):
    """camlookat(h): the view centred on the objects (CameraTarget their
    middle) and closed in on them (CameraViewAngle) until they fill it;
    camlookat(ax) or camlookat: all the axes' objects, the view reset."""
    nargchk(args, 0, 1, 'camlookat')
    G, GB = _g(), _gb()
    target = args[0] if args else G.gca_()
    objs = [GB.handle_of_number(float(x)) for x in np.asarray(darr(target)).reshape(-1)] if isinstance(target, (float, np.ndarray)) else (
        list(target.items()) if hasattr(target, 'items') else [target])
    objs = [o for o in objs if o is not None]
    if not objs:
        raise err('MATLAB:camlookat:InvalidHandle', 'camlookat takes graphics objects or axes.', 'camlookat')
    ax = objs[0]
    while ax is not None and not isinstance(ax, GB.Axes):
        ax = getattr(ax, 'parent', None)
    if ax is None:
        raise err('MATLAB:camlookat:InvalidHandle', 'The objects are not in axes.', 'camlookat')
    if isinstance(objs[0], GB.Axes):
        # the whole axes: the camera as it was before any camera function
        ax.props['CameraTargetMode'] = 'auto'
        ax.props['CameraViewAngleMode'] = 'auto'
        ax.touch()
        return None
    lo, hi = _bounds(objs)
    if not np.all(np.isfinite(lo)):
        raise err('MATLAB:camlookat:NoData', 'The objects hold no data to look at.', 'camlookat')
    lims = [np.asarray(arr(ax.get_value(k)), F64).reshape(-1) for k in ('XLim', 'YLim', 'ZLim')]
    span = np.array([max(l[1] - l[0], 1e-300) for l in lims])
    three = ax.is3d()
    # the plot box's proportions as drawn: the spans over the data aspect ratio when that is fixed (axis equal), else its own
    # ratio; a box taken as a cube made an object long in a long box look far bigger than it is (a 2-unit sphere in an 8-unit
    # box was closed in on by a fifth)
    if ax.props.get('DataAspectRatioMode') == 'manual':
        box = span / np.maximum(np.asarray(arr(ax.props['DataAspectRatio']), F64).reshape(-1)[:3], 1e-300)
    else:
        box = np.asarray(arr(ax.get_value('PlotBoxAspectRatio')), F64).reshape(-1)[:3]
    box = box / max(float(box.max()), 1e-300)
    size = (hi - lo) / span * box
    if not three:
        size, box = size[:2], box[:2]
    whole = float(np.linalg.norm(box))
    part = max(float(np.linalg.norm(size)), 1e-6 * whole)
    zoom = min(whole / part, 20.0)          # a point or a line still leaves some of its surroundings in view
    auto = ax.auto_view_angle()
    angle = math.degrees(2 * math.atan(math.tan(math.radians(auto) / 2) / zoom))
    ax.props['CameraTarget'] = ((lo + hi) / 2).reshape(1, 3)
    ax.props['CameraTargetMode'] = 'manual'
    ax.props['CameraViewAngle'] = min(angle, auto)
    ax.props['CameraViewAngleMode'] = 'manual'
    ax.touch()
    return None


# ---- streamribbon ---------------------------------------------------------------------------------------------------------------

def _ribbon(L, twist, width):
    """X, Y, Z (n-by-2) of a ribbon of the given width along the polyline L,
    turned by the angles twist (radians) about the line from a frame carried
    along it."""
    n = len(L)
    T = np.gradient(L, axis=0)
    nt = np.linalg.norm(T, axis=1, keepdims=True)
    T /= np.where(nt == 0, 1, nt)
    a = np.cross(T[0], [0, 0, 1.0] if abs(T[0][2]) < 0.9 else [1.0, 0, 0])
    a /= np.linalg.norm(a)
    A = np.zeros_like(L)
    A[0] = a
    for i in range(1, n):
        a = a - T[i] * float(a @ T[i])
        na = np.linalg.norm(a)
        if na < 1e-12:
            a = np.cross(T[i], [0, 0, 1.0] if abs(T[i][2]) < 0.9 else [1.0, 0, 0])
            na = np.linalg.norm(a)
        a = a / na
        A[i] = a
    B = np.cross(T, A)
    c, s = np.cos(twist)[:, None], np.sin(twist)[:, None]
    D = c * A + s * B
    w = np.broadcast_to(np.asarray(width, F64).reshape(-1, 1), (n, 1)) / 2
    P0, P1 = L - w * D, L + w * D
    return (np.column_stack([P0[:, k], P1[:, k]]) for k in range(3))


@bi('streamribbon', arr=False)
def streamribbon(nargout, *args):
    """streamribbon(X, Y, Z, U, V, W, startx, starty, startz): ribbons along
    the streamlines, turning about each line as the flow spins about it (half
    the curl along the flow, integrated over the time to travel); also
    streamribbon(verts, X, Y, Z, cav, speed), streamribbon(verts, cav, speed),
    streamribbon(verts, twistangle), and a width last."""
    nargchk(args, 2, 12, 'streamribbon')
    from .moreplots import _volume_field, _grid_vectors, _field_at
    G, GB = _g(), _gb()
    rest = list(args)
    width = None
    lines, twists = [], []
    if type(rest[0]) is Cell:
        lines = [np.asarray(darr(c), F64) for c in rest[0].a.reshape(-1, order='F')]
        more = rest[1:]
        if len(more) in (1, 2) and type(more[0]) is Cell:
            # verts, twistangle (a cell of angles for each line)
            twists = [np.asarray(darr(c), F64).reshape(-1) for c in more[0].a.reshape(-1, order='F')]
            if len(more) == 2:
                width = float(num(more[1]))
        elif len(more) >= 2 and type(more[0]) is Cell and type(more[1]) is Cell:
            cavs = [np.asarray(darr(c), F64).reshape(-1) for c in more[0].a.reshape(-1, order='F')]
            spds = [np.asarray(darr(c), F64).reshape(-1) for c in more[1].a.reshape(-1, order='F')]
            twists = [_integrate_twist(L, cv, sp) for L, cv, sp in zip(lines, cavs, spds)]
            if len(more) > 2:
                width = float(num(more[2]))
        elif len(more) >= 5:
            X, Y, Z, CAV, SPD = (darr(m).astype(F64) for m in more[:5])
            for L in lines:
                L = L[np.all(np.isfinite(L), axis=1)] if L.size else L
                cv = _field_at(X, Y, Z, CAV, L[:, 0], L[:, 1], L[:, 2]) if len(L) else np.zeros(0)
                sp = _field_at(X, Y, Z, SPD, L[:, 0], L[:, 1], L[:, 2]) if len(L) else np.zeros(0)
                twists.append(_integrate_twist(L, cv, sp))
            if len(more) > 5:
                width = float(num(more[5]))
        else:
            raise err('MATLAB:streamribbon:InvalidInput', 'After the vertices give twistangle, or cav and speed (cells or volumes).', 'streamribbon')
        cell = max(float(np.ptp(np.vstack([L for L in lines if L.size]))) if any(L.size for L in lines) else 1.0, 1e-12) / 20
    else:
        if len(rest) in (7, 10):
            width = float(num(rest.pop()))
        X, Y, Z, U, V, W, extra = _volume_field(rest, 'streamribbon')
        if len(extra) != 3:
            raise err('MATLAB:minrhs', 'Give the starting points startx, starty and startz.', 'streamribbon')
        lines = [np.asarray(darr(c), F64) for c in REG['stream3'].fn(1, *(out(A) for A in (X, Y, Z, U, V, W)), *extra).a.reshape(-1, order='F')]
        xv, yv, zv = _grid_vectors(X, Y, Z, U)
        g = lambda F, ax_, v: np.gradient(F, v, axis=ax_) if v.size > 1 else np.zeros_like(F)
        # the curl, and half of it along the flow: how fast the flow spins about itself
        cx = g(W, 0, yv) - g(V, 2, zv)
        cy = g(U, 2, zv) - g(W, 1, xv)
        cz = g(V, 1, xv) - g(U, 0, yv)
        spd = np.sqrt(U ** 2 + V ** 2 + W ** 2)
        with np.errstate(invalid='ignore', divide='ignore'):
            cav = 0.5 * (cx * U + cy * V + cz * W) / np.where(spd == 0, 1, spd)
        for L in lines:
            L = L[np.all(np.isfinite(L), axis=1)] if L.size else L
            if len(L) < 2:
                twists.append(np.zeros(len(L)))
                continue
            cv = np.nan_to_num(_field_at(X, Y, Z, cav, L[:, 0], L[:, 1], L[:, 2]))
            sp = np.nan_to_num(_field_at(X, Y, Z, spd, L[:, 0], L[:, 1], L[:, 2]))
            twists.append(_integrate_twist(L, cv, sp))
        cell = float(np.mean([np.mean(np.abs(np.diff(v))) if v.size > 1 else 1.0 for v in (xv, yv, zv)]))
    w = width if width is not None else cell * 1.0
    ax = G.newplot(None)
    hs = []
    for L, tw in zip(lines, twists + [None] * (len(lines) - len(twists))):
        L = L[np.all(np.isfinite(L), axis=1)] if L.size else L
        if len(L) < 2:
            continue
        tw = np.zeros(len(L)) if tw is None or len(tw) != len(L) else np.nan_to_num(tw)
        Xr, Yr, Zr = _ribbon(L, tw, w)
        s = GB.Surface(ax)
        s.props['XData'], s.props['YData'], s.props['ZData'] = Xr, Yr, Zr
        s.props['CData'] = Zr
        hs.append(s)
    REG['view'].fn(0, ax, 3.0)
    ax.touch()
    return G.handles_out(hs) if nargout else None


def _integrate_twist(L, cav, speed):
    """The angle turned by each vertex: the spin over the speed, summed along the arc."""
    n = len(L)
    if n < 2:
        return np.zeros(n)
    cav = np.broadcast_to(np.asarray(cav, F64).reshape(-1), (n,)) if np.asarray(cav).size in (1, n) else np.zeros(n)
    speed = np.broadcast_to(np.asarray(speed, F64).reshape(-1), (n,)) if np.asarray(speed).size in (1, n) else np.ones(n)
    ds = np.linalg.norm(np.diff(L, axis=0), axis=1)
    with np.errstate(invalid='ignore', divide='ignore'):
        rate = np.where(speed > 0, cav / speed, 0.0)
    mid = (rate[:-1] + rate[1:]) / 2
    return np.concatenate([[0.0], np.cumsum(np.nan_to_num(mid) * ds)])


# ---- reflectance ------------------------------------------------------------------------------------------------------------------

def _direction(v, fn):
    """A unit vector from [x y z], or from [az el] in degrees."""
    d = np.asarray(darr(v), F64).reshape(-1)
    if d.size == 2:
        az, el = np.radians(d)
        d = np.array([math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)])
    if d.size != 3 or not np.any(d):
        raise err(f'MATLAB:{fn}:InvalidDirection', 'A direction is [x y z] or [azimuth elevation] in degrees.', fn)
    return d / np.linalg.norm(d)


def _normals(args, fn):
    Nx, Ny, Nz = (np.asarray(darr(a), F64) for a in args[:3])
    if not (Nx.shape == Ny.shape == Nz.shape):
        raise err(f'MATLAB:{fn}:SizeMismatch', 'Nx, Ny and Nz are arrays of one size.', fn)
    m = np.sqrt(Nx ** 2 + Ny ** 2 + Nz ** 2)
    m = np.where(m == 0, 1, m)
    return Nx / m, Ny / m, Nz / m


@bi('diffuse')
def diffuse(nargout, *args):
    """R = diffuse(Nx, Ny, Nz, S): the diffuse (Lambert) reflectance of a
    surface with these normals lit from direction S: the cosine of the angle
    between normal and light, 0 where the light is behind."""
    nargchk(args, 4, 4, 'diffuse')
    nx, ny, nz = _normals(args, 'diffuse')
    s = _direction(args[3], 'diffuse')
    return out(np.maximum(0.0, nx * s[0] + ny * s[1] + nz * s[2]))


@bi('specular')
def specular(nargout, *args):
    """R = specular(Nx, Ny, Nz, S, V, spread): the specular reflectance of a
    surface with these normals, lit from direction S and seen from V: the
    cosine of the angle between the mirrored light and the view, to the
    power spread (10), 0 where the light is behind."""
    nargchk(args, 5, 6, 'specular')
    nx, ny, nz = _normals(args, 'specular')
    s = _direction(args[3], 'specular')
    v = _direction(args[4], 'specular')
    spread = float(num(args[5])) if len(args) > 5 else 10.0
    if not spread > 0:
        raise err('MATLAB:specular:InvalidSpread', 'The spread is a positive number.', 'specular')
    ns = nx * s[0] + ny * s[1] + nz * s[2]
    rx, ry, rz = 2 * ns * nx - s[0], 2 * ns * ny - s[1], 2 * ns * nz - s[2]
    c = np.maximum(0.0, rx * v[0] + ry * v[1] + rz * v[2])
    return out(np.where(ns > 0, c ** spread, 0.0))


# ---- paper and clipboard ----------------------------------------------------------------------------------------------------------

@bi('orient', arr=False)
def orient(nargout, *args):
    """orient(fig, o) or orient o: the paper's orientation for printing,
    'portrait', 'landscape' or 'tall' (portrait, the figure filling the page);
    orient(fig) gives it."""
    nargchk(args, 0, 2, 'orient')
    G, GB = _g(), _gb()
    rest = list(args)
    fig = None
    if rest and not is_str(rest[0]):
        fig = rest.pop(0)
        if isinstance(fig, float):
            fig = GB.handle_of_number(fig)
        if not isinstance(fig, GB.Figure):
            raise err('MATLAB:orient:InvalidFigure', 'orient takes a figure.', 'orient')
    if fig is None:
        fig = G.gcf_()
    if not rest:
        return Char.of(fig.props.get('PaperOrientation', 'portrait'))
    o = py_str(rest[0]).lower()
    if o not in ('portrait', 'landscape', 'tall'):
        raise err('MATLAB:orient:InvalidOrientation', "The orientation is 'portrait', 'landscape' or 'tall'.", 'orient')
    size = np.asarray(arr(fig.get_value('PaperSize')), F64).reshape(-1)
    w, h = (max(size), min(size)) if o == 'landscape' else (min(size), max(size))
    fig.props['PaperOrientation'] = 'landscape' if o == 'landscape' else 'portrait'
    fig.props['PaperSize'] = np.array([[w, h]])
    if o == 'tall':
        margin = 0.25 if fig.props.get('PaperUnits', 'inches') == 'inches' else 0.25 * 2.54 if fig.props.get('PaperUnits') == 'centimeters' else 0.0
        fig.props['PaperPosition'] = np.array([[margin, margin, w - 2 * margin, h - 2 * margin]])
        fig.props['PaperPositionMode'] = 'manual'
    return None


@bi('copygraphics', aw=True, arr=False)
async def copygraphics(nargout, *args):
    """copygraphics(target, 'ContentType', 'image', 'Resolution', dpi,
    'BackgroundColor', c): the figure (or the figure of the axes or chart
    given) copied to the clipboard as a picture."""
    nargchk(args, 1, 9, 'copygraphics')
    G, GB = _g(), _gb()
    target = args[0]
    if isinstance(target, float):
        target = GB.handle_of_number(target)
    k = 1
    while k < len(args):
        o = (opt_str(args[k]) or '').lower()
        if o not in ('contenttype', 'resolution', 'backgroundcolor', 'padding') or k + 1 >= len(args):
            raise err('MATLAB:copygraphics:InvalidOption', "The options are 'ContentType', 'Resolution', 'BackgroundColor' and 'Padding'.", 'copygraphics')
        k += 2
    fig = target
    while fig is not None and not isinstance(fig, GB.Figure):
        fig = getattr(fig, 'parent', None)
    if fig is None:
        raise err('MATLAB:copygraphics:InvalidTarget', 'copygraphics takes a figure, axes or chart.', 'copygraphics')
    G.flush_figures()
    if not await R.ask_page({'type': 'copyfig', 'figure': fig.id}):
        R.warn('MATLAB:copygraphics:clipboard', 'The figure could not be copied to the clipboard here.')
    return None
