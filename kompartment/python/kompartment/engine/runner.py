"""Runs a project and collects its results.

A port of ``src/sim/runner.js``: the solver is driven over the output grid --
restarted at every switch time, every jump and every discrete event -- and
only the states are kept. Every other series (an expression, a rate, a table
read at the clock, what a recorder holds) is worked out from ``(t, y)`` when
it is asked for, exactly as the application does.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence

import numpy as np

from ..jsonio import js_number
from .builder import BuildError, build_system, tuple_by_list
from .project import Project, value_at
from .solvers import SolverError
from .switchtimes import switch_times

MAX_SOLVER_POINTS = 4000
MAX_EVENTS = 10000
POINT_LIST = 'Time point'
HISTORY_KINDS = {'min_max', 'running_mean', 'snapshot', 'delay', 'trigger', 'event'}

SOLVER_LABELS = {
    'ndf': 'stiff, NDF', 'ros23': 'stiff, low order, Rosenbrock 2-3', 'dp45': 'non-stiff, Dormand-Prince 4-5',
    'rodas5p': 'stiff, Rosenbrock 5', 'radau5': 'stiff, Radau IIA 5', 'fbdf': 'stiff, fixed-leading-coefficient BDF',
    'qndf': 'stiff, quasi-constant-step NDF', 'kencarp4': 'stiff, ESDIRK 4',
    'trbdf2': 'stiff, ESDIRK 2 (loose tolerances)', 'scipy_bdf': 'SciPy BDF, stiff',
    'scipy_radau': 'SciPy Radau IIA, stiff', 'scipy_lsoda': 'SciPy LSODA, auto-switching',
}


def _solver_for(solver_id: str) -> Optional[Callable[..., Dict[str, Any]]]:
    from . import solverset
    return solverset.SOLVERS.get(solver_id)


def check_initial_state(system: Any, y0: np.ndarray) -> None:
    bad = np.nonzero(~np.isfinite(y0))[0]
    if not bad.size:
        return
    i = int(bad[0])
    at = next((s for s in system.layout.states if s.base <= i < s.base + s.width), None)
    where = ''
    if at is not None and at.dims:
        tup = tuple_by_list(system.layout.index_space, at.dims, i - at.base)
        where = ' at ' + ', '.join(f'{k}={v}' for k, v in tup.items())
    name = at.name if at is not None else f'State {i}'
    v = js_number(float(y0[i]))
    raise SolverError('nonfinite', f'{name} starts at {v}{where}, which is not a number the simulation can start from. '
                                   f'Its initial inventory works out to {v} -- most often a division by a parameter '
                                   'that is zero, or a log or square root of one.', 0.0)


def absolute_tolerance(project: Project, layout: Any) -> Any:
    """The absolute tolerance per state, or one number when nothing asked for more."""
    fallback = float(project.simulation['abstol'])
    per_state = np.full(layout.nstate, fallback)
    asked = False
    for s in layout.states:
        if s.kind not in ('compartment', 'waste_package'):
            continue
        for off in range(s.width):
            v = value_at(s.block, 'abstol', tuple_by_list(layout.index_space, s.dims, off))
            if v is None or v == '':
                continue
            try:
                n = float(v)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(n) or not (n > 0):
                continue
            per_state[s.base + off] = n
            asked = True
    return per_state if asked else fallback


def non_negative_states(project: Project, system: Any) -> List[bool]:
    out = [False] * system.nstate
    if project.simulation.get('non_negative') is False:
        return out
    for s in system.layout.states:
        if s.kind not in ('compartment', 'waste_package'):
            continue
        for i in range(s.width):
            v = value_at(s.block, 'non_negative', tuple_by_list(system.layout.index_space, s.dims, i))
            out[s.base + i] = v is not False
    return out


def _stop_asked(signal: Any) -> bool:
    """``signal?.aborted``: an object with ``aborted``, a mapping with that key,
    or a callable answering whether to stop."""
    if signal is None:
        return False
    if callable(signal):
        return bool(signal())
    if isinstance(signal, dict):
        return bool(signal.get('aborted'))
    return bool(getattr(signal, 'aborted', False))


def jumps_of(system: Any) -> List[Any]:
    """Every jump the state makes in a run of ``system``, as ``(jump, at)``:
    waste packages failing all at one time, at the time their slot holds -- read
    now, since a probabilistic run moves the parameter behind it -- and a
    disruptive event's occurrences, one per occurrence (``jumpsOf``)."""
    out = []
    for j in system.jumps:
        if j.slot is not None:
            out.append((j, system.slot_value(j.slot)))
        else:
            for at in (j.times() if j.times else []):
                out.append((j, at))
    return out


