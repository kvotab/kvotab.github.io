"""HDF5 files: h5create, h5write, h5read, h5info, h5disp, h5readatt and
h5writeatt, through h5py (in the page, Pyodide loads it the first time).

The language counts dimensions column first and HDF5 row first, so sizes
are given and shown here in the language's order, the reverse of the
file's: a 3-by-4 matrix is a dataset of 4 by 3 in the file, its elements in
the same order. Starts and counts are in the language's order and from 1.
"""
import os

import numpy as np

from . import bi as _register
from ._util import err, nargchk, out, num, opt_str, is_str, darr, arr
from ..values import MError, Char, Cell, Struct, Str, EMPTY, numel, py_str
from .. import runtime as R


def bi(*names, **kw):
    """Registered as builtins are, with what h5py or NumPy refuses told as the function's own error."""
    def deco(f):
        async def g(*a):
            try:
                return await f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError, OSError, RuntimeError) as e:
                raise err(f'MATLAB:imagesci:{names[0]}:libraryError', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, aw=True, **kw)(g)
    return deco


async def _h5py(fn):
    try:
        import h5py
        return h5py
    except ImportError:
        pass
    try:
        import pyodide_js
    except ImportError:
        raise err(f'MATLAB:{fn}:noH5py', 'HDF5 files need the h5py package (pip install h5py).', fn)
    try:
        await pyodide_js.loadPackage('h5py')
    except Exception as e:
        raise err(f'MATLAB:{fn}:noH5py', f'h5py, which reads and writes HDF5 files, could not be loaded ({e}).', fn)
    import h5py
    return h5py


def _path(v, fn, exists=True):
    from .iofun import abspath
    name = py_str(v)
    p = abspath(name)
    if exists and not os.path.isfile(p):
        raise err(f'MATLAB:imagesci:{fn}:fileDoesNotExist', f"The file '{name}' does not exist.", fn)
    return p


def _changed(p):
    from .iofun import files_changed
    files_changed(os.path.dirname(p))


def _loc(v):
    s = py_str(v)
    return s if s.startswith('/') else '/' + s


_TYPES = {'double': 'f8', 'single': 'f4', 'uint8': 'u1', 'int8': 'i1', 'uint16': 'u2', 'int16': 'i2', 'uint32': 'u4', 'int32': 'i4',
          'uint64': 'u8', 'int64': 'i8'}


def _class_name(dt):
    dt = np.dtype(dt)
    for k, v in _TYPES.items():
        if np.dtype(v) == dt:
            return k
    if dt == bool:
        return 'logical'
    if dt.kind in 'SUO':
        return 'string'
    if dt.names:
        return 'compound'
    return str(dt)


def _h5type_name(dt):
    dt = np.dtype(dt)
    if dt.kind == 'f':
        return f'H5T_IEEE_F{dt.itemsize * 8}LE'
    if dt.kind in 'iu':
        return f'H5T_STD_{"I" if dt.kind == "i" else "U"}{dt.itemsize * 8}LE'
    if dt.kind == 'b':
        return 'H5T_ENUM (logical)'
    if dt.names:
        return 'H5T_COMPOUND'
    return 'H5T_STRING'


def _lang_size(shape):
    """A dataset's shape in the language's order (reversed; a vector is a column)."""
    s = [float(d) for d in reversed(shape)]
    if len(s) == 0:
        return [1.0, 1.0]
    if len(s) == 1:
        return [s[0], 1.0]
    return s


