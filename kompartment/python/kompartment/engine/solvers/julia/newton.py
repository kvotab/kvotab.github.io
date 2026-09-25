"""The simplified Newton iteration the implicit methods share (``core/newton.js``).

W is held fixed across the iterations of a stage, and usually across steps;
the convergence machinery -- the contraction estimate theta, the forecast
eta = theta/(1 - theta), the divergence tests, the carried-over eta -- is
OrdinaryDiffEq's, with the package's two measured deviations: kappa defaults
to 1e-3 rather than 1e-2, and the eta forecast is not believed on the first
iteration.

W is the textbook I - gh*J here (OrdinaryDiffEq stores its negative), so a
correction is added where the Julia source subtracts it.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict

import numpy as np

from ._js import EPS, jdiv, jmax, jpow, max_or_zero, seq_sum

DIRK = 'DIRK'
COEFFICIENT_MULTISTEP = 'COEFFICIENT_MULTISTEP'

CONVERGENCE = 'Convergence'
DIVERGENCE = 'Divergence'
NEWTON_MAX_ITERS = 'MaxIters'
SINGULAR = 'Singular'

EPS_AROUND_ONE = 100 * math.sqrt(EPS)
DEFAULT_KAPPA = 1e-3


def residual_norm(dz: np.ndarray, uprev: np.ndarray, ustep: np.ndarray, abstol: Any, reltol: float, n: int,
                  norm: str) -> float:
    """Each component of the increment against what a unit of error would be
    for it (``residualNorm``); a component that is not a number makes it NaN,
    in either norm."""
    w = abstol + reltol * np.maximum(np.abs(uprev), np.abs(ustep))
    if norm == 'max':
        return max_or_zero(np.abs(dz) / w)
    r = dz / w
    return math.sqrt(seq_sum(r * r) / n)


class NewtonSolver:
    """One reusable simplified-Newton solver (``NewtonSolver``).

    The caller sets ``tmp``, ``gamma``, ``c`` and ``method`` and seeds ``z``
    before each solve, and reads ``z`` afterwards.
    """

    def __init__(self, n: int, norm: Any = None, kappa: Any = None, max_iters: Any = None,
                 fast_convergence_cutoff: Any = None) -> None:
        self.n = n
        self.kappa = kappa if kappa is not None else DEFAULT_KAPPA
        self.max_iters = max_iters if max_iters is not None else 10
        self.fast_convergence_cutoff = fast_convergence_cutoff if fast_convergence_cutoff is not None else 0.2
        self.norm = norm or 'rms'
        self.z = np.zeros(n)
        self.tmp = np.zeros(n)
        self.ustep = np.zeros(n)
        self.gamma = 1.0
        self.c = 0.0
        self.method = DIRK
        self.eta_old = 1.0
        self.prev_theta = 1.0
        self.status = CONVERGENCE
        self.iter = 0
        self.eta = 1.0
        self.ndz = 0.0
        self.nfails = 0
        self.nf = 0
        self.error_constant = 1.0

    def reset(self) -> None:
        self.eta_old = 1.0
        self.prev_theta = 1.0
        self.nfails = 0

    def apply_step(self, out: np.ndarray) -> np.ndarray:
        if self.method == DIRK:
            out[:] = self.tmp + self.gamma * self.z
        else:
            out[:] = self.z
        return out

    def solve(self, f: Callable[[float, np.ndarray], np.ndarray], W: Any, t: float, dt: float, uprev: np.ndarray,
              tol: Dict[str, Any], new_w: bool, last_accepted: bool = True) -> str:
        n = self.n
        z = self.z
        ustep = self.ustep
        kappa = self.kappa
        max_iters = self.max_iters
        gamma_dt = self.gamma * dt
        tstep = t + self.c * dt
        eta = jpow(jmax(self.eta_old, EPS), 0.8) if new_w else self.eta_old
        ndz = 1.0
        prev_theta = self.prev_theta if last_accepted else 1.0
        self.status = DIVERGENCE
        abstol = tol['abstol']
        reltol = tol['reltol']

        it = 1
        while it <= max_iters:
            self.iter = it
            ndz_prev = ndz
            self.apply_step(ustep)
            self.nf += 1
            k = f(tstep, ustep)
            if self.method == DIRK:
                dz = dt * k - z
            else:
                dz = self.tmp + gamma_dt * k - z
            dz = W.solve(dz)

            ndz = residual_norm(dz, uprev, ustep, abstol, reltol, n, self.norm)
            if self.error_constant != 1:
                ndz *= self.error_constant

            if not math.isfinite(ndz):
                self.status = DIVERGENCE
                self.nfails += 1
                break

            if it > 1:
                theta = prev_theta = jmax(0.3 * prev_theta, jdiv(ndz, ndz_prev))
                if abs(theta - 1) <= EPS_AROUND_ONE:
                    if ndz <= 1:
                        self.status = CONVERGENCE
                        self.nfails = 0
                        z += dz
                        self.eta = eta
                        self.ndz = ndz
                        self.eta_old = eta
                        self.prev_theta = prev_theta
                        return self.status
                    self.status = DIVERGENCE
                    self.nfails += 1
                    break
                if theta > 2:
                    self.status = DIVERGENCE
                    self.nfails += 1
                    break
            else:
                theta = prev_theta

            z += dz
            eta = jdiv(theta, 1 - theta)
            if (it == 1 and ndz < 1e-5) or (it > 1 and eta >= 0 and eta * ndz < kappa):
                self.status = CONVERGENCE
                self.nfails = 0
                break
            if it == max_iters:
                self.status = NEWTON_MAX_ITERS
                self.nfails += 1
            it += 1

        self.eta = eta
        self.ndz = ndz
        self.eta_old = eta
        self.prev_theta = prev_theta
        return self.status

    @property
    def fast_convergence(self) -> bool:
        return self.status == CONVERGENCE and self.eta < self.fast_convergence_cutoff
