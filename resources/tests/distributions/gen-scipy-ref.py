#!/usr/bin/env python3
"""Reference values for distributions.html's engine, from scipy.stats.

For every family of resources/js/distributions/ and a few parameter sets
each (ordinary ones and awkward ones: tiny shapes, huge counts, a shape
near a boundary), SciPy's density (or probability), CDF, survival function,
quantiles in both tails, mean, variance, skewness, excess kurtosis, entropy
and median; and for the families that are fitted, a sample drawn with a
fixed seed and SciPy's maximum-likelihood fit to it with its log-likelihood.

Three families have no SciPy counterpart and are built here from one that
has (the log-triangular, double-triangular and log-double-triangular); their
moments come from scipy.integrate.quad.

    python3 resources/tests/distributions/gen-scipy-ref.py

writes scipy-ref.json beside this file. test-engine.mjs reads it.
Generated with SciPy 1.16 and NumPy 2.3; the numbers are SciPy's, the file
is ours.
"""
import json
import math
import os
import warnings

import numpy as np
from scipy import integrate, optimize, stats as st

warnings.filterwarnings('ignore')

HERE = os.path.dirname(os.path.abspath(__file__))
U = [1e-12, 1e-6, 1e-3, 0.05, 0.3, 0.5, 0.7, 0.95, 0.999, 1 - 1e-6]
Q = [1e-12, 1e-6, 1e-3, 0.05, 0.3]


def num(v):
    v = float(v)
    if math.isnan(v):
        return 'nan'
    if math.isinf(v):
        return 'inf' if v > 0 else '-inf'
    return v


class Custom:
    """A distribution SciPy lacks, from functions; moments by quad."""

    def __init__(self, logpdf, cdf, sf, ppf, isf, lo, hi):
        self._logpdf, self._cdf, self._sf, self._ppf, self._isf = logpdf, cdf, sf, ppf, isf
        self.lo, self.hi = lo, hi

    def logpdf(self, x):
        return np.array([self._logpdf(v) for v in np.atleast_1d(x)])

    def cdf(self, x):
        return np.array([self._cdf(v) for v in np.atleast_1d(x)])

    def sf(self, x):
        return np.array([self._sf(v) for v in np.atleast_1d(x)])

    def ppf(self, u):
        return np.array([self._ppf(v) for v in np.atleast_1d(u)])

    def isf(self, q):
        return np.array([self._isf(v) for v in np.atleast_1d(q)])

    def _moment(self, f):
        # over the quantile function, which is finite on (0, 1) for these bounded shapes
        return integrate.quad(lambda u: f(self._ppf(u)), 0, 1, limit=400, epsabs=1e-14, epsrel=1e-12)[0]

    def stats(self, moments='mvsk'):
        m = self._moment(lambda x: x)
        v = self._moment(lambda x: (x - m) ** 2)
        s = self._moment(lambda x: (x - m) ** 3) / v ** 1.5
        k = self._moment(lambda x: (x - m) ** 4) / v ** 2 - 3
        return m, v, s, k

    def entropy(self):
        return integrate.quad(lambda u: -self._logpdf(self._ppf(u)), 0, 1, limit=400, epsabs=1e-13, epsrel=1e-11)[0]

    def median(self):
        return self._ppf(0.5)

    def support(self):
        return self.lo, self.hi


def triang_on(a, c, b):
    return st.triang(c=(c - a) / (b - a), loc=a, scale=b - a)


def logtriang(p):
    t = triang_on(math.log(p['a']), math.log(p['c']), math.log(p['b']))
    return Custom(lambda x: (t.logpdf(math.log(x)) - math.log(x)) if x > 0 else -math.inf,
                  lambda x: t.cdf(math.log(x)) if x > 0 else 0.0,
                  lambda x: t.sf(math.log(x)) if x > 0 else 1.0,
                  lambda u: math.exp(t.ppf(u)), lambda q: math.exp(t.isf(q)), p['a'], p['b'])


