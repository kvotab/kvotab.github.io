"""The standard normal distribution, as Kompartment computes it.

Exact ports of ``erfc`` (``src/parser/functions.js``) and of ``phi``,
``probit`` and ``normalQuantile`` (``src/domain/pdf.js``), so that everything
built on them -- quantiles, samples, sensitivity designs -- comes out as the
application's does. Scalars in, scalars out; the arithmetic is the same step
for step. (``math.exp`` and ``math.log`` may differ from V8's in the last bit,
so agreement is to a few ulps, not bit for bit.)
"""

from __future__ import annotations

import math
from typing import Optional

_ERFC_COF = (
    -1.3026537197817094, 6.4196979235649026e-1, 1.9476473204185836e-2,
    -9.561514786808631e-3, -9.46595344482036e-4, 3.66839497852761e-4,
    4.2523324806907e-5, -2.0278578112534e-5, -1.624290004647e-6,
    1.303655835580e-6, 1.5626441722e-8, -8.5238095915e-8,
    6.529054439e-9, 5.059343495e-9, -9.91364156e-10,
    -2.27365122e-10, 9.6467911e-11, 2.394038e-12,
    -6.886027e-12, 8.94487e-13, 3.13092e-13,
    -1.12708e-13, 3.81e-16, 7.106e-15,
)

SQRT2 = math.sqrt(2.0)


def erfc(x: float) -> float:
    """The complementary error function: Numerical Recipes' Chebyshev fit."""
    if math.isnan(x):
        return math.nan
    z = abs(x)
    t = 2 / (2 + z)
    ty = 4 * t - 2
    d = 0.0
    dd = 0.0
    for j in range(len(_ERFC_COF) - 1, 0, -1):
        tmp = d
        d = ty * d - dd + _ERFC_COF[j]
        dd = tmp
    ans = t * math.exp(-z * z + 0.5 * (_ERFC_COF[0] + ty * d) - dd)
    return ans if x >= 0 else 2 - ans


def erf(x: float) -> float:
    """The error function, as ``1 - erfc(x)``."""
    return 1 - erfc(x)


def phi(z: float) -> float:
    """The standard normal CDF."""
    return 0.5 * erfc(-z / SQRT2)


_A = (-3.969683028665376e+1, 2.209460984245205e+2, -2.759285104469687e+2,
      1.383577518672690e+2, -3.066479806614716e+1, 2.506628277459239)
_B = (-5.447609879822406e+1, 1.615858368580409e+2, -1.556989798598866e+2,
      6.680131188771972e+1, -1.328068155288572e+1)
_C = (-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838,
      -2.549732539343734, 4.374664141464968, 2.938163982698783)
_D = (7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996,
      3.754408661907416)


def probit(p: float) -> Optional[float]:
    """Acklam's approximation to the normal quantile; ``None`` outside (0, 1)."""
    try:
        q = float(p)
    except (TypeError, ValueError):
        return None
    if not (0 < q < 1):
        return None
    a, b, c, d = _A, _B, _C, _D
    lo = 0.02425
    if q < lo:
        t = math.sqrt(-2 * math.log(q))
        return ((((((c[0] * t + c[1]) * t + c[2]) * t + c[3]) * t + c[4]) * t + c[5])
                / ((((d[0] * t + d[1]) * t + d[2]) * t + d[3]) * t + 1))
    if q <= 1 - lo:
        t = q - 0.5
        r = t * t
        return ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * t
                / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1))
    t = math.sqrt(-2 * math.log(1 - q))
    return (-(((((c[0] * t + c[1]) * t + c[2]) * t + c[3]) * t + c[4]) * t + c[5])
            / ((((d[0] * t + d[1]) * t + d[2]) * t + d[3]) * t + 1))


def normal_quantile(p: float) -> float:
    """The standard normal's inverse CDF: ``probit`` and two Newton steps."""
    if not (p > 0):
        return -math.inf
    if not (p < 1):
        return math.inf
    x = probit(p)
    assert x is not None
    for _ in range(2):
        e = phi(x) - p
        dens = math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
        if not (dens > 0):
            break
        x -= e / dens
    return x
