"""The DifferentialEquations.jl methods in this engine's solver shape
(``src/ode/julia-solvers.js``).

``julia(id)`` wraps one of the ported methods so that it takes what every
solver here is handed -- ``(f, tspan, y0, opts)`` -- and gives back what one
returns: ``{'t', 'y', 'stopped', 'stats'}``. It maps the run's options onto
the package's, hands over the analytic Jacobian as a callback that may
decline a point, asks for a row at every requested time (``saveat``), hands
the blocks that remember every accepted step (``on_accepted``) and every
requested time (``on_output``), makes every event terminal, with a direction
per event function, and turns a retcode other than Success, or an event's
Terminated, into a :class:`SolverError`.

Where the model's analytic Jacobian is declined (``available: False``), the
engine's runner hands over the structural pattern, as the application's does,
and the matrix is differenced through it and factorised sparsely: a large
model runs rather than asking for n^2 numbers.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional

import numpy as np

from .. import SolverError
from ._js import jmin
from .integrator import (CONVERGENCE_FAILURE, DT_LESS_THAN_MIN, MAX_ITERS, SUCCESS, TERMINATED, UNSTABLE, ODEError,
                         ODEProblem, solve)
from .methods import FBDF, QBDF, QNDF, KenCarp4, RadauIIA5, Rodas5P, TRBDF2

ALGORITHMS: Dict[str, Callable[..., Any]] = {
    'fbdf': FBDF,
    'qndf': QNDF,
    'rodas5p': Rodas5P,
    'radau5': RadauIIA5,
    'kencarp4': KenCarp4,
    'trbdf2': TRBDF2,
}

# What `simulation.bdf` runs instead, by the id the run then reports.
AS_BDF: Dict[str, Any] = {
    'qndf': ('qbdf', QBDF),
}

_ODE_CODES = {'nonfinite': 'nonfinite', 'empty': 'span', 'tspan': 'span', 'dt': 'span'}
_RETCODES = {MAX_ITERS: 'steps', DT_LESS_THAN_MIN: 'tolerance', UNSTABLE: 'nonfinite',
             CONVERGENCE_FAILURE: 'tolerance'}


def _jacobian_for(jacobian: Optional[Dict[str, Any]]) -> Optional[Callable[..., bool]]:
    """The run's Jacobian as a callback filling the package's matrix; it
    answers False where ``evaluate`` declines (``jacobianFor``)."""
    if not jacobian:
        return None
    pattern = jacobian['pattern']
    evaluate = jacobian.get('evaluate')
    rows = np.asarray(pattern.row_idx, dtype=np.int64)
    cols = np.repeat(np.arange(pattern.n, dtype=np.int64), np.diff(np.asarray(pattern.col_ptr, dtype=np.int64)))

    def jac(t: float, u: np.ndarray, cache: Any) -> bool:
        values = evaluate(t, u) if evaluate is not None else None
        if values is None:
            return False
        values = np.asarray(values, dtype=float)
        if cache.sparse:
            cache.values[:] = values
            return True
        cache.J.fill(0.0)
        cache.J[rows, cols] = values
        return True

    return jac


def _order(v: Any) -> Any:
    """An order as a list index: 3.0 is 3, as JavaScript indexes an array."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _positive(v: Any) -> bool:
    """``v > 0`` as JavaScript reads it for an option that may be absent."""
    try:
        return v is not None and not isinstance(v, bool) and float(v) > 0
    except (TypeError, ValueError):
        return False


