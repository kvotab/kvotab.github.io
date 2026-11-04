"""Econometrics: sample autocorrelations (autocorr, parcorr, crosscorr), the
unit-root and stationarity tests (adftest, pptest, kpsstest), tests of
residuals (lbqtest, archtest), the variance ratio test, the Engle-Granger
cointegration test, the likelihood tests (lratiotest, waldtest, lmtest),
information criteria (aicbic), hpfilter and lagmatrix.

The tau statistics' p-values and critical values come from MacKinnon's
response surfaces (J. G. MacKinnon, "Approximate asymptotic distribution
functions for unit-root and cointegration tests", Journal of Business &
Economic Statistics 12 (1994) 167-176), with his coefficients as statsmodels
(BSD-3-Clause) tabulates them; the normalized-bias (t2) and F statistics'
from their distributions under the null, simulated here with a fixed seed;
the KPSS statistic's from the table of Kwiatkowski, Phillips, Schmidt and
Shin (1992).
"""
import math

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, darr, out, opt_str, is_str, sval, num
from ..values import MError, Char, Cell, Struct, EMPTY, numel, py_str
from .. import runtime as R


def bi(*names, **kw):
    """Registered as builtins are, with what NumPy or SciPy refuses told as the function's own error."""
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'econ:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _st():
    import scipy.stats as st
    return st


def _series(v, fn, what='y'):
    """A series as a column of numbers, NaN left out (a vector)."""
    a = np.asarray(darr(v, fn), float)
    if a.ndim > 2 or (a.ndim == 2 and min(a.shape) > 1):
        raise err(f'econ:{fn}:NotVector', f'{what} is a vector.', fn)
    return a.reshape(-1)


def _pairs(args, fn, names):
    """Positional inputs, then Name, Value pairs (any case) among names."""
    pos, opts = [], {}
    k = 0
    args = list(args)
    while k < len(args):
        o = opt_str(args[k])
        if o is not None and o.lower() in names and k + 1 < len(args):
            opts[o.lower()] = args[k + 1]
            k += 2
            continue
        if opts:
            raise err(f'econ:{fn}:InvalidOption', f"'{o if o is not None else '?'}' is not an option of {fn}.", fn)
        pos.append(args[k])
        k += 1
    return pos, opts


def _cases(opts, keys, fn):
    """The tests asked for: options given as vectors (or cells) give one test each, a single value applies to all."""
    vals = {}
    n = 1
    for k in keys:
        if k not in opts:
            continue
        v = opts[k]
        if type(v) is Cell:
            items = [py_str(x) if is_str(x) else x for x in v.a.reshape(-1, order='F')]
        elif is_str(v):
            items = [py_str(v)]
        else:
            a = np.asarray(darr(v)).reshape(-1)
            items = [x.item() for x in a]
        if not items:
            raise err(f'econ:{fn}:EmptyOption', f'The option {k} has no value.', fn)
        vals[k] = items
        if len(items) > 1:
            if n > 1 and len(items) != n:
                raise err(f'econ:{fn}:OptionSizes', 'Options given as vectors have the same length.', fn)
            n = len(items)
    return n, [{k: (v[i] if len(v) > 1 else v[0]) for k, v in vals.items()} for i in range(n)]


def _outs(nargout, cols, row=True):
    """[h, pValue, stat, cValue, ...] as rows over the tests (logical h)."""
    res = []
    for k, c in enumerate(cols):
        if k == 0:
            res.append(out(np.array([c], bool)) if len(c) > 1 else bool(c[0]))
        elif all(isinstance(x, (float, int, np.floating)) for x in c):
            res.append(out(np.array([c], float)) if len(c) > 1 else float(c[0]))
        else:
            res.append(c[0] if len(c) == 1 else _struct_row(c))
    n = max(nargout, 1)
    return tuple(res[:n]) if n > 1 else res[0]


def _struct_row(items):
    keys = list(items[0].f.keys())
    S = Struct.empty((1, len(items)), tuple(keys))
    for i, s in enumerate(items):
        for k in keys:
            S.f[k][0, i] = s.f[k][0, 0]
    return S


def _alpha(v, fn):
    a = float(v)
    if not 0.001 <= a <= 0.999:
        raise err(f'econ:{fn}:InvalidAlpha', 'alpha is from 0.001 to 0.999.', fn)
    return a


# ---- sample correlations ---------------------------------------------------------------------------------------------------

def _acf(y, nlags):
    d = y - y.mean()
    n = y.size
    c0 = d @ d / n
    return np.array([(d[:n - k] @ d[k:]) / n / c0 if c0 > 0 else np.nan for k in range(nlags + 1)])


def _corr_plot(lags, vals, bounds, title, ylabel, tail_from=None):
    b = lambda name, *a: R._builtin(name, *a)
    h = b('stem', out(np.asarray(lags, float).reshape(-1, 1)), out(np.asarray(vals, float).reshape(-1, 1)), Char.of('filled'))
    b('hold', Char.of('on'))
    lo, hi = float(np.min(lags)), float(np.max(lags))
    if bounds is not None:
        x0 = lo if tail_from is None else tail_from
        for v in bounds:
            b('plot', out(np.array([[x0], [hi]])), out(np.array([[v], [v]])), Char.of('-'), Char.of('Color'), out(np.array([[0.85, 0.33, 0.1]])))
    b('hold', Char.of('off'))
    b('title', Char.of(title))
    b('xlabel', Char.of('Lag'))
    b('ylabel', Char.of(ylabel))
    return h


def _numlags(opts, n, fn, default=20):
    if 'numlags' in opts:
        k = float(num(opts['numlags']))
        if not (0 <= k < n and k == int(k)):
            raise err(f'econ:{fn}:InvalidNumLags', f'NumLags is a whole number from 0 to {n - 1}.', fn)
        return int(k)
    return int(min(default, n - 1))


