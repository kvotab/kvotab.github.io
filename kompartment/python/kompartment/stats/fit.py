"""A distribution fitted to a sample, and the fits ranked, as Kompartment does it.

A port of the application's ``src/domain/fit.js``. The shapes are the ones a
parameter can be given (:mod:`.pdf`), so a fit is an expression that can be
written straight back into a model: ``logt(min=...,max=...,mode=...)``. The
three log-normal spellings are one shape, fitted once -- as a geometric mean
and SD by maximum likelihood, as an arithmetic mean and SD by moments.

**Maximum likelihood** is the mean and SD (of the values or their logarithms)
for the normal and log-normal, the smallest and largest value for the two
uniforms, and a search for the four triangles: the mode is always one of the
realisations (Oliver 1972), which leaves the two ends, searched by Nelder-Mead.
**Moments** match the sample's mean and variance, and its skewness for a
three-parameter shape; a shape that cannot be as skewed as the sample is given
the most skewness it can have, and says so. The fits are ranked by
Anderson-Darling's A², Kolmogorov-Smirnov's D or AIC.

The arithmetic is the application's, in the same order, with V8's logarithms
and exponentials (see :mod:`.pdf`), so a search takes the same steps and ends
at the same numbers. Powers (``x ** 1.5``, ``x ** 3``) go through the
platform's ``pow``, which V8 can differ from in the last bit; the moment fits
and skewnesses that use them agree to a few units in the last place.
"""

from __future__ import annotations

import functools
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .pdf import (
    _MISSING, _div, _exp, _expm1, _four_figures, _is_finite_num, _jmax, _jmin, _log, _log1p_array,
    _log_array, _meta, _pow, _prop, _sqrt, _to_number, _truthy, cumulative_at, density_at,
)

__all__ = [
    'FIT_METHODS', 'FIT_TESTS', 'FIT_FAMILIES', 'FIT_MIN_SAMPLE', 'sample_moments', 'fit_family',
    'ks_p_value', 'ad_p_value', 'score_fit', 'fit_all', 'rank_fits', 'fit_text',
]

#: The two methods: ``[id, label, what it is]``.
FIT_METHODS: List[List[str]] = [
    ['mle', 'maximum likelihood', 'The parameters under which this sample is the most probable.'],
    ['mom', 'method of moments', 'The parameters whose mean and variance — and skewness, for a three-parameter '
     'shape — are the sample’s.'],
]

#: The three goodness-of-fit measures a table can be ranked by: ``[id, label, what it is]``.
FIT_TESTS: List[List[str]] = [
    ['ad', 'Anderson–Darling', 'A²: the squared gap between the cumulative curves, weighted towards the '
     'tails. Smaller is better.'],
    ['ks', 'Kolmogorov–Smirnov', 'D: the largest gap between the cumulative curves. Smaller is better.'],
    ['aic', 'AIC', 'Akaike’s information criterion: −2 × log-likelihood + 2 per fitted parameter. '
     'Smaller is better; shown less the smallest in the table.'],
]

#: The shapes, in the order the model's editor offers them.
FIT_FAMILIES: List[Dict[str, Any]] = [
    {'id': 'unif', 'label': 'Uniform', 'params': 2},
    {'id': 'triang', 'label': 'Triangular', 'params': 3},
    {'id': 'dtriang', 'label': 'Double-triangular', 'params': 3},
    {'id': 'norm', 'label': 'Normal', 'params': 2},
    {'id': 'logu', 'label': 'Log-uniform', 'params': 2, 'positive': True},
    {'id': 'logt', 'label': 'Log-triangular', 'params': 3, 'positive': True},
    {'id': 'logdt', 'label': 'Log-double-triangular', 'params': 3, 'positive': True},
    {'id': 'logn', 'label': 'Log-normal', 'params': 2, 'positive': True},
]

#: Fewer than this and a fit is a guess with decimals.
FIT_MIN_SAMPLE = 5

_LN2 = 0.6931471805599453  # Math.LN2
_EPSILON = 2.220446049250313e-16  # Number.EPSILON
_MIN_VALUE = 5e-324  # Number.MIN_VALUE


def _array(x: Any) -> Any:
    import numpy as np
    return np.asarray(x, dtype=np.float64)


def _seq_sum(values: Any) -> float:
    """``s = 0; for (v of values) s += v``: a sum in order, as the application adds."""
    import numpy as np
    if len(values) == 0:
        return 0.0
    with np.errstate(all='ignore'):
        return float(np.cumsum(np.concatenate(([0.0], values)))[-1])


