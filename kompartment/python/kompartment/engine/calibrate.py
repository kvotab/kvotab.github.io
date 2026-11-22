"""Running an optimisation against the model: calibration.

A port of the application's ``src/sim/calibrate.js``.
:mod:`kompartment.stats.optimise` knows how to walk downhill and nothing about
compartments; this is the other half -- what one evaluation *is*. Which is a
whole integration: set the parameters, work the invariants out again, solve,
and read the endpoints at the times the targets name.

**The system is built once.** Everything a candidate changes is read live --
``P`` is the array the compiled code holds and ``initial_state()`` is a call
rather than a value -- which is the same reason a probabilistic run can
integrate a thousand times off one build.

**A variable may be searched in its logarithm** (``space: 'log'``): a rate
constant known to within orders of magnitude is not usefully stepped by a
fixed amount. The search happens in whatever space the variable declares;
only ``P`` ever sees the value itself.

**An evaluation that will not solve is not an error.** A corner of the box the
solver cannot carry comes back as NaN readings -- a miss of 1e6 per target --
which every method reads as "not that way".

**How well the values are known** comes after the search: the residuals
differenced along each value about the answer, and
:func:`kompartment.stats.precision.precision_of` on what that gives -- standard
errors, ranges and correlations. Its runs are not counted among the search's
evaluations, so the steps and counts are the application's.

What the application does that it perhaps should not is done here too; see
:data:`KNOWN_QUIRKS`.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..stats.optimise import METHODS, SPACES, OptimiseError, _aborted, _lookup, _member, objective_of
from ..stats.pdf import _MISSING, _is_finite_num, _jmax, _jmin, _js_round, _js_str, _nullish, _prop, _to_number, \
    _truthy
from ..stats.precision import precision_of
from .builder import build_system
from .localsens import _as_project, parameter_slots, slot_label
from .runner import run

__all__ = ['WHENS', 'reading_of', 'variables_of', 'calibrate', 'calibration_precision', 'PRECISION_STEP',
           'KNOWN_QUIRKS']

#: Where a target is read: a time, the peak, or the end of the run.
WHENS: Dict[str, Dict[str, str]] = {
    'at': {'label': 'at a time'},
    'peak': {'label': 'at its highest'},
    'end': {'label': 'at the end of the run'},
}

#: What the application's calibration does that it perhaps should not, and
#: this port does as well: nothing, since the three that were are fixed there.
KNOWN_QUIRKS: tuple = ()


def reading_of(results: Any, target: Mapping[str, Any]) -> float:
    """One endpoint's value out of a finished run (``readingOf``).

    ``target`` is ``{output, when, time}``: the series labelled ``output``,
    read at its highest (``when: 'peak'``), at the end (``'end'``), or at the
    output time nearest ``time`` -- the nearest rather than an interpolation,
    since a target is compared against what the model says. NaN when the run
    has no such series.
    """
    want_label = _prop(target, 'output')
    o = None
    for x in results.outputs():
        label = x.get('label')
        if (label if label is not None else '') == want_label and isinstance(want_label, str):
            o = x
            break
    if o is None:
        return math.nan
    v = results.series(o)
    t = results.t
    if v is None or not len(v):
        return math.nan
    when = _prop(target, 'when')
    if when == 'peak':
        best = -math.inf
        for i in range(len(v)):
            if v[i] > best:
                best = float(v[i])
        return best
    if when == 'end':
        return float(v[len(v) - 1])
    want = _to_number(_prop(target, 'time'))
    at = 0
    gap = math.inf
    for i in range(len(t)):
        d = abs(float(t[i]) - want)
        if d < gap:
            gap = d
            at = i
    return float(v[at])


def variables_of(model: Any) -> List[Dict[str, Any]]:
    """The variables of a model, as an optimisation can offer them: every
    parameter slot, ``{'key', 'name', 'index', 'slot', 'value', 'unit'}``
    (``variablesOf``). ``unit`` is the slot's, as the chart labels it."""
    system = build_system(_as_project(model))
    out = []
    for e in parameter_slots(system):
        unit = e.get('unit')
        out.append({'key': slot_label(e), 'name': e['name'], 'index': e['index'], 'slot': e['slot'],
                    'value': e['value'], 'unit': '' if unit is None else unit})
    return out


def _within(want: float, got: float) -> bool:
    if not _is_finite_num(got) or not _is_finite_num(want):
        return False
    if want == 0:
        return abs(got) < 1e-12
    return abs((got - want) / want) < 0.01


