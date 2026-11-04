"""Indexing: A(i,j), A{i} and A.f, read and written.

Indices count from 1 and run down the columns first. A single index runs
over every element (linear indexing); two or more index the dimensions, the
last one running over every dimension past it. Writing past the end grows an
array (padding with zeros, blanks, [] or missing); writing [] deletes.

Reads of A{i} and A.f can give several values (a comma-separated list), so
cidx and fld return lists; cidx1 and fld1 are the one-value forms.
"""
import math
import re

import numpy as np

from .values import (MError, NOVAL, COLON, Char, Cell, Struct, Str, FH, Obj, F64, C128,
                     INT_TYPES, DTYPE_CLASS, class_of, scalar_out, EMPTY, share, share_all, is_shared,
                     writable, copy_container, _2d, numel, shape_of, is_empty_double, Sparse)
from .ops import to_int_class, INT_CLASSES

_DF = np.dtype(np.float64)
_DB = np.dtype(np.bool_)
_DC = np.dtype(np.complex128)


def _bad_index(v=None):
    return MError('MATLAB:badsubscript', 'Array indices must be positive integers or logical values.')


def _exceeds(n):
    return MError('MATLAB:badsubscript', f'Index exceeds the number of array elements. Index must not exceed {n}.')


def _exceeds_pos(k, n):
    return MError('MATLAB:badsubscript', f'Index in position {k} exceeds array bounds. Index must not exceed {n}.')


def _sz(sh):
    return '-by-'.join(str(d) for d in sh)


def conv(v):
    """An index as (COLON, None) or (0-based intp array, the index's shape,
    the length a logical index covers)."""
    t = type(v)
    if v is COLON:
        return COLON, None, 0
    if t is float:
        i = int(v) if v == v and v not in (math.inf, -math.inf) else -1
        if i != v or i < 1:
            raise _bad_index()
        return np.array([i - 1], np.intp), (1, 1), 0
    if t is bool:
        return (np.array([0], np.intp), (1, 1), 1) if v else (np.zeros(0, np.intp), (0, 0), 1)
    if t is np.ndarray:
        k = v.dtype.kind
        if k == 'b':
            f = np.flatnonzero(v.reshape(-1, order='F'))
            if v.ndim == 2 and v.shape[0] == 1:
                sh = (1, f.size)
            else:
                sh = (f.size, 1)
            return f.astype(np.intp), sh, v.size
        if k == 'f':
            f = v.reshape(-1, order='F')
            if f.size:
                with np.errstate(invalid='ignore'):
                    fi = f.astype(np.intp)
                if not np.array_equal(fi, f) or fi.min() < 1:
                    raise _bad_index()
                return fi - 1, v.shape, 0
            return np.zeros(0, np.intp), v.shape, 0
        if k in 'iu':
            f = v.reshape(-1, order='F').astype(np.intp)
            if f.size and f.min() < 1:
                raise _bad_index()
            return f - 1, v.shape, 0
        raise _bad_index()
    if t is Char:
        if v.a.size == 1 and int(v.a.reshape(-1)[0]) == 58:
            return COLON, None, 0
        return conv(v.a.astype(F64))
    if t is int:
        return conv(float(v))
    if t is complex:
        raise _bad_index()
    if t is Sparse:
        return conv(v.dense())
    if t is Cell:
        raise MError('MATLAB:badsubscript', 'Unable to use a value of type cell as an index.')
    if t is Str:
        raise MError('MATLAB:badsubscript', 'Unable to use a value of type string as an index.')
    raise MError('MATLAB:badsubscript', f'Unable to use a value of type {class_of(v)} as an index.')


def _is_vec_shape(sh):
    return len(sh) == 2 and (sh[0] == 1 or sh[1] == 1)


def endv(A, k, n):
    """The value of `end` in index position k (0-based) of n."""
    sh = shape_of(A) if A is not NOVAL else (0, 0)
    if n == 1:
        p = 1
        for d in sh:
            p *= d
        return float(p)
    if k < n - 1:
        return float(sh[k]) if k < len(sh) else 1.0
    p = 1
    for d in sh[k:]:
        p *= d
    return float(p)


# ---- reading: the arrays under any value ----------------------------------------

def _lin_shape(Ash, ishape, count):
    """The shape of A(I) for linear indexing."""
    if ishape is None:
        return (count, 1)
    if _is_vec_shape(ishape):
        if _is_vec_shape(Ash) and not (Ash[0] == 1 and Ash[1] == 1):
            return (1, count) if Ash[0] == 1 else (count, 1)
        return ishape if ishape[0] * ishape[1] == count else ((1, count) if ishape[0] == 1 else (count, 1))
    return ishape


def lin_take(arr, ix, ishape, cover):
    """arr(I) for any numpy array (numbers or objects)."""
    n = arr.size
    if ix is COLON:
        return arr.reshape(-1, 1, order='F').copy() if arr.ndim > 1 or True else arr
    if cover and cover > n:
        if ix.size and ix.max() >= n:
            raise _exceeds(n)
    if ix.size and ix.max() >= n:
        raise _exceeds(n)
    sh = arr.shape
    if len(sh) == 2 and (sh[0] == 1 or sh[1] == 1):
        r = arr.reshape(-1)[ix]
    elif ix.size:
        r = arr[np.unravel_index(ix, sh, order='F')]
    else:
        r = arr.reshape(-1)[:0]
    return r.reshape(_lin_shape(sh, ishape, ix.size), order='F')


