"""Solving a model in its independent parts, at the same time.

A port of the application's ``src/sim/split.js`` and of the coordinator in its
simulation worker. :mod:`kompartment.engine.partition` finds the parts of a
model that cannot reach each other -- on an assessment, one per decay chain --
and this decides whether solving them side by side pays for the model in
hand, and does it: the whole model is built (its Jacobian says where the parts
are, and its system is what every series is worked out from afterwards), each
*job* -- the model with every material switched off but the job's own -- is
built and run in a worker process on the model's output grid at its own
steps, and every state is filed back into the whole model's vector by name.
What comes out is an ordinary :class:`~kompartment.engine.runner.Results` of
the whole model whose states were integrated in pieces.

**Not bit for bit the whole model's.** Each part takes the steps its own
states need rather than the steps the stiffest state anywhere needs, which is
the point, and so agrees with the whole to within the tolerance. The worker
count changes nothing: each job is the same run in whichever process takes
it.

**Refused, whatever the setting, where it would be wrong or cannot work:** a
model the partition declines (a delay, a snapshot or an event reaches across
parts without showing in the Jacobian); output at the solver's own steps,
which differ in every part; a model with no materials to divide by; one part
holding everything; one core; and a run that is itself in a worker process.
Unlike the application, a SciPy solver is allowed: here it is native, where
each of the application's workers would download a Python runtime. And one
refusal the application does not make, because it gets it wrong: a min/max
whose target reads states of more than one job (a peak of a total over
nuclides) cannot be given back by any part, so such a model is solved whole.
The application splits it and reports the target's current value as its
peak.

**Carried back:** besides the states, each part's run leaves its recorders'
histories (``System.run_state``); a min/max or running mean is taken from the
job that owns the states its target reads, and put on the whole system, so
their series are the run's.

The processes are started with ``spawn``, so this is safe on every platform,
and they load only this package, never the caller's script: a script needs no
``if __name__ == '__main__':`` guard for a run to be split, as it would for a
process pool of its own.
"""

from __future__ import annotations

import contextlib
import copy
import json
import math
import multiprocessing as mp
import os
import re
import sys
import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from .partition import partition_of

__all__ = ['SPLIT_MODES', 'SHARED_WORK', 'AUTO_STATES', 'AUTO_SOLVE_MS', 'AUTO_GAIN', 'AUTO_GAIN_UNTIMED',
           'START_MS', 'state_keys', 'state_materials', 'split_jobs', 'job_cost', 'pack_jobs', 'plan_split',
           'part_model', 'place_states', 'assemble_parts', 'build_part', 'run_split', 'run_whole_or_split']

#: The setting, as the application's Simulation section offers it.
SPLIT_MODES = [
    ('auto', 'auto', 'Split the model into its independent parts when that is expected to be clearly faster on '
                     'this machine: a large model that falls apart into several decay chains of comparable size, '
                     'with the cores to run them side by side.'),
    ('on', 'always', 'Split whenever the model can be split: every part that cannot reach another is solved in a '
                     'worker of its own, at its own steps.'),
    ('off', 'never', 'Solve the whole model as one system, as it always was.'),
]

# --- the cost model: the application's structure, this engine's numbers ----------------------
#
# The formulas are the application's; the numbers were measured on this engine
# (made-up models of independent decay chains, 2,400 to 28,800 states, on a
# 10-core machine), not copied: the application's workers are threads of a
# browser that start in a quarter of a second, where each of these is a new
# Python process that has to import the engine and load its compiled kernels.

#: The share of a derivative call every part pays whatever its size. Here it
#: is the solver's own work per step, which does not shrink with the part: a
#: part of an eighth of a 9,600-state model took 22% of the whole model's
#: solve, which is ``0.1 + 0.9 x 0.125`` (with its fewer steps counted in).
#: The share falls as the model grows -- 0.3 at 2,400 states, near nothing at
#: 19,200 -- so this is its value where auto has a choice to make, and the
#: prediction is pessimistic for anything larger.
SHARED_WORK = 0.1

#: Auto splits a model it has not timed only from this many states up: below
#: about 7,000 states a split of these models was measured slower than the
#: whole, the processes' start eating what the parts save.
AUTO_STATES = 10000

#: Auto splits a model it has timed only when a whole solve took this long: a
#: split was measured at break-even about a second, and at 1.3x or more from
#: a second and a half.
AUTO_SOLVE_MS = 1500.0

#: How much faster auto wants the split to be expected, or measured, to be.
AUTO_GAIN = 1.2

#: The same, for a model whose solve time is not known yet: a larger margin
#: than the application's 1.6, since the start below is a larger share of a
#: run here and the shape alone does not see it.
AUTO_GAIN_UNTIMED = 2.0

