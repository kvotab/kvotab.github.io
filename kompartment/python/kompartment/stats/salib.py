"""Global sensitivity analysis: what SALib adds to GlobalSensitivity.jl.

A port of ``src/domain/salib.js``, which ports from SALib 1.6.0 (MIT) what
GlobalSensitivity.jl does not have:

- **PAWN** (:func:`pawn`), which reads any sample: how far the output's
  distribution moves, as a Kolmogorov-Smirnov distance, when one input is held
  to a slice of its range;
- **discrepancy** (:func:`discrepancy_shares`), which reads any sample too: how
  far each input's scatter against the output is from an even spread;
- the **radial one-at-a-time design** (:func:`radial_design`,
  :func:`radial_indices`): elementary effects and Jansen's total index;
- Morris's **trajectories** (:func:`morris_trajectory_design`), with the
  **optimal** selection among candidates by Ruano, Ewald and Kolar's local
  search (:func:`optimal_trajectories`);
- SALib's **bootstrap intervals** on mu*, the Sobol indices and DGSM's nu;
- the fractional factorial's **two-way interactions** and RBD-FAST's bias
  correction.

Everything is in probability space, as in :mod:`kompartment.stats.gsa`. Where
the application differs from SALib it does so on purpose, and so does this:
Morris's levels are the middles of ``p`` equal slices of probability; PAWN's
slice edges are ``i/S``; the interval on Jansen's total index resamples the
base points; discrepancy is read on ranks when it comes from a sample; and the
random draws come from the caller's stream (``next``), not numpy's.

Arrays come back as numpy arrays, results as dictionaries with the
application's keys. Sums are added in the application's order, so the numbers
are its numbers; only the normal quantile of an interval's ``z`` can differ in
the last bit.
"""

from __future__ import annotations

import math
import random
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from ._normal import normal_quantile
from .sensitivity import (
    _col, _div, _f64, _js_floor, _js_max, _js_round, _seqsum, _seqsum_rows, _sqrt,
)

__all__ = [
    'resample_indices', 'ks_statistic', 'pawn', 'DISCREPANCIES', 'discrepancy2d', 'discrepancy_shares',
    'rank_probabilities', 'radial_design', 'radial_indices', 'morris_trajectory', 'trajectory_distance',
    'optimal_trajectories', 'morris_trajectory_design', 'mu_star_interval', 'sobol_bootstrap',
    'ff_interactions', 'unskew', 'dgsm_spread',
]

# `next` is the application's name for a stream of uniforms, kept so the two read alike.
# pylint: disable=redefined-builtin

Next = Callable[[], float]

# ---------------------------------------------------------------------------
# Small things, done as numpy does them.
# ---------------------------------------------------------------------------


def _quantile_sorted(s: np.ndarray, q: float) -> float:
    """numpy's ``quantile(x, q)``, method 'linear', of values already sorted."""
    n = len(s)
    if not n:
        return math.nan
    at = (n - 1) * q
    lo = math.floor(at)
    hi = min(n - 1, lo + 1)
    g = at - lo
    a = float(s[lo])
    b = float(s[hi])
    # numpy's _lerp, which works from the nearer end for accuracy.
    return b - (b - a) * (1 - g) if g >= 0.5 else a + (b - a) * g


def _mean_of(a: np.ndarray) -> float:
    return _div(_seqsum(a), len(a))


def _sd_of(a: np.ndarray, ddof: int = 1) -> float:
    """The standard deviation, over ``n - ddof``."""
    v = _f64(a)
    m = _mean_of(v)
    d = v - m
    return _sqrt(_div(_seqsum(d * d), len(v) - ddof))


def _var_of(a: np.ndarray) -> float:
    """The variance over ``n``, numpy's default."""
    v = _f64(a)
    m = _mean_of(v)
    d = v - m
    return _div(_seqsum(d * d), len(v))