def sub_take(arr, ixs):
    """arr(i1, i2, ...) for any numpy array, two or more indices."""
    sh = arr.shape
    n = len(ixs)
    if n < arr.ndim:
        p = 1
        for d in sh[n - 1:]:
            p *= d
        eff = sh[:n - 1] + (p,)
        arr = arr.reshape(eff, order='F')
    elif n > arr.ndim:
        eff = sh + (1,) * (n - arr.ndim)
        arr = arr.reshape(eff)
    else:
        eff = sh
    arrays = 0
    for k, ix in enumerate(ixs):
        if ix is not COLON:
            arrays += 1
            if ix.size and ix.max() >= eff[k]:
                raise _exceeds_pos(k + 1, eff[k])
    if arrays <= 1:
        sel = tuple(slice(None) if ix is COLON else ix for ix in ixs)
        r = arr[sel]
        if arrays == 0:
            r = r.copy()
    else:
        sel = np.ix_(*[np.arange(eff[k]) if ix is COLON else ix for k, ix in enumerate(ixs)])
        r = arr[sel]
    return _2d(r)


def take(arr, args):
    """arr(args...) on a numpy array, for every kind of index."""
    n = len(args)
    if n == 0:
        return arr
    if n == 1:
        ix, ish, cover = conv(args[0])
        return lin_take(arr, ix, ish, cover)
    return sub_take(arr, [conv(a)[0] for a in args])


class _NoSym:
    pass


# symbolic values (symbolic.py sets these)
SYM = _NoSym
SYMOPS = None
VOBJ = _NoSym          # vobj.VObj (vobj.py sets it)


