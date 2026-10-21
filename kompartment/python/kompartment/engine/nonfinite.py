"""Where a value that is not a number came from: a port of ``src/sim/nonfinite.js``.

A run that stops on a NaN or an infinity used to say when and nothing else.
The state the solver held is known, so the equations are worked out once more
there and a value that is not a number is followed back the way it came: from
the compartments whose derivative it reached, through the transfers that
carried it, and down through each equation a part at a time to the one
operation that made it out of numbers -- zero divided by zero, the log of a
negative, an overflow -- and the values that operation read.

It is followed by value, not by name: a block that is not a number at one
index is followed only where it is read at that one, and a conditional down
the branch it took. A part of an equation is resolved by the builder's own
resolvers at the element's tuple and evaluated with the code generator's own
arithmetic (``apply_binary``, ``call_value``), so what this says went wrong is
what did. :func:`start_warnings` says the same before a run, from the values
at the start.

The words are the application's, letter for letter: a message from this
engine reads as the application's does.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import codegen
from .builder import describe_tuple, tuple_by_list
from .codegen import INLINE_NUMPY, apply_binary, call_value, js_pow
from .solvers.julia._js import js_string, to_exponential

#: How deep one value is followed: an equation that reads another, which reads another, ...
MOST_STEPS = 500
#: How many elements are followed back before the rest are only counted.
MOST_FOLLOWED = 2000
#: How many names a list in the message carries before it says how many more.
MOST_NAMED = 3
#: How many of the values an operation read are written out.
MOST_READS = 6
#: The longest a part of an equation is quoted at; longer, its middle is left out.
LONGEST_PART = 240
#: The shortest step the clock tells apart at ``t``, which the probes past it start from.
EPS = 2.0 ** -52

_ARRAY_OF = {'state': 'y', 'param': 'P', 'alg': 'X'}
_ASSEMBLY_PREFIX = re.compile(r'^(waste_package|event|farfield):')
_NON_NUMBERS = re.compile(r'not a number|non-finite|not-a-number|infinite|\bNaN\b', re.IGNORECASE)


def _finite(v: Any) -> bool:
    return v is not None and math.isfinite(v)


def _read_by_assembly(a: Any) -> bool:
    """The algebraic slots the assembly of the derivative reads (``readByDerivative``)."""
    kind = a.kind
    return (kind in ('transfer', 'inflow', 'compartment:dydt', 'waste_package', 'farfield', 'running_mean:target')
            or bool(_ASSEMBLY_PREFIX.match(kind)))


def _block_of(name: str) -> str:
    """A slot of a block's own -- ``T#limit``, ``M#target`` -- answers as the block."""
    return str(name).split('#')[0]


# --- one element of an equation, taken apart -------------------------------------------------

class _Equation:
    """``equationAt`` of the application: one element of an algebraic slot's
    equation, its tree, where each reference reads, and what any part of it
    comes to at ``(t, y)``. Reads ``X`` as the last evaluation left it."""

    def __init__(self, system: Any, a: Any, off: int) -> None:
        b = system.builder
        self.system = system
        self.ast = a.asts[0 if a.uniform else off]
        tup = tuple_by_list(b.space, a.dims, off) if a.dims else {}
        self._ref = b.resolver(a, a.dims, None, tup, 1)
        self._call = b.call_resolver(a, a.dims, None, tup)
        self._locate: Callable[[Any], Tuple[str, Any, Any]] = \
            lambda node: b.locate(a, a.dims, None, tup, node.name, node.indices, node)
        self._values: Dict[int, Optional[float]] = {}

    def read(self, node: Any) -> Dict[str, Any]:
        kind, _, index = self._locate(node)
        return {'array': _ARRAY_OF.get(kind), 'offset': int(index)}

    def value_of(self, node: Any, t: float, y: np.ndarray) -> Optional[float]:
        key = id(node)
        if key not in self._values:
            try:
                tree = codegen.resolve(node, self._ref, self._call)
                with np.errstate(all='ignore'):
                    self._values[key] = float(_tree_value(tree, t, y, self.system))
            except Exception:  # noqa: BLE001 - a part that will not evaluate is one not followed
                self._values[key] = None
        return self._values[key]


