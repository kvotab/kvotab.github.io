"""Cell arrays, structs, maps, and calling a function on every element
(cellfun, arrayfun, structfun)."""
import math

import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, sval, ival, num, is_str, bool_out,
                    like_class, dims_from, cellstr_list)
from ..values import (MError, NOVAL, Char, Cell, Struct, Str, FH, Obj, F64, C128, class_of, shape_of, numel,
                      _2d, EMPTY, py_str, share, share_all, scalar_out, Sparse)
from ..ops import cat as _cat
from ..index import field_name
from .. import runtime as R


# ---- cells -------------------------------------------------------------------------------

@bi('cell')
def cell(nargout, *args):
    shape, _, _ = dims_from(args, 'cell', allow_class=False) if args else ((0, 0), None, None)
    return Cell.filled(shape)


@bi('num2cell')
def num2cell(nargout, *args):
    nargchk(args, 1, 2, 'num2cell')
    v = args[0]
    if len(args) > 1:
        dims = [int(d) - 1 for d in arr(args[1]).reshape(-1)]
        a = arr(v)
        if any(d < 0 for d in dims):
            raise err('MATLAB:num2cell:InvalidDim', 'The dimensions must be positive integers.', 'num2cell')
        a = a.reshape(a.shape + (1,) * max(0, max(dims, default=0) + 1 - a.ndim))
        shape = list(a.shape)
        for d in dims:
            shape[d] = 1
        res = np.empty(shape, object)
        for idx in np.ndindex(*shape):
            sl = tuple(slice(None) if k in dims else slice(i, i + 1) for k, i in enumerate(idx))
            res[idx] = like_class(a[sl], v)
        return Cell(_2d(res))
    t = type(v)
    if t is Cell:
        r = np.empty(v.a.shape, object)
        for i in range(v.a.size):
            r.flat[i] = Cell.of_list([v.a.flat[i]])
        return Cell(r)
    if t is Struct:
        from ..index import struct_take
        return Cell.of_list([struct_take(v, (float(i + 1),)) for i in range(v.size)], v.shape)
    if t is Char:
        r = np.empty(v.a.shape, object)
        for i, c in enumerate(v.a.flat):
            r.flat[i] = Char(np.array([[c]], np.uint16))
        return Cell(r)
    if t is Str:
        r = np.empty(v.a.shape, object)
        for i, s in enumerate(v.a.flat):
            r.flat[i] = Str.of(s)
        return Cell(r)
    a = arr(v)
    r = np.empty(a.shape, object)
    klass = class_of(v)
    for i in range(a.size):
        x = a.flat[i]
        r.flat[i] = like_class(np.array([[x]], a.dtype), v)
    return Cell(r)


@bi('cell2mat')
def cell2mat(nargout, *args):
    nargchk(args, 1, 1, 'cell2mat')
    c = args[0]
    if type(c) is not Cell:
        raise err('MATLAB:cell2mat:WrongInputType', 'Input must be a cell array.' if True else '', 'cell2mat')
    if c.a.size == 0:
        return EMPTY()
    for x in c.a.flat:
        if type(x) is Cell or isinstance(x, (FH,)):
            raise err('MATLAB:cell2mat:UnsupportedCellContent', 'CELL2MAT does not support cell arrays containing cell arrays or objects.', 'cell2mat')
    def build(a):
        # rows of a page joined side by side, then stacked; pages joined along
        # the higher dimensions, the last one last
        if a.ndim <= 2:
            return _cat(0, [_cat(1, list(r)) for r in a.reshape(a.shape[0], -1)])
        return _cat(a.ndim - 1, [build(a[..., k]) for k in range(a.shape[-1])])
    return build(c.a)


