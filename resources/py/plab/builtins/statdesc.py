"""Descriptive statistics: trimmean, geomean, harmmean, mad, moment, zscore,
the nan- functions, tabulate, grpstats, ecdf, ksdensity, corr, bootstrp and
jackknife; and the grouping variables the statistics functions share
(numbers, text in a char matrix, a cell or a string array)."""
import math

import numpy as np

from . import bi
from ._util import err, nargchk, darr, out, opt_str, sval, num, is_str, cellstr_list
from ..values import MError, Char, Cell, Struct, Str, FH, EMPTY, py_str
from .. import runtime as R
from .datafun import first_dim


# ---- groups ----------------------------------------------------------------------------------------

def groups(g, n, fn):
    """A grouping variable as (labels, index): index[i] is the group of
    observation i (0-based; -1 where it is missing). Numbers are ordered by
    value, text by first appearance; NaN and empty text are missing. A cell
    of grouping variables groups by all of them together."""
    t = type(g)
    if t is Cell and g.a.size and all(type(v) in (Cell, np.ndarray, float, Str) or (type(v) is Char and v.a.shape[0] > 1)
                                      for v in g.a.reshape(-1)) and not all(type(v) is Char for v in g.a.reshape(-1)):
        parts = [groups(v, n, fn) for v in g.a.reshape(-1, order='F')]
        keys = list(zip(*[p[1] for p in parts]))
        labels, idx, seen = [], np.full(n, -1), {}
        for i, key in enumerate(keys):
            if any(k < 0 for k in key):
                continue
            if key not in seen:
                seen[key] = len(labels)
                labels.append(','.join(parts[j][0][k] for j, k in enumerate(key)))
            idx[i] = seen[key]
        return labels, idx
    if t is Char:
        vals = g.row_strs() if g.a.shape[0] > 1 or n == 1 else [g.str()] * n
        vals = [v.rstrip() for v in vals]
    elif t in (Cell, Str):
        vals = [s if s is not None else '' for s in cellstr_list(g)] if t is Cell else [s if s is not None else '' for s in g.a.reshape(-1, order='F')]
    else:
        a = darr(g).real.reshape(-1)
        if a.size != n:
            raise err('stats:grp2idx:InputSizeMismatch', 'The grouping variable must have one value for each observation.', fn)
        u = np.unique(a[~np.isnan(a)])
        pos = {float(v): i for i, v in enumerate(u)}
        idx = np.array([pos.get(float(v), -1) if not np.isnan(v) else -1 for v in a])
        return [f'{v:g}' for v in u], idx
    if len(vals) != n:
        raise err('stats:grp2idx:InputSizeMismatch', 'The grouping variable must have one value for each observation.', fn)
    labels, idx, seen = [], np.full(n, -1), {}
    for i, v in enumerate(vals):
        if v == '':
            continue
        if v not in seen:
            seen[v] = len(labels)
            labels.append(v)
        idx[i] = seen[v]
    return labels, idx


@bi('grp2idx', nout=3)
def grp2idx(nargout, *args):
    nargchk(args, 1, 1, 'grp2idx')
    g = args[0]
    n = _count(g)
    labels, idx = groups(g, n, 'grp2idx')
    gi = out(np.where(idx >= 0, idx + 1.0, np.nan).reshape(-1, 1))
    gn = Cell.of_list([Char.of(s) for s in labels], (len(labels), 1))
    return (gi, gn, gn)[:nargout] if nargout > 1 else gi


def _count(g):
    t = type(g)
    if t is Char:
        return g.a.shape[0]
    if t in (Cell, Str):
        return g.a.size
    return darr(g).size


# ---- along a dimension, missing values left out ------------------------------------------------------

def _along(x, dim, fn, keepnan=False):
    """Apply fn to each vector of x along dim (0-based), NaN left out unless keepnan."""
    x = np.moveaxis(x, dim, -1)
    res = np.empty(x.shape[:-1])
    for i in np.ndindex(x.shape[:-1]):
        v = x[i]
        if not keepnan:
            v = v[~np.isnan(v)]
        res[i] = fn(v) if v.size else np.nan
    return np.expand_dims(res, -1).swapaxes(-1, dim) if res.ndim else np.array(res).reshape(1, 1)


