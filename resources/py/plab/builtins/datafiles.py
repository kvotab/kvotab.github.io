"""Structs in XML and JSON files (readstruct, writestruct), spreadsheets the
older way (xlsread, xlswrite, xlsfinfo), and timetables from files
(readtimetable).

XML is read into a struct by these rules: each child element is a field;
an element with only text is its value (a number when the text is one, else
a string); an element's attributes are fields named with the suffix
'Attribute', and its text beside children or attributes the field 'Text';
elements of the same name repeated make an array (of numbers or strings) or
a struct array. writestruct writes the same layout back.
"""
import math
import os
import re

import numpy as np

from . import bi as _register
from ._util import err, nargchk, out, num, opt_str, is_str, darr
from ..values import MError, Char, Cell, Struct, Str, EMPTY, numel, py_str, shape_of
from .. import runtime as R


def bi(*names, **kw):
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError, OSError) as e:
                raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _opts(args, names):
    low = {n.lower(): n for n in names}
    got, rest = {}, []
    i = 0
    while i < len(args):
        s = opt_str(args[i])
        if s is not None and s.lower() in low and i + 1 < len(args):
            got[low[s.lower()]] = args[i + 1]
            i += 2
            continue
        rest.append(args[i])
        i += 1
    return got, rest


def _existing(v, fn):
    from .iofun import _existing as ex
    return ex(v, fn)


def _abspath(v):
    from .iofun import abspath
    return abspath(py_str(v))


def _changed(p):
    from .iofun import files_changed
    files_changed(os.path.dirname(p))


# ---- XML and JSON structs ---------------------------------------------------------------------------------------------------

_NUM = re.compile(r'^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*$|^\s*[-+]?(Inf|NaN)\s*$')


def _leaf(text):
    t = (text or '').strip()
    if _NUM.match(t):
        return float(t)
    return t


def _local(tag):
    return tag.rsplit('}', 1)[-1]


def _xml_value(el, suffix, read_attrs):
    """An element as a value: its text alone, or a dict of fields (attributes, children, Text)."""
    kids = list(el)
    attrs = el.attrib if read_attrs else {}
    if not kids and not attrs:
        return _leaf(el.text)
    d = {}
    for k, v in attrs.items():
        d[_valid(_local(k)) + suffix] = _leaf(v)
    groups = {}
    for c in kids:
        groups.setdefault(_valid(_local(c.tag)), []).append(_xml_value(c, suffix, read_attrs))
    for k, vals in groups.items():
        d[k] = vals if len(vals) > 1 else vals[0]
    text = (el.text or '').strip()
    if text:
        d['Text'] = _leaf(text)
    return d


def _valid(name):
    n = re.sub(r'\W', '_', name)
    if not n or not (n[0].isalpha()):
        n = 'x' + n
    return n[:63]


def _to_value(x):
    """What the reader made, as a value of the language."""
    if isinstance(x, dict):
        return Struct.scalar({k: _to_value(v) for k, v in x.items()})
    if isinstance(x, list):
        if all(isinstance(v, float) for v in x):
            return np.array([x], float)
        if all(isinstance(v, str) for v in x):
            return Str(np.array([x], object))
        if all(isinstance(v, dict) for v in x):
            keys = list(dict.fromkeys(k for v in x for k in v))
            s = Struct.empty((1, len(x)), keys)
            for i, v in enumerate(x):
                for k in keys:
                    s.f[k][0, i] = _to_value(v[k]) if k in v else EMPTY()
            return s
        c = Cell.empty((1, len(x)))
        for i, v in enumerate(x):
            c.a[0, i] = _to_value(v)
        return c
    if isinstance(x, float):
        return x
    return Str(np.array([[x]], object))


