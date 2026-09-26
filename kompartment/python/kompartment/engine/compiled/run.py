"""A run's solve on the compiled path.

:func:`prepare` says whether a run can take it -- a model whose derivative
compiles (:mod:`.model`) and a solver with a compiled loop (the NDF,
Rosenbrock (2,3), Dormand-Prince) -- and hands back a :class:`CompiledRun`,
which the runner calls in place of the solver: with a span and a start,
answering as the solver's Python version does (:mod:`..solverset`), failures
and their messages included.

Three things stay in Python, and the compiled loop calls them back: an
analytic Jacobian, with the min/max histories handed over first (they live
in the compiled arrays during a run); the progress report; and, where the
Python solver would factorise with SuperLU or LAPACK rather than the
application's dense LU, the iteration matrix itself, formed and solved with
by the Python solver's own :class:`~kompartment.engine.solvers.matrix.IterationMatrix`.
"""

from __future__ import annotations

import ctypes
import math
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import numpy as np
from numba import types

from ..jacobian import colour_columns, difference_jacobian
from ..solvers import SolverError
from ..solvers.matrix import APP_LU_MAX, DENSE_BELOW, IterationMatrix, non_finite_message, singular_message
from . import solvers as cs
from . import NotCompiled
from .model import CompiledModel, compile_model

#: The solvers with a compiled loop.
COMPILED_SOLVERS = ('ndf', 'ros23', 'dp45')
SINGULAR_HINT = 'A compartment with no way in and no way out will do this.'
#: The most the collected steps (when they are output) may take.
STEPS_MAX_BYTES = 256 * 1024 ** 2


class HistoryFull(Exception):
    """A min/max history ran out of room: the run is made again with more."""


class UsePython(NotCompiled):
    """This run is found, once under way, to be one for the Python path."""


class Callback(types.WrapperAddressProtocol):
    """A Python function as the ``int64(float64, float64)`` the compiled loop
    calls. An exception it raises is kept in ``error``, and the call answers
    -1, which ends the solve."""

    _PROTO = ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.c_double, ctypes.c_double)

    def __init__(self, fn: Callable[[float, float], int]) -> None:
        self.error: Optional[BaseException] = None

        def call(a: float, b: float) -> int:
            try:
                return int(fn(a, b))
            except BaseException as e:  # noqa: BLE001 - handed back to the caller of the solve
                self.error = e
                return -1

        self._c = self._PROTO(call)

    def __wrapper_address__(self) -> int:
        return ctypes.cast(self._c, ctypes.c_void_p).value

    def signature(self) -> Any:
        return cs.CB_SIG


def compiled_model(system: Any) -> CompiledModel:
    """The system's compiled derivative, compiled once per system; the
    reason it cannot be, as :class:`NotCompiled`, every time it is asked."""
    cached = getattr(system, '_compiled_model', None)
    if isinstance(cached, CompiledModel):
        return cached
    if isinstance(cached, str):
        raise NotCompiled(cached)
    try:
        cm = compile_model(system)
    except NotCompiled as e:
        system._compiled_model = str(e)
        raise
    system._compiled_model = cm
    return cm


def prepare(system: Any, solver_id: str, opts: Dict[str, Any], *, min_change: float = 0.0,
            solver_points: bool = False, equations: bool = False) -> 'CompiledRun':
    """A compiled stand-in for the solver of this run, or :class:`NotCompiled`
    saying why the run keeps to the Python path."""
    if equations:
        raise NotCompiled('the run integrates a system of equations of its own')
    if solver_id not in COMPILED_SOLVERS:
        raise NotCompiled(f"the solver '{solver_id}' has no compiled loop")
    if min_change > 0:
        raise NotCompiled('the clock-only slots are worked out every min_change_time and interpolated')
    semi = [F for F in getattr(system, 'laplace', None) or []]
    if semi:
        raise NotCompiled(f"'{semi[0].block_name}' is worked out semi-analytically: its release is the inflow's "
                          'recorded history convolved with the path\'s responses, which the compiled loop does not '
                          'keep')
    n = system.nstate
    if solver_points and 2 * cs.MAX_SOLVER_POINTS * n * 8 > STEPS_MAX_BYTES:
        raise NotCompiled(f"the solver's own steps are asked for as output, and {n} states would need more room "
                          'for them than the compiled path sets aside')
    return CompiledRun(system, compiled_model(system), solver_id, opts, solver_points)


