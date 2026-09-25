"""Which inputs the answer depends on: the measures read off a probabilistic sample.

A port of ``src/domain/sensitivity.js``. A probabilistic run gives a band; a
sensitivity analysis says what made it that wide, from the sample already
drawn and without another run:

- :func:`pearson` and :func:`spearman` (Pearson's on the ranks, ties averaged),
  at one output time (:func:`at_time`, :func:`ranked`) or at every one
  (:func:`over_time`);
- the regression family at one time, :func:`regression_measures`: R², the
  standardized regression coefficient SRC, its value in units ``b``, and the
  partial correlation PCC -- on the values, on ranks (SRRC, PRCC) or on
  logarithms;
- :func:`line_fit`, the straight line a scatter plot draws;
- :func:`first_order_index`, S1 estimated by binning the input.

Every function takes an optional ``mask`` -- 1 to use a realisation, 0 to leave
it out -- which is how a result screened to some categories of realisation is
analysed over just those. A masked realisation is treated exactly as a failed
one: as if it were not there.

The arithmetic is the application's, step for step: sums are added in the
order the JavaScript adds them (``np.cumsum`` adds left to right, which
``np.sum`` does not), and the regression's Cholesky factor and inverse are the
same sequence of operations. What involves only ``+ - * /`` and square roots
therefore comes out bit for bit as the application's; a logarithm (``translate
='log'``) can differ from V8's in its last bit.

Arrays come back as numpy ``float64`` arrays and the measures as dictionaries
with the application's keys, so that what they hold reads the same on both
sides.

This module also holds the small pieces of JavaScript arithmetic the other
statistics modules share (a sum added left to right, ``Math.round``,
``Number()``, the Cholesky factor), so each is written once.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

import numpy as np

__all__ = [
    'pearson', 'rank', 'spearman', 'scratch_for', 'at_time', 'ranked', 'over_time',
    'regression_measures', 'line_fit', 'first_order_index',
]

ArrayLike = Union[Sequence[float], np.ndarray]
Mask = Optional[Union[Sequence[Any], np.ndarray]]

# ---------------------------------------------------------------------------
# JavaScript arithmetic, shared with the other statistics modules.
# ---------------------------------------------------------------------------

# What JavaScript's Number() trims: its WhiteSpace and LineTerminator characters.
_JS_SPACE = ('\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a'
             '\u2028\u2029\u202f\u205f\u3000\ufeff')


def _f64(a: Any) -> np.ndarray:
    """A float64 array of ``a`` (a copy only where needed)."""
    return np.asarray(a, dtype=np.float64)


def _col(a: Any, n: int) -> np.ndarray:
    """The first ``n`` of ``a`` as floats, NaN past its end, as a typed array reads there."""
    v = _f64(a)
    if len(v) == n:
        return v
    out = np.full(n, math.nan)
    t = min(n, len(v))
    out[:t] = v[:t]
    return out


def _keep(mask: Mask, n: int) -> np.ndarray:
    """Which of ``n`` realisations a mask keeps: ``mask[i]`` truthy; all when there is none."""
    if mask is None:
        return np.ones(n, dtype=bool)
    m = np.asarray(mask)
    out = np.zeros(n, dtype=bool)
    t = min(n, len(m))
    if t:
        part = m[:t]
        out[:t] = (part != 0) & ~np.isnan(part) if part.dtype.kind == 'f' else part.astype(bool)
    return out


def _seqsum(a: Any) -> float:
    """The sum of ``a`` added left to right from zero, as a JavaScript loop adds it."""
    v = _f64(a)
    if v.size == 0:
        return 0.0
    return float(np.cumsum(v)[-1])


def _seqsum_rows(m: np.ndarray) -> np.ndarray:
    """Each row of a 2-D array summed left to right."""
    if m.shape[1] == 0:
        return np.zeros(m.shape[0])
    return np.cumsum(m, axis=1)[:, -1]


def _div(a: float, b: float) -> float:
    """``a / b`` as IEEE arithmetic has it: an infinity or NaN, not an exception."""
    try:
        return a / b
    except ZeroDivisionError:
        if a != a or a == 0:
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)


def _sqrt(x: float) -> float:
    """``Math.sqrt``: NaN for a negative number."""
    return math.sqrt(x) if x >= 0 else math.nan


def _log(x: float) -> float:
    """``Math.log``: minus infinity at zero, NaN below."""
    if x > 0:
        return math.log(x)
    if x == 0:
        return -math.inf
    return math.nan


def _exp(x: float) -> float:
    """``Math.exp``: infinity where it overflows."""
    try:
        return math.exp(x)
    except OverflowError:
        return math.inf


def _js_round(x: float) -> Union[int, float]:
    """``Math.round``: the nearest integer, halves towards plus infinity.

    An int for a finite number; NaN and the infinities come back as they are.
    """
    x = float(x)
    if not math.isfinite(x):
        return x
    f = math.floor(x)
    return f + 1 if x - f >= 0.5 else f


def _js_round_array(t: np.ndarray) -> np.ndarray:
    """``Math.round`` of each element, as floats."""
    f = np.floor(t)
    return f + (t - f >= 0.5)


def _js_floor(x: float) -> Union[int, float]:
    """``Math.floor``: an int for a finite number, NaN and the infinities as they are."""
    x = float(x)
    return math.floor(x) if math.isfinite(x) else x


def _js_max(*xs: float) -> float:
    """``Math.max``: NaN if any argument is NaN."""
    best = -math.inf
    for x in xs:
        if x != x:
            return math.nan
        if x > best:
            best = x
    return best


def _js_min(*xs: float) -> float:
    """``Math.min``: NaN if any argument is NaN."""
    best = math.inf
    for x in xs:
        if x != x:
            return math.nan
        if x < best:
            best = x
    return best


def _loop_count(n: Any, length: int) -> int:
    """How many of ``i = 0, 1, ...`` pass ``i < n``, at most ``length`` of them."""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return 0
    if not v > 0:
        return 0
    if v >= length:
        return length
    return int(math.ceil(v))


def _is_js_number(v: Any) -> bool:
    return isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, (bool, np.bool_))


def _is_js_finite(v: Any) -> bool:
    """``Number.isFinite``: a number, and finite (a string is not a number)."""
    if not _is_js_number(v):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:
        return False


def _is_js_integer(v: Any) -> bool:
    """``Number.isInteger``."""
    if not _is_js_number(v):
        return False
    try:
        f = float(v)
    except OverflowError:
        return False
    return math.isfinite(f) and f == math.floor(f)


def _js_truthy(v: Any) -> bool:
    """JavaScript's truthiness: an empty list or dict is true, NaN false."""
    if v is None or v is False:
        return False
    if v is True:
        return True
    if _is_js_number(v):
        return not (v == 0 or v != v)
    if isinstance(v, str):
        return len(v) > 0
    return True


