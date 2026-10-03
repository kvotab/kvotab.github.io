"""A run of a Julia-derived solver on the compiled path.

:class:`JuliaRun` stands in for ``fbdf``, ``qndf``, ``rodas5p``, ``radau5``,
``kencarp4`` and ``trbdf2`` as :class:`~.run.CompiledRun` stands in for the
NDF: called with a span and a start, it answers as the adapter
(``solvers/julia/adapter.py``) does -- the same rows, the same counts, the
same events and the same failures, with their messages -- from the loop
compiled in :mod:`.julia`.

It maps the run's options as the adapter does, and builds the Python
solver's own ``Integrator`` for each span, which holds every number the
methods are configured with (their tableaux, orders and controllers), the
Jacobian's colouring, W's pattern and, for a sparse W, the ``SparseLU`` the
compiled loop calls back to factorise and to solve with: the loop is handed
those objects' arrays, so a run is configured exactly as the Python solver
configures it. What stays in Python is called back -- an analytic Jacobian
(the recorders handed over first), progress, SuperLU -- and an exception any
of them raises, or the model's equations raise, comes out as the adapter
turns it into a :class:`~kompartment.engine.solvers.SolverError`.

A run whose Python solver has been given other arithmetic than the one the
loop ports -- a test putting the application's own ``pow`` and dense LU in
its place -- keeps to the Python loop (:func:`why_python`). So does a run of
the five methods that came with the default algorithm (``auto``,
``fbdf_krylov``, ``rosenbrock23``, ``tsit5``, ``vern7``), which the loop
does not port yet: on the compiled path they run their Python solver's own
loop on the compiled model, as SciPy's solvers do, the same steps to the
last bit.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from ..solvers import SolverError
from . import FAIL_PYTHON, CompiledFailure, python_error
from . import julia as cj
from .model import Callback, CompiledModel, HistoryFull
from .solvers import no_callback, no_events

#: The solvers whose loop :mod:`.julia` compiles, and the family each is.
METHODS = {'fbdf': cj.M_FBDF, 'qndf': cj.M_QNDF, 'rodas5p': cj.M_ROSENBROCK, 'radau5': cj.M_RADAU,
           'kencarp4': cj.M_ESDIRK, 'trbdf2': cj.M_ESDIRK}


def why_python(solver_id: str, opts: Dict[str, Any]) -> Optional[str]:
    """Why a run of ``solver_id`` keeps the Python solver's own loop, or None."""
    if solver_id not in METHODS:
        # The default algorithm's methods (and the switch between them) have
        # no compiled loop yet: such a run falls back to PythonLoopRun, the
        # Python solver's loop on the compiled model, as SciPy's solvers do.
        return 'the compiled loop does not take this method yet'
    from ..solvers.julia import _js, controller, linalg, newton
    from ..solvers.julia.methods import fbdf, qndf, radau
    # The arithmetic the loop ports: each module's pow, and the dense LU.
    ported = [getattr(m, 'jpow', None) for m in (_js, controller, newton, fbdf, qndf, radau)]
    ported += [linalg.DenseLU.factor, linalg.DenseLU.solve]
    if any(getattr(fn, '__module__', None) not in (_js.__name__, linalg.__name__) for fn in ported):
        return "the Python solver's arithmetic has been replaced, and the compiled loop ports the original"
    return None


def _adapted(e: BaseException, t0: float) -> BaseException:
    """What the adapter raises for an exception out of the package's solve."""
    if not isinstance(e, Exception):
        return e
    at = getattr(e, 't', None)
    code = getattr(e, 'code', None) if isinstance(e, SolverError) else None
    return SolverError(code or 'failed', str(e), at if at is not None else t0)


def settings_of(opts: Dict[str, Any], saveat: List[float]) -> Dict[str, Any]:
    """The package's options for a run, as the adapter's ``solve_it`` maps
    them; what the adapter hands over as callbacks -- the steps, the outputs,
    progress -- the compiled loop does itself."""
    from ..solvers.julia.adapter import _order, _positive
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
    return settings


def _floats(a: Any, n: int) -> np.ndarray:
    """A tolerance, one number or one per state, as n contiguous floats."""
    if np.ndim(a) == 0:
        return np.full(n, float(a))
    return np.ascontiguousarray(a, dtype=float)


