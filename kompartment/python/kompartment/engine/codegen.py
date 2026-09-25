"""From equation trees to numpy code.

The application compiles each equation to a JavaScript expression per index
and runs the loops; here an equation is evaluated for every index it is
written at in one numpy expression. The steps:

1. :func:`resolve` turns a parsed equation into an *expression tree* whose
   leaves are resolved: a slot of the state (``y``), of the parameters
   (``P``), of the algebraic values (``X``), a number (``K``), the clock
   (``T``) -- each leaf holding one index, or an array of them, one per
   element the statement computes. Subtrees made of numbers alone are folded
   here, with JavaScript's arithmetic (``1/0`` is ``inf``).
2. Statements whose trees have the same shape -- the same operations, the
   same kinds of leaf -- and that do not read one another can be *merged*:
   their leaves' index arrays are concatenated, and one numpy expression then
   computes them all (:func:`merge`). A model of a thousand scalar
   expressions that are all ``a * b`` is one multiplication of two gathered
   arrays, not a thousand.
3. :class:`CodeWriter` writes a statement out as Python source over numpy.

The operations keep JavaScript's meaning: comparisons give 1 or 0, ``&&`` and
``||`` treat anything non-zero (NaN included) as true, ``a ? b : c`` tests
``a != 0``, ``^`` is ``Math.pow`` (so ``1^NaN`` is NaN, not 1), ``round``
takes halves up. Division by zero and the like are left to IEEE arithmetic,
evaluated under ``np.errstate(all='ignore')``.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from .functions import FUNCTIONS, FUNCTION_ALIASES, js_round
from .lang import Binary, Call, Cond, Node, Num, Ref, Unary

Index = Union[int, np.ndarray]


class Leaf:
    """One operand of a statement.

    ``kind`` is ``'y'``, ``'P'``, ``'X'`` (an array read at ``index``),
    ``'K'`` (a number, or an array of them, in ``index``), ``'T'``, ``'T0'``,
    ``'T1'`` (the clock, the run's start and end), ``'TAB'`` (the lookup
    table at ``index``), ``'DIS'`` (an event's expected-value switch at
    ``index``).
    """

    __slots__ = ('kind', 'index')

    def __init__(self, kind: str, index: Any = None) -> None:
        self.kind = kind
        self.index = index

    def __repr__(self) -> str:
        return f'Leaf({self.kind}, {self.index!r})'


# An expression tree is nested tuples:
#   ('leaf', Leaf)
#   ('neg', a)
#   ('bin', op, a, b)        op in + - * / ^ < <= > >= == ~= && ||
#   ('cond', test, a, b)
#   ('call', key, [args])    a built-in function, by its canonical name
#   ('tab', Leaf, arg)       a lookup table read at an argument
Tree = Tuple[Any, ...]

INLINE_NUMPY = {
    'abs': 'np.abs', 'sqrt': 'np.sqrt', 'exp': 'np.exp', 'log': 'np.log', 'log10': 'np.log10',
    'log2': 'np.log2', 'sin': 'np.sin', 'cos': 'np.cos', 'tan': 'np.tan', 'sinh': 'np.sinh',
    'cosh': 'np.cosh', 'tanh': 'np.tanh', 'asin': 'np.arcsin', 'acos': 'np.arccos', 'atan': 'np.arctan',
    'ceil': 'np.ceil', 'floor': 'np.floor', 'sign': 'np.sign', 'atan2': 'np.arctan2', 'hypot': 'np.hypot',
}


def js_pow(a: Any, b: Any) -> Any:
    """``Math.pow``: as C's ``pow`` except that 1 and -1 to an infinite or NaN
    power are NaN."""
    r = np.power(a, b)
    bad = (np.abs(a) == 1) & ~np.isfinite(b)
    if np.ndim(bad):
        if bad.any():
            r = np.where(bad, np.nan, r)
        return r
    return np.nan if bad else r


def _fold(tree: Tree) -> Optional[float]:
    """The value of a tree made of numbers alone, else None."""
    if tree[0] == 'leaf':
        leaf = tree[1]
        return float(leaf.index) if leaf.kind == 'K' and np.ndim(leaf.index) == 0 else None
    return None


def _k(value: float) -> Tree:
    return ('leaf', Leaf('K', float(value)))


def _evaluate_constant(tree: Tree) -> Optional[float]:
    """Folds a node whose children are all numbers, with numpy's arithmetic."""
    with np.errstate(all='ignore'):
        kind = tree[0]
        if kind == 'neg':
            v = _fold(tree[1])
            return None if v is None else float(-np.float64(v))
        if kind == 'bin':
            a, b = _fold(tree[2]), _fold(tree[3])
            if a is None or b is None:
                return None
            return float(apply_binary(tree[1], np.float64(a), np.float64(b)))
        if kind == 'cond':
            t = _fold(tree[1])
            if t is None:
                return None
            branch = tree[2] if t != 0 else tree[3]
            return _fold(branch)
        if kind == 'call':
            vals = [_fold(a) for a in tree[2]]
            if any(v is None for v in vals):
                return None
            spec = FUNCTIONS[tree[1]]
            if spec.get('needsContext'):
                return None
            try:
                return float(call_value(tree[1], [np.float64(v) for v in vals]))
            except Exception:  # noqa: BLE001 - left for run time, where it raises in place
                return None
    return None