def _js_number_text(x: float) -> str:
    """``String(x)`` of a number."""
    if x != x:
        return 'NaN'
    if x in (math.inf, -math.inf):
        return 'Infinity' if x > 0 else '-Infinity'
    from ..jsonio import js_number  # pylint: disable=import-outside-toplevel
    return js_number(float(x))


def _js_string(v: Any) -> str:
    """``String(v)``: how a value reads in a template or a join."""
    if v is None:
        return 'null'
    if isinstance(v, (bool, np.bool_)):
        return 'true' if v else 'false'
    if _is_js_number(v):
        try:
            return _js_number_text(float(v))
        except OverflowError:
            return 'Infinity' if v > 0 else '-Infinity'
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return ','.join('' if e is None else _js_string(e) for e in v)
    if isinstance(v, Mapping):
        return '[object Object]'
    return str(v)


def _js_number(v: Any) -> float:
    """``Number(v)``, for a value read from JSON; ``None`` is ``null`` (0)."""
    if v is None:
        return 0.0
    if isinstance(v, (bool, np.bool_)):
        return 1.0 if v else 0.0
    if _is_js_number(v):
        try:
            return float(v)
        except OverflowError:
            return math.inf if v > 0 else -math.inf
    if isinstance(v, (list, tuple, Mapping)):
        return _js_number(_js_string(v))
    if not isinstance(v, str):
        return math.nan
    s = v.strip(_JS_SPACE)
    if not s:
        return 0.0
    if s in ('Infinity', '+Infinity'):
        return math.inf
    if s == '-Infinity':
        return -math.inf
    head = s[:2].lower()
    base = {'0x': 16, '0o': 8, '0b': 2}.get(head)
    if base:
        digits = s[2:]
        try:
            return float(int(digits, base)) if digits and digits.isalnum() else math.nan
        except (ValueError, OverflowError):
            return math.inf if digits and digits.isalnum() and _all_digits(digits, base) else math.nan
    import re  # pylint: disable=import-outside-toplevel
    if re.fullmatch(r'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?', s):
        return float(s)
    return math.nan


