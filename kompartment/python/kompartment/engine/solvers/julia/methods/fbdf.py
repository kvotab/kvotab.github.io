"""FBDF: fixed-leading-coefficient BDF, variable step, orders 1 to 5
(``solvers/fbdf.js``).

The real history is interpolated onto a fictitious uniform grid of spacing h
and the textbook formula applied to that, so the leading coefficient -- and W
-- survive a change of step. Four error estimates (orders k-2 .. k+1), each
from the history by a Fornberg finite-difference formula, drive the order,
with CVODE's ``qwait`` countdown between changes.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

import numpy as np

from .._js import INF, jdiv, jmax, jmin, jpow, jsign
from ..integrator import algorithm
from ..newton import COEFFICIENT_MULTISTEP, CONVERGENCE

BDF_COEFFS: List[Any] = [
    None,
    [1, -1],
    [3 / 2, -2, 1 / 2],
    [11 / 6, -3, 3 / 2, -1 / 3],
    [25 / 12, -4, 3, -4 / 3, 1 / 4],
    [137 / 60, -5, 5, -10 / 3, 5 / 4, -1 / 5],
]
MAX_ORDER_LIMIT = 5


def fornberg_weights(xs: List[float], count: int, x0: float, m: int, work: List[float]) -> List[float]:
    """Fornberg's weights for the m-th derivative at x0 from the first
    ``count`` nodes, the highest derivative only (``fornbergWeights``)."""
    c = work
    stride = count
    for i in range(count * (m + 1)):
        c[i] = 0.0
    c[0] = 1.0
    c1 = 1.0
    c4 = xs[0] - x0
    for i in range(1, count):
        mn = min(i, m)
        c2 = 1.0
        c5 = c4
        c4 = xs[i] - x0
        for j in range(i):
            c3 = xs[i] - xs[j]
            c2 *= c3
            if j == i - 1:
                for k in range(mn, 0, -1):
                    c[i + k * stride] = jdiv(c1 * (k * c[(i - 1) + (k - 1) * stride] - c5 * c[(i - 1) + k * stride]),
                                             c2)
                c[i] = jdiv(-c1 * c5 * c[i - 1], c2)
            for k in range(mn, 0, -1):
                c[j + k * stride] = jdiv(c4 * c[j + k * stride] - k * c[j + (k - 1) * stride], c3)
            c[j] = jdiv(c4 * c[j], c3)
        c1 = c2
    return [c[i + m * stride] for i in range(count)]


class FBDFCache:
    def __init__(self, n: int, integ: Any, opts: Dict[str, Any]) -> None:
        self.n = n
        self.max_order = min(opts.get('max_order') or MAX_ORDER_LIMIT, MAX_ORDER_LIMIT)
        self.min_order = max(1, opts.get('min_order') or 1)
        self.order = self.min_order
        self.prev_order = self.order
        self.error_order = self.order
        self.has_fsal_last = False
        self.dtpropose = None
        K = MAX_ORDER_LIMIT + 2
        # The history's times measured from its newest point (ts[0] = 0, ts[j]
        # minus the last j steps), not the clock readings: late in a run the
        # clock's rounding is a sizeable fraction of a short step, and the
        # predictor would carry |f| times it into the error estimate.
        self.ts = [0.0] * K
        self.u_history = [np.zeros(n) for _ in range(K)]
        self.n_history = 0
        self.thetas = [0.0] * K
        self.corrector = [np.zeros(n) for _ in range(K)]
        self.upred = np.zeros(n)
        self.fd_work = [0.0] * ((K + 1) * (K + 2))
        self.terkm2 = INF
        self.terkm1 = INF
        self.terk = INF
        self.terkp1 = 0.0
        self.terkm3 = INF
        self.qwait = 3
        self.nconsteps = 0
        self.consfailcnt = 0
        self.iters_from_event = 0
        self.gamma_ctrl = opts.get('gamma') if opts.get('gamma') is not None else 1.2
        self.qmax = opts.get('qmax') if opts.get('qmax') is not None else 5
        self.qmin = opts.get('qmin') if opts.get('qmin') is not None else 0.2
        self.qsteady_min = opts.get('qsteady_min') if opts.get('qsteady_min') is not None else 0.9
        self.qsteady_max = opts.get('qsteady_max') if opts.get('qsteady_max') is not None else 1.2
        self.prev_order_pending = self.order
        self.next_order = self.order
        self.next_terk = INF

    def init(self, integ: Any) -> None:
        integ.newton.method = COEFFICIENT_MULTISTEP
        self.ts[0] = 0.0
        self.u_history[0][:] = integ.uprev
        self.n_history = 1
        self.iters_from_event = 0

    def restart(self, integ: Any) -> None:
        self.ts[0] = 0.0
        self.u_history[0][:] = integ.uprev
        self.n_history = 1
        self.iters_from_event = 0
        self.order = self.min_order
        self.prev_order = self.order
        self.qwait = 3
        self.nconsteps = 0
        self.consfailcnt = 0
        self.terkm2 = self.terkm1 = self.terk = INF
        self.terkp1 = 0.0

    def lagrange(self, xi: float, count: int) -> np.ndarray:
        """The Lagrange interpolant of the history, in theta = (tau - t)/h,
        summed as the newest point plus weighted differences from it, so that
        a component at rest stays exactly at rest (fbdf.js explains)."""
        thetas = self.thetas
        u0 = self.u_history[0]
        out = u0.copy()
        for j in range(1, count):
            w = 1.0
            for m in range(count):
                if m == j:
                    continue
                w *= jdiv(xi - thetas[m], thetas[j] - thetas[m])
            if w == 0:
                continue
            out += w * (self.u_history[j] - u0)
        return out

    def estimate_terk(self, integ: Any, m: int) -> float:
        """||h^(m-1) y^(m-1)(t+h)|| from the real history by an m-node formula."""
        dt = integ.dt
        count = min(m, self.n_history + 1)
        if count < 2:
            return INF
        ts_tmp = [dt] + [self.ts[i] for i in range(count - 1)]
        w = fornberg_weights(ts_tmp, count, dt, count - 1, self.fd_work)
        tmp = w[0] * integ.u
        for j in range(1, count):
            tmp += w[j] * self.u_history[j - 1]
        scale = jpow(abs(dt), count - 1)
        tmp *= scale
        return integ.error_norm(tmp)

    def step(self, integ: Any) -> bool:
        ts = self.ts
        thetas = self.thetas
        corrector = self.corrector
        dt = integ.dt
        uprev = integ.uprev
        t = integ.t
        newton = integ.newton
        k = min(self.order, max(1, self.n_history))
        self.order = k
        a = BDF_COEFFS[k]
        gamma = 1 / a[0]
        gamma_dt = gamma * dt
        tdt = dt  # t + dt on the history's own clock

        need_new = integ.W.jac_stale or not integ.W.have_factor or not newton.fast_convergence
        if not integ.form_w(gamma_dt, False, need_new):
            return False

        count = min(k + 1, self.n_history)
        for j in range(count):
            thetas[j] = ts[j] / dt

        if self.iters_from_event >= 1 and count >= 2:
            upred = self.lagrange(1, count)
            for i in range(1, k):
                corrector[i] = self.lagrange(-i, count)
        else:
            # The first step from a start or a restart: an Euler predictor, so
            # the predictor-corrector difference is O(h^2), as the error
            # estimate assumes (fbdf.js explains).
            upred = uprev + dt * integ.fsalfirst
            for i in range(1, k):
                corrector[i] = uprev.copy()
        self.upred = upred

        # -(a1 u_n + sum a_{m+1} u~_{n-m}) / a0, as u_n - sum a_{m+1} (u~_{n-m} - u_n) / a0.
        v = np.zeros(self.n)
        for m in range(1, k):
            v = v + a[m + 1] * (corrector[m] - uprev)
        newton.tmp[:] = uprev - v * gamma
        newton.gamma = gamma
        newton.c = 1
        newton.method = COEFFICIENT_MULTISTEP
        newton.z[:] = upred
        newton.error_constant = 1 / (k + 1)

        status = newton.solve(integ.f, integ.W, t, dt, uprev,
                              {'reltol': integ.reltol, 'abstol': integ.abstol_fixed},
                              need_new, self.consfailcnt == 0)
        integ.stats['nnonliniter'] += newton.iter
        newton.error_constant = 1
        if status != CONVERGENCE:
            integ.stats['nnonlinconvfail'] += 1
            integ.W.mark_stale()
            if self.order > 1 and newton.nfails >= 3:
                self.order -= 1
            self.consfailcnt += 1
            self.nconsteps = 0
            return False
        integ.u[:] = newton.z
        u = integ.u

        # the local error, from the predictor-corrector difference
        terkp1_tmp = u - upred
        for j in range(count):
            s = jdiv((j + 1) * dt, tdt - ts[j])
            terkp1_tmp *= s
        lte = -1 / (1 + k)
        for j in range(2, k + 1):
            r = float(1 - j)
            for m in range(2, count + 1):
                r *= jdiv((tdt - j * dt) - ts[m - 1], m * dt)
            lte -= a[j - 1] * r
        integ.eest = integ.error_norm(lte * terkp1_tmp)

        # what the order should be next
        self.terk = self.estimate_terk(integ, k + 1)
        self.terkm1 = self.estimate_terk(integ, k) if k > 1 else INF
        self.terkm2 = self.estimate_terk(integ, k - 1) if k > 2 else INF
        self.terkp1 = (self.estimate_terk(integ, k + 2)
                       if (self.qwait == 0 and k < self.max_order and self.n_history >= k + 2) else 0.0)
        self.terkm3 = self.estimate_terk(integ, k - 2) if k > 3 else INF
        self.error_order = k
        self.decide(integ)
        return True

    def interpolate(self, integ: Any, theta: float) -> np.ndarray:
        """u(t + theta h) inside the step just taken: the Lagrange interpolant
        through the new point (theta = 1) and the k points of history the step
        was taken from, as OrdinaryDiffEq's FBDF interpolates."""
        thetas = self.thetas
        m = min(self.order, self.n_history)
        w = 1.0
        for j in range(m):
            w *= jdiv(theta - thetas[j], 1 - thetas[j])
        u0 = self.u_history[0]
        out = u0 + w * (integ.u - u0)
        for a in range(1, m):
            wa = jdiv(theta - 1, thetas[a] - 1)
            for b in range(m):
                if b == a:
                    continue
                wa *= jdiv(theta - thetas[b], thetas[a] - thetas[b])
            if wa == 0:
                continue
            out += wa * (self.u_history[a] - u0)
        return out

    def decide(self, integ: Any) -> None:
        self.prev_order_pending = self.order
        k = self.order
        terk = self.terk
        terkm1, terkm2, terkp1 = self.terkm1, self.terkm2, self.terkp1

        def decreasing() -> bool:
            return terkm2 > terkm1 and terkm1 > terk and terk > terkp1

        if (k < self.max_order and self.qwait == 0
                and ((k == 1 and terk > terkp1)
                     or (k == 2 and terkm1 > terk and terk > terkp1)
                     or (k > 2 and decreasing()))):
            k += 1
            terk = terkp1
        else:
            if not decreasing() and k > max(2, self.min_order):
                terkp1 = terk
                terk = terkm1
                terkm1 = terkm2
                terkm2 = self.terkm3
                k -= 1
        self.next_order = k
        self.next_terk = terk

    def accepted(self, integ: Any, dtjust: float) -> None:
        self.prev_order = self.prev_order_pending
        k = self.next_order
        terk = self.next_terk
        if k != self.order:
            self.nconsteps = 0
            self.order = k
        if not (terk > 0):
            q = 1 / self.qmax
        else:
            alpha0 = BDF_COEFFS[k][0]
            q = jpow(jdiv(6 * terk, alpha0 * (k + 1)), 1 / (k + 1))
        q = jmin(1 / self.qmin, jmax(1 / self.qmax, q))
        if q <= self.qsteady_max and q >= self.qsteady_min:
            q = 1
        self.consfailcnt = 0
        self.nconsteps += 1
        self.iters_from_event += 1
        if self.order != self.prev_order:
            self.qwait = self.order + 2
        elif self.qwait > 0:
            self.qwait -= 1
        K = len(self.u_history)
        last = self.u_history[K - 1]
        for j in range(K - 1, 0, -1):
            self.u_history[j] = self.u_history[j - 1]
            self.ts[j] = self.ts[j - 1] - dtjust
        self.u_history[0] = last
        self.u_history[0][:] = integ.u
        self.ts[0] = 0.0
        if self.n_history < K:
            self.n_history += 1
        self.dtpropose = jdiv(dtjust, q)

    def rejected(self, integ: Any) -> bool:
        k = self.order
        h = abs(integ.dt)
        self.consfailcnt += 1
        self.nconsteps = 0
        if self.consfailcnt > 1:
            h /= 2
        zs = self.gamma_ctrl
        z = zs * jpow(integ.eest, 1 / (k + 1))
        hk = jdiv(h, z) if z <= 10 else 0.1 * h
        hn = hk
        kn = k
        if k > 1 and math.isfinite(self.terkm1):
            zk1 = 1.3 * jpow(self.terkm1, 1 / k)
            hk1 = jdiv(h, zk1) if zk1 <= 10 else 0.1 * h
            if self.consfailcnt > 2 or abs(hk1) > abs(hk):
                hn = jmin(h, abs(hk1))
                kn = k - 1
        self.order = max(self.min_order, kn)
        integ.dt = jsign(integ.dt) * hn
        self.dtpropose = None
        return True


def FBDF(**options: Any) -> Any:
    def build(n: int, integ: Any, opts: Dict[str, Any]) -> FBDFCache:
        merged = dict(opts)
        merged.update(options)
        return FBDFCache(n, integ, merged)
    return algorithm('FBDF', options.get('max_order') or MAX_ORDER_LIMIT, build,
                     {'qmax': 5, 'qmin': 0.2, 'gamma': 1.2, 'qsteady_min': 0.9, 'qsteady_max': 1.2})
