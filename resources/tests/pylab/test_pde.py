"""Partial differential equations by finite elements, run natively (CPython
with numpy and scipy): decsg's regions (their areas against Shapely's),
meshes (area, element quality, nodes on the curves), and solutions whose
answers are known: Poisson's equation on a disk ((1 - r^2)/4) and with a
manufactured sine, layered conduction, a Robin edge, a nonlinear
coefficient, systems and mixed conditions, the square's eigenvalues,
heat decay, a standing wave, a boundary value growing in time; the
finite-element matrices; interpolation and gradients; the drawings.

Shapely is a reference only for the areas here (the page's decsg does not
use it); the suite says so and stops when it is missing.

    python3 test_pde.py          (from any folder)
"""
import asyncio
import math
import os
import sys
import tempfile
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

try:
    import shapely.geometry as SG
except ImportError as e:
    print(f'test_pde needs Shapely as a reference ({e}).')
    sys.exit(1)

R.setup()
warnings.filterwarnings('ignore')


def run(code):
    R.BASE.clear()
    R.take_output()
    asyncio.run(R.execute(code))
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
        return np.concatenate([np.asarray(v, dtype=float).reshape(-1) for v in x])
    return np.asarray(x)


def near(label, got, want, tol=1e-10):
    g, w = a(got).astype(float), np.asarray(want, float)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 8).tolist() if g.size < 30 else g.shape}, want {np.round(w, 8).tolist() if w.size < 30 else w.shape}')


def text(v):
    return v.str() if isinstance(v, Char) else str(v)


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = text(W['e'])
    return C(f'refused: {code}', words in msg, msg)


SQ = "decsg([3; 4; 0; 1; 1; 0; 0; 0; 1; 1])"
DISK = "decsg([1; 0; 0; 1])"

# ---- geometry ------------------------------------------------------------------------------------------------------------------------

W, _ = run("gd = [3 4 -1 1 1 -1 -1 -1 1 1; 1 0 0 0.5 0 0 0 0 0 0]'; [dl, bt] = decsg(gd, 'R1-C1', char('R1', 'C1')'); m = createpde; g = geometryFromEdges(m, dl);"
           "ne = g.NumEdges; nf = g.NumFaces; nv = g.NumVertices; generateMesh(m, 'Hmax', 0.05); A = area(m.Mesh); [A2, Ae] = area(m.Mesh, 1:5); s5 = sum(Ae);"
           "n = findNodes(m.Mesh, 'region', 'Edge', 5:8); P = m.Mesh.Nodes(:, n); r = sqrt(sum(P.^2, 1));")
near('decsg R1-C1: 8 edges (4 sides, 4 quarter arcs), 1 face, 8 vertices', (W['ne'], W['nf'], W['nv']), [8, 1, 8])
near('decsg R1-C1: the region of the square, not the circle', W['bt'], [[1, 0]])
near('the mesh of a square less a circle: its area 4 - pi/4 (curved quadratic elements)', W['A'], 4 - math.pi / 4, 1e-6)
near('area(mesh, elements): the sum of those elements', W['A2'], W['s5'], 1e-14)
dl = a(W['dl'])
arcs = [j for j in range(dl.shape[1]) if dl[0, j] == 1]
C('the circle\'s edges are arcs of radius 0.5, and their nodes on it', len(arcs) == 4 and np.allclose(dl[9, arcs], 0.5), dl[:, arcs])
near('nodes found on the arcs lie on the circle', a(W['r']).reshape(-1), np.full(a(W['r']).size, 0.5), 1e-12)


def shp_area(code):
    W, _ = run(code + " m = createpde; geometryFromEdges(m, dl); generateMesh(m, 'Hmax', 0.05); A = area(m.Mesh); nf = m.Geometry.NumFaces;")
    return W


