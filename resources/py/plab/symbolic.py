"""Symbolic values, sym and symfun, on SymPy.

A Sym holds a 2-D object array of SymPy expressions; a symbolic function
(symfun) also holds its arguments, the Symbols its formula is in. SymPy is
imported the first time a symbolic value is made: in the page Pyodide
loads it then (ensure). The operators, indexing, concatenation, conditions
and the Command Window's display come here through the hooks install()
sets in ops, index and display; the functions of symbolic values are in
builtins/symmath.py.

Symbols are complex unless assumed otherwise, as in the language. NAMES
keeps each name's current Symbol (with its assumptions, which assume
changes), and expressions are brought up to date with it (fresh) before
they are worked on.
"""
import math
import re
import sys
from fractions import Fraction

import numpy as np

from .values import MError, Obj, Char, Cell, Str, NOVAL, EMPTY, F64, py_str, is_empty_double

_SP = None
NAMES = {}            # name -> the Symbol that name stands for now
RELS = {}             # name -> relations assumed of it that SymPy's assumptions cannot hold (x > 2)
DIGITS = [32]         # vpa's significant digits


def sp():
    global _SP
    if _SP is None:
        import sympy
        _SP = sympy
    return _SP


async def ensure():
    """SymPy, imported; in the page, Pyodide loads the package the first time."""
    global _SP
    if _SP is not None:
        return _SP
    try:
        import sympy
    except ImportError:
        if sys.platform != 'emscripten':
            raise MError('symbolic:sympy', 'The symbolic functions need the SymPy package (pip install sympy).')
        import pyodide_js
        await pyodide_js.loadPackage('sympy')
        import sympy
    _SP = sympy
    return sympy


class Sym(Obj):
    """A symbolic array (2-D object array of SymPy expressions), or a
    symbolic function of fargs."""
    __slots__ = ('a', 'fargs')
    is_handle = False

    def __init__(self, a, fargs=None):
        self.a = a
        self.fargs = fargs

    @property
    def shape(self):
        return (1, 1) if self.fargs is not None else self.a.shape

    @property
    def cls(self):
        return 'symfun' if self.fargs is not None else 'sym'

    def value_copy(self):
        return self

    def propnames(self):
        return []

    def display_lines(self):
        return lines_of(self)

    @property
    def item(self):
        return self.a[0, 0]


def S(e, fargs=None):
    """A 1x1 Sym of one expression."""
    a = np.empty((1, 1), object)
    a[0, 0] = e
    return Sym(a, fargs)


def of_array(a, fargs=None):
    a = np.asarray(a, object)
    if a.ndim < 2:
        a = a.reshape(1, -1) if a.ndim == 1 else a.reshape(1, 1)
    return Sym(a, fargs)


# ---- numbers as exact symbolic values ------------------------------------------------------------------

def num2sym(x, flag='r'):
    """A double as a symbolic number. 'r' (the default) finds p/q, p*pi/q,
    sqrt(p)/q or 2^k that the double is exactly; 'f' is the double's own
    binary fraction; 'd' a decimal of the current digits."""
    s = sp()
    if isinstance(x, (complex, np.complexfloating)):
        re_, im_ = num2sym(float(x.real), flag), num2sym(float(x.imag), flag)
        return re_ + s.I * im_ if im_ != 0 else re_
    x = float(x)
    if x != x:
        return s.nan
    if math.isinf(x):
        return s.oo if x > 0 else -s.oo
    if x == int(x) and abs(x) < 2 ** 63:
        return s.Integer(int(x))
    if flag == 'd':
        return s.Float(x, DIGITS[0])
    if flag != 'f':
        fr = Fraction(x).limit_denominator(10 ** 7)
        if float(fr) == x:
            return s.Rational(fr.numerator, fr.denominator)
        fp = Fraction(x / math.pi).limit_denominator(10 ** 4)
        if fp != 0 and float(fp.numerator * math.pi / fp.denominator) == x:
            return s.Rational(fp.numerator, fp.denominator) * s.pi
        sq = Fraction(x * x).limit_denominator(10 ** 4)
        if sq > 0 and math.copysign(math.sqrt(float(sq)), x) == x:
            r = s.sqrt(s.Rational(sq.numerator, sq.denominator))
            return r if x > 0 else -r
    fr = Fraction(x)
    return s.Rational(fr.numerator, fr.denominator)


def to_expr(v, what='input'):
    """One value of the language as one SymPy expression."""
    a = arr_of(v)
    if a.size != 1:
        raise MError('symbolic:sym:NotScalar', f'The {what} must be a scalar.')
    return a[0, 0]