def calibrate(model: Any, *, targets: Optional[Sequence[Mapping[str, Any]]] = None,
              variables: Optional[Sequence[Mapping[str, Any]]] = None, method: Any = None, max_evals: Any = None,
              seed: Any = None, on_progress: Optional[Callable[[Dict[str, Any]], Any]] = None,
              signal: Any = None, precision: Any = True) -> Dict[str, Any]:
    """Solves for the parameter values that put the endpoints where they are
    asked to be (``calibrate``).

    ``targets`` are ``{output, when, time, value, scale, weight}`` (see
    :func:`reading_of` and :func:`kompartment.stats.optimise.objective_of`);
    ``variables`` are ``{key, lower, upper, space, start}`` with ``key`` a slot
    label (:func:`kompartment.engine.localsens.slot_label`), ``space``
    'linear' or 'log', ``start`` the model's own value when not a number;
    ``method`` a key of :data:`~kompartment.stats.optimise.METHODS` ('nelder'
    when it names none); ``max_evals`` the budget (300, at least 10); ``seed``
    for differential evolution (1). ``on_progress`` hears
    ``{'evals', 'fx', 'best', 'values'}`` after every evaluation;
    ``signal`` (an object with ``aborted``, a mapping, or a callable) stops
    the search before the next one. ``precision=False`` leaves out how well
    the values are known, and the runs it takes.

    Returns ``{'ok', 'matched', 'method', 'reason', 'evals', 'ms',
    'objective', 'values', 'precision', 'targets'}``: ``values[i]`` =
    ``{'key', 'was', 'value', 'lower', 'upper', 'pinned'}`` and ``targets[i]``
    = ``{'output', 'want', 'got', 'scale'}``. ``matched`` says whether every
    target is met to 1%, which ``ok`` -- numbers came back -- does not.
    ``precision`` is :func:`kompartment.stats.precision.precision_of`'s answer
    with ``'runs'``, the runs it took, beside it: worked out after the search,
    its runs not among ``evals``; None for a search that was stopped (or a
    Stop while it was worked out), for one whose best point the model could
    not finish, and with ``precision=False``.
    """
    started = time.time()
    c = _set_up(model, targets, variables, signal)
    vars_ = c['vars']
    evaluate = c['evaluate']

    ctx = {
        'start': [v['start'] for v in vars_],
        'objective': lambda x: evaluate(x)['objective'],
        'residuals': lambda x: evaluate(x)['residuals'],
    }

    found_method = _lookup(METHODS, method)
    chosen = METHODS['nelder'] if found_method is _MISSING else found_method

    def on_step(p: Mapping[str, Any]) -> None:
        best_x = p.get('bestX')
        on_progress({  # type: ignore[misc]
            'evals': p['evals'],
            'fx': p['fx'],
            'best': p['best'],
            # In the values a reader knows, not in the search space.
            'values': [v['space']['from'](best_x[i]) for i, v in enumerate(vars_)] if best_x is not None else None,
        })

    budget = 300 if _nullish(max_evals) else max_evals
    out = _member(chosen, 'run', 'method')(ctx, {
        'lower': [v['lower'] for v in vars_],
        'upper': [v['upper'] for v in vars_],
        'max_evals': _jmax(10, _js_round(_to_number(budget))),
        'seed': 1 if _nullish(seed) else seed,
        'signal': signal,
        'on_step': on_step if callable(on_progress) else None,
    })

    # The best point, read once more so the readings reported are the ones
    # that belong to the values reported.
    readings = None
    objective = out['fx']
    residuals = None
    if out['x'] is not None:
        got = evaluate(out['x'], True)
        readings = c['readings']()
        objective = got['objective']
        residuals = got['residuals']
    values = _values_at(c, out['x']) if out['x'] is not None else []
    # How well they are known: after the search, so nothing the search decided
    # depends on it and its count of evaluations is its own. Not for a search
    # that was stopped -- a Stop is a Stop -- nor one the model could not
    # finish at its best point.
    found_precision = None
    if (out['x'] is not None and precision is not False and out['reason'] != 'stopped' and not c['stopped']()
            and all(_is_finite_num(r) for r in readings)):  # type: ignore[union-attr]
        found_precision = _precision_around(c, out['x'], residuals, values)  # type: ignore[arg-type]
    c['restore']()

    targets = c['targets']
    return {
        'ok': out['x'] is not None and _is_finite_num(objective),
        'matched': readings is not None and all(
            _within(_to_number(_prop(t, 'value')), readings[i]) for i, t in enumerate(targets)),
        'method': 'nelder' if _nullish(method) else method,
        'reason': out['reason'],
        'evals': out['evals'],
        'ms': int(round((time.time() - started) * 1000)),
        'objective': objective,
        'values': values,
        'precision': found_precision,
        'targets': [{'output': _prop(t, 'output'), 'want': _to_number(_prop(t, 'value')),
                     'got': readings[i] if readings is not None else math.nan,
                     'scale': 'relative' if _nullish(_prop(t, 'scale')) else _prop(t, 'scale')}
                    for i, t in enumerate(targets)],
    }


