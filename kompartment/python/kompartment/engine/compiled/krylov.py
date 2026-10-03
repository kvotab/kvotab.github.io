# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at https://mozilla.org/MPL/2.0/.
#
# _sym_givens and _gmres are a port of Krylov.jl's sym_givens and gmres!,
# https://github.com/JuliaSmoothOptimizers/Krylov.jl, Copyright (c)
# 2015-present: Alexis Montoison, Dominique Orban, and other contributors, by
# way of ../solvers/julia/krylov.py; like that file and Krylov.jl, and unlike
# the rest of this package (LICENSE at its root), this file is licensed under
# the MPL 2.0.

"""GMRES, and the matrix-free W of the Krylov FBDF, compiled with numba: a
port of ``solvers/julia/krylov.py`` with the same arithmetic in the same
order -- every inner product summed left to right from its first term, as
that file sums it -- for the compiled loop of :mod:`.julia`, whose Newton
iteration calls :func:`_krylov_solve` where a KrylovFBDF forms no W.

``kry``: the state (kwf, kwi, named by the constants below), the error
weights, the last solution, the basis held in a list of one array (which
grows, as ``GMRES._basis`` grows it, up to 256 MB), and the work vectors:
b/(gh), the solution, a residual, w, q, a scaled basis vector, a product, a
perturbed state, and the warm start.
"""

from __future__ import annotations

import math

import numpy as np
from numba import njit

from . import guard_numba_cache

guard_numba_cache()

EPS = 2.0 ** -52
SQRT_EPS = math.sqrt(EPS)
BTOL = EPS ** 0.75                       # ``krylov.BTOL``
#: LinearSolve's Hegedus acceptance: the guess must at least halve the residual.
HEGEDUS_MIN_COSINE = math.sqrt(1 - 0.5 ** 2)
C_NF = 0                                 # ``julia.C_NF``: the count of f evaluations

# ``KrylovW``'s state: floats (``kwf``) and integers (``kwi``).
KF_T = 0               # where the Newton iteration is: its time,
KF_GAMMA_DT = 1        # gh,
KF_ZNORM = 2           # and ||z||
NKF = 3
KI_HAVE_PREV = 0       # the last solution, for Hegedus's warm start
KI_NSOLVE = 1
KI_NITER = 2
KI_NJVP = 3
KI_NFAIL = 4
KI_WARM = 5
KI_MAX_BASIS = 6       # the basis vectors GMRES may hold
KI_MEMORY = 7          # and how many it starts with
NKI = 8

_OPTS = dict(cache=True, error_model='numpy')


@njit(inline='always', **_OPTS)
def _jmax(a, b):
    """``Math.max``: NaN wins, and +0 is larger than -0 (``julia._jmax``)."""
    if a != a or b != b:
        return np.nan
    if a > b:
        return a
    if b > a:
        return b
    if a == 0 and b == 0:
        return b if math.copysign(1.0, a) < 0 else a
    return a


@njit(inline='always', **_OPTS)
def _jsign(x):
    """``Math.sign`` (``julia._jsign``)."""
    if x != x:
        return np.nan
    if x > 0:
        return 1.0
    if x < 0:
        return -1.0
    return x


@njit(inline='always', **_OPTS)
def _npmax(a, b):
    """numpy's ``maximum``: NaN when either is."""
    if a != a or b != b:
        return np.nan
    return a if a >= b else b


@njit(inline='always', **_OPTS)
def _seq_dot(x, y):
    """``seq_sum(x * y)``: left to right from the first product, as
    ``np.cumsum`` sums."""
    n = x.size
    if n == 0:
        return 0.0
    s = x[0] * y[0]
    for i in range(1, n):
        s += x[i] * y[i]
    return s


@njit(**_OPTS)
def _sym_givens(a, b):
    """Krylov.jl's ``sym_givens`` for real a, b: (c, s, rho) with
    [c s; s -c] [a; b] = [rho; 0]."""
    if b == 0:
        c = 1.0 if a == 0 else _jsign(a)
        return c, 0.0, abs(a)
    if a == 0:
        return 0.0, _jsign(b), abs(b)
    if abs(b) > abs(a):
        t = a / b
        s = _jsign(b) / math.sqrt(1 + t * t)
        return s * t, s, b / s
    t = b / a
    c = _jsign(a) / math.sqrt(1 + t * t)
    return c, c * t, a / c


