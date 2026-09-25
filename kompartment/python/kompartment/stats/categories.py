"""Sorting the realisations of a probabilistic run into named categories.

A port of ``src/domain/categories.js``. A category is a label and a condition
over one kept series -- one statistic of it over the run (its peak, its lowest
value, its value at the end or at one time) and one comparison -- and each
realisation belongs to the **first** category whose condition it meets, in the
order the categories are written. Whatever meets none is *Other*. A category
can be screened out of every display (``include`` false); Other always stays.

Nothing is stored per realisation in the model: the categories are, in
``simulation.categories``, and the membership is worked out from whichever run
stands. A run that did not keep the series a category reads leaves that
category empty and says so.

The categories come back as dictionaries with the application's keys
(``label``, ``output``, ``stat``, ``at``, ``op``, ``value``, ``value2``,
``include``), so they can be written back into a model as they are.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np

from .sensitivity import (
    _f64, _is_js_finite, _is_js_integer, _js_max, _js_min, _js_number, _js_string, _js_truthy,
)

__all__ = [
    'STATS', 'STAT_LABEL', 'OPS', 'categories_of', 'category_problems', 'statistic_of', 'classify',
    'include_mask', 'describe_category',
]

#: Which number of a series a condition reads.
STATS = ['final', 'max', 'min', 'at']

STAT_LABEL = {
    'final': 'value at the end',
    'max': 'peak',
    'min': 'lowest value',
    'at': 'value at a time',
}

#: How it is compared.
OPS = ['>', '>=', '<', '<=', 'between']


def _raw_of(project: Any) -> Any:
    """The project's dictionary, from a dictionary or a :class:`kompartment.Model`."""
    raw = getattr(project, 'raw', project)
    return raw if isinstance(raw, Mapping) else None


def categories_of(project: Any) -> List[Dict[str, Any]]:
    """Reads the categories off a model, filling in what cannot be read.

    ``project`` is the model's dictionary (or a :class:`kompartment.Model`). A
    statistic or comparison the application does not know becomes ``max`` or
    ``>``; a time index that is not an integer becomes 0; a value is read as
    JavaScript's ``Number()`` reads it, so a missing one is NaN.
    """
    raw = _raw_of(project)
    sim = raw.get('simulation') if raw is not None else None
    cats = sim.get('categories') if isinstance(sim, Mapping) else None
    if not isinstance(cats, (list, tuple)):
        return []
    out = []
    for i, c in enumerate(cats):
        d = c if isinstance(c, Mapping) else {}
        label = d.get('label')
        output = d.get('output')
        stat = d.get('stat')
        op = d.get('op')
        at = d.get('at')
        out.append({
            'label': _js_string(label) if label is not None else f'Category {i + 1}',
            'output': _js_string(output) if output is not None else '',
            'stat': stat if isinstance(stat, str) and stat in STATS else 'max',
            'at': int(at) if _is_js_integer(at) else 0,
            'op': op if isinstance(op, str) and op in OPS else '>',
            'value': _js_number(d['value']) if 'value' in d else math.nan,
            'value2': _js_number(d['value2']) if 'value2' in d else math.nan,
            # Screened out of every display when false. Absent means included.
            'include': d.get('include') is not False,
        })
    return out


def category_problems(categories: Sequence[Mapping[str, Any]],
                      output_labels: Optional[Sequence[str]] = None) -> List[str]:
    """What is wrong with each category, before it is used, as sentences.

    With ``output_labels`` -- the series a run kept -- a category that reads a
    series outside them is named too.
    """
    out = []
    for i, c in enumerate(categories):
        label = c.get('label')
        who = _js_string(label) if _js_truthy(label) else f'category {i + 1}'
        output = c.get('output')
        if not _js_truthy(output):
            out.append(f'{who}: no series is named.')
        elif output_labels is not None and output not in list(output_labels):
            out.append(f'{who}: the run did not keep {_js_string(output)}, so nothing can be sorted by it.')
        if not _is_js_finite(c.get('value')):
            out.append(f'{who}: the value to compare against is not a number.')
        if c.get('op') == 'between' and not _is_js_finite(c.get('value2')):
            out.append(f"{who}: 'between' needs a second value.")
    return out


