"""Units in equations: parsing them, checking an equation, scaling a literal.

A port of ``src/domain/unitcheck.js``. A unit is a product of powers of
symbols times a scale (``km`` is m^1 x 1000, ``g`` is kg^1 x 0.001); two units
are the same quantity when their powers agree, and the same unit when the
scales agree too. A number written with a unit -- ``1000[mm]`` -- is converted
to the unit of what it is added to, compared with or chosen against, when
that unit is known: ``p1 + 1000[mm]`` with ``p1`` in metres is ``p1 + 1``.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Dict, List, Optional

from .lang import Node

_NONE = {'', '-', '[-]', '1', 'unitless', 'dimensionless', 'none', 'n/a', '[]'}
ALIAS = {
    'y': 'year', 'yr': 'year', 'years': 'year', 'a': 'year',
    'sec': 's', 'second': 's', 'seconds': 's',
    'hour': 'h', 'hours': 'h',
    'day': 'd', 'days': 'd',
    'litre': 'L', 'liter': 'L', 'l': 'L',
    'Bequerel': 'Bq', 'becquerel': 'Bq',
    'Mole': 'mol', 'mole': 'mol', 'moles': 'mol',
    'Sievert': 'Sv', 'sievert': 'Sv',
    'kilogram': 'kg', 'kilograms': 'kg',
    'metre': 'm', 'meter': 'm', 'metres': 'm', 'meters': 'm',
}
PREFIX = [('T', 1e12), ('G', 1e9), ('M', 1e6), ('k', 1e3), ('d', 1e-1), ('c', 1e-2), ('m', 1e-3), ('u', 1e-6),
          ('µ', 1e-6), ('μ', 1e-6), ('n', 1e-9), ('p', 1e-12)]
PREFIXABLE = {'Bq', 'Sv', 'Gy', 'g', 'kg', 'm', 'mol', 'L', 's', 'J', 'W', 'Pa', 'Ci'}


def _js_str(v: float) -> str:
    from ..jsonio import js_number
    return js_number(v)


def _to_exponential(v: float) -> str:
    """``Number.prototype.toExponential()`` with no argument."""
    if v == 0:
        return '0e+0'
    r = repr(float(v))
    if 'e' in r:
        mant, exp = r.split('e')
        e = int(exp)
    else:
        mant, e = r, 0
    sign = '-' if mant.startswith('-') else ''
    mant = mant.lstrip('-')
    if '.' in mant:
        whole, frac = mant.split('.')
    else:
        whole, frac = mant, ''
    digits = (whole + frac).lstrip('0')
    lead_zeros = len(whole + frac) - len((whole + frac).lstrip('0'))
    e += len(whole) - 1 - lead_zeros
    digits = digits.rstrip('0') or '0'
    body = digits[0] + ('.' + digits[1:] if len(digits) > 1 else '')
    return f"{sign}{body}e{'+' if e >= 0 else '-'}{abs(e)}"


def scale_text(scale: float) -> str:
    if 1e-3 <= scale < 1e6:
        return _js_str(float(f'{scale:.12g}'))
    return re.sub(r'\.?0+e', 'e', _to_exponential(float(f'{scale:.12g}')))


class Dim:
    """A unit: powers of symbols, and a scale."""

    __slots__ = ('powers', 'scale')

    def __init__(self, powers: Optional[Dict[str, float]] = None, scale: float = 1.0) -> None:
        self.powers = dict(powers or {})
        self.scale = scale

    @staticmethod
    def one() -> 'Dim':
        return Dim()

    @property
    def is_one(self) -> bool:
        return not self.powers and self.scale == 1

    def times(self, other: 'Dim', sign: int = 1) -> 'Dim':
        out = dict(self.powers)
        for sym, n in other.powers.items():
            nxt = out.get(sym, 0) + n * sign
            if nxt == 0:
                out.pop(sym, None)
            else:
                out[sym] = nxt
        return Dim(out, self.scale * other.scale if sign > 0 else self.scale / other.scale)

    def over(self, other: 'Dim') -> 'Dim':
        return self.times(other, -1)

    def pow(self, n: float) -> Optional['Dim']:
        if n == 0:
            return Dim.one()
        out = {}
        for sym, e in self.powers.items():
            nxt = e * n
            if not float(nxt).is_integer():
                return None
            out[sym] = int(nxt)
        return Dim(out, self.scale ** n)

    def same_kind(self, other: Optional['Dim']) -> bool:
        if other is None or len(self.powers) != len(other.powers):
            return False
        return all(other.powers.get(sym) == n for sym, n in self.powers.items())

    def factor(self, other: 'Dim') -> float:
        return self.scale / other.scale

    def equals(self, other: Optional['Dim']) -> bool:
        if not self.same_kind(other):
            return False
        return abs(self.factor(other) - 1) < 1e-9  # type: ignore[arg-type]

    def __str__(self) -> str:
        if self.is_one:
            return 'unitless'
        up = sorted((s, n) for s, n in self.powers.items() if n > 0)
        down = sorted((s, n) for s, n in self.powers.items() if n < 0)

        def part(p: tuple) -> str:
            return p[0] if abs(p[1]) == 1 else f'{p[0]}^{_js_str(abs(p[1]))}'

        if not up and not down:
            return f'×{scale_text(self.scale)}'
        top = '*'.join(part(p) for p in up) if up else '1'
        lead = '' if self.scale == 1 else f'{scale_text(self.scale)} '
        if not down:
            return f'{lead}{top}'
        bottom = '*'.join(part(p) for p in down)
        return f"{lead}{top}/{'(' + bottom + ')' if len(down) > 1 else bottom}"


def _mass_dim(base: str, scale: float) -> Dim:
    if base == 'g':
        return Dim({'kg': 1}, scale * 1e-3)
    return Dim({base: 1}, scale)


def _prefixed(name: str) -> Optional[Dim]:
    for pre, scale in PREFIX:
        if not name.startswith(pre) or len(name) == len(pre):
            continue
        rest = name[len(pre):]
        base = ALIAS.get(rest, rest)
        if base == 'kg':
            continue
        if base in PREFIXABLE:
            return _mass_dim(base, scale)
    return None


def _symbol_dim(raw: str) -> Dim:
    sym = raw.strip()
    if not sym:
        return Dim.one()
    if sym.lower() in _NONE:
        return Dim.one()
    packed = re.match(r'^([A-Za-zµμ]+)(\d)$', sym)
    if packed:
        base = _symbol_dim(packed.group(1))
        if len(base.powers) == 1 and 'm' in base.powers:
            return base.pow(int(packed.group(2)))  # type: ignore[return-value]
    name = ALIAS.get(sym, sym)
    if name in PREFIXABLE:
        return _mass_dim(name, 1)
    return _prefixed(name) or Dim({name: 1})


def parse_unit(text: Any) -> Optional[Dim]:
    """A unit's text as a :class:`Dim`, or None when it cannot be read."""
    src = str(text if text is not None else '').strip()
    if src.lower() in _NONE:
        return Dim.one()
    if re.match(r'^\[.*\]$', src, re.S):
        src = src[1:-1].strip()
    if src.lower() in _NONE:
        return Dim.one()
    max_depth = 32
    state = {'at': 0, 'depth': 0}

    def skip() -> None:
        while state['at'] < len(src) and src[state['at']] == ' ':
            state['at'] += 1

    def number() -> Optional[float]:
        m = re.match(r'^[+-]?\d+(\.\d+)?', src[state['at']:])
        if not m:
            return None
        state['at'] += len(m.group(0))
        return float(m.group(0))

    def factor() -> Optional[Dim]:
        skip()
        at = state['at']
        if at < len(src) and src[at] == '(':
            if state['depth'] >= max_depth:
                return None
            state['at'] += 1
            state['depth'] += 1
            inner = expr()
            state['depth'] -= 1
            skip()
            if state['at'] >= len(src) or src[state['at']] != ')':
                return None
            state['at'] += 1
            return inner
        m = re.match(r'^[A-Za-z_µμ%][A-Za-z0-9_µμ%.]*', src[at:])
        if m:
            state['at'] += len(m.group(0))
            if m.group(0) == 'per':
                return None
            dim: Optional[Dim] = _symbol_dim(m.group(0))
            bare = re.match(r'^-\d+', src[state['at']:])
            if bare:
                state['at'] += len(bare.group(0))
                dim = dim.pow(float(bare.group(0))) if dim else None
            return dim
        n = number()
        return None if n is None else Dim.one()

    def term() -> Optional[Dim]:
        base = factor()
        if base is None:
            return None
        before = state['at']
        skip()
        if state['at'] >= len(src) or src[state['at']] != '^':
            state['at'] = before
        if state['at'] < len(src) and src[state['at']] == '^':
            state['at'] += 1
            skip()
            if state['at'] < len(src) and src[state['at']] == '(':
                state['at'] += 1
                n = number()
                skip()
                if n is not None and state['at'] < len(src) and src[state['at']] == '/':
                    state['at'] += 1
                    skip()
                    d = number()
                    if d is None or d == 0:
                        return None
                    n /= d
                    skip()
                if n is None or state['at'] >= len(src) or src[state['at']] != ')':
                    return None
                state['at'] += 1
            else:
                n = number()
            if n is None:
                return None
            base = base.pow(n)
            if base is None:
                return None
        return base

    def expr() -> Optional[Dim]:
        out = term()
        if out is None:
            return None
        while True:
            save = state['at']
            skip()
            ch = src[state['at']] if state['at'] < len(src) else ''
            if ch in ('*', '·'):
                state['at'] += 1
                nxt = term()
                if nxt is None:
                    return None
                out = out.times(nxt)
            elif ch == '/':
                state['at'] += 1
                nxt = term()
                if nxt is None:
                    return None
                out = out.over(nxt)
            elif re.match(r'^per\b', src[state['at']:]):
                state['at'] += 3
                rest = expr()
                if rest is None:
                    return None
                return out.over(rest)
            elif ch and re.match(r'[A-Za-z_(µμ%]', ch) and save != state['at']:
                nxt = term()
                if nxt is None:
                    return None
                out = out.times(nxt)
            else:
                state['at'] = save
                break
        return out

    value = expr()
    skip()
    return value if value is not None and state['at'] >= len(src) else None


