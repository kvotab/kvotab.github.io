"""Global sensitivity analysis: the methods of GlobalSensitivity.jl, as Kompartment runs them.

A port of ``src/domain/gsa.js``, which ports SciML's GlobalSensitivity.jl 2.12.8
(MIT):

- **designed** methods, each an experiment of its own that the model is run
  over: Morris's elementary effects, Sobol's variance decomposition, eFAST,
  RBD-FAST, a two-level fractional factorial, derivative-based measures (DGSM)
  and Shapley effects -- a ``*_design`` function lays out the runs and a
  ``*_indices`` function reads the outputs over them;
- measures **from a sample**, reading any sample the way the correlations do:
  EASI, Borgonovo's moment-independent delta, regional sensitivity analysis
  (RSA) and mutual information;
- the registry the application offers them through: :data:`GSA_METHODS`,
  :func:`gsa_options`, :func:`gsa_runs`, :func:`gsa_refusal`,
  :func:`build_design` (a design from a run's seed), :func:`gsa_table` (one
  method's answer as rows) and :func:`gsa_main`. The SALib methods of
  :mod:`kompartment.stats.salib` are reached through it too.

**Everything is done in probability space.** Each design is drawn in the unit
hypercube, a probability per input, and a point becomes a run through each
input's inverse CDF, as a Latin hypercube sample is. A design's ``u`` is a
K x runs array: row k holds input k's probabilities, column i is design point i.

The deliberate differences from GlobalSensitivity.jl are the application's
(seeded streams instead of Julia's RNG, Morris levels at the middles of the
probability slices, eFAST's points raised to where the harmonics fit, DGSM by
finite differences in probability, a one-input factorial, RSA's dummy spread
over all dummies, and delta's density of a tied class at the whole output's
bandwidth); see the top of ``gsa.js``.

The arithmetic is the application's, sums added in its order, so what uses only
``+ - * /`` and square roots comes out as its numbers bit for bit. The platform's
``exp``, ``log``, ``sin``, ``cos`` and ``asin`` can differ from V8's in the last
bit, which reaches the spectral methods, the kernel density estimate behind
delta, the normal quantile of an interval and the eFAST and RBD-FAST designs.

Designs and results are dictionaries with the application's keys (``K``,
``runs``, ``meanStar``, ``nVar``, ...), so that what they hold reads as the
application's does and can be saved where it saves them.
"""

from __future__ import annotations

import math
import random
import struct
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from ._normal import normal_quantile, phi
from .fft import dct2, irfft, power_spectrum, rfft
from .salib import (
    dgsm_spread, ff_interactions, morris_trajectory_design, mu_star_interval, radial_design, radial_indices,
    sobol_bootstrap, unskew,
)
from .sensitivity import (
    _as_square, _cholesky_lower, _div, _f64, _is_js_integer, _js_floor, _js_max, _js_min, _js_number,
    _js_round, _js_round_array, _js_string, _js_truthy, _seqsum, _sqrt,
)

__all__ = [
    'normal_quantile', 'quantile7', 'average_ranks', 'normal_scores', 'sort_perm', 'compete_rank', 'sinpi',
    'random_permutation', 'permutations_of',
    'morris_design', 'morris_indices',
    'SOBOL_ESTIMATORS', 'sobol_runs', 'sobol_design', 'sobol_indices',
    'efast_samples', 'efast_frequencies', 'efast_design', 'efast_indices',
    'rbd_fast_design', 'rbd_fast_indices',
    'hadamard', 'ff_design', 'ff_indices',
    'dgsm_design', 'dgsm_derivatives', 'dgsm_statistics', 'dgsm_indices',
    'cholesky', 'shapley_design', 'shapley_indices',
    'easi', 'kde_bandwidth', 'kde', 'kde_pdf', 'delta_classes', 'delta_moment',
    'rsa_score', 'rsa', 'histogram_entropy', 'joint_entropy', 'mutual_information',
    'GSA_METHODS', 'GSA_METHOD_IDS', 'gsa_options', 'gsa_runs', 'gsa_refusal', 'build_design', 'gsa_table',
    'gsa_main',
]

# `next` is the application's name for a stream of uniforms, kept so the two read alike.
# pylint: disable=redefined-builtin

Next = Callable[[], float]

# ---------------------------------------------------------------------------
# The small things every method needs, done the way Julia's Statistics does
# them, so that the same data give the same numbers.
# ---------------------------------------------------------------------------


def _segment(a: Any, frm: int, to: int) -> np.ndarray:
    """``a[frm:to]``, NaN where it runs past the end, as a loop over a typed array reads it."""
    v = _f64(a)
    n = max(0, to - frm)
    if frm >= 0 and to <= len(v):
        return v[frm:to]
    out = np.full(n, math.nan)
    for j in range(n):
        i = frm + j
        if 0 <= i < len(v):
            out[j] = v[i]
    return out


def _take(v: np.ndarray, idx: Any) -> np.ndarray:
    """``v[idx[i]]`` for each i, NaN where the index is not in ``v``."""
    ix = np.asarray(idx, dtype=np.int64)
    out = np.full(len(ix), math.nan)
    ok = (ix >= 0) & (ix < len(v))
    out[ok] = v[ix[ok]]
    return out


def _mean(a: Any, frm: int = 0, to: Optional[int] = None) -> float:
    v = _f64(a)
    to = len(v) if to is None else to
    return _div(_seqsum(_segment(v, frm, to)), to - frm)


def _variance(a: Any, frm: int = 0, to: Optional[int] = None) -> float:
    """The sample variance, over n - 1, in two passes as Julia's ``var`` does."""
    v = _f64(a)
    to = len(v) if to is None else to
    seg = _segment(v, frm, to)
    m = _div(_seqsum(seg), to - frm)
    d = seg - m
    return _div(_seqsum(d * d), to - frm - 1)


def _std(a: Any) -> float:
    return _sqrt(_variance(a))


def quantile7(values: Sequence[float], p: float) -> float:
    """Julia's default ``quantile``, Hyndman and Fan's type 7: linear between the order statistics either side."""
    v = np.sort(_f64(values))
    n = len(v)
    if n == 1:
        return float(v[0])
    aleph = n * p + (1 - p)
    if not math.isfinite(aleph) or n == 0:
        return math.nan
    j = _js_min(n - 1, _js_max(1, math.trunc(aleph)))
    g = _js_min(1, _js_max(0, aleph - j))
    a = float(v[j - 1]) if 0 <= j - 1 < n else math.nan
    b = float(v[j]) if 0 <= j < n else math.nan
    return a + g * (b - a)


def _sort_perm(x: Any) -> np.ndarray:
    """:func:`sort_perm` as an index array."""
    return np.argsort(_f64(x), kind='stable')


def sort_perm(x: Sequence[float]) -> List[int]:
    """The indices that sort ``x``, ties in their original order.

    (With NaN in ``x`` the application's order is whatever V8's sort makes of
    a comparison NaN never wins; here NaN sorts last.)
    """
    return [int(i) for i in _sort_perm(x)]


def _runs(s: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Where each run of equal values in the sorted ``s`` starts and ends."""
    m = len(s)
    change = np.empty(m, dtype=bool)
    change[0] = True
    change[1:] = s[1:] != s[:-1]
    starts = np.flatnonzero(change)
    ends = np.append(starts[1:], m) - 1
    return starts, ends


def average_ranks(x: Sequence[float]) -> np.ndarray:
    """Ranks from 1, ties sharing the mean of the places they span."""
    v = _f64(x)
    r = np.zeros(len(v))
    if not len(v):
        return r
    order = _sort_perm(v)
    starts, ends = _runs(v[order])
    r[order] = np.repeat((starts + ends) / 2 + 1, ends - starts + 1)
    return r


def normal_scores(y: Sequence[float]) -> np.ndarray:
    """Each value replaced by the standard normal's quantile at its rank, ``Phi^-1((r - 1/2)/n)``.

    The same order, and a marginal a Gaussian kernel and Silverman's rule were
    made for.
    """
    r = average_ranks(y)
    n = len(r)
    return np.array([normal_quantile((v - 0.5) / n) for v in r.tolist()], dtype=np.float64)


def compete_rank(x: Sequence[float]) -> np.ndarray:
    """Competition ranks ("1224"): a tie takes the lowest rank of the places it spans.

    As StatsBase's ``competerank``.
    """
    v = _f64(x)
    r = np.zeros(len(v))
    if not len(v):
        return r
    order = _sort_perm(v)
    starts, ends = _runs(v[order])
    r[order] = np.repeat(starts + 1.0, ends - starts + 1)
    return r


def sinpi(x: float) -> float:
    """``sin(pi x)``, reduced exactly first, as Julia's ``sinpi``."""
    r = math.fmod(x, 2) if math.isfinite(x) else math.nan
    if r < 0:
        r += 2
    if r < 0.25:
        return math.sin(math.pi * r)
    if r < 0.75:
        return math.cos(math.pi * (r - 0.5))
    if r < 1.25:
        return -math.sin(math.pi * (r - 1))
    if r < 1.75:
        return -math.cos(math.pi * (r - 1.5))
    return math.sin(math.pi * (r - 2)) if r == r else math.nan


def _sinpi_array(x: np.ndarray) -> np.ndarray:
    """:func:`sinpi` of every element, branch for branch."""
    with np.errstate(all='ignore'):
        r = np.fmod(x, 2.0)
        r = np.where(r < 0, r + 2, r)
        out = np.full(r.shape, math.nan)
        c1 = r < 0.25
        c2 = ~c1 & (r < 0.75)
        c3 = ~c1 & ~c2 & (r < 1.25)
        c4 = ~c1 & ~c2 & ~c3 & (r < 1.75)
        c5 = ~c1 & ~c2 & ~c3 & ~c4
        out[c1] = np.sin(np.pi * r[c1])
        out[c2] = np.cos(np.pi * (r[c2] - 0.5))
        out[c3] = -np.sin(np.pi * (r[c3] - 1))
        out[c4] = -np.cos(np.pi * (r[c4] - 1.5))
        out[c5] = np.sin(np.pi * (r[c5] - 2))
    return out


def _linspace(a: float, b: float, n: int) -> np.ndarray:
    """``n`` evenly spaced from ``a`` to ``b``, both included."""
    n = int(n)
    if n <= 0:
        return np.zeros(0)
    if n == 1:
        return np.array([a], dtype=np.float64)
    with np.errstate(all='ignore'):
        step = (b - a) / (n - 1)
        out = a + np.arange(n, dtype=np.float64) * step
    out[n - 1] = b
    return out


def random_permutation(n: int, next: Next) -> List[int]:
    """A uniformly random permutation of 0..n-1, Fisher-Yates from the end."""
    p = list(range(int(n)))
    for i in range(len(p) - 1, 0, -1):
        j = math.floor(next() * (i + 1))
        p[i], p[j] = p[j], p[i]
    return p


def _gaussian(next: Next) -> float:
    """A standard normal from two uniforms, Box-Muller; the stream decides both."""
    u = next()
    while not u > 0:
        u = next()
    v = next()
    return math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * v)


def permutations_of(n: int) -> List[List[int]]:
    """Every permutation of 0..n-1, in lexicographic order, as Combinatorics' ``permutations``."""
    out = []
    a = list(range(n))
    while True:
        out.append(list(a))
        i = n - 2
        while i >= 0 and a[i] >= a[i + 1]:
            i -= 1
        if i < 0:
            return out
        j = n - 1
        while a[j] <= a[i]:
            j -= 1
        a[i], a[j] = a[j], a[i]
        a[i + 1:] = a[i + 1:][::-1]


