"""The equation language: a parser that builds the tree the rest of the engine reads.

A port of ``parse`` in ``src/parser/parser.js``, over the same tokenizer
(:func:`kompartment.equations.tokenize`), with the same precedence rules:

* the C family's precedence for everything except ``^``;
* ``^`` binds tighter than unary minus and is left-associative, so
  ``2^3^2`` is 64 and ``-a^2`` is ``-(a^2)``;
* a sign is allowed at the head of an exponent: ``2^-1``;
* ``~=`` and ``!=`` are not-equal; ``.*``, ``./`` and ``.^`` are ``*``, ``/``, ``^``.

Nodes are small immutable objects -- :class:`Num`, :class:`Ref`, :class:`Call`,
:class:`Unary`, :class:`Binary`, :class:`Cond` -- matching the JavaScript node
shapes one for one.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Set, Tuple, Union

from ..equations import EquationSyntaxError, Token, tokenize
from .functions import lookup_function


class ParseError(ValueError):
    """An equation that cannot be read, with the position it fails at."""

    def __init__(self, message: str, position: int, source: str) -> None:
        super().__init__(message)
        self.position = position
        self.source = source


class Node:
    __slots__ = ()
    type = ''


class Num(Node):
    """A number, and the unit written against it (``0.01[m]``), if any."""
    __slots__ = ('value', 'unit', 'dim')
    type = 'num'

    def __init__(self, value: float, unit: Optional[str] = None) -> None:
        self.value = value
        self.unit = unit
        self.dim = None

    def __repr__(self) -> str:
        return f'Num({self.value!r}{", " + repr(self.unit) if self.unit is not None else ""})'


class Ref(Node):
    """A reference to a block. ``indices`` is one entry per bracket (``None`` for
    ``[]``), or a dict naming a list outright (the reducing blocks build those).
    ``scope`` is the sub-system a reference moved in by the function inliner
    was written in."""
    __slots__ = ('name', 'indices', 'scope')
    type = 'ref'

    def __init__(self, name: str, indices: Union[List[Optional[str]], Dict[str, str], None] = None,
                 scope: Optional[str] = None) -> None:
        self.name = name
        self.indices = indices if indices is not None else []
        self.scope = scope

    def __repr__(self) -> str:
        return f'Ref({self.name!r}, {self.indices!r}{", scope=" + repr(self.scope) if self.scope is not None else ""})'


class Call(Node):
    __slots__ = ('name', 'args', 'scope')
    type = 'call'

    def __init__(self, name: str, args: List[Node], scope: Optional[str] = None) -> None:
        self.name = name
        self.args = args
        self.scope = scope

    def __repr__(self) -> str:
        return f'Call({self.name!r}, {self.args!r})'


class Unary(Node):
    __slots__ = ('op', 'operand')
    type = 'unary'

    def __init__(self, op: str, operand: Node) -> None:
        self.op = op
        self.operand = operand

    def __repr__(self) -> str:
        return f'Unary({self.op!r}, {self.operand!r})'


class Binary(Node):
    __slots__ = ('op', 'left', 'right')
    type = 'binary'

    def __init__(self, op: str, left: Node, right: Node) -> None:
        self.op = op
        self.left = left
        self.right = right

    def __repr__(self) -> str:
        return f'Binary({self.op!r}, {self.left!r}, {self.right!r})'


class Cond(Node):
    __slots__ = ('test', 'then', 'otherwise')
    type = 'cond'

    def __init__(self, test: Node, then: Node, otherwise: Node) -> None:
        self.test = test
        self.then = then
        self.otherwise = otherwise

    def __repr__(self) -> str:
        return f'Cond({self.test!r}, {self.then!r}, {self.otherwise!r})'


OP_ALIAS = {'.*': '*', './': '/', '.^': '^', '!=': '~='}

BINARY_PRECEDENCE = {
    '||': 1,
    '&&': 2,
    '==': 3, '~=': 3,
    '<': 4, '<=': 4, '>': 4, '>=': 4,
    '+': 5, '-': 5,
    '*': 6, '/': 6,
}
POWER_PRECEDENCE = 8


def _js_number_text(text: str) -> float:
    return float(text)


def parse(src: object, calls: Optional[Callable[[str], bool]] = None) -> Node:
    """Parses an equation into a tree. Empty text is the number 0.

    ``calls(name)`` says whether a name the function table does not know is a
    call the model itself defines (a lookup table read at an argument, a
    user-defined function); without it such a call is an error.
    """
    if src is None or str(src).strip() == '':
        return Num(0.0)
    text = str(src)
    try:
        raw = tokenize(text)
    except EquationSyntaxError as e:
        raise ParseError(str(e), e.position, text) from None
    tokens: List[Tuple[str, str, int]] = []
    for t in raw:
        if t.type == 'op':
            tokens.append(('op', OP_ALIAS.get(t.text, t.text), t.pos))
        else:
            tokens.append((t.type, t.text, t.pos))
    pos = [0]

    def peek() -> Tuple[str, str, int]:
        return tokens[pos[0]]

    def advance() -> Tuple[str, str, int]:
        tok = tokens[pos[0]]
        pos[0] += 1
        return tok

    def shown(tok: Tuple[str, str, int]) -> str:
        return '<end>' if tok[0] == 'eof' else tok[1]

    def expect(kind: str, what: str) -> Tuple[str, str, int]:
        tok = peek()
        if tok[0] != kind:
            raise ParseError(f"Expected {what} but found '{shown(tok)}'", tok[2], text)
        return advance()

    def args_until_rparen() -> List[Node]:
        out: List[Node] = []
        if peek()[0] != 'rparen':
            while True:
                out.append(parse_ternary())
                if peek()[0] == 'comma':
                    advance()
                    continue
                break
        expect('rparen', "')'")
        return out

    def parse_primary() -> Node:
        tok = peek()
        kind, value, where = tok
        if kind == 'number':
            advance()
            if peek()[0] == 'lbracket':
                advance()
                unit = advance()[1].strip() if peek()[0] == 'index' else ''
                expect('rbracket', "']'")
                return Num(_js_number_text(value), unit)
            return Num(_js_number_text(value))
        if kind == 'lparen':
            advance()
            inner = parse_ternary()
            expect('rparen', "')'")
            return inner
        if kind == 'op' and value in ('-', '+'):
            advance()
            operand = parse_binary(POWER_PRECEDENCE - 1)
            return Unary('-', operand) if value == '-' else operand
        if kind == 'ident':
            advance()
            name = value
            if peek()[0] == 'lparen':
                fn = lookup_function(name)
                if fn is None:
                    if not (calls and calls(name)):
                        raise ParseError(f"Unknown function '{name}'", where, text)
                    advance()
                    return Call(name, args_until_rparen())
                advance()
                args = args_until_rparen()
                most = fn['maxArity'] if fn.get('maxArity') is not None else (
                    float('inf') if fn.get('varargs') else fn['arity'])
                if len(args) < fn['arity'] or len(args) > most:
                    if most == float('inf'):
                        wanted = f"at least {fn['arity']}"
                    elif fn['arity'] == most:
                        wanted = f"{fn['arity']}"
                    else:
                        wanted = f"{fn['arity']}-{int(most)}"
                    raise ParseError(f"Function '{name}' takes {wanted} argument(s), got {len(args)}", where, text)
                return Call(fn['key'], args)
            fn = lookup_function(name)
            if fn is not None and fn['arity'] == 0:
                return Call(fn['key'], [])
            indices: List[Optional[str]] = []
            while peek()[0] == 'lbracket':
                advance()
                idx = advance()[1].strip() if peek()[0] == 'index' else ''
                expect('rbracket', "']'")
                indices.append(None if idx == '' else idx)
            return Ref(name, indices)
        raise ParseError(f"Unexpected '{shown(tok)}'", where, text)

    def parse_exponent() -> Node:
        kind, value, _ = peek()
        if kind == 'op' and value in ('-', '+'):
            advance()
            operand = parse_exponent()
            return Unary('-', operand) if value == '-' else operand
        return parse_primary()

    def parse_power() -> Node:
        left = parse_primary()
        while peek()[0] == 'op' and peek()[1] == '^':
            advance()
            right = parse_exponent()
            left = Binary('^', left, right)
        return left

    def parse_binary(min_prec: int) -> Node:
        left = parse_power()
        while True:
            kind, value, _ = peek()
            if kind != 'op':
                break
            prec = BINARY_PRECEDENCE.get(value)
            if prec is None or prec < min_prec:
                break
            advance()
            right = parse_binary(prec + 1)
            left = Binary(value, left, right)
        return left

    def parse_ternary() -> Node:
        test = parse_binary(1)
        if peek()[0] == 'op' and peek()[1] == '?':
            advance()
            then = parse_ternary()
            colon = peek()
            if colon[0] != 'op' or colon[1] != ':':
                raise ParseError(f"Expected ':' in conditional but found '{shown(colon)}'", colon[2], text)
            advance()
            otherwise = parse_ternary()
            return Cond(test, then, otherwise)
        return test

    try:
        ast = parse_ternary()
    except RecursionError:
        raise ParseError('This equation is nested too deeply to read. Split it into expression blocks, '
                         'which is also how anyone else will be able to follow it.', 0, text) from None
    trailing = peek()
    if trailing[0] != 'eof':
        raise ParseError(f"Unexpected '{shown(trailing)}'", trailing[2], text)
    return ast


def collect_references(ast: Node, out: Optional[Set[str]] = None) -> Set[str]:
    """The names of every block a tree refers to."""
    out = set() if out is None else out
    stack = [ast]
    while stack:
        node = stack.pop()
        t = node.type
        if t == 'ref':
            out.add(node.name)  # type: ignore[attr-defined]
        elif t == 'call':
            stack.extend(node.args)  # type: ignore[attr-defined]
        elif t == 'unary':
            stack.append(node.operand)  # type: ignore[attr-defined]
        elif t == 'binary':
            stack.append(node.left)  # type: ignore[attr-defined]
            stack.append(node.right)  # type: ignore[attr-defined]
        elif t == 'cond':
            stack.append(node.test)  # type: ignore[attr-defined]
            stack.append(node.then)  # type: ignore[attr-defined]
            stack.append(node.otherwise)  # type: ignore[attr-defined]
    return out


def reads_clock(ast: Node) -> bool:
    """Whether a tree calls ``time``, anywhere."""
    stack = [ast]
    while stack:
        node = stack.pop()
        t = node.type
        if t == 'call':
            if node.name == 'time':  # type: ignore[attr-defined]
                return True
            stack.extend(node.args)  # type: ignore[attr-defined]
        elif t == 'unary':
            stack.append(node.operand)  # type: ignore[attr-defined]
        elif t == 'binary':
            stack.append(node.left)  # type: ignore[attr-defined]
            stack.append(node.right)  # type: ignore[attr-defined]
        elif t == 'cond':
            stack.append(node.test)  # type: ignore[attr-defined]
            stack.append(node.then)  # type: ignore[attr-defined]
            stack.append(node.otherwise)  # type: ignore[attr-defined]
    return False


__all__ = ['ParseError', 'Node', 'Num', 'Ref', 'Call', 'Unary', 'Binary', 'Cond', 'parse',
           'collect_references', 'reads_clock', 'Token']
