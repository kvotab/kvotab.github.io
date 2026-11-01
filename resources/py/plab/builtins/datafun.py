"""Data analysis: sums and products, means and spreads, minima and maxima,
sorting, sets, histograms, cumulative and difference operations.

Reductions work down the first dimension that is not 1 unless a dimension
is given ('all' takes every element). min and max leave NaN out unless
'includenan' is given; sum, mean and the rest keep it unless 'omitnan'.
"""
import math

import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, sval, ival, num, is_str, bool_out,
                    like_class, first_dim, dim_arg, reduce, strip_flags, expand_dims, cellstr_list, to_cell_of_char)
from ..values import (MError, NOVAL, Char, Cell, Struct, Str, F64, C128, INT_TYPES, DTYPE_CLASS, class_of,
                      shape_of, numel, _2d, scalar_out, EMPTY, share_all, py_str)
from ..ops import finish, INT_CLASSES, align, check_bcast


def _dim_and_flags(args, flags, fn):
    """(dim or None or 'all', flags found) from the arguments after the
    data."""
    rest, found = strip_flags(args, flags)
    dim = None
    if rest:
        d = rest[0]
        if not (type(d) is np.ndarray and d.size == 0):
            dim = dim_arg(d, fn)
    return dim, found, rest


def _num_input(v, fn):
    t = type(v)
    if t in (Cell, Struct, Str):
        raise err('MATLAB:UndefinedFunction', f"Invalid data type. First argument must be numeric or logical.", fn)
    return arr(v, fn)


def _vecdims(a, dim):
    """Dimensions to reduce over when dim is a vector."""
    return dim


# ---- sums and products ---------------------------------------------------------------

def _sum_like(name, fn, ident):
    def f(nargout, *args):
        nargchk(args, 1, 4, name)
        x = args[0]
        if type(x) is float:
            if len(args) == 1:
                return x
        a = _num_input(x, name)
        dim, flags, rest = _dim_and_flags(args[1:], ('omitnan', 'includenan', 'double', 'native', 'default'), name)
        klass = class_of(x)
        if klass in INT_CLASSES and 'double' not in flags:
            outcls = klass
        elif klass == 'single' and 'double' not in flags:
            outcls = 'single'
        elif 'native' in flags and klass in ('logical',):
            outcls = 'logical' if name == 'sum' and False else 'double'
        else:
            outcls = 'double'
        if a.dtype.kind in 'iu':
            A = a.astype(np.float64)
        elif a.dtype.kind == 'b' or a.dtype == np.uint16:
            A = a.astype(F64)
        else:
            A = a
        omit = 'omitnan' in flags
        if omit and A.dtype.kind in 'fc':
            A = np.where(np.isnan(A), ident, A)
        with np.errstate(all='ignore'):
            r = reduce(A, dim, lambda b, ax: fn(b, axis=ax))
        return finish(np.asarray(r), outcls)
    f.__name__ = name
    bi(name)(f)


_sum_like('sum', np.sum, 0)
_sum_like('prod', np.prod, 1)


def _cum(name, fn):
    def f(nargout, *args):
        nargchk(args, 1, 4, name)
        x = args[0]
        a = _num_input(x, name)
        dim, flags, rest = _dim_and_flags(args[1:], ('reverse', 'forward', 'omitnan', 'includenan'), name)
        if dim is None:
            dim = first_dim(a.shape)
        A = expand_dims(a, dim)
        if A.dtype.kind in 'iub' or A.dtype == np.uint16:
            A = A.astype(F64)
        if 'omitnan' in flags and A.dtype.kind in 'fc':
            A = np.where(np.isnan(A), 0 if name == 'cumsum' else 1, A)
        with np.errstate(all='ignore'):
            if 'reverse' in flags:
                r = np.flip(fn(np.flip(A, dim), axis=dim), dim)
            else:
                r = fn(A, axis=dim)
        return like_class(r, x) if class_of(x) not in ('logical', 'char') else out(r)
    f.__name__ = name
    bi(name)(f)


_cum('cumsum', np.cumsum)
_cum('cumprod', np.cumprod)


def _cumext(name, ufunc):
    def f(nargout, *args):
        x = args[0]
        a = _num_input(x, name)
        dim, flags, rest = _dim_and_flags(args[1:], ('reverse', 'forward', 'omitnan', 'includenan'), name)
        if dim is None:
            dim = first_dim(a.shape)
        A = expand_dims(a, dim).astype(F64) if a.dtype.kind not in 'f' else expand_dims(a, dim)
        if 'reverse' in flags:
            A = np.flip(A, dim)
        with np.errstate(all='ignore'):
            # NaN does not stop the running value unless includenan
            if 'includenan' in flags:
                r = ufunc.accumulate(A, axis=dim)
            else:
                fill = -np.inf if name == 'cummax' else np.inf
                B = np.where(np.isnan(A), fill, A)
                r = ufunc.accumulate(B, axis=dim)
                lead = np.logical_and.accumulate(np.isnan(A), axis=dim)
                r = np.where(lead, np.nan, r)
        if 'reverse' in flags:
            r = np.flip(r, dim)
        return like_class(r, x)
    f.__name__ = name
    bi(name)(f)


_cumext('cummax', np.maximum)
_cumext('cummin', np.minimum)


@bi('diff')
def diff(nargout, *args):
    nargchk(args, 1, 3, 'diff')
    x = args[0]
    a = _num_input(x, 'diff')
    n = ival(args[1], 'order', 'diff') if len(args) > 1 and numel(args[1]) else 1
    if len(args) > 2:
        dim = dim_arg(args[2], 'diff')
    else:
        dim = None
    A = a.astype(F64) if a.dtype.kind in 'biu' or a.dtype == np.uint16 else a
    for _ in range(n):
        d = dim if dim is not None else first_dim(A.shape)
        if A.ndim <= d or A.shape[d] <= 1:
            sh = list(A.shape) + [1] * max(0, d + 1 - A.ndim)
            sh[d] = 0
            if dim is None and A.size <= 1:
                return np.zeros((0, 0))
            A = np.zeros(sh, A.dtype)
            break
        A = np.diff(A, axis=d)
    return like_class(A, x) if class_of(x) not in ('logical', 'char') else out(A)


# ---- means and spreads -------------------------------------------------------------------