def run(project: Any, system: Any = None, on_progress: Optional[Callable[[float, float], Any]] = None,
        on_grid: bool = False, signal: Any = None, equations: Optional[Dict[str, Any]] = None,
        workers: Optional[int] = None, compiled: Any = 'auto') -> 'Results':
    """Runs a project (a :class:`Project`, a model dict, or a :class:`kompartment.Model`).

    ``signal`` (an object with ``aborted``, a mapping, or a callable) stops the
    run, read with the progress, as the application reads it: only when
    ``on_progress`` is given, and for a model with nothing to integrate once it
    is done. ``equations`` is a system of equations standing over the model's
    own, integrated by this run's machinery in its place (the application's
    ``opts.equations``, and ``kompartment.engine.localsens`` its one user):
    ``{'dydt', 'y0', 'abstol', 'jacobian', 'solver', 'on_segment'}``, the first
    ``nstate`` entries of ``y0`` being the model's states.

    A run that builds its own system is solved in its independent parts on
    several processes when ``simulation.split`` says so and the plan agrees
    (see :mod:`kompartment.engine.split`); ``workers`` caps the processes
    (every core by default), and ``stats['split']`` says what was done.

    ``compiled`` -- 'auto' (the default), True or False -- is whether the
    solve runs on the compiled path (:mod:`kompartment.engine.compiled`): the
    derivative and the solver's loop compiled with numba, the same steps as
    the Python path to the last bit and several times quicker on a small
    model. 'auto' takes it when the run allows (and numba is installed),
    True insists (raising ``NotCompiled`` with the reason when it cannot),
    False keeps to Python. ``stats['compiled']`` says which path ran, and
    ``stats['compiled_why']`` why not, when it was not.
    """
    if not isinstance(project, Project):
        raw = project.to_dict() if hasattr(project, 'to_dict') else project
        project = Project(raw)
    if system is None and equations is None:
        from .split import run_whole_or_split
        return run_whole_or_split(project, on_progress=on_progress, on_grid=on_grid, signal=signal, workers=workers,
                                  compiled=compiled)
    t0 = time.perf_counter()
    system = system if system is not None else build_system(project)
    build_ms = (time.perf_counter() - t0) * 1000
    grid = project.time_grid()
    eq = equations or {}
    y0 = eq['y0'] if eq.get('y0') is not None else system.initial_state()
    check_initial_state(system, y0)
    nstate = system.nstate
    # As long as the vector integrated: the model's states come first, and
    # nothing after them is an inventory.
    non_negative = non_negative_states(project, system) + [False] * (len(y0) - system.nstate)
    abstol = eq['abstol'] if eq.get('abstol') is not None else absolute_tolerance(project, system.layout)
    steps = ({'t': [], 'y': [], 'stride': 1, 'seen': 0, 'last': -math.inf}
             if project.solver_points and not on_grid else None)
    span = np.array([grid[0], grid[-1]]) if steps is not None and project.output_mode == 'solver' else grid

    def collect(t: float, y: np.ndarray) -> None:
        if not (t > steps['last']):  # type: ignore[index]
            return
        steps['last'] = t  # type: ignore[index]
        seen = steps['seen']  # type: ignore[index]
        steps['seen'] = seen + 1  # type: ignore[index]
        if seen % steps['stride']:  # type: ignore[index]
            return
        steps['t'].append(t)  # type: ignore[index]
        steps['y'].append(np.array(y, dtype=float))  # type: ignore[index]
        if len(steps['t']) >= MAX_SOLVER_POINTS * 2:  # type: ignore[index]
            steps['t'] = steps['t'][::2]  # type: ignore[index]
            steps['y'] = steps['y'][::2]  # type: ignore[index]
            steps['stride'] *= 2  # type: ignore[index]

    solve_start = time.perf_counter()
    if nstate == 0:
        empty = np.zeros(0)
        solution = {'t': grid, 'y': [empty for _ in grid], 'stats': {'solver': None, 'integrated': False,
                                                                      'points': len(grid)}}
        if system.has_store_step:
            system.prime_recorders(float(grid[0]), empty)
            for tt in grid:
                system.store_step(float(tt), empty)
        if on_progress:
            on_progress(1.0, float(grid[-1]))
        if _stop_asked(signal):
            raise RuntimeError('Cancelled')
        return Results(project, system, solution, {'build_ms': build_ms,
                                                   'solve_ms': (time.perf_counter() - solve_start) * 1000})
    solver_id = eq.get('solver') or project.simulation.get('solver') or 'ndf'
    solver = _solver_for(solver_id)
    if solver is None:
        known = ', '.join(SOLVER_LABELS)
        raise ValueError(f"Unknown solver '{solver_id}'. Available: {known}.")
    system.prime_recorders(float(grid[0]), y0)
    sim = project.simulation

    def _step(fraction: float, at: float) -> bool:
        # The stop is read with the progress, as the application reads it.
        if _stop_asked(signal):
            return False
        on_progress(fraction, at)  # type: ignore[misc]
        return True

    on_accepted: Optional[Callable[[float, np.ndarray], None]] = None
    if steps is not None and system.has_store_step:
        def on_accepted(t: float, y: np.ndarray) -> None:
            system.store_step(t, y)
            collect(t, y)
    elif steps is not None:
        on_accepted = collect
    elif system.has_store_step:
        on_accepted = system.store_step
    opts: Dict[str, Any] = {
        'rtol': float(sim['rtol']), 'abstol': abstol,
        'jacobian': _jacobian_option(system, sim),
        'non_negative': non_negative,
        'auto_abstol': sim.get('auto_abstol') is True,
        'hmax': sim.get('max_step') if (sim.get('max_step') or 0) > 0 else None,
        'h0': sim.get('initial_step') if (sim.get('initial_step') or 0) > 0 else None,
        'max_steps': sim.get('max_steps'), 'max_order': sim.get('max_order'), 'min_order': sim.get('min_order'),
        'bdf': sim.get('bdf') is True, 'norm_control': sim.get('norm_control') is True,
        'error_norm': sim.get('error_norm'), 'newton_kappa': sim.get('newton_kappa'),
        'stagnation_tol': sim.get('stagnation_tol'), 'max_jac_age': sim.get('max_jac_age'),
        'below_tol_run': sim.get('below_tol_run'), 'matrix': sim.get('matrix'),
        'on_accepted': on_accepted,
        'on_output': system.store_step if system.has_store_step else None,
        'ends_only': steps is not None and project.output_mode == 'solver',
        'events': system.events,
        'on_step': (lambda fraction, n, at: _step(fraction, at)) if on_progress else None,
    }
    if equations is not None:
        opts['jacobian'] = eq.get('jacobian')
    jumps = jumps_of(system)
    for j, at in jumps:
        if j.slot is None:
            continue
        if not math.isfinite(at) or system.slot_class[j.slot] != 0:
            raise BuildError(f"The time every package fails has to come to a number before the run; '{j.name}' says "
                             f"'{j.text}'.", j.name)

    def inside(t: float) -> bool:
        return span[0] < t < span[-1]

    breaks = sorted({b for b in [*switch_times(project), *(at for _, at in jumps)] if inside(b)})
    jumped = [0]

    def jump_at(t: float, y: np.ndarray) -> np.ndarray:
        due = [j for j, at in jumps if at == t]
        if not due:
            return y
        nxt = np.array(y, dtype=float)
        for j in due:
            j.apply(nxt)
        jumped[0] += len(due)
        return nxt

    min_change = float(sim.get('min_change_time') or 0)
    f = eq['dydt'] if eq.get('dydt') is not None else system.rhs
    on_segment = eq.get('on_segment')
    compiled_run, compiled_why = _compiled_run(compiled, system, solver_id, opts, min_change, steps is not None,
                                               equations is not None)

    def solve_span(grid2: np.ndarray, start: np.ndarray) -> Dict[str, Any]:
        system.use_clock_interpolation(min_change, float(grid2[0]))
        if on_segment is not None:
            on_segment(float(grid2[0]), min_change)
        if system.events is not None:
            return solve_with_events(system, f, solver, grid2, start, opts)
        if compiled_run is not None:
            return compiled_run(grid2, start)
        return solver(f, grid2, start, opts)

    try:
        # One error state for the whole solve: the derivative (System.rhs)
        # sets none of its own. A division by zero or an overflow is the
        # model's, reported by the solver as a non-finite state, not a warning.
        with np.errstate(all='ignore'):
            if compiled_run is None:
                solution = (solve_across_breaks(solve_span, span, y0, breaks, jump_at if jumps else None) if breaks
                            else solve_span(span, y0))
            else:
                from .compiled.run import HistoryFull, UsePython, restart_state
                tolerances = restart_state(abstol)
                while True:
                    compiled_run.start()
                    try:
                        solution = (solve_across_breaks(solve_span, span, y0, breaks, jump_at if jumps else None)
                                    if breaks else solve_span(span, y0))
                        break
                    except (HistoryFull, UsePython) as e:
                        # Made again from the start: with more room for the
                        # histories, or on the Python path.
                        compiled_run.finish()
                        if isinstance(e, UsePython):
                            if compiled is True:
                                raise
                            compiled_run, compiled_why = None, str(e)
                        else:
                            compiled_run.grow()
                        if tolerances is not None:
                            abstol[:] = tolerances
                        jumped[0] = 0
                        system.prime_recorders(float(grid[0]), y0)
                        if compiled_run is None:
                            solution = (solve_across_breaks(solve_span, span, y0, breaks, jump_at if jumps else None)
                                        if breaks else solve_span(span, y0))
                            break
                    except BaseException:
                        compiled_run.finish()
                        raise
                if compiled_run is not None:
                    if steps is not None:
                        compiled_run.steps_into(steps)
                    compiled_run.finish()
        if solution.get('stats') is not None:
            solution['stats']['compiled'] = compiled_run is not None
            if compiled_why and compiled_run is None:
                solution['stats']['compiled_why'] = compiled_why
        if jumps and solution.get('stats') is not None:
            solution['stats']['jumps'] = jumped[0]
        if steps is not None:
            solution = merge_steps(solution, steps) if project.output_mode == 'both' else from_steps(steps, solution)
    except SolverError as e:
        hints = []
        if solver_id == 'dp45':
            hints.append(f'This model looks stiff; switch the solver to "{SOLVER_LABELS["ndf"]}" or '
                         f'"{SOLVER_LABELS["ros23"]}".')
        said = 'cannot go negative' in str(e)
        if not said and solver_id != 'ndf' and any(non_negative):
            hints.append('If a compartment reaches zero at this time, its "cannot go negative" setting is the likely '
                         f'cause: "{SOLVER_LABELS["ndf"]}" carries a binding constraint, and turning the setting off '
                         'on that compartment shows what the model is really doing.')
        if hints:
            e.hint = ' '.join(hints)
        raise
    return Results(project, system, solution, {'build_ms': build_ms,
                                               'solve_ms': (time.perf_counter() - solve_start) * 1000,
                                               'total_ms': (time.perf_counter() - t0) * 1000})


