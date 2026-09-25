"""The SciPy methods: ``scipy_bdf``, ``scipy_radau`` and ``scipy_lsoda``.

The application runs these in a Python it downloads into the browser
(``src/ode/scipy.js``); here they are ``scipy.integrate`` itself, driven the
same way: ``solve_ivp`` over the run, answering at the output times, with the
analytic Jacobian where the model has one (sparse for a large sparse model,
dense otherwise), a hook on every accepted step for the blocks that remember,
and the same account of a state that went below zero. Discrete events are
refused, as the application refuses them: its events are terminal and
located by its own rules.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np

from . import SolverError

SCIPY_METHODS = {'scipy_bdf': 'BDF', 'scipy_radau': 'Radau', 'scipy_lsoda': 'LSODA'}
TICK = 64


class _Cancelled(Exception):
    pass


def _solve(solver_id: str, f: Any, tspan: Any, y0: np.ndarray, opts: Dict[str, Any]) -> Dict[str, Any]:
    from scipy.integrate import BDF, LSODA, Radau, solve_ivp
    from scipy.sparse import csc_matrix
    methods = {'BDF': BDF, 'Radau': Radau, 'LSODA': LSODA}
    tspan = np.asarray(tspan, dtype=float)
    y0 = np.asarray(y0, dtype=float)
    neq = y0.size
    t0, tfinal = float(tspan[0]), float(tspan[-1])
    if not (abs(tfinal - t0) > 0):
        raise SolverError('span', 'Simulation start and end time are equal', t0)
    if opts.get('events') is not None:
        raise SolverError('events', f"{solver_id} does not support discrete events. This tool's events are terminal and "
                                    'are located by its own event locator, including the rule that a crossing at the '
                                    'instant a previous event fired is not a new one; reproducing that on top of SciPy '
                                    'would risk a subtly different model rather than an independent check of this one. '
                                    'Use ndf, ros23 or dp45 for a model with events.', t0)
    nn = opts.get('non_negative') or []
    nn_idx = np.array([i for i, v in enumerate(nn) if v], dtype=np.int64)
    span = abs(tfinal - t0) or 1.0
    counter = {'nfevals': 0, 'last': 0.0, 'nsteps': 0, 'nfailed': 0}
    on_step = opts.get('on_step')
    on_accepted = opts.get('on_accepted')

    def rhs(t: float, y: np.ndarray) -> np.ndarray:
        counter['nfevals'] += 1
        d = np.array(f(float(t), y), dtype=float)
        if nn_idx.size:
            sub = d[nn_idx]
            d[nn_idx] = np.where((y[nn_idx] < 0) & (sub < 0), 0.0, sub)
        if on_step is not None and counter['nfevals'] % TICK == 0:
            counter['last'] = max(counter['last'], min(1.0, abs(t - t0) / span))
            if on_step(counter['last'], counter['nfevals'], t) is False:
                raise _Cancelled()
        return d

    jac_info = opts.get('jacobian')
    jac = jac_info if jac_info and jac_info.get('available') and jac_info.get('evaluate') else None
    use_sparse = bool(jac) and neq >= 60 and jac['density'] < 0.25
    kwargs: Dict[str, Any] = {}
    if jac is not None:
        pattern = jac['pattern']
        evaluate = jac['evaluate']
        indptr = pattern.col_ptr.astype(np.int32)
        indices = pattern.row_idx.astype(np.int32)
        groups = jac.get('groups')
        ab = opts.get('abstol', 1e-6)
        threshold = (np.full(neq, float(ab)) if np.ndim(ab) == 0 else np.asarray(ab, dtype=float)) \
            / float(opts.get('rtol') or 1e-3)

        def values_at(t: float, y: np.ndarray) -> np.ndarray:
            """The generated Jacobian's values -- or, where it answers None (an
            entry that is not a number at this state), differences through
            its pattern, as every other solver takes them (``jacobianValues``
            in the application's bridge)."""
            values = evaluate(float(t), y)
            if values is not None:
                return np.asarray(values, dtype=float)
            from ..jacobian import colour_columns, difference_jacobian
            nonlocal groups
            if groups is None:
                groups = colour_columns(pattern)
            yy = np.array(y, dtype=float)
            f0 = np.asarray(f(float(t), yy), dtype=float)
            counter['nfevals'] += 1 + len(groups)
            return difference_jacobian(lambda tt, v: np.asarray(f(tt, v), dtype=float), float(t), yy, f0, pattern,
                                       groups, threshold)

        if use_sparse:
            def jacobian(t: float, y: np.ndarray) -> Any:
                return csc_matrix((values_at(t, y).copy(), indices, indptr), shape=(neq, neq))
        else:
            rows, cols = pattern.row_idx, pattern.col_of

            def jacobian(t: float, y: np.ndarray) -> Any:
                J = np.zeros((neq, neq))
                J[rows, cols] = values_at(t, y)
                return J
        kwargs['jac'] = jacobian
    if (opts.get('hmax') or 0) > 0:
        kwargs['max_step'] = float(opts['hmax'])
    if (opts.get('h0') or 0) > 0:
        kwargs['first_step'] = float(opts['h0'])
    base = methods[SCIPY_METHODS[solver_id]]

    class Hooked(base):  # type: ignore[misc, valid-type]
        def _step_impl(self) -> Any:
            ok, message = super()._step_impl()
            if ok:
                counter['nsteps'] += 1
                if on_accepted is not None:
                    on_accepted(float(self.t), np.array(self.y, dtype=float))
            else:
                counter['nfailed'] += 1
            return ok, message

    ab = opts.get('abstol', 1e-6)
    atol = np.asarray(ab, dtype=float) if np.ndim(ab) else float(ab if ab is not None else 1e-6)
    try:
        with np.errstate(all='ignore'):
            sol = solve_ivp(rhs, (t0, tfinal), y0, method=Hooked, t_eval=tspan, rtol=float(opts.get('rtol') or 1e-3),
                            atol=atol, **kwargs)
    except _Cancelled:
        raise SolverError('aborted', 'Simulation aborted', t0) from None
    except Exception as e:  # noqa: BLE001 - reported with the solver's name
        raise SolverError('failed', f'{solver_id} failed: {type(e).__name__}: {e}. A derivative that returns NaN or '
                                    'infinity stops SciPy in the linear algebra rather than in the step controller, so '
                                    'this usually means an equation divided by zero rather than that the tolerances were '
                                    'too tight.', t0) from None
    if not sol.success:
        raise SolverError('failed', f'{solver_id} did not reach the end of the simulation: {sol.message} This model may '
                                    'be stiffer than the tolerances allow; try loosening them, or ndf.', t0)
    t = np.asarray(sol.t, dtype=float)
    y = [np.array(row, dtype=float) for row in np.asarray(sol.y).T]
    if not t.size:
        raise SolverError('output', f'{solver_id} produced no output', t0)
    negative = 0
    if nn_idx.size:
        floor = -np.abs(np.broadcast_to(np.asarray(ab if ab is not None else 1e-6, dtype=float), (neq,)))
        Y = np.array(y)
        negative = int(np.sum(Y[:, nn_idx] < floor[nn_idx]))
    return {
        't': t, 'y': y, 'stopped': None,
        'stats': {'nsteps': counter['nsteps'], 'nfailed': counter['nfailed'], 'nfevals': counter['nfevals'],
                  'npds': int(sol.njev), 'ndecomps': int(sol.nlu), 'nsolves': None, 'sparse': use_sparse, 'fill': None,
                  'negative': negative, 'points': int(t.size), 'solver': solver_id},
    }


def scipy_bdf(f: Any, tspan: Any, y0: np.ndarray, opts: Dict[str, Any]) -> Dict[str, Any]:
    return _solve('scipy_bdf', f, tspan, y0, opts)


def scipy_radau(f: Any, tspan: Any, y0: np.ndarray, opts: Dict[str, Any]) -> Dict[str, Any]:
    return _solve('scipy_radau', f, tspan, y0, opts)


def scipy_lsoda(f: Any, tspan: Any, y0: np.ndarray, opts: Dict[str, Any]) -> Dict[str, Any]:
    return _solve('scipy_lsoda', f, tspan, y0, opts)
