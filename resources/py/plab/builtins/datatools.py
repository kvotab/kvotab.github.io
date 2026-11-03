"""Cleaning and grouping data: fillmissing, rmmissing, standardizeMissing,
isoutlier, filloutliers, smoothdata, findgroups, splitapply, histcounts2."""
import math
import warnings

import numpy as np

from . import bi
from ._util import err, nargchk, arr, darr, out, opt_str, opt_lower, num, is_str, first_dim, expand_dims, like_class
from ..values import Char, Cell, Struct, Str, F64, class_of, shape_of, numel, py_str, text_list
from ..ops import cat as _cat, finish
from .. import runtime as R

# the scale that makes the median absolute deviation estimate a normal standard deviation
_MAD_SCALE = 1.482602218505602


# ---- missing values -------------------------------------------------------------------------------------------

class _Data:
    """An array whose missing entries are known: numbers (NaN), a cell of
    text (''), a string array (missing) or characters (blank)."""

    def __init__(self, v, fn):
        self.v = v
        self.kind = type(v).__name__
        if type(v) is Cell:
            if not all(type(x) is Char for x in v.a.reshape(-1)):
                raise err(f'MATLAB:{fn}:InvalidInput', 'A cell array must hold character vectors.', fn)
            self.a = v.a.copy()
            self.miss = np.vectorize(lambda x: x.a.size == 0, otypes=[bool])(self.a) if self.a.size else np.zeros(self.a.shape, bool)
        elif type(v) is Str:
            self.a = v.a.copy()
            self.miss = np.vectorize(lambda x: x is None, otypes=[bool])(self.a) if self.a.size else np.zeros(self.a.shape, bool)
        elif type(v) is Char:
            self.a = v.a.copy()
            self.miss = self.a == 32
        else:
            a = np.asarray(arr(v, fn))
            self.a = a.copy()
            self.miss = np.isnan(a) if a.dtype.kind in 'fc' else np.zeros(a.shape, bool)
        self.numeric = self.kind not in ('Cell', 'Str', 'Char')

    def back(self, a):
        if self.kind == 'Cell':
            return Cell(a)
        if self.kind == 'Str':
            return Str(a)
        if self.kind == 'Char':
            return Char(a)
        return like_class(a, self.v) if class_of(self.v) != 'logical' else out(a)


def _dim_of(v, rest, fn):
    """A dimension number among the trailing inputs (0-based), else the first that is not 1."""
    for i, x in enumerate(rest):
        if opt_str(x) is None and not isinstance(x, (Cell,)) and numel(x) == 1:
            return int(num(x)) - 1, rest[:i] + rest[i + 1:]
    return None, rest


def _interp_fill(xk, yk, xq, method):
    """Values at xq from the known points (xk, yk) by an interpolation method,
    extrapolating past the ends."""
    from scipy import interpolate as I
    if xk.size == 1:
        return np.full(xq.shape, yk[0])
    if method == 'linear':
        f = I.interp1d(xk, yk, kind='linear', fill_value='extrapolate', assume_sorted=True)
    elif method == 'spline':
        f = I.CubicSpline(xk, yk, bc_type='not-a-knot' if xk.size > 3 else 'natural', extrapolate=True) if xk.size > 2 else I.interp1d(xk, yk, fill_value='extrapolate')
    elif method == 'pchip':
        f = I.PchipInterpolator(xk, yk, extrapolate=True)
    elif method == 'makima':
        if xk.size < 3:
            f = I.interp1d(xk, yk, fill_value='extrapolate')
        else:
            try:
                f = I.Akima1DInterpolator(xk, yk, method='makima', extrapolate=True)
            except TypeError:
                f = I.Akima1DInterpolator(xk, yk)
    else:
        raise ValueError(method)
    return np.asarray(f(xq))


_FILL_METHODS = ('constant', 'previous', 'next', 'nearest', 'linear', 'spline', 'pchip', 'makima', 'movmean', 'movmedian')


