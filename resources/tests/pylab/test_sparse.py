"""Sparse matrices, run natively (CPython with numpy and scipy): making
them, which results stay sparse, indexing and assignment, the functions
that keep them sparse, linear algebra (SuperLU, ARPACK), orderings,
incomplete factors, iterative solvers, display, whos and the validators.
The expected values are worked out here by hand, from identities, or with
NumPy and SciPy on the same matrices.

    python3 test_sparse.py          (from any folder)
"""
import asyncio
import os
import sys
import tempfile

import numpy as np
import scipy.sparse as sps

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char, Sparse, class_of  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-sparse-')


def run(code):
    R.BASE.clear()
    R.BASE.gnames.clear()
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


def full(x):
    if type(x) is Sparse:
        return x.dense()
    if isinstance(x, (bool, float, int, complex)):
        return np.array([[x]])
    return np.asarray(x)


def near(label, got, want, tol=1e-9):
    g = full(got)
    w = np.asarray(want)
    if w.ndim < 2:
        w = w.reshape(g.shape) if w.size == g.size else w
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {g.tolist()}, want {w.tolist()}')


def sparse_of(label, x, kind='double'):
    """x is sparse and of the class kind."""
    return C(label, type(x) is Sparse and class_of(x) == kind, f'got {type(x).__name__} {class_of(x)}')


def full_of(label, x):
    return C(label, type(x) is not Sparse, f'got {type(x).__name__}')


def text(x):
    return x.str() if isinstance(x, Char) else x


A0 = np.array([[4.0, 0, 1], [0, 0, 2], [3, 0, 0]])

# ---- making sparse matrices -------------------------------------------------------------------------
W, out = run("""S = sparse([1 3 1 2], [1 1 3 3], [4 3 1 2]);
D = sparse([1 1 2], [1 1 2], [2 5 7]);
L = sparse([1 1 2], [1 1 2], [true true false]);
Z = sparse(2, 3); F = sparse([1 0; 0 2]); E = speye(3); E2 = speye(2, 3);
k = issparse(S); kf = issparse(full(S)); n = nnz(S); nz = nzmax(S); nz0 = nzmax(Z); c = class(L); sz = size(Z);
B = spones(S); V = spconvert([1 1 5; 3 2 6; 4 4 0]); P = spalloc(3, 4, 10); Q = spzeros(2);
nzv = nonzeros(S); fz = full(Z);""")
sparse_of('sparse(i, j, v) is sparse', W['S'])
near('sparse(i, j, v): the values in their places', W['S'], A0)
near('values given for one place are added', W['D'], [[7, 0], [0, 7]])
sparse_of('logical values make a sparse logical', W['L'], 'logical')
near('logical values for one place are combined by or', W['L'], [[1, 0], [0, 0]])
C('issparse, nnz and nzmax', W['k'] is True and W['kf'] is False and W['n'] == 4 and W['nz'] == 4 and W['nz0'] == 1, (W['k'], W['kf'], W['n'], W['nz'], W['nz0']))
near('sparse(m, n) has no nonzeros and the size asked', W['sz'], [[2, 3]])
near('speye and speye(m, n)', W['E2'], np.eye(2, 3))
near('spones', W['B'], (A0 != 0).astype(float))
near('spconvert: [i j v] rows, the last [m n 0] the size', W['V'], [[5, 0, 0, 0], [0, 0, 0, 0], [0, 6, 0, 0], [0, 0, 0, 0]])
sparse_of('spalloc and spzeros are sparse', W['P'])
near('nonzeros: the values in column order, a full column', W['nzv'], [[4], [3], [1], [2]])
full_of('nonzeros is full', W['nzv'])
full_of('full is full', W['fz'])

