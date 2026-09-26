"""How the answer moves when one parameter moves: forward sensitivities.

A port of the application's ``src/sim/localsens.js``. The other sensitivity
(:mod:`kompartment.stats.sensitivity`) asks which inputs a spread came from,
over a sample; this one asks a sharper and narrower question: at the values
the model actually holds, what is ``dy/dp``?

**The forward sensitivity equations.** Differentiate ``y' = f(t, y, p)`` with
respect to a parameter and ``S = dy/dp`` satisfies::

    S' = J·S + df/dp,      S(0) = dy0/dp

-- a linear system driven by ``df/dp``, integrated alongside the states. So the
augmented vector is ``[y, S_1, ..., S_m]`` and one solve gives the states and
every sensitivity at once.

**J·S** is the model's analytic Jacobian applied to each sensitivity block.
The application gets it from one pass of its generated tangent; here the
Jacobian's values are formed once per derivative call and multiplied in, which
is the same product to the last bit or two.

**df/dp is differentiated where the model allows it**
(:mod:`kompartment.engine.paramtangent`, the application's ``paramTangent``)
and differenced otherwise -- one forward step of ``sqrt(eps)·max(|p|, 1)``,
with the invariant pass run on either side so the perturbation reaches the
algebra worked out from the parameter. ``differenced=True`` forces the
difference, as in the application.

**The iteration matrix ignores the second derivatives**, as CVODES does: it is
the original Jacobian repeated down the diagonal, with the original colouring
repeated with it. It is also why the solve is the NDF whatever solver the model
names: a Rosenbrock method uses the whole Jacobian inside its formula.

**It is a run of the model.** The augmented system is integrated by the
runner's own machinery (``equations`` in :func:`kompartment.engine.runner.run`):
restarted at every switch time, through the discrete events, with the blocks
that remember primed and fed, the model's solver settings, each compartment's
own floor, the clock interpolation, and progress and stop.

**What the forward equations cannot carry is refused, by name** (see
:func:`uncarried`): a jump in the state, a block that remembers the path of the
run where the derivative reads it, and a parameter that places a corner of the
run.

**Tolerances.** The states take the run's own absolute tolerances; the block
of ``dy/dp`` takes them divided by ``|p|`` (CVODES's rule; a parameter at zero
takes the state's unchanged).

What the application does that it perhaps should not is done here too; see
:data:`KNOWN_QUIRKS`.
"""

from __future__ import annotations

import math
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import numpy as np

from ..errors import KompartmentError
from ..stats.pdf import _MISSING, _js_str, _jmax, _to_number
from .builder import build_system, tuple_by_list
from .jacobian import SQRT_EPS, Pattern
from .paramtangent import param_tangent
from .project import Project, value_at
from .recorders import EVENT_FIELDS
from .runner import absolute_tolerance, describe_entry, jumps_of, run
from .switchtimes import switch_times

__all__ = ['SensitivityError', 'parameter_slots', 'slot_label', 'state_series', 'uncarried', 'run_sensitivity',
           'sensitivity_problem', 'elasticity', 'step_for', 'KNOWN_QUIRKS']

#: A step that is small against the value and large against its rounding.
EPS = math.sqrt(2.0 ** -52)

#: What the application's sensitivity run does that it perhaps should not, and
#: this port does as well.
KNOWN_QUIRKS = (
    'A parameter asked for that is not a slot of the model is dropped silently, and '
    'one asked for twice is integrated twice.',
)


class SensitivityError(KompartmentError):
    """A sensitivity run that cannot be set up: no analytic Jacobian, no
    parameter named, too many, or something in the model the sensitivity
    equations cannot carry."""


def step_for(p: float) -> float:
    """``sqrt(eps)·max(|p|, 1)``: the forward step for ``p``."""
    return EPS * _jmax(abs(p), 1.0)


# --- the parameter slots ----------------------------------------------------------------

_ARRAY_INDEX = re.compile(r'0|[1-9][0-9]*')


def _is_array_index(k: Any) -> bool:
    return isinstance(k, str) and _ARRAY_INDEX.fullmatch(k) is not None and int(k) < 2 ** 32 - 1