def _set_up(model: Any, targets: Optional[Sequence[Mapping[str, Any]]],
            variables: Optional[Sequence[Mapping[str, Any]]], signal: Any) -> Dict[str, Any]:
    """What every evaluation needs, set up once (``setUp``): the targets, the
    variables in the space each is searched in, and what one evaluation is --
    the parameters set, the invariants worked out again, a run, the endpoints
    read -- with the way back to what the model held before."""
    project = _as_project(model)
    targets = [t for t in (targets if targets is not None else []) if _truthy(t) and _truthy(_prop(t, 'output'))]
    if not targets:
        raise OptimiseError('No endpoint has been given a target value.')
    wanted = list(variables) if variables is not None else []
    if not wanted:
        raise OptimiseError('No parameter has been allowed to vary.')

    system = build_system(project)
    by_label: Dict[Any, Dict[str, Any]] = {}
    for e in parameter_slots(system):
        by_label[slot_label(e)] = e
    vars_: List[Dict[str, Any]] = []
    for v in wanted:
        key = _prop(v, 'key')
        found = by_label.get(key) if isinstance(key, str) else None
        if found is None:
            raise OptimiseError(f"'{_js_str(key)}' is not a parameter of this model.")
        space = _lookup(SPACES, _prop(v, 'space'))
        if space is _MISSING:
            space = SPACES['linear']
        lo = _to_number(_prop(v, 'lower'))
        hi = _to_number(_prop(v, 'upper'))
        if not (hi > lo):
            raise OptimiseError(f"'{_js_str(key)}' has no range: {_js_str(lo)} to {_js_str(hi)}.")
        # A range that does not end gives a search no size to start from.
        if not (math.isfinite(lo) and math.isfinite(hi)):
            raise OptimiseError(f"'{_js_str(key)}' needs finite bounds: {_js_str(lo)} to {_js_str(hi)}.")
        if not _member(space, 'ok', 'space')(lo, hi):
            raise OptimiseError(f"'{_js_str(key)}' is searched in the logarithm, so both bounds have to be above "
                                'zero.')
        s = _to_number(_prop(v, 'start'))
        at0 = s if math.isfinite(s) else found['value']
        to = space['to']
        vars_.append({
            'key': key,
            'slot': int(found['slot']),
            'space': space,
            'lower': to(lo),
            'upper': to(hi),
            'start': to(_jmin(hi, _jmax(lo, at0 if _is_finite_num(at0) else lo))),
        })

    P = system.P
    # What the model held before any of this, so it can be put back.
    before = [float(P[v['slot']]) for v in vars_]
    last: Dict[str, Any] = {'readings': None}

    # `final` is the report's own reading of the best point, which is not a
    # step of the search and is not stopped.
    def evaluate(x: Sequence[float], final: bool = False) -> Dict[str, Any]:
        for i, v in enumerate(vars_):
            P[v['slot']] = v['space']['from'](x[i])
        system.evaluate_invariant()
        try:
            results = run(project, system=system, on_grid=True, signal=None if final else signal)
            last['readings'] = [reading_of(results, t) for t in targets]
        except Exception:  # noqa: BLE001 - a corner the solver cannot carry is a fact about the model
            last['readings'] = [math.nan for _ in targets]
        return objective_of(last['readings'], targets)

    def restore() -> None:
        for i, v in enumerate(vars_):
            P[v['slot']] = before[i]
        system.evaluate_invariant()

    return {'project': project, 'targets': targets, 'vars': vars_, 'before': before, 'evaluate': evaluate,
            'restore': restore, 'readings': lambda: last['readings'], 'stopped': lambda: _aborted(signal)}


