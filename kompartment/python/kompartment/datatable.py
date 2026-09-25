"""The model's data as a flat table, and back again.

A port of the application's ``src/domain/datatable.js``: a parameter's value,
a lookup table's points and the distribution either of them carries, as rows
that :mod:`kompartment.io.datafile` spells as a spreadsheet or an HDF5 tree --
and rows read from such a file written back into the model. It works on the
project dictionary (:attr:`kompartment.Model.raw`) exactly as the application
works on its model object, edits included::

    import kompartment as kp
    from kompartment import datatable

    m = kp.load('biosphere.json')
    rows = datatable.collect(m.raw)          # [{'id', 'unit', 'time', 'value', 'pdf', 'note', ...}]
    report = datatable.apply(m.raw, rows_from_a_file)
    print(datatable.describe(report))        # "Read 12 values, 3 distributions."

**A row** is ``{'id', 'unit', 'time', 'value', 'pdf', 'note'}`` (``collect``
adds ``block``, ``index`` and ``kind``). ``id`` is a dotted path -- the
sub-systems, the block, then one segment per index, in the block's own list
order; ``time`` is ``None`` for a parameter and a number for one point of a
lookup table; ``pdf`` is a spec as :mod:`kompartment.stats.pdf` holds one.

**Reading an id back** asks the model: the longest prefix that is a parameter
or a lookup table is the block, and what is left are its indices; ``_`` is the
block's own value. Creating what is missing (``create=True``) has no block to
ask, so the whole path is the name: ``a.b.c`` makes ``c`` in the sub-system
``a.b`` -- unless the model already gives that name to a block or a sub-system,
it is a reserved word, the id has no name in it, or the rows would write
nothing into the block, each of which is a line in the report and makes
nothing. Reading the data out (:func:`collect`) changes nothing in the model; a
blank cell is no value; a row's unit is its block's, whichever index it is for.

The few editor operations this needs (``effectiveValue``, ``setEntryValue``,
``clearEntryValue``, ``addSystem``, ``addParameter``, ``addLookup``,
``validateName``, ``findBlock``) are ported here from ``src/domain/edit.js`` and
``blocks.js``, and write into the dictionary as the application's do.
"""

from __future__ import annotations

import math
import numbers
import re
from array import array
from functools import cmp_to_key
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from .errors import EditError, KompartmentError
from .indexlists import derive_block_lists, derive_elements
from .io.csv import JS_WHITESPACE, is_js_boolean, js_string, js_to_number
from .io.datafile import DEFAULT_SEGMENT, usable
from .keys import COLLECTIONS
from .names import NAME_RE, RESERVED, is_valid_path, system_paths
from .stats.pdf import PDF_KINDS, parse_pdf

__all__ = ['DataTableError', 'DataReport', 'CARRIES', 'id_for', 'collect', 'legal_name', 'resolve', 'apply',
           'describe']

#: The two kinds of block this carries. Nothing else has data in this sense.
CARRIES = ('parameters', 'lookups')

#: The singular name of each collection: what one of its blocks is.
_SINGULAR = {
    'compartments': 'compartment', 'expressions': 'expression', 'parameters': 'parameter', 'lookups': 'lookup',
    'index_reductions': 'index_reduction', 'block_reductions': 'block_reduction', 'functions': 'function',
    'min_maxes': 'min_max', 'running_means': 'running_mean', 'snapshots': 'snapshot', 'delays': 'delay',
    'triggers': 'trigger', 'farfields': 'farfield', 'waste_packages': 'waste_package', 'events': 'event',
    'transfers': 'transfer', 'inflows': 'inflow',
}

_WORD = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


class DataTableError(KompartmentError):
    """Something about a data table that cannot be done."""


# --- JavaScript's rules, where Python's differ ----------------------------------------------

class _Undefined:
    def __repr__(self) -> str:
        return 'undefined'

    def __bool__(self) -> bool:
        return False


_UNDEF = _Undefined()


def _nullish(v: Any) -> bool:
    return v is None or v is _UNDEF


def _get(obj: Any, key: Any) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, _UNDEF)
    return _UNDEF


def _nz(v: Any, default: Any) -> Any:
    return default if _nullish(v) else v


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
    return 'undefined' if v is _UNDEF else js_string(v)


def _finite(x: Any) -> bool:
    try:
        return math.isfinite(x)
    except (OverflowError, TypeError):
        return False


