"""Builds a runnable system from a :class:`~kompartment.engine.project.Project`.

A port of ``src/sim/builder.js``. The state vector, the parameter vector and
the algebraic slots are laid out exactly as the application lays them out --
same order, same offsets -- so a state or a slot can be compared with the
application's one for one. What differs is how the equations are run: the
application writes a JavaScript loop per block; here every equation becomes a
statement over all the indices it is written at, statements of the same shape
that do not read one another are merged into one numpy expression, and the
derivative is assembled by one weighted ``bincount`` over every flux, decay
and ingrowth term of the model, in the order the application adds them.

The equations per compartment C at index tuple i are the application's:

    dC[i]/dt = sum(inflows) - sum(outflows) + sources
               - lambda[m] * C[i] + sum over parents p (lambda * ratio * C[i, m := p])

with a flux ``donor * rate`` when it multiplies by its donor and ``rate``
otherwise.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from ..errors import KompartmentError
from ..indexlists import COMPARTMENT_LIST, SOURCE_INDEX, TARGET_INDEX, TRANSFER_LIST
from ..names import qualified_name, resolve_reference
from . import codegen
from .codegen import CodeWriter, Leaf, Tree
from .farfield import (FARF_METHODS, FARF_NUCLIDE_KEYS, FarfError, FarfPath, active_equation_keys, cell_count,
                       effective_structure, geometry_problem, is_semi_analytic, structure_problem, surface_of,
                       uses_cells)
from .farfield_semi import FARF_TEXT, LaplaceFarfPath
from .indexspace import IndexError_, IndexSpace
from .lang import Call, Node, Num, ParseError, Ref, collect_references, parse
from .lookup import LookupError_, Table
from .project import (DIS_EQUATION_KEYS, FAILURE_KEYS, SECONDS_PER_YEAR, TIMING_KEYS, WASTE_EQUATION_KEYS,
                      WASTE_LABEL, WASTE_NUCLIDE_KEYS, Project, has_dydt, lam, normalise_actions, value_at)
from .recorders import (DIRECTION_SIGN, EQUATION_FIELDS, EVENT_ACTION, EVENT_FIELDS, RECORDER_COLLECTION,
                        RECORDER_KINDS, REMEMBERING_KINDS, Recorder)
from .reduce import OPERATION_FUNCTION, operated_list
from .userfunctions import FunctionError, UserFunctions

BUDGET_TERMS = ('in', 'out', 'decay', 'ingrowth', 'explicit', 'between')
UNINDEXED = 'not by nuclide'
WINDOW_TAIL = 1e-3
AVAILABILITY_SCHEMES = ('limit', 'shared_limit', 'langmuir', 'shared_langmuir')
AVOGADRO_AVAILABILITY = 6.02214076e23
TIME_UNITS = {'second': 1 / SECONDS_PER_YEAR, 'minute': 60 / SECONDS_PER_YEAR, 'hour': 3600 / SECONDS_PER_YEAR,
              'day': 1 / 365.25, 'year': 1.0}

DIS_LABEL = {'at': 'At', 'rate': 'Rate', 'from': 'From', 'until': 'Until'}
SLOT_WORDS = {
    **{k: v.lower() for k, v in WASTE_LABEL.items()},
    **{k: f'{v.lower()} setting' for k, v in DIS_LABEL.items()},
    'dydt': 'dy/dt term', 'limit': 'availability limit', 'top': 'availability numerator',
    'bottom': 'availability denominator', 'hazard': 'failure hazard', 'lambda': 'rate', 'share': 'share',
}


def in_words(message: str) -> str:
    """A builder message with its ``'Block#setting'`` names said in words."""
    def slot(block: str, key: str) -> str:
        words = SLOT_WORDS.get(key) or SLOT_WORDS.get(re.sub(r'\d+$', '', key)) or f'setting {key}'
        return f'{block}’s {words}'

    text = str(message if message is not None else '')
    text = re.sub(r"add '([^']+)' to '([^'#]+)#[^']*'", lambda m: f"add '{m.group(1)}' to the lists {m.group(2)} is "
                  'indexed by', text)
    return re.sub(r"'([^'#\s]+)#([A-Za-z_]+\d*)'", lambda m: slot(m.group(1), m.group(2)), text)


class BuildError(KompartmentError):
    """A model that cannot be turned into equations; ``block_name`` names the
    block it is about, ``setting`` the setting of it, when it is one."""

    def __init__(self, message: str, block_name: Optional[str] = None) -> None:
        cut = block_name.find('#') if isinstance(block_name, str) else -1
        owner = block_name[:cut] if cut > 0 else block_name
        said = in_words(message)
        super().__init__(f'{owner}: {said}' if owner else said)
        self.block_name = owner
        self.setting = block_name[cut + 1:] if cut > 0 else None


class Entry:
    """A layout entry: a state block, a parameter, an algebraic slot range."""

    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)

    def get(self, key: str, default: Any = None) -> Any:
        return self.__dict__.get(key, default)

    def __repr__(self) -> str:
        return f"Entry({self.__dict__.get('kind')}, {self.__dict__.get('name')!r})"


# --- helpers over the index space ---------------------------------------------------

def tuple_by_list(space: IndexSpace, dims: Sequence[str], offset: int) -> Dict[str, str]:
    names = space.tuple_at(dims, offset)
    return {d: names[i] for i, d in enumerate(dims)}


def position_in(space: IndexSpace, dim: str, tuple_: Dict[str, str]) -> Optional[int]:
    """The enabled position of ``dim`` for a tuple, through related lists."""
    if tuple_.get(dim) is not None:
        pos = space.get(dim).position_of.get(tuple_[dim])
        if pos is not None:
            return pos
    for list_name, index_name in tuple_.items():
        if list_name == dim:
            continue
        rel = space.relate(dim, list_name) if space.has(list_name) else None
        if not rel:
            continue
        if rel['kind'] == 'same':
            pos = space.get(dim).position_of.get(index_name)
            if pos is not None:
                return pos
        else:
            k = space.get(list_name).position_of.get(index_name)
            if k is None:
                continue
            pos = int(rel['table'][k])
            if pos >= 0:
                return pos
    return None


def derived_index(space: IndexSpace, dim: str, index_name: str) -> Any:
    """The index of ``dim`` standing for ``index_name`` of its root list: None
    when ``dim`` is a root or the name is not its root's, False when the root
    index has no counterpart in ``dim``."""
    lst = space.get(dim)
    if lst.root_name == dim:
        return None
    root = space.get(lst.root_name)
    k = root.position_of.get(index_name)
    if k is None:
        return None
    rel = space.relate(dim, lst.root_name)
    pos = int(rel['table'][k]) if rel and rel['kind'] == 'map' else k
    if pos is None or pos < 0:
        return False
    return lst.enabled[pos]['name'] if pos < len(lst.enabled) else False


def pin_indices(space: IndexSpace, target: Entry, indices: Any, name: str, owner_name: Optional[str],
                context: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Which dimension of ``target`` each written index pins -- by name, not by
    position, as the file format resolves them."""
    fixed: Dict[str, str] = {}
    written = [i for i in (indices or []) if i is not None and i != '']
    given = []
    for i in written:
        if i != SOURCE_INDEX and i != TARGET_INDEX:
            given.append(i)
            continue
        end = (context or {}).get(i)
        if end:
            given.append(end)
            continue
        which = 'flows out of' if i == SOURCE_INDEX else 'flows into'
        if context and context.get(TRANSFER_LIST) is not None:
            goes = 'comes from' if i == SOURCE_INDEX else 'goes'
            raise BuildError(f"'{name}[{i}]' asks for the compartment this transfer {which}, and it has none: it "
                             f'{goes} outside the model.', owner_name)
        raise BuildError(f"'{i}' means the compartment a transfer {which}, so it can only be written in a "
                         "transfer's own equation.", owner_name)
    if not given:
        return fixed

    def as_written() -> str:
        return name + ''.join(f"[{'' if i is None else i}]" for i in (indices or []))

    dims = target.dims
    if len(given) > len(dims):
        noun = 'index' if len(given) == 1 else 'indices'
        if dims:
            what = f"only {len(dims)} list{'' if len(dims) == 1 else 's'} ({', '.join(dims)})"
        else:
            what = 'nothing, so it holds a single value'
        raise BuildError(f"'{as_written()}' pins {len(given)} {noun}, but '{name}' is indexed by {what}.",
                         owner_name)

    def accepted(dim: str, index_name: str) -> Optional[str]:
        if index_name in space.index_names(dim):
            return index_name
        d = derived_index(space, dim, index_name)
        return d or None

    claimed: Set[int] = set()
    for dim in dims:
        pick = next((k for k, i in enumerate(given) if k not in claimed and accepted(dim, i) is not None), -1)
        if pick == -1:
            pick = next((k for k, i in enumerate(given) if accepted(dim, i) is not None), -1)
        if pick == -1:
            continue
        fixed[dim] = accepted(dim, given[pick])  # type: ignore[assignment]
        claimed.add(pick)
    for k, g in enumerate(given):
        if k in claimed:
            continue
        disabled_in = [d for d in dims if any(i['name'] == g and i['enabled'] is False for i in space.get(d).indices)]
        if disabled_in:
            raise BuildError(f"'{g}' is disabled in '{disabled_in[0]}', so '{as_written()}' has no value. Re-enable "
                             'it, or change this equation.', owner_name)
        owns = [d for d in dims if accepted(d, g) is not None]
        if owns:
            names = "' and '".join(owns)
            raise BuildError(f"'{as_written()}' pins '{names}' twice: '{g}' belongs to "
                             f"{'it' if len(owns) == 1 else 'them'}, and so does another index in the same reference.",
                             owner_name)
        raise BuildError(f"'{g}' is not an index of any list that '{name}' is indexed by ({', '.join(dims) or 'none'})",
                         owner_name)
    return fixed


def implicit_indices(owner: Any) -> Optional[Dict[str, Any]]:
    """The index positions a block occupies by being what it is: a transfer is
    one of the transfers and knows its two ends; a compartment is one of the
    compartments."""
    if owner is None or isinstance(owner, str):
        return None
    block = owner.get('block') or {}
    alias = block.get('alias') or {}
    kind = str(owner.get('kind'))
    if kind == 'transfer' or kind.startswith('availability:'):
        return {
            TRANSFER_LIST: alias.get('transfer') or owner.get('transfer') or owner.name,
            SOURCE_INDEX: alias.get('from') or block.get('from'),
            TARGET_INDEX: alias.get('to') or block.get('to'),
        }
    if kind in ('compartment', 'compartment:dydt'):
        return {COMPARTMENT_LIST: alias.get('compartment') or owner.get('state_name') or owner.name}
    return None


def describe_tuple(tuple_: Dict[str, str]) -> str:
    return ', '.join(f'{k}={v}' for k, v in tuple_.items()) or 'scalar'


def decay_tables(model: Dict[str, Any], size: int) -> Dict[str, np.ndarray]:
    """The decay model flattened: per index its constant, and its (parent,
    coefficient) pairs."""
    n = max(1, size)
    ioff = np.zeros(n, dtype=np.int64)
    icnt = np.zeros(n, dtype=np.int64)
    ipar: List[int] = []
    icoef: List[float] = []
    for k in range(n):
        ioff[k] = len(ipar)
        parents = model['parents'][k] if k < len(model['parents']) else []
        for p in parents:
            ipar.append(p['index'])
            icoef.append(p['lambda'] * p['ratio'])
        icnt[k] = len(parents)
    lambdas = model['lambdas'] if model['lambdas'] else [0.0] * n
    return {'lam': np.array(lambdas, dtype=float), 'ioff': ioff, 'icnt': icnt,
            'ipar': np.array(ipar, dtype=np.int64), 'icoef': np.array(icoef, dtype=float)}


