"""Checking a model: in Python, and through Kompartment's own validator.

:func:`check_model` finds, without leaving Python, the faults an edit through
this package can still leave -- mostly by editing :attr:`Model.raw` or a block's
raw values directly: a name that is not a name, a transfer end that is not a
block, an equation that reads nothing, an index list nobody defined, a
per-index value keyed by an index that does not exist.

:func:`validate_with_node` hands the model to the application's own code --
the loader, the equation checker, the builder -- through Node.js, and reports
exactly what the application would.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from .blocks import (
    AVAILABILITY_SCHEMES, DIRECTIONS, EXTREMES, FAILURES, INTERPOLATIONS, OPERATIONS, SINGULAR, TIMINGS,
)
from .equations import EquationSyntaxError, _reference_tokens, tokenize
from .errors import ValidationError
from .indexlists import clashing_dimensions, clashing_dimensions_why, find_list, index_name, list_applies
from .keys import COLLECTIONS
from .names import RESERVED, name_problem, qualified_name, resolve_reference, system_of
from .simulation import SOLVERS, SPACINGS, TIME_UNITS

if TYPE_CHECKING:  # pragma: no cover
    from .model import Model

#: The equations each kind writes, block-level and per entry.
EQUATION_FIELDS: Dict[str, tuple] = {
    'compartment': ('initial', 'dydt'), 'transfer': ('rate',), 'inflow': ('rate',),
    'expression': ('equation',), 'function': ('equation',),
    'min_max': ('target',), 'running_mean': ('target',), 'snapshot': ('target', 'initial'),
    'delay': ('target', 'delay'), 'trigger': ('first', 'second'),
    'farfield': ('tw', 'f', 'kd_f', 'kd_m', 'de_m', 'eps_m', 'rho_m', 'pe', 'pen_dep', 'pen_dep_0'),
    'waste_package': ('inventory', 'irf', 'degradation_rate', 'fail_at', 'fail_from', 'fail_to',
                      'fail_start', 'fail_rate', 'fail_scale', 'fail_shape'),
    'event': ('at', 'rate', 'from', 'until'),
}
TRIGGER_FIELDS = {
    'min_max': ('reset_trigger', 'start_trigger', 'stop_trigger'),
    'running_mean': ('reset_trigger', 'start_trigger', 'stop_trigger'),
    'snapshot': ('trigger',),
}


def _equation_problem(text: Any, system: str, known: Any, locals_: Optional[Set[str]] = None) -> Optional[str]:
    """What is wrong with one equation's characters and names, or ``None``."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        tokens = tokenize(text)
    except EquationSyntaxError as e:
        return f'{e} at position {e.position + 1}'
    depth = 0
    for t in tokens:
        if t.type == 'lparen':
            depth += 1
        elif t.type == 'rparen':
            depth -= 1
            if depth < 0:
                return "a ')' closes nothing"
    if depth > 0:
        return "a '(' is never closed"
    for tok in _reference_tokens(tokens, locals_):
        if tok.text in RESERVED:
            continue  # a function with no arguments written bare: time, pi, eps
        if resolve_reference(tok.text, system, known) is None:
            return f"reads '{tok.text}', which is not a block"
    return None