@bi('cell2struct')
def cell2struct(nargout, *args):
    nargchk(args, 2, 3, 'cell2struct')
    c = args[0]
    fields = cellstr_list(args[1]) if type(args[1]) in (Cell, Str) else (args[1].row_strs() if type(args[1]) is Char and args[1].a.shape[0] > 1 else [py_str(args[1])])
    dim = ival(args[2]) - 1 if len(args) > 2 else 0
    a = c.a
    if a.ndim == 1:
        a = a.reshape(-1, 1)
    a2 = np.moveaxis(a, dim, 0)
    if a2.shape[0] != len(fields):
        raise err('MATLAB:cell2struct:FieldNameAndCellMismatch', 'Number of field names must match number of fields in new structure.', 'cell2struct')
    for f in fields:
        field_name(f, 'cell2struct')
    rest = a2.shape[1:]
    shape = rest if len(rest) >= 2 else (rest[0], 1) if rest else (1, 1)
    s = Struct(shape, {})
    for k, f in enumerate(fields):
        arrf = np.empty(shape, object)
        flat = a2[k].reshape(-1)
        for i in range(flat.size):
            arrf.reshape(-1)[i] = flat[i]
        share_all(arrf)
        s.f[f] = arrf
    return s


@bi('struct2cell')
def struct2cell(nargout, *args):
    s = args[0]
    if type(s) is not Struct:
        raise err('MATLAB:struct2cell:InputMustBeStruct', 'Input must be a struct.', 'struct2cell')
    keys = list(s.f)
    shape = (len(keys),) + tuple(s.shape)
    a = np.empty(shape, object)
    for k, f in enumerate(keys):
        a[k] = s.f[f]
    share_all(a)
    return Cell(_2d(a.reshape(len(keys), -1)) if s.shape == (1, 1) else a)


# ---- structs --------------------------------------------------------------------------------

@bi('struct')
def struct(nargout, *args):
    if not args:
        return Struct((1, 1))
    if len(args) == 1:
        v = args[0]
        if type(v) is np.ndarray and v.size == 0:
            return Struct((0, 0))
        if type(v) is Struct:
            return v
        if isinstance(v, Obj):
            return Struct.scalar({k: v.getprop(k) for k in v.propnames()})
        raise err('MATLAB:struct:InvalidArgument', 'Field and value input arguments must come in pairs.', 'struct')
    if len(args) % 2:
        raise err('MATLAB:struct:FieldValuePairs', 'Field and value input arguments must come in pairs.', 'struct')
    names = []
    vals = []
    shape = None
    for i in range(0, len(args), 2):
        name = field_name(sval(args[i], 'field name', 'struct'), 'struct')
        v = args[i + 1]
        names.append(name)
        vals.append(v)
        if type(v) is Cell and v.a.size != 1:
            if shape is None:
                shape = v.a.shape
            elif shape != v.a.shape:
                raise err('MATLAB:struct:fieldsizeMismatch', 'Array dimensions of input cell arrays must match.' if True else '', 'struct')
    if shape is None:
        shape = (1, 1)
    s = Struct(shape, {})
    for name, v in zip(names, vals):
        a = np.empty(shape, object)
        if type(v) is Cell:
            if v.a.size == 1:
                x = v.a.flat[0]
                for i in range(a.size):
                    a.flat[i] = share(x)
            else:
                a[...] = v.a
                share_all(a)
        else:
            share(v)
            for i in range(a.size):
                a.flat[i] = v
        s.f[name] = a
    return s


@bi('fieldnames')
def fieldnames(nargout, *args):
    nargchk(args, 1, 2, 'fieldnames')
    s = args[0]
    if type(s) is Struct:
        keys = list(s.f)
    elif isinstance(s, Obj):
        keys = s.propnames()
    else:
        raise err('MATLAB:fieldnames:InvalidInput', 'Invalid input argument of type \'' + class_of(s) + '\'. Input must be a structure or a Java or COM object.', 'fieldnames')
    return Cell.of_list([Char.of(k) for k in keys], (len(keys), 1))


@bi('isfield')
def isfield(nargout, *args):
    nargchk(args, 2, 2, 'isfield')
    s, f = args
    if type(s) is not Struct:
        return False
    if type(f) is Cell or (type(f) is Str and f.a.size != 1):
        names = cellstr_list(f)
        return out(np.array([n in s.f for n in names], bool).reshape(shape_of(f), order='F'))
    if not is_str(f):
        return False
    return py_str(f) in s.f


