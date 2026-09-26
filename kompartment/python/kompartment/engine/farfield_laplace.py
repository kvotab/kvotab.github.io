"""The far-field path solved in the Laplace domain: the semi-analytical
alternative to the cells of :mod:`kompartment.engine.farfield`.

A port of ``src/domain/farfield-laplace.js``, algorithm for algorithm and
decision for decision, so that the two agree to rounding. That file explains
the method; in short:

* the path is advection and dispersion along a fracture (TW, Pe) with
  sorption on its coating (Kd,f: Rf = 1 + Kd,f aw, aw = F/TW), diffusion into
  the rock matrix beside it (eps_m, rho_m, Kd,m, De,m, depth PENDEP, which may
  be unlimited), and decay and ingrowth along the model's decay network (the
  builder's decay table: ingrowth coefficient k_ij, lower triangular once the
  nuclides are ordered parents first);
* with A = sI + Lambda, M = De^-1 A Rm and tau(z) = sqrt(z) tanh(x0 sqrt(z)),
  G = A Rf + aw De tau(M) and the transfer matrix from inflow to release is
  T(s) = H(G), H(g) = exp((Pe/2)(1 - sqrt(1 + 4 TW g/Pe))), exp(-TW g) for
  plug flow; the path's inventory has K(s) = A^-1 (I - T(s));
* tau(M) and H(G) are functions of triangular matrices: Parlett's recurrence,
  or sums over decay paths of divided differences from Taylor series where
  diagonal entries cluster;
* inversion along a parabola through the saddle point on the real axis, with
  Talbot's contour and de Hoog's method as checks; responses tabulated with
  their first two derivatives on adaptive grids, quintic Hermite between
  samples; the exact convolution of a piecewise-linear inflow.

The complex arithmetic is Python's own complex type, with the application's
formulas for the square root, tanh and division (Smith's, which is also
CPython's); the exponential and trigonometric functions are the C library's
rather than V8's, which is where the last digits part.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

__all__ = [
    'LaplacePathError', 'LaplacePath', 'MAX_BLOCK', 'KINDS', 'decay_table', 'prepare_path', 'transfer',
    'inventory_transfer', 'transfer_at_zero', 'pairs', 'response_at', 'unit_response', 'unit_responses',
    'inflow_series', 'convolve', 'release_at', 'inventory_at',
]


class LaplacePathError(ValueError):
    """A path this method cannot solve, and why."""


#: The largest set of nuclides one pair's transform couples.
MAX_BLOCK = 16

#: Which transform: what leaves the path, or what it holds.
KINDS = ('release', 'inventory')

RELEASE = 0
# What the path holds: K = A^-1 (I - T), inverted whole where most of a pulse
# has left, and otherwise as e^(-Lambda t) minus the inverse of A^-1 T -- the
# decayed cumulative release, DECAYED -- which has a saddle of its own.
INVENTORY = 1
DECAYED = 2

PI = math.pi
EPS = 2.220446049250313e-16
INF = math.inf
NAN = math.nan
CNAN = complex(NAN, NAN)


# ---------------------------------------------------------------------------
# Complex arithmetic, with JavaScript's answers where Python would raise
# ---------------------------------------------------------------------------

def _exp(x: float) -> float:
    """``Math.exp``: Infinity past the largest double, not OverflowError."""
    try:
        return math.exp(x)
    except OverflowError:
        return INF


def _cdiv(a: complex, b: complex) -> complex:
    """Smith's division, as the application does it; NaN for 0/0."""
    ar = a.real
    ai = a.imag
    br = b.real
    bi = b.imag
    if abs(br) >= abs(bi):
        if br == 0.0:
            return CNAN
        r = bi / br
        d = br + bi * r
        return complex((ar + ai * r) / d, (ai - ar * r) / d)
    r = br / bi
    d = bi + br * r
    return complex((ar * r + ai) / d, (ai * r - ar) / d)


def _csqrt(z: complex) -> complex:
    """The principal square root; the cut is the negative real axis."""
    ar = z.real
    ai = z.imag
    if ai == 0:
        if ar >= 0:
            return complex(math.sqrt(ar), 0.0)
        if ar != ar:
            return CNAN
        return complex(0.0, math.sqrt(-ar))
    m = math.hypot(ar, ai)
    if ar >= 0:
        t = math.sqrt(0.5 * (m + ar))
        return complex(t, ai / (2 * t))
    if m != m:
        return CNAN
    t = math.sqrt(0.5 * (m - ar))
    return complex(abs(ai) / (2 * t), t if ai >= 0 else -t)


def _cexp(z: complex) -> complex:
    e = _exp(z.real)
    y = z.imag
    if y - y != 0:
        return CNAN
    return complex(e * math.cos(y), e * math.sin(y))


def _ctanh(z: complex) -> complex:
    """tanh, accurate for small arguments and safe for large ones."""
    ar = z.real
    ai = z.imag
    sg = 1.0
    if ar < 0:
        ar = -ar
        ai = -ai
        sg = -1.0
    if ar > 18:
        e = 2 * math.exp(-2 * ar)
        return complex(sg * (1 - e * math.cos(2 * ai)), sg * (e * math.sin(2 * ai)))
    d = math.cosh(2 * ar) + math.cos(2 * ai)
    return complex(sg * math.sinh(2 * ar) / d, sg * math.sin(2 * ai) / d)


def _csech2(z: complex) -> complex:
    """sech^2 = 1 - tanh^2, without the cancellation near tanh = 1."""
    ar = z.real
    ai = z.imag
    if ar < 0:
        ar = -ar
        ai = -ai
    e1 = math.exp(-ar)
    e2 = e1 * e1
    w = complex(e2 * math.cos(2 * ai), -e2 * math.sin(2 * ai))
    num = complex(2 * e1 * math.cos(ai), -2 * e1 * math.sin(ai))
    s = _cdiv(num, 1 + w)
    return complex(s.real * s.real - s.imag * s.imag, 2 * s.real * s.imag)


# ---------------------------------------------------------------------------
# The settings, checked and turned into per-nuclide constants
# ---------------------------------------------------------------------------

NUCLIDE_KEYS = ('kd_f', 'eps_m', 'kd_m', 'de_m')


def _is_list(v: Any) -> bool:
    return isinstance(v, (list, tuple)) or (hasattr(v, 'shape') and getattr(v, 'ndim', 0) > 0)


def decay_table(lambdas: Sequence[float], pairs_: Sequence[Tuple[int, int, float]] = ()) -> Dict[str, List[Any]]:
    """A decay table in the builder's layout -- ``lam``, ``ioff``, ``icnt``,
    ``ipar``, ``icoef`` -- from decay constants and (parent, daughter,
    coefficient) triples, the coefficient being the ingrowth coefficient
    itself."""
    n = len(lambdas)
    by_daughter: List[List[Tuple[int, float]]] = [[] for _ in range(n)]
    for p, d, c in pairs_:
        by_daughter[d].append((p, c))
    ioff: List[int] = []
    icnt: List[int] = []
    ipar: List[int] = []
    icoef: List[float] = []
    for k in range(n):
        ioff.append(len(ipar))
        for p, c in by_daughter[k]:
            ipar.append(int(p))
            icoef.append(float(c))
        icnt.append(len(by_daughter[k]))
    return {'lam': [float(x) for x in lambdas], 'ioff': ioff, 'icnt': icnt, 'ipar': ipar, 'icoef': icoef}


class _DD:
    """Divided differences over subsets of points, and their scratch."""

    def __init__(self, nmax: int) -> None:
        self.n = 0
        self.kind = 0
        self.d = 0j
        self.E = 0.0
        self.t = 0.0
        self.z = [0j] * nmax
        self.f = [0j] * nmax
        self.sc = [0.0] * nmax
        self.cl = [0] * nmax
        self.dist = [0.0] * (nmax * nmax)
        self.memo: Dict[int, complex] = {}
        self.ncl = 0
        self.cl_mask = [0] * nmax
        self.cl_c = [0j] * nmax
        self.cl_ok = [False] * nmax
        self.cl_k = [-1] * nmax
        self.cl_coef: List[List[complex]] = [[] for _ in range(nmax)]


class _Workspace:
    def __init__(self, nmax: int) -> None:
        nn = nmax * nmax
        self.a = [0j] * nmax
        self.mz = [0j] * nmax
        self.tz = [0j] * nmax
        self.g = [0j] * nmax
        self.v = [0j] * nmax
        self.col = [0.0] * nmax
        self.L = [0j] * nn
        self.T = [0j] * nn
        self.F = [0j] * nn
        self.E = 0.0
        self.dd = _DD(nmax)
        self.clustered = 0
        self.evaluations = 0


