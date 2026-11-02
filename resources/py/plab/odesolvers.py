"""The ODE solvers behind ode113, ode78, ode89, ode15s, ode23s, ode23t,
ode23tb and ode15i. (ode45 and ode23 are SciPy's RK45 and RK23, the
Dormand-Prince and Bogacki-Shampine pairs those two names stand for.)

Each is a scipy.integrate.OdeSolver, so solve_ivp drives it: output times,
events and the interpolant kept in sol = ode...(...) work as for SciPy's
own. An error is measured as SciPy measures it: the root mean square of
err ./ (AbsTol + RelTol*|y|).

  Adams          ode113   Adams-Bashforth-Moulton PECE of variable step
                          and order (1 to 12): Shampine and Gordon's STEP
                          and INTRP as they are in SLATEC's DDEABM (public
                          domain), translated line for line.
  Verner78, 89   ode78,   Verner's 8(7) and 9(8) Runge-Kutta pairs, with
                 ode89    interpolants of order 7 and 8 (vernertab.py).
  NDF            ode15s,  the numerical differentiation formulas of order 1
                 ode15i   to 5 (or the plain BDFs), quasi-constant step:
                          SciPy's BDF, written for M(t, y) y' = f(t, y)
                          with M singular too, and for F(t, y, y') = 0.
  Rosenbrock23   ode23s   the modified Rosenbrock pair of order 2(3) of
                          Shampine and Reichelt, "The MATLAB ODE Suite",
                          SIAM J. Sci. Comput. 18 (1997) 1-22.
  Trapezoid      ode23t   the trapezoidal rule with its free interpolant.
  TRBDF2         ode23tb  a trapezoidal stage, then a BDF2 one: Bank et
                          al. (1985), as Hosea and Shampine, Appl. Numer.
                          Math. 20 (1996) 21-37, implement it.

The implicit ones take a mass matrix M (constant, or a function of t and
y); ode15s and ode23t also take a singular one (an index-1 DAE), after
moving the algebraic part of y0 until its equations hold.

NDF is SciPy's BDF (scipy/integrate/_ivp/bdf.py) and _initial_step is its
select_initial_step: BSD 3-clause license, Copyright (c) 2001-2002
Enthought, Inc. 2003, SciPy Developers.
"""
import math

import numpy as np
from scipy.linalg import lu_factor, lu_solve
from scipy.integrate import OdeSolver, DenseOutput

EPS = np.finfo(float).eps
SAFETY = 0.9
MIN_FACTOR = 0.2
MAX_FACTOR = 10.0
NEWTON_MAXITER = 4


class SolverError(Exception):
    """A problem the solver cannot take (the message says why)."""


def _norm(x):
    """The root mean square."""
    return np.linalg.norm(x) / x.size ** 0.5


def _tols(rtol, atol, n):
    rtol = max(float(rtol), 100 * EPS)
    atol = np.asarray(atol, float)
    if atol.ndim > 0 and atol.shape != (n,):
        raise SolverError('AbsTol must be a scalar or have one value for each component of y0.')
    if np.any(atol < 0):
        raise SolverError('AbsTol must not be negative.')
    return rtol, atol


def _max_step(max_step):
    if max_step <= 0:
        raise SolverError('MaxStep must be positive.')
    return max_step


def _first(first_step, t0, t_bound):
    if first_step <= 0:
        raise SolverError('InitialStep must be positive.')
    return min(first_step, abs(t_bound - t0))


def _initial_step(fun, t0, y0, t_bound, max_step, f0, direction, order, rtol, atol):
    """A first step from the size of y0, of f(t0, y0) and of its change over
    a trial step (Hairer, Norsett and Wanner, Solving ODEs I, II.4)."""
    if y0.size == 0:
        return np.inf
    span = abs(t_bound - t0)
    if span == 0.0:
        return 0.0
    scale = atol + np.abs(y0) * rtol
    d0 = _norm(y0 / scale)
    d1 = _norm(f0 / scale)
    h0 = 1e-6 if d0 < 1e-5 or d1 < 1e-5 else 0.01 * d0 / d1
    h0 = min(h0, span)
    f1 = fun(t0 + h0 * direction, y0 + h0 * direction * f0)
    d2 = _norm((f1 - f0) / scale) / h0
    if d1 <= 1e-15 and d2 <= 1e-15:
        h1 = max(1e-6, h0 * 1e-3)
    else:
        h1 = (0.01 / max(d1, d2)) ** (1 / (order + 1))
    return min(100 * h0, h1, span, max_step)


def _guess_step(t0, y0, yp0, t_bound, max_step, rtol, atol):
    """A first step for a problem whose y' is not f(t, y) (a DAE, or
    F(t, y, y') = 0): the first half of _initial_step."""
    span = abs(t_bound - t0)
    if span == 0.0:
        return 0.0
    scale = atol + np.abs(y0) * rtol
    d0 = _norm(y0 / scale)
    d1 = _norm(yp0 / scale)
    h0 = 1e-6 * max(1.0, abs(t0)) if d0 < 1e-5 or d1 < 1e-5 else 0.01 * d0 / d1
    return min(h0, span, max_step)


def _fd(fun, x, f0, threshold):
    """d fun / dx by forward differences, a column per evaluation."""
    n = x.size
    J = np.empty((f0.size, n), dtype=np.result_type(x, f0, float))
    xx = x.copy()
    root = math.sqrt(EPS)
    for j in range(n):
        h = root * max(abs(x[j]), threshold[j]) or root
        xx[j] = x[j] + h
        h = xx[j] - x[j]
        J[:, j] = (fun(xx) - f0) / h
        xx[j] = x[j]
    return J


def _num_jac(solver, t, y, f, as_scipy=False):
    """df/dy at (t, y) by SciPy's adaptive differences. Their scale for a
    component is |y| or AbsTol, whichever is larger; except as_scipy, it is
    kept above 1e-5 of the largest |y|, or an increment on a zero component
    can vanish beside the others (y1 + y2 + y3 - 1 with AbsTol 1e-10)."""
    from scipy.integrate._ivp.common import num_jac
    thr = solver.atol if as_scipy else np.maximum(solver.atol, 1e-5 * max(1.0, float(np.abs(y).max(initial=0.0))))
    J, solver.jac_factor = num_jac(solver.fun_vectorized, t, y, f, thr, solver.jac_factor, None)
    return J


def null_spaces(M):
    """For a singular M: its left null space Q (the combinations of the
    equations that are algebraic) and its null space N (the algebraic
    directions of y); (None, None) when M is nonsingular."""
    U, s, Vt = np.linalg.svd(M)
    tol = max(M.shape) * EPS * (s[0] if s.size else 0.0)
    r = int(np.sum(s > tol))
    if r == M.shape[0]:
        return None, None
    return U[:, r:], Vt[r:].conj().T