def _to_lang(a):
    """What h5py read, as a value of the language: arrays with their dimensions reversed, text as text."""
    if isinstance(a, bytes):
        return Char.of(a.decode('utf-8', 'replace'))
    if isinstance(a, str):
        return Char.of(a)
    a = np.asarray(a)
    if a.dtype.names:
        return Struct.scalar({k: _to_lang(a[k]) for k in a.dtype.names})
    if a.dtype.kind in 'SUO':
        flat = [x.decode('utf-8', 'replace') if isinstance(x, bytes) else str(x) for x in a.reshape(-1)]
        if a.ndim == 0:
            return Char.of(flat[0])
        c = Cell.of_list([Char.of(x) for x in flat], (len(flat), 1)) if a.ndim == 1 else None
        if c is None:
            arr = np.empty(a.shape, object)
            for i, x in enumerate(flat):
                arr.flat[i] = Char.of(x)
            c = Cell(np.ascontiguousarray(arr.T))
        return c
    if a.ndim == 0:
        v = a.item()
        return bool(v) if a.dtype == bool else (float(v) if a.dtype == np.float64 else a.reshape(1, 1))
    if a.ndim == 1:
        return np.ascontiguousarray(a.reshape(-1, 1))
    return np.ascontiguousarray(a.transpose())


def _to_file(v, fn):
    """A value of the language as the array h5py writes (dimensions reversed), or text."""
    if isinstance(v, Char):
        return v.str() if v.a.shape[0] <= 1 else [s for s in v.row_strs()]
    if isinstance(v, Str):
        items = ['' if x is None else str(x) for x in v.a.reshape(-1, order='F')]
        return items[0] if len(items) == 1 else np.array(items, dtype=object)
    if isinstance(v, Cell):
        items = [py_str(x) for x in v.a.reshape(-1, order='F')]
        return np.array(items, dtype=object)
    a = arr(v, fn)
    if a.dtype.kind == 'c':
        raise err(f'MATLAB:{fn}:complex', 'Complex values are not written to HDF5 here.', fn)
    return np.ascontiguousarray(a.transpose())


# ---- create, write, read --------------------------------------------------------------------------------------------------

@bi('h5create')
async def h5create(nargout, *args):
    """h5create(filename, ds, size, 'Datatype', class, 'ChunkSize', c, 'Deflate', level, 'FillValue', v): a new dataset (Inf in size: no limit)."""
    nargchk(args, 3, 15, 'h5create')
    h5py = await _h5py('h5create')
    p = _path(args[0], 'h5create', exists=False)
    ds = _loc(args[1])
    size = darr(args[2]).reshape(-1).astype(float)
    opts = {}
    i = 3
    while i + 1 < len(args):
        k = opt_str(args[i])
        if k is None:
            raise err('MATLAB:h5create:option', 'Options come as name, value pairs.', 'h5create')
        opts[k.lower()] = args[i + 1]
        i += 2
    cls = py_str(opts['datatype']).lower() if 'datatype' in opts else 'double'
    if cls == 'string':
        dt = h5py.string_dtype()
    elif cls in _TYPES:
        dt = np.dtype(_TYPES[cls])
    else:
        raise err('MATLAB:h5create:datatype', f"The Datatype is one of {', '.join(_TYPES)} or 'string'.", 'h5create')
    shape = tuple(0 if np.isinf(s) else int(s) for s in reversed(size))
    maxshape = tuple(None if np.isinf(s) else int(s) for s in reversed(size))
    chunks = tuple(int(c) for c in reversed(darr(opts['chunksize']).reshape(-1))) if 'chunksize' in opts else None
    if any(m is None for m in maxshape) and chunks is None:
        raise err('MATLAB:h5create:chunkSize', 'A dataset without a limit (Inf in size) needs ChunkSize.', 'h5create')
    kw = {}
    if 'deflate' in opts:
        kw['compression'], kw['compression_opts'] = 'gzip', int(num(opts['deflate']))
        if chunks is None:
            raise err('MATLAB:h5create:deflate', 'Deflate needs ChunkSize.', 'h5create')
    if 'shuffle' in opts and bool(num(opts['shuffle'])):
        kw['shuffle'] = True
    if 'fletcher32' in opts and bool(num(opts['fletcher32'])):
        kw['fletcher32'] = True
    if 'fillvalue' in opts and cls != 'string':
        kw['fillvalue'] = float(num(opts['fillvalue']))
    with h5py.File(p, 'a') as f:
        if ds in f:
            raise err('MATLAB:imagesci:h5create:datasetAlreadyExists', f"The dataset '{ds}' already exists.", 'h5create')
        if any(m is None for m in maxshape):
            kw['maxshape'] = maxshape
        f.create_dataset(ds, shape=shape, dtype=dt, chunks=chunks, **kw)
    _changed(p)
    return None