def _dim(args, i, x):
    if len(args) > i and np.size(darr(args[i])):
        return int(num(args[i])) - 1
    return first_dim(x.shape)


def _arr(v):
    return darr(v).real.astype(float)


def _result(r, x, dim):
    r = np.asarray(r, float)
    if r.ndim < 2:
        r = r.reshape(1, -1) if dim == 1 else r.reshape(-1, 1) if r.ndim == 1 else r.reshape(1, 1)
    return out(r)


@bi('trimmean')
def trimmean(nargout, *args):
    nargchk(args, 2, 4, 'trimmean')
    x = _arr(args[0])
    pct = float(num(args[1]))
    if not 0 <= pct <= 100:
        raise err('stats:trimmean:InvalidPercent', 'PERCENT must be between 0 and 100.', 'trimmean')
    rest = list(args[2:])
    flag = 'round'
    if rest and is_str(rest[0]):
        flag = sval(rest.pop(0)).lower()
    dim = _dim(rest, 0, x)

    def tm(v):
        v = np.sort(v)
        n = v.size
        k0 = n * pct / 200
        if flag == 'weighted':
            k = int(math.floor(k0))
            f = 1 - (k0 - k)
            w = np.ones(n)
            if 2 * k < n:
                w[:k] = 0
                w[n - k:] = 0
                if k < n - k - 1 and f < 1:
                    w[k] = w[n - k - 1] = f
                return float(np.sum(w * v) / np.sum(w))
            return float(np.median(v))
        k = int(math.floor(k0 + 0.5)) if flag == 'round' else int(math.floor(k0))
        if 2 * k >= n:
            return float(np.median(v))
        return float(np.mean(v[k:n - k]))
    return out(_along(x, dim, tm))


@bi('geomean')
def geomean(nargout, *args):
    nargchk(args, 1, 2, 'geomean')
    x = _arr(args[0])
    if np.any(x < 0):
        raise err('stats:geomean:BadData', 'The data must not be negative.', 'geomean')
    dim = _dim(args, 1, x)
    with np.errstate(divide='ignore'):
        return out(np.exp(np.mean(np.log(x), axis=dim, keepdims=True)))


@bi('harmmean')
def harmmean(nargout, *args):
    nargchk(args, 1, 2, 'harmmean')
    x = _arr(args[0])
    dim = _dim(args, 1, x)
    with np.errstate(divide='ignore'):
        return out(x.shape[dim] / np.sum(1 / x, axis=dim, keepdims=True))


@bi('mad')
def mad(nargout, *args):
    nargchk(args, 1, 3, 'mad')
    x = _arr(args[0])
    flag = int(num(args[1])) if len(args) > 1 and np.size(darr(args[1])) else 0
    dim = _dim(args, 2, x)
    if flag:
        return out(_along(x, dim, lambda v: float(np.median(np.abs(v - np.median(v))))))
    return out(_along(x, dim, lambda v: float(np.mean(np.abs(v - np.mean(v))))))


@bi('moment')
def moment(nargout, *args):
    nargchk(args, 2, 3, 'moment')
    x = _arr(args[0])
    k = int(num(args[1]))
    if k < 1:
        raise err('stats:moment:BadOrder', 'ORDER must be a positive whole number.', 'moment')
    dim = _dim(args, 2, x)
    m = np.mean(x, axis=dim, keepdims=True)
    return out(np.mean((x - m) ** k, axis=dim, keepdims=True))


@bi('zscore', nout=3)
def zscore(nargout, *args):
    nargchk(args, 1, 3, 'zscore')
    x = _arr(args[0])
    flag = int(num(args[1])) if len(args) > 1 and np.size(darr(args[1])) else 0
    dim = _dim(args, 2, x)
    if x.size == 0:
        return (EMPTY(), EMPTY(), EMPTY())[:max(nargout, 1)] if nargout > 1 else EMPTY()
    mu = np.mean(x, axis=dim, keepdims=True)
    s = np.std(x, axis=dim, ddof=0 if flag else (1 if x.shape[dim] > 1 else 0), keepdims=True)
    s0 = np.where(s == 0, 1.0, s)
    z = out((x - mu) / s0)
    return (z, out(mu), out(s))[:nargout] if nargout > 1 else z


