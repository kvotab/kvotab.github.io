"""The built-in functions of the equation language, as Kompartment defines them.

A port of ``src/parser/functions.js``: the same names, the same aliases, the
same arities, and the same answers -- including the ones JavaScript gives
where Python would raise (``log(0)`` is ``-inf``, ``sqrt(-1)`` NaN, ``1/0``
``inf``) and where the two languages round differently (``round`` takes halves
up, as ``Math.round`` does, not to even). Every function works on scalars and
on numpy arrays alike, element by element, which is how the engine evaluates a
block for all of its indices at once.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from ..stats._normal import erfc as _erfc_scalar

AVOGADRO = 6.02214179e23
EPS = 2.0 ** -52
SECONDS_PER_YEAR = 365.25 * 24 * 3600
LN2 = math.log(2)


def _arr(x: Any) -> Any:
    return np.asarray(x, dtype=float)


def js_round(a: Any) -> Any:
    """``Math.round``: the nearest integer, halves towards positive infinity.

    Not ``floor(a + 0.5)``, which rounds 0.49999999999999994 up to 1 (the sum
    rounds to 1.0 first); ``a - floor(a)`` is exact. A negative argument that
    rounds to zero gives -0, as it does in JavaScript.
    """
    a = np.asarray(a, dtype=float)
    with np.errstate(invalid='ignore'):
        f = np.floor(a)
        r = f + (a - f >= 0.5)
    r = np.where(r == 0, np.copysign(0.0, a), r)
    return r if r.ndim else float(r)


def fix(a: Any) -> Any:
    """Truncation towards zero."""
    return np.trunc(a)


def js_mod(a: Any, b: Any) -> Any:
    a, b = _arr(a), _arr(b)
    with np.errstate(all='ignore'):
        return np.where(b == 0, a, a - b * np.floor(a / b))


def js_rem(a: Any, b: Any) -> Any:
    a, b = _arr(a), _arr(b)
    with np.errstate(all='ignore'):
        return np.where(b == 0, np.nan, a - b * np.trunc(a / b))


_erfc_vec = np.frompyfunc(_erfc_scalar, 1, 1)


def erfc(x: Any) -> Any:
    """Numerical Recipes' erfc, exactly as the application computes it."""
    if np.ndim(x) == 0:
        return _erfc_scalar(float(x))
    return _erfc_vec(np.asarray(x, dtype=float)).astype(float)


def erf(x: Any) -> Any:
    return 1 - erfc(x)


FACTORIAL_MAX = 170


def _factorial_scalar(n: float) -> float:
    k = math.floor(n + 0.5) if math.isfinite(n) else n
    if not (k >= 0):
        return math.nan
    if k > FACTORIAL_MAX:
        return math.inf
    r = 1.0
    for i in range(2, int(k) + 1):
        r *= i
    return r


_factorial_vec = np.frompyfunc(_factorial_scalar, 1, 1)


def factorial(n: Any) -> Any:
    if np.ndim(n) == 0:
        return _factorial_scalar(float(n))
    return _factorial_vec(np.asarray(n, dtype=float)).astype(float)


def binomial(n: Any, k: Any) -> Any:
    with np.errstate(all='ignore'):
        return factorial(n) / (factorial(k) * factorial(_arr(n) - _arr(k)))


def js_min(*args: Any) -> Any:
    """``Math.min``: NaN in, NaN out."""
    out = args[0]
    for a in args[1:]:
        out = np.minimum(out, a)
    return out if len(args) > 1 else _arr(out) * 1.0


def js_max(*args: Any) -> Any:
    out = args[0]
    for a in args[1:]:
        out = np.maximum(out, a)
    return out if len(args) > 1 else _arr(out) * 1.0


def js_sum(*args: Any) -> Any:
    s: Any = 0.0
    for a in args:
        s = s + a
    return s


def js_prod(*args: Any) -> Any:
    p: Any = 1.0
    for a in args:
        p = p * a
    return p


def js_mean(*args: Any) -> Any:
    return js_sum(*args) / len(args)


def _truthy(v: Any) -> Any:
    return np.asarray(v) != 0


def js_if(t: Any, a: Any, b: Any = 0.0) -> Any:
    return np.where(_truthy(t), a, b)


def js_not(a: Any) -> Any:
    return np.where(_truthy(a), 0.0, 1.0)


def js_and(*a: Any) -> Any:
    out = _truthy(a[0])
    for v in a[1:]:
        out = out & _truthy(v)
    return out * 1.0


def js_or(*a: Any) -> Any:
    out = _truthy(a[0])
    for v in a[1:]:
        out = out | _truthy(v)
    return out * 1.0


def js_nand(*a: Any) -> Any:
    return 1.0 - js_and(*a)


def js_nor(*a: Any) -> Any:
    return 1.0 - js_or(*a)


