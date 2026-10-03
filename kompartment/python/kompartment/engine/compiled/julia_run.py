"""A run of a Julia-derived solver on the compiled path.

:class:`JuliaRun` stands in for every Julia-derived method -- ``fbdf``,
``fbdf_krylov``, ``qndf``, ``rodas5p``, ``radau5``, ``kencarp4``,
``trbdf2``, ``rosenbrock23``, ``tsit5`` and ``vern7`` -- and for the two
switching solvers, ``auto_julia`` (DifferentialEquations.jl's default
algorithm) and ``auto`` (the same start, handing the run to the NDF), as
:class:`~.run.CompiledRun` stands in for the NDF: called with a span and a
start, it answers as the adapter (``solvers/julia/adapter.py``) does -- the
same rows, the same counts, the same events and the same failures, with
their messages -- from the loop compiled in :mod:`.julia`.

It maps the run's options as the adapter does, and builds the Python
solver's own ``Integrator`` for each span, which holds every number the
methods are configured with (their tableaux, orders and controllers, the
switch's thresholds), the Jacobian's colouring, W's pattern and, for a
sparse W, the ``SparseLU`` the compiled loop calls back to factorise and to
solve with: the loop is handed those objects' arrays, so a run is configured
exactly as the Python solver configures it. A method that forms no matrix --
an explicit one, the matrix-free FBDF, ``auto``'s explicit start -- is handed
none. What stays in Python is called back -- an analytic Jacobian (the
recorders handed over first), progress, SuperLU -- and an exception any of
them raises, or the model's equations raise, comes out as the adapter turns
it into a :class:`~kompartment.engine.solvers.SolverError`.

``auto`` is the adapter's ``auto`` step for step: the compiled explicit start
at a tenth of the tolerances, landing on the corners of the clock-read
tables, and where the loop stops for the hand-off, the compiled NDF
(:class:`~.run.CompiledRun`, ``solverset.variable_order``'s port) over the
rest of the span, from the last accepted point; the two parts' rows and
counts put together as the adapter puts them together.

A run whose Python solver has been given other arithmetic than the one the
loop ports -- a test putting the application's own ``pow`` and dense LU in
its place -- keeps to the Python loop (:func:`why_python`).
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..solvers import SolverError
from . import FAIL_PYTHON, CompiledFailure, python_error
from . import julia as cj
from .model import Callback, CompiledModel, HistoryFull
from .solvers import no_callback, no_events

#: The solvers whose loop :mod:`.julia` compiles, and the family each is (a
#: switching solver: None, its methods chosen from the default algorithm's).
METHODS: Dict[str, Optional[int]] = {
    'fbdf': cj.M_FBDF, 'fbdf_krylov': cj.M_FBDF, 'qndf': cj.M_QNDF, 'rodas5p': cj.M_ROSENBROCK, 'radau5': cj.M_RADAU,
    'kencarp4': cj.M_ESDIRK, 'trbdf2': cj.M_ESDIRK, 'rosenbrock23': cj.M_ROS23, 'tsit5': cj.M_TSIT5,
    'vern7': cj.M_VERN7, 'auto': None, 'auto_julia': None}

#: The default algorithm's methods, by its numbering (``DEFAULT_CHOICES``), as families.
CHOICE_METHODS = (cj.M_TSIT5, cj.M_VERN7, cj.M_ROS23, cj.M_ROSENBROCK, cj.M_FBDF, cj.M_FBDF)


def why_python(solver_id: str, opts: Dict[str, Any]) -> Optional[str]:
    """Why a run of ``solver_id`` keeps the Python solver's own loop, or None."""
    if solver_id not in METHODS:
        return 'the compiled loop does not take this method'
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