@bi('isprop')
def isprop(nargout, *args):
    nargchk(args, 2, 2, 'isprop')
    s, f = args
    if isinstance(s, Obj):
        return py_str(f) in s.propnames()
    return False


@bi('rmfield')
def rmfield(nargout, *args):
    nargchk(args, 2, 2, 'rmfield')
    s = args[0]
    if type(s) is not Struct:
        raise err('MATLAB:rmfield:InvalidInput', 'Input must be a structure.', 'rmfield')
    names = cellstr_list(args[1]) if type(args[1]) in (Cell, Str) else [py_str(args[1])]
    f = dict(s.f)
    for n in names:
        if n not in f:
            raise err('MATLAB:rmfield:InvalidFieldname', f'Unrecognized field name "{n}".' if False else f"A field named '{n}' doesn't exist.", 'rmfield')
        del f[n]
    for a in f.values():
        share_all(a)
    return Struct(s.shape, f)


@bi('setfield')
def setfield(nargout, *args):
    s = args[0]
    names = [field_name(py_str(a), 'setfield') for a in args[1:-1] if is_str(a)]
    if not names:
        raise err('MATLAB:setfield:NoFieldName', 'Give the name of the field to set.', 'setfield')
    from ..index import fasgn, asgn_chain
    steps = tuple(('.', n) for n in names)
    v = args[-1]
    return asgn_chain(s, steps, share(v))


@bi('getfield')
def getfield(nargout, *args):
    s = args[0]
    from ..index import fld1, idx
    v = s
    for a in args[1:]:
        if type(a) is Cell:
            v = idx(v, tuple(a.a.flat))
        else:
            v = fld1(v, py_str(a))
    return v


@bi('orderfields', nout=2)
def orderfields(nargout, *args):
    s = args[0]
    if type(s) is not Struct:
        raise err('MATLAB:orderfields:InvalidInput', 'The first input must be a struct.', 'orderfields')
    keys = list(s.f)
    if len(args) > 1:
        o = args[1]
        if type(o) is Struct:
            order = list(o.f)
        elif type(o) in (Cell, Str):
            order = cellstr_list(o)
        else:
            perm = [int(x) - 1 for x in arr(o).reshape(-1)]
            order = [keys[p] for p in perm]
    else:
        order = sorted(keys)
    f = {k: s.f[k] for k in order}
    for a in f.values():
        share_all(a)
    res = Struct(s.shape, f)
    if nargout >= 2:
        return res, out(np.array([keys.index(k) + 1 for k in order], F64).reshape(-1, 1))
    return res


# ---- calling a function on every element ------------------------------------------------------

def _opts(args):
    """Split cellfun/arrayfun's arguments: the data, UniformOutput and
    ErrorHandler."""
    data = []
    uniform = True
    handler = None
    i = 0
    while i < len(args):
        s = opt_str(args[i])
        if s is not None and s.lower() in ('uniformoutput', 'errorhandler') and i + 1 < len(args):
            if s.lower() == 'uniformoutput':
                uniform = bool(arr(args[i + 1]).reshape(-1)[0]) if type(args[i + 1]) is not Char else py_str(args[i + 1]).lower() in ('true', '1')
            else:
                handler = args[i + 1]
            i += 2
            continue
        data.append(args[i])
        i += 1
    return data, uniform, handler


