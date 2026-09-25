"""What a compiled model's equations call: numba versions of the few helpers
the generated code reaches for.

The generated passes are numpy code (``engine/codegen.py``), and numba
compiles almost all of it as it stands. What it cannot compile is a call into
a Python object: a lookup table, a function of the language not written
inline, the history a min/max keeps, a far-field path's release. Each has a
version here that reads flat arrays instead of objects -- the model's
floating-point data ``W`` and integer data ``IW``, laid out by
:mod:`.model` -- and does the arithmetic of the Python one it replaces, in
its order, so a compiled derivative is the Python derivative to the last bit.

The functions of the language take a number or an array, as the Python ones
do, and are written once for each with ``numba.extending.overload``.
"""

from __future__ import annotations

import math

import numpy as np
from numba import njit, types
from numba.extending import overload

from ...stats._normal import _ERFC_COF as _NORMAL_ERFC_COF

# --- JavaScript's arithmetic -----------------------------------------------------------------


def js_pow(a, b):  # pragma: no cover - replaced by the overload in compiled code
    raise NotImplementedError


def js_round(a):  # pragma: no cover
    raise NotImplementedError


def js_mod(a, b):  # pragma: no cover
    raise NotImplementedError


def js_rem(a, b):  # pragma: no cover
    raise NotImplementedError


def js_fix(a):  # pragma: no cover
    raise NotImplementedError


def js_ulp(a):  # pragma: no cover
    raise NotImplementedError


def js_erfc(a):  # pragma: no cover
    raise NotImplementedError


def js_erf(a):  # pragma: no cover
    raise NotImplementedError


def _is_num(t):
    return isinstance(t, (types.Float, types.Integer, types.Boolean))


def _is_arr(t):
    return isinstance(t, types.Array) and t.ndim == 1


@njit(cache=True, inline='always', error_model='numpy')
def _pow1(a, b):
    r = np.power(float(a), float(b))
    if abs(a) == 1.0 and not math.isfinite(b):
        return np.nan
    return r


@overload(js_pow, jit_options={'cache': True, 'error_model': 'numpy'})
def _ov_pow(a, b):
    if _is_num(a) and _is_num(b):
        return lambda a, b: _pow1(a, b)
    if _is_arr(a) and _is_num(b):
        def impl(a, b):
            out = np.empty(a.size)
            for i in range(a.size):
                out[i] = _pow1(a[i], b)
            return out
        return impl
    if _is_num(a) and _is_arr(b):
        def impl(a, b):
            out = np.empty(b.size)
            for i in range(b.size):
                out[i] = _pow1(a, b[i])
            return out
        return impl
    if _is_arr(a) and _is_arr(b):
        def impl(a, b):
            n = max(a.size, b.size)
            out = np.empty(n)
            for i in range(n):
                out[i] = _pow1(a[i if a.size > 1 else 0], b[i if b.size > 1 else 0])
            return out
        return impl
    return None


@njit(cache=True, inline='always', error_model='numpy')
def _round1(a):
    f = math.floor(a)
    r = f + (1.0 if a - f >= 0.5 else 0.0)
    if r == 0:
        return math.copysign(0.0, a)
    return r


@overload(js_round, jit_options={'cache': True, 'error_model': 'numpy'})
def _ov_round(a):
    if _is_num(a):
        return lambda a: _round1(float(a))
    if _is_arr(a):
        def impl(a):
            out = np.empty(a.size)
            for i in range(a.size):
                out[i] = _round1(a[i])
            return out
        return impl
    return None


def _binary(scalar):
    """An overload body for a two-argument function of numbers or arrays."""
    def ov(a, b):
        if _is_num(a) and _is_num(b):
            return lambda a, b: scalar(float(a), float(b))
        if _is_arr(a) or _is_arr(b):
            def impl(a, b):
                aa = np.asarray(a)
                bb = np.asarray(b)
                n = max(aa.size, bb.size)
                out = np.empty(n)
                for i in range(n):
                    out[i] = scalar(aa.flat[i if aa.size > 1 else 0], bb.flat[i if bb.size > 1 else 0])
                return out
            return impl
        return None
    return ov


def _unary(scalar):
    def ov(a):
        if _is_num(a):
            return lambda a: scalar(float(a))
        if _is_arr(a):
            def impl(a):
                out = np.empty(a.size)
                for i in range(a.size):
                    out[i] = scalar(a[i])
                return out
            return impl
        return None
    return ov


@njit(cache=True, inline='always', error_model='numpy')
def _mod1(a, b):
    if b == 0:
        return a
    return a - b * math.floor(a / b)


