"""gallery: Higham's test matrices, by name. Each is built from its
defining formula; the ones made of random numbers (rando, randsvd and the
data sets) come from this engine's generator, so their numbers are not
another program's."""
import math

import numpy as np

from . import bi
from ._util import err, darr, out, num, ival, opt_str
from ..values import F64, C128, numel
from .. import sparsemat as SPM


def _n_or_vec(v, fn):
    """A scalar n as 1:n, a vector as itself."""
    a = np.asarray(darr(v)).reshape(-1)
    if a.size == 1:
        return np.arange(1, int(a[0]) + 1, dtype=F64)
    return a


def _arg(args, k, default):
    return float(num(args[k])) if len(args) > k and numel(args[k]) else default


def _int(v, fn, what='n'):
    """A size: a whole number (a negative one gives an empty matrix)."""
    x = float(num(v))
    if x != int(x):
        raise err(f'MATLAB:gallery:{fn}', f'{what} must be a whole number.', 'gallery')
    return max(int(x), 0)


def _sparse(m):
    import scipy.sparse as sp
    return SPM.make(sp.csc_matrix(m))


def _tri(n, sub, diag, sup):
    import scipy.sparse as sp
    sub, diag, sup = (np.broadcast_to(np.asarray(x, F64).reshape(-1), (k,)) for x, k in ((sub, n - 1), (diag, n), (sup, n - 1)))
    return sp.diags([sub, diag, sup], [-1, 0, 1], shape=(n, n), format='csc')


def cauchy(x, y=None):
    x = _n_or_vec(x, 'cauchy')
    y = x if y is None else _n_or_vec(y, 'cauchy')
    with np.errstate(divide='ignore'):
        return 1.0 / (x.reshape(-1, 1) + y.reshape(1, -1))


def chebvand(*args):
    if len(args) == 1:
        p = np.asarray(darr(args[0])).reshape(-1)
        if p.size == 1:
            n = int(p[0])
            p = np.linspace(0, 1, n) if n > 1 else np.zeros(n)
        m = p.size
    else:
        m = _int(args[0], 'chebvand', 'm')
        p = np.asarray(darr(args[1])).reshape(-1)
        if p.size == 1:
            n = int(p[0])
            p = np.linspace(0, 1, n) if n > 1 else np.zeros(n)
    C = np.ones((m, p.size))
    if m > 1:
        C[1] = p
    for i in range(2, m):
        C[i] = 2 * p * C[i - 1] - C[i - 2]
    return C


def chow(n, alpha=1.0, delta=0.0):
    n = _int(n, 'chow')
    A = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if j <= i:
                A[i, j] = alpha ** (i - j + 1)
            elif j == i + 1:
                A[i, j] = 1.0
    return A + delta * np.eye(n)


def circul(v):
    v = _n_or_vec(v, 'circul')
    n = v.size
    i, j = np.indices((n, n))
    return v[(j - i) % n]


def clement(n, k=0):
    n = _int(n, 'clement')
    if n < 1:
        return np.zeros((n, n))
    x = np.arange(n - 1, 0, -1, dtype=F64)
    z = np.arange(1, n, dtype=F64)
    if k == 0:
        return np.diag(x, -1) + np.diag(z, 1)
    y = np.sqrt(x * z)
    return np.diag(y, -1) + np.diag(y, 1)


def compar(A, k=0):
    A = np.asarray(darr(A))
    if k != 0:
        raise err('MATLAB:gallery:compar', "Only compar(A) and compar(A, 0) are given here.", 'gallery')
    C = -np.abs(A)
    m = min(A.shape)
    C[np.arange(m), np.arange(m)] = np.abs(np.diag(A))
    return C


def fiedler(c):
    c = _n_or_vec(c, 'fiedler')
    return np.abs(c.reshape(-1, 1) - c.reshape(1, -1))


