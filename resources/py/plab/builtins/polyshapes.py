"""polyshape: 2-D polygons with holes and several regions, their
measures, queries and changes, Boolean operations (union, intersect,
subtract, xor), buffers, triangulation and plots. The geometry is
Shapely's (GEOS), loaded in the page by the first polyshape or
nsidedpoly. Solid boundaries run clockwise, holes counterclockwise; a
polyshape's boundaries are kept as rings, each without its closing
vertex, and Vertices lists them with a row of NaN between."""
import math

import numpy as np

from . import bi as _register
from . import REG
from ._util import err, nargchk, out, num, opt_str, opt_lower, is_str, darr, arr
from ..values import MError, Char, Cell, Struct, Str, Obj, numel, py_str, EMPTY, F64
from ..graphics_base import HArr
from .. import runtime as R


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


async def _shapely(fn):
    try:
        import shapely
        return shapely
    except ImportError:
        pass
    try:
        import pyodide_js
    except ImportError:
        raise err(f'MATLAB:{fn}:noShapely', 'polyshape needs the shapely package (pip install shapely).', fn)
    try:
        await pyodide_js.loadPackage('shapely')
    except Exception as e:
        raise err(f'MATLAB:{fn}:noShapely', f'Shapely, which works out polygons, could not be loaded ({e}).', fn)
    import shapely
    return shapely


def _sh():
    import shapely
    return shapely


# ---- the object ------------------------------------------------------------------------------------------------

def _signed_area(ring):
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


class PolyShape(Obj):
    """A polygon: boundaries (rings of vertices) and which are holes."""
    cls = 'polyshape'
    is_handle = False

    def __init__(self, rings=(), holes=(), simplified=True):
        self.rings = [np.asarray(r, F64).reshape(-1, 2) for r in rings]
        self.holes = [bool(h) for h in holes]
        self.simplified = simplified
        self._geom = None

    def value_copy(self):
        return self

    @property
    def shape(self):
        return (1, 1)

    # -- to and from Shapely --
    def geom(self):
        """The polygon as a Shapely (Multi)Polygon: solids less holes, or for an
        unsimplified one the rings combined even-odd."""
        if self._geom is not None:
            return self._geom
        shp = _sh()
        from shapely.geometry import Polygon, MultiPolygon
        if not self.rings:
            g = MultiPolygon()
        elif self.simplified:
            solids = [Polygon(r) for r, h in zip(self.rings, self.holes) if not h and len(r) >= 3]
            holes = [Polygon(r) for r, h in zip(self.rings, self.holes) if h and len(r) >= 3]
            g = shp.union_all([shp.make_valid(p) for p in solids]) if solids else MultiPolygon()
            if holes:
                g = shp.difference(g, shp.union_all([shp.make_valid(p) for p in holes]))
        else:
            g = _even_odd([r for r in self.rings if len(r) >= 3])
        self._geom = _areal(g)
        return self._geom

    @staticmethod
    def from_geom(g, keep_collinear=False):
        """A simplified polyshape from Shapely geometry: each region's outer
        boundary clockwise, then its holes counterclockwise."""
        from shapely.geometry.polygon import orient
        g = _areal(g)
        if not keep_collinear:
            g = _areal(_sh().simplify(g, 0.0)) if not g.is_empty else g
        rings, holes = [], []
        for poly in _polys(g):
            poly = orient(poly, sign=-1.0)
            rings.append(np.asarray(poly.exterior.coords)[:-1])
            holes.append(False)
            for hole in poly.interiors:
                rings.append(np.asarray(hole.coords)[:-1])
                holes.append(True)
        p = PolyShape(rings, holes, True)
        p._geom = g
        return p

    # -- properties --
    def vertices(self):
        if not self.rings:
            return np.zeros((0, 2))
        parts = []
        for i, r in enumerate(self.rings):
            if i:
                parts.append(np.full((1, 2), np.nan))
            parts.append(r)
        return np.vstack(parts)

    def regions_list(self):
        """The regions, in the order of their outer boundaries in Vertices (so sortregions shows in regions and in
        isinterior's region numbers), not the order the geometry library leaves them in."""
        polys = _polys(self.geom())
        if len(polys) < 2:
            return polys
        from shapely.geometry import Point

        def first(poly):
            for i, (r, h) in enumerate(zip(self.rings, self.holes)):
                if not h and len(r) and poly.distance(Point(r[0])) <= 1e-9 * (1 + float(np.max(np.abs(r[0])))):
                    return i
            return len(self.rings)
        return sorted(polys, key=first)

    def getprop(self, name):
        k = name.lower()
        if k == 'vertices':
            return out(self.vertices())
        if k == 'numregions':
            return float(len(self.regions_list()))
        if k == 'numholes':
            return float(sum(self.holes))
        if name in POLY_METHODS:
            from ..classdef import BoundBuiltin
            return BoundBuiltin(self, name)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class 'polyshape'.")

    def setprop(self, name, value):
        if name.lower() == 'vertices':
            V = np.asarray(darr(value), F64)
            if V.ndim != 2 or V.shape[1] != 2:
                raise err('MATLAB:polyshape:BadVertices', 'Vertices is an n-by-2 matrix (boundaries parted by rows of NaN).', 'polyshape')
            new = _build(_split_rows(V), True, 'auto', False, 'polyshape')
            self.rings, self.holes, self.simplified, self._geom = new.rings, new.holes, new.simplified, new._geom
            return
        raise MError('MATLAB:class:SetProhibited', f"You cannot set the read-only property '{name}' of polyshape.")

    def propnames(self):
        return ['Vertices', 'NumRegions', 'NumHoles']

    def display_lines(self):
        V = self.vertices()
        return ['  polyshape with properties:', '', f'      Vertices: [{V.shape[0]}×2 double]',
                f'    NumRegions: {len(self.regions_list())}', f'      NumHoles: {sum(self.holes)}']


