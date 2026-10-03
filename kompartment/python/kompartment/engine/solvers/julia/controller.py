"""The next step size from the error estimate (``core/controller.js``).

OrdinaryDiffEq's PI controller -- beta1 = 7/(10k), beta2 = 2/(5k), gamma 9/10,
qmin 1/5, qmax 10, qoldinit 1e-4 -- Hairer's starting step, and
OrdinaryDiffEq's own (``initialStepSciML``) for the methods ported with it.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Optional

import numpy as np

from ....jsmath import log10 as js_log10
from ._js import EPS, INF, MIN_VALUE, jdiv, jmax, jmin, jpow, max_or_zero, seq_sum


class PIController:
    """``PIController``: ``accept`` and ``reject`` answer the next step."""

    def __init__(self, order: float, beta1: Optional[float] = None, beta2: Optional[float] = None,
                 gamma: Optional[float] = None, qmin: Optional[float] = None, qmax: Optional[float] = None,
                 qsteady_min: Optional[float] = None, qsteady_max: Optional[float] = None,
                 qoldinit: Optional[float] = None, qmax_first_step: Optional[float] = None) -> None:
        k = order
        self.beta1 = beta1 if beta1 is not None else 7 / (10 * k)
        self.beta2 = beta2 if beta2 is not None else 2 / (5 * k)
        self.gamma = gamma if gamma is not None else 0.9
        self.qmin = qmin if qmin is not None else 0.2
        self.qmax = qmax if qmax is not None else 10
        self.qsteady_min = qsteady_min if qsteady_min is not None else 1
        self.qsteady_max = qsteady_max if qsteady_max is not None else 1.2
        self.qoldinit = qoldinit if qoldinit is not None else 1e-4
        # OrdinaryDiffEq's qmax_first_step: the growth allowed after the run's
        # first accepted step, the starting step being only an estimate. Only
        # the methods ported with it set it; the older ports keep qmax
        # throughout, as they were checked with.
        self.qmax_first_step = qmax_first_step if qmax_first_step is not None else 0
        self.errold = self.qoldinit
        self.q11 = 1.0

    def set_order(self, k: float) -> None:
        self.beta1 = 7 / (10 * k)
        self.beta2 = 2 / (5 * k)

    def q(self, eest: float, first: bool = False) -> float:
        qmax = self.qmax_first_step if (first and self.qmax_first_step > 0) else self.qmax
        if eest == 0:
            return 1 / qmax
        self.q11 = jpow(eest, self.beta1)
        q = jdiv(self.q11, jpow(self.errold, self.beta2))
        q /= self.gamma
        return jmin(1 / self.qmin, jmax(1 / qmax, q))

    def accept(self, eest: float, dt: float, first: bool = False) -> float:
        """dtnew after an accepted step; ``first`` says it is the run's first
        accepted step, for ``qmax_first_step``."""
        q = self.q(eest, first)
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


def next_up(x: float) -> float:
    """The next double above x, Julia's ``nextfloat``, for finite x >= 0 (``nextUp``)."""
    if x == 0:
        return MIN_VALUE
    return math.nextafter(x, INF)


def eps_of(x: float) -> float:
    """Julia's ``eps(x)``: the gap from |x| to the next double, the smallest
    double at zero (``epsOf``)."""
    a = abs(x)
    if a == 0:
        return MIN_VALUE
    return next_up(a) - a


def initial_step_sciml(f: Callable[[float, np.ndarray], np.ndarray], t0: float, u0: np.ndarray, f0: np.ndarray,
                       tdir: float, order: float, reltol: float, abstol: Any, dtmax: float, norm: str = 'rms',
                       dtmin: float = 0.0) -> float:
    """The starting step as OrdinaryDiffEq's ``ode_determine_initdt`` takes it,
    for the methods ported with it (``initialStepSciML``).

    The same two Euler probes as :func:`initial_step`, but the refinement is
    the p-th root of the method's order (not one more), the first probe is
    held to dtmax, an f that did not change at all answers a hundred times the
    first probe, and a first probe below machine epsilon falls back to a
    default. ``norm`` is the integrator's; the run passes dtmax at most the
    span, as OrdinaryDiffEq's default is. ``log10`` is V8's
    (:mod:`kompartment.jsmath`), so the step is the application's to the bit
    wherever the power is. Signed, in the direction of tdir.
    """
    n = u0.size
    if norm == 'max':
        def measure(v: np.ndarray) -> float:
            return max_or_zero(np.abs(v))
    else:
        def measure(v: np.ndarray) -> float:
            return math.sqrt(seq_sum(v * v) / n)
    dtmin_user = dtmin if dtmin > 0 else 0.0
    dtmin_ = next_up(jmax(dtmin_user, eps_of(t0)))
    smalldt = jmax(dtmin_, 1e-6)
    dtmax_abs = abs(dtmax)

    w = abstol + np.abs(u0) * reltol
    d0 = measure(u0 / w)
    d1 = measure(f0 / w)
    if d1 != d1:
        return tdir * dtmin_

    dt0 = smalldt if (d0 < 1e-5 or d1 < 1e-5) else jdiv(jdiv(d0, d1), 100)
    dt0 = jmin(dt0, dtmax_abs)
    tiny_first = dt0 < 10 * EPS

    def fallback(dt: float) -> float:
        if tiny_first and (not math.isfinite(dt) or abs(dt) < 10 * EPS):
            return tdir * jmax(smalldt, dtmin_)
        return dt

    u1 = u0 + tdir * dt0 * f0
    f1 = f(t0 + tdir * dt0, u1)
    if n > 0 and bool(np.all(f0 == f1)):
        return fallback(tdir * jmax(dtmin_, 100 * dt0))

    d2 = jdiv(measure((f1 - f0) / w), dt0)
    m = jmax(d1, d2)
    dt1 = jmax(1e-6, dt0 * 1e-3) if m <= 1e-15 else jpow(10.0, jdiv(-(2 + js_log10(m)), order))
    return fallback(tdir * jmax(dtmin_, jmin(jmin(100 * dt0, dt1), dtmax_abs)))
