"""Equations in Ecolego's spelling, for the .eco export: ``src/io/ecoequation.js``.

The rules, and why each is there, are the application's (see that file): a
unit written against a number goes without it; a test is only ever the
condition of an ``if()``, and a test that stands for a number is
``if(test, 1, 0)``; ``?:`` and ``!=`` are ``if()`` and ``~=``; a sign after an
operator is bracketed; five spellings Ecolego does not know are its own; one
value of ``min`` and the like is that value; the functions Ecolego has no
counterpart for are written out as the arithmetic they stand for, and so are
``mod`` and ``rem``, which Ecolego works out as the exact remainder and this
package as ``a - b * floor(a / b)`` and with ``fix`` (``mod`` by what may be
zero guarded, since ``mod(a, 0)`` is ``a``); a call to a table that repeats
over its range is wrapped into the range; and ``percentile`` and the
transport operations leave their block out.

The application parses with its own parser; this parses with a copy of the
same grammar, because the engine's (``engine/lang.py``) needs numpy and the
export does not. The function table it needs -- which names are functions,
how many arguments each takes, and the other spellings -- is the
application's, written to ``data/functions.json`` by ``tools/gen_data.mjs``.
The export tests compare the two translators' texts, byte for byte.
"""
from __future__ import annotations

import json
from importlib import resources
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from ..equations import EquationSyntaxError, tokenize
from ..importers._eco_maps import js_trim

_TABLE = json.loads(resources.files('kompartment').joinpath('data', 'functions.json').read_text('utf-8'))

#: Every function an equation can call: name -> (fewest arguments, most or None).
FUNCTIONS: Dict[str, Tuple[int, Optional[int]]] = {k: (v[0], v[1]) for k, v in _TABLE['functions'].items()}

#: The other spellings the parser accepts.
FUNCTION_ALIASES: Dict[str, str] = dict(_TABLE['aliases'])

#: Calls with no Ecolego counterpart and no written-out form: a block that makes one is left out.
NO_ECOLEGO_FUNCTION = frozenset(['percentile', 'transport_point', 'transport_sum', 'transport_mean'])

#: The constants the written-out functions need, as Java writes them.
LN2_TEXT = '0.6931471805599453'
AVOGADRO_TEXT = '6.02214179E23'
SECONDS_PER_YEAR_TEXT = '3.15576E7'
MAX_DOUBLE_TEXT = '1.7976931348623157E308'

#: The written-out functions that agree to rounding rather than to the bit.
TO_ROUNDING = frozenset(['asinh', 'acosh', 'atanh'])

#: The written-out functions Ecolego has too, working them out another way.
WORKED_OTHERWISE = frozenset(['mod', 'rem'])

_WRITTEN_OUT = frozenset([
    'mole2bq', 'bq2mole', 'ulp', 'rampDown', 'rampUp', 'smoothDown', 'smoothUp', 'nand', 'nor', 'xor',
    'asinh', 'acosh', 'atanh', *WORKED_OTHERWISE,
])
_LOGICAL_CALLS = frozenset(['and', 'or', 'not', 'nand', 'nor', 'xor'])
_AGGREGATES = frozenset(['min', 'max', 'sum', 'prod', 'mean'])
_COMPARISONS = frozenset(['<', '<=', '>', '>=', '==', '~='])
_TEST_OPERATORS = frozenset(list(_COMPARISONS) + ['&&', '||', '!=', '?'])
_CALLS_TO_WRITE = frozenset(list(FUNCTION_ALIASES) + list(_WRITTEN_OUT) + list(_LOGICAL_CALLS)
                            + list(_AGGREGATES) + list(NO_ECOLEGO_FUNCTION) + ['if'])
_ARITHMETIC = frozenset(['+', '-', '*', '/', '^', '.*', './', '.^'])

_PRIMARY = 10
_POWER = 8
_UNARY = 7
_PRECEDENCE = {'+': 5, '-': 5, '*': 6, '/': 6}

_OP_ALIAS = {'.*': '*', './': '/', '.^': '^', '!=': '~='}
_BINARY_PRECEDENCE = {
    '||': 1, '&&': 2, '==': 3, '~=': 3, '<': 4, '<=': 4, '>': 4, '>=': 4,
    '+': 5, '-': 5, '*': 6, '/': 6,
}
_POWER_PRECEDENCE = 8