@njit(cache=True, inline='always', error_model='numpy')
def _rem1(a, b):
    if b == 0:
        return np.nan
    return a - b * np.trunc(a / b)


@njit(cache=True, inline='always', error_model='numpy')
def _fix1(a):
    return np.trunc(a)


@njit(cache=True, inline='always', error_model='numpy')
def _ulp1(a):
    return abs(a) * 2.0 ** -52


# Numerical Recipes' coefficients, the very ones stats/_normal.py uses.
_ERFC_COF = np.array(_NORMAL_ERFC_COF, dtype=np.float64)


@njit(cache=True, inline='always', error_model='numpy')
def _erfc1(x):
    if x != x:
        return np.nan
    z = abs(x)
    t = 2 / (2 + z)
    ty = 4 * t - 2
    d = 0.0
    dd = 0.0
    for j in range(_ERFC_COF.size - 1, 0, -1):
        tmp = d
        d = ty * d - dd + _ERFC_COF[j]
        dd = tmp
    ans = t * math.exp(-z * z + 0.5 * (_ERFC_COF[0] + ty * d) - dd)
    return ans if x >= 0 else 2 - ans


@njit(cache=True, inline='always', error_model='numpy')
def _erf1(x):
    return 1 - _erfc1(x)


overload(js_mod, jit_options={'cache': True, 'error_model': 'numpy'})(_binary(_mod1))
overload(js_rem, jit_options={'cache': True, 'error_model': 'numpy'})(_binary(_rem1))
overload(js_fix, jit_options={'cache': True, 'error_model': 'numpy'})(_unary(_fix1))
overload(js_ulp, jit_options={'cache': True, 'error_model': 'numpy'})(_unary(_ulp1))
overload(js_erfc, jit_options={'cache': True, 'error_model': 'numpy'})(_unary(_erfc1))
overload(js_erf, jit_options={'cache': True, 'error_model': 'numpy'})(_unary(_erf1))

# The functions of the language a compiled model can call by name, and the
# name each is called by in the generated code. Anything else keeps a model on
# the Python path.
FUNCTION_NAMES = {
    'round': 'js_round', 'mod': 'js_mod', 'rem': 'js_rem', 'fix': 'js_fix', 'ulp': 'js_ulp',
    'erfc': 'js_erfc', 'erf': 'js_erf',
}
# ...and the ones the language's own ``functions.py`` names for them, which
# the Python code writer binds; see :mod:`.model`.
PYTHON_FUNCTIONS = {'js_round': 'round', 'js_mod': 'mod', 'js_rem': 'rem', 'fix': 'fix', '_ulp': 'ulp',
                    'erfc': 'erfc', 'erf': 'erf'}

# --- lookup tables ---------------------------------------------------------------------------
# Table k's entry in the directory at IW[td + 5k]: the offsets of its x and y
# values in W, its number of points, its interpolation (0 linear,
# 1 extrapolate, 2 below, 3 above, 4 nearest) and whether it wraps.

INTERPOLATION_CODES = {'linear': 0, 'extrapolate': 1, 'below': 2, 'above': 3, 'nearest': 4}


@njit(cache=True, inline='always', error_model='numpy')
def _between(W, xo, yo, v, i):
    dx = W[xo + i + 1] - W[xo + i]
    if dx == 0:
        return W[yo + i + 1]
    return W[yo + i] + ((v - W[xo + i]) / dx) * (W[yo + i + 1] - W[yo + i])


@njit(cache=True, error_model='numpy')
def table_at(W, IW, td, k, raw):
    """``Table.at_scalar``: table ``k`` read at ``raw``."""
    base = td + 5 * k
    xo = IW[base]
    yo = IW[base + 1]
    n = IW[base + 2]
    interp = IW[base + 3]
    first = W[xo]
    last = W[xo + n - 1]
    v = raw
    if IW[base + 4] != 0:
        span = last - first
        a = np.fmod(v - first, span)
        v = a + first if a >= 0 else a + span + first
    if n == 1:
        return W[yo]
    if v <= first:
        return _between(W, xo, yo, v, 0) if interp == 1 else W[yo]
    if v >= last:
        return _between(W, xo, yo, v, n - 2) if interp == 1 else W[yo + n - 1]
    if v != v:
        i = 0
    else:
        # bisect_right(x, v) - 1, kept inside the table.
        lo = 0
        hi = n
        while lo < hi:
            mid = (lo + hi) // 2
            if v < W[xo + mid]:
                hi = mid
            else:
                lo = mid + 1
        i = min(max(lo - 1, 0), n - 2)
    if interp == 2:
        return W[yo + i]
    if interp == 3:
        return W[yo + i] if W[xo + i] == v else W[yo + i + 1]
    if interp == 4:
        dx = W[xo + i + 1] - W[xo + i]
        return W[yo + i] if dx == 0 or (v - W[xo + i]) / dx < 0.5 else W[yo + i + 1]
    return _between(W, xo, yo, v, i)


