"""Wavelets: the filters (Daubechies, symlets, coiflets, biorthogonal
splines and their reverses) computed rather than tabulated, the discrete
transform in one and two dimensions with its extension modes, the
stationary and maximal overlap transforms, the continuous transform on
analytic wavelets, and denoising by thresholds.

The filters come from the Daubechies polynomial sum C(N-1+k, k) y^k: its
roots, polished to 60 digits in decimal arithmetic, give the minimum phase
(db) filters; symlets take, of each pair of roots, the one the standard
table takes; coiflets solve their moment and orthogonality equations by
Newton's method from the interpolating filter, polished likewise. Filters
follow the usual conventions: LoR sums to sqrt(2), LoD is LoR reversed for
orthogonal wavelets, HiR(k) = (-1)^k LoD(k), HiD(k) = (-1)^(k+1) LoR(k).
"""
import math
from decimal import Decimal, localcontext
from fractions import Fraction

import numpy as np

from . import bi as _register
from ._util import err, nargchk, darr, out, opt_str, is_str
from ..values import MError, Char, Cell, EMPTY, numel
from .. import runtime as R


def bi(*names, **kw):
    """Registered as builtins are, with what NumPy refuses told as the
    language's error of that function."""
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'Wavelet:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _b(name, *args):
    return R._builtin(name, *args)


def _outs(nargout, *vals):
    """The first value alone for one output, else as many as asked for."""
    return vals[0] if nargout <= 1 else vals[:nargout]


# ---- decimal arithmetic for the filters ---------------------------------------------------------------------------

_PREC = 60


def _cmul(a, b):
    return (a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0])


def _cdiv(a, b):
    d = b[0] * b[0] + b[1] * b[1]
    return ((a[0] * b[0] + a[1] * b[1]) / d, (a[1] * b[0] - a[0] * b[1]) / d)


def _csqrt(a):
    r = (a[0] * a[0] + a[1] * a[1]).sqrt()
    re = max((r + a[0]) / 2, Decimal(0)).sqrt()
    im = max((r - a[0]) / 2, Decimal(0)).sqrt()
    return (re, -im if a[1] < 0 else im)


def _cabs2(a):
    return a[0] * a[0] + a[1] * a[1]


def _yroots(N):
    """The roots of the Daubechies polynomial sum C(N-1+k, k) y^k (degree
    N - 1), from NumPy's and polished together (Weierstrass' iteration)
    to 60 digits, as (re, im) Decimal pairs."""
    c = [math.comb(N - 1 + k, k) for k in range(N)]
    approx = np.roots(np.array(c[::-1], dtype=float))
    with localcontext() as ctx:
        ctx.prec = _PREC
        a = [Decimal(v) / Decimal(c[-1]) for v in c]
        zs = [(Decimal(float(r.real)), Decimal(float(r.imag))) for r in approx]
        tol = Decimal(10) ** (8 - _PREC)
        for _ in range(100):
            delta = Decimal(0)
            for i in range(len(zs)):
                z = zs[i]
                p = (Decimal(1), Decimal(0))
                for k in range(N - 2, -1, -1):
                    p = _cmul(p, z)
                    p = (p[0] + a[k], p[1])
                q = (Decimal(1), Decimal(0))
                for j, w in enumerate(zs):
                    if j != i:
                        q = _cmul(q, (z[0] - w[0], z[1] - w[1]))
                c_ = _cdiv(p, q)
                zs[i] = (z[0] - c_[0], z[1] - c_[1])
                delta = max(delta, abs(c_[0]) + abs(c_[1]))
            if delta < tol:
                break
    return zs


def _zgroups(N):
    """The roots in z of the inside half, grouped: a real one alone, a
    complex one with its conjugate; complex groups by their angle, largest
    first, then the real one."""
    groups = []
    with localcontext() as ctx:
        ctx.prec = _PREC
        tiny = Decimal(10) ** (20 - _PREC)
        for y in _yroots(N):
            if y[1] < -tiny:
                continue
            b = (2 - 4 * y[0], -4 * y[1])
            s = _csqrt((b[0] * b[0] - b[1] * b[1] - 4, 2 * b[0] * b[1]))
            z = ((b[0] - s[0]) / 2, (b[1] - s[1]) / 2)
            if _cabs2(z) > 1:
                z = ((b[0] + s[0]) / 2, (b[1] + s[1]) / 2)
            if abs(y[1]) <= tiny:
                groups.append([(z[0], Decimal(0))])
            else:
                groups.append([z, (z[0], -z[1])])
    groups.sort(key=lambda g: -math.atan2(float(g[0][1]), float(g[0][0])) if len(g) == 2 else 0.0)
    return groups


def _from_roots(ones, roots):
    """The real filter with the zeros -1 (ones times) and roots (Decimal
    pairs), as floats summing to sqrt(2)."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        p = [(Decimal(1), Decimal(0))]
        for z in [(Decimal(-1), Decimal(0))] * ones + list(roots):
            q = [(Decimal(0), Decimal(0))] * (len(p) + 1)
            for i, c in enumerate(p):
                q[i] = (q[i][0] + c[0], q[i][1] + c[1])
                m = _cmul(c, z)
                q[i + 1] = (q[i + 1][0] - m[0], q[i + 1][1] - m[1])
            p = q
        re = [c[0] for c in p]
        s = sum(re)
        r2 = Decimal(2).sqrt()
        return np.array([float(v * r2 / s) for v in re])


def _inv(z):
    return _cdiv((Decimal(1), Decimal(0)), z)


_SYM_BITS = {2: '0', 3: '0', 4: '10', 5: '01', 6: '101', 7: '001', 8: '1010', 9: '0110', 10: '10101', 11: '00110',
             12: '010101', 13: '011100', 14: '0101100', 15: '0011100', 16: '01011001', 17: '10001110',
             18: '101001101', 19: '001110100', 20: '0101100101'}


def _db(N):
    if N == 1:
        return np.array([1.0, 1.0]) / math.sqrt(2)
    roots = [z for g in _zgroups(N) for z in g]
    with localcontext() as ctx:
        ctx.prec = _PREC
        return _from_roots(N, roots)


def _sym(N):
    if N == 1:
        return _db(1)
    roots = []
    with localcontext() as ctx:
        ctx.prec = _PREC
        for bit, g in zip(_SYM_BITS[N], _zgroups(N)):
            roots += [_inv(z) for z in g] if bit == '1' else g
        return _from_roots(N, roots)


# ---- coiflets ---------------------------------------------------------------------------------------------------

def _coif_start(K):
    """The interpolating filter of order 2K (midpoint Lagrange weights) about
    index 2K, scaled to sum sqrt(2): where Newton's method starts."""
    L, s = 6 * K, 2 * K
    h = np.zeros(L)
    h[s] = 1.0
    pts = np.arange(-(2 * K - 1), 2 * K, 2) / 2.0
    for i, xi in enumerate(pts):
        w = 1.0
        for j, xj in enumerate(pts):
            if j != i:
                w *= -xj / (xi - xj)
        h[int(s + 2 * xi)] += w
    return h * math.sqrt(2) / 2


def _coif_rows(K, h, dec=False):
    """The square system of coiflet K: wavelet moments 0..2K-1, scaling
    moments 1..2K-1 about index 2K, and orthogonality at shifts 0..2K
    (the others follow); its residual and Jacobian."""
    L, s = 6 * K, 2 * K
    one = Decimal(1) if dec else 1.0
    zero = Decimal(0) if dec else 0.0
    k = [(i - s) * one / L for i in range(L)]
    F, J = [], []
    for p in range(2 * K):
        row = [(-one if i % 2 else one) * (k[i] ** p if p else one) for i in range(L)]
        F.append(sum(r * x for r, x in zip(row, h)))
        J.append(row)
    for p in range(1, 2 * K):
        row = [k[i] ** p for i in range(L)]
        F.append(sum(r * x for r, x in zip(row, h)))
        J.append(row)
    for m in range(2 * K + 1):
        F.append(sum(h[i] * h[i + 2 * m] for i in range(L - 2 * m)) - (one if m == 0 else zero))
        row = [zero] * L
        for i in range(L - 2 * m):
            row[i] += h[i + 2 * m]
            row[i + 2 * m] += h[i]
        J.append(row)
    return F, J


def _dsolve(A, b):
    """A x = b in Decimal by Gaussian elimination with partial pivoting."""
    n = len(b)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        for r in range(c + 1, n):
            f = M[r][c] / M[c][c]
            if f:
                for j in range(c, n + 1):
                    M[r][j] -= f * M[c][j]
    x = [Decimal(0)] * n
    for c in range(n - 1, -1, -1):
        x[c] = (M[c][n] - sum(M[c][j] * x[j] for j in range(c + 1, n))) / M[c][c]
    return x


def _coif(K):
    h = _coif_start(K)
    for _ in range(50):
        F, J = _coif_rows(K, h)
        F, J = np.array(F), np.array(J)
        d = np.linalg.solve(J, -F)
        t, n0 = 1.0, np.linalg.norm(F)
        while t > 1e-6 and np.linalg.norm(_coif_rows(K, h + t * d)[0]) >= n0:
            t /= 2
        h = h + t * d
        if n0 < 1e-14:
            break
    with localcontext() as ctx:
        ctx.prec = _PREC
        hd = [Decimal(float(v)) for v in h]
        for _ in range(4):
            F, J = _coif_rows(K, hd, dec=True)
            d = _dsolve(J, [-f for f in F])
            hd = [a + b for a, b in zip(hd, d)]
        s = sum(hd)
        r2 = Decimal(2).sqrt()
        return np.array([float(v * r2 / s) for v in hd])


# ---- biorthogonal ----------------------------------------------------------------------------------------------

_BIOR = ('1.1', '1.3', '1.5', '2.2', '2.4', '2.6', '2.8', '3.1', '3.3', '3.5', '3.7', '3.9', '4.4', '5.5', '6.8')

# the three that split the roots of the Daubechies polynomial of order l: (l, power of (1+z)/2 in the reconstruction
# filter, in the decomposition filter, the reconstruction filter's root groups (by real part, smallest first))
_BIOR_SPLIT = {'4.4': (4, 4, 4, (0,)), '5.5': (5, 6, 4, (0,)), '6.8': (7, 6, 8, (1,))}


def _fpoly_mul(p, q):
    r = [Fraction(0)] * (len(p) + len(q) - 1)
    for i, a in enumerate(p):
        for j, b in enumerate(q):
            r[i + j] += a * b
    return r


def _spline_pair(nr, nd):
    """The spline biorthogonal scaling filters (each summing to 1): the
    reconstruction one the B-spline ((1 + z)/2)^nr, the decomposition one
    ((1 + z)/2)^nd times sum C(l-1+n, n) sin^2n(w/2), l = (nr + nd)/2."""
    half = [Fraction(1, 2), Fraction(1, 2)]
    rf = [Fraction(1)]
    for _ in range(nr):
        rf = _fpoly_mul(rf, half)
    l = (nr + nd) // 2
    s2 = [Fraction(-1, 4), Fraction(1, 2), Fraction(-1, 4)]      # z sin^2(w/2) = (-1 + 2z - z^2)/4
    Q = [Fraction(0)] * (2 * l - 1)
    for n in range(l):
        t = [Fraction(math.comb(l - 1 + n, n))]
        for _ in range(n):
            t = _fpoly_mul(t, s2)
        off = l - 1 - n
        for i, v in enumerate(t):
            Q[off + i] += v
    df = Q
    for _ in range(nd):
        df = _fpoly_mul(df, half)
    while df and df[0] == 0:
        df = df[1:]
    while df and df[-1] == 0:
        df = df[:-1]
    return np.array([float(v) for v in rf]), np.array([float(v) for v in df])