def _coefficients(solver_id: str, cache: Any) -> np.ndarray:
    """The method's numbers in the layout :mod:`.julia` reads (``coef``),
    from the Python solver's own cache."""
    if solver_id == 'rodas5p':
        tab = cache.tab
        s, nh = tab.stages, len(tab.H)
        a = np.zeros((s, s))
        C = np.zeros((s, s))
        for i in range(s):
            a[i, :len(tab.a[i])] = tab.a[i]
            C[i, :len(tab.C[i])] = tab.C[i]
        return np.concatenate([[s, nh, tab.gamma], a.ravel(), C.ravel(), tab.c, tab.d, tab.b, tab.btilde,
                               np.asarray(tab.H, dtype=float).ravel()]).astype(float)
    if solver_id in ('kencarp4', 'trbdf2'):
        tab = cache.tab
        s = tab.stages
        alpha = np.zeros((s, s))
        for i in range(s):
            alpha[i, :len(tab.alpha[i])] = tab.alpha[i]
        return np.concatenate([[s, tab.gamma, 1.0 if cache.smooth_est else 0.0],
                               np.asarray(tab.a, dtype=float).ravel(), tab.b, tab.btilde, tab.c,
                               alpha.ravel()]).astype(float)
    if solver_id == 'fbdf':
        from ..solvers.julia.methods.fbdf import BDF_COEFFS
        table = np.zeros((cj.FB_STRIDE, cj.FB_STRIDE))
        for k, row in enumerate(BDF_COEFFS):
            if row is not None:
                table[k, :len(row)] = row
        return table.ravel()
    if solver_id == 'qndf':
        from ..solvers.julia.methods.qndf import GAMMA
        return np.concatenate([np.asarray(cache.kappa[:5], dtype=float), GAMMA, cache.U]).astype(float)
    tab = cache.tab
    return np.array([getattr(tab, name) for name in cj.RADAU_COEFFICIENTS], dtype=float)


def _method_state(solver_id: str, cache: Any) -> Any:
    """The method's floats and integers as a run starts them (cpar and ipar
    after the shared ones), from the Python solver's own cache."""
    if solver_id == 'fbdf':
        fbv = np.zeros(cj.NFB)
        fbv[[cj.FB_TERKM2, cj.FB_TERKM1, cj.FB_TERK, cj.FB_TERKP1, cj.FB_TERKM3, cj.FB_NEXT_TERK]] = (
            cache.terkm2, cache.terkm1, cache.terk, cache.terkp1, cache.terkm3, cache.next_terk)
        fbv[[cj.FB_GAMMA, cj.FB_QMAX, cj.FB_QMIN, cj.FB_QSTEADY_MIN, cj.FB_QSTEADY_MAX, cj.FB_MAX_ORDER]] = (
            cache.gamma_ctrl, cache.qmax, cache.qmin, cache.qsteady_min, cache.qsteady_max, cache.max_order)
        fbi = np.zeros(cj.NFI, dtype=np.int64)
        fbi[[cj.FI_ORDER, cj.FI_PREV_ORDER, cj.FI_N_HISTORY, cj.FI_QWAIT, cj.FI_NCONSTEPS, cj.FI_CONSFAIL,
             cj.FI_FROM_EVENT, cj.FI_PENDING, cj.FI_NEXT_ORDER, cj.FI_MIN_ORDER]] = (
            cache.order, cache.prev_order, cache.n_history, cache.qwait, cache.nconsteps, cache.consfailcnt,
            cache.iters_from_event, cache.prev_order_pending, cache.next_order, cache.min_order)
        return fbv, fbi
    if solver_id == 'qndf':
        qnv = np.zeros(cj.NQN)
        qnv[[cj.QN_DTPREV, cj.QN_EEST1, cj.QN_EEST2, cj.QN_GAMMA, cj.QN_QMAX, cj.QN_QMIN, cj.QN_QSTEADY_MIN,
             cj.QN_QSTEADY_MAX, cj.QN_MAX_ORDER]] = (
            cache.dtprev, cache.eest1, cache.eest2, cache.gamma_ctrl, cache.qmax, cache.qmin, cache.qsteady_min,
            cache.qsteady_max, cache.max_order)
        qni = np.zeros(cj.NQI, dtype=np.int64)
        qni[[cj.QI_ORDER, cj.QI_PREV_ORDER, cj.QI_NCONSTEPS, cj.QI_CONSFAIL, cj.QI_STARTED, cj.QI_MIN_ORDER]] = (
            cache.order, cache.prev_order, cache.nconsteps, cache.consfailcnt, cache.started, cache.min_order)
        return qnv, qni
    if solver_id == 'radau5':
        rav = np.zeros(cj.NRA)
        rav[[cj.RA_DTPREV, cj.RA_COMPLEX_DT, cj.RA_ETA_OLD, cj.RA_KAPPA, cj.RA_CUTOFF]] = (
            cache.dtprev, cache.complex_dt, cache.eta_old, cache.kappa, cache.fast_convergence_cutoff)
        rai = np.zeros(cj.NRI, dtype=np.int64)
        statuses = {'Convergence': cj.RS_CONVERGENCE, 'FastConvergence': cj.RS_FAST, 'Divergence': cj.RS_DIVERGENCE}
        rai[[cj.RI_COMPLEX_VALID, cj.RI_HAVE_HISTORY, cj.RI_STATUS, cj.RI_MAX_ITERS, cj.RI_SMOOTH]] = (
            cache.complex_valid, cache.have_history, statuses[cache.status], cache.max_iters, cache.smooth_est)
        return rav, rai
    return np.zeros(0), np.zeros(0, dtype=np.int64)