def dtri_parts(a, c, b):
    def logpdf(x):
        if x < a or x > b:
            return -math.inf
        return math.log((x - a) / (c - a) ** 2) if x <= c else math.log((b - x) / (b - c) ** 2)

    def cdf(x):
        if x <= a:
            return 0.0
        if x >= b:
            return 1.0
        return (x - a) ** 2 / (2 * (c - a) ** 2) if x <= c else 1 - (b - x) ** 2 / (2 * (b - c) ** 2)

    def sf(x):
        if x <= a:
            return 1.0
        if x >= b:
            return 0.0
        return 1 - (x - a) ** 2 / (2 * (c - a) ** 2) if x <= c else (b - x) ** 2 / (2 * (b - c) ** 2)

    def ppf(u):
        return a + (c - a) * math.sqrt(2 * u) if u <= 0.5 else b - (b - c) * math.sqrt(2 * (1 - u))

    def isf(q):
        return b - (b - c) * math.sqrt(2 * q) if q <= 0.5 else a + (c - a) * math.sqrt(2 * (1 - q))

    return logpdf, cdf, sf, ppf, isf


def dtriang(p):
    lp, F, S, P, I = dtri_parts(p['a'], p['c'], p['b'])
    return Custom(lp, F, S, P, I, p['a'], p['b'])


def logdtriang(p):
    lp, F, S, P, I = dtri_parts(math.log(p['a']), math.log(p['c']), math.log(p['b']))
    return Custom(lambda x: (lp(math.log(x)) - math.log(x)) if x > 0 else -math.inf,
                  lambda x: F(math.log(x)) if x > 0 else 0.0,
                  lambda x: S(math.log(x)) if x > 0 else 1.0,
                  lambda u: math.exp(P(u)), lambda q: math.exp(I(q)), p['a'], p['b'])


def pert(p):
    a, c, b, lam = p['a'], p['c'], p['b'], p['lambda']
    return st.beta(1 + lam * (c - a) / (b - a), 1 + lam * (b - c) / (b - a), loc=a, scale=b - a)