def _areal(g):
    """Only the areal parts of a geometry, as a MultiPolygon."""
    from shapely.geometry import MultiPolygon, Polygon
    return MultiPolygon([p for p in _polys(g) if not p.is_empty and p.area > 0])


def _polys(g):
    from shapely.geometry import Polygon, MultiPolygon, GeometryCollection
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, (MultiPolygon, GeometryCollection)):
        out_ = []
        for x in g.geoms:
            out_ += _polys(x)
        return out_
    return []


def _even_odd(rings):
    shp = _sh()
    from shapely.geometry import Polygon, MultiPolygon
    g = MultiPolygon()
    for r in rings:
        g = shp.symmetric_difference(g, shp.make_valid(Polygon(r)))
    return g


def _split_rows(V):
    """Rings from rows of vertices parted by NaN rows (a repeated closing vertex dropped)."""
    rings, cur = [], []
    for row in V:
        if np.any(np.isnan(row)):
            if cur:
                rings.append(np.array(cur))
            cur = []
        else:
            cur.append(row)
    if cur:
        rings.append(np.array(cur))
    out_ = []
    for r in rings:
        if len(r) > 1 and np.all(r[0] == r[-1]):
            r = r[:-1]
        out_.append(r)
    return out_


def _needs_repair(rings):
    """Whether rings have repeated vertices, cross themselves or each other."""
    shp = _sh()
    from shapely.geometry import LinearRing
    lr = []
    for r in rings:
        if len(r) < 3:
            return True
        d = np.diff(np.vstack([r, r[:1]]), axis=0)
        if np.any(np.all(d == 0, axis=1)):
            return True
        ring = LinearRing(r)
        if not ring.is_simple:
            return True
        lr.append(ring)
    for i in range(len(lr)):
        for j in range(i + 1, len(lr)):
            if lr[i].intersects(lr[j]):
                return True
    return False


def _build(rings, simplify, orientation, keep_collinear, fn):
    shp = _sh()
    from shapely.geometry import Polygon
    rings = [r for r in rings if len(r)]
    if not simplify:
        holes = []
        for r in rings:
            a = _signed_area(r)
            holes.append(a > 0 if orientation != 'ccw' else a < 0)
        return PolyShape(rings, holes, False)
    if _needs_repair(rings):
        R.warn('MATLAB:polyshape:repairedBySimplify', 'Polyshape has duplicate vertices, intersections, or other inconsistencies that may produce '
               'inaccurate or unexpected results. Input data has been modified to create a well-defined polyshape.')
    good = [r for r in rings if len(r) >= 3]
    if orientation == 'auto':
        g = _even_odd(good)
    else:
        cw = [r for r in good if _signed_area(r) < 0]
        ccw = [r for r in good if _signed_area(r) > 0]
        solids, holes = (cw, ccw) if orientation == 'cw' else (ccw, cw)
        g = shp.union_all([shp.make_valid(Polygon(r)) for r in solids]) if solids else Polygon()
        if holes:
            g = shp.difference(g, shp.union_all([shp.make_valid(Polygon(r)) for r in holes]))
    p = PolyShape.from_geom(g, keep_collinear)
    # a ring that kept a given boundary's first vertex starts there, as given
    firsts = [r[0] for r in good]
    for i, ring in enumerate(p.rings):
        for f in firsts:
            hit = np.nonzero(np.all(ring == f, axis=1))[0]
            if hit.size:
                p.rings[i] = np.roll(ring, -int(hit[0]), axis=0)
                break
    return p


