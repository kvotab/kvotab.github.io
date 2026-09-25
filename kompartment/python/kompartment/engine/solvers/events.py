"""Where an event function crosses zero inside a step (``src/ode/core/events.js``)."""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional

import numpy as np

EPS = 2.0 ** -52


def _sign(v: float) -> float:
    if v != v:
        return math.nan
    return (v > 0) - (v < 0) if v != 0 else v  # keeps -0 and +0 apart, as Math.sign does


def crosses(vl: np.ndarray, vr: np.ndarray, direction: np.ndarray, i: int, enabled: Optional[np.ndarray]) -> bool:
    if enabled is not None and not enabled[i]:
        return False
    a, b = float(vl[i]), float(vr[i])
    sa, sb = _sign(a), _sign(b)
    # Math.sign(a) === Math.sign(b): NaN never equals, and -0 === +0.
    if sa == sb:
        return False
    return direction[i] * (b - a) >= 0


def any_crossing(vl: np.ndarray, vr: np.ndarray, direction: np.ndarray, enabled: Optional[np.ndarray]) -> bool:
    return any(crosses(vl, vr, direction, i, enabled) for i in range(len(vl)))


def crossing_tolerance(tl: float, tr: float) -> float:
    scale = max(abs(tl), abs(tr), 1.0)
    return min(abs(tr - tl), 64 * EPS * scale)


def _earliest_secant(vlo: np.ndarray, vhi: np.ndarray, direction: np.ndarray, enabled: Optional[np.ndarray]) -> float:
    frac = 1.0
    for i in range(len(vlo)):
        if not crosses(vlo, vhi, direction, i, enabled):
            continue
        a, b = float(vlo[i]), float(vhi[i])
        f = 0.5 if a == b else -a / (b - a)
        if not (0 < f < 1):
            f = 0.5
        if f < frac:
            frac = f
    return frac


def first_crossing(values_at: Callable[[float], np.ndarray], tl: float, vl: np.ndarray, tr: float, vr: np.ndarray,
                   direction: np.ndarray, t_start: Optional[float] = None,
                   enabled: Optional[np.ndarray] = None) -> Optional[Dict[str, Any]]:
    tol = crossing_tolerance(tl, tr)
    tdir = math.copysign(1.0, tr - tl) if tr != tl else 0.0
    lo = tl
    vlo = vl
    if t_start is not None and tl == t_start:
        resting = any(vl[i] == 0 and vr[i] != 0 and (enabled is None or enabled[i]) for i in range(len(vl)))
        if resting:
            lo = tl + tdir * 0.5 * tol
            if tdir * (tr - lo) <= 0:
                return None
            vlo = np.array(values_at(lo), dtype=float)
            for i in range(len(vlo)):
                if vlo[i] == 0 and vl[i] == 0:
                    vlo[i] = vr[i]
    if not any_crossing(vlo, vr, direction, enabled):
        return None
    hi = tr
    vhi = vr
    kept = 0
    same_end = 0
    for _ in range(80):
        if not (abs(hi - lo) > tol):
            break
        if same_end >= 2:
            mid = 0.5 * (lo + hi)
        else:
            mid = lo + _earliest_secant(vlo, vhi, direction, enabled) * (hi - lo)
            inner = 0.5 * tol
            if tdir * (mid - lo) < inner:
                mid = lo + tdir * inner
            if tdir * (hi - mid) < inner:
                mid = hi - tdir * inner
            if not (tdir * (mid - lo) > 0 and tdir * (hi - mid) > 0):
                mid = 0.5 * (lo + hi)
        vmid = np.array(values_at(mid), dtype=float)
        if any_crossing(vlo, vmid, direction, enabled):
            hi = mid
            vhi = vmid
            same_end = same_end + 1 if kept == 1 else 1
            kept = 1
        else:
            lo = mid
            vlo = vmid
            same_end = same_end + 1 if kept == -1 else 1
            kept = -1
    which = [i for i in range(len(vlo)) if crosses(vlo, vhi, direction, i, enabled)]
    return {'t': hi, 'values': vhi, 'which': which}


def locate_crossing(events: Any, t: float, vl: np.ndarray, tnew: float, ynew: np.ndarray, vr: np.ndarray,
                    dense_at: Callable[[float], np.ndarray], t_start: Optional[float]) -> Optional[Dict[str, Any]]:
    """Reads the event functions at the end of a step (into ``vr``) and, if
    any crossed, finds the first crossing inside it."""
    vr[:] = events.fun(tnew, ynew)
    enabled = getattr(events, 'enabled', None)
    if not any_crossing(vl, vr, events.direction, enabled):
        return None

    def at(tq: float) -> np.ndarray:
        return np.array(events.fun(tq, dense_at(tq)), dtype=float)

    return first_crossing(at, t, vl, tnew, vr, events.direction, t_start, enabled)