def _median_of(a: Sequence[float]) -> float:
    s = np.sort(_f64(a))
    n = len(s)
    if not n:
        return math.nan
    return float(s[(n - 1) // 2]) if n % 2 else (float(s[n // 2 - 1]) + float(s[n // 2])) / 2


def _z_of(conf: float) -> float:
    """``norm.ppf(0.5 + conf/2)``: the half-width of an interval, in standard deviations."""
    return normal_quantile(0.5 + conf / 2)


def resample_indices(n: int, resamples: int, next: Optional[Next] = None) -> np.ndarray:
    """``resamples`` bootstrap samples of ``n`` indices each, drawn with replacement.

    ``out[r * n + i]``, an ``int32`` array: the layout numpy's
    ``randint(n, size=(resamples, n))`` gives, so numpy's own can be handed in
    instead. The draws are ``floor(next() * n)``, in order.
    """
    nxt = next or random.random
    total = max(0, int(n) * int(resamples))
    out = np.empty(total, dtype=np.int32)
    top = n - 1
    for i in range(total):
        out[i] = min(top, math.floor(nxt() * n))
    return out


# ---------------------------------------------------------------------------
# From a sample: PAWN.
# ---------------------------------------------------------------------------


def ks_statistic(a: Sequence[float], b: Sequence[float]) -> float:
    """The two-sample Kolmogorov-Smirnov statistic, scipy's ``ks_2samp(a, b).statistic``.

    The largest gap between the two empirical CDFs, each taken from the right
    at every value either sample holds; NaN when either is empty.
    """
    x = np.sort(_f64(a))
    z = np.sort(_f64(b))
    n1 = len(x)
    n2 = len(z)
    if not n1 or not n2:
        return math.nan
    pooled = np.concatenate([x, z])
    i = np.searchsorted(x, pooled, side='right')
    j = np.searchsorted(z, pooled, side='right')
    d = np.abs(i / n1 - j / n2)
    return float(min(1.0, max(0.0, float(d.max()))))


def pawn(x: Sequence[float], y: Sequence[float], *, slides: Any = 10) -> Dict[str, Any]:
    """PAWN for one input: the KS distance of the output in each slice of the input from the whole.

    ``slides`` slices, each an equal share of the sample by the input's
    quantiles, half open, so the largest value of the input is in none. Returns
    ``{'minimum', 'mean', 'median', 'maximum', 'cv', 'stdev', 'ks'}``, the
    statistics over the slices (the median is the one usually reported) and
    ``ks`` per slice, NaN where a slice holds nothing.
    """
    xv = _f64(x)
    yv = _f64(y)
    # A slice takes y[r] for each r of x, NaN past y's end; the distance is to the whole of y.
    yr = _col(yv, len(xv))
    S = _js_max(1, _js_round(slides))
    if not math.isfinite(S):
        S = 0
    S = int(S)
    step = _div(1, S)
    s = np.sort(xv)
    edges = [_quantile_sorted(s, min(1.0, i * step)) for i in range(S + 1)]
    ks = np.full(S, math.nan)
    for k in range(S):
        sel = yr[(xv >= edges[k]) & (xv < edges[k + 1])]
        if len(sel):
            ks[k] = ks_statistic(sel, yv)
    got = ks[~np.isnan(ks)]
    if not len(got):
        return {'minimum': math.nan, 'mean': math.nan, 'median': math.nan, 'maximum': math.nan,
                'cv': math.nan, 'stdev': math.nan, 'ks': ks}
    m = _mean_of(got)
    stdev = _sd_of(got, 0)
    return {
        'minimum': float(got.min()), 'mean': m, 'median': _median_of(got), 'maximum': float(got.max()),
        'cv': _div(stdev, m), 'stdev': stdev, 'ks': ks,
    }


# ---------------------------------------------------------------------------
# From a sample: discrepancy.
# ---------------------------------------------------------------------------

#: The kinds of discrepancy :func:`discrepancy2d` computes, as scipy's ``qmc.discrepancy``.
DISCREPANCIES = ['WD', 'CD', 'MD', 'L2-star']


def _pair_sum(n: int, term: Callable[[slice], np.ndarray], chunk: int = 2_000_000) -> float:
    """The double sum over i then j of ``term``, added in that order, a block of rows at a time."""
    total = 0.0
    rows = max(1, chunk // max(1, n))
    for i0 in range(0, n, rows):
        block = term(slice(i0, min(n, i0 + rows))).ravel()
        total = float(np.cumsum(np.concatenate(([total], block)))[-1])
    return total


def discrepancy2d(u: Sequence[float], v: Sequence[float], method: str = 'WD') -> float:
    """The discrepancy of the points ``(u[i], v[i])`` in the unit square: scipy's ``qmc.discrepancy``.

    ``'CD'``, ``'WD'`` and ``'MD'`` come back squared, as scipy returns them;
    ``'L2-star'`` as the root of the square, as it returns that one. Any other
    name is ``'WD'``. NaN for no points.
    """
    uu = _f64(u)
    vv = _f64(v)
    n = len(uu)
    if not n:
        return math.nan
    with np.errstate(all='ignore'):
        if method == 'CD':
            a = np.abs(uu - 0.5)
            b = np.abs(vv - 0.5)
            one = _seqsum((1 + 0.5 * a - 0.5 * a * a) * (1 + 0.5 * b - 0.5 * b * b))

            def cd(rows: slice) -> np.ndarray:
                ai = a[rows, None]
                bi = b[rows, None]
                return ((1 + 0.5 * ai + 0.5 * a[None, :] - 0.5 * np.abs(uu[rows, None] - uu[None, :]))
                        * (1 + 0.5 * bi + 0.5 * b[None, :] - 0.5 * np.abs(vv[rows, None] - vv[None, :])))

            pair = _pair_sum(n, cd)
            return (13 / 12) * (13 / 12) - (2 / n) * one + pair / (n * n)
        if method == 'MD':
            a = np.abs(uu - 0.5)
            b = np.abs(vv - 0.5)
            one = _seqsum((5 / 3 - 0.25 * a - 0.25 * a * a) * (5 / 3 - 0.25 * b - 0.25 * b * b))

            def md(rows: slice) -> np.ndarray:
                du = np.abs(uu[rows, None] - uu[None, :])
                dv = np.abs(vv[rows, None] - vv[None, :])
                return ((15 / 8 - 0.25 * a[rows, None] - 0.25 * a[None, :] - 0.75 * du + 0.5 * du * du)
                        * (15 / 8 - 0.25 * b[rows, None] - 0.25 * b[None, :] - 0.75 * dv + 0.5 * dv * dv))

            pair = _pair_sum(n, md)
            return (19 / 12) * (19 / 12) - (2 / n) * one + pair / (n * n)
        if method == 'L2-star':
            one = _seqsum((1 - uu * uu) * (1 - vv * vv))

            def l2(rows: slice) -> np.ndarray:
                return ((1 - np.maximum(uu[rows, None], uu[None, :]))
                        * (1 - np.maximum(vv[rows, None], vv[None, :])))

            pair = _pair_sum(n, l2)
            return _sqrt(_js_max(0, (1 / 3) * (1 / 3) - ((2 ** (1 - 2)) / n) * one + pair / (n * n)))

        def wd(rows: slice) -> np.ndarray:
            du = np.abs(uu[rows, None] - uu[None, :])
            dv = np.abs(vv[rows, None] - vv[None, :])
            return (1.5 - du * (1 - du)) * (1.5 - dv * (1 - dv))

        pair = _pair_sum(n, wd)
        return -((4 / 3) * (4 / 3)) + pair / (n * n)


def discrepancy_shares(us: Sequence[Sequence[float]], y: Sequence[float], method: str = 'WD') -> Dict[str, np.ndarray]:
    """Each input's share of the discrepancy, SALib's ``discrepancy.analyze``.

    ``us`` holds one column per input, each in [0, 1]; ``y`` is the output,
    scaled onto [0, 1] by its extremes here. Returns ``{'shares', 'raw'}``.
    """
    yv = _f64(y)
    # Math.min and Math.max over the output: one NaN makes both NaN.
    if np.isnan(yv).any():
        lo = hi = math.nan
    else:
        lo = float(yv.min()) if len(yv) else math.inf
        hi = float(yv.max()) if len(yv) else -math.inf
    with np.errstate(all='ignore'):
        v = (yv - lo) / (hi - lo)
    raw = np.array([discrepancy2d(u, v, method) for u in us], dtype=np.float64)
    total = _seqsum(raw)
    with np.errstate(all='ignore'):
        return {'shares': raw / total, 'raw': raw}


def rank_probabilities(x: Sequence[float]) -> np.ndarray:
    """A sample's column as probabilities: its average ranks over ``n``, less a half.

    ``[3, 1, 2, 2]`` reads ``[0.875, 0.125, 0.5, 0.5]``. What discrepancy is
    read on when it comes from a sample, since ranks are uniform whatever the
    distribution.
    """
    xv = _f64(x)
    n = len(xv)
    out = np.zeros(n)
    if not n:
        return out
    order = np.argsort(xv, kind='stable')
    s = xv[order]
    change = np.empty(n, dtype=bool)
    change[0] = True
    change[1:] = s[1:] != s[:-1]
    starts = np.flatnonzero(change)
    ends = np.append(starts[1:], n) - 1
    r = (starts + ends) / 2 + 0.5
    out[order] = np.repeat(r / n, ends - starts + 1)
    return out


# ---------------------------------------------------------------------------
# The radial one-at-a-time design, Campolongo, Saltelli and Cariboni 2011.
# ---------------------------------------------------------------------------


def _columns_of(cols: Sequence[Sequence[float]], K: int, N: int) -> np.ndarray:
    out = np.full((K, N), math.nan)
    for k in range(min(K, len(cols))):
        c = _f64(cols[k])
        t = min(N, len(c))
        out[k, :t] = c[:t]
    return out


def radial_design(K: int, base: Sequence[Sequence[float]], step: Sequence[Sequence[float]]) -> Dict[str, Any]:
    """The radial design: each of ``N`` base points run as it is, then once per input moved to its perturbation point.

    ``base`` and ``step`` hold one column of ``N`` probabilities per input.
    ``N (K + 1)`` runs; ``u`` is a K x runs array, row k input k's probabilities.
    """
    N = len(base[0]) if len(base) else 0
    per = K + 1
    b = _columns_of(base, K, N)
    s = _columns_of(step, K, N)
    u = np.repeat(b, per, axis=1) if N else np.zeros((K, 0))
    for k in range(K):
        u[k, np.arange(N) * per + 1 + k] = s[k]
    return {'method': 'radial', 'K': K, 'N': N, 'per': per, 'base': b, 'step': s, 'u': u, 'runs': N * per}


def radial_indices(y: Sequence[float], design: Dict[str, Any], *, resamples: int = 100, conf: float = 0.95,
                   next: Optional[Next] = None, indices: Optional[Sequence[int]] = None,
                   st_indices: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """The elementary effects and Jansen's total indices of a radial design, with bootstrap intervals.

    The resamples, ``resample_indices(N, resamples, next)``, are drawn unless
    ``indices`` gives them (``st_indices`` for S_T's own, which default to the
    same). Returns ``{'mu', 'muStar', 'sigma', 'muStarCi', 'ST', 'STci',
    'effects'}``; the intervals are NaN with fewer than two resamples.
    """
    K = design['K']
    N = design['N']
    per = design['per']
    base = _f64(design['base'])
    step = _f64(design['step'])
    yv = _f64(y)
    if len(yv) < N * per:
        yv = _col(yv, N * per)
    at = np.arange(N) * per
    yb = yv[at] if N else np.zeros(0)
    d = np.zeros((K, N))
    ee = np.zeros((K, N))
    with np.errstate(all='ignore'):
        for k in range(K):
            d[k] = yb - yv[at + 1 + k]
            # numpy's nan_to_num: nothing for a 0/0, the largest number for a division by zero.
            ee[k] = np.nan_to_num(d[k] / (base[k] - step[k]))
    R = int(resamples)
    idx = None
    idx_t = None
    if R > 1:
        idx = np.asarray(indices, dtype=np.int64) if indices is not None else resample_indices(N, R, next)
        idx_t = np.asarray(st_indices, dtype=np.int64) if st_indices is not None else idx
        idx = idx[:R * N].reshape(R, N)
        idx_t = idx_t[:R * N].reshape(R, N)
    z = _z_of(conf)
    var_b = _var_of(yb)
    mu = np.zeros(K)
    mu_star = np.zeros(K)
    sigma = np.zeros(K)
    mu_star_ci = np.full(K, math.nan)
    ST = np.zeros(K)
    ST_ci = np.full(K, math.nan)
    with np.errstate(all='ignore'):
        for k in range(K):
            mu[k] = _mean_of(ee[k])
            mu_star[k] = _mean_of(np.abs(ee[k]))
            sigma[k] = _sd_of(ee[k], 1)
            sq = d[k] * d[k]
            ST[k] = _div(_div(_seqsum(sq), 2 * N), var_b)
            if idx is None:
                continue
            a = _seqsum_rows(np.abs(ee[k])[idx]) / N
            mu_star_ci[k] = z * _sd_of(a, 1)
            # Resampled whole: the base point, its perturbation, and so the
            # variance the index is a share of.
            sums = _seqsum_rows(sq[idx_t])
            varb = np.array([_var_of(row) for row in yb[idx_t]])
            a = (sums / (2 * N)) / varb
            ST_ci[k] = z * _sd_of(a, 1)
    return {'mu': mu, 'muStar': mu_star, 'sigma': sigma, 'muStarCi': mu_star_ci, 'ST': ST, 'STci': ST_ci,
            'effects': ee}


# ---------------------------------------------------------------------------
# Morris's trajectories, as SALib samples them.
# ---------------------------------------------------------------------------


def _int_if_whole(v: float) -> Any:
    return int(v) if isinstance(v, float) and v.is_integer() else v


def morris_trajectory(K: int, p: int, next: Next) -> List[List[Any]]:
    """One trajectory, in levels (0 to ``p - 1``): ``K + 1`` rows of ``K``.

    Each input moves once, in a random order and a random direction, by half
    the levels, from a start in the lower half (or the upper, for a step down).
    The draws: the order (Fisher-Yates from the end), then the directions, then
    the starts.
    """
    half = _int_if_whole(p / 2)
    order = list(range(K))
    for i in range(K - 1, 0, -1):
        j = math.floor(next() * (i + 1))
        order[i], order[j] = order[j], order[i]
    direction = [-1 if next() < 0.5 else 1 for _ in range(K)]
    start = [_js_floor(next() * half) for _ in range(K)]
    at = list(start)
    for k in range(K):
        if direction[k] < 0:
            at[k] += half
    rows = [list(at)]
    for k in order:
        at[k] += direction[k] * half
        rows.append(list(at))
    return rows


def trajectory_distance(m: Sequence[Sequence[float]], l: Sequence[Sequence[float]]) -> float:  # noqa: E741
    """SALib's distance between two trajectories: every point of one to every point of the other, summed.

    Euclidean, and held in single precision as SALib holds its distance
    matrix, so a tie is broken where SALib breaks it. Zero for two identical
    trajectories.
    """
    a = _f64(m)
    b = _f64(l)
    if a.ndim != 2 or b.ndim != 2 or not a.size or not b.size:
        return _distance_loop(m, l)
    diff = a[:, None, :] - b[None, :, :]
    q = np.cumsum(diff * diff, axis=2)[:, :, -1] if diff.shape[2] else np.zeros(diff.shape[:2])
    s = _seqsum(np.sqrt(q).ravel())
    same = a.shape == b.shape and bool(np.all(a == b))
    return 0.0 if same else float(np.float32(s))


def _distance_loop(m: Sequence[Sequence[float]], l: Sequence[Sequence[float]]) -> float:  # noqa: E741
    """:func:`trajectory_distance` for ragged input, element by element."""
    s = 0.0
    same = len(m) == len(l)
    for ra in range(len(m)):
        for rb in range(len(l)):
            q = 0.0
            for k in range(len(m[ra])):
                t = m[ra][k] - (l[rb][k] if k < len(l[rb]) else math.nan)
                q += t * t
            s += _sqrt(q)
        if same:
            for k in range(len(m[ra])):
                if k >= len(l[ra]) or m[ra][k] != l[ra][k]:
                    same = False
    return 0.0 if same else float(np.float32(s))


def _distance_matrix(candidates: Sequence[Sequence[Sequence[float]]], chunk: int = 2_000_000) -> np.ndarray:
    """:func:`trajectory_distance` between every two candidates, symmetric, zero on the diagonal.

    Candidates of one shape are measured against all the later ones at once,
    each distance summed in the same order as one at a time.
    """
    N = len(candidates)
    D = np.zeros((N, N))
    try:
        C = np.array(candidates, dtype=np.float64)
    except ValueError:
        C = None
    if C is None or C.ndim != 3 or not C.shape[1] or not C.shape[2]:
        for j in range(N):
            for l in range(j + 1, N):  # noqa: E741
                d = trajectory_distance(candidates[j], candidates[l])
                D[j, l] = d
                D[l, j] = d
        return D
    rows, K = C.shape[1], C.shape[2]
    step = max(1, chunk // (rows * rows * K))
    with np.errstate(all='ignore'):
        for j in range(N - 1):
            m = C[j]
            for l0 in range(j + 1, N, step):
                other = C[l0:min(N, l0 + step)]
                diff = m[None, :, None, :] - other[:, None, :, :]
                q = np.cumsum(diff * diff, axis=3)[:, :, :, -1]
                s = np.cumsum(np.sqrt(q).reshape(len(other), -1), axis=1)[:, -1]
                same = np.all((other == m[None, :, :]).reshape(len(other), -1), axis=1)
                d = np.where(same, 0.0, s.astype(np.float32).astype(np.float64))
                D[j, l0:l0 + len(other)] = d
                D[l0:l0 + len(other), j] = d
    return D


def _spreads(sets: np.ndarray, D: np.ndarray) -> np.ndarray:
    """SALib's ``sum_distances`` of each row of ``sets``: the root of the summed squared pair distances."""
    size = sets.shape[1]
    ia, ib = np.triu_indices(size, 1)
    if not len(ia):
        return np.zeros(len(sets))
    vals = D[sets[:, ia], sets[:, ib]]
    return np.sqrt(np.cumsum(vals * vals, axis=1)[:, -1])


def _last_max(values: Sequence[float]) -> int:
    """The position of the largest, the last of equals, as numpy's ``argsort()[-1]`` has it."""
    best = 0
    for i in range(1, len(values)):
        if values[i] >= values[best]:
            best = i
    return best


def optimal_trajectories(candidates: Sequence[Sequence[Sequence[float]]], k: int) -> List[int]:
    """The ``k`` most spread-out of the candidate trajectories: SALib's ``LocalOptimisation``, Ruano et al. 2012.

    ``candidates`` are trajectories, each ``K + 1`` rows of ``K``. Returns which
    candidates, ascending; every one when ``k`` is not below their number.
    """
    N = len(candidates)
    if k >= N:
        return list(range(N))
    D = _distance_matrix(candidates)
    by_row = [np.argsort(D[r], kind='stable') for r in range(N)]
    tried: List[List[int]] = []
    scores: List[float] = []
    for i in range(1, k):
        # Each row's i farthest, and the row itself.
        sets = np.array([list(order[N - i:][::-1]) + [r] for r, order in enumerate(by_row)], dtype=np.int64)
        best = list(sets[_last_max(_spreads(sets, D))])
        for _ in range(1, k - i):
            rest = [c for c in range(N) if c not in best]
            grown = np.array([best + [c] for c in rest], dtype=np.int64)
            best = list(grown[_last_max(_spreads(grown, D))])
        tried.append([int(c) for c in best])
        scores.append(float(_spreads(np.array([best], dtype=np.int64), D)[0]))
    if not tried:
        # The application spreads tried[lastMax([])], which is undefined, and throws.
        raise TypeError('undefined is not iterable: fewer than two trajectories to keep among candidates')
    return sorted(tried[_last_max(scores)])


def morris_trajectory_design(K: int, *, trajectories: int = 10, levels: int = 4, candidates: Any = 0,
                             next: Next) -> Dict[str, Any]:
    """A design of Morris trajectories, ``K + 1`` runs each, at the middles of the level slices.

    With ``candidates`` above the number wanted, that many are drawn and the
    most spread out kept. ``u`` is a K x runs array.
    """
    p = _js_max(2, 2 * _js_round(levels / 2))
    c = _js_round(candidates) if candidates is not None else 0
    drawn = int(_js_max(trajectories, c if c == c and c else 0))
    everyone = [morris_trajectory(K, p, next) for _ in range(drawn)]
    keep = optimal_trajectories(everyone, trajectories) if drawn > trajectories else list(range(drawn))
    points = K + 1
    u = np.zeros((K, len(keep) * points))
    for t, which in enumerate(keep):
        rows = np.array(everyone[which], dtype=np.float64).reshape(points, K)
        u[:, t * points:(t + 1) * points] = ((rows + 0.5) / p).T
    return {
        'method': 'morris', 'design': 'trajectories', 'K': K, 'trajectories': len(keep), 'points': points,
        'levels': p, 'candidates': drawn, 'u': u, 'runs': len(keep) * points,
    }


def mu_star_interval(effects: Sequence[Sequence[float]], *, resamples: int = 100, conf: float = 0.95,
                     next: Optional[Next] = None,
                     indices: Optional[Callable[[int, int], Sequence[int]]] = None) -> np.ndarray:
    """The bootstrap interval on mu*, SALib's: each input's elementary effects resampled with replacement.

    ``indices(k, n)`` gives input k's resamples (``r * n + i``); otherwise they
    are drawn from ``next``, input by input. NaN for fewer than two effects or
    resamples. Returns the half-widths.
    """
    z = _z_of(conf)
    out = np.zeros(len(effects))
    for k, e in enumerate(effects):
        ev = np.abs(_f64(e))
        n = len(ev)
        if n < 2 or resamples < 2:
            out[k] = math.nan
            continue
        idx = np.asarray(indices(k, n) if indices else resample_indices(n, resamples, next), dtype=np.int64)
        at = _seqsum_rows(ev[idx[:resamples * n].reshape(resamples, n)]) / n
        out[k] = z * _sd_of(at, 1)
    return out


# ---------------------------------------------------------------------------
# Sobol's indices: SALib's bootstrap interval.
# ---------------------------------------------------------------------------


def sobol_bootstrap(y: Sequence[float], design: Dict[str, Any], *, resamples: int = 100, conf: float = 0.95,
                    next: Optional[Next] = None,
                    indices: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """SALib's bootstrap interval on the Sobol indices of a one-block Saltelli design.

    The runs are resampled row by row -- the same rows of A, B and every A_B --
    and the indices worked out again from each resample, on the output
    standardised as SALib standardises it. ``design`` needs ``K``, ``n`` and
    ``second``. The resamples are read as ``indices[i * resamples + r]`` (numpy's
    ``randint(n, size=(n, resamples))``, which is how SALib draws them) and
    drawn from ``next`` when not given. Returns ``{'S1ci', 'STci', 'S2ci'}``,
    the half-widths; ``S2ci`` is K x K flattened, the upper triangle filled.
    """
    K = design['K']
    n = design['n']
    second = bool(design.get('second', False))
    R = int(resamples)
    idx = np.asarray(indices, dtype=np.int64) if indices is not None else resample_indices(n, R, next)
    per = (2 * K + 2 if second else K + 2) * n
    yv = _f64(y)
    if len(yv) < per:
        yv = _col(yv, per)
    head = yv[:per]
    m = _mean_of(head)
    sd = math.sqrt(_var_of(head))
    with np.errstate(all='ignore'):
        Y = (yv - m) / sd
    z = _z_of(conf)
    # rows[r] are the resample's row numbers, in order: idx[i * R + r].
    rows = idx[:n * R].reshape(n, R).T

    def block(c: int) -> np.ndarray:
        return Y[c * n:(c + 1) * n][rows]

    A = block(0)
    B = block(1)
    with np.errstate(all='ignore'):
        s = _seqsum_rows(A + B)
        mean = s / (2 * n)
        dA = A - mean[:, None]
        dB = B - mean[:, None]
        var = _seqsum_rows(dA * dA + dB * dB) / (2 * n)

        def first(ab: np.ndarray) -> np.ndarray:
            return (_seqsum_rows(B * (ab - A)) / n) / var

        S1ci = np.zeros(K)
        STci = np.zeros(K)
        for k in range(K):
            ab = block(2 + k)
            S1ci[k] = z * _sd_of(first(ab), 1)
            dd = A - ab
            t = ((0.5 * _seqsum_rows(dd * dd)) / n) / var
            STci[k] = z * _sd_of(t, 1)
        S2ci = None
        if second:
            S2ci = np.full(K * K, math.nan)
            for j in range(K):
                ba = block(2 + K + j)
                fj = first(block(2 + j))
                for k in range(j + 1, K):
                    ab = block(2 + k)
                    s2 = (_seqsum_rows(ba * ab - A * B) / n) / var - fj - first(ab)
                    S2ci[j * K + k] = z * _sd_of(s2, 1)
    return {'S1ci': S1ci, 'STci': STci, 'S2ci': S2ci}


# ---------------------------------------------------------------------------
# The fractional factorial's interactions, RBD-FAST's bias, DGSM's spread.
# ---------------------------------------------------------------------------


def ff_interactions(y: Sequence[float], design: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every pair's two-way interaction effect, SALib's ``ff.interactions``.

    The output's contrast with the product of the two inputs' signs, from a
    design of :func:`kompartment.stats.gsa.ff_design`. In a design of resolution
    IV each is aliased with others, but clear of the main effects. Rows
    ``{'a', 'b', 'value'}``, ``b`` outer and ``a < b`` inner.
    """
    K = design['K']
    rows = design['rows']
    signs = np.asarray(design['signs'], dtype=np.float64)
    yv = _f64(y)[:rows]
    out = []
    for b in range(K):
        for a in range(b):
            out.append({'a': a, 'b': b, 'value': _seqsum(yv * signs[:rows, a] * signs[:rows, b]) / rows})
    return out


def unskew(S1: float, M: float, N: float) -> float:
    """Tissot and Prieur's correction of an RBD-FAST first-order index, SALib's ``unskew_S1``.

    ``M`` is the harmonics and ``N`` the runs.
    """
    lam = _div(2 * M, N)
    return S1 - _div(lam, 1 - lam) * (1 - S1)


def dgsm_spread(g: Sequence[float], K: int, N: int, *, resamples: int = 100, conf: float = 0.95,
                next: Optional[Next] = None,
                indices: Optional[Callable[[int], Sequence[int]]] = None) -> Dict[str, np.ndarray]:
    """The spread of DGSM's squared derivatives and SALib's interval on their mean, nu.

    ``g[i * K + k]`` as :func:`kompartment.stats.gsa.dgsm_derivatives` gives
    them. Returns ``{'sd', 'ci'}``: numpy's standard deviation (over n) of the
    squared derivative, and the half-width of the interval on its mean from the
    points resampled -- ``indices(k)``, or drawn afresh for each input from
    ``next`` as SALib draws them. The interval is NaN with fewer than two
    resamples.
    """
    gv = _f64(g)
    sd = np.zeros(K)
    ci = np.full(K, math.nan)
    z = _z_of(conf)
    for k in range(K):
        col = gv[np.arange(N) * K + k] if N else np.zeros(0)
        sq = col * col
        sd[k] = _sqrt(_var_of(sq))
        if resamples < 2:
            continue
        idx = np.asarray(indices(k) if indices else resample_indices(N, resamples, next), dtype=np.int64)
        at = _seqsum_rows(sq[idx[:resamples * N].reshape(resamples, N)]) / N
        ci[k] = z * _sd_of(at, 1)
    return {'sd': sd, 'ci': ci}