def _nanfn(name, fn_vec):
    @bi(name)
    def f(nargout, *args):
        nargchk(args, 1, 3, name)
        x = _arr(args[0])
        flag_used = name in ('nanstd', 'nanvar')
        flag = int(num(args[1])) if flag_used and len(args) > 1 and np.size(darr(args[1])) else 0
        dim = _dim(args, 2 if flag_used else 1, x)
        return out(_along(x, dim, lambda v: fn_vec(v, flag)))
    return f


_nanfn('nanmean', lambda v, f: float(np.mean(v)))
_nanfn('nanmedian', lambda v, f: float(np.median(v)))
_nanfn('nanstd', lambda v, f: float(np.std(v, ddof=0 if f or v.size < 2 else 1)))
_nanfn('nanvar', lambda v, f: float(np.var(v, ddof=0 if f or v.size < 2 else 1)))


@bi('nansum')
def nansum(nargout, *args):
    nargchk(args, 1, 2, 'nansum')
    x = _arr(args[0])
    dim = _dim(args, 1, x)
    return out(np.nansum(x, axis=dim, keepdims=True))


@bi('nanmax', nout=2)
def nanmax(nargout, *args):
    return R.BUILTINS['max'].fn(nargout, *args)


@bi('nanmin', nout=2)
def nanmin(nargout, *args):
    return R.BUILTINS['min'].fn(nargout, *args)


# ---- tables of counts and statistics by group ------------------------------------------------------

@bi('tabulate')
def tabulate(nargout, *args):
    nargchk(args, 1, 1, 'tabulate')
    x = args[0]
    if type(x) in (Char, Cell, Str):
        labels, idx = groups(x, _count(x), 'tabulate')
        counts = np.bincount(idx[idx >= 0], minlength=len(labels)).astype(float)
        total = counts.sum()
        rows = [(lab, c, 100 * c / total if total else 0.0) for lab, c in zip(labels, counts)]
        if nargout:
            a = np.empty((len(rows), 3), object)
            for i, (lab, c, p) in enumerate(rows):
                a[i, 0], a[i, 1], a[i, 2] = Char.of(lab), float(c), float(p)
            return Cell(a)
        w = max([5] + [len(r[0]) for r in rows])
        lines = [f'  {"Value":>{w}}    Count   Percent'] + [f'  {lab:>{w}}    {int(c):5d}    {p:6.2f}%' for lab, c, p in rows]
        R.write('\n'.join(lines) + '\n')
        return None
    a = _arr(x).reshape(-1)
    a = a[~np.isnan(a)]
    if a.size and np.all(a == np.floor(a)) and np.min(a) >= 1:
        vals = np.arange(1, int(np.max(a)) + 1, dtype=float)       # whole numbers from 1: all of them, with the empty ones
    else:
        vals = np.unique(a)
    counts = np.array([np.sum(a == v) for v in vals], float)
    pct = 100 * counts / a.size if a.size else counts
    if nargout:
        return out(np.column_stack([vals, counts, pct]))
    lines = ['  Value    Count   Percent'] + [f'  {v:5g}    {int(c):5d}    {p:6.2f}%' for v, c, p in zip(vals, counts, pct)]
    R.write('\n'.join(lines) + '\n')
    return None


_GRPSTATS = ('mean', 'sem', 'numel', 'gname', 'std', 'var', 'min', 'max', 'range', 'median', 'meanci', 'predci')


