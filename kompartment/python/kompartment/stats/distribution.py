"""What a sample of one output looks like, in numbers: Kompartment's distribution summary.

A port of the application's ``src/domain/distribution.js``: one output at one
time over the realisations, sorted once so that every question after the first
is a lookup -- the mean with normal-approximation bounds, standard deviation,
skewness and excess kurtosis, a percentile table, the probability of a value,
the conditional tail expectation, a histogram, and the Dvoretzky-Kiefer-
Wolfowitz band on the whole distribution function, which holds for any shape.

The percentile at ``p`` is the value at position ``p * (n - 1)`` of the sorted
sample, linearly interpolated (a spreadsheet's PERCENTILE). The arithmetic is
the application's, in the same order, with V8's logarithms and exponentials
(see :mod:`.pdf`); the skewness uses the platform's ``pow`` and agrees to the
last bit or two.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from .pdf import _div, _exp, _jmax, _jmin, _js_round, _log, _log_array, _pow, _to_number

__all__ = [
    'sorted_column', 'value_at', 'probability_of', 'conditional_tail_expectation', 'PERCENTILES',
    'describe_sample', 'HIST_BINS', 'histogram',
]

#: The percentiles a summary tabulates.
PERCENTILES: List[float] = [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]

#: How many bins a histogram may be asked for.
HIST_BINS: Dict[str, int] = {'min': 2, 'max': 200}


def _seq_sum(values: Any) -> float:
    """``s = 0; for (v of values) s += v``: a sum in order, as the application adds."""
    import numpy as np
    if len(values) == 0:
        return 0.0
    with np.errstate(all='ignore'):
        return float(np.cumsum(np.concatenate(([0.0], values)))[-1])


def _typed_sort(values: Any) -> Any:
    """``Float64Array.prototype.sort``: ascending, -0 before +0, NaN last."""
    import numpy as np
    s = np.sort(np.array(values, dtype=np.float64), kind='stable')
    zeros = np.flatnonzero(s == 0)
    if zeros.size:
        negative = int(np.signbit(s[zeros]).sum())
        s[zeros[:negative]] = -0.0
        s[zeros[negative:]] = 0.0
    return s


def sorted_column(values: Sequence[float], times: int, iterations: int, at: int,
                  mask: Optional[Sequence[Any]] = None) -> Any:
    """One output at one time, over the realisations, sorted and finite: a float64 numpy array.

    ``values`` is realisation-major, ``iterations x times``: realisation ``i``
    at time ``j`` is ``values[i * times + j]``; ``at`` is the time. ``mask``,
    where given, keeps realisation ``i`` where ``mask[i]`` is true (non-zero)
    and screens it out otherwise. NaN and infinite values -- realisations that
    failed -- are left out.
    """
    import numpy as np
    vals = np.asarray(values, dtype=np.float64).ravel()
    idx = np.arange(int(iterations), dtype=np.int64) * int(times) + int(at)
    keep = (idx >= 0) & (idx < len(vals))
    if mask is not None:
        m = np.zeros(len(idx), dtype=bool)
        given = np.asarray(mask, dtype=np.float64).ravel()[:len(idx)]
        m[:len(given)] = (given != 0) & ~np.isnan(given)
        keep &= m
    picked = vals[idx[keep]]
    return _typed_sort(picked[np.isfinite(picked)])


def value_at(sorted_: Sequence[float], p: float) -> float:
    """The value at cumulative probability ``p``, interpolated between order statistics."""
    n = len(sorted_)
    if not n:
        return math.nan
    if n == 1:
        return float(sorted_[0])
    x = _jmin(1.0, _jmax(0.0, _to_number(p))) * (n - 1)
    if x != x:
        return math.nan
    lo = math.floor(x)
    hi = min(n - 1, lo + 1)
    a = float(sorted_[lo])
    return a + (float(sorted_[hi]) - a) * (x - lo)


def probability_of(sorted_: Sequence[float], x: float) -> float:
    """The fraction of the sample at or below ``x``: the empirical CDF."""
    n = len(sorted_)
    if not n:
        return math.nan
    x = _to_number(x)
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) >> 1
        if sorted_[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo / n


def conditional_tail_expectation(sorted_: Sequence[float], q: float) -> float:
    """The mean of the sample above its ``q``-quantile: what the bad cases average to.

    Not where the tail starts but how heavy it is -- the number a regulator
    asks for after the 95th percentile.
    """
    import numpy as np
    n = len(sorted_)
    if not n:
        return math.nan
    t = _jmin(1.0, _jmax(0.0, _to_number(q))) * n
    if t != t:
        return math.nan
    start = min(n - 1, math.floor(t))
    return _seq_sum(np.asarray(sorted_, dtype=np.float64)[start:]) / (n - start)


def describe_sample(sorted_: Sequence[float]) -> Dict[str, Any]:
    """The summary itself, of a column from :func:`sorted_column`.

    Returns ``{'n', 'mean', 'sd', 'skewness', 'kurtosis', 'min', 'max',
    'meanBounds', 'percentiles', 'dkw'}``: the sample SD (over n - 1), the
    population skewness and excess kurtosis, the 95% bounds on the mean, the
    :data:`PERCENTILES` as ``[{'p', 'value'}]``, and ``dkw``, the half-width of
    the 95% Dvoretzky-Kiefer-Wolfowitz band on the CDF, ``sqrt(ln(40) / 2n)``.
    """
    import numpy as np
    a = np.asarray(sorted_, dtype=np.float64)
    n = len(a)
    if not n:
        return {
            'n': 0, 'mean': math.nan, 'sd': math.nan, 'skewness': math.nan, 'kurtosis': math.nan,
            'min': math.nan, 'max': math.nan, 'meanBounds': [math.nan, math.nan], 'percentiles': [],
            'dkw': math.nan,
        }
    mean = _seq_sum(a) / n
    with np.errstate(all='ignore'):
        d = a - mean
        d2 = d * d
        m2 = _seq_sum(d2)
        m3 = _seq_sum(d2 * d)
        m4 = _seq_sum(d2 * d2)
    # The sample standard deviation (n - 1), which a bound on the mean wants;
    # the population form for the shape.
    sd = math.sqrt(m2 / (n - 1)) if n > 1 else 0
    v = m2 / n
    skewness = _div(m3 / n, _pow(v, 1.5)) if v > 0 else math.nan
    kurtosis = _div(m4 / n, v * v) - 3 if v > 0 else math.nan
    half = 1.959964 * sd / math.sqrt(n) if n > 1 else 0
    return {
        'n': n,
        'mean': mean,
        'sd': sd,
        'skewness': skewness,
        'kurtosis': kurtosis,
        'min': float(a[0]),
        'max': float(a[n - 1]),
        'meanBounds': [mean - half, mean + half],
        'percentiles': [{'p': p, 'value': value_at(a, p)} for p in PERCENTILES],
        # DKW: P(sup|F_n - F| > e) <= 2 exp(-2 n e**2), so at 95% e = sqrt(ln(2/0.05) / 2n).
        'dkw': math.sqrt(_log(2 / 0.05) / (2 * n)),
    }


def histogram(sorted_: Sequence[float], bins: Any = None, scale: str = 'auto') -> Dict[str, Any]:
    """A histogram of an ascending sample, for the density panel.

    ``bins`` is how many (clamped to :data:`HIST_BINS`; ``None`` or fewer than
    two for Sturges' rule, 5 to 60). ``scale`` is what the bin edges are spaced
    by: ``'linear'``, ``'log'``, or ``'auto'`` -- a log axis where the sample
    is positive and its 5th to 95th percentiles span more than two decades. A
    log request on a sample that reaches zero or below cannot be honoured; it
    falls back to linear and says so in ``refused``.

    Returns ``{'edges', 'counts', 'log', 'wanted', 'refused'}``: ``edges`` a
    float64 array one longer than ``counts`` (uint32), ``wanted`` the scale
    asked for. A sample of fewer than two has no histogram (empty arrays).
    """
    import numpy as np
    a = np.asarray(sorted_, dtype=np.float64)
    n = len(a)
    if n < 2:
        return {'edges': np.zeros(0, dtype=np.float64), 'counts': np.zeros(0, dtype=np.uint32),
                'log': False, 'wanted': scale, 'refused': False}
    asked = _js_round(_to_number(bins))
    if math.isfinite(asked) and asked >= HIST_BINS['min']:
        k = int(min(HIST_BINS['max'], asked))
    else:
        k = max(5, min(60, math.ceil(math.log2(n) + 1)))
    lo = float(a[0])
    hi = float(a[n - 1])
    # Decades, judged on the body of the sample and not its extremes.
    can = lo > 0
    if scale == 'log':
        log = can
    elif scale == 'linear':
        log = False
    else:
        log = can and value_at(a, 0.95) / value_at(a, 0.05) > 100
    refused = scale == 'log' and not can
    edges = np.empty(k + 1, dtype=np.float64)
    for b in range(k + 1):
        if log:
            edges[b] = _exp(_log(lo) + (_log(hi) - _log(lo)) * (b / k))
        else:
            edges[b] = lo + (hi - lo) * (b / k)
    with np.errstate(all='ignore'):
        if log:
            where = np.floor(((_log_array(a) - _log(lo)) / (_log(hi) - _log(lo))) * k)
        else:
            where = np.floor(((a - lo) / (hi - lo)) * k)
    # A bin that is not a number -- a sample all of one value, 0/0 -- counts
    # nowhere, as the application's typed array ignores such an index.
    counted = ~np.isnan(where)
    where = np.where(where >= k, k - 1, where)
    where = np.where(where < 0, 0, where)
    counts = np.bincount(where[counted].astype(np.int64), minlength=k).astype(np.uint32)
    return {'edges': edges, 'counts': counts, 'log': bool(log), 'wanted': scale, 'refused': bool(refused)}
