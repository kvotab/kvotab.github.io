"""Triangulations, polygons and alpha shapes, run natively (needs shapely):
triangulation and delaunayTriangulation against scipy.spatial and their
geometry (counterclockwise triangles, Euler's formula, barycentric
coordinates, circumcentres equidistant, neighbours mutual, the free
boundary a loop, Voronoi diagrams), polyshape against areas worked by hand
and against Shapely called on its own (Booleans, buffers, holes, regions,
triangulation, line cuts), alpha shapes (areas of a ring with and without
its hole filled, critical alphas, inShape) and boundary.

    python3 test_shapes.py          (from any folder)
"""
import asyncio
import math
import os
import sys
import tempfile

import numpy as np
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-shapes-')
R.STATE['home'] = TMP


def run(code):
    R.BASE.clear()
    R.take_output()
    asyncio.run(R.execute(f"cd('{TMP}');\n" + code))
    return dict(R.BASE), R.take_output()


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, ok, detail=''):
        self.n += 1
        if not ok:
            self.failed.append(label)
            print(f'FAIL  {label}  {detail}')
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        return 1 if self.failed else 0


C = Checks()


def a(x):
    if isinstance(x, tuple):
        parts = [np.asarray(v, dtype=float).reshape(-1) for v in x]
        return np.concatenate(parts) if parts else np.zeros(0)
    return np.asarray(x, dtype=float)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 6).tolist() if g.size < 30 else g.shape}, want {np.round(w, 6).tolist() if w.size < 30 else w.shape}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str() if isinstance(W['e'], Char) else str(W['e'])
    return C(f'refused: {code}', words in msg, msg)



from scipy.spatial import Delaunay, ConvexHull, Voronoi  # noqa: E402


def flat(x):
    return np.asarray(x, dtype=float).reshape(-1).tolist()


def mat(M):
    return '[' + '; '.join(' '.join(repr(float(v)) for v in row) for row in np.atleast_2d(M)) + ']'


rs = np.random.RandomState(3)
P = rs.random_sample((30, 2))

# ---- delaunayTriangulation ----------------------------------------------------------------------------------------
W, out = run(f"""P = {mat(P)}; DT = delaunayTriangulation(P); cls = class(DT); T = DT.ConnectivityList; sz = size(DT);
E = edges(DT); [C, v] = convexHull(DT); Q = [0.5 0.5; 0.2 0.3; 2 2]; [id, B] = pointLocation(DT, Q);
pb = barycentricToCartesian(DT, id(1:2), B(1:2,:)); cb = cartesianToBarycentric(DT, id(1:2), Q(1:2,:));
[cc, r] = circumcenter(DT, (1:size(T,1))'); [ic, ri] = incenter(DT, 1); N = neighbors(DT); nn = nearestNeighbor(DT, [0.5 0.5]);
fb = freeBoundary(DT); va = vertexAttachments(DT, 5); va5 = va{{1}}; ea = edgeAttachments(DT, E(1,1), E(1,2)); ic1 = isConnected(DT, E(1,1), E(1,2));
[V, R] = voronoiDiagram(DT); DT
""")
T = a(W['T']).astype(int) - 1
ref = Delaunay(P, qhull_options='Qt Qbb Qc Qz')
same('delaunayTriangulation: the triangles of scipy.spatial.Delaunay', (W['cls'] if isinstance(W['cls'], str) else W['cls'].str(), sorted(map(tuple, np.sort(T, axis=1).tolist()))),
     ('delaunayTriangulation', sorted(map(tuple, np.sort(ref.simplices, axis=1).tolist()))))
area2 = (P[T[:, 1], 0] - P[T[:, 0], 0]) * (P[T[:, 2], 1] - P[T[:, 0], 1]) - (P[T[:, 1], 1] - P[T[:, 0], 1]) * (P[T[:, 2], 0] - P[T[:, 0], 0])
hull = ConvexHull(P)
C('every triangle counterclockwise; edges by Euler (V + F - E = 1); size is the connectivity list\'s',
  bool(np.all(area2 > 0)) and a(W['E']).shape[0] == 30 + T.shape[0] - 1 and flat(W['sz']) == [T.shape[0], 3.0], (area2.min(), a(W['E']).shape))