circle = lambda x, y, r: SG.Point(x, y).buffer(r, 4096)  # noqa: E731
rect = lambda x0, x1, y0, y1: SG.box(x0, y0, x1, y1)  # noqa: E731
W = shp_area("dl = decsg([3 4 -1 1 1 -1 -1 -1 1 1; 1 0 0 1.2 0 0 0 0 0 0]', 'R1*C1', char('R1', 'C1')');")
near("decsg R1*C1: Shapely's area of the intersection", W['A'], rect(-1, 1, -1, 1).intersection(circle(0, 0, 1.2)).area, 1e-5)
gd3 = "[1 0 0 1 0 0 0 0 0 0; 1 0.8 0 0.6 0 0 0 0 0 0; 3 4 -0.2 0.3 0.3 -0.2 -0.2 -0.2 0.3 0.3]'"
W = shp_area(f"dl = decsg({gd3}, '(C1+C2)-R1', char('C1', 'C2', 'R1')');")
ref = circle(0, 0, 1).union(circle(0.8, 0, 0.6)).difference(rect(-0.2, 0.3, -0.2, 0.3))
near("decsg (C1+C2)-R1: Shapely's area (a hole and a crescent)", W['A'], ref.area, 1e-5)
C('decsg (C1+C2)-R1: the overlap and the two crescents are faces of their own', a(W['nf']) == 3, W['nf'])
W = shp_area("dl = decsg([4 0 0 2 1 0.3 0; 1 0.5 0 0.3 0 0 0]', 'E1-C1', char('E1', 'C1')');")
near('decsg E1-C1: an ellipse less a circle, pi*2*1 - pi*0.09', W['A'], 2 * math.pi - math.pi * 0.09, 1e-5)
W = shp_area("dl = decsg([2 6 0 2 2 1 1 0 0 0 1 1 2 2]');")
near('decsg of a polygon: an L of area 3', W['A'], 3.0, 1e-12)
W, _ = run("gd = [3 4 0 1 1 0 0 0 0.5 0.5; 3 4 1 2 2 1 0 0 0.5 0.5]'; [dl, bt] = decsg(gd); ne = size(dl, 2); inner = dl(6:7, 2)';")
near('decsg of two rectangles side by side: 7 edges, the shared one between faces 1 and 2', (W['ne'], W['inner'], W['bt']), [7, 1, 2, 1, 0, 0, 1])

tmp = tempfile.mkdtemp()
with open(os.path.join(tmp, 'twohalves.m'), 'w') as fh:
    fh.write("function [x, y] = twohalves(bs, s)\n% a unit disk as two edges\nif nargin == 0\n    x = 2;\n    return\nend\n"
             "d = [0 pi; pi 2*pi; 1 1; 0 0];\nif nargin == 1\n    x = d(:, bs);\n    return\nend\nx = cos(s);\ny = sin(s);\nend\n")
W, _ = run(f"addpath('{tmp}'); m = createpde; g = geometryFromEdges(m, @twohalves); ne = g.NumEdges; generateMesh(m, 'Hmax', 0.2); A = area(m.Mesh);"
           "specifyCoefficients(m, 'm', 0, 'd', 0, 'c', 1, 'a', 0, 'f', 1); applyBoundaryCondition(m, 'dirichlet', 'Edge', 1:2, 'u', 0); R = solvepde(m); u0 = interpolateSolution(R, 0, 0);")
near('a geometry function: its two edges, the disk\'s area and Poisson\'s solution at the centre', (W['ne'], W['A'], W['u0']), [2, math.pi, 0.25], 1e-4)

W, _ = run(f"m = createpde; geometryFromEdges(m, {DISK}); M = generateMesh(m, 'Hmax', 0.15); nl = size(M.Elements, 1); M1 = generateMesh(m, 'Hmax', 0.15, 'GeometricOrder', 'linear');"
           "n1 = size(M1.Elements, 1); go = M1.GeometricOrder; [p, e, t] = meshToPet(M); sp = size(p, 1); st = size(t, 1);")
near('quadratic elements 6 nodes, linear 3; meshToPet\'s forms', (W['nl'], W['n1'], W['sp'], W['st']), [6, 3, 2, 7])
C('GeometricOrder', text(W['go']) == 'linear', W['go'])
W, _ = run("m = createpde; geometryFromEdges(m, decsg([1 0 0 1; 1 0.95 0 0.1]', 'C1-C2', char('C1', 'C2')')); generateMesh(m, 'Hmax', 0.1);")
mesh = W['m'].mesh
P, t = mesh.p, mesh.t[:, :3]
A_, B_, C_ = P[t[:, 0]], P[t[:, 1]], P[t[:, 2]]


