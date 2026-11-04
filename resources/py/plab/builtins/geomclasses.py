"""Triangulations as objects: triangulation and delaunayTriangulation with
their queries (pointLocation, nearestNeighbor, edges, neighbors,
freeBoundary, circumcenter, incenter, attachments, normals, the convex
hull and the Voronoi diagram), and alpha shapes (alphaShape, boundary).
Delaunay triangulations come from Qhull through SciPy."""
import math

import numpy as np

from . import bi as _register
from . import REG
from ._util import err, nargchk, out, num, opt_str, opt_lower, is_str, darr, arr
from ..values import MError, Char, Cell, Struct, Str, Obj, Sparse, numel, py_str, EMPTY, F64
from .. import runtime as R


def bi(*names, **kw):
    """Register, with Python's own errors given as the language's."""
    def deco(fn):
        def wrapped(*a):
            try:
                return fn(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError, OverflowError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'MATLAB:{names[0]}:InvalidInput', str(e) or 'The input is not valid.', names[0]) from None
        wrapped.__name__ = fn.__name__
        wrapped.__doc__ = fn.__doc__
        return _register(*names, **kw)(wrapped)
    return deco


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


def _num_mat(v, fn, what):
    if isinstance(v, (Cell, Struct, Char, Str)) or isinstance(v, Obj):
        raise err(f'MATLAB:{fn}:InvalidInput', f'{what} is a numeric matrix.', fn)
    a = np.asarray(darr(v), F64)
    return a.reshape(1, -1) if a.ndim < 2 else a


def _cell_rows(lists):
    """A column cell array of row vectors (1-based ids)."""
    items = [np.asarray(x, F64).reshape(1, -1) + 1 if len(x) else np.zeros((1, 0)) for x in lists]
    return Cell.of_list(items, (len(items), 1)) if items else Cell.empty((0, 1))