def _split_pair(name):
    l, a, b, rec_groups = _BIOR_SPLIT[name]
    with localcontext() as ctx:
        ctx.prec = _PREC
        ys = sorted([y for y in _yroots(l) if y[1] >= 0], key=lambda y: (float(y[0]), float(y[1])))
        groups = [[y] if abs(y[1]) < Decimal(10) ** (20 - _PREC) else [y, (y[0], -y[1])] for y in ys]

        def filt(ones, gs):
            # each y root r gives the factor (1 - y/r): in z, (1 + (4r - 2) z + z^2)/(4r) up to scale; its zeros
            roots = []
            for g in gs:
                for r in g:
                    bb = (2 - 4 * r[0], -4 * r[1])
                    s = _csqrt((bb[0] * bb[0] - bb[1] * bb[1] - 4, 2 * bb[0] * bb[1]))
                    roots += [((bb[0] - s[0]) / 2, (bb[1] - s[1]) / 2), ((bb[0] + s[0]) / 2, (bb[1] + s[1]) / 2)]
            return _from_roots(ones, roots) / math.sqrt(2)
        rf = filt(a, [groups[i] for i in rec_groups])
        df = filt(b, [g for i, g in enumerate(groups) if i not in rec_groups])
    return rf, df


def _place(f, L, centre):
    """f in a vector of length L, its middle at index centre."""
    out_ = np.zeros(L)
    start = int(round(centre - (f.size - 1) / 2))
    out_[start:start + f.size] = f
    return out_


def _bior_filters(name):
    rf, df = _split_pair(name) if name in _BIOR_SPLIT else _spline_pair(int(name[0]), int(name[2:]))
    L = max(rf.size, df.size)
    L += L % 2
    r2 = math.sqrt(2)
    if rf.size % 2:
        lo_r, lo_d = _place(rf * r2, L, L / 2 - 1), _place(df * r2, L, L / 2)
    else:
        lo_r, lo_d = _place(rf * r2, L, (L - 1) / 2), _place(df * r2, L, (L - 1) / 2)
    return lo_d, lo_r


def _highs(lo_d, lo_r):
    k = np.arange(lo_d.size)
    sign = np.where(k % 2, -1.0, 1.0)
    return -sign * lo_r, sign * lo_d          # hi_d, hi_r


class Wavelet:
    """A wavelet's four filters and what it is."""
    __slots__ = ('name', 'family', 'orth', 'lo_d', 'hi_d', 'lo_r', 'hi_r')

    def __init__(self, name, family, orth, lo_d, lo_r):
        self.name, self.family, self.orth = name, family, orth
        self.lo_d, self.lo_r = lo_d, lo_r
        self.hi_d, self.hi_r = _highs(lo_d, lo_r)

    @property
    def L(self):
        return self.lo_d.size


_CACHE = {}
_FAMILIES = ('haar', 'db1..db45', 'sym2..sym20', 'coif1..coif5', 'bior' + ', bior'.join(_BIOR), 'rbio (as bior)')


def wavelet(name, fn):
    """The Wavelet of a name (haar, dbN, symN, coifN, biorNr.Nd, rbioNr.Nd)."""
    key = name.strip().lower()
    if key in _CACHE:
        return _CACHE[key]
    w = None
    if key == 'haar':
        h = _db(1)
        w = Wavelet('haar', 'haar', True, h[::-1].copy(), h)
    else:
        for fam, lo, hi, make in (('db', 1, 45, _db), ('sym', 2, 20, _sym), ('coif', 1, 5, _coif)):
            if key.startswith(fam) and key[len(fam):].isdigit() and lo <= int(key[len(fam):]) <= hi:
                h = make(int(key[len(fam):]))
                w = Wavelet(key, fam, True, h[::-1].copy(), h)
                break
        for fam in ('bior', 'rbio'):
            if key.startswith(fam) and key[4:] in _BIOR:
                lo_d, lo_r = _bior_filters(key[4:])
                if fam == 'rbio':
                    lo_d, lo_r = lo_r[::-1].copy(), lo_d[::-1].copy()
                w = Wavelet(key, fam, False, lo_d, lo_r)
    if w is None:
        raise err(f'Wavelet:{fn}:wname', f"'{name}' is not a wavelet {fn} knows: haar, db1 to db45, sym2 to sym20, coif1 to coif5, "
                  f"bior1.1 to bior6.8 and rbio1.1 to rbio6.8.", fn)
    _CACHE[key] = w
    return w


# ---- extension modes ---------------------------------------------------------------------------------------------

_MODES = {'sym': 'symmetric', 'symh': 'symmetric', 'symw': 'reflect', 'asym': 'antisymmetric', 'asymh': 'antisymmetric',
          'asymw': 'antireflect', 'zpd': 'zero', 'sp0': 'constant', 'sp1': 'smooth', 'spd': 'smooth', 'ppd': 'periodic',
          'per': 'periodization'}
_MODE_TEXT = {'sym': 'symmetric, half-point', 'symh': 'symmetric, half-point', 'symw': 'symmetric, whole-point',
              'asym': 'antisymmetric, half-point', 'asymh': 'antisymmetric, half-point', 'asymw': 'antisymmetric, whole-point',
              'zpd': 'zeros', 'sp0': 'constant (smooth of order 0)', 'sp1': 'linear (smooth of order 1)',
              'spd': 'linear (smooth of order 1)', 'ppd': 'periodic', 'per': 'periodization'}
MODE = ['sym']


def _mode_name(v, fn):
    s = opt_str(v)
    if s is None or s.lower() not in _MODES:
        raise err(f'Wavelet:{fn}:mode', f"The extension mode is one of {', '.join(sorted(_MODES))}.", fn)
    return s.lower()


def _take_mode(args, fn):
    """The 'mode', name pair taken out of args: (mode, the rest)."""
    rest, mode = [], MODE[0]
    i = 0
    while i < len(args):
        s = opt_str(args[i])
        if s is not None and s.lower() == 'mode' and i + 1 < len(args):
            mode = _mode_name(args[i + 1], fn)
            i += 2
            continue
        rest.append(args[i])
        i += 1
    return _MODES[mode], rest


def _extend(x, nl, nr, mode):
    """x extended by nl samples before and nr after along its last axis."""
    N = x.shape[-1]
    if nl == 0 and nr == 0:
        return x
    if mode == 'zero':
        z = np.zeros(x.shape[:-1] + (nl,)), np.zeros(x.shape[:-1] + (nr,))
        return np.concatenate([z[0], x, z[1]], axis=-1)
    if mode == 'constant' or (N == 1 and mode in ('smooth', 'reflect', 'antireflect')):
        return np.concatenate([np.repeat(x[..., :1], nl, axis=-1), x, np.repeat(x[..., -1:], nr, axis=-1)], axis=-1)
    if mode == 'smooth':
        kl = np.arange(nl, 0, -1)
        kr = np.arange(1, nr + 1)
        left = x[..., :1] + (x[..., :1] - x[..., 1:2]) * kl
        right = x[..., -1:] + (x[..., -1:] - x[..., -2:-1]) * kr
        return np.concatenate([left, x, right], axis=-1)
    if mode == 'antireflect':
        left = x
        while left.shape[-1] < N + nl:
            k = min(N - 1, N + nl - left.shape[-1])
            left = np.concatenate([2 * left[..., :1] - left[..., 1:k + 1][..., ::-1], left], axis=-1)
        right = x
        while right.shape[-1] < N + nr:
            k = min(N - 1, N + nr - right.shape[-1])
            right = np.concatenate([right, 2 * right[..., -1:] - right[..., -k - 1:-1][..., ::-1]], axis=-1)
        return np.concatenate([left[..., left.shape[-1] - N - nl:left.shape[-1] - N], x, right[..., N:N + nr]], axis=-1)
    idx = np.arange(-nl, N + nr)
    if mode == 'periodic':
        return x[..., idx % N]
    if mode == 'reflect':
        k = idx % (2 * N - 2)
        return x[..., np.where(k >= N, 2 * N - 2 - k, k)]
    k = idx % (2 * N)
    flip = k >= N
    y = x[..., np.where(flip, 2 * N - 1 - k, k)]
    if mode == 'antisymmetric':
        y = y * np.where(flip, -1.0, 1.0)
    return y


# ---- one step of the transform along the last axis ---------------------------------------------------------------

def dwt_last(x, lo, hi, mode):
    """Approximation and detail coefficients of x along its last axis."""
    L, N = lo.size, x.shape[-1]
    if mode == 'periodization':
        if N % 2:
            x = np.concatenate([x, x[..., -1:]], axis=-1)
        M = x.shape[-1]
        n = M // 2
        a = np.zeros(x.shape[:-1] + (n,))
        d = np.zeros_like(a)
        o = 2 * np.arange(n) + L // 2
        for j in range(L):
            s = x[..., (o - j) % M]
            a += lo[j] * s
            d += hi[j] * s
        return a, d
    xe = _extend(x, L - 1, L - 1, mode)
    n = (N + L - 1) // 2
    a = np.zeros(x.shape[:-1] + (n,))
    d = np.zeros_like(a)
    for k in range(L):
        s = xe[..., L - k:L - k + 2 * n:2]
        a += lo[k] * s
        d += hi[k] * s
    return a, d


def _keep(y, n):
    """The middle n samples of y along its last axis."""
    m = y.shape[-1]
    if n is None or n >= m:
        return y
    f = (m - n) // 2
    return y[..., f:f + n]


