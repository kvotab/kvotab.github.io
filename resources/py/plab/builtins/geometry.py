"""Computational geometry: delaunay, convhull, voronoi, voronoin, tsearchn,
dsearchn, rectint, interp3, griddedInterpolant, scatteredInterpolant, and
the triangle plots triplot, trimesh and trisurf."""
import math

import numpy as np

from . import bi
from ._util import err, nargchk, arr, darr, out, opt_str, num, is_str
from ..values import Char, Cell, Struct, Obj, F64, class_of, shape_of, numel, py_str, share
from .. import runtime as R


def _points(args, fn, dims=(2, 3)):
    """The points of x, y (and z), or of a matrix with one per row: an n-by-d
    array, and how many inputs it took."""
    a0 = darr(args[0])
    if len(args) == 1 or (a0.ndim == 2 and a0.shape[1] in dims and a0.shape[1] > 1 and (len(args) < 2 or is_str(args[1]) or numel(args[1]) != a0.size)):
        P = a0.astype(F64)
        if P.ndim != 2 or P.shape[1] not in dims:
            raise err(f'MATLAB:{fn}:InvalidPoints', f'The points must be {" or ".join(map(str, dims))} columns.', fn)
        return P, 1
    cols = []
    for v in args[:max(dims)]:
        if is_str(v) or isinstance(v, Cell):
            break
        cols.append(darr(v).reshape(-1, order='F').astype(F64))
    if len(cols) not in dims or any(c.size != cols[0].size for c in cols):
        raise err(f'MATLAB:{fn}:InvalidPoints', 'The coordinates must be vectors of one length.', fn)
    return np.column_stack(cols), len(cols)


def _ints(a):
    return out(np.asarray(a, F64) + 1)


# ---- triangulations and hulls ----------------------------------------------------------------------------

@bi('delaunay')
def delaunay(nargout, *args):
    """T = delaunay(x, y) or delaunay(x, y, z): the Delaunay triangles (or
    tetrahedra), a row of point indices each, by scipy.spatial.Delaunay
    (Qhull)."""
    nargchk(args, 1, 3, 'delaunay')
    from scipy.spatial import Delaunay
    P, _ = _points(args, 'delaunay')
    if P.shape[0] < P.shape[1] + 1:
        return np.zeros((0, P.shape[1] + 1))
    try:
        tri = Delaunay(P)
    except Exception as e:
        raise err('MATLAB:delaunay:EmptyDelaunay2DErrId', f'The triangulation is empty: the points may be collinear or coincident ({e.__class__.__name__}).', 'delaunay')
    return _ints(tri.simplices)


def _hull_loop(P, hull):
    """The 2-D hull's vertices counterclockwise, the first repeated at the end."""
    v = list(hull.vertices)
    # SciPy gives them counterclockwise already; start from the lowest index as a habit
    return np.array(v + [v[0]])


def _collinear_free(P, loop):
    """The loop without the points that lie on a straight edge."""
    keep = []
    n = len(loop) - 1
    for k in range(n):
        a, b, c = P[loop[(k - 1) % n]], P[loop[k]], P[loop[(k + 1) % n]]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) > 1e-12 * max(1.0, np.abs(P).max()) ** 2:
            keep.append(loop[k])
    return np.array(keep + keep[:1])


@bi('convhull', nout=2)
def convhull(nargout, *args):
    """[K, V] = convhull(x, y) or convhull(x, y, z): the convex hull (a closed
    loop of point indices counterclockwise in 2-D, triangles in 3-D) and its
    area or volume, by scipy.spatial.ConvexHull (Qhull); 'Simplify', false
    keeps the points on straight edges."""
    nargchk(args, 1, 5, 'convhull')
    from scipy.spatial import ConvexHull
    simplify, data, i = True, [], 0
    while i < len(args):
        if is_str(args[i]):
            if py_str(args[i]).lower() != 'simplify' or i + 1 >= len(args):
                raise err('MATLAB:convhull:InvalidOption', "The only option is 'Simplify'.", 'convhull')
            simplify = bool(num(args[i + 1]))
            i += 2
            continue
        data.append(args[i])
        i += 1
    P, _ = _points(data, 'convhull')
    try:
        h = ConvexHull(P, qhull_options='Qt' if simplify else 'Qt Qc')
    except Exception:
        raise err('MATLAB:convhull:EmptyConvhull2DErrId', 'The convex hull is empty: the points may be collinear or coincident.', 'convhull')
    if P.shape[1] == 2:
        loop = _hull_loop(P, h)
        if not simplify:
            # points on the hull's edges (Qhull's coplanar points) put in their places along it
            onedge = [int(c[0]) for c in getattr(h, 'coplanar', np.zeros((0, 3), int))]
            if onedge:
                ring = list(loop[:-1])
                for q in onedge:
                    for k in range(len(ring)):
                        a, b = P[ring[k]], P[ring[(k + 1) % len(ring)]]
                        if abs(np.cross(b - a, P[q] - a)) < 1e-12 and np.dot(P[q] - a, b - a) > 0 and np.dot(P[q] - b, a - b) > 0:
                            ring.insert(k + 1, q)
                            break
                loop = np.array(ring + ring[:1])
        else:
            loop = _collinear_free(P, loop)
        K = (loop.astype(F64) + 1).reshape(-1, 1)
        V = float(h.volume)
    else:
        K = h.simplices.astype(F64) + 1
        V = float(h.volume)
    return (out(K), V) if nargout > 1 else out(K)