def idx(A, args):
    """A(args...): a part of an array, cell or struct."""
    t = type(A)
    if t is np.ndarray:
        n = len(args)
        if n == 1:
            i = args[0]
            if type(i) is float and A.ndim == 2:
                k = int(i) if i == i and i not in (math.inf, -math.inf) else 0
                if k == i and k >= 1:
                    if k <= A.size:
                        r0 = A.shape[0]
                        k -= 1
                        if A.dtype is _DF or A.dtype is _DB or A.dtype is _DC:
                            return A.item(k % r0, k // r0)
                        a, b = k % r0, k // r0
                        return A[a:a + 1, b:b + 1].copy()
                    raise _exceeds(A.size)
        elif n == 2:
            i, j = args
            if type(i) is float and type(j) is float and A.ndim == 2:
                ii, jj = int(i) if i == i and abs(i) != math.inf else 0, int(j) if j == j and abs(j) != math.inf else 0
                if ii == i and jj == j and ii >= 1 and jj >= 1:
                    if ii > A.shape[0]:
                        raise _exceeds_pos(1, A.shape[0])
                    if jj > A.shape[1]:
                        raise _exceeds_pos(2, A.shape[1])
                    if A.dtype is _DF or A.dtype is _DB or A.dtype is _DC:
                        return A.item(ii - 1, jj - 1)
                    return A[ii - 1:ii, jj - 1:jj].copy()
        r = take(A, args)
        if r.size == 1:
            return scalar_out(r)
        return r
    if t is SYM:
        return SYMOPS.idx(A, args)
    if t is Sparse:
        from . import sparsemat
        return sparsemat.idx(A, args)
    if t is float or t is bool or t is complex:
        r = take(np.array([[A]]), args)
        if r.size == 1:
            return scalar_out(r)
        return r
    if t is Char:
        return Char(take(A.a, args))
    if t is Cell:
        r = take(A.a, args)
        share_all(r)
        return Cell(r)
    if t is Str:
        return Str(take(A.a, args))
    if t is Struct:
        return struct_take(A, args)
    if isinstance(A, Obj):
        f = getattr(A, 'index', None)
        if f is not None:
            return f(args)
        from .graphics_base import HArr
        r = take(A.a if isinstance(A, HArr) else np.array([[A]], object), args)
        if r.size == 1:
            return r.reshape(-1)[0]
        return HArr(r)
    if isinstance(A, FH):
        raise MError('MATLAB:fhIndex', 'Function handles must be called with parentheses, not indexed.')
    if t is int:
        return idx(float(A), args)
    raise MError('MATLAB:badsubscript', f'Indexing is not supported for values of class {class_of(A)}.')


def struct_take(S, args):
    pos = np.arange(S.size).reshape(S.shape, order='F') if S.shape else np.zeros((0, 0), int)
    sel = take(pos, args)
    f = {}
    for k, a in S.f.items():
        a2 = a.reshape(-1, order='F')[sel.reshape(-1, order='F')].reshape(sel.shape, order='F')
        share_all(a2)
        f[k] = a2
    return Struct(sel.shape, f)


def cidx(A, args):
    """A{args...}: the elements as a list (several for a range)."""
    t = type(A)
    if t is Cell:
        a = A.a
        if len(args) == 1 and type(args[0]) is float and a.ndim == 2:
            i = args[0]
            k = int(i) if i == i and abs(i) != math.inf else 0
            if k == i and 1 <= k:
                if k > a.size:
                    raise _exceeds(a.size)
                k -= 1
                return [a.item(k % a.shape[0], k // a.shape[0])]
        r = take(a, args)
        return list(r.reshape(-1, order='F'))
    if t is Str:
        r = take(A.a, args)
        return [Char.of('' if s is None else s) for s in r.reshape(-1, order='F')]
    if A is NOVAL:
        raise MError('MATLAB:UndefinedFunction', 'Unrecognized variable.')
    if isinstance(A, Obj) and hasattr(A, 'brace'):
        return A.brace(args)
    raise MError('MATLAB:cellRefFromNonCell', 'Brace indexing is not supported for variables of this type.')


def one(vals, what='curly brace'):
    if len(vals) == 1:
        return vals[0]
    if not vals:
        raise MError('MATLAB:needMoreRhsOutputs', 'Insufficient number of outputs from right hand side of equal sign to satisfy assignment.')
    raise MError('MATLAB:index:expected_one_output_from_expression',
                 f'Expected one output from a {what} or dot indexing expression, but there were {len(vals)} results.')


def cidx1(A, args):
    if type(A) is Cell and len(args) == 1 and type(args[0]) is float:
        a = A.a
        i = args[0]
        k = int(i) if i == i and abs(i) != math.inf else 0
        if k == i and 1 <= k <= a.size and a.ndim == 2:
            k -= 1
            return a.item(k % a.shape[0], k // a.shape[0])
    return one(cidx(A, args), 'curly brace')


def fld(A, name):
    """A.name: the field of every element of a struct array, as a list."""
    t = type(A)
    if t is Struct:
        a = A.f.get(name)
        if a is None:
            raise MError('MATLAB:nonExistentField', f'Unrecognized field name "{name}".')
        return list(a.reshape(-1, order='F'))
    if isinstance(A, Obj):
        each = getattr(A, 'fld_list', None)
        if each is not None:
            # an object array of its own (test results, suites): a value for each element
            return each(name)
        arr_ = getattr(A, 'a', None)
        if isinstance(arr_, np.ndarray) and arr_.dtype == object and getattr(A, 'is_handle', False):
            return [h.getprop(name) for h in arr_.reshape(-1, order='F')]
        return [A.getprop(name)]
    if A is NOVAL:
        raise MError('MATLAB:UndefinedFunction', 'Unrecognized variable.')
    raise MError('MATLAB:structRefFromNonStruct', 'Dot indexing is not supported for variables of this type.')


def fld1(A, name):
    if type(A) is Struct and A.shape == (1, 1):
        a = A.f.get(name)
        if a is None:
            raise MError('MATLAB:nonExistentField', f'Unrecognized field name "{name}".')
        return a.item(0)
    if isinstance(A, Obj):
        return A.getprop(name)
    return one(fld(A, name), 'curly brace')


def dyn_name(v):
    """The name in A.(expr)."""
    t = type(v)
    if t is Char:
        return field_name(v.str())
    if t is Str and v.a.size == 1 and v.a.flat[0] is not None:
        return field_name(v.a.flat[0])
    raise MError('MATLAB:dynamicFieldName', 'Dynamic structure field names must be character vectors or string scalars.')


_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]*')


def field_name(name, fn=None):
    """A field's name as given, if it is a name (a letter, then letters,
    digits and underscores): the desktop writes field names into code."""
    if not _NAME.fullmatch(name):
        e = MError('MATLAB:InvalidFieldName', f'Invalid field name "{name}".')
        e.fn = fn
        raise e
    return name


# ---- writing --------------------------------------------------------------------

def _region(cur_shape, ixs, linear, vshape, nv):
    """For A(ixs) = V: the index arrays along each dimension, the shape the
    array must grow to, and the region's shape."""
    if linear:
        ix = ixs[0]
        n = 1
        for d in cur_shape:
            n *= d
        if ix is COLON:
            if n == 0:
                # x(:) = v on an empty x takes v's elements
                return [np.arange(nv)], (vshape if len(vshape) == 2 else (nv, 1)), (nv,)
            return [np.arange(n)], cur_shape, (n,)
        m = int(ix.max()) + 1 if ix.size else 0
        if m <= n:
            return [ix], cur_shape, (ix.size,)
        sh = cur_shape
        if n == 0:
            new = (m, 1) if (len(sh) == 2 and sh[1] == 1 and sh[0] == 0) else (1, m)
        elif len(sh) == 2 and sh[0] == 1:
            new = (1, m)
        elif len(sh) == 2 and sh[1] == 1:
            new = (m, 1)
        else:
            raise MError('MATLAB:indexed:ambiguousGrow', 'Attempt to grow array along ambiguous dimension.')
        return [ix], new, (ix.size,)
    nidx = len(ixs)
    sh = list(cur_shape) + [1] * max(0, nidx - len(cur_shape))
    if nidx < len(cur_shape):
        p = 1
        for d in cur_shape[nidx - 1:]:
            p *= d
        sh = list(cur_shape[:nidx - 1]) + [p]
        collapsed = True
    else:
        collapsed = False
    empty = all(d == 0 for d in cur_shape) or (1 in (0,) and False) or (numel_of_shape(cur_shape) == 0)
    lens = []
    unknown = []
    for k, ix in enumerate(ixs):
        if ix is COLON:
            if sh[k] == 0 and empty:
                lens.append(None)
                unknown.append(k)
            else:
                lens.append(sh[k])
        else:
            lens.append(ix.size)
    if unknown:
        known = 1
        for L in lens:
            if L is not None:
                known *= L
        vdims = [d for d in vshape if d != 1]
        if len(unknown) == 1:
            L = (nv // known) if known else 0
            lens[unknown[0]] = L
        else:
            # several open dimensions take v's dimensions in order
            vs = list(vshape) + [1] * (nidx - len(vshape))
            for k in unknown:
                lens[k] = vs[k]
    new = list(sh)
    out_ix = []
    for k, ix in enumerate(ixs):
        if ix is COLON:
            L = lens[k]
            if L > new[k]:
                new[k] = L
            out_ix.append(np.arange(L))
        else:
            m = int(ix.max()) + 1 if ix.size else 0
            if m > new[k]:
                if collapsed and k == nidx - 1 and len(cur_shape) > nidx:
                    raise MError('MATLAB:indexed:ambiguousGrow', 'Attempt to grow array along ambiguous dimension.')
                new[k] = m
            out_ix.append(ix)
    if collapsed:
        if tuple(new) != tuple(sh):
            raise MError('MATLAB:indexed:ambiguousGrow', 'Attempt to grow array along ambiguous dimension.')
        new_shape = tuple(cur_shape)
    else:
        new_shape = tuple(new)
        while len(new_shape) > 2 and new_shape[-1] == 1:
            new_shape = new_shape[:-1]
    return out_ix, new_shape, tuple(len(i) for i in out_ix)


def numel_of_shape(sh):
    n = 1
    for d in sh:
        n *= d
    return n


def _squeeze(sh):
    return [d for d in sh if d != 1]


def _grow(arr, new_shape, fill):
    """A new array of new_shape holding arr in its leading corner."""
    if arr.shape == tuple(new_shape):
        return arr
    out = np.empty(new_shape, arr.dtype)
    if fill is not None:
        if arr.dtype == object:
            for i in range(out.size):
                out.flat[i] = fill()
        else:
            out.fill(fill)
    if arr.size:
        src = arr
        if src.ndim < len(new_shape):
            src = src.reshape(src.shape + (1,) * (len(new_shape) - src.ndim))
        elif src.ndim > len(new_shape):
            src = src.reshape(src.shape[:len(new_shape) - 1] + (-1,), order='F')
        sel = tuple(slice(0, d) for d in src.shape)
        out[sel] = src
    return out


def _put(arr, ixs, linear, region, vals, vshape):
    """arr(ixs) = vals in place (arr already has its final shape)."""
    count = numel_of_shape(region)
    nv = vals.size
    if linear:
        ix = ixs[0]
        if nv == 1:
            v = vals.reshape(-1)[0]
        elif nv == count:
            v = vals.reshape(-1, order='F')
        else:
            raise MError('MATLAB:index:assignmentWithSizeMismatch' if False else 'MATLAB:subsassignnumelmismatch',
                         'Unable to perform assignment because the left and right sides have a different number of elements.')
        sh = arr.shape
        if arr.dtype == object:
            # objects go in one by one: numpy would spread an array value out
            flat_pos = np.asarray(ix, np.intp).reshape(-1)
            rows = np.unravel_index(flat_pos, sh, order='F')
            for k in range(flat_pos.size):
                arr[tuple(r[k] for r in rows)] = v if nv == 1 else v[k]
            return
        if len(sh) == 2 and (sh[0] == 1 or sh[1] == 1):
            arr.reshape(-1)[ix] = v
        else:
            arr[np.unravel_index(ix, sh, order='F')] = v
        return
    shape = arr.shape
    nidx = len(ixs)
    if nidx != arr.ndim:
        if nidx < arr.ndim:
            p = 1
            for d in shape[nidx - 1:]:
                p *= d
            view_shape = shape[:nidx - 1] + (p,)
        else:
            view_shape = shape + (1,) * (nidx - arr.ndim)
        target = arr.reshape(view_shape, order='F' if nidx < arr.ndim else 'C')
        if nidx < arr.ndim and not np.shares_memory(target, arr):
            # an F-order reshape of a C array copies: work on the copy, then put it back
            target = target.copy()
            _put_sub(target, ixs, region, vals, vshape, count, nv)
            arr[...] = target.reshape(shape, order='F')
            return
    else:
        target = arr
    _put_sub(target, ixs, region, vals, vshape, count, nv)


def _put_sub(target, ixs, region, vals, vshape, count, nv):
    if nv == 1:
        v = vals.reshape(-1)[0]
    elif nv == count and _squeeze(vshape) == _squeeze(region):
        v = vals.reshape(region, order='F')
    else:
        raise MError('MATLAB:subsassigndimmismatch',
                     f'Unable to perform assignment because the size of the left side is {_sz(region)} and the size of the right side is {_sz(vshape)}.')
    if target.dtype == object:
        import itertools
        vv = v if nv != 1 else None
        for pos in itertools.product(*[range(len(ix)) for ix in ixs]):
            where = tuple(int(ix[p]) for ix, p in zip(ixs, pos))
            target[where] = v if nv == 1 else vv[pos]
        return
    sel = np.ix_(*ixs)
    target[sel] = v


# the class an assignment leaves
def _assign_class(ca, cv):
    if ca == cv:
        return ca
    if ca == 'logical':
        return cv if cv != 'char' else 'double'
    if cv in INT_CLASSES:
        return cv if ca in ('double', 'single', 'logical') else ca
    if ca in INT_CLASSES:
        return ca
    if ca == 'char':
        return 'char' if cv in ('double', 'logical', 'single') else cv
    if ca == 'double':
        if cv == 'single':
            return 'single'
        return 'double'
    if ca == 'single':
        return 'single'
    return ca


def _np_of(v):
    """(numbers, class) of a numeric/logical/char value for assignment."""
    t = type(v)
    if t is float:
        return np.array([[v]]), 'double'
    if t is bool:
        return np.array([[v]]), 'logical'
    if t is complex:
        return np.array([[v]], C128), 'double'
    if t is np.ndarray:
        return v, DTYPE_CLASS.get(v.dtype, 'double')
    if t is Char:
        return v.a, 'char'
    if t is int:
        return np.array([[float(v)]]), 'double'
    if getattr(v, 'is_graphics', False):
        # h = zeros(1, 3); h(2) = line(...) keeps the line's handle number
        items = v.a if hasattr(v, 'a') else np.array([[v]], object)
        return np.vectorize(lambda o: o.number_value() if o is not None else math.nan, otypes=[float])(items), 'double'
    return None, class_of(v)


def _convert(a, cls, cplx):
    """Numbers as the array of a class (cplx: keep a complex part)."""
    if cls == 'double':
        if cplx or a.dtype.kind == 'c':
            return a.astype(C128) if cplx else a.real.astype(F64)
        return a.astype(F64, copy=False)
    if cls == 'single':
        return a.astype(np.complex64 if (cplx or a.dtype.kind == 'c') else np.float32)
    if cls == 'logical':
        return a.astype(bool)
    if cls == 'char':
        if a.dtype == np.uint16:
            return a
        x = np.asarray(a.real if a.dtype.kind == 'c' else a, F64)
        return np.clip(np.nan_to_num(np.round(x), nan=0), 0, 65535).astype(np.uint16)
    return to_int_class(a.real if a.dtype.kind == 'c' else a, cls)


_FILL = {'double': 0.0, 'single': 0.0, 'logical': False, 'char': 0}


def _empty_like_value(V):
    """What `x(i) = V` grows from when x does not exist yet (or is [])."""
    t = type(V)
    if t is Cell:
        return Cell.empty()
    if t is Struct:
        return Struct.empty((0, 0), V.keys)
    if t is Str:
        return Str(np.empty((0, 0), object))
    if t is Char:
        return Char(np.zeros((0, 0), np.uint16))
    if t is np.ndarray:
        return np.zeros((0, 0), V.dtype)
    if t is bool:
        return np.zeros((0, 0), bool)
    if t is complex:
        return np.zeros((0, 0), C128)
    if isinstance(V, VOBJ):
        return V.empty_like()
    if isinstance(V, Obj):
        from .graphics_base import HArr
        return HArr(np.empty((0, 0), object))
    if isinstance(V, FH):
        raise MError('MATLAB:fhNonScalar', 'Nonscalar arrays of function handles are not allowed; use cell arrays instead.')
    return np.zeros((0, 0))


def _conv_args(args):
    if len(args) == 1:
        ix, _, cover = conv(args[0])
        return [ix], True
    return [conv(a)[0] for a in args], False


def asgn(A, args, V):
    """A(args...) = V. Returns the array that the name now holds."""
    if getattr(V, 'is_missing', False) and not getattr(A, 'is_missing', False):
        # missing becomes the missing value of the array it goes in
        V = V.like(EMPTY() if A is NOVAL else A)
    t = type(A)
    # the fast path: one element of a double array, in place
    if t is np.ndarray and A.flags.writeable and A.ndim == 2 and A.dtype is _DF and type(V) is float:
        if len(args) == 1:
            i = args[0]
            if type(i) is float:
                k = int(i) if i == i and abs(i) != math.inf else 0
                if k == i and 1 <= k <= A.size:
                    k -= 1
                    r0 = A.shape[0]
                    A[k % r0, k // r0] = V
                    return A
        elif len(args) == 2:
            i, j = args
            if type(i) is float and type(j) is float:
                ii = int(i) if i == i and abs(i) != math.inf else 0
                jj = int(j) if j == j and abs(j) != math.inf else 0
                if ii == i and jj == j and 1 <= ii <= A.shape[0] and 1 <= jj <= A.shape[1]:
                    A[ii - 1, jj - 1] = V
                    return A
    if not args:
        # x() = v replaces x
        return V
    if t is SYM or type(V) is SYM:
        return SYMOPS.asgn(A, args, V)
    if t is Sparse or type(V) is Sparse:
        from . import sparsemat
        if t is Sparse and is_empty_double(V):
            return sparsemat.delete(A, args)
        return sparsemat.asgn(A, args, V)
    if A is NOVAL:
        if is_empty_double(V):
            return EMPTY()
        A = _empty_like_value(V)
        t = type(A)
    elif t is np.ndarray and A.size == 0 and A.dtype is _DF and (type(V) in (Cell, Struct, Str) or getattr(V, 'is_graphics', False) or isinstance(V, VOBJ)):
        # h = []; h(1) = plot(...) makes a graphics array
        A = _empty_like_value(V)
        t = type(A)
    if getattr(A, 'own_assign', False):
        # an object that takes every assignment itself (a dictionary: [] takes a key out)
        return A.index_assign(args, V)
    # deletion
    if is_empty_double(V) and t is not Cell or (t is Char and type(V) is Char and V.a.shape == (0, 0)) or (t is Cell and is_empty_double(V)):
        return delete(A, args)
    if t in (float, bool, complex) or t is np.ndarray or (t is Char and type(V) is not Str and type(V) is not Cell):
        return _asgn_numeric(A, args, V)
    if t is Cell:
        if type(V) is not Cell:
            raise MError('MATLAB:invalidConversion', f'Conversion to cell from {class_of(V)} is not possible.')
        C = writable(A)
        ixs, linear = _conv_args(args)
        vals = V.a
        ixs2, new_shape, region = _region(C.a.shape, ixs, linear, vals.shape, vals.size)
        arr = _grow(C.a, new_shape, EMPTY)
        if arr is C.a and not linear:
            pass
        _put(arr, ixs2, linear, region, vals, vals.shape)
        C.a = arr
        share_all(vals)
        return C
    if t is Struct:
        return _asgn_struct(A, args, V)
    if t is Str or type(V) is Str:
        from .strings import to_str_array
        S = writable(A) if t is Str else to_str_array(A)
        Vs = to_str_array(V)
        ixs, linear = _conv_args(args)
        ixs2, new_shape, region = _region(S.a.shape, ixs, linear, Vs.a.shape, Vs.a.size)
        arr = _grow(S.a, new_shape, lambda: None)
        _put(arr, ixs2, linear, region, Vs.a, Vs.a.shape)
        S.a = arr
        return S
    if isinstance(A, Obj):
        f = getattr(A, 'index_assign', None)
        if f is not None:
            return f(args, V)
        from .graphics_base import HArr
        if isinstance(A, HArr) or isinstance(V, Obj):
            return _asgn_handles(A, args, V)
    if isinstance(A, FH):
        raise MError('MATLAB:fhNonScalar', 'Nonscalar arrays of function handles are not allowed; use cell arrays instead.')
    raise MError('MATLAB:invalidAssignment', f'Unable to perform assignment to a value of class {class_of(A)}.')


def _asgn_handles(A, args, V):
    from .graphics_base import HArr
    arrA = A.a if isinstance(A, HArr) else np.array([[A]], object)
    if isinstance(V, HArr):
        vals = V.a
    elif isinstance(V, Obj):
        vals = np.array([[V]], object)
    else:
        raise MError('MATLAB:invalidAssignment', f'Unable to assign a value of class {class_of(V)} into an array of objects.')
    ixs, linear = _conv_args(args)
    ixs2, new_shape, region = _region(arrA.shape, ixs, linear, vals.shape, vals.size)
    arr = _grow(arrA.copy(), new_shape, lambda: None)
    _put(arr, ixs2, linear, region, vals, vals.shape)
    return HArr(arr)


def _asgn_numeric(A, args, V):
    ta = type(A)
    if ta is Char:
        arrA, ca = A.a, 'char'
        own = not A.ro
    elif ta is np.ndarray:
        arrA, ca = A, DTYPE_CLASS.get(A.dtype, 'double')
        own = A.flags.writeable
    else:
        arrA, ca = _np_of(A)
        own = True
    vals, cv = _np_of(V)
    if vals is None:
        if type(V) is Cell:
            # x = 5; x(2) = {1}: the numbers become a cell first
            if arrA.size == 0:
                return asgn(Cell.empty(), args, V)
            raise MError('MATLAB:invalidConversion', f'Conversion to {ca} from cell is not possible.')
        if type(V) is Struct:
            if arrA.size == 0:
                return asgn(Struct.empty((0, 0), V.keys), args, V)
            raise MError('MATLAB:invalidConversion', f'Conversion to {ca} from struct is not possible.')
        raise MError('MATLAB:invalidConversion', f'Conversion to {ca} from {cv} is not possible.')
    cls = _assign_class(ca, cv)
    cplx = arrA.dtype.kind == 'c' or vals.dtype.kind == 'c'
    if cplx and cls in INT_CLASSES:
        cplx = False
    if cls != ca or (cplx and arrA.dtype.kind != 'c'):
        arrA = _convert(arrA, cls, cplx)
        own = True
    vals = _convert(vals, cls, cplx)
    ixs, linear = _conv_args(args)
    ixs2, new_shape, region = _region(arrA.shape, ixs, linear, vals.shape, vals.size)
    if tuple(new_shape) != arrA.shape:
        fill = 0 if cls not in _FILL else _FILL[cls]
        arrA = _grow(arrA, new_shape, fill)
    elif not own:
        arrA = arrA.copy()
    _put(arrA, ixs2, linear, region, vals, vals.shape)
    if cls == 'char':
        if ta is Char and arrA is A.a:
            return A
        return Char(arrA)
    if cls == 'double' and arrA.dtype.kind == 'c':
        if not np.any(arrA.imag):
            arrA = np.ascontiguousarray(arrA.real)
    if arrA.size == 1 and arrA.ndim == 2 and (arrA.dtype is _DF or arrA.dtype is _DB or arrA.dtype is _DC):
        return scalar_out(arrA)
    return arrA


def _asgn_struct(A, args, V):
    if type(V) is not Struct:
        if is_empty_double(V):
            return delete(A, args)
        raise MError('MATLAB:invalidConversion', f'Conversion to struct from {class_of(V)} is not possible.')
    S = writable(A)
    keys_a = list(S.f)
    keys_v = list(V.f)
    if S.size == 0 and not keys_a:
        keys_a = keys_v
        S.f = {k: np.empty(S.shape, object) for k in keys_v}
    elif set(keys_a) != set(keys_v):
        if S.size == 0:
            S.f = {k: np.empty(S.shape, object) for k in keys_v}
            keys_a = keys_v
        else:
            raise MError('MATLAB:heterogeneousStrucAssignment', 'Subscripted assignment between dissimilar structures.')
    ixs, linear = _conv_args(args)
    ixs2, new_shape, region = _region(S.shape, ixs, linear, V.shape, V.size)
    nf = {}
    for k in keys_a:
        arr = S.f[k]
        if arr.shape != S.shape:
            arr = arr.reshape(S.shape)
        arr = _grow(arr, new_shape, EMPTY)
        vals = V.f[k]
        _put(arr, ixs2, linear, region, vals, V.shape)
        share_all(vals)
        nf[k] = arr
    S.f = nf
    S.shape = tuple(new_shape)
    return S


def delete(A, args):
    """A(args) = []."""
    t = type(A)
    if isinstance(A, VOBJ):
        return A.delete(args)
    if t is Sparse:
        from . import sparsemat
        return sparsemat.delete(A, args)
    if t is float or t is bool or t is complex:
        A = np.array([[A]])
        t = np.ndarray
    if t is np.ndarray:
        arrs = [A]
    elif t in (Char, Cell, Str):
        arrs = [A.a]
    elif t is Struct:
        arrs = [A.f[k] for k in A.f] or [np.empty(A.shape, object)]
    else:
        from .graphics_base import HArr
        if isinstance(A, HArr):
            arrs = [A.a]
        else:
            raise MError('MATLAB:invalidDeletion', f'Deleting elements of a value of class {class_of(A)} is not possible.')
    shape = arrs[0].shape
    ixs, linear = _conv_args(args)
    if linear:
        ix = ixs[0]
        n = numel_of_shape(shape)
        if ix is COLON:
            out = [a.reshape(-1)[:0].reshape(0, 0) for a in arrs]
            new_shape = (0, 0)
        else:
            if ix.size and ix.max() >= n:
                raise _exceeds(n)
            keep = np.ones(n, bool)
            keep[ix] = False
            out = [a.reshape(-1, order='F')[keep] for a in arrs]
            k = int(keep.sum())
            if len(shape) == 2 and shape[1] == 1 and shape[0] != 1:
                new_shape = (k, 1)
            elif not ix.size:
                new_shape = shape
                out = [a for a in arrs]
            else:
                new_shape = (1, k)
            out = [o.reshape(new_shape, order='F') if o.shape != new_shape else o for o in out]
    else:
        nidx = len(ixs)
        if nidx < len(shape):
            p = numel_of_shape(shape[nidx - 1:])
            eff = shape[:nidx - 1] + (p,)
        else:
            eff = shape + (1,) * (nidx - len(shape))
        which = None
        for k, ix in enumerate(ixs):
            if ix is COLON:
                continue
            if ix.size and ix.max() >= eff[k]:
                raise _exceeds_pos(k + 1, eff[k])
            full = ix.size >= eff[k] and np.array_equal(np.unique(ix), np.arange(eff[k]))
            if full and which is not None:
                continue
            if which is not None:
                if full:
                    continue
                raise MError('MATLAB:nullAssignment', 'A null assignment can have only one non-colon index.')
            which = k
            if full:
                # a full index deletes every element along it
                pass
        if which is None:
            # every index covers everything: all is deleted along the last
            which = nidx - 1
        keep = np.ones(eff[which], bool)
        if ixs[which] is not COLON:
            keep[ixs[which]] = False
        else:
            keep[:] = False
        out = []
        for a in arrs:
            a2 = a.reshape(eff, order='F') if a.shape != eff else a
            a2 = np.compress(keep, a2, axis=which)
            if nidx < len(shape):
                if which != nidx - 1:
                    a2 = a2.reshape(a2.shape[:nidx - 1] + shape[nidx - 1:], order='F')
            out.append(_2d(a2))
        new_shape = out[0].shape
    if t is np.ndarray:
        r = out[0]
        return scalar_out(r) if r.size == 1 and r.ndim == 2 else r
    if t is Char:
        return Char(out[0])
    if t is Cell:
        return Cell(out[0])
    if t is Str:
        return Str(out[0])
    if t is Struct:
        if A.f:
            return Struct(new_shape, dict(zip(A.f.keys(), out)))
        return Struct(new_shape, {})
    from .graphics_base import HArr
    return HArr(out[0])


def casgn(A, args, V):
    """A{args} = V."""
    t = type(A)
    if t is Cell and not A.ro and len(args) == 1 and type(args[0]) is float:
        a = A.a
        i = args[0]
        k = int(i) if i == i and abs(i) != math.inf else 0
        if k == i and 1 <= k <= a.size and a.ndim == 2:
            k -= 1
            a[k % a.shape[0], k // a.shape[0]] = V
            return A
    if A is NOVAL or (t is np.ndarray and A.size == 0) or (t is Char and A.a.size == 0):
        # x = []; x{1} = v, and the same for '' (a list box's String when it lists nothing)
        A = Cell.empty()
        t = Cell
    if t is Str:
        from .strings import to_str_array
        Vs = to_str_array(V)
        if Vs.a.size != 1:
            raise MError('MATLAB:invalidAssignment', 'Unable to perform assignment: the right side must be one string.')
        return asgn(A, args, Vs)
    if t is not Cell and hasattr(A, 'brace_assign'):
        return A.brace_assign(args, V)
    if t is not Cell:
        raise MError('MATLAB:cellAssToNonCell', 'Unable to perform assignment because brace indexing is not supported for variables of this type. Use parentheses instead.')
    C = writable(A)
    ixs, linear = _conv_args(args)
    count = 1
    for ix in ixs:
        if ix is COLON:
            count *= -1
        else:
            count *= ix.size
    vals = np.empty((1, 1), object)
    vals[0, 0] = V
    ixs2, new_shape, region = _region(C.a.shape, ixs, linear, (1, 1), 1)
    if numel_of_shape(region) != 1:
        raise MError('MATLAB:cellAssignmentMultiple', 'Unable to perform assignment: brace indexing on the left side must name exactly one element. Use deal to assign several.')
    arr = _grow(C.a, new_shape, EMPTY)
    _put(arr, ixs2, linear, region, vals, (1, 1))
    C.a = arr
    return C


def fasgn(A, name, V):
    """A.name = V."""
    t = type(A)
    if t is Struct and not A.ro and A.shape == (1, 1):
        a = A.f.get(name)
        if a is not None:
            a[0, 0] = V
            return A
        a = np.empty((1, 1), object)
        a[0, 0] = V
        A.f[name] = a
        return A
    if A is NOVAL or is_empty_double(A):
        S = Struct((1, 1))
        a = np.empty((1, 1), object)
        a[0, 0] = V
        S.f[name] = a
        return S
    if t is Struct:
        if A.size != 1:
            if A.size == 0:
                S = Struct((1, 1), {k: np.empty((1, 1), object) for k in A.f})
                for arr in S.f.values():
                    arr[0, 0] = EMPTY()
                return fasgn(S, name, V)
            raise MError('MATLAB:scalarStructRequired', 'Scalar structure required for this assignment.')
        S = writable(A)
        return fasgn(S, name, V)
    if isinstance(A, Obj):
        # a value object changes in a copy of its own
        if not A.is_handle and hasattr(A, 'value_copy'):
            A = A.value_copy()
        A.setprop(name, V)
        return A
    raise MError('MATLAB:structAssToNonStruct', 'Unable to perform assignment because dot indexing is not supported for variables of this type.')


# ---- chains: s.a(2).b{3} = v ---------------------------------------------------

def _sub_for_assign(A, kind, key):
    """The part of A a chain goes into, or NOVAL when it is not there yet."""
    if A is NOVAL or is_empty_double(A) or (kind == '{}' and type(A) is Char and A.a.size == 0):
        return NOVAL
    t = type(A)
    if kind == '.':
        if t is Struct:
            if A.size != 1:
                raise MError('MATLAB:scalarStructRequired', 'Scalar structure required for this assignment.')
            a = A.f.get(key)
            return NOVAL if a is None else a.item(0)
        if isinstance(A, Obj):
            return A.getprop(key)
        raise MError('MATLAB:structAssToNonStruct', 'Unable to perform assignment because dot indexing is not supported for variables of this type.')
    if kind == '{}':
        if t is not Cell:
            raise MError('MATLAB:cellAssToNonCell', 'Unable to perform assignment because brace indexing is not supported for variables of this type. Use parentheses instead.')
        ixs, linear = _conv_args(key)
        arr = A.a
        try:
            if linear:
                ix = ixs[0]
                if ix is COLON or ix.size != 1:
                    raise MError('MATLAB:cellAssignmentMultiple', 'Unable to perform assignment: brace indexing on the left side must name exactly one element.')
                if ix[0] >= arr.size:
                    return NOVAL
                return lin_take(arr, ix, (1, 1), 0).reshape(-1)[0]
            for k, ix in enumerate(ixs):
                d = arr.shape[k] if k < arr.ndim else 1
                if ix is not COLON and ix.size and ix.max() >= d:
                    return NOVAL
            r = sub_take(arr, ixs)
            if r.size != 1:
                raise MError('MATLAB:cellAssignmentMultiple', 'Unable to perform assignment: brace indexing on the left side must name exactly one element.')
            return r.reshape(-1)[0]
        except MError as e:
            if e.identifier == 'MATLAB:badsubscript':
                return NOVAL
            raise
    # '()': an element of an array, typically of a struct array
    try:
        if t is Struct:
            pos = np.arange(A.size).reshape(A.shape, order='F')
            sel = take(pos, key)
            if sel.size != 1:
                raise MError('MATLAB:scalarStructRequired', 'Scalar structure required for this assignment.')
            i = int(sel.reshape(-1)[0])
            f = {}
            for k, a in A.f.items():
                x = np.empty((1, 1), object)
                x[0, 0] = a.reshape(-1, order='F')[i]
                f[k] = x
            return Struct((1, 1), f)
        return idx(A, key)
    except MError as e:
        if e.identifier == 'MATLAB:badsubscript':
            if t is Struct:
                return Struct((1, 1), {k: _empty_obj() for k in A.f})
            return NOVAL
        raise


def _empty_obj():
    a = np.empty((1, 1), object)
    a[0, 0] = EMPTY()
    return a


def asgn1(A, kind, key, V):
    if kind == '()':
        return asgn(A, key, V)
    if kind == '{}':
        return casgn(A, key, V)
    return fasgn(A, key, V)


def asgn_chain(A, steps, V):
    """A<steps> = V for a chain of (kind, key) steps: kind '()', '{}' or '.';
    a key that is callable gets the value it indexes (for `end`)."""
    kind, key = steps[0]
    if callable(key):
        key = key(A)
    if len(steps) == 1:
        return asgn1(A, kind, key, V)
    sub = _sub_for_assign(A, kind, key)
    if sub is not NOVAL and is_shared(A):
        share(sub)
    new = asgn_chain(sub, steps[1:], V)
    if isinstance(A, Obj) and kind == '.' and getattr(A, 'is_handle', False) and new is sub:
        return A
    if kind == '()' and type(A) is Struct and type(new) is Struct and steps[1][0] == '.':
        # s(k).f = v with a field the struct array lacks: every element gets it (empty but there)
        extra = [k for k in new.f if k not in A.f]
        if extra:
            A = writable(A)
            for k in extra:
                arr = np.empty(A.shape, object)
                for i in range(arr.size):
                    arr.flat[i] = EMPTY()
                A.f[k] = arr
    return asgn1(A, kind, key, new)


def cs_count(A, key):
    """How many values a field target s.f (or s(key).f) of a multiple assignment takes: one for each element of a struct array."""
    if type(A) is not Struct:
        return 1
    if key is None:
        return max(A.size, 1) if A.size else 1
    pos = np.arange(A.size).reshape(A.shape, order='F')
    try:
        return max(int(take(pos, key).size), 1)
    except MError:
        return 1


def cs_assign(A, key, name, vals):
    """[s.f] = ... or [s(key).f] = ...: each element's field set to its value in turn (the field added when it is new)."""
    vals = list(vals)
    if type(A) is not Struct or (A.size <= 1 and key is None):
        return asgn_chain(A, (('.', name),), vals[0]) if key is None else asgn_chain(A, (('()', key), ('.', name)), vals[0])
    pos = np.arange(A.size).reshape(A.shape, order='F')
    sel = pos.reshape(-1, order='F') if key is None else take(pos, key).reshape(-1, order='F')
    if len(vals) != sel.size:
        raise MError('MATLAB:deal:narginchk', 'The number of outputs should match the number of elements on the left.')
    for p, v in zip(sel, vals):
        A = asgn_chain(A, (('()', (float(p + 1),)), ('.', name)), v)
    return A


def get_chain(A, steps):
    """A<steps> read as one value (used for compound reads)."""
    for kind, key in steps:
        if callable(key):
            key = key(A)
        if kind == '()':
            A = idx(A, key)
        elif kind == '{}':
            A = cidx1(A, key)
        else:
            A = fld1(A, key)
    return A