near("convexHull: the hull's area, a closed loop", (W['v'], a(W['C'])[0] == a(W['C'])[-1]), (hull.volume, 1), 1e-12)
ids = a(W['id']).reshape(-1)
near('pointLocation: a triangle holding each inside point, NaN outside; back and forth through barycentric coordinates',
     (np.isnan(ids[2]), W['pb'], W['cb']), (1, [[0.5, 0.5], [0.2, 0.3]], a(W['B'])[:2]), 1e-12)
cc, r = a(W['cc']), a(W['r']).reshape(-1)
C('circumcentres equidistant from their triangles\' corners', np.allclose(np.linalg.norm(P[T] - cc[:, None, :], axis=2), r[:, None], rtol=1e-10), None)
N = a(W['N'])
C('neighbours are mutual, NaN on the hull', all(np.isnan(N[i, j]) or i + 1 in N[int(N[i, j]) - 1] for i in range(N.shape[0]) for j in range(3))
  and int(np.isnan(N).sum()) == hull.vertices.size, None)
fb = a(W['fb'])
C('freeBoundary: a closed loop of the hull\'s edges', fb.shape[0] == hull.vertices.size and np.all(fb[1:, 0] == fb[:-1, 1]) and fb[0, 0] == fb[-1, 1], fb[:3].tolist())
C('nearestNeighbor, vertexAttachments, edgeAttachments, isConnected', int(a(W['nn'])) == int(np.argmin(np.linalg.norm(P - 0.5, axis=1))) + 1
  and np.all(np.any(T[a(W['va5']).astype(int).reshape(-1) - 1] == 4, axis=1)) and bool(W['ic1']) and float(a(W['ri'])) > 0, None)
vor = Voronoi(P)
same('voronoiDiagram: the vertices of scipy.spatial.Voronoi after a row of Inf', (a(W['V']).shape, bool(np.all(np.isinf(a(W['V'])[0])))), ((vor.vertices.shape[0] + 1, 2), True))
C('a delaunayTriangulation displays its properties', 'ConnectivityList: [' in out and 'Constraints: []' in out, out[-200:])
W, out = run("DT = delaunayTriangulation([0 0; 1 0; 0 1]); DT.Points(end+1, :) = [1 1]; n = size(DT.ConnectivityList, 1); D2 = delaunayTriangulation([0 0; 1 0; 0 1; 0 0]); np = size(D2.Points, 1); D3 = delaunayTriangulation([0 0; 1 1; 2 2]); nc = size(D3.ConnectivityList, 1);")
same('setting Points triangulates again; duplicates removed with a warning; collinear points no triangles',
     (float(W['n']), float(W['np']), 'Duplicate data points' in out, float(W['nc'])), (2.0, 3.0, True, 0.0))
W, _ = run("tet = delaunayTriangulation([0 0 0; 1 0 0; 0 1 0; 0 0 1; 1 1 1]); k = size(tet.ConnectivityList, 2); [K, v] = convexHull(tet); "
           "TR3 = triangulation([1 2 3], [0 0 0; 1 0 0; 0 1 0]); fn = faceNormal(TR3); vn = vertexNormal(TR3, 1); "
           "TR = triangulation([1 2 3; 1 3 4], [0 0; 1 0; 1 1; 0 1]); fb = freeBoundary(TR); f = figure('Visible', 'off'); h = triplot(TR); hc = class(h); close(f);")
near('in 3-D: tetrahedra and the hull\'s volume; a triangle\'s face and vertex normals', (W['k'], W['v'], W['fn'], W['vn']), (4, 0.5, [[0, 0, 1]], [[0, 0, 1]]), 1e-12)
near("triangulation(T, P): its free boundary round the square; triplot draws it", W['fb'], [[2, 3], [3, 4], [4, 1], [1, 2]])
same('triplot of a triangulation draws a line', W['hc'].str(), 'matlab.graphics.chart.primitive.Line')
raises('triangulation([1 2 5], [0 0; 1 0; 0 1])', 'point indices from 1 to 3')