def apply_binary(op: str, a: Any, b: Any) -> Any:
    if op == '+':
        return a + b
    if op == '-':
        return a - b
    if op == '*':
        return a * b
    if op == '/':
        return a / b
    if op == '^':
        return js_pow(a, b)
    if op == '<':
        return (a < b) * 1.0
    if op == '<=':
        return (a <= b) * 1.0
    if op == '>':
        return (a > b) * 1.0
    if op == '>=':
        return (a >= b) * 1.0
    if op == '==':
        return (a == b) * 1.0
    if op == '~=':
        return (a != b) * 1.0
    if op == '&&':
        return ((a != 0) & (b != 0)) * 1.0
    if op == '||':
        return ((a != 0) | (b != 0)) * 1.0
    raise ValueError(f"Cannot evaluate operator '{op}'")


def call_value(key: str, args: Sequence[Any]) -> Any:
    """A built-in function applied to values, as the emitted code applies it."""
    if key == 'if':
        return np.where(np.asarray(args[0]) != 0, args[1], args[2] if len(args) > 2 else 0.0)
    if key == 'not':
        return (np.asarray(args[0]) == 0) * 1.0
    if key == 'min':
        out = args[0]
        for a in args[1:]:
            out = np.minimum(out, a)
        return out
    if key == 'max':
        out = args[0]
        for a in args[1:]:
            out = np.maximum(out, a)
        return out
    if key == 'sum':
        out = args[0]
        for a in args[1:]:
            out = out + a
        return out
    if key == 'prod':
        out = args[0]
        for a in args[1:]:
            out = out * a
        return out
    if key == 'mean':
        out = args[0]
        for a in args[1:]:
            out = out + a
        return out / len(args)
    if key == 'power':
        return js_pow(args[0], args[1])
    if key == 'round':
        return js_round(args[0])
    if key == 'pi':
        return math.pi
    return FUNCTIONS[key]['fn'](*args)


Resolver = Callable[[str, Any, Ref], Leaf]
CallResolver = Callable[[str, List[Tree]], Optional[Tree]]