@bi('readstruct')
def readstruct(nargout, *args):
    """S = readstruct(filename, 'FileType', 'xml'|'json', 'AttributeSuffix', s, 'StructNodeName', name, 'ReadAttributes', tf): a struct from an XML (or JSON) file."""
    nargchk(args, 1, 9, 'readstruct')
    opts, rest = _opts(list(args[1:]), ('FileType', 'AttributeSuffix', 'StructNodeName', 'ReadAttributes', 'StructSelector'))
    p = _existing(args[0], 'readstruct')
    ftype = py_str(opts['FileType']).lower() if 'FileType' in opts else ('json' if p.lower().endswith('.json') else 'xml')
    if ftype == 'json':
        with open(p, encoding='utf-8') as f:
            text = f.read()
        v = R._builtin('jsondecode', Char.of(text))
        if not isinstance(v, Struct):
            raise err('MATLAB:readstruct:notStruct', 'The JSON file does not hold an object.', 'readstruct')
        return v
    if ftype != 'xml':
        raise err('MATLAB:readstruct:fileType', "The FileType is 'xml' or 'json'.", 'readstruct')
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(p).getroot()
    except ET.ParseError as e:
        raise err('MATLAB:readstruct:parse', f'The file is not well-formed XML: {e}.', 'readstruct')
    if 'StructNodeName' in opts:
        name = py_str(opts['StructNodeName'])
        found = root if _local(root.tag) == name else next((e for e in root.iter() if _local(e.tag) == name), None)
        if found is None:
            raise err('MATLAB:readstruct:node', f"The file has no element '{name}'.", 'readstruct')
        root = found
    suffix = py_str(opts['AttributeSuffix']) if 'AttributeSuffix' in opts else 'Attribute'
    read_attrs = bool(num(opts['ReadAttributes'])) if 'ReadAttributes' in opts else True
    v = _xml_value(root, suffix, read_attrs)
    if not isinstance(v, dict):
        v = {'Text': v}
    return _to_value(v)


def _texts_of(v):
    """A value as the texts of the elements it becomes (one each; arrays give several)."""
    if isinstance(v, Char):
        return [v.str()] if v.a.shape[0] <= 1 else v.row_strs()
    if isinstance(v, Str):
        return ['' if x is None else str(x) for x in v.a.reshape(-1, order='F')]
    if isinstance(v, (bool, np.bool_)):
        return ['true' if v else 'false']
    if isinstance(v, (float, int)):
        return [_num_text(v)]
    a = np.asarray(v)
    if a.dtype == bool:
        return ['true' if x else 'false' for x in a.reshape(-1, order='F')]
    if a.dtype.kind in 'iuf':
        return [_num_text(x) for x in a.reshape(-1, order='F')]
    raise err('MATLAB:writestruct:type', f'A value of class {type(v).__name__} cannot be written to XML.', 'writestruct')


def _num_text(x):
    x = float(x)
    if math.isnan(x):
        return 'NaN'
    if math.isinf(x):
        return 'Inf' if x > 0 else '-Inf'
    return str(int(x)) if x.is_integer() and abs(x) < 1e15 else repr(x)


def _write_el(name, v, suffix, depth, lines):
    from xml.sax.saxutils import escape, quoteattr
    pad = '   ' * depth
    if isinstance(v, Struct):
        for i in range(v.size):
            e = v.elem(i)
            attrs = ''.join(f' {k[:-len(suffix)]}={quoteattr(_texts_of(x)[0])}' for k, x in e.items() if suffix and k.endswith(suffix) and len(k) > len(suffix))
            kids = [(k, x) for k, x in e.items() if not (suffix and k.endswith(suffix) and len(k) > len(suffix)) and k != 'Text']
            text = escape(' '.join(_texts_of(e['Text']))) if 'Text' in e and numel(e['Text']) else ''
            if not kids:
                lines.append(f'{pad}<{name}{attrs}>{text}</{name}>' if text else f'{pad}<{name}{attrs}/>')
                continue
            lines.append(f'{pad}<{name}{attrs}>{text}')
            for k, x in kids:
                _write_el(k, x, suffix, depth + 1, lines)
            lines.append(f'{pad}</{name}>')
        return
    if isinstance(v, Cell):
        for x in v.a.reshape(-1, order='F'):
            _write_el(name, x, suffix, depth, lines)
        return
    if numel(v) == 0 and not isinstance(v, (Char, Str)):
        lines.append(f'{pad}<{name}/>')
        return
    for t in _texts_of(v):
        lines.append(f'{pad}<{name}>{escape(t)}</{name}>')


