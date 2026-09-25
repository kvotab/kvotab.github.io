"""Rosenbrock (2,3): the stiff one-step method (``src/ode/solvers/rosenbrock23.js``).

The modified Rosenbrock triple of Shampine and Reichelt (the method of
MATLAB's ode23s): one iteration matrix I - h*d*J per step, three solves, a
second-order solution with a third-order error estimate and a quadratic
interpolant. It forms the matrix afresh every step, which makes it steady
through a discontinuity.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

import numpy as np

from ..jacobian import difference_increment, difference_jacobian
from . import SolverError
from . import kernels
from .matrix import IterationMatrix
from .onestep import integrate

SINGULAR_HINT = 'A compartment with no way in and no way out will do this.'
D = 1 / (2 + math.sqrt(2))
E32 = 6 + math.sqrt(2)
EPS = 2.0 ** -52
SQRT_EPS = math.sqrt(EPS)


class _Stepper:
    def __init__(self, neq: int, rhs: Any, threshold: np.ndarray, opts: Dict[str, Any]) -> None:
        self.neq = neq
        self.rhs = rhs
        self.threshold = threshold
        supplied = opts.get('jacobian')
        self.pattern = supplied.get('pattern') if supplied else None
        self.groups = supplied.get('groups') if supplied else None
        self.evaluate = supplied.get('evaluate') if supplied else None
        self.constant = bool(supplied.get('constant')) if supplied else False
        self.f0 = np.zeros(neq)
        self.ft = np.zeros(neq)
        self.npds = 0
        self.ndecomps = 0
        self.spent = 0
        self.need_jacobian = True
        self.dfdt_at = math.nan
        self.J: Any = None
        self.W: Optional[IterationMatrix] = None
        self._fused = None
        if kernels.available():
            self._fused = (kernels.kernel('ros_first'), kernels.kernel('ros_second'), kernels.kernel('ros_third'))
            self._tmp = np.zeros(neq)

    def _jacobian(self, t: float, y: np.ndarray) -> Any:
        if self.evaluate is not None:
            got = self.evaluate(t, y)
            if got is not None:
                return np.asarray(got, dtype=float)
        if self.pattern is not None:
            self.spent += len(self.groups) if self.groups is not None else self.neq
            return difference_jacobian(self.rhs, t, y, self.f0, self.pattern, self.groups, self.threshold)
        dl = difference_increment(y, self.threshold)
        J = np.zeros((self.neq, self.neq))
        for j in range(self.neq):
            ytry = y.copy()
            ytry[j] = y[j] + dl[j]
            J[:, j] = (np.asarray(self.rhs(t, ytry)) - self.f0) / dl[j]
        self.spent += self.neq
        return J

    def start(self, t: float, y: np.ndarray) -> int:
        self.f0 = np.asarray(self.rhs(t, y), dtype=float)
        self.J = self._jacobian(t, y)
        self.npds += 1
        self.need_jacobian = False
        self.W = IterationMatrix(self.neq, self.pattern, self.J, 'auto', None, {'singular': SINGULAR_HINT})
        return 1

    def derivative_at_start(self) -> np.ndarray:
        return self.f0

    def attempt(self, t: float, y: np.ndarray, h: float, tnew: float, ynew: np.ndarray,
                err: np.ndarray) -> Tuple[int, float]:
        before = self.spent
        if self.need_jacobian and not (self.constant and self.npds > 0):
            self.J = self._jacobian(t, y)
            self.npds += 1
        self.need_jacobian = False
        if self.dfdt_at != t:
            dt = math.copysign(min(SQRT_EPS * max(abs(t), abs(t + h)), abs(h)), h)
            f1 = np.asarray(self.rhs(t + dt, y), dtype=float)
            self.spent += 1
            self.ft = (f1 - self.f0) / dt
            self.dfdt_at = t
        try:
            self.W.form(h * D, self.J)  # type: ignore[union-attr]
        except RuntimeError as e:
            raise SolverError('singular', f'{e} (at t={t})', t) from None
        self.ndecomps += 1
        W = self.W
        if self._fused is not None and W._lu == 'kernel':  # type: ignore[union-attr]
            return self._attempt_fused(t, y, h, tnew, ynew, err, before)
        solve = W.solve  # type: ignore[union-attr]
        f0, ft = self.f0, self.ft
        k1 = solve(f0 + h * D * ft)
        f1 = np.asarray(self.rhs(t + 0.5 * h, y + 0.5 * h * k1), dtype=float)
        k2 = solve(f1 - k1) + k1
        ynew[:] = y + h * k2
        f2 = np.asarray(self.rhs(tnew, ynew), dtype=float)
        k3 = solve(f2 - E32 * (k2 - f1) - 2 * (k1 - f0) + h * D * ft)
        self.spent += 2
        err[:] = k1 - 2 * k2 + k3
        self.t_from, self.h_from, self.y_from = t, h, y.copy()
        self.k2 = k2
        self.f2 = f2
        return self.spent - before, 1 / 6

    def _attempt_fused(self, t: float, y: np.ndarray, h: float, tnew: float, ynew: np.ndarray, err: np.ndarray,
                       before: int) -> Tuple[int, float]:
        """The same step with its arithmetic compiled (``kernels.py``): the
        application's loops, value for value."""
        first, second, third = self._fused  # type: ignore[misc]
        W = self.W
        lu, piv, tmp = W._lu_buf, W._piv, self._tmp  # type: ignore[union-attr]
        n = self.neq
        f0, ft = self.f0, self.ft
        hD = h * D
        k1 = np.empty(n)
        ymid = np.empty(n)
        first(lu, piv, f0, ft, hD, y, 0.5 * h, tmp, k1, ymid)
        f1 = np.asarray(self.rhs(t + 0.5 * h, ymid), dtype=float)
        k2 = np.empty(n)
        second(lu, piv, f1, k1, y, h, tmp, k2, ynew)
        f2 = np.asarray(self.rhs(tnew, ynew), dtype=float)
        k3 = np.empty(n)
        third(lu, piv, f2, k2, f1, k1, f0, ft, hD, E32, tmp, k3, err)
        self.spent += 2
        self.t_from, self.h_from, self.y_from = t, h, y.copy()
        self.k2 = k2
        self.f2 = f2
        return self.spent - before, 1 / 6

    def dense_at(self, tq: float) -> np.ndarray:
        s = (tq - self.t_from) / self.h_from
        return self.y_from + s * self.h_from * self.f0 + s * s * self.h_from * (self.k2 - self.f0)

    def accept(self, tnew: float, ynew: np.ndarray, reprojected: bool) -> int:
        used = 0
        if reprojected:
            self.f2 = np.asarray(self.rhs(tnew, ynew), dtype=float)
            used = 1
        self.f0 = self.f2.copy()
        self.need_jacobian = True
        self.dfdt_at = math.nan
        return used

    def restart(self, t: float, y: np.ndarray) -> int:
        self.f0 = np.asarray(self.rhs(t, y), dtype=float)
        self.need_jacobian = True
        self.dfdt_at = math.nan
        return 1

    def stats(self) -> Dict[str, Any]:
        return {'npds': self.npds, 'ndecomps': self.ndecomps, 'sparse': bool(self.W and self.W.sparse),
                'fill': self.W.info['fill'] if self.W else None}