def same_unit(a: Any, b: Any) -> bool:
    x, y = parse_unit(a), parse_unit(b)
    return x is not None and y is not None and x.equals(y)


class UnitClash(ValueError):
    pass


def _clash_note(l: Optional[Dim], r: Optional[Dim]) -> str:
    if l is None or not l.same_kind(r):
        return ''
    f = l.factor(r)  # type: ignore[arg-type]
    return (f' — the same quantity, a factor of {scale_text(f if f >= 1 else 1 / f)} apart; only a literal written '
            'directly against the other side is converted, so the factor is yours to write in here')


def _agree(dims: List[Optional[Dim]], what: str) -> Optional[Dim]:
    out: Optional[Dim] = None
    for d in dims:
        if d is None:
            return None
        if out is None or out.is_one:
            out = d
            continue
        if d.is_one or out.equals(d):
            continue
        raise UnitClash(f'{what} do not agree: {out} and {d}')
    return out


PURE = {'exp', 'log', 'log10', 'log2', 'ln', 'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'sinh', 'cosh', 'tanh',
        'asinh', 'acosh', 'atanh', 'erf', 'erfc', 'factorial', 'binomial'}
SAME = {'abs', 'fabs', 'ceil', 'floor', 'round', 'fix', 'min', 'max', 'mean', 'percentile'}
CLOCK = {'time', 'start_time', 'end_time'}
_COMPARE = {'==', '!=', '<', '>', '<=', '>=', '~=', '&&', '||'}