# --- the tree -------------------------------------------------------------------------------

class _Node:
    __slots__ = ()
    type = ''


class _Num(_Node):
    __slots__ = ('value', 'text', 'unit')
    type = 'num'

    def __init__(self, text: str, unit: Optional[str] = None) -> None:
        self.value = float(text)
        self.text = text
        self.unit = unit


class _Ref(_Node):
    __slots__ = ('name', 'indices')
    type = 'ref'

    def __init__(self, name: str, indices: List[Optional[str]]) -> None:
        self.name = name
        self.indices = indices


class _Call(_Node):
    __slots__ = ('name', 'args', 'wrapped', 'native')
    type = 'call'

    def __init__(self, name: str, args: List[_Node], wrapped: bool = False, native: bool = False) -> None:
        self.name = name
        self.args = args
        self.wrapped = wrapped
        #: Ecolego's own, as it is: the table wrap's ``rem``.
        self.native = native


class _Unary(_Node):
    __slots__ = ('op', 'operand')
    type = 'unary'

    def __init__(self, op: str, operand: _Node) -> None:
        self.op = op
        self.operand = operand


class _Binary(_Node):
    __slots__ = ('op', 'left', 'right')
    type = 'binary'

    def __init__(self, op: str, left: _Node, right: _Node) -> None:
        self.op = op
        self.left = left
        self.right = right


class _Cond(_Node):
    __slots__ = ('test', 'then', 'otherwise')
    type = 'cond'

    def __init__(self, test: _Node, then: _Node, otherwise: _Node) -> None:
        self.test = test
        self.then = then
        self.otherwise = otherwise


class _Refused(Exception):
    """An equation the application's parser refuses: it goes as it was typed."""


def _lookup(name: str) -> Optional[Tuple[str, int, Optional[int]]]:
    key = FUNCTION_ALIASES.get(name, name)
    spec = FUNCTIONS.get(key)
    return None if spec is None else (key, spec[0], spec[1])


def _parse(src: str) -> _Node:
    """``parse`` in ``src/parser/parser.js`` with every unknown call the model's own."""
    raw = tokenize(src)
    toks = [(t.type, _OP_ALIAS.get(t.text, t.text) if t.type == 'op' else t.text) for t in raw]
    pos = [0]

    def peek() -> Tuple[str, str]:
        return toks[pos[0]]

    def advance() -> Tuple[str, str]:
        tok = toks[pos[0]]
        pos[0] += 1
        return tok

    def expect(kind: str) -> None:
        if peek()[0] != kind:
            raise _Refused()
        advance()

    def args_until_rparen() -> List[_Node]:
        out: List[_Node] = []
        if peek()[0] != 'rparen':
            while True:
                out.append(parse_ternary())
                if peek()[0] == 'comma':
                    advance()
                    continue
                break
        expect('rparen')
        return out

    def parse_primary() -> _Node:
        kind, value = peek()
        if kind == 'number':
            advance()
            if peek()[0] == 'lbracket':
                advance()
                unit = js_trim(advance()[1]) if peek()[0] == 'index' else ''
                expect('rbracket')
                return _Num(value, unit)
            return _Num(value)
        if kind == 'lparen':
            advance()
            inner = parse_ternary()
            expect('rparen')
            return inner
        if kind == 'op' and value in ('-', '+'):
            advance()
            operand = parse_binary(_POWER_PRECEDENCE - 1)
            return _Unary('-', operand) if value == '-' else operand
        if kind == 'ident':
            advance()
            name = value
            if peek()[0] == 'lparen':
                fn = _lookup(name)
                advance()
                args = args_until_rparen()
                if fn is None:
                    return _Call(name, args)
                key, fewest, most = fn
                if len(args) < fewest or (most is not None and len(args) > most):
                    raise _Refused()
                return _Call(key, args)
            fn = _lookup(name)
            if fn is not None and fn[1] == 0:
                return _Call(fn[0], [])
            indices: List[Optional[str]] = []
            while peek()[0] == 'lbracket':
                advance()
                text = js_trim(advance()[1]) if peek()[0] == 'index' else ''
                expect('rbracket')
                indices.append(None if text == '' else text)
            return _Ref(name, indices)
        raise _Refused()

    def parse_exponent() -> _Node:
        kind, value = peek()
        if kind == 'op' and value in ('-', '+'):
            advance()
            operand = parse_exponent()
            return _Unary('-', operand) if value == '-' else operand
        return parse_primary()

    def parse_power() -> _Node:
        left = parse_primary()
        while peek()[0] == 'op' and peek()[1] == '^':
            advance()
            left = _Binary('^', left, parse_exponent())
        return left

    def parse_binary(min_prec: int) -> _Node:
        left = parse_power()
        while True:
            kind, value = peek()
            if kind != 'op':
                break
            prec = _BINARY_PRECEDENCE.get(value)
            if prec is None or prec < min_prec:
                break
            advance()
            left = _Binary(value, left, parse_binary(prec + 1))
        return left

    def parse_ternary() -> _Node:
        test = parse_binary(1)
        if peek()[0] == 'op' and peek()[1] == '?':
            advance()
            then = parse_ternary()
            if peek()[0] != 'op' or peek()[1] != ':':
                raise _Refused()
            advance()
            return _Cond(test, then, parse_ternary())
        return test

    ast = parse_ternary()
    if peek()[0] != 'eof':
        raise _Refused()
    return ast