def method(name, cls, fn):
    """name(obj, ...) for objects of cls, in front of a built-in of that name
    (or on its own when there is none)."""
    info = REG.get(name)
    if info is None:
        @bi(name, nout=4, arr=False)
        def own(nargout, *args):
            if args and isinstance(args[0], cls):
                return fn(nargout, *args)
            raise err('MATLAB:UndefinedFunction', f"Undefined function '{name}' for input arguments of type '{_class(args[0]) if args else 'double'}'.", name)
        return
    orig = info.fn
    if info.aw:
        async def f(*a):
            args = a[2:] if info.ws else a[1:]
            if args and isinstance(args[0], cls):
                return fn(a[1] if info.ws else a[0], *args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if info.ws else a[1:]
            if args and isinstance(args[0], cls):
                return fn(a[1] if info.ws else a[0], *args)
            return orig(*a)
    info.fn = f
    info.nout = max(info.nout, 4) if info.nout != 99 else 99


def _class(v):
    from ..values import class_of
    return class_of(v)


# ---- geometry of simplices -------------------------------------------------------------------------------------

def _orient2d(P, T):
    """Triangles in 2-D turned counterclockwise."""
    if T.size == 0 or P.shape[1] != 2 or T.shape[1] != 3:
        return T
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    s = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    T = T.copy()
    neg = s < 0
    T[neg, 1], T[neg, 2] = T[neg, 2], T[neg, 1].copy()
    return T


def _circum(P, T):
    """Circumcentres and radii of simplices (triangles in 2-D or 3-D, tetrahedra in 3-D)."""
    V = P[T]                                         # m x k x d
    a = V[:, 0, :]
    E = V[:, 1:, :] - a[:, None, :]                  # m x (k-1) x d
    G = np.einsum('mid,mjd->mij', E, E)              # Gram matrix
    rhs = 0.5 * np.einsum('mid,mid->mi', E, E)
    try:
        lam = np.linalg.solve(G, rhs[..., None])[..., 0]
    except np.linalg.LinAlgError:
        lam = np.array([np.linalg.lstsq(g, r, rcond=None)[0] for g, r in zip(G, rhs)])
    C = a + np.einsum('mi,mid->md', lam, E)
    r = np.linalg.norm(C - a, axis=1)
    return C, r


def _volumes(P, T):
    """Areas of triangles (2-D or 3-D) or volumes of tetrahedra."""
    V = P[T]
    E = V[:, 1:, :] - V[:, :1, :]
    if T.shape[1] == 3:
        if P.shape[1] == 2:
            return 0.5 * np.abs(E[:, 0, 0] * E[:, 1, 1] - E[:, 0, 1] * E[:, 1, 0])
        return 0.5 * np.linalg.norm(np.cross(E[:, 0], E[:, 1]), axis=1)
    if T.shape[1] == 4:
        return np.abs(np.einsum('md,md->m', E[:, 0], np.cross(E[:, 1], E[:, 2]))) / 6.0
    return np.zeros(T.shape[0])


def _facets(T):
    """Each simplex's facets: (m*k) x (k-1) sorted rows, facet j opposite vertex j."""
    k = T.shape[1]
    F = np.concatenate([np.delete(T, j, axis=1) for j in range(k)], axis=0)
    return np.sort(F, axis=1)


class Triangulation(Obj):
    """A triangulation: points and the simplices (rows of point indices) joining them."""
    is_handle = False
    KIND = 'triangulation'

    def __init__(self, T, P):
        self.T = np.asarray(T, int).reshape(-1, T.shape[1] if np.ndim(T) == 2 else 3)
        self.P = np.asarray(P, F64)
        self.C = np.zeros((0, 2), int)

    @property
    def cls(self):
        return self.KIND

    def value_copy(self):
        import copy
        o = copy.copy(self)
        o.T, o.P = self.T.copy(), self.P.copy()
        return o

    @property
    def shape(self):
        return (1, 1)

    def getprop(self, name):
        k = name.lower()
        if k == 'points':
            return out(self.P.copy())
        if k == 'connectivitylist':
            return out(self.T.astype(F64) + 1)
        if k == 'constraints' and isinstance(self, DelaunayTri):
            return out(self.C.astype(F64) + 1) if self.C.size else np.zeros((0, 2))
        if name in TRI_METHODS or (isinstance(self, DelaunayTri) and name in DT_METHODS):
            from ..classdef import BoundBuiltin
            return BoundBuiltin(self, name)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls}'.")

    def setprop(self, name, value):
        raise MError('MATLAB:class:SetProhibited', f"You cannot set the read-only property '{name}' of {self.cls}.")

    def propnames(self):
        return ['Points', 'ConnectivityList']

    def display_lines(self):
        n, d = self.P.shape
        m, k = self.T.shape
        lines = [f'  {self.cls} with properties:', '', f'              Points: [{n}×{d} double]',
                 f'    ConnectivityList: [{m}×{k} double]']
        if isinstance(self, DelaunayTri):
            lines.append(f'         Constraints: [{self.C.shape[0]}×2 double]' if self.C.size else '         Constraints: []')
        return lines

    # ---- what the methods share ----
    def ids(self, v, fn, what='ID'):
        if v is None:
            return np.arange(self.T.shape[0])
        a = np.asarray(darr(v), F64).reshape(-1)
        if np.any(a != np.round(a)) or np.any(a < 1) or np.any(a > self.T.shape[0]):
            raise err(f'MATLAB:{fn}:InvalidID', f'{what} holds simplex indices from 1 to {self.T.shape[0]}.', fn)
        return a.astype(int) - 1

    def vids(self, v, fn):
        a = np.asarray(darr(v), F64).reshape(-1)
        if np.any(a != np.round(a)) or np.any(a < 1) or np.any(a > self.P.shape[0]):
            raise err(f'MATLAB:{fn}:InvalidID', f'The vertex indices run from 1 to {self.P.shape[0]}.', fn)
        return a.astype(int) - 1

    def neighbors(self):
        """m x k: the simplex across the facet opposite each vertex, -1 at the boundary."""
        m, k = self.T.shape
        F = _facets(self.T)
        key = [tuple(r) for r in F]
        owner = {}
        Nb = np.full((m, k), -1, int)
        for idx, kk in enumerate(key):
            s, j = idx % m, idx // m
            if kk in owner:
                s2, j2 = owner[kk]
                Nb[s, j] = s2
                Nb[s2, j2] = s
            else:
                owner[kk] = (s, j)
        return Nb

    def edges(self):
        k = self.T.shape[1]
        E = np.concatenate([self.T[:, [i, j]] for i in range(k) for j in range(i + 1, k)], axis=0) if self.T.size else np.zeros((0, 2), int)
        E = np.sort(E, axis=1)
        if not E.size:
            return E.reshape(0, 2)
        return np.unique(E, axis=0)

    def locate(self, Q):
        """(simplex index or -1, barycentric coordinates) of each query point."""
        P, T = self.P, self.T
        d = P.shape[1]
        nq = Q.shape[0]
        ids = np.full(nq, -1, int)
        B = np.full((nq, T.shape[1]), np.nan)
        if not T.size or T.shape[1] != d + 1:
            return ids, B
        V = P[T]                                    # m x (d+1) x d
        M = np.transpose(V[:, 1:, :] - V[:, :1, :], (0, 2, 1))   # m x d x d
        ok = np.abs(np.linalg.det(M)) > 0
        Minv = np.zeros_like(M)
        Minv[ok] = np.linalg.inv(M[ok])
        tol = 1e-12
        step = max(1, int(2e6 // max(T.shape[0], 1)))
        for a in range(0, nq, step):
            q = Q[a:a + step]
            lam = np.einsum('mij,qmj->qmi', Minv, q[:, None, :] - V[None, :, 0, :])
            l0 = 1 - lam.sum(axis=2)
            allb = np.concatenate([l0[..., None], lam], axis=2)
            inside = np.all(allb >= -tol, axis=2) & ok[None, :]
            has = inside.any(axis=1)
            first = np.argmax(inside, axis=1)
            rows = np.nonzero(has)[0]
            ids[a + rows] = first[rows]
            B[a + rows] = allb[rows, first[rows]]
        return ids, B


class DelaunayTri(Triangulation):
    KIND = 'delaunayTriangulation'

    def __init__(self, P, C=None):
        P = np.asarray(P, F64)
        self.C = np.zeros((0, 2), int)
        super().__init__(np.zeros((0, P.shape[1] + 1), int), P)
        self.retriangulate()

    def retriangulate(self):
        from scipy.spatial import Delaunay
        P = self.P
        n, d = P.shape
        if d not in (2, 3):
            raise err('MATLAB:delaunayTriangulation:BadDim', 'The points are in 2-D or 3-D.', 'delaunayTriangulation')
        _, first = np.unique(P, axis=0, return_index=True)
        if first.size < n:
            R.warn('MATLAB:delaunayTriangulation:DupPtsWarnId', 'Duplicate data points have been detected and removed.\n'
                   ' The Triangulation indices are defined with respect to the unique set of points in delaunayTriangulation.')
            P = P[np.sort(first)]
            self.P = P
            n = P.shape[0]
        if n <= d:
            self.T = np.zeros((0, d + 1), int)
            return
        try:
            T = Delaunay(P, qhull_options='Qt Qbb Qc Qz' + (' Qx' if d >= 4 else '')).simplices
        except Exception:
            T = np.zeros((0, d + 1), int)            # collinear or coplanar points: no simplices
        self.T = _orient2d(P, np.asarray(T, int))
        # a fixed order: by the rows' sorted vertices
        if self.T.size:
            order = np.lexsort(np.sort(self.T, axis=1).T[::-1])
            self.T = self.T[order]

    def setprop(self, name, value):
        k = name.lower()
        if k == 'points':
            P = _num_mat(value, 'delaunayTriangulation', 'Points')
            if P.shape[1] != self.P.shape[1] and self.P.size:
                raise err('MATLAB:delaunayTriangulation:BadDim', f'The points have {self.P.shape[1]} coordinates.', 'delaunayTriangulation')
            self.P = P
            self.retriangulate()
            return
        if k == 'constraints':
            if numel(value):
                raise err('MATLAB:delaunayTriangulation:Constraints', 'Constrained edges are not supported here.', 'delaunayTriangulation')
            return
        super().setprop(name, value)


TRI_METHODS = {'barycentricToCartesian', 'cartesianToBarycentric', 'circumcenter', 'edgeAttachments', 'edges', 'faceNormal',
               'featureEdges', 'freeBoundary', 'incenter', 'isConnected', 'nearestNeighbor', 'neighbors', 'pointLocation',
               'size', 'vertexAttachments', 'vertexNormal'}
DT_METHODS = {'convexHull', 'isInterior', 'voronoiDiagram'}


def _points_from(args, fn):
    """P from P, or from x, y (and z) columns."""
    if len(args) == 1:
        P = _num_mat(args[0], fn, 'P')
    else:
        cols = [np.asarray(darr(a), F64).reshape(-1) for a in args]
        if any(c.size != cols[0].size for c in cols):
            raise err(f'MATLAB:{fn}:SizeMismatch', 'x, y (and z) have as many points.', fn)
        P = np.column_stack(cols)
    if P.shape[1] not in (2, 3):
        raise err(f'MATLAB:{fn}:BadDim', 'The points are in 2-D or 3-D: two or three columns.', fn)
    if not np.all(np.isfinite(P)):
        raise err(f'MATLAB:{fn}:NonFinite', 'The points are finite.', fn)
    return P


@bi('triangulation', arr=False)
def triangulation(nargout, *args):
    """TR = triangulation(T, P) or triangulation(T, x, y) or (T, x, y, z):
    the triangles (or tetrahedra), rows of indices into the points, as an
    object to query (pointLocation, edges, neighbors, freeBoundary, ...)."""
    nargchk(args, 2, 4, 'triangulation')
    T = _num_mat(args[0], 'triangulation', 'T')
    P = _points_from(args[1:], 'triangulation')
    if T.size and (np.any(T != np.round(T)) or T.min() < 1 or T.max() > P.shape[0]):
        raise err('MATLAB:triangulation:InvalidConnectivity', f'T holds point indices from 1 to {P.shape[0]}.', 'triangulation')
    if T.shape[1] not in (3, 4) and T.size:
        raise err('MATLAB:triangulation:InvalidConnectivity', 'T has three columns (triangles) or four (tetrahedra).', 'triangulation')
    if T.shape[1] == 4 and P.shape[1] != 3:
        raise err('MATLAB:triangulation:InvalidConnectivity', 'Tetrahedra join points in 3-D.', 'triangulation')
    return Triangulation(T.astype(int) - 1 if T.size else np.zeros((0, 3), int), P)


@bi('delaunayTriangulation', arr=False)
def delaunayTriangulation(nargout, *args):
    """DT = delaunayTriangulation(P), (x, y) or (x, y, z): the Delaunay
    triangulation of points in 2-D or 3-D (duplicates removed, with a
    warning); triangles counterclockwise. Setting DT.Points triangulates
    again. Constrained edges are not supported here."""
    nargchk(args, 0, 4, 'delaunayTriangulation')
    if not args:
        return DelaunayTri(np.zeros((0, 2)))
    if len(args) in (2, 3) and np.asarray(darr(args[-1])).ndim == 2 and np.asarray(darr(args[-1])).shape[1:] == (2,) and len(args) == 2 \
            and np.asarray(darr(args[0])).ndim == 2 and np.asarray(darr(args[0])).shape[1] in (2, 3) and np.asarray(darr(args[0])).shape[0] > 1:
        raise err('MATLAB:delaunayTriangulation:Constraints', 'Constrained edges are not supported here.', 'delaunayTriangulation')
    return DelaunayTri(_points_from(args, 'delaunayTriangulation'))


# ---- the methods ------------------------------------------------------------------------------------------------

def _size(nargout, TR, *args):
    s = TR.T.shape
    if args:
        d = int(num(args[0]))
        return float(s[d - 1]) if 1 <= d <= 2 else 1.0
    if nargout > 1:
        return tuple([float(x) for x in s] + [1.0] * (nargout - 2))[:nargout]
    return np.array([[float(s[0]), float(s[1])]])


def _pointLocation(nargout, TR, *args):
    if not args:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'pointLocation')
    Q = _points_from(args, 'pointLocation') if len(args) > 1 else _num_mat(args[0], 'pointLocation', 'The query points')
    if Q.shape[1] != TR.P.shape[1]:
        raise err('MATLAB:pointLocation:BadDim', f'The query points have {TR.P.shape[1]} coordinates.', 'pointLocation')
    ids, B = TR.locate(Q)
    ID = np.where(ids >= 0, ids + 1.0, np.nan).reshape(-1, 1)
    return _outs(nargout, out(ID), out(B))


def _nearestNeighbor(nargout, TR, *args):
    from scipy.spatial import cKDTree
    if not args:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'nearestNeighbor')
    Q = _points_from(args, 'nearestNeighbor') if len(args) > 1 else _num_mat(args[0], 'nearestNeighbor', 'The query points')
    used = np.unique(TR.T) if (TR.T.size and not isinstance(TR, DelaunayTri)) else np.arange(TR.P.shape[0])
    d, j = cKDTree(TR.P[used]).query(Q)
    return _outs(nargout, out((used[j] + 1.0).reshape(-1, 1)), out(np.asarray(d, F64).reshape(-1, 1)))