@bi('mean')
def mean(nargout, *args):
    nargchk(args, 1, 4, 'mean')
    x = args[0]
    if getattr(x, 'is_probdist', False):
        return x.moment('mean')
    if type(x) is float and len(args) == 1:
        return x
    a = _num_input(x, 'mean')
    dim, flags, rest = _dim_and_flags(args[1:], ('omitnan', 'includenan', 'double', 'native', 'default'), 'mean')
    A = a.astype(F64) if a.dtype.kind in 'biu' or a.dtype == np.uint16 else a
    with np.errstate(all='ignore'):
        if 'omitnan' in flags:
            r = reduce(A, dim, lambda b, ax: np.nanmean(b, axis=ax) if b.shape[ax] else np.full(np.delete(np.array(b.shape), ax), np.nan))
        else:
            r = reduce(A, dim, lambda b, ax: np.mean(b, axis=ax) if b.shape[ax] else np.full([s for i, s in enumerate(b.shape) if i != ax], np.nan))
    klass = class_of(x)
    if klass == 'single':
        return finish(r, 'single')
    if klass in INT_CLASSES and 'native' in flags:
        return finish(r, klass)
    return out(np.asarray(r))


@bi('median')
def median(nargout, *args):
    nargchk(args, 1, 3, 'median')
    x = args[0]
    if getattr(x, 'is_probdist', False):
        return x.moment('median')
    a = _num_input(x, 'median')
    dim, flags, rest = _dim_and_flags(args[1:], ('omitnan', 'includenan'), 'median')
    A = a.astype(F64) if a.dtype.kind in 'biu' or a.dtype == np.uint16 else a
    with np.errstate(all='ignore'):
        def med(b, ax):
            if b.shape[ax] == 0:
                return np.full([s for i, s in enumerate(b.shape) if i != ax], np.nan)
            if 'omitnan' in flags:
                return np.nanmedian(b, axis=ax)
            r = np.median(b, axis=ax)
            return r
        r = reduce(A, dim, med)
    return like_class(np.asarray(r), x) if class_of(x) in ('single',) else out(np.asarray(r))


@bi('mode', nout=3)
def mode(nargout, *args):
    nargchk(args, 1, 2, 'mode')
    x = args[0]
    a = _num_input(x, 'mode')
    dim = dim_arg(args[1], 'mode') if len(args) > 1 else None
    if dim is None:
        if a.shape == (0, 0):
            return math.nan if nargout <= 1 else (math.nan, 0.0, Cell.of_list([np.zeros((0, 0))]))
        dim = first_dim(a.shape)
    A = expand_dims(a, dim)
    A2 = np.moveaxis(A, dim, -1)
    flat = A2.reshape(-1, A2.shape[-1])
    M = np.empty(flat.shape[0], dtype=A.dtype if A.dtype.kind != 'b' else F64)
    Fq = np.zeros(flat.shape[0])
    Cs = []
    for i, row in enumerate(flat):
        row = row[~np.isnan(row)] if row.dtype.kind == 'f' else row
        if row.size == 0:
            M[i] = np.nan if M.dtype.kind == 'f' else 0
            Fq[i] = 0
            Cs.append(np.zeros((0, 1)))
            continue
        vals, counts = np.unique(row, return_counts=True)
        mx = counts.max()
        ties = vals[counts == mx]
        M[i] = ties[0]
        Fq[i] = mx
        Cs.append(ties.reshape(-1, 1).astype(F64))
    shape = list(A2.shape[:-1]) + [1]
    Mr = np.moveaxis(M.reshape(shape), -1, dim)
    Fr = np.moveaxis(Fq.reshape(shape), -1, dim)
    m = like_class(Mr, x) if class_of(x) not in ('logical', 'char') else out(Mr.astype(F64))
    if nargout <= 1:
        return m
    c = Cell(np.empty(Mr.shape, object))
    for i, v in enumerate(Cs):
        c.a.reshape(-1)[i] = out(v)
    return (m, out(Fr), c)[:nargout]


def _var_std(name, args, sq):
    nargchk(args, 1, 4, name)
    x = args[0]
    a = _num_input(x, name)
    rest, flags = strip_flags(args[1:], ('omitnan', 'includenan'))
    w = 0.0
    dim = None
    if rest:
        wv = rest[0]
        if not (type(wv) is np.ndarray and wv.size == 0):
            wa = arr(wv)
            if wa.size == 1:
                w = float(wa.reshape(-1)[0])
            else:
                w = wa.astype(F64).reshape(-1)
    if len(rest) > 1:
        dim = dim_arg(rest[1], name)
    A = a.astype(F64) if a.dtype.kind in 'biu' or a.dtype == np.uint16 else a
    if isinstance(w, np.ndarray):
        wts = w

        def f(b, ax):
            bb = np.moveaxis(b, ax, -1)
            mu = np.sum(bb * wts, axis=-1, keepdims=True) / wts.sum()
            return np.sum(wts * np.abs(bb - mu) ** 2, axis=-1) / wts.sum()
    else:
        ddof = 0 if w == 1 else 1
        omit = 'omitnan' in flags

        def f(b, ax):
            n = b.shape[ax]
            if n == 0:
                return np.full([s for i, s in enumerate(b.shape) if i != ax], np.nan)
            if n == 1:
                r = np.zeros([s for i, s in enumerate(b.shape) if i != ax])
                return np.where(np.isfinite(np.take(b, 0, axis=ax)), r, np.nan)
            if omit:
                return np.nanvar(b, axis=ax, ddof=ddof)
            return np.var(b, axis=ax, ddof=ddof)
    with np.errstate(all='ignore'):
        r = reduce(A, dim, f)
        if sq:
            r = np.sqrt(r)
    return like_class(np.asarray(r), x) if class_of(x) == 'single' else out(np.asarray(r))


@bi('var')
def var(nargout, *args):
    if args and getattr(args[0], 'is_probdist', False):
        return args[0].moment('var')
    return _var_std('var', args, False)


@bi('std')
def std(nargout, *args):
    if args and getattr(args[0], 'is_probdist', False):
        return args[0].moment('std')
    return _var_std('std', args, True)


@bi('range')
def range_(nargout, *args):
    a = darr(args[0])
    dim = dim_arg(args[1], 'range') if len(args) > 1 else None
    with np.errstate(all='ignore'):
        r = reduce(a, dim, lambda b, ax: np.nanmax(b, axis=ax) - np.nanmin(b, axis=ax))
    return out(np.asarray(r))


# ---- minima and maxima -----------------------------------------------------------------------

def _cmp_key(a):
    """Values to compare: complex numbers by magnitude, then angle."""
    if a.dtype.kind == 'c':
        return np.abs(a)
    return a


