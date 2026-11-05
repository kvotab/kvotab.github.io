"""Hypothesis tests: t and z tests, tests of variances, the sign, signed
rank and rank sum tests, goodness of fit (Kolmogorov-Smirnov, Lilliefors,
Jarque-Bera, Anderson-Darling, chi-square), the runs test, analysis of
variance (one- and two-way, Kruskal-Wallis, Friedman) with multiple
comparisons, contingency tables and Fisher's exact test.

Each gives the result h (1 when the null hypothesis is rejected at the
significance level, 0 when it is not), the p-value and the statistics, in
the order and with the names of the language's functions. Where a p-value
has no closed form it comes from a published approximation (Lilliefors:
Dallal and Wilkinson; Anderson-Darling: Stephens) or from a simulation with
a fixed seed (so that the same data give the same p-value).
"""
import math

import numpy as np

from . import bi
from ._util import err, nargchk, darr, out, opt_str, sval, num, is_str, cellstr_list
from ..values import Char, Cell, Struct, Str, FH, EMPTY
from .. import runtime as R
from .statdesc import groups, _count


def _st():
    import scipy.stats as st
    return st


TAILS = {'both': 'both', 'ne': 'both', 'right': 'right', 'gt': 'right', 'left': 'left', 'lt': 'left',
         '0': 'both', '1': 'right', '-1': 'left'}


def _opts(args, fn, positional=('alpha', 'tail')):
    """Options: the older positional ones (alpha, tail...) then name-value pairs."""
    opts = {}
    rest = list(args)
    k = 0
    while rest and k < len(positional):
        a = rest[0]
        if is_str(a) and sval(a).lower() in ('alpha', 'tail', 'dim', 'vartype', 'method', 'cdf', 'distribution', 'distr',
                                              'testtype', 'display', 'nbins', 'ctrs', 'edges', 'expected', 'nparams',
                                              'emin', 'frequency', 'ctype', 'estimate', 'dimension', 'mctol', 'mode'):
            break
        if not (is_str(a) or np.size(darr(a)) == 0):
            opts[positional[k]] = a
        elif is_str(a):
            opts[positional[k]] = a
        rest.pop(0)
        k += 1
    i = 0
    while i < len(rest):
        s = opt_str(rest[i])
        if s is None or i + 1 >= len(rest):
            raise err('stats:NameValue', 'Options must come in name-value pairs.', fn)
        opts[s.lower()] = rest[i + 1]
        i += 2
    return opts


def _alpha(opts, fn):
    a = float(num(opts['alpha'])) if 'alpha' in opts else 0.05
    if not 0 < a < 1:
        raise err('stats:BadAlpha', 'ALPHA must be a scalar between 0 and 1.', fn)
    return a


def _tail(opts, fn, words=TAILS):
    t = opts.get('tail')
    if t is None:
        return 'both'
    s = sval(t).lower() if is_str(t) else f'{int(num(t))}'
    if s not in words:
        raise err('stats:BadTail', "TAIL must be 'both', 'right' or 'left'.", fn)
    return words[s]


def _p_from(stat_cdf, stat_sf, tail):
    """A p-value from the null distribution's cdf and sf at the statistic."""
    if tail == 'both':
        return min(1.0, 2 * min(stat_cdf, stat_sf))
    return stat_sf if tail == 'right' else stat_cdf


def _h(p, alpha):
    return math.nan if p != p else float(p <= alpha)


def _vec(v):
    a = darr(v).real.astype(float).reshape(-1)
    return a[~np.isnan(a)]


def _columns(v):
    a = darr(v).real.astype(float)
    if a.ndim == 2 and a.shape[0] == 1:
        a = a.reshape(-1, 1)
    return a


def _pack(nargout, *vals):
    vals = tuple(float(v) if isinstance(v, np.floating) else v for v in vals)
    return vals[:nargout] if nargout > 1 else vals[0]


def _is_row(v):
    a = darr(v)
    return a.ndim == 2 and a.shape[0] == 1 and a.shape[1] > 1


def _ci(lo_hi, data):
    """An interval laid along the data: a row for a row vector, else a column."""
    a = np.asarray(lo_hi, float).reshape(2, 1)
    return out(a.T if _is_row(data) else a)


# ---- t, z ---------------------------------------------------------------------------------------------

def _t_one(d, m, alpha, tail):
    st = _st()
    n = d.size
    mean = float(np.mean(d)) if n else math.nan
    sd = float(np.std(d, ddof=1)) if n > 1 else math.nan
    df = n - 1
    se = sd / math.sqrt(n) if n else math.nan
    with np.errstate(all='ignore'):
        t = (mean - m) / se if se > 0 else (math.copysign(math.inf, mean - m) if mean != m else math.nan)
    p = _p_from(float(st.t.cdf(t, df)), float(st.t.sf(t, df)), tail) if df > 0 else math.nan
    if tail == 'both':
        c = float(st.t.ppf(1 - alpha / 2, df)) if df > 0 else math.nan
        ci = (mean - c * se, mean + c * se)
    else:
        c = float(st.t.ppf(1 - alpha, df)) if df > 0 else math.nan
        ci = (mean - c * se, math.inf) if tail == 'right' else (-math.inf, mean + c * se)
    return p, ci, t, float(df), sd


@bi('ttest', nout=4)
def ttest(nargout, *args):
    nargchk(args, 1, 10, 'ttest')
    X = darr(args[0]).real.astype(float)
    rest = list(args[1:])
    m = 0.0
    if rest and not is_str(rest[0]):
        y = darr(rest.pop(0)).real.astype(float)
        if y.size == 1:
            m = float(y.reshape(-1)[0])
        else:
            if y.shape != X.shape:
                raise err('stats:ttest:InputSizeMismatch', 'The data in a paired t-test must be the same size.', 'ttest')
            X = X - y
    opts = _opts(rest, 'ttest')
    alpha, tail = _alpha(opts, 'ttest'), _tail(opts, 'ttest')
    by_rows = int(num(opts['dim'])) == 2 if 'dim' in opts else _is_row(args[0])
    X = X.reshape(X.shape[0], -1)
    if by_rows:
        X = X.T
    res = [_t_one(X[:, j][~np.isnan(X[:, j])], m, alpha, tail) for j in range(X.shape[1])]

    def lay(v):
        a = np.array([v], float)
        return out(a.T if by_rows else a)
    ci = np.array([list(r[1]) for r in res], float).T
    stats = Struct.scalar({'tstat': lay([r[2] for r in res]), 'df': lay([r[3] for r in res]), 'sd': lay([r[4] for r in res])})
    return _pack(nargout, lay([_h(r[0], alpha) for r in res]), lay([r[0] for r in res]), out(ci.T if by_rows else ci), stats)


@bi('ttest2', nout=4)
def ttest2(nargout, *args):
    nargchk(args, 2, 12, 'ttest2')
    st = _st()
    x, y = _vec(args[0]), _vec(args[1])
    opts = _opts(args[2:], 'ttest2', ('alpha', 'tail', 'vartype'))
    alpha, tail = _alpha(opts, 'ttest2'), _tail(opts, 'ttest2')
    vt = sval(opts['vartype']).lower() if 'vartype' in opts else 'equal'
    nx, ny = x.size, y.size
    mx, my = float(np.mean(x)), float(np.mean(y))
    vx, vy = float(np.var(x, ddof=1)), float(np.var(y, ddof=1))
    diff = mx - my
    if vt.startswith('u'):
        se = math.sqrt(vx / nx + vy / ny)
        df = (vx / nx + vy / ny) ** 2 / ((vx / nx) ** 2 / (nx - 1) + (vy / ny) ** 2 / (ny - 1))
        sd = out(np.array([[math.sqrt(vx), math.sqrt(vy)]]))
    else:
        df = nx + ny - 2
        sp = math.sqrt(((nx - 1) * vx + (ny - 1) * vy) / df)
        se = sp * math.sqrt(1 / nx + 1 / ny)
        sd = sp
    with np.errstate(all='ignore'):
        t = diff / se if se > 0 else math.nan
    p = _p_from(float(st.t.cdf(t, df)), float(st.t.sf(t, df)), tail)
    if tail == 'both':
        c = float(st.t.ppf(1 - alpha / 2, df))
        ci = [diff - c * se, diff + c * se]
    else:
        c = float(st.t.ppf(1 - alpha, df))
        ci = [diff - c * se, math.inf] if tail == 'right' else [-math.inf, diff + c * se]
    stats = Struct.scalar({'tstat': t, 'df': float(df), 'sd': sd})
    return _pack(nargout, _h(p, alpha), p, _ci(ci, args[0]), stats)


