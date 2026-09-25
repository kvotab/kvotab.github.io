"""The loop every method runs inside (``core/integrator.js``).

Propose a step, judge it, save what it passed, look for an event, choose the
next one. A method contributes a cache with ``init``, ``step``, ``accepted``
and, where it has them, ``rejected``, ``restart`` and ``interpolate``;
everything else -- the Jacobian, W, the Newton iteration, the controller,
saving, event location, the floor on the step -- is here.

What the adapter never asks for is not ported: dense output kept for later,
``maxPoints`` thinning and a ``history`` to start a multistep method at full
order. Everything the adapter can reach is.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from ._js import EPS, INF, MIN_VALUE, jmax, jmin, js_string, max_or_zero, seq_sum, to_exponential, ulp
from .controller import PIController, initial_step
from .jacobian import JacobianCache, WFactorization
from .newton import NewtonSolver

SUCCESS = 'Success'
MAX_ITERS = 'MaxIters'
DT_LESS_THAN_MIN = 'DtLessThanMin'
UNSTABLE = 'Unstable'
TERMINATED = 'Terminated'
CONVERGENCE_FAILURE = 'ConvergenceFailure'


class ODEError(Exception):
    """A problem that cannot be integrated at all (``ODEError``)."""

    def __init__(self, code: str, message: str, t: Optional[float]) -> None:
        super().__init__(message)
        self.code = code
        self.t = t


class ODEProblem:
    """u' = f(t, u) on [t0, tf] (``ODEProblem``). ``f(t, u)`` returns du."""

    def __init__(self, f: Callable[[float, np.ndarray], np.ndarray], u0: Any, tspan: Any,
                 jac: Optional[Callable[..., bool]] = None, jac_pattern: Any = None, events: Any = None,
                 tgrad: Optional[Callable[[float, np.ndarray], np.ndarray]] = None) -> None:
        self.f = f
        self.u0 = np.array(u0, dtype=float)
        self.tspan = (float(tspan[0]), float(tspan[1]))
        self.jac = jac
        self.tgrad = tgrad
        self.jac_pattern = jac_pattern
        self.events = events
        self.n = int(self.u0.size)


class ODESolution:
    def __init__(self, t: List[float], u: List[np.ndarray], stats: Dict[str, Any], retcode: str,
                 message: str) -> None:
        self.t = t
        self.u = u
        self.stats = stats
        self.retcode = retcode
        self.message = message or ''
        self.events: List[Dict[str, Any]] = []


DEFAULTS: Dict[str, Any] = {
    'reltol': 1e-3,
    'abstol': 1e-6,
    'dtmax': INF,
    'dtmin': 0.0,
    'dt': 0.0,
    'maxiters': 1e7,
    'max_steps': 0,
    'save_everystep': True,
    'saveat': None,
    'progress': None,
    'progress_every': 64,
    'on_accepted': None,
    'on_output': None,
    'matrix': 'auto',
    'norm': 'rms',
    'central': False,
    'unstable_check': True,
    'adaptive': True,
    'tstops': None,
    'max_events': 1000,
    'max_order': 0,
    'min_order': 0,
    'max_jac_age': 20,
    'kappa': None,
    'newton_max_iters': None,
    'non_negative': None,
    'auto_abstol': False,
    'below_tol_run': 0,
}


