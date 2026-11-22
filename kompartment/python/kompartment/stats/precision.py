"""How well the values a calibration found are known.

A port of the application's ``src/domain/precision.js``. A calibration answers
*what would the inputs have to be*; the next question anybody asks of the
answer is *how sure is it*. Least squares answers that from two things it
already has at the answer: how much misfit is left, and how the endpoints move
when each value moves. Near the answer the residuals are close to straight in
the values, ``r(u) ~ r0 + J (u - u*)``, and then::

    cov(u) = s^2 (J^T J)^-1,   s^2 = |r0|^2 / (m - n)

for ``m`` residuals and ``n`` values found. Each value's standard error is the
root of its diagonal entry, its range about 95 % that times Student's t on
``m - n`` degrees of freedom, and the off-diagonal entries, scaled to the
diagonal, are the correlations.

**In the space the search moved in.** A value searched in its logarithm has its
standard error in the logarithm too, which makes its range a factor either way
rather than a plus-or-minus that could run below nought. The residuals are the
search's own (:func:`kompartment.stats.optimise.objective_of`).

**What it cannot say.** With no more targets than values there is no misfit
left to judge by: the correlations still follow from ``J``, the standard errors
do not. A value on a bound is held where it is and given no range; a value no
endpoint moves is said to have *no effect*; two values the endpoints cannot
tell apart are named as that. The whole is a linearisation.

Every exp and log here is the C library's, as :mod:`math` calls it -- the Julia
package's and the C++ engine's ports call the same, so each value is theirs to
the last bit; beside the application's (V8's own exp and log) they agree to
round-off. Where Python would raise -- an exp past the largest double, a
division by nought -- the arithmetic gives what JavaScript's does: Infinity,
or NaN.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from ._normal import normal_quantile

__all__ = ['ln_gamma', 'incomplete_beta', 'student_cdf', 'student_quantile', 'precision_of']

#: Lanczos's coefficients for g = 7, n = 9: ln Gamma to about 1e-15.
_LANCZOS = (0.99999999999980993, 676.5203681218851, -1259.1392167224028,
            771.32342877765313, -176.61502916214059, 12.507343278686905,
            -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7)


def _div(a: float, b: float) -> float:
    """``a / b`` as IEEE divides: a division by nought is +-Infinity or NaN."""
    if b != 0:
        return a / b
    if a == 0 or a != a:
        return math.nan
    return math.copysign(math.inf, a) * math.copysign(1.0, b)


def _exp(x: float) -> float:
    """``exp``, Infinity past the largest double rather than OverflowError."""
    try:
        return math.exp(x)
    except OverflowError:
        return math.inf


def _sqrt(x: float) -> float:
    """``sqrt``, NaN below nought rather than ValueError."""
    return math.sqrt(x) if x >= 0 else math.nan


def ln_gamma(x: float) -> float:
    """The logarithm of the gamma function (``lnGamma``)."""
    if x < 0.5:
        s = abs(math.sin(math.pi * x))
        return (math.inf if s == 0 else math.log(math.pi / s)) - ln_gamma(1 - x)
    z = x - 1
    a = _LANCZOS[0]
    t = z + 7.5
    for i in range(1, 9):
        a += _LANCZOS[i] / (z + i)
    return 0.5 * math.log(2 * math.pi) + (z + 0.5) * math.log(t) - t + math.log(a)


def _beta_fraction(a: float, b: float, x: float) -> float:
    """The continued fraction of the incomplete beta function, by Lentz's method."""
    tiny = 1e-300
    qab = a + b
    qap = a + 1
    qam = a - 1
    c = 1.0
    d = 1 - (qab * x) / qap
    if abs(d) < tiny:
        d = tiny
    d = 1 / d
    h = d
    for m in range(1, 501):
        m2 = 2 * m
        aa = (m * (b - m) * x) / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1 / d
        h *= d * c
        aa = (-(a + m) * (qab + m) * x) / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1 / d
        step = d * c
        h *= step
        if abs(step - 1) < 1e-15:
            break
    return h