@bi('autocorr', nout=3, arr=False)
def autocorr(nargout, *args):
    """[acf, lags, bounds] = autocorr(y, 'NumLags', k, 'NumMA', q, 'NumSTD',
    s): the sample autocorrelation of y at lags 0 to k (20), with bounds for
    the hypothesis of an MA(q) process (Bartlett's formula); without
    outputs, a stem plot with the bounds."""
    nargchk(args, 1, 7, 'autocorr')
    pos, opts = _pairs(args, 'autocorr', ('numlags', 'numma', 'numstd'))
    if len(pos) > 1:
        # the older positional form: autocorr(y, numLags, numMA, numSTD)
        for k, key in zip(pos[1:], ('numlags', 'numma', 'numstd')):
            if numel(k):
                opts[key] = k
    y = _series(pos[0], 'autocorr')
    y = y[np.isfinite(y)]
    n = y.size
    if n < 2:
        raise err('econ:autocorr:TooFew', 'y has at least 2 values.', 'autocorr')
    k = _numlags(opts, n, 'autocorr')
    q = int(num(opts['numma'])) if 'numma' in opts else 0
    if not 0 <= q < max(k, 1) + (1 if k == 0 else 0):
        raise err('econ:autocorr:InvalidNumMA', 'NumMA is a whole number below NumLags.', 'autocorr')
    s = float(num(opts['numstd'])) if 'numstd' in opts else 2.0
    if s < 0:
        raise err('econ:autocorr:InvalidNumSTD', 'NumSTD is a nonnegative number.', 'autocorr')
    r = _acf(y, k)
    se = math.sqrt((1 + 2 * float(np.sum(r[1:q + 1] ** 2))) / n)
    bounds = np.array([[s * se], [-s * se]])
    lags = np.arange(k + 1, dtype=float).reshape(-1, 1)
    if nargout == 0:
        _corr_plot(lags, r, bounds.reshape(-1), 'Sample Autocorrelation Function', 'Sample Autocorrelation', tail_from=q + 0.5 if q else None)
        return None
    vals = (out(r.reshape(-1, 1)), out(lags), out(bounds))
    return vals[:nargout] if nargout > 1 else vals[0]


@bi('parcorr', nout=3, arr=False)
def parcorr(nargout, *args):
    """[pacf, lags, bounds] = parcorr(y, 'NumLags', k, 'NumAR', p, 'NumSTD',
    s, 'Method', 'ols' or 'yule-walker'): the sample partial
    autocorrelation of y; bounds +-s/sqrt(n) for lags past p."""
    nargchk(args, 1, 9, 'parcorr')
    pos, opts = _pairs(args, 'parcorr', ('numlags', 'numar', 'numstd', 'method'))
    if len(pos) > 1:
        for k, key in zip(pos[1:], ('numlags', 'numar', 'numstd')):
            if numel(k):
                opts[key] = k
    y = _series(pos[0], 'parcorr')
    y = y[np.isfinite(y)]
    n = y.size
    if n < 3:
        raise err('econ:parcorr:TooFew', 'y has at least 3 values.', 'parcorr')
    k = _numlags(opts, n, 'parcorr', 20)
    k = min(k, n - 2) if 'numlags' not in opts else k
    p = int(num(opts['numar'])) if 'numar' in opts else 0
    s = float(num(opts['numstd'])) if 'numstd' in opts else 2.0
    method = (opt_str(opts['method']) or 'ols').lower() if 'method' in opts else 'ols'
    if method not in ('ols', 'yule-walker'):
        raise err('econ:parcorr:InvalidMethod', "Method is 'ols' or 'yule-walker'.", 'parcorr')
    pacf = np.zeros(k + 1)
    pacf[0] = 1.0
    if method == 'ols':
        for m in range(1, k + 1):
            # y(t) on a constant and y(t-1) ... y(t-m): the last coefficient
            X = np.column_stack([np.ones(n - m)] + [y[m - j:n - j] for j in range(1, m + 1)])
            c, *_ = np.linalg.lstsq(X, y[m:], rcond=None)
            pacf[m] = c[-1]
    else:
        from scipy.linalg import solve_toeplitz
        r = _acf(y, k)
        for m in range(1, k + 1):
            phi = solve_toeplitz(r[:m], r[1:m + 1])
            pacf[m] = phi[-1]
    se = 1 / math.sqrt(n)
    bounds = np.array([[s * se], [-s * se]])
    lags = np.arange(k + 1, dtype=float).reshape(-1, 1)
    if nargout == 0:
        _corr_plot(lags, pacf, bounds.reshape(-1), 'Sample Partial Autocorrelation Function', 'Sample Partial Autocorrelation', tail_from=p + 0.5 if p else None)
        return None
    vals = (out(pacf.reshape(-1, 1)), out(lags), out(bounds))
    return vals[:nargout] if nargout > 1 else vals[0]


@bi('crosscorr', nout=3, arr=False)
def crosscorr(nargout, *args):
    """[xcf, lags, bounds] = crosscorr(y1, y2, 'NumLags', k, 'NumSTD', s):
    the sample cross-correlation of y1(t+k) with y2(t) at lags -k to k (20),
    with bounds +-s/sqrt(n)."""
    nargchk(args, 2, 6, 'crosscorr')
    pos, opts = _pairs(args, 'crosscorr', ('numlags', 'numstd'))
    if len(pos) > 2:
        for k, key in zip(pos[2:], ('numlags', 'numstd')):
            if numel(k):
                opts[key] = k
    y1, y2 = _series(pos[0], 'crosscorr', 'y1'), _series(pos[1], 'crosscorr', 'y2')
    if y1.size != y2.size:
        raise err('econ:crosscorr:Lengths', 'y1 and y2 have the same length.', 'crosscorr')
    keep = np.isfinite(y1) & np.isfinite(y2)
    y1, y2 = y1[keep], y2[keep]
    n = y1.size
    if n < 2:
        raise err('econ:crosscorr:TooFew', 'The series have at least 2 values.', 'crosscorr')
    k = _numlags(opts, n, 'crosscorr')
    s = float(num(opts['numstd'])) if 'numstd' in opts else 2.0
    a, b = y1 - y1.mean(), y2 - y2.mean()
    den = math.sqrt((a @ a) * (b @ b))
    xcf = []
    for L in range(-k, k + 1):
        v = a[L:] @ b[:n - L] if L >= 0 else a[:n + L] @ b[-L:]
        xcf.append(v / den if den > 0 else np.nan)
    lags = np.arange(-k, k + 1, dtype=float).reshape(-1, 1)
    bounds = np.array([[s / math.sqrt(n)], [-s / math.sqrt(n)]])
    if nargout == 0:
        _corr_plot(lags, xcf, bounds.reshape(-1), 'Sample Cross Correlation Function', 'Sample Cross Correlation')
        return None
    vals = (out(np.array(xcf).reshape(-1, 1)), out(lags), out(bounds))
    return vals[:nargout] if nargout > 1 else vals[0]