def resolve(ast: Node, ref: Resolver, call: Optional[CallResolver] = None) -> Tree:
    """The expression tree of a parsed equation, with every reference resolved.

    ``ref(name, indices, node)`` gives the leaf a reference reads;
    ``call(name, args)`` gives the tree of a call the model defines (a table
    read at an argument), or None to leave the name to the built-in table.
    """
    def walk(node: Node) -> Tree:
        t = node.type
        if t == 'num':
            return _k(node.value)  # type: ignore[attr-defined]
        if t == 'ref':
            return ('leaf', ref(node.name, node.indices, node))  # type: ignore[attr-defined]
        if t == 'unary':
            out: Tree = ('neg', walk(node.operand))  # type: ignore[attr-defined]
        elif t == 'binary':
            out = ('bin', node.op, walk(node.left), walk(node.right))  # type: ignore[attr-defined]
        elif t == 'cond':
            out = ('cond', walk(node.test), walk(node.then), walk(node.otherwise))  # type: ignore[attr-defined]
        elif t == 'call':
            name = FUNCTION_ALIASES.get(node.name, node.name)  # type: ignore[attr-defined]
            args = [walk(a) for a in node.args]  # type: ignore[attr-defined]
            own = call(node.name, args) if call else None  # type: ignore[attr-defined]
            if own is not None:
                return own
            if name not in FUNCTIONS:
                raise ValueError(f"Unknown function '{name}'")
            if name == 'time':
                return ('leaf', Leaf('T'))
            if name == 'start_time':
                return ('leaf', Leaf('T0'))
            if name == 'end_time':
                return ('leaf', Leaf('T1'))
            if name == 'eps':
                return _k(2.0 ** -52)
            if name == 'pi':
                return _k(math.pi)
            if name == 'if':
                out = ('cond', args[0], args[1], args[2] if len(args) > 2 else _k(0.0))
            else:
                out = ('call', name, args)
        else:
            raise ValueError(f"Cannot emit node type '{t}'")
        v = _evaluate_constant(out)
        return _k(v) if v is not None else out

    try:
        return walk(ast)
    except RecursionError:
        raise ValueError('This equation is too long or too deeply nested to compile. Split it into '
                         'expression blocks.') from None


# --- shapes and merging ---------------------------------------------------------

def signature(tree: Tree) -> str:
    """The shape of a tree: its operations and the kinds of its leaves."""
    parts: List[str] = []

    def walk(t: Tree) -> None:
        k = t[0]
        if k == 'leaf':
            parts.append(t[1].kind)
        elif k == 'neg':
            parts.append('-(')
            walk(t[1])
            parts.append(')')
        elif k == 'bin':
            parts.append(t[1] + '(')
            walk(t[2])
            parts.append(',')
            walk(t[3])
            parts.append(')')
        elif k == 'cond':
            parts.append('?(')
            walk(t[1])
            parts.append(',')
            walk(t[2])
            parts.append(',')
            walk(t[3])
            parts.append(')')
        elif k == 'call':
            parts.append(t[1] + '(')
            for i, a in enumerate(t[2]):
                if i:
                    parts.append(',')
                walk(a)
            parts.append(')')
        elif k == 'tab':
            parts.append('tab(')
            walk(t[2])
            parts.append(')')
        else:
            raise ValueError(k)

    walk(tree)
    return ''.join(parts)


def leaves(tree: Tree) -> List[Leaf]:
    """Every leaf of a tree, in a fixed order (the order :func:`rebuild` takes)."""
    out: List[Leaf] = []

    def walk(t: Tree) -> None:
        k = t[0]
        if k == 'leaf':
            out.append(t[1])
        elif k == 'neg':
            walk(t[1])
        elif k == 'bin':
            walk(t[2])
            walk(t[3])
        elif k == 'cond':
            walk(t[1])
            walk(t[2])
            walk(t[3])
        elif k == 'call':
            for a in t[2]:
                walk(a)
        elif k == 'tab':
            out.append(t[1])
            walk(t[2])

    walk(tree)
    return out


def rebuild(tree: Tree, new: List[Leaf]) -> Tree:
    """The same tree with its leaves replaced, in :func:`leaves` order."""
    it = iter(new)

    def walk(t: Tree) -> Tree:
        k = t[0]
        if k == 'leaf':
            return ('leaf', next(it))
        if k == 'neg':
            return ('neg', walk(t[1]))
        if k == 'bin':
            a = walk(t[2])
            return ('bin', t[1], a, walk(t[3]))
        if k == 'cond':
            a = walk(t[1])
            b = walk(t[2])
            return ('cond', a, b, walk(t[3]))
        if k == 'call':
            return ('call', t[1], [walk(a) for a in t[2]])
        if k == 'tab':
            leaf = next(it)
            return ('tab', leaf, walk(t[2]))
        raise ValueError(k)

    return walk(tree)