def _plan(jc: Any, n: int) -> Sequence[np.ndarray]:
    """The Jacobian's colouring as flat arrays: per group its columns
    (gptr, gcols) and the entries it fills (eptr; each entry's row, its
    column's place in gcols, its place in J's values)."""
    if jc._plan is None:
        # Set where the Python solver first differences: the same plan.
        from ..solvers.julia.jacobian import colour_columns
        from ..solvers.julia.linalg import dense_pattern
        jc.diff_pattern = dense_pattern(n)
        jc._set_groups(colour_columns(n, jc.diff_pattern[0], jc.diff_pattern[1]))
    gptr, eptr = [0], [0]
    gcols: List[np.ndarray] = []
    erow: List[np.ndarray] = []
    ewhich: List[np.ndarray] = []
    eent: List[np.ndarray] = []
    for g, entries, rows, which in jc._plan:
        ewhich.append(np.asarray(which, dtype=np.int64) + gptr[-1])
        gcols.append(np.asarray(g, dtype=np.int64))
        gptr.append(gptr[-1] + len(g))
        erow.append(np.asarray(rows, dtype=np.int64))
        eent.append(np.asarray(entries, dtype=np.int64))
        eptr.append(eptr[-1] + len(rows))

    def flat(parts: List[np.ndarray]) -> np.ndarray:
        return np.ascontiguousarray(np.concatenate(parts) if parts else np.zeros(0), dtype=np.int64)
    return (np.asarray(gptr, dtype=np.int64), flat(gcols), np.asarray(eptr, dtype=np.int64), flat(erow), flat(ewhich),
            flat(eent))


