"""A model and the run it produced, in one archive, as Kompartment writes one.

A port of the application's ``src/io/dataset.js`` -- *Save with results* and
opening such a file again -- so an archive written from Python opens in the
application as a live run, and one the application wrote opens here::

    import kompartment as kp
    from kompartment.io import dataset

    res = kp.load('biosphere.json').run()
    dataset.write_dataset(res, 'biosphere-results.zip')

    again = dataset.load_results('biosphere-results.zip')   # a live Results
    again['Dose [I-129]']

**What is kept is the state vector, not the series**: every other series is
worked out from ``(t, y)`` on demand, so a reopened run answers every
question a fresh one does. The archive is the ZIP a compressed save writes,
with the run beside the model::

    <name>.json          the model
    results/meta.json    the run report, the run log, the layout signature, the lengths
    results/t.f64        the output times
    results/y.f64        the state vector at each of them, time-major
    results/held.i32     per state, how many steps the zero-floor moved it
    results/mem.f64      the histories of the blocks that remember

The **layout signature** says what every number in ``y`` is -- every state and
every recorder slot by name and offset -- and a stored run is refused against
a system whose signature differs, since the numbers would read as plausible
values against the wrong labels.

The archive is laid out as the application lays it out (the ZIP writer is
:mod:`kompartment.io.xlsx`'s port of the application's); with
``compress=False`` every entry is stored and the file is the application's to
the byte, as it is when the platform cannot compress.

Two things differ from a run's own record, by necessity: the Python engine
names two counters of its statistics and its timings in snake case, and they
are written under the application's names (``solverPoints``, ``thinnedBy``,
``buildMs``, ``solveMs``, ``totalMs``), so that the application reads them as
its own.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import numbers
import re
import struct
import zlib
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

import numpy as np

from ..errors import KompartmentError
from ..jsonio import dumps, slug
from .csv import is_js_boolean, js_string, js_to_number
from .xlsx import _zip

__all__ = ['FORMAT', 'DIR', 'META', 'DatasetError', 'layout_signature', 'dataset_entries', 'is_dataset',
           'read_dataset', 'rows_of', 'restore_results', 'describe_dataset', 'unzip', 'dataset_archive',
           'write_dataset', 'read_archive', 'load_results']

#: Bumped only for a change that an older reader could not make sense of.
FORMAT = 1

#: Where the run lives inside the archive.
DIR = 'results/'
META = f'{DIR}meta.json'
_T = f'{DIR}t.f64'
_Y = f'{DIR}y.f64'
_HELD = f'{DIR}held.i32'
_MEM = f'{DIR}mem.f64'

#: The most a whole archive may expand to, as the application's reader allows.
MAX_INFLATED = 256 * 1024 * 1024

#: The Python engine's names for what the application calls otherwise.
_STATS_NAMES = {'solver_points': 'solverPoints', 'thinned_by': 'thinnedBy'}
_TIMING_NAMES = {'build_ms': 'buildMs', 'solve_ms': 'solveMs', 'total_ms': 'totalMs'}

_DEFAULT = object()


class DatasetError(KompartmentError, ValueError):
    """An archive whose run cannot be read: damaged, from a newer version, or
    not a description of the model it is read against."""


# --- JavaScript's rules, where Python's differ ----------------------------------------------

def _prop(obj: Any, name: str, default: Any = None) -> Any:
    """``obj.name`` for an object or a dictionary."""
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _truthy(v: Any) -> bool:
    """JavaScript's ToBoolean: an object or array is true however empty."""
    if v is None:
        return False
    if is_js_boolean(v):
        return bool(v)
    if isinstance(v, numbers.Real):
        return not (v == 0 or v != v)
    if isinstance(v, str):
        return v != ''
    return True


def _utf8(s: str) -> bytes:
    """``TextEncoder``: UTF-8, a lone surrogate written as U+FFFD."""
    try:
        return s.encode('utf-8')
    except UnicodeEncodeError:
        return s.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace').encode('utf-8')


def _decode(b: bytes) -> str:
    """``new TextDecoder().decode(b)``: UTF-8, bad bytes replaced, a BOM dropped."""
    s = bytes(b).decode('utf-8', 'replace')
    return s[1:] if s.startswith('﻿') else s


def _no_constant(name: str) -> Any:
    raise ValueError(f'Unexpected token {name[0]} in JSON')