def _values_at(c: Mapping[str, Any], x: Sequence[float]) -> List[Dict[str, Any]]:
    """The values at a point of the search, as the model holds them, and which
    sit on a bound (``valuesAt``)."""
    values: List[Dict[str, Any]] = []
    for i, v in enumerate(c['vars']):
        frm = v['space']['from']
        # Within a thousandth of the range searched, in the space it was
        # searched in, is *on* a bound -- the same rule at every bound, 0
        # included.
        reach = abs(v['upper'] - v['lower']) * 1e-3
        u = x[i]
        pinned = ('lower' if abs(u - v['lower']) <= reach else ('upper' if abs(u - v['upper']) <= reach else None))
        values.append({'key': v['key'], 'was': c['before'][i], 'value': frm(u), 'lower': frm(v['lower']),
                       'upper': frm(v['upper']), 'pinned': pinned})
    return values


#: How far each value is moved to difference the residuals for the precision:
#: a thousandth -- of the value itself where it is searched as it is, of its
#: logarithm's unit where it is searched in the logarithm, which is a tenth of
#: a per cent of the value either way -- and never more than a quarter of the
#: range (``PRECISION_STEP``).
PRECISION_STEP = 1e-3


def _precision_around(c: Mapping[str, Any], x: Sequence[float], residuals: Sequence[float],
                      values: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The precision of the values found (``precisionAround``): the residuals
    differenced along each value about the answer -- central where both sides
    are inside the bounds, one-sided against a bound -- and ``precision_of``
    on what that gives. A value on a bound is held; one the model would not
    run around is said so. None when the signal stops it part way."""
    vars_ = c['vars']
    columns: List[Optional[List[float]]] = []
    failed: List[Optional[str]] = []
    runs = 0

    def at(k: int, u: float) -> Optional[List[float]]:
        nonlocal runs
        xp = [float(e) for e in x]
        xp[k] = u
        runs += 1
        got = c['evaluate'](xp)
        return got['residuals'] if all(_is_finite_num(r) for r in c['readings']()) else None

    for k, v in enumerate(vars_):
        if c['stopped']():
            return None
        if values[k]['pinned']:
            columns.append(None)
            failed.append(None)
            continue
        span = v['upper'] - v['lower']
        own = 1 if v['space'] is SPACES['log'] else abs(x[k])
        h = min(span / 4, PRECISION_STEP * (own if own > 0 else span))
        up = x[k] + h <= v['upper']
        down = x[k] - h >= v['lower']
        col = None
        if h > 0 and up and down:
            p = at(k, x[k] + h)
            q = at(k, x[k] - h) if p is not None else None
            if p is not None and q is not None:
                col = [(pi - q[i]) / (2 * h) for i, pi in enumerate(p)]
        elif h > 0 and (up or down):
            step = h if up else -h
            p = at(k, x[k] + step)
            if p is not None:
                col = [(pi - residuals[i]) / step for i, pi in enumerate(p)]
        columns.append(col)
        failed.append(None if col is not None else 'did not run')
    out = precision_of(residuals=residuals, columns=columns, keys=[v['key'] for v in vars_],
                       spaces=['log' if v['space'] is SPACES['log'] else 'linear' for v in vars_],
                       values=[v['value'] for v in values], pinned=[v['pinned'] for v in values], failed=failed)
    out['runs'] = runs
    return out


def calibration_precision(model: Any, *, targets: Optional[Sequence[Mapping[str, Any]]] = None,
                          variables: Optional[Sequence[Mapping[str, Any]]] = None,
                          values: Optional[Sequence[Mapping[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """The precision of values a calibration found, worked out at them as
    :func:`calibrate` works it out at its own (``calibrationPrecision``):
    ``targets`` and ``variables`` as :func:`calibrate` takes them, ``values``
    a result's ``values`` in the variables' order. None when the model cannot
    be finished there."""
    c = _set_up(model, targets, variables, None)
    try:
        found = list(values) if values is not None else []
        if len(found) != len(c['vars']):
            raise OptimiseError('The values do not match the parameters that were varied.')
        x = [v['space']['to'](_to_number(_prop(found[i], 'value'))) for i, v in enumerate(c['vars'])]
        got = c['evaluate'](x, True)
        if not all(_is_finite_num(r) for r in c['readings']()):
            return None
        return _precision_around(c, x, got['residuals'], _values_at(c, x))
    finally:
        c['restore']()
