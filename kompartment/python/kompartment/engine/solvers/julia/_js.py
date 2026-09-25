"""What JavaScript does with a number, where Python would do something else.

The JS package these solvers are ported from leans on a handful of built-ins
whose Python counterparts differ at the edges: ``Math.max`` of a NaN is NaN
(Python's ``max`` keeps whichever came first), ``x ** y`` of a negative base is
NaN (Python gives a complex number or raises), ``String(x)`` writes ``100000``
and ``1e-7`` where ``repr`` writes ``100000.0`` and ``1e-07``, and a sum of
squares accumulated one term at a time rounds differently from numpy's
pairwise ``sum``. Each of those decides something here -- a step size, an
error norm, the text of an error message -- so each is written out once.

``**`` itself is the platform's ``pow``: V8 carries its own, which differs from
the C library's in the last bit for a few per cent of arguments. That is the
same size of difference as the LAPACK and SuperLU factorisations make against
the package's own LUs, and it moves nothing a step is decided on.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Any

import numpy as np

from ....jsonio import js_number

EPS = 2.0 ** -52
MIN_VALUE = 5e-324
SQRT_EPS = math.sqrt(EPS)
INF = math.inf
NAN = math.nan


def jmax(a: float, b: float) -> float:
    """``Math.max(a, b)``: NaN wins, and +0 is larger than -0."""
    if a != a or b != b:
        return NAN
    if a > b:
        return a
    if b > a:
        return b
    if a == 0 and b == 0:
        return b if math.copysign(1.0, a) < 0 else a
    return a


def jmin(a: float, b: float) -> float:
    """``Math.min(a, b)``: NaN wins, and -0 is smaller than +0."""
    if a != a or b != b:
        return NAN
    if a < b:
        return a
    if b < a:
        return b
    if a == 0 and b == 0:
        return b if math.copysign(1.0, b) < 0 else a
    return a


def _odd_integer(y: float) -> bool:
    return math.isfinite(y) and y == math.floor(y) and math.fmod(y, 2.0) != 0


def jpow(x: float, y: float) -> float:
    """``x ** y`` with JavaScript's answers where Python raises or goes complex."""
    if y != y:
        return NAN
    if y == 0:
        return 1.0
    if x != x:
        return NAN
    if math.isinf(y) and abs(x) == 1:
        return NAN
    # fdlibm's exact cases, which V8's pow keeps: x ** 0.5 is sqrt(x) there,
    # and the platform's pow misses that by an ulp now and then.
    if y == 0.5 and x > 0 and math.isfinite(x):
        return math.sqrt(x)
    if y == 1:
        return x
    if y == 2:
        return x * x
    try:
        return math.pow(x, y)
    except OverflowError:
        return -INF if (x < 0 and _odd_integer(y)) else INF
    except ValueError:
        if x == 0:
            # 0 to a negative power.
            negative = math.copysign(1.0, x) < 0 and _odd_integer(y)
            return -INF if negative else INF
        return NAN


def jdiv(a: float, b: float) -> float:
    """``a / b`` for two numbers: dividing by zero gives an infinity or NaN."""
    try:
        return a / b
    except ZeroDivisionError:
        if a != a or a == 0:
            return NAN
        negative = (a < 0) != (math.copysign(1.0, b) < 0)
        return -INF if negative else INF


def jsign(x: float) -> float:
    """``Math.sign``."""
    if x != x:
        return NAN
    if x > 0:
        return 1.0
    if x < 0:
        return -1.0
    return x


def seq_sum(v: np.ndarray) -> float:
    """``s = 0; for (...) s += v[i]``: left to right, not numpy's pairwise sum."""
    if v.size == 0:
        return 0.0
    return float(np.cumsum(v)[-1])


def max_or_zero(v: np.ndarray) -> float:
    """``m = 0; for (...) { if (v[i] > m) m = v[i]; else if (v[i] !== v[i]) return NaN; }``:
    the largest, at least 0, and NaN if any entry is NaN."""
    if v.size == 0:
        return 0.0
    m = float(np.max(v))
    if m != m:
        return NAN
    return m if m > 0 else 0.0


def js_string(x: Any) -> str:
    """``String(x)`` for a number, or ``${x}`` in a template."""
    if isinstance(x, bool):
        return 'true' if x else 'false'
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    x = float(x)
    if x != x:
        return 'NaN'
    if math.isinf(x):
        return 'Infinity' if x > 0 else '-Infinity'
    return js_number(x)


_WIDE = Context(prec=2000)


def to_exponential(x: float, digits: int) -> str:
    """``x.toExponential(digits)``: exact decimal rounding, ties away from zero."""
    x = float(x)
    if x != x:
        return 'NaN'
    if math.isinf(x):
        return 'Infinity' if x > 0 else '-Infinity'
    sign = '-' if x < 0 else ''
    x = abs(x)
    if x == 0:
        return f"0{'.' + '0' * digits if digits else ''}e+0"
    d = Decimal(x)
    e = d.adjusted()
    q = d.scaleb(digits - e, context=_WIDE)
    n = int(q.quantize(Decimal(1), rounding=ROUND_HALF_UP, context=_WIDE))
    if n >= 10 ** (digits + 1):
        n //= 10
        e += 1
    s = str(n)
    mant = s[0] + ('.' + s[1:] if digits else '')
    return f"{sign}{mant}e{'+' if e >= 0 else '-'}{abs(e)}"


def ulp(x: float) -> float:
    """``x === 0 ? Number.MIN_VALUE : 2 ** (Math.floor(Math.log2(Math.abs(x))) - 52)``."""
    if x == 0:
        return MIN_VALUE
    a = abs(x)
    if a != a:
        return NAN
    if math.isinf(a):
        return INF
    return 2.0 ** (math.floor(math.log2(a)) - 52)