CONT = {
    'normal': (lambda p: st.norm(p['mu'], p['sigma']),
               [dict(mu=0, sigma=1), dict(mu=-3.5, sigma=0.01), dict(mu=1e5, sigma=250)]),
    'lognormal': (lambda p: st.lognorm(s=p['sigma'], scale=math.exp(p['mu'])),
                  [dict(mu=0, sigma=1), dict(mu=2.3, sigma=0.1), dict(mu=-5, sigma=2.5)]),
    'uniform': (lambda p: st.uniform(loc=p['a'], scale=p['b'] - p['a']), [dict(a=0, b=1), dict(a=-3, b=7.5)]),
    'loguniform': (lambda p: st.loguniform(p['a'], p['b']), [dict(a=1, b=100), dict(a=1e-6, b=0.5), dict(a=1, b=1.001)]),
    'triangular': (lambda p: triang_on(p['a'], p['c'], p['b']),
                   [dict(a=0, c=1, b=3), dict(a=-2, c=-2, b=5), dict(a=1, c=4, b=4)]),
    'logtriangular': (logtriang, [dict(a=0.1, c=1, b=100), dict(a=2, c=40, b=50)]),
    'dtriangular': (dtriang, [dict(a=0, c=1, b=3), dict(a=-5, c=4, b=4.5)]),
    'logdtriangular': (logdtriang, [dict(a=0.1, c=1, b=100), dict(a=1e-3, c=0.5, b=2)]),
    'pert': (pert, [dict(a=0, c=1, b=3, **{'lambda': 4}), dict(a=10, c=12, b=30, **{'lambda': 2.5})]),
    'beta': (lambda p: st.beta(p['alpha'], p['beta'], loc=p['lo'], scale=p['hi'] - p['lo']),
             [dict(alpha=2, beta=5, lo=0, hi=1), dict(alpha=0.5, beta=0.5, lo=0, hi=1),
              dict(alpha=0.2, beta=3, lo=-1, hi=4), dict(alpha=300, beta=150, lo=0, hi=1)]),
    'trapezoidal': (lambda p: st.trapezoid(c=(p['b'] - p['a']) / (p['d'] - p['a']), d=(p['c'] - p['a']) / (p['d'] - p['a']),
                                           loc=p['a'], scale=p['d'] - p['a']),
                    [dict(a=0, b=1, c=2, d=4), dict(a=-1, b=-1, c=3, d=3.5)]),
    'gamma': (lambda p: st.gamma(p['k'], scale=p['theta']),
              [dict(k=2, theta=1), dict(k=0.05, theta=3), dict(k=500, theta=0.01), dict(k=1, theta=2)]),
    'exponential': (lambda p: st.expon(scale=1 / p['lambda']), [{'lambda': 1}, {'lambda': 3e-4}]),
    'weibull': (lambda p: st.weibull_min(p['k'], scale=p['lambda']),
                [dict(k=1.5, **{'lambda': 1}), dict(k=0.4, **{'lambda': 10}), dict(k=12, **{'lambda': 3}), dict(k=60, **{'lambda': 1})]),
    'chisquare': (lambda p: st.chi2(p['k']), [dict(k=3), dict(k=0.5), dict(k=200)]),
    'f': (lambda p: st.f(p['d1'], p['d2']), [dict(d1=5, d2=10), dict(d1=1, d2=3), dict(d1=20, d2=50), dict(d1=3, d2=9.5)]),
    'pareto': (lambda p: st.pareto(b=p['alpha'], scale=p['xm']), [dict(xm=1, alpha=3), dict(xm=2, alpha=1.5), dict(xm=0.5, alpha=5)]),
    'rayleigh': (lambda p: st.rayleigh(scale=p['sigma']), [dict(sigma=1), dict(sigma=0.03)]),
    'halfnormal': (lambda p: st.halfnorm(scale=p['sigma']), [dict(sigma=1), dict(sigma=7)]),
    'invgauss': (lambda p: st.invgauss(p['mu'] / p['lambda'], scale=p['lambda']),
                 [dict(mu=1, **{'lambda': 3}), dict(mu=2.5, **{'lambda': 0.4}), dict(mu=0.1, **{'lambda': 50})]),
    'invgamma': (lambda p: st.invgamma(p['alpha'], scale=p['beta']), [dict(alpha=3, beta=2), dict(alpha=0.8, beta=1), dict(alpha=10, beta=0.5)]),
    'loglogistic': (lambda p: st.fisk(c=p['beta'], scale=p['alpha']), [dict(alpha=1, beta=4), dict(alpha=3, beta=1.5), dict(alpha=0.2, beta=9)]),
    'logistic': (lambda p: st.logistic(p['mu'], p['s']), [dict(mu=0, s=1), dict(mu=-40, s=0.5)]),
    'laplace': (lambda p: st.laplace(p['mu'], p['b']), [dict(mu=0, b=1), dict(mu=3, b=10)]),
    'cauchy': (lambda p: st.cauchy(p['x0'], p['gamma']), [dict(x0=0, gamma=1), dict(x0=5, gamma=0.1)]),
    'studentt': (lambda p: st.t(p['nu'], p['mu'], p['sigma']),
                 [dict(nu=5, mu=0, sigma=1), dict(nu=1.5, mu=2, sigma=3), dict(nu=0.7, mu=0, sigma=1),
                  dict(nu=50, mu=-1, sigma=0.2), dict(nu=4.5, mu=0, sigma=1)]),
    'gumbel': (lambda p: st.gumbel_r(p['mu'], p['beta']), [dict(mu=0, beta=1), dict(mu=100, beta=15)]),
    'gumbelmin': (lambda p: st.gumbel_l(p['mu'], p['beta']), [dict(mu=0, beta=1), dict(mu=-3, beta=0.2)]),
    'gev': (lambda p: st.genextreme(-p['xi'], p['mu'], p['sigma']),
            [dict(mu=0, sigma=1, xi=0.1), dict(mu=0, sigma=1, xi=-0.3), dict(mu=2, sigma=0.5, xi=0.6),
             dict(mu=0, sigma=1, xi=0.0005), dict(mu=1, sigma=2, xi=-1.5), dict(mu=0, sigma=1, xi=0.3)]),
    'genpareto': (lambda p: st.genpareto(p['xi'], p['mu'], p['sigma']),
                  [dict(mu=0, sigma=1, xi=0.2), dict(mu=0, sigma=1, xi=-0.25), dict(mu=1, sigma=2, xi=0.6), dict(mu=0, sigma=1, xi=1e-9)]),
}

DISC = {
    'bernoulli': (lambda p: st.bernoulli(p['p']), [dict(p=0.3), dict(p=0.9)]),
    'binomial': (lambda p: st.binom(p['n'], p['p']), [dict(n=10, p=0.3), dict(n=1000, p=0.02), dict(n=5000000, p=0.4), dict(n=7, p=1e-3)]),
    'poisson': (lambda p: st.poisson(p['lambda']), [{'lambda': 4}, {'lambda': 0.01}, {'lambda': 1e5}, {'lambda': 37.5}]),
    'negbinomial': (lambda p: st.nbinom(p['r'], p['p']), [dict(r=3, p=0.4), dict(r=0.5, p=0.05), dict(r=100, p=0.9)]),
    'geometric': (lambda p: st.geom(p['p'], loc=-1), [dict(p=0.3), dict(p=0.001), dict(p=0.97)]),
    'hypergeometric': (lambda p: st.hypergeom(p['N'], p['K'], p['n']), [dict(N=50, K=10, n=12), dict(N=1000, K=300, n=100)]),
    'discreteuniform': (lambda p: st.randint(p['a'], p['b'] + 1), [dict(a=1, b=6), dict(a=-5, b=20)]),
    'betabinomial': (lambda p: st.betabinom(p['n'], p['alpha'], p['beta']), [dict(n=10, alpha=2, beta=3), dict(n=60, alpha=0.5, beta=0.7)]),
}