def _minmax(name, args, nargout, is_max):
    nargchk(args, 1, 5, name)
    x = args[0]
    rest, flags = strip_flags(args[1:], ('omitnan', 'includenan', 'linear', 'omitmissing', 'includemissing'))
    include_nan = 'includenan' in flags or 'includemissing' in flags
    if len(rest) >= 1 and not (type(rest[0]) is np.ndarray and rest[0].size == 0 and rest[0].shape == (0, 0) and len(rest) > 1):
        if len(rest) == 1 or not (type(rest[0]) is np.ndarray and rest[0].size == 0):
            # max(a, b): element-wise
            if nargout > 1:
                raise err('MATLAB:TooManyOutputs', f'{name.upper()} with two matrices to compare and two output arguments is not supported.', name)
            y = rest[0]
            A = arr(x, name)
            B = arr(y, name)
            from ..ops import result_class
            ca = class_of(x)
            cb = class_of(y)
            klass = result_class('double' if ca in ('logical', 'char') else ca, 'double' if cb in ('logical', 'char') else cb, name)
            A, B = align(A, B)
            check_bcast(A, B)
            with np.errstate(all='ignore'):
                if A.dtype.kind == 'c' or B.dtype.kind == 'c':
                    Ac, Bc = A.astype(C128), B.astype(C128)
                    ka, kb = np.abs(Ac), np.abs(Bc)
                    pick_a = (ka > kb) | ((ka == kb) & (np.angle(Ac) >= np.angle(Bc))) if is_max else (ka < kb) | ((ka == kb) & (np.angle(Ac) <= np.angle(Bc)))
                    r = np.where(pick_a, Ac, Bc)
                else:
                    Af = A.astype(F64) if A.dtype.kind != 'f' else A
                    Bf = B.astype(F64) if B.dtype.kind != 'f' else B
                    if include_nan:
                        r = np.maximum(Af, Bf) if is_max else np.minimum(Af, Bf)
                    else:
                        r = np.fmax(Af, Bf) if is_max else np.fmin(Af, Bf)
            return finish(r, klass)
    dim = None
    if len(rest) >= 2:
        dim = dim_arg(rest[1], name)
    a = arr(x, name)
    if a.size == 0 and dim is None and a.shape == (0, 0):
        e = np.zeros((0, 0), a.dtype if a.dtype.kind != 'b' else F64)
        return like_class(e, x) if nargout <= 1 else (like_class(e, x), np.zeros((0, 0)))
    if dim == 'all':
        a = a.reshape(-1, 1, order='F')
        dim = 0
    if dim is None:
        dim = first_dim(a.shape)
    A = expand_dims(a, dim)
    if A.shape[dim] == 0:
        sh = list(A.shape)
        sh[dim] = 0 if False else 1
        sh[dim] = 0
        e = np.zeros(sh, A.dtype)
        return like_class(e, x) if nargout <= 1 else (like_class(e, x), out(np.zeros(sh)))
    key = _cmp_key(A)
    if key.dtype.kind == 'b':
        key = key.astype(np.int8)
    if key.dtype.kind == 'f':
        nan = np.isnan(key)
        if np.any(nan):
            if include_nan:
                fill = np.inf if is_max else -np.inf
                k2 = np.where(nan, fill, key)
                i = np.argmax(k2, axis=dim) if is_max else np.argmin(k2, axis=dim)
                firstnan = np.argmax(nan, axis=dim)
                anynan = np.any(nan, axis=dim)
                i = np.where(anynan, firstnan, i)
            else:
                fill = -np.inf if is_max else np.inf
                k2 = np.where(nan, fill, key)
                i = np.argmax(k2, axis=dim) if is_max else np.argmin(k2, axis=dim)
                # where all are NaN the result is NaN at the first
                allnan = np.all(nan, axis=dim)
                i = np.where(allnan, 0, i)
        else:
            i = np.argmax(key, axis=dim) if is_max else np.argmin(key, axis=dim)
    else:
        i = np.argmax(key, axis=dim) if is_max else np.argmin(key, axis=dim)
    if A.dtype.kind == 'c':
        # ties in magnitude go to the larger (smaller) angle
        pass
    iexp = np.expand_dims(i, dim)
    m = np.take_along_axis(A, iexp, axis=dim)
    mv = like_class(m, x) if class_of(x) not in ('logical', 'char') else out(m.astype(F64))
    if nargout <= 1:
        return mv
    if 'linear' in flags:
        shape = A.shape
        grids = list(np.indices(iexp.shape))
        grids[dim] = iexp
        lin = np.ravel_multi_index(tuple(grids), shape, order='F') + 1
        return mv, out(lin.astype(F64))
    return mv, out((iexp + 1).astype(F64))


@bi('max', nout=2)
def max_(nargout, *args):
    x = args[0] if args else None
    if len(args) == 2 and type(x) is float and type(args[1]) is float:
        a, b = x, args[1]
        if a != a:
            return b
        if b != b:
            return a
        return a if a >= b else b
    return _minmax('max', args, nargout, True)


@bi('min', nout=2)
def min_(nargout, *args):
    x = args[0] if args else None
    if len(args) == 2 and type(x) is float and type(args[1]) is float:
        a, b = x, args[1]
        if a != a:
            return b
        if b != b:
            return a
        return a if a <= b else b
    return _minmax('min', args, nargout, False)


@bi('bounds', nout=2)
def bounds(nargout, *args):
    lo = _minmax('min', args, 1, False)
    hi = _minmax('max', args, 1, True)
    return (lo, hi) if nargout > 1 else lo


# ---- any / all ---------------------------------------------------------------------------------

def _anyall(name, fn, empty):
    def f(nargout, *args):
        nargchk(args, 1, 2, name)
        x = args[0]
        if type(x) is bool and len(args) == 1:
            return x
        if type(x) is float and len(args) == 1:
            if x != x:
                return name == 'any' and False or (name == 'all')
            return x != 0
        a = _num_input(x, name)
        dim = dim_arg(args[1], name) if len(args) > 1 else None
        if a.dtype.kind in 'fc':
            b = (a != 0) & ~np.isnan(a) if name == 'any' else (a != 0)
        else:
            b = a != 0
        if dim is None and b.ndim == 2 and (b.shape[0] == 1 or b.shape[1] == 1):
            return bool(fn(b))
        r = reduce(b, dim, lambda c, ax: fn(c, axis=ax))
        return out(np.asarray(r, bool))
    f.__name__ = name
    bi(name)(f)


