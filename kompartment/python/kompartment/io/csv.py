"""CSV as the application writes it, and the two conversions its writers share.

A port of ``src/io/csv.js``, which is one rule -- quote a field that would
otherwise be read as more than one -- and of the two places that apply it: the
header and the rows of ``Results.csvLines`` in ``src/sim/runner.js``, and the
page's own export of the table, which joins its rows the same way.

A row is not quoted cell by cell: the numbers in it are written as
JavaScript's ``String(x)`` writes them (``100000``, ``1e-7``, ``NaN``,
``Infinity``) and joined with commas, and only the header's labels go through
:func:`csv_cell`. Every indexed output's label holds a comma
(``Soil [Cs-137, Lake]``), which is why the header needs it and the numbers do
not.

The two conversions every file writer in this package follows are here too,
since CSV is where they are most visible: :func:`js_string` is
``String(value)`` and :func:`js_to_number` is ``Number(value)``. The HDF5 and
spreadsheet writers use them wherever the application turns a value into text
or into a number, so a file written from Python holds the same bytes.
"""

from __future__ import annotations

import math
import numbers
import re
from typing import Any, Iterable, Iterator, List, Mapping, Sequence

from ..jsonio import js_number

__all__ = ['csv_cell', 'csv_row', 'csv_header', 'csv_lines', 'to_csv', 'js_string', 'js_to_number', 'is_js_boolean',
           'JS_WHITESPACE']

#: What makes a field need quotes: a quote, a comma or a line break (RFC 4180).
_NEEDS_QUOTES = re.compile(r'[",\r\n]')

#: JavaScript's WhiteSpace and LineTerminator, which ``Number()`` and ``trim()``
#: strip. Not Python's ``str.isspace``: that takes ``\x1c``-``\x1f`` and leaves
#: U+FEFF, and JavaScript does the opposite.
JS_WHITESPACE = ('\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006'
                 '\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff')

_DECIMAL = re.compile(r'[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)')
_NON_DECIMAL = re.compile(r'0(?:[xX][0-9a-fA-F]+|[oO][0-7]+|[bB][01]+)')


def _is_numpy_bool(value: Any) -> bool:
    t = type(value)
    return t.__module__ == 'numpy' and t.__name__ in ('bool_', 'bool')


def is_js_boolean(value: Any) -> bool:
    """Whether ``value`` is what JavaScript would call a boolean: ``True``,
    ``False``, or numpy's own."""
    return isinstance(value, bool) or _is_numpy_bool(value)


def _int_to_float(i: int) -> float:
    """An integer as the double JavaScript would hold: rounded, and infinite
    past the largest double rather than an error."""
    try:
        return float(i)
    except OverflowError:
        return math.inf if i > 0 else -math.inf


def _number_text(x: float) -> str:
    if math.isnan(x):
        return 'NaN'
    if math.isinf(x):
        return 'Infinity' if x > 0 else '-Infinity'
    return js_number(x)


def js_string(value: Any) -> str:
    """``String(value)``: a value as JavaScript writes it as text.

    A number is written as JavaScript writes it -- ``100000``, ``0.000015``,
    ``1e-7``, ``1e+21``, ``NaN``, ``Infinity`` -- an integer first becoming the
    double JavaScript would hold. ``None`` is ``null``, a boolean ``true`` or
    ``false``, a list its elements joined with commas (``None`` inside one
    written as nothing, as ``Array.prototype.join`` does), and a dictionary
    ``[object Object]``. numpy scalars and arrays count as the numbers,
    booleans and arrays they are.
    """
    if value is None:
        return 'null'
    if isinstance(value, str):
        return value
    if is_js_boolean(value):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return _number_text(_int_to_float(value))
    if isinstance(value, float):
        return _number_text(float(value))  # numpy's float64 is a float with a repr of its own
    if isinstance(value, (list, tuple, range)):
        return ','.join('' if v is None else js_string(v) for v in value)
    if isinstance(value, Mapping):
        return '[object Object]'
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ','.join(str(b) for b in bytes(value))
    if isinstance(value, numbers.Integral):
        return _number_text(_int_to_float(int(value)))
    if isinstance(value, numbers.Real):
        return _number_text(float(value))
    if hasattr(value, 'tolist'):  # numpy arrays, array.array
        return js_string(value.tolist())
    return str(value)