class _Block:
    """The block of a pair (i, j): the nuclides on some decay path from j to
    i, parents first; local index 0 is j and the last is i."""

    __slots__ = ('i', 'j', 'S', 'm', 'A', 'lam', 'Rf', 'Rm', 'De', 'Rmin', 'matrix', 's0')

    def __init__(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


class LaplacePath:
    """A path, ready to be solved: see :func:`prepare_path`."""

    def __init__(self) -> None:
        self.n = 0
        self.names: List[str] = []
        self.tw = 0.0
        self.f = 0.0
        self.Pe = 0.0
        self.inf_pe = False
        self.aw = 0.0
        self.x0 = 0.0
        self.inf_x0 = False
        self.rho = 0.0
        self.lam: List[float] = []
        self.Rf: List[float] = []
        self.Rm: List[float] = []
        self.De: List[float] = []
        self.matrix: List[int] = []
        self.parents: List[List[List[Any]]] = []
        self.order: List[int] = []
        self.pos: List[int] = []
        self.reach: List[List[int]] = []
        self.max_block = 1
        self.blocks: Dict[int, Optional[_Block]] = {}
        self.axes: Dict[Tuple[int, int, int], Dict[str, Any]] = {}
        self.ws: _Workspace = _Workspace(1)


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return NAN


def prepare_path(settings: Dict[str, Any], decay: Optional[Dict[str, Any]] = None, n: Optional[int] = None,
                 names: Optional[Sequence[str]] = None) -> LaplacePath:
    """A path, ready to be solved.

    ``settings`` holds the block's settings as numbers: ``tw``, ``rho_m``,
    ``pe`` and ``pen_dep`` once for the path, and ``kd_f``, ``eps_m``,
    ``kd_m``, ``de_m`` once or one per nuclide. The wetted surface is given as
    the block gives it: ``surface`` 'f' (the default) reads F, a_w = F/TW;
    'aw' reads a_w; 'aperture' reads the aperture delta, a_w = 2/delta. ``pe``
    and ``pen_dep`` may be infinite (plug flow, an unlimited matrix).
    ``decay`` is the builder's decay table for the path's nuclide list, or
    None for species that neither decay nor grow in.
    """
    if n is None and decay:
        n = len(decay['lam'])
    if n is None:
        for key in NUCLIDE_KEYS:
            if _is_list(settings.get(key)):
                n = len(settings[key])
    if n is None:
        n = 1
    if not n >= 1:
        raise LaplacePathError('A path needs at least one species to carry.')
    nm = list(names) if names is not None else [f'#{k + 1}' for k in range(n)]

    def one(key: str) -> float:
        v = _num(settings.get(key))
        if v != v:
            raise LaplacePathError(f'{key} must be a number (got {settings.get(key)})')
        return v

    def each(key: str) -> List[float]:
        v = settings.get(key)
        out = []
        for k in range(n):
            x = _num(v[k] if _is_list(v) else v)
            if not math.isfinite(x) or x < 0:
                raise LaplacePathError(
                    f'{key} of {nm[k]} must be zero or a positive number (got {v[k] if _is_list(v) else v})')
            out.append(x)
        return out

    tw = one('tw')
    rho = one('rho_m')
    Pe = one('pe')
    x0 = one('pen_dep')
    if not tw > 0 or not math.isfinite(tw):
        raise LaplacePathError(f'The travel time TW must be a positive number (got {tw})')
    surface = settings.get('surface') or 'f'
    if surface == 'aw':
        aw = one('aw')
        if not aw >= 0 or not math.isfinite(aw):
            raise LaplacePathError(f'The flow-wetted surface a_w must be zero or positive (got {aw})')
    elif surface == 'aperture':
        delta = one('aperture')
        if not delta > 0:
            raise LaplacePathError(f'The fracture aperture must be a positive length (got {delta})')
        aw = 2 / delta
    elif surface == 'f':
        f0 = one('f')
        if not f0 >= 0 or not math.isfinite(f0):
            raise LaplacePathError(f'The flow-related transport resistance F must be zero or positive (got {f0})')
        aw = f0 / tw
    else:
        raise LaplacePathError(f"Unknown way of giving the wetted surface '{surface}'")
    f = aw * tw
    if not Pe > 0:
        raise LaplacePathError(f'The Peclet number must be greater than zero (got {Pe})')
    if not x0 > 0:
        raise LaplacePathError(f'The depth into the matrix must be a positive length, or Infinity (got {x0})')
    if not rho >= 0 or not math.isfinite(rho):
        raise LaplacePathError(f'The rock density must be zero or positive (got {rho})')
    kd_f = each('kd_f')
    eps = each('eps_m')
    kd_m = each('kd_m')
    De = each('de_m')
    Rf = [0.0] * n
    Rm = [0.0] * n
    matrix = [0] * n
    for k in range(n):
        Rf[k] = 1 + kd_f[k] * aw
        Rm[k] = eps[k] + rho * kd_m[k]
        if aw > 0 and De[k] > 0 and not Rm[k] > 0:
            raise LaplacePathError(
                f'The matrix capacity eps + rho*Kd of {nm[k]} must be greater than zero: a rock with no porosity '
                'and no sorption has nothing for it to diffuse into.')
        matrix[k] = 1 if aw > 0 and De[k] > 0 else 0

    lam = [0.0] * n
    parents: List[List[List[Any]]] = [[] for _ in range(n)]
    if decay:
        if len(decay['lam']) < n:
            raise LaplacePathError('The decay table is shorter than the nuclide list.')
        for i in range(n):
            lam[i] = float(decay['lam'][i])
            if not math.isfinite(lam[i]) or lam[i] < 0:
                raise LaplacePathError(f'The decay constant of {nm[i]} must be zero or positive (got {lam[i]})')
            o = int(decay['ioff'][i])
            for q in range(int(decay['icnt'][i])):
                p = int(decay['ipar'][o + q])
                c = float(decay['icoef'][o + q])
                if not math.isfinite(c) or c < 0:
                    raise LaplacePathError(f'The ingrowth of {nm[i]} from {nm[p]} must be zero or positive (got {c})')
                if c == 0:
                    continue
                if p == i:
                    raise LaplacePathError(f'{nm[i]} is its own parent.')
                had = next((e for e in parents[i] if e[0] == p), None)
                if had:
                    had[1] += c
                else:
                    parents[i].append([p, c])
    indeg = [0] * n
    children: List[List[int]] = [[] for _ in range(n)]
    for i in range(n):
        for p, _ in parents[i]:
            children[p].append(i)
            indeg[i] += 1
    order: List[int] = []
    taken = [False] * n
    for _ in range(n):
        pick = -1
        for k in range(n):
            if not taken[k] and indeg[k] == 0:
                pick = k
                break
        if pick < 0:
            break
        taken[pick] = True
        order.append(pick)
        for c in children[pick]:
            indeg[c] -= 1
    if len(order) < n:
        raise LaplacePathError('The decay network closes on itself, so it has no order to solve it in.')
    pos = [0] * n
    for p, k in enumerate(order):
        pos[k] = p
    reach = [[0] * n for _ in range(n)]
    for p in range(n - 1, -1, -1):
        k = order[p]
        reach[k][k] = 1
        for c in children[k]:
            rc = reach[c]
            rk = reach[k]
            for l in range(n):
                if rc[l]:
                    rk[l] = 1
    for i in range(n):
        for p, _ in parents[i]:
            if matrix[p] != matrix[i]:
                inside, outside = (nm[p], nm[i]) if matrix[p] else (nm[i], nm[p])
                raise LaplacePathError(
                    f'{outside} does not diffuse into the matrix (De = 0) while {inside}, which it decays '
                    f"{'from' if matrix[p] else 'into'}, does: give it a small De, or use the discretised path.")
    inf_pe = not math.isfinite(Pe)
    if inf_pe:
        for k in range(n):
            if not matrix[k]:
                raise LaplacePathError(
                    f'Plug flow (Pe = Infinity) needs matrix diffusion for every nuclide: without it {nm[k]} '
                    'leaves as a pulse with no width at all.')
    max_block = 1
    for j in range(n):
        for i in range(n):
            if i == j or not reach[j][i]:
                continue
            m = sum(1 for k in range(n) if reach[j][k] and reach[k][i])
            if m > MAX_BLOCK:
                raise LaplacePathError(
                    f'{m} nuclides lie on the decay paths from {nm[j]} to {nm[i]}; at most {MAX_BLOCK} can be '
                    'solved together.')
            max_block = max(max_block, m)
    path = LaplacePath()
    path.n = n
    path.names = nm
    path.tw = tw
    path.f = f
    path.Pe = Pe
    path.inf_pe = inf_pe
    path.aw = aw
    path.x0 = x0
    path.inf_x0 = not math.isfinite(x0)
    path.rho = rho
    path.lam = lam
    path.Rf = Rf
    path.Rm = Rm
    path.De = De
    path.matrix = matrix
    path.parents = parents
    path.order = order
    path.pos = pos
    path.reach = reach
    path.max_block = max_block
    path.ws = _Workspace(max_block)
    return path


# ---------------------------------------------------------------------------
# The two scalar functions, their Taylor series and length scales
# ---------------------------------------------------------------------------

def _tau_at(path: LaplacePath, z: complex) -> complex:
    u = _csqrt(z)
    if path.inf_x0:
        return u
    return u * _ctanh(path.x0 * u)


def _tau_scale(path: LaplacePath, z: complex) -> float:
    zr = z.real
    zi = z.imag
    sc = math.hypot(zr, zi)
    if not path.inf_x0:
        a = PI / path.x0
        n0 = 0
        if zr < 0:
            n0 = max(0, math.floor(math.sqrt(-zr) / a - 0.5))
        for n in range(max(0, n0 - 1), n0 + 2):
            zp = -((n + 0.5) * a) * ((n + 0.5) * a)
            d = math.hypot(zr - zp, zi)
            if d < sc:
                sc = d
    return sc


def _phi_at(path: LaplacePath, g: complex, d: complex) -> complex:
    tw = path.tw
    if path.inf_pe:
        return complex(-tw * (g.real - d.real), -tw * (g.imag - d.imag))
    B = 4 * tw / path.Pe
    S = _csqrt(complex(1 + B * g.real, B * g.imag))
    return _cdiv(complex(-2 * tw * g.real, -2 * tw * g.imag), complex(1 + S.real, S.imag))


def _h_scale(path: LaplacePath, g: complex) -> float:
    tw = path.tw
    if path.inf_pe:
        return 1 / tw
    B = 4 * tw / path.Pe
    S = math.sqrt(math.hypot(1 + B * g.real, B * g.imag))
    return min(S / tw, S * S / B)


def _binom_half() -> List[float]:
    b = [0.0] * 260
    b[0] = 1.0
    for n in range(1, 260):
        b[n] = b[n - 1] * (0.5 - (n - 1)) / n
    return b


BINOM_HALF = _binom_half()


def _sqrt_series(A: complex, B: complex, K: int) -> List[complex]:
    """Taylor coefficients of sqrt(A + B w) about w = 0."""
    s0 = _csqrt(A)
    q = _cdiv(B, A)
    qr = q.real
    qi = q.imag
    pr = s0.real
    pi = s0.imag
    out = [0j] * (K + 1)
    for n in range(K + 1):
        out[n] = complex(BINOM_HALF[n] * pr, BINOM_HALF[n] * pi)
        t = pr * qr - pi * qi
        pi = pr * qi + pi * qr
        pr = t
    return out


def _tau_series(path: LaplacePath, c: complex, K: int) -> List[complex]:
    s1 = _sqrt_series(c, 1 + 0j, K)
    if path.inf_x0:
        return s1
    x0 = path.x0
    s2 = [0j] * (K + 1)
    s3 = [0j] * (K + 1)
    s2[0] = _ctanh(complex(x0 * s1[0].real, x0 * s1[0].imag))
    s3[0] = _csech2(complex(x0 * s1[0].real, x0 * s1[0].imag))
    for n in range(1, K + 1):
        ar = 0.0
        ai = 0.0
        for k in range(1, n + 1):
            vr = k * x0 * s1[k].real
            vi = k * x0 * s1[k].imag
            q = s3[n - k]
            ar += vr * q.real - vi * q.imag
            ai += vr * q.imag + vi * q.real
        s2[n] = complex(ar / n, ai / n)
        br = 0.0
        bi = 0.0
        for k in range(n + 1):
            a = s2[k]
            b = s2[n - k]
            br += a.real * b.real - a.imag * b.imag
            bi += a.real * b.imag + a.imag * b.real
        s3[n] = complex(-br, -bi)
    out = [0j] * (K + 1)
    for n in range(K + 1):
        ar = 0.0
        ai = 0.0
        for k in range(n + 1):
            a = s1[k]
            b = s2[n - k]
            ar += a.real * b.real - a.imag * b.imag
            ai += a.real * b.imag + a.imag * b.real
        out[n] = complex(ar, ai)
    return out


def _h_series(path: LaplacePath, c: complex, d: complex, E: float, K: int) -> List[complex]:
    tw = path.tw
    if path.inf_pe:
        s1 = [0j] * (K + 1)
        s1[0] = complex(-tw * (c.real - d.real), -tw * (c.imag - d.imag))
        if K >= 1:
            s1[1] = complex(-tw, 0.0)
    else:
        B = 4 * tw / path.Pe
        half = path.Pe / 2
        s1 = _sqrt_series(complex(1 + B * c.real, B * c.imag), complex(B, 0.0), K)
        for n in range(1, K + 1):
            s1[n] = complex(s1[n].real * -half, s1[n].imag * -half)
        s1[0] = _phi_at(path, c, d)
    out = [0j] * (K + 1)
    out[0] = _cexp(complex(s1[0].real + E, s1[0].imag))
    for n in range(1, K + 1):
        ar = 0.0
        ai = 0.0
        for k in range(1, n + 1):
            pr = k * s1[k].real
            pi = k * s1[k].imag
            h = out[n - k]
            ar += pr * h.real - pi * h.imag
            ai += pr * h.imag + pi * h.real
        out[n] = complex(ar / n, ai / n)
    return out


def _exp_series(t: float, c: complex, K: int) -> List[complex]:
    """Taylor coefficients of exp(-t (c + w)): e^(-t c) (-t)^n/n!."""
    out = [0j] * (K + 1)
    e = _cexp(complex(-t * c.real, -t * c.imag))
    r = e.real
    i = e.imag
    out[0] = e
    for n in range(1, K + 1):
        r = r * (-t / n)
        i = i * (-t / n)
        out[n] = complex(r, i)
    return out


# ---------------------------------------------------------------------------
# Divided differences over subsets of points, robust for clusters
# ---------------------------------------------------------------------------

LINK_FRAC = 0.3
TAYLOR_FRAC = 0.5


def _dd_scale(path: LaplacePath, dd: _DD, z: complex) -> float:
    if dd.kind == 0:
        return _tau_scale(path, z)
    if dd.kind == 1:
        return _h_scale(path, z)
    return 1 / dd.t


def _dd_series(path: LaplacePath, dd: _DD, c: complex, K: int) -> List[complex]:
    if dd.kind == 0:
        return _tau_series(path, c, K)
    if dd.kind == 1:
        return _h_series(path, c, dd.d, dd.E, K)
    return _exp_series(dd.t, c, K)


def _dd_setup(path: LaplacePath, dd: _DD, n: int) -> bool:
    dd.n = n
    dd.memo = {}
    z = dd.z
    for k in range(n):
        dd.sc[k] = _dd_scale(path, dd, z[k])
        dd.cl[k] = k
    anyc = False
    for a in range(n):
        for b in range(a + 1, n):
            dx = z[a].real - z[b].real
            dy = z[a].imag - z[b].imag
            d = math.sqrt(dx * dx + dy * dy)
            dd.dist[a * n + b] = d
            dd.dist[b * n + a] = d
            if d <= LINK_FRAC * min(dd.sc[a], dd.sc[b]):
                anyc = True
                ca = dd.cl[a]
                cb = dd.cl[b]
                if ca != cb:
                    for k in range(n):
                        if dd.cl[k] == cb:
                            dd.cl[k] = ca
    dd.ncl = 0
    if not anyc:
        return False
    seen = [-1] * n
    for k in range(n):
        root = dd.cl[k]
        if seen[root] < 0:
            seen[root] = dd.ncl
            dd.cl_mask[dd.ncl] = 0
            dd.ncl += 1
        c = seen[root]
        dd.cl[k] = c
        dd.cl_mask[c] |= 1 << k
    for c in range(dd.ncl):
        dd.cl_ok[c] = False
        dd.cl_k[c] = -1
    return True


def _low(mask: int) -> int:
    return (mask & -mask).bit_length() - 1


def _dd_get(path: LaplacePath, dd: _DD, mask: int) -> complex:
    v = dd.memo.get(mask)
    if v is not None:
        return v
    n = dd.n
    lo = _low(mask)
    hi = mask.bit_length() - 1
    if lo == hi:
        v = dd.f[lo]
    else:
        c0 = dd.cl[lo] if dd.ncl else -1
        cnt = 0
        m = mask
        while m:
            cnt += 1
            if c0 >= 0 and dd.cl[_low(m)] != c0:
                c0 = -1
            m &= m - 1
        t = _dd_taylor(path, dd, mask, cnt, c0) if c0 >= 0 else None
        if t is not None:
            v = t
        else:
            a = lo
            b = hi
            if dd.ncl and dd.cl[a] == dd.cl[b]:
                bd = -1.0
                bb = -1
                m = mask
                while m:
                    k = _low(m)
                    if dd.cl[k] != dd.cl[a] and dd.dist[a * n + k] > bd:
                        bd = dd.dist[a * n + k]
                        bb = k
                    m &= m - 1
                if bb < 0:
                    m = mask
                    while m:
                        p = _low(m)
                        m2 = m & (m - 1)
                        while m2:
                            q = _low(m2)
                            if dd.dist[p * n + q] > bd:
                                bd = dd.dist[p * n + q]
                                a = p
                                bb = q
                            m2 &= m2 - 1
                        m &= m - 1
                b = bb
            x = _dd_get(path, dd, mask & ~(1 << a))
            y = _dd_get(path, dd, mask & ~(1 << b))
            v = _cdiv(x - y, dd.z[b] - dd.z[a])
    dd.memo[mask] = v
    return v


def _dd_taylor(path: LaplacePath, dd: _DD, mask: int, cnt: int, c: int) -> Optional[complex]:
    m = cnt - 1
    if dd.cl_k[c] < 0:
        cm = dd.cl_mask[c]
        cr = 0.0
        ci = 0.0
        k0 = 0
        for k in range(dd.n):
            if cm & (1 << k):
                cr += dd.z[k].real
                ci += dd.z[k].imag
                k0 += 1
        cr /= k0
        ci /= k0
        rad = 0.0
        for k in range(dd.n):
            if cm & (1 << k):
                rad = max(rad, math.hypot(dd.z[k].real - cr, dd.z[k].imag - ci))
        sc = _dd_scale(path, dd, complex(cr, ci))
        q = rad / sc
        dd.cl_c[c] = complex(cr, ci)
        if not q <= TAYLOR_FRAC:
            dd.cl_ok[c] = False
            dd.cl_k[c] = 0
            return None
        dd.cl_ok[c] = True
        mmax = k0 - 1
        extra = 2
        if q > 0:
            term = 1.0
            extra = 1
            while extra < 240:
                term *= q * (extra + mmax) / extra
                if term < 1e-17 and extra > 2:
                    break
                extra += 1
        K = min(255, mmax + extra + 2)
        dd.cl_k[c] = K
        dd.cl_coef[c] = _dd_series(path, dd, complex(cr, ci), K)
    if not dd.cl_ok[c]:
        return None
    K = dd.cl_k[c]
    cc = dd.cl_c[c]
    L = K - m
    h = [0j] * (L + 1)
    h[0] = 1 + 0j
    mm = mask
    while mm:
        k = _low(mm)
        w = dd.z[k] - cc
        wr = w.real
        wi = w.imag
        for j in range(1, L + 1):
            p = h[j - 1]
            h[j] = complex(h[j].real + (wr * p.real - wi * p.imag), h[j].imag + (wr * p.imag + wi * p.real))
        mm &= mm - 1
    f = dd.cl_coef[c]
    sr = 0.0
    si = 0.0
    for j in range(L, -1, -1):
        a = f[m + j]
        b = h[j]
        sr += a.real * b.real - a.imag * b.imag
        si += a.real * b.imag + a.imag * b.real
    return complex(sr, si)


# ---------------------------------------------------------------------------
# Functions of lower-triangular matrices
# ---------------------------------------------------------------------------

NEED_ALL = 0
NEED_COLUMN = 1
NEED_CORNER = 2


def _tri_fun(path: LaplacePath, ws: _Workspace, m: int, L: List[complex], F: List[complex], need: int) -> None:
    dd = ws.dd
    for p in range(m):
        F[p * m + p] = dd.f[p]
    if m == 1:
        return
    if not _dd_setup(path, dd, m):
        z = dd.z
        for d in range(1, m):
            for q in range(m - d):
                p = q + d
                l = L[p * m + q]
                e = F[p * m + p] - F[q * m + q]
                ar = l.real * e.real - l.imag * e.imag
                ai = l.real * e.imag + l.imag * e.real
                for k in range(q + 1, p):
                    g1 = L[p * m + k]
                    f1 = F[k * m + q]
                    f2 = F[p * m + k]
                    g2 = L[k * m + q]
                    ar += f2.real * g2.real - f2.imag * g2.imag - (g1.real * f1.real - g1.imag * f1.imag)
                    ai += f2.real * g2.imag + f2.imag * g2.real - (g1.real * f1.imag + g1.imag * f1.real)
                F[p * m + q] = _cdiv(complex(ar, ai), z[p] - z[q])
        return
    ws.clustered += 1
    if need == NEED_ALL:
        for p in range(1, m):
            for q in range(p):
                F[p * m + q] = 0j
        for q in range(m - 1):
            _path_visit(path, ws, m, L, F, q, q, 1 << q, 1 + 0j, False)
    else:
        for p in range(1, m):
            F[p * m] = 0j
        _path_visit(path, ws, m, L, F, 0, 0, 1, 1 + 0j, need == NEED_CORNER)


def _path_visit(path: LaplacePath, ws: _Workspace, m: int, L: List[complex], F: List[complex], q: int, k: int,
                mask: int, prod: complex, corner_only: bool) -> None:
    if k != q and (not corner_only or k == m - 1):
        v = _dd_get(path, ws.dd, mask)
        F[k * m + q] += complex(prod.real * v.real - prod.imag * v.imag, prod.real * v.imag + prod.imag * v.real)
    for l in range(k + 1, m):
        e = L[l * m + k]
        if e == 0:
            continue
        _path_visit(path, ws, m, L, F, q, l, mask | (1 << l),
                    complex(prod.real * e.real - prod.imag * e.imag, prod.real * e.imag + prod.imag * e.real),
                    corner_only)


# ---------------------------------------------------------------------------
# One pair's transform
# ---------------------------------------------------------------------------

def _block_of(path: LaplacePath, i: int, j: int) -> Optional[_Block]:
    key = i * path.n + j
    if key in path.blocks:
        return path.blocks[key]
    blk = None
    if path.reach[j][i]:
        S = [k for k in path.order if path.reach[j][k] and path.reach[k][i]]
        m = len(S)
        local = {k: p for p, k in enumerate(S)}
        A = [0.0] * (m * m)
        for p in range(m):
            for par, c in path.parents[S[p]]:
                q = local.get(par)
                if q is not None:
                    A[p * m + q] -= c
        Rf = [path.Rf[k] for k in S]
        blk = _Block(i=i, j=j, S=S, m=m, A=A, lam=[path.lam[k] for k in S], Rf=Rf, Rm=[path.Rm[k] for k in S],
                     De=[path.De[k] for k in S], Rmin=min(Rf), matrix=path.matrix[S[0]] == 1, s0=NAN)
    path.blocks[key] = blk
    return blk


def _eval_block(path: LaplacePath, ws: _Workspace, blk: _Block, s: complex, kind: int) -> complex:
    """The pair's transform at s, scaled: the value is the result times
    e^(-ws.E). RELEASE gives T_ij and DECAYED (A^-1 T)_ij, under plug flow
    both without their delay e^(-TW Rmin s); INVENTORY gives K_ij."""
    m = blk.m
    aw = path.aw
    ws.evaluations += 1
    delay = blk.Rmin if kind != INVENTORY and path.inf_pe else 0.0
    d = complex(delay * s.real, delay * s.imag)
    phi_max = -INF
    lam = blk.lam
    Rf = blk.Rf
    De = blk.De
    for p in range(m):
        a = complex(s.real + lam[p], s.imag)
        ws.a[p] = a
        gr = a.real * Rf[p]
        gi = a.imag * Rf[p]
        if blk.matrix:
            fm = blk.Rm[p] / De[p]
            mz = complex(fm * a.real, fm * a.imag)
            ws.mz[p] = mz
            tz = _tau_at(path, mz)
            ws.tz[p] = tz
            gr += aw * De[p] * tz.real
            gi += aw * De[p] * tz.imag
        g = complex(gr, gi)
        ws.g[p] = g
        ph = _phi_at(path, g, d)
        if ph.real > phi_max:
            phi_max = ph.real
    E = -phi_max if math.isfinite(phi_max) else 0.0
    L = ws.L
    dd = ws.dd
    A = blk.A
    if m > 1:
        if blk.matrix:
            dd.kind = 0
            for p in range(m):
                dd.z[p] = ws.mz[p]
                dd.f[p] = ws.tz[p]
                for q in range(p):
                    L[p * m + q] = complex(A[p * m + q] * blk.Rm[q] / De[p], 0.0)
            _tri_fun(path, ws, m, L, ws.T, NEED_ALL)
            T = ws.T
            for p in range(1, m):
                c = aw * De[p]
                for q in range(p):
                    t = T[p * m + q]
                    L[p * m + q] = complex(A[p * m + q] * Rf[q] + c * t.real, c * t.imag)
        else:
            for p in range(1, m):
                for q in range(p):
                    L[p * m + q] = complex(A[p * m + q] * Rf[q], 0.0)
    dd.kind = 1
    dd.d = d
    dd.E = E
    for p in range(m):
        dd.z[p] = ws.g[p]
        ph = _phi_at(path, ws.g[p], d)
        dd.f[p] = _cexp(complex(ph.real + E, ph.imag))
    F = ws.F
    _tri_fun(path, ws, m, L, F, NEED_CORNER if kind == RELEASE else NEED_COLUMN)
    if kind == RELEASE:
        ws.E = E
        return F[(m - 1) * m]
    if kind == DECAYED:
        EK = E
        c0 = 0.0
        c1 = -1.0
    else:
        EK = E if E < 0 else 0.0
        c0 = math.exp(EK)
        c1 = _exp(EK - E)
    v = ws.v
    for p in range(m):
        fp = F[p * m]
        wr = (c0 if p == 0 else 0.0) - c1 * fp.real
        wi = -c1 * fp.imag
        for q in range(p):
            a = A[p * m + q]
            if a != 0:
                wr -= a * v[q].real
                wi -= a * v[q].imag
        v[p] = _cdiv(complex(wr, wi), ws.a[p])
    ws.E = EK
    return v[m - 1]


def _kind_of(kind: Any) -> int:
    if kind is None:
        k = RELEASE
    elif isinstance(kind, int) and not isinstance(kind, bool):
        k = kind
    elif kind in KINDS:
        k = KINDS.index(kind)
    else:
        k = -1
    if k not in (RELEASE, INVENTORY, DECAYED):
        raise LaplacePathError(f"Unknown response kind '{kind}'")
    return k


def transfer(path: LaplacePath, sr: float, si: float, i: int, j: int) -> complex:
    """T_ij(s); 0 when j never becomes i."""
    blk = _block_of(path, i, j)
    if blk is None:
        return 0j
    v = _eval_block(path, path.ws, blk, complex(sr, si), RELEASE)
    lr = -path.ws.E - (path.tw * blk.Rmin * sr if path.inf_pe else 0.0)
    li = -path.tw * blk.Rmin * si if path.inf_pe else 0.0
    e = _cexp(complex(lr, li))
    return complex(v.real * e.real - v.imag * e.imag, v.real * e.imag + v.imag * e.real)


def inventory_transfer(path: LaplacePath, sr: float, si: float, i: int, j: int) -> complex:
    """K_ij(s), the transform of what the path holds."""
    blk = _block_of(path, i, j)
    if blk is None:
        return 0j
    v = _eval_block(path, path.ws, blk, complex(sr, si), INVENTORY)
    f = _exp(-path.ws.E)
    return complex(v.real * f, v.imag * f)


def transfer_at_zero(path: LaplacePath) -> List[float]:
    """T(0) for every pair, row-major n x n."""
    n = path.n
    out = [0.0] * (n * n)
    for i in range(n):
        for j in range(n):
            if _block_of(path, i, j) is None:
                continue
            v = transfer(path, 0.0, 0.0, i, j).real
            if not math.isfinite(v):
                v = transfer(path, 1e-300, 0.0, i, j).real
            out[i * n + j] = v
    return out


def pairs(path: LaplacePath) -> List[Tuple[int, int]]:
    """Which pairs (i, j) have a response: j is i, or decays into it."""
    return [(i, j) for j in range(path.n) for i in range(path.n) if path.reach[j][i]]


# ---------------------------------------------------------------------------
# Numerical inversion
# ---------------------------------------------------------------------------

M_DEFAULT = 28
TALBOT_M_MAX = 96


def _tau_real(path: LaplacePath, z: float) -> float:
    if z >= 0:
        u = math.sqrt(z)
        return u if path.inf_x0 else u * math.tanh(path.x0 * u)
    u = math.sqrt(-z)
    return NAN if path.inf_x0 else -u * math.tan(path.x0 * u)


def _singularity(path: LaplacePath, blk: _Block, kind: int = RELEASE) -> float:
    if kind == DECAYED:
        s0 = _singularity(path, blk)
        for p in range(blk.m):
            if -blk.lam[p] > s0:
                s0 = -blk.lam[p]
        return s0
    if blk.s0 == blk.s0:
        return blk.s0
    s0 = -INF
    for p in range(blk.m):
        lam = blk.lam[p]
        Rf = blk.Rf[p]
        if not blk.matrix:
            sk = -INF if path.inf_pe else -lam - path.Pe / (4 * path.tw * Rf)
        elif path.inf_x0:
            sk = -lam
        else:
            f = blk.Rm[p] / blk.De[p]
            pole = -lam - (PI / (2 * path.x0)) * (PI / (2 * path.x0)) / f
            if path.inf_pe:
                sk = pole
            else:
                gs = -path.Pe / (4 * path.tw)
                a = pole
                b = -lam
                it = 0
                while it < 200 and b - a > 1e-15 * max(abs(a), abs(b)):
                    c = 0.5 * (a + b)
                    g = (c + lam) * Rf + path.aw * blk.De[p] * _tau_real(path, f * (c + lam))
                    if g > gs:
                        b = c
                    else:
                        a = c
                    it += 1
                sk = b
        if sk > s0:
            s0 = sk
    blk.s0 = s0
    return s0


def _off_lambda(blk: _Block, s: float, gap: float) -> float:
    for _ in range(blk.m + 1):
        moved = False
        for p in range(blk.m):
            if abs(s + blk.lam[p]) < gap:
                s = -blk.lam[p] + gap
                moved = True
        if not moved:
            break
    return s


def _real_axis(path: LaplacePath, ws: _Workspace, pr: Dict[str, Any], t_lo: float, t_hi: float) -> Dict[str, Any]:
    blk = pr['blk']
    kind = pr['kind']
    s0 = _singularity(path, blk, kind)
    fac = 10 ** (1 / 8)

    def psi_at(s: float) -> float:
        at = _off_lambda(blk, s, 1e-7 * (s - s0)) if kind == INVENTORY else s
        v = _eval_block(path, ws, blk, complex(at, 0.0), kind)
        F = v.real
        return math.log(F) - ws.E if F > 0 and math.isfinite(F) else -INF

    x0 = max(abs(s0), 0.0) + 1 / t_hi
    up: List[Tuple[float, float]] = []
    dn: List[Tuple[float, float]] = []
    x = x0
    for _ in range(800):
        p = psi_at(s0 + x)
        up.append((s0 + x, p))
        if p < -900 or x > 1e12 / t_lo:
            break
        x *= fac

    # Toward s0 the tilted mean D grows without bound. w = s D + psi(s) there
    # is the Chernoff bound: the part of the response after the time D is at
    # most e^w (s < 0). The scan stops where that part is negligible, where D
    # passes 10 t_hi, and where D no longer grows: psi is convex, so a D that
    # does not grow is rounding next to the singularity.
    def d_of(a: Tuple[float, float], b: Tuple[float, float]) -> float:
        return -(b[1] - a[1]) / (b[0] - a[0])

    wmax = -INF
    for k in range(len(up) - 1):
        w = 0.5 * (up[k][0] + up[k + 1][0]) * d_of(up[k], up[k + 1]) + 0.5 * (up[k][1] + up[k + 1][1])
        if w > wmax:
            wmax = w
    prev = up[0]
    d_prev = d_of(up[0], up[1]) if len(up) > 1 else 0.0
    x = x0 / fac
    for _ in range(800):
        s = s0 + x
        if not s > s0:
            break
        p = psi_at(s)
        if not math.isfinite(p):
            break
        D = d_of((s, p), prev)
        if not D > d_prev:
            break
        dn.append((s, p))
        w = 0.5 * (s + prev[0]) * D + 0.5 * (p + prev[1])
        if w > wmax:
            wmax = w
        prev = (s, p)
        d_prev = D
        if D > 10 * t_hi or x < 1e-13 * max(abs(s0), 1 / t_hi) or w < wmax - 120:
            break
        x /= fac
    pts = dn[::-1] + up
    # A grid geometric in s - s0 steps by about |s0|/3 near s = 0: add s = +-e,
    # e geometric from 1/t_hi, on either side of 0 (on the left no nearer s0
    # than half way), and keep the tilted mean positive and falling.
    extra: List[float] = []
    e_hi = max(pts[-1][0], 0.0)
    e_left = 0.5 * abs(s0)
    e = 1 / t_hi
    while e < max(e_hi, e_left):
        if e < e_hi:
            extra.append(e)
        if e < e_left:
            extra.append(-e)
        e *= fac
    if extra:
        have = [q[0] for q in pts]
        lo0 = have[0]

        def near(a: float, b: float) -> bool:
            return abs(a - b) < 1e-6 * max(abs(a), abs(b), 1 / t_hi)

        for e in extra:
            if not e > lo0 or any(near(h, e) for h in have):
                continue
            pv = psi_at(e)
            if math.isfinite(pv):
                pts.append((e, pv))
        pts.sort(key=lambda q: q[0])
        kept = [pts[0]]
        for k in range(1, len(pts)):
            Dn = d_of(kept[-1], pts[k])
            if not Dn > 0 or (len(kept) >= 2 and not Dn < d_of(kept[-2], kept[-1])):
                continue
            kept.append(pts[k])
        pts = kept
    # Resolve the saddles: where D falls from one interval to the next by more
    # than the tilted spread allows, put a node between, as far as the
    # response matters (w within 80 of its top).
    for _ in range(14):
        if len(pts) >= 4000:
            break
        out = [pts[0]]
        added = False
        for k in range(len(pts) - 1):
            a = pts[k]
            b = pts[k + 1]
            Dk = d_of(a, b)
            Dl = d_of(pts[k - 1], a) if k > 0 else NAN
            Dr = d_of(b, pts[k + 2]) if k + 2 < len(pts) else NAN
            drop = max(Dl - Dk if math.isfinite(Dl) else 0.0, Dk - Dr if math.isfinite(Dr) else 0.0)
            w = 0.5 * (a[0] + b[0]) * Dk + 0.5 * (a[1] + b[1])
            if drop * (b[0] - a[0]) > 1 and w > wmax - 80:
                s_mid = s0 + math.sqrt((a[0] - s0) * (b[0] - s0))
                if a[0] < s_mid < b[0]:
                    p = psi_at(s_mid)
                    if math.isfinite(p):
                        out.append((s_mid, p))
                        added = True
            out.append(b)
        pts = out
        if not added:
            break
    K = len(pts)
    sv = [q[0] for q in pts]
    psi = [q[1] for q in pts]
    sm = [0.0] * max(0, K - 1)
    D = [0.0] * max(0, K - 1)
    for k in range(K - 1):
        sm[k] = s0 + math.sqrt((sv[k] - s0) * (sv[k + 1] - s0))
        D[k] = -(psi[k + 1] - psi[k]) / (sv[k + 1] - sv[k]) if math.isfinite(psi[k + 1]) and math.isfinite(
            psi[k]) else NAN
    return {'pr': pr, 's0': s0, 's': sv, 'psi': psi, 'sm': sm, 'D': D}


def _saddle_at(ax: Dict[str, Any], t: float) -> Optional[Dict[str, Any]]:
    D = ax['D']
    sm = ax['sm']
    K = len(D)
    s0 = ax['s0']
    if K < 2:
        return None
    k = 0
    while k < K and not D[k] <= t:
        if not math.isfinite(D[k]) and k > 0:
            break
        k += 1
    if k == 0:
        psi2 = (D[0] - D[1]) / (sm[1] - sm[0])
        return {'s': sm[0], 'psi2': psi2, 'w': sm[0] * t + ax['psi'][0], 'edge': True, 'beyond': False}
    if k >= K or not math.isfinite(D[k]):
        return {'s': sm[min(k, K) - 1], 'psi2': NAN, 'w': -INF, 'edge': False, 'beyond': True}
    a = k - 1
    b = k
    la = math.log(D[a])
    lb = math.log(D[b])
    f = (la - math.log(t)) / (la - lb)
    xa = sm[a] - s0
    xb = sm[b] - s0
    ss = s0 + xa * (xb / xa) ** f
    psi2 = (D[a] - D[b]) / (sm[b] - sm[a])
    psi = ax['psi'][b] + (ax['s'][b] - ss) * 0.5 * (t + D[b])
    return {'s': ss, 'psi2': psi2, 'w': ss * t + psi, 'edge': False, 'beyond': False}


def _parabola_term(path: LaplacePath, ws: _Workspace, pr: Dict[str, Any], t: float, ss: float, kappa: float,
                   Y: float, wgt: float, acc: Dict[str, Any]) -> float:
    sr = ss - kappa * Y * Y
    si = Y
    F = _eval_block(path, ws, pr['blk'], complex(sr, si), pr['kind'])
    ex = t * sr - ws.E
    if ex > 700:
        acc['bad'] = True
        return INF
    if ex < -740 or F == 0:
        return 0.0
    e = _cexp(complex(ex, t * si))
    ar = e.real * F.real - e.imag * F.imag
    ai = e.real * F.imag + e.imag * F.real
    q = 2 * kappa * Y
    zr = ar - ai * q
    zi = ai + ar * q
    acc['h'] += wgt * zr
    yr = sr * zr - si * zi
    yi = sr * zi + si * zr
    acc['dh'] += wgt * yr
    acc['d2'] += wgt * (sr * yr - si * yi)
    mod = math.hypot(zr, zi)
    acc['abs'] += wgt * mod
    return mod


def _parabola_sweep(path: LaplacePath, ws: _Workspace, pr: Dict[str, Any], t: float, ss: float, kappa: float,
                    step: float, off: float, acc: Dict[str, Any]) -> None:
    """Trapezoidal sum over Y = off, off + 2 step, ... until the terms die
    out; terms that grow back after they have fallen away set `regrow` (the
    envelope is the largest of the last seven terms), and a sum out of nodes
    or budget before the terms died out is `cut` short."""
    max_mod = 0.0
    min_env = INF
    small = 0
    last = [0.0] * 7
    for k in range(20000):
        Y = off + k * (2 * step if off else step)
        if Y == 0:
            m0 = _parabola_term(path, ws, pr, t, ss, kappa, 0.0, 0.5, acc)
            max_mod = max(max_mod, m0)
            continue
        m = _parabola_term(path, ws, pr, t, ss, kappa, Y, 1.0, acc)
        if k > 3 and (m > 100 * max_mod or (min_env < 1e-6 * max_mod and m > 1e-3 * max_mod)):
            acc['regrow'] = True
            break
        if m > max_mod:
            max_mod = m
        last[k % 7] = m
        if k >= 7:
            min_env = min(min_env, max(last))
        if m <= 1e-18 * max_mod:
            small += 1
            if small >= 3 and k > 3:
                return
        else:
            small = 0
        if acc['bad']:
            return
        if ws.evaluations > acc['stop']:
            break
    acc['cut'] = True


def _psi_real(path: LaplacePath, ws: _Workspace, pr: Dict[str, Any], s: float) -> float:
    v = _eval_block(path, ws, pr['blk'], complex(s, 0.0), pr['kind'])
    F = v.real
    return math.log(F) - ws.E if F > 0 and math.isfinite(F) else NAN


def _local_axis(path: LaplacePath, ws: _Workspace, ax: Dict[str, Any], s: float, scale: float) -> Dict[str, float]:
    """psi, the tilted mean D = -psi' and psi'' at s, by central differences a
    thousandth of s - s0 apart, or a tenth of `scale` when that is less."""
    dl = min(1e-3 * (s - ax['s0']), 0.1 * scale if scale > 0 else INF)
    pm = _psi_real(path, ws, ax['pr'], s - dl)
    p0 = _psi_real(path, ws, ax['pr'], s)
    pp = _psi_real(path, ws, ax['pr'], s + dl)
    return {'psi': p0, 'D': (pm - pp) / (2 * dl), 'psi2': (pp - 2 * p0 + pm) / (dl * dl)}


def _ln_hk(path: LaplacePath, blk: _Block, p: int, sr: float, si: float, rfc: float) -> float:
    """ln |H(g_p(s))|, the size of member p's own transform at s, with the
    delay e^(-TW rfc s) taken out as the pair's transform has it."""
    lam = blk.lam[p]
    gr = blk.Rf[p] * (sr + lam)
    gi = blk.Rf[p] * si
    if blk.matrix:
        fm = blk.Rm[p] / blk.De[p]
        tz = _tau_at(path, complex(fm * (sr + lam), fm * si))
        gr += path.aw * blk.De[p] * tz.real
        gi += path.aw * blk.De[p] * tz.imag
    return _phi_at(path, complex(gr, gi), complex(rfc * sr, rfc * si)).real


def _clears_ridge(path: LaplacePath, blk: _Block, v: float, t: float, kappa: float, lev: List[float],
                  lev_min: float, rfc: float) -> bool:
    """Whether, along the parabola, no member's own transform times e^(st)
    grows above its level: the fracture's transform is large next to its
    branch point (under plug flow, next to the poles of tanh), and a parabola
    that bends too fast passes there low."""
    if path.inf_pe:
        ymax = math.sqrt(80 / (t * kappa))
    else:
        if t * v + path.Pe / 2 <= lev_min:
            return True
        ymax = math.sqrt((t * v + path.Pe / 2 - lev_min + 40) / (t * kappa))
    for q in range(1, 97):
        Y = ymax * q / 96
        sr = v - kappa * Y * Y
        for p in range(blk.m):
            if t * sr + _ln_hk(path, blk, p, sr, Y, rfc) > lev[p]:
                return False
    return True


def _path_frequency(path: LaplacePath, blk: _Block, v: float, t: float, kappa: float, floor: float,
                    rfc: float) -> float:
    """How fast, at most, the phase of any member's own transform times e^(st)
    turns along the parabola (per unit Y), over the stretch where its size is
    above e^floor (``pathFrequency``): the trapezoidal step must follow it."""
    ymax = math.sqrt(max(0.0, (t * v - floor + (40 if path.inf_pe else path.Pe / 2 + 40)) / (t * kappa)))
    wmax = 0.0
    for q in range(97):
        Y = ymax * q / 96
        sr = v - kappa * Y * Y
        si = Y
        for p in range(blk.m):
            zr0 = sr + blk.lam[p]
            gr = blk.Rf[p] * zr0
            gi = blk.Rf[p] * si
            dgr = blk.Rf[p]
            dgi = 0.0
            if blk.matrix:
                f = blk.Rm[p] / blk.De[p]
                c = path.aw * blk.De[p]
                u = _csqrt(complex(f * zr0, f * si))
                tr, ti = u.real, u.imag
                hh = _cdiv(complex(0.5, 0.0), u)
                if path.inf_x0:
                    dr, di = hh.real, hh.imag
                else:
                    th = _ctanh(complex(path.x0 * u.real, path.x0 * u.imag))
                    tr = u.real * th.real - u.imag * th.imag
                    ti = u.real * th.imag + u.imag * th.real
                    se = _csech2(complex(path.x0 * u.real, path.x0 * u.imag))
                    dr = th.real * hh.real - th.imag * hh.imag + 0.5 * path.x0 * se.real
                    di = th.real * hh.imag + th.imag * hh.real + 0.5 * path.x0 * se.imag
                gr += c * tr
                gi += c * ti
                dgr += c * f * dr
                dgi += c * f * di
            ph = _phi_at(path, complex(gr, gi), complex(rfc * sr, rfc * si))
            if t * sr + ph.real < floor:
                continue
            if path.inf_pe:
                pr_ = -path.tw * (dgr - rfc)
                pi_ = -path.tw * dgi
            else:
                B = 4 * path.tw / path.Pe
                sq = _csqrt(complex(1 + B * gr, B * gi))
                q_ = _cdiv(complex(-path.tw, 0.0), sq)
                pr_ = q_.real * dgr - q_.imag * dgi
                pi_ = q_.real * dgi + q_.imag * dgr
            w = abs((t + pr_) - 2 * kappa * Y * pi_)
            if w > wmax:
                wmax = w
    return wmax


def _zero(**extra: Any) -> Dict[str, Any]:
    out = {'h': 0.0, 'dh': 0.0, 'd2': 0.0, 'err': 0.0, 'cond': 1.0, 'nodes': 0}
    out.update(extra)
    return out


def _new_acc(stop: float = INF) -> Dict[str, Any]:
    return {'h': 0.0, 'dh': 0.0, 'd2': 0.0, 'abs': 0.0, 'bad': False, 'regrow': False, 'cut': False, 'stop': stop}


VERTEX_BETA = 1.5


def _invert_parabola(path: LaplacePath, ws: _Workspace, ax: Dict[str, Any], t: float,
                     opt: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The response and its first two derivatives at t on a parabola through
    the saddle (polished by Newton's method), at least 1.5/t right of the
    rightmost singularity, bent no less than to put its focus there and no
    more than keeps every member's own transform from growing along it."""
    pr = ax['pr']
    tt = t - pr['shift']
    if not tt > 0:
        return _zero()
    opt = opt or {}
    rtol = opt.get('rtol') or 1e-11
    atol = opt.get('atol') or 0.0
    max_eval = opt.get('maxEval') or 6000
    sad = _saddle_at(ax, tt)
    if sad is None or sad['beyond'] or sad['w'] < -720:
        return _zero(negligible=True)
    n0 = ws.evaluations
    v_min = ax['s0'] + VERTEX_BETA / tt
    v = max(sad['s'], v_min)
    psi2 = NAN
    wv = sad['w']
    omega = 0.0
    # K's removable points s = -lambda would spoil the differences
    if pr['kind'] != INVENTORY:
        # the differences on the scale of the saddle's own width
        scale = min(1 / tt, 1 / math.sqrt(sad['psi2']) if math.isfinite(sad['psi2']) and sad['psi2'] > 0 else INF)
        loc = _local_axis(path, ws, ax, v, scale)
        for _ in range(3):
            if not (v > v_min and loc['psi2'] > 0 and abs(loc['D'] - tt) > 0.5 * math.sqrt(loc['psi2'])):
                break
            vn = max(v + (loc['D'] - tt) / loc['psi2'], v_min)
            ln = _local_axis(path, ws, ax, vn, scale)
            if not abs(ln['D'] - tt) < abs(loc['D'] - tt) or not ln['psi2'] > 0:
                break
            v = vn
            loc = ln
        psi2 = loc['psi2']
        if math.isfinite(loc['psi']):
            wv = tt * v + loc['psi']
        omega = abs(tt - loc['D']) if math.isfinite(loc['D']) else 0.0
    if not psi2 > 0 or not math.isfinite(psi2):
        psi2 = sad['psi2'] if math.isfinite(sad['psi2']) and sad['psi2'] > 0 else tt * tt
    kappa = max(psi2 / (2 * tt), 0.25 / (v - ax['s0']))
    # the delay the pair's transform has taken out (under plug flow)
    rfc = pr['blk'].Rmin if pr['shift'] > 0 else 0.0
    if not path.inf_pe or not path.inf_x0:
        m = pr['blk'].m
        lev = [0.0] * m
        lev_min = INF
        for p in range(m):
            lev[p] = max(tt * v + _ln_hk(path, pr['blk'], p, v, 0.0, rfc), wv) + 2
            lev_min = min(lev_min, lev[p])
        for _ in range(16):
            if _clears_ridge(path, pr['blk'], v, tt, kappa, lev, lev_min, rfc):
                break
            kappa /= 4
    res: Dict[str, Any] = {}
    for _ in range(4):
        w_path = omega if path.inf_pe else max(omega, _path_frequency(path, pr['blk'], v, tt, kappa, wv - 25, rfc))
        res = _parabola_sums(path, ws, ax, tt, v, kappa, psi2, w_path, rtol, atol, n0 + max_eval)
        if not res.get('regrow'):
            break
        kappa /= 8
    if res.get('regrow') or res.get('bad'):
        return {'h': NAN, 'dh': NAN, 'd2': NAN, 'err': INF, 'cond': INF, 'nodes': ws.evaluations - n0}
    res['nodes'] = ws.evaluations - n0
    return res


def _parabola_sums(path: LaplacePath, ws: _Workspace, ax: Dict[str, Any], tt: float, v: float, kappa: float,
                   psi2: float, omega: float, rtol: float, atol: float, stop: float) -> Dict[str, Any]:
    pr = ax['pr']
    step = 1.5 * PI / math.sqrt(18.5 * psi2)
    if omega > 0:
        step = min(step, 0.5 * PI / omega)
    dist = v - ax['s0']
    strip = INF
    if dist > 0 and math.isfinite(dist):
        if kappa * dist < 1e-12:
            strip = dist
        elif 4 * kappa * dist >= 1:
            strip = 1 / (2 * kappa)
        else:
            strip = (1 - math.sqrt(1 - 4 * kappa * dist)) / (2 * kappa)
    if not strip > 0:
        strip = dist if dist > 0 else INF
    step = min(step, 0.5 * strip)
    ss = _off_lambda(pr['blk'], v, 0.25 * step) if pr['kind'] == INVENTORY else v
    acc = _new_acc(stop)
    _parabola_sweep(path, ws, pr, tt, ss, kappa, step, 0.0, acc)
    if acc['regrow']:
        return {'regrow': True}
    h = acc['h'] * step / PI
    dh = acc['dh'] * step / PI
    d2 = acc['d2'] * step / PI
    err = INF
    agreed = 0
    for level in range(12):
        if acc['bad'] or ws.evaluations > stop:
            break
        half = step / 2
        a2 = _new_acc(stop)
        _parabola_sweep(path, ws, pr, tt, ss, kappa, half, half, a2)
        if a2['regrow']:
            return {'regrow': True}
        if a2['bad']:
            acc['bad'] = True
            break
        if a2['cut']:
            acc['cut'] = True
        acc['h'] += a2['h']
        acc['dh'] += a2['dh']
        acc['d2'] += a2['d2']
        acc['abs'] += a2['abs']
        step = half
        h2 = acc['h'] * step / PI
        err = abs(h2 - h)
        h = h2
        dh = acc['dh'] * step / PI
        d2 = acc['d2'] * step / PI
        floor = 1e-15 * acc['abs'] * step / PI + atol
        rel = err / max(abs(h), 1e-300)
        edge = 2 * _exp(-2 * PI * strip / step) if math.isfinite(strip) else 0.0
        nxt = max(rel * rel, edge)
        # under plug flow two agreements in a row (the step does not follow
        # the phase along the path there)
        ok = err <= floor or (level >= 1 and err <= rtol * abs(h) and nxt <= rtol) or (
            step <= 0.3 * strip and nxt <= rtol * 1e-2)
        agreed = agreed + 1 if ok else 0
        if ok and (agreed >= 2 or not path.inf_pe):
            err = min(err, nxt * abs(h) + floor)
            break
    if acc['bad']:
        return {'bad': True}
    cond = acc['abs'] * step / PI / max(abs(h), 1e-300)
    # a sum cut short can agree with the next one and still be wrong
    if acc['cut']:
        err = INF
    return {'h': h, 'dh': dh, 'd2': d2, 'err': err, 'cond': cond, 's': ss, 'kappa': kappa}


def _talbot_sum(path: LaplacePath, ws: _Workspace, pr: Dict[str, Any], t: float, r: float,
                M: int) -> Tuple[float, float, float]:
    sh = 0.0
    sd = 0.0
    s2 = 0.0
    bad = False
    for k in range(M):
        if k == 0:
            sr = r
            si = 0.0
            sig = 0.0
        else:
            th = k * PI / M
            cot = math.cos(th) / math.sin(th)
            sr = r * th * cot
            si = r * th
            sig = th + (th * cot - 1) * cot
        F = _eval_block(path, ws, pr['blk'], complex(sr, si), pr['kind'])
        if F == 0:
            continue
        ex = t * sr - ws.E
        if ex < -740:
            continue
        if ex > 700:
            bad = True
            continue
        e = _cexp(complex(ex, t * si))
        ar = e.real * F.real - e.imag * F.imag
        ai = e.real * F.imag + e.imag * F.real
        tr = ar - ai * sig
        ti = ai + ar * sig
        w = 0.5 if k == 0 else 1.0
        yr = sr * tr - si * ti
        yi = sr * ti + si * tr
        sh += w * tr
        sd += w * yr
        s2 += w * (sr * yr - si * yi)
    c = r / M
    return (NAN, NAN, NAN) if bad else (c * sh, c * sd, c * s2)


def _invert_talbot(path: LaplacePath, ws: _Workspace, ax: Dict[str, Any], t: float,
                   opt: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    pr = ax['pr']
    M0 = (opt or {}).get('M') or M_DEFAULT
    tt = t - pr['shift']
    if not tt > 0:
        return {'h': 0.0, 'dh': 0.0, 'd2': 0.0, 'r': 0.0, 'M': 0, 'saddle': False}
    rdef = 2 * M0 / (5 * tt)
    sad = _saddle_at(ax, tt)
    r = rdef
    M = M0
    use_sad = False
    if sad is not None and sad['s'] > rdef:
        if sad['beyond'] or sad['w'] < -720:
            return {'h': 0.0, 'dh': 0.0, 'd2': 0.0, 'r': sad['s'], 'M': 0, 'saddle': True}
        use_sad = True
        r = sad['s']
        need = 2.2 * r * math.sqrt(sad['psi2']) if math.isfinite(sad['psi2']) and sad['psi2'] > 0 else 0.0
        M = min(TALBOT_M_MAX, max(M0, math.ceil(need + 0.6 * M0)))
    h, dh, d2 = _talbot_sum(path, ws, pr, tt, r, M)
    return {'h': h, 'dh': dh, 'd2': d2, 'r': r, 'M': M, 'saddle': use_sad}


def _de_hoog_terms(path: LaplacePath, ax: Optional[Dict[str, Any]] = None, t: float = 0.0) -> int:
    """De Hoog's M for this path (``deHoogTerms``): about 1.2 sqrt(Pe), 24 to
    160, and with the axis and a time also 1.7 t/sigma."""
    m = 24 if path.inf_pe else max(24, math.ceil(1.2 * math.sqrt(path.Pe)))
    if ax is not None:
        tt = t - ax['pr']['shift']
        sad = _saddle_at(ax, tt) if tt > 0 else None
        if sad is not None and not sad['beyond'] and sad['psi2'] > 0:
            m = max(m, math.ceil(1.7 * tt / math.sqrt(sad['psi2'])))
    return min(160, m)


def _invert_de_hoog(path: LaplacePath, ws: _Workspace, pr: Dict[str, Any], t: float,
                    opt: Optional[Dict[str, Any]] = None) -> float:
    tt = t - pr['shift']
    if not tt > 0:
        return 0.0
    opt = opt or {}
    M = opt.get('M') or 24
    tol = opt.get('tol') or 1e-12
    deriv = opt.get('deriv') or 0
    if deriv is True:
        deriv = 1
    T = (opt.get('Tfac') or 2) * tt
    gamma = -math.log(tol) / (2 * T)
    K = 2 * M
    a = [0j] * (K + 1)
    E0 = 0.0
    k_use = K
    for k in range(K + 1):
        F = _eval_block(path, ws, pr['blk'], complex(gamma, k * PI / T), pr['kind'])
        if k == 0:
            E0 = ws.E
        sc = _exp(E0 - ws.E)
        v = complex(F.real * sc, F.imag * sc)
        for _ in range(deriv):
            sr = gamma
            si = k * PI / T
            v = complex(sr * v.real - si * v.imag, sr * v.imag + si * v.real)
        for _ in range(-deriv if deriv < 0 else 0):
            v = _cdiv(v, complex(gamma, k * PI / T))
        a[k] = v
        if not (v.real != 0 or v.imag != 0) or not math.isfinite(v.real) or not math.isfinite(v.imag):
            k_use = k - 1
            break
    if k_use % 2 == 1:
        k_use -= 1
    if k_use < 2:
        return NAN
    Mu = k_use // 2
    a[0] = complex(a[0].real * 0.5, a[0].imag * 0.5)
    q = [0j] * k_use
    e = [0j] * (k_use + 1)
    d = [0j] * (k_use + 1)
    for k in range(k_use):
        q[k] = _cdiv(a[k + 1], a[k])
    d[0] = a[0]
    for r in range(1, Mu + 1):
        for k in range(k_use - 2 * r + 1):
            e[k] = q[k + 1] - q[k] + e[k + 1]
        d[2 * r - 1] = -q[0]
        d[2 * r] = -e[0]
        if r < Mu:
            for k in range(k_use - 2 * r):
                x = q[k + 1]
                y = e[k + 1]
                q[k] = _cdiv(complex(x.real * y.real - x.imag * y.imag, x.real * y.imag + x.imag * y.real), e[k])
    zr = math.cos(PI * tt / T)
    zi = math.sin(PI * tt / T)
    A2 = 0j
    A1 = d[0]
    B2 = 1 + 0j
    B1 = 1 + 0j
    for k in range(1, k_use + 1):
        c = complex(d[k].real * zr - d[k].imag * zi, d[k].real * zi + d[k].imag * zr)
        if k < k_use:
            An = A1 + complex(c.real * A2.real - c.imag * A2.imag, c.real * A2.imag + c.imag * A2.real)
            Bn = B1 + complex(c.real * B2.real - c.imag * B2.imag, c.real * B2.imag + c.imag * B2.real)
        else:
            d1 = d[k_use - 1] - d[k_use]
            hr = 0.5 * (1 + d1.real * zr - d1.imag * zi)
            hi = 0.5 * (d1.real * zi + d1.imag * zr)
            h2 = complex(hr * hr - hi * hi, 2 * hr * hi)
            u = _cdiv(c, h2)
            w = _csqrt(complex(1 + u.real, u.imag))
            Rr = -(hr * (1 - w.real) - hi * (-w.imag))
            Ri = -(hr * (-w.imag) + hi * (1 - w.real))
            An = A1 + complex(Rr * A2.real - Ri * A2.imag, Rr * A2.imag + Ri * A2.real)
            Bn = B1 + complex(Rr * B2.real - Ri * B2.imag, Rr * B2.imag + Ri * B2.real)
        A2 = A1
        A1 = An
        B2 = B1
        B1 = Bn
    res = _cdiv(A1, B1)
    return _exp(gamma * tt - E0) / T * res.real


# ---------------------------------------------------------------------------
# Unit responses on adaptive grids
# ---------------------------------------------------------------------------

RESP_PER_DECADE = 10
RESP_RTOL = 2e-8
RESP_ATOL = 1e-13
RESP_MAXPTS = 6000
T_CAP = 1e12


def _log_estimate(ax: Dict[str, Any], t: float) -> float:
    tt = t - ax['pr']['shift']
    if not tt > 0:
        return -INF
    sad = _saddle_at(ax, tt)
    if sad is None or sad['beyond'] or not math.isfinite(sad['w']):
        return -INF
    c = -0.5 * math.log(2 * PI * sad['psi2']) if math.isfinite(sad['psi2']) and sad['psi2'] > 0 else 0.0
    return sad['w'] + c


def _response_support(ax: Dict[str, Any], t_min: float, t_max: float) -> Optional[Dict[str, float]]:
    # under plug flow the grid is logarithmic in t - d, d the delay
    d = ax['pr']['shift']
    u_min = t_min - d
    u_max = t_max - d
    per = 16
    n = max(2, math.ceil(math.log10(u_max / u_min) * per) + 1)
    ts = [0.0] * n
    est = [0.0] * n
    wmax = -INF
    kmax = -1
    for k in range(n):
        ts[k] = d + u_min * (u_max / u_min) ** (k / (n - 1))
        est[k] = _log_estimate(ax, ts[k])
        if est[k] > wmax:
            wmax = est[k]
            kmax = k
    if not math.isfinite(wmax):
        return None
    k_lo = 0
    while k_lo < n and not est[k_lo] > wmax - 62:
        k_lo += 1
    k_hi = n - 1
    while k_hi > kmax and not est[k_hi] > wmax - 72:
        k_hi -= 1
    k_tail = n - 1
    while k_tail > kmax and not est[k_tail] > wmax - 20.7:
        k_tail -= 1
    return {
        'tLo': ts[max(0, k_lo - 1)], 'tHi': t_max if k_hi >= n - 1 else ts[min(n - 1, k_hi + 1)],
        'tPeak': ts[kmax], 'logPeak': wmax,
        'tTail': t_max if k_tail >= n - 1 else ts[min(n - 1, k_tail + 1)],
    }


def _sample(path: LaplacePath, ws: _Workspace, ax: Dict[str, Any], t: float, method: Optional[str],
            atol: float, hint: Optional[Dict[str, int]] = None) -> Tuple[float, float, float, float, float]:
    if method == 'talbot':
        r = _invert_talbot(path, ws, ax, t)
        if math.isfinite(r['h']) and math.isfinite(r['dh']) and math.isfinite(r['d2']):
            return (r['h'], r['dh'], r['d2'], 1.0, 0.0)
    elif method == 'dehoog':
        mh = _de_hoog_terms(path, ax, t)
        v = (_invert_de_hoog(path, ws, ax['pr'], t, {'M': mh}), _invert_de_hoog(path, ws, ax['pr'], t, {'M': mh, 'deriv': 1}),
             _invert_de_hoog(path, ws, ax['pr'], t, {'M': mh, 'deriv': 2}), 1.0, 0.0)
        if math.isfinite(v[0]) and math.isfinite(v[1]) and math.isfinite(v[2]):
            return v
    # the default, and where the other two break down; a response whose
    # samples mostly fell back to de Hoog goes there first
    if hint is not None:
        hint['tries'] += 1
    direct = hint is not None and hint['tries'] > 16 and hint['fails'] > 0.75 * hint['tries']
    r = {'h': NAN, 'err': INF} if direct else _invert_parabola(path, ws, ax, t, {'atol': atol})
    if math.isfinite(r['h']) and not r['err'] > 1e-6 * abs(r['h']) + atol:
        return (r['h'], r['dh'], r['d2'], r['cond'] or 1.0, r['err'])
    if hint is not None:
        hint['fails'] += 1
    # de Hoog's Bromwich line with twice the terms the spread asks for; the
    # parabola only when it has an error estimate below de Hoog's
    m1 = _de_hoog_terms(path, ax, t)
    m2 = min(2 * m1, 320)
    a_ = _invert_de_hoog(path, ws, ax['pr'], t, {'M': m1})
    b_ = _invert_de_hoog(path, ws, ax['pr'], t, {'M': m2})
    e_h = abs(a_ - b_)
    if math.isfinite(b_) and (not math.isfinite(r['h']) or not math.isfinite(r['err']) or e_h < r['err']):
        d1 = _invert_de_hoog(path, ws, ax['pr'], t, {'M': m2, 'deriv': 1})
        d2 = _invert_de_hoog(path, ws, ax['pr'], t, {'M': m2, 'deriv': 2})
        if math.isfinite(d1) and math.isfinite(d2):
            return (b_, d1, d2, 1.0, e_h + atol)
    if math.isfinite(r['h']):
        return (r['h'], r['dh'], r['d2'], r['cond'] or 1.0, r['err'])
    if direct:
        s2 = _invert_parabola(path, ws, ax, t, {'atol': atol})
        if math.isfinite(s2['h']):
            return (s2['h'], s2['dh'], s2['d2'], s2['cond'] or 1.0, s2['err'])
    return (0.0, 0.0, 0.0, INF, INF)


def _bateman(path: LaplacePath, ws: _Workspace, blk: _Block, t: float) -> Tuple[float, float, float]:
    """The block's e^(-Lambda t), entry (i, j), and its first two derivatives."""
    m = blk.m
    last = m - 1
    lam = blk.lam
    A = blk.A

    def L(p: int, q: int) -> float:
        return lam[p] if p == q else A[p * m + q]

    col = ws.col
    if not t > 0:
        for p in range(m):
            col[p] = 1.0 if p == 0 else 0.0
    else:
        dd = ws.dd
        dd.kind = 2
        dd.t = t
        for p in range(m):
            dd.z[p] = complex(lam[p], 0.0)
            dd.f[p] = complex(math.exp(-t * lam[p]), 0.0)
            for q in range(p):
                ws.L[p * m + q] = complex(A[p * m + q], 0.0)
        _tri_fun(path, ws, m, ws.L, ws.T, NEED_COLUMN)
        for p in range(m):
            col[p] = ws.T[p * m].real
    b1 = 0.0
    b2 = 0.0
    for k in range(m):
        b1 += L(last, k) * col[k]
        u = 0.0
        for l in range(k + 1):
            u += L(k, l) * col[l]
        b2 += L(last, k) * u
    return (col[last], -b1, b2)


def _sample_inventory(path: LaplacePath, ws: _Workspace, ax_c: Dict[str, Any], ax_k: Dict[str, Any], t: float,
                      method: Optional[str], atol: float,
                      hint: Optional[Dict[str, int]] = None) -> Tuple[float, float, float, float, float]:
    """One sample of an inventory response: e^(-Lambda t) - c while the path
    still holds at least half of that, and otherwise whichever of that and K
    inverted whole carries the smaller error estimate (see the application's
    ``sampleInventory``)."""
    b0, b1, b2 = _bateman(path, ws, ax_c['pr']['blk'], t)
    c0, c1, c2, cc, ce = _sample(path, ws, ax_c, t, method, atol, hint)
    k0 = b0 - c0
    err_split = ce + EPS * (cc * abs(c0) + 2 * abs(b0))
    split = (k0, b1 - c1, b2 - c2, cc, err_split)
    if abs(k0) >= 0.5 * abs(b0):
        return split
    r = _sample(path, ws, ax_k, t, method, atol)
    err_whole = r[4] + EPS * r[3] * abs(r[0])
    return r if err_whole < err_split else split


def _hermite5(ta: float, ya: float, da: float, ea: float, tb: float, yb: float, db: float, eb: float,
              t: float) -> float:
    d = tb - ta
    x = (t - ta) / d
    x2 = x * x
    x3 = x2 * x
    x4 = x3 * x
    x5 = x4 * x
    h0 = 1 - 10 * x3 + 15 * x4 - 6 * x5
    h1 = x - 6 * x3 + 8 * x4 - 3 * x5
    h2 = 0.5 * (x2 - 3 * x3 + 3 * x4 - x5)
    h4 = -4 * x3 + 7 * x4 - 3 * x5
    h5 = 0.5 * (x3 - 2 * x4 + x5)
    return h0 * ya + d * h1 * da + d * d * h2 * ea + (1 - h0) * yb + d * h4 * db + d * d * h5 * eb


def _compute_response(sampler: Callable[..., Tuple[float, float, float, float, float]],
                      start: Optional[Tuple[float, float, float]], t_a: float, t_b: float,
                      opt: Dict[str, Any]) -> Dict[str, Any]:
    method = opt.get('method') or 'parabola'
    rtol = opt.get('rtol') or RESP_RTOL
    atol_rel = RESP_ATOL if method == 'parabola' else 1e-9 if method == 'talbot' else 1e-8
    max_pts = opt.get('maxPts') or RESP_MAXPTS
    per = opt.get('perDecade') or RESP_PER_DECADE
    # logarithmic in t - d, d the plug-flow delay
    dl = opt.get('delay') or 0.0
    n0 = max(16, math.ceil(math.log10((t_b - dl) / (t_a - dl)) * per) + 1)
    T: List[float] = []
    H: List[float] = []
    D: List[float] = []
    D2: List[float] = []
    peak = 0.0
    max_cond = 1.0
    max_err = 0.0
    pe = opt.get('peakEstimate') or 0.0
    atol = 1e-3 * RESP_ATOL * pe if pe > 0 else 0.0
    hint = {'tries': 0, 'fails': 0}
    if start is not None:
        T.append(0.0)
        H.append(start[0])
        D.append(start[1])
        D2.append(start[2])
        peak = abs(start[0])
    for k in range(n0):
        t = dl + (t_a - dl) * ((t_b - dl) / (t_a - dl)) ** (k / (n0 - 1))
        h, dh, d2, c, e = sampler(t, atol, hint)
        if e > max_err:
            max_err = e
        T.append(t)
        H.append(h)
        D.append(dh)
        D2.append(d2)
        if abs(h) > peak:
            peak = abs(h)
        if c > max_cond:
            max_cond = c
    flag = [True] * (len(T) - 1)
    for _ in range(30):
        nT = [T[0]]
        nH = [H[0]]
        nD = [D[0]]
        nD2 = [D2[0]]
        nF: List[bool] = []
        inserted = False
        for k in range(len(T) - 1):
            if flag[k] and len(T) + len(nT) < 2 * max_pts and (
                    T[k] == dl or (T[k + 1] - dl) / (T[k] - dl) > 1 + 1e-9):
                tm = dl + 0.5 * (T[k + 1] - dl) if T[k] == dl else dl + math.sqrt((T[k] - dl) * (T[k + 1] - dl))
                h, dh, d2, c, e = sampler(tm, max(atol, 1e-3 * RESP_ATOL * peak), hint)
                if e > max_err:
                    max_err = e
                if abs(h) > peak:
                    peak = abs(h)
                if c > max_cond:
                    max_cond = c
                p = _hermite5(T[k], H[k], D[k], D2[k], T[k + 1], H[k + 1], D[k + 1], D2[k + 1], tm)
                # where de Hoog made most samples, to what de Hoog can deliver
                dh0 = hint['fails'] > 0.5 * hint['tries']
                ok = abs(h - p) <= (max(rtol, 1e-7) if dh0 else rtol) * abs(h) + (
                    max(atol_rel, 1e-10) if dh0 else atol_rel) * peak
                nT.append(tm)
                nH.append(h)
                nD.append(dh)
                nD2.append(d2)
                nF.append(not ok)
                nF.append(not ok)
                if not ok:
                    inserted = True
            else:
                nF.append(False)
            nT.append(T[k + 1])
            nH.append(H[k + 1])
            nD.append(D[k + 1])
            nD2.append(D2[k + 1])
        T, H, D, D2, flag = nT, nH, nD, nD2, nF
        if not inserted or len(T) >= max_pts:
            break
    n = len(T)
    integral = 0.0
    t_peak = T[0]
    pk = -INF
    for k in range(n):
        if H[k] > pk:
            pk = H[k]
            t_peak = T[k]
    for k in range(n - 1):
        d = T[k + 1] - T[k]
        integral += d * (0.5 * (H[k] + H[k + 1]) + d * (D[k] - D[k + 1]) / 10 + d * d * (D2[k] + D2[k + 1]) / 120)
    return {'t': T, 'h': H, 'dh': D, 'd2h': D2, 'peak': max(pk, 0.0), 'tPeak': t_peak, 'integral': integral,
            'maxCond': max_cond, 'maxErr': max_err / max(pk, 1e-300)}


def _pair_of(path: LaplacePath, i: int, j: int, kind: Any) -> Optional[Dict[str, Any]]:
    blk = _block_of(path, i, j)
    if blk is None:
        return None
    k = _kind_of(kind)
    return {'blk': blk, 'kind': k, 'shift': path.tw * blk.Rmin if k != INVENTORY and path.inf_pe else 0.0}


def _axis_of(path: LaplacePath, pr: Dict[str, Any]) -> Dict[str, Any]:
    key = (pr['blk'].i, pr['blk'].j, pr['kind'])
    ax = path.axes.get(key)
    if ax is None:
        t_lo = pr['shift'] * (1 + 1e-9) if pr['shift'] > 0 else path.tw * 1e-6
        ax = _real_axis(path, path.ws, pr, t_lo, T_CAP)
        ax['tLo'] = t_lo
        path.axes[key] = ax
    return ax


def _inventory_axes(path: LaplacePath, i: int, j: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return (_axis_of(path, _pair_of(path, i, j, DECAYED)), _axis_of(path, _pair_of(path, i, j, INVENTORY)))


def response_at(path: LaplacePath, i: int, j: int, t: float, kind: Any = 'release',
                method: Optional[str] = None, **opt: Any) -> Dict[str, Any]:
    """The response of i to a unit pulse of j at t = 0 -- the release rate,
    or with ``kind='inventory'`` what the path holds -- and its first two
    derivatives, inverted at t directly."""
    pr = _pair_of(path, i, j, kind)
    if pr is None:
        return {'h': 0.0, 'dh': 0.0, 'd2': 0.0}
    ws = path.ws
    if pr['kind'] == INVENTORY:
        if not t > 0:
            h, dh, d2 = _bateman(path, ws, pr['blk'], 0.0)
            return {'h': h, 'dh': dh, 'd2': d2}
        ax_c, ax_k = _inventory_axes(path, i, j)
        h, dh, d2, cond, err = _sample_inventory(path, ws, ax_c, ax_k, t, method, 0.0)
        return {'h': h, 'dh': dh, 'd2': d2, 'cond': cond, 'err': err}
    if method == 'dehoog':
        return {'h': _invert_de_hoog(path, ws, pr, t, opt),
                'dh': _invert_de_hoog(path, ws, pr, t, {**opt, 'deriv': 1}),
                'd2': _invert_de_hoog(path, ws, pr, t, {**opt, 'deriv': 2})}
    ax = _axis_of(path, pr)
    if method == 'talbot':
        return _invert_talbot(path, ws, ax, t, opt)
    return _invert_parabola(path, ws, ax, t, opt)


def _add_early_mass(path: LaplacePath, pr: Dict[str, Any], resp: Dict[str, Any]) -> None:
    """Under plug flow, what arrives before a response's first time, kept as a
    point mass ``m0`` there and added to its integral (``addEarlyMass``)."""
    resp['m0'] = 0.0
    if not path.inf_pe or pr['kind'] == INVENTORY or len(resp['t']) < 2:
        return
    S = _invert_de_hoog(path, path.ws, pr, resp['t'][0], {'M': _de_hoog_terms(path), 'deriv': -1})
    if S > 0 and math.isfinite(S):
        resp['m0'] = S
        resp['integral'] += S


def _mass_balance(path: LaplacePath, ax: Dict[str, Any], resp: Dict[str, Any], tol: float) -> Dict[str, Any]:
    """A release response's integral against what leaves the path by its last
    time (``massBalance``): ``{ok, checked, expected, rel}``."""
    T0 = resp['T0']
    if not abs(T0) > 1e-30:
        return {'ok': True, 'checked': False, 'expected': T0, 'rel': 0.0}
    expected = T0
    n = len(resp['t'])
    if n:
        tl = resp['t'][n - 1]
        tt = tl - ax['pr']['shift']
        sad = _saddle_at(ax, tt) if tt > 0 else None
        rest = _exp(sad['w']) if sad is not None and not sad['beyond'] and sad['s'] <= 0 else INF
        if not rest <= 1e-10 * abs(T0):
            S = _invert_de_hoog(path, path.ws, ax['pr'], tl, {'M': _de_hoog_terms(path), 'deriv': -1})
            if math.isfinite(S):
                expected = S
    rel = abs(resp['integral'] - expected) / max(abs(T0), 1e-10)
    return {'ok': rel <= tol, 'checked': True, 'expected': expected, 'rel': rel}


def unit_response(path: LaplacePath, i: int, j: int, kind: Any = 'release', t_max: Optional[float] = None,
                  method: Optional[str] = None, rtol: Optional[float] = None,
                  per_decade: Optional[int] = None, max_pts: Optional[int] = None) -> Dict[str, Any]:
    """One unit response, tabulated on an adaptive grid over [0, t_max]:
    ``{i, j, kind, t, h, dh, d2h, peak, tPeak, integral, T0}``, and for a
    release ``m0``, ``expected``, ``balanced`` and ``rel``: its integral held
    to what leaves the path by its last time, worked out again from far
    earlier on a finer grid when it misses (``unitResponse``)."""
    pr = _pair_of(path, i, j, kind)
    kname = KINDS[_kind_of(kind)]

    def empty() -> Dict[str, Any]:
        return {'t': [], 'h': [], 'dh': [], 'd2h': [], 'peak': 0.0, 'tPeak': NAN, 'integral': 0.0, 'maxCond': 1.0,
                'maxErr': 0.0}

    if pr is None:
        return {'i': i, 'j': j, 'kind': kname, **empty(), 'T0': 0.0}
    ws = path.ws
    tm = min(T_CAP if t_max is None else t_max, T_CAP)
    o = {'method': method, 'perDecade': per_decade, 'rtol': rtol, 'maxPts': max_pts}
    T0 = transfer(path, 0.0, 0.0, i, j).real
    if not math.isfinite(T0):
        T0 = transfer(path, 1e-300, 0.0, i, j).real
    if pr['kind'] == INVENTORY:
        ax_c, ax_k = _inventory_axes(path, i, j)

        def sampler_k(t: float, atol: float, hint: Optional[Dict[str, int]] = None) -> Tuple[float, float, float,
                                                                                            float, float]:
            return _sample_inventory(path, ws, ax_c, ax_k, t, method, atol, hint)

        start = _bateman(path, ws, pr['blk'], 0.0)
        sup = _response_support(ax_k, ax_k['tLo'], T_CAP)
        t_a = min(sup['tLo'] if sup else ax_k['tLo'], ax_k['tLo'], tm / 2)
        t_b = min(max(sup['tHi'], 2 * t_a), tm) if sup else tm
        resp = _compute_response(sampler_k, start, t_a, t_b, {**o, 'peakEstimate': 1.0})
        return {'i': i, 'j': j, 'kind': kname, **resp, 'T0': T0}
    ax = _axis_of(path, pr)
    sup = _response_support(ax, ax['tLo'], T_CAP)
    t_a = sup['tLo'] if sup else NAN
    t_b = min(sup['tHi'], tm) if sup else NAN

    def sampler(t: float, atol: float, hint: Optional[Dict[str, int]] = None) -> Tuple[float, float, float, float,
                                                                                     float]:
        return _sample(path, ws, ax, t, method, atol, hint)

    ropt = {**o, 'peakEstimate': _exp(sup['logPeak']) if sup else 0.0, 'delay': pr['shift']}
    resp = _compute_response(sampler, None, t_a, t_b, ropt) if sup and t_b > t_a * (1 + 1e-9) else empty()
    _add_early_mass(path, pr, resp)
    resp['T0'] = T0
    # a check for failures, not for the last digits
    tol = max(1e-5, 50 * (rtol or RESP_RTOL))
    bal = _mass_balance(path, ax, resp, tol)
    if not bal['ok']:
        t_a2 = max(ax['tLo'], (sup['tLo'] if sup else ax['tLo']) / 1e3)
        t_b2 = t_b if sup else min(T_CAP, tm)
        if t_b2 > t_a2 * (1 + 1e-9):
            r2 = _compute_response(sampler, None, t_a2, t_b2, {**ropt, 'perDecade': 2 * (per_decade or RESP_PER_DECADE),
                                                              'maxPts': 2 * (max_pts or RESP_MAXPTS)})
            _add_early_mass(path, pr, r2)
            r2['T0'] = T0
            b2 = _mass_balance(path, ax, r2, tol)
            if b2['rel'] < bal['rel']:
                resp = r2
                bal = b2
    return {'i': i, 'j': j, 'kind': kname, **resp, 'T0': T0, 'expected': bal['expected'], 'balanced': bal['ok'],
            'rel': bal['rel'], 'checked': bal['checked']}


def unit_responses(path: LaplacePath, kinds: Sequence[str] = KINDS, sources: Optional[Sequence[int]] = None,
                   **opt: Any) -> Dict[str, List[Optional[Dict[str, Any]]]]:
    """Every unit response of the path: ``{'release': [...], 'inventory':
    [...]}``, each indexed i*n + j (None where j never becomes i)."""
    n = path.n
    out: Dict[str, List[Optional[Dict[str, Any]]]] = {'release': [None] * (n * n), 'inventory': [None] * (n * n)}
    srcs = range(n) if sources is None else sources
    for kind in kinds:
        for j in srcs:
            for i in range(n):
                if not path.reach[j][i]:
                    continue
                out[kind][i * n + j] = unit_response(path, i, j, kind=kind, **opt)
    return out


# ---------------------------------------------------------------------------
# Inflow series and the convolution
# ---------------------------------------------------------------------------

def inflow_series(points: Sequence[Sequence[float]], name: str = 'Inflow') -> Dict[str, Any]:
    """An inflow history from [t, rate] points: piecewise linear, zero before
    the first and after the last; a repeated time is a step."""
    t: List[float] = []
    v: List[float] = []
    for p in points or []:
        a = _num(p[0])
        b = _num(p[1])
        if not math.isfinite(a) or not math.isfinite(b):
            raise LaplacePathError(f'{name}: every point needs a finite time and rate.')
        if t and a < t[-1]:
            raise LaplacePathError(f'{name}: the times must not decrease ({a} after {t[-1]}).')
        if t and a == t[-1] and b == v[-1]:
            continue
        t.append(a)
        v.append(b)
    if len(t) < 2:
        raise LaplacePathError(f'{name}: at least two points are needed.')
    first = -1
    last = -1
    for k in range(len(t)):
        nz = v[k] != 0 or (k + 1 < len(t) and v[k + 1] != 0 and t[k + 1] > t[k]) or (
            k > 0 and v[k - 1] != 0 and t[k] > t[k - 1])
        if nz:
            if first < 0:
                first = k
            last = k
    mass = 0.0
    for k in range(len(t) - 1):
        mass += 0.5 * (t[k + 1] - t[k]) * (v[k] + v[k + 1])
    return {'t': t, 'v': v, 'tFirst': NAN if first < 0 else t[first], 'tLast': NAN if last < 0 else t[last],
            'mass': mass, 'empty': first < 0}


GL_X1 = 0.3399810435848563
GL_X2 = 0.8611363115940526
GL_W1 = 0.6521451548625461
GL_W2 = 0.3478548451374538
_GL = ((-GL_X1, GL_W1), (GL_X1, GL_W1), (-GL_X2, GL_W2), (GL_X2, GL_W2))


def _series_at(ser: Dict[str, Any], x: float) -> float:
    """The inflow at time x: linear between its points, zero outside them."""
    st = ser['t']
    n = len(st)
    if not n or x < st[0] or x > st[n - 1]:
        return 0.0
    lo = 0
    hi = n - 1
    while hi - lo > 1:
        c = (lo + hi) >> 1
        if st[c] <= x:
            lo = c
        else:
            hi = c
    d = st[hi] - st[lo]
    return ser['v'][lo] + (ser['v'][hi] - ser['v'][lo]) * (x - st[lo]) / d if d > 0 else ser['v'][hi]


def convolve(resp: Dict[str, Any], ser: Dict[str, Any], t: float) -> float:
    """(h * in)(t): the integral over u of h(u) in(t - u), exactly, and the
    point mass before the first time (``m0``, under plug flow)."""
    rt = resp['t']
    nr = len(rt)
    st = ser['t']
    sv = ser['v']
    ns = len(st)
    if nr < 2 or ser['empty']:
        return 0.0
    m0 = resp.get('m0') or 0.0
    lump = m0 * _series_at(ser, t - rt[0]) if m0 > 0 else 0.0
    u_lo = max(rt[0], t - st[ns - 1])
    u_hi = min(rt[nr - 1], t - st[0], t)
    if not u_hi > u_lo:
        return lump
    a = 0
    b = nr - 1
    while b - a > 1:
        c = (a + b) >> 1
        if rt[c] <= u_lo:
            a = c
        else:
            b = c
    k = a
    x0 = t - u_lo
    lo = 0
    hi = ns - 1
    while hi - lo > 1:
        c = (lo + hi) >> 1
        if st[c] < x0:
            lo = c
        else:
            hi = c
    m = lo
    rh = resp['h']
    rd = resp['dh']
    r2 = resp['d2h']
    total = 0.0
    u = u_lo
    while u < u_hi:
        while k + 1 < nr - 1 and rt[k + 1] <= u:
            k += 1
        while m > 0 and t - st[m] <= u:
            m -= 1
        nxt = u_hi
        if u < rt[k + 1] < nxt:
            nxt = rt[k + 1]
        um = t - st[m]
        if u < um < nxt:
            nxt = um
        if nxt <= u:
            break
        tm0 = st[m]
        tm1 = st[m + 1]
        dseg = tm1 - tm0
        if dseg > 0:
            vm0 = sv[m]
            slope = (sv[m + 1] - vm0) / dseg
            c = 0.5 * (u + nxt)
            hw = 0.5 * (nxt - u)
            q = 0.0
            ta = rt[k]
            tb = rt[k + 1]
            for x, w in _GL:
                uu = c + x * hw
                q += w * _hermite5(ta, rh[k], rd[k], r2[k], tb, rh[k + 1], rd[k + 1], r2[k + 1], uu) * (
                    vm0 + slope * (t - uu - tm0))
            total += hw * q
        u = nxt
    return total + lump


def _sum_over(path: LaplacePath, table: List[Optional[Dict[str, Any]]], inflows: Sequence[Optional[Dict[str, Any]]],
              t: float) -> List[float]:
    n = path.n
    out = [0.0] * n
    for i in range(n):
        s = 0.0
        for j in range(n):
            r = table[i * n + j]
            if r is not None and inflows[j] is not None:
                s += convolve(r, inflows[j], t)
        out[i] = s
    return out


def release_at(path: LaplacePath, responses: Dict[str, List[Optional[Dict[str, Any]]]],
               inflows: Sequence[Optional[Dict[str, Any]]], t: float) -> List[float]:
    """The release of every nuclide at t, from the release responses and one
    inflow series per nuclide (None for none)."""
    return _sum_over(path, responses['release'], inflows, t)


def inventory_at(path: LaplacePath, responses: Dict[str, List[Optional[Dict[str, Any]]]],
                 inflows: Sequence[Optional[Dict[str, Any]]], t: float) -> List[float]:
    """What the path holds of every nuclide at t."""
    return _sum_over(path, responses['inventory'], inflows, t)