def _fill_vector(y, miss, method, arg, ends, maxgap, text):
    """One vector with its missing entries filled; returns (values, filled mask)."""
    n = y.size
    known = np.flatnonzero(~miss)
    filled = np.zeros(n, bool)
    if not miss.any():
        return y, filled
    y = y.copy()
    idx = np.flatnonzero(miss)
    if maxgap is not None and known.size:
        # a gap is measured from the known value before it to the one after it
        before = np.searchsorted(known, idx) - 1
        after = before + 1
        span = np.where((before >= 0) & (after < known.size),
                        known[np.minimum(after, known.size - 1)] - known[np.maximum(before, 0)], np.inf)
        idx = idx[span <= maxgap]
    if method == 'constant':
        vals = arg
        y[idx] = vals[idx] if isinstance(vals, np.ndarray) and vals.size == n else vals
        filled[idx] = True
        return y, filled
    if known.size == 0:
        return y, filled
    interior = idx[(idx > known[0]) & (idx < known[-1])]
    lead, trail = idx[idx < known[0]], idx[idx > known[-1]]

    def by(kind, where):
        if where.size == 0:
            return
        pos = np.searchsorted(known, where)
        if kind == 'previous':
            ok = pos > 0
            y[where[ok]] = y[known[pos[ok] - 1]]
            filled[where[ok]] = True
        elif kind == 'next':
            ok = pos < known.size
            y[where[ok]] = y[known[pos[ok]]]
            filled[where[ok]] = True
        elif kind == 'nearest':
            lo = known[np.maximum(pos - 1, 0)]
            hi = known[np.minimum(pos, known.size - 1)]
            pick = np.where((where - lo) <= (hi - where), lo, hi)       # a tie goes to the earlier one
            pick = np.where(pos == 0, hi, np.where(pos == known.size, lo, pick))
            y[where] = y[pick]
            filled[where] = True
    if method in ('previous', 'next', 'nearest'):
        by(method, interior)
    elif method in ('movmean', 'movmedian'):
        before_n, after_n = arg
        fn = np.nanmean if method == 'movmean' else np.nanmedian
        yy = np.where(miss, np.nan, y.astype(F64))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            for i in idx:
                v = fn(yy[max(0, i - before_n):min(n, i + after_n + 1)])
                if not np.isnan(v):
                    y[i] = v
                    filled[i] = True
        return y, filled
    else:
        if text:
            raise err('MATLAB:fillmissing:InvalidMethodForText', f"'{method}' does not fill text.", 'fillmissing')
        if interior.size:
            y[interior] = _interp_fill(known.astype(F64), y[known].astype(F64), interior.astype(F64), method)
            filled[interior] = True
    ends_kind = 'extrap' if ends is None else ends
    for where in (lead, trail):
        if where.size == 0:
            continue
        if isinstance(ends_kind, str):
            if ends_kind == 'none':
                continue
            if ends_kind == 'extrap':
                if method in ('previous', 'next', 'nearest'):
                    by(method, where)
                elif method not in ('movmean', 'movmedian'):
                    y[where] = _interp_fill(known.astype(F64), y[known].astype(F64), where.astype(F64), method)
                    filled[where] = True
            else:
                by(ends_kind, where)
        else:
            y[where] = ends_kind
            filled[where] = True
    return y, filled


def _window(v, fn):
    k = darr(v).reshape(-1)
    if k.size == 1:
        kk = int(k[0])
        if kk < 1:
            raise err(f'MATLAB:{fn}:InvalidWindow', 'The window must be a positive integer or [kb kf].', fn)
        return kk // 2, kk - kk // 2 - 1
    return int(k[0]), int(k[1])


@bi('fillmissing', nout=2)
def fillmissing(nargout, *args):
    """[F, TF] = fillmissing(A, method, ...): missing entries filled along a
    dimension by 'constant' v, 'previous', 'next', 'nearest', 'linear',
    'spline', 'pchip', 'makima', or a moving 'movmean' or 'movmedian' over a
    window; EndValues ('extrap', 'previous', 'next', 'nearest', 'none' or a
    value) and MaxGap."""
    nargchk(args, 2, 10, 'fillmissing')
    D = _Data(args[0], 'fillmissing')
    method = (opt_str(args[1]) or '').lower()
    if method not in _FILL_METHODS:
        raise err('MATLAB:fillmissing:InvalidMethod', "The method is 'constant', 'previous', 'next', 'nearest', 'linear', 'spline', 'pchip', 'makima', 'movmean' or 'movmedian'.", 'fillmissing')
    rest = list(args[2:])
    arg = None
    if method == 'constant':
        if not rest:
            raise err('MATLAB:fillmissing:ConstantMissing', "'constant' needs a value.", 'fillmissing')
        c = rest.pop(0)
        if D.kind == 'Cell':
            arg = c if type(c) is Char else Char.of(text_list(c)[0])
        elif D.kind == 'Str':
            arg = text_list(c)[0]
        elif D.kind == 'Char':
            arg = ord(py_str(c)[0])
        else:
            arg = np.asarray(arr(c)).reshape(-1)
    elif method in ('movmean', 'movmedian'):
        if not rest:
            raise err('MATLAB:fillmissing:WindowMissing', f"'{method}' needs a window.", 'fillmissing')
        arg = _window(rest.pop(0), 'fillmissing')
    ends, maxgap, dim = None, None, None
    i = 0
    while i < len(rest):
        o = opt_str(rest[i])
        if o is None:
            dim = int(num(rest[i])) - 1
            i += 1
            continue
        key = o.lower()
        if i + 1 >= len(rest):
            raise err('MATLAB:fillmissing:NameValue', f"'{o}' needs a value.", 'fillmissing')
        val = rest[i + 1]
        if key == 'endvalues':
            e = opt_str(val)
            ends = e.lower() if e is not None else (float(num(val)) if D.numeric else (val if D.kind != 'Char' else ord(py_str(val)[0])))
            if isinstance(ends, str) and ends not in ('extrap', 'previous', 'next', 'nearest', 'none'):
                raise err('MATLAB:fillmissing:InvalidEndValues', "EndValues is 'extrap', 'previous', 'next', 'nearest', 'none' or a value.", 'fillmissing')
        elif key == 'maxgap':
            maxgap = float(num(val))
        elif key in ('samplepoints', 'datavariables', 'replacevalues', 'missinglocations'):
            raise err('MATLAB:fillmissing:Unsupported', f"'{o}' is not supported here.", 'fillmissing')
        else:
            raise err('MATLAB:fillmissing:InvalidOption', f"Unknown option '{o}'.", 'fillmissing')
        i += 2
    a, miss = D.a, D.miss
    if dim is None:
        dim = first_dim(a.shape)
    A = np.moveaxis(expand_dims(a, dim), dim, -1)
    M = np.moveaxis(expand_dims(miss, dim), dim, -1)
    if D.numeric and A.dtype.kind not in 'fc':
        return (D.back(a), out(np.zeros(a.shape, bool))) if nargout > 1 else D.back(a)
    F = A.copy()
    TF = np.zeros(A.shape, bool)
    cols = int(np.prod(A.shape[:-1])) if A.ndim > 1 else 1
    flatA = F.reshape(cols, A.shape[-1])
    flatM = M.reshape(cols, A.shape[-1])
    flatT = TF.reshape(cols, A.shape[-1])
    for c in range(cols):
        carg = arg
        if method == 'constant' and D.numeric and arg.size > 1:
            if arg.size != cols:
                raise err('MATLAB:fillmissing:SizeConstant', 'The constants must be one per vector filled.', 'fillmissing')
            carg = arg[c]
        elif method == 'constant' and D.numeric:
            carg = arg[0]
        if D.kind == 'Cell':
            vals = flatA[c]
            y, tf = _fill_vector(vals.copy(), flatM[c], method, carg, ends, maxgap, True)
        else:
            y, tf = _fill_vector(flatA[c].copy(), flatM[c], method, carg, ends, maxgap, not D.numeric)
        flatA[c] = y
        flatT[c] = tf
    F = np.moveaxis(flatA.reshape(A.shape), -1, dim).reshape(a.shape)
    TFo = np.moveaxis(flatT.reshape(A.shape), -1, dim).reshape(a.shape)
    res = D.back(F)
    return (res, out(TFo)) if nargout > 1 else res


