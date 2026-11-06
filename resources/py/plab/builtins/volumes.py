"""Volumes and implicit surfaces: fimplicit3, tetramesh, isocaps,
isonormals, smooth3, reducepatch, reducevolume, subvolume, volumebounds,
streamslice and streamparticles."""
import math

import numpy as np

from . import bi as _register
from ._util import err, nargchk, out, num, opt_str, is_str, darr
from ..values import MError, Char, Cell, Struct, FH, EMPTY, numel, py_str
from .. import runtime as R


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        aw = kw.get('aw', False)
        if aw:
            async def g(*a):
                try:
                    return await f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, ZeroDivisionError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        else:
            def g(*a):
                try:
                    return f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, ZeroDivisionError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _g():
    from . import graphics as G
    return G


def _gb():
    from .. import graphics_base as GB
    return GB


def _mp():
    from . import moreplots as M
    return M


# ---- implicit surfaces and tetrahedra --------------------------------------------------------------------------------------------

@bi('fimplicit3', aw=True)
async def fimplicit3(nargout, *args):
    """fs = fimplicit3(f), fimplicit3(f, [min max]), fimplicit3(f, [xmin xmax ymin ymax zmin zmax], 'MeshDensity', n): the surface f(x, y, z) = 0."""
    G, GB = _g(), _gb()
    a = list(args)
    ax, a = G.split_axes_arg(a)
    f = a.pop(0)
    if not isinstance(f, FH):
        raise err('MATLAB:fimplicit3:function', 'fimplicit3 takes a function handle of x, y and z.', 'fimplicit3')
    lim = darr(a.pop(0)).reshape(-1).astype(float) if a and not is_str(a[0]) else np.array([-5.0, 5.0])
    if lim.size == 2:
        lim = np.tile(lim, 3)
    if lim.size != 6:
        raise err('MATLAB:fimplicit3:interval', 'The interval is [min max] or [xmin xmax ymin ymax zmin zmax].', 'fimplicit3')
    o = {}
    for i in range(0, len(a) - 1, 2):
        o[py_str(a[i]).lower()] = a[i + 1]
    n = int(num(o.pop('meshdensity', 35.0)))
    xs, ys, zs = (np.linspace(lim[2 * k], lim[2 * k + 1], n) for k in range(3))
    X, Y, Z = np.meshgrid(xs, ys, zs)
    V = await f.acall(1, out(X), out(Y), out(Z))
    V = np.asarray(darr(V), float)
    if V.shape != X.shape:
        V = np.broadcast_to(V, X.shape).astype(float)
    F, P, Cv = _mp()._isosurface(X, Y, Z, V, 0.0, np.broadcast_to(Z, X.shape).astype(float))
    ax = G.newplot(ax)
    h = GB.Patch(ax)
    h.props['Faces'], h.props['Vertices'] = F, P
    h.props['FaceVertexCData'] = Cv
    h.props['FaceColor'] = 'interp'
    h.props['EdgeColor'] = 'none'
    for k, v in o.items():
        h.setprop(k, v)
    R.BUILTINS['view'].fn(0, ax, 3.0)
    ax.props['XLim'] = lim[0:2].reshape(1, 2)
    ax.props['YLim'] = lim[2:4].reshape(1, 2)
    ax.props['ZLim'] = lim[4:6].reshape(1, 2)
    ax.props['XLimMode'] = ax.props['YLimMode'] = ax.props['ZLimMode'] = 'manual'
    ax.touch()
    return h if nargout else None


@bi('tetramesh')
def tetramesh(nargout, *args):
    """h = tetramesh(T, X), tetramesh(T, X, c), tetramesh(TR): tetrahedra drawn as their faces, each coloured from the colormap by c (1, 2, ... unless given)."""
    G, GB = _g(), _gb()
    a = list(args)
    T = np.asarray(darr(a.pop(0)), float).astype(int) - 1
    X = np.asarray(darr(a.pop(0)), float)
    if T.ndim != 2 or T.shape[1] != 4 or X.shape[1] != 3:
        raise err('MATLAB:tetramesh:inputs', 'T is m-by-4 (indices into X) and X n-by-3.', 'tetramesh')
    c = darr(a.pop(0)).reshape(-1).astype(float) if a and not is_str(a[0]) else np.arange(1, T.shape[0] + 1, dtype=float)
    ax = G.newplot(None)
    hs = []
    faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
    for k in range(T.shape[0]):
        h = GB.Patch(ax)
        h.props['Vertices'] = X[T[k]]
        h.props['Faces'] = (faces + 1).astype(float)
        h.props['FaceVertexCData'] = np.full((4, 1), c[k])
        h.props['FaceColor'] = 'flat'
        h.props['EdgeColor'] = (0.0, 0.0, 0.0)
        h.props['FaceAlpha'] = 0.9
        for i in range(0, len(a) - 1, 2):
            h.setprop(py_str(a[i]), a[i + 1])
        hs.append(h)
    ax.props['CLim'] = np.array([[c.min(), c.max() if c.max() > c.min() else c.min() + 1]])
    R.BUILTINS['view'].fn(0, ax, 3.0)
    ax.touch()
    return G.handles_out(hs) if nargout else None