_anyall('any', np.any, False)
_anyall('all', np.all, True)


@bi('xor')
def xor(nargout, *args):
    from ..ops import xor as _x
    nargchk(args, 2, 2, 'xor')
    return _x(args[0], args[1])


@bi('not')
def not_fn(nargout, *args):
    from ..ops import not_
    return not_(args[0])


@bi('and')
def and_fn(nargout, *args):
    from ..ops import and_
    r = args[0]
    for b in args[1:]:
        r = and_(r, b)
    return r


@bi('or')
def or_fn(nargout, *args):
    from ..ops import or_
    r = args[0]
    for b in args[1:]:
        r = or_(r, b)
    return r


# ---- sorting --------------------------------------------------------------------------------

def _sort_keys_desc(a, descend):
    pass


def _argsort_matlab(v, descend):
    """A stable sort order of a 1-D array: NaN last ascending, first
    descending; complex by magnitude then angle."""
    if v.dtype.kind == 'c':
        key1 = np.abs(v)
        key2 = np.angle(v)
        if descend:
            order = np.lexsort((-key2, -key1))
        else:
            order = np.lexsort((key2, key1))
        return order
    if v.dtype.kind == 'f':
        nan = np.isnan(v)
        if descend:
            k = np.where(nan, np.inf, -v)
            # NaN first when descending
            k = np.where(nan, -np.inf, -v)
            return np.argsort(k, kind='stable')
        return np.argsort(np.where(nan, np.inf, v), kind='stable') if not np.any(nan) else np.lexsort((np.where(nan, 0, v), nan))
    if descend:
        if v.dtype.kind in 'ub':
            return np.argsort(-(v.astype(np.int64)), kind='stable')
        return np.argsort(-v.astype(np.float64) if v.dtype.kind in 'iu' else -v, kind='stable')
    return np.argsort(v, kind='stable')


@bi('sort', nout=2, arr=True)
def sort(nargout, *args):
    nargchk(args, 1, 4, 'sort')
    x = args[0]
    rest, flags = strip_flags(args[1:], ('ascend', 'descend'))
    rest2 = []
    i = 0
    while i < len(rest):
        s = opt_str(rest[i])
        if s is not None and s.lower() in ('missingplacement', 'comparisonmethod'):
            i += 2
            continue
        rest2.append(rest[i])
        i += 1
    rest = rest2
    descend = 'descend' in flags
    if type(x) is Cell or type(x) is Str:
        strs = cellstr_list(x)
        order = sorted(range(len(strs)), key=lambda k: [ord(c) for c in strs[k]], reverse=descend)
        if descend:
            # stable for equal strings in descending order
            order = sorted(range(len(strs)), key=lambda k: [-ord(c) for c in strs[k]] + [1])
            order = sorted(range(len(strs)), key=lambda k: strs[k], reverse=True)
        shape = x.a.shape
        vals = [strs[k] for k in order]
        if type(x) is Cell:
            r = Cell.of_list([Char.of(s) for s in vals], shape)
        else:
            r = Str.from_list(vals, shape)
        if nargout > 1:
            return r, out(np.array(order, F64).reshape(shape, order='F') + 1)
        return r
    a = arr(x, 'sort')
    dim = dim_arg(rest[0], 'sort') if rest else first_dim(a.shape)
    A = expand_dims(a, dim)
    A2 = np.moveaxis(A, dim, -1)
    flat = A2.reshape(-1, A2.shape[-1]) if A2.size else A2.reshape(-1, A2.shape[-1] if A2.ndim else 0)
    idx = np.empty(flat.shape, np.int64)
    for r in range(flat.shape[0]):
        idx[r] = _argsort_matlab(flat[r], descend)
    srt = np.take_along_axis(flat, idx, axis=1)
    srt = np.moveaxis(srt.reshape(A2.shape), -1, dim)
    idx = np.moveaxis(idx.reshape(A2.shape), -1, dim)
    if type(x) is Char:
        s = Char(_2d(srt))
    else:
        s = like_class(srt, x)
    if nargout > 1:
        return s, out((idx + 1).astype(F64))
    return s


@bi('sortrows', nout=2)
def sortrows(nargout, *args):
    nargchk(args, 1, 3, 'sortrows')
    x = args[0]
    rest, flags = strip_flags(args[1:], ('ascend', 'descend'))
    if type(x) is Cell:
        rows = [[py_str(v) if type(v) in (Char, Str) else float(arr(v).reshape(-1)[0]) for v in row] for row in x.a]
        cols = list(range(len(rows[0]))) if rows else []
        desc = [False] * len(cols)
        if rest:
            spec = [int(c) for c in arr(rest[0]).reshape(-1)]
            cols = [abs(c) - 1 for c in spec]
            desc = [c < 0 for c in spec]
        if 'descend' in flags:
            desc = [True] * len(cols)
        order = list(range(len(rows)))
        for c, d in reversed(list(zip(cols, desc))):
            order.sort(key=lambda k: rows[k][c], reverse=d)
        r = Cell(x.a[order].copy())
        share_all(r.a)
        return (r, out(np.array(order, F64).reshape(-1, 1) + 1)) if nargout > 1 else r
    a = arr(x, 'sortrows')
    if a.ndim != 2:
        raise err('MATLAB:sortrows:inputDimensionMismatch', 'Only 2-D arrays can be sorted.', 'sortrows')
    ncol = a.shape[1]
    cols = list(range(ncol))
    desc = [False] * ncol
    if rest and numel(rest[0]):
        spec = [int(c) for c in arr(rest[0]).reshape(-1)]
        cols = [abs(c) - 1 for c in spec]
        desc = [c < 0 for c in spec]
    if 'descend' in flags:
        desc = [True] * len(cols)
    order = np.arange(a.shape[0])
    for c, d in reversed(list(zip(cols, desc))):
        col = a[order, c]
        o = _argsort_matlab(col, d)
        order = order[o]
    r = a[order]
    res = Char(_2d(r)) if type(x) is Char else like_class(r, x)
    if nargout > 1:
        return res, out((order + 1).astype(F64).reshape(-1, 1))
    return res


@bi('issorted')
def issorted(nargout, *args):
    a = arr(args[0]).reshape(-1)
    if a.dtype.kind == 'c':
        a = np.abs(a)
    return bool(np.all(a[:-1] <= a[1:])) if a.size > 1 else True


# ---- sets -------------------------------------------------------------------------------

