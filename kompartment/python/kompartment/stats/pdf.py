"""Probability distributions on a parameter, as Kompartment reads, draws and checks them.

A port of the application's ``src/domain/pdf.js``: the eleven kinds a
parameter's distribution can be (``unif``, ``triang``, ``dtriang``, ``norm``,
``logu``, ``logt``, ``logdt``, ``Logn4``, ``logn``, ``logn5`` and the list of
values ``pg``), read from Ecolego's spelling and written back in it, their
forward and inverse CDFs, their densities with truncation, the range worth
drawing them over, a one-line description and the editor's checks.

A distribution is a dictionary, as a model file stores it::

    {'kind': 'logt', 'params': {'min': 7e-12, 'max': 5e-11, 'mode': 1e-11},
     'values': None, 'trmin': None, 'trmax': None, 'pmin': None, 'pmax': None,
     'group': None, 'inorder': True, 'pos': 0}

Every function is the JavaScript one step for step, down to the order of the
operations, so that a value drawn here is the value the application draws. Two
things make that more than a transcription:

- **The arithmetic is V8's.** ``Math.exp`` and ``Math.log`` in the application
  are V8's ports of fdlibm, which differ from the platform's ``libm`` in the
  last bit for about one argument in ten (``exp``). The private ``_exp``,
  ``_log``, ``_log1p`` and ``_expm1`` here are ports of the same fdlibm
  routines, checked bit for bit against Node, and everything in this module
  uses them. The normal CDF and quantile (``phi``, ``probit``,
  ``normal_quantile``) come from :mod:`kompartment.stats._normal` and use
  Python's ``math``; where a result passes through them it agrees with the
  application to the last bit or two rather than exactly.
- **JavaScript's rules where a value is not a plain number.** ``null`` counts
  as 0 in arithmetic and a missing key as NaN, ``Math.max`` of a NaN is NaN, a
  number is written as ``String(x)`` writes it, and so on. So a distribution
  that is only half filled in gives here what it gives in the application,
  rather than raising.

``phi``, ``probit``, ``normal_quantile``, ``erf`` and ``erfc`` are re-exported
from :mod:`kompartment.stats._normal`, as the application's ``pdf.js`` exports
its own.
"""

from __future__ import annotations

import math
import numbers
import re
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..jsonio import js_number
from ._normal import erf, erfc, normal_quantile, phi, probit

__all__ = [
    'PDF_KINDS', 'PDF_KIND_IDS', 'TRUNCATION', 'PERCENTILE_TRUNCATION',
    'parse_pdf', 'complete', 'format_pdf', 'phi', 'cdf_at', 'quantile', 'probability_cuts',
    'density_at', 'cumulative_at', 'probit', 'normal_quantile', 'value_cuts', 'support_of',
    'curve_of', 'describe_pdf', 'pdf_problems', 'erf', 'erfc',
]

Spec = Dict[str, Any]

# ---------------------------------------------------------------------------
# JavaScript's rules, where Python's differ.
# ---------------------------------------------------------------------------


class _Missing:
    """JavaScript's ``undefined``: a key that is not there, as distinct from ``null``."""

    _instance: Optional['_Missing'] = None

    def __new__(cls) -> '_Missing':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return 'undefined'

    def __bool__(self) -> bool:
        return False


_MISSING = _Missing()

#: What ``String.prototype.trim`` and a regular expression's ``\s`` take as
#: white space: JavaScript's WhiteSpace and LineTerminator characters.
_JS_SPACE = ('\t\n\x0b\x0c\r \xa0         '
             '       　﻿')
_JS_SPACE_CLASS = '[' + ''.join(re.escape(c) for c in _JS_SPACE) + ']'

_DECIMAL_LITERAL = re.compile(r'[+-]?(?:Infinity|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)')
_OTHER_LITERAL = re.compile(r'0(?:[xX]([0-9a-fA-F]+)|[oO]([0-7]+)|[bB]([01]+))')

#: The properties every JavaScript object inherits. ``PDF_KINDS[name]`` finds
#: one of these for such a name, which is truthy, and the application then fails
#: on it: see :func:`_meta`.
_OBJECT_PROTOTYPE_KEYS = frozenset({
    'constructor', '__defineGetter__', '__defineSetter__', 'hasOwnProperty', '__lookupGetter__',
    '__lookupSetter__', 'isPrototypeOf', 'propertyIsEnumerable', 'toString', 'valueOf',
    '__proto__', 'toLocaleString',
})


def _is_bool(v: Any) -> bool:
    """A boolean: Python's, or numpy's (``bool_`` before numpy 2, ``bool`` since)."""
    return isinstance(v, bool) or (type(v).__module__ == 'numpy' and type(v).__name__ in ('bool_', 'bool'))


def _is_num(v: Any) -> bool:
    """Whether ``v`` is a JavaScript number: a real number and not a boolean."""
    return isinstance(v, numbers.Real) and not _is_bool(v)


def _is_finite_num(v: Any) -> bool:
    """``Number.isFinite(v)``: a number, and neither NaN nor infinite."""
    if not _is_num(v):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:  # an int too large for a double is Infinity in JavaScript
        return False


def _js_trim(s: str) -> str:
    """``String.prototype.trim``."""
    return s.strip(_JS_SPACE)


def _js_number_str(x: Any) -> str:
    """``String(x)`` for a number, NaN and the infinities included."""
    try:
        v = float(x)
    except OverflowError:
        v = math.inf if x > 0 else -math.inf
    if math.isnan(v):
        return 'NaN'
    if math.isinf(v):
        return 'Infinity' if v > 0 else '-Infinity'
    return js_number(v)


def _js_str(v: Any) -> str:
    """``String(v)`` for anything a model file can hold."""
    if v is _MISSING:
        return 'undefined'
    if v is None:
        return 'null'
    if _is_bool(v):
        return 'true' if v else 'false'
    if isinstance(v, str):
        return v
    if isinstance(v, numbers.Real):
        return _js_number_str(v)
    if isinstance(v, (list, tuple)):
        return ','.join('' if e is None or e is _MISSING else _js_str(e) for e in v)
    if isinstance(v, Mapping):
        return '[object Object]'
    return str(v)


def _string_to_number(s: str) -> float:
    """``Number(s)`` for a string: JavaScript's StringToNumber."""
    t = _js_trim(s)
    if not t:
        return 0.0
    m = _OTHER_LITERAL.fullmatch(t)
    if m:
        for digits, base in zip(m.groups(), (16, 8, 2)):
            if digits is not None:
                try:
                    return float(int(digits, base))
                except OverflowError:
                    return math.inf
    if _DECIMAL_LITERAL.fullmatch(t):
        return float(t)
    return math.nan