def _slab(dset_shape, start, count, stride, fn):
    """The selection (tuple of slices, in the file's order) of start, count and stride given in the language's order."""
    k = len(dset_shape)
    st = [int(x) - 1 for x in reversed(start)] if start is not None else [0] * k
    sd = [int(x) for x in reversed(stride)] if stride is not None else [1] * k
    if len(st) != k:
        st = (st + [0] * k)[:k] if k else st
    cnt = []
    for d in range(k):
        if count is None:
            cnt.append((dset_shape[d] - st[d] + sd[d] - 1) // sd[d])
        else:
            c = list(reversed(count))[d]
            cnt.append((dset_shape[d] - st[d] + sd[d] - 1) // sd[d] if np.isinf(c) else int(c))
    return tuple(slice(st[d], st[d] + (cnt[d] - 1) * sd[d] + 1, sd[d]) for d in range(k)), cnt


@bi('h5write')
async def h5write(nargout, *args):
    """h5write(filename, ds, data), h5write(filename, ds, data, start, count, stride): data written to a dataset (made with h5create), or into a part of it."""
    nargchk(args, 3, 6, 'h5write')
    h5py = await _h5py('h5write')
    p = _path(args[0], 'h5write')
    ds = _loc(args[1])
    data = _to_file(args[2], 'h5write')
    start = darr(args[3]).reshape(-1) if len(args) > 3 else None
    count = darr(args[4]).reshape(-1) if len(args) > 4 else None
    stride = darr(args[5]).reshape(-1) if len(args) > 5 else None
    with h5py.File(p, 'a') as f:
        if ds not in f:
            raise err('MATLAB:imagesci:h5write:datasetDoesNotExist', f"The dataset '{ds}' does not exist: make it with h5create.", 'h5write')
        d = f[ds]
        arr = np.asarray(data, dtype=d.dtype) if d.dtype.kind not in 'O' else np.asarray(data, dtype=object)
        if start is None:
            if d.ndim == 1:
                arr = arr.reshape(-1)
            if arr.shape != d.shape and arr.size == d.size and d.maxshape == d.shape:
                arr = arr.reshape(d.shape)
            if d.maxshape != d.shape and arr.shape != d.shape:
                d.resize(arr.shape if arr.ndim == d.ndim else tuple(max(a, b) for a, b in zip(d.shape, arr.shape)))
            if arr.shape != d.shape and arr.size != d.size:
                raise err('MATLAB:imagesci:h5write:datasetDimensionMismatch',
                          f"The data are {'x'.join(str(int(s)) for s in _lang_size(arr.shape))} and the dataset {'x'.join(str(int(s)) for s in _lang_size(d.shape))}.", 'h5write')
            d[...] = arr.reshape(d.shape)
        else:
            if count is None:
                count = np.array(_lang_size(arr.shape)[:d.ndim] if d.ndim > 1 else [arr.size], float)
            need = [int(s) - 1 + (int(c) - 1) * (int(t) if stride is not None else 1) + 1
                    for s, c, t in zip(reversed(start), reversed(count), reversed(stride) if stride is not None else [1] * len(start))]
            if any(n > s for n, s in zip(need, d.shape)):
                if any(m is not None and n > m for n, m in zip(need, d.maxshape)):
                    raise err('MATLAB:imagesci:h5write:outOfRange', 'The part written lies outside the dataset.', 'h5write')
                d.resize(tuple(max(n, s) for n, s in zip(need, d.shape)))
            sel, cnt = _slab(d.shape, start, count, stride, 'h5write')
            d[sel] = arr.reshape(cnt)
    _changed(p)
    return None


@bi('h5read')
async def h5read(nargout, *args):
    """data = h5read(filename, ds), h5read(filename, ds, start, count, stride): a dataset, or part of it."""
    nargchk(args, 2, 5, 'h5read')
    h5py = await _h5py('h5read')
    p = _path(args[0], 'h5read')
    ds = _loc(args[1])
    with h5py.File(p, 'r') as f:
        if ds not in f or not isinstance(f[ds], h5py.Dataset):
            raise err('MATLAB:imagesci:h5read:datasetDoesNotExist', f"The dataset '{ds}' does not exist in the file.", 'h5read')
        d = f[ds]
        if len(args) > 2:
            start = darr(args[2]).reshape(-1)
            count = darr(args[3]).reshape(-1) if len(args) > 3 else None
            stride = darr(args[4]).reshape(-1) if len(args) > 4 else None
            sel, _ = _slab(d.shape, start, count, stride, 'h5read')
            a = d[sel]
        else:
            a = d[()]
        if d.dtype.kind == 'O' or h5py.check_string_dtype(d.dtype) is not None:
            a = np.asarray(a, dtype=object)
    return _to_lang(a)


# ---- attributes ------------------------------------------------------------------------------------------------------------

@bi('h5readatt')
async def h5readatt(nargout, *args):
    """value = h5readatt(filename, loc, attr): an attribute of the group or dataset at loc."""
    nargchk(args, 3, 3, 'h5readatt')
    h5py = await _h5py('h5readatt')
    p = _path(args[0], 'h5readatt')
    loc, name = _loc(args[1]), py_str(args[2])
    with h5py.File(p, 'r') as f:
        if loc not in f:
            raise err('MATLAB:imagesci:h5readatt:locationDoesNotExist', f"'{loc}' is not in the file.", 'h5readatt')
        o = f[loc]
        if name not in o.attrs:
            raise err('MATLAB:imagesci:h5readatt:attributeDoesNotExist', f"'{loc}' has no attribute '{name}'.", 'h5readatt')
        v = o.attrs[name]
    if isinstance(v, np.ndarray) and v.dtype.kind in 'SUO' and v.size == 1:
        v = v.reshape(-1)[0]
    return _to_lang(v)


@bi('h5writeatt')
async def h5writeatt(nargout, *args):
    """h5writeatt(filename, loc, attr, value): an attribute written to the group or dataset at loc (the file made when there is none)."""
    nargchk(args, 4, 6, 'h5writeatt')
    h5py = await _h5py('h5writeatt')
    p = _path(args[0], 'h5writeatt', exists=False)
    loc, name = _loc(args[1]), py_str(args[2])
    v = _to_file(args[3], 'h5writeatt')
    with h5py.File(p, 'a') as f:
        if loc not in f:
            if loc == '/':
                pass
            else:
                raise err('MATLAB:imagesci:h5writeatt:locationDoesNotExist', f"'{loc}' is not in the file.", 'h5writeatt')
        o = f[loc]
        if isinstance(v, np.ndarray) and v.dtype == object:
            o.attrs.create(name, v, dtype=h5py.string_dtype())
        elif isinstance(v, np.ndarray) and v.size == 1 and not isinstance(args[3], np.ndarray):
            o.attrs[name] = v.reshape(-1)[0]
        else:
            o.attrs[name] = v
    _changed(p)
    return None


# ---- what is in a file ----------------------------------------------------------------------------------------------------------

def _dtype_struct(h5py, dt):
    return Struct.scalar({'Name': EMPTY(), 'Class': Char.of(_h5class(dt)), 'Type': Char.of(_h5type_name(dt)),
                          'Size': float(np.dtype(dt).itemsize) if np.dtype(dt).kind != 'O' else np.inf, 'Attributes': EMPTY()})


def _h5class(dt):
    dt = np.dtype(dt)
    return {'f': 'H5T_FLOAT', 'i': 'H5T_INTEGER', 'u': 'H5T_INTEGER', 'b': 'H5T_ENUM'}.get(dt.kind, 'H5T_COMPOUND' if dt.names else 'H5T_STRING')


def _attrs(h5py, o):
    recs = []
    for k in o.attrs:
        v = o.attrs[k]
        a = np.asarray(v)
        if a.dtype.kind in 'SUO' and a.size == 1:
            v = a.reshape(-1)[0]
        recs.append({'Name': Char.of(k), 'Datatype': _dtype_struct(h5py, a.dtype),
                     'Dataspace': Struct.scalar({'Size': out(np.array([_lang_size(a.shape)])) if a.ndim else EMPTY(), 'MaxSize': EMPTY(),
                                                 'Type': Char.of('simple' if a.ndim else 'scalar')}),
                     'Value': _to_lang(v)})
    return _records(recs, ('Name', 'Datatype', 'Dataspace', 'Value'))


def _records(recs, keys):
    s = Struct.empty((len(recs), 1) if recs else (0, 1), keys)
    for i, rc in enumerate(recs):
        for k in keys:
            s.f[k][i, 0] = rc[k]
    return s


def _filters(d):
    fl = []
    if d.compression:
        fl.append({'Name': Char.of('deflate'), 'Data': float(d.compression_opts or 0)})
    if d.shuffle:
        fl.append({'Name': Char.of('shuffle'), 'Data': EMPTY()})
    if d.fletcher32:
        fl.append({'Name': Char.of('fletcher32'), 'Data': EMPTY()})
    return _records(fl, ('Name', 'Data'))


def _dataset(h5py, name, d):
    fv = d.fillvalue
    return {'Filename': None, 'Name': Char.of(name), 'Datatype': _dtype_struct(h5py, d.dtype),
            'Dataspace': Struct.scalar({'Size': out(np.array([_lang_size(d.shape)])), 'MaxSize': out(np.array([[np.inf if m is None else float(m) for m in reversed(d.maxshape)] or [1.0, 1.0]])) if d.ndim else EMPTY(),
                                        'Type': Char.of('simple' if d.ndim else 'scalar')}),
            'ChunkSize': out(np.array([[float(c) for c in reversed(d.chunks)]])) if d.chunks else EMPTY(),
            'FillValue': _to_lang(fv) if fv is not None and np.asarray(fv).dtype.kind not in 'O' else EMPTY(),
            'Filters': _filters(d), 'Attributes': _attrs(h5py, d)}


_DS_KEYS = ('Name', 'Datatype', 'Dataspace', 'ChunkSize', 'FillValue', 'Filters', 'Attributes')


def _group(h5py, path, g, filename):
    groups, dsets = [], []
    for k in g:
        o = g.get(k, getlink=False)
        full = (path.rstrip('/') + '/' + k)
        if isinstance(o, h5py.Group):
            groups.append(_group(h5py, full, o, filename))
        elif isinstance(o, h5py.Dataset):
            dsets.append(_dataset(h5py, k, o))
    gs = _records(groups, ('Name', 'Groups', 'Datasets', 'Datatypes', 'Links', 'Attributes'))
    return {'Filename': Char.of(filename), 'Name': Char.of(path), 'Groups': gs, 'Datasets': _records(dsets, _DS_KEYS),
            'Datatypes': EMPTY(), 'Links': EMPTY(), 'Attributes': _attrs(h5py, g)}


@bi('h5info')
async def h5info(nargout, *args):
    """info = h5info(filename, loc): what is in an HDF5 file (or at loc): its groups, datasets (size, type, chunks, filters) and attributes."""
    nargchk(args, 1, 2, 'h5info')
    h5py = await _h5py('h5info')
    p = _path(args[0], 'h5info')
    loc = _loc(args[1]) if len(args) > 1 else '/'
    with h5py.File(p, 'r') as f:
        if loc not in f:
            raise err('MATLAB:imagesci:h5info:locationDoesNotExist', f"'{loc}' is not in the file.", 'h5info')
        o = f[loc]
        if isinstance(o, h5py.Dataset):
            d = _dataset(h5py, loc.rsplit('/', 1)[-1], o)
            d['Filename'] = Char.of(p)
            return Struct.scalar({k: d[k] for k in ('Filename',) + _DS_KEYS})
        g = _group(h5py, loc, o, p)
        return Struct.scalar({k: g[k] for k in ('Filename', 'Name', 'Groups', 'Datasets', 'Datatypes', 'Links', 'Attributes')})


def _size_text(shape):
    return 'x'.join(str(int(s)) if np.isfinite(s) else 'Inf' for s in _lang_size(shape)) if shape else 'scalar'


def _value_text(v):
    a = np.asarray(v)
    if a.dtype.kind in 'SO':
        items = [x.decode('utf-8', 'replace') if isinstance(x, bytes) else str(x) for x in a.reshape(-1)]
        return ', '.join(f'"{x}"' for x in items[:6]) + (' ...' if len(items) > 6 else '')
    if a.dtype.kind == 'U':
        return ', '.join(f'"{x}"' for x in a.reshape(-1)[:6])
    vals = a.reshape(-1)
    return ' '.join(f'{x:.6g}' for x in vals[:8]) + (' ...' if vals.size > 8 else '')


def _disp(h5py, name, o, depth, lines):
    pad = '    ' * depth
    if isinstance(o, h5py.Dataset):
        lines.append(f"{pad}Dataset '{name}' ")
        lines.append(f'{pad}    Size:  {_size_text(o.shape)}')
        lines.append(f"{pad}    MaxSize:  {'x'.join('Inf' if m is None else str(m) for m in reversed(o.maxshape)) if o.ndim else 'scalar'}")
        lines.append(f'{pad}    Datatype:   {_h5type_name(o.dtype)} ({_class_name(o.dtype)})')
        lines.append(f"{pad}    ChunkSize:  {'x'.join(str(c) for c in reversed(o.chunks)) if o.chunks else '[]'}")
        filt = [x for x in (('deflate(%s)' % o.compression_opts) if o.compression else None, 'shuffle' if o.shuffle else None, 'fletcher32' if o.fletcher32 else None) if x]
        lines.append(f"{pad}    Filters:  {', '.join(filt) if filt else 'none'}")
        if o.fillvalue is not None and np.asarray(o.fillvalue).dtype.kind not in 'O':
            lines.append(f'{pad}    FillValue:  {_value_text(o.fillvalue)}')
    else:
        lines.append(f"{pad}Group '{name}' ")
    if len(o.attrs):
        lines.append(f'{pad}    Attributes:')
        for k in o.attrs:
            lines.append(f"{pad}        '{k}':  {_value_text(o.attrs[k])}")
    if isinstance(o, h5py.Group):
        for k in o:
            _disp(h5py, (name.rstrip('/') + '/' + k) if isinstance(o.get(k, getlink=False), h5py.Group) else k, o[k], depth + 1, lines)


@bi('h5disp')
async def h5disp(nargout, *args):
    """h5disp(filename, loc): what is in an HDF5 file (or at loc), shown as a tree."""
    nargchk(args, 1, 3, 'h5disp')
    h5py = await _h5py('h5disp')
    p = _path(args[0], 'h5disp')
    loc = _loc(args[1]) if len(args) > 1 else '/'
    lines = [f'HDF5 {os.path.basename(p)} ']
    with h5py.File(p, 'r') as f:
        if loc not in f:
            raise err('MATLAB:imagesci:h5disp:locationDoesNotExist', f"'{loc}' is not in the file.", 'h5disp')
        _disp(h5py, loc, f[loc], 0, lines)
    R.write('\n'.join(lines) + '\n\n')
    return None