# ---- MacKinnon's tau distributions --------------------------------------------------------------------------------------------
# For N = 1 to 6 series: where the small-p and large-p surfaces meet, where the p-value is 0 or 1, and the coefficients
# (polynomials in the statistic of the probit of p).

_TAU_STAR = {'n': [-1.04, -1.53, -2.68, -3.09, -3.07, -3.77], 'c': [-1.61, -2.62, -3.13, -3.47, -3.78, -3.93],
             'ct': [-2.89, -3.19, -3.50, -3.65, -3.80, -4.36], 'ctt': [-3.21, -3.51, -3.81, -3.83, -4.12, -4.63]}
_TAU_MIN = {'n': [-19.04, -19.62, -21.21, -23.25, -21.63, -25.74], 'c': [-18.83, -18.86, -23.48, -28.07, -25.96, -23.27],
            'ct': [-16.18, -21.15, -25.37, -26.63, -26.53, -26.18], 'ctt': [-17.17, -21.1, -24.33, -24.03, -24.33, -28.22]}
_TAU_MAX = {'n': [np.inf, 1.51, 0.86, 0.88, 1.05, 1.24], 'c': [2.74, 0.92, 0.55, 0.61, 0.79, 1],
            'ct': [0.7, 0.63, 0.71, 0.93, 1.19, 1.42], 'ctt': [0.54, 0.79, 1.08, 1.43, 3.49, 1.92]}
_SMALLP = {
    'n': [[0.6344, 1.2378, 3.2496], [1.9129, 1.3857, 3.5322], [2.7648, 1.4502, 3.4186], [3.4336, 1.4835, 3.19], [4.0999, 1.5533, 3.59], [4.5388, 1.5344, 2.9807]],
    'c': [[2.1659, 1.4412, 3.8269], [2.92, 1.5012, 3.9796], [3.4699, 1.4856, 3.164], [3.9673, 1.4777, 2.6315], [4.5509, 1.5338, 2.9545], [5.1399, 1.6036, 3.4445]],
    'ct': [[3.2512, 1.6047, 4.9588], [3.6646, 1.5419, 3.6448], [4.0983, 1.5173, 2.9898], [4.5844, 1.5338, 2.8796], [5.0722, 1.5634, 2.9472], [5.53, 1.5914, 3.0392]],
    'ctt': [[4.0003, 1.658, 4.8288], [4.3534, 1.6016, 3.7947], [4.7343, 1.5768, 3.2396], [5.214, 1.6077, 3.3449], [5.6481, 1.6274, 3.3455], [5.9296, 1.5929, 2.8223]]}
_LARGEP = {
    'n': [[0.4797, 9.3557, -0.6999, 3.3066], [1.5578, 8.558, -2.083, -3.3549], [2.2268, 6.8093, -3.2362, -5.4448], [2.7654, 6.4502, -3.0811, -4.4946],
          [3.2684, 6.8051, -2.6778, -3.4972], [3.7268, 7.167, -2.3648, -2.8288]],
    'c': [[1.7339, 9.3202, -1.2745, -1.0368], [2.1945, 6.4695, -2.9198, -4.2377], [2.5893, 4.5168, -3.6529, -5.0074], [3.0387, 4.5452, -3.3666, -4.1921],
          [3.5049, 5.2098, -2.9158, -3.3468], [3.9489, 5.8933, -2.5359, -2.721]],
    'ct': [[2.5261, 6.1654, -3.7956, -6.0285], [2.85, 5.272, -3.6622, -5.1695], [3.221, 5.255, -3.2685, -4.1501], [3.652, 5.9758, -2.7483, -3.2081],
           [4.0712, 6.6428, -2.3464, -2.546], [4.4735, 7.1757, -2.0681, -2.1196]],
    'ctt': [[3.0778, 4.9529, -4.1477, -5.9359], [3.4713, 5.967, -3.2507, -4.2286], [3.8637, 6.7852, -2.6286, -3.1381], [4.2736, 7.6199, -2.1534, -2.4026],
            [4.6679, 8.2618, -1.822, -1.9147], [5.0009, 8.3735, -1.6994, -1.6928]]}


def tau_p(stat, reg, N=1):
    """MacKinnon's (1994) p-value of a tau statistic: the left tail."""
    i = N - 1
    if stat > _TAU_MAX[reg][i]:
        return 1.0
    if stat < _TAU_MIN[reg][i]:
        return 0.0
    if stat <= _TAU_STAR[reg][i]:
        c = np.array(_SMALLP[reg][i]) * np.array([1, 1, 1e-2])
    else:
        c = np.array(_LARGEP[reg][i]) * np.array([1, 1e-1, 1e-1, 1e-2])
    return float(_st().norm.cdf(np.polyval(c[::-1], stat)))


def tau_crit(alpha, reg, N=1):
    """The tau statistic whose p-value is alpha (the surfaces inverted)."""
    from scipy.optimize import brentq
    lo, hi = _TAU_MIN[reg][N - 1] + 1e-9, min(_TAU_MAX[reg][N - 1], 10.0) - 1e-9
    if tau_p(lo, reg, N) > alpha:
        return lo
    if tau_p(hi, reg, N) < alpha:
        return hi
    return float(brentq(lambda s: tau_p(s, reg, N) - alpha, lo, hi, xtol=1e-10))


# ---- simulated null distributions (the normalized bias and F) --------------------------------------------------------------

_NULLS = {}


