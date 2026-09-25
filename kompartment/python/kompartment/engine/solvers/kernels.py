"""The solvers' inner loops, compiled when numba is installed.

* The application's own dense LU (``src/ode/core/linalg.js``: ``formAndFactor``,
  ``factorizeInPlace``, ``solve``) -- the same row-major elimination with
  partial pivoting, the same pivot choice, one rounding per operation -- so a
  dense factorisation is the application's to the last bit, and on a small
  system it is several times quicker than LAPACK's through SciPy, whose call
  costs more than the factorisation.
* The weighted error norms (the one-step methods' and NDF's), the checks for
  a constrained state at or below zero, and the arithmetic of a Rosenbrock
  (2,3) step between its derivative calls.

``available()`` says whether they compiled; without numba the solvers keep to
LAPACK and numpy.
"""

from __future__ import annotations

import math
from typing import Any, Tuple

import numpy as np

from .._numba import jit

#: Status codes of the factorisations.
OK, SINGULAR, NONFINITE = 0, 1, 2


def _factor_in_place(lu: np.ndarray, piv: np.ndarray, fail: np.ndarray) -> int:  # pragma: no cover - compiled
    n = lu.shape[0]
    for i in range(n):
        piv[i] = i
    for k in range(n):
        p = k
        max_abs = abs(lu[k, k])
        for i in range(k + 1, n):
            v = abs(lu[i, k])
            if v > max_abs:
                max_abs = v
                p = i
        if not (max_abs > 0) or not math.isfinite(max_abs):
            fail[0] = k
            fail[1] = max_abs
            return NONFINITE if max_abs != 0 else SINGULAR
        if p != k:
            for j in range(n):
                tmp = lu[p, j]
                lu[p, j] = lu[k, j]
                lu[k, j] = tmp
            t = piv[p]
            piv[p] = piv[k]
            piv[k] = t
        pivot = lu[k, k]
        for i in range(k + 1, n):
            f = lu[i, k] / pivot
            if f == 0:
                continue
            lu[i, k] = f
            for j in range(k + 1, n):
                lu[i, j] -= f * lu[k, j]
    return OK


def _form_factor_pattern(a: float, col_ptr: np.ndarray, row_idx: np.ndarray, values: np.ndarray,
                         held: np.ndarray, mass: np.ndarray, lu: np.ndarray, piv: np.ndarray,
                         fail: np.ndarray) -> int:  # pragma: no cover - compiled
    """Mass - a*J from a CSC pattern's values, then factorised (``formAndFactor``).
    A row ``held`` marks is a row of the identity."""
    n = lu.shape[0]
    for i in range(n):
        for j in range(n):
            lu[i, j] = 0.0
    bad = -1
    bad_value = 0.0
    for j in range(n):
        for p in range(col_ptr[j], col_ptr[j + 1]):
            i = row_idx[p]
            if held[i]:
                continue
            v = -a * values[p]
            if bad < 0 and not math.isfinite(v):
                bad = j
                bad_value = v
            lu[i, j] = v
    if bad >= 0:
        fail[0] = bad
        fail[1] = bad_value
        return -NONFINITE
    for i in range(n):
        lu[i, i] += mass[i]
    return _factor_in_place(lu, piv, fail)


def _form_factor_dense(a: float, J: np.ndarray, held: np.ndarray, mass: np.ndarray, lu: np.ndarray,
                       piv: np.ndarray, fail: np.ndarray) -> int:  # pragma: no cover - compiled
    """Mass - a*J from a dense Jacobian, then factorised."""
    n = lu.shape[0]
    bad = -1
    bad_value = 0.0
    for j in range(n):
        for i in range(n):
            v = 0.0 if held[i] else -a * J[i, j]
            if bad < 0 and not math.isfinite(v):
                bad = j
                bad_value = v
            lu[i, j] = v
    if bad >= 0:
        fail[0] = bad
        fail[1] = bad_value
        return -NONFINITE
    for i in range(n):
        lu[i, i] += mass[i]
    return _factor_in_place(lu, piv, fail)