def arr_of(v):
    """Any value as a 2-D object array of SymPy expressions."""
    t = type(v)
    if t is Sym:
        return v.a
    s = sp()
    if t is float or t is int or t is complex:
        a = np.empty((1, 1), object)
        a[0, 0] = num2sym(v)
        return a
    if t is bool:
        a = np.empty((1, 1), object)
        a[0, 0] = s.true if v else s.false
        return a
    if t is np.ndarray:
        if v.ndim > 2:
            raise MError('symbolic:sym:ND', 'Symbolic arrays here have two dimensions.')
        out = np.empty(v.shape if v.ndim == 2 else (1, v.size), object)
        flat = v.reshape(out.shape)
        if v.dtype.kind == 'b':
            for i, x in np.ndenumerate(flat):
                out[i] = s.true if x else s.false
        else:
            for i, x in np.ndenumerate(flat):
                out[i] = num2sym(complex(x) if np.iscomplexobj(flat) else float(x))
        return out
    if t is Char or t is Str:
        e = parse_text(py_str(v))
        a = np.empty((1, 1), object)
        a[0, 0] = e
        return a
    raise MError('symbolic:sym:Conversion', f'Conversion to sym from {getattr(v, "cls", t.__name__)} is not possible.')


def fresh(e):
    """e with each Symbol replaced by its name's current one (assumptions)."""
    if not NAMES or not hasattr(e, 'free_symbols'):
        return e
    rep = {x: NAMES[x.name] for x in e.free_symbols if x.name in NAMES and NAMES[x.name] is not x}
    return e.xreplace(rep) if rep else e


def symbol(name):
    """The Symbol a name stands for (complex unless assumed otherwise)."""
    x = NAMES.get(name)
    if x is None:
        x = sp().Symbol(name)
        NAMES[name] = x
    return x


_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]*$')


def parse_text(text):
    """A number or a name as sym('...') takes them; an expression too."""
    s = sp()
    t = text.strip()
    if _NAME.match(t):
        if t in ('pi',):
            return s.pi
        if t in ('Inf', 'inf'):
            return s.oo
        if t in ('NaN', 'nan'):
            return s.nan
        if t in ('i', 'j', '1i'):
            return s.I
        return symbol(t)
    return from_language(t)


def from_language(text):
    """An expression in the language's syntax (str2sym) as a SymPy
    expression: its operators and function names translated, names as
    symbols."""
    s = sp()
    src = text.strip()
    # the operators: element-wise ones are the same for scalars; ~= and ~ before ==
    src = src.replace('.^', '^').replace('.*', '*').replace('./', '/')
    src = re.sub(r'~=', '!=', src)
    src = re.sub(r'~(?!=)', ' ~', src)
    src = src.replace('^', '**')
    src = re.sub(r'(?<![\w.])(\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[ij]\b', lambda m: f'({m.group(0)[:-1]})*I', src)
    names = {}
    for w in set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', src)):
        if w in _FROM_LANG:
            names[w] = _FROM_LANG[w]()
        elif w in ('i', 'j'):
            names[w] = s.I
        elif w == 'I':
            names[w] = symbol('I')
        elif w not in ('and', 'or', 'not'):
            names[w] = symbol(w)
    from sympy.parsing.sympy_parser import parse_expr, standard_transformations
    src = src.replace('&&', '&').replace('||', '|')
    rel = re.split(r'(==|!=|<=|>=|<|>)', src)
    try:
        if len(rel) == 3 or len(rel) > 3 and not re.search(r'[&|]', src):
            # 0 < x < 1 is 0 < x & x < 1
            sides = [parse_expr(t, local_dict=names, transformations=standard_transformations, evaluate=True) for t in rel[0::2]]
            ops = {'==': s.Eq, '!=': s.Ne, '<=': s.Le, '>=': s.Ge, '<': s.Lt, '>': s.Gt}
            parts = [ops[o](L, Rr, evaluate=False) for L, o, Rr in zip(sides, rel[1::2], sides[1:])]
            return parts[0] if len(parts) == 1 else s.And(*parts)
        return parse_expr(src, local_dict=names, transformations=standard_transformations, evaluate=True)
    except (SyntaxError, TypeError, ValueError, AttributeError) as e:
        raise MError('symbolic:str2sym:Invalid', f"Unable to read '{text}' as a symbolic expression.")


