"""Singly diagonally implicit Runge-Kutta methods with an explicit first
stage: TRBDF2 and KenCarp4 (``solvers/esdirk.js``).

Each stage solves z_i = h f(t + c_i h, uprev + sum_{j<i} a_ij z_j + gamma z_i)
by the shared Newton iteration against one W = I - gamma h J. Both methods
are stiffly accurate: the solution is the last stage value and f at the end
of the step is z_s/h.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from ..integrator import algorithm
from ..newton import CONVERGENCE, DIRK
from .tableaus import KENCARP4, TRBDF2 as TRBDF2_TABLEAU


class ESDIRKCache:
    def __init__(self, n: int, tab: Any, integ: Any, opts: Dict[str, Any]) -> None:
        self.tab = tab
        self.n = n
        self.order = tab.order
        self.error_order = tab.error_order
        self.has_fsal_last = True
        self.dtpropose = None
        self.z: List[np.ndarray] = [np.zeros(n) for _ in range(tab.stages)]
        self.smooth_est = opts.get('smooth_est') is not False
        self.new_w = True

    def init(self, integ: Any) -> None:
        integ.newton.method = DIRK
        integ.newton.gamma = self.tab.gamma

    def restart(self, integ: Any = None) -> None:
        self.new_w = True

    def step(self, integ: Any) -> bool:
        tab = self.tab
        z = self.z
        dt = integ.dt
        uprev = integ.uprev
        t = integ.t
        newton = integ.newton
        gamma_dt = tab.gamma * dt
        s = tab.stages

        fresh_jac = integ.W.jac_stale or not integ.W.have_factor or not newton.fast_convergence
        gamma_moved = abs(integ.W.gamma_dt - gamma_dt) > 0.2 * abs(gamma_dt)
        if not integ.form_w(gamma_dt, False, fresh_jac):
            return False
        self.new_w = fresh_jac or gamma_moved

        z[0] = dt * integ.fsalfirst

        for stage in range(1, s):
            a = tab.a[stage]
            alpha = tab.alpha[stage]
            v = uprev.copy()
            for j in range(stage):
                v += a[j] * z[j]
            newton.tmp[:] = v
            seed = np.zeros(self.n)
            for j in range(stage):
                seed += alpha[j] * z[j]
            newton.z[:] = seed
            newton.c = tab.c[stage]
            newton.gamma = tab.gamma
            status = newton.solve(integ.f, integ.W, t, dt, uprev,
                                  {'reltol': integ.reltol, 'abstol': integ.abstol_fixed},
                                  self.new_w and stage == 1, True)
            integ.stats['nnonliniter'] += newton.iter
            if status != CONVERGENCE:
                integ.stats['nnonlinconvfail'] += 1
                integ.W.mark_stale()
                return False
            z[stage] = newton.z.copy()
            self.new_w = False

        u = uprev.copy()
        for j in range(s):
            u += tab.b[j] * z[j]
        integ.u[:] = u
        invdt = 1 / dt
        integ.fsallast[:] = z[s - 1] * invdt

        est = np.zeros(self.n)
        for j in range(s):
            bt = tab.btilde[j]
            if bt != 0:
                est += bt * z[j]
        if self.smooth_est:
            est = integ.solve_w(est)
        integ.eest = integ.error_norm(est)
        return True


def _controller(options: Dict[str, Any]) -> Dict[str, Any]:
    c = {'qmax': 10, 'qsteady_min': 1, 'qsteady_max': 1.2}
    c.update(options.get('controller') or {})
    return c


def _build(tab: Any, options: Dict[str, Any]) -> Any:
    def build(n: int, integ: Any, opts: Dict[str, Any]) -> ESDIRKCache:
        merged = dict(options)
        merged.update(opts)
        return ESDIRKCache(n, tab, integ, merged)
    return build


def TRBDF2(**options: Any) -> Any:
    return algorithm('TRBDF2', TRBDF2_TABLEAU.order, _build(TRBDF2_TABLEAU, options), _controller(options))


def KenCarp4(**options: Any) -> Any:
    return algorithm('KenCarp4', KENCARP4.order, _build(KENCARP4, options), _controller(options))


def esdirk_algorithm(tab: Any, **options: Any) -> Any:
    return algorithm(tab.name, tab.order, _build(tab, options), dict(options.get('controller') or {}))