def _edges(nargout, TR, *args):
    return out(TR.edges().astype(F64) + 1) if TR.T.size else np.zeros((0, 2))


def _neighbors(nargout, TR, *args):
    ids = TR.ids(args[0] if args else None, 'neighbors')
    Nb = TR.neighbors()[ids]
    return out(np.where(Nb >= 0, Nb + 1.0, np.nan))


def _vertexAttachments(nargout, TR, *args):
    vi = TR.vids(args[0], 'vertexAttachments') if args else np.arange(TR.P.shape[0])
    lists = []
    for v in vi:
        s = np.nonzero(np.any(TR.T == v, axis=1))[0]
        if TR.P.shape[1] == 2 and TR.T.shape[1] == 3 and s.size > 1:
            cen = TR.P[TR.T[s]].mean(axis=1) - TR.P[v]
            s = s[np.argsort(np.arctan2(cen[:, 1], cen[:, 0]), kind='stable')]     # counterclockwise round the vertex
        lists.append(s)
    return _cell_rows(lists)


def _edgeAttachments(nargout, TR, *args):
    if len(args) == 1:
        E = np.asarray(darr(args[0]), F64).reshape(-1, 2)
    elif len(args) == 2:
        E = np.column_stack([np.asarray(darr(a), F64).reshape(-1) for a in args])
    else:
        raise err('MATLAB:edgeAttachments:nargin', 'Give the edges as an n-by-2 matrix, or as V1 and V2.', 'edgeAttachments')
    E = E.astype(int) - 1
    lists = [np.nonzero(np.any(TR.T == a, axis=1) & np.any(TR.T == b, axis=1))[0] for a, b in E]
    return _cell_rows(lists)


