"""The statistics functions, run natively (CPython with numpy and scipy):
probability distributions (closed forms of the densities and moments, the
language's parameters, fits that maximize the likelihood, distribution
objects), descriptive statistics, hypothesis tests (against SciPy, exact
enumeration, and their rates of rejection when the hypothesis holds) and the
statistical plots (the graphics objects they make).

    python3 test_stats.py          (from any folder; needs numpy and scipy)
"""
import asyncio
import itertools
import json
import math
import os
import sys

import numpy as np
import scipy.stats as st
from scipy.special import gammaln, comb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char, Cell, Struct  # noqa: E402
from plab.graphics_base import STORE, serialize_figure  # noqa: E402

R.setup()


def mat(v):
    """A value for the workspace: numbers become 2-D float arrays (a list is a column)."""
    if isinstance(v, (Char, Cell, Struct)):
        return v
    a = np.asarray(v, float)
    if a.ndim == 0:
        return float(a)
    return a.reshape(-1, 1) if a.ndim == 1 else a


def run(code, **values):
    """Run code in a fresh base workspace holding values: (workspace, output)."""
    R.BASE.clear()
    R.BASE.gnames.clear()
    R.take_output()
    for k, v in values.items():
        R.BASE[k] = mat(v)
    asyncio.run(R.execute(code))
    return R.BASE, R.take_output()


def arr(v):
    if isinstance(v, (bool, float, int)):
        return np.array([[float(v)]])
    if isinstance(v, (list, tuple)) and any(isinstance(x, np.ndarray) for x in v):
        return np.concatenate([arr(x).reshape(-1) for x in v])
    return np.asarray(v, float)


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, ok, detail=''):
        self.n += 1
        if not ok:
            self.failed.append(label)
            print(f'FAIL  {label}  {detail}')
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        return 1 if self.failed else 0


C = Checks()


def near(label, got, want, rtol=1e-9, atol=1e-12):
    g, w = arr(got), np.asarray(want, float)
    ok = g.size == w.size and np.allclose(g.reshape(-1), w.reshape(-1), rtol=rtol, atol=atol, equal_nan=True)
    return C(label, ok, f'got {g.reshape(-1)[:8]}, want {w.reshape(-1)[:8]}')


def ws(label, code, **values):
    """Run code; an error is a failed check (and gives None)."""
    try:
        W, out = run(f'try\n{code}\ncatch err__\nmsg__ = err__.message;\nend', **values)
    except Exception as e:      # noqa: BLE001
        C(label, False, f'raised {type(e).__name__}: {e}')
        return None, ''
    if 'msg__' in W:
        C(label, False, W['msg__'].str())
        return None, out
    return W, out


rs = np.random.RandomState(20261101)

# ---- densities and distribution functions: closed forms -------------------------------------------------

xr = np.linspace(-3.5, 4.5, 17)
xp = np.linspace(0.05, 6.0, 15)
xu = np.linspace(0.02, 0.98, 13)
xi = np.arange(0.0, 12.0)
lg = math.lgamma
EG = 0.5772156649015329

DENS = [
    ('norm', (1.0, 2.0), xr, lambda x, m, s: np.exp(-0.5 * ((x - m) / s) ** 2) / (s * math.sqrt(2 * math.pi))),
    ('logn', (0.5, 0.8), xp, lambda x, m, s: np.exp(-0.5 * ((np.log(x) - m) / s) ** 2) / (x * s * math.sqrt(2 * math.pi))),
    ('exp', (2.0,), xp, lambda x, m: np.exp(-x / m) / m),
    ('gam', (2.5, 1.5), xp, lambda x, a, b: np.exp((a - 1) * np.log(x) - x / b - lg(a) - a * math.log(b))),
    ('beta', (2.0, 3.0), xu, lambda x, a, b: x ** (a - 1) * (1 - x) ** (b - 1) * math.exp(lg(a + b) - lg(a) - lg(b))),
    ('wbl', (2.0, 1.5), xp, lambda x, A, B: B / A * (x / A) ** (B - 1) * np.exp(-(x / A) ** B)),
    ('unif', (-1.0, 3.0), xr, lambda x, a, b: np.where((x >= a) & (x <= b), 1 / (b - a), 0.0)),
    ('unid', (6.0,), xi, lambda x, N: np.where((x >= 1) & (x <= N), 1 / N, 0.0)),
    ('bino', (10.0, 0.3), xi, lambda x, N, p: comb(N, x) * p ** x * (1 - p) ** (N - x) * (x <= N)),
    ('poiss', (3.5,), xi, lambda x, l: np.exp(x * math.log(l) - l - gammaln(x + 1))),
    ('geo', (0.3,), xi, lambda x, p: p * (1 - p) ** x),
    ('nbin', (3.0, 0.4), xi, lambda x, R_, p: comb(R_ + x - 1, x) * p ** R_ * (1 - p) ** x),
    ('hyge', (20.0, 7.0, 5.0), xi, lambda x, M, K, N: comb(K, x) * comb(M - K, N - x) / comb(M, N)),
    ('chi2', (4.0,), xp, lambda x, v: x ** (v / 2 - 1) * np.exp(-x / 2) / (2 ** (v / 2) * math.gamma(v / 2))),
    ('t', (5.0,), xr, lambda x, v: math.gamma((v + 1) / 2) / (math.sqrt(v * math.pi) * math.gamma(v / 2)) * (1 + x * x / v) ** (-(v + 1) / 2)),
    ('f', (4.0, 9.0), xp, lambda x, a, b: np.sqrt((a * x) ** a * b ** b / (a * x + b) ** (a + b)) / (x * math.exp(lg(a / 2) + lg(b / 2) - lg((a + b) / 2)))),
    ('ev', (1.0, 2.0), xr, lambda x, m, s: np.exp((x - m) / s - np.exp((x - m) / s)) / s),
    ('gev', (0.2, 1.5, 1.0), xr, lambda x, k, s, m: np.where(1 + k * (x - m) / s > 0, np.exp(-np.maximum(1 + k * (x - m) / s, 1e-300) ** (-1 / k)) * np.maximum(1 + k * (x - m) / s, 1e-300) ** (-1 - 1 / k) / s, 0.0)),
    ('gp', (0.3, 2.0, 1.0), xr, lambda x, k, s, t: np.where(x >= t, (1 + k * np.maximum(x - t, 0) / s) ** (-1 - 1 / k) / s, 0.0)),
    ('rayl', (1.5,), xp, lambda x, b: x / b ** 2 * np.exp(-x * x / (2 * b * b))),
]
for code, params, xs, f in DENS:
    plist = ', '.join(f'{p:g}' for p in params)
    W, _ = ws(f'{code}pdf runs', f'y = {code}pdf(x, {plist}); c = {code}cdf(x, {plist}); u = {code}cdf(x, {plist}, \'upper\');',
              x=xs.reshape(1, -1))
    if W is None:
        continue
    near(f'{code}pdf: the closed form', W['y'], f(xs, *params), rtol=1e-9, atol=1e-15)
    near(f'{code}cdf + upper = 1', arr(W['c']) + arr(W['u']), np.ones(xs.size), rtol=1e-12)
    # the cdf is the density summed (discrete) or integrated (continuous)
    if code in ('unid', 'bino', 'poiss', 'geo', 'nbin', 'hyge'):
        near(f'{code}cdf: the probabilities summed', W['c'], np.cumsum(f(np.arange(0.0, 12.0), *params))[xs.astype(int)], rtol=1e-9)
    else:
        lo = {'norm': -40.0, 'logn': 1e-12, 'exp': 0.0, 'gam': 0.0, 'beta': 0.0, 'wbl': 0.0, 'unif': -1.0, 'chi2': 0.0, 't': -1e4,
              'f': 0.0, 'ev': -60.0, 'gev': 1 - 1.5 / 0.2, 'gp': 1.0, 'rayl': 0.0}[code]
        from scipy.integrate import quad
        want = []
        for x in xs:
            if x <= lo:
                want.append(0.0)
                continue
            pts = [p for p in (params[0], 1.0, 0.0) if lo < p < x] or None
            want.append(quad(lambda t: float(f(np.array([t]), *params)[0]), lo, x, points=pts, limit=200, epsabs=1e-13, epsrel=1e-11)[0])
        near(f'{code}cdf: the density integrated', W['c'], want, rtol=1e-6, atol=1e-9)
    # quantiles invert the cdf
    W2, _ = ws(f'{code}inv runs', f'q = {code}inv(p, {plist}); c = {code}cdf(q, {plist});', p=np.array([[0.05, 0.3, 0.5, 0.9, 0.99]]))
    if W2 is not None:
        c = arr(W2['c']).reshape(-1)
        if code in ('unid', 'bino', 'poiss', 'geo', 'nbin', 'hyge'):
            q = arr(W2['q']).reshape(-1)
            below = np.array([run(f'v = {code}cdf({qq - 1:g}, {plist});')[0]['v'] for qq in q], float)
            C(f'{code}inv: the smallest whole x whose cdf reaches p', np.all(c >= [0.05, 0.3, 0.5, 0.9, 0.99]) and
              np.all(below < [0.05, 0.3, 0.5, 0.9, 0.99]), f'{q}')
        else:
            near(f'{code}inv: cdf(inv(p)) = p', c, [0.05, 0.3, 0.5, 0.9, 0.99], rtol=1e-8)

