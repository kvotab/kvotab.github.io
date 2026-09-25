"""A data table as a spreadsheet and as an HDF5 tree, both ways.

A port of the application's ``src/io/datafile.js``: how the rows of
:mod:`kompartment.datatable` -- a parameter's value, a lookup table's points,
the distribution either carries -- are spelled in the two formats an
assessment's data travels in, so a file written here is the file the
application writes and one written by hand reads alike::

    from kompartment import datatable
    from kompartment.io import datafile

    rows = datatable.collect(model.raw)
    data = datafile.write_data_workbook(rows, name='biosphere')
    back = datafile.read_data_workbook(data)      # {'rows': [...], 'problems': [...]}

**The spreadsheet** is one row per value: ``ID`` (the dotted path), ``Unit``,
the helper columns ``Subsystem``, ``Name``, ``Media``, ``Position``,
``Species`` (read only when ``ID`` is empty), ``Time`` (a lookup table's
point), ``Value``, ``Type`` (which curve: norm, unif, logn, logu, triang,
dtriang, logt, logdt), ``Group``, ``Min``, ``Max``, ``Mean``, ``Std``, ``GM``,
``GSD``, ``Pmin``, ``Pmax``, ``PDF`` and ``Reference``. A distribution the
columns cannot hold -- a log-normal by its mean or through two quantiles, a
list of values, or a truncation of a curve whose Min and Max are its ends --
goes in ``PDF`` whole, written as a model file writes one
(``logn(mean=2,sd=0.5)``), and a row with no ``Type`` is read from it. A blank
cell is no value.

**The HDF5 tree**: the path is the id under one root group named after the
model; a parameter is a dataset of one value, a lookup table a dataset of its
values with ``lookup_table`` and the times in ``index``, and ``pdf`` a JSON
object in the words the files already use (a list of them, one per point, for
a table), or the same expression the PDF column holds where the shape has no
word. A matrix or column of realisations (``probabilistic``, or a ``pdf``
of ``{"type": "raw"}``) reads as a list of values handed out in order. What a
file gets wrong -- a table whose times do not pair with its values, text marked
as a sample, a word that is no distribution -- is a problem line, and the rest
of the file is read.

A path segment ``_`` means the block's own value, not an index of that name.
"""

from __future__ import annotations

import json
import math
import numbers
import re
from array import array
from functools import cmp_to_key
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

from ..jsonio import dumps
from ..stats.pdf import PDF_KINDS, complete, format_pdf, parse_pdf
from .csv import JS_WHITESPACE, is_js_boolean, js_string, js_to_number
from .hdf5 import F64, STR, Group, dataset, group, put, write_hdf5
from .hdf5read import read_hdf5
from .xlsx import read_workbook, write_workbook

__all__ = ['DEFAULT_SEGMENT', 'SHAPES', 'COLUMNS', 'sample_spec', 'pdf_from_columns', 'columns_from_pdf',
           'pdf_to_json', 'pdf_attribute', 'pdf_list_from_json', 'pdf_from_json', 'to_sheet', 'from_sheet',
           'write_data_workbook', 'read_data_workbook', 'to_tree', 'write_data_hdf5', 'read_data_hdf5', 'usable']

#: The segment that means "the block's own value, at no index".
DEFAULT_SEGMENT = '_'

#: A dataset that is the numbers themselves rather than a curve.
RAW = 'raw'

#: Where a file keeps the times a matrix is against.
TIME_PATHS = ('/time', '/Time', '/times')