@bi('rmmissing', nout=2)
def rmmissing(nargout, *args):
    """[R, TF] = rmmissing(A, dim, 'MinNumMissing', n): a vector without its
    missing entries; a matrix without the rows (dim 1) or columns (dim 2)
    that have n or more of them (1 unless given)."""
    nargchk(args, 1, 4, 'rmmissing')
    D = _Data(args[0], 'rmmissing')
    rest = list(args[1:])
    dim, minn = None, 1
    i = 0
    while i < len(rest):
        o = opt_str(rest[i])
        if o is None:
            dim = int(num(rest[i])) - 1
            i += 1
        elif o.lower() == 'minnummissing' and i + 1 < len(rest):
            minn = int(num(rest[i + 1]))
            i += 2
        else:
            raise err('MATLAB:rmmissing:InvalidOption', f"Unknown option '{o}'.", 'rmmissing')
    a, miss = D.a, D.miss
    if a.ndim > 2:
        raise err('MATLAB:rmmissing:NDArray', 'The input must be a vector or a matrix.', 'rmmissing')
    if dim is None and (a.shape[0] == 1 or a.shape[1] == 1):
        keep = ~miss.reshape(-1, order='F') if minn <= 1 else np.ones(miss.size, bool)
        flat = a.reshape(-1, order='F')[keep]
        r = flat.reshape((1, -1) if a.shape[0] == 1 else (-1, 1))
        res = D.back(r)
        return (res, out(miss.reshape(a.shape))) if nargout > 1 else res
    dim = 0 if dim is None else dim
    counts = miss.sum(axis=1 - dim)
    drop = counts >= minn
    r = a[~drop] if dim == 0 else a[:, ~drop]
    res = D.back(r)
    tf = drop.reshape(-1, 1) if dim == 0 else drop.reshape(1, -1)
    return (res, out(tf)) if nargout > 1 else res


@bi('standardizeMissing')
def standardize_missing(nargout, *args):
    """standardizeMissing(A, indicators): the entries equal to an indicator
    made the standard missing value (NaN, '' or a missing string)."""
    nargchk(args, 2, 2, 'standardizeMissing')
    D = _Data(args[0], 'standardizeMissing')
    ind = args[1]
    a = D.a.copy()
    if D.numeric:
        if a.dtype.kind not in 'fc':
            raise err('MATLAB:standardizeMissing:IntegerInput', 'Integers and logical values have no standard missing value.', 'standardizeMissing')
        vals = np.asarray(arr(ind)).reshape(-1) if not (is_str(ind) or type(ind) in (Cell, Str)) else np.zeros(0)
        a[np.isin(a, vals)] = np.nan
        return D.back(a)
    texts = set(text_list(ind)) if (is_str(ind) or type(ind) in (Cell, Str)) else set()
    if D.kind == 'Cell':
        for i in np.ndindex(a.shape):
            if a[i].str() in texts:
                a[i] = Char.of('')
    elif D.kind == 'Str':
        for i in np.ndindex(a.shape):
            if a[i] in texts:
                a[i] = None
    else:
        for t in texts:
            if len(t) == 1:
                a[a == ord(t)] = 32
    return D.back(a)


# ---- outliers -------------------------------------------------------------------------------------------------

def _quantile_sorted(v, p):
    """The language's quantile of sorted values: they sit at (i - 0.5)/n."""
    n = v.size
    t = min(max(p * n + 0.5, 1), n) - 1
    lo = int(math.floor(t))
    hi = min(lo + 1, n - 1)
    return v[lo] + (t - lo) * (v[hi] - v[lo])


