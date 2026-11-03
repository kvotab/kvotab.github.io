"""Data analysis: sums and products, means and spreads, minima and maxima,
sorting, sets, histograms, cumulative and difference operations.

Reductions work down the first dimension that is not 1 unless a dimension
is given ('all' takes every element). min and max leave NaN out unless
'includenan' is given; sum, mean and the rest keep it unless 'omitnan'.
"""
import math
import warnings

import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, opt_lower, sval, ival, num, is_str, bool_out,
                    like_class, first_dim, dim_arg, dims_arg, gather, along, reduce, strip_flags, expand_dims, cellstr_list,
                    to_cell_of_char)
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
            dim = dims_arg(d, fn)
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
        # the class: double, but single stays single; 'native' keeps any class
        # ('double' makes even single double)
        klass = class_of(x)
        if 'native' in flags and klass in INT_CLASSES:
            outcls = klass
        elif 'native' in flags and klass == 'logical':
            outcls = 'logical'
        elif klass == 'single' and 'double' not in flags:
            outcls = 'single'
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
        if outcls == 'logical':
            return out(np.asarray(r) != 0)
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
        if isinstance(dim, tuple) or dim == 'all':
            raise err('MATLAB:getdimarg:dimensionMustBePositiveInteger', 'Dimension argument must be a positive integer scalar within indexing range.', name)
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
        if isinstance(dim, tuple) or dim == 'all':
            raise err('MATLAB:getdimarg:dimensionMustBePositiveInteger', 'Dimension argument must be a positive integer scalar within indexing range.', name)
        if dim is None:
            dim = first_dim(a.shape)
        A = expand_dims(a, dim)
        if A.dtype.kind == 'c':
            # complex values by abs, then angle: a running pick along the dimension
            A2 = np.moveaxis(np.flip(A, dim) if 'reverse' in flags else A, dim, 0)
            r = A2.copy()
            for k in range(1, A2.shape[0]):
                prev, cur = r[k - 1], A2[k]
                kp, kc = np.abs(prev), np.abs(cur)
                ap, ac = np.angle(prev), np.angle(cur)
                if name == 'cummax':
                    take = (kc > kp) | ((kc == kp) & (ac > ap)) | (np.isnan(kp) & ~np.isnan(kc))
                else:
                    take = (kc < kp) | ((kc == kp) & (ac < ap)) | (np.isnan(kp) & ~np.isnan(kc))
                r[k] = np.where(take, cur, prev)
            r = np.moveaxis(r, 0, dim)
            return like_class(np.flip(r, dim) if 'reverse' in flags else r, x)
        A = A.astype(F64) if a.dtype.kind not in 'f' else A
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
    nargchk(args, 1, 6, 'mean')
    x = args[0]
    if getattr(x, 'is_probdist', False):
        return x.moment('mean')
    if type(x) is float and len(args) == 1:
        return x
    a = _num_input(x, 'mean')
    rest, wts = list(args[1:]), None
    for k in range(len(rest) - 1):
        if opt_str(rest[k]) is not None and opt_lower(rest[k]) == 'weights':
            wts = arr(rest[k + 1]).astype(F64)
            if np.any(wts < 0):
                raise err('MATLAB:mean:invalidWeights', 'Weights must be nonnegative.', 'mean')
            del rest[k:k + 2]
            break
    dim, flags, rest = _dim_and_flags(rest, ('omitnan', 'includenan', 'double', 'native', 'default'), 'mean')
    A = a.astype(F64) if a.dtype.kind in 'biu' or a.dtype == np.uint16 else a
    if dim is None:
        if A.shape == (0, 0):
            A = np.zeros((0, 1), A.dtype)
        dim = first_dim(A.shape)
    dims = tuple(range(A.ndim)) if dim == 'all' else (dim if isinstance(dim, tuple) else (dim,))
    m, shape = gather(A, dims)
    if wts is None:
        mw = np.ones(m.shape)
    elif wts.shape == A.shape and A.size > 1:
        mw = gather(wts, dims)[0]
    elif wts.size == m.shape[-1]:
        mw = np.broadcast_to(wts.reshape(-1), m.shape)
    else:
        raise err('MATLAB:mean:invalidSizeWeights', 'The weights must have as many elements as the dimension they weight, or be the size of the data.', 'mean')
    with np.errstate(all='ignore'):
        if 'omitnan' in flags:
            gone = np.isnan(m) | np.isnan(mw)
            mw = np.where(gone, 0.0, mw)
            m = np.where(gone, 0.0, m)
        r = (np.sum(mw * m, axis=-1) / np.sum(mw, axis=-1)).reshape(shape)
    klass = class_of(x)
    if 'double' in flags:
        return out(r)
    if klass == 'single':
        return finish(r, 'single')
    if klass in INT_CLASSES and 'native' in flags:
        return finish(r, klass)
    return out(np.asarray(r))