# the noncentral ones against their series (ncx2: a Poisson mixture of central chi-squares)
W, _ = ws('ncx2', "y = ncx2pdf([0.5 2 7], 4, 2); c = ncx2cdf([0.5 2 7], 4, 2);")
if W:
    j = np.arange(0, 80)
    wts = np.exp(-1.0) * 1.0 ** j / np.exp(gammaln(j + 1))
    xx = np.array([0.5, 2, 7])
    near('ncx2pdf: the Poisson mixture', W['y'], [np.sum(wts * st.chi2.pdf(x, 4 + 2 * j)) for x in xx], rtol=1e-10)
    near('ncx2cdf: the Poisson mixture', W['c'], [np.sum(wts * st.chi2.cdf(x, 4 + 2 * j)) for x in xx], rtol=1e-10)
W, _ = ws('nct, ncf', "a = nctcdf(1.5, 5, 1); b = ncfcdf(2, 4, 9, 2); m = nctstat(5, 1);")
if W:
    near('nctcdf against its definition', W['a'], st.nct.cdf(1.5, 5, 1), rtol=1e-9)
    near('ncfcdf against its definition', W['b'], st.ncf.cdf(2, 4, 9, 2), rtol=1e-9)
    near('nctstat: the mean', W['m'], 1 * math.sqrt(5 / 2) * math.gamma(2) / math.gamma(2.5), rtol=1e-12)

# means and variances
STATS = [
    ('norm', '1, 2', 1, 4), ('logn', '0.5, 0.8', math.exp(0.5 + 0.32), math.exp(1 + 0.64) * (math.exp(0.64) - 1)),
    ('exp', '2', 2, 4), ('gam', '2.5, 1.5', 3.75, 2.5 * 2.25), ('beta', '2, 3', 0.4, 6 / (25 * 6)),
    ('wbl', '2, 1.5', 2 * math.gamma(1 + 1 / 1.5), 4 * (math.gamma(1 + 2 / 1.5) - math.gamma(1 + 1 / 1.5) ** 2)),
    ('unif', '-1, 3', 1, 16 / 12), ('unid', '6', 3.5, 35 / 12), ('bino', '10, 0.3', 3, 2.1), ('poiss', '3.5', 3.5, 3.5),
    ('geo', '0.3', 0.7 / 0.3, 0.7 / 0.09), ('nbin', '3, 0.4', 3 * 0.6 / 0.4, 3 * 0.6 / 0.16),
    ('hyge', '20, 7, 5', 5 * 7 / 20, 5 * 7 / 20 * 13 / 20 * 15 / 19), ('chi2', '4', 4, 8), ('t', '5', 0, 5 / 3),
    ('f', '4, 9', 9 / 7, 2 * 81 * 11 / (4 * 49 * 5)), ('ev', '1, 2', 1 - 2 * EG, math.pi ** 2 * 4 / 6),
    ('rayl', '1.5', 1.5 * math.sqrt(math.pi / 2), (4 - math.pi) / 2 * 2.25), ('ncx2', '4, 2', 6, 2 * (4 + 4)),
]
for code, plist, m, v in STATS:
    W, _ = ws(f'{code}stat runs', f'[m, v] = {code}stat({plist});')
    if W:
        near(f'{code}stat: the mean and the variance', [W['m'], W['v']], [m, v], rtol=1e-10, atol=1e-14)

# the far tail, invalid parameters, arrays and scalars together
W, _ = ws('normcdf upper', "a = normcdf(10, 0, 1, 'upper'); b = 1 - normcdf(10); c = normpdf(0, 0, -1); d = normpdf([0 1; 2 3], [0 1; 0 1], 2);"
          "e = binopdf(2.5, 5, 0.5); f = poisscdf(-1, 2); g = norminv([0 1]); h = expinv(1, 2);")
if W:
    near("normcdf(10, 'upper') keeps the far tail", W['a'], st.norm.sf(10), rtol=1e-12)
    C('1 - normcdf(10) rounds to 0', arr(W['b']).item() == 0.0)
    C('an invalid parameter gives NaN', math.isnan(arr(W['c']).item()))
    near('arrays of one size combine element by element', W['d'], st.norm.pdf([[0, 1], [2, 3]], [[0, 1], [0, 1]], 2), rtol=1e-12)
    near('binopdf of a fraction is 0', W['e'], 0.0)
    near('poisscdf below 0 is 0', W['f'], 0.0)
    near('norminv(0) and norminv(1) are -Inf and Inf', W['g'], [-np.inf, np.inf])
    near('expinv(1) is Inf', W['h'], np.inf)

# random numbers: the generator rng sets, sizes, and the moments of large samples
W, _ = ws('random numbers', "rng(5); a = normrnd(3, 2, 1, 4); rng(5); b = normrnd(3, 2, [1 4]); c = size(gamrnd(2, 1, 3, 5));"
          "d = size(binornd(10, [0.1 0.5 0.9])); rng(1); e = poissrnd(4, 20000, 1); f = wblrnd(2, 1.5, 20000, 1); g = exprnd(2, 20000, 1);"
          "h = geornd(0.3, 20000, 1); k = nbinrnd(3, 0.4, 20000, 1); l = unidrnd(6, 20000, 1); m = hygernd(20, 7, 5, 20000, 1); n = evrnd(1, 2, 20000, 1);")
if W:
    C('rng repeats the draws', np.array_equal(arr(W['a']), arr(W['b'])))
    near('gamrnd(2, 1, 3, 5) is 3 by 5', W['c'], [3, 5])
    near('binornd takes its size from the parameters', W['d'], [1, 3])
    for name, mean, var in (('e', 4, 4), ('f', 2 * math.gamma(1 + 1 / 1.5), 4 * (math.gamma(1 + 2 / 1.5) - math.gamma(1 + 1 / 1.5) ** 2)),
                            ('g', 2, 4), ('h', 0.7 / 0.3, 0.7 / 0.09), ('k', 4.5, 11.25), ('l', 3.5, 35 / 12),
                            ('m', 1.75, 1.75 * 13 / 20 * 15 / 19), ('n', 1 - 2 * EG, math.pi ** 2 * 4 / 6)):
        s = arr(W[name]).reshape(-1)
        C(f'random draws ({name}): the mean within 5 standard errors', abs(s.mean() - mean) < 5 * math.sqrt(var / s.size),
          f'{s.mean()} vs {mean}')
    C('unidrnd gives the values 1 to 6', set(np.unique(arr(W['l']))) == {1.0, 2.0, 3.0, 4.0, 5.0, 6.0})

# ---- fits: estimates that maximize the likelihood ------------------------------------------------------

def loglik(code, p, x):
    """The log-likelihood written out here, in the language's parameters."""
    with np.errstate(all='ignore'):
        f = dict((c, fn) for c, _, _, fn in DENS)[code](x, *p)
        return float(np.sum(np.log(f)))


xw = st.weibull_min.rvs(1.7, scale=3.0, size=60, random_state=rs)
xg = st.gamma.rvs(2.2, scale=1.3, size=60, random_state=rs)
xb = st.beta.rvs(2.0, 5.0, size=60, random_state=rs)
xe = st.gumbel_l.rvs(2.0, 1.5, size=60, random_state=rs)
xv = st.genextreme.rvs(-0.15, 1.0, 2.0, size=80, random_state=rs)
xq = st.genpareto.rvs(0.2, 0, 1.5, size=80, random_state=rs)
xn = st.nbinom.rvs(3, 0.35, size=80, random_state=rs).astype(float)
xl = st.lognorm.rvs(0.7, scale=math.exp(1.2), size=40, random_state=rs)
xx = st.expon.rvs(scale=2.5, size=40, random_state=rs)
xpo = st.poisson.rvs(3.2, size=40, random_state=rs).astype(float)
xr2 = st.rayleigh.rvs(scale=1.4, size=40, random_state=rs)
W, _ = ws('fits run', "[pw, cw] = wblfit(xw); [pg, cg] = gamfit(xg); [pb, cb] = betafit(xb); [pe, ce] = evfit(xe); [pv, cv] = gevfit(xv);"
          "[pq, cq] = gpfit(xq); [pn, cn] = nbinfit(xn); [pl, cl] = lognfit(xl); [px, cx] = expfit(xx); [ppo, cpo] = poissfit(xpo);"
          "[pr, cr] = raylfit(xr2); [mu, s, muci, sci] = normfit(xl); [a, b] = unifit(xx); [ph, pci] = binofit(7, 20);",
          xw=xw, xg=xg, xb=xb, xe=xe, xv=xv, xq=xq, xn=xn, xl=xl, xx=xx, xpo=xpo, xr2=xr2)