def _tree_value(tree: Any, t: float, y: np.ndarray, system: Any) -> Any:
    """A resolved tree's value for one element, with the code generator's arithmetic."""
    k = tree[0]
    if k == 'leaf':
        leaf = tree[1]
        kind = leaf.kind
        if kind == 'y':
            return np.float64(y[int(leaf.index)])
        if kind == 'P':
            return np.float64(system.P[int(leaf.index)])
        if kind == 'X':
            return np.float64(system.X[int(leaf.index)])
        if kind == 'K':
            return np.float64(leaf.index)
        if kind == 'T':
            return np.float64(t)
        if kind == 'T0':
            return np.float64(system.start_time)
        if kind == 'T1':
            return np.float64(system.end_time)
        if kind == 'DIS':
            return np.float64(system.DIS[int(leaf.index)])
        raise ValueError(f'A {kind} leaf is not a value')
    if k == 'neg':
        return -_tree_value(tree[1], t, y, system)
    if k == 'bin':
        return apply_binary(tree[1], _tree_value(tree[2], t, y, system), _tree_value(tree[3], t, y, system))
    if k == 'cond':
        test = _tree_value(tree[1], t, y, system)
        return _tree_value(tree[2] if test != 0 else tree[3], t, y, system)
    if k == 'call':
        key = tree[1]
        args = [_tree_value(a, t, y, system) for a in tree[2]]
        if key in INLINE_NUMPY:
            return getattr(np, INLINE_NUMPY[key][3:])(*args)
        if key == 'power':
            return js_pow(args[0], args[1])
        return call_value(key, args)
    if k == 'tab':
        return np.float64(system.TAB[int(tree[1].index)].at(_tree_value(tree[2], t, y, system)))
    raise ValueError(k)


def _equation_at(system: Any, k: int, off: int) -> Optional[_Equation]:
    a = system.layout.algebraic[k]
    if not a.get('asts'):
        return None
    return _Equation(system, a, off)


# --- following a value back -----------------------------------------------------------------

class _At:
    """The equations worked out at ``(t, y)``, and a way to follow a value that
    is not a number back through them."""

    def __init__(self, system: Any, t: float, state: np.ndarray, d: np.ndarray, X: np.ndarray) -> None:
        L = system.layout
        self.system, self.L, self.t, self.state, self.d, self.X = system, L, t, state, d, X
        self.algebraic = L.algebraic
        owner = np.full(max(1, L.nalg), -1, dtype=np.int64)
        for k, a in enumerate(self.algebraic):
            if a.width > 0:
                owner[a.base:a.base + a.width] = k
        self.owner = owner
        self._memo: Dict[Tuple[int, int], Optional[Dict[str, Any]]] = {}

    def at(self, offset: int) -> Optional[Tuple[int, int]]:
        k = int(self.owner[offset]) if 0 <= offset < self.owner.size else -1
        return None if k < 0 else (k, offset - self.algebraic[k].base)

    def root_of(self, k: int, off: int, depth: int = 0) -> Dict[str, Any]:
        key = (k, off)
        if key in self._memo:
            return self._memo[key] or {'k': k, 'off': off}
        self._memo[key] = None
        found = self._follow(k, off, depth)
        self._memo[key] = found
        return found

    def _follow(self, k: int, off: int, depth: int) -> Dict[str, Any]:
        here = {'k': k, 'off': off}
        if depth > MOST_STEPS:
            return here
        a = self.algebraic[k]
        X = self.X
        # A block that remembers has no equation; what it is not a number of,
        # if anything now, is its target.
        rec = a.get('recorder')
        target = rec.aux.get('target') if rec is not None and isinstance(getattr(rec, 'aux', None), dict) else None
        if target is not None and rec.kind != 'trigger':
            nxt = self.at(target.base + off) if not _finite(X[target.base + off]) else None
            return self.root_of(nxt[0], nxt[1], depth + 1) if nxt else here
        try:
            eq = _equation_at(self.system, k, off)
        except Exception:  # noqa: BLE001
            eq = None
        if eq is None:
            return here
        part = _innermost(eq, self.t, self.state)
        if part is None:
            # The equation comes to a number and the slot does not: the slot
            # is the rate times an availability, and it is that.
            avail = a.get('availability')
            for op in (avail.operands.values() if avail is not None else ()):
                nxt = self.at(op.base + off) if not _finite(X[op.base + off]) else None
                if nxt:
                    return self.root_of(nxt[0], nxt[1], depth + 1)
            return here
        if part['node'].type == 'ref':
            try:
                read = eq.read(part['node'])
            except Exception:  # noqa: BLE001
                read = None
            nxt = self.at(read['offset']) if read is not None and read['array'] == 'X' else None
            if nxt:
                return self.root_of(nxt[0], nxt[1], depth + 1)
            return {**here, 'eq': eq, 'part': part, 'read': read}
        return {**here, 'eq': eq, 'part': part}


