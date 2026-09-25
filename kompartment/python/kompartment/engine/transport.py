"""Transport sub-systems, unrolled into the chain they stand for.

A port of ``src/sim/transport.js`` and the helpers of
``src/domain/transport.js``. A transport is a sub-system drawn as two
compartments -- its Begin and its End -- standing for a chain of N identical
ones. Before anything is laid out, the chain is written out as ordinary
compartments and transfers: the elements in between are copies of Begin
(marked ``hidden``), the transfers between Begin and End are repeated for
every pair, and the expressions those read are copied per pair. A transport
operation (the sum or mean over the chain, or a value at a point along it)
becomes an expression or a call of ``transport_point``/``transport_sum``/
``transport_mean``. The result is a new :class:`Project`, so nothing
downstream has to know a chain from a model.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..equations import EquationSyntaxError, tokenize
from ..names import base_name, parent_of, qualified_name, qualify, reference_from, resolve_reference
from .farfield import FARF_EQUATION_KEYS
from .functions import lookup_function
from .recorders import EQUATION_FIELDS, EVENT_FIELDS, RECORDER_COLLECTION
from .switchtimes import constant_value


class TransportError(ValueError):
    def __init__(self, message: str, block_name: Optional[str] = None) -> None:
        super().__init__(message)
        self.block_name = block_name


EQUATION_KEYS: Dict[str, List[str]] = {
    'compartments': ['initial', 'dydt'],
    'transfers': ['rate'],
    'inflows': ['rate'],
    'expressions': ['equation'],
    'farfields': list(FARF_EQUATION_KEYS),
}
for _kind, _plural in RECORDER_COLLECTION.items():
    EQUATION_KEYS[_plural] = [*EQUATION_FIELDS[_kind], *EVENT_FIELDS[_kind]]

_UNDEFINED = object()


def role_of(block: Dict[str, Any]) -> Optional[str]:
    return block.get('transport') if block else None


def transport_paths(project: Any) -> List[str]:
    lst = project.transports if hasattr(project, 'transports') else (project or {}).get('transports') or []
    out = []
    for p in lst:
        name = p if isinstance(p, str) else (p or {}).get('name')
        if name:
            out.append(name)
    return out


def _blocks(project: Any, key: str) -> List[Dict[str, Any]]:
    return project.blocks.get(key, []) if hasattr(project, 'blocks') else (project or {}).get(key) or []


def transport_parts(project: Any, path: str) -> Dict[str, Any]:
    def own(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [b for b in blocks if (b.get('system') or '') == path]

    def with_role(key: str, role: str) -> List[Dict[str, Any]]:
        return [b for b in own(_blocks(project, key)) if role_of(b) == role]

    begins = with_role('compartments', 'begin')
    ends = with_role('compartments', 'end')
    numbers = with_role('expressions', 'number')
    counters = with_role('expressions', 'counter')
    operations = with_role('expressions', 'operation')
    return {'path': path, 'begin': begins[0] if begins else None, 'begins': begins,
            'end': ends[0] if ends else None, 'ends': ends, 'number': numbers[0] if numbers else None,
            'numbers': numbers, 'counter': counters[0] if counters else None, 'counters': counters,
            'operations': operations}


def internal_transfers(project: Any, parts: Dict[str, Any]) -> List[Dict[str, Any]]:
    b = qualified_name(parts['begin']) if parts['begin'] else None
    e = qualified_name(parts['end']) if parts['end'] else None
    if not b or not e:
        return []
    return [t for t in _blocks(project, 'transfers')
            if (t.get('from') == b and t.get('to') == e) or (t.get('from') == e and t.get('to') == b)]


def transport_number(project: Any, parts: Dict[str, Any]) -> Dict[str, Any]:
    N = parts['number']
    if not N:
        return {'n': None, 'value': None,
                'why': f"'{parts['path']}' has no transport number, so the length of its chain is not known. Add one "
                       '(an expression with the part "number").'}
    name = qualified_name(N)
    value = constant_value(project, N, 'expression')
    if value is None:
        return {'n': None, 'value': None,
                'why': f"'{name}' cannot be worked out before the run starts. The number of compartments in a transport "
                       'may use numbers, parameters and expressions made of those, and nothing that changes over the run.'}
    import math
    n = math.trunc(value)
    if n < 1:
        from ..jsonio import js_number
        return {'n': None, 'value': value,
                'why': f"'{name}' comes to {js_number(value)}, and a transport needs at least one compartment."}
    return {'n': n, 'value': value, 'why': None}


def _plain(block: Dict[str, Any], patch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = {k: v for k, v in block.items() if k not in ('transport', 'qname', 'kind')}
    for key, value in (patch or {}).items():
        if value is _UNDEFINED:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def _rewrite_refs(text: Any, system: str, known: Set[str], replace: Callable[[str], Optional[str]]) -> Any:
    src = str(text if text is not None else '')
    if not src:
        return src
    try:
        tokens = tokenize(src)
    except EquationSyntaxError:
        return src
    out = []
    cursor = 0
    for i, tok in enumerate(tokens):
        if tok.type != 'ident':
            continue
        if i + 1 < len(tokens) and tokens[i + 1].type == 'lparen' and lookup_function(tok.value):
            continue
        q = resolve_reference(tok.value, system, lambda n: n in known)
        if q is None:
            continue
        to = replace(q)
        if to is None or to == tok.value:
            continue
        out.append(src[cursor:tok.pos] + to)
        cursor = tok.pos + len(tok.text)
    return ''.join(out) + src[cursor:]


def _rewrite_calls(text: Any, system: str, target: str, fn_name: str, elements: List[str], arity: int,
                   known: Set[str], owner: str) -> Any:
    src = str(text if text is not None else '')
    if not src or base_name(target) not in src:
        return src
    try:
        tokens = tokenize(src)
    except EquationSyntaxError:
        return src
    out = []
    cursor = 0
    for i, tok in enumerate(tokens):
        if tok.type != 'ident' or i + 1 >= len(tokens) or tokens[i + 1].type != 'lparen':
            continue
        if lookup_function(tok.value):
            continue
        q = resolve_reference(tok.value, system, lambda n: n in known)
        if q != target:
            continue
        depth = 0
        commas = 0
        empty = True
        for j in range(i + 1, len(tokens)):
            t = tokens[j]
            if t.type == 'lparen':
                depth += 1
            elif t.type == 'rparen':
                depth -= 1
                if depth == 0:
                    break
            elif t.type == 'comma' and depth == 1:
                commas += 1
            if depth == 1 and j > i + 1:
                empty = False
        given = 0 if empty else commas + 1
        if given != arity:
            wants = ('one position along the chain, between 0 and 1' if arity == 1
                     else 'two positions along the chain, each between 0 and 1')
            was = ' was' if given == 1 else 's were'
            raise TransportError(f"'{tok.value}' is a transport operation that takes {wants}; {given} argument{was} "
                                 'given.', owner)
        spelled = [reference_from(e, system, lambda n: n in known) for e in elements]
        opening = tokens[i + 1]
        out.append(src[cursor:tok.pos] + f"{fn_name}({', '.join(spelled)}, ")
        cursor = opening.pos + 1
    return ''.join(out) + src[cursor:]


def expand_transports(project: Any) -> Any:
    """The project with every transport written out as its chain."""
    from .project import Project
    paths = [p for p in transport_paths(project) if p in project.systems]
    if not paths:
        return project
    raw = dict(project.to_json())
    for key in ('compartments', 'expressions', 'transfers', 'inflows'):
        raw[key] = list(raw.get(key) or [])
    raw.pop('transports', None)
    known: Set[str] = set()
    for key in list(EQUATION_KEYS) + ['parameters', 'lookups', 'index_reductions', 'block_reductions']:
        for b in raw.get(key) or []:
            known.add(qualified_name(b))
    taken = set(known)
    off: Set[str] = set()
    for path in paths:
        _expand_one(project, raw, path, known, taken, off)
    derived = Project(copy.deepcopy(raw))
    derived.disabled = set(project.disabled) | set(derived.disabled) | off
    derived.implicitly_disabled = {**project.implicitly_disabled, **derived.implicitly_disabled}
    return derived


def _expand_one(project: Any, raw: Dict[str, Any], path: str, known: Set[str], taken: Set[str],
                off: Set[str]) -> None:
    parts = transport_parts(project, path)
    switched_off = any(parent_of(n) == path for n in project.disabled)
    if (not parts['begins'] or not parts['ends']) and switched_off:
        going = {b['qname'] for b in [*parts['begins'], *parts['ends'], *parts['numbers'], *parts['counters'],
                                      *parts['operations']]}
        raw['compartments'] = [b for b in raw['compartments'] if qualified_name(b) not in going]
        raw['expressions'] = [b for b in raw['expressions'] if qualified_name(b) not in going]
        off.update(going)
        return
    if len(parts['begins']) != 1 or len(parts['ends']) != 1:
        def count(lst: List[Any], what: str) -> str:
            n = len(lst)
            return f"{n or 'no'} {what}{'' if n == 1 else ('s' if n else '')}"
        what = []
        if len(parts['begins']) != 1:
            what.append(count(parts['begins'], 'Begin compartment'))
        if len(parts['ends']) != 1:
            what.append(count(parts['ends'], 'End compartment'))
        raise TransportError(f"'{path}' is a transport with {' and '.join(what)}. A transport is a chain from one Begin "
                             'to one End.', path)
    B, E = parts['begin'], parts['end']
    bq, eq = B['qname'], E['qname']

    def dims_of(b: Dict[str, Any]) -> str:
        return ' '.join(sorted(b.get('index_lists') or []))

    if dims_of(B) != dims_of(E):
        raise TransportError(f"'{eq}' is not indexed by the same lists as '{bq}'. Every compartment of the chain is one "
                             'compartment repeated, so Begin and End must match.', eq)
    number = transport_number(project, parts)
    if number['why']:
        raise TransportError(number['why'], parts['number']['qname'] if parts['number'] else path)
    n = number['n']
    C = parts['counter']
    cq = C['qname'] if C else None
    internal = internal_transfers(project, parts)
    internal_names = {t['qname'] for t in internal}
    dependent: List[Dict[str, Any]] = []
    dependent_names: Set[str] = set()

    def pair_names() -> Set[str]:
        return {bq, eq, *([cq] if cq else []), *internal_names, *dependent_names}

    def refs_any(block: Dict[str, Any], keys: List[str], names: Set[str]) -> bool:
        texts = []
        for key in keys:
            if isinstance(block.get(key), str):
                texts.append(block[key])
            for e in block.get('entries') or []:
                if isinstance(e.get(key), str):
                    texts.append(e[key])
        for text in texts:
            found = [False]

            def note(q: str) -> None:
                if q in names:
                    found[0] = True
                return None

            _rewrite_refs(text, path, known, note)
            if found[0]:
                return True
        return False

    grew = True
    while grew:
        grew = False
        names = pair_names()
        for x in project.blocks['expressions']:
            if (x.get('system') or '') != path or role_of(x) or x['qname'] in dependent_names:
                continue
            if refs_any(x, ['equation'], names):
                dependent.append(x)
                dependent_names.add(x['qname'])
                grew = True
    if cq:
        only = {cq}
        outside = None
        for blocks, keys in ((project.blocks['expressions'], ['equation']), (project.blocks['transfers'], ['rate']),
                             (project.blocks['inflows'], ['rate']),
                             (project.blocks['compartments'], ['initial', 'dydt'])):
            for b in blocks:
                if (b.get('system') or '') != path and refs_any(b, keys, only):
                    outside = b
                    break
            if outside:
                break
        if outside:
            raise TransportError(f"'{outside['qname']}' reads '{cq}', the element counter of '{path}', from outside the "
                                 'transport. The counter counts the compartments of the chain and has a value only '
                                 'inside it.', outside['qname'])

    def fresh(base: str) -> str:
        name = base
        i = 1
        while qualify(path, name) in taken:
            name = f'{base}_{i}'
            i += 1
        taken.add(qualify(path, name))
        return name

    elem_local: List[Optional[str]] = [None] * (n + 1)
    elem_local[1] = B['name']
    if n > 1:
        elem_local[n] = E['name']
    for e in range(2, n):
        elem_local[e] = fresh(f"{B['name']}_{e}")

    def elem_q(e: int) -> str:
        return qualify(path, elem_local[e])  # type: ignore[arg-type]

    elements = [elem_q(e) for e in range(1, n + 1)]
    copy_name: Dict[str, str] = {}
    for e in range(1, n):
        for x in dependent:
            copy_name[f"{x['qname']} {e}"] = fresh(f"{x['name']}_{e}")
        for t in internal:
            copy_name[f"{t['qname']} {e}"] = t['name'] if e == 1 else fresh(f"{t['name']}_{e}")

    def replace_for(e: int) -> Callable[[str], Optional[str]]:
        def replace(q: str) -> Optional[str]:
            if q == bq:
                return elem_local[e]
            if q == eq:
                return elem_local[e + 1]
            if q == cq:
                return str(e)
            return copy_name.get(f'{q} {e}')
        return replace

    def rewrite(text: Any, e: int) -> Any:
        return _rewrite_refs(text, path, known, replace_for(e))

    def rewrite_entries(entries: Any, key: str, e: int) -> List[Dict[str, Any]]:
        return [({**en, key: rewrite(en[key], e)} if isinstance(en.get(key), str) else dict(en))
                for en in entries or []]

    def rewrite_initial(text: Any, e: int) -> Any:
        return _rewrite_refs(text, path, known, lambda q: str(e) if q == cq else None)

    def without(lst: List[Dict[str, Any]], names: Set[str]) -> List[Dict[str, Any]]:
        return [b for b in lst if qualified_name(b) not in names]

    if n == 1:
        raw['compartments'] = without(raw['compartments'], {eq})
        raw['expressions'].append(_plain(E, {
            'equation': B['name'], 'unit': E.get('unit') or B.get('unit'),
            'index_lists': list(B.get('index_lists') or []), 'entries': [], 'initial': _UNDEFINED,
            'abstol': _UNDEFINED, 'non_negative': _UNDEFINED, 'handle_decay': _UNDEFINED, 'dydt': _UNDEFINED,
        }))

        def rewire(conn: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            if qualified_name(conn) in internal_names:
                return None
            if conn.get('from') != eq and conn.get('to') != eq:
                return conn
            return {**conn, 'from': bq if conn.get('from') == eq else conn.get('from'),
                    'to': bq if conn.get('to') == eq else conn.get('to')}

        raw['transfers'] = [c for c in (rewire(c) for c in raw['transfers']) if c]
        raw['inflows'] = [c for c in (rewire(c) for c in raw['inflows']) if c]
    else:
        for e in range(2, n):
            raw['compartments'].append(_plain(B, {
                'name': elem_local[e], 'system': path, 'hidden': True, 'alias': {'compartment': bq},
                'initial': rewrite_initial(B.get('initial'), e),
                'dydt': rewrite(B['dydt'], e) if isinstance(B.get('dydt'), str) else _UNDEFINED,
                'entries': rewrite_entries(rewrite_entries(B.get('entries'), 'initial', e), 'dydt', e),
                'color': _UNDEFINED, 'symbol': _UNDEFINED, 'comment': '',
            }))

        def end_block(c: Dict[str, Any]) -> Dict[str, Any]:
            if qualified_name(c) != eq:
                return c
            initial_entries = []
            for en in rewrite_entries(B.get('entries'), 'initial', n):
                rest = {k: v for k, v in en.items() if k != 'dydt'}
                if any(k != 'index' for k in rest):
                    initial_entries.append(rest)
            dydt_entries = [{'index': en.get('index'), 'dydt': rewrite(en['dydt'], n)}
                            for en in E.get('entries') or [] if isinstance(en.get('dydt'), str)]
            return _plain(B, {
                'name': E['name'], 'system': path, 'unit': E.get('unit') or B.get('unit'),
                'comment': E.get('comment'), 'color': E.get('color'), 'symbol': E.get('symbol'),
                'initial': rewrite_initial(B.get('initial'), n),
                'dydt': rewrite(E['dydt'], n) if isinstance(E.get('dydt'), str) else _UNDEFINED,
                'entries': [*initial_entries, *dydt_entries],
            })

        raw['compartments'] = [end_block(c) for c in raw['compartments']]
        raw['transfers'] = without(raw['transfers'], internal_names)
        for e in range(1, n):
            for x in dependent:
                raw['expressions'].append(_plain(x, {
                    'name': copy_name[f"{x['qname']} {e}"], 'system': path, 'hidden': True,
                    'equation': rewrite(x.get('equation'), e), 'entries': rewrite_entries(x.get('entries'), 'equation', e),
                    'color': _UNDEFINED, 'symbol': _UNDEFINED, 'comment': '',
                }))
            for t in internal:
                forward = t.get('from') == bq
                patch: Dict[str, Any] = {
                    'name': copy_name[f"{t['qname']} {e}"], 'system': path,
                    'alias': {'transfer': t['qname'], 'from': t.get('from'), 'to': t.get('to')},
                    'from': elem_q(e) if forward else elem_q(e + 1),
                    'to': elem_q(e + 1) if forward else elem_q(e),
                    'rate': rewrite(t.get('rate'), e), 'entries': rewrite_entries(t.get('entries'), 'rate', e),
                }
                if e != 1:
                    patch.update(hidden=True, color=_UNDEFINED, comment='')
                raw['transfers'].append(_plain(t, patch))
    if n == 1:
        for t in internal:
            entries = []
            for en in t.get('entries') or []:
                rest = {k: v for k, v in en.items() if k != 'rate'}
                entries.append({**rest, 'equation': en['rate']} if isinstance(en.get('rate'), str) else rest)
            raw['expressions'].append(_plain(t, {
                'equation': t.get('rate'), 'entries': entries, 'from': _UNDEFINED, 'to': _UNDEFINED,
                'multiply_by_donor': _UNDEFINED, 'index_lists': list(B.get('index_lists') or []),
            }))
    if C:
        raw['expressions'] = [x if qualified_name(x) != cq else _plain(C, {'equation': '1', 'hidden': True})
                              for x in raw['expressions']]
    number_q = parts['number']['qname']
    raw['expressions'] = [x if qualified_name(x) != number_q else _plain(x) for x in raw['expressions']]
    locals_ = [base_name(q) for q in elements]
    for op in parts['operations']:
        oq = op['qname']
        mean = (op.get('operation') or 'mean') == 'mean'
        if (op.get('argument') or 'all') == 'all':
            total = locals_[0] if len(locals_) == 1 else ' + '.join(locals_)
            raw['expressions'] = [x if qualified_name(x) != oq else _plain(op, {
                'equation': f'({total}) / {n}' if mean else total,
                'index_lists': list(B.get('index_lists') or []), 'unit': op.get('unit') or B.get('unit'),
                'entries': [], 'operation': _UNDEFINED, 'argument': _UNDEFINED,
            }) for x in raw['expressions']]
            continue
        raw['expressions'] = without(raw['expressions'], {oq})
        point = op.get('argument') == 'point'
        fn_name = 'transport_point' if point else ('transport_mean' if mean else 'transport_sum')
        arity = 1 if point else 2
        for collection, keys in EQUATION_KEYS.items():
            new_list = []
            for b in raw.get(collection) or []:
                system = b.get('system') or ''
                owner = qualified_name(b)
                changed: Optional[Dict[str, Any]] = None
                for key in keys:
                    if isinstance(b.get(key), str):
                        nxt = _rewrite_calls(b[key], system, oq, fn_name, elements, arity, taken, owner)
                        if nxt != b[key]:
                            changed = changed or dict(b)
                            changed[key] = nxt
                    for i, en in enumerate(b.get('entries') or []):
                        if not isinstance(en.get(key), str):
                            continue
                        nxt = _rewrite_calls(en[key], system, oq, fn_name, elements, arity, taken, owner)
                        if nxt == en[key]:
                            continue
                        changed = changed or dict(b)
                        if changed.get('entries') is b.get('entries'):
                            changed['entries'] = [dict(x) for x in b.get('entries') or []]
                        changed['entries'][i][key] = nxt
                new_list.append(changed or b)
            if collection in raw or new_list:
                raw[collection] = new_list