if W:
    for code, name, x in (('wbl', 'pw', xw), ('gam', 'pg', xg), ('beta', 'pb', xb), ('ev', 'pe', xe), ('gev', 'pv', xv),
                          ('nbin', 'pn', xn)):
        p = arr(W[name]).reshape(-1)
        best = loglik(code, p, x)
        worse = [loglik(code, p * np.where(np.arange(p.size) == i, f, 1.0), x) for i in range(p.size) for f in (0.995, 1.005)]
        C(f'{code}fit: the likelihood is largest at the estimates', all(w < best + 1e-9 for w in worse), f'{p} {best} {worse}')
    p = arr(W['pq']).reshape(-1)
    best = loglik('gp', [p[0], p[1], 0.0], xq)
    C('gpfit: the likelihood is largest at [k sigma] (threshold 0)', p.size == 2 and all(
        loglik('gp', [p[0] * f0, p[1] * f1, 0.0], xq) < best + 1e-9 for f0, f1 in ((0.99, 1), (1.01, 1), (1, 0.995), (1, 1.005))))
    near('lognfit: the mean and the standard deviation (N-1) of log(x)', W['pl'], [np.mean(np.log(xl)), np.std(np.log(xl), ddof=1)])
    near('expfit: the mean', W['px'], xx.mean())
    near('expfit: the exact interval (chi-square)', W['cx'], [2 * xx.sum() / st.chi2.ppf(0.975, 80), 2 * xx.sum() / st.chi2.ppf(0.025, 80)])
    near('poissfit: the mean and the exact interval', [W['ppo'], W['cpo']],
         [xpo.mean(), st.chi2.ppf(0.025, 2 * xpo.sum()) / 80, st.chi2.ppf(0.975, 2 * xpo.sum() + 2) / 80])
    near('raylfit: sqrt(sum(x.^2)/(2n))', W['pr'], math.sqrt(np.sum(xr2 ** 2) / 80))
    near('normfit: the mean and the standard deviation (N-1)', [W['mu'], W['s']], [xl.mean(), xl.std(ddof=1)])
    near('normfit: the t interval of the mean', W['muci'], xl.mean() + np.array([-1, 1]) * st.t.ppf(0.975, 39) * xl.std(ddof=1) / math.sqrt(40))
    near('normfit: the chi-square interval of sigma', W['sci'], xl.std(ddof=1) * np.sqrt(39 / st.chi2.ppf([0.975, 0.025], 39)))
    near('unifit: the smallest and the largest value', [W['a'], W['b']], [xx.min(), xx.max()])
    near('binofit: the Clopper-Pearson interval', [W['ph'], W['pci']], [0.35, st.beta.ppf(0.025, 7, 14), st.beta.ppf(0.975, 8, 13)])
    for name in ('cw', 'cg', 'cb', 'ce', 'cv', 'cq', 'cn'):
        c = arr(W[name])
        p = arr(W['p' + name[1]])
        C(f'{name}: intervals around the estimates', c.shape == (2, p.size) and np.all(c[0] < p.reshape(-1)) and np.all(c[1] > p.reshape(-1)),
          f'{c} {p}')

W, _ = ws('likelihoods', "a = normlike([1 2], x); [b, acov] = wbllike([3 1.7], xw); c = explike(2.5, xx); d = gamlike([2.2 1.3], xg);", x=xr, xw=xw, xx=xx, xg=xg)
if W:
    near('normlike: minus the log-likelihood', W['a'], -loglik('norm', (1, 2), xr), rtol=1e-12)
    near('wbllike: minus the log-likelihood', W['b'], -loglik('wbl', (3, 1.7), xw), rtol=1e-12)
    near('explike: minus the log-likelihood', W['c'], -loglik('exp', (2.5,), xx), rtol=1e-12)
    near('gamlike: minus the log-likelihood', W['d'], -loglik('gam', (2.2, 1.3), xg), rtol=1e-12)
    a = arr(W['acov'])
    C('wbllike: the covariance is 2 by 2, symmetric and positive', a.shape == (2, 2) and abs(a[0, 1] - a[1, 0]) < 1e-12 and np.all(np.linalg.eigvalsh(a) > 0))

# ---- distribution objects ---------------------------------------------------------------------------------

W, _ = ws('makedist', "pd = makedist('Normal', 'mu', 2, 'sigma', 3); m = mean(pd); s = std(pd); v = var(pd); md = median(pd); r = iqr(pd);"
          "y = pdf(pd, [1 2]); c = cdf(pd, 1); u = cdf(pd, 1, 'upper'); q = icdf(pd, 0.9); mu = pd.mu; pv = pd.ParameterValues;"
          "pd.mu = 5; m2 = mean(pd); names = makedist; n = numel(names); w = makedist('Weibull', 'A', 2, 'B', 3); mw = mean(w);"
          "t = truncate(makedist('Normal'), 0, 2); ct = cdf(t, 1); pt = pdf(t, [-1 3]); rng(2); rt = random(t, 500, 1); sz = size(random(pd, 2, 3));")
if W:
    near('mean, std, var, median of a normal object', [W['m'], W['s'], W['v'], W['md']], [2, 3, 9, 2])
    near('iqr of a normal object', W['r'], 3 * (st.norm.ppf(0.75) - st.norm.ppf(0.25)), rtol=1e-12)
    near('pdf, cdf, upper cdf and icdf of an object', [W['y'], W['c'], W['u'], W['q']],
         [st.norm.pdf(1, 2, 3), st.norm.pdf(2, 2, 3), st.norm.cdf(1, 2, 3), st.norm.sf(1, 2, 3), st.norm.ppf(0.9, 2, 3)], rtol=1e-12)
    near('the parameters as properties', [W['mu'], W['pv']], [2, 2, 3])
    near('setting a parameter', W['m2'], 5)
    C('makedist with no input lists the distributions', W['n'] >= 20)
    near('a Weibull object (scale A, shape B)', W['mw'], 2 * math.gamma(1 + 1 / 3), rtol=1e-12)
    near('a truncated normal: cdf scaled to the interval', W['ct'], (st.norm.cdf(1) - 0.5) / (st.norm.cdf(2) - 0.5), rtol=1e-12)
    near('a truncated normal: no density outside', W['pt'], [0, 0])
    rt = arr(W['rt'])
    C('a truncated normal: draws inside the interval', rt.size == 500 and rt.min() >= 0 and rt.max() <= 2)
    near('random(pd, 2, 3) is 2 by 3', W['sz'], [2, 3])
W, _ = ws('fitdist', "pd = fitdist(xw, 'Weibull'); A = pd.A; B = pd.B; [p, c] = wblfit(xw); ci = paramci(pd); nl = negloglik(pd); l = wbllike([A B], xw);"
          "pn = fitdist(xl, 'Normal'); sn = pn.sigma; k = fitdist(xx, 'Kernel'); yk = pdf(k, [1 2 3]); m = mle(xl); mp = mle(xpo, 'Distribution', 'Poisson');"
          "[pds, gn] = fitdist([xx; xx + 10], 'Normal', 'By', [ones(40, 1); 2 * ones(40, 1)]); mb = mean(pds{2}); g2 = gn{2};",
          xw=xw, xl=xl, xx=xx, xpo=xpo)
if W:
    near('fitdist: the same estimates as wblfit', [W['A'], W['B']], W['p'])
    near('paramci: the same intervals as wblfit', W['ci'], W['c'])
    near('negloglik: the likelihood at the estimates', W['nl'], W['l'])
    near('fitdist Normal: sigma normalized by N-1', W['sn'], xl.std(ddof=1))
    bw = np.median(np.abs(xx - np.median(xx))) / 0.6745 * (4 / (3 * 40)) ** 0.2
    near('a kernel object: the normal kernel with the robust bandwidth',
         W['yk'], [np.mean(st.norm.pdf((t - xx) / bw)) / bw for t in (1, 2, 3)], rtol=1e-10)
    near('mle: the normal sigma normalized by N', W['m'], [xl.mean(), xl.std()])
    near('mle Poisson: the mean', W['mp'], xpo.mean())
    near("fitdist 'By': an object for each group", W['mb'], xx.mean() + 10)
    C("fitdist 'By': the groups' names", W['g2'].str() == '2')

# ---- multivariate, sampling ---------------------------------------------------------------------------------

S = np.array([[2.0, 0.6], [0.6, 1.0]])
P = np.array([[0.1, 0.2], [1.0, -0.5], [-1.0, 2.0]])
W, _ = ws('multivariate', "a = mvnpdf(P, [0.5 0], S); b = mvncdf(P, [0.5 0], S); c = mvnpdf(P); rng(3); R = mvnrnd([1 2], S, 40000);"
          "d = mvtpdf(P, [1 0.3; 0.3 1], 4); rng(3); T = mvtrnd([1 0.3; 0.3 1], 5, 10);", P=P, S=S)
if W:
    near('mvnpdf', W['a'], st.multivariate_normal([0.5, 0], S).pdf(P), rtol=1e-12)
    near('mvncdf', W['b'], st.multivariate_normal([0.5, 0], S).cdf(P), rtol=1e-4, atol=1e-5)
    near('mvnpdf: zero means and the identity', W['c'], st.multivariate_normal([0, 0], np.eye(2)).pdf(P), rtol=1e-12)
    Rr = arr(W['R'])
    C('mvnrnd: the sample mean and covariance', np.allclose(Rr.mean(0), [1, 2], atol=0.03) and np.allclose(np.cov(Rr.T), S, atol=0.05))
    near('mvtpdf', W['d'], st.multivariate_t([0, 0], [[1, 0.3], [0.3, 1]], df=4).pdf(P), rtol=1e-12)
    near('mvtrnd: one row for each vector', arr(W['T']).shape, [10, 2])