def _evaluated(system: Any, t: float, y: Any) -> Optional[_At]:
    L = getattr(system, 'layout', None)
    if L is None or getattr(system, 'builder', None) is None:
        return None
    n = L.nstate
    y = np.asarray(y, dtype=float)
    if y.size < n:
        return None
    state = y[:n].copy()
    try:
        d = np.array(system.dydt(t, state), dtype=float)
        # Every slot, not only those the derivative runs: a block the
        # derivative reads is in both, and its value is the same in either.
        X = system.evaluate_algebraic(t, state)
    except Exception:  # noqa: BLE001 - a system that will not evaluate says nothing more
        return None
    return _At(system, t, state, d, X)


def _innermost(eq: _Equation, t: float, y: np.ndarray) -> Optional[Dict[str, Any]]:
    """The node of an equation that is not a number while every operand it was
    worked out from is one -- the operation that made it -- and its operands."""
    def value(node: Any) -> Optional[float]:
        return eq.value_of(node, t, y)
    node = eq.ast
    v = value(node)
    if v is None or math.isfinite(v):
        return None
    while True:
        parts = _operands(node, value)
        nxt = next((p for p in parts if p['value'] is not None and not math.isfinite(p['value'])), None)
        if nxt is None:
            return {'node': node, 'value': v, 'operands': parts}
        node, v = nxt['node'], nxt['value']


def _operands(node: Any, value: Callable[[Any], Optional[float]]) -> List[Dict[str, Any]]:
    """The operands a node was worked out from, with their values: only the branch a conditional took."""
    def of(n: Any) -> Dict[str, Any]:
        return {'node': n, 'value': value(n)}
    t = node.type
    if t == 'unary':
        return [of(node.operand)]
    if t == 'binary':
        return [of(node.left), of(node.right)]
    if t == 'cond':
        test = of(node.test)
        if test['value'] is None:
            return [test]
        return [test, of(node.then if test['value'] != 0 else node.otherwise)]
    if t == 'call':
        args = list(node.args or [])
        if node.name == 'if' and len(args) >= 2:
            test = of(args[0])
            if test['value'] is None:
                return [test]
            taken = args[1] if test['value'] != 0 else (args[2] if len(args) > 2 else None)
            return [test, of(taken)] if taken is not None else [test]
        return [of(a) for a in args]
    return []


def _from_assembly(at: _At) -> Dict[str, Any]:
    """The blocks behind the values that are not numbers which the assembly of
    the derivative reads, the flows that carry them, and which flows each reach."""
    flows_seen: Dict[str, Dict[str, Any]] = {}
    flows_of: Dict[int, List[str]] = {}
    roots: List[Dict[str, Any]] = []
    followed = 0
    X = at.X
    for k, a in enumerate(at.algebraic):
        if not _read_by_assembly(a):
            continue
        flow = _block_of(a.name) if a.kind in ('transfer', 'inflow') else None
        for off in range(a.width):
            if math.isfinite(X[a.base + off]):
                continue
            if flow is not None:
                seen = flows_seen.setdefault(flow, {'name': flow, 'kind': a.kind, 'count': 0})
                seen['count'] += 1
            followed += 1
            if followed > MOST_FOLLOWED:
                continue
            r = at.root_of(k, off)
            roots.append(r)
            if flow is not None and a.kind == 'transfer':
                via = flows_of.setdefault(r['k'], [])
                if flow not in via:
                    via.append(flow)
    return {'flows': list(flows_seen.values()), 'blocks': _by_root_block(roots), 'flows_of': flows_of}


