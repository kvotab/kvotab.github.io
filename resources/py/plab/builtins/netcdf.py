"""NetCDF files: nccreate, ncwrite, ncread, ncinfo, ncdisp, ncreadatt and
ncwriteatt. The classic formats (CDF-1, and CDF-2 with 64-bit offsets) are
read and written through SciPy's netcdf_file; netCDF-4 files, which are
HDF5 files laid out by the netCDF-4 conventions (each dimension a
dimension scale, variables attached to theirs), through h5py.

As with HDF5, the language counts dimensions column first and NetCDF row
first, so sizes, starts and counts are in the language's order, the reverse
of the file's. ncread scales by scale_factor and add_offset, and turns
_FillValue (and missing_value) into NaN when the values are floating or
scaled; ncwrite does the reverse."""
import os

import numpy as np

from . import bi as _register
from ._util import err, nargchk, out, num, opt_str, opt_lower, is_str, darr, arr
from ..values import MError, Char, Cell, Struct, Str, EMPTY, numel, py_str, text_list
from .. import runtime as R


def bi(*names, **kw):
    def deco(f):
        async def g(*a):
            try:
                return await f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError, OSError, RuntimeError) as e:
                raise err(f'MATLAB:imagesci:netcdf:libraryFailure', f'{names[0]}: {e}', names[0]) from None
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, aw=True, **kw)(g)
    return deco


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


NOT_A_VARIABLE = 'This is a netCDF dimension but not a netCDF variable.'
_INTERNAL = {'CLASS', 'NAME', 'REFERENCE_LIST', 'DIMENSION_LIST', '_Netcdf4Dimid', '_Netcdf4Coordinates', '_nc3_strict',
             '_NCProperties', '_FillValue_internal'}
_TYPES = {'double': 'f8', 'single': 'f4', 'int8': 'i1', 'uint8': 'u1', 'int16': 'i2', 'uint16': 'u2', 'int32': 'i4', 'uint32': 'u4',
          'int64': 'i8', 'uint64': 'u8', 'char': 'S1'}
_CLASSIC_TYPES = {'double', 'single', 'int8', 'int16', 'int32', 'char'}
# the fill values netCDF uses when a variable sets none
_DEFAULT_FILL = {'f8': 9.969209968386869e36, 'f4': np.float32(9.96921e36), 'i1': -127, 'u1': 255, 'i2': -32767, 'u2': 65535,
                 'i4': -2147483647, 'u4': 4294967295, 'i8': -9223372036854775806, 'u8': 18446744073709551614}


def _class_of(dt):
    if dt is str or (isinstance(dt, np.dtype) and dt.kind in 'OU'):
        return 'string'
    dt = np.dtype(dt)
    if dt.kind == 'S':
        return 'char'
    for k, v in _TYPES.items():
        if v != 'S1' and np.dtype(v) == dt:
            return k
    return dt.name


async def _need_h5py(fn):
    from .hdf5 import _h5py
    return await _h5py(fn)


def _path(v, fn, exists=True):
    from .iofun import abspath
    name = py_str(v)
    if name.startswith(('http://', 'https://')):
        raise err(f'MATLAB:imagesci:{fn}:remote', 'NetCDF files are read from files here (an OPeNDAP address is not supported).', fn)
    p = abspath(name)
    if exists and not os.path.isfile(p):
        raise err(f'MATLAB:imagesci:{fn}:fileDoesNotExist', f"The file '{name}' does not exist.", fn)
    return p


def _changed(p):
    from .iofun import files_changed
    files_changed(os.path.dirname(p))


def _sniff(p):
    with open(p, 'rb') as f:
        head = f.read(8)
    if head[:4] == b'CDF\x01':
        return 'classic'
    if head[:4] == b'CDF\x02':
        return '64bit'
    if head[:4] == b'CDF\x05':
        return '64bit_data'
    if head[:8] == b'\x89HDF\r\n\x1a\n':
        return 'netcdf4'
    raise err('MATLAB:imagesci:netcdf:notNetCDF', f"'{os.path.basename(p)}' is not a NetCDF file.", 'netcdf')


def _text(v):
    if isinstance(v, bytes):
        return v.decode('utf-8', errors='replace')
    if isinstance(v, np.ndarray) and v.dtype.kind == 'S':
        return b''.join(v.reshape(-1).tolist()).decode('utf-8', errors='replace')
    return v


def _attr_value(v):
    """An attribute as the language sees it: text as char, numbers as a row."""
    v = _text(v)
    if isinstance(v, str):
        return Char.of(v)
    a = np.asarray(v)
    if a.dtype.kind == 'O':
        items = [_text(x) for x in a.reshape(-1)]
        if all(isinstance(x, str) for x in items):
            return Str(np.array(items, object).reshape(1, -1)) if len(items) != 1 else Str.of(items[0])
    if a.dtype.kind == 'S':
        return Char.of(_text(a))
    if a.ndim == 0 or a.size == 1:
        x = a.reshape(-1)[0]
        return float(x) if a.dtype == np.float64 else out(a.reshape(1, 1))
    return out(a.reshape(1, -1))


# ---- the two kinds of file ---------------------------------------------------------------------------------------------

