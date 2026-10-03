# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at https://mozilla.org/MPL/2.0/.
#
# GMRES and sym_givens are a port of Krylov.jl's gmres! and sym_givens,
# https://github.com/JuliaSmoothOptimizers/Krylov.jl, Copyright (c)
# 2015-present: Alexis Montoison, Dominique Orban, and other contributors,
# which is licensed under the MPL 2.0; so, unlike the rest of this package
# (LICENSE beside this file), is this file.

"""GMRES, and the matrix-free W of the Krylov FBDF (``core/krylov.js``).

What OrdinaryDiffEq does with ``FBDF(linsolve = KrylovJL_GMRES())``, the stiff
method its default algorithm takes for a system of more than 500 states: no
matrix is formed, and each Newton iteration solves its linear system by GMRES,
with J*v a directional difference of f at the current iterate,

    J*v ~ (f(z + eps*v) - f(z)) / eps,   eps = max(sqrt(eps)*||z||, sqrt(eps)) / ||v||

(FiniteDiff.jl's step), or the problem's own ``jvp`` where it has one. Each
GMRES iteration costs one evaluation of f.

The pieces are OrdinaryDiffEq's, as the package stacks them: Julia's form of
the system, ``(J - I/(gh)) x = b/(gh)``, whose absolute tolerance means what it
means there; a diagonal scaling on both sides by the error weights
(``wrapprecs``); rtol the integration's reltol and atol sqrt(eps); at most n
iterations, never restarted; a warm start from the previous solution rescaled
by Hegedus's trick, kept only when it halves the residual; and Krylov.jl's
GMRES itself, modified Gram-Schmidt and its Givens rotations. The basis never
grows past 256 MB; a solve that reaches the cap fails as one that reaches its
iteration limit does.

Every inner product is summed left to right, as the package sums it
(:func:`._js.seq_sum`), not by BLAS: the iteration counts, and so the f
evaluations a run reports, are decided on those sums.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from ._js import EPS, INF, SQRT_EPS, jdiv, jmax, jsign, seq_sum

JVP_SQRT_EPS = SQRT_EPS
BTOL = EPS ** 0.75
BASIS_MAX_BYTES = 256 * 1024 * 1024
# LinearSolve's Hegedus acceptance: the guess must at least halve the residual.
HEGEDUS_MIN_COSINE = math.sqrt(1 - 0.5 ** 2)


def sym_givens(a: float, b: float) -> Tuple[float, float, float]:
    """Krylov.jl's ``sym_givens`` for real a, b: (c, s, rho) with
    [c s; s -c] [a; b] = [rho; 0] (``symGivens``)."""
    if b == 0:
        c = 1.0 if a == 0 else jsign(a)
        s = 0.0
        rho = abs(a)
    elif a == 0:
        c = 0.0
        s = jsign(b)
        rho = abs(b)
    elif abs(b) > abs(a):
        t = a / b
        s = jdiv(jsign(b), math.sqrt(1 + t * t))
        c = s * t
        rho = jdiv(b, s)
    else:
        t = jdiv(b, a)
        c = jdiv(jsign(a), math.sqrt(1 + t * t))
        s = c * t
        rho = jdiv(a, c)
    return c, s, rho


def _dot(x: np.ndarray, y: np.ndarray) -> float:
    """``s = 0; s += x[i] * y[i]``, in order."""
    return seq_sum(x * y)


def _norm2(x: np.ndarray) -> float:
    return math.sqrt(seq_sum(x * x))


class GMRES:
    """GMRES without restarts, as Krylov.jl's ``gmres!`` with restart = false
    (``GMRES``). The basis grows as it is needed, from ``memory`` vectors up
    to ``max_basis``."""

    def __init__(self, n: int, memory: Optional[int] = None, max_bytes: Optional[float] = None) -> None:
        self.n = n
        self.memory = min(memory if memory is not None else 20, n)
        self.max_basis = max(self.memory, math.floor(
            (max_bytes if max_bytes is not None else BASIS_MAX_BYTES) / (8 * max(1, n))))
        self.V: List[np.ndarray] = []
        self.stats: Dict[str, Any] = {'niter': 0, 'solved': False, 'status': '', 'r_norm': 0.0}

    def _basis(self, k: int) -> np.ndarray:
        while len(self.V) <= k:
            self.V.append(np.zeros(self.n))
        return self.V[k]

    def solve(self, A: Callable[[np.ndarray], np.ndarray], b: np.ndarray, atol: float, rtol: float,
              itmax: int = 0, left: Optional[np.ndarray] = None, right: Optional[np.ndarray] = None,
              x0: Optional[np.ndarray] = None) -> np.ndarray:
        """Solve A x = b and answer x, with :attr:`stats` saying how it went.

        ``left`` is a diagonal left preconditioner applied as M^-1 v = left*v,
        ``right`` a diagonal right one applied as N^-1 v = v/right
        (OrdinaryDiffEq's InvPreconditioner(Diagonal(w)) and Diagonal(w),
        ldiv'd); ``x0`` a warm start, already chosen; ``itmax`` 0 is 2n."""
        n = self.n
        V = self.V
        stats = self.stats
        warm = x0 is not None
        x = np.zeros(n)
        if warm:
            dx = np.array(x0, dtype=float)
            w = b - A(dx)
        else:
            dx = None
            w = b
        r0 = left * w if left is not None else np.array(w, dtype=float)
        beta = _norm2(r0)
        r_norm = beta
        eps = atol + rtol * r_norm

        if beta == 0:
            if warm:
                x += dx
            stats.update(niter=0, solved=True, status='x is a zero-residual solution', r_norm=0.0)
            return x

        asked = itmax if itmax > 0 else 2 * n
        it_max = min(asked, self.max_basis)
        capped = it_max == self.max_basis and asked > self.max_basis

        solved = r_norm <= eps
        breakdown = False
        inconsistent = False
        k = 0             # inner iterations
        nr = 0            # coefficients stored in R
        R: List[float] = []
        c: List[float] = []
        s: List[float] = []
        z: List[float] = []

        if not solved:
            z.append(beta)
            self._basis(0)[:] = r0 / r_norm
            while True:
                k += 1
                vk = V[k - 1]
                q = A(vk / right if right is not None else vk)
                q = left * q if left is not None else np.array(q, dtype=float)
                for i in range(k):
                    h = _dot(V[i], q)
                    R.append(h)
                    q -= h * V[i]
                hbis = _norm2(q)
                # The previous rotations, then this column's own.
                for i in range(k - 1):
                    a1 = R[nr + i]
                    a2 = R[nr + i + 1]
                    R[nr + i] = c[i] * a1 + s[i] * a2
                    R[nr + i + 1] = s[i] * a1 - c[i] * a2
                cg, sg, rho = sym_givens(R[nr + k - 1], hbis)
                c.append(cg)
                s.append(sg)
                R[nr + k - 1] = rho
                zeta = s[k - 1] * z[k - 1]
                z[k - 1] = c[k - 1] * z[k - 1]
                r_norm = abs(zeta)
                nr += k

                solved = r_norm <= eps
                breakdown = hbis <= BTOL
                tired = k >= it_max
                if solved or tired or breakdown or not math.isfinite(r_norm):
                    break
                self._basis(k)[:] = q / hbis
                z.append(zeta)

            # y from R y = z by back substitution, in Krylov.jl's packed
            # indexing (1-based positions, column after column).
            y = z
            for i in range(k, 0, -1):
                pos = nr + i - k
                for j in range(k, i, -1):
                    y[i - 1] -= R[pos - 1] * y[j - 1]
                    pos = pos - j + 1
                if abs(R[pos - 1]) <= BTOL:
                    y[i - 1] = 0.0
                    inconsistent = True
                else:
                    y[i - 1] /= R[pos - 1]
            for i in range(k):
                x += y[i] * V[i]
            if right is not None:
                x /= right
        if warm:
            x += dx

        stats['niter'] = k
        stats['solved'] = solved
        stats['r_norm'] = r_norm
        if solved:
            stats['status'] = ('found approximate least-squares solution' if inconsistent
                               else 'solution good enough given atol and rtol')
        elif capped and k >= it_max:
            stats['status'] = 'the basis reached its memory cap'
        elif k >= it_max:
            stats['status'] = 'maximum number of iterations exceeded'
        else:
            stats['status'] = 'breakdown' if breakdown else 'not a number'
        return x


class KrylovW:
    """The matrix-free W of the Krylov FBDF, with the ``solve(b)`` the Newton
    iteration calls (``KrylovW``).

    The Newton iteration says where it is before every solve --
    ``set_point(t, z, f(z), gh)`` -- and hands over this package's right-hand
    side, (I - gh J) dz = b. OrdinaryDiffEq solves (J - I/(gh)) x = b/(gh) and
    steps by -x: the same equation, in the form whose absolute tolerance
    means what it means there.
    """

    def __init__(self, n: int, integ: Any, opts: Dict[str, Any]) -> None:
        self.n = n
        self.integ = integ
        self.gmres = GMRES(n, memory=opts.get('krylov_memory'), max_bytes=opts.get('krylov_max_bytes'))
        self.weight = np.zeros(n)
        self.x_prev = np.zeros(n)
        self.have_prev = False
        self.t = 0.0
        self.z: Optional[np.ndarray] = None
        self.fz: Optional[np.ndarray] = None
        self.gamma_dt = 1.0
        self.z_norm = 0.0
        # Counted work: solves, GMRES iterations, products J*v, failed solves.
        self.nsolve = 0
        self.niter = 0
        self.njvp = 0
        self.nfail = 0
        self.warm_starts = 0

    def prepare(self, integ: Any) -> None:
        """This step's error weights, as OrdinaryDiffEq's Newton ``initialize!``
        sets them: 1/(abstol + reltol*max(|uprev|, |u|)). A weight that is no
        number to scale by -- zero, or infinite where a rejected non-finite
        step left a state -- is left at one: 1/inf would be a zero the right
        scaling then divides by."""
        w = integ.abstol_fixed + integ.reltol * np.maximum(np.abs(integ.uprev), np.abs(integ.u))
        with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
            inv = 1 / w
        self.weight = np.where((w > 0) & np.isfinite(w), inv, 1.0)

    def set_point(self, t: float, z: np.ndarray, fz: np.ndarray, gamma_dt: float) -> None:
        """Where the Newton iteration is: the linearisation point of J."""
        self.t = t
        self.z = z
        self.fz = fz
        self.gamma_dt = gamma_dt
        self.z_norm = _norm2(z)

    def jvp(self, v: np.ndarray) -> np.ndarray:
        """J*v at the current point: the problem's own, or a forward difference."""
        self.njvp += 1
        integ = self.integ
        if integ.prob.jvp is not None:
            return np.array(integ.prob.jvp(self.t, self.z, v, self.fz), dtype=float)
        nx = self.z_norm if math.isfinite(self.z_norm) else 0.0
        nv = _norm2(v)
        eps = jmax(JVP_SQRT_EPS * nx, JVP_SQRT_EPS)
        if nv != 0 and math.isfinite(nv):
            eps /= nv
        fpert = integ.f(self.t, self.z + eps * v)
        return (fpert - self.fz) / eps

    def apply_w(self, v: np.ndarray) -> np.ndarray:
        """Julia's W v = J v - v/(gh) (``applyW``)."""
        out = self.jvp(v)
        inv = jdiv(1.0, self.gamma_dt)
        return out - v * inv

    def hegedus(self, b: np.ndarray) -> Optional[np.ndarray]:
        """LinearSolve's Hegedus warm start: the previous solution scaled to
        minimise the residual along it, kept only if that at least halves it;
        None for a cold start."""
        if not self.have_prev:
            return None
        u = self.x_prev
        unorm = _norm2(u)
        if unorm == 0 or not math.isfinite(unorm):
            return None
        Au = self.apply_w(u)
        d = _dot(Au, Au)
        if d == 0 or not math.isfinite(d):
            return None
        Aub = _dot(Au, b)
        if not math.isfinite(Aub):
            return None
        bnorm = _norm2(b)
        if bnorm == 0 or not math.isfinite(bnorm):
            return None
        if abs(Aub) < HEGEDUS_MIN_COSINE * math.sqrt(d) * bnorm:
            return None
        xi = Aub / d
        return xi * u

    def solve(self, b: np.ndarray) -> np.ndarray:
        """Solve (I - gh J) dz = b in place, as the Newton iteration expects;
        a solve that failed answers infinities, which the Newton iteration
        takes as divergence."""
        n = self.n
        weight = self.weight
        bj = b / self.gamma_dt
        atol = JVP_SQRT_EPS
        rtol = self.integ.reltol
        x0 = self.hegedus(bj)
        a = atol
        r = rtol
        if x0 is not None:
            # The threshold kept at the cold start's: atol + rtol*||M^-1 b||,
            # with rtol then zero.
            v = weight * bj
            a = atol + rtol * math.sqrt(seq_sum(v * v))
            r = 0.0
            self.warm_starts += 1
        x = self.gmres.solve(self.apply_w, bj, atol=a, rtol=r, itmax=n, left=weight, right=weight, x0=x0)
        st = self.gmres.stats
        self.nsolve += 1
        self.niter += st['niter']
        if not st['solved']:
            self.nfail += 1
            self.have_prev = False
            b[:] = INF
            return b
        self.x_prev = x.copy()
        self.have_prev = True
        b[:] = -x
        return b

    def report(self) -> Dict[str, int]:
        return {'krylovSolves': self.nsolve, 'krylovIters': self.niter, 'krylovJvps': self.njvp,
                'krylovFailures': self.nfail, 'krylovWarmStarts': self.warm_starts}