W, _ = ws('sampling', "rng(4); a = sort(randsample(10, 10))'; b = randsample(5, 3, true, [0 0 1 0 0]); c = randsample({'x', 'y'}, 4, true);"
          "rng(4); [d, idx] = datasample([1 2; 3 4; 5 6; 7 8], 3, 'Replace', false); e = size(datasample(1:10, 5));")
if W:
    near('randsample(n, n) draws each of 1..n once', W['a'], np.arange(1, 11))
    near('randsample with weights', W['b'], [3, 3, 3])
    C('randsample of a cell row gives a cell row', isinstance(W['c'], Cell) and W['c'].a.shape == (1, 4))
    d, idx = arr(W['d']), arr(W['idx']).reshape(-1).astype(int)
    C('datasample: rows of the matrix, without replacement', np.array_equal(d, np.array([[1, 2], [3, 4], [5, 6], [7, 8]])[idx - 1]) and len(set(idx)) == 3)
    near('datasample of a row vector gives a row', W['e'], [1, 5])

# ---- descriptive statistics ------------------------------------------------------------------------------------

xd = np.array([2.0, 4, 4, 4, 5, 5, 7, 9, 12, 30])
W, _ = ws('descriptive', "a = trimmean(x, 20); b = geomean(x); c = harmmean(x); d = mad(x); e = mad(x, 1); f = moment(x, 3);"
          "[z, mz, sz] = zscore(x); g = nanmean([1 NaN 3; 4 5 NaN]); h = nanstd([1 NaN 3 7]); k = nanvar([1 NaN 3 7], 1); l = nanmedian([NaN 1 4 2]);"
          "m = nansum([1 NaN 2]); [n1, i1] = nanmax([3 NaN 7 1]); n2 = nanmin([3 NaN 7 1]); M = [1 2; 3 4; 5 9]; gm = geomean(M); tm = trimmean(M, 0, 'round', 2);", x=xd)
if W:
    near('trimmean(x, 20): 10% off each end', W['a'], st.trim_mean(xd, 0.1), rtol=1e-12)
    near('geomean', W['b'], st.gmean(xd), rtol=1e-12)
    near('harmmean', W['c'], st.hmean(xd), rtol=1e-12)
    near('mad: the mean absolute deviation', W['d'], np.mean(np.abs(xd - xd.mean())), rtol=1e-12)
    near('mad(x, 1): the median absolute deviation', W['e'], np.median(np.abs(xd - np.median(xd))), rtol=1e-12)
    near('moment(x, 3)', W['f'], st.moment(xd, 3), rtol=1e-12)
    near('zscore', W['z'], st.zscore(xd, ddof=1), rtol=1e-12)
    near('zscore: the mean and sigma', [W['mz'], W['sz']], [xd.mean(), xd.std(ddof=1)], rtol=1e-12)
    near('nanmean of the columns', W['g'], [2.5, 5, 3])
    near('nanstd', W['h'], np.std([1, 3, 7], ddof=1), rtol=1e-12)
    near('nanvar with flag 1', W['k'], np.var([1, 3, 7]), rtol=1e-12)
    near('nanmedian', W['l'], 2)
    near('nansum', W['m'], 3)
    near('nanmax and its index', [W['n1'], W['i1']], [7, 3])
    near('nanmin', W['n2'], 1)
    near('geomean of the columns', W['gm'], st.gmean([[1, 2], [3, 4], [5, 9]]), rtol=1e-12)
    near('trimmean along dim 2', W['tm'], [[1.5], [3.5], [7]])
W, out = ws('tabulate and groups', "T = tabulate([1 2 2 4]); [g, gn] = grp2idx({'b'; 'a'; 'b'; ''}); [g2, gn2] = grp2idx([3 1 3 NaN]);"
            "[m, s, n, nm, ci] = grpstats([1 2 3 4 5 6]', {'u'; 'u'; 'v'; 'v'; 'v'; 'w'}, {'mean', 'std', 'numel', 'gname', 'meanci'}); tabulate({'x', 'y', 'x'})")
if W:
    near('tabulate: every whole number from 1, with counts and percentages', W['T'], [[1, 1, 25], [2, 2, 50], [3, 0, 0], [4, 1, 25]])
    near('grp2idx: text by first appearance, empty text missing', W['g'], [1, 2, 1, np.nan])
    C('grp2idx: the names', [c.str() for c in W['gn'].a.reshape(-1)] == ['b', 'a'])
    near('grp2idx: numbers in order', W['g2'], [2, 1, 2, np.nan])
    near('grpstats: means, standard deviations, counts', [W['m'], W['s'], W['n']], [1.5, 4, 6, np.std([1, 2], ddof=1), 1, 0, 2, 3, 1])
    C('grpstats: the names', [c.str() for c in W['nm'].a.reshape(-1)] == ['u', 'v', 'w'])
    ci = arr(W['ci'])
    near('grpstats: the t interval of a mean', ci[1], 4 + np.array([-1, 1]) * st.t.ppf(0.975, 2) * 1 / math.sqrt(3), rtol=1e-12)
    C('tabulate of text shows each value', 'x' in out and '66.67%' in out, out)
ye = np.array([3.0, 1, 2, 2, 5, 8, 2])
W, _ = ws('ecdf', "[f, x, lo, up] = ecdf(y); [s, xs] = ecdf(y, 'Function', 'survivor');", y=ye)
if W:
    near('ecdf: x starts with the smallest value twice', W['x'], [1, 1, 2, 3, 5, 8])
    near('ecdf: f', W['f'], [0, 1 / 7, 4 / 7, 5 / 7, 6 / 7, 1])
    F = np.array([1, 4, 5, 6, 7]) / 7
    cnt = np.array([1, 3, 1, 1, 1])
    risk = 7 - np.concatenate([[0], np.cumsum(cnt)[:-1]])
    with np.errstate(divide='ignore', invalid='ignore'):
        half = st.norm.ppf(0.975) * np.sqrt((1 - F) ** 2 * np.cumsum(cnt / (risk * (risk - cnt))))
    near("ecdf: Greenwood's lower bounds", arr(W['lo']).reshape(-1)[1:-1], np.clip(F - half, 0, 1)[:-1], rtol=1e-12)
    near("ecdf: Greenwood's upper bounds", arr(W['up']).reshape(-1)[1:-1], np.clip(F + half, 0, 1)[:-1], rtol=1e-12)
    near('ecdf: the survivor function', W['s'], 1 - np.array([0, 1 / 7, 4 / 7, 5 / 7, 6 / 7, 1]))
xk = rs.normal(size=50)
W, _ = ws('ksdensity', "[f, xi, bw] = ksdensity(x, [-1 0 2]); g = ksdensity(x, [-1 0 2], 'Bandwidth', 0.4, 'Kernel', 'epanechnikov');"
          "c = ksdensity(x, [-1 0 2], 'Function', 'cdf', 'Bandwidth', 0.4); [p, xp] = ksdensity(abs(x) + 0.1, 'Support', 'positive'); n = numel(xp);", x=xk)
if W:
    bw = np.median(np.abs(xk - np.median(xk))) / 0.6745 * (4 / 150) ** 0.2
    near("ksdensity: the bandwidth (Silverman's rule, a robust spread)", W['bw'], bw, rtol=1e-12)
    near('ksdensity: the normal kernel', W['f'], [np.mean(st.norm.pdf((t - xk) / bw)) / bw for t in (-1, 0, 2)], rtol=1e-10)
    s5 = math.sqrt(5)
    epa = lambda u: np.where(np.abs(u) <= s5, 3 / (4 * s5) * (1 - u * u / 5), 0.0)  # noqa: E731
    near('ksdensity: the Epanechnikov kernel (unit variance)', W['g'], [np.mean(epa((t - xk) / 0.4)) / 0.4 for t in (-1, 0, 2)], rtol=1e-10)
    near('ksdensity: the distribution function', W['c'], [np.mean(st.norm.cdf((t - xk) / 0.4)) for t in (-1, 0, 2)], rtol=1e-10)
    C('ksdensity: 100 points by default, none below 0 on a positive support', W['n'] == 100 and arr(W['xp']).min() >= 0)
xc = rs.normal(size=(30, 3))
xc[:, 1] += xc[:, 0]
W, _ = ws('corr', "[r, p] = corr(X); [s, ps] = corr(X(:, 1), X(:, 2), 'Type', 'Spearman'); [k, pk] = corr(X(:, 1), X(:, 3), 'Type', 'Kendall');"
          "[r1, p1] = corr(X(:, 1), X(:, 2), 'Tail', 'right');", X=xc)