def _xy_rings(args, fn):
    """The rings of polyshape(x, y), polyshape(P) or polyshape({x1, x2}, {y1, y2})."""
    if len(args) == 1:
        a = args[0]
        if isinstance(a, Cell):
            raise err(f'MATLAB:{fn}:InvalidInput', 'Give the x and y coordinates, or an n-by-2 matrix.', fn)
        V = np.asarray(darr(a), F64)
        if V.ndim != 2 or V.shape[1] != 2:
            raise err(f'MATLAB:{fn}:InvalidInput', 'The vertices are an n-by-2 matrix.', fn)
        return _split_rows(V)
    x, y = args[0], args[1]
    if isinstance(x, Cell) or isinstance(y, Cell):
        if not (isinstance(x, Cell) and isinstance(y, Cell)) or x.a.size != y.a.size:
            raise err(f'MATLAB:{fn}:InvalidInput', 'x and y are cell arrays of as many vectors.', fn)
        rings = []
        for xi, yi in zip(x.a.reshape(-1, order='F'), y.a.reshape(-1, order='F')):
            xv, yv = np.asarray(darr(xi), F64).reshape(-1), np.asarray(darr(yi), F64).reshape(-1)
            if xv.size != yv.size:
                raise err(f'MATLAB:{fn}:SizeMismatch', 'Each x vector is as long as its y vector.', fn)
            rings += _split_rows(np.column_stack([xv, yv]))
        return rings
    xv, yv = np.asarray(darr(x), F64), np.asarray(darr(y), F64)
    if xv.shape != yv.shape and xv.size != yv.size:
        raise err(f'MATLAB:{fn}:SizeMismatch', 'x and y are the same size.', fn)
    if xv.ndim == 2 and min(xv.shape) > 1:
        # columns as boundaries
        return [r for j in range(xv.shape[1]) for r in _split_rows(np.column_stack([xv[:, j], yv[:, j]]))]
    return _split_rows(np.column_stack([xv.reshape(-1), yv.reshape(-1)]))


@bi('polyshape', aw=True, arr=False)
async def polyshape(nargout, *args):
    """pgon = polyshape(x, y), polyshape(P) or polyshape({x1, x2}, {y1, y2}):
    a polygon whose boundaries are given by their vertices (several parted by
    NaN, or in cells); boundaries inside others are holes. 'Simplify'
    (true) mends crossings and repeated vertices (with a warning) and puts
    solids clockwise and holes counterclockwise; 'SolidBoundaryOrientation'
    'cw' or 'ccw' says which are solid instead; 'KeepCollinearPoints'
    (false) keeps vertices on straight edges."""
    await _shapely('polyshape')
    if not args:
        return PolyShape()
    a = list(args)
    opts = {}
    while len(a) >= 2 and is_str(a[-2]) and (opt_lower(a[-2]) or '') in ('simplify', 'solidboundaryorientation', 'keepcollinearpoints'):
        opts[opt_lower(a[-2])] = a[-1]
        a = a[:-2]
    if len(a) > 2:
        raise err('MATLAB:polyshape:nargin', "polyshape takes x and y (or P), then 'Simplify', 'SolidBoundaryOrientation' and 'KeepCollinearPoints'.", 'polyshape')
    rings = _xy_rings(a, 'polyshape')
    simp = _tf(opts['simplify']) if 'simplify' in opts else True
    orient_ = opt_lower(opts['solidboundaryorientation']) if 'solidboundaryorientation' in opts else 'auto'
    if orient_ not in ('auto', 'cw', 'ccw'):
        raise err('MATLAB:polyshape:BadOrientation', "SolidBoundaryOrientation is 'auto', 'cw' or 'ccw'.", 'polyshape')
    keep = _tf(opts['keepcollinearpoints']) if 'keepcollinearpoints' in opts else False
    for r in rings:
        if not np.all(np.isfinite(r)):
            raise err('MATLAB:polyshape:NonFinite', 'The vertices are finite (NaN only parts boundaries).', 'polyshape')
    return _build(rings, simp, orient_, keep, 'polyshape')


def _tf(v):
    if is_str(v):
        return (opt_lower(v) or '') in ('on', 'true')
    return bool(np.all(np.asarray(darr(v)) != 0))


@bi('nsidedpoly', aw=True, arr=False)
async def nsidedpoly(nargout, *args):
    """pgon = nsidedpoly(n, 'Center', c, 'Radius', r) or 'SideLength', s: a
    regular polygon of n sides about c ([0 0]) with its vertices on a circle
    of radius r (1), its lowest side level."""
    await _shapely('nsidedpoly')
    nargchk(args, 1, 5, 'nsidedpoly')
    n = float(num(args[0]))
    if n < 3 or n != int(n):
        raise err('MATLAB:nsidedpoly:BadN', 'n is a whole number from 3.', 'nsidedpoly')
    n = int(n)
    rest = list(args[1:])
    c, r = np.zeros(2), 1.0
    for i in range(0, len(rest), 2):
        k = opt_lower(rest[i])
        if i + 1 >= len(rest) or k not in ('center', 'radius', 'sidelength'):
            raise err('MATLAB:nsidedpoly:BadOption', "nsidedpoly's options are Center, and Radius or SideLength.", 'nsidedpoly')
        v = rest[i + 1]
        if k == 'center':
            c = np.asarray(darr(v), F64).reshape(-1)[:2]
        elif k == 'radius':
            r = float(num(v))
        else:
            r = float(num(v)) / (2 * math.sin(math.pi / n))
    ang = -math.pi / 2 - math.pi / n - 2 * math.pi * np.arange(n) / n        # clockwise from the lower left
    ring = np.column_stack([c[0] + r * np.cos(ang), c[1] + r * np.sin(ang)])
    p = PolyShape([ring], [False], True)
    return p