@bi('voronoin', nout=2)
def voronoin(nargout, *args):
    """[V, C] = voronoin(X): the Voronoi vertices (the first row Inf, standing
    for the point at infinity) and each point's cell as indices into V, by
    scipy.spatial.Voronoi (Qhull)."""
    nargchk(args, 1, 2, 'voronoin')
    from scipy.spatial import Voronoi
    P = darr(args[0]).astype(F64)
    vor = Voronoi(P)
    V = np.vstack([np.full((1, P.shape[1]), np.inf), vor.vertices])
    cells = []
    for i in range(P.shape[0]):
        reg = vor.regions[vor.point_region[i]]
        cells.append(out(np.array([[1.0 if k < 0 else k + 2.0 for k in reg]])))
    C = Cell.of_list(cells, (len(cells), 1))
    return (out(V), C) if nargout > 1 else out(V)


def _voronoi_edges(P):
    """The finite Voronoi edges, and the unbounded ones cut at a distance past
    the points (as lines of two ends)."""
    from scipy.spatial import Voronoi
    vor = Voronoi(P)
    center = P.mean(axis=0)
    span = np.ptp(P, axis=0).max() or 1.0
    xs, ys = [], []
    for (p, q), rv in zip(vor.ridge_points, vor.ridge_vertices):
        rv = np.asarray(rv)
        if np.all(rv >= 0):
            a, b = vor.vertices[rv[0]], vor.vertices[rv[1]]
        else:
            i = rv[rv >= 0][0]
            t = P[q] - P[p]
            t = t / np.linalg.norm(t)
            n = np.array([-t[1], t[0]])
            mid = P[[p, q]].mean(axis=0)
            far = vor.vertices[i] + np.sign(np.dot(mid - center, n)) * n * span * 2
            a, b = vor.vertices[i], far
        xs.append([a[0], b[0]])
        ys.append([a[1], b[1]])
    return np.array(xs).T, np.array(ys).T


@bi('voronoi', nout=2, arr=False)
def voronoi(nargout, *args):
    """voronoi(x, y) draws the Voronoi diagram of the points; [vx, vy] =
    voronoi(x, y) gives its edges (a column of two ends each, the unbounded
    ones cut past the points) instead."""
    nargchk(args, 2, 4, 'voronoi')
    P, _ = _points(args[:2], 'voronoi', dims=(2,))
    vx, vy = _voronoi_edges(P)
    if nargout >= 2:
        return out(vx), out(vy)
    spec = [a for a in args[2:] if is_str(a)]
    plot = R.BUILTINS['plot'].fn
    hs = plot(1, out(P[:, 0].reshape(-1, 1)), out(P[:, 1].reshape(-1, 1)), Char.of('.'),
              out(vx), out(vy), spec[0] if spec else Char.of('-'))
    return hs if nargout else None


# ---- searching -------------------------------------------------------------------------------------------

