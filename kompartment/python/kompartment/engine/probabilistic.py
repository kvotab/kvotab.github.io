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
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np

from ..stats.correlate import correlation_pairs, iman_conover
from ..stats.gsa import build_design, cholesky
from ..stats.sample import distributed_slots, stream_for, uniforms, value_at_probability
from .. import jsmath
from .builder import build_system, tuple_by_list
from .project import Project, value_at
from .runner import run

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


def hold_precision(series: int, times: int, iterations: int) -> str:
    return 'float32' if estimate(series, times, iterations)['bytes'] > MOST_BYTES else 'double'


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

    def value_for_sample(k: int, i: int) -> float:
        return value_at_probability(plan[k]['spec'], float(draws[k][i]), i) if varies(plan[k]) else best[k]

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

    def value_for(k: int, i: int) -> float:
        if factor_of[k] < 0:
            return best[k]
        return value_at_probability(drawn[k], float(design['u'][factor_of[k]][i]), i)

    return Design(plan, names, best, varies, int(design['runs']), value_for, seed,
                  {'seed': seed, 'latin': False, 'sampled': len(plan),
                   'gsa': {'method': gsa['method'], 'options': design.get('options'),
                           'factors': [{'key': f['key'], 'group': f['group'], 'members': f['members']}
                                       for f in factors],
                           'correlated': len(between), 'correlationsUsed': corr is not None,
                           'correlationShrunk': shrunk, 'correlationProblems': problems}},
                  gsa_design=design)


def apply_point(system: Any, design: Design, i: int) -> List[float]:
    """Sets design point ``i`` into the system, ready to run; the values set."""
    P = system.P
    out = []
    for k, e in enumerate(design.plan):
        v = design.value_for(k, i)
        out.append(v)
        if v is not None and math.isfinite(v):
            P[e['slot']] = v
        elif not design.varies(e):
            P[e['slot']] = design.best[k]
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
    results = run(project, system=system)
    return {'results': results, 'index': i, 'iterations': design.iterations,
            'values': [{'name': design.names[k], 'value': values[k],
                        'held': (not design.varies(e)) or (values[k] == design.best[k]
                                                             if design.stats.get('tornado') else False)}
                       for k, e in enumerate(design.plan)]}


def _design_options(opts: Dict[str, Any]) -> Dict[str, Any]:
    return {k: opts[k] for k in ('seed', 'iterations', 'latin', 'varied', 'tornado', 'gsa') if k in opts}


def run_probabilistic(model: Any, *, iterations: int = 100, seed: int = 1, latin: bool = True,
                      varied: Optional[Iterable[str]] = None, tornado: Optional[Dict[str, float]] = None,
                      gsa: Optional[Dict[str, Any]] = None, keep: Any = None, workers: int = 1,
                      on_progress: Optional[Callable[[int, int], Any]] = None, large: bool = False,
                      range_: Optional[Sequence[int]] = None) -> 'ProbabilisticResults':
    """Runs ``iterations`` realisations and keeps the series asked for.

    ``keep``: which series to hold -- None for every endpoint (anything but an
    input), a list of block names or labels, or a function ``(name, output)``.
    ``workers`` > 1 shares the realisations out between processes; the design
    is drawn whole in each, so the answer does not depend on how many.
    ``tornado={'low': .05, 'high': .95}`` swings each input alone;
    ``gsa={'method': ..., 'options': {...}}`` runs a sensitivity design.
    """
    started = time.perf_counter()
    project = _as_project(model)
    raw = project.to_json() if workers > 1 else None
    if workers > 1:
        return _run_pool(raw, dict(iterations=iterations, seed=seed, latin=latin, varied=varied, tornado=tornado,
                                   gsa=gsa, keep=keep, large=large), workers, on_progress, started)
    system = build_system(project)
    design = design_for(project, system, seed=seed, iterations=iterations, latin=latin, varied=varied,
                        tornado=tornado, gsa=gsa)
    return _run_slice(project, system, design, keep, range_, on_progress, large, started)


def _keep_fn(keep: Any) -> Optional[Callable[[str, Dict[str, Any]], bool]]:
    if keep is None:
        return None
    if callable(keep):
        return keep
    wanted = {str(k) for k in keep}
    return lambda name, o: name in wanted or o.get('label') in wanted


