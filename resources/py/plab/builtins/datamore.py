"""More functions of data: mink, maxk, clip, rmoutliers, allfinite,
anynan, isuniform, resize, paddata, trimdata, cbrt and interpft; and of
tables: groupcounts, grouptransform, groupfilter, pivot, topkrows and lag."""
import math

import numpy as np

from . import bi as _register
from ._util import err, nargchk, out, num, opt_str, is_str, darr, arr
from ..values import MError, Char, Cell, Struct, Str, FH, EMPTY, numel, py_str, text_list
from .. import runtime as R


def bi(*names, **kw):
    def deco(f):
        aw = kw.get('aw', False)
        if aw:
            async def g(*a):
                try:
                    return await f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, ZeroDivisionError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        else:
            def g(*a):
                try:
                    return f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, ZeroDivisionError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _dim_of(a, args, k, fn):
    if len(args) > k and not is_str(args[k]):
        d = int(num(args[k]))
        if d < 1:
            raise err(f'MATLAB:{fn}:dim', 'The dimension is a positive integer.', fn)
        return d - 1
    return next((i for i, s in enumerate(a.shape) if s != 1), 0)


# ---- smallest and largest k ---------------------------------------------------------------------------------------------------

def _topk(nargout, args, fn, largest):
    nargchk(args, 2, 5, fn)
    a = arr(args[0], fn)
    k = int(num(args[1]))
    if k < 0:
        raise err(f'MATLAB:{fn}:k', 'k is a nonnegative integer.', fn)
    words = [py_str(x).lower() for x in args[2:] if is_str(x)]
    absval = 'abs' in words
    dim = _dim_of(a, [x for x in args if not is_str(x)], 2, fn)
    if a.ndim <= dim:
        a = a.reshape(a.shape + (1,) * (dim + 1 - a.ndim))
    x = np.moveaxis(a, dim, 0)
    key = np.abs(x) if absval else x
    keyf = key.astype(float) if key.dtype.kind != 'c' else np.abs(key)
    # NaN last, whichever way: the k largest (or smallest) numbers first
    sortkey = np.where(np.isnan(keyf), np.inf if not largest else -np.inf, keyf)
    order = np.argsort(-sortkey if largest else sortkey, axis=0, kind='stable')
    order = order[:min(k, x.shape[0])]
    B = np.take_along_axis(x, order, axis=0)
    B = np.moveaxis(B, 0, dim)
    I = np.moveaxis(order + 1.0, 0, dim)
    return (B, I) if nargout > 1 else B


@bi('mink', nout=2)
def mink(nargout, *args):
    """[B, I] = mink(A, k, dim, 'ComparisonMethod', 'abs'): the k smallest elements along a dimension, smallest first."""
    return _topk(nargout, args, 'mink', False)


@bi('maxk', nout=2)
def maxk(nargout, *args):
    """[B, I] = maxk(A, k, dim, 'ComparisonMethod', 'abs'): the k largest elements along a dimension, largest first."""
    return _topk(nargout, args, 'maxk', True)


@bi('clip')
def clip(nargout, *args):
    """C = clip(A, lower, upper): A's values held between lower and upper (NaN stays)."""
    nargchk(args, 3, 3, 'clip')
    a = arr(args[0], 'clip')
    lo, hi = darr(args[1]), darr(args[2])
    if np.any(lo > hi):
        raise err('MATLAB:clip:bounds', 'The lower bound is not above the upper.', 'clip')
    if a.dtype.kind in 'iu':
        r = np.clip(a.astype(float), lo, hi)
        info = np.iinfo(a.dtype)
        return np.clip(np.round(r), info.min, info.max).astype(a.dtype)
    with np.errstate(invalid='ignore'):
        r = np.minimum(np.maximum(a, lo), hi)
    return np.where(np.isnan(a), a, r) if a.dtype.kind == 'f' else r


