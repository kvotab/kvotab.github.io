"""The language's object classes as MAT-files keep them: each object's saved
properties, to and from the values here.

    from_props(classname, props) -> a value      (reading; props by name)
    to_props(value) -> (classname, props, saveobj) (writing)
    CLASSES                                        the classes known

The properties are those the open-source mat-io reader documents
(github.com/foreverallama/matio, BSD-3-Clause, (c) 2025 foreverallama):

    datetime          data (milliseconds since 1970 as a double-double: the
                      real part, and in the imaginary part the real part's
                      rounding error), tz, fmt
    duration          millis, fmt
    calendarDuration  components (a struct of months, days and millis, each
                      an array or one value for all), fmt
    categorical       categoryNames (a column cell), codes (from 1, 0 for
                      undefined, the smallest unsigned class that holds
                      them), isOrdinal, isProtected
    table             data (a cell, a variable each), varnames, nrows,
                      nvars, ndims, rownames, props (a struct of the
                      table's other properties)
    timetable         any: the struct its saveobj gives (data, varNames,
                      numRows, rowTimes, dimNames, arrayProps, ...)
    string            any (see matfile.py)

A value here that holds another object (a table's datetime variable) holds
it as that object; matfile.py and matwrite.py resolve and make the
references between them."""
import math

import numpy as np

from .values import Char, Cell, Struct, Str, MError

CLASSES = ('datetime', 'duration', 'calendarDuration', 'categorical', 'table', 'timetable', 'string')
TABLE_SAVE_VERSION = 4.0
TIMETABLE_SAVE_VERSION = 6.0


class Unreadable(Exception):
    pass


def _text(v, default=''):
    if isinstance(v, Char):
        return v.str() if v.a.shape[0] <= 1 else ''.join(v.row_strs())
    if isinstance(v, Str) and v.a.size == 1:
        return v.a.flat[0] or default
    return default


def _texts(v):
    """The texts of a cell of character vectors (or strings), a string array or one character vector."""
    if v is None or (isinstance(v, np.ndarray) and v.size == 0):
        return []
    if isinstance(v, Str):
        return ['' if s is None else s for s in v.a.reshape(-1, order='F')]
    if isinstance(v, Char):
        return [_text(v)]
    if isinstance(v, Cell):
        out = []
        for x in v.a.reshape(-1, order='F'):
            if isinstance(x, (Char, Str)):
                out.append(_text(x))
            elif isinstance(x, np.ndarray) and x.size == 0:
                out.append('')
            else:
                raise Unreadable('its names are damaged')
        return out
    raise Unreadable('its names are damaged')


def _num(v, default=0.0):
    a = np.asarray(v, float).reshape(-1) if not isinstance(v, (Char, Cell, Struct, Str)) and v is not None else np.zeros(0)
    return float(a[0]) if a.size else default


def _bool(v):
    return bool(_num(v, 0.0))


def _arr(v):
    if isinstance(v, (float, int, bool, complex)):
        return np.array([[v]])
    if isinstance(v, np.ndarray):
        return v
    raise Unreadable('its data is not an array')


def _field(s, k, default=None):
    if isinstance(s, Struct) and s.size >= 1 and k in s.f:
        return s.f[k].reshape(-1)[0]
    return default


# ---- reading ---------------------------------------------------------------------------------------------

