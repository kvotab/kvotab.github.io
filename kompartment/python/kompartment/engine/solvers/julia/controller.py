"""The next step size from the error estimate (``core/controller.js``).

OrdinaryDiffEq's PI controller -- beta1 = 7/(10k), beta2 = 2/(5k), gamma 9/10,
qmin 1/5, qmax 10, qoldinit 1e-4 -- and Hairer's starting step.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Optional

import numpy as np

from ._js import jdiv, jmax, jmin, jpow, seq_sum


class PIController:
    """``PIController``: ``accept`` and ``reject`` answer the next step."""

    def __init__(self, order: float, beta1: Optional[float] = None, beta2: Optional[float] = None,
                 gamma: Optional[float] = None, qmin: Optional[float] = None, qmax: Optional[float] = None,
                 qsteady_min: Optional[float] = None, qsteady_max: Optional[float] = None,
                 qoldinit: Optional[float] = None) -> None:
        k = order
        self.beta1 = beta1 if beta1 is not None else 7 / (10 * k)
        self.beta2 = beta2 if beta2 is not None else 2 / (5 * k)
        self.gamma = gamma if gamma is not None else 0.9
        self.qmin = qmin if qmin is not None else 0.2
        self.qmax = qmax if qmax is not None else 10
        self.qsteady_min = qsteady_min if qsteady_min is not None else 1
        self.qsteady_max = qsteady_max if qsteady_max is not None else 1.2
        self.qoldinit = qoldinit if qoldinit is not None else 1e-4
        self.errold = self.qoldinit
        self.q11 = 1.0

    def set_order(self, k: float) -> None:
        self.beta1 = 7 / (10 * k)
        self.beta2 = 2 / (5 * k)

    def q(self, eest: float) -> float:
        if eest == 0:
            return 1 / self.qmax
        self.q11 = jpow(eest, self.beta1)
        q = jdiv(self.q11, jpow(self.errold, self.beta2))
        q /= self.gamma
        return jmin(1 / self.qmin, jmax(1 / self.qmax, q))

    def accept(self, eest: float, dt: float) -> float:
        q = self.q(eest)
        if q >= self.qsteady_min and q <= self.qsteady_max:
            q = 1
        self.errold = jmax(eest, self.qoldinit)
        return jdiv(dt, q)

    def reject(self, eest: float, dt: float) -> float:
        self.q11 = jpow(eest, self.beta1)
        return jdiv(dt, jmin(1 / self.qmin, self.q11 / self.gamma))

    def reset(self) -> None:
        self.errold = self.qoldinit
        self.q11 = 1.0


def initial_step(f: Callable[[float, np.ndarray], np.ndarray], t0: float, u0: np.ndarray, f0: np.ndarray,
                 tdir: float, order: float, reltol: float, abstol: Any, dtmax: float) -> float:
    """Hairer's starting step (Solving ODEs I, II.4), signed (``initialStep``)."""
    n = u0.size
    w = abstol + reltol * np.abs(u0)
    a = u0 / w
    b = f0 / w
    d0 = math.sqrt(seq_sum(a * a) / n)
    d1 = math.sqrt(seq_sum(b * b) / n)
    h0 = 1e-6 if (d0 < 1e-5 or d1 < 1e-5) else 0.01 * jdiv(d0, d1)
    h0 = jmin(h0, abs(dtmax))
    u1 = u0 + tdir * h0 * f0
    f1 = f(t0 + tdir * h0, u1)
    c = (f1 - f0) / w
    d2 = jdiv(math.sqrt(seq_sum(c * c) / n), h0)
    dmax = jmax(d1, d2)
    h1 = jmax(1e-6, h0 * 1e-3) if dmax <= 1e-15 else jpow(jdiv(0.01, dmax), 1 / (order + 1))
    h = jmin(jmin(100 * h0, h1), abs(dtmax))
    return tdir * h
