"""Numbers read off finished curves: the peak, when it peaked, the total.

A port of ``src/domain/derived.js``. A derived value is an output like any
other, worked out from ``(t, y)`` when asked for; the kinds that are curves
(the running integral, per-period means and sums) return one value per output
time, the rest one number.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

DERIVED_KINDS = ('max', 'min', 'time_of_max', 'at_time', 'integral', 'period_mean', 'period_sum', 'period_change',
                 'period_rate')
PERIOD_KINDS = ('period_mean', 'period_sum', 'period_change', 'period_rate')


def is_series(kind: str) -> bool:
    return kind == 'integral' or kind in PERIOD_KINDS


def derived_unit(kind: str, source_unit: Optional[str], time_unit: Optional[str]) -> str:
    u = str(source_unit if source_unit is not None else '').strip()
    tu = str(time_unit if time_unit is not None else '').strip()
    if kind == 'time_of_max':
        return tu
    if kind in ('integral', 'period_sum'):
        return f'{u} {tu}' if u else ''
    if kind == 'period_rate':
        return f'{u}/{tu}' if u else ''
    return u


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def reduce(kind: str, t: Sequence[float], values: Sequence[float], at: Any = None, period: Any = None) -> Any:
    n = min(len(t), len(values))
    if kind == 'integral':
        return integral(t, values, n)
    if kind in PERIOD_KINDS:
        return by_period(kind, t, values, n, _num(period))
    if not n:
        return math.nan
    if kind == 'at_time':
        return value_at(t, values, n, _num(at))
    best = math.nan
    best_at = math.nan
    for i in range(n):
        v = float(values[i])
        if not math.isfinite(v):
            continue
        if best != best or (v < best if kind == 'min' else v > best):
            best = v
            best_at = float(t[i])
    return best_at if kind == 'time_of_max' else best


def value_at(t: Sequence[float], values: Sequence[float], n: int, at: float) -> float:
    if not n or not math.isfinite(at):
        return math.nan
    if at <= t[0]:
        return float(values[0])
    if at >= t[n - 1]:
        return float(values[n - 1])
    lo, hi = 0, n - 1
    while hi - lo > 1:
        mid = (lo + hi) >> 1
        if t[mid] <= at:
            lo = mid
        else:
            hi = mid
    span = t[hi] - t[lo]
    if not (span > 0):
        return float(values[lo])
    a, b = float(values[lo]), float(values[hi])
    if not math.isfinite(a):
        return b
    if not math.isfinite(b):
        return a
    return a + ((at - t[lo]) / span) * (b - a)


def integral(t: Sequence[float], values: Sequence[float], n: Optional[int] = None) -> np.ndarray:
    n = min(len(t), len(values)) if n is None else n
    out = np.zeros(n)
    total = 0.0
    for i in range(1, n):
        dt = t[i] - t[i - 1]
        a, b = float(values[i - 1]), float(values[i])
        if dt > 0 and math.isfinite(a) and math.isfinite(b):
            total += 0.5 * (a + b) * dt
        out[i] = total
    return out


def by_period(kind: str, t: Sequence[float], values: Sequence[float], n: int, period: float) -> np.ndarray:
    out = np.full(n, math.nan)
    if not n or not (period > 0):
        return out
    t0, t_end = t[0], t[n - 1]
    running = integral(t, values, n)

    def integral_to(x: float) -> float:
        if x <= t0:
            return 0.0
        if x >= t_end:
            return float(running[n - 1])
        lo, hi = 0, n - 1
        while hi - lo > 1:
            mid = (lo + hi) >> 1
            if t[mid] <= x:
                lo = mid
            else:
                hi = mid
        a = float(values[lo])
        b = value_at(t, values, n, x)
        if not math.isfinite(a) or not math.isfinite(b):
            return float(running[lo])
        return float(running[lo]) + 0.5 * (a + b) * (x - t[lo])

    j = 0
    k = 0
    while True:
        frm = t0 + k * period
        if frm > t_end:
            break
        to = min(t_end, frm + period)
        span = to - frm
        if kind == 'period_mean':
            v = (integral_to(to) - integral_to(frm)) / span if span > 0 else value_at(t, values, n, frm)
        elif kind == 'period_sum':
            v = integral_to(to) - integral_to(frm)
        else:
            change = value_at(t, values, n, to) - value_at(t, values, n, frm)
            v = change if kind == 'period_change' else (change / span if span > 0 else math.nan)
        while j < n and (t[j] < to or (to == t_end and t[j] <= t_end)):
            out[j] = v
            j += 1
        if to == t_end:
            break
        k += 1
    return out


def derived_blocks(project: Any) -> List[Dict[str, Any]]:
    derived = project.derived if hasattr(project, 'derived') else (project or {}).get('derived')
    return [b for b in derived or [] if isinstance(b, dict) and str(b.get('name') or '').strip()
            and b.get('kind') in DERIVED_KINDS and str(b.get('of') or '').strip()]


def derived_outputs(project: Any, known_outputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The derived values a run can report, admitted in passes so one may be of another."""
    out: List[Dict[str, Any]] = []
    known = {o['label'] for o in known_outputs}
    by_label = {o['label']: o for o in known_outputs}
    pending = derived_blocks(project)
    time_unit = (project.simulation if hasattr(project, 'simulation') else {}).get('time_unit') or 'year'
    passes = 0
    while pending and passes <= len(pending):
        later = []
        for d in pending:
            name = str(d['name'])
            if d['of'] not in known or name in known:
                later.append(d)
                continue
            src = by_label.get(d['of'])
            o = {'kind': 'derived', 'source': 'D', 'block': name, 'label': name,
                 'unit': derived_unit(d['kind'], src.get('unit') if src else None, time_unit),
                 'derived': {'kind': d['kind'], 'of': d['of'], 'at': _num(d.get('at')),
                             'period': _num(d.get('period'))},
                 'dims': [], 'index': None}
            if not is_series(d['kind']):
                o['timeDependent'] = False
            out.append(o)
            by_label[name] = o
            known.add(name)
        if len(later) == len(pending):
            break
        pending = later
        passes += 1
    return out