def _json_parse(text: str) -> Any:
    """``JSON.parse``: NaN and Infinity are not JSON."""
    return json.loads(text, parse_constant=_no_constant)


def _plain(v: Any) -> Any:
    """A value as ``JSON.stringify`` sees it: numpy's numbers as numbers, a
    typed array as the object of numbered keys it stringifies to, a function
    dropped (``_DEFAULT`` marks it)."""
    if v is None or isinstance(v, (str, bool)):
        return v
    if is_js_boolean(v):
        return bool(v)
    if isinstance(v, numbers.Integral):
        return int(v)
    if isinstance(v, numbers.Real):
        return float(v)
    if isinstance(v, Mapping):
        out = {}
        for k, x in v.items():
            p = _plain(x)
            if p is not _DEFAULT:
                out[k if isinstance(k, str) else js_string(k)] = p
        return out
    if isinstance(v, (list, tuple)):
        return [None if p is _DEFAULT else p for p in (_plain(x) for x in v)]
    if isinstance(v, np.ndarray):
        return {str(i): _plain(x) for i, x in enumerate(v.reshape(-1).tolist())}
    if callable(v):
        return _DEFAULT
    return {}


def _stringify(value: Any) -> str:
    """``JSON.stringify(value, null, 2)``."""
    return dumps(_plain(value), 2)


def _locale(v: Any) -> str:
    """``v.toLocaleString()`` as an en-US page writes it: grouped in threes, at
    most three decimals."""
    if isinstance(v, str):
        return v
    if v is None or is_js_boolean(v) or not isinstance(v, numbers.Real):
        return js_string(v)
    x = float(v)
    if math.isnan(x):
        return 'NaN'
    if math.isinf(x):
        return '∞' if x > 0 else '-∞'
    d = Decimal(repr(abs(x))).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
    whole, _, frac = f'{d:f}'.partition('.')
    frac = frac.rstrip('0')
    text = f'{int(whole):,}' + (f'.{frac}' if frac else '')
    return ('-' if x < 0 and text != '0' else '') + text


# --- the layout signature --------------------------------------------------------------------

def _text(v: Any) -> str:
    return 'undefined' if v is None else js_string(v)


def layout_signature(system: Any) -> str:
    """What the numbers mean, as one string (``layoutSignature``): every entry of
    the state vector and every recorder slot, by the name and offset the builder
    gave it. Two models that produce this string produce the same ``y``."""
    layout = _prop(system, 'layout') if system is not None else None
    states = (_prop(layout, 'states') if layout is not None else None) or []
    s = ','.join(f"{_text(_prop(x, 'kind'))}:{_text(_prop(x, 'name'))}@{_text(_prop(x, 'base'))}"
                 f"+{_text(_prop(x, 'width'))}" for x in states)
    recorders = (_prop(system, 'recorders') if system is not None else None) or []

    def entry_name(r: Any) -> str:
        entry = _prop(r, 'entry')
        name = _prop(entry, 'name') if entry is not None else None
        return '?' if name is None else js_string(name)

    m = ','.join(f"{_text(_prop(r, 'kind'))}:{entry_name(r)}@{_text(_prop(r, 'mem'))}+{_text(_prop(r, 'width'))}"
                 for r in recorders)

    def count(key: str) -> str:
        v = _prop(layout, key) if layout is not None else None
        return js_string(0 if v is None else v)

    return f"v{FORMAT}|n={count('nstate')},{count('nalg')},{count('nparam')}|s={s}|m={m}"


# --- writing ---------------------------------------------------------------------------------

class RangeError(DatasetError):
    """What a typed array says when it is asked to hold more than it has room for."""


def _set_at(out: np.ndarray, values: Any, at: int) -> None:
    """``out.set(values, at)``: past the end is a RangeError, as a typed array says."""
    if values is None or not hasattr(values, '__len__'):
        return
    v = np.asarray(values, dtype=np.float64).reshape(-1)
    if at + v.size > out.size:
        raise RangeError('offset is out of bounds')
    out[at:at + v.size] = v


def _flatten(rows: Sequence[Any], width: int) -> np.ndarray:
    out = np.zeros(len(rows) * width)
    for i, row in enumerate(rows):
        _set_at(out, row, i * width)
    return out