def _lang_names():
    s = sp()
    return {'sin': s.sin, 'cos': s.cos, 'tan': s.tan, 'cot': s.cot, 'sec': s.sec, 'csc': s.csc, 'asin': s.asin, 'acos': s.acos,
            'atan': s.atan, 'acot': s.acot, 'asec': s.asec, 'acsc': s.acsc, 'sinh': s.sinh, 'cosh': s.cosh, 'tanh': s.tanh,
            'coth': s.coth, 'sech': s.sech, 'csch': s.csch, 'asinh': s.asinh, 'acosh': s.acosh, 'atanh': s.atanh, 'acoth': s.acoth,
            'exp': s.exp, 'log': s.log, 'sqrt': s.sqrt, 'abs': s.Abs, 'sign': s.sign, 'real': s.re, 'imag': s.im, 'conj': s.conjugate,
            'angle': s.arg, 'floor': s.floor, 'ceil': s.ceiling, 'gamma': s.gamma, 'factorial': s.factorial, 'erf': s.erf,
            'erfc': s.erfc, 'heaviside': s.Heaviside, 'dirac': s.DiracDelta, 'besselj': s.besselj, 'bessely': s.bessely,
            'besseli': s.besseli, 'besselk': s.besselk, 'atan2': s.atan2, 'nchoosek': s.binomial, 'mod': s.Mod, 'max': s.Max,
            'min': s.Min, 'pi': s.pi, 'Inf': s.oo, 'inf': s.oo, 'NaN': s.nan, 'nan': s.nan, 'log2': lambda x: s.log(x, 2),
            'log10': lambda x: s.log(x, 10), 'zeta': s.zeta, 'lambertw': s.LambertW, 'sinc': lambda x: s.sin(x) / x,
            'nthroot': lambda x, n: s.root(x, n), 'psi': s.digamma, 'sinint': s.Si, 'cosint': s.Ci, 'kroneckerDelta': s.KroneckerDelta,
            'diff': s.diff, 'int': s.integrate}


class _FromLang(dict):
    def __missing__(self, k):
        raise KeyError(k)

    def __contains__(self, k):
        return k in _lang_names()

    def __getitem__(self, k):
        f = _lang_names()[k]
        return lambda: f


_FROM_LANG = _FromLang()


# ---- the language's syntax out ----------------------------------------------------------------------------

_PRINTER = [None]
_FUNC_NAMES = {'Abs': 'abs', 're': 'real', 'im': 'imag', 'conjugate': 'conj', 'arg': 'angle', 'ceiling': 'ceil', 'Heaviside': 'heaviside',
               'DiracDelta': 'dirac', 'Max': 'max', 'Min': 'min', 'binomial': 'nchoosek', 'Mod': 'mod', 'LambertW': 'lambertw',
               'KroneckerDelta': 'kroneckerDelta', 'Si': 'sinint', 'Ci': 'cosint', 'Shi': 'sinhint', 'Chi': 'coshint', 'Ei': 'ei',
               'li': 'logint', 'digamma': 'psi', 'loggamma': 'gammaln', 'fresnels': 'fresnels', 'fresnelc': 'fresnelc',
               'airyai': 'airy', 'sign': 'sign', 'factorial': 'factorial', 'gamma': 'gamma'}