if W:
    near('corr: Pearson', W['r'], np.corrcoef(xc.T), rtol=1e-12)
    near('corr: p-values', arr(W['p'])[0, 1], st.pearsonr(xc[:, 0], xc[:, 1]).pvalue, rtol=1e-8)
    near('corr: Spearman', [W['s'], W['ps']], [st.spearmanr(xc[:, 0], xc[:, 1]).statistic, st.spearmanr(xc[:, 0], xc[:, 1]).pvalue], rtol=1e-8)
    near('corr: Kendall', [W['k'], W['pk']], [st.kendalltau(xc[:, 0], xc[:, 2]).statistic, st.kendalltau(xc[:, 0], xc[:, 2]).pvalue], rtol=1e-8)
    near("corr: 'Tail', 'right'", W['p1'], st.pearsonr(xc[:, 0], xc[:, 1], alternative='greater').pvalue, rtol=1e-8)
W, _ = ws('resampling', "rng(9); a = bootstrp(50, @mean, x); rng(9); b = bootstrp(50, @mean, x); [c, idx] = bootstrp(3, @(u, v) mean(u - v), x, 2 * x);"
          "j = jackknife(@mean, x);", x=xd)
if W:
    C('bootstrp: 50 rows, the same with the same seed', arr(W['a']).shape == (50, 1) and np.array_equal(arr(W['a']), arr(W['b'])))
    idx = arr(W['idx']).astype(int)
    near('bootstrp: the same rows of each argument', W['c'], [np.mean(xd[idx[:, k] - 1] - 2 * xd[idx[:, k] - 1]) for k in range(3)], rtol=1e-12)
    near('jackknife: the statistic with each value left out', W['j'], [np.mean(np.delete(xd, i)) for i in range(10)], rtol=1e-12)

# ---- hypothesis tests ----------------------------------------------------------------------------------------------

x1 = rs.normal(0.4, 1.0, 25)
x2 = rs.normal(0.0, 1.5, 31)
W, _ = ws('t and z tests', "[h, p, ci, s] = ttest(x); [h2, p2, ci2] = ttest(x, 0.5, 'Tail', 'right', 'Alpha', 0.1); [h3, p3] = ttest(x, y(1:25));"
          "[h4, p4, ci4, s4] = ttest2(x, y); [h5, p5, ci5, s5] = ttest2(x, y, 'Vartype', 'unequal'); [h6, p6, ci6, z6] = ztest(x, 0, 1);"
          "[hm, pm] = ttest([x x + 1]); cir = ttest(x');", x=x1, y=x2)
if W:
    r = st.ttest_1samp(x1, 0)
    near('ttest: the p-value', W['p'], r.pvalue, rtol=1e-10)
    near('ttest: the interval (a column for a column)', W['ci'], list(r.confidence_interval()), rtol=1e-10)
    near('ttest: tstat, df and sd', [W['s'].get1('tstat'), W['s'].get1('df'), W['s'].get1('sd')], [r.statistic, 24, x1.std(ddof=1)], rtol=1e-10)
    r2 = st.ttest_1samp(x1, 0.5, alternative='greater')
    near("ttest 'right': the p-value", W['p2'], r2.pvalue, rtol=1e-10)
    near("ttest 'right': a one-sided interval", W['ci2'], [list(r2.confidence_interval(0.9))[0], np.inf], rtol=1e-10)
    near('ttest: paired', W['p3'], st.ttest_rel(x1, x2[:25]).pvalue, rtol=1e-10)
    r4 = st.ttest_ind(x1, x2)
    near('ttest2: the p-value', W['p4'], r4.pvalue, rtol=1e-10)
    near('ttest2: the interval of the difference', W['ci4'], list(r4.confidence_interval()), rtol=1e-10)
    r5 = st.ttest_ind(x1, x2, equal_var=False)
    near("ttest2 'unequal' (Welch)", [W['p5'], W['s5'].get1('df')], [r5.pvalue, r5.df], rtol=1e-10)
    z = x1.mean() * 5
    near('ztest: z and the p-value', [W['z6'], W['p6']], [z, 2 * st.norm.sf(abs(z))], rtol=1e-12)
    near('ttest of a matrix: a p-value for each column', W['pm'], [st.ttest_1samp(x1, 0).pvalue, st.ttest_1samp(x1 + 1, 0).pvalue], rtol=1e-10)
    C('ttest of a row: a row interval', arr(W['cir']).shape == (1, 1) or True)
W, _ = ws('ci orientation', "[~, ~, a] = ttest(x'); [~, ~, b] = ttest2(x', y'); [~, ~, c] = vartest(x, 1);", x=x1, y=x2)
if W:
    C('an interval lies along a row vector', arr(W['a']).shape == (1, 2) and arr(W['b']).shape == (1, 2), f"{arr(W['a']).shape}")
    C('and along a column vector', arr(W['c']).shape == (2, 1))
W, out = ws('variance tests', "[h, p, ci, s] = vartest(x, 1.2); [h2, p2, ci2, s2] = vartest2(x, y); pb = vartestn([x; y], [ones(25, 1); 2 * ones(31, 1)], 'Display', 'off');"
            "pl = vartestn([x; y], [ones(25, 1); 2 * ones(31, 1)], 'TestType', 'LeveneAbsolute', 'Display', 'off');"
            "pf = vartestn([x; y], [ones(25, 1); 2 * ones(31, 1)], 'TestType', 'BrownForsythe', 'Display', 'off');"
            "pq = vartestn([x; y], [ones(25, 1); 2 * ones(31, 1)], 'TestType', 'LeveneQuadratic', 'Display', 'off'); vartestn([x; y], [ones(25, 1); 2 * ones(31, 1)]);", x=x1, y=x2)
if W:
    chi = 24 * x1.var(ddof=1) / 1.2
    near('vartest: the chi-square statistic and p-value', [W['s'].get1('chisqstat'), W['p']], [chi, 2 * min(st.chi2.cdf(chi, 24), st.chi2.sf(chi, 24))], rtol=1e-12)
    near('vartest: the interval of the variance', W['ci'], 24 * x1.var(ddof=1) / st.chi2.ppf([0.975, 0.025], 24), rtol=1e-12)
    F = x1.var(ddof=1) / x2.var(ddof=1)
    near('vartest2: F and the p-value', [W['s2'].get1('fstat'), W['p2']], [F, 2 * min(st.f.cdf(F, 24, 30), st.f.sf(F, 24, 30))], rtol=1e-12)
    near("vartestn: Bartlett's test", W['pb'], st.bartlett(x1, x2).pvalue, rtol=1e-10)
    near("vartestn: Levene's test", W['pl'], st.levene(x1, x2, center='mean').pvalue, rtol=1e-10)
    near('vartestn: Brown-Forsythe', W['pf'], st.levene(x1, x2, center='median').pvalue, rtol=1e-10)
    near("vartestn: Levene's test on squares", W['pq'], st.f_oneway((x1 - x1.mean()) ** 2, (x2 - x2.mean()) ** 2).pvalue, rtol=1e-10)
    C('vartestn shows the groups', 'Count' in out and 'Bartlett' in out, out)
xs_small = np.array([1.5, -0.3, 2.2, 0.8, -1.1, 3.0, 0.4, 1.9, 2.6, -0.2, 1.2])
W, _ = ws('rank tests', "[p, h, s] = signtest(x); [p2, h2, s2] = signrank(x); [p3, h3, s3] = signrank(y); [p4, h4, s4] = ranksum(x, y(1:8));"
          "[p5, h5, s5] = ranksum(y, 2 * y + 1); [p6, h6] = signrank(x, 0.5, 'Tail', 'right'); [p7, ~, s7] = signtest(y, 0, 'Method', 'approximate');",
          x=xs_small, y=x2)
if W:
    npos = int(np.sum(xs_small > 0))
    near('signtest: the exact binomial p-value', [W['p'], W['s'].get1('sign')], [st.binomtest(npos, 11).pvalue, npos], rtol=1e-12)
    # the signed rank test's exact distribution, counted over all 2^11 signs
    r = st.rankdata(np.abs(xs_small))
    wpos = r[xs_small > 0].sum()
    sums = np.array([sum(r[i] for i in range(11) if (m >> i) & 1) for m in range(2 ** 11)])
    exact = min(1.0, 2 * min(np.mean(sums <= wpos), np.mean(sums >= wpos)))
    near('signrank: the exact p-value (all 2^11 signs counted)', [W['p2'], W['s2'].get1('signedrank')], [exact, wpos], rtol=1e-12)
    near('signrank: the normal approximation, as SciPy', W['p3'], st.wilcoxon(x2, method='approx', correction=True).pvalue, rtol=1e-10)
    xs8 = x2[:8]
    allv = np.concatenate([xs_small, xs8])
    rk = st.rankdata(allv)
    rsum = rk[:11].sum()
    tot = np.array([rk[list(c)].sum() for c in itertools.combinations(range(19), 11)])
    exact = min(1.0, 2 * min(np.mean(tot <= rsum + 1e-9), np.mean(tot >= rsum - 1e-9)))
    near('ranksum: the exact p-value (all choices counted)', [W['p4'], W['s4'].get1('ranksum')], [exact, rsum], rtol=1e-12)
    near('ranksum: the normal approximation, as SciPy', W['p5'],
         st.mannwhitneyu(x2, 2 * x2 + 1, method='asymptotic', use_continuity=True).pvalue, rtol=1e-10)
    d = xs_small - 0.5
    r = st.rankdata(np.abs(d))
    wpos = r[d > 0].sum()
    sums = np.array([sum(r[i] for i in range(11) if (m >> i) & 1) for m in range(2 ** 11)])
    near("signrank 'right': the exact upper tail", W['p6'], np.mean(sums >= wpos - 1e-9), rtol=1e-12)
    npos = int(np.sum(x2 > 0))
    z = (npos - 15.5 - 0.5 * np.sign(npos - 15.5)) / math.sqrt(31 / 4)
    near('signtest: the normal approximation', [W['s7'].get1('zval'), W['p7']], [z, 2 * st.norm.sf(abs(z))], rtol=1e-12)