def consistent(fun, jac, M, t0, y0, rtol, atol, Q, N):
    """y0 with its algebraic part (the directions N) moved by Newton's
    method until the algebraic equations Q'f(t0, y) = 0 hold; then f there
    and the y'0 of least norm with M y'0 = f. jac None: differences with
    increments scaled to y, not to AbsTol (an increment of AbsTol on a zero
    component can vanish beside the others: y1 + y2 + y3 - 1)."""
    y = np.array(y0, dtype=np.result_type(y0, float))
    scale = atol + rtol * np.abs(y)
    if jac is None:
        thr = np.maximum(np.broadcast_to(atol, y.shape), 1e-6 * (1 + np.abs(y).max()))
        jac = lambda t, z, f: _fd(lambda x: fun(t, x), z, f, thr)       # noqa: E731
    for _ in range(20):
        f = fun(t0, y)
        g = Q.conj().T @ f
        G = Q.conj().T @ jac(t0, y, f) @ N
        try:
            if np.linalg.cond(G) > 1 / (1000 * EPS):
                raise np.linalg.LinAlgError
            dz = np.linalg.solve(G, -g)
        except np.linalg.LinAlgError:
            raise SolverError('This DAE appears to be of index greater than 1: its algebraic equations do not '
                              'determine its algebraic variables.') from None
        step = N @ dz
        y = y + step
        if _norm(step / scale) < 1e-3:
            break
    else:
        raise SolverError('The initial conditions could not be made consistent with the algebraic equations.')
    f = fun(t0, y)
    yp = np.linalg.lstsq(M, f, rcond=None)[0]
    return y, f, yp


# ---- ode113: Adams-Bashforth-Moulton (Shampine and Gordon) ---------------------------------------

_TWO = [0.0] + [2.0 ** i for i in range(1, 14)]
_GSTR = [0.0, 0.5, 0.0833, 0.0417, 0.0264, 0.0188, 0.0143, 0.0114, 0.00936, 0.00789, 0.00679, 0.00592,
         0.00524, 0.00468]


class Adams(OdeSolver):
    """PECE with local extrapolation; the order (1 to 12) and the step are
    chosen together from error estimates at neighbouring orders. Arrays are
    indexed from 1, as in the Fortran, so that each line can be checked
    against it."""

    def __init__(self, fun, t0, y0, t_bound, max_step=np.inf, rtol=1e-3, atol=1e-6, vectorized=False,
                 first_step=None, **extraneous):
        super().__init__(fun, t0, y0, t_bound, vectorized, support_complex=True)
        self.max_step = _max_step(max_step)
        self.rtol, self.atol = _tols(rtol, atol, self.n)
        n, dt = self.n, self.y.dtype
        self.yp = self.fun(self.t, self.y)
        if first_step is None:
            h = _initial_step(self.fun, self.t, self.y, t_bound, self.max_step, self.yp, self.direction, 1,
                              self.rtol, self.atol)
        else:
            h = _first(first_step, t0, t_bound)
        self.h = h * self.direction
        self.phi = np.zeros((17, n), dtype=dt)
        self.p = np.zeros(n, dtype=dt)
        self.psi = np.zeros(14)
        self.alpha = np.zeros(14)
        self.beta = np.zeros(14)
        self.sig = np.zeros(15)
        self.v = np.zeros(15)
        self.w = np.zeros(15)
        self.g = np.zeros(15)
        self.gi = np.zeros(13)
        self.iv = np.zeros(12, dtype=int)
        self.k = 1
        self.kold = 0
        self.kprev = 0
        self.ivc = 0
        self.kgi = 0
        self.ns = 0
        self.hold = 0.0
        self.start = True
        self.phase1 = True
        self.nornd = True
        self.eps = 1.0
        self.nfail = 0
        self._last = None

    def _step_impl(self):
        t = self.t
        fouru = 4 * EPS
        left = abs(self.t_bound - t)
        if left <= fouru * abs(t):
            # too close to the end for a step: extrapolate there (as DDES does)
            self.p = self.y.copy()
            self.y = self.y + (self.t_bound - t) * self.yp
            self.t = self.t_bound
            self.yp = self.fun(self.t, self.y)
            self._last = ('line', t, self.p.copy(), self.y.copy())
            return True, None
        self.h = math.copysign(min(abs(self.h), self.max_step, left), self.direction)
        while True:
            wt = self.rtol * np.abs(self.y) + self.atol
            wt = np.where(wt > 0, wt, np.finfo(float).tiny)
            got = self._steps(wt)
            if got != 'round':
                break
            # the tolerances are below what the arithmetic can give: relax them, as DDES does
            self.rtol = self.rtol * self.eps
            self.atol = self.atol * self.eps
            self.eps = 1.0
        if got == 'small':
            return False, self.TOO_SMALL_STEP
        return True, None

    def _steps(self, wt):
        """One step of STEP (SLATEC's DSTEPS), retried with smaller steps
        and lower orders until it passes: 'ok', 'small' (the step fell below
        what the arithmetic can resolve) or 'round' (eps raised)."""
        n = self.n
        sq = lambda u: float(np.sum(np.abs(u) ** 2)) / n          # noqa: E731  (a mean square)
        phi, psi, alpha, beta, sig = self.phi, self.psi, self.alpha, self.beta, self.sig
        v, w, g, gi, iv = self.v, self.w, self.g, self.gi, self.iv
        x, h, eps, y, p = self.t, self.h, self.eps, self.y, self.p
        k, kold, kprev, ivc, kgi, ns = self.k, self.kold, self.kprev, self.ivc, self.kgi, self.ns
        hold, phase1, nornd = self.hold, self.phase1, self.nornd
        twou, fouru = 2 * EPS, 4 * EPS
        if abs(h) < fouru * abs(x):
            h = math.copysign(fouru * abs(x), h)
        p5eps = 0.5 * eps
        rnd = twou * math.sqrt(sq(y / wt))
        if p5eps < rnd:
            self.eps = 2.0 * rnd * (1.0 + fouru)
            return 'round'
        g[1] = 1.0
        g[2] = 0.5
        sig[1] = 1.0
        if self.start:
            phi[1] = self.yp
            phi[2] = 0.0
            hold = 0.0
            k = 1
            kold = 0
            kprev = 0
            self.start = False
            phase1 = True
            nornd = True
            if p5eps <= 100.0 * rnd:
                nornd = False
                phi[15] = 0.0
        ifail = 0
        while True:
            # 100: the coefficients for the step from x to x + h
            kp1, kp2, km1, km2 = k + 1, k + 2, k - 1, k - 2
            if h != hold:
                ns = 0
            if ns <= kold:
                ns += 1
            nsp1 = ns + 1
            if k >= ns:
                beta[ns] = 1.0
                alpha[ns] = 1.0 / ns
                temp1 = h * ns
                sig[nsp1] = 1.0
                for i in range(nsp1, k + 1):
                    temp2 = psi[i - 1]
                    psi[i - 1] = temp1
                    beta[i] = beta[i - 1] * psi[i - 1] / temp2
                    temp1 = temp2 + h
                    alpha[i] = h / temp1
                    sig[i + 1] = i * alpha[i] * sig[i]
                psi[k] = temp1
                if ns <= 1:
                    for iq in range(1, k + 1):
                        v[iq] = 1.0 / (iq * (iq + 1))
                        w[iq] = v[iq]
                    ivc = 0
                    kgi = 0
                    if k != 1:
                        kgi = 1
                        gi[1] = w[2]
                else:
                    if k > kprev:
                        if ivc != 0:
                            jv = kp1 - iv[ivc]
                            ivc -= 1
                        else:
                            jv = 1
                            v[k] = 1.0 / (k * kp1)
                            w[k] = v[k]
                            if k == 2:
                                kgi = 1
                                gi[1] = w[2]
                        nsm2 = ns - 2
                        if nsm2 >= jv:
                            for j in range(jv, nsm2 + 1):
                                i = k - j
                                v[i] = v[i] - alpha[j + 1] * v[i + 1]
                                w[i] = v[i]
                            if i == 2:
                                kgi = ns - 1
                                gi[kgi] = w[2]
                    limit1 = kp1 - ns
                    temp5 = alpha[ns]
                    for iq in range(1, limit1 + 1):
                        v[iq] = v[iq] - temp5 * v[iq + 1]
                        w[iq] = v[iq]
                    g[nsp1] = w[1]
                    if limit1 != 1:
                        kgi = ns
                        gi[kgi] = w[2]
                    w[limit1 + 1] = v[limit1 + 1]
                    if k < kold:
                        ivc += 1
                        iv[ivc] = limit1 + 2
                # 140
                kprev = k
                for i in range(ns + 2, kp1 + 1):
                    temp6 = alpha[i - 1]
                    for iq in range(1, kp2 - i + 1):
                        w[iq] = w[iq] - temp6 * w[iq + 1]
                    g[i] = w[1]
            # 199: predict
            for i in range(nsp1, k + 1):
                phi[i] = beta[i] * phi[i]
            phi[kp2] = phi[kp1]
            phi[kp1] = 0.0
            pp = np.zeros(n, dtype=phi.dtype)
            for j in range(1, k + 1):
                i = kp1 - j
                pp = pp + g[i] * phi[i]
                phi[i] = phi[i] + phi[i + 1]
            if not nornd:
                tau = h * pp - phi[15]
                p[:] = y + tau
                phi[16] = (p - y) - tau
            else:
                p[:] = y + h * pp
            xold = x
            x = x + h
            absh = abs(h)
            ypp = self.fun(x, p)
            # the errors at orders k, k - 1 and k - 2
            d = ypp - phi[1]
            erkm2 = erkm1 = 0.0
            if km2 > 0:
                erkm2 = absh * sig[km1] * _GSTR[km2] * math.sqrt(sq((phi[km1] + d) / wt))
            if km2 >= 0:
                erkm1 = absh * sig[k] * _GSTR[km1] * math.sqrt(sq((phi[k] + d) / wt))
            temp5 = absh * math.sqrt(sq(d / wt))
            err = temp5 * (g[k] - g[kp1])
            erk = temp5 * sig[kp1] * _GSTR[k]
            knew = k
            if km2 > 0:
                if max(erkm1, erkm2) <= erk:
                    knew = km1
            elif km2 == 0:
                if erkm1 <= 0.5 * erk:
                    knew = km1
            if err <= eps:
                break
            # the step failed: put phi and psi back, and try a shorter step (order one from the third failure)
            self.nfail += 1
            phase1 = False
            x = xold
            for i in range(1, k + 1):
                phi[i] = (phi[i] - phi[i + 1]) / beta[i]
            for i in range(2, k + 1):
                psi[i - 1] = psi[i] - h
            ifail += 1
            temp2 = 0.5
            if ifail > 3 and p5eps < 0.25 * erk:
                temp2 = math.sqrt(p5eps / erk)
            if ifail >= 3:
                knew = 1
            h = temp2 * h
            k = knew
            ns = 0
            if abs(h) < fouru * abs(x):
                self.k, self.ns, self.h = k, ns, h
                self.phase1 = phase1
                return 'small'
        # 400: correct and evaluate
        kold = k
        hold = h
        temp1 = h * g[kp1]
        old = y.copy()
        if not nornd:
            rho = temp1 * (ypp - phi[1]) - phi[16]
            ynew = p + rho
            phi[15] = (ynew - p) - rho
        else:
            ynew = p + temp1 * (ypp - phi[1])
        p[:] = old
        yp = self.fun(x, ynew)
        # the differences for the next step
        phi[kp1] = yp - phi[1]
        phi[kp2] = phi[kp1] - phi[kp2]
        for i in range(1, k + 1):
            phi[i] = phi[i] + phi[kp1]
        # the order for the next step: raise it, lower it, or keep it
        erkp1 = 0.0
        if knew == km1 or k == 12:
            phase1 = False
        if phase1:
            change = 1
        elif knew == km1:
            change = -1
        elif kp1 > ns:
            change = 0
        else:
            erkp1 = absh * _GSTR[kp1] * math.sqrt(sq(phi[kp2] / wt))
            if k > 1:
                if erkm1 <= min(erk, erkp1):
                    change = -1
                elif erkp1 >= erk or k == 12:
                    change = 0
                else:
                    change = 1
            else:
                change = 0 if erkp1 >= 0.5 * erk else 1
        if change == 1:
            k = kp1
            erk = erkp1
        elif change == -1:
            k = km1
            erk = erkm1
        # and the step: double it in the first phase, else as the error allows
        hnew = h + h
        if not phase1 and p5eps < erk * _TWO[k + 1]:
            hnew = h
            if p5eps < erk:
                r = (p5eps / erk) ** (1.0 / (k + 1))
                hnew = absh * max(0.5, min(0.9, r))
                hnew = math.copysign(max(hnew, fouru * abs(x)), h)
        # what INTRP needs for the step just taken
        self._last = ('adams', xold, x, ynew.copy(), p.copy(), phi[1:kold + 2].copy(), kold, ivc, iv.copy(), kgi,
                      gi.copy(), alpha.copy(), g.copy(), w.copy())
        self.t, self.y, self.yp, self.h = x, ynew, yp, hnew
        self.k, self.kold, self.kprev, self.ivc, self.kgi, self.ns = k, kold, kprev, ivc, kgi, ns
        self.hold, self.phase1, self.nornd = hold, phase1, nornd
        return 'ok'

    def _dense_output_impl(self):
        return _AdamsDense(self.t_old, self.t, self._last)


