"""A run's results as an HDF5 tree, as Kompartment writes one.

A port of the application's ``src/io/resultfile.js``: the result-browser
convention (Ecolego's own shape) laid over :mod:`kompartment.io.hdf5`, so a
file written from Python is, for the same numbers, the file the application
writes, to the byte::

    import kompartment as kp
    from kompartment.io import resultfile

    res = kp.load('biosphere.json').run()
    resultfile.write_results_hdf5(res, 'biosphere.h5')

The tree::

    /time                        the output grid, once, with its unit
    /IndexLists/Radionuclides    the members of each index list, by name
    /Soil/                       a block, as a group, when it is indexed
         @IndexLists = ['Radionuclides']
         @time_dependent = 'TRUE'
         Cs-137                  one series per member
    /NearField/Flux              a block that is not indexed, as a dataset

Two dimensions nest: a block indexed by areas and nuclides is
``/Dose/<area>/<nuclide>``, the nuclide the leaf and each ``<area>`` a group
carrying the ``IndexLists`` that gets the nuclides drawn together. A value
that cannot change over the run (``timeDependent`` false on its descriptor)
is one value -- one per realisation in a file of realisations -- and says
``time_dependent = 'FALSE'``.

:func:`result_tree` is the application's ``resultTree`` with its arguments as
keywords; :func:`results_tree` and :func:`write_results_hdf5` take a
:class:`kompartment.engine.Results` and do what the page's *Export to HDF5*
does with it.
"""

from __future__ import annotations

import datetime as _dt
import math
import numbers
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .csv import JS_WHITESPACE, is_js_boolean, js_string, js_to_number
from .hdf5 import F32, F64, STR, Group, dataset, group, put, write_hdf5

__all__ = ['description_html', 'result_tree', 'results_tree', 'write_results_hdf5', 'probabilistic_tree',
           'write_probabilistic_hdf5', 'scenarios_tree', 'write_scenarios_hdf5']


class _Undefined:
    """JavaScript's ``undefined``: a property that is not there, as distinct from ``null``."""

    def __repr__(self) -> str:
        return 'undefined'

    def __bool__(self) -> bool:
        return False


_UNDEF = _Undefined()


def _get(obj: Any, key: str) -> Any:
    """``obj[key]`` for a dictionary, and ``undefined`` for anything else."""
    if isinstance(obj, Mapping):
        return obj.get(key, _UNDEF)
    return _UNDEF


def _nullish(v: Any) -> bool:
    return v is None or v is _UNDEF


def _nz(v: Any, default: Any) -> Any:
    """``v ?? default``."""
    return default if _nullish(v) else v


def _truthy(v: Any) -> bool:
    """JavaScript's ToBoolean: an object or array is true however empty; 0, NaN and '' are not."""
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
    """``String(v)``, with ``undefined`` written as JavaScript writes it."""
    return 'undefined' if v is _UNDEF else js_string(v)


def _link_name(s: Any) -> str:
    """What a name has to be before it can be a link (``linkName``): a slash is
    the one character HDF5 keeps for itself, and is replaced by U+2044."""
    out = ('' if _nullish(s) else js_string(s)).replace('/', '⁄').strip(JS_WHITESPACE)
    return '_' if out in ('', '.', '..') else out


def _place(root: Group, path: List[str], node: Any) -> Any:
    """Puts ``node`` at ``path``, numbering the last name past one already taken."""
    try:
        return put(root, path, node)
    except Exception as first:  # noqa: BLE001 -- the JavaScript catches whatever `put` throws
        head, last = path[:-1], path[-1]
        for n in range(2, 1000):
            try:
                return put(root, [*head, f'{last} ({n})'], node)
            except Exception:  # noqa: BLE001 -- keep counting
                pass
        raise first


def _strictly_equal(a: Any, b: Any) -> bool:
    """``a === b`` for the values a descriptor holds."""
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a == b
    if is_js_boolean(a) or is_js_boolean(b):
        return is_js_boolean(a) and is_js_boolean(b) and bool(a) == bool(b)
    if isinstance(a, numbers.Real) and isinstance(b, numbers.Real):
        return a == b
    return a is b