def _from_the_rest(at: _At, stopping: set) -> List[Dict[str, Any]]:
    """The blocks behind the values that are not numbers which only results read."""
    roots: List[Dict[str, Any]] = []
    followed = 0
    X = at.X
    for k, a in enumerate(at.algebraic):
        # The slots behind a block -- a recorder's target, an availability --
        # answer for it: the block's own slot is the one to follow.
        if a.get('hidden') or _read_by_assembly(a):
            continue
        stop = False
        for off in range(a.width):
            if math.isfinite(X[a.base + off]):
                continue
            followed += 1
            if followed > MOST_FOLLOWED:
                stop = True
                break
            r = at.root_of(k, off)
            if r['k'] not in stopping:
                roots.append(r)
        if stop:
            break
    return _by_root_block(roots)


def _by_root_block(roots: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One root per block, at its first element, with which elements it has, in the order of the blocks."""
    by_block: Dict[int, Dict[str, Any]] = {}
    for r in roots:
        had = by_block.get(r['k'])
        if had is None:
            by_block[r['k']] = {'first': r, 'offs': {r['off']}}
        else:
            had['offs'].add(r['off'])
            if r['off'] < had['first']['off']:
                had['first'] = r
    return [by_block[k] for k in sorted(by_block)]


def _group_by(entries: Sequence[Any], n: int, bad: Callable[[int], bool]) -> List[Dict[str, Any]]:
    """The run's states that are not numbers, a block at a time, in the order of the state vector."""
    out = []
    for s in entries or []:
        count = 0
        first = -1
        for i in range(s.width):
            at = s.base + i
            if at >= n or not bad(at):
                continue
            if first < 0:
                first = i
            count += 1
        if count:
            out.append({'name': _block_of(s.name), 'kind': s.get('kind') or 'compartment', 'count': count,
                        'first': first, 'at': s.base + first, 'dims': list(s.dims or [])})
    return out


def _entry_at(entries: Sequence[Any], offset: int) -> Any:
    for e in entries or []:
        if e.base <= offset < e.base + e.width:
            return e
    return None


def _describe_root(block: Dict[str, Any], at: _At) -> Dict[str, Any]:
    first, offs = block['first'], block['offs']
    L = at.L
    a = L.algebraic[first['k']]
    space = L.index_space
    index = tuple_by_list(space, a.dims, first['off']) if a.dims else None
    root: Dict[str, Any] = {'name': _block_of(a.name), 'kind': a.kind, 'index': index, 'count': len(offs),
                            'value': float(at.X[a.base + first['off']]), 'part': None, 'source': None}
    part = first.get('part')
    if part is None:
        return root
    read = first.get('read')
    if part['node'].type == 'ref' and read is not None:
        # A state or a parameter that is not a number: what the equation read.
        holder = (_entry_at(L.states, read['offset']) if read['array'] == 'y'
                  else _entry_at(L.parameters, read['offset']) if read['array'] == 'P' else None)
        if holder is not None:
            off = read['offset'] - holder.base
            root['source'] = {
                'name': _block_of(holder.name),
                'kind': (holder.get('kind') or 'compartment') if read['array'] == 'y' else 'parameter',
                'index': tuple_by_list(space, holder.dims, off) if holder.dims else None,
                'value': part['value'],
            }
            return root
    eq = first['eq']
    root['part'] = {
        'text': equation_text(part['node']),
        'worked': _worked_text(part['node'], part['operands'], part['value']),
        'reads': _reads_of(part['node'], eq, at.t, at.state),
    }
    return root


def _reads_of(node: Any, eq: _Equation, t: float, y: np.ndarray) -> List[Dict[str, Any]]:
    """The references inside a part, each once, with the value it read."""
    out: Dict[str, Optional[float]] = {}

    def walk(n: Any) -> None:
        if n.type == 'ref':
            text = equation_text(n)
            if text not in out:
                out[text] = eq.value_of(n, t, y)
            return
        for c in _children(n):
            walk(c)
    walk(node)
    return [{'text': text, 'value': value} for text, value in out.items()]


def _children(n: Any) -> List[Any]:
    t = n.type
    if t == 'unary':
        return [n.operand]
    if t == 'binary':
        return [n.left, n.right]
    if t == 'cond':
        return [n.test, n.then, n.otherwise]
    if t == 'call':
        return list(n.args or [])
    return []


# --- what is found ---------------------------------------------------------------------------

def non_finite_at(system: Any, t: float, y: Any) -> Optional[Dict[str, Any]]:
    """Where the derivative at ``(t, y)`` stops being a number, and why
    (``nonFiniteAt``). None when it is a number throughout, or the system
    cannot be taken apart."""
    at = _evaluated(system, t, y)
    if at is None:
        return None
    states = _group_by(at.L.states, at.L.nstate, lambda i: not math.isfinite(at.d[i]) or
                       not math.isfinite(at.state[i]))
    if not states:
        return None
    found = _from_assembly(at)
    roots = [_describe_root(b, at) for b in found['blocks']]
    root = roots[0] if roots else None
    others: List[str] = []
    for r in roots[1:]:
        if r['name'] not in others and r['name'] != (root or {}).get('name'):
            others.append(r['name'])
    return {'t': t, 'states': states, 'state_count': sum(g['count'] for g in states), 'flows': found['flows'],
            'root': root, 'others': others}


def start_warnings(system: Any, t0: float, y0: Any) -> List[Dict[str, Any]]:
    """What a run would trip over, said before one is run (``startWarnings``):
    every block whose value at the start is not a number of its own making,
    ``{'block', 'message', 'stops'}`` each, in the order the equations are
    worked out. The ones the run reads stop it at its first step; the ones only
    a result reads let it go on; a compartment whose initial value is not a
    number stops it before that."""
    L = getattr(system, 'layout', None)
    if L is None:
        return []
    y0 = np.asarray(y0, dtype=float)
    out: List[Dict[str, Any]] = []
    for g in _group_by(L.states, L.nstate, lambda i: not math.isfinite(y0[i])):
        if g['kind'] != 'compartment':
            continue
        out.append({'block': g['name'], 'stops': True,
                    'message': f"Its initial value comes to {number(y0[g['at']])}{_where_text(g, L)}, so a run "
                               'cannot start.'})
    if out:
        return out
    at = _evaluated(system, t0, y0)
    if at is None:
        return out
    found = _from_assembly(at)
    stopping = {b['first']['k'] for b in found['blocks']}
    for b in found['blocks']:
        r = _describe_root(b, at)
        via = found['flows_of'].get(b['first']['k'], [])
        through = f", through {'the transfer' if len(via) == 1 else 'the transfers'} {_list(via)}," if via else ''
        out.append({'block': r['name'], 'stops': True,
                    'message': f'{_root_sentence(r, True)} The run reads it{through} so it will stop at its first '
                               'step.'})
    for b in _from_the_rest(at, stopping):
        r = _describe_root(b, at)
        what = 'these values' if r['count'] > 1 else 'this value'
        out.append({'block': r['name'], 'stops': False,
                    'message': f'{_root_sentence(r, True)} Only results read it, so a run goes on, with {what} at '
                               'its first point.'})
    return out


# --- the words -------------------------------------------------------------------------------

def non_finite_message(found: Dict[str, Any], layout: Any, step: Optional[Dict[str, float]] = None) -> str:
    """The message for a run that stopped on a value that is not a number."""
    if step is not None:
        lines = [f"The simulation produced a value that is not a number at t={js_string(step['from'])}.",
                 f"The state it held there gives numbers; a step of {number(step['h'])} past it does not."]
    else:
        lines = [f"The simulation produced a value that is not a number at t={js_string(found['t'])}."]
    if found['root'] is not None:
        lines.append(_root_sentence(found['root'], False))
    lines.append(_reach_text(found, layout))
    others = found['others']
    if others:
        first, rest = others[0], others[1:]
        lines.append(f"{first} and {len(rest)} more {'block' if len(rest) == 1 else 'blocks'} start one of their own "
                     'as well.' if rest else f'{first} starts one of its own as well.')
    return ' '.join(lines)


def _root_sentence(r: Dict[str, Any], at_start: bool) -> str:
    more = r['count'] - 1
    others = f" (and {more} more of its indices)" if more else ''
    if at_start:
        lead = (f"Comes to {number(r['value'])} at the start"
                f"{' at ' + describe_tuple(r['index']) if r['index'] else ''}{others}")
    else:
        lead = f"It starts in {r['name']}{_index_text(r['index'])}{others}"
    s = r['source']
    if s is not None:
        if s['kind'] == 'parameter':
            what = f"the parameter {s['name']}{_index_text(s['index'])}, which is"
        elif s['kind'] == 'compartment':
            what = f"the compartment {s['name']}{_index_text(s['index'])}, which holds"
        else:
            what = f"the state {s['name']}{_index_text(s['index'])}, which is"
        if at_start:
            return f"{lead}: it reads {what} {number(s['value'])}."
        return f"It starts in {what} {number(s['value'])}, read by {r['name']}{_index_text(r['index'])}{others}."
    p = r['part']
    if p is not None:
        return f"{lead}: {p['text']} comes to {p['worked']}{_reads_text(p['reads'])}."
    return f'{lead}.' if at_start else f"{lead}, which comes to {number(r['value'])}."


def _reach_text(found: Dict[str, Any], layout: Any) -> str:
    states, state_count, flows = found['states'], found['state_count'], found['flows']
    named = []
    for s in states:
        index = ''
        if len(states) == 1 and s['count'] == 1 and s['dims']:
            index = _index_text(tuple_by_list(layout.index_space, s['dims'], s['first']))
        named.append(f"{s['name']}{index}")
    noun = 'compartment' if all(s['kind'] == 'compartment' for s in states) else 'block'
    if len(states) == 1:
        text = f"It reaches the {noun} {named[0]}{f' ({state_count} states)' if state_count > 1 else ''}"
    else:
        text = f'It reaches {len(states)} {noun}s, {state_count} states in all: {_list(named)}'
    if flows:
        transfers = [f['name'] for f in flows if f['kind'] == 'transfer']
        inflows = [f['name'] for f in flows if f['kind'] == 'inflow']
        parts = []
        if transfers:
            parts.append(f"{'the transfer' if len(transfers) == 1 else 'the transfers'} {_list(transfers)}")
        if inflows:
            parts.append(f"{'the inflow' if len(inflows) == 1 else 'the inflows'} {_list(inflows)}")
        text += f", through {' and '.join(parts)}"
    return f'{text}.'


def _list(names: Sequence[str]) -> str:
    """Up to three names, then how many more."""
    names = list(names)
    if len(names) <= MOST_NAMED:
        return ''.join(names) if len(names) < 2 else f"{', '.join(names[:-1])} and {names[-1]}"
    return f"{', '.join(names[:MOST_NAMED])} and {len(names) - MOST_NAMED} more"


def _reads_text(reads: Sequence[Dict[str, Any]]) -> str:
    """What an operation read, the values most likely to be the cause first."""
    if not reads:
        return ''

    def telling(v: Optional[float]) -> bool:
        return v is None or not math.isfinite(v) or v <= 0
    if len(reads) <= MOST_READS:
        shown = list(reads)
    else:
        shown = ([r for r in reads if telling(r['value'])] + [r for r in reads if not telling(r['value'])])[:MOST_READS]
    keep = {id(r) for r in shown}
    ordered = [r for r in reads if id(r) in keep]
    items = [f"{r['text']} = {'?' if r['value'] is None else number(r['value'])}" for r in ordered]
    more = len(reads) - len(ordered)
    if more:
        return f", with {', '.join(items)} and {more} more"
    return f", with {''.join(items) if len(items) < 2 else ', '.join(items[:-1]) + ' and ' + items[-1]}"


def _index_text(index: Optional[Dict[str, str]]) -> str:
    return f' [{describe_tuple(index)}]' if index else ''


def _where_text(g: Dict[str, Any], layout: Any) -> str:
    if not g['dims']:
        return ''
    more = g['count'] - 1
    tail = f" (and {more} more of its indices)" if more else ''
    return f" at {describe_tuple(tuple_by_list(layout.index_space, g['dims'], g['first']))}{tail}"


def number(v: float) -> str:
    """A value as it is shown: four figures, written as JavaScript writes a number."""
    v = float(v)
    if not math.isfinite(v):
        return js_string(v)
    if v == 0:
        return '0'
    return js_string(float(to_exponential(v, 3)))


def _worked_text(node: Any, parts: Sequence[Dict[str, Any]], value: float) -> str:
    """An operation with its operands' values in place of their equations: ``0/0``, ``log(0)``."""
    def v(i: int) -> str:
        x = parts[i]['value'] if i < len(parts) else None
        if x is None:
            return '?'
        s = number(x)
        return f'({s})' if x < 0 else s
    t = node.type
    big = ', too large for a number' if _overflows(parts, value) else ''
    if t == 'binary':
        return f'{v(0)}{_op_text(node.op)}{v(1)}{big}'
    if t == 'unary':
        return f'-{v(0)}'
    if t == 'call':
        if not parts:
            return number(value)
        args = ', '.join(number(p['value'] if p['value'] is not None else math.nan) for p in parts)
        return f'{node.name}({args}){big}'
    return number(value)


def _overflows(parts: Sequence[Dict[str, Any]], value: float) -> bool:
    """Whether numbers went in and an infinity came out: an overflow rather than a domain error."""
    return (math.isinf(value) and all(p['value'] is not None and math.isfinite(p['value']) for p in parts)
            and not any(p['value'] == 0 for p in parts))


def _op_text(op: str) -> str:
    return op if op in ('*', '/', '^') else f' {op} '


# --- equations back to text ------------------------------------------------------------------

_PRECEDENCE = {'||': 1, '&&': 2, '==': 3, '~=': 3, '<': 4, '<=': 4, '>': 4, '>=': 4, '+': 5, '-': 5, '*': 6, '/': 6}
_UNARY = 7
_POWER = 8
_ATOM = 10


def _precedence_of(node: Any) -> int:
    t = node.type
    if t == 'binary':
        return _POWER if node.op == '^' else _PRECEDENCE.get(node.op, 0)
    if t == 'unary':
        return _UNARY
    if t == 'cond':
        return 0
    if t == 'num':
        return _UNARY if node.value < 0 else _ATOM
    return _ATOM


def equation_text(node: Any) -> str:
    """A tree written back out as an equation (``equationText``)."""
    text = _write(node)
    if len(text) <= LONGEST_PART:
        return text
    keep = (LONGEST_PART - 1) // 2
    return f'{text[:keep]}…{text[len(text) - keep:]}'


def _write(node: Any) -> str:
    def wrap(child: Any, tighter: int) -> str:
        return f'({_write(child)})' if _precedence_of(child) < tighter else _write(child)
    t = node.type
    if t == 'num':
        unit = getattr(node, 'unit', None)
        return f"{js_string(node.value)}{f'[{unit}]' if unit is not None else ''}"
    if t == 'ref':
        idx = list(node.indices.values()) if isinstance(node.indices, dict) else list(node.indices or [])
        return node.name + ''.join(f"[{'' if i is None else i}]" for i in idx)
    if t == 'unary':
        return f'-{wrap(node.operand, _POWER)}'
    if t == 'binary':
        if node.op == '^':
            right = node.right
            exponent = (_write(right) if right.type == 'unary' and _precedence_of(right.operand) >= _ATOM
                        else wrap(right, _ATOM))
            return f'{wrap(node.left, _POWER)}^{exponent}'
        p = _PRECEDENCE.get(node.op, 0)
        return f'{wrap(node.left, p)}{_op_text(node.op)}{wrap(node.right, p + 1)}'
    if t == 'cond':
        return f'{wrap(node.test, 1)} ? {wrap(node.then, 1)} : {wrap(node.otherwise, 1)}'
    if t == 'call':
        return f"{node.name}({', '.join(_write(a) for a in node.args or [])})"
    return '?'


# --- the run's side --------------------------------------------------------------------------

def _about_non_numbers(e: Any) -> bool:
    return getattr(e, 'code', None) == 'nonfinite' or bool(_NON_NUMBERS.search(str(e)))


def _step_past(system: Any, frm: Dict[str, Any], up_to: float) -> Optional[Dict[str, Any]]:
    """Explicit steps past the last state the solver held, from the shortest the
    clock tells apart and four times longer each time, up to ``up_to`` or the
    first that shows a value that is not a number (``stepPast``)."""
    n = system.layout.nstate
    y = np.array(frm['y'], dtype=float)[:n]
    f = np.array(system.dydt(frm['t'], y), dtype=float)
    if not np.all(np.isfinite(f)):
        return None
    shortest = 4 * EPS * max(1.0, abs(frm['t']))
    longest = max(up_to, 1024 * shortest)
    h = shortest
    while h <= longest:
        found = non_finite_at(system, frm['t'] + h, y + h * f)
        if found is not None:
            return {'found': found, 'h': h}
        h *= 4
    return None


def explain_non_finite(e: Any, system: Any, start: Optional[Tuple[float, Any]] = None,
                       held: Optional[Dict[str, Any]] = None, end: float = math.nan) -> bool:
    """Puts what :func:`non_finite_at` finds into a solver's error
    (``explainNonFinite``): at the state the solver last held -- its own, if
    its error carries one, else the step the runner kept -- and at the instant
    it failed; else at the start of the stretch it was solving, if that is
    where it failed; else, for a failure about a value that is not a number,
    short steps past the state held. The message is said again with the place
    in it, and the block it starts in becomes ``block_name``. Nothing is
    changed when nothing is found."""
    if e is None or system is None:
        return False
    if getattr(e, 'code', None) in ('aborted', 'span'):
        return False
    last_y = getattr(e, 'last_y', None)
    last_t = getattr(e, 'last_t', None)
    if last_y is not None and _finite(last_t):
        frm: Optional[Dict[str, Any]] = {'t': float(last_t), 'y': last_y}
    elif held is not None and _finite(held.get('t')) and (start is None or not held['t'] < start[0]):
        frm = held
    else:
        frm = None
    e_t = getattr(e, 't', None)
    tries = []
    if frm is not None:
        tries.append((frm['t'], frm['y']))
        if _finite(e_t) and e_t != frm['t']:
            tries.append((float(e_t), frm['y']))
    elif start is not None and _finite(start[0]) and (not _finite(e_t) or e_t == start[0]):
        tries.append((float(start[0]), start[1]))

    def said(found: Dict[str, Any], step: Optional[Dict[str, float]] = None) -> bool:
        e.solver_message = str(e)
        e.args = (non_finite_message(found, system.layout, step),)
        e.non_finite = found
        root = found['root'] or {}
        block = (root.get('source') or {}).get('name') or root.get('name') or \
            (found['states'][0]['name'] if found['states'] else None)
        if block:
            e.block_name = block
        return True

    for t, y in tries:
        try:
            found = non_finite_at(system, t, y)
        except Exception:  # noqa: BLE001
            found = None
        if found is not None:
            return said(found)
    if frm is not None and _about_non_numbers(e):
        up_to = max(2 * abs(e_t - frm['t']) if _finite(e_t) else 0.0,
                    1e-3 * abs(end - frm['t']) if _finite(end) else 0.0)
        try:
            past = _step_past(system, frm, up_to)
        except Exception:  # noqa: BLE001
            past = None
        if past is not None:
            return said(past['found'], {'from': frm['t'], 'h': past['h']})
    return False


__all__ = ['non_finite_at', 'start_warnings', 'non_finite_message', 'explain_non_finite', 'equation_text', 'number']