#: Starting a worker process and loading the engine into it, in wall time,
#: once per run (the processes start side by side): spawning and importing,
#: 0.2 to 0.3 s for one to ten processes; the first build in a process, which
#: loads the compiled kernels, 0.2 to 0.3 s more than any later one; and the
#: states coming back and the processes closing.
START_MS = 650.0


def _to_fixed(x: float, digits: int) -> str:
    """``x.toFixed(digits)``: a tie goes to the larger, as JavaScript rounds."""
    q = Decimal(1).scaleb(-digits)
    return str(Decimal(float(x)).quantize(q, rounding=ROUND_HALF_UP))


def _js_round(x: float) -> int:
    """``Math.round``: halves up."""
    return int(math.floor(x + 0.5))


# --- names and materials of the states ------------------------------------------------------

def state_keys(layout: Any) -> Optional[List[str]]:
    """A name for each state that is the same for the same state in any build
    of the model, whichever materials that build has (``stateKeys``): the
    block, its index, and for a far-field path the cell; a mass-balance budget
    by its term and family. None when two states come out with one name."""
    n = int(layout.nstate)
    keys: List[Optional[str]] = [None] * n
    space = layout.index_space
    for entry in layout.states:
        kind = entry.kind
        farf = entry.get('farf')
        if kind == 'farfield' and farf is not None:
            names = space.index_names(farf.list_name) if farf.list_name else [None]
            for o in range(farf.other_width):
                others = space.tuple_at(farf.other_dims, o) if farf.other_dims else []
                base = entry.base + o * farf.ncells * farf.nnuc
                for m in range(farf.nnuc):
                    index = []
                    k = 0
                    for dim in entry.dims:
                        if dim == farf.list_name:
                            index.append(names[m])
                        else:
                            index.append(others[k])
                            k += 1
                    joined = ','.join('' if v is None else str(v) for v in index)
                    for cell in range(farf.ncells):
                        keys[base + cell * farf.nnuc + m] = f'{kind}:{entry.name}[{joined}]#{cell}'
            continue
        budget = entry.get('budget')
        if kind == 'budget' and budget is not None:
            nfam, families, terms = budget['nfam'], budget['families'], budget['terms']
            for t, term in enumerate(terms):
                for f in range(nfam):
                    keys[entry.base + t * nfam + f] = f'budget:{term}:{families[f]}'
            continue
        dims = list(entry.dims or [])
        for off in range(entry.width):
            index = space.tuple_at(dims, off) if dims else []
            keys[entry.base + off] = f"{kind}:{entry.name}[{','.join(index)}]"
    seen = set()
    for k in keys:
        if k is None or k in seen:
            return None
        seen.add(k)
    return keys  # type: ignore[return-value]


def _material_dim(space: Any, root: Optional[str], dims: Sequence[str]) -> int:
    """The dimension of a block that is its material, as the runner reads it:
    a list whose root is the material catalogue and that is not a mapping."""
    if not root:
        return -1
    for i, d in enumerate(dims):
        if not space.has(d):
            continue
        lst = space.get(d)
        if not lst.mapping and lst.root_name == root:
            return i
    return -1


def state_materials(layout: Any) -> List[Optional[str]]:
    """The material each state belongs to, or None for one that is not per
    material (``stateMaterials``)."""
    from .massbalance import UNINDEXED
    out: List[Optional[str]] = [None] * int(layout.nstate)
    space = layout.index_space
    material_list = space.get(layout.material_list) if layout.material_list else None
    root = material_list.root_name if material_list is not None else None
    for entry in layout.states:
        farf = entry.get('farf')
        if entry.kind == 'farfield' and farf is not None:
            if not farf.list_name:
                continue
            names = space.index_names(farf.list_name)
            for o in range(farf.other_width):
                base = entry.base + o * farf.ncells * farf.nnuc
                for m in range(farf.nnuc):
                    for cell in range(farf.ncells):
                        out[base + cell * farf.nnuc + m] = names[m]
            continue
        budget = entry.get('budget')
        if entry.kind == 'budget' and budget is not None:
            nfam, families, terms = budget['nfam'], budget['families'], budget['terms']
            for t in range(len(terms)):
                for f in range(nfam):
                    out[entry.base + t * nfam + f] = None if families[f] == UNINDEXED else families[f]
            continue
        dims = list(entry.dims or [])
        md = _material_dim(space, root, dims)
        if md < 0:
            continue
        for off in range(entry.width):
            out[entry.base + off] = space.tuple_at(dims, off)[md]
    return out


# --- the jobs -------------------------------------------------------------------------------