def _null_draws(kind, reg, n):
    """The statistic's draws under a unit root for samples of n: a random walk regressed as Dickey and Fuller did, 20000
    times with a fixed seed (cached)."""
    key = (kind, reg, n)
    if key in _NULLS:
        return _NULLS[key]
    rs = np.random.default_rng(20261104)
    M = 20000
    m = max(n, 10)
    draws = []
    for start in range(0, M, 2000):
        k = min(2000, M - start)
        e = rs.standard_normal((k, m + 1))
        y = np.cumsum(e, axis=1)
        ylag, yt = y[:, :-1], y[:, 1:]
        cols = [ylag]
        if reg in ('c', 'ct'):
            cols.append(np.ones_like(ylag))
        if reg == 'ct':
            cols.append(np.broadcast_to(np.arange(1, m + 1, dtype=float), ylag.shape))
        X = np.stack(cols, axis=2)                         # k x m x p
        XtX = np.einsum('kti,ktj->kij', X, X)
        Xty = np.einsum('kti,kt->ki', X, yt)
        b = np.linalg.solve(XtX, Xty[..., None])[..., 0]
        res = yt - np.einsum('kti,ki->kt', X, b)
        p = X.shape[2]
        s2 = np.sum(res ** 2, axis=1) / (m - p)
        if kind == 't2':
            draws.append(m * (b[:, 0] - 1))
        else:
            # F of the joint hypothesis: the unit root with no constant ('c') or no trend ('ct')
            if reg == 'c':
                rest = yt - ylag
                ssr_r = np.sum(rest ** 2, axis=1)
                q = 2
            else:
                d = yt - ylag
                ssr_r = np.sum((d - d.mean(axis=1, keepdims=True)) ** 2, axis=1)
                q = 2
            ssr_u = np.sum(res ** 2, axis=1)
            draws.append(((ssr_r - ssr_u) / q) / s2)
    d = np.sort(np.concatenate(draws))
    _NULLS[key] = d
    return d


def _sim_p(stat, draws, upper):
    """(k + 1)/(M + 1) of the draws as far out as stat or farther."""
    k = int(np.sum(draws >= stat)) if upper else int(np.sum(draws <= stat))
    return (k + 1) / (draws.size + 1)


def _sim_crit(alpha, draws, upper):
    return float(np.quantile(draws, 1 - alpha if upper else alpha))


# ---- the Dickey-Fuller regression -------------------------------------------------------------------------------------------

_MODELS = {'ar': 'n', 'ard': 'c', 'ts': 'ct'}


def _df_regression(y, lags, model):
    """y(t) on y(t-1), the lagged differences and the deterministic terms: (coefficients, their covariance, residuals,
    the effective sample, the regressor matrix and the response)."""
    dy = np.diff(y)
    T = y.size
    n = T - 1 - lags
    if n <= lags + 3:
        raise err('econ:adftest:TooFew', 'The series is too short for that many lags.', 'adftest')
    cols = [y[lags:T - 1]]
    names = ['a']
    if model in ('ard', 'ts'):
        cols.append(np.ones(n))
        names.append('c')
    if model == 'ts':
        cols.append(np.arange(lags + 2, T + 1, dtype=float))
        names.append('d')
    for j in range(1, lags + 1):
        cols.append(dy[lags - j:T - 1 - j])
        names.append(f'b{j}')
    X = np.column_stack(cols)
    yt = y[lags + 1:]
    b, *_ = np.linalg.lstsq(X, yt, rcond=None)
    res = yt - X @ b
    df = n - X.shape[1]
    s2 = res @ res / df
    cov = s2 * np.linalg.inv(X.T @ X)
    return b, cov, res, n, X, yt, names


def _reg_struct(b, cov, res, n, X, names, model):
    se = np.sqrt(np.diag(cov))
    k = len(b)
    sse = float(res @ res)
    df = n - k
    s2 = sse / df
    ll = -n / 2 * (math.log(2 * math.pi) + math.log(sse / n) + 1)
    yv = X @ b + res
    sst = float(np.sum((yv - yv.mean()) ** 2))
    rsq = 1 - sse / sst if sst > 0 else np.nan
    return Struct.scalar({'num': float(n), 'size': float(n), 'names': Cell.of_list([Char.of(x) for x in names], (k, 1)),
                          'coeff': out(b.reshape(-1, 1)), 'se': out(se.reshape(-1, 1)), 'Cov': out(cov),
                          'tStats': Struct.scalar({'t': out((b / se).reshape(-1, 1)), 'pVal': out((2 * _st().t.sf(np.abs(b / se), df)).reshape(-1, 1))}),
                          'FStat': Struct.scalar({'F': np.nan, 'pVal': np.nan}),
                          'yMu': float(np.mean(X @ b + res)), 'ySigma': float(np.std(X @ b + res, ddof=1)), 'yHat': out((X @ b).reshape(-1, 1)),
                          'res': out(res.reshape(-1, 1)), 'DWStat': float(np.sum(np.diff(res) ** 2) / sse) if sse > 0 else np.nan,
                          'SSR': float(np.sum((X @ b - np.mean(X @ b + res)) ** 2)), 'SSE': sse, 'SST': float(np.sum((X @ b + res - np.mean(X @ b + res)) ** 2)),
                          'MSE': s2, 'RMSE': math.sqrt(s2), 'RSq': rsq, 'aRSq': 1 - (1 - rsq) * (n - 1) / df if df > 0 else np.nan, 'LL': ll,
                          'AIC': -2 * ll + 2 * k, 'BIC': -2 * ll + k * math.log(n), 'HQC': -2 * ll + 2 * k * math.log(math.log(n)) if n > 2 else np.nan})


def _model_opt(v, fn):
    m = str(v).lower()
    if m not in _MODELS:
        raise err(f'econ:{fn}:InvalidModel', "model is 'AR', 'ARD' or 'TS'.", fn)
    return m