class _Method:
    id = 'ros23'
    order = 2
    default_max_steps = 1e6
    holds_at_zero = True
    snaps_to_constraint = True

    @staticmethod
    def step_budget_message(max_steps: float, t: float) -> str:
        return f'Exceeded {int(max_steps)} steps at t={t}.'

    @staticmethod
    def floor_message(t: float, hmin: float, worst: int) -> str:
        return (f'Unable to meet integration tolerances at t={t} without reducing the step below the smallest allowed '
                f'({hmin}).')

    @staticmethod
    def stall_message(t: float, window: int, covered: float) -> str:
        return (f'The solver stopped making progress at t={t}: {window} steps advanced the clock by less than '
                f'{covered}. This usually means a state reaching zero while its equations push it below -- a '
                'constraint that binds is not one a one-step method can carry; turn "cannot go negative" off on the '
                'compartment to see what the model really does, or use variableOrder -- or that a rate changes faster '
                'than the step size can follow.')

    @staticmethod
    def set_up(neq: int, rhs: Any, f: Any, threshold: np.ndarray, atol: np.ndarray, rtol: float,
               opts: Dict[str, Any]) -> _Stepper:
        return _Stepper(neq, rhs, threshold, opts)


def rosenbrock23(f: Any, tspan: Any, y0: np.ndarray, opts: Dict[str, Any]) -> Dict[str, Any]:
    return integrate(_Method, f, tspan, y0, opts)