def _to_number(v: Any) -> float:
    """``Number(v)``: ``null`` is 0, ``undefined`` NaN, a string read as JavaScript reads one."""
    if v is _MISSING:
        return math.nan
    if v is None:
        return 0.0
    if _is_bool(v):
        return 1.0 if v else 0.0
    if isinstance(v, numbers.Real):
        try:
            return float(v)
        except OverflowError:
            return math.inf if v > 0 else -math.inf
    if isinstance(v, str):
        return _string_to_number(v)
    if isinstance(v, (list, tuple)):
        return _string_to_number(_js_str(v))
    return math.nan


def _truthy(v: Any) -> bool:
    """JavaScript's ToBoolean: an empty dictionary or list is true, 0, NaN and '' are not."""
    if v is None or v is _MISSING:
        return False
    if _is_bool(v):
        return bool(v)
    if isinstance(v, numbers.Real):
        return not (v == 0 or v != v)
    if isinstance(v, str):
        return len(v) > 0
    return True


def _prop(obj: Any, key: str) -> Any:
    """``obj?.[key]``: the value, or ``_MISSING`` for a key (or an object) that is not there."""
    if isinstance(obj, Mapping):
        return obj.get(key, _MISSING)
    return _MISSING


def _nullish(v: Any) -> bool:
    """``v == null``: ``null`` or ``undefined``."""
    return v is None or v is _MISSING


def _param(p: Any, key: str) -> float:
    """A distribution's parameter as JavaScript's arithmetic reads it: ``null`` is 0, missing NaN."""
    return _to_number(_prop(p, key))


def _jmax(a: float, b: float) -> float:
    """``Math.max(a, b)``: NaN if either is, and +0 above -0."""
    if a != a or b != b:
        return math.nan
    if a == b:
        return b if math.copysign(1.0, a) < 0 else a
    return a if a > b else b


def _jmin(a: float, b: float) -> float:
    """``Math.min(a, b)``: NaN if either is, and -0 below +0."""
    if a != a or b != b:
        return math.nan
    if a == b:
        return a if math.copysign(1.0, a) < 0 else b
    return a if a < b else b


def _js_round(x: float) -> float:
    """``Math.round``: to the nearest integer, a half going up (V8's ``Float64Round``)."""
    if x != x or math.isinf(x):
        return x
    c = float(math.ceil(x))
    return c if c - 0.5 <= x else c - 1.0


def _pow(x: float, y: float) -> float:
    """``x ** y`` with JavaScript's special cases (the platform's ``pow`` otherwise)."""
    x = float(x)
    y = float(y)
    if y != y:
        return math.nan
    if y == 0:
        return 1.0
    if x != x:
        return math.nan
    if abs(x) == 1 and math.isinf(y):
        return math.nan
    # fdlibm's own special cases, which V8's pow keeps: x, 1/x, x*x and sqrt(x).
    if y == 1:
        return x
    if y == -1:
        return _div(1.0, x)
    if y == 2:
        return x * x
    if y == 0.5 and math.copysign(1.0, x) > 0:
        return math.sqrt(x)
    odd = y.is_integer() and abs(y) < 2 ** 53 and int(y) % 2 == 1
    try:
        return math.pow(x, y)
    except OverflowError:
        return -math.inf if x < 0 and odd else math.inf
    except ValueError:
        if x == 0:
            return -math.inf if odd and math.copysign(1.0, x) < 0 else math.inf
        return math.nan


def _round_digits(x: float, digits: int) -> Tuple[int, int]:
    """The ``n``, ``e`` of ``toPrecision``: ``digits`` digits of positive, finite ``x``.

    ``10**(digits-1) <= n < 10**digits`` and ``n * 10**(e-digits+1)`` is the
    nearest such number to ``x``, a tie going to the larger, as the
    specification says and V8 does -- from the exact binary value.
    """
    with localcontext() as ctx:
        ctx.prec = 1200
        d = Decimal(x)
        e = d.adjusted()
        _sign, ds, exp = d.as_tuple()
        scaled = Decimal((0, ds, exp + (digits - 1 - e)))
        n = int(scaled.to_integral_value(rounding=ROUND_HALF_UP))
    if n >= 10 ** digits:
        n //= 10
        e += 1
    return n, e


def _to_exponential(x: float, f: int) -> str:
    """``x.toExponential(f)``."""
    x = float(x)
    if x != x:
        return 'NaN'
    s = ''
    if x < 0:
        s = '-'
        x = -x
    if math.isinf(x):
        return s + 'Infinity'
    if x == 0:
        m = '0' * (f + 1)
        e = 0
    else:
        n, e = _round_digits(x, f + 1)
        m = str(n)
    if f != 0:
        m = m[0] + '.' + m[1:]
    if e == 0:
        tail = '+0'
    elif e > 0:
        tail = '+' + str(e)
    else:
        tail = '-' + str(-e)
    return s + m + 'e' + tail


def _to_precision(x: float, p: int) -> str:
    """``x.toPrecision(p)``."""
    x = float(x)
    if x != x:
        return 'NaN'
    s = ''
    if x < 0:
        s = '-'
        x = -x
    if math.isinf(x):
        return s + 'Infinity'
    if x == 0:
        m = '0' * p
        e = 0
    else:
        n, e = _round_digits(x, p)
        m = str(n)
        if e < -6 or e >= p:
            m = m[0] + ('.' + m[1:] if p != 1 else '')
            return s + m + 'e' + ('+' if e >= 0 else '-') + str(abs(e))
    if e == p - 1:
        return s + m
    if e >= 0:
        return s + m[:e + 1] + '.' + m[e + 1:]
    return s + '0.' + '0' * (-(e + 1)) + m


def _four_figures(v: float) -> str:
    """``String(Number(v.toPrecision(4)))``: a number to four significant figures, as JavaScript writes it."""
    return _js_number_str(float(_to_precision(v, 4)))


# ---------------------------------------------------------------------------
# V8's Math.exp, Math.log, Math.log1p and Math.expm1 (fdlibm, as V8 ports it),
# from the package's one copy: ../jsmath.py. Under the names used here.
# ---------------------------------------------------------------------------

from ..jsmath import exp as _exp, expm1 as _expm1, log as _log, log1p as _log1p  # noqa: E402
from ..jsmath import log1p_array as _log1p_array, log_array as _log_array  # noqa: E402
# ---------------------------------------------------------------------------
# The kinds.
# ---------------------------------------------------------------------------