def _index_of(values: Sequence[Any], wanted: Any) -> int:
    """``values.indexOf(wanted)``: strict equality, so NaN is never found."""
    for i, v in enumerate(values):
        if _strictly_equal(v, wanted):
            return i
    return -1


def _path_of(o: Mapping[str, Any]) -> Tuple[List[str], Optional[Any]]:
    """Where one series goes, and which dimension its group carries (``pathOf``)."""
    block = _get(o, 'block')
    if _nullish(block):
        block = _get(o, 'label')
    if _nullish(block):
        block = 'value'
    parts = [_link_name(p) for p in js_string(block).split('.')]
    dims = _get(o, 'dims')
    dims = [] if _nullish(dims) else list(dims)
    index = _get(o, 'index')
    index = [] if _nullish(index) else list(index)
    if not dims or not index:
        return parts, None
    # The nuclide is the leaf when there is one; otherwise the last dimension.
    leaf = len(index) - 1
    nuclide = _get(o, 'nuclide')
    if not _nullish(nuclide):
        at = _index_of(index, nuclide)
        if at >= 0:
            leaf = at
    rest = [_link_name(v) for i, v in enumerate(index) if i != leaf]
    leaf_dim = dims[leaf] if leaf < len(dims) and dims[leaf] is not None else None
    return [*parts, *rest, _link_name(index[leaf])], leaf_dim


def description_html(text: Any) -> Optional[str]:
    """The model's description as the markup the result browser renders
    (``descriptionHTML``), or ``None`` when there is nothing to say.

    The text is escaped first -- the description is plain text, so a ``<`` in
    it is a ``<`` somebody meant -- then blank lines become paragraphs and
    single newlines breaks.
    """
    clean = re.sub(r'\r\n?', '\n', '' if _nullish(text) else js_string(text)).strip(JS_WHITESPACE)
    if not clean:
        return None

    def escape(s: str) -> str:
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    return ''.join('<p>' + escape(para).replace('\n', '<br>') + '</p>' for para in re.split(r'\n{2,}', clean))


DateLike = Union[None, _dt.datetime, _dt.date, int, float]


def _local_time(when: DateLike) -> _dt.datetime:
    """A time as the page's clock reads it: local. ``None`` is now, a number is
    seconds since the epoch, an aware ``datetime`` is converted to local time."""
    if when is None:
        return _dt.datetime.now()
    if isinstance(when, _dt.datetime):
        return when.astimezone() if when.tzinfo is not None else when
    if isinstance(when, _dt.date):
        return _dt.datetime(when.year, when.month, when.day)
    return _dt.datetime.fromtimestamp(float(when))


def _stamp(when: DateLike) -> str:
    """A time, an hour and a minute, in the shape Ecolego's own files use."""
    d = _local_time(when)
    return f'{d.year}-{d.month:02d}-{d.day:02d} {d.hour:02d}:{d.minute:02d}:{d.second:02d}'


def _project_dict(project: Any) -> Any:
    """The model as a dictionary: a :class:`kompartment.Model`'s own, an engine
    ``Project``'s file, or the dictionary given."""
    if project is None:
        return {}
    if isinstance(project, Mapping):
        return project
    raw = getattr(project, 'raw', None)
    if isinstance(raw, Mapping):
        return raw
    raw = getattr(project, '_raw', None)
    if isinstance(raw, Mapping):
        return raw
    return {'name': getattr(project, 'name', None), 'description': getattr(project, 'description', None),
            'simulation': getattr(project, 'simulation', None) or {}}


def _first(values: Any) -> float:
    """``column(i)[0]`` as a double: NaN where there is none."""
    try:
        n = len(values)
    except TypeError:
        n = 0
    if not n:
        return math.nan
    v = values[0]
    return js_to_number(v.item() if hasattr(v, 'item') else v)


def _length(values: Any) -> int:
    if hasattr(values, 'size') and not isinstance(values, (list, tuple)):
        try:
            return int(values.size)
        except TypeError:
            pass
    return len(values)


def _realisation_of(of: Any) -> Any:
    """``sample.of === 'mean' ? 'mean' : Number(sample.of)``."""
    return 'mean' if isinstance(of, str) and of == 'mean' else js_to_number(of)


