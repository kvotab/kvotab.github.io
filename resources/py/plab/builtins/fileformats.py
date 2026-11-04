"""More file formats: Parquet files (parquetread, parquetwrite, parquetinfo)
through pyarrow, which the page loads the first time one is read or written;
FITS files (fitsread, fitsinfo, fitswrite, fitsdisp) read and written here,
images and ASCII and binary tables; and writetimetable.
"""
import math
import os
import time

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, arr, darr, out, opt_str, is_str, sval, num
from ..values import MError, Char, Cell, Struct, Str, EMPTY, numel, py_str, shape_of, class_of
from .. import runtime as R


def bi(*names, **kw):
    """Registered as builtins are, with what NumPy refuses told as the function's own error."""
    def deco(f):
        if kw.get('aw'):
            async def g(*a):
                try:
                    return await f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError, OverflowError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        else:
            def g(*a):
                try:
                    return f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError, OverflowError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _opts(args, names, fn):
    pos, opts = [], {}
    k = 0
    args = list(args)
    while k < len(args):
        o = opt_str(args[k])
        if o is not None and o.lower() in names and k + 1 < len(args):
            opts[o.lower()] = args[k + 1]
            k += 2
            continue
        if opts or (o is not None and k > 0 and k + 1 < len(args) and fn != 'fitsread'):
            raise err(f'MATLAB:{fn}:InvalidParameter', f"'{o if o is not None else class_of(args[k])}' is not an option of {fn}.", fn)
        pos.append(args[k])
        k += 1
    return pos, opts


# ---- writetimetable ------------------------------------------------------------------------------------------------------

@bi('writetimetable', arr=False)
def writetimetable(nargout, *args):
    """writetimetable(TT, filename): a timetable written as writetable writes
    a table, its row times the first column."""
    nargchk(args, 1, 20, 'writetimetable')
    from .tables import TimeTable
    if not isinstance(args[0], TimeTable):
        raise err('MATLAB:writetimetable:NotTimetable', 'writetimetable takes a timetable: use writetable for a table.', 'writetimetable')
    rest = list(args[1:]) or [Char.of('timetable.txt')]
    return REG['writetable'].fn(0, args[0], *rest)


# ---- Parquet --------------------------------------------------------------------------------------------------------------

async def need_pyarrow(fn):
    """pyarrow (and pandas, which it needs), loaded into the page the first time."""
    try:
        import pyarrow  # noqa: F401
        import pyarrow.parquet  # noqa: F401
        return
    except ImportError:
        pass
    try:
        import pyodide_js
    except ImportError:
        raise err(f'MATLAB:{fn}:noPyarrow', 'Parquet files need the pyarrow package (pip install pyarrow).', fn)
    try:
        await pyodide_js.loadPackage('pyarrow')
    except Exception as e:
        raise err(f'MATLAB:{fn}:noPyarrow', f'pyarrow, which reads and writes Parquet files, could not be loaded ({e}).', fn)


def _pa():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise err('MATLAB:parquetread:noPyarrow', 'Parquet files need the pyarrow package: call parquetread or parquetinfo first, which loads it.', 'parquetread')
    return pa, pq


def parquet_names(p):
    pa, pq = _pa()
    try:
        return list(pq.read_schema(p).names)
    except (OSError, pa.ArrowException) as e:
        raise err('MATLAB:parquetread:FileReadError', f'{os.path.basename(p)} is not a Parquet file that can be read: {e}', 'parquetread')


def _column(col):
    """A table variable from an Arrow column."""
    pa, _ = _pa()
    from .timetypes import DateTime, Duration
    from .categoricals import Categorical
    t = col.type
    n = len(col)
    nulls = col.is_null().to_numpy(zero_copy_only=False).astype(bool) if col.null_count else np.zeros(n, bool)
    T = pa.types
    if T.is_dictionary(t):
        # the categories in the dictionary's order (those no row uses too), each chunk's mapped onto them
        cats, codes = [], []
        for ch in col.chunks:
            names = [str(x) for x in ch.dictionary.to_pylist()]
            for nm in names:
                if nm not in cats:
                    cats.append(nm)
            where = np.array([cats.index(nm) + 1.0 for nm in names] + [0.0])
            ix = ch.indices.to_numpy(zero_copy_only=False)
            ix = np.where(ch.is_null().to_numpy(zero_copy_only=False), -1, np.nan_to_num(np.asarray(ix, float), nan=-1)).astype(int)
            codes.append(where[ix])
        a = np.concatenate(codes) if codes else np.zeros(0)
        return Categorical(a.reshape(-1, 1), cats, bool(t.ordered))
    if T.is_boolean(t):
        a = col.to_numpy(zero_copy_only=False)
        if nulls.any():
            r = np.where(nulls, np.nan, np.asarray([bool(x) if x is not None else False for x in a], float))
            return r.reshape(-1, 1)
        return np.asarray(a, bool).reshape(-1, 1)
    if T.is_integer(t):
        if nulls.any():
            a = col.cast(pa.float64()).to_numpy(zero_copy_only=False)
            return np.where(nulls, np.nan, a).astype(float).reshape(-1, 1)
        return np.asarray(col.to_numpy(zero_copy_only=False)).reshape(-1, 1)
    if T.is_floating(t) or T.is_decimal(t):
        a = col.cast(pa.float64()).to_numpy(zero_copy_only=False) if not T.is_floating(t) else col.to_numpy(zero_copy_only=False)
        a = np.asarray(a, np.float32 if T.is_float32(t) else float)
        if nulls.any():
            a = np.where(nulls, np.nan, a).astype(a.dtype)
        return a.reshape(-1, 1)
    if T.is_string(t) or T.is_large_string(t):
        return Str(np.array([None if v is None else v for v in col.to_pylist()] + [''], object)[:-1].reshape(-1, 1))
    if T.is_timestamp(t):
        scale = {'s': 1.0, 'ms': 1e3, 'us': 1e6, 'ns': 1e9}[t.unit]
        a = col.cast(pa.int64()).to_numpy(zero_copy_only=False).astype(float) / scale
        a = np.where(nulls, np.nan, a)
        return DateTime(a.reshape(-1, 1), 'dd-MMM-uuuu HH:mm:ss', t.tz or '')
    if T.is_date(t):
        if T.is_date32(t):
            a = col.cast(pa.int32()).to_numpy(zero_copy_only=False).astype(float) * 86400.0
        else:
            a = col.cast(pa.int64()).to_numpy(zero_copy_only=False).astype(float) / 1e3
        a = np.where(nulls, np.nan, a)
        return DateTime(a.reshape(-1, 1), 'dd-MMM-uuuu')
    if T.is_time(t) or T.is_duration(t):
        scale = {'s': 1.0, 'ms': 1e3, 'us': 1e6, 'ns': 1e9}[t.unit]
        a = col.cast(pa.int64()).to_numpy(zero_copy_only=False).astype(float) / scale
        a = np.where(nulls, np.nan, a)
        return Duration(a.reshape(-1, 1))
    if T.is_binary(t) or T.is_large_binary(t) or T.is_fixed_size_binary(t):
        vals = col.to_pylist()
        return Cell.of_list([np.zeros((0, 1), np.uint8) if v is None else np.frombuffer(v, np.uint8).reshape(-1, 1).copy() for v in vals], (n, 1))
    if T.is_list(t) or T.is_large_list(t) or T.is_fixed_size_list(t):
        vals = col.to_pylist()
        items = []
        for v in vals:
            if v is None:
                items.append(EMPTY())
            elif all(isinstance(x, str) or x is None for x in v) and v:
                items.append(Str(np.array([x for x in v] + [''], object)[:-1].reshape(-1, 1)))
            else:
                items.append(np.array([np.nan if x is None else x for x in v], float).reshape(-1, 1))
        return Cell.of_list(items, (n, 1))
    raise err('MATLAB:parquetread:UnsupportedType', f"Parquet columns of type {t} are not read here.", 'parquetread')