def _printer():
    if _PRINTER[0] is not None:
        return _PRINTER[0]
    s = sp()
    from sympy.printing.str import StrPrinter
    from sympy.printing.precedence import precedence

    class P(StrPrinter):
        def _paren(self, e, level):
            return self.parenthesize(e, level)

        def _print_ImaginaryUnit(self, e):
            return '1i'

        def _print_Exp1(self, e):
            return 'exp(1)'

        def _print_Infinity(self, e):
            return 'Inf'

        def _print_NegativeInfinity(self, e):
            return '-Inf'

        def _print_ComplexInfinity(self, e):
            return 'Inf'

        def _print_NaN(self, e):
            return 'NaN'

        def _print_BooleanTrue(self, e):
            return 'symtrue'

        def _print_BooleanFalse(self, e):
            return 'symfalse'

        def _print_Equality(self, e):
            return f'{self._print(e.lhs)} == {self._print(e.rhs)}'

        def _print_Unequality(self, e):
            return f'{self._print(e.lhs)} ~= {self._print(e.rhs)}'

        def _print_And(self, e):
            return ' & '.join(self._paren(a, precedence(e)) for a in _chain_order(e.args))

        def _print_Or(self, e):
            return ' | '.join(self._paren(a, precedence(e)) for a in e.args)

        def _print_Not(self, e):
            return '~' + self._paren(e.args[0], precedence(e) + 1)

        def _print_Pow(self, e, rational=False):
            return super()._print_Pow(e, rational).replace('**', '^')

        def _print_Float(self, e):
            t = super()._print_Float(e)
            if 'e' not in t and '.' in t:
                t = t.rstrip('0')
                if t.endswith('.'):
                    t += '0'
            return t

        def _print_Function(self, e):
            name = type(e).__name__
            name = _FUNC_NAMES.get(name, name)
            if name in ('heaviside', 'dirac') and len(e.args) == 2:
                if name == 'dirac':
                    return f'dirac({self._print(e.args[1])}, {self._print(e.args[0])})'
                return f'heaviside({self._print(e.args[0])})'
            if name == 'log' and len(e.args) == 2:
                return f'log({self._print(e.args[0])})/log({self._print(e.args[1])})'
            return f"{name}({', '.join(self._print(a) for a in e.args)})"

        _print_Abs = _print_re = _print_im = _print_conjugate = _print_arg = _print_sign = _print_Function
        _print_Heaviside = _print_DiracDelta = _print_ceiling = _print_floor = _print_Function
        _print_Max = _print_Min = _print_binomial = _print_LambertW = _print_KroneckerDelta = _print_Function
        _print_factorial = _print_gamma = _print_Function

        def _print_LaplaceTransform(self, e):
            return f"laplace({', '.join(self._print(a) for a in e.args[:3])})"

        def _print_InverseLaplaceTransform(self, e):
            return f"ilaplace({', '.join(self._print(a) for a in e.args[:3])})"

        def _print_FourierTransform(self, e):
            return f"fourier({', '.join(self._print(a) for a in e.args[:3])})"

        def _print_InverseFourierTransform(self, e):
            return f"ifourier({', '.join(self._print(a) for a in e.args[:3])})"

        def _print_Mod(self, e):
            return f'mod({self._print(e.args[0])}, {self._print(e.args[1])})'

        def _print_Piecewise(self, e):
            parts = []
            args = e.args
            if len(args) > 1 and args[-1].cond is s.true and args[-1].expr is s.nan:
                # no otherwise given
                args = args[:-1]
            for val, cond in args:
                if cond is s.true:
                    parts.append(self._print(val))
                else:
                    parts += [self._print(cond), self._print(val)]
            return 'piecewise(' + ', '.join(parts) + ')'

        def _print_Derivative(self, e):
            out = [self._print(e.expr)]
            for v, n in e.variable_count:
                out.append(self._print(v))
                if n != 1:
                    out.append(str(n))
            return 'diff(' + ', '.join(out) + ')'

        def _print_Integral(self, e):
            f = self._print(e.function)
            for lim in e.limits:
                if len(lim) == 3:
                    f = f'int({f}, {self._print(lim[0])}, {self._print(lim[1])}, {self._print(lim[2])})'
                else:
                    f = f'int({f}, {self._print(lim[0])})'
            return f

        def _print_Sum(self, e):
            f = self._print(e.function)
            for v, a, b in e.limits:
                f = f'symsum({f}, {self._print(v)}, {self._print(a)}, {self._print(b)})'
            return f

        def _print_Product(self, e):
            f = self._print(e.function)
            for v, a, b in e.limits:
                f = f'symprod({f}, {self._print(v)}, {self._print(a)}, {self._print(b)})'
            return f

        def _print_Subs(self, e):
            expr, old, new = e.args
            if len(old) == 1:
                return f'subs({self._print(expr)}, {self._print(old[0])}, {self._print(new[0])})'
            return f"subs({self._print(expr)}, [{', '.join(map(self._print, old))}], [{', '.join(map(self._print, new))}])"

        def _print_ComplexRootOf(self, e):
            return f'root({self._print(e.expr)}, {self._print(e.poly.gen)}, {e.index + 1})'

        def _print_CRootOf(self, e):
            return self._print_ComplexRootOf(e)

        def _print_Contains(self, e):
            x, st = e.args
            word = {s.Integers: 'integer', s.Reals: 'real', s.Rationals: 'rational', s.Complexes: 'complex',
                    s.Naturals: 'positive integer', s.Naturals0: 'nonnegative integer'}.get(st)
            if word is None:
                return f'in({self._print(x)}, {self._print(st)})'
            return f"in({self._print(x)}, '{word}')"

        def _print_Lambda(self, e):
            return f"@({', '.join(map(self._print, e.variables))}) {self._print(e.expr)}"

    _PRINTER[0] = P(settings={'order': None})
    return _PRINTER[0]