class _Classic:
    """A CDF-1 or CDF-2 file through scipy.io.netcdf_file."""

    def __init__(self, path, mode='r', version=1):
        from scipy.io import netcdf_file
        self.path = path
        self.f = netcdf_file(path, mode, mmap=False, version=version, maskandscale=False)
        self.format = 'classic' if self.f.version_byte == 1 else '64bit'

    def close(self):
        self.f.close()

    def dims(self):
        out_ = []
        for name, n in self.f.dimensions.items():
            unl = n is None
            if unl:
                n = max((v.shape[0] for v in self.f.variables.values() if v.dimensions and v.dimensions[0] == name), default=0)
            out_.append((name, int(n), unl))
        return out_

    def var_names(self):
        return list(self.f.variables)

    def has_var(self, name):
        return name in self.f.variables

    def var_dims(self, name):
        return list(self.f.variables[name].dimensions)

    def var_shape(self, name):
        return tuple(self.f.variables[name].shape)

    def var_dtype(self, name):
        return self.f.variables[name].data.dtype

    def var_attrs(self, name):
        return {k: v for k, v in self.f.variables[name]._attributes.items()}

    def global_attrs(self):
        return dict(self.f._attributes)

    def read(self, name, idx):
        v = self.f.variables[name]
        a = np.asarray(v.getValue()) if not v.shape else np.array(v[idx] if idx is not None else v[:])
        return a.astype(a.dtype.newbyteorder('=')) if a.dtype.kind in 'iuf' else a   # classic files are big-endian

    def write(self, name, idx, data):
        v = self.f.variables[name]
        if not v.shape:
            v.assignValue(data.reshape(()))
            return
        if v.isrec:
            stop = idx[0].stop if isinstance(idx[0], slice) else None
            need = stop if stop is not None else 0
            if need > v.shape[0]:
                # a record variable grows to take the new records (filled first)
                fill = v._attributes.get('_FillValue', _DEFAULT_FILL.get(v.data.dtype.str[1:], 0))
                old = v.shape[0]
                v[old:need] = np.full((need - old,) + v.shape[1:], fill, dtype=v.data.dtype)
        v[idx] = data

    def create_dim(self, name, n):
        if n is None and self.f._dims:
            # SciPy takes an unlimited dimension only as the first one defined; the format takes it anywhere
            self.f._dims.insert(0, name)
            self.f.dimensions[name] = None
            return
        self.f.createDimension(name, n)

    def create_var(self, name, dtype, dims, fill, opts):
        code = np.dtype(dtype).char if dtype != 'S1' else 'c'
        v = self.f.createVariable(name, code, tuple(dims))
        if fill is not None:
            v._attributes['_FillValue'] = np.array(fill, dtype=v.data.dtype if dtype != 'S1' else 'S1').reshape(())[()]
        if v.shape and not v.isrec:
            f0 = fill if fill is not None else _DEFAULT_FILL.get(np.dtype(dtype).str[1:], b'\x00' if dtype == 'S1' else 0)
            v[:] = np.full(v.shape, f0, dtype=v.data.dtype)

    def set_attr(self, name, att, value):
        target = self.f if name is None else self.f.variables[name]
        target._attributes[att] = value

    def chunking(self, name):
        return None, 0, False