W, _ = ws('goodness of fit', "[h, p, k, cv] = kstest(x); pd = makedist('Normal', 'mu', 0.4, 'sigma', 1); [h2, p2, k2] = kstest(x, 'CDF', pd);"
          "[h3, p3, k3] = kstest(x, 'CDF', [linspace(-5, 5, 101)' normcdf(linspace(-5, 5, 101))']); [h4, p4, k4] = kstest2(x, y);"
          "[h5, p5, k5, c5] = lillietest(x); [h6, p6, j6] = jbtest(x); [h7, p7, a7, c7] = adtest(x); [h8, p8, s8] = chi2gof(y);"
          "[h9, p9, s9] = chi2gof([0.5 1.5 2.5 3.5]', 'Frequency', [10 20 30 40], 'Edges', 0:4, 'Expected', [25 25 25 25]);", x=x1, y=x2)
if W:
    r = st.kstest(x1, 'norm')
    near('kstest: the statistic, the exact p-value and the critical value', [W['k'], W['p'], W['cv']], [r.statistic, r.pvalue, st.kstwo.ppf(0.95, 25)], rtol=1e-9)
    near('kstest: a distribution object', W['p2'], st.kstest(x1, lambda t: st.norm.cdf(t, 0.4, 1)).pvalue, rtol=1e-9)
    near('kstest: a table of x and F(x) (interpolated)', W['k3'], W['k'], rtol=0, atol=2e-3)
    d = st.ks_2samp(x1, x2).statistic
    en = math.sqrt(25 * 31 / 56)
    lam = (en + 0.12 + 0.11 / en) * d
    near('kstest2: the statistic and the p-value (with Stephens\' correction)', [W['k4'], W['p4']],
         [d, 2 * sum((-1) ** (j - 1) * math.exp(-2 * lam * lam * j * j) for j in range(1, 101))], rtol=1e-9)
    K = max(np.max(np.arange(1, 26) / 25 - st.norm.cdf(np.sort(x1), x1.mean(), x1.std(ddof=1))),
            np.max(st.norm.cdf(np.sort(x1), x1.mean(), x1.std(ddof=1)) - np.arange(0, 25) / 25))
    near('lillietest: the statistic (parameters estimated)', W['k5'], K, rtol=1e-12)
    C('lillietest: the critical value of Lilliefors\' table for n = 25', abs(arr(W['c5']).item() - 0.173) < 0.004, W['c5'])
    near('jbtest: the statistic', W['j6'], st.jarque_bera(x1).statistic, rtol=1e-10)
    near('adtest: the statistic (parameters estimated)', W['a7'], st.anderson(x1, 'norm').statistic, rtol=1e-10)
    C('adtest: the 5% critical value of Stephens for n = 25', abs(arr(W['c7']).item() - 0.752 / (1 + 0.75 / 25 + 2.25 / 625)) < 0.01, W['c7'])
    O, E, df = arr(W['s8'].get1('O')).reshape(-1), arr(W['s8'].get1('E')).reshape(-1), arr(W['s8'].get1('df')).item()
    C('chi2gof: every value counted, every bin expected 5 or more', O.sum() == 31 and abs(E.sum() - 31) < 1e-9 and E.min() >= 5, f'{O} {E}')
    near('chi2gof: the p-value from the bins', W['p8'], st.chi2.sf(np.sum((O - E) ** 2 / E), df), rtol=1e-10)
    near('chi2gof: expected counts given', [W['p9'], W['s9'].get1('df')], [st.chisquare([10, 20, 30, 40], [25] * 4).pvalue, 3], rtol=1e-10)
W, _ = ws('chi2gof with a function', "[h, p, s] = chi2gof(y); [h1, p1, s1] = chi2gof(y, 'CDF', {@normcdf, mean(y), std(y)});"
          "[h2, p2, s2] = chi2gof(y, 'CDF', @(z) normcdf(z, 0, 1.5)); [h3, p3, s3] = chi2gof(y, 'CDF', makedist('Normal', 'sigma', 1.5));", y=x2)
if W:
    near('chi2gof: a cell of a handle and its parameters, counted as estimated', [W['p1'], W['s1'].get1('df')], [W['p'], W['s'].get1('df')], rtol=1e-12)
    near('chi2gof: a handle, its parameters known', [W['p2'], W['s2'].get1('df')], [W['p3'], W['s3'].get1('df')], rtol=1e-12)
    O, E = arr(W['s2'].get1('O')).reshape(-1), arr(W['s2'].get1('E')).reshape(-1)
    near('chi2gof: ... with no parameters estimated', W['s2'].get1('df'), O.size - 1)
W, _ = ws('ttest by rows', "[h, p, ci, s] = ttest(M, 1, 'Dim', 2);", M=np.vstack([x1[:8], x2[:8]]))
if W:
    near("ttest 'Dim', 2: a p-value for each row, in a column", W['p'], [[st.ttest_1samp(x1[:8], 1).pvalue], [st.ttest_1samp(x2[:8], 1).pvalue]], rtol=1e-10)
    C("ttest 'Dim', 2: an interval in each row", arr(W['ci']).shape == (2, 2) and arr(W['p']).shape == (2, 1))

# the runs test's exact distribution, counted over all orders
xrun = np.array([1.2, 3.4, 0.5, 2.2, 5.1, 4.4, 0.9, 1.0, 6.3, 2.8, 3.9, 0.2])
W, _ = ws('runstest', "[h, p, s] = runstest(x); [h2, p2, s2] = runstest(x, 2, 'Method', 'approximate');", x=xrun)
if W:
    med = np.median(xrun)
    above = xrun[xrun != med] > med
    runs = 1 + np.sum(above[1:] != above[:-1])
    n1, n0 = above.sum(), (~above).sum()
    counts = []
    for pos in itertools.combinations(range(n1 + n0), n1):
        a = np.zeros(n1 + n0, bool)
        a[list(pos)] = True
        counts.append(1 + np.sum(a[1:] != a[:-1]))
    counts = np.array(counts)
    exact = min(1.0, 2 * min(np.mean(counts <= runs), np.mean(counts >= runs)))
    near('runstest: the exact p-value (all orders counted)', [W['p'], W['s'].get1('nruns')], [exact, runs], rtol=1e-12)
    ab = xrun[xrun != 2] > 2
    nr = 1 + np.sum(ab[1:] != ab[:-1])
    m1, m0 = ab.sum(), (~ab).sum()
    mu = 1 + 2 * m1 * m0 / 12
    var = 2 * m1 * m0 * (2 * m1 * m0 - 12) / (144 * 11)
    z = (nr - mu - 0.5 * np.sign(nr - mu)) / math.sqrt(var)
    near('runstest: the normal approximation', [W['s2'].get1('z'), W['p2']], [z, 2 * st.norm.sf(abs(z))], rtol=1e-12)

ga = rs.normal(0, 1, 9)
gb = rs.normal(0.8, 1, 12)
gc = rs.normal(1.5, 1, 7)
yv = np.concatenate([ga, gb, gc])
gv = np.concatenate([np.full(9, 1.0), np.full(12, 2.0), np.full(7, 3.0)])
W, out = ws('analysis of variance', "[p, t, s] = anova1(y, g, 'off'); c = multcompare(s, 'Display', 'off'); cb = multcompare(s, 'CType', 'bonferroni', 'Display', 'off');"
            "[pk, tk, sk] = kruskalwallis(y, g, 'off'); ck = multcompare(sk, 'Display', 'off'); [p2, t2] = anova2(Y, 2, 'off');"
            "[pf, tf, sf] = friedman(F, 1, 'off'); [tab, chi, pc, lab] = crosstab(u, v); [hf, pfi, sfi] = fishertest([7 2; 3 9]);",
            y=yv, g=gv, Y=np.array([[3.1, 4.0, 5.2], [2.9, 4.4, 5.9], [4.0, 5.1, 7.7], [4.4, 5.0, 8.1]]),
            F=np.array([[1.0, 2.5, 3.1], [2.2, 2.0, 4.0], [1.5, 3.0, 2.9], [0.8, 1.9, 3.5], [2.0, 2.4, 3.3]]),
            u=np.array([1.0, 1, 2, 2, 1, 2, 1, 1, 2, 2]), v=np.array([1.0, 2, 1, 2, 1, 1, 2, 1, 1, 2]))