def sample_moments(x: Sequence[float]) -> Dict[str, Any]:
    """Mean, variance and skewness -- the population ones, over ``n``.

    Returns ``{'n', 'mean', 'm2', 'sd', 'skew'}``; the skewness is 0 for a
    sample with no spread.
    """
    import numpy as np
    a = _array(x)
    n = len(a)
    mean = _div(_seq_sum(a), n)
    with np.errstate(all='ignore'):
        d = a - mean
        d2 = d * d
        m2 = _div(_seq_sum(d2), n)
        m3 = _div(_seq_sum(d2 * d), n)
    return {'n': n, 'mean': mean, 'm2': m2, 'sd': _sqrt(m2), 'skew': _div(m3, _pow(m2, 1.5)) if m2 > 0 else 0}


# ---------------------------------------------------------------------------
# The triangles, standardised: a peak at `r` on [0, 1]. The triangle holds `r`
# of its probability left of the peak; the double triangle holds half there.
# ---------------------------------------------------------------------------


def _left_weight(r: float, double: bool) -> float:
    return 0.5 if double else r


def _shape_raw(r: float, double: bool) -> List[float]:
    """E[Z**k] for k = 1..3, from the binomial expansion of each piece."""
    wl = _left_weight(r, double)
    q = 1 - r
    out: List[float] = [1]
    for k in range(1, 4):
        # E[V**k] = 2/(k+2); the right piece expanded in powers of (1-r).
        right = 0.0
        c = 1.0
        for j in range(k + 1):
            right += c * _pow(-q, j) * (2 / (j + 2))
            c = (c * (k - j)) / (j + 1)
        out.append(wl * _pow(r, k) * (2 / (k + 2)) + (1 - wl) * right)
    return out


def _shape_moments(r: float, double: bool) -> Dict[str, float]:
    """Mean, SD and skewness of the standardised shape."""
    _, m1, m2, m3 = _shape_raw(r, double)
    v = m2 - m1 * m1
    return {'mean': m1, 'sd': _sqrt(v), 'skew': _div(m3 - 3 * m1 * m2 + 2 * _pow(m1, 3), _pow(v, 1.5))}


def _solve_shape(measure: Callable[[float], float], target: float, lo: float, hi: float) -> Tuple[float, bool]:
    """The peak at which ``measure(r)`` equals ``target``: ``(r, clamped)``.

    A scan for a change of sign and bisection inside it; none -- the target out
    of the shape's reach -- gives the nearest, flagged ``clamped``.
    """
    steps = 64
    prev_r = lo
    prev = measure(lo) - target
    best_r, best_gap = lo, abs(prev)
    if prev == 0:
        return lo, False
    for s in range(1, steps + 1):
        r = lo + ((hi - lo) * s) / steps
        now = measure(r) - target
        if not math.isfinite(now):
            prev_r = r
            prev = now
            continue
        if abs(now) < best_gap:
            best_r, best_gap = r, abs(now)
        if now == 0:
            return r, False
        if math.isfinite(prev) and (prev < 0) != (now < 0):
            a, b, fa = prev_r, r, prev
            for _ in range(60):
                m = (a + b) / 2
                fm = measure(m) - target
                if (fm < 0) == (fa < 0):
                    a = m
                    fa = fm
                else:
                    b = m
            return (a + b) / 2, False
        prev_r = r
        prev = now
    return best_r, True


# ---------------------------------------------------------------------------
# The log shapes' moments: X = exp(Y), Y = ln(min) + L*Z, so E[X**k] is Z's
# moment generating function at kL, kept as e**kL times a number in (0, 1].
# ---------------------------------------------------------------------------


def _ramp_mgf(s: float) -> float:
    """E[exp(-sV)] for V with density 2v on [0, 1], any real ``s``."""
    if abs(s) < 0.5:
        # 2 * sum (-s)**n / (n! (n+2)), where the closed form cancels.
        total = 0.0
        term = 1.0
        for n in range(24):
            total += term / (n + 2)
            term *= -s / (n + 1)
        return 2 * total
    return _div(2 * (1 - _exp(-s) * (1 + s)), s * s)


