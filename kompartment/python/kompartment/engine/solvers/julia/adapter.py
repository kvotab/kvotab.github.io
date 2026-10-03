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

The switching solvers (``auto``, ``auto_julia``) report which of their
methods took the accepted steps and how often they changed between them
(``steps_by``, ``switches``), and the matrix-free FBDF its GMRES iterations
(``krylov_iters``) -- the application's ``stepsBy``, ``switches`` and
``krylovIters``, in this engine's spelling. A run is one solve between two
events; the runner hands every solve of a run one ``carry`` dict, in which
``auto_julia`` keeps whether it ended on its stiff method and goes on with
it, as DifferentialEquations.jl carries its choice across a callback, and
``auto`` whether it has handed the run to the NDF.

``auto`` is DifferentialEquations.jl's start and its test for stiffness, with
the engine's NDF (:func:`kompartment.engine.solverset.variable_order`) in
place of all four stiff methods: its explicit methods run at a tenth of the
model's tolerances (``EXPLICIT_TOLERANCE``) and land on the corners of the
tables read at the clock (the runner's ``table_corners``), and where the run
turns stiff, the NDF takes the rest of it from the last accepted point. A run
that has turned stiff, or whose tables turn more than ``MAX_CORNERS`` times,
is the NDF's from the start.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional

import numpy as np

from .. import SolverError
from ._js import jmin
from .integrator import (CONVERGENCE_FAILURE, DT_LESS_THAN_MIN, HANDED_OFF, MAX_ITERS, SUCCESS, TERMINATED, UNSTABLE,
                         ODEError, ODEProblem, solve)
from .methods import (FBDF, QBDF, QNDF, DefaultODEAlgorithm, KenCarp4, RadauIIA5, Rodas5P, Rosenbrock23, TRBDF2,
                      Tsit5, Vern7)

#: ``auto``'s explicit methods run at this fraction of the model's tolerances.
#: Their error test is on the end of each step; what lies between is read off
#: an interpolant that nothing tests, and at a loose tolerance a long step
#: across a change of slope the model does not declare -- an onset written as
#: an expression -- left values a factor of two out between its ends, with
#: both ends right (``EXPLICIT_TOLERANCE`` in the application's adapter).
EXPLICIT_TOLERANCE = 0.1

#: At most this many corners of the clock-read tables for ``auto``'s explicit
#: methods to land on in one solve. Landing costs a step each, and a model with
#: thousands (a yearly series) ran several times longer than on the NDF; such a
#: run is the NDF's from the start, and its error test deals with the corners.
MAX_CORNERS = 100

#: The stiff methods of the default algorithm, none of which ``auto`` switches
#: to: the NDF goes on instead.
HANDED_OFF_METHODS = ('Rosenbrock23', 'Rodas5P', 'FBDF', 'KrylovFBDF')

ALGORITHMS: Dict[str, Callable[..., Any]] = {
    'fbdf': FBDF,
    'qndf': QNDF,
    'rodas5p': Rodas5P,
    'radau5': RadauIIA5,
    'kencarp4': KenCarp4,
    'trbdf2': TRBDF2,
    # The default algorithm and the three methods it brought with it: as
    # DifferentialEquations.jl has it (`auto_julia`), and with the NDF as its
    # only stiff method (`auto`).
    'auto': DefaultODEAlgorithm,
    'auto_julia': DefaultODEAlgorithm,
    'rosenbrock23': Rosenbrock23,
    'tsit5': Tsit5,
    'vern7': Vern7,
    'fbdf_krylov': lambda: FBDF(linsolve='gmres'),
}

#: The switching solver's stiff methods, by the names its statistics give them.
STIFF_METHODS = frozenset(['Rosenbrock23', 'Rodas5P', 'FBDF', 'KrylovFBDF'])

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


def _scaled(tol: Any, k: float) -> Any:
    """A tolerance, one number or one per state, times k (``scaled``)."""
    if np.ndim(tol) == 0:
        return tol * k
    return np.asarray(tol, dtype=float) * k


def ndf_part(f: Callable[[float, np.ndarray], np.ndarray], grid: np.ndarray, t0: float, tf: float, t1: float,
             y1: np.ndarray, opts: Dict[str, Any], steps_before: int) -> Dict[str, Any]:
    """The NDF over the requested times from ``t1`` on, starting from ``y1``
    (``ndfPart``): the whole of a solve when t1 is its start, the rest of one
    when the explicit methods handed it on there. Its first row is t1 itself.
    Progress is reported as a fraction of the whole solve, and the step
    budget is what the first part left of it."""
    from ...solverset import variable_order
    direction = 1.0 if tf > t0 else (-1.0 if tf < t0 else 0.0)
    times = [t1]
    if opts.get('ends_only'):
        times.append(tf)
    else:
        times.extend(float(v) for v in grid if direction * (v - t1) > 0)
    sub = dict(opts)
    sub.pop('carry', None)
    sub.pop('table_corners', None)
    if t1 != t0:
        sub.pop('h0', None)
    if _positive(opts.get('max_steps')):
        sub['max_steps'] = max(1, opts['max_steps'] - steps_before)
    on_step = opts.get('on_step')
    if on_step is not None and t1 != t0:
        span = abs(tf - t0)
        sub['on_step'] = lambda _fraction, count, t: on_step(jmin(1.0, abs(t - t0) / span), count, t)
    return variable_order(f, np.array(times, dtype=float), np.asarray(y1, dtype=float), sub)


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

        # The switching solvers. `auto_julia` is DifferentialEquations.jl's
        # default as it is, and goes on with the method a run ended on when
        # it is restarted at an event, as that does across a callback. `auto`
        # is the same start and the same test for stiffness, with the NDF in
        # place of all four stiff methods: where the run turns stiff, the
        # explicit method stops and the NDF takes the rest of it. Its explicit
        # methods run at a tenth of the tolerances and land on the corners of
        # the clock-read tables; a run that has turned stiff, or whose tables
        # turn too often, is the NDF's from the start. (An empty carry is one
        # all the same: `is not None`, not truth.)
        carry = opts.get('carry') if solver_id in ('auto', 'auto_julia') else None
        if solver_id == 'auto':
            table_corners = opts.get('table_corners')
            corners = table_corners(t0, tf, MAX_CORNERS) if table_corners is not None else []
            if (carry is not None and carry.get('ndf')) or corners is None:
                if carry is not None:
                    carry['ndf'] = True
                r = ndf_part(f, grid, t0, tf, t0, np.array(y0, dtype=float), opts, 0)
                st = r['stats']
                return {
                    't': r['t'], 'y': r['y'], 'stopped': r['stopped'],
                    'stats': {**st, 'nsteps': st['nsteps'] + st['nfailed'], 'solver': 'auto',
                              'steps_by': {'BDF' if opts.get('bdf') else 'NDF': st['nsteps']}, 'switches': 0},
                }
            settings['reltol'] = settings['reltol'] * EXPLICIT_TOLERANCE
            settings['abstol'] = _scaled(settings['abstol'], EXPLICIT_TOLERANCE)
            if len(corners):
                settings['tstops'] = list(corners)
            alg = DefaultODEAlgorithm(hand_off=HANDED_OFF_METHODS)
        elif solver_id == 'auto_julia':
            alg = DefaultODEAlgorithm(stiffalgfirst=carry is not None and carry.get('stiff') is True)
        else:
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
        if carry is not None and solver_id == 'auto_julia' and sol.stats.get('lastAlg'):
            carry['stiff'] = sol.stats['lastAlg'] in STIFF_METHODS
        if carry is not None and sol.retcode == HANDED_OFF:
            carry['ndf'] = True

        last_t = sol.t[-1] if sol.t else t0
        if stopped_here[0]:
            raise SolverError('aborted', 'Simulation aborted', last_t)
        if sol.retcode not in (SUCCESS, TERMINATED, HANDED_OFF):
            raise SolverError(_RETCODES.get(sol.retcode, 'failed'), f'{sol.message or sol.retcode} ({run_id})', last_t)

        fired = sol.events[-1] if sol.events else None
        stopped = ({'t': fired['t'], 'y': np.array(fired['u'], dtype=float),
                    'which': list(fired.get('all') or [fired['which']])}
                   if fired is not None else None)
        s = sol.stats
        stats = {
            'nsteps': s.get('nsteps') or 0,
            'nfailed': s.get('nreject') or 0,
            'nfevals': s.get('nf') or 0,
            'npds': s.get('njacs') or 0,
            'ndecomps': s.get('nw') or 0,
            'nsolves': s.get('nsolve') or 0,
            'solver': run_id,
            'sparse': bool(s.get('sparse')),
            'fill': s.get('fill'),
        }
        # The switching solver says which of its methods took the accepted
        # steps and how often it changed between them, for the run log.
        if s.get('stepsBy') is not None:
            stats['steps_by'] = dict(s['stepsBy'])
            stats['switches'] = s['switches'] if s.get('switches') is not None else 0
        # GMRES's own work, where the method solved without a matrix.
        if s.get('krylovIters') is not None:
            stats['krylov_iters'] = s['krylovIters']

        # Where `auto` turned stiff: the NDF from that point, and one account
        # of both parts -- the steps each method took, and the one switch.
        if sol.retcode == HANDED_OFF:
            handed = sol.hand_off
            r = ndf_part(f, grid, t0, tf, handed['t'], handed['u'], opts, stats['nsteps'])
            b = r['stats']
            rows = [np.array(u, dtype=float) for u in sol.u]
            rows.extend(r['y'][1:])
            return {
                't': np.concatenate([np.array(sol.t, dtype=float), np.asarray(r['t'], dtype=float)[1:]]),
                'y': rows,
                'stopped': r['stopped'],
                'stats': {
                    **stats,
                    'nsteps': stats['nsteps'] + b['nsteps'] + b['nfailed'],
                    'nfailed': stats['nfailed'] + b['nfailed'],
                    'nfevals': stats['nfevals'] + b['nfevals'],
                    'npds': stats['npds'] + b['npds'],
                    'ndecomps': stats['ndecomps'] + b['ndecomps'],
                    'nsolves': stats['nsolves'] + b['nsolves'],
                    'nbelowtol': b['nbelowtol'],
                    'negative': b['negative'],
                    'held': b['held'],
                    'sparse': b['sparse'],
                    'fill': b['fill'],
                    'steps_by': {**stats['steps_by'], 'BDF' if opts.get('bdf') else 'NDF': b['nsteps']},
                    'switches': stats['switches'] + 1,
                },
            }
        return {
            't': np.array(sol.t, dtype=float),
            'y': [np.array(u, dtype=float) for u in sol.u],
            'stopped': stopped,
            'stats': stats,
        }

    solve_it.__name__ = solver_id
    solve_it.__qualname__ = solver_id
    return solve_it