def forsythe(n, alpha=None, lam=0.0):
    n = _int(n, 'forsythe')
    A = jordbloc(n, lam)
    if n:
        A[n - 1, 0] = math.sqrt(np.finfo(float).eps) if alpha is None else alpha
    return A


def frank(n, k=0):
    n = _int(n, 'frank')
    i, j = np.indices((n, n)) + 1
    F = np.where(j >= i - 1, n + 1 - np.maximum(i, j), 0).astype(F64)
    if k == 1:
        F = F[::-1, ::-1].T.copy()
    return F


def gearmat(n, i=None, j=None):
    n = _int(n, 'gearmat')
    i = n if i is None else int(i)
    j = -n if j is None else int(j)
    if not (1 <= abs(i) <= n and 1 <= abs(j) <= n):
        raise err('MATLAB:gallery:gearmat', 'i and j must be between -n and n, not 0.', 'gallery')
    A = np.diag(np.ones(n - 1), -1) + np.diag(np.ones(n - 1), 1)
    A[0, abs(i) - 1] = np.sign(i)
    A[n - 1, n - abs(j)] = np.sign(j)
    return A


def grcar(n, k=3):
    n = _int(n, 'grcar')
    k = int(k)
    return np.tril(np.triu(np.ones((n, n))), k) - np.diag(np.ones(max(n - 1, 0)), -1)


def hanowa(n, d=-1.0):
    n = _int(n, 'hanowa')
    if n % 2:
        raise err('MATLAB:gallery:hanowa', 'n must be even.', 'gallery')
    m = n // 2
    D = np.diag(np.arange(1, m + 1, dtype=F64))
    I = np.eye(m)
    return np.block([[d * I, -D], [D, d * I]])


def ipjfact(n, k=0):
    n = _int(n, 'ipjfact')
    i, j = np.indices((n, n)) + 1
    A = np.vectorize(lambda s: float(math.factorial(s)))(i + j).astype(F64) if n else np.zeros((0, 0))
    return 1.0 / A if k == 1 else A


def jordbloc(n, lam=1.0):
    n = _int(n, 'jordbloc')
    return lam * np.eye(n) + np.diag(np.ones(max(n - 1, 0)), 1)


def kms(n, rho=0.5):
    n = _int(n, 'kms')
    i, j = np.indices((n, n))
    rho = complex(rho) if isinstance(rho, complex) else float(rho)
    A = np.power(rho, np.abs(i - j).astype(F64)) if not isinstance(rho, complex) else np.power(rho, np.abs(i - j).astype(complex))
    if isinstance(rho, complex):
        A = np.where(i > j, np.conj(A), A)
    return A


def krylov(A, x=None, j=None):
    from .elmat import RNG
    A = np.asarray(darr(A))
    if A.size == 1:
        n = int(A.reshape(-1)[0])
        A = RNG.rs.standard_normal((n, n))
    n = A.shape[0]
    x = np.ones(n) if x is None else np.asarray(darr(x)).reshape(-1)
    j = n if j is None else int(j)
    K = np.zeros((n, j), dtype=np.result_type(A, x, F64))
    v = x.astype(K.dtype)
    for k in range(j):
        K[:, k] = v
        v = A @ v
    return K


def lauchli(n, mu=None):
    n = _int(n, 'lauchli')
    mu = math.sqrt(np.finfo(float).eps) if mu is None else mu
    return np.vstack([np.ones((1, n)), mu * np.eye(n)])


def lehmer(n):
    n = _int(n, 'lehmer')
    i, j = np.indices((n, n)) + 1
    return np.minimum(i, j) / np.maximum(i, j)


def leslie(a, b=None):
    a = np.asarray(darr(a)).reshape(-1)
    if b is None:
        n = int(a[0])
        a, b = np.ones(n), np.ones(n - 1)
    else:
        b = np.asarray(darr(b)).reshape(-1)
    n = a.size
    if b.size != n - 1:
        raise err('MATLAB:gallery:leslie', 'b must have one element fewer than a.', 'gallery')
    A = np.diag(b, -1)
    A[0, :] = a
    return A