def equation_unit(ast: Node, unit_of: Callable[[str], Optional[Dim]], time_dim: Optional[Dim]) -> Dict[str, Any]:
    """The unit an equation comes out in, or the clash that stops it having one."""
    def walk(node: Optional[Node]) -> Optional[Dim]:
        if node is None:
            return None
        t = node.type
        if t == 'num':
            if node.dim is not None:  # type: ignore[attr-defined]
                return node.dim  # type: ignore[attr-defined]
            if node.unit is None:  # type: ignore[attr-defined]
                return Dim.one()
            return parse_unit(node.unit)  # type: ignore[attr-defined]
        if t == 'ref':
            return unit_of(node.name)  # type: ignore[attr-defined]
        if t == 'unary':
            return Dim.one() if node.op == '!' else walk(node.operand)  # type: ignore[attr-defined]
        if t == 'binary':
            op = node.op  # type: ignore[attr-defined]
            if op in _COMPARE:
                l = walk(node.left)  # type: ignore[attr-defined]
                r = walk(node.right)  # type: ignore[attr-defined]
                if l and r and not l.is_one and not r.is_one and not l.equals(r):
                    raise UnitClash(f'{l} and {r} cannot be compared{_clash_note(l, r)}')
                return Dim.one()
            l = walk(node.left)  # type: ignore[attr-defined]
            r = walk(node.right)  # type: ignore[attr-defined]
            if op in ('*', '.*'):
                return l.times(r) if l and r else None
            if op in ('/', './'):
                return l.over(r) if l and r else None
            if op in ('^', '.^'):
                if l is None:
                    return None
                if l.is_one:
                    return Dim.one()
                if node.right.type != 'num':  # type: ignore[attr-defined]
                    return None
                return l.pow(node.right.value)  # type: ignore[attr-defined]
            if l is None or r is None:
                return None
            if l.is_one:
                return r
            if r.is_one:
                return l
            if not l.equals(r):
                raise UnitClash(f"{l} and {r} cannot be {'subtracted' if op == '-' else 'added'}{_clash_note(l, r)}")
            return l
        if t == 'cond':
            walk(node.test)  # type: ignore[attr-defined]
            return _agree([walk(node.then), walk(node.otherwise)], 'the two results')  # type: ignore[attr-defined]
        if t == 'call':
            name = node.name  # type: ignore[attr-defined]
            args = [walk(a) for a in node.args]  # type: ignore[attr-defined]
            if name in CLOCK:
                return time_dim
            if name in PURE:
                a = args[0] if args else None
                if a and not a.is_one:
                    raise UnitClash(f'{name} needs a plain number, not {a}')
                return Dim.one()
            if name == 'sqrt':
                return args[0].pow(0.5) if args and args[0] else None
            if name in ('power', 'pow'):
                if not args or args[0] is None:
                    return None
                if args[0].is_one:
                    return Dim.one()
                second = node.args[1] if len(node.args) > 1 else None  # type: ignore[attr-defined]
                if second is None or second.type != 'num':
                    return None
                return args[0].pow(second.value)  # type: ignore[attr-defined]
            if name == 'if':
                return _agree(args[1:], 'the two results of if')
            if name in ('rampUp', 'rampDown'):
                _agree(args, f'the argument and the two ends of {name}')
                return Dim.one()
            if name in ('smoothUp', 'smoothDown'):
                _agree(args[:2], f'the argument and the half-way point of {name}')
                if len(args) > 2 and args[2] and not args[2].is_one:
                    raise UnitClash(f'the sharpness of {name} is a plain number, not {args[2]}')
                return Dim.one()
            if name in ('mod', 'rem'):
                return args[0] if args else None
            if name in ('atan2', 'sign', 'sgn'):
                return Dim.one()
            if name == 'hypot':
                return _agree(args, 'the arguments of hypot')
            if name in ('sum', 'prod', 'product'):
                return _agree(args, 'the arguments of sum') if name == 'sum' else None
            if name in SAME:
                return _agree(args, f'the arguments of {name}')
            return None
        return None

    try:
        return {'dim': walk(ast), 'clash': None}
    except UnitClash as e:
        return {'dim': None, 'clash': str(e)}


