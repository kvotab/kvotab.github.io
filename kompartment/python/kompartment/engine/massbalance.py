"""The mass-balance audit (``src/domain/massbalance.js``).

With ``mass_balance`` on, the run carries one budget state per family (each
radionuclide, and one for what is not indexed by any) per kind of movement.
The audit checks that what each family holds equals what it started with plus
what came in, less what went out and decayed, plus what grew in.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

TERMS = ('in', 'out', 'decay', 'ingrowth', 'explicit', 'between')
UNINDEXED = 'not by nuclide'


def budget_index(budget: Dict[str, Any], term: str, family: int) -> int:
    return budget['base'] + TERMS.index(term) * budget['nfam'] + family


def closed_below(rtol: Any) -> float:
    try:
        r = float(rtol)
    except (TypeError, ValueError):
        r = math.nan
    return max(1e-10, 20 * (r if math.isfinite(r) and r > 0 else 1e-6))


def audit(budget: Dict[str, Any], t: Sequence[float], y: Sequence[np.ndarray], rtol: Any = None,
          abstol: Any = None) -> Dict[str, Any]:
    """The closure, family by family and in total (``audit``). ``abstol`` is
    the run's absolute tolerance, one number or one per state: a family that
    never holds or moves more than the largest among its states is
    ``unresolved`` -- the solver promises nothing that fine -- and not judged."""
    n = len(t)
    F = budget['nfam']
    inventory = np.zeros((F, n))
    for i in range(n):
        yi = y[i]
        for m in budget['members']:
            for off in range(m['width']):
                inventory[m['famOf'][off], i] += yi[m['base'] + off]

    def row_at(i: int, f: int) -> Dict[str, float]:
        def term(name: str) -> float:
            return float(y[i][budget_index(budget, name, f)])
        row = {'inventory': float(inventory[f, i]), 'start': float(inventory[f, 0]), 'in': term('in'),
               'out': term('out'), 'decay': term('decay'), 'ingrowth': term('ingrowth'), 'explicit': term('explicit'),
               'between': term('between')}
        row['expected'] = (row['start'] + row['in'] - row['out'] - row['decay'] + row['ingrowth'] + row['explicit']
                           + row['between'])
        row['residual'] = row['inventory'] - row['expected']
        return row

    def add_rows(a: Dict[str, float], b: Dict[str, float]) -> Dict[str, float]:
        return {k: a[k] + b[k] for k in a}

    def scale_of(row: Dict[str, float], scale: float) -> float:
        return max(scale, abs(row['inventory']), abs(row['start']), row['in'], row['out'], row['decay'],
                   row['ingrowth'], abs(row['explicit']), abs(row['between']))

    def floor_of(f: int) -> float:
        if abstol is None:
            return 0.0
        if np.ndim(abstol) == 0:
            a = float(abstol)
            return a if math.isfinite(a) and a > 0 else 0.0
        most = 0.0
        for m in budget['members']:
            for off in range(m['width']):
                v = float(abstol[m['base'] + off])
                if m['famOf'][off] == f and math.isfinite(v) and v > most:
                    most = v
        return most

    families: List[Dict[str, Any]] = []
    totals: List[Optional[Dict[str, float]]] = [None] * n
    for f in range(F):
        worst = 0.0
        at = float(t[0])
        scale = 0.0
        last = None
        for i in range(n):
            row = row_at(i, f)
            scale = scale_of(row, scale)
            if abs(row['residual']) > worst:
                worst = abs(row['residual'])
                at = float(t[i])
            last = row
            totals[i] = add_rows(totals[i], row) if totals[i] else row
        floor = floor_of(f)
        idle = scale == 0 or scale <= floor
        families.append({'name': budget['families'][f], 'idle': idle, 'unresolved': idle and scale > 0,
                         'floor': floor, 'scale': scale, 'worst': 0.0 if idle else worst,
                         'relative': 0.0 if idle else worst / scale, 'at': at, 'final': last})
    total: Dict[str, Any] = {'scale': 0.0, 'worst': 0.0, 'relative': 0.0, 'at': float(t[0]) if n else 0.0,
                             'final': None}
    for i in range(n):
        row = totals[i]
        if not row:
            continue
        total['scale'] = scale_of(row, total['scale'])
        if abs(row['residual']) > total['worst']:
            total['worst'] = abs(row['residual'])
            total['at'] = float(t[i])
        total['final'] = row
    total['relative'] = total['worst'] / total['scale'] if total['scale'] > 0 else 0.0
    live = [f for f in families if not f['idle']]
    worst_family = None
    for f in live:
        if f['relative'] > (worst_family['relative'] if worst_family else -1):
            worst_family = f
    worst_rel = worst_family['relative'] if worst_family else 0.0
    return {
        'worst': worst_rel,
        'at': worst_family['at'] if worst_family else (float(t[0]) if n else 0.0),
        'worstFamily': worst_family['name'] if worst_family else None,
        'closed': worst_rel <= closed_below(rtol),
        'tolerance': closed_below(rtol),
        'families': families,
        'total': total,
    }