def _set_input(v, fn):
    """('num', array) or ('str', list of str, kind) for the set functions."""
    t = type(v)
    if t is Cell:
        return 'str', cellstr_list(v), 'cell'
    if t is Str:
        return 'str', cellstr_list(v), 'string'
    return 'num', arr(v, fn), None


def _set_out_str(vals, kind, row):
    shape = (1, len(vals)) if row else (len(vals), 1)
    if kind == 'cell':
        return Cell.of_list([Char.of(s) for s in vals], shape)
    return Str.from_list(vals, shape)


def _isrow(v):
    sh = shape_of(v)
    return len(sh) == 2 and sh[0] == 1


@bi('unique', nout=3)
def unique(nargout, *args):
    nargchk(args, 1, 4, 'unique')
    x = args[0]
    rest, flags = strip_flags(args[1:], ('stable', 'sorted', 'rows', 'first', 'last', 'legacy'))
    kind, data, sk = _set_input(x, 'unique')
    stable = 'stable' in flags
    last = 'last' in flags
    if kind == 'str':
        seen = {}
        order = []
        for i, s in enumerate(data):
            if s not in seen:
                seen[s] = i
                order.append(s)
            elif last:
                seen[s] = i
        vals = order if stable else sorted(seen)
        ia = [seen[s] + 1 for s in vals]
        pos = {s: k + 1 for k, s in enumerate(vals)}
        ic = [pos[s] for s in data]
        row = _isrow(x) and False
        C = _set_out_str(vals, sk, row)
        if nargout <= 1:
            return C
        return (C, out(np.array(ia, F64).reshape(-1, 1)), out(np.array(ic, F64).reshape(-1, 1)))[:nargout]
    a = data
    if 'rows' in flags and a.ndim == 2:
        rows = [tuple(r) for r in a]
        first = {}
        for i, r in enumerate(rows):
            if r not in first or last:
                if r not in first or last:
                    first[r] = i if (r not in first or last) else first[r]
        keys = list(dict.fromkeys(rows)) if stable else sorted(set(rows))
        C = np.array(keys).reshape(len(keys), a.shape[1]) if keys else np.zeros((0, a.shape[1]), a.dtype)
        ia = [first[k] + 1 for k in keys]
        pos = {k: i + 1 for i, k in enumerate(keys)}
        ic = [pos[r] for r in rows]
        res = like_class(C, x) if type(x) is not Char else Char(_2d(C))
        if nargout <= 1:
            return res
        return (res, out(np.array(ia, F64).reshape(-1, 1)), out(np.array(ic, F64).reshape(-1, 1)))[:nargout]
    flat = a.reshape(-1, order='F')
    if flat.dtype.kind == 'f' and np.any(np.isnan(flat)):
        # every NaN is distinct
        nn = flat[~np.isnan(flat)]
        vals, first_idx, inv = np.unique(nn, return_index=True, return_inverse=True)
        nan_pos = np.flatnonzero(np.isnan(flat))
        vals = np.concatenate([vals, flat[nan_pos]])
        nn_pos = np.flatnonzero(~np.isnan(flat))
        ia = np.concatenate([nn_pos[first_idx], nan_pos])
        ic = np.empty(flat.size, np.int64)
        ic[nn_pos] = inv
        ic[nan_pos] = len(vals) - len(nan_pos) + np.arange(len(nan_pos))
    else:
        if flat.dtype.kind == 'c':
            key = np.lexsort((np.angle(flat), np.abs(flat)))
            sflat = flat[key]
            new = np.ones(sflat.size, bool)
            new[1:] = sflat[1:] != sflat[:-1]
            vals = sflat[new]
            grp = np.cumsum(new) - 1
            ic = np.empty(flat.size, np.int64)
            ic[key] = grp
            ia = np.array([key[np.flatnonzero(grp == g)[0]] for g in range(len(vals))], np.int64)
        else:
            vals, ia, ic = np.unique(flat, return_index=True, return_inverse=True)
            if last:
                rev = flat[::-1]
                _, ia_r = np.unique(rev, return_index=True)
                ia = flat.size - 1 - ia_r
    if stable:
        order = np.argsort(ia, kind='stable')
        vals = vals[order]
        ia = ia[order]
        remap = np.empty(order.size, np.int64)
        remap[order] = np.arange(order.size)
        ic = remap[ic]
    row = _isrow(x) and a.size > 0
    C = vals.reshape(1, -1) if row else vals.reshape(-1, 1)
    if a.shape == (0, 0) or (a.size == 0):
        C = np.zeros((0, 1) if not row else (1, 0), a.dtype)
        if a.shape == (0, 0):
            C = np.zeros((0, 0), a.dtype)
    res = Char(_2d(C)) if type(x) is Char else like_class(C, x)
    if nargout <= 1:
        return res
    return (res, out((np.asarray(ia) + 1).astype(F64).reshape(-1, 1)), out((np.asarray(ic) + 1).astype(F64).reshape(-1, 1)))[:nargout]


@bi('ismember', nout=2)
def ismember(nargout, *args):
    nargchk(args, 2, 3, 'ismember')
    x, s = args[0], args[1]
    rest, flags = strip_flags(args[2:], ('rows', 'legacy'))
    if type(x) in (Char, Str) and type(s) in (Cell, Str) or type(x) in (Cell, Str):
        xs = cellstr_list(x) if type(x) in (Cell, Str) else [py_str(x)]
        ss = cellstr_list(s)
        pos = {}
        for i, v in enumerate(ss):
            pos.setdefault(v, i + 1)
        tf = np.array([v in pos for v in xs])
        loc = np.array([pos.get(v, 0) for v in xs], F64)
        shape = shape_of(x) if type(x) in (Cell, Str) else (1, 1)
        tf = out(tf.reshape(shape, order='F'))
        if nargout > 1:
            return tf, out(loc.reshape(shape, order='F'))
        return tf
    A = arr(x)
    S = arr(s)
    if 'rows' in flags:
        srows = {}
        for i, r in enumerate(S):
            srows.setdefault(tuple(r), i + 1)
        tf = np.array([tuple(r) in srows for r in A]).reshape(-1, 1)
        loc = np.array([srows.get(tuple(r), 0) for r in A], F64).reshape(-1, 1)
        return (out(tf), out(loc)) if nargout > 1 else out(tf)
    sflat = S.reshape(-1, order='F')
    tf = np.isin(A, sflat)
    if nargout <= 1:
        return out(tf)
    pos = {}
    for i, v in enumerate(sflat.tolist()):
        pos.setdefault(v, i + 1)
    loc = np.array([pos.get(v, 0) for v in A.reshape(-1).tolist()], F64).reshape(A.shape)
    return out(tf), out(loc)