def _grubbs(v, alpha):
    """Indices of outliers by Grubbs's test, removing the most extreme value
    while its statistic passes the critical value."""
    from scipy import stats
    idx = list(range(v.size))
    out_ = []
    while len(idx) > 2:
        w = v[idx]
        m, s = w.mean(), w.std(ddof=1)
        if s == 0:
            break
        j = int(np.argmax(np.abs(w - m)))
        g = abs(w[j] - m) / s
        n = len(idx)
        t = stats.t.ppf(1 - alpha / (2 * n), n - 2)
        crit = (n - 1) / math.sqrt(n) * math.sqrt(t * t / (n - 2 + t * t))
        if g <= crit:
            break
        out_.append(idx.pop(j))
    return out_


def _gesd(v, alpha, maxn):
    """Indices of outliers by the generalized extreme studentized deviate test."""
    from scipy import stats
    idx = list(range(v.size))
    n = v.size
    removed, last = [], 0
    for i in range(1, min(maxn, n - 2) + 1):
        w = v[idx]
        m, s = w.mean(), w.std(ddof=1)
        if s == 0:
            break
        j = int(np.argmax(np.abs(w - m)))
        r = abs(w[j] - m) / s
        p = 1 - alpha / (2 * (n - i + 1))
        t = stats.t.ppf(p, n - i - 1)
        lam = (n - i) * t / math.sqrt((n - i - 1 + t * t) * (n - i + 1))
        removed.append(idx.pop(j))
        if r > lam:
            last = i
    return removed[:last]


_OUT_METHODS = ('median', 'mean', 'quartiles', 'grubbs', 'gesd', 'movmedian', 'movmean')


def _outliers(args, fn, first_method=1):
    """The outlier test shared by isoutlier and filloutliers: (TF, L, U, C,
    the data, the dimension), the bounds along the dimension."""
    x0 = args[0]
    x = np.asarray(arr(x0, fn))
    if x.dtype.kind == 'c':
        raise err(f'MATLAB:{fn}:ComplexInput', 'The data must be real.', fn)
    x = x.astype(F64)
    rest = list(args[first_method:])
    method, window = 'median', None
    if rest and (opt_str(rest[0]) or '').lower() in _OUT_METHODS:
        method = opt_lower(rest.pop(0))
        if method in ('movmedian', 'movmean'):
            if not rest:
                raise err(f'MATLAB:{fn}:WindowMissing', f"'{method}' needs a window.", fn)
            window = _window(rest.pop(0), fn)
    thresh, dim, maxn = None, None, None
    i = 0
    while i < len(rest):
        o = opt_str(rest[i])
        if o is None:
            dim = int(num(rest[i])) - 1
            i += 1
            continue
        key = o.lower()
        if i + 1 >= len(rest):
            raise err(f'MATLAB:{fn}:NameValue', f"'{o}' needs a value.", fn)
        if key == 'thresholdfactor':
            thresh = float(num(rest[i + 1]))
        elif key == 'maxnumoutliers':
            maxn = int(num(rest[i + 1]))
        elif key in ('samplepoints', 'datavariables'):
            raise err(f'MATLAB:{fn}:Unsupported', f"'{o}' is not supported here.", fn)
        else:
            raise err(f'MATLAB:{fn}:InvalidOption', f"Unknown option '{o}'.", fn)
        i += 2
    if dim is None:
        dim = first_dim(x.shape)
    X = np.moveaxis(expand_dims(x, dim), dim, -1)
    shp = X.shape
    V = X.reshape(-1, shp[-1])
    n = shp[-1]
    TF = np.zeros(V.shape, bool)
    moving = method in ('movmedian', 'movmean')
    L = np.full(V.shape if moving else (V.shape[0], 1), np.nan)
    U, C = L.copy(), L.copy()
    t = thresh if thresh is not None else (1.5 if method == 'quartiles' else (0.05 if method in ('grubbs', 'gesd') else 3.0))
    with warnings.catch_warnings(), np.errstate(all='ignore'):
        warnings.simplefilter('ignore', RuntimeWarning)
        for r in range(V.shape[0]):
            v = V[r]
            ok = ~np.isnan(v)
            w = v[ok]
            if moving:
                kb, kf = window
                for j in range(n):
                    seg = v[max(0, j - kb):min(n, j + kf + 1)]
                    seg = seg[~np.isnan(seg)]
                    if not seg.size:
                        continue
                    if method == 'movmedian':
                        c = np.median(seg)
                        s = _MAD_SCALE * np.median(np.abs(seg - c))
                    else:
                        c = seg.mean()
                        s = seg.std(ddof=1) if seg.size > 1 else 0.0
                    C[r, j], L[r, j], U[r, j] = c, c - t * s, c + t * s
                TF[r] = (v < L[r]) | (v > U[r])
                continue
            if not w.size:
                continue
            if method == 'median':
                c = np.median(w)
                s = _MAD_SCALE * np.median(np.abs(w - c))
                lo, hi = c - t * s, c + t * s
            elif method == 'mean':
                c = w.mean()
                s = w.std(ddof=1) if w.size > 1 else 0.0
                lo, hi = c - t * s, c + t * s
            elif method == 'quartiles':
                ws = np.sort(w)
                q1, q3 = _quantile_sorted(ws, 0.25), _quantile_sorted(ws, 0.75)
                c = _quantile_sorted(ws, 0.5)
                lo, hi = q1 - t * (q3 - q1), q3 + t * (q3 - q1)
            else:
                pos = np.flatnonzero(ok)
                found = _grubbs(w, t) if method == 'grubbs' else _gesd(w, t, maxn if maxn is not None else max(1, math.ceil(0.1 * w.size)))
                c = w.mean()
                keep = np.setdiff1d(np.arange(w.size), found)
                lo = w[keep].min() if keep.size else np.nan
                hi = w[keep].max() if keep.size else np.nan
                TF[r, pos[found]] = True
                L[r, 0], U[r, 0], C[r, 0] = lo, hi, c
                continue
            L[r, 0], U[r, 0], C[r, 0] = lo, hi, c
            TF[r] = (v < lo) | (v > hi)

    def shape_back(M, full):
        sh = shp if full else shp[:-1] + (1,)
        return np.moveaxis(M.reshape(sh), -1, dim)
    return (shape_back(TF, True).reshape(x.shape), shape_back(L, moving), shape_back(U, moving), shape_back(C, moving), x, dim, method)