def from_props(cname, props):
    from .builtins.timetypes import DateTime, Duration, CalDuration, FULL
    if cname == 'datetime':
        data = props.get('data')
        if data is None:
            raise Unreadable('the datetime has no data')
        a = _arr(data)
        ms = a.real.astype(float) + (a.imag.astype(float) if np.iscomplexobj(a) else 0.0)
        fmt = _text(props.get('fmt')) or FULL
        tz = _text(props.get('tz', props.get('tmz')))
        return DateTime(ms / 1000.0, fmt, tz)
    if cname == 'duration':
        millis = props.get('millis')
        if millis is None:
            raise Unreadable('the duration has no data')
        return Duration(_arr(millis).astype(float) / 1000.0, _text(props.get('fmt')) or 'hh:mm:ss')
    if cname == 'calendarDuration':
        comps = props.get('components')
        if not isinstance(comps, Struct):
            raise Unreadable('the calendarDuration has no components')
        parts = [np.asarray(_arr(_field(comps, k, np.zeros((1, 1)))), float) for k in ('months', 'days', 'millis')]
        shape = max((p.shape for p in parts), key=lambda s: int(np.prod(s)))
        mo, d, t = (np.broadcast_to(p, shape) if p.size == 1 else p for p in parts)
        if any(p.shape != shape for p in (mo, d, t)):
            raise Unreadable('the calendarDuration is damaged')
        return CalDuration(mo, d, t / 1000.0, _text(props.get('fmt')) or 'ymdt')
    if cname == 'categorical':
        from .builtins.categoricals import Categorical
        names = _texts(props.get('categoryNames'))
        codes = _arr(props.get('codes', np.zeros((0, 0)))).astype(float)
        if codes.size and (codes.max() > len(names) or codes.min() < 0):
            raise Unreadable('the categorical is damaged (a code past its categories)')
        ordinal = _bool(props.get('isOrdinal', False))
        return Categorical(codes, names, ordinal, _bool(props.get('isProtected', False)) or ordinal)
    if cname == 'table':
        return _table(props)
    if cname == 'timetable':
        return _timetable(props.get('any'))
    raise Unreadable(f"it is an object of class '{cname}', which cannot be read from MAT-files here")


def _vars(data, n):
    if not isinstance(data, Cell):
        raise Unreadable('its variables are damaged')
    out = []
    for v in data.a.reshape(-1, order='F'):
        if isinstance(v, (float, int, bool, complex)):
            v = np.array([[v]])
        out.append(v)
    return out


def _table(props):
    from .builtins.tables import Table
    p = props.get('props')
    use_orig = _bool(_field(p, 'useVariableNamesOriginal', False))
    names = _texts(_field(p, 'VariableNamesOriginal')) if use_orig else _texts(props.get('varnames'))
    n = int(_num(props.get('nrows'), 0))
    vars_ = _vars(props.get('data'), n)
    if len(vars_) != len(names):
        raise Unreadable('its variables and their names do not match')
    rn = _texts(props.get('rownames')) or None
    try:
        T = Table(vars_, names, rn, n)
    except MError as e:
        raise Unreadable(f'it is damaged ({e.message})')
    if isinstance(p, Struct):
        T.desc = _text(_field(p, 'Description'))
        ud = _field(p, 'UserData')
        if ud is not None:
            T.userdata = ud
        dims = _texts(_field(p, 'DimensionNamesOriginal')) if _bool(_field(p, 'useDimensionNamesOriginal', False)) else _texts(_field(p, 'DimensionNames'))
        if len(dims) == 2:
            T.dims = dims
        units = _texts(_field(p, 'VariableUnits'))
        T.units = units if len(units) == len(names) and any(units) else None
        descs = _texts(_field(p, 'VariableDescriptions'))
        T.vdescs = descs if len(descs) == len(names) and any(descs) else None
    return T


def _row_times(rt, n):
    """A timetable's row times: the times, or the struct of a regular timetable (origin,
    specifiedAsRate, stepSize, sampleRate)."""
    from .builtins.timetypes import DateTime, Duration, CalDuration
    if isinstance(rt, (DateTime, Duration)):
        return rt.mapped(lambda a: a.reshape(-1, 1))
    if not isinstance(rt, Struct):
        raise Unreadable('its row times are damaged')
    origin = _field(rt, 'origin')
    if not isinstance(origin, (DateTime, Duration)):
        raise Unreadable('its row times are damaged')
    k = np.arange(n, dtype=float).reshape(-1, 1)
    if _bool(_field(rt, 'specifiedAsRate', False)):
        steps = Duration(k / _num(_field(rt, 'sampleRate'), math.nan))
        return origin.binop('+', origin, steps)
    step = _field(rt, 'stepSize')
    if isinstance(step, Duration):
        steps = step.mapped(lambda a: float(a.reshape(-1)[0]) * k)
    elif isinstance(step, CalDuration):
        steps = CalDuration(k * float(step.mo.reshape(-1)[0]), k * float(step.d.reshape(-1)[0]), k * float(step.t.reshape(-1)[0]))
    else:
        raise Unreadable('its row times are damaged')
    return origin.binop('+', origin, steps)