# ---- results that stay sparse, and those that do not ----------------------------------------------
W, out = run("""S = sparse([4 0 1; 0 0 2; 3 0 0]); F = [1 2 3; 4 5 6; 7 8 10];
a1 = S + S; a2 = S + F; a3 = S + 1; a4 = S - S; m1 = S .* F; m2 = F .* S; d1 = S ./ 2; d2 = 2 ./ S; p1 = S .^ 2; p2 = 2 .^ S;
x1 = S * S; x2 = S * F; x3 = F * S; x4 = 2 * S; t1 = S'; u1 = -S; c1 = S > 1; c2 = S == 0; c3 = ~S; c4 = S & F; c5 = S | 0;
k1 = [S F]; k2 = [F; S]; k3 = [S S]; i1 = S(1, :); i2 = S(2, 3); i3 = S(:); i4 = S([1 3], [1 3]); i5 = S(S > 1);""")
for name, want in (('a1', 'sparse'), ('a2', 'full'), ('a3', 'full'), ('a4', 'sparse'), ('m1', 'sparse'), ('m2', 'sparse'),
                   ('d1', 'sparse'), ('d2', 'full'), ('p1', 'sparse'), ('p2', 'full'), ('x1', 'sparse'), ('x2', 'full'), ('x3', 'full'),
                   ('x4', 'sparse'), ('t1', 'sparse'), ('u1', 'sparse'), ('k1', 'sparse'), ('k2', 'sparse'), ('k3', 'sparse'),
                   ('i1', 'sparse'), ('i2', 'sparse'), ('i3', 'sparse'), ('i4', 'sparse'), ('i5', 'sparse')):
    C(f'{name} is {want}', (type(W[name]) is Sparse) == (want == 'sparse'), type(W[name]).__name__)
for name in ('c1', 'c2', 'c3', 'c4', 'c5'):
    sparse_of(f'{name}: comparisons and logical operators give sparse logicals', W[name], 'logical')
F = np.array([[1.0, 2, 3], [4, 5, 6], [7, 8, 10]])
near('S + F', W['a2'], A0 + F)
near('S .* F', W['m1'], A0 * F)
with np.errstate(divide='ignore'):
    near('2 ./ S has Inf where S is zero', W['d2'], 2 / A0)
near('2 .^ S is 1 where S is zero', W['p2'], 2 ** A0)
near('S * S', W['x1'], A0 @ A0)
near('F * S', W['x3'], F @ A0)
near("S'", W['t1'], A0.T)
near('S == 0', W['c2'], A0 == 0)
near('[S F]', W['k1'], np.hstack([A0, F]))
near('S(:) is a column', W['i3'], A0.reshape(-1, 1, order='F'))
near('S(S > 1)', W['i5'], [[4], [3], [2]])
near('S(2, 3)', W['i2'], [[2]])

A2 = np.array([[4.0, 0, 1], [0, 2, 2], [3, 0, 0]])
W, out = run("""S = sparse([4 0 1; 0 2 2; 3 0 0]); b = [1; 2; 3];
x = S \\ b; X = S \\ speye(3); y = b' / S; r = S \\ S; w = S ^ 3; q = S(:, [1 3]) \\ b;""")
full_of('S \\ b with b full is full', W['x'])
near('S \\ b', W['x'], np.linalg.solve(A2, [1, 2, 3]).reshape(-1, 1))
sparse_of('S \\ S is sparse', W['X'])
near('S \\ speye(3) is the inverse', W['X'], np.linalg.inv(A2))
near("b' / S", W['y'], np.linalg.solve(A2.T, [1, 2, 3]).reshape(1, -1))
near('S ^ 3', W['w'], np.linalg.matrix_power(A2, 3))
sparse_of('S ^ 3 is sparse', W['w'])
near('a rectangular sparse system by least squares', W['q'], np.linalg.lstsq(A2[:, [0, 2]], [1, 2, 3], rcond=None)[0].reshape(-1, 1))

W, out = run("""S = sparse([4 0 1; 0 0 2; 3 0 0]);
S(2, 2) = 5; a = S; S(4, 4) = 1; b = S; S(:, 2) = []; c = S; T = sparse(2, 2); T(1, :) = [7 8]; G = zeros(2); G(1, 1) = sparse(3);
s = 0; for col = sparse([1 2; 3 4]), s = s + sum(col); k = issparse(col); end
try, Q = sparse([1 2]); Q(:, :, 2) = 1; catch e, m3 = e.message; end""")
sparse_of('assignment keeps a sparse matrix sparse', W['a'])
near('S(2, 2) = 5', W['a'], A0 + np.diag([0, 5, 0]))
near('assignment past the end grows the matrix', W['b'], np.pad(A0 + np.diag([0, 5, 0]), ((0, 1), (0, 1))) + np.diag([0, 0, 0, 1]))
near("S(:, 2) = [] deletes a column", W['c'], [[4, 1, 0], [0, 2, 0], [3, 0, 0], [0, 0, 1]])
near('a row put in an all-zero sparse matrix', W['T'], [[7, 8], [0, 0]])
full_of('a full matrix stays full when a sparse value is put in it', W['G'])
C('for loops over the columns of a sparse matrix, each sparse', W['s'] == 10 and W['k'] is True, (W['s'], W['k']))
C('a third dimension is refused', '2-D' in text(W.get('m3', '')), W.get('m3'))