def flat_dimensions(space: IndexSpace, entry: Entry) -> List[str]:
    """The dimensions along which an entry's equation never changes."""
    dims = entry.dims or []
    if len(dims) < 2:
        return []
    equations = entry.equations or []
    if len(equations) != entry.width:
        return []
    strides = space.strides(dims)
    sizes = [space.size(d) for d in dims]
    out = []
    for i, d in enumerate(dims):
        flat = True
        for off in range(entry.width):
            pos = (off // strides[i]) % sizes[i]
            if pos != 0 and equations[off] != equations[off - pos * strides[i]]:
                flat = False
                break
        if flat:
            out.append(d)
    return out


def _self_refs(ast: Node, a: Entry, alg_by_name: Dict[str, Entry]) -> bool:
    stack = [ast]
    while stack:
        node = stack.pop()
        t = node.type
        if t == 'ref':
            if not node.indices:  # type: ignore[attr-defined]
                q = resolve_reference(node.name, a.system or '', lambda n: n in alg_by_name)  # type: ignore
                if q == a.name:
                    return True
        elif t == 'unary':
            stack.append(node.operand)  # type: ignore[attr-defined]
        elif t == 'binary':
            stack.extend((node.left, node.right))  # type: ignore[attr-defined]
        elif t == 'cond':
            stack.extend((node.test, node.then, node.otherwise))  # type: ignore[attr-defined]
        elif t == 'call':
            stack.extend(node.args)  # type: ignore[attr-defined]
    return False


def order_algebraic(algebraic: List[Entry], alg_by_name: Dict[str, Entry]) -> None:
    """Sorts the algebraic blocks into dependency order, in place; a cycle is an error."""
    deps: Dict[str, List[str]] = {}
    for a in algebraic:
        refs: Set[str] = set()
        seen_ids: Set[int] = set()
        for ast in a.asts:
            if id(ast) in seen_ids:
                continue
            seen_ids.add(id(ast))
            collect_references(ast, refs)
        resolved: List[str] = []
        have: Set[str] = set()
        for r in sorted(refs, key=_js_set_order(a.asts)):
            q = resolve_reference(r, a.system or '', lambda n: n in alg_by_name)
            if q and q != a.name and q not in have:
                have.add(q)
                resolved.append(q)
        for ast in a.asts:
            if _self_refs(ast, a, alg_by_name):
                local = a.get('local') or a.name
                hint = (f" To read this block at another index, name that index -- '{local}[<index>]'."
                        if a.dims else '')
                raise BuildError(f"'{local}' refers to itself. An equation cannot read its own value: there is "
                                 f'nothing to read until it has been worked out.{hint}', a.name)
        for n in a.get('needs') or []:
            if n not in have:
                have.add(n)
                resolved.append(n)
        deps[a.name] = resolved
        a.reads_alg = resolved
    state: Dict[str, int] = {}
    ordered: List[Entry] = []
    stack: List[str] = []

    def visit(name: str) -> None:
        s = state.get(name, 0)
        if s == 2:
            return
        if s == 1:
            cycle = ' -> '.join([*stack[stack.index(name):], name])
            raise BuildError(f'Circular reference: {cycle}. Expressions and transfer rates may not depend on '
                             'themselves, directly or indirectly.')
        state[name] = 1
        stack.append(name)
        for d in deps.get(name, []):
            visit(d)
        stack.pop()
        state[name] = 2
        ordered.append(alg_by_name[name])

    import sys
    limit = sys.getrecursionlimit()
    if len(algebraic) * 2 + 100 > limit:
        sys.setrecursionlimit(len(algebraic) * 2 + 100)
    try:
        for a in algebraic:
            visit(a.name)
    finally:
        sys.setrecursionlimit(limit)
    algebraic[:] = ordered


def _js_set_order(asts: Sequence[Node]) -> Callable[[str], int]:
    """The order a JavaScript Set of references would iterate in: first seen first."""
    order: Dict[str, int] = {}
    seen_ids: Set[int] = set()
    for ast in asts:
        if id(ast) in seen_ids:
            continue
        seen_ids.add(id(ast))
        _collect_in_order(ast, order)
    return lambda name: order.get(name, len(order))


def _collect_in_order(ast: Node, order: Dict[str, int]) -> None:
    # collectReferences walks the tree depth first, left to right.
    t = ast.type
    if t == 'ref':
        order.setdefault(ast.name, len(order))  # type: ignore[attr-defined]
    elif t == 'call':
        for a in ast.args:  # type: ignore[attr-defined]
            _collect_in_order(a, order)
    elif t == 'unary':
        _collect_in_order(ast.operand, order)  # type: ignore[attr-defined]
    elif t == 'binary':
        _collect_in_order(ast.left, order)  # type: ignore[attr-defined]
        _collect_in_order(ast.right, order)  # type: ignore[attr-defined]
    elif t == 'cond':
        _collect_in_order(ast.test, order)  # type: ignore[attr-defined]
        _collect_in_order(ast.then, order)  # type: ignore[attr-defined]
        _collect_in_order(ast.otherwise, order)  # type: ignore[attr-defined]


def _reads_time(node: Any) -> bool:
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, Call):
            if n.name == 'time':
                return True
            stack.extend(n.args)
        elif isinstance(n, Node):
            for key in ('operand', 'left', 'right', 'test', 'then', 'otherwise'):
                child = getattr(n, key, None)
                if child is not None:
                    stack.append(child)
    return False


def time_invariant_algebraic(algebraic: List[Entry], alg_by_name: Dict[str, Entry],
                             state_by_name: Dict[str, Entry]) -> Set[str]:
    """The algebraic blocks that hold the same value for the whole run, which
    an initial condition may read."""
    can = {'expression', 'index_reduction', 'block_reduction'}
    invariant: Set[str] = set()
    for a in algebraic:
        if a.kind not in can:
            continue
        if any(_reads_time(ast) for ast in a.asts or []):
            continue
        refs: Set[str] = set()
        for ast in a.asts or []:
            collect_references(ast, refs)
        for n in a.get('needs') or []:
            refs.add(n)

        def known(n: str) -> bool:
            return n in alg_by_name or n in state_by_name

        ok = True
        for r in refs:
            q = resolve_reference(r, a.system or '', known)
            if q is None:
                continue
            if q != a.name and q not in invariant:
                ok = False
                break
        if ok:
            invariant.add(a.name)
    return invariant


def why_not_initial(name: str, s: Entry, alg_by_name: Dict[str, Entry], state_by_name: Dict[str, Entry]) -> str:
    where = f" in '{s.system}' or at the top level" if s.system else ''
    q = resolve_reference(name, s.system or '', lambda n: n in alg_by_name or n in state_by_name)
    if q and q in state_by_name:
        return (f"Initial condition cannot read '{name}': it is a compartment, and no compartment has a value until "
                'every initial condition has been worked out. Use a parameter or an expression that does not read '
                'the state.')
    a = alg_by_name.get(q) if q else None
    if a is not None:
        why = (', being read from a table at the clock' if a.kind == 'lookup'
               else ', being the release out of a far-field path' if a.kind == 'farfield' else '')
        return (f"Initial condition cannot read '{name}': its value changes over the run{why}. Only a parameter, or "
                'an expression made of parameters and numbers, holds the same value at every moment.')
    return (f'Initial condition may only use parameters, numbers and expressions that do not change over the run; '
            f"'{name}' is not one of those{where}.")


# --- statements ----------------------------------------------------------------------

class Stmt:
    """One statement of a pass: ``array[out] = tree`` over ``width`` elements,
    or a piece of special code (``code``) that is not an expression."""

    __slots__ = ('out', 'tree', 'width', 'block', 'level', 'mergeable', 'code', 'array', 'multiply')

    def __init__(self, out: Any, tree: Optional[Tree], width: int, block: Optional[Entry], level: Tuple[int, int],
                 mergeable: bool = True, code: Optional[str] = None, array: str = 'X',
                 multiply: bool = False) -> None:
        self.out = out
        self.tree = tree
        self.width = width
        self.block = block
        self.level = level
        self.mergeable = mergeable
        self.code = code
        self.array = array
        self.multiply = multiply


def _split(stmt: Stmt) -> List[Stmt]:
    """A statement over several elements as one statement per element, in order."""
    if stmt.width <= 1 or stmt.tree is None:
        return [stmt]
    leaves = codegen.leaves(stmt.tree)
    out = []
    outs = np.asarray(stmt.out) if np.ndim(stmt.out) else np.full(stmt.width, stmt.out)
    for i in range(stmt.width):
        new = [Leaf(l.kind, l.index[i] if np.ndim(l.index) else l.index) for l in leaves]
        out.append(Stmt(int(outs[i]), codegen.rebuild(stmt.tree, new), 1, stmt.block, stmt.level, False,
                        array=stmt.array, multiply=stmt.multiply))
    return out


def merge_statements(stmts: Sequence[Stmt]) -> List[Stmt]:
    """Statements at the same level with the same shape, merged into one each.

    The order of the result is by level; within a level, merged groups keep
    the position of their first statement. Statements that may not be merged
    (special code, a block that reads itself) stay where they are.
    """
    by_level: Dict[Tuple[int, int], List[Stmt]] = defaultdict(list)
    for s in stmts:
        by_level[s.level].append(s)
    out: List[Stmt] = []
    for level in sorted(by_level):
        group_of: Dict[Tuple[str, str, bool], List[Stmt]] = {}
        order: List[Any] = []
        for s in by_level[level]:
            if not s.mergeable or s.tree is None:
                order.append(s)
                continue
            key = (s.array, codegen.signature(s.tree), s.multiply)
            g = group_of.get(key)
            if g is None:
                group_of[key] = g = []
                order.append(g)
            g.append(s)
        for item in order:
            if isinstance(item, Stmt):
                out.append(item)
                continue
            if len(item) == 1:
                out.append(item[0])
                continue
            leaves = codegen.merge_leaves([(codegen.leaves(s.tree), s.width) for s in item])
            outs = np.concatenate([np.asarray(s.out, dtype=np.int64).reshape(-1) if np.ndim(s.out)
                                   else np.full(s.width, s.out, dtype=np.int64) for s in item])
            first = item[0]
            out.append(Stmt(outs, codegen.rebuild(first.tree, leaves), int(outs.size), first.block, level,
                            array=first.array, multiply=first.multiply))
    return out


def write_statements(writer: CodeWriter, stmts: Sequence[Stmt], indent: str = '    ') -> List[str]:
    lines = []
    for s in stmts:
        if s.code is not None:
            lines.extend(indent + line for line in s.code.split('\n'))
            continue
        vector = s.width > 1
        expr = writer.expression(s.tree, vector=vector)
        target = f'{s.array}[{writer.index(s.out)}]'
        if s.multiply:
            lines.append(f'{indent}{target} *= {expr}')
        else:
            lines.append(f'{indent}{target} = {expr}')
    return lines


# --- the builder ------------------------------------------------------------------------

def build_system(project: Project, jacobian: bool = True) -> 'Any':
    """The runnable system of a project (``buildSystem``)."""
    from .system import System
    b = _Builder(project)
    return System(b, jacobian=jacobian)


