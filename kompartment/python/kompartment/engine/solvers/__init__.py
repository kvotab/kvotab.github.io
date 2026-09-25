"""The integrators, and how they fail.

Ports of the application's own solvers (``src/ode``): the variable-order NDF
that is the default, the Rosenbrock 2-3 and the Dormand-Prince 4-5; and the
SciPy methods, which the application runs in a downloaded Python and which
here are simply ``scipy.integrate``.
"""

from __future__ import annotations

from typing import Any, Optional


class SolverError(RuntimeError):
    """A run the solver could not finish. ``code`` says how, ``t`` where.

    Codes: 'span', 'tolerance', 'nonfinite', 'singular', 'stalled', 'steps',
    'jacobian', 'aborted'.
    """

    def __init__(self, code: str, message: str, t: Optional[float] = None) -> None:
        super().__init__(message)
        self.code = code
        self.t = t
        self.hint: Optional[str] = None
        self.trace: Any = None
        self.last_t: Optional[float] = None
        self.last_y: Any = None
        self.stats: Any = None


__all__ = ['SolverError']