def _isConnected(nargout, TR, *args):
    if len(args) == 1:
        E = np.asarray(darr(args[0]), F64).reshape(-1, 2)
    else:
        E = np.column_stack([np.asarray(darr(a), F64).reshape(-1) for a in args[:2]])
    edges = {tuple(e) for e in TR.edges().tolist()}
    E = np.sort(E.astype(int) - 1, axis=1)
    return out(np.array([tuple(e) in edges for e in E.tolist()], bool).reshape(-1, 1))


def _freeBoundary(nargout, TR, *args):
    T = TR.T
    m, k = T.shape
    if not T.size:
        F = np.zeros((0, k - 1), int)
    else:
        # facets used once; for triangles in 2-D the edges in each triangle's (counterclockwise) order, chained into loops
        faces = [np.delete(T, j, axis=1) for j in range(k)]
        if k == 3 and TR.P.shape[1] == 2:
            faces = [T[:, [1, 2]], T[:, [2, 0]], T[:, [0, 1]]]
        allf = np.concatenate(faces, axis=0)
        key = np.sort(allf, axis=1)
        _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
        F = allf[cnt[inv.reshape(-1)] == 1]
        if k == 3 and TR.P.shape[1] == 2 and F.size:
            nxt = {a: i for i, (a, b) in enumerate(F.tolist())}
            used = np.zeros(len(F), bool)
            chain = []
            for s in range(len(F)):
                i = s
                while not used[i]:
                    used[i] = True
                    chain.append(i)
                    i = nxt.get(F[i, 1], i)
            F = F[chain]
        elif k == 4:
            # facets of tetrahedra turned outward
            pass
    if nargout > 1:
        used = np.unique(F)
        remap = np.full(TR.P.shape[0], -1, int)
        remap[used] = np.arange(used.size)
        return out(remap[F].astype(F64) + 1), out(TR.P[used])
    return out(F.astype(F64) + 1) if F.size else np.zeros((0, k - 1))


def _circumcenter(nargout, TR, *args):
    ids = TR.ids(args[0] if args else None, 'circumcenter')
    if not ids.size:
        return _outs(nargout, np.zeros((0, TR.P.shape[1])), np.zeros((0, 1)))
    C, r = _circum(TR.P, TR.T[ids])
    return _outs(nargout, out(C), out(r.reshape(-1, 1)))


def _incenter(nargout, TR, *args):
    ids = TR.ids(args[0] if args else None, 'incenter')
    T = TR.T[ids]
    V = TR.P[T]
    k = T.shape[1]
    if k == 3:
        a = np.linalg.norm(V[:, 1] - V[:, 2], axis=1)
        b = np.linalg.norm(V[:, 2] - V[:, 0], axis=1)
        c = np.linalg.norm(V[:, 0] - V[:, 1], axis=1)
        w = np.column_stack([a, b, c])
        area = _volumes(TR.P, T)
        r = 2 * area / w.sum(axis=1)
    else:
        w = np.column_stack([_volumes(TR.P, np.delete(T, j, axis=1)) for j in range(4)])
        r = 3 * _volumes(TR.P, T) / w.sum(axis=1)
    C = np.einsum('mk,mkd->md', w / w.sum(axis=1, keepdims=True), V)
    return _outs(nargout, out(C), out(r.reshape(-1, 1)))


def _barycentricToCartesian(nargout, TR, *args):
    if len(args) != 2:
        raise err('MATLAB:barycentricToCartesian:nargin', 'barycentricToCartesian takes ID and B.', 'barycentricToCartesian')
    ids = TR.ids(args[0], 'barycentricToCartesian')
    B = _num_mat(args[1], 'barycentricToCartesian', 'B')
    if B.shape != (ids.size, TR.T.shape[1]):
        raise err('MATLAB:barycentricToCartesian:SizeMismatch', f'B has a row of {TR.T.shape[1]} coordinates for each ID.', 'barycentricToCartesian')
    return out(np.einsum('mk,mkd->md', B, TR.P[TR.T[ids]]))