def _run_slice(project: Project, system: Any, design: Design, keep: Any, range_: Optional[Sequence[int]],
               on_progress: Optional[Callable[[int, int], Any]], large: bool, started: float) -> 'ProbabilisticResults':
    plan, iterations = design.plan, design.iterations
    frm = max(0, min(iterations - 1, int(round(range_[0])) if range_ else 0))
    to = max(frm + 1, min(iterations, int(round(range_[1])) if range_ else iterations))
    span = to - frm
    samples = np.zeros((len(plan), span))

    def apply(i: int) -> None:
        values = apply_point(system, design, i)
        for k in range(len(plan)):
            samples[k, i - frm] = values[k] if values[k] is not None else math.nan

    apply(frm)
    first = run(project, system=system, on_grid=True)
    outputs = first.outputs()
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
    precision = hold_precision(len(wanted), times, iterations)
    size = estimate(len(wanted), times, iterations, precision)
    if size['bytes'] > (MOST_BYTES_ASKED if large else MOST_BYTES):
        designed = design.stats.get('tornado') or design.stats.get('gsa')
        what = 'runs' if designed else 'realisations'
        fewer = ('fewer inputs' if design.stats.get('tornado')
                 else 'a smaller design' if design.stats.get('gsa') else 'fewer realisations')
        extra = ' even held as float32' if precision == 'float32' else ''
        raise MemoryError(f'{iterations} {what} of {len(wanted)} series over {times} times is {size["text"]}{extra}; '
                          f'pass large=True to go ahead on a machine with the memory for it, or choose fewer '
                          f'endpoints, or {fewer}.')
    dtype = np.float32 if precision == 'float32' else np.float64
    values = [np.zeros((span, times), dtype=dtype) for _ in wanted]
    kept = [outputs[k] for k in wanted]

    def take(i: int, results: Any) -> None:
        rows = None
        if results.t.size != times:
            rows = np.searchsorted(results.t, grid, side='left')
            rows = np.minimum(rows, results.t.size - 1)
        cols = results.series_many(kept)
        for w, c in enumerate(cols):
            values[w][i - frm] = c[:times] if rows is None else c[rows]

    take(frm, first)
    if on_progress:
        on_progress(1, span)
    failed = 0
    trouble: List[str] = []
    ran = np.ones(span, dtype=np.uint8)
    for i in range(frm + 1, to):
        apply(i)
        try:
            r = run(project, system=system, on_grid=True)
            take(i, r)
        except Exception as e:  # noqa: BLE001 - one realisation failing is reported, not fatal
            failed += 1
            if len(trouble) < 5:
                trouble.append(f'realisation {i + 1}: {e}')
            ran[i - frm] = 0
            for w in range(len(wanted)):
                values[w][i - frm] = np.nan
        if on_progress:
            on_progress(i - frm + 1, span)
    return ProbabilisticResults({
        't': grid.copy(), 'outputs': kept, 'values': values, 'plan': plan, 'samples': samples, 'inputs': inputs,
        'ran': ran, 'iterations': iterations, 'from': frm, 'to': to, 'precision': precision,
        'names': design.names, 'gsa_design': design.gsa_design,
        'stats': {'failed': failed, 'trouble': trouble, 'ms': (time.perf_counter() - started) * 1000,
                  **design.stats},
    })


def _pool_slice(args: tuple) -> Dict[str, Any]:
    raw, opts, lo, hi = args
    project = Project(raw)
    system = build_system(project)
    design = design_for(project, system, **_design_options(opts))
    res = _run_slice(project, system, design, opts.get('keep'), (lo, hi), None, opts.get('large', False),
                     time.perf_counter())
    return res.data