@bi('grpstats', nout=20)
def grpstats(nargout, *args):
    nargchk(args, 1, 5, 'grpstats')
    from scipy import stats as st
    X = _arr(args[0])
    if X.ndim == 2 and X.shape[0] == 1:
        X = X.reshape(-1, 1)
    n = X.shape[0]
    g = args[1] if len(args) > 1 and not (type(args[1]) is np.ndarray and args[1].size == 0) else None
    which = ['mean']
    alpha = 0.05
    rest = list(args[2:])
    if rest and not (is_str(rest[0]) and sval(rest[0]).lower() == 'alpha'):
        w = rest.pop(0)
        which = [w.str()] if type(w) is Char else cellstr_list(w)
    if len(rest) >= 2 and is_str(rest[0]) and sval(rest[0]).lower() == 'alpha':
        alpha = float(num(rest[1]))
    if g is None:
        labels, idx = ['1'], np.zeros(n, int)
    else:
        labels, idx = groups(g, n, 'grpstats')
    G = len(labels)
    outs = []
    for name in which:
        nm = name.lower()
        if nm not in _GRPSTATS:
            raise err('stats:grpstats:BadStats', f"Unknown statistic '{name}': use {', '.join(_GRPSTATS)}.", 'grpstats')
        if nm == 'gname':
            outs.append(Cell.of_list([Char.of(s) for s in labels], (G, 1)))
            continue
        cols = []
        for j in range(X.shape[1]):
            per = []
            for gi in range(G):
                v = X[idx == gi, j]
                v = v[~np.isnan(v)]
                m = v.size
                mean = float(np.mean(v)) if m else math.nan
                sd = float(np.std(v, ddof=1)) if m > 1 else (0.0 if m == 1 else math.nan)
                if nm == 'mean':
                    per.append(mean)
                elif nm == 'sem':
                    per.append(sd / math.sqrt(m) if m else math.nan)
                elif nm == 'numel':
                    per.append(float(m))
                elif nm == 'std':
                    per.append(sd)
                elif nm == 'var':
                    per.append(sd * sd)
                elif nm == 'min':
                    per.append(float(np.min(v)) if m else math.nan)
                elif nm == 'max':
                    per.append(float(np.max(v)) if m else math.nan)
                elif nm == 'range':
                    per.append(float(np.ptp(v)) if m else math.nan)
                elif nm == 'median':
                    per.append(float(np.median(v)) if m else math.nan)
                else:
                    t = st.t.ppf(1 - alpha / 2, m - 1) if m > 1 else math.nan
                    half = t * sd / math.sqrt(m) if nm == 'meanci' else t * sd * math.sqrt(1 + 1 / m)
                    per.append((mean - half, mean + half))
            cols.append(per)
        if nm in ('meanci', 'predci'):
            a = np.array([[c[gi] for c in cols] for gi in range(G)])        # G x ncols x 2
            a = np.transpose(a, (0, 2, 1))                                   # G x 2 x ncols
            outs.append(out(a[:, :, 0] if a.shape[2] == 1 else a))
        else:
            outs.append(out(np.array(cols, float).T))
    if nargout <= 1:
        return outs[0]
    return tuple(outs[:nargout])


# ---- the empirical distribution and kernel densities ------------------------------------------------

@bi('ecdf', nout=4)
def ecdf(nargout, *args):
    nargchk(args, 1, 10, 'ecdf')
    from scipy import stats as st
    y = _arr(args[0]).reshape(-1)
    y = y[~np.isnan(y)]
    if y.size == 0:
        raise err('stats:ecdf:NoData', 'There are no data.', 'ecdf')
    opts = {}
    i = 1
    while i + 1 < len(args):
        opts[sval(args[i]).lower()] = args[i + 1]
        i += 2
    alpha = float(num(opts['alpha'])) if 'alpha' in opts else 0.05
    func = sval(opts['function']).lower() if 'function' in opts else 'cdf'
    n = y.size
    xs, counts = np.unique(y, return_counts=True)
    F = np.cumsum(counts) / n
    x = np.concatenate([[xs[0]], xs])
    f = np.concatenate([[0.0], F])
    # Greenwood's bounds
    atrisk = n - np.concatenate([[0], np.cumsum(counts)[:-1]])
    with np.errstate(divide='ignore', invalid='ignore'):
        terms = counts / (atrisk * (atrisk - counts))
        var = (1 - F) ** 2 * np.cumsum(terms)
    z = st.norm.ppf(1 - alpha / 2)
    half = z * np.sqrt(var)
    flo = np.concatenate([[np.nan], np.clip(F - half, 0, 1)])
    fup = np.concatenate([[np.nan], np.clip(F + half, 0, 1)])
    flo[-1] = fup[-1] = np.nan
    if func == 'survivor':
        f, flo, fup = 1 - f, 1 - fup, 1 - flo
    elif func == 'cumulative hazard':
        with np.errstate(divide='ignore'):
            f = -np.log(1 - f)
    if nargout == 0:
        from .statplots import stairs_plot
        stairs_plot(x, f, 'x', {'cdf': 'F(x)', 'survivor': 'S(x)'}.get(func, 'H(x)'))
        return None
    res = (out(f.reshape(-1, 1)), out(x.reshape(-1, 1)), out(flo.reshape(-1, 1)), out(fup.reshape(-1, 1)))
    return res[:nargout] if nargout > 1 else res[0]