def incomplete_beta(x: float, a: float, b: float) -> float:
    """The regularised incomplete beta function, ``I_x(a, b)`` (``incompleteBeta``)."""
    if not (x > 0):
        return 0.0
    if not (x < 1):
        return 1.0
    front = _exp(ln_gamma(a + b) - ln_gamma(a) - ln_gamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return (front * _beta_fraction(a, b, x)) / a
    return 1 - (front * _beta_fraction(b, a, 1 - x)) / b


def student_cdf(t: float, dof: float) -> float:
    """Student's t distribution with ``dof`` degrees of freedom: P(T <= t)."""
    tail = 0.5 * incomplete_beta(dof / (dof + t * t), dof / 2, 0.5)
    return 1 - tail if t >= 0 else tail


def student_quantile(p: float, dof: float) -> float:
    """Student's t quantile: the t below which a share ``p`` lies
    (``studentQuantile``). Closed forms for one and two degrees of freedom, the
    normal's beyond ten million, and between them the distribution function
    inverted by bisection to the last bit. NaN outside (0, 1) or for no
    degrees of freedom."""
    if not (0 < p < 1) or not (dof > 0):
        return math.nan
    if p == 0.5:
        return 0.0
    if dof == 1:
        return math.tan(math.pi * (p - 0.5))
    if dof == 2:
        return (2 * p - 1) / math.sqrt(2 * p * (1 - p))
    if dof > 1e7:
        return normal_quantile(p)
    q = p if p > 0.5 else 1 - p
    lo = 0.0
    hi = 2 * normal_quantile(q)
    if not (hi > 2):   # Math.max(2, ...)
        hi = 2.0
    while student_cdf(hi, dof) < q:
        hi *= 2
    i = 0
    while i < 300 and hi - lo > 1e-15 * hi:
        mid = 0.5 * (lo + hi)
        if student_cdf(mid, dof) < q:
            lo = mid
        else:
            hi = mid
        i += 1
    t = 0.5 * (lo + hi)
    return t if p > 0.5 else -t


def _invert_scaled(S: List[List[float]], tiny: float = 1e-12) -> Optional[List[List[float]]]:
    """Inverts a symmetric positive matrix scaled to unit diagonal, by
    Gauss-Jordan with partial pivoting; None when a pivot falls under ``tiny``,
    which on a matrix of correlations means two columns of J nearly in line."""
    n = len(S)
    M: List[List[float]] = []
    for i, row in enumerate(S):
        r = [0.0] * (2 * n)
        r[:n] = row
        r[n + i] = 1.0
        M.append(r)
    for c in range(n):
        p = c
        for r in range(c + 1, n):
            if abs(M[r][c]) > abs(M[p][c]):
                p = r
        if not (abs(M[p][c]) > tiny):
            return None
        M[c], M[p] = M[p], M[c]
        piv = M[c][c]
        for k in range(2 * n):
            M[c][k] /= piv
        for r in range(n):
            if r == c:
                continue
            f = M[r][c]
            if f == 0:
                continue
            for k in range(2 * n):
                M[r][k] -= f * M[c][k]
    return [row[n:] for row in M]


def precision_of(*, residuals: Sequence[float], columns: Sequence[Optional[Sequence[float]]], keys: Sequence[str],
                 spaces: Sequence[str], values: Sequence[float], pinned: Optional[Sequence[Optional[str]]] = None,
                 failed: Optional[Sequence[Optional[str]]] = None, level: float = 0.95) -> Dict[str, Any]:
    """The precision of a least-squares answer, from its residuals and their
    derivatives there (``precisionOf``).

    ``residuals`` are the search's own at the answer; ``columns[k]`` is dr/du
    for value ``k`` in the space the search moved in, None for one held (on a
    bound) or one the model would not run around; ``spaces`` 'linear' or
    'log'; ``values`` the values found, as the model holds them; ``pinned``
    'lower', 'upper' or None per value; ``failed`` why a value has no column,
    where the model did not run around it; ``level`` the share the ranges hold.

    Returns ``{'targets', 'free', 'dof', 'spread', 't', 'level', 'reason',
    'values', 'correlations'}``: per value ``{'key', 'se', 'low', 'high',
    'factor', 'held'}`` -- ``se`` in the value's own units (for a logarithmic
    one, the value times its standard error in the logarithm), ``factor`` the
    range's either way for a logarithmic one, ``held`` why it has none
    ('lower', 'upper', 'no effect', or the reason it could not be
    differenced). ``reason`` says why there are no ranges: 'nothing free',
    'cannot tell apart' or 'no spare targets'. ``correlations`` is ``{'keys',
    'matrix'}`` over the values left free.
    """
    pinned = list(pinned) if pinned is not None else []
    failed = list(failed) if failed is not None else []
    m = len(residuals)
    n = len(keys)
    held: List[Optional[str]] = []
    for k in range(n):
        h = pinned[k] if k < len(pinned) else None
        if h is None:
            h = failed[k] if k < len(failed) else None
        if h is None:
            h = None if columns[k] is not None else 'held'
        held.append(h)
    # A value no endpoint moves: its column is nothing, so the matrix would be
    # singular for a reason the reader can be told plainly.
    for k in range(n):
        col = columns[k]
        if held[k] or col is None:
            continue
        if not any(col[i] != 0 for i in range(m)):
            held[k] = 'no effect'
    free = [k for k in range(n) if not held[k]]
    ssr = 0.0
    for i in range(m):
        ssr += residuals[i] * residuals[i]
    dof = m - len(free)
    out: Dict[str, Any] = {
        'targets': m,
        'free': len(free),
        'dof': dof,
        'spread': _sqrt(ssr / dof) if dof > 0 else None,
        't': student_quantile(0.5 + level / 2, dof) if dof > 0 else None,
        'level': level,
        'reason': None,
        'values': [{'key': key, 'se': None, 'low': None, 'high': None, 'factor': None, 'held': held[k]}
                   for k, key in enumerate(keys)],
        'correlations': None,
    }
    if not free:
        out['reason'] = 'nothing free'
        return out

    # J^T J over the values left free, scaled to unit diagonal so that the
    # pivots say how nearly in line two columns are, whatever their units.
    A: List[List[float]] = []
    for a in free:
        row = []
        for b in free:
            s = 0.0
            for i in range(m):
                s += columns[a][i] * columns[b][i]   # type: ignore[index]
            row.append(s)
        A.append(row)
    d = [_sqrt(A[i][i]) for i in range(len(free))]
    S = [[_div(A[i][j], d[i] * d[j]) for j in range(len(free))] for i in range(len(free))]
    Sinv = _invert_scaled(S)
    if Sinv is None:
        out['reason'] = 'cannot tell apart'
        return out
    # The inverse of a symmetric matrix, symmetric to the last bit: the two
    # halves Gauss-Jordan gives differ in it, and a correlation is one number.
    matrix = [[1.0 if a == b else _div(0.5 * (Sinv[a][b] + Sinv[b][a]), _sqrt(Sinv[a][a] * Sinv[b][b]))
               for b in range(len(free))] for a in range(len(free))]
    out['correlations'] = {'keys': [keys[k] for k in free], 'matrix': matrix}
    if not (dof > 0):
        out['reason'] = 'no spare targets'
        return out

    s2 = ssr / dof
    t = out['t']
    for a, k in enumerate(free):
        # (J^T J)^-1 = D^-1 S^-1 D^-1, so the variance is s^2 S^-1[a][a] / d[a]^2.
        se_u = _sqrt(_div(s2 * Sinv[a][a], d[a] * d[a]))
        v = values[k]
        row = out['values'][k]
        if spaces[k] == 'log':
            row['factor'] = _exp(t * se_u)
            row['low'] = _div(v, row['factor'])
            row['high'] = v * row['factor']
            row['se'] = abs(v) * se_u
        else:
            row['se'] = se_u
            row['low'] = v - t * se_u
            row['high'] = v + t * se_u
    return out