@bi('ztest', nout=4)
def ztest(nargout, *args):
    nargchk(args, 3, 9, 'ztest')
    st = _st()
    x = _vec(args[0])
    m, sigma = float(num(args[1])), float(num(args[2]))
    opts = _opts(args[3:], 'ztest')
    alpha, tail = _alpha(opts, 'ztest'), _tail(opts, 'ztest')
    n = x.size
    mean = float(np.mean(x))
    se = sigma / math.sqrt(n)
    z = (mean - m) / se
    p = _p_from(float(st.norm.cdf(z)), float(st.norm.sf(z)), tail)
    if tail == 'both':
        c = float(st.norm.ppf(1 - alpha / 2))
        ci = [mean - c * se, mean + c * se]
    else:
        c = float(st.norm.ppf(1 - alpha))
        ci = [mean - c * se, math.inf] if tail == 'right' else [-math.inf, mean + c * se]
    return _pack(nargout, _h(p, alpha), p, _ci(ci, args[0]), z)


# ---- variances ----------------------------------------------------------------------------------------

@bi('vartest', nout=4)
def vartest(nargout, *args):
    nargchk(args, 2, 8, 'vartest')
    st = _st()
    x = _vec(args[0])
    v0 = float(num(args[1]))
    opts = _opts(args[2:], 'vartest')
    alpha, tail = _alpha(opts, 'vartest'), _tail(opts, 'vartest')
    n = x.size
    df = n - 1
    s2 = float(np.var(x, ddof=1))
    chi = df * s2 / v0
    p = _p_from(float(st.chi2.cdf(chi, df)), float(st.chi2.sf(chi, df)), tail)
    if tail == 'both':
        ci = [df * s2 / st.chi2.ppf(1 - alpha / 2, df), df * s2 / st.chi2.ppf(alpha / 2, df)]
    elif tail == 'right':
        ci = [df * s2 / st.chi2.ppf(1 - alpha, df), math.inf]
    else:
        ci = [0.0, df * s2 / st.chi2.ppf(alpha, df)]
    stats = Struct.scalar({'chisqstat': chi, 'df': float(df)})
    return _pack(nargout, _h(p, alpha), p, _ci(ci, args[0]), stats)


@bi('vartest2', nout=4)
def vartest2(nargout, *args):
    nargchk(args, 2, 8, 'vartest2')
    st = _st()
    x, y = _vec(args[0]), _vec(args[1])
    opts = _opts(args[2:], 'vartest2')
    alpha, tail = _alpha(opts, 'vartest2'), _tail(opts, 'vartest2')
    d1, d2 = x.size - 1, y.size - 1
    F = float(np.var(x, ddof=1) / np.var(y, ddof=1))
    p = _p_from(float(st.f.cdf(F, d1, d2)), float(st.f.sf(F, d1, d2)), tail)
    if tail == 'both':
        ci = [F / st.f.ppf(1 - alpha / 2, d1, d2), F / st.f.ppf(alpha / 2, d1, d2)]
    elif tail == 'right':
        ci = [F / st.f.ppf(1 - alpha, d1, d2), math.inf]
    else:
        ci = [0.0, F / st.f.ppf(alpha, d1, d2)]
    stats = Struct.scalar({'fstat': F, 'df1': float(d1), 'df2': float(d2)})
    return _pack(nargout, _h(p, alpha), p, _ci(ci, args[0]), stats)


def _grouped(args, fn):
    """Data in groups: a matrix's columns, or a vector with a grouping
    variable: (list of arrays, labels)."""
    X = darr(args[0]).real.astype(float)
    g = args[1] if len(args) > 1 and not (type(args[1]) is np.ndarray and args[1].size == 0) else None
    if g is None or (is_str(g) and sval(g).lower() in ('on', 'off', 'display', 'testtype')):
        if X.ndim == 2 and X.shape[0] == 1:
            X = X.reshape(-1, 1)
        cols = [X[:, j][~np.isnan(X[:, j])] for j in range(X.shape[1])]
        return cols, [str(j + 1) for j in range(X.shape[1])]
    x = X.reshape(-1)
    if X.ndim == 2 and X.shape[1] > 1 and X.shape[0] > 1:
        # a matrix with group names for its columns
        names = groups(g, X.shape[1], fn)[0] if _count(g) == X.shape[1] else None
        if names is not None:
            return [X[:, j][~np.isnan(X[:, j])] for j in range(X.shape[1])], names
    labels, idx = groups(g, x.size, fn)
    out_ = []
    for k in range(len(labels)):
        v = x[idx == k]
        out_.append(v[~np.isnan(v)])
    return out_, labels


@bi('vartestn', nout=2)
def vartestn(nargout, *args):
    nargchk(args, 1, 10, 'vartestn')
    st = _st()
    rest = list(args)
    data = rest[:2] if len(rest) > 1 and not (is_str(rest[1]) and sval(rest[1]).lower() in ('testtype', 'display')) else rest[:1]
    cols, labels = _grouped(data, 'vartestn')
    opts = _opts(rest[len(data):], 'vartestn', ())
    kind = sval(opts['testtype']).lower() if 'testtype' in opts else 'bartlett'
    display = sval(opts['display']).lower() != 'off' if 'display' in opts else True
    cols = [c for c in cols if c.size > 0]
    k = len(cols)
    n = np.array([c.size for c in cols], float)
    N = n.sum()
    if kind == 'bartlett':
        v = np.array([np.var(c, ddof=1) for c in cols])
        sp = float(np.sum((n - 1) * v) / (N - k))
        chi = float(((N - k) * math.log(sp) - np.sum((n - 1) * np.log(v))) / (1 + (np.sum(1 / (n - 1)) - 1 / (N - k)) / (3 * (k - 1))))
        p = float(st.chi2.sf(chi, k - 1))
        stats = Struct.scalar({'chisqstat': chi, 'df': float(k - 1)})
        line = f'Bartlett statistic {chi:.4g} on {k - 1} degrees of freedom'
    else:
        if kind in ('levenequadratic', 'levene'):
            z = [(c - c.mean()) ** 2 for c in cols]
        elif kind == 'leveneabsolute':
            z = [np.abs(c - c.mean()) for c in cols]
        elif kind == 'brownforsythe':
            z = [np.abs(c - np.median(c)) for c in cols]
        elif kind == 'obrien':
            z = []
            for c in cols:
                m_ = c.size
                w = 0.5
                r = (c - c.mean()) ** 2
                z.append(((w + m_ - 2) * m_ * r - w * (m_ - 1) * np.sum(r)) / ((m_ - 1) * (m_ - 2)))
        else:
            raise err('stats:vartestn:BadTestType', "TestType must be 'Bartlett', 'LeveneQuadratic', 'LeveneAbsolute', "
                      "'BrownForsythe' or 'OBrien'.", 'vartestn')
        F, p, _, _ = _anova_parts(z)
        stats = Struct.scalar({'fstat': F, 'df': out(np.array([[k - 1, N - k]], float))})
        line = f'F statistic {F:.4g} on {k - 1} and {int(N - k)} degrees of freedom'
    if display:
        rows = [(lab, int(c.size), float(np.mean(c)), float(np.std(c, ddof=1)) if c.size > 1 else math.nan) for lab, c in zip(labels, cols)]
        w = max([5] + [len(r[0]) for r in rows])
        text = [f'  {"Group":<{w}}  {"Count":>6}  {"Mean":>11}  {"Std Dev":>11}']
        text += [f'  {lab:<{w}}  {cnt:>6d}  {m_:>11.5g}  {s_:>11.5g}' for lab, cnt, m_, s_ in rows]
        text += ['', f'  {line}, p = {p:.4g}', '']
        R.write('\n'.join(text) + '\n')
    return _pack(nargout, p, stats)


# ---- sign, signed rank, rank sum ---------------------------------------------------------------------------