def _run_pool(raw: Dict[str, Any], opts: Dict[str, Any], workers: int,
              on_progress: Optional[Callable[[int, int], Any]], started: float) -> 'ProbabilisticResults':
    """The realisations shared out between processes, stitched back in order."""
    import concurrent.futures as cf
    # The number of runs is the design's, which for a GSA or tornado is not
    # `iterations`: work it out once here.
    project = Project(raw)
    system = build_system(project, jacobian=False)
    total = design_for(project, system, **_design_options(opts)).iterations
    workers = max(1, min(workers, total))
    edges = np.linspace(0, total, workers + 1).round().astype(int)
    slices = [(int(edges[k]), int(edges[k + 1])) for k in range(workers) if edges[k + 1] > edges[k]]
    if callable(opts.get('keep')):
        raise ValueError('keep= must be a list of names, not a function, when the run is shared between processes')
    parts: List[Dict[str, Any]] = [None] * len(slices)  # type: ignore[list-item]
    done = 0
    with cf.ProcessPoolExecutor(max_workers=len(slices)) as pool:
        futures = {pool.submit(_pool_slice, (raw, opts, lo, hi)): n for n, (lo, hi) in enumerate(slices)}
        for fut in cf.as_completed(futures):
            n = futures[fut]
            parts[n] = fut.result()
            done += parts[n]['to'] - parts[n]['from']
            if on_progress:
                on_progress(done, total)
    first = parts[0]
    values = [np.concatenate([p['values'][w] for p in parts], axis=0) for w in range(len(first['values']))]
    samples = np.concatenate([p['samples'] for p in parts], axis=1)
    ran = np.concatenate([p['ran'] for p in parts])
    failed = sum(p['stats']['failed'] for p in parts)
    trouble = [t for p in parts for t in p['stats']['trouble']][:5]
    stats = {**first['stats'], 'failed': failed, 'trouble': trouble, 'ms': (time.perf_counter() - started) * 1000,
             'workers': len(slices)}
    precision = 'float32' if any(p['precision'] == 'float32' for p in parts) else 'double'
    return ProbabilisticResults({**first, 'values': values, 'samples': samples, 'ran': ran, 'from': 0, 'to': total,
                                 'precision': precision, 'stats': stats})


class ProbabilisticResults:
    """What a probabilistic run kept: every realisation of each kept series,
    the values drawn, and the statistics read off them."""

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


def _finite_sorted_column(values: np.ndarray, times: int, iterations: int, j: int,
                          mask: Optional[np.ndarray]) -> np.ndarray:
    col = values.reshape(iterations, times)[:, j]
    if mask is not None:
        col = col[np.asarray(mask, dtype=bool)]
    col = col[np.isfinite(col)]
    return np.sort(col.astype(np.float64))


def quantiles(values: np.ndarray, times: int, iterations: int, qs: Sequence[float] = (0.05, 0.5, 0.95),
              mask: Optional[np.ndarray] = None) -> List[Dict[str, Any]]:
    """The band at each time: order statistics across the realisations that ran."""
    values = np.asarray(values)
    out = [{'q': q, 'y': np.zeros(times)} for q in qs]
    for j in range(times):
        s = _finite_sorted_column(values, times, iterations, j, mask)
        n = s.size
        for k, q in enumerate(qs):
            if not n:
                out[k]['y'][j] = math.nan
                continue
            r = q * (n - 1)
            idx = int(math.floor(r + 0.5))
            out[k]['y'][j] = s[min(n - 1, max(0, idx))]
    return out


def median_spread(values: np.ndarray, times: int, iterations: int, z: float = 1.959964,
                  mask: Optional[np.ndarray] = None) -> Dict[str, np.ndarray]:
    values = np.asarray(values)
    err_lo, err_hi = np.zeros(times), np.zeros(times)
    body_lo, body_hi = np.zeros(times), np.zeros(times)
    for j in range(times):
        s = _finite_sorted_column(values, times, iterations, j, mask)
        n = s.size
        if not n:
            err_lo[j] = err_hi[j] = body_lo[j] = body_hi[j] = math.nan
            continue

        def at(k: int) -> float:
            return float(s[min(n - 1, max(0, k))])

        half = (z * math.sqrt(n)) / 2
        err_lo[j] = at(math.ceil((n - 1) / 2 - half))
        err_hi[j] = at(math.floor((n - 1) / 2 + half))
        body_lo[j] = at(int(math.floor(0.158655 * (n - 1) + 0.5)))
        body_hi[j] = at(int(math.floor(0.841345 * (n - 1) + 0.5)))
    return {'errLo': err_lo, 'errHi': err_hi, 'bodyLo': body_lo, 'bodyHi': body_hi}


def mean_of(values: np.ndarray, times: int, iterations: int, mask: Optional[np.ndarray] = None) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64).reshape(iterations, times)
    out = np.zeros(times)
    use = np.ones(iterations, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    for j in range(times):
        total = 0.0
        n = 0
        for i in range(iterations):
            if not use[i]:
                continue
            v = values[i, j]
            if math.isfinite(v):
                total += v
                n += 1
        out[j] = total / n if n else math.nan
    return out