# ---- alpha shapes ---------------------------------------------------------------------------------------------------
th = np.linspace(0, 2 * np.pi, 41)[:-1]
ring = np.vstack([np.column_stack([np.cos(th), np.sin(th)]), 0.5 * np.column_stack([np.cos(th), np.sin(th)])])
def polyarea(x, y):
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
outer, inner = polyarea(np.cos(th), np.sin(th)), polyarea(0.5 * np.cos(th), 0.5 * np.sin(th))
W, _ = run(f"""shp = alphaShape({mat(ring)}, 0.3); a1 = area(shp); n1 = numRegions(shp); p1 = perimeter(shp); shp.HoleThreshold = 10; a2 = area(shp);
s2 = alphaShape({mat(ring)}); al = s2.Alpha; ca = criticalAlpha(s2, 'all-points'); in = inShape(s2, [0 0; 0.75 0; 2 0]); sp = alphaSpectrum(s2);
bf = boundaryFacets(shp); s3 = alphaShape(rand(40, 3)); v3 = volume(s3); sa = surfaceArea(s3);""")
perim = np.sum(np.hypot(np.diff(np.r_[np.cos(th), 1]), np.diff(np.r_[np.sin(th), 0]))) * 1.5
near('alphaShape: a ring\'s area and perimeter (holes included) with alpha 0.3; its hole filled', (W['a1'], W['n1'], W['p1'], W['a2']), (outer - inner, 1, perim, outer), 1e-10)
near('the default alpha is criticalAlpha all-points; inShape; the spectrum falls', (W['al'] == W['ca'], W['in'], bool(np.all(np.diff(a(W['sp']).reshape(-1)) <= 0))),
     (1, [[0], [1], [0]], 1))
C('3-D alpha shapes have volume and surface', float(W['v3']) > 0 and float(W['sa']) > 0, (W['v3'], W['sa']))
W, _ = run(f"P = {mat(P)}; [k, A] = boundary(P(:,1), P(:,2)); [k0, A0] = boundary(P, 0); [k1, A1] = boundary(P, 1); [k3, V3] = boundary(rand(30, 3));")
near('boundary: a closed loop; s = 0 the convex hull; the area shrinks as s grows', (a(W['k'])[0] == a(W['k'])[-1], W['A0'], float(W['A1']) <= float(W['A']) <= float(W['A0'])),
     (1, hull.volume, 1), 1e-12)
same('boundary in 3-D: triangles', a(W['k3']).shape[1], 3)

# ---- polyshape -----------------------------------------------------------------------------------------------------------
import shapely  # noqa: E402
from shapely.geometry import Polygon as SPolygon  # noqa: E402
W, out = run("""p = polyshape([0 0 1 1], [1 0 0 1]); V = p.Vertices; ar = area(p); pe = perimeter(p); [cx, cy] = centroid(p);
sq = polyshape([0 4 4 0], [0 0 4 4]); hole = polyshape([1 3 3 1], [1 1 3 3]); d = subtract(sq, hole);
ad = area(d); nh = d.NumHoles; nr = d.NumRegions; ih = ishole(d)'; nb = numboundaries(d);
u = area(union(sq, translate(sq, 2, 0))); i2 = area(intersect(sq, translate(sq, [2 2]))); x = area(xor(sq, translate(sq, 2, 0)));
nest = polyshape({[0 4 4 0], [1 3 3 1]}, {[0 0 4 4], [1 1 3 3]}); an = area(nest); bow = polyshape([0 2 2 0], [0 2 0 2]); bw = bow.NumRegions; ba = area(bow);
[in, on] = isinterior(d, [0.5 2 4 2], [0.5 2 2 1]); r = rotate(sq, 90); [bx, by] = boundingbox(r); s2 = area(scale(sq, 2)); s3 = area(scale(sq, [1 2]));
c = area(convhull(polyshape([0 2 1 2 0], [0 0 1 2 2]))); bs = area(polybuffer(sq, 1, 'JointType', 'square')); br = area(polybuffer(sq, 1));
h6 = area(nsidedpoly(6, 'Radius', 2)); n4 = nsidedpoly(4, 'SideLength', 1); n4v = n4.Vertices; R = regions(union(sq, translate(sq, 10, 0))); ra = area(R);
H = area(holes(d)); rh = area(rmholes(d)); T = triangulation(d); nt = size(T.ConnectivityList, 1);
[vid, bid, vix] = nearestvertex(d, 2.9, 2.9); ov = [overlaps(sq, translate(sq, 5, 0)) overlaps(sq, hole)]; [xb, yb] = boundary(hole);
k = sortboundaries(d, 'area', 'ascend'); kh = ishole(k)'; pa = area([sq hole]); ab = area(addboundary(sq, [1 2 2 1], [1 1 2 2]));
ns = issimplified(polyshape([0 1 1 0], [0 0 1 1], 'Simplify', false)); [inl, outl] = intersect(sq, [-1 2; 5 2]);
f = figure('Visible', 'off'); h = plot(d); hc = class(h); ht = h.Type; hfa = h.FaceAlpha; hsa = area(h.Shape); hx = h.XData; close(f); da = d.area;""")
near('a square: clockwise from its first vertex, its area, perimeter and centroid', (W['V'], W['ar'], W['pe'], W['cx'], W['cy']),
     ([[0, 1], [1, 1], [1, 0], [0, 0]], 1, 4, 0.5, 0.5))