def _js_ordered(d: Mapping[str, Any]) -> Dict[str, Any]:
    """A dictionary in the order JavaScript enumerates an object's keys: the
    integer-like ones first, ascending, then the rest as they were inserted."""
    ints = sorted((k for k in d if _is_array_index(k)), key=int)
    out = {k: d[k] for k in ints}
    out.update((k, v) for k, v in d.items() if not _is_array_index(k))
    return out


def _effective_value(block: Mapping[str, Any], key: str, index: Mapping[str, Any]) -> Any:
    """``effectiveValue`` (``src/domain/edit.js``): the most specific entry that
    sets ``key`` and matches ``index``, else the block's own -- ``_MISSING``
    where neither says anything."""
    best: Any = _MISSING
    best_score = -1
    for entry in block.get('entries') or []:
        if not isinstance(entry, Mapping) or key not in entry:
            continue
        score = 0
        ok = True
        for lst, name in (entry.get('index') or {}).items():
            if index.get(lst, _MISSING) != name:
                ok = False
                break
            score += 1
        if ok and score > best_score:
            best_score = score
            best = entry[key]
    return best if best_score >= 0 else block.get(key, _MISSING)


def parameter_slots(system: Any) -> List[Dict[str, Any]]:
    """Every parameter slot a built model has: ``{'slot', 'name', 'index',
    'value', 'unit'}``, one per index tuple (``parameterSlots``).

    ``value`` is the value the model file gives the slot, read the way the
    editor reads it; ``unit`` is the slot's as the chart labels its series.
    """
    out: List[Dict[str, Any]] = []
    layout = system.layout
    for entry in layout.get('parameters') or []:
        block, dims, base, width = entry.block, list(entry.dims or []), entry.base, entry.width
        described = describe_entry(layout, entry, 'parameter', 'P')
        for off in range(width):
            tup = _js_ordered(tuple_by_list(layout.index_space, dims, off)) if dims else {}
            out.append({'slot': base + off, 'name': entry.name, 'index': tup,
                        'value': _to_number(_effective_value(block, 'value', tup)),
                        'unit': described[off].get('unit', '') if off < len(described) else ''})
    return out


def slot_label(e: Mapping[str, Any]) -> Any:
    """``name`` or ``name[i][j]``, which is how a parameter slot is asked for
    (``slotLabel``)."""
    index = e.get('index')
    idx = list(_js_ordered(index).values()) if isinstance(index, Mapping) else []
    if not idx:
        return e.get('name')
    return f"{_js_str(e.get('name'))}[{']['.join('' if v is None else _js_str(v) for v in idx)}]"


def state_series(system: Any) -> List[Dict[str, Any]]:
    """A name for every state the solve carries, as the chart names the same
    series (``stateSeries``): ``{'offset', 'label', 'block', 'kind', 'unit',
    'hidden'}``, in the order of the state vector. Machinery -- a far-field
    path's cells, a running mean's integral, the mass balance, the inside of a
    transport chain -- is ``hidden``."""
    layout = system.layout
    out: List[Dict[str, Any]] = []
    for s in layout.states:
        if s.kind == 'compartment' and not s.get('hidden'):
            kind: Optional[str] = 'compartment'
        elif s.kind == 'waste_package':
            kind = 'waste_inventory'
        elif s.kind == 'event':
            kind = 'event'
        else:
            kind = None
        if kind is not None:
            for d in describe_entry(layout, s, kind, 'y'):
                out.append({'offset': d['offset'], 'label': d['label'], 'block': s.name, 'kind': kind,
                            'unit': d['unit'], 'hidden': False})
            continue
        for off in range(s.width):
            out.append({'offset': s.base + off, 'label': f'{s.name} #{off}' if s.width > 1 else s.name,
                        'block': s.name, 'kind': s.kind, 'unit': '', 'hidden': True})
    return out


# --- what the forward equations cannot carry --------------------------------------------

#: The blocks that remember a path rather than a state.
_PATH_KINDS = ('min_max', 'snapshot', 'delay')