def check_model(model: 'Model') -> List[str]:
    """Every fault :mod:`kompartment` can see in a model, in words."""
    raw = model.raw
    out: List[str] = []
    names: Dict[str, str] = {}
    known = model._known()
    lists = model._lists()
    systems = set(model.systems)

    for collection in COLLECTIONS:
        items = raw.get(collection)
        if items is None:
            continue
        if not isinstance(items, list):
            out.append(f"'{collection}' is not a list of blocks")
            continue
        kind = SINGULAR[collection]
        for b in items:
            if not isinstance(b, dict):
                out.append(f"'{collection}' holds something that is not a block: {b!r}")
                continue
            q = qualified_name(b)
            problem = name_problem(b.get('name'))
            if problem:
                out.append(f'{q or "(unnamed)"}: {problem}')
            if q in names:
                out.append(f"'{q}' is the name of two blocks ({names[q]} and {kind})")
            names.setdefault(q, kind)
            if q in systems:
                out.append(f"'{q}' is the name of a block and of a sub-system")
            where = system_of(b)
            if where and any(name_problem(p) for p in where.split('.')):
                out.append(f"{q}: '{where}' is not a valid sub-system path")

            dims = b.get('index_lists')
            if isinstance(dims, list) and kind not in ('function', 'event'):
                for d in dims:
                    lst = find_list(lists, d)
                    if lst is None:
                        out.append(f"{q} is indexed by '{d}', which is not an index list of the model")
                    elif not list_applies(lst, kind):
                        out.append(f"{q} is a {kind.replace('_', ' ')} and cannot be indexed by '{d}'")
                clash = clashing_dimensions(lists, [d for d in dims if find_list(lists, d)])
                if clash:
                    out.append(f'{q}: {clashing_dimensions_why(clash)}')
                for e in b.get('entries') or []:
                    ix = e.get('index') if isinstance(e, dict) else None
                    if not isinstance(ix, dict):
                        out.append(f'{q}: a per-index value has no index')
                        continue
                    for lst_name, idx in ix.items():
                        if lst_name not in dims:
                            out.append(f"{q}: a per-index value is keyed by '{lst_name}', which the block is not indexed by")
                            continue
                        lst = find_list(lists, lst_name)
                        if lst is not None and idx not in [index_name(i) for i in lst.get('indices') or []]:
                            out.append(f"{q}: a per-index value is keyed by '{idx}', which is not an index of '{lst_name}'")

            system = where
            locals_ = set(map(str, b.get('parameters') or [])) if kind == 'function' else None
            for field in EQUATION_FIELDS.get(kind, ()):
                if kind == 'expression' and b.get('transport') in ('counter', 'operation'):
                    continue
                for holder in [b, *(e for e in b.get('entries') or [] if isinstance(e, dict))]:
                    problem = _equation_problem(holder.get(field), system, known, locals_)
                    if problem:
                        out.append(f'{q}: its {field.replace("_", " ")} {problem}')
            if kind == 'function' and not str(b.get('equation') or '').strip():
                out.append(f"{q} has no body yet")

            if kind in ('transfer', 'inflow'):
                for end in ('from', 'to') if kind == 'transfer' else ('to',):
                    v = b.get(end)
                    if v is None:
                        continue
                    k = model._kind_of(v)
                    if k is None:
                        out.append(f"{q}: its {'source' if end == 'from' else 'target'} '{v}' is not a block")
                    elif k not in ('compartment', 'farfield', 'waste_package') or (k == 'waste_package' and end == 'to'):
                        out.append(f"{q}: its {'source' if end == 'from' else 'target'} '{v}' is a "
                                   f"{k.replace('_', ' ')}, which a flux cannot {'leave' if end == 'from' else 'enter'}")
                if kind == 'transfer' and b.get('from') is None and b.get('to') is None:
                    out.append(f'{q} runs from nowhere to nowhere')
                if kind == 'inflow' and b.get('to') is None:
                    out.append(f'{q} feeds nothing')
                a = b.get('availability')
                if isinstance(a, dict):
                    if a.get('scheme') not in AVAILABILITY_SCHEMES:
                        out.append(f"{q}: '{a.get('scheme')}' is not an availability scheme")
                    for key in ('limit', 'top', 'bottom'):
                        problem = _equation_problem(a.get(key), system, known)
                        if problem:
                            out.append(f'{q}: its availability {key} {problem}')
            if kind == 'index_reduction':
                if b.get('target') and resolve_reference(str(b['target']), system, known) is None:
                    out.append(f"{q} reduces '{b['target']}', which is not a block")
                if b.get('operation', 'sum') not in OPERATIONS:
                    out.append(f"{q}: '{b.get('operation')}' is not a reduction")
            if kind == 'block_reduction':
                for t in b.get('targets') or []:
                    if resolve_reference(str(t), system, known) is None:
                        out.append(f"{q} combines '{t}', which is not a block")
            if kind == 'lookup':
                if b.get('interpolation', 'linear') not in INTERPOLATIONS:
                    out.append(f"{q}: '{b.get('interpolation')}' is not an interpolation rule")
                pts = b.get('points') or []
                xs = []
                for p in pts:
                    try:
                        xs.append(float(p[0]))
                        float(p[1])
                    except (TypeError, ValueError, IndexError, KeyError):
                        out.append(f'{q}: a point {p!r} is not two numbers')
                        break
                if any(b2 < a2 for a2, b2 in zip(xs, xs[1:])):
                    out.append(f'{q}: its points are not in order of x')
            if kind in TRIGGER_FIELDS:
                for field in TRIGGER_FIELDS[kind]:
                    v = b.get(field)
                    if v:
                        t = resolve_reference(str(v).strip(), system, known)
                        if t is None or model._kind_of(t) != 'trigger':
                            out.append(f"{q}: its {field.replace('_', ' ')} '{v}' is not a trigger")
            if kind == 'min_max' and b.get('operation', 'max') not in EXTREMES:
                out.append(f"{q}: '{b.get('operation')}' is not max or min")
            if kind == 'trigger' and b.get('direction', 'rising') not in DIRECTIONS:
                out.append(f"{q}: '{b.get('direction')}' is not a crossing direction")
            if kind == 'waste_package' and b.get('failure', 'never') not in FAILURES:
                out.append(f"{q}: '{b.get('failure')}' is not a way of failing")
            if kind == 'event':
                if b.get('timing', 'at') not in TIMINGS:
                    out.append(f"{q}: '{b.get('timing')}' is not a timing")
                for a in b.get('actions') or []:
                    for end in ('block', 'from', 'to'):
                        v = a.get(end) if isinstance(a, dict) else None
                        if isinstance(v, str) and v and resolve_reference(v, system, known) is None:
                            out.append(f"{q}: an action names '{v}', which is not a block")
                    problem = _equation_problem((a or {}).get('fraction'), system, known)
                    if problem:
                        out.append(f'{q}: an action\'s share {problem}')

    seen_lists: Set[str] = set()
    for lst in raw.get('index_lists') or []:
        if not isinstance(lst, dict):
            out.append(f'An index list is not a list: {lst!r}')
            continue
        n = lst.get('name')
        if n in seen_lists:
            out.append(f"Two index lists are called '{n}'")
        seen_lists.add(n)
        idx = [index_name(i) for i in lst.get('indices') or []]
        if len(set(idx)) != len(idx):
            out.append(f"Index list '{n}' has an index twice")
        if any(not str(i or '').strip() for i in idx):
            out.append(f"Index list '{n}' has an index with no name")
        if lst.get('sub_set_of'):
            parent = find_list(lists, lst['sub_set_of'])
            if parent is None:
                out.append(f"'{n}' is a sub-set of '{lst['sub_set_of']}', which is not an index list")
            else:
                have = {index_name(i) for i in parent.get('indices') or []}
                stray = [i for i in idx if i not in have]
                if stray:
                    out.append(f"'{n}' is a sub-set of '{parent['name']}' but holds {', '.join(stray)}, which it has not")
        m = lst.get('mapping')
        if isinstance(m, dict):
            parent = find_list(lists, m.get('to'))
            if parent is None:
                out.append(f"'{n}' maps onto '{m.get('to')}', which is not an index list")
            else:
                have = {index_name(i) for i in parent.get('indices') or []}
                for p in m.get('pairs') or []:
                    if p.get('to') not in have or p.get('from') not in idx:
                        out.append(f"'{n}' maps '{p.get('to')}' to '{p.get('from')}', and one of them is not an index")
                        break
    for nuc in model.nuclides:
        if model.half_life(nuc) is None:
            out.append(f"{nuc} has no half-life: ICRP 107 does not know it and the model gives none")
    for pair in raw.get('chains') or []:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            out.append(f'A decay pair is not [parent, daughter, branching]: {pair!r}')

    sim = raw.get('simulation') or {}
    try:
        start = float(sim.get('start_time', 0))
        end = float(sim.get('end_time', 1e5))
        if not end > start:
            out.append('The run ends before it starts (end time not after start time)')
    except (TypeError, ValueError):
        out.append('The start or end time is not a number')
    for key in ('rtol', 'abstol'):
        v = sim.get(key)
        if v is not None:
            try:
                if not float(v) > 0 or math.isinf(float(v)):
                    out.append(f'{key} has to be a number greater than zero')
            except (TypeError, ValueError):
                out.append(f'{key} has to be a number greater than zero')
    if sim.get('solver', 'ndf') not in SOLVERS:
        out.append(f"'{sim.get('solver')}' is not a solver")
    if sim.get('spacing', 'log') not in SPACINGS:
        out.append(f"'{sim.get('spacing')}' is not a way of choosing output times")
    if sim.get('time_unit', 'year') not in TIME_UNITS:
        out.append(f"'{sim.get('time_unit')}' is not a time unit")
    return out


