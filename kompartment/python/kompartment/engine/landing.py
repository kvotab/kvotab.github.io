"""Where a step has to end so as not to pass over a pulse in a table
(``src/sim/landing.js`` in the application, number for number).

A solver looks at the derivative at the ends of its steps and at its stages
inside them, and nowhere else. A table read at the clock that rises and falls
back between two of those places is never seen, and what it would have put
into the model is lost: a pulse after a time of none arrives as nothing, a
spike on a steady release as the steady release alone.

So each turn of each such table -- a point higher than both its neighbours, or
lower -- is a place a step may not cover whole when the turn matters: when the
area it adds to the straight line between its neighbours is more than rtol of
what the table holds over that step. Such a step ends at the turn instead. A
turn is judged over the stretch a step would have to cover to miss it, by the
interpolation rule, and the step ends inside that stretch, never on a jump.
Tables read at an expression, and cyclic ones, are left out.

:class:`TableLanding` is the rule for the Python loops; :meth:`TableLanding.arrays`
hands the same numbers to the compiled ones (``compiled/solvers.py``,
``_landing``), which reach the same answers from them.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from typing import Any, Iterable, List, Optional, Tuple

import numpy as np

EPS = 2.0 ** -52

#: Turns judged together: one maximum each, so a long step skips quiet stretches.
LANDING_BLOCK = 32


class _Tab:
    __slots__ = ('x', 'ay', 'cum', 'A', 'B', 'AT', 'CRIT', 'block_max')

    def __init__(self, x: List[float], ay: List[float], cum: List[float], A: List[float], B: List[float],
                 AT: List[float], CRIT: List[float], block_max: List[float]) -> None:
        self.x = x
        self.ay = ay
        self.cum = cum
        self.A = A
        self.B = B
        self.AT = AT
        self.CRIT = CRIT
        self.block_max = block_max


def table_landing(tables: Iterable[Any], rtol: float) -> Optional['TableLanding']:
    """The rule for ``tables`` (each with ``x``, ``y`` and ``interpolation``),
    or None when none of them turns (``tableLanding``)."""
    tabs: List[_Tab] = []
    for table in tables:
        x = [float(v) for v in table.x]
        y = [float(v) for v in table.y]
        n = len(x)
        if n < 3:
            continue
        rule = getattr(table, 'interpolation', None) or 'linear'
        A: List[float] = []
        B: List[float] = []
        AT: List[float] = []
        CRIT: List[float] = []
        for i in range(1, n - 1):
            y0 = y[i - 1]
            y1 = y[i]
            y2 = y[i + 1]
            if not ((y1 > y0 and y1 >= y2) or (y1 < y0 and y1 <= y2)):
                continue
            x0 = x[i - 1]
            x1 = x[i]
            x2 = x[i + 1]
            if rule == 'below':
                a, b, at = x1, x2, 0.5 * (x1 + x2)
            elif rule == 'above':
                a, b, at = x0, x1, 0.5 * (x0 + x1)
            elif rule == 'nearest':
                a, b, at = 0.5 * (x0 + x1), 0.5 * (x1 + x2), x1
            else:
                a, b = x0, x2
                at = x1 if (x0 < x1 and x1 < x2) else 0.5 * (x0 + x2)
            if not (b - a > 1024 * EPS * max(abs(a), abs(b))):
                continue
            span = x2 - x0
            chord = y0 + (y2 - y0) * ((x1 - x0) / span)
            bump = 0.5 * span * abs(y1 - chord)
            if not (bump > 0):
                continue
            A.append(a)
            B.append(b)
            AT.append(at)
            CRIT.append(bump / rtol)
        m = len(A)
        if not m:
            continue
        ay = [abs(v) for v in y]
        cum = [0.0] * n
        for j in range(1, n):
            cum[j] = cum[j - 1] + 0.5 * (x[j] - x[j - 1]) * (ay[j - 1] + ay[j])
        nb = -(-m // LANDING_BLOCK)
        block_max = [0.0] * nb
        for q in range(nb):
            top = 0.0
            for i in range(q * LANDING_BLOCK, min(m, (q + 1) * LANDING_BLOCK)):
                if CRIT[i] > top:
                    top = CRIT[i]
            block_max[q] = top
        tabs.append(_Tab(x, ay, cum, A, B, AT, CRIT, block_max))
    return TableLanding(tabs) if tabs else None


def _held_by(tab: _Tab, s: float) -> float:
    """The area under |table| up to s: straight lines between points, flat beyond them."""
    x = tab.x
    ay = tab.ay
    n = len(x)
    if s <= x[0]:
        return (s - x[0]) * ay[0]
    if s >= x[n - 1]:
        return tab.cum[n - 1] + (s - x[n - 1]) * ay[n - 1]
    j = min(bisect_right(x, s) - 1, n - 2)
    dx = x[j + 1] - x[j]
    v = ay[j] + (ay[j + 1] - ay[j]) * ((s - x[j]) / dx) if dx > 0 else ay[j + 1]
    return tab.cum[j] + 0.5 * (s - x[j]) * (ay[j] + v)


def _earliest_turn(tab: _Tab, t: float, t_next: float) -> int:
    """The first turn of ``tab`` a step from t to t_next covers whole and that
    holds more than rtol of what the table holds over the step; -1 for none."""
    i0 = bisect_left(tab.A, t)
    i1 = bisect_right(tab.B, t_next, i0)
    if i1 <= i0:
        return -1
    held = _held_by(tab, t_next) - _held_by(tab, t)
    crit = tab.CRIT
    i = i0
    while i < i1:
        q = i // LANDING_BLOCK
        end = min(i1, (q + 1) * LANDING_BLOCK)
        if i == q * LANDING_BLOCK and end == (q + 1) * LANDING_BLOCK and not (tab.block_max[q] > held):
            i = end
            continue
        while i < end:
            if crit[i] > held:
                return i
            i += 1
    return -1


class TableLanding:
    """``landing(t, t_next)``: where a step from t to t_next is to end
    instead, or NaN."""

    __slots__ = ('tabs',)

    def __init__(self, tabs: List[_Tab]) -> None:
        self.tabs = tabs

    def __call__(self, t: float, t_next: float) -> float:
        best = math.nan
        if not (t_next > t):
            return best
        for tab in self.tabs:
            i = _earliest_turn(tab, t, t_next)
            if i >= 0 and not (tab.AT[i] >= best):
                best = tab.AT[i]
        return best

    def arrays(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """The same numbers for the compiled loops: the tables' points (x,
        |y|, the area to each) and the turns (stretch start and end, the time
        to end on, the criterion) side by side, the block maxima, and where
        each table starts in those three, in that order."""
        return landing_arrays(self)


def landing_arrays(landing: Optional[TableLanding]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """``TableLanding.arrays``, and empty ones for no landing."""
    tabs = landing.tabs if landing is not None else []
    npts = sum(len(tb.x) for tb in tabs)
    nturn = sum(len(tb.A) for tb in tabs)
    nblock = sum(len(tb.block_max) for tb in tabs)
    LT = np.zeros((3, npts))
    LF = np.zeros((4, nturn))
    LB = np.zeros(nblock)
    ntab = len(tabs)
    LO = np.zeros(3 * (ntab + 1), dtype=np.int64)
    p = f = b = 0
    for k, tb in enumerate(tabs):
        LO[k] = p
        LO[ntab + 1 + k] = f
        LO[2 * (ntab + 1) + k] = b
        n = len(tb.x)
        LT[0, p:p + n] = tb.x
        LT[1, p:p + n] = tb.ay
        LT[2, p:p + n] = tb.cum
        m = len(tb.A)
        LF[0, f:f + m] = tb.A
        LF[1, f:f + m] = tb.B
        LF[2, f:f + m] = tb.AT
        LF[3, f:f + m] = tb.CRIT
        nb = len(tb.block_max)
        LB[b:b + nb] = tb.block_max
        p += n
        f += m
        b += nb
    LO[ntab] = p
    LO[2 * ntab + 1] = f
    LO[3 * ntab + 2] = b
    return LT, LF, LB, LO