def js_xor(*a: Any) -> Any:
    count = sum(_truthy(v).astype(int) for v in a)
    return (count % 2 == 1) * 1.0


def ramp_down(x: Any, start: Any, end: Any) -> Any:
    x, s, e = _arr(x), _arr(start), _arr(end)
    lo = np.minimum(s, e)
    hi = np.maximum(s, e)
    with np.errstate(all='ignore'):
        mid = (hi - x) / (hi - lo)
    return np.where(~(x > lo), 1.0, np.where(x >= hi, 0.0, mid))


def ramp_up(x: Any, start: Any, end: Any) -> Any:
    return 1.0 - ramp_down(x, start, end)


def smooth_down(x: Any, X: Any, s: Any) -> Any:
    x, X, s = _arr(x), _arr(X), _arr(s)
    with np.errstate(all='ignore'):
        r = np.power(x / X, 2 * s)
        val = np.where(np.isfinite(r), 1.0 / (1.0 + r), 0.0)
    return np.where(~(x > 0), 1.0, np.where(~(X > 0), 0.0, val))


def smooth_up(x: Any, X: Any, s: Any) -> Any:
    return 1.0 - smooth_down(x, X, s)


def bq2mole(bq: Any, half_life_years: Any) -> Any:
    return (_arr(bq) * half_life_years * SECONDS_PER_YEAR) / (LN2 * AVOGADRO)


def mole2bq(mole: Any, half_life_years: Any) -> Any:
    with np.errstate(all='ignore'):
        return (LN2 * _arr(mole) * AVOGADRO) / (_arr(half_life_years) * SECONDS_PER_YEAR)


def _elementwise(fn: Callable[..., float]) -> Callable[..., Any]:
    """A scalar function of several arguments, applied element by element."""
    def apply(*args: Any) -> Any:
        if all(np.ndim(a) == 0 for a in args):
            return fn(*[float(a) for a in args])
        arrays = np.broadcast_arrays(*[np.asarray(a, dtype=float) for a in args])
        out = np.empty(arrays[0].shape)
        flat = [a.ravel() for a in arrays]
        res = out.ravel()
        for i in range(res.size):
            res[i] = fn(*[f[i] for f in flat])
        return out
    return apply


def _percentile_scalar(phi: float, *xs: float) -> float:
    from .reduce import percentile
    return percentile(phi, list(xs))


def _interp_scalar(kind: str) -> Callable[..., float]:
    def fn(*args: float) -> float:
        from .lookup import interpolate_args
        return interpolate_args(list(args), kind)
    return fn


def _interp_slope(kind: str) -> Callable[..., float]:
    def fn(*args: float) -> float:
        from .lookup import interpolate_slope
        return interpolate_slope(list(args), kind)
    return fn


class TransportRangeError(ValueError):
    pass


def _transport_point(*args: float) -> float:
    x = args[-1]
    n = len(args) - 1
    if math.isnan(x):
        return math.nan
    if x < 0:
        raise TransportRangeError(f'transport operation: the position {x} is lower than zero')
    if x > 1:
        raise TransportRangeError(f'transport operation: the position {x} is higher than one')
    return args[n - 1 if x == 1 else math.trunc(x * n)]


def _transport_range(mean: bool) -> Callable[..., float]:
    def fn(*args: float) -> float:
        n = len(args) - 2
        a, b = args[n], args[n + 1]
        if math.isnan(a) or math.isnan(b):
            return math.nan
        if a > b:
            a, b = b, a
        if a < 0:
            raise TransportRangeError(f'transport operation: the range starts at {a}, which is lower than zero')
        if b > 1:
            raise TransportRangeError(f'transport operation: the range ends at {b}, which is higher than one')
        total = 0.0
        if a == 0 and b == 1:
            for e in range(n):
                total += args[e]
            return total / n if mean else total
        f = math.trunc(a * n) + 1
        t = math.trunc(b * n)
        cells = 0.0
        if t > f:
            for e in range(f, t):
                total += args[e]
            cells += t - f
        dx = f - a * n
        cells += dx
        total += args[f - 1] * dx
        if b < 1:
            dy = b * n - t
            cells += dy
            total += args[t] * dy
        return total / cells if mean else total
    return fn


def _ulp(a: Any) -> Any:
    return np.abs(a) * EPS