def _collect(results, shape, nout, uniform, fname):
    """The outputs of cellfun/arrayfun from the per-element results."""
    outs = []
    for k in range(nout):
        vals = [r[k] for r in results]
        if uniform:
            if not vals:
                outs.append(np.zeros(shape))
                continue
            klass = None
            for i, v in enumerate(vals):
                if numel(v) != 1 or type(v) in (Cell, Struct, Str) and False:
                    raise err('MATLAB:' + fname + ':NotAScalarOutput',
                              f"Non-scalar in Uniform output, at index {i + 1}, output {k + 1}.\nSet 'UniformOutput' to false.", fname)
                if type(v) is Cell or isinstance(v, FH):
                    raise err('MATLAB:' + fname + ':NotAScalarOutput',
                              f"Non-scalar in Uniform output, at index {i + 1}, output {k + 1}.\nSet 'UniformOutput' to false.", fname)
            first = vals[0]
            c0 = class_of(first)
            for i, v in enumerate(vals):
                if class_of(v) != c0:
                    if not (class_of(v) in ('double', 'logical') and c0 in ('double', 'logical')):
                        raise err('MATLAB:' + fname + ':MismatchInOutputTypes', f"Mismatch in type of outputs, at index {i + 1}, output {k + 1} ({class_of(v)} versus {c0}).\nSet 'UniformOutput' to false.", fname)
            if c0 == 'struct':
                keys = list(first.f)
                for i, v in enumerate(vals):
                    if list(v.f) != keys and set(v.f) != set(keys):
                        raise err('MATLAB:' + fname + ':MismatchInOutputTypes', f"Mismatch in the fields of the structs, at index {i + 1}, output {k + 1}.\nSet 'UniformOutput' to false.", fname)
                S = Struct(tuple(shape), {kk: np.empty(tuple(shape), object) for kk in keys})
                for i, v in enumerate(vals):
                    for kk in keys:
                        S.f[kk].reshape(-1, order='F')[i] = v.f[kk].reshape(-1)[0]
                outs.append(S)
            elif c0 == 'char':
                a = np.array([int(v.a.reshape(-1)[0]) for v in vals], np.uint16).reshape(shape, order='F')
                outs.append(Char(_2d(a)))
            elif c0 == 'string':
                outs.append(Str.from_list([v.a.flat[0] for v in vals], shape))
            elif isinstance(first, Obj):
                from ..graphics_base import HArr
                a = np.empty(len(vals), object)
                for i, v in enumerate(vals):
                    a[i] = v
                outs.append(HArr(a.reshape(shape, order='F')))
            else:
                classes = set(class_of(v) for v in vals)
                if classes == {'logical'}:
                    a = np.array([bool(arr(v).reshape(-1)[0]) for v in vals], bool)
                else:
                    flat = [arr(v).reshape(-1)[0] for v in vals]
                    a = np.array(flat)
                    if a.dtype.kind == 'b':
                        a = a.astype(F64)
                a = a.reshape(shape, order='F')
                outs.append(like_class(a, first) if c0 not in ('logical', 'double') else out(a))
        else:
            outs.append(Cell.of_list([share(v) for v in vals], shape))
    return outs


async def _call_each(f, items, nargout, handler, fname):
    # asked for no output, the function is asked for none either, as a call
    # at statement level is: disp or set give nothing, plot no handle, and
    # what does give a value (x*2, a file's function) gives it as ans
    want = nargout
    results = []
    for i, a in enumerate(items):
        try:
            r = await f.acall(want, *a) if isinstance(f, FH) else None
        except MError as e:
            if handler is None:
                raise
            st = Struct.scalar({'message': Char.of(e.message), 'identifier': Char.of(e.identifier), 'index': float(i + 1)})
            r = await handler.acall(want, st, *a)
        if nargout == 0 and r is None:
            results.append(None)
            continue
        if want <= 1:
            results.append((r,))
        else:
            results.append(tuple(r))
        if R.tk():
            await R.H(None, 0, '')
    if nargout == 0 and all(r is None for r in results):
        return None
    if nargout == 0:
        results = [r if r is not None else (EMPTY(),) for r in results]
    return results


_SPECIAL = {
    'isempty': lambda v: numel(v) == 0,
    'islogical': lambda v: class_of(v) == 'logical',
    'isreal': lambda v: not (type(v) is complex or (type(v) is np.ndarray and v.dtype.kind == 'c')) and type(v) not in (Cell, Struct, Str),
    'length': lambda v: float(0 if 0 in shape_of(v) else max(shape_of(v))),
    'ndims': lambda v: float(len(shape_of(v))),
    'prodofsize': lambda v: float(numel(v)),
    'numel': lambda v: float(numel(v)),
}