def _all_digits(text: str, base: int) -> bool:
    try:
        int(text, base)
        return True
    except ValueError:
        return False


def _js_slice_end(most: Any, length: int) -> int:
    """Where ``array.slice(0, most)`` stops."""
    if most is None:
        return length
    try:
        v = float(most)
    except (TypeError, ValueError):
        v = _js_number(most)
    if v != v:
        return 0
    if v == math.inf:
        return length
    if v == -math.inf:
        return 0
    k = int(v)  # towards zero, as ToIntegerOrInfinity
    if k < 0:
        return max(0, length + k)
    return min(k, length)


def _cholesky_lower(a: np.ndarray, d: int, tol: float) -> Optional[np.ndarray]:
    """The lower Cholesky factor of the ``d`` x ``d`` array ``a``, or None.

    The application's loop computes ``L[i][j] = (A[i][j] - sum_l L[i][l]
    L[j][l]) / L[j][j]`` row by row, subtracting term by term; this computes the
    same entries a column at a time, the subtractions in the same order
    (``np.subtract.accumulate``), so every entry is the same number. A diagonal
    that is not above ``tol`` is a matrix that is not positive definite for the
    purpose, and gives None.
    """
    L = np.zeros((d, d))
    with np.errstate(all='ignore'):
        for j in range(d):
            if j == 0:
                s = np.array(a[j:, j], dtype=np.float64)
            else:
                terms = np.empty((j + 1, d - j))
                terms[0] = a[j:, j]
                np.multiply(L[j:, :j].T, L[j, :j, None], out=terms[1:])
                s = np.subtract.accumulate(terms, axis=0, out=terms)[-1]
            if not s[0] > tol:
                return None
            L[j, j] = math.sqrt(s[0])
            L[j + 1:, j] = s[1:] / L[j, j]
    return L


def _as_square(a: Any, n: int) -> np.ndarray:
    """A row-major ``n*n`` sequence (or an ``n`` x ``n`` array) as an array, NaN where short."""
    v = _f64(a)
    if v.ndim == 2:
        v = v.ravel()
    return _col(v, n * n).reshape(n, n) if n else np.zeros((0, 0))


def _invert_symmetric(a: np.ndarray, d: int) -> Optional[np.ndarray]:
    """The inverse of a symmetric positive-definite matrix, or None.

    Cholesky and two triangular solves per column, as the application does it:
    a pivot that is not comfortably positive is a matrix that is singular for
    the purpose -- two inputs that are the same numbers, or more inputs than
    realisations -- and None is the honest answer rather than a large wrong one.
    Every column is solved at once, each entry's subtractions in the
    application's order.
    """
    L = _cholesky_lower(a, d, 1e-10)
    if L is None:
        return None
    z = np.zeros((d, d))
    out = np.zeros((d, d))
    buf = np.empty((d, d))
    with np.errstate(all='ignore'):
        # L z = e_c for every column c. z is lower triangular: an entry above
        # the diagonal is 0 - 0 - ... = 0, so only columns up to i are solved.
        for i in range(d):
            w = i + 1
            terms = buf[:i + 1, :w]
            terms[0] = 0.0
            terms[0, i] = 1.0
            if i:
                np.multiply(L[i, :i, None], z[:i, :w], out=terms[1:])
            z[i, :w] = np.subtract.accumulate(terms, axis=0, out=terms)[-1] / L[i, i]
        # Then L' x = z.
        for i in range(d - 1, -1, -1):
            terms = buf[:d - i]
            terms[0] = z[i]
            if i < d - 1:
                np.multiply(L[i + 1:, i, None], out[i + 1:, :], out=terms[1:])
            out[i] = np.subtract.accumulate(terms, axis=0, out=terms)[-1] / L[i, i]
    return out