_I_AFTER_NUM = re.compile(r'(?<![\w.])(\d+(?:\.\d+)?(?:e[+-]?\d+)?)\*1i\b')


def text(e):
    """An expression in the language's syntax."""
    t = _printer().doprint(e).replace('**', '^')
    return _I_AFTER_NUM.sub(r'\1i', t)


def lines_of(v):
    """The lines that show a symbolic value."""
    a = v.a
    if a.size == 0:
        return [f'Empty sym: {a.shape[0]}-by-{a.shape[1]}']
    if a.size == 1 and v.fargs is None:
        return [text(a[0, 0])]
    if v.fargs is not None and a.size == 1:
        return [text(a[0, 0])]
    cells = [[text(a[i, j]) for j in range(a.shape[1])] for i in range(a.shape[0])]
    w = [max(len(cells[i][j]) for i in range(a.shape[0])) for j in range(a.shape[1])]
    return ['[' + ', '.join(cells[i][j].rjust(w[j]) for j in range(a.shape[1])) + ']' for i in range(a.shape[0])]


def display(name, v):
    from .display import FMT
    loose = FMT['spacing'] == 'loose'
    head = f"{name}({', '.join(text(x) for x in v.fargs)}) =" if v.fargs is not None else f'{name} ='
    out = [head]
    if loose:
        out.append('')
    out += lines_of(v)
    if loose:
        out.append('')
    return '\n'.join(out) + '\n'


def disp_text(v):
    return '\n'.join(lines_of(v)) + '\n'


# ---- operators -------------------------------------------------------------------------------------------

def _bcast(A, B, sym):
    if A.shape == B.shape or A.size == 1 or B.size == 1:
        return np.broadcast_arrays(A, B)
    try:
        return np.broadcast_arrays(A, B)
    except ValueError:
        raise MError('MATLAB:sizeDimensionsMustMatch', f'Arrays have incompatible sizes for this operation ({sym}).')


def _each(fn, *arrs):
    out = np.empty(arrs[0].shape, object)
    for idx in np.ndindex(out.shape):
        out[idx] = fn(*(a[idx] for a in arrs))
    return out


def _fargs(a, b):
    fa = a.fargs if type(a) is Sym else None
    fb = b.fargs if type(b) is Sym else None
    return fa if fa is not None else fb


def _rel(op):
    s = sp()
    return {'==': lambda x, y: s.Eq(x, y, evaluate=False), '~=': lambda x, y: s.Ne(x, y, evaluate=False),
            '<': lambda x, y: s.Lt(x, y, evaluate=False), '<=': lambda x, y: s.Le(x, y, evaluate=False),
            '>': lambda x, y: s.Gt(x, y, evaluate=False), '>=': lambda x, y: s.Ge(x, y, evaluate=False)}[op]


def _chain_end(e):
    """The right end of a chain of comparisons on the left of another (0 < x < 1 is 0 < x & x < 1), or None."""
    s = sp()
    order = (s.StrictLessThan, s.LessThan, s.StrictGreaterThan, s.GreaterThan)
    if isinstance(e, order):
        return e.rhs
    if isinstance(e, s.And) and all(isinstance(r, order) for r in e.args):
        ends = {r.rhs for r in e.args} - {r.lhs for r in e.args}
        if len(ends) == 1:
            return ends.pop()
    return None


def _chain_order(args):
    """The parts of a conjunction in the order of their chain (0 < x, x < y, y < 1), else as they are."""
    s = sp()
    order = (s.StrictLessThan, s.LessThan, s.StrictGreaterThan, s.GreaterThan)
    if not all(isinstance(r, order) for r in args):
        return args
    by_lhs = {r.lhs: r for r in args}
    starts = set(by_lhs) - {r.rhs for r in args}
    if len(by_lhs) != len(args) or len(starts) != 1:
        return args
    out, at = [], starts.pop()
    while at in by_lhs and len(out) < len(args):
        out.append(by_lhs[at])
        at = out[-1].rhs
    return out if len(out) == len(args) else args


def _chain(op):
    s = sp()
    rel = _rel(op)
    if op in ('==', '~='):
        return rel

    def f(x, y):
        end = _chain_end(x)
        # (a Symbol is a Boolean in SymPy)
        if end is None or isinstance(y, (s.core.relational.Relational, s.logic.boolalg.BooleanFunction, s.logic.boolalg.BooleanAtom)):
            return rel(x, y)
        return s.And(x, rel(end, y))
    return f