@bi('cellfun', aw=True, nout=99, arr=False)
async def cellfun(nargout, *args):
    nargchk(args, 2, None, 'cellfun')
    f = args[0]
    if is_str(f) and py_str(f) in ('size', 'isclass'):
        # the old forms cellfun('size', C, k) and cellfun('isclass', C, name)
        name = py_str(f)
        nargchk(args, 3, 3, 'cellfun')
        c = args[1]
        if type(c) is not Cell:
            raise err('MATLAB:cellfun:NotACell', 'Input #2 expected to be a cell array, was ' + class_of(c) + ' instead.', 'cellfun')
        items = c.a.reshape(-1, order='F')
        if name == 'size':
            k = int(num(args[2]))
            vals = [float(shape_of(x)[k - 1]) if k <= len(shape_of(x)) else 1.0 for x in items]
            return out(np.array(vals, F64).reshape(c.a.shape, order='F'))
        cls = py_str(args[2])
        return out(np.array([class_of(x) == cls for x in items], bool).reshape(c.a.shape, order='F'))
    data, uniform, handler = _opts(args[1:])
    if not data:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'cellfun')
    for c in data:
        if type(c) is not Cell:
            raise err('MATLAB:cellfun:NotACell', 'Input #2 expected to be a cell array, was ' + class_of(c) + ' instead.', 'cellfun')
    shape = data[0].a.shape
    for c in data[1:]:
        if c.a.shape != shape:
            raise err('MATLAB:cellfun:ArgumentSizeMismatch', 'All of the input arguments must be of the same size and shape.\nPrevious inputs had size ' + 'x'.join(map(str, shape)) + ', input #' + '3' + ' has size ' + 'x'.join(map(str, c.a.shape)) + '.', 'cellfun')
    cols = [c.a.reshape(-1, order='F') for c in data]
    n = cols[0].size
    if is_str(f):
        name = py_str(f)
        sp = _SPECIAL.get(name)
        if sp is not None:
            vals = [sp(x) for x in cols[0]]
            return out(np.array(vals).reshape(shape, order='F'))
        f = R.NamedFH(name)
    if not isinstance(f, FH):
        raise err('MATLAB:cellfun:InvalidFunction', 'Invalid function. The first input must be a function handle or a function name.', 'cellfun')
    if isinstance(f, R.NamedFH) and f.fname in _SPECIAL and f.target is None and not R._user_file(f.fname) and nargout <= 1 and uniform:
        sp = _SPECIAL[f.fname]
        return out(np.array([sp(x) for x in cols[0]]).reshape(shape, order='F'))
    items = [tuple(c[i] for c in cols) for i in range(n)]
    results = await _call_each(f, items, nargout, handler, 'cellfun')
    if results is None:
        return None
    nout = max(nargout, 1)
    outs = _collect(results, shape, nout, uniform, 'cellfun')
    return outs[0] if nargout <= 1 else tuple(outs)


def _elements(v):
    """The elements of any array for arrayfun, one value each."""
    t = type(v)
    if t is float or t is bool or t is complex:
        return [v]
    if t is np.ndarray:
        flat = v.reshape(-1, order='F')
        if v.dtype.kind in 'fbc' and v.dtype in (np.dtype(F64), np.dtype(bool), np.dtype(C128)):
            return [x.item() for x in flat]
        return [flat[i:i + 1].reshape(1, 1) for i in range(flat.size)]
    if t is Char:
        flat = v.a.reshape(-1, order='F')
        return [Char(flat[i:i + 1].reshape(1, 1)) for i in range(flat.size)]
    if t is Cell:
        flat = v.a.reshape(-1, order='F')
        res = []
        for x in flat:
            a = np.empty((1, 1), object)
            a[0, 0] = x
            res.append(Cell(a))
        return res
    if t is Struct:
        from ..index import struct_take
        return [struct_take(v, (float(i + 1),)) for i in range(v.size)]
    if t is Str:
        return [Str.of(s) for s in v.a.reshape(-1, order='F')]
    if isinstance(v, Obj) and hasattr(v, 'a'):
        return list(v.a.reshape(-1, order='F'))
    if t is Sparse:
        # each element a sparse 1-by-1 matrix
        from ..sparsemat import idx
        return [idx(v, (float(i + 1),)) for i in range(numel(v))]
    return [v]