def _solve(lu: np.ndarray, piv: np.ndarray, b: np.ndarray, x: np.ndarray) -> np.ndarray:  # pragma: no cover
    n = lu.shape[0]
    for i in range(n):
        x[i] = b[piv[i]]
    for i in range(1, n):
        s = x[i]
        for j in range(i):
            s -= lu[i, j] * x[j]
        x[i] = s
    for i in range(n - 1, -1, -1):
        s = x[i]
        for j in range(i + 1, n):
            s -= lu[i, j] * x[j]
        x[i] = s / lu[i, i]
    return x


def _weighted(v: np.ndarray, ya: np.ndarray, yb: np.ndarray, threshold: np.ndarray,
              out: np.ndarray) -> None:  # pragma: no cover - compiled
    """The largest |v| / max(|ya|, |yb|, threshold) and where, into ``out``
    (worst, index); NaN and the first index where it is not a number."""
    n = v.size
    worst = 0.0
    at = 0
    for i in range(n):
        s = max(max(abs(ya[i]), abs(yb[i])), threshold[i])
        e = abs(v[i]) / s
        if not (e >= 0) or not math.isfinite(yb[i]):
            out[0] = math.nan
            out[1] = i
            return
        if i == 0 or e > worst:
            worst = e
            at = i
    if worst > 0:
        out[0] = worst
        out[1] = at
    else:
        out[0] = 0.0
        out[1] = 0


# --- the Rosenbrock (2,3) step, in three pieces around its two derivative calls ---------------------
# Each is the application's loops (rosenbrock23.js, attempt) with its
# association: h*D*ft[i] is (h*D)*ft[i], and hD, half_h are those products.

def _ros_first(lu: np.ndarray, piv: np.ndarray, f0: np.ndarray, ft: np.ndarray, hD: float, y: np.ndarray,
               half_h: float, tmp: np.ndarray, k1: np.ndarray, ymid: np.ndarray) -> None:  # pragma: no cover
    n = y.size
    for i in range(n):
        tmp[i] = f0[i] + hD * ft[i]
    _solve(lu, piv, tmp, k1)
    for i in range(n):
        ymid[i] = y[i] + half_h * k1[i]


def _ros_second(lu: np.ndarray, piv: np.ndarray, f1: np.ndarray, k1: np.ndarray, y: np.ndarray, h: float,
                tmp: np.ndarray, k2: np.ndarray, ynew: np.ndarray) -> None:  # pragma: no cover
    n = y.size
    for i in range(n):
        tmp[i] = f1[i] - k1[i]
    _solve(lu, piv, tmp, k2)
    for i in range(n):
        k2[i] += k1[i]
    for i in range(n):
        ynew[i] = y[i] + h * k2[i]


def _ros_third(lu: np.ndarray, piv: np.ndarray, f2: np.ndarray, k2: np.ndarray, f1: np.ndarray, k1: np.ndarray,
               f0: np.ndarray, ft: np.ndarray, hD: float, e32: float, tmp: np.ndarray, k3: np.ndarray,
               err: np.ndarray) -> None:  # pragma: no cover
    n = k1.size
    for i in range(n):
        tmp[i] = f2[i] - e32 * (k2[i] - f1[i]) - 2 * (k1[i] - f0[i]) + hD * ft[i]
    _solve(lu, piv, tmp, k3)
    for i in range(n):
        err[i] = k1[i] - 2 * k2[i] + k3[i]


def _all_above_zero(y: np.ndarray, idx: np.ndarray) -> bool:  # pragma: no cover - compiled
    """Whether every ``y[idx]`` is above zero (NaN is not)."""
    for k in range(idx.size):
        if not (y[idx[k]] > 0):
            return False
    return True


def _any_below_zero(y: np.ndarray, idx: np.ndarray) -> bool:  # pragma: no cover - compiled
    """Whether any ``y[idx]`` is below zero."""
    for k in range(idx.size):
        if y[idx[k]] < 0:
            return True
    return False


