"""The core's numerical functions, run natively and checked against NumPy
and SciPy computing the same things another way: uniquetol and ismembertol,
lsqminnorm against pinv, decomposition against solve for each type,
sylvester, lscov against the weighted normal equations, normest1, subspace
against scipy.linalg.subspace_angles, condeig against eig's left and right
vectors, cdf2rdf, hadamard, delaunayn, convhulln and griddatan against
scipy.spatial, nufft and nufftn against fft and the direct sums, colperm,
symbfact against the nonzeros of a Cholesky factor, rmse and mape.

    python3 test_numerics.py          (from any folder)
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
TMP = tempfile.mkdtemp(prefix='pylab-numerics-')
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



import scipy.linalg as sla  # noqa: E402
from scipy.spatial import Delaunay, ConvexHull  # noqa: E402


def flat(x):
    return np.asarray(x, dtype=float).reshape(-1).tolist()


def mat(M):
    return '[' + '; '.join(' '.join(repr(float(v)) for v in row) for row in np.atleast_2d(M)) + ']'


# ---- equal within a tolerance --------------------------------------------------------------------------------------
W, _ = run("""[C, IA, IC] = uniquetol([1 1+1e-8 2 3 3+1e-9 1-1e-8]); C2 = uniquetol([1 1.05 1.2 2], 0.04);
[C3, ia3] = uniquetol([1 2; 1.0000001 2; 3 4], 'ByRows', true); [~, ia4] = uniquetol([1 1+1e-9 2], 'OutputAllIndices', true); g1 = ia4{1};
s = uniquetol(single([1 1.00001 2])); sc = class(s);""")
near('uniquetol: groups within tol*max(abs(A)), the smallest of each kept, IA and IC', (W['C'], W['IA'], W['IC']),
     ([1 - 1e-8, 2, 3], [6, 3, 4], [1, 1, 2, 3, 3, 1]), 1e-15)
near('uniquetol: a tolerance given; by rows; all the indices of a group', (W['C2'], W['C3'], W['ia3'], W['g1']),
     ([1, 1.2, 2], [[1, 2], [3, 4]], [1, 3], [1, 2]), 1e-12)
same('uniquetol of single: 1e-4 and single kept', (flat(W['s']), str(W['sc'].str())), ([1.0, 2.0], 'single'))
W, _ = run("[l, lb] = ismembertol([1 2.0000000000001 5], [9 2 1]); [l2, lb2] = ismembertol([1 1.1], [1.05 3], 0.03); [l3, lb3] = ismembertol([1 2; 3 4], [3 4.0000000001; 1 2], 1e-9, 'ByRows', true);")
near('ismembertol: members and the index in B; a tolerance; by rows', (W['l'], W['lb'], W['l2'], W['lb2'], W['l3'], W['lb3']),
     ([1, 1, 0], [3, 2, 0], [1, 1], [1, 1], [1, 1], [2, 1]))

# ---- least squares and factorizations -------------------------------------------------------------------------------
rs = np.random.RandomState(4)
Ar = rs.standard_normal((6, 4)) @ np.diag([1, 1, 0, 1.0]) @ rs.standard_normal((4, 4))       # rank 3
br = rs.standard_normal((6, 2))
W, _ = run(f"x = lsqminnorm({mat(Ar)}, {mat(br)}, 'nowarn'); x2 = lsqminnorm([1 1; 1 1], [2; 2], 'nowarn'); lastwarn(''); lsqminnorm({mat(Ar)}, {mat(br)}); [~, id] = lastwarn;")
near('lsqminnorm: the minimum-norm solution, as pinv gives it, for a rank-deficient A', (W['x'], W['x2']), (np.linalg.pinv(Ar) @ br, [[1], [1]]), 1e-9)
same('lsqminnorm warns of a rank-deficient A', W['id'].str(), 'MATLAB:rankDeficientMatrix')
An = rs.standard_normal((5, 5)) + 5 * np.eye(5)
Sp = An @ An.T
Lo = np.tril(An)
Ht = np.array([[2.0, 1, 0], [1, -3, 1], [0, 1, 1]])
b5 = rs.standard_normal((5, 1))
W, _ = run(f"""A = {mat(An)}; b = {mat(b5)}; S = {mat(Sp)}; L = {mat(Lo)}; H = {mat(Ht)};
d1 = decomposition(A); t1 = d1.Type; x1 = d1 \\ b; y1 = b' / d1; z1 = d1' \\ b;
d2 = decomposition(S); t2 = d2.Type; x2 = d2 \\ b; d3 = decomposition(L); t3 = d3.Type; x3 = d3 \\ b;
d4 = decomposition(H, 'ldl'); x4 = d4 \\ [1; 2; 3]; d5 = decomposition(A(:, 1:3), 'qr'); t5 = d5.Type; x5 = d5 \\ b; ms = d5.MatrixSize;
d6 = decomposition(diag([2 4 8])); t6 = d6.Type; x6 = d6 \\ [2; 4; 8]; d7 = decomposition(A, 'cod'); x7 = d7 \\ b; rk = rank(decomposition([1 2; 2 4], 'cod'));
rc = rcond(d1); il = isIllConditioned(decomposition([1 1; 1 1+1e-17], 'lu', 'CheckCondition', false));""")
same('decomposition chooses lu, chol, triangular, qr and diagonal', tuple(W[k].str() for k in ('t1', 't2', 't3', 't5', 't6')), ('lu', 'chol', 'triangular', 'qr', 'diagonal'))
near("dA\\b, b/dA and dA'\\b as solve gives them", (W['x1'], W['y1'], W['z1']),
     (np.linalg.solve(An, b5), np.linalg.solve(An.T, b5).T, np.linalg.solve(An.T, b5)), 1e-10)
near('chol, triangular, ldl, qr (least squares), diagonal and cod solve', (W['x2'], W['x3'], W['x4'], W['x5'], W['x6'], W['x7'], W['ms']),
     (np.linalg.solve(Sp, b5), np.linalg.solve(Lo, b5), np.linalg.solve(Ht, [[1], [2], [3]]), np.linalg.lstsq(An[:, :3], b5, rcond=None)[0],
      [[1], [1], [1]], np.linalg.solve(An, b5), [6 - 1, 3]), 1e-9)
near('rcond of a decomposition; rank of cod; isIllConditioned', (W['rc'], W['rk'], W['il']), (1 / np.linalg.cond(An, 1), 1, 1), 1e-10)
raises("decomposition(ones(3, 2), 'chol')", 'square matrix')

As, Bs, Cs = rs.standard_normal((3, 3)), rs.standard_normal((2, 2)) + 4 * np.eye(2), rs.standard_normal((3, 2))
W, _ = run(f"X = sylvester({mat(As)}, {mat(Bs)}, {mat(Cs)});")
near('sylvester as scipy.linalg.solve_sylvester', W['X'], sla.solve_sylvester(As, Bs, Cs), 1e-10)
A2 = np.column_stack([np.ones(6), np.arange(1, 7.0)])
b2 = np.array([[1.1], [1.9], [3.2], [3.9], [5.1], [6.2]])
w2 = np.array([1, 2, 1, 2, 1, 3.0])
Wm = np.diag(w2)
xr = np.linalg.solve(A2.T @ Wm @ A2, A2.T @ Wm @ b2)
res = b2 - A2 @ xr
mse = float((res.T @ Wm @ res)[0, 0]) / 4
Sr = np.linalg.inv(A2.T @ Wm @ A2) * mse
W, _ = run(f"[x, stdx, mse, S] = lscov({mat(A2)}, {mat(b2)}, {mat(w2)}'); xv = lscov({mat(A2)}, {mat(b2)}, diag(1 ./ {mat(w2)}));")
near('lscov: the weighted normal equations, mse, the covariance and its square roots; V = inv(W) the same',
     (W['x'], W['mse'], W['S'], W['stdx'], W['xv']), (xr, mse, Sr, np.sqrt(np.diag(Sr)).reshape(-1, 1), xr), 1e-10)
M6 = rs.standard_normal((40, 40))
W, _ = run(f"c1 = normest1(magic(6)); c2 = normest1({mat(M6)}); [c3, v, w] = normest1({mat(M6)});")
near('normest1: exact for magic(6) and a lower bound for a random matrix; w = A*v and |w|_1 = c*|v|_1',
     (W['c1'], float(W['c2']) <= np.linalg.norm(M6, 1) + 1e-12, np.abs(a(W['w'])).sum() / np.abs(a(W['v'])).sum(), a(W['w']) - M6 @ a(W['v'])),
     (np.linalg.norm(np.array([[35, 1, 6, 26, 19, 24], [3, 32, 7, 21, 23, 25], [31, 9, 2, 22, 27, 20], [8, 28, 33, 17, 10, 15],
                               [30, 5, 34, 12, 14, 16], [4, 36, 29, 13, 18, 11.0]]), 1), 1, float(W['c3']), np.zeros((40, 1))), 1e-10)
Pa, Pb = rs.standard_normal((5, 2)), rs.standard_normal((5, 3))
W, _ = run(f"t = subspace({mat(Pa)}, {mat(Pb)}); t2 = subspace([1; 0; 0], [1; 1; 0]);")
near('subspace: the largest principal angle, as scipy.linalg.subspace_angles', (W['t'], W['t2']), (sla.subspace_angles(Pa, Pb).max(), math.pi / 4), 1e-10)
Ae = np.array([[1.0, 1000], [0, 2]])
w_, vl, vr = sla.eig(Ae, left=True, right=True)
cref = 1 / np.abs(np.sum(vl.conj() * vr, axis=0))
W, _ = run(f"c = condeig({mat(Ae)}); [V, D] = eig([1 2; -2 1]); [Vr, Dr] = cdf2rdf(V, D); r = norm([1 2; -2 1]*Vr - Vr*Dr); im = isreal(Dr);")
near("condeig as 1/|w'*v| of scipy.linalg.eig's unit left and right vectors; cdf2rdf keeps A*V = V*D, real",
     (np.sort(a(W['c']).reshape(-1)), W['r'], W['im']), (np.sort(cref), 0, 1), 1e-9)
W, _ = run("ok = true; for n = [1 2 4 8 12 20 24 40 80], H = hadamard(n); ok = ok && isequal(H'*H, n*eye(n)) && all(abs(H(:)) == 1); end; hs = class(hadamard(4, 'single'));")
same("hadamard: H'*H = n*I for n, n/12 and n/20 powers of 2", (bool(W['ok']), W['hs'].str()), (True, 'single'))
raises('hadamard(6)', '2^k, 12*2^k or 20*2^k')

# ---- scattered data ------------------------------------------------------------------------------------------------------
P3 = rs.random_sample((20, 3))
W, _ = run(f"T = delaunayn({mat(P3)}); [K, V] = convhulln({mat(P3)}); P = [0 0; 1 0; 0 1; 1 1]; v = P(:,1) + 2*P(:,2);"
           f"vq = griddatan(P, v, [0.5 0.5; 0.2 0.7; 2 2]); vn = griddatan(P, v, [0.1 0.1; 0.9 0.8], 'nearest');")
dref = Delaunay(P3, qhull_options='Qt Qbb Qc Qz')
same('delaunayn: the simplices scipy.spatial.Delaunay gives', sorted(map(tuple, np.sort(a(W['T']).astype(int) - 1, axis=1).tolist())),
     sorted(map(tuple, np.sort(dref.simplices, axis=1).tolist())))
near('convhulln: the volume as scipy.spatial.ConvexHull', W['V'], ConvexHull(P3).volume, 1e-12)
near('griddatan: a linear function exact inside, NaN outside; nearest', (W['vq'], W['vn']), ([[1.5], [1.6], [np.nan]], [[0], [3]]), 1e-12)

# ---- nonuniform Fourier transforms --------------------------------------------------------------------------------------
x8 = rs.random_sample(8)
X34 = rs.random_sample((3, 4))
t5, f3 = np.array([0, 1, 2, 4, 5.0]), np.array([0, 0.1, 0.25])
W, _ = run(f"y1 = nufft({mat(x8)}); y2 = nufft({mat(x8[:5])}, {mat(t5)}, {mat(f3)}); y3 = nufftn({mat(X34)}); y4 = nufftn([1 2 3]', [0; 0.5; 2], [0.25; 1]);")
got = [np.asarray(W[k]) for k in ('y1', 'y2', 'y3', 'y4')]
want = [np.fft.fft(x8).reshape(1, -1), (np.exp(-2j * np.pi * np.outer(f3, t5)) @ x8[:5]).reshape(1, -1), np.fft.fft2(X34),
        (np.exp(-2j * np.pi * np.outer([0.25, 1], [0, 0.5, 2])) @ [1, 2, 3.0]).reshape(-1, 1)]
near('nufft: fft with the defaults; the direct sum otherwise; nufftn: fftn; points in one dimension (real and imaginary parts)',
     tuple(z.real for z in got) + tuple(z.imag for z in got), tuple(z.real for z in want) + tuple(z.imag for z in want), 1e-10)

# ---- sparse orderings ---------------------------------------------------------------------------------------------------
Sx = np.array([[1, 1, 1], [0, 1, 0], [1, 1, 0.0]])
pat = np.array([[1, 1, 0, 1, 0], [1, 1, 1, 0, 0], [0, 1, 1, 0, 1], [1, 0, 0, 1, 1], [0, 0, 1, 1, 1.0]])
Aspd = pat * rs.random_sample((5, 5))
Aspd = (Aspd + Aspd.T) / 2 + 10 * np.eye(5)
Lc = np.linalg.cholesky(Aspd)
W, _ = run(f"j = colperm(sparse({mat(Sx)})); [cnt, h, par, post, R] = symbfact(sparse({mat(Aspd)})); Rf = full(R); et = etree(sparse({mat(Aspd)}));")
near('colperm: the columns by their nonzeros, fewest first', W['j'], [[3, 1, 2]])
near("symbfact: R's structure and row counts those of chol (Cholesky of a matrix with that pattern), parent etree's",
     (W['cnt'], W['Rf'], W['par']), (np.sum(np.abs(Lc) > 1e-14, axis=0).reshape(-1, 1), (np.abs(Lc.T) > 1e-14).astype(float), a(W['et'])))
C('symbfact: post is a postorder (children before parents)', all(list(a(W['post']).reshape(-1)).index(k + 1) > max([list(a(W['post']).reshape(-1)).index(c + 1)
  for c in range(5) if int(a(W['par']).reshape(-1)[c]) == k + 1], default=-1) for k in range(5)), a(W['post']).tolist())

# ---- errors of a prediction ---------------------------------------------------------------------------------------------
F = rs.random_sample((4, 3))
Aa = rs.random_sample((4, 3)) + 0.5
W, _ = run(f"F = {mat(F)}; A = {mat(Aa)}; r1 = rmse(F, A); r2 = rmse(F, A, 'all'); r3 = rmse(F, A, 2); r4 = rmse([1 NaN 3], [1 2 4], 'omitmissing'); "
           f"m1 = mape(F, A); r5 = rmse([1 2 3], [2 2 2], 'Weights', [1 0 1]);")
near('rmse along columns, all, rows, omitting NaN, weighted; mape', (W['r1'], W['r2'], W['r3'], W['r4'], W['r5'], W['m1']),
     (np.sqrt(np.mean((F - Aa) ** 2, axis=0)).reshape(1, -1), np.sqrt(np.mean((F - Aa) ** 2)), np.sqrt(np.mean((F - Aa) ** 2, axis=1)).reshape(-1, 1),
      math.sqrt(0.5), 1.0, (100 * np.mean(np.abs((Aa - F) / Aa), axis=0)).reshape(1, -1)), 1e-12)

sys.exit(C.done())