#: What each kind is called where a person reads it, and what it takes --
#: the application's ``PDF_KINDS``, key for key.
PDF_KINDS: Dict[str, Dict[str, Any]] = {
    'unif': {
        'label': 'Uniform',
        'expr': 'unif',
        'blurb': 'Every value between the two ends is as likely as any other.',
        'params': [
            {'key': 'min', 'label': 'Minimum'},
            {'key': 'max', 'label': 'Maximum'},
        ],
    },
    'triang': {
        'label': 'Triangular',
        'expr': 'triang',
        'blurb': ('A straight rise to the most likely value and a straight fall away '
                  'from it — the shape for "about this, no less than that, no more than '
                  'the other".'),
        'params': [
            {'key': 'min', 'label': 'Minimum'},
            {'key': 'max', 'label': 'Maximum'},
            {'key': 'mode', 'label': 'Most likely'},
        ],
    },
    # skbrnt's `dtriang` (samp_util.Dtriang). Ecolego has no such shape, so the
    # spelling is skbrnt's and the numbers are its `a`, `b` and `m`.
    'dtriang': {
        'label': 'Double-triangular',
        'expr': 'dtriang',
        'blurb': ('Two triangles that meet at the most likely value, with half the '
                  'probability on each side — so that value is the median as well as '
                  'the peak, wherever it sits between the ends.'),
        'params': [
            {'key': 'min', 'label': 'Minimum'},
            {'key': 'max', 'label': 'Maximum'},
            {'key': 'mode', 'label': 'Most likely (the median)'},
        ],
    },
    'norm': {
        'label': 'Normal',
        'expr': 'norm',
        'blurb': 'The bell curve, symmetric about its mean.',
        'params': [
            {'key': 'mean', 'label': 'Mean'},
            {'key': 'sd', 'label': 'Std. deviation', 'positive': True},
        ],
    },
    'logu': {
        'label': 'Log-uniform',
        'expr': 'logu',
        'positive': True,
        'log': True,
        'blurb': ('Uniform in the logarithm: every decade between the ends carries the '
                  'same probability. The shape for a quantity known only to within '
                  'orders of magnitude.'),
        'params': [
            {'key': 'min', 'label': 'Minimum', 'positive': True},
            {'key': 'max', 'label': 'Maximum', 'positive': True},
        ],
    },
    'logt': {
        'label': 'Log-triangular',
        'expr': 'logt',
        'positive': True,
        'log': True,
        'blurb': ('A triangle in the logarithm — the commonest shape in these '
                  'assessments, and what a sorption coefficient known to a factor of '
                  'ten usually gets.'),
        'params': [
            {'key': 'min', 'label': 'Minimum', 'positive': True},
            {'key': 'max', 'label': 'Maximum', 'positive': True},
            {'key': 'mode', 'label': 'Most likely', 'positive': True},
        ],
    },
    # skbrnt's `logdt` (samp_util.Logdt): the double triangular in `ln x`.
    'logdt': {
        'label': 'Log-double-triangular',
        'expr': 'logdt',
        'positive': True,
        'log': True,
        'blurb': ('Two triangles in the logarithm that meet at the most likely value, '
                  'with half the probability on each side — so that value is the median '
                  'as well as the peak, wherever it sits between the ends.'),
        'params': [
            {'key': 'min', 'label': 'Minimum', 'positive': True},
            {'key': 'max', 'label': 'Maximum', 'positive': True},
            {'key': 'mode', 'label': 'Most likely (the median)', 'positive': True},
        ],
    },
    'Logn4': {
        'label': 'Log-normal (geometric)',
        'expr': 'logn',
        'positive': True,
        'log': True,
        'blurb': ('A normal curve in the logarithm, given as a geometric mean and a '
                  'geometric standard deviation — a GSD of 3 means "a factor of three '
                  'either way".'),
        'params': [
            {'key': 'gm', 'label': 'Geometric mean', 'positive': True},
            {'key': 'gsd', 'label': 'Geometric SD', 'positive': True},
        ],
    },
    'logn': {
        'label': 'Log-normal (mean, SD)',
        'expr': 'logn',
        'positive': True,
        'log': True,
        'blurb': ('The same curve, given as the ordinary mean and standard deviation '
                  'of the quantity itself rather than of its logarithm.'),
        'params': [
            {'key': 'mean', 'label': 'Mean', 'positive': True},
            {'key': 'sd', 'label': 'Std. deviation', 'positive': True},
        ],
    },
    'logn5': {
        'label': 'Log-normal (two quantiles)',
        'expr': 'logn',
        'positive': True,
        'log': True,
        'blurb': ('A log-normal fitted through two points you know: "5% below x1, 95% '
                  'below x2".'),
        'params': [
            {'key': 'p1', 'label': 'First quantile'},
            {'key': 'x1', 'label': 'is at', 'positive': True},
            {'key': 'p2', 'label': 'Second quantile'},
            {'key': 'x2', 'label': 'is at', 'positive': True},
        ],
    },
    'pg': {
        'label': 'List of values',
        'expr': 'pg',
        'list': True,
        'blurb': ('Not a curve but a list — values sampled somewhere else and written '
                  'into the model, taken one per realisation. The commonest kind here '
                  'by far, and the reason a run can reproduce somebody else’s.'),
        'params': [],
    },
}

#: The order the editor offers them in: the shapes first, the list last.
PDF_KIND_IDS: List[str] = [
    'unif', 'triang', 'dtriang', 'norm', 'logu', 'logt', 'logdt', 'Logn4', 'logn', 'logn5', 'pg',
]

#: Truncation by value, which any kind may carry: cut the curve at ``trmin``
#: and ``trmax``.
TRUNCATION: List[Dict[str, str]] = [
    {'key': 'trmin', 'label': 'Truncate below'},
    {'key': 'trmax', 'label': 'Truncate above'},
]

#: The same two as percentiles of the distribution's own curve (0.05, not 5).
PERCENTILE_TRUNCATION: List[Dict[str, str]] = [
    {'key': 'pmin', 'label': 'Truncate below percentile'},
    {'key': 'pmax', 'label': 'Truncate above percentile'},
]


def _meta(kind: Any) -> Optional[Dict[str, Any]]:
    """The kind's description, or ``None`` for anything that is not a kind's own
    name (``kindInfo``): a name every JavaScript object inherits --
    ``constructor``, ``toString``, ``__proto__`` -- is not a kind, and neither is
    anything but a string."""
    if not isinstance(kind, str):
        return None
    return PDF_KINDS.get(kind)


def _num(v: Any) -> Optional[float]:
    """A number, or ``None`` for nothing, an empty string or something that is not a finite number."""
    if _nullish(v) or v == '':
        return None
    n = _to_number(v)
    return n if math.isfinite(n) else None


def _token(v: Any) -> Optional[str]:
    """A name rather than a number (a correlation group's); ``None`` for nothing."""
    t = _js_trim(_js_str('' if _nullish(v) else v))
    return None if t == '' else t


_EXPRESSION = re.compile(
    r'([A-Za-z_][A-Za-z0-9_]*)' + _JS_SPACE_CLASS + r'*\(([\s\S]*)\)' + _JS_SPACE_CLASS + r'*\Z')