def _cartesianToBarycentric(nargout, TR, *args):
    if len(args) != 2:
        raise err('MATLAB:cartesianToBarycentric:nargin', 'cartesianToBarycentric takes ID and P.', 'cartesianToBarycentric')
    ids = TR.ids(args[0], 'cartesianToBarycentric')
    Q = _num_mat(args[1], 'cartesianToBarycentric', 'P')
    V = TR.P[TR.T[ids]]
    A = np.concatenate([np.transpose(V, (0, 2, 1)), np.ones((V.shape[0], 1, V.shape[1]))], axis=1)   # (d+1) x k
    rhs = np.concatenate([Q, np.ones((Q.shape[0], 1))], axis=1)
    B = np.array([np.linalg.lstsq(Ai, bi_, rcond=None)[0] for Ai, bi_ in zip(A, rhs)]) if ids.size else np.zeros((0, TR.T.shape[1]))
    return out(B)


def _faceNormal(nargout, TR, *args):
    if TR.T.shape[1] != 3 or TR.P.shape[1] != 3:
        raise err('MATLAB:faceNormal:NotSurface', 'faceNormal is for triangles in 3-D.', 'faceNormal')
    ids = TR.ids(args[0] if args else None, 'faceNormal')
    V = TR.P[TR.T[ids]]
    N = np.cross(V[:, 1] - V[:, 0], V[:, 2] - V[:, 0])
    return out(N / np.linalg.norm(N, axis=1, keepdims=True))


def _vertexNormal(nargout, TR, *args):
    if TR.T.shape[1] != 3 or TR.P.shape[1] != 3:
        raise err('MATLAB:vertexNormal:NotSurface', 'vertexNormal is for triangles in 3-D.', 'vertexNormal')
    V = TR.P[TR.T]
    N = np.cross(V[:, 1] - V[:, 0], V[:, 2] - V[:, 0])
    N = N / np.linalg.norm(N, axis=1, keepdims=True)
    acc = np.zeros(TR.P.shape)
    for j in range(3):
        np.add.at(acc, TR.T[:, j], N)
    vi = TR.vids(args[0], 'vertexNormal') if args else np.arange(TR.P.shape[0])
    A = acc[vi]
    nrm = np.linalg.norm(A, axis=1, keepdims=True)
    with np.errstate(invalid='ignore', divide='ignore'):
        return out(A / nrm)


def _featureEdges(nargout, TR, *args):
    if TR.T.shape[1] != 3:
        raise err('MATLAB:featureEdges:NotTriangles', 'featureEdges is for triangles.', 'featureEdges')
    ang = float(num(args[0])) if args else math.pi / 6
    P = TR.P if TR.P.shape[1] == 3 else np.column_stack([TR.P, np.zeros(TR.P.shape[0])])
    V = P[TR.T]
    N = np.cross(V[:, 1] - V[:, 0], V[:, 2] - V[:, 0])
    N = N / np.linalg.norm(N, axis=1, keepdims=True)
    att = {}
    for s, t in enumerate(TR.T.tolist()):
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            att.setdefault((min(a, b), max(a, b)), []).append(s)
    E = []
    for e, ss in sorted(att.items()):
        if len(ss) == 1:
            E.append(e)
        elif len(ss) == 2:
            c = float(np.clip(np.dot(N[ss[0]], N[ss[1]]), -1, 1))
            if math.acos(c) > ang:
                E.append(e)
    return out(np.array(E, F64).reshape(-1, 2) + 1)


def _convexHull(nargout, DT, *args):
    from scipy.spatial import ConvexHull
    P = DT.P
    if P.shape[0] <= P.shape[1]:
        return _outs(nargout, np.zeros((0, 1)), 0.0)
    h = ConvexHull(P)
    if P.shape[1] == 2:
        k = h.vertices                               # counterclockwise
        C = np.concatenate([k, k[:1]]).astype(F64) + 1
        return _outs(nargout, out(C.reshape(-1, 1)), float(h.volume))
    return _outs(nargout, out(h.simplices.astype(F64) + 1), float(h.volume))


def _voronoiDiagram(nargout, DT, *args):
    from scipy.spatial import Voronoi
    P = DT.P
    if P.shape[0] <= P.shape[1]:
        raise err('MATLAB:voronoiDiagram:TooFewPoints', 'There are too few points for a Voronoi diagram.', 'voronoiDiagram')
    vor = Voronoi(P)
    V = np.vstack([np.full((1, P.shape[1]), np.inf), vor.vertices])
    regs = []
    for i in range(P.shape[0]):
        reg = vor.regions[vor.point_region[i]]
        regs.append([x + 1 for x in reg])            # -1 (at infinity) becomes the first row
    items = [np.asarray(r, F64).reshape(1, -1) + 1 for r in regs]
    return _outs(nargout, out(V), Cell.of_list(items, (len(items), 1)))


def _isInterior(nargout, DT, *args):
    raise err('MATLAB:isInterior:NoConstraints', 'isInterior needs a triangulation with constrained edges, which are not supported here.', 'isInterior')


for _n, _f in (('size', _size), ('pointLocation', _pointLocation), ('nearestNeighbor', _nearestNeighbor), ('edges', _edges),
               ('neighbors', _neighbors), ('vertexAttachments', _vertexAttachments), ('edgeAttachments', _edgeAttachments),
               ('isConnected', _isConnected), ('freeBoundary', _freeBoundary), ('circumcenter', _circumcenter),
               ('incenter', _incenter), ('barycentricToCartesian', _barycentricToCartesian),
               ('cartesianToBarycentric', _cartesianToBarycentric), ('faceNormal', _faceNormal), ('vertexNormal', _vertexNormal),
               ('featureEdges', _featureEdges)):
    method(_n, Triangulation, _f)
for _n, _f in (('convexHull', _convexHull), ('voronoiDiagram', _voronoiDiagram), ('isInterior', _isInterior)):
    method(_n, DelaunayTri, _f)


