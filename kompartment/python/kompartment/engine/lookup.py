"""Lookup tables: a value that changes with time.

A port of ``src/domain/lookup.js``. A table is a list of (x, y) points and a
rule for reading between and beyond them:

* ``linear`` -- straight lines between the points, held flat at the ends;
* ``extrapolate`` -- as ``linear``, with the end segments continued outwards;
* ``below`` -- the value at or before x;
* ``above`` -- the value at or after x;
* ``nearest`` -- the value of whichever point is closer.

``cyclic`` wraps x into the table's own span first. The point is found by
bisection, so the answer does not depend on the order a solver asks in; two
points at the same x are a step, and the later one wins.

A table reads one number (:meth:`Table.at` on a float) or a whole array at
once, with the same arithmetic, in the same order, as the application.
"""

from __future__ import annotations

import bisect
import math
from typing import Any, List, Sequence, Tuple

import numpy as np

INTERPOLATIONS = ('linear', 'extrapolate', 'below', 'above', 'nearest')

INTERPOLATION_FROM_ECO = {
    'Interpolation-Use End Values': 'linear',
    'Interpolation-Extrapolation': 'extrapolate',
    'Use Input Below': 'below',
    'Use Input Above': 'above',
    'Use Input Nearest': 'nearest',
}


class LookupError_(ValueError):
    """A table that cannot be read: no points, an unknown rule, an x that is not a number."""