def parse_pdf(expr: Any, function_name: Any = '') -> Optional[Spec]:
    """Reads Ecolego's expression into a distribution; ``None`` if it is not one.

    ``expr`` is the ``<pdf-value>`` text, ``logt(min=1,max=9,mode=3)``;
    ``function_name`` the ``function=`` attribute, which names the kind. It is
    the attribute that tells the three log-normals apart -- they all spell
    themselves ``logn(...)`` -- and without one the argument names do (``gm``,
    ``gsd`` for ``Logn4``; ``p1``, ``x1`` for ``logn5``).

    A distribution declared and not filled in, ``logn(gm,gsd)``, is read with its
    parameters ``None``; :func:`complete` says whether every number is there.
    A list's values are separated by ``;``: ``pg(values=1;2;3,inorder=true,pos=0)``.
    """
    text = _js_trim(_js_str('' if _nullish(expr) else expr))
    if not text:
        return None
    m = _EXPRESSION.match(text)
    if not m:
        return None
    name, body = m.group(1), m.group(2)

    # Commas separate arguments; a list's own values are separated by `;`.
    args: Dict[str, str] = {}
    bare: List[str] = []
    for piece in body.split(','):
        at = piece.find('=')
        if at < 0:
            word = _js_trim(piece)
            if word:
                bare.append(word)
            continue
        args[_js_trim(piece[:at])] = _js_trim(piece[at + 1:])

    # The attribute is the kind; without one, the argument names say which
    # log-normal it is and the expression's name does for the rest.
    kind = function_name if _meta(function_name) else None
    if not kind:
        def has(k: str) -> bool:
            return k in args or k in bare
        if name == 'logn':
            if has('gm') or has('gsd'):
                kind = 'Logn4'
            elif has('p1') or has('x1'):
                kind = 'logn5'
            else:
                kind = 'logn'
        else:
            kind = next((k for k in PDF_KINDS if PDF_KINDS[k]['expr'] == name), None)
    if not kind:
        return None

    pos = _num(args.get('pos', _MISSING))
    spec: Spec = {
        'kind': kind,
        'params': {},
        'values': None,
        'trmin': _num(args.get('trmin', _MISSING)),
        'trmax': _num(args.get('trmax', _MISSING)),
        'pmin': _num(args.get('pmin', _MISSING)),
        'pmax': _num(args.get('pmax', _MISSING)),
        'group': _token(args.get('group', _MISSING)),
        'inorder': args.get('inorder') != 'false',
        'pos': pos if pos is not None else 0,
    }
    meta = _meta(kind)
    assert meta is not None
    for p in meta['params']:
        spec['params'][p['key']] = _num(args.get(p['key'], _MISSING))
    if kind == 'pg':
        raw = args.get('values')
        if raw:
            values = [_string_to_number(v) for v in raw.split(';')]
            spec['values'] = [v for v in values if math.isfinite(v)]
        else:
            spec['values'] = []
    return spec


def complete(spec: Any) -> bool:
    """Whether every number the kind needs is filled in (for a list, whether it has values)."""
    if not _truthy(spec):
        return False
    kind = _prop(spec, 'kind')
    meta = _meta(kind)
    if meta is None:
        return False
    if kind == 'pg':
        values = _prop(spec, 'values')
        try:
            return not isinstance(values, (Mapping, numbers.Number)) and not _nullish(values) \
                and len(values) > 0
        except TypeError:
            return False
    params = _prop(spec, 'params')
    return all(not _nullish(_prop(params, p['key'])) for p in meta['params'])


def _join(values: Any, sep: str) -> str:
    """``array.join(sep)``: ``null`` and ``undefined`` as nothing, numbers as JavaScript writes them."""
    return sep.join('' if _nullish(v) else _js_str(v.item() if hasattr(v, 'item') else v)
                    for v in values)


def format_pdf(spec: Any) -> str:
    """A distribution in Ecolego's spelling, as a model file had it.

    A half-filled one is written as it came: the names alone where there are no
    numbers, ``logn(gm,gsd)``. Truncations, the group, and a list's ``inorder``
    and ``pos`` follow the kind's own numbers.
    """
    if not _truthy(spec):
        return ''
    kind = _prop(spec, 'kind')
    meta = _meta(kind)
    if meta is None:
        return ''
    bits: List[str] = []
    if kind == 'pg':
        values = _prop(spec, 'values')
        bits.append('values=' + _join([] if _nullish(values) else values, ';'))
    else:
        params = _prop(spec, 'params')
        for p in meta['params']:
            v = _prop(params, p['key'])
            # The name alone where there is no number: `logn(gm,gsd)`.
            bits.append(p['key'] if _nullish(v) else f"{p['key']}={_js_str(v)}")
    for key in ('trmin', 'trmax', 'pmin', 'pmax'):
        v = _prop(spec, key)
        if not _nullish(v):
            bits.append(f'{key}={_js_str(v)}')
    group = _prop(spec, 'group')
    if _truthy(group):
        bits.append(f'group={_js_str(group)}')
    if kind == 'pg':
        bits.append('inorder=' + ('false' if _prop(spec, 'inorder') is False else 'true'))
        pos = _prop(spec, 'pos')
        bits.append('pos=' + _js_str(0 if _nullish(pos) else pos))
    return f"{meta['expr']}({','.join(bits)})"


# ---------------------------------------------------------------------------
# The forward and inverse CDF.
# ---------------------------------------------------------------------------


def _params_of(spec: Any) -> Any:
    """``spec.params ?? {}``; like the application, fails on no distribution at all."""
    if _nullish(spec):
        raise TypeError('no distribution: the application cannot read the parameters of null either')
    p = _prop(spec, 'params')
    return {} if _nullish(p) else p


def _logn_log_space(mean: float, sd: float) -> Tuple[float, float]:
    """Logn.muprim / sigmaprim: an arithmetic mean and sd carried into log space."""
    return (_log(_div(mean * mean, math.sqrt(sd * sd + mean * mean))),
            _sqrt(_log(1 + _div(sd * sd, mean * mean))))


def _log_space(spec: Any) -> Optional[Tuple[float, float]]:
    """A log-normal's log-space mean and sd, whichever way it was written."""
    kind = _prop(spec, 'kind')
    p = _prop(spec, 'params')
    p = {} if _nullish(p) else p
    if kind == 'Logn4':
        return _log(_param(p, 'gm')), _log(_param(p, 'gsd'))
    if kind == 'logn':
        return _logn_log_space(_param(p, 'mean'), _param(p, 'sd'))
    if kind == 'logn5':
        z1 = probit(_arg_raw(p, 'p1'))
        z2 = probit(_arg_raw(p, 'p2'))
        if z1 is None or z2 is None or z1 == z2:
            return None
        sigma = _div(_log(_param(p, 'x2')) - _log(_param(p, 'x1')), z2 - z1)
        if not sigma > 0:
            return None
        return _log(_param(p, 'x1')) - sigma * z1, sigma
    return None