@bi('allfinite')
def allfinite(nargout, *args):
    """tf = allfinite(A): whether every element is finite."""
    nargchk(args, 1, 1, 'allfinite')
    a = arr(args[0], 'allfinite')
    return bool(np.all(np.isfinite(a))) if a.dtype.kind in 'fc' else True


@bi('anynan')
def anynan(nargout, *args):
    """tf = anynan(A): whether any element is NaN."""
    nargchk(args, 1, 1, 'anynan')
    a = arr(args[0], 'anynan')
    return bool(np.any(np.isnan(a))) if a.dtype.kind in 'fc' else False


@bi('isuniform', nout=2)
def isuniform(nargout, *args):
    """[tf, step] = isuniform(v): whether a vector's values are evenly spaced (to round-off), and the spacing (NaN when not).
    A scalar or an empty array is not uniform; a single vector's step is single."""
    nargchk(args, 1, 1, 'isuniform')
    raw = arr(args[0], 'isuniform')
    single = raw.dtype == np.float32
    v = darr(args[0], 'isuniform').reshape(-1)

    def res(tf, step):
        step = out(np.full((1, 1), step, np.float32)) if single else float(step)
        return (bool(tf), step) if nargout > 1 else bool(tf)
    if v.size < 2 or not np.all(np.isfinite(v)):
        return res(False, np.nan)
    d = np.diff(v)
    step = (v[-1] - v[0]) / (v.size - 1)
    eps_of = np.spacing(np.float32(1)) / np.spacing(1.0) if single else 1.0
    tol = 4 * np.spacing(max(np.max(np.abs(v)), np.abs(step))) * eps_of
    tf = bool(np.all(np.abs(d - step) <= tol * max(v.size, 1)))
    return res(tf, step if tf else np.nan)


@bi('rmoutliers', nout=2)
def rmoutliers(nargout, *args):
    """[B, TFrm] = rmoutliers(A, method, dim, Name, Value): A without its outliers (isoutlier's methods); rows of a matrix with any (or MinNumOutliers) outlier go."""
    nargchk(args, 1, 12, 'rmoutliers')
    a = args[0]
    rest = list(args[1:])
    minn = 1
    # MinNumOutliers is rmoutliers' own; the rest goes to isoutlier
    keep = []
    i = 0
    while i < len(rest):
        if is_str(rest[i]) and py_str(rest[i]).lower() == 'minnumoutliers' and i + 1 < len(rest):
            minn = int(num(rest[i + 1]))
            i += 2
            continue
        keep.append(rest[i])
        i += 1
    # the dimension: the numeric argument after the method (after the window for a moving method)
    dim = 0
    k = 0
    moving = False
    if keep and is_str(keep[0]) and py_str(keep[0]).lower() in ('median', 'mean', 'quartiles', 'grubbs', 'gesd', 'movmedian', 'movmean'):
        moving = py_str(keep[0]).lower().startswith('mov')
        k = 1
    if moving and k < len(keep) and not is_str(keep[k]):
        k += 1
    if k < len(keep) and not is_str(keep[k]):
        dim = int(num(keep[k])) - 1
    A = arr(a, 'rmoutliers')
    vec = A.ndim == 2 and min(A.shape) == 1
    TF = arr(R._builtin('isoutlier', a, *keep))
    if vec:
        flat = A.reshape(-1)
        tf = TF.reshape(-1)
        B = flat[~tf].reshape((1, -1) if A.shape[0] == 1 else (-1, 1))
        return (B, out(tf.reshape(A.shape))) if nargout > 1 else B
    cnt = TF.sum(axis=1 - dim) if A.ndim == 2 else TF.sum(axis=1)
    drop = cnt >= minn
    B = A[~drop] if dim == 0 else A[:, ~drop]
    return (B, out(drop.reshape(-1, 1) if dim == 0 else drop.reshape(1, -1))) if nargout > 1 else B