@bi('adftest', nout=5, arr=False)
def adftest(nargout, *args):
    """[h, pValue, stat, cValue, reg] = adftest(y, 'model', m, 'lags', k,
    'test', t, 'alpha', a): the augmented Dickey-Fuller test of a unit root
    against a stationary alternative."""
    nargchk(args, 1, 11, 'adftest')
    pos, opts = _pairs(args, 'adftest', ('model', 'lags', 'test', 'alpha'))
    y = _series(pos[0], 'adftest')
    y = y[np.isfinite(y)]
    n_tests, cases = _cases(opts, ('model', 'lags', 'test', 'alpha'), 'adftest')
    cols = [[], [], [], [], []]
    for c in cases:
        model = _model_opt(c.get('model', 'AR'), 'adftest')
        lags = c.get('lags', 0)
        if not (float(lags) >= 0 and float(lags) == int(lags)):
            raise err('econ:adftest:InvalidLags', 'lags is a whole number from 0.', 'adftest')
        lags = int(lags)
        test = str(c.get('test', 't1')).lower()
        if test not in ('t1', 't2', 'f'):
            raise err('econ:adftest:InvalidTest', "test is 't1', 't2' or 'F'.", 'adftest')
        if test == 'f' and model == 'ar':
            raise err('econ:adftest:InvalidTest', "The F test needs model 'ARD' or 'TS'.", 'adftest')
        alpha = _alpha(c.get('alpha', 0.05), 'adftest')
        b, cov, res, n, X, yt, names = _df_regression(y, lags, model)
        reg = _MODELS[model]
        if test == 't1':
            stat = (b[0] - 1) / math.sqrt(cov[0, 0])
            p, cv = tau_p(stat, reg), tau_crit(alpha, reg)
            h = stat < cv
        elif test == 't2':
            stat = n * (b[0] - 1) / (1 - float(np.sum(b[X.shape[1] - lags:])) if lags else 1.0)
            draws = _null_draws('t2', reg, n)
            p, cv = _sim_p(stat, draws, False), _sim_crit(alpha, draws, False)
            h = stat < cv
        else:
            # the unit root with no drift ('ARD') or no trend ('TS'): restricted and unrestricted sums of squares
            k = X.shape[1]
            R = np.zeros((2, k))
            R[0, 0] = 1
            R[1, 1 if model == 'ard' else 2] = 1
            r = R @ b - np.array([1.0, 0.0])
            stat = float(r @ np.linalg.solve(R @ cov @ R.T, r)) / 2
            draws = _null_draws('f', reg, n)
            p, cv = _sim_p(stat, draws, True), _sim_crit(alpha, draws, True)
            h = stat > cv
        cols[0].append(bool(h))
        cols[1].append(float(p))
        cols[2].append(float(stat))
        cols[3].append(float(cv))
        cols[4].append(_reg_struct(b, cov, res, n, X, names, model))
    return _outs(nargout, cols)


def _newey_west(u, lags):
    """The long-run variance of u: Bartlett weights 1 - j/(lags + 1)."""
    n = u.size
    v = u @ u / n
    for j in range(1, lags + 1):
        v += 2 * (1 - j / (lags + 1)) * (u[j:] @ u[:-j]) / n
    return v


@bi('pptest', nout=5, arr=False)
def pptest(nargout, *args):
    """[h, pValue, stat, cValue, reg] = pptest(y, 'model', m, 'lags', k,
    'test', 't1' or 't2', 'alpha', a): the Phillips-Perron test of a unit
    root, the Dickey-Fuller regression's statistics corrected by the
    Newey-West variance of its residuals."""
    nargchk(args, 1, 9, 'pptest')
    pos, opts = _pairs(args, 'pptest', ('model', 'lags', 'test', 'alpha'))
    y = _series(pos[0], 'pptest')
    y = y[np.isfinite(y)]
    n_tests, cases = _cases(opts, ('model', 'lags', 'test', 'alpha'), 'pptest')
    cols = [[], [], [], [], []]
    for c in cases:
        model = _model_opt(c.get('model', 'AR'), 'pptest')
        lags = int(c.get('lags', 0))
        if lags < 0:
            raise err('econ:pptest:InvalidLags', 'lags is a whole number from 0.', 'pptest')
        test = str(c.get('test', 't1')).lower()
        if test not in ('t1', 't2'):
            raise err('econ:pptest:InvalidTest', "test is 't1' or 't2'.", 'pptest')
        alpha = _alpha(c.get('alpha', 0.05), 'pptest')
        b, cov, res, n, X, yt, names = _df_regression(y, 0, model)
        k = X.shape[1]
        s2 = res @ res / (n - k)
        g0 = res @ res / n
        lam2 = _newey_west(res, lags)
        se = math.sqrt(cov[0, 0])
        reg = _MODELS[model]
        if test == 't1':
            t = (b[0] - 1) / se
            stat = math.sqrt(g0 / lam2) * t - (lam2 - g0) * n * se / (2 * math.sqrt(lam2) * math.sqrt(s2))
            p, cv = tau_p(stat, reg), tau_crit(alpha, reg)
        else:
            stat = n * (b[0] - 1) - (n * se) ** 2 / s2 * (lam2 - g0) / 2
            draws = _null_draws('t2', reg, n)
            p, cv = _sim_p(stat, draws, False), _sim_crit(alpha, draws, False)
        cols[0].append(bool(stat < cv))
        cols[1].append(float(p))
        cols[2].append(float(stat))
        cols[3].append(float(cv))
        cols[4].append(_reg_struct(b, cov, res, n, X, names, model))
    return _outs(nargout, cols)


# Kwiatkowski, Phillips, Schmidt and Shin (1992), Table 1: the upper-tail critical values for 10, 5, 2.5 and 1 percent
_KPSS = {'level': [0.347, 0.463, 0.574, 0.739], 'trend': [0.119, 0.146, 0.176, 0.216]}
_KPSS_P = [0.10, 0.05, 0.025, 0.01]


@bi('kpsstest', nout=4, arr=False)
def kpsstest(nargout, *args):
    """[h, pValue, stat, cValue] = kpsstest(y, 'lags', k, 'trend', tf,
    'alpha', a): the KPSS test of stationarity (about a level, or a trend
    when trend is true, the default) against a unit root."""
    nargchk(args, 1, 7, 'kpsstest')
    pos, opts = _pairs(args, 'kpsstest', ('lags', 'trend', 'alpha'))
    y = _series(pos[0], 'kpsstest')
    y = y[np.isfinite(y)]
    n = y.size
    if n < 4:
        raise err('econ:kpsstest:TooFew', 'y has at least 4 values.', 'kpsstest')
    _, cases = _cases(opts, ('lags', 'trend', 'alpha'), 'kpsstest')
    cols = [[], [], [], []]
    for c in cases:
        lags = int(c.get('lags', 0))
        trend = bool(c.get('trend', True))
        alpha = float(c.get('alpha', 0.05))
        if not 0.01 <= alpha <= 0.1:
            raise err('econ:kpsstest:InvalidAlpha', 'alpha is from 0.01 to 0.1 (the table of critical values).', 'kpsstest')
        X = np.column_stack([np.ones(n), np.arange(1, n + 1, dtype=float)]) if trend else np.ones((n, 1))
        e = y - X @ np.linalg.lstsq(X, y, rcond=None)[0]
        S = np.cumsum(e)
        stat = float(S @ S / n ** 2 / _newey_west(e, lags))
        table = _KPSS['trend' if trend else 'level']
        # p by interpolation in the table (upper tail), held at its ends
        p = float(np.interp(stat, table, _KPSS_P))
        if stat < table[0] or stat > table[-1]:
            R.warn('econ:kpsstest:StatisticOutsideTable', f'The statistic is outside the table of critical values: the p-value is {"above" if stat < table[0] else "below"} {p:g}.')
        cv = float(np.interp(alpha, _KPSS_P[::-1], table[::-1]))
        cols[0].append(bool(stat > cv))
        cols[1].append(p)
        cols[2].append(stat)
        cols[3].append(cv)
    return _outs(nargout, cols)