def _expand(index: Any, width: int, dtype: Any) -> np.ndarray:
    if np.ndim(index) == 0:
        return np.full(width, index, dtype=dtype)
    return np.asarray(index, dtype=dtype)


def merge_leaves(groups: Sequence[Tuple[List[Leaf], int]]) -> List[Leaf]:
    """Leaves of several same-shaped statements, concatenated position by position.

    ``groups`` is ``[(leaves, width), ...]``. A leaf that is the same scalar
    in every statement stays a scalar; otherwise it becomes one array covering
    every element of every statement, in order.
    """
    first = groups[0][0]
    out: List[Leaf] = []
    for i, leaf in enumerate(first):
        kind = leaf.kind
        if kind in ('T', 'T0', 'T1'):
            out.append(leaf)
            continue
        idx = [g[0][i].index for g in groups]
        if all(np.ndim(v) == 0 for v in idx) and all(v == idx[0] or (kind == 'K' and v != v and idx[0] != idx[0])
                                                     for v in idx):
            out.append(Leaf(kind, idx[0]))
            continue
        dtype = float if kind == 'K' else np.int64
        out.append(Leaf(kind, np.concatenate([_expand(v, w, dtype) for v, (_, w) in zip(idx, groups)])))
    return out


# --- writing code ------------------------------------------------------------------