def _centred(y: Any, frm: int = 0, to: Optional[int] = None) -> np.ndarray:
    """A slice, less its mean: the mean is all of frequency zero, which no spectral method reads."""
    v = _f64(y)
    to = len(v) if to is None else to
    m = _mean(v, frm, to)
    return _segment(v, frm, to) - m


def _get(a: Any, k: Any) -> float:
    """``a[k]``, NaN where a typed array has nothing (past its ends, or at an index that is not an integer)."""
    try:
        f = float(k)
    except (TypeError, ValueError):
        return math.nan
    if not (math.isfinite(f) and f == math.floor(f) and 0 <= f < len(a)):
        return math.nan
    return float(a[int(f)])


def _upto(m: Any) -> range:
    """``1, 2, ...`` while ``<= m``, as the application's loops count."""
    f = _js_floor(m) if m == m else 0
    return range(1, int(f) + 1) if math.isfinite(f) else range(0)


# ---------------------------------------------------------------------------
# Morris's elementary effects: GlobalSensitivity.jl's random walks.
# ---------------------------------------------------------------------------


def _int32(v: float) -> int:
    """``ToInt32``, as a store into an ``Int32Array`` does it."""
    if not math.isfinite(v):
        return 0
    i = int(v) & 0xFFFFFFFF
    return i - 0x100000000 if i >= 0x80000000 else i


def morris_design(K: int, *, trajectories: int = 10, points: int = 10, levels: int = 100,
                  next: Next) -> Dict[str, Any]:
    """GlobalSensitivity.jl's Morris design: ``trajectories`` random walks of ``points`` runs.

    Each walk starts at a random level of each input and every step moves one
    input, chosen at random, one level up or down on a grid of ``levels``,
    bouncing off the ends. Levels sit at the middles of equal slices of
    probability, ``(j + 1/2)/levels``.
    """
    if not levels >= 2:
        raise ValueError('Morris needs at least two levels.')
    if not points >= 2:
        raise ValueError('A Morris trajectory needs at least two points.')
    runs = trajectories * points
    u = np.zeros((K, runs))
    at = [0] * K
    for t in range(trajectories):
        # rand(rng, 1:p) for each input: where the walk starts.
        for k in range(K):
            at[k] = _int32(math.floor(next() * levels))
        for s in range(points):
            j = math.floor(next() * K)
            step = -1 if next() < 0.5 else 1
            if 0 <= j < K:
                at[j] = _int32(at[j] + step)
                if at[j] > levels - 1:
                    at[j] -= 2
                elif at[j] < 0:
                    at[j] += 2
            if K:
                u[:, t * points + s] = (np.array(at, dtype=np.float64) + 0.5) / levels
    return {'method': 'morris', 'K': K, 'trajectories': trajectories, 'points': points, 'levels': levels,
            'u': u, 'runs': runs}


def morris_indices(y: Sequence[float], design: Mapping[str, Any], *, relative: bool = False) -> Dict[str, Any]:
    """The elementary effects of a Morris design and their statistics, per input.

    Returns ``{'mean', 'meanStar', 'variance', 'count', 'effects'}``: mu, mu*
    (the mean of the effects' magnitudes), their variance (NaN for a single
    effect), how many each input has (0 for an input no step moved, whose
    statistics are then 0), and the effects themselves in the order the design
    made them. With ``relative`` each effect is divided by the output.
    """
    K = design['K']
    trajectories = design['trajectories']
    points = design['points']
    u = _f64(design['u'])
    yv = _segment(y, 0, max(len(y), trajectories * points))
    effects: List[List[float]] = [[] for _ in range(K)]
    for t in range(trajectories):
        y1 = _get(yv, t * points)
        for j in range(t * points, (t + 1) * points - 1):
            y2 = y1
            if K:
                d = u[:, j + 1] - u[:, j]
                moved = np.flatnonzero(np.abs(d) > 0)
                changed = int(moved[0]) if len(moved) else -1
                dl = _seqsum(d)
            else:
                changed = -1
                dl = 0.0
            y1 = _get(yv, j + 1)
            if not relative:
                e = _div(y1 - y2, dl)
            elif dl > 0:
                e = _div(y1 - y2, y2 * dl)
            else:
                e = _div(y1 - y2, y1 * dl)
            if changed >= 0:
                effects[changed].append(e)
    mean = np.zeros(K)
    mean_star = np.zeros(K)
    var = np.zeros(K)
    count = np.zeros(K, dtype=np.int32)
    for k in range(K):
        e = effects[k]
        count[k] = len(e)
        if not e:
            continue
        mean[k] = _mean(e)
        mean_star[k] = _mean(np.abs(_f64(e)))
        # One effect has no spread; Julia says NaN, and so does this.
        var[k] = _variance(e) if len(e) > 1 else math.nan
    return {'mean': mean, 'meanStar': mean_star, 'variance': var, 'count': count, 'effects': effects}


# ---------------------------------------------------------------------------
# Sobol's indices, by Saltelli's design.
# ---------------------------------------------------------------------------

#: The estimators of the total index :func:`sobol_indices` offers.
SOBOL_ESTIMATORS = ['jansen1999', 'sobol2007', 'homma1996', 'janon2014']


def sobol_runs(K: int, n: int, *, second: bool = False, blocks: int = 1) -> int:
    """How many runs a Sobol design is: ``(K + 2) n`` per block, ``(2K + 2) n`` with pairs."""
    return blocks * (2 * K + 2 if second else K + 2) * n


def _set(col: np.ndarray, src: np.ndarray, offset: int) -> None:
    """``col.set(src, offset)``: refused past the end, as a typed array refuses it."""
    if offset < 0 or offset + len(src) > len(col):
        raise ValueError('offset is out of bounds')
    col[offset:offset + len(src)] = src


def sobol_design(K: int, n: int, *, second: bool = False, blocks: int = 1,
                 draw: Callable[[int, str, int], Sequence[float]]) -> Dict[str, Any]:
    """Saltelli's design: samples A and B of ``n`` points, and A with each input's column from B.

    ``draw(k, which, block)`` gives the ``n`` probabilities of input k in
    sample ``'A'`` or ``'B'`` of a block. With ``second``, B with each column
    from A too, for every pair's interaction; ``blocks`` repeats the design.
    """
    per = (2 * K + 2 if second else K + 2) * n
    u = np.zeros((K, blocks * per))
    for b in range(blocks):
        base = b * per
        for k in range(K):
            A = _f64(draw(k, 'A', b))
            B = _f64(draw(k, 'B', b))
            col = u[k]
            _set(col, A, base)
            _set(col, B, base + n)
            # A with column j from B, for each j; then B with column j from A.
            for j in range(K):
                _set(col, B if k == j else A, base + (2 + j) * n)
            if second:
                for j in range(K):
                    _set(col, A if k == j else B, base + (2 + K + j) * n)
    return {'method': 'sobol', 'K': K, 'n': n, 'second': second, 'blocks': blocks, 'u': u, 'runs': blocks * per}


def _total_effect(estimator: Any, fA: np.ndarray, a: np.ndarray, n: int, sumA: float) -> float:
    """The ``E_i`` term of a total index, by one of the four estimators (Jansen's for any other name)."""
    if estimator == 'homma1996':
        m = _div(sumA, n)
        d = fA - m
        ss = _seqsum(d * d)
        dot = _seqsum(fA * a)
        return _div(ss, n - 1) - _div(dot, n) + m * m
    if estimator == 'sobol2007':
        return _div(_seqsum(fA * (fA - a)), n)
    if estimator == 'janon2014':
        sq = _seqsum(fA * fA + a * a)
        total = _seqsum(fA + a)
        dot = _seqsum(fA * a)
        half = _seqsum((fA + a) / 2)
        half_sq = _seqsum((fA * fA + a * a) / 2)
        mean = _div(total, 2 * n)
        first = _div(sq, 2 * n) - mean * mean
        inv = _div(1, n)
        h = inv * half
        num = inv * dot - h * h
        den = inv * half_sq - h * h
        return first * (1 - _div(num, den))
    d = fA - a
    return _div(_seqsum(d * d), 2 * n)


def sobol_indices(y: Sequence[float], spec: Mapping[str, Any]) -> Dict[str, Any]:
    """Sobol's first-order and total indices from the outputs over a Saltelli design.

    ``spec`` holds ``K``, ``n`` and optionally ``second``, ``blocks``,
    ``estimator`` (one of :data:`SOBOL_ESTIMATORS`, Jansen 1999 by default) and
    ``conf``. S1 is Saltelli 2010's estimator. Returns ``{'S1', 'ST', 'S2',
    'S1ci', 'STci', 'S2ci'}``: ``S2`` is K x K flattened, the upper triangle
    filled; with more than one block every index is the mean over the blocks
    and the intervals the spread between them, and with one they are None.
    """
    K = spec['K']
    n = spec['n']
    second = _js_truthy(spec.get('second', False))
    blocks = spec.get('blocks')
    blocks = 1 if blocks is None else blocks
    estimator = spec.get('estimator', 'jansen1999')
    conf = spec.get('conf')
    conf = 0.95 if conf is None else conf
    step = 2 * K + 2 if second else K + 2
    yv = _f64(y)
    S1s = []
    STs = []
    S2s = []
    with np.errstate(all='ignore'):
        for b in range(blocks):
            base = b * step * n
            fA = _segment(yv, base, base + n)
            fB = _segment(yv, base + n, base + 2 * n)
            # The variance over A and B together, 2n points.
            vary = _variance(yv, base, base + 2 * n)
            V = np.zeros(K)
            E = np.zeros(K)
            sumA = _seqsum(fA)
            for k in range(K):
                a = _segment(yv, base + (2 + k) * n, base + (3 + k) * n)
                V[k] = _div(_seqsum(fB * (a - fA)), n)
                E[k] = _total_effect(estimator, fA, a, n, sumA)
            S1s.append(V / vary)
            STs.append(E / vary)
            if second:
                S2 = np.zeros(K * K)
                ab = fA * fB
                for k in range(K):
                    bk = _segment(yv, base + (2 + K + k) * n, base + (3 + K + k) * n)
                    for j in range(k + 1, K):
                        aj = _segment(yv, base + (2 + j) * n, base + (3 + j) * n)
                        s = _seqsum(bk * aj - ab)
                        S2[k * K + j] = _div(_div(s, n) - (V[k] + V[j]), vary)
                S2s.append(S2)
    if blocks == 1:
        return {'S1': S1s[0], 'ST': STs[0], 'S2': S2s[0] if second else None,
                'S1ci': None, 'STci': None, 'S2ci': None}
    z = normal_quantile((1 + conf) / 2)

    def pool(items: List[np.ndarray], length: int) -> Tuple[np.ndarray, np.ndarray]:
        m = np.zeros(length)
        ci = np.zeros(length)
        for i in range(length):
            v = [float(a[i]) for a in items]
            m[i] = _mean(v)
            ci[i] = _div(z * _std(v), math.sqrt(len(v)))
        return m, ci

    S1, S1ci = pool(S1s, K)
    ST, STci = pool(STs, K)
    S2, S2ci = pool(S2s, K * K) if second else (None, None)
    return {'S1': S1, 'ST': ST, 'S2': S2, 'S1ci': S1ci, 'STci': STci, 'S2ci': S2ci}