@bi('lbqtest', nout=4, arr=False)
def lbqtest(nargout, *args):
    """[h, pValue, stat, cValue] = lbqtest(res, 'Lags', L, 'DOF', dof,
    'Alpha', a): the Ljung-Box Q test of autocorrelation up to lag L
    (min(20, n-1)), chi-square with dof (L) degrees of freedom."""
    nargchk(args, 1, 7, 'lbqtest')
    pos, opts = _pairs(args, 'lbqtest', ('lags', 'dof', 'alpha'))
    y = _series(pos[0], 'lbqtest', 'res')
    y = y[np.isfinite(y)]
    n = y.size
    _, cases = _cases(opts, ('lags', 'dof', 'alpha'), 'lbqtest')
    cols = [[], [], [], []]
    for c in cases:
        L = int(c.get('lags', min(20, n - 1)))
        if not 1 <= L < n:
            raise err('econ:lbqtest:InvalidLags', f'Lags is a whole number from 1 to {n - 1}.', 'lbqtest')
        dof = float(c.get('dof', L))
        alpha = _alpha(c.get('alpha', 0.05), 'lbqtest')
        r = _acf(y, L)[1:]
        Q = float(n * (n + 2) * np.sum(r ** 2 / (n - np.arange(1, L + 1))))
        p = float(_st().chi2.sf(Q, dof))
        cv = float(_st().chi2.ppf(1 - alpha, dof))
        cols[0].append(Q > cv)
        cols[1].append(p)
        cols[2].append(Q)
        cols[3].append(cv)
    return _outs(nargout, cols)


@bi('archtest', nout=4, arr=False)
def archtest(nargout, *args):
    """[h, pValue, stat, cValue] = archtest(res, 'Lags', L, 'Alpha', a):
    Engle's test of conditional heteroscedasticity: the squared residuals
    on L of their lags (1), T*R^2 chi-square with L degrees of freedom."""
    nargchk(args, 1, 5, 'archtest')
    pos, opts = _pairs(args, 'archtest', ('lags', 'alpha'))
    e = _series(pos[0], 'archtest', 'res')
    e = e[np.isfinite(e)]
    e = e - e.mean()
    _, cases = _cases(opts, ('lags', 'alpha'), 'archtest')
    cols = [[], [], [], []]
    e2 = e ** 2
    for c in cases:
        L = int(c.get('lags', 1))
        if not 1 <= L < e.size - 2:
            raise err('econ:archtest:InvalidLags', 'Lags is a whole number from 1, below the series length less 2.', 'archtest')
        alpha = _alpha(c.get('alpha', 0.05), 'archtest')
        n = e.size - L
        X = np.column_stack([np.ones(n)] + [e2[L - j:e.size - j] for j in range(1, L + 1)])
        yv = e2[L:]
        b, *_ = np.linalg.lstsq(X, yv, rcond=None)
        res = yv - X @ b
        r2 = 1 - (res @ res) / np.sum((yv - yv.mean()) ** 2)
        stat = float(n * r2)
        p = float(_st().chi2.sf(stat, L))
        cv = float(_st().chi2.ppf(1 - alpha, L))
        cols[0].append(stat > cv)
        cols[1].append(p)
        cols[2].append(stat)
        cols[3].append(cv)
    return _outs(nargout, cols)


@bi('vratiotest', nout=5, arr=False)
def vratiotest(nargout, *args):
    """[h, pValue, stat, cValue, ratio] = vratiotest(y, 'period', q, 'IID',
    tf, 'alpha', a): Lo and MacKinlay's variance ratio test of a random walk
    in the log prices y: the variance of q-period returns over q times that
    of one-period returns, robust to heteroscedasticity unless IID."""
    nargchk(args, 1, 7, 'vratiotest')
    pos, opts = _pairs(args, 'vratiotest', ('period', 'iid', 'alpha'))
    y = _series(pos[0], 'vratiotest')
    y = y[np.isfinite(y)]
    _, cases = _cases(opts, ('period', 'iid', 'alpha'), 'vratiotest')
    r = np.diff(y)
    T = r.size
    mu = r.mean()
    cols = [[], [], [], [], []]
    for c in cases:
        q = int(c.get('period', 2))
        if not 2 <= q < T:
            raise err('econ:vratiotest:InvalidPeriod', f'period is a whole number from 2 to {T - 1}.', 'vratiotest')
        iid = bool(c.get('iid', False))
        alpha = _alpha(c.get('alpha', 0.05), 'vratiotest')
        # overlapping q-period returns, with the unbiased variances of Lo and MacKinlay (1988)
        s1 = np.sum((r - mu) ** 2) / (T - 1)
        rq = y[q:] - y[:-q] - q * mu
        m = q * (T - q + 1) * (1 - q / T)
        s2 = np.sum(rq ** 2) / m
        ratio = s2 / s1
        if iid:
            phi = 2 * (2 * q - 1) * (q - 1) / (3 * q * T)
        else:
            d = (r - mu) ** 2
            den = np.sum(d) ** 2
            phi = 0.0
            for j in range(1, q):
                delta = T * np.sum(d[j:] * d[:-j]) / den
                phi += (2 * (q - j) / q) ** 2 * delta
            phi /= T                     # theta(q)/T: the variance of the ratio itself
        stat = (ratio - 1) / math.sqrt(phi)
        p = float(2 * _st().norm.sf(abs(stat)))
        cv = float(_st().norm.ppf(1 - alpha / 2))
        cols[0].append(abs(stat) > cv)
        cols[1].append(p)
        cols[2].append(float(stat))
        cols[3].append(cv)
        cols[4].append(float(ratio))
    return _outs(nargout, cols)