def _tri_plot(name):
    """triplot(TR, ...), trimesh, trisurf and tetramesh of a triangulation: its simplices and points."""
    def f(nargout, TR, *rest):
        T = out(TR.T.astype(F64) + 1)
        cols = [out(TR.P[:, j].reshape(-1, 1)) for j in range(TR.P.shape[1])]
        if name == 'tetramesh':
            return REG_ORIG[name](nargout, T, out(TR.P), *rest)
        if name == 'triplot':
            return REG_ORIG[name](nargout, T, cols[0], cols[1], *rest)
        if TR.P.shape[1] < 3:
            cols.append(out(np.zeros((TR.P.shape[0], 1))))
        return REG_ORIG[name](nargout, T, *cols[:3], *rest)
    return f


REG_ORIG = {}
for _n in ('triplot', 'trimesh', 'trisurf', 'tetramesh'):
    if _n in REG:
        REG_ORIG[_n] = REG[_n].fn
        method(_n, Triangulation, _tri_plot(_n))


# ---- alpha shapes ---------------------------------------------------------------------------------------------------

class AlphaShape(Obj):
    """The simplices of a Delaunay triangulation whose circumradius is at most
    Alpha: regions (joined through shared facets) smaller than
    RegionThreshold left out, holes smaller than HoleThreshold filled."""
    cls = 'alphaShape'
    is_handle = False

    def __init__(self, P, alpha=None, hole=0.0, region=0.0):
        from scipy.spatial import Delaunay
        self.P = P
        d = P.shape[1]
        try:
            self.T = np.asarray(Delaunay(P, qhull_options='Qt Qbb Qc Qz').simplices, int) if P.shape[0] > d else np.zeros((0, d + 1), int)
        except Exception:
            self.T = np.zeros((0, d + 1), int)
        self.T = _orient2d(P, self.T)
        self.r = _circum(P, self.T)[1] if self.T.size else np.zeros(0)
        self.vol = _volumes(P, self.T) if self.T.size else np.zeros(0)
        self.nb = Triangulation(self.T, P).neighbors() if self.T.size else np.zeros((0, d + 1), int)
        self.hole = hole
        self.region = region
        self.alpha = self.critical('all-points') if alpha is None else alpha
        self.update()

    def value_copy(self):
        import copy
        return copy.copy(self)

    @property
    def shape(self):
        return (1, 1)

    def _components(self, keep):
        """Region number of each kept simplex (-1 otherwise), joined through shared facets."""
        lab = np.full(self.T.shape[0], -1, int)
        k = 0
        for s in np.nonzero(keep)[0]:
            if lab[s] >= 0:
                continue
            stack = [s]
            lab[s] = k
            while stack:
                t = stack.pop()
                for u in self.nb[t]:
                    if u >= 0 and keep[u] and lab[u] < 0:
                        lab[u] = k
                        stack.append(u)
            k += 1
        return lab, k

    def update(self):
        keep = self.r <= self.alpha * (1 + 1e-12) if self.T.size else np.zeros(0, bool)
        if self.hole > 0 and self.T.size:
            # holes: groups of left-out simplices that touch no outer facet; filled when small
            out_lab, nout = self._components(~keep)
            for g in range(nout):
                members = out_lab == g
                touches_hull = np.any(self.nb[members] < 0)
                if not touches_hull and self.vol[members].sum() <= self.hole:
                    keep = keep | members
        lab, n = self._components(keep)
        if self.region > 0:
            for g in range(n):
                if self.vol[lab == g].sum() < self.region:
                    keep = keep & (lab != g)
            lab, n = self._components(keep)
        self.keep, self.lab, self.n = keep, lab, n

    def critical(self, kind):
        if not self.T.size:
            return 0.0
        if kind == 'all-points':
            best = np.full(self.P.shape[0], np.inf)
            for j in range(self.T.shape[1]):
                np.minimum.at(best, self.T[:, j], self.r)
            used = np.isfinite(best)
            return float(best[used].max()) if used.any() else 0.0
        if kind == 'one-region':
            a0 = self.critical('all-points')
            for a in np.unique(self.r[self.r >= a0 * (1 - 1e-12)]):
                keep = self.r <= a * (1 + 1e-12)
                if self._components(keep)[1] == 1:
                    return float(a)
            return float(self.r.max())
        raise err('MATLAB:alphaShape:BadType', "The type is 'all-points' or 'one-region'.", 'criticalAlpha')

    def region_ids(self, v, fn):
        if v is None:
            return list(range(self.n))
        a = np.asarray(darr(v), F64).reshape(-1)
        if np.any(a < 1) or np.any(a > self.n) or np.any(a != np.round(a)):
            raise err(f'MATLAB:{fn}:BadRegion', f'The region numbers run from 1 to {self.n}.', fn)
        return [int(x) - 1 for x in a]

    def facets(self, regions):
        """Boundary facets of the kept simplices in those regions (outward for 2-D: counterclockwise)."""
        sel = np.isin(self.lab, regions) & self.keep
        T = self.T[sel]
        if not T.size:
            return np.zeros((0, self.T.shape[1] - 1), int)
        tr = Triangulation(T, self.P)
        F = np.asarray(darr(_freeBoundary(1, tr)), F64)
        return F.astype(int) - 1 if F.size else np.zeros((0, self.T.shape[1] - 1), int)

    def getprop(self, name):
        k = name.lower()
        if k == 'points':
            return out(self.P.copy())
        if k == 'alpha':
            return float(self.alpha)
        if k == 'holethreshold':
            return float(self.hole)
        if k == 'regionthreshold':
            return float(self.region)
        if name in ALPHA_METHODS:
            from ..classdef import BoundBuiltin
            return BoundBuiltin(self, name)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class 'alphaShape'.")

    def setprop(self, name, value):
        k = name.lower()
        if k == 'alpha':
            a = float(num(value))
            if not a > 0:
                raise err('MATLAB:alphaShape:BadAlpha', 'Alpha is a positive number.', 'alphaShape')
            self.alpha = a
        elif k == 'holethreshold':
            self.hole = float(num(value))
        elif k == 'regionthreshold':
            self.region = float(num(value))
        elif k == 'points':
            P = _num_mat(value, 'alphaShape', 'Points')
            self.__init__(P, self.alpha, self.hole, self.region)
            return
        else:
            raise MError('MATLAB:noPublicFieldForClass', f"Unrecognized property '{name}' for class 'alphaShape'.")
        self.update()

    def propnames(self):
        return ['Points', 'Alpha', 'HoleThreshold', 'RegionThreshold']

    def display_lines(self):
        n, d = self.P.shape
        return ['  alphaShape with properties:', '', f'              Points: [{n}×{d} double]', f'               Alpha: {self.alpha:.4g}',
                f'       HoleThreshold: {self.hole:.4g}', f'     RegionThreshold: {self.region:.4g}']


