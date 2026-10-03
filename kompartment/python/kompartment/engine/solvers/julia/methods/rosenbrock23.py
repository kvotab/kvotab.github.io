"""Rosenbrock23: the Rosenbrock (2,3) W-method of MATLAB's ode23s, as
OrdinaryDiffEq implements it (``solvers/rosenbrock23.js``).

The stiff method DifferentialEquations.jl's default algorithm switches to for
a small system (up to 50 states) at a relative tolerance of 1e-6 or above.
With d = 1/(2 + sqrt 2) and W = I - h d J,

    W k1 = f(t, u) + h d df/dt
    W k2 = f(t + h/2, u + h/2 k1) - k1,                 then k2 += k1
    u1   = u + h k2
    W k3 = f(t + h, u1) - (6 + sqrt 2)(k2 - f1) - 2(k1 - f0) + h df/dt

and the step's error is h/6 (k1 - 2 k2 + k3). The same method as the engine's
own ``ros23`` and a different implementation of it: OrdinaryDiffEq's step
controller, error weights and norm, starting step and interpolant. W is formed
from a fresh Jacobian on every step, held as I/(h d) - J, so each solve is
multiplied by 1/(h d).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .._js import jdiv
from ..integrator import algorithm
from .rosenbrock import rosenbrock_time_derivative

D = 1 / (2 + math.sqrt(2))
C32 = 6 + math.sqrt(2)


class Rosenbrock23Cache:
    def __init__(self, n: int) -> None:
        self.n = n
        self.order = 2
        # OrdinaryDiffEq's alg_adaptive_order(Rosenbrock23) is 3; the PI
        # controller's gains are given from the method's order, 2.
        self.error_order = 3
        self.has_fsal_last = True
        self.refresh_fsal_on_clamp = True
        self.dtpropose = None
        self.k1 = np.zeros(n)
        self.k2 = np.zeros(n)

    def step(self, integ: Any) -> bool:
        t = integ.t
        dt = integ.dt
        uprev = integ.uprev
        dtgamma = dt * D
        inv = jdiv(1.0, dtgamma)
        dto2 = dt / 2
        dto6 = dt / 6
        f0 = integ.fsalfirst

        # A fresh J on every step, W = I/(h d) - J.
        if not integ.form_w(dtgamma, True, True):
            return False
        dT = rosenbrock_time_derivative(integ, t, uprev, f0)

        k1 = integ.solve_w(f0 + dtgamma * dT) * inv
        u = uprev + dto2 * k1
        f1 = integ.f(t + dto2, u)
        k2 = integ.solve_w(f1 - k1) * inv + k1
        integ.u[:] = uprev + dt * k2

        f2 = integ.f(t + dt, integ.u)
        integ.fsallast[:] = f2
        k3 = integ.solve_w(f2 - C32 * (k2 - f1) - 2 * (k1 - f0) + dt * dT) * inv

        integ.eest = integ.error_norm(dto6 * (k1 - 2 * k2 + k3))
        self.k1 = k1
        self.k2 = k2
        return True

    def interpolate(self, integ: Any, theta: float) -> np.ndarray:
        """u(t + theta*dt) by the method's own second-order interpolant (the
        MATLAB suite's): uprev + dt*(c1 k1 + c2 k2), c1 = theta(1 - theta)/(1 - 2d),
        c2 = theta(theta - 2d)/(1 - 2d)."""
        # The end of the step is the step's own solution.
        if theta == 1:
            return integ.u.copy()
        c1 = theta * (1 - theta) / (1 - 2 * D)
        c2 = theta * (theta - 2 * D) / (1 - 2 * D)
        return integ.uprev + integ.dt * (c1 * self.k1 + c2 * self.k2)


def Rosenbrock23(**options: Any) -> Any:
    """Rosenbrock23: linearly implicit, order 2 with a third-order error
    estimate, L-stable. PI step control with OrdinaryDiffEq's defaults for
    order 2: beta1 = 7/20, beta2 = 1/5, the step held where it would change by
    less than a fifth."""
    controller = {'beta1': 7 / 20, 'beta2': 1 / 5, 'gamma': 0.9, 'qmin': 0.2, 'qmax': 10, 'qsteady_min': 1,
                  'qsteady_max': 1.2, 'qoldinit': 1e-4, 'qmax_first_step': 10000}
    controller.update(options.get('controller') or {})
    return algorithm('Rosenbrock23', 2, lambda n, integ, opts: Rosenbrock23Cache(n), controller, initdt='sciml')