class JuliaRun:
    """The Julia-derived solver of one run, compiled: called as
    :class:`~.run.CompiledRun` is -- ``run(tspan, y0)`` for each span, with
    :meth:`start` before the first and :meth:`finish` after the last."""

    def __init__(self, system: Any, cm: CompiledModel, solver_id: str, opts: Dict[str, Any],
                 solver_points: bool = False) -> None:
        self.system = system
        self.cm = cm
        self.solver_id = solver_id
        self.opts = opts
        n = system.nstate
        jac = opts.get('jacobian')
        if jac is not None and jac.get('available') is False:
            # Declined values: differenced through the pattern (the adapter).
            jac = ({'pattern': jac['pattern'], 'groups': jac.get('groups'), 'constant': False, 'evaluate': None}
                   if jac.get('pattern') is not None else None)
        self.jacobian = jac
        self.evaluate = jac.get('evaluate') if jac else None
        if self.evaluate is not None:
            pattern = jac['pattern']
            self._jrows = np.asarray(pattern.row_idx, dtype=np.int64)
            self._jcols = np.repeat(np.arange(pattern.n, dtype=np.int64),
                                    np.diff(np.asarray(pattern.col_ptr, dtype=np.int64)))
        self.ybuf = np.zeros(n)
        self.rbuf = np.zeros(n)
        self.xbuf = np.zeros(n)
        self.pbuf = np.zeros(1, dtype=np.int64)
        self.integ: Any = None  # the Python solver's objects for the span under way
        self._jac_cb = Callback(self._jacobian) if self.evaluate is not None else None
        self._factor_cb = Callback(self._factor)
        self._solve_cb = Callback(self._solve)
        on_step = opts.get('on_step')
        self._progress_cb = Callback(self._progress) if on_step is not None else None
        # The accepted steps, when they are output: kept across the spans.
        rows = 2 * cj.MAX_SOLVER_POINTS if solver_points else 1
        self.ct = np.zeros(rows)
        self.cy = np.zeros((rows, n if solver_points else 1))
        self.cint = np.array([0, 0, 1, 1 if solver_points else 0], dtype=np.int64)
        self.cflt = np.array([-math.inf])
        # The discrete events, every one terminal, with the direction the
        # integrator reads off the adapter's list.
        from ..solvers.julia.integrator import _direction_of
        events = system.events
        nev = events.n if events is not None else 0
        self.evf = cm.module.event_values if nev else no_events
        direction = getattr(events, 'direction', None) if nev else None
        listed = SimpleNamespace(direction=[] if direction is None else list(np.asarray(direction).tolist()))
        self.evdir = np.array([_direction_of(listed, i) for i in range(nev)], dtype=float)
        self.evbuf = np.zeros((3, max(nev, 1)))
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

    # --- what the loop calls back --------------------------------------------------------------------

    def _jacobian(self, t: float, _unused: float) -> int:
        """The model's Jacobian at (t, ybuf) into the Python solver's cache, as
        the adapter's ``jacobian_for`` puts it there: 1, or 0 where declined.
        Worked out in Python: the recorders as the compiled run has them
        first, and a clock not cached."""
        if self.cm.has_store:
            self.cm.sync_histories()
        self.system._clock_at = math.nan
        got = self.evaluate(t, self.ybuf)  # type: ignore[misc]
        if got is None:
            return 0
        values = np.asarray(got, dtype=float)
        jc = self.integ.jac_cache
        if jc.sparse:
            jc.values[:] = values
        else:
            jc.J.fill(0.0)
            jc.J[self._jrows, self._jcols] = values
        return 1

    def _factor(self, _a: float, _b: float) -> int:
        """W's values, formed by the loop, factorised by the Python solver's SparseLU."""
        W = self.integ.W
        ok = W.lu.factor(W.w_values)
        W._factored = True
        return 1 if ok else 0

    def _solve(self, _a: float, _b: float) -> int:
        self.xbuf[:] = self.integ.W.lu.solve(self.rbuf)
        return 0

    def _progress(self, fraction: float, t: float) -> int:
        """The adapter's progress: on_step(fraction, steps, t), False to stop."""
        return 0 if self.opts['on_step'](fraction, int(self.pbuf[0]), t) is False else 1

    def _callback_error(self) -> BaseException:
        for cb in (self._jac_cb, self._factor_cb, self._solve_cb, self._progress_cb):
            if cb is not None and cb.error is not None:
                e, cb.error = cb.error, None
                return e
        return RuntimeError('a callback of the compiled solver failed')

    # --- a span ---------------------------------------------------------------------------------------

    def __call__(self, tspan: Any, y0: np.ndarray) -> Dict[str, Any]:
        from ..solvers.julia.adapter import AS_BDF
        self.cm.load_clock()
        variant = AS_BDF.get(self.solver_id) if self.opts.get('bdf') else None
        run_id = variant[0] if variant else self.solver_id
        grid = np.array(tspan, dtype=float)
        t0 = float(grid[0])
        tf = float(grid[-1])
        if not (tf != t0):
            raise SolverError('span', 'Simulation start and end time are equal', t0)
        try:
            with np.errstate(all='ignore'):
                return self._span(grid, t0, tf, y0, variant, run_id)
        except (SolverError, HistoryFull):
            raise
        except CompiledFailure as e:
            # Where the model's own equations raise: the same exception, at
            # the same evaluation, as the adapter hands it on.
            raised = self.cm.python_error() if e.args and int(e.args[0]) == FAIL_PYTHON else None
            if raised is not None:
                self.cm.py_callback.error = None
            else:
                raised = python_error(e)
            raise _adapted(raised, t0) from None
        except Exception as e:  # noqa: BLE001 - the adapter re-throws whatever the package threw
            raise _adapted(e, t0) from None

    def _span(self, grid: np.ndarray, t0: float, tf: float, y0: np.ndarray, variant: Any,
              run_id: str) -> Dict[str, Any]:
        from ..solvers.julia._js import js_string, to_exponential
        from ..solvers.julia.adapter import ALGORITHMS, _jacobian_for
        from ..solvers.julia.integrator import DEFAULTS, Integrator, ODEProblem
        opts, cm, system = self.opts, self.cm, self.system
        saveat = [t0, tf] if opts.get('ends_only') else [float(v) for v in grid]
        jacobian = self.jacobian
        pattern = jacobian['pattern'] if jacobian else None
        problem = ODEProblem(cm.derivative, np.asarray(y0, dtype=float), (t0, tf), jac=_jacobian_for(jacobian),
                             jac_pattern=(pattern.col_ptr, pattern.row_idx) if pattern is not None else None)
        run_opts = dict(DEFAULTS)
        run_opts.update(settings_of(opts, saveat))
        n = problem.n
        if not (n > 0):
            raise SolverError('span', 'The initial state is empty', t0)
        if not math.isfinite(t0) or not math.isfinite(tf):
            raise SolverError('span', 'The time span must be finite', t0)
        alg = (variant[1] if variant else ALGORITHMS[self.solver_id])()
        integ = Integrator(problem, alg, run_opts)
        self.integ = integ
        cache, jc, W, newton, pi = integ.cache, integ.jac_cache, integ.W, integ.newton, integ.controller

        # Where the rows are saved, as the integrator sorts and starts them.
        tdir = integ.tdir
        times = sorted((float(v) for v in run_opts['saveat']), reverse=tdir < 0)
        at = 0
        while at < len(times) and tdir * (times[at] - t0) < 0:
            at += 1
        max_steps = run_opts['max_steps'] if run_opts['max_steps'] > 0 else run_opts['maxiters']
        below_tol_max = max(0, int(math.floor(float(run_opts['below_tol_run'] or 0) + 0.5)))
        mv, mi = _method_state(self.solver_id, cache)
        fpar = np.zeros(cj.NFP)
        fpar[[cj.FP_RTOL, cj.FP_T0, cj.FP_TF, cj.FP_DTMAX, cj.FP_DT, cj.FP_MAX_STEPS, cj.FP_MAX_AGE, cj.FP_KAPPA,
              cj.FP_CUTOFF]] = (integ.reltol, t0, tf, run_opts['dtmax'], run_opts['dt'], max_steps, W.max_age,
                                newton.kappa, newton.fast_convergence_cutoff)
        ipar = np.zeros(cj.NIP, dtype=np.int64)
        ipar[[cj.IP_METHOD, cj.IP_BELOW_TOL, cj.IP_STORE, cj.IP_PROGRESS, cj.IP_SAVEAT_AT, cj.IP_ORDER,
              cj.IP_AUTO_ABSTOL, cj.IP_NEWTON_MAX_ITERS]] = (
            METHODS[self.solver_id], below_tol_max, cm.has_store, self._progress_cb is not None, at, cache.order,
            integ.auto_abstol, newton.max_iters)
        cpar = np.concatenate([[pi.beta1, pi.beta2, pi.gamma, pi.qmin, pi.qmax, pi.qsteady_min, pi.qsteady_max,
                                pi.qoldinit, pi.errold], mv]).astype(float)
        fl = np.array([self._jac_cb is not None, jc.sparse, run_opts['norm'] == 'max'], dtype=np.int64)
        gptr, gcols, eptr, erow, ewhich, eent = _plan(jc, n)
        none_i = np.zeros(0, dtype=np.int64)
        # The integrator's own tolerance, which the loop raises in place under
        # auto_abstol (a copy the Integrator made: the run's is never touched).
        atol = _floats(integ.abstol, n)
        nn = (np.ascontiguousarray(integ.non_negative, dtype=np.int64) if integ.non_negative is not None
              else none_i)
        rows = len(times) + 1
        tout = np.zeros(rows)
        yout = np.zeros((rows, n))
        stats = np.zeros(cj.NC + 1, dtype=np.int64)
        fstat = np.zeros(3)
        cm.W[0] = math.nan
        status = cj.julia(
            cm.rhs, cm.store, self.evf, self._jac_cb or no_callback, self._progress_cb or no_callback,
            self._factor_cb, self._solve_cb, system.P, system.X, cm.W, cm.IW, cm.py_callback,
            np.array(times, dtype=float), np.ascontiguousarray(y0, dtype=float), atol, _floats(run_opts['abstol'], n),
            nn, _coefficients(self.solver_id, cache), fpar, cpar, np.concatenate([ipar, mi]), fl,
            jc.J if jc.J is not None else np.zeros((1, 1)), jc.values if jc.values is not None else np.zeros(1),
            gptr, gcols, eptr, erow, ewhich, eent, self.ybuf,
            W.W if not W.sparse else np.zeros((1, 1)), W.w_values if W.sparse else np.zeros(1),
            W.j_to_w if W.sparse else none_i, W.diag_w if W.sparse else none_i, self.rbuf, self.xbuf,
            self.evdir, self.evbuf, self.evy, self.evwhich, self.evstat, tout, yout, stats, fstat, self.pbuf,
            self.ct, self.cy, self.cint, self.cflt)

        if status == cj.E_HISTORY:
            raise HistoryFull()
        if status == cj.E_CALLBACK:
            raise _adapted(self._callback_error(), t0)
        if status == cj.E_ZERO_DIVISION:
            raise SolverError('failed', 'float division by zero', t0)
        if status == cj.E_INITIAL:
            raise SolverError('nonfinite', f'The state or its derivative is not a number at t = {js_string(t0)} '
                                           f'(component {int(fstat[2])})', t0)
        kept = int(stats[cj.NC])
        last_t = float(tout[kept - 1]) if kept else t0
        if status == cj.R_STOPPED:
            raise SolverError('aborted', 'Simulation aborted', last_t)
        if status != cj.OK:
            t, step = float(fstat[0]), abs(float(fstat[1]))
            if status == cj.R_MAX_ITERS:
                code, message = 'steps', (f'More than {js_string(max_steps)} steps were needed, and the run stopped '
                                          f'at t = {js_string(t)}')
            elif status == cj.R_DT_FLOOR:
                code, message = 'tolerance', (f'The step size fell to {to_exponential(step, 3)} at t = '
                                              f'{js_string(t)}, which does not change the time at this magnitude')
            elif status == cj.R_NOT_SOLVED:
                code, message = 'tolerance', (f'The step could not be taken at t = {js_string(t)} even at '
                                              f'{to_exponential(step, 3)}, the smallest the clock can represent: '
                                              'the equations of its stages could not be solved there')
            elif status == cj.R_UNSTABLE:
                code, message = 'nonfinite', (f'The solution became infinite or not-a-number at t = {js_string(t)} '
                                              f'(component {int(fstat[2])})')
            elif status == cj.R_EEST_NAN:
                code, message = 'nonfinite', (f'The error estimate is not a number at t = {js_string(t)}, even with '
                                              f'a step of {to_exponential(step, 3)}, the smallest the clock can '
                                              'represent')
            elif status == cj.R_ERROR_TEST:
                code, message = 'tolerance', (f'The error test failed at t = {js_string(t)} with a step of '
                                              f'{to_exponential(step, 3)}, the smallest the clock can represent'
                                              + (f', {below_tol_max} times in a row' if below_tol_max > 0 else ''))
            else:
                code, message = 'failed', f'The compiled solver ended with status {status} at t={t}.'
            raise SolverError(code, f'{message} ({run_id})', last_t)

        nev = self.evdir.size
        stopped = ({'t': float(self.evstat[1]), 'y': self.evy.copy(),
                    'which': [i for i in range(nev) if self.evwhich[i]]} if self.evstat[0] else None)
        return {
            't': tout[:kept].copy(),
            'y': [yout[i].copy() for i in range(kept)],
            'stopped': stopped,
            'stats': {
                'nsteps': int(stats[cj.C_NSTEPS]),
                'nfailed': int(stats[cj.C_NREJECT]),
                'nfevals': int(stats[cj.C_NF]),
                'npds': int(stats[cj.C_NJAC]),
                'ndecomps': int(stats[cj.C_NFACTOR]),
                'nsolves': int(stats[cj.C_NSOLVE]),
                'solver': run_id,
                'sparse': bool(W.sparse),
                'fill': W.fill,
            },
        }


__all__: Sequence[str] = ('METHODS', 'JuliaRun', 'settings_of', 'why_python')