# ---- functions that keep sparse matrices sparse -----------------------------------------------------
W, out = run("""S = sparse([4 0 -1; 0 0 2; 9 0 0]);
f1 = abs(S); f2 = sqrt(S); f3 = sin(S); f4 = cos(S); f5 = round(S / 3); f6 = mod(S, 2); f7 = isnan(S); f8 = spfun(@exp, S);
r1 = sum(S); r2 = sum(S, 2); r3 = any(S); r4 = all(S); r5 = max(S); [r6, i6] = max(S, [], 2); r7 = cumsum(S); r8 = mean(S);
r9 = prod(S); [I, J, V] = find(S); g1 = diag(S); g2 = diag(sparse([1 2])); g3 = tril(S); g4 = triu(S, 1); g5 = kron(S, speye(2));
g6 = reshape(S, 1, 9); g7 = repmat(S, 1, 2); g8 = blkdiag(S, sparse(1)); g9 = trace(S); e1 = isequal(S, full(S)); e2 = isequal(S, S');
n1 = double(S > 1); n2 = logical(S); n3 = flipud(S); n4 = diff(S); n5 = S(:, end:-1:1); n6 = nnz(S > 0);
try, single(S); catch e, m1 = e.message; end
try, int8(S); catch e, m2 = e.message; end""")
A1 = np.array([[4.0, 0, -1], [0, 0, 2], [9, 0, 0]])
for name in ('f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f8', 'r1', 'r2', 'r5', 'r7', 'r8', 'r9', 'g1', 'g2', 'g3', 'g4', 'g5', 'g6', 'g7', 'g8', 'n1', 'n3', 'n4', 'n5'):
    sparse_of(f'{name} stays sparse', W[name])
for name in ('f7', 'r3', 'r4', 'n2'):
    sparse_of(f'{name} is a sparse logical', W[name], 'logical')
near('sqrt of a negative element is complex', W['f2'], np.sqrt(A1.astype(complex)))
near('cos: 1 where S is zero', W['f4'], np.cos(A1))
near('round(S / 3)', W['f5'], np.round(A1 / 3))
near('mod(S, 2)', W['f6'], np.mod(A1, 2))
near('spfun works on the nonzeros alone', W['f8'], np.where(A1 != 0, np.exp(A1), 0))
near('sum and sum(S, 2)', (W['r1']), A1.sum(axis=0, keepdims=True))
near('sum(S, 2)', W['r2'], A1.sum(axis=1, keepdims=True))
near('any and all', W['r4'], [[False, False, False]])
near('[m, i] = max(S, [], 2)', W['i6'], [[1], [3], [1]])
full_of('the index of max is full', W['i6'])
near('cumsum', W['r7'], np.cumsum(A1, axis=0))
near('mean', W['r8'], A1.mean(axis=0, keepdims=True))
near('[I, J, V] = find(S), in column order', np.hstack([full(W['I']), full(W['J']), full(W['V'])]), [[1, 1, 4], [3, 1, 9], [1, 3, -1], [2, 3, 2]])
near('diag of a sparse vector is a sparse matrix', W['g2'], [[1, 0], [0, 2]])
near('triu(S, 1)', W['g4'], np.triu(A1, 1))
near('kron(S, speye(2))', W['g5'], np.kron(A1, np.eye(2)))
near('reshape', W['g6'], A1.reshape(1, 9, order='F'))
near('blkdiag', W['g8'], np.block([[A1, np.zeros((3, 1))], [np.zeros((1, 3)), np.ones((1, 1))]]))
C('trace is a number; isequal compares the values, sparse or full', W['g9'] == 4 and W['e1'] is True and W['e2'] is False, (W['g9'], W['e1'], W['e2']))
near('diff', W['n4'], np.diff(A1, axis=0))
C('single and the integer classes refuse a sparse matrix', 'full' in text(W.get('m1', '')) and 'full' in text(W.get('m2', '')), (W.get('m1'), W.get('m2')))
C('nnz of a sparse logical', W['n6'] == 3, W['n6'])