def _number(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        s = str(v).strip()
        if s == '':
            return 0.0
        return math.nan


def to_table(points: Any) -> Tuple[List[float], List[float]]:
    """``[[x, y], ...]`` or ``[xs, ys]`` as two lists sorted by x (a stable sort,
    as JavaScript's is)."""
    def flat(a: Any) -> bool:
        return isinstance(a, list) and all(isinstance(v, (int, float, str)) and not isinstance(v, bool) for v in a)

    if (isinstance(points, list) and len(points) == 2 and flat(points[0]) and flat(points[1])
            and len(points[0]) == len(points[1]) and len(points[0]) != 2):
        xs, ys = points[0], points[1]
    else:
        pairs = points or []
        xs = [p[0] if isinstance(p, (list, tuple)) else (p or {}).get('x') for p in pairs]
        ys = [p[1] if isinstance(p, (list, tuple)) and len(p) > 1 else
              (None if isinstance(p, (list, tuple)) else (p or {}).get('y')) for p in pairs]
    nx = [_number(v) if v is not None else math.nan for v in xs]
    order = sorted(range(len(nx)), key=lambda i: (0, nx[i]) if not math.isnan(nx[i]) else (1, 0.0))
    return [nx[i] for i in order], [_number(ys[i]) if ys[i] is not None else math.nan for i in order]


class Table:
    """A table ready to be read (``makeTable``)."""

    __slots__ = ('x', 'y', 'xa', 'ya', 'n', 'first', 'last', 'span', 'interpolation', 'cyclic', '_wraps')

    def __init__(self, points: Any, interpolation: str = 'linear', cyclic: bool = False) -> None:
        if interpolation not in INTERPOLATIONS:
            raise LookupError_(f"'{interpolation}' is not an interpolation rule ({', '.join(INTERPOLATIONS)})")
        x, y = to_table(points)
        n = len(x)
        if not n:
            raise LookupError_('A lookup table needs at least one point')
        if any(not math.isfinite(v) for v in x):
            raise LookupError_('A lookup point has no x value')
        self.x = x
        self.y = y
        self.xa = np.array(x, dtype=float)
        self.ya = np.array(y, dtype=float)
        self.n = n
        self.first = x[0]
        self.last = x[-1]
        self.span = self.last - self.first
        self.interpolation = interpolation
        self.cyclic = bool(cyclic)
        self._wraps = self.cyclic and self.span > 0

    def __len__(self) -> int:
        return self.n

    def set_y(self, row: int, value: float) -> None:
        """Rewrites one point's value (a distributed point, drawn again)."""
        self.y[row] = float(value)
        self.ya[row] = float(value)

    # --- one number -------------------------------------------------------------

    def _wrap(self, v: float) -> float:
        a = math.fmod(v - self.first, self.span)
        return a + self.first if a >= 0 else a + self.span + self.first

    def _segment(self, v: float) -> int:
        if v != v:
            return 0
        return min(max(bisect.bisect_right(self.x, v) - 1, 0), self.n - 2)

    def _between(self, v: float, i: int) -> float:
        x, y = self.x, self.y
        dx = x[i + 1] - x[i]
        if dx == 0:
            return y[i + 1]
        return y[i] + ((v - x[i]) / dx) * (y[i + 1] - y[i])

    def at_scalar(self, raw: float) -> float:
        v = self._wrap(raw) if self._wraps else raw
        n = self.n
        y = self.y
        if n == 1:
            return y[0]
        interp = self.interpolation
        if v <= self.first:
            return self._between(v, 0) if interp == 'extrapolate' else y[0]
        if v >= self.last:
            return self._between(v, n - 2) if interp == 'extrapolate' else y[n - 1]
        i = self._segment(v)
        if interp == 'below':
            return y[i]
        if interp == 'above':
            return y[i] if self.x[i] == v else y[i + 1]
        if interp == 'nearest':
            dx = self.x[i + 1] - self.x[i]
            return y[i] if dx == 0 or (v - self.x[i]) / dx < 0.5 else y[i + 1]
        return self._between(v, i)

    def slope_scalar(self, raw: float) -> float:
        n = self.n
        if n == 1 or self.interpolation in ('below', 'above', 'nearest'):
            return 0.0
        v = self._wrap(raw) if self._wraps else raw
        x, y = self.x, self.y
        if v < self.first or v > self.last:
            if self.interpolation != 'extrapolate':
                return 0.0
            i = 0 if v < self.first else n - 2
        else:
            i = self._segment(v)
        dx = x[i + 1] - x[i]
        return 0.0 if dx == 0 else (y[i + 1] - y[i]) / dx

    # --- many numbers -------------------------------------------------------------

    def at(self, raw: Any) -> Any:
        """The table read at ``raw``: a float, or an array of them."""
        if np.ndim(raw) == 0:
            return self.at_scalar(float(raw))
        v = np.asarray(raw, dtype=float)
        if self._wraps:
            a = np.fmod(v - self.first, self.span)
            v = np.where(a >= 0, a + self.first, a + self.span + self.first)
        n = self.n
        if n == 1:
            return np.full(v.shape, self.y[0])
        xa, ya = self.xa, self.ya
        i = np.clip(np.searchsorted(xa, v, side='right') - 1, 0, n - 2)
        i = np.where(np.isnan(v), 0, i)
        interp = self.interpolation
        x0, x1, y0, y1 = xa[i], xa[i + 1], ya[i], ya[i + 1]
        dx = x1 - x0
        with np.errstate(all='ignore'):
            lin = np.where(dx == 0, y1, y0 + ((v - x0) / dx) * (y1 - y0))
        if interp == 'below':
            inside = y0
        elif interp == 'above':
            inside = np.where(x0 == v, y0, y1)
        elif interp == 'nearest':
            with np.errstate(all='ignore'):
                inside = np.where((dx == 0) | ((v - x0) / dx < 0.5), y0, y1)
        else:
            inside = lin
        if interp == 'extrapolate':
            with np.errstate(all='ignore'):
                lo = self._between_array(v, 0)
                hi = self._between_array(v, n - 2)
        else:
            lo = ya[0]
            hi = ya[n - 1]
        out = np.where(v <= self.first, lo, np.where(v >= self.last, hi, inside))
        return out

    def _between_array(self, v: np.ndarray, i: int) -> np.ndarray:
        x, y = self.x, self.y
        dx = x[i + 1] - x[i]
        if dx == 0:
            return np.full(v.shape, y[i + 1])
        return y[i] + ((v - x[i]) / dx) * (y[i + 1] - y[i])

    def slope_at(self, raw: Any) -> Any:
        """dy/dx at ``raw`` (zero for the step rules and at a step)."""
        if np.ndim(raw) == 0:
            return self.slope_scalar(float(raw))
        return np.array([self.slope_scalar(float(v)) for v in np.ravel(raw)]).reshape(np.shape(raw))


def make_table(points: Any, interpolation: str = 'linear', cyclic: bool = False) -> Table:
    return Table(points, interpolation, cyclic)


def interpolate_args(args: Sequence[float], interpolation: str) -> float:
    """``interpolationUseEndValues(XI, X1, Y1, X2, Y2, ...)`` and its siblings."""
    key, rest = args[0], list(args[1:])
    if len(rest) < 2 or len(rest) % 2 != 0:
        raise LookupError_(f'interpolation needs a lookup value and then x, y pairs; got {len(rest)} value(s) '
                           'after it')
    pairs = [[rest[i], rest[i + 1]] for i in range(0, len(rest), 2)]
    return Table(pairs, interpolation).at_scalar(float(key))


def interpolate_slope(args: Sequence[float], interpolation: str) -> float:
    key, rest = args[0], list(args[1:])
    if len(rest) < 2 or len(rest) % 2 != 0:
        return 0.0
    pairs = [[rest[i], rest[i + 1]] for i in range(0, len(rest), 2)]
    return Table(pairs, interpolation).slope_scalar(float(key))
