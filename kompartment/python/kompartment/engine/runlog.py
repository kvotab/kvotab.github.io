"""The run log: what a run was, in words that survive it.

A port of the application's ``src/domain/runlog.js`` -- the account a run
keeps of itself (program, date, the settings, how the solve went, what was
held at zero, whether the mass balance closed), which the page shows under
*Run log* and writes into a results archive -- and of ``describeAudit`` from
``src/domain/massbalance.js``, which it ends with::

    import kompartment as kp
    from kompartment.engine import runlog

    res = kp.load('biosphere.json').run()
    print(runlog.run_log(res))

:func:`run_log_lines` takes what the application's takes: the model (the
project dictionary) and a *payload* in the worker's words -- ``stats``,
``timing`` (``buildMs``, ``solveMs``), ``jacobian``, ``heldAtZero``,
``stateCount``, ``outputs``, ``t``, ``massBalance``. :func:`payload_of` makes
that payload from a :class:`kompartment.engine.Results`, as the worker's
``donePayload`` does, including the application's account of how df/dy was
obtained (:func:`jacobian_of`). Numbers are written as the page writes them
(``toFixed``, ``toExponential``, ``toPrecision``, ``String``), so the two logs
of one payload are the same text.
"""

from __future__ import annotations

import datetime as _dt
import math
import numbers
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ..io.csv import JS_WHITESPACE, is_js_boolean, js_string, js_to_number
from ..simulation import SOLVER_OPTIONS
from ..stats.pdf import _to_exponential, _to_precision

__all__ = ['run_log_lines', 'scenario_log_lines', 'probabilistic_log_lines', 'run_log_text', 'describe_audit',
           'jacobian_of', 'payload_of', 'run_log']

DEFAULT_SOLVER = 'ndf'

#: The Python engine's names for what the application calls otherwise.
_STATS_NAMES = {'solver_points': 'solverPoints', 'thinned_by': 'thinnedBy'}
_TIMING_NAMES = {'build_ms': 'buildMs', 'solve_ms': 'solveMs', 'total_ms': 'totalMs'}

_SPACE = re.compile('[' + ''.join(re.escape(c) for c in JS_WHITESPACE) + ']+')


# --- JavaScript's rules, where Python's differ ----------------------------------------------

class _Undefined:
    def __repr__(self) -> str:
        return 'undefined'

    def __bool__(self) -> bool:
        return False


_UNDEF = _Undefined()


def _nullish(v: Any) -> bool:
    return v is None or v is _UNDEF


def _get(obj: Any, key: str) -> Any:
    """``obj?.[key]``: ``undefined`` for a key that is not there, or an object that is not one."""
    if isinstance(obj, Mapping):
        return obj.get(key, _UNDEF)
    if obj is None or obj is _UNDEF or isinstance(obj, (str, numbers.Number)):
        return _UNDEF
    return getattr(obj, key, _UNDEF)


def _nz(v: Any, default: Any) -> Any:
    """``v ?? default``."""
    return default if _nullish(v) else v


def _truthy(v: Any) -> bool:
    if _nullish(v):
        return False
    if is_js_boolean(v):
        return bool(v)
    if isinstance(v, numbers.Real):
        return not (v == 0 or v != v)
    if isinstance(v, str):
        return v != ''
    return True


def _s(v: Any) -> str:
    """``${v}``: ``String(v)``, ``undefined`` included."""
    return 'undefined' if v is _UNDEF else js_string(v)


def _number(v: Any) -> float:
    """``Number(v)``: ``undefined`` is NaN, ``null`` 0."""
    if v is _UNDEF:
        return math.nan
    return js_to_number(v)