def _boolean(e):
    s = sp()
    if isinstance(e, (s.logic.boolalg.Boolean, s.core.relational.Relational)):
        return e
    if e.is_zero:
        return s.false
    if e.is_zero is False:
        return s.true
    return s.Ne(e, 0, evaluate=False)


def _sides(fn, kinds=None):
    """fn of two expressions, applied to each side of an equation: (a == b)/m is a/m == b/m, and
    (a == b) + (c == d) is a + c == b + d. kinds: the relations it goes through (equations unless given)."""
    s = sp()
    kinds = kinds or (s.Eq,)

    def f(x, y):
        kx, ky = isinstance(x, kinds), isinstance(y, kinds)
        if kx and ky and type(x) is type(y):
            return type(x)(fn(x.lhs, y.lhs), fn(x.rhs, y.rhs), evaluate=False)
        if kx and not isinstance(y, s.core.relational.Relational):
            return type(x)(fn(x.lhs, y), fn(x.rhs, y), evaluate=False)
        if ky and not isinstance(x, s.core.relational.Relational):
            return type(y)(fn(x, y.lhs), fn(x, y.rhs), evaluate=False)
        return fn(x, y)
    return f


def binop(op, a, b):
    s = sp()
    A, B = arr_of(a), arr_of(b)
    fa = _fargs(a, b)
    if op in ('+', '-', '.*', './', '.\\', '.^', '==', '~=', '<', '<=', '>', '>=', '&', '|'):
        X, Y = _bcast(A, B, op)
        # adding to both sides keeps an inequality too
        both = (s.Eq, s.Ne, s.StrictLessThan, s.LessThan, s.StrictGreaterThan, s.GreaterThan)
        if op == '+':
            r = _each(_sides(lambda x, y: x + y, both), X, Y)
        elif op == '-':
            r = _each(_sides(lambda x, y: x - y, both), X, Y)
        elif op == '.*':
            r = _each(_sides(lambda x, y: x * y), X, Y)
        elif op == './':
            r = _each(_sides(lambda x, y: x / y), X, Y)
        elif op == '.\\':
            r = _each(_sides(lambda x, y: y / x), X, Y)
        elif op == '.^':
            r = _each(_sides(lambda x, y: x ** y), X, Y)
        elif op in ('&', '|'):
            f = s.And if op == '&' else s.Or
            r = _each(lambda x, y: f(_boolean(x), _boolean(y)), X, Y)
        else:
            r = _each(_chain(op), X, Y)
        return Sym(r, fa)
    if op == '*':
        if A.size == 1 or B.size == 1:
            return binop('.*', a, b)
        if A.shape[1] != B.shape[0]:
            raise MError('MATLAB:innerdim', 'Incorrect dimensions for matrix multiplication.')
        return Sym(_np(s.Matrix(A.tolist()) * s.Matrix(B.tolist())), fa)
    if op == '/':
        if B.size == 1:
            return binop('./', a, b)
        # A/B is (B.'\A.').'
        return Sym(_np((s.Matrix(B.T.tolist()).solve(s.Matrix(A.T.tolist()))).T), fa) if B.shape[0] == B.shape[1] else _lsq('/', A, B, fa)
    if op == '\\':
        if A.size == 1:
            return binop('.\\', a, b)
        if A.shape[0] != B.shape[0]:
            raise MError('MATLAB:dimagree', 'Matrix dimensions must agree.')
        if A.shape[0] == A.shape[1]:
            M = s.Matrix(A.tolist())
            if M.det() == 0:
                raise MError('symbolic:mldivide:Singular', 'The matrix is singular: the system has no unique solution.')
            return Sym(_np(M.LUsolve(s.Matrix(B.tolist()))), fa)
        return _lsq('\\', A, B, fa)
    if op == '^':
        if A.size == 1 and B.size == 1:
            return Sym(_each(_sides(lambda x, y: x ** y), A, B), fa)
        if A.shape[0] == A.shape[1] and B.size == 1:
            return Sym(_np(s.Matrix(A.tolist()) ** B[0, 0]), fa)
        raise MError('MATLAB:mpower', 'Incorrect dimensions for raising a matrix to a power: the matrix must be square and the power a scalar.')
    raise MError('symbolic:op', f'The operator {op} is not defined for sym.')


def _lsq(op, A, B, fa):
    s = sp()
    if op == '\\':
        sol, params = s.Matrix(A.tolist()).gauss_jordan_solve(s.Matrix(B.tolist()))
        return Sym(_np(sol.subs({p: 0 for p in params})), fa)
    return Sym(_np(_lsq('\\', B.T, A.T, None).a.T), fa)