@njit(**_OPTS)
def _krylov_prepare(kry, atol0, rtol, uprev, u):
    """``KrylovW.prepare``: this step's error weights,
    1/(abstol + reltol*max(|uprev|, |u|)), one where that is no number to
    scale by."""
    weight = kry[2]
    for i in range(u.size):
        w = atol0[i] + rtol * _npmax(abs(uprev[i]), abs(u[i]))
        weight[i] = 1 / w if (w > 0 and math.isfinite(w)) else 1.0


@njit(**_OPTS)
def _krylov_apply(f, model, pycb, ctr, kry, z, fz, v, out):
    """``KrylovW.apply_w``: Julia's W v = J v - v/(gh), J v a forward
    difference of f at the Newton iteration's point (``jvp``)."""
    P, X, Wm, IW = model
    kwf, kwi = kry[0], kry[1]
    upert = kry[12]
    n = v.size
    kwi[KI_NJVP] += 1
    nx = kwf[KF_ZNORM] if math.isfinite(kwf[KF_ZNORM]) else 0.0
    nv = math.sqrt(_seq_dot(v, v))
    eps = _jmax(SQRT_EPS * nx, SQRT_EPS)
    if nv != 0 and math.isfinite(nv):
        eps /= nv
    for i in range(n):
        upert[i] = z[i] + eps * v[i]
    f(kwf[KF_T], upert, out, P, X, Wm, IW, pycb)
    ctr[C_NF] += 1
    for i in range(n):
        out[i] = (out[i] - fz[i]) / eps
    inv = 1.0 / kwf[KF_GAMMA_DT]
    for i in range(n):
        out[i] = out[i] - v[i] * inv