def lotkin(n):
    n = _int(n, 'lotkin')
    i, j = np.indices((n, n)) + 1
    A = 1.0 / (i + j - 1)
    if n:
        A[0, :] = 1.0
    return A


def minij(n):
    n = _int(n, 'minij')
    i, j = np.indices((n, n)) + 1
    return np.minimum(i, j).astype(F64)


def moler(n, alpha=-1.0):
    T = triw(n, alpha)
    return T.T @ T


def neumann(n):
    n = _int(n, 'neumann')
    m = int(round(math.sqrt(n)))
    if m * m != n:
        raise err('MATLAB:gallery:neumann', 'n must be a perfect square.', 'gallery')
    import scipy.sparse as sp
    T = _tri(m, -1.0, 2.0, -1.0).tolil()
    if m > 1:
        T[0, 1] = -2.0
        T[m - 1, m - 2] = -2.0
    T = T.tocsc()
    I = sp.identity(m, format='csc')
    return _sparse(sp.kron(T, I) + sp.kron(I, T))


def orthog(n, k=1):
    n = _int(n, 'orthog')
    i, j = np.indices((n, n)) + 1
    k = int(k)
    if k == 1:
        return math.sqrt(2 / (n + 1)) * np.sin(i * j * math.pi / (n + 1))
    if k == 2:
        return 2 / math.sqrt(2 * n + 1) * np.sin(2 * i * j * math.pi / (2 * n + 1))
    if k == 3:
        return np.exp(2j * math.pi * (i - 1) * (j - 1) / n) / math.sqrt(n)
    if k == 4:
        # Helmert's: the first row all 1/sqrt(n), row i the mean of the first i-1 against the i-th
        Q = np.zeros((n, n))
        if n:
            Q[0, :] = 1 / math.sqrt(n)
        for r in range(1, n):
            Q[r, :r] = 1 / math.sqrt(r * (r + 1))
            Q[r, r] = -r / math.sqrt(r * (r + 1))
        return Q
    if k == 5:
        t = 2 * math.pi * (i - 1) * (j - 1) / n
        return (np.sin(t) + np.cos(t)) / math.sqrt(n)
    if k == 6:
        return math.sqrt(2 / n) * np.cos((i - 0.5) * (j - 0.5) * math.pi / n)
    if k == -1:
        return np.cos((i - 1) * (j - 1) * math.pi / (n - 1)) if n > 1 else np.ones((n, n))
    if k == -2:
        return np.cos((i - 1) * (j - 0.5) * math.pi / n)
    raise err('MATLAB:gallery:orthog', 'k is 1, 2, 3, 4, 5, 6, -1 or -2.', 'gallery')


def parter(n):
    n = _int(n, 'parter')
    i, j = np.indices((n, n)) + 1
    return 1.0 / (i - j + 0.5)


def pei(n, alpha=1.0):
    n = _int(n, 'pei')
    return alpha * np.eye(n) + np.ones((n, n))


def poisson(n):
    import scipy.sparse as sp
    n = _int(n, 'poisson')
    T = _tri(n, -1.0, 2.0, -1.0)
    I = sp.identity(n, format='csc')
    return _sparse(sp.kron(I, T) + sp.kron(T, I))


def prolate(n, w=0.25):
    n = _int(n, 'prolate')
    i, j = np.indices((n, n))
    d = (i - j).astype(F64)
    with np.errstate(divide='ignore', invalid='ignore'):
        A = np.where(d == 0, 2 * w, np.sin(2 * math.pi * w * d) / (math.pi * np.where(d == 0, 1, d)))
    return A


def redheff(n):
    n = _int(n, 'redheff')
    i, j = np.indices((n, n)) + 1
    return ((j == 1) | (j % i == 0)).astype(F64)


def riemann(n):
    n = _int(n, 'riemann')
    i, j = np.indices((n, n)) + 2
    return np.where(j % i == 0, i - 1, -1).astype(F64)