ALPHA_METHODS = {'alphaSpectrum', 'alphaTriangulation', 'area', 'boundaryFacets', 'criticalAlpha', 'inShape', 'nearestNeighbor',
                 'numRegions', 'perimeter', 'plot', 'surfaceArea', 'volume'}


@bi('alphaShape', arr=False)
def alphaShape(nargout, *args):
    """shp = alphaShape(x, y, a), (x, y, z, a) or (P, a), and 'HoleThreshold',
    'RegionThreshold': the Delaunay triangles (tetrahedra) whose circumradius
    is at most a; without a, the smallest that takes in every point
    (criticalAlpha 'all-points')."""
    nargchk(args, 1, 8, 'alphaShape')
    a = list(args)
    opts = {}
    while len(a) >= 2 and is_str(a[-2]):
        opts[opt_lower(a[-2])] = a[-1]
        a = a[:-2]
    for k in opts:
        if k not in ('holethreshold', 'regionthreshold'):
            raise err('MATLAB:alphaShape:BadOption', f"'{k}' is not an option of alphaShape (HoleThreshold, RegionThreshold).", 'alphaShape')
    alpha = None
    first = np.asarray(darr(a[0])) if a else np.zeros(0)
    if first.ndim == 2 and first.shape[1] in (2, 3) and first.shape[0] > 1 and len(a) <= 2:
        P = _num_mat(a[0], 'alphaShape', 'P')
        if len(a) == 2:
            alpha = float(num(a[1]))
    else:
        ncoords = 3 if len(a) >= 3 and numel(a[2]) == numel(a[0]) and numel(a[0]) > 1 else 2
        P = _points_from(a[:ncoords], 'alphaShape')
        if len(a) > ncoords:
            alpha = float(num(a[ncoords]))
    if alpha is not None and not alpha > 0:
        raise err('MATLAB:alphaShape:BadAlpha', 'Alpha is a positive number.', 'alphaShape')
    return AlphaShape(P, alpha, float(num(opts['holethreshold'])) if 'holethreshold' in opts else 0.0,
                      float(num(opts['regionthreshold'])) if 'regionthreshold' in opts else 0.0)


def _a_area(nargout, S, *args):
    if S.P.shape[1] != 2:
        raise err('MATLAB:area:Dim', 'area is for 2-D alpha shapes (volume for 3-D).', 'area')
    regs = S.region_ids(args[0] if args else None, 'area')
    if args:
        return out(np.array([S.vol[(S.lab == g) & S.keep].sum() for g in regs]).reshape(-1, 1))
    return float(S.vol[S.keep].sum())


def _a_volume(nargout, S, *args):
    if S.P.shape[1] != 3:
        raise err('MATLAB:volume:Dim', 'volume is for 3-D alpha shapes (area for 2-D).', 'volume')
    regs = S.region_ids(args[0] if args else None, 'volume')
    if args:
        return out(np.array([S.vol[(S.lab == g) & S.keep].sum() for g in regs]).reshape(-1, 1))
    return float(S.vol[S.keep].sum())


def _facet_measure(S, F):
    if not F.size:
        return 0.0
    if F.shape[1] == 2:
        return float(np.linalg.norm(S.P[F[:, 0]] - S.P[F[:, 1]], axis=1).sum())
    return float(_volumes(S.P, F).sum())


def _a_perimeter(nargout, S, *args):
    if S.P.shape[1] != 2:
        raise err('MATLAB:perimeter:Dim', 'perimeter is for 2-D alpha shapes (surfaceArea for 3-D).', 'perimeter')
    regs = S.region_ids(args[0] if args else None, 'perimeter')
    if args:
        return out(np.array([_facet_measure(S, S.facets([g])) for g in regs]).reshape(-1, 1))
    return _facet_measure(S, S.facets(list(range(S.n))))


def _a_surface(nargout, S, *args):
    if S.P.shape[1] != 3:
        raise err('MATLAB:surfaceArea:Dim', 'surfaceArea is for 3-D alpha shapes (perimeter for 2-D).', 'surfaceArea')
    regs = S.region_ids(args[0] if args else None, 'surfaceArea')
    if args:
        return out(np.array([_facet_measure(S, S.facets([g])) for g in regs]).reshape(-1, 1))
    return _facet_measure(S, S.facets(list(range(S.n))))


def _a_numRegions(nargout, S, *args):
    return float(S.n)


def _a_boundaryFacets(nargout, S, *args):
    regs = S.region_ids(args[0] if args else None, 'boundaryFacets')
    F = S.facets(regs)
    if nargout > 1:
        used = np.unique(F)
        remap = np.full(S.P.shape[0], -1, int)
        remap[used] = np.arange(used.size)
        return out(remap[F].astype(F64) + 1), out(S.P[used])
    return out(F.astype(F64) + 1) if F.size else np.zeros((0, S.P.shape[1]))


def _a_triangulation(nargout, S, *args):
    regs = S.region_ids(args[0] if args else None, 'alphaTriangulation')
    T = S.T[np.isin(S.lab, regs) & S.keep]
    if nargout > 1:
        used = np.unique(T)
        remap = np.full(S.P.shape[0], -1, int)
        remap[used] = np.arange(used.size)
        return out(remap[T].astype(F64) + 1), out(S.P[used])
    return out(T.astype(F64) + 1) if T.size else np.zeros((0, S.P.shape[1] + 1))