def _tree(text: str) -> Optional[_Node]:
    try:
        return _parse(text)
    except (_Refused, EquationSyntaxError, RecursionError, IndexError):
        return None


# --- what the tokens say ------------------------------------------------------------------------

def _scan(toks: Sequence[Any], wraps: Optional[Callable[[str], Any]]) -> Tuple[bool, bool]:
    look = False
    must = False
    for i, t in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if t.type == 'number' and nxt is not None and nxt.type == 'lbracket':
            look = must = True
        if t.type == 'op':
            if t.text in _TEST_OPERATORS:
                look = True
            if t.text == '!=':
                must = True
            if t.text in _ARITHMETIC and nxt is not None and nxt.type == 'op' and nxt.text in ('-', '+'):
                look = must = True
        if t.type == 'ident' and nxt is not None and nxt.type == 'lparen' and t.text in _CALLS_TO_WRITE:
            look = True
            if t.text in FUNCTION_ALIASES:
                must = True
        if t.type == 'ident' and nxt is not None and nxt.type == 'lparen' and wraps is not None and wraps(t.text):
            look = must = True
    return look, must


def unsupported_calls(text: Any) -> List[str]:
    """The calls in an equation Ecolego has no counterpart for (``unsupportedCalls``)."""
    src = '' if text is None else str(text)
    try:
        toks = tokenize(src)
    except EquationSyntaxError:
        return []
    out: List[str] = []
    for i, t in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if (t.type == 'ident' and nxt is not None and nxt.type == 'lparen'
                and t.text in NO_ECOLEGO_FUNCTION and t.text not in out):
            out.append(t.text)
    return out


class EcolegoEquation(NamedTuple):
    """An equation in Ecolego's spelling, and what that took."""

    text: str
    units: bool
    written_out: List[str]
    respelled: bool


class _Notes:
    __slots__ = ('units', 'written_out', 'needed', 'wraps')

    def __init__(self, needed: bool, wraps: Optional[Callable[[str], Any]]) -> None:
        self.units = False
        self.written_out: List[str] = []
        self.needed = needed
        self.wraps = wraps


def ecolego_equation(text: Any, call: Optional[Callable[[str], Optional[Dict[str, str]]]] = None) -> EcolegoEquation:
    """An equation in Ecolego's spelling (``ecolegoEquation``). ``call`` says of a
    call the model defines whether it reads a table that repeats over its range,
    and that range -- ``{'first': ..., 'span': ...}`` as Java writes the numbers."""
    src = '' if text is None else str(text)
    same = EcolegoEquation(src, False, [], False)
    if js_trim(src) == '':
        return same
    try:
        toks = tokenize(src)
    except EquationSyntaxError:
        return same
    look, must = _scan(toks, call)
    if not look:
        return same
    ast = _tree(src)
    if ast is None:
        return same
    notes = _Notes(must, call)
    out = _value(ast, notes)[0]
    if not notes.needed:
        return same
    return EcolegoEquation(out, notes.units, notes.written_out, out != src)