def _recorder_owners(system: Any, owner: np.ndarray, smallest: int) -> Any:
    """For every entry of a recorder that remembers (a min/max, a running mean):
    ``(key, job, slot)`` -- its name, the job whose states its target reads,
    and its place in the whole system's histories -- or a refusal, when those
    states are in more than one job and no part can give it back."""
    from .jacobian import state_dependencies
    out = []
    remembering = [r for r in system.recorders if r.kind in ('min_max', 'running_mean') and r.mem >= 0]
    if not remembering:
        return out
    deps = state_dependencies(system)
    space = system.layout.index_space
    for rec in remembering:
        target = rec.aux['target']
        for off in range(rec.width):
            reads = deps.get(target.base + off)
            jobs = sorted({int(owner[s]) for s in (reads.tolist() if reads is not None else [])})
            if len(jobs) > 1:
                return (f"'{rec.name}' remembers a value read from more than one part, so no part can give it "
                        'back')
            index = space.tuple_at(rec.dims, off) if rec.dims else []
            out.append((f"{rec.kind}:{rec.name}[{','.join(index)}]", jobs[0] if jobs else smallest, rec.mem + off))
    return out


def split_jobs(system: Any) -> Dict[str, Any]:
    """The jobs a model's parts make: sets of materials, each with the states it
    owns (``splitJobs``).

    A job is built by switching every other material off, so parts that share
    a material are merged. A part with no material at all is in every job's
    build and is taken from whichever job is smallest.
    """
    part = partition_of(system)
    if not part['ok']:
        return {'ok': False, 'why': part['refusal']}
    layout = system.layout
    if not layout.material_list:
        return {'ok': False, 'why': 'the model has no materials to divide it by'}
    if part['count'] < 2:
        return {'ok': False, 'why': 'the model is one part: every state can reach every other'}
    keys = state_keys(layout)
    if keys is None:
        return {'ok': False, 'why': 'two states of the model share a name, so a part could not be filed back by it'}
    materials = state_materials(layout)
    n = int(layout.nstate)
    of = part['of']
    count = part['count']

    # Parts that share a material are one job.
    parent = list(range(count))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    first_part: Dict[str, int] = {}
    for i in range(n):
        m = materials[i]
        if m is None:
            continue
        p = int(of[i])
        was = first_part.get(m)
        if was is None:
            first_part[m] = p
        elif find(was) != find(p):
            parent[find(p)] = find(was)
    # The groups with a material, numbered in the order they first appear.
    job_of = [-1] * count
    jobs: List[Dict[str, Any]] = []
    carries = [False] * count
    for i in range(n):
        if materials[i] is not None:
            carries[int(of[i])] = True
    for p in range(count):
        if not carries[p]:
            continue
        r = find(p)
        if job_of[r] < 0:
            job_of[r] = len(jobs)
            jobs.append({'materials': [], 'seen': set(), 'states': 0})
        job_of[p] = job_of[r]
    if len(jobs) < 2:
        return {'ok': False, 'why': 'every part shares a material with another, so the model builds as one job'}
    owner = np.zeros(n, dtype=np.int64)
    for i in range(n):
        j = job_of[find(int(of[i]))]
        owner[i] = j
        if j >= 0:
            jobs[j]['states'] += 1
            m = materials[i]
            if m is not None and m not in jobs[j]['seen']:
                jobs[j]['seen'].add(m)
                jobs[j]['materials'].append(m)
    # The parts with no material go to the smallest job, which every build
    # holds them anyway.
    smallest = 0
    for k, jb in enumerate(jobs):
        if jb['states'] < jobs[smallest]['states']:
            smallest = k
    for i in range(n):
        if owner[i] < 0:
            owner[i] = smallest
            jobs[smallest]['states'] += 1
    # A material the model has but no state carries rides with the smallest
    # job, so that every material is switched on somewhere.
    placed = {m for jb in jobs for m in jb['materials']}
    for m in layout.index_space.index_names(layout.material_list):
        if m not in placed:
            jobs[smallest]['materials'].append(m)
            jobs[smallest]['seen'].add(m)
    recorders = _recorder_owners(system, owner, smallest)
    if isinstance(recorders, str):
        return {'ok': False, 'why': recorders}
    return {'ok': True, 'jobs': [{'materials': list(jb['materials']), 'states': jb['states']} for jb in jobs],
            'owner': owner, 'keys': keys, 'parts': count, 'recorders': recorders}


def job_cost(states: int, total: int) -> float:
    """A job's share of a whole derivative call, from its share of the states."""
    return SHARED_WORK + (1 - SHARED_WORK) * (states / total if total > 0 else 1)