class _HDF:
    """A netCDF-4 file through h5py, by the netCDF-4 conventions."""

    def __init__(self, h5py, path, mode='r'):
        self.h5 = h5py
        self.path = path
        # netCDF keeps variables and attributes in the order they were made
        self.f = h5py.File(path, mode, track_order=True) if mode in ('a', 'w') and not os.path.exists(path) else h5py.File(path, mode)
        self.format = 'netcdf4_classic' if '_nc3_strict' in self.f.attrs else 'netcdf4'

    def close(self):
        self.f.close()

    def _group(self, path):
        g = self.f
        for part in [p for p in path.split('/') if p]:
            g = g[part]
        return g

    def _split(self, name):
        name = name.strip()
        if '/' in name.strip('/'):
            gp, _, leaf = name.rstrip('/').rpartition('/')
            return self._group(gp), leaf
        return self.f, name.strip('/')

    def _keys(self, g):
        """A group's names in the order they were made, when the file keeps that order (netCDF's do)."""
        h5 = self.h5
        try:
            gid = g['/'].id if isinstance(g, h5.File) else g.id          # a file's id is the file's, not its root group's
            if gid.get_create_plist().get_link_creation_order() & h5.h5p.CRT_ORDER_TRACKED:
                names = []
                gid.links.iterate(lambda n: names.append(n.decode('utf-8')), idx_type=h5.h5.INDEX_CRT_ORDER)
                return names
        except Exception:
            pass
        return list(g.keys())

    def _is_dim_only(self, ds):
        nm = ds.attrs.get('NAME')
        nm = _text(nm) if nm is not None else ''
        return isinstance(nm, str) and nm.startswith(NOT_A_VARIABLE)

    def _is_scale(self, ds):
        c = ds.attrs.get('CLASS')
        return c is not None and _text(c) == 'DIMENSION_SCALE'

    def dims(self, group=None):
        g = group or self.f
        res = []
        items = []
        for k in self._keys(g):
            ds = g[k]
            if isinstance(ds, self.h5.Dataset) and self._is_scale(ds):
                did = ds.attrs.get('_Netcdf4Dimid')
                items.append((int(did) if did is not None else 10 ** 6 + len(items), k, ds))
        for _, k, ds in sorted(items, key=lambda t: t[0]):
            res.append((k, int(ds.shape[0]) if ds.shape else 0, ds.maxshape and ds.maxshape[0] is None))
        return res

    def var_names(self, group=None):
        g = group or self.f
        return [k for k in self._keys(g) if isinstance(g[k], self.h5.Dataset) and not self._is_dim_only(g[k])]

    def groups(self, group=None):
        g = group or self.f
        return [k for k in self._keys(g) if isinstance(g[k], self.h5.Group)]

    def has_var(self, name):
        try:
            g, leaf = self._split(name)
        except KeyError:
            return False
        return leaf in g and isinstance(g[leaf], self.h5.Dataset) and not self._is_dim_only(g[leaf])

    def _ds(self, name):
        g, leaf = self._split(name)
        return g[leaf]

    def var_dims(self, name):
        ds = self._ds(name)
        if self._is_scale(ds) and len(ds.shape) == 1:
            return [ds.name.rsplit('/', 1)[-1]]             # a coordinate variable is its own dimension
        names = []
        for i in range(len(ds.shape)):
            d = ds.dims[i]
            names.append(d[0].name.rsplit('/', 1)[-1] if len(d) else f'phony_dim_{i}')
        return names

    def var_shape(self, name):
        return tuple(self._ds(name).shape)

    def var_dtype(self, name):
        dt = self._ds(name).dtype
        if self.h5.check_string_dtype(dt) is not None and dt.kind == 'O':
            return np.dtype('O')
        return dt

    def var_attrs(self, name):
        return {k: v for k, v in self._ds(name).attrs.items() if k not in _INTERNAL}

    def global_attrs(self, group=None):
        g = group or self.f
        return {k: v for k, v in g.attrs.items() if k not in _INTERNAL}

    def read(self, name, idx):
        ds = self._ds(name)
        if not ds.shape:
            a = ds[()]
        else:
            a = ds[idx] if idx is not None else ds[...]
        a = np.asarray(a)
        if a.dtype.kind == 'O':
            a = np.vectorize(lambda x: x.decode('utf-8', 'replace') if isinstance(x, bytes) else str(x), otypes=[object])(a)
        return a

    def write(self, name, idx, data):
        ds = self._ds(name)
        if not ds.shape:
            ds[()] = data.reshape(())
            return
        # an unlimited dimension grows to take what is written past its end
        new = list(ds.shape)
        for i, sl in enumerate(idx):
            stop = sl.stop if isinstance(sl, slice) else sl + 1
            if stop is not None and stop > new[i]:
                if ds.maxshape[i] is not None:
                    raise err('MATLAB:imagesci:netcdf:outOfRange', 'The data go past the end of a fixed dimension.', 'ncwrite')
                new[i] = stop
        if tuple(new) != ds.shape:
            ds.resize(tuple(new))
            for i in range(len(new)):
                for sc in ds.dims[i].values():
                    if sc.shape and sc.shape[0] < new[i]:
                        sc.resize((new[i],))
        ds[idx] = data

    def create_dim(self, name, n):
        h5 = self.h5
        size = 0 if n is None else int(n)
        ds = self.f.create_dataset(name, shape=(size,), dtype='f4', maxshape=(None,) if n is None else (size,),
                                   chunks=(1024,) if n is None else None, track_order=True)
        ds.make_scale(NOT_A_VARIABLE + f'{size:10d}')
        ds.attrs['_Netcdf4Dimid'] = np.int32(len(self.dims()) - 1)

    def create_var(self, name, dtype, dims, fill, opts):
        h5 = self.h5
        lengths = {d: (n, unl) for d, n, unl in self.dims()}
        shape = tuple(lengths[d][0] for d in dims)
        maxshape = tuple(None if lengths[d][1] else lengths[d][0] for d in dims)
        kw = {}
        if dtype == 'string':
            dt = h5.string_dtype('utf-8')
        else:
            dt = np.dtype(dtype)
        if fill is not None and dtype != 'string':
            kw['fillvalue'] = np.array(fill, dtype=dt)[()]
        chunks = opts.get('chunks')
        if any(m is None for m in maxshape) or chunks or opts.get('deflate') or opts.get('shuffle'):
            kw['chunks'] = tuple(chunks) if chunks else tuple(max(1, min(s if s else 1, 1024)) if m is not None else 1024 for s, m in zip(shape, maxshape)) \
                if shape else None
        if opts.get('deflate'):
            kw['compression'] = 'gzip'
            kw['compression_opts'] = int(opts['deflate'])
        if opts.get('shuffle'):
            kw['shuffle'] = True
        coord = len(dims) == 1 and dims[0] == name
        users = []
        if coord and name in self.f:
            # a coordinate variable takes the place of its dimension's placeholder
            old = self.f[name]
            did = old.attrs.get('_Netcdf4Dimid')
            for k, ds in self.f.items():
                if isinstance(ds, h5.Dataset) and ds.name != old.name:
                    for i in range(len(ds.shape)):
                        if any(sc.name == old.name for sc in ds.dims[i].values()):
                            ds.dims[i].detach_scale(old)
                            users.append((ds, i))
            del self.f[name]
        else:
            did = None
        ds = self.f.create_dataset(name, shape=shape, dtype=dt, maxshape=maxshape, track_order=True, **kw)
        if fill is not None and dtype != 'string':
            ds.attrs['_FillValue'] = np.array(fill, dtype=dt)[()].reshape(1)
        if coord:
            ds.make_scale(name)
            ds.attrs['_Netcdf4Dimid'] = np.int32(did if did is not None else len(self.dims()) - 1)
            for other, i in users:
                other.dims[i].attach_scale(ds)
        else:
            for i, d in enumerate(dims):
                ds.dims[i].attach_scale(self.f[d])

    def set_attr(self, name, att, value):
        target = self.f if name is None else self._ds(name)
        target.attrs[att] = value

    def chunking(self, name):
        ds = self._ds(name)
        return ds.chunks, (ds.compression_opts or 0) if ds.compression == 'gzip' else 0, bool(ds.shuffle)