@bi('tsearchn', nout=2)
def tsearchn(nargout, *args):
    """[t, p] = tsearchn(X, T, XI): the simplex of T enclosing each point of XI
    (NaN outside) and its barycentric coordinates there."""
    nargchk(args, 3, 3, 'tsearchn')
    X = darr(args[0]).astype(F64)
    T = darr(args[1]).astype(np.intp) - 1
    Q = darr(args[2]).astype(F64)
    d = X.shape[1]
    t = np.full(Q.shape[0], np.nan)
    p = np.full((Q.shape[0], d + 1), np.nan)
    for s, tri in enumerate(T):
        V = X[tri]
        A = np.vstack([V.T, np.ones(d + 1)])
        try:
            Ai = np.linalg.inv(A)
        except np.linalg.LinAlgError:
            continue
        lam = (Ai @ np.vstack([Q.T, np.ones(Q.shape[0])])).T
        inside = np.all(lam >= -1e-12, axis=1) & np.isnan(t)
        t[inside] = s + 1
        p[inside] = lam[inside]
    return (out(t.reshape(-1, 1)), out(p)) if nargout > 1 else out(t.reshape(-1, 1))


@bi('dsearchn', nout=2)
def dsearchn(nargout, *args):
    """[k, d] = dsearchn(X, XI): the index of the point of X nearest each point
    of XI (scipy.spatial.cKDTree) and the distance; dsearchn(X, T, XI,
    outval) gives outval for points outside the convex hull."""
    nargchk(args, 2, 4, 'dsearchn')
    from scipy.spatial import cKDTree, Delaunay
    X = darr(args[0]).astype(F64)
    if X.ndim == 2 and X.shape[1] == 1 and X.shape[0] > 1 and darr(args[-1]).ndim == 2 and darr(args[-1]).shape[1] == 1:
        pass
    Q = darr(args[2] if len(args) > 2 else args[1]).astype(F64)
    if Q.ndim == 2 and Q.shape[1] != X.shape[1] and Q.size == X.shape[1]:
        Q = Q.reshape(1, -1)
    dist, idx = cKDTree(X).query(Q)
    k = idx.astype(F64) + 1
    if len(args) > 3:
        outside = Delaunay(X).find_simplex(Q) < 0
        k = np.where(outside, float(num(args[3])), k)
    return (out(k.reshape(-1, 1)), out(dist.reshape(-1, 1))) if nargout > 1 else out(k.reshape(-1, 1))


@bi('rectint')
def rectint(nargout, *args):
    """The areas where the rectangles [x y width height] of A (rows) and of B
    overlap: an m-by-n matrix."""
    nargchk(args, 2, 2, 'rectint')
    A, B = darr(args[0]).astype(F64), darr(args[1]).astype(F64)
    A = A.reshape(1, -1) if A.ndim == 2 and A.shape[0] == 1 or A.ndim == 1 else A
    B = B.reshape(1, -1) if B.ndim == 2 and B.shape[0] == 1 or B.ndim == 1 else B
    if A.shape[1] != B.shape[1] or A.shape[1] % 2:
        raise err('MATLAB:rectint:InvalidInput', 'Each rectangle is a row of positions and sizes, [x y width height], both of one length.', 'rectint')
    d = A.shape[1] // 2
    r = np.ones((A.shape[0], B.shape[0]))
    for k in range(d):
        lo = np.maximum(A[:, None, k], B[None, :, k])
        hi = np.minimum(A[:, None, k] + A[:, None, d + k], B[None, :, k] + B[None, :, d + k])
        r = r * np.maximum(0, hi - lo)
    return out(r)


# ---- interpolation ------------------------------------------------------------------------------------------

@bi('interp3')
def interp3(nargout, *args):
    """Vq = interp3(X, Y, Z, V, Xq, Yq, Zq, method, extrapval), or interp3(V,
    Xq, Yq, Zq) on the grid 1:n: interpn with the grids in meshgrid's order
    (y down the rows, x across, z through the pages)."""
    nargchk(args, 4, 9, 'interp3')
    rest = list(args)
    tail = []
    while rest and (is_str(rest[-1]) or (len(rest) in (5, 9) and numel(rest[-1]) == 1 and not is_str(rest[-1]))):
        tail.insert(0, rest.pop())
        if len(tail) >= 2:
            break
    interpn = R.BUILTINS['interpn'].fn
    if len(rest) == 4:
        V, xq, yq, zq = rest
        Va = darr(V)
        ny, nx = Va.shape[0], Va.shape[1]
        nz = Va.shape[2] if Va.ndim > 2 else 1
        X, Y, Z = (out(np.arange(1, n + 1, dtype=F64)) for n in (nx, ny, nz))
    elif len(rest) == 7:
        X, Y, Z, V, xq, yq, zq = rest
        Xa, Ya, Za = darr(X), darr(Y), darr(Z)
        if Xa.ndim == 3:
            X, Y, Z = out(Xa[0, :, 0]), out(Ya[:, 0, 0]), out(Za[0, 0, :])
    else:
        raise err('MATLAB:interp3:nargin', 'interp3 takes V and the query points, or X, Y, Z, V and the query points.', 'interp3')
    return interpn(1, Y, X, Z, V, yq, xq, zq, *tail)