# --- Kompartment's own checks, through Node ------------------------------------------------

def _kompartment_src() -> Path:
    env = os.environ.get('KOMPARTMENT_SRC')
    candidates = [Path(env)] if env else []
    candidates.append(Path(__file__).resolve().parents[2] / 'src')
    for c in candidates:
        if (c / 'domain' / 'project.js').is_file():
            return c
    raise FileNotFoundError(
        "Kompartment's sources were not found: set KOMPARTMENT_SRC to the directory holding "
        "'domain/project.js' (kompartment/src in the kvotab repository)")


def validate_with_node(model: 'Model', *, node: str = 'node', timeout: float = 300) -> List[str]:
    """Kompartment's own validation of a model; see :meth:`Model.validate`."""
    exe = shutil.which(node) or node
    script = Path(__file__).resolve().parent / '_node' / 'validate.mjs'
    proc = subprocess.run([exe, str(script), str(_kompartment_src())], input=model.to_json(0),
                          capture_output=True, text=True, timeout=timeout, encoding='utf-8')
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(f'Node could not run the validator: {proc.stderr.strip()[:2000]}')
    result = json.loads(proc.stdout)
    errors = [e['message'] for e in result.get('errors') or []]
    if errors:
        first = (result['errors'][0] or {}).get('block')
        more = f' (and {len(errors) - 1} more)' if len(errors) > 1 else ''
        raise ValidationError(errors[0] + more, errors, first)
    return [w['message'] if not w.get('name') else f"{w['name']}: {w['message']}"
            for w in result.get('warnings') or []]