#: Which columns hold which curve's numbers: ``params`` maps the spec's own
#: parameter keys to columns, and ``cut`` says whether Min and Max are a
#: truncation of the curve (a normal) rather than its ends (a uniform).
SHAPES: Dict[str, Dict[str, Any]] = {
    'norm': {'kind': 'norm', 'params': {'mean': 'Mean', 'sd': 'Std'}, 'cut': True},
    'unif': {'kind': 'unif', 'params': {'min': 'Min', 'max': 'Max'}, 'cut': False},
    'logn': {'kind': 'Logn4', 'params': {'gm': 'GM', 'gsd': 'GSD'}, 'cut': True},
    'logu': {'kind': 'logu', 'params': {'min': 'Min', 'max': 'Max'}, 'cut': False},
    'triang': {'kind': 'triang', 'params': {'min': 'Min', 'max': 'Max', 'mode': 'Mean'}, 'cut': False},
    'logt': {'kind': 'logt', 'params': {'min': 'Min', 'max': 'Max', 'mode': 'Mean'}, 'cut': False},
    'dtriang': {'kind': 'dtriang', 'params': {'min': 'Min', 'max': 'Max', 'mode': 'Mean'}, 'cut': False},
    'logdt': {'kind': 'logdt', 'params': {'min': 'Min', 'max': 'Max', 'mode': 'Mean'}, 'cut': False},
}

#: A spec's kind to the word a file uses for it.
WORD = {s['kind']: word for word, s in SHAPES.items()}

COLUMNS = [
    'ID', 'Unit', 'Subsystem', 'Name', 'Media', 'Position', 'Species',
    'Time', 'Value', 'Type', 'Group',
    'Min', 'Max', 'Mean', 'Std', 'GM', 'GSD', 'Pmin', 'Pmax', 'PDF',
    'Reference',
]

#: The helper columns, in the order a hand-made ID pastes them together.
HELPERS = ['Subsystem', 'Name', 'Media', 'Position', 'Species']

#: The HDF5 form's names for a spec's parameters.
_HDF_NAME = {'min': 'a', 'max': 'b', 'sd': 'std', 'mode': 'm'}

_SPLIT = re.compile('[,' + ''.join(re.escape(c) for c in JS_WHITESPACE) + ']+')


# --- JavaScript's rules, where Python's differ ----------------------------------------------

class _Undefined:
    def __repr__(self) -> str:
        return 'undefined'

    def __bool__(self) -> bool:
        return False


_UNDEF = _Undefined()


def _nullish(v: Any) -> bool:
    return v is None or v is _UNDEF


def _get(obj: Any, key: str) -> Any:
    """``obj[key]`` for a dictionary; ``undefined`` for a key it has not, or anything else."""
    if isinstance(obj, Mapping):
        return obj.get(key, _UNDEF)
    return _UNDEF


def _truthy(v: Any) -> bool:
    if _nullish(v):
        return False
    if is_js_boolean(v):
        return bool(v)
    if isinstance(v, numbers.Real):
        return not (v == 0 or v != v)
    if isinstance(v, str):
        return v != ''
    return True


def _text(v: Any) -> str:
    """``String(v)``, ``undefined`` included."""
    return 'undefined' if v is _UNDEF else js_string(v)


def _is_number(v: Any) -> bool:
    """``typeof v === 'number'``."""
    return isinstance(v, numbers.Real) and not is_js_boolean(v)


def _finite(x: Any) -> bool:
    try:
        return math.isfinite(x)
    except (OverflowError, TypeError):
        return False


def _num(v: Any) -> Optional[Union[int, float]]:
    """A number where there is one, ``None`` otherwise. Blank is no value: a
    cell of spaces is ``None``, not the 0 that ``Number('')`` is."""
    if _nullish(v) or (isinstance(v, str) and v == ''):
        return None
    if _is_number(v):
        n = v.item() if hasattr(v, 'item') else v
    else:
        text = js_string(v).strip(JS_WHITESPACE)
        if text == '':
            return None
        n = js_to_number(text)
    return n if _finite(n) else None


def _str(v: Any) -> str:
    return '' if _nullish(v) else js_string(v).strip(JS_WHITESPACE)


def _value(v: Any) -> Any:
    """A value cell: a number where it is one, the text otherwise (a class name, say)."""
    n = _num(v)
    if n is not None:
        return n
    t = _str(v)
    return None if t == '' else t


def _no_constant(name: str) -> Any:
    raise ValueError(f'Unexpected token {name[0]} in JSON')


def _json_parse(text: str) -> Any:
    """``JSON.parse``: NaN and Infinity are not JSON."""
    return json.loads(text, parse_constant=_no_constant)