def case(D, discrete):
    out = {}
    lo, hi = D.support()
    if discrete:
        ks = sorted(set(int(v) for v in D.ppf(U) if np.isfinite(v)) | {int(lo) if np.isfinite(lo) else 0})
        ks = [k for k in ks] + [ks[0] - 1, ks[-1] + 1]
        out['x'] = ks
        out['logpdf'] = [num(v) for v in st.rv_discrete.logpmf(D, ks)] if False else [num(D.logpmf(k)) for k in ks]
    else:
        xs = [float(v) for v in D.ppf(U) if np.isfinite(v)]
        if np.isfinite(lo):
            xs.append(float(lo) - 1)
        if np.isfinite(hi):
            xs.append(float(hi) + 1)
        out['x'] = xs
        out['logpdf'] = [num(v) for v in D.logpdf(xs)]
    out['cdf'] = [num(v) for v in D.cdf(out['x'])]
    out['sf'] = [num(v) for v in D.sf(out['x'])]
    out['u'] = U
    out['ppf'] = [num(v) for v in D.ppf(U)]
    out['q'] = Q
    out['isf'] = [num(v) for v in D.isf(Q)]
    m, v, s, k = D.stats(moments='mvsk')
    out['stats'] = {'mean': num(m), 'variance': num(v), 'skewness': num(s), 'kurtosis': num(k),
                    'entropy': num(D.entropy()), 'median': num(D.median())}
    return out


# ---- the arbiter ---------------------------------------------------------------------
#
# Where SciPy is known to lose precision, the values come from mpmath at 40
# digits instead, and the case lists what was replaced under 'arbiter'.
# Found by disagreement with the engine and confirmed one by one: the F's
# and inverse Gaussian's far-tail quantiles (SciPy off by 1e-5), the
# half-normal's quantiles below 1e-6 (SciPy takes ndtri of (1 + u)/2), a
# survival function SciPy forms as 1 - cdf, the binomial for millions of
# trials (SciPy off by 1e-9), the GEV's skewness and kurtosis near xi = 0
# and the log-uniform's over a narrow range (cancellation in SciPy's
# formulas), and the entropy of a discrete distribution (SciPy's sum stops
# early: half the value for a Poisson of mean 1e5).

import mpmath as mp

mp.mp.dps = 40


def mpf(v):
    """The double itself, exactly: mp.mpf(float) converts the binary value, where a decimal string would not."""
    return mp.mpf(float(v))


def mp_root(F, target, x0, lo=None, hi=None):
    """x with F(x) = target, F increasing, polished from SciPy's x0 by bisection on a bracket."""
    x0 = mpf(x0)
    a = x0 * (1 - mp.mpf('1e-3')) if x0 > 0 else x0 - mp.mpf('1e-3')
    b = x0 * (1 + mp.mpf('1e-3')) if x0 > 0 else x0 + mp.mpf('1e-3')
    if lo is not None:
        a = max(a, mpf(lo))
    if hi is not None:
        b = min(b, mpf(hi))
    for _ in range(200):
        if F(a) <= target:
            break
        a = a - (b - a)
    for _ in range(200):
        if F(b) >= target:
            break
        b = b + (b - a)
    for _ in range(400):
        m = (a + b) / 2
        if F(m) < target:
            a = m
        else:
            b = m
        if b - a <= abs(m) * mp.mpf('1e-30'):
            break
    return (a + b) / 2