@bi('arrayfun', aw=True, nout=99, arr=False)
async def arrayfun(nargout, *args):
    nargchk(args, 2, None, 'arrayfun')
    f = args[0]
    if is_str(f):
        f = R.NamedFH(py_str(f))
    data, uniform, handler = _opts(args[1:])
    shape = shape_of(data[0])
    for d in data[1:]:
        if shape_of(d) != shape:
            raise err('MATLAB:arrayfun:ArgumentSizeMismatch', 'All of the input arguments must be of the same size and shape.', 'arrayfun')
    cols = [_elements(d) for d in data]
    n = len(cols[0])
    items = [tuple(c[i] for c in cols) for i in range(n)]
    results = await _call_each(f, items, nargout, handler, 'arrayfun')
    if results is None:
        return None
    nout = max(nargout, 1)
    outs = _collect(results, shape, nout, uniform, 'arrayfun')
    return outs[0] if nargout <= 1 else tuple(outs)


@bi('structfun', aw=True, nout=99, arr=False)
async def structfun(nargout, *args):
    nargchk(args, 2, None, 'structfun')
    f = args[0]
    data, uniform, handler = _opts(args[1:])
    s = data[0]
    if type(s) is not Struct or s.size != 1:
        raise err('MATLAB:structfun:NotAScalarStruct', 'Input must be a scalar structure.', 'structfun')
    keys = list(s.f)
    items = [(s.f[k].item(0),) for k in keys]
    results = await _call_each(f, items, nargout, handler, 'structfun')
    if results is None:
        return None
    nout = max(nargout, 1)
    if uniform:
        outs = _collect(results, (len(keys), 1), nout, True, 'structfun')
    else:
        outs = []
        for k in range(nout):
            st = Struct((1, 1), {})
            for name, r in zip(keys, results):
                a = np.empty((1, 1), object)
                a[0, 0] = share(r[k])
                st.f[name] = a
            outs.append(st)
    return outs[0] if nargout <= 1 else tuple(outs)


# ---- containers.Map ----------------------------------------------------------------------------

class MapObj(Obj):
    """containers.Map: keys (text or numbers) to values, a handle object."""
    __slots__ = ('d', 'keytype', 'valuetype')
    cls = 'containers.Map'
    is_handle = True

    def __init__(self, keytype='char', valuetype='any'):
        self.d = {}
        self.keytype = keytype
        self.valuetype = valuetype

    def _key(self, k):
        if self.keytype == 'char':
            if not is_str(k):
                raise err('MATLAB:Containers:TypeMismatch', 'Specified key type does not match the type expected for this container.')
            return py_str(k)
        if is_str(k):
            raise err('MATLAB:Containers:TypeMismatch', 'Specified key type does not match the type expected for this container.')
        return float(num(k))

    def _keyval(self, k):
        return Char.of(k) if self.keytype == 'char' else float(k)

    def sorted_keys(self):
        return sorted(self.d)

    def index(self, args):
        if len(args) != 1:
            raise err('MATLAB:Containers:Map:OnlyOneKey', 'Only one level of indexing is supported by a containers.Map.')
        k = self._key(args[0])
        if k not in self.d:
            shown = k if isinstance(k, str) else f'{k:g}'
            raise err('MATLAB:Containers:Map:NoKey', f"The specified key is not present in this container." if False else f"The specified key is not present in this container.")
        return self.d[k]

    def index_assign(self, args, v):
        k = self._key(args[0])
        self.d[k] = share(v)
        return self

    def getprop(self, name):
        if name == 'Count':
            return float(len(self.d))
        if name == 'KeyType':
            return Char.of(self.keytype)
        if name == 'ValueType':
            return Char.of(self.valuetype)
        if name in ('keys', 'values', 'isKey', 'remove', 'length'):
            return R.NamedFH(name, _bound(self, name))
        return super().getprop(name)

    def propnames(self):
        return ['Count', 'KeyType', 'ValueType']

    def display_lines(self):
        return ['  Map with properties:', '', f'        Count: {len(self.d)}', f"      KeyType: {self.keytype}", f"    ValueType: {self.valuetype}"]


