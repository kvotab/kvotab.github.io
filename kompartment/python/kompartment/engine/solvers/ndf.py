"""The variable-order NDF/BDF integrator: Kompartment's default solver.

A port of ``src/ode/solvers/ndf.js`` -- the numerical differentiation
formulas of orders one to five (Shampine and Reichelt, "The MATLAB ODE
Suite", 1997), with the backward differentiation formulas as the case of
every kappa zero, in backward-difference form with a quasi-constant step. The
three things the application adds beyond the published method are here too:

* ``non_negative`` states are integrated as the projected system -- a state
  at zero whose equation pushes it lower is held there, its Jacobian row with
  it -- and every hold is counted;
* a Jacobian that declines a point is differenced there instead;
* a run that accepts steps but covers none of the interval stops, saying so.

The per-state arithmetic is the application's, element for element; the
linear algebra is LAPACK's or SuperLU's (see :mod:`.matrix`), so results agree
with the application's to the tolerance, not to the last bit.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from ..jacobian import Pattern, colour_columns, difference_increment, difference_jacobian
from . import SolverError
from . import kernels
from .events import locate_crossing
from .matrix import IterationMatrix

EPS = 2.0 ** -52
MAX_ORDER = 5
KAPPA = (-0.185, -1 / 9, -0.0823, -0.0415, 0.0)
GAMMA = (1.0, 3 / 2, 11 / 6, 25 / 12, 137 / 60)
NEWTON_MAX = 4
NEWTON_TOL = 0.3
RATE_LIMIT = 0.9
RATE_FLOOR = 0.02
CONVERGED_FLOOR = 1e-3
SAFETY = 0.8
SAFETY_LOWER = 0.75
SAFETY_HIGHER = 0.7
MAX_GROWTH = 10.0
NEWTON_CUT = 0.25
STALL_WINDOW_STEPS = 2000
STALL_SPAN_FRACTION = 1e-10
MAX_BELOW_TOLERANCE = 20
TRACE_STEPS = 12


def ulp(x: float) -> float:
    a = abs(x)
    if not (a > 0):
        return 5e-324
    return 2.0 ** max(math.floor(math.log2(a)) - 52, -1074)


def step_floor(t: float) -> float:
    return 16 * ulp(t)


def basis_at(s: float, k: int) -> List[float]:
    out = [1.0] * (k + 1)
    for j in range(1, k + 1):
        out[j] = out[j - 1] * ((s + j - 1) / j)
    return out


def _choose(n: int, r: int) -> float:
    v = 1.0
    for i in range(1, r + 1):
        v = (v * (n - r + i)) / i
    return v


def regrid_matrix(k: int, s_end: float, ratio: float) -> List[List[float]]:
    values = [basis_at(s_end - i * ratio, k) for i in range(k + 1)]
    T = []
    for m in range(k + 1):
        row = [0.0] * (k + 1)
        for j in range(m, k + 1):
            acc = 0.0
            for i in range(m + 1):
                acc += (-1 if i % 2 else 1) * _choose(m, i) * values[i][j]
            row[j] = acc
        T.append(row)
    return T


class DifferenceTable:
    """The backward differences of the solution: ``cols[j]`` is ∇^j y_n."""

    def __init__(self, neq: int, max_order: int) -> None:
        self.cols = np.zeros((max_order + 3, neq))

    def start(self, y: np.ndarray, hf: np.ndarray) -> None:
        self.cols[0] = y
        self.cols[1] = hf
        self.cols[2:] = 0.0

    @property
    def y(self) -> np.ndarray:
        return self.cols[0]

    def predict(self, k: int) -> np.ndarray:
        out = self.cols[0].copy()
        for j in range(1, k + 1):
            out += self.cols[j]
        return out

    def history(self, k: int) -> np.ndarray:
        out = np.zeros(self.cols.shape[1])
        for j in range(1, k + 1):
            out += GAMMA[j - 1] * self.cols[j]
        return out

    def advance(self, k: int, d: np.ndarray) -> None:
        c = self.cols
        c[k + 2] = d - c[k + 1]
        c[k + 1] = d
        for j in range(k, -1, -1):
            c[j] += c[j + 1]

    def rescale(self, k: int, ratio: float) -> None:
        self.regrid(k, 0.0, ratio)

    def regrid(self, k: int, s_end: float, ratio: float) -> None:
        T = regrid_matrix(k, s_end, ratio)
        c = self.cols
        for m in range(k + 1):
            row = T[m]
            tmp = np.zeros(c.shape[1])
            for j in range(m, k + 1):
                w = row[j]
                if w == 0:
                    continue
                tmp += w * c[j]
            c[m] = tmp

    def value_at(self, k: int, s: float, clamp: Optional[np.ndarray]) -> np.ndarray:
        b = basis_at(s, k)
        out = self.cols[0].copy()
        for j in range(1, k + 1):
            out += b[j] * self.cols[j]
        if clamp is not None and clamp.size:
            sub = out[clamp]
            out[clamp] = np.where(sub < 0, 0.0, sub)
        return out

    def forget(self, i: Any) -> None:
        self.cols[1:, i] = 0.0


def _seq_sum_squares(v: np.ndarray) -> float:
    if v.size == 0:
        return 0.0
    return float(np.cumsum(v * v)[-1])


class Weighting:
    """The norm every test is measured in (``Weighting``)."""

    def __init__(self, neq: int, threshold: np.ndarray, norm_control: bool, rms: bool = False,
                 skip: Optional[np.ndarray] = None) -> None:
        self.threshold = threshold
        self.norm_control = norm_control
        self.rms = (not norm_control) and rms
        self.inv = np.zeros(1 if norm_control else neq)
        self.skip = skip if (not norm_control and skip is not None and skip.size) else None
        self.inv_error = np.zeros(neq) if self.skip is not None else self.inv
        self._scaled_max = kernels.kernel('scaled_max')

    def update(self, y: np.ndarray, ynew: np.ndarray) -> None:
        if self.norm_control:
            self.inv[0] = 1 / max(math.sqrt(_seq_sum_squares(y)), math.sqrt(_seq_sum_squares(ynew)),
                                  float(self.threshold[0]))
            return
        self.inv[:] = 1 / np.maximum(np.maximum(np.abs(y), np.abs(ynew)), self.threshold)
        if self.skip is not None:
            self.inv_error[:] = self.inv
            self.inv_error[self.skip] = 0.0

    def of(self, v: np.ndarray, inv: Optional[np.ndarray] = None) -> float:
        inv = self.inv if inv is None else inv
        if self.norm_control:
            return math.sqrt(_seq_sum_squares(v)) * float(inv[0])
        if self.rms:
            a = v * inv
            return math.sqrt(_seq_sum_squares(a) / v.size) if v.size else 0.0
        if self._scaled_max is not None:
            return float(self._scaled_max(v, inv))
        a = np.abs(v) * inv
        if a.size == 0:
            return 0.0
        if np.isnan(a).any():
            return math.nan
        return float(max(0.0, a.max()))

    def of_error(self, v: np.ndarray) -> float:
        return self.of(v, self.inv_error)

    def of_sum(self, a: np.ndarray, b: np.ndarray) -> float:
        return self.of(a + b)


class _Projected:
    """The right-hand side of the projected system (``projectedDerivative``)."""

    def __init__(self, f: Callable[[float, np.ndarray], np.ndarray], constrained: np.ndarray, neq: int) -> None:
        self.f = f
        self.constrained = constrained
        self.held_rows = np.zeros(neq, dtype=np.uint8)
        self.push = np.zeros(constrained.size)
        self._c64 = np.asarray(constrained, dtype=np.int64)
        self._above = kernels.kernel('all_above_zero')
        self._any_held = False

    def __call__(self, t: float, y: np.ndarray) -> np.ndarray:
        # Every constrained state above zero, which is nearly always: nothing
        # is held, the push cannot grow (it is never below zero), and the
        # derivative -- a fresh array from System.rhs -- is returned as it is.
        if self._above is not None and self._above(y, self._c64):
            dy = self.f(t, y)
            if self._any_held:
                self.held_rows[self.constrained] = 0
                self._any_held = False
            return dy
        dy = np.array(self.f(t, y), dtype=float)
        c = self.constrained
        yc = y[c]
        dc = dy[c]
        hold = (yc <= 0) & (dc < 0)
        push = np.where(hold, -dc, 0.0)
        np.maximum(self.push, push, out=self.push)
        dy[c[hold]] = 0.0
        self.held_rows[c] = hold
        self._any_held = bool(hold.any())
        return dy


def ndf(f: Callable[[float, np.ndarray], np.ndarray], tspan: Sequence[float], y0: np.ndarray,
        rtol: float = 1e-3, abstol: Any = 1e-6, non_negative: Sequence[int] = (), max_order: int = MAX_ORDER,
        bdf: bool = False, hmax: float = 0.0, h0: float = 0.0, max_steps: float = 1e6,
        error_norm: str = 'max', norm_control: bool = False, jacobian: Optional[Dict[str, Any]] = None,
        matrix: str = 'auto', below_tol_run: Optional[int] = None, stagnation_tol: float = 0.0,
        min_newton: int = 1, stall_window: int = STALL_WINDOW_STEPS, events: Any = None,
        t_start: Optional[float] = None, hints: Optional[Dict[str, str]] = None,
        on_accepted: Optional[Callable[[float, np.ndarray], None]] = None,
        on_output: Optional[Callable[[float, np.ndarray], None]] = None,
        on_step: Optional[Callable[[float, int], Any]] = None, auto_abstol: bool = False,
        ends_only: bool = False, mass: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Integrates y' = f(t, y) over ``tspan``, answering at every time in it."""
    tspan = np.asarray(tspan, dtype=float)
    y0 = np.asarray(y0, dtype=float)
    neq = y0.size
    npts = tspan.size
    t0 = float(tspan[0])
    t_end = float(tspan[-1])
    direction = math.copysign(1.0, t_end - t0) if t_end != t0 else 0.0
    span = abs(t_end - t0)
    if not (span > 0):
        raise SolverError('span', 'The start and end times are equal', t0)
    max_order = max(1, min(MAX_ORDER, int(math.floor(max_order + 0.5))))
    leading = [0.0] * (MAX_ORDER + 2)
    error_const = [0.0] * (MAX_ORDER + 2)
    for k in range(1, MAX_ORDER + 1):
        kappa = 0.0 if bdf else KAPPA[k - 1]
        leading[k] = (1 - kappa) * GAMMA[k - 1]
        error_const[k] = kappa * GAMMA[k - 1] + 1 / (k + 1)
    if auto_abstol and isinstance(abstol, np.ndarray) and abstol.size == neq and abstol.dtype == float:
        atol = abstol
    elif np.ndim(abstol) == 0:
        atol = np.full(neq, float(abstol))
    else:
        atol = np.array(abstol, dtype=float)
    threshold = atol / rtol
    newton_threshold = threshold.copy() if auto_abstol else threshold
    mass_arr = np.asarray(mass, dtype=float) if mass is not None and len(mass) == neq else None
    algebraic = np.nonzero(mass_arr == 0)[0] if mass_arr is not None else np.zeros(0, dtype=np.int64)
    rms = error_norm == 'rms'
    error_weight = Weighting(neq, threshold, norm_control, rms, None)
    newton_weight = Weighting(neq, newton_threshold, norm_control, rms) if auto_abstol else error_weight
    floor_run = MAX_BELOW_TOLERANCE if below_tol_run is None else max(0, int(round(below_tol_run)))
    floor_newton_run = 0 if below_tol_run is None else floor_run
    hmax = min(hmax, span) if hmax and hmax > 0 else 0.1 * span

    nfevals = [0]

    def raw(tt: float, yy: np.ndarray) -> np.ndarray:
        nfevals[0] += 1
        return np.asarray(f(tt, yy), dtype=float)

    constrained = np.array([i for i in non_negative if not (mass_arr is not None and not mass_arr[i])],
                           dtype=np.int64)
    projected = _Projected(raw, constrained, neq) if constrained.size else None
    rhs = projected if projected is not None else raw
    clamp = constrained if constrained.size else None

    stats = {'nsteps': 0, 'nfailed': 0, 'npds': 0, 'ndecomps': 0, 'nsolves': 0, 'nbelowtol': 0, 'negative': 0}
    held = np.zeros(neq, dtype=np.int64) if constrained.size else None
    trace: List[Dict[str, Any]] = []

    tout: List[float] = []
    yout: List[np.ndarray] = []

    def record(tv: float, yv: np.ndarray) -> None:
        if ends_only and len(tout) > 1:
            tout[1] = tv
            yout[1] = np.array(yv, dtype=float)
            return
        tout.append(tv)
        yout.append(np.array(yv, dtype=float))

    next_out = 1
    table = DifferenceTable(neq, max_order)
    table.cols[0] = y0
    record(t0, table.y)
    t = t0

    def fail(e: SolverError) -> SolverError:
        e.trace = list(trace)
        e.last_t = t
        e.last_y = table.y.copy()
        e.stats = dict(stats, nfevals=nfevals[0])
        return e

    f0 = rhs(t0, table.y)
    bad = ~np.isfinite(table.y) | ~np.isfinite(f0)
    if bad.any():
        raise SolverError('nonfinite', f'The state or its derivative is not a number at t={t0} '
                                       f'(state {int(np.nonzero(bad)[0][0])}).', t0)
    vl = vr = None
    if events is not None:
        vl = np.array(events.fun(t0, table.y), dtype=float)
        vr = np.zeros(events.n)
    t_start = t0 if t_start is None else t_start
    stopped = None

    # --- the Jacobian and the matrix -------------------------------------------------
    pattern: Optional[Pattern] = jacobian.get('pattern') if jacobian else None
    evaluate = jacobian.get('evaluate') if jacobian else None
    constant = bool(jacobian.get('constant')) if jacobian else False
    groups = jacobian.get('groups') if jacobian else None
    if pattern is not None and groups is None:
        groups = colour_columns(pattern)
    state = {'J': None, 'fresh': False}

    def differenced(fy: np.ndarray) -> np.ndarray:
        y = table.y
        if pattern is not None:
            return difference_jacobian(raw, t, y, fy, pattern, groups, threshold)
        dl = difference_increment(y, threshold)
        J = np.zeros((neq, neq))
        for j in range(neq):
            ytry = y.copy()
            ytry[j] = y[j] + dl[j]
            J[:, j] = (raw(t, ytry) - fy) / dl[j]
        return J

    def evaluate_jacobian(fy: Optional[np.ndarray]) -> None:
        stats['npds'] += 1
        supplied = evaluate(t, table.y) if evaluate is not None else None
        if supplied is not None:
            state['J'] = np.asarray(supplied, dtype=float)
        else:
            state['J'] = differenced(fy if fy is not None else raw(t, table.y))
        state['fresh'] = True

    evaluate_jacobian(f0)
    try:
        W = IterationMatrix(neq, pattern, state['J'], matrix or 'auto', mass_arr, hints)
    except RuntimeError as e:
        raise SolverError('singular', str(e), t0) from None

    held_now = np.zeros(neq, dtype=np.uint8) if projected is not None else None
    held_in_w = np.zeros(neq, dtype=np.uint8) if projected is not None else None

    def read_held() -> None:
        if projected is not None:
            held_now[:] = projected.held_rows  # type: ignore[index]

    def held_moved() -> bool:
        if projected is None:
            return False
        return bool(np.any(held_now[constrained] != held_in_w[constrained]))  # type: ignore[index]

    def released_in_w() -> bool:
        if projected is None:
            return False
        rel = (held_in_w[constrained] == 1) & (projected.held_rows[constrained] == 0)  # type: ignore[index]
        if rel.any():
            held_now[constrained[rel]] = 0  # type: ignore[index]
            return True
        return False

    cur = {'h': 0.0, 'k': 1, 'hW': 0.0, 'kW': 0, 'rate': -1.0, 'hTable': 0.0}

    def form_w() -> None:
        any_held = False
        if projected is not None:
            held_in_w[:] = held_now  # type: ignore[index]
            any_held = bool(np.any(held_in_w[constrained]))  # type: ignore[index]
        try:
            W.form(cur['h'] / leading[cur['k']], state['J'], held_in_w if any_held else None)
        except RuntimeError as e:
            raise fail(SolverError('singular', f'{e} (at t={t})', t)) from None
        stats['ndecomps'] += 1
        cur['hW'] = cur['h']
        cur['kW'] = cur['k']
        cur['rate'] = -1.0

    # --- the first step ----------------------------------------------------------------
    yp = f0.copy()
    if algebraic.size:
        yp[algebraic] = 0.0

    def differential(v: np.ndarray) -> np.ndarray:
        if not algebraic.size:
            return v
        w = v.copy()
        w[algebraic] = 0.0
        return w

    y = table.y
    if h0 and h0 > 0:
        step_size = float(h0)
    else:
        error_weight.update(y, y)
        d0 = error_weight.of(differential(y)) / rtol
        d1 = error_weight.of(yp) / rtol
        guess = 1e-6 if (d0 < 1e-5 or d1 < 1e-5) else 0.01 * (d0 / d1)
        guess = min(guess, hmax)
        trial = y + direction * guess * yp
        f1 = rhs(t0 + direction * guess, trial)
        df = f1 - f0
        d2 = error_weight.of(differential(df)) / rtol / guess
        if not math.isfinite(d2):
            d2 = 100 * d1
        m = max(d1, d2)
        h1 = max(1e-6, guess * 1e-3) if m <= 1e-15 else math.sqrt(0.01 / m)
        step_size = min(100 * guess, h1)
    step_size = min(hmax, max(step_floor(t0), step_size))
    cur['h'] = direction * step_size
    table.start(y, cur['h'] * yp)
    cur['hTable'] = cur['h']
    read_held()
    form_w()

    consecutive = 0
    mask_reforms = 0
    below_run = 0
    tnew = t0
    stall_step = 0
    stall_t = t0
    stall_h = 0.0
    newton_its = 0
    step_fails = 0
    d = np.zeros(neq)

    def dense_at(tq: float) -> np.ndarray:
        return table.value_at(cur['k'], (tq - tnew) / cur['h'], clamp)

    def change_step(factor: float) -> None:
        nonlocal consecutive, mask_reforms
        h_new = direction * max(step_floor(t), abs(cur['h']) * factor)
        if h_new != cur['hTable']:
            table.rescale(cur['k'], h_new / cur['hTable'])
            cur['hTable'] = h_new
        cur['h'] = h_new
        consecutive = 0
        mask_reforms = 0

    def snap_onto_bound(should: Callable[[np.ndarray], np.ndarray]) -> bool:
        yv = table.y
        c = constrained
        sel = (yv[c] > 0) & (yv[c] <= atol[c]) & should(c)
        if not sel.any():
            return False
        idx = c[sel]
        yv[idx] = 0.0
        table.forget(idx)
        stats['negative'] += int(idx.size)
        rhs(t, yv)
        read_held()
        form_w()
        return True

    def floor_failure(nonfinite: bool) -> SolverError:
        hmin = step_floor(t)
        if nonfinite:
            return SolverError('nonfinite', f'The state or its derivative became non-finite at t={t}, and no step size '
                                            f'above the smallest allowed ({hmin}) gives a number.', t)
        return SolverError('tolerance', f'Failure at t={t}: unable to meet the integration tolerances without reducing '
                                        f'the step size below the smallest value allowed ({hmin}).', t)

    while True:
        hmin = step_floor(t)
        step_size = min(hmax, max(hmin, abs(cur['h'])))
        last = False
        h_try = direction * step_size
        if 1.1 * step_size >= abs(t_end - t):
            h_try = t_end - t
            last = True
        if h_try != cur['hTable']:
            table.rescale(cur['k'], h_try / cur['hTable'])
            cur['hTable'] = h_try
            consecutive = 0
        cur['h'] = h_try
        mask_reforms = 0
        y = table.y
        if projected is not None:
            if np.any(y[constrained] <= 0):
                rhs(t, y)
            read_held()
        if cur['h'] != cur['hW'] or cur['k'] != cur['kW'] or held_moved():
            form_w()

        err = 0.0
        first_failure = True
        while True:
            k = cur['k']
            h = cur['h']
            tnew = t_end if last else t + h
            pred = table.predict(k)
            hist = table.history(k)
            ynew = pred.copy()
            d = np.zeros(neq)
            if projected is not None:
                projected.push[:] = 0.0
            error_weight.update(y, ynew)
            if newton_weight is not error_weight:
                newton_weight.update(y, ynew)
            roundoff = 100 * EPS * newton_weight.of(ynew)
            outcome = 'converged'
            prev = 0.0
            rho = cur['rate']
            scale = 1 / leading[k]
            newton_its = 0
            delta = np.zeros(neq)
            for it in range(1, NEWTON_MAX + 1):
                fv = rhs(tnew, ynew)
                if mass_arr is not None:
                    resid = (h * fv - mass_arr * hist) * scale - mass_arr * d
                else:
                    resid = (h * fv - hist) * scale - d
                delta = W.solve(resid)
                stats['nsolves'] += 1
                newton_its = it
                size = newton_weight.of(delta)
                if not math.isfinite(size):
                    outcome = 'nonfinite'
                    break
                d = d + delta
                ynew = pred + d
                if size <= roundoff or size <= CONVERGED_FLOOR * rtol:
                    break
                if it == 1:
                    rate = cur['rate']
                    if min_newton <= 1 and rate >= 0 and (rate / (1 - rate)) * size <= NEWTON_TOL * rtol:
                        break
                    prev = size
                    continue
                ratio = size / prev
                if ratio >= RATE_LIMIT:
                    if stagnation_tol > 0 and state['fresh'] and size <= stagnation_tol * rtol:
                        break
                    outcome = 'slow'
                    break
                rho = max(ratio, RATE_FLOOR)
                remaining = (rho / (1 - rho)) * size
                if remaining <= NEWTON_TOL * rtol and it >= min_newton:
                    break
                if it == NEWTON_MAX or remaining * rho ** (NEWTON_MAX - it) > NEWTON_TOL * rtol:
                    outcome = 'slow'
                    break
                prev = size

            if outcome != 'converged':
                stats['nfailed'] += 1
                if projected is not None and snap_onto_bound(lambda c: projected.held_rows[c] == 1):
                    continue
                if not state['fresh']:
                    evaluate_jacobian(None)
                    read_held()
                    form_w()
                    continue
                if abs(h) <= hmin:
                    if outcome == 'nonfinite' or below_run >= floor_newton_run:
                        raise fail(floor_failure(outcome == 'nonfinite'))
                    below_run += 1
                    stats['nbelowtol'] += 1
                    err = rtol
                    break
                change_step(NEWTON_CUT)
                last = False
                form_w()
                continue
            if mask_reforms < 1 and released_in_w():
                mask_reforms += 1
                stats['nfailed'] += 1
                form_w()
                continue
            cur['rate'] = rho

            err = error_const[k] * error_weight.of_error(d)
            if not math.isfinite(err):
                raise fail(SolverError('nonfinite', f'The error estimate is not a number at t={t}: a tolerance or a '
                                                    'state weight is NaN.', t))
            for_constraint = False
            if projected is not None:
                neg = ynew[constrained]
                v = np.where(neg < 0, -neg / threshold[constrained], 0.0)
                worst = float(v.max()) if v.size else 0.0
                if worst > rtol and worst > err:
                    err = worst
                    for_constraint = True
            if err <= rtol:
                below_run = 0
                break
            stats['nfailed'] += 1
            step_fails += 1
            if for_constraint and snap_onto_bound(lambda c, _yn=ynew: _yn[c] < 0):
                continue
            if abs(h) <= hmin:
                if below_run >= floor_run:
                    raise fail(floor_failure(False))
                below_run += 1
                stats['nbelowtol'] += 1
                break
            if first_failure:
                first_failure = False
                factor = max(0.1, SAFETY * (rtol / err) ** (1 / (k + 1)))
                if k > 1:
                    err_lower = error_const[k - 1] * error_weight.of_sum(table.cols[k], d)
                    lower = max(0.1, SAFETY_LOWER * (rtol / err_lower) ** (1 / k)) if err_lower > 0 else math.inf
                    if lower > factor:
                        cur['k'] = k - 1
                        factor = min(1.0, lower)
            else:
                factor = 0.5
            change_step(factor)
            last = False
            form_w()

        # --- accepted ---------------------------------------------------------------
        stats['nsteps'] += 1
        trace.append({'t': t, 'h': cur['h'], 'k': cur['k'], 'err': err, 'newton': newton_its, 'failed': step_fails})
        if len(trace) > TRACE_STEPS:
            trace.pop(0)
        step_fails = 0
        if stats['nsteps'] > max_steps:
            raise fail(SolverError('steps', f'Exceeded {int(max_steps)} steps at t={t}. Nothing this solver can do with '
                                            'the step size will finish this run.', t))
        if stats['nsteps'] - stall_step >= stall_window:
            crawling = abs(tnew - stall_t) < span * STALL_SPAN_FRACTION
            not_growing = abs(cur['h']) <= 2 * stall_h
            if crawling and not_growing:
                raise fail(SolverError('stalled', f'The solver stopped making progress at t={tnew}: {stall_window} '
                                                  f'accepted steps advanced the clock by less than '
                                                  f'{span * STALL_SPAN_FRACTION}, and the step size is no longer '
                                                  'growing.', tnew))
            stall_step = stats['nsteps']
            stall_t = tnew
            stall_h = abs(cur['h'])

        k = cur['k']
        table.advance(k, d)
        y = table.y
        if projected is not None:
            c = constrained
            negs = c[y[c] < 0]
            if negs.size:
                y[negs] = 0.0
                stats['negative'] += int(negs.size)
                table.forget(negs)
            held[c] += (projected.push * abs(cur['h']) > atol[c]).astype(np.int64)  # type: ignore[index]

        if events is not None:
            hit = locate_crossing(events, t, vl, tnew, y, vr, dense_at, t_start)
            if hit is not None:
                t_e = hit['t']
                table.regrid(k, (t_e - tnew) / cur['h'], (t_e - t) / cur['h'])
                cur['h'] = t_e - t
                cur['hTable'] = cur['h']
                tnew = t_e
                consecutive = 0
                y = table.y
                if clamp is not None:
                    sub = y[clamp]
                    y[clamp] = np.where(sub < 0, 0.0, sub)
                vr[:] = hit['values']
                stopped = {'t': t_e, 'y': y.copy(), 'which': hit['which']}
                last = True
            vl[:] = vr

        while next_out < npts:
            tq = float(tspan[next_out])
            if direction * (tnew - tq) < 0:
                break
            at = table.y if tq == tnew else dense_at(tq)
            record(tq, at)
            if on_output is not None:
                on_output(tq, at)
            next_out += 1
        if on_accepted is not None:
            on_accepted(tnew, table.y)
        if on_step is not None and (stats['nsteps'] & 15) == 0 and on_step(tnew, stats['nsteps']) is False:
            raise SolverError('aborted', 'Aborted', tnew)

        t = tnew
        if auto_abstol:
            floor = rtol * np.abs(table.y)
            up = floor > atol
            atol[up] = floor[up]
            threshold[up] = floor[up] / rtol
        if last:
            break

        consecutive += 1
        k = cur['k']
        if consecutive >= k + 1:
            def allowed(e: float, q: int, safety: float) -> float:
                return min(MAX_GROWTH, safety * (rtol / e) ** (1 / (q + 1))) if e > 0 else MAX_GROWTH

            best_k = k
            best = allowed(err, k, SAFETY)
            if k > 1:
                e_lower = error_const[k - 1] * error_weight.of(table.cols[k])
                g = allowed(e_lower, k - 1, SAFETY_LOWER)
                if g > best:
                    best, best_k = g, k - 1
            if k < max_order:
                e_higher = error_const[k + 1] * error_weight.of(table.cols[k + 2])
                g = allowed(e_higher, k + 1, SAFETY_HIGHER)
                if g > best:
                    best, best_k = g, k + 1
            if best > 1:
                cur['k'] = best_k
                cur['h'] *= best
                consecutive = 0
        if not constant:
            state['fresh'] = False

    return {
        't': np.array(tout), 'y': yout, 'end': {'t': t, 'y': table.y.copy()}, 'stopped': stopped,
        'stats': dict(stats, nfevals=nfevals[0], held=held, sparse=W.info['sparse'], fill=W.info['fill'],
                      lu=W.info['lu'], solver='BDF' if bdf else 'NDF'),
    }