def _setop(name, args, nargout, op):
    nargchk(args, 2, 4, name)
    a, b = args[0], args[1]
    rest, flags = strip_flags(args[2:], ('stable', 'sorted', 'rows', 'legacy'))
    stable = 'stable' in flags
    ka, da, sa = _set_input(a, name)
    kb, db, sb = _set_input(b, name)
    if ka == 'str' or kb == 'str':
        la = da if ka == 'str' else [py_str(a)]
        lb = db if kb == 'str' else [py_str(b)]
        res, ia, ib = op(la, lb, stable)
        C = _set_out_str(res, sa or sb, False)
        outs = (C, out(np.array(ia, F64).reshape(-1, 1)), out(np.array(ib, F64).reshape(-1, 1)))
        return outs[0] if nargout <= 1 else outs[:nargout]
    if 'rows' in flags:
        la = [tuple(r) for r in da]
        lb = [tuple(r) for r in db]
        res, ia, ib = op(la, lb, stable)
        ncol = da.shape[1] if da.ndim == 2 else 1
        C = np.array(res).reshape(len(res), ncol) if res else np.zeros((0, ncol))
        outs = (out(C), out(np.array(ia, F64).reshape(-1, 1)), out(np.array(ib, F64).reshape(-1, 1)))
        return outs[0] if nargout <= 1 else outs[:nargout]
    la = da.reshape(-1, order='F').tolist()
    lb = db.reshape(-1, order='F').tolist()
    res, ia, ib = op(la, lb, stable)
    row = (_isrow(a) or numel(a) == 0) and (_isrow(b) or numel(b) == 0) and not (numel(a) == 0 and numel(b) == 0)
    if name in ('setdiff',):
        row = _isrow(a)
    dt = np.result_type(da, db) if name != 'setdiff' else da.dtype
    C = np.array(res, dtype=dt)
    C = C.reshape(1, -1) if row else C.reshape(-1, 1)
    klass = class_of(a) if name == 'setdiff' else class_of(a)
    res_v = Char(_2d(C)) if type(a) is Char else like_class(C, a)
    outs = (res_v, out(np.array(ia, F64).reshape(-1, 1)), out(np.array(ib, F64).reshape(-1, 1)))
    return outs[0] if nargout <= 1 else outs[:nargout]


def _first_pos(lst):
    pos = {}
    for i, v in enumerate(lst):
        pos.setdefault(v, i + 1)
    return pos


def _sorted_keys(keys):
    try:
        return sorted(keys)
    except TypeError:
        return sorted(keys, key=lambda v: (abs(v), np.angle(v)))


def _union(la, lb, stable):
    pa, pb = _first_pos(la), _first_pos(lb)
    if stable:
        keys = list(dict.fromkeys(la + lb))
    else:
        keys = _sorted_keys(set(la) | set(lb))
    ia = [pa[k] for k in keys if k in pa]
    ib = [pb[k] for k in keys if k not in pa]
    return keys, ia, ib


def _intersect(la, lb, stable):
    pa, pb = _first_pos(la), _first_pos(lb)
    common = set(pa) & set(pb)
    keys = [k for k in dict.fromkeys(la) if k in common] if stable else _sorted_keys(common)
    return keys, [pa[k] for k in keys], [pb[k] for k in keys]


def _setdiff(la, lb, stable):
    pa = _first_pos(la)
    sb = set(lb)
    keys = [k for k in dict.fromkeys(la) if k not in sb] if stable else _sorted_keys(set(la) - sb)
    return keys, [pa[k] for k in keys], []


def _setxor(la, lb, stable):
    pa, pb = _first_pos(la), _first_pos(lb)
    keys = (list(dict.fromkeys([k for k in la if k not in pb] + [k for k in lb if k not in pa])) if stable
            else _sorted_keys(set(la) ^ set(lb)))
    return keys, [pa[k] for k in keys if k in pa], [pb[k] for k in keys if k in pb]


@bi('union', nout=3)
def union(nargout, *args):
    return _setop('union', args, nargout, _union)


@bi('intersect', nout=3)
def intersect(nargout, *args):
    return _setop('intersect', args, nargout, _intersect)


@bi('setdiff', nout=2)
def setdiff(nargout, *args):
    return _setop('setdiff', args, nargout, _setdiff)


@bi('setxor', nout=3)
def setxor(nargout, *args):
    return _setop('setxor', args, nargout, _setxor)


# ---- histograms and binning ---------------------------------------------------------------------

def nice_edges(x, nbins=None, binwidth=None, limits=None):
    """Bin edges as histogram and histcounts choose them: a round bin width
    (Scott's rule when no number is given), edges on its multiples."""
    x = x[np.isfinite(x)]
    if limits is not None:
        lo, hi = limits
    elif x.size == 0:
        lo, hi = 0.0, 1.0
    else:
        lo, hi = float(x.min()), float(x.max())
    if nbins is not None:
        if hi == lo:
            lo, hi = lo - 0.5, hi + 0.5
        if limits is not None:
            return np.linspace(lo, hi, nbins + 1)
        span = hi - lo
        raw = span / nbins
        w = _nice(raw)
        start = math.floor(lo / w) * w
        edges = start + w * np.arange(nbins + 1)
        if edges[-1] < hi:
            # fall back to exact limits when the round width cannot cover
            return np.linspace(lo, hi, nbins + 1)
        return edges
    if binwidth is None:
        if x.size < 2 or hi == lo:
            if hi == lo:
                return np.array([lo - 0.5, lo + 0.5]) if x.size else np.array([0.0, 1.0])
        sd = float(np.std(x, ddof=1)) if x.size > 1 else 0.0
        if sd == 0 or x.size < 2:
            binwidth = _nice((hi - lo) / 10 if hi > lo else 1.0)
        else:
            binwidth = 3.5 * sd / (x.size ** (1 / 3))
            binwidth = _nice(binwidth)
        if (hi - lo) / binwidth > 1000:
            binwidth = _nice((hi - lo) / 1000)
    w = binwidth
    start = math.floor(lo / w) * w
    stop = math.ceil(hi / w) * w
    if stop <= hi:
        stop = start + w * (math.floor((hi - start) / w) + 1) if stop == hi and hi == lo else stop
    n = max(1, int(round((stop - start) / w)))
    edges = start + w * np.arange(n + 1)
    if edges[-1] < hi:
        edges = np.append(edges, edges[-1] + w)
    return edges