async def _open(p, fn, mode='r'):
    kind = _sniff(p)
    if kind == '64bit_data':
        raise err('MATLAB:imagesci:netcdf:cdf5', 'CDF-5 (64-bit data) files are not read here.', fn)
    if kind == 'netcdf4':
        h5 = await _need_h5py(fn)
        return _HDF(h5, p, mode)
    return _Classic(p, mode, 1 if kind == 'classic' else 2)


# ---- reading --------------------------------------------------------------------------------------------------------------

def _indices(shape_c, start, count, stride, fn):
    """Slices in the file's order from 1-based start, count and stride in the language's."""
    n = len(shape_c)
    if start is None:
        return None, shape_c
    s = np.asarray(darr(start), float).reshape(-1)
    c = np.asarray(darr(count), float).reshape(-1) if count is not None else np.full(n, np.inf)
    t = np.asarray(darr(stride), float).reshape(-1) if stride is not None else np.ones(n)
    if not (s.size == c.size == t.size == n):
        raise err(f'MATLAB:imagesci:{fn}:badStart', f'start, count and stride have an element for each of the {n} dimensions.', fn)
    sl, out_shape = [], []
    for k in range(n):
        dim = shape_c[n - 1 - k]
        a, b, st = int(s[k]) - 1, c[k], int(t[k])
        if a < 0 or st < 1 or (a >= dim and dim > 0 and fn == 'ncread'):
            raise err(f'MATLAB:imagesci:{fn}:badStart', 'start is from 1, within the dimension, and stride from 1.', fn)
        if np.isinf(b):
            b = len(range(a, dim, st))
        b = int(b)
        sl.append(slice(a, a + (b - 1) * st + 1 if b > 0 else a, st))
        out_shape.append(b)
    return tuple(reversed(sl)), tuple(reversed(out_shape))


def _to_language(a, dims_c, char=False):
    """A file's (C-ordered) array in the language's order."""
    if char:
        b = np.asarray(a)
        if b.dtype.kind == 'S':
            # one character each, in the language's order: a column for one dimension, the transpose for two
            codes = np.frombuffer(np.ascontiguousarray(b).tobytes(), np.uint8).reshape(b.shape).astype(np.uint16)
            if codes.ndim <= 1:
                return Char(codes.reshape(-1, 1))
            return Char(np.ascontiguousarray(np.transpose(codes)))
    if a.dtype.kind == 'O':
        S = np.array(a, object)
        S = S.T if S.ndim > 1 else S.reshape(-1, 1)
        return Str(S)
    b = np.transpose(a) if a.ndim > 1 else a.reshape(-1, 1)
    return out(np.ascontiguousarray(b))


def _unpack(a, attrs):
    """scale_factor, add_offset, _FillValue and missing_value applied as ncread does."""
    sf, ao = attrs.get('scale_factor'), attrs.get('add_offset')
    fills = [attrs[k] for k in ('_FillValue', 'missing_value') if k in attrs]
    if a.dtype.kind not in 'iuf':
        return a
    if sf is not None or ao is not None:
        b = a.astype(np.float64)
        for fv in fills:
            for x in np.asarray(fv).reshape(-1):
                b[a == x] = np.nan
        if sf is not None:
            b = b * float(np.asarray(sf).reshape(-1)[0])
        if ao is not None:
            b = b + float(np.asarray(ao).reshape(-1)[0])
        return b
    if a.dtype.kind == 'f' and fills:
        b = a.copy()
        for fv in fills:
            for x in np.asarray(fv).reshape(-1):
                b[a == np.asarray(x, a.dtype)] = np.nan
        return b
    return a


@bi('ncread', arr=False)
async def ncread(nargout, *args):
    """vardata = ncread(source, varname, start, count, stride): a variable's
    values (all, or from start, count of them with stride, in the language's
    order), scaled by scale_factor and add_offset with fill values NaN."""
    nargchk(args, 2, 5, 'ncread')
    p = _path(args[0], 'ncread')
    name = py_str(args[1])
    f = await _open(p, 'ncread')
    try:
        if not f.has_var(name):
            raise err('MATLAB:imagesci:netcdf:unknownLocation', f"Could not find variable or group '{name}' in file.", 'ncread')
        shape = f.var_shape(name)
        idx, _ = _indices(shape, args[2] if len(args) > 2 else None, args[3] if len(args) > 3 else None,
                          args[4] if len(args) > 4 else None, 'ncread')
        a = f.read(name, idx)
        dt = f.var_dtype(name)
        if np.dtype(dt).kind == 'S':
            return _to_language(a, f.var_dims(name), char=True)
        a = _unpack(np.asarray(a), f.var_attrs(name))
        return _to_language(np.asarray(a), f.var_dims(name))
    finally:
        f.close()