def _coefficients(method: int, cache: Any) -> np.ndarray:
    """The stiff (or only) method's numbers in the layout :mod:`.julia` reads
    (``coef``), from the Python solver's own cache."""
    if method == cj.M_ROSENBROCK:
        tab = cache.tab
        s, nh = tab.stages, len(tab.H)
        a = np.zeros((s, s))
        C = np.zeros((s, s))
        for i in range(s):
            a[i, :len(tab.a[i])] = tab.a[i]
            C[i, :len(tab.C[i])] = tab.C[i]
        return np.concatenate([[s, nh, tab.gamma], a.ravel(), C.ravel(), tab.c, tab.d, tab.b, tab.btilde,
                               np.asarray(tab.H, dtype=float).ravel()]).astype(float)
    if method == cj.M_ESDIRK:
        tab = cache.tab
        s = tab.stages
        alpha = np.zeros((s, s))
        for i in range(s):
            alpha[i, :len(tab.alpha[i])] = tab.alpha[i]
        return np.concatenate([[s, tab.gamma, 1.0 if cache.smooth_est else 0.0],
                               np.asarray(tab.a, dtype=float).ravel(), tab.b, tab.btilde, tab.c,
                               alpha.ravel()]).astype(float)
    if method == cj.M_FBDF:
        from ..solvers.julia.methods.fbdf import BDF_COEFFS
        table = np.zeros((cj.FB_STRIDE, cj.FB_STRIDE))
        for k, row in enumerate(BDF_COEFFS):
            if row is not None:
                table[k, :len(row)] = row
        return table.ravel()
    if method == cj.M_QNDF:
        from ..solvers.julia.methods.qndf import GAMMA
        return np.concatenate([np.asarray(cache.kappa[:5], dtype=float), GAMMA, cache.U]).astype(float)
    if method == cj.M_RADAU:
        tab = cache.tab
        return np.array([getattr(tab, name) for name in cj.RADAU_COEFFICIENTS], dtype=float)
    # Rosenbrock23's are the module's own; the explicit methods' are apart (_explicit_tables).
    return np.zeros(1)


def _method_state(method: int, cache: Any) -> Any:
    """The method's floats and integers as a run starts them (cpar and ipar
    after the shared ones), from the Python solver's own cache."""
    if method == cj.M_FBDF:
        fbv = np.zeros(cj.NFB)
        fbv[[cj.FB_TERKM2, cj.FB_TERKM1, cj.FB_TERK, cj.FB_TERKP1, cj.FB_TERKM3, cj.FB_NEXT_TERK]] = (
            cache.terkm2, cache.terkm1, cache.terk, cache.terkp1, cache.terkm3, cache.next_terk)
        fbv[[cj.FB_GAMMA, cj.FB_QMAX, cj.FB_QMIN, cj.FB_QSTEADY_MIN, cj.FB_QSTEADY_MAX, cj.FB_MAX_ORDER]] = (
            cache.gamma_ctrl, cache.qmax, cache.qmin, cache.qsteady_min, cache.qsteady_max, cache.max_order)
        fbi = np.zeros(cj.NFI, dtype=np.int64)
        fbi[[cj.FI_ORDER, cj.FI_PREV_ORDER, cj.FI_N_HISTORY, cj.FI_QWAIT, cj.FI_NCONSTEPS, cj.FI_CONSFAIL,
             cj.FI_FROM_EVENT, cj.FI_PENDING, cj.FI_NEXT_ORDER, cj.FI_MIN_ORDER, cj.FI_KRYLOV,
             cj.FI_KRYLOV_FRESH]] = (
            cache.order, cache.prev_order, cache.n_history, cache.qwait, cache.nconsteps, cache.consfailcnt,
            cache.iters_from_event, cache.prev_order_pending, cache.next_order, cache.min_order,
            cache.krylov is not None, cache.krylov_fresh)
        return fbv, fbi
    if method == cj.M_QNDF:
        qnv = np.zeros(cj.NQN)
        qnv[[cj.QN_DTPREV, cj.QN_EEST1, cj.QN_EEST2, cj.QN_GAMMA, cj.QN_QMAX, cj.QN_QMIN, cj.QN_QSTEADY_MIN,
             cj.QN_QSTEADY_MAX, cj.QN_MAX_ORDER]] = (
            cache.dtprev, cache.eest1, cache.eest2, cache.gamma_ctrl, cache.qmax, cache.qmin, cache.qsteady_min,
            cache.qsteady_max, cache.max_order)
        qni = np.zeros(cj.NQI, dtype=np.int64)
        qni[[cj.QI_ORDER, cj.QI_PREV_ORDER, cj.QI_NCONSTEPS, cj.QI_CONSFAIL, cj.QI_STARTED, cj.QI_MIN_ORDER]] = (
            cache.order, cache.prev_order, cache.nconsteps, cache.consfailcnt, cache.started, cache.min_order)
        return qnv, qni
    if method == cj.M_RADAU:
        rav = np.zeros(cj.NRA)
        rav[[cj.RA_DTPREV, cj.RA_COMPLEX_DT, cj.RA_ETA_OLD, cj.RA_KAPPA, cj.RA_CUTOFF]] = (
            cache.dtprev, cache.complex_dt, cache.eta_old, cache.kappa, cache.fast_convergence_cutoff)
        rai = np.zeros(cj.NRI, dtype=np.int64)
        statuses = {'Convergence': cj.RS_CONVERGENCE, 'FastConvergence': cj.RS_FAST, 'Divergence': cj.RS_DIVERGENCE}
        rai[[cj.RI_COMPLEX_VALID, cj.RI_HAVE_HISTORY, cj.RI_STATUS, cj.RI_MAX_ITERS, cj.RI_SMOOTH]] = (
            cache.complex_valid, cache.have_history, statuses[cache.status], cache.max_iters, cache.smooth_est)
        return rav, rai
    return np.zeros(0), np.zeros(0, dtype=np.int64)