def read_parquet(p, select, rule='modify'):
    """A Parquet file as a table (only the variables selected, when given)."""
    pa, pq = _pa()
    from .tables import Table, _valid_name
    try:
        tab = pq.read_table(p, columns=select)
    except (OSError, pa.ArrowException) as e:
        raise err('MATLAB:parquetread:FileReadError', f'{os.path.basename(p)} cannot be read as a Parquet file: {e}', 'parquetread')
    names = []
    for nm in tab.column_names:
        h = nm
        if rule == 'modify' and not _valid_name(h):
            h = py_str(REG['matlab.lang.makeValidName'].fn(1, Char.of(h)))
        while h in names:
            h = h + '_1'
        names.append(h)
    vars_ = [_column(tab.column(i)) for i in range(tab.num_columns)]
    return Table(vars_, names, None, tab.num_rows)


def _texts(v, fn, what):
    if type(v) is Char:
        return [v.str()]
    if type(v) is Str:
        return ['' if s is None else s for s in v.a.reshape(-1, order='F')]
    if type(v) is Cell and all(is_str(c) for c in v.a.reshape(-1)):
        return [py_str(c) for c in v.a.reshape(-1, order='F')]
    raise err(f'MATLAB:{fn}:InvalidInput', f'{what} is text, a string array or a cell array of texts.', fn)


@bi('parquetread', aw=True, arr=False)
async def parquetread(nargout, *args):
    """T = parquetread(filename, 'SelectedVariableNames', names, 'OutputType',
    'table' or 'timetable', 'RowTimes', name, 'VariableNamingRule', rule):
    a Parquet file as a table."""
    nargchk(args, 1, 9, 'parquetread')
    pos, opts = _opts(args, ('selectedvariablenames', 'outputtype', 'rowtimes', 'variablenamingrule'), 'parquetread')
    if len(pos) != 1:
        raise err('MATLAB:parquetread:InvalidInput', 'Give the file name, then Name, Value pairs.', 'parquetread')
    from .iofun import _existing
    p = _existing(pos[0], 'parquetread')
    await need_pyarrow('parquetread')
    sel = None
    if 'selectedvariablenames' in opts:
        sel = _texts(opts['selectedvariablenames'], 'parquetread', 'SelectedVariableNames')
        have = parquet_names(p)
        bad = [s for s in sel if s not in have]
        if bad:
            raise err('MATLAB:parquetread:UnknownVariable', f"'{bad[0]}' is not a variable of the file.", 'parquetread')
    rule = (opt_str(opts['variablenamingrule']) or 'modify').lower() if 'variablenamingrule' in opts else 'modify'
    T = read_parquet(p, sel, rule)
    otype = (opt_str(opts['outputtype']) or 'table').lower() if 'outputtype' in opts else 'table'
    if otype not in ('table', 'timetable'):
        raise err('MATLAB:parquetread:InvalidOutputType', "OutputType is 'table' or 'timetable'.", 'parquetread')
    if otype == 'timetable' or 'rowtimes' in opts:
        extra = []
        if 'rowtimes' in opts:
            extra = [Char.of('RowTimes'), Char.of(sval(opts['rowtimes'], 'RowTimes', 'parquetread'))]
        return REG['table2timetable'].fn(1, T, *extra)
    return T