def _arg_raw(p: Any, key: str) -> Any:
    """A parameter as handed to ``probit``, which reads it with ``Number``."""
    v = _prop(p, key)
    return math.nan if v is _MISSING else v


def _sqrt(x: float) -> float:
    """``Math.sqrt``: NaN below zero rather than an error."""
    return math.sqrt(x) if x >= 0 else (math.nan if x == x else x)


def _div(a: float, b: float) -> float:
    """``a / b`` with IEEE's answers for a zero ``b`` rather than an error."""
    try:
        return a / b
    except ZeroDivisionError:
        if a != a or a == 0:
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)


def cdf_at(spec: Spec, x: float) -> float:
    """The probability of being at or below ``x``, before truncation.

    Exact where the shape is elementary; through the normal CDF for the three
    log-normals, which are one normal curve in ``ln x``. 0 for a kind it does
    not know.
    """
    p = _params_of(spec)
    kind = _prop(spec, 'kind')
    x = _to_number(x)
    if kind == 'unif':
        a = _param(p, 'min')
        b = _param(p, 'max')
        if x <= a:
            return 0.0
        if x >= b:
            return 1.0
        return _div(x - a, b - a)
    if kind == 'triang':
        a = _param(p, 'min')
        b = _param(p, 'max')
        c = _param(p, 'mode')
        if x <= a:
            return 0.0
        if x >= b:
            return 1.0
        if x <= c:
            return _div((x - a) * (x - a), (b - a) * (c - a))
        return 1 - _div((b - x) * (b - x), (b - a) * (b - c))
    if kind == 'dtriang':
        # skbrnt's Dtriang.cdf: each side a right triangle holding half the
        # probability, so the mode is at exactly 1/2.
        a = _param(p, 'min')
        b = _param(p, 'max')
        c = _param(p, 'mode')
        if x <= a:
            return 0.0
        if x >= b:
            return 1.0
        if x <= c:
            return _div((x - a) * (x - a), 2 * ((c - a) * (c - a)))
        return 1 - _div((b - x) * (b - x), 2 * ((b - c) * (b - c)))
    if kind == 'logu':
        a = _param(p, 'min')
        b = _param(p, 'max')
        if x <= a:
            return 0.0
        if x >= b:
            return 1.0
        return _div(_log(x) - _log(a), _log(b) - _log(a))
    if kind == 'logt':
        # The triangular CDF, in `ln x`.
        la = _log(_param(p, 'min'))
        lb = _log(_param(p, 'max'))
        lc = _log(_param(p, 'mode'))
        if x <= _param(p, 'min'):
            return 0.0
        if x >= _param(p, 'max'):
            return 1.0
        lx = _log(x)
        if lx <= lc:
            return _div((lx - la) * (lx - la), (lc - la) * (lb - la))
        return 1 - _div((lb - lx) * (lb - lx), (lb - la) * (lb - lc))
    if kind == 'logdt':
        # The double triangular's CDF, in `ln x`.
        if x <= _param(p, 'min'):
            return 0.0
        if x >= _param(p, 'max'):
            return 1.0
        la = _log(_param(p, 'min'))
        lb = _log(_param(p, 'max'))
        lc = _log(_param(p, 'mode'))
        lx = _log(x)
        if lx <= lc:
            return _div((lx - la) * (lx - la), 2 * ((lc - la) * (lc - la)))
        return 1 - _div((lb - lx) * (lb - lx), 2 * ((lb - lc) * (lb - lc)))
    if kind == 'norm':
        return phi(_div(x - _param(p, 'mean'), _param(p, 'sd')))
    if kind in ('Logn4', 'logn', 'logn5'):
        if x <= 0:
            return 0.0
        ls = _log_space(spec)
        return phi(_div(_log(x) - ls[0], ls[1])) if ls else 0.0
    return 0.0


def _probit_or_zero(u: float) -> float:
    """``probit(u)`` where JavaScript multiplies by it: its ``null`` outside (0, 1) counts as 0."""
    z = probit(u)
    return 0.0 if z is None else z


def quantile(spec: Spec, u: float) -> float:
    """The value at probability ``u``, before truncation; NaN for a kind it does not know.

    As in the application, the normal kinds read ``probit(u)``, which is
    ``null`` -- 0 in the arithmetic -- outside (0, 1): the quantile of 0 or 1
    of a normal is its mean (of a log-normal, its median), not an infinity.
    """
    p = _params_of(spec)
    kind = _prop(spec, 'kind')
    u = _to_number(u)
    if kind == 'unif':
        a = _param(p, 'min')
        return a + u * (_param(p, 'max') - a)
    if kind == 'triang':
        a = _param(p, 'min')
        b = _param(p, 'max')
        c = _param(p, 'mode')
        split = _div(c - a, b - a)
        if u <= split:
            return a + _sqrt(u * (b - a) * (c - a))
        return b - _sqrt((1 - u) * (b - a) * (b - c))
    if kind == 'dtriang':
        # Dtriang.inv: the split is always the median.
        a = _param(p, 'min')
        b = _param(p, 'max')
        c = _param(p, 'mode')
        if u <= 0.5:
            return a + _sqrt(2 * u) * (c - a)
        return b - (b - c) * _sqrt(2 * (1 - u))
    if kind == 'logu':
        la = _log(_param(p, 'min'))
        return _exp(la + u * (_log(_param(p, 'max')) - la))
    if kind == 'logt':
        la = _log(_param(p, 'min'))
        lb = _log(_param(p, 'max'))
        lc = _log(_param(p, 'mode'))
        split = _div(lc - la, lb - la)
        if u <= split:
            lx = la + _sqrt(u * (lb - la) * (lc - la))
        else:
            lx = lb - _sqrt((1 - u) * (lb - la) * (lb - lc))
        return _exp(lx)
    if kind == 'logdt':
        la = _log(_param(p, 'min'))
        lb = _log(_param(p, 'max'))
        lc = _log(_param(p, 'mode'))
        if u <= 0.5:
            lx = la + _sqrt(2 * u) * (lc - la)
        else:
            lx = lb - (lb - lc) * _sqrt(2 * (1 - u))
        return _exp(lx)
    if kind == 'norm':
        return _param(p, 'mean') + _param(p, 'sd') * _probit_or_zero(u)
    if kind in ('Logn4', 'logn', 'logn5'):
        ls = _log_space(spec)
        return _exp(ls[0] + ls[1] * _probit_or_zero(u)) if ls else math.nan
    return math.nan


_SQRT_2PI_ARG = 2 * math.pi


