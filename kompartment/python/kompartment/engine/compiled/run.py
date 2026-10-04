"""A run's solve on the compiled path.

:func:`prepare` hands back the compiled stand-in for a run's solver, which
the runner calls in place of it -- with a span and a start, answering as the
solver's Python version does (:mod:`..solverset`), failures and their
messages included:

* a :class:`CompiledRun` for the NDF, Rosenbrock (2,3) and Dormand-Prince,
  whose loops are compiled (:mod:`.solvers`);
* a :class:`~.julia_run.JuliaRun` for every Julia-derived one and the two
  switching solvers, whose loop is compiled too (:mod:`.julia`) -- ``auto``
  going on, where it turns stiff, on the NDF's;
* a :class:`PythonLoopRun` for a solver that keeps its own loop in Python --
  SciPy's, and a Julia-derived one whose Python solver computes otherwise
  than the compiled loop ports (see :func:`.julia_run.why_python`) -- handed
  the compiled model.

What stays in Python is called back: an analytic Jacobian, with the
recorders handed over first (they live in the compiled arrays during a run);
the progress report; where the Python solver would factorise with SuperLU or
LAPACK rather than the application's dense LU, the iteration matrix itself,
formed and solved with by the Python solver's own
:class:`~kompartment.engine.solvers.matrix.IterationMatrix`; and the blocks a
model works out in Python (see :mod:`.model`).
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np

from ..jacobian import colour_columns, difference_jacobian
from ..solvers import SolverError
from ..solvers.matrix import APP_LU_MAX, DENSE_BELOW, IterationMatrix, non_finite_message, singular_message
from . import solvers as cs
from . import FAIL_PYTHON, CompiledFailure, NotCompiled, python_error
from .model import Callback, CompiledModel, HistoryFull, compile_model

#: The solvers with a compiled loop.
COMPILED_SOLVERS = ('ndf', 'ros23', 'dp45')
SINGULAR_HINT = 'A compartment with no way in and no way out will do this.'


class UsePython(NotCompiled):
    """This run is found, once under way, to be one for the Python path."""


def compiled_model(system: Any) -> CompiledModel:
    """The system's compiled derivative, compiled once per system; the
    reason it cannot be, as :class:`NotCompiled`, every time it is asked."""
    cached = getattr(system, '_compiled_model', None)
    if isinstance(cached, CompiledModel):
        return cached
    if isinstance(cached, str):
        raise NotCompiled(cached)
    # A process compiling this system's module into the cache while the system
    # was busy with something else (a split run's parts): waited for, so that
    # the module is loaded from the cache rather than compiled again here.
    warming = getattr(system, '_warming', None)
    if warming is not None:
        system._warming = None
        warming.join()
    try:
        cm = compile_model(system)
    except NotCompiled as e:
        system._compiled_model = str(e)
        raise
    system._compiled_model = cm
    return cm


def prepare(system: Any, solver_id: str, opts: Dict[str, Any], *, min_change: float = 0.0,
            solver_points: bool = False, equations: bool = False, solver: Any = None) -> Any:
    """A compiled stand-in for the solver of this run: a :class:`CompiledRun`
    for the solvers with a compiled loop, a :class:`~.julia_run.JuliaRun` for
    the Julia-derived ones and the switching solvers, a :class:`PythonLoopRun`
    for the ones that keep their own (``solver`` is it) -- or
    :class:`NotCompiled` saying why the run keeps to the Python path."""
    if equations:
        raise NotCompiled('the run integrates a system of equations of its own')
    cm = compiled_model(system)
    from ..solvers.julia.adapter import ALGORITHMS
    why = None
    if solver_id in ALGORITHMS:
        from .julia_run import JuliaRun, why_python
        why = why_python(solver_id, opts)
        if why is None:
            return JuliaRun(system, cm, solver_id, opts, solver_points)
    if solver_id not in COMPILED_SOLVERS:
        if solver is None:
            raise NotCompiled(f"the solver '{solver_id}' has no compiled loop")
        return PythonLoopRun(system, cm, solver_id, solver, opts, why)
    return CompiledRun(system, cm, solver_id, opts, solver_points)


class _CompiledEvents:
    """The discrete events as a Python solver asks for them (``Events``),
    their functions worked out by the compiled model."""

    def __init__(self, events: Any, cm: CompiledModel) -> None:
        self.n = events.n
        self.direction = events.direction
        self.cm = cm

    def fun(self, t: float, y: np.ndarray, out: Optional[np.ndarray] = None) -> np.ndarray:
        v = self.cm.event_values(t, y)
        if out is not None:
            out[:] = v
            return out
        return v.copy()


class PythonLoopRun:
    """A run whose solver keeps its own loop in Python -- SciPy's methods, and
    a Julia-derived one the compiled loop does not take -- on the compiled
    model: the derivative, what the recorders and the semi-analytical paths
    record at each step, the events' functions and what firing them does. The
    answer is the Python path's to the last bit, since every number the solver
    is given is. Called as :class:`CompiledRun` is; ``loop`` says the solver's
    own loop is not compiled."""

    loop = False

    def __init__(self, system: Any, cm: CompiledModel, solver_id: str, solver: Any, opts: Dict[str, Any],
                 why: Optional[str] = None) -> None:
        self.system = system
        self.cm = cm
        self.solver_id = solver_id
        self.solver = solver
        self.opts = opts
        #: Why the solver's loop is not compiled, as a run's stats say it.
        self.loop_why = (f"the solver '{solver_id}' keeps the loop of its own, in Python, on the compiled model"
                         + (f': {why}' if why else ''))
        jac = opts.get('jacobian')
        if jac and jac.get('evaluate') is not None:
            evaluate = jac['evaluate']

            def handed(t: float, y: np.ndarray) -> Any:
                # Worked out in Python: the recorders as the compiled model
                # has them first, and a clock it no longer holds after.
                self.cm.sync_histories()
                self.system._clock_at = math.nan
                try:
                    return evaluate(t, y)
                finally:
                    self.cm.W[0] = math.nan
            jac = dict(jac, evaluate=handed)
        self.jacobian = jac
        self.events = _CompiledEvents(system.events, cm) if system.events is not None else None

    def store_step(self, t: float, y: np.ndarray) -> None:
        self.cm.store_step(t, y, grow=True)

    def fire(self, which: Sequence[int], t: float, y: np.ndarray) -> None:
        self.cm.fire(which, t, y, grow=True)

    def start(self) -> None:
        self.cm.load()

    def steps_into(self, steps: Dict[str, Any]) -> None:
        """Nothing: the runner collects the steps itself, as on the Python path."""

    def finish(self) -> None:
        self.cm.write_back()

    def grow(self) -> None:
        self.cm.grow()

    def __call__(self, tspan: Any, y0: np.ndarray) -> Dict[str, Any]:
        self.cm.load_clock()
        opts = dict(self.opts)
        opts['jacobian'] = self.jacobian
        opts['events'] = self.events
        return self.solver(self.cm.derivative, tspan, y0, opts)


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
        # The discrete events: their functions, the directions they watch,
        # and where a solve an event stops says so.
        events = system.events
        nev = events.n if events is not None else 0
        self.evf = cm.module.event_values if nev else cs.no_events
        self.evdir = (np.ascontiguousarray(events.direction, dtype=float) if nev else np.zeros(0))
        self.evbuf = np.zeros((5, max(nev, 1)))
        self.evy = np.zeros(n)
        self.evwhich = np.zeros(max(nev, 1), dtype=np.int64)
        self.evstat = np.zeros(2)

    # --- the run around the spans -----------------------------------------------------------------

    def start(self) -> None:
        self.cm.load()
        # The steps collected as output start afresh with each attempt at the run.
        self.cint[:3] = (0, 0, 1)
        self.cflt[0] = -math.inf

    def store_step(self, t: float, y: np.ndarray) -> None:
        """A step recorded between solves (after an event): a history that
        runs out of room makes the run again, as inside the loop."""
        self.cm.store_step(t, y)

    def fire(self, which: Sequence[int], t: float, y: np.ndarray) -> None:
        self.cm.fire(which, t, y)

    def _stopped(self) -> Optional[Dict[str, Any]]:
        """Where an event stopped the last solve, as the Python solvers say it."""
        if not self.evstat[0]:
            return None
        nev = self.evdir.size
        return {'t': float(self.evstat[1]), 'y': self.evy.copy(),
                'which': [i for i in range(nev) if self.evwhich[i]]}

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
            # A matrix the Python solver would not form either: it stops on
            # it, the NDF calling it singular.
            if kind == 'ndf':
                from ..solverset import variable_order_failure
                raise variable_order_failure(SolverError('singular', str(e), t0), t0) from None
            raise RuntimeError(str(e)) from None
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
        self.cm.load_clock()
        try:
            if self.solver_id == 'ndf':
                return self._ndf(tspan, y0)
            return self._onestep(tspan, y0)
        except CompiledFailure as e:
            # Where the model's own equations raise on the Python path: the
            # same exception, at the same evaluation.
            raised = self.cm.python_error() if e.args and int(e.args[0]) == FAIL_PYTHON else None
            if raised is not None:
                self.cm.py_callback.error = None
                raise raised from None
            raise python_error(e) from None

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
                        cm.py_callback, tspan, y0, atol, constrained, self.jac_mode, self.colptr, self.rowidx,
                        self.jvals, self.gptr, self.gcols, self.ybuf, fpar, ipar, yout, held, stats, fstat,
                        self.ct, self.cy, self.cint, self.cflt, form_cb, solve_cb, self.jdense, self.held_in_w,
                        self.rbuf, self.xbuf, self.evf, self.evdir, self.evbuf, self.evy, self.evwhich, self.evstat)
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
            't': tspan[:rows].copy(), 'y': list(yout[:rows]), 'stopped': self._stopped(),
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
                            cm.IW, cm.py_callback, tspan, y0, atol, nn_idx, self.jac_mode, self.colptr, self.rowidx,
                            self.jvals, self.gptr, self.gcols, self.ybuf, fpar, ipar, yout, held, stats, fstat,
                            self.ct, self.cy, self.cint, self.cflt, form_cb, solve_cb, self.jdense, self.rbuf,
                            self.xbuf, self.evf, self.evdir, self.evbuf, self.evy, self.evwhich, self.evstat)
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
        return {'t': tspan[:rows].copy(), 'y': list(yout[:rows]), 'stopped': self._stopped(), 'stats': out}

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


__all__: Sequence[str] = ('COMPILED_SOLVERS', 'CompiledRun', 'HistoryFull', 'NotCompiled', 'PythonLoopRun',
                          'UsePython', 'prepare',
                          'compiled_model')