def ris(n):
    n = _int(n, 'ris')
    i, j = np.indices((n, n)) + 1
    return 0.5 / (n - i - j + 1.5)


def smoke(n, k=0):
    n = _int(n, 'smoke')
    w = np.exp(2j * math.pi / n) if n else 1
    A = np.diag(np.concatenate([w ** np.arange(1, n), [1.0]]) if n else np.zeros(0)) + np.diag(np.ones(max(n - 1, 0)), 1)
    if k == 0 and n:
        A[n - 1, 0] = 1
    return A


def toeppen(n, a=1.0, b=-10.0, c=0.0, d=10.0, e=1.0):
    import scipy.sparse as sp
    n = _int(n, 'toeppen')
    vals = [(a, -2), (b, -1), (c, 0), (d, 1), (e, 2)]
    diags = [np.full(max(n - abs(o), 0), v) for v, o in vals]
    return _sparse(sp.diags(diags, [o for _, o in vals], shape=(n, n), format='csc'))


def tridiag(*args):
    if len(args) == 1 or (len(args) == 4 and numel(args[0]) == 1):
        n = _int(args[0], 'tridiag')
        c, d, e = (float(num(a)) for a in args[1:4]) if len(args) == 4 else (-1.0, 2.0, -1.0)
        return _sparse(_tri(n, c, d, e))
    if len(args) == 3:
        x, y, z = (np.asarray(darr(a)).reshape(-1) for a in args)
        n = y.size
        if x.size != n - 1 or z.size != n - 1:
            raise err('MATLAB:gallery:tridiag', 'x and z must have one element fewer than y.', 'gallery')
        return _sparse(_tri(n, x, y, z))
    raise err('MATLAB:gallery:tridiag', 'tridiag takes n, (n, c, d, e) or (x, y, z).', 'gallery')


def triw(n, alpha=-1.0, k=None):
    sz = np.asarray(darr(n)).reshape(-1).astype(int)
    m, nn = (int(sz[0]), int(sz[0])) if sz.size == 1 else (int(sz[0]), int(sz[1]))
    k = nn - 1 if k is None else int(k)
    A = np.tril(np.eye(m, nn) + alpha * np.triu(np.ones((m, nn)), 1), k)
    return A


def wilk(n):
    """Wilkinson's examples: [A, b] for n = 3 (upper triangular) and 4 (lower
    triangular), A for 5 (1.8144 times a block of hilb(6)) and 21 (W21+)."""
    n = _int(n, 'wilk')
    if n == 3:
        return (np.array([[1e-10, 0.9, -0.4], [0, 0.9, -0.4], [0, 0, 1e-10]]), np.array([[0.0], [0.0], [1.0]]))
    if n == 4:
        A = np.array([[0.9143e-4, 0, 0, 0], [0.8762, 0.7156e-4, 0, 0],
                      [0.7943, 0.8143, 0.9504e-4, 0], [0.8017, 0.6123, 0.7165, 0.7123e-4]])
        return (A, np.array([[0.6524], [0.3127], [0.4186], [0.7853]]))
    if n == 5:
        i = np.arange(1, 6, dtype=F64)
        return 1.8144 / (i[:, None] + i[None, :])         # hilb(6)(1:5, 2:6) * 1.8144
    if n == 21:
        return np.diag(np.abs(np.arange(-10, 11, dtype=F64))) + np.diag(np.ones(20), 1) + np.diag(np.ones(20), -1)
    raise err('MATLAB:gallery:wilk', 'wilk is made for n = 3, 4, 5 and 21.', 'gallery')