def _arrow_column(v, n, name):
    """An Arrow array from a table variable."""
    pa, _ = _pa()
    from .timetypes import DateTime, Duration
    from .categoricals import Categorical
    if isinstance(v, Categorical):
        codes = v.a.reshape(-1).astype(int)
        idx = pa.array(np.where(codes == 0, 0, codes - 1).astype(np.int32), mask=codes == 0)
        return pa.DictionaryArray.from_arrays(idx, pa.array(v.cats, pa.string()), ordered=v.ordinal)
    if isinstance(v, DateTime):
        a = np.asarray(v.a, float).reshape(-1)
        mask = np.isnan(a)
        us = np.where(mask, 0, np.round(a * 1e6)).astype(np.int64)
        return pa.array(us, pa.timestamp('us', tz=v.tz or None), mask=mask)
    if isinstance(v, Duration):
        a = np.asarray(v.a, float).reshape(-1)
        mask = np.isnan(a)
        us = np.where(mask, 0, np.round(a * 1e6)).astype(np.int64)
        return pa.array(us, pa.duration('us'), mask=mask)
    if type(v) is Str:
        if v.a.shape[1] != 1:
            raise err('MATLAB:parquetwrite:MultiColumn', f"The variable '{name}' has more than one column: Parquet columns hold one value a row.", 'parquetwrite')
        return pa.array(list(v.a.reshape(-1)), pa.string())
    if type(v) is Cell:
        items = list(v.a.reshape(-1))
        if all(type(x) is Char and x.a.shape[0] <= 1 for x in items):
            return pa.array([x.str() for x in items], pa.string())
        if all(type(x) is Str for x in items):
            return pa.array([list(x.a.reshape(-1)) for x in items], pa.list_(pa.string()))
        try:
            return pa.array([[float(z) for z in np.asarray(darr(x), float).reshape(-1)] for x in items], pa.list_(pa.float64()))
        except Exception:
            raise err('MATLAB:parquetwrite:UnsupportedType', f"The cells of '{name}' are not text or numbers.", 'parquetwrite')
    if type(v) is Char:
        return pa.array(v.row_strs(), pa.string())
    a = np.asarray(v)
    if a.ndim == 2 and a.shape[1] != 1:
        raise err('MATLAB:parquetwrite:MultiColumn', f"The variable '{name}' has more than one column: Parquet columns hold one value a row.", 'parquetwrite')
    a = a.reshape(-1)
    if a.dtype.kind == 'c':
        raise err('MATLAB:parquetwrite:UnsupportedType', f"The variable '{name}' is complex, which Parquet does not hold.", 'parquetwrite')
    if a.dtype.kind == 'f':
        mask = np.isnan(a)
        return pa.array(a, mask=mask if mask.any() else None)
    if a.dtype.kind in 'biu':
        return pa.array(a)
    raise err('MATLAB:parquetwrite:UnsupportedType', f"The variable '{name}' of class {class_of(v)} is not written to Parquet files.", 'parquetwrite')


@bi('parquetwrite', aw=True, arr=False)
async def parquetwrite(nargout, *args):
    """parquetwrite(filename, T, 'VariableCompression', c, 'RowGroupHeights',
    h, 'Version', v): a table or timetable as a Parquet file."""
    nargchk(args, 2, 10, 'parquetwrite')
    from .tables import Table, TimeTable
    name = sval(args[0], 'file name', 'parquetwrite')
    T = args[1]
    if not isinstance(T, Table):
        raise err('MATLAB:parquetwrite:NotTable', 'parquetwrite writes a table or a timetable.', 'parquetwrite')
    pos, opts = _opts(args[2:], ('variablecompression', 'rowgroupheights', 'version', 'variableencoding'), 'parquetwrite')
    await need_pyarrow('parquetwrite')
    pa, pq = _pa()
    cols, names = [], []
    if isinstance(T, TimeTable):
        cols.append(_arrow_column(T.times, T.n, T.dims[0]))
        names.append(T.dims[0])
    for nm, v in zip(T.names, T.vars):
        cols.append(_arrow_column(v, T.n, nm))
        names.append(nm)
    tab = pa.Table.from_arrays(cols, names=names)
    comp = 'snappy'
    if 'variablecompression' in opts:
        c = (opt_str(opts['variablecompression']) or '').lower()
        comp = {'uncompressed': 'none', 'none': 'none'}.get(c, c)
        if comp not in ('none', 'snappy', 'gzip', 'brotli', 'lz4', 'zstd'):
            raise err('MATLAB:parquetwrite:InvalidCompression', "VariableCompression is 'snappy', 'gzip', 'brotli', 'lz4', 'zstd' or 'uncompressed'.", 'parquetwrite')
    rg = None
    if 'rowgroupheights' in opts:
        h = np.asarray(darr(opts['rowgroupheights']), float).reshape(-1)
        rg = int(h[0]) if h.size else None
    ver = sval(opts['version'], 'Version', 'parquetwrite') if 'version' in opts else '2.6'
    from .iofun import abspath, files_changed
    p = abspath(name)
    if not os.path.splitext(p)[1]:
        p += '.parquet'
    try:
        pq.write_table(tab, p, compression=comp, row_group_size=rg, version=ver if ver in ('1.0', '2.4', '2.6') else '2.6')
    except (OSError, pa.ArrowException) as e:
        raise err('MATLAB:parquetwrite:WriteError', f'Unable to write {name}: {e}', 'parquetwrite')
    files_changed(os.path.dirname(p))
    return None