def _gram(z: np.ndarray, chunk: int = 4_000_000) -> np.ndarray:
    """``z' z``, every entry summed down the rows in order, as the application's dot products.

    Row by row into one matrix when there are many columns, column by column
    (a running sum down each) when there are few; the additions are the same
    either way.
    """
    m, p = z.shape
    g = np.zeros((p, p))
    if m == 0:
        return g
    if p >= 24:
        tmp = np.empty((p, p))
        for i in range(m):
            np.multiply(z[i, :, None], z[i, None, :], out=tmp)
            g += tmp
        return g
    for a in range(p):
        width = max(1, chunk // max(1, m))
        for b0 in range(a, p, width):
            b1 = min(p, b0 + width)
            sums = np.cumsum(z[:, a:a + 1] * z[:, b0:b1], axis=0)[-1]
            g[a, b0:b1] = sums
            g[b0:b1, a] = sums
    return g


# ---------------------------------------------------------------------------
# The correlations.
# ---------------------------------------------------------------------------


def pearson(x: ArrayLike, y: ArrayLike, n: Optional[int] = None) -> float:
    """Pearson's product-moment correlation of two samples.

    Non-finite pairs are left out rather than poisoning the sum: one realisation
    of a thousand can fail. Fewer than three pairs, or a sample that never
    varies, gives NaN -- a constant input has no correlation with anything, and
    saying 0 would claim it was measured.
    """
    xs = _f64(x)
    ys = _f64(y)
    count = _loop_count(len(xs) if n is None else n, min(len(xs), len(ys)))
    xs = xs[:count]
    ys = ys[:count]
    ok = np.isfinite(xs) & np.isfinite(ys)
    used = int(ok.sum())
    if used < 3:
        return math.nan
    xv = xs[ok]
    yv = ys[ok]
    mx = _seqsum(xv) / used
    my = _seqsum(yv) / used
    dx = xv - mx
    dy = yv - my
    sxy = _seqsum(dx * dy)
    sxx = _seqsum(dx * dx)
    syy = _seqsum(dy * dy)
    if not sxx > 0 or not syy > 0:
        return math.nan
    return _div(sxy, math.sqrt(sxx * syy))


def _average_ranks_finite(v: np.ndarray, into: np.ndarray) -> np.ndarray:
    """Fills ``into`` with the ranks of the finite values of ``v``, ties averaged, NaN elsewhere."""
    into[...] = math.nan
    fin = np.flatnonzero(np.isfinite(v))
    m = len(fin)
    if not m:
        return into
    order = fin[np.argsort(v[fin], kind='stable')]
    sv = v[order]
    change = np.empty(m, dtype=bool)
    change[0] = True
    change[1:] = sv[1:] != sv[:-1]
    starts = np.flatnonzero(change)
    ends = np.append(starts[1:], m) - 1
    r = (starts + ends) / 2 + 1
    into[order] = np.repeat(r, ends - starts + 1)
    return into


def rank(v: ArrayLike, n: Optional[int] = None, into: Optional[np.ndarray] = None,
         order: Optional[np.ndarray] = None) -> np.ndarray:
    """Ranks from 1, ties sharing the average of the positions they span; NaN where ``v`` is not finite.

    ``into`` is filled and returned when given, as the application fills its
    scratch array; ``order`` is accepted for the same signature and not needed.
    A vector of one repeated number ranks flat, which is what keeps a constant
    input at a correlation of NaN rather than an arbitrary one.
    """
    del order  # the application's scratch space for the sort
    vals = _f64(v)
    count = len(vals) if n is None else max(0, int(n))
    ranks = _average_ranks_finite(_col(vals, count), np.empty(count))
    if into is None:
        return ranks
    into[...] = math.nan
    t = min(len(into), count)
    into[:t] = ranks[:t]
    return into


def spearman(x: ArrayLike, y: ArrayLike, n: Optional[int] = None,
             scratch: Optional[Mapping[str, np.ndarray]] = None) -> float:
    """Spearman's coefficient: Pearson's, on the ranks.

    Each sample is ranked over its own finite values; a pair with either side
    not finite is then left out of the correlation.
    """
    count = len(_f64(x)) if n is None else n
    rx = rank(x, count, None if scratch is None else scratch.get('rx'))
    ry = rank(y, count, None if scratch is None else scratch.get('ry'))
    return pearson(rx, ry, count)


def scratch_for(n: int) -> Dict[str, np.ndarray]:
    """Room to rank two vectors of ``n`` without allocating per call: ``rx``, ``ry``, ``ix``, ``iy``."""
    return {
        'rx': np.zeros(n),
        'ry': np.zeros(n),
        'ix': np.zeros(n, dtype=np.int32),
        'iy': np.zeros(n, dtype=np.int32),
    }


def _column_at(values: ArrayLike, times: int, iterations: int, at: Any, keep: np.ndarray) -> np.ndarray:
    """``values[i * times + at]`` for each realisation, NaN where masked or past the end."""
    v = _f64(values)
    out = np.full(iterations, math.nan)
    try:
        a = float(at)
    except (TypeError, ValueError):
        return out
    if not math.isfinite(a) or a != math.floor(a):
        return out
    idx = np.arange(iterations, dtype=np.int64) * int(times) + int(a)
    ok = (idx >= 0) & (idx < len(v)) & keep
    out[ok] = v[idx[ok]]
    return out


def at_time(samples: Sequence[ArrayLike], values: ArrayLike, times: int, iterations: int, at: int,
            scratch: Optional[Dict[str, np.ndarray]] = None, mask: Mask = None) -> Dict[str, np.ndarray]:
    """How each input correlates with one output at one time: ``{'pearson', 'spearman'}``, one per input.

    ``samples`` holds one array per input, ``iterations`` long; ``values`` is
    the output, realisation-major (``values[i * times + j]``); ``at`` is which
    output time.
    """
    s = scratch if scratch is not None else scratch_for(iterations)
    y = _column_at(values, times, iterations, at, _keep(mask, iterations))
    if s.get('y') is not None:
        s['y'][:iterations] = y
    K = len(samples)
    p = np.zeros(K)
    r = np.zeros(K)
    # The output's ranks are the same for every input, so they are worked out once.
    ry = rank(y, iterations, s.get('ry'))
    for k in range(K):
        p[k] = pearson(samples[k], y, iterations)
        r[k] = pearson(rank(samples[k], iterations, s.get('rx')), ry, iterations)
    return {'pearson': p, 'spearman': r}


def ranked(samples: Sequence[ArrayLike], values: ArrayLike, times: int, iterations: int, at: int, *,
           most: Any = 20, mask: Mask = None) -> List[Dict[str, Any]]:
    """The inputs that matter at one time, ranked by the size of their Spearman coefficient.

    Rows ``{'k', 'pearson', 'spearman'}``, the ``most`` largest; an input with
    neither coefficient is left out. Ordered by |Spearman| rather than
    |Pearson|, because a monotone relationship that is not a straight line is
    the normal case.
    """
    got = at_time(samples, values, times, iterations, at, None, mask)
    p = got['pearson']
    r = got['spearman']
    rows = []
    for k in range(len(samples)):
        if not math.isfinite(r[k]) and not math.isfinite(p[k]):
            continue
        rows.append({'k': k, 'pearson': float(p[k]), 'spearman': float(r[k])})

    def size(row: Dict[str, Any]) -> float:
        v = row['spearman']
        return abs(v) if v == v and v != 0 else 0.0

    rows.sort(key=lambda row: -size(row))
    return rows[:_js_slice_end(20 if most is None else most, len(rows))]


def over_time(sample: ArrayLike, values: ArrayLike, times: int, iterations: int, *,
              rank_based: bool = True, mask: Mask = None) -> np.ndarray:
    """One input's correlation with one output at every time: Spearman's, or Pearson's with ``rank_based=False``."""
    out = np.zeros(times)
    keep = _keep(mask, iterations)
    rx = rank(sample, iterations) if rank_based else _f64(sample)
    v = _f64(values)
    idx = np.arange(iterations, dtype=np.int64) * int(times)
    for j in range(times):
        y = np.full(iterations, math.nan)
        at = idx + j
        ok = (at < len(v)) & keep
        y[ok] = v[at[ok]]
        out[j] = pearson(rx, rank(y, iterations), iterations) if rank_based else pearson(sample, y, iterations)
    return out


# ---------------------------------------------------------------------------
# The regression family, the straight line, and S1.
# ---------------------------------------------------------------------------


def regression_measures(samples: Sequence[ArrayLike], y: ArrayLike, *, translate: str = 'none',
                        mask: Mask = None) -> Dict[str, Any]:
    """The regression family at one time: R², SRC, ``b`` and PCC for every input.

    One multiple regression of the output on all the inputs at once, from the
    inputs' correlation matrix and their correlations with the output::

        SRC    = R_xx^-1 r_xy
        R²     = r_xy' SRC
        PCC_k² = SRC_k² / (SRC_k² + (1 - R²) (R_xx^-1)_kk), with SRC_k's sign

    ``translate`` is what the fit is fitted to: ``'none'`` the values,
    ``'rank'`` their ranks (SRRC and PRCC), ``'log'`` their logarithms, where a
    row with anything that is not positive is dropped and counted. ``b`` is the
    coefficient in units, ``SRC_k sd(y) / sd(x_k)`` on what the translation left.

    An input that never varied has no column and reads NaN. When the inverse
    fails -- more inputs than realisations, or two inputs that are the same
    numbers -- everything is NaN and ``ok`` is False.

    Returns ``{'r2', 'src', 'b', 'pcc', 'used', 'dropped', 'ok'}``.
    """
    K = len(samples)
    yv = _f64(y)
    n = len(yv)
    logs = translate == 'log'
    src = np.full(K, math.nan)
    b = np.full(K, math.nan)
    pcc = np.full(K, math.nan)
    keep = _keep(mask, n)
    offered = int(keep.sum())

    def usable(a: np.ndarray) -> np.ndarray:
        fin = np.isfinite(a)
        return fin & (a > 0) if logs else fin

    cols_in = [_col(s, n) for s in samples]
    good = keep & usable(yv)
    for c in cols_in:
        good &= usable(c)
    m = int(good.sum())
    dropped = offered - m

    def refused() -> Dict[str, Any]:
        return {'r2': math.nan, 'src': src, 'b': b, 'pcc': pcc, 'used': m, 'dropped': dropped, 'ok': False}

    if m < 4:
        return refused()

    def take(v: np.ndarray) -> np.ndarray:
        vals = v[good]
        return np.log(vals) if logs else vals

    def standardize(col: np.ndarray):
        x = rank(col, m) if translate == 'rank' else col
        mean = _seqsum(x) / m
        d = x - mean
        ss = _seqsum(d * d)
        if not ss > 0:
            return None
        sd = math.sqrt(ss / (m - 1))
        return d / sd, sd

    cols = []
    sds = []
    which = []
    with np.errstate(all='ignore'):
        for k in range(K):
            z = standardize(take(cols_in[k]))
            if z is not None:
                cols.append(z[0])
                sds.append(z[1])
                which.append(k)
        ystd = standardize(take(yv))
    if ystd is None or not cols:
        return refused()
    zy = ystd[0]
    P = len(cols)
    if P >= m - 1:
        return refused()
    Z = np.column_stack(cols)
    Rxx = _gram(Z) / (m - 1)
    rxy = np.cumsum(Z * zy[:, None], axis=0)[-1] / (m - 1)
    # Only the inputs' matrix is inverted: the augmented [inputs, output]
    # matrix is singular exactly when the fit is perfect, which on ranks is the
    # ordinary case of an output that follows one input.
    inv = _invert_symmetric(Rxx, P)
    if inv is None:
        return refused()
    with np.errstate(all='ignore'):
        beta = _seqsum_rows(inv * rxy[None, :])
        r2 = _seqsum(rxy * beta)
        # Rounding can carry a perfect fit a hair past one.
        left = float(_js_max(0, 1 - r2))
        ysd = ystd[1]
        idx = np.array(which, dtype=np.intp)
        src[idx] = beta
        b[idx] = beta * (ysd / np.array(sds))
        denom = beta * beta + left * np.diag(inv)
        part = np.sign(beta) * np.sqrt((beta * beta) / denom)
        pcc[idx] = np.where(denom > 0, part, 0.0)
    return {'r2': r2, 'src': src, 'b': b, 'pcc': pcc, 'used': m, 'dropped': dropped, 'ok': True}


def line_fit(x: ArrayLike, y: ArrayLike, *, translate: str = 'none', mask: Mask = None) -> Dict[str, Any]:
    """The least-squares line ``y = a + b x`` through one input and one output, and its R².

    With ``translate='log'`` the line is fitted to the logarithms, where a power
    law is straight and its slope the exponent; pairs that cannot be translated
    are left out and counted. Returns ``{'a', 'b', 'r2', 'n', 'dropped', 'log', 'ok'}``.
    """
    xv = _f64(x)
    yv = _f64(y)
    n = min(len(xv), len(yv))
    logs = translate == 'log'
    xv = xv[:n]
    yv = yv[:n]
    keep = _keep(mask, n)
    offered = int(keep.sum())

    def usable(a: np.ndarray) -> np.ndarray:
        fin = np.isfinite(a)
        return fin & (a > 0) if logs else fin

    ok = keep & usable(xv) & usable(yv)
    xs = np.log(xv[ok]) if logs else xv[ok]
    ys = np.log(yv[ok]) if logs else yv[ok]
    m = len(xs)
    dropped = offered - m
    none = {'a': math.nan, 'b': math.nan, 'r2': math.nan, 'n': m, 'dropped': dropped, 'log': logs, 'ok': False}
    if m < 3:
        return none
    mx = _seqsum(xs) / m
    my = _seqsum(ys) / m
    dx = xs - mx
    dy = ys - my
    sxx = _seqsum(dx * dx)
    syy = _seqsum(dy * dy)
    sxy = _seqsum(dx * dy)
    # A column of one value has no line through it, and neither has an output that never moved.
    if not sxx > 0 or not syy > 0:
        return none
    slope = sxy / sxx
    return {
        'a': my - slope * mx,
        'b': slope,
        'r2': _div(sxy * sxy, sxx * syy),
        'n': m,
        'dropped': dropped,
        'log': logs,
        'ok': True,
    }


def first_order_index(x: ArrayLike, y: ArrayLike, *, mask: Mask = None, bins: Any = None) -> float:
    """A first-order sensitivity index, ``Var(E[y|x]) / Var(y)``, estimated by binning.

    The input is cut into bins of equal count -- ``round(sqrt(n))`` of them,
    between 4 and 50, unless ``bins`` says -- the output averaged in each, and
    the variance of those averages is the numerator. The bias sampling noise
    puts in it, about ``bins / n``, is subtracted and the result clamped to
    [0, 1]; NaN when there is nothing to measure (fewer than ten usable pairs,
    a constant input, or an output that never varied).
    """
    xv = _f64(x)
    n = len(xv)
    yv = _col(y, n)
    ok = _keep(mask, n) & np.isfinite(xv) & np.isfinite(yv)
    idx = np.flatnonzero(ok)
    m = len(idx)
    if m < 10:
        return math.nan
    idx = idx[np.argsort(xv[idx], kind='stable')]
    # A constant input has no bins to speak of.
    if xv[idx[0]] == xv[idx[m - 1]]:
        return math.nan
    ys = yv[idx]
    mean = _seqsum(ys) / m
    d = ys - mean
    total = _seqsum(d * d) / m
    if not total > 0:
        return math.nan
    B = bins if bins is not None else _js_max(4, _js_min(50, _js_round(math.sqrt(m))))
    between = 0.0
    b = 0
    while b < B:
        frm = math.floor((b * m) / B)
        to = math.floor(((b + 1) * m) / B)
        if to > frm:
            mb = _seqsum(ys[frm:to]) / (to - frm)
            dev = mb - mean
            between += (to - frm) * (dev * dev)
        b += 1
    between /= m
    # The bin means carry noise of about total/(m/B) each, which adds B/m of the total to `between`.
    raw = _div(between, total) - _div(B, m)
    return float(_js_max(0, _js_min(1, raw)))