def _compiled_run(compiled: Any, system: Any, solver_id: str, opts: Dict[str, Any], min_change: float,
                  solver_points: bool, equations: bool) -> Any:
    """``(compiled solver, None)`` for a run that takes the compiled path,
    ``(None, why not)`` for one that does not."""
    if compiled is False or compiled is None:
        return None, None
    from .compiled import NotCompiled
    try:
        from .compiled.run import prepare
    except ImportError as e:
        if compiled is True:
            raise NotCompiled(f'numba is not installed ({e})') from None
        return None, f'numba is not installed ({e})'
    try:
        return prepare(system, solver_id, opts, min_change=min_change, solver_points=solver_points,
                       equations=equations), None
    except NotCompiled as e:
        if compiled is True:
            raise
        return None, str(e)
    except Exception as e:  # noqa: BLE001 - a model the compiler trips on: 'auto' runs it on the Python path
        if compiled is True:
            raise
        return None, f'the compiler failed on it ({type(e).__name__}: {e})'


def _jacobian_option(system: Any, sim: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    j = system.jacobian
    if not j or j.get('pattern') is None:
        return None
    if sim.get('jacobian') == 'numeric':
        return {'pattern': j['pattern'], 'groups': j['groups'], 'constant': False, 'evaluate': None}
    return j


def from_steps(steps: Dict[str, Any], solution: Dict[str, Any]) -> Dict[str, Any]:
    t = [float(solution['t'][0])]
    y = [solution['y'][0]]
    for tt, yy in zip(steps['t'], steps['y']):
        if not (tt > t[-1]):
            continue
        t.append(tt)
        y.append(yy)
    end_t = float(solution['t'][-1])
    if end_t > t[-1]:
        t.append(end_t)
        y.append(solution['y'][-1])
    stats = dict(solution.get('stats') or {})
    stats.update(points=len(t), solver_points=steps['seen'], thinned_by=steps['stride'] if steps['stride'] > 1 else 0)
    return {**solution, 't': np.array(t), 'y': y, 'stats': stats}


def merge_steps(solution: Dict[str, Any], steps: Dict[str, Any]) -> Dict[str, Any]:
    t: List[float] = []
    y: List[np.ndarray] = []

    def push(tv: float, yv: np.ndarray) -> None:
        if t and abs(tv - t[-1]) <= abs(t[-1] or tv) * 1e-9:
            return
        t.append(tv)
        y.append(yv)

    i = j = 0
    st, sy = solution['t'], solution['y']
    while i < len(st) or j < len(steps['t']):
        a = float(st[i]) if i < len(st) else math.inf
        b = steps['t'][j] if j < len(steps['t']) else math.inf
        if a <= b:
            push(a, sy[i])
            i += 1
        else:
            push(b, steps['y'][j])
            j += 1
    stats = dict(solution.get('stats') or {})
    stats.update(points=len(t), solver_points=steps['seen'], thinned_by=steps['stride'] if steps['stride'] > 1 else 0)
    return {**solution, 't': np.array(t), 'y': y, 'stats': stats}


def solve_across_breaks(solve: Callable[[np.ndarray, np.ndarray], Dict[str, Any]], grid: np.ndarray, y0: np.ndarray,
                        breaks: Sequence[float],
                        jump_at: Optional[Callable[[float, np.ndarray], np.ndarray]] = None) -> Dict[str, Any]:
    """Integrates in segments, restarting at every declared corner."""
    times: List[float] = []
    rows: List[np.ndarray] = []
    stats: Dict[str, Any] = {'nsteps': 0, 'nfailed': 0, 'nfevals': 0, 'restarts': 0, 'breaks': len(breaks)}
    ends = [*breaks, float(grid[-1])]
    y = y0
    at = float(grid[0])
    nxt = 0
    for end in ends:
        if not (end > at):
            continue
        inside = [at]
        while nxt < len(grid) and grid[nxt] <= at:
            nxt += 1
        while nxt < len(grid) and grid[nxt] < end:
            inside.append(float(grid[nxt]))
            nxt += 1
        inside.append(end)
        seg = solve(np.array(inside), y)
        for i, tt in enumerate(seg['t']):
            if i == 0 and times and tt == times[-1]:
                continue
            times.append(float(tt))
            rows.append(seg['y'][i])
        s = seg.get('stats') or {}
        for key in ('nsteps', 'nfailed', 'nfevals', 'restarts'):
            stats[key] += s.get(key, 0) or 0
        if s:
            if not stats.get('solver') and s.get('solver'):
                stats['solver'] = s['solver']
            if s.get('sparse') is not None:
                stats['sparse'] = s['sparse']
            if s.get('fill') is not None:
                stats['fill'] = s['fill']
            for key in ('npds', 'ndecomps', 'negative', 'events'):
                if s.get(key) is not None:
                    stats[key] = stats.get(key, 0) + s[key]
            if s.get('held') is not None:
                stats['held'] = s['held'] if stats.get('held') is None else stats['held'] + s['held']
        y = seg['y'][-1]
        at = float(seg['t'][-1])
        if jump_at is not None:
            y = jump_at(at, y)
    stats['restarts'] += len(ends) - 1
    return {'t': np.array(times), 'y': rows, 'stats': stats}


def solve_with_events(system: Any, f: Callable[..., np.ndarray], solver: Callable[..., Dict[str, Any]],
                      grid: np.ndarray, y0: np.ndarray,
                      opts: Dict[str, Any]) -> Dict[str, Any]:
    """Integrates a model with discrete events, restarting at each crossing."""
    events = system.events
    last = float(grid[-1])
    times: List[float] = []
    rows: List[np.ndarray] = []
    stats: Dict[str, Any] = {'nsteps': 0, 'nfailed': 0, 'nfevals': 0, 'events': 0, 'restarts': 0}
    t = float(grid[0])
    y = y0
    nxt = 0
    guard = 0
    while True:
        if guard > MAX_EVENTS:
            raise RuntimeError(f'The simulation hit {MAX_EVENTS} discrete events without reaching t={last}. An event '
                               'whose two expressions stay equal fires again the moment the solver restarts; check '
                               'the crossing direction.')
        guard += 1
        while nxt < len(grid) and grid[nxt] <= t:
            nxt += 1
        if nxt >= len(grid):
            break
        span = np.concatenate([[t], grid[nxt:]])
        seg = solver(f, span, y, opts)
        for i, tt in enumerate(seg['t']):
            if i == 0 and times and tt == times[-1]:
                continue
            times.append(float(tt))
            rows.append(seg['y'][i])
        s = seg['stats']
        stats['nsteps'] += s.get('nsteps', 0) or 0
        stats['nfailed'] += s.get('nfailed', 0) or 0
        stats['nfevals'] += s.get('nfevals', 0) or 0
        stats.setdefault('solver', s.get('solver'))
        stats['sparse'] = s.get('sparse', stats.get('sparse'))
        stats['negative'] = stats.get('negative', 0) + (s.get('negative') or 0)
        if s.get('held') is not None:
            stats['held'] = s['held'] if stats.get('held') is None else stats['held'] + s['held']
        stopped = seg.get('stopped')
        if not stopped:
            break
        t = stopped['t']
        y = stopped['y']
        events.fire(stopped['which'], t, y)
        system.store_step(t, y)
        stats['events'] += len(stopped['which'])
        stats['restarts'] += 1
    return {'t': np.array(times), 'y': rows, 'stats': stats}


# --- what a run reports -----------------------------------------------------------------------

def _material_dim(layout: Any, dims: Sequence[str]) -> Optional[str]:
    space, material = layout.index_space, layout.material_list
    root = space.get(material).root_name if material else None
    for d in dims:
        if not root or not space.has(d):
            continue
        lst = space.get(d)
        if not lst.mapping and lst.root_name == root:
            return d
    return None


def time_dependent_of(layout: Any, kind: str, source: str, offset: int) -> bool:
    if source == 'P':
        return False
    if source == 'X' and kind not in HISTORY_KINDS:
        return int(layout.slot_class[offset]) != 0
    return True


def describe_entry(layout: Any, entry: Any, kind: str, source: str) -> List[Dict[str, Any]]:
    """The series one layout entry stands for: one per index tuple, or one."""
    space = layout.index_space
    dims = list(entry.dims or [])
    block = entry.get('block') or {}
    unit = entry.get('unit') if entry.get('unit') is not None else (block.get('unit') or '')

    def still(offset: int) -> Dict[str, Any]:
        return {} if time_dependent_of(layout, kind, source, offset) else {'timeDependent': False}

    if not dims:
        return [{'kind': kind, 'block': entry.name, 'nuclide': None, 'index': None, 'dims': [], 'label': entry.name,
                 'unit': unit, 'source': source, 'offset': entry.base, **still(entry.base)}]
    md = _material_dim(layout, dims)
    out = []
    for off in range(entry.width):
        names = space.tuple_at(dims, off)
        material = names[dims.index(md)] if md else None
        u = unit or (layout.material_units.get(material, '') if material and kind != 'trigger' else '')
        out.append({'kind': kind, 'block': entry.name, 'nuclide': material, 'index': names, 'dims': dims,
                    'label': f"{entry.name} [{', '.join(names)}]", 'unit': u, 'source': source,
                    'offset': entry.base + off, **still(entry.base + off)})
    return out


def lookup_point_outputs(layout: Any) -> List[Dict[str, Any]]:
    out = []
    for pt in layout.lookup_points:
        dims = list(pt['dims'] or [])
        names = [pt['index'].get(d) for d in dims]
        md = _material_dim(layout, dims)
        material = pt['index'].get(md) if md else None
        at = f"@{js_number(pt['at'])}"
        out.append({'kind': 'lookup', 'block': pt['name'], 'nuclide': material, 'index': [*names, at],
                    'dims': [*dims, POINT_LIST], 'label': f"{pt['name']} [{', '.join([*names, at])}]",
                    'unit': pt['unit'] or (layout.material_units.get(material, '') if material else ''),
                    'source': 'P', 'offset': pt['slot'], 'timeDependent': False})
    return out


def farfield_outputs(entry: Any, space: Any, material_list: Optional[str]) -> List[Dict[str, Any]]:
    from .farfield import cell_names
    farf, block = entry.farf, entry.block
    unit_text = str(block.get('unit') if block.get('unit') is not None else '')
    import re
    unit = re.sub(r'/[^/]*$', '', unit_text) or 'Bq'
    cells = cell_names(block) if block.get('report_cells') else None
    names = space.index_names(farf.list_name) if farf.list_name else [None]
    out = []
    for o in range(farf.other_width):
        others = space.tuple_at(farf.other_dims, o) if farf.other_dims else []
        base = entry.base + o * farf.ncells * farf.nnuc
        for m in range(farf.nnuc):
            nuclide = names[m]
            index = []
            k = 0
            for dim in entry.dims:
                if dim == farf.list_name:
                    index.append(nuclide)
                else:
                    index.append(others[k])
                    k += 1
            suffix = f" [{', '.join(index)}]" if index else ''
            offsets = base + np.arange(farf.ncells) * farf.nnuc + m
            out.append({'kind': 'farfield_inventory', 'block': f'{entry.name} held',
                        'nuclide': nuclide if material_list else None, 'index': index or None, 'dims': entry.dims,
                        'label': f'{entry.name} held{suffix}', 'unit': unit, 'source': 'y',
                        'offsets': offsets.astype(np.int64)})
            if not cells:
                continue
            for cell in range(farf.ncells):
                out.append({'kind': 'farfield_cell', 'block': f'{entry.name}.{cells[cell]}',
                            'nuclide': nuclide if material_list else None, 'index': index or None,
                            'dims': entry.dims, 'label': f'{entry.name}.{cells[cell]}{suffix}', 'unit': unit,
                            'source': 'y', 'offset': int(base + cell * farf.nnuc + m)})
    return out


def outputs_of(system: Any, project: Project) -> List[Dict[str, Any]]:
    """Every series a run of this system can report."""
    layout = system.layout
    out: List[Dict[str, Any]] = []
    for s in layout.states:
        if s.kind == 'compartment':
            if not s.get('hidden'):
                out.extend(describe_entry(layout, s, 'compartment', 'y'))
            continue
        if s.kind == 'farfield':
            out.extend(farfield_outputs(s, layout.index_space, layout.material_list))
        if s.kind == 'waste_package':
            out.extend(describe_entry(layout, s, 'waste_inventory', 'y'))
        if s.kind == 'event':
            out.extend(describe_entry(layout, s, 'event', 'y'))
    for a in layout.algebraic:
        if a.kind == 'inflow' or a.get('hidden'):
            continue
        out.extend(describe_entry(layout, a, a.kind, 'X'))
    for p in layout.parameters:
        out.extend(describe_entry(layout, p, 'parameter', 'P'))
    out.extend(lookup_point_outputs(layout))
    from .derived import derived_outputs
    out.extend(derived_outputs(project, out))
    return out


class Results:
    """What a run produced: the states at every output time, and every other
    series worked out from them on demand."""

    def __init__(self, project: Project, system: Any, solution: Dict[str, Any], timing: Dict[str, float]) -> None:
        self.project = project
        self.system = system
        self.t = np.asarray(solution['t'], dtype=float)
        self.y = solution['y']
        self.stats = solution.get('stats') or {}
        self.timing = timing if timing is not None else {}

    @property
    def nuclides(self) -> List[str]:
        return self.system.layout.nuclides

    def outputs(self) -> List[Dict[str, Any]]:
        """Every series the run can report, as descriptors: ``label``, ``block``,
        ``kind``, ``index``, ``unit``, ``source``... One per block per index."""
        if getattr(self, '_outputs', None) is None:
            self._outputs = outputs_of(self.system, self.project)
        return self._outputs

    @property
    def labels(self) -> List[str]:
        """The label of every series, as the application's chart and table name them."""
        return [o['label'] for o in self.outputs()]

    def __getitem__(self, label: str) -> np.ndarray:
        """A series by its label: ``res['Soil [Cs-137]']``."""
        return self.series(label)

    def __contains__(self, label: object) -> bool:
        return any(o['label'] == label for o in self.outputs())

    def select(self, block: Optional[str] = None, *, kind: Optional[str] = None,
               nuclide: Optional[str] = None) -> List[Dict[str, Any]]:
        """The output descriptors of one block, one kind, one nuclide, or any mix."""
        out = []
        for o in self.outputs():
            if block is not None and o.get('block') != block:
                continue
            if kind is not None and o.get('kind') != kind:
                continue
            if nuclide is not None and o.get('nuclide') != nuclide:
                continue
            out.append(o)
        return out

    def to_dict(self, outputs: Optional[Sequence[Any]] = None) -> Dict[str, np.ndarray]:
        """``{'time': t, label: series, ...}``."""
        outs = self._resolve(outputs)
        cols = self.series_many(outs)
        return {'time': self.t.copy(), **{o['label']: c for o, c in zip(outs, cols)}}

    def to_dataframe(self, outputs: Optional[Sequence[Any]] = None) -> Any:
        """The series as a pandas DataFrame indexed by time (pandas required)."""
        import pandas as pd
        data = self.to_dict(outputs)
        t = data.pop('time')
        return pd.DataFrame(data, index=pd.Index(t, name='time'))

    def _resolve(self, outputs: Optional[Sequence[Any]]) -> List[Dict[str, Any]]:
        if outputs is None:
            return self.outputs()
        return [self._find(o) if isinstance(o, str) else o for o in outputs]

    def held_at_zero(self) -> List[Dict[str, Any]]:
        held = self.stats.get('held')
        if held is None or not self.stats.get('nsteps'):
            return []
        out = []
        layout = self.system.layout
        for i in np.nonzero(held)[0]:
            state = next((s for s in layout.states if s.base <= i < s.base + s.width), None)
            if state is None:
                continue
            if state.dims:
                tup = tuple_by_list(layout.index_space, state.dims, int(i) - state.base)
                label = f"{state.name} [{', '.join(tup.values())}]"
            else:
                label = state.name
            out.append({'label': label, 'steps': int(held[i]), 'fraction': int(held[i]) / self.stats['nsteps']})
        return sorted(out, key=lambda r: (-r['fraction'], r['label'].casefold()))

    def mass_balance(self) -> Optional[Dict[str, Any]]:
        budget = self.system.layout.budget
        if not budget:
            return None
        from .massbalance import audit
        return audit(budget, self.t, self.y, rtol=self.project.simulation.get('rtol'),
                     abstol=absolute_tolerance(self.project, self.system.layout))

    def series(self, output: Any) -> np.ndarray:
        return self.series_many([output])[0]

    def series_many(self, outputs: Sequence[Any]) -> List[np.ndarray]:
        outputs = [self._find(o) if isinstance(o, str) else o for o in outputs]
        n = self.t.size
        cols = [np.zeros(n) for _ in outputs]
        live, derived = [], []
        for k, o in enumerate(outputs):
            if o['source'] == 'P':
                cols[k][:] = self.constant_of(o)
            elif o['source'] == 'D':
                derived.append(k)
            else:
                live.append(k)
        if derived:
            from .derived import reduce as reduce_derived
            wanted = list(dict.fromkeys(outputs[k]['derived']['of'] for k in derived))
            every = self.outputs()
            frm = [o for o in (next((x for x in every if x['label'] == label), None) for label in wanted) if o]
            got = {}
            if frm:
                for o, col in zip(frm, self.series_many(frm)):
                    got[o['label']] = col
            for k in derived:
                d = outputs[k]['derived']
                src = got.get(d['of'])
                if src is None:
                    cols[k][:] = math.nan
                    continue
                v = reduce_derived(d['kind'], self.t, src, at=d.get('at'), period=d.get('period'))
                if isinstance(v, np.ndarray):
                    cols[k][:] = v[:n]
                else:
                    cols[k][:] = v
        if not live:
            return cols
        needs_x = any(outputs[k]['source'] != 'y' for k in live)
        Y = np.array(self.y) if len(self.y) else np.zeros((0, self.system.nstate))
        state_only = [k for k in live if outputs[k]['source'] == 'y']
        for k in state_only:
            o = outputs[k]
            if o.get('offsets') is not None:
                cols[k][:] = _sequential_sum(Y[:, o['offsets']])
            else:
                cols[k][:] = Y[:, o['offset']]
        alg = [k for k in live if outputs[k]['source'] != 'y']
        if needs_x and alg:
            # The slots asked for, at every output time, then whole columns of them.
            need = sorted({int(off) for k in alg for off in (outputs[k]['offsets'] if outputs[k].get('offsets')
                                                               is not None else [outputs[k]['offset']])})
            column = {off: j for j, off in enumerate(need)}
            XS = self._algebraic_rows(Y, np.asarray(need, dtype=np.int64))
            for k in alg:
                o = outputs[k]
                if o.get('offsets') is not None:
                    cols[k][:] = _sequential_sum(XS[:, [column[int(off)] for off in o['offsets']]])
                else:
                    cols[k][:] = XS[:, column[int(o['offset'])]]
        return cols

    def _algebraic_rows(self, Y: np.ndarray, need: np.ndarray) -> np.ndarray:
        """The algebraic slots ``need`` at every output time, a row per time:
        through the compiled passes when the run was compiled (the Python
        passes' numbers to the last bit, the histories read as the system
        holds them), else the Python passes."""
        n = self.t.size
        out = np.zeros((n, need.size))
        system = self.system
        if self.stats.get('compiled') and n and not getattr(system, '_min_change', 0):
            cm = getattr(system, '_compiled_model', None)
            rows = getattr(cm, 'algebraic_rows', None)
            if rows is not None:
                try:
                    cm.load()
                    rows(np.ascontiguousarray(self.t, dtype=float), np.ascontiguousarray(Y, dtype=float), need, out,
                         system.P, system.X, cm.W, cm.IW)
                    return out
                except Exception:  # noqa: BLE001 - the Python passes give the same numbers
                    pass
                finally:
                    system._clock_at = math.nan
        with np.errstate(all='ignore'):
            for i in range(n):
                system.at_instant(float(self.t[i]), self.y[i])
                system._step(float(self.t[i]), self.y[i], system.X)
                out[i] = system.X[need]
        return out

    def _find(self, label: str) -> Dict[str, Any]:
        for o in self.outputs():
            if o['label'] == label:
                return o
        raise KeyError(f"No output labelled '{label}'")

    def constant_of(self, output: Dict[str, Any]) -> Optional[float]:
        if output['source'] != 'P':
            return None
        return float(self.system.P[output['offset']])

    def total(self, block_name: str, over: Optional[Sequence[str]] = None) -> Any:
        layout = self.system.layout
        s = next((x for x in layout.states if x.name == block_name), None)
        if s is None:
            raise KeyError(f"No compartment named '{block_name}'")
        Y = np.array(self.y)
        if not over:
            return _sequential_sum(Y[:, s.base:s.base + s.width])
        keep = [d for d in s.dims if d not in over]
        groups: Dict[str, List[int]] = {}
        for off in range(s.width):
            names = layout.index_space.tuple_at(s.dims, off)
            key = '\u0000'.join(names[s.dims.index(d)] for d in keep)
            groups.setdefault(key, []).append(s.base + off)
        out = []
        for key, offs in groups.items():
            out.append({'index': key.split('\u0000') if key else [], 'dims': keep,
                        'label': f"{block_name} [{', '.join(key.split(chr(0)))}]" if keep else block_name,
                        'values': _sequential_sum(Y[:, offs])})
        if not keep and len(out) == 1:
            return out[0]['values']
        return out

    def max(self, output: Any) -> Dict[str, float]:
        v = self.series(output)
        best, at = -math.inf, float(self.t[0])
        for i in range(v.size):
            if v[i] > best:
                best, at = float(v[i]), float(self.t[i])
        return {'value': best, 'time': at}

    def csv_lines(self, outputs: Optional[Sequence[Any]] = None) -> Iterator[str]:
        from ..io.csv import csv_cell
        outputs = self.outputs() if outputs is None else [self._find(o) if isinstance(o, str) else o for o in outputs]
        yield ','.join(['time', *(csv_cell(o['label']) for o in outputs)])
        cols = self.series_many(outputs)
        for i in range(self.t.size):
            yield ','.join([js_number(float(self.t[i])), *(js_number(float(c[i])) for c in cols)])

    def to_csv(self, path: Any = None, outputs: Optional[Sequence[Any]] = None) -> Optional[str]:
        """The run as the application's CSV export: a time column, then one
        column per series, numbers written as JavaScript writes them. Written
        to ``path`` when one is given (line by line, so a large run is never
        held as one string); returned as text otherwise."""
        if path is None:
            return '\n'.join(self.csv_lines(outputs))
        from pathlib import Path
        with Path(path).open('w', encoding='utf-8', newline='') as fh:
            first = True
            for line in self.csv_lines(outputs):
                if not first:
                    fh.write('\n')
                fh.write(line)
                first = False
        return None

    @property
    def jacobian(self) -> Dict[str, Any]:
        """How df/dy was obtained, as the application's run log says it:
        ``{'available': False, 'reason'}`` for a differenced one, the analytic
        one's colours, non-zeros, density and fill otherwise."""
        from .runlog import jacobian_of
        return jacobian_of(self)

    def run_log(self) -> str:
        """The run log the application writes beside a saved run: the model,
        its settings, and how the solver went."""
        from .runlog import run_log
        return run_log(self)

    def to_hdf5(self, path: Any = None, outputs: Optional[Sequence[Any]] = None, **options: Any) -> bytes:
        """The run as an HDF5 result file, as the application's *Export to
        HDF5* writes it (the shape the assessment tools read): its bytes,
        written to ``path`` too when one is given. ``outputs`` picks the
        series (labels, indices or descriptors), every one by default; see
        :func:`kompartment.io.resultfile.results_tree` for the rest."""
        from ..io.resultfile import write_results_hdf5
        return write_results_hdf5(self, path, outputs, **options)

    def save(self, path: Any, **options: Any) -> bytes:
        """The model and this run as one archive, as *Save with results*
        writes it: the application opens it with the run in place, and so
        does :func:`kompartment.load_results`. See
        :func:`kompartment.io.dataset.dataset_archive` for the options."""
        from ..io.dataset import write_dataset
        return write_dataset(self, path, **options)

    def summary(self) -> str:
        """One line on how the run went: solver, steps, time taken."""
        st = self.stats
        parts = [f"{st.get('solver') or 'no solver'}"]
        if st.get('nsteps') is not None:
            parts.append(f"{st['nsteps']} steps")
        if st.get('nfailed'):
            parts.append(f"{st['nfailed']} failed")
        parts.append(f"{len(self.t)} output times")
        if self.timing.get('total_ms') is not None:
            parts.append(f"{self.timing['total_ms'] / 1000:.2f} s")
        held = self.held_at_zero()
        if held:
            parts.append(f'{len(held)} state(s) held at zero')
        return ', '.join(parts)

    def __repr__(self) -> str:
        return f'<Results {self.project.name!r}: {self.summary()}>'


def _sequential_sum(M: np.ndarray) -> np.ndarray:
    """Rows summed left to right, as the application's loops sum them."""
    if M.shape[1] == 0:
        return np.zeros(M.shape[0])
    acc = np.zeros(M.shape[0])
    for j in range(M.shape[1]):
        acc = acc + M[:, j]
    return acc
