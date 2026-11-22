"""Is the run resolved? The run set against itself solved more carefully.

A port of the application's ``src/sim/checkrun.js``, with the names
``stateLabels`` (``src/sim/jaccheck.js``) gives the states. A run is solved to
the tolerances the model gives, and nothing in it says whether they were tight
enough: the way to know is to run again with them tighter and see whether what
is read off the chart moves -- done here for every state at once, where the
run is held, so that a page checking a run its engine holds need not fetch it.

**The careful run** is the same model with both tolerances a hundred times
tighter -- a compartment's own absolute tolerance too -- the relative one never
below :data:`RTOL_FLOOR`; the step budget ten times larger where the model sets
one; every other setting the run's own. It reports at the run's own output
times, so the two are set against each other point by point; a time the
careful run does not have is read at the nearest it does.

**What a difference is measured against.** Each state's largest difference
over the run, as a share of the most that state reaches in either run -- or of
the run's absolute tolerance over its relative, where that is more. A run
**holds** when no state moved by 0.1 % of its size, **nearly holds** when none
moved by 1 %, and otherwise **does not**; the states that moved most are named.

Nothing here rounds: the comparison is absolute values, maxima and one
division, so on the same two runs it gives the application's report exactly.
"""

from __future__ import annotations

import copy
import math
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..stats.pdf import _MISSING, _jmax, _js_round, _prop, _to_number
from .farfield import cell_names
from .runner import absolute_tolerance

__all__ = ['CAREFUL', 'RTOL_FLOOR', 'HOLDS', 'NEARLY', 'tighten_tolerances', 'careful_model', 'state_labels',
           'compare_runs', 'check_run']

#: How much tighter the careful run's tolerances are.
CAREFUL = 100

#: The careful run's relative tolerance goes no lower than this.
RTOL_FLOOR = 1e-12

#: A run holds below the first, nearly holds below the second.
HOLDS = 1e-3
NEARLY = 1e-2

#: How many of the states that moved most are named.
MOST_NAMED = 6

#: The solvers whose own step budget is ten million (``PORTED_IDS``, ``auto`` aside).
_TEN_MILLION = ('dp45', 'auto_julia', 'rodas5p', 'radau5', 'fbdf', 'fbdf_krylov', 'qndf', 'kencarp4', 'trbdf2',
                'rosenbrock23', 'tsit5', 'vern7')


def _set(v: Any) -> bool:
    """``v != null && v !== ''``."""
    return v is not _MISSING and v is not None and not (isinstance(v, str) and v == '')


def tighten_tolerances(model: Dict[str, Any]) -> Dict[str, Any]:
    """Tightens a model's tolerances in place, as the careful run has them
    (``tightenTolerances``): both a hundred times tighter, the relative one no
    lower than :data:`RTOL_FLOOR`; a step budget the model sets ten times as
    large; a compartment's own absolute tolerance, and an index's, a hundred
    times tighter with the rest. Returns ``{'rtol', 'abstol', 'floor'}``,
    ``floor`` when the relative tolerance could not be tightened all the way."""
    sim = model.get('simulation')
    if not isinstance(sim, dict):
        sim = model['simulation'] = {}
    rtol = _to_number(_prop(sim, 'rtol'))
    abstol = _to_number(_prop(sim, 'abstol'))
    tighter = _jmax(RTOL_FLOOR, rtol / CAREFUL)
    sim['rtol'] = tighter
    sim['abstol'] = abstol / CAREFUL
    given = _prop(sim, 'max_steps')
    steps = _to_number(given)
    if _set(given) and math.isfinite(steps) and steps > 0:
        sim['max_steps'] = _js_round(steps * 10)
    for key in ('compartments', 'waste_packages'):
        blocks = model.get(key)
        for b in blocks if isinstance(blocks, list) else []:
            if not isinstance(b, dict):
                continue
            own = _prop(b, 'abstol')
            n = _to_number(own)
            if _set(own) and math.isfinite(n) and n > 0:
                b['abstol'] = n / CAREFUL
            entries = b.get('entries')
            for e in entries if isinstance(entries, list) else []:
                if not isinstance(e, dict):
                    continue
                v = _prop(e, 'abstol')
                x = _to_number(v)
                if _set(v) and math.isfinite(x) and x > 0:
                    e['abstol'] = x / CAREFUL
    return {'rtol': tighter, 'abstol': sim['abstol'], 'floor': tighter > rtol / CAREFUL}