def _bare_density(spec: Spec, x: float) -> float:
    """The density at one point, before truncation."""
    p = _params_of(spec)
    kind = _prop(spec, 'kind')
    x = _to_number(x)
    if kind == 'unif':
        a = _param(p, 'min')
        b = _param(p, 'max')
        return 1 / (b - a) if (x >= a and x <= b and b > a) else 0.0
    if kind == 'triang':
        # Triang.pdf, which guards the degenerate ends rather than dividing by zero.
        a = _param(p, 'min')
        b = _param(p, 'max')
        c = _param(p, 'mode')
        if x > a and x <= c and a != c and b != a:
            return (2 * (x - a)) / (b - a) / (c - a)
        if x > a and x > c and x <= b and b != a and b != c:
            return (2 * (b - x)) / (b - a) / (b - c)
        return 0.0
    if kind == 'dtriang':
        # Dtriang.pdf: each side holds half the probability however wide it is.
        a = _param(p, 'min')
        b = _param(p, 'max')
        c = _param(p, 'mode')
        if x > a and x <= c and a != c:
            return _div(x - a, (c - a) * (c - a))
        if x > a and x > c and x <= b and b != c:
            return _div(b - x, (b - c) * (b - c))
        return 0.0
    if kind == 'norm':
        mu = _param(p, 'mean')
        sd = _param(p, 'sd')
        if not sd > 0:
            return 0.0
        t = (x - mu) / sd
        return _exp(-0.5 * (t * t)) / (math.sqrt(_SQRT_2PI_ARG) * sd)
    if kind == 'logu':
        a = _param(p, 'min')
        b = _param(p, 'max')
        if not (a > 0 and b > a) or x < a or x > b:
            return 0.0
        return _div(1, x * (_log(b) - _log(a)))
    if kind == 'logt':
        a = _param(p, 'min')
        b = _param(p, 'max')
        c = _param(p, 'mode')
        if not (a > 0 and b > 0 and c > 0) or x <= 0:
            return 0.0
        la = _log(a)
        lb = _log(b)
        lc = _log(c)
        lx = _log(x)
        if x > a and x <= c and a != c:
            return (1 / x) * _div(_div(2 * (lx - la), lc - la), lb - la)
        if x > a and x > c and x <= b and b != c:
            return (1 / x) * _div(_div(2 * (lb - lx), lb - lc), lb - la)
        return 0.0
    if kind == 'logdt':
        # The double triangular's density in `ln x`, over x.
        a = _param(p, 'min')
        b = _param(p, 'max')
        c = _param(p, 'mode')
        if not (a > 0 and b > 0 and c > 0) or x <= 0:
            return 0.0
        la = _log(a)
        lb = _log(b)
        lc = _log(c)
        lx = _log(x)
        if x > a and x <= c and a != c:
            return _div(lx - la, (lc - la) * (lc - la)) / x
        if x > a and x > c and x <= b and b != c:
            return _div(lb - lx, (lb - lc) * (lb - lc)) / x
        return 0.0
    if kind == 'Logn4':
        gm = _param(p, 'gm')
        gsd = _param(p, 'gsd')
        if not (gm > 0 and gsd > 1) or x <= 0:
            return 0.0
        s = _log(gsd)
        t = (_log(x) - _log(gm)) / s
        return _div(_exp(-0.5 * (t * t)), x * math.sqrt(_SQRT_2PI_ARG) * s)
    if kind == 'logn':
        # Logn.muprim / sigmaprim: an arithmetic mean and sd carried into log space.
        mean = _param(p, 'mean')
        sd = _param(p, 'sd')
        if not (mean > 0 and sd > 0) or x <= 0:
            return 0.0
        mu, sigma = _logn_log_space(mean, sd)
        t = _div(_log(x) - mu, sigma)
        return _div(_exp(-0.5 * (t * t)), x * math.sqrt(_SQRT_2PI_ARG) * sigma)
    if kind == 'logn5':
        fit = _quantile_fit(p)
        if not fit:
            return 0.0
        if x <= 0:
            return 0.0
        mu, sigma = fit
        t = (_log(x) - mu) / sigma
        return _div(_exp(-0.5 * (t * t)), x * math.sqrt(_SQRT_2PI_ARG) * sigma)
    return 0.0


def probability_cuts(spec: Spec) -> Dict[str, Any]:
    """The two probabilities a truncated curve is read between, as the sampler reads it.

    ``trmin``/``trmax`` through the CDF, ``pmin``/``pmax`` as they are, the
    tighter on each side. A cut the wrong way round -- Ecolego's
    ``trmin=6.5,trmax=0.0`` -- is no cut at all: ``cut`` is false then, as for a
    curve with no truncation, and ``reversed`` says which of the two it was.

    Returns ``{'lo', 'hi', 'cut', 'reversed'}``.
    """
    lo = 0.0
    hi = 1.0
    trmin = _prop(spec, 'trmin')
    trmax = _prop(spec, 'trmax')
    pmin = _prop(spec, 'pmin')
    pmax = _prop(spec, 'pmax')
    if not _nullish(trmin):
        lo = _jmax(lo, cdf_at(spec, trmin))
    if not _nullish(trmax):
        hi = _jmin(hi, cdf_at(spec, trmax))
    if not _nullish(pmin):
        lo = _jmax(lo, _to_number(pmin))
    if not _nullish(pmax):
        hi = _jmin(hi, _to_number(pmax))
    if not hi > lo:
        return {'lo': 0.0, 'hi': 1.0, 'cut': False, 'reversed': True}
    return {'lo': lo, 'hi': hi, 'cut': lo > 0 or hi < 1, 'reversed': False}


def _drawable(spec: Any) -> bool:
    """A known kind, not a list, and filled in: what has a density."""
    return _truthy(spec) and _meta(_prop(spec, 'kind')) is not None and _prop(spec, 'kind') != 'pg' \
        and complete(spec)


def density_at(spec: Spec, x: float) -> float:
    """The density at ``x`` of the distribution the sampler draws from.

    The curve, cut where its truncation cuts it and raised by the probability
    left so the area is one again. NaN for a list (``pg``), which has no
    density, and for a distribution that is not filled in.
    """
    if not _drawable(spec):
        return math.nan
    f = _bare_density(spec, x)
    cuts = probability_cuts(spec)
    if not cuts['cut'] or f == 0:
        return f
    big_f = cdf_at(spec, x)
    lo, hi = cuts['lo'], cuts['hi']
    return 0.0 if (big_f < lo or big_f > hi) else f / (hi - lo)


def cumulative_at(spec: Spec, x: float) -> float:
    """The probability of at most ``x``, truncation and all; NaN as :func:`density_at`."""
    if not _drawable(spec):
        return math.nan
    cuts = probability_cuts(spec)
    big_f = cdf_at(spec, x)
    if not cuts['cut']:
        return big_f
    return _jmin(1.0, _jmax(0.0, (big_f - cuts['lo']) / (cuts['hi'] - cuts['lo'])))