# ---- display and whos --------------------------------------------------------------------------------
W, out = run("""S = sparse([1 12], [1 3], [5 -6.5])
Z = sparse(2, 3)
L = sparse([1 2], [2 1], [true true])""")
C('display: the size, class and count of nonzeros', '  12×3 sparse double matrix (2 nonzeros)' in out, out)
C('display: an entry per nonzero, the row indices aligned', '   ( 1,1)      5.0000\n   (12,3)     -6.5000' in out, out)
C('display: an all-zero sparse matrix', '   All zero sparse: 2×3' in out, out)
C('display: a sparse logical', '  2×2 sparse logical matrix (2 nonzeros)' in out and '   (2,1)       1\n   (1,2)       1' in out, out)
W, out = run("""S = speye(5); L = S > 0; Z = sparse([1i 0; 0 2]); whos
w = whos('S'); k = w.sparse; b = w.bytes;""")
C('whos: the sparse attribute', 'sparse' in out and 'sparse, complex' in out, out)
C('whos: the bytes of compressed columns (16 per nonzero, 8 per column and one more)', W['k'] is True and W['b'] == 5 * 16 + 6 * 8, (W['k'], W['b']))

# ---- linear algebra ----------------------------------------------------------------------------------
T = np.diag(4.0 * np.ones(6)) + np.diag(-np.ones(5), 1) + np.diag(-2 * np.ones(5), -1)
T[0, 5] = 0.5
W, out = run("""A = sparse(diag(4*ones(6, 1)) + diag(-ones(5, 1), 1) + diag(-2*ones(5, 1), -1)); A(1, 6) = 0.5;
Y = inv(A); d = det(A); d0 = det(sparse([1 2; 2 4]));
[L2, U2] = lu(A); e2 = norm(full(L2*U2 - A), 1);
[L3, U3, P3] = lu(A); e3 = norm(full(P3*A - L3*U3), 1); t3 = istril(L3);
[L4, U4, P4, Q4] = lu(A); e4 = norm(full(P4*A*Q4 - L4*U4), 1);
[L5, U5, p5] = lu(A, 'vector'); e5 = norm(full(A(p5, :) - L5*U5), 1);
R = sparse([1 2; 3 4; 5 6]); [L6, U6, P6] = lu(R); e6 = norm(full(P6*R - L6*U6), 1); k6 = issparse(L6);
n1 = norm(A, 1); ni = norm(A, inf); nf = norm(A, 'fro'); n2 = norm(A); nv = norm(sparse([3 0 4])); c1 = condest(A);
E = expm(sparse([0 1; 0 0])); ks = [issparse(Y) issparse(L2) issparse(P3) issparse(E)];
try, inv(sparse([1 2; 2 4])); catch e, mi = e.message; end""")
near('inv of a sparse matrix', W['Y'], np.linalg.inv(T))
near('det', W['d'], np.linalg.det(T))
C('det of a singular sparse matrix is 0', W['d0'] == 0, W['d0'])
C('[L, U] = lu(S): L*U = S', W['e2'] < 1e-12, W['e2'])
C('[L, U, P] = lu(S): P*S = L*U, L lower triangular', W['e3'] < 1e-12 and W['t3'] is True, (W['e3'], W['t3']))
C('[L, U, P, Q] = lu(S): P*S*Q = L*U', W['e4'] < 1e-12, W['e4'])
C("lu(S, 'vector'): S(p, :) = L*U", W['e5'] < 1e-12, W['e5'])
C('lu of a rectangular sparse matrix, its factors sparse', W['e6'] < 1e-12 and W['k6'] is True, (W['e6'], W['k6']))
near('norm(S, 1), norm(S, Inf), norm(S, fro), norm(S)', np.array([[W['n1'], W['ni'], W['nf'], W['n2']]]),
     [[np.linalg.norm(T, 1), np.linalg.norm(T, np.inf), np.linalg.norm(T, 'fro'), np.linalg.norm(T, 2)]])
C('norm of a sparse vector', W['nv'] == 5, W['nv'])
near('condest of a small sparse matrix is cond(A, 1)', W['c1'], np.linalg.cond(T, 1), 1e-9)
near('expm of a sparse matrix', W['E'], [[1, 1], [0, 1]])
near('inv, lu, the permutation and expm give sparse results', W['ks'], [[1, 1, 1, 1]])