def idwt_last(a, d, lo, hi, mode, n=None):
    """The inverse of one step along the last axis (a or d None for zeros),
    its middle n samples when n is given."""
    c = a if a is not None else d
    if c is None:
        return None
    L, m = lo.size, c.shape[-1]
    if mode == 'periodization':
        M = 2 * m
        y = np.zeros(c.shape[:-1] + (M,))
        t = np.arange(M)
        for f, v in ((lo, a), (hi, d)):
            if v is None:
                continue
            u = np.zeros(c.shape[:-1] + (M,))
            u[..., ::2] = v
            for j in range(L):
                y += f[j] * u[..., (t - j + L // 2 - 1) % M]
        return _keep(y, n)
    full = np.zeros(c.shape[:-1] + (2 * m + L - 2,))
    for f, v in ((lo, a), (hi, d)):
        if v is None:
            continue
        u = np.zeros(c.shape[:-1] + (2 * m - 1,))
        u[..., ::2] = v
        for k in range(L):
            full[..., k:k + 2 * m - 1] += f[k] * u
    y = full[..., L - 2:L - 2 + max(2 * m - L + 2, 0)]
    return _keep(y, n)


def _upconv(x, f):
    """x upsampled (zeros between) and convolved in full with f."""
    m = x.shape[-1]
    u = np.zeros(x.shape[:-1] + (2 * m - 1,))
    u[..., ::2] = x
    y = np.zeros(x.shape[:-1] + (2 * m - 1 + f.size - 1,))
    for k in range(f.size):
        y[..., k:k + 2 * m - 1] += f[k] * u
    return y


# ---- arguments -------------------------------------------------------------------------------------------------------

def _vec(v, fn, what='The signal'):
    a = darr(v, fn)
    if a.ndim > 2 or (a.size and min(a.shape) > 1):
        raise err(f'Wavelet:{fn}:vector', f'{what} must be a vector.', fn)
    if np.iscomplexobj(a):
        raise err(f'Wavelet:{fn}:real', f'{what} must be real.', fn)
    return a.reshape(-1).astype(float), a.ndim == 2 and a.shape[0] != 1 and a.size > 0


def _mat(v, fn, what='The image'):
    a = darr(v, fn)
    if a.ndim != 2:
        raise err(f'Wavelet:{fn}:matrix', f'{what} must be a matrix.', fn)
    if np.iscomplexobj(a):
        raise err(f'Wavelet:{fn}:real', f'{what} must be real.', fn)
    return a.astype(float)


def _int(v, fn, what='level', lo=0):
    a = darr(v, fn).reshape(-1)
    if a.size != 1 or not np.isfinite(a[0]) or a[0] != int(a[0]) or a[0] < lo:
        raise err(f'Wavelet:{fn}:{what}', f'The {what} must be a whole number{" of at least %d" % lo if lo else ", 0 or more"}.', fn)
    return int(a[0])


def _filters(args, i, fn, kind):
    """A wavelet name at args[i], or two filters there: (lo, hi, wavelet or None, the index after).
    kind is 'd' for the decomposition filters, 'r' for the reconstruction ones."""
    if i >= len(args):
        raise err(f'Wavelet:{fn}:wname', f'{fn} needs a wavelet name or its filters.', fn)
    if is_str(args[i]):
        w = wavelet(opt_str(args[i]), fn)
        return (w.lo_d, w.hi_d, w, i + 1) if kind == 'd' else (w.lo_r, w.hi_r, w, i + 1)
    if i + 1 >= len(args) or is_str(args[i + 1]):
        raise err(f'Wavelet:{fn}:wname', f'{fn} needs a wavelet name or two filters, lowpass and highpass.', fn)
    lo, _ = _vec(args[i], fn, 'A filter')
    hi, _ = _vec(args[i + 1], fn, 'A filter')
    if lo.size != hi.size or lo.size < 2:
        raise err(f'Wavelet:{fn}:filters', 'The two filters must have the same length, at least 2.', fn)
    return lo, hi, None, i + 2


def _orient(v, col):
    v = np.asarray(v, dtype=float).reshape(-1)
    return out(v.reshape(-1, 1) if col else v.reshape(1, -1))


def _lvec(l, fn):
    a = darr(l, fn).reshape(-1)
    if a.size < 2 or np.any(a != np.round(a)) or np.any(a < 0):
        raise err(f'Wavelet:{fn}:bookkeeping', 'The bookkeeping vector l must be whole numbers, as wavedec gives.', fn)
    return [int(v) for v in a]


def _split(c, l, fn):
    """The coefficients of a wavedec vector: cA_N and [cD_N, ..., cD_1]."""
    if sum(l[:-1]) != c.size:
        raise err(f'Wavelet:{fn}:bookkeeping', f'The lengths in l (sum {sum(l[:-1])}) do not match the {c.size} coefficients.', fn)
    parts, k = [], 0
    for n in l[:-1]:
        parts.append(c[k:k + n])
        k += n
    return parts[0], parts[1:]


# ---- filters as functions ----------------------------------------------------------------------------------------

def _row(v):
    return out(np.asarray(v, dtype=float).reshape(1, -1))


@bi('wfilters', nout=4)
def wfilters(nargout, *args):
    """[LoD, HiD, LoR, HiR] = wfilters(wname); [F1, F2] = wfilters(wname, 'd'|'r'|'l'|'h')."""
    nargchk(args, 1, 2, 'wfilters')
    w = wavelet(opt_str(args[0]) or '', 'wfilters')
    if len(args) == 2:
        o = (opt_str(args[1]) or '').lower()
        pair = {'d': (w.lo_d, w.hi_d), 'r': (w.lo_r, w.hi_r), 'l': (w.lo_d, w.lo_r), 'h': (w.hi_d, w.hi_r)}.get(o)
        if pair is None:
            raise err('Wavelet:wfilters:type', "The second input is 'd', 'r', 'l' or 'h'.", 'wfilters')
        return _outs(nargout, *(_row(f) for f in pair))
    return _outs(nargout, *(_row(f) for f in (w.lo_d, w.hi_d, w.lo_r, w.hi_r)))


def _scaling(fam):
    def f(nargout, *args):
        nargchk(args, 1, 1, fam + 'wavf')
        name = (opt_str(args[0]) or '').lower()
        w = wavelet(name, fam + 'wavf')
        if w.family != fam and not (fam == 'db' and w.family == 'haar'):
            raise err(f'Wavelet:{fam}wavf:wname', f"{fam}wavf takes a {fam} wavelet name, as '{fam}4'.", fam + 'wavf')
        return _row(w.lo_r / math.sqrt(2))
    f.__doc__ = f'F = {fam}wavf(wname): the scaling filter of a {fam} wavelet, summing to 1.'
    return f


for _fam in ('db', 'sym', 'coif'):
    bi(_fam + 'wavf')(_scaling(_fam))


@bi('qmf')
def qmf(nargout, *args):
    """Y = qmf(X, P): X reversed with every second sign changed (from the second; from the first when P is odd)."""
    nargchk(args, 1, 2, 'qmf')
    x, col = _vec(args[0], 'qmf', 'The filter')
    p = _int(args[1], 'qmf', 'parity') if len(args) > 1 else 0
    y = x[::-1].copy()
    y[(1 if p % 2 == 0 else 0)::2] *= -1
    return _orient(y, col)


@bi('orthfilt', nout=4)
def orthfilt(nargout, *args):
    """[LoD, HiD, LoR, HiR] = orthfilt(W): the four filters of an orthogonal scaling filter W."""
    nargchk(args, 1, 1, 'orthfilt')
    W, _ = _vec(args[0], 'orthfilt', 'The scaling filter')
    lo_r = W / np.linalg.norm(W)
    lo_d = lo_r[::-1].copy()
    hi_d, hi_r = _highs(lo_d, lo_r)
    return _outs(nargout, *(_row(f) for f in (lo_d, hi_d, lo_r, hi_r)))


@bi('biorfilt', nout=4)
def biorfilt(nargout, *args):
    """[LoD, HiD, LoR, HiR] = biorfilt(DF, RF): the four filters of a biorthogonal pair of scaling filters."""
    nargchk(args, 2, 2, 'biorfilt')
    df, _ = _vec(args[0], 'biorfilt', 'The decomposition filter')
    rf, _ = _vec(args[1], 'biorfilt', 'The reconstruction filter')
    df, rf = np.trim_zeros(df), np.trim_zeros(rf)
    if df.size % 2 != rf.size % 2:
        raise err('Wavelet:biorfilt:lengths', 'The two scaling filters must both have odd or both even lengths.', 'biorfilt')
    df, rf = df / df.sum(), rf / rf.sum()
    L = max(rf.size, df.size)
    L += L % 2
    r2 = math.sqrt(2)
    c = (L / 2 - 1, L / 2) if rf.size % 2 else ((L - 1) / 2, (L - 1) / 2)
    lo_r, lo_d = _place(rf * r2, L, c[0]), _place(df * r2, L, c[1])
    hi_d, hi_r = _highs(lo_d, lo_r)
    return _outs(nargout, *(_row(f) for f in (lo_d, hi_d, lo_r, hi_r)))


@bi('dwtmode')
def dwtmode(nargout, *args):
    """dwtmode(mode) sets the extension mode of the discrete transforms; dwtmode or dwtmode('status') shows it; m = dwtmode('status') gives it."""
    nargchk(args, 0, 2, 'dwtmode')
    quiet = len(args) == 2 and (opt_str(args[1]) or '').lower() == 'nodisp'
    s = (opt_str(args[0]) or '').lower() if args else 'status'
    if s in ('status', 'mode'):
        if nargout:
            return Char.of(MODE[0])
        R.write(f'DWT extension mode: {MODE[0]} ({_MODE_TEXT[MODE[0]]})\n')
        return None
    MODE[0] = _mode_name(args[0], 'dwtmode')
    if not quiet and not nargout:
        R.write(f'DWT extension mode set to {MODE[0]} ({_MODE_TEXT[MODE[0]]})\n')
    return Char.of(MODE[0]) if nargout else None


@bi('wmaxlev')
def wmaxlev(nargout, *args):
    """L = wmaxlev(sz, wname): the largest useful level, floor(log2(n/(length of the filters - 1))), n the smallest of sz."""
    nargchk(args, 2, 2, 'wmaxlev')
    sz = darr(args[0], 'wmaxlev').reshape(-1)
    if sz.size == 0 or np.any(sz < 0) or np.any(sz != np.round(sz)):
        raise err('Wavelet:wmaxlev:size', 'The size must be whole numbers.', 'wmaxlev')
    n = int(sz.min()) if sz.size > 1 else int(sz[0])
    lo, _, _, _ = _filters(args, 1, 'wmaxlev', 'd')
    return float(_maxlev(n, lo.size))


def _maxlev(n, L):
    if L < 2 or n < L - 1 or n < 1:
        return 0
    return max(int(math.floor(math.log2(n / (L - 1)))), 0)


# ---- one dimension ---------------------------------------------------------------------------------------------------

@bi('dwt', nout=2)
def dwt(nargout, *args):
    """[cA, cD] = dwt(x, wname) or dwt(x, LoD, HiD), also with 'mode', m: one level of the discrete wavelet transform."""
    mode, args = _take_mode(args, 'dwt')
    nargchk(args, 2, 3, 'dwt')
    x, col = _vec(args[0], 'dwt')
    if x.size == 0:
        raise err('Wavelet:dwt:empty', 'The signal is empty.', 'dwt')
    lo, hi, _, _ = _filters(args, 1, 'dwt', 'd')
    a, d = dwt_last(x, lo, hi, mode)
    return _outs(nargout, _orient(a, col), _orient(d, col))


@bi('idwt')
def idwt(nargout, *args):
    """x = idwt(cA, cD, wname) or idwt(cA, cD, LoR, HiR), with a length L last (the middle L samples) and 'mode', m."""
    mode, args = _take_mode(args, 'idwt')
    nargchk(args, 3, 5, 'idwt')
    a, ca = _vec(args[0], 'idwt', 'cA')
    d, cd = _vec(args[1], 'idwt', 'cD')
    if a.size == 0 and d.size == 0:
        raise err('Wavelet:idwt:empty', 'cA and cD are both empty.', 'idwt')
    if a.size and d.size and a.size != d.size:
        raise err('Wavelet:idwt:lengths', 'cA and cD must have the same length.', 'idwt')
    lo, hi, _, i = _filters(args, 2, 'idwt', 'r')
    n = _int(args[i], 'idwt', 'length') if i < len(args) else None
    y = idwt_last(a if a.size else None, d if d.size else None, lo, hi, mode, n)
    return _orient(y, ca if a.size else cd)


def _wavedec(x, n, lo, hi, mode):
    """[cA_n, cD_n, ..., cD_1] and the lengths [cA_n, cD_n, ..., cD_1, x]."""
    parts, a = [], x
    for _ in range(n):
        a, d = dwt_last(a, lo, hi, mode)
        parts.insert(0, d)
    parts.insert(0, a)
    return parts, [p.shape[-1] for p in parts] + [x.shape[-1]]


def _waverec(a, ds, l, lo, hi, mode, to=0):
    """The approximation at level `to` from cA_N and the details [cD_N, ..., cD_1] (None for zeros)."""
    N = len(ds)
    for j in range(N, to, -1):
        d = ds[N - j]
        a = idwt_last(a, d, lo, hi, mode, l[N - j + 2])
    return a


@bi('wavedec', nout=2)
def wavedec(nargout, *args):
    """[c, l] = wavedec(x, n, wname) or wavedec(x, n, LoD, HiD): the decomposition to level n, c = [cA_n, cD_n, ..., cD_1]."""
    mode, args = _take_mode(args, 'wavedec')
    nargchk(args, 3, 4, 'wavedec')
    x, col = _vec(args[0], 'wavedec')
    if x.size == 0:
        raise err('Wavelet:wavedec:empty', 'The signal is empty.', 'wavedec')
    n = _int(args[1], 'wavedec')
    lo, hi, _, _ = _filters(args, 2, 'wavedec', 'd')
    parts, l = _wavedec(x, n, lo, hi, mode)
    return _outs(nargout, _orient(np.concatenate(parts), col), _orient(np.array(l, float), col))


@bi('waverec')
def waverec(nargout, *args):
    """x = waverec(c, l, wname) or waverec(c, l, LoR, HiR): the signal again from wavedec's c and l."""
    mode, args = _take_mode(args, 'waverec')
    nargchk(args, 3, 4, 'waverec')
    c, col = _vec(args[0], 'waverec', 'c')
    l = _lvec(args[1], 'waverec')
    lo, hi, _, _ = _filters(args, 2, 'waverec', 'r')
    a, ds = _split(c, l, 'waverec')
    return _orient(_waverec(a, ds, l, lo, hi, mode), col)


@bi('appcoef')
def appcoef(nargout, *args):
    """A = appcoef(c, l, wname, n) or appcoef(c, l, LoR, HiR, n): the approximation coefficients at level n (the deepest by default)."""
    mode, args = _take_mode(args, 'appcoef')
    nargchk(args, 3, 5, 'appcoef')
    c, col = _vec(args[0], 'appcoef', 'c')
    l = _lvec(args[1], 'appcoef')
    lo, hi, _, i = _filters(args, 2, 'appcoef', 'r')
    a, ds = _split(c, l, 'appcoef')
    N = len(ds)
    n = _int(args[i], 'appcoef') if i < len(args) else N
    if n > N:
        raise err('Wavelet:appcoef:level', f'The level must be from 0 to {N}.', 'appcoef')
    return _orient(_waverec(a, ds, l, lo, hi, mode, n), col)


@bi('detcoef', nout=-1)
def detcoef(nargout, *args):
    """D = detcoef(c, l, n): the detail coefficients at level n (1 by default); a vector n gives a cell, or one output each; detcoef(c, l, 'cells') all levels."""
    nargchk(args, 2, 4, 'detcoef')
    words = [opt_str(a).lower() for a in args[2:] if is_str(a)]
    rest = [a for a in args[2:] if not is_str(a)]
    c, col = _vec(args[0], 'detcoef', 'c')
    l = _lvec(args[1], 'detcoef')
    _, ds = _split(c, l, 'detcoef')
    N = len(ds)
    if rest:
        lev = darr(rest[0], 'detcoef').reshape(-1)
    else:
        lev = np.arange(1, N + 1) if 'cells' in words else np.array([1])
    if np.any(lev != np.round(lev)) or np.any(lev < 1) or np.any(lev > N):
        raise err('Wavelet:detcoef:level', f'The levels must be from 1 to {N}.', 'detcoef')
    got = [_orient(ds[N - int(k)], col) for k in lev]
    if nargout > 1:
        if nargout > len(got):
            raise err('Wavelet:detcoef:nargout', 'More outputs than levels asked for.', 'detcoef')
        return tuple(got[:nargout])
    if len(got) == 1 and 'cells' not in words:
        return got[0]
    return Cell.of_list(got, (1, len(got)))


@bi('wrcoef')
def wrcoef(nargout, *args):
    """X = wrcoef('a'|'d', c, l, wname, n) or wrcoef(o, c, l, LoR, HiR, n): the part of the signal from the approximation or details at level n."""
    mode, args = _take_mode(args, 'wrcoef')
    nargchk(args, 4, 6, 'wrcoef')
    o = (opt_str(args[0]) or '').lower()
    if o not in ('a', 'd'):
        raise err('Wavelet:wrcoef:type', "The first input is 'a' (approximation) or 'd' (details).", 'wrcoef')
    c, col = _vec(args[1], 'wrcoef', 'c')
    l = _lvec(args[2], 'wrcoef')
    lo, hi, _, i = _filters(args, 3, 'wrcoef', 'r')
    a, ds = _split(c, l, 'wrcoef')
    N = len(ds)
    n = _int(args[i], 'wrcoef') if i < len(args) else N
    if o == 'a' and n > N or o == 'd' and not 1 <= n <= N:
        raise err('Wavelet:wrcoef:level', f'The level must be from {0 if o == "a" else 1} to {N}.', 'wrcoef')
    if o == 'a':
        keep = [d if j > n else None for j, d in zip(range(N, 0, -1), ds)]
        return _orient(_waverec(a, keep, l, lo, hi, mode), col)
    keep = [d if j == n else None for j, d in zip(range(N, 0, -1), ds)]
    return _orient(_waverec(np.zeros_like(a), keep, l, lo, hi, mode), col)


@bi('upcoef')
def upcoef(nargout, *args):
    """Y = upcoef('a'|'d', x, wname, n, lx) or upcoef(o, x, LoR, HiR, n, lx): x reconstructed n steps (1 by default), its middle lx samples."""
    nargchk(args, 3, 6, 'upcoef')
    o = (opt_str(args[0]) or '').lower()
    if o not in ('a', 'd'):
        raise err('Wavelet:upcoef:type', "The first input is 'a' (approximation) or 'd' (details).", 'upcoef')
    x, col = _vec(args[1], 'upcoef', 'x')
    lo, hi, _, i = _filters(args, 2, 'upcoef', 'r')
    n = _int(args[i], 'upcoef', 'level', 1) if i < len(args) else 1
    lx = _int(args[i + 1], 'upcoef', 'length') if i + 1 < len(args) else None
    y = _upconv(x, lo if o == 'a' else hi)
    for _ in range(n - 1):
        y = _upconv(y, lo)
    return _orient(_keep(y, lx), col)


@bi('wenergy', nout=2)
def wenergy(nargout, *args):
    """[Ea, Ed] = wenergy(c, l): the percentages of the energy in the approximation and in the details of each level (Ed(1) level 1)."""
    nargchk(args, 2, 2, 'wenergy')
    c, _ = _vec(args[0], 'wenergy', 'c')
    l = _lvec(args[1], 'wenergy')
    a, ds = _split(c, l, 'wenergy')
    tot = np.sum(c ** 2)
    if tot == 0:
        raise err('Wavelet:wenergy:zero', 'The coefficients are all zero.', 'wenergy')
    return _outs(nargout, float(100 * np.sum(a ** 2) / tot), _row([100 * np.sum(d ** 2) / tot for d in ds[::-1]]))


# ---- two dimensions --------------------------------------------------------------------------------------------------

def dwt2_(X, lo, hi, mode):
    a, d = dwt_last(X, lo, hi, mode)                   # along the rows
    aa, da = dwt_last(a.T, lo, hi, mode)               # then down the columns
    ad, dd = dwt_last(d.T, lo, hi, mode)
    return aa.T, da.T, ad.T, dd.T                      # cA, cH, cV, cD


def idwt2_(A, H, V, D, lo, hi, mode, size=None):
    m = None if size is None else size[0]
    n = None if size is None else size[1]
    T = (lambda M: None if M is None else M.T)
    lo_ = T(idwt_last(T(A), T(H), lo, hi, mode, m))
    hi_ = T(idwt_last(T(V), T(D), lo, hi, mode, m))
    return idwt_last(lo_, hi_, lo, hi, mode, n)


@bi('dwt2', nout=4)
def dwt2(nargout, *args):
    """[cA, cH, cV, cD] = dwt2(X, wname) or dwt2(X, LoD, HiD), also with 'mode', m: one level in two dimensions."""
    mode, args = _take_mode(args, 'dwt2')
    nargchk(args, 2, 3, 'dwt2')
    X = _mat(args[0], 'dwt2')
    lo, hi, _, _ = _filters(args, 1, 'dwt2', 'd')
    return _outs(nargout, *(out(m) for m in dwt2_(X, lo, hi, mode)))


@bi('idwt2')
def idwt2(nargout, *args):
    """X = idwt2(cA, cH, cV, cD, wname) or idwt2(..., LoR, HiR), with a size S last (the middle S part) and 'mode', m; [] for parts that are zero."""
    mode, args = _take_mode(args, 'idwt2')
    nargchk(args, 5, 7, 'idwt2')
    parts = [None if numel(a) == 0 else _mat(a, 'idwt2', 'A coefficient matrix') for a in args[:4]]
    shapes = {p.shape for p in parts if p is not None}
    if not shapes:
        raise err('Wavelet:idwt2:empty', 'All four coefficient matrices are empty.', 'idwt2')
    if len(shapes) > 1:
        raise err('Wavelet:idwt2:sizes', 'The coefficient matrices must have the same size.', 'idwt2')
    lo, hi, _, i = _filters(args, 4, 'idwt2', 'r')
    size = None
    if i < len(args):
        s = darr(args[i], 'idwt2').reshape(-1)
        size = (int(s[0]), int(s[-1]))
    return out(idwt2_(*parts, lo, hi, mode, size))


def _wavedec2(X, n, lo, hi, mode):
    """The approximation at level n, the details [(H, V, D) at level n, ..., at level 1] and the sizes matrix."""
    dets, A = [], X
    for _ in range(n):
        A, H, V, D = dwt2_(A, lo, hi, mode)
        dets.insert(0, (H, V, D))
    S = [A.shape] + [d[0].shape for d in dets] + [X.shape]
    return A, dets, S


def _pack2(A, dets):
    return np.concatenate([A.reshape(-1, order='F')] + [m.reshape(-1, order='F') for d in dets for m in d])


def _unpack2(C, S, fn):
    S = [tuple(int(v) for v in r) for r in S]
    need = S[0][0] * S[0][1] + 3 * sum(r[0] * r[1] for r in S[1:-1])
    if need != C.size:
        raise err(f'Wavelet:{fn}:bookkeeping', f'The sizes in S account for {need} coefficients, not {C.size}.', fn)
    k = S[0][0] * S[0][1]
    A = C[:k].reshape(S[0], order='F')
    dets = []
    for r in S[1:-1]:
        m = r[0] * r[1]
        dets.append(tuple(C[k + j * m:k + (j + 1) * m].reshape(r, order='F') for j in range(3)))
        k += 3 * m
    return A, dets, S


def _smat(v, fn):
    S = darr(v, fn)
    if S.ndim != 2 or S.shape[1] != 2 or S.shape[0] < 2:
        raise err(f'Wavelet:{fn}:bookkeeping', 'The bookkeeping matrix S has two columns, as wavedec2 gives.', fn)
    return S


def _waverec2(A, dets, S, lo, hi, mode, to=0):
    N = len(dets)
    for j in range(N, to, -1):
        H, V, D = dets[N - j]
        A = idwt2_(A, H, V, D, lo, hi, mode, S[N - j + 2])
    return A


@bi('wavedec2', nout=2)
def wavedec2(nargout, *args):
    """[C, S] = wavedec2(X, n, wname) or wavedec2(X, n, LoD, HiD): C = [A_n(:)' H_n(:)' V_n(:)' D_n(:)' ... D_1(:)'], S the sizes."""
    mode, args = _take_mode(args, 'wavedec2')
    nargchk(args, 3, 4, 'wavedec2')
    X = _mat(args[0], 'wavedec2')
    n = _int(args[1], 'wavedec2')
    lo, hi, _, _ = _filters(args, 2, 'wavedec2', 'd')
    A, dets, S = _wavedec2(X, n, lo, hi, mode)
    return _row(_pack2(A, dets)), out(np.array(S, dtype=float))


@bi('waverec2')
def waverec2(nargout, *args):
    """X = waverec2(C, S, wname) or waverec2(C, S, LoR, HiR): the image again from wavedec2's C and S."""
    mode, args = _take_mode(args, 'waverec2')
    nargchk(args, 3, 4, 'waverec2')
    C, _ = _vec(args[0], 'waverec2', 'C')
    A, dets, S = _unpack2(C, _smat(args[1], 'waverec2'), 'waverec2')
    lo, hi, _, _ = _filters(args, 2, 'waverec2', 'r')
    return out(_waverec2(A, dets, S, lo, hi, mode))


@bi('appcoef2')
def appcoef2(nargout, *args):
    """A = appcoef2(C, S, wname, n) or appcoef2(C, S, LoR, HiR, n): the approximation at level n (the deepest by default)."""
    mode, args = _take_mode(args, 'appcoef2')
    nargchk(args, 3, 5, 'appcoef2')
    C, _ = _vec(args[0], 'appcoef2', 'C')
    A, dets, S = _unpack2(C, _smat(args[1], 'appcoef2'), 'appcoef2')
    lo, hi, _, i = _filters(args, 2, 'appcoef2', 'r')
    N = len(dets)
    n = _int(args[i], 'appcoef2') if i < len(args) else N
    if n > N:
        raise err('Wavelet:appcoef2:level', f'The level must be from 0 to {N}.', 'appcoef2')
    return out(_waverec2(A, dets, S, lo, hi, mode, n))


@bi('detcoef2', nout=3)
def detcoef2(nargout, *args):
    """D = detcoef2('h'|'v'|'d'|'c', C, S, n): details at level n ('c' all three as one row); [H, V, D] = detcoef2('all', C, S, n)."""
    nargchk(args, 4, 4, 'detcoef2')
    o = (opt_str(args[0]) or '').lower()
    C, _ = _vec(args[1], 'detcoef2', 'C')
    _, dets, _ = _unpack2(C, _smat(args[2], 'detcoef2'), 'detcoef2')
    N = len(dets)
    n = _int(args[3], 'detcoef2', 'level', 1)
    if n > N:
        raise err('Wavelet:detcoef2:level', f'The level must be from 1 to {N}.', 'detcoef2')
    H, V, D = dets[N - n]
    if o in ('h', 'v', 'd'):
        return out({'h': H, 'v': V, 'd': D}[o])
    if o in ('c', 'compact'):
        return _row(np.concatenate([m.reshape(-1, order='F') for m in (H, V, D)]))
    if o == 'all':
        return _outs(nargout, out(H), out(V), out(D))
    raise err('Wavelet:detcoef2:type', "The first input is 'h', 'v', 'd', 'all' or 'c'.", 'detcoef2')


@bi('wrcoef2')
def wrcoef2(nargout, *args):
    """X = wrcoef2('a'|'h'|'v'|'d', C, S, wname, n) or with LoR, HiR: the part of the image from that kind of coefficient at level n."""
    mode, args = _take_mode(args, 'wrcoef2')
    nargchk(args, 4, 6, 'wrcoef2')
    o = (opt_str(args[0]) or '').lower()
    if o not in ('a', 'h', 'v', 'd'):
        raise err('Wavelet:wrcoef2:type', "The first input is 'a', 'h', 'v' or 'd'.", 'wrcoef2')
    C, _ = _vec(args[1], 'wrcoef2', 'C')
    A, dets, S = _unpack2(C, _smat(args[2], 'wrcoef2'), 'wrcoef2')
    lo, hi, _, i = _filters(args, 3, 'wrcoef2', 'r')
    N = len(dets)
    n = _int(args[i], 'wrcoef2') if i < len(args) else N
    if o == 'a' and n > N or o != 'a' and not 1 <= n <= N:
        raise err('Wavelet:wrcoef2:level', f'The level must be from {0 if o == "a" else 1} to {N}.', 'wrcoef2')
    if o == 'a':
        keep = [d if j > n else (None, None, None) for j, d in zip(range(N, 0, -1), dets)]
        return out(_waverec2(A, keep, S, lo, hi, mode))
    k = 'hvd'.index(o)
    keep = [tuple(m if (j == n and q == k) else None for q, m in enumerate(d)) for j, d in zip(range(N, 0, -1), dets)]
    return out(_waverec2(np.zeros_like(A), keep, S, lo, hi, mode))


# ---- stationary (undecimated) transform ------------------------------------------------------------------------------

def _up(f, j):
    if j == 1:
        return f
    g = np.zeros((f.size - 1) * 2 ** (j - 1) + 1)
    g[::2 ** (j - 1)] = f
    return g


def _circ(x, f, shift):
    """y[t] = sum_k f[k] x[(t + shift - k) mod N] along the last axis."""
    y = np.zeros(x.shape)
    N = x.shape[-1]
    t = np.arange(N)
    for k in np.nonzero(f)[0]:
        y += f[k] * x[..., (t + shift - k) % N]
    return y


def swt_step(x, lo, hi, j):
    s = lo.size // 2 * 2 ** (j - 1)
    return _circ(x, _up(lo, j), s), _circ(x, _up(hi, j), s)


def iswt_step(a, d, lo, hi, j):
    s = (lo.size // 2 - 1) * 2 ** (j - 1)
    return 0.5 * (_circ(a, _up(lo, j), s) + _circ(d, _up(hi, j), s))


def _swt_len(n, N, fn):
    if N < 1:
        raise err(f'Wavelet:{fn}:level', 'The level must be at least 1.', fn)
    for size in np.atleast_1d(n):
        if size % 2 ** N:
            raise err(f'Wavelet:{fn}:length', f'The length must be a multiple of 2^{N} = {2 ** N} for level {N}.', fn)


@bi('swt', nout=2)
def swt(nargout, *args):
    """[swa, swd] = swt(x, n, wname) or swt(x, n, LoD, HiD): the stationary transform, row i level i; swc = swt(...) is [swd; swa(n,:)]."""
    nargchk(args, 3, 4, 'swt')
    x, _ = _vec(args[0], 'swt')
    N = _int(args[1], 'swt', 'level', 1)
    lo, hi, _, _ = _filters(args, 2, 'swt', 'd')
    _swt_len(x.size, N, 'swt')
    A, D, a = [], [], x
    for j in range(1, N + 1):
        a, d = swt_step(a, lo, hi, j)
        A.append(a)
        D.append(d)
    if nargout < 2:
        return out(np.vstack(D + [A[-1]]))
    return _outs(nargout, out(np.vstack(A)), out(np.vstack(D)))


@bi('iswt')
def iswt(nargout, *args):
    """x = iswt(swa, swd, wname) or iswt(swc, wname), or with LoR, HiR: the inverse of swt."""
    nargchk(args, 2, 4, 'iswt')
    first = darr(args[0], 'iswt')
    if len(args) >= 3 and not is_str(args[1]) and (is_str(args[2]) or len(args) == 4):
        A, D = np.atleast_2d(first), np.atleast_2d(darr(args[1], 'iswt'))
        i = 2
        a = A[-1]
    else:
        C = np.atleast_2d(first)
        A, D = None, C[:-1]
        a = C[-1]
        i = 1
    lo, hi, _, _ = _filters(args, i, 'iswt', 'r')
    if D.shape[1] != a.size:
        raise err('Wavelet:iswt:sizes', 'The approximations and details must have the same length.', 'iswt')
    N = D.shape[0]
    for j in range(N, 0, -1):
        a = iswt_step(a, D[j - 1], lo, hi, j)
    return _row(a)


@bi('swt2', nout=4)
def swt2(nargout, *args):
    """[A, H, V, D] = swt2(X, n, wname): the stationary transform of an image, page k level k; one output: cat(3, H, V, D, A(:,:,n))."""
    nargchk(args, 3, 4, 'swt2')
    X = _mat(args[0], 'swt2')
    N = _int(args[1], 'swt2', 'level', 1)
    lo, hi, _, _ = _filters(args, 2, 'swt2', 'd')
    _swt_len(X.shape, N, 'swt2')
    res = [[], [], [], []]
    a = X
    for j in range(1, N + 1):
        l_, h_ = swt_step(a, lo, hi, j)
        aa, da = swt_step(l_.T, lo, hi, j)
        ad, dd = swt_step(h_.T, lo, hi, j)
        a = aa.T
        for q, m in enumerate((a, da.T, ad.T, dd.T)):
            res[q].append(m)
    A, H, V, D = (np.stack(r, axis=2) for r in res)
    if nargout < 2:
        return out(np.concatenate([H, V, D, A[:, :, -1:]], axis=2))
    return _outs(nargout, out(A), out(H), out(V), out(D))


@bi('iswt2')
def iswt2(nargout, *args):
    """X = iswt2(A, H, V, D, wname) or iswt2(swc, wname), or with LoR, HiR: the inverse of swt2."""
    nargchk(args, 2, 6, 'iswt2')
    if len(args) >= 5:
        A, H, V, D = (np.atleast_3d(darr(a, 'iswt2')) for a in args[:4])
        i = 4
        a = A[:, :, -1]
    else:
        C = np.atleast_3d(darr(args[0], 'iswt2'))
        if (C.shape[2] - 1) % 3:
            raise err('Wavelet:iswt2:sizes', 'swc has 3n + 1 pages, as swt2 gives.', 'iswt2')
        N = (C.shape[2] - 1) // 3
        H, V, D = C[:, :, :N], C[:, :, N:2 * N], C[:, :, 2 * N:3 * N]
        a = C[:, :, -1]
        i = 1
    lo, hi, _, _ = _filters(args, i, 'iswt2', 'r')
    N = H.shape[2]
    for j in range(N, 0, -1):
        l_ = iswt_step(a.T, H[:, :, j - 1].T, lo, hi, j).T
        h_ = iswt_step(V[:, :, j - 1].T, D[:, :, j - 1].T, lo, hi, j).T
        a = iswt_step(l_, h_, lo, hi, j)
    return out(a)


# ---- maximal overlap transform ---------------------------------------------------------------------------------------

def _modwt_filters(args, i, fn):
    if i < len(args) and not (is_str(args[i]) and opt_str(args[i]).lower() == 'reflection') and not (
            not is_str(args[i]) and numel(args[i]) == 1):
        lo, hi, w, i = _filters(args, i, fn, 'r')
        return lo, hi, i
    w = wavelet('sym4', fn)
    return w.lo_r, w.hi_r, i


def _dft_filter(f, N, j):
    """The DFT (length N) of f at level j: F(2^(j-1) k), divided by sqrt(2)."""
    k = np.arange(N)
    e = np.exp(-2j * np.pi * np.outer((2 ** (j - 1) * k) % N, np.arange(f.size)) / N)
    return e @ (f / math.sqrt(2))


@bi('modwt')
def modwt(nargout, *args):
    """w = modwt(x, wname, J) or modwt(x, LoR, HiR, J), with 'reflection': the maximal overlap transform, rows W_1 .. W_J and V_J."""
    nargchk(args, 1, 5, 'modwt')
    refl = any(is_str(a) and opt_str(a).lower() == 'reflection' for a in args)
    args = [a for a in args if not (is_str(a) and opt_str(a).lower() == 'reflection')]
    x, _ = _vec(args[0], 'modwt')
    if x.size < 2:
        raise err('Wavelet:modwt:length', 'The signal needs at least two samples.', 'modwt')
    lo, hi, i = _modwt_filters(args, 1, 'modwt')
    if refl:
        x = np.concatenate([x, x[::-1]])
    N = x.size
    J = _int(args[i], 'modwt', 'level', 1) if i < len(args) else int(math.floor(math.log2(N if not refl else N // 2)))
    if J > math.floor(math.log2(N)):
        raise err('Wavelet:modwt:level', f'The level is at most floor(log2(length)) = {int(math.floor(math.log2(N)))}.', 'modwt')
    V = np.fft.fft(x)
    rows = []
    for j in range(1, J + 1):
        G, H = _dft_filter(lo, N, j), _dft_filter(hi, N, j)
        rows.append(np.real(np.fft.ifft(H * V)))
        V = G * V
    rows.append(np.real(np.fft.ifft(V)))
    return out(np.vstack(rows))


def _imodwt(W, lo, hi):
    J, N = W.shape[0] - 1, W.shape[1]
    V = np.fft.fft(W[-1])
    for j in range(J, 0, -1):
        G, H = _dft_filter(lo, N, j), _dft_filter(hi, N, j)
        V = np.conj(G) * V + np.conj(H) * np.fft.fft(W[j - 1])
    return np.real(np.fft.ifft(V))


@bi('imodwt')
def imodwt(nargout, *args):
    """x = imodwt(w, wname) or imodwt(w, LoR, HiR), with 'reflection' (half the samples): the inverse of modwt."""
    nargchk(args, 1, 4, 'imodwt')
    refl = any(is_str(a) and opt_str(a).lower() == 'reflection' for a in args)
    args = [a for a in args if not (is_str(a) and opt_str(a).lower() == 'reflection')]
    W = np.atleast_2d(darr(args[0], 'imodwt'))
    if W.shape[0] < 2:
        raise err('Wavelet:imodwt:rows', 'w has a row for each level and one for the scaling coefficients, as modwt gives.', 'imodwt')
    lo, hi, _ = _modwt_filters(args, 1, 'imodwt')
    x = _imodwt(W, lo, hi)
    return _row(x[:x.size // 2] if refl else x)


@bi('modwtmra')
def modwtmra(nargout, *args):
    """mra = modwtmra(w, wname) or modwtmra(w, LoR, HiR), with 'reflection': the details D_1 .. D_J and the smooth S_J; they sum to the signal."""
    nargchk(args, 1, 4, 'modwtmra')
    refl = any(is_str(a) and opt_str(a).lower() == 'reflection' for a in args)
    args = [a for a in args if not (is_str(a) and opt_str(a).lower() == 'reflection')]
    W = np.atleast_2d(darr(args[0], 'modwtmra'))
    if W.shape[0] < 2:
        raise err('Wavelet:modwtmra:rows', 'w has a row for each level and one for the scaling coefficients, as modwt gives.', 'modwtmra')
    lo, hi, _ = _modwt_filters(args, 1, 'modwtmra')
    rows = []
    for r in range(W.shape[0]):
        Z = np.zeros_like(W)
        Z[r] = W[r]
        rows.append(_imodwt(Z, lo, hi))
    M = np.vstack(rows)
    return out(M[:, :M.shape[1] // 2] if refl else M)


# ---- wavelet functions -----------------------------------------------------------------------------------------------

def _cascade(lo, g, lev):
    u = _upconv(np.array([1.0]), g)
    for _ in range(lev - 1):
        u = _upconv(u, lo)
    return u * math.sqrt(2 ** lev)


def _wavefun(w, lev):
    """phi and psi (and the decomposition ones of a biorthogonal wavelet) on
    the grid x = (0:n-1)/2^lev, by the cascade algorithm."""
    p = 2 ** lev
    pairs = [(w.lo_r, w.hi_r)] if w.orth else [(w.lo_d[::-1], w.hi_d[::-1]), (w.lo_r, w.hi_r)]
    fs = [_cascade(lo, g, lev) for lo, hi in pairs for g in (lo, hi)]
    n = max((w.L - 1) * p + 1, fs[0].size + 2) if w.orth else (w.L - 1) * p
    res = []
    for f in fs:
        v = np.zeros(n)
        k = min(f.size, n - 1)
        v[1:1 + k] = f[:k]
        res.append(v)
    return res, np.arange(n) / p


@bi('wavefun', nout=5)
def wavefun(nargout, *args):
    """[phi, psi, x] = wavefun(wname, iter) (8 iterations by default); [phi1, psi1, phi2, psi2, x] for a biorthogonal wavelet (1 decomposition, 2 reconstruction)."""
    nargchk(args, 1, 2, 'wavefun')
    w = wavelet(opt_str(args[0]) or '', 'wavefun')
    lev = _int(args[1], 'wavefun', 'number of iterations', 1) if len(args) > 1 else 8
    if lev > 20:
        raise err('Wavelet:wavefun:iter', 'At most 20 iterations.', 'wavefun')
    fs, x = _wavefun(w, lev)
    if nargout == 0:
        names = ['Scaling function', 'Wavelet function'] if w.orth else [
            'Decomposition scaling function', 'Decomposition wavelet', 'Reconstruction scaling function', 'Reconstruction wavelet']
        for i, (f, t) in enumerate(zip(fs, names)):
            _b('subplot', float(len(fs) // 2), 2.0, float(i + 1))
            _b('plot', _row(x), _row(f))
            _b('title', Char.of(f'{w.name}: {t}'))
            _b('grid', Char.of('on'))
        return None
    return _outs(nargout, *(_row(f) for f in fs), _row(x))


def _centfrq(w, lev=8):
    fs, x = _wavefun(w, lev)
    psi = fs[1]
    X = np.abs(np.fft.fft(psi))
    k = int(np.argmax(X[1:psi.size // 2])) + 1
    return k / (x[-1] - x[0])


@bi('centfrq')
def centfrq(nargout, *args):
    """f = centfrq(wname, iter): the centre frequency of the wavelet (cycles per unit), where the spectrum of psi (by wavefun, 8 iterations) is largest."""
    nargchk(args, 1, 3, 'centfrq')
    w = wavelet(opt_str(args[0]) or '', 'centfrq')
    lev = _int(args[1], 'centfrq', 'number of iterations', 1) if len(args) > 1 else 8
    return float(_centfrq(w, lev))


@bi('scal2frq')
def scal2frq(nargout, *args):
    """f = scal2frq(a, wname, delta): the frequencies of scales a, centfrq(wname)./(a*delta) (delta, the sampling period, 1 by default)."""
    nargchk(args, 2, 3, 'scal2frq')
    a = darr(args[0], 'scal2frq')
    w = wavelet(opt_str(args[1]) or '', 'scal2frq')
    delta = float(darr(args[2], 'scal2frq').reshape(-1)[0]) if len(args) > 2 else 1.0
    if np.any(a <= 0) or delta <= 0:
        raise err('Wavelet:scal2frq:positive', 'The scales and the sampling period must be positive.', 'scal2frq')
    return out(_centfrq(w) / (a * delta))


# ---- continuous transform ----------------------------------------------------------------------------------------

class _CWave:
    """An analytic wavelet in frequency (scale 1, radians per sample), its peak 2 at wp."""

    def __init__(self, kind, params=None):
        self.kind = kind
        if kind == 'morse':
            g, p2 = (3.0, 60.0) if params is None else params
            self.g, self.b = g, p2 / g
            self.wp = (self.b / self.g) ** (1 / self.g)
        elif kind == 'amor':
            self.wp = 6.0
        else:
            self.mu, self.sig = 5.0, 0.6
            self.wp = 5.0

    def __call__(self, w):
        w = np.asarray(w, dtype=float)
        out_ = np.zeros_like(w)
        pos = w > 0
        if self.kind == 'morse':
            u = w[pos]
            out_[pos] = 2 * np.exp(self.b * np.log(u / self.wp) - (u ** self.g - self.wp ** self.g))
        elif self.kind == 'amor':
            out_[pos] = 2 * np.exp(-(w[pos] - 6.0) ** 2 / 2)
        else:
            r = (w - self.mu) / self.sig
            m = np.abs(r) < 1
            out_[m] = 2 * np.exp(1 - 1 / (1 - r[m] ** 2))
        return out_

    def cutoff(self, frac=0.5):
        """The frequency above the peak where the wavelet falls to frac of its peak."""
        from scipy.optimize import brentq
        hi = self.wp * 2
        while self(hi) > 2 * frac:
            hi *= 2
        return brentq(lambda w: self(w) - 2 * frac, self.wp, hi)

    def sigma_t(self):
        """The wavelet's standard deviation in time (samples, scale 1), from its spectrum."""
        w = np.linspace(1e-6, self.cutoff(1e-12) * 1.5, 20001)
        P = self(w)
        dP = np.gradient(P, w)
        return math.sqrt(np.sum(dP ** 2) / np.sum(P ** 2))      # Parseval on a uniform grid

    def admissibility(self):
        """C = integral over w > 0 of Psi(w)/w."""
        from scipy.integrate import quad
        lo = 0.0 if self.kind != 'bump' else self.mu - self.sig
        hi = self.cutoff(1e-14)
        import warnings
        from scipy.integrate import IntegrationWarning
        with warnings.catch_warnings():
            # the analytic Morlet's spectrum is not quite zero at 0 (2 exp(-18)): Psi(w)/w has a weak logarithmic singularity
            # there, which quad reports while what it adds stays below 1e-5 of C
            warnings.simplefilter('ignore', IntegrationWarning)
            return quad(lambda w: self(w) / w if w > 0 else 0.0, lo, hi, limit=200)[0]


def _cwt_opts(args, fn):
    names = {'wavelet', 'voicesperoctave', 'frequencylimits', 'periodlimits', 'waveletparameters', 'extendsignal',
             'timebandwidth', 'signalmean', 'scaletype'}
    opts, rest = {}, []
    i = 0
    while i < len(args):
        s = opt_str(args[i])
        if s is not None and s.lower() in names and i + 1 < len(args):
            opts[s.lower()] = args[i + 1]
            i += 2
            continue
        rest.append(args[i])
        i += 1
    return opts, rest


def _cwave(opts, rest, fn):
    kind = 'morse'
    for r in list(rest):
        s = opt_str(r)
        if s is not None and s.lower() in ('morse', 'amor', 'bump'):
            kind = s.lower()
            rest.remove(r)
    for r in rest:
        if is_str(r):
            raise err(f'Wavelet:{fn}:wavelet', f"'{opt_str(r)}' is not a wavelet {fn} has: 'morse', 'amor' or 'bump'.", fn)
    if 'wavelet' in opts:
        kind = (opt_str(opts['wavelet']) or '').lower()
        if kind not in ('morse', 'amor', 'bump'):
            raise err(f'Wavelet:{fn}:wavelet', "The wavelet is 'morse', 'amor' or 'bump'.", fn)
    params = None
    if 'waveletparameters' in opts or 'timebandwidth' in opts:
        if kind != 'morse':
            raise err(f'Wavelet:{fn}:parameters', 'Only the Morse wavelet takes parameters.', fn)
        if 'waveletparameters' in opts:
            pv = darr(opts['waveletparameters'], fn).reshape(-1)
            if pv.size != 2:
                raise err(f'Wavelet:{fn}:parameters', 'WaveletParameters is [gamma, P^2] (the symmetry and the time-bandwidth product).', fn)
            params = (float(pv[0]), float(pv[1]))
        else:
            params = (3.0, float(darr(opts['timebandwidth'], fn).reshape(-1)[0]))
        if params[0] < 1 or params[1] < params[0] or params[1] / params[0] > 40 * params[0]:
            raise err(f'Wavelet:{fn}:parameters', 'The Morse parameters need gamma >= 1 and gamma <= P^2 <= 40 gamma^2.', fn)
    nv = 10
    if 'voicesperoctave' in opts:
        nv = _int(opts['voicesperoctave'], fn, 'number of voices per octave', 1)
        if nv > 48:
            raise err(f'Wavelet:{fn}:voices', 'VoicesPerOctave is from 1 to 48.', fn)
    return _CWave(kind, params), nv


def _scales(wav, N, nv, flim=None):
    """The scales (samples), smallest first: from where the wavelet's spectrum
    falls to half its peak at the Nyquist frequency, up to where two of its
    time standard deviations fill half the signal; nv per octave."""
    s0 = wav.cutoff(0.5) / math.pi
    smax = max(N / (4 * wav.sigma_t()), s0)
    if flim is not None:
        f1, f2 = sorted(flim)             # cycles per sample
        lo = wav.wp / (2 * math.pi * f2) if f2 > 0 else s0
        hi = wav.wp / (2 * math.pi * f1) if f1 > 0 else smax
        s0, smax = max(s0, lo), min(smax, hi)
        if smax < s0:
            raise err('Wavelet:cwt:limits', 'The frequency limits leave no scales.', 'cwt')
    n = int(math.floor(nv * math.log2(smax / s0) + 1e-9)) + 1
    return s0 * 2.0 ** (np.arange(n) / nv)


def _cwt(x, wav, scales, extend=True):
    N = x.size
    if extend:
        p = N // 2
        xe = np.concatenate([x[:p][::-1], x, x[N - (N - p):][::-1]])
        start = p
    else:
        xe, start = x, 0
    M = xe.size
    X = np.fft.fft(xe)
    w = 2 * np.pi * np.fft.fftfreq(M)
    W = np.fft.ifft(X[None, :] * wav(np.outer(scales, w)), axis=1)
    return W[:, start:start + N]


def _fs_arg(rest, fn):
    if not rest:
        return None
    v = rest[0]
    a = darr(v, fn).reshape(-1)
    if a.size != 1 or not a[0] > 0:
        raise err(f'Wavelet:{fn}:fs', 'The sampling rate must be a positive number.', fn)
    return float(a[0])


@bi('cwt', nout=3)
def cwt(nargout, *args):
    """[wt, f, coi] = cwt(x, fs) or cwt(x, wname, fs), with 'VoicesPerOctave', 'FrequencyLimits', 'WaveletParameters', 'ExtendSignal':
    the continuous wavelet transform on an analytic wavelet ('morse', 'amor', 'bump'); no outputs draws the scalogram."""
    nargchk(args, 1, 13, 'cwt')
    opts, rest = _cwt_opts(args[1:], 'cwt')
    x, _ = _vec(args[0], 'cwt')
    if x.size < 4:
        raise err('Wavelet:cwt:length', 'The signal needs at least four samples.', 'cwt')
    if not np.all(np.isfinite(x)):
        raise err('Wavelet:cwt:finite', 'The signal must be finite.', 'cwt')
    wav, nv = _cwave(opts, rest, 'cwt')
    fs = _fs_arg(rest, 'cwt')
    flim = None
    if 'frequencylimits' in opts:
        fl = darr(opts['frequencylimits'], 'cwt').reshape(-1)
        if fl.size != 2 or np.any(fl < 0):
            raise err('Wavelet:cwt:limits', 'FrequencyLimits is two frequencies, 0 or more.', 'cwt')
        flim = fl / (fs if fs else 1.0)
    ext = True
    if 'extendsignal' in opts:
        ext = bool(darr(opts['extendsignal'], 'cwt').reshape(-1)[0])
    scales = _scales(wav, x.size, nv, flim)
    W = _cwt(x, wav, scales, ext)
    f = wav.wp / (2 * np.pi * scales) * (fs if fs else 1.0)
    t = np.arange(x.size)
    edge = np.minimum(t + 1, x.size - t).astype(float)
    coi = wav.wp / (2 * np.pi * edge / (math.sqrt(2) * wav.sigma_t())) * (fs if fs else 1.0)
    coi = np.minimum(coi, f[0])
    if nargout == 0:
        _draw_scalogram(W, f, coi, x.size, fs)
        return None
    return _outs(nargout, out(W), out(f.reshape(-1, 1)), out(coi.reshape(-1, 1)))


def _freq_ticks(ax, y):
    """An axis of log2 frequencies (log-spaced scales drawn evenly) ticked at the powers of 2, labelled with the frequencies."""
    lo, hi = math.floor(y.min()), math.ceil(y.max())
    ticks = np.arange(lo, hi + 1, dtype=float)
    ticks = ticks[(ticks >= y.min() - 1e-9) & (ticks <= y.max() + 1e-9)]
    if ticks.size:
        ax.set_value('YTick', _row(ticks))
        ax.set_value('YTickLabel', Cell.of_list([Char.of(f'{2.0 ** t:.4g}') for t in ticks]))


def _draw_scalogram(W, f, coi, N, fs):
    tt = np.arange(N) / (fs if fs else 1.0)
    y = np.log2(f)
    _b('imagesc', _row(tt), out(y.reshape(-1, 1)), out(np.abs(W)))
    ax = _b('gca')
    _b('axis', Char.of('xy'))
    _b('hold', Char.of('on'))
    _b('plot', _row(tt), _row(np.log2(np.maximum(coi, f[-1]))), Char.of('w--'), Char.of('LineWidth'), 1.5)
    _b('hold', Char.of('off'))
    _freq_ticks(ax, y)
    _b('colorbar')
    _b('title', Char.of('Magnitude scalogram'))
    _b('xlabel', Char.of('Time (s)' if fs else 'Samples'))
    _b('ylabel', Char.of('Frequency (Hz)' if fs else 'Frequency (cycles/sample)'))


@bi('icwt')
def icwt(nargout, *args):
    """xrec = icwt(wt) or icwt(wt, wname, f, freqrange), with 'VoicesPerOctave', 'WaveletParameters', 'SignalMean': the signal from cwt's coefficients."""
    nargchk(args, 1, 12, 'icwt')
    W = darr(args[0], 'icwt')
    if W.ndim != 2 or W.shape[0] < 2:
        raise err('Wavelet:icwt:wt', 'wt is the matrix cwt gives, a row for each scale.', 'icwt')
    opts, rest = _cwt_opts(args[1:], 'icwt')
    wav, nv = _cwave(opts, rest, 'icwt')
    rows = np.arange(W.shape[0])
    if len(rest) >= 2:
        f = darr(rest[0], 'icwt').reshape(-1)
        fr = darr(rest[1], 'icwt').reshape(-1)
        if f.size != W.shape[0] or fr.size != 2:
            raise err('Wavelet:icwt:freqrange', 'f has a frequency for each row of wt, freqrange two frequencies.', 'icwt')
        rows = rows[(f >= fr.min()) & (f <= fr.max())]
    C = wav.admissibility()
    x = 2 / C * (math.log(2) / nv) * np.real(W[rows]).sum(axis=0)
    if 'signalmean' in opts:
        x = x + float(darr(opts['signalmean'], 'icwt').reshape(-1)[0])
    return _row(x)


@bi('cwtfreqbounds', nout=2)
def cwtfreqbounds(nargout, *args):
    """[minf, maxf] = cwtfreqbounds(N, fs), with 'Wavelet', 'VoicesPerOctave', 'WaveletParameters': the frequency range of cwt's scales for N samples."""
    nargchk(args, 1, 8, 'cwtfreqbounds')
    N = _int(args[0], 'cwtfreqbounds', 'number of samples', 4)
    opts, rest = _cwt_opts(args[1:], 'cwtfreqbounds')
    wav, nv = _cwave(opts, rest, 'cwtfreqbounds')
    fs = _fs_arg(rest, 'cwtfreqbounds') or 1.0
    s = _scales(wav, N, nv)
    return _outs(nargout, float(wav.wp / (2 * np.pi * s[-1]) * fs), float(wav.wp / (2 * np.pi * s[0]) * fs))


# ---- thresholds and denoising ------------------------------------------------------------------------------------------

def _thresh(x, sorh, t):
    if sorh == 's':
        return np.sign(x) * np.maximum(np.abs(x) - t, 0)
    return x * (np.abs(x) > t)


@bi('wthresh')
def wthresh(nargout, *args):
    """Y = wthresh(X, 's'|'h', T): soft or hard thresholding of X at T."""
    nargchk(args, 3, 3, 'wthresh')
    X = darr(args[0], 'wthresh')
    sorh = (opt_str(args[1]) or '').lower()
    if sorh not in ('s', 'h'):
        raise err('Wavelet:wthresh:type', "The rule is 's' (soft) or 'h' (hard).", 'wthresh')
    t = darr(args[2], 'wthresh')
    if np.any(t < 0):
        raise err('Wavelet:wthresh:threshold', 'The threshold must be 0 or more.', 'wthresh')
    return out(_thresh(X.astype(float), sorh, t))


_PHI_INV_75 = 0.6744897501960817


def _sigma(d):
    return float(np.median(np.abs(d)) / _PHI_INV_75) if d.size else 0.0


@bi('wnoisest')
def wnoisest(nargout, *args):
    """stdc = wnoisest(c, l, s): the noise's standard deviation at the levels s (1 by default), median(abs(cD))/0.6745."""
    nargchk(args, 2, 3, 'wnoisest')
    c, _ = _vec(args[0], 'wnoisest', 'c')
    l = _lvec(args[1], 'wnoisest')
    _, ds = _split(c, l, 'wnoisest')
    N = len(ds)
    s = darr(args[2], 'wnoisest').reshape(-1) if len(args) > 2 else np.array([1.0])
    if np.any(s < 1) or np.any(s > N) or np.any(s != np.round(s)):
        raise err('Wavelet:wnoisest:level', f'The levels must be from 1 to {N}.', 'wnoisest')
    return _row([_sigma(ds[N - int(k)]) for k in s])


def _sure(x):
    """The threshold that minimizes Stein's unbiased risk estimate of soft thresholding (unit noise)."""
    n = x.size
    if n == 0:
        return 0.0
    sx2 = np.sort(np.abs(x)) ** 2
    risks = (n - 2 * np.arange(1, n + 1) + np.cumsum(sx2) + np.arange(n - 1, -1, -1) * sx2) / n
    return float(math.sqrt(sx2[int(np.argmin(risks))]))


def _thselect(x, rule):
    n = x.size
    if rule == 'sqtwolog':
        return math.sqrt(2 * math.log(n)) if n > 1 else 0.0
    if rule == 'minimaxi':
        return 0.0 if n <= 32 else 0.3936 + 0.1829 * math.log2(n)
    if rule == 'rigrsure':
        return _sure(x)
    eta = (np.sum(x ** 2) - n) / n
    crit = math.log2(n) ** 1.5 / math.sqrt(n) if n > 1 else 0.0
    univ = math.sqrt(2 * math.log(n)) if n > 1 else 0.0
    return univ if eta < crit else min(_sure(x), univ)


_RULES = ('rigrsure', 'heursure', 'sqtwolog', 'minimaxi')


@bi('thselect')
def thselect(nargout, *args):
    """thr = thselect(x, 'rigrsure'|'heursure'|'sqtwolog'|'minimaxi'): a threshold for x with noise of unit variance."""
    nargchk(args, 2, 2, 'thselect')
    x = darr(args[0], 'thselect').reshape(-1).astype(float)
    rule = (opt_str(args[1]) or '').lower()
    if rule not in _RULES:
        raise err('Wavelet:thselect:rule', f"The rule is one of {', '.join(_RULES)}.", 'thselect')
    return float(_thselect(x, rule))


@bi('wden', nout=3)
def wden(nargout, *args):
    """[xd, cxd, lxd] = wden(x, tptr, sorh, scal, n, wname) or wden(c, l, tptr, sorh, scal, n, wname): denoising by thresholds per level
    (tptr 'rigrsure', 'heursure', 'sqtwolog', 'minimaxi'; sorh 's' or 'h'; scal 'one', 'sln' (noise from level 1) or 'mln' (per level))."""
    mode, args = _take_mode(args, 'wden')
    nargchk(args, 6, 7, 'wden')
    if len(args) == 7:
        c, col = _vec(args[0], 'wden', 'c')
        l = _lvec(args[1], 'wden')
        a, ds = _split(c, l, 'wden')
        args = args[2:]
        w = wavelet(opt_str(args[4]) or '', 'wden')
        n = len(ds)
    else:
        x, col = _vec(args[0], 'wden')
        args = args[1:]
        n = _int(args[3], 'wden', 'level', 1)
        w = wavelet(opt_str(args[4]) or '', 'wden')
        parts, l = _wavedec(x, n, w.lo_d, w.hi_d, mode)
        a, ds = parts[0], parts[1:]
    rule = (opt_str(args[0]) or '').lower()
    sorh = (opt_str(args[1]) or '').lower()
    scal = (opt_str(args[2]) or '').lower()
    if rule not in _RULES:
        raise err('Wavelet:wden:rule', f"The threshold rule is one of {', '.join(_RULES)}.", 'wden')
    if sorh not in ('s', 'h'):
        raise err('Wavelet:wden:type', "The thresholding is 's' (soft) or 'h' (hard).", 'wden')
    if scal not in ('one', 'sln', 'mln'):
        raise err('Wavelet:wden:scal', "The noise scaling is 'one', 'sln' or 'mln'.", 'wden')
    s1 = _sigma(ds[-1])
    new = []
    for d in ds:
        s = 1.0 if scal == 'one' else s1 if scal == 'sln' else _sigma(d)
        t = _thselect(d / s, rule) * s if s > 0 else 0.0
        new.append(_thresh(d, sorh, t))
    xd = _waverec(a, new, l, w.lo_r, w.hi_r, mode)
    return _outs(nargout, _orient(xd, col), _orient(np.concatenate([a] + new), col), _orient(np.array(l, float), col))


@bi('ddencmp', nout=4)
def ddencmp(nargout, *args):
    """[thr, sorh, keepapp] = ddencmp('den', 'wv', x): the default denoising threshold sqrt(2 log n) times the noise (from db1's level-1 details), soft, approximation kept."""
    nargchk(args, 3, 3, 'ddencmp')
    if (opt_str(args[0]) or '').lower() != 'den' or (opt_str(args[1]) or '').lower() != 'wv':
        raise err('Wavelet:ddencmp:type', "ddencmp takes 'den' and 'wv' (wavelet denoising).", 'ddencmp')
    x = darr(args[2], 'ddencmp').reshape(-1).astype(float)
    n = x.size
    if n < 2:
        raise err('Wavelet:ddencmp:length', 'The signal needs at least two samples.', 'ddencmp')
    w = wavelet('db1', 'ddencmp')
    _, d = dwt_last(x, w.lo_d, w.hi_d, 'symmetric')
    thr = math.sqrt(2 * math.log(n)) * _sigma(d)
    return _outs(nargout, thr, Char.of('s'), 1.0)


# empirical Bayes (Johnstone and Silverman): a Laplace prior of scale a = 0.5 on the nonzero coefficients

_EB_A = 0.5


def _Phi(z):
    from scipy.special import ndtr
    return ndtr(z)


def _e2(z, a=_EB_A):
    """exp(2 a z) (1 - Phi(z + a)), without overflow (z >= 0)."""
    from scipy.special import erfcx
    return 0.5 * erfcx((z + a) / math.sqrt(2)) * np.exp(-(z - a) ** 2 / 2)


def _beta(z, a=_EB_A):
    """g(z)/phi(z) - 1, g the Laplace prior convolved with the noise."""
    from scipy.special import erfcx
    z = np.abs(z)
    with np.errstate(over='ignore'):
        big = np.exp(np.minimum((z - a) ** 2 / 2, 700.0)) * _Phi(z - a)
    return (a / 2) * math.sqrt(2 * math.pi) * (big + 0.5 * erfcx((z + a) / math.sqrt(2))) - 1


def _post_w(z, w):
    b = _beta(z)
    return w * (1 + b) / (1 + w * b)


def _eb_threshold(w):
    """The value of |z| below which the posterior median is zero, for weight w."""
    def f(z):
        pw = _post_w(np.array([z]), w)[0]
        P = _Phi(z - _EB_A)
        return pw * P / (P + _e2(z)) - 0.5
    lo, hi = 0.0, 50.0
    if f(lo) >= 0:
        return 0.0
    for _ in range(100):
        m = (lo + hi) / 2
        if f(m) < 0:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def _eb_weight(z):
    """The prior weight by marginal maximum likelihood, no smaller than the one whose threshold is sqrt(2 log n)."""
    n = z.size
    b = np.minimum(_beta(z), 1e300)
    univ = math.sqrt(2 * math.log(max(n, 2)))
    lo, hi = 1e-12, 1.0
    for _ in range(80):                       # the weight whose threshold is the universal one
        m = math.sqrt(lo * hi)
        if _eb_threshold(m) > univ:
            lo = m
        else:
            hi = m
    wmin = hi

    def score(w):
        return np.sum(b / (1 + w * b))
    if score(1.0) >= 0:
        return 1.0
    if score(wmin) <= 0:
        return wmin
    lo, hi = wmin, 1.0
    for _ in range(100):
        m = (lo + hi) / 2
        if score(m) > 0:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def _eb_rule(z, w, rule):
    s, az = np.sign(z), np.abs(z)
    if rule in ('hard', 'soft'):
        return _thresh(z, rule[0], _eb_threshold(w))
    pw = _post_w(az, w)
    P = _Phi(az - _EB_A)
    E2 = _e2(az)
    if rule == 'mean':
        return s * pw * (az - _EB_A * (P - E2) / (P + E2))
    from scipy.special import ndtri
    arg = (P + E2) / (2 * np.maximum(pw, 1e-300))
    with np.errstate(invalid='ignore'):
        m = az - _EB_A - ndtri(np.clip(arg, 0, 1))
    m = np.where((arg < P) & (m > 0), m, 0.0)
    return s * np.minimum(m, az)


def _fdr_threshold(z, q):
    from scipy.special import ndtri
    m = z.size
    p = np.sort(2 * (1 - _Phi(np.abs(z))))
    ok = np.nonzero(p <= q * np.arange(1, m + 1) / m)[0]
    if not ok.size:
        return float(np.max(np.abs(z))) if m else 0.0
    return float(ndtri(1 - p[ok[-1]] / 2))


def _blockjs(d, s):
    n = d.size
    L = max(int(math.floor(math.log(max(n, 2)))), 1)
    lam = 4.50524
    out_ = d.copy()
    for k in range(0, n, L):
        blk = d[k:k + L]
        S2 = np.sum(blk ** 2)
        out_[k:k + L] = blk * max(0.0, 1 - lam * blk.size * s ** 2 / S2) if S2 > 0 else 0.0
    return out_


_METHODS = {'bayes': 'Bayes', 'sure': 'SURE', 'universalthreshold': 'UniversalThreshold', 'minimax': 'Minimax',
            'fdr': 'FDR', 'blockjs': 'BlockJS'}


def _wdenoise1(x, lev, w, method, q, rule, levdep):
    parts, l = _wavedec(x, lev, w.lo_d, w.hi_d, 'symmetric')
    a, ds = parts[0], parts[1:]
    s1 = _sigma(ds[-1])
    N = x.size
    new = []
    for d in ds:
        s = _sigma(d) if levdep else s1
        if s <= 0:
            new.append(d.copy())
            continue
        z = d / s
        if method == 'Bayes':
            r = _eb_rule(z, _eb_weight(z), rule)
        elif method == 'BlockJS':
            r = _blockjs(z, 1.0)
        else:
            t = (_sure(z) if method == 'SURE' else math.sqrt(2 * math.log(N)) if method == 'UniversalThreshold'
                 else _thselect(np.zeros(N), 'minimaxi') if method == 'Minimax' else _fdr_threshold(z, q))
            r = _thresh(z, rule[0], t)
        new.append(r * s)
    return _waverec(a, new, l, w.lo_r, w.hi_r, 'symmetric'), new, ds, a


@bi('wdenoise', nout=3)
def wdenoise(nargout, *args):
    """[xden, dcfs, ocfs] = wdenoise(x, level) with 'Wavelet' ('sym4'), 'DenoisingMethod' ('Bayes', 'SURE', 'UniversalThreshold', 'Minimax',
    'BlockJS', 'FDR' or {'FDR', q}), 'ThresholdRule', 'NoiseEstimate' ('LevelIndependent' or 'LevelDependent'): wavelet denoising; columns of a matrix one by one."""
    nargchk(args, 1, 10, 'wdenoise')
    X = darr(args[0], 'wdenoise')
    if X.ndim != 2 or X.size == 0:
        raise err('Wavelet:wdenoise:signal', 'The signal is a vector, or a matrix of signals in its columns.', 'wdenoise')
    if not np.all(np.isfinite(X)) or np.iscomplexobj(X):
        raise err('Wavelet:wdenoise:finite', 'The signal must be real and finite.', 'wdenoise')
    row = X.shape[0] == 1
    rest = list(args[1:])
    lev = None
    if rest and not is_str(rest[0]):
        lev = _int(rest.pop(0), 'wdenoise', 'level', 1)
    opts = {}
    names = {'wavelet', 'denoisingmethod', 'thresholdrule', 'noiseestimate'}
    while rest:
        s = opt_str(rest[0])
        if s is None or s.lower() not in names or len(rest) < 2:
            raise err('Wavelet:wdenoise:option', "The options are 'Wavelet', 'DenoisingMethod', 'ThresholdRule' and 'NoiseEstimate'.", 'wdenoise')
        opts[s.lower()] = rest[1]
        rest = rest[2:]
    w = wavelet(opt_str(opts.get('wavelet', Char.of('sym4'))) or '', 'wdenoise')
    q = 0.05
    m = opts.get('denoisingmethod', Char.of('Bayes'))
    if isinstance(m, Cell):
        items = m.items()
        m, q = items[0], float(darr(items[1], 'wdenoise').reshape(-1)[0]) if len(items) > 1 else 0.05
        if not 0 < q < 1:
            raise err('Wavelet:wdenoise:fdr', 'The FDR rate q is between 0 and 1.', 'wdenoise')
    method = _METHODS.get((opt_str(m) or '').lower())
    if method is None:
        raise err('Wavelet:wdenoise:method', "DenoisingMethod is 'Bayes', 'SURE', 'UniversalThreshold', 'Minimax', 'BlockJS' or 'FDR'.", 'wdenoise')
    allowed = {'Bayes': ('median', 'mean', 'soft', 'hard'), 'BlockJS': ('james-stein',), 'FDR': ('hard',)}.get(method, ('soft', 'hard'))
    rule = (opt_str(opts.get('thresholdrule', Char.of(allowed[0]))) or '').lower()
    if rule not in allowed:
        raise err('Wavelet:wdenoise:rule', f"For {method} the ThresholdRule is {' or '.join(repr(r.title()) for r in allowed)}.", 'wdenoise')
    ne = (opt_str(opts.get('noiseestimate', Char.of('LevelIndependent'))) or '').lower()
    if ne not in ('levelindependent', 'leveldependent'):
        raise err('Wavelet:wdenoise:noise', "NoiseEstimate is 'LevelIndependent' or 'LevelDependent'.", 'wdenoise')
    res, dc, oc = [], None, None
    for x in (X if row else X.T).astype(float):
        L = lev if lev is not None else max(1, min(int(math.floor(math.log2(x.size))), _maxlev(x.size, w.L)))
        if x.size < 2:
            raise err('Wavelet:wdenoise:length', 'A signal needs at least two samples.', 'wdenoise')
        xd, new, ds, a = _wdenoise1(x, L, w, method, q, rule, ne == 'leveldependent')
        res.append(xd)
        if dc is None:
            dc = Cell.of_list([_orient(d, True) for d in new[::-1]] + [_orient(a, True)], (1, len(new) + 1))
            oc = Cell.of_list([_orient(d, True) for d in ds[::-1]] + [_orient(a, True)], (1, len(ds) + 1))
    Y = np.array(res)
    Y = Y if row else Y.T
    if nargout == 0:
        t = _row(np.arange(1, (X.size if row else X.shape[0]) + 1))
        _b('plot', t, out(X.T if row else X), Char.of('Color'), _row([0.7, 0.7, 0.7]))
        _b('hold', Char.of('on'))
        _b('plot', t, out(Y.T if row else Y), Char.of('LineWidth'), 1.5)
        _b('hold', Char.of('off'))
        _b('legend', Char.of('Original'), Char.of('Denoised'))
        _b('title', Char.of(f'Denoised by {method}, {w.name}'))
        return None
    return _outs(nargout, out(Y), dc, oc)


@bi('wcodemat')
def wcodemat(nargout, *args):
    """Y = wcodemat(X, nb, opt, absol): X coded as whole numbers 1..nb (16) for display, over the whole matrix ('mat'), each row ('row') or column ('col'), of abs(X) unless absol is 0."""
    nargchk(args, 1, 4, 'wcodemat')
    X = darr(args[0], 'wcodemat').astype(float)
    nb = _int(args[1], 'wcodemat', 'number of codes', 1) if len(args) > 1 else 16
    opt = (opt_str(args[2]) or 'mat').lower() if len(args) > 2 else 'mat'
    absol = bool(darr(args[3], 'wcodemat').reshape(-1)[0]) if len(args) > 3 else True
    if opt not in ('mat', 'row', 'col', 'r', 'c', 'm'):
        raise err('Wavelet:wcodemat:opt', "opt is 'mat', 'row' or 'col'.", 'wcodemat')
    Y = np.abs(X) if absol else X
    ax = None if opt in ('mat', 'm') else 1 if opt in ('row', 'r') else 0
    lo = Y.min(axis=ax, keepdims=ax is not None) if Y.size else 0
    hi = Y.max(axis=ax, keepdims=ax is not None) if Y.size else 0
    span = np.where(hi - lo > 0, hi - lo, 1)
    return out(np.minimum(np.floor(nb * (Y - lo) / span) + 1, nb))