def arbiter(fid, p, D, out, discrete):
    done = []
    if fid in ('triangular', 'logtriangular', 'pareto', 'loguniform'):
        if fid == 'pareto':
            xm, al = mpf(p['xm']), mpf(p['alpha'])
            cdf = lambda x: 1 - (xm / x) ** al if x > xm else mp.mpf(0)
        elif fid == 'loguniform':
            la, lb = mp.log(mpf(p['a'])), mp.log(mpf(p['b']))
            cdf = lambda x: mp.mpf(0) if x <= 0 or mp.log(x) <= la else (mp.mpf(1) if mp.log(x) >= lb else (mp.log(x) - la) / (lb - la))
        else:
            lg = fid == 'logtriangular'
            a, c, b = (mp.log(mpf(p[k])) if lg else mpf(p[k]) for k in ('a', 'c', 'b'))

            def cdf(x):
                if lg and x <= 0:
                    return mp.mpf(0)
                y = mp.log(x) if lg else x
                if y <= a:
                    return mp.mpf(0)
                if y >= b:
                    return mp.mpf(1)
                return (y - a) ** 2 / ((b - a) * (c - a)) if y <= c else 1 - (b - y) ** 2 / ((b - a) * (b - c))
        out['cdf'] = [num(cdf(mpf(x))) for x in out['x']]
        out['sf'] = [num(1 - cdf(mpf(x))) for x in out['x']]
        done.append('cdf and sf')
    if fid == 'f':
        d1, d2 = mpf(p['d1']), mpf(p['d2'])
        F = lambda x: mp.betainc(d1 / 2, d2 / 2, 0, d1 * x / (d1 * x + d2), regularized=True)
        S = lambda x: mp.betainc(d1 / 2, d2 / 2, d1 * x / (d1 * x + d2), 1, regularized=True)
        tail_quantiles(out, F, S, lo=0)
        done.append('far-tail quantiles')
    if fid == 'invgauss':
        mu, lam = mpf(p['mu']), mpf(p['lambda'])

        def F(x):
            r = mp.sqrt(lam / x)
            return mp.ncdf(r * (x / mu - 1)) + mp.exp(2 * lam / mu) * mp.ncdf(-r * (x / mu + 1))

        def S(x):
            r = mp.sqrt(lam / x)
            return mp.ncdf(-r * (x / mu - 1)) - mp.exp(2 * lam / mu) * mp.ncdf(-r * (x / mu + 1))
        tail_quantiles(out, F, S, lo=0)
        done.append('far-tail quantiles')
    if fid == 'halfnormal':
        sg = mpf(p['sigma'])
        out['ppf'] = [num(sg * mp.sqrt(2) * mp.erfinv(mpf(u))) if u <= 1e-3 else out['ppf'][i] for i, u in enumerate(out['u'])]
        done.append('small quantiles')
    if fid == 'studentt':
        out['ppf'] = [num(p['mu']) if u == 0.5 else out['ppf'][i] for i, u in enumerate(out['u'])]
        done.append('the median, which is mu by symmetry')
    if fid == 'loguniform':
        a, b = mpf(p['a']), mpf(p['b'])
        L = mp.log(b / a)
        raw = [(b ** k - a ** k) / (k * L) for k in range(1, 5)]
        m = raw[0]
        c2 = raw[1] - m ** 2
        c3 = raw[2] - 3 * m * raw[1] + 2 * m ** 3
        c4 = raw[3] - 4 * m * raw[2] + 6 * m ** 2 * raw[1] - 3 * m ** 4
        out['stats'].update(mean=num(m), variance=num(c2), skewness=num(c3 / c2 ** 1.5), kurtosis=num(c4 / c2 ** 2 - 3))
        done.append('moments')
    if fid == 'gev' and abs(p['xi']) < 0.01:
        xi = mpf(p['xi'])
        g = [mp.gamma(1 - k * xi) for k in range(1, 5)]
        v = g[1] - g[0] ** 2
        out['stats']['skewness'] = num(mp.sign(xi) * (g[2] - 3 * g[0] * g[1] + 2 * g[0] ** 3) / v ** 1.5)
        out['stats']['kurtosis'] = num((g[3] - 4 * g[0] * g[2] + 6 * g[1] * g[0] ** 2 - 3 * g[0] ** 4) / v ** 2 - 3)
        done.append('skewness and kurtosis')
    if fid == 'binomial' and p['n'] >= 1e6:
        n, pr = p['n'], mpf(p['p'])
        lpmf = lambda k: mp.loggamma(n + 1) - mp.loggamma(k + 1) - mp.loggamma(n - k + 1) + k * mp.log(pr) + (n - k) * mp.log(1 - pr)
        out['logpdf'] = [num(lpmf(k)) if 0 <= k <= n else '-inf' for k in out['x']]
        sd = math.sqrt(n * p['p'] * (1 - p['p']))
        start = int(n * p['p'] - 40 * sd)
        top = int(n * p['p'] + 40 * sd)
        cum, t, k = {}, mp.exp(lpmf(start)), start
        run = t
        wanted = set(out['x'])
        while k <= top:
            if k in wanted:
                cum[k] = run
            t = t * (n - k) / (k + 1) * pr / (1 - pr)
            k += 1
            run += t
        out['cdf'] = [num(cum[k]) if k in cum else out['cdf'][i] for i, k in enumerate(out['x'])]
        out['sf'] = [num(1 - cum[k]) if k in cum else out['sf'][i] for i, k in enumerate(out['x'])]
        done.append('log-probabilities, cdf and sf')
    if discrete:
        s0, s1 = D.support()
        m, v = D.stats(moments='mv')
        lo = s0 if np.isfinite(s0) else int(m - 80 * math.sqrt(v) - 200)
        hi = s1 if np.isfinite(s1) else int(m + 80 * math.sqrt(v) + 200)
        ks = np.arange(lo, hi + 1)
        lp = D.logpmf(ks)
        pk = np.exp(lp)
        out['stats']['entropy'] = num(-np.sum(pk[pk > 0] * lp[pk > 0]))
        done.append('entropy by summation')
    if done:
        out['arbiter'] = done


