"""Tsit5: Tsitouras's explicit Runge-Kutta pair of order 5(4) (``solvers/tsit5.js``).

The non-stiff method DifferentialEquations.jl recommends first, and the one
its default algorithm starts on. Seven stages, the last of which is f at the
new solution, so a step costs six evaluations of f; the error estimate is the
embedded fourth-order solution's difference, and the free fourth-order
interpolant is what saved rows and event location are read off.

An explicit method asks for no Jacobian, so the integrator never forms one
while it runs. Inside the automatic switch each step also estimates the
largest eigenvalue from its last two stages, |lambda| ~ ||(k7 - k6) /
(g7 - g6)||_inf (Hairer & Wanner II, p. 22), and leaves it in
``integ.eigen_est``.
"""

from __future__ import annotations

from typing import Any, List

import numpy as np

from .._js import max_or_zero
from ..integrator import algorithm
from .tableaus import TSIT5


def explicit_stiffness(ka: np.ndarray, kb: np.ndarray, ga: np.ndarray, gb: np.ndarray,
                       still_is_stiff: bool = False) -> float:
    """The spectral-radius estimate of OrdinaryDiffEq's explicit methods from
    two stages: the largest |(kb - ka)_i / (gb - ga)_i| (``explicitStiffness``).

    A NaN makes the whole estimate NaN, as Julia's norm(., Inf) does, and the
    switch reads a NaN as stiff. A component that has not moved at all between
    the two stages -- both differences exactly zero -- is passed over, a
    deliberate difference from OrdinaryDiffEq, where 0/0 makes a single state
    at rest enough for every step to be judged stiff; ``still_is_stiff``
    restores Julia's reading.
    """
    num = kb - ka
    den = gb - ga
    with np.errstate(divide='ignore', invalid='ignore'):
        r = np.abs(num / den)
    if not still_is_stiff:
        r = r[~((num == 0) & (den == 0))]
    return max_or_zero(r)


class Tsit5Cache:
    def __init__(self, n: int, tab: Any) -> None:
        self.n = n
        # Never reads J or W (see the integrator's ageing of the Jacobian).
        self.explicit = True
        self.tab = tab
        self.order = tab.order
        self.error_order = tab.error_order
        self.stability_size = tab.stability_size
        self.has_fsal_last = True
        # A clamped solution is not the point k7 was evaluated at; f is taken
        # again there, as OrdinaryDiffEq does after a callback changes u.
        self.refresh_fsal_on_clamp = True
        self.dtpropose = None
        self.k: List[np.ndarray] = [np.zeros(n) for _ in range(tab.stages)]

    def step(self, integ: Any) -> bool:
        tab = self.tab
        a = tab.a
        c = tab.c
        btilde = tab.btilde
        k = self.k
        t = integ.t
        dt = integ.dt
        uprev = integ.uprev
        f = integ.f

        k[0] = integ.fsalfirst.copy()
        # Stages 2..6 at their own times; stage 6 is at t + dt, and the point
        # it is evaluated at (g6) stays in tmp for the stiffness estimate.
        a2 = dt * a[1][0]
        tmp = uprev + a2 * k[0]
        k[1] = f(t + c[1] * dt, tmp)
        for s in range(2, 6):
            row = a[s]
            acc = row[0] * k[0]
            for j in range(1, s):
                acc = acc + row[j] * k[j]
            tmp = uprev + dt * acc
            k[s] = f(t + c[s] * dt, tmp)
        # The solution is stage 7's point, and k7 = f(u) is the next step's k1.
        row = a[6]
        acc = row[0] * k[0]
        for j in range(1, 6):
            acc = acc + row[j] * k[j]
        integ.u[:] = uprev + dt * acc
        k[6] = f(t + dt, integ.u)
        integ.fsallast[:] = k[6]

        if integ.is_composite:
            integ.eigen_est = explicit_stiffness(k[5], k[6], tmp, integ.u, integ.still_is_stiff)

        acc = btilde[0] * k[0]
        for j in range(1, 7):
            acc = acc + btilde[j] * k[j]
        integ.eest = integ.error_norm(dt * acc)
        return True

    def interpolate(self, integ: Any, theta: float) -> np.ndarray:
        """u(t + theta*dt) by Tsitouras's free interpolant, fourth order:
        uprev + dt*sum_j bj(theta)*kj, b1 = theta*p1(theta), bj = theta^2*pj(theta)."""
        # The end of the step is the step's own solution, as OrdinaryDiffEq
        # saves u itself at a requested time the step lands on.
        if theta == 1:
            return integ.u.copy()
        r = self.tab.interp
        k = self.k
        th2 = theta * theta
        r0 = r[0]
        w = [theta * (r0[0] + theta * (r0[1] + theta * (r0[2] + theta * r0[3])))]
        for j in range(1, 7):
            rj = r[j]
            w.append(th2 * (rj[0] + theta * (rj[1] + theta * rj[2])))
        acc = k[0] * w[0]
        for j in range(1, 7):
            acc = acc + k[j] * w[j]
        return integ.uprev + integ.dt * acc


def Tsit5(**options: Any) -> Any:
    """Tsit5: explicit, order 5(4). OrdinaryDiffEq's PI controller with its
    defaults for a fifth-order method: beta1 = 7/50, beta2 = 2/25, a safety
    factor of 9/10, a step at most ten times the last (ten thousand after the
    first accepted one) and at least a fifth of it."""
    controller = {'beta1': 7 / 50, 'beta2': 2 / 25, 'gamma': 0.9, 'qmin': 0.2, 'qmax': 10, 'qsteady_min': 1,
                  'qsteady_max': 1, 'qoldinit': 1e-4, 'qmax_first_step': 10000}
    controller.update(options.get('controller') or {})
    return algorithm('Tsit5', 5, lambda n, integ, opts: Tsit5Cache(n, TSIT5), controller,
                     stability_size=TSIT5.stability_size, initdt='sciml')
