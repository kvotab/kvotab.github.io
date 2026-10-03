"""The solvers the application vendors from DifferentialEquations.jl.

A port of ``src/ode/julia/`` -- the stiff methods FBDF (factorising, or
matrix-free by GMRES), QNDF/QBDF, Rodas5P, Rosenbrock23, RadauIIA5, KenCarp4
and TRBDF2, the explicit Tsit5 and Vern7, and the default algorithm that
switches between them as a run turns stiff and back, with the integrator
loop, Jacobian cache, Newton iteration and step controller they share -- and
of the adapter ``src/ode/julia-solvers.js`` that wraps them in the engine's
solver shape, with the default algorithm as it is (``auto_julia``) and with
the engine's NDF as its only stiff method (``auto``)::

    from kompartment.engine.solvers.julia import fbdf
    result = fbdf(f, tspan, y0, {'rtol': 1e-6, 'abstol': 1e-9})

Each of ``fbdf, qndf, rodas5p, radau5, kencarp4, trbdf2, auto, auto_julia,
fbdf_krylov, rosenbrock23, tsit5, vern7`` takes ``(f, tspan, y0, opts)`` and
returns ``{'t', 'y', 'stopped', 'stats'}``.

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
auto = julia('auto')
auto_julia = julia('auto_julia')
fbdf_krylov = julia('fbdf_krylov')
rosenbrock23 = julia('rosenbrock23')
tsit5 = julia('tsit5')
vern7 = julia('vern7')

__all__ = ['fbdf', 'qndf', 'rodas5p', 'radau5', 'kencarp4', 'trbdf2', 'auto', 'auto_julia', 'fbdf_krylov',
           'rosenbrock23', 'tsit5', 'vern7', 'julia']