_GI_METHODS = ('linear', 'nearest', 'next', 'previous', 'pchip', 'cubic', 'spline', 'makima')


class GriddedInterpolant(Obj):
    """griddedInterpolant: values on a grid, evaluated at any points by
    F(xq) (or F({x1q, x2q}) on a grid of them)."""
    __slots__ = ('grid', 'values', 'method', 'extrap')
    cls = 'griddedInterpolant'
    is_handle = True

    def __init__(self, grid, values, method, extrap):
        self.grid, self.values, self.method, self.extrap = grid, values, method, extrap

    def getprop(self, name):
        if name == 'GridVectors':
            return Cell.of_list([out(g.reshape(1, -1)) for g in self.grid])
        if name == 'Values':
            return out(self.values)
        if name == 'Method':
            return Char.of(self.method)
        if name == 'ExtrapolationMethod':
            return Char.of(self.extrap)
        return super().getprop(name)

    def setprop(self, name, value):
        if name == 'Values':
            v = np.asarray(arr(value)).astype(F64)
            if v.shape[:len(self.grid)] != tuple(g.size for g in self.grid) and v.size != np.prod([g.size for g in self.grid]):
                raise err('MATLAB:griddedInterpolant:BadValues', 'The values must match the grid.')
            self.values = v.reshape(tuple(g.size for g in self.grid), order='F')
        elif name == 'Method':
            m = py_str(value).lower()
            if m not in _GI_METHODS:
                raise err('MATLAB:griddedInterpolant:BadMethod', f"Unknown method '{m}'.")
            self.method = m
        elif name == 'ExtrapolationMethod':
            m = py_str(value).lower()
            if m not in _GI_METHODS + ('none',):
                raise err('MATLAB:griddedInterpolant:BadMethod', f"Unknown method '{m}'.")
            self.extrap = m
        else:
            return super().setprop(name, value)
        return self

    def propnames(self):
        return ['GridVectors', 'Values', 'Method', 'ExtrapolationMethod']

    def display_lines(self):
        return ['  griddedInterpolant with properties:', '',
                '            GridVectors: {' + ' '.join(f'[1×{g.size} double]' for g in self.grid) + '}',
                '                 Values: [' + '×'.join(str(s) for s in self.values.shape) + ' double]',
                f"                 Method: '{self.method}'",
                f"    ExtrapolationMethod: '{self.extrap}'"]

    def index(self, args):
        d = len(self.grid)
        if len(args) == 1 and isinstance(args[0], Cell):
            vecs = [darr(x).reshape(-1) for x in args[0].a.reshape(-1, order='F')]
            mesh = np.meshgrid(*vecs, indexing='ij')
            pts = [m.reshape(-1, order='F') for m in mesh]
            shape = tuple(v.size for v in vecs)
        elif len(args) == 1 and d > 1:
            Q = darr(args[0])
            pts = [Q[:, k] for k in range(d)]
            shape = (Q.shape[0], 1)
        else:
            qs = [darr(a) for a in args]
            shape = qs[0].shape
            pts = [q.reshape(-1, order='F') for q in qs]
        return out(self.evaluate(pts).reshape(shape, order='F'))

    def evaluate(self, pts):
        """Inside the grid by interp1 or interpn (the language's methods);
        outside by the extrapolation method."""
        d = len(self.grid)
        npts = pts[0].size
        if d == 1:
            interp1 = R.BUILTINS['interp1'].fn
            m = self.method
            ex = self.extrap
            if ex == 'none':
                r = interp1(1, out(self.grid[0]), out(self.values.reshape(-1)), out(pts[0]), Char.of(m))
            elif ex == m or ex in ('linear', 'nearest', 'pchip', 'spline', 'makima', 'cubic', 'previous', 'next'):
                inside = np.asarray(arr(interp1(1, out(self.grid[0]), out(self.values.reshape(-1)), out(pts[0]), Char.of(m))), F64).reshape(-1)
                outr = np.asarray(arr(interp1(1, out(self.grid[0]), out(self.values.reshape(-1)), out(pts[0]), Char.of(ex), Char.of('extrap'))), F64).reshape(-1)
                g = self.grid[0]
                r = np.where((pts[0] >= g[0]) & (pts[0] <= g[-1]), inside, outr)
            return np.asarray(arr(r), F64).reshape(-1)
        interpn = R.BUILTINS['interpn'].fn
        m = self.method if self.method not in ('next', 'previous') else 'nearest'
        r = np.asarray(arr(interpn(1, *[out(g) for g in self.grid], out(self.values), *[out(p) for p in pts], Char.of(m))), F64).reshape(-1)
        outside = np.zeros(npts, bool)
        for g, p in zip(self.grid, pts):
            outside |= (p < g[0]) | (p > g[-1])
        if outside.any() and self.extrap != 'none':
            from scipy.interpolate import RegularGridInterpolator
            sm = {'linear': 'linear', 'nearest': 'nearest', 'pchip': 'pchip', 'spline': 'cubic', 'cubic': 'cubic', 'makima': 'cubic',
                  'next': 'nearest', 'previous': 'nearest'}[self.extrap]
            if sm in ('cubic', 'pchip') and any(g.size < 4 for g in self.grid):
                sm = 'linear'
            f = RegularGridInterpolator(tuple(self.grid), self.values, method=sm, bounds_error=False, fill_value=None)
            Q = np.column_stack([p[outside] for p in pts])
            r[outside] = f(Q)
        elif outside.any():
            r[outside] = np.nan
        return r