def careful_model(json_model: Dict[str, Any], times: Sequence[float]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The careful run's model (``carefulModel``): the run's own with the
    tolerances tightened and the output times the run's. Returns the model and
    what :func:`tighten_tolerances` said."""
    model = copy.deepcopy(json_model)
    tightened = tighten_tolerances(model)
    model['simulation']['spacing'] = 'series'
    model['simulation']['output_times'] = [{'times': [float(x) for x in times]}]
    return model, tightened


def _nearest(t: Sequence[float], want: float) -> int:
    """The index of the time in ``t`` nearest ``want``, ``t`` sorted."""
    lo = 0
    hi = len(t) - 1
    while hi - lo > 1:
        mid = (lo + hi) >> 1
        if t[mid] <= want:
            lo = mid
        else:
            hi = mid
    return hi if abs(t[hi] - want) < abs(t[lo] - want) else lo


def state_labels(layout: Any) -> List[str]:
    """What each state is called (``stateLabels``): a block's name with its
    index, a far-field path's with the cell, ``state i`` for one nothing names."""
    from .runner import describe_entry
    labels: List[Optional[str]] = [None] * layout.nstate
    space = layout.index_space
    for entry in layout.states or []:
        try:
            farf = entry.get('farf')
            if entry.kind == 'farfield' and farf is not None:
                nnuc, other_dims, other_width = farf.nnuc, list(farf.other_dims), farf.other_width
                ncells, list_name = farf.ncells, farf.list_name
                names = space.index_names(list_name) if list_name else [None]
                try:
                    cells: Optional[List[str]] = cell_names(entry.block)
                except Exception:  # noqa: BLE001 - as the application, which catches anything
                    cells = None
                for o in range(other_width):
                    others = space.tuple_at(other_dims, o) if other_dims else []
                    base = entry.base + o * ncells * nnuc
                    for m in range(nnuc):
                        index = []
                        k = 0
                        for dim in entry.dims or []:
                            if dim == list_name:
                                index.append(names[m])
                            else:
                                index.append(others[k])
                                k += 1
                        suffix = f" [{', '.join('' if x is None else str(x) for x in index)}]" if index else ''
                        for cell in range(ncells):
                            name = (cells[cell] if cells is not None and cell < len(cells) and cells[cell] is not None
                                    else f'cell {cell + 1}')
                            labels[base + cell * nnuc + m] = f'{entry.name}{suffix} {name}'
                continue
            for d in describe_entry(layout, entry, entry.kind, 'y'):
                labels[d['offset']] = d['label']
        except Exception:  # noqa: BLE001 - as the application, which catches anything
            for i in range(entry.width):
                labels[entry.base + i] = f'{entry.name} [{i}]' if entry.width > 1 else entry.name
    return [x if x else f'state {i}' for i, x in enumerate(labels)]


def compare_runs(held: Any, careful: Any, abstol: Any = None, labels: Optional[Sequence[str]] = None
                 ) -> Dict[str, Any]:
    """The run set against the careful one, state by state (``compareRuns``).

    ``held`` and ``careful`` are runs (:class:`kompartment.engine.runner.Results`:
    ``project``, ``system``, ``t``, ``y`` a row per time); ``abstol`` the run's
    absolute tolerance, per state or one for all (:func:`absolute_tolerance`).
    Returns ``{'verdict', 'worst', 'moved', 'states', 'times', 'sameTimes'}``,
    ``moved`` the states that moved most, each ``{'label', 'state', 'share',
    'at', 'held', 'careful'}``."""
    n = int(held.system.layout.nstate)
    rtol = _to_number(_prop(held.project.simulation, 'rtol'))
    atol = abstol if abstol is not None else absolute_tolerance(held.project, held.system.layout)
    names = list(labels) if labels is not None else state_labels(held.system.layout)
    ht = [float(x) for x in held.t]
    ct = [float(x) for x in careful.t]
    T = len(ht)
    # Each of the run's times, in the careful run.
    at = [0] * T
    same = len(ct) == T
    for k in range(T):
        at[k] = k if same and ct[k] == ht[k] else _nearest(ct, ht[k])
        if at[k] != k:
            same = False
    peak = np.zeros(n)
    diff = np.zeros(n)
    when = np.zeros(n, dtype=np.int64)
    with np.errstate(invalid='ignore'):
        for k in range(T):
            a = np.asarray(held.y[k], dtype=float)
            b = np.asarray(careful.y[at[k]], dtype=float)
            # Math.max of the two magnitudes: NaN if either is, and a NaN is never a peak.
            big = np.maximum(np.abs(a), np.abs(b))
            up = big > peak
            peak[up] = big[up]
            d = np.abs(a - b)
            # A state that is not a number in one run and is in the other is as
            # far apart as two runs can be.
            nan = np.isnan(d)
            more = (d > diff) | nan
            diff[more] = np.where(nan[more], math.inf, d[more])
            when[more] = k
    with np.errstate(divide='ignore', invalid='ignore'):
        floor = np.asarray(atol, dtype=float) / rtol
        floor = np.where(np.isfinite(floor), floor, 0.0)
        size = np.maximum(peak, floor)
        # Infinity over Infinity -- a state infinite in a run -- is NaN, as in
        # the application, where it is neither the worst nor among the moved.
        share = np.where(size > 0, diff / np.where(size > 0, size, 1.0), np.where(diff > 0, math.inf, 0.0))
    judged = share[~np.isnan(share)]
    worst = max(float(judged.max()), 0.0) if judged.size else 0.0
    moving = np.nonzero(share > 0)[0]
    order = moving[np.argsort(-share[moving], kind='stable')][:MOST_NAMED]
    moved = []
    for i in order:
        i = int(i)
        w = int(when[i])
        moved.append({
            'label': names[i] if i < len(names) and names[i] is not None else f'state {i}',
            'state': i,
            'share': float(share[i]),
            'at': ht[w],
            'held': float(held.y[w][i]),
            'careful': float(careful.y[at[w]][i]),
        })
    return {
        'verdict': 'holds' if worst < HOLDS else 'nearly' if worst < NEARLY else 'does not',
        'worst': worst,
        'moved': moved,
        'states': n,
        'times': T,
        'sameTimes': same,
    }


def _max_steps_of(model: Dict[str, Any], solver: Any) -> Any:
    """``model.simulation.max_steps ?? solverDefault('max_steps', id).value ?? null``,
    ``id`` the run's solver (``ndf`` where it names none)."""
    sim = model.get('simulation') or {}
    given = sim.get('max_steps')
    if given is not None:
        return given
    sid = 'ndf' if solver is None else solver
    if sid == 'auto':
        return None
    return 1e7 if sid in _TEN_MILLION else 1e6


def check_run(held: Any, solve: Callable[[Any], Any], model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Checks a run (``checkRun``): solves the careful run and sets the run
    against it. ``solve`` solves a :class:`~kompartment.engine.project.Project`
    -- a run with whatever signal and progress the caller has; ``model`` is
    the model the run was made of, as a project file (the project's own,
    :meth:`~kompartment.engine.project.Project.to_json`, when not given).
    Returns what :func:`compare_runs` gives, with what each run was solved at:
    ``run`` ``{'rtol', 'abstol', 'steps'}`` and ``careful`` ``{'rtol',
    'abstol', 'floor', 'ms', 'steps', 'maxSteps'}``."""
    from .project import Project
    if held is None or held.y is None or held.t is None or len(held.y) != len(held.t):
        raise ValueError('The run on show does not carry its states here, so it cannot be set against another.')
    json_model = model if model is not None else held.project.to_json()
    careful_json, tightened = careful_model(json_model, held.t)
    started = time.time()
    careful = solve(Project(careful_json))
    ms = (time.time() - started) * 1000
    report = compare_runs(held, careful)
    sim = held.project.simulation
    held_steps = (held.stats or {}).get('nsteps')
    careful_steps = (careful.stats or {}).get('nsteps')
    return {
        **report,
        'run': {'rtol': _to_number(_prop(sim, 'rtol')), 'abstol': _to_number(_prop(sim, 'abstol')),
                'steps': held_steps},
        'careful': {'rtol': tightened['rtol'], 'abstol': tightened['abstol'], 'floor': tightened['floor'], 'ms': ms,
                    'steps': careful_steps, 'maxSteps': _max_steps_of(careful_json, sim.get('solver'))},
    }