def _cplx_median(row):
    """The middle of complex values ordered by size, then angle."""
    order = np.lexsort((np.angle(row), np.abs(row)))
    v = row[order]
    k = v.size
    return v[k // 2] if k % 2 else (v[k // 2 - 1] + v[k // 2]) / 2


@bi('median')
def median(nargout, *args):
    nargchk(args, 1, 4, 'median')
    x = args[0]
    if getattr(x, 'is_probdist', False):
        return x.moment('median')
    a = _num_input(x, 'median')
    dim, flags, rest = _dim_and_flags(args[1:], ('omitnan', 'includenan', 'default', 'double', 'native'), 'median')
    klass = class_of(x)
    A = a.astype(F64) if a.dtype.kind in 'biu' or a.dtype == np.uint16 else a
    if dim is None:
        if A.shape == (0, 0):
            A = np.zeros((0, 1), A.dtype)
        dim = first_dim(A.shape)
    dims = tuple(range(A.ndim)) if dim == 'all' else (dim if isinstance(dim, tuple) else (dim,))
    m, shape = gather(A, dims)
    rows = m.reshape(int(np.prod(m.shape[:-1])), m.shape[-1])
    res = np.empty(rows.shape[0], dtype=C128 if A.dtype.kind == 'c' else F64)
    with np.errstate(all='ignore'):
        for i, row in enumerate(rows):
            if 'omitnan' in flags:
                row = row[~np.isnan(row)]
            if row.size == 0 or np.any(np.isnan(row)):
                res[i] = np.nan
            elif row.dtype.kind == 'c':
                res[i] = _cplx_median(row)
            else:
                res[i] = np.median(row)
    r = res.reshape(shape)
    # the class: single stays single and integers and logicals stay what they are,
    # unless 'double' (or 'default', for integers and logicals) is asked for
    if 'double' in flags:
        return out(r)
    if klass == 'single':
        return finish(r, 'single')
    if klass in INT_CLASSES and 'default' not in flags:
        return finish(np.where(np.isnan(r), 0, np.round(r)), klass)
    if klass == 'logical' and not ({'default', 'native'} & set(flags)):
        return out(np.where(np.isnan(r), False, r != 0))
    return out(r)


@bi('mode', nout=3)
def mode(nargout, *args):
    nargchk(args, 1, 2, 'mode')
    x = args[0]
    a = _num_input(x, 'mode')
    dim = dims_arg(args[1], 'mode') if len(args) > 1 else None
    empty00 = a.shape == (0, 0) and dim is None
    if dim is None:
        dim = 0 if a.shape == (0, 0) else first_dim(a.shape)
        if a.shape == (0, 0):
            a = np.zeros((0, 1), a.dtype)
    if dim == 'all':
        dim = tuple(range(a.ndim))
    m2, shape = gather(a, dim if isinstance(dim, tuple) else (dim,))
    flat = m2.reshape(int(np.prod(m2.shape[:-1])), m2.shape[-1])
    M = np.empty(flat.shape[0], dtype=a.dtype if a.dtype.kind not in 'b' and a.dtype != np.uint16 else F64)
    Fq = np.zeros(flat.shape[0])
    Cs = []
    for i, row in enumerate(flat):
        row = row[~np.isnan(row)] if row.dtype.kind in 'fc' else row
        if row.size == 0:
            M[i] = np.nan if M.dtype.kind in 'fc' else 0
            Fq[i] = 0
            Cs.append(np.zeros((0, 1) if empty00 else (1, 0), M.dtype))
            continue
        vals, counts = np.unique(row, return_counts=True)
        mx = counts.max()
        ties = vals[counts == mx]
        M[i] = ties[0]
        Fq[i] = mx
        Cs.append(ties.reshape(-1, 1).astype(M.dtype))
    Mr, Fr = M.reshape(shape), Fq.reshape(shape)
    m = like_class(Mr, x) if class_of(x) not in ('logical', 'char') else out(Mr.astype(F64))
    if nargout <= 1:
        return m
    c = Cell(np.empty(_2d(Mr).shape, object))
    for i, v in enumerate(Cs):
        c.a.reshape(-1)[i] = like_class(v, x) if class_of(x) not in ('logical', 'char') else out(v.astype(F64))
    return (m, out(Fr), c)[:nargout]


def _var_std(name, args, sq, nargout=1):
    """var and std (and their means): over a dimension, a vector of them or
    'all'; normalized by N-1 (w = 0), by N (w = 1), or by weights (a vector
    along the dimension, or an array the size of the data); NaN left out
    with 'omitnan' (and so are the weights of the values left out)."""
    nargchk(args, 1, 4, name)
    x = args[0]
    a = _num_input(x, name)
    rest, flags = strip_flags(args[1:], ('omitnan', 'includenan'))
    omit = 'omitnan' in flags
    w, dim = 0.0, None
    if rest and opt_str(rest[0]) is not None:
        dim = dims_arg(rest[0], name)          # var(A, 'all')
        rest = rest[1:]
    elif rest:
        wv = rest[0]
        if not (type(wv) is np.ndarray and wv.size == 0):
            wa = arr(wv).astype(F64)
            if wa.size == 1 and float(wa.reshape(-1)[0]) in (0.0, 1.0):
                w = float(wa.reshape(-1)[0])
            else:
                if np.any(wa < 0):
                    raise err('MATLAB:var:invalidWgts', 'Weights must be nonnegative.', name)
                w = wa
        if len(rest) > 1:
            dim = dims_arg(rest[1], name)
    A = a.astype(F64) if a.dtype.kind in 'biu' or a.dtype == np.uint16 else a
    if dim is None:
        if A.shape == (0, 0):
            A = np.zeros((0, 1), A.dtype)
        dim = first_dim(A.shape)
    dims = tuple(range(A.ndim)) if dim == 'all' else (dim if isinstance(dim, tuple) else (dim,))
    ma, shape = gather(A, dims)
    n = ma.shape[-1]
    if isinstance(w, np.ndarray):
        if w.shape == A.shape and A.size > 1:
            mw = gather(w, dims)[0]
        elif w.size == n:
            mw = np.broadcast_to(w.reshape(-1), ma.shape)
        else:
            raise err('MATLAB:var:invalidSizeWgts', 'The weights must have as many elements as the dimension they weight, or be the size of the data.', name)
        weighted = True
    else:
        mw = np.ones(ma.shape)
        weighted = False
    with np.errstate(all='ignore'):
        if omit:
            gone = np.isnan(ma) | np.isnan(mw)
            mw = np.where(gone, 0.0, mw)
            ma = np.where(gone, 0.0, ma)
        sw = np.sum(mw, axis=-1)
        mu = np.sum(mw * ma, axis=-1) / sw
        dev = np.sum(mw * np.abs(ma - mu[..., None]) ** 2, axis=-1)
        if weighted or w == 1:
            v = dev / sw
        else:
            cnt = np.sum(mw != 0, axis=-1) if omit else np.full(sw.shape, n)
            v = np.where(cnt > 1, dev / (cnt - 1), np.where(np.isfinite(mu), 0.0, np.nan))
            v = np.where(cnt == 0, np.nan, v)
        if sq:
            v = np.sqrt(v)
    single = class_of(x) == 'single'
    v = v.reshape(shape)
    res = like_class(v, x) if single else out(v)
    if nargout < 2:
        return res
    mu = mu.reshape(shape)
    return res, (like_class(mu, x) if single else out(mu))


@bi('var', nout=2)
def var(nargout, *args):
    if args and getattr(args[0], 'is_probdist', False):
        return args[0].moment('var')
    return _var_std('var', args, False, nargout)


@bi('std', nout=2)
def std(nargout, *args):
    if args and getattr(args[0], 'is_probdist', False):
        return args[0].moment('std')
    return _var_std('std', args, True, nargout)


@bi('range')
def range_(nargout, *args):
    """max(A) - min(A) along a dimension, a vector of them or 'all', NaN
    left out unless 'includenan'; in A's class."""
    nargchk(args, 1, 3, 'range')
    margs = (args[0], np.zeros((0, 0))) + tuple(args[1:]) if len(args) > 1 else (args[0],)
    lo = _minmax('min', margs, 1, False)
    hi = _minmax('max', margs, 1, True)
    from ..ops import minus
    return minus(hi, lo)


# ---- minima and maxima -----------------------------------------------------------------------

def _order_keys(a, method):
    """The keys min and max order values by: the values; complex ones by
    abs, then angle ('auto' and 'abs'), or by real part, then imaginary
    part ('real')."""
    if a.dtype.kind == 'c':
        if method == 'real':
            return a.real, a.imag
        return np.abs(a), np.angle(a)
    if method == 'abs':
        return np.abs(a.astype(F64)), None
    return a.astype(F64) if a.dtype.kind != 'f' else a, None


def _pick(key1, key2, is_max, include_nan):
    """For each row the index of its greatest (least) element by key1, then
    key2, the first of those tied; NaN left out unless include_nan (then the
    first NaN), a row of NaN giving its first."""
    big = -np.inf if is_max else np.inf
    nan = np.isnan(key1)
    k1 = np.where(nan, big, key1)
    best = k1.max(axis=1) if is_max else k1.min(axis=1)
    cand = (k1 == best[:, None]) & ~nan
    if key2 is not None:
        k2 = np.where(cand, key2, big)
        best2 = k2.max(axis=1) if is_max else k2.min(axis=1)
        cand &= key2 == best2[:, None]
    idx = np.argmax(cand, axis=1)
    anynan, allnan = nan.any(axis=1), nan.all(axis=1)
    first_nan = np.argmax(nan, axis=1)
    if include_nan:
        idx = np.where(anynan, first_nan, idx)
    else:
        idx = np.where(allnan, 0, idx)
    return idx


def _minmax_class(r, *vals):
    """The class of min and max: logical when all are, else arithmetic's."""
    from ..ops import result_class
    classes = [class_of(v) for v in vals]
    if all(c == 'logical' for c in classes):
        return out(np.asarray(r) != 0)
    k = 'double'
    for c in classes:
        k = result_class(k, 'double' if c in ('logical', 'char') else c, 'max')
    return finish(np.asarray(r), k)


def _minmax(name, args, nargout, is_max):
    nargchk(args, 1, 7, name)
    x = args[0]
    args = list(args)
    method = 'auto'
    for k in range(1, len(args) - 1):
        s_ = opt_str(args[k])
        if s_ is not None and s_.lower() == 'comparisonmethod':
            method = (opt_str(args[k + 1]) or '').lower()
            if method not in ('auto', 'abs', 'real'):
                raise err(f'MATLAB:{name}:invalidComparisonMethod', "ComparisonMethod is 'auto', 'abs' or 'real'.", name)
            del args[k:k + 2]
            break
    rest, flags = strip_flags(args[1:], ('omitnan', 'includenan', 'linear', 'omitmissing', 'includemissing'))
    include_nan = 'includenan' in flags or 'includemissing' in flags
    empty_b = bool(rest) and type(rest[0]) is np.ndarray and rest[0].size == 0 and rest[0].shape == (0, 0)
    if len(rest) >= 1 and not (empty_b and (len(rest) > 1 or flags)):
        if len(rest) == 1 or not (type(rest[0]) is np.ndarray and rest[0].size == 0):
            # max(a, b): element-wise
            if nargout > 1:
                raise err('MATLAB:TooManyOutputs', f'{name.upper()} with two matrices to compare and two output arguments is not supported.', name)
            y = rest[0]
            A, B = align(arr(x, name), arr(y, name))
            check_bcast(A, B)
            A, B = np.broadcast_arrays(A, B)
            cplx = A.dtype.kind == 'c' or B.dtype.kind == 'c'
            Ac = A.astype(C128) if cplx else A.astype(F64)
            Bc = B.astype(C128) if cplx else B.astype(F64)
            with np.errstate(all='ignore'):
                a1, a2 = _order_keys(Ac, method)
                b1, b2 = _order_keys(Bc, method)
                k1 = np.stack([a1.reshape(-1), b1.reshape(-1)], axis=1)
                k2 = np.stack([a2.reshape(-1), b2.reshape(-1)], axis=1) if a2 is not None else None
                pick = _pick(k1, k2, is_max, include_nan).reshape(Ac.shape)
                r = np.where(pick == 0, Ac, Bc)
            return _minmax_class(r, x, y)
    dim = dims_arg(rest[1], name) if len(rest) >= 2 else None
    a = arr(x, name)
    if a.size == 0 and dim is None and a.shape == (0, 0):
        e = np.zeros((0, 0), a.dtype)
        return _minmax_class(e, x) if nargout <= 1 else (_minmax_class(e, x), np.zeros((0, 0)))
    if dim is None:
        dim = first_dim(a.shape)
    dims = tuple(range(a.ndim)) if dim == 'all' else (dim if isinstance(dim, tuple) else (dim,))
    m2, shape = gather(a, dims)
    n = m2.shape[-1]
    if n == 0:
        sh = list(shape)
        for d in dims:
            sh[d] = 0
        e = np.zeros(sh, a.dtype)
        return _minmax_class(e, x) if nargout <= 1 else (_minmax_class(e, x), out(np.zeros(sh)))
    rows = m2.reshape(int(np.prod(m2.shape[:-1])), n)
    with np.errstate(all='ignore'):
        k1, k2 = _order_keys(rows, method)
        idx = _pick(k1, k2, is_max, include_nan)
    m = rows[np.arange(rows.shape[0]), idx].reshape(shape)
    mv = _minmax_class(m, x) if class_of(x) not in ('char',) else out(m.astype(F64))
    if nargout <= 1:
        return mv
    if 'linear' in flags:
        full = a.shape + (1,) * (len(shape) - a.ndim)
        keep = [d for d in range(len(full)) if d not in dims]
        kidx = np.unravel_index(np.arange(rows.shape[0]), [full[d] for d in keep]) if keep else ()
        ridx = np.unravel_index(idx, [full[d] for d in dims], order='F')
        multi = [None] * len(full)
        for d, v in zip(keep, kidx):
            multi[d] = v
        for d, v in zip(dims, ridx):
            multi[d] = v
        lin = np.ravel_multi_index(tuple(multi), full, order='F') + 1
        return mv, out(lin.astype(F64).reshape(shape))
    return mv, out((idx + 1).astype(F64).reshape(shape))


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
    """[S, L] = bounds(A, dim, nanflag): min(A, [], ...) and max(A, [], ...)
    along a dimension, a vector of them or 'all'."""
    nargchk(args, 1, 3, 'bounds')
    margs = (args[0], np.zeros((0, 0))) + tuple(args[1:]) if len(args) > 1 else (args[0],)
    lo = _minmax('min', margs, 1, False)
    hi = _minmax('max', margs, 1, True)
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
        dim = dims_arg(args[1], name) if len(args) > 1 else None
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
        nan = np.isnan(v)
        key1 = np.where(nan, 0.0, np.abs(v))
        key2 = np.where(nan, 0.0, np.angle(v))
        if descend:
            return np.lexsort((-key2, -key1, ~nan))     # NaN first
        return np.lexsort((key2, key1, nan))            # NaN last
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
        if any(c == 0 or abs(c) > a.shape[1] for c in spec):
            raise err('MATLAB:sortrows:COLmismatchX', 'The column numbers must be from 1 to the number of columns (minus for descending).', 'sortrows')
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
    """Whether sort would leave the values (or rows) as they are: 'ascend'
    (the default), 'descend', 'monotonic' (either), and their strict forms
    (no two equal); each column of a matrix (or along dim); NaN placed as
    sort places it."""
    nargchk(args, 1, 3, 'issorted')
    v = args[0]
    words = [opt_lower(a) for a in args[1:] if opt_str(a) is not None]
    nums = [a for a in args[1:] if opt_str(a) is None]
    modes = ('ascend', 'descend', 'monotonic', 'strictascend', 'strictdescend', 'strictmonotonic', 'either')
    mode = next((w for w in words if w in modes), 'ascend')
    if mode == 'either':
        mode = 'monotonic'
    strict = mode.startswith('strict')
    dirs = {'ascend': [False], 'descend': [True], 'monotonic': [False, True]}[mode.replace('strict', '')]
    if type(v) in (Cell, Str):
        items = cellstr_list(v)
        vecs = [items]

        def ok(vals, desc):
            pairs = list(zip(vals[:-1], vals[1:]))
            return all((b > a if not desc else b < a) if strict else (b >= a if not desc else b <= a) for a, b in pairs)
        return any(ok(vecs[0], d) for d in dirs)
    a = arr(v)
    if a.size == 0:
        return True                 # nothing is out of order
    if 'rows' in words:
        rows = a.reshape(a.shape[0], -1) if a.ndim >= 2 else a.reshape(-1, 1)
        keys = [tuple(r) for r in rows]

        def ok(desc):
            for x, y in zip(keys[:-1], keys[1:]):
                if (x > y if not desc else x < y) or (strict and x == y):
                    return False
            return True
        return any(ok(d) for d in dirs)
    if a.ndim == 2 and 1 in a.shape and not nums:
        vecs = [a.reshape(-1)]
    else:
        dim = dim_arg(nums[0], 'issorted') if nums else first_dim(a.shape)
        A = np.moveaxis(expand_dims(a, dim), dim, -1)
        vecs = list(A.reshape(-1, A.shape[-1]))

    def sorted_as(vv, desc):
        if vv.size < 2:
            return True
        if not np.array_equal(_argsort_matlab(vv, desc), np.arange(vv.size)):
            return False
        if strict:
            return not np.any(vv[1:] == vv[:-1])
        return True
    return any(all(sorted_as(vv, d) for vv in vecs) for d in dirs)


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


def _on_handles(fn, nargout, args, ndata, values=True):
    """A set function given graphics objects: worked on their handle numbers
    (as handles were numbers in the language's older graphics), and the values
    of the answer made objects again; None when no data argument is one."""
    from ..graphics_base import GObj, HArr, handle_of_number
    data = args[:ndata]
    if not any(isinstance(a, GObj) or (isinstance(a, HArr) and all(isinstance(h, GObj) for h in a.a.flat)) for a in data):
        return None
    objs = {}

    def number(a):
        if isinstance(a, GObj):
            a = HArr.of([a])
        if not isinstance(a, HArr):
            return a
        nums = np.empty(a.a.shape)
        for i, h in enumerate(a.a.reshape(-1)):
            if not isinstance(h, GObj):
                raise err('MATLAB:invalidType', 'Invalid data type: handles of graphics objects and other values cannot be mixed here.')
            nums.reshape(-1)[i] = objs.setdefault(h.number_value(), h).number_value()
        return out(nums) if nums.size != 1 else float(nums.reshape(-1)[0])

    res = fn(nargout, *[number(a) for a in data], *args[ndata:])
    if not values:
        return res

    def handles(v):
        a = np.asarray(arr(v), float)
        hs = np.empty(a.shape, object)
        for i, x in enumerate(a.reshape(-1)):
            hs.reshape(-1)[i] = objs.get(float(x)) or handle_of_number(float(x))
        return HArr(hs)
    return handles(res) if nargout <= 1 else (handles(res[0]),) + tuple(res[1:])


@bi('unique', nout=3)
def unique(nargout, *args):
    nargchk(args, 1, 4, 'unique')
    r = _on_handles(unique, nargout, args, 1)
    if r is not None:
        return r
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
        row = _isrow(x)                 # a row of text gives a row
        C = _set_out_str(vals, sk, row) if (vals or shape_of(x) != (0, 0)) else (Cell.empty((0, 0)) if sk == 'cell' else Str.from_list([], (0, 0)))
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
    r = _on_handles(ismember, nargout, args, 2, values=False)
    if r is not None:
        return r
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
    r = _on_handles(lambda n, *a: _setop(name, a, n, op), nargout, args, 2)
    if r is not None:
        return r
    a, b = args[0], args[1]
    rest, flags = strip_flags(args[2:], ('stable', 'sorted', 'rows', 'legacy'))
    stable = 'stable' in flags
    ka, da, sa = _set_input(a, name)
    kb, db, sb = _set_input(b, name)
    if ka == 'str' or kb == 'str':
        # [] is no text at all
        la = da if ka == 'str' else ([] if numel(a) == 0 else [py_str(a)])
        lb = db if kb == 'str' else ([] if numel(b) == 0 else [py_str(b)])
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
    (Scott's rule when no number is given), edges on its multiples; always
    doubles (a whole-number width would otherwise make integer edges)."""
    return np.asarray(_nice_edges(x, nbins, binwidth, limits), F64)


def _nice_edges(x, nbins, binwidth, limits):
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
        key = opt_lower(rest[i])
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
            norm = opt_lower(val)
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

def _cov_cols(X, w, wts, nanflag):
    """The covariance matrix of X's columns: normalized by N - 1 (w 0, N 1
    by N) or by N (w 1), or with observation weights wts (normalized by
    their sum); NaN kept, rows with any NaN dropped, or pairs taken from the
    rows both have (partialrows)."""
    def one(a, b, ww):
        n = a.shape[0]
        if n == 0:
            return np.full((a.shape[1], b.shape[1]), np.nan)
        if ww is not None:
            sw = ww.sum()
            ma, mb = (ww @ a) / sw, (ww @ b) / sw
            return ((a - ma).conj().T * ww) @ (b - mb) / sw
        d = n - 1 if (w == 0 and n > 1) else n
        return (a - a.mean(axis=0)).conj().T @ (b - b.mean(axis=0)) / d

    k = X.shape[1]
    with np.errstate(all='ignore'):
        if nanflag == 'omitrows':
            keep = ~np.any(np.isnan(X), axis=1)
            return one(X[keep], X[keep], None if wts is None else wts[keep])
        if nanflag == 'partialrows':
            C = np.empty((k, k), X.dtype)
            ok = ~np.isnan(X)
            for i in range(k):
                for j in range(i, k):
                    rows = ok[:, i] & ok[:, j]
                    c = one(X[rows][:, [i]], X[rows][:, [j]], None if wts is None else wts[rows])[0, 0]
                    C[i, j], C[j, i] = c, np.conj(c)
            return C
        return one(X, X, wts)


@bi('cov')
def cov(nargout, *args):
    """cov(A), cov(A, B), with a normalization (0, 1 or weights) and a NaN
    flag ('includenan', 'omitrows', 'partialrows')."""
    nargchk(args, 1, 4, 'cov')
    rest = list(args)
    nanflag = 'includenan'
    if rest and opt_str(rest[-1]) is not None:
        nanflag = opt_lower(rest.pop())
        if nanflag not in ('includenan', 'omitrows', 'partialrows'):
            raise err('MATLAB:cov:unknownFlag', f"Unknown option '{nanflag}'.", 'cov')
    data = [rest.pop(0)]
    w, wts = 0, None
    if len(rest) == 2:
        data.append(rest.pop(0))
    if rest:
        # cov(A, B) when the second input is data: not a normalization (0 or
        # 1) and as many elements as A (weights are one per row of A)
        v = darr(rest[0]).reshape(-1)
        a = darr(data[0])
        norm_flag = v.size == 1 and v[0] in (0, 1)
        if len(data) == 1 and not norm_flag and v.size == a.size:
            data.append(rest[0])
        elif v.size == 1:
            if not norm_flag:
                raise err('MATLAB:cov:invalidWgts', 'The normalization must be 0, 1 or a vector of weights.', 'cov')
            w = int(v[0])
        else:
            wts = v.astype(F64)
            if np.any(wts < 0):
                raise err('MATLAB:cov:invalidWgts', 'Weights must not be negative.', 'cov')
    single = any(class_of(v) == 'single' for v in data)
    if len(data) == 2:
        a, b = darr(data[0]), darr(data[1])
        if a.size != b.size:
            raise err('MATLAB:cov:XYlengthMismatch', 'The two inputs must have the same number of elements.', 'cov')
        X = np.column_stack([a.reshape(-1, order='F'), b.reshape(-1, order='F')])
    else:
        x = darr(data[0])
        if x.ndim > 2:
            raise err('MATLAB:cov:InputDim', 'The input must be a vector or a matrix.', 'cov')
        X = x.reshape(-1, 1) if x.shape[0] == 1 or x.shape == (0, 0) else x
    if wts is not None and wts.size != X.shape[0]:
        raise err('MATLAB:cov:invalidWgts', 'The weights must have one value per observation.', 'cov')
    if X.dtype.kind not in 'fc':
        X = X.astype(F64)
    C = _cov_cols(X, w, wts, nanflag)
    C = np.atleast_2d(C)
    return out(C.astype(np.complex64 if C.dtype.kind == 'c' else np.float32)) if single else out(C)


@bi('corrcoef', nout=4)
def corrcoef(nargout, *args):
    nargchk(args, 1, None, 'corrcoef')
    x = darr(args[0])
    rest = list(args[1:])
    if rest and opt_str(rest[0]) is None:
        y = darr(rest[0])
        if y.size != x.size:
            raise err('MATLAB:corrcoef:XYmismatch', 'x and y must have the same number of elements.', 'corrcoef')
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


def _trapz_parts(args, fn):
    """trapz's and cumtrapz's arguments: (Y moved so that the dimension is
    last, the spacing between its points along it, the dimension, Y's shape).
    trapz(Y, dim) when the second of two arguments is a scalar; X a scalar
    spacing, a vector of points, or an array the size of Y."""
    nargchk(args, 1, 3, fn)
    x = dim = None
    if len(args) == 1:
        y = darr(args[0])
    elif len(args) == 2 and numel(args[1]) == 1 and numel(args[0]) != 1:
        y, dim = darr(args[0]), dim_arg(args[1], fn)
    else:
        x, y = darr(args[0]), darr(args[1])
        if len(args) > 2:
            dim = dim_arg(args[2], fn)
    if dim is None:
        dim = first_dim(y.shape)
    Y = np.moveaxis(expand_dims(y, dim), dim, -1).astype(C128 if y.dtype.kind == 'c' else F64)
    n = Y.shape[-1]
    if x is None or x.size == 1:
        dx = np.full(max(n - 1, 0), 1.0 if x is None else float(x.reshape(-1)[0]))
    elif x.size == n and (x.ndim <= 2 and 1 in x.shape):
        dx = np.diff(x.reshape(-1).astype(F64))
    elif x.shape == y.shape:
        dx = np.diff(np.moveaxis(expand_dims(x, dim), dim, -1).astype(F64), axis=-1)
    else:
        raise err(f'MATLAB:{fn}:LengthXMismatchY', f'The points X must be as many as the values of Y along the dimension (or a scalar spacing, or an array the size of Y).', fn)
    return Y, dx, dim, y.shape


@bi('trapz')
def trapz(nargout, *args):
    Y, dx, dim, shape = _trapz_parts(args, 'trapz')
    r = np.sum(dx * (Y[..., 1:] + Y[..., :-1]) / 2, axis=-1) if Y.shape[-1] > 1 else np.zeros(Y.shape[:-1], Y.dtype)
    return out(np.moveaxis(r[..., None], -1, dim))


@bi('cumtrapz')
def cumtrapz(nargout, *args):
    Y, dx, dim, shape = _trapz_parts(args, 'cumtrapz')
    steps = dx * (Y[..., 1:] + Y[..., :-1]) / 2
    r = np.concatenate([np.zeros(Y.shape[:-1] + (min(1, Y.shape[-1]),), Y.dtype), np.cumsum(steps, axis=-1)], axis=-1)
    return out(np.moveaxis(r, -1, dim))


def _quantiles(x, p, dim):
    """The language's quantiles: the sorted values sit at (i - 0.5)/n,
    linear in between, clamped at the ends; NaN left out. Along a dimension,
    a vector of them or 'all' (a column); the quantiles take the place of
    the first dimension worked along, the others become 1."""
    p = np.asarray(p, F64).reshape(-1)
    if dim == 'all':
        x, dim = x.reshape(-1, 1), 0
    elif dim is None:
        dim = first_dim(x.shape)
    dims = dim if isinstance(dim, tuple) else (dim,)
    m, shape = gather(x.astype(F64), dims)
    rows = m.reshape(int(np.prod(m.shape[:-1])), m.shape[-1])
    res = np.empty((rows.shape[0], p.size))
    for i, v in enumerate(rows):
        v = np.sort(v[~np.isnan(v)])
        n = v.size
        res[i] = np.nan if n == 0 else np.interp(p * n + 0.5, np.arange(1, n + 1), v)
    keep = [s_ for d, s_ in enumerate(shape) if d not in dims]
    r = np.moveaxis(res.reshape(keep + [p.size]), -1, dims[0])
    shape[dims[0]] = p.size
    return r.reshape(shape)


@bi('quantile')
def quantile(nargout, *args):
    nargchk(args, 2, 3, 'quantile')
    x = darr(args[0])
    pa = darr(args[1])
    pv = pa.reshape(-1)
    if pv.size == 1 and pv[0] >= 1 and pv[0] == int(pv[0]):
        n = int(pv[0])
        pv = np.arange(1, n + 1) / (n + 1)
        pa = pv.reshape(1, -1)
    if np.any((pv < 0) | (pv > 1)):
        raise err('stats:quantile:BadProbs', 'P must be between 0 and 1, or a number of quantiles.', 'quantile')
    dim = dims_arg(args[2], 'quantile') if len(args) > 2 else None
    if dim is None and x.ndim == 2 and (x.shape[0] == 1 or x.shape[1] == 1 or x.shape == (0, 0)):
        # a vector (or []): its quantiles as p is laid out
        r = _quantiles(x.reshape(-1, 1), pv, 0).reshape(-1)
        return out(r.reshape(-1, 1) if (pa.ndim == 2 and pa.shape[1] == 1 and pa.shape[0] > 1) else r.reshape(1, -1))
    return out(_quantiles(x, pv, dim))


@bi('prctile')
def prctile(nargout, *args):
    p = darr(args[1]) / 100
    return quantile(nargout, args[0], p, *args[2:])


@bi('iqr')
def iqr(nargout, *args):
    if args and getattr(args[0], 'is_probdist', False):
        return args[0].moment('iqr')
    x = darr(args[0])
    dim = dims_arg(args[1], 'iqr') if len(args) > 1 else None
    if dim is None and x.ndim == 2 and (x.shape[0] <= 1 or x.shape[1] <= 1):
        x, dim = x.reshape(-1, 1), 0
    q = _quantiles(x, [0.25, 0.75], dim)
    first = dim if isinstance(dim, int) else (dim[0] if isinstance(dim, tuple) else (0 if dim == 'all' else first_dim(x.shape)))
    return out(np.diff(q, axis=first))


def _shape_stat(name, args, fn):
    """skewness and kurtosis: (x, flag, dim) with flag 1 (biased, the
    default, also for []) or 0 (corrected); dim a dimension, a vector of them
    or 'all'; NaN left out as missing; single computed in single."""
    nargchk(args, 1, 3, name)
    x0 = args[0]
    single = class_of(x0) == 'single'
    x = np.asarray(arr(x0, name))
    if x.dtype.kind == 'c':
        raise err(f'stats:{name}:ComplexData', 'The data must be real.', name)
    x = x.astype(np.float32 if single else F64)
    flag = 1
    if len(args) > 1 and numel(args[1]):
        flag = num(args[1])
        if flag not in (0, 1):
            raise err(f'stats:{name}:BadFlag', 'The flag must be 0 or 1.', name)
    dim = dims_arg(args[2], name) if len(args) > 2 else None

    def f(m):
        r = np.full(m.shape[:-1], np.nan, m.dtype)
        for i in np.ndindex(m.shape[:-1]):
            v = m[i][~np.isnan(m[i])]
            if v.size:
                with np.errstate(all='ignore'):
                    r[i] = fn(v - v.mean(dtype=v.dtype), v.size, flag)
        return r
    r = along(x, dim, f)
    return finish(r.astype(np.float32), 'single') if single else out(r)


def _skew(c, n, flag):
    m2, m3 = np.mean(c * c), np.mean(c * c * c)
    g = m3 / m2 ** 1.5
    if flag == 0:
        return g * np.sqrt(n * (n - 1.0)) / (n - 2.0) if n > 2 else np.nan
    return g


def _kurt(c, n, flag):
    c2 = c * c
    m2, m4 = np.mean(c2), np.mean(c2 * c2)
    k = m4 / (m2 * m2)
    if flag == 0:
        return 3 + (n - 1.0) / ((n - 2.0) * (n - 3.0)) * ((n + 1.0) * k - 3 * (n - 1.0)) if n > 3 else np.nan
    return k


@bi('skewness')
def skewness(nargout, *args):
    return _shape_stat('skewness', args, _skew)


@bi('kurtosis')
def kurtosis(nargout, *args):
    return _shape_stat('kurtosis', args, _kurt)


@bi('rescale')
def rescale(nargout, *args):
    """(A - inmin)/(inmax - inmin) scaled to [l, u], the data clamped to
    [inmin, inmax] (A's least and greatest unless given); l, u, inmin and
    inmax may be arrays that broadcast against A."""
    x0 = args[0]
    x = darr(x0).astype(F64)
    rest = list(args[1:])
    opts = {}
    for k in range(len(rest) - 1, 0, -1):
        s_ = opt_str(rest[k - 1])
        if s_ is not None and s_.lower() in ('inputmin', 'inputmax'):
            opts[s_.lower()] = darr(rest[k]).astype(F64)
            del rest[k - 1:k + 1]
    lo = darr(rest[0]).astype(F64) if len(rest) > 0 else np.float64(0.0)
    hi = darr(rest[1]).astype(F64) if len(rest) > 1 else np.float64(1.0)
    if x.size == 0:
        return like_class(x, x0) if class_of(x0) == 'single' else out(x)
    mn = opts.get('inputmin', np.float64(np.nanmin(x)) if np.any(~np.isnan(x)) else np.float64(np.nan))
    mx = opts.get('inputmax', np.float64(np.nanmax(x)) if np.any(~np.isnan(x)) else np.float64(np.nan))
    with np.errstate(all='ignore'):
        xc = np.clip(x, mn, mx)
        span = mx - mn
        r = np.where(span > 0, lo + (xc - mn) / np.where(span > 0, span, 1) * (hi - lo), lo + 0 * xc)
    return like_class(r, x0) if class_of(x0) == 'single' else out(r)


def _nanq(m, p):
    """The language's quantile p of m's last axis, NaN left out (keepdims)."""
    r = np.full(m.shape[:-1] + (1,), np.nan)
    for i in np.ndindex(m.shape[:-1]):
        v = np.sort(m[i][~np.isnan(m[i])])
        n = v.size
        if n:
            t = min(max(p * n + 0.5, 1), n) - 1          # sorted values sit at (i - 0.5)/n
            lo = int(np.floor(t))
            hi = min(lo + 1, n - 1)
            r[i + (0,)] = v[lo] + (t - lo) * (v[hi] - v[lo]) if hi != lo else v[lo]
    return r


def _norm_stat(m, what, arg=None):
    """A statistic of m's last axis for normalize, NaN left out (keepdims)."""
    with warnings.catch_warnings(), np.errstate(all='ignore'):
        warnings.simplefilter('ignore', RuntimeWarning)
        ok = ~np.isnan(m)
        n = ok.sum(axis=-1, keepdims=True)
        if m.shape[-1] == 0:
            return np.full(m.shape[:-1] + (1,), np.nan)
        if what == 'mean':
            return np.nanmean(m, axis=-1, keepdims=True)
        if what == 'median':
            return np.nanmedian(m, axis=-1, keepdims=True)
        if what == 'std':
            mu = np.nanmean(m, axis=-1, keepdims=True)
            # only NaN in the data is left out: Inf - Inf stays NaN
            ss = np.sum(np.where(ok, np.abs(m - mu) ** 2, 0), axis=-1, keepdims=True)
            return np.sqrt(ss / np.maximum(n - 1, 1))
        if what == 'mad':
            c = np.nanmedian(m, axis=-1, keepdims=True)
            return np.nanmedian(np.abs(m - c), axis=-1, keepdims=True)
        if what == 'iqr':
            return _nanq(m, 0.75) - _nanq(m, 0.25)
        if what == 'first':
            return m[..., :1]
        if what == 'norm':
            a = np.abs(m)
            if arg == math.inf:
                return np.nanmax(a, axis=-1, keepdims=True)
            return np.nansum(a ** arg, axis=-1, keepdims=True) ** (1 / arg)
        if what == 'min':
            return np.nanmin(m, axis=-1, keepdims=True)
        if what == 'max':
            return np.nanmax(m, axis=-1, keepdims=True)
    raise ValueError(what)


@bi('normalize', nout=3)
def normalize(nargout, *args):
    """[N, C, S] = normalize(A, dim, method, ...): N = (A - C) ./ S. Methods:
    'zscore' ('std' or 'robust'), 'norm' p, 'scale' (a value, 'std', 'mad',
    'first' or 'iqr'), 'range' [a b], 'center' (a value, 'mean' or
    'median'), 'medianiqr'; 'center' and 'scale' together. NaN is left out
    of the statistics."""
    nargchk(args, 1, 6, 'normalize')
    x0 = args[0]
    cls = class_of(x0)
    if cls not in ('double', 'single'):
        raise err('MATLAB:normalize:InvalidFirstInput', 'The data must be numeric of class double or single.', 'normalize')
    x = np.asarray(arr(x0, 'normalize'))
    x = x.astype(C128 if x.dtype.kind == 'c' else F64)
    shape = x.shape
    rest = list(args[1:])
    dim = None
    if rest and opt_str(rest[0]) is None:
        d = darr(rest.pop(0)).reshape(-1)
        if d.size != 1 or d[0] != np.floor(d[0]) or d[0] < 1:
            raise err('MATLAB:normalize:InvalidDim', 'The dimension must be a positive integer.', 'normalize')
        dim = min(int(d[0]) - 1, 30)
        x = expand_dims(x, dim)
    method = None
    center = scale = None
    i = 0
    while i < len(rest):
        name = opt_str(rest[i])
        if name is None:
            raise err('MATLAB:normalize:InvalidMethod', 'Expected a method name.', 'normalize')
        k = name.lower()
        nxt = rest[i + 1] if i + 1 < len(rest) else None
        nxt_s = opt_lower(nxt) if nxt is not None and opt_str(nxt) is not None else None
        i += 1
        if k == 'zscore':
            method = ('zscore', 'std')
            if nxt_s in ('std', 'robust'):
                method = ('zscore', nxt_s)
                i += 1
        elif k == 'norm':
            method = ('norm', 2.0)
            if nxt is not None and nxt_s is None:
                p = float(num(nxt))
                if not (p > 0):
                    raise err('MATLAB:normalize:InvalidNorm', 'The norm must be a positive number or Inf.', 'normalize')
                method = ('norm', p)
                i += 1
        elif k == 'range':
            method = ('range', (0.0, 1.0))
            if nxt is not None and nxt_s is None:
                r = darr(nxt).reshape(-1)
                if r.size != 2 or not r[0] < r[1]:
                    raise err('MATLAB:normalize:InvalidRange', 'The range is two increasing numbers.', 'normalize')
                method = ('range', (float(r[0]), float(r[1])))
                i += 1
        elif k == 'medianiqr':
            method = ('medianiqr', None)
        elif k in ('center', 'scale'):
            v = 'mean' if k == 'center' else 'std'
            if nxt is not None and (nxt_s is None or nxt_s in (('mean', 'median') if k == 'center' else ('std', 'mad', 'first', 'iqr'))):
                v = nxt_s if nxt_s is not None else np.asarray(arr(nxt, 'normalize'), F64)
                i += 1
            if k == 'center':
                center = v
            else:
                scale = v
        else:
            raise err('MATLAB:normalize:InvalidMethod', f"Unknown method '{name}'.", 'normalize')
    if method is not None and (center is not None or scale is not None):
        raise err('MATLAB:normalize:InvalidMethodCombination', "Only 'center' and 'scale' may be given together.", 'normalize')
    if method is None and center is None and scale is None:
        method = ('zscore', 'std')

    def stat(what, a=None):
        return along(x, dim, lambda m: _norm_stat(m, what, a)[..., 0])

    C, S = 0.0, 1.0
    if method is not None:
        kind, opt_ = method
        if kind == 'zscore':
            C = stat('mean' if opt_ == 'std' else 'median')
            S = stat('std' if opt_ == 'std' else 'mad')
        elif kind == 'norm':
            S = stat('norm', opt_)
        elif kind == 'range':
            lo, hi = stat('min'), stat('max')
            a, b = opt_
            S = (hi - lo) / (b - a)
            C = lo - a * S
        else:
            C, S = stat('median'), stat('iqr')
    if center is not None:
        C = stat(center) if isinstance(center, str) else center
    if scale is not None:
        S = stat(scale) if isinstance(scale, str) else scale
    with np.errstate(all='ignore'):
        N = ((x - C) / S).reshape(shape)

    def back(v):
        v = np.asarray(v)
        if cls == 'single':
            return finish(v.astype(np.complex64 if v.dtype.kind == 'c' else np.float32), 'single')
        return out(v.astype(F64) if v.dtype.kind != 'c' else v)
    if nargout <= 1:
        return back(N)
    return (back(N), back(C), back(S))[:nargout]


def _mov_spread(seg, omit, w, sq):
    """The variance (sq) or standard deviation of each window, normalized by
    N - 1 (w 0; by N for a single value) or by N (w 1)."""
    if omit:
        n = np.sum(~np.isnan(seg), axis=-1)
        mu = np.nanmean(seg, axis=-1, keepdims=True)
        ss = np.nansum(np.abs(seg - mu) ** 2, axis=-1)
    else:
        n = np.full(seg.shape[:-1], seg.shape[-1])
        mu = np.mean(seg, axis=-1, keepdims=True)
        ss = np.sum(np.abs(seg - mu) ** 2, axis=-1)
    d = np.where((w == 1) | (n <= 1), n, n - 1)
    v = np.where(n == 0, np.nan, ss / np.where(d == 0, 1, d))
    return v if sq else np.sqrt(v)


def _mov_mad(seg, omit):
    med = (np.nanmedian if omit else np.median)(seg, axis=-1, keepdims=True)
    return (np.nanmedian if omit else np.median)(np.abs(seg - med), axis=-1)


_MOV_STATS = {
    'movmean': lambda s, o, w: (np.nanmean if o else np.mean)(s, axis=-1),
    'movsum': lambda s, o, w: (np.nansum if o else np.sum)(s, axis=-1),
    'movprod': lambda s, o, w: (np.nanprod if o else np.prod)(s, axis=-1),
    'movmax': lambda s, o, w: (np.nanmax if o else np.max)(s, axis=-1),
    'movmin': lambda s, o, w: (np.nanmin if o else np.min)(s, axis=-1),
    'movmedian': lambda s, o, w: (np.nanmedian if o else np.median)(s, axis=-1),
    'movmad': lambda s, o, w: _mov_mad(s, o),
    'movstd': lambda s, o, w: _mov_spread(s, o, w, False),
    'movvar': lambda s, o, w: _mov_spread(s, o, w, True),
}


def _movfun(name, args):
    """movXXX(A, k, [w,] dim, nanflag, 'Endpoints', e): a statistic of each
    window of k values centred on an element (k/2 before and k/2 - 1 after
    for an even k), or of [kb kf] values before and after; windows shrink at
    the ends unless Endpoints is 'discard', 'fill' or a value."""
    nargchk(args, 2, 9, name)
    x0 = args[0]
    cls = class_of(x0)
    x = np.asarray(arr(x0, name))
    x = x.astype(C128 if x.dtype.kind == 'c' else F64)
    k = darr(args[1]).reshape(-1)
    if k.size == 1:
        if not (k[0] > 0) or k[0] != int(k[0]):
            raise err(f'MATLAB:{name}:wrongWindowLength', 'The window length must be a positive integer (or [kb kf]).', name)
        kk = int(k[0])
        before, after = kk // 2, kk - kk // 2 - 1
    elif k.size == 2 and np.all(k >= 0) and np.all(k == np.floor(k)):
        before, after = int(k[0]), int(k[1])
    else:
        raise err(f'MATLAB:{name}:wrongWindowLength', 'The window is a positive integer or two nonnegative integers [kb kf].', name)
    rest = list(args[2:])
    w = 0
    if name in ('movstd', 'movvar') and rest and opt_str(rest[0]) is None:
        wv = rest.pop(0)
        if numel(wv):
            w = num(wv)
            if w not in (0, 1):
                raise err(f'MATLAB:{name}:wrongWeight', 'The normalization weight must be 0 or 1.', name)
    dim = None
    if rest and opt_str(rest[0]) is None:
        dim = min(int(num(rest.pop(0))) - 1, 30)
    omit, ends = False, 'shrink'
    i = 0
    while i < len(rest):
        o = (opt_str(rest[i]) or '').lower()
        if o in ('omitnan', 'omitmissing'):
            omit = True
        elif o in ('includenan', 'includemissing'):
            omit = False
        elif o == 'endpoints' and i + 1 < len(rest):
            e = rest[i + 1]
            ends = opt_lower(e) if opt_str(e) is not None else float(num(e))
            if isinstance(ends, str) and ends not in ('shrink', 'discard', 'fill'):
                raise err(f'MATLAB:{name}:invalidEndpoints', "Endpoints is 'shrink', 'discard', 'fill' or a number.", name)
            i += 1
        elif o == 'samplepoints':
            raise err(f'MATLAB:{name}:samplePoints', 'SamplePoints is not supported here.', name)
        else:
            raise err(f'MATLAB:{name}:invalidOption', f"Unknown option '{opt_str(rest[i])}'.", name)
        i += 1
    if dim is None:
        dim = first_dim(x.shape)
    X = np.moveaxis(expand_dims(x, dim), dim, -1)
    n = X.shape[-1]
    stat = _MOV_STATS[name]
    R = np.empty(X.shape, X.dtype if name not in ('movstd', 'movvar', 'movmad') else F64)
    with warnings.catch_warnings(), np.errstate(all='ignore'):
        warnings.simplefilter('ignore', RuntimeWarning)
        for j in range(n):
            lo, hi = max(0, j - before), min(n, j + after + 1)
            R[..., j] = stat(X[..., lo:hi], omit, w)
    full = (np.arange(n) - before >= 0) & (np.arange(n) + after < n)
    if ends == 'discard':
        R = R[..., full]
    elif ends != 'shrink':
        R[..., ~full] = np.nan if ends == 'fill' else ends
    R = np.moveaxis(R, -1, dim)
    if cls == 'single':
        return finish(R.astype(np.complex64 if R.dtype.kind == 'c' else np.float32), 'single')
    if cls in INT_CLASSES and name in ('movmax', 'movmin', 'movsum', 'movprod', 'movmedian'):
        return finish(R, cls)
    return out(R)


for _name in _MOV_STATS:
    bi(_name)((lambda nm: lambda nargout, *args: _movfun(nm, args))(_name))


@bi('rms')
def rms(nargout, *args):
    """sqrt(mean(abs(x).^2)) along a dimension, a vector of them or 'all';
    'omitnan' leaves NaN out."""
    nargchk(args, 1, 3, 'rms')
    rest, flags = strip_flags(args[1:], ('omitnan', 'includenan', 'omitmissing', 'includemissing'))
    omit = any(f in ('omitnan', 'omitmissing') for f in flags)
    x = np.asarray(arr(args[0], 'rms'))
    single = x.dtype == np.float32 or x.dtype == np.complex64
    x = np.abs(x.astype(C128 if x.dtype.kind == 'c' else F64)) ** 2
    dim = dims_arg(rest[0], 'rms') if rest else None

    def f(m):
        with warnings.catch_warnings(), np.errstate(all='ignore'):
            warnings.simplefilter('ignore', RuntimeWarning)
            if m.shape[-1] == 0:
                return np.full(m.shape[:-1], np.nan)
            return np.sqrt((np.nanmean if omit else np.mean)(m, axis=-1))
    r = along(x, dim, f)
    return finish(r.astype(np.float32), 'single') if single else out(r)