def _matrix_of(realisations: Any, i: int) -> Any:
    fn = _get(realisations, 'matrix_for')
    if fn is _UNDEF:
        fn = _get(realisations, 'matrixFor')
    if fn is _UNDEF:
        fn = getattr(realisations, 'matrix_for', None) or getattr(realisations, 'matrixFor', None)
    return fn(i)


def _attr_of(obj: Any, key: str) -> Any:
    """``obj.key`` for a dictionary or an object."""
    v = _get(obj, key)
    if v is _UNDEF and not isinstance(obj, Mapping):
        v = getattr(obj, key, _UNDEF)
    return v


def result_tree(*, t: Any, outputs: Sequence[Mapping[str, Any]], column: Callable[[int], Any],
                which: Sequence[int], project: Any = None, index_lists: Optional[Sequence[Any]] = None,
                now: DateLike = None, realisations: Any = None, sample: Any = None) -> Group:
    """The tree for a run (``resultTree``), ready for :func:`kompartment.io.hdf5.write_hdf5`.

    ``t`` is the output times; ``outputs`` the series descriptors (``label``,
    ``block``, ``kind``, ``nuclide``, ``index``, ``dims``, ``unit``,
    ``timeDependent``) in order; ``column(i)`` one series' values; ``which``
    the outputs to write, by index. ``project`` is the model, for its name,
    description and settings (a dictionary, a :class:`kompartment.Model` or an
    engine ``Project``); ``index_lists`` its index lists, each a dictionary
    with ``name`` and ``indices`` (or the shorthand ``elements``). ``now`` is
    the ``created_time`` (local time; a ``datetime``, a ``date`` or seconds
    since the epoch; ``None`` is now).

    ``realisations`` -- ``{'iterations': n, 'matrix_for': fn}`` (``matrixFor``
    is read too) -- writes every run of a probabilistic result: ``fn(i)``
    returns ``times x n`` values for a series, flat and time-major (float32),
    ``n`` of them for one that cannot change over the run, or ``None`` for a
    series that was not part of the run. ``sample`` -- ``{'iterations': n,
    'of': 'mean' | k}`` -- says that the curves are the mean of a
    probabilistic run or its ``k``-th realisation.
    """
    project = _project_dict(project)
    sim = _nz(_get(project, 'simulation'), {})
    time_unit = _nz(_get(sim, 'time_unit'), 'year')
    created = _stamp(now)
    iterations = _attr_of(realisations, 'iterations') if realisations is not None else _UNDEF
    name = _get(project, 'name')
    attrs: Dict[str, Any] = {
        'model': 'model' if _nullish(name) else name,
        'created_time': created,
        'source': 'Kompartment',
        'time_unit': time_unit,
        'start_time': js_to_number(_nz(_get(sim, 'start_time'), 0)),
        'end_time': js_to_number(_nz(_get(sim, 'end_time'), 0)),
        'solver': js_string(_nz(_get(sim, 'solver'), '')),
        'series': len(which),
        'probabilistic': _truthy(realisations),
    }
    if _truthy(realisations):
        attrs['n_iter'] = None if iterations is _UNDEF else iterations
    if _truthy(sample):
        n = _attr_of(sample, 'iterations')
        attrs['n_iter'] = None if n is _UNDEF else n
        attrs['realisation'] = _realisation_of(_attr_of(sample, 'of'))
    attrs['Information'] = description_html(_get(project, 'description'))
    root = group(attrs)

    # `probabilistic` on /time is whether the *time axis* is a matrix, which it
    # never is: every realisation is reported on the one output grid.
    put(root, ['time'], dataset(t, F64, {
        'unit': time_unit, 'created_time': created, 'name': 'time', 'probabilistic': False,
    }))

    # The index lists, whole: the members of a dimension and their order, and
    # only the members that are switched on. An index may be the bare string
    # a file wrote it as, and that string is its name.
    for lst in index_lists or []:
        indices = _get(lst, 'indices')
        if _truthy(indices):
            names: List[Any] = []
            for i in indices:
                if i is None:
                    continue
                if isinstance(i, (Mapping, list, tuple)):
                    enabled = _get(i, 'enabled')
                    if is_js_boolean(enabled) and not enabled:
                        continue
                    names.append(_get(i, 'name'))
                else:
                    names.append(i)
        else:
            elements = _get(lst, 'elements')
            names = list([] if _nullish(elements) else elements)
        members = [_text(e) for e in names if not _nullish(e)]
        if not members:
            continue
        list_name = _get(lst, 'name')
        _place(root, ['IndexLists', _link_name(None if list_name is _UNDEF else list_name)],
               dataset(members, STR, {'name': None if list_name is _UNDEF else list_name,
                                      'members': len(members)}))

    n_iter = 0 if _nullish(iterations) else iterations
    for i in which:
        o = outputs[i]
        path, leaf_dim = _path_of(o)
        # Every run of it, where there is one, as float32: a Monte Carlo sample
        # does not need the digits, and Ecolego writes its own series so.
        matrix = _matrix_of(realisations, i) if _truthy(realisations) else None
        if matrix is _UNDEF:
            matrix = None
        still = _get(o, 'timeDependent') is False
        if matrix is not None:
            values = matrix[:int(n_iter)] if still and _length(matrix) > js_to_number(n_iter) else matrix
        else:
            values = [_first(column(i))] if still else column(i)
        unit = _get(o, 'unit')
        unit = unit if _truthy(unit) else ''
        node_attrs: Dict[str, Any] = {
            'unit': unit,
            'time_dependent': not still,
            'probabilistic': matrix is not None,
        }
        if matrix is not None:
            node_attrs['n_iter'] = None if iterations is _UNDEF else iterations
        if _truthy(sample) and matrix is None:
            n = _attr_of(sample, 'iterations')
            node_attrs['n_iter'] = None if n is _UNDEF else n
            node_attrs['realisation'] = _realisation_of(_attr_of(sample, 'of'))
        label = _get(o, 'label')
        node_attrs['kind'] = js_string(_nz(_get(o, 'kind'), ''))
        node_attrs['block'] = js_string(_nz(_get(o, 'block'), ''))
        node_attrs['name'] = None if label is _UNDEF else label
        # What the browser writes as the column heading of this series.
        node_attrs['index'] = [math.nan if label is _UNDEF else label]
        node_attrs['created_time'] = created
        dims = [len(t), iterations] if matrix is not None and not still else None
        node = dataset(values, F32 if matrix is not None else F64, node_attrs, dims)
        _place(root, path, node)
        if not _truthy(leaf_dim):
            continue
        holder: Any = root
        for part in path[:-1]:
            holder = holder.children.get(part) if isinstance(holder, Group) else None
        if not isinstance(holder, Group):
            continue
        # Said once per group, the same way every time, so two series of one
        # block cannot disagree about what the group is.
        before = holder.attrs if holder.attrs is not None else {}
        holder.attrs = {
            **before,
            'IndexLists': [leaf_dim],
            'time_dependent': not still,
            'probabilistic': matrix is not None,
            'unit': unit if ('unit' not in before or before['unit'] == unit) else '',
            'block': js_string(_nz(_get(o, 'block'), '')),
        }
    return root


