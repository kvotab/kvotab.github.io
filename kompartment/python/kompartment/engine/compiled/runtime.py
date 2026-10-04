"""What a compiled model's equations call: numba versions of the few helpers
the generated code reaches for.

The generated passes are numpy code (``engine/codegen.py``), and numba
compiles almost all of it as it stands. What it cannot compile is a call into
a Python object: a lookup table, a function of the language not written
inline, the history a min/max keeps, a far-field path's release and the
refresh of its rates it starts with (in :mod:`.farfield`). Each has a
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
from numba import literal_unroll, njit, types
from numba.extending import overload

from ...stats._normal import _ERF_A as _NORMAL_ERF_A
from ...stats._normal import _ERF_B as _NORMAL_ERF_B
from ...stats._normal import _ERFC_COF as _NORMAL_ERFC_COF
from ...stats._normal import ERF_NEAR
from ..functions import AVOGADRO, FACTORIAL_MAX, LN2, SECONDS_PER_YEAR
from . import (FAIL_INTERPOLATION_ARGS, FAIL_LOOKUP_NO_X, FAIL_PYTHON, FAIL_RANGE_END, FAIL_RANGE_START,
               FAIL_TRANSPORT_ABOVE, FAIL_TRANSPORT_BELOW, CompiledFailure, guard_numba_cache)
from .farfield import DONE as _REFRESHED
from .farfield import refresh as _farf_refresh
from .solvers import CB_T

guard_numba_cache()

#: The overloads made around a kernel (``_binary``, ``_unary``, ``_ternary``,
#: ``_tuple_call``) are not cached: numba files a version by its closure's
#: contents, the kernel's dispatcher among them, which pickles differently in
#: every process -- so no other process would ever find it, and every one
#: would add its own.
_UNCACHED = {'cache': False, 'error_model': 'numpy'}

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


# Numerical Recipes' coefficients, and Cody's for erf near zero: the very ones
# stats/_normal.py uses.
_ERFC_COF = np.array(_NORMAL_ERFC_COF, dtype=np.float64)
_ERF_A = np.array(_NORMAL_ERF_A, dtype=np.float64)
_ERF_B = np.array(_NORMAL_ERF_B, dtype=np.float64)


@njit(cache=True, inline='always', error_model='numpy')
def _erf_near(x):
    y = abs(x)
    ysq = y * y if y > 1.11e-16 else 0.0
    num = _ERF_A[4] * ysq
    den = ysq
    for i in range(3):
        num = (num + _ERF_A[i]) * ysq
        den = (den + _ERF_B[i]) * ysq
    return x * (num + _ERF_A[3]) / (den + _ERF_B[3])


@njit(cache=True, inline='always', error_model='numpy')
def _erfc1(x):
    if x != x:
        return np.nan
    if abs(x) <= ERF_NEAR:
        return 1 - _erf_near(x)
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
    if abs(x) <= ERF_NEAR:
        return _erf_near(x)
    v = 1 - _erfc1(abs(x))
    return -v if x < 0 else v


overload(js_mod, jit_options=_UNCACHED)(_binary(_mod1))
overload(js_rem, jit_options=_UNCACHED)(_binary(_rem1))
overload(js_fix, jit_options=_UNCACHED)(_unary(_fix1))
overload(js_ulp, jit_options=_UNCACHED)(_unary(_ulp1))
overload(js_erfc, jit_options=_UNCACHED)(_unary(_erfc1))
overload(js_erf, jit_options=_UNCACHED)(_unary(_erf1))


# --- the rest of the language's functions (``engine/functions.py``) ------------------------------
# Each scalar kernel is the Python function's arithmetic, operation for
# operation; the overloads apply it element by element as the Python
# functions broadcast.


@njit(cache=True, inline='always', error_model='numpy')
def _npmin(a, b):
    """``np.minimum``: the first when they are equal, NaN when either is."""
    return a if (a <= b or a != a) else b


@njit(cache=True, inline='always', error_model='numpy')
def _npmax(a, b):
    """``np.maximum``."""
    return a if (a >= b or a != a) else b


@njit(cache=True, error_model='numpy')
def _factorial1(n):
    k = np.floor(n + 0.5) if math.isfinite(n) else n
    if not (k >= 0):
        return np.nan
    if k > FACTORIAL_MAX:
        return np.inf
    r = 1.0
    for i in range(2, int(k) + 1):
        r *= i
    return r


@njit(cache=True, inline='always', error_model='numpy')
def _binomial1(n, k):
    return _factorial1(n) / (_factorial1(k) * _factorial1(n - k))


@njit(cache=True, inline='always', error_model='numpy')
def _bq2mole1(bq, half_life):
    return (bq * half_life * SECONDS_PER_YEAR) / (LN2 * AVOGADRO)


@njit(cache=True, inline='always', error_model='numpy')
def _mole2bq1(mole, half_life):
    return (LN2 * mole * AVOGADRO) / (half_life * SECONDS_PER_YEAR)


@njit(cache=True, inline='always', error_model='numpy')
def _ramp_down1(x, start, end):
    lo = _npmin(start, end)
    hi = _npmax(start, end)
    mid = (hi - x) / (hi - lo)
    if not (x > lo):
        return 1.0
    if x >= hi:
        return 0.0
    return mid


@njit(cache=True, inline='always', error_model='numpy')
def _ramp_up1(x, start, end):
    return 1.0 - _ramp_down1(x, start, end)


@njit(cache=True, inline='always', error_model='numpy')
def _smooth_down1(x, X, s):
    r = np.power(x / X, 2 * s)
    val = 1.0 / (1.0 + r) if math.isfinite(r) else 0.0
    if not (x > 0):
        return 1.0
    if not (X > 0):
        return 0.0
    return val


@njit(cache=True, inline='always', error_model='numpy')
def _smooth_up1(x, X, s):
    return 1.0 - _smooth_down1(x, X, s)


def _ternary(scalar):
    """An overload body for a three-argument function of numbers or arrays."""
    def ov(a, b, c):
        if _is_num(a) and _is_num(b) and _is_num(c):
            return lambda a, b, c: scalar(float(a), float(b), float(c))
        if _is_arr(a) or _is_arr(b) or _is_arr(c):
            def impl(a, b, c):
                aa = np.asarray(a)
                bb = np.asarray(b)
                cc = np.asarray(c)
                n = max(aa.size, bb.size, cc.size)
                out = np.empty(n)
                for i in range(n):
                    out[i] = scalar(aa.flat[i if aa.size > 1 else 0], bb.flat[i if bb.size > 1 else 0],
                                    cc.flat[i if cc.size > 1 else 0])
                return out
            return impl
        return None
    return ov


def js_factorial(a):  # pragma: no cover - replaced by the overload in compiled code
    raise NotImplementedError


def js_binomial(a, b):  # pragma: no cover
    raise NotImplementedError


def js_bq2mole(a, b):  # pragma: no cover
    raise NotImplementedError


def js_mole2bq(a, b):  # pragma: no cover
    raise NotImplementedError


def js_ramp_down(a, b, c):  # pragma: no cover
    raise NotImplementedError


def js_ramp_up(a, b, c):  # pragma: no cover
    raise NotImplementedError


def js_smooth_down(a, b, c):  # pragma: no cover
    raise NotImplementedError


def js_smooth_up(a, b, c):  # pragma: no cover
    raise NotImplementedError


overload(js_factorial, jit_options=_UNCACHED)(_unary(_factorial1))
overload(js_binomial, jit_options=_UNCACHED)(_binary(_binomial1))
overload(js_bq2mole, jit_options=_UNCACHED)(_binary(_bq2mole1))
overload(js_mole2bq, jit_options=_UNCACHED)(_binary(_mole2bq1))
overload(js_ramp_down, jit_options=_UNCACHED)(_ternary(_ramp_down1))
overload(js_ramp_up, jit_options=_UNCACHED)(_ternary(_ramp_up1))
overload(js_smooth_down, jit_options=_UNCACHED)(_ternary(_smooth_down1))
overload(js_smooth_up, jit_options=_UNCACHED)(_ternary(_smooth_up1))


# --- the functions of any number of arguments ----------------------------------------------------
# The generated code passes their arguments as one tuple -- numbers and
# arrays mixed -- and the kernel reads them from a buffer, one element at a
# time, as ``functions._elementwise`` applies the Python ones.


def _size(a):  # pragma: no cover - replaced by the overload in compiled code
    raise NotImplementedError


def _at(a, i):  # pragma: no cover
    raise NotImplementedError


@overload(_size, jit_options={'cache': True, 'error_model': 'numpy'})
def _ov_size(a):
    if _is_num(a):
        return lambda a: 1
    if _is_arr(a):
        return lambda a: a.size
    return None


@overload(_at, jit_options={'cache': True, 'error_model': 'numpy'})
def _ov_at(a, i):
    if _is_num(a):
        return lambda a, i: float(a)
    if _is_arr(a):
        return lambda a, i: a[i if a.size > 1 else 0]
    return None


def _tuple_call(kernel):
    """An overload body for a function of a tuple of numbers and arrays: a
    number when every argument is one, else an array as long as the longest."""
    def ov(args):
        if not isinstance(args, types.BaseTuple):
            return None
        count = len(args)
        if all(_is_num(t) for t in args.types):
            def scalar_impl(args):
                buf = np.empty(count)
                i = 0
                for a in literal_unroll(args):
                    buf[i] = a
                    i += 1
                return kernel(buf)
            return scalar_impl

        def impl(args):
            n = 1
            for a in literal_unroll(args):
                s = _size(a)
                if s > n:
                    n = s
            out = np.empty(n)
            buf = np.empty(count)
            for e in range(n):
                i = 0
                for a in literal_unroll(args):
                    buf[i] = _at(a, e)
                    i += 1
                out[e] = kernel(buf)
            return out
        return impl
    return ov


@njit(cache=True, inline='always', error_model='numpy')
def _truthy(v):
    return v != 0


@njit(cache=True, error_model='numpy')
def _and_k(buf):
    out = True
    for i in range(buf.size):
        out = out and _truthy(buf[i])
    return 1.0 if out else 0.0


@njit(cache=True, error_model='numpy')
def _or_k(buf):
    out = False
    for i in range(buf.size):
        out = out or _truthy(buf[i])
    return 1.0 if out else 0.0


@njit(cache=True, error_model='numpy')
def _nand_k(buf):
    return 1.0 - _and_k(buf)


@njit(cache=True, error_model='numpy')
def _nor_k(buf):
    return 1.0 - _or_k(buf)


@njit(cache=True, error_model='numpy')
def _xor_k(buf):
    count = 0
    for i in range(buf.size):
        if _truthy(buf[i]):
            count += 1
    return 1.0 if count % 2 == 1 else 0.0


@njit(cache=True, inline='always', error_model='numpy')
def _js_compare(a, b):
    v = a - b
    return 0.0 if v != v else v


@njit(cache=True, error_model='numpy')
def _stable_sort(a, n, nan_last):
    """``sorted`` of a[:n], in place: a merge sort, which keeps equal values
    (0 and -0) in the order they came, as Python's sort does; ``nan_last``
    sorts by ``(1, 0) if NaN else (0, v)``."""
    tmp = np.empty(n)
    width = 1
    while width < n:
        lo = 0
        while lo < n:
            mid = min(lo + width, n)
            hi = min(lo + 2 * width, n)
            i = lo
            j = mid
            k = lo
            while i < mid and j < hi:
                x = a[i]
                y = a[j]
                if nan_last:
                    yn = y != y
                    xn = x != x
                    take_right = (not yn) and (xn or y < x)
                else:
                    take_right = y < x
                if take_right:
                    tmp[k] = y
                    j += 1
                else:
                    tmp[k] = x
                    i += 1
                k += 1
            while i < mid:
                tmp[k] = a[i]
                i += 1
                k += 1
            while j < hi:
                tmp[k] = a[j]
                j += 1
                k += 1
            lo += 2 * width
        for q in range(n):
            a[q] = tmp[q]
        width *= 2


@njit(cache=True, error_model='numpy')
def _js_sort(a, n):
    """``reduce.js_sort_numbers`` in place on a[:n]: V8's sort with the
    comparator ``a - b``."""
    if n < 2:
        return
    has_nan = False
    for i in range(n):
        if a[i] != a[i]:
            has_nan = True
            break
    if not has_nan:
        _stable_sort(a, n, False)
        return
    if n >= 64:
        _stable_sort(a, n, True)
        return
    run = 2
    descending = _js_compare(a[1], a[0]) < 0
    previous = a[1]
    for i in range(2, n):
        order = _js_compare(a[i], previous)
        if (descending and order >= 0) or (not descending and order < 0):
            break
        previous = a[i]
        run += 1
    if descending:
        lo = 0
        hi = run - 1
        while lo < hi:
            tmp = a[lo]
            a[lo] = a[hi]
            a[hi] = tmp
            lo += 1
            hi -= 1
    for start in range(run, n):
        pivot = a[start]
        left = 0
        right = start
        while left < right:
            mid = left + ((right - left) >> 1)
            if _js_compare(pivot, a[mid]) < 0:
                right = mid
            else:
                left = mid + 1
        for q in range(start, left, -1):
            a[q] = a[q - 1]
        a[left] = pivot


@njit(cache=True, error_model='numpy')
def _percentile_k(buf):
    """``reduce.percentile(buf[0], buf[1:])``."""
    phi = buf[0]
    n = buf.size - 1
    if not n or not (phi >= 0) or not (phi <= 100):
        return np.nan
    p = phi / 100
    s = buf[1:].copy()
    _js_sort(s, n)
    if p == 0.5:
        return s[(n + 1) // 2 - 1] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2
    xx = np.empty(n + 2)
    pp = np.empty(n + 2)
    xx[0] = s[0]
    pp[0] = 0.0
    for i in range(1, n + 1):
        xx[i] = s[i - 1]
        pp[i] = (i - 0.5) / n
    xx[n + 1] = s[n - 1]
    pp[n + 1] = 1.0
    j = 1
    while j < n + 2 and p > pp[j]:
        j += 1
    if j >= n + 2:
        return xx[n + 1]
    span = pp[j] - pp[j - 1]
    if span == 0:
        return xx[j]
    return ((p - pp[j - 1]) / span) * (xx[j] - xx[j - 1]) + xx[j - 1]


@njit(cache=True, error_model='numpy')
def _interpolate(buf, extrapolate):
    """``lookup.interpolate_args(buf, 'extrapolate' if extrapolate else
    'linear')``: a table of the x, y pairs after the lookup value, sorted by
    x as ``to_table`` sorts them, read at the lookup value."""
    rest = buf.size - 1
    if rest < 2 or rest % 2 != 0:
        raise CompiledFailure(FAIL_INTERPOLATION_ARGS, float(rest), 0.0)
    n = rest // 2
    xs = np.empty(n)
    ys = np.empty(n)
    for i in range(n):
        xs[i] = buf[1 + 2 * i]
        ys[i] = buf[2 + 2 * i]
    for i in range(n):
        if not math.isfinite(xs[i]):
            raise CompiledFailure(FAIL_LOOKUP_NO_X, 0.0, 0.0)
    # A stable sort by x, the y values following (insertion: the tables
    # written into an equation are short, and mostly in order already).
    for i in range(1, n):
        x = xs[i]
        y = ys[i]
        j = i
        while j > 0 and xs[j - 1] > x:
            xs[j] = xs[j - 1]
            ys[j] = ys[j - 1]
            j -= 1
        xs[j] = x
        ys[j] = y
    v = buf[0]
    if n == 1:
        return ys[0]
    if v <= xs[0]:
        return _between_xy(xs, ys, v, 0) if extrapolate else ys[0]
    if v >= xs[n - 1]:
        return _between_xy(xs, ys, v, n - 2) if extrapolate else ys[n - 1]
    if v != v:
        i = 0
    else:
        lo = 0
        hi = n
        while lo < hi:
            mid = (lo + hi) // 2
            if v < xs[mid]:
                hi = mid
            else:
                lo = mid + 1
        i = min(max(lo - 1, 0), n - 2)
    return _between_xy(xs, ys, v, i)


@njit(cache=True, inline='always', error_model='numpy')
def _between_xy(xs, ys, v, i):
    dx = xs[i + 1] - xs[i]
    if dx == 0:
        return ys[i + 1]
    return ys[i] + ((v - xs[i]) / dx) * (ys[i + 1] - ys[i])


@njit(cache=True, error_model='numpy')
def _interp_linear_k(buf):
    return _interpolate(buf, False)


@njit(cache=True, error_model='numpy')
def _interp_extrapolate_k(buf):
    return _interpolate(buf, True)


@njit(cache=True, error_model='numpy')
def _transport_point_k(buf):
    n = buf.size - 1
    x = buf[n]
    if x != x:
        return np.nan
    if x < 0:
        raise CompiledFailure(FAIL_TRANSPORT_BELOW, x, 0.0)
    if x > 1:
        raise CompiledFailure(FAIL_TRANSPORT_ABOVE, x, 0.0)
    return buf[n - 1 if x == 1 else int(math.trunc(x * n))]


@njit(cache=True, error_model='numpy')
def _transport_range(buf, mean):
    n = buf.size - 2
    a = buf[n]
    b = buf[n + 1]
    if a != a or b != b:
        return np.nan
    if a > b:
        tmp = a
        a = b
        b = tmp
    if a < 0:
        raise CompiledFailure(FAIL_RANGE_START, a, 0.0)
    if b > 1:
        raise CompiledFailure(FAIL_RANGE_END, b, 0.0)
    total = 0.0
    if a == 0 and b == 1:
        for e in range(n):
            total += buf[e]
        return total / n if mean else total
    f = int(math.trunc(a * n)) + 1
    t = int(math.trunc(b * n))
    cells = 0.0
    if t > f:
        for e in range(f, t):
            total += buf[e]
        cells += t - f
    dx = f - a * n
    cells += dx
    total += buf[f - 1] * dx
    if b < 1:
        dy = b * n - t
        cells += dy
        total += buf[t] * dy
    return total / cells if mean else total


@njit(cache=True, error_model='numpy')
def _transport_sum_k(buf):
    return _transport_range(buf, False)


@njit(cache=True, error_model='numpy')
def _transport_mean_k(buf):
    return _transport_range(buf, True)


def js_and(args):  # pragma: no cover - replaced by the overload in compiled code
    raise NotImplementedError


def js_or(args):  # pragma: no cover
    raise NotImplementedError


def js_nand(args):  # pragma: no cover
    raise NotImplementedError


def js_nor(args):  # pragma: no cover
    raise NotImplementedError


def js_xor(args):  # pragma: no cover
    raise NotImplementedError


def js_percentile(args):  # pragma: no cover
    raise NotImplementedError


def js_interp_linear(args):  # pragma: no cover
    raise NotImplementedError


def js_interp_extrapolate(args):  # pragma: no cover
    raise NotImplementedError


def js_transport_point(args):  # pragma: no cover
    raise NotImplementedError


def js_transport_sum(args):  # pragma: no cover
    raise NotImplementedError


def js_transport_mean(args):  # pragma: no cover
    raise NotImplementedError


for _stub, _kernel in ((js_and, _and_k), (js_or, _or_k), (js_nand, _nand_k), (js_nor, _nor_k), (js_xor, _xor_k),
                       (js_percentile, _percentile_k), (js_interp_linear, _interp_linear_k),
                       (js_interp_extrapolate, _interp_extrapolate_k), (js_transport_point, _transport_point_k),
                       (js_transport_sum, _transport_sum_k), (js_transport_mean, _transport_mean_k)):
    overload(_stub, jit_options=_UNCACHED)(_tuple_call(_kernel))
del _stub, _kernel

# Every function of the language a compiled model can call, and the name each
# is called by in the generated code (see :mod:`.model`); the ones in
# ``TUPLE_FUNCTIONS`` take their arguments as one tuple.
FUNCTION_NAMES = {
    'round': 'js_round', 'mod': 'js_mod', 'rem': 'js_rem', 'fix': 'js_fix', 'ulp': 'js_ulp',
    'erfc': 'js_erfc', 'erf': 'js_erf',
    'asinh': 'np.arcsinh', 'acosh': 'np.arccosh', 'atanh': 'np.arctanh',
    'factorial': 'js_factorial', 'binomial': 'js_binomial', 'bq2mole': 'js_bq2mole', 'mole2bq': 'js_mole2bq',
    'rampDown': 'js_ramp_down', 'rampUp': 'js_ramp_up', 'smoothDown': 'js_smooth_down', 'smoothUp': 'js_smooth_up',
    'and': 'js_and', 'or': 'js_or', 'nand': 'js_nand', 'nor': 'js_nor', 'xor': 'js_xor',
    'percentile': 'js_percentile', 'interpolationUseEndValues': 'js_interp_linear',
    'interpolationExtrapolation': 'js_interp_extrapolate', 'transport_point': 'js_transport_point',
    'transport_sum': 'js_transport_sum', 'transport_mean': 'js_transport_mean',
}
TUPLE_FUNCTIONS = frozenset({
    'and', 'or', 'nand', 'nor', 'xor', 'percentile', 'interpolationUseEndValues', 'interpolationExtrapolation',
    'transport_point', 'transport_sum', 'transport_mean',
})
#: What the generated module imports from this one.
RUNTIME_IMPORTS = ('js_pow', 'js_round', 'js_mod', 'js_rem', 'js_fix', 'js_ulp', 'js_erfc', 'js_erf',
                   'js_factorial', 'js_binomial', 'js_bq2mole', 'js_mole2bq', 'js_ramp_down', 'js_ramp_up',
                   'js_smooth_down', 'js_smooth_up', 'js_and', 'js_or', 'js_nand', 'js_nor', 'js_xor',
                   'js_percentile', 'js_interp_linear', 'js_interp_extrapolate', 'js_transport_point',
                   'js_transport_sum', 'js_transport_mean', 'tab1', 'tabs', 'extreme', 'running_mean', 'snapshot',
                   'delayed', 'recorder_store', 'recorder_fire', 'release', 'farf_refresh')
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
# Recorder m (a min/max, running mean, snapshot or delay at one index) keeps
# RECW numbers at W[ro + RECW*m]: the time and value of its history's last
# entry, its sign (1 max, -1 min), whether it records, and -- for a running
# mean -- the time it has recorded for, the last time it was told about and
# the sum at its last reset; then its kind. Its history is at W[hb + 2Cm ...]
# (times, then values), with the count in IW[hc + m].

RECW = 8
REC_MIN_MAX = 0
REC_RUNNING_MEAN = 1
REC_SNAPSHOT = 2
REC_DELAY = 3
RECORDER_CODES = {'min_max': REC_MIN_MAX, 'running_mean': REC_RUNNING_MEAN, 'snapshot': REC_SNAPSHOT,
                  'delay': REC_DELAY}
# What an event does to a recorder (``Recorder.fire``).
FIRE_SNAPSHOT = 0
FIRE_RESET = 1
FIRE_START = 2
FIRE_STOP = 3
FIRE_CODES = {'snapshot': FIRE_SNAPSHOT, 'reset': FIRE_RESET, 'start': FIRE_START, 'stop': FIRE_STOP}

# These and the far-field helpers below are compiled for one set of types
# each. The generated code passes offsets (RO, HB, a recorder's number) as
# numbers written into it, and numba compiles a function of no declared
# types again for every number it is passed: a version for every recorder of
# every model, each compiled with its model and filed in this module's
# cache, by every process compiling at once.
_W = types.float64[::1]
_IW = types.int64[::1]
_i = types.int64
_f = types.float64
_b = types.boolean


@njit(_i(_W, _IW, _i, _i, _i, _i, _f), cache=True, error_model='numpy')
def _history_below(W, IW, hb, hc, cap, m, time):
    """``History._below``: the last entry at or before ``time``, -1 for none."""
    n = IW[hc + m]
    to = hb + 2 * cap * m
    hi = n - 1
    if hi < 0 or time < W[to]:
        return -1
    lo = 0
    while lo < hi:
        mid = (lo + hi + 1) >> 1
        if W[to + mid] <= time:
            lo = mid
        else:
            hi = mid - 1
    return lo


@njit(_f(_W, _IW, _i, _i, _i, _i, _f), cache=True, error_model='numpy')
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
    return W[vo + _history_below(W, IW, hb, hc, cap, m, t)]


@njit(_f(_W, _IW, _i, _i, _i, _i, _f), cache=True, error_model='numpy')
def history_lerp(W, IW, hb, hc, cap, m, t):
    """``History.lerp``: straight lines between the entries."""
    n = IW[hc + m]
    if n == 0:
        return 0.0
    to = hb + 2 * cap * m
    vo = to + cap
    if t <= W[to]:
        return W[vo]
    if t >= W[to + n - 1]:
        return W[vo + n - 1]
    i = _history_below(W, IW, hb, hc, cap, m, t)
    t0 = W[to + i]
    t1 = W[to + i + 1]
    if t1 == t0:
        return W[vo + i + 1]
    return W[vo + i] + ((t - t0) / (t1 - t0)) * (W[vo + i + 1] - W[vo + i])


@njit(_f(_W, _IW, _i, _i, _i, _i, _i, _f, _f), cache=True, error_model='numpy')
def extreme(W, IW, ro, hb, hc, cap, m, t, target):
    """``Recorder.extreme``: a min/max read at ``t``, watching ``target``."""
    s = ro + RECW * m
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


@njit(_f(_W, _IW, _i, _i, _i, _i, _i, _f, _f, _f), cache=True, error_model='numpy')
def running_mean(W, IW, ro, hb, hc, cap, m, t, summed, target):
    """``Recorder.mean``: a running mean read at ``t``, from what its state
    has summed."""
    s = ro + RECW * m
    if t <= W[s]:
        return history_hold(W, IW, hb, hc, cap, m, t)
    elapsed = W[s + 4] + t - W[s + 5] if W[s + 3] != 0.0 else W[s + 4]
    return (summed - W[s + 6]) / elapsed if elapsed > 0 else target


@njit(_f(_W, _IW, _i, _i, _i, _i, _f), cache=True, error_model='numpy')
def snapshot(W, IW, hb, hc, cap, m, t):
    """``Recorder.held``."""
    return history_hold(W, IW, hb, hc, cap, m, t)


@njit(_f(_W, _IW, _i, _i, _i, _i, _f, _f), cache=True, error_model='numpy')
def delayed(W, IW, hb, hc, cap, m, t, lag):
    """``Recorder.delayed``: the history read ``lag`` before ``t``."""
    return history_lerp(W, IW, hb, hc, cap, m, t - lag)


@njit(_b(_W, _IW, _i, _i, _i, _i, _i, _f, _f), cache=True, error_model='numpy')
def history_add(W, IW, ro, hb, hc, cap, m, time, value):
    """``History.add``; False when the history is full."""
    to = hb + 2 * cap * m
    vo = to + cap
    n = IW[hc + m]
    s = ro + RECW * m
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


@njit(_b(_W, _IW, _i, _i, _i, _i, _i, _f, _f), cache=True, error_model='numpy')
def recorder_store(W, IW, ro, hb, hc, cap, m, t, current):
    """``Recorder.store``: a step accepted; False when a history is full."""
    s = ro + RECW * m
    kind = W[s + 7]
    if kind == REC_MIN_MAX:
        if current != W[s + 1]:
            return history_add(W, IW, ro, hb, hc, cap, m, t, current)
    elif kind == REC_DELAY:
        return history_add(W, IW, ro, hb, hc, cap, m, t, current)
    elif kind == REC_RUNNING_MEAN:
        ok = True
        if W[s + 3] != 0.0:
            ok = history_add(W, IW, ro, hb, hc, cap, m, t, current)
            W[s + 4] += t - W[s + 5]
        W[s + 5] = t
        return ok
    return True


@njit(_b(_W, _IW, _i, _i, _i, _i, _i, _i, _f, _f, _f), cache=True, error_model='numpy')
def recorder_fire(W, IW, ro, hb, hc, cap, m, what, t, target, summed):
    """``Recorder.fire``: what an event does to a recorder; False when a
    history is full."""
    s = ro + RECW * m
    if what == FIRE_SNAPSHOT:
        return history_add(W, IW, ro, hb, hc, cap, m, t, target)
    if what == FIRE_RESET:
        ok = history_add(W, IW, ro, hb, hc, cap, m, t, target)
        if W[s + 7] == REC_RUNNING_MEAN:
            W[s + 6] = summed
            W[s + 4] = 0.0
            W[s + 5] = t
        return ok
    if what == FIRE_START:
        W[s + 3] = 1.0
        W[s + 5] = t
    elif what == FIRE_STOP:
        W[s + 3] = 0.0
    return True


# --- what a model works out in Python -------------------------------------------------------------


@njit(types.void(CB_T, _W, _W, _f, _i, _f), cache=True, error_model='numpy')
def pyhook(cb, W, y, t, yb, code):
    """A block the model works out in Python (a semi-analytical far-field
    path; a path whose settings move, when its compiled refresh hands it
    over): the state copied to W[yb:] for it, then the callback, which
    writes what it works out into X or W. Raises :class:`CompiledFailure`
    when the callback raised."""
    for i in range(y.size):
        W[yb + i] = y[i]
    if cb(t, code) != 0:
        raise CompiledFailure(FAIL_PYTHON, code, 0.0)


# --- a far-field path's release ------------------------------------------------------------------


@njit(types.void(_W, _W, _W, _i, _IW, _i, _IW), cache=True, error_model='numpy')
def release(y, X, W, wo, rel_idx, nrel, slots):
    """``FarfPath.release``: each slot's weighted sum of its release cells,
    added from zero in the cells' order, into its slot of ``X``.
    ``rel_idx`` holds the cells' states slot by slot, ``nrel`` to a slot."""
    for i in range(slots.size):
        q = 0.0
        for r in range(nrel):
            q += W[wo + i * nrel + r] * y[rel_idx[i * nrel + r]]
        X[slots[i]] = q


@njit(types.void(CB_T, _W, _f, _W, _W, _IW, _i, _f), cache=True, error_model='numpy')
def farf_refresh(cb, y, t, X, W, fd, yb, code):
    """``FarfPath.refresh``, which its release starts with, for a path whose
    settings move: compiled (:mod:`.farfield`), on the path's directory
    ``fd``, and the path handed to Python through the callback -- the
    state copied to W[yb:] -- when the refresh asks for it: after it laid
    the matched layers out, or at a setting the Python refresh raises on,
    which the callback then raises."""
    if _farf_refresh(X, W, fd) != _REFRESHED:
        pyhook(cb, W, y, t, yb, code)