@bi('griddedInterpolant', arr=False)
def gridded_interpolant(nargout, *args):
    """F = griddedInterpolant(x1, x2, ..., V, method, extrapolation), or
    griddedInterpolant({x1, x2, ...}, V, ...), or griddedInterpolant(X1,
    X2, ..., V) with full grids (ndgrid's); F(xq1, xq2, ...) evaluates."""
    rest = list(args)
    strs = []
    while rest and is_str(rest[-1]):
        strs.insert(0, py_str(rest.pop()).lower())
    method = strs[0] if strs else 'linear'
    extrap = strs[1] if len(strs) > 1 else method
    if method not in _GI_METHODS or extrap not in _GI_METHODS + ('none',):
        raise err('MATLAB:griddedInterpolant:BadMethod', f"Unknown method '{method if method not in _GI_METHODS else extrap}'.", 'griddedInterpolant')
    if not rest:
        raise err('MATLAB:griddedInterpolant:NoValues', 'Give the values (and the grid).', 'griddedInterpolant')
    if len(rest) == 2 and isinstance(rest[0], Cell):
        grid = [darr(g).reshape(-1).astype(F64) for g in rest[0].a.reshape(-1, order='F')]
        V = darr(rest[1]).astype(F64)
    elif len(rest) == 1:
        V = darr(rest[0]).astype(F64)
        if V.ndim == 2 and 1 in V.shape:
            V = V.reshape(-1)
        grid = [np.arange(1, n + 1, dtype=F64) for n in V.shape]
    else:
        V = darr(rest[-1]).astype(F64)
        gs = [darr(g) for g in rest[:-1]]
        if len(gs) == 1:
            V = V.reshape(-1)
            grid = [gs[0].reshape(-1).astype(F64)]
        elif all(g.shape == V.shape for g in gs) and V.ndim >= 2:
            grid = [np.moveaxis(g, k, 0)[(slice(None),) + (0,) * (g.ndim - 1)].astype(F64) for k, g in enumerate(gs)]
        else:
            grid = [g.reshape(-1).astype(F64) for g in gs]
    shape = tuple(g.size for g in grid)
    if V.size != np.prod(shape):
        raise err('MATLAB:griddedInterpolant:GridValuesMismatch', 'The values must have one element per grid point.', 'griddedInterpolant')
    V = V.reshape(shape, order='F') if V.shape != shape else V
    for g in grid:
        if g.size > 1 and np.any(np.diff(g) <= 0):
            raise err('MATLAB:griddedInterpolant:NonMonotonicCompVecsErrId', 'The grid vectors must be strictly increasing.', 'griddedInterpolant')
    return GriddedInterpolant(grid, V, method, extrap)