def chebspec(n, k=0):
    """The Chebyshev spectral differentiation matrix on the points
    cos(pi*(0:N)/N): applied to a polynomial's values there, of degree N at
    most, it gives the derivative's. k = 1 imposes u = 0 at x = 1 (the first
    row and column of the matrix of order n + 1 go)."""
    n = _int(n, 'chebspec')
    if k not in (0, 1):
        raise err('MATLAB:gallery:chebspec', 'k is 0 or 1.', 'gallery')
    N = n if k == 1 else n - 1
    if N < 1:
        return np.zeros((n, n))
    j = np.arange(N + 1)
    x = np.cos(np.pi * j / N)
    c = np.ones(N + 1)
    c[0] = c[-1] = 2.0
    sign = np.where((j[:, None] + j[None, :]) % 2 == 0, 1.0, -1.0)
    with np.errstate(divide='ignore', invalid='ignore'):
        C = (c[:, None] / c[None, :]) * sign / (x[:, None] - x[None, :])
    inner = j[1:-1]
    C[inner, inner] = -x[inner] / (2 * (1 - x[inner] ** 2))
    C[0, 0] = (2 * N * N + 1) / 6
    C[N, N] = -C[0, 0]
    return C[1:, 1:] if k == 1 else C


def dorr(n, theta=0.01):
    """Dorr's tridiagonal M-matrix, row diagonally dominant and ill
    conditioned for small theta >= 0: [c, d, e] gives its sub-, main and
    super-diagonals."""
    n = _int(n, 'dorr')
    h = 1.0 / (n + 1)
    m = (n + 1) // 2
    t = theta / h ** 2
    i = np.arange(1, n + 1, dtype=F64)
    c, e = np.empty(n), np.empty(n)
    lo = i <= m
    c[lo] = -t
    e[lo] = c[lo] - (0.5 - i[lo] * h) / h
    e[~lo] = -t
    c[~lo] = e[~lo] + (0.5 - i[~lo] * h) / h
    d = -(c + e)
    c, e = c[1:], e[:-1]
    A = np.diag(d) + np.diag(c, -1) + np.diag(e, 1)
    return (A, c.reshape(-1, 1), d.reshape(-1, 1), e.reshape(-1, 1))


def wathen(nx, ny=None, k=0):
    """Wathen's finite-element matrix: the consistent mass matrix of an nx-by-ny
    grid of 8-node serendipity elements, each weighted by a random density
    (100*rand); sparse, symmetric and positive definite, of order
    3*nx*ny + 2*nx + 2*ny + 1. k = 1 scales it by its diagonal."""
    from .elmat import RNG
    nx = _int(nx, 'wathen', 'nx')
    ny = nx if ny is None else _int(ny, 'wathen', 'ny')
    e1 = np.array([[6, -6, 2, -8], [-6, 32, -6, 20], [2, -6, 6, -6], [-8, 20, -6, 32]], F64)
    e2 = np.array([[3, -8, 2, -6], [-8, 16, -8, 20], [2, -8, 3, -8], [-6, 20, -8, 16]], F64)
    em = np.block([[e1, e2], [e2.T, e1]]) / 45
    rho = 100 * RNG.uniform((nx, ny))     # rand(nx, ny), from the session's generator
    n = 3 * nx * ny + 2 * nx + 2 * ny + 1
    rows, cols, vals = [], [], []
    for jj in range(1, ny + 1):
        for ii in range(1, nx + 1):
            # the element's nodes counter-clockwise from its top right corner (1-based)
            n1 = 3 * jj * nx + 2 * ii + 2 * jj + 1
            n4 = (3 * jj - 1) * nx + 2 * jj + ii - 1
            n5 = 3 * (jj - 1) * nx + 2 * ii + 2 * jj - 3
            nn = np.array([n1, n1 - 1, n1 - 2, n4, n5, n5 + 1, n5 + 2, n4 + 1]) - 1
            rows.append(np.repeat(nn, 8))
            cols.append(np.tile(nn, 8))
            vals.append((em * rho[ii - 1, jj - 1]).reshape(-1))
    import scipy.sparse as sp
    if rows:
        A = sp.csc_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
    else:
        A = sp.csc_matrix((n, n))
    if k == 1:
        A = sp.diags(1.0 / A.diagonal()) @ A if A.nnz else A
    return SPM.make(sp.csc_matrix(A))