@bi('isoutlier', nout=4)
def isoutlier(nargout, *args):
    """[TF, L, U, C] = isoutlier(A, method, ...): outliers along a dimension:
    'median' (more than 3 scaled MADs from the median, the default), 'mean'
    (3 standard deviations), 'quartiles' (1.5 interquartile ranges past the
    quartiles), 'grubbs', 'gesd', or 'movmedian' and 'movmean' over a
    window; 'ThresholdFactor' changes the 3 (or 1.5, or the alpha 0.05)."""
    nargchk(args, 1, 8, 'isoutlier')
    TF, L, U, C, x, dim, method = _outliers(args, 'isoutlier')
    res = out(TF)
    if nargout <= 1:
        return res
    back = (lambda m: like_class(m, args[0])) if class_of(args[0]) == 'single' else out
    return (res, back(L), back(U), back(C))[:nargout]


@bi('filloutliers', nout=5)
def filloutliers(nargout, *args):
    """[B, TF, L, U, C] = filloutliers(A, fill, method, ...): the outliers
    isoutlier finds (by method, 'median' unless given) replaced: by 'center',
    'clip' (to the bounds), 'previous', 'next', 'nearest', 'linear',
    'spline', 'pchip', 'makima' or a number; NaN stays NaN."""
    nargchk(args, 2, 9, 'filloutliers')
    f = args[1]
    fill = opt_lower(f) if opt_str(f) is not None else float(num(f))
    if isinstance(fill, str) and fill not in ('center', 'clip', 'previous', 'next', 'nearest', 'linear', 'spline', 'pchip', 'makima'):
        raise err('MATLAB:filloutliers:InvalidFill', "The fill is 'center', 'clip', 'previous', 'next', 'nearest', 'linear', 'spline', 'pchip', 'makima' or a number.", 'filloutliers')
    TF, L, U, C, x, dim, method = _outliers((args[0],) + tuple(args[2:]), 'filloutliers')
    B = x.copy()
    Lb, Ub, Cb = (np.broadcast_to(M, x.shape) for M in (L, U, C))
    if not isinstance(fill, str):
        B[TF] = fill
    elif fill == 'center':
        B[TF] = Cb[TF]
    elif fill == 'clip':
        B = np.where(TF & (x < Lb), Lb, np.where(TF & (x > Ub), Ub, B))
    else:
        X = np.moveaxis(expand_dims(B, dim), dim, -1)
        T = np.moveaxis(expand_dims(TF, dim), dim, -1)
        shp = X.shape
        XV, TV = X.reshape(-1, shp[-1]).copy(), T.reshape(-1, shp[-1])
        for r in range(XV.shape[0]):
            # NaN in the data is neither filled nor used: only the outliers are gaps
            y = XV[r]
            known = ~TV[r] & ~np.isnan(y)
            gaps = TV[r]
            z = np.where(known, y, np.nan)
            filled, _ = _fill_vector(z, ~known, fill, None, 'extrap' if fill in ('linear', 'spline', 'pchip', 'makima') else None, None, False)
            XV[r] = np.where(gaps, filled, y)
        B = np.moveaxis(XV.reshape(shp), -1, dim).reshape(x.shape)
    res = like_class(B, args[0]) if class_of(args[0]) == 'single' else out(B)
    if nargout <= 1:
        return res
    return (res, out(TF), out(L), out(U), out(C))[:nargout]


# ---- smoothing ----------------------------------------------------------------------------------------------

_SMOOTH = ('movmean', 'movmedian', 'gaussian', 'lowess', 'loess', 'rlowess', 'rloess', 'sgolay')