def _np(M):
    """A SymPy Matrix as a 2-D object array."""
    rows, cols = M.shape
    a = np.empty((rows, cols), object)
    for i in range(rows):
        for j in range(cols):
            a[i, j] = M[i, j]
    return a


def unop(op, a):
    s = sp()
    A = arr_of(a)
    fa = a.fargs if type(a) is Sym else None
    if op == '-':
        return Sym(_each(lambda x: type(x)(-x.lhs, -x.rhs, evaluate=False) if isinstance(x, (s.Eq, s.Ne)) else -x, A), fa)
    if op == '+':
        return Sym(A, fa)
    if op == '~':
        return Sym(_each(lambda x: s.Not(_boolean(x)), A), fa)
    if op == ".'":
        return Sym(A.T.copy(), fa)
    if op == "'":
        return Sym(_each(lambda x: s.conjugate(x), A.T.copy()), fa)
    raise MError('symbolic:op', f'The operator {op} is not defined for sym.')


_ELIM = [None, {}]


def _elimination():
    """The relations assumed between variables (RELS) as substitutions that make them hold: a < b becomes
    b = a + t with t > 0 (t >= 0 for <=), one variable a relation. A condition that is true or false after the
    substitution is so for every value the relations allow (the substituted values cover them all)."""
    s = sp()
    facts = []
    for k in sorted(RELS):
        facts += [r for r in RELS[k] if r not in facts]
    key = tuple(facts)
    if _ELIM[0] == key:
        return _ELIM[1]
    elim = {}
    for r in facts:
        if isinstance(r, (s.StrictLessThan, s.LessThan)):
            a, b = r.lhs, r.rhs
        elif isinstance(r, (s.StrictGreaterThan, s.GreaterThan)):
            a, b = r.rhs, r.lhs
        else:
            continue
        a, b = a.xreplace(elim), b.xreplace(elim)
        t = s.Dummy('t', positive=True) if isinstance(r, (s.StrictLessThan, s.StrictGreaterThan)) else s.Dummy('t', nonnegative=True)
        if isinstance(b, s.Symbol) and not isinstance(b, s.Dummy) and b not in a.free_symbols:
            x, v = b, a + t
        elif isinstance(a, s.Symbol) and not isinstance(a, s.Dummy) and a not in b.free_symbols:
            x, v = a, b - t
        else:
            continue
        elim = {k: w.xreplace({x: v}) for k, w in elim.items()}
        elim[x] = v
    _ELIM[:] = [key, elim]
    return elim


def _by_rels(c, elim):
    """A condition's truth under the relations assumed: SymPy's true or false, or None."""
    s = sp()
    try:
        r = c.subs(elim)
    except (TypeError, ValueError):
        return None
    return r if r is s.true or r is s.false else None


def settle(e):
    """e (brought up to date with the assumptions) with each piecewise condition that the relations assumed
    decide made true or false, so that the piecewise keeps only what can hold."""
    s = sp()
    e = fresh(e)
    if not RELS or not hasattr(e, 'has') or not e.has(s.Piecewise):
        return e
    elim = _elimination()
    if not elim:
        return e

    def fix(p):
        # (SymPy's false is falsy: no `or` here)
        return s.Piecewise(*[(v, c if r is None else r) for v, c in p.args for r in [_by_rels(c, elim)]])
    return e.replace(lambda q: isinstance(q, s.Piecewise), fix)


def decide(e):
    """True or False for a condition that SymPy can settle; None otherwise."""
    s = sp()
    e = settle(e)
    if isinstance(e, (s.logic.boolalg.Boolean, s.core.relational.Relational)):
        if e is s.true or e is s.false:
            return e is s.true
        r = _by_rels(e, _elimination()) if RELS and not isinstance(e, s.Symbol) else None
        if r is not None:
            return r is s.true
        try:
            r = s.simplify(e)
        except Exception:
            r = e
        if r is s.true or r is s.false:
            return r is s.true
        if isinstance(e, s.Eq):
            d = s.simplify(e.lhs - e.rhs)
            if d.is_zero:
                return True
            if d.is_zero is False and not d.free_symbols:
                return False
        return None
    if e.is_zero:
        return False
    if e.is_zero is False:
        return True
    return None


