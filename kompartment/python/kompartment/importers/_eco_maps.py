"""What the Ecolego importer takes from the rest of Kompartment, and the rules
of JavaScript it leans on.

Private to :mod:`kompartment.importers.eco`. Two kinds of thing:

* **The small mappers** ``src/io/eco.js`` imports from other modules of the
  application: how Ecolego spells an interpolation rule
  (``src/domain/lookup.js``), a reduction (``src/domain/reduce.js``), an extreme
  and an event direction (``src/domain/recorders.js``); the solvers' names
  (``src/ode/solvers.js``); the length of a year (``src/domain/nuclides.js``);
  and what each kind of block is called (``KIND_LABEL`` in
  ``src/domain/edit.js``). Nothing else in the package needs them, so they are
  here rather than in its public modules.

* **JavaScript itself.** In a few places the importer's output depends on the
  language rather than on anything the importer says: ``Number('')`` is 0,
  ``trim()`` and ``\\s`` know a different set of spaces from Python's, a string's
  length counts UTF-16 code units, an object lists its integer-like keys first,
  ``localeCompare`` sorts by the Unicode collation rather than by code point,
  and a lookup table written as a plain object answers ``constructor`` with a
  function. Each is written out here, so that the same file gives the same
  model -- and the same report -- in both.
"""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from ..jsonio import js_number

# --- JavaScript: strings -------------------------------------------------------------

#: What JavaScript's ``trim()``, ``\s`` and ``Number()`` count as white space:
#: the WhiteSpace and LineTerminator code points. Python's ``str.strip()`` and
#: ``\s`` differ -- they take the separators U+001C..U+001F and U+0085, and
#: leave the byte-order mark U+FEFF.
JS_SPACE = ('\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007'
            '\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff')

#: The same set, written for the inside of a regular expression's ``[...]``.
JS_SPACE_CLASS = '\\t\\n\\x0b\\x0c\\r \\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff'

#: JavaScript's ``.`` in a regular expression: anything but a line terminator.
JS_DOT = '[^\\n\\r\\u2028\\u2029]'


def js_trim(text: str) -> str:
    """``text.trim()``, with JavaScript's idea of white space."""
    return text.strip(JS_SPACE)


def js_len(text: str) -> int:
    """``text.length``: UTF-16 code units, so a character outside the Basic
    Multilingual Plane counts twice."""
    return len(text) + sum(1 for c in text if ord(c) > 0xFFFF)


def utf16_index(text: str, i: int) -> int:
    """Position ``i`` of a Python string as JavaScript would number it."""
    return i + sum(1 for c in text[:i] if ord(c) > 0xFFFF)


def js_identifier(text: str) -> str:
    """``text.replace(/[^A-Za-z0-9_]/g, '_')``.

    The expression has no ``u`` flag, so it works on UTF-16 code units: a
    character outside the Basic Multilingual Plane is two of them and becomes
    two underscores.
    """
    out = []
    for c in text:
        if c.isascii() and (c.isalnum() or c == '_'):
            out.append(c)
        else:
            out.append('__' if ord(c) > 0xFFFF else '_')
    return ''.join(out)


# --- JavaScript: numbers --------------------------------------------------------------

_DECIMAL = re.compile(r'[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)')
_RADIX = re.compile(r'0([xXoObB])([0-9A-Za-z]+)')
_RADIX_BASE = {'x': 16, 'o': 8, 'b': 2}

#: The largest integer a double holds exactly, and so the largest a result can
#: be handed back as a Python ``int`` without its JSON changing.
_SAFE = 2 ** 53


def to_number(value: Any) -> float:
    """JavaScript's ``Number(value)``, for what the importer passes it.

    ``None`` is ``null``, which is 0 -- as is the empty string and one of
    nothing but spaces. A string is a decimal number (``1.``, ``.5`` and
    ``1e5`` included), ``Infinity`` with an optional sign, or an unsigned
    ``0x``/``0o``/``0b`` integer; anything else, Python's ``inf``, ``nan`` and
    ``1_000`` among them, is NaN.
    """
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = js_trim(str(value))
    if s == '':
        return 0.0
    if _DECIMAL.fullmatch(s):
        if s.endswith('Infinity'):
            return -math.inf if s[0] == '-' else math.inf
        return float(s)
    m = _RADIX.fullmatch(s)
    if m:
        try:
            whole = int(m.group(2), _RADIX_BASE[m.group(1).lower()])
        except ValueError:
            return math.nan
        try:
            return float(whole)
        except OverflowError:
            return math.inf
    return math.nan