# ---- arrays of polyshapes ----------------------------------------------------------------------------------------

def _items(v):
    """(list of PolyShape, shape) of a polyshape or an array of them."""
    if isinstance(v, PolyShape):
        return [v], (1, 1)
    if isinstance(v, HArr) and all(isinstance(x, PolyShape) for x in v.a.reshape(-1)):
        return list(v.a.reshape(-1, order='F')), v.a.shape
    raise err('MATLAB:polyshape:NotPolyshape', 'The input is a polyshape.', 'polyshape')


def _is_poly(v):
    return isinstance(v, PolyShape) or (isinstance(v, HArr) and v.a.size and all(isinstance(x, PolyShape) for x in v.a.reshape(-1)))


def _array(items, shape=None):
    if len(items) == 1 and (shape is None or shape == (1, 1)):
        return items[0]
    a = np.empty(shape or (len(items), 1), object)
    for i, x in enumerate(items):
        a.reshape(-1, order='F')[i] = x
    return HArr(a)


def _each(v, fn):
    items, shape = _items(v)
    vals = [fn(p) for p in items]
    if len(vals) == 1:
        return vals[0]
    return out(np.array(vals, F64).reshape(shape, order='F'))


def _bindex(p, v, fn):
    """Boundary indices (0-based) from I."""
    a = np.asarray(darr(v), F64).reshape(-1)
    if np.any(a != np.round(a)) or np.any(a < 1) or np.any(a > len(p.rings)):
        raise err(f'MATLAB:{fn}:BadIndex', f'The boundary indices run from 1 to {len(p.rings)}.', fn)
    return [int(x) - 1 for x in a]