# --- from a Results ---------------------------------------------------------------------

def _which_of(outputs: Sequence[Mapping[str, Any]], which: Optional[Sequence[Any]]) -> List[int]:
    if which is None:
        return list(range(len(outputs)))
    out = []
    for w in which:
        if isinstance(w, str):
            k = next((j for j, o in enumerate(outputs) if o.get('label') == w), None)
            if k is None:
                raise KeyError(f"No output labelled '{w}'")
            out.append(k)
        elif isinstance(w, Mapping):
            k = next((j for j, o in enumerate(outputs) if o is w or o.get('label') == w.get('label')), None)
            if k is None:
                raise KeyError(f"No output labelled '{w.get('label')}'")
            out.append(k)
        else:
            out.append(int(w))
    return out


def results_tree(results: Any, which: Optional[Sequence[Any]] = None, *, project: Any = None,
                 index_lists: Optional[Sequence[Any]] = None, now: DateLike = None,
                 column: Optional[Callable[[int], Any]] = None, realisations: Any = None,
                 sample: Any = None) -> Group:
    """The tree of a run, as the page's *Export to HDF5* builds it.

    ``results`` is a :class:`kompartment.engine.Results`; ``which`` the series
    to write -- indices into ``results.outputs()``, labels, or descriptors --
    every one of them by default. ``project`` is the model the file names
    (a dictionary or a :class:`kompartment.Model`): by default the model the
    run was built from. ``index_lists`` defaults to the index lists the run
    was built with. ``column(i)`` overrides where a series' values come from
    (the mean of a probabilistic run, say); by default they are the run's own,
    worked out in one pass. ``now``, ``realisations`` and ``sample`` are as in
    :func:`result_tree`.
    """
    outputs = results.outputs()
    chosen = _which_of(outputs, which)
    if project is None:
        project = _project_dict(results.project)
    if index_lists is None:
        index_lists = getattr(results.project, 'index_lists', None) or []
    if column is None:
        wanted = list(dict.fromkeys(chosen))
        cache: Dict[int, Any] = {}
        if wanted:
            for k, values in zip(wanted, results.series_many([outputs[k] for k in wanted])):
                cache[k] = values

        def column(i: int) -> Any:
            if i not in cache:
                cache[i] = results.series(outputs[i])
            return cache[i]

    return result_tree(t=results.t, outputs=outputs, column=column, which=chosen, project=project,
                       index_lists=index_lists, now=now, realisations=realisations, sample=sample)