# --- the printer ----------------------------------------------------------------------------------

def _num(text: str) -> _Num:
    return _Num(text)


def _is_test(node: _Node) -> bool:
    op = getattr(node, 'op', None)
    return ((node.type == 'binary' and (op in _COMPARISONS or op in ('&&', '||')))
            or (node.type == 'call' and node.name in _LOGICAL_CALLS))  # type: ignore[attr-defined]


def _value(node: _Node, notes: _Notes) -> Tuple[str, int]:
    t = node.type
    if t == 'num':
        if node.unit is not None:  # type: ignore[attr-defined]
            notes.units = notes.needed = True
        return node.text, _PRIMARY  # type: ignore[attr-defined]
    if t == 'ref':
        name, indices = node.name, node.indices  # type: ignore[attr-defined]
        return name + ''.join(f"[{'' if i is None else i}]" for i in indices), _PRIMARY
    if t == 'unary':
        inner, prec = _value(node.operand, notes)  # type: ignore[attr-defined]
        return f"-{inner if prec >= _POWER else '(' + inner + ')'}", _UNARY
    if t == 'cond':
        notes.needed = True
        test = _test(node.test, notes, True)  # type: ignore[attr-defined]
        then = _value(node.then, notes)[0]  # type: ignore[attr-defined]
        otherwise = _value(node.otherwise, notes)[0]  # type: ignore[attr-defined]
        return f'if({test}, {then}, {otherwise})', _PRIMARY
    if t == 'binary':
        if _is_test(node):
            notes.needed = True
            return f'if({_test(node, notes, True)}, 1, 0)', _PRIMARY
        if node.op == '^':  # type: ignore[attr-defined]
            base, bp = _value(node.left, notes)  # type: ignore[attr-defined]
            power, pp = _value(node.right, notes)  # type: ignore[attr-defined]
            b = base if bp in (_PRIMARY, _POWER) else f'({base})'
            p = power if pp == _PRIMARY else f'({power})'
            return f'{b}^{p}', _POWER
        return _arithmetic(node, notes)
    if t == 'call':
        return _call_value(node, notes)
    return '0', _PRIMARY


def _arithmetic(node: Any, notes: _Notes) -> Tuple[str, int]:
    p = _PRECEDENCE.get(node.op, 5)
    left, lp = _value(node.left, notes)
    right, rp = _value(node.right, notes)
    lt = f'({left})' if lp == _UNARY or lp < p else left
    rt = f'({right})' if rp == _UNARY or rp <= p else right
    return f'{lt} {node.op} {rt}', p