def method(name, fn):
    info = REG.get(name)
    if info is None:
        @bi(name, nout=4, arr=False)
        def own(nargout, *args):
            if args and _is_poly(args[0]):
                return fn(nargout, *args)
            raise err('MATLAB:UndefinedFunction', f"Undefined function '{name}' for these inputs.", name)
        return
    orig = info.fn
    if info.aw:
        async def f(*a):
            args = a[2:] if info.ws else a[1:]
            if args and _is_poly(args[0]):
                return fn(a[1] if info.ws else a[0], *args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if info.ws else a[1:]
            if args and _is_poly(args[0]):
                return fn(a[1] if info.ws else a[0], *args)
            return orig(*a)
    info.fn = f
    if info.nout != 99:
        info.nout = max(info.nout, 4)


POLY_METHODS = set()


def pmethod(*names):
    def deco(fn):
        for n in names:
            POLY_METHODS.add(n)
            method(n, fn)
        return fn
    return deco


# ---- measures and queries ------------------------------------------------------------------------------------------

@pmethod('area')
def _area(nargout, P, *args):
    if args:
        items, _ = _items(P)
        p = items[0]
        return out(np.array([abs(_signed_area(p.rings[i])) for i in _bindex(p, args[0], 'area')]).reshape(-1, 1)) \
            if numel(args[0]) > 1 else abs(_signed_area(p.rings[_bindex(p, args[0], 'area')[0]]))
    return _each(P, lambda p: float(p.geom().area))


@pmethod('perimeter')
def _perimeter(nargout, P, *args):
    def ring_len(r):
        return float(np.sum(np.linalg.norm(np.diff(np.vstack([r, r[:1]]), axis=0), axis=1))) if len(r) else 0.0
    if args:
        p = _items(P)[0][0]
        vals = [ring_len(p.rings[i]) for i in _bindex(p, args[0], 'perimeter')]
        return vals[0] if len(vals) == 1 else out(np.array(vals).reshape(-1, 1))
    return _each(P, lambda p: sum(ring_len(r) for r in p.rings))


@pmethod('centroid')
def _centroid(nargout, P, *args):
    items, shape = _items(P)
    pts = []
    for p in items:
        if args:
            from shapely.geometry import Polygon
            for i in _bindex(p, args[0], 'centroid'):
                c = Polygon(p.rings[i]).centroid if len(p.rings[i]) >= 3 else None
                pts.append((c.x, c.y) if c is not None and not c.is_empty else (np.nan, np.nan))
        else:
            g = p.geom()
            c = g.centroid if not g.is_empty else None
            pts.append((c.x, c.y) if c is not None and not c.is_empty else (np.nan, np.nan))
    a = np.array(pts, F64)
    sh = (a.shape[0], 1) if args or len(items) > 1 else (1, 1)
    if args and numel(args[0]) == 1 or (not args and len(items) == 1):
        return _outs(nargout, float(a[0, 0]), float(a[0, 1]))
    return _outs(nargout, out(a[:, :1].reshape(sh if not args else (-1, 1), order='F') if args else a[:, 0].reshape(shape, order='F')),
                 out(a[:, 1:].reshape(-1, 1) if args else a[:, 1].reshape(shape, order='F')))


@pmethod('boundingbox')
def _boundingbox(nargout, P, *args):
    p = _items(P)[0][0]
    rings = [p.rings[i] for i in _bindex(p, args[0], 'boundingbox')] if args else p.rings
    if not rings:
        return _outs(nargout, np.zeros((0, 2)), np.zeros((0, 2)))
    V = np.vstack(rings)
    return _outs(nargout, np.array([[V[:, 0].min(), V[:, 0].max()]]), np.array([[V[:, 1].min(), V[:, 1].max()]]))


def _poly_boundary(nargout, P, *args):
    p = _items(P)[0][0]
    idx = _bindex(p, args[0], 'boundary') if args else range(len(p.rings))
    parts = []
    for k, i in enumerate(idx):
        r = p.rings[i]
        if k:
            parts.append(np.full((1, 2), np.nan))
        parts.append(np.vstack([r, r[:1]]) if len(r) else r)
    V = np.vstack(parts) if parts else np.zeros((0, 2))
    return _outs(nargout, out(V[:, :1]), out(V[:, 1:]))


POLY_METHODS.add('boundary')
method('boundary', _poly_boundary)


@pmethod('numboundaries')
def _numboundaries(nargout, P, *args):
    return _each(P, lambda p: float(len(p.rings)))


@pmethod('numsides')
def _numsides(nargout, P, *args):
    if args:
        p = _items(P)[0][0]
        vals = [float(len(p.rings[i])) for i in _bindex(p, args[0], 'numsides')]
        return vals[0] if len(vals) == 1 else out(np.array(vals).reshape(-1, 1))
    return _each(P, lambda p: float(sum(len(r) for r in p.rings)))


@pmethod('ishole')
def _ishole(nargout, P, *args):
    p = _items(P)[0][0]
    idx = _bindex(p, args[0], 'ishole') if args else range(len(p.rings))
    return out(np.array([p.holes[i] for i in idx], bool).reshape(-1, 1))


@pmethod('issimplified')
def _issimplified(nargout, P, *args):
    items, shape = _items(P)
    v = np.array([p.simplified for p in items], bool)
    return bool(v[0]) if v.size == 1 else v.reshape(shape, order='F')


def _query_points(args, fn):
    if len(args) == 1:
        Q = np.asarray(darr(args[0]), F64)
        if Q.ndim != 2 or Q.shape[1] != 2:
            raise err(f'MATLAB:{fn}:BadPoints', 'The query points are an n-by-2 matrix, or x and y.', fn)
        return Q, (Q.shape[0], 1)
    x, y = np.asarray(darr(args[0]), F64), np.asarray(darr(args[1]), F64)
    if x.size != y.size:
        raise err(f'MATLAB:{fn}:SizeMismatch', 'x and y are the same size.', fn)
    return np.column_stack([x.reshape(-1, order='F'), y.reshape(-1, order='F')]), (x.size, 1)


@pmethod('isinterior')
def _isinterior(nargout, P, *args):
    shp = _sh()
    p = _items(P)[0][0]
    Q, shape = _query_points(args, 'isinterior')
    g = p.geom()
    pts = shp.points(Q)
    on = np.zeros(len(Q), bool)
    for r in p.rings:
        from shapely.geometry import LinearRing
        if len(r) >= 3:
            on |= shp.distance(LinearRing(r), pts) <= 1e-12 * max(1.0, float(np.abs(r).max()))
    inside = shp.contains(g, pts) | on if not g.is_empty else on
    if nargout > 2:
        idx = np.full(len(Q), np.nan)
        for k, poly in enumerate(p.regions_list()):
            hit = shp.covers(poly, pts) & np.isnan(idx)
            idx[hit] = k + 1
        return inside.reshape(shape), on.reshape(shape), out(idx.reshape(shape))
    return _outs(nargout, inside.reshape(shape), on.reshape(shape))


@pmethod('nearestvertex')
def _nearestvertex(nargout, P, *args):
    p = _items(P)[0][0]
    Q, shape = _query_points(args, 'nearestvertex')
    V = p.vertices()
    ok = ~np.isnan(V[:, 0])
    if not ok.any():
        e = np.full((len(Q), 1), np.nan)
        return _outs(nargout, out(e), out(e), out(e))
    d = np.linalg.norm(Q[:, None, :] - V[None, ok, :], axis=2)
    vids = np.nonzero(ok)[0][np.argmin(d, axis=1)]
    bid = np.zeros(len(V), int)
    vix = np.zeros(len(V), int)
    pos = 0
    for i, r in enumerate(p.rings):
        bid[pos:pos + len(r)] = i
        vix[pos:pos + len(r)] = np.arange(len(r))
        pos += len(r) + 1
    return _outs(nargout, out((vids + 1.0).reshape(-1, 1)), out((bid[vids] + 1.0).reshape(-1, 1)), out((vix[vids] + 1.0).reshape(-1, 1)))


@pmethod('overlaps')
def _overlaps(nargout, P, *args):
    shp = _sh()
    if args:
        a, _ = _items(P)
        b, _ = _items(args[0])
        M = np.array([[bool(shp.intersects(x.geom(), y.geom())) for y in b] for x in a], bool)
        return bool(M[0, 0]) if M.size == 1 else M
    items, _ = _items(P)
    return np.array([[bool(shp.intersects(x.geom(), y.geom())) for y in items] for x in items], bool)


# ---- changes --------------------------------------------------------------------------------------------------------

def _affine(p, M, t):
    rings = [r @ M.T + t for r in p.rings]
    q = PolyShape(rings, p.holes, p.simplified)
    if np.linalg.det(M) < 0:
        q = PolyShape([r[::-1] for r in rings], p.holes, p.simplified)
    return q


@pmethod('rotate')
def _rotate(nargout, P, *args):
    if not args:
        raise err('MATLAB:rotate:nargin', 'rotate takes the angle in degrees (counterclockwise), and a point to turn about.', 'rotate')
    th = math.radians(float(num(args[0])))
    ref = np.asarray(darr(args[1]), F64).reshape(-1)[:2] if len(args) > 1 else np.zeros(2)
    M = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
    items, shape = _items(P)
    return _array([_affine(p, M, ref - M @ ref) for p in items], shape)


@pmethod('scale')
def _scale(nargout, P, *args):
    if not args:
        raise err('MATLAB:scale:nargin', 'scale takes the factor (or [sx sy]), and a point to scale about.', 'scale')
    s = np.asarray(darr(args[0]), F64).reshape(-1)
    s = np.array([s[0], s[0]]) if s.size == 1 else s[:2]
    if np.any(s <= 0):
        raise err('MATLAB:scale:BadFactor', 'The scale factors are positive.', 'scale')
    ref = np.asarray(darr(args[1]), F64).reshape(-1)[:2] if len(args) > 1 else np.zeros(2)
    M = np.diag(s)
    items, shape = _items(P)
    return _array([_affine(p, M, ref - M @ ref) for p in items], shape)


@pmethod('translate')
def _translate(nargout, P, *args):
    if len(args) == 1:
        t = np.asarray(darr(args[0]), F64).reshape(-1)[:2]
    elif len(args) == 2:
        t = np.array([float(num(args[0])), float(num(args[1]))])
    else:
        raise err('MATLAB:translate:nargin', 'translate takes [dx dy], or dx and dy.', 'translate')
    items, shape = _items(P)
    return _array([_affine(p, np.eye(2), t) for p in items], shape)


@pmethod('rmholes')
def _rmholes(nargout, P, *args):
    items, shape = _items(P)
    return _array([PolyShape.from_geom(_sh().union_all([_sh().geometry.Polygon(poly.exterior) for poly in _polys(p.geom())]))
                   if p.rings else p for p in items], shape)


@pmethod('rmboundary')
def _rmboundary(nargout, P, *args):
    p = _items(P)[0][0]
    if not args:
        raise err('MATLAB:rmboundary:nargin', 'rmboundary takes the indices of the boundaries to remove.', 'rmboundary')
    drop = set(_bindex(p, args[0], 'rmboundary'))
    keep = [i for i in range(len(p.rings)) if i not in drop]
    q = PolyShape([p.rings[i] for i in keep], [p.holes[i] for i in keep], p.simplified)
    return PolyShape.from_geom(q.geom()) if p.simplified else q


@pmethod('rmslivers')
def _rmslivers(nargout, P, *args):
    """Spikes and slivers narrower than tol taken off (an opening: in by tol/2
    and out again), then slits narrower than tol closed (out and in), with
    mitred corners (PyLAB's approach)."""
    if not args:
        raise err('MATLAB:rmslivers:nargin', 'rmslivers takes the tolerance.', 'rmslivers')
    tol = float(num(args[0]))
    p = _items(P)[0][0]
    g = p.geom()
    if tol > 0 and not g.is_empty:
        h = tol / 2
        g = g.buffer(-h, join_style='mitre').buffer(h, join_style='mitre')
        g = g.buffer(h, join_style='mitre').buffer(-h, join_style='mitre')
    return PolyShape.from_geom(g)


@pmethod('simplify')
def _simplify(nargout, P, *args):
    items, shape = _items(P)
    keep = False
    rest = list(args)
    if len(rest) >= 2 and (opt_lower(rest[0]) or '') == 'keepcollinearpoints':
        keep = _tf(rest[1])
    res = []
    for p in items:
        if p.simplified:
            res.append(p if keep else PolyShape.from_geom(p.geom()))
        else:
            res.append(_build(p.rings, True, 'auto', keep, 'simplify'))
    return _array(res, shape)


@pmethod('addboundary')
def _addboundary(nargout, P, *args):
    p = _items(P)[0][0]
    a = list(args)
    simp = True
    while len(a) >= 2 and is_str(a[-2]):
        if opt_lower(a[-2]) == 'simplify':
            simp = _tf(a[-1])
        a = a[:-2]
    rings = _xy_rings(a, 'addboundary')
    return _build(p.rings + rings, simp, 'auto', False, 'addboundary') if simp else \
        PolyShape(p.rings + rings, p.holes + [_signed_area(r) > 0 for r in rings], False)


def _sorted(P, args, fn, regions):
    p = _items(P)[0][0]
    crit = opt_lower(args[0]) if args else 'area'
    direction = opt_lower(args[1]) if len(args) > 1 else 'ascend'
    if direction not in ('ascend', 'descend'):
        raise err(f'MATLAB:{fn}:BadDirection', "The direction is 'ascend' or 'descend'.", fn)
    def key_ring(r):
        if crit == 'area':
            return abs(_signed_area(r))
        if crit == 'perimeter':
            return float(np.sum(np.linalg.norm(np.diff(np.vstack([r, r[:1]]), axis=0), axis=1)))
        if crit == 'numsides':
            return len(r)
        if crit == 'centroid':
            return float(np.hypot(*r.mean(axis=0)))
        raise err(f'MATLAB:{fn}:BadCriterion', "The criterion is 'area', 'perimeter', 'numsides' or 'centroid'.", fn)
    if regions:
        groups, cur = [], None
        for r, h in zip(p.rings, p.holes):
            if not h:
                cur = [(r, h)]
                groups.append(cur)
            elif cur is not None:
                cur.append((r, h))
        groups.sort(key=lambda g: key_ring(g[0][0]), reverse=direction == 'descend')
        flat = [x for g in groups for x in g]
    else:
        flat = sorted(zip(p.rings, p.holes), key=lambda rh: key_ring(rh[0]), reverse=direction == 'descend')
    q = PolyShape([r for r, _ in flat], [h for _, h in flat], p.simplified)
    q._geom = p._geom
    return q


@pmethod('sortboundaries')
def _sortboundaries(nargout, P, *args):
    return _sorted(P, args, 'sortboundaries', False)


@pmethod('sortregions')
def _sortregions(nargout, P, *args):
    return _sorted(P, args, 'sortregions', True)


@pmethod('regions')
def _regions(nargout, P, *args):
    p = _items(P)[0][0]
    polys = p.regions_list()
    items = [PolyShape.from_geom(x) for x in polys]
    if not items:
        return HArr(np.empty((0, 1), object))
    return _array(items, (len(items), 1))


@pmethod('holes')
def _holes(nargout, P, *args):
    p = _items(P)[0][0]
    hs = [r for r, h in zip(p.rings, p.holes) if h]
    items = [PolyShape([r[::-1]], [False], True) for r in hs]
    if not items:
        return HArr(np.empty((0, 1), object))
    return _array(items, (len(items), 1))


# ---- Boolean operations ----------------------------------------------------------------------------------------------

def _binary(name, op):
    def f(nargout, P, *args):
        shp = _sh()
        if not args:
            if name == 'union':
                items, _ = _items(P)
                return PolyShape.from_geom(shp.union_all([p.geom() for p in items]))
            raise err(f'MATLAB:{name}:nargin', f'{name} takes two polyshapes.', name)
        other = args[0]
        if name == 'intersect' and not _is_poly(other):
            return _cut_lines(nargout, _items(P)[0][0], other)
        a, sa = _items(P)
        b, sb = _items(other)
        if len(a) > 1 and len(b) > 1 and len(a) != len(b):
            raise err(f'MATLAB:{name}:SizeMismatch', 'The polyshape arrays are the same size, or one is a single polyshape.', name)
        n = max(len(a), len(b))
        res = [PolyShape.from_geom(op(a[i if len(a) > 1 else 0].geom(), b[i if len(b) > 1 else 0].geom())) for i in range(n)]
        if nargout > 1 and name in ('union', 'intersect', 'subtract', 'xor'):
            # the vertex map outputs are not given here
            raise err(f'MATLAB:{name}:nargout', f'{name} of polyshapes gives one output here.', name)
        return _array(res, sa if len(a) >= len(b) else sb)
    return f


def _cut_lines(nargout, p, L):
    """[in, out] = intersect(pgon, lineseg): the parts of the polyline inside and outside."""
    shp = _sh()
    from shapely.geometry import LineString
    V = np.asarray(darr(L), F64)
    if V.ndim != 2 or V.shape[1] != 2:
        raise err('MATLAB:intersect:BadLine', 'The line is an n-by-2 matrix of points.', 'intersect')
    line = LineString(V)
    g = p.geom()

    def rows(geom):
        parts = []
        for seg in getattr(geom, 'geoms', [geom]):
            if seg.is_empty or seg.geom_type != 'LineString':
                continue
            if parts:
                parts.append(np.full((1, 2), np.nan))
            parts.append(np.asarray(seg.coords))
        return out(np.vstack(parts)) if parts else np.zeros((0, 2))
    inside = shp.line_merge(shp.intersection(line, g)) if not g.is_empty else LineString()
    outside = shp.line_merge(shp.difference(line, g)) if not g.is_empty else line
    return _outs(nargout, rows(inside), rows(outside))


for _n, _op in (('union', lambda a, b: _sh().union(a, b)), ('intersect', lambda a, b: _sh().intersection(a, b)),
                ('subtract', lambda a, b: _sh().difference(a, b)), ('xor', lambda a, b: _sh().symmetric_difference(a, b))):
    POLY_METHODS.add(_n)
    method(_n, _binary(_n, _op))


@pmethod('convhull')
def _convhull(nargout, P, *args):
    p = _items(P)[0][0]
    g = p.geom()
    return PolyShape.from_geom(g.convex_hull) if not g.is_empty else PolyShape()


def _polybuffer(nargout, P, *args):
    p = _items(P)[0][0]
    if not args:
        raise err('MATLAB:polybuffer:nargin', 'polybuffer takes the distance.', 'polybuffer')
    d = float(num(args[0]))
    rest = list(args[1:])
    joint, limit = 'round', 3.0
    for i in range(0, len(rest) - 1, 2):
        k = opt_lower(rest[i])
        if k == 'jointtype':
            joint = opt_lower(rest[i + 1])
        elif k == 'miterlimit':
            limit = float(num(rest[i + 1]))
    style = {'round': 'round', 'square': 'mitre', 'miter': 'mitre'}.get(joint)
    if style is None:
        raise err('MATLAB:polybuffer:BadJoint', "JointType is 'round', 'square' or 'miter'.", 'polybuffer')
    g = p.geom()
    if joint == 'square':
        g2 = g.buffer(d, join_style='mitre', mitre_limit=1.0)          # a corner cut square at distance d
    else:
        g2 = g.buffer(d, quad_segs=16, join_style=style, mitre_limit=limit)
    return PolyShape.from_geom(g2)


@bi('polybuffer', aw=True, arr=False)
async def polybuffer_points(nargout, *args):
    """polyB = polybuffer(pgon, d, ...) or polybuffer(P, 'points', d) or
    polybuffer(P, 'lines', d): the region within d of a polyshape (inwards
    for d < 0), or of points or a polyline; 'JointType' 'round' (default),
    'square' or 'miter', 'MiterLimit'."""
    if args and _is_poly(args[0]):
        return _polybuffer(nargout, *args)
    await _shapely('polybuffer')
    if len(args) < 3:
        raise err('MATLAB:polybuffer:nargin', "polybuffer takes a polyshape and d, or points, 'points' or 'lines', and d.", 'polybuffer')
    V = np.asarray(darr(args[0]), F64)
    kind = opt_lower(args[1])
    d = float(num(args[2]))
    from shapely.geometry import LineString, MultiPoint
    if kind == 'points':
        g = MultiPoint(V).buffer(d, quad_segs=16)
    elif kind == 'lines':
        g = LineString(V).buffer(d, quad_segs=16)
    else:
        raise err('MATLAB:polybuffer:BadType', "The type is 'points' or 'lines'.", 'polybuffer')
    return PolyShape.from_geom(g)


POLY_METHODS.add('polybuffer')


@pmethod('triangulation')
def _triangulation(nargout, P, *args):
    shp = _sh()
    p = _items(P)[0][0]
    from .geomclasses import Triangulation
    g = p.geom()
    V = p.vertices()
    ok = ~np.isnan(V[:, 0])
    pts = V[ok]
    if g.is_empty or not pts.size:
        return Triangulation(np.zeros((0, 3), int), np.zeros((0, 2)))
    tris = shp.constrained_delaunay_triangles(g) if hasattr(shp, 'constrained_delaunay_triangles') else None
    if tris is None:
        tris = shp.ops.triangulate(g)
        tris = [t for t in tris if g.contains(t.representative_point())]
    else:
        tris = list(tris.geoms)
    from scipy.spatial import cKDTree
    tree = cKDTree(pts)
    T = []
    for t in tris:
        c = np.asarray(t.exterior.coords)[:3]
        _, j = tree.query(c)
        T.append(j)
    T = np.array(T, int).reshape(-1, 3)
    from .geomclasses import _orient2d
    return Triangulation(_orient2d(pts, T), pts)


def _draw(p, args):
    """A Polygon in the current axes (or the axes given first): the next colour, its face 0.35 opaque."""
    from .graphics import newplot, split_axes_arg, apply_props, name_value
    from ..graphics_base import Polygon
    ax, rest = split_axes_arg(args)
    ax = newplot(ax)
    h = Polygon(ax)
    h.set_value('Shape', p)
    c = ax.next_color()
    h.props['FaceColor'] = c
    h.props['EdgeColor'] = c
    apply_props(h, name_value(rest, 0))
    ax.touch()
    return h


@pmethod('plot')
def _plot(nargout, P, *args):
    items, shape = _items(P)
    # an array of shapes in the same axes: held after the first, as it was after the last
    hs, ax, keep = [], None, None
    for p in items:
        hs.append(_draw(p, args))
        if ax is None:
            ax = hs[-1].parent
            keep = ax.props['NextPlot']
            ax.props['NextPlot'] = 'add'
    if ax is not None:
        ax.props['NextPlot'] = keep
    if not nargout:
        return None
    return hs[0] if len(hs) == 1 else HArr.of(hs, col=False)