def write_results_hdf5(results: Any, path: Union[None, str, Path] = None,
                       which: Optional[Sequence[Any]] = None, **options: Any) -> bytes:
    """A run as an HDF5 result file's bytes, written to ``path`` too when one is
    given. The keyword arguments are :func:`results_tree`'s."""
    data = write_hdf5(results_tree(results, which, **options))
    if path is not None:
        Path(path).write_bytes(data)
    return data


# --- a probabilistic run ----------------------------------------------------------------

def _index_lists_of(project: Any) -> List[Any]:
    """The index lists the application hands a result file for a model: the
    stored ones and those derived from them."""
    if project is None:
        return []
    lists = getattr(project, 'index_lists', None)
    if isinstance(lists, list) and not isinstance(project, Mapping):  # an engine Project
        return lists
    raw = _project_dict(project)
    from ..indexlists import derive_block_lists, derive_elements
    stored = raw.get('index_lists') if isinstance(raw, Mapping) else None
    return derive_block_lists(derive_elements(stored if isinstance(stored, list) else []), raw)


def _finite_mean(rows: Any) -> Any:
    """The mean of each column over the rows that are finite there, NaN where
    none is (the application's ``meanOf``)."""
    import numpy as np
    m = np.asarray(rows, dtype=np.float64)
    finite = np.isfinite(m)
    count = finite.sum(axis=0)
    total = np.where(finite, m, 0.0).sum(axis=0)
    with np.errstate(invalid='ignore', divide='ignore'):
        return np.where(count > 0, total / np.maximum(count, 1), math.nan)