def _call_value(node: Any, notes: _Notes) -> Tuple[str, int]:
    name, args = node.name, node.args

    def said(fn: str) -> None:
        notes.needed = True
        if fn not in notes.written_out:
            notes.written_out.append(fn)

    if name in _LOGICAL_CALLS:
        notes.needed = True
    if name == 'if':
        condition = _test(args[0], notes, True)
        rest = [_value(a, notes)[0] for a in args[1:]]
        return f"if({', '.join([condition] + rest)})", _PRIMARY
    if name in ('and', 'or'):
        return f'if({_test(node, notes, True)}, 1, 0)', _PRIMARY
    if name == 'not':
        return f'if({_test(args[0], notes, True)}, 0, 1)', _PRIMARY
    if name in ('nand', 'nor'):
        said(name)
        return f"if({_joined(args, '&&' if name == 'nand' else '||', notes)}, 0, 1)", _PRIMARY
    if name == 'xor':
        said(name)
        # Ecolego's own mod: of a count, the exact remainder is the only one.
        return f"mod({' + '.join(f'if({_test(a, notes, True)}, 1, 0)' for a in args)}, 2)", _PRIMARY
    if name in WORKED_OTHERWISE:
        if not node.native:
            said(name)
            a, b = args
            body = _Binary('-', a, _Binary('*', b, _Call('floor' if name == 'mod' else 'fix', [_Binary('/', a, b)])))
            # rem(a, 0) is NaN here and so is the arithmetic; mod(a, 0) is a.
            if b.type == 'num':
                non_zero = b.value != 0
            else:
                non_zero = b.type == 'unary' and b.operand.type == 'num' and b.operand.value != 0
            if name == 'rem' or non_zero:
                return _value(body, notes)
            return _value(_Call('if', [_Binary('==', b, _num('0')), a, body]), notes)
    elif name == 'mole2bq':
        said(name)
        return _value(_Binary('/', _Binary('*', _Binary('*', _num(LN2_TEXT), args[0]), _num(AVOGADRO_TEXT)),
                              _Binary('*', args[1], _num(SECONDS_PER_YEAR_TEXT))), notes)
    elif name == 'bq2mole':
        said(name)
        return _value(_Binary('/', _Binary('*', _Binary('*', args[0], args[1]), _num(SECONDS_PER_YEAR_TEXT)),
                              _Binary('*', _num(LN2_TEXT), _num(AVOGADRO_TEXT))), notes)
    elif name == 'ulp':
        said(name)
        return _value(_Binary('*', _Call('abs', [args[0]]), _Call('eps', [])), notes)
    elif name == 'rampDown':
        said(name)
        return _value(_ramp_down(args), notes)
    elif name == 'rampUp':
        said(name)
        return _value(_Binary('-', _num('1'), _ramp_down(args)), notes)
    elif name == 'smoothDown':
        said(name)
        return _value(_smooth_down(args), notes)
    elif name == 'smoothUp':
        said(name)
        return _value(_Binary('-', _num('1'), _smooth_down(args)), notes)
    elif name in ('asinh', 'acosh', 'atanh'):
        said(name)
        return _value(_HYPERBOLIC[name](args[0]), notes)
    else:
        if name in _AGGREGATES and len(args) == 1:
            notes.needed = True
            return _value(args[0], notes)
        if len(args) == 1 and not node.wrapped:
            span = notes.wraps(name) if notes.wraps is not None else None
            if span:
                notes.needed = True
                return _value(_Call(name, [_wrapped(args[0], span)], wrapped=True), notes)
    return f"{name}({', '.join(_value(a, notes)[0] for a in args)})", _PRIMARY


def _wrapped(x: _Node, span: Dict[str, str]) -> _Node:
    """A value put on a table's own range (``wrapped``)."""
    first = span['first']
    at: _Node = _Unary('-', _num(first[1:])) if first.startswith('-') else _num(first)
    a = _Call('rem', [_Binary('-', x, at), _num(span['span'])], native=True)
    return _Call('if', [_Binary('>=', a, _num('0')), _Binary('+', a, at),
                        _Binary('+', _Binary('+', a, _num(span['span'])), at)])


def _ramp_down(args: Sequence[_Node]) -> _Node:
    x, start, end = args
    lo = _Call('min', [start, end])
    hi = _Call('max', [start, end])
    return _Call('if', [_Binary('>', x, lo),
                        _Call('if', [_Binary('>=', x, hi), _num('0'),
                                     _Binary('/', _Binary('-', hi, x), _Binary('-', hi, lo))]),
                        _num('1')])


def _smooth_down(args: Sequence[_Node]) -> _Node:
    x, big_x, s = args
    r = _Call('power', [_Binary('/', x, big_x), _Binary('*', _num('2'), s)])
    return _Call('if', [_Binary('>', x, _num('0')),
                        _Call('if', [_Binary('>', big_x, _num('0')),
                                     _Call('if', [_Binary('<=', r, _num(MAX_DOUBLE_TEXT)),
                                                  _Binary('/', _num('1'), _Binary('+', _num('1'), r)), _num('0')]),
                                     _num('0')]),
                        _num('1')])


def _pow(x: _Node, n: str) -> _Node:
    return x if n == '1' else _Binary('^', x, _num(n))


def _series(x: _Node, terms: Sequence[Tuple[str, str, str, str]]) -> _Node:
    total: _Node = _num('1')
    for op, k, n, d in terms:
        term = (_Binary('/', _pow(x, n), _num(d)) if k == '1'
                else _Binary('/', _Binary('*', _num(k), _pow(x, n)), _num(d)))
        total = _Binary(op, total, term)
    return total