def _num(v: Any) -> Optional[Union[int, float]]:
    """A number where there is one, ``None`` otherwise (``num``). Blank is no
    value: a string of spaces is ``None``, not the 0 that ``Number('')`` is."""
    if _nullish(v) or (isinstance(v, str) and v == ''):
        return None
    if isinstance(v, numbers.Real) and not is_js_boolean(v):
        n = v.item() if hasattr(v, 'item') else v
    else:
        text = js_string(v).strip(JS_WHITESPACE)
        if text == '':
            return None
        n = js_to_number(text)
    return n if _finite(n) else None


def _present(v: Any) -> bool:
    """Whether a row gives a time or a value at all: blank is none."""
    return not _nullish(v) and not (isinstance(v, str) and v.strip(JS_WHITESPACE) == '')


def _value(v: Any) -> Any:
    """A number where it is one, the text otherwise (``value``)."""
    n = _num(v)
    if n is not None:
        return n
    t = '' if _nullish(v) else js_string(v).strip(JS_WHITESPACE)
    return None if t == '' else t


def _strictly_equal(a: Any, b: Any) -> bool:
    """``a === b``."""
    if a is _UNDEF or b is _UNDEF:
        return a is b
    if a is None or b is None:
        return a is b
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a == b
    if is_js_boolean(a) or is_js_boolean(b):
        return is_js_boolean(a) and is_js_boolean(b) and bool(a) == bool(b)
    if isinstance(a, numbers.Real) and isinstance(b, numbers.Real):
        return a == b
    return a is b


def _is_array_index(k: str) -> bool:
    return (k == '0' or (k[:1] in '123456789' and k.isdigit() and k.isascii())) and int(k) < 0xFFFFFFFF


def _entries(obj: Any) -> List[tuple]:
    """``Object.entries(obj ?? {})``: a string's characters and a list's items by
    their indices, a dictionary's own keys with the array indices first."""
    if _nullish(obj):
        return []
    if isinstance(obj, str):
        return [(str(i), c) for i, c in enumerate(obj)]
    if isinstance(obj, (list, tuple)):
        return [(str(i), v) for i, v in enumerate(obj)]
    if isinstance(obj, Mapping):
        items = [(k if isinstance(k, str) else js_string(k), v) for k, v in obj.items()]
        first = sorted((kv for kv in items if _is_array_index(kv[0])), key=lambda kv: int(kv[0]))
        return first + [kv for kv in items if not _is_array_index(kv[0])]
    return []


def _keys(obj: Any) -> List[str]:
    return [k for k, _ in _entries(obj)]


def _is_view(v: Any) -> bool:
    return isinstance(v, (array, memoryview)) or type(v).__name__ == 'ndarray'


def _length(v: Any) -> Any:
    """``v?.length``: ``undefined`` for what has none."""
    if type(v).__name__ == 'ndarray':
        return int(v.size)
    if isinstance(v, (str, list, tuple, array, memoryview)):
        return len(v)
    return _UNDEF


def _message(e: BaseException) -> str:
    """``e.message``."""
    if isinstance(e, KeyError) and e.args:
        return js_string(e.args[0])
    return str(e)


def _locale(n: Any) -> str:
    """``n.toLocaleString()`` for a count, as an en-US page writes it."""
    if isinstance(n, numbers.Integral) and not is_js_boolean(n):
        return f'{int(n):,}'
    if isinstance(n, float) and n.is_integer():
        return f'{int(n):,}'
    return js_string(n)


# --- the editor, as far as a data table uses it (src/domain/edit.js, blocks.js) -------------

def _qualified_name(block: Any) -> str:
    """``qualifiedName``: the block's sub-system's path, then its own name."""
    system = _nz(_get(block, 'system'), '')
    name = _nz(_get(block, 'name'), '')
    return f'{_text(system)}.{_text(name)}' if _truthy(system) else _text(name)


def _qualify(system: str, name: Any) -> str:
    return f'{system}.{_text(name)}' if system else _text(name)


def _find_block(project: Mapping[str, Any], name: Any) -> Optional[Dict[str, Any]]:
    """``findBlock``: the first block of that qualified name, in the order of the collections."""
    for collection in COLLECTIONS:
        for b in _nz(_get(project, collection), []):
            if isinstance(b, Mapping) and _strictly_equal(_qualified_name(b), name):
                return {'block': b, 'collection': collection, 'kind': _SINGULAR[collection]}
    return None


def _block_names(project: Mapping[str, Any]) -> List[str]:
    return [_qualified_name(b) for c in COLLECTIONS for b in _nz(_get(project, c), []) if isinstance(b, Mapping)]


