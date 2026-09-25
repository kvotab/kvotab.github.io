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
from .builder import build_system
from .localsens import _as_project, parameter_slots, slot_label
from .runner import run

__all__ = ['WHENS', 'reading_of', 'variables_of', 'calibrate', 'KNOWN_QUIRKS']

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
              signal: Any = None) -> Dict[str, Any]:
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
    the search before the next one.

    Returns ``{'ok', 'matched', 'method', 'reason', 'evals', 'ms',
    'objective', 'values', 'targets'}``: ``values[i]`` =
    ``{'key', 'was', 'value', 'lower', 'upper', 'pinned'}`` and ``targets[i]``
    = ``{'output', 'want', 'got', 'scale'}``. ``matched`` says whether every
    target is met to 1%, which ``ok`` -- numbers came back -- does not.
    """
    started = time.time()
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
    if out['x'] is not None:
        got = evaluate(out['x'], True)
        readings = last['readings']
        objective = got['objective']
    for i, v in enumerate(vars_):
        P[v['slot']] = before[i]
    system.evaluate_invariant()

    values: List[Dict[str, Any]] = []
    if out['x'] is not None:
        for i, v in enumerate(vars_):
            frm = v['space']['from']
            value = frm(out['x'][i])
            lo = frm(v['lower'])
            hi = frm(v['upper'])
            # Within a thousandth of the range searched, in the space it was
            # searched in, is *on* a bound -- the same rule at every bound, 0
            # included.
            reach = abs(v['upper'] - v['lower']) * 1e-3
            u = out['x'][i]
            pinned = ('lower' if abs(u - v['lower']) <= reach else ('upper' if abs(u - v['upper']) <= reach else None))
            values.append({'key': v['key'], 'was': before[i], 'value': value, 'lower': lo, 'upper': hi,
                           'pinned': pinned})

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
        'targets': [{'output': _prop(t, 'output'), 'want': _to_number(_prop(t, 'value')),
                     'got': readings[i] if readings is not None else math.nan,
                     'scale': 'relative' if _nullish(_prop(t, 'scale')) else _prop(t, 'scale')}
                    for i, t in enumerate(targets)],
    }