# ---- isocaps and isonormals ----------------------------------------------------------------------------------------------------------

def _cap_polys(V2, iso, above):
    """For a 2-D slice of values, the polygons (as lists of (i, j) points in grid coordinates) of the region above (or below)
    iso: each cell clipped by linear interpolation along its edges."""
    polys = []
    m, n = V2.shape
    sgn = 1.0 if above else -1.0
    W = sgn * (V2 - iso)
    for i in range(m - 1):
        for j in range(n - 1):
            corners = [(i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j)]
            vals = [W[p] for p in corners]
            if all(v < 0 for v in vals) or any(not np.isfinite(v) for v in vals):
                continue
            pts = []
            for k in range(4):
                p, q = corners[k], corners[(k + 1) % 4]
                vp, vq = vals[k], vals[(k + 1) % 4]
                if vp >= 0:
                    pts.append((float(p[0]), float(p[1])))
                if (vp >= 0) != (vq >= 0):
                    t = vp / (vp - vq)
                    pts.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
            if len(pts) >= 3:
                polys.append(pts)
    return polys


@bi('isocaps', nout=3)
def isocaps(nargout, *args):
    """fvc = isocaps(X, Y, Z, V, isovalue), isocaps(V, isovalue), isocaps(..., 'enclose', 'below'), [f, v, c] = isocaps(...): the faces closing an isosurface where it meets the volume's boundary."""
    G, GB = _g(), _gb()
    a = list(args)
    enclose, which = 'above', 'all'
    words = [i for i, x in enumerate(a) if is_str(x)]
    for i in reversed(words):
        w = py_str(a[i]).lower()
        if w in ('above', 'below'):
            enclose = w
        elif w in ('all', 'xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax'):
            which = w
        elif w == 'enclose' or w == 'whichplane':
            pass
        a.pop(i)
    X, Y, Z, V, rest = _mp()._volume_args(a, 'isocaps')
    iso = float(num(rest[0])) if rest else float(np.nanmean(V))
    xs, ys, zs = X[0, :, 0], Y[:, 0, 0], Z[0, 0, :]
    verts, faces, cols = [], [], []
    planes = {'xmin': (1, 0), 'xmax': (1, -1), 'ymin': (0, 0), 'ymax': (0, -1), 'zmin': (2, 0), 'zmax': (2, -1)}
    for name, (axis, idx) in planes.items():
        if which not in ('all', name):
            continue
        V2 = np.take(V, idx, axis=axis)
        for poly in _cap_polys(V2, iso, enclose == 'above'):
            base = len(verts)
            for (u, w) in poly:
                # (u, w) indexes the slice's two remaining dimensions in order
                if axis == 0:
                    pt = (np.interp(u, np.arange(xs.size), xs), ys[idx], np.interp(w, np.arange(zs.size), zs))
                    cval = _interp2(V2, u, w)
                elif axis == 1:
                    pt = (xs[idx], np.interp(u, np.arange(ys.size), ys), np.interp(w, np.arange(zs.size), zs))
                    cval = _interp2(V2, u, w)
                else:
                    pt = (np.interp(w, np.arange(xs.size), xs), np.interp(u, np.arange(ys.size), ys), zs[idx])
                    cval = _interp2(V2, u, w)
                verts.append(pt)
                cols.append(cval)
            for k in range(1, len(poly) - 1):
                faces.append([base + 1, base + k + 1, base + k + 2])
    F = np.array(faces, float).reshape(-1, 3)
    P = np.array(verts, float).reshape(-1, 3)
    Cv = np.array(cols, float).reshape(-1, 1)
    if nargout >= 2:
        return (out(F), out(P), out(Cv))[:nargout]
    if nargout == 1:
        return Struct.scalar({'vertices': out(P), 'faces': out(F), 'facevertexcdata': out(Cv)})
    ax = G.newplot(None)
    h = GB.Patch(ax)
    h.props['Faces'], h.props['Vertices'], h.props['FaceVertexCData'] = F, P, Cv
    h.props['FaceColor'] = 'interp'
    h.props['EdgeColor'] = 'none'
    R.BUILTINS['view'].fn(0, ax, 3.0)
    ax.touch()
    return None


