"""The solvers a run can be given, by the id the model file stores.

Each takes ``(f, tspan, y0, opts)`` with ``f(t, y)`` the derivative and
returns ``{'t', 'y', 'stopped', 'stats'}``: a row per requested time reached,
and where an event stopped the run.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional

import numpy as np

from .solvers import SolverError

HINTS = {
    'singular': 'A compartment with no way in and no way out will do this.',
    'noPattern': 'Give the model an analytic Jacobian, or run fewer states.',
}


def non_finite_error(at: float) -> SolverError:
    return SolverError('nonfinite', f'The simulation produced a value that is not a number at t={at}. An equation '
                                    'divides by zero, takes the log of zero or a negative, or overflows; the state '
                                    'or rate that went first is where to look.', at)


def variable_order_failure(e: SolverError, t0: float) -> SolverError:
    """What ``variableOrder`` says when the NDF fails with ``e``."""
    if e.code in ('aborted', 'span'):
        return e
    at = e.t if e.t is not None else t0
    if e.code in ('stalled', 'steps'):
        return SolverError(e.code, f'{e} Something is holding a state where it cannot go: most often a compartment '
                                   'kept at zero by "cannot go negative" while its equations push it below. Turn '
                                   'that setting off on the compartment to see what the model really does.', at)
    if e.code == 'nonfinite':
        return non_finite_error(at)
    if e.code in ('singular', 'jacobian'):
        return SolverError(e.code, str(e), at)
    return SolverError(e.code, f'variableOrder failed: {e}. If the model is not stiff, dormandPrince may do better; '
                               'if it is very stiff, try tightening the tolerances.', at)


def variable_order(f: Callable[[float, np.ndarray], np.ndarray], tspan: Any, y0: np.ndarray,
                   opts: Dict[str, Any]) -> Dict[str, Any]:
    """The NDF (BDF with ``bdf``): ``variableOrder`` in the application."""
    from .solvers.ndf import ndf
    tspan = np.asarray(tspan, dtype=float)
    t0, t_final = float(tspan[0]), float(tspan[-1])
    if not (abs(t_final - t0) > 0):
        raise SolverError('span', 'Simulation start and end time are equal', t0)
    neq = y0.size
    abstol = opts.get('abstol', 1e-6)
    non_negative = [i for i, v in enumerate(opts.get('non_negative') or []) if v]
    span = abs(t_final - t0) or 1.0
    counter = {'n': 0, 'last': 0.0}
    on_step = opts.get('on_step')

    def fun(t: float, y: np.ndarray) -> np.ndarray:
        counter['n'] += 1
        dy = f(t, y)
        if on_step is not None and (counter['n'] & 63) == 0:
            progress = min(1.0, abs(t - t0) / span)
            if progress > counter['last']:
                counter['last'] = progress
                if on_step(progress, counter['n'], t) is False:
                    raise SolverError('aborted', 'Simulation aborted', t)
        return dy

    kw: Dict[str, Any] = dict(
        rtol=float(opts.get('rtol') or 1e-3), abstol=abstol, non_negative=non_negative,
        hmax=opts.get('hmax') or 0.0, h0=opts.get('h0') or 0.0, max_order=opts.get('max_order') or 5,
        jacobian=opts.get('jacobian'), bdf=bool(opts.get('bdf')), hints=HINTS,
        norm_control=bool(opts.get('norm_control')), auto_abstol=bool(opts.get('auto_abstol')),
        ends_only=bool(opts.get('ends_only')), events=opts.get('events'), on_accepted=opts.get('on_accepted'),
        on_output=opts.get('on_output'),
    )
    if opts.get('max_steps'):
        kw['max_steps'] = opts['max_steps']
    if (opts.get('stagnation_tol') or 0) > 0:
        kw['stagnation_tol'] = opts['stagnation_tol']
    if opts.get('error_norm'):
        kw['error_norm'] = opts['error_norm']
    if opts.get('matrix'):
        kw['matrix'] = opts['matrix']
    if opts.get('below_tol_run') is not None:
        kw['below_tol_run'] = opts['below_tol_run']
    try:
        result = ndf(fun, tspan, y0, **kw)
    except SolverError as e:
        failure = variable_order_failure(e, t0)
        if failure is e:
            raise
        raise failure from None
    if not len(result['t']) or not len(result['y']):
        raise SolverError('output', 'the variable-order solver produced no output', t0)
    s = result['stats']
    return {
        't': result['t'], 'y': result['y'],
        'stopped': ({'t': result['stopped']['t'], 'y': result['stopped']['y'],
                     'which': result['stopped'].get('which') or []} if result['stopped'] else None),
        'stats': {'nsteps': s['nsteps'], 'nfailed': s['nfailed'], 'nfevals': counter['n'], 'npds': s['npds'],
                  'ndecomps': s['ndecomps'], 'nsolves': s['nsolves'], 'nbelowtol': s['nbelowtol'],
                  'sparse': s.get('sparse', False), 'fill': s.get('fill'), 'negative': s.get('negative', 0),
                  'held': s.get('held'), 'points': len(result['t']), 'solver': 'bdf' if opts.get('bdf') else 'ndf'},
    }


def _lazy(module: str, name: str) -> Callable[..., Dict[str, Any]]:
    def call(f: Any, tspan: Any, y0: Any, opts: Dict[str, Any]) -> Dict[str, Any]:
        import importlib
        mod = importlib.import_module(f'kompartment.engine.solvers.{module}')
        return getattr(mod, name)(f, tspan, y0, opts)
    return call


SOLVERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    'ndf': variable_order,
    'ros23': _lazy('rosenbrock23', 'rosenbrock23'),
    'dp45': _lazy('dormand_prince', 'dormand_prince'),
    'scipy_bdf': _lazy('scipy_driver', 'scipy_bdf'),
    'scipy_radau': _lazy('scipy_driver', 'scipy_radau'),
    'scipy_lsoda': _lazy('scipy_driver', 'scipy_lsoda'),
    'fbdf': _lazy('julia', 'fbdf'),
    'qndf': _lazy('julia', 'qndf'),
    'rodas5p': _lazy('julia', 'rodas5p'),
    'radau5': _lazy('julia', 'radau5'),
    'kencarp4': _lazy('julia', 'kencarp4'),
    'trbdf2': _lazy('julia', 'trbdf2'),
}