def kde(x, pts, bw, kernel, func, support):
    """A kernel estimate at pts: the density ('pdf'), the distribution ('cdf'),
    the survivor or the cumulative hazard. support is 'unbounded', 'positive'
    or (lo, hi); x is the data on the scale the kernel works on (the log, or
    the logit within (lo, hi), for a bounded support)."""
    from .distributions import KERNELS
    pdf_, cdf_ = KERNELS[kernel]
    pts = np.asarray(pts, float)
    p = pts.reshape(-1)
    if support == 'unbounded':
        inside = np.ones(p.shape, bool)
        tp, jac = p, np.ones(p.shape)
    elif support == 'positive':
        inside = p > 0
        pp = np.where(inside, p, 1.0)
        tp, jac = np.log(pp), 1 / pp
    else:
        lo, hi = support
        inside = (p > lo) & (p < hi)
        pp = np.where(inside, p, (lo + hi) / 2)
        tp, jac = np.log((pp - lo) / (hi - pp)), (hi - lo) / ((pp - lo) * (hi - pp))
    u = (tp.reshape(-1, 1) - x.reshape(1, -1)) / bw
    if func == 'pdf':
        v = np.where(inside, np.mean(pdf_(u), axis=1) / bw * jac, 0.0)
    else:
        c = np.mean(cdf_(u), axis=1)
        if support != 'unbounded':
            lo = 0.0 if support == 'positive' else support[0]
            c = np.where(inside, c, np.where(p <= lo, 0.0, 1.0))
        with np.errstate(divide='ignore'):
            v = c if func == 'cdf' else 1 - c if func == 'survivor' else -np.log(1 - c)
    return v.reshape(pts.shape)