def is_finite(value: Any) -> bool:
    """``Number.isFinite(value)``: a number, and neither infinite nor NaN."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def whole(x: float) -> Union[int, float]:
    """A whole number as an ``int`` where a double holds it exactly, so that it
    writes the same and reads as a count; anything else as it is."""
    if isinstance(x, float) and x.is_integer() and abs(x) < _SAFE:
        return int(x)
    return x


def js_round(x: float) -> Union[int, float]:
    """``Math.round(x)``: halves go up, towards positive infinity."""
    if not math.isfinite(x):
        return x
    r = math.floor(x)
    if x - r >= 0.5:
        r += 1
    return whole(float(r))


def js_floor(x: float) -> Union[int, float]:
    """``Math.floor(x)``, kept a double as JavaScript keeps it."""
    if not math.isfinite(x):
        return x
    return whole(float(math.floor(x)))


def js_string(x: Any) -> str:
    """``String(x)`` for what the importer writes into its messages."""
    if x is None:
        return 'null'
    if isinstance(x, bool):
        return 'true' if x else 'false'
    if isinstance(x, (int, float)):
        x = float(x)
        if math.isnan(x):
            return 'NaN'
        if math.isinf(x):
            return 'Infinity' if x > 0 else '-Infinity'
        return js_number(x)
    return str(x)


def round_significant(x: float, digits: int) -> float:
    """``Number(x.toPrecision(digits))``.

    ``toPrecision`` rounds the double's exact value, and a tie away from zero,
    where Python's formatting rounds a tie to even: 1000500 to four figures is
    1.001e6 in JavaScript and 1.000e6 in ``'%.3e'``.
    """
    if x == 0 or not math.isfinite(x):
        return x
    d = Decimal(x)
    step = Decimal(1).scaleb(d.adjusted() - digits + 1)
    return float(d.quantize(step, rounding=ROUND_HALF_UP))


def to_exponential(x: float) -> str:
    """``x.toExponential()``: the shortest digits that read back as ``x``,
    written ``1.5e+7``."""
    if not math.isfinite(x):
        return js_string(x)
    if x == 0:
        return '0e+0'
    sign = '-' if x < 0 else ''
    t = Decimal(repr(abs(x))).normalize().as_tuple()
    digits = ''.join(map(str, t.digits))
    e = len(digits) - 1 + int(t.exponent)
    mantissa = digits if len(digits) == 1 else f'{digits[0]}.{digits[1:]}'
    return f"{sign}{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"


# --- JavaScript: dates ----------------------------------------------------------------

_MAX_TIME = 8.64e15


def iso_date(ms: float) -> str:
    """``new Date(ms).toISOString().slice(0, 10)``.

    A year past 9999 is written with a sign and six digits, so the slice is
    ``+010000-01``; a time past what a ``Date`` holds (8.64e15 ms) raises
    ``ValueError('Invalid time value')``, where JavaScript raises a
    ``RangeError`` with that message.
    """
    if not math.isfinite(ms) or abs(ms) > _MAX_TIME:
        raise ValueError('Invalid time value')
    t = int(ms)  # TimeClip truncates towards zero
    days = t // 86400000
    y, m, d = _civil_from_days(days)
    if 0 <= y <= 9999:
        year = f'{y:04d}'
    else:
        year = f"{'+' if y > 0 else '-'}{abs(y):06d}"
    return f'{year}-{m:02d}-{d:02d}'[:10]


def _civil_from_days(z: int) -> Tuple[int, int, int]:
    # Howard Hinnant's days-from-civil, inverted: proleptic Gregorian.
    z += 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return y + (1 if m <= 2 else 0), m, d


# --- JavaScript: objects --------------------------------------------------------------

_ARRAY_INDEX = re.compile(r'0|[1-9][0-9]*')


def js_object_order(d: Dict[str, Any]) -> Dict[str, Any]:
    """``d`` with its keys in the order a JavaScript object lists them.

    An object lists its integer-like keys -- the canonical spellings of 0 to
    2**32 - 2 -- first and in numeric order, then the rest in the order they
    were added. Only matters for an object keyed by text out of the file: a
    nuclide called ``42`` comes first in ``half_lives``.
    """
    ints = [k for k in d if _ARRAY_INDEX.fullmatch(k) and int(k) <= 4294967294]
    if not ints:
        return d
    out = {k: d[k] for k in sorted(ints, key=int)}
    out.update((k, v) for k, v in d.items() if k not in out)
    return out


class Inherited:
    """What a plain JavaScript object answers for a key it does not have but
    inherits from ``Object.prototype``: ``constructor``, ``toString`` and the
    rest are functions, and ``__proto__`` is the prototype itself.

    Two of the tables the importer reads file text through are plain objects
    in the application -- Ecolego's interpolation rules in ``lookup.js`` and
    its event directions in ``recorders.js`` -- so
    ``<lookup-option>constructor</lookup-option>`` finds ``Object`` there:
    truthy, so no warning, and put on the block. JSON leaves a function out and
    writes the prototype as ``{}``, and :func:`json_ready` does the same to
    these.
    """

    __slots__ = ('key', 'is_function')

    def __init__(self, key: str, is_function: bool) -> None:
        self.key = key
        self.is_function = is_function

    def __bool__(self) -> bool:
        return True

    def __copy__(self) -> 'Inherited':
        return self

    def __deepcopy__(self, memo: Any) -> 'Inherited':
        return self

    def __repr__(self) -> str:
        return f'<inherited Object.prototype.{self.key}>'


_PROTOTYPE_MEMBERS: Dict[str, Inherited] = {
    k: Inherited(k, k != '__proto__') for k in (
        'constructor', '__defineGetter__', '__defineSetter__', 'hasOwnProperty',
        '__lookupGetter__', '__lookupSetter__', 'isPrototypeOf', 'propertyIsEnumerable',
        'toString', 'valueOf', '__proto__', 'toLocaleString',
    )
}


def plain_lookup(table: Mapping[str, Any], key: str) -> Any:
    """``table[key]`` where ``table`` is a plain JavaScript object: its own
    value, or what every object inherits, or ``None``."""
    if key in table:
        return table[key]
    return _PROTOTYPE_MEMBERS.get(key)


def json_ready(value: Any) -> Any:
    """``value`` as ``JSON.stringify`` would see it, changed in place: an
    :class:`Inherited` function is left out of an object (``null`` in an
    array), and the inherited prototype becomes ``{}``."""
    if isinstance(value, Inherited):
        return None if value.is_function else {}
    if isinstance(value, dict):
        for k in list(value):
            v = value[k]
            if isinstance(v, Inherited) and v.is_function:
                del value[k]
            else:
                value[k] = json_ready(v)
        return value
    if isinstance(value, list):
        for i, v in enumerate(value):
            value[i] = json_ready(v)
        return value
    return value


# --- JavaScript: localeCompare --------------------------------------------------------

def collation_key(text: str) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
    """A sort key that orders names as ``a.localeCompare(b)`` does in Node.

    The Unicode collation's root order, for what an index list can be called
    (letters, digits and underscore): underscore before digits before letters,
    case ignored until everything else is equal, and then lower case before
    upper. ``L_1 < L1 < L10 < L2``, ``aa < aA < ab``. Any other character sorts
    after those by its code point, which the importer never needs: a list's
    name is an identifier by the time it is sorted.
    """
    primary: List[int] = []
    tertiary: List[int] = []
    for c in text:
        o = ord(c)
        if c == '_':
            primary.append(1)
        elif 48 <= o <= 57:
            primary.append(2 + o - 48)
        elif 97 <= o <= 122:
            primary.append(12 + o - 97)
        elif 65 <= o <= 90:
            primary.append(12 + o - 65)
        else:
            primary.append(100 + o)
        tertiary.append(1 if 65 <= o <= 90 else 0)
    return tuple(primary), tuple(tertiary)


# --- the mappers eco.js imports ---------------------------------------------------------

#: Seconds in a Julian year, which is what Ecolego's half-lives are divided by.
#: ``src/domain/nuclides.js``.
SECONDS_PER_YEAR = 365.25 * 24 * 3600

# How Ecolego spells the interpolation rules. A plain object in lookup.js, and
# so read through `plain_lookup`.
_INTERPOLATION_FROM_ECO = {
    'Interpolation-Use End Values': 'linear',
    'Interpolation-Extrapolation': 'extrapolate',
    'Use Input Below': 'below',
    'Use Input Above': 'above',
    'Use Input Nearest': 'nearest',
}


def interpolation_from_eco(name: Optional[str]) -> Any:
    """A lookup table's interpolation rule from Ecolego's ``<lookup-option>``,
    or ``None``. ``interpolationFromEco`` in ``src/domain/lookup.js``.

    The application's table is a plain object, so a name it inherits
    (``constructor``, ``toString``, ...) comes back as an :class:`Inherited`.
    """
    return plain_lookup(_INTERPOLATION_FROM_ECO, js_trim('' if name is None else str(name)))


# How Ecolego names the reductions, in the current and an older spelling. A
# prototype-free table in reduce.js.
_OPERATION_FROM_ECO = {
    'SUM': 'sum', 'PRODUCT': 'product', 'MIN': 'min', 'MAX': 'max', 'MEAN': 'mean',
    'PERCENTILE': 'percentile',
    'Sum': 'sum', 'Product': 'product', 'Minimum': 'min', 'Maximum': 'max', 'Mean': 'mean',
    'Percentile': 'percentile',
}


def operation_from_eco(name: Optional[str]) -> Optional[str]:
    """An index operation's or aggregate's reduction from Ecolego's
    ``<operation>``, or ``None``. ``operationFromEco`` in
    ``src/domain/reduce.js``."""
    return _OPERATION_FROM_ECO.get(js_trim('' if name is None else str(name)))


#: The recorder kinds, by Ecolego's block type. ``src/domain/recorders.js``.
KIND_FROM_ECO = {
    'min-max': 'min_max',
    'running-mean': 'running_mean',
    'snapshot': 'snapshot',
    'delay': 'delay',
    'discrete-event': 'trigger',
}

#: Which of a recorder's fields name a discrete event.
EVENT_FIELDS = {
    'min_max': ['reset_trigger', 'start_trigger', 'stop_trigger'],
    'running_mean': ['reset_trigger', 'start_trigger', 'stop_trigger'],
    'snapshot': ['trigger'],
    'delay': [],
    'trigger': [],
}

#: Which of a recorder's fields hold an equation.
EQUATION_FIELDS = {
    'min_max': ['target'],
    'running_mean': ['target'],
    'snapshot': ['target', 'initial'],
    'delay': ['target', 'delay'],
    'trigger': ['first', 'second'],
}


def extreme_from_eco(name: Optional[str]) -> Optional[str]:
    """``'min'`` or ``'max'`` from a min/max block's ``<operation>``, or
    ``None``. ``extremeFromEco`` in ``src/domain/recorders.js``."""
    s = js_trim('' if name is None else str(name)).upper()
    return 'min' if s == 'MIN' else 'max' if s == 'MAX' else None


# A plain object in recorders.js, and so read through `plain_lookup`.
_DIRECTION_FROM_ECO = {
    'RIGHT': 'rising',
    'LEFT': 'falling',
    'BOTH': 'both',
    '->': 'rising',
    '<-': 'falling',
    '>-<': 'both',
}


def direction_from_eco(name: Optional[str]) -> Any:
    """A discrete event's direction from Ecolego's ``<direction>``, or ``None``.
    ``directionFromEco`` in ``src/domain/recorders.js``.

    Upper-cased first and then as written; the second lookup is into a plain
    object, so ``constructor`` comes back as an :class:`Inherited`.
    """
    s = js_trim('' if name is None else str(name))
    found = plain_lookup(_DIRECTION_FROM_ECO, s.upper())
    if found is None:
        found = plain_lookup(_DIRECTION_FROM_ECO, s)
    return found


#: Each solver's name in the interface. ``SOLVER_INFO`` in ``src/ode/solvers.js``.
SOLVER_LABELS = {
    'ndf': 'stiff, NDF',
    'ros23': 'stiff, low order, Rosenbrock 2-3',
    'dp45': 'non-stiff, Dormand-Prince 4-5',
    'rodas5p': 'stiff, Rosenbrock 5',
    'radau5': 'stiff, Radau IIA 5',
    'fbdf': 'stiff, fixed-leading-coefficient BDF',
    'qndf': 'stiff, quasi-constant-step NDF',
    'kencarp4': 'stiff, ESDIRK 4',
    'trbdf2': 'stiff, ESDIRK 2 (loose tolerances)',
    'scipy_bdf': 'SciPy BDF, stiff',
    'scipy_radau': 'SciPy Radau IIA, stiff',
    'scipy_lsoda': 'SciPy LSODA, auto-switching',
}


def solver_name(solver_id: Any) -> str:
    """Both of a solver's names, ``stiff, NDF (ndf)``; the id alone for one
    this tool does not have. ``solverName`` in ``src/ode/solvers.js``."""
    label = SOLVER_LABELS.get(solver_id) if isinstance(solver_id, str) else None
    return f'{label} ({solver_id})' if label else js_string(solver_id)


#: What each kind of block is called in the interface, in the plural.
#: ``KIND_LABEL`` in ``src/domain/edit.js``.
KIND_LABEL = {
    'compartment': 'Compartments',
    'transfer': 'Transfers',
    'inflow': 'Inflows',
    'expression': 'Expressions',
    'parameter': 'Parameters',
    'lookup': 'Lookup tables',
    'index_reduction': 'Reduce over an index',
    'block_reduction': 'Combine blocks',
    'function': 'Functions',
    'min_max': 'Min/max',
    'running_mean': 'Running means',
    'snapshot': 'Snapshots',
    'delay': 'Delays',
    'trigger': 'Triggers',
    'farfield': 'Far-field pathways',
    'waste_package': 'Waste packages',
    'event': 'Events',
    'farfield_inventory': 'Path inventories',
    'farfield_cell': 'Path cells',
    'waste_inventory': 'Package inventories',
}