class _AdamsDense(DenseOutput):
    """INTRP (SLATEC's DINTP): the Adams interpolating polynomial of the
    step, from the differences and coefficients it was taken with."""

    def __init__(self, t_old, t, last):
        super().__init__(t_old, t)
        self.last = last

    def _call_impl(self, t):
        if t.ndim == 0:
            return self._at(float(t))
        out = [self._at(float(x)) for x in t]
        return np.column_stack(out) if out else np.zeros((self.last[3].size, 0))

    def _at(self, xout):
        if self.last[0] == 'line':
            _, t0, y0, y1 = self.last
            s = (xout - t0) / (self.t - t0)
            return y0 + s * (y1 - y0)
        _, ox, x, y, oy, phi, kold, ivc, iv, kgi, gi, alpha, og, ow = self.last
        ph = lambda i: phi[i - 1]          # noqa: E731  (PHI(., i), from 1)
        kp1, kp2 = kold + 1, kold + 2
        hi = xout - ox
        h = x - ox
        xi = hi / h
        xim1 = xi - 1.0
        wl = [0.0] * 16
        gl = [0.0] * 16
        c = [0.0] * 16
        xiq = xi
        temp1 = 1.0
        for iq in range(1, kp1 + 1):
            xiq = xi * xiq
            temp1 = iq * (iq + 1)
            wl[iq] = xiq / temp1
        # the double integral term
        if kold <= kgi:
            gdi = gi[kold]
        else:
            if ivc > 0:
                iw = iv[ivc]
                gdi = ow[iw]
                m = kold - iw + 3
            else:
                gdi = 1.0 / temp1
                m = 2
            for i in range(m, kold + 1):
                gdi = ow[kp2 - i] - alpha[i] * gdi
        gl[1] = xi
        gl[2] = 0.5 * xi * xi
        c[1] = 1.0
        c[2] = xi
        for i in range(2, kold + 1):
            alp = alpha[i]
            gamma = 1.0 + xim1 * alp
            for jq in range(1, kp2 - i + 1):
                wl[jq] = gamma * wl[jq] - alp * wl[jq + 1]
            gl[i + 1] = wl[1]
            c[i + 1] = gamma * c[i]
        sigma = (wl[2] - xim1 * wl[1]) / gdi
        yout = np.zeros_like(y)
        for j in range(1, kold + 1):
            i = kp2 - j
            gdif = og[i] - og[i - 1]
            yout = yout + ((gl[i] - gl[i - 1]) - sigma * gdif) * ph(i)
        return ((1.0 - sigma) * oy + sigma * y) + h * (yout + (gl[1] - sigma * og[1]) * ph(1))


