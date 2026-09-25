"""RadauIIA5: three-stage Radau IIA collocation, order 5 (``solvers/radau.js``).

The 3n x 3n Newton system splits, in the eigenbasis of the inverse Butcher
matrix, into one real n x n solve with (gamma/h)I - J and one complex solve
with ((alpha + i beta)/h)I - J, the latter always dense. Hairer's transformed
tolerances, rtol' = rtol^(2/3)/10 and atol' = rtol'*(atol/rtol), per
component.
"""

from __future__ import annotations

import math
from typing import Any, Dict

import numpy as np

from .._js import EPS, jdiv, jmax, jpow, seq_sum
from ..integrator import algorithm
from ..linalg import ComplexDenseLU
from .tableaus import RADAU_IIA5


class RadauCache:
    def __init__(self, n: int, integ: Any, opts: Dict[str, Any]) -> None:
        self.n = n
        self.tab = RADAU_IIA5
        self.order = 5
        self.error_order = 3
        self.has_fsal_last = True
        self.dtpropose = None
        self.kappa = opts.get('kappa') if opts.get('kappa') is not None else 0.01
        self.max_iters = opts.get('max_iters') if opts.get('max_iters') is not None else 10
        self.fast_convergence_cutoff = (opts.get('fast_convergence_cutoff')
                                        if opts.get('fast_convergence_cutoff') is not None else 0.2)
        self.smooth_est = opts.get('smooth_est') is not False
        self.z1 = np.zeros(n)
        self.z2 = np.zeros(n)
        self.z3 = np.zeros(n)
        self.w1 = np.zeros(n)
        self.w2 = np.zeros(n)
        self.w3 = np.zeros(n)
        self.clu = ComplexDenseLU(n)
        # The last accepted step's collocation polynomial (cont1..cont3): what
        # the next starting guess is extrapolated from.
        self.cont1 = np.zeros(n)
        self.cont2 = np.zeros(n)
        self.cont3 = np.zeros(n)
        self.dtprev = 1.0
        self.complex_valid = False
        self.complex_dt = math.nan
        self.have_history = False
        self.eta_old = 1.0
        self.status = 'Convergence'
        self.iter = 0

    def restart(self, integ: Any = None) -> None:
        self.have_history = False
        self.complex_valid = False
        self.eta_old = 1.0
        self.dtprev = 1.0

    def scaled_norm(self, v: np.ndarray, integ: Any, atol: Any, rtol: float) -> float:
        """The weighted rms Radau measures its iterate and error in; ``atol`` is
        a number or one per component."""
        w = atol + rtol * np.maximum(np.abs(integ.uprev), np.abs(integ.u))
        r = v / w
        return math.sqrt(seq_sum(r * r) / self.n)

    def form_complex_w(self, integ: Any, alpha_dt: float, beta_dt: float) -> bool:
        """((alpha + i beta)/h) I - J, from whichever storage J is in."""
        n = self.n
        jc = integ.jac_cache
        re = np.zeros((n, n))
        if jc.sparse:
            col_ptr, row_idx = jc.pattern
            cols = np.repeat(np.arange(n), np.diff(col_ptr))
            re[row_idx, cols] = -jc.values
        else:
            np.negative(jc.J, out=re)
        C = np.empty((n, n), dtype=complex)
        diag = np.arange(n)
        re[diag, diag] += alpha_dt
        im = np.zeros((n, n))
        im[diag, diag] += beta_dt
        C.real = re
        C.imag = im
        return self.clu.factor(C)

    def step(self, integ: Any) -> bool:
        n = self.n
        tab = self.tab
        dt = integ.dt
        uprev = integ.uprev
        t = integ.t
        z1, z2, z3 = self.z1, self.z2, self.z3
        w1, w2, w3 = self.w1, self.w2, self.w3

        reltol = integ.reltol
        rtol_r = jpow(reltol, 2 / 3) / 10
        scale = rtol_r / reltol
        if np.ndim(integ.abstol) == 0:
            atol_r: Any = integ.abstol * scale
        else:
            atol_r = integ.abstol * scale

        gamma_dt = tab.gamma / dt
        alpha_dt = tab.alpha / dt
        beta_dt = tab.beta / dt

        need_new = integ.W.jac_stale or not integ.W.have_factor or self.status != 'FastConvergence'
        # The complex half follows every renewal of J, including one for age.
        jacs_before = integ.jac_cache.njac
        if not integ.form_w(dt / tab.gamma, True, need_new):
            return False
        jac_renewed = integ.jac_cache.njac != jacs_before
        if need_new or jac_renewed or not self.complex_valid or self.complex_dt != dt:
            if not self.form_complex_w(integ, alpha_dt, beta_dt):
                return False
            self.complex_valid = True
            self.complex_dt = dt
        integ.stats['nw'] = integ.W.nfactor

        # --- the starting guess ----------------------------------------------------------
        if not self.have_history:
            z1.fill(0.0)
            z2.fill(0.0)
            z3.fill(0.0)
            w1.fill(0.0)
            w2.fill(0.0)
            w3.fill(0.0)
        else:
            # Extrapolated from the last accepted step's polynomial, never from
            # the stages of a rejected or failed attempt.
            c1 = tab.c1
            c2 = tab.c2
            c1m1 = c1 - 1
            c2m1 = c2 - 1
            c3p = dt / self.dtprev
            c1p = c1 * c3p
            c2p = c2 * c3p
            a1 = self.cont1
            a2 = self.cont2
            a3 = self.cont3
            z1[:] = c1p * (a1 + (c1p - c2m1) * (a2 + (c1p - c1m1) * a3))
            z2[:] = c2p * (a1 + (c2p - c2m1) * (a2 + (c2p - c1m1) * a3))
            z3[:] = c3p * (a1 + (c3p - c2m1) * (a2 + (c3p - c1m1) * a3))
            # Kept at or above zero where the caller asked for that: the
            # polynomial is from before the step was projected back to zero,
            # and carried on below zero it met rates that are flat there
            # (radau.js explains).
            nn = integ.non_negative
            if nn is not None:
                floor = -uprev
                for z in (z1, z2, z3):
                    low = nn & (z < floor)
                    z[low] = floor[low]
            w1[:] = tab.TI11 * z1 + tab.TI12 * z2 + tab.TI13 * z3
            w2[:] = tab.TI21 * z1 + tab.TI22 * z2 + tab.TI23 * z3
            w3[:] = tab.TI31 * z1 + tab.TI32 * z2 + tab.TI33 * z3

        # --- Newton ----------------------------------------------------------------------
        eta = jpow(jmax(self.eta_old, EPS), 0.8)
        ndw = 1.0
        converged = False
        it = 0
        while it < self.max_iters:
            it += 1
            ff1 = integ.f(t + tab.c1 * dt, uprev + z1)
            ff2 = integ.f(t + tab.c2 * dt, uprev + z2)
            ff3 = integ.f(t + dt, uprev + z3)

            fw1 = tab.TI11 * ff1 + tab.TI12 * ff2 + tab.TI13 * ff3
            fw2 = tab.TI21 * ff1 + tab.TI22 * ff2 + tab.TI23 * ff3
            fw3 = tab.TI31 * ff1 + tab.TI32 * ff2 + tab.TI33 * ff3
            rhs1 = fw1 - gamma_dt * w1
            rhs2 = fw2 - alpha_dt * w2 + beta_dt * w3
            rhs3 = fw3 - beta_dt * w2 - alpha_dt * w3
            rhs1 = integ.solve_w(rhs1)
            b = np.empty(n, dtype=complex)
            b.real = rhs2
            b.imag = rhs3
            x = self.clu.solve(b)
            rhs2 = np.ascontiguousarray(x.real)
            rhs3 = np.ascontiguousarray(x.imag)
            integ.W.nsolve += 1

            ndw_prev = ndw
            ndw = (self.scaled_norm(rhs1, integ, atol_r, rtol_r)
                   + self.scaled_norm(rhs2, integ, atol_r, rtol_r)
                   + self.scaled_norm(rhs3, integ, atol_r, rtol_r))
            if not math.isfinite(ndw):
                break

            if it > 1:
                theta = jdiv(ndw, ndw_prev)
                diverging = theta > 1
                crawling = ndw * jpow(theta, self.max_iters - it) > self.kappa * (1 - theta)
                if diverging or crawling:
                    self.status = 'Divergence'
                    break
                eta = jdiv(theta, 1 - theta)

            w1 += rhs1
            w2 += rhs2
            w3 += rhs3
            z1[:] = tab.T11 * w1 + tab.T12 * w2 + tab.T13 * w3
            z2[:] = tab.T21 * w1 + tab.T22 * w2 + tab.T23 * w3
            z3[:] = tab.T31 * w1 + w2

            if eta * ndw < self.kappa and (it > 1 or ndw == 0 or self.have_history):
                converged = True
                self.status = 'FastConvergence' if eta < self.fast_convergence_cutoff else 'Convergence'
                break
        integ.stats['nnonliniter'] += it
        self.iter = it
        if not converged:
            integ.stats['nnonlinconvfail'] += 1
            integ.W.mark_stale()
            return False
        self.eta_old = eta

        integ.u[:] = uprev + z3

        # --- the error estimate ----------------------------------------------------------
        e1dt = tab.e1 / dt
        e2dt = tab.e2 / dt
        e3dt = tab.e3 / dt
        utilde = integ.fsalfirst + e1dt * z1 + e2dt * z2 + e3dt * z3
        if self.smooth_est:
            utilde = integ.solve_w(utilde)
        eest = self.scaled_norm(utilde, integ, atol_r, rtol_r)

        if not (eest < 1) and not self.have_history:
            ff1 = integ.f(t, uprev + utilde)
            utilde = ff1 + e1dt * z1 + e2dt * z2 + e3dt * z3
            if self.smooth_est:
                utilde = integ.solve_w(utilde)
            eest = self.scaled_norm(utilde, integ, atol_r, rtol_r)
        integ.eest = eest

        integ.fsallast[:] = integ.f(t + dt, integ.u)
        return True

    def accepted(self, integ: Any, dtjust: float) -> None:
        self.dtprev = dtjust
        self.have_history = True
        tab = self.tab
        c1 = tab.c1
        c2 = tab.c2
        c1m1 = c1 - 1
        c2m1 = c2 - 1
        c1mc2 = c1 - c2
        z1, z2, z3 = self.z1, self.z2, self.z3
        a1 = (z2 - z3) / c2m1
        tmp = (z1 - z2) / c1mc2
        a2 = (tmp - a1) / c1m1
        self.cont1 = a1
        self.cont2 = a2
        self.cont3 = a2 - (tmp - z1 / c1) / c2

    def interpolate(self, integ: Any, theta: float) -> np.ndarray:
        """The collocation polynomial through the three stages, in Newton form
        about the nodes 1, c2, c1."""
        tab = self.tab
        z1, z2, z3 = self.z1, self.z2, self.z3
        c1 = tab.c1
        c2 = tab.c2
        c1m1 = c1 - 1
        c2m1 = c2 - 1
        c1mc2 = c1 - c2
        th1 = theta - 1
        k1 = (z2 - z3) / c2m1
        tmp = (z1 - z2) / c1mc2
        k2 = (tmp - k1) / c1m1
        k3 = k2 - (tmp - z1 / c1) / c2
        return integ.uprev + z3 + th1 * (k1 + (theta - c2) * (k2 + (theta - c1) * k3))


def RadauIIA5(**options: Any) -> Any:
    def build(n: int, integ: Any, opts: Dict[str, Any]) -> RadauCache:
        merged = dict(opts)
        merged.update(options)
        return RadauCache(n, integ, merged)
    controller = {'qmax': 8, 'qmin': 0.125, 'gamma': 0.9, 'qsteady_min': 1, 'qsteady_max': 1.2}
    controller.update(options.get('controller') or {})
    return algorithm('RadauIIA5', 5, build, controller)