def truth(v):
    """A symbolic condition of if or while: each element settled."""
    for e in v.a.flat:
        r = decide(e)
        if r is None:
            raise MError('symbolic:sym:isAlways:TruthUnknown',
                         f"Unable to prove '{text(e)}' literally. Use isAlways to test the statement mathematically.")
        if not r:
            return False
    return v.a.size > 0


def cat(axis, vals):
    parts = []
    fa = None
    for v in vals:
        if type(v) is Char:
            raise MError('symbolic:sym:CatChar', 'A character vector cannot be concatenated with a symbolic value: use char or str2sym.')
        if type(v) is np.ndarray and v.size == 0:
            continue
        a = arr_of(v)
        if type(v) is Sym and v.fargs is not None:
            fa = v.fargs
        if a.size:
            parts.append(a)
    if not parts:
        return Sym(np.empty((0, 0), object))
    try:
        r = np.concatenate(parts, axis=axis)
    except ValueError:
        raise MError('MATLAB:catenate:dimensionMismatch', 'Dimensions of arrays being concatenated are not consistent.')
    return Sym(r, fa)


# ---- indexing ---------------------------------------------------------------------------------------------

def _is_symbol(v):
    return type(v) is Sym and v.a.size == 1 and isinstance(v.a[0, 0], sp().Symbol)


def call(f, args):
    """A symbolic function at arguments: its formula with its arguments
    replaced (element by element for arrays of them)."""
    if len(args) != len(f.fargs):
        raise MError('symbolic:symfun:subsref:InvalidNumberOfArguments',
                     f'Symbolic function expected {len(f.fargs)} input arguments but received {len(args)}.')
    arrs = [arr_of(x) for x in args]
    sizes = {a.shape for a in arrs if a.size != 1}
    if len(sizes) > 1:
        raise MError('symbolic:symfun:subsref:Size', 'The arguments must be scalars or arrays of one size.')
    F = f.a
    if not sizes:
        rep = dict(zip(f.fargs, (a[0, 0] for a in arrs)))
        return Sym(_each(lambda e: settle(e.subs(rep, simultaneous=True)), F))
    if F.size != 1:
        raise MError('symbolic:symfun:subsref:Size', 'A function whose formula is an array takes scalar arguments.')
    shape = sizes.pop()
    out = np.empty(shape, object)
    for idx in np.ndindex(shape):
        rep = {x: (a[idx] if a.size != 1 else a[0, 0]) for x, a in zip(f.fargs, arrs)}
        out[idx] = settle(F[0, 0].subs(rep, simultaneous=True))
    return Sym(out)


def idx(A, args):
    from .index import take
    if A.fargs is not None:
        return call(A, args)
    for x in args:
        if type(x) is Sym:
            raise MError('symbolic:sym:subsref:InvalidIndex',
                         'Invalid indexing or function definition: indices must be positive integers or logicals, and a function '
                         'is defined as f(x) = expression with x symbolic variables.')
    return Sym(take(A.a, args))


def asgn(A, args, V):
    """A(args) = V where A or V is symbolic; f(x, y) = expression defines a symbolic function."""
    from .index import asgn as cell_asgn
    s = sp()
    if args and all(_is_symbol(x) for x in args) and type(V) is not Cell:
        names = [x.a[0, 0] for x in args]
        if len(set(names)) != len(names):
            raise MError('symbolic:symfun:Args', 'The arguments of a symbolic function must differ.')
        return Sym(arr_of(V).copy(), tuple(names))
    if type(A) is Sym and A.fargs is not None:
        A = Sym(A.a)
    base = np.empty((0, 0), object) if A is NOVAL else arr_of(A).copy()
    if is_empty_double(V):
        r = cell_asgn(Cell(base), args, EMPTY())
    else:
        r = cell_asgn(Cell(base), args, Cell(arr_of(V).copy()))
    a = r.a
    zero = s.Integer(0)
    for i in np.ndindex(a.shape):
        if not isinstance(a[i], s.Basic):
            a[i] = zero
    return Sym(a)


# ---- the hooks -----------------------------------------------------------------------------------------------

class _Ops:
    binop = staticmethod(binop)
    unop = staticmethod(unop)
    truth = staticmethod(truth)
    cat = staticmethod(cat)
    idx = staticmethod(idx)
    asgn = staticmethod(asgn)
    display = staticmethod(display)
    disp_text = staticmethod(disp_text)


def install():
    from . import ops, index, display as D
    ops.SYM = Sym
    ops.SYMOPS = _Ops
    index.SYM = Sym
    index.SYMOPS = _Ops
    D.SYM = Sym
    D.SYMOPS = _Ops


install()