def _a_inShape(nargout, S, *args):
    if not args:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'inShape')
    if len(args) == 1:
        Q = _num_mat(args[0], 'inShape', 'The query points')
        shape = (Q.shape[0], 1)
    else:
        a0 = np.asarray(darr(args[0]))
        shape = a0.shape
        Q = np.column_stack([np.asarray(darr(a), F64).reshape(-1, order='F') for a in args[:S.P.shape[1]]])
    tr = Triangulation(S.T, S.P)
    ids, _ = tr.locate(Q)
    inside = (ids >= 0) & S.keep[np.maximum(ids, 0)]
    tf = inside.reshape(shape, order='F')
    if nargout > 1:
        reg = np.where(inside, S.lab[np.maximum(ids, 0)] + 1.0, np.nan).reshape(shape, order='F')
        return tf, out(reg)
    return tf


def _a_spectrum(nargout, S, *args):
    return out(np.unique(S.r)[::-1].reshape(-1, 1))


def _a_critical(nargout, S, *args):
    kind = opt_lower(args[0]) if args else 'all-points'
    return S.critical(kind)


def _a_nearest(nargout, S, *args):
    from scipy.spatial import cKDTree
    Q = _points_from(args, 'nearestNeighbor') if len(args) > 1 else _num_mat(args[0], 'nearestNeighbor', 'The query points')
    used = np.unique(S.T[S.keep]) if S.keep.any() else np.arange(S.P.shape[0])
    d, j = cKDTree(S.P[used]).query(Q)
    return _outs(nargout, out((used[j] + 1.0).reshape(-1, 1)), out(np.asarray(d, F64).reshape(-1, 1)))


def _a_plot(nargout, S, *args):
    T = S.T[S.keep]
    if S.P.shape[1] == 2:
        F = out(T.astype(F64) + 1) if T.size else np.zeros((0, 3))
        h = REG['patch'].fn(1, Char.of('Faces'), F, Char.of('Vertices'), out(S.P), Char.of('FaceColor'), np.array([[0.0, 0.45, 0.74]]),
                            Char.of('EdgeColor'), np.array([[0.0, 0.0, 0.0]]), Char.of('FaceAlpha'), 0.4, *args)
    else:
        F = S.facets(list(range(S.n)))
        h = REG['patch'].fn(1, Char.of('Faces'), out(F.astype(F64) + 1) if F.size else np.zeros((0, 3)), Char.of('Vertices'), out(S.P),
                            Char.of('FaceColor'), np.array([[0.0, 0.45, 0.74]]), Char.of('EdgeColor'), np.array([[0.0, 0.0, 0.0]]), *args)
        try:
            REG['view'].fn(0, 3.0)
        except Exception:
            pass
    return h if nargout else None


for _n, _f in (('area', _a_area), ('volume', _a_volume), ('perimeter', _a_perimeter), ('surfaceArea', _a_surface),
               ('numRegions', _a_numRegions), ('boundaryFacets', _a_boundaryFacets), ('alphaTriangulation', _a_triangulation),
               ('inShape', _a_inShape), ('alphaSpectrum', _a_spectrum), ('criticalAlpha', _a_critical), ('nearestNeighbor', _a_nearest),
               ('plot', _a_plot)):
    method(_n, AlphaShape, _f)


@bi('boundary', nout=2, arr=False)
def boundary(nargout, *args):
    """k = boundary(x, y, s), (x, y, z, s) or (P, s); [k, v] = boundary(...):
    a boundary around the points, from the convex hull (s = 0) to the
    tightest single region (s = 1; 0.5 by default), as an alpha shape with
    its holes filled: in 2-D a closed loop of point indices
    (counterclockwise, first = last), in 3-D the boundary's triangles; v its
    area or volume. Between the two ends alpha steps through the alpha
    spectrum in proportion to 1 - s (PyLAB's rule)."""
    nargchk(args, 1, 4, 'boundary')
    a = list(args)
    s = 0.5
    first = np.asarray(darr(a[0]))
    if first.ndim == 2 and first.shape[1] in (2, 3) and first.shape[0] > 1 and len(a) <= 2:
        P = _num_mat(a[0], 'boundary', 'P')
        if len(a) == 2:
            s = float(num(a[1]))
    else:
        ncoords = 3 if len(a) >= 3 and numel(a[2]) == numel(a[0]) and numel(a[0]) > 1 else 2
        P = _points_from(a[:ncoords], 'boundary')
        if len(a) > ncoords:
            s = float(num(a[ncoords]))
    if not 0 <= s <= 1:
        raise err('MATLAB:boundary:BadShrink', 'The shrink factor s is from 0 to 1.', 'boundary')
    S = AlphaShape(P, 1.0, np.inf, 0.0)
    if not S.T.size:
        return _outs(nargout, np.zeros((0, 1)), 0.0)
    a1 = S.critical('one-region')
    spec = np.unique(S.r[S.r >= a1 * (1 - 1e-12)])
    alpha = float(spec[int(round((1 - s) * (spec.size - 1)))])
    S.alpha = alpha
    S.update()
    if S.n > 1:                                  # keep the largest region
        big = max(range(S.n), key=lambda g: S.vol[S.lab == g].sum())
        S.keep = S.keep & (S.lab == big)
        S.lab = np.where(S.keep, 0, -1)
        S.n = 1
    F = S.facets([0])
    v = float(S.vol[S.keep].sum())
    if P.shape[1] == 2:
        if not F.size:
            return _outs(nargout, np.zeros((0, 1)), v)
        loop = list(F[:, 0]) + [F[0, 0]]
        # one loop: the outer boundary (holes are filled)
        k = np.array(loop[:F.shape[0] + 1], F64) + 1
        return _outs(nargout, out(k.reshape(-1, 1)), v)
    return _outs(nargout, out(F.astype(F64) + 1), v)