@bi('cbrt')
def cbrt(nargout, *args):
    """y = cbrt(x): the real cube root."""
    nargchk(args, 1, 1, 'cbrt')
    a = arr(args[0], 'cbrt')
    if a.dtype.kind == 'c':
        raise err('MATLAB:cbrt:complex', 'cbrt takes real numbers (nthroot too; x.^(1/3) gives the principal complex root).', 'cbrt')
    r = np.cbrt(a.astype(np.float32) if a.dtype == np.float32 else a.astype(float))
    return r if r.size != 1 or r.ndim != 2 else r


@bi('interpft')
def interpft(nargout, *args):
    """y = interpft(x, n, dim): x resampled to n points by its Fourier transform (x taken as periodic)."""
    nargchk(args, 2, 3, 'interpft')
    x = darr(args[0], 'interpft')
    n = int(num(args[1]))
    if n < 1:
        raise err('MATLAB:interpft:n', 'n is a positive integer.', 'interpft')
    dim = _dim_of(x, args, 2, 'interpft')
    X = np.moveaxis(x, dim, 0)
    m = X.shape[0]
    if m == 0:
        return x
    incr = 1
    ny = n
    if n < m:
        incr = m // n + 1
        ny = incr * n
    a = np.fft.fft(X, axis=0)
    nyq = int(math.ceil((m + 1) / 2))
    b = np.concatenate([a[:nyq], np.zeros((ny - m,) + a.shape[1:], complex), a[nyq:]], axis=0)
    if m % 2 == 0:
        b[nyq - 1] = b[nyq - 1] / 2
        b[nyq - 1 + ny - m] = b[nyq - 1]
    y = np.fft.ifft(b, axis=0) * (ny / m)
    if not np.iscomplexobj(x):
        y = y.real
    y = y[::incr]
    return np.moveaxis(y, 0, dim)


# ---- resize, paddata, trimdata -----------------------------------------------------------------------------------------------------