def _interp2(A, u, w):
    i0, j0 = int(min(math.floor(u), A.shape[0] - 2)), int(min(math.floor(w), A.shape[1] - 2))
    i0, j0 = max(i0, 0), max(j0, 0)
    fu, fw = u - i0, w - j0
    return float(A[i0, j0] * (1 - fu) * (1 - fw) + A[i0 + 1, j0] * fu * (1 - fw) + A[i0, j0 + 1] * (1 - fu) * fw + A[i0 + 1, j0 + 1] * fu * fw)


def _vertex_normals_prop():
    GB = _gb()
    if 'VertexNormals' not in GB.Patch.DEFAULTS:
        GB.Patch.DEFAULTS['VertexNormals'] = lambda: EMPTY()
        GB.register(GB.Patch)


@bi('isonormals')
def isonormals(nargout, *args):
    """n = isonormals(X, Y, Z, V, vertices), isonormals(V, vertices), isonormals(..., p), isonormals(..., 'negate'): the normals of an isosurface at its vertices, from the volume's gradient (pointing to lower values)."""
    GB = _gb()
    a = list(args)
    negate = any(is_str(x) and py_str(x).lower() == 'negate' for x in a)
    a = [x for x in a if not (is_str(x) and py_str(x).lower() == 'negate')]
    target = a.pop() if a and isinstance(a[-1], GB.Patch) else None
    if target is not None:
        verts = np.asarray(target.props['Vertices'], float)
    else:
        verts = np.asarray(darr(a.pop()), float)
    X, Y, Z, V, _ = _mp()._volume_args(a, 'isonormals')
    xs, ys, zs = X[0, :, 0], Y[:, 0, 0], Z[0, 0, :]
    gy, gx, gz = np.gradient(V, ys, xs, zs) if min(V.shape) > 1 else (np.zeros_like(V),) * 3
    from scipy.interpolate import RegularGridInterpolator as RGI
    pts = np.column_stack([verts[:, 1], verts[:, 0], verts[:, 2]])
    N = np.column_stack([RGI((ys, xs, zs), g, bounds_error=False, fill_value=None)(pts) for g in (gx, gy, gz)])
    N = -N if not negate else N
    if target is not None:
        _vertex_normals_prop()
        target.props['VertexNormals'] = N
        target.props['VertexNormalsMode'] = 'manual'
        target.touch()
        return None
    return out(N)


# ---- smoothing and reducing ------------------------------------------------------------------------------------------------------

@bi('smooth3')
def smooth3(nargout, *args):
    """W = smooth3(V), smooth3(V, 'box'|'gaussian', size, sd): a volume smoothed by a box or Gaussian kernel (3 by 3 by 3, sd 0.65), edges replicated."""
    from scipy import ndimage
    nargchk(args, 1, 4, 'smooth3')
    V = np.asarray(darr(args[0], 'smooth3'), float)
    if V.ndim != 3:
        raise err('MATLAB:smooth3:dims', 'smooth3 takes a 3-D array.', 'smooth3')
    kind = py_str(args[1]).lower() if len(args) > 1 else 'box'
    sz = darr(args[2]).reshape(-1).astype(int) if len(args) > 2 else np.array([3])
    sz = np.repeat(sz, 3) if sz.size == 1 else sz
    if np.any(sz % 2 == 0) or np.any(sz < 1):
        raise err('MATLAB:smooth3:size', 'The kernel size is odd.', 'smooth3')
    if kind == 'box':
        k = np.ones(tuple(sz)) / np.prod(sz)
    elif kind == 'gaussian':
        sd = float(num(args[3])) if len(args) > 3 else 0.65
        g = [np.exp(-(np.arange(n) - (n - 1) / 2) ** 2 / (2 * sd * sd)) for n in sz]
        k = np.einsum('i,j,k->ijk', *g)
        k /= k.sum()
    else:
        raise err('MATLAB:smooth3:filter', "The filter is 'box' or 'gaussian'.", 'smooth3')
    return ndimage.correlate(V, k, mode='nearest')