def _to_int32(x: float) -> int:
    if math.isnan(x) or math.isinf(x):
        return 0
    i = int(x) & 0xFFFFFFFF
    return i - (1 << 32) if i & 0x80000000 else i


def _int32(values: Any) -> np.ndarray:
    """``Int32Array.from(values)``."""
    if values is None:
        return np.zeros(0, dtype='<i4')
    a = np.asarray(values)
    if a.dtype.kind in 'biu':
        return a.reshape(-1).astype(np.int64).astype('<i4')
    return np.array([_to_int32(js_to_number(x)) for x in a.reshape(-1).tolist()], dtype='<i4')


def _memory(system: Any) -> List[Any]:
    """The recorders' histories a system carries: ``memory`` in the application, ``MEM`` here."""
    if system is None:
        return []
    for name in ('memory', 'MEM'):
        m = _prop(system, name)
        if m is not None:
            return list(m)
    return []


def _field(m: Any, js_name: str, py_name: str) -> Any:
    """A recorder's field by the application's name, or this engine's."""
    if isinstance(m, Mapping):
        return m.get(js_name, _DEFAULT)
    if hasattr(m, py_name):
        return getattr(m, py_name)
    return getattr(m, js_name, _DEFAULT)


def _project_dict(project: Any) -> Dict[str, Any]:
    """The model as the dictionary a file holds."""
    if project is None:
        return {}
    if isinstance(project, Mapping):
        return project  # type: ignore[return-value]
    if hasattr(project, 'to_dict') and hasattr(project, 'raw'):  # a kompartment.Model
        return project.to_dict()
    raw = getattr(project, '_raw', None)  # an engine Project: the file it was read from
    if isinstance(raw, Mapping):
        return raw  # type: ignore[return-value]
    return {'name': getattr(project, 'name', None), 'description': getattr(project, 'description', None),
            'simulation': getattr(project, 'simulation', None)}


def _renamed(d: Any, names: Mapping[str, str]) -> Any:
    if not isinstance(d, Mapping):
        return d
    return {names.get(k, k): v for k, v in d.items()}