def _read_by_derivative(system: Any) -> List[Any]:
    """The algebraic blocks the derivative reads, directly or through others
    (``readByDerivative``)."""
    algebraic = system.builder.algebraic
    by_name = {a.name: a for a in algebraic}

    def direct(a: Any) -> bool:
        k = a.kind
        return (k in ('transfer', 'inflow', 'compartment:dydt', 'waste_package', 'farfield', 'running_mean:target')
                or re.match(r'(waste_package|event|farfield):', k) is not None)

    reached = set()
    stack = [a.name for a in algebraic if direct(a)]
    while stack:
        name = stack.pop()
        if name in reached:
            continue
        reached.add(name)
        stack.extend(by_name[name].reads_alg if name in by_name else [])
    return [a for a in algebraic if a.name in reached]


def _switched_by_event(system: Any, rec: Any) -> bool:
    for off in range(rec.width):
        tup = tuple_by_list(system.layout.index_space, rec.dims, off) if rec.dims else {}
        for field in EVENT_FIELDS.get(rec.kind, ()):
            v = value_at(rec.block, field, tup)
            if v is not None and str(v).strip() != '':
                return True
    return False


def _with_block_moved(block: Dict[str, Any], fn: Callable[[], Any]) -> Any:
    """``fn()`` with every value of a parameter block moved a little, then put back."""
    def move(v: Any) -> Any:
        x = _to_number(v)
        return x * (1 + 1e-6) + 1e-9 if math.isfinite(x) and str('' if v is None else v).strip() != '' else v

    had_value = block.get('value', _MISSING)
    entries = block.get('entries') or []
    had_entries = [e.get('value', _MISSING) for e in entries]
    try:
        if had_value is not _MISSING:
            block['value'] = move(had_value)
        for e in entries:
            if 'value' in e:
                e['value'] = move(e['value'])
        return fn()
    finally:
        if had_value is not _MISSING:
            block['value'] = had_value
        for e, v in zip(entries, had_entries):
            if v is not _MISSING:
                e['value'] = v


def uncarried(project: Project, system: Any, wanted: Sequence[Mapping[str, Any]]) -> Optional[str]:
    """What stands between the forward equations and the right answer, in
    words, or None (``uncarried``): a jump in the state inside the run; a
    min/max, snapshot or delay -- or a running mean a discrete event switches --
    that the derivative reads; or a chosen parameter that places a corner of the
    run (a switch time, a failure window, an event's window)."""
    grid = project.time_grid()
    for j, at in jumps_of(system):
        if not (grid[0] < at < grid[-1]):
            continue
        return (f"'{j.name}' makes the state jump at t={_js_str(float(at))}, and dy/dp is not carried across a "
                'jump: after it, it depends on how the jump moves with the parameters, which the sensitivity '
                'equations do not have.')
    # A semi-analytical path's release is read by its own held state, always,
    # and it is a convolution over the whole run's inflow.
    for p in system.layout.farfields or []:
        if not p.farf.laplace:
            continue
        return (f"'{p.get('local') or p.name}' is worked out semi-analytically: its release is a convolution over "
                'what flowed into it during the run, and dy/dp through a history is not carried by the sensitivity '
                'equations, which see only the present. Work the path out on cells to run a local sensitivity '
                'analysis.')
    for a in _read_by_derivative(system):
        rec = a.get('recorder')
        if rec is None:
            continue
        if rec.kind in _PATH_KINDS or (rec.kind == 'running_mean' and _switched_by_event(system, rec)):
            name = a.get('local') or a.name
            return (f"'{name}' remembers the path of the run, and the model's rates read it: dy/dp through a "
                    'history is not carried by the sensitivity equations, which see only the present.')
    corners = switch_times(project)
    for e in wanted:
        entry = next((p for p in system.layout.parameters if p.base <= e['slot'] < p.base + p.width), None)
        if entry is None or entry.block is None:
            continue
        moved = _with_block_moved(entry.block, lambda: switch_times(project))
        if list(moved) != list(corners):
            return (f"'{slot_label(e)}' places a corner of the run (a switch time, or when something starts or "
                    'stops): moving it moves a discontinuity, and dy/dp with respect to it is an impulse the '
                    'sensitivity equations do not have.')
    return None