def _nice(v):
    if v <= 0 or not math.isfinite(v):
        return 1.0
    p = 10 ** math.floor(math.log10(v))
    m = v / p
    if m <= 1:
        n = 1
    elif m <= 2:
        n = 2
    elif m <= 5:
        n = 5
    else:
        n = 10
    return n * p


def bin_counts(x, edges):
    """Counts per bin: [e(k), e(k+1)), the last bin closed."""
    x = x[np.isfinite(x)] if x.dtype.kind == 'f' else x
    idx = np.searchsorted(edges, x, side='right') - 1
    idx = np.where(x == edges[-1], len(edges) - 2, idx)
    ok = (idx >= 0) & (idx < len(edges) - 1)
    return np.bincount(idx[ok], minlength=len(edges) - 1).astype(F64), idx, ok


@bi('histcounts', nout=3)
def histcounts(nargout, *args):
    nargchk(args, 1, None, 'histcounts')
    x = darr(args[0]).reshape(-1, order='F').real
    rest = list(args[1:])
    nbins = None
    edges = None
    binwidth = None
    limits = None
    norm = 'count'
    if rest and opt_str(rest[0]) is None:
        e = darr(rest[0]).reshape(-1)
        if e.size == 1:
            nbins = int(e[0])
        else:
            edges = e
        rest = rest[1:]
    i = 0
    while i + 1 < len(rest):
        key = opt_str(rest[i]).lower()
        val = rest[i + 1]
        if key == 'binwidth':
            binwidth = num(val)
        elif key == 'binlimits':
            limits = tuple(darr(val).reshape(-1))
        elif key == 'numbins':
            nbins = int(num(val))
        elif key == 'binedges':
            edges = darr(val).reshape(-1)
        elif key == 'normalization':
            norm = opt_str(val).lower()
        i += 2
    if edges is None:
        xx = x if limits is None else x[(x >= limits[0]) & (x <= limits[1])]
        edges = nice_edges(xx, nbins, binwidth, limits)
    n, idx, ok = bin_counts(x, edges)
    w = np.diff(edges)
    if norm == 'probability':
        n = n / max(x.size, 1)
    elif norm == 'pdf':
        n = n / max(x.size, 1) / w
    elif norm == 'countdensity':
        n = n / w
    elif norm == 'cumcount':
        n = np.cumsum(n)
    elif norm == 'cdf':
        n = np.cumsum(n) / max(x.size, 1)
    r = out(n.reshape(1, -1))
    if nargout <= 1:
        return r
    binidx = np.where(ok, idx + 1, 0).astype(F64)
    return (r, out(edges.reshape(1, -1)), out(binidx.reshape(args[0].shape if type(args[0]) is np.ndarray else (1, -1))))[:nargout]


@bi('histc', nout=2)
def histc(nargout, *args):
    nargchk(args, 2, 3, 'histc')
    x = darr(args[0]).real
    edges = darr(args[1]).reshape(-1)
    flat = x.reshape(-1, order='F')
    idx = np.searchsorted(edges, flat, side='right') - 1
    ok = (idx >= 0) & (flat <= edges[-1])
    idx = np.where(flat == edges[-1], len(edges) - 1, idx)
    n = np.bincount(idx[ok], minlength=len(edges)).astype(F64)[:len(edges)]
    shape = (1, -1) if (x.ndim == 2 and x.shape[0] == 1) else (-1, 1)
    r = out(n.reshape(shape))
    if nargout > 1:
        return r, out(np.where(ok, idx + 1, 0).astype(F64).reshape(x.shape, order='F'))
    return r


@bi('discretize')
def discretize(nargout, *args):
    x = darr(args[0])
    edges = darr(args[1]).reshape(-1)
    flat = x.reshape(-1)
    idx = np.searchsorted(edges, flat, side='right').astype(F64)
    idx = np.where(flat == edges[-1], len(edges) - 1, idx)
    idx = np.where((flat < edges[0]) | (flat > edges[-1]) | np.isnan(flat), np.nan, idx)
    return out(idx.reshape(x.shape))


# ---- statistics ---------------------------------------------------------------------------------

@bi('cov')
def cov(nargout, *args):
    nargchk(args, 1, 3, 'cov')
    rest, flags = strip_flags(args[1:], ('omitrows', 'partialrows', 'includenan'))
    x = darr(args[0])
    w = 0
    if rest and numel(rest[-1]) == 1 and (len(rest) == 2 or (len(rest) == 1 and numel(args[0]) != 1 and shape_of(rest[0]) == (1, 1))):
        w = int(num(rest[-1]))
        rest = rest[:-1]
    if rest:
        y = darr(rest[0])
        X = np.column_stack([x.reshape(-1, order='F'), y.reshape(-1, order='F')])
    else:
        X = x.reshape(-1, 1) if (x.ndim == 2 and x.shape[0] == 1) else x
    if X.shape[0] == 1:
        return 0.0
    with np.errstate(all='ignore'):
        r = np.cov(X, rowvar=False, ddof=0 if w == 1 else 1)
    return out(np.atleast_2d(r))


@bi('corrcoef', nout=4)
def corrcoef(nargout, *args):
    nargchk(args, 1, None, 'corrcoef')
    x = darr(args[0])
    rest = list(args[1:])
    if rest and opt_str(rest[0]) is None:
        y = darr(rest[0])
        X = np.column_stack([x.reshape(-1, order='F'), y.reshape(-1, order='F')])
        rest = rest[1:]
    else:
        X = x.reshape(-1, 1) if (x.ndim == 2 and x.shape[0] == 1) else x
    with np.errstate(all='ignore'):
        R = np.atleast_2d(np.corrcoef(X, rowvar=False))
    if nargout <= 1:
        return out(R)
    from scipy import stats
    n = X.shape[0]
    with np.errstate(all='ignore'):
        t = R * np.sqrt((n - 2) / (1 - R ** 2))
        P = 2 * stats.t.sf(np.abs(t), n - 2)
    np.fill_diagonal(P, 1.0)
    return out(R), out(P)