@njit(**_OPTS)
def _gmres(f, model, pycb, ctr, kry, z, fz, b, atol, rtol, itmax, warm):
    """``GMRES.solve`` with restart off and the diagonal error weights on
    both sides, started -- when ``warm`` -- from the warm start in ``kry``:
    the answer in ``kry``'s solution vector, and (solved, iterations)."""
    kwi = kry[1]
    weight = kry[2]
    Vh = kry[4]
    x, r0, w, q, vs, ax, dx = kry[6], kry[7], kry[8], kry[9], kry[10], kry[11], kry[13]
    n = b.size
    for i in range(n):
        x[i] = 0.0
    if warm:
        _krylov_apply(f, model, pycb, ctr, kry, z, fz, dx, ax)
        for i in range(n):
            w[i] = b[i] - ax[i]
    else:
        for i in range(n):
            w[i] = b[i]
    for i in range(n):
        r0[i] = weight[i] * w[i]
    beta = math.sqrt(_seq_dot(r0, r0))
    r_norm = beta
    eps = atol + rtol * r_norm
    if beta == 0:
        if warm:
            for i in range(n):
                x[i] += dx[i]
        return True, 0
    asked = itmax if itmax > 0 else 2 * n
    it_max = min(asked, kwi[KI_MAX_BASIS])
    solved = r_norm <= eps
    k = 0
    if not solved:
        cg = np.zeros(it_max + 1)
        sg = np.zeros(it_max + 1)
        zz = np.zeros(it_max + 1)
        # R holds k(k+1)/2 coefficients after k iterations; it grows as they come.
        R = np.zeros(min(64, it_max) * (min(64, it_max) + 1) // 2)
        nr = 0
        zz[0] = beta
        V = Vh[0]
        for i in range(n):
            V[0, i] = r0[i] / r_norm
        while True:
            k += 1
            V = Vh[0]
            vk = V[k - 1]
            for i in range(n):
                vs[i] = vk[i] / weight[i]
            _krylov_apply(f, model, pycb, ctr, kry, z, fz, vs, q)
            for i in range(n):
                q[i] = weight[i] * q[i]
            if nr + k > R.size:
                bigger = np.zeros(max(2 * R.size, nr + k))
                bigger[:R.size] = R
                R = bigger
            for i in range(k):
                vi = V[i]
                h = _seq_dot(vi, q)
                R[nr + i] = h
                for j in range(n):
                    q[j] -= h * vi[j]
            hbis = math.sqrt(_seq_dot(q, q))
            # The previous rotations, then this column's own.
            for i in range(k - 1):
                a1 = R[nr + i]
                a2 = R[nr + i + 1]
                R[nr + i] = cg[i] * a1 + sg[i] * a2
                R[nr + i + 1] = sg[i] * a1 - cg[i] * a2
            cgk, sgk, rho = _sym_givens(R[nr + k - 1], hbis)
            cg[k - 1] = cgk
            sg[k - 1] = sgk
            R[nr + k - 1] = rho
            zeta = sg[k - 1] * zz[k - 1]
            zz[k - 1] = cg[k - 1] * zz[k - 1]
            r_norm = abs(zeta)
            nr += k
            solved = r_norm <= eps
            breakdown = hbis <= BTOL
            tired = k >= it_max
            if solved or tired or breakdown or not math.isfinite(r_norm):
                break
            if k >= V.shape[0]:
                grown = np.zeros((min(2 * V.shape[0], kwi[KI_MAX_BASIS]), n))
                grown[:V.shape[0]] = V
                Vh[0] = grown
                V = grown
            vn = V[k]
            for i in range(n):
                vn[i] = q[i] / hbis
            zz[k] = zeta
        # y from R y = z by back substitution, in Krylov.jl's packed indexing.
        V = Vh[0]
        for i in range(k, 0, -1):
            pos = nr + i - k
            for j in range(k, i, -1):
                zz[i - 1] -= R[pos - 1] * zz[j - 1]
                pos = pos - j + 1
            if abs(R[pos - 1]) <= BTOL:
                zz[i - 1] = 0.0
            else:
                zz[i - 1] /= R[pos - 1]
        for i in range(k):
            yi = zz[i]
            vi = V[i]
            for j in range(n):
                x[j] += yi * vi[j]
        for j in range(n):
            x[j] /= weight[j]
    if warm:
        for i in range(n):
            x[i] += dx[i]
    return solved, k


@njit(**_OPTS)
def _krylov_solve(f, model, pycb, ctr, kry, b, z, fz, rtol):
    """``KrylovW.solve``: (I - gh J) dz = b in place, as the Newton iteration
    expects; a solve that failed answers infinities, which the Newton
    iteration takes as divergence."""
    kwf, kwi = kry[0], kry[1]
    weight, x_prev = kry[2], kry[3]
    bj, x, dx, ax = kry[5], kry[6], kry[13], kry[11]
    n = b.size
    gdt = kwf[KF_GAMMA_DT]
    for i in range(n):
        bj[i] = b[i] / gdt
    atol = SQRT_EPS
    # Hegedus's warm start: the last solution scaled to minimise the
    # residual along it, kept only if that at least halves it.
    warm = False
    if kwi[KI_HAVE_PREV]:
        unorm = math.sqrt(_seq_dot(x_prev, x_prev))
        if unorm != 0 and math.isfinite(unorm):
            _krylov_apply(f, model, pycb, ctr, kry, z, fz, x_prev, ax)
            d = _seq_dot(ax, ax)
            if d != 0 and math.isfinite(d):
                aub = _seq_dot(ax, bj)
                if math.isfinite(aub):
                    bnorm = math.sqrt(_seq_dot(bj, bj))
                    if bnorm != 0 and math.isfinite(bnorm):
                        if not (abs(aub) < HEGEDUS_MIN_COSINE * math.sqrt(d) * bnorm):
                            xi = aub / d
                            for i in range(n):
                                dx[i] = xi * x_prev[i]
                            warm = True
    a = atol
    r = rtol
    if warm:
        # The threshold kept at the cold start's: atol + rtol*||M^-1 b||.
        ss = 0.0
        first = True
        for i in range(n):
            v = weight[i] * bj[i]
            if first:
                ss = v * v
                first = False
            else:
                ss += v * v
        a = atol + rtol * math.sqrt(ss)
        r = 0.0
        kwi[KI_WARM] += 1
    solved, k = _gmres(f, model, pycb, ctr, kry, z, fz, bj, a, r, n, warm)
    kwi[KI_NSOLVE] += 1
    kwi[KI_NITER] += k
    if not solved:
        kwi[KI_NFAIL] += 1
        kwi[KI_HAVE_PREV] = 0
        for i in range(n):
            b[i] = np.inf
        return
    for i in range(n):
        x_prev[i] = x[i]
    kwi[KI_HAVE_PREV] = 1
    for i in range(n):
        b[i] = -x[i]