near('a square less a hole: area, one hole, one region, the hole counterclockwise', (W['ad'], W['nh'], W['nr'], W['ih'], W['nb'], W['da']), (12, 1, 1, [0, 1], 2, 12))
near('union, intersect, xor; nesting makes a hole; a bow tie two regions (with a warning)', (W['u'], W['i2'], W['x'], W['an'], W['bw'], W['ba']), (24, 4, 16, 12, 2, 2))
C('the bow tie was mended with a warning', 'Input data has been modified' in out, out[-200:])
near('isinterior: inside, in the hole, on the outer and on the hole boundary', (W['in'], W['on']), ([[1], [0], [1], [1]], [[0], [0], [1], [1]]))
near('rotate, boundingbox, scale, convhull, polybuffer (square corners; round: 16 + 16 + pi)', (W['bx'], W['by'], W['s2'], W['s3'], W['c'], W['bs']),
     ([[-4, 0]], [[0, 4]], 64, 32, 4, 36 - 4 * (math.sqrt(2) - 1) ** 2), 1e-9)
C('a round buffer: 16 + 16 + pi to its polygon\'s accuracy', abs(float(W['br']) - (32 + math.pi)) < 0.01, W['br'])
near('nsidedpoly: a hexagon\'s area; a unit square, its lowest side level, clockwise', (W['h6'], W['n4v']), (6 * math.sqrt(3), [[-0.5, -0.5], [-0.5, 0.5], [0.5, 0.5], [0.5, -0.5]]), 1e-12)
near('regions, holes, rmholes, triangulation, nearestvertex, overlaps, boundary (closed, clockwise from the first vertex)', (W['ra'], W['H'], W['rh'], W['nt'], W['bid'], W['ov'], W['xb'], W['yb']),
     ([[16], [16]], 4, 16, 8, 2, [[0, 1]], [[1], [1], [3], [3], [1]], [[1], [3], [3], [1], [1]]))
near('sortboundaries, an array of polyshapes, addboundary, Simplify false, cutting a line', (W['kh'], W['pa'], W['ab'], W['ns'], W['inl'], a(W['outl']).shape),
     ([1, 0], [16, 4], 15, 0, [[0, 2], [4, 2]], (5, 2)))
same("plot: a Polygon, Type 'polygon', FaceAlpha 0.35, its Shape", (W['hc'].str(), W['ht'].str(), float(W['hfa']), float(W['hsa']), int(np.isnan(a(W['hx'])).sum())),
     ('matlab.graphics.primitive.Polygon', 'polygon', 0.35, 12.0, 1))
# random polygons against Shapely called directly
for k in range(3):
    pa_, pb_ = rs.random_sample((7, 2)) * 4, rs.random_sample((6, 2)) * 4 + 1
    ga, gb = shapely.make_valid(SPolygon(pa_)), shapely.make_valid(SPolygon(pb_))
    W, _ = run(f"A = polyshape({mat(pa_)}); B = polyshape({mat(pb_)}); r = [area(A) area(B) area(union(A, B)) area(intersect(A, B)) area(subtract(A, B)) area(xor(A, B))];")
    near(f'random polygons {k + 1}: areas of the Booleans as Shapely gives them', W['r'],
         [[ga.area, gb.area, ga.union(gb).area, ga.intersection(gb).area, ga.difference(gb).area, ga.symmetric_difference(gb).area]], 1e-9)
raises("polyshape([0 1 1], [0 0 1], 'SolidBoundaryOrientation', 'up')", "'auto', 'cw' or 'ccw'")

sys.exit(C.done())