def _bound(m, name):
    async def f(nargout, *args):
        return R.BUILTINS[name].fn(nargout, m, *args)
    return f


@bi('containers.Map', arr=False)
def containers_map(nargout, *args):
    args = list(args)
    keytype = 'char'
    valuetype = 'any'
    uniform = True
    opts = {}
    i = 0
    positional = []
    while i < len(args):
        s = opt_str(args[i])
        if s is not None and s in ('KeyType', 'ValueType', 'UniformValues') and i + 1 < len(args):
            opts[s] = args[i + 1]
            i += 2
            continue
        positional.append(args[i])
        i += 1
    if 'KeyType' in opts:
        keytype = py_str(opts['KeyType'])
    if 'ValueType' in opts:
        valuetype = py_str(opts['ValueType'])
    m = MapObj(keytype, valuetype)
    if positional:
        ks = positional[0]
        vs = positional[1] if len(positional) > 1 else None
        if type(ks) in (Cell,):
            klist = list(ks.a.reshape(-1, order='F'))
        elif type(ks) is Str:
            klist = [Char.of(s) for s in ks.a.reshape(-1, order='F')]
        elif is_str(ks):
            klist = [ks]
        else:
            klist = [float(x) for x in arr(ks).reshape(-1, order='F')]
        if klist and not is_str(klist[0]) and 'KeyType' not in opts:
            m.keytype = 'double'
        if vs is None:
            vlist = [EMPTY()] * len(klist)
        elif type(vs) is Cell and len(klist) != 1:
            vlist = list(vs.a.reshape(-1, order='F'))
        elif len(klist) == 1:
            vlist = [vs]
        else:
            vlist = [like_class(np.array([[x]]), vs) for x in arr(vs).reshape(-1, order='F')]
        if len(vlist) != len(klist):
            raise err('MATLAB:Containers:Map:KeyValueNumberMismatch', 'The number of keys and values must be the same.')
        for k, v in zip(klist, vlist):
            m.d[m._key(k)] = share(v)
    return m


@bi('keys')
def keys(nargout, *args):
    m = args[0]
    if not isinstance(m, MapObj):
        raise err('MATLAB:UndefinedFunction', "Undefined function 'keys' for input arguments of type '" + class_of(m) + "'.")
    ks = m.sorted_keys()
    return Cell.of_list([m._keyval(k) for k in ks])


def _map_arg(m, fn):
    if not isinstance(m, MapObj):
        raise err(f'MATLAB:{fn}:NotAMap', 'The first input must be a containers.Map.', fn)


@bi('values')
def values(nargout, *args):
    m = args[0]
    _map_arg(m, 'values')
    if len(args) > 1:
        if type(args[1]) is not Cell:
            raise err('MATLAB:Containers:Map:KeysNotCell', 'The keys must be given in a cell array.', 'values')
        ks = [m._key(k) for k in args[1].a.reshape(-1, order='F')]
        for k in ks:
            if k not in m.d:
                raise err('MATLAB:Containers:Map:NoKey', f"The specified key is not present in this container.")
        return Cell.of_list([m.d[k] for k in ks])
    return Cell.of_list([m.d[k] for k in m.sorted_keys()])


@bi('isKey')
def iskey(nargout, *args):
    m, k = args[0], args[1]
    _map_arg(m, 'isKey')
    if type(k) is Cell:
        return out(np.array([m._key(x) in m.d for x in k.a.reshape(-1, order='F')], bool).reshape(k.a.shape, order='F'))
    try:
        return m._key(k) in m.d
    except MError:
        return False