def _scaled_max(v: np.ndarray, inv: np.ndarray) -> float:  # pragma: no cover - compiled
    """max(0, max |v| * inv), NaN when any product is not a number (NDF's max norm)."""
    m = 0.0
    for i in range(v.size):
        a = abs(v[i]) * inv[i]
        if a != a:
            return math.nan
        if a > m:
            m = a
    return m


_COMPILED: Any = None
#: Compiled first, and put in place of their Python selves in this module, so
#: that the kernels calling them are compiled against the compiled ones.
_BASE = ('_factor_in_place', '_solve')
_KERNELS = {'pattern': '_form_factor_pattern', 'dense': '_form_factor_dense', 'solve': '_solve',
            'weighted': '_weighted', 'ros_first': '_ros_first', 'ros_second': '_ros_second',
            'ros_third': '_ros_third', 'all_above_zero': '_all_above_zero', 'any_below_zero': '_any_below_zero',
            'scaled_max': '_scaled_max'}


def _compiled() -> Any:
    global _COMPILED
    if _COMPILED is not None:
        return _COMPILED or None
    g = globals()
    python = {name: g[name] for name in _BASE}
    try:
        for name in _BASE:
            k = jit(python[name])
            if k is None:
                raise RuntimeError('no numba')
            g[name] = k
        kernels = {key: (g[name] if name in _BASE else jit(g[name])) for key, name in _KERNELS.items()}
        if any(k is None for k in kernels.values()):
            raise RuntimeError('a kernel did not compile')
        # Compiled here, on the smallest problem, so that a failure shows now
        # and falls back rather than in the middle of a run.
        lu = np.eye(1)
        piv = np.zeros(1, dtype=np.int64)
        fail = np.zeros(2)
        one = np.ones(1)
        z = np.zeros(1)
        kernels['pattern'](0.5, np.array([0, 1], dtype=np.int64), np.array([0], dtype=np.int64), one,
                           np.zeros(1, dtype=np.bool_), one, lu, piv, fail)
        kernels['dense'](0.5, np.ones((1, 1)), np.zeros(1, dtype=np.bool_), one, lu, piv, fail)
        kernels['solve'](lu, piv, one, z)
        kernels['weighted'](one, one, one, one, np.zeros(2))
        kernels['ros_first'](lu, piv, one, one, 0.5, one, 0.5, z.copy(), z.copy(), z.copy())
        kernels['ros_second'](lu, piv, one, one, one, 0.5, z.copy(), z.copy(), z.copy())
        kernels['ros_third'](lu, piv, one, one, one, one, one, one, 0.5, 7.4, z.copy(), z.copy(), z.copy())
        kernels['all_above_zero'](one, np.zeros(1, dtype=np.int64))
        kernels['any_below_zero'](one, np.zeros(1, dtype=np.int64))
        kernels['scaled_max'](one, one)
        _COMPILED = kernels
    except Exception:  # noqa: BLE001 - numba missing or refusing: go without
        g.update(python)
        _COMPILED = False
    return _COMPILED or None


def available() -> bool:
    return _compiled() is not None


def kernel(name: str) -> Any:
    k = _compiled()
    return k[name] if k else None


def weighted_py(v: np.ndarray, ya: np.ndarray, yb: np.ndarray, threshold: np.ndarray) -> Tuple[float, int]:
    """The same norm in numpy, for when numba is not there."""
    with np.errstate(all='ignore'):
        e = np.abs(v) / np.maximum(np.maximum(np.abs(ya), np.abs(yb)), threshold)
    bad = ~(e >= 0) | ~np.isfinite(yb)
    if bad.any():
        return math.nan, int(np.nonzero(bad)[0][0])
    if not e.size:
        return 0.0, 0
    at = int(np.argmax(e))
    worst = float(e[at])
    return (worst, at) if worst > 0 else (0.0, 0)