def ang(u, v):
    c = np.einsum('ij,ij->i', u, v) / (np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1))
    return np.degrees(np.arccos(np.clip(c, -1, 1)))


a1, a2 = ang(B_ - A_, C_ - A_), ang(A_ - B_, C_ - B_)
mins = np.minimum(np.minimum(a1, a2), 180 - a1 - a2)
C('mesh quality: no angle below 15 degrees where a hole nearly cuts the boundary, half of them above 50', mins.min() > 15 and np.median(mins) > 50, (mins.min(), np.median(mins)))
C('every element counterclockwise', np.all(mesh.areas() > 0), mesh.areas().min())

# ---- stationary problems -------------------------------------------------------------------------------------------------------------

W, _ = run(f"m = createpde; geometryFromEdges(m, {DISK}); applyBoundaryCondition(m, 'dirichlet', 'Edge', 1:4, 'u', 0);"
           "specifyCoefficients(m, 'm', 0, 'd', 0, 'c', 1, 'a', 0, 'f', 1); generateMesh(m, 'Hmax', 0.2); R = solvepde(m); p = m.Mesh.Nodes;"
           "e2 = max(abs(R.NodalSolution - (1 - sum(p.^2, 1))'/4)); generateMesh(m, 'Hmax', 0.2, 'GeometricOrder', 'linear'); R1 = solvepde(m); p1 = m.Mesh.Nodes;"
           "e1 = max(abs(R1.NodalSolution - (1 - sum(p1.^2, 1))'/4)); ui = interpolateSolution(R, [0 0.5 2], [0 0.3 0]); [gx, gy] = evaluateGradient(R, 0.5, 0.3);")
C("Poisson's equation on the unit disk: (1 - r^2)/4 at the nodes (quadratic within 1e-4, linear within 3e-3)", a(W['e2']) < 1e-4 and a(W['e1']) < 3e-3, (W['e2'], W['e1']))
near('interpolateSolution: inside, and NaN outside', W['ui'], [[0.25], [(1 - 0.34) / 4], [np.nan]], 2e-4)
near('evaluateGradient: -(x, y)/2', (W['gx'], W['gy']), [-0.25, -0.15], 2e-3)
for h, tol in ((0.1, 3e-4), (0.05, 4e-5)):
    W, _ = run(f"m = createpde; geometryFromEdges(m, {SQ}); applyBoundaryCondition(m, 'dirichlet', 'Edge', 1:4, 'u', 0);"
               "specifyCoefficients(m, 'm', 0, 'd', 0, 'c', 1, 'a', 0, 'f', @(l, s) 2*pi^2*sin(pi*l.x).*sin(pi*l.y));"
               f"generateMesh(m, 'Hmax', {h}); R = solvepde(m); p = m.Mesh.Nodes; e = max(abs(R.NodalSolution - (sin(pi*p(1,:)).*sin(pi*p(2,:)))'));")
    C(f'a manufactured solution sin(pi x) sin(pi y), Hmax {h}: within {tol:g}', a(W['e']) < tol, W['e'])
W, _ = run("m = createpde; geometryFromEdges(m, decsg([3 4 0 1 1 0 0 0 0.5 0.5; 3 4 1 2 2 1 0 0 0.5 0.5]'));"
           "specifyCoefficients(m, 'm', 0, 'd', 0, 'c', 1, 'a', 0, 'f', 0, 'Face', 1); specifyCoefficients(m, 'm', 0, 'd', 0, 'c', 2, 'a', 0, 'f', 0, 'Face', 2);"
           "applyBoundaryCondition(m, 'dirichlet', 'Edge', 4, 'u', 0); applyBoundaryCondition(m, 'dirichlet', 'Edge', 6, 'u', 1);"
           "generateMesh(m, 'Hmax', 0.1); R = solvepde(m); v = interpolateSolution(R, [0.5 1 1.5], [0.25 0.25 0.25]);")