@bi('ncreadatt', arr=False)
async def ncreadatt(nargout, *args):
    """attvalue = ncreadatt(source, location, attname): an attribute of a variable, or of the file when location is '/'."""
    nargchk(args, 3, 3, 'ncreadatt')
    p = _path(args[0], 'ncreadatt')
    loc, att = py_str(args[1]), py_str(args[2])
    f = await _open(p, 'ncreadatt')
    try:
        if loc in ('/', ''):
            attrs = f.global_attrs()
        else:
            if not f.has_var(loc):
                raise err('MATLAB:imagesci:netcdf:unknownLocation', f"Could not find variable or group '{loc}' in file.", 'ncreadatt')
            attrs = f.var_attrs(loc)
        if att not in attrs:
            raise err('MATLAB:imagesci:netcdf:libraryFailure', f"The attribute '{att}' is not there.", 'ncreadatt')
        return _attr_value(attrs[att])
    finally:
        f.close()


def _dims_struct(items):
    S = Struct.empty((1, len(items)) if items else (0, 0), ('Name', 'Length', 'Unlimited'))
    for i, (n, L, u) in enumerate(items):
        S.f['Name'][0, i] = Char.of(n)
        S.f['Length'][0, i] = float(L)
        S.f['Unlimited'][0, i] = bool(u)
    return S


def _attrs_struct(attrs):
    S = Struct.empty((1, len(attrs)) if attrs else (0, 0), ('Name', 'Value'))
    for i, (k, v) in enumerate(attrs.items()):
        S.f['Name'][0, i] = Char.of(k)
        S.f['Value'][0, i] = _attr_value(v)
    return S


def _var_struct(f, name, path):
    dims_c = f.var_dims(name)
    shape_c = f.var_shape(name)
    dl = {d: (n, u) for d, n, u in f.dims()}
    dims = [(d, dl.get(d, (s, False))[0] if d in dl else s, dl.get(d, (s, False))[1]) for d, s in zip(dims_c, shape_c)]
    dims = list(reversed(dims))
    attrs = f.var_attrs(name)
    dt = f.var_dtype(name)
    cls = _class_of(dt)
    chunks, deflate, shuffle = f.chunking(name)
    keys = ('Filename', 'Name', 'Dimensions', 'Size', 'Datatype', 'Attributes', 'ChunkSize', 'FillValue', 'DeflateLevel', 'Shuffle', 'Format')
    fill = attrs.get('_FillValue')
    vals = {'Filename': Char.of(path), 'Name': Char.of(name.split('/')[-1]), 'Dimensions': _dims_struct(dims),
            'Size': np.array([[float(s) for s in reversed(shape_c)]]) if shape_c else np.array([[1.0]]), 'Datatype': Char.of(cls),
            'Attributes': _attrs_struct(attrs),
            'ChunkSize': np.array([[float(c) for c in reversed(chunks)]]) if chunks else EMPTY(),
            'FillValue': _attr_value(fill) if fill is not None else Char.of('default'),
            'DeflateLevel': float(deflate) if deflate else EMPTY(), 'Shuffle': bool(shuffle), 'Format': Char.of(f.format)}
    S = Struct.empty((1, 1), keys)
    for k in keys:
        S.f[k][0, 0] = vals[k]
    return S


@bi('ncinfo', arr=False)
async def ncinfo(nargout, *args):
    """finfo = ncinfo(source) or vinfo = ncinfo(source, varname): a struct of
    the file's Filename, Name, Dimensions, Variables, Attributes, Groups and
    Format, or of one variable (its Dimensions, Size, Datatype, Attributes,
    ChunkSize, FillValue, DeflateLevel, Shuffle)."""
    nargchk(args, 1, 2, 'ncinfo')
    p = _path(args[0], 'ncinfo')
    f = await _open(p, 'ncinfo')
    try:
        if len(args) > 1:
            name = py_str(args[1])
            if not f.has_var(name):
                raise err('MATLAB:imagesci:netcdf:unknownLocation', f"Could not find variable or group '{name}' in file.", 'ncinfo')
            return _var_struct(f, name, p)
        names = f.var_names()
        V = Struct.empty((1, len(names)) if names else (0, 0), ('Filename', 'Name', 'Dimensions', 'Size', 'Datatype', 'Attributes',
                                                                 'ChunkSize', 'FillValue', 'DeflateLevel', 'Shuffle', 'Format'))
        for i, n in enumerate(names):
            vs = _var_struct(f, n, p)
            for k in V.keys:
                V.f[k][0, i] = vs.get1(k)
        groups = f.groups() if isinstance(f, _HDF) else []
        G = Struct.empty((1, len(groups)) if groups else (0, 0), ('Name',))
        for i, g in enumerate(groups):
            G.f['Name'][0, i] = Char.of(g)
        keys = ('Filename', 'Name', 'Dimensions', 'Variables', 'Attributes', 'Groups', 'Format')
        S = Struct.empty((1, 1), keys)
        vals = {'Filename': Char.of(p), 'Name': Char.of('/'), 'Dimensions': _dims_struct(f.dims()), 'Variables': V,
                'Attributes': _attrs_struct(f.global_attrs()), 'Groups': G, 'Format': Char.of(f.format)}
        for k in keys:
            S.f[k][0, 0] = vals[k]
        return S
    finally:
        f.close()