# name -> {arity, maxArity, varargs, needsContext, fn (vectorised), slope?}
FUNCTIONS: Dict[str, Dict[str, Any]] = {
    'abs': {'arity': 1, 'fn': np.abs},
    'sqrt': {'arity': 1, 'fn': np.sqrt},
    'exp': {'arity': 1, 'fn': np.exp},
    'log': {'arity': 1, 'fn': np.log},
    'log10': {'arity': 1, 'fn': np.log10},
    'log2': {'arity': 1, 'fn': np.log2},
    'power': {'arity': 2, 'fn': np.power},
    'hypot': {'arity': 2, 'fn': np.hypot},
    'ceil': {'arity': 1, 'fn': np.ceil},
    'floor': {'arity': 1, 'fn': np.floor},
    'round': {'arity': 1, 'fn': js_round},
    'fix': {'arity': 1, 'fn': fix},
    'sign': {'arity': 1, 'fn': np.sign},
    'eps': {'arity': 0, 'maxArity': 0, 'fn': lambda: EPS},
    'ulp': {'arity': 1, 'fn': _ulp},
    'pi': {'arity': 0, 'maxArity': 0, 'fn': lambda: math.pi},
    'mod': {'arity': 2, 'fn': js_mod},
    'rem': {'arity': 2, 'fn': js_rem},
    'factorial': {'arity': 1, 'fn': factorial},
    'binomial': {'arity': 2, 'fn': binomial},
    'erf': {'arity': 1, 'fn': erf},
    'erfc': {'arity': 1, 'fn': erfc},
    'sin': {'arity': 1, 'fn': np.sin},
    'cos': {'arity': 1, 'fn': np.cos},
    'tan': {'arity': 1, 'fn': np.tan},
    'asin': {'arity': 1, 'fn': np.arcsin},
    'acos': {'arity': 1, 'fn': np.arccos},
    'atan': {'arity': 1, 'fn': np.arctan},
    'atan2': {'arity': 2, 'fn': np.arctan2},
    'sinh': {'arity': 1, 'fn': np.sinh},
    'cosh': {'arity': 1, 'fn': np.cosh},
    'tanh': {'arity': 1, 'fn': np.tanh},
    'asinh': {'arity': 1, 'fn': np.arcsinh},
    'acosh': {'arity': 1, 'fn': np.arccosh},
    'atanh': {'arity': 1, 'fn': np.arctanh},
    'min': {'arity': 1, 'varargs': True, 'fn': js_min},
    'max': {'arity': 1, 'varargs': True, 'fn': js_max},
    'sum': {'arity': 1, 'varargs': True, 'fn': js_sum},
    'prod': {'arity': 1, 'varargs': True, 'fn': js_prod},
    'mean': {'arity': 1, 'varargs': True, 'fn': js_mean},
    'if': {'arity': 2, 'maxArity': 3, 'fn': js_if},
    'not': {'arity': 1, 'fn': js_not},
    'and': {'arity': 2, 'varargs': True, 'fn': js_and},
    'or': {'arity': 2, 'varargs': True, 'fn': js_or},
    'nand': {'arity': 2, 'varargs': True, 'fn': js_nand},
    'nor': {'arity': 2, 'varargs': True, 'fn': js_nor},
    'xor': {'arity': 2, 'varargs': True, 'fn': js_xor},
    'percentile': {'arity': 2, 'varargs': True, 'fn': _elementwise(_percentile_scalar)},
    'interpolationUseEndValues': {'arity': 3, 'varargs': True,
                                  'fn': _elementwise(_interp_scalar('linear')),
                                  'slope': _elementwise(_interp_slope('linear'))},
    'interpolationExtrapolation': {'arity': 3, 'varargs': True,
                                   'fn': _elementwise(_interp_scalar('extrapolate')),
                                   'slope': _elementwise(_interp_slope('extrapolate'))},
    'bq2mole': {'arity': 2, 'fn': bq2mole},
    'mole2bq': {'arity': 2, 'fn': mole2bq},
    'transport_point': {'arity': 2, 'varargs': True, 'fn': _elementwise(_transport_point)},
    'transport_sum': {'arity': 3, 'varargs': True, 'fn': _elementwise(_transport_range(False))},
    'transport_mean': {'arity': 3, 'varargs': True, 'fn': _elementwise(_transport_range(True))},
    'rampDown': {'arity': 3, 'fn': ramp_down},
    'rampUp': {'arity': 3, 'fn': ramp_up},
    'smoothDown': {'arity': 3, 'fn': smooth_down},
    'smoothUp': {'arity': 3, 'fn': smooth_up},
    'time': {'arity': 0, 'maxArity': 0, 'needsContext': True, 'fn': lambda ctx: ctx.t},
    'start_time': {'arity': 0, 'maxArity': 0, 'needsContext': True, 'fn': lambda ctx: ctx.start_time},
    'end_time': {'arity': 0, 'maxArity': 0, 'needsContext': True, 'fn': lambda ctx: ctx.end_time},
}

#: Aliases the language accepts.
FUNCTION_ALIASES = {'fabs': 'abs', 'ln': 'log', 'pow': 'power', 'sgn': 'sign', 'product': 'prod'}


def lookup_function(name: str) -> Optional[Dict[str, Any]]:
    """The function a name calls, with its canonical ``key``, or ``None``."""
    key = FUNCTION_ALIASES.get(name, name)
    spec = FUNCTIONS.get(key)
    if spec is None:
        return None
    out = dict(spec)
    out['key'] = key
    return out