W, out = run("""n = 1000; e = ones(n, 1); A = spdiags([-e 2*e -e], -1:1, n, n);
d = eigs(A, 3); ds = eigs(A, 3, 'smallestabs'); dn = eigs(A, 2, 1.5); [V, D, fl] = eigs(A, 2); r = norm(A*V - V*D);
s = svds(A, 2); sn = svds(A, 1, 1.9); fh = eigs(@(x) A*x, n, 2, 'largestreal');
B = sparse([2 1 0; 1 3 0; 0 0 1]); db = eigs(B, 2); dsm = eigs(B, 1, 'smallestreal');
nn = normest(sparse([3 0; 0 4]));""")
lam = 2 - 2 * np.cos(np.arange(1, 1001) * np.pi / 1001)
near('eigs of a large sparse matrix (ARPACK): the largest', W['d'], lam[::-1][:3].reshape(-1, 1), 1e-8)
near("eigs(A, k, 'smallestabs')", W['ds'], lam[:3].reshape(-1, 1), 1e-8)
near('eigs(A, k, sigma): the nearest to sigma', np.sort(full(W['dn']), axis=0), np.sort(lam[np.argsort(np.abs(lam - 1.5))[:2]]).reshape(-1, 1), 1e-8)
C('[V, D, flag] = eigs: A*V = V*D, flag 0', W['r'] < 1e-8 and W['fl'] == 0, (W['r'], W['fl']))
near('svds of a large sparse matrix', W['s'], lam[::-1][:2].reshape(-1, 1), 1e-8)
near('svds(A, k, sigma): the singular value nearest sigma', W['sn'], lam[np.argmin(np.abs(lam - 1.9))], 1e-8)
near('eigs of a function handle', W['fh'], lam[::-1][:2].reshape(-1, 1), 1e-8)
near('eigs of a small sparse matrix', W['db'], np.sort(np.linalg.eigvalsh([[2, 1, 0], [1, 3, 0], [0, 0, 1]]))[::-1][:2].reshape(-1, 1))
near("eigs(B, 1, 'smallestreal')", W['dsm'], 1.0)
near('normest', W['nn'], 4.0, 1e-6)

# ---- orderings, structure and incomplete factors -----------------------------------------------------
W, out = run("""n = 40; p0 = [1:2:n, 2:2:n]; A = spdiags(ones(n, 3), -1:1, n, n); B = A(p0, p0);
r = symrcm(B); [lo0, up0] = bandwidth(B); [lo1, up1] = bandwidth(B(r, r)); ok = isequal(sort(r), 1:n);
pa = amd(B); pc = colamd(B); pok = isequal(sort(pa), 1:n) && isequal(sort(pc), 1:n);
L = chol(A(1:5, 1:5) + 2*speye(5), 'lower'); ch = nnz(L);
[pt, q] = etree(sparse([1 0 1; 0 1 1; 1 1 1])); m = dmperm(sparse([0 1 0; 1 0 0; 0 1 1])); sr = sprank(sparse([1 1 0; 1 1 0; 0 0 0]));
T = spdiags([-ones(n, 1) 4*ones(n, 1) -ones(n, 1)], -1:1, n, n); Li = ichol(T); ei = norm(full(Li*Li' - T), 1);
[Lu, Uu] = ilu(T); eu = norm(full(Lu*Uu - T), 1); M = sparse([4 1 0; 1 4 1; 1 0 4]); [L0, U0] = ilu(M); P0 = L0*U0;
G = spaugment(sparse([1; 2]), 1); sym1 = issymmetric(T); sym2 = issymmetric(T + sparse(1, 2, 1, n, n));
hn = ishermitian(sparse([1 1i; -1i 2])); tl = istril(tril(T)); bw = isbanded(T, 1, 1);
try, ichol(sparse([1 2; 2 1])); catch e, mc = e.message; end""")
C('symrcm: a permutation that brings the band back', W['ok'] is True and W['lo1'] <= 2 and W['up1'] <= 2 and W['lo0'] > 10, (W['lo0'], W['lo1'], W['up1']))
C('amd and colamd: permutations of 1:n', W['pok'] is True, W['pok'])
near('etree: the parent of each column', W['pt'], [[3, 3, 0]])
near('etree: a postorder', W['q'], [[1, 2, 3]])
near('dmperm: the row matched to each column', W['m'], [[2, 1, 3]])
C('sprank', W['sr'] == 2, W['sr'])
C('ichol of a tridiagonal matrix is exact (no fill is needed)', W['ei'] < 1e-12, W['ei'])
C('ilu of a tridiagonal matrix is exact', W['eu'] < 1e-12, W['eu'])
P0 = full(W['P0'])
Mf = np.array([[4.0, 1, 0], [1, 4, 1], [1, 0, 4]])
C("ilu with no fill: L*U equals A on A's pattern", np.allclose(P0[Mf != 0], Mf[Mf != 0]) and abs(P0[2, 1]) > 0, P0.tolist())
near('spaugment', W['G'], [[1, 0, 1], [0, 1, 2], [1, 2, 0]])
C('issymmetric, ishermitian, istril and isbanded read a sparse matrix', W['sym1'] is True and W['sym2'] is False and W['hn'] is True and W['tl'] is True and W['bw'] is True,
  (W['sym1'], W['sym2'], W['hn'], W['tl'], W['bw']))