class Integrator:
    """Everything one integration needs, handed to the method's cache."""

    def __init__(self, prob: ODEProblem, alg: Any, opts: Dict[str, Any]) -> None:
        n = prob.n
        self.n = n
        self.prob = prob
        self.opts = opts
        self.reltol = opts['reltol']
        self.abstol = opts['abstol']
        self.auto_abstol = bool(opts['auto_abstol'])
        if self.auto_abstol:
            ab = opts['abstol']
            self.abstol = np.full(n, float(ab)) if np.ndim(ab) == 0 else np.array(ab, dtype=float)
        self.abstol_fixed = opts['abstol']
        self.t = prob.tspan[0]
        self.tf = prob.tspan[1]
        diff = self.tf - self.t
        self.tdir = 1.0 if diff > 0 else (-1.0 if diff < 0 else 1.0)
        self.uprev = prob.u0.copy()
        self.u = prob.u0.copy()
        self.fsalfirst = np.zeros(n)
        self.fsallast = np.zeros(n)
        self.eest = 1.0
        self.dt = 0.0
        self.nsteps = 0
        nn = opts['non_negative']
        self.non_negative: Optional[np.ndarray] = None
        if nn is not None and nn is not False:
            self.non_negative = (np.ones(n, dtype=bool) if nn is True
                                 else np.array([bool(v) for v in nn], dtype=bool))
        self.stats: Dict[str, Any] = {
            'nf': 0, 'njacs': 0, 'nw': 0, 'nsolve': 0, 'nsteps': 0, 'naccept': 0, 'nreject': 0,
            'nnonlinconvfail': 0, 'nnonliniter': 0, 'nbelowtol': 0, 'maxOrder': 0, 'points': 0, 'stride': 1,
            'sparse': False, 'fill': None, 'ordering': 'none', 'alg': alg.name,
        }
        self.jac_cache = JacobianCache(n, prob.jac, prob.jac_pattern, opts['matrix'], opts['central'])
        self.W = WFactorization(n, self.jac_cache, opts['max_jac_age'])
        self.newton = NewtonSolver(n, norm=opts['norm'], kappa=opts['kappa'], max_iters=opts['newton_max_iters'])
        self.stats['sparse'] = self.W.sparse
        self.stats['ordering'] = self.W.ordering
        self.cache = alg.build(n, self, opts)
        order = self.cache.error_order if self.cache.error_order is not None else self.cache.order
        self.controller = PIController(order, **(alg.controller or {}))

    def f(self, t: float, u: np.ndarray) -> np.ndarray:
        self.stats['nf'] += 1
        return np.array(self.prob.f(t, u), dtype=float)

    def clamp(self, u: np.ndarray) -> int:
        nn = self.non_negative
        if nn is None:
            return 0
        hit = nn & (u < 0)
        u[hit] = 0.0
        return int(np.count_nonzero(hit))

    def weights(self) -> np.ndarray:
        """atol + rtol*max(|uprev|, |u|), for the step just taken."""
        return self.abstol + self.reltol * np.maximum(np.abs(self.uprev), np.abs(self.u))

    def error_norm(self, e: np.ndarray) -> float:
        """In the integrator's norm; a component that is not a number makes it NaN."""
        w = self.weights()
        if self.opts['norm'] == 'max':
            return max_or_zero(np.abs(e / w))
        r = e / w
        return math.sqrt(seq_sum(r * r) / self.n)

    def form_w(self, gamma_dt: float, transform: bool, force_jac: bool = False) -> bool:
        ok = self.W.form(self.f, self.t, self.uprev, self.fsalfirst, gamma_dt, transform, force_jac)
        self.stats['njacs'] = self.jac_cache.njac
        self.stats['nw'] = self.W.nfactor
        return ok

    def solve_w(self, b: np.ndarray) -> np.ndarray:
        self.stats['nsolve'] += 1
        return self.W.solve(b)


def _report_progress(integ: Integrator, opts: Dict[str, Any]) -> bool:
    progress = opts['progress']
    if progress is None:
        return True
    if integ.nsteps % opts['progress_every'] != 0:
        return True
    return progress(integ.t, integ.nsteps) is not False


def hermite(theta: float, dt: float, uprev: np.ndarray, u: np.ndarray, f0: np.ndarray,
            f1: np.ndarray) -> np.ndarray:
    """Cubic Hermite through (t, uprev, f0) and (t + dt, u, f1)."""
    t2 = theta * theta
    t3 = t2 * theta
    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + theta
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2
    return h00 * uprev + h10 * dt * f0 + h01 * u + h11 * dt * f1


def _direction_of(ev: Any, i: int) -> float:
    """The direction asked of event function ``i``: one number for all, or one each."""
    d = getattr(ev, 'direction', None)
    if d is None:
        return 1.0
    if isinstance(d, (int, float, np.integer, np.floating)):
        return float(d)
    try:
        v = d[i]
    except (IndexError, TypeError):
        return 1.0
    return 1.0 if v is None else float(v)