@bi('remove')
def remove(nargout, *args):
    m, k = args[0], args[1]
    _map_arg(m, 'remove')
    ks = [m._key(x) for x in k.a.reshape(-1, order='F')] if type(k) is Cell else [m._key(k)]
    for kk in ks:
        if kk not in m.d:
            raise err('MATLAB:Containers:Map:NoKey', 'The specified key is not present in this container.')
        del m.d[kk]
    return m



# ---- mat2cell, celldisp -------------------------------------------------------------------------------

@bi('mat2cell')
def mat2cell(nargout, *args):
    """C = mat2cell(A, d1, d2, ...): A cut into blocks, d1 the heights of the
    rows of blocks, d2 the widths of the columns of them and so on (a
    dimension not given is one block)."""
    nargchk(args, 2, None, 'mat2cell')
    v = args[0]
    t = type(v)
    if t is Struct or isinstance(v, (FH, Obj)):
        raise err('MATLAB:mat2cell:invalidInput', 'mat2cell divides arrays, characters and cells here.', 'mat2cell')
    a = v.a if t in (Char, Cell, Str) else np.asarray(arr(v))
    sizes = [np.asarray(arr(d)).reshape(-1).astype(np.intp) for d in args[1:]]
    nd = max(a.ndim, len(sizes))
    a = a.reshape(a.shape + (1,) * (nd - a.ndim))
    while len(sizes) < nd:
        sizes.append(np.array([a.shape[len(sizes)]], np.intp))
    if any(int(s.sum()) != a.shape[k] or np.any(s < 0) for k, s in enumerate(sizes)):
        raise err('MATLAB:mat2cell:dimensionMismatch',
                  f"Input arguments, D1 through D{len(args) - 1}, must sum to each dimension of the input matrix size, [{' '.join(str(x) for x in a.shape)}].", 'mat2cell')
    starts = [np.concatenate([[0], np.cumsum(s)[:-1]]) for s in sizes]
    cells = np.empty(tuple(len(s) for s in sizes), object)
    for idx in np.ndindex(cells.shape):
        sl = tuple(slice(starts[k][i], starts[k][i] + sizes[k][i]) for k, i in enumerate(idx))
        part = _2d(a[sl])
        if t is Char:
            cells[idx] = Char(part)
        elif t is Cell:
            cells[idx] = Cell(part)
        elif t is Str:
            cells[idx] = Str(part)
        else:
            cells[idx] = like_class(part, v) if class_of(v) not in ('double', 'logical') else out(part)
    share_all(cells)
    return Cell(_2d(cells))


@bi('celldisp', ws=True, arr=False)
def celldisp(W, nargout, *args):
    """celldisp(C, name): each element of C shown as name{i} = ..., cells
    inside cells as name{i}{j}; the name is the variable holding C (or
    'ans')."""
    nargchk(args, 1, 2, 'celldisp')
    noout(nargout, 'celldisp')
    c = args[0]
    if type(c) is not Cell:
        raise err('MATLAB:celldisp:notCellArray', 'The input must be a cell array.', 'celldisp')
    if len(args) > 1:
        name = py_str(args[1])
    else:
        name = next((k for k in W.keys() if W.get(k) is c), 'ans') if hasattr(W, 'keys') else 'ans'
    from .. import display as D

    def show(cell, prefix):
        a = cell.a
        vec = a.ndim == 2 and (a.shape[0] == 1 or a.shape[1] == 1)
        for k in range(a.size):
            sub = np.unravel_index(k, a.shape, order='F')
            label = f'{prefix}{{{k + 1}}}' if vec else f"{prefix}{{{','.join(str(i + 1) for i in sub)}}}"
            x = a.reshape(-1, order='F')[k]
            if type(x) is Cell and x.a.size:
                show(x, label)
            else:
                R.write(D.display(label, x))
    show(c, name)
    return None