_AGREE_OPS = {'+', '-', '==', '!=', '<', '>', '<=', '>=', '~='}
_AGREE_CALLS = {'min', 'max', 'if', 'ifelse'}
_CHILDREN = ('left', 'right', 'operand', 'test', 'then', 'otherwise')


def has_unit_literal(node: Any) -> bool:
    if not isinstance(node, Node):
        return False
    if node.type == 'num':
        return node.unit is not None  # type: ignore[attr-defined]
    for key in _CHILDREN:
        child = getattr(node, key, None)
        if child is not None and has_unit_literal(child):
            return True
    return any(has_unit_literal(a) for a in getattr(node, 'args', None) or [])


def scale_literals(ast: Node, unit_of: Callable[[str], Optional[Dim]], time_dim: Optional[Dim]) -> Dict[str, List[Any]]:
    """Converts, in place, each literal written with a unit to the unit of what
    it is written against."""
    converted: List[Dict[str, Any]] = []
    unconverted: List[Dict[str, Any]] = []
    if not has_unit_literal(ast):
        return {'converted': converted, 'unconverted': unconverted}

    def dim_of(node: Node) -> Optional[Dim]:
        try:
            return equation_unit(node, unit_of, time_dim)['dim']
        except Exception:  # noqa: BLE001 - the unit of this piece is simply not known
            return None

    def literal(n: Any) -> bool:
        return isinstance(n, Node) and n.type == 'num' and n.unit is not None and n.dim is None  # type: ignore

    def against(lit: Node, other: Optional[Node]) -> None:
        want = dim_of(other) if other is not None else None
        here = dim_of(lit)
        if here is None or here.is_one:
            return
        if want is None:
            unconverted.append({'value': lit.value, 'unit': lit.unit})  # type: ignore[attr-defined]
            return
        if not want.same_kind(here) or want.equals(here):
            return
        f = here.factor(want)
        converted.append({'value': lit.value, 'from': str(here), 'to': str(want),  # type: ignore[attr-defined]
                          'now': lit.value * f})  # type: ignore[attr-defined]
        lit.value *= f  # type: ignore[attr-defined]
        lit.dim = want  # type: ignore[attr-defined]

    def reconcile(nodes: List[Any]) -> None:
        lits = [n for n in nodes if literal(n)]
        if not lits:
            return
        anchor = next((n for n in nodes if not literal(n) and dim_of(n) is not None), None)
        if anchor is None:
            anchor = next((n for n in nodes if n is not lits[0]), None)
        for lit in lits:
            if lit is anchor:
                continue
            against(lit, anchor)

    def walk(node: Any) -> None:
        if not isinstance(node, Node):
            return
        for key in _CHILDREN:
            child = getattr(node, key, None)
            if child is not None:
                walk(child)
        for a in getattr(node, 'args', None) or []:
            walk(a)
        t = node.type
        if t == 'binary' and node.op in _AGREE_OPS:  # type: ignore[attr-defined]
            reconcile([node.left, node.right])  # type: ignore[attr-defined]
        elif t == 'cond':
            reconcile([node.then, node.otherwise])  # type: ignore[attr-defined]
        elif t == 'call' and node.name in _AGREE_CALLS:  # type: ignore[attr-defined]
            args = list(node.args)  # type: ignore[attr-defined]
            reconcile(args[1:] if node.name in ('if', 'ifelse') else args)  # type: ignore[attr-defined]

    walk(ast)
    return {'converted': converted, 'unconverted': unconverted}
