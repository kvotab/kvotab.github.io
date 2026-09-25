"""The times a model says it changes at, where the solver is restarted.

A port of ``src/domain/switchtimes.js`` and of ``constantValue`` in
``src/domain/transport.js``: the declared switch times (a number, or the name
of a parameter or expression that comes to one before the run starts), plus
the times waste packages fail at and events happen at.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Set

import numpy as np

from ..indexlists import parent_list_name
from ..names import qualified_name, resolve_reference
from . import codegen
from .codegen import Leaf
from .lang import ParseError, parse

_NUMBER = re.compile(r'^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$')
FAILURE_TIME_KEYS = {'never': [], 'at': ['fail_at'], 'uniform': ['fail_from', 'fail_to'],
                     'exponential': ['fail_start'], 'weibull': ['fail_start']}


def _get(project: Any, key: str, default: Any = None) -> Any:
    if isinstance(project, dict):
        return project.get(key, default)
    return getattr(project, key, default)


def _blocks(project: Any, collection: str) -> List[Dict[str, Any]]:
    if isinstance(project, dict):
        return project.get(collection) or []
    return project.blocks.get(collection, []) if hasattr(project, 'blocks') else []


def declared_switch_times(project: Any) -> List[Any]:
    lst = (_get(project, 'simulation') or {}).get('switch_times')
    return lst if isinstance(lst, list) else []


def _number(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def switch_times(project: Any) -> List[float]:
    sim = _get(project, 'simulation') or {}
    start = _number(sim.get('start_time', 0) if sim.get('start_time') is not None else 0)
    end = _number(sim.get('end_time', 0) if sim.get('end_time') is not None else 0)
    out: Set[float] = set()
    for entry in declared_switch_times(project):
        v = resolve_switch_time(project, entry)
        if v is None or not (v > start) or not (v < end):
            continue
        out.add(v)
    for w in _blocks(project, 'waste_packages'):
        failure = w.get('failure') if w.get('failure') in FAILURE_TIME_KEYS else 'never'
        for key in FAILURE_TIME_KEYS[failure]:
            v = resolve_switch_time(project, w.get(key))
            if v is None or not (v > start) or not (v < end):
                continue
            out.add(v)
    for d in _blocks(project, 'events'):
        keys = ['at'] if (d.get('timing') if d.get('timing') in ('at', 'poisson') else 'at') == 'at' \
            else ['from', 'until']
        for key in keys:
            v = resolve_switch_time(project, d.get(key))
            if v is None or not (v > start) or not (v < end):
                continue
            out.add(v)
    return sorted(out)


def resolve_switch_time(project: Any, entry: Any) -> Optional[float]:
    if isinstance(entry, (int, float)) and not isinstance(entry, bool):
        return float(entry) if math.isfinite(entry) else None
    name = str(entry if entry is not None else '').strip()
    if not name:
        return None
    if _NUMBER.match(name):
        return float(name)
    found = _find_by_name(project, name)
    if found is None:
        return None
    v = constant_value(project, found[0], found[1])
    return v if v is not None and math.isfinite(v) else None


def _find_by_name(project: Any, name: str) -> Optional[tuple]:
    for collection, kind in (('parameters', 'parameter'), ('expressions', 'expression')):
        for b in _blocks(project, collection):
            if qualified_name(b) == name:
                return b, kind
    return None


def _scenario_dims(project: Any) -> List[str]:
    lists = _get(project, 'index_lists') or []
    root = next((l['name'] for l in lists if l.get('for_scenarios')), None)
    if not root:
        return []
    by_name = {l['name']: l for l in lists}
    out = []
    for l in lists:
        at = l['name']
        i = 0
        while at and i <= len(by_name):
            if at == root:
                out.append(l['name'])
                break
            at = parent_list_name(by_name.get(at))
            i += 1
    return out


def _active_scenario(project: Any) -> Optional[str]:
    lst = next((l for l in _get(project, 'index_lists') or [] if l.get('for_scenarios')), None)
    names = []
    for i in (lst or {}).get('indices') or []:
        item = {'name': i, 'enabled': True} if isinstance(i, str) else i
        if item and item.get('name') and item.get('enabled') is not False:
            names.append(item['name'])
    if not names:
        return None
    sc = _get(project, 'scenario')
    return sc if sc in names else names[0]


def _constant_entry(project: Any, block: Dict[str, Any], key: str, dims: List[str]) -> Any:
    if not dims:
        return block.get(key)
    scen = set(_scenario_dims(project))
    if not all(d in scen for d in dims):
        return None
    active = _active_scenario(project)
    for e in block.get('entries') or []:
        if e and key in e and all(v == active for v in (e.get('index') or {}).values()):
            return e[key]
    return block.get(key)


def constant_value(project: Any, block: Optional[Dict[str, Any]], kind: str,
                   seen: Optional[Set[str]] = None) -> Optional[float]:
    """A block's value for the run when it has one: a parameter's number, or an
    expression made of numbers and such blocks."""
    if not block:
        return None
    seen = seen or set()
    dims = block.get('index_lists') or []
    if kind == 'parameter':
        v = _number(_constant_entry(project, block, 'value', dims))
        return v if math.isfinite(v) else None
    if kind != 'expression':
        return None
    text = _constant_entry(project, block, 'equation', dims)
    if text is None:
        return None
    try:
        ast = parse(str(text))
    except ParseError:
        return None
    system = block.get('system') or ''
    own = qualified_name(block)

    def find(q: str) -> Optional[tuple]:
        for b in _blocks(project, 'parameters'):
            if qualified_name(b) == q:
                return b, 'parameter'
        for b in _blocks(project, 'expressions'):
            if qualified_name(b) == q:
                return b, 'expression'
        return None

    ok = [True]

    def ref(name: str, indices: Any, node: Any = None) -> Leaf:
        if not ok[0]:
            return Leaf('K', 0.0)
        if indices:
            ok[0] = False
            return Leaf('K', 0.0)
        q = resolve_reference(name, system, lambda n: find(n) is not None)
        if not q or q == own or q in seen:
            ok[0] = False
            return Leaf('K', 0.0)
        target = find(q)
        v = constant_value(project, target[0], target[1], seen | {own})  # type: ignore[index]
        if v is None:
            ok[0] = False
            return Leaf('K', 0.0)
        return Leaf('K', v)

    try:
        tree = codegen.resolve(ast, ref)
    except ValueError:
        return None
    if not ok[0]:
        return None
    sim = _get(project, 'simulation') or {}
    start = _number(sim.get('start_time', 0) or 0)
    end = _number(sim.get('end_time', 0) or 0)
    try:
        v = _evaluate(tree, start, end)
    except Exception:  # noqa: BLE001 - a value that cannot be worked out is not a constant
        return None
    return v if math.isfinite(v) else None


def _evaluate(tree: Any, start: float, end: float) -> float:
    writer = codegen.CodeWriter()
    ns = writer.ns
    ns.update(T=np.float64(start), T0=np.float64(start), T1=np.float64(end))
    code = writer.expression(tree, vector=False)
    with np.errstate(all='ignore'):
        return float(eval(code, ns))  # noqa: S307 - generated from a parsed equation
