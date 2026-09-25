"""The two blocks that reduce many values to one.

A port of ``src/domain/reduce.js``: an *index operation* reduces one block
along one of its index lists, an *aggregate* reduces several blocks element by
element. Both come down to a call of a function the equation language has.
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Sequence

OPERATIONS = ('sum', 'product', 'min', 'max', 'mean', 'percentile')
AGGREGATE_OPERATIONS = tuple(o for o in OPERATIONS if o != 'percentile')

OPERATION_FUNCTION = {
    'sum': 'sum', 'product': 'prod', 'min': 'min', 'max': 'max', 'mean': 'mean', 'percentile': 'percentile',
}


def operated_list(own_dims: Optional[Sequence[str]], target_dims: Optional[Sequence[str]],
                  is_scenario: Optional[Callable[[str], bool]] = None) -> Optional[str]:
    """The index list an index operation reduces over: the target's first list
    the block itself is not indexed by (its first, for a block of no lists)."""
    target = [d for d in target_dims or [] if not (is_scenario and is_scenario(d))]
    if not target:
        return None
    own = list(own_dims or [])
    if not own:
        return target[0]
    return next((d for d in target if d not in own), None)


def _compare(a: float, b: float) -> float:
    v = a - b
    return 0.0 if v != v else v


def js_sort_numbers(values: Sequence[float]) -> List[float]:
    """``[...values].sort((a, b) => a - b)`` as V8 does it.

    With no NaN among them this is an ordinary sort. With one, the comparator
    answers NaN, which V8 reads as "equal", and where the NaN ends up depends
    on the algorithm -- so for the short arrays an equation can pass (under 64)
    this follows V8's own: the first run, then binary insertion. Longer ones
    fall back to a stable sort with NaN last.
    """
    a = [float(v) for v in values]
    n = len(a)
    if n < 2:
        return a
    if not any(v != v for v in a):
        return sorted(a)
    if n >= 64:
        return sorted(a, key=lambda v: (1, 0.0) if v != v else (0, v))
    # CountAndMakeRun
    run = 2
    descending = _compare(a[1], a[0]) < 0
    previous = a[1]
    for i in range(2, n):
        order = _compare(a[i], previous)
        if (descending and order >= 0) or (not descending and order < 0):
            break
        previous = a[i]
        run += 1
    if descending:
        a[:run] = a[:run][::-1]
    # BinaryInsertionSort(0, run, n)
    for start in range(run, n):
        pivot = a[start]
        left, right = 0, start
        while left < right:
            mid = left + ((right - left) >> 1)
            if _compare(pivot, a[mid]) < 0:
                right = mid
            else:
                left = mid + 1
        a[left + 1:start + 1] = a[left:start]
        a[left] = pivot
    return a


def percentile(phi: float, xs: Sequence[float]) -> float:
    """The percentile of a sample: sorted values at the midpoints (i - 0.5)/n,
    the extremes pinned to 0 and 1, straight lines between."""
    n = len(xs)
    if not n or not (phi >= 0) or not (phi <= 100):
        return math.nan
    p = phi / 100
    s = js_sort_numbers(xs)
    if p == 0.5:
        return s[(n + 1) // 2 - 1] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2
    xx = [s[0], *s, s[n - 1]]
    pp = [0.0] + [(i - 0.5) / n for i in range(1, n + 1)] + [1.0]
    j = 1
    while j < n + 2 and p > pp[j]:
        j += 1
    if j >= n + 2:
        return xx[n + 1]
    span = pp[j] - pp[j - 1]
    if span == 0:
        return xx[j]
    return ((p - pp[j - 1]) / span) * (xx[j] - xx[j - 1]) + xx[j - 1]