@bi('reducevolume', nout=4)
def reducevolume(nargout, *args):
    """[nx, ny, nz, nv] = reducevolume(X, Y, Z, V, [Rx Ry Rz]), nv = reducevolume(V, R): every R-th element kept in each dimension."""
    a = list(args)
    r = darr(a.pop()).reshape(-1).astype(int)
    r = np.repeat(r, 3) if r.size == 1 else r
    X, Y, Z, V, _ = _mp()._volume_args(a, 'reducevolume')
    sl = (slice(None, None, int(r[1])), slice(None, None, int(r[0])), slice(None, None, int(r[2])))
    res = [X[sl], Y[sl], Z[sl], V[sl]]
    if nargout <= 1:
        return res[3]
    return tuple(res[:nargout])


@bi('subvolume', nout=4)
def subvolume(nargout, *args):
    """[Nx, Ny, Nz, Nv] = subvolume(X, Y, Z, V, limits), Nv = subvolume(V, limits): the part of a volume within [xmin xmax ymin ymax zmin zmax] (NaN: no limit)."""
    a = list(args)
    lim = darr(a.pop()).reshape(-1).astype(float)
    if lim.size != 6:
        raise err('MATLAB:subvolume:limits', 'The limits are [xmin xmax ymin ymax zmin zmax].', 'subvolume')
    X, Y, Z, V, _ = _mp()._volume_args(a, 'subvolume')
    xs, ys, zs = X[0, :, 0], Y[:, 0, 0], Z[0, 0, :]

    def keep(v, lo, hi):
        return (v >= (lo if np.isfinite(lo) else -np.inf)) & (v <= (hi if np.isfinite(hi) else np.inf))
    ix, iy, iz = keep(xs, lim[0], lim[1]), keep(ys, lim[2], lim[3]), keep(zs, lim[4], lim[5])
    res = [A[np.ix_(iy, ix, iz)] for A in (X, Y, Z, V)]
    if nargout <= 1:
        return res[3]
    return tuple(res[:nargout])


@bi('volumebounds')
def volumebounds(nargout, *args):
    """lims = volumebounds(X, Y, Z, V) or volumebounds(V): [xmin xmax ymin ymax zmin zmax cmin cmax]; with U, V, W only the coordinates."""
    a = list(args)
    vecs = len(a) in (6, 3)
    if vecs:
        Xs = a[:3] if len(a) == 6 else None
        X, Y, Z, V, _ = _mp()._volume_args((list(Xs) + [a[3]]) if Xs else [a[0]], 'volumebounds')
    else:
        X, Y, Z, V, _ = _mp()._volume_args(a, 'volumebounds')
    b = [X.min(), X.max(), Y.min(), Y.max(), Z.min(), Z.max()]
    if not vecs:
        fin = V[np.isfinite(V)]
        b += [fin.min(), fin.max()] if fin.size else [np.nan, np.nan]
    return np.array([b], float)


def _patch_fv(a, fn):
    GB = _gb()
    v = a[0]
    if isinstance(v, GB.Patch):
        return v, np.asarray(v.props['Faces'], float), np.asarray(v.props['Vertices'], float), a[1:]
    if isinstance(v, Struct):
        return None, np.asarray(darr(v.get1('faces')), float), np.asarray(darr(v.get1('vertices')), float), a[1:]
    return None, np.asarray(darr(a[0]), float), np.asarray(darr(a[1]), float), a[2:]