def tail_quantiles(out, F, S, lo=None):
    out['ppf'] = [num(mp_root(F, mpf(u), v, lo=lo)) if u <= 1e-3 and v not in ('nan', 'inf', '-inf') else v
                  for u, v in zip(out['u'], out['ppf'])]
    out['isf'] = [num(mp_root(lambda x: -S(x), -mpf(q), v, lo=lo)) if q <= 1e-3 and v not in ('nan', 'inf', '-inf') else v
                  for q, v in zip(out['q'], out['isf'])]


def build_cases():
    cases = []
    for fid, (make, sets) in CONT.items():
        for p in sets:
            D = make(p)
            out = case(D, False)
            arbiter(fid, p, D, out, False)
            cases.append({'family': fid, 'params': p, **out})
    for fid, (make, sets) in DISC.items():
        for p in sets:
            D = make(p)
            out = case(D, True)
            arbiter(fid, p, D, out, True)
            cases.append({'family': fid, 'params': p, **out})
    return cases


# ---- fits ------------------------------------------------------------------------------

rs = np.random.default_rng(20261004)


def sig(x):
    """Six significant figures, so that the sample in the file is the sample fitted."""
    return np.array([float(f'{v:.6g}') for v in x])


FIT = {
    # family: (sampler, scipy fit -> our canonical params)
    'normal': (lambda n: st.norm(3, 2).rvs(n, random_state=rs), lambda x: dict(zip(['mu', 'sigma'], st.norm.fit(x)))),
    'lognormal': (lambda n: st.lognorm(0.8, scale=5).rvs(n, random_state=rs),
                  lambda x: (lambda s, l, sc: dict(mu=math.log(sc), sigma=s))(*st.lognorm.fit(x, floc=0))),
    'gamma': (lambda n: st.gamma(2.5, scale=3).rvs(n, random_state=rs),
              lambda x: (lambda a, l, sc: dict(k=a, theta=sc))(*st.gamma.fit(x, floc=0))),
    'weibull': (lambda n: st.weibull_min(1.7, scale=4).rvs(n, random_state=rs),
                lambda x: (lambda c, l, sc: {'k': c, 'lambda': sc})(*st.weibull_min.fit(x, floc=0))),
    'exponential': (lambda n: st.expon(scale=2).rvs(n, random_state=rs),
                    lambda x: (lambda l, sc: {'lambda': 1 / sc})(*st.expon.fit(x, floc=0))),
    'beta': (lambda n: st.beta(2, 5).rvs(n, random_state=rs),
             lambda x: (lambda a, b, l, sc: dict(alpha=a, beta=b, lo=0, hi=1))(*st.beta.fit(x, floc=0, fscale=1))),
    'gumbel': (lambda n: st.gumbel_r(10, 3).rvs(n, random_state=rs), lambda x: dict(zip(['mu', 'beta'], st.gumbel_r.fit(x)))),
    'gumbelmin': (lambda n: st.gumbel_l(10, 3).rvs(n, random_state=rs), lambda x: dict(zip(['mu', 'beta'], st.gumbel_l.fit(x)))),
    'logistic': (lambda n: st.logistic(1, 2).rvs(n, random_state=rs), lambda x: dict(zip(['mu', 's'], st.logistic.fit(x)))),
    'laplace': (lambda n: st.laplace(1, 2).rvs(n, random_state=rs), lambda x: dict(zip(['mu', 'b'], st.laplace.fit(x)))),
    'cauchy': (lambda n: st.cauchy(1, 2).rvs(n, random_state=rs), lambda x: dict(zip(['x0', 'gamma'], st.cauchy.fit(x)))),
    'studentt': (lambda n: st.t(4, 1, 2).rvs(n, random_state=rs),
                 lambda x: (lambda df, l, sc: dict(nu=df, mu=l, sigma=sc))(*st.t.fit(x))),
    'gev': (lambda n: st.genextreme(-0.15, 5, 2).rvs(n, random_state=rs),
            lambda x: (lambda c, l, sc: dict(mu=l, sigma=sc, xi=-c))(*st.genextreme.fit(x))),
    'genpareto': (lambda n: st.genpareto(0.2, 0, 2).rvs(n, random_state=rs),
                  lambda x: (lambda c, l, sc: dict(mu=0, sigma=sc, xi=c))(*st.genpareto.fit(x, floc=0))),
    'rayleigh': (lambda n: st.rayleigh(scale=3).rvs(n, random_state=rs),
                 lambda x: (lambda l, sc: dict(sigma=sc))(*st.rayleigh.fit(x, floc=0))),
    'halfnormal': (lambda n: st.halfnorm(scale=3).rvs(n, random_state=rs),
                   lambda x: (lambda l, sc: dict(sigma=sc))(*st.halfnorm.fit(x, floc=0))),
    'invgauss': (lambda n: st.invgauss(0.5, scale=4).rvs(n, random_state=rs),
                 lambda x: (lambda m, l, sc: {'mu': m * sc, 'lambda': sc})(*st.invgauss.fit(x, floc=0))),
    'invgamma': (lambda n: st.invgamma(4, scale=3).rvs(n, random_state=rs),
                 lambda x: (lambda a, l, sc: dict(alpha=a, beta=sc))(*st.invgamma.fit(x, floc=0))),
    'loglogistic': (lambda n: st.fisk(3, scale=2).rvs(n, random_state=rs),
                    lambda x: (lambda c, l, sc: dict(alpha=sc, beta=c))(*st.fisk.fit(x, floc=0))),
    'chisquare': (lambda n: st.chi2(4).rvs(n, random_state=rs),
                  lambda x: (lambda df, l, sc: dict(k=df))(*st.chi2.fit(x, floc=0, fscale=1))),
    'f': (lambda n: st.f(6, 12).rvs(n, random_state=rs),
          lambda x: (lambda a, b, l, sc: dict(d1=a, d2=b))(*st.f.fit(x, floc=0, fscale=1))),
    'triangular': (lambda n: triang_on(1, 3, 8).rvs(n, random_state=rs),
                   lambda x: (lambda c, l, sc: dict(a=l, c=l + c * sc, b=l + sc))(*st.triang.fit(x))),
    'pareto': (lambda n: st.pareto(3, scale=2).rvs(n, random_state=rs),
               lambda x: (lambda b, l, sc: dict(xm=sc, alpha=b))(*st.pareto.fit(x, floc=0))),
}


