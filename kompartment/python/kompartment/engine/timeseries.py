"""When results are saved: the output time grid.

A port of ``src/domain/timeseries.js``. A list of series -- geometric, linear,
or times written out -- combines into one sorted set of times, the run's own
start and end always in it and duplicates removed with a relative tolerance.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

from .. import jsmath

SERIES_KINDS = ('log', 'linear', 'times')
SPACINGS = ('log', 'linear', 'series', 'solver', 'both')

#: Two times are the same time when they are this close, relatively.
SAME = 1e-9


def _number(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def _round(x: float) -> float:
    return math.floor(x + 0.5) if math.isfinite(x) else x


def series_kind(spec: Optional[Dict[str, Any]]) -> str:
    """Which sort of series a spec is, however it was written."""
    if spec is not None and isinstance(spec.get('times'), list):
        return 'times'
    named = str((spec or {}).get('kind') if (spec or {}).get('kind') is not None
                else (spec or {}).get('spacing') if (spec or {}).get('spacing') is not None else 'log')
    return named if named in SERIES_KINDS else 'log'


def series_times(spec: Dict[str, Any], t0: float, t1: float) -> List[float]:
    """One series' own time points inside the run, in increasing order."""
    kind = series_kind(spec)
    if kind == 'times':
        vals = [_number(v) for v in spec.get('times') or []]
        return sorted(v for v in vals if math.isfinite(v) and t0 <= v <= t1)
    n = _round(_number(spec.get('points', 0)))
    if not (n >= 2):
        return []
    n = int(n)
    frm = t0 if spec.get('from') is None else _number(spec['from'])
    to = t1 if spec.get('to') is None else _number(spec['to'])
    if not math.isfinite(frm) or not math.isfinite(to):
        return []
    out: List[float] = []
    last = min(t1, to)
    if kind == 'log':
        if frm <= 0:
            frm = 1.0
        if not (to > frm):
            return []
        step = (jsmath.log10(to) - jsmath.log10(frm)) / (n - 1)
        if not (step > 0):
            return []
        log_from = jsmath.log10(frm)
        for c in range(n * 4 + 8):
            v = jsmath.pow(10.0, log_from + step * c)
            if v > last * (1 + SAME):
                break
            if v >= t0:
                out.append(v)
        return out
    step = (to - frm) / (n - 1)
    if not (step > 0):
        return []
    for c in range(n * 4 + 8):
        v = frm + step * c
        if v > last + abs(step) * SAME:
            break
        if v >= t0:
            out.append(v)
    return out


def combine_series(series: Optional[Iterable[Dict[str, Any]]], t0: float, t1: float) -> np.ndarray:
    """Every series, sorted, without duplicates; the run's start and end always in."""
    every = [t0, t1]
    for spec in series or []:
        every.extend(series_times(spec, t0, t1))
    every.sort()
    out: List[float] = []
    for v in every:
        if not math.isfinite(v):
            continue
        if out:
            last = out[-1]
            if abs(v - last) <= abs(last or v) * SAME:
                continue
        out.append(v)
    return np.array(out, dtype=float)


def dropped_times(spec: Dict[str, Any], t0: float, t1: float) -> List[float]:
    """The times a ``times`` series names that the run never reaches."""
    if series_kind(spec) != 'times':
        return []
    vals = [_number(v) for v in spec.get('times') or []]
    return [v for v in vals if math.isfinite(v) and (v < t0 or v > t1)]


def clipped_ends(spec: Dict[str, Any], t0: float, t1: float) -> List[Dict[str, Any]]:
    """Which of a series' own ends lie outside the run."""
    if series_kind(spec) == 'times':
        return []
    out = []
    for end in ('from', 'to'):
        v = spec.get(end)
        if v is None:
            continue
        n = _number(v)
        if not math.isfinite(n):
            continue
        if n < t0 or n > t1:
            out.append({'end': end, 'value': n})
    return out