def _show_value(v):
    v = _text(v)
    if isinstance(v, str):
        return f"'{v}'"
    a = np.asarray(v).reshape(-1)
    if a.dtype.kind == 'O':
        return ', '.join(f'"{_text(x)}"' for x in a)
    s = ' '.join(f'{x:g}' if a.dtype.kind == 'f' else str(x) for x in a)
    return s if a.size == 1 else f'[{s}]'


@bi('ncdisp', arr=False)
async def ncdisp(nargout, *args):
    """ncdisp(source) or ncdisp(source, varname): the file's (or the variable's)
    format, dimensions, variables and attributes printed."""
    nargchk(args, 1, 3, 'ncdisp')
    p = _path(args[0], 'ncdisp')
    f = await _open(p, 'ncdisp')
    lines = []
    try:
        lines += ['Source:', f'           {p}', 'Format:', f'           {f.format}']
        only = py_str(args[1]) if len(args) > 1 and py_str(args[1]) not in ('/', '') else None
        if only is None:
            ga = f.global_attrs()
            if ga:
                lines.append('Global Attributes:')
                w = max(len(k) for k in ga)
                lines += [f'           {k.ljust(w)} = {_show_value(v)}' for k, v in ga.items()]
            dims = f.dims()
            if dims:
                lines.append('Dimensions:')
                w = max(len(d) for d, _, _ in dims)
                lines += [f'           {d.ljust(w)} = {n}' + ('   (UNLIMITED)' if u else '') for d, n, u in dims]
        names = [only] if only else f.var_names()
        if only and not f.has_var(only):
            raise err('MATLAB:imagesci:netcdf:unknownLocation', f"Could not find variable or group '{only}' in file.", 'ncdisp')
        if names:
            lines.append('Variables:')
        for n in names:
            dims_c = f.var_dims(n)
            shape_c = f.var_shape(n)
            lines.append(f'    {n}')
            size = 'x'.join(str(s) for s in reversed(shape_c)) if shape_c else '1x1'
            lines.append(f'           Size:       {size}')
            lines.append(f"           Dimensions: {','.join(reversed(dims_c))}")
            lines.append(f'           Datatype:   {_class_of(f.var_dtype(n))}')
            at = f.var_attrs(n)
            if at:
                lines.append('           Attributes:')
                w = max(len(k) for k in at)
                lines += [f'                       {k.ljust(w)} = {_show_value(v)}' for k, v in at.items()]
    finally:
        f.close()
    R.write('\n'.join(lines) + '\n')
    return None


# ---- writing --------------------------------------------------------------------------------------------------------------

def _dim_pairs(v):
    """{'x', 10, 'y', Inf, 'z'} as [(name, length or None for unlimited, given)]."""
    if isinstance(v, (Char, Str)):
        items = [py_str(v)]
    elif isinstance(v, Cell):
        items = list(v.a.reshape(-1, order='F'))
    else:
        raise err('MATLAB:imagesci:nccreate:badDimensions', "Dimensions is a cell array like {'x', 10, 'time', Inf}.", 'nccreate')
    res = []
    i = 0
    while i < len(items):
        name = opt_str(items[i]) if not isinstance(items[i], str) else items[i]
        if name is None:
            raise err('MATLAB:imagesci:nccreate:badDimensions', 'Each dimension is named by text.', 'nccreate')
        if i + 1 < len(items) and opt_str(items[i + 1]) is None:
            n = float(num(items[i + 1]))
            res.append((name, None if np.isinf(n) else int(n), True))
            i += 2
        else:
            res.append((name, None, False))
            i += 1
    return res