@bi('parquetinfo', aw=True, arr=False)
async def parquetinfo(nargout, *args):
    """info = parquetinfo(filename): the file's size, row groups, variables and their types and compression."""
    nargchk(args, 1, 1, 'parquetinfo')
    from .iofun import _existing
    p = _existing(args[0], 'parquetinfo')
    await need_pyarrow('parquetinfo')
    pa, pq = _pa()
    try:
        f = pq.ParquetFile(p)
    except (OSError, pa.ArrowException) as e:
        raise err('MATLAB:parquetinfo:FileReadError', f'{os.path.basename(p)} is not a Parquet file that can be read: {e}', 'parquetinfo')
    md = f.metadata
    schema = f.schema_arrow
    names = list(schema.names)
    heights = [float(md.row_group(i).num_rows) for i in range(md.num_row_groups)]
    comps, encs = [], []
    for j in range(md.num_columns):
        if md.num_row_groups:
            c = md.row_group(0).column(j)
            comps.append(str(c.compression).lower())
            encs.append(', '.join(str(e) for e in c.encodings))
        else:
            comps.append('')
            encs.append('')
    from .tables import Table
    fake = Table([], [], None, 0)
    types = []
    for fld in schema:
        try:
            col = _column(pa.chunked_array([pa.array([], fld.type)]))
            types.append(class_of(col))
        except MError:
            types.append(str(fld.type))
    del fake
    row = lambda xs: Cell.of_list([Char.of(x) for x in xs], (1, len(xs)))
    return Struct.scalar({'Filename': Char.of(p), 'FileSize': float(os.path.getsize(p)), 'NumRowGroups': float(md.num_row_groups),
                          'RowGroupHeights': out(np.array([heights], float)) if heights else out(np.zeros((1, 0))),
                          'VariableNames': row(names), 'VariableTypes': row(types), 'VariableCompression': row(comps),
                          'VariableEncoding': row(encs), 'Version': Char.of(str(md.format_version))})


# ---- FITS ------------------------------------------------------------------------------------------------------------------

_BLOCK = 2880


class _HDU:
    """One header-and-data unit: its cards in order, and where its data is."""

    def __init__(self, cards, start, size):
        self.cards = cards           # (keyword, value, comment)
        self.start = start
        self.size = size
        self.kw = {}
        for k, v, c in cards:
            if k and k not in ('COMMENT', 'HISTORY', '') and k not in self.kw:
                self.kw[k] = v

    def get(self, k, d=None):
        return self.kw.get(k, d)

    @property
    def kind(self):
        x = self.get('XTENSION')
        if x is None:
            return 'Primary'
        x = str(x).strip().upper()
        return {'IMAGE': 'Image', 'BINTABLE': 'Binary Table', 'TABLE': 'ASCII Table', 'A3DTABLE': 'Binary Table'}.get(x, 'Unknown')