def _locate_root(integ: Integrator, eval_at: Callable[[float], np.ndarray], ev: Any, which: int,
                 g_start: float) -> float:
    """Where in the step, as theta, event function ``which`` crosses zero:
    bisection then Illinois on the step's interpolant (``locateRoot``)."""
    def g(theta: float) -> float:
        u = eval_at(theta)
        return float(np.asarray(ev.fun(integ.t + theta * integ.dt, u), dtype=float)[which])

    lo = 0.0
    hi = 1.0
    flo = float(g_start)
    fhi = g(1.0)
    it = 0
    while it < 60 and hi - lo > 1e-14:
        denom = fhi - flo
        mid = 0.5 * (lo + hi) if denom == 0 else lo - flo * (hi - lo) / denom
        if not (lo < mid < hi):
            mid = 0.5 * (lo + hi)
        fmid = g(mid)
        if fmid == 0:
            lo = hi = mid
            break
        if (fmid < 0) == (flo < 0):
            lo = mid
            flo = fmid
            fhi *= 0.5
        else:
            hi = mid
            fhi = fmid
            flo *= 0.5
        it += 1
    # The bracket's far end, where the function has crossed: a run restarted
    # from the middle could start a hair short of the crossing and find it
    # again (``locateRoot`` explains).
    return hi


def _root_at_start(integ: Integrator, t_event: float) -> bool:
    """A root at the instant the solve began is not a crossing (``rootAtStart``)."""
    t0 = integ.prob.tspan[0]
    return abs(t_event - t0) <= 16 * EPS * jmax(abs(t0), abs(integ.dt))