near('two layers, conductivities 1 and 2: piecewise linear, the flux continuous', W['v'], [[1 / 3], [2 / 3], [5 / 6]], 1e-10)
W, _ = run("m = createpde; geometryFromEdges(m, decsg([3; 4; 0; 1; 1; 0; 0; 0; 0.2; 0.2])); specifyCoefficients(m, 'm', 0, 'd', 0, 'c', 1, 'a', 0, 'f', 0);"
           "applyBoundaryCondition(m, 'dirichlet', 'Edge', 4, 'u', 1); applyBoundaryCondition(m, 'neumann', 'Edge', 2, 'g', 1, 'q', 2);"
           "generateMesh(m, 'Hmax', 0.05); R = solvepde(m); v = interpolateSolution(R, [0.5 1], [0.1 0.1]);")
near("a Robin edge, u'(1) + 2u(1) = 1 with u(0) = 1: u = 1 - x/3", W['v'], [[5 / 6], [2 / 3]], 1e-10)
W, _ = run(f"m = createpde; geometryFromEdges(m, {SQ}); specifyCoefficients(m, 'm', 0, 'd', 0, 'c', @(l, s) 1 + s.u.^2, 'a', 0, 'f', @(l, s) -2*l.x);"
           "applyBoundaryCondition(m, 'dirichlet', 'Edge', 1:4, 'u', @(l, s) l.x); generateMesh(m, 'Hmax', 0.2); R = solvepde(m); p = m.Mesh.Nodes; e = max(abs(R.NodalSolution - p(1, :)'));")
C('a nonlinear coefficient, -div((1 + u^2) grad u) = -2x: u = x by the fixed-point iteration', a(W['e']) < 1e-5, W['e'])
W, _ = run(f"m = createpde(2); geometryFromEdges(m, {DISK}); specifyCoefficients(m, 'm', 0, 'd', 0, 'c', [1; 2], 'a', 0, 'f', [1; 1]);"
           "applyBoundaryCondition(m, 'dirichlet', 'Edge', 1:4, 'u', [0 0]); generateMesh(m, 'Hmax', 0.2); R = solvepde(m); U = R.NodalSolution; sz = size(U);"
           "d = max(abs(U(:,2) - U(:,1)/2)); mx = max(U(:,1)); v = interpolateSolution(R, [0 0.5], [0 0], 2);"
           "applyBoundaryCondition(m, 'mixed', 'Edge', 1:4, 'u', 0, 'EquationIndex', 1, 'g', 0.1); specifyCoefficients(m, 'm', 0, 'd', 0, 'c', [1; 2], 'a', [0; 1], 'f', [1; 1]);"
           "R5 = solvepde(m); U5 = R5.NodalSolution; same = max(abs(U5(:,1) - U(:,1))); lo = min(U5(:,2));")
near('a system: its components a column each; c = [1; 2] halves the second', (W['sz'], W['d']), [389, 2, 0], 1e-12)
near("a system: the first component is the disk's Poisson solution", W['mx'], 0.25, 1e-3)
near('interpolateSolution of one component', W['v'], [[0.125], [0.125 * 0.75]], 3e-4)
C('mixed: Dirichlet for the first component, a Neumann inflow raising the second above f/a', a(W['same']) < 1e-12 and a(W['lo']) > 1, (W['same'], W['lo']))
raises(f"m = createpde(2); geometryFromEdges(m, {DISK}); specifyCoefficients(m, 'm', 0, 'd', 0, 'c', [1; 2], 'a', 0, 'f', [1; 1]); generateMesh(m, 'Hmax', 0.2);"
       "applyBoundaryCondition(m, 'mixed', 'Edge', 1:4, 'u', 0, 'EquationIndex', 1, 'g', 0.1); solvepde(m)", 'singular')

