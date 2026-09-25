"""Rosenbrock-Wanner methods, and Rodas5P in particular (``solvers/rosenbrock.js``).

One linear solve per stage and no nonlinear iteration: J is part of the
method, re-evaluated and W = I/(gh) - J re-factorised on every step. df/dt is
differenced with a step scaled by max(|t|, |h|).
"""

from __future__ import annotations

import math
from typing import Any, List

import numpy as np

from .._js import EPS, jmax
from ..integrator import algorithm
from .tableaus import RODAS5P


def _cbrt(x: float) -> float:
    if hasattr(math, 'cbrt'):
        return math.cbrt(x)  # type: ignore[attr-defined]
    return math.copysign(abs(x) ** (1.0 / 3.0), x)


class RosenbrockCache:
    def __init__(self, n: int, tab: Any, integ: Any) -> None:
        self.tab = tab
        self.n = n
        self.order = tab.order
        self.error_order = tab.error_order
        self.interp_order = tab.interp_order
        self.has_fsal_last = False
        self.dtpropose = None
        self.k: List[np.ndarray] = [np.zeros(n) for _ in range(tab.stages)]
        self.dense: List[np.ndarray] = [np.zeros(n) for _ in range(len(tab.H))]
        self.dense_valid = False

    def time_derivative(self, integ: Any, t: float, u: np.ndarray, fu: np.ndarray) -> np.ndarray:
        """df/dt at (t, u): the problem's, else differenced."""
        if integ.prob.tgrad is not None:
            return np.array(integ.prob.tgrad(t, u), dtype=float)
        scale = jmax(abs(t), abs(integ.dt))
        if integ.opts['central']:
            dtd = _cbrt(EPS) * scale
            out = integ.f(t + dtd, u)
            back = integ.f(t - dtd, u)
            inv = 1 / (2 * dtd)
            return (out - back) * inv
        dtd = math.sqrt(EPS) * scale
        out = integ.f(t + dtd, u)
        inv = 1 / dtd
        return (out - fu) * inv

    def step(self, integ: Any) -> bool:
        tab = self.tab
        k = self.k
        dt = integ.dt
        uprev = integ.uprev
        t = integ.t
        gamma_dt = dt * tab.gamma
        s = tab.stages

        if not integ.form_w(gamma_dt, True, True):
            return False

        dT = self.time_derivative(integ, t, uprev, integ.fsalfirst)

        du = integ.fsalfirst.copy()
        d0 = dt * tab.d[0]
        rhs = du + d0 * dT
        k[0] = integ.solve_w(rhs)

        for stage in range(1, s):
            A = tab.a[stage]
            ustage = uprev.copy()
            for j in range(stage):
                ustage += A[j] * k[j]
            du = integ.f(t + tab.c[stage] * dt, ustage)
            C = tab.C[stage]
            ds = dt * tab.d[stage]
            invdt = 1 / dt
            acc = np.zeros(self.n)
            for j in range(stage):
                acc += C[j] * k[j]
            rhs = du + ds * dT + acc * invdt
            k[stage] = integ.solve_w(rhs)

        u = uprev.copy()
        for j in range(s):
            bj = tab.b[j]
            if bj != 0:
                u += bj * k[j]
        integ.u[:] = u

        err = np.zeros(self.n)
        for j in range(s):
            bt = tab.btilde[j]
            if bt != 0:
                err += bt * k[j]
        integ.eest = integ.error_norm(err)
        self.dense_valid = False
        return True

    def accepted(self, integ: Any, dtjust: float) -> None:
        self.dense_valid = False

    def build_dense(self) -> None:
        tab = self.tab
        for j in range(len(self.dense)):
            H = tab.H[j]
            out = np.zeros(self.n)
            for m in range(tab.stages):
                h = H[m]
                if h != 0:
                    out += h * self.k[m]
            self.dense[j] = out
        self.dense_valid = True

    def interpolate(self, integ: Any, theta: float) -> np.ndarray:
        """u(t + theta*h) = (1-theta)*u0 + theta*(u1 + (1-theta)*(k1 + theta*(k2 + theta*k3)))."""
        if not self.dense_valid:
            self.build_dense()
        dense = self.dense
        t1 = 1 - theta
        m = len(dense)
        acc = dense[m - 1]
        for j in range(m - 2, -1, -1):
            acc = dense[j] + theta * acc
        return t1 * integ.uprev + theta * (integ.u + t1 * acc)


def Rodas5P(**options: Any) -> Any:
    controller = {'qmax': 10, 'qsteady_min': 1, 'qsteady_max': 1.2}
    controller.update(options.get('controller') or {})
    return algorithm('Rodas5P', RODAS5P.order, lambda n, integ, opts: RosenbrockCache(n, RODAS5P, integ), controller)


def rosenbrock_algorithm(tab: Any, **options: Any) -> Any:
    return algorithm(tab.name, tab.order, lambda n, integ, opts: RosenbrockCache(n, tab, integ),
                     dict(options.get('controller') or {}))
