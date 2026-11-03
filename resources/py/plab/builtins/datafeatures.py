"""Features of data: local extrema (islocalmax, islocalmin), abrupt changes
(ischange) and trend decomposition (trenddecomp).
"""
import math

import numpy as np

from . import bi as _register
from ._util import err, nargchk, darr, out, opt_str, is_str
from ..values import MError, Char, py_str, numel


def bi(*names, **kw):
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _opts(args, names):
    low = {n.lower(): n for n in names}
    got, rest = {}, []
    i = 0
    while i < len(args):
        s = opt_str(args[i])
        if s is not None and s.lower() in low and i + 1 < len(args):
            got[low[s.lower()]] = args[i + 1]
            i += 2
            continue
        rest.append(args[i])
        i += 1
    return got, rest


def _along(a, rest, fn):
    """The data as columns along the dimension (the first not of size 1) and how to give results back."""
    dim = int(darr(rest[0]).flat[0]) - 1 if rest and not is_str(rest[0]) else next((i for i, s in enumerate(a.shape) if s != 1), 0)
    if a.ndim > 2:
        raise err(f'MATLAB:{fn}:ndims', f'{fn} takes vectors and matrices.', fn)
    X = a.T if dim == 1 else a
    return X, (lambda Y: Y.T if dim == 1 else Y)


# ---- local extrema -----------------------------------------------------------------------------------------------------