def dataset_entries(project: Any, results: Any, inner: str, stamp: Optional[str] = None,
                    log: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """The entries a results archive holds, the model aside (``datasetEntries``).

    ``project`` is the model as it will be saved (for its name), ``results`` a
    :class:`kompartment.engine.Results`, ``inner`` the model entry's name
    (``biosphere.json``), ``stamp`` when the run was made (ISO, the caller's
    clock) and ``log`` the run log as lines. Returns ``[{'name', 'bytes'}]``:
    ``results/meta.json``, ``t.f64`` and ``y.f64``, then ``held.i32`` and
    ``mem.f64`` when there is anything to put in them.
    """
    project = _project_dict(project)
    t = np.asarray(results.t, dtype=np.float64).reshape(-1)
    rows = results.y
    first = rows[0] if len(rows) else None
    nstate = len(first) if first is not None and hasattr(first, '__len__') else 0
    y = _flatten(rows, nstate)
    stats_in = results.stats if results.stats is not None else {}
    held = _int32(stats_in.get('held') if isinstance(stats_in, Mapping) else None)

    # Every recorder's history end to end: its times, then its values.
    memory = _memory(getattr(results, 'system', None))
    lengths = [len(m.history.t) for m in memory]
    total = sum(lengths)
    mem = np.zeros(total * 2)
    at = 0
    for m in memory:
        n = len(m.history.t)
        _set_at(mem, m.history.t, at)
        _set_at(mem, m.history.v, at + n)
        at += n * 2

    # The scalars a recorder carries beside its history; a field it does not
    # have is left out, as JSON.stringify leaves out an undefined one.
    recorders = []
    for m, n in zip(memory, lengths):
        kind = _field(m, 'kind', 'kind')
        recording = _field(m, 'recording', 'recording')
        r: Dict[str, Any] = {} if kind is _DEFAULT else {'kind': kind}
        r['n'] = n
        r['recording'] = _truthy(None if recording is _DEFAULT else recording)
        for js_name, py_name in (('totalTime', 'total_time'), ('lastTime', 'last_time'),
                                 ('resetSum', 'reset_sum')):
            v = _field(m, js_name, py_name)
            if v is not _DEFAULT:
                r[js_name] = v
        recorders.append(r)

    # Everything but the big arrays, so that a reader can say what the file
    # holds without decompressing megabytes of it.
    stats = {k: v for k, v in (stats_in.items() if isinstance(stats_in, Mapping) else []) if k != 'held'}
    outputs = getattr(results, 'outputs', None)
    timing = getattr(results, 'timing', None)
    meta = {
        'format': FORMAT,
        'kind': 'ecolego-results',
        'model': inner,
        'name': project.get('name') if project.get('name') is not None else '',
        'stamp': stamp,
        'times': int(t.size),
        'states': nstate,
        'outputs': len(outputs()) if callable(outputs) else None,
        'signature': layout_signature(getattr(results, 'system', None)),
        'stats': _renamed(stats, _STATS_NAMES),
        'timing': _renamed(timing, _TIMING_NAMES),
        'recorders': recorders,
        'log': list(log) if isinstance(log, (list, tuple)) else None,
    }
    out = [
        {'name': META, 'bytes': _utf8(_stringify(meta))},
        {'name': _T, 'bytes': t.astype('<f8').tobytes()},
        {'name': _Y, 'bytes': y.astype('<f8').tobytes()},
    ]
    if held.size:
        out.append({'name': _HELD, 'bytes': held.astype('<i4').tobytes()})
    if total:
        out.append({'name': _MEM, 'bytes': mem.astype('<f8').tobytes()})
    return out


# --- reading ---------------------------------------------------------------------------------

def is_dataset(entries: Any) -> bool:
    """Whether an unzipped archive carries a run as well as a model (``isDataset``)."""
    return isinstance(entries, Mapping) and META in entries


def _read_floats(data: Any, dtype: str = '<f8') -> np.ndarray:
    """A typed array out of an entry's bytes: as many whole values as fit."""
    if data is None:
        return np.zeros(0, dtype=dtype)
    per = np.dtype(dtype).itemsize
    b = bytes(data) if not isinstance(data, (bytes, bytearray)) else data
    n = len(b) // per
    return np.frombuffer(b, dtype=dtype, count=n)


def _index(x: Any, length: int) -> int:
    """A ``subarray`` bound: truncated, counted from the end when negative, clamped."""
    v = js_to_number(x)
    if math.isnan(v):
        return 0
    if math.isinf(v):
        return length if v > 0 else 0
    v = int(v)
    return max(length + v, 0) if v < 0 else min(v, length)


def _subarray(a: np.ndarray, begin: Any, end: Any) -> np.ndarray:
    return a[_index(begin, a.size):_index(end, a.size)]


def read_dataset(entries: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The run out of an archive, as plain arrays (``readDataset``); ``None`` when
    the archive holds none.

    ``entries`` maps each entry's name to its bytes (:func:`unzip`). Returns
    ``{'meta', 't', 'flat', 'held', 'memory'}``: the parsed ``meta.json``, the
    times as a list, the trajectory flat (a read-only numpy view: :func:`rows_of`
    cuts it into rows), the held counts or ``None``, and one dictionary per
    recorder with its history as ``t`` and ``v``. Nothing is checked against a
    model here -- that is :func:`restore_results`. Raises :class:`DatasetError`
    for a run from a newer version or a trajectory that is not as long as the
    file says.
    """
    if not is_dataset(entries):
        return None
    meta = _json_parse(_decode(entries[META]))
    info: Mapping[str, Any] = meta if isinstance(meta, Mapping) else {}
    fmt = info.get('format')
    if fmt is not None and js_to_number(fmt) > FORMAT:
        raise DatasetError(f'These results were written by a newer version of this editor (format '
                           f'{js_string(fmt)}; this one reads {FORMAT}). The model in the file opens either way.')
    t = _read_floats(entries.get(_T))
    flat = _read_floats(entries.get(_Y))
    states = info.get('states') if info.get('states') is not None else 0
    want = t.size * js_to_number(states)
    if flat.size != want:
        raise DatasetError(f'The trajectory is {_locale(int(flat.size))} numbers and the file says it should be '
                           f'{_locale(want)} ({_locale(int(t.size))} times × {_locale(states)} states). '
                           'The archive is damaged.')
    held = _read_floats(entries[_HELD], '<i4') if _HELD in entries else None
    mem = _read_floats(entries[_MEM]) if _MEM in entries else np.zeros(0)
    memory = []
    at: Any = 0
    for r in info.get('recorders') or []:
        # `at + r.n`: a missing count is NaN and a null one 0, as JavaScript adds them.
        n = js_to_number(r['n']) if isinstance(r, Mapping) and 'n' in r else math.nan
        memory.append({**(r if isinstance(r, Mapping) else {}),
                       't': _subarray(mem, at, at + n).tolist(),
                       'v': _subarray(mem, at + n, at + n * 2).tolist()})
        at = at + n * 2
    return {'meta': meta, 't': t.tolist(), 'flat': flat, 'held': held, 'memory': memory}


def rows_of(flat: np.ndarray, times: Any, states: Any) -> List[np.ndarray]:
    """The flat trajectory as one row per output time (``rowsOf``): views into
    the one array, not copies."""
    k = js_to_number(states)
    return [_subarray(flat, i * k, (i + 1) * k) for i in range(int(js_to_number(times)))]


def _set_field(m: Any, js_name: str, py_name: str, value: Any) -> None:
    if hasattr(m, py_name):
        setattr(m, py_name, value)
    else:
        setattr(m, js_name, value)


def restore_results(project: Any, system: Any, data: Mapping[str, Any], results_class: Any = None) -> Any:
    """Puts a stored run back onto a freshly built system (``restoreResults``).

    ``project`` is the engine ``Project`` the system was built from (a model
    dictionary or a :class:`kompartment.Model` is loaded into one), ``system``
    its :class:`kompartment.engine.System` (built here when ``None``), ``data``
    what :func:`read_dataset` returned. The layout signature is the gate:
    raises :class:`DatasetError` when the stored run does not describe this
    system's state vector. Returns a live :class:`kompartment.engine.Results`
    whose rows share the stored trajectory, with the recorders' histories put
    back. A run stored without its timings gets ``{}`` rather than ``None``,
    which the Python ``Results`` could not describe itself with.
    """
    from ..engine.project import Project
    if not isinstance(project, Project):
        project = Project(_project_dict(project))
    if system is None:
        from ..engine.builder import build_system
        system = build_system(project)
    if results_class is None:
        from ..engine.runner import Results as results_class  # noqa: N813
    meta = data['meta']
    if layout_signature(system) != meta.get('signature'):
        raise DatasetError('The stored run does not describe this model’s state vector, so the numbers in it '
                           'cannot be read against it.')
    stats = dict(meta.get('stats')) if isinstance(meta.get('stats'), Mapping) else {}
    if data.get('held') is not None:
        stats['held'] = data['held']

    # Back into the histories the blocks read, as plain lists that they can
    # go on pushing onto.
    saved_all = data.get('memory') or []
    for i, m in enumerate(_memory(system)):
        saved = saved_all[i] if i < len(saved_all) else None
        if saved is None:
            continue
        m.history.t = saved.get('t')
        m.history.v = saved.get('v')
        m.recording = saved.get('recording')
        _set_field(m, 'totalTime', 'total_time', saved.get('totalTime'))
        _set_field(m, 'lastTime', 'last_time', saved.get('lastTime'))
        _set_field(m, 'resetSum', 'reset_sum', saved.get('resetSum'))

    states = meta.get('states') if meta.get('states') is not None else 0
    y = rows_of(data['flat'], len(data['t']), states)
    timing = meta.get('timing')
    return results_class(project, system, {'t': data['t'], 'y': y, 'stats': stats},
                         timing if timing is not None else {})


# --- a date, as the page shows one -----------------------------------------------------------

_ISO = re.compile(r'([+-]\d{6}|\d{4})(?:-(\d{2})(?:-(\d{2}))?)?'
                  r'(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|[+-]\d{2}:\d{2})?)?')


def _parse_date(value: Any) -> Optional[_dt.datetime]:
    """``new Date(value)``, for a number (milliseconds) or an ISO string; ``None``
    for what would be an Invalid Date (the application's parser also takes
    other spellings, which are not read here)."""
    try:
        if isinstance(value, numbers.Real) and not is_js_boolean(value):
            ms = float(value)
            if not math.isfinite(ms):
                return None
            return _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(milliseconds=ms)
        if not isinstance(value, str):
            return None
        m = _ISO.fullmatch(value.strip())
        if not m:
            return None
        year, month, day, hh, mm, ss, frac, zone = m.groups()
        ms = int((frac or '0')[:3].ljust(3, '0'))
        d = _dt.datetime(int(year), int(month or 1), int(day or 1), int(hh or 0), int(mm or 0), int(ss or 0),
                         ms * 1000)
        if hh is None:  # a date alone is midnight UTC
            return d.replace(tzinfo=_dt.timezone.utc)
        if zone is None:  # a date and time without a zone is local
            return d.astimezone()
        if zone == 'Z':
            return d.replace(tzinfo=_dt.timezone.utc)
        sign = 1 if zone[0] == '+' else -1
        offset = _dt.timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6]))
        return d.replace(tzinfo=_dt.timezone(sign * offset))
    except (ValueError, OverflowError):
        return None


def _locale_datetime(d: _dt.datetime) -> str:
    """``date.toLocaleString()`` as an en-US page writes it, in local time."""
    d = d.astimezone()
    hour = d.hour % 12 or 12
    return f"{d.month}/{d.day}/{d.year}, {hour}:{d.minute:02d}:{d.second:02d} {'AM' if d.hour < 12 else 'PM'}"


def describe_dataset(meta: Any) -> str:
    """One line saying what is in the file, for the notice after opening it
    (``describeDataset``). Numbers and the date are written as an en-US page
    writes them."""
    if not _truthy(meta):
        return ''
    stamp = meta.get('stamp')
    when = _parse_date(stamp) if _truthy(stamp) else None
    ran = f'run {_locale_datetime(when)}, ' if when is not None else ''
    times, states = meta.get('times'), meta.get('states')

    def one(v: Any) -> bool:
        return isinstance(v, numbers.Real) and not is_js_boolean(v) and v == 1

    stats = meta.get('stats')
    solver = stats.get('solver') if isinstance(stats, Mapping) else None
    return (f"{ran}{_locale(times)} output time{'' if one(times) else 's'} over "
            f"{_locale(states)} state{'' if one(states) else 's'}"
            + (f', {js_string(solver)}' if _truthy(solver) else ''))


# --- the archive -----------------------------------------------------------------------------

def _zip_error(message: str) -> DatasetError:
    return DatasetError(message)


def unzip(data: Union[bytes, bytearray, memoryview], inflate_limit: int = MAX_INFLATED) -> Dict[str, bytes]:
    """The entries of a ZIP archive, by name, in the order its directory lists
    them, as the application's ``unzip`` reads one: names as UTF-8, directories
    left out, stored and deflated entries only, no encrypted ones, and what
    comes out held to one allowance for the whole archive (``inflate_limit``,
    the application's 256 MB unless a test says otherwise). Checksums are not
    checked, as the application does not check them. The writer here keeps to
    the same allowance (see :func:`dataset_archive`), so an archive written
    here always opens."""
    b = bytes(data)
    size = len(b)
    u16 = struct.Struct('<H').unpack_from
    u32 = struct.Struct('<I').unpack_from
    eocd = -1
    for p in range(size - 22, max(0, size - 0x10000 - 22) - 1, -1):
        if u32(b, p)[0] == 0x06054B50:
            eocd = p
            break
    if eocd < 0:
        raise _zip_error('This does not look like a ZIP archive. An Ecolego project (.eco) is a zipped project '
                         'folder; a bare model.xml should be opened directly instead.')
    count = u16(b, eocd + 10)[0]
    at = u32(b, eocd + 16)[0]
    if count == 0xFFFF or at == 0xFFFFFFFF:
        loc = eocd - 20
        if loc >= 0 and u32(b, loc)[0] == 0x07064B50:
            z64 = struct.unpack_from('<Q', b, loc + 8)[0]
            if z64 + 56 > size:
                raise _zip_error(f'This archive says its ZIP64 directory is at byte {z64}, which is outside its own '
                                 f'{size} bytes.')
            if u32(b, z64)[0] == 0x06064B50:
                count = struct.unpack_from('<Q', b, z64 + 32)[0]
                at = struct.unpack_from('<Q', b, z64 + 48)[0]
    out: Dict[str, bytes] = {}
    spent = 0

    def mb(n: float) -> int:
        return math.floor(n / 1048576 + 0.5)

    for _ in range(count):
        if at < 0 or at + 46 > size or u32(b, at)[0] != 0x02014B50:
            raise _zip_error('The central directory is damaged')
        flags, method = u16(b, at + 8)[0], u16(b, at + 10)[0]
        csize, usize = u32(b, at + 20)[0], u32(b, at + 24)[0]
        nlen, xlen, clen = u16(b, at + 28)[0], u16(b, at + 30)[0], u16(b, at + 32)[0]
        local = u32(b, at + 42)[0]
        if at + 46 + nlen + xlen + clen > size:
            raise _zip_error(f'The central directory runs past the end of this {size}-byte archive')
        name = b[at + 46:at + 46 + nlen].decode('utf-8', 'replace')
        if flags & 0x01:
            raise _zip_error(f"'{name}' is encrypted. Ecolego can obfuscate a project on save; re-save it without "
                             'that option, or export the model, before importing.')
        if 0xFFFFFFFF in (csize, usize, local):
            p, end = at + 46 + nlen, min(at + 46 + nlen + xlen, size)
            while p + 4 <= end:
                tag, length = u16(b, p)[0], u16(b, p + 2)[0]
                if tag == 0x0001:
                    q = p + 4
                    for field in ('usize', 'csize', 'local'):
                        if {'usize': usize, 'csize': csize, 'local': local}[field] != 0xFFFFFFFF:
                            continue
                        if q + 8 > min(p + 4 + length, end):
                            raise _zip_error(f"The ZIP64 record for '{name}' says it is {length} bytes long but "
                                             'does not hold the sizes it promises; the archive looks damaged.')
                        v = struct.unpack_from('<Q', b, q)[0]
                        q += 8
                        if field == 'usize':
                            usize = v
                        elif field == 'csize':
                            csize = v
                        else:
                            local = v
                    break
                p += 4 + length
        at += 46 + nlen + xlen + clen
        if name.endswith('/'):
            continue
        if local + 30 > size:
            raise _zip_error(f"'{name}' says its data begins at byte {local}, which is outside this {size}-byte "
                             'archive.')
        if u32(b, local)[0] != 0x04034B50:
            raise _zip_error(f"The local header for '{name}' is damaged")
        start = local + 30 + u16(b, local + 26)[0] + u16(b, local + 28)[0]
        if start > size or start + csize > size:
            raise _zip_error(f"'{name}' claims {csize} bytes from {start}, which runs past the end of this "
                             f'{size}-byte archive.')
        raw = b[start:start + csize]
        if method == 0:
            out[name] = raw
            continue
        if method != 8:
            raise _zip_error(f"'{name}' uses compression method {method}, which is not supported (only stored "
                             'and deflate are).')
        if usize > MAX_INFLATED:
            raise _zip_error(f"'{name}' says it expands to {mb(usize)} MB, past the {mb(MAX_INFLATED)} MB this "
                             'reader will decompress. No real model is that large.')
        if usize > inflate_limit - spent:
            raise _zip_error(f"'{name}' takes this archive past the {mb(inflate_limit)} MB this reader will "
                             f'decompress in total: {mb(spent)} MB have come out already and this entry adds '
                             f'{mb(usize)} more. No real project expands that far, so the archive is either '
                             'damaged or built to exhaust memory.')
        try:
            d = zlib.decompressobj(-15)
            body = d.decompress(raw, max(0, inflate_limit - spent) + 1)
        except zlib.error as e:
            raise _zip_error(f"Could not decompress '{name}': {e}") from None
        spent += len(body)
        if usize and len(body) != usize:
            raise _zip_error(f"'{name}' inflated to {len(body)} bytes but the directory says {usize}; the archive "
                             'looks damaged.')
        out[name] = body
    return out


def _iso_now() -> str:
    """``new Date().toISOString()``."""
    d = _dt.datetime.now(_dt.timezone.utc)
    return f'{d:%Y-%m-%dT%H:%M:%S}.{d.microsecond // 1000:03d}Z'


def _default_log(project: Dict[str, Any], results: Any) -> List[str]:
    from .. import __version__
    from ..engine.runlog import payload_of, run_log_lines, run_log_text
    lines = run_log_lines(project, payload_of(results), build=f'Python {__version__}')
    return run_log_text(lines).split('\n')


def dataset_archive(results: Any, *, project: Any = None, inner: Optional[str] = None, stamp: Any = _DEFAULT,
                    log: Any = _DEFAULT, compress: bool = True, modified: Any = None) -> bytes:
    """A model and its run as the archive *Save with results* writes: the model
    at the root as ``<slug of its name>.json`` (``JSON.stringify(model, null,
    2)``), the run beside it under ``results/``.

    ``project`` is the model (a dictionary or a :class:`kompartment.Model`),
    by default the one the run was built from -- it has to be, or the file is a
    pair of things that do not go together. ``inner`` names the model entry;
    ``stamp`` defaults to now and ``log`` to the run log of ``results`` (pass
    ``None`` for either to write none). ``compress=False`` stores every entry,
    as the application does where the platform cannot compress; ``modified`` is
    the entries' time stamp, local time, the epoch by default. What would take
    the deflated total past the reader's 256 MB allowance is stored, as the
    application stores it, so every archive written opens again.
    """
    raw = _project_dict(results.project if project is None else project)
    name = f"{slug(raw.get('name'))}.json" if inner is None else inner
    if stamp is _DEFAULT:
        stamp = _iso_now()
    if log is _DEFAULT:
        log = _default_log(raw, results)
    entries = dataset_entries(raw, results, name, stamp=stamp, log=log)
    return _zip([(name, _utf8(dumps(raw, 2))), *((e['name'], e['bytes']) for e in entries)],
                modified=modified, compress=compress)


def write_dataset(results: Any, path: Union[str, Path], **options: Any) -> bytes:
    """Writes :func:`dataset_archive` to ``path`` and returns the bytes."""
    data = dataset_archive(results, **options)
    Path(path).write_bytes(data)
    return data


def _source_bytes(source: Any) -> bytes:
    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source)
    return Path(source).read_bytes()


def read_archive(source: Any) -> Dict[str, Any]:
    """A model archive read as opening one reads it: the model, and the run
    beside it when there is one.

    ``source`` is the archive's bytes or its path. Returns ``{'project',
    'dataset', 'problem'}``: the model (the first ``.json`` entry outside
    ``results/``), what :func:`read_dataset` made of the run (``None`` when
    there is none) and, when the run would not read, why -- the model opens
    either way. An Ecolego project (an archive with a ``model.xml``) is not
    read here.
    """
    entries = unzip(_source_bytes(source))
    if any(re.search(r'(^|/)model\.xml$', n, re.I) for n in entries):
        raise DatasetError('This is an Ecolego project (it holds a model.xml); import it with '
                           'kompartment.importers rather than opening it as a model archive.')
    name = next((n for n in entries if not n.startswith(DIR) and n.lower().endswith('.json')), None)
    if name is None:
        raise DatasetError(f"This is a ZIP archive with no model in it — no .json file and no model.xml. It holds "
                           f"{', '.join(list(entries)[:4])}.")
    project = _json_parse(_decode(entries[name]))
    out: Dict[str, Any] = {'project': project, 'dataset': None, 'problem': None}
    if not is_dataset(entries):
        return out
    try:
        out['dataset'] = read_dataset(entries)
    except Exception as e:  # noqa: BLE001 -- the model opens whatever the run did
        out['problem'] = str(e)
    return out


def load_results(source: Any, *, project: Any = None) -> Any:
    """The run in a model archive, as a live :class:`kompartment.engine.Results`,
    the way the application opens one: the model in the archive loaded and
    built, the stored run checked against it and put back, and the timings
    marked as those of a run that was opened (``opened``, and ``buildMs`` the
    time this build took).

    ``project`` replaces the model in the archive (it must lay its states out
    the same way). Raises :class:`DatasetError` when the archive holds no run,
    when the run will not read, or when it does not describe the model.
    """
    import time
    from ..engine.builder import build_system
    from ..engine.project import Project
    got = read_archive(source)
    if got['problem']:
        raise DatasetError(got['problem'])
    if got['dataset'] is None:
        raise DatasetError('This archive holds a model and no run.')
    started = time.perf_counter()
    engine_project = Project(_project_dict(got['project'] if project is None else project))
    system = build_system(engine_project)
    results = restore_results(engine_project, system, got['dataset'])
    timing = got['dataset']['meta'].get('timing')
    results.timing = {**(timing if isinstance(timing, Mapping) else {}),
                      'buildMs': (time.perf_counter() - started) * 1000, 'opened': True}
    return results