@bi('nccreate', arr=False)
async def nccreate(nargout, *args):
    """nccreate(filename, varname, 'Dimensions', {'x', 10, 'time', Inf},
    'Datatype', 'double', 'Format', 'netcdf4_classic', 'FillValue', v,
    'ChunkSize', c, 'DeflateLevel', k, 'Shuffle', tf): a variable made (and the
    file, and dimensions not there yet); Inf makes a dimension unlimited.
    Formats: netcdf4_classic (default), netcdf4, classic and 64bit."""
    nargchk(args, 2, None, 'nccreate')
    p = _path(args[0], 'nccreate', exists=False)
    name = py_str(args[1])
    rest = list(args[2:])
    if len(rest) % 2:
        raise err('MATLAB:imagesci:nccreate:nargin', 'The options come as names and values.', 'nccreate')
    o = {}
    for i in range(0, len(rest), 2):
        k = opt_lower(rest[i])
        if k not in ('dimensions', 'datatype', 'format', 'fillvalue', 'chunksize', 'deflatelevel', 'shuffle'):
            raise err('MATLAB:imagesci:nccreate:badOption', f"'{py_str(rest[i])}' is not an option of nccreate.", 'nccreate')
        o[k] = rest[i + 1]
    dims = _dim_pairs(o['dimensions']) if 'dimensions' in o else []
    dtype = (opt_lower(o['datatype']) if 'datatype' in o else 'double')
    if dtype not in _TYPES and dtype != 'string':
        raise err('MATLAB:imagesci:nccreate:badDatatype', f"'{dtype}' is not a NetCDF data type.", 'nccreate')
    exists = os.path.isfile(p)
    fmt = opt_lower(o['format']) if 'format' in o else None
    if exists:
        kind = _sniff(p)
        if fmt and fmt != kind and not (kind == 'netcdf4' and fmt in ('netcdf4', 'netcdf4_classic')):
            raise err('MATLAB:imagesci:nccreate:formatMismatch', f'The file is already {kind}.', 'nccreate')
    else:
        kind = fmt or 'netcdf4_classic'
        if kind not in ('classic', '64bit', 'netcdf4', 'netcdf4_classic'):
            raise err('MATLAB:imagesci:nccreate:badFormat', "Format is 'classic', '64bit', 'netcdf4_classic' or 'netcdf4'.", 'nccreate')
    classic = kind in ('classic', '64bit')
    if not classic and exists:
        h5 = await _need_h5py('nccreate')
        with h5.File(p, 'r') as probe:
            if '_nc3_strict' in probe.attrs:
                kind = 'netcdf4_classic'
    if kind == 'netcdf4_classic' and dtype not in _CLASSIC_TYPES:
        raise err('MATLAB:imagesci:nccreate:badDatatype', f"A netcdf4_classic file holds the classic types (double, single, int8, int16, int32, char), not {dtype}.", 'nccreate')
    if classic and dtype not in _CLASSIC_TYPES:
        raise err('MATLAB:imagesci:nccreate:badDatatype', f"A classic file holds double, single, int8, int16, int32 and char, not {dtype}.", 'nccreate')
    if classic:
        f = _Classic(p, 'a' if exists else 'w', 1 if kind == 'classic' else 2)
    else:
        h5 = await _need_h5py('nccreate')
        f = _HDF(h5, p, 'a')
        if not exists and kind == 'netcdf4_classic':
            f.f.attrs['_nc3_strict'] = np.int32(1)
    try:
        if f.has_var(name):
            raise err('MATLAB:imagesci:nccreate:variableExists', f"The variable '{name}' is already in the file.", 'nccreate')
        have = {d: (n, u) for d, n, u in f.dims()}
        dims_c = []
        for d, n, given in dims:
            if d in have:
                if given and n is not None and not have[d][1] and have[d][0] != n:
                    raise err('MATLAB:imagesci:nccreate:dimensionMismatch', f"The dimension '{d}' is already {have[d][0]} long.", 'nccreate')
            else:
                if not given:
                    raise err('MATLAB:imagesci:nccreate:unknownDimension', f"Give the length of the new dimension '{d}'.", 'nccreate')
                if classic and n is None and any(u for _, _, u in f.dims()):
                    raise err('MATLAB:imagesci:nccreate:twoUnlimited', 'A classic file has one unlimited dimension.', 'nccreate')
                if n is None or not (len(dims) == 1 and d == name and not classic):
                    f.create_dim(d, n)
                else:
                    f.create_dim(d, n)
                have[d] = (n or 0, n is None)
            dims_c.append(d)
        dims_c = list(reversed(dims_c))
        if classic and any(have[d][1] for d in dims_c[1:]):
            raise err('MATLAB:imagesci:nccreate:unlimitedLast', 'In a classic file the unlimited dimension is the last.', 'nccreate')
        fill = None
        if 'fillvalue' in o and not (is_str(o['fillvalue']) and opt_lower(o['fillvalue']) == 'disable'):
            fv = o['fillvalue']
            fill = py_str(fv).encode()[:1] if dtype == 'char' else np.asarray(darr(fv)).reshape(-1)[0]
        opts = {}
        if 'chunksize' in o:
            if classic:
                raise err('MATLAB:imagesci:nccreate:classicChunk', 'Classic files are not chunked.', 'nccreate')
            opts['chunks'] = [int(x) for x in reversed(np.asarray(darr(o['chunksize'])).reshape(-1))]
        if 'deflatelevel' in o:
            if classic:
                raise err('MATLAB:imagesci:nccreate:classicDeflate', 'Classic files are not compressed.', 'nccreate')
            opts['deflate'] = int(num(o['deflatelevel']))
        if 'shuffle' in o and not classic:
            v = o['shuffle']
            opts['shuffle'] = (opt_lower(v) in ('on', 'true')) if is_str(v) else bool(np.all(np.asarray(darr(v)) != 0))
        f.create_var(name, 'string' if dtype == 'string' else _TYPES[dtype], dims_c, fill, opts)
    finally:
        f.close()
    _changed(p)
    return None


def _pack(data, attrs, dt):
    """The reverse of _unpack, for ncwrite."""
    sf, ao = attrs.get('scale_factor'), attrs.get('add_offset')
    fill = attrs.get('_FillValue')
    a = np.asarray(data)
    if sf is not None or ao is not None:
        b = a.astype(np.float64)
        nan = np.isnan(b)
        if ao is not None:
            b = b - float(np.asarray(ao).reshape(-1)[0])
        if sf is not None:
            b = b / float(np.asarray(sf).reshape(-1)[0])
        if np.dtype(dt).kind in 'iu':
            b = np.round(b)
        if nan.any():
            fv = np.asarray(fill).reshape(-1)[0] if fill is not None else _DEFAULT_FILL.get(np.dtype(dt).str[1:], 0)
            b[nan] = fv
        return b.astype(dt)
    if np.dtype(dt).kind == 'f' and a.dtype.kind == 'f' and fill is not None:
        b = a.astype(dt)
        b[np.isnan(a)] = np.asarray(fill).reshape(-1)[0]
        return b
    if np.dtype(dt).kind in 'iu' and a.dtype.kind == 'f':
        return np.round(a).astype(dt)
    return a.astype(dt) if np.dtype(dt).kind != 'O' else a