def probabilistic_tree(prob: Any, want: Any = 'all', *, which: Optional[Sequence[Any]] = None, project: Any = None,
                       index_lists: Optional[Sequence[Any]] = None, now: DateLike = None,
                       inputs: bool = True) -> Group:
    """A probabilistic run as a result file's tree, as the page's
    *Save → Realisations* writes it.

    ``prob`` is a :class:`kompartment.engine.probabilistic.ProbabilisticResults`.
    ``want`` is what of the sample: ``'all'`` -- every realisation, one row per
    output time and one column per realisation, as float32, or one value per
    realisation for a series that cannot change over the run -- ``'mean'``, the
    mean at every time of the realisations that ran, or a realisation by its
    number, from 1 (clamped to the ones there are). The file says which, so it
    is not taken for a deterministic run.

    ``which`` picks the kept series (labels, indices or descriptors), every one
    by default; with ``inputs`` the varied parameters come too, one value per
    realisation (NaN for one that did not run). ``project`` is the model the
    file names (a dictionary, a :class:`kompartment.Model` or an engine
    ``Project``) and gives the index lists unless ``index_lists`` does. The
    times are the sample's own grid -- the one every realisation was reported
    on -- whatever the model's own runs are reported on.
    """
    import numpy as np
    t = np.asarray(prob.t, dtype=np.float64)
    times = t.size
    series: List[Dict[str, Any]] = [dict(o) for o in prob.outputs]
    source: List[Tuple[str, int]] = [('kept', w) for w in range(len(series))]
    ran = np.asarray(prob.ran, dtype=bool) if getattr(prob, 'ran', None) is not None else None
    if inputs:
        taken = {o.get('label') for o in series}
        for inp in getattr(prob, 'inputs', None) or []:
            o = dict(inp['output'])
            if o.get('label') in taken:
                continue
            series.append(o)
            source.append(('input', int(inp['k'])))
    n = int(np.asarray(prob.values[0]).shape[0]) if len(prob.values) else (
        int(ran.size) if ran is not None else int(prob.iterations))
    chosen = _which_of(series, which)

    def draws(j: int) -> Any:
        col = np.asarray(prob.samples[j], dtype=np.float64).copy()
        if ran is not None and ran.size == col.size:
            col[~ran] = math.nan
        return col

    def rows(k: int) -> Any:
        kind, j = source[k]
        return np.asarray(prob.values[j]) if kind == 'kept' else draws(j)[:, None]

    def still(k: int) -> bool:
        return source[k][0] == 'input' or series[k].get('timeDependent') is False

    realisations = None
    sample = None
    if want == 'all':
        def matrix_for(k: int) -> Any:
            m = rows(k)
            if still(k):
                return np.asarray(m[:, 0], dtype=np.float32)
            return np.asarray(m, dtype=np.float32).T.ravel()

        def column(k: int) -> Any:
            return np.full(times, math.nan)

        realisations = {'iterations': n, 'matrix_for': matrix_for}
    elif want == 'mean':
        def column(k: int) -> Any:
            m = rows(k)
            mean = _finite_mean(m)
            return np.full(times, mean[0]) if m.shape[1] == 1 else mean

        sample = {'iterations': n, 'of': 'mean'}
    else:
        number = js_to_number(want)
        one = min(n, max(1, int(math.floor(number + 0.5)) if math.isfinite(number) else 1)) - 1

        def column(k: int) -> Any:
            m = rows(k)
            return np.full(times, float(m[one, 0])) if m.shape[1] == 1 else np.asarray(m[one], dtype=np.float64)

        sample = {'iterations': n, 'of': one + 1}
    if index_lists is None:
        index_lists = _index_lists_of(project)
    return result_tree(t=t, outputs=series, column=column, which=chosen, project=project,
                       index_lists=index_lists, now=now, realisations=realisations, sample=sample)


def write_probabilistic_hdf5(prob: Any, path: Union[None, str, Path] = None, want: Any = 'all',
                             **options: Any) -> bytes:
    """A probabilistic run as an HDF5 result file's bytes, written to ``path``
    too when one is given. The keyword arguments are :func:`probabilistic_tree`'s."""
    data = write_hdf5(probabilistic_tree(prob, want, **options))
    if path is not None:
        Path(path).write_bytes(data)
    return data


# --- scenarios side by side -------------------------------------------------------------

def _onto_axis(frm: Any, to: Any) -> Callable[[Any], Any]:
    """A curve on one time axis, read onto another (the page's ``ontoAxis``):
    linear between the first axis's points, NaN outside its span, and the curve
    itself where the two are the same times."""
    import numpy as np
    a_t = np.asarray(frm, dtype=np.float64)
    b_t = np.asarray(to, dtype=np.float64)
    if a_t.shape == b_t.shape and bool(np.all(a_t == b_t)):
        return lambda v: v
    idx = np.zeros(b_t.size, dtype=np.int64)
    w = np.zeros(b_t.size)
    k = 0
    last = a_t.size - 1
    for j in range(b_t.size):
        x = b_t[j]
        while k + 1 < a_t.size and a_t[k + 1] < x:
            k += 1
        idx[j] = k
        a, b = a_t[k], a_t[min(k + 1, last)]
        w[j] = math.nan if x < a_t[0] or x > a_t[last] else ((x - a) / (b - a) if b > a else 0.0)

    def onto(v: Any) -> Any:
        v = np.asarray(v, dtype=np.float64)
        out = np.empty(b_t.size)
        for j in range(b_t.size):
            i = int(idx[j])
            a = v[i]
            b = v[min(i + 1, v.size - 1)]
            out[j] = a + (b - a) * w[j]
        return out

    return onto