class CompiledRun:
    """The solver of one run, compiled: ``run(tspan, y0)`` for each span, with
    :meth:`start` before the first (after the recorders are primed) and
    :meth:`finish` after the last, whatever happened."""

    def __init__(self, system: Any, cm: CompiledModel, solver_id: str, opts: Dict[str, Any],
                 solver_points: bool = False) -> None:
        self.system = system
        self.cm = cm
        self.solver_id = solver_id
        self.opts = opts
        jac = opts.get('jacobian')
        self.pattern = jac.get('pattern') if jac else None
        self.evaluate = jac.get('evaluate') if jac else None
        self.constant = bool(jac.get('constant')) if jac else False
        groups = jac.get('groups') if jac else None
        if self.pattern is not None and groups is None:
            groups = colour_columns(self.pattern)
        self.groups = groups
        n = system.nstate
        none = np.zeros(0, dtype=np.int64)
        if self.pattern is None:
            self.jac_mode = cs.JAC_DENSE
            self.colptr = self.rowidx = self.gptr = self.gcols = none
            self.jvals = np.zeros(0)
        else:
            self.colptr = np.ascontiguousarray(self.pattern.col_ptr, dtype=np.int64)
            self.rowidx = np.ascontiguousarray(self.pattern.row_idx, dtype=np.int64)
            sizes = [len(g) for g in groups]
            self.gptr = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int64) if sizes else np.zeros(1, np.int64)
            self.gcols = np.ascontiguousarray(np.concatenate(groups) if sizes else none, dtype=np.int64)
            self.jvals = np.zeros(self.pattern.nnz)
            self.jac_mode = cs.JAC_CALLBACK if self.evaluate is not None else cs.JAC_PATTERN
        self.ybuf = np.zeros(n)
        self._jac_cb = Callback(self._jacobian) if self.jac_mode == cs.JAC_CALLBACK else None
        # What the matrix callbacks read and write: the Jacobian without a
        # pattern, the rows held in the matrix, a solve's right-hand side and answer.
        implicit = solver_id != 'dp45'
        self.jdense = np.zeros((n, n) if implicit and self.jac_mode == cs.JAC_DENSE else (1, 1))
        self.held_in_w = np.zeros(n, dtype=np.int64)
        self.rbuf = np.zeros(n)
        self.xbuf = np.zeros(n)
        self.matrix_error = ''
        # The accepted steps, when they are output: kept across the spans.
        rows = 2 * cs.MAX_SOLVER_POINTS if solver_points else 1
        self.ct = np.zeros(rows)
        self.cy = np.zeros((rows, n if solver_points else 1))
        self.cint = np.array([0, 0, 1, 1 if solver_points else 0], dtype=np.int64)
        self.cflt = np.array([-math.inf])

    # --- the run around the spans -----------------------------------------------------------------

    def start(self) -> None:
        self.cm.load()
        self.cint[:3] = (0, 0, 1)
        self.cflt[0] = -math.inf

    def steps_into(self, steps: Dict[str, Any]) -> None:
        """The collected steps into the runner's record of them."""
        n = int(self.cint[0])
        steps['t'] = self.ct[:n].tolist()
        steps['y'] = list(self.cy[:n].copy())
        steps['seen'] = int(self.cint[1])
        steps['stride'] = int(self.cint[2])
        steps['last'] = float(self.cflt[0])

    def finish(self) -> None:
        self.cm.write_back()

    def grow(self) -> None:
        self.cm.grow()

    def _hand_over(self) -> None:
        """Before Python works anything out of the model mid-run: the
        histories as they stand, and a clock that is not cached."""
        if self.cm.has_store:
            self.cm.sync_histories()
        self.system._clock_at = math.nan

    def _jacobian(self, t: float, _unused: float) -> int:
        self._hand_over()
        got = self.evaluate(t, self.ybuf)  # type: ignore[misc]
        if got is None:
            return 0
        self.jvals[:] = got
        return 1

    def _matrix(self, t0: float, y0: np.ndarray, threshold: np.ndarray, mode: str, kind: str,
                held: np.ndarray) -> Tuple[int, Optional[IterationMatrix], Any, Any]:
        """Where this span's matrix is factorised, as the Python solver would
        decide it: ``(where, its IterationMatrix, form, solve)``, the last two
        the callbacks when it is the Python matrix."""
        from ..solvers import kernels
        from ..solverset import HINTS
        n = self.system.nstate
        if n <= APP_LU_MAX and kernels.available() and (self.pattern is None or mode == 'dense'
                                                        or (mode == 'auto' and n < DENSE_BELOW)):
            # The application's dense LU without a trial: nothing to ask the Python matrix.
            return cs.MAT_KERNEL, None, cs.no_callback, cs.no_callback
        hints = HINTS if kind == 'ndf' else {'singular': SINGULAR_HINT}
        # The first Jacobian only decides between sparse and dense, by trial
        # factorisations, which the Python solver makes only here.
        trial = self.pattern is not None and mode != 'dense' and not (mode == 'auto' and n < DENSE_BELOW)
        values = self._first_jacobian(t0, y0, threshold, kind, held) if trial else \
            (self.jvals if self.pattern is not None else self.jdense)
        try:
            W = IterationMatrix(n, self.pattern, values, mode, None, hints)
        except RuntimeError as e:
            raise UsePython(str(e)) from None
        if W._kernels and not W.sparse:
            return cs.MAT_KERNEL, W, cs.no_callback, cs.no_callback
        return cs.MAT_PYTHON, W, Callback(lambda a, any_held: self._form(W, a, any_held)), \
            Callback(lambda _a, _b: self._solve(W))

    def _form(self, W: IterationMatrix, a: float, any_held: float) -> int:
        J = self.jvals if self.pattern is not None else self.jdense
        try:
            W.form(a, J, (self.held_in_w != 0) if any_held else None)
        except RuntimeError as e:
            self.matrix_error = str(e)
            return 1
        return 0

    def _solve(self, W: IterationMatrix) -> int:
        self.xbuf[:] = W.solve(self.rbuf)
        return 0

    def _first_jacobian(self, t0: float, y0: np.ndarray, threshold: np.ndarray, kind: str,
                        held: np.ndarray) -> np.ndarray:
        """The Jacobian the Python solver starts a span with."""
        self._hand_over()
        if self.evaluate is not None:
            got = self.evaluate(t0, y0)
            if got is not None:
                return np.asarray(got, dtype=float)
        rhs = self.system.rhs
        n = self.system.nstate
        if kind == 'ndf':
            from ..solvers.ndf import _Projected
            fy = np.asarray((_Projected(rhs, held, n) if held.size else rhs)(t0, y0), dtype=float)
            f = rhs
        else:
            from ..solvers.onestep import HeldDerivative
            mask = np.zeros(n, dtype=bool)
            mask[held] = True
            f = HeldDerivative(rhs, mask) if held.size else rhs
            fy = np.asarray(f(t0, y0), dtype=float)
        J0 = difference_jacobian(f, t0, y0, fy, self.pattern, self.groups, threshold)
        self.system._clock_at = math.nan
        return J0

    def _progress(self, filtered: bool) -> Any:
        on_step = self.opts.get('on_step')
        if on_step is None:
            return cs.no_callback
        last = [0.0]

        def report(fraction: float, at: float) -> int:
            if filtered:
                if not (fraction > last[0]):
                    return 1
                last[0] = fraction
            return 0 if on_step(fraction, 0, at) is False else 1

        return Callback(report)

    def _callback_error(self, *others: Any) -> BaseException:
        for cb in (self._jac_cb, *others):
            if isinstance(cb, Callback) and cb.error is not None:
                return cb.error
        return RuntimeError('a callback of the compiled solver failed')

    def __call__(self, tspan: Any, y0: np.ndarray) -> Dict[str, Any]:
        if self.solver_id == 'ndf':
            return self._ndf(tspan, y0)
        return self._onestep(tspan, y0)

    # --- the NDF (``solverset.variable_order``) ----------------------------------------------------

    def _ndf(self, tspan: Any, y0: np.ndarray) -> Dict[str, Any]:
        from ..solverset import variable_order_failure
        opts, system, cm = self.opts, self.system, self.cm
        tspan = np.ascontiguousarray(tspan, dtype=float)
        y0 = np.ascontiguousarray(y0, dtype=float)
        t0, t_final = float(tspan[0]), float(tspan[-1])
        if not (abs(t_final - t0) > 0):
            raise SolverError('span', 'Simulation start and end time are equal', t0)
        n = y0.size
        rtol = float(opts.get('rtol') or 1e-3)
        abstol = opts.get('abstol', 1e-6)
        auto = bool(opts.get('auto_abstol'))
        into = None
        if auto and isinstance(abstol, np.ndarray) and abstol.size == n and abstol.dtype == float:
            # Raised in place, and so carried into the next span, as the Python solver does.
            atol = abstol
            if not atol.flags.c_contiguous:
                into, atol = abstol, np.ascontiguousarray(abstol)
        elif np.ndim(abstol) == 0:
            atol = np.full(n, float(abstol))
        else:
            atol = np.array(abstol, dtype=float)
        constrained = np.array([i for i, v in enumerate(opts.get('non_negative') or []) if v], dtype=np.int64)
        where, W, form_cb, solve_cb = self._matrix(t0, y0, atol / rtol, opts.get('matrix') or 'auto', 'ndf',
                                                   constrained)
        max_order = max(1, min(cs.MAX_ORDER, int(math.floor((opts.get('max_order') or 5) + 0.5))))
        below = opts.get('below_tol_run')
        max_steps = opts['max_steps'] if opts.get('max_steps') else 1e6
        stagnation = opts['stagnation_tol'] if (opts.get('stagnation_tol') or 0) > 0 else 0.0
        fpar = np.array([rtol, float(opts.get('hmax') or 0.0), float(opts.get('h0') or 0.0), float(max_steps),
                         float(stagnation)])
        progress = self._progress(True)
        ipar = np.array([max_order, bool(opts.get('bdf')), bool(opts.get('norm_control')),
                         (opts.get('error_norm') or 'max') == 'rms', auto,
                         -1 if below is None else max(0, int(round(below))), 1, 2000, self.constant,
                         cm.has_store, progress is not cs.no_callback, where], dtype=np.int64)
        yout = np.empty((tspan.size, n))
        held = np.zeros(n, dtype=np.int64)
        stats = np.zeros(9, dtype=np.int64)
        fstat = np.zeros(4)
        cm.W[0] = math.nan
        status = cs.ndf(cm.rhs, cm.store, self._jac_cb or cs.no_callback, progress, system.P, system.X, cm.W, cm.IW,
                        tspan, y0, atol, constrained, self.jac_mode, self.colptr, self.rowidx, self.jvals,
                        self.gptr, self.gcols, self.ybuf, fpar, ipar, yout, held, stats, fstat,
                        self.ct, self.cy, self.cint, self.cflt, form_cb, solve_cb, self.jdense, self.held_in_w,
                        self.rbuf, self.xbuf)
        if into is not None:
            into[:] = atol
        if status != cs.OK:
            if status == cs.E_HISTORY:
                raise HistoryFull()
            if status == cs.E_CALLBACK:
                err = self._callback_error(progress, form_cb, solve_cb)
                if isinstance(err, SolverError):
                    raise variable_order_failure(err, t0) from None
                raise err
            raise variable_order_failure(self._ndf_error(status, fstat, max_steps, self.matrix_error), t0)
        rows = int(stats[8])
        return {
            't': tspan[:rows].copy(), 'y': list(yout[:rows]), 'stopped': None,
            'stats': {'nsteps': int(stats[0]), 'nfailed': int(stats[1]), 'nfevals': int(stats[7]),
                      'npds': int(stats[2]), 'ndecomps': int(stats[3]), 'nsolves': int(stats[4]),
                      'nbelowtol': int(stats[5]), 'sparse': bool(W is not None and W.info['sparse']),
                      'fill': W.info['fill'] if W is not None else None,
                      'negative': int(stats[6]),
                      'held': held if constrained.size else None, 'points': rows,
                      'solver': 'bdf' if opts.get('bdf') else 'ndf'},
        }

    @staticmethod
    def _ndf_error(status: int, fstat: np.ndarray, max_steps: float, matrix_error: str) -> SolverError:
        from ..solvers.ndf import error_nonfinite, floor_failure, initial_nonfinite, stall_failure, steps_failure
        t = float(fstat[0])
        if status == cs.E_ABORTED:
            return SolverError('aborted', 'Simulation aborted', t)
        if status == cs.E_INITIAL:
            return initial_nonfinite(t, int(fstat[1]))
        if status == cs.E_SINGULAR:
            return SolverError('singular', f'{_singular_text(fstat)} (at t={t})', t)
        if status == cs.E_MATRIX:
            return SolverError('singular', f'{matrix_error} (at t={t})', t)
        if status == cs.E_FLOOR:
            return floor_failure(t, False)
        if status == cs.E_FLOOR_NONFINITE:
            return floor_failure(t, True)
        if status == cs.E_ERR_NONFINITE:
            return error_nonfinite(t)
        if status == cs.E_STEPS:
            return steps_failure(max_steps, t)
        if status == cs.E_STALLED:
            return stall_failure(t, int(fstat[1]), float(fstat[2]))
        return SolverError('compiled', f'The compiled solver ended with status {status} at t={t}.', t)

    # --- Rosenbrock (2,3) and Dormand-Prince (``solvers/onestep.py``) -------------------------------

    def _onestep(self, tspan: Any, y0: np.ndarray) -> Dict[str, Any]:
        from ..solvers import dormand_prince, rosenbrock23
        from ..solvers.onestep import STALL_WINDOW_STEPS
        opts, system, cm = self.opts, self.system, self.cm
        ros = self.solver_id == 'ros23'
        method = rosenbrock23._Method if ros else dormand_prince._Method
        tspan = np.ascontiguousarray(tspan, dtype=float)
        y0 = np.ascontiguousarray(y0, dtype=float)
        t0, t_end = float(tspan[0]), float(tspan[-1])
        if t_end == t0:
            raise SolverError('span', 'Simulation start and end time are equal', t0)
        n = y0.size
        rtol = float(opts.get('rtol') or 1e-3)
        ab = opts.get('abstol', 1e-6)
        atol = np.full(n, float(ab)) if np.ndim(ab) == 0 else np.array(ab, dtype=float)
        nn = opts.get('non_negative')
        nn_idx = (np.nonzero(np.array(nn, dtype=bool))[0].astype(np.int64) if nn is not None and any(nn)
                  else np.zeros(0, dtype=np.int64))
        max_steps = opts.get('max_steps') or method.default_max_steps
        where, W, form_cb, solve_cb = (self._matrix(t0, y0, atol / rtol, 'auto', 'ros23', nn_idx) if ros
                                       else (cs.MAT_KERNEL, None, cs.no_callback, cs.no_callback))
        fpar = np.array([rtol, float(opts['hmax']) if (opts.get('hmax') or 0) > 0 else 0.0,
                         float(opts['h0']) if (opts.get('h0') or 0) > 0 else 0.0, float(max_steps),
                         float(opts['hmin']) if (opts.get('hmin') or 0) > 0 else 0.0])
        progress = self._progress(False)
        ipar = np.array([0 if ros else 1, self.constant, cm.has_store, progress is not cs.no_callback,
                         opts.get('stall_window') or STALL_WINDOW_STEPS, where], dtype=np.int64)
        yout = np.empty((tspan.size, n))
        held = np.zeros(n, dtype=np.int64)
        stats = np.zeros(8, dtype=np.int64)
        fstat = np.zeros(4)
        cm.W[0] = math.nan
        status = cs.onestep(cm.rhs, cm.store, self._jac_cb or cs.no_callback, progress, system.P, system.X, cm.W,
                            cm.IW, tspan, y0, atol, nn_idx, self.jac_mode, self.colptr, self.rowidx, self.jvals,
                            self.gptr, self.gcols, self.ybuf, fpar, ipar, yout, held, stats, fstat,
                            self.ct, self.cy, self.cint, self.cflt, form_cb, solve_cb, self.jdense, self.rbuf,
                            self.xbuf)
        if status != cs.OK:
            if status == cs.E_HISTORY:
                raise HistoryFull()
            if status == cs.E_CALLBACK:
                raise self._callback_error(progress, form_cb, solve_cb)
            raise self._onestep_error(status, fstat, method, max_steps, self.matrix_error)
        rows = int(stats[7])
        out = {'nsteps': int(stats[0]), 'nfailed': int(stats[1]), 'nfevals': int(stats[2]),
               'nbelowtol': int(stats[3]), 'negative': int(stats[4]),
               'held': held if (ros and nn_idx.size) else None, 'solver': method.id, 'points': rows}
        if ros:
            out.update(npds=int(stats[5]), ndecomps=int(stats[6]), sparse=bool(W is not None and W.sparse),
                       fill=W.info['fill'] if W is not None else None)
        return {'t': tspan[:rows].copy(), 'y': list(yout[:rows]), 'stopped': None, 'stats': out}

    @staticmethod
    def _onestep_error(status: int, fstat: np.ndarray, method: Any, max_steps: float,
                       matrix_error: str) -> SolverError:
        from ..solvers.onestep import non_finite_error
        t = float(fstat[0])
        if status == cs.E_ABORTED:
            return SolverError('aborted', 'Simulation aborted', t)
        if status == cs.E_SINGULAR:
            return SolverError('singular', f'{_singular_text(fstat)} (at t={t})', t)
        if status == cs.E_MATRIX:
            return SolverError('singular', f'{matrix_error} (at t={t})', t)
        if status == cs.E_FLOOR_NONFINITE:
            return non_finite_error(t, int(fstat[2]))
        if status == cs.E_FLOOR:
            return SolverError('tolerance', method.floor_message(t, float(fstat[1]), int(fstat[2])), t)
        if status == cs.E_STEPS:
            return SolverError('steps', method.step_budget_message(max_steps, t), t)
        if status == cs.E_STALLED:
            return SolverError('stalled', method.stall_message(t, int(fstat[1]), float(fstat[2])), t)
        return SolverError('compiled', f'The compiled solver ended with status {status} at t={t}.', t)


def _singular_text(fstat: np.ndarray) -> str:
    col = int(fstat[1])
    if fstat[3]:
        return non_finite_message(None, col, float(fstat[2]))
    return singular_message(None, col, SINGULAR_HINT)


def restart_state(abstol: Any) -> Any:
    """What a run made again from its start needs back: the tolerances, which
    the NDF raises in place under ``auto_abstol``."""
    return abstol.copy() if isinstance(abstol, np.ndarray) else None


__all__: Sequence[str] = ('COMPILED_SOLVERS', 'CompiledRun', 'HistoryFull', 'NotCompiled', 'UsePython', 'prepare',
                          'compiled_model')