@bi('egcitest', nout=5, arr=False)
def egcitest(nargout, *args):
    """[h, pValue, stat, cValue, reg1] = egcitest(Y, 'creg', c, 'lags', k,
    'alpha', a): the Engle-Granger test of no cointegration: Y(:,1) on the
    other columns (with a constant 'c', a trend 'ct', or 'nc'), then the
    residuals' augmented Dickey-Fuller tau with MacKinnon's values for that
    many series."""
    nargchk(args, 1, 9, 'egcitest')
    pos, opts = _pairs(args, 'egcitest', ('creg', 'lags', 'alpha', 'test', 'cvec', 'rreg'))
    Y = np.asarray(darr(pos[0], 'egcitest'), float)
    if Y.ndim != 2 or Y.shape[1] < 2:
        raise err('econ:egcitest:InvalidData', 'Y has a column for each series, at least two.', 'egcitest')
    Y = Y[np.all(np.isfinite(Y), axis=1)]
    N = Y.shape[1]
    if N > 6:
        raise err('econ:egcitest:TooManySeries', 'MacKinnon\'s values go to 6 series.', 'egcitest')
    _, cases = _cases(opts, ('creg', 'lags', 'alpha'), 'egcitest')
    cols = [[], [], [], [], []]
    T = Y.shape[0]
    for c in cases:
        creg = str(c.get('creg', 'c')).lower()
        if creg not in ('nc', 'c', 'ct', 'ctt'):
            raise err('econ:egcitest:InvalidCreg', "creg is 'nc', 'c', 'ct' or 'ctt'.", 'egcitest')
        lags = int(c.get('lags', 0))
        alpha = _alpha(c.get('alpha', 0.05), 'egcitest')
        det = []
        if creg != 'nc':
            det.append(np.ones(T))
        if creg in ('ct', 'ctt'):
            det.append(np.arange(1, T + 1, dtype=float))
        if creg == 'ctt':
            det.append(np.arange(1, T + 1, dtype=float) ** 2)
        X = np.column_stack(det + [Y[:, k] for k in range(1, N)])
        b, *_ = np.linalg.lstsq(X, Y[:, 0], rcond=None)
        u = Y[:, 0] - X @ b
        bb, cov, res, n, Xd, yt, names = _df_regression(u, lags, 'ar')
        stat = (bb[0] - 1) / math.sqrt(cov[0, 0])
        reg = {'nc': 'n', 'c': 'c', 'ct': 'ct', 'ctt': 'ctt'}[creg]
        p, cv = tau_p(stat, reg, N), tau_crit(alpha, reg, N)
        cols[0].append(bool(stat < cv))
        cols[1].append(p)
        cols[2].append(float(stat))
        cols[3].append(cv)
        nd = len(det)
        cols[4].append(Struct.scalar({'coeff': out(b.reshape(-1, 1)), 'res': out(u.reshape(-1, 1)), 'num': float(T), 'size': float(T),
                                      'a': out(b[:nd].reshape(-1, 1)), 'b': out(b[nd:].reshape(-1, 1))}))
    return _outs(nargout, cols)


# ---- likelihoods and information ------------------------------------------------------------------------------------------

@bi('aicbic', nout=3, arr=False)
def aicbic(nargout, *args):
    """[aic, bic, ic] = aicbic(logL, numParam, numObs, 'Normalize', tf): the
    information criteria of fitted models: aic = -2 logL + 2k, bic = -2 logL
    + k log n; ic also holds aicc, caic and hqc."""
    nargchk(args, 2, 5, 'aicbic')
    pos, opts = _pairs(args, 'aicbic', ('normalize',))
    L = np.asarray(darr(pos[0]), float)
    k = np.asarray(darr(pos[1]), float)
    n = np.asarray(darr(pos[2]), float) if len(pos) > 2 else None
    L, k = np.broadcast_arrays(L, k)
    aic = -2 * L + 2 * k
    norm = bool(num(opts['normalize'])) if 'normalize' in opts else False
    if n is None:
        if nargout > 1:
            raise err('econ:aicbic:NoObservations', 'bic needs numObs.', 'aicbic')
        return out(aic)
    L, k, n = np.broadcast_arrays(L, k, n)
    bic = -2 * L + k * np.log(n)
    with np.errstate(divide='ignore', invalid='ignore'):
        aicc = aic + 2 * k * (k + 1) / (n - k - 1)
        caic = -2 * L + k * (np.log(n) + 1)
        hqc = -2 * L + 2 * k * np.log(np.log(n))
    if norm:
        aic, bic, aicc, caic, hqc = aic / n, bic / n, aicc / n, caic / n, hqc / n
    if nargout < 3:
        return (out(aic), out(bic)) if nargout > 1 else out(aic)
    ic = Struct.scalar({'aic': out(aic), 'bic': out(bic), 'aicc': out(aicc), 'caic': out(caic), 'hqc': out(hqc)})
    return out(aic), out(bic), ic


def _chi2_test(stat, dof, alpha, nargout):
    st = _st()
    stat, dof, alpha = np.broadcast_arrays(np.asarray(stat, float), np.asarray(dof, float), np.asarray(alpha, float))
    if np.any(alpha < 0.001) or np.any(alpha > 0.999):
        raise err('econ:test:InvalidAlpha', 'alpha is from 0.001 to 0.999.', 'test')
    p = st.chi2.sf(stat, dof)
    cv = st.chi2.ppf(1 - alpha, dof)
    h = stat > cv
    vals = (out(h.reshape(1, -1)) if h.size > 1 else bool(h.reshape(-1)[0]), out(p.reshape(1, -1)), out(stat.reshape(1, -1)), out(cv.reshape(1, -1)))
    n = max(nargout, 1)
    return vals[:n] if n > 1 else vals[0]


@bi('lratiotest', nout=4, arr=False)
def lratiotest(nargout, *args):
    """[h, pValue, stat, cValue] = lratiotest(uLogL, rLogL, dof, alpha): the
    likelihood ratio test of restricted models against unrestricted ones:
    2*(uLogL - rLogL), chi-square with dof degrees of freedom."""
    nargchk(args, 3, 4, 'lratiotest')
    u, r = np.asarray(darr(args[0]), float).reshape(-1), np.asarray(darr(args[1]), float).reshape(-1)
    dof = np.asarray(darr(args[2]), float).reshape(-1)
    alpha = np.asarray(darr(args[3]), float).reshape(-1) if len(args) > 3 else 0.05
    if np.any(dof <= 0):
        raise err('econ:lratiotest:InvalidDof', 'dof is positive.', 'lratiotest')
    return _chi2_test(2 * (u - r), dof, alpha, nargout)