def disc_fit(logpmf, z0, x):
    res = optimize.minimize(lambda z: -np.sum(logpmf(x, z)), z0, method='Nelder-Mead',
                            options={'xatol': 1e-12, 'fatol': 1e-12, 'maxiter': 20000})
    return res.x


DFIT = {
    'poisson': (lambda n: st.poisson(3.7).rvs(n, random_state=rs), lambda x: {'lambda': float(np.mean(x))}),
    'geometric': (lambda n: st.geom(0.25, loc=-1).rvs(n, random_state=rs), lambda x: {'p': 1 / (1 + float(np.mean(x)))}),
    'negbinomial': (lambda n: st.nbinom(2.5, 0.3).rvs(n, random_state=rs),
                    lambda x: (lambda z: dict(r=math.exp(z[0]), p=math.exp(z[0]) / (math.exp(z[0]) + np.mean(x))))(
                        disc_fit(lambda x, z: st.nbinom.logpmf(x, math.exp(z[0]), math.exp(z[0]) / (math.exp(z[0]) + np.mean(x))),
                                 [0.5], x))),
}


def loglik(D, x, discrete):
    return float(np.sum(D.logpmf(x) if discrete else D.logpdf(x)))


def build_fits():
    fits = []
    for fid, (draw, fit) in FIT.items():
        x = sig(draw(150))
        p = {k: float(v) for k, v in fit(x).items()}
        make = CONT[fid][0]
        fits.append({'family': fid, 'data': list(x), 'scipy': p, 'logL': loglik(make(p), x, False)})
    for fid, (draw, fit) in DFIT.items():
        x = draw(150).astype(float)
        p = {k: float(v) for k, v in fit(x).items()}
        make = DISC[fid][0]
        fits.append({'family': fid, 'data': list(x), 'scipy': p, 'logL': loglik(make(p), x, True)})
    return fits


