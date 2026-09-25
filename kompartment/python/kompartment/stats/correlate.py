"""Making sampled inputs move together, as Kompartment does it: Iman and Conover (1982).

A port of the application's ``src/domain/correlate.js``. A probabilistic run
draws every distributed input on a stream of its own, so two inputs are
independent unless the model says otherwise. The model says so in its
simulation settings::

    "correlations": [
      {"a": "Kd[Tc-99]", "b": "Kd[I-129]", "r": 0.8},
      {"group": "Kd", "r": 0.9}
    ]

-- a *pair* names two sampled inputs as the sampling plan spells them, a
*group* correlates every sampled index of one parameter with every other.

Iman-Conover *permutes* each correlated column so that the columns' ranks
correlate as the target matrix says. Nothing about any one column changes --
the same strata, the same values, the same marginal -- only which realisation
gets which, so every input outside a pair keeps exactly the draws it had. For
the ``K`` columns in some pair:

1. scores: van der Waerden scores ``probit(i/(N+1))``, shuffled per column on
   a stream named for the input;
2. ``E``, the correlation the scores have, and its Cholesky factor ``F``; the
   target ``C`` and its factor ``P``;
3. ``T = S (P F^-1)^T``, whose rank correlation is ``C``;
4. each column reordered so its ranks are those of its column of ``T``.

A target that no set of inputs could have (A-B 0.9, B-C 0.9, A-C -0.9) is moved
to the nearest correlation matrix first, and how far it moved is returned.

The arithmetic is the application's, in the same order, so the same seed gives
the same permutation.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from ._normal import probit
from .pdf import _MISSING, _div, _jmax, _js_str, _nullish, _prop, _sqrt, _to_number, _truthy
from .sample import Mulberry32, stream_for

__all__ = ['correlation_pairs', 'iman_conover', 'describe_correlation']


def _simulation_of(project: Any) -> Any:
    """``project?.simulation``: from a model dictionary, or anything with ``.raw`` or ``.simulation``."""
    if isinstance(project, Mapping):
        return project.get('simulation', _MISSING)
    raw = getattr(project, 'raw', None)
    if isinstance(raw, Mapping):
        return raw.get('simulation', _MISSING)
    sim = getattr(project, 'simulation', _MISSING)
    raw = getattr(sim, 'raw', None)
    return raw if isinstance(raw, Mapping) else sim


def _or_q(v: Any) -> str:
    """``${v ?? '?'}``."""
    return '?' if _nullish(v) else _js_str(v)


def correlation_pairs(project: Any, names: Sequence[str]) -> Dict[str, List[Any]]:
    """The pairs a model asks for, read off ``simulation.correlations``.

    ``names`` are every sampled input, as the sampling plan spells them
    (``slotName``: ``Kd[Tc-99]``). A pair names two of them; a group
    (``{'group': 'Kd', 'r': 0.9}``) correlates every one of the parameter's
    sampled indices with every other.

    Returns ``{'pairs': [{'a', 'b', 'r'}], 'problems': [str]}``: pairs by
    position in ``names``, ``a < b``, and what was ignored and why -- a
    coefficient outside [-1, 1], a name that is not sampled, an input paired
    with itself, a group with fewer than two members, a pair given twice (the
    first coefficient is kept).
    """
    names = list(names)
    at: Dict[Any, int] = {}
    for k, n in enumerate(names):
        at[n] = k
    pairs: List[Dict[str, Any]] = []
    problems: List[str] = []
    seen = set()

    def add(i: int, j: int, r: float, where: str) -> None:
        if i == j:
            problems.append(f'{where}: an input cannot be correlated with itself.')
            return
        key = (i, j) if i < j else (j, i)
        if key in seen:
            problems.append(f'{where}: {_js_str(names[i])} and {_js_str(names[j])} are correlated twice; '
                            'the first coefficient is kept.')
            return
        seen.add(key)
        pairs.append({'a': min(i, j), 'b': max(i, j), 'r': r})

    correlations = _prop(_simulation_of(project), 'correlations')
    for c in ([] if _nullish(correlations) else correlations):
        r_raw = _prop(c, 'r')
        r = _to_number(r_raw)
        group = _prop(c, 'group')
        where = (f'group {_js_str(group)}' if _truthy(group)
                 else f"{_or_q(_prop(c, 'a'))} – {_or_q(_prop(c, 'b'))}")
        if not math.isfinite(r) or r < -1 or r > 1:
            problems.append(f'{where}: a correlation is a number between -1 and 1, not {_js_str(r_raw)}.')
            continue
        if not _nullish(group):
            # Every sampled index of the parameter: `Kd[...]`, and the bare name
            # for a parameter with no index -- which has one slot, and is said.
            prefix = f'{_js_str(group)}['
            members = [k for k, n in enumerate(names)
                       if isinstance(n, str) and ((isinstance(group, str) and n == group) or n.startswith(prefix))]
            if len(members) < 2:
                problems.append(f"{where}: {'only one' if len(members) == 1 else 'no'} sampled "
                                'index carries that name, so there is nothing to correlate it with.')
                continue
            for x in range(len(members)):
                for y in range(x + 1, len(members)):
                    add(members[x], members[y], r, where)
            continue
        a = _prop(c, 'a')
        b = _prop(c, 'b')
        i = at.get(_js_str(a))
        j = at.get(_js_str(b))
        if i is None or j is None:
            missing = [v for v in (a if i is None else None, b if j is None else None) if _truthy(v)]
            problems.append(f"{where}: {' and '.join(_js_str(v) for v in missing)} "
                            f"{'is' if len(missing) == 1 else 'are'} "
                            'not a sampled input of this model (spelled as in the sampling plan, '
                            'e.g. Kd[Tc-99]).')
            continue
        add(i, j, r, where)
    return {'pairs': pairs, 'problems': problems}


def _seq_sum(values: Any) -> float:
    """``s = 0; for (v of values) s += v``: a sum in order, as the application adds."""
    import numpy as np
    if len(values) == 0:
        return 0.0
    with np.errstate(all='ignore'):
        return float(np.cumsum(np.concatenate(([0.0], values)))[-1])


def _typed_sort(values: Any) -> Any:
    """``Float64Array.from(values).sort()``: ascending, -0 before +0, NaN last."""
    import numpy as np
    s = np.sort(np.array(values, dtype=np.float64), kind='stable')
    zeros = np.flatnonzero(s == 0)
    if zeros.size:
        negative = int(np.signbit(s[zeros]).sum())
        s[zeros[:negative]] = -0.0
        s[zeros[negative:]] = 0.0
    return s


def iman_conover(columns: List[Any], pairs: Sequence[Mapping[str, Any]], names: Sequence[str],
                 seed: Any) -> Dict[str, Any]:
    """Reorders the correlated columns in place so their ranks correlate as asked.

    ``columns`` are one per sampled input, ``n`` long each (numpy arrays or
    lists, changed in place); ``pairs`` from :func:`correlation_pairs`;
    ``names`` what each column is called, which names its score stream;
    ``seed`` the run's seed.

    Returns ``{'columns': [...], 'adjusted': x}``: which columns moved, and
    the largest change the target matrix needed to become a correlation
    matrix (0 when it already was one). Nothing moves with no pairs, or with
    fewer than three realisations.
    """
    import numpy as np
    if not pairs:
        return {'columns': [], 'adjusted': 0}
    n = len(columns[0]) if len(columns) else 0
    # Two realisations cannot carry a correlation, and one cannot be ranked.
    if n < 3:
        return {'columns': [], 'adjusted': 0}

    involved = sorted({k for p in pairs for k in (p['a'], p['b'])})
    size = len(involved)
    pos = {k: i for i, k in enumerate(involved)}

    # The target, and the nearest correlation matrix to it when it is not one.
    target = _identity(size)
    for p in pairs:
        i = pos[p['a']]
        j = pos[p['b']]
        r = _to_number(p['r'])
        target[i * size + j] = r
        target[j * size + i] = r
    adjusted = _nearest_correlation(target, size)
    chol_target = _cholesky(target, size)

    # Scores: normal quantiles of evenly spaced probabilities, shuffled on a
    # stream named for the input.
    base = [probit((i + 1) / (n + 1)) for i in range(n)]
    scores = np.empty((n, size), dtype=np.float64)
    for j in range(size):
        k = involved[j]
        name = names[k] if 0 <= k < len(names) else _MISSING
        nxt = stream_for(seed, f'correlation:{_js_str(name)}')
        col = list(base)
        picks = _fisher_yates_picks(nxt, n)
        for step, i in enumerate(range(n - 1, 0, -1)):
            t = picks[step]
            col[i], col[t] = col[t], col[i]
        scores[:, j] = col

    # What the scores correlate to by accident, taken out; what is wanted, put
    # in: T = S (P F^-1)^T.
    chol_scores = _cholesky(_correlation_of(scores, n, size), size)
    inv = _invert_lower(chol_scores, size)
    m = [0.0] * (size * size)  # P F^-1
    for i in range(size):
        for j in range(size):
            s = 0.0
            for l in range(size):
                s += chol_target[i * size + l] * inv[l * size + j]
            m[i * size + j] = s
    t_mat = np.empty((n, size), dtype=np.float64)
    with np.errstate(all='ignore'):
        for i in range(size):
            s = np.zeros(n, dtype=np.float64)
            for j in range(size):
                s = s + scores[:, j] * m[i * size + j]
            t_mat[:, i] = s

    # Each input takes the rank pattern of its column of T: the realisation
    # holding the largest score gets the input's largest value, and so on.
    for j in range(size):
        col = columns[involved[j]]
        ordered = _typed_sort(col)
        order = np.argsort(t_mat[:, j], kind='stable')
        if isinstance(col, np.ndarray):
            col[order] = ordered
        else:
            for rank, where in enumerate(order.tolist()):
                col[where] = float(ordered[rank])
    return {'columns': involved, 'adjusted': adjusted}


def _fisher_yates_picks(nxt: Any, n: int) -> List[int]:
    """The ``j`` of each Fisher-Yates step, ``i`` from ``n - 1`` down to 1: ``floor(next() * (i + 1))``."""
    import numpy as np
    if n < 2:
        return []
    if isinstance(nxt, Mulberry32):
        return np.floor(nxt.take(n - 1) * np.arange(n, 1, -1, dtype=np.float64)).astype(np.int64).tolist()
    return [math.floor(nxt() * (i + 1)) for i in range(n - 1, 0, -1)]


def _identity(size: int) -> List[float]:
    """The identity of order ``size``, flat, row-major."""
    out = [0.0] * (size * size)
    for i in range(size):
        out[i * size + i] = 1.0
    return out


def _correlation_of(scores: Any, n: int, size: int) -> List[float]:
    """The sample correlation matrix of the columns of ``scores`` (n x size), flat."""
    import numpy as np
    mean = [_seq_sum(scores[:, j]) / n for j in range(size)]
    cov = [0.0] * (size * size)
    with np.errstate(all='ignore'):
        for i in range(size):
            di = scores[:, i] - mean[i]
            for j in range(i, size):
                cov[i * size + j] = _seq_sum(di * (scores[:, j] - mean[j]))
    out = [0.0] * (size * size)
    for i in range(size):
        for j in range(i, size):
            c = _div(cov[i * size + j], math.sqrt(cov[i * size + i] * cov[j * size + j]))
            out[i * size + j] = c
            out[j * size + i] = c
    return out


def _cholesky(a: List[float], size: int) -> List[float]:
    """Cholesky, lower triangular, flat; a pivot below 1e-12 is floored there (rounding, not repair)."""
    low = [0.0] * (size * size)
    for i in range(size):
        for j in range(i + 1):
            s = a[i * size + j]
            for l in range(j):
                s -= low[i * size + l] * low[j * size + l]
            if i == j:
                low[i * size + i] = _sqrt(_jmax(s, 1e-12))
            else:
                low[i * size + j] = _div(s, low[j * size + j])
    return low


def _invert_lower(low: List[float], size: int) -> List[float]:
    """The inverse of a lower-triangular matrix, by forward substitution; flat."""
    out = [0.0] * (size * size)
    for col in range(size):
        for i in range(size):
            s = 1.0 if i == col else 0.0
            for l in range(i):
                s -= low[i * size + l] * out[l * size + col]
            out[i * size + col] = _div(s, low[i * size + i])
    return out


def _nearest_correlation(c: List[float], size: int) -> float:
    """Moves a symmetric unit-diagonal matrix, in place, to a correlation matrix near it.

    Eigenvalues below 1e-6 are lifted to it and the matrix rebuilt, then the
    diagonal scaled back to one: one pass, which is enough for matrices typed
    by hand. Returns the largest change to any coefficient.
    """
    values, vectors = _jacobi_eigen(c, size)
    floor = 1e-6
    if all(v >= floor for v in values):
        return 0
    before = list(c)
    for i in range(size):
        for j in range(size):
            s = 0.0
            for l in range(size):
                s += vectors[i * size + l] * _jmax(values[l], floor) * vectors[j * size + l]
            c[i * size + j] = s
    d = [_sqrt(c[i * size + i]) for i in range(size)]
    for i in range(size):
        for j in range(size):
            c[i * size + j] = _div(c[i * size + j], d[i] * d[j])
    worst = 0.0
    for i in range(size * size):
        worst = _jmax(worst, abs(c[i] - before[i]))
    return worst


def _jacobi_eigen(a0: List[float], size: int) -> Tuple[List[float], List[float]]:
    """Eigenvalues and eigenvectors of a symmetric matrix by cyclic Jacobi; vectors are columns."""
    a = list(a0)
    v = _identity(size)
    for _sweep in range(100):
        off = 0.0
        for i in range(size):
            for j in range(i + 1, size):
                off += a[i * size + j] * a[i * size + j]
        if off < 1e-22:
            break
        for p in range(size):
            for q in range(p + 1, size):
                apq = a[p * size + q]
                if abs(apq) < 1e-300:
                    continue
                theta = (a[q * size + q] - a[p * size + p]) / (2 * apq)
                sign = 1.0 if (theta == 0 or theta != theta) else math.copysign(1.0, theta)
                t = sign / (abs(theta) + math.sqrt(theta * theta + 1))
                c = 1 / math.sqrt(t * t + 1)
                s = t * c
                for k in range(size):
                    akp = a[k * size + p]
                    akq = a[k * size + q]
                    a[k * size + p] = c * akp - s * akq
                    a[k * size + q] = s * akp + c * akq
                for k in range(size):
                    apk = a[p * size + k]
                    aqk = a[q * size + k]
                    a[p * size + k] = c * apk - s * aqk
                    a[q * size + k] = s * apk + c * aqk
                for k in range(size):
                    vkp = v[k * size + p]
                    vkq = v[k * size + q]
                    v[k * size + p] = c * vkp - s * vkq
                    v[k * size + q] = s * vkp + c * vkq
    return [a[i * size + i] for i in range(size)], v


def describe_correlation(c: Any) -> str:
    """One line per correlation, for a dialog or a notice."""
    group = _prop(c, 'group')
    if not _nullish(group):
        return f"every index of {_js_str(group)}, pairwise, at {_js_str(_prop(c, 'r'))}"
    return f"{_or_q(_prop(c, 'a'))} with {_or_q(_prop(c, 'b'))} at {_js_str(_prop(c, 'r'))}"