def _controller(pi: Any) -> np.ndarray:
    """A ``PIController``'s numbers as the loop holds them (``PC_``)."""
    pc = np.zeros(cj.NPC)
    pc[[cj.PC_BETA1, cj.PC_BETA2, cj.PC_GAMMA, cj.PC_QMIN, cj.PC_QMAX, cj.PC_QSTEADY_MIN, cj.PC_QSTEADY_MAX,
        cj.PC_QOLDINIT, cj.PC_ERROLD, cj.PC_QMAX_FIRST]] = (
        pi.beta1, pi.beta2, pi.gamma, pi.qmin, pi.qmax, pi.qsteady_min, pi.qsteady_max, pi.qoldinit, pi.errold,
        pi.qmax_first_step)
    return pc


def _explicit_tables(method: int) -> Tuple[np.ndarray, np.ndarray]:
    """The explicit method's tableau as :func:`.julia._explicit_tables` reads
    it: Tsit5's a, c, btilde and interpolant, padded to rows of 7 and 4;
    Vern7's rows of nonzero terms in the source's order (``Vern7Cache``'s),
    c, the interpolation stages' c, and the interpolant."""
    from ..solvers.julia.methods.tableaus import TSIT5, VERN7
    if method == cj.M_TSIT5:
        a = np.zeros((7, 7))
        for i, row in enumerate(TSIT5.a):
            a[i, :len(row)] = row
        interp = np.zeros((7, 4))
        for j, row in enumerate(TSIT5.interp):
            interp[j, :len(row)] = row
        return (np.concatenate([a.ravel(), TSIT5.c, TSIT5.btilde, interp.ravel()]).astype(float),
                np.zeros(1, dtype=np.int64))
    if method == cj.M_VERN7:
        from ..solvers.julia.methods.vern7 import _terms
        rows = [_terms(row) for row in VERN7.a] + [_terms(VERN7.b), _terms(VERN7.btilde)]
        rows += [_terms(row) for row in VERN7.extra_a]
        ptr = [0]
        for r in rows:
            ptr.append(ptr[-1] + len(r))
        vj = [j for r in rows for j, _ in r]
        vv = [v for r in rows for _, v in r]
        stages = list(VERN7.interp_stages)
        ip = [0]
        for r in VERN7.interp:
            ip.append(ip[-1] + len(r))
        iv = [v for r in VERN7.interp for v in r]
        eint = np.array([len(vj), len(iv), len(stages)] + ptr + vj + stages + ip, dtype=np.int64)
        ecoef = np.array(vv + list(VERN7.c) + list(VERN7.extra_c) + iv, dtype=float)
        return ecoef, eint
    return np.zeros(1), np.zeros(1, dtype=np.int64)


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
        self.hand = np.zeros(n)
        # `auto` hands the stiff part of a span to the NDF, compiled: a run of
        # its own over the same model, made the first time it is needed and
        # collecting the steps into the same arrays.
        self.solver_points = solver_points
        self.ndf: Any = None

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
        if self.solver_id == 'auto':
            return self._auto(grid, t0, tf, y0)
        return self._compiled(grid, t0, tf, y0, variant, run_id)[0]

    def _compiled(self, grid: np.ndarray, t0: float, tf: float, y0: np.ndarray, variant: Any, run_id: str,
                  corners: Any = None) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """The compiled loop over one span, failures turned as the adapter
        turns them: the adapter's answer, and where it handed off (or None)."""
        try:
            with np.errstate(all='ignore'):
                return self._span(grid, t0, tf, y0, variant, run_id, corners)
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

    def _algorithm(self, run_opts: Dict[str, Any], variant: Any) -> Any:
        """The package's method for this run, as the adapter makes it."""
        from ..solvers.julia.adapter import ALGORITHMS, HANDED_OFF_METHODS
        from ..solvers.julia.methods import DefaultODEAlgorithm
        if self.solver_id == 'auto':
            return DefaultODEAlgorithm(hand_off=HANDED_OFF_METHODS)
        if self.solver_id == 'auto_julia':
            carry = self.opts.get('carry')
            return DefaultODEAlgorithm(stiffalgfirst=carry is not None and carry.get('stiff') is True)
        return (variant[1] if variant else ALGORITHMS[self.solver_id])()

    def _span(self, grid: np.ndarray, t0: float, tf: float, y0: np.ndarray, variant: Any, run_id: str,
              corners: Any) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        from ..solvers.julia._js import js_string, to_exponential
        from ..solvers.julia.adapter import EXPLICIT_TOLERANCE, _jacobian_for, _scaled
        from ..solvers.julia.integrator import DEFAULTS, Integrator, ODEProblem
        from ..solvers.julia.methods.default import STABILITY_SIZES, _nonstiff_choice, _stiff_choice
        opts, cm, system = self.opts, self.cm, self.system
        saveat = [t0, tf] if opts.get('ends_only') else [float(v) for v in grid]
        jacobian = self.jacobian
        pattern = jacobian['pattern'] if jacobian else None
        problem = ODEProblem(cm.derivative, np.asarray(y0, dtype=float), (t0, tf), jac=_jacobian_for(jacobian),
                             jac_pattern=(pattern.col_ptr, pattern.row_idx) if pattern is not None else None)
        run_opts = dict(DEFAULTS)
        run_opts.update(settings_of(opts, saveat))
        if self.solver_id == 'auto':
            # The explicit start at a tenth of the tolerances, landing on the
            # corners of the clock-read tables (the adapter's `auto`).
            run_opts['reltol'] = run_opts['reltol'] * EXPLICIT_TOLERANCE
            run_opts['abstol'] = _scaled(run_opts['abstol'], EXPLICIT_TOLERANCE)
            if corners is not None and len(corners):
                run_opts['tstops'] = list(corners)
        n = problem.n
        if not (n > 0):
            raise SolverError('span', 'The initial state is empty', t0)
        if not math.isfinite(t0) or not math.isfinite(tf):
            raise SolverError('span', 'The time span must be finite', t0)
        alg = self._algorithm(run_opts, variant)
        integ = Integrator(problem, alg, run_opts)
        self.integ = integ
        cache, newton = integ.cache, integ.newton
        composite = bool(integ.is_composite)

        # The methods: one, or the composite's two, fixed by the tolerance and
        # the size of the system before it starts (``default_autoswitch``).
        fpar = np.zeros(cj.NFP)
        ipar = np.zeros(cj.NIP, dtype=np.int64)
        pcs = np.zeros((2, cj.NPC))
        if composite:
            reltol = integ.reltol
            choices = (_nonstiff_choice(reltol), _stiff_choice(reltol, n))
            state = cache.state
            first = 1 if state.stiffalgfirst else 0
            subs = [cache.ensure(c, integ) for c in choices]
            for slot, c in enumerate(choices):
                pcs[slot] = _controller(cache.controllers[c])
            methods = [CHOICE_METHODS[c] for c in choices]
            hand = sum(1 << slot for slot, c in enumerate(choices) if cache.algs[c].name in cache.hand_off)
            if hand & (1 << first):
                # Started on a method it hands off, which the adapter never asks for.
                raise RuntimeError('a composite that hands off the method it starts on')
            stiff_cache = subs[1]
            ipar[[cj.IP_COMPOSITE, cj.IP_STIFF, cj.IP_FIRST, cj.IP_HAND_OFF, cj.IP_STIFFALGFIRST, cj.IP_STILL]] = (
                1, methods[1], first, hand, state.is_stiff_alg, integ.still_is_stiff)
            fpar[[cj.FP_NONSTIFFTOL, cj.FP_STIFFTOL, cj.FP_DTFAC, cj.FP_STABILITY, cj.FP_MAXSTIFFSTEP,
                  cj.FP_MAXNONSTIFFSTEP, cj.FP_SWITCH_MAX]] = (
                state.nonstifftol, state.stifftol, state.dtfac, STABILITY_SIZES[choices[0]], state.maxstiffstep,
                state.maxnonstiffstep, state.switch_max)
            mcode0, order = methods[0], subs[first].order
            stiff_method = methods[1]
            explicit_only = bool(hand & 2) or (stiff_method == cj.M_FBDF and stiff_cache.krylov is not None)
            choice_names = [cache.algs[c].name for c in choices]
        else:
            mcode0 = METHODS[self.solver_id]
            stiff_method = mcode0
            stiff_cache = cache
            pcs[0] = _controller(integ.controller)
            order = cache.order
            explicit_only = mcode0 in (cj.M_TSIT5, cj.M_VERN7) or (mcode0 == cj.M_FBDF and cache.krylov is not None)
            choice_names = []
        ipar[cj.IP_METHOD] = mcode0

        # J, W and the colouring: the Python solver's own, where the run can
        # form a matrix at all.
        if explicit_only:
            jc = W = None
            none_i = np.zeros(0, dtype=np.int64)
            gptr, gcols, eptr, erow, ewhich, eent = np.zeros(1, dtype=np.int64), none_i, np.zeros(1, dtype=np.int64), \
                none_i, none_i, none_i
            sparse = False
            jd, jv = np.zeros((1, 1)), np.zeros(1)
            wf, wv, j_to_w, diag_w = np.zeros((1, 1)), np.zeros(1), none_i, none_i
            jrow = none_i
            max_age = 20.0
        else:
            jc, W = integ.jac_cache, integ.W
            gptr, gcols, eptr, erow, ewhich, eent = _plan(jc, n)
            sparse = bool(jc.sparse)
            jd = jc.J if jc.J is not None else np.zeros((1, 1))
            jv = jc.values if jc.values is not None else np.zeros(1)
            none_i = np.zeros(0, dtype=np.int64)
            wf = W.W if not W.sparse else np.zeros((1, 1))
            wv = W.w_values if W.sparse else np.zeros(1)
            j_to_w = W.j_to_w if W.sparse else none_i
            diag_w = W.diag_w if W.sparse else none_i
            jrow = (np.ascontiguousarray(jc.pattern[1], dtype=np.int64) if (composite and jc.sparse)
                    else np.zeros(0, dtype=np.int64))
            max_age = W.max_age

        # Where the rows are saved, and the times landed on, as the integrator sorts them.
        tdir = integ.tdir
        times = sorted((float(v) for v in run_opts['saveat']), reverse=tdir < 0)
        at = 0
        while at < len(times) and tdir * (times[at] - t0) < 0:
            at += 1
        tstops = run_opts['tstops'] or []
        tstops = [v for v in sorted((float(v) for v in tstops), reverse=tdir < 0) if tdir * (v - t0) > 0]
        max_steps = run_opts['max_steps'] if run_opts['max_steps'] > 0 else run_opts['maxiters']
        below_tol_max = max(0, int(math.floor(float(run_opts['below_tol_run'] or 0) + 0.5)))
        mv, mi = _method_state(stiff_method, stiff_cache)
        fpar[[cj.FP_RTOL, cj.FP_T0, cj.FP_TF, cj.FP_DTMAX, cj.FP_DT, cj.FP_MAX_STEPS, cj.FP_MAX_AGE, cj.FP_KAPPA,
              cj.FP_CUTOFF]] = (integ.reltol, t0, tf, run_opts['dtmax'], run_opts['dt'], max_steps, max_age,
                                newton.kappa, newton.fast_convergence_cutoff)
        ipar[[cj.IP_BELOW_TOL, cj.IP_STORE, cj.IP_PROGRESS, cj.IP_SAVEAT_AT, cj.IP_ORDER, cj.IP_AUTO_ABSTOL,
              cj.IP_NEWTON_MAX_ITERS, cj.IP_INITDT]] = (
            below_tol_max, cm.has_store, self._progress_cb is not None, at, order, integ.auto_abstol,
            newton.max_iters, getattr(alg, 'initdt', None) == 'sciml')
        cpar = np.concatenate([pcs.ravel(), mv]).astype(float)
        fl = np.array([self._jac_cb is not None, sparse, run_opts['norm'] == 'max'], dtype=np.int64)
        ecoef, eint = _explicit_tables(mcode0)
        # The integrator's own tolerance, which the loop raises in place under
        # auto_abstol (a copy the Integrator made: the run's is never touched).
        atol = _floats(integ.abstol, n)
        nn = (np.ascontiguousarray(integ.non_negative, dtype=np.int64) if integ.non_negative is not None
              else np.zeros(0, dtype=np.int64))
        rows = len(times) + 1
        tout = np.zeros(rows)
        yout = np.zeros((rows, n))
        stats = np.zeros(cj.NC + cj.NSO, dtype=np.int64)
        fstat = np.zeros(3)
        cm.W[0] = math.nan
        status = cj.julia(
            cm.rhs, cm.store, self.evf, self._jac_cb or no_callback, self._progress_cb or no_callback,
            self._factor_cb, self._solve_cb, system.P, system.X, cm.W, cm.IW, cm.py_callback,
            np.array(times, dtype=float), np.ascontiguousarray(y0, dtype=float), atol, _floats(run_opts['abstol'], n),
            nn, _coefficients(stiff_method, stiff_cache), fpar, cpar, np.concatenate([ipar, mi]), fl,
            jd, jv, gptr, gcols, eptr, erow, ewhich, eent, self.ybuf, wf, wv, j_to_w, diag_w, self.rbuf, self.xbuf,
            self.evdir, self.evbuf, self.evy, self.evwhich, self.evstat, tout, yout, stats, fstat, self.pbuf,
            self.ct, self.cy, self.cint, self.cflt, np.array(tstops, dtype=float), ecoef, eint, jrow, self.hand)

        if status == cj.E_HISTORY:
            raise HistoryFull()
        if status == cj.E_CALLBACK:
            raise _adapted(self._callback_error(), t0)
        if status == cj.E_ZERO_DIVISION:
            raise SolverError('failed', 'float division by zero', t0)
        if status == cj.E_INITIAL:
            raise SolverError('nonfinite', f'The state or its derivative is not a number at t = {js_string(t0)} '
                                           f'(component {int(fstat[2])})', t0)
        kept = int(stats[cj.NC + cj.SO_ROWS])
        last_t = float(tout[kept - 1]) if kept else t0
        out_by = stats[cj.NC:]
        # The switching solver goes on with the method it ended on (the carry, as the adapter keeps it).
        carry = self.opts.get('carry')
        if composite and carry is not None and self.solver_id == 'auto_julia':
            from ..solvers.julia.adapter import STIFF_METHODS
            carry['stiff'] = choice_names[int(out_by[cj.SO_SLOT])] in STIFF_METHODS
        if composite and carry is not None and status == cj.R_HANDED_OFF:
            carry['ndf'] = True
        if status == cj.R_STOPPED:
            raise SolverError('aborted', 'Simulation aborted', last_t)
        if status not in (cj.OK, cj.R_HANDED_OFF):
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
        # W, where the run formed one: the integrator reports its sparsity and
        # fill only then, as it makes it only then.
        formed = W is not None and bool(out_by[cj.SO_W])
        result_stats: Dict[str, Any] = {
            'nsteps': int(stats[cj.C_NSTEPS]),
            'nfailed': int(stats[cj.C_NREJECT]),
            'nfevals': int(stats[cj.C_NF]),
            'npds': int(stats[cj.C_NJAC]),
            'ndecomps': int(stats[cj.C_NFACTOR]),
            'nsolves': int(stats[cj.C_NSOLVE]) + int(out_by[cj.SO_KSOLVES]),
            'solver': run_id,
            'sparse': bool(W.sparse) if formed else False,
            'fill': W.fill if formed else None,
        }
        krylov_built = stiff_method == cj.M_FBDF and stiff_cache.krylov is not None
        if composite:
            built = int(out_by[cj.SO_BUILT])
            by = {}
            for slot, name in enumerate(choice_names):
                if built & (1 << slot):
                    by[name] = int(out_by[cj.SO_STEPS0 + slot])
            result_stats['steps_by'] = by
            result_stats['switches'] = int(out_by[cj.SO_SWITCHES])
            krylov_built = krylov_built and bool(built & 2)
        if krylov_built:
            result_stats['krylov_iters'] = int(out_by[cj.SO_KITERS])
        out = {
            't': tout[:kept].copy(),
            'y': [yout[i].copy() for i in range(kept)],
            'stopped': stopped,
            'stats': result_stats,
        }
        handed = None
        if status == cj.R_HANDED_OFF:
            handed = {'t': float(fstat[0]), 'u': self.hand.copy()}
        return out, handed

    # --- `auto`: the explicit start, and the NDF from where the run turns stiff ----------------------------

    def _ndf_part(self, grid: np.ndarray, t0: float, tf: float, t1: float, y1: np.ndarray,
                  steps_before: int) -> Dict[str, Any]:
        """The adapter's ``ndf_part`` on the compiled NDF: over the requested
        times from ``t1`` on, starting from ``y1``, with what the first part
        left of the step budget and progress as a fraction of the whole span."""
        from ..solvers.julia._js import jmin
        from ..solvers.julia.adapter import _positive
        opts = self.opts
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
        if self.ndf is None:
            from .run import CompiledRun
            self.ndf = CompiledRun(self.system, self.cm, 'ndf', opts, self.solver_points)
            self.ndf.ct, self.ndf.cy, self.ndf.cint, self.ndf.cflt = self.ct, self.cy, self.cint, self.cflt
        ndf = self.ndf
        ndf.opts = sub
        try:
            return ndf._ndf(np.array(times, dtype=float), np.asarray(y1, dtype=float))
        except CompiledFailure as e:
            # Where the model's own equations raise on the Python path: the
            # same exception, at the same evaluation (``CompiledRun``).
            raised = self.cm.python_error() if e.args and int(e.args[0]) == FAIL_PYTHON else None
            if raised is not None:
                self.cm.py_callback.error = None
                raise raised from None
            raise python_error(e) from None
        finally:
            ndf.opts = opts

    def _auto(self, grid: np.ndarray, t0: float, tf: float, y0: np.ndarray) -> Dict[str, Any]:
        """The adapter's ``auto``: the NDF from the start where the run has
        turned stiff or its tables turn too often, else the explicit start
        and, where it hands off, the NDF for the rest, the two put together."""
        from ..solvers.julia.adapter import MAX_CORNERS
        opts = self.opts
        carry = opts.get('carry')
        table_corners = opts.get('table_corners')
        corners = table_corners(t0, tf, MAX_CORNERS) if table_corners is not None else []
        if (carry is not None and carry.get('ndf')) or corners is None:
            if carry is not None:
                carry['ndf'] = True
            r = self._ndf_part(grid, t0, tf, t0, np.array(y0, dtype=float), 0)
            st = r['stats']
            return {
                't': r['t'], 'y': r['y'], 'stopped': r['stopped'],
                'stats': {**st, 'nsteps': st['nsteps'] + st['nfailed'], 'solver': 'auto',
                          'steps_by': {'BDF' if opts.get('bdf') else 'NDF': st['nsteps']}, 'switches': 0},
            }
        out, handed = self._compiled(grid, t0, tf, y0, None, 'auto', corners)
        if handed is None:
            return out
        stats = out['stats']
        r = self._ndf_part(grid, t0, tf, handed['t'], handed['u'], stats['nsteps'])
        b = r['stats']
        rows = list(out['y'])
        rows.extend(r['y'][1:])
        return {
            't': np.concatenate([out['t'], np.asarray(r['t'], dtype=float)[1:]]),
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


__all__: Sequence[str] = ('METHODS', 'JuliaRun', 'settings_of', 'why_python')