def _find_event(integ: Integrator, eval_at: Callable[[float], np.ndarray], g_prev: np.ndarray,
                work: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The earliest crossing inside the step just taken, each function in its
    own direction; functions crossing together are reported together
    (``findEvent``)."""
    ev = integ.prob.events
    if ev is None:
        return None
    g_now = np.array(ev.fun(integ.t + integ.dt, integ.u), dtype=float)
    crossed = []
    for i in range(ev.n):
        a = float(g_prev[i])
        b = float(g_now[i])
        direction = _direction_of(ev, i)
        rising = a < 0 and b >= 0
        falling = a > 0 and b <= 0
        if (direction >= 0 and rising) or (direction <= 0 and falling):
            crossed.append(i)
    if not crossed:
        return None
    found = []
    for which in crossed:
        theta = _locate_root(integ, eval_at, ev, which, float(g_prev[which]))
        t_event = integ.t + theta * integ.dt
        if _root_at_start(integ, t_event):
            continue
        found.append((theta, t_event, which))
    if not found:
        return None
    first = found[0]
    for f in found:
        if f[0] < first[0]:
            first = f
    together = jmax(2e-14 * abs(integ.dt), 16 * EPS * jmax(abs(first[1]), abs(integ.dt)))
    group = [f for f in found if abs(f[1] - first[1]) <= together]
    # Handed back where every one of them has crossed: the latest.
    last = first
    for f in group:
        if f[0] > last[0]:
            last = f
    every = sorted(f[2] for f in group)
    work['u_event'] = eval_at(last[0])
    return {'theta': last[0], 't': last[1], 'which': every[0], 'all': every}


def solve(prob: ODEProblem, alg: Any, options: Optional[Dict[str, Any]] = None) -> ODESolution:
    """Integrate (``solve``)."""
    opts = dict(DEFAULTS)
    opts.update(options or {})
    n = prob.n
    if not (n > 0):
        raise ODEError('empty', 'The initial state is empty', prob.tspan[0])
    t0, tf = prob.tspan
    if not math.isfinite(t0) or not math.isfinite(tf):
        raise ODEError('tspan', 'The time span must be finite', t0)
    if t0 == tf:
        raise ODEError('tspan', 'The time span is empty', t0)

    integ = Integrator(prob, alg, opts)
    tdir = integ.tdir
    span = abs(tf - t0)
    if opts['dtmin'] > 0:
        dtmin_fixed = opts['dtmin']

        def dtmin_at(t: float) -> float:
            return dtmin_fixed
    else:
        def dtmin_at(t: float) -> float:
            return jmax(MIN_VALUE, 16 * ulp(t))
    t_eps = 16 * jmax(ulp(t0), ulp(tf))
    max_steps = opts['max_steps'] if opts['max_steps'] > 0 else opts['maxiters']

    # --- saving --------------------------------------------------------------------------
    T: List[float] = []
    U: List[np.ndarray] = []

    def remember(t: float, u: np.ndarray) -> None:
        T.append(t)
        U.append(np.array(u, dtype=float))

    saveat: Optional[List[float]] = None
    saveat_at = 0
    if opts['saveat'] is not None:
        sa = opts['saveat']
        if isinstance(sa, (int, float)) and not isinstance(sa, bool):
            saveat = []
            tt = t0
            while tdir * (tf - tt) > 0:
                saveat.append(tt)
                tt += tdir * sa
            saveat.append(tf)
        else:
            saveat = sorted((float(v) for v in sa), reverse=tdir < 0)
        while saveat_at < len(saveat) and tdir * (saveat[saveat_at] - t0) < 0:
            saveat_at += 1

    tstops: List[float] = []
    if opts['tstops']:
        tstops = [v for v in sorted((float(v) for v in opts['tstops']), reverse=tdir < 0) if tdir * (v - t0) > 0]
    tstop_at = 0

    # --- start ---------------------------------------------------------------------------
    integ.fsalfirst[:] = integ.f(t0, integ.uprev)
    bad = np.nonzero(~np.isfinite(integ.uprev) | ~np.isfinite(integ.fsalfirst))[0]
    if bad.size:
        raise ODEError('nonfinite', f'The state or its derivative is not a number at t = {js_string(t0)} '
                                    f'(component {int(bad[0])})', t0)
    if hasattr(integ.cache, 'init'):
        integ.cache.init(integ)

    work: Dict[str, Any] = {'utmp': np.zeros(n)}
    g_prev = None

    if not opts['adaptive'] and not opts['dt']:
        raise ODEError('dt', 'A non-adaptive run needs an explicit dt', t0)
    if opts['dt']:
        dt = abs(opts['dt']) * tdir
    else:
        dt = initial_step(integ.f, t0, integ.uprev, integ.fsalfirst, tdir, integ.cache.order, opts['reltol'],
                          opts['abstol'], opts['dtmax'])
    if not math.isfinite(dt) or dt == 0:
        dt = tdir * jmin(1e-6 * span, opts['dtmax'])
    dt = tdir * jmin(jmin(abs(dt), abs(opts['dtmax'])), span)
    integ.dt = dt

    if saveat is None or (saveat_at < len(saveat) and saveat[saveat_at] == t0):
        remember(t0, integ.uprev)
        if saveat is not None and saveat_at < len(saveat) and saveat[saveat_at] == t0:
            saveat_at += 1
    if prob.events is not None:
        g_prev = np.array(prob.events.fun(t0, integ.uprev), dtype=float)

    retcode = SUCCESS
    message = ''
    events: List[Dict[str, Any]] = []
    below_tol_max = max(0, int(math.floor(float(opts['below_tol_run'] or 0) + 0.5)))
    below_tol_run = 0
    stats = integ.stats
    cache = integ.cache

    def eval_at(theta: float) -> np.ndarray:
        interp = getattr(cache, 'interpolate', None)
        if interp is not None:
            return interp(integ, theta)
        return hermite(theta, integ.dt, integ.uprev, integ.u, integ.fsalfirst, integ.fsallast)

    # --- the loop ------------------------------------------------------------------------
    while tdir * (tf - integ.t) > t_eps:
        if integ.nsteps >= max_steps:
            retcode = MAX_ITERS
            message = f'More than {js_string(max_steps)} steps were needed, and the run stopped at t = ' \
                      f'{js_string(integ.t)}'
            break

        limit = tf
        if tstop_at < len(tstops) and tdir * (tstops[tstop_at] - limit) < 0:
            limit = tstops[tstop_at]
        if tdir * (integ.t + integ.dt - limit) > 0:
            integ.dt = limit - integ.t
        elif tdir * (limit - (integ.t + integ.dt)) <= t_eps:
            integ.dt = limit - integ.t
        dtmin = dtmin_at(integ.t)
        at_floor = abs(integ.dt) <= dtmin
        if at_floor:
            integ.dt = tdir * dtmin
        if integ.t + integ.dt == integ.t:
            retcode = DT_LESS_THAN_MIN
            message = f'The step size fell to {to_exponential(abs(integ.dt), 3)} at t = {js_string(integ.t)}, ' \
                      'which does not change the time at this magnitude'
            break

        ok = cache.step(integ)
        integ.nsteps += 1
        stats['nsteps'] += 1

        if not ok:
            stats['nreject'] += 1
            if not _report_progress(integ, opts):
                retcode = TERMINATED
                message = 'The run was stopped from outside'
                break
            # At the smallest step the clock can represent there is nowhere
            # left to go: the run ends rather than retrying there.
            if at_floor:
                retcode = CONVERGENCE_FAILURE
                message = f'The step could not be taken at t = {js_string(integ.t)} even at ' \
                          f'{to_exponential(abs(integ.dt), 3)}, the smallest the clock can represent: ' \
                          'the equations of its stages could not be solved there'
                break
            integ.dt *= 0.5
            integ.W.mark_stale()
            integ.controller.reset()
            continue

        if opts['unstable_check']:
            bad_at = np.nonzero(~np.isfinite(integ.u))[0]
            if bad_at.size:
                bad = int(bad_at[0])
                stats['nreject'] += 1
                # The candidate is no state; the last accepted one is.
                integ.u[:] = integ.uprev
                integ.dt *= 0.5
                integ.W.mark_stale()
                if abs(integ.dt) < dtmin_at(integ.t):
                    retcode = UNSTABLE
                    message = f'The solution became infinite or not-a-number at t = {js_string(integ.t)} ' \
                              f'(component {bad})'
                    break
                continue

        # An error estimate that is not a number is a step that failed outright.
        if opts['adaptive'] and integ.eest != integ.eest:
            stats['nreject'] += 1
            integ.u[:] = integ.uprev
            if not _report_progress(integ, opts):
                retcode = TERMINATED
                message = 'The run was stopped from outside'
                break
            if at_floor:
                retcode = UNSTABLE
                message = f'The error estimate is not a number at t = {js_string(integ.t)}, even with a step of ' \
                          f'{to_exponential(abs(integ.dt), 3)}, the smallest the clock can represent'
                break
            integ.dt *= 0.5
            integ.W.mark_stale()
            integ.controller.reset()
            continue

        accepted = (not opts['adaptive']) or integ.eest <= 1
        if not accepted and at_floor:
            if below_tol_run < below_tol_max:
                below_tol_run += 1
                stats['nbelowtol'] += 1
                accepted = True
            else:
                retcode = DT_LESS_THAN_MIN
                message = (f'The error test failed at t = {js_string(integ.t)} with a step of '
                           f'{to_exponential(abs(integ.dt), 3)}, the smallest the clock can represent'
                           + (f', {below_tol_max} times in a row' if below_tol_max > 0 else ''))
                break
        if accepted:
            below_tol_run = 0

        if not accepted:
            stats['nreject'] += 1
            rejected = getattr(cache, 'rejected', None)
            handled = rejected(integ) is True if rejected is not None else False
            if not handled:
                integ.dt = integ.controller.reject(integ.eest, integ.dt)
            if not _report_progress(integ, opts):
                retcode = TERMINATED
                message = 'The run was stopped from outside'
                break
            continue

        # --- the step is good ------------------------------------------------------------
        # The event functions and the saved rows are read off the step's own
        # interpolant over the whole step, before an event cuts it short.
        tnew = integ.t + integ.dt
        ev = None
        if prob.events is not None:
            if not cache.has_fsal_last and getattr(cache, 'interpolate', None) is None:
                integ.fsallast[:] = integ.f(tnew, integ.u)
            ev = _find_event(integ, eval_at, g_prev, work)  # type: ignore[arg-type]

        stats['naccept'] += 1
        if integ.non_negative is not None:
            integ.clamp(integ.u)

        if saveat is not None:
            t_end = ev['t'] if ev is not None else tnew
            on_output = opts['on_output']
            while saveat_at < len(saveat) and tdir * (saveat[saveat_at] - t_end) <= 0:
                ts = saveat[saveat_at]
                if tdir * (ts - integ.t) >= 0:
                    theta = 1.0 if integ.dt == 0 else (ts - integ.t) / integ.dt
                    utmp = eval_at(theta)
                    if integ.non_negative is not None:
                        integ.clamp(utmp)
                    remember(ts, utmp)
                    if on_output is not None:
                        on_output(ts, utmp)
                saveat_at += 1

        if ev is not None:
            integ.dt = ev['t'] - integ.t
            integ.u[:] = work['u_event']
            integ.clamp(integ.u)
        if opts['save_everystep'] and saveat is None:
            remember(integ.t + integ.dt, integ.u)
        if opts['on_accepted'] is not None:
            opts['on_accepted'](integ.t + integ.dt, integ.u)
        if integ.auto_abstol:
            want = opts['reltol'] * np.abs(integ.u)
            up = want > integ.abstol
            integ.abstol[up] = want[up]

        dtjust = integ.dt
        integ.t += integ.dt
        if abs(tf - integ.t) <= t_eps:
            integ.t = tf
        elif tstop_at < len(tstops) and abs(tstops[tstop_at] - integ.t) <= 16 * jmax(ulp(integ.t), MIN_VALUE):
            integ.t = tstops[tstop_at]
        integ.uprev[:] = integ.u
        if cache.has_fsal_last:
            integ.fsalfirst[:] = integ.fsallast
        else:
            integ.fsalfirst[:] = integ.f(integ.t, integ.uprev)

        integ.W.age_plus()
        accepted_hook = getattr(cache, 'accepted', None)
        if accepted_hook is not None:
            accepted_hook(integ, dtjust)

        if tstop_at < len(tstops) and tdir * (integ.t - tstops[tstop_at]) >= 0:
            tstop_at += 1

        if prob.events is not None:
            if ev is not None:
                events.append({'t': integ.t, 'u': integ.u.copy(), 'which': ev['which'], 'all': ev['all']})
                if len(events) >= opts['max_events']:
                    retcode = TERMINATED
                    message = f'Stopped after {len(events)} events'
                    break
                apply = getattr(prob.events, 'apply', None)
                if apply is not None:
                    apply(integ.t, integ.u)
                if integ.non_negative is not None:
                    integ.clamp(integ.u)
                integ.uprev[:] = integ.u
                integ.fsalfirst[:] = integ.f(integ.t, integ.uprev)
                integ.W.mark_stale()
                integ.newton.reset()
                integ.controller.reset()
                restart = getattr(cache, 'restart', None)
                if restart is not None:
                    restart(integ)
                remember(integ.t, integ.u)
                if getattr(prob.events, 'terminal', False):
                    retcode = TERMINATED
                    message = 'An event stopped the run'
                    break
            g_prev = np.array(prob.events.fun(integ.t, integ.uprev), dtype=float)

        # --- the next step ---------------------------------------------------------------
        if not opts['adaptive']:
            dtnext = abs(opts['dt']) * tdir if opts['dt'] else dtjust
        elif cache.dtpropose is not None:
            dtnext = cache.dtpropose
        else:
            dtnext = integ.controller.accept(integ.eest, dtjust)
        cache.dtpropose = None
        if not math.isfinite(dtnext) or dtnext == 0:
            dtnext = dtjust
        dtnext = tdir * jmin(abs(dtnext), abs(opts['dtmax']))
        integ.dt = dtnext

        if not _report_progress(integ, opts):
            retcode = TERMINATED
            message = 'The run was stopped from outside'
            break

    if saveat is None and (not T or T[-1] != integ.t):
        remember(integ.t, integ.uprev)

    stats['points'] = len(T)
    stats['stride'] = 1
    stats['njacs'] = integ.jac_cache.njac
    stats['nw'] = integ.W.nfactor
    stats['nsolve'] = integ.W.nsolve
    stats['fill'] = integ.W.fill
    stats['nnonliniter'] = integ.newton.nf
    stats['t'] = integ.t
    sol = ODESolution(T, U, stats, retcode, message)
    sol.events = events
    return sol


def algorithm(name: str, order: float, build: Callable[..., Any], controller: Dict[str, Any]) -> SimpleNamespace:
    """What a solver module hands ``solve``: ``{ name, order, build, controller }``."""
    return SimpleNamespace(name=name, order=order, build=build, controller=controller)