# --- the run ----------------------------------------------------------------------------

def _as_project(model: Any) -> Project:
    if isinstance(model, Project):
        return model
    if isinstance(model, (str, Path)):
        from ..model import Model
        model = Model.load(model)
    raw = model.to_dict() if hasattr(model, 'to_dict') else model
    return Project(raw)


def run_sensitivity(model: Any, parameters: Optional[Sequence[str]] = None, *, most: Any = None,
                    differenced: bool = False, on_progress: Optional[Callable[[float, float], Any]] = None,
                    signal: Any = None) -> Dict[str, Any]:
    """Integrates the model and ``dy/dp`` for the parameters named (``runSensitivity``).

    ``model`` is a :class:`Project`, a :class:`kompartment.Model`, a model
    dict or the path of a model file; ``parameters`` are slot labels, as
    :func:`slot_label` spells them (``'Kd[I-129]'``); ``most`` (12) refuses
    more, since each one adds a copy of the state vector to the solve;
    ``differenced`` differences ``df/dp`` even where it could be generated.
    ``on_progress(fraction, t)`` hears the run's progress, and ``signal`` (an
    object with ``aborted``, a mapping, or a callable) stops it.

    Returns ``{'t', 'y', 'sens', 'chosen', 'states', 'series', 'stats'}``: the
    output times; ``y[i]`` the series of state ``i``; ``sens[k][i]`` that of
    ``d y_i / d p_k``; ``chosen[k]`` = ``{'label', 'name', 'index', 'value'}``;
    the layout's state blocks; a name for every state (:func:`state_series`);
    and ``{'ms', 'nsteps', 'states', 'restarts'}``. Raises
    :class:`SensitivityError` where it refuses.
    """
    started = time.time()
    problem = sensitivity_problem(model, parameters, most=most, differenced=differenced)
    n, m, N = problem['n'], problem['m'], problem['n'] * (1 + problem['m'])
    # Progress and stop are read through one hook, as a run reads them, so a
    # caller with only a stop to offer still has one read.
    hear = on_progress if on_progress is not None else ((lambda fraction, at: None) if signal is not None else None)
    results = run(problem['project'], system=problem['system'], on_grid=True, on_progress=hear, signal=signal,
                  equations=problem['equations'])

    # --- unpack: the states, and one sensitivity block per parameter.
    t = np.asarray(results.t, dtype=float)
    Ymat = np.array(results.y, dtype=float).reshape(t.size, N)
    y = [Ymat[:, i].copy() for i in range(n)]
    sens = [[Ymat[:, n * (k + 1) + i].copy() for i in range(n)] for k in range(m)]
    stats = results.stats or {}
    nsteps = stats.get('nsteps')
    return {
        't': t,
        'y': y,
        'sens': sens,
        'chosen': problem['chosen'],
        'states': problem['system'].layout.states,
        'series': state_series(problem['system']),
        'stats': {'ms': int(round((time.time() - started) * 1000)), 'nsteps': 0 if nsteps is None else nsteps,
                  'states': N, 'restarts': stats.get('restarts') or 0},
    }