def _asinh(x: _Node) -> _Node:
    small = _series(x, [('-', '1', '2', '6'), ('+', '3', '4', '40'), ('-', '15', '6', '336')])
    huge = _Binary('+', _Call('log', [_Call('abs', [x])]), _num(LN2_TEXT))
    rest = _Call('log', [_Binary('+', _Call('abs', [x]), _Call('sqrt', [_Binary('+', _pow(x, '2'), _num('1'))]))])
    return _Call('if', [_Binary('<', _Call('abs', [x]), _num('0.01')),
                        _Binary('*', x, small),
                        _Call('if', [_Binary('>', _Call('abs', [x]), _num('1e150')),
                                     _Binary('*', _Call('sign', [x]), huge),
                                     _Binary('*', _Call('sign', [x]), rest)])])


def _acosh(x: _Node) -> _Node:
    e = _Binary('-', x, _num('1'))
    small = _series(e, [('-', '1', '1', '12'), ('+', '3', '2', '160'), ('-', '5', '3', '896')])
    rest = _Binary('*', _Call('sqrt', [e]), _Call('sqrt', [_Binary('+', x, _num('1'))]))
    return _Call('if', [_Binary('<', e, _num('1e-5')),
                        _Binary('*', _Call('sqrt', [_Binary('*', _num('2'), e)]), small),
                        _Call('if', [_Binary('>', x, _num('1e150')),
                                     _Binary('+', _Call('log', [x]), _num(LN2_TEXT)),
                                     _Call('log', [_Binary('+', x, rest)])])])


def _atanh(x: _Node) -> _Node:
    return _Call('if', [_Binary('<', _Call('abs', [x]), _num('0.01')),
                        _Binary('*', x, _series(x, [('+', '1', '2', '3'), ('+', '1', '4', '5'), ('+', '1', '6', '7')])),
                        _Binary('*', _num('0.5'), _Call('log', [_Binary('/', _Binary('+', _num('1'), x),
                                                                        _Binary('-', _num('1'), x))]))])


_HYPERBOLIC: Dict[str, Callable[[_Node], _Node]] = {'asinh': _asinh, 'acosh': _acosh, 'atanh': _atanh}


def _test(node: Any, notes: _Notes, direct: bool) -> str:
    if node.type == 'binary' and node.op in _COMPARISONS:
        return f'{_operand(_value(node.left, notes))} {node.op} {_operand(_value(node.right, notes))}'
    if node.type == 'binary' and node.op in ('&&', '||'):
        return _joined([node.left, node.right], node.op, notes)
    if node.type == 'call' and node.name in ('and', 'or'):
        return _joined(node.args, '&&' if node.name == 'and' else '||', notes)
    conditional = node.type == 'cond' or (node.type == 'call' and (node.name == 'if' or node.name in _LOGICAL_CALLS))
    if direct and not conditional:
        return _value(node, notes)[0]
    notes.needed = True
    return f'{_operand(_value(node, notes))} ~= 0'


def _joined(parts: Sequence[Any], op: str, notes: _Notes) -> str:
    out: List[str] = []
    for p in parts:
        text = _test(p, notes, False)
        other = ((p.type == 'binary' and p.op in ('&&', '||') and p.op != op)
                 or (p.type == 'call' and p.name in ('and', 'or') and ('&&' if p.name == 'and' else '||') != op))
        out.append(f'({text})' if other else text)
    return f' {op} '.join(out)


def _operand(v: Tuple[str, int]) -> str:
    return f'({v[0]})' if v[1] == _UNARY else v[0]


# --- what an equation reads -----------------------------------------------------------------------

def reads_of(text: Any) -> Tuple[List[str], bool]:
    """The names an equation reads -- its references, and the calls that are the
    model's own -- and whether it reads the time (``readsOf``)."""
    names: List[str] = []
    time = False
    ast = _tree('' if text is None else str(text)) if js_trim('' if text is None else str(text)) != '' else _Num('0')
    if ast is None:
        return names, time
    stack: List[Any] = [ast]
    while stack:
        node = stack.pop()
        if node.type == 'ref':
            names.append(node.name)
        elif node.type == 'call':
            if node.name == 'time':
                time = True
            elif node.name not in FUNCTIONS:
                names.append(node.name)
            stack.extend(node.args)
        elif node.type == 'unary':
            stack.append(node.operand)
        elif node.type == 'binary':
            stack.extend([node.left, node.right])
        elif node.type == 'cond':
            stack.extend([node.test, node.then, node.otherwise])
    return names, time