def _rank_dist(scores):
    """The exact null distribution of a sum over random signs (signed rank) of
    integer scores: {value: probability}."""
    dist = {0: 1.0}
    for s in scores:
        nxt = {}
        for v, pr in dist.items():
            nxt[v + s] = nxt.get(v + s, 0.0) + pr / 2
            nxt[v] = nxt.get(v, 0.0) + pr / 2
        dist = nxt
    return dist


def _paired_input(args, fn):
    x = darr(args[0]).real.astype(float).reshape(-1)
    rest = list(args[1:])
    m = 0.0
    if rest and not is_str(rest[0]):
        y = darr(rest.pop(0)).real.astype(float).reshape(-1)
        if y.size == 1:
            m = float(y[0])
            d = x - m
        else:
            if y.size != x.size:
                raise err(f'stats:{fn}:InputSizeMismatch', 'X and Y must be the same length.', fn)
            d = x - y
    else:
        d = x - m
    return d[~np.isnan(d)], rest


@bi('signtest', nout=3)
def signtest(nargout, *args):
    nargchk(args, 1, 10, 'signtest')
    st = _st()
    d, rest = _paired_input(args, 'signtest')
    opts = _opts(rest, 'signtest', ('alpha', 'method'))
    alpha, tail = _alpha(opts, 'signtest'), _tail(opts, 'signtest')
    d = d[d != 0]
    npos, nneg = int(np.sum(d > 0)), int(np.sum(d < 0))
    n = npos + nneg
    method = sval(opts['method']).lower() if 'method' in opts else ('exact' if n < 100 else 'approximate')
    fields = {'sign': float(npos)}
    if method == 'exact':
        lo, hi = float(st.binom.cdf(npos, n, 0.5)), float(st.binom.sf(npos - 1, n, 0.5))
        p = _p_from(lo, hi, tail)
    else:
        z = (npos - n / 2 - 0.5 * np.sign(npos - n / 2)) / math.sqrt(n / 4) if n else 0.0
        if tail == 'right':
            z = (npos - n / 2 - 0.5) / math.sqrt(n / 4)
        elif tail == 'left':
            z = (npos - n / 2 + 0.5) / math.sqrt(n / 4)
        p = _p_from(float(st.norm.cdf(z)), float(st.norm.sf(z)), tail)
        fields['zval'] = float(z)
    return _pack(nargout, p, _h(p, alpha), Struct.scalar(fields))


@bi('signrank', nout=3)
def signrank(nargout, *args):
    nargchk(args, 1, 10, 'signrank')
    st = _st()
    d, rest = _paired_input(args, 'signrank')
    opts = _opts(rest, 'signrank', ('alpha', 'method'))
    alpha, tail = _alpha(opts, 'signrank'), _tail(opts, 'signrank')
    d = d[d != 0]
    n = d.size
    r = st.rankdata(np.abs(d))
    w = float(np.sum(r[d > 0]))
    method = sval(opts['method']).lower() if 'method' in opts else ('exact' if n <= 15 else 'approximate')
    fields = {'signedrank': w}
    if method == 'exact':
        dist = _rank_dist([int(round(2 * v)) for v in r])
        w2 = int(round(2 * w))
        lo = sum(p for v, p in dist.items() if v <= w2)
        hi = sum(p for v, p in dist.items() if v >= w2)
        p = _p_from(lo, hi, tail)
    else:
        _, counts = np.unique(np.abs(d), return_counts=True)
        tieadj = float(np.sum(counts ** 3 - counts)) / 2
        e = n * (n + 1) / 4
        sd = math.sqrt((n * (n + 1) * (2 * n + 1) - tieadj) / 24)
        corr = 0.5 * np.sign(w - e) if tail == 'both' else (0.5 if tail == 'right' else -0.5)
        z = (w - e - corr) / sd if sd > 0 else 0.0
        p = _p_from(float(st.norm.cdf(z)), float(st.norm.sf(z)), tail)
        fields['zval'] = float(z)
    return _pack(nargout, p, _h(p, alpha), Struct.scalar(fields))


@bi('ranksum', nout=3)
def ranksum(nargout, *args):
    nargchk(args, 2, 10, 'ranksum')
    st = _st()
    x, y = _vec(args[0]), _vec(args[1])
    opts = _opts(args[2:], 'ranksum', ('alpha', 'method'))
    alpha, tail = _alpha(opts, 'ranksum'), _tail(opts, 'ranksum')
    nx, ny = x.size, y.size
    r = st.rankdata(np.concatenate([x, y]))
    srank = float(np.sum(r[:nx]))
    method = sval(opts['method']).lower() if 'method' in opts else ('exact' if min(nx, ny) < 10 and nx + ny < 20 else 'approximate')
    fields = {'ranksum': srank}
    if method == 'exact':
        # the sums of nx of the (doubled, integer) ranks, all choices equally likely
        scores = [int(round(2 * v)) for v in r]
        ways = [{0: 1}]
        for s in scores:
            nxt = [dict(w) for w in ways] + [{}]
            for k in range(len(ways)):
                for v, c in ways[k].items():
                    nxt[k + 1][v + s] = nxt[k + 1].get(v + s, 0) + c
            ways = nxt
        dist = ways[nx]
        total = sum(dist.values())
        s2 = int(round(2 * srank))
        lo = sum(c for v, c in dist.items() if v <= s2) / total
        hi = sum(c for v, c in dist.items() if v >= s2) / total
        p = _p_from(lo, hi, tail)
    else:
        _, counts = np.unique(np.concatenate([x, y]), return_counts=True)
        tie = float(np.sum(counts ** 3 - counts))
        N = nx + ny
        e = nx * (N + 1) / 2
        sd = math.sqrt(nx * ny / 12 * ((N + 1) - tie / (N * (N - 1))))
        corr = 0.5 * np.sign(srank - e) if tail == 'both' else (0.5 if tail == 'right' else -0.5)
        z = (srank - e - corr) / sd if sd > 0 else 0.0
        p = _p_from(float(st.norm.cdf(z)), float(st.norm.sf(z)), tail)
        fields['zval'] = float(z)
    return _pack(nargout, p, _h(p, alpha), Struct.scalar(fields))


# ---- goodness of fit ------------------------------------------------------------------------------------

def _cdf_fn(spec, fn):
    """A hypothesized distribution: a distribution object or a two-column table [x, F(x)]."""
    from .distributions import is_dist
    if is_dist(spec):
        return lambda x: np.asarray(spec.cdf(x), float)
    a = darr(spec).real.astype(float)
    if a.ndim == 2 and a.shape[1] == 2:
        xs, Fs = a[:, 0], a[:, 1]
        return lambda x: np.interp(x, xs, Fs, left=0.0, right=1.0)
    raise err(f'stats:{fn}:BadCdf', 'The CDF must be a probability distribution object or a two-column matrix [x, F(x)].', fn)


KS_TAILS = {'unequal': 'two-sided', 'larger': 'greater', 'smaller': 'less'}


@bi('kstest', nout=4)
def kstest(nargout, *args):
    nargchk(args, 1, 10, 'kstest')
    st = _st()
    x = np.sort(_vec(args[0]))
    opts = _opts(args[1:], 'kstest', ('cdf', 'alpha', 'tail'))
    alpha = _alpha(opts, 'kstest')
    tail = sval(opts['tail']).lower() if 'tail' in opts and is_str(opts['tail']) else 'unequal'
    if tail not in KS_TAILS:
        raise err('stats:kstest:BadTail', "TAIL must be 'unequal', 'larger' or 'smaller'.", 'kstest')
    F = _cdf_fn(opts['cdf'], 'kstest') if 'cdf' in opts and np.size(darr(opts['cdf']) if not hasattr(opts['cdf'], 'is_probdist') else 1) else (lambda t: st.norm.cdf(t))
    res = st.kstest(x, F, alternative=KS_TAILS[tail])
    n = x.size
    cv = float(st.kstwo.ppf(1 - alpha, n)) if tail == 'unequal' else float(st.ksone.ppf(1 - alpha, n))
    p = float(res.pvalue)
    return _pack(nargout, _h(p, alpha), p, float(res.statistic), cv)