def _scenario_list_name(project: Any, results: Any) -> str:
    """The scenario list's name, as the page finds it: the model's list marked as
    the scenario list, ``Scenarios`` where there is none."""
    raw = _project_dict(project) if project is not None else _project_dict(results.project)
    for lst in (raw.get('index_lists') or []) if isinstance(raw, Mapping) else []:
        if isinstance(lst, Mapping) and _truthy(lst.get('for_scenarios')):
            return lst.get('name')
    for lst in getattr(results.project, 'index_lists', None) or []:
        if isinstance(lst, Mapping) and _truthy(lst.get('for_scenarios')):
            return lst.get('name')
    return 'Scenarios'


def scenarios_tree(runs: Mapping[str, Any], which: Optional[Sequence[Any]] = None, *, active: Optional[str] = None,
                   project: Any = None, index_lists: Optional[Sequence[Any]] = None,
                   now: DateLike = None) -> Group:
    """Several scenarios' runs as one result file, as the page writes a table
    that holds more than one scenario: each series once per scenario, with the
    scenario list as one more index of it, so every block holds a group per
    scenario the way it holds one per nuclide.

    ``runs`` is ``{scenario: Results}``, as :meth:`kompartment.Model.run_scenarios`
    returns it, in the model's order. ``active`` is the scenario the file is
    read against -- its series and its output times -- the first by default;
    each other scenario's series of the same label follows it, read onto those
    times (linearly, NaN outside its own span). ``which`` picks the active
    run's series, every one by default. With one run there is nothing beside
    it and the file is that run's alone, as :func:`results_tree` writes it.
    """
    names = list(runs)
    if not names:
        raise ValueError('There are no runs to write.')
    if active is None:
        active = names[0]
    if active not in runs:
        raise KeyError(f"No run of the scenario '{active}'")
    r = runs[active]
    others = [(name, runs[name]) for name in names if name != active]
    if project is None:
        project = _project_dict(r.project)
    if index_lists is None:
        index_lists = getattr(r.project, 'index_lists', None) or []
    if not others:
        return results_tree(r, which, project=project, index_lists=index_lists, now=now)
    outputs = r.outputs()
    chosen = _which_of(outputs, which)
    own = dict(zip(chosen, r.series_many([outputs[i] for i in chosen])))
    beside = []
    for name, e in others:
        eo = e.outputs()
        by_label = {o.get('label'): j for j, o in enumerate(eo)}
        wanted = list(dict.fromkeys(by_label[outputs[i].get('label')] for i in chosen
                                    if outputs[i].get('label') in by_label))
        cols = dict(zip(wanted, e.series_many([eo[j] for j in wanted]))) if wanted else {}
        beside.append((name, eo, by_label, cols, _onto_axis(e.t, r.t)))
    spec: List[Dict[str, Any]] = []
    for i in chosen:
        o = outputs[i]
        spec.append({'output': o, 'label': f"{o.get('label')} · {active}", 'scenario': active, 'values': own[i]})
        for name, eo, by_label, cols, onto in beside:
            j = by_label.get(o.get('label'))
            if j is None:
                continue
            spec.append({'output': eo[j], 'label': f"{o.get('label')} · {name}", 'scenario': name,
                         'values': onto(cols[j])})
    list_name = _scenario_list_name(project, r)
    outs = [{**c['output'], 'dims': [*(c['output'].get('dims') or []), list_name],
             'index': [*(c['output'].get('index') or []), c['scenario']], 'label': c['label']} for c in spec]
    values = [c['values'] for c in spec]
    return result_tree(t=r.t, outputs=outs, column=lambda k: values[k], which=list(range(len(spec))),
                       project=project, index_lists=index_lists, now=now)


def write_scenarios_hdf5(runs: Mapping[str, Any], path: Union[None, str, Path] = None,
                         which: Optional[Sequence[Any]] = None, **options: Any) -> bytes:
    """Several scenarios' runs as one HDF5 result file's bytes, written to
    ``path`` too when one is given. The keyword arguments are
    :func:`scenarios_tree`'s."""
    data = write_hdf5(scenarios_tree(runs, which, **options))
    if path is not None:
        Path(path).write_bytes(data)
    return data