def _ramp_mgf_up(s: float, t: float) -> float:
    """exp(-t) E[exp(sV)], kept finite however large ``s`` is (s <= t)."""
    if s < 0.5:
        return _exp(-t) * _ramp_mgf(-s)
    return _div(2 * (_exp(s - t) * (s - 1) + _exp(-t)), s * s)


def _peak_scaled(t: float, r: float, double: bool) -> float:
    """E[exp(-t(1-Z))] for the peak shape."""
    wl = _left_weight(r, double)
    return wl * _ramp_mgf_up(t * r, t) + (1 - wl) * _ramp_mgf(t * (1 - r))


def _flat_scaled(t: float) -> float:
    """E[exp(-t(1-U))] for U uniform."""
    return 1.0 if t < 1e-12 else _div(-_expm1(-t), t)


def _log_moments(scaled: Callable[[float], float], spread: float) -> Dict[str, float]:
    """The squared coefficient of variation and the skewness of X = exp(L Z)."""
    m1 = scaled(spread)
    m2 = scaled(2 * spread)
    m3 = scaled(3 * spread)
    v = _div(m2, m1 * m1) - 1
    c = m2 - m1 * m1
    return {'cv2': v, 'skew': _div(m3 - 3 * m1 * m2 + 2 * _pow(m1, 3), _pow(c, 1.5)), 'm1': m1}


def _spread_for(scaled: Callable[[float], float], cv2: float) -> Optional[float]:
    """The spread L at which the squared CV is ``cv2``, or ``None`` out of reach."""
    a = _log(1e-5)
    b = _log(1400)
    if not _log_moments(scaled, _exp(b))['cv2'] >= cv2:
        return None
    if _log_moments(scaled, _exp(a))['cv2'] >= cv2:
        return _exp(a)
    for _ in range(80):
        m = (a + b) / 2
        if _log_moments(scaled, _exp(m))['cv2'] < cv2:
            a = m
        else:
            b = m
    return _exp((a + b) / 2)


# ---------------------------------------------------------------------------
# Maximum likelihood for the triangles.
# ---------------------------------------------------------------------------