def pack_jobs(costs: Sequence[float], workers: int) -> List[List[int]]:
    """Jobs into ``workers`` bins, largest first into the least loaded: the
    longest-processing-time rule (``packJobs``)."""
    n = max(1, min(int(workers), len(costs)))
    load = [0.0] * n
    bins: List[List[int]] = [[] for _ in range(n)]
    order = sorted(range(len(costs)), key=lambda i: (-costs[i], i))
    for j in order:
        k = 0
        for b in range(1, n):
            if load[b] < load[k]:
                k = b
        load[k] += costs[j]
        bins[k].append(j)
    return [sorted(b) for b in bins]


def plan_split(system: Any, project: Any, *, mode: Any = 'auto', workers: int = 1, nest: bool = True,
               build_ms: float = 0.0, known: Optional[Dict[str, Any]] = None, on_grid: bool = False) -> Dict[str, Any]:
    """Whether to split this run, and how (``planSplit``).

    The prediction is the application's cost model: each job costs its share
    of the whole model's build and of its solve, the bins run side by side,
    and each worker costs a start -- with this engine's numbers. ``known`` is
    the whole model's solve time from an earlier run of this layout here
    (``{'solve_ms', 'gain'}``); without it the ratio is judged on the model's
    shape alone, with a larger margin and only for a large model.

    Returns ``{'use', 'mode', 'why', ...}``; when ``use``, also ``jobs``,
    ``owner``, ``keys``, ``bins``, ``parts``, ``predicted`` and ``recorders``.
    """
    m = mode if mode in ('on', 'off') else 'auto'

    def no(why: str, **extra: Any) -> Dict[str, Any]:
        return {'use': False, 'mode': m, 'why': why, **extra}

    if m == 'off':
        return no('switched off')
    if not getattr(system.layout, 'nstate', 0):
        return no('the model has nothing to integrate')
    if not on_grid and getattr(project, 'output_mode', 'grid') != 'grid':
        return no('the results are reported at the solver’s own steps, which would be different in every part')
    if not nest:
        return no('this run is itself in a worker process, which does not start more')
    found = split_jobs(system)
    if not found['ok']:
        return no(found['why'])
    n = int(system.layout.nstate)
    costs = [job_cost(j['states'], n) for j in found['jobs']]
    cores = max(1, int(math.floor(workers)))
    if cores < 2:
        return no('there is one core to run on')
    bins = pack_jobs(costs, cores)
    load = max(sum(costs[j] for j in b) for b in bins)
    plan = {'use': True, 'mode': m, 'jobs': found['jobs'], 'owner': found['owner'], 'keys': found['keys'],
            'bins': bins, 'parts': found['parts'], 'predicted': None, 'why': '', 'recorders': found['recorders']}
    largest = max(j['states'] for j in found['jobs'])
    size = f"{len(found['jobs'])} parts, the largest {_js_round(100 * largest / n)}% of the states"
    if m == 'on':
        plan['why'] = f'asked for: {size}, on {len(bins)} cores'
        return plan
    # Auto. A split this model has had, measured, decides.
    if known is not None and known.get('gain') is not None:
        gain = float(known['gain'])
        if gain < AUTO_GAIN:
            return no(f'split, it was measured at {_to_fixed(gain, 1)}×, which is not enough to be worth it')
        plan['predicted'] = gain
        plan['why'] = f'{size}; measured at {_to_fixed(gain, 1)}× the last time, on {len(bins)} cores'
        return plan
    if known is not None and known.get('solve_ms') is not None and math.isfinite(known['solve_ms']):
        S = float(known['solve_ms'])
        B = max(0.0, float(build_ms))
        predicted = S / (load * (B + S) + START_MS)
        if S < AUTO_SOLVE_MS:
            return no(f'a whole solve takes {_js_round(S)} ms, too short to be worth dividing', predicted=predicted)
        if predicted < AUTO_GAIN:
            return no(f'{size}; expected {_to_fixed(predicted, 1)}× on {len(bins)} cores, not enough',
                      predicted=predicted)
        plan['predicted'] = predicted
        plan['why'] = f'{size}; expected {_to_fixed(predicted, 1)}× faster on {len(bins)} cores'
        return plan
    shape = 1 / load
    if n < AUTO_STATES:
        return no(f'{n:,} states, too few to be worth dividing before a run has been timed', predicted=shape)
    if shape < AUTO_GAIN_UNTIMED:
        return no(f'{size}; at most {_to_fixed(shape, 1)}× on {len(bins)} cores, not enough', predicted=shape)
    plan['predicted'] = shape
    plan['why'] = f'{size}; up to {_to_fixed(shape, 1)}× faster on {len(bins)} cores'
    return plan


# --- one job's model -------------------------------------------------------------------------