C('ichol refuses a pivot that is not positive', 'pivot' in text(W.get('mc', '')), W.get('mc'))

W, out = run("""A1 = sparse([0.37 -0.05 -0.05 -0.07; -0.05 0.116 0 -0.05; -0.05 0 0.116 -0.05; -0.07 -0.05 -0.05 0.202]); e = ones(4, 1);
L0 = ichol(A1); o.michol = 'on'; Lm = ichol(A1, o); o.shape = 'upper'; Um = ichol(A1, o);
t.type = 'ict'; t.droptol = 0; Lt = ichol(A1, t); t.droptol = 0.1; Ld = ichol(A1, t); dc.diagcomp = 0.5; Lc = ichol(A1, dc);
Z = sparse([2 1i; -1i 3]); Lz = ichol(Z); r0 = full(Z(1, 2) + Z(1, 2)); zz = Z - Z; ks = issparse(zz);
try, ichol(sparse([1i 0; 0 1])); catch err, m1 = err.message; end
try, q.type = 'other'; ichol(A1, q); catch err, m2 = err.message; end
n = 30; e30 = ones(n, 1); T = spdiags([-e30 4*e30 -e30], -1:1, n, n); T(1, n) = -1; T(n, 1) = -1;
c.type = 'crout'; c.droptol = 0; [Lc0, Uc0] = ilu(T, c); c.droptol = 1e-3; c.milu = 'row'; [Lr, Ur] = ilu(T, c); c.milu = 'col'; [Lk, Uk] = ilu(T, c);
M = sparse([1 2 0; 4 1 0; 0 0 3]); p.type = 'ilutp'; p.thresh = 1; [Lp, Up, Pp] = ilu(M, p); [Lq, Uq] = ilu(M, p); W1 = ilu(M, p);
p.thresh = 0; [L0p, U0p, P0p] = ilu(M, p);
try, ilu(sparse([0 1; 1 0])); catch err, m3 = err.message; end
u.type = 'ilutp'; u.udiag = 1; u.droptol = 0.1; u.thresh = 0; [Lu, Uu] = ilu(sparse([0 1; 1 0]), u);
try, ilu(eye(2)); catch err, m4 = err.message; end""")
A1 = np.array([[0.37, -0.05, -0.05, -0.07], [-0.05, 0.116, 0, -0.05], [-0.05, 0, 0.116, -0.05], [-0.07, -0.05, -0.05, 0.202]])
L0, Lm, Um, Lt, Ld, Lc = (full(W[k]) for k in ('L0', 'Lm', 'Um', 'Lt', 'Ld', 'Lc'))
C('ichol with no fill: L*L\' equals A on the pattern of its lower triangle', np.allclose((L0 @ L0.T)[np.tril(A1) != 0], np.tril(A1)[np.tril(A1) != 0]) and np.all(L0[np.tril(A1) == 0] == 0), L0.tolist())
C("michol 'on': L*L' keeps A's row sums", np.allclose(Lm @ Lm.T @ np.ones(4), A1 @ np.ones(4)) and not np.allclose(Lm, L0), Lm.tolist())
C("shape 'upper' gives L'", np.allclose(Um, Lm.T), Um.tolist())
C("'ict' with droptol 0 is the full Cholesky factor", np.allclose(Lt, np.linalg.cholesky(A1)), Lt.tolist())
C("'ict' drops small entries", np.count_nonzero(Ld) < np.count_nonzero(Lt) and np.allclose(np.diag(Ld @ Ld.T)[:1], A1[0, 0]), np.count_nonzero(Ld))
C('diagcomp factors A + alpha*diag(diag(A))', np.allclose((Lc @ Lc.T)[np.tril(A1) != 0], (np.tril(A1) + 0.5 * np.diag(np.diag(A1)))[np.tril(A1) != 0]), Lc.tolist())
Lz = full(W['Lz'])
C('ichol of a Hermitian matrix: L*L\' is the matrix', np.allclose(Lz @ Lz.conj().T, [[2, 1j], [-1j, 3]]), Lz.tolist())
C('complex sparse values keep their imaginary parts through + and -', W['r0'] == 2j and W['ks'] is True and W['zz'].nnz == 0, (W['r0'], W['ks']))
C('ichol: a pivot that is not real, and an unknown type, are errors', 'not real' in text(W.get('m1', '')) and 'nofill' in text(W.get('m2', '')), (W.get('m1'), W.get('m2')))
T30 = np.diag(4.0 * np.ones(30)) - np.diag(np.ones(29), 1) - np.diag(np.ones(29), -1)
T30[0, 29] = T30[29, 0] = -1
Lc0, Uc0 = full(W['Lc0']), full(W['Uc0'])
C("ilu 'crout' with droptol 0 is the exact LU, L unit lower and U upper", np.allclose(Lc0 @ Uc0, T30) and np.allclose(np.diag(Lc0), 1) and np.allclose(Lc0, np.tril(Lc0)) and np.allclose(Uc0, np.triu(Uc0)))
C("milu 'row' keeps the row sums, 'col' the column sums", np.allclose(full(W['Lr']) @ full(W['Ur']) @ np.ones(30), T30 @ np.ones(30))
  and np.allclose(np.ones(30) @ full(W['Lk']) @ full(W['Uk']), np.ones(30) @ T30) and np.count_nonzero(full(W['Lr'])) + np.count_nonzero(full(W['Ur'])) < np.count_nonzero(Lc0) + np.count_nonzero(Uc0))