W, _ = run(f"m = createpde; geometryFromEdges(m, {DISK}); specifyCoefficients(m, 'm', 0, 'd', 0, 'c', 1, 'a', 2, 'f', 1); applyBoundaryCondition(m, 'neumann', 'Edge', 1:4, 'g', 0.5);"
           "applyBoundaryCondition(m, 'dirichlet', 'Edge', 1, 'u', 0); generateMesh(m, 'Hmax', 0.3); F = assembleFEMatrices(m); K = full(F.K); A = full(F.A);"
           "sym = max(max(abs(K - K'))); rows = max(abs(sum(K, 2))); fs = sum(F.F); as = sum(A(:)); gs = sum(F.G); nh = size(F.H, 1); nb = numel(findNodes(m.Mesh, 'region', 'Edge', 1));"
           "isp = issparse(F.K);")
near('assembleFEMatrices: K symmetric, its rows summing to 0 (constants have no gradient)', (W['sym'], W['rows']), [0, 0], 1e-12)
near('assembleFEMatrices: F and A integrate f = 1 and a = 2 over the disk, G g = 0.5 round the three arcs the Dirichlet edge leaves', (W['fs'], W['as'], W['gs']), [math.pi, 2 * math.pi, 0.75 * math.pi], 1e-4)
W2, _ = run("m = createpde; geometryFromEdges(m, decsg([3; 4; 0; 2; 2; 0; 0; 0; 1; 1])); mesh = generateMesh(m, 'Hmax', 0.25, 'GeometricOrder', 'linear'); [p, e, t] = meshToPet(mesh); "
            "ok = true; cnt = zeros(1, 4); for k = 1:4, n = findNodes(mesh, 'region', 'Edge', k); cnt(k) = numel(n); ok = ok && isequal(n, unique(reshape(e(1:2, e(5, :) == k), 1, []))); end")
C('findNodes by edge: the nodes of that edge, counted from 1 as meshToPet gives them (Edge 1 gave the second edge, the last none)', bool(W2['ok']) and sorted(a(W2['cnt']).reshape(-1).tolist()) == [5, 5, 9, 9], W2['cnt'])
C('assembleFEMatrices: H a row for each node fixed by the Dirichlet edge; sparse', a(W['nh']) == a(W['nb']) and bool(W['isp']), (W['nh'], W['nb']))

# ---- eigenvalues, time ----------------------------------------------------------------------------------------------------------------

W, _ = run(f"m = createpde; geometryFromEdges(m, {SQ}); applyBoundaryCondition(m, 'dirichlet', 'Edge', 1:4, 'u', 0); specifyCoefficients(m, 'm', 0, 'd', 1, 'c', 1, 'a', 0, 'f', 0);"
           "generateMesh(m, 'Hmax', 0.1); E = solvepdeeig(m, [0 90]); lam = E.Eigenvalues / pi^2; V = E.Eigenvectors; sv = size(V);")
near("the unit square's Dirichlet eigenvalues: 2, 5, 5, 8 times pi^2", a(W['lam']).reshape(-1), [2, 5, 5, 8], 1e-3)
near('an eigenvector for each', W['sv'], [[a(W['V']).shape[0], 4]])
W, _ = run(f"m = createpde; geometryFromEdges(m, {SQ}); applyBoundaryCondition(m, 'dirichlet', 'Edge', 1:4, 'u', 0); specifyCoefficients(m, 'm', 0, 'd', 1, 'c', 1, 'a', 0, 'f', 0);"
           "generateMesh(m, 'Hmax', 0.1); p = m.Mesh.Nodes; ex = (sin(pi*p(1,:)).*sin(pi*p(2,:)))'; setInitialConditions(m, @(l) sin(pi*l.x).*sin(pi*l.y));"
           "T = solvepde(m, [0 0.02 0.05]); u = T.NodalSolution; st = T.SolutionTimes; e1 = max(abs(u(:, 3) - exp(-2*pi^2*0.05)*ex));"
           "m.SolverOptions.RelativeTolerance = 1e-5; m.SolverOptions.AbsoluteTolerance = 1e-8; T2 = solvepde(m, [0 0.05]); u2 = T2.NodalSolution; e2 = max(abs(u2(:, 2) - exp(-2*pi^2*0.05)*ex));"
           "specifyCoefficients(m, 'm', 1, 'd', 0, 'c', 1, 'a', 0, 'f', 0); m.SolverOptions.RelativeTolerance = 1e-3; m.SolverOptions.AbsoluteTolerance = 1e-6;"
           "Wv = solvepde(m, [0 0.25 0.5]); w = Wv.NodalSolution; ew = max(abs(w(:, 3) - cos(sqrt(2)*pi*0.5)*ex));")