def _ks2_p(d, n, tail):
    """The large-sample p-value of a two-sample statistic d with effective size n."""
    lam = max((math.sqrt(n) + 0.12 + 0.11 / math.sqrt(n)) * d, 0.0)
    if tail != 'unequal':
        return math.exp(-2 * lam * lam)
    if lam == 0:
        return 1.0
    j = np.arange(1, 101)
    return float(min(1.0, max(0.0, 2 * np.sum((-1.0) ** (j - 1) * np.exp(-2 * lam * lam * j * j)))))


@bi('kstest2', nout=3)
def kstest2(nargout, *args):
    nargchk(args, 2, 8, 'kstest2')
    x1, x2 = np.sort(_vec(args[0])), np.sort(_vec(args[1]))
    opts = _opts(args[2:], 'kstest2', ('alpha', 'tail'))
    alpha = _alpha(opts, 'kstest2')
    tail = sval(opts['tail']).lower() if 'tail' in opts and is_str(opts['tail']) else 'unequal'
    allx = np.concatenate([x1, x2])
    F1 = np.searchsorted(x1, allx, side='right') / x1.size
    F2 = np.searchsorted(x2, allx, side='right') / x2.size
    diff = F1 - F2
    d = float(np.max(np.abs(diff)) if tail == 'unequal' else (np.max(diff) if tail == 'larger' else np.max(-diff)))
    n = x1.size * x2.size / (x1.size + x2.size)
    p = _ks2_p(d, n, tail)
    return _pack(nargout, _h(p, alpha), p, d)


def _lillie_p(K, n):
    """The Lilliefors (normal, both parameters estimated) p-value of a
    Kolmogorov-Smirnov statistic K for n values: Dallal and Wilkinson's
    approximation below 0.1, Stephens' polynomials above."""
    Kd, nd = (K, n) if n <= 100 else (K * (n / 100) ** 0.49, 100)
    p = math.exp(-7.01256 * Kd * Kd * (nd + 2.78019) + 2.99587 * Kd * math.sqrt(nd + 2.78019) - 0.122119
                 + 0.974598 / math.sqrt(nd) + 1.67997 / nd)
    if p > 0.1:
        KK = (math.sqrt(n) - 0.01 + 0.85 / math.sqrt(n)) * K
        if KK <= 0.302:
            p = 1.0
        elif KK <= 0.5:
            p = 2.76773 - 19.828315 * KK + 80.709644 * KK ** 2 - 138.55152 * KK ** 3 + 81.218052 * KK ** 4
        elif KK <= 0.9:
            p = -4.901232 + 40.662806 * KK - 97.490286 * KK ** 2 + 94.029866 * KK ** 3 - 32.355711 * KK ** 4
        elif KK <= 1.31:
            p = 6.198765 - 19.558097 * KK + 23.186922 * KK ** 2 - 12.234627 * KK ** 3 + 2.423045 * KK ** 4
        else:
            p = 0.0
    return float(min(1.0, max(0.0, p)))


def _ks_stat(x, F):
    n = x.size
    Fx = F(x)
    i = np.arange(1, n + 1)
    return float(max(np.max(i / n - Fx), np.max(Fx - (i - 1) / n)))