# ---------------------------------------------------------------------------
# eFAST: Saltelli, Tarantola and Chan's extended Fourier amplitude test.
# ---------------------------------------------------------------------------


def efast_samples(n: float, M: int = 4) -> int:
    """The smallest number of points at or above ``n`` that eFAST can use with ``M`` harmonics.

    (For a number that is not finite, or no harmonics, the application's loop
    never ends; this raises instead.)
    """
    N = _js_max(_js_round(n), 4 * M * M + 1)
    if not math.isfinite(N) or not M >= 1:
        raise ValueError('eFAST needs a number of points and at least one harmonic.')
    N = int(N)
    while True:
        w = math.floor((N - 1) / (2 * M))
        if math.floor(w / (2 * M)) >= 1 and M * w <= math.floor(N / 2) - 1:
            return N
        N += 1


def efast_frequencies(K: int, N: int, M: int = 4) -> List[Any]:
    """omega_1 and the complementary frequencies, as GlobalSensitivity.jl chooses them."""
    if K < 1:
        raise ValueError('Invalid array length')
    omega: List[Any] = [_js_floor(_div(N - 1, 2 * M))]
    m = _js_floor(_div(omega[0], 2 * M))
    if m >= K - 1:
        # floor.(Int, range(1, m, length = K - 1))
        r = [1] if K - 1 == 1 else [1 + _div(i * (m - 1), K - 2) for i in range(K - 1)]
        omega.extend(_js_floor(v) for v in r)
    else:
        omega.extend((i % m) + 1 if m else math.nan for i in range(K - 1))
    return omega


def efast_design(K: int, N: int, *, harmonics: int = 4, phases: Sequence[float]) -> Dict[str, Any]:
    """The eFAST design: ``N`` points along one curve per input, ``K N`` runs.

    Along curve i input i oscillates at omega_1 and every other at a lower
    frequency; ``phases`` holds one phase per curve, in [0, 2).
    """
    M = harmonics
    omega = efast_frequencies(K, N, M)
    u = np.zeros((K, K * N))
    temp: List[Any] = [0] * K
    s = _div(2, N) * np.arange(N, dtype=np.float64)
    for i in range(K):
        temp[i] = omega[0]
        for k in range(i):
            temp[k] = omega[k + 1]
        for k in range(i + 1, K):
            temp[k] = omega[k]
        phi0 = phases[i]
        for j in range(K):
            with np.errstate(all='ignore'):
                u[j, i * N:(i + 1) * N] = 0.5 + (1 / math.pi) * np.arcsin(_sinpi_array(temp[j] * s + phi0))
    return {'method': 'efast', 'K': K, 'N': N, 'harmonics': M, 'omega': omega, 'u': u, 'runs': K * N}


def efast_indices(y: Sequence[float], spec: Mapping[str, Any]) -> Dict[str, np.ndarray]:
    """eFAST's first-order and total indices from the outputs over its design.

    ``spec`` holds ``K``, ``N``, ``omega`` and optionally ``harmonics``. S1 is
    the power at omega_1 and its harmonics; S_T one less everything at the
    other inputs' frequencies. Returns ``{'S1', 'ST'}``.
    """
    K = spec['K']
    N = spec['N']
    M = spec.get('harmonics')
    M = 4 if M is None else M
    omega = spec['omega']
    yv = _f64(y)
    S1 = np.zeros(K)
    ST = np.zeros(K)
    w = omega[0]
    last = math.floor(N / 2) - 1
    for i in range(K):
        P = power_spectrum(_centred(yv, i * N, (i + 1) * N))
        z = _seqsum([_get(P, k) for k in range(1, last + 1)])
        first = _seqsum([_get(P, p * w) for p in _upto(M)])
        low = _seqsum([_get(P, k) for k in _upto(_div(w, 2))])
        S1[i] = _div(first, z)
        ST[i] = 1 - _div(low, z)
    return {'S1': S1, 'ST': ST}


# ---------------------------------------------------------------------------
# RBD-FAST: Tarantola, Gatelli and Mara's random balance design.
# ---------------------------------------------------------------------------


def rbd_fast_design(K: int, N: int, *, perms: Sequence[Sequence[int]]) -> Dict[str, Any]:
    """The random balance design: one periodic curve of ``N`` runs, each input along it in its own order.

    ``perms`` holds one random permutation of 0..N-1 per input. Returns the
    design with ``s``, each input's positions on the curve.
    """
    s0 = _linspace(-math.pi, math.pi, N)
    s = np.zeros((K, N))
    u = np.zeros((K, N))
    for k in range(K):
        idx = list(perms[k])[:N]
        sk = _take(s0, idx)
        if len(sk) < N:
            sk = np.concatenate([sk, np.full(N - len(sk), math.nan)])
        s[k] = sk
        with np.errstate(all='ignore'):
            u[k] = 0.5 + np.arcsin(np.sin(sk)) / math.pi
    return {'method': 'rbdfast', 'K': K, 'N': N, 's': s, 'u': u, 'runs': N}


def rbd_fast_indices(y: Sequence[float], spec: Mapping[str, Any], *, harmonics: int = 6) -> np.ndarray:
    """RBD-FAST's first-order index of each input: the power in the first ``harmonics`` frequencies along its order.

    ``spec`` holds ``K`` and ``s``, as :func:`rbd_fast_design` gives them.
    """
    K = spec['K']
    s = spec['s']
    yv = _f64(y)
    N = len(yv)
    out = np.zeros(K)
    for k in range(K):
        order = _sort_perm(s[k])
        yp = _take(yv, order[:N])
        if len(yp) < N:
            yp = np.concatenate([yp, np.full(N - len(yp), math.nan)])
        P = power_spectrum(_centred(yp))
        end = len(P) - 1
        V = _seqsum(P[1:end]) if end > 1 else 0.0
        V = 2 * V + _get(P, end)
        Vi = _seqsum([_get(P, j) for j in _upto(harmonics)])
        out[k] = _div(2 * Vi, V)
    return out


# ---------------------------------------------------------------------------
# A two-level fractional factorial of resolution IV (Saltelli 2008, eq. 2.31).
# ---------------------------------------------------------------------------


def hadamard(k: int) -> np.ndarray:
    """A Sylvester-Hadamard matrix of order ``k``, a power of two, as a k x k ``int8`` array.

    (Any other order fails in the application too, with a TypeError.)
    """
    if isinstance(k, float) and k.is_integer():
        k = int(k)
    if not isinstance(k, (int, np.integer)) or k < 2 or k & (k - 1):
        raise TypeError(f'A Hadamard matrix of order {k!r} is not a power of two from 2 up')
    h = np.ones((k, k), dtype=np.int8)
    h[1, 1] = -1
    bot = 2
    right = 2
    while bot < k:
        blk = h[:bot, :right].copy()
        h[:bot, right:2 * right] = blk
        h[bot:2 * bot, :right] = blk
        h[bot:2 * bot, right:2 * right] = -blk
        bot *= 2
        right *= 2
    return h


def ff_design(K: int, *, low: float = 0.05, high: float = 0.95) -> Dict[str, Any]:
    """The fractional factorial: the columns of a Hadamard matrix and of its negative, each input low or high.

    ``2^ceil(log2 K) * 2`` runs (4 for up to two inputs); ``low`` and ``high``
    are the probabilities the two levels are at. ``signs`` is rows x k2, +1 or -1.
    """
    k2 = 2
    while k2 < K:
        k2 *= 2
    H = hadamard(k2)
    rows = 2 * k2
    signs = np.vstack([H, -H]).astype(np.int8)
    u = np.where(signs[:, :K].T > 0, float(high), float(low)) if K else np.zeros((0, rows))
    return {'method': 'ff', 'K': K, 'rows': rows, 'signs': signs, 'low': low, 'high': high, 'u': u, 'runs': rows}


def ff_indices(y: Sequence[float], spec: Mapping[str, Any]) -> Dict[str, np.ndarray]:
    """The main effect of each input: its contrast with the output over the factorial. ``{'main', 'squared'}``."""
    K = spec['K']
    rows = spec['rows']
    signs = np.asarray(spec['signs'], dtype=np.float64)
    yv = _segment(y, 0, rows)
    main = np.zeros(K)
    for c in range(K):
        main[c] = _seqsum(yv * signs[:rows, c]) / rows
    return {'main': main, 'squared': main * main}


# ---------------------------------------------------------------------------
# DGSM: Sobol and Kucherenko's derivative-based measures.
# ---------------------------------------------------------------------------


def _columns_of(cols: Sequence[Sequence[float]], K: int, N: int) -> np.ndarray:
    out = np.full((K, N), math.nan)
    for k in range(min(K, len(cols))):
        c = _f64(cols[k])
        t = min(N, len(c))
        out[k, :t] = c[:t]
    return out