Mf = np.array([[1.0, 2, 0], [4, 1, 0], [0, 0, 3]])
Lp, Up, Pp = full(W['Lp']), full(W['Up']), full(W['Pp'])
C("ilu 'ilutp' pivots: P*A = L*U, the larger row first", np.allclose(Pp @ Mf, Lp @ Up) and Pp[0, 1] == 1 and np.allclose(Lp, np.tril(Lp)), (Pp.tolist(), Lp.tolist()))
C("[L, U] = ilu: L carries P's rows; W = ilu(A) is L + U - I", np.allclose(full(W['Lq']) @ full(W['Uq']), Mf) and np.allclose(full(W['W1']), Lp + Up - np.eye(3)))
C('thresh 0 keeps the diagonal rows', np.allclose(full(W['P0p']), np.eye(3)) and np.allclose(full(W['L0p']) @ full(W['U0p']), Mf))
C('ilu: a zero pivot is an error; udiag replaces it; a full matrix is refused', 'zero pivot' in text(W.get('m3', '')) and full(W['Uu'])[0, 0] != 0 and 'sparse' in text(W.get('m4', '')),
  (W.get('m3'), full(W['Uu']).tolist(), W.get('m4')))

# ---- iterative solvers and large matrices -----------------------------------------------------------
W, out = run("""n = 50000; e = ones(n, 1); A = spdiags([-e 4*e -e], -1:1, n, n); b = A*e;
[x1, f1] = pcg(A, b, 1e-10, 200); L = ichol(A); [x2, f2, ~, it2] = pcg(A, b, 1e-10, 200, L, L');
[x3, f3] = gmres(A, b, 10, 1e-10, 20); [Li, Ui] = ilu(A); [x4, f4] = bicgstab(A, b, 1e-10, 50, Li, Ui);
R = A(:, 1:200); [x5, f5] = lsqr(R, R*ones(200, 1), 1e-12, 500);
x6 = A \\ b; e6 = max(abs(x6 - 1)); I = speye(100000); s = sum(I(:)); ni = nnz(I); y = I * ones(100000, 1);
try, full(speye(100000)); catch err, mf = err.message; end""")
C('pcg on a 50000-row sparse matrix', W['f1'] == 0 and np.max(np.abs(full(W['x1']) - 1)) < 1e-6, W['f1'])
C('pcg with an incomplete Cholesky preconditioner converges in a few steps', W['f2'] == 0 and W['it2'] < 10, (W['f2'], W['it2']))
C('gmres and bicgstab (with ilu) on a sparse matrix', W['f3'] == 0 and W['f4'] == 0 and np.max(np.abs(full(W['x4']) - 1)) < 1e-6, (W['f3'], W['f4']))
C('lsqr on a sparse rectangular matrix', W['f5'] == 0 and np.max(np.abs(full(W['x5']) - 1)) < 1e-6, W['f5'])
C('backslash on a 50000-row sparse matrix', W['e6'] < 1e-10, W['e6'])
C('a 100000-by-100000 identity: sum, nnz and a product without making it full', full(W['s']).item() == 100000 and W['ni'] == 100000 and full(W['y']).shape == (100000, 1),
  (W['s'], W['ni']))