def _read(values: np.ndarray, index: Any) -> float:
    """``values[index]``: NaN where a typed array would give ``undefined``."""
    try:
        f = float(index)
    except (TypeError, ValueError):
        return math.nan
    if not math.isfinite(f) or f != math.floor(f):
        return math.nan
    k = int(f)
    return float(values[k]) if 0 <= k < len(values) else math.nan


def statistic_of(values: Sequence[float], times: int, i: int, stat: str, at: Any) -> float:
    """The one number of realisation ``i``'s series a condition reads.

    ``values`` is realisation-major, ``times`` numbers per realisation. ``final``
    is the last, ``at`` the one at time index ``at`` (clamped to the series),
    ``max`` the largest finite one; any other statistic reads the smallest, as
    ``min`` does. NaN where there is nothing to read. A tornado reads a design
    point's series the same way.
    """
    v = _f64(values)
    frm = i * times
    if stat == 'final':
        return _read(v, frm + times - 1)
    if stat == 'at':
        # Math.max(0, at) reads `at` as a number; None is null, which is 0.
        return _read(v, frm + _js_min(times - 1, _js_max(0, _js_number(at))))
    j = np.arange(times, dtype=np.int64) + frm
    j = j[(j >= 0) & (j < len(v))]
    seg = v[j]
    seg = seg[np.isfinite(seg)]
    if not len(seg):
        return math.nan
    return float(seg.max() if stat == 'max' else seg.min())


def _statistic_all(v: np.ndarray, times: int, iterations: int, stat: Any, at: Any) -> np.ndarray:
    """:func:`statistic_of` for every realisation at once."""
    i = np.arange(iterations, dtype=np.int64)
    if stat in ('final', 'at'):
        if stat == 'final':
            off: float = times - 1
        else:
            off = _js_min(times - 1, _js_max(0, _js_number(at)))
        out = np.full(iterations, math.nan)
        if not math.isfinite(off) or off != math.floor(off):
            return out
        idx = i * times + int(off)
        ok = (idx >= 0) & (idx < len(v))
        out[ok] = v[idx[ok]]
        return out
    if times <= 0:
        return np.full(iterations, math.nan)
    idx = i[:, None] * times + np.arange(times, dtype=np.int64)[None, :]
    ok = (idx >= 0) & (idx < len(v))
    m = np.full(idx.shape, math.nan)
    m[ok] = v[idx[ok]]
    fin = np.isfinite(m)
    if stat == 'max':
        best = np.where(fin, m, -math.inf).max(axis=1)
    else:
        best = np.where(fin, m, math.inf).min(axis=1)
    return np.where(fin.any(axis=1), best, math.nan)


def _meets_all(v: np.ndarray, c: Mapping[str, Any]) -> np.ndarray:
    """Whether each number meets the category's comparison; never where it is not finite."""
    fin = np.isfinite(v)
    op = c.get('op')
    value = _js_number(c.get('value')) if 'value' in c else math.nan
    with np.errstate(invalid='ignore'):
        if op == '>':
            hit = v > value
        elif op == '>=':
            hit = v >= value
        elif op == '<':
            hit = v < value
        elif op == '<=':
            hit = v <= value
        elif op == 'between':
            value2 = _js_number(c.get('value2')) if 'value2' in c else math.nan
            lo = _js_min(value, value2)
            hi = _js_max(value, value2)
            hit = (v >= lo) & (v <= hi)
        else:
            hit = np.zeros(len(v), dtype=bool)
    return fin & hit


def _get(run: Mapping[str, Any], key: str) -> Any:
    return run.get(key) if isinstance(run, Mapping) else getattr(run, key, None)