def _card_value(s):
    """A card's value (bool, int, float, str or complex) and comment, from columns 11-80."""
    s = s.rstrip()
    t = s.lstrip()
    if not t:
        return None, ''
    if t.startswith("'"):
        # a string: '' is a quote inside it
        i = 1
        buf = []
        while i < len(t):
            if t[i] == "'":
                if i + 1 < len(t) and t[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                break
            buf.append(t[i])
            i += 1
        rest = t[i + 1:]
        com = rest.split('/', 1)[1].strip() if '/' in rest else ''
        return ''.join(buf).rstrip(), com
    val, _, com = t.partition('/')
    val = val.strip()
    com = com.strip()
    if val in ('T', 'F'):
        return val == 'T', com
    if val.startswith('(') and val.endswith(')'):
        re_, im = val[1:-1].split(',')
        return complex(float(re_.replace('D', 'E')), float(im.replace('D', 'E'))), com
    try:
        return int(val), com
    except ValueError:
        pass
    try:
        return float(val.replace('D', 'E').replace('d', 'e')), com
    except ValueError:
        return val, com


def _read_hdus(p, fn):
    """The file's units, each with its header read."""
    size = os.path.getsize(p)
    hdus = []
    with open(p, 'rb') as f:
        pos = 0
        while pos < size:
            cards = []
            done = False
            hstart = pos
            while not done:
                f.seek(pos)
                block = f.read(_BLOCK)
                if len(block) < _BLOCK:
                    if not hdus:
                        raise err(f'MATLAB:{fn}:NotFITS', f'{os.path.basename(p)} is not a FITS file (its header has no END).', fn)
                    return hdus
                pos += _BLOCK
                for i in range(36):
                    card = block[i * 80:(i + 1) * 80].decode('ascii', 'replace')
                    key = card[:8].strip()
                    if key == 'END':
                        done = True
                        break
                    if card[8:10] == '= ' and key not in ('COMMENT', 'HISTORY'):
                        v, c = _card_value(card[10:])
                        cards.append((key, v, c))
                    else:
                        cards.append((key, None, card[8:].rstrip()))
            if hstart == 0 and (not cards or cards[0][0] != 'SIMPLE'):
                raise err(f'MATLAB:{fn}:NotFITS', f'{os.path.basename(p)} is not a FITS file (it does not start with SIMPLE).', fn)
            h = _HDU(cards, pos, 0)
            naxis = int(h.get('NAXIS', 0) or 0)
            bits = abs(int(h.get('BITPIX', 8) or 8))
            n = 0
            if naxis:
                n = 1
                for k in range(1, naxis + 1):
                    n *= int(h.get(f'NAXIS{k}', 0) or 0)
            n = (int(h.get('PCOUNT', 0) or 0) + n) * int(h.get('GCOUNT', 1) or 1) if (naxis and h.get('XTENSION') is not None) else n
            h.size = n * bits // 8
            hdus.append(h)
            pos += ((h.size + _BLOCK - 1) // _BLOCK) * _BLOCK
    return hdus


_BITPIX = {8: '>u1', 16: '>i2', 32: '>i4', 64: '>i8', -32: '>f4', -64: '>f8'}


def _image(p, h, raw):
    naxis = int(h.get('NAXIS', 0) or 0)
    if naxis == 0:
        return out(np.zeros((0, 0)))
    dims = [int(h.get(f'NAXIS{k}')) for k in range(1, naxis + 1)]
    bitpix = int(h.get('BITPIX'))
    with open(p, 'rb') as f:
        f.seek(h.start)
        buf = f.read(h.size)
    a = np.frombuffer(buf, _BITPIX[bitpix], count=int(np.prod(dims))).reshape(dims[::-1])
    # NAXIS1 runs fastest: in the language's order the first axis is NAXIS2 (rows), then NAXIS1, then the rest
    a = np.transpose(a, list(range(a.ndim))[::-1]) if a.ndim > 2 else a
    if a.ndim > 2:
        a = np.swapaxes(a, 0, 1)
    a = a.astype(a.dtype.newbyteorder('='))
    if raw:
        return out(np.ascontiguousarray(a))
    blank = h.get('BLANK')
    scale, zero = float(h.get('BSCALE', 1.0) or 1.0), float(h.get('BZERO', 0.0) or 0.0)
    r = a.astype(float)
    if blank is not None and bitpix > 0:
        r[a == int(blank)] = np.nan
    r = r * scale + zero
    return out(r)


_TFORM = {'L': ('?', 1), 'X': ('u1', 1), 'B': ('u1', 1), 'I': ('>i2', 2), 'J': ('>i4', 4), 'K': ('>i8', 8), 'A': ('S1', 1),
          'E': ('>f4', 4), 'D': ('>f8', 8), 'C': ('>c8', 8), 'M': ('>c16', 16), 'P': ('>i4', 8), 'Q': ('>i8', 16)}


def _tform(s):
    """repeat, code and the rest of a binary table's TFORM."""
    s = str(s).strip()
    i = 0
    while i < len(s) and s[i].isdigit():
        i += 1
    rep = int(s[:i]) if i else 1
    return rep, s[i], s[i + 1:]


def _bintable(p, h, raw, cols=None, rows=None):
    nrows = int(h.get('NAXIS2', 0) or 0)
    width = int(h.get('NAXIS1', 0) or 0)
    nf = int(h.get('TFIELDS', 0) or 0)
    with open(p, 'rb') as f:
        f.seek(h.start)
        buf = f.read(h.size)
    table = np.frombuffer(buf, np.uint8, count=nrows * width).reshape(nrows, width) if nrows else np.zeros((0, width), np.uint8)
    heap_start = int(h.get('THEAP', nrows * width) or nrows * width)
    heap = buf[heap_start:]
    which = range(nf) if cols is None else cols
    rsel = np.arange(nrows) if rows is None else rows
    res = []
    off = 0
    offsets = []
    for k in range(nf):
        rep, code, rest = _tform(h.get(f'TFORM{k + 1}'))
        size = _TFORM[code][1]
        offsets.append((off, rep, code, rest))
        off += (rep + 7) // 8 if code == 'X' else rep * size
    for k in which:
        o, rep, code, rest = offsets[k]
        dt, size = _TFORM[code]
        if code == 'X':
            nb = (rep + 7) // 8
            bits = np.unpackbits(table[rsel, o:o + nb], axis=1)[:, :rep]
            res.append(out(bits.astype(bool)))
            continue
        chunk = np.ascontiguousarray(table[rsel, o:o + rep * size])
        if code == 'A':
            texts = [bytes(r).split(b'\x00', 1)[0].decode('ascii', 'replace').rstrip() for r in chunk]
            res.append(Cell.of_list([Char.of(t) for t in texts], (len(texts), 1)))
            continue
        if code in 'PQ':
            desc = chunk.view('>i4' if code == 'P' else '>i8').reshape(len(rsel), 2)
            ecode = rest[:1]
            edt, esize = _TFORM[ecode]
            items = []
            for cnt, start in desc:
                seg = heap[int(start):int(start) + int(cnt) * esize]
                if ecode == 'A':
                    items.append(Char.of(seg.split(b'\x00', 1)[0].decode('ascii', 'replace')))
                else:
                    v = np.frombuffer(seg, edt).astype(np.dtype(edt).newbyteorder('=')) if edt != '?' else np.frombuffer(seg, 'S1') == b'T'
                    items.append(out(np.asarray(v).reshape(1, -1)))
            res.append(Cell.of_list(items, (len(items), 1)))
            continue
        if code == 'L':
            a = (chunk.view('S1') == b'T').reshape(len(rsel), rep)
            res.append(out(a))
            continue
        a = chunk.view(dt).reshape(len(rsel), rep)
        a = a.astype(a.dtype.newbyteorder('='))
        scale, zero = h.get(f'TSCAL{k + 1}'), h.get(f'TZERO{k + 1}')
        tnull = h.get(f'TNULL{k + 1}')
        if not raw and code not in 'CM':
            if scale is not None or zero is not None or (tnull is not None and code in 'BIJK'):
                r = a.astype(float)
                if tnull is not None and code in 'BIJK':
                    r[a == int(tnull)] = np.nan
                a = r * float(scale if scale is not None else 1.0) + float(zero if zero is not None else 0.0)
        res.append(out(a))
    return res


def _asciitable(p, h, cols=None, rows=None):
    nrows = int(h.get('NAXIS2', 0) or 0)
    width = int(h.get('NAXIS1', 0) or 0)
    nf = int(h.get('TFIELDS', 0) or 0)
    with open(p, 'rb') as f:
        f.seek(h.start)
        buf = f.read(nrows * width)
    lines = [buf[i * width:(i + 1) * width].decode('ascii', 'replace') for i in range(nrows)]
    if rows is not None:
        lines = [lines[i] for i in rows]
    res = []
    for k in (range(nf) if cols is None else cols):
        start = int(h.get(f'TBCOL{k + 1}')) - 1
        form = str(h.get(f'TFORM{k + 1}')).strip()
        code = form[0].upper()
        w = int(form[1:].split('.')[0])
        cells = [ln[start:start + w] for ln in lines]
        if code == 'A':
            res.append(Cell.of_list([Char.of(c.rstrip()) for c in cells], (len(cells), 1)))
            continue
        nullv = h.get(f'TNULL{k + 1}')
        vals = []
        for c in cells:
            t = c.strip()
            if not t or (nullv is not None and t == str(nullv).strip()):
                vals.append(np.nan)
                continue
            vals.append(float(t.replace('D', 'E')))
        a = np.array(vals, float).reshape(-1, 1)
        scale, zero = h.get(f'TSCAL{k + 1}'), h.get(f'TZERO{k + 1}')
        if scale is not None or zero is not None:
            a = a * float(scale if scale is not None else 1.0) + float(zero if zero is not None else 0.0)
        res.append(out(a))
    return res


def _pick(hdus, kind, index, fn):
    names = {'primary': 'Primary', 'image': 'Image', 'binarytable': 'Binary Table', 'bintable': 'Binary Table', 'asciitable': 'ASCII Table',
             'table': 'ASCII Table', 'unknown': 'Unknown'}
    if kind not in names:
        raise err(f'MATLAB:{fn}:InvalidExtension', "The part is 'primary', 'image', 'binarytable', 'asciitable' or 'unknown'.", fn)
    hits = [h for h in hdus if h.kind == names[kind]]
    if not hits or index > len(hits) or index < 1:
        raise err(f'MATLAB:{fn}:NoSuchExtension', f"The file has {len(hits)} part{'s' if len(hits) != 1 else ''} of the kind '{kind}'.", fn)
    return hits[index - 1]


def _index_list(v, n, fn, what):
    a = np.asarray(darr(v), float).reshape(-1)
    if np.any(a < 1) or np.any(a > n) or np.any(a != np.round(a)):
        raise err(f'MATLAB:{fn}:InvalidIndex', f'{what} are whole numbers from 1 to {n}.', fn)
    return [int(x) - 1 for x in a]


@bi('fitsread', arr=False)
def fitsread(nargout, *args):
    """data = fitsread(filename), fitsread(filename, part, index, 'raw',
    'TableColumns', c, 'TableRows', r, 'PixelRegion', {rows, cols}): a FITS
    file's data, scaled to double unless 'raw'; a table as a cell array of
    its columns."""
    nargchk(args, 1, 10, 'fitsread')
    from .iofun import _existing
    p = _existing(args[0], 'fitsread')
    rest = list(args[1:])
    raw = False
    kind, index = 'primary', 1
    opts = {}
    k = 0
    while k < len(rest):
        o = (opt_str(rest[k]) or '').lower()
        if o == 'raw':
            raw = True
            k += 1
        elif o in ('tablecolumns', 'tablerows', 'pixelregion') and k + 1 < len(rest):
            opts[o] = rest[k + 1]
            k += 2
        elif o and k == 0:
            kind = o
            k += 1
            if k < len(rest) and not is_str(rest[k]):
                index = int(num(rest[k]))
                k += 1
        else:
            raise err('MATLAB:fitsread:InvalidInput', "Give the part ('primary', 'image', 'binarytable', 'asciitable'), its index, 'raw' and the options.", 'fitsread')
    hdus = _read_hdus(p, 'fitsread')
    h = _pick(hdus, kind, index, 'fitsread')
    if h.kind in ('Primary', 'Image'):
        a = _image(p, h, raw)
        if 'pixelregion' in opts:
            from ..index import idx as take
            pr = opts['pixelregion']
            regs = list(pr.a.reshape(-1, order='F')) if type(pr) is Cell else [pr]
            a = take(a, tuple(regs) + ((Char.of(':'),) * (len(shape_of(a)) - len(regs)) if len(regs) < len(shape_of(a)) else ()))
        return a
    if h.kind == 'Unknown':
        with open(p, 'rb') as f:
            f.seek(h.start)
            return out(np.frombuffer(f.read(h.size), np.uint8).reshape(-1, 1).copy())
    nf = int(h.get('TFIELDS', 0) or 0)
    nr = int(h.get('NAXIS2', 0) or 0)
    cols = _index_list(opts['tablecolumns'], nf, 'fitsread', 'TableColumns') if 'tablecolumns' in opts else None
    rows = _index_list(opts['tablerows'], nr, 'fitsread', 'TableRows') if 'tablerows' in opts else None
    res = _bintable(p, h, raw, cols, rows) if h.kind == 'Binary Table' else _asciitable(p, h, cols, rows)
    return Cell.of_list(res, (1, len(res)))


def _keywords(h):
    rows = []
    for k, v, c in h.cards:
        if v is None:
            val = EMPTY()
        elif isinstance(v, bool):
            val = Char.of('T' if v else 'F')
        elif isinstance(v, (int, float)):
            val = float(v)
        elif isinstance(v, complex):
            val = complex(v)
        else:
            val = Char.of(str(v))
        rows.append([Char.of(k), val, Char.of(c)])
    rows.append([Char.of('END'), EMPTY(), Char.of('')])
    c = Cell(np.empty((len(rows), 3), object))
    for i, r in enumerate(rows):
        for j in range(3):
            c.a[i, j] = r[j]
    return c


_DTYPE_NAME = {8: 'uint8', 16: 'int16', 32: 'int32', 64: 'int64', -32: 'single', -64: 'double'}


@bi('fitsinfo', arr=False)
def fitsinfo(nargout, *args):
    """info = fitsinfo(filename): the file's parts (Contents) and, for each,
    its kind of data, size, scaling and header keywords."""
    nargchk(args, 1, 1, 'fitsinfo')
    from .iofun import _existing
    p = _existing(args[0], 'fitsinfo')
    hdus = _read_hdus(p, 'fitsinfo')
    st = os.stat(p)
    info = {'Filename': Char.of(p), 'FileModDate': Char.of(time.strftime('%d-%b-%Y %H:%M:%S', time.localtime(st.st_mtime))),
            'FileSize': float(st.st_size), 'Contents': Cell.of_list([Char.of(h.kind) for h in hdus], (1, len(hdus)))}
    groups = {}
    for h in hdus:
        naxis = int(h.get('NAXIS', 0) or 0)
        dims = [int(h.get(f'NAXIS{k}', 0) or 0) for k in range(1, naxis + 1)]
        bitpix = int(h.get('BITPIX', 8) or 8)
        d = {'DataType': Char.of(_DTYPE_NAME.get(bitpix, 'uint8')), 'Size': out(np.array([[dims[1], dims[0]] + dims[2:]], float)) if len(dims) >= 2 else out(np.array([dims], float)),
             'DataSize': float(h.size), 'Offset': float(h.start)}
        if h.kind in ('Primary', 'Image'):
            d.update({'MissingDataValue': float(h.get('BLANK')) if h.get('BLANK') is not None else EMPTY(),
                      'Intercept': float(h.get('BZERO', 0.0) or 0.0), 'Slope': float(h.get('BSCALE', 1.0) or 1.0)})
        else:
            nf = int(h.get('TFIELDS', 0) or 0)
            d = {'Rows': float(dims[1]) if len(dims) > 1 else 0.0, 'RowSize': float(dims[0]) if dims else 0.0, 'NFields': float(nf),
                 'FieldFormat': Cell.of_list([Char.of(str(h.get(f'TFORM{k}', '')).strip()) for k in range(1, nf + 1)], (1, nf)),
                 'FieldPrecision': Cell.of_list([Char.of(_precision(h, k)) for k in range(1, nf + 1)], (1, nf)),
                 'FieldSize': out(np.array([[_field_size(h, k) for k in range(1, nf + 1)]], float)) if nf else out(np.zeros((1, 0))),
                 'DataSize': float(h.size),
                 'MissingDataValue': Cell.of_list([float(h.get(f'TNULL{k}')) if isinstance(h.get(f'TNULL{k}'), (int, float)) else EMPTY() for k in range(1, nf + 1)], (1, nf)),
                 'Intercept': out(np.array([[float(h.get(f'TZERO{k}', 0.0) or 0.0) for k in range(1, nf + 1)]])) if nf else out(np.zeros((1, 0))),
                 'Slope': out(np.array([[float(h.get(f'TSCAL{k}', 1.0) or 1.0) for k in range(1, nf + 1)]])) if nf else out(np.zeros((1, 0))),
                 'Offset': float(h.start),
                 'ExtensionSize': float(h.size - (dims[0] * dims[1] if len(dims) > 1 else 0))}
        d['Keywords'] = _keywords(h)
        key = {'Primary': 'PrimaryData', 'Image': 'Image', 'Binary Table': 'BinaryTable', 'ASCII Table': 'AsciiTable', 'Unknown': 'Unknown'}[h.kind]
        groups.setdefault(key, []).append(d)
    for key, items in groups.items():
        if key == 'PrimaryData':
            info[key] = Struct.scalar(items[0])
            continue
        S = Struct.empty((1, len(items)), tuple(items[0].keys()))
        for i, d in enumerate(items):
            for k2, v in d.items():
                S.f[k2][0, i] = v
        info[key] = S
    return Struct.scalar(info)


def _precision(h, k):
    form = str(h.get(f'TFORM{k}', '')).strip()
    if h.kind == 'ASCII Table':
        return {'A': 'Char', 'I': 'Integer', 'F': 'Single', 'E': 'Single', 'D': 'Double'}.get(form[:1].upper(), 'Char')
    rep, code, rest = _tform(form)
    return {'L': 'logical', 'X': 'bit', 'B': 'uint8', 'I': 'int16', 'J': 'int32', 'K': 'int64', 'A': 'char', 'E': 'single', 'D': 'double',
            'C': 'single complex', 'M': 'double complex', 'P': 'variable length', 'Q': 'variable length'}.get(code, '')


def _field_size(h, k):
    form = str(h.get(f'TFORM{k}', '')).strip()
    if h.kind == 'ASCII Table':
        return float(int(form[1:].split('.')[0]))
    return float(_tform(form)[0])


@bi('fitsdisp')
def fitsdisp(nargout, *args):
    """fitsdisp(filename), fitsdisp(filename, 'Index', k, 'Mode', 'standard',
    'min' or 'full'): the headers of the file's parts."""
    nargchk(args, 1, 5, 'fitsdisp')
    from .iofun import _existing
    p = _existing(args[0], 'fitsdisp')
    pos, opts = _opts(args[1:], ('index', 'mode'), 'fitsdisp')
    hdus = _read_hdus(p, 'fitsdisp')
    which = _index_list(opts['index'], len(hdus), 'fitsdisp', 'The indices') if 'index' in opts else range(len(hdus))
    mode = (opt_str(opts['mode']) or 'standard').lower() if 'mode' in opts else 'standard'
    lines = []
    for i in which:
        h = hdus[i]
        lines.append(f'HDU: {i + 1}' + ('' if h.kind == 'Primary' else f' ({h.kind})'))
        cards = h.cards
        if mode == 'min':
            cards = [c for c in cards if c[0] in ('SIMPLE', 'XTENSION', 'BITPIX', 'NAXIS') or c[0].startswith('NAXIS')]
        for k, v, c in cards:
            if v is None:
                lines.append(f'    {k:<8}{c}')
                continue
            if isinstance(v, bool):
                s = 'T' if v else 'F'
            elif isinstance(v, str):
                s = "'" + v.replace("'", "''") + "'"
            else:
                s = repr(v) if isinstance(v, float) else str(v)
            lines.append(f'    {k:<8}= {s}' + (f' / {c}' if c and mode == 'full' or (c and mode == 'standard') else ''))
        lines.append('')
    R.write('\n'.join(lines) + '\n')
    return None


def _card(key, value=None, comment=''):
    if value is None:
        text = f'{key:<8}{comment}'
    else:
        if isinstance(value, bool):
            v = f'{"T" if value else "F":>20}'
        elif isinstance(value, str):
            v = ("'" + value.replace("'", "''").ljust(8) + "'").ljust(20)
        elif isinstance(value, int):
            v = f'{value:>20}'
        else:
            v = f'{repr(float(value)).upper():>20}'
        text = f'{key:<8}= {v}' + (f' / {comment}' if comment else '')
    return text[:80].ljust(80)


@bi('fitswrite')
def fitswrite(nargout, *args):
    """fitswrite(imagedata, filename, 'WriteMode', 'overwrite' or 'append'):
    an array as a FITS image, the primary data or (appended) an image
    extension; its class kept (int8, uint16, uint32 and uint64 through BZERO,
    logical as uint8)."""
    nargchk(args, 2, 6, 'fitswrite')
    if type(args[0]) is Char:
        raise err('MATLAB:fitswrite:InvalidClass', 'A FITS image holds numbers.', 'fitswrite')
    a = np.asarray(arr(args[0], 'fitswrite'))
    name = sval(args[1], 'file name', 'fitswrite')
    pos, opts = _opts(args[2:], ('writemode', 'compression'), 'fitswrite')
    mode = (opt_str(opts['writemode']) or 'overwrite').lower() if 'writemode' in opts else 'overwrite'
    if mode not in ('overwrite', 'append'):
        raise err('MATLAB:fitswrite:InvalidWriteMode', "WriteMode is 'overwrite' or 'append'.", 'fitswrite')
    if 'compression' in opts and (opt_str(opts['compression']) or 'none').lower() != 'none':
        raise err('MATLAB:fitswrite:Compression', 'Compressed FITS images are not written here.', 'fitswrite')
    if a.dtype.kind == 'c':
        raise err('MATLAB:fitswrite:Complex', 'FITS images hold real numbers.', 'fitswrite')
    zero = None
    if a.dtype == bool:
        a = a.astype(np.uint8)
    kinds = {np.dtype(np.uint8): (8, None), np.dtype(np.int16): (16, None), np.dtype(np.int32): (32, None), np.dtype(np.int64): (64, None),
             np.dtype(np.float32): (-32, None), np.dtype(np.float64): (-64, None),
             np.dtype(np.int8): (8, -128), np.dtype(np.uint16): (16, 32768), np.dtype(np.uint32): (32, 2147483648), np.dtype(np.uint64): (64, 9223372036854775808)}
    if a.dtype not in kinds:
        raise err('MATLAB:fitswrite:InvalidClass', f'A {class_of(args[0])} array is not written as a FITS image.', 'fitswrite')
    bitpix, zero = kinds[a.dtype]
    if zero is None:
        stored = a
    elif a.dtype == np.int8:
        stored = (a.astype(np.int16) + 128).astype(np.uint8)
    else:
        # unsigned values stored signed, less 2^(bits-1): the top bit flipped
        bits = 8 * a.dtype.itemsize
        stored = (a ^ a.dtype.type(1 << (bits - 1))).view(np.dtype(f'int{bits}'))
    # NAXIS1 runs fastest and is the language's second dimension (along a row), NAXIS2 its first
    perm = list(range(stored.ndim - 1, 1, -1)) + [0, 1]
    body = np.ascontiguousarray(np.transpose(stored, perm)).astype(_BITPIX[bitpix]).tobytes() if stored.size else b''
    dims = [a.shape[1], a.shape[0]] + list(a.shape[2:]) if a.size else []
    from .iofun import abspath, files_changed
    p = abspath(name)
    append = mode == 'append' and os.path.isfile(p)
    cards = [_card('XTENSION', 'IMAGE', 'Image extension') if append else _card('SIMPLE', True, 'file conforms to the FITS standard'),
             _card('BITPIX', bitpix, 'bits per value'), _card('NAXIS', len(dims), 'number of axes')]
    cards += [_card(f'NAXIS{k + 1}', int(d)) for k, d in enumerate(dims)]
    if append:
        cards += [_card('PCOUNT', 0), _card('GCOUNT', 1)]
    else:
        cards.append(_card('EXTEND', True, 'there may be extensions'))
    if zero is not None:
        cards += [_card('BSCALE', 1.0), _card('BZERO', zero)]
    cards.append(_card('END'))
    head = ''.join(cards).encode('ascii')
    head += b' ' * ((-len(head)) % _BLOCK)
    body += b'\x00' * ((-len(body)) % _BLOCK)
    if append:
        hdus = _read_hdus(p, 'fitswrite')
        if not hdus[0].get('EXTEND', False):
            # an extension follows only a primary header that says there may be one
            with open(p, 'r+b') as f:
                f.seek(0)
                block = bytearray(f.read(hdus[0].start))
                txt = block.decode('ascii', 'replace')
                endpos = next(i for i in range(0, len(txt), 80) if txt[i:i + 8].strip() == 'END')
                if endpos + 80 >= hdus[0].start:
                    raise err('MATLAB:fitswrite:AppendError', 'The primary header has no room for EXTEND.', 'fitswrite')
                block[endpos:endpos + 160] = (_card('EXTEND', True) + _card('END')).encode('ascii')
                f.seek(0)
                f.write(bytes(block))
    try:
        with open(p, 'ab' if append else 'wb') as f:
            f.write(head + body)
    except OSError as e:
        raise err('MATLAB:fitswrite:WriteError', f'Unable to write {name}: {e.strerror or e}.', 'fitswrite')
    files_changed(os.path.dirname(p))
    return None