def _quantile_fit(p: Any) -> Optional[Tuple[float, float]]:
    """Two quantiles to a log-normal: ``(mu, sigma)`` through both points, or ``None``."""
    x1 = _param(p, 'x1')
    x2 = _param(p, 'x2')
    if not (x1 > 0 and x2 > 0):
        return None
    z1 = probit(_arg_raw(p, 'p1'))
    z2 = probit(_arg_raw(p, 'p2'))
    if z1 is None or z2 is None or z1 == z2:
        return None
    sigma = (_log(x2) - _log(x1)) / (z2 - z1)
    if not sigma > 0:
        return None
    return _log(x1) - sigma * z1, sigma


def value_cuts(spec: Any, lo: float = -math.inf, hi: float = math.inf) -> Dict[str, Any]:
    """Both truncations as the values they cut at: ``{'lo', 'hi'}``, ``None`` for no cut.

    ``trmin``/``trmax`` are values already. A percentile becomes one through
    :func:`quantile`, which only a filled-in distribution can answer, so an
    incomplete one reports no cut rather than NaN. ``lo``/``hi`` are the
    untruncated support, which a percentile of 0 or 1 falls back to rather
    than reaching for an infinite tail.
    """
    trmin = _prop(spec, 'trmin')
    trmax = _prop(spec, 'trmax')
    out: Dict[str, Any] = {'lo': None if _nullish(trmin) else trmin,
                           'hi': None if _nullish(trmax) else trmax}
    can = _truthy(spec) and _meta(_prop(spec, 'kind')) is not None and _prop(spec, 'kind') != 'pg' \
        and complete(spec)

    def at(p: Any, fallback: float) -> Any:
        if not can or not (_is_num(p) and p > 0) or not (_is_num(p) and p < 1):
            if _is_num(p) and (p == 0 or p == 1):
                return fallback
            return None
        v = quantile(spec, p)
        return v if _is_finite_num(v) else None

    pl = at(_prop(spec, 'pmin'), lo)
    ph = at(_prop(spec, 'pmax'), hi)
    if pl is not None and _is_finite_num(pl):
        out['lo'] = pl if out['lo'] is None else _jmax(_to_number(out['lo']), pl)
    if ph is not None and _is_finite_num(ph):
        out['hi'] = ph if out['hi'] is None else _jmin(_to_number(out['hi']), ph)
    return out


def support_of(spec: Any) -> Optional[List[float]]:
    """``[lo, hi]``: where the curve is worth drawing, truncation applied; ``None`` if nowhere.

    The ends for the bounded kinds, four standard deviations either side (in
    ``ln x`` for the log-normals) for the rest, the smallest and largest value
    of a list.
    """
    if not complete(spec):
        return None
    p = _prop(spec, 'params')
    p = {} if _nullish(p) else p
    kind = _prop(spec, 'kind')
    if kind in ('unif', 'triang', 'dtriang', 'logu', 'logt', 'logdt'):
        lo = _param(p, 'min')
        hi = _param(p, 'max')
    elif kind == 'norm':
        mean = _param(p, 'mean')
        sd = _param(p, 'sd')
        lo = mean - 4 * sd
        hi = mean + 4 * sd
    elif kind == 'Logn4':
        s = _log(_param(p, 'gsd'))
        gm = _param(p, 'gm')
        lo = gm * _exp(-4 * s)
        hi = gm * _exp(4 * s)
    elif kind == 'logn':
        mu, sigma = _logn_log_space(_param(p, 'mean'), _param(p, 'sd'))
        lo = _exp(mu - 4 * sigma)
        hi = _exp(mu + 4 * sigma)
    elif kind == 'logn5':
        fit = _quantile_fit(p)
        if not fit:
            return None
        lo = _exp(fit[0] - 4 * fit[1])
        hi = _exp(fit[0] + 4 * fit[1])
    elif kind == 'pg':
        v = [_to_number(x.item() if hasattr(x, 'item') else x) for x in _prop(spec, 'values')]
        if not v:
            return None
        lo = math.nan if any(x != x for x in v) else min(v)
        hi = math.nan if any(x != x for x in v) else max(v)
        if lo == hi:
            lo -= abs(lo) * 0.1 + 1
            hi += abs(hi) * 0.1 + 1
    else:
        return None
    # Truncation cuts the drawing as well as the density; a percentile cut is
    # resolved to the value it falls at and applied beside the other.
    cut = value_cuts(spec, lo, hi)
    if cut['lo'] is not None and _to_number(cut['lo']) > lo:
        lo = _to_number(cut['lo'])
    if cut['hi'] is not None and _to_number(cut['hi']) < hi:
        hi = _to_number(cut['hi'])
    if not (math.isfinite(lo) and math.isfinite(hi) and hi > lo):
        return None
    return [lo, hi]


def curve_of(spec: Any, points: int = 240, bins: int = 32) -> Optional[Dict[str, Any]]:
    """The curve to draw: ``points`` samples of the density across its support.

    Truncation is applied by cutting and rescaling so the area -- the trapezoid
    sum over these very points -- is one again. A log-scaled kind is sampled
    geometrically. A list (``pg``) comes back as ``bins`` bars, as a density.

    Returns ``{'xs', 'ys', 'log', 'bars', 'area'}`` (lists of floats), or ``None``.
    """
    span = support_of(spec)
    if not span:
        return None
    lo, hi = span
    kind = _prop(spec, 'kind')
    meta = _meta(kind)
    assert meta is not None

    if kind == 'pg':
        if bins < 0:
            raise ValueError('Invalid array length: a histogram cannot have fewer than no bins')
        v = [_to_number(x.item() if hasattr(x, 'item') else x) for x in _prop(spec, 'values')]
        width = _div(hi - lo, bins)
        xs = [lo + width * (i + 0.5) for i in range(bins)]
        ys = [0] * bins
        for x in v:
            k = math.floor(_div(x - lo, width))
            if k < 0:
                k = 0
            if k >= bins:
                k = bins - 1
            if 0 <= k < bins:  # with no bins the application counts into no bar either
                ys[k] += 1
        # As a density, so the y axis means the same thing as the curves'.
        scale = len(v) * width
        return {'xs': xs, 'ys': [(n / scale if scale > 0 else 0) for n in ys], 'log': False,
                'bars': True, 'area': 1}

    use_log = bool(meta.get('log')) and lo > 0 and hi > 0
    xs: List[float] = []
    for i in range(points):
        f = _div(i, points - 1)
        xs.append(_exp(_log(lo) + f * (_log(hi) - _log(lo))) if use_log else lo + f * (hi - lo))
    ys = [_bare_density(spec, x) for x in xs]

    # Trapezoid over the drawn points, which is the area the picture shows.
    area = 0.0
    for i in range(1, len(xs)):
        area += ((ys[i] + ys[i - 1]) / 2) * (xs[i] - xs[i - 1])
    truncated = any(not _nullish(_prop(spec, k)) for k in ('trmin', 'trmax', 'pmin', 'pmax'))
    if truncated and area > 0:
        ys = [y / area for y in ys]
    return {'xs': xs, 'ys': ys, 'log': use_log, 'bars': False, 'area': 1 if truncated else area}