def part_model(model: Dict[str, Any], keep: Sequence[str], copy_it: bool = True) -> Dict[str, Any]:
    """The model as one job builds it: every material switched off but its own
    (``partModel``)."""
    out = copy.deepcopy(model) if copy_it else model
    want = set(keep)
    for lst in out.get('index_lists') or []:
        if not (lst.get('for_contaminants') or lst.get('for_nuclides')):
            continue
        indices = []
        for i in lst.get('indices') or []:
            idx = {'name': i, 'enabled': True} if isinstance(i, str) else dict(i)
            if idx.get('name') not in want:
                idx['enabled'] = False
            indices.append(idx)
        lst['indices'] = indices
    if isinstance(out.get('nuclides'), list):
        out['nuclides'] = [n for n in out['nuclides'] if n in want]
    return out


def _is_material_index(model: Dict[str, Any], name: str) -> bool:
    for lst in model.get('index_lists') or []:
        if not (lst.get('for_contaminants') or lst.get('for_nuclides')):
            continue
        for i in lst.get('indices') or []:
            if (i if isinstance(i, str) else (i or {}).get('name')) == name:
                return True
    return False


def _switch_on(model: Dict[str, Any], name: str) -> Dict[str, Any]:
    out = copy.deepcopy(model)
    for lst in out.get('index_lists') or []:
        if not (lst.get('for_contaminants') or lst.get('for_nuclides')):
            continue
        for i in lst.get('indices') or []:
            if isinstance(i, dict) and i.get('name') == name:
                i['enabled'] = True
    if isinstance(out.get('nuclides'), list) and name not in out['nuclides']:
        catalogue = next((lst for lst in out.get('index_lists') or [] if lst.get('for_contaminants')), None)
        order = [(i if isinstance(i, str) else i.get('name')) for i in (catalogue or {}).get('indices') or []]
        on = set(out['nuclides']) | {name}
        out['nuclides'] = [n for n in order if n in on]
    return out


_PINNED = re.compile(r"'([^']+)' is disabled in '([^']+)'")


def build_part(model: Dict[str, Any]) -> Any:
    """A job's model, built, switching back on any material its equations name
    outright -- ``k[C-14]`` -- and trying again (``buildPart``). ``(project,
    system, pinned)``."""
    from .builder import build_system
    from .project import Project
    pinned: List[str] = []
    current = model
    while True:
        try:
            project = Project(current)
            return project, build_system(project), pinned
        except Exception as e:  # noqa: BLE001 - only a pin to a switched-off material is retried
            found = _PINNED.search(str(e))
            if not found or found.group(1) in pinned or not _is_material_index(current, found.group(1)):
                raise
            pinned.append(found.group(1))
            current = _switch_on(current, found.group(1))


def place_states(whole: Dict[str, int], keys: Sequence[str], owner: np.ndarray, job: int) -> Any:
    """Where a job's states go in the whole model's vector (``placeStates``):
    ``(from, to)``, for the states the job owns."""
    frm, to = [], []
    for k, key in enumerate(keys):
        i = whole.get(key)
        if i is None or owner[i] != job:
            continue
        frm.append(k)
        to.append(i)
    return np.array(frm, dtype=np.int64), np.array(to, dtype=np.int64)


_SUMMED = ('nsteps', 'nfailed', 'nfevals', 'npds', 'ndecomps', 'restarts', 'breaks', 'events', 'jumps', 'nbelowtol',
           'negative')