def _to_fixed(v: Any, digits: int) -> str:
    """``Number(v).toFixed(digits)``: the exact value rounded half up, the sign
    kept on a negative number that rounds to nothing, ``String(x)`` past 1e21."""
    x = _number(v)
    if math.isnan(x):
        return 'NaN'
    if abs(x) >= 1e21:
        return js_string(x)
    sign = '-' if x < 0 else ''
    d = Decimal(abs(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return sign + f'{d:f}'


def _js_round(x: float) -> float:
    """``Math.round``: halves go up, towards +Infinity."""
    if math.isnan(x) or math.isinf(x):
        return x
    r = math.floor(x)
    return float(r + 1 if x - r >= 0.5 else r)


def _gt(v: Any, n: float) -> bool:
    """``v > n``, which is false for anything that is not a number."""
    x = _number(v)
    return not math.isnan(x) and x > n


def _length(v: Any) -> Any:
    """``v?.length``."""
    if _nullish(v):
        return _UNDEF
    if hasattr(v, 'shape') and hasattr(v, 'size'):
        return int(v.size) if getattr(v, 'ndim', 1) <= 1 else int(v.shape[0])
    try:
        return len(v)
    except TypeError:
        return _UNDEF


def _join(values: Any, sep: str) -> str:
    """``values.join(sep)``: ``null`` and ``undefined`` as nothing."""
    return sep.join('' if _nullish(v) else _s(v) for v in (values or []))


def _utf16_prefix(s: str, units: int) -> str:
    """``s.slice(0, units)``, in UTF-16 code units as JavaScript counts."""
    if all(ord(c) < 0x10000 for c in s):
        return s[:units]
    return s.encode('utf-16-le', 'surrogatepass')[:2 * units].decode('utf-16-le', 'surrogatepass')


def _iso(at: Any) -> str:
    """``date.toISOString()``: UTC, to the millisecond. A naive ``datetime`` is
    local time, as the page's clock is; ``None`` is now."""
    if at is None:
        d = _dt.datetime.now(_dt.timezone.utc)
    elif isinstance(at, _dt.datetime):
        d = at.astimezone(_dt.timezone.utc)
    elif isinstance(at, _dt.date):
        d = _dt.datetime(at.year, at.month, at.day).astimezone(_dt.timezone.utc)
    else:
        d = _dt.datetime.fromtimestamp(float(at), _dt.timezone.utc)
    return f'{d.year:04d}-{d:%m-%dT%H:%M:%S}.{d.microsecond // 1000:03d}Z'


def _project_dict(project: Any) -> Any:
    if project is None or isinstance(project, Mapping):
        return project
    raw = getattr(project, 'raw', None)
    if isinstance(raw, Mapping):
        return raw
    raw = getattr(project, '_raw', None)
    if isinstance(raw, Mapping):
        return raw
    return {'name': getattr(project, 'name', None), 'description': getattr(project, 'description', None),
            'simulation': getattr(project, 'simulation', None) or {}}


# --- the mass-balance audit, in words (src/domain/massbalance.js) ---------------------------

def _audit_num(v: Any) -> str:
    """A number as the audit's report writes it."""
    x = _number(v)
    if x == 0:
        return '0'
    if abs(x) >= 1e-3 and abs(x) < 1e6:
        return js_string(float(_to_precision(x, 4)))
    return _to_exponential(x, 3)


def describe_audit(a: Mapping[str, Any], time_unit: Any = '') -> List[str]:
    """The mass-balance audit as lines (``describeAudit``): whether it closes,
    then one line per family -- what it holds at the end and what that is made
    of, and its residual."""
    unit = f' {_s(time_unit)}' if _truthy(time_unit) else ''
    out = []
    worst_family = _get(a, 'worstFamily')
    if _truthy(_get(a, 'closed')):
        out.append(f"mass balance: closes — worst relative residual {_to_exponential(_number(_get(a, 'worst')), 1)}"
                   + (f" ({_s(worst_family)} at t = {_audit_num(_get(a, 'at'))}{unit})"
                      if _truthy(worst_family) else ''))
    else:
        out.append(f"mass balance: DOES NOT CLOSE — relative residual {_to_exponential(_number(_get(a, 'worst')), 2)} "
                   f"in {_s(worst_family)} at t = {_audit_num(_get(a, 'at'))}{unit}; a state held at zero, or an "
                   'amount the equations moved that nothing accounts for')
    for f in _get(a, 'families') or []:
        if _truthy(_get(f, 'unresolved')):
            out.append(f"  {_s(_get(f, 'name'))}: never more than {_audit_num(_get(f, 'scale'))} held or moved, "
                       f"within the absolute tolerance {_audit_num(_get(f, 'floor'))} -- too little for the solver "
                       'to resolve, so not audited')
            continue
        if _truthy(_get(f, 'idle')):
            out.append(f"  {_s(_get(f, 'name'))}: nothing held or moved")
            continue
        r = _get(f, 'final')
        parts = [f"start {_audit_num(_get(r, 'start'))}", f"+ in {_audit_num(_get(r, 'in'))}",
                 f"− out {_audit_num(_get(r, 'out'))}", f"− decay {_audit_num(_get(r, 'decay'))}",
                 f"+ ingrowth {_audit_num(_get(r, 'ingrowth'))}"]
        for key in ('explicit', 'between'):
            x = _number(_get(r, key))
            if not x == 0:
                parts.append(f"{'−' if x < 0 else '+'} {key} {_audit_num(abs(x))}")
        out.append(f"  {_s(_get(f, 'name'))}: holds {_audit_num(_get(r, 'inventory'))} at the end = "
                   f"{' '.join(parts)}; residual {_audit_num(_get(r, 'residual'))} "
                   f"({_to_exponential(_number(_get(f, 'relative')), 1)} relative, worst at t = "
                   f"{_audit_num(_get(f, 'at'))}{unit})")
    return out


# --- the log ------------------------------------------------------------------------------------

def _inventory_unit(project: Any) -> str:
    """What a radionuclide inventory is measured in (``inventoryUnit``): ``mol``
    where the model says so, ``Bq`` otherwise."""
    given = _get(project, 'decayUnit')
    if _nullish(given):
        given = _get(project, 'decay_unit')
    return 'mol' if _s('' if _nullish(given) else given).strip(JS_WHITESPACE) == 'mol' else 'Bq'


def _settings_lines(sim: Any, project: Any = None) -> List[str]:
    """One line per setting, in the order somebody reads them. The decay unit
    is the model's -- it lives at the top of the file, beside the nuclides --
    and is always one of the two, ``Bq`` when unset."""
    if sim is _UNDEF:
        sim = {}
    if sim is None:
        raise TypeError("Cannot read properties of null (reading 'time_unit')")
    out: List[str] = []

    def put(label: str, v: Any) -> None:
        if not _nullish(v) and not (isinstance(v, str) and v == ''):
            out.append(f'  {label}: {_s(v)}')

    put('time unit', _get(sim, 'time_unit'))
    put('span', f"{_s(_get(sim, 'start_time'))} – {_s(_get(sim, 'end_time'))}")
    spacing = _get(sim, 'spacing')
    put('output times', 'a series of the model’s own' if spacing == 'series'
        else f"{_s(_nz(_get(sim, 'output_points'), '?'))}, {_s(_nz(spacing, 'log'))}")
    put('solver', _get(sim, 'solver'))
    put('relative tolerance', _get(sim, 'rtol'))
    put('absolute tolerance', _get(sim, 'abstol'))
    put('cannot go negative', 'off everywhere' if _get(sim, 'non_negative') is False else 'per compartment')
    if _truthy(_get(sim, 'mass_balance')):
        put('mass-balance audit', 'on')
    if _truthy(_get(sim, 'auto_abstol')):
        put('tolerance follows the solution', 'each component’s absolute tolerance rises with it')
    put('decay unit', _inventory_unit(sim if project is None else project))
    if _gt(_get(sim, 'decay_ceiling'), 0):
        put('decay chains stop above', f"{_s(_get(sim, 'decay_ceiling'))} years")
    return out


def run_log_lines(project: Any, payload: Any, replayed: Any = None, build: str = '',
                  at: Any = None) -> List[str]:
    """The log of a deterministic run, as lines (``runLogLines``).

    ``project`` is the model (the project dictionary, or a
    :class:`kompartment.Model`); ``payload`` what the run reported, in the
    worker's words (see :func:`payload_of`); ``replayed`` -- ``{'index',
    'iterations', 'seed', 'values', 'tornado'}`` -- when the run is one
    realisation replayed; ``build`` the program's build stamp; ``at`` when
    (a ``datetime``; naive is local time; ``None`` is now).
    """
    project = _project_dict(project)
    s = _nz(_get(payload, 'stats'), {})
    t = _nz(_get(payload, 'timing'), {})
    out: List[str] = []
    out.append(f"Kompartment run log{f' — build {_s(build)}' if _truthy(build) else ''}")
    out.append(_iso(at))
    out.append(f"model: {_s(_nz(_get(project, 'name'), 'Untitled'))}")
    description = _get(project, 'description')
    if _truthy(description):
        out.append('  ' + _utf16_prefix(_SPACE.sub(' ', _s(description)), 200))
    out.append('')
    out.append('settings')
    out.extend(_settings_lines(_get(project, 'simulation'), project))
    out.append('')
    if _truthy(replayed):
        index = _number(_get(replayed, 'index'))
        iterations = _s(_get(replayed, 'iterations'))
        out.append(f'this is design point {js_string(index + 1)} of {iterations} of a tornado'
                   if _truthy(_get(replayed, 'tornado'))
                   else f"this is realisation {js_string(index + 1)} of {iterations}, seed {_s(_get(replayed, 'seed'))}")
        for v in _nz(_get(replayed, 'values'), []):
            value = _get(v, 'value')
            finite = isinstance(value, numbers.Real) and not is_js_boolean(value) and math.isfinite(value)
            out.append(f"  {_s(_get(v, 'name'))} = {js_string(value) if finite else '—'}"
                       f"{' (held)' if _truthy(_get(v, 'held')) else ''}")
        out.append('')
    out.append('run')
    if _get(s, 'integrated') is False:
        out.append('  nothing integrated: no compartments, the algebraic blocks over the output grid')
    else:
        out.append(f"  states: {_s(_nz(_get(payload, 'stateCount'), '?'))}")
        out.append(f"  steps: {_s(_nz(_get(s, 'nsteps'), '?'))}, rejected: {_s(_nz(_get(s, 'nfailed'), 0))}, "
                   f"f evaluations: {_s(_nz(_get(s, 'nfevals'), '?'))}")
        if _truthy(_get(s, 'nbelowtol')):
            out.append(f"  steps taken below tolerance: {_s(_get(s, 'nbelowtol'))}")
        if not _nullish(_get(s, 'events')):
            out.append(f"  events: {_s(_get(s, 'events'))}, restarts: {_s(_nz(_get(s, 'restarts'), 0))}")
        if not _nullish(_get(s, 'jumps')):
            out.append(f"  jumps: {_s(_get(s, 'jumps'))} — package failures at a time and disruptive events, "
                       'applied to the state at their corners')
        j = _get(payload, 'jacobian')
        if _truthy(j):
            if _truthy(_get(j, 'available')):
                colours = _get(j, 'colours')
                out.append(f"  df/dy: analytic, {'sparse' if _truthy(_get(j, 'sparse')) else 'dense'}"
                           f"{f', {_s(colours)} colours' if _truthy(colours) else ''}"
                           f"{', constant' if _truthy(_get(j, 'constant')) else ''}")
            else:
                reason = _get(j, 'reason')
                out.append(f"  df/dy: differenced{f' — {_s(reason)}' if _truthy(reason) else ''}")
    split = _get(s, 'split')
    if _truthy(_get(split, 'used')):
        jobs = _nz(_get(split, 'jobs'), [])
        out.append(f"  split: {len(jobs)} independent parts on {_s(_get(split, 'workers'))} cores "
                   f"({_s(_get(split, 'mode'))}) — {_s(_get(split, 'why'))}")
        for job in jobs:
            out.append(f"    {_join(_get(job, 'materials'), ', ')}: {_s(_get(job, 'states'))} states, "
                       f"{_s(_nz(_get(job, 'nsteps'), '?'))} steps, "
                       f"compile {_to_fixed(_nz(_get(job, 'buildMs'), 0), 1)} ms, "
                       f"solve {_to_fixed(_nz(_get(job, 'solveMs'), 0), 0)} ms")
        gain = _get(split, 'gain')
        if _truthy(gain):
            out.append(f'    about {_to_fixed(gain, 1)}× a whole solve, by this machine\'s estimate')
    elif _truthy(split):
        out.append(f"  not split ({_s(_get(split, 'mode'))}): {_s(_get(split, 'why'))}")
    out.append(f"  output points: {_s(_nz(_length(_get(payload, 't')), '?'))}")
    out.append(f"  series: {_s(_nz(_length(_get(payload, 'outputs')), '?'))}")
    solve = ('not repeated (states reused)' if _truthy(_get(t, 'reused'))
             else f"{_to_fixed(_nz(_get(t, 'solveMs'), 0), 0)} ms")
    out.append(f"  compile: {_to_fixed(_nz(_get(t, 'buildMs'), 0), 1)} ms, solve: {solve}")
    held = _nz(_get(payload, 'heldAtZero'), [])
    if len(held):
        out.append('')
        out.append(f"held at zero: {len(held)} state{'' if len(held) == 1 else 's'} the model pushed below zero")
        for h in list(held)[:20]:
            out.append(f"  {_s(_get(h, 'label'))}: {_s(_get(h, 'steps'))} steps, "
                       f"{_to_fixed(100 * _number(_get(h, 'fraction')), 1)}% of the run")
        if len(held) > 20:
            out.append(f'  and {len(held) - 20} more')
    audit = _get(payload, 'massBalance')
    if _truthy(audit):
        out.append('')
        out.extend(describe_audit(audit, _nz(_get(_get(project, 'simulation'), 'time_unit'), '')))
    return out


def scenario_log_lines(active: Any, runs: Optional[Sequence[Any]]) -> List[str]:
    """The scenarios run beside the selected one, appended under its log
    (``scenarioLogLines``): ``runs`` is ``[{'name', 'r', 'error', 'running',
    'queued'}]``, ``r`` a run's report (``stats``, ``timing``)."""
    if not runs:
        return []
    out = ['', 'scenarios run together', f'  {_s(active)} — the selected scenario, the run described above']
    for e in runs:
        name = _s(_get(e, 'name'))
        if _truthy(_get(e, 'error')):
            out.append(f"  {name} — did not run: {_s(_get(e, 'error'))}")
            continue
        if _truthy(_get(e, 'running')) or _truthy(_get(e, 'queued')):
            out.append(f'  {name} — still running')
            continue
        r = _get(e, 'r')
        s = _nz(_get(r, 'stats'), {})
        t = _nz(_get(r, 'timing'), {})
        if _truthy(r):
            solve = ('not repeated (states reused)' if _truthy(_get(t, 'reused'))
                     else f"{_to_fixed(_nz(_get(t, 'solveMs'), 0), 0)} ms")
            split = _get(s, 'split')
            out.append(f"  {name} — {_s(_nz(_get(s, 'nsteps'), '?'))} steps, compile "
                       f"{_to_fixed(_nz(_get(t, 'buildMs'), 0), 1)} ms, solve {solve}"
                       + (f", in {len(_get(split, 'jobs'))} parts on {_s(_get(split, 'workers'))} cores"
                          if _truthy(_get(split, 'used')) else ''))
        else:
            out.append(f'  {name} — not run yet')
    return out


def probabilistic_log_lines(prob: Any) -> List[str]:
    """The log of a probabilistic run (or a tornado), appended under the
    deterministic one (``probabilisticLogLines``): ``prob`` is ``{'iterations',
    'stats', 'plan', 'screen'}``."""
    if not _truthy(prob):
        return []
    s = _nz(_get(prob, 'stats'), {})
    tornado = _get(s, 'tornado')
    out = ['', 'tornado' if _truthy(tornado) else 'probabilistic run',
           f"  {'design points' if _truthy(tornado) else 'realisations'}: {_s(_get(prob, 'iterations'))}"]
    if not _truthy(tornado):
        out.append(f"  seed: {_s(_get(s, 'seed'))}, sampling: "
                   f"{'independent draws' if _get(s, 'latin') is False else 'Latin hypercube'}")
    else:
        low = js_string(_js_round(_number(_get(tornado, 'low')) * 100))
        high = js_string(_js_round(_number(_get(tornado, 'high')) * 100))
        out.append(f'  swung to the {low}th and {high}th percentiles')
    plan = _get(prob, 'plan')
    out.append(f"  sampled inputs: {_s(_nz(_get(s, 'sampled'), _nz(_length(plan), '?')))}")
    if _truthy(_get(s, 'correlated')):
        adjusted = _get(s, 'correlationAdjusted')
        out.append(f"  correlated inputs: {_s(_get(s, 'correlated'))}"
                   + (f', target matrix moved by up to {_to_fixed(adjusted, 3)} to be achievable'
                      if _gt(adjusted, 0) else ''))
    for p in _nz(_get(s, 'correlationProblems'), []):
        out.append(f'  correlation ignored: {_s(p)}')
    if _gt(_get(s, 'workers'), 1):
        out.append(f"  over {_s(_get(s, 'workers'))} workers")
    out.append(f"  wall clock: {_to_fixed(_number(_nz(_get(s, 'ms'), 0)) / 1000, 1)} s")
    if _truthy(_get(s, 'failed')):
        out.append(f"  failed realisations: {_s(_get(s, 'failed'))}")
        for line in _nz(_get(s, 'trouble'), []):
            out.append(f'    {_s(line)}')
    screen = _get(prob, 'screen')
    if _truthy(screen):
        out.append(f"  categories: {_join(_get(screen, 'counts'), ', ')} (last is Other); "
                   f"{_s(_get(screen, 'kept'))} of {_s(_get(prob, 'iterations'))} shown")
    return out


def run_log_text(parts: Iterable[Any]) -> str:
    """The whole log as one text (``runLogText``): the lines that are there, joined."""
    return '\n'.join(_s(line) for line in parts if not _nullish(line))


# --- from a Results -------------------------------------------------------------------------

def _renamed(d: Any, names: Mapping[str, str]) -> Any:
    if not isinstance(d, Mapping):
        return d
    return {names.get(k, k): v for k, v in d.items()}


def jacobian_of(results: Any) -> Dict[str, Any]:
    """How df/dy was obtained, as the application's ``Results.jacobian`` says it:
    ``{'available': False, 'reason'}`` for a differenced one, and the analytic
    one's colours, non-zeros, density, sparsity and fill otherwise -- or, where
    the model asked for a numeric Jacobian from a solver that reads the setting,
    the same with ``available`` false and ``asked`` true."""
    j = getattr(results.system, 'jacobian', None)
    if not _truthy(_get(j, 'available')):
        reason = _get(j, 'reason')
        return {'available': False, 'reason': None if _nullish(reason) else reason}
    sim = results.project.simulation
    stats = results.stats or {}
    budget = _get(j, 'budgetRows')
    if _nullish(budget):
        budget = _get(j, 'budget_rows')
    fill = stats.get('fill')

    def common() -> Dict[str, Any]:
        return {'colours': _nz(_get(j, 'colours'), None), 'nnz': _nz(_get(j, 'nnz'), None),
                'density': _nz(_get(j, 'density'), None), 'sparse': _truthy(stats.get('sparse')),
                'fill': None if fill is None else fill}

    extra = {'budgetRows': budget} if _truthy(budget) else {}
    solver = sim.get('solver') if sim.get('solver') is not None else DEFAULT_SOLVER
    if sim.get('jacobian') == 'numeric' and 'jacobian' in SOLVER_OPTIONS.get(solver, ()):
        return {'available': False, 'asked': True, **common(), **extra}
    return {'available': True, 'constant': _nz(_get(j, 'constant'), None), **common(), **extra}


def payload_of(results: Any) -> Dict[str, Any]:
    """What the application's worker reports of a run (``donePayload``), as far
    as the log reads it: ``t``, ``outputs``, ``stats``, ``timing``,
    ``stateCount``, ``jacobian``, ``heldAtZero`` and ``massBalance`` -- the
    statistics and timings under the application's names."""
    return {
        't': results.t,
        'outputs': results.outputs(),
        'stats': _renamed(results.stats, _STATS_NAMES),
        'timing': _renamed(results.timing, _TIMING_NAMES),
        'stateCount': results.system.layout.nstate,
        'jacobian': jacobian_of(results),
        'heldAtZero': results.held_at_zero(),
        'massBalance': results.mass_balance(),
    }


def run_log(results: Any, *, project: Any = None, build: str = '', at: Any = None, replayed: Any = None) -> str:
    """The log of a run, as text: :func:`run_log_lines` of :func:`payload_of`.
    ``project`` defaults to the model the run was built from."""
    raw = _project_dict(results.project if project is None else project)
    return run_log_text(run_log_lines(raw, payload_of(results), replayed=replayed, build=build, at=at))