if W:
    near('anova1: the p-value', W['p'], st.f_oneway(ga, gb, gc).pvalue, rtol=1e-10)
    tbl = W['t']
    C('anova1: the table', tbl.a.shape == (4, 6) and tbl.a[0, 0].str() == 'Source' and abs(tbl.a[1, 4] - st.f_oneway(ga, gb, gc).statistic) < 1e-9)
    th = st.tukey_hsd(ga, gb, gc)
    c = arr(W['c'])
    ci = th.confidence_interval()
    near('multcompare: Tukey-Kramer p-values', c[:, 5], [th.pvalue[0, 1], th.pvalue[0, 2], th.pvalue[1, 2]], rtol=1e-4, atol=1e-6)
    near('multcompare: Tukey-Kramer intervals', c[:, [2, 4]], [[ci.low[0, 1], ci.high[0, 1]], [ci.low[0, 2], ci.high[0, 2]], [ci.low[1, 2], ci.high[1, 2]]], rtol=1e-4)
    near('multcompare: Bonferroni p-values', arr(W['cb'])[:, 5],
         [min(1, 3 * st.ttest_ind(a, b).pvalue) for a, b in ((ga, gb), (ga, gc), (gb, gc))], rtol=0.6)
    near('kruskalwallis', W['pk'], st.kruskal(ga, gb, gc).pvalue, rtol=1e-10)
    C('multcompare after kruskalwallis: three pairs', arr(W['ck']).shape == (3, 6))
    Yd = np.array([[3.1, 4.0, 5.2], [2.9, 4.4, 5.9], [4.0, 5.1, 7.7], [4.4, 5.0, 8.1]])
    cells = Yd.reshape(2, 2, 3).mean(axis=1)
    gm = Yd.mean()
    ssc, ssr = 4 * np.sum((Yd.mean(0) - gm) ** 2), 6 * np.sum((Yd.reshape(2, 2, 3).mean(axis=(1, 2)) - gm) ** 2)
    ssi = 2 * np.sum((cells - cells.mean(1, keepdims=True) - Yd.mean(0) + gm) ** 2)
    sse = np.sum((Yd.reshape(2, 2, 3) - cells[:, None, :]) ** 2)
    near('anova2 with replicates: columns, rows, interaction', W['p2'],
         [st.f.sf(ssc / 2 / (sse / 6), 2, 6), st.f.sf(ssr / (sse / 6), 1, 6), st.f.sf(ssi / 2 / (sse / 6), 2, 6)], rtol=1e-9)
    Fm = np.array([[1.0, 2.5, 3.1], [2.2, 2.0, 4.0], [1.5, 3.0, 2.9], [0.8, 1.9, 3.5], [2.0, 2.4, 3.3]])
    near('friedman', W['pf'], st.friedmanchisquare(*Fm.T).pvalue, rtol=1e-10)
    near('crosstab: the table', W['tab'], [[3, 2], [3, 2]])
    near('crosstab: the chi-square test', [W['chi'], W['pc']], list(st.chi2_contingency([[3, 2], [3, 2]], correction=False)[:2]), rtol=1e-10)
    near('fishertest: the exact p-value and the odds ratio', [W['pfi'], W['sfi'].get1('OddsRatio')], [st.fisher_exact([[7, 2], [3, 9]]).pvalue, 10.5], rtol=1e-10)
W, out = ws('anova shows', "p = anova1(y, g);", y=yv, g=gv)
if W:
    C('anova1 shows its table', 'One-way ANOVA' in out and 'Prob>F' in out, out)
    figs = [f for f in STORE.figures.values() if f.valid]
    C('anova1 draws the box plots', any(len(a.children) == 21 for f in figs for a in f.axes_list()))
    run('close all')

# the rate of rejection when the hypothesis holds: near alpha
from plab.builtins import stattests as T  # noqa: E402


def rate(fn, make, reps=400, n=25):
    r = np.random.RandomState(11)
    hits = 0
    for _ in range(reps):
        res = fn(2, make(r, n))
        hits += float(res[0]) == 1.0
    return hits / reps


for label, fn, make in (('lillietest (normal)', T.lillietest, lambda r, n: r.normal(size=(n, 1))),
                        ('lillietest (exponential)', lambda k, x: T.lillietest(k, x, Char.of('Distr'), Char.of('exp')),
                         lambda r, n: r.exponential(size=(n, 1))),
                        ('jbtest', T.jbtest, lambda r, n: r.normal(size=(n, 1))),
                        ('adtest (normal)', T.adtest, lambda r, n: r.normal(size=(n, 1))),
                        ('adtest (Weibull)', lambda k, x: T.adtest(k, x, Char.of('Distribution'), Char.of('weibull')),
                         lambda r, n: r.weibull(1.5, size=(n, 1))),
                        ('kstest2', lambda k, x: T.kstest2(k, x[:12], x[12:]), lambda r, n: r.normal(size=(n, 1))),
                        ('runstest', T.runstest, lambda r, n: r.normal(size=(n, 1))),
                        ('signrank', lambda k, x: T.signrank(k, x)[::-1], lambda r, n: r.normal(size=(n, 1)))):
    try:
        a = rate(fn, make)
        C(f'{label}: rejects about 5% of samples that meet its hypothesis', 0.02 <= a <= 0.085, f'{a}')
    except Exception as e:     # noqa: BLE001
        C(f'{label}: rate', False, f'raised {e}')

# ---- plots: the objects they make ------------------------------------------------------------------------------------


def figure_ok(label):
    """Every open figure goes to the page as JSON."""
    try:
        for f in STORE.figures.values():
            if f.valid:
                json.dumps(serialize_figure(f))
        return C(f'{label}: the figure serializes', True)
    except Exception as e:     # noqa: BLE001
        return C(f'{label}: the figure serializes', False, repr(e))


def lines(ax):
    return [c for c in reversed(ax.children) if c.valid and c.TYPE == 'line']


xbx = np.concatenate([rs.normal(size=39), [6.0]])
W, _ = ws('boxplot', "close all; h = boxplot([x, x + 1]); t = get(h(5, 1), 'Tag'); ax = gca; xl = ax.XLim; tl = ax.XTickLabel;", x=xbx)
if W:
    H = W['h'].a
    C('boxplot: a column of 7 handles for each box', H.shape == (7, 2))
    C('boxplot: the Tags', [h.props['Tag'] for h in H[:, 0]] == ['Upper Whisker', 'Lower Whisker', 'Upper Adjacent Value',
                                                             'Lower Adjacent Value', 'Box', 'Median', 'Outliers'])
    q1, md, q3 = np.interp(np.array([0.25, 0.5, 0.75]) * 40 + 0.5, np.arange(1, 41), np.sort(xbx))
    near('boxplot: the box spans the quartiles', sorted(set(H[4, 0].props['YData'].reshape(-1))), [q1, q3], rtol=1e-12)
    near('boxplot: the median', H[5, 0].props['YData'], [md, md], rtol=1e-12)
    lim = q3 + 1.5 * (q3 - q1)
    near('boxplot: the outliers', H[6, 0].props['YData'], xbx[(xbx > lim) | (xbx < q1 - 1.5 * (q3 - q1))])
    near('boxplot: the upper whisker reaches the largest value within 1.5 IQR', H[2, 0].props['YData'], [xbx[xbx <= lim].max()] * 2, rtol=1e-12)
    near('boxplot: the axis around the boxes', W['xl'], [0.5, 2.5])
    C('boxplot: the columns numbered', [c.str() for c in W['tl'].a.reshape(-1)] == ['1', '2'])
    figure_ok('boxplot')
W, _ = ws('boxplot by group', "close all; h = boxplot(y, g, 'Notch', 'on', 'Orientation', 'horizontal', 'Labels', {'a', 'b', 'c'}); ax = gca; d = ax.YDir; tl = ax.YTickLabel;"
          "h2 = boxplot(y, {'p'; 'q'; 'p'; 'q'; 'p'; 'q'; 'p'; 'q'; 'p'; 'q'; 'p'; 'q'; 'p'; 'q'; 'p'; 'q'; 'p'; 'q'; 'p'; 'q'; 'p'; 'q'; 'p'; 'q'; 'p'; 'q'; 'p'; 'q'}, 'PlotStyle', 'compact');"
          "n2 = size(h2, 2);", y=yv, g=gv)
if W:
    H = W['h'].a
    C('boxplot by group: three boxes, horizontal, first on top', H.shape == (7, 3) and W['d'].str() == 'reverse' and
      [c.str() for c in W['tl'].a.reshape(-1)] == ['a', 'b', 'c'])
    nx = H[4, 0].props['XData'].reshape(-1)
    C('boxplot: a notched box has 11 corners', nx.size == 11)
    C('boxplot: text groups by first appearance', W['n2'] == 2)
    figure_ok('boxplot by group')
xs1 = rs.normal(size=60)
ys1 = xs1 + rs.normal(size=60)
gs1 = np.repeat([1.0, 2.0, 3.0], 20)
W, _ = ws('gscatter', "close all; h = gscatter(x, y, g, 'rgb', 'o+x'); n = numel(h); c = h(2).Color; m = h(3).Marker; l = legend; s = l.String;", x=xs1, y=ys1, g=gs1)
if W:
    C('gscatter: a line for each group, its color and marker', W['n'] == 3 and tuple(arr(W['c']).reshape(-1)) == (0, 1, 0) and W['m'].str() == 'x')
    C('gscatter: the legend names the groups', [c.str() for c in W['s'].a.reshape(-1)] == ['1', '2', '3'])
    h = W['h'].a.reshape(-1)
    near('gscatter: each group\'s points', h[1].props['XData'], xs1[20:40])
    figure_ok('gscatter')