def julia(solver_id: str) -> Callable[..., Dict[str, Any]]:
    algorithm = ALGORITHMS.get(solver_id)
    if algorithm is None:
        raise SolverError('failed', f"'{solver_id}' is not one of the ported methods", 0.0)

    def solve_it(f: Callable[[float, np.ndarray], np.ndarray], tspan: Any, y0: Any,
                 opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        opts = opts or {}
        variant = AS_BDF.get(solver_id) if opts.get('bdf') else None
        run_id = variant[0] if variant else solver_id
        grid = np.array(tspan, dtype=float)
        t0 = float(grid[0])
        tf = float(grid[-1])
        if not (tf != t0):
            raise SolverError('span', 'Simulation start and end time are equal', t0)

        saveat = [t0, tf] if opts.get('ends_only') else [float(v) for v in grid]

        events = None
        ev = opts.get('events')
        if ev is not None:
            direction = getattr(ev, 'direction', None)
            events = SimpleNamespace(
                n=ev.n,
                fun=lambda t, u: ev.fun(t, u),
                direction=[] if direction is None else list(np.asarray(direction).tolist()),
                terminal=True,
            )

        jacobian = opts.get('jacobian')
        if jacobian is not None and jacobian.get('available') is False:
            # Declined values: differenced through the pattern, as when a
            # numeric Jacobian is asked for.
            jacobian = ({'pattern': jacobian['pattern'], 'groups': jacobian.get('groups'), 'constant': False,
                         'evaluate': None} if jacobian.get('pattern') is not None else None)
        pattern = jacobian['pattern'] if jacobian else None
        problem = ODEProblem(f, np.asarray(y0, dtype=float), (t0, tf), jac=_jacobian_for(jacobian),
                             jac_pattern=(pattern.col_ptr, pattern.row_idx) if pattern is not None else None,
                             events=events)

        abstol = opts.get('abstol')
        if abstol is None:
            abstol = 1e-6
        elif np.ndim(abstol) > 0:
            abstol = np.asarray(abstol, dtype=float)
        settings: Dict[str, Any] = {
            'reltol': opts['rtol'] if opts.get('rtol') is not None else 1e-3,
            'abstol': abstol,
            'saveat': saveat,
            'save_everystep': False,
            'auto_abstol': bool(opts.get('auto_abstol')),
        }
        nn = opts.get('non_negative')
        if nn is not None and any(bool(v) for v in nn):
            settings['non_negative'] = list(nn)
        if _positive(opts.get('hmax')):
            settings['dtmax'] = float(opts['hmax'])
        if _positive(opts.get('h0')):
            settings['dt'] = float(opts['h0'])
        if _positive(opts.get('max_steps')):
            settings['maxiters'] = opts['max_steps']
        if _positive(opts.get('max_order')):
            settings['max_order'] = _order(opts['max_order'])
        if _positive(opts.get('min_order')):
            settings['min_order'] = _order(opts['min_order'])
        if opts.get('error_norm'):
            settings['norm'] = opts['error_norm']
        if _positive(opts.get('newton_kappa')):
            settings['kappa'] = float(opts['newton_kappa'])
        if _positive(opts.get('max_jac_age')):
            settings['max_jac_age'] = opts['max_jac_age']
        if _positive(opts.get('below_tol_run')):
            settings['below_tol_run'] = opts['below_tol_run']
        if opts.get('matrix'):
            settings['matrix'] = opts['matrix']
        if opts.get('on_accepted') is not None:
            settings['on_accepted'] = opts['on_accepted']
        if opts.get('on_output') is not None:
            settings['on_output'] = opts['on_output']

        stopped_here = [False]
        on_step = opts.get('on_step')
        if on_step is not None:
            span = abs(tf - t0)

            def progress(t: float, nsteps: int) -> bool:
                go = on_step(jmin(1.0, abs(t - t0) / span), nsteps, t) is not False
                if not go:
                    stopped_here[0] = True
                return go

            settings['progress'] = progress
            settings['progress_every'] = 1

        alg = (variant[1] if variant else algorithm)()
        try:
            with np.errstate(all='ignore'):
                sol = solve(problem, alg, settings)
        except ODEError as e:
            raise SolverError(_ODE_CODES.get(e.code, 'failed'), str(e), e.t if e.t is not None else t0) from None
        except Exception as e:  # noqa: BLE001 - the application re-throws whatever the package threw
            at = getattr(e, 't', None)
            code = getattr(e, 'code', None) if isinstance(e, SolverError) else None
            raise SolverError(code or 'failed', str(e), at if at is not None else t0) from None

        last_t = sol.t[-1] if sol.t else t0
        if stopped_here[0]:
            raise SolverError('aborted', 'Simulation aborted', last_t)
        if sol.retcode != SUCCESS and sol.retcode != TERMINATED:
            raise SolverError(_RETCODES.get(sol.retcode, 'failed'), f'{sol.message or sol.retcode} ({run_id})', last_t)

        fired = sol.events[-1] if sol.events else None
        stopped = ({'t': fired['t'], 'y': np.array(fired['u'], dtype=float),
                    'which': list(fired.get('all') or [fired['which']])}
                   if fired is not None else None)
        s = sol.stats
        return {
            't': np.array(sol.t, dtype=float),
            'y': [np.array(u, dtype=float) for u in sol.u],
            'stopped': stopped,
            'stats': {
                'nsteps': s.get('nsteps') or 0,
                'nfailed': s.get('nreject') or 0,
                'nfevals': s.get('nf') or 0,
                'npds': s.get('njacs') or 0,
                'ndecomps': s.get('nw') or 0,
                'nsolves': s.get('nsolve') or 0,
                'solver': run_id,
                'sparse': bool(s.get('sparse')),
                'fill': s.get('fill'),
            },
        }

    solve_it.__name__ = solver_id
    solve_it.__qualname__ = solver_id
    return solve_it