def sensitivity_problem(model: Any, parameters: Optional[Sequence[str]] = None, *, most: Any = None,
                        differenced: bool = False) -> Dict[str, Any]:
    """The augmented system :func:`run_sensitivity` integrates, set up and not
    solved: for a caller that wants to look at it or hand it elsewhere.

    Returns ``{'dydt', 'jacobian', 'y0', 'rtol', 'abstol', 'non_negative',
    'grid', 'n', 'm', 'chosen', 'system', 'project', 'equations'}``:
    ``dydt(t, Y)`` the right-hand side of ``Y = [y, S_1, ..., S_m]``;
    ``jacobian`` the model's own repeated down the diagonal; ``non_negative``
    the floor the run applies (each compartment's own); ``equations`` what
    :func:`run_sensitivity` hands the runner. Refuses as it refuses.
    """
    project = _as_project(model)
    system = build_system(project)
    jac = system.jacobian or {}
    if not jac.get('available'):
        reason = ('the model has no compartments to differentiate' if not system.nstate
                  else jac.get('reason'))
        raise SensitivityError('This model has no analytic Jacobian, and the sensitivity equations are driven by '
                               'it. ' + ('' if reason is None else _js_str(reason)))

    every = parameter_slots(system)
    by_label: Dict[Any, Dict[str, Any]] = {}
    for e in every:
        by_label[slot_label(e)] = e
    if isinstance(parameters, str):
        raise TypeError('parameters is a list of slot labels, not one label')
    wanted = [by_label[p] for p in (parameters if parameters is not None else [])
              if isinstance(p, str) and p in by_label]
    if not wanted:
        raise SensitivityError('Name at least one parameter to take the sensitivity to.')
    most_ = 12 if most is None else most
    if len(wanted) > _to_number(most_):
        raise SensitivityError(f'{len(wanted)} parameters at once: each one adds a copy of the whole state vector '
                               f'to the solve and an evaluation of the derivative to every step. Choose at most '
                               f'{_js_str(most_)}.')
    refusal = uncarried(project, system, wanted)
    if refusal:
        raise SensitivityError(refusal)

    n = int(system.nstate)
    m = len(wanted)
    N = n * (1 + m)
    P = system.P
    slots = [int(e['slot']) for e in wanted]

    tangent: Mapping[str, Any] = ({'available': False, 'reason': 'asked for the differenced df/dp'} if differenced
                                  else param_tangent(system))
    pvp = tangent.get('pvp') if tangent.get('available') else None
    nparam = max(1, int(system.nparam))

    pattern = jac['pattern']
    jac_evaluate = jac['evaluate']
    row_idx = np.asarray(pattern.row_idx, dtype=np.int64)
    col_of = np.asarray(pattern.col_of, dtype=np.int64)

    # The clock-only algebra may be interpolated (`min_change_time`), anchored
    # where each segment of the run starts: the runner says where. The two ends
    # it holds were worked out from the parameter as it was, so they are
    # dropped around each difference.
    clock = {'interval': 0.0, 'from': float(project.simulation['start_time'])}

    def on_segment(frm: float, interval: float) -> None:
        clock['from'] = frm
        clock['interval'] = interval

    def forget_clock() -> None:
        if clock['interval'] > 0:
            system.use_clock_interpolation(clock['interval'], clock['from'])

    def jvp(t: float, yv: np.ndarray, values: Optional[np.ndarray], f0: np.ndarray, sv: np.ndarray) -> np.ndarray:
        """J·v, off the Jacobian's values at (t, y) -- or, at a point where the
        analytic Jacobian declines (an entry that is not finite), differenced
        along v, as the solvers difference the matrix there."""
        if values is not None:
            return np.bincount(row_idx, weights=values * sv[col_of], minlength=n)
        size = float(np.max(np.abs(sv))) if sv.size else 0.0
        if not (size > 0):
            return np.zeros(n)
        delta = SQRT_EPS * max(1.0, float(np.max(np.abs(yv)))) / size
        return (np.asarray(system.dydt(t, yv + delta * sv), dtype=float) - f0) / delta

    def dydt(t: float, Y: np.ndarray) -> np.ndarray:
        Y = np.asarray(Y, dtype=float)
        yv = Y[:n].copy()
        f0 = np.array(system.dydt(t, yv), dtype=float)
        out = np.empty(N)
        out[:n] = f0
        values = jac_evaluate(t, yv)
        values = None if values is None else np.asarray(values, dtype=float)
        for j in range(m):
            base = n * (j + 1)
            jv = jvp(t, yv, values, f0, Y[base:base + n])
            slot = slots[j]
            if pvp is not None:
                seed = np.zeros(nparam)
                seed[slot] = 1.0
                out[base:base + n] = jv + np.asarray(pvp(t, yv, seed), dtype=float)
                continue
            # df/dp by one forward difference. The invariant pass carries the
            # new parameter into the algebra worked out from the old one.
            p0 = float(P[slot])
            h = step_for(p0)
            P[slot] = p0 + h
            system.evaluate_invariant()
            forget_clock()
            fp = np.array(system.dydt(t, yv), dtype=float)
            P[slot] = p0
            system.evaluate_invariant()
            forget_clock()
            out[base:base + n] = jv + (fp - f0) / h
        return out

    # --- the iteration matrix: J down the diagonal, (1 + m) times, and the
    # colouring repeated with it.
    blocks = 1 + m
    rows = np.concatenate([row_idx + b * n for b in range(blocks)])
    cols = np.concatenate([col_of + b * n for b in range(blocks)])
    big = Pattern(N, rows, cols)
    if big.nnz != rows.size or not (np.array_equal(big.row_idx, rows) and np.array_equal(big.col_of, cols)):
        raise RuntimeError('the repeated Jacobian pattern did not keep the order of its blocks')
    base_groups = jac.get('groups') or []
    big_groups = ([np.concatenate([np.asarray(g, dtype=np.int64) + b * n for b in range(blocks)])
                   for g in base_groups] if len(base_groups) else None)
    # Asked to difference its Jacobian, the model gets that here too: the
    # pattern and its colouring, and no values.
    differenced_matrix = project.simulation.get('jacobian') == 'numeric'

    def big_evaluate(t: float, Y: np.ndarray) -> Optional[np.ndarray]:
        if differenced_matrix:
            return None
        v = jac_evaluate(t, np.array(Y[:n], dtype=float))
        if v is None:
            return None
        return np.tile(np.asarray(v, dtype=float), blocks)

    big_jacobian = {'available': True, 'pattern': big, 'constant': False, 'groups': big_groups,
                    'evaluate': big_evaluate}

    # --- initial conditions, the sensitivities included. dy0/dp: an initial
    # inventory may be an equation over parameters, and where it is not this
    # is exactly zero.
    y0 = np.array(system.initial_state(), dtype=float)
    Y0 = np.zeros(N)
    Y0[:n] = y0
    for j, slot in enumerate(slots):
        p0 = float(P[slot])
        h = step_for(p0)
        P[slot] = p0 + h
        system.evaluate_invariant()
        yh = np.array(system.initial_state(), dtype=float)
        P[slot] = p0
        system.evaluate_invariant()
        Y0[n * (j + 1):n * (j + 2)] = (yh - y0) / h

    # --- tolerances: the run's own for the states, over |p| for dy/dp.
    base_atol = absolute_tolerance(project, system.layout)
    per_state = (np.full(n, float(base_atol)) if np.ndim(base_atol) == 0
                 else np.asarray(base_atol, dtype=float)[:n].copy())
    atol = np.zeros(N)
    atol[:n] = per_state
    for j, slot in enumerate(slots):
        a = abs(float(P[slot]))
        scale = a if (a == a and a != 0) else 1.0
        atol[n * (j + 1):n * (j + 2)] = per_state / scale

    # The floor the run applies -- each compartment's own -- on the states and
    # nothing after them.
    from .runner import non_negative_states
    non_negative = non_negative_states(project, system) + [False] * (N - n)

    return {
        'dydt': dydt,
        'jacobian': big_jacobian,
        'y0': Y0,
        'rtol': project.simulation['rtol'],
        'abstol': atol,
        'non_negative': non_negative,
        'grid': project.time_grid(),
        'n': n,
        'm': m,
        'chosen': [{'label': slot_label(e), 'name': e['name'], 'index': e['index'], 'value': e['value']}
                   for e in wanted],
        'system': system,
        'project': project,
        'equations': {'dydt': dydt, 'y0': Y0, 'abstol': atol, 'jacobian': big_jacobian, 'solver': 'ndf',
                      'on_segment': on_segment},
    }


def elasticity(y_row: Sequence[float], s_row: Sequence[float], p: Any) -> np.ndarray:
    """``(p / y)·(dy/dp)``: a relative change for a relative change, which is
    comparable across parameters as ``dy/dp`` is not. NaN where ``y`` is zero."""
    y = np.asarray(y_row, dtype=float)
    s = np.full(y.size, np.nan)
    given = np.asarray(s_row, dtype=float)[:y.size]
    s[:given.size] = given
    pv = _to_number(p)
    with np.errstate(all='ignore'):
        out = (pv / y) * s
    out[y == 0] = np.nan
    return out