@bi('reducepatch', nout=2)
def reducepatch(nargout, *args):
    """nfv = reducepatch(p or fv or faces, vertices, r), [nf, nv] = reducepatch(...): a patch with fewer faces, r a fraction of them (or a count), vertices merged on a grid."""
    p, F, Vt, rest = _patch_fv(list(args), 'reducepatch')
    r = float(num(rest[0])) if rest and not is_str(rest[0]) else 0.5
    F = F.astype(int) - 1
    n0 = F.shape[0]
    target = int(round(r * n0)) if r <= 1 else int(r)
    lo, hi = Vt.min(axis=0), Vt.max(axis=0)
    span = np.maximum(hi - lo, 1e-12)

    def reduce(cells):
        q = np.minimum(np.floor((Vt - lo) / span * cells).astype(int), cells - 1)
        keys, inv = np.unique(q, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        nv = np.zeros((keys.shape[0], 3))
        cnt = np.zeros(keys.shape[0])
        np.add.at(nv, inv, Vt)
        np.add.at(cnt, inv, 1)
        nv /= cnt[:, None]
        nf = inv[F]
        # faces whose corners merged are dropped, and faces made twice kept once
        nf = nf[np.array([len(set(f)) == len(f) for f in nf], bool)] if nf.size else nf
        if nf.size:
            _, first = np.unique(np.sort(nf, axis=1), axis=0, return_index=True)
            nf = nf[np.sort(first)]
        used = np.unique(nf) if nf.size else np.zeros(0, int)
        remap = -np.ones(keys.shape[0], int)
        remap[used] = np.arange(used.size)
        return (remap[nf] if nf.size else nf.reshape(0, F.shape[1])), nv[used]
    if target >= n0:
        nf, nv = F, Vt
    else:
        lo_c, hi_c = 1, 2048
        best = None
        while lo_c < hi_c:
            mid = (lo_c + hi_c) // 2
            nf, nv = reduce(mid)
            if nf.shape[0] < target:
                lo_c = mid + 1
            else:
                best = (nf, nv)
                hi_c = mid
        nf, nv = best if best is not None else reduce(lo_c)
    NF, NV = (nf + 1).astype(float), np.asarray(nv, float)
    if p is not None and nargout == 0:
        p.props['Faces'], p.props['Vertices'] = NF, NV
        p.touch()
        return None
    if nargout >= 2:
        return out(NF), out(NV)
    return Struct.scalar({'faces': out(NF), 'vertices': out(NV)})


# ---- streamslice and streamparticles ----------------------------------------------------------------------------------------------------

def _rk_line(field, start, step, occupied, cell, bounds, maxn, sign):
    """A streamline from start (x, y), forward (sign 1) or back (-1), stopping at the edge, a still point, or a cell another line has taken."""
    pts = [start]
    x, y = start
    for _ in range(maxn):
        def vel(px, py):
            u, v = field(px, py)
            s = math.hypot(u, v)
            return (sign * u / s, sign * v / s) if s > 1e-12 else (0.0, 0.0)
        k1 = vel(x, y)
        if k1 == (0.0, 0.0):
            break
        k2 = vel(x + step / 2 * k1[0], y + step / 2 * k1[1])
        k3 = vel(x + step / 2 * k2[0], y + step / 2 * k2[1])
        k4 = vel(x + step * k3[0], y + step * k3[1])
        nx = x + step / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0])
        ny = y + step / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])
        if not (bounds[0] <= nx <= bounds[1] and bounds[2] <= ny <= bounds[3]):
            break
        key = (int((nx - bounds[0]) / cell), int((ny - bounds[2]) / cell))
        if key in occupied and occupied[key] != id(pts):
            break
        occupied.setdefault(key, id(pts))
        pts.append((nx, ny))
        x, y = nx, ny
    return pts