def _name_taken(project: Mapping[str, Any], name: str) -> bool:
    return name in set(_block_names(project))


def _systems(project: Mapping[str, Any]) -> List[str]:
    """``systems``: every sub-system, as dotted paths, shallowest first."""
    return system_paths(_nz(_get(project, 'systems'), []), _nz(_get(project, 'transports'), []),
                        (_nz(_get(b, 'system'), '') or '' for c in COLLECTIONS
                         for b in _nz(_get(project, c), []) if isinstance(b, Mapping)))


def _is_transport(project: Mapping[str, Any], path: str) -> bool:
    if not path:
        return False
    listed = _nz(_get(project, 'transports'), [])
    names = [p if isinstance(p, str) else _get(p, 'name') for p in listed]
    return path in [n for n in names if _truthy(n)]


def _index_lists(project: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """``indexLists``: the stored lists and the ones derived from them."""
    lists = _get(project, 'index_lists')
    return derive_block_lists(derive_elements(lists if isinstance(lists, list) else []), project)


def _validate_name(project: Mapping[str, Any], name: Any, system: str = '') -> Optional[str]:
    """``validateName``: what is wrong with a block's name in its sub-system, or
    ``None``: not an identifier, a reserved word, or a name already given to a
    block or a sub-system."""
    if not isinstance(name, str) or NAME_RE.fullmatch(name) is None:
        return 'Use letters, digits and underscore; do not start with a digit.'
    if name in RESERVED:
        return f"'{name}' is a reserved name."
    target = _qualify(system, name)
    if _name_taken(project, target):
        return (f"'{name}' is already used by another block in '{system}'." if system
                else f"'{name}' is already used by another block.")
    if target in _systems(project):
        return f"'{name}' is already used by a sub-system."
    return None


def _effective_value(block: Mapping[str, Any], key: str, index: Mapping[str, Any]) -> Any:
    """``effectiveValue``: the most specific entry that matches, else the block's own."""
    best: Any = _UNDEF
    best_score = -1
    for entry in _nz(_get(block, 'entries'), []):
        if not isinstance(entry, Mapping) or key not in entry:
            continue
        score = 0
        ok = True
        for lst, name in _entries(_get(entry, 'index')):
            if not _strictly_equal(_get(index, lst), name):
                ok = False
                break
            score += 1
        if ok and score > best_score:
            best_score = score
            best = entry[key]
    return best if best_score >= 0 else _get(block, key)


def _same_index(a: Any, b: Any) -> bool:
    ka, kb = _keys(a), _keys(b)
    if len(ka) != len(kb):
        return False
    return all(_strictly_equal(_get(a, k), _get(b, k)) for k in ka)


def _find_entry(block: Mapping[str, Any], index: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    for e in _nz(_get(block, 'entries'), []):
        if _same_index(_get(e, 'index'), index):
            return e
    return None


def _set_entry_value(project: Mapping[str, Any], block_name: str, index: Mapping[str, Any], key: str,
                     value: Any) -> Dict[str, Any]:
    """``setEntryValue``: the value at one index combination, the entry made if needed."""
    found = _find_block(project, block_name)
    if found is None:
        raise EditError(f"No block named '{block_name}'")
    block = found['block']
    lists = _nz(_get(block, 'index_lists'), [])
    for lst in _keys(index):
        if lst not in lists:
            raise EditError(f"'{block_name}' is not indexed by '{lst}'")
    if not isinstance(block.get('entries'), list):
        block['entries'] = []
    entry = _find_entry(block, index)
    if entry is None:
        entry = {'index': dict(index)}
        block['entries'].append(entry)
    entry[key] = value
    return entry


def _clear_entry_value(project: Mapping[str, Any], block_name: str, index: Mapping[str, Any], key: str) -> None:
    """``clearEntryValue``: the override gone, and the entry with it once empty."""
    found = _find_block(project, block_name)
    if found is None:
        raise EditError(f"No block named '{block_name}'")
    block = found['block']
    entry = _find_entry(block, index)
    if entry is None:
        return
    entry.pop(key, None)
    if not [k for k in _keys(entry) if k != 'index']:
        entries = block['entries']
        entries.pop(next(i for i, e in enumerate(entries) if e is entry))


def _next_system_name(project: Mapping[str, Any], parent: str, base: Any) -> str:
    base = 'Sub' if base is None else base
    existing = set(_systems(project)) | set(_block_names(project))
    local = _text(base)
    i = 1
    while _qualify(parent, local) in existing:
        local = f'{_text(base)}{i}'
        i += 1
    return local


def _add_system(project: Dict[str, Any], name: str, parent: str = '') -> str:
    """``addSystem``: a sub-system declared, before anything is in it."""
    if parent and parent not in _systems(project):
        raise EditError(f"No sub-system named '{parent}'")
    if parent and _is_transport(project, parent):
        raise EditError(f"'{parent}' is a transport, which is a chain of compartments and holds no sub-system of "
                        'its own.')
    if name is not None and not is_valid_path(name):
        raise EditError(f"'{name}' is not a valid name (letters, digits and underscore; must not start with a "
                        'digit)')
    if name is not None and _name_taken(project, _qualify(parent, name)):
        where = f"'{parent}'" if parent else 'this model'
        raise EditError(f"'{name}' is already used by a block in {where}. A sub-system and a block cannot share "
                        'a name.')
    path = _qualify(parent, _next_system_name(project, parent, name))
    if not isinstance(project.get('systems'), list):
        project['systems'] = _systems(project)
    project['systems'].append(path)
    return path


def _id_taken(project: Mapping[str, Any], name: str) -> bool:
    return _name_taken(project, name) or name in _systems(project)


def _unique_name(project: Mapping[str, Any], base: str, system: str = '') -> str:
    if not _id_taken(project, _qualify(system, base)):
        return base
    for i in range(1, 10000):
        if not _id_taken(project, _qualify(system, f'{base}{i}')):
            return f'{base}{i}'
    raise EditError(f"Could not find a free name based on '{base}'")


def _ensure(project: Dict[str, Any], collection: str) -> List[Any]:
    if not isinstance(project.get(collection), list):
        project[collection] = []
    return project[collection]


def _add_parameter(project: Dict[str, Any], name: Any, system: str = '') -> Dict[str, Any]:
    """``addParameter``, which checks nothing about the name it is given."""
    n = _unique_name(project, 'p', system) if name is None else name
    block: Dict[str, Any] = {'name': n, 'value': 0, 'unit': '', 'index_lists': []}
    if system:
        block['system'] = system
    _ensure(project, 'parameters').append(block)
    return block


def _add_lookup(project: Dict[str, Any], name: Any, system: str = '') -> Dict[str, Any]:
    """``addLookup``: a flat line at zero over the simulated span."""
    n = _unique_name(project, 'L', system) if name is None else name
    sim = _get(project, 'simulation')
    start = js_to_number(_nz(_get(sim, 'start_time'), 0))
    end = js_to_number(_nz(_get(sim, 'end_time'), 1))
    block: Dict[str, Any] = {
        'name': n, 'unit': '', 'interpolation': 'linear', 'cyclic': False,
        'points': [[start if _finite(start) else 0, 0],
                   [end if _finite(end) and end > start else start + 1, 0]],
        'index_lists': [],
    }
    if system:
        block['system'] = system
    _ensure(project, 'lookups').append(block)
    return block


# --- the model's data as rows ---------------------------------------------------------------

def _held(spec: Any) -> Any:
    """A spec the model can hold: a sample read out of a file becomes a plain
    list here, where the numbers enter the model."""
    if not _truthy(spec):
        return spec
    values = _get(spec, 'values')
    if not _is_view(values):
        return spec
    return {**spec, 'values': values.tolist() if hasattr(values, 'tolist') else list(values)}


def _count_sample(spec: Any, out: 'DataReport') -> None:
    """Counts a sample that went into the model -- only once it has."""
    n = _length(_get(spec, 'values'))
    if _get(spec, 'kind') == 'pg' and _truthy(n):
        out.samples += 1
        out.sample_values += n


def _spec_of(raw: Any) -> Any:
    """A spec, where a model file may hold Ecolego's text for one."""
    if not _truthy(raw):
        return None
    return parse_pdf(raw) if isinstance(raw, str) else raw


def id_for(block: Mapping[str, Any], index: Optional[Mapping[str, Any]] = None) -> str:
    """The dotted id of a block at an index combination (``idFor``): its
    qualified name, then the index in the block's own list order."""
    base = _qualified_name(block)
    lists = _nz(_get(block, 'index_lists'), [])
    if index is None or not lists:
        return base
    tail = [v for v in (_get(index, l) for l in lists) if not _nullish(v) and not (isinstance(v, str) and v == '')]
    return f"{base}.{'.'.join(js_string(v) for v in tail)}" if tail else base


def _combinations_of(project: Mapping[str, Any], block: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every index combination a block is given at, as ``{index, id}``: the
    block's own value first (an id of underscores) where it has one."""
    lists = _nz(_get(block, 'index_lists'), [])
    if not lists:
        return [{'index': {}, 'id': id_for(block)}]
    rows: List[Dict[str, Any]] = [{}]
    for name in lists:
        # Read as the file has it: a read of the data is not an edit of the
        # model, and a bare string is an index's name.
        lst = next((l for l in _index_lists(project) if _strictly_equal(_get(l, 'name'), name)), None)
        indices = _get(lst, 'indices')
        members = []
        for i in (indices if isinstance(indices, list) else []):
            if i is None:
                continue
            if isinstance(i, (Mapping, list, tuple)):
                enabled = _get(i, 'enabled')
                if is_js_boolean(enabled) and not enabled:
                    continue
                m = _get(i, 'name')
            else:
                m = i
            if _nullish(m) or (isinstance(m, str) and m == ''):
                continue
            members.append(m)
        # A list nobody has filled in yet gives the block one row at no index.
        if not members:
            return [{'index': {}, 'id': id_for(block)}]
        rows = [{**r, name: m} for r in rows for m in members]
    out = [{'index': index, 'id': id_for(block, index)} for index in rows]
    own = _nz(_get(block, 'value'), _get(block, 'points'))
    if not _nullish(own):
        out.insert(0, {'index': {}, 'id': f"{_qualified_name(block)}.{'.'.join(DEFAULT_SEGMENT for _ in lists)}",
                       'isDefault': True})
    return out


def _pdf_at(block: Mapping[str, Any], index: Mapping[str, Any]) -> Any:
    raw = _effective_value(block, 'pdf', index)
    if not _truthy(raw):
        return None
    if isinstance(raw, str):
        return parse_pdf(raw)
    return raw


def _at(p: Any, k: int) -> Any:
    """``p?.[k]``."""
    if isinstance(p, (list, tuple, str)) and k < len(p):
        return p[k]
    return _UNDEF


def collect(project: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The model's data as rows (``collect``): every parameter and every lookup
    table, distributed or not.

    Each row is ``{'id', 'unit', 'time', 'value', 'pdf', 'note', 'block',
    'index', 'kind'}``: ``block`` the block's own dictionary, ``index`` the
    combination (``{}`` for the block's own value), ``kind`` ``'parameter'`` or
    ``'lookup'``. A parameter's value is a number, or its text where it is an
    expression; its ``pdf`` is parsed where it is Ecolego's text. A lookup
    table is one row per point (and one with no time for a table with none).
    Like the application's, this normalises the indices of the index lists it
    reads, in place.
    """
    out: List[Dict[str, Any]] = []
    for kind in CARRIES:
        for block in _nz(_get(project, kind), []):
            unit = _nz(_get(block, 'unit'), '')
            note = _nz(_get(block, 'comment'), '')
            for combo in _combinations_of(project, block):
                index, rid = combo['index'], combo['id']
                if kind == 'lookups':
                    points = _nz(_effective_value(block, 'points', index), [])
                    if not _truthy(_length(points)):
                        out.append({'id': rid, 'unit': unit, 'time': None, 'value': None, 'pdf': None,
                                    'note': note, 'block': block, 'index': index, 'kind': 'lookup'})
                        continue
                    for p in points:
                        out.append({
                            'id': rid, 'unit': unit, 'time': _num(_at(p, 0)), 'value': _num(_at(p, 1)),
                            'pdf': _spec_of(_nz(_at(p, 2), None)),
                            'note': note, 'block': block, 'index': index, 'kind': 'lookup',
                        })
                    continue
                out.append({
                    'id': rid, 'unit': unit, 'time': None,
                    'value': _value(_effective_value(block, 'value', index)),
                    'pdf': _pdf_at(block, index),
                    'note': note, 'block': block, 'index': index, 'kind': 'parameter',
                })
    return out


# --- reading an id back ---------------------------------------------------------------------

def legal_name(segment: Any) -> str:
    """A path segment as a block name can be (``legalName``): ``9XY`` becomes
    ``_9XY``, and every character that is not a letter, digit or underscore an
    underscore (two for a character beyond the Basic Multilingual Plane, which
    JavaScript counts as two)."""
    s = '' if _nullish(segment) else js_string(segment)
    if _WORD.fullmatch(s):
        return s
    body = ''.join(c if (c.isascii() and (c.isalnum() or c == '_')) else ('__' if ord(c) > 0xFFFF else '_')
                   for c in s)
    return body if re.match(r'[A-Za-z_]', body) else f'_{body}'


def _match(project: Mapping[str, Any], parts: List[str]) -> Optional[Dict[str, Any]]:
    for k in range(len(parts), 0, -1):
        name = '.'.join(parts[:k])
        found = _find_block(project, name)
        if found is None or found['collection'] not in CARRIES:
            continue
        rest = parts[k:]
        lists = _nz(_get(found['block'], 'index_lists'), [])
        # More segments than the block has index lists is not this block.
        if len(rest) > len(lists):
            continue
        index: Dict[str, Any] = {}
        for i, v in enumerate(rest):
            if v != DEFAULT_SEGMENT:
                index[lists[i]] = v
        return {'block': found['block'], 'kind': found['kind'], 'name': name, 'index': index, 'extra': rest}
    return None


def resolve(project: Mapping[str, Any], rid: Any) -> Optional[Dict[str, Any]]:
    """Which block and index an id names, asking the model (``resolve``):
    ``{'block', 'kind', 'name', 'index', 'extra'}``, or ``None``. The id as
    written is tried first, then as :func:`legal_name` would have made it."""
    raw = [s.strip(JS_WHITESPACE) for s in ('' if _nullish(rid) else js_string(rid)).split('.')]
    raw = [s for s in raw if s]
    if not raw:
        return None
    legal = [legal_name(s) for s in raw]
    hit = _match(project, raw)
    if hit is not None:
        return hit
    return None if '.'.join(legal) == '.'.join(raw) else _match(project, legal)


# --- writing rows into the model ------------------------------------------------------------

class DataReport:
    """What an import did (the application's report object): counts, one line
    per id that matched nothing (``unmatched``) or could not be used
    (``problems``), and the names that had to change (``renamed``, in the order
    they were met)."""

    def __init__(self) -> None:
        self.values = 0
        self.pdfs = 0
        self.tables = 0
        self.created = 0
        self.samples = 0
        self.sample_values = 0
        self.unmatched: List[str] = []
        self.problems: List[str] = []
        self.renamed: Dict[str, str] = {}

    def say(self, kind: str, rid: Any, why: str) -> None:
        line = f'{_text(rid)}: {why}'
        if kind == 'unmatched':
            self.unmatched.append(line)
        else:
            self.problems.append(line)

    def __str__(self) -> str:
        return describe(self)

    def as_dict(self) -> Dict[str, Any]:
        """The report under the application's names (``sampleValues``)."""
        return {
            'values': self.values, 'pdfs': self.pdfs, 'tables': self.tables, 'created': self.created,
            'samples': self.samples, 'sampleValues': self.sample_values,
            'unmatched': list(self.unmatched), 'problems': list(self.problems), 'renamed': dict(self.renamed),
        }

    def __repr__(self) -> str:
        return f'<DataReport {describe(self)!r}>'


def _time_order(a: Mapping[str, Any], b: Mapping[str, Any]) -> int:
    ta, tb = _get(a, 'time'), _get(b, 'time')
    x = (-math.inf if _nullish(ta) else js_to_number(ta)) - (-math.inf if _nullish(tb) else js_to_number(tb))
    if x != x:
        return 0
    return -1 if x < 0 else (1 if x > 0 else 0)


def _by_id(rows: Iterable[Any]) -> Dict[Any, List[Mapping[str, Any]]]:
    """Rows grouped by id, in the order the ids first appear, each group in time order."""
    out: Dict[Any, List[Mapping[str, Any]]] = {}
    for r in rows:
        if not isinstance(r, Mapping) or not _truthy(_get(r, 'id')):
            continue
        out.setdefault(r['id'], []).append(r)
    for group in out.values():
        group.sort(key=cmp_to_key(_time_order))
    return out


def apply(project: Dict[str, Any], rows: Iterable[Mapping[str, Any]], opts: Optional[Mapping[str, Any]] = None, *,
          create: Optional[bool] = None) -> DataReport:
    """Writes rows into the model, in place (``apply``), and says what it did.

    An id nothing matches is a line in the report, or -- with ``create=True``
    (or ``opts={'create': True}``) -- a new block: a lookup table when a row
    gives it a time, a parameter otherwise. A parameter's value is written as
    text (``'0.5'``), a distribution where it is complete; ``pdf=None`` on a row
    removes one, and a row with no ``pdf`` key leaves it alone. A lookup
    table's points are replaced by the rows' times and values, in time order.
    """
    out = DataReport()
    if create is None:
        create = _get(opts or {}, 'create') is True
    else:
        create = create is True
    for rid, group in _by_id(rows).items():
        hit = resolve(project, rid)
        if hit is None:
            if not create:
                out.say('unmatched', rid, 'nothing in this model is called that')
                continue
            hit = _make(project, rid, group, out)
            if hit is None:
                continue
        timed = [r for r in group if _present(_get(r, 'time'))]
        if hit['kind'] == 'lookup' or (timed and hit['kind'] != 'parameter'):
            _write_table(project, hit, timed if timed else group, out, rid)
        elif timed:
            out.say('problems', rid, f"is a {hit['kind']}, and the file gives it {len(timed)} times — only a lookup "
                                     'table has points over time')
        else:
            _write_value(project, hit, group[0], out, rid)
    return out


def _unwritable(project: Mapping[str, Any], row: Any) -> bool:
    """Whether a row's value is one a parameter cannot hold: a word that is
    neither a number nor the name of a block."""
    value = _get(row, 'value')
    return (isinstance(value, str) and value.strip(JS_WHITESPACE) != '' and _num(value) is None
            and _find_block(project, value) is None)


def _make(project: Dict[str, Any], rid: Any, group: List[Mapping[str, Any]],
          out: DataReport) -> Optional[Dict[str, Any]]:
    """A block for an id nothing matched. The last segment is the name.

    Refused, and said, where the block could not be what the rows ask for: an
    id with no name in it, a name the model already gives to a block or a
    sub-system, a reserved word, or rows that would write nothing into it --
    before anything is made, so a refusal leaves nothing behind.
    """
    if not isinstance(rid, str):
        raise TypeError('id.split is not a function')
    raw = [p for p in rid.split('.') if p]
    if not raw:
        out.say('problems', rid, 'could not be created — there is no name in it')
        return None
    parts = [legal_name(p) for p in raw]
    name = parts[-1]
    system = '.'.join(parts[:-1])
    timed = [r for r in group if _present(_get(r, 'time'))]
    if timed:
        why = _table_points(timed)[1]
        if why is not None:
            out.say('problems', rid, why)
            return None
    elif _unwritable(project, group[0]):
        out.say('problems', rid, f"'{_text(_get(group[0], 'value'))}' is not a number, so there is nothing here to "
                                 'make a parameter out of')
        return None
    clash = _validate_name(project, name, system)
    if clash:
        out.say('problems', rid, f'could not be created — {clash}')
        return None
    try:
        known = set(_systems(project))
        for k in range(1, len(parts)):
            path = '.'.join(parts[:k])
            if path in known:
                continue
            _add_system(project, parts[k - 1], '.'.join(parts[:k - 1]))
            known.add(path)
        made = _add_lookup(project, name, system) if timed else _add_parameter(project, name, system)
        if not made:
            raise DataTableError('nothing was made')
        # A created block carries no index lists, so the id reads back whole.
        made['index_lists'] = []
        unit = _get(group[0], 'unit')
        if _truthy(unit):
            made['unit'] = unit
        for was, now in zip(raw, parts):
            if was != now:
                out.renamed[was] = now
        out.created += 1
        return {'block': made, 'kind': 'lookup' if timed else 'parameter', 'name': rid, 'index': {}, 'extra': []}
    except Exception as e:  # noqa: BLE001 -- the application reports whatever went wrong
        out.say('problems', rid, f'could not be created — {_message(e)}')
        return None


def _write_value(project: Dict[str, Any], hit: Mapping[str, Any], row: Mapping[str, Any], out: DataReport,
                 rid: Any) -> None:
    """Sets a parameter's value and distribution at one index. A row's unit is
    its block's, whichever index the row is for."""
    block, index = hit['block'], hit['index']
    has = len(_keys(index)) > 0

    def set_value(key: str, value: Any) -> None:
        if has:
            _set_entry_value(project, _qualified_name(block), index, key, value)
        else:
            block[key] = value

    def clear(key: str) -> None:
        if has:
            _clear_entry_value(project, _qualified_name(block), index, key)
        else:
            block.pop(key, None)

    try:
        value = _get(row, 'value')
        given = None if isinstance(value, str) and value.strip(JS_WHITESPACE) == '' else value
        # A value has to be a number or an expression the model can evaluate.
        if _unwritable(project, row):
            out.say('problems', rid, f"'{value}' is not a number and names no block — the value was left alone")
        elif not _nullish(given):
            set_value('value', js_string(given))
            out.values += 1
        unit = _get(row, 'unit')
        if _truthy(unit):
            block['unit'] = unit
        pdf = _get(row, 'pdf')
        if pdf is _UNDEF:
            return
        if _truthy(pdf) and usable(pdf):
            spec = _held(pdf)
            set_value('pdf', spec)
            out.pdfs += 1
            _count_sample(spec, out)
        elif pdf is None:
            clear('pdf')
        elif _truthy(pdf):
            kind = _get(pdf, 'kind')
            known = isinstance(kind, str) and kind in PDF_KINDS
            out.say('problems', rid, 'the distribution is not filled in — it was left alone' if known
                    else f"'{_text(kind)}' is not a kind of distribution — it was left alone")
    except Exception as e:  # noqa: BLE001
        out.say('problems', rid, _message(e))


def _table_points(rows: List[Mapping[str, Any]]) -> tuple:
    """A table's points from its rows, and why there are none: every row with
    both a time and a value, and no two at one time."""
    points = [([r['time'], r['value'], _held(r['pdf'])] if _truthy(_get(r, 'pdf')) else [r['time'], r['value']])
              for r in rows if _present(_get(r, 'time')) and _present(_get(r, 'value'))]
    if not points:
        return None, 'no point in the file has both a time and a value'
    for i in range(1, len(points)):
        if _strictly_equal(points[i][0], points[i - 1][0]):
            return None, f'two rows are both at time {js_string(points[i][0])}'
    return points, None


def _write_table(project: Dict[str, Any], hit: Mapping[str, Any], rows: List[Mapping[str, Any]], out: DataReport,
                 rid: Any) -> None:
    """Replaces a lookup table's points."""
    block, index = hit['block'], hit['index']
    points, why = _table_points(rows)
    if why is not None:
        out.say('problems', rid, why)
        return
    try:
        if _keys(index):
            _set_entry_value(project, _qualified_name(block), index, 'points', points)
        else:
            block['points'] = points
        unit = _get(rows[0], 'unit')
        if _truthy(unit):
            block['unit'] = unit
        out.tables += 1
        # A point's own spread counts as a distribution read.
        out.pdfs += sum(1 for pt in points if len(pt) > 2)
        for pt in points:
            if len(pt) > 2:
                _count_sample(pt[2], out)
    except Exception as e:  # noqa: BLE001
        out.say('problems', rid, _message(e))


def _report_value(rep: Any, py_name: str, js_name: str) -> Any:
    if isinstance(rep, Mapping):
        return rep.get(js_name, rep.get(py_name))
    return getattr(rep, py_name, getattr(rep, js_name, None))


def describe(rep: Any) -> str:
    """What an import did, in one paragraph (``describe``); counts are written as
    an en-US page writes them. Takes a :class:`DataReport` or its
    :meth:`DataReport.as_dict`."""
    if not _truthy(rep):
        return ''

    def get(py_name: str, js_name: Optional[str] = None) -> Any:
        return _report_value(rep, py_name, js_name or py_name)

    def plural(n: Any) -> str:
        return '' if n == 1 and not is_js_boolean(n) else 's'

    bits = []
    values, tables, pdfs = get('values'), get('tables'), get('pdfs')
    samples, sample_values, created = get('samples'), get('sample_values', 'sampleValues'), get('created')
    if _truthy(values):
        bits.append(f'{_locale(values)} value{plural(values)}')
    if _truthy(tables):
        bits.append(f'{_locale(tables)} lookup table{plural(tables)}')
    if _truthy(pdfs):
        bits.append(f'{_locale(pdfs)} distribution{plural(pdfs)}')
    if _truthy(samples):
        bits.append(f'{_locale(samples)} of them raw samples ({_locale(sample_values)} values)')
    if _truthy(created):
        bits.append(f'{_locale(created)} block{plural(created)} created')
    head = ', '.join(bits) if bits else 'nothing'
    unmatched = get('unmatched') or []
    problems = get('problems') or []
    left = (f' {_locale(len(unmatched))} id{plural(len(unmatched))} matched nothing in this model.'
            if unmatched else '')
    bad = f' {_locale(len(problems))} could not be used.' if problems else ''
    renamed = get('renamed') or {}
    pairs = list(renamed.items())
    said = (f" {len(pairs)} name{plural(len(pairs))} could not be kept as written ("
            f"{', '.join(f'{a} → {b}' for a, b in pairs[:3])}{', …' if len(pairs) > 3 else ''})."
            if pairs else '')
    return f'Read {head}.{left}{bad}{said}'