def describe_pdf(spec: Any) -> str:
    """One line saying what a distribution is: ``Log-triangular: min 0.7, max 20, mode 3``."""
    if not _truthy(spec):
        return ''
    meta = _meta(_prop(spec, 'kind'))
    if meta is None:
        return ''
    if not complete(spec):
        return f"{meta['label']} — not filled in"

    def fmt(v: Any) -> str:
        x = _to_number(v)
        if abs(x) >= 1e4 or (x != 0 and abs(x) < 1e-3):
            return _to_exponential(x, 2)
        return _js_str(v)

    kind = _prop(spec, 'kind')
    if kind == 'pg':
        n = len(_prop(spec, 'values'))
        body = f"{n} value{'' if n == 1 else 's'}"
    else:
        params = _prop(spec, 'params')
        body = ', '.join(f"{p['key']} {fmt(params[p['key']])}" for p in meta['params'])
    group = _prop(spec, 'group')
    tail = f', group {_js_str(group)}' if _truthy(group) else ''
    cut: List[str] = []
    if not _nullish(_prop(spec, 'trmin')):
        cut.append(f"≥ {fmt(spec['trmin'])}")
    if not _nullish(_prop(spec, 'trmax')):
        cut.append(f"≤ {fmt(spec['trmax'])}")
    # A percentile cut is written as the percentile, not the value it lands on.

    def pc(v: Any) -> str:
        return 'p' + _four_figures(_to_number(v) * 100)

    if not _nullish(_prop(spec, 'pmin')):
        cut.append(f"≥ {pc(spec['pmin'])}")
    if not _nullish(_prop(spec, 'pmax')):
        cut.append(f"≤ {pc(spec['pmax'])}")
    truncated = f", truncated {' and '.join(cut)}" if cut else ''
    return f"{meta['label']}: {body}{truncated}{tail}"


def _n(v: Any) -> float:
    """A value compared as JavaScript compares it with a number."""
    return _to_number(v)


def pdf_problems(spec: Any) -> List[str]:
    """What is wrong with a distribution, in the editor's words; empty when nothing is.

    Never raises for a distribution being edited: one passes through every
    half-finished state on the way to a finished one, and a half-filled one
    is not a problem.
    """
    out: List[str] = []
    if not _truthy(spec):
        return out
    kind = _prop(spec, 'kind')
    meta = _meta(kind)
    if meta is None:
        return out
    p = _prop(spec, 'params')
    p = {} if _nullish(p) else p

    def get(key: str) -> Any:
        return _prop(p, key)

    for d in meta['params']:
        v = get(d['key'])
        if _nullish(v):
            continue
        if d.get('positive') and not _n(v) > 0:
            out.append(f"{d['label']} has to be more than zero.")
    # A percentile is a probability, and one at either end asks for the tail itself.
    for key in ('pmin', 'pmax'):
        v = _prop(spec, key)
        if _nullish(v):
            continue
        if not (_n(v) >= 0 and _n(v) <= 1):
            out.append('A percentile truncation is a probability, so it has to be between '
                       '0 and 1 — 0.05 for the 5th percentile, not 5.')
            break
    pmin = _prop(spec, 'pmin')
    pmax = _prop(spec, 'pmax')
    trmin = _prop(spec, 'trmin')
    trmax = _prop(spec, 'trmax')
    if not _nullish(pmin) and not _nullish(pmax) and not _n(pmax) > _n(pmin):
        out.append('The percentile truncation is inside out — nothing is left between them.')
    # Both forms at once is allowed and means the intersection, but a pair that
    # leaves nothing is worth saying out loud.
    cut = value_cuts(spec)
    if cut['lo'] is not None and cut['hi'] is not None and not _n(cut['hi']) > _n(cut['lo']):
        both = (not _nullish(trmin) or not _nullish(trmax)) and (not _nullish(pmin) or not _nullish(pmax))
        if both:
            out.append('The value truncation and the percentile truncation do not overlap — '
                       'between them nothing is left to draw from.')
    if meta.get('positive'):
        for key in ('trmin', 'trmax'):
            v = _prop(spec, key)
            if not _nullish(v) and _n(v) < 0:
                out.append('This distribution is only defined above zero, so it cannot be '
                           'truncated below it.')
                break

    def pair(a: str, b: str, what: str) -> None:
        if not _nullish(get(a)) and not _nullish(get(b)) and not _n(get(b)) > _n(get(a)):
            out.append(f'{what} — the maximum has to be above the minimum.')

    if kind in ('unif', 'triang', 'dtriang', 'logu', 'logt', 'logdt'):
        pair('min', 'max', 'The range is empty')
    mode, lo, hi = get('mode'), get('min'), get('max')
    if kind in ('triang', 'dtriang', 'logt', 'logdt') and not _nullish(mode):
        if not _nullish(lo) and _n(mode) < _n(lo):
            out.append('The most likely value is below the minimum.')
        if not _nullish(hi) and _n(mode) > _n(hi):
            out.append('The most likely value is above the maximum.')
    # Each side of a double triangular holds half the probability however narrow it is.
    if kind in ('dtriang', 'logdt') and not _nullish(mode) and not _nullish(lo) and not _nullish(hi) \
            and _n(hi) > _n(lo) and (_n(mode) == _n(lo) or _n(mode) == _n(hi)):
        where = 'minimum' if _n(mode) == _n(lo) else 'maximum'
        out.append(f'With the most likely value at the {where}, '
                   'half of every sample is that one number: each side of this shape holds half '
                   'the probability, however narrow it is.')
    gsd = get('gsd')
    if kind == 'Logn4' and not _nullish(gsd) and _n(gsd) <= 1 and _n(gsd) > 0:
        out.append('A geometric standard deviation of 1 or less is a single value, not a '
                   'spread — it has to be more than 1.')
    if kind == 'logn5':
        for key in ('p1', 'p2'):
            v = get(key)
            if not _nullish(v) and not (_n(v) > 0 and _n(v) < 1):
                out.append('A quantile is a probability, so it has to be between 0 and 1.')
                break
        if not _nullish(get('p1')) and not _nullish(get('p2')) and _n(get('p1')) == _n(get('p2')):
            out.append('The two quantiles have to be different.')
    if not _nullish(trmin) and not _nullish(trmax) and not _n(trmax) > _n(trmin):
        # Ecolego writes `unif(min=0.0,max=6.5,trmin=6.5,trmax=0.0)` -- the two the
        # wrong way round, which is how it spells "no truncation".
        out.append('The truncation is inside out — nothing is left. Ecolego writes this '
                   'when a truncation has been cleared; clear both fields to say the same '
                   'thing.')
    span = support_of(spec)
    if complete(spec) and not span:
        out.append('These numbers do not describe a distribution that can be drawn.')
    return out
