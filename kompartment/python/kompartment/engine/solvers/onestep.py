"""The driver the one-step methods share (``src/ode/core/onestep.js``).

Step-size control, the non-negativity constraint (held derivatives and the
projection onto zero), the stall guard, events and output are the same for
the Rosenbrock and the Dormand-Prince methods; each method supplies only how
a step is attempted and how the solution is read inside one.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from . import SolverError
from . import kernels
from .events import locate_crossing

EPS = 2.0 ** -52
STALL_WINDOW_STEPS = 2000
STALL_SPAN_FRACTION = 1e-9
MAX_AT_FLOOR = 20
SAFETY = 0.9
SHRINK_LEAST = 0.1
GROW_MOST = 5.0


def non_finite_error(t: float, index: Optional[int] = None) -> SolverError:
    where = '' if index is None else f' (state {index})'
    return SolverError('nonfinite', f'The state or its derivative became non-finite at t={t}{where}. Check for '
                                    'division by zero, a negative base raised to a fractional power, or an initial '
                                    'value that is not a number.', t)


def step_floor(t: float) -> float:
    return 16 * EPS * abs(t)


class HeldDerivative:
    """The derivative with a constrained state at zero held there.

    ``f`` hands back a fresh array each call (as ``System.rhs`` does), so it
    is returned as it is, and copied only when something is held.
    """

    def __init__(self, f: Callable[[float, np.ndarray], np.ndarray], non_negative: np.ndarray) -> None:
        self.f = f
        self.mask = non_negative
        self.idx = np.nonzero(non_negative)[0].astype(np.int64)
        self.every = self.idx.size == non_negative.size
        self.push = np.zeros(non_negative.size)
        self._above = kernels.kernel('all_above_zero')

    def __call__(self, t: float, y: np.ndarray) -> np.ndarray:
        out = self.f(t, y)
        idx = self.idx
        # Nothing to hold while every constrained state is above zero, which
        # is nearly always: one pass rather than the whole test.
        if not idx.size:
            return out
        if self._above is not None:
            if self._above(y, idx):
                return out
        elif (y.min() if self.every else y[idx].min()) > 0:
            return out
        hold = self.mask & (y <= 0) & (out < 0)
        if hold.any():
            out = np.array(out, dtype=float)
            np.maximum(self.push, np.where(hold, -out, 0.0), out=self.push)
            out[hold] = 0.0
        return out


def integrate(method: Any, f: Callable[[float, np.ndarray], np.ndarray], tspan: Any, y0: np.ndarray,
              opts: Dict[str, Any]) -> Dict[str, Any]:
    tspan = np.asarray(tspan, dtype=float)
    y0 = np.asarray(y0, dtype=float)
    neq = y0.size
    npts = tspan.size
    t0 = float(tspan[0])
    t_end = float(tspan[-1])
    if t_end == t0:
        raise SolverError('span', 'Simulation start and end time are equal', t0)
    direction = 1.0 if t_end > t0 else -1.0
    span = abs(t_end - t0)
    rtol = float(opts.get('rtol') or 1e-3)
    ab = opts.get('abstol', 1e-6)
    atol = np.full(neq, float(ab)) if np.ndim(ab) == 0 else np.array(ab, dtype=float)
    threshold = atol / rtol
    nn = opts.get('non_negative')
    non_negative = np.array(nn, dtype=bool) if nn is not None and any(nn) else None
    max_steps = opts.get('max_steps') or method.default_max_steps
    hmax = min(opts['hmax'], span) if (opts.get('hmax') or 0) > 0 else 0.1 * span
    hmin_opt = opts['hmin'] if (opts.get('hmin') or 0) > 0 else 0.0
    stall_window = opts.get('stall_window') or STALL_WINDOW_STEPS
    stall_span = STALL_SPAN_FRACTION * span
    exponent = 1 / (method.order + 1)
    rhs = HeldDerivative(f, non_negative) if (non_negative is not None and method.holds_at_zero) else f
    stepper = method.set_up(neq, rhs, f, threshold, atol, rtol, opts)
    tout: List[float] = []
    yout: List[np.ndarray] = []

    def record(tv: float, yv: np.ndarray) -> None:
        tout.append(tv)
        yout.append(np.array(yv, dtype=float))

    t = t0
    y = y0.copy()
    record(t0, y)
    next_out = 1
    nsteps = nfailed = nbelowtol = negative = 0
    nfevals = 0
    held = np.zeros(neq, dtype=np.int64) if isinstance(rhs, HeldDerivative) else None
    events = opts.get('events')
    vl = vr = None
    if events is not None:
        vl = np.array(events.fun(t0, y), dtype=float)
        vr = np.zeros(events.n)
    stopped = None
    nfevals += stepper.start(t, y)

    compiled_norm = kernels.kernel('weighted')
    norm_out = np.zeros(2)
    below = kernels.kernel('any_below_zero')
    nn_idx = np.nonzero(non_negative)[0].astype(np.int64) if non_negative is not None else None

    def any_negative(v: np.ndarray) -> bool:
        """Whether a constrained state is below zero in ``v``."""
        if below is not None:
            return bool(below(v, nn_idx))
        return bool((non_negative & (v < 0)).any())

    def weighted(v: np.ndarray, ya: np.ndarray, yb: np.ndarray) -> tuple:
        if compiled_norm is not None:
            compiled_norm(v, ya, yb, threshold, norm_out)
            return float(norm_out[0]), int(norm_out[1])
        return kernels.weighted_py(v, ya, yb, threshold)

    if (opts.get('h0') or 0) > 0:
        step_size = float(opts['h0'])
    else:
        f0 = stepper.derivative_at_start()
        d0 = weighted(y, y, y)[0] / rtol
        d1 = weighted(f0, y, y)[0] / rtol
        guess = 1e-6 if (d0 < 1e-5 or d1 < 1e-5) else 0.01 * (d0 / d1)
        guess = min(guess, hmax)
        trial = y + direction * guess * f0
        ftry = np.array(rhs(t0 + direction * guess, trial), dtype=float)
        nfevals += 1
        ftry = ftry - f0
        d2 = weighted(ftry, y, y)[0] / rtol / guess
        if not math.isfinite(d2):
            d2 = 100 * d1
        m = max(d1, d2)
        h1 = max(1e-6, guess * 1e-3) if m <= 1e-15 else (0.01 / m) ** exponent
        step_size = min(100 * guess, h1)
    step_size = min(hmax, max(step_floor(t0), hmin_opt, step_size))
    at_floor = 0
    stall_step = 0
    stall_t = t0
    ynew = np.zeros(neq)
    err_vec = np.zeros(neq)
    while True:
        if nsteps > max_steps:
            raise SolverError('steps', method.step_budget_message(max_steps, t), t)
        hmin = max(step_floor(t), hmin_opt)
        step_size = min(hmax, max(hmin, step_size))
        h = direction * step_size
        last = False
        if 1.1 * step_size >= abs(t_end - t):
            h = t_end - t
            step_size = abs(h)
            last = True
        err = 0.0
        worst_at = 0
        failed_once = False
        restart = False
        tnew = t
        while True:
            tnew = t_end if last else t + h
            h = tnew - t
            fevals, scale = stepper.attempt(t, y, h, tnew, ynew, err_vec)
            nfevals += fevals
            worst, worst_at = weighted(err_vec, y, ynew)
            err = worst * step_size * scale
            if not math.isfinite(err):
                nfailed += 1
                if step_size <= hmin:
                    raise non_finite_error(t, worst_at)
                failed_once = True
                step_size = max(hmin, 0.1 * step_size)
                h = direction * step_size
                last = False
                continue
            for_constraint = False
            if non_negative is not None and err <= rtol and any_negative(ynew):
                v = np.where(non_negative & (ynew < 0), -ynew / threshold, 0.0)
                at = int(np.argmax(v))
                if v[at] > 0 and v[at] > rtol:
                    err = float(v[at])
                    worst_at = at
                    for_constraint = True
            if err <= rtol:
                at_floor = 0
                break
            nfailed += 1
            if for_constraint and method.snaps_to_constraint:
                snap = non_negative & (ynew < 0) & (y > 0) & (y <= atol)
                if snap.any():
                    y[snap] = 0.0
                    nfevals += stepper.restart(t, y)
                    restart = True
                    break
            before = step_size
            if for_constraint or failed_once:
                step_size = max(hmin, 0.5 * step_size)
            else:
                step_size = max(hmin, step_size * max(SHRINK_LEAST, SAFETY * (rtol / err) ** exponent))
            failed_once = True
            if step_size <= hmin:
                at_floor += 1
                if at_floor >= MAX_AT_FLOOR:
                    raise SolverError('tolerance', method.floor_message(t, hmin, worst_at), t)
                step_size = before
                nbelowtol += 1
                break
            h = direction * step_size
            last = False
        if restart:
            continue
        nsteps += 1
        reprojected = False
        if non_negative is not None:
            if any_negative(ynew):
                neg = non_negative & (ynew < 0)
                ynew[neg] = 0.0
                reprojected = True
                negative += int(neg.sum())
            if held is not None:
                held += (rhs.push * step_size > atol).astype(np.int64)  # type: ignore[union-attr]
                rhs.push[:] = 0.0  # type: ignore[union-attr]
        if nsteps - stall_step >= stall_window:
            if abs(tnew - stall_t) < stall_span:
                raise SolverError('stalled', method.stall_message(tnew, stall_window, stall_span), tnew)
            stall_step = nsteps
            stall_t = tnew

        def dense_at(tq: float) -> np.ndarray:
            out = stepper.dense_at(tq)
            if non_negative is not None:
                out = np.where(non_negative & (out < 0), 0.0, out)
            return out

        if events is not None:
            hit = locate_crossing(events, t, vl, tnew, ynew, vr, dense_at, t0)
            if hit is not None:
                tnew = hit['t']
                ynew[:] = dense_at(tnew)
                vr[:] = hit['values']
                stopped = {'t': tnew, 'y': ynew.copy(), 'which': hit['which']}
                last = True
            vl[:] = vr
        while next_out < npts:
            tq = float(tspan[next_out])
            if direction * (tnew - tq) < 0:
                break
            at_v = ynew if tq == tnew else dense_at(tq)
            record(tq, at_v)
            if opts.get('on_output') is not None:
                opts['on_output'](tq, at_v)
            next_out += 1
        if opts.get('on_accepted') is not None:
            opts['on_accepted'](tnew, ynew)
        if opts.get('on_step') is not None and (nsteps & 31) == 0:
            if opts['on_step'](abs(tnew - t0) / span, nsteps, tnew) is False:
                raise SolverError('aborted', 'Simulation aborted', tnew)
        if last:
            break
        nfevals += stepper.accept(tnew, ynew, reprojected)
        if not failed_once:
            grow = SAFETY * (rtol / err) ** exponent if err > 0 else GROW_MOST
            step_size *= min(GROW_MOST, max(SHRINK_LEAST, grow))
        t = tnew
        y = ynew.copy()
    stats = {'nsteps': nsteps, 'nfailed': nfailed, 'nfevals': nfevals, 'nbelowtol': nbelowtol, 'negative': negative,
             'held': held, 'solver': method.id, 'points': len(tout)}
    stats.update(stepper.stats())
    return {'t': np.array(tout), 'y': yout, 'stopped': stopped, 'stats': stats}