@bi('ksdensity', nout=3)
def ksdensity(nargout, *args):
    nargchk(args, 1, 20, 'ksdensity')
    from scipy.optimize import brentq
    from .distributions import kernel_name, default_bandwidth
    x = _arr(args[0]).reshape(-1)
    x = x[~np.isnan(x)]
    if x.size == 0:
        raise err('stats:ksdensity:NoData', 'There are no data.', 'ksdensity')
    rest = list(args[1:])
    pts = None
    if rest and not is_str(rest[0]):
        pts = _arr(rest.pop(0))
    opts = {}
    i = 0
    while i + 1 < len(rest):
        opts[sval(rest[i]).lower()] = rest[i + 1]
        i += 2
    kernel = kernel_name(sval(opts['kernel']), 'ksdensity') if 'kernel' in opts else 'normal'
    func = sval(opts['function']).lower() if 'function' in opts else 'pdf'
    sup = opts.get('support')
    if sup is None or (is_str(sup) and sval(sup).lower() == 'unbounded'):
        support = 'unbounded'
    elif is_str(sup) and sval(sup).lower() == 'positive':
        support = 'positive'
        if np.any(x <= 0):
            raise err('stats:ksdensity:BadSupport', "The data must be positive for 'Support', 'positive'.", 'ksdensity')
    else:
        lohi = _arr(sup).reshape(-1)
        support = (float(lohi[0]), float(lohi[1]))
        if np.any(x <= support[0]) or np.any(x >= support[1]):
            raise err('stats:ksdensity:BadSupport', 'The data must lie inside the support.', 'ksdensity')
    t = x if support == 'unbounded' else (np.log(x) if support == 'positive' else np.log((x - support[0]) / (support[1] - x)))
    bw = float(num(opts['bandwidth'])) if 'bandwidth' in opts else default_bandwidth(t)
    npts = int(num(opts['numpoints'])) if 'numpoints' in opts else 100
    if func == 'icdf':
        p = pts if pts is not None else np.linspace(0, 1, npts)
        lo_t, hi_t = t.min() - 10 * bw, t.max() + 10 * bw
        vals = np.empty(np.size(p))
        for k, q in enumerate(np.asarray(p, float).reshape(-1)):
            if not 0 < q < 1:
                vals[k] = np.nan if not 0 <= q <= 1 else (-np.inf if q == 0 else np.inf)
                continue
            r = brentq(lambda s: float(kde(t, np.array([s]), bw, kernel, 'cdf', 'unbounded')[0]) - q, lo_t, hi_t, xtol=1e-12)
            vals[k] = r if support == 'unbounded' else (math.exp(r) if support == 'positive' else support[0] + (support[1] - support[0]) / (1 + math.exp(-r)))
        f = vals.reshape(np.shape(p))
        xi = np.asarray(p, float)
    else:
        if pts is None:
            if support == 'unbounded':
                xi = np.linspace(x.min() - 3 * bw, x.max() + 3 * bw, npts)
            elif support == 'positive':
                xi = np.linspace(max(x.min() * math.exp(-3 * bw), 0), x.max() * math.exp(3 * bw), npts)
            else:
                xi = np.linspace(support[0], support[1], npts)
        else:
            xi = pts
        f = kde(t, xi, bw, kernel, func, support)
    if nargout == 0:
        from .statplots import line_plot
        line_plot(np.asarray(xi, float).reshape(-1), np.asarray(f, float).reshape(-1))
        return None
    shape_row = pts is None or (np.ndim(pts) == 2 and np.shape(pts)[0] == 1)
    fo = out(np.asarray(f, float).reshape(1, -1) if shape_row else np.asarray(f, float))
    xo = out(np.asarray(xi, float).reshape(1, -1) if shape_row else np.asarray(xi, float))
    res = (fo, xo, bw)
    return res[:nargout] if nargout > 1 else fo


# ---- correlation with p-values ----------------------------------------------------------------------

@bi('corr', nout=2)
def corr(nargout, *args):
    nargchk(args, 1, 8, 'corr')
    from scipy import stats as st
    X = _arr(args[0])
    if X.ndim == 2 and X.shape[0] == 1:
        X = X.reshape(-1, 1)
    rest = list(args[1:])
    Y = None
    if rest and not is_str(rest[0]):
        Y = _arr(rest.pop(0))
        if Y.ndim == 2 and Y.shape[0] == 1:
            Y = Y.reshape(-1, 1)
    opts = {}
    i = 0
    while i + 1 < len(rest):
        opts[sval(rest[i]).lower()] = sval(rest[i + 1]).lower() if is_str(rest[i + 1]) else rest[i + 1]
        i += 2
    kind = opts.get('type', 'pearson')
    rows = opts.get('rows', 'all')
    tail = opts.get('tail', 'both')
    tail = {'ne': 'both', 'gt': 'right', 'lt': 'left'}.get(tail, tail)
    same = Y is None
    if same:
        Y = X
    if Y.shape[0] != X.shape[0]:
        raise err('stats:corr:InputSizeMismatch', 'X and Y must have the same number of rows.', 'corr')
    if rows == 'complete':
        keep = ~(np.any(np.isnan(X), axis=1) | np.any(np.isnan(Y), axis=1))
        X, Y = X[keep], Y[keep]
    p_, q_ = X.shape[1], Y.shape[1]
    rho = np.full((p_, q_), np.nan)
    pv = np.full((p_, q_), np.nan)
    for a in range(p_):
        for b in range(q_):
            x, y = X[:, a], Y[:, b]
            if rows == 'pairwise' or rows == 'complete':
                ok = ~(np.isnan(x) | np.isnan(y))
                x, y = x[ok], y[ok]
            elif np.any(np.isnan(x)) or np.any(np.isnan(y)):
                continue
            n = x.size
            if n < 2:
                continue
            with np.errstate(all='ignore'):
                if kind == 'kendall':
                    res = st.kendalltau(x, y)
                    r, p2 = float(res.statistic), float(res.pvalue)
                else:
                    if kind == 'spearman':
                        x, y = st.rankdata(x), st.rankdata(y)
                    r = float(np.corrcoef(x, y)[0, 1])
                    t = r * math.sqrt((n - 2) / max(1e-300, 1 - r * r)) if n > 2 else math.nan
                    p2 = 2 * float(st.t.sf(abs(t), n - 2)) if n > 2 else math.nan
            if same and a == b:
                r, p2 = 1.0, 1.0
            rho[a, b] = r
            if tail == 'both':
                pv[a, b] = min(1.0, p2)
            else:
                half = p2 / 2
                pv[a, b] = half if (r > 0) == (tail == 'right') else 1 - half
    ro = out(rho)
    return (ro, out(pv)) if nargout > 1 else ro


