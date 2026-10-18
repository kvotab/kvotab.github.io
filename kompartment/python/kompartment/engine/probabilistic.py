"""Running a model many times over its distributions.

A port of ``src/sim/probabilistic.js``. A probabilistic run draws a value for
every distributed parameter (and every lookup point that carries a spread) per
realisation, integrates the model again, and keeps the series asked for --
every realisation of them, because a band is read off all of them.

**Built once, integrated many times.** Each realisation rewrites the
parameter array the compiled code reads and works the invariant algebra out
again; nothing is rebuilt. **The design is drawn whole**, whatever slice of it
one process integrates: Latin hypercube is a statement about a whole column,
and each input draws from a stream named after it, so any number of worker
processes gives the same answer, to the last bit, as one.

Besides a sample: a *tornado* (every input swung alone to a low and a high
probability) and a *global sensitivity design* (see
:mod:`kompartment.stats.gsa`) run the same way.
"""

from __future__ import annotations

import math
import numbers
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np

from ..stats.correlate import correlation_pairs, iman_conover
from ..stats.gsa import build_design, cholesky
from ..stats.sample import ValueDrawer, distributed_slots, stream_for, uniforms, value_at_probability
from .. import jsmath
from .builder import build_system, tuple_by_list
from .project import Project, value_at
from .runner import outputs_of, run

MOST_BYTES = 1073741824
MOST_BYTES_ASKED = 4 * 1073741824
MIN_VALUE = 5e-324


def can_be_endpoint(kind: Optional[str]) -> bool:
    """Anything but an input: not a parameter, not a lookup table."""
    return kind not in ('parameter', 'lookup')


def group_of(entry: Dict[str, Any]) -> Optional[str]:
    g = (entry.get('spec') or {}).get('group') if isinstance(entry.get('spec'), dict) else None
    t = '' if g is None else str(g).strip()
    return None if t == '' else t


def slot_name(entry: Dict[str, Any]) -> str:
    idx = list((entry.get('index') or {}).values())
    return f"{entry['name']}[{']['.join(idx)}]" if idx else str(entry.get('name') or '')


def _groups_of(plan: List[Dict[str, Any]], names: List[str]) -> List[Dict[str, Any]]:
    out: Dict[str, List[str]] = {}
    for k, e in enumerate(plan):
        g = group_of(e)
        if g:
            out.setdefault(g, []).append(names[k])
    return [{'name': n, 'members': m} for n, m in out.items()]


def estimate(series: int, times: int, iterations: int, precision: str = 'double') -> Dict[str, Any]:
    """Bytes a run of this shape holds (``double`` while running, ``float32`` in a file)."""
    b = series * times * iterations * (4 if precision == 'float32' else 8)
    if b >= 1073741824:
        text = f'{b / 1073741824:.1f} GB'
    elif b >= 1048576:
        text = f'{round(b / 1048576)} MB'
    else:
        text = f'{max(1, round(b / 1024))} kB'
    return {'bytes': b, 'text': text}


def hold_precision(series: int, times: int, iterations: int, most: int = MOST_BYTES) -> str:
    """``float32`` when a run of this shape would hold more than ``most`` bytes as
    doubles (a gigabyte, what a tab may hold), else ``double``."""
    return 'float32' if estimate(series, times, iterations)['bytes'] > most else 'double'


def sample_occurrences(rate: float, frm: float, until: float, stream: Callable[[], float],
                       most: int = 10000) -> List[float]:
    """A Poisson process's occurrence times between two times."""
    out: List[float] = []
    if not (rate > 0) or not (until > frm):
        return out
    t = frm
    while True:
        u = stream()
        t += -jsmath.log(u if u > 0 else MIN_VALUE) / rate
        if t >= until:
            break
        out.append(t)
        if len(out) >= most:
            break
    return out


def sampling_plan(project: Project, system: Any = None) -> List[Dict[str, Any]]:
    """The distributions a model would sample: ``[{slot, name, index, spec}]``."""
    sys_ = system if system is not None else build_system(project)
    every = distributed_slots(sys_.layout, value_at, lambda space, dims, off: tuple_by_list(space, dims, off))
    chosen = project.simulation.get('varied')
    if not isinstance(chosen, list) or not chosen:
        return every
    want = set(chosen)

    def named(e: Dict[str, Any]) -> str:
        idx = list((e.get('index') or {}).values())
        return e['name'] + ''.join(f'[{v}]' for v in idx) if idx else e['name']

    kept = [e for e in every if named(e) in want or e['name'] in want]
    return kept if kept else every


class Design:
    """What every realisation of a run sets (``designFor``)."""

    def __init__(self, plan: List[Dict[str, Any]], names: List[str], best: List[float], varies: Callable[[Any], bool],
                 iterations: int, value_for: Callable[[int, int], float], seed: int, stats: Dict[str, Any],
                 gsa_design: Any = None) -> None:
        self.plan = plan
        self.names = names
        self.best = best
        self.varies = varies
        self.iterations = iterations
        self.value_for = value_for
        self.seed = seed
        self.stats = stats
        self.gsa_design = gsa_design
        # Each input's values held over a draw that is no number, worked out the
        # first time one is met (``value_set``).
        self.held_over: Dict[int, np.ndarray] = {}