def binomial(n):
    n = _int(n, 'binomial')
    L = np.array([[float(math.comb(i, j)) for j in range(n)] for i in range(n)]).reshape(n, n)
    U = L[::-1, ::-1]
    D = np.diag((-2.0) ** np.arange(n))
    return L @ D @ U


def invhess(x, y=None):
    x = _n_or_vec(x, 'invhess')
    n = x.size
    y = -x[:n - 1] if y is None else np.asarray(darr(y)).reshape(-1)
    if y.size != n - 1:
        raise err('MATLAB:gallery:invhess', 'y must have one element fewer than x.', 'gallery')
    i, j = np.indices((n, n))
    return np.where(j <= i, x[j], np.concatenate([y, [0.0]])[i])


def gcdmat(n):
    n = _int(n, 'gcdmat')
    return np.array([[float(math.gcd(i, j)) for j in range(1, n + 1)] for i in range(1, n + 1)]).reshape(n, n)


def cycol(n, k=None):
    from .elmat import RNG
    m, nn = _size(n)
    k = max(round(nn / 4), 1) if k is None else int(k)
    base = RNG.rs.standard_normal((k, m)).T
    return base[:, np.arange(nn) % k]


def randhess(x):
    """An orthogonal upper Hessenberg matrix: a product of plane rotations,
    their angles random (n given) or x(1:n-1)."""
    from .elmat import RNG
    x = np.asarray(darr(x)).reshape(-1)
    if x.size == 1:
        n = int(x[0])
        ang = 2 * math.pi * RNG.rs.random_sample(max(n - 1, 0))
    else:
        n = x.size
        ang = x[:n - 1]
    H = np.eye(n)
    for i in range(n - 1, 0, -1):
        c, s = math.cos(ang[i - 1]), math.sin(ang[i - 1])
        G = np.eye(n)
        G[i - 1:i + 1, i - 1:i + 1] = [[c, s], [-s, c]]
        H = G @ H
    return H


def toeppd(n, m=None, w=None, theta=None):
    """sum of w(k)*T(theta(k)), T(t)(i,j) = cos(2*pi*t*(i-j)): a symmetric
    positive semidefinite Toeplitz matrix (w and theta random unless given)."""
    from .elmat import RNG
    n = _int(n, 'toeppd')
    m = n if m is None else int(m)
    w = RNG.rs.random_sample(m) if w is None else np.asarray(darr(w)).reshape(-1)
    theta = RNG.rs.random_sample(m) if theta is None else np.asarray(darr(theta)).reshape(-1)
    i, j = np.indices((n, n))
    return sum(wk * np.cos(2 * math.pi * tk * (i - j)) for wk, tk in zip(w, theta)) if m else np.zeros((n, n))


def house(x, k=0):
    """[v, beta, s] = gallery('house', x, k): H = I - beta*v*v' takes x to s*e1;
    k 0: s has the sign opposite to x(1), k 1: the same sign."""
    x = np.asarray(darr(x)).reshape(-1, 1)
    s = np.linalg.norm(x)
    sg = np.sign(x[0, 0]) if x[0, 0] != 0 else 1.0
    s = -sg * s if int(k) == 0 else sg * s
    v = x.astype(np.result_type(x, F64)).copy()
    v[0, 0] = v[0, 0] - s
    vv = float(np.real(np.vdot(v, v)))
    beta = 2 / vv if vv else 0.0
    return v, float(beta), float(s)


def kahan(n, theta=1.2, pert=25.0):
    m, nn = _size(n)
    s, c = math.sin(theta), math.cos(theta)
    U = np.eye(nn) - c * np.triu(np.ones((nn, nn)), 1)
    U = np.diag(s ** np.arange(nn)) @ U + pert * np.finfo(float).eps * np.diag(np.arange(nn, 0, -1, dtype=F64))
    return U[:m, :] if m <= nn else np.vstack([U, np.zeros((m - nn, nn))])