def _local_fit(t, y, deg, robust):
    """lowess/loess at each point: a weighted least-squares line (deg 1) or
    parabola (deg 2) over its window, tricube weights by distance; robust
    adds bisquare weights from the residuals, five times."""
    n = y.size
    k = t.size
    res = np.empty(n)
    rw = np.ones(n)
    for it in range(6 if robust else 1):
        for i in range(n):
            lo = max(0, min(i - k // 2, n - k))
            idx = np.arange(lo, min(n, lo + k))
            d = np.abs(idx - i)
            dmax = max(d.max(), 1) + 1
            w = (1 - (d / dmax) ** 3) ** 3 * rw[idx]
            X = np.vander(idx - i, deg + 1, increasing=True).astype(F64)
            W = np.sqrt(w)
            beta = np.linalg.lstsq(X * W[:, None], y[idx] * W, rcond=None)[0]
            res[i] = beta[0]
        if robust and it < 5:
            r = y - res
            s = np.median(np.abs(r))
            if s == 0:
                break
            u = r / (6 * s)
            rw = np.where(np.abs(u) < 1, (1 - u * u) ** 2, 0.0)
    return res


@bi('smoothdata', nout=2)
def smoothdata(nargout, *args):
    """[B, window] = smoothdata(A, method, window, ...): a moving mean (the
    default), median, Gaussian-weighted mean (standard deviation window/5),
    lowess or loess (local lines or parabolas with tricube weights; the r
    forms robust), or Savitzky-Golay ('Degree', 2 unless given) along a
    dimension, NaN left out unless 'includenan'. Without a window, 4 points
    or about a tenth of the length, whichever is larger."""
    nargchk(args, 1, 9, 'smoothdata')
    x0 = args[0]
    x = np.asarray(arr(x0, 'smoothdata')).astype(F64)
    rest = list(args[1:])
    dim = None
    if rest and opt_str(rest[0]) is None:
        dim = int(num(rest.pop(0))) - 1
    method = 'movmean'
    if rest and (opt_str(rest[0]) or '').lower() in _SMOOTH:
        method = opt_lower(rest.pop(0))
    window = None
    if rest and opt_str(rest[0]) is None:
        window = darr(rest.pop(0)).reshape(-1)
    omit, degree = True, 2
    i = 0
    while i < len(rest):
        o = (opt_str(rest[i]) or '').lower()
        if o in ('omitnan', 'omitmissing'):
            omit = True
            i += 1
        elif o in ('includenan', 'includemissing'):
            omit = False
            i += 1
        elif o == 'degree' and i + 1 < len(rest):
            degree = int(num(rest[i + 1]))
            i += 2
        elif o == 'smoothingfactor' and i + 1 < len(rest):
            raise err('MATLAB:smoothdata:Unsupported', "'SmoothingFactor' is not supported here: give a window.", 'smoothdata')
        else:
            raise err('MATLAB:smoothdata:InvalidOption', f"Unknown option '{opt_str(rest[i])}'.", 'smoothdata')
    if dim is None:
        dim = first_dim(x.shape)
    X = np.moveaxis(expand_dims(x, dim), dim, -1)
    n = X.shape[-1]
    if window is None:
        w = max(4, int(round(n / 10)))
        window = np.array([float(w)])
    if window.size == 1:
        w = int(window[0])
        kb, kf = w // 2, w - w // 2 - 1
    else:
        kb, kf = int(window[0]), int(window[1])
        w = kb + kf + 1
    V = X.reshape(-1, n).copy()
    with warnings.catch_warnings(), np.errstate(all='ignore'):
        warnings.simplefilter('ignore', RuntimeWarning)
        for r in range(V.shape[0]):
            y = V[r].copy()
            nan = np.isnan(y)
            if method in ('movmean', 'movmedian', 'gaussian'):
                res = np.empty(n)
                for j in range(n):
                    lo, hi = max(0, j - kb), min(n, j + kf + 1)
                    seg = y[lo:hi]
                    if method == 'gaussian':
                        sd = max(w / 5, 1e-12)
                        wt = np.exp(-0.5 * ((np.arange(lo, hi) - j) / sd) ** 2)
                        m = ~np.isnan(seg) if omit else np.ones(seg.size, bool)
                        res[j] = np.sum(wt[m] * seg[m]) / np.sum(wt[m]) if m.any() else np.nan
                    elif method == 'movmean':
                        res[j] = (np.nanmean if omit else np.mean)(seg)
                    else:
                        res[j] = (np.nanmedian if omit else np.median)(seg)
            elif method == 'sgolay':
                from scipy.signal import savgol_filter
                yy = y.copy()
                if omit and nan.any() and (~nan).sum() > 1:
                    yy[nan] = np.interp(np.flatnonzero(nan), np.flatnonzero(~nan), y[~nan])
                wl = min(w if w % 2 else w + 1, n if n % 2 else n - 1)
                res = savgol_filter(yy, wl, min(degree, wl - 1), mode='interp') if wl > degree else yy
                if not omit:
                    res = np.where(nan, np.nan, res)
            else:
                deg = 1 if method in ('lowess', 'rlowess') else 2
                good = ~nan
                res = np.full(n, np.nan)
                if good.sum() > deg:
                    t = np.arange(min(w, int(good.sum())))
                    res_good = _local_fit(t, y[good], deg, method.startswith('r'))
                    res[good] = res_good
                    if omit and nan.any():
                        res[nan] = np.interp(np.flatnonzero(nan), np.flatnonzero(good), res_good)
            V[r] = res
    B = np.moveaxis(V.reshape(X.shape), -1, dim).reshape(x.shape)
    res = like_class(B, x0) if class_of(x0) == 'single' else out(B)
    if nargout > 1:
        return res, out(window.reshape(1, -1).astype(F64))
    return res


# ---- groups -------------------------------------------------------------------------------------------------

def _group_keys(v, fn):
    """Each element's key and whether it is missing, for a grouping variable."""
    t = type(v)
    if t is Cell:
        items = [x.str() if type(x) is Char else None for x in v.a.reshape(-1, order='F')]
        if any(s is None for s in items):
            raise err(f'MATLAB:{fn}:InvalidGroup', 'A cell grouping variable must hold character vectors.', fn)
        return items, [s == '' for s in items], 'cell'
    if t is Str:
        items = list(v.a.reshape(-1, order='F'))
        return items, [s is None for s in items], 'string'
    if t is Char:
        rows = v.row_strs() if v.a.shape[0] > 1 else [v.str()]
        if v.a.shape[0] == 1 and v.a.shape[1] > 1:
            rows = list(v.str())
        return rows, [r.strip() == '' for r in rows], 'char'
    a = np.asarray(arr(v)).reshape(-1, order='F')
    miss = np.isnan(a) if a.dtype.kind in 'fc' else np.zeros(a.size, bool)
    return list(a), list(miss), 'num'


@bi('findgroups', nout=99)
def findgroups(nargout, *args):
    """[G, ID1, ID2, ...] = findgroups(A1, A2, ...): the group number of each
    element, the groups being the distinct values (or combinations) in
    sorted order; a missing value gets NaN and no group."""
    nargchk(args, 1, None, 'findgroups')
    cols = [_group_keys(v, 'findgroups') for v in args]
    n = len(cols[0][0])
    if any(len(c[0]) != n for c in cols):
        raise err('MATLAB:findgroups:InputSizeMismatch', 'The grouping variables must have the same number of elements.', 'findgroups')
    miss = np.zeros(n, bool)
    for c in cols:
        miss |= np.array(c[1], bool)
    keys = [tuple(c[0][i] for c in cols) for i in range(n)]
    uniq = sorted({k for k, m in zip(keys, miss) if not m})
    num_of = {k: i + 1 for i, k in enumerate(uniq)}
    G = np.array([np.nan if m else num_of[k] for k, m in zip(keys, miss)], F64)
    sh = shape_of(args[0])
    G = G.reshape((1, -1) if (len(sh) == 2 and sh[0] == 1 and sh[1] != 1) else (-1, 1))
    res = [out(G)]
    for j, (items, _, kind) in enumerate(cols):
        vals = [k[j] for k in uniq]
        row = res[0].shape[0] == 1 if isinstance(res[0], np.ndarray) else False
        shape = (1, len(vals)) if row else (len(vals), 1)
        if kind == 'cell' or kind == 'char':
            res.append(Cell.of_list([Char.of(s) for s in vals], shape))
        elif kind == 'string':
            res.append(Str.from_list(vals, shape))
        else:
            a = np.array(vals, F64 if not vals else np.asarray(arr(args[j])).dtype).reshape(shape)
            res.append(like_class(a, args[j]) if class_of(args[j]) not in ('double',) else out(a.astype(F64)))
    return res[0] if nargout <= 1 else tuple(res[:max(nargout, 1)])


def _rows_of(v, sel):
    """The rows (elements of a vector) of a value picked by a logical mask."""
    sh = shape_of(v)
    vec = len(sh) == 2 and (sh[0] == 1 or sh[1] == 1)
    t = type(v)
    if t is Cell or t is Str or t is Char:
        a = v.a
        part = a.reshape(-1, order='F')[sel].reshape((1, -1) if sh[0] == 1 else (-1, 1)) if vec else a[sel]
        return t(part) if t is not Cell else Cell(part)
    if t is Struct:
        raise err('MATLAB:splitapply:Struct', 'splitapply does not split struct arrays here.', 'splitapply')
    a = np.asarray(arr(v))
    part = a.reshape(-1, order='F')[sel].reshape((1, -1) if sh[0] == 1 else (-1, 1)) if vec else a[sel]
    return like_class(part, v) if class_of(v) not in ('double', 'logical') else (out(part) if part.dtype != bool else out(part))


@bi('splitapply', aw=True, nout=99)
async def splitapply(nargout, *args):
    """Y = splitapply(func, X1, ..., G): func applied to the rows of the X's
    in each group 1..max(G) in turn, its results stacked; rows whose group
    is NaN are left out."""
    nargchk(args, 3, None, 'splitapply')
    f = args[0]
    from ..values import FH
    if not isinstance(f, FH):
        raise err('MATLAB:splitapply:InvalidFunction', 'The first input must be a function handle.', 'splitapply')
    data, G = list(args[1:-1]), np.asarray(arr(args[-1])).reshape(-1).astype(F64)
    good = G[~np.isnan(G)]
    if np.any(good < 1) or np.any(good != np.round(good)):
        raise err('MATLAB:splitapply:InvalidGroupNums', 'Group numbers must be positive integers or NaN.', 'splitapply')
    ng = int(good.max()) if good.size else 0
    for d in data:
        sh = shape_of(d)
        rows = numel(d) if (len(sh) == 2 and (sh[0] == 1 or sh[1] == 1)) else sh[0]
        if rows != G.size:
            raise err('MATLAB:splitapply:InputSizeMismatch', 'Each data input must have one row (or element) per group number.', 'splitapply')
    nout = max(nargout, 1)
    outs = [[] for _ in range(nout)]
    for k in range(1, ng + 1):
        sel = G == k
        if not sel.any():
            raise err('MATLAB:splitapply:MissingGroupNums', f'Group {k} has no members: group numbers must run from 1 to the largest without gaps.', 'splitapply')
        r = await f.acall(nout, *[_rows_of(d, sel) for d in data])
        rs = r if isinstance(r, tuple) else (r,)
        for j in range(nout):
            v = rs[j]
            if shape_of(v)[0] != 1 and numel(v) != 1:
                raise err('MATLAB:splitapply:OutputNotScalar', f'The function returned a non-scalar value for group {k}. To keep a value that is not a scalar, return it in a cell: @(x){{func(x)}}.', 'splitapply')
            outs[j].append(v)
    res = tuple(_cat(0, o) if o else np.zeros((0, 1)) for o in outs)
    return res[0] if nargout <= 1 else res


# ---- histcounts2 ------------------------------------------------------------------------------------------

@bi('histcounts2', nout=5)
def histcounts2(nargout, *args):
    """[N, Xedges, Yedges, binX, binY] = histcounts2(X, Y, nbins or Xedges,
    Yedges, ...): counts of the (x, y) pairs in a grid of bins, chosen as
    histcounts chooses them for each coordinate unless given ('NumBins',
    'BinWidth', 'XBinLimits', 'YBinLimits', 'XBinEdges', 'YBinEdges',
    'Normalization'); a pair with NaN, or outside, is in no bin."""
    from .datafun import nice_edges
    nargchk(args, 2, None, 'histcounts2')
    x = darr(args[0]).reshape(-1, order='F').real
    y = darr(args[1]).reshape(-1, order='F').real
    if x.size != y.size:
        raise err('MATLAB:histcounts2:XYSizeMismatch', 'X and Y must have the same number of elements.', 'histcounts2')
    rest = list(args[2:])
    nb = [None, None]
    edges = [None, None]
    width = [None, None]
    lims = [None, None]
    norm = 'count'
    if rest and opt_str(rest[0]) is None:
        a = darr(rest.pop(0)).reshape(-1)
        if rest and opt_str(rest[0]) is None:
            edges = [a, darr(rest.pop(0)).reshape(-1)]
        elif a.size <= 2:
            nb = [int(a[0]), int(a[-1])]
        else:
            raise err('MATLAB:histcounts2:InvalidBins', 'Give the number of bins, [nx ny], or both edge vectors.', 'histcounts2')
    i = 0
    while i + 1 < len(rest):
        key = (opt_str(rest[i]) or '').lower()
        val = rest[i + 1]
        v = darr(val).reshape(-1) if opt_str(val) is None else None
        if key == 'numbins':
            nb = [int(v[0]), int(v[-1])]
        elif key == 'binwidth':
            width = [float(v[0]), float(v[-1])]
        elif key == 'xbinlimits':
            lims[0] = (float(v[0]), float(v[1]))
        elif key == 'ybinlimits':
            lims[1] = (float(v[0]), float(v[1]))
        elif key == 'xbinedges':
            edges[0] = v
        elif key == 'ybinedges':
            edges[1] = v
        elif key == 'normalization':
            norm = opt_lower(val)
        else:
            raise err('MATLAB:histcounts2:InvalidOption', f"Unknown option '{opt_str(rest[i])}'.", 'histcounts2')
        i += 2
    ok = np.isfinite(x) & np.isfinite(y)
    for k, (c, l) in enumerate(((x, lims[0]), (y, lims[1]))):
        if edges[k] is None:
            cc = c[ok]
            if l is not None:
                cc = cc[(cc >= l[0]) & (cc <= l[1])]
            edges[k] = nice_edges(cc, nb[k], width[k], l)

    def bins(c, e):
        idx = np.searchsorted(e, c, side='right') - 1
        idx = np.where(c == e[-1], len(e) - 2, idx)
        good = (idx >= 0) & (idx < len(e) - 1) & np.isfinite(c)
        return idx, good
    ix, gx = bins(x, edges[0])
    iy, gy = bins(y, edges[1])
    g = gx & gy & ok
    N = np.zeros((len(edges[0]) - 1, len(edges[1]) - 1))
    np.add.at(N, (ix[g], iy[g]), 1)
    area = np.outer(np.diff(edges[0]), np.diff(edges[1]))
    total = max(int(ok.sum()), 1)
    if norm == 'probability':
        N = N / total
    elif norm == 'pdf':
        N = N / total / area
    elif norm == 'countdensity':
        N = N / area
    elif norm == 'cumcount':
        N = np.cumsum(np.cumsum(N, 0), 1)
    elif norm == 'cdf':
        N = np.cumsum(np.cumsum(N, 0), 1) / total
    elif norm != 'count':
        raise err('MATLAB:histcounts2:InvalidNormalization', f"Unknown normalization '{norm}'.", 'histcounts2')
    shp = shape_of(args[0])
    bx = np.where(g, ix + 1, 0).astype(F64).reshape(shp, order='F')
    by = np.where(g, iy + 1, 0).astype(F64).reshape(shp, order='F')
    res = (out(N), out(edges[0].reshape(1, -1)), out(edges[1].reshape(1, -1)), out(bx), out(by))
    return res[0] if nargout <= 1 else res[:nargout]