class _Builder:
    """Everything ``buildSystem`` works out, kept for :class:`System`."""

    def __init__(self, project: Project) -> None:
        if project.transports:
            from .transport import TransportError, expand_transports
            try:
                project = expand_transports(project)
            except TransportError as e:
                raise BuildError(str(e), e.block_name) from None
        self.project = project
        self.space = space = project.index_space
        self.material_list = project.material_list_name
        self.decay = project.decay_model()
        self.material_root = space.get(self.material_list).root_name if self.material_list else None
        self.writer = CodeWriter()
        self._layout_states()
        self._layout_parameters()
        self._layout_tables()
        self._layout_algebraic()
        self._prepare_parsing()
        self._parse_all()
        try:
            order_algebraic(self.algebraic, self.alg_by_name)
        except BuildError as e:
            raise self._semi_loop(e) from None
        self._levels()
        self._events()
        self._generate_algebraic()
        self._classes()
        self._assembly()
        self._jumps()
        self._decay_tables()
        self._initial_state()

    def _semi_loop(self, e: 'BuildError') -> 'BuildError':
        """A loop through a semi-analytical path's release said as what it is:
        the path's inflow reads the release, which reads the inflow, with no
        state between them -- a path on cells breaks such a loop with its
        cells, and this one cannot."""
        m = re.search(r'Circular reference: (.*)\. ', str(e))
        if not m:
            return e
        names = m.group(1).split(' -> ')
        path = next((p for p in self.farf_layout if p.farf.laplace and p.name in names), None)
        if path is None:
            return e
        return BuildError(f"'{path.local}' is worked out semi-analytically, and what flows into it reads its own "
                          f'release at the same instant ({m.group(1)}). Its release depends on what flows in, so '
                          'the two cannot be worked out one after the other: put a compartment between them, or '
                          'work the path out on cells.', path.name)

    def semi_refusals(self, X: np.ndarray) -> None:
        """What a semi-analytical path cannot be, found once the settings that
        never move are worked out: a setting that follows the clock or the
        state, and a path its method cannot solve."""
        for p in self.farf_layout:
            if not p.farf.laplace:
                continue
            for key in active_equation_keys(p.block):
                slot = self.alg_by_name.get(f'{p.name}#{key}')
                if slot is None or key == 'pen_dep_0':
                    continue
                cls = int(self.slot_class[slot.base:slot.base + slot.width].max()) if slot.width else 0
                if cls == 0:
                    continue
                said = str(p.block.get(key) if p.block.get(key) is not None else '').strip()
                raise BuildError(f"'{p.local}' is worked out semi-analytically, which solves the path once for the "
                                 f'whole run, so its settings have to be constants -- and '
                                 f"{FARF_TEXT.get(key, key)} follows the {'clock' if cls == 1 else 'state of the model'}"
                                 + (f" ('{said}')" if said else '')
                                 + '. Give it a constant, or work the path out on cells, which reads its settings '
                                 'as they change.', p.name)
            try:
                self.FARF[p.farf_index].prepare(X)
            except FarfError as e:
                raise BuildError(f"'{p.local}' cannot be worked out semi-analytically: {e}", p.name) from None

    # --- small helpers ------------------------------------------------------------------

    def dims_of(self, block: Dict[str, Any]) -> List[str]:
        return self.space.without_scenarios(block.get('index_lists') or [])

    def is_nuclide_dim(self, d: str) -> bool:
        space = self.space
        return bool(self.material_list) and not space.get(d).mapping and space.get(d).root_name == self.material_root

    def entry_tuple(self, block: Dict[str, Any], dims: Sequence[str], off: int) -> Dict[str, str]:
        return self.space.pin_scenario(block.get('index_lists') or [], tuple_by_list(self.space, dims, off))

    # --- layout -------------------------------------------------------------------------

    def _layout_states(self) -> None:
        project, space = self.project, self.space
        states: List[Entry] = []
        n = 0
        for c in project.compartments:
            dims = self.dims_of(c)
            width = space.width(dims)
            e = Entry(name=c['qname'], local=c['name'], system=c.get('system') or '', base=n, width=width, dims=dims,
                      block=c, kind='compartment', hidden=bool(c.get('hidden')))
            states.append(e)
            n += width
        self.mean_states: List[Entry] = []
        for m in project.running_means:
            dims = self.dims_of(m)
            width = space.width(dims)
            e = Entry(name=m['qname'], local=m['name'], system=m.get('system') or '', base=n, width=width, dims=dims,
                      block=m, kind='running_mean', hidden=True)
            states.append(e)
            self.mean_states.append(e)
            n += width
        self.farf_layout: List[Entry] = []
        for b in project.farfields:
            problem = structure_problem(b) or geometry_problem(b)
            if problem:
                raise BuildError(problem, b['qname'])
            laplace = is_semi_analytic(b)
            if not uses_cells(b) and not laplace:
                raise BuildError(f"'{b.get('method')}' is not a way this tool can work a path out "
                                 f"({', '.join(FARF_METHODS)})", b['qname'])
            dims = self.dims_of(b)
            nuc_dims = [d for d in dims if self.is_nuclide_dim(d)]
            if len(nuc_dims) > 1:
                raise BuildError('A far-field path runs one decay chain, and it is indexed by two radionuclide '
                                 f"dimensions ({' and '.join(nuc_dims)}).", b['qname'])
            m_idx = next((i for i, d in enumerate(dims) if self.is_nuclide_dim(d)), -1)
            list_name = dims[m_idx] if m_idx >= 0 else None
            nnuc = space.size(list_name) if list_name else 1
            other_idx = [i for i in range(len(dims)) if i != m_idx]
            other_dims = [dims[i] for i in other_idx]
            other_width = space.width(other_dims)
            ncells = cell_count(b)
            strides = space.strides(dims)
            other_strides = space.strides(other_dims)
            dim_off = np.zeros(other_width * nnuc, dtype=np.int64)
            single_off = np.arange(other_width, dtype=np.int64)
            for o in range(other_width):
                at = 0
                for k, od in enumerate(other_dims):
                    pos = (o // other_strides[k]) % space.size(od)
                    at += pos * strides[other_idx[k]]
                for m in range(nnuc):
                    dim_off[o * nnuc + m] = at + (m * strides[m_idx] if m_idx >= 0 else 0)
            e = Entry(name=b['qname'], local=b['name'], system=b.get('system') or '', base=n,
                      width=other_width * ncells * nnuc, dims=dims, block=b, kind='farfield', hidden=True,
                      farf=Entry(structure=None if laplace else effective_structure(b), laplace=laplace,
                                 nnuc=nnuc, other_dims=other_dims, other_width=other_width, ncells=ncells,
                                 m_idx=m_idx, list_name=list_name, dim_off=dim_off, single_off=single_off))
            states.append(e)
            self.farf_layout.append(e)
            n += e.width
        self.waste_layout: List[Entry] = []
        for w in project.waste_packages:
            q = w['qname']
            dims = self.dims_of(w)
            width = space.width(dims)
            shared = dict(local=w['name'], system=w.get('system') or '', width=width, dims=dims, block=w, qname=q,
                          kind='waste_package', hidden=True, unit=project.decay_unit)
            intact = Entry(**shared, name=f'{q} intact', role='intact', base=n)
            exposed = Entry(**shared, name=f'{q} exposed', role='exposed', base=n + width)
            states.extend((intact, exposed))
            failure = w.get('failure') if w.get('failure') in FAILURE_KEYS else 'never'
            self.waste_layout.append(Entry(q=q, block=w, intact=intact, exposed=exposed, dims=dims, width=width,
                                           failure=failure, disrupted=[]))
            n += 2 * width
        self.waste_by_name = {W.q: W for W in self.waste_layout}
        self.disruption_layout: List[Entry] = []
        for d in project.events:
            q = d['qname']
            e = Entry(name=q, local=d['name'], system=d.get('system') or '', base=n, width=1, dims=[], block=d,
                      qname=q, kind='event', hidden=False, unit='')
            states.append(e)
            timing = d.get('timing') if d.get('timing') in TIMING_KEYS else 'at'
            self.disruption_layout.append(Entry(q=q, block=d, entry=e, timing=timing,
                                                actions=normalise_actions(d.get('actions')),
                                                index=len(self.disruption_layout), sampled_times=[]))
            n += 1
        self.budget = None
        if project.simulation.get('mass_balance'):
            mat = space.get(self.material_list) if self.material_list else None
            families = ([i['name'] for i in mat.enabled] if mat else []) + [UNINDEXED]
            nfam = len(families)
            members = []
            for s in states:
                if s.kind not in ('compartment', 'waste_package'):
                    continue
                fam_of = np.full(s.width, nfam - 1, dtype=np.int64)
                m = next((i for i, d in enumerate(s.dims) if self.is_nuclide_dim(d)), -1)
                if m >= 0 and mat is not None:
                    for off in range(s.width):
                        nm = tuple_by_list(space, s.dims, off)[s.dims[m]]
                        fam_of[off] = mat.position_of.get(nm, nfam - 1)
                members.append({'name': s.name, 'base': s.base, 'width': s.width, 'famOf': fam_of})
            self.budget = {'base': n, 'nfam': nfam, 'families': families, 'terms': list(BUDGET_TERMS),
                           'members': members}
            states.append(Entry(name='#mass-balance', local='#mass-balance', system='', base=n,
                                width=len(BUDGET_TERMS) * nfam, dims=[], block=None, kind='budget', hidden=True,
                                budget=self.budget))
            n += len(BUDGET_TERMS) * nfam
        self.states = states
        self.nstate = n
        self.state_by_name = {s.name: s for s in states if s.kind == 'compartment'}
        self.path_by_name = {f.name: f for f in self.farf_layout}

    def _layout_parameters(self) -> None:
        project, space = self.project, self.space
        self.param_layout: List[Entry] = []
        n = 0
        for p in project.parameters:
            dims = self.dims_of(p)
            width = space.width(dims)
            self.param_layout.append(Entry(name=p['qname'], local=p['name'], system=p.get('system') or '', base=n,
                                           width=width, dims=dims, block=p))
            n += width
        self.param_by_name = {p.name: p for p in self.param_layout}
        self.point_layout: List[Entry] = []
        for lk in project.lookups:
            dims = self.dims_of(lk)
            width = space.width(dims)
            for off in range(width):
                tup = self.entry_tuple(lk, dims, off)
                points = value_at(lk, 'points', tup) or []
                for i, pt in enumerate(points):
                    spec = pt[2] if isinstance(pt, list) and len(pt) > 2 else None
                    if not spec:
                        continue
                    self.point_layout.append(Entry(name=lk['qname'], block=lk, dims=dims, index=tup, off=off, point=i,
                                                   at=float(pt[0]), value=float(pt[1]), spec=spec, slot=n, tab=-1,
                                                   row=-1))
                    n += 1
        self.points_by_entry: Dict[Tuple[str, int], List[Entry]] = defaultdict(list)
        for pt in self.point_layout:
            self.points_by_entry[(pt.name, pt.off)].append(pt)
        self.nparam = n
        P = np.zeros(max(1, n))
        for pt in self.point_layout:
            P[pt.slot] = pt.value
        for e in self.param_layout:
            for off in range(e.width):
                tup = self.entry_tuple(e.block, e.dims, off)
                v = value_at(e.block, 'value', tup)
                num = _js_number(v)
                if not math.isfinite(num):
                    raise BuildError(f"Value '{v}' is not a number", e.name)
                P[e.base + off] = num
        self.P = P

    def _layout_tables(self) -> None:
        project, space = self.project, self.space
        self.TAB: List[Table] = []
        self.lookup_layout: List[Entry] = []
        for lk in project.lookups:
            dims = self.dims_of(lk)
            width = space.width(dims)
            cache: Dict[int, Table] = {}
            base = len(self.TAB)
            for off in range(width):
                tup = self.entry_tuple(lk, dims, off)
                points = value_at(lk, 'points', tup) or []
                mine = self.points_by_entry.get((lk['qname'], off))
                table = None if mine else cache.get(id(points))
                if table is None:
                    try:
                        table = Table(points if points else [[0, 0]], lk.get('interpolation') or 'linear',
                                      bool(lk.get('cyclic')))
                    except LookupError_ as e:
                        at = f' at {describe_tuple(tup)}' if dims else ''
                        raise BuildError(f'{e}{at}', lk['qname']) from None
                    if not mine:
                        cache[id(points)] = table
                self.TAB.append(table)
                if mine:
                    order = sorted(range(len(points)), key=lambda i: _js_number(points[i][0]))
                    rank = {frm: to for to, frm in enumerate(order)}
                    for pt in mine:
                        pt.tab = len(self.TAB) - 1
                        pt.row = rank.get(pt.point, pt.point)
            self.lookup_layout.append(Entry(name=lk['qname'], local=lk['name'], system=lk.get('system') or '',
                                            tab=base, width=width, dims=dims, block=lk,
                                            argument=lk.get('argument') or None))
        self.table_by_name = {lk.name: lk for lk in self.lookup_layout if lk.argument}

    def _layout_algebraic(self) -> None:
        project, space = self.project, self.space
        self.algebraic: List[Entry] = []
        self.nalg = 0

        def add(name: str, kind: str, block: Dict[str, Any], value_key: Optional[str],
                over: Optional[List[str]] = None) -> Entry:
            dims = over if over is not None else self.dims_of(block)
            width = space.width(dims)
            e = Entry(name=name, local=block.get('name'), system=block.get('system') or '', kind=kind, block=block,
                      value_key=value_key, dims=dims, base=self.nalg, width=width, hidden=bool(block.get('hidden')))
            self.algebraic.append(e)
            self.nalg += width
            return e

        self._add_algebraic = add
        for e in project.expressions:
            add(e['qname'], 'expression', e, 'equation')
        for t in project.transfers:
            slot = add(t['qname'], 'transfer', t, 'rate')
            scheme = t.get('availability')
            if not isinstance(scheme, dict) or scheme.get('scheme') not in AVAILABILITY_SCHEMES:
                continue
            slot.availability = Entry(scheme=scheme, operands={})
            keys = ['limit'] if scheme['scheme'] in ('limit', 'shared_limit') else ['top', 'bottom']
            for key in keys:
                holder = {**t, 'entries': [], key: scheme.get(key)}
                op = add(f"{slot.name}#{key}", f'availability:{key}', holder, key, slot.dims)
                op.hidden = True
                op.transfer = slot.name
                slot.availability.operands[key] = op
            slot.needs = [op.name for op in slot.availability.operands.values()]
        for s in project.inflows:
            add(s['qname'], 'inflow', s, 'rate')
        self.dydt_slots: List[Entry] = []
        for c in project.compartments:
            if not has_dydt(c):
                continue
            slot = add(f"{c['qname']}#dydt", 'compartment:dydt', c, 'dydt')
            slot.hidden = True
            slot.state_name = c['qname']
            self.dydt_slots.append(slot)
        for lk in self.lookup_layout:
            if lk.argument:
                continue
            add(lk.name, 'lookup', lk.block, 'points').tab = lk.tab
        for o in project.index_reductions:
            add(o['qname'], 'index_reduction', o, 'target')
        for g in project.block_reductions:
            add(g['qname'], 'block_reduction', g, 'targets')
        for W in self.waste_layout:
            W.setting = {}
            for key in WASTE_EQUATION_KEYS:
                if key.startswith('fail_') and key not in FAILURE_KEYS[W.failure]:
                    continue
                single = key not in WASTE_NUCLIDE_KEYS
                slot = add(f'{W.q}#{key}', f'waste_package:{key}', W.block, key, [] if single else None)
                slot.hidden = True
                if single:
                    slot.single = True
                W.setting[key] = slot
            hazard = add(f'{W.q}#hazard', 'waste_package:hazard', W.block, None, [])
            hazard.hidden = True
            hazard.needs = [W.setting[k].name for k in FAILURE_KEYS[W.failure]]
            hazard.waste = W
            W.hazard_slot = hazard
            release = add(W.q, 'waste_package', W.block, None)
            release.needs = [hazard.name, W.setting['irf'].name, W.setting['degradation_rate'].name]
            release.waste = W
            W.release_slot = release
        for D in self.disruption_layout:
            D.setting = {}
            for key in TIMING_KEYS[D.timing]:
                if not str(D.block.get(key) if D.block.get(key) is not None else '').strip():
                    continue
                slot = add(f'{D.q}#{key}', f'event:{key}', D.block, key, [])
                slot.hidden = True
                slot.single = True
                D.setting[key] = slot
            D.shares = []
            for k, a in enumerate(D.actions):
                holder = {'name': D.block['name'], 'system': D.block.get('system'), 'index_lists': [], 'entries': [],
                          'fraction': a['fraction']}
                slot = add(f'{D.q}#share{k}', 'event:share', holder, 'fraction', [])
                slot.hidden = True
                slot.single = True
                D.shares.append(slot)
            lam_slot = add(f'{D.q}#lambda', 'event:lambda', D.block, None, [])
            lam_slot.hidden = True
            lam_slot.needs = [s.name for s in D.setting.values()]
            lam_slot.event = D
            D.lambda_slot = lam_slot
            for k, a in enumerate(D.actions):
                if a['kind'] != 'fail':
                    continue
                W = self.waste_by_name.get(a.get('block'))
                if W is None:
                    raise BuildError(f"'{a.get('block')}' is not a set of waste packages, so it has no packages to "
                                     'fail.', D.q)
                W.hazard_slot.needs.extend([lam_slot.name, D.shares[k].name])
                W.disrupted.append(Entry(D=D, share=D.shares[k]))
        self.FARF: List[FarfPath] = []
        for p in self.farf_layout:
            setting_base = {}
            keys = active_equation_keys(p.block)
            for key in keys:
                per_nuclide = key in FARF_NUCLIDE_KEYS
                slot = add(f'{p.name}#{key}', f'farfield:{key}', p.block, key, None if per_nuclide else p.farf.other_dims)
                slot.hidden = True
                setting_base[key] = slot.base
                if not per_nuclide:
                    slot.single = True
            rel = add(p.name, 'farfield', p.block, None)
            rel.needs = [f'{p.name}#{key}' for key in keys]
            rel.farf = p
            rel.farf_index = len(self.FARF)
            p.alg_release = rel
            p.farf_index = len(self.FARF)
            if p.farf.laplace:
                # The release reads what flows in at the same instant -- the
                # step being taken carries it with a weight -- so it is worked
                # out after every rate that delivers into the path.
                for t in self.project.transfers:
                    if t.get('to') and t.get('to') not in self.state_by_name and self.path_by_name.get(t['to']) is p:
                        rel.needs.append(t['qname'])
                for src in self.project.inflows:
                    if src.get('to') not in self.state_by_name and self.path_by_name.get(src.get('to')) is p:
                        rel.needs.append(src['qname'])
                sim = self.project.simulation
                self.FARF.append(LaplaceFarfPath(
                    base=p.base, nnuc=p.farf.nnuc, other_width=p.farf.other_width, dim_off=p.farf.dim_off,
                    single_off=p.farf.single_off, setting_base=setting_base, keys=keys,
                    single=[k for k in keys if k not in FARF_NUCLIDE_KEYS], surface=surface_of(p.block),
                    release_base=rel.base, span=float(sim['end_time']) - float(sim['start_time']),
                    names=self.space.index_names(p.farf.list_name) if p.farf.list_name else None,
                    block_name=p.name))
                continue
            self.FARF.append(FarfPath(structure=p.farf.structure, base=p.base, nnuc=p.farf.nnuc,
                                      other_width=p.farf.other_width, dim_off=p.farf.dim_off,
                                      single_off=p.farf.single_off, setting_base=setting_base,
                                      single=[k for k in keys if k not in FARF_NUCLIDE_KEYS],
                                      release_base=rel.base, keys=keys,
                                      grid='matched' if p.block.get('grid') == 'matched' else 'reference',
                                      surface=surface_of(p.block)))
        self.MEM: List[Recorder] = []
        self.recorders: List[Entry] = []
        mean_state_by_name = {m.name: m for m in self.mean_states}
        for kind in RECORDER_KINDS:
            for blk in getattr(project, RECORDER_COLLECTION[kind]):
                name = blk['qname']
                aux = {}
                for key in EQUATION_FIELDS[kind]:
                    slot = add(f'{name}#{key}', f'{kind}:{key}', blk, key)
                    slot.hidden = True
                    aux[key] = slot
                entry = add(name, kind, blk, None)
                entry.aux = aux
                entry.needs = [a.name for a in aux.values()]
                rec = Entry(name=name, kind=kind, block=blk, entry=entry, aux=aux, dims=entry.dims, width=entry.width,
                            mem=len(self.MEM) if kind in REMEMBERING_KINDS else -1,
                            state=mean_state_by_name.get(name))
                if rec.mem >= 0:
                    for off in range(entry.width):
                        tup = self.entry_tuple(blk, entry.dims, off)
                        start = value_at(blk, 'start_trigger', tup)
                        self.MEM.append(Recorder(kind, operation=blk.get('operation') or 'max',
                                                 recording=not (start is not None and str(start).strip() != '')))
                self.recorders.append(rec)
                entry.recorder = rec
        self.alg_by_name = {a.name: a for a in self.algebraic}

    # --- parsing --------------------------------------------------------------------------

    def _known(self, n: str) -> bool:
        return n in self.state_by_name or n in self.param_by_name or n in self.alg_by_name or n in self.table_by_name

    def call_target(self, name: str, system: str) -> Optional[Entry]:
        if not self.table_by_name:
            return None
        q = resolve_reference(name, system or '', self._known)
        return self.table_by_name.get(q) if q else None

    def _prepare_parsing(self) -> None:
        project = self.project
        try:
            self.functions = UserFunctions(project.functions,
                                           callable_=lambda n, s: self.call_target(n, s or '') is not None)
        except FunctionError as e:
            raise BuildError(str(e), e.block_name) from None
        self.unit_blocks = {b['qname']: b for b in project.all_blocks()}

    def function_call(self, name: str, system: str) -> Optional[str]:
        return self.functions.resolve(name, system or '') if len(self.functions) else None

    def callable(self, name: str, system: str) -> bool:
        return self.call_target(name, system) is not None or self.function_call(name, system) is not None

    def parse_equation(self, text: str, system: str, owner: str) -> Node:
        try:
            ast = parse(text, calls=lambda n: self.callable(n, system))
            _scale_literals(ast, self, system)
        except ParseError as e:
            m = re.match(r"^Unknown function '([^']+)'", str(e))
            if m:
                raise BuildError(f'{e} in "{text}". If \'{m.group(1)}\' is meant to be one of this model’s own, '
                                 'add a function of that name under Functions and write what it works out to; '
                                 'Ecolego keeps some functions in a library beside the project, and those do not '
                                 'travel with the file.', owner) from None
            raise
        try:
            return self.functions.inline(ast, owner, system or '') if len(self.functions) else ast
        except FunctionError as e:
            raise BuildError(str(e), e.block_name or owner) from None

    def target_entry(self, name: str, system: str) -> Optional[Entry]:
        q = resolve_reference(name, system or '', self._known)
        if not q:
            return None
        return (self.state_by_name.get(q) or self.param_by_name.get(q) or self.alg_by_name.get(q)
                or self.table_by_name.get(q))

    def index_operation_ast(self, a: Entry, target: str) -> Dict[str, Any]:
        entry = self.target_entry(target, a.system)
        if entry is None:
            where = f" or in '{a.system}'" if a.system else ''
            raise BuildError(f"'{target}' is not a block in this model{where}.", a.name)
        dims = entry.dims or []
        if not dims:
            raise BuildError(f"'{target}' holds a single value, so there is no index to reduce over. An index "
                             'operation needs a target with one more dimension than it has itself.', a.name)
        over = operated_list(a.dims, dims, lambda d: self.space.get(d).for_scenarios)
        if not over:
            raise BuildError(f"'{a.local}' is indexed by every list '{target}' is ({', '.join(dims)}), so there is "
                             'nothing left to reduce over.', a.name)
        names = self.space.index_names(over)
        if not names:
            return {'ast': Num(0.0), 'text': '0', 'over': over}
        op = a.block.get('operation')
        fn = OPERATION_FUNCTION[op]
        args: List[Node] = [Ref(target, {over: idx}) for idx in names]
        shown = [f'{target}[{idx}]' for idx in names]
        if op == 'percentile':
            args.insert(0, Num(float(a.block.get('percentile'))))
            shown.insert(0, _js_str(a.block.get('percentile')))
        return {'ast': Call(fn, args), 'text': f"{fn}({', '.join(shown)})", 'over': over}

    def aggregate_ast(self, a: Entry, targets: Sequence[str]) -> Dict[str, Any]:
        kept, dropped = [], []
        for t in targets:
            entry = self.target_entry(t, a.system)
            if entry is None:
                where = f" or in '{a.system}'" if a.system else ''
                raise BuildError(f"'{t}' is not a block in this model{where}.", a.name)
            try:
                self.space.projection(a.dims, entry.dims or [], {}, {'owner': a.name, 'target': t})
                kept.append(t)
            except IndexError_:
                dropped.append(t)
        if dropped and not kept:
            frm = f"'{', '.join(a.dims)}'" if a.dims else 'a single value'
            raise BuildError(f"none of its targets ({', '.join(dropped)}) can be reached from {frm}.", a.name)
        if not kept:
            return {'ast': Num(0.0), 'text': '0', 'dropped': dropped}
        if len(kept) == 1:
            return {'ast': Ref(kept[0], []), 'text': kept[0], 'dropped': dropped}
        fn = OPERATION_FUNCTION[a.block.get('operation')]
        return {'ast': Call(fn, [Ref(t, []) for t in kept]), 'text': f"{fn}({', '.join(kept)})", 'dropped': dropped}

    def _parse_all(self) -> None:
        for a in self.algebraic:
            a.equations = []
            a.asts = []
            a.uniform = True
            if a.kind == 'lookup' or a.get('recorder') is not None or a.kind in (
                    'farfield', 'waste_package', 'waste_package:hazard', 'event:lambda'):
                continue
            if a.kind in ('index_reduction', 'block_reduction'):
                for off in range(a.width):
                    tup = self.entry_tuple(a.block, a.dims, off)
                    if a.kind == 'index_reduction':
                        t = value_at(a.block, 'target', tup)
                        spec = self.index_operation_ast(a, str(t if t is not None else ''))
                    else:
                        spec = self.aggregate_ast(a, value_at(a.block, 'targets', tup) or [])
                    a.equations.append(spec['text'])
                    a.asts.append(spec['ast'])
                    if spec.get('over'):
                        a.over = spec['over']
                    if spec.get('dropped'):
                        a.dropped = spec['dropped']
                a.uniform = all(e == a.equations[0] for e in a.equations)
                continue
            parsed: Dict[str, Node] = {}
            for off in range(a.width):
                tup = self.entry_tuple(a.block, a.dims, off)
                v = value_at(a.block, a.value_key, tup)
                eq = _js_str(v if v is not None else '0')
                a.equations.append(eq)
                ast = parsed.get(eq)
                if ast is None:
                    try:
                        ast = self.parse_equation(eq, a.system, a.name)
                    except ParseError as err:
                        raise BuildError(f'{err} in "{eq}" (at character {err.position + 1})', a.name) from None
                    parsed[eq] = ast
                a.asts.append(ast)
            a.uniform = all(e == a.equations[0] for e in a.equations)

    def _levels(self) -> None:
        level: Dict[str, int] = {}
        for a in self.algebraic:
            lv = 0
            for d in a.reads_alg:
                if d in level:
                    lv = max(lv, level[d] + 1)
            level[a.name] = lv
            a.level = lv

    # --- resolution -------------------------------------------------------------------------

    def locate(self, owner: Any, source_dims: Sequence[str], pos: Optional[List[np.ndarray]],
               fixed_tuple: Optional[Dict[str, str]], name: str, indices: Any,
               node: Optional[Node] = None) -> Tuple[str, Entry, Any]:
        """What a reference reads: ``(kind, target, index)``, the index an int
        or one per element of the statement (``pos``)."""
        space = self.space
        owner_name = owner if isinstance(owner, str) else (owner.name if owner is not None else None)
        scope = getattr(node, 'scope', None) if node is not None else None
        owner_system = scope if scope is not None else ('' if isinstance(owner, str) or owner is None
                                                        else owner.get('system') or '')
        qname = resolve_reference(name, owner_system, self._known)
        target = None
        if qname:
            target = (self.state_by_name.get(qname) or self.param_by_name.get(qname) or self.alg_by_name.get(qname)
                      or self.table_by_name.get(qname))
        if target is None:
            off = resolve_reference(name, owner_system, lambda n: n in self.project.disabled)
            if off:
                raise BuildError(f"'{name}' is disabled, so it has no value for this equation to read. Enable "
                                 f"'{off}', or disable this block as well.", owner_name)
            if owner_system:
                tail = (f"in sub-system '{owner_system}' or at the top level of this model. To reach a block in "
                        f"another sub-system, give its full path, as in '{owner_system}.{name}'.")
            else:
                tail = 'in this model.'
            raise BuildError(f"Unknown name '{name}'. It is not a parameter, compartment, expression or transfer "
                             f'{tail}', owner_name)
        kind = ('state' if qname in self.state_by_name else 'param' if qname in self.param_by_name
                else 'table' if qname in self.table_by_name else 'alg')
        context = implicit_indices(owner)
        if isinstance(indices, dict):
            fixed = dict(indices)
        else:
            fixed = pin_indices(space, target, indices, name, owner_name, context)
        for dim in target.dims:
            if dim in fixed:
                continue
            if any(space.relate(dim, sd) for sd in source_dims):
                continue
            implied = (context or {}).get(dim)
            if implied is None and context:
                root = space.get(dim).root_name
                if root != dim and context.get(root) is not None:
                    own = derived_index(space, dim, context[root])
                    if own is False:
                        what = 'transfers' if root == TRANSFER_LIST else 'compartments'
                        raise BuildError(f"'{name}' has a value per index of '{dim}', which is made of {what}, and "
                                         f"'{owner_name}' is not one of them. Add it to '{dim}', or name one, as "
                                         f"'{name}[<index>]'.", owner_name)
                    implied = own
            if implied is not None:
                fixed[dim] = implied
                continue
            if dim == COMPARTMENT_LIST:
                who = f"'{owner_name}'" if owner_name else 'this equation'
                if owner is not None and not isinstance(owner, str) and owner.get('kind') == 'transfer':
                    how = (f"Write '{name}[{SOURCE_INDEX}]' for the compartment it flows out of, or "
                           f"'{name}[{TARGET_INDEX}]' for the one it flows into.")
                else:
                    how = f"Name one, as '{name}[<compartment>]'."
                raise BuildError(f"'{name}' has a value per compartment, and {who} does not say which. {how}",
                                 owner_name)
            if dim == TRANSFER_LIST:
                who = f"'{owner_name}'" if owner_name else 'this equation'
                raise BuildError(f"'{name}' has a value per transfer, and {who} is not a transfer, so there is no "
                                 f"transfer to take it from. Name one, as '{name}[<transfer>]'.", owner_name)
        base = target.tab if kind == 'table' else target.base
        if target.width == 1 and not target.dims:
            return kind, target, int(base)
        if fixed_tuple is not None:
            tup = {**fixed_tuple, **fixed}
            off = 0
            strides = space.strides(target.dims)
            for i, dim in enumerate(target.dims):
                p = position_in(space, dim, tup)
                if p is None:
                    try:
                        space.projection(source_dims, [dim], fixed, {'owner': owner_name, 'target': name})
                    except IndexError_ as e:
                        raise BuildError(str(e), owner_name) from None
                    raise BuildError(f"Cannot resolve index '{dim}' of '{name}'", owner_name)
                off += p * strides[i]
            return kind, target, int(base + off)
        try:
            terms = space.projection(source_dims, target.dims, fixed, {'owner': owner_name, 'target': name})
        except IndexError_ as e:
            raise BuildError(str(e), owner_name) from None
        constant = int(base)
        index: Any = None
        for term in terms:
            if term.get('fixed') is not None:
                constant += term['fixed'] * term['stride']
                continue
            v = pos[term['from']]  # type: ignore[index]
            comp = term['table'][v] if term.get('table') is not None else v
            part = comp * term['stride']
            index = part if index is None else index + part
        if index is None:
            return kind, target, constant
        index = index + constant
        if index.size == 1:
            return kind, target, int(index[0])
        return kind, target, index.astype(np.int64)

    def resolver(self, owner: Any, source_dims: Sequence[str], pos: Optional[List[np.ndarray]],
                 fixed_tuple: Optional[Dict[str, str]], width: int) -> Callable[..., Leaf]:
        array_of = {'state': 'y', 'param': 'P', 'alg': 'X'}
        owner_name = owner if isinstance(owner, str) else owner.name

        def ref(name: str, indices: Any, node: Optional[Node] = None) -> Leaf:
            kind, target, index = self.locate(owner, source_dims, pos, fixed_tuple, name, indices, node)
            if kind == 'table':
                raise BuildError(f"'{name}' is a lookup table with an argument, so it has no value of its own; call "
                                 f"it, as '{name}(...)'.", owner_name)
            if kind == 'alg' and not isinstance(owner, str) and target is owner:
                self._self_reading.add(owner.name)
            return Leaf(array_of[kind], index)
        return ref

    def call_resolver(self, owner: Any, source_dims: Sequence[str], pos: Optional[List[np.ndarray]],
                      fixed_tuple: Optional[Dict[str, str]]) -> Callable[[str, List[Tree]], Optional[Tree]]:
        owner_name = owner if isinstance(owner, str) else owner.name
        owner_system = '' if isinstance(owner, str) else owner.get('system') or ''

        def call(name: str, args: List[Tree]) -> Optional[Tree]:
            if self.call_target(name, owner_system) is None:
                return None
            if len(args) != 1:
                raise BuildError(f"'{name}' is a lookup table and takes exactly one argument; {len(args)} were "
                                 'given.', owner_name)
            _, target, index = self.locate(owner, source_dims, pos, fixed_tuple, name, [], None)
            return ('tab', Leaf('TAB', index), args[0])
        return call

    # --- events -----------------------------------------------------------------------------

    def _events(self) -> None:
        space = self.space
        self.event_slots: List[Dict[str, Any]] = []
        for rec in self.recorders:
            if rec.kind != 'trigger':
                continue
            rec.event_base = len(self.event_slots)
            for off in range(rec.width):
                tup = self.entry_tuple(rec.block, rec.dims, off)
                written = value_at(rec.block, 'direction', tup) or rec.block.get('direction')
                self.event_slots.append({'slot': rec.entry.base + off, 'direction': DIRECTION_SIGN.get(written, 0),
                                         'name': rec.name,
                                         'index': tuple_by_list(space, rec.dims, off) if rec.dims else None})
        self.event_direction = np.array([e['direction'] for e in self.event_slots], dtype=np.int8)
        self.event_handlers: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for rec in self.recorders:
            if rec.mem < 0:
                continue
            for field in EVENT_FIELDS[rec.kind]:
                for off in range(rec.width):
                    tup = self.entry_tuple(rec.block, rec.dims, off)
                    written = value_at(rec.block, field, tup)
                    text = '' if written is None else str(written).strip()
                    if not text:
                        continue
                    try:
                        ast = parse(text)
                    except ParseError:
                        raise BuildError(f"'{text}' is not the name of a discrete event.", rec.name) from None
                    if ast.type != 'ref':
                        raise BuildError(f"'{field.replace('_', ' ')}' must name a discrete event, not an expression; "
                                         f"'{text}' is one.", rec.name)
                    kind, target, index = self.locate(rec.entry, rec.dims, None, tup, ast.name,  # type: ignore
                                                      ast.indices)  # type: ignore[attr-defined]
                    owner = target.get('recorder')
                    if owner is None or owner.kind != 'trigger':
                        what = 'take a snapshot' if field == 'trigger' else field.replace('_', ' ')
                        raise BuildError(f"'{ast.name}' is not a discrete event, so it cannot {what}.",  # type: ignore
                                         rec.name)
                    which = owner.event_base + (int(index) - target.base)
                    self.event_handlers[which].append({'rec': rec, 'off': off, 'action': EVENT_ACTION[field]})

    # --- statements for the algebraic blocks -----------------------------------------------

    def _generate_algebraic(self) -> None:
        self._self_reading: Set[str] = set()
        self.alg_stmts: Dict[str, List[Stmt]] = {}
        self.reads: Dict[str, Tuple[bool, bool]] = {}
        for a in self.algebraic:
            stmts = self._statements_for(a)
            if a.name in self._self_reading:
                split: List[Stmt] = []
                for s in stmts:
                    if s.tree is not None and s.width > 1:
                        split.extend(_split(s))
                    else:
                        s.mergeable = False
                        split.append(s)
                stmts = split
                for s in stmts:
                    s.mergeable = False
            self.alg_stmts[a.name] = stmts

    def _stmt(self, a: Entry, out: Any, tree: Tree, width: int, sub: int = 0, multiply: bool = False) -> Stmt:
        return Stmt(out, tree, width, a, (a.level, sub), multiply=multiply)

    def _special(self, a: Entry, code: str, state: bool, clock: bool) -> Stmt:
        s = Stmt(None, None, 0, a, (a.level, 0), mergeable=False, code=code)
        s.array = 'state' if state else ('clock' if clock else 'X')
        return s

    def _statements_for(self, a: Entry) -> List[Stmt]:
        space, w = self.space, self.writer
        out: List[Stmt] = []
        if a.kind == 'lookup':
            if a.width == 1 and not a.dims:
                out.append(self._stmt(a, a.base, ('tab', Leaf('TAB', a.tab), ('leaf', Leaf('T'))), 1))
            elif a.width > 0:
                idx = np.arange(a.width, dtype=np.int64)
                out.append(self._stmt(a, a.base + idx, ('tab', Leaf('TAB', a.tab + idx), ('leaf', Leaf('T'))),
                                      a.width))
            return out
        if a.kind == 'farfield':
            # A semi-analytical path reads the clock too: the step being taken
            # is the one from its last record to now.
            call = (f'FARF[{a.farf_index}].release(y, X, t)' if a.farf.farf.laplace
                    else f'FARF[{a.farf_index}].release(y, X)')
            out.append(self._special(a, call, True, False))
            return out
        if a.kind == 'waste_package:hazard':
            W = a.waste

            def at(key: str) -> Tree:
                slot = W.setting.get(key)
                return ('leaf', Leaf('X', slot.base)) if slot is not None else codegen._k(0.0)

            tree = _hazard_tree(W.failure, ('leaf', Leaf('T')), at('fail_from'), at('fail_to'), at('fail_start'),
                                at('fail_rate'), at('fail_scale'), at('fail_shape'))
            for dis in W.disrupted:
                tree = ('bin', '+', tree, ('bin', '*', ('leaf', Leaf('X', dis.D.lambda_slot.base)),
                                           ('leaf', Leaf('X', dis.share.base))))
            out.append(self._stmt(a, a.base, tree, 1))
            return out
        if a.kind == 'event:lambda':
            D = a.event
            if D.timing != 'poisson':
                out.append(self._stmt(a, a.base, codegen._k(0.0), 1))
                return out
            frm = ('leaf', Leaf('X', D.setting['from'].base)) if 'from' in D.setting else ('leaf', Leaf('T0'))
            until = ('leaf', Leaf('X', D.setting['until'].base)) if 'until' in D.setting else ('leaf', Leaf('T1'))
            t = ('leaf', Leaf('T'))
            inside = ('bin', '&&', ('bin', '>=', t, frm), ('bin', '<', t, until))
            rate = ('leaf', Leaf('X', D.setting['rate'].base))
            tree = ('bin', '*', ('leaf', Leaf('DIS', D.index)), ('cond', inside, rate, codegen._k(0.0)))
            out.append(self._stmt(a, a.base, tree, 1))
            return out
        if a.kind == 'waste_package':
            W = a.waste
            if a.width == 0:
                return out
            idx = np.arange(a.width, dtype=np.int64) if a.width > 1 else 0
            tree = ('bin', '+',
                    ('bin', '*', ('bin', '*', ('leaf', Leaf('X', W.hazard_slot.base)),
                                  ('leaf', Leaf('y', W.intact.base + idx))),
                     ('leaf', Leaf('X', W.setting['irf'].base + idx))),
                    ('bin', '*', ('leaf', Leaf('X', W.setting['degradation_rate'].base + idx)),
                     ('leaf', Leaf('y', W.exposed.base + idx))))
            out.append(self._stmt(a, a.base + idx, tree, a.width))
            return out
        if a.get('recorder') is not None:
            rec = a.recorder
            if a.width == 0:
                return out
            k = rec.kind
            lines = []
            if k == 'trigger':
                idx = np.arange(a.width, dtype=np.int64) if a.width > 1 else 0
                tree = ('bin', '-', ('leaf', Leaf('X', rec.aux['first'].base + idx)),
                        ('leaf', Leaf('X', rec.aux['second'].base + idx)))
                out.append(self._stmt(a, a.base + idx, tree, a.width))
                return out
            for off in range(a.width):
                if k == 'min_max':
                    v = f'MEM[{rec.mem + off}].extreme(t, float(X[{rec.aux["target"].base + off}]))'
                elif k == 'running_mean':
                    v = (f'MEM[{rec.mem + off}].mean(t, float(y[{rec.state.base + off}]), '
                         f'float(X[{rec.aux["target"].base + off}]))')
                elif k == 'snapshot':
                    v = f'MEM[{rec.mem + off}].held(t)'
                else:
                    v = f'MEM[{rec.mem + off}].delayed(t, float(X[{rec.aux["delay"].base + off}]))'
                lines.append(f'X[{a.base + off}] = {v}')
            out.append(self._special(a, '\n'.join(lines), True, False))
            return out
        if a.width == 0:
            return out
        if a.width == 1 and not a.dims:
            tree = codegen.resolve(a.asts[0], self.resolver(a, [], None, {}, 1), self.call_resolver(a, [], None, {}))
            out.append(self._stmt(a, a.base, tree, 1))
        elif a.uniform:
            pos = space.positions(a.dims)
            tree = self._resolve_tree(a, a.asts[0], a.dims, pos, None, a.width)
            out.append(self._stmt(a, a.base + np.arange(a.width, dtype=np.int64), tree, a.width))
        else:
            out.extend(self._by_equation(a))
        if a.get('availability') is not None:
            out.extend(self._availability(a))
        return out

    def _resolve_tree(self, a: Entry, ast: Node, dims: Sequence[str], pos: Optional[List[np.ndarray]],
                      tup: Optional[Dict[str, str]], width: int) -> Tree:
        try:
            return codegen.resolve(ast, self.resolver(a, dims, pos, tup, width),
                                   self.call_resolver(a, dims, pos, tup))
        except ValueError as e:
            if isinstance(e, (BuildError, IndexError_)):
                raise
            raise BuildError(str(e), a.name) from None

    def _by_equation(self, a: Entry) -> List[Stmt]:
        space = self.space
        dims = a.dims
        flat = flat_dimensions(space, a)
        if flat:
            try:
                return self._groups(a, set(flat))
            except (BuildError, IndexError_):
                pass
        out = []
        for off in range(a.width):
            tup = tuple_by_list(space, dims, off)
            tree = self._resolve_tree(a, a.asts[off], dims, None, tup, 1)
            out.append(self._stmt(a, a.base + off, tree, 1))
        return out

    def _groups(self, a: Entry, flat_set: Set[str]) -> List[Stmt]:
        space = self.space
        dims = a.dims
        strides = space.strides(dims)
        sizes = [space.size(d) for d in dims]
        varying = [i for i in range(len(dims)) if dims[i] not in flat_set]
        looped = [i for i in range(len(dims)) if dims[i] in flat_set]
        groups = 1
        for i in varying:
            groups *= sizes[i]
        # The looped dimensions' positions, in loop order (outer first).
        if looped:
            grids = np.indices([sizes[i] for i in looped]).reshape(len(looped), -1)
        else:
            grids = np.zeros((0, 1), dtype=np.int64)
        count = grids.shape[1]
        out = []
        for g in range(groups):
            at = [0] * len(dims)
            rest = g
            for k in range(len(varying) - 1, -1, -1):
                i = varying[k]
                at[i] = rest % sizes[i]
                rest //= sizes[i]
            base = a.base + sum(at[i] * strides[i] for i in range(len(dims)))
            ast = a.asts[base - a.base]
            pos = []
            offs = np.full(count, base, dtype=np.int64)
            for i in range(len(dims)):
                if dims[i] in flat_set:
                    p = grids[looped.index(i)].astype(np.int64)
                    offs = offs + p * strides[i]
                else:
                    p = np.full(count, at[i], dtype=np.int64)
                pos.append(p)
            tree = self._resolve_tree(a, ast, dims, pos, None, count)
            out.append(self._stmt(a, offs if count > 1 else int(offs[0]), tree, count))
        return out

    def _availability(self, a: Entry) -> List[Stmt]:
        t = a.block
        src = self.state_by_name.get(t.get('from')) if t.get('from') else None
        if src is None:
            raise BuildError(f"'{t['name']}' has an availability, which is a fraction of what is in the compartment it "
                             'flows out of, and it does not flow out of one.', t['name'])
        scheme = a.availability.scheme
        operands = a.availability.operands
        if a.width == 0:
            return []
        pos = self.space.positions(a.dims)
        idx = np.arange(a.width, dtype=np.int64) if a.width > 1 else 0
        terms = self._availability_terms(t, scheme, src, a, pos)
        amount = _availability_sum(terms)
        ops = {key: ('leaf', Leaf('X', op.base + idx)) for key, op in operands.items()}
        tree = _availability_expression(scheme, amount, ops)
        return [self._stmt(a, a.base + idx, tree, a.width, sub=1, multiply=True)]

    def _availability_terms(self, transfer: Dict[str, Any], scheme: Dict[str, Any], src: Entry, alg: Entry,
                            pos: List[np.ndarray]) -> List[Dict[str, Any]]:
        space = self.space
        base = self.state_offsets(alg.dims, pos, src, transfer['name'], alg.width)
        own = [{'off': base, 'factor': 1.0, 'when': None}]
        if scheme.get('scheme') not in ('shared_limit', 'shared_langmuir'):
            return own
        over = str(scheme.get('over') if scheme.get('over') is not None else '').strip()
        dims = src.dims or []
        which = dims.index(over) if over in dims else -1
        groups = None
        if which < 0 and over and space.has(over):
            grouping = space.get(over)
            for k in range(len(dims)):
                if which >= 0:
                    break
                if not grouping.mapping or grouping.root_name != space.get(dims[k]).root_name:
                    continue
                rel = space.relate(over, dims[k])
                if not rel or rel['kind'] != 'map':
                    continue
                which = k
                groups = rel['table']
        if which < 0:
            return own
        along = dims[which]
        size = space.size(along)
        if not (size > 1):
            return own
        stride = space.strides(dims)[which]
        peer = None
        at = alg.dims.index(along) if along in alg.dims else -1
        if at >= 0:
            peer = pos[at]
        else:
            for k in range(len(alg.dims)):
                rel = space.relate(along, alg.dims[k])
                if rel and rel['kind'] == 'map':
                    peer = rel['table'][pos[k]]
                    break
        if peer is None:
            raise BuildError(f"'{transfer['name']}' shares its amount along '{along}', which the transfer is not "
                             'indexed by, so there is no telling which member of the group each flux belongs to.',
                             transfer['name'])
        first = base - stride * peer
        moles = scheme.get('basis') == 'moles'
        names = space.get(along).enabled
        unit = self.project.simulation.get('time_unit') or 'year'
        seconds_per = TIME_UNITS[unit] * SECONDS_PER_YEAR
        group_at = groups[peer] if groups is not None else None
        terms = []
        for i in range(size):
            if groups is not None and groups[i] < 0:
                continue
            if moles:
                lam_i = lam(names[i]['name'] if i < len(names) else None, unit, self.project.half_lives)
                factor = _moles_per_unit(self.project.decay_unit, lam_i, seconds_per)
            else:
                factor = 1.0
            if factor == 0:
                continue
            terms.append({'off': first + i * stride, 'factor': factor,
                          'when': (group_at, int(groups[i])) if group_at is not None else None})
        return terms

    def state_offsets(self, source_dims: Sequence[str], pos: List[np.ndarray], entry: Optional[Entry], owner: str,
                      width: int) -> Any:
        """Where a state block is read from inside ``source_dims`` (``stateOffsetExpr``)."""
        if entry is None:
            return 0
        if not entry.dims:
            return entry.base if width <= 1 else np.full(width, entry.base, dtype=np.int64)
        try:
            terms = self.space.projection(source_dims, entry.dims, {}, {'owner': owner, 'target': entry.name})
        except IndexError_ as e:
            raise BuildError(str(e), owner) from None
        idx = np.full(max(width, 1), entry.base, dtype=np.int64)
        for term in terms:
            if term.get('fixed') is not None:
                idx += term['fixed'] * term['stride']
                continue
            v = pos[term['from']]
            comp = term['table'][v] if term.get('table') is not None else v
            idx = idx + comp * term['stride']
        return idx if width > 1 else int(idx[0])

    def farf_inlet(self, source_dims: Sequence[str], pos: List[np.ndarray], entry: Entry, owner: str,
                   width: int) -> Any:
        farf = entry.farf
        try:
            terms = self.space.projection(source_dims, entry.dims, {}, {'owner': owner, 'target': entry.name})
        except IndexError_ as e:
            raise BuildError(str(e), owner) from None
        stride = {farf.list_name: 1}
        other_strides = self.space.strides(farf.other_dims)
        for i, d in enumerate(farf.other_dims):
            stride[d] = other_strides[i] * farf.ncells * farf.nnuc
        idx = np.full(max(width, 1), entry.base, dtype=np.int64)
        for term in terms:
            st = stride[term['dim']]
            if term.get('fixed') is not None:
                idx += term['fixed'] * st
                continue
            v = pos[term['from']]
            comp = term['table'][v] if term.get('table') is not None else v
            idx = idx + comp * st
        return idx if width > 1 else int(idx[0])

    # --- which slots move --------------------------------------------------------------------

    def _classes(self) -> None:
        on_state: Set[str] = set()
        on_clock: Set[str] = set()
        for a in self.algebraic:
            state = clock = False
            for s in self.alg_stmts[a.name]:
                if s.code is not None:
                    state = state or s.array == 'state'
                    clock = clock or s.array == 'clock'
                    continue
                for leaf in codegen.leaves(s.tree):
                    if leaf.kind == 'y':
                        state = True
                    elif leaf.kind in ('T', 'T0', 'T1', 'TAB', 'DIS'):
                        clock = True
            for d in a.reads_alg:
                if d in on_state:
                    state = True
                if d in on_clock:
                    clock = True
            if state:
                on_state.add(a.name)
            if clock:
                on_clock.add(a.name)
        slot_class = np.zeros(max(1, self.nalg), dtype=np.uint8)
        self.pass_stmts: Dict[int, List[Stmt]] = {0: [], 1: [], 2: []}
        for a in self.algebraic:
            cls = 2 if a.name in on_state else (1 if a.name in on_clock else 0)
            a.cls = cls
            slot_class[a.base:a.base + a.width] = cls
            for s in self.alg_stmts[a.name]:
                if s.code is not None:
                    s.array = 'X'
                self.pass_stmts[cls].append(s)
        self.slot_class = slot_class
        self.on_state = on_state
        self.on_clock = on_clock

    # --- the derivative ------------------------------------------------------------------------

    def family_of(self, dims: Sequence[str], pos: List[np.ndarray], width: int) -> np.ndarray:
        """Which budget family each element of a loop over ``dims`` is in (``familyExpr``)."""
        nfam = self.budget['nfam']  # type: ignore[index]
        k = next((i for i, d in enumerate(dims) if self.is_nuclide_dim(d)), -1)
        if k < 0:
            return np.full(width, nfam - 1, dtype=np.int64)
        if dims[k] == self.material_list:
            return pos[k].astype(np.int64)
        rel = self.space.relate(self.material_list, dims[k])  # type: ignore[arg-type]
        table = rel['table'] if rel else np.full(self.space.size(dims[k]), -1)
        fam = table[pos[k]]
        return np.where(fam < 0, nfam - 1, fam).astype(np.int64)

    def endpoint_family(self, entry: Entry, dims: Sequence[str], pos: List[np.ndarray], width: int) -> np.ndarray:
        if any(self.is_nuclide_dim(d) for d in entry.dims):
            return self.family_of(dims, pos, width)
        return np.full(width, self.budget['nfam'] - 1, dtype=np.int64)  # type: ignore[index]

    def family_key(self, entry: Entry, dims: Sequence[str]) -> str:
        """The family of an endpoint as the application writes it: 'loop' for a
        position read off the loop, 'unindexed' for the constant."""
        if any(self.is_nuclide_dim(d) for d in entry.dims) and any(self.is_nuclide_dim(d) for d in dims):
            return 'loop'
        return 'unindexed'

    def budget_at(self, term: str, fam: np.ndarray) -> np.ndarray:
        b = self.budget
        return b['base'] + BUDGET_TERMS.index(term) * b['nfam'] + fam  # type: ignore[index]

    def _assembly(self) -> None:
        """The derivative as phases of (target, value) contributions, each phase's
        in the order the application adds them."""
        space, project = self.space, self.project
        budget = self.budget
        ph = self.phases = []

        # Transfers: F = rate, times the donor where it multiplies by it.
        rate_idx: List[np.ndarray] = []
        mbd_mask: List[np.ndarray] = []
        src_idx: List[np.ndarray] = []
        contrib_flux: List[np.ndarray] = []
        contrib_sign: List[np.ndarray] = []
        contrib_tgt: List[np.ndarray] = []
        nflux = 0
        # What flows into each semi-analytical path, term by term: the
        # release reads it at the same instant (``laplaceLines``).
        laplace_in: Dict[int, List[Tuple[np.ndarray, np.ndarray, np.ndarray]]] = {}
        for t in project.transfers:
            alg = self.alg_by_name[t['qname']]
            src = self.state_by_name.get(t.get('from')) if t.get('from') else None
            tgt = self.state_by_name.get(t.get('to')) if t.get('to') else None
            path = self.path_by_name.get(t.get('to')) if t.get('to') and tgt is None else None
            mbd = t.get('multiply_by_donor') is not False
            if mbd and src is None:
                raise BuildError('A transfer with no source compartment cannot be multiplied by its donor; set '
                                 '"multiply_by_donor": false to give an absolute flux.', t['name'])
            W = alg.width
            if W == 0 or any(space.size(d) == 0 for d in alg.dims):
                continue
            pos = space.positions(alg.dims) if alg.dims else []
            k = np.arange(nflux, nflux + W, dtype=np.int64)
            nflux += W
            rate_idx.append(alg.base + np.arange(W, dtype=np.int64))
            s_off = _as_array(self.state_offsets(alg.dims, pos, src, t['name'], W), W) if src else None
            g_off = _as_array(self.state_offsets(alg.dims, pos, tgt, t['name'], W), W) if tgt else None
            p_off = _as_array(self.farf_inlet(alg.dims, pos, path, t['name'], W), W) if path else None
            if path is not None and path.farf.laplace:
                donor = s_off if mbd and s_off is not None else np.full(W, -1, dtype=np.int64)
                laplace_in.setdefault(path.farf_index, []).append(
                    (p_off - path.base, alg.base + np.arange(W, dtype=np.int64), donor))
            mbd_mask.append(np.full(W, mbd))
            src_idx.append(s_off if s_off is not None else np.full(W, -1, dtype=np.int64))
            cols_t: List[np.ndarray] = []
            cols_s: List[np.ndarray] = []
            cols_f: List[np.ndarray] = []
            if src is not None:
                cols_t.append(s_off)
                cols_s.append(np.full(W, -1.0))
            if tgt is not None:
                cols_t.append(g_off)
                cols_s.append(np.full(W, 1.0))
            if path is not None:
                cols_t.append(p_off)
                cols_s.append(np.full(W, 1.0))
            if budget is not None:
                f_s = self.endpoint_family(src, alg.dims, pos, W) if src else None
                f_t = self.endpoint_family(tgt, alg.dims, pos, W) if tgt else None
                if src is not None and tgt is None:
                    cols_t.append(self.budget_at('out', f_s))
                    cols_s.append(np.full(W, 1.0))
                if src is None and tgt is not None and t.get('from') not in self.waste_by_name:
                    cols_t.append(self.budget_at('in', f_t))
                    cols_s.append(np.full(W, 1.0))
                if src is not None and tgt is not None and (
                        self.family_key(src, alg.dims) != self.family_key(tgt, alg.dims)):
                    # The application compares the two families as written,
                    # when it generates the code, not as they come out: one
                    # endpoint with a nuclide dimension and one without is a
                    # move between families at every index, even where the
                    # loop happens to be at the unindexed family's number.
                    cols_t.append(self.budget_at('between', f_s))
                    cols_s.append(np.full(W, -1.0))
                    cols_t.append(self.budget_at('between', f_t))
                    cols_s.append(np.full(W, 1.0))
            if not cols_t:
                continue
            T = np.stack(cols_t, axis=1)
            S = np.stack(cols_s, axis=1)
            Fk = np.repeat(k[:, None], T.shape[1], axis=1)
            keep = (T >= 0).ravel()
            contrib_tgt.append(T.ravel()[keep])
            contrib_sign.append(S.ravel()[keep])
            contrib_flux.append(Fk.ravel()[keep])
        # A semi-analytical path's release leaves what it holds: a flux out of
        # each held state at the rate of its release slot, taken from no donor.
        for p in self.farf_layout:
            if not p.farf.laplace:
                continue
            F = self.FARF[p.farf_index]
            W = F.slots
            if W == 0:
                continue
            k = np.arange(nflux, nflux + W, dtype=np.int64)
            nflux += W
            rate_idx.append(F.release_slots.copy())
            mbd_mask.append(np.zeros(W, dtype=bool))
            src_idx.append(np.full(W, -1, dtype=np.int64))
            contrib_tgt.append(F.held_idx.copy())
            contrib_sign.append(np.full(W, -1.0))
            contrib_flux.append(k)
        self.nflux = nflux
        if nflux:
            self.flux_rate = np.concatenate(rate_idx)
            mbd = np.concatenate(mbd_mask)
            self.flux_mbd = np.nonzero(mbd)[0].astype(np.int64)
            self.flux_mbd_src = np.concatenate(src_idx)[self.flux_mbd]
            ph.append(('transfers', np.concatenate(contrib_tgt) if contrib_tgt else np.zeros(0, dtype=np.int64),
                       np.concatenate(contrib_flux) if contrib_flux else np.zeros(0, dtype=np.int64),
                       np.concatenate(contrib_sign) if contrib_sign else np.zeros(0)))
        else:
            self.flux_rate = np.zeros(0, dtype=np.int64)
            self.flux_mbd = np.zeros(0, dtype=np.int64)
            self.flux_mbd_src = np.zeros(0, dtype=np.int64)

        # Inflows: + rate into the target (or a path's inlet), and 'in' to the budget.
        tg: List[np.ndarray] = []
        xs: List[np.ndarray] = []
        for s in project.inflows:
            alg = self.alg_by_name[s['qname']]
            tgt = self.state_by_name.get(s.get('to'))
            path = None if tgt is not None else self.path_by_name.get(s.get('to'))
            W = alg.width
            if W == 0 or any(space.size(d) == 0 for d in alg.dims):
                continue
            pos = space.positions(alg.dims) if alg.dims else []
            target = (_as_array(self.state_offsets(alg.dims, pos, tgt, s['name'], W), W) if tgt is not None
                      else _as_array(self.farf_inlet(alg.dims, pos, path, s['name'], W), W))
            rate = alg.base + np.arange(W, dtype=np.int64)
            if path is not None and path.farf.laplace:
                laplace_in.setdefault(path.farf_index, []).append(
                    (target - path.base, rate.copy(), np.full(W, -1, dtype=np.int64)))
            cols_t = [target]
            cols_x = [rate]
            if budget is not None and tgt is not None:
                cols_t.append(self.budget_at('in', self.endpoint_family(tgt, alg.dims, pos, W)))
                cols_x.append(rate)
            tg.append(np.stack(cols_t, axis=1).ravel())
            xs.append(np.stack(cols_x, axis=1).ravel())
        if tg:
            ph.append(('x', np.concatenate(tg), np.concatenate(xs)))
        for p in self.farf_layout:
            if not p.farf.laplace:
                continue
            terms = laplace_in.get(p.farf_index, [])
            empty = np.zeros(0, dtype=np.int64)
            self.FARF[p.farf_index].set_inflow(
                np.concatenate([q[0] for q in terms]) if terms else empty,
                np.concatenate([q[1] for q in terms]) if terms else empty,
                np.concatenate([q[2] for q in terms]) if terms else empty)

        # Waste packages: fail out of the intact inventory, fail - release into the exposed.
        for W in self.waste_layout:
            if W.width == 0:
                continue
            Pd = W.intact
            pos = space.positions(Pd.dims) if Pd.dims else []
            carried = any(t.get('from') == W.q and t.get('to') is not None and t.get('to') in self.state_by_name
                          for t in project.transfers)
            idx = np.arange(W.width, dtype=np.int64)
            out_budget = (self.budget_at('out', self.family_of(Pd.dims, pos, W.width))
                          if budget is not None and not carried else None)
            ph.append(('waste', Pd.base + idx, W.exposed.base + idx, W.hazard_slot.base, W.release_slot.base + idx,
                       out_budget))

        # Disruptive events: the count, and moves at the expected-value rate.
        for D in self.disruption_layout:
            ph.append(('x', np.array([D.entry.base], dtype=np.int64), np.array([D.lambda_slot.base], dtype=np.int64)))
            for k, a in enumerate(D.actions):
                if a['kind'] != 'move':
                    continue
                A, B = self._move_ends(D, a)
                if A.width == 0:
                    continue
                pos = space.positions(A.dims) if A.dims else []
                idx = np.arange(A.width, dtype=np.int64)
                if B is not None:
                    second = B.base + idx
                elif budget is not None:
                    second = self.budget_at('out', self.family_of(A.dims, pos, A.width))
                else:
                    second = None
                ph.append(('move', A.base + idx, second, D.lambda_slot.base, D.shares[k].base))

        # Explicit dy/dt terms.
        tg, xs = [], []
        for slot in self.dydt_slots:
            st = self.state_by_name[slot.state_name]
            if slot.width == 0:
                continue
            pos = space.positions(slot.dims) if slot.dims else []
            idx = np.arange(slot.width, dtype=np.int64)
            cols_t = [st.base + idx]
            cols_x = [slot.base + idx]
            if budget is not None:
                cols_t.append(self.budget_at('explicit', self.endpoint_family(st, slot.dims, pos, slot.width)))
                cols_x.append(slot.base + idx)
            tg.append(np.stack(cols_t, axis=1).ravel())
            xs.append(np.stack(cols_x, axis=1).ravel())
        if tg:
            ph.append(('x', np.concatenate(tg), np.concatenate(xs)))

        # Running means: dS/dt = target while recording.
        for rec in self.recorders:
            if rec.kind != 'running_mean' or rec.width == 0:
                continue
            idx = np.arange(rec.width, dtype=np.int64)
            ph.append(('mean', rec.state.base + idx, rec.aux['target'].base + idx, rec.mem))

        # Decay and ingrowth, per decaying state block, along its nuclide list.
        self.decay_lists: List[str] = []
        decay_index: Dict[str, int] = {}

        def decay_slot(list_name: str) -> int:
            if list_name not in decay_index:
                decay_index[list_name] = len(self.decay_lists)
                self.decay_lists.append(list_name)
            return decay_index[list_name]

        self.decaying: List[Entry] = []
        for s in self.states:
            if s.kind not in ('compartment', 'waste_package'):
                continue
            if s.block.get('handle_decay') is False or not self.material_list:
                continue
            m = next((i for i, d in enumerate(s.dims) if self.is_nuclide_dim(d)), -1)
            if m < 0:
                continue
            self.decaying.append(Entry(state=s, m=m, slot=decay_slot(s.dims[m])))
        tables = {}
        for lst in self.decay_lists:
            model = self.decay if lst == self.material_list else project.decay_model_for(lst)
            tables[lst] = decay_tables(model, space.size(lst))
        tg, sc, sr = [], [], []
        for d in self.decaying:
            s = d.state
            if s.width == 0:
                continue
            D = tables[s.dims[d.m]]
            pos = space.positions(s.dims)
            stride_m = space.strides(s.dims)[d.m]
            nm = pos[d.m]
            si = s.base + np.arange(s.width, dtype=np.int64)
            lam_v = D['lam'][nm]
            fam = self.family_of(s.dims, pos, s.width) if budget is not None else None
            # Per state, in order: decay, [budget decay], then each parent's
            # ingrowth, [budget ingrowth].
            cnt = D['icnt'][nm]
            ncols = 1 + (1 if budget is not None else 0) + int(cnt.max() if cnt.size else 0) * (
                2 if budget is not None else 1)
            T = np.full((s.width, ncols), -1, dtype=np.int64)
            C = np.zeros((s.width, ncols))
            R = np.zeros((s.width, ncols), dtype=np.int64)
            T[:, 0] = si
            C[:, 0] = -lam_v
            R[:, 0] = si
            col = 1
            if budget is not None:
                T[:, 1] = self.budget_at('decay', fam)
                C[:, 1] = lam_v
                R[:, 1] = si
                col = 2
            maxc = int(cnt.max()) if cnt.size else 0
            for q in range(maxc):
                has = cnt > q
                o = D['ioff'][nm] + q
                o = np.where(has, o, 0)
                coef = D['icoef'][o] if D['icoef'].size else np.zeros(s.width)
                par = D['ipar'][o] if D['ipar'].size else np.zeros(s.width, dtype=np.int64)
                src = si + (par - nm) * stride_m
                T[:, col] = np.where(has, si, -1)
                C[:, col] = coef
                R[:, col] = np.where(has, src, 0)
                col += 1
                if budget is not None:
                    T[:, col] = np.where(has, self.budget_at('ingrowth', fam), -1)
                    C[:, col] = coef
                    R[:, col] = np.where(has, src, 0)
                    col += 1
            keep = (T >= 0).ravel()
            tg.append(T.ravel()[keep])
            sc.append(C.ravel()[keep])
            sr.append(R.ravel()[keep])
        if tg:
            ph.append(('coef', np.concatenate(tg), np.concatenate(sc), np.concatenate(sr)))

        # Far-field paths: transport inside, then decay along their chain.
        for p in self.farf_layout:
            dec = None
            if p.block.get('handle_decay') is not False and p.farf.list_name:
                p.decay_slot = decay_slot(p.farf.list_name)
                if p.farf.list_name not in tables:
                    model = (self.decay if p.farf.list_name == self.material_list
                             else project.decay_model_for(p.farf.list_name))
                    tables[p.farf.list_name] = decay_tables(model, space.size(p.farf.list_name))
                dec = tables[p.farf.list_name]
            else:
                p.decay_slot = None
            F = self.FARF[p.farf_index]
            if p.farf.laplace:
                # The whole table: the path is solved along the chain itself.
                F.set_decay(None if dec is None else dec['lam'], None if dec is None else {
                    'lam': [float(v) for v in dec['lam']], 'ioff': [int(v) for v in dec['ioff']],
                    'icnt': [int(v) for v in dec['icnt']], 'ipar': [int(v) for v in dec['ipar']],
                    'icoef': [float(v) for v in dec['icoef']]})
            else:
                # The matched layers resolve the thinnest profile any nuclide on
                # the path has, and one that decays fast has a thin one.
                F.set_decay(dec['lam'] if dec is not None else None)
                ph.append(('farf', p.farf_index))
            if dec is not None:
                nnuc = p.farf.nnuc
                starts = F.cell_starts
                si = (starts[:, None] + np.arange(nnuc)[None, :]).ravel()
                m = np.tile(np.arange(nnuc), len(starts))
                maxc = int(dec['icnt'].max()) if dec['icnt'].size else 0
                T = np.full((si.size, 1 + maxc), -1, dtype=np.int64)
                C = np.zeros((si.size, 1 + maxc))
                R = np.zeros((si.size, 1 + maxc), dtype=np.int64)
                T[:, 0] = si
                C[:, 0] = -dec['lam'][m]
                R[:, 0] = si
                for q in range(maxc):
                    has = dec['icnt'][m] > q
                    o = np.where(has, dec['ioff'][m] + q, 0)
                    T[:, 1 + q] = np.where(has, si, -1)
                    C[:, 1 + q] = dec['icoef'][o] if dec['icoef'].size else 0.0
                    base_cell = si - m
                    R[:, 1 + q] = np.where(has, base_cell + (dec['ipar'][o] if dec['ipar'].size else 0), 0)
                keep = (T >= 0).ravel()
                ph.append(('coef', T.ravel()[keep], C.ravel()[keep], R.ravel()[keep]))
        self.DEC_tables = tables

    def _move_ends(self, D: Entry, a: Dict[str, Any]) -> Tuple[Entry, Optional[Entry]]:
        A = self.state_by_name.get(a.get('from'))
        if A is None:
            raise BuildError(f"'{a.get('from')}' is not a compartment, so there is nothing to move out of it.", D.q)
        B = self.state_by_name.get(a['to']) if a.get('to') else None
        if a.get('to') and B is None:
            raise BuildError(f"'{a['to']}' is not a compartment, so nothing can be moved into it.", D.q)
        if B is not None and (B.width != A.width or ','.join(B.dims) != ','.join(A.dims)):
            fa = ' × '.join(A.dims) or 'by nothing'
            fb = ' × '.join(B.dims) or 'by nothing'
            raise BuildError(f"'{a['from']}' and '{a['to']}' are indexed differently ({fa} against {fb}). An event "
                             'moves a share cell for cell, so the two have to match.', D.q)
        return A, B

    # --- jumps -------------------------------------------------------------------------------

    def _fail_code(self, W: Entry, share: str, lines: List[str]) -> None:
        space, project, w = self.space, self.project, self.writer
        Pd, M = W.intact, W.exposed
        carrier = next((t for t in project.transfers if t.get('from') == W.q), None)
        tgt = self.state_by_name.get(carrier['to']) if carrier and carrier.get('to') else None
        path = self.path_by_name.get(carrier['to']) if carrier and carrier.get('to') and tgt is None else None
        if W.width == 0:
            return
        pos = space.positions(Pd.dims) if Pd.dims else []
        idx = np.arange(W.width, dtype=np.int64)
        P_i = w.index(Pd.base + idx)
        M_i = w.index(M.base + idx)
        irf_i = w.index(W.setting['irf'].base + idx)
        lines.append(f'fail = {share} * y[{P_i}]')
        lines.append(f'irf = X[{irf_i}]')
        lines.append(f'y[{P_i}] -= fail')
        lines.append(f'y[{M_i}] += fail * (1 - irf)')
        if tgt is not None:
            to = _as_array(self.state_offsets(Pd.dims, pos, tgt, carrier['name'], W.width), W.width)
            lines.append(f'np.add.at(y, {w.bind(to)}, fail * irf)')
        elif path is not None:
            to = _as_array(self.farf_inlet(Pd.dims, pos, path, carrier['name'], W.width), W.width)
            lines.append(f'np.add.at(y, {w.bind(to)}, fail * irf)')
        if self.budget is not None and tgt is None:
            to = self.budget_at('out', self.family_of(Pd.dims, pos, W.width))
            lines.append(f'np.add.at(y, {w.bind(to)}, fail * irf)')

    def _jumps(self) -> None:
        self.jump_specs: List[Dict[str, Any]] = []
        for W in self.waste_layout:
            if W.failure != 'at':
                continue
            lines: List[str] = []
            self._fail_code(W, '1.0', lines)
            self.jump_specs.append({'name': W.q, 'slot': W.setting['fail_at'].base,
                                    'text': str(W.block.get('fail_at') if W.block.get('fail_at') is not None else ''),
                                    'code': lines})
        for D in self.disruption_layout:
            lines = [f'y[{D.entry.base}] += 1']
            for k, a in enumerate(D.actions):
                share = f'X[{D.shares[k].base}]'
                if a['kind'] == 'fail':
                    self._fail_code(self.waste_by_name[a['block']], share, lines)
                    continue
                A, B = self._move_ends(D, a)
                if A.width == 0:
                    continue
                pos = self.space.positions(A.dims) if A.dims else []
                idx = np.arange(A.width, dtype=np.int64)
                A_i = self.writer.index(A.base + idx)
                lines.append(f'm = {share} * y[{A_i}]')
                lines.append(f'y[{A_i}] -= m')
                if B is not None:
                    lines.append(f'y[{self.writer.index(B.base + idx)}] += m')
                elif self.budget is not None:
                    to = self.budget_at('out', self.family_of(A.dims, pos, A.width))
                    lines.append(f'np.add.at(y, {self.writer.bind(to)}, m)')
            spec = {'name': D.q, 'code': lines, 'index': D.index}
            if D.timing == 'at':
                spec.update(slot=D.setting['at'].base, text=str(D.block.get('at') if D.block.get('at') is not None
                                                                 else ''))
            else:
                spec.update(slot=None)
            self.jump_specs.append(spec)

    def _decay_tables(self) -> None:
        self.DEC = [self.DEC_tables[lst] for lst in self.decay_lists]

    # --- initial state ------------------------------------------------------------------------

    def _initial_state(self) -> None:
        space, project = self.space, self.project
        invariant = time_invariant_algebraic(self.algebraic, self.alg_by_name, self.state_by_name)
        used: Set[str] = set()
        stmts: List[Stmt] = []
        for s in self.states:
            if s.kind in ('farfield', 'budget', 'event'):
                continue
            if s.kind == 'waste_package' and s.role != 'intact':
                continue
            key = 'inventory' if s.kind == 'waste_package' else 'initial'
            parsed: Dict[str, Node] = {}
            for off in range(s.width):
                tup = space.pin_scenario(s.block.get('index_lists') or [], tuple_by_list(space, s.dims, off))
                v = value_at(s.block, key, tup)
                eq = _js_str(v if v is not None else '0')

                def resolve(name: str, indices: Any, node: Optional[Node] = None, _s: Entry = s,
                            _tup: Dict[str, str] = tup) -> Leaf:
                    def reachable(n: str) -> bool:
                        return n in self.param_by_name or n in invariant
                    q = resolve_reference(name, _s.system or '', reachable)
                    pr = (self.param_by_name.get(q) or self.alg_by_name.get(q)) if q else None
                    if pr is None:
                        raise BuildError(why_not_initial(name, _s, self.alg_by_name, self.state_by_name), _s.name)
                    store = 'P' if q in self.param_by_name else 'X'
                    if store == 'X':
                        used.add(q)  # type: ignore[arg-type]
                    if not pr.dims:
                        return Leaf(store, pr.base)
                    here = {COMPARTMENT_LIST: _s.name}
                    t = {**here, **_tup, **pin_indices(space, pr, indices, name, _s.name, here)}
                    strides = space.strides(pr.dims)
                    o = 0
                    for i, dim in enumerate(pr.dims):
                        p = position_in(space, dim, t)
                        if p is None:
                            if dim == TRANSFER_LIST:
                                msg = (f"'{name}' has a value per transfer, and a compartment is not a transfer. Name "
                                       f"one, as '{name}[<transfer>]'.")
                            else:
                                msg = (f"'{name}' is indexed by '{dim}', which the initial condition of '{_s.name}' "
                                       'cannot resolve. Give an explicit index.')
                            raise BuildError(msg, _s.name)
                        o += p * strides[i]
                    return Leaf(store, pr.base + o)

                ast = parsed.get(eq)
                try:
                    if ast is None:
                        ast = self.parse_equation(eq, s.block.get('system') or '', s.name)
                        parsed[eq] = ast
                    tree = codegen.resolve(ast, resolve)
                except ParseError as e:
                    raise BuildError(f'{e} in initial condition "{eq}"', s.name) from None
                except ValueError as e:
                    if isinstance(e, (BuildError, IndexError_)):
                        raise
                    raise BuildError(str(e), s.name) from None
                stmts.append(Stmt(s.base + off, tree, 1, None, (0, 0), array='y0'))
        before: List[Stmt] = []
        if used:
            wanted = set(used)
            for a in reversed(self.algebraic):
                if a.name in wanted:
                    wanted.update(a.reads_alg)
            for a in self.algebraic:
                if a.name in wanted:
                    before.extend(self.alg_stmts[a.name])
        self.initial_before = before
        self.initial_stmts = stmts


# --- small pieces ------------------------------------------------------------------------------

def _as_array(v: Any, width: int) -> np.ndarray:
    if np.ndim(v) == 0:
        return np.full(width, int(v), dtype=np.int64)
    return np.asarray(v, dtype=np.int64)


def _js_number(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        low = s.lower()
        if low in ('infinity', '+infinity'):
            return math.inf
        if low == '-infinity':
            return -math.inf
        return math.nan


def _js_str(v: Any) -> str:
    """``String(v)`` for what a model file holds: numbers as JavaScript prints them."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        from ..jsonio import js_number
        return js_number(v)
    return str(v)


def _hazard_tree(failure: str, t: Tree, frm: Tree, to: Tree, start: Tree, rate: Tree, scale: Tree,
                 shape: Tree) -> Tree:
    K = codegen._k
    if failure == 'uniform':
        width = ('call', 'max', [('bin', '-', to, t), ('bin', '*', K(WINDOW_TAIL), ('call', 'abs', [
            ('bin', '-', to, frm)]))])
        return ('cond', ('bin', '<', t, frm), K(0.0), ('bin', '/', K(1.0), width))
    if failure == 'exponential':
        return ('cond', ('bin', '<', t, start), K(0.0), rate)
    if failure == 'weibull':
        age = ('call', 'max', [('bin', '-', t, start), ('bin', '*', K(1e-12), ('call', 'abs', [scale]))])
        powr = ('call', 'power', [('bin', '/', age, scale), ('bin', '-', shape, K(1.0))])
        return ('cond', ('bin', '<', t, start), K(0.0), ('bin', '*', ('bin', '/', shape, scale), powr))
    return K(0.0)


def _moles_per_unit(decay_unit: str, lam_per_time_unit: float, seconds_per_time_unit: float) -> float:
    if decay_unit == 'mol':
        return 1.0
    per_second = lam_per_time_unit / seconds_per_time_unit
    if not (per_second > 0):
        return 0.0
    return 1 / (per_second * AVOGADRO_AVAILABILITY)


def _availability_sum(terms: List[Dict[str, Any]]) -> Tree:
    if not terms:
        return codegen._k(0.0)
    parts: List[Tree] = []
    for term in terms:
        read: Tree = ('leaf', Leaf('y', term['off']))
        if term['factor'] != 1:
            read = ('bin', '*', codegen._k(term['factor']), read)
        if term['when'] is not None:
            group_at, value = term['when']
            test = ('bin', '==', ('leaf', Leaf('K', np.asarray(group_at, dtype=float))), codegen._k(float(value)))
            read = ('cond', test, read, codegen._k(0.0))
        parts.append(read)
    if len(parts) == 1:
        return parts[0]
    out = parts[0]
    for p in parts[1:]:
        out = ('bin', '+', out, p)
    return out


def _availability_expression(scheme: Dict[str, Any], amount: Tree, ops: Dict[str, Tree]) -> Tree:
    K = codegen._k
    if scheme['scheme'] in ('limit', 'shared_limit'):
        body: Tree = ('cond', ('bin', '>', amount, K(0.0)),
                      ('call', 'min', [('bin', '/', ops['limit'], amount), K(1.0)]), K(1.0))
    else:
        a, b = ops['top'], ops['bottom']
        body = ('cond', ('bin', '~=', ('bin', '+', amount, b), K(0.0)),
                ('bin', '/', ('bin', '+', amount, a), ('bin', '+', amount, b)), K(1.0))
    if scheme.get('unavailable'):
        return ('bin', '-', K(1.0), body)
    return body


def _scale_literals(ast: Node, builder: '_Builder', system: str) -> None:
    """Scales a literal written with a unit to the unit it is added to (see
    :mod:`kompartment.engine.unitcheck`)."""
    if not _has_unit_literal(ast):
        return
    from .unitcheck import parse_unit, scale_literals
    time_dim = parse_unit(builder.project.simulation.get('time_unit') or 'year')

    def unit_of(written: str) -> Any:
        q = resolve_reference(str(written), system or '', lambda n: n in builder.unit_blocks)
        text = builder.unit_blocks[q].get('unit') if q else None
        return parse_unit(text) if text else None

    scale_literals(ast, unit_of, time_dim)


def _has_unit_literal(node: Node) -> bool:
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == 'num':
            if n.unit is not None:  # type: ignore[attr-defined]
                return True
        elif n.type == 'call':
            stack.extend(n.args)  # type: ignore[attr-defined]
        elif n.type == 'unary':
            stack.append(n.operand)  # type: ignore[attr-defined]
        elif n.type == 'binary':
            stack.extend((n.left, n.right))  # type: ignore[attr-defined]
        elif n.type == 'cond':
            stack.extend((n.test, n.then, n.otherwise))  # type: ignore[attr-defined]
    return False