def _plain(v: Any) -> Any:
    if v is None or isinstance(v, (str, bool)):
        return v
    if is_js_boolean(v):
        return bool(v)
    if isinstance(v, numbers.Integral):
        return int(v)
    if isinstance(v, numbers.Real):
        return float(v)
    if isinstance(v, Mapping):
        return {k if isinstance(k, str) else js_string(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if hasattr(v, 'tolist'):
        return {str(i): _plain(x) for i, x in enumerate(v.tolist())}
    return {}


def _stringify(v: Any) -> str:
    """``JSON.stringify(v)``."""
    return dumps(_plain(v), 0)


def _shape(word: str) -> Optional[Dict[str, Any]]:
    """The shape a word names, or ``None`` -- a word every JavaScript object
    answers to (``constructor``) included, which the application now asks of
    its own words only."""
    return SHAPES.get(word)


def _fits_columns(spec: Any) -> bool:
    """Whether the columns hold all of a spec: a kind with a word, and no
    truncation on a curve whose Min and Max are its own ends."""
    kind = _get(spec, 'kind')
    word = WORD.get(kind) if _hashable(kind) else None
    if not word:
        return False
    return SHAPES[word]['cut'] or (_nullish(_get(spec, 'trmin')) and _nullish(_get(spec, 'trmax')))


def _expression_of(spec: Any) -> str:
    """Ecolego's expression for a spec of a kind there is, '' for anything else."""
    kind = _get(spec, 'kind')
    return format_pdf(spec) if isinstance(kind, str) and kind in PDF_KINDS else ''


def _is_view(v: Any) -> bool:
    """``ArrayBuffer.isView(v)``: a typed array, which here is an ``array.array``,
    a numpy array or a memoryview."""
    return isinstance(v, (array, memoryview)) or type(v).__name__ == 'ndarray'


def _length(v: Any) -> int:
    if type(v).__name__ == 'ndarray':
        return int(v.size)
    return len(v)


def _cmp(x: float) -> int:
    """A comparator's answer: NaN is 0, as ``Array.prototype.sort`` takes it."""
    if x != x:
        return 0
    return -1 if x < 0 else (1 if x > 0 else 0)


# --- a distribution, either way -------------------------------------------------------------

def _middle(values: Any) -> Optional[float]:
    """The middle of a sample, for a deterministic value where the file gives none."""
    finite = sorted(float(v) for v in values if _is_number(v) and _finite(v))
    if not finite:
        return None
    half = len(finite) >> 1
    return finite[half] if len(finite) % 2 else (finite[half - 1] + finite[half]) / 2


def sample_spec(values: Any, group: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """A list of values as a spec -- a ``pg``, handed out in order, one per
    realisation (``sampleSpec``) -- or ``None`` where there is nothing to hand out."""
    if values is None or not _length(values):
        return None
    return {
        'kind': 'pg',
        'params': {},
        'values': values,
        'trmin': None, 'trmax': None, 'pmin': None, 'pmax': None,
        'group': group,
        'inorder': True,
        'pos': 0,
    }


def _raw_of(attr: Any) -> Optional[Dict[str, bool]]:
    """Whether an attribute says "these are the numbers", and how to read them."""
    if _nullish(attr):
        return None
    obj = attr
    if isinstance(attr, str):
        t = attr.strip(JS_WHITESPACE)
        if not t.startswith('{'):
            return None
        try:
            obj = _json_parse(t)
        except ValueError:
            return None
    kind = _get(obj, 'type')
    if js_string('' if _nullish(kind) else kind).lower() != RAW:
        return None
    return {'deterministic': _get(obj, 'include_deterministic') is True}


def _flagged(v: Any) -> bool:
    """``True``/``true``/1, however the file wrote it."""
    return not _nullish(v) and re.fullmatch(r'(false|0|)', js_string(v), re.I) is None


def pdf_from_columns(at: Callable[[str], Any]) -> Optional[Dict[str, Any]]:
    """A spec from a row of columns (``pdfFromColumns``): ``at(column)`` reads one
    cell. ``None`` where the row names no curve, ``{'bad': why}`` where it names
    one this does not read."""
    word = _str(at('Type')).lower()
    if not word:
        return _pdf_from_expression(at)
    shape = _shape(word)
    if shape is None:
        return {'bad': f"'{_text(at('Type'))}' is not a distribution this reads"}
    group_name = _str(at('Group'))
    spec: Dict[str, Any] = {
        'kind': shape['kind'],
        'params': {},
        'values': None,
        'trmin': None, 'trmax': None,
        'pmin': _num(at('Pmin')), 'pmax': _num(at('Pmax')),
        'group': group_name or None,
        'inorder': True, 'pos': 0,
    }
    for key, column in shape['params'].items():
        spec['params'][key] = _num(at(column))
    # A triangular's most likely value is `Value` where `Mean` is empty.
    if 'mode' in shape['params'] and spec['params']['mode'] is None:
        spec['params']['mode'] = _num(at('Value'))
    # Min and Max are a truncation of a curve that has no ends of its own.
    if shape['cut']:
        spec['trmin'] = _num(at('Min'))
        spec['trmax'] = _num(at('Max'))
    return spec


def _pdf_from_expression(at: Callable[[str], Any]) -> Optional[Dict[str, Any]]:
    """A spec from the PDF column, for a row with no ``Type``, with the row's
    group, percentile cuts and a triangular's mode in ``Value`` where the
    expression does not give them."""
    text = _str(at('PDF'))
    if not text:
        return None
    spec = parse_pdf(text)
    if spec is None:
        return {'bad': f"'{text}' is not a distribution this reads"}
    if spec.get('group') is None:
        spec['group'] = _str(at('Group')) or None
    if spec.get('pmin') is None:
        spec['pmin'] = _num(at('Pmin'))
    if spec.get('pmax') is None:
        spec['pmax'] = _num(at('Pmax'))
    if 'mode' in spec['params'] and spec['params']['mode'] is None:
        spec['params']['mode'] = _num(at('Value'))
    return spec


def _hashable(v: Any) -> bool:
    try:
        hash(v)
        return True
    except TypeError:
        return False


def columns_from_pdf(spec: Any) -> Dict[str, Any]:
    """The columns a spec fills in (``columnsFromPDF``); nothing for a spec of a
    kind neither format spells (a list of values, Ecolego's ``logn``)."""
    out: Dict[str, Any] = {}
    if not _truthy(spec):
        return out
    kind = _get(spec, 'kind')
    word = WORD.get(kind) if _hashable(kind) else None
    if not word:
        return out
    shape = SHAPES[word]
    out['Type'] = word
    params = _get(spec, 'params')
    for key, column in shape['params'].items():
        v = _get(params, key)
        if not _nullish(v):
            out[column] = v
    if shape['cut']:
        if not _nullish(_get(spec, 'trmin')):
            out['Min'] = spec['trmin']
        if not _nullish(_get(spec, 'trmax')):
            out['Max'] = spec['trmax']
    if not _nullish(_get(spec, 'pmin')):
        out['Pmin'] = spec['pmin']
    if not _nullish(_get(spec, 'pmax')):
        out['Pmax'] = spec['pmax']
    if _truthy(_get(spec, 'group')):
        out['Group'] = spec['group']
    return out


def pdf_to_json(spec: Any) -> Optional[Dict[str, Any]]:
    """The same spec as the JSON object an HDF5 attribute carries (``pdfToJSON``):
    ``{"type": "unif", "a": 1, "b": 2}``, the truncation as ``trmin``/``trmax``
    whatever the shape."""
    cols = columns_from_pdf(spec)
    if not cols.get('Type'):
        return None
    shape = SHAPES[cols['Type']]
    out: Dict[str, Any] = {'type': cols['Type']}
    params = _get(spec, 'params')
    for key in shape['params']:
        v = _get(params, key)
        if not _nullish(v):
            out[_HDF_NAME.get(key, key)] = v
    for key in ('trmin', 'trmax', 'pmin', 'pmax'):
        if not _nullish(_get(spec, key)):
            out[key] = spec[key]
    if _truthy(_get(spec, 'group')):
        out['group'] = spec['group']
    return out


def pdf_attribute(spec: Any) -> Any:
    """A spec as the ``pdf`` attribute holds it (``pdfAttribute``): the JSON
    object where its shape has a word, and Ecolego's expression otherwise --
    a log-normal by its mean, one through two quantiles, a list of values.
    ``None`` for what is not a distribution; a spec held as text is read first."""
    s = parse_pdf(spec) if isinstance(spec, str) else spec
    if not _truthy(s):
        return None
    return pdf_to_json(s) or (_expression_of(s) or None)


def _sheet_columns(spec: Any) -> Dict[str, Any]:
    """The columns a spec fills in on a sheet: the shape's own where they hold
    all of it, the PDF column otherwise."""
    s = parse_pdf(spec) if isinstance(spec, str) else spec
    if not _truthy(s):
        return {}
    if _fits_columns(s):
        return columns_from_pdf(s)
    expr = _expression_of(s)
    return {'PDF': expr} if expr else {}


def pdf_list_from_json(raw: Any) -> Optional[List[Optional[Dict[str, Any]]]]:
    """A list of specs, one per point, for a table whose points carry their own
    (``pdfListFromJSON``); ``None`` where the attribute is not a list."""
    if _nullish(raw):
        return None
    lst = raw
    if isinstance(raw, str):
        text = raw.strip(JS_WHITESPACE)
        if not text.startswith('['):
            return None
        try:
            lst = _json_parse(text)
        except ValueError:
            return None
    if not isinstance(lst, list):
        return None
    return [pdf_from_json(o) for o in lst]


def pdf_from_json(raw: Any) -> Optional[Dict[str, Any]]:
    """A spec from an HDF5 attribute (``pdfFromJSON``): the JSON object, or the
    expression itself (``unif(min=1,max=2)``); ``None`` for a list or for
    anything that is not a curve this reads. A truncation at a uniform's own
    ends is dropped: it cuts nothing off."""
    if not _truthy(raw):
        return None
    obj = raw
    if isinstance(raw, str):
        text = raw.strip(JS_WHITESPACE)
        if not text:
            return None
        if text.startswith('['):
            return None
        if not text.startswith('{'):
            return parse_pdf(text)
        try:
            obj = _json_parse(text)
        except ValueError:
            return None
    kind = _get(obj, 'type')
    shape = _shape(js_string('' if _nullish(kind) else kind).lower())
    if shape is None:
        return None
    group_name = _str(_get(obj, 'group'))
    spec: Dict[str, Any] = {
        'kind': shape['kind'],
        'params': {},
        'values': None,
        'trmin': _num(_get(obj, 'trmin')), 'trmax': _num(_get(obj, 'trmax')),
        'pmin': _num(_get(obj, 'pmin')), 'pmax': _num(_get(obj, 'pmax')),
        'group': group_name or None,
        'inorder': True, 'pos': 0,
    }
    for key in shape['params']:
        first = _get(obj, _HDF_NAME.get(key, key))
        spec['params'][key] = _num(_get(obj, key) if _nullish(first) else first)
    if not shape['cut']:
        if spec['trmin'] is not None and spec['trmin'] == spec['params']['min']:
            spec['trmin'] = None
        if spec['trmax'] is not None and spec['trmax'] == spec['params']['max']:
            spec['trmax'] = None
    return spec


# --- the spreadsheet ------------------------------------------------------------------------

def to_sheet(rows: Sequence[Mapping[str, Any]]) -> List[List[Any]]:
    """The rows of a data table as a grid, header first (``toSheet``). The
    helper columns say where the block lives and what it is called; trailing
    empty cells are left off."""
    grid: List[List[Any]] = [list(COLUMNS)]
    for r in rows:
        cells: List[Any] = [None] * len(COLUMNS)

        def put_cell(name: str, v: Any) -> None:
            cells[COLUMNS.index(name)] = None if v is _UNDEF else v

        rid = _get(r, 'id')
        put_cell('ID', rid)
        unit = _get(r, 'unit')
        put_cell('Unit', unit if _truthy(unit) else None)
        parts = _text(rid).split('.')
        block = _get(r, 'block')
        name = _get(block, 'name')
        own = parts[-1] if _nullish(name) else name
        system = _get(block, 'system')
        sub = '' if _nullish(system) else system
        put_cell('Subsystem', sub if _truthy(sub) else None)
        put_cell('Name', own if _truthy(own) else None)
        if not _nullish(_get(r, 'time')):
            put_cell('Time', r['time'])
        if not _nullish(_get(r, 'value')):
            put_cell('Value', r['value'])
        for k, v in _sheet_columns(_get(r, 'pdf')).items():
            put_cell(k, v)
        if _truthy(_get(r, 'note')):
            put_cell('Reference', r['note'])
        last = len(cells)
        while last > 0 and cells[last - 1] is None:
            last -= 1
        grid.append(cells[:last])
    return grid


def from_sheet(grid: Optional[Sequence[Any]], sheet: Any = '') -> Dict[str, List[Any]]:
    """A grid back to rows (``fromSheet``): ``{'rows', 'problems'}``.

    The header decides which column is which, by name; a sheet with neither an
    ``ID`` column nor any helper is refused rather than read as rows of
    nothing. Each row is ``{'id', 'unit', 'time', 'value', 'pdf', 'note',
    'row', 'sheet'}``, ``row`` counting from 1 with the header.
    """
    rows: List[Dict[str, Any]] = []
    problems: List[str] = []
    first = grid[0] if grid is not None and len(grid) and grid[0] is not None else []
    header = [_str(h) for h in first]
    where: Dict[str, int] = {}
    for i, h in enumerate(header):
        if h and h not in where:
            where[h] = i
    if 'ID' not in where and not any(h in where for h in HELPERS):
        return {'rows': rows, 'problems': [f"{js_string(sheet) if _truthy(sheet) else 'The sheet'} has no ID column."]}
    for i in range(1, len(grid) if grid is not None else 0):
        line = grid[i] if grid[i] is not None else []

        def at(name: str, line: Sequence[Any] = line) -> Any:
            k = where.get(name)
            if k is None:
                return None
            return line[k] if k < len(line) else None

        rid = _str(at('ID'))
        if not rid:
            rid = '.'.join(p for p in (_str(at(h)) for h in HELPERS) if p)
        if not rid:
            continue
        cell = _value(at('Value'))
        time = _num(at('Time'))
        spec = pdf_from_columns(at)
        bad = spec.get('bad') if spec is not None else None
        if _truthy(bad):
            problems.append(f'Row {i + 1}: {bad}.')
        rows.append({
            'id': rid, 'unit': _str(at('Unit')), 'time': time, 'value': cell,
            'pdf': spec if spec is not None and not _truthy(bad) else None,
            'note': _str(at('Reference')), 'row': i + 1, 'sheet': sheet,
        })
    return {'rows': rows, 'problems': problems}


def write_data_workbook(rows: Sequence[Mapping[str, Any]], name: Any = 'data', *, modified: Any = None,
                        compress: bool = True) -> bytes:
    """A workbook of one sheet of the rows (``writeDataWorkbook``), as bytes.
    ``modified`` and ``compress`` are :func:`kompartment.io.xlsx.write_workbook`'s."""
    return write_workbook({'sheets': [{'name': name, 'rows': to_sheet(rows)}]}, modified=modified,
                          compress=compress)


def read_data_workbook(data: Any) -> Dict[str, List[Any]]:
    """Every sheet of a workbook, read as rows (``readDataWorkbook``):
    ``{'rows', 'problems'}``. ``data`` is the file's bytes or its path."""
    book = read_workbook(data)
    rows: List[Dict[str, Any]] = []
    problems: List[str] = []
    for sheet in book['sheets']:
        got = from_sheet(sheet['rows'], sheet=sheet['name'])
        rows.extend(got['rows'])
        problems.extend(got['problems'])
    return {'rows': rows, 'problems': problems}


# --- the HDF5 tree --------------------------------------------------------------------------

def _segment(s: Any) -> str:
    """A path segment HDF5 can hold: ``/`` is the separator and cannot be in one."""
    return _text(s).replace('/', '_')


def to_tree(rows: Sequence[Mapping[str, Any]], root: Any = 'model') -> Group:
    """The rows as a tree under one root group named after the model (``toTree``).

    A parameter is a dataset of its one value (text where the value is not a
    number); a lookup table, put after every parameter, is its values with the
    times beside them in ``index``, sorted, and a list of specs in ``pdf`` where
    any point carries one.
    """
    tree = group({})
    tables: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        path = [_segment(root), *(_segment(p) for p in _text(_get(r, 'id')).split('.'))]
        time = _get(r, 'time')
        if not _nullish(time):
            key = '/'.join(path)
            if key not in tables:
                tables[key] = {'path': path, 'times': [], 'values': [], 'pdfs': [], 'row': r}
            t = tables[key]
            t['times'].append(time)
            value = _get(r, 'value')
            t['values'].append(math.nan if _nullish(value) else value)
            pdf = _get(r, 'pdf')
            t['pdfs'].append(None if _nullish(pdf) else pdf)
            continue
        unit = _get(r, 'unit')
        attrs: Dict[str, Any] = {'unit': '' if _nullish(unit) else unit}
        pdf = pdf_attribute(_get(r, 'pdf'))
        if pdf:
            attrs['pdf'] = pdf if isinstance(pdf, str) else _stringify(pdf)
        if _truthy(_get(r, 'note')):
            attrs['reference'] = r['note']
        value = _get(r, 'value')
        # A value that is not a number goes out as text rather than as NaN.
        put(tree, path, dataset([value], STR, attrs) if isinstance(value, str)
            else dataset([math.nan if _nullish(value) else value], F64, attrs))
    for t in tables.values():
        times = t['times']
        order = sorted(range(len(times)),
                       key=cmp_to_key(lambda a, b: _cmp(js_to_number(times[a]) - js_to_number(times[b]))))
        unit = _get(t['row'], 'unit')
        attrs = {
            'unit': '' if _nullish(unit) else unit,
            'lookup_table': 'true',
            'index': ','.join(js_string(times[i]) for i in order),
        }
        specs = [pdf_attribute(t['pdfs'][i]) for i in order]
        if any(s is not None for s in specs):
            attrs['pdf'] = _stringify(specs)
        if _truthy(_get(t['row'], 'note')):
            attrs['reference'] = t['row']['note']
        put(tree, t['path'], dataset([t['values'][i] for i in order], F64, attrs))
    return tree


def write_data_hdf5(rows: Sequence[Mapping[str, Any]], root: Any = 'model') -> bytes:
    """The tree written out (``writeDataHDF5``), as bytes."""
    return write_hdf5(to_tree(rows, root=root))


def _index_times(raw: Any) -> Optional[List[float]]:
    """The ``index`` attribute, however it was written: a list, or a string of
    numbers -- where an empty piece at either end reads as 0, as ``Number('')``."""
    if _nullish(raw):
        return None
    if isinstance(raw, (list, tuple)) or _is_view(raw):
        return [js_to_number(x) for x in (raw.tolist() if hasattr(raw, 'tolist') else raw)]
    # Empty pieces are separators at either end, not times of 0.
    parts = [js_to_number(s) for s in _SPLIT.split(js_string(raw)) if s != '']
    parts = [n for n in parts if _finite(n)]
    return parts or None


def _subarray(values: Any, begin: int, end: Optional[int] = None) -> Any:
    """``values.subarray(begin, end)``: a slice of a typed array."""
    return values[begin:end]


def read_data_hdf5(data: Any) -> Dict[str, List[Any]]:
    """An HDF5 file read as rows (``readDataHDF5``): ``{'rows', 'problems'}``.

    The first path segment is the file's own root name and is dropped; the rest
    join with dots into the id. ``/time`` (or ``/Time``, ``/times``) and
    ``/IndexLists`` are how the file is put together and are not rows. A value
    of a sample comes back as a ``pg`` spec whose values are an
    ``array('d')`` (the application's is a view into the file's array).
    """
    got = read_hdf5(data)
    datasets, problems = got['datasets'], got['problems']
    rows: List[Dict[str, Any]] = []
    clock = next((d['values'] for d in datasets if d['path'] in TIME_PATHS), None)
    for d in datasets:
        parts = [p for p in d['path'].split('/') if p]
        if len(parts) < 2:
            continue
        if d['path'] in TIME_PATHS or parts[0] == 'IndexLists':
            continue
        rid = '.'.join(parts[1:])
        attrs = d.get('attrs') or {}
        unit = _str(_get(attrs, 'unit'))
        note = _str(_get(attrs, 'reference'))
        times = _index_times(_get(attrs, 'index'))
        table = _get(attrs, 'lookup_table')
        is_table = not _nullish(table) and js_string(table).lower() != 'false'
        raw = _raw_of(_get(attrs, 'pdf'))
        sampled = raw is not None or _flagged(_get(attrs, 'probabilistic'))
        dims = d.get('dims') or []
        values = d['values']

        # A sample is numbers: text marked as one, or nothing, is said and left out.
        not_numbers = (f"{d['path']}: is marked as a sample but {'holds text' if len(values) else 'holds nothing'}, "
                       'so it was not read.')

        # A matrix of realisations: one whole curve per column.
        if len(dims) == 2 and sampled:
            if not _is_view(values):
                problems.append(not_numbers)
                continue
            n_t, n_r = dims
            when = times if times is not None and len(times) == n_t else (
                clock if clock is not None and len(clock) == n_t else None)
            if when is None:
                problems.append(f"{d['path']}: is {_text(n_t)}×{_text(n_r)} and nothing in the file says what the "
                                f'{_text(n_t)} are times of.')
                continue
            for t in range(int(n_t or 0)):
                at = _subarray(values, t * n_r, (t + 1) * n_r)
                rows.append({'id': rid, 'unit': unit, 'time': when[t], 'value': _middle(at),
                             'pdf': sample_spec(at), 'note': note})
            continue

        # A column of realisations: one value each.
        if len(dims) == 1 and sampled and not is_table:
            if not _is_view(values):
                problems.append(not_numbers)
                continue
            deterministic = raw is not None and raw['deterministic']
            sample = _subarray(values, 1) if deterministic else values
            first = (values[0] if len(values) else None) if deterministic else _middle(sample)
            rows.append({'id': rid, 'unit': unit, 'time': None, 'value': first,
                         'pdf': sample_spec(sample), 'note': note})
            continue

        if is_table:
            # Times and values that do not pair up are not a table, and not a
            # single value either.
            n = len(values)
            if times is None or len(times) != n:
                m = 0 if times is None else len(times)
                problems.append(f"{d['path']}: is a lookup table of {n} value{'' if n == 1 else 's'} and "
                                f"{m} time{'' if m == 1 else 's'}, so it was not read.")
                continue
            specs = pdf_list_from_json(_get(attrs, 'pdf'))
            for i in range(len(times)):
                spec = specs[i] if specs is not None and i < len(specs) else None
                rows.append({'id': rid, 'unit': unit, 'time': times[i], 'value': values[i],
                             'pdf': spec, 'note': note})
            continue

        rows.append({'id': rid, 'unit': unit, 'time': None, 'value': values[0] if len(values) else None,
                     'pdf': pdf_from_json(_get(attrs, 'pdf')), 'note': note})
    return {'rows': rows, 'problems': problems}


def usable(spec: Any) -> bool:
    """Whether a spec is worth writing (``usable``): a kind this knows -- the
    application's own kinds, not a property every JavaScript object has --
    filled in."""
    if not _truthy(spec):
        return False
    kind = _get(spec, 'kind')
    if not isinstance(kind, str) or kind not in PDF_KINDS:
        return False
    return complete(spec)