def _extrema(v, x, opts):
    """(tf, prominence) of the local maxima of one column."""
    from scipy.signal import peak_prominences
    n = v.size
    tf = np.zeros(n, bool)
    prom = np.zeros(n)
    if n < 3:
        return tf, prom
    flat = py_str(opts['FlatSelection']).lower() if 'FlatSelection' in opts else 'center'
    # runs of equal values; a run higher than the values on both sides is a maximum (never one touching an end)
    cand = []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and v[j + 1] == v[i]:
            j += 1
        if i > 0 and j < n - 1 and np.isfinite(v[i]) and v[i - 1] < v[i] and v[j + 1] < v[i]:
            cand.append((i, j))
        i = j + 1
    if not cand:
        return tf, prom
    vv = np.where(np.isfinite(v), v, -np.inf)
    lefts = np.array([c[0] for c in cand])
    pr = peak_prominences(vv, lefts)[0]
    keep = np.ones(len(cand), bool)
    mp = float(darr(opts['MinProminence']).flat[0]) if 'MinProminence' in opts else 0.0
    keep &= pr >= mp
    sep = float(darr(opts['MinSeparation']).flat[0]) if 'MinSeparation' in opts else 0.0
    order = np.argsort(-pr, kind='stable')
    if sep > 0:
        chosen = []
        for k in order:
            if not keep[k]:
                continue
            centre = x[(cand[k][0] + cand[k][1]) // 2]
            if all(abs(centre - x[(cand[c][0] + cand[c][1]) // 2]) >= sep for c in chosen):
                chosen.append(k)
            else:
                keep[k] = False
    if 'MaxNumExtrema' in opts:
        m = int(darr(opts['MaxNumExtrema']).flat[0])
        kept = [k for k in order if keep[k]]
        for k in kept[m:]:
            keep[k] = False
    for k, (i, j) in enumerate(cand):
        if not keep[k]:
            continue
        idx = {'first': [i], 'last': [j], 'all': list(range(i, j + 1))}.get(flat, [(i + j) // 2])
        tf[idx] = True
        prom[idx] = pr[k]
    return tf, prom


def _localext(nargout, args, fn, sign):
    nargchk(args, 1, 20, fn)
    opts, rest = _opts(list(args[1:]), ('MinProminence', 'FlatSelection', 'MinSeparation', 'MaxNumExtrema', 'ProminenceWindow', 'SamplePoints'))
    a = darr(args[0], fn)
    X, back = _along(a, rest, fn)
    xs = darr(opts['SamplePoints']).reshape(-1).astype(float) if 'SamplePoints' in opts else np.arange(X.shape[0], dtype=float)
    TF = np.zeros(X.shape, bool)
    P = np.zeros(X.shape)
    for j in range(X.shape[1]):
        TF[:, j], P[:, j] = _extrema(sign * X[:, j].astype(float), xs, opts)
    return (out(back(TF)), out(back(P))) if nargout > 1 else out(back(TF))


@bi('islocalmax', nout=2)
def islocalmax(nargout, *args):
    """[TF, P] = islocalmax(A, dim, Name, Value): where the local maxima are (and their prominences)."""
    return _localext(nargout, args, 'islocalmax', 1.0)


@bi('islocalmin', nout=2)
def islocalmin(nargout, *args):
    """[TF, P] = islocalmin(A, dim, Name, Value): where the local minima are (and their prominences)."""
    return _localext(nargout, args, 'islocalmin', -1.0)


# ---- abrupt changes ------------------------------------------------------------------------------------------------------

class _Costs:
    """The cost of a segment y(i:j) (j exclusive) from cumulative sums: its squared residuals about its mean or line, or
    n*log(variance) about its mean (segments of at least 3, the variance kept above a millionth of the data's)."""

    def __init__(self, y, x, method):
        self.method = method
        c = lambda a: np.concatenate([[0.0], np.cumsum(a)])  # noqa: E731
        self.S1, self.S2 = c(y), c(y * y)
        self.X1, self.X2, self.XY = c(x), c(x * x), c(x * y)
        self.min_len = {'mean': 1, 'linear': 2}.get(method, 3)
        self.floor = max(float(np.var(y)) * 1e-6, 1e-300)

    def cost(self, i, j):
        """The costs of the segments from each start in the array i to the end j."""
        n = j - i
        s1, s2 = self.S1[j] - self.S1[i], self.S2[j] - self.S2[i]
        if self.method == 'mean':
            return s2 - s1 * s1 / n
        if self.method == 'variance':
            return n * np.log(np.maximum((s2 - s1 * s1 / n) / n, self.floor))
        x1, x2, xy = self.X1[j] - self.X1[i], self.X2[j] - self.X2[i], self.XY[j] - self.XY[i]
        sxx = x2 - x1 * x1 / n
        sxy = xy - x1 * s1 / n
        with np.errstate(all='ignore'):
            fit = np.where(sxx > 0, sxy * sxy / np.where(sxx > 0, sxx, 1), 0.0)
        return np.maximum(s2 - s1 * s1 / n - fit, 0.0)


def _segments(y, x, method, thr, kmax):
    """The changes (the first sample of each new segment) of the best segmentation: least cost plus thr for each change
    (optimal partitioning with PELT's pruning, Killick et al.), or least cost with at most kmax changes."""
    n = y.size
    C = _Costs(y, x, method)
    L = C.min_len
    if n < 2 * L:
        return []
    if kmax is None:
        best = np.full(n + 1, np.inf)
        best[0] = -thr
        back = np.zeros(n + 1, int)
        cands = np.array([0])
        for j in range(L, n + 1):
            ok = cands[j - cands >= L]
            if ok.size:
                v = best[ok] + C.cost(ok, j)
                k = int(np.argmin(v))
                best[j], back[j] = v[k] + thr, ok[k]
                if L == 1:
                    # a start that cannot beat the best now never will (splitting a segment never raises its squared
                    # residuals); with a least segment length that no longer holds, so nothing is pruned
                    cands = cands[best[cands] + C.cost(cands, j) <= best[j]]
            if j <= n - L:
                cands = np.append(cands, j)
        cuts = []
        j = n
        while j > 0:
            i = back[j]
            if i > 0:
                cuts.append(int(i))
            j = i
        return sorted(cuts)
    K = min(kmax, n // L - 1) + 1
    D = np.full((K + 1, n + 1), np.inf)
    B = np.zeros((K + 1, n + 1), int)
    D[0, 0] = 0.0
    for k in range(1, K + 1):
        for j in range(k * L, n + 1):
            i = np.arange((k - 1) * L, j - L + 1)
            v = D[k - 1, i] + C.cost(i, j)
            m = int(np.argmin(v))
            D[k, j], B[k, j] = v[m], i[m]
    k = int(np.argmin(D[1:, n])) + 1
    cuts = []
    j = n
    while k > 0:
        i = B[k, j]
        if i > 0:
            cuts.append(int(i))
        j, k = i, k - 1
    return sorted(cuts)


@bi('ischange', nout=3)
def ischange(nargout, *args):
    """[TF, S1, S2] = ischange(A, method, dim, 'Threshold', t, 'MaxNumChanges', k): where abrupt changes in the mean (or variance, or line) begin."""
    nargchk(args, 1, 10, 'ischange')
    opts, rest = _opts(list(args[1:]), ('Threshold', 'MaxNumChanges', 'SamplePoints'))
    method = py_str(rest.pop(0)).lower() if rest and is_str(rest[0]) else 'mean'
    if method not in ('mean', 'variance', 'linear'):
        raise err('MATLAB:ischange:method', "The method is 'mean', 'variance' or 'linear'.", 'ischange')
    a = darr(args[0], 'ischange')
    X, back = _along(a, rest, 'ischange')
    thr = float(darr(opts['Threshold']).flat[0]) if 'Threshold' in opts else 1.0
    kmax = int(darr(opts['MaxNumChanges']).flat[0]) if 'MaxNumChanges' in opts else None
    xs = darr(opts['SamplePoints']).reshape(-1).astype(float) if 'SamplePoints' in opts else np.arange(1, X.shape[0] + 1, dtype=float)
    TF = np.zeros(X.shape, bool)
    S1 = np.zeros(X.shape)
    S2 = np.zeros(X.shape)
    for j in range(X.shape[1]):
        y = X[:, j].astype(float)
        if X.shape[0] < 2:
            continue
        cuts = _segments(y, xs, method, thr, kmax)
        TF[cuts, j] = True
        edges = [0] + cuts + [y.size]
        for i0, i1 in zip(edges[:-1], edges[1:]):
            seg, xx = y[i0:i1], xs[i0:i1]
            if method == 'linear':
                if seg.size > 1:
                    slope, icpt = np.polyfit(xx, seg, 1)
                else:
                    slope, icpt = 0.0, seg[0]
                S1[i0:i1, j], S2[i0:i1, j] = slope, icpt
            else:
                S1[i0:i1, j] = seg.mean()
                S2[i0:i1, j] = seg.var(ddof=1) if seg.size > 1 else 0.0
    res = (out(back(TF)), out(back(S1)), out(back(S2)))
    return res[:nargout] if nargout > 1 else res[0]


# ---- trend decomposition -----------------------------------------------------------------------------------------------------

def _ssa(y, L):
    """Singular spectrum analysis: the elementary reconstructed components, largest first."""
    n = y.size
    K = n - L + 1
    T = np.column_stack([y[i:i + L] for i in range(K)])
    U, s, Vt = np.linalg.svd(T, full_matrices=False)
    comps = []
    for k in range(s.size):
        Xk = s[k] * np.outer(U[:, k], Vt[k])
        # diagonal averaging back to a series
        r = np.zeros(n)
        c = np.zeros(n)
        for i in range(L):
            r[i:i + K] += Xk[i]
            c[i:i + K] += 1
        comps.append(r / c)
    return comps, s


def _freq(c):
    F = np.abs(np.fft.rfft(c - c.mean()))
    F[0] = 0
    return int(np.argmax(F)) / c.size if F.size > 1 else 0.0


def _loess_fit(x, y, span, at):
    k = max(int(span), 2)
    out_ = np.empty(at.size)
    for i, t in enumerate(at):
        d = np.abs(x - t)
        idx = np.argsort(d, kind='stable')[:k]
        dmax = max(d[idx].max(), 1e-12)
        if k > x.size:
            dmax = dmax * k / x.size
        w = (1 - (d[idx] / dmax) ** 3) ** 3
        A = np.column_stack([np.ones(idx.size), x[idx] - t])
        sw = np.sqrt(np.maximum(w, 0))
        cc = np.linalg.lstsq(A * sw[:, None], y[idx] * sw, rcond=None)[0]
        out_[i] = cc[0]
    return out_


def _stl(y, period):
    """STL (Cleveland et al.): seasonal-trend decomposition by loess, the inner loop twice, no robustness iterations."""
    n = y.size
    ns = 7
    odd = lambda v: int(v) + (1 - int(v) % 2)  # noqa: E731
    nl = odd(period)
    nt = odd(math.ceil(1.5 * period / (1 - 1.5 / ns)))
    t = np.arange(n, dtype=float)
    trend = np.zeros(n)
    season = np.zeros(n)
    for _ in range(2):
        detr = y - trend
        # each cycle-subseries smoothed, extended a period on each side
        C = np.zeros(n + 2 * period)
        for k in range(period):
            idx = np.arange(k, n, period)
            if idx.size == 0:
                continue
            xs = idx.astype(float)
            at = np.concatenate([[k - period], xs, [xs[-1] + period]])
            sm = _loess_fit(xs, detr[idx], ns, at)
            C[at.astype(int) + period] = sm
        # low-pass: moving averages of period, period, 3, then loess
        def ma(a, m):
            return np.convolve(a, np.ones(m) / m, mode='valid')
        Lp = ma(ma(ma(C, period), period), 3)
        Lp = _loess_fit(np.arange(Lp.size, dtype=float), Lp, nl, np.arange(Lp.size, dtype=float))
        season = C[period:period + n] - Lp[:n]
        trend = _loess_fit(t, y - season, nt, t)
    return trend, season, y - trend - season


@bi('trenddecomp', nout=3)
def trenddecomp(nargout, *args):
    """[LT, ST, R] = trenddecomp(A), trenddecomp(A, 'ssa', lag), trenddecomp(A, 'stl', period): long-term trend, seasonal trends and remainder."""
    nargchk(args, 1, 6, 'trenddecomp')
    a = darr(args[0], 'trenddecomp')
    row = a.shape[0] == 1
    y = a.reshape(-1).astype(float)
    if np.any(~np.isfinite(y)):
        raise err('MATLAB:trenddecomp:finite', 'trenddecomp takes data without NaN or Inf.', 'trenddecomp')
    method = py_str(args[1]).lower() if len(args) > 1 and is_str(args[1]) else 'ssa'
    n = y.size
    if method == 'stl':
        if len(args) < 3:
            raise err('MATLAB:trenddecomp:period', "The 'stl' method needs the period: trenddecomp(A, 'stl', period).", 'trenddecomp')
        periods = [int(v) for v in darr(args[2]).reshape(-1)]
        rest = y.copy()
        ST = []
        LT = np.zeros(n)
        for p in periods:
            if p < 2 or 2 * p > n:
                raise err('MATLAB:trenddecomp:period', 'Each period is at least 2 and at most half the data.', 'trenddecomp')
            tr, se, _ = _stl(rest, p)
            ST.append(se)
            rest = rest - se
            LT = tr
        ST = np.column_stack(ST)
        R_ = y - LT - ST.sum(axis=1)
    elif method == 'ssa':
        L = int(darr(args[2]).flat[0]) if len(args) > 2 else max(2, n // 2)
        if not 2 <= L <= n - 1:
            raise err('MATLAB:trenddecomp:lag', 'The lag is from 2 to the length of the data less 1.', 'trenddecomp')
        comps, s = _ssa(y, L)
        # the signal's components stand above the noise: the hard threshold of Gavish and Donoho (2014) for noise of
        # unknown level, omega(beta) times the median singular value
        beta = min(L, n - L + 1) / max(L, n - L + 1)
        tau = (0.56 * beta ** 3 - 0.95 * beta ** 2 + 1.82 * beta + 1.43) * np.median(s)
        LT = np.zeros(n)
        seasonal = {}
        for c, sv in zip(comps, s):
            if sv <= tau or sv <= s[0] * 1e-10:
                continue
            f = _freq(c)
            if f * L <= 1:
                LT += c
            else:
                # oscillations of the same period (they come in pairs) make one seasonal trend
                key = round(1 / f)
                seasonal[key] = seasonal.get(key, np.zeros(n)) + c
        order = sorted(seasonal, key=lambda k: -np.sum(seasonal[k] ** 2))
        ST = np.column_stack([seasonal[k] for k in order]) if seasonal else np.zeros((n, 0))
        R_ = y - LT - (ST.sum(axis=1) if ST.size else 0)
    else:
        raise err('MATLAB:trenddecomp:method', "The method is 'ssa' or 'stl'.", 'trenddecomp')
    fix = (lambda v: v.T) if row else (lambda v: v)
    res = (out(fix(LT.reshape(-1, 1))), out(fix(ST) if ST.size else np.zeros((0, 0))), out(fix(R_.reshape(-1, 1))))
    return res[:nargout] if nargout > 1 else res[0]