class ScatteredInterpolant(Obj):
    """scatteredInterpolant: values at scattered points, evaluated anywhere by
    F(xq, yq) or F(Q)."""
    __slots__ = ('points', 'values', 'method', 'extrap', '_tri')
    cls = 'scatteredInterpolant'
    is_handle = True

    def __init__(self, points, values, method, extrap):
        self.points, self.values, self.method, self.extrap = points, values, method, extrap
        self._tri = None

    def tri(self):
        if self._tri is None:
            from scipy.spatial import Delaunay
            self._tri = Delaunay(self.points)
        return self._tri

    def getprop(self, name):
        if name == 'Points':
            return out(self.points)
        if name == 'Values':
            return out(self.values.reshape(-1, 1))
        if name == 'Method':
            return Char.of(self.method)
        if name == 'ExtrapolationMethod':
            return Char.of(self.extrap)
        return super().getprop(name)

    def setprop(self, name, value):
        if name == 'Values':
            v = darr(value).reshape(-1).astype(F64)
            if v.size != self.points.shape[0]:
                raise err('MATLAB:scatteredInterpolant:BadValues', 'There must be one value per point.')
            self.values = v
        elif name == 'Method':
            m = py_str(value).lower()
            if m not in ('linear', 'nearest', 'natural'):
                raise err('MATLAB:scatteredInterpolant:BadMethod', f"Unknown method '{m}'.")
            self.method = m
        elif name == 'ExtrapolationMethod':
            m = py_str(value).lower()
            if m not in ('linear', 'nearest', 'none'):
                raise err('MATLAB:scatteredInterpolant:BadMethod', f"Unknown method '{m}'.")
            self.extrap = m
        elif name == 'Points':
            P = darr(value).astype(F64)
            self.points = P
            self._tri = None
        else:
            return super().setprop(name, value)
        return self

    def propnames(self):
        return ['Points', 'Values', 'Method', 'ExtrapolationMethod']

    def display_lines(self):
        n, d = self.points.shape
        return ['  scatteredInterpolant with properties:', '',
                f'                 Points: [{n}×{d} double]',
                f'                 Values: [{n}×1 double]',
                f"                 Method: '{self.method}'",
                f"    ExtrapolationMethod: '{self.extrap}'"]

    def index(self, args):
        d = self.points.shape[1]
        if len(args) == 1:
            Q = darr(args[0]).astype(F64)
            shape = (Q.shape[0], 1)
            pts = Q
        else:
            qs = [darr(a).astype(F64) for a in args[:d]]
            shape = qs[0].shape
            pts = np.column_stack([q.reshape(-1, order='F') for q in qs])
        return out(self.evaluate(pts).reshape(shape, order='F'))

    def evaluate(self, Q):
        from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
        near = NearestNDInterpolator(self.points, self.values)
        if self.method == 'nearest':
            r = near(Q)
        else:
            # 'natural' is computed as 'linear' here (SciPy has no natural neighbours)
            r = LinearNDInterpolator(self.tri(), self.values)(Q)
        outside = self.tri().find_simplex(Q) < 0
        if outside.any():
            if self.extrap == 'none':
                r[outside] = np.nan
            elif self.extrap == 'nearest':
                r[outside] = near(Q[outside])
            else:
                r[outside] = self._extrapolate(Q[outside])
        return np.asarray(r, F64)

    def _extrapolate(self, Q):
        """Linear extrapolation: the plane through the triangle (simplex) of the
        hull nearest each point, extended to it."""
        tri = self.tri()
        P, v = self.points, self.values
        hull_simplices = np.unique(np.where(tri.neighbors < 0)[0])
        res = np.empty(Q.shape[0])
        cents = P[tri.simplices[hull_simplices]].mean(axis=1)
        for i, q in enumerate(Q):
            s = hull_simplices[np.argmin(np.linalg.norm(cents - q, axis=1))]
            idx = tri.simplices[s]
            A = np.column_stack([P[idx], np.ones(len(idx))])
            coef = np.linalg.lstsq(A, v[idx], rcond=None)[0]
            res[i] = coef[:-1] @ q + coef[-1]
        return res