# ---- truncation -------------------------------------------------------------------------

TRUNC = [
    ('normal', dict(mu=0, sigma=1), 0.0, None),
    ('normal', dict(mu=0, sigma=1), 8.0, 9.0),
    ('normal', dict(mu=10, sigma=2), None, 7.0),
    ('lognormal', dict(mu=0, sigma=1), 0.5, 3.0),
    ('gamma', dict(k=2, theta=1), 1.0, None),
    ('cauchy', dict(x0=0, gamma=1), -5.0, 5.0),
    ('studentt', dict(nu=1.5, mu=0, sigma=1), -10.0, 4.0),
    ('weibull', dict(k=0.6, **{'lambda': 2}), 0.1, 50.0),
]
DTRUNC = [
    ('poisson', {'lambda': 4}, 2, 9),
    ('binomial', dict(n=20, p=0.3), 1, None),
    ('negbinomial', dict(r=3, p=0.4), None, 6),
]


def build_trunc():
    out = []
    for fid, p, lo, hi in TRUNC:
        D = CONT[fid][0](p)
        a = -math.inf if lo is None else lo
        b = math.inf if hi is None else hi
        Fa, Fb = (0.0 if lo is None else D.cdf(lo)), (1.0 if hi is None else D.cdf(hi))
        Sa, Sb = (1.0 if lo is None else D.sf(lo)), (0.0 if hi is None else D.sf(hi))
        Z = Sa - Sb if Fa > 0.5 else Fb - Fa
        mlo = a if np.isfinite(a) else D.ppf(1e-300)
        mhi = b if np.isfinite(b) else D.isf(1e-300)
        quad = lambda f: integrate.quad(lambda x: f(x) * D.pdf(x) / Z, mlo, mhi, limit=500, epsabs=0, epsrel=1e-13,
                                        points=[v for v in (D.median(),) if mlo < v < mhi])[0]
        mean = quad(lambda x: x)
        var = quad(lambda x: (x - mean) ** 2)
        us = [0.01, 0.25, 0.5, 0.75, 0.99]
        qs = []
        # the truncated CDF from whichever side of the distribution keeps its digits
        Ft = (lambda x: (Sa - D.sf(x)) / Z) if Fa > 0.5 else (lambda x: (D.cdf(x) - Fa) / Z)
        for u in us:
            qs.append(optimize.brentq(lambda x: Ft(x) - u, mlo, mhi, xtol=1e-300, rtol=1e-15, maxiter=1000))
        out.append({'family': fid, 'params': p, 'lo': lo, 'hi': hi, 'mass': Z, 'mean': mean, 'variance': var, 'u': us, 'q': qs})
    for fid, p, lo, hi in DTRUNC:
        D = DISC[fid][0](p)
        a = D.support()[0] if lo is None else lo
        b = int(D.isf(1e-18)) + 5 if hi is None else hi
        ks = np.arange(a, b + 1)
        pk = D.pmf(ks)
        Z = pk.sum()
        pk = pk / Z
        mean = float((ks * pk).sum())
        var = float((((ks - mean) ** 2) * pk).sum())
        cum = np.cumsum(pk)
        us = [0.01, 0.25, 0.5, 0.75, 0.99]
        qs = [int(ks[np.searchsorted(cum, u - 1e-12)]) for u in us]
        out.append({'family': fid, 'params': p, 'lo': lo, 'hi': hi, 'mass': float(Z), 'mean': mean, 'variance': var, 'u': us, 'q': qs})
    return out


if __name__ == '__main__':
    import scipy
    out = {'scipy': scipy.__version__, 'numpy': np.__version__, 'cases': build_cases(), 'fits': build_fits(),
           'truncated': build_trunc()}
    path = os.path.join(HERE, 'scipy-ref.json')
    with open(path, 'w') as f:
        json.dump(out, f, indent=0)
    print(f'{len(out["cases"])} cases and {len(out["fits"])} fits written to {path}')