def _triangle_profile(z: Any, a: float, b: float, double: bool) -> Dict[str, Any]:
    """The log-likelihood of the triangle on [a, b] whose mode is the best candidate.

    ``z`` sorted in (a, b). The candidates are the order statistics and, for
    the plain triangle, the two ends; for the double triangle, whose density
    jumps at the mode, also the mode a hair below each realisation
    (``below``). Returns ``{'ll', 'at', 'below'}``, ``at`` -1 and n for the ends.

    The application's loop, run over the whole sample at once: the running
    sums are sums in the same order, every term the same arithmetic, and the
    best is the first candidate strictly better than all before it.
    """
    import numpy as np
    n = len(z)
    w = b - a
    with np.errstate(all='ignore'):
        u = (z - a) / w
        lu = _log_array(u)
        lv = _log1p_array(-u)
        right0 = _seq_sum(lv)
        base = -n * _log(w) if double else n * _LN2 - n * _log(w)
        p = 2.0 if double else 1.0
        left = np.cumsum(np.concatenate(([0.0], lu)))  # left before realisation r, and after the last
        right = np.subtract.accumulate(np.concatenate(([right0], lv)))
        r = np.arange(n, dtype=np.float64)
        at_ll = base + left[1:] - p * (r + 1) * lu + right[1:] - p * (n - r - 1) * lv
        if double:
            below_ll = base + left[:-1] - p * r * lu + right[:-1] - p * (n - r) * lv
            cand = np.empty(2 * n, dtype=np.float64)
            cand[0::2] = below_ll
            cand[1::2] = at_ll
            start = (-math.inf, -1, False)
        else:
            cand = np.concatenate((at_ll, [base + float(left[-1])]))
            start = (base + right0, -1, False)
    if start[0] != start[0] or len(cand) == 0:
        best = start
    else:
        clean = np.where(np.isnan(cand), -np.inf, cand)
        top = float(clean.max())
        if top > start[0]:
            i = int(np.argmax(clean == top))
            if double:
                best = (float(cand[i]), i // 2, i % 2 == 0)
            else:
                best = (float(cand[i]), i if i < n else n, False)
        else:
            best = start
    return {'ll': best[0], 'at': best[1], 'below': best[2]}


def _under(v: float) -> float:
    """The largest number below ``v``, or near enough: a hair under it."""
    return -_MIN_VALUE if v == 0 else v - abs(v) * _EPSILON


def _js_sort(items: List[Any], compare: Callable[[Any, Any], float]) -> List[Any]:
    """``items.slice().sort(compare)``, as V8 sorts: a NaN from ``compare`` counts as 0.

    For fewer than 64 items V8's TimSort is a run count and a binary insertion
    sort, reproduced here step for step, so that a comparison that is not
    consistent gives what it gives in the application. Longer lists are sorted
    stably, which is the same for any consistent comparison.
    """
    def cmp(x: Any, y: Any) -> float:
        c = compare(x, y)
        return 0 if c != c else c

    a = list(items)
    n = len(a)
    if n < 2:
        return a
    if n >= 64:
        return sorted(a, key=functools.cmp_to_key(lambda x, y: -1 if cmp(x, y) < 0 else (1 if cmp(x, y) > 0 else 0)))
    run = 2
    descending = cmp(a[1], a[0]) < 0
    previous = a[1]
    for idx in range(2, n):
        order = cmp(a[idx], previous)
        if descending:
            if order >= 0:
                break
        elif order < 0:
            break
        previous = a[idx]
        run += 1
    if descending:
        a[:run] = a[:run][::-1]
    for start in range(run, n):
        left, right = 0, start
        pivot = a[start]
        while left < right:
            mid = left + ((right - left) >> 1)
            if cmp(pivot, a[mid]) < 0:
                right = mid
            else:
                left = mid + 1
        a[left + 1:start + 1] = a[left:start]
        a[left] = pivot
    return a


def _nelder_mead(f: Callable[[List[float]], float], x0: List[float], step: float = 0.7,
                 iterations: int = 160, tol: float = 1e-10) -> Tuple[List[float], float]:
    """A small Nelder-Mead, for the two ends: the best point and its value."""
    d = len(x0)
    pts = [list(x0)]
    for i in range(d):
        x = list(x0)
        x[i] += step
        pts.append(x)
    vals = [f(p) for p in pts]
    for _ in range(iterations):
        order = _js_sort(list(range(d + 1)), lambda i, j: vals[i] - vals[j])
        pts = [pts[i] for i in order]
        vals = [vals[i] for i in order]
        if abs(vals[d] - vals[0]) <= tol * (1 + abs(vals[0])):
            break
        c = [0.0] * d
        for i in range(d):
            for j in range(d):
                c[j] += pts[i][j] / d
        worst = pts[d]

        def along(t: float) -> List[float]:
            return [cj + t * (worst[j] - cj) for j, cj in enumerate(c)]

        xr = along(-1)
        fr = f(xr)
        if fr < vals[0]:
            xe = along(-2)
            fe = f(xe)
            if fe < fr:
                pts[d] = xe
                vals[d] = fe
            else:
                pts[d] = xr
                vals[d] = fr
        elif fr < vals[d - 1]:
            pts[d] = xr
            vals[d] = fr
        else:
            xc = along(-0.5 if fr < vals[d] else 0.5)
            fc = f(xc)
            if fc < _jmin(fr, vals[d]):
                pts[d] = xc
                vals[d] = fc
            else:
                for i in range(1, d + 1):
                    pts[i] = [pts[0][j] + 0.5 * (v - pts[0][j]) for j, v in enumerate(pts[i])]
                    vals[i] = f(pts[i])
    k = 0
    for i in range(1, d + 1):
        if vals[i] < vals[k]:
            k = i
    return pts[k], vals[k]


def _clamp(v: float) -> float:
    return _jmin(6.0, _jmax(-28.0, v))


def _triangle_mle(y: Any, double: bool) -> Dict[str, Any]:
    """The triangle of largest likelihood through sorted ``y``: its ends, and where its mode is.

    Standardised to [0, 1] first, and the ends searched as their distance past
    the extremes on a log scale: ``a = -exp(alpha)``, ``b = 1 + exp(beta)``.
    Returns ``{'min', 'max', 'at', 'below'}`` (see :func:`_triangle_profile`).
    """
    import numpy as np
    y = _array(y)
    n = len(y)
    lo = float(y[0])
    span = float(y[n - 1]) - lo
    with np.errstate(all='ignore'):
        z = (y - lo) / span

    def cost(x: List[float]) -> float:
        return -_triangle_profile(z, -_exp(_clamp(x[0])), 1 + _exp(_clamp(x[1])), double)['ll']

    best: Optional[Tuple[List[float], float]] = None
    for s in (-4.0, -1.5):
        got = _nelder_mead(cost, [s, s])
        if best is None or got[1] < best[1]:
            best = got
    assert best is not None
    a = -_exp(_clamp(best[0][0]))
    b = 1 + _exp(_clamp(best[0][1]))
    found = _triangle_profile(z, a, b, double)
    return {'min': lo + a * span, 'max': lo + b * span, 'at': found['at'], 'below': found['below']}


def _mode_of(found: Dict[str, Any], sorted_: Any, lo: float, hi: float) -> float:
    """The mode found, in the units of ``sorted_``: a realisation as it is, or a hair under it."""
    if found['at'] < 0:
        return lo
    if found['at'] >= len(sorted_):
        return hi
    v = float(sorted_[found['at']])
    return _under(v) if found['below'] else v


# ---------------------------------------------------------------------------
# The fits.
# ---------------------------------------------------------------------------


def _family(fid: Any) -> Optional[Dict[str, Any]]:
    return next((f for f in FIT_FAMILIES if f['id'] == fid), None)


def fit_family(fid: str, sorted_: Sequence[float], method: str) -> Dict[str, Any]:
    """One shape (``fid``, a :data:`FIT_FAMILIES` id) fitted to ``sorted_`` by ``method`` ('mle' or 'mom').

    ``sorted_`` is the sample in ascending order. Returns ``{'spec': {'kind',
    'params'}}`` with, where they apply, ``'edges': True`` (the fit's ends are
    the sample's extremes, which :func:`score_fit` then leaves out) and
    ``'note'`` (what the fit had to give up) -- or ``{'why': reason}`` for a
    shape that could not be fitted.
    """
    got = _fit_shape(fid, sorted_, method)
    if _truthy(got.get('why')):
        return got
    # What a moment fit asks of a log shape can be past what a number holds.
    p = got['spec']['params']
    lo = p.get('min', _MISSING)
    ok = (all(_is_finite_num(v) for v in p.values())
          and (lo is _MISSING or lo is None or p['max'] > lo)
          and (p.get('mode') is None or (p['mode'] >= p['min'] and p['mode'] <= p['max']))
          and (not (_family(fid) or {}).get('positive') or not _to_number(lo) <= 0))
    return got if ok else {'why': 'would need numbers beyond what a computer holds'}


def _fit_shape(fid: Any, sorted_: Sequence[float], method: str) -> Dict[str, Any]:
    fam = _family(fid)
    if not fam:
        return {'why': 'not a shape a parameter can have'}
    y = _array(sorted_)
    n = len(y)
    if n < FIT_MIN_SAMPLE:
        return {'why': f'needs at least {FIT_MIN_SAMPLE} realisations'}
    first = float(y[0])
    last = float(y[n - 1])
    if not last > first:
        return {'why': 'every realisation has the same value'}
    if fam.get('positive') and not first > 0:
        return {'why': 'needs every value above zero'}
    mom = method == 'mom'
    x = sample_moments(y)
    # A log shape a thousandth wide is its linear shape to the sixth figure.
    if mom and fam.get('positive') and fid != 'logn' and x['sd'] < 1e-3 * x['mean']:
        return {'why': 'too narrow for its moments to tell it from the linear shape'}

    def spec(kind: str, params: Dict[str, float], **extra: Any) -> Dict[str, Any]:
        return {'spec': {'kind': kind, 'params': params}, **extra}

    if fid == 'norm':
        return spec('norm', {'mean': x['mean'], 'sd': x['sd']})
    if fid == 'unif':
        if mom:
            return spec('unif', {'min': x['mean'] - math.sqrt(3) * x['sd'], 'max': x['mean'] + math.sqrt(3) * x['sd']})
        return spec('unif', {'min': first, 'max': last}, edges=True)
    if fid == 'logn':
        if mom:
            return spec('logn', {'mean': x['mean'], 'sd': x['sd']})
        logs = sample_moments(_log_array(y))
        return spec('Logn4', {'gm': _exp(logs['mean']), 'gsd': _exp(logs['sd'])})
    if fid == 'logu':
        if not mom:
            return spec('logu', {'min': first, 'max': last}, edges=True)
        spread = _spread_for(_flat_scaled, _div(x['m2'], x['mean'] * x['mean']))
        if spread is None:
            return {'why': 'would need a range of more than 600 decades'}
        la = _log(x['mean']) - spread - _log(_flat_scaled(spread))
        return spec('logu', {'min': _exp(la), 'max': _exp(la + spread)})
    if fid in ('triang', 'dtriang'):
        double = fid == 'dtriang'
        if not mom:
            found = _triangle_mle(y, double)
            return spec(fid, {'min': found['min'], 'max': found['max'],
                              'mode': _mode_of(found, y, found['min'], found['max'])})
        # The peak from the skewness, which is the shape's alone; then the width
        # from the SD and the position from the mean.
        rlo, rhi = (1e-4, 1 - 1e-4) if double else (0.0, 1.0)
        r, clamped = _solve_shape(lambda q: _shape_moments(q, double)['skew'], x['skew'], rlo, rhi)
        m = _shape_moments(r, double)
        width = _div(x['sd'], m['sd'])
        lo = x['mean'] - width * m['mean']
        extra = {'note': f"the sample is more skewed than a {fam['label'].lower()} shape can be"} if clamped else {}
        return spec(fid, {'min': lo, 'max': lo + width, 'mode': lo + r * width}, **extra)
    if fid in ('logt', 'logdt'):
        double = fid == 'logdt'
        if not mom:
            # The triangle in the logarithms, which is where it is one.
            found = _triangle_mle(_log_array(y), double)
            lo = _exp(found['min'])
            hi = _exp(found['max'])
            return spec(fid, {'min': lo, 'max': hi, 'mode': _mode_of(found, y, lo, hi)})
        # The spread L and the peak r from the CV and the skewness, neither of
        # which depends on where the shape sits; the position last, from the mean.
        cv2 = _div(x['m2'], x['mean'] * x['mean'])
        rlo, rhi = (1e-3, 1 - 1e-3) if double else (0.0, 1.0)

        def spread_at(q: float) -> Optional[float]:
            return _spread_for(lambda t: _peak_scaled(t, q, double), cv2)

        def skew_at(q: float) -> float:
            spread_q = spread_at(q)
            return math.nan if spread_q is None else _log_moments(lambda t: _peak_scaled(t, q, double), spread_q)['skew']

        r, clamped = _solve_shape(skew_at, x['skew'], rlo, rhi)
        spread = spread_at(r)
        if spread is None:
            return {'why': 'would need a range of more than 600 decades'}
        la = _log(x['mean']) - spread - _log(_peak_scaled(spread, r, double))
        extra = ({'note': 'no shape of this kind has both the sample’s spread and its skewness — the nearest'}
                 if clamped else {})
        return spec(fid, {'min': _exp(la), 'max': _exp(la + spread), 'mode': _exp(la + r * spread)}, **extra)
    return {'why': 'not a shape a parameter can have'}


# ---------------------------------------------------------------------------
# The scores.
# ---------------------------------------------------------------------------


def ks_p_value(d: float, n: int) -> float:
    """Kolmogorov's distribution: the probability of a gap at least ``d`` over ``n`` points.

    With Stephens's correction for a finite sample (Numerical Recipes' ``probks``).
    """
    sq = math.sqrt(n)
    lam = (sq + 0.12 + _div(0.11, sq)) * d
    if lam < 0.2:
        return 1.0
    a2 = -2 * lam * lam
    fac = 2.0
    total = 0.0
    before = 0.0
    for j in range(1, 101):
        term = fac * _exp(a2 * j * j)
        total += term
        if abs(term) <= 0.001 * before or abs(term) <= 1e-8 * total:
            return _jmin(1.0, _jmax(0.0, total))
        fac = -fac
        before = abs(term)
    return 1.0


def ad_p_value(a2: float) -> float:
    """The probability of an A² at least ``a2``, from the limiting distribution.

    Marsaglia & Marsaglia (2004), ``ADinf``, good to 2e-6.
    """
    if not a2 > 0:
        return 1.0
    if not math.isfinite(a2):
        return 0.0
    z = a2
    if z < 2:
        below = ((_exp(-1.2337141 / z) / math.sqrt(z))
                 * (2.00012 + (0.247105 - (0.0649821 - (0.0347962 - (0.011672 - 0.00168691 * z) * z) * z) * z) * z))
    else:
        below = _exp(-_exp(1.0776 - (2.30695 - (0.43424 - (0.082433 - (0.008056 - 0.0003146 * z) * z) * z) * z) * z))
    return _jmin(1.0, _jmax(0.0, 1 - below))


def score_fit(sorted_: Sequence[float], spec: Dict[str, Any], k: int, edges: bool = False) -> Dict[str, Any]:
    """How well ``spec`` describes ``sorted_`` (ascending), with ``k`` fitted parameters.

    Returns ``{'ll', 'k', 'aic', 'ks', 'ksP', 'ad', 'adP', 'tested',
    'outside'}``: the log-likelihood and AIC, Kolmogorov-Smirnov's D and
    Anderson-Darling's A² with their p-values, how many realisations the tests
    read, and how many the fit calls impossible (A² and AIC are infinite then).
    With ``edges`` the realisations at probability 0 or 1 -- the extremes a
    maximum-likelihood uniform ends at -- are left out of the tests.
    """
    import numpy as np
    y = _array(sorted_)
    n = len(y)
    dens = [density_at(spec, float(v)) for v in y]
    outside = sum(1 for f in dens if not f > 0)
    ll = _seq_sum(_log_array(dens)) if n else 0.0
    if ll != ll:
        ll = -math.inf
    cums: List[float] = []
    for v in y:
        f = cumulative_at(spec, float(v))
        if edges and (f <= 0 or f >= 1):
            continue
        cums.append(f)
    m = len(cums)
    d = 0.0
    a2 = 0.0
    if m:
        big_f = np.array(cums, dtype=np.float64)
        i = np.arange(m, dtype=np.float64)
        with np.errstate(all='ignore'):
            gaps = np.concatenate(((i + 1) / m - big_f, big_f - i / m))
            d = math.nan if np.isnan(gaps).any() else max(0.0, float(gaps.max()))
            a2 = _seq_sum((2 * i + 1) * (_log_array(big_f) + _log1p_array(-big_f[::-1])))
    a2 = -m - a2 / m if m else math.nan
    if a2 != a2 or a2 == -math.inf:
        a2 = math.inf
    return {
        'll': ll, 'k': k, 'aic': 2 * k - 2 * ll,
        'ks': d, 'ksP': ks_p_value(d, m) if m else math.nan,
        'ad': a2, 'adP': ad_p_value(a2),
        'tested': m, 'outside': outside,
    }


def fit_all(sorted_: Sequence[float], method: str = 'mle') -> List[Dict[str, Any]]:
    """Every shape in :data:`FIT_FAMILIES` fitted by ``method`` and scored.

    Each is ``{'family', 'label', 'method', 'spec', 'note', **score_fit}``, or
    ``{'family', 'label', 'method', 'why'}`` for one that could not be fitted,
    so a table can say what was tried.
    """
    out: List[Dict[str, Any]] = []
    for fam in FIT_FAMILIES:
        got = fit_family(fam['id'], sorted_, method)
        if _truthy(got.get('why')):
            out.append({'family': fam['id'], 'label': fam['label'], 'method': method, 'why': got['why']})
            continue
        score = score_fit(sorted_, got['spec'], fam['params'], edges=bool(got.get('edges', False)))
        out.append({'family': fam['id'], 'label': fam['label'], 'method': method, 'spec': got['spec'],
                    'note': got.get('note'), **score})
    return out


def rank_fits(fits: Sequence[Dict[str, Any]], test: str = 'ad') -> List[Dict[str, Any]]:
    """The fits in order of ``test`` ('ad', 'ks' or 'aic'), best first; the ones that failed last."""
    key = 'ks' if test == 'ks' else 'aic' if test == 'aic' else 'ad'

    def val(f: Dict[str, Any]) -> float:
        v = f.get(key)
        return math.inf if _truthy(f.get('why')) or not _is_finite_num(v) else v

    def compare(a: Dict[str, Any], b: Dict[str, Any]) -> float:
        wa = _truthy(a.get('why'))
        if wa != _truthy(b.get('why')):
            return 1 if wa else -1
        d = val(a) - val(b)
        return 0 if (d != d or d == 0) else d

    return _js_sort(list(fits), compare)


def fit_text(spec: Dict[str, Any]) -> str:
    """A fitted distribution as the model would take it, to four significant figures.

    ``logt(min=0.001,max=10,mode=0.1)``; empty for a kind that is not one.
    """
    meta = _meta(_prop(spec, 'kind'))
    if not meta:
        return ''
    params = spec['params']
    return f"{meta['expr']}({','.join(p['key'] + '=' + _four_figures(params[p['key']]) for p in meta['params'])})"