def _cell_items(v):
    return list(v.a.reshape(-1, order='F')) if type(v) is Cell else [v]


@bi('waldtest', nout=4, arr=False)
def waldtest(nargout, *args):
    """[h, pValue, stat, cValue] = waldtest(r, R, EstCov, alpha): the Wald
    test of restrictions r(theta) = 0 with their Jacobian R and the
    estimates' covariance: r'*(R*EstCov*R')^-1*r, chi-square with numel(r)
    degrees of freedom. Cells of each give several tests."""
    nargchk(args, 3, 4, 'waldtest')
    rs, Rs, Cs = (_cell_items(a) for a in args[:3])
    n = max(len(rs), len(Rs), len(Cs))
    stats, dofs = [], []
    for i in range(n):
        r = np.asarray(darr(rs[min(i, len(rs) - 1)]), float).reshape(-1)
        Rm = np.atleast_2d(np.asarray(darr(Rs[min(i, len(Rs) - 1)]), float))
        C = np.atleast_2d(np.asarray(darr(Cs[min(i, len(Cs) - 1)]), float))
        if Rm.shape != (r.size, C.shape[0]) or C.shape[0] != C.shape[1]:
            raise err('econ:waldtest:SizeMismatch', 'R has a row for each restriction and a column for each parameter of EstCov.', 'waldtest')
        stats.append(float(r @ np.linalg.solve(Rm @ C @ Rm.T, r)))
        dofs.append(r.size)
    alpha = np.asarray(darr(args[3]), float).reshape(-1) if len(args) > 3 else 0.05
    return _chi2_test(np.array(stats), np.array(dofs), alpha, nargout)


@bi('lmtest', nout=4, arr=False)
def lmtest(nargout, *args):
    """[h, pValue, stat, cValue] = lmtest(score, ParamCov, dof, alpha): the
    Lagrange multiplier test: score'*ParamCov*score, chi-square with dof
    degrees of freedom. Cells give several tests."""
    nargchk(args, 3, 4, 'lmtest')
    ss, Cs = _cell_items(args[0]), _cell_items(args[1])
    n = max(len(ss), len(Cs))
    stats = []
    for i in range(n):
        s = np.asarray(darr(ss[min(i, len(ss) - 1)]), float).reshape(-1)
        C = np.atleast_2d(np.asarray(darr(Cs[min(i, len(Cs) - 1)]), float))
        if C.shape != (s.size, s.size):
            raise err('econ:lmtest:SizeMismatch', 'ParamCov is square, with a row for each element of score.', 'lmtest')
        stats.append(float(s @ C @ s))
    dof = np.asarray(darr(args[2]), float).reshape(-1)
    alpha = np.asarray(darr(args[3]), float).reshape(-1) if len(args) > 3 else 0.05
    return _chi2_test(np.array(stats), dof, alpha, nargout)


# ---- filters and lags ----------------------------------------------------------------------------------------------------

@bi('hpfilter', nout=2, arr=False)
def hpfilter(nargout, *args):
    """[trend, cyclical] = hpfilter(Y, smoothing): the Hodrick-Prescott
    trend of each column (smoothing 1600, for quarterly data) and what is
    left; without outputs, the series and their trends plotted."""
    nargchk(args, 1, 2, 'hpfilter')
    from scipy import sparse
    from scipy.sparse.linalg import spsolve
    Y = np.asarray(darr(args[0], 'hpfilter'), float)
    if Y.ndim != 2:
        raise err('econ:hpfilter:InvalidData', 'Y is a vector or a matrix with a column for each series.', 'hpfilter')
    row = Y.shape[0] == 1
    if row:
        Y = Y.T
    lam = float(num(args[1])) if len(args) > 1 and numel(args[1]) else 1600.0
    if lam < 0:
        raise err('econ:hpfilter:InvalidSmoothing', 'The smoothing is a nonnegative number.', 'hpfilter')
    T = Y.shape[0]
    if T < 3 or lam == 0:
        trend = Y.copy()
    else:
        D = sparse.diags([np.ones(T - 2), -2 * np.ones(T - 2), np.ones(T - 2)], [0, 1, 2], shape=(T - 2, T))
        A = (sparse.eye(T) + lam * (D.T @ D)).tocsc()
        trend = np.column_stack([spsolve(A, Y[:, k]) for k in range(Y.shape[1])]).reshape(Y.shape)
    cyc = Y - trend
    if row:
        trend, cyc = trend.T, cyc.T
    if nargout == 0:
        b = lambda name, *a: R._builtin(name, *a)
        b('plot', out(Y if not row else Y.T))
        b('hold', Char.of('on'))
        b('plot', out(trend if not row else trend.T), Char.of('LineWidth'), 1.5)
        b('hold', Char.of('off'))
        b('title', Char.of(f'Hodrick-Prescott filter, smoothing {lam:g}'))
        return None
    return (out(trend), out(cyc)) if nargout > 1 else out(trend)


@bi('lagmatrix', arr=False)
def lagmatrix(nargout, *args):
    """YLag = lagmatrix(Y, lags): the series shifted by each lag (a negative
    lag a lead), NaN where there is nothing: [Y(t-l1) Y(t-l2) ...], every
    series for the first lag, then for the next."""
    nargchk(args, 2, 2, 'lagmatrix')
    Y = np.asarray(darr(args[0], 'lagmatrix'), float)
    if Y.ndim != 2:
        raise err('econ:lagmatrix:InvalidData', 'Y is a vector or a matrix with a column for each series.', 'lagmatrix')
    if Y.shape[0] == 1:
        Y = Y.T
    lags = np.asarray(darr(args[1]), float).reshape(-1)
    if np.any(lags != np.round(lags)):
        raise err('econ:lagmatrix:InvalidLags', 'The lags are whole numbers.', 'lagmatrix')
    T, k = Y.shape
    cols = []
    for L in lags.astype(int):
        S = np.full((T, k), np.nan)
        if L >= 0:
            if L < T:
                S[L:] = Y[:T - L]
        else:
            if -L < T:
                S[:T + L] = Y[-L:]
        cols.append(S)
    return out(np.hstack(cols) if cols else np.zeros((T, 0)))