def classify(categories: Sequence[Mapping[str, Any]], run: Mapping[str, Any]) -> Dict[str, Any]:
    """Which category each realisation falls in: first true wins, in the order written.

    ``run`` holds ``outputs`` (each with a ``label``), ``values`` (one
    realisation-major array per output), ``iterations``, and the times as ``t``
    (or their count as ``times``); ``flat[k]`` marks an output that is one
    number per realisation, a varied parameter, whose peak, end and value at any
    time are that number.

    Returns ``{'member', 'counts', 'missing'}``: ``member[i]`` is the category's
    position, or ``len(categories)`` for Other (a ``uint16`` array); ``counts``
    has one entry per category and one more for Other; ``missing`` names the
    series the categories read that the run did not keep.
    """
    outputs = _get(run, 'outputs') or []
    values = _get(run, 'values') or []
    iterations = int(_get(run, 'iterations') or 0)
    # A result carries its times as `t`; a caller that has only the count may say `times`.
    times = _get(run, 'times')
    if times is None:
        t = _get(run, 't')
        times = len(t) if t is not None and hasattr(t, '__len__') else 0
    times = int(times)
    ncat = len(categories)
    member = np.full(iterations, ncat % 65536, dtype=np.uint16)
    counts = [0] * (ncat + 1)
    missing: List[str] = []
    column = []
    for c in categories:
        want = c.get('output')
        k = next((j for j, o in enumerate(outputs) if (o.get('label') if isinstance(o, Mapping) else None) == want), -1)
        if k < 0 and _js_truthy(want):
            missing.append(want)
        column.append(k)
    flat = _get(run, 'flat')

    def stride(k: int) -> int:
        if flat is not None and 0 <= k < len(flat) and _js_truthy(flat[k]):
            return 1
        return times

    # Category by category over every realisation at once; a realisation keeps
    # the first category it meets, which is what the application's loop with
    # its early break gives.
    placed = np.zeros(iterations, dtype=bool)
    for c in range(ncat):
        k = column[c]
        if k < 0:
            continue
        cat = categories[c]
        hit = _meets_all(_statistic_all(_f64(values[k]), stride(k), iterations, cat.get('stat'), cat.get('at')), cat)
        hit &= ~placed
        member[hit] = c % 65536
        placed |= hit
    for m in member:
        counts[int(m)] += 1
    seen = []
    for name in missing:
        if name not in seen:
            seen.append(name)
    return {'member': member, 'counts': counts, 'missing': seen}


def include_mask(categories: Sequence[Mapping[str, Any]], member: Sequence[int]) -> Optional[np.ndarray]:
    """Which realisations the displays should use: 1 to keep, 0 to screen out.

    None when every category is included, the common case, so that nothing has
    to check a mask for it. Other is always included.
    """
    if all(_js_truthy(c.get('include')) for c in categories):
        return None
    m = np.asarray(member)
    mask = np.zeros(len(m), dtype=np.uint8)
    for i, c in enumerate(m):
        c = int(c)
        mask[i] = 1 if c >= len(categories) or _js_truthy(categories[c].get('include')) else 0
    return mask


def _plus_one(at: Any) -> str:
    """``${c.at + 1}``: a number adds, a string concatenates."""
    if isinstance(at, str):
        return at + '1'
    if at is None:
        return '1'
    return _js_string(_js_number(at) + 1)


def describe_category(c: Mapping[str, Any]) -> str:
    """One line saying what a category is, for a list: ``Dose: peak > 4``."""
    stat = c.get('stat')
    if stat == 'at':
        how = f"value at time #{_plus_one(c.get('at'))}"
    else:
        how = STAT_LABEL.get(stat) if isinstance(stat, str) and stat in STAT_LABEL else _js_string(stat)
    if c.get('op') == 'between':
        cmp = f"between {_js_string(c.get('value'))} and {_js_string(c.get('value2'))}"
    else:
        cmp = f"{_js_string(c.get('op'))} {_js_string(c.get('value'))}"
    output = c.get('output')
    return f"{_js_string(output) if _js_truthy(output) else '?'}: {how} {cmp}"