def _string_to_number(s: str) -> float:
    """``Number(s)`` for a string: JavaScript's grammar, not Python's.

    Python's ``float`` takes ``inf``, ``nan`` and ``1_000``; JavaScript reads
    all three as NaN, and reads ``0x1F`` as 31 where Python refuses it.
    """
    t = s.strip(JS_WHITESPACE)
    if not t:
        return 0.0
    if _NON_DECIMAL.fullmatch(t):
        return _int_to_float(int(t[2:], {'x': 16, 'o': 8, 'b': 2}[t[1].lower()]))
    if _DECIMAL.fullmatch(t):
        if t.endswith('Infinity'):
            return -math.inf if t[0] == '-' else math.inf
        return float(t)
    return math.nan


def js_to_number(value: Any) -> float:
    """``Number(value)``: a value as JavaScript turns it into a number.

    ``None`` (JavaScript's ``null``) is 0, a boolean 1 or 0, a string read by
    JavaScript's own grammar (blank is 0, ``0x10`` is 16, ``1_000`` and ``inf``
    are NaN), a list what its text reads as (``[]`` is 0, ``[5]`` is 5,
    ``[1, 2]`` is NaN) and anything else NaN unless it converts to a float.
    """
    if value is None:
        return 0.0
    if is_js_boolean(value):
        return 1.0 if value else 0.0
    if isinstance(value, int):
        return _int_to_float(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return _string_to_number(value)
    if isinstance(value, (list, tuple, range, bytes, bytearray, memoryview)):
        return _string_to_number(js_string(value))
    if isinstance(value, Mapping):
        return math.nan
    if isinstance(value, numbers.Integral):
        return _int_to_float(int(value))
    if isinstance(value, numbers.Real):
        return float(value)
    if hasattr(value, 'tolist') and hasattr(value, 'ndim') and value.ndim:
        return _string_to_number(js_string(value.tolist()))
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return math.nan


def csv_cell(text: Any) -> str:
    """One CSV field, quoted when it has to be (``csvCell``).

    RFC 4180: a field holding a comma, a quote or a line break is put in
    quotes, and a quote inside it doubled. ``None`` is an empty field; any
    other value is first written as :func:`js_string` writes it.
    """
    s = '' if text is None else js_string(text)
    return '"' + s.replace('"', '""') + '"' if _NEEDS_QUOTES.search(s) else s


def csv_row(values: Iterable[Any]) -> str:
    """One CSV line as the application joins a row: ``row.join(',')``.

    Each value is written as :func:`js_string` writes it and ``None`` as
    nothing; nothing is quoted. This is how the numbers of a table go out --
    the time, then one value per series -- and why the header, whose labels do
    need quoting, is :func:`csv_header` instead.
    """
    return ','.join('' if v is None else js_string(v) for v in values)


def csv_header(labels: Iterable[Any]) -> str:
    """The header line: ``time``, then every label through :func:`csv_cell`."""
    return ','.join(['time'] + [csv_cell(label) for label in labels])


def csv_lines(t: Sequence[Any], labels: Sequence[Any],
              columns: Sequence[Sequence[Any]]) -> Iterator[str]:
    """The lines of a table's CSV, one at a time (``Results.csvLines``).

    ``t`` is the output times, ``labels`` one label per series and
    ``columns`` one sequence of values per series, in the same order. The
    first line is :func:`csv_header`; then one line per time, the time first.
    A column shorter than ``t`` leaves its cell empty, as the application's
    does.
    """
    yield csv_header(labels)
    for i, time in enumerate(t):
        row: List[Any] = [time]
        for col in columns:
            row.append(col[i] if i < len(col) else None)
        yield csv_row(row)


def to_csv(t: Sequence[Any], labels: Sequence[Any], columns: Sequence[Sequence[Any]]) -> str:
    """A table's CSV as one string (``Results.toCSV``): :func:`csv_lines`
    joined with ``\\n``, with no line break after the last."""
    return '\n'.join(csv_lines(t, labels, columns))