def _timetable(s):
    from .builtins.tables import TimeTable
    if not isinstance(s, Struct) or s.size != 1:
        raise Unreadable('the timetable is damaged')
    use_orig = _bool(_field(s, 'useVarNamesOrig', False))
    names = _texts(_field(s, 'varNamesOrig')) if use_orig else _texts(_field(s, 'varNames'))
    n = int(_num(_field(s, 'numRows'), 0))
    vars_ = _vars(_field(s, 'data'), n)
    if len(vars_) != len(names):
        raise Unreadable('its variables and their names do not match')
    times = _row_times(_field(s, 'rowTimes'), n)
    try:
        T = TimeTable(vars_, names, times)
    except MError as e:
        raise Unreadable(f'it is damaged ({e.message})')
    dims = _texts(_field(s, 'dimNamesOrig')) if _bool(_field(s, 'useDimNamesOrig', False)) else _texts(_field(s, 'dimNames'))
    if len(dims) == 2:
        T.dims = dims
    ap = _field(s, 'arrayProps')
    if isinstance(ap, Struct):
        T.desc = _text(_field(ap, 'Description'))
        ud = _field(ap, 'UserData')
        if ud is not None:
            T.userdata = ud
    units = _texts(_field(s, 'varUnits'))
    T.units = units if len(units) == len(names) and any(units) else None
    descs = _texts(_field(s, 'varDescriptions'))
    T.vdescs = descs if len(descs) == len(names) and any(descs) else None
    return T


# ---- writing -------------------------------------------------------------------------------------------------

def _cellrow(items):
    return Cell.of_list([Char.of(x) for x in items], (1, len(items))) if items else Cell(np.empty((0, 0), object))


def _cellcol(items):
    return Cell.of_list([Char.of(x) for x in items], (len(items), 1)) if items else Cell(np.empty((0, 0), object))


def _empty_struct():
    return Struct((1, 1), {})


def is_object(v):
    from .builtins.timetypes import DateTime, Duration, CalDuration
    from .builtins.categoricals import Categorical
    from .builtins.tables import Table
    return isinstance(v, (DateTime, Duration, CalDuration, Categorical, Table, Str))