@bi('scatteredInterpolant', arr=False)
def scattered_interpolant(nargout, *args):
    """F = scatteredInterpolant(x, y, v, method, extrapolation) or
    scatteredInterpolant(P, v, ...): F(xq, yq) interpolates over the
    Delaunay triangulation of the points."""
    rest = list(args)
    strs = []
    while rest and is_str(rest[-1]):
        strs.insert(0, py_str(rest.pop()).lower())
    method = strs[0] if strs else 'linear'
    extrap = strs[1] if len(strs) > 1 else ('nearest' if method == 'nearest' else 'linear')
    if method not in ('linear', 'nearest', 'natural') or extrap not in ('linear', 'nearest', 'none'):
        raise err('MATLAB:scatteredInterpolant:BadMethod', 'The method is linear, nearest or natural; the extrapolation linear, nearest or none.', 'scatteredInterpolant')
    if not rest:
        return ScatteredInterpolant(np.zeros((0, 2)), np.zeros(0), method, extrap)
    if len(rest) == 2:
        P = darr(rest[0]).astype(F64)
        v = darr(rest[1]).reshape(-1).astype(F64)
    else:
        P = np.column_stack([darr(a).reshape(-1, order='F').astype(F64) for a in rest[:-1]])
        v = darr(rest[-1]).reshape(-1, order='F').astype(F64)
    if P.shape[0] != v.size:
        raise err('MATLAB:scatteredInterpolant:InputSizeMismatch', 'There must be one value per point.', 'scatteredInterpolant')
    return ScatteredInterpolant(P, v, method, extrap)


# ---- triangle plots ---------------------------------------------------------------------------------------

def _tri_args(args, fn, need_z):
    from .graphics import split_axes_arg
    ax, rest = split_axes_arg(args)
    T = darr(rest[0]).astype(np.intp) - 1
    k = 4 if need_z else 3
    if len(rest) < k - (0 if need_z else 0):
        raise err(f'MATLAB:{fn}:nargin', 'Give the triangles and the coordinates.', fn)
    x = darr(rest[1]).reshape(-1).astype(F64)
    y = darr(rest[2]).reshape(-1).astype(F64)
    z = darr(rest[3]).reshape(-1).astype(F64) if need_z and len(rest) > 3 and not is_str(rest[3]) else None
    tail = rest[(4 if z is not None else 3):]
    return ax, T, x, y, z, tail


@bi('triplot', arr=False)
def triplot(nargout, *args):
    """triplot(TRI, x, y, spec): the edges of the triangles, as one line with
    breaks."""
    nargchk(args, 3, None, 'triplot')
    ax, T, x, y, _, tail = _tri_args(args, 'triplot', False)
    xs, ys = [], []
    for t in T:
        loop = list(t) + [t[0]]
        xs += [x[i] for i in loop] + [np.nan]
        ys += [y[i] for i in loop] + [np.nan]
    pre = (ax,) if ax is not None else ()
    h = R.BUILTINS['plot'].fn(1, *pre, out(np.array(xs).reshape(-1, 1)), out(np.array(ys).reshape(-1, 1)), *tail)
    return h if nargout else None


def _trisurface(nargout, args, fn, mesh):
    from .graphics import newplot, gca_
    ax, T, x, y, z, tail = _tri_args(args, fn, True)
    if z is None:
        raise err(f'MATLAB:{fn}:nargin', 'Give the triangles and x, y and z.', fn)
    c = None
    if tail and not is_str(tail[0]):
        c = darr(tail.pop(0)).reshape(-1).astype(F64)
    ax = newplot(ax)
    V = np.column_stack([x, y, z])
    props = [Char.of('Faces'), out(T.astype(F64) + 1), Char.of('Vertices'), out(V),
             Char.of('FaceVertexCData'), out((c if c is not None else z).reshape(-1, 1))]
    if mesh:
        props += [Char.of('FaceColor'), Char.of('w'), Char.of('EdgeColor'), Char.of('flat')]
    else:
        props += [Char.of('FaceColor'), Char.of('flat'), Char.of('EdgeColor'), Char.of('k')]
    h = R.BUILTINS['patch'].fn(1, ax, *props, *tail)
    R.BUILTINS['view'].fn(0, ax, 3.0)
    return h if nargout else None


@bi('trisurf', arr=False)
def trisurf(nargout, *args):
    """trisurf(TRI, x, y, z, c): the triangles as a surface coloured by z (or c)."""
    nargchk(args, 4, None, 'trisurf')
    return _trisurface(nargout, args, 'trisurf', False)


@bi('trimesh', arr=False)
def trimesh(nargout, *args):
    """trimesh(TRI, x, y, z, c): the triangles as a mesh, white faces, edges coloured by z (or c)."""
    nargchk(args, 4, None, 'trimesh')
    return _trisurface(nargout, args, 'trimesh', True)