# ---- ode78 and ode89: Verner's pairs ------------------------------------------------------------

def _tableau(name):
    from . import vernertab as V
    s, a = getattr(V, name + '_STAGES'), getattr(V, name + '_ALL')
    C = np.array(getattr(V, name + '_C'))
    A = np.zeros((a, a))
    for (i, j), x in getattr(V, name + '_A').items():
        A[i - 1, j - 1] = x
    B = np.zeros(s)
    for i, x in getattr(V, name + '_B').items():
        B[i - 1] = x
    E = np.zeros(s)
    for i, x in getattr(V, name + '_E').items():
        E[i - 1] = x
    Rd = getattr(V, name + '_R')
    deg = max(p for d in Rd.values() for p in d)
    R = np.zeros((a, deg))
    for i, d in Rd.items():
        for q, x in d.items():
            R[i - 1, q - 1] = x
    # the first extra stage is f at the end of the step when its row is the weights
    end = C[s] == 1.0 and np.allclose(A[s, :s], B, rtol=0, atol=1e-15) and not A[s, s:].any()
    return s, a, C, A, B, E, R, end


class _Verner(OdeSolver):
    """An explicit Runge-Kutta pair with local extrapolation; its
    interpolant needs extra stages, which are evaluated only for the steps
    an interpolated value is asked of."""
    NAME = None
    order = error_estimator_order = None
    _tab = None

    def __init__(self, fun, t0, y0, t_bound, max_step=np.inf, rtol=1e-3, atol=1e-6, vectorized=False,
                 first_step=None, **extraneous):
        super().__init__(fun, t0, y0, t_bound, vectorized, support_complex=True)
        cls = type(self)
        if cls._tab is None:
            cls._tab = _tableau(cls.NAME)
        self.S, self.ALL, self.C, self.A, self.B, self.E, self.R, self.end_stage = cls._tab
        self.max_step = _max_step(max_step)
        self.rtol, self.atol = _tols(rtol, atol, self.n)
        self.f = self.fun(self.t, self.y)
        if first_step is None:
            self.h_abs = _initial_step(self.fun, self.t, self.y, t_bound, self.max_step, self.f, self.direction,
                                       self.error_estimator_order, self.rtol, self.atol)
        else:
            self.h_abs = _first(first_step, t0, t_bound)
        self.K = np.empty((self.ALL, self.n), dtype=self.y.dtype)
        self.y_old = None
        self.h_previous = None
        self.exponent = -1 / (self.error_estimator_order + 1)

    def _step_impl(self):
        t, y = self.t, self.y
        S, C, A, K = self.S, self.C, self.A, self.K
        min_step = 10 * np.abs(np.nextafter(t, self.direction * np.inf) - t)
        h_abs = min(max(self.h_abs, min_step), self.max_step)
        rejected = False
        while True:
            if h_abs < min_step:
                return False, self.TOO_SMALL_STEP
            h = h_abs * self.direction
            t_new = t + h
            if self.direction * (t_new - self.t_bound) > 0:
                t_new = self.t_bound
            h = t_new - t
            h_abs = abs(h)
            K[0] = self.f
            for i in range(1, S):
                K[i] = self.fun(t + C[i] * h, y + h * (A[i, :i] @ K[:i]))
            y_new = y + h * (self.B @ K[:S])
            scale = self.atol + np.maximum(np.abs(y), np.abs(y_new)) * self.rtol
            err = _norm(h * (self.E @ K[:S]) / scale)
            if err < 1:
                factor = MAX_FACTOR if err == 0 else min(MAX_FACTOR, SAFETY * err ** self.exponent)
                if rejected:
                    factor = min(1.0, factor)
                h_abs *= factor
                break
            h_abs *= max(MIN_FACTOR, SAFETY * err ** self.exponent)
            rejected = True
        self.h_previous = h
        self.y_old = y
        self.t, self.y, self.h_abs = t_new, y_new, h_abs
        self.f = self.fun(t_new, y_new)
        return True, None

    def _dense_output_impl(self):
        from scipy.integrate._ivp.rk import RkDenseOutput
        K, C, A, h = self.K, self.C, self.A, self.h_previous
        for i in range(self.S, self.ALL):
            if i == self.S and self.end_stage:
                K[i] = self.f
            else:
                K[i] = self.fun(self.t_old + C[i] * h, self.y_old + h * (A[i, :i] @ K[:i]))
        return RkDenseOutput(self.t_old, self.t, self.y_old, K.T @ self.R)


class Verner78(_Verner):
    NAME = 'VERN8'
    order = 8
    error_estimator_order = 7


class Verner89(_Verner):
    NAME = 'VERN9'
    order = 9
    error_estimator_order = 8


# ---- what the implicit methods share: M, the Jacobian, the factorisations -----------------------

