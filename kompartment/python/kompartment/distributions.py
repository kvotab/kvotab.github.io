"""Probability distributions on parameters and lookup-table points.

A parameter carries its number in ``value`` and, beside it, the distribution a
probabilistic run draws that number from in ``pdf`` -- per index as well, in its
``entries``, since a sorption coefficient has one per nuclide and so does its
spread. A lookup table's point may carry one as its third element,
``[x, y, pdf]``.

A distribution is stored as an object::

    {"kind": "logt", "params": {"min": 1e-5, "max": 1e-3, "mode": 1e-4},
     "values": null, "trmin": null, "trmax": null, "inorder": true, "pos": 0}

This module builds those objects (:func:`make_pdf`, or one function per kind:
:func:`uniform`, :func:`log_triangular`, ...) and checks them the way the
application does (:func:`pdf_problems`).

Kinds, as Kompartment names them and with the parameters each takes:

============  ===========================  =======================================
kind          what                         params
============  ===========================  =======================================
``unif``      Uniform                      ``min``, ``max``
``triang``    Triangular                   ``min``, ``max``, ``mode``
``dtriang``   Double-triangular            ``min``, ``max``, ``mode`` (the median)
``norm``      Normal                       ``mean``, ``sd``
``logu``      Log-uniform                  ``min``, ``max``
``logt``      Log-triangular               ``min``, ``max``, ``mode``
``logdt``     Log-double-triangular        ``min``, ``max``, ``mode``
``Logn4``     Log-normal (geometric)       ``gm``, ``gsd``
``logn``      Log-normal (mean, SD)        ``mean``, ``sd``
``logn5``     Log-normal (two quantiles)   ``p1``, ``x1``, ``p2``, ``x2``
``pg``        List of values               none; the sample is in ``values``
============  ===========================  =======================================

Any of them may be truncated, by value (``trmin``, ``trmax``) or by percentile
of its own curve (``pmin``, ``pmax``, as probabilities: 0.05, not 5), and may
name a correlation ``group``.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

#: kind -> (label, [(param, must be positive)], only defined above zero, is a list)
KINDS: Dict[str, Any] = {
    'unif': ('Uniform', [('min', False), ('max', False)], False, False),
    'triang': ('Triangular', [('min', False), ('max', False), ('mode', False)], False, False),
    'dtriang': ('Double-triangular', [('min', False), ('max', False), ('mode', False)], False, False),
    'norm': ('Normal', [('mean', False), ('sd', True)], False, False),
    'logu': ('Log-uniform', [('min', True), ('max', True)], True, False),
    'logt': ('Log-triangular', [('min', True), ('max', True), ('mode', True)], True, False),
    'logdt': ('Log-double-triangular', [('min', True), ('max', True), ('mode', True)], True, False),
    'Logn4': ('Log-normal (geometric)', [('gm', True), ('gsd', True)], True, False),
    'logn': ('Log-normal (mean, SD)', [('mean', True), ('sd', True)], True, False),
    'logn5': ('Log-normal (two quantiles)', [('p1', False), ('x1', True), ('p2', False), ('x2', True)], True, False),
    'pg': ('List of values', [], False, True),
}

#: The kinds, in the order the application offers them.
KIND_IDS = tuple(KINDS)


class DistributionError(ValueError):
    """A distribution that cannot be written down."""


def _num(value: Any) -> Optional[float]:
    if value is None or value == '':
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise DistributionError(f"'{value}' is not a number") from None
    if math.isnan(v) or math.isinf(v):
        raise DistributionError(f"'{value}' is not a finite number")
    return int(v) if v.is_integer() and isinstance(value, int) else v


def make_pdf(kind: str, *, values: Optional[Sequence[float]] = None,
             trmin: Optional[float] = None, trmax: Optional[float] = None,
             pmin: Optional[float] = None, pmax: Optional[float] = None,
             group: Optional[str] = None, inorder: bool = True, pos: int = 0,
             check: bool = True, **params: Any) -> Dict[str, Any]:
    """A distribution object, as Kompartment stores one.

    ``params`` are the kind's own parameters by name (see the table in this
    module's documentation); a parameter left out is stored as ``None``, which
    the application accepts as a distribution not yet filled in. ``values`` is
    the sample of a ``pg`` (list of values) distribution. With ``check`` the
    result is checked by :func:`pdf_problems` and refused if anything is wrong.
    """
    if kind not in KINDS:
        raise DistributionError(
            f"'{kind}' is not a kind of distribution ({', '.join(KIND_IDS)})")
    label, keys, _positive, is_list = KINDS[kind]
    known = [k for k, _ in keys]
    unknown = [k for k in params if k not in known]
    if unknown:
        raise DistributionError(
            f"A {label.lower()} distribution has no parameter {', '.join(map(repr, unknown))}; "
            f"it takes {', '.join(known) or 'none (give values=[...])'}")
    spec: Dict[str, Any] = {
        'kind': kind,
        'params': {k: _num(params.get(k)) for k in known},
        'values': [float(v) for v in values] if is_list else None,
        'trmin': _num(trmin),
        'trmax': _num(trmax),
    }
    if is_list and values is None:
        spec['values'] = []
    for key, v in (('pmin', pmin), ('pmax', pmax)):
        if v is not None:
            spec[key] = _num(v)
    if group is not None and str(group).strip():
        spec['group'] = str(group).strip()
    spec['inorder'] = bool(inorder)
    spec['pos'] = int(pos)
    if check:
        problems = pdf_problems(spec)
        if problems:
            raise DistributionError(' '.join(problems))
    return spec


def uniform(min: float, max: float, **truncation: Any) -> Dict[str, Any]:  # noqa: A002
    """Uniform between ``min`` and ``max``."""
    return make_pdf('unif', min=min, max=max, **truncation)


def triangular(min: float, max: float, mode: float, **truncation: Any) -> Dict[str, Any]:  # noqa: A002
    """Triangular from ``min`` to ``max``, most likely at ``mode``."""
    return make_pdf('triang', min=min, max=max, mode=mode, **truncation)


def double_triangular(min: float, max: float, mode: float, **truncation: Any) -> Dict[str, Any]:  # noqa: A002
    """Double-triangular: half the probability on each side of ``mode``."""
    return make_pdf('dtriang', min=min, max=max, mode=mode, **truncation)


def normal(mean: float, sd: float, **truncation: Any) -> Dict[str, Any]:
    """Normal with mean ``mean`` and standard deviation ``sd``."""
    return make_pdf('norm', mean=mean, sd=sd, **truncation)


def log_uniform(min: float, max: float, **truncation: Any) -> Dict[str, Any]:  # noqa: A002
    """Log-uniform between ``min`` and ``max`` (both positive)."""
    return make_pdf('logu', min=min, max=max, **truncation)


def log_triangular(min: float, max: float, mode: float, **truncation: Any) -> Dict[str, Any]:  # noqa: A002
    """Triangular in ln x (all three positive)."""
    return make_pdf('logt', min=min, max=max, mode=mode, **truncation)


def log_double_triangular(min: float, max: float, mode: float, **truncation: Any) -> Dict[str, Any]:  # noqa: A002
    """Double-triangular in ln x (all three positive)."""
    return make_pdf('logdt', min=min, max=max, mode=mode, **truncation)


def lognormal(mean: float, sd: float, **truncation: Any) -> Dict[str, Any]:
    """Log-normal by the arithmetic mean and standard deviation of the quantity."""
    return make_pdf('logn', mean=mean, sd=sd, **truncation)


def lognormal_geometric(gm: float, gsd: float, **truncation: Any) -> Dict[str, Any]:
    """Log-normal by its geometric mean and geometric standard deviation (> 1)."""
    return make_pdf('Logn4', gm=gm, gsd=gsd, **truncation)


def lognormal_quantiles(p1: float, x1: float, p2: float, x2: float, **truncation: Any) -> Dict[str, Any]:
    """Log-normal through two quantiles: a fraction ``p1`` below ``x1``, ``p2`` below ``x2``."""
    return make_pdf('logn5', p1=p1, x1=x1, p2=p2, x2=x2, **truncation)


def value_list(values: Sequence[float], in_order: bool = True, pos: int = 0,
               **truncation: Any) -> Dict[str, Any]:
    """A sample drawn somewhere else, taken one value per realisation."""
    return make_pdf('pg', values=values, inorder=in_order, pos=pos, **truncation)


def pdf_problems(spec: Optional[Dict[str, Any]]) -> List[str]:
    """What is wrong with a distribution, in words; empty when nothing is.

    The application's own checks (``pdfProblems`` in ``src/domain/pdf.js``),
    except the last, which needs its quantile arithmetic: whether the numbers
    describe a curve that can be drawn at all.
    """
    out: List[str] = []
    if not spec or spec.get('kind') not in KINDS:
        return out
    _label, keys, positive, _is_list = KINDS[spec['kind']]
    p = spec.get('params') or {}
    for key, must_be_positive in keys:
        v = p.get(key)
        if v is None:
            continue
        if must_be_positive and not v > 0:
            out.append(f'{key} has to be more than zero.')
    for key in ('pmin', 'pmax'):
        v = spec.get(key)
        if v is not None and not (0 <= v <= 1):
            out.append('A percentile truncation is a probability, so it has to be between '
                       '0 and 1 -- 0.05 for the 5th percentile, not 5.')
            break
    if spec.get('pmin') is not None and spec.get('pmax') is not None and not spec['pmax'] > spec['pmin']:
        out.append('The percentile truncation is inside out -- nothing is left between them.')
    if positive:
        for key in ('trmin', 'trmax'):
            if spec.get(key) is not None and spec[key] < 0:
                out.append('This distribution is only defined above zero, so it cannot be '
                           'truncated below it.')
                break
    kind = spec['kind']
    if kind in ('unif', 'triang', 'dtriang', 'logu', 'logt', 'logdt'):
        if p.get('min') is not None and p.get('max') is not None and not p['max'] > p['min']:
            out.append('The range is empty -- the maximum has to be above the minimum.')
    if kind in ('triang', 'dtriang', 'logt', 'logdt') and p.get('mode') is not None:
        if p.get('min') is not None and p['mode'] < p['min']:
            out.append('The most likely value is below the minimum.')
        if p.get('max') is not None and p['mode'] > p['max']:
            out.append('The most likely value is above the maximum.')
    if kind == 'Logn4' and p.get('gsd') is not None and 0 < p['gsd'] <= 1:
        out.append('A geometric standard deviation of 1 or less is a single value, not a '
                   'spread -- it has to be more than 1.')
    if kind == 'logn5':
        for key in ('p1', 'p2'):
            v = p.get(key)
            if v is not None and not (0 < v < 1):
                out.append('A quantile is a probability, so it has to be between 0 and 1.')
                break
        if p.get('p1') is not None and p.get('p2') is not None and p['p1'] == p['p2']:
            out.append('The two quantiles have to be different.')
    if spec.get('trmin') is not None and spec.get('trmax') is not None and not spec['trmax'] > spec['trmin']:
        out.append('The truncation is inside out -- nothing is left.')
    if kind == 'pg' and not spec.get('values'):
        pass  # a list not yet filled in is allowed, as it is in the application
    return out


def describe(spec: Optional[Dict[str, Any]]) -> str:
    """A distribution in a few words: ``log-triangular(min=1e-05, max=0.001, mode=0.0001)``."""
    if not spec:
        return 'none'
    kind = spec.get('kind')
    if kind not in KINDS:
        return str(kind)
    label = KINDS[kind][0].lower()
    if kind == 'pg':
        return f"{label} of {len(spec.get('values') or [])}"
    bits = [f'{k}={v:g}' if isinstance(v, (int, float)) else f'{k}=?'
            for k, v in (spec.get('params') or {}).items()]
    return f"{label}({', '.join(bits)})"