def to_props(v):
    """(class name, properties by name in the order they are written, saved through saveobj)."""
    from .builtins.timetypes import DateTime, Duration, CalDuration
    from .builtins.categoricals import Categorical
    from .builtins.tables import Table, TimeTable
    if isinstance(v, DateTime):
        return 'datetime', {'data': np.asarray(v.a, float) * 1000.0, 'tz': Char.of(v.tz or ''), 'fmt': Char.of(v.fmt or '')}, False
    if isinstance(v, Duration):
        return 'duration', {'millis': np.asarray(v.a, float) * 1000.0, 'fmt': Char.of(v.fmt or 'hh:mm:ss')}, False
    if isinstance(v, CalDuration):
        def one(a):
            a = np.asarray(a, float)
            return np.array([[a.reshape(-1)[0]]]) if a.size and np.all((a == a.reshape(-1)[0]) | (np.isnan(a) & np.isnan(a.reshape(-1)[0]))) else a
        comps = Struct.scalar({'months': one(v.mo), 'days': one(v.d), 'millis': one(np.asarray(v.t, float) * 1000.0)})
        return 'calendarDuration', {'components': comps, 'fmt': Char.of(v.fmt or 'ymdt')}, False
    if isinstance(v, Categorical):
        n = len(v.cats)
        codes = np.asarray(v.a, float)
        dtype = np.uint8 if n < 2 ** 8 else np.uint16 if n < 2 ** 16 else np.uint32
        return 'categorical', {'categoryNames': _cellcol(list(v.cats)), 'codes': np.nan_to_num(codes).astype(dtype),
                               'isOrdinal': bool(v.ordinal), 'isProtected': bool(v.ordinal or v.protected)}, False
    if isinstance(v, TimeTable):
        names = list(v.names)
        data = Cell.of_list(list(v.vars), (1, len(v.vars))) if v.vars else Cell(np.empty((1, 0), object))
        arrayprops = Struct.scalar({'Description': Char.of(v.desc or ''), 'UserData': v.userdata, 'TableCustomProperties': _empty_struct()})
        s = Struct.scalar({
            'data': data, 'dimNames': _cellrow(list(v.dims)), 'varNames': _cellrow(names), 'numRows': float(v.n),
            'numVars': float(len(names)), 'rowTimes': v.times.mapped(lambda a: a.reshape(-1, 1)),
            'CustomProps': _empty_struct(), 'VariableCustomProps': _empty_struct(), 'versionSavedFrom': TIMETABLE_SAVE_VERSION,
            'minCompatibleVersion': 2.0, 'incompatibilityMsg': Char.of(''), 'arrayProps': arrayprops, 'numDims': 2.0,
            'useVarNamesOrig': False, 'useDimNamesOrig': False, 'dimNamesOrig': Cell(np.empty((0, 0), object)),
            'varNamesOrig': Cell(np.empty((0, 0), object)),
            'varDescriptions': _cellrow(v.vdescs) if v.vdescs else Cell(np.empty((0, 0), object)),
            'varUnits': _cellrow(v.units) if v.units else Cell(np.empty((0, 0), object)),
            'timeEvents': np.zeros((0, 0)), 'varContinuity': Cell(np.empty((0, 0), object)),
        })
        return 'timetable', {'any': s}, True
    if isinstance(v, Table):
        names = list(v.names)
        data = Cell.of_list(list(v.vars), (1, len(v.vars))) if v.vars else Cell(np.empty((1, 0), object))
        props = Struct.scalar({
            'useVariableNamesOriginal': False, 'useDimensionNamesOriginal': False, 'CustomProps': _empty_struct(),
            'VariableCustomProps': _empty_struct(), 'versionSavedFrom': TABLE_SAVE_VERSION, 'minCompatibleVersion': 1.0,
            'incompatibilityMsg': Char.of(''), 'VersionSavedFrom': TABLE_SAVE_VERSION, 'Description': Char.of(v.desc or ''),
            'VariableNamesOriginal': Cell(np.empty((0, 0), object)), 'DimensionNames': _cellrow(list(v.dims)),
            'DimensionNamesOriginal': Cell(np.empty((0, 0), object)), 'UserData': v.userdata,
            'VariableDescriptions': _cellrow(v.vdescs) if v.vdescs else Cell(np.empty((0, 0), object)),
            'VariableUnits': _cellrow(v.units) if v.units else Cell(np.empty((0, 0), object)),
            'VariableContinuity': Cell(np.empty((0, 0), object)),
        })
        return 'table', {'data': data, 'ndims': 2.0, 'nrows': float(v.n),
                         'rownames': _cellcol(list(v.rownames)) if v.rownames else Cell(np.empty((0, 0), object)),
                         'nvars': float(len(names)), 'varnames': _cellrow(names), 'props': props}, False
    if isinstance(v, Str):
        return 'string', {'any': string_words(v)}, True
    raise TypeError(type(v).__name__)


def string_words(v):
    """A string array as its saved property 'any' (little-endian words): 1, the number of
    dimensions, the size, each string's length in UTF-16 code units (all ones for a missing
    string), then the text, four code units a uint64 word."""
    a = v.a
    counts, text = [], b''
    for s in a.reshape(-1, order='F'):
        if s is None:
            counts.append((1 << 64) - 1)
            continue
        b = s.encode('utf-16-le', 'surrogatepass')
        counts.append(len(b) // 2)
        text += b
    text += b'\0' * (-len(text) % 8)
    head = np.array([1, a.ndim, *a.shape, *counts], dtype=np.uint64)
    words = np.concatenate([head, np.frombuffer(text, '<u8')]) if text else head
    return words.reshape(1, -1)