def lesp(n):
    n = _int(n, 'lesp')
    x = np.arange(2, n + 1, dtype=F64)
    return np.diag(1 / x, -1) + np.diag(-(2 * np.arange(1, n + 1) + 3.0)) + np.diag(x, 1)


def invol(n):
    """An involutory matrix (A*A = I), made from the Hilbert matrix."""
    n = _int(n, 'invol')
    i, j = np.indices((n, n)) + 1
    A = 1.0 / (i + j - 1)
    d = -float(n)
    if n:
        A[:, 0] = d * A[:, 0]
    for r in range(1, n):
        d = -(n + r) * (n - r) * d / (r * r)
        A[r, :] = d * A[r, :]
    return A


def _size(v):
    sz = np.asarray(darr(v)).reshape(-1).astype(int)
    return (int(sz[0]), int(sz[0])) if sz.size == 1 else tuple(int(s) for s in sz)


def rando(n, k=1):
    from .elmat import RNG
    shape = _size(n)
    r = RNG.rs.random_sample(shape[::-1]).T if len(shape) == 2 else RNG.rs.random_sample(shape)
    k = int(k)
    if k == 1:
        return np.floor(r + 0.5)
    if k == 2:
        return 2 * np.floor(r + 0.5) - 1
    if k == 3:
        return np.round(3 * r - 1.5)
    raise err('MATLAB:gallery:rando', 'k is 1, 2 or 3.', 'gallery')


def _haar(n, rs):
    Q, R = np.linalg.qr(rs.standard_normal((n, n)))
    return Q * np.sign(np.diag(R))


def randsvd(n, kappa=None, mode=3):
    from .elmat import RNG
    m, nn = _size(n)
    kappa = 1 / math.sqrt(np.finfo(float).eps) if kappa is None else float(kappa)
    p = min(m, nn)
    mode = int(mode)
    if p == 0:
        return np.zeros((m, nn))
    if mode == 1:
        s = np.full(p, 1 / kappa)
        s[0] = 1
    elif mode == 2:
        s = np.ones(p)
        s[-1] = 1 / kappa
    elif mode == 3:
        s = kappa ** (-np.arange(p) / max(p - 1, 1))
    elif mode == 4:
        s = 1 - (1 - 1 / kappa) * np.arange(p) / max(p - 1, 1)
    elif mode == 5:
        s = np.exp(-RNG.rs.random_sample(p) * math.log(kappa))
    else:
        raise err('MATLAB:gallery:randsvd', 'mode is 1, 2, 3, 4 or 5.', 'gallery')
    S = np.zeros((m, nn))
    S[np.arange(p), np.arange(p)] = s
    return _haar(m, RNG.rs) @ S @ _haar(nn, RNG.rs).T


def _data(kind, args):
    """integerdata(imax, sz, j), uniformdata(sz, j), normaldata(sz, j): numbers
    from a generator of their own seeded by j, so the same j gives the same
    numbers and the session's generator is left alone."""
    if kind == 'integerdata':
        if len(args) != 3:
            raise err('MATLAB:gallery:integerdata', 'integerdata takes imax, the size and the seed j.', 'gallery')
        lim = np.asarray(darr(args[0])).reshape(-1)
        lo, hi = (1, int(lim[0])) if lim.size == 1 else (int(lim[0]), int(lim[1]))
        shape, j = _size(args[1]), int(num(args[2]))
    else:
        if len(args) != 2:
            raise err(f'MATLAB:gallery:{kind}', f'{kind} takes the size and the seed j.', 'gallery')
        shape, j = _size(args[0]), int(num(args[1]))
    rs = np.random.RandomState(j)
    if kind == 'integerdata':
        return rs.randint(lo, hi + 1, size=shape).astype(F64)
    if kind == 'uniformdata':
        return rs.random_sample(shape)
    return rs.standard_normal(shape)