# ---- resampling ---------------------------------------------------------------------------------------

async def _call(f, args):
    if isinstance(f, FH):
        return await f.acall(1, *args)
    raise err('stats:bootstrp:BadFunction', 'The statistic must be a function handle.', 'bootstrp')


def _rows(v):
    """How many observations a data argument has: a vector's length, a
    matrix's rows; None for a scalar, which goes to the statistic as it is."""
    a = darr(v)
    if a.size <= 1:
        return None
    return a.size if a.ndim == 2 and 1 in a.shape else a.shape[0]


def _pick(v, idx):
    """The observations idx of a data argument (a vector keeps its orientation)."""
    a = darr(v)
    if a.ndim == 2 and 1 in a.shape:
        return out(a.reshape(-1)[idx].reshape((1, -1) if a.shape[0] == 1 else (-1, 1)))
    return out(a[idx])


@bi('bootstrp', nout=2, aw=True)
async def bootstrp(nargout, *args):
    nargchk(args, 3, 30, 'bootstrp')
    from .elmat import RNG
    nboot = int(num(args[0]))
    f = args[1]
    data = list(args[2:])
    sizes = [_rows(d) for d in data]
    n = next((s for s in sizes if s), None)
    if n is None:
        raise err('stats:bootstrp:NoData', 'The data must have more than one row.', 'bootstrp')
    if any(s and s != n for s in sizes):
        raise err('stats:bootstrp:SizeMismatch', 'The data must all have the same number of rows.', 'bootstrp')
    rows = []
    samples = np.empty((n, nboot))
    for b in range(nboot):
        idx = RNG.rs.randint(0, n, n)
        samples[:, b] = idx + 1
        pick = [_pick(d, idx) if s else d for d, s in zip(data, sizes)]
        v = await _call(f, pick)
        rows.append(darr(v).reshape(-1))
    stat = out(np.vstack(rows) if rows else np.zeros((0, 0)))
    return (stat, out(samples)) if nargout > 1 else stat


@bi('jackknife', aw=True)
async def jackknife(nargout, *args):
    nargchk(args, 2, 30, 'jackknife')
    f = args[0]
    data = list(args[1:])
    sizes = [_rows(d) for d in data]
    n = next((s for s in sizes if s), None)
    if n is None:
        raise err('stats:jackknife:NoData', 'The data must have more than one row.', 'jackknife')
    rows = []
    for i in range(n):
        keep = np.flatnonzero(np.arange(n) != i)
        pick = [_pick(d, keep) if s else d for d, s in zip(data, sizes)]
        v = await _call(f, pick)
        rows.append(darr(v).reshape(-1))
    return out(np.vstack(rows))