class _Implicit(OdeSolver):
    """Mass matrix, Jacobian and LU bookkeeping for the implicit one-step
    methods. mass: None, a matrix, or a function (t, y) -> matrix; jac: None
    (differences), a matrix, or a function (t, y) -> matrix."""
    singular_ok = False

    def __init__(self, fun, t0, y0, t_bound, max_step=np.inf, rtol=1e-3, atol=1e-6, jac=None, mass=None,
                 vectorized=False, first_step=None, **extraneous):
        super().__init__(fun, t0, y0, t_bound, vectorized, support_complex=True)
        self.max_step = _max_step(max_step)
        self.rtol, self.atol = _tols(rtol, atol, self.n)
        self.newton_tol = max(10 * EPS / self.rtol, min(0.03, self.rtol ** 0.5))
        self.jac_factor = None
        self.mass_fn = mass if callable(mass) else None
        self.mass_const = None if mass is None or callable(mass) else np.asarray(mass, dtype=self.y.dtype)
        self.has_mass = mass is not None
        M0 = self.M(self.t, self.y)
        self.Q = self.N = None
        if M0 is not None:
            self.Q, self.N = null_spaces(M0)
            if self.Q is not None and not self.singular_ok:
                raise SolverError('singular')
        self.Mlu = lu_factor(self.mass_const) if self.mass_const is not None and self.Q is None else None
        if jac is None:
            self.jac_fn = lambda t, y, f: _num_jac(self, t, y, f)     # noqa: E731
            self.jac_const = False
        elif callable(jac):
            self.jac_fn = lambda t, y, f: np.asarray(jac(t, y), dtype=self.y.dtype)    # noqa: E731
            self.jac_const = False
        else:
            Jc = np.asarray(jac, dtype=self.y.dtype)
            self.jac_fn = lambda t, y, f: Jc     # noqa: E731
            self.jac_const = True
        if self.Q is not None:
            self.y, self.f, self.yp = consistent(self.fun, None if jac is None else self.jac_fn_counted, M0, self.t,
                                                 self.y, self.rtol, self.atol, self.Q, self.N)
        else:
            self.f = self.fun(self.t, self.y)
            self.yp = self.deriv(self.t, self.y, self.f)
        self.J = self.jac_fn_counted(self.t, self.y, self.f)
        self.jac_current = True
        if first_step is not None:
            self.h_abs = _first(first_step, t0, t_bound)
        elif self.Q is not None:
            self.h_abs = _guess_step(self.t, self.y, self.yp, t_bound, self.max_step, self.rtol, self.atol)
        else:
            self.h_abs = _initial_step(self.rate, self.t, self.y, t_bound, self.max_step, self.yp, self.direction,
                                       self.error_order, self.rtol, self.atol)
        self.LU = None
        self.LU_h = None
        self.nlinsolve = 0

    error_order = 2

    def jac_fn_counted(self, t, y, f):
        self.njev += 1
        return self.jac_fn(t, y, f)

    def M(self, t, y):
        if self.mass_const is not None:
            return self.mass_const
        if self.mass_fn is not None:
            return np.asarray(self.mass_fn(t, y), dtype=self.y.dtype)
        return None

    def deriv(self, t, y, f):
        """y' from f: M \\ f (the least-norm one for a singular M)."""
        if not self.has_mass:
            return f
        if self.Mlu is not None:
            return lu_solve(self.Mlu, f)
        M = self.M(t, y)
        if self.Q is not None:
            return np.linalg.lstsq(M, f, rcond=None)[0]
        return np.linalg.solve(M, f)

    def rate(self, t, y):
        f = self.fun(t, y)
        return self.deriv(t, y, f)

    def mult(self, M, x):
        return x if M is None else M @ x

    def factor(self, M, c):
        """LU of M - c J (I - c J without a mass matrix)."""
        A = (np.identity(self.n, dtype=self.y.dtype) if M is None else M) - c * self.J
        self.nlu += 1
        return lu_factor(A, overwrite_a=True)

    def solve(self, LU, b):
        self.nlinsolve += 1
        return lu_solve(LU, b)

    newton_maxiter = 6      # as SciPy's Radau, the other one-step implicit method

    def newton(self, t, z0, residual, LU, scale):
        """Simplified Newton for residual(z) = 0 with the factored LU: the
        converged z and f(t, z), or None when it will not converge."""
        z = z0.copy()
        dz_old = None
        maxiter = self.newton_maxiter
        for k in range(maxiter):
            r = residual(z)
            if r is None or not np.all(np.isfinite(r)):
                return None
            dz = self.solve(LU, -r)
            dz_norm = _norm(dz / scale)
            rate = None if dz_old is None else dz_norm / dz_old
            if rate is not None and (rate >= 1 or rate ** (maxiter - k) / (1 - rate) * dz_norm > self.newton_tol):
                return None
            z = z + dz
            if dz_norm == 0 or (rate is not None and rate / (1 - rate) * dz_norm < self.newton_tol):
                f = self.fun(t, z)
                return (z, f) if np.all(np.isfinite(f)) else None
            dz_old = dz_norm
        return None

    def bounded_step(self):
        """The step to try, kept within MaxStep and the smallest one the
        arithmetic resolves; None when that is below the smallest."""
        t = self.t
        min_step = 10 * np.abs(np.nextafter(t, self.direction * np.inf) - t)
        return min(max(self.h_abs, min_step), self.max_step), min_step

    def attempt(self, t, h):
        """One try at a step of h from (self.t, self.y): (y_new, f_new,
        error vector, accepted data) or None when Newton fails."""
        raise NotImplementedError

    def _step_impl(self):
        t = self.t
        h_abs, min_step = self.bounded_step()
        rejected = False
        exponent = -1.0 / (self.error_order + 1)
        while True:
            if h_abs < min_step:
                return False, self.TOO_SMALL_STEP
            h = h_abs * self.direction
            t_new = t + h
            if self.direction * (t_new - self.t_bound) > 0:
                t_new = self.t_bound
            h = t_new - t
            h_abs = abs(h)
            got = self.attempt(t, h)
            if got is None:
                # Newton did not converge: a fresh Jacobian first, then a shorter step
                if not self.jac_current and not self.jac_const:
                    self.J = self.jac_fn_counted(t, self.y, self.f)
                    self.jac_current = True
                    self.LU = None
                    continue
                h_abs *= 0.5
                self.LU = None
                rejected = True
                continue
            y_new, f_new, est, data = got
            scale = self.atol + self.rtol * np.maximum(np.abs(self.y), np.abs(y_new))
            if self.N is not None:
                est = est - self.N @ (self.N.conj().T @ est)
            err = _norm(est / scale)
            if err <= 1:
                factor = MAX_FACTOR if err == 0 else min(MAX_FACTOR, SAFETY * err ** exponent)
                if rejected:
                    factor = min(1.0, factor)
                break
            h_abs *= max(MIN_FACTOR, SAFETY * err ** exponent)
            rejected = True
            self.LU = None
        self.accept(t, h, y_new, f_new, data)
        self.h_abs = h_abs * factor
        if factor != 1.0:
            self.LU = None
        return True, None

    def accept(self, t, h, y_new, f_new, data):
        self.y_old, self.f_old, self.yp_old = self.y, self.f, self.yp
        self.h_previous = h
        self.data = data
        self.t, self.y, self.f = t + h, y_new, f_new
        self.yp = self.deriv(self.t, y_new, f_new)
        if not self.jac_const:
            self.jac_current = False


class _Quadratic(DenseOutput):
    """The quadratic through three points (t, y); or through two, with the
    slope yp0 at the first."""

    def __init__(self, t_old, t, points, yp0=None):
        super().__init__(t_old, t)
        self.points = points
        self.yp0 = yp0

    def _call_impl(self, t):
        x = np.asarray(t, float)
        if self.yp0 is not None:
            (t0, y0), (t1, y1) = self.points
            h = t1 - t0
            d = x - t0
            return (np.multiply.outer(y0, np.ones_like(d)) + np.multiply.outer(self.yp0, d)
                    + np.multiply.outer((y1 - y0 - h * self.yp0) / (h * h), d * d))
        (ta, ya), (tb, yb), (tc, yc) = self.points
        la = (x - tb) * (x - tc) / ((ta - tb) * (ta - tc))
        lb = (x - ta) * (x - tc) / ((tb - ta) * (tb - tc))
        lc = (x - ta) * (x - tb) / ((tc - ta) * (tc - tb))
        return np.multiply.outer(ya, la) + np.multiply.outer(yb, lb) + np.multiply.outer(yc, lc)


# ---- ode23s: the modified Rosenbrock pair -----------------------------------------------------------

_D = 1 / (2 + math.sqrt(2))
_E32 = 6 + math.sqrt(2)