@bi('streamslice', nout=2)
def streamslice(nargout, *args):
    """h = streamslice(X, Y, U, V), streamslice(U, V), streamslice(..., density, 'noarrows'), [verts, averts] = streamslice(...): streamlines spread evenly over a 2-D vector field, with arrows."""
    G, GB = _g(), _gb()
    a = list(args)
    arrows = True
    for i in reversed(range(len(a))):
        if is_str(a[i]):
            w = py_str(a[i]).lower()
            if w == 'noarrows':
                arrows = False
            a.pop(i)
    nums = [darr(x) for x in a]
    density = 1.0
    if len(nums) in (3, 5) and nums[-1].size == 1:
        density = float(nums.pop()[0])
    if len(nums) == 4:
        X, Y, U, V = (np.asarray(v, float) for v in nums)
    elif len(nums) == 2:
        U, V = (np.asarray(v, float) for v in nums)
        X, Y = np.meshgrid(np.arange(1, U.shape[1] + 1, dtype=float), np.arange(1, U.shape[0] + 1, dtype=float))
    else:
        raise err('MATLAB:streamslice:inputs', 'streamslice(X, Y, U, V) or streamslice(U, V) for a 2-D field (slices of 3-D fields are not drawn here).', 'streamslice')
    if U.ndim != 2:
        raise err('MATLAB:streamslice:dims', 'streamslice takes a 2-D field here (slices of 3-D fields are not drawn).', 'streamslice')
    xs, ys = X[0, :], Y[:, 0]
    from scipy.interpolate import RegularGridInterpolator as RGI
    fu = RGI((ys, xs), U, bounds_error=False, fill_value=0.0)
    fv = RGI((ys, xs), V, bounds_error=False, fill_value=0.0)

    def field(px, py):
        return float(fu((py, px))), float(fv((py, px)))
    bounds = (xs.min(), xs.max(), ys.min(), ys.max())
    size = max(bounds[1] - bounds[0], bounds[3] - bounds[2])
    cell = size / (25 * density)
    step = cell / 3
    occupied = {}
    lines = []
    seeds = [(x0, y0) for y0 in np.linspace(bounds[2], bounds[3], int(12 * density) + 2)[1:-1] for x0 in np.linspace(bounds[0], bounds[1], int(12 * density) + 2)[1:-1]]
    for sx, sy in seeds:
        key = (int((sx - bounds[0]) / cell), int((sy - bounds[2]) / cell))
        if key in occupied:
            continue
        fwd = _rk_line(field, (sx, sy), step, occupied, cell, bounds, 2000, 1)
        back = _rk_line(field, (sx, sy), step, occupied, cell, bounds, 2000, -1)
        pts = back[::-1] + fwd[1:]
        if len(pts) >= 4:
            lines.append(np.array(pts, float))
    averts = []
    if arrows:
        for L in lines:
            k = len(L) // 2
            p, q = L[k - 1], L[k]
            d = q - p
            nrm = math.hypot(*d)
            if nrm == 0:
                continue
            d /= nrm
            al = cell * 0.6
            left = q - al * d + al * 0.5 * np.array([-d[1], d[0]])
            right = q - al * d - al * 0.5 * np.array([-d[1], d[0]])
            averts.append(np.array([left, q, right], float))
    if nargout == 2:
        return Cell.of_list([out(L) for L in lines]), Cell.of_list([out(A) for A in averts])
    ax = G.newplot(None)
    hs = []
    col = (0.0, 0.447, 0.741)
    for L in lines + averts:
        h = GB.Line(ax)
        h.props['XData'], h.props['YData'] = L[:, 0].reshape(1, -1), L[:, 1].reshape(1, -1)
        h.props['Color'] = col
        hs.append(h)
    ax.touch()
    return G.handles_out(hs) if nargout else None


@bi('streamparticles', aw=True)
async def streamparticles(nargout, *args):
    """h = streamparticles(verts, n, 'Animate', k, 'FrameRate', fps, 'ParticleAlignment', 'on', Name, Value): markers along streamlines (from stream2 or stream3), moved along them k times."""
    G, GB = _g(), _gb()
    a = list(args)
    target = None
    if a and isinstance(a[0], GB.Line):
        target = a.pop(0)
    verts = a.pop(0)
    lines = [np.asarray(darr(v), float) for v in (verts.a.reshape(-1) if isinstance(verts, Cell) else [verts])]
    n = int(num(a.pop(0))) if a and not is_str(a[0]) else 30
    o = {}
    for i in range(0, len(a) - 1, 2):
        o[py_str(a[i]).lower()] = a[i + 1]
    animate = int(num(o.pop('animate', 0.0)))
    fps = float(num(o.pop('framerate', 30.0))) if 'framerate' in o else 30.0
    o.pop('particlealignment', None)
    ax = G.gca_(G.gcf_())
    h = target or GB.Line(ax)
    h.props['LineStyle'] = 'none'
    h.props['Marker'] = 'o'
    h.props['MarkerFaceColor'] = (1.0, 0.0, 0.0)
    h.props['Color'] = (1.0, 0.0, 0.0)
    h.props['MarkerSize'] = 4.0
    for k, v in o.items():
        h.setprop(k, v)
    total = sum(len(L) for L in lines)
    every = max(total // max(n, 1), 1)
    three = any(L.shape[1] > 2 for L in lines if L.size)

    def place(shift):
        xs, ys, zs = [], [], []
        for L in lines:
            for k in range(shift % every, len(L), every):
                xs.append(L[k, 0])
                ys.append(L[k, 1])
                zs.append(L[k, 2] if L.shape[1] > 2 else 0.0)
        h.props['XData'] = np.array([xs], float)
        h.props['YData'] = np.array([ys], float)
        h.props['ZData'] = np.array([zs], float) if three else np.zeros((1, 0))
        h.touch()
    place(0)
    for frame in range(animate * every):
        place(frame + 1)
        R.flush_figures()
        await R.sleep(1.0 / fps)
    return h if nargout else None