class CodeWriter:
    """Writes statements as Python source, binding the arrays they index into a
    namespace: an index array becomes a slice where it is a run, a scalar where
    it is the same everywhere, and a name bound to the array otherwise."""

    def __init__(self, namespace: Optional[Dict[str, Any]] = None) -> None:
        self.ns: Dict[str, Any] = namespace if namespace is not None else {}
        self.ns.setdefault('np', np)
        self.ns.setdefault('_pow', js_pow)
        self.ns.setdefault('_round', js_round)
        self._n = 0
        self._funcs: Dict[str, str] = {}

    def bind(self, value: Any, prefix: str = '_a') -> str:
        name = f'{prefix}{self._n}'
        self._n += 1
        self.ns[name] = value
        return name

    def index(self, index: Any) -> str:
        """How an index is written: a number, a slice, or a bound array."""
        if np.ndim(index) == 0:
            return str(int(index))
        arr = np.asarray(index, dtype=np.int64)
        n = arr.size
        if n == 0:
            return self.bind(arr)
        if n == 1:
            return self.bind(arr)
        start = int(arr[0])
        if int(arr[-1]) - start == n - 1 and (n < 3 or bool(np.all(np.diff(arr) == 1))):
            return f'{start}:{start + n}'
        if bool(np.all(arr == start)):
            return self.bind(arr)
        return self.bind(arr)

    def number(self, value: Any) -> str:
        if np.ndim(value) == 0:
            v = float(value)
            if v != v:
                return 'np.nan'
            if math.isinf(v):
                return 'np.inf' if v > 0 else '(-np.inf)'
            return repr(v) if v >= 0 else f'({v!r})'
        arr = np.asarray(value, dtype=float)
        if arr.size and bool(np.all(arr == arr[0])):
            return self.number(float(arr[0]))
        return self.bind(arr, '_k')

    def function(self, key: str) -> str:
        if key not in self._funcs:
            self._funcs[key] = self.bind(FUNCTIONS[key]['fn'], '_f')
        return self._funcs[key]

    def leaf(self, leaf: Leaf) -> str:
        k = leaf.kind
        if k in ('y', 'P', 'X'):
            return f'{k}[{self.index(leaf.index)}]'
        if k == 'K':
            return self.number(leaf.index)
        if k in ('T', 'T0', 'T1'):
            return k
        if k == 'DIS':
            return f'DIS[{self.index(leaf.index)}]'
        raise ValueError(f'A {k} leaf is not a value')

    def expression(self, tree: Tree, vector: bool = True) -> str:
        """``tree`` as a Python expression. ``vector`` says whether it is
        evaluated for many elements at once (a conditional is then
        ``np.where``, which evaluates both branches) or for one."""
        def walk(t: Tree) -> str:
            k = t[0]
            if k == 'leaf':
                return self.leaf(t[1])
            if k == 'neg':
                return f'(-{walk(t[1])})'
            if k == 'bin':
                op = t[1]
                a = walk(t[2])
                b = walk(t[3])
                if op in ('+', '-', '*', '/'):
                    return f'({a} {op} {b})'
                if op == '^':
                    exp = t[3]
                    if exp[0] == 'leaf' and exp[1].kind == 'K' and bool(np.all(np.isfinite(exp[1].index))):
                        return f'np.power({a}, {b})'
                    return f'_pow({a}, {b})'
                if op in ('<', '<=', '>', '>=', '=='):
                    return f'(({a} {op} {b}) * 1.0)'
                if op == '~=':
                    return f'(({a} != {b}) * 1.0)'
                if op == '&&':
                    return f'((({a} != 0) & ({b} != 0)) * 1.0)'
                if op == '||':
                    return f'((({a} != 0) | ({b} != 0)) * 1.0)'
                raise ValueError(f"Cannot emit operator '{op}'")
            if k == 'cond':
                test = walk(t[1])
                a = walk(t[2])
                b = walk(t[3])
                if vector:
                    return f'np.where({test} != 0, {a}, {b})'
                return f'({a} if {test} != 0 else {b})'
            if k == 'call':
                key = t[1]
                args = [walk(a) for a in t[2]]
                if key in INLINE_NUMPY:
                    return f'{INLINE_NUMPY[key]}({", ".join(args)})'
                if key == 'power':
                    exp = t[2][1]
                    if exp[0] == 'leaf' and exp[1].kind == 'K' and bool(np.all(np.isfinite(exp[1].index))):
                        return f'np.power({args[0]}, {args[1]})'
                    return f'_pow({args[0]}, {args[1]})'
                if key == 'round':
                    return f'_round({args[0]})'
                if key == 'not':
                    return f'(({args[0]} == 0) * 1.0)'
                if key in ('min', 'max'):
                    fn = 'np.minimum' if key == 'min' else 'np.maximum'
                    out = args[0]
                    for a in args[1:]:
                        out = f'{fn}({out}, {a})'
                    return out if len(args) > 1 else f'(+{out})'
                if key == 'sum':
                    return f'({" + ".join(args)})'
                if key == 'prod':
                    return f'({" * ".join(args)})'
                if key == 'mean':
                    return f'(({" + ".join(args)}) / {len(args)})'
                return f'{self.function(key)}({", ".join(args)})'
            if k == 'tab':
                leaf = t[1]
                arg = walk(t[2])
                if np.ndim(leaf.index) == 0:
                    return f'TAB[{int(leaf.index)}].at({arg})'
                return f'_tabs(TAB, {self.index_array(leaf.index)}, {arg})'
            raise ValueError(k)

        return walk(tree)

    def index_array(self, index: Any) -> str:
        return self.bind(np.asarray(index, dtype=np.int64))


def read_tables(tables: Sequence[Any], which: np.ndarray, x: Any) -> np.ndarray:
    """Several tables, each read at its own element: ``tables[which[i]].at(x[i])``."""
    which = np.asarray(which)
    out = np.empty(which.shape)
    xs = np.broadcast_to(np.asarray(x, dtype=float), which.shape)
    uniq = np.unique(which)
    if uniq.size == 1:
        out[:] = tables[int(uniq[0])].at(xs)
        return out
    for k in uniq:
        sel = which == k
        out[sel] = tables[int(k)].at(xs[sel])
    return out