def dgsm_design(K: int, base: Sequence[Sequence[float]], *, step: float = 1e-3,
                crossed: bool = False) -> Dict[str, Any]:
    """The DGSM design: each base point, then one step along each input (and each pair with ``crossed``).

    ``base`` holds one column of ``N`` probabilities per input; the step is in
    probability, forward except where that would leave (0, 1). ``K + 1`` runs a
    point, ``K (K - 1) / 2`` more with ``crossed``. ``h[i * K + k]`` is the step
    taken.
    """
    N = len(base[0]) if len(base) else 0
    per = 1 + K + ((K * (K - 1)) // 2 if crossed else 0)
    b = _columns_of(base, K, N)
    with np.errstate(invalid='ignore'):
        h = np.where(b.T + step < 1, step, -step).ravel() if K else np.zeros(0)
    u = np.repeat(b, per, axis=1) if N else np.zeros((K, 0))
    at = np.arange(N) * per
    for k in range(K):
        u[k, at + 1 + k] += h[k::K]
    if crossed:
        p = 1 + K
        for a in range(K):
            for c in range(a + 1, K):
                u[a, at + p] += h[a::K]
                u[c, at + p] += h[c::K]
                p += 1
    return {'method': 'dgsm', 'K': K, 'N': N, 'per': per, 'step': step, 'crossed': crossed, 'h': h,
            'base': b, 'u': u, 'runs': N * per}


def dgsm_derivatives(y: Sequence[float], spec: Mapping[str, Any]) -> Dict[str, Any]:
    """The derivatives a DGSM design measured.

    ``g[i * K + k]``, the first derivative at point i along input k; with
    ``crossed`` the mixed second ones, ``H[(i * K + a) * K + b]``; and ``y0``,
    the outputs at the points. Returns ``{'g', 'H', 'y0'}``.
    """
    K = spec['K']
    N = spec['N']
    per = spec['per']
    crossed = spec.get('crossed')
    h = _f64(spec['h'])
    yv = _segment(y, 0, max(len(y), N * per))
    at = np.arange(N) * per
    y0 = yv[at] if N else np.zeros(0)
    hh = h[:N * K].reshape(N, K) if N and K else np.zeros((N, K))
    with np.errstate(all='ignore'):
        if K and N:
            yk = yv[at[:, None] + 1 + np.arange(K)[None, :]]
            g = ((yk - y0[:, None]) / hh).ravel()
        else:
            g = np.zeros(N * K)
        H = None
        if _js_truthy(crossed):
            H = np.zeros(N * K * K)
            p = 1 + K
            for a in range(K):
                for b in range(a + 1, K):
                    d = (yv[at + p] - yv[at + 1 + a] - yv[at + 1 + b] + y0) / (hh[:, a] * hh[:, b])
                    i = np.arange(N)
                    H[(i * K + a) * K + b] = d
                    H[(i * K + b) * K + a] = d
                    p += 1
    return {'g': g, 'H': H, 'y0': y0}


def dgsm_statistics(g: Sequence[float], base: Sequence[Sequence[float]], *, H: Optional[Sequence[float]] = None,
                    y0: Optional[Sequence[float]] = None) -> Dict[str, Any]:
    """GlobalSensitivity.jl's statistics of DGSM's derivatives, and the bound nu gives on the total index.

    ``g[i * K + k]`` taken at ``base`` (one column of probabilities per input).
    Returns ``{'a', 'absa', 'asq', 'sigma', 'tao', 'variance', 'bound',
    'crossed'}``: the mean derivative, the mean of its magnitude, nu (the mean
    of its square), GlobalSensitivity.jl's sigma and tao, the outputs'
    variance (from ``y0``), ``nu / (pi^2 Var y)``, and with ``H`` the mixed
    derivatives' ``{'mean', 'abs', 'sq'}``, K x K flattened.
    """
    K = len(base)
    N = len(base[0]) if K else 0
    b = _columns_of(base, K, N)
    gv = _segment(g, 0, N * K)
    G = gv.reshape(N, K) if N and K else np.zeros((N, K))
    a = np.zeros(K)
    absa = np.zeros(K)
    asq = np.zeros(K)
    sigma = np.zeros(K)
    tao = np.zeros(K)
    for k in range(K):
        d = G[:, k]
        x = b[k]
        a[k] = _div(_seqsum(d), N)
        absa[k] = _div(_seqsum(np.abs(d)), N)
        asq[k] = _div(_seqsum(d * d), N)
        tao[k] = _div(_seqsum((d * d * (1 - 3 * x + x * x)) / 6), N)
        sigma[k] = _div(_seqsum(0.5 * x * (1 - x) * d * d), N)
    vary = _variance(y0) if y0 is not None and len(y0) > 1 else math.nan
    with np.errstate(all='ignore'):
        bound = asq / (math.pi * math.pi * vary)
    crossed = None
    if H is not None:
        hv = _segment(H, 0, N * K * K)
        crossed = {'mean': np.zeros(K * K), 'abs': np.zeros(K * K), 'sq': np.zeros(K * K)}
        i = np.arange(N)
        for p in range(K):
            for q in range(p + 1, K):
                d = hv[(i * K + p) * K + q]
                for key, v in (('mean', _div(_seqsum(d), N)), ('abs', _div(_seqsum(np.abs(d)), N)),
                               ('sq', _div(_seqsum(d * d), N))):
                    crossed[key][p * K + q] = v
                    crossed[key][q * K + p] = v
    return {'a': a, 'absa': absa, 'asq': asq, 'sigma': sigma, 'tao': tao, 'variance': vary, 'bound': bound,
            'crossed': crossed}


def dgsm_indices(y: Sequence[float], design: Mapping[str, Any]) -> Dict[str, Any]:
    """:func:`dgsm_derivatives` and :func:`dgsm_statistics` of a design's outputs."""
    d = dgsm_derivatives(y, design)
    return dgsm_statistics(d['g'], design['base'], H=d['H'], y0=d['y0'])


# ---------------------------------------------------------------------------
# Shapley effects: Song, Nelson and Staum's algorithm.
# ---------------------------------------------------------------------------


def cholesky(A: Sequence[float], n: int) -> Optional[np.ndarray]:
    """The lower Cholesky factor of a symmetric matrix, or None if it is not positive definite.

    ``A`` is row-major, ``n * n`` long (an ``n`` x ``n`` array will do); only
    its lower triangle is read. The factor comes back row-major and flat too.
    A pivot not above 1e-14 counts as not positive definite.
    """
    L = _cholesky_lower(_as_square(A, n), n, 1e-14)
    return None if L is None else L.ravel()


def _jitter_cholesky(A: List[float], n: int) -> List[float]:
    """A Cholesky factor of a matrix that is positive semi-definite but not quite definite."""
    eps = 1e-12
    while eps < 1:
        B = list(A)
        for i in range(n):
            B[i * n + i] += eps
        L = cholesky(B, n)
        if L is not None:
            return L.tolist()
        eps *= 10
    raise ValueError('A conditional covariance could not be factorised.')


class _Copula:
    """The inputs' joint law in probability space: independent, or a Gaussian copula."""

    def __init__(self, K: int, corr: Optional[Sequence[float]], next: Next) -> None:
        self.K = K
        self.corr = None if corr is None else _as_square(corr, K).ravel().tolist()
        self.next = next
        self.cache: Dict[str, Optional[List[float]]] = {}

    def _sub(self, idx: Sequence[int]) -> List[float]:
        c = self.corr
        K = self.K
        return [c[a * K + b] for a in idx for b in idx]

    def _draw_z(self, m: int, L: List[float], mu: Optional[List[float]]) -> List[float]:
        """z ~ N(mu, L L')."""
        e = [_gaussian(self.next) for _ in range(m)]
        z = []
        for a in range(m):
            s = mu[a] if mu is not None else 0.0
            row = a * m
            for b in range(a + 1):
                s += L[row + b] * e[b]
            z.append(s)
        return z

    def subset(self, idx: Sequence[int], n: int) -> List[List[float]]:
        """``n`` draws of the inputs ``idx`` from their joint marginal."""
        nxt = self.next
        if self.corr is None:
            return [[nxt() for _ in idx] for _ in range(n)]
        key = ','.join(str(i) for i in idx)
        L = self.cache.get(key)
        if L is None:
            f = cholesky(self._sub(idx), len(idx))
            L = None if f is None else f.tolist()
            self.cache[key] = L
        if L is None:
            raise ValueError('The correlations between these inputs are not a valid correlation matrix.')
        return [[phi(v) for v in self._draw_z(len(idx), L, None)] for _ in range(n)]

    def given(self, plus: Sequence[int], minus: Sequence[int], u_minus: Sequence[float],
              n: int) -> List[List[float]]:
        """``n`` draws of the inputs ``plus`` given ``minus`` at the probabilities ``u_minus``."""
        nxt = self.next
        if self.corr is None:
            return [[nxt() for _ in plus] for _ in range(n)]
        # GlobalSensitivity.jl's find_cond_mean_var: B - C'D^-1 C, and C'D^-1
        # times the conditioning values as normal scores.
        corr = self.corr
        K = self.K
        p = len(plus)
        q = len(minus)
        z_minus = [normal_quantile(v) for v in u_minus]
        f = cholesky(self._sub(minus), q)
        if f is None:
            raise ValueError('The correlations between these inputs are not a valid correlation matrix.')
        Ld = f.tolist()
        # Solve D X = C for X = D^-1 C, one column per member of `plus`.
        X = [0.0] * (q * p)
        for c in range(p):
            col = [corr[minus[r] * K + plus[c]] for r in range(q)]
            w = [0.0] * q
            for r in range(q):
                s = col[r]
                for l in range(r):  # noqa: E741
                    s -= Ld[r * q + l] * w[l]
                w[r] = s / Ld[r * q + r]
            for r in range(q - 1, -1, -1):
                s = w[r]
                for l in range(r + 1, q):  # noqa: E741
                    s -= Ld[l * q + r] * X[l * p + c]
                X[r * p + c] = s / Ld[r * q + r]
        mu = [0.0] * p
        cov = [0.0] * (p * p)
        for a in range(p):
            s = 0.0
            for r in range(q):
                s += X[r * p + a] * z_minus[r]
            mu[a] = s
            for b in range(p):
                c = corr[plus[a] * K + plus[b]]
                for r in range(q):
                    c -= corr[minus[r] * K + plus[a]] * X[r * p + b]
                cov[a * p + b] = c
        # Symmetrised, and a variance rounding made a hair negative is zero.
        for a in range(p):
            for b in range(a + 1, p):
                v = (cov[a * p + b] + cov[b * p + a]) / 2
                cov[a * p + b] = v
                cov[b * p + a] = v
        f = cholesky(cov, p)
        L = f.tolist() if f is not None else _jitter_cholesky(cov, p)
        return [[phi(v) for v in self._draw_z(p, L, mu)] for _ in range(n)]


def shapley_design(K: int, *, perms: int = -1, n_var: int, n_outer: int, n_inner: int = 3,
                   corr: Optional[Sequence[float]] = None, next: Next) -> Dict[str, Any]:
    """Song, Nelson and Staum's design for Shapley effects.

    ``n_var`` points for the output's variance, then for each order of the
    inputs -- all ``K!`` of them with ``perms=-1``, or ``perms`` random ones --
    and each step along it, ``n_outer`` conditioning points with ``n_inner``
    conditional draws each. With ``corr``, a K x K correlation matrix of the
    normal scores (row-major), the inputs are drawn from a Gaussian copula and
    every conditional draw respects it.
    """
    if perms == -1:
        orders = permutations_of(K)
    else:
        if perms < 0:
            raise ValueError('Invalid array length')
        orders = [random_permutation(K, next) for _ in range(int(perms))]
    law = _Copula(K, corr, next)
    everyone = list(range(K))
    runs = n_var + len(orders) * (K - 1) * n_outer * n_inner
    # With no inputs the application makes no columns at all, whatever the count comes to.
    u = np.zeros((K, runs if K else max(0, runs)))
    at = 0
    for row in law.subset(everyone, n_var):
        if K:
            u[:, at] = row
        at += 1
    for perm in orders:
        for j in range(1, K):
            plus = perm[:j]
            minus = perm[j:]
            outer = law.subset(minus, n_outer)
            for fixed in outer:
                inner = law.given(plus, minus, fixed, n_inner)
                for drawn in inner:
                    u[plus, at] = drawn
                    u[minus, at] = fixed
                    at += 1
    return {'method': 'shapley', 'K': K, 'orders': orders, 'nVar': n_var, 'nOuter': n_outer, 'nInner': n_inner,
            'correlated': corr is not None, 'u': u, 'runs': runs}


def shapley_indices(y: Sequence[float], spec: Mapping[str, Any]) -> Dict[str, np.ndarray]:
    """Shapley effects from the outputs over a Shapley design.

    ``spec`` holds ``K``, ``orders``, ``nVar``, ``nOuter`` and ``nInner``.
    Returns ``{'effects', 'stdErr', 'lower', 'upper'}``, the bounds at 1.96
    standard errors.
    """
    K = spec['K']
    orders = spec['orders']
    n_var = spec['nVar']
    n_outer = spec['nOuter']
    n_inner = spec['nInner']
    yv = _f64(y)
    Sh = np.zeros(K)
    Sh2 = np.zeros(K)
    vary = _variance(yv, 0, n_var)
    at = n_var
    for perm in orders:
        prev = 0.0
        for j in range(K):
            if j == K - 1:
                Sh[perm[j]] += vary - prev
                prev = vary
                continue
            c_var = np.array([_variance(yv, at + l * n_inner, at + (l + 1) * n_inner) for l in range(n_outer)])
            at += n_outer * n_inner
            C = _mean(c_var)
            d = C - prev
            dev = c_var - prev
            d2 = _seqsum(dev * dev)
            Sh2[perm[j]] += _div(d2, n_outer) - d * d
            Sh[perm[j]] += d
            prev = C
    m = len(orders)
    with np.errstate(all='ignore'):
        effects = Sh / m / vary
        se = np.sqrt(Sh2 / m / (vary * vary) / n_outer)
    return {'effects': effects, 'stdErr': se, 'lower': effects - 1.96 * se, 'upper': effects + 1.96 * se}


# ---------------------------------------------------------------------------
# From a sample: EASI.
# ---------------------------------------------------------------------------


def easi(x: Sequence[float], y: Sequence[float], *, harmonics: int = 4, dct: bool = False) -> Dict[str, float]:
    """Plischke's EASI: a first-order index read off any sample.

    The runs are sorted by the input and folded into a triangle so the output
    is periodic in it, and the index is the power in the first ``harmonics``
    frequencies -- or, with ``dct``, the first cosine coefficients. ``s1c`` is
    Tissot and Prieur's correction for the bias a random design leaves.
    Returns ``{'s1', 's1c'}``.
    """
    H = harmonics
    yv = _f64(y)
    n = len(yv)
    order = _sort_perm(x)
    with np.errstate(all='ignore'):
        if dct:
            yp = _take(yv, order[:n])
            if len(yp) < n:
                yp = np.concatenate([yp, np.full(n - len(yp), math.nan)])
            c = _centred(yp)
            den = _seqsum(c * c)
            X = dct2(c, _js_min(H, n - 1) + 1)
            num = _seqsum(X[1:] * X[1:])
            s = _div(num, den)
        else:
            full = np.concatenate([order, np.full(max(0, n - len(order)), -1, dtype=order.dtype)])[:n]
            odd_top = 2 * (n // 2) - 1
            picks = np.concatenate([full[0::2], full[1:odd_top + 1:2][::-1]]) if n else full
            yp = _take(yv, picks)
            P = power_spectrum(_centred(yp))
            top = len(P) - 2
            den = _seqsum(P[1:top + 1]) if top >= 1 else 0.0
            upto = min(top, _js_floor(H)) if H == H else 0
            num = _seqsum(P[1:upto + 1]) if upto >= 1 else 0.0
            s = _div(num, den)
    lam = _div(2 * H, n)
    return {'s1': s, 's1c': s - _div(lam, 1 - lam) * (1 - s)}


# ---------------------------------------------------------------------------
# From a sample: Borgonovo's moment-independent delta, and the kernel
# density estimate behind it (KernelDensity.jl's, with Interpolations.jl's
# quadratic B-spline to read it anywhere).
# ---------------------------------------------------------------------------


def kde_bandwidth(data: Sequence[float], fallback: Optional[float] = None) -> float:
    """Silverman's rule of thumb, as KernelDensity.jl's ``default_bandwidth``.

    Data with no spread at all have nothing to take a width from; KernelDensity.jl
    falls back to a width of one in the data's own units, and ``fallback``,
    where given, is used instead.
    """
    d = _f64(data)
    n = len(d)
    if n <= 1:
        return 0.9 if fallback is None else fallback
    sd = _std(d)
    iqr = (quantile7(d, 0.75) - quantile7(d, 0.25)) / 1.34
    width = _js_min(sd, iqr)
    if width == 0:
        if sd == 0 and fallback is not None:
            return fallback
        width = 1 if sd == 0 else sd
    return 0.9 * width * n ** -0.2


_SPLINE: Dict[int, Tuple[List[float], List[float]]] = {}


def _spline_coefficients(y: np.ndarray) -> np.ndarray:
    """The coefficients of Interpolations.jl's ``BSpline(Quadratic(Line(OnGrid())))`` through ``y``.

    Padded one at each end, the second derivative zero at both ends; the
    tridiagonal system for the rest solved by Thomas's algorithm, step for
    step as the application solves it.
    """
    n = len(y)
    yl = y.tolist()
    c = [0.0] * (n + 2)
    c[1] = yl[0]
    c[n] = yl[n - 1]
    m = n - 2
    if m > 0:
        pre = _SPLINE.get(m)
        if pre is None:
            # The pivots depend on the length alone.
            cps = [0.0] * m
            dens = [0.0] * m
            for i in range(m):
                den = 0.75 - (0.125 * cps[i - 1] if i > 0 else 0)
                dens[i] = den
                cps[i] = 0.125 / den
            pre = (cps, dens)
            if len(_SPLINE) > 16:
                _SPLINE.clear()
            _SPLINE[m] = pre
        cps, dens = pre
        dp = [0.0] * m
        prev = 0.0
        for i in range(m):
            r = yl[i + 1]
            if i == 0:
                r -= c[1] / 8
            if i == m - 1:
                r -= c[n] / 8
            prev = (r - (0.125 * prev if i > 0 else 0)) / dens[i]
            dp[i] = prev
        c[m + 1] = dp[m - 1]
        nxt = c[m + 1]
        for i in range(m - 2, -1, -1):
            nxt = dp[i] - cps[i] * nxt
            c[i + 2] = nxt
    c[0] = 2 * c[1] - c[2]
    c[n + 1] = 2 * c[n] - c[n - 1]
    return np.array(c, dtype=np.float64)


def kde(data: Sequence[float], *, npoints: int = 2048, fallback: Optional[float] = None) -> Dict[str, Any]:
    """A Gaussian kernel density estimate on ``npoints`` points spanning the data and four bandwidths either side.

    KernelDensity.jl's: Silverman's bandwidth, linear binning, the Gaussian
    applied in Fourier space. Returns ``{'lo', 'hi', 'step', 'density',
    'coef'}``, ``coef`` the spline :func:`kde_pdf` reads it through.
    """
    d = _f64(data)
    bw = kde_bandwidth(d, fallback)
    if not bw > 0:
        raise ValueError('Bandwidth must be positive')
    fin = d[~np.isnan(d)]
    mn = float(fin.min()) if len(fin) else math.inf
    mx = float(fin.max()) if len(fin) else -math.inf
    lo = mn - 4 * bw
    hi = mx + 4 * bw
    s = _div(hi - lo, npoints - 1)
    grid = np.zeros(npoints)
    with np.errstate(all='ignore'):
        ainc = _div(1, s * s)
        w = _div(1, len(d))
        x = d[~np.isnan(d)]

        def mid(k: np.ndarray) -> np.ndarray:
            return np.where(k == npoints - 1, hi, lo + k * s)

        # Jones and Lotwick's linear binning, each point to the two grid points around it.
        k = _js_round_array((x - lo) / s)
        k = np.where(k < 0, 0.0, k)
        k = np.where(k > npoints - 1, float(npoints - 1), k)
        while True:
            move = (k > 0) & (mid(k - 1) >= x)
            if not move.any():
                break
            k = np.where(move, k - 1, k)
        while True:
            move = (k < npoints) & (mid(k) < x)
            if not move.any():
                break
            k = np.where(move, k + 1, k)
        j = k - 1
        ok = (j >= 0) & (j <= npoints - 2)
        kk = k[ok]
        jj = j[ok]
        xx = x[ok]
        left = (mid(kk) - xx) * ainc * w
        right = (xx - mid(jj)) * ainc * w
        # Added in the application's order: each point's two contributions, point by point.
        where = np.empty(2 * len(xx), dtype=np.intp)
        where[0::2] = jj.astype(np.intp)
        where[1::2] = kk.astype(np.intp)
        what = np.empty(2 * len(xx))
        what[0::2] = left
        what[1::2] = right
        np.add.at(grid, where, what)
        # The Gaussian's characteristic function applied to the binned data's.
        ft = rfft(grid)
        c = _div(-2 * math.pi, s * npoints)
        t = np.arange(len(ft['re']), dtype=np.float64) * c
        f = np.exp(-((bw * bw) / 2) * t * t)
        ft['re'] = ft['re'] * f
        ft['im'] = ft['im'] * f
        density = irfft(ft, npoints)
    density[density < 0] = 0
    return {'lo': lo, 'hi': hi, 'step': s, 'density': density, 'coef': _spline_coefficients(density)}


def kde_pdf(k: Mapping[str, Any], xs: Sequence[float]) -> np.ndarray:
    """The estimate at each of ``xs``, and zero outside its grid, as KernelDensity.jl's ``pdf(kde, xs)``."""
    density = k['density']
    coef = _f64(k['coef'])
    n = len(density)
    x = _f64(xs)
    out = np.zeros(len(x))
    with np.errstate(all='ignore'):
        inside = (x >= k['lo']) & (x <= k['hi'])
        xv = x[inside]
        xi = (xv - k['lo']) / k['step'] + 1
        xm = np.where(xi < n + 0.5, np.floor(xi + 0.5), np.ceil(xi + 0.5) - 1)
        d = xi - xm
        im = xm.astype(np.intp)
        dm = d - 0.5
        dp = d + 0.5
        out[inside] = ((dm * dm) / 2) * coef[im - 1] + (0.75 - d * d) * coef[im] + ((dp * dp) / 2) * coef[im + 1]
    return out


def _trapz(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2:
        return 0.0
    return _seqsum((x[1:] - x[:-1]) * (y[:-1] + y[1:])) / 2


def delta_classes(n: int) -> int:
    """The number of classes GlobalSensitivity.jl cuts ``n`` realisations into for delta."""
    e = 2 / (7 + math.tanh((1500 - n) / 500))
    return _js_round(_js_min(math.ceil(n ** e), 48))


def _delta_once(x: np.ndarray, y: np.ndarray, ygrid: np.ndarray, cut: List[float]) -> float:
    n = len(y)
    if n <= 1 or bool(np.all(y[1:] == y[0])):
        return 0.0
    fallback = kde_bandwidth(y)
    fy = kde_pdf(kde(y), ygrid)
    r = compete_rank(x)
    if len(r) < n:
        r = np.concatenate([r, np.full(n - len(r), math.nan)])
    r = r[:n]
    total = 0.0
    with np.errstate(invalid='ignore'):
        for j in range(len(cut) - 1):
            members = y[(r > cut[j]) & (r <= cut[j + 1])]
            if not len(members):
                continue
            fyc = kde_pdf(kde(members, fallback=fallback), ygrid)
            total += len(members) * _trapz(ygrid, np.abs(fy - fyc))
    return total / (2 * n)


def delta_moment(x: Sequence[float], y: Sequence[float], *, boots: int = 500, conf: float = 0.95,
                 grid: int = 2048, classes: Optional[int] = None, next: Optional[Next] = None,
                 resamples: Optional[Sequence[Sequence[int]]] = None) -> Dict[str, float]:
    """Borgonovo's moment-independent delta of one input, with a bootstrap bias correction and interval.

    Half the expected area between the output's density and its density given
    the input, from the input cut into classes (``classes``, or
    :func:`delta_classes`) and kernel density estimates compared on ``grid``
    points. The adjusted delta subtracts the bias ``boots`` bootstrap resamples
    measure -- drawn from ``next``, or given as ``resamples`` -- and the
    interval is around that. Returns ``{'delta', 'adjusted', 'low', 'high'}``.
    """
    xv = _f64(x)
    yv = _f64(y)
    n = len(yv)
    M = classes if classes is not None else delta_classes(n)
    cut = [_div(j * n, M) for j in range(int(M + 1))]
    fin = yv[~np.isnan(yv)]
    lo = float(fin.min()) if len(fin) else math.inf
    hi = float(fin.max()) if len(fin) else -math.inf
    ygrid = _linspace(lo, hi, grid)
    delta = _delta_once(xv, yv, ygrid, cut)
    B = len(resamples) if resamples is not None else int(boots)
    if not B:
        return {'delta': delta, 'adjusted': delta, 'low': math.nan, 'high': math.nan}
    nxt = next or random.random
    bs = np.zeros(B)
    for b in range(B):
        if resamples is not None:
            # resamples[b][i] for each i < n; past a short row's end, nothing, which reads as NaN.
            r = np.full(n, -1, dtype=np.int64)
            given = np.asarray(resamples[b], dtype=np.int64)[:n]
            r[:len(given)] = given
        else:
            r = np.array([math.floor(nxt() * n) for _ in range(n)], dtype=np.int64)
        bs[b] = _delta_once(_take(xv, r), _take(yv, r), ygrid, cut)
    adjusted = 2 * delta - _mean(bs)
    band = _div(normal_quantile(0.5 + conf / 2) * _std(bs), math.sqrt(B))
    return {'delta': delta, 'adjusted': adjusted, 'low': adjusted - band, 'high': adjusted + band}


# ---------------------------------------------------------------------------
# From a sample: regional sensitivity analysis.
# ---------------------------------------------------------------------------


def rsa_score(x: Sequence[float], flag: Sequence[float]) -> float:
    """The Kolmogorov-Smirnov distance between the input's values where ``flag`` is 1 and where it is 0.

    NaN when either group is empty.
    """
    order = _sort_perm(x)
    f = _f64(flag)
    if not len(order):
        return 0.0
    fl = _take(f, order)
    acc_c = np.cumsum(fl)
    rej_c = np.cumsum(1 - fl)
    acc = acc_c[-1]
    rej = rej_c[-1]
    with np.errstate(all='ignore'):
        d = np.abs(acc_c / acc - rej_c / rej)
    if np.isnan(d).any():
        return math.nan
    return float(max(0.0, float(d.max())))


def rsa(xs: Sequence[Sequence[float]], y: Sequence[float], *, threshold: Optional[float] = None,
        dummies: Sequence[Sequence[float]] = ()) -> Dict[str, Any]:
    """Regional sensitivity analysis: split the runs at ``threshold`` (the output's mean by default).

    Each input's score is :func:`rsa_score` between the runs above the
    threshold ("behavioural") and the rest; ``dummies``, draws the model never
    saw, say how large a distance chance alone gives. Returns ``{'threshold',
    'behavioural', 'scores', 'dummyMean', 'dummySd'}``.
    """
    yv = _f64(y)
    t = _mean(yv) if threshold is None else threshold
    flag = (yv > t).astype(np.float64)
    scores = np.array([rsa_score(x, flag) for x in xs], dtype=np.float64)
    d = [rsa_score(x, flag) for x in dummies]
    return {
        'threshold': t,
        'behavioural': int(flag.sum()),
        'scores': scores,
        'dummyMean': _mean(d) if len(d) else math.nan,
        'dummySd': _std(d) if len(d) > 1 else math.nan,
    }


# ---------------------------------------------------------------------------
# From a sample: mutual information, with ComplexityMeasures.jl's binning.
# ---------------------------------------------------------------------------


def _next_up(x: float, n: int = 1) -> float:
    """The next representable number above ``x``, ``n`` times, by the bits (so infinity steps to NaN)."""
    v = float(x)
    for _ in range(n):
        if v == 0:
            v = 5e-324
            continue
        bits = struct.unpack('<Q', struct.pack('<d', v))[0]
        bits = (bits + 1 if v > 0 else bits - 1) & 0xFFFFFFFFFFFFFFFF
        v = struct.unpack('<d', struct.pack('<Q', bits))[0]
    return v


def _bins(x: np.ndarray, bins: int) -> np.ndarray:
    """Each value's bin, as ``RectangularBinning(bins)`` lays them over the column."""
    fin = x[~np.isnan(x)]
    mn = float(fin.min()) if len(fin) else math.inf
    mx = float(fin.max()) if len(fin) else -math.inf
    top = _next_up(mx, 2)
    with np.errstate(all='ignore'):
        width = _div(top - mn, bins)
        return np.floor((x - mn) / width)


def _entropy_of(keys: np.ndarray) -> float:
    """The entropy in bits of the keys' counts, added in the order each key first appears."""
    n = len(keys)
    if not n:
        return 0.0
    uniq, first, counts = np.unique(keys, return_index=True, return_counts=True)
    del uniq
    counts = counts[np.argsort(first, kind='stable')]
    p = counts / n
    return _seqsum(-(p * np.log2(p)))


def histogram_entropy(x: Sequence[float], bins: int) -> float:
    """The entropy in bits of one column's histogram of ``bins`` equal bins."""
    return _entropy_of(_bins(_f64(x), bins))


def joint_entropy(x: Sequence[float], y: Sequence[float], bins: int) -> float:
    """The entropy in bits of two columns' joint histogram."""
    xv = _f64(x)
    # Each column's bins are laid over the whole column, and then paired up.
    by = _segment(_bins(_f64(y), bins), 0, len(xv))
    with np.errstate(all='ignore'):
        return _entropy_of(_bins(xv, bins) * (bins + 2) + by)


def mutual_information(x: Sequence[float], y: Sequence[float], *, boots: int = 1000, conf: float = 0.95,
                       next: Optional[Next] = None,
                       shuffles: Optional[Sequence[Sequence[int]]] = None) -> Dict[str, float]:
    """How many bits the input tells about the output, and how much of that is more than chance.

    From histograms with ``round(sqrt(n))`` bins a side. The chance level is the
    ``conf`` quantile of the same measure over ``boots`` shuffles of the output
    -- drawn from ``next``, each shuffling the last, or given as ``shuffles``.
    Returns ``{'mi', 'bound', 's'}``, ``s`` what is left above the bound.
    """
    xv = _f64(x)
    yv = _f64(y)
    n = len(yv)
    bins = _js_round(math.sqrt(n))
    hx = histogram_entropy(xv, bins)
    hy = histogram_entropy(yv, bins)
    mi = hx + hy - joint_entropy(xv, yv, bins)
    B = len(shuffles) if shuffles is not None else int(boots)
    nulls = np.zeros(B)
    perm = yv.tolist()
    nxt = next or random.random
    for b in range(B):
        if shuffles is not None:
            arr = _take(yv, np.asarray(shuffles[b], dtype=np.int64)[:n])
        else:
            for i in range(n - 1, 0, -1):
                j = math.floor(nxt() * (i + 1))
                perm[i], perm[j] = perm[j], perm[i]
            arr = np.array(perm, dtype=np.float64)
        nulls[b] = hx + hy - joint_entropy(xv, arr, bins)
    bound = quantile7(nulls, conf) if B else math.nan
    return {'mi': mi, 'bound': bound, 's': float(_js_max(0, mi - bound))}


# ---------------------------------------------------------------------------
# The designed methods as the tool offers them.
# ---------------------------------------------------------------------------

#: Each method's label, blurb and settings: ``[key, label, default, kind, title]`` (and the
#: choices of a ``choice``), where a default that is a function is worked out from the number
#: of inputs. The keys are the application's, as a model saves them.
GSA_METHODS: Dict[str, Dict[str, Any]] = {
    'morris': {
        'label': 'Morris elementary effects',
        'short': 'Morris',
        'blurb': 'Random walks through the inputs, one input moved one level at a time. μ* says how '
                 'much an input matters, μ which way, σ how much its effect depends on where it is '
                 'taken — a curve or an interaction. Cheap: a screening method, for many inputs.',
        'options': [
            ['design', 'Design', 'walks', 'choice', 'How the runs are laid out: GlobalSensitivity.jl’s random walks, '
             'or Morris’s own trajectories as SALib samples them, each moving every input once by half its range.',
             [['walks', 'Random walks'], ['trajectories', 'Trajectories (SALib)']]],
            ['trajectories', 'Trajectories', 10, 'int', 'How many walks, or trajectories.'],
            ['points', 'Walk length', 10, 'int', 'Walks only: runs in each; each step after the first is one '
             'elementary effect. A trajectory is K + 1 runs.'],
            ['levels', 'Levels', 100, 'int', 'How many levels each input’s probability is cut into. A walk moves '
             'one level a step; a trajectory, half of them.'],
            ['candidates', 'Candidates', 0, 'int', 'Trajectories only: draw this many and keep the most spread out '
             '— Campolongo’s optimal trajectories, by Ruano’s local search. 0 keeps every one drawn.'],
            ['relative', 'Relative', False, 'switch', 'Each effect divided by the output, so it is a proportion '
             'rather than in the output’s units.'],
            ['resamples', 'Bootstrap', 100, 'int', 'Resamples for SALib’s interval on μ*; 0 for none.'],
        ],
    },
    'sobol': {
        'label': 'Sobol indices',
        'short': 'Sobol',
        'blurb': 'The variance decomposition: S₁ is the share of the spread an input explains alone, '
                 'Sₜ the share it has a hand in, interactions included. Saltelli’s design, two samples '
                 'and one more per input. The reference method, and the most expensive.',
        'options': [
            ['samples', 'Samples', 1000, 'int', 'Points in each of the two base samples, A and B.'],
            ['second', 'Pairs, S₂', False, 'switch', 'Every pair’s interaction too, at the cost of K more samples.'],
            ['blocks', 'Blocks', 1, 'int', 'Repeat the design this many times and give an interval from the '
             'spread between them.'],
            ['estimator', 'Sₜ estimator', 'jansen1999', 'choice', 'How Sₜ is estimated from the samples.',
             [['jansen1999', 'Jansen 1999'], ['sobol2007', 'Sobol 2007'], ['homma1996', 'Homma and Saltelli 1996'],
              ['janon2014', 'Janon 2014']]],
            ['resamples', 'Bootstrap', 100, 'int', 'With one block: resamples for SALib’s bootstrap interval on '
             'each index, from the one design. 0 for none.'],
        ],
    },
    'efast': {
        'label': 'eFAST',
        'short': 'eFAST',
        'blurb': 'The extended Fourier amplitude test: one curve per input, along which that input '
                 'oscillates fast and the rest slowly, and the variances read off the spectrum. S₁ and '
                 'Sₜ for about the price of Sobol’s S₁.',
        'options': [
            ['samples', 'Curve length', 1000, 'int', 'Runs along each input’s curve; K curves in all.'],
            ['harmonics', 'Harmonics', 4, 'int', 'How many harmonics of the input’s frequency count as its own.'],
        ],
    },
    'rbdfast': {
        'label': 'RBD-FAST',
        'short': 'RBD-FAST',
        'blurb': 'Random balance design: one curve for every input at once, each in its own random '
                 'order. First-order indices only, but for a fixed number of runs whatever the number '
                 'of inputs.',
        'options': [
            ['samples', 'Samples', 1000, 'int', 'Runs in all.'],
            ['harmonics', 'Harmonics', 6, 'int', 'How many harmonics count as the input’s.'],
        ],
    },
    'ff': {
        'label': 'Fractional factorial',
        'short': 'Fractional factorial',
        'blurb': 'Every input at a low or a high value in a two-level design of resolution IV. Main '
                 'effects, clear of two-way interactions, from a handful of runs.',
        'options': [
            ['low', 'Low level', 0.05, 'number', 'The probability each input’s low level is at.'],
            ['high', 'High level', 0.95, 'number', 'The probability each input’s high level is at.'],
            ['pairs', 'Pairs', False, 'switch', 'Every pair’s two-way interaction effect too, from the same runs '
             '(SALib’s). In this design each is aliased with others: what is measured for a pair is its sum with '
             'the pairs aliased with it.'],
        ],
    },
    'dgsm': {
        'label': 'Derivative-based measures (DGSM)',
        'short': 'DGSM',
        'blurb': 'The derivative of the output with respect to each input, at sampled points. ν, the '
                 'mean squared derivative, bounds the total Sobol index from above. K + 1 runs a point.',
        'options': [
            ['samples', 'Points', 100, 'int', 'Where the derivatives are taken.'],
            ['step', 'Step', 0.001, 'number', 'The finite-difference step, in probability.'],
            ['crossed', 'Cross terms', False, 'switch', 'Every pair’s second derivative too, K(K − 1)/2 more runs '
             'a point.'],
            ['resamples', 'Bootstrap', 100, 'int', 'Resamples for SALib’s interval on ν; 0 for none.'],
        ],
    },
    'radial': {
        'label': 'Radial one-at-a-time',
        'short': 'Radial',
        'blurb': 'Campolongo, Saltelli and Cariboni’s design: base points spread over the whole space, each '
                 'moved one input at a time towards a second point. Elementary effects to screen with, as '
                 'Morris’s, and Jansen’s total index from the same runs — N(K + 1) of them.',
        'options': [
            ['samples', 'Base points', 100, 'int', 'How many; each costs K + 1 runs.'],
            ['resamples', 'Bootstrap', 100, 'int', 'Resamples for the intervals on μ* and Sₜ; 0 for none.'],
        ],
    },
    'shapley': {
        'label': 'Shapley effects',
        'short': 'Shapley',
        'blurb': 'Each input’s fair share of the variance, over the orders the inputs could be learnt '
                 'in. They add up to one when inputs are correlated, which is what they are for: the '
                 'model’s correlations are honoured through a Gaussian copula.',
        'options': [
            # Song, Nelson and Staum's advice: over random orders, one outer sample and
            # three inner ones; over all of them (K!, affordable to four), more outer samples.
            ['perms', 'Orders', lambda K: 0 if K <= 4 else 100, 'int', 'Random orders of the inputs; 0 for all K! '
             'of them.'],
            ['nVar', 'Variance runs', 1000, 'int', 'Runs for the output’s total variance.'],
            ['nOuter', 'Outer samples', lambda K: 10 if K <= 4 else 1, 'int', 'Conditioning points per step of an '
             'order.'],
            ['nInner', 'Inner samples', 3, 'int', 'Conditional draws per conditioning point.'],
        ],
    },
}

#: The methods' ids, in the order the application lists them.
GSA_METHOD_IDS = list(GSA_METHODS)


def gsa_options(method: str, K: int, given: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """A method's settings with every one filled in: what ``given`` says where it can be read, the default elsewhere.

    A switch is read for its truth, a choice must be one of its values, and a
    number is read as JavaScript's ``Number()`` reads it (an ``int`` rounded);
    anything else takes the default. An unknown method has no settings.
    """
    spec = GSA_METHODS.get(method) if isinstance(method, str) else None
    out: Dict[str, Any] = {}
    for opt in (spec or {}).get('options', []):
        key, default, kind = opt[0], opt[2], opt[3]
        choices = opt[5] if len(opt) > 5 else []
        want = given.get(key) if isinstance(given, Mapping) else None
        d = default(K) if callable(default) else default
        if kind == 'switch':
            out[key] = d if want is None else _js_truthy(want)
        elif kind == 'choice':
            out[key] = want if isinstance(want, str) and any(v == want for v, _ in choices) else d
        else:
            v = math.nan if want is None or (isinstance(want, str) and want == '') else _js_number(want)
            out[key] = (_js_round(v) if kind == 'int' else v) if math.isfinite(v) else d
    return out


def _factorial(n: int) -> float:
    """``n!`` in floating point, multiplied as the application's recursion multiplies it."""
    f = 1.0
    for i in range(2, int(n) + 1):
        f = i * f
    return f


def _whole(v: float) -> Any:
    """An integral number as an int, anything else as it is."""
    if isinstance(v, float) and math.isfinite(v) and v == math.floor(v):
        return int(v)
    return v


def gsa_runs(method: str, K: int, options: Optional[Mapping[str, Any]] = None) -> Any:
    """How many runs a design of ``method`` over ``K`` inputs is, before any is made (0 for an unknown method)."""
    o = gsa_options(method, K, options or {})
    if method == 'morris':
        return o['trajectories'] * (K + 1 if o['design'] == 'trajectories' else o['points'])
    if method == 'radial':
        return o['samples'] * (K + 1)
    if method == 'sobol':
        return sobol_runs(K, o['samples'], second=o['second'], blocks=o['blocks'])
    if method == 'efast':
        return K * efast_samples(o['samples'], o['harmonics'])
    if method == 'rbdfast':
        return o['samples']
    if method == 'ff':
        k2 = 2
        while k2 < K:
            k2 *= 2
        return 2 * k2
    if method == 'dgsm':
        return o['samples'] * (1 + K + ((K * (K - 1)) // 2 if o['crossed'] else 0))
    if method == 'shapley':
        orders = o['perms'] if o['perms'] > 0 else _factorial(K)
        return _whole(o['nVar'] + orders * (K - 1) * o['nOuter'] * o['nInner'])
    return 0


def gsa_refusal(method: str, K: int, options: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """Why a design cannot be made as asked, in a sentence, or None."""
    o = gsa_options(method, K, options or {})
    if not isinstance(method, str) or method not in GSA_METHODS:
        return f'There is no method called {_js_string(method)}.'
    if K < 1:
        return 'Nothing is sampled, so there is nothing to vary.'

    def positive(v: Any) -> bool:
        return _is_js_integer(v) and v >= 1

    if method == 'morris':
        if not positive(o['trajectories']) or not o['points'] >= 2 or not o['levels'] >= 2:
            return 'Morris needs at least one trajectory of two points, over at least two levels.'
        if o['design'] == 'trajectories' and 0 < o['candidates'] < o['trajectories']:
            return 'Fewer candidates than trajectories to keep; 0 keeps every one drawn.'
    elif method == 'radial':
        if not o['samples'] >= 2:
            return 'The radial design needs at least two base points.'
    elif method == 'sobol':
        if not o['samples'] >= 2 or not positive(o['blocks']):
            return 'Sobol needs at least two samples and one block.'
        if o['blocks'] > 1 and o['blocks'] > o['samples']:
            return 'More blocks than samples.'
    elif method in ('efast', 'rbdfast'):
        if not o['samples'] >= 8 or not positive(o['harmonics']):
            return 'This needs at least a few samples and one harmonic.'
        if method == 'rbdfast' and 2 * o['harmonics'] >= o['samples'] / 2:
            return 'Too many harmonics for so few samples.'
    elif method == 'ff':
        if not (o['low'] > 0 and o['high'] < 1 and o['low'] < o['high']):
            return 'The two levels must be probabilities, the low one below the high.'
    elif method == 'dgsm':
        if not o['samples'] >= 2:
            return 'DGSM needs at least two points.'
        if not (o['step'] > 0 and o['step'] < 0.5):
            return 'The step must be a small probability.'
    elif method == 'shapley':
        if o['perms'] <= 0 and K > 8:
            k = _js_string(K)
            return f'All {k}! orders of {k} inputs is too many; give a number of random orders.'
        if not o['nVar'] >= 2 or not positive(o['nOuter']) or not o['nInner'] >= 2:
            return 'Shapley needs at least two variance samples, one outer and two inner samples.'
    return None


def _default_streams() -> Tuple[Callable[..., Any], Callable[..., Any]]:
    try:
        from . import sample  # pylint: disable=import-outside-toplevel
        return sample.stream_for, sample.uniforms  # type: ignore[attr-defined]
    except (ImportError, AttributeError) as e:
        raise TypeError('build_design needs stream_for and uniforms, as kompartment.stats.sample has them') from e


def build_design(method: str, keys: Sequence[str], options: Optional[Mapping[str, Any]] = None, *, seed: int = 1,
                 corr: Optional[Sequence[float]] = None, stream_for: Optional[Callable[[int, str], Next]] = None,
                 uniforms: Optional[Callable[..., Sequence[float]]] = None) -> Dict[str, Any]:
    """A method's design, drawn from a run's seed, with its settings (``options``) and ``seed`` recorded.

    ``keys`` names each input, for its streams. Every column a method samples
    freely comes from a stream named after the input it belongs to, Latin
    hypercube, as a probabilistic run draws -- ``uniforms(n, stream_for(seed,
    name), latin=True)`` -- so the same seed gives an input the same numbers
    whichever other inputs are in the model. The walks, the orders and the
    conditional draws have one stream each (``#gsa#morris``,
    ``#gsa#shapley``). ``stream_for`` and ``uniforms`` are
    :mod:`kompartment.stats.sample`'s unless given. ``corr`` reaches Shapley
    only. Raises ValueError with the reason when the design cannot be made.
    """
    if stream_for is None or uniforms is None:
        sf, un = _default_streams()
        stream_for = stream_for or sf
        uniforms = uniforms or un
    K = len(keys)
    o = gsa_options(method, K, options or {})
    refused = gsa_refusal(method, K, o)
    if refused:
        raise ValueError(refused)
    names = [_js_string(k) for k in keys]

    def col(name: str, n: int) -> np.ndarray:
        return _f64(uniforms(n, stream_for(seed, name), latin=True))

    if method == 'morris':
        nxt = stream_for(seed, '#gsa#morris')
        if o['design'] == 'trajectories':
            d = morris_trajectory_design(K, trajectories=o['trajectories'], levels=o['levels'],
                                         candidates=o['candidates'], next=nxt)
        else:
            d = morris_design(K, trajectories=o['trajectories'], points=o['points'], levels=o['levels'], next=nxt)
    elif method == 'radial':
        d = radial_design(K, [col(f'{k}#radial#base', o['samples']) for k in names],
                          [col(f'{k}#radial#step', o['samples']) for k in names])
    elif method == 'sobol':
        d = sobol_design(K, o['samples'], second=o['second'], blocks=o['blocks'],
                         draw=lambda k, which, b: col(f'{names[k]}#sobol#{which}#{b}', o['samples']))
    elif method == 'efast':
        N = efast_samples(o['samples'], o['harmonics'])
        phases = [2 * stream_for(seed, f'{k}#efast')() for k in names]
        d = efast_design(K, N, harmonics=o['harmonics'], phases=phases)
    elif method == 'rbdfast':
        d = rbd_fast_design(K, o['samples'],
                            perms=[random_permutation(o['samples'], stream_for(seed, f'{k}#rbdfast')) for k in names])
    elif method == 'ff':
        d = ff_design(K, low=o['low'], high=o['high'])
    elif method == 'dgsm':
        d = dgsm_design(K, [col(f'{k}#dgsm', o['samples']) for k in names], step=o['step'], crossed=o['crossed'])
    elif method == 'shapley':
        d = shapley_design(K, perms=o['perms'] if o['perms'] > 0 else -1, n_var=o['nVar'], n_outer=o['nOuter'],
                           n_inner=o['nInner'], corr=corr, next=stream_for(seed, '#gsa#shapley'))
    else:
        raise ValueError(f'There is no method called {_js_string(method)}.')
    d['options'] = o
    # What the intervals are drawn from, so that reading the table again gives the same one.
    d['seed'] = seed
    return d


def _gt(v: Any, x: float) -> bool:
    """``v > x`` as JavaScript compares a setting that may be missing."""
    if v is None:
        return False
    return _js_number(v) > x


def _columns_for(design: Mapping[str, Any]) -> Dict[str, Any]:
    """What a table of a method's answer holds: the columns, and which of them the rows are ranked by."""
    o = design.get('options') or {}
    method = design.get('method')
    boot = _gt(o.get('resamples'), 1)
    if method == 'morris':
        return {'rank': 'meanStar', 'columns': [
            ['meanStar', 'μ*', 'value', 'The mean of the elementary effects’ magnitudes: how much this input '
             'matters, whichever way.'],
            *([['meanStarCi', '± μ*', 'value', 'Half-width of the 95 % interval on μ*, SALib’s: this input’s '
                'effects resampled.']] if boot else []),
            ['mean', 'μ', 'value', 'The mean elementary effect: its sign says which way the output moves as the '
             'input rises.'],
            ['sd', 'σ', 'value', 'The spread of the elementary effects: large where the effect depends on where '
             'it is taken — a curve, or an interaction.'],
            ['count', 'n', 'count', 'How many elementary effects this input has.'],
        ]}
    if method == 'radial':
        return {'rank': 'ST', 'columns': [
            ['ST', 'Sₜ', 'index', 'Total index, by Jansen’s estimator: the share of the variance this input has '
             'a hand in.'],
            *([['STci', '± Sₜ', 'value', 'Half-width of the 95 % interval on Sₜ, from the base points '
                'resampled.']] if boot else []),
            ['meanStar', 'μ*', 'value', 'The mean magnitude of the elementary effects, as Morris’s, from points '
             'spread over the whole space.'],
            *([['meanStarCi', '± μ*', 'value', 'Half-width of the 95 % interval on μ*, SALib’s.']] if boot else []),
            ['mean', 'μ', 'value', 'The mean elementary effect: which way the output moves.'],
            ['sd', 'σ', 'value', 'The spread of the elementary effects.'],
        ]}
    if method == 'sobol':
        if _gt(o.get('blocks'), 1):
            extra = [
                ['S1ci', '± S₁', 'value', 'Half-width of the interval on S₁, from the spread between blocks.'],
                ['STci', '± Sₜ', 'value', 'Half-width of the interval on Sₜ.'],
            ]
        elif boot:
            extra = [
                ['S1ci', '± S₁', 'value', 'Half-width of the 95 % interval on S₁, SALib’s: the runs of the one '
                 'design resampled.'],
                ['STci', '± Sₜ', 'value', 'Half-width of the 95 % interval on Sₜ, likewise.'],
            ]
        else:
            extra = []
        return {'rank': 'ST', 'columns': [
            ['S1', 'S₁', 'index', 'First-order index: the share of the variance this input explains alone.'],
            ['ST', 'Sₜ', 'index', 'Total index: the share it has a hand in, interactions included.'],
            *extra,
        ]}
    if method == 'efast':
        return {'rank': 'ST', 'columns': [
            ['S1', 'S₁', 'index', 'First-order index, from the power at this input’s frequency and its '
             'harmonics.'],
            ['ST', 'Sₜ', 'index', 'Total index: one less everything at the other inputs’ frequencies.'],
        ]}
    if method == 'rbdfast':
        return {'rank': 'S1', 'columns': [
            ['S1', 'S₁', 'index', 'First-order index, from the first harmonics along this input’s order.'],
            ['S1c', 'S₁ corrected', 'index', 'The same with Tissot and Prieur’s correction for the bias a random '
             'design leaves in it, which SALib applies.'],
        ]}
    if method == 'ff':
        return {'rank': 'absMain', 'columns': [
            ['main', 'Main effect', 'value', 'Half the difference between the output’s mean with this input high '
             'and with it low.'],
            ['squared', 'Squared', 'value', 'The main effect squared, which is what ranks them.'],
        ]}
    if method == 'dgsm':
        return {'rank': 'asq', 'columns': [
            ['bound', 'Sₜ ≤', 'index', 'Upper bound on the total Sobol index: ν / (π² Var y). An input with a small '
             'bound is safely unimportant.'],
            ['asq', 'ν', 'value', 'The mean squared derivative, per unit probability squared.'],
            *([['asqCi', '± ν', 'value', 'Half-width of the 95 % interval on ν, SALib’s: the points '
                'resampled.']] if boot else []),
            ['asqSd', 'sd', 'value', 'The spread of the squared derivative across the points, SALib’s vi_std.'],
            ['a', 'mean', 'value', 'The mean derivative: which way the output moves.'],
            ['absa', '|mean|', 'value', 'The mean of the derivative’s magnitude.'],
            ['sigma', 'σ', 'value', 'GlobalSensitivity.jl’s sigma: the mean of u(1 − u)/2 times the squared '
             'derivative.'],
            ['tao', 'τ', 'value', 'GlobalSensitivity.jl’s tao: the mean of (1 − 3u + u²)/6 times the squared '
             'derivative.'],
        ]}
    if method == 'shapley':
        return {'rank': 'effect', 'columns': [
            ['effect', 'Shapley', 'index', 'This input’s share of the variance, fairly attributed; they add up to '
             'one.'],
            ['ci', '±', 'value', 'Half-width of the 95 % interval, from the spread between outer samples; none '
             'with one of them.'],
        ]}
    return {'rank': None, 'columns': []}


def _scalar(v: Any) -> Any:
    """A numpy number as a Python one."""
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    return v


def gsa_table(design: Mapping[str, Any], y: Sequence[float], *, next: Optional[Next] = None,
              intervals: bool = True) -> Dict[str, Any]:
    """One method's answer for one output, as rows ranked by the method's main number.

    ``design`` is from :func:`build_design` and ``y`` the output at every
    design point. The intervals SALib adds are bootstraps drawn from ``next``
    -- a stream of the run's seed, so that reading the table again gives the
    same one; ``intervals=False`` leaves them out. Returns ``{'method',
    'columns', 'rank', 'rows', 'pairs', 'failed', 'flat'}``: each row is ``{'k',
    'values'}`` with a value per column key; ``pairs`` (Sobol's S2, the
    factorial's interactions, DGSM's cross terms) or None. Nothing is computed
    when a run failed (``failed`` counts them) or the output never varied.
    """
    K = design['K']
    nxt = next or random.random
    yv = _f64(y)
    failed = int((~np.isfinite(yv)).sum())
    # An output that came out the same in every run has no spread to share out.
    flat = len(yv) <= 1 or bool(np.all(yv[1:] == yv[0]))
    shape = _columns_for(design)
    columns = shape['columns']
    rank = shape['rank']
    rows: List[Dict[str, Any]] = [{'k': k, 'values': {}} for k in range(K)]
    pairs = None
    if not failed and not flat:
        o = design.get('options') or {}
        method = design.get('method')

        def put(key: str, arr: Any) -> None:
            for k in range(K):
                rows[k]['values'][key] = _scalar(arr[k])

        if method == 'morris':
            r = morris_indices(yv, design, relative=_js_truthy(o.get('relative')))
            put('meanStar', r['meanStar'])
            put('mean', r['mean'])
            with np.errstate(invalid='ignore'):
                put('sd', np.sqrt(r['variance']))
            put('count', r['count'])
            if _gt(o.get('resamples'), 1):
                put('meanStarCi', mu_star_interval(r['effects'], resamples=o['resamples'], next=nxt)
                    if intervals else np.full(K, math.nan))
            for k in range(K):
                if not r['count'][k]:
                    for c in ('meanStar', 'mean', 'sd'):
                        rows[k]['values'][c] = math.nan
        elif method == 'radial':
            r = radial_indices(yv, design, resamples=o.get('resamples', 100) if intervals else 0, next=nxt)
            put('ST', r['ST'])
            put('meanStar', r['muStar'])
            put('mean', r['mu'])
            put('sd', r['sigma'])
            if _gt(o.get('resamples'), 1):
                put('STci', r['STci'])
                put('meanStarCi', r['muStarCi'])
        elif method == 'sobol':
            r = sobol_indices(yv, {'K': K, 'n': design['n'], 'second': design['second'], 'blocks': design['blocks'],
                                   'estimator': o.get('estimator')})
            put('S1', r['S1'])
            put('ST', r['ST'])
            # With one design, SALib's bootstrap gives the interval blocks would.
            if r['S1ci'] is None and _gt(o.get('resamples'), 1) and intervals:
                b = sobol_bootstrap(yv, design, resamples=o['resamples'], next=nxt)
                r['S1ci'] = b['S1ci']
                r['STci'] = b['STci']
                r['S2ci'] = b['S2ci']
            if r['S1ci'] is not None:
                put('S1ci', r['S1ci'])
                put('STci', r['STci'])
            if r['S2'] is not None:
                pairs = []
                for a in range(K):
                    for b in range(a + 1, K):
                        pairs.append({'a': a, 'b': b, 'value': float(r['S2'][a * K + b]),
                                      'ci': float(r['S2ci'][a * K + b]) if r['S2ci'] is not None else None})
                pairs.sort(key=lambda p: -abs(p['value']))
        elif method == 'efast':
            r = efast_indices(yv, design)
            put('S1', r['S1'])
            put('ST', r['ST'])
        elif method == 'rbdfast':
            h = o.get('harmonics')
            S1 = rbd_fast_indices(yv, design, harmonics=6 if h is None else h)
            put('S1', S1)
            # A design without settings: the application's unskew then reads harmonics as undefined, NaN.
            put('S1c', [unskew(float(v), h, design['N']) if h is not None else math.nan for v in S1])
        elif method == 'ff':
            r = ff_indices(yv, design)
            put('main', r['main'])
            put('squared', r['squared'])
            put('absMain', np.abs(r['main']))
            if _js_truthy(o.get('pairs')):
                pairs = sorted(ff_interactions(yv, design), key=lambda p: -abs(p['value']))
        elif method == 'dgsm':
            r = dgsm_indices(yv, design)
            for key in ('bound', 'asq', 'a', 'absa', 'sigma', 'tao'):
                put(key, r[key])
            spread = dgsm_spread(dgsm_derivatives(yv, design)['g'], K, design['N'],
                                 resamples=o.get('resamples', 100) if intervals else 0, next=nxt)
            put('asqSd', spread['sd'])
            if _gt(o.get('resamples'), 1):
                put('asqCi', spread['ci'])
            if r['crossed'] is not None:
                pairs = []
                for a in range(K):
                    for b in range(a + 1, K):
                        pairs.append({'a': a, 'b': b, 'value': float(r['crossed']['sq'][a * K + b])})
                pairs.sort(key=lambda p: -p['value'])
        elif method == 'shapley':
            r = shapley_indices(yv, design)
            put('effect', r['effects'])
            # The standard error is read off the spread between outer samples;
            # with one of them it comes out exactly zero, which is not an interval.
            put('ci', [1.96 * float(v) if design['nOuter'] > 1 else math.nan for v in r['stdErr']])

    def by(row: Dict[str, Any]) -> float:
        v = row['values'].get(rank) if rank is not None else None
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else -math.inf

    rows.sort(key=lambda row: -by(row))
    return {'method': design.get('method'), 'columns': columns, 'rank': rank, 'rows': rows, 'pairs': pairs,
            'failed': failed, 'flat': not failed and flat}


def gsa_main(design: Mapping[str, Any], y: Sequence[float]) -> np.ndarray:
    """The number a method ranks by, for each input: what its curve over time is of. Never draws a bootstrap."""
    t = gsa_table(design, y, intervals=False)
    out = np.full(design['K'], math.nan)
    for r in t['rows']:
        v = r['values'].get(t['rank']) if t['rank'] is not None else None
        out[r['k']] = v if isinstance(v, (int, float)) and not isinstance(v, bool) else math.nan
    return out