def assemble_parts(plan: Dict[str, Any], outcomes: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The parts, back into one run of the whole model (``assembleParts``).

    ``outcomes[j]`` is job ``j``'s run: ``t``, ``y`` (a row per time),
    ``keys``, ``stats`` and ``held``. Every state is filed from the job that
    owns it, by name; every part must have come back on the same times, and
    every state must have come from one -- else this raises and the caller
    solves the whole model. The counts are summed; a held-at-zero tally is
    kept as a share of its own part's steps.
    """
    keys = plan['keys']
    owner = plan['owner']
    n = len(keys)
    whole = {k: i for i, k in enumerate(keys)}
    t = np.asarray(outcomes[0]['t'], dtype=float)
    for o in outcomes:
        ot = np.asarray(o['t'], dtype=float)
        if ot.size != t.size or np.any(ot != t):
            raise RuntimeError('the parts came back on different output times')
    Y = np.zeros((t.size, n))
    filled = np.zeros(n, dtype=bool)
    share = np.zeros(n)
    held_any = False
    stats: Dict[str, Any] = {'nsteps': 0, 'nfailed': 0, 'nfevals': 0}
    for j, o in enumerate(outcomes):
        frm, to = place_states(whole, o['keys'], owner, j)
        oy = np.asarray(o['y'], dtype=float).reshape(t.size, -1)
        Y[:, to] = oy[:, frm]
        filled[to] = True
        s = o.get('stats') or {}
        for key in _SUMMED:
            v = s.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                stats[key] = stats.get(key, 0) + v
        if not stats.get('solver') and s.get('solver'):
            stats['solver'] = s['solver']
        if s.get('sparse') is not None:
            stats['sparse'] = s['sparse']
        # This engine's own: the run was compiled when every part was, and
        # the first part that was not says why.
        if 'compiled' in s:
            stats['compiled'] = bool(stats.get('compiled', True) and s['compiled'])
            if s.get('compiled_why') and 'compiled_why' not in stats:
                stats['compiled_why'] = s['compiled_why']
        held = o.get('held')
        if held is not None:
            steps = max(1, s.get('nsteps') or 1)
            h = np.asarray(held, dtype=float)
            v = h[frm]
            hit = v != 0
            if np.any(hit):
                share[to[hit]] = v[hit] / steps
                held_any = True
    missing = np.nonzero(~filled)[0]
    if missing.size:
        raise RuntimeError(f"no part carried the state '{keys[int(missing[0])]}'")
    if held_any:
        stats['held'] = np.array([_js_round(v * stats['nsteps']) for v in share], dtype=np.int64)
    return {'t': t, 'rows': [Y[i].copy() for i in range(t.size)], 'stats': stats}


# --- running the jobs -----------------------------------------------------------------------

#: What a worker process is handed once, when it starts: the model as text,
#: the channels for progress back and a stop in (None where the caller asked
#: for neither), and the run's ``compiled`` setting. Set by
#: :func:`_start_part_worker`.
_WORKER: Dict[str, Any] = {}


#: The numerical libraries' thread pools, held to one thread in each worker
#: process: the parts are the parallelism here, and a library that starts a
#: thread per core in each of several processes spends the machine waiting
#: (OpenBLAS, which numpy's wheels carry on Linux, doubled a split's wall time
#: on eight processes).
_ONE_THREAD = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS',
               'NUMEXPR_NUM_THREADS')


@contextlib.contextmanager
def _one_thread_each() -> Any:
    """While the worker processes are started, which is when they take their
    environment: one thread per library, except where the caller has set it."""
    added = [k for k in _ONE_THREAD if k not in os.environ]
    for k in added:
        os.environ[k] = '1'
    try:
        yield
    finally:
        for k in added:
            os.environ.pop(k, None)


@contextlib.contextmanager
def _without_main() -> Any:
    """While the worker processes are started: no main module of the caller's
    for them to load. ``spawn`` runs a script's main module again in every
    process it starts -- its whole top level, model runs and all, unless the
    script has the ``if __name__ == '__main__':`` guard -- and a piped script
    has none to load, so its processes die. A part needs only this package,
    so the processes are not told of it."""
    main = sys.modules.get('__main__')
    if main is None:
        yield
        return
    own = vars(main)
    saved = {k: own[k] for k in ('__file__', '__spec__') if k in own}
    try:
        own.pop('__file__', None)
        if '__spec__' in saved:
            own['__spec__'] = None
        yield
    finally:
        own.update(saved)


def _start_part_worker(text: str, heard: Any, stop: Any, compiled: Any = 'auto') -> None:
    """A worker process's start: the model once rather than once per job, and
    the channels, which a process can only be given as it starts."""
    _WORKER.update(text=text, heard=heard, stop=stop, compiled=compiled)


def _remembered(system: Any, mem: Sequence[Any]) -> Dict[str, Any]:
    """The histories of the recorders that remember (a min/max, a running
    mean), by the name :func:`_recorder_owners` gives each entry."""
    out = {}
    space = system.layout.index_space
    for rec in system.recorders:
        if rec.kind not in ('min_max', 'running_mean') or rec.mem < 0:
            continue
        for off in range(rec.width):
            index = space.tuple_at(rec.dims, off) if rec.dims else []
            out[f"{rec.kind}:{rec.name}[{','.join(index)}]"] = mem[rec.mem + off]
    return out


def _part_job(job: int, materials: Sequence[str]) -> Dict[str, Any]:
    """One job, in a worker process: build the part, run it on the grid, and
    send back its states by name, its recorders' histories and its timing."""
    from .runner import run
    started = time.perf_counter()
    model = part_model(json.loads(_WORKER['text']), materials, copy_it=False)
    project, system, pinned = build_part(model)
    build_ms = (time.perf_counter() - started) * 1000
    heard, stop = _WORKER.get('heard'), _WORKER.get('stop')
    last = [0.0]

    def hear(fraction: float, at: float) -> None:
        # At most ten a second: each is a message to the caller's process.
        now = time.perf_counter()
        if heard is not None and now - last[0] > 0.1:
            last[0] = now
            heard.put((job, float(fraction), float(at)))

    watched = heard is not None or stop is not None
    results = run(project, system=system, on_grid=True, on_progress=hear if watched else None,
                  signal=stop.is_set if stop is not None else None, compiled=_WORKER.get('compiled', 'auto'))
    keys = state_keys(system.layout)
    if keys is None:
        raise RuntimeError('two states of this part share a name')
    stats = dict(results.stats or {})
    held = stats.pop('held', None)
    state = system.run_state()
    return {
        't': np.asarray(results.t, dtype=float),
        'y': np.array(results.y, dtype=float).reshape(len(results.t), -1),
        'keys': keys,
        'stats': stats,
        'held': None if held is None else np.asarray(held),
        'mem': _remembered(system, state['mem']),
        'dis': state['dis'],
        'sampled': state['sampled'],
        'clock': state['clock'],
        'timing': {'build_ms': build_ms, 'solve_ms': (results.timing or {}).get('solve_ms'), 'pinned': pinned},
        'pid': os.getpid(),
    }


def _aborted(signal: Any) -> bool:
    if signal is None:
        return False
    if callable(signal):
        return bool(signal())
    if isinstance(signal, dict):
        return bool(signal.get('aborted'))
    return bool(getattr(signal, 'aborted', False))


def run_split(project: Any, system: Any, plan: Dict[str, Any], *, workers: Optional[int] = None,
              on_progress: Optional[Callable[[float, float], Any]] = None, signal: Any = None,
              compiled: Any = 'auto') -> Dict[str, Any]:
    """The whole model, solved in its parts at once, as one run (``runSplit``).

    The jobs go to a pool of spawned worker processes, one per bin of the plan
    unless ``workers`` says otherwise, largest job first to whichever process
    is free; what each sends back is filed into the whole model's vector by
    name, and its recorders' histories onto the whole system. Each part is
    run with ``compiled`` as :func:`~kompartment.engine.runner.run` takes it.
    Returns ``{'solution', 'wall_ms', 'jobs', 'whole_ms', 'processes'}``;
    raises if anything does not add up, and the caller solves the whole model
    instead.
    """
    import concurrent.futures as cf
    import queue as queue_module
    from .solvers import SolverError
    jobs = plan['jobs']
    count = len(plan['bins']) if workers is None else max(1, min(int(workers), len(jobs)))
    order = sorted(range(len(jobs)), key=lambda j: (-jobs[j]['states'], j))
    ctx = mp.get_context('spawn')
    started = time.perf_counter()
    outcome: List[Optional[Dict[str, Any]]] = [None] * len(jobs)
    # Progress back and a stop in, only where the caller asked for them.
    heard = ctx.Queue() if on_progress is not None else None
    stop = ctx.Event() if signal is not None else None
    # Where each part is: its fraction, and its clock -- the run's start until
    # it has said, since a part that has not begun is there.
    progress = [(0.0, float(system.start_time))] * len(jobs)

    def stopped() -> SolverError:
        if stop is not None:
            stop.set()
        return SolverError('aborted', 'Simulation aborted', 0.0)

    executor = cf.ProcessPoolExecutor(max_workers=count, mp_context=ctx, initializer=_start_part_worker,
                                      initargs=(json.dumps(project.to_json()), heard, stop, compiled))
    try:
        # A process is started as a job is handed in, while no process is free.
        with _one_thread_each(), _without_main():
            futures = {executor.submit(_part_job, j, jobs[j]['materials']): j for j in order}
        pending = set(futures)
        while pending:
            if _aborted(signal):
                raise stopped()
            finished, pending = cf.wait(pending, timeout=0.1, return_when=cf.FIRST_COMPLETED)
            while heard is not None:
                try:
                    j, fraction, at = heard.get_nowait()
                except queue_module.Empty:
                    break
                if outcome[j] is None:
                    progress[j] = (fraction, at)
            for f in finished:
                j = futures[f]
                try:
                    outcome[j] = f.result()
                except Exception:
                    # A part that failed because the run was stopped is a
                    # stopped run, not a split that did not add up.
                    if _aborted(signal):
                        raise stopped() from None
                    raise
                progress[j] = (1.0, float(system.end_time))
            if on_progress is not None:
                # The parts' mean fraction, and the slowest part's clock: the
                # run is as far along as its last part.
                on_progress(sum(p[0] for p in progress) / len(progress), min(p[1] for p in progress))
    except BaseException:
        # Whatever ended it early, the parts still running are told to stop,
        # where they were given the means: a run with a signal.
        if stop is not None:
            stop.set()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        if heard is not None:
            heard.close()
    wall_ms = (time.perf_counter() - started) * 1000
    assembled = assemble_parts(plan, outcome)  # type: ignore[arg-type]
    # The recorders' histories, from the job that owns what each one reads.
    state = system.run_state()
    mem = list(state['mem'])
    for key, job, slot in plan.get('recorders') or []:
        carried = outcome[job]['mem'].get(key)  # type: ignore[index]
        if carried is None:
            raise RuntimeError(f"the part that owns '{key}' did not send its history back")
        mem[slot] = carried
    first = outcome[0]
    system.restore_run_state({'mem': mem, 'dis': first['dis'], 'sampled': first['sampled'],  # type: ignore[index]
                              'clock': first['clock']})  # type: ignore[index]
    summary = []
    for j, jb in enumerate(jobs):
        o = outcome[j]
        summary.append({'materials': jb['materials'], 'states': jb['states'],
                        'nsteps': (o['stats'] or {}).get('nsteps'),  # type: ignore[index]
                        'buildMs': o['timing']['build_ms'], 'solveMs': o['timing']['solve_ms']})  # type: ignore[index]
    n = int(system.layout.nstate)
    # What one process would have taken for the whole model, as the slowest
    # part stretched to the whole: kept for deciding the next run.
    whole_ms = max(((s['solveMs'] or 0.0) / job_cost(s['states'], n)) for s in summary)
    return {'solution': {'t': assembled['t'], 'y': assembled['rows'], 'stats': assembled['stats']},
            'wall_ms': wall_ms, 'jobs': summary, 'whole_ms': whole_ms,
            'processes': len({outcome[j]['pid'] for j in range(len(jobs))})}  # type: ignore[index]


#: What whole runs of each model layout have cost here, for deciding whether
#: the next one is worth splitting: layout signature -> ``{'solve_ms', 'gain'}``.
_MEMORY: Dict[str, Dict[str, Any]] = {}


def _in_worker_process() -> bool:
    """Whether this is a process some pool started: such a run is not split,
    which would start processes from processes."""
    return mp.parent_process() is not None


def run_whole_or_split(project: Any, *, on_progress: Optional[Callable[[float, float], Any]] = None,
                       on_grid: bool = False, signal: Any = None, workers: Optional[int] = None,
                       compiled: Any = 'auto') -> Any:
    """A run of the whole model -- solved in its parts when
    ``simulation.split`` says so and the plan agrees, whole otherwise -- with
    the plan's account in ``stats['split']``, as the application gives it.
    What :func:`kompartment.engine.runner.run` does with a project it builds
    itself; ``compiled`` goes to every run it makes, the parts' included."""
    from ..io.dataset import layout_signature
    from .builder import build_system
    from .runner import Results, run
    t0 = time.perf_counter()
    system = build_system(project)
    build_ms = (time.perf_counter() - t0) * 1000
    signature = layout_signature(system)
    known = _MEMORY.get(signature)
    cores = int(workers) if workers is not None else (os.cpu_count() or 1)
    plan = plan_split(system, project, mode=project.simulation.get('split') or 'auto', workers=cores,
                      nest=not _in_worker_process(), build_ms=build_ms, known=known, on_grid=on_grid)
    results = None
    if plan['use']:
        try:
            split = run_split(project, system, plan, workers=workers, on_progress=on_progress, signal=signal,
                              compiled=compiled)
            results = Results(project, system, split['solution'],
                              {'build_ms': build_ms, 'solve_ms': split['wall_ms'],
                               'total_ms': (time.perf_counter() - t0) * 1000})
            plan['jobs'] = split['jobs']
            plan['wall_ms'] = split['wall_ms']
            whole_ms = known['solve_ms'] if known and known.get('solve_ms') is not None else split['whole_ms']
            plan['gain'] = whole_ms / split['wall_ms'] if split['wall_ms'] > 0 else None
            _MEMORY[signature] = {'solve_ms': whole_ms, 'gain': plan['gain']}
        except Exception as e:  # noqa: BLE001 - a split that does not add up is solved whole instead
            from .solvers import SolverError
            if isinstance(e, SolverError) and e.code == 'aborted':
                raise
            plan['use'] = False
            plan['why'] = f'tried, and solved whole instead: {e}'
    if results is None:
        results = run(project, system=system, on_progress=on_progress, on_grid=on_grid, signal=signal,
                      compiled=compiled)
        timing = dict(results.timing or {})
        timing['build_ms'] = build_ms
        timing['total_ms'] = (timing.get('total_ms') or 0.0) + build_ms
        results.timing = timing
        _MEMORY[signature] = {**(known or {}), 'solve_ms': timing.get('solve_ms')}
    account: Dict[str, Any] = {'used': bool(plan['use']), 'mode': plan['mode'], 'why': plan['why'],
                               'predicted': plan.get('predicted')}
    if plan['use']:
        account.update(parts=plan['parts'], workers=len(plan['bins']), jobs=plan['jobs'], wallMs=plan['wall_ms'],
                       gain=plan.get('gain'))
    results.stats = {**(results.stats or {}), 'split': account}
    return results