C('full of a matrix too large is refused', 'memory' in text(W.get('mf', '')).lower(), W.get('mf'))

# ---- random sparse matrices, spdiags -----------------------------------------------------------------
W, out = run("""rng(3); R = sprand(100, 200, 0.05); nr = nnz(R); mx = max(R(:)); mn = min(nonzeros(R));
Rn = sprandn(50, 50, 0.1); nn = nnz(Rn); Rs = sprandsym(60, 0.1); sy = isequal(Rs, Rs'); P = sprand(sparse([1 0; 0 1])); pp = nnz(P);
B = [1 2 3; 4 5 6; 7 8 9]; S = spdiags(B, [-1 0 1], 3, 3); [Bx, dx] = spdiags(S); W2 = spdiags([10; 20; 30], 0, S);""")
C('sprand: round(density*m*n) values in (0, 1)', W['nr'] == 1000 and 0 < W['mn'] and full(W['mx']).item() < 1, (W['nr'], W['mn']))
C('sprandn and sprandsym: the counts and the symmetry', W['nn'] == 250 and W['sy'] is True and W['pp'] == 2, (W['nn'], W['sy'], W['pp']))
near('spdiags(B, d, m, n): each column of B by the column of S it lands in', W['S'], [[2, 6, 0], [1, 5, 9], [0, 4, 8]])
near('[B, d] = spdiags(S): the diagonals as columns', W['Bx'], [[1, 2, 0], [4, 5, 6], [0, 8, 9]])
near('[B, d] = spdiags(S): their numbers', W['dx'], [[-1], [0], [1]])
near('spdiags(B, d, A) replaces a diagonal', W['W2'], [[10, 6, 0], [1, 20, 9], [0, 4, 30]])

# ---- sparse values where the language takes any array ---------------------------------------------------
W, out = run("""S = sparse([3 0 1]); [v, i] = sort(S); t = sprintf('%g,', S); a = arrayfun(@(x) x*2, S); k = kron([1 2], S);
st.m = S; c = {S}; f = figure('Visible', 'off'); xlim(sparse([0 2])); xl = xlim; close(f); m = mat2str(S); j = jsonencode(S);
try, det(1, S); catch err, m1 = err.message; end
try, kron(S); catch err, m2 = err.message; end""")
sparse_of('sort keeps the values sparse', W['v'])
full_of('the indices of sort are full', W['i'])
C('sprintf reads a sparse matrix element by element', text(W['t']) == '3,0,1,', W['t'])
near('arrayfun over a sparse matrix, one element at a time', W['a'], [[6, 0, 2]])
sparse_of('kron with the sparse matrix second is sparse', W['k'])
near('a graphics limit given as a sparse vector', W['xl'], [[0, 2]])
C('mat2str and jsonencode of a sparse matrix', text(W['m']) == '[3 0 1]' and text(W['j']) == '[3,0,1]', (W.get('m'), W.get('j')))
C('wrong inputs with a sparse matrix are language errors', 'MATLAB:internal' not in out and W.get('m1') is not None and W.get('m2') is not None, (W.get('m1'), W.get('m2')))

# ---- validators and spy ------------------------------------------------------------------------------
W, out = run("""S = speye(2);
try, mustBeNonsparse(S); catch e, m1 = e.message; end
try, validateattributes(S, {'double'}, {'nonsparse'}); catch e, m2 = e.message; end
mustBeNonsparse(eye(2)); ok = 1;
f = figure('Visible', 'off'); h = spy(sparse([1 0 1; 0 1 0])); t = get(get(gca, 'XLabel'), 'String'); xd = get(h, 'XData'); yd = get(h, 'YData'); close(f);""")
C('mustBeNonsparse refuses a sparse matrix', 'sparse' in text(W.get('m1', '')), W.get('m1'))
C("validateattributes 'nonsparse' refuses a sparse matrix", 'nonsparse' in text(W.get('m2', '')), W.get('m2'))
C('a full matrix passes mustBeNonsparse', W.get('ok') == 1, W.get('ok'))
C('spy: a marker at each nonzero, nz under the axes', text(W.get('t')) == 'nz = 3' and sorted(zip(full(W['xd']).reshape(-1), full(W['yd']).reshape(-1))) == [(1, 1), (2, 2), (3, 1)],
  (W.get('t'), W.get('xd'), W.get('yd')))

sys.exit(C.done())