_PLAIN = {
    'cauchy': cauchy, 'chebvand': chebvand, 'chow': chow, 'circul': circul, 'clement': clement, 'compar': compar,
    'fiedler': fiedler, 'forsythe': forsythe, 'frank': frank, 'gearmat': gearmat, 'grcar': grcar, 'hanowa': hanowa,
    'ipjfact': ipjfact, 'jordbloc': jordbloc, 'kms': kms, 'krylov': krylov, 'lauchli': lauchli, 'lehmer': lehmer,
    'leslie': leslie, 'lotkin': lotkin, 'minij': minij, 'moler': moler, 'neumann': neumann, 'orthog': orthog,
    'parter': parter, 'pei': pei, 'poisson': poisson, 'prolate': prolate, 'redheff': redheff, 'riemann': riemann,
    'ris': ris, 'smoke': smoke, 'toeppen': toeppen, 'tridiag': tridiag, 'triw': triw, 'wilk': wilk,
    'chebspec': chebspec, 'dorr': dorr, 'wathen': wathen,
    'binomial': binomial, 'rando': rando, 'randsvd': randsvd, 'invhess': invhess, 'gcdmat': gcdmat, 'cycol': cycol,
    'randhess': randhess, 'toeppd': toeppd, 'house': house, 'kahan': kahan, 'lesp': lesp, 'invol': invol,
}
# inputs passed as values, not numbers (vectors, matrices)
_RAW = {'cauchy', 'chebvand', 'circul', 'compar', 'fiedler', 'krylov', 'leslie', 'tridiag', 'triw', 'rando', 'randsvd',
        'invhess', 'cycol', 'randhess', 'toeppd', 'house', 'kahan'}


@bi('gallery', nout=3)
def gallery(nargout, *args):
    """gallery(name, ...): Higham's test matrices (cauchy, chebvand, chow,
    circul, clement, compar, fiedler, forsythe, frank, gearmat, grcar,
    hanowa, ipjfact, jordbloc, kms, krylov, lauchli, lehmer, leslie, lotkin,
    minij, moler, neumann, orthog, parter, pei, poisson, prolate, redheff,
    riemann, ris, smoke, toeppen, tridiag, triw, wilk, binomial, rando,
    randsvd, chebspec, dorr, wathen, and the data sets integerdata,
    uniformdata, normaldata)."""
    if not args:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'gallery')
    name = opt_str(args[0])
    if name is None:
        raise err('MATLAB:gallery:InvalidName', 'The first input is the name of a matrix.', 'gallery')
    name = name.lower()
    rest = list(args[1:])
    if name in ('integerdata', 'uniformdata', 'normaldata'):
        return out(_data(name, rest))
    fn = _PLAIN.get(name)
    if fn is None:
        raise err('MATLAB:gallery:UnknownMatrix', f"'{name}' is not a matrix gallery makes here. It makes: {', '.join(sorted(_PLAIN) + ['integerdata', 'normaldata', 'uniformdata'])}.", 'gallery')
    if not rest and name not in ('rando', 'randsvd'):
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'gallery')
    if name in _RAW:
        vals = rest
    else:
        vals = [(complex(num(a)) if isinstance(num(a), complex) else float(num(a))) if numel(a) == 1 else np.asarray(darr(a)) for a in rest]
    try:
        r = fn(*vals)
    except TypeError:
        raise err('MATLAB:gallery:nargin', f"Wrong number of inputs for gallery('{name}').", 'gallery') from None
    if name == 'dorr':
        r = r[0] if nargout <= 1 else r[1:]         # A, or its diagonals c, d, e
    if isinstance(r, tuple):
        r = tuple(out(x) if isinstance(x, np.ndarray) else x for x in r)
        return r[0] if nargout <= 1 else r[:nargout]
    return r if not isinstance(r, np.ndarray) else out(r)