class Rosenbrock23(_Implicit):
    """W = M - h d J with a fresh Jacobian (and df/dt) at every step; two
    stages give the second-order result, a third its error."""
    error_order = 2

    def attempt(self, t, h):
        y, f0 = self.y, self.f
        if not self.jac_current:
            self.J = self.jac_fn_counted(t, y, f0)
            self.jac_current = True
            self.LU = None
        if self.T_at != t:
            dt = math.copysign(min(math.sqrt(EPS) * max(abs(t), abs(t + h)), abs(h)), h)
            self.T = (self.fun(t + dt, y) - f0) / dt
            self.T_at = t
        M = self.M(t, y)
        if self.LU is None or self.LU_h != h:
            self.LU = self.factor(M, h * _D)
            self.LU_h = h
        LU, T = self.LU, self.T
        k1 = self.solve(LU, f0 + h * _D * T)
        f1 = self.fun(t + 0.5 * h, y + 0.5 * h * k1)
        k2 = self.solve(LU, f1 - self.mult(M, k1)) + k1
        y_new = y + h * k2
        f2 = self.fun(t + h, y_new)
        k3 = self.solve(LU, f2 - _E32 * (self.mult(M, k2) - f1) - 2 * (self.mult(M, k1) - f0) + h * _D * T)
        if not (np.all(np.isfinite(y_new)) and np.all(np.isfinite(k3))):
            return None
        return y_new, f2, h / 6 * (k1 - 2 * k2 + k3), (k1, k2)

    T_at = None
    T = None

    def accept(self, t, h, y_new, f_new, data):
        super().accept(t, h, y_new, f_new, data)
        self.jac_current = self.jac_const
        self.T_at = None

    def _dense_output_impl(self):
        return _RosenbrockDense(self.t_old, self.t, self.y_old, self.h_previous, *self.data)


class _RosenbrockDense(DenseOutput):
    """Shampine and Reichelt's free interpolant:
    y(t + s h) = y + h (s (1 - s) k1 + s (s - 2d) k2) / (1 - 2d)."""

    def __init__(self, t_old, t, y_old, h, k1, k2):
        super().__init__(t_old, t)
        self.y_old, self.h, self.k1, self.k2 = y_old, h, k1, k2

    def _call_impl(self, t):
        s = (np.asarray(t, float) - self.t_old) / self.h
        a = s * (1 - s) / (1 - 2 * _D)
        b = s * (s - 2 * _D) / (1 - 2 * _D)
        return (np.multiply.outer(self.y_old, np.ones_like(s)) + self.h * (np.multiply.outer(self.k1, a) + np.multiply.outer(self.k2, b)))


# ---- ode23t: the trapezoidal rule ------------------------------------------------------------------

class Trapezoid(_Implicit):
    """M (y1 - y0) = h/2 (M y0' + f1), solved by simplified Newton with
    W = M - (h/2) J. Its local error is -h^3 y'''/12. With y''' from the
    third divided difference of the last four solution values, a stiff
    component that rings (the rule does not damp it) counts at its own
    size; for the first two steps, before there are four, from the
    derivative at the middle of the free (quadratic) interpolant against
    the mean of the end ones, passed through W."""
    singular_ok = True
    error_order = 2
    hist = ()

    def attempt(self, t, h):
        y, f0, yp0 = self.y, self.f, self.yp
        t_new = t + h
        M = self.M(t_new, y)
        if self.LU is None or self.LU_h != h:
            self.LU = self.factor(M, 0.5 * h)
            self.LU_h = h
        scale = self.atol + self.rtol * np.abs(y)

        def residual(z):
            f1 = self.fun(t_new, z)
            if not np.all(np.isfinite(f1)):
                return None
            Mz = self.M(t_new, z) if self.mass_fn is not None else M
            return self.mult(Mz, z - y - 0.5 * h * yp0) - 0.5 * h * f1
        # Newton starts from the line through the last two values (not from the slope, which a
        # ringing stiff component makes large)
        if self.hist:
            tp, yprev = self.hist[-1]
            guess = y + (h / (t - tp)) * (y - yprev)
        else:
            guess = y + h * yp0
        got = self.newton(t_new, guess, residual, self.LU, scale)
        if got is None:
            return None
        y1, f1 = got
        if len(self.hist) == 2:
            (ta, ya), (tb, yb) = self.hist
            d1a, d1b, d1c = (yb - ya) / (tb - ta), (y - yb) / (t - tb), (y1 - y) / (t_new - t)
            d3 = ((d1c - d1b) / (t_new - tb) - (d1b - d1a) / (t - ta)) / (t_new - ta)
            return y1, f1, 0.5 * h ** 3 * d3, None
        yp1 = self.deriv(t_new, y1, f1)
        tm = t + 0.5 * h
        ym = y + h * (0.5 * yp0 + 0.125 * (yp1 - yp0))
        if self.N is not None:
            ym = ym + self.N @ (self.N.conj().T @ (0.5 * (y + y1) - ym))
        r = self.fun(tm, ym) - self.mult(self.M(tm, ym), 0.5 * (yp0 + yp1))
        if self.Q is not None:
            r = r - self.Q @ (self.Q.conj().T @ r)
        est = (2.0 / 3.0) * h * self.solve(self.LU, r)
        return y1, f1, est, None

    def accept(self, t, h, y_new, f_new, data):
        self.hist = (tuple(self.hist) + ((t, self.y),))[-2:]
        super().accept(t, h, y_new, f_new, data)

    def _dense_output_impl(self):
        # from solution values only: slopes f(y) of a ringing stiff component are large, and a free
        # interpolant would carry them into the middle of the step
        if len(self.hist) == 2:
            return _Quadratic(self.t_old, self.t, [self.hist[0], (self.t_old, self.y_old), (self.t, self.y)])
        return _Quadratic(self.t_old, self.t, [(self.t_old, self.y_old), (self.t, self.y)], self.yp_old)


# ---- ode23tb: TR-BDF2 -------------------------------------------------------------------------------

_G = 2 - math.sqrt(2)                       # the trapezoidal stage covers gamma*h
_DG = _G / 2                                # = (1 - gamma)/(2 - gamma): one W = M - d h J for both stages
_BA = 1 / (_G * (2 - _G))
_BB = (1 - _G) ** 2 / (_G * (2 - _G))
_ET = (-0.1380711874576984, 0.3333333333333333, -0.19526214587563495)


class TRBDF2(_Implicit):
    """A trapezoidal stage to t + gamma h, gamma = 2 - sqrt(2), then a BDF2
    stage to t + h, both with W = M - d h J (d = gamma/2). The error is
    Hosea and Shampine's estimate from the three slopes, passed through W."""
    error_order = 2

    def attempt(self, t, h):
        y, f0, yp0 = self.y, self.f, self.yp
        tg, t1 = t + _G * h, t + h
        M = self.M(tg, y)
        if self.LU is None or self.LU_h != h:
            self.LU = self.factor(M, _DG * h)
            self.LU_h = h
        scale = self.atol + self.rtol * np.abs(y)
        Mat = (lambda tt, z: self.M(tt, z)) if self.mass_fn is not None else (lambda tt, z: M)   # noqa: E731

        def tr(z):
            fz = self.fun(tg, z)
            return None if not np.all(np.isfinite(fz)) else self.mult(Mat(tg, z), z - y - _DG * h * yp0) - _DG * h * fz
        got = self.newton(tg, y + _G * h * yp0, tr, self.LU, scale)
        if got is None:
            return None
        yg, fg = got
        ypg = self.deriv(tg, yg, fg)
        base = _BA * yg - _BB * y

        def bdf2(z):
            fz = self.fun(t1, z)
            return None if not np.all(np.isfinite(fz)) else self.mult(Mat(t1, z), z - base) - _DG * h * fz
        got = self.newton(t1, y + (yg - y) / _G, bdf2, self.LU, scale)     # the line through y and yg
        if got is None:
            return None
        y1, f1 = got
        if self.mass_fn is None:
            est = self.solve(self.LU, h * (_ET[0] * f0 + _ET[1] * fg + _ET[2] * f1))
        else:
            # from the slopes, then back through M where the step ends: a mass matrix that varies
            yp1 = self.deriv(t1, y1, f1)
            est = self.solve(self.LU, self.M(t1, y1) @ (h * (_ET[0] * yp0 + _ET[1] * ypg + _ET[2] * yp1)))
        return y1, f1, est, (tg, yg, ypg)

    def _dense_output_impl(self):
        tg, yg, _ = self.data
        return _Quadratic(self.t_old, self.t, [(self.t_old, self.y_old), (tg, yg), (self.t, self.y)])