@bi('writestruct')
def writestruct(nargout, *args):
    """writestruct(S, filename, 'FileType', 'xml'|'json', 'StructNodeName', name, 'AttributeSuffix', s, 'PrettyPrint', tf): a struct written as XML (or JSON)."""
    nargchk(args, 2, 10, 'writestruct')
    S = args[0]
    if not isinstance(S, Struct):
        raise err('MATLAB:writestruct:struct', 'writestruct writes a struct.', 'writestruct')
    opts, _ = _opts(list(args[2:]), ('FileType', 'StructNodeName', 'AttributeSuffix', 'PrettyPrint'))
    p = _abspath(args[1])
    ftype = py_str(opts['FileType']).lower() if 'FileType' in opts else ('json' if p.lower().endswith('.json') else 'xml')
    if ftype == 'json':
        pretty = bool(num(opts['PrettyPrint'])) if 'PrettyPrint' in opts else True
        text = R._builtin('jsonencode', S, Char.of('PrettyPrint'), pretty)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(py_str(text) + '\n')
    elif ftype == 'xml':
        root = py_str(opts['StructNodeName']) if 'StructNodeName' in opts else 'struct'
        suffix = py_str(opts['AttributeSuffix']) if 'AttributeSuffix' in opts else 'Attribute'
        lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        _write_el(root, S if S.size == 1 else Struct.scalar({root: S}), suffix, 0, lines)
        with open(p, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
    else:
        raise err('MATLAB:writestruct:fileType', "The FileType is 'xml' or 'json'.", 'writestruct')
    _changed(p)
    return None


# ---- spreadsheets -----------------------------------------------------------------------------------------------------------------

def _cell_ref(ref):
    m = re.fullmatch(r'\s*([A-Za-z]+)(\d+)\s*', ref)
    if not m:
        raise err('MATLAB:xlsread:range', f"'{ref}' is not a cell such as 'B2'.", 'xlsread')
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + ord(ch) - 64
    return int(m.group(2)) - 1, col - 1


def _range(text):
    parts = text.split(':')
    r0, c0 = _cell_ref(parts[0])
    r1, c1 = _cell_ref(parts[1]) if len(parts) > 1 else (None, None)
    return r0, c0, r1, c1


_RANGE_RE = re.compile(r'\s*[A-Za-z]+\d+(\s*:\s*[A-Za-z]+\d+)?\s*')


def _sheet_range(extra):
    """(sheet, range) from the arguments after the file: one alone is a range when it looks like one, else the sheet."""
    def sheet_of(a):
        return py_str(a) if is_str(a) else (int(num(a)) if numel(a) else None)
    if len(extra) == 1:
        a = extra[0]
        if is_str(a) and _RANGE_RE.fullmatch(py_str(a)):
            return None, py_str(a).replace(' ', '')
        return sheet_of(a), None
    if len(extra) >= 2:
        return sheet_of(extra[0]), py_str(extra[1]).replace(' ', '') if is_str(extra[1]) and py_str(extra[1]) else None
    return None, None


def _sheet_rows(p, sheet):
    from .tables import _xlsx_read, _text_rows
    if p.lower().endswith(('.csv', '.txt')):
        rows = _text_rows(p, ',')
        return [[(float(x) if _NUM.match(str(x)) else (None if str(x).strip() == '' else str(x))) if isinstance(x, str) else x for x in r] for r in rows]
    return _xlsx_read(p, sheet)


def _trim(mask):
    """The bounding rows and columns of the true entries of mask (or None)."""
    rr, cc = np.nonzero(mask)
    if rr.size == 0:
        return None
    return rr.min(), rr.max() + 1, cc.min(), cc.max() + 1


@bi('xlsread', nout=3)
def xlsread(nargout, *args):
    """[num, txt, raw] = xlsread(filename, sheet, range): a sheet's numbers (the numeric block, NaN between), its texts and all its cells."""
    nargchk(args, 1, 4, 'xlsread')
    p = _existing(args[0], 'xlsread')
    sheet, rng = _sheet_range([a for a in args[1:] if not (is_str(a) and py_str(a).lower() in ('basic', ''))])
    rows = _sheet_rows(p, sheet)
    w = max((len(r) for r in rows), default=0)
    rows = [list(r) + [None] * (w - len(r)) for r in rows]
    if rng:
        r0, c0, r1, c1 = _range(rng)
        r1 = len(rows) if r1 is None and ':' in rng else (r0 + 1 if r1 is None else r1 + 1)
        c1 = w if c1 is None and ':' in rng else (c0 + 1 if c1 is None else c1 + 1)
        rows = [(r + [None] * max(0, c1 - len(r)))[c0:c1] for r in (rows[r0:r1] + [[None] * w] * max(0, r1 - len(rows)))]
    n_r, n_c = len(rows), (len(rows[0]) if rows else 0)
    isnum = np.array([[isinstance(v, (float, int, bool)) and not isinstance(v, str) for v in r] for r in rows], bool).reshape(n_r, n_c)
    istxt = np.array([[isinstance(v, str) and v != '' for v in r] for r in rows], bool).reshape(n_r, n_c)
    numv = np.full((n_r, n_c), np.nan)
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            if isnum[i, j]:
                numv[i, j] = float(v)
    b = _trim(isnum)
    num_out = numv[b[0]:b[1], b[2]:b[3]] if b else np.zeros((0, 0))
    res = [num_out]
    if nargout > 1:
        bt = _trim(istxt)
        if bt:
            txt = Cell.empty((bt[1] - bt[0], bt[3] - bt[2]))
            for i in range(bt[0], bt[1]):
                for j in range(bt[2], bt[3]):
                    txt.a[i - bt[0], j - bt[2]] = Char.of(rows[i][j] if istxt[i, j] else '')
        else:
            txt = Cell.empty((0, 0))
        res.append(txt)
    if nargout > 2:
        braw = _trim(isnum | istxt)
        if braw:
            raw = Cell.empty((braw[1], braw[3]))
            for i in range(braw[1]):
                for j in range(braw[3]):
                    v = rows[i][j]
                    raw.a[i, j] = Char.of(v) if isinstance(v, str) else (bool(v) if isinstance(v, bool) else (float(v) if v is not None else np.nan))
        else:
            raw = Cell.empty((0, 0))
        res.append(raw)
    return tuple(res) if nargout > 1 else res[0]


def _cell_values(A):
    """A matrix or cell array as rows of str, float, bool or None."""
    if isinstance(A, Cell):
        a = A.a if A.a.ndim == 2 else A.a.reshape(A.a.shape[0], -1, order='F')
        rows = []
        for i in range(a.shape[0]):
            row = []
            for x in a[i]:
                if isinstance(x, (Char, Str)):
                    row.append(py_str(x))
                elif numel(x) == 0:
                    row.append(None)
                elif numel(x) == 1:
                    v = np.asarray(x).reshape(-1)[0]
                    row.append(bool(v) if np.asarray(x).dtype == bool else float(v))
                else:
                    raise err('MATLAB:xlswrite:cell', 'Each cell of the cell array holds one number or a text.', 'xlswrite')
            rows.append(row)
        return rows
    if isinstance(A, (Char, Str)):
        return [[py_str(A)]]
    a = darr(A, 'xlswrite')
    if a.ndim == 1:
        a = a.reshape(1, -1)
    if a.ndim > 2:
        raise err('MATLAB:xlswrite:dims', 'xlswrite writes a matrix or a cell array.', 'xlswrite')
    return [[bool(v) if a.dtype == bool else float(v) for v in r] for r in a]


@bi('xlswrite', nout=2)
def xlswrite(nargout, *args):
    """xlswrite(filename, A, sheet, range): a matrix or cell array written into a sheet of an .xlsx file, from the range's top-left cell (A1)."""
    nargchk(args, 2, 4, 'xlswrite')
    from .tables import _xlsx_read, _xlsx_sheets, _xlsx_write_book
    p = _abspath(args[0])
    if not os.path.splitext(p)[1]:
        p += '.xlsx'
    if not p.lower().endswith(('.xlsx', '.xlsm')):
        raise err('MATLAB:xlswrite:format', 'xlswrite writes .xlsx files here (writematrix and writetable write text files).', 'xlswrite')
    cells = _cell_values(args[1])
    sheet, rng = _sheet_range(list(args[2:]))
    rng = rng or 'A1'
    book = []
    if os.path.isfile(p):
        names = _xlsx_sheets(p)
        book = [(nm, _xlsx_read(p, nm)) for nm in names]
    if sheet is None:
        k = 0
    elif isinstance(sheet, int):
        k = sheet - 1
    else:
        k = next((i for i, (nm, _) in enumerate(book) if nm == sheet), len(book))
    while len(book) <= k:
        book.append((sheet if isinstance(sheet, str) and len(book) == k else f'Sheet{len(book) + 1}', []))
    name, rows = book[k]
    rows = [list(r) for r in rows]
    r0, c0, r1, c1 = _range(rng)
    if r1 is not None:
        cells = [row[:c1 - c0 + 1] for row in cells[:r1 - r0 + 1]]
    for i, row in enumerate(cells):
        while len(rows) <= r0 + i:
            rows.append([])
        target = rows[r0 + i]
        while len(target) < c0 + len(row):
            target.append(None)
        for j, v in enumerate(row):
            target[c0 + j] = v
    book[k] = (name, rows)
    _xlsx_write_book(p, book)
    _changed(p)
    return (True, Struct.scalar({'message': Char.of(''), 'identifier': Char.of('')})) if nargout > 1 else (True if nargout else None)


@bi('xlsfinfo', nout=3)
def xlsfinfo(nargout, *args):
    """[status, sheets] = xlsfinfo(filename): whether the file is a spreadsheet, and its sheets' names."""
    nargchk(args, 1, 1, 'xlsfinfo')
    from .tables import _xlsx_sheets
    p = _existing(args[0], 'xlsfinfo')
    try:
        names = _xlsx_sheets(p)
        status = 'Microsoft Excel Spreadsheet'
    except Exception:
        names, status = [], ''
    res = (Char.of(status), Cell.of_list([Char.of(n) for n in names]), Char.of('xlOpenXMLWorkbook' if names else ''))
    return res[:nargout] if nargout > 1 else res[0]


@bi('readtimetable', arr=False)
def readtimetable(nargout, *args):
    """TT = readtimetable(filename, 'RowTimes', var, ...): a timetable from a file, the first datetime (or duration) column its row times; readtable's options."""
    nargchk(args, 1, 20, 'readtimetable')
    rt = None
    rest = []
    i = 0
    while i < len(args):
        s = opt_str(args[i]) if i > 0 else None
        if s is not None and s.lower() == 'rowtimes' and i + 1 < len(args):
            rt = args[i + 1]
            i += 2
            continue
        rest.append(args[i])
        i += 1
    T = R._builtin('readtable', *rest)
    return R._builtin('table2timetable', T, Char.of('RowTimes'), rt) if rt is not None else R._builtin('table2timetable', T)