def tab1(W, IW, td, k, x):  # pragma: no cover
    raise NotImplementedError


def tabs(W, IW, td, which, x):  # pragma: no cover
    raise NotImplementedError


@overload(tab1, jit_options={'cache': True, 'error_model': 'numpy'})
def _ov_tab1(W, IW, td, k, x):
    if _is_num(x):
        return lambda W, IW, td, k, x: table_at(W, IW, td, k, float(x))
    if _is_arr(x):
        def impl(W, IW, td, k, x):
            out = np.empty(x.size)
            for i in range(x.size):
                out[i] = table_at(W, IW, td, k, x[i])
            return out
        return impl
    return None


@overload(tabs, jit_options={'cache': True, 'error_model': 'numpy'})
def _ov_tabs(W, IW, td, which, x):
    if _is_num(x):
        def impl(W, IW, td, which, x):
            out = np.empty(which.size)
            for i in range(which.size):
                out[i] = table_at(W, IW, td, which[i], float(x))
            return out
        return impl
    if _is_arr(x):
        def impl(W, IW, td, which, x):
            out = np.empty(which.size)
            for i in range(which.size):
                out[i] = table_at(W, IW, td, which[i], x[i if x.size > 1 else 0])
            return out
        return impl
    return None


# --- the blocks that remember ------------------------------------------------------------------
# A min/max m keeps four numbers at W[ro + 4m] -- the time and value of its
# last history entry, its sign (1 max, -1 min), whether it records -- and its
# history at W[hb + 2Cm ...] (times, then values), with the count in IW[hc + m].


@njit(cache=True, error_model='numpy')
def history_hold(W, IW, hb, hc, cap, m, t):
    """``History.hold``: the value in force at ``t``."""
    n = IW[hc + m]
    if n == 0:
        return 0.0
    to = hb + 2 * cap * m
    vo = to + cap
    if t <= W[to]:
        return W[vo]
    if t >= W[to + n - 1]:
        return W[vo + n - 1]
    lo = 0
    hi = n - 1
    while lo < hi:
        mid = (lo + hi + 1) >> 1
        if W[to + mid] <= t:
            lo = mid
        else:
            hi = mid - 1
    return W[vo + lo]


@njit(cache=True, error_model='numpy')
def extreme(W, IW, ro, hb, hc, cap, m, t, target):
    """``Recorder.extreme``: a min/max read at ``t``, watching ``target``."""
    s = ro + 4 * m
    if t <= W[s]:
        return history_hold(W, IW, hb, hc, cap, m, t)
    if W[s + 3] == 0.0:
        return W[s + 1]
    last = W[s + 1]
    if last != last or target != target:
        return np.nan
    if W[s + 2] > 0:
        return max(last, target)
    return min(last, target)


@njit(cache=True, error_model='numpy')
def history_add(W, IW, ro, hb, hc, cap, m, time, value):
    """``History.add``; False when the history is full."""
    to = hb + 2 * cap * m
    vo = to + cap
    n = IW[hc + m]
    s = ro + 4 * m
    if n and time <= W[to + n - 1]:
        W[to + n - 1] = time
        W[vo + n - 1] = value
    elif n >= 2 and W[vo + n - 1] == value and W[vo + n - 2] == value:
        W[to + n - 1] = time
    else:
        if n >= cap:
            return False
        W[to + n] = time
        W[vo + n] = value
        IW[hc + m] = n + 1
        n += 1
    W[s] = W[to + n - 1]
    W[s + 1] = W[vo + n - 1]
    return True


# --- a far-field path's release ------------------------------------------------------------------


@njit(cache=True, error_model='numpy')
def release(y, X, W, wo, rel_idx, slots):
    """``FarfPath.release``: each slot's weighted sum of its release cells,
    added from zero in the cells' order, into its slot of ``X``."""
    nrel = rel_idx.shape[1]
    for i in range(slots.size):
        q = 0.0
        for r in range(nrel):
            q += W[wo + i * nrel + r] * y[rel_idx[i, r]]
        X[slots[i]] = q