# ---- ode15s and ode15i: NDFs and BDFs ----------------------------------------------------------------

_MAX_ORDER = 5


def _compute_R(order, factor):
    I = np.arange(1, order + 1)[:, None]
    J = np.arange(1, order + 1)
    M = np.zeros((order + 1, order + 1))
    M[1:, 1:] = (I - 1 - factor * J) / I
    M[0] = 1
    return np.cumprod(M, axis=0)


def _change_D(D, order, factor):
    """The differences for a step size changed by factor."""
    R = _compute_R(order, factor)
    U = _compute_R(order, 1)
    D[:order + 1] = np.dot(R.dot(U).T, D[:order + 1])


class NDF(OdeSolver):
    """SciPy's BDF, for three forms of the problem:

      y' = f(t, y)                       ode15s (exactly SciPy's steps)
      M(t, y) y' = f(t, y)               ode15s with a mass matrix,
                                         singular too (an index-1 DAE)
      F(t, y, y') = 0                    ode15i (residual=F, yp0 given)

    Each step predicts y from the differences in D and solves for the
    correction d with y' = (psi + d)/c, c = h/alpha_k. Newton's matrix is
    I - c J, M - c J, or c dF/dy + dF/dy'. max_order caps the order (1 to
    5); bdf=True takes the plain BDFs (all kappa 0) for the NDFs."""

    def __init__(self, fun, t0, y0, t_bound, max_step=np.inf, rtol=1e-3, atol=1e-6, jac=None, vectorized=False,
                 first_step=None, mass=None, residual=None, yp0=None, max_order=5, bdf=False, **extraneous):
        super().__init__(fun, t0, y0, t_bound, vectorized, support_complex=True)
        self.max_step = _max_step(max_step)
        self.rtol, self.atol = _tols(rtol, atol, self.n)
        self.max_order = max(1, min(_MAX_ORDER, int(max_order)))
        self.mode = 'implicit' if residual is not None else 'mass' if mass is not None else 'ode'
        self.jac_factor = None
        self.Q = self.N = None
        self.nlinsolve = 0
        if self.mode == 'ode':
            f = self.fun(self.t, self.y)
            yp = f
            if first_step is None:
                self.h_abs = _initial_step(self.fun, self.t, self.y, t_bound, self.max_step, f, self.direction, 1,
                                           self.rtol, self.atol)
            else:
                self.h_abs = _first(first_step, t0, t_bound)
            self.jac, self.J = self._validate_jac(jac)
        elif self.mode == 'mass':
            self.mass_fn = mass if callable(mass) else None
            self.mass_const = None if callable(mass) else np.asarray(mass, dtype=self.y.dtype)
            M0 = self.M(self.t, self.y)
            self.jac, self.J = self._validate_jac(jac)
            self.Q, self.N = null_spaces(M0)
            if self.Q is not None:
                jfn = None if jac is None else (lambda t, y, f: self.jac(t, y)) if callable(jac) else (lambda t, y, f: self.J)   # noqa: E731
                self.y, f, yp = consistent(self.fun, jfn, M0, self.t, self.y, self.rtol, self.atol, self.Q, self.N)
                if self.jac is not None:
                    self.J = self.jac(self.t, self.y)
            else:
                f = self.fun(self.t, self.y)
                yp = np.linalg.solve(M0, f)
            if first_step is not None:
                self.h_abs = _first(first_step, t0, t_bound)
            elif self.Q is not None:
                self.h_abs = _guess_step(self.t, self.y, yp, t_bound, self.max_step, self.rtol, self.atol)
            else:
                rate = lambda t, y: np.linalg.solve(self.M(t, y), self.fun(t, y))     # noqa: E731
                self.h_abs = _initial_step(rate, self.t, self.y, t_bound, self.max_step, yp, self.direction, 1,
                                           self.rtol, self.atol)
        else:
            self.F = residual
            yp = np.asarray(yp0, dtype=self.y.dtype).reshape(-1)
            self.jac, self.J = self._validate_implicit_jac(jac, yp)
            self.h_abs = (_first(first_step, t0, t_bound) if first_step is not None else
                          _guess_step(self.t, self.y, yp, t_bound, self.max_step, self.rtol, self.atol))
        self.h_abs_old = None
        self.error_norm_old = None
        self.newton_tol = max(10 * EPS / self.rtol, min(0.03, self.rtol ** 0.5))
        self.I = np.identity(self.n, dtype=self.y.dtype)
        kappa = np.zeros(6) if bdf else np.array([0, -0.1850, -1 / 9, -0.0823, -0.0415, 0])
        self.gamma = np.hstack((0, np.cumsum(1 / np.arange(1, _MAX_ORDER + 1))))
        self.alpha = (1 - kappa) * self.gamma
        self.error_const = kappa * self.gamma + 1 / np.arange(1, _MAX_ORDER + 2)
        D = np.empty((_MAX_ORDER + 3, self.n), dtype=self.y.dtype)
        D[0] = self.y
        D[1] = yp * self.h_abs * self.direction
        self.D = D
        self.order = 1
        self.n_equal_steps = 0
        self.LU = None

    def M(self, t, y):
        if self.mass_const is not None:
            return self.mass_const
        return np.asarray(self.mass_fn(t, y), dtype=self.y.dtype)

    def _validate_jac(self, jac):
        t0, y0 = self.t, self.y
        if jac is None:
            def jac_wrapped(t, y):
                self.njev += 1
                f = self.fun_single(t, y)
                return _num_jac(self, t, y, f, as_scipy=self.mode == 'ode')
            return jac_wrapped, jac_wrapped(t0, y0)
        if callable(jac):
            J = np.asarray(jac(t0, y0), dtype=y0.dtype)
            self.njev += 1

            def jac_wrapped(t, y):
                self.njev += 1
                return np.asarray(jac(t, y), dtype=y0.dtype)
            if J.shape != (self.n, self.n):
                raise SolverError(f'The Jacobian must be {self.n}-by-{self.n}.')
            return jac_wrapped, J
        J = np.asarray(jac, dtype=y0.dtype)
        if J.shape != (self.n, self.n):
            raise SolverError(f'The Jacobian must be {self.n}-by-{self.n}.')
        return None, J

    def _validate_implicit_jac(self, jac, yp0):
        """(dF/dy, dF/dy'): given as two matrices, by a function (t, y, yp),
        or by differences."""
        t0, y0 = self.t, self.y
        if jac is None:
            def jac_wrapped(t, y, yp):
                self.njev += 1
                F0 = self.F(t, y, yp)
                Fy = _fd(lambda z: self.F(t, z, yp), y, F0, self.atol * np.ones(self.n))
                Fyp = _fd(lambda z: self.F(t, y, z), yp, F0, np.maximum(np.abs(yp), 1.0) * 1e-8)
                return Fy, Fyp
        elif callable(jac):
            def jac_wrapped(t, y, yp):
                self.njev += 1
                Fy, Fyp = jac(t, y, yp)
                return np.asarray(Fy, dtype=y0.dtype), np.asarray(Fyp, dtype=y0.dtype)
        else:
            pair = (np.asarray(jac[0], dtype=y0.dtype), np.asarray(jac[1], dtype=y0.dtype))
            for m in pair:
                if m.shape != (self.n, self.n):
                    raise SolverError(f'The Jacobian matrices must be {self.n}-by-{self.n}.')
            return None, pair
        return jac_wrapped, jac_wrapped(t0, y0, yp0)

    def _matrix(self, t, y, c, J):
        if self.mode == 'ode':
            return self.I - c * J
        if self.mode == 'mass':
            return self.M(t, y) - c * J
        Fy, Fyp = J
        return c * Fy + Fyp

    def _rhs(self, t, y, c, psi, d):
        """The right side of Newton's linear system at (t, y)."""
        if self.mode == 'ode':
            f = self.fun(t, y)
            return c * f - psi - d if np.all(np.isfinite(f)) else None
        if self.mode == 'mass':
            f = self.fun(t, y)
            return c * f - self.M(t, y) @ (psi + d) if np.all(np.isfinite(f)) else None
        F = np.asarray(self.F(t, y, (psi + d) / c), dtype=self.y.dtype)
        return -c * F if np.all(np.isfinite(F)) else None

    def _solve_system(self, t_new, y_predict, c, psi, LU, scale):
        d = 0
        y = y_predict.copy()
        dy_norm_old = None
        converged = False
        for k in range(NEWTON_MAXITER):
            r = self._rhs(t_new, y, c, psi, d)
            if r is None:
                break
            self.nlinsolve += 1
            dy = lu_solve(LU, r, overwrite_b=True)
            dy_norm = _norm(dy / scale)
            rate = None if dy_norm_old is None else dy_norm / dy_norm_old
            if rate is not None and (rate >= 1 or rate ** (NEWTON_MAXITER - k) / (1 - rate) * dy_norm > self.newton_tol):
                break
            y += dy
            d += dy
            if dy_norm == 0 or rate is not None and rate / (1 - rate) * dy_norm < self.newton_tol:
                converged = True
                break
            dy_norm_old = dy_norm
        return converged, k + 1, y, d

    def _step_impl(self):
        t = self.t
        D = self.D
        max_step = self.max_step
        min_step = 10 * np.abs(np.nextafter(t, self.direction * np.inf) - t)
        if self.h_abs > max_step:
            h_abs = max_step
            _change_D(D, self.order, max_step / self.h_abs)
            self.n_equal_steps = 0
        elif self.h_abs < min_step:
            h_abs = min_step
            _change_D(D, self.order, min_step / self.h_abs)
            self.n_equal_steps = 0
        else:
            h_abs = self.h_abs
        atol, rtol, order = self.atol, self.rtol, self.order
        alpha, gamma, error_const = self.alpha, self.gamma, self.error_const
        J = self.J
        LU = self.LU
        current_jac = self.jac is None
        step_accepted = False
        while not step_accepted:
            if h_abs < min_step:
                return False, self.TOO_SMALL_STEP
            h = h_abs * self.direction
            t_new = t + h
            if self.direction * (t_new - self.t_bound) > 0:
                t_new = self.t_bound
                _change_D(D, order, np.abs(t_new - t) / h_abs)
                self.n_equal_steps = 0
                LU = None
            h = t_new - t
            h_abs = np.abs(h)
            y_predict = np.sum(D[:order + 1], axis=0)
            scale = atol + rtol * np.abs(y_predict)
            psi = np.dot(D[1: order + 1].T, gamma[1: order + 1]) / alpha[order]
            converged = False
            c = h / alpha[order]
            while not converged:
                if LU is None:
                    self.nlu += 1
                    LU = lu_factor(self._matrix(t_new, y_predict, c, J), overwrite_a=True)
                converged, n_iter, y_new, d = self._solve_system(t_new, y_predict, c, psi, LU, scale)
                if not converged:
                    if current_jac:
                        break
                    J = self.jac(t_new, y_predict) if self.mode != 'implicit' else self.jac(t_new, y_predict, psi / c)
                    LU = None
                    current_jac = True
            if not converged:
                factor = 0.5
                h_abs *= factor
                _change_D(D, order, factor)
                self.n_equal_steps = 0
                LU = None
                continue
            safety = 0.9 * (2 * NEWTON_MAXITER + 1) / (2 * NEWTON_MAXITER + n_iter)
            scale = atol + rtol * np.abs(y_new)
            error = error_const[order] * d
            error_norm = _norm(error / scale)
            if error_norm > 1:
                factor = max(MIN_FACTOR, safety * error_norm ** (-1 / (order + 1)))
                h_abs *= factor
                _change_D(D, order, factor)
                self.n_equal_steps = 0
            else:
                step_accepted = True
        self.n_equal_steps += 1
        self.t = t_new
        self.y = y_new
        self.h_abs = h_abs
        self.J = J
        self.LU = LU
        D[order + 2] = d - D[order + 1]
        D[order + 1] = d
        for i in reversed(range(order + 1)):
            D[i] += D[i + 1]
        if self.n_equal_steps < order + 1:
            return True, None
        if order > 1:
            error_m = error_const[order - 1] * D[order]
            error_m_norm = _norm(error_m / scale)
        else:
            error_m_norm = np.inf
        if order < self.max_order:
            error_p = error_const[order + 1] * D[order + 2]
            error_p_norm = _norm(error_p / scale)
        else:
            error_p_norm = np.inf
        error_norms = np.array([error_m_norm, error_norm, error_p_norm])
        with np.errstate(divide='ignore'):
            factors = error_norms ** (-1 / np.arange(order, order + 3))
        delta_order = np.argmax(factors) - 1
        order += delta_order
        self.order = order
        factor = min(MAX_FACTOR, safety * np.max(factors))
        self.h_abs *= factor
        _change_D(D, order, factor)
        self.n_equal_steps = 0
        self.LU = None
        return True, None

    def _dense_output_impl(self):
        return _NdfDense(self.t_old, self.t, self.h_abs * self.direction, self.order, self.D[:self.order + 1].copy())


class _NdfDense(DenseOutput):
    """The interpolating polynomial through the last order + 1 points."""

    def __init__(self, t_old, t, h, order, D):
        super().__init__(t_old, t)
        self.order = order
        self.t_shift = self.t - h * np.arange(self.order)
        self.denom = h * (1 + np.arange(self.order))
        self.D = D

    def _call_impl(self, t):
        if t.ndim == 0:
            x = (t - self.t_shift) / self.denom
            p = np.cumprod(x)
        else:
            x = (t - self.t_shift[:, None]) / self.denom[:, None]
            p = np.cumprod(x, axis=0)
        y = np.dot(self.D[1:].T, p)
        if y.ndim == 1:
            y += self.D[0]
        else:
            y += self.D[0, :, None]
        return y