def _resize(nargout, args, fn, pad, trim):
    nargchk(args, 2, 12, fn)
    from .tables import Table, _take_rows, _cat_rows, _missing_like
    A = args[0]
    m = darr(args[1]).reshape(-1).astype(int)
    o = {}
    rest = list(args[2:])
    for i in range(0, len(rest) - 1, 2):
        o[py_str(rest[i]).lower()] = rest[i + 1]
    pattern = py_str(o.get('pattern', Char.of('constant'))).lower()
    side = py_str(o.get('side', Char.of('trailing'))).lower()
    fill = o.get('fillvalue', None)
    if isinstance(A, Table):
        n = A.n
        target = int(m[0])
        if target >= n and not pad or target < n and not trim:
            return A
        if target < n:
            keep = list(range(n - target, n)) if side == 'leading' else list(range(target)) if side == 'trailing' else list(range((n - target) // 2, (n - target) // 2 + target))
            return A.copy_meta([_take_rows(v, keep) for v in A.vars], A.names, [A.rownames[i] for i in keep] if A.rownames else None, len(keep), keep=list(range(len(A.vars))))
        extra = target - n
        vars_ = [_cat_rows([v, _missing_like(v, extra)]) if side != 'leading' else _cat_rows([_missing_like(v, extra), v]) for v in A.vars]
        return A.copy_meta(vars_, A.names, None, target, keep=list(range(len(A.vars))))
    a = arr(A, fn)
    if 'dimension' in o:
        dims = [int(d) - 1 for d in darr(o['dimension']).reshape(-1)]
    elif m.size == 1:
        dims = [next((i for i, s in enumerate(a.shape) if s != 1), 0)]
    else:
        dims = list(range(m.size))
    sizes = m if m.size == len(dims) else np.repeat(m, len(dims))
    fv = 0.0 if fill is None else float(darr(fill).reshape(-1)[0])
    for d, size in zip(dims, sizes):
        while a.ndim <= d:
            a = a[..., None]
        cur = a.shape[d]
        size = int(size)
        if size < cur and trim:
            if side == 'leading':
                sl = slice(cur - size, cur)
            elif side == 'both':
                s0 = (cur - size) // 2
                sl = slice(s0, s0 + size)
            else:
                sl = slice(0, size)
            idx = [slice(None)] * a.ndim
            idx[d] = sl
            a = a[tuple(idx)]
        elif size > cur and pad:
            extra = size - cur
            before = extra if side == 'leading' else (extra // 2 if side == 'both' else 0)
            after = extra - before
            widths = [(0, 0)] * a.ndim
            widths[d] = (before, after)
            mode = {'constant': 'constant', 'edge': 'edge', 'circular': 'wrap', 'flip': 'symmetric', 'reflect': 'reflect'}.get(pattern)
            if mode is None:
                raise err(f'MATLAB:{fn}:pattern', "The pattern is 'constant', 'edge', 'circular', 'flip' or 'reflect'.", fn)
            if mode == 'constant':
                a = np.pad(a, widths, mode='constant', constant_values=np.asarray(fv).astype(a.dtype) if a.dtype.kind != 'b' else bool(fv))
            else:
                a = np.pad(a, widths, mode=mode)
    return a


@bi('resize')
def resize(nargout, *args):
    """B = resize(A, m, 'Dimension', dim, 'Pattern', p, 'FillValue', v, 'Side', s): A padded or cut to size m (trailing, leading or both sides)."""
    return _resize(nargout, args, 'resize', True, True)


@bi('paddata')
def paddata(nargout, *args):
    """B = paddata(A, m, ...): A padded to size m ('constant' 0 unless a FillValue or Pattern is given); never cut."""
    return _resize(nargout, args, 'paddata', True, False)


@bi('trimdata')
def trimdata(nargout, *args):
    """B = trimdata(A, m, 'Side', s): A cut to size m; never padded."""
    return _resize(nargout, args, 'trimdata', False, True)


# ---- tables: counts, transforms, filters, pivots ------------------------------------------------------------------------------------

def _tab(v, fn):
    from .tables import Table
    if not isinstance(v, Table):
        raise err(f'MATLAB:{fn}:table', f'{fn} takes a table (or timetable).', fn)
    return v


def _groups(T, gv):
    from .tables import _row_keys
    keys = [tuple(x for g in gv for x in _row_keys(T.vars[g], T.n)[i]) for i in range(T.n)]
    uniq = sorted(set(keys))
    pos = {k: i for i, k in enumerate(uniq)}
    gid = np.array([pos[k] for k in keys], int)
    first = [int(np.flatnonzero(gid == g)[0]) for g in range(len(uniq))]
    return gid, first


@bi('groupcounts', nout=3)
def groupcounts(nargout, *args):
    """G = groupcounts(T, groupvars), [B, BG, BP] = groupcounts(A): how many rows (elements) fall in each group, with GroupCount and Percent."""
    nargchk(args, 1, 8, 'groupcounts')
    from .tables import Table, _take_rows
    a0 = args[0]
    if isinstance(a0, Table):
        T = a0
        gv = T.var_index(args[1]) if len(args) > 1 and not (is_str(args[1]) and py_str(args[1]).lower() in ('includeemptygroups', 'includepercentgroups')) else list(range(len(T.vars)))
        gid, first = _groups(T, gv)
        cnt = np.bincount(gid, minlength=len(first)).astype(float)
        vars_ = [_take_rows(T.vars[g], first) for g in gv] + [cnt.reshape(-1, 1), (100 * cnt / max(T.n, 1)).reshape(-1, 1)]
        return Table(vars_, [T.names[g] for g in gv] + ['GroupCount', 'Percent'], None, len(first))
    from .tables import _row_keys
    v = a0
    n = numel(v)
    col = v if not (type(v) is np.ndarray and v.ndim == 2 and v.shape[0] == 1) else out(np.asarray(v).reshape(-1, 1))
    keys = [k for k in _row_keys(col, n)]
    uniq = sorted(set(keys))
    pos = {k: i for i, k in enumerate(uniq)}
    gid = np.array([pos[k] for k in keys], int)
    cnt = np.bincount(gid, minlength=len(uniq)).astype(float).reshape(-1, 1)
    first = [int(np.flatnonzero(gid == g)[0]) for g in range(len(uniq))]
    BG = _take_rows(col, first)
    res = (cnt, BG, 100 * cnt / max(n, 1))
    return res[:nargout] if nargout > 1 else res[0]


_TRANSFORMS = {
    'zscore': lambda x: (x - np.nanmean(x)) / (np.nanstd(x, ddof=1) if np.nanstd(x, ddof=1) > 0 else 1.0),
    'norm': lambda x: x / (np.sqrt(np.nansum(x * x)) or 1.0),
    'meancenter': lambda x: x - np.nanmean(x),
    'rescale': lambda x: (x - np.nanmin(x)) / ((np.nanmax(x) - np.nanmin(x)) or 1.0),
    'meanfill': lambda x: np.where(np.isnan(x), np.nanmean(x) if np.any(~np.isnan(x)) else np.nan, x),
    'linearfill': lambda x: _linfill(x),
}


def _linfill(x):
    ok = ~np.isnan(x)
    if ok.sum() < 2:
        return x
    idx = np.arange(x.size)
    y = x.copy()
    y[~ok] = np.interp(idx[~ok], idx[ok], x[ok], left=np.nan, right=np.nan)
    return y


@bi('grouptransform', aw=True)
async def grouptransform(nargout, *args):
    """G = grouptransform(T, groupvars, method, datavars, 'ReplaceValues', tf): each group's data transformed: 'zscore', 'norm', 'meancenter', 'rescale', 'meanfill', 'linearfill', or a function of a column."""
    nargchk(args, 3, 8, 'grouptransform')
    T = _tab(args[0], 'grouptransform')
    gv = T.var_index(args[1])
    method = args[2]
    rest = list(args[3:])
    replace = True
    dv = None
    i = 0
    while i < len(rest):
        if is_str(rest[i]) and py_str(rest[i]).lower() == 'replacevalues' and i + 1 < len(rest):
            replace = bool(num(rest[i + 1]))
            i += 2
            continue
        dv = T.var_index(rest[i])
        i += 1
    if dv is None:
        dv = [k for k, v in enumerate(T.vars) if k not in gv and type(v) is np.ndarray and v.dtype.kind in 'fiub']
    gid, _ = _groups(T, gv)
    new_vars = list(T.vars)
    names = list(T.names)
    for k in dv:
        x = np.asarray(T.vars[k], float).reshape(T.n, -1)
        y = np.empty_like(x)
        for g in np.unique(gid):
            m = gid == g
            for j in range(x.shape[1]):
                col = x[m, j]
                if isinstance(method, FH):
                    r = await method.acall(1, col.reshape(-1, 1))
                    r = np.asarray(darr(r), float).reshape(-1)
                    y[m, j] = r if r.size == col.size else np.full(col.size, r[0])
                else:
                    f = _TRANSFORMS.get(py_str(method).lower())
                    if f is None:
                        raise err('MATLAB:grouptransform:method', f"The method is one of {', '.join(_TRANSFORMS)} or a function handle.", 'grouptransform')
                    y[m, j] = f(col)
        if replace:
            new_vars[k] = y
        else:
            mname = py_str(method) if not isinstance(method, FH) else 'fun'
            new_vars.append(y)
            names.append(f'{mname}_{T.names[k]}')
    if replace:
        return T.copy_meta(new_vars, names, T.rownames, T.n, keep=list(range(len(T.vars))))
    return _plain(T, new_vars, names)


def _plain(T, vars_, names):
    from .tables import Table, TimeTable
    if isinstance(T, TimeTable):
        return TimeTable(vars_, names, T.times)
    return Table(vars_, names, T.rownames, T.n)


@bi('groupfilter', aw=True)
async def groupfilter(nargout, *args):
    """G = groupfilter(T, groupvars, method, datavars): the rows of the groups (or the elements) for which method, a function of a group's column giving a logical scalar (or vector), is true."""
    nargchk(args, 3, 4, 'groupfilter')
    from .tables import _take_rows
    T = _tab(args[0], 'groupfilter')
    gv = T.var_index(args[1])
    method = args[2]
    if not isinstance(method, FH):
        raise err('MATLAB:groupfilter:method', 'The method is a function handle giving true or false.', 'groupfilter')
    dv = T.var_index(args[3]) if len(args) > 3 else [k for k in range(len(T.vars)) if k not in gv]
    gid, _ = _groups(T, gv)
    keep = np.ones(T.n, bool)
    for g in np.unique(gid):
        m = np.flatnonzero(gid == g)
        for k in dv:
            r = await method.acall(1, _take_rows(T.vars[k], list(m)))
            tf = np.asarray(arr(r), bool).reshape(-1)
            if tf.size == 1:
                if not tf[0]:
                    keep[m] = False
            elif tf.size == m.size:
                keep[m] &= tf
            else:
                raise err('MATLAB:groupfilter:size', 'The method gives a logical scalar or one value for each row of the group.', 'groupfilter')
    rows = list(np.flatnonzero(keep))
    return T.copy_meta([_take_rows(v, rows) for v in T.vars], T.names, [T.rownames[i] for i in rows] if T.rownames else None, len(rows), keep=list(range(len(T.vars))))


@bi('pivot', aw=True)
async def pivot(nargout, *args):
    """P = pivot(T, 'Columns', cvar, 'Rows', rvar, 'DataVariable', dvar, 'Method', m): a table of a statistic (count unless a data variable gives sum) for each row and column group."""
    nargchk(args, 3, 13, 'pivot')
    from .tables import Table, _take_rows, _valid_name
    T = _tab(args[0], 'pivot')
    o = {}
    for i in range(1, len(args) - 1, 2):
        o[py_str(args[i]).lower()] = args[i + 1]
    if 'columns' not in o:
        raise err('MATLAB:pivot:columns', "pivot needs 'Columns'.", 'pivot')
    cv = T.var_index(o['columns'])
    rv = T.var_index(o['rows']) if 'rows' in o else []
    dv = T.var_index(o['datavariable'])[0] if 'datavariable' in o else None
    method = o.get('method', Char.of('sum' if dv is not None else 'count'))
    cg, cfirst = _groups(T, cv)
    rg, rfirst = _groups(T, rv) if rv else (np.zeros(T.n, int), [0])
    clab = []
    for f in cfirst:
        parts = []
        for k in cv:
            v = _take_rows(T.vars[k], [f])
            parts.append(py_str(R._builtin('string', v)) if not isinstance(v, (Char, Str)) else py_str(v))
        name = '_'.join(parts)
        clab.append(name if _valid_name(name) else py_str(R.BUILTINS['matlab.lang.makeValidName'].fn(1, Char.of(name))))
    vals = np.asarray(T.vars[dv], float).reshape(-1) if dv is not None else np.ones(T.n)
    M = np.full((len(rfirst), len(cfirst)), np.nan)
    fns = {'count': len, 'sum': np.sum, 'mean': np.mean, 'median': np.median, 'max': np.max, 'min': np.min, 'mode': lambda v: float(R._builtin('mode', v.reshape(-1, 1))),
           'std': lambda v: np.std(v, ddof=1) if v.size > 1 else 0.0, 'var': lambda v: np.var(v, ddof=1) if v.size > 1 else 0.0, 'none': lambda v: v[0]}
    for i in range(len(rfirst)):
        for j in range(len(cfirst)):
            m = (rg == i) & (cg == j)
            if not m.any():
                if py_str(method).lower() in ('count', 'sum') if not isinstance(method, FH) else False:
                    M[i, j] = 0.0
                continue
            if isinstance(method, FH):
                M[i, j] = float(num(await method.acall(1, vals[m].reshape(-1, 1))))
            else:
                f = fns.get(py_str(method).lower())
                if f is None:
                    raise err('MATLAB:pivot:method', f"The method is one of {', '.join(fns)} or a function handle.", 'pivot')
                M[i, j] = float(f(vals[m]))
    vars_ = [_take_rows(T.vars[k], rfirst) for k in rv] + [M[:, j].reshape(-1, 1) for j in range(len(cfirst))]
    names = [T.names[k] for k in rv] + clab
    seen = set()
    for i, nm in enumerate(names):
        while nm in seen:
            nm += '_1'
        names[i] = nm
        seen.add(nm)
    return Table(vars_, names, None, len(rfirst))


@bi('topkrows', nout=2)
def topkrows(nargout, *args):
    """[B, I] = topkrows(X, k, col, direction), topkrows(T, k, vars, direction): the k rows that sort first (largest first unless 'ascend')."""
    nargchk(args, 2, 8, 'topkrows')
    from .tables import Table, _take_rows
    X = args[0]
    k = int(num(args[1]))
    rest = list(args[2:])
    cols = None
    dirs = []
    for x in rest:
        if is_str(x) and py_str(x).lower() in ('ascend', 'descend'):
            dirs.append(py_str(x).lower())
        elif isinstance(x, Cell) and all(py_str(y).lower() in ('ascend', 'descend') for y in x.a.reshape(-1)):
            dirs += [py_str(y).lower() for y in x.a.reshape(-1)]
        elif is_str(x) and py_str(x).lower() == 'comparisonmethod':
            continue
        elif cols is None:
            cols = x
    if isinstance(X, Table):
        from .tables import _row_keys
        vi = list(range(len(X.vars))) if cols is None else X.var_index(cols)
        ds = dirs if len(dirs) == len(vi) else (dirs * len(vi) if dirs else ['descend'] * len(vi))
        order = list(range(X.n))
        for v, d in reversed(list(zip(vi, ds))):
            keys = _row_keys(X.vars[v], X.n)
            order = sorted(order, key=lambda r: keys[r], reverse=(d == 'descend'))
        idx = order[:k]
        res = (X.copy_meta([_take_rows(v, idx) for v in X.vars], X.names, [X.rownames[i] for i in idx] if X.rownames else None, len(idx), keep=list(range(len(X.vars)))),
               np.array(idx, float).reshape(-1, 1) + 1)
        return res if nargout > 1 else res[0]
    A = arr(X, 'topkrows')
    if A.ndim == 1:
        A = A.reshape(-1, 1)
    cidx = list(range(A.shape[1])) if cols is None else [int(c) for c in darr(cols).reshape(-1)]
    signs = [(-1 if c < 0 else 1) for c in cidx]
    cidx = [abs(c) - 1 if cols is not None else c for c in cidx]
    if not dirs:
        dirs = ['descend'] * len(cidx)
    elif len(dirs) == 1:
        dirs = dirs * len(cidx)
    keys = []
    for c, d, sg in reversed(list(zip(cidx, dirs, signs))):
        col = A[:, c].astype(float)
        desc = (d == 'descend') != (sg < 0)
        keys.append(-col if desc else col)
    order = np.lexsort(keys) if keys else np.arange(A.shape[0])
    order = order[:k]
    return (A[order], (order + 1.0).reshape(-1, 1)) if nargout > 1 else A[order]


@bi('lag')
def lag(nargout, *args):
    """TT2 = lag(TT, n): a timetable's data moved n rows later (earlier for negative n), missing values where there is nothing; the row times stay."""
    nargchk(args, 1, 2, 'lag')
    from .tables import TimeTable, _take_rows, _cat_rows, _missing_like
    TT = args[0]
    if not isinstance(TT, TimeTable):
        raise err('MATLAB:lag:timetable', 'lag takes a timetable.', 'lag')
    n = int(num(args[1])) if len(args) > 1 else 1
    N = TT.n
    vars_ = []
    for v in TT.vars:
        if n >= 0:
            k = min(n, N)
            vars_.append(_cat_rows([_missing_like(v, k), _take_rows(v, list(range(N - k)))]))
        else:
            k = min(-n, N)
            vars_.append(_cat_rows([_take_rows(v, list(range(k, N))), _missing_like(v, k)]))
    return TimeTable(vars_, TT.names, TT.times)
