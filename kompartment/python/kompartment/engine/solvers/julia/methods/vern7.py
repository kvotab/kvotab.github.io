"""Vern7: Verner's "most efficient" explicit Runge-Kutta pair of order 7(6)
(``solvers/vern7.js``).

The non-stiff method DifferentialEquations.jl's default algorithm takes below
a relative tolerance of 1e-6. Ten stages a step and not first same as last,
so ten evaluations of f, the first of them f at the step's start, which the
integrator already holds. Its seventh-order interpolant needs six stages
more; they are worked out only when a point inside the step is asked for,
once per step ("lazy", OrdinaryDiffEq's default).

Inside the automatic switch it estimates the largest eigenvalue as Tsit5 does
(:func:`.tsit5.explicit_stiffness`), from the difference of stages 10 and 9
over the difference of the solution and stage 10's point.
"""

from __future__ import annotations

from typing import Any, List, Sequence, Tuple

import numpy as np

from ..integrator import algorithm
from .tableaus import VERN7
from .tsit5 import explicit_stiffness


def _terms(row: Sequence[float]) -> List[Tuple[int, float]]:
    """A row's nonzero coefficients, in the source's order, so a stage sums
    exactly the terms OrdinaryDiffEq writes out and no zeros."""
    return [(j, v) for j, v in enumerate(row) if v != 0]


class Vern7Cache:
    def __init__(self, n: int, tab: Any) -> None:
        self.n = n
        # Never reads J or W (see the integrator's ageing of the Jacobian).
        self.explicit = True
        self.tab = tab
        self.order = tab.order
        self.error_order = tab.error_order
        self.stability_size = tab.stability_size
        self.has_fsal_last = False
        self.dtpropose = None
        # Stages 1..10 of the step, and 11..16 for the interpolant.
        self.k: List[np.ndarray] = [np.zeros(n) for _ in range(16)]
        self.extra_valid = False
        self.rows = [_terms(row) for row in tab.a]
        self.extra_rows = [_terms(row) for row in tab.extra_a]
        self.b_terms = _terms(tab.b)
        self.e_terms = _terms(tab.btilde)

    def combine(self, uprev: np.ndarray, dt: float, terms: List[Tuple[int, float]]) -> np.ndarray:
        """uprev + dt*sum coefficient*k over ``terms``."""
        k = self.k
        j0, v0 = terms[0]
        acc = v0 * k[j0]
        for j, v in terms[1:]:
            acc = acc + v * k[j]
        return uprev + dt * acc

    def step(self, integ: Any) -> bool:
        k = self.k
        c = self.tab.c
        t = integ.t
        dt = integ.dt
        uprev = integ.uprev
        f = integ.f

        k[0] = integ.fsalfirst.copy()
        tmp = uprev
        for s in range(1, 10):
            tmp = self.combine(uprev, dt, self.rows[s])
            k[s] = f(t + c[s] * dt, tmp)
        # tmp now holds stage 10's point, which the stiffness estimate reads.
        integ.u[:] = self.combine(uprev, dt, self.b_terms)
        self.extra_valid = False

        if integ.is_composite:
            integ.eigen_est = explicit_stiffness(k[8], k[9], tmp, integ.u, integ.still_is_stiff)

        e = self.e_terms
        acc = e[0][1] * k[e[0][0]]
        for j, v in e[1:]:
            acc = acc + v * k[j]
        integ.eest = integ.error_norm(dt * acc)
        return True

    def extra_stages(self, integ: Any) -> None:
        """Stages 11..16, for the interpolant: six more evaluations, once a step."""
        tab = self.tab
        t = integ.t
        dt = integ.dt
        uprev = integ.uprev
        for m in range(6):
            tmp = self.combine(uprev, dt, self.extra_rows[m])
            self.k[10 + m] = integ.f(t + tab.extra_c[m] * dt, tmp)
        self.extra_valid = True

    def interpolate(self, integ: Any, theta: float) -> np.ndarray:
        """u(t + theta*dt) by Verner's seventh-order interpolant, over stages
        1, 4..9 and 11..16: b1 = theta*p1(theta), the others theta^2*pj(theta)."""
        # The end of the step is the step's own solution: OrdinaryDiffEq saves
        # u itself at a requested time the step lands on, and would otherwise
        # work out six stages to reproduce it.
        if theta == 1:
            return integ.u.copy()
        if not self.extra_valid:
            self.extra_stages(integ)
        tab = self.tab
        k = self.k
        stages = tab.interp_stages
        th2 = theta * theta
        w = []
        for q, r in enumerate(tab.interp):
            p = r[-1]
            for d in range(len(r) - 2, -1, -1):
                p = r[d] + theta * p
            w.append((theta if q == 0 else th2) * p)
        acc = k[stages[0] - 1] * w[0]
        for q in range(1, len(stages)):
            acc = acc + k[stages[q] - 1] * w[q]
        return integ.uprev + integ.dt * acc


def Vern7(**options: Any) -> Any:
    """Vern7: explicit, order 7(6), ten stages a step and six more for a point
    inside one. PI step control with OrdinaryDiffEq's defaults for order 7:
    beta1 = 1/10, beta2 = 2/35."""
    controller = {'beta1': 7 / 70, 'beta2': 2 / 35, 'gamma': 0.9, 'qmin': 0.2, 'qmax': 10, 'qsteady_min': 1,
                  'qsteady_max': 1, 'qoldinit': 1e-4, 'qmax_first_step': 10000}
    controller.update(options.get('controller') or {})
    return algorithm('Vern7', 7, lambda n, integ, opts: Vern7Cache(n, VERN7), controller,
                     stability_size=VERN7.stability_size, initdt='sciml')
