"""Dormand-Prince (4,5): the explicit method (``src/ode/solvers/dormand-prince.js``).

Seven stages with the first-same-as-last property, error controlled on the
fourth-order solution, and the continuous extension of Hairer-Norsett-Wanner
for output between steps.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

from .onestep import integrate

NODES = (1 / 5, 3 / 10, 4 / 5, 8 / 9, 1.0, 1.0)
STAGE = (
    (1 / 5,),
    (3 / 40, 9 / 40),
    (44 / 45, -56 / 15, 32 / 9),
    (19372 / 6561, -25360 / 2187, 64448 / 6561, -212 / 729),
    (9017 / 3168, -355 / 33, 46732 / 5247, 49 / 176, -5103 / 18656),
    (35 / 384, 0.0, 500 / 1113, 125 / 192, -2187 / 6784, 11 / 84),
)
ERROR = (71 / 57600, 0.0, -71 / 16695, 71 / 1920, -17253 / 339200, 22 / 525, -1 / 40)
DENSE = (
    (1.0, -183 / 64, 37 / 12, -145 / 128),
    (0.0, 0.0, 0.0, 0.0),
    (0.0, 1500 / 371, -1000 / 159, 1000 / 371),
    (0.0, -125 / 32, 125 / 12, -375 / 64),
    (0.0, 9477 / 3392, -729 / 106, 25515 / 6784),
    (0.0, -11 / 7, 11 / 3, -55 / 28),
    (0.0, 3 / 2, -4.0, 5 / 2),
)


class _Stepper:
    def __init__(self, neq: int, rhs: Any) -> None:
        self.neq = neq
        self.rhs = rhs
        self.k = [np.zeros(neq) for _ in range(7)]

    def _combine(self, y: np.ndarray, h: float, row: Tuple[float, ...]) -> np.ndarray:
        acc = np.zeros(self.neq)
        for j, c in enumerate(row):
            if c != 0:
                acc = acc + c * self.k[j]
        return y + h * acc

    def start(self, t: float, y: np.ndarray) -> int:
        self.k[0] = np.asarray(self.rhs(t, y), dtype=float)
        return 1

    def derivative_at_start(self) -> np.ndarray:
        return self.k[0]

    def attempt(self, t: float, y: np.ndarray, h: float, tnew: float, ynew: np.ndarray,
                err: np.ndarray) -> Tuple[int, float]:
        for s in range(5):
            self.k[s + 1] = np.asarray(self.rhs(t + h * NODES[s], self._combine(y, h, STAGE[s])), dtype=float)
        ynew[:] = self._combine(y, h, STAGE[5])
        self.k[6] = np.asarray(self.rhs(tnew, ynew), dtype=float)
        acc = np.zeros(self.neq)
        for j in range(7):
            if ERROR[j] != 0:
                acc = acc + ERROR[j] * self.k[j]
        err[:] = acc
        self.t_from, self.h_from, self.y_from = t, h, y.copy()
        return 6, 1.0

    def dense_at(self, tq: float) -> np.ndarray:
        s = (tq - self.t_from) / self.h_from
        s2 = s * s
        s3 = s2 * s
        s4 = s3 * s
        acc = np.zeros(self.neq)
        for j in range(7):
            c = DENSE[j]
            w = c[0] * s + c[1] * s2 + c[2] * s3 + c[3] * s4
            if w != 0:
                acc = acc + w * self.k[j]
        return self.y_from + self.h_from * acc

    def accept(self, tnew: float, ynew: np.ndarray, reprojected: bool) -> int:
        spent = 0
        if reprojected:
            self.k[6] = np.asarray(self.rhs(tnew, ynew), dtype=float)
            spent = 1
        self.k[0] = self.k[6].copy()
        return spent

    def restart(self, t: float, y: np.ndarray) -> int:
        return 0

    def stats(self) -> Dict[str, Any]:
        return {}


class _Method:
    id = 'dp45'
    order = 4
    default_max_steps = 1e7
    holds_at_zero = False
    snaps_to_constraint = False

    @staticmethod
    def step_budget_message(max_steps: float, t: float) -> str:
        return (f'Exceeded {int(max_steps)} steps at t={t}; the system may be stiff -- try a stiff solver '
                '(variableOrder or rosenbrock23).')

    @staticmethod
    def floor_message(t: float, hmin: float, worst: int) -> str:
        return (f'Unable to meet integration tolerances at t={t} without reducing the step below the smallest allowed '
                f'({hmin}). State {worst} is the worst offender; the system is probably stiff -- try a stiff solver '
                '(variableOrder or rosenbrock23).')

    @staticmethod
    def stall_message(t: float, window: int, covered: float) -> str:
        return (f'The solver stopped making progress at t={t}: {window} steps advanced the clock by less than '
                f'{covered}. Either the system is stiff -- try a stiff solver (variableOrder or rosenbrock23) -- or a '
                'discontinuous rate is holding a state against zero.')

    @staticmethod
    def set_up(neq: int, rhs: Any, f: Any, threshold: np.ndarray, atol: np.ndarray, rtol: float,
               opts: Dict[str, Any]) -> _Stepper:
        return _Stepper(neq, rhs)


def dormand_prince(f: Any, tspan: Any, y0: np.ndarray, opts: Dict[str, Any]) -> Dict[str, Any]:
    return integrate(_Method, f, tspan, y0, opts)
