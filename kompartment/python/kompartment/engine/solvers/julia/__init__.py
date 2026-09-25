"""The six stiff solvers the application vendors from DifferentialEquations.jl.

A port of ``src/ode/julia/`` (FBDF, QNDF/QBDF, Rodas5P, RadauIIA5, KenCarp4,
TRBDF2, with the integrator loop, Jacobian cache, Newton iteration and step
controller they share) and of the adapter ``src/ode/julia-solvers.js`` that
wraps them in the engine's solver shape::

    from kompartment.engine.solvers.julia import fbdf
    result = fbdf(f, tspan, y0, {'rtol': 1e-6, 'abstol': 1e-9})

Each of ``fbdf, qndf, rodas5p, radau5, kencarp4, trbdf2`` takes
``(f, tspan, y0, opts)`` and returns ``{'t', 'y', 'stopped', 'stats'}``.

The per-state arithmetic follows the package's order of operations; the
factorisations are LAPACK's and SuperLU's (see :mod:`.linalg`), so a run
takes the application's steps and agrees with it to rounding.
"""

from __future__ import annotations

from .adapter import julia

fbdf = julia('fbdf')
qndf = julia('qndf')
rodas5p = julia('rodas5p')
radau5 = julia('radau5')
kencarp4 = julia('kencarp4')
trbdf2 = julia('trbdf2')

__all__ = ['fbdf', 'qndf', 'rodas5p', 'radau5', 'kencarp4', 'trbdf2', 'julia']