@bi('trapz')
def trapz(nargout, *args):
    nargchk(args, 1, 3, 'trapz')
    if len(args) == 1:
        y = darr(args[0])
        x = None
        dim = None
    elif len(args) == 2:
        if numel(args[1]) == 1 and numel(args[0]) > 1 and shape_of(args[0]) != (1, 1) and numel(args[1]) == 1 and not (numel(args[0]) == 1):
            # trapz(Y, dim) or trapz(X, Y) with scalar spacing: decide by sizes
            y = darr(args[0])
            dim = dim_arg(args[1], 'trapz')
            x = None
        else:
            x = darr(args[0])
            y = darr(args[1])
            dim = None
    else:
        x = darr(args[0])
        y = darr(args[1])
        dim = dim_arg(args[2], 'trapz')
    if dim is None:
        dim = first_dim(y.shape)
    Y = expand_dims(y, dim)
    if x is None:
        r = np.trapezoid(Y, axis=dim) if hasattr(np, 'trapezoid') else np.trapz(Y, axis=dim)
    else:
        xv = x.reshape(-1)
        if xv.size == 1:
            r = (np.trapezoid(Y, axis=dim) if hasattr(np, 'trapezoid') else np.trapz(Y, axis=dim)) * xv[0]
        else:
            r = np.trapezoid(Y, x=xv, axis=dim) if hasattr(np, 'trapezoid') else np.trapz(Y, x=xv, axis=dim)
    r = np.expand_dims(r, dim)
    return out(r)


@bi('cumtrapz')
def cumtrapz(nargout, *args):
    from scipy.integrate import cumulative_trapezoid
    if len(args) == 1:
        y = darr(args[0])
        x = None
    else:
        x = darr(args[0]).reshape(-1)
        y = darr(args[1])
    dim = first_dim(y.shape)
    if x is not None and x.size == 1:
        r = cumulative_trapezoid(y, dx=x[0], axis=dim, initial=0)
    elif x is not None:
        r = cumulative_trapezoid(y, x=x, axis=dim, initial=0)
    else:
        r = cumulative_trapezoid(y, axis=dim, initial=0)
    return out(r)


def _quantiles(x, p, dim):
    """The language's quantiles: the sorted values sit at (i - 0.5)/n,
    linear in between, clamped at the ends."""
    def q(b, ax):
        b = np.moveaxis(b, ax, -1)
        out_ = np.empty(b.shape[:-1] + (len(p),))
        for idx in np.ndindex(b.shape[:-1]):
            v = b[idx]
            v = np.sort(v[~np.isnan(v)])
            n = v.size
            if n == 0:
                out_[idx] = np.nan
                continue
            pos = np.array(p) * n + 0.5
            res = np.interp(pos, np.arange(1, n + 1), v)
            out_[idx] = res
        return np.moveaxis(out_, -1, ax)
    if dim is None:
        dim = first_dim(x.shape)
    X = expand_dims(x, dim)
    return q(X, dim)


@bi('quantile')
def quantile(nargout, *args):
    x = darr(args[0])
    pv = darr(args[1]).reshape(-1)
    if pv.size == 1 and pv[0] >= 1 and pv[0] == int(pv[0]):
        n = int(pv[0])
        pv = np.arange(1, n + 1) / (n + 1)
    dim = dim_arg(args[2], 'quantile') if len(args) > 2 else None
    vec = x.ndim == 2 and (x.shape[0] == 1 or x.shape[1] == 1) and dim is None
    if vec:
        r = _quantiles(x.reshape(-1, 1), list(pv), 0).reshape(-1)
        return out(r.reshape(1, -1) if (x.shape[0] == 1 and pv.size > 1) else r.reshape(-1, 1) if pv.size > 1 else r)
    return out(_quantiles(x, list(pv), dim))


@bi('prctile')
def prctile(nargout, *args):
    p = darr(args[1]) / 100
    return quantile(nargout, args[0], p, *args[2:])


@bi('iqr')
def iqr(nargout, *args):
    if args and getattr(args[0], 'is_probdist', False):
        return args[0].moment('iqr')
    x = darr(args[0])
    q = _quantiles(x.reshape(-1, 1) if (x.ndim == 2 and 1 in x.shape) else x, [0.25, 0.75], 0)
    return out(np.diff(q, axis=0))


@bi('skewness')
def skewness(nargout, *args):
    from scipy import stats
    x = darr(args[0])
    flag = num(args[1]) if len(args) > 1 else 1
    dim = first_dim(x.shape)
    return out(np.expand_dims(stats.skew(x, axis=dim, bias=flag == 1), dim))


@bi('kurtosis')
def kurtosis(nargout, *args):
    from scipy import stats
    x = darr(args[0])
    flag = num(args[1]) if len(args) > 1 else 1
    dim = first_dim(x.shape)
    return out(np.expand_dims(stats.kurtosis(x, axis=dim, bias=flag == 1, fisher=False), dim))


@bi('rescale')
def rescale(nargout, *args):
    x = darr(args[0])
    lo = num(args[1]) if len(args) > 1 else 0.0
    hi = num(args[2]) if len(args) > 2 else 1.0
    mn, mx = np.nanmin(x), np.nanmax(x)
    with np.errstate(all='ignore'):
        r = lo + (x - mn) / (mx - mn) * (hi - lo) if mx > mn else np.full(x.shape, lo)
    return out(r)


@bi('normalize')
def normalize(nargout, *args):
    x = darr(args[0])
    dim = first_dim(x.shape)
    X = expand_dims(x, dim)
    with np.errstate(all='ignore'):
        r = (X - np.mean(X, axis=dim, keepdims=True)) / np.std(X, axis=dim, ddof=1, keepdims=True)
    return out(r)


def _mov(name, fn):
    def f(nargout, *args):
        x = darr(args[0])
        k = darr(args[1]).reshape(-1)
        if k.size == 1:
            kk = int(k[0])
            before = kk // 2 if kk % 2 else kk // 2
            after = kk // 2 if kk % 2 else kk // 2 - 1
        else:
            before, after = int(k[0]), int(k[1])
        dim = first_dim(x.shape)
        X = np.moveaxis(expand_dims(x, dim), dim, -1)
        R = np.empty(X.shape)
        n = X.shape[-1]
        for i in range(n):
            lo, hi = max(0, i - before), min(n, i + after + 1)
            with np.errstate(all='ignore'):
                R[..., i] = fn(X[..., lo:hi], axis=-1)
        return out(np.moveaxis(R, -1, dim))
    f.__name__ = name
    bi(name)(f)


_mov('movmean', np.mean)
_mov('movsum', np.sum)
_mov('movmax', np.max)
_mov('movmin', np.min)
_mov('movmedian', np.median)
_mov('movstd', lambda a, axis: np.std(a, axis=axis, ddof=1) if a.shape[-1] > 1 else np.zeros(a.shape[:-1]))