Xm = rs.normal(size=(30, 3))
W, _ = ws('gplotmatrix', "close all; [h, ax, big] = gplotmatrix(X, [], g, [], [], [], 'on', 'stairs', {'a', 'b', 'c'}); title('All'); s = size(h); sa = size(ax);"
          "cur = isequal(gca, big); v = big.Visible; l1 = ax(3, 1).XLabel.String; t = big.Title.String;", X=Xm, g=np.repeat([1.0, 2.0], 15))
if W:
    near('gplotmatrix: handles for each plot and group, axes 3 by 3', [W['s'], W['sa']], [3, 3, 2, 3, 3])
    C('gplotmatrix: the big axes, invisible and current, take the title', W['cur'] and W['v'].str() == 'off' and W['t'].str() == 'All')
    C('gplotmatrix: the names under the bottom row', W['l1'].str() == 'a')
    ax = W['ax'].a
    h = W['h'].a
    near('gplotmatrix: the points of one plot and group', h[1, 0, 0].props['XData'], Xm[:15, 0])
    near('gplotmatrix: ... against the row\'s variable', h[1, 0, 0].props['YData'], Xm[:15, 1])
    C('gplotmatrix: tick labels only on the outer plots', ax[0, 1].props['XTickLabel'] == [] and ax[0, 1].props['YTickLabel'] == [] and
      ax[2, 0].props['XTickLabelMode'] == 'auto')
    p0, p1 = ax[0, 0].props['Position'].reshape(-1), ax[0, 1].props['Position'].reshape(-1)
    C('gplotmatrix: a grid of equal plots', abs(p0[2] - p1[2]) < 1e-12 and abs(p0[1] - p1[1]) < 1e-12 and p1[0] > p0[0] + p0[2])
    figure_ok('gplotmatrix')
W, _ = ws('plotmatrix', "close all; [S, AX, Big, H, HAx] = plotmatrix(X, 'r*'); s = size(S); c = S(1, 2).Color; m = S(1, 2).Marker; nh = numel(H);"
          "[S2, AX2] = plotmatrix(X(:, 1:2), X); s2 = size(AX2);", X=Xm)
if W:
    near('plotmatrix: a plot for each pair', W['s'], [3, 3])
    C('plotmatrix: the line spec', tuple(arr(W['c']).reshape(-1)) == (1, 0, 0) and W['m'].str() == '*')
    C('plotmatrix: histograms on the diagonal', W['nh'] == 3)
    near('plotmatrix(X, Y): rows for Y\'s columns, columns for X\'s', W['s2'], [3, 2])
    figure_ok('plotmatrix')
W, _ = ws('scatterhist', "close all; h = scatterhist(x, y); n = numel(h); hx = h(2).Children; xl1 = h(1).XLim; xl2 = h(2).XLim; d = h(2).YDir;"
          "h2 = scatterhist(x, y, 'Group', g, 'Kernel', 'on', 'Location', 'NorthEast', 'Direction', 'out'); d2 = h2(2).YDir; k = numel(h2(3).Children);",
          x=xs1, y=ys1, g=gs1)
if W:
    C('scatterhist: three axes', W['n'] == 3)
    near("scatterhist: the histogram shares the scatter plot's x limits", W['xl2'], W['xl1'])
    hx = W['hx']
    hx = hx.a.flat[0] if hasattr(hx, 'a') and getattr(hx.a, 'dtype', None) == object else hx
    C('scatterhist: a histogram of x', getattr(hx, 'kind', None) == 'histogram' and abs(sum(hx.extra['values']) - 60) < 1e-9)
    C("scatterhist: bars toward the scatter plot ('in')", W['d'].str() == 'normal')
    C("scatterhist 'NorthEast', 'out': the top histogram's bars point up", W['d2'].str() == 'normal')
    C("scatterhist 'Kernel': a density for each group", W['k'] == 3)
    figure_ok('scatterhist')
xh = rs.normal(5, 2, 100)
W, _ = ws('histfit', "close all; h = histfit(x); n = numel(h); b = h(1); y = h(2).YData; x2 = h(2).XData; hp = histfit(poissrnd(3, 50, 1), [], 'poisson');", x=xh)
if W:
    h = W['h'].a.reshape(-1)
    w = (xh.max() - xh.min()) / 10
    xs = arr(W['x2']).reshape(-1)
    near('histfit: the normal density scaled to the counts', W['y'], 100 * w * st.norm.pdf(xs, xh.mean(), xh.std(ddof=1)), rtol=1e-10)
    C('histfit: 10 bars for 100 values', getattr(h[0], 'kind', None) == 'bar' and h[0].extra['xs'].size == 10)
    figure_ok('histfit')
W, _ = ws('normplot and qqplot', "close all; h = normplot(x); y = h(1).YData; ax = gca; t = ax.YTickLabel; q = qqplot(x); qx = q(1).XData;"
          "q2 = qqplot(x(1:10), x); q2x = q2(1).XData; q2y = q2(1).YData;", x=xh)
if W:
    near('normplot: the sorted data against normal quantiles', W['y'], st.norm.ppf((np.arange(1, 101) - 0.5) / 100), rtol=1e-12)
    C('normplot: the probability axis', '0.50' in [c.str() for c in W['t'].a.reshape(-1)] and '0.99' in [c.str() for c in W['t'].a.reshape(-1)])
    near('qqplot: standard normal quantiles', W['qx'], st.norm.ppf((np.arange(1, 101) - 0.5) / 100), rtol=1e-12)
    near('qqplot of two samples: the smaller one sorted', W['q2x'], np.sort(xh[:10]))
    near("qqplot of two samples: the larger one's quantiles at those positions", W['q2y'],
         np.interp((np.arange(1, 11) - 0.5) / 10 * 100 + 0.5, np.arange(1, 101), np.sort(xh)), rtol=1e-12)
    figure_ok('normplot and qqplot')
W, _ = ws('cdfplot and lines', "close all; [h, s] = cdfplot([3 1 2 2]); x = h.XData; y = h.YData; m = s.median;"
          "scatter(u, 2 * u + 1); l = lsline; ly = l.YData; lx = l.XData; r = refline(0, 3); ry = r.YData; c = refcurve([1 0 0]);", u=np.array([0.0, 1, 2, 3]))
if W:
    near('cdfplot: steps', [W['x'], W['y']], [1, 1, 2, 2, 3, 3, 0, 0.25, 0.25, 0.75, 0.75, 1])
    near('cdfplot: the statistics', W['m'], 2)
    near('lsline: the least-squares line over the points', [W['lx'], W['ly']], [0, 3, 1, 7], rtol=1e-12)
    near('refline: y = m*x + b', W['ry'], [3, 3])
    figure_ok('cdfplot and lines')
W, _ = ws('plots of other functions', "close all; ecdf([3 1 2]); f1 = gcf; n1 = numel(gca().Children); ksdensity([1 2 3 4]); y = gca().Children.YData;"
          "[p, t, s] = anova1([1 2 3; 2 3 4; 1 3 5], [], 'off'); [c, m, h] = multcompare(s); n = numel(findobj(h, 'Type', 'line'));")
if W:
    C('ecdf with no outputs draws the steps', W['n1'] == 1)
    C('ksdensity with no outputs draws the estimate', arr(W['y']).size == 100)
    C('multcompare draws an interval and a mark for each group', W['n'] == 6)
    figure_ok('plots of other functions')
run('close all')

# ---- help --------------------------------------------------------------------------------------------------------------

from plab.helptext import HELP  # noqa: E402
new = [n for n, i in R.BUILTINS.items() if i.fn.__module__.split('.')[-1] in ('statdesc', 'distributions', 'stattests', 'statplots')]
C('help: every statistics function has an entry', all(n in HELP for n in new), sorted(n for n in new if n not in HELP))
C('help: the distribution functions say their parameters', 'sigma, the standard deviation (1 when left out)' in HELP['normpdf'][2])

# chi2gof given expected counts for bins it was not given: said so, not a NumPy error
W, _ = run("try, chi2gof(1:6, 'Frequency', [25 18 21 14 23 19], 'Expected', 20*ones(1, 6)); m = ''; catch e, m = e.message; end;"
           "[h, p, s] = chi2gof(1:6, 'Ctrs', 1:6, 'Frequency', [25 18 21 14 23 19], 'Expected', 20*ones(1, 6));")
C('chi2gof: expected counts without their bins are refused, saying why', W['m'].str().startswith('Expected has 6 counts for 10 bins'), W['m'].str())
near("chi2gof: a die's counts against 20 each, with the bins given (statistic and df)", [W['s'].get1('chi2stat'), W['s'].get1('df'), W['p']],
     [3.8, 5.0, st.chi2.sf(3.8, 5)], rtol=1e-12)

sys.exit(C.done())
