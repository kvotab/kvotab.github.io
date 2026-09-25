"""QNDF: the quasi-constant-step numerical differentiation formulas of
Shampine and Reichelt, orders 1 to 5 (``solvers/qndf.js``); QBDF is QNDF with
every kappa zero.

The backward differences are rescaled onto a new step by D <- D*(R*U), so the
coefficients stay those of the uniform formula. qsteadyMin/Max are the
package's measured 0.25/4, not OrdinaryDiffEq's 0.9/1.2.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np

from .._js import INF, jdiv, jmax, jmin, jpow, jsign
from ..integrator import algorithm
from ..newton import COEFFICIENT_MULTISTEP, CONVERGENCE

KAPPA = [-0.1850, -1 / 9, -0.0823, -0.0415, 0.0]
QNDF_MAX_ORDER = 5


def _gamma_table() -> List[float]:
    g = [0.0] * (QNDF_MAX_ORDER + 1)
    for m in range(1, QNDF_MAX_ORDER + 1):
        g[m] = g[m - 1] + 1 / m
    return g


GAMMA = _gamma_table()


def rescale_matrix(out: List[float], rho: float, k: int, stride: int) -> List[float]:
    """R[j][r] = prod(m=1..j) ((m-1) - r*rho)/m, row-major (``rescaleMatrix``)."""
    for r in range(1, k + 1):
        v = -r * rho
        out[0 * stride + (r - 1)] = v
        for j in range(2, k + 1):
            v = v * ((j - 1) - r * rho) / j
            out[(j - 1) * stride + (r - 1)] = v
    return out


class QNDFCache:
    def __init__(self, n: int, integ: Any, opts: Dict[str, Any]) -> None:
        self.n = n
        self.max_order = min(opts.get('max_order') or QNDF_MAX_ORDER, QNDF_MAX_ORDER)
        self.min_order = max(1, opts.get('min_order') or 1)
        nk = opts.get('ndf_kappa')
        self.kappa = list(nk) if isinstance(nk, (list, tuple)) and len(nk) >= QNDF_MAX_ORDER else KAPPA
        self.order = self.min_order
        self.prev_order = 0
        self.error_order = self.order
        self.has_fsal_last = False
        self.dtpropose: Optional[float] = None
        self.D = [np.zeros(n) for _ in range(QNDF_MAX_ORDER + 3)]
        S = QNDF_MAX_ORDER
        self.stride = S
        self.U = rescale_matrix([0.0] * (S * S), 1, S, S)
        self.R = [0.0] * (S * S)
        self.RU = [0.0] * (S * S)
        self.u0 = np.zeros(n)
        self.dtprev = 0.0
        self.eest1 = 1.0
        self.eest2 = 1.0
        self.nconsteps = 0
        self.consfailcnt = 0
        self.started = False
        self.gamma_ctrl = opts.get('gamma') if opts.get('gamma') is not None else 1.2
        self.qmax = opts.get('qmax') if opts.get('qmax') is not None else 5
        self.qmin = opts.get('qmin') if opts.get('qmin') is not None else 0.2
        self.qsteady_min = opts.get('qsteady_min') if opts.get('qsteady_min') is not None else 0.25
        self.qsteady_max = opts.get('qsteady_max') if opts.get('qsteady_max') is not None else 4

    def error_constant_at(self, m: int) -> float:
        """kappa(m)*gamma(m) + 1/(m+1)."""
        return self.kappa[m - 1] * GAMMA[m] + 1 / (m + 1)

    def init(self, integ: Any) -> None:
        integ.newton.method = COEFFICIENT_MULTISTEP
        self.begin(integ)

    def begin(self, integ: Any) -> None:
        for d in self.D:
            d.fill(0.0)
        self.order = self.min_order
        self.prev_order = 0
        self.dtprev = 0.0
        self.nconsteps = 0
        self.consfailcnt = 0
        self.eest1 = 1.0
        self.eest2 = 1.0
        self.started = False

    def restart(self, integ: Any) -> None:
        self.begin(integ)

    def step(self, integ: Any) -> bool:
        D = self.D
        dt = integ.dt
        uprev = integ.uprev
        t = integ.t
        newton = integ.newton
        k = min(self.order, self.max_order)
        self.order = k

        if not self.started:
            D[1][:] = dt * integ.fsalfirst
            self.dtprev = dt
            self.prev_order = k
            self.started = True
        elif self.dtprev == 0:
            self.dtprev = dt
            self.prev_order = k
        elif dt != self.dtprev or self.prev_order != k:
            U, R, RU, stride = self.U, self.R, self.RU, self.stride
            rho = dt / self.dtprev
            rescale_matrix(R, rho, k, stride)
            for i in range(1, k + 1):
                for j in range(1, k + 1):
                    acc = 0.0
                    for m in range(1, k + 1):
                        acc += R[(i - 1) * stride + (m - 1)] * U[(m - 1) * stride + (j - 1)]
                    RU[(i - 1) * stride + (j - 1)] = acc
            new = []
            for j in range(1, k + 1):
                out = np.zeros(self.n)
                for i in range(1, k + 1):
                    w = RU[(i - 1) * stride + (j - 1)]
                    if w == 0:
                        continue
                    out += w * D[i]
                new.append(out)
            for j in range(1, k + 1):
                D[j][:] = new[j - 1]
            self.nconsteps = 0
            self.dtprev = dt
        self.prev_order = k

        kappa = self.kappa[k - 1]
        beta0 = 1 / ((1 - kappa) * GAMMA[k])
        gamma_dt = beta0 * dt

        need_new = integ.W.jac_stale or not integ.W.have_factor or not newton.fast_convergence
        if not integ.form_w(gamma_dt, False, need_new):
            return False

        u0 = uprev.copy()
        phi = np.zeros(self.n)
        for j in range(1, k + 1):
            u0 += D[j]
            phi += GAMMA[j] * D[j]
        self.u0 = u0

        newton.tmp[:] = u0 - beta0 * phi
        newton.gamma = beta0
        newton.c = 1
        newton.method = COEFFICIENT_MULTISTEP
        newton.z[:] = u0
        newton.error_constant = abs(self.error_constant_at(k))

        status = newton.solve(integ.f, integ.W, t, dt, uprev,
                              {'reltol': integ.reltol, 'abstol': integ.abstol_fixed},
                              need_new, self.consfailcnt == 0)
        integ.stats['nnonliniter'] += newton.iter
        newton.error_constant = 1
        if status != CONVERGENCE:
            integ.stats['nnonlinconvfail'] += 1
            integ.W.mark_stale()
            if self.order > self.min_order and newton.nfails >= 3:
                self.order -= 1
            self.consfailcnt += 1
            self.nconsteps = 0
            return False
        integ.u[:] = newton.z
        u = integ.u

        # dd = the difference the predictor missed by. The estimates read the
        # differences as they will be once the step is kept -- D[k] + dd and
        # dd - D[k+1] -- and D itself waits for `accepted`.
        dd = u - u0
        integ.eest = abs(self.error_constant_at(k)) * integ.error_norm(dd)
        self.eest1 = abs(self.error_constant_at(k - 1)) * integ.error_norm(D[k] + dd) if k > 1 else INF
        self.eest2 = (abs(self.error_constant_at(k + 1)) * integ.error_norm(dd - D[k + 1])
                      if k < self.max_order else INF)
        self.error_order = k
        return True

    def commit(self, integ: Any) -> None:
        """Roll the differences forward past the step just kept, from the state
        the integrator kept (``commit``)."""
        D = self.D
        k = self.order
        dd = integ.u - self.u0
        D[k + 2][:] = dd - D[k + 1]
        D[k + 1][:] = dd
        for j in range(k, 0, -1):
            D[j] += D[j + 1]

    def interpolate(self, integ: Any, theta: float) -> np.ndarray:
        """u(t + theta h): the backward-difference polynomial through the new
        point, u + sum_j phi_j(theta - 1) * del^j u, with the differences as they
        stand once the step is kept."""
        D = self.D
        k = self.order
        s = theta - 1
        p = s
        phi = [0.0] * (k + 2)
        phi[1] = p
        for j in range(1, k):
            p = p * (s + j) / (j + 1)
            phi[j + 1] = p
        u = integ.u
        acc = u - self.u0
        cols: List[Any] = [None] * (k + 2)
        for j in range(k, 0, -1):
            acc = D[j] + acc
            cols[j] = acc
        v = u.copy()
        for j in range(1, k + 1):
            v += phi[j] * cols[j]
        return v

    def accepted(self, integ: Any, dtjust: float) -> None:
        self.commit(integ)
        self.consfailcnt = 0
        self.nconsteps += 1
        k = self.order
        h = abs(dtjust)
        if not (integ.eest > 0):
            self.dtpropose = dtjust * self.qmax
            return
        prefer_const_step = self.nconsteps < k + 2
        zs = self.gamma_ctrl
        z = zs * jpow(integ.eest, 1 / (k + 1))
        hk = 10 * h if z <= 0.1 else jdiv(h, z)
        hn = hk
        kn = k
        if k > 1 and math.isfinite(self.eest1):
            zm = 1.3 * jpow(self.eest1, 1 / k)
            hm = 0.0
            if zm <= 0.1:
                hm = 10 * h
            elif zm <= 1.3:
                hm = jdiv(h, zm)
            if hm > hk:
                hn = hm
                kn = k - 1
        if k < self.max_order and math.isfinite(self.eest2):
            zp = 1.4 * jpow(self.eest2, 1 / (k + 2))
            hp = 0.0
            if zp <= 0.1:
                hp = 10 * h
            elif zp <= 1.4:
                hp = jdiv(h, zp)
            if hp > hn:
                hn = hp
                kn = k + 1
        self.order = max(self.min_order, kn)
        q = jdiv(h, hn)
        if prefer_const_step and q > 0.6 and q < 1.2:
            hnew = h
        elif q <= self.qsteady_max and q >= self.qsteady_min:
            hnew = h
        else:
            hnew = jdiv(h, jmin(1 / self.qmin, jmax(1 / self.qmax, q)))
        self.dtpropose = jsign(dtjust) * hnew

    def rejected(self, integ: Any) -> bool:
        k = self.order
        h = abs(integ.dt)
        self.consfailcnt += 1
        self.nconsteps = 0
        if self.consfailcnt > 1:
            h /= 2
        z = self.gamma_ctrl * jpow(integ.eest, 1 / (k + 1))
        hk = jdiv(h, z) if z <= 10 else 0.1 * h
        hn = hk
        kn = k
        if k > 1 and math.isfinite(self.eest1):
            zm = 1.3 * jpow(self.eest1, 1 / k)
            hm = jdiv(h, zm) if zm <= 10 else 0.1 * h
            if self.consfailcnt > 2 or abs(hm) > abs(hk):
                hn = jmin(h, abs(hm))
                kn = k - 1
        self.order = max(self.min_order, kn)
        integ.dt = jsign(integ.dt) * hn
        self.dtpropose = None
        return True


def QNDF(**options: Any) -> Any:
    def build(n: int, integ: Any, opts: Dict[str, Any]) -> QNDFCache:
        merged = dict(opts)
        merged.update(options)
        merged['ndf_kappa'] = options.get('kappa')
        return QNDFCache(n, integ, merged)
    return algorithm('QNDF', options.get('max_order') or QNDF_MAX_ORDER, build,
                     {'qmax': 5, 'qmin': 0.2, 'gamma': 1.2, 'qsteady_min': 0.25, 'qsteady_max': 4})


def QBDF(**options: Any) -> Any:
    """QNDF with every kappa zero: the plain variable-step BDF."""
    merged = dict(options)
    merged['kappa'] = [0, 0, 0, 0, 0]
    return QNDF(**merged)