def design_for(project: Project, system: Any, *, seed: int = 1, iterations: Optional[int] = None,
               latin: bool = True, varied: Optional[Iterable[str]] = None, tornado: Optional[Dict[str, float]] = None,
               gsa: Optional[Dict[str, Any]] = None) -> Design:
    plan = sampling_plan(project, system)
    dice = any(D['timing'] == 'poisson' and D['sampled'] for D in system.layout.events)
    if not plan and not (dice and not tornado and not gsa):
        if dice:
            what = 'tornado swings' if tornado else 'sensitivity design varies'
            tail = (f', and a {what} parameters; the disruptive events are what varies here, and they need a '
                    'probabilistic run.')
        else:
            tail = (', so every realisation would be the same run. Give a parameter one first — the curve at the '
                    'end of its row in the left panel — or add a disruptive event that draws its occurrences.')
        raise ValueError('No parameter in this model has a distribution' + tail)
    names = [slot_name(e) for e in plan]
    P = system.P
    best = [float(P[e['slot']]) for e in plan]
    wanted = None if varied is None else {str(v) for v in varied}

    def varies(e: Dict[str, Any]) -> bool:
        return wanted is None or slot_name(e) in wanted

    if tornado:
        low = float(tornado.get('low', 0.05))
        high = float(tornado.get('high', 0.95))
        swung = [k for k in range(len(plan)) if varies(plan[k])]
        n = 2 * len(swung) + 1

        def value_for(k: int, i: int) -> float:
            if i == 0:
                return best[k]
            which = swung[(i - 1) // 2]
            if which != k:
                return best[k]
            return value_at_probability(plan[k]['spec'], low if (i - 1) % 2 == 0 else high, i)

        return Design(plan, names, best, varies, n, value_for, seed,
                      {'seed': seed, 'latin': False, 'sampled': len(plan),
                       'tornado': {'low': low, 'high': high, 'swung': swung}})
    if gsa:
        return _gsa_design_for(project, plan, names, best, varies, seed, gsa)
    n = max(1, int(math.floor((iterations if iterations is not None else 100) + 0.5)))
    draws = [uniforms(n, stream_for(seed, group_of(e) or slot_name(e)), latin=latin) for e in plan]
    cp = correlation_pairs(project, names)
    pairs, problems = cp['pairs'], list(cp['problems'])
    grouped = {k for k, e in enumerate(plan) if group_of(e)}
    for pr in pairs:
        if pr['a'] not in grouped and pr['b'] not in grouped:
            continue
        who = names[pr['a']] if pr['a'] in grouped else names[pr['b']]
        problems.append(f"{names[pr['a']]} and {names[pr['b']]}: {who} is in a correlation group, which already fixes "
                        'its sample. The correlation was ignored.')
    usable = [pr for pr in pairs if varies(plan[pr['a']]) and varies(plan[pr['b']])
              and pr['a'] not in grouped and pr['b'] not in grouped]
    corr = iman_conover(draws, usable, names, seed)

    # Each distribution read once: a draw is then only the arithmetic of its uniform.
    drawers = [ValueDrawer(e['spec']) for e in plan]

    def value_for_sample(k: int, i: int) -> float:
        return drawers[k].value(float(draws[k][i]), i) if varies(plan[k]) else best[k]

    return Design(plan, names, best, varies, n, value_for_sample, seed,
                  {'seed': seed, 'latin': latin, 'sampled': len(plan), 'correlated': len(corr['columns']),
                   'correlationAdjusted': corr['adjusted'], 'correlationProblems': problems,
                   'groups': _groups_of(plan, names)})


def _gsa_design_for(project: Project, plan: List[Dict[str, Any]], names: List[str], best: List[float],
                    varies: Callable[[Any], bool], seed: int, gsa: Dict[str, Any]) -> Design:
    factors: List[Dict[str, Any]] = []
    by_key: Dict[str, Dict[str, Any]] = {}
    for k, e in enumerate(plan):
        if not varies(e):
            continue
        key = group_of(e) or names[k]
        f = by_key.get(key)
        if f is None:
            f = {'key': key, 'group': group_of(e), 'members': []}
            by_key[key] = f
            factors.append(f)
        f['members'].append(k)
    if not factors:
        raise ValueError('Every sampled input is held, so a sensitivity design has nothing to vary.')
    factor_of = [-1] * len(plan)
    for j, f in enumerate(factors):
        for k in f['members']:
            factor_of[k] = j
    cp = correlation_pairs(project, names)
    pairs, problems = cp['pairs'], cp['problems']
    between = [pr for pr in pairs if factor_of[pr['a']] >= 0 and factor_of[pr['b']] >= 0
               and factor_of[pr['a']] != factor_of[pr['b']]]
    corr = None
    shrunk = 0.0
    if gsa.get('method') == 'shapley' and between:
        K = len(factors)
        R = np.zeros(K * K)
        for j in range(K):
            R[j * K + j] = 1.0
        for pr in between:
            a, b = factor_of[pr['a']], factor_of[pr['b']]
            r = 2 * math.sin((math.pi * pr['r']) / 6)
            R[a * K + b] = r
            R[b * K + a] = r
        lam = 0.0
        while lam < 1:
            S = np.array([1.0 if i % (K + 1) == 0 else (1 - lam) * v for i, v in enumerate(R)])
            if cholesky(S, K) is not None:
                corr = S
                shrunk = lam
                break
            lam += 0.05
    design = build_design(gsa['method'], [f['key'] for f in factors], gsa.get('options') or {}, seed=seed, corr=corr,
                          stream_for=stream_for, uniforms=uniforms)
    drawn = [({**e['spec'], 'inorder': False} if (e['spec'] or {}).get('kind') == 'pg'
              and (e['spec'] or {}).get('inorder') is not False else e['spec']) for e in plan]

    drawers = [ValueDrawer(s) for s in drawn]

    def value_for(k: int, i: int) -> float:
        if factor_of[k] < 0:
            return best[k]
        return drawers[k].value(float(design['u'][factor_of[k]][i]), i)

    return Design(plan, names, best, varies, int(design['runs']), value_for, seed,
                  {'seed': seed, 'latin': False, 'sampled': len(plan),
                   'gsa': {'method': gsa['method'], 'options': design.get('options'),
                           'factors': [{'key': f['key'], 'group': f['group'], 'members': f['members']}
                                       for f in factors],
                           'correlated': len(between), 'correlationsUsed': corr is not None,
                           'correlationShrunk': shrunk, 'correlationProblems': problems}},
                  gsa_design=design)


def _a_number(v: Any) -> bool:
    """JavaScript's ``Number.isFinite(v)``: a finite number, and nothing read as one
    -- a list's word, null or Boolean is not (the slot keeps what it held)."""
    return isinstance(v, numbers.Real) and not isinstance(v, bool) and math.isfinite(v)


def value_set(design: Design, k: int, i: int) -> float:
    """The value input ``k`` takes in realisation ``i`` (the application's
    ``valueSet``): what is set into the run, and what the run records of it.

    The value drawn, where that is a number. A draw that is not -- a gap in a
    list, a word or a Boolean in one, a distribution with no value there --
    leaves a varied input at the last value drawn before it that was, as one
    run going through the realisations in order holds it, and at the model's
    own where none was; an input that is held is at the model's own throughout.
    Read off the design alone, so that a realisation is the same run however
    the realisations are shared out between processes, and replayed on its own."""
    v = design.value_for(k, i)
    if _a_number(v):
        return float(v)
    if not design.varies(design.plan[k]):
        return design.best[k]
    column = design.held_over.get(k)
    if column is None:
        column = np.empty(design.iterations)
        last = design.best[k]
        for j in range(design.iterations):
            w = design.value_for(k, j)
            if _a_number(w):
                last = float(w)
            column[j] = last
        design.held_over[k] = column
    return float(column[i])


def apply_point(system: Any, design: Design, i: int) -> List[float]:
    """Sets design point ``i`` into the system, ready to run; the values set (``value_set``)."""
    P = system.P
    out = []
    for k, e in enumerate(design.plan):
        v = value_set(design, k, i)
        out.append(v)
        P[e['slot']] = v
    system.evaluate_invariant()
    draw_disruptions(system, design.seed, i, sample=not design.stats.get('tornado') and not design.stats.get('gsa'))
    return out


def draw_disruptions(system: Any, seed: int, i: int, sample: bool = True) -> None:
    """This realisation's occurrences of every random event that draws them."""
    layout = system.layout
    for D in layout.events:
        if D['timing'] != 'poisson' or not D['sampled'] or not sample:
            system.set_disruption(D['index'], sampled=False)
            continue

        def fixed(slot: Optional[int]) -> bool:
            return slot is None or int(layout.slot_class[slot]) == 0

        if not fixed(D['rate_slot']) or not fixed(D['from_slot']) or not fixed(D['until_slot']):
            system.set_disruption(D['index'], sampled=False)
            continue
        rate = system.slot_value(D['rate_slot'])
        frm = system.span_start() if D['from_slot'] is None else system.slot_value(D['from_slot'])
        until = system.span_end() if D['until_slot'] is None else system.slot_value(D['until_slot'])
        stream = stream_for(seed, f"{D['name']}#occurrences#{i}")
        system.set_disruption(D['index'], sampled=True,
                              times=sample_occurrences(rate, max(frm, system.span_start()),
                                                       min(until, system.span_end()), stream))


def _as_project(model: Any) -> Project:
    if isinstance(model, Project):
        return model
    if hasattr(model, 'project') and callable(model.project):
        return model.project()
    return Project(model)


def run_realization(model: Any, index: int, **opts: Any) -> Dict[str, Any]:
    """One realisation of a probabilistic run, as an ordinary run: every series of it."""
    project = _as_project(model)
    system = build_system(project)
    design = design_for(project, system, **_design_options(opts))
    i = min(design.iterations - 1, max(0, int(round(float(index))) if index is not None else 0))
    values = apply_point(system, design, i)
    results = run(project, system=system, compiled=opts.get('compiled', 'auto'))
    # Held: not varied, at the model's value in a tornado's point, or held over
    # from a realisation before, the draw being no number.
    return {'results': results, 'index': i, 'iterations': design.iterations,
            'values': [{'name': design.names[k], 'value': values[k],
                        'held': (not design.varies(e)) or not _a_number(design.value_for(k, i))
                        or (values[k] == design.best[k] if design.stats.get('tornado') else False)}
                       for k, e in enumerate(design.plan)]}


def _design_options(opts: Dict[str, Any]) -> Dict[str, Any]:
    return {k: opts[k] for k in ('seed', 'iterations', 'latin', 'varied', 'tornado', 'gsa') if k in opts}


def run_probabilistic(model: Any, *, iterations: int = 100, seed: int = 1, latin: bool = True,
                      varied: Optional[Iterable[str]] = None, tornado: Optional[Dict[str, float]] = None,
                      gsa: Optional[Dict[str, Any]] = None, keep: Any = None, workers: int = 1,
                      on_progress: Optional[Callable[[int, int], Any]] = None, progress: Any = False,
                      large: bool = False, range_: Optional[Sequence[int]] = None,
                      compiled: Any = 'auto', most_bytes: int = MOST_BYTES,
                      asked_bytes: int = MOST_BYTES_ASKED) -> 'ProbabilisticResults':
    """Runs ``iterations`` realisations and keeps the series asked for.

    ``keep``: which series to hold -- None for every endpoint (anything but an
    input), a list of block names or labels, or a function ``(name, output)``.
    ``workers`` > 1 shares the realisations out between processes; the design
    is drawn whole in each, so the answer does not depend on how many.
    ``tornado={'low': .05, 'high': .95}`` swings each input alone;
    ``gsa={'method': ..., 'options': {...}}`` runs a sensitivity design.
    ``compiled`` is each run's, as :func:`kompartment.engine.runner.run`
    takes it: the model compiles once, and every realisation runs compiled.

    A run that would hold more than a gigabyte as doubles keeps float32, and past
    a gigabyte even so it is refused unless ``large`` (4 GB): what a tab may hold.
    ``most_bytes`` and ``asked_bytes`` put other numbers in their place -- the
    application's, drawn from this machine's memory, for a sample the engine
    holds for its page.

    ``progress=True`` shows how far the run has got, and how long it has left,
    as a line on standard error (standard output in a notebook), or on a
    stream passed as ``progress``: see :mod:`kompartment.engine.progress`.
    ``on_progress(done, total)`` is called after every realisation, with
    ``workers`` too, for a display of the caller's own.
    """
    started = time.perf_counter()
    project = _as_project(model)
    line = None
    if progress:
        from .progress import ProgressLine
        line = ProgressLine(iterations, what='runs' if (tornado or gsa) else 'realisations',
                            stream=None if progress is True else progress)
    tell = _both(on_progress, line)
    try:
        if workers > 1:
            res = _run_pool(project.to_json(), dict(iterations=iterations, seed=seed, latin=latin, varied=varied,
                                                    tornado=tornado, gsa=gsa, keep=keep, large=large,
                                                    compiled=compiled, most_bytes=most_bytes,
                                                    asked_bytes=asked_bytes), workers, tell, started, line)
        else:
            system = build_system(project)
            design = design_for(project, system, seed=seed, iterations=iterations, latin=latin, varied=varied,
                                tornado=tornado, gsa=gsa)
            if line is not None:
                line.set_total(design.iterations)
            res = _run_slice(project, system, design, keep, range_, tell, large, started, compiled,
                             most_bytes, asked_bytes)
    except BaseException:
        if line is not None:
            line.close(stopped=True)
        raise
    if line is not None:
        line.close(failed=int(res.stats.get('failed', 0)))
    return res


def _both(on_progress: Optional[Callable[[int, int], Any]], line: Any) -> Optional[Callable[[int, int], Any]]:
    """The caller's ``on_progress`` and the progress line, as one."""
    if line is None or on_progress is None:
        return on_progress if line is None else line

    def both(done: int, total: int) -> None:
        line(done, total)
        on_progress(done, total)
    return both


def _keep_fn(keep: Any) -> Optional[Callable[[str, Dict[str, Any]], bool]]:
    if keep is None:
        return None
    if callable(keep):
        return keep
    wanted = {str(k) for k in keep}
    return lambda name, o: name in wanted or o.get('label') in wanted


def _frame(project: Project, system: Any, design: Design, keep: Any, large: bool, most: int = MOST_BYTES,
           asked: int = MOST_BYTES_ASKED) -> Dict[str, Any]:
    """What a run of ``design`` keeps, read off the built system before anything
    runs (``outputs_of``): the series and those kept, the inputs among them, the
    output grid and the precision they are held in. A run too large to hold --
    past ``most`` bytes, or ``asked`` with ``large`` -- is refused here."""
    plan, iterations = design.plan, design.iterations
    outputs = outputs_of(system, project)
    keep_fn = _keep_fn(keep)
    wanted = [k for k, o in enumerate(outputs) if can_be_endpoint(o.get('kind'))
              and (keep_fn is None or keep_fn(o.get('block') or o.get('label') or '', o))]
    column: Dict[int, int] = {}
    if not design.stats.get('tornado') and not design.stats.get('gsa'):
        for k, e in enumerate(plan):
            if design.varies(e):
                column[e['slot']] = k
    inputs = [{'output': o, 'k': column[o['offset']]} for o in outputs
              if o['source'] == 'P' and o['offset'] in column]
    grid = project.time_grid()
    times = grid.size
    precision = hold_precision(len(wanted), times, iterations, most)
    size = estimate(len(wanted), times, iterations, precision)
    if size['bytes'] > (asked if large else most):
        designed = design.stats.get('tornado') or design.stats.get('gsa')
        what = 'runs' if designed else 'realisations'
        fewer = ('fewer inputs' if design.stats.get('tornado')
                 else 'a smaller design' if design.stats.get('gsa') else 'fewer realisations')
        extra = ' even held as float32' if precision == 'float32' else ''
        raise MemoryError(f'{iterations} {what} of {len(wanted)} series over {times} times is {size["text"]}{extra}; '
                          f'pass large=True to go ahead on a machine with the memory for it, or choose fewer '
                          f'endpoints, or {fewer}.')
    return {'kept': [outputs[k] for k in wanted], 'inputs': inputs, 'grid': grid, 'times': times,
            'precision': precision}


def _realisations(project: Project, system: Any, design: Design, frame: Dict[str, Any], lo: int, hi: int,
                  fatal: int, on_progress: Optional[Callable[[int, int], Any]], compiled: Any) -> Dict[str, Any]:
    """Realisations ``lo`` to ``hi - 1`` on ``system``, their kept series into
    arrays of their own, and the values each set (``value_set``). A failure in
    realisation ``fatal`` fails the run; any other is recorded, its row NaN."""
    plan = design.plan
    kept, grid, times = frame['kept'], frame['grid'], frame['times']
    span = hi - lo
    dtype = np.float32 if frame['precision'] == 'float32' else np.float64
    values = [np.zeros((span, times), dtype=dtype) for _ in kept]
    samples = np.zeros((len(plan), span))
    ran = np.ones(span, dtype=np.uint8)
    failed = 0
    trouble: List[str] = []
    for i in range(lo, hi):
        samples[:, i - lo] = apply_point(system, design, i)
        try:
            r = run(project, system=system, on_grid=True, compiled=compiled)
            rows = None
            if r.t.size != times:
                rows = np.searchsorted(r.t, grid, side='left')
                rows = np.minimum(rows, r.t.size - 1)
            for w, c in enumerate(r.series_many(kept)):
                values[w][i - lo] = c[:times] if rows is None else c[rows]
        except Exception as e:  # noqa: BLE001 - one realisation failing is reported, not fatal
            if i == fatal:
                raise
            failed += 1
            if len(trouble) < 5:
                trouble.append(f'realisation {i + 1}: {e}')
            ran[i - lo] = 0
            for w in range(len(kept)):
                values[w][i - lo] = np.nan
        if on_progress:
            on_progress(i - lo + 1, span)
    return {'values': values, 'samples': samples, 'ran': ran, 'failed': failed, 'trouble': trouble}


def _run_slice(project: Project, system: Any, design: Design, keep: Any, range_: Optional[Sequence[int]],
               on_progress: Optional[Callable[[int, int], Any]], large: bool, started: float,
               compiled: Any = 'auto', most: int = MOST_BYTES,
               asked: int = MOST_BYTES_ASKED) -> 'ProbabilisticResults':
    plan, iterations = design.plan, design.iterations
    frm = max(0, min(iterations - 1, int(round(range_[0])) if range_ else 0))
    to = max(frm + 1, min(iterations, int(round(range_[1])) if range_ else iterations))
    frame = _frame(project, system, design, keep, large, most, asked)
    got = _realisations(project, system, design, frame, frm, to, frm, on_progress, compiled)
    return ProbabilisticResults({
        't': frame['grid'].copy(), 'outputs': frame['kept'], 'values': got['values'], 'plan': plan,
        'samples': got['samples'], 'inputs': frame['inputs'], 'ran': got['ran'], 'iterations': iterations,
        'from': frm, 'to': to, 'precision': frame['precision'], 'names': design.names,
        'gsa_design': design.gsa_design,
        'stats': {'failed': got['failed'], 'trouble': got['trouble'], 'ms': (time.perf_counter() - started) * 1000,
                  **design.stats},
    })


#: A worker process's model and channel back to the caller, given as it starts, and the
#: model built from them (once, for every chunk the process is handed).
_SLICE_WORKER: Dict[str, Any] = {}

#: Chunks per worker process: enough that a process which drew quick realisations takes
#: more of them, and none is left waiting on a slice of slow ones.
_CHUNKS_PER_WORKER = 8


def _start_slice_worker(heard: Any, raw: Dict[str, Any], opts: Dict[str, Any]) -> None:
    """A worker process's start: the queue its progress goes back by, which a
    process can only be given as it starts (as split.py's workers are), and the
    model it runs."""
    _SLICE_WORKER.clear()
    _SLICE_WORKER.update(heard=heard, raw=raw, opts=opts)


def _slice_context() -> tuple:
    """The worker's project, system, design and frame, built on its first chunk."""
    ctx = _SLICE_WORKER.get('context')
    if ctx is None:
        opts = _SLICE_WORKER['opts']
        project = Project(_SLICE_WORKER['raw'])
        system = build_system(project)
        design = design_for(project, system, **_design_options(opts))
        frame = _frame(project, system, design, opts.get('keep'), opts.get('large', False),
                       opts.get('most_bytes', MOST_BYTES), opts.get('asked_bytes', MOST_BYTES_ASKED))
        ctx = _SLICE_WORKER['context'] = (project, system, design, frame)
    return ctx


def _pool_chunk(args: tuple) -> Dict[str, Any]:
    lo, hi, n = args
    project, system, design, frame = _slice_context()
    opts = _SLICE_WORKER['opts']
    heard = _SLICE_WORKER.get('heard')
    last = [0.0]

    def hear(done: int, span: int) -> None:
        # At most ten a second, and the last always: each is a message to the
        # caller's process.
        now = time.perf_counter()
        if now - last[0] > 0.1 or done >= span:
            last[0] = now
            heard.put((n, int(done)))

    # Only the design's first realisation fails the run. A realisation sets its inputs
    # from the design alone (``value_set``), so it runs as it would in one process.
    return _realisations(project, system, design, frame, lo, hi, 0, hear if heard is not None else None,
                         opts.get('compiled', 'auto'))


def _run_pool(raw: Dict[str, Any], opts: Dict[str, Any], workers: int,
              on_progress: Optional[Callable[[int, int], Any]], started: float,
              line: Any = None) -> 'ProbabilisticResults':
    """The realisations shared out between processes in chunks, a process taking
    the next as it finishes one, and stitched back in order. Each process says
    how many of its chunk it has run, so ``on_progress`` hears every realisation
    as it is done, not every chunk."""
    import concurrent.futures as cf
    import queue as queue_module
    # The number of runs is the design's, which for a GSA or tornado is not
    # `iterations`: work it out once here, and what is kept, so that a run too
    # large to hold is refused before any process starts.
    project = Project(raw)
    system = build_system(project, jacobian=False)
    design = design_for(project, system, **_design_options(opts))
    total = design.iterations
    if line is not None:
        line.set_total(total)
    if callable(opts.get('keep')):
        raise ValueError('keep= must be a list of names, not a function, when the run is shared between processes')
    frame = _frame(project, system, design, opts.get('keep'), opts.get('large', False),
                   opts.get('most_bytes', MOST_BYTES), opts.get('asked_bytes', MOST_BYTES_ASKED))
    workers = max(1, min(workers, total))
    size = max(1, math.ceil(total / (workers * _CHUNKS_PER_WORKER)))
    chunks = [(lo, min(total, lo + size)) for lo in range(0, total, size)]
    # The whole run, filled in as each chunk comes back and the chunk let go of, so
    # that the realisations are never held twice -- what a sample as large as half
    # the machine's memory needs (``most_bytes``, ``asked_bytes``).
    dtype = np.float32 if frame['precision'] == 'float32' else np.float64
    values = [np.empty((total, frame['times']), dtype=dtype) for _ in frame['kept']]
    samples = np.empty((len(design.plan), total))
    ran = np.empty(total, dtype=np.uint8)
    failed = 0
    trouble: List[str] = []
    done = 0
    # Spawned processes with one thread per numerical library, as a split's
    # parts are (``_one_thread_each`` in ./split.py): the realisations are the
    # parallelism here, and a BLAS that starts a thread per core in each of
    # several processes spends the machine waiting. Processes start as the
    # chunks are handed in, which is when they take their environment.
    import multiprocessing as mp
    from .split import _one_thread_each, _without_main
    ctx = mp.get_context('spawn')
    heard = ctx.Queue() if on_progress is not None else None
    counts = [0] * len(chunks)
    with cf.ProcessPoolExecutor(max_workers=workers, mp_context=ctx, initializer=_start_slice_worker,
                                initargs=(heard, raw, opts)) as pool:
        with _one_thread_each(), _without_main():
            futures = {pool.submit(_pool_chunk, (lo, hi, n)): n for n, (lo, hi) in enumerate(chunks)}
        pending = set(futures)
        while pending:
            finished, pending = cf.wait(pending, timeout=0.1, return_when=cf.FIRST_COMPLETED)
            while heard is not None:
                try:
                    n, count = heard.get_nowait()
                except queue_module.Empty:
                    break
                counts[n] = max(counts[n], count)
            for fut in finished:
                # Taken out of the map, so that the future and the chunk it holds go.
                n = futures.pop(fut)
                part = fut.result()
                lo, hi = chunks[n]
                for w, v in enumerate(part['values']):
                    values[w][lo:hi] = v
                samples[:, lo:hi] = part['samples']
                ran[lo:hi] = part['ran']
                failed += part['failed']
                trouble.append((n, part['trouble']))
                del part
                counts[n] = hi - lo
            if on_progress is not None and sum(counts) > done:
                done = sum(counts)
                on_progress(done, total)
    if heard is not None:
        heard.close()
    # The first five troubles in the order of the realisations, as one process meets them.
    trouble = [t for _, chunk in sorted(trouble, key=lambda x: x[0]) for t in chunk][:5]
    stats = {'failed': failed, 'trouble': trouble, 'ms': (time.perf_counter() - started) * 1000, **design.stats,
             'workers': workers}
    return ProbabilisticResults({
        't': frame['grid'].copy(), 'outputs': frame['kept'], 'values': values, 'plan': design.plan,
        'samples': samples, 'inputs': frame['inputs'], 'ran': ran, 'iterations': total, 'from': 0, 'to': total,
        'precision': frame['precision'], 'names': design.names, 'gsa_design': design.gsa_design, 'stats': stats,
    })


class ProbabilisticResults:
    """What a probabilistic run kept: every realisation of each kept series,
    the value each input took in each (``value_set``), and the statistics read
    off them."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self.data = data
        self.t = data['t']
        self.outputs = data['outputs']
        self.values = data['values']
        self.samples = data['samples']
        self.plan = data['plan']
        self.names = data['names']
        self.ran = data['ran']
        self.iterations = data['iterations']
        self.stats = data['stats']
        self.inputs = data['inputs']

    @property
    def labels(self) -> List[str]:
        return [o['label'] for o in self.outputs]

    def _index(self, label: Any) -> int:
        if isinstance(label, int):
            return label
        for k, o in enumerate(self.outputs):
            if o['label'] == label:
                return k
        raise KeyError(f"No kept series labelled '{label}'")

    def realisations(self, label: Any) -> np.ndarray:
        """Every realisation of one series: an array of (realisations, times)."""
        return self.values[self._index(label)]

    def __getitem__(self, label: Any) -> np.ndarray:
        return self.realisations(label)

    def sample(self, name: str) -> np.ndarray:
        """The values one input took, by its name (``Kd[Cs-137]``)."""
        return self.samples[self.names.index(name)]

    def quantiles(self, label: Any, qs: Sequence[float] = (0.05, 0.5, 0.95),
                  mask: Optional[np.ndarray] = None) -> Dict[float, np.ndarray]:
        m = self.realisations(label)
        return {q['q']: q['y'] for q in quantiles(m.ravel(), self.t.size, m.shape[0], qs, mask)}

    def mean(self, label: Any, mask: Optional[np.ndarray] = None) -> np.ndarray:
        m = self.realisations(label)
        return mean_of(m.ravel(), self.t.size, m.shape[0], mask)

    def median_spread(self, label: Any, mask: Optional[np.ndarray] = None) -> Dict[str, np.ndarray]:
        m = self.realisations(label)
        return median_spread(m.ravel(), self.t.size, m.shape[0], mask=mask)

    # --- what it says (see kompartment.engine.analysis) -------------------------

    def bands(self, percentiles: Optional[Sequence[float]] = None, mask: Optional[np.ndarray] = None) -> List[Any]:
        from .analysis import bands
        return bands(self, percentiles, mask)

    def summary(self, label: Any, at: Any = None, mask: Optional[np.ndarray] = None) -> Dict[str, Any]:
        from .analysis import summary
        return summary(self, label, at, mask)

    def what_drove(self, label: Any, at: Any = None, **kw: Any) -> Dict[str, Any]:
        """Which inputs the spread of one output came from, at one time."""
        from .analysis import what_drove
        return what_drove(self, label, at, **kw)

    def tornado_table(self, label: Any, stat: str = 'max', at: Any = 0) -> Dict[str, Any]:
        from .analysis import tornado_table
        return tornado_table(self, label, stat, at)

    def gsa_table(self, label: Any, stat: str = 'max', at: Any = 0) -> Dict[str, Any]:
        from .analysis import gsa_answer
        return gsa_answer(self, label, stat, at)

    def to_hdf5(self, path: Any = None, want: Any = 'all', **options: Any) -> bytes:
        """The run as an HDF5 result file, as the application's *Save →
        Realisations* writes it: every realisation (``want='all'``), their mean
        (``'mean'``) or one of them by number, from 1. Its bytes, written to
        ``path`` too when one is given. Pass ``project=`` (the model) for its
        name and index lists; see :func:`kompartment.io.resultfile.probabilistic_tree`
        for the rest."""
        from ..io.resultfile import write_probabilistic_hdf5
        return write_probabilistic_hdf5(self, path, want, **options)

    def __repr__(self) -> str:
        return (f'<ProbabilisticResults: {self.iterations} runs, {len(self.outputs)} series kept, '
                f"{len(self.plan)} inputs, {self.stats.get('failed', 0)} failed>")


def run_tornado(model: Any, *, low: float = 0.05, high: float = 0.95, **opts: Any) -> ProbabilisticResults:
    """Every varied input swung alone to a low and a high probability, the rest
    held at their values: 2 runs per input and one central run."""
    return run_probabilistic(model, tornado={'low': low, 'high': high}, **opts)


def run_gsa(model: Any, method: str, options: Optional[Dict[str, Any]] = None, **opts: Any) -> ProbabilisticResults:
    """A global sensitivity design (``morris``, ``sobol``, ``efast``, ``rbd_fast``,
    ``ff``, ``dgsm``, ``shapley``, ``radial``...; see :mod:`kompartment.stats.gsa`)
    run over the model's distributions. Read the answer with
    :meth:`ProbabilisticResults.gsa_table`."""
    return run_probabilistic(model, gsa={'method': method, 'options': options or {}}, **opts)


def time_major(values: np.ndarray, times: int, iterations: int) -> np.ndarray:
    """Realisation-major values as a result file stores them: time-major, float32."""
    return np.asarray(values, dtype=np.float32).reshape(iterations, times).T.ravel().copy()


def _kept_rows(values: np.ndarray, times: int, iterations: int, mask: Optional[np.ndarray]) -> np.ndarray:
    """The realisations the mask keeps, in their order, as doubles: (kept, times)."""
    rows = np.asarray(values).reshape(iterations, times)
    if mask is not None:
        rows = rows[np.asarray(mask, dtype=bool)]
    return rows.astype(np.float64)


def _sorted_columns(values: np.ndarray, times: int, iterations: int,
                    mask: Optional[np.ndarray]) -> tuple:
    """Every time's finite values over the realisations kept, ascending, a column
    each with what is not finite after them; and how many are finite at each time.
    One sort of the whole series, where a sort per time was the slow part of the
    bands of a large sample."""
    rows = _kept_rows(values, times, iterations, mask)
    finite = np.isfinite(rows)
    rows[~finite] = np.nan
    s = np.sort(rows, axis=0)
    # -0 before 0, as the application's typed-array sort and Julia's leave them:
    # NumPy's sort takes the two for one value and leaves them in any order.
    zero = s == 0
    if zero.any():
        negative = (np.signbit(rows) & (rows == 0)).sum(axis=0)
        first = (s < 0).sum(axis=0)
        s[zero] = 0.0
        s[zero & (np.arange(s.shape[0])[:, None] < first + negative)] = -0.0
    return s, finite.sum(axis=0)


def _order_statistic(s: np.ndarray, n: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """``s[min(n - 1, max(0, idx)), j]`` at each time j, NaN where none is finite."""
    out = np.full(n.size, math.nan)
    has = n > 0
    if has.any():
        at = np.minimum(n - 1, np.maximum(0, idx))
        cols = np.nonzero(has)[0]
        out[cols] = s[at[cols], cols]
    return out


def _sequential_sum(rows: np.ndarray) -> np.ndarray:
    """Each column's sum, added row after row as the application's loops add it:
    ``add.accumulate`` is sequential by definition, where ``sum`` is pairwise down a
    lone column. The ``+ 0.0`` is the loop's start at zero, which turns an all-zero
    column's ``-0`` into ``0``. Accumulated over ``rows`` itself, which the caller
    gives up."""
    if not rows.shape[0]:
        return np.zeros(rows.shape[1])
    return np.add.accumulate(rows, axis=0, out=rows)[-1] + 0.0


def quantiles(values: np.ndarray, times: int, iterations: int, qs: Sequence[float] = (0.05, 0.5, 0.95),
              mask: Optional[np.ndarray] = None) -> List[Dict[str, Any]]:
    """The band at each time: order statistics across the realisations that ran."""
    s, n = _sorted_columns(values, times, iterations, mask)
    return _quantiles_of(s, n, qs)


def _quantiles_of(s: np.ndarray, n: np.ndarray, qs: Sequence[float]) -> List[Dict[str, Any]]:
    # The rank as the loop worked it out: q (n - 1), rounded half up, in doubles.
    return [{'q': q, 'y': _order_statistic(s, n, np.floor(q * (n - 1) + 0.5).astype(np.int64))} for q in qs]


def median_spread(values: np.ndarray, times: int, iterations: int, z: float = 1.959964,
                  mask: Optional[np.ndarray] = None) -> Dict[str, np.ndarray]:
    s, n = _sorted_columns(values, times, iterations, mask)
    return _median_spread_of(s, n, z)


def _median_spread_of(s: np.ndarray, n: np.ndarray, z: float) -> Dict[str, np.ndarray]:
    half = (z * np.sqrt(n.astype(np.float64))) / 2
    ranks = {'errLo': np.ceil((n - 1) / 2 - half), 'errHi': np.floor((n - 1) / 2 + half),
             'bodyLo': np.floor(0.158655 * (n - 1) + 0.5), 'bodyHi': np.floor(0.841345 * (n - 1) + 0.5)}
    return {k: _order_statistic(s, n, r.astype(np.int64)) for k, r in ranks.items()}


def mean_of(values: np.ndarray, times: int, iterations: int, mask: Optional[np.ndarray] = None) -> np.ndarray:
    rows = _kept_rows(values, times, iterations, mask)
    finite = np.isfinite(rows)
    n = finite.sum(axis=0)
    rows[~finite] = 0.0
    total = _sequential_sum(rows)
    with np.errstate(all='ignore'):
        return np.where(n > 0, total / np.maximum(n, 1), math.nan)