near('a time-dependent solution: a column for each time', a(W['st']), [[0, 0.02, 0.05]])
C('heat: the decay exp(-2 pi^2 t) within the default tolerances (3e-3), and within 2e-4 at 1e-5', a(W['e1']) < 3e-3 and a(W['e2']) < 2e-4, (W['e1'], W['e2']))
C("the wave equation's standing wave cos(sqrt(2) pi t) sin sin (m = 1, from rest)", a(W['ew']) < 3e-3, W['ew'])
W, _ = run(f"m = createpde; geometryFromEdges(m, {SQ}); specifyCoefficients(m, 'm', 0, 'd', 1, 'c', 1, 'a', 0, 'f', 1);"
           "applyBoundaryCondition(m, 'dirichlet', 'Edge', 1:4, 'u', @(l, s) s.time*ones(size(l.x))); generateMesh(m, 'Hmax', 0.25);"
           "T = solvepde(m, [0 0.5 1]); u = T.NodalSolution; e = max(abs(u(:, 3) - 1));")
near('a boundary value growing in time: u = t everywhere', W['e'], 0.0, 1e-6)

# ---- drawings, refusals --------------------------------------------------------------------------------------------------------------

W, _ = run(f"m = createpde; geometryFromEdges(m, {DISK}); applyBoundaryCondition(m, 'dirichlet', 'Edge', 1:4, 'u', 0); specifyCoefficients(m, 'm', 0, 'd', 0, 'c', 1, 'a', 0, 'f', 1);"
           "generateMesh(m, 'Hmax', 0.3); R = solvepde(m); f = figure('Visible', 'off'); h = pdeplot(m, 'XYData', R.NodalSolution, 'Contour', 'on', 'Mesh', 'on'); c1 = class(h);"
           "nc = numel(get(gca, 'Children')); clf; pdegplot(m, 'EdgeLabels', 'on', 'FaceLabels', 'on'); ng = numel(findobj(gca, 'Type', 'text'));"
           "clf; pdemesh(m); nm = numel(get(gca, 'Children')); clf; pdeplot(R.Mesh, 'XYData', R.NodalSolution, 'ZData', R.NodalSolution, 'FlowData', [R.XGradients R.YGradients]); close(f);")
C('pdeplot: a patch with contour lines and the mesh over it', text(W['c1']) == 'matlab.graphics.primitive.Patch' and a(W['nc']) >= 3, (W['c1'], W['nc']))
near('pdegplot: four edge labels and a face label', W['ng'], 5.0)
C('pdemesh draws', a(W['nm']) >= 1, W['nm'])
raises("createpde('thermal')", 'general PDE models')
raises(f"m = createpde; geometryFromEdges(m, {SQ}); specifyCoefficients(m, 'c', 1, 'a', 0, 'f', 1)", 'All five coefficients')
raises("m = createpde; geometryFromEdges(m, decsg([3 4 0 1 1 0 0 0 0.5 0.5; 3 4 1 2 2 1 0 0 0.5 0.5]')); applyBoundaryCondition(m, 'dirichlet', 'Edge', 2, 'u', 0)", 'between two faces')
raises("m = createpde; generateMesh(m)", 'no geometry')
raises(f"m = createpde; geometryFromEdges(m, {SQ}); generateMesh(m); specifyCoefficients(m, 'm', 0, 'd', 1, 'c', 1, 'a', 0, 'f', 0); solvepde(m)", 'needs the times')
raises("decsg([1; 0; 0; 1], 'C1+Q', char('C1')')", "'Q' is not a shape's name")
raises(f"m = createpde; geometryFromEdges(m, {SQ}); generateMesh(m, 'Hedge', {{1, 0.1}})", 'Hedge')

sys.exit(C.done())