def _reps(n):
    """How many samples a simulated null distribution draws: 20000, fewer
    for large samples (at least 2000)."""
    return max(2000, min(20000, 4_000_000 // max(n, 1)))


def _mc_p(null, stat):
    """A simulated p-value: (draws at least as large + 1) / (draws + 1)."""
    return float((np.sum(null >= stat) + 1) / (null.size + 1))


def _ev_fit(Z):
    """Maximum likelihood estimates (mu, sigma) of the smallest extreme
    value distribution for each row of Z. sigma solves
    sigma = sum(x w) / sum(w) - mean(x), w = exp(x / sigma), by Newton's
    method; then mu = sigma log(mean(w))."""
    Z = np.atleast_2d(np.asarray(Z, float))
    xbar = Z.mean(axis=1)
    s = np.sqrt(6) / np.pi * Z.std(axis=1, ddof=1)
    s = np.where(s > 0, s, 1.0)
    for _ in range(200):
        u = Z / s[:, None]
        w = np.exp(u - u.max(axis=1, keepdims=True))
        sw = w.sum(axis=1)
        a = (Z * w).sum(axis=1) / sw
        v = np.maximum((Z * Z * w).sum(axis=1) / sw - a * a, 0.0)
        new = s - (a - xbar - s) / (-v / (s * s) - 1)
        new = np.where(new > 0, new, s / 2)
        done = np.all(np.abs(new - s) <= 1e-13 * s)
        s = new
        if done:
            break
    u = Z / s[:, None]
    top = u.max(axis=1)
    mu = s * (np.log(np.mean(np.exp(u - top[:, None]), axis=1)) + top)
    return mu, s


def _ev_cdf(z, mu, s):
    return -np.expm1(-np.exp((z - mu) / s))


_NULLS = {}


def _simulate(stat_fn, n, reps=None, seed=20261101, key=None):
    """The null distribution of a statistic by simulation (a fixed seed, so
    the same data give the same p-value). With a key, the draws are kept
    for the next test of that kind and size."""
    reps = reps or _reps(n)
    if key is not None and (key, n, reps) in _NULLS:
        return _NULLS[(key, n, reps)]
    rs = np.random.RandomState(seed)
    out_ = np.empty(reps)
    batch = max(1, min(reps, 2_000_000 // max(n, 1)))
    k = 0
    while k < reps:
        m = min(batch, reps - k)
        out_[k:k + m] = stat_fn(rs, m, n)
        k += m
    if key is not None:
        if len(_NULLS) >= 64:
            _NULLS.pop(next(iter(_NULLS)))
        _NULLS[(key, n, reps)] = out_
    return out_


@bi('lillietest', nout=4)
def lillietest(nargout, *args):
    nargchk(args, 1, 8, 'lillietest')
    st = _st()
    x = np.sort(_vec(args[0]))
    opts = _opts(args[1:], 'lillietest', ('alpha', 'distr'))
    alpha = _alpha(opts, 'lillietest')
    distr = sval(opts.get('distribution', opts.get('distr', Char.of('norm')))).lower()
    n = x.size
    if n < 4:
        raise err('stats:lillietest:NotEnoughData', 'The sample must have at least 4 values.', 'lillietest')
    if distr.startswith('norm'):
        m, s = float(np.mean(x)), float(np.std(x, ddof=1))
        K = _ks_stat(x, lambda t: st.norm.cdf(t, m, s))
        p = _lillie_p(K, n)
        from scipy.optimize import brentq
        cv = brentq(lambda k: _lillie_p(k, n) - alpha, 1e-6, 1.0) if 0 < alpha < 1 else math.nan
    else:
        if distr.startswith('exp'):
            if np.any(x < 0):
                raise err('stats:lillietest:BadData', 'The data must be nonnegative for an exponential test.', 'lillietest')
            K = _ks_stat(x, lambda t: st.expon.cdf(t, scale=float(np.mean(x))))

            def sim(rs, m_, n_):
                z = np.sort(rs.exponential(size=(m_, n_)), axis=1)
                F = 1 - np.exp(-z / z.mean(axis=1, keepdims=True))
                i = np.arange(1, n_ + 1)
                return np.maximum(np.max(i / n_ - F, axis=1), np.max(F - (i - 1) / n_, axis=1))
        elif distr == 'ev':
            mu, s = (float(v[0]) for v in _ev_fit(x))
            K = _ks_stat(x, lambda t: _ev_cdf(t, mu, s))

            def sim(rs, m_, n_):
                z = np.sort(np.log(rs.exponential(size=(m_, n_))), axis=1)
                a, b = _ev_fit(z)
                F = _ev_cdf(z, a[:, None], b[:, None])
                i = np.arange(1, n_ + 1)
                return np.maximum(np.max(i / n_ - F, axis=1), np.max(F - (i - 1) / n_, axis=1))
        else:
            raise err('stats:lillietest:BadDistr', "Distr must be 'norm', 'exp' or 'ev'.", 'lillietest')
        null = _simulate(sim, n, key='lillie-' + distr[:3])
        p = _mc_p(null, K)
        cv = float(np.quantile(null, 1 - alpha))
    return _pack(nargout, _h(p, alpha), p, K, cv)


def _jb(x):
    n = x.shape[-1]
    m = x - x.mean(axis=-1, keepdims=True)
    m2 = np.mean(m ** 2, axis=-1)
    s = np.mean(m ** 3, axis=-1) / m2 ** 1.5
    k = np.mean(m ** 4, axis=-1) / m2 ** 2
    return n / 6 * (s ** 2 + (k - 3) ** 2 / 4)


@bi('jbtest', nout=4)
def jbtest(nargout, *args):
    nargchk(args, 1, 3, 'jbtest')
    st = _st()
    x = _vec(args[0])
    alpha = float(num(args[1])) if len(args) > 1 and np.size(darr(args[1])) else 0.05
    if len(args) > 1 and np.size(darr(args[1])) and (np.size(darr(args[1])) != 1 or not 0 < alpha < 1):
        raise err('stats:jbtest:BadAlpha', 'alpha must be a number between 0 and 1.', 'jbtest')
    n = x.size
    if n < 2:
        raise err('stats:jbtest:NotEnoughData', 'The sample must have at least 2 values.', 'jbtest')
    jb = float(_jb(x))
    if n <= 2000:
        null = _simulate(lambda rs, m_, n_: _jb(rs.standard_normal((m_, n_))), n, key='jb')
        p = _mc_p(null, jb)
        cv = float(np.quantile(null, 1 - alpha))
    else:
        p = float(st.chi2.sf(jb, 2))
        cv = float(st.chi2.ppf(1 - alpha, 2))
    return _pack(nargout, _h(p, alpha), p, jb, cv)


def _ad(z):
    """The Anderson-Darling statistic of probabilities z (sorted, the cdf at the data)."""
    n = z.shape[-1]
    i = np.arange(1, n + 1)
    with np.errstate(divide='ignore'):
        s = np.sum((2 * i - 1) * (np.log(z) + np.log(1 - z[..., ::-1])), axis=-1)
    return -n - s / n


def _ad_norm_p(A2, n):
    a = A2 * (1 + 0.75 / n + 2.25 / n ** 2)
    if a >= 0.6:
        p = math.exp(1.2937 - 5.709 * a + 0.0186 * a * a)
    elif a >= 0.34:
        p = math.exp(0.9177 - 4.279 * a - 1.38 * a * a)
    elif a >= 0.2:
        p = 1 - math.exp(-8.318 + 42.796 * a - 59.938 * a * a)
    else:
        p = 1 - math.exp(-13.436 + 101.14 * a - 223.73 * a * a)
    return min(1.0, max(0.0, p))


def _ad_exp_p(A2, n):
    a = A2 * (1 + 0.6 / n)
    if a < 0.26:
        p = 1 - math.exp(-12.2204 + 67.459 * a - 110.3 * a * a)
    elif a < 0.51:
        p = 1 - math.exp(-6.1327 + 20.218 * a - 18.663 * a * a)
    elif a < 0.95:
        p = math.exp(0.9209 - 3.353 * a + 0.300 * a * a)
    else:
        p = math.exp(0.731 - 3.009 * a + 0.15 * a * a)
    return min(1.0, max(0.0, p))


@bi('adtest', nout=4)
def adtest(nargout, *args):
    nargchk(args, 1, 10, 'adtest')
    st = _st()
    from scipy.optimize import brentq
    from .distributions import is_dist
    x = np.sort(_vec(args[0]))
    opts = _opts(args[1:], 'adtest', ())
    alpha = _alpha(opts, 'adtest')
    dist = opts.get('distribution', Char.of('norm'))
    n = x.size
    if is_dist(dist):
        z = np.clip(np.asarray(dist.cdf(x), float), 1e-300, 1 - 1e-16)
        A2 = float(_ad(z))
        null = _simulate(lambda rs, m_, n_: _ad(np.sort(rs.random_sample((m_, n_)), axis=1)), n, key='ad-known')
        p = _mc_p(null, A2)
        cv = float(np.quantile(null, 1 - alpha))
        return _pack(nargout, _h(p, alpha), p, A2, cv)
    name = sval(dist).lower()
    if name in ('norm', 'normal', 'logn', 'lognormal'):
        y = np.log(x) if name.startswith('logn') else x
        m, s = float(np.mean(y)), float(np.std(y, ddof=1))
        A2 = float(_ad(np.clip(st.norm.cdf(np.sort(y), m, s), 1e-300, 1 - 1e-16)))
        p = _ad_norm_p(A2, n)
        cv = brentq(lambda a: _ad_norm_p(a, n) - alpha, 1e-6, 50.0)
    elif name in ('exp', 'exponential'):
        A2 = float(_ad(np.clip(st.expon.cdf(x, scale=float(np.mean(x))), 1e-300, 1 - 1e-16)))
        p = _ad_exp_p(A2, n)
        cv = brentq(lambda a: _ad_exp_p(a, n) - alpha, 1e-6, 50.0)
    elif name in ('ev', 'extreme value', 'weibull', 'wbl'):
        y = np.log(x) if name in ('weibull', 'wbl') else x
        mu, sg = (float(v[0]) for v in _ev_fit(y))
        A2 = float(_ad(np.clip(_ev_cdf(np.sort(y), mu, sg), 1e-300, 1 - 1e-16)))

        def sim(rs, m_, n_):
            z = np.sort(np.log(rs.exponential(size=(m_, n_))), axis=1)
            a, b = _ev_fit(z)
            return _ad(np.clip(_ev_cdf(z, a[:, None], b[:, None]), 1e-300, 1 - 1e-16))
        null = _simulate(sim, n, key='ad-ev')
        p = _mc_p(null, A2)
        cv = float(np.quantile(null, 1 - alpha))
    else:
        raise err('stats:adtest:BadDistribution', "Distribution must be 'norm', 'exp', 'ev', 'logn', 'weibull' or a "
                  'probability distribution object.', 'adtest')
    return _pack(nargout, _h(p, alpha), p, A2, cv)


@bi('chi2gof', nout=3, aw=True)
async def chi2gof(nargout, *args):
    nargchk(args, 1, 20, 'chi2gof')
    st = _st()
    from .distributions import is_dist
    x = _vec(args[0])
    opts = _opts(args[1:], 'chi2gof', ())
    alpha = _alpha(opts, 'chi2gof')
    freq = _vec(opts['frequency']) if 'frequency' in opts else None
    emin = float(num(opts['emin'])) if 'emin' in opts else 5.0
    w = freq if freq is not None else np.ones(x.size)
    n = float(np.sum(w))
    if 'edges' in opts:
        edges = darr(opts['edges']).real.astype(float).reshape(-1)
    elif 'ctrs' in opts:
        c = darr(opts['ctrs']).real.astype(float).reshape(-1)
        mid = (c[:-1] + c[1:]) / 2
        edges = np.concatenate([[c[0] - (mid[0] - c[0])], mid, [c[-1] + (c[-1] - mid[-1])]])
    else:
        nb = int(num(opts['nbins'])) if 'nbins' in opts else 10
        lo, hi = float(np.min(x)), float(np.max(x))
        if lo == hi:
            lo, hi = lo - 0.5, hi + 0.5
        edges = np.linspace(lo, hi, nb + 1)
    O = np.histogram(x, bins=edges, weights=w)[0].astype(float)
    nparams = int(num(opts['nparams'])) if 'nparams' in opts else None
    if 'expected' in opts:
        E = darr(opts['expected']).real.astype(float).reshape(-1)
        if E.size != O.size:
            raise err('stats:chi2gof:BadExpected', f'Expected has {E.size} counts for {O.size} bins: give the bins too '
                      "('Ctrs' or 'Edges'), one for each expected count.", 'chi2gof')
        nparams = nparams or 0
    else:
        if 'cdf' in opts:
            spec = opts['cdf']
            first = spec.a.reshape(-1, order='F')[0] if type(spec) is Cell and spec.a.size else None
            if is_dist(spec):
                cdfv = spec.cdf(edges)
                k = 0 if spec.data is None else len(getattr(spec, 'values', []))
            elif isinstance(spec, FH) or isinstance(first, FH):
                # a handle, or a cell of a handle and its parameters (which count as estimated)
                extra = [] if isinstance(spec, FH) else list(spec.a.reshape(-1, order='F')[1:])
                cdfv = darr(await (spec if isinstance(spec, FH) else first).acall(1, out(edges.reshape(1, -1)), *extra))
                k = len(extra)
            else:
                raise err('stats:chi2gof:BadCdf', 'CDF must be a probability distribution object, a function handle, '
                          'or a cell of a function handle and its parameters.', 'chi2gof')
            nparams = k if nparams is None else nparams
        else:
            m, s = float(np.sum(w * x) / n), math.sqrt(float(np.sum(w * (x - np.sum(w * x) / n) ** 2) / (n - 1)))
            cdfv = st.norm.cdf(edges, m, s)
            nparams = 2 if nparams is None else nparams
        cdfv = np.array(cdfv, float).real.reshape(-1)
        if cdfv.size != edges.size:
            raise err('stats:chi2gof:BadCdf', 'The CDF must give one value for each bin edge.', 'chi2gof')
        cdfv[0], cdfv[-1] = 0.0, 1.0      # the outer bins take the tails
        E = n * np.diff(cdfv)
    # bins with too few expected join a neighbour: the tails inward, then
    # the smallest left with the smaller of its neighbours
    O, E, edges = list(O), list(E), list(edges)

    def join(a):
        """Bins a and a + 1 become one."""
        O[a] += O[a + 1]
        E[a] += E[a + 1]
        del O[a + 1], E[a + 1], edges[a + 1]
    while len(E) > 1 and E[0] < emin:
        join(0)
    while len(E) > 1 and E[-1] < emin:
        join(len(E) - 2)
    while len(E) > 2 and min(E) < emin:
        i = int(np.argmin(E))
        join(i - 1 if i == len(E) - 1 or (i > 0 and E[i - 1] < E[i + 1]) else i)
    O, E, edges = np.array(O), np.array(E), np.array(edges)
    chi = float(np.sum((O - E) ** 2 / E))
    df = len(E) - 1 - nparams
    if df <= 0:
        p = math.nan
        R.warn('stats:chi2gof:NoDF', 'There are not enough bins left for the test (no degrees of freedom).')
    else:
        p = float(st.chi2.sf(chi, df))
    stats = Struct.scalar({'chi2stat': chi, 'df': float(df), 'edges': out(edges.reshape(1, -1)),
                           'O': out(O.reshape(1, -1)), 'E': out(E.reshape(1, -1))})
    return _pack(nargout, _h(p, alpha), p, stats)


# ---- runs ---------------------------------------------------------------------------------------------------

def _runs_dist(n1, n0):
    """The exact null distribution of the number of runs of n1 ones and n0 zeros."""
    from math import comb
    total = comb(n1 + n0, n1)
    dist = {}
    for r in range(2, n1 + n0 + 1):
        if r % 2 == 0:
            k = r // 2
            c = 2 * comb(n1 - 1, k - 1) * comb(n0 - 1, k - 1) if k >= 1 else 0
        else:
            k = (r - 1) // 2
            c = comb(n1 - 1, k) * comb(n0 - 1, k - 1) + comb(n1 - 1, k - 1) * comb(n0 - 1, k)
        if c:
            dist[r] = c / total
    return dist


@bi('runstest', nout=3)
def runstest(nargout, *args):
    nargchk(args, 1, 10, 'runstest')
    st = _st()
    x = _vec(args[0])
    rest = list(args[1:])
    v = None
    if rest and not is_str(rest[0]):
        a = darr(rest.pop(0))
        v = float(a.reshape(-1)[0]) if a.size else None
    opts = _opts(rest, 'runstest', ('alpha', 'tail'))
    alpha, tail = _alpha(opts, 'runstest'), _tail(opts, 'runstest')
    if v is None:
        v = float(np.median(x))
    x = x[x != v]
    above = x > v
    n1, n0 = int(above.sum()), int((~above).sum())
    nruns = int(1 + np.sum(above[1:] != above[:-1])) if x.size else 0
    n = n1 + n0
    method = sval(opts['method']).lower() if 'method' in opts else ('exact' if n < 50 else 'approximate')
    mu = 1 + 2 * n1 * n0 / n if n else math.nan
    var = 2 * n1 * n0 * (2 * n1 * n0 - n) / (n * n * (n - 1)) if n > 1 else math.nan
    if tail == 'both':
        z = (nruns - mu - 0.5 * np.sign(nruns - mu)) / math.sqrt(var) if var and var > 0 else math.nan
    else:
        z = (nruns - mu + (-0.5 if tail == 'right' else 0.5)) / math.sqrt(var) if var and var > 0 else math.nan
    if method == 'exact' and n1 and n0:
        dist = _runs_dist(n1, n0)
        lo = sum(p_ for r_, p_ in dist.items() if r_ <= nruns)
        hi = sum(p_ for r_, p_ in dist.items() if r_ >= nruns)
        p = _p_from(lo, hi, tail)
    else:
        p = _p_from(float(st.norm.cdf(z)), float(st.norm.sf(z)), tail) if z == z else math.nan
    stats = Struct.scalar({'nruns': float(nruns), 'n1': float(n1), 'n0': float(n0), 'z': float(z)})
    return _pack(nargout, _h(p, alpha), p, stats)


# ---- analysis of variance ---------------------------------------------------------------------------------

def _anova_parts(cols):
    """F, p, the table's numbers and the pooled error of a one-way layout."""
    st = _st()
    alld = np.concatenate(cols)
    N, k = alld.size, len(cols)
    gm = float(np.mean(alld))
    ssb = float(sum(c.size * (np.mean(c) - gm) ** 2 for c in cols))
    ssw = float(sum(np.sum((c - np.mean(c)) ** 2) for c in cols))
    dfb, dfw = k - 1, N - k
    msb = ssb / dfb if dfb else math.nan
    msw = ssw / dfw if dfw else math.nan
    with np.errstate(all='ignore'):
        F = msb / msw if msw > 0 else math.nan
    p = float(st.f.sf(F, dfb, dfw)) if F == F else math.nan
    return F, p, (ssb, ssw, ssb + ssw, dfb, dfw, msb, msw), gm


def _table(rows):
    """A table as the language's ANOVA functions give it: a cell, header first."""
    a = np.empty((len(rows), len(rows[0])), object)
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            a[i, j] = Char.of(v) if isinstance(v, str) else (EMPTY() if v is None else float(v))
    return Cell(a)


def _show_table(title, rows):
    """An ANOVA table in the Command Window."""
    def cell(v, j):
        if v is None:
            return ''
        if isinstance(v, str):
            return v
        if j == 2:
            return f'{v:g}'
        return f'{v:.5g}'
    texts = [[cell(v, j) for j, v in enumerate(r)] for r in rows]
    w = [max(len(t[j]) for t in texts) for j in range(len(texts[0]))]
    lines = [f'  {title}', '']
    for i, t in enumerate(texts):
        lines.append('  ' + '  '.join(t[j].ljust(w[j]) if j == 0 else t[j].rjust(w[j]) for j in range(len(t))))
        if i == 0:
            lines.append('  ' + '-' * (sum(w) + 2 * (len(w) - 1)))
    R.write('\n'.join(lines) + '\n\n')


def _boxplot(cols, labels, title, ylabel=''):
    from .statplots import boxplot_groups
    boxplot_groups(cols, labels, title=title, ylabel=ylabel)


@bi('anova1', nout=3)
def anova1(nargout, *args):
    nargchk(args, 1, 3, 'anova1')
    rest = list(args)
    display = True
    if rest and is_str(rest[-1]) and sval(rest[-1]).lower() in ('on', 'off'):
        display = sval(rest.pop()).lower() == 'on'
    cols, labels = _grouped(rest, 'anova1')
    keep = [i for i, c in enumerate(cols) if c.size]
    cols, labels = [cols[i] for i in keep], [labels[i] for i in keep]
    F, p, (ssb, ssw, sst, dfb, dfw, msb, msw), _ = _anova_parts(cols)
    rows = [['Source', 'SS', 'df', 'MS', 'F', 'Prob>F'], ['Groups', ssb, dfb, msb, F, p],
            ['Error', ssw, dfw, msw, None, None], ['Total', sst, dfb + dfw, None, None, None]]
    stats = Struct.scalar({'gnames': Cell.of_list([Char.of(s) for s in labels], (len(labels), 1)),
                           'n': out(np.array([[c.size for c in cols]], float)), 'source': Char.of('anova1'),
                           'means': out(np.array([[np.mean(c) for c in cols]])), 'df': float(dfw), 's': math.sqrt(msw)})
    if display:
        _show_table('One-way ANOVA', rows)
        _boxplot(cols, labels, 'One-way ANOVA')
    return _pack(nargout, p, _table(rows), stats)


@bi('anova2', nout=3)
def anova2(nargout, *args):
    nargchk(args, 1, 3, 'anova2')
    st = _st()
    Y = darr(args[0]).real.astype(float)
    reps = int(num(args[1])) if len(args) > 1 and not is_str(args[1]) and np.size(darr(args[1])) else 1
    display = not (len(args) > 2 and sval(args[2]).lower() == 'off')
    r, c = Y.shape
    if r % reps:
        raise err('stats:anova2:BadReps', 'The number of rows must be a multiple of REPS.', 'anova2')
    if np.any(np.isnan(Y)):
        raise err('stats:anova2:NaNs', 'The data must have no missing values (NaN).', 'anova2')
    m = r // reps
    gm = float(Y.mean())
    colmeans = Y.mean(axis=0)
    cells = Y.reshape(m, reps, c)
    rowmeans = cells.mean(axis=(1, 2))
    cellmeans = cells.mean(axis=1)
    ssc = m * reps * float(np.sum((colmeans - gm) ** 2))
    ssr = c * reps * float(np.sum((rowmeans - gm) ** 2))
    sst = float(np.sum((Y - gm) ** 2))
    dfc, dfr = c - 1, m - 1
    if reps > 1:
        ssi = reps * float(np.sum((cellmeans - rowmeans.reshape(-1, 1) - colmeans.reshape(1, -1) + gm) ** 2))
        dfi = dfc * dfr
        sse = sst - ssc - ssr - ssi
        dfe = c * m * (reps - 1)
    else:
        ssi, dfi = 0.0, 0
        sse = sst - ssc - ssr
        dfe = dfc * dfr
    mse = sse / dfe if dfe else math.nan
    def fp(ss, df):
        ms = ss / df if df else math.nan
        F = ms / mse if mse and mse > 0 else math.nan
        return ms, F, float(st.f.sf(F, df, dfe)) if F == F else math.nan
    msc, Fc, pc = fp(ssc, dfc)
    msr, Fr, pr = fp(ssr, dfr)
    rows = [['Source', 'SS', 'df', 'MS', 'F', 'Prob>F'], ['Columns', ssc, dfc, msc, Fc, pc], ['Rows', ssr, dfr, msr, Fr, pr]]
    ps = [pc, pr]
    if reps > 1:
        msi, Fi, pi_ = fp(ssi, dfi)
        rows.append(['Interaction', ssi, dfi, msi, Fi, pi_])
        ps.append(pi_)
    rows += [['Error', sse, dfe, mse, None, None], ['Total', sst, r * c - 1, None, None, None]]
    stats = Struct.scalar({'source': Char.of('anova2'), 'sigmasq': mse, 'colmeans': out(colmeans.reshape(1, -1)),
                           'coln': float(r), 'rowmeans': out(rowmeans.reshape(1, -1)), 'rown': float(c * reps),
                           'inter': float(reps > 1), 'pval': ps[2] if reps > 1 else math.nan, 'df': float(dfe)})
    if display:
        _show_table('Two-way ANOVA', rows)
    return _pack(nargout, out(np.array([ps])), _table(rows), stats)


@bi('kruskalwallis', nout=3)
def kruskalwallis(nargout, *args):
    nargchk(args, 1, 3, 'kruskalwallis')
    st = _st()
    rest = list(args)
    display = True
    if rest and is_str(rest[-1]) and sval(rest[-1]).lower() in ('on', 'off'):
        display = sval(rest.pop()).lower() == 'on'
    cols, labels = _grouped(rest, 'kruskalwallis')
    keep = [i for i, c in enumerate(cols) if c.size]
    cols, labels = [cols[i] for i in keep], [labels[i] for i in keep]
    alld = np.concatenate(cols)
    N, k = alld.size, len(cols)
    ranks = st.rankdata(alld)
    rc, i = [], 0
    for c in cols:
        rc.append(ranks[i:i + c.size])
        i += c.size
    gm = (N + 1) / 2
    ssb = float(sum(r.size * (r.mean() - gm) ** 2 for r in rc))
    sst = float(np.sum((ranks - gm) ** 2))
    ssw = sst - ssb
    _, counts = np.unique(alld, return_counts=True)
    sumt = float(np.sum(counts ** 3 - counts))
    H = ssb / (sst / (N - 1)) if sst > 0 and N > 1 else math.nan
    p = float(st.chi2.sf(H, k - 1)) if k > 1 else math.nan

    def per(a, b):
        return a / b if b else math.nan
    rows = [['Source', 'SS', 'df', 'MS', 'Chi-sq', 'Prob>Chi-sq'], ['Groups', ssb, k - 1, per(ssb, k - 1), H, p],
            ['Error', ssw, N - k, per(ssw, N - k), None, None], ['Total', sst, N - 1, None, None, None]]
    stats = Struct.scalar({'gnames': Cell.of_list([Char.of(s) for s in labels], (k, 1)),
                           'n': out(np.array([[c.size for c in cols]], float)), 'source': Char.of('kruskalwallis'),
                           'meanranks': out(np.array([[r.mean() for r in rc]])), 'sumt': sumt})
    if display:
        _show_table('Kruskal-Wallis ANOVA', rows)
        _boxplot(cols, labels, 'Kruskal-Wallis ANOVA')
    return _pack(nargout, p, _table(rows), stats)


@bi('friedman', nout=3)
def friedman(nargout, *args):
    nargchk(args, 1, 3, 'friedman')
    st = _st()
    X = darr(args[0]).real.astype(float)
    if len(args) > 1 and not is_str(args[1]) and np.size(darr(args[1])) > 1:
        raise err('stats:friedman:BadReps', 'reps must be a positive whole number.', 'friedman')
    reps = int(num(args[1])) if len(args) > 1 and not is_str(args[1]) and np.size(darr(args[1])) else 1
    display = not (len(args) > 2 and sval(args[2]).lower() == 'off')
    if X.ndim != 2:
        raise err('stats:friedman:BadData', 'X must be a matrix.', 'friedman')
    r, c = X.shape
    if reps < 1 or r % reps or r == 0 or c < 2:
        raise err('stats:friedman:BadData', 'X needs at least two columns, and a number of rows that reps divides.', 'friedman')
    m = r // reps
    ranks = np.empty_like(X)
    for b in range(m):
        block = X[b * reps:(b + 1) * reps]
        ranks[b * reps:(b + 1) * reps] = st.rankdata(block.reshape(-1)).reshape(block.shape)
    gm = (c * reps + 1) / 2
    colmeans = ranks.mean(axis=0)
    ssc = m * reps * float(np.sum((colmeans - gm) ** 2))
    sst = float(np.sum((ranks - gm) ** 2))
    if reps > 1:
        cells = ranks.reshape(m, reps, c).mean(axis=1)
        ssi = reps * float(np.sum((cells - cells.mean(axis=1, keepdims=True) - colmeans.reshape(1, -1) + gm) ** 2))
    else:
        ssi = 0.0
    sse = sst - ssc - ssi
    sigma2 = sst / (m * (reps * c - 1)) if m else math.nan
    chi = ssc / sigma2 if sigma2 > 0 else math.nan
    p = float(st.chi2.sf(chi, c - 1))
    rows = [['Source', 'SS', 'df', 'MS', 'Chi-sq', 'Prob>Chi-sq'], ['Columns', ssc, c - 1, ssc / (c - 1), chi, p]]
    if reps > 1:
        rows.append(['Interaction', ssi, (c - 1) * (m - 1), ssi / max(1, (c - 1) * (m - 1)), None, None])
    dfe = r * c - 1 - (c - 1) - ((c - 1) * (m - 1) if reps > 1 else 0)
    rows += [['Error', sse, dfe, sse / dfe if dfe else math.nan, None, None], ['Total', sst, r * c - 1, None, None, None]]
    stats = Struct.scalar({'source': Char.of('friedman'), 'n': float(m), 'meanranks': out(colmeans.reshape(1, -1)),
                           'sigma': math.sqrt(sigma2)})
    if display:
        _show_table("Friedman's ANOVA", rows)
    return _pack(nargout, p, _table(rows), stats)


@bi('multcompare', nout=4)
def multcompare(nargout, *args):
    nargchk(args, 1, 12, 'multcompare')
    st = _st()
    S = args[0]
    if type(S) is not Struct or 'source' not in S.f:
        raise err('stats:multcompare:BadStats', 'STATS must be the third output of anova1, kruskalwallis or friedman.', 'multcompare')
    opts = _opts(args[1:], 'multcompare', ())
    alpha = _alpha(opts, 'multcompare')
    ctype = sval(opts['ctype']).lower() if 'ctype' in opts else 'tukey-kramer'
    display = sval(opts['display']).lower() != 'off' if 'display' in opts else True
    src = S.get1('source').str()
    if src == 'anova1':
        means = darr(S.get1('means')).reshape(-1)
        n = darr(S.get1('n')).reshape(-1)
        df = float(S.get1('df'))
        s = float(S.get1('s'))
        se_one = s / np.sqrt(n)
        names = cellstr_list(S.get1('gnames'))

        def se_pair(i, j):
            return s * math.sqrt(1 / n[i] + 1 / n[j])
    elif src == 'kruskalwallis':
        means = darr(S.get1('meanranks')).reshape(-1)
        n = darr(S.get1('n')).reshape(-1)
        N = n.sum()
        sumt = float(S.get1('sumt'))
        v = N * (N + 1) / 12 * (1 - sumt / (N ** 3 - N))
        df = math.inf
        se_one = np.sqrt(v / n)
        names = cellstr_list(S.get1('gnames'))

        def se_pair(i, j):
            return math.sqrt(v * (1 / n[i] + 1 / n[j]))
    elif src == 'friedman':
        means = darr(S.get1('meanranks')).reshape(-1)
        nb = float(S.get1('n'))
        sig = float(S.get1('sigma'))
        df = math.inf
        se_one = np.full(means.size, sig / math.sqrt(nb))
        names = [str(i + 1) for i in range(means.size)]

        def se_pair(i, j):
            return sig * math.sqrt(2 / nb)
    else:
        raise err('stats:multcompare:BadStats', f"multcompare cannot use STATS from {src}.", 'multcompare')
    k = means.size
    m_pairs = k * (k - 1) / 2

    def crit():
        if ctype in ('tukey-kramer', 'hsd'):
            q = st.studentized_range.ppf(1 - alpha, k, df if df != math.inf else 1e6)
            return q / math.sqrt(2)
        if ctype == 'bonferroni':
            return st.t.ppf(1 - alpha / (2 * m_pairs), df) if df != math.inf else st.norm.ppf(1 - alpha / (2 * m_pairs))
        if ctype == 'dunn-sidak':
            a = 1 - (1 - alpha) ** (1 / m_pairs)
            return st.t.ppf(1 - a / 2, df) if df != math.inf else st.norm.ppf(1 - a / 2)
        if ctype == 'lsd':
            return st.t.ppf(1 - alpha / 2, df) if df != math.inf else st.norm.ppf(1 - alpha / 2)
        if ctype == 'scheffe':
            return math.sqrt((k - 1) * st.f.ppf(1 - alpha, k - 1, df if df != math.inf else 1e6))
        raise err('stats:multcompare:BadCType', "CType must be 'tukey-kramer', 'bonferroni', 'dunn-sidak', 'lsd' or 'scheffe'.", 'multcompare')

    def pval(t):
        t = abs(t)
        d_ = df if df != math.inf else 1e6
        if ctype in ('tukey-kramer', 'hsd'):
            return float(st.studentized_range.sf(t * math.sqrt(2), k, d_))
        p2 = 2 * float(st.t.sf(t, d_))
        if ctype == 'bonferroni':
            return min(1.0, p2 * m_pairs)
        if ctype == 'dunn-sidak':
            return 1 - (1 - p2) ** m_pairs
        if ctype == 'scheffe':
            return float(st.f.sf(t * t / (k - 1), k - 1, d_))
        return p2
    rows = []
    c0 = crit()
    for i in range(k):
        for j in range(i + 1, k):
            d = means[i] - means[j]
            se = se_pair(i, j)
            rows.append([i + 1, j + 1, d - c0 * se, d, d + c0 * se, pval(d / se) if se > 0 else math.nan])
    c = out(np.array(rows, float).reshape(-1, 6))
    M = out(np.column_stack([means, se_one]))
    gn = Cell.of_list([Char.of(s) for s in names], (k, 1))
    h = EMPTY()
    if display:
        # intervals of half-width c0 se / sqrt(2) miss each other where the
        # pair differs (exactly so for groups of equal size)
        from .statplots import comparison_plot
        h = comparison_plot(means, c0 * se_one / math.sqrt(2), names, 'Comparison intervals',
                            'Mean ranks' if src != 'anova1' else 'Means')
    return _pack(nargout, c, M, h, gn)


# ---- contingency tables ----------------------------------------------------------------------------------------

@bi('crosstab', nout=4)
def crosstab(nargout, *args):
    nargchk(args, 1, 10, 'crosstab')
    st = _st()
    if len(args) == 1:
        raise err('stats:crosstab:NeedTwo', 'crosstab needs at least two grouping variables.', 'crosstab')
    n = _count(args[0])
    parts = [groups(a, n, 'crosstab') for a in args]
    keep = np.all(np.array([p[1] for p in parts]) >= 0, axis=0)
    shape = tuple(len(p[0]) for p in parts)
    tbl = np.zeros(shape)
    for i in np.flatnonzero(keep):
        tbl[tuple(p[1][i] for p in parts)] += 1
    E = np.ones(shape) * tbl.sum()
    for ax in range(len(shape)):
        marg = tbl.sum(axis=tuple(a for a in range(len(shape)) if a != ax)) / tbl.sum()
        E = E * marg.reshape([-1 if a == ax else 1 for a in range(len(shape))])
    with np.errstate(divide='ignore', invalid='ignore'):
        chi = float(np.nansum((tbl - E) ** 2 / E))
    df = int(np.prod(shape) - 1 - sum(s - 1 for s in shape))
    p = float(st.chi2.sf(chi, df)) if df > 0 else math.nan
    L = max(shape)
    labels = np.empty((L, len(parts)), object)
    for j, (labs, _) in enumerate(parts):
        for i in range(L):
            labels[i, j] = Char.of(labs[i]) if i < len(labs) else EMPTY()
    return _pack(nargout, out(tbl), chi, p, Cell(labels))


@bi('fishertest', nout=3)
def fishertest(nargout, *args):
    nargchk(args, 1, 5, 'fishertest')
    st = _st()
    x = darr(args[0]).real.astype(float)
    if x.shape != (2, 2) or np.any(x < 0) or np.any(x != np.floor(x)):
        raise err('stats:fishertest:BadData', 'X must be a 2-by-2 table of nonnegative whole counts.', 'fishertest')
    opts = _opts(args[1:], 'fishertest', ())
    alpha, tail = _alpha(opts, 'fishertest'), _tail(opts, 'fishertest')
    alt = {'both': 'two-sided', 'right': 'greater', 'left': 'less'}[tail]
    p = float(st.fisher_exact(x, alternative=alt).pvalue)
    a, b, c, d = x[0, 0], x[0, 1], x[1, 0], x[1, 1]
    with np.errstate(divide='ignore', invalid='ignore'):
        orr = a * d / (b * c) if b * c > 0 else (math.inf if a * d > 0 else math.nan)
        se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d) if min(a, b, c, d) > 0 else math.inf
    z = float(st.norm.ppf(1 - alpha / 2))
    if np.isfinite(se) and orr > 0 and np.isfinite(orr):
        ci = [orr * math.exp(-z * se), orr * math.exp(z * se)]
    else:
        ci = [0.0, math.inf]
    stats = Struct.scalar({'OddsRatio': float(orr), 'ConfidenceInterval': out(np.array([ci]))})
    return _pack(nargout, _h(p, alpha), p, stats)