@bi('ncwrite', arr=False)
async def ncwrite(nargout, *args):
    """ncwrite(filename, varname, vardata, start, stride): values written to a
    variable nccreate made (from start, with stride, in the language's
    order); an unlimited dimension grows; scale_factor, add_offset and
    _FillValue (for NaN) applied in reverse."""
    nargchk(args, 3, 5, 'ncwrite')
    p = _path(args[0], 'ncwrite')
    name = py_str(args[1])
    data = args[2]
    f = await _open(p, 'ncwrite', 'a' if _sniff(p) != 'netcdf4' else 'r+')
    try:
        if not f.has_var(name):
            raise err('MATLAB:imagesci:netcdf:unknownLocation', f"Could not find variable '{name}' in file (nccreate makes it).", 'ncwrite')
        shape = f.var_shape(name)
        dt = f.var_dtype(name)
        n = len(shape)
        if np.dtype(dt).kind == 'S':
            ca = np.asarray((data if isinstance(data, Char) else Char.of(py_str(data))).a)
            codes = np.where(ca < 256, ca, ord('?')).astype(np.uint8)     # a byte for each character
            if n <= 1:
                c_data = codes.reshape(-1, order='F').view('S1')
            else:
                c_data = np.ascontiguousarray(codes.T).view('S1')
            lang_shape = ca.shape
        elif np.dtype(dt).kind == 'O':
            items = text_list(data)
            c_data = np.array(items, object)
            sh = data.a.shape if isinstance(data, Str) else (len(items), 1)
            c_data = np.transpose(np.array(items, object).reshape(sh, order='F')) if n > 1 else c_data.reshape(-1)
            lang_shape = sh
        else:
            a = np.asarray(darr(data)) if not isinstance(data, np.ndarray) else data
            if a.dtype == bool:
                a = a.astype(np.uint8)
            lang_shape = a.shape
            if n <= 1:
                c_data = a.reshape(-1)
            else:
                full = list(a.shape) + [1] * max(0, n - a.ndim)
                c_data = np.transpose(a.reshape(full[:n] if len(full) >= n else full))
            c_data = _pack(c_data, f.var_attrs(name), dt)
        if n == 0:
            f.write(name, None, np.asarray(c_data).reshape(()))
        else:
            start = np.asarray(darr(args[3]), float).reshape(-1) if len(args) > 3 else np.ones(n)
            stride = np.asarray(darr(args[4]), float).reshape(-1) if len(args) > 4 else np.ones(n)
            if start.size != n or stride.size != n:
                raise err('MATLAB:imagesci:ncwrite:badStart', f'start and stride have an element for each of the {n} dimensions.', 'ncwrite')
            cs = np.asarray(c_data).shape if n > 1 else (np.asarray(c_data).size,)
            cs = tuple(cs) + (1,) * (n - len(cs))
            idx = []
            for k in range(n):
                kk = n - 1 - k                           # the file's dimension for the language's k
                a0, st = int(start[k]) - 1, int(stride[k])
                cnt = cs[kk]
                idx.append((kk, slice(a0, a0 + (cnt - 1) * st + 1, st)))
            sl = tuple(s for _, s in sorted(idx))
            for i, s in enumerate(sl):
                if s.stop > shape[i] and isinstance(f, _Classic) and not (i == 0 and f.f.variables[name].isrec):
                    raise err('MATLAB:imagesci:ncwrite:outOfRange', 'The data go past the end of a fixed dimension.', 'ncwrite')
            f.write(name, sl, np.asarray(c_data).reshape(cs))
    finally:
        f.close()
    _changed(p)
    return None


@bi('ncwriteatt', arr=False)
async def ncwriteatt(nargout, *args):
    """ncwriteatt(filename, location, attname, attvalue): an attribute written to a variable, or to the file when location is '/'."""
    nargchk(args, 4, 4, 'ncwriteatt')
    p = _path(args[0], 'ncwriteatt')
    loc, att, v = py_str(args[1]), py_str(args[2]), args[3]
    kind = _sniff(p)
    f = await _open(p, 'ncwriteatt', 'a' if kind != 'netcdf4' else 'r+')
    try:
        target = None if loc in ('/', '') else loc
        if target is not None and not f.has_var(target):
            raise err('MATLAB:imagesci:netcdf:unknownLocation', f"Could not find variable or group '{loc}' in file.", 'ncwriteatt')
        if isinstance(v, (Char, Str)):
            val = py_str(v) if isinstance(f, _HDF) else py_str(v).encode()
            if isinstance(f, _Classic):
                val = py_str(v)
        else:
            a = np.asarray(arr(v, 'ncwriteatt'))
            if a.dtype == bool:
                a = a.astype(np.int8)
            if isinstance(f, _Classic) and a.dtype.kind == 'u':
                raise err('MATLAB:imagesci:ncwriteatt:badType', 'A classic file holds no unsigned attributes.', 'ncwriteatt')
            val = a.reshape(-1) if a.size != 1 else a.reshape(-1)[0]
            if att == '_FillValue' and target is not None:
                val = np.asarray(val, dtype=f.var_dtype(target)).reshape(-1)[0]
        f.set_attr(target, att, val)
    finally:
        f.close()
    _changed(p)
    return None
