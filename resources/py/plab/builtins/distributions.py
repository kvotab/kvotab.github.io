"""Probability distributions: the functions of each distribution (normpdf,
normcdf, norminv, normrnd, normstat and the like, with the fits and the
negative log-likelihoods of the common ones), the generic functions (pdf,
cdf, icdf, random), distribution objects (makedist, fitdist, mle, and
their methods: pdf, cdf, icdf, random, mean, median, std, var, iqr,
paramci, truncate, negloglik), the multivariate normal and t, and drawing
samples (randsample, datasample).

The distributions are SciPy's with the language's parameters: each entry
of DISTS says how its parameters, in the language's order, map onto
scipy.stats, which values are valid, and how it is fitted. Random numbers
come from the session's generator (rng).
"""
import math

import numpy as np

from . import bi
from ._util import err, nargchk, darr, out, opt_str, sval, num, is_str, dims_from, cellstr_list
from ..values import MError, Char, Cell, Struct, Str, FH, Obj, EMPTY, py_str
from .. import runtime as R


def _st():
    import scipy.stats as st
    return st


def _rs():
    from .elmat import RNG
    return RNG.rs


class Dist:
    """One distribution: its names, its parameters (in the language's order),
    the frozen scipy distribution they make, and which values are valid."""

    def __init__(self, name, code, objname, params, defaults, make, valid, safe, discrete=False,
                 mk_defaults=None, kinds=None, desc=None, fit=None):
        self.name = name                # 'Normal'
        self.code = code                # 'norm' (the prefix of normpdf...), or None
        self.objname = objname          # 'Normal' for makedist, or None
        self.params = params            # ('mu', 'sigma')
        self.defaults = defaults        # for normpdf(x): None where the parameter is required
        self.make = make                # (*params) -> frozen scipy distribution
        self.valid = valid              # (*params) -> boolean array
        self.safe = safe                # a valid value of each parameter, for the invalid places
        self.discrete = discrete
        self.mk_defaults = mk_defaults or tuple(d if d is not None else 1.0 for d in defaults)
        self.kinds = kinds or ('real',) * len(params)       # 'real', 'pos' or 'prob': how intervals are made
        self.desc = desc or params
        self.fit = fit                  # (x, alpha) -> (values, intervals 2 x k, covariance) or None

    def frozen(self, params):
        """The frozen distribution and where the parameters are valid (params broadcast)."""
        with np.errstate(all='ignore'):
            ok = np.asarray(self.valid(*params), bool)
        safe = [np.where(ok, p, s) for p, s in zip(params, self.safe)]
        with np.errstate(all='ignore'):
            return self.make(*safe), ok


def _isint(v):
    return np.isfinite(v) & (v == np.floor(v))


def _pos(*a):
    out_ = True
    for x in a:
        out_ = out_ & (x > 0)
    return out_


DISTS = {}


def _add(d):
    DISTS[d.name] = d
    return d


def _define():
    st = _st()
    exp = np.exp
    _add(Dist('Normal', 'norm', 'Normal', ('mu', 'sigma'), (0.0, 1.0), lambda m, s: st.norm(m, s),
              lambda m, s: np.isfinite(m) & (s > 0), (0.0, 1.0), kinds=('real', 'pos'), desc=('mean', 'standard deviation')))
    _add(Dist('Lognormal', 'logn', 'Lognormal', ('mu', 'sigma'), (0.0, 1.0), lambda m, s: st.lognorm(s, scale=exp(m)),
              lambda m, s: np.isfinite(m) & (s > 0), (0.0, 1.0), kinds=('real', 'pos'), desc=('log mean', 'log standard deviation')))
    _add(Dist('Exponential', 'exp', 'Exponential', ('mu',), (1.0,), lambda m: st.expon(scale=m),
              lambda m: m > 0, (1.0,), kinds=('pos',), desc=('mean',)))
    _add(Dist('Gamma', 'gam', 'Gamma', ('a', 'b'), (None, 1.0), lambda a, b: st.gamma(a, scale=b),
              lambda a, b: _pos(a, b), (1.0, 1.0), kinds=('pos', 'pos'), desc=('shape', 'scale')))
    _add(Dist('Beta', 'beta', 'Beta', ('a', 'b'), (None, None), lambda a, b: st.beta(a, b),
              lambda a, b: _pos(a, b), (1.0, 1.0), kinds=('pos', 'pos'), desc=('first shape', 'second shape')))
    _add(Dist('Weibull', 'wbl', 'Weibull', ('A', 'B'), (1.0, 1.0), lambda A, B: st.weibull_min(B, scale=A),
              lambda A, B: _pos(A, B), (1.0, 1.0), kinds=('pos', 'pos'), desc=('scale', 'shape')))
    _add(Dist('Uniform', 'unif', 'Uniform', ('Lower', 'Upper'), (0.0, 1.0), lambda a, b: st.uniform(a, b - a),
              lambda a, b: np.isfinite(a) & np.isfinite(b) & (a < b), (0.0, 1.0), desc=('lower limit', 'upper limit')))
    _add(Dist('Discrete Uniform', 'unid', None, ('N',), (None,), lambda n: st.randint(1, n + 1),
              lambda n: _isint(n) & (n >= 1), (1.0,), discrete=True, desc=('maximum value',)))
    _add(Dist('Binomial', 'bino', 'Binomial', ('N', 'p'), (None, None), lambda n, p: st.binom(n, p),
              lambda n, p: _isint(n) & (n >= 0) & (p >= 0) & (p <= 1), (1.0, 0.5), discrete=True,
              mk_defaults=(1.0, 0.5), kinds=('real', 'prob'), desc=('number of trials', 'probability of success')))
    _add(Dist('Poisson', 'poiss', 'Poisson', ('lambda',), (None,), lambda l: st.poisson(l),
              lambda l: np.isfinite(l) & (l >= 0), (1.0,), discrete=True, kinds=('pos',), desc=('mean',)))
    _add(Dist('Geometric', 'geo', None, ('p',), (None,), lambda p: st.geom(p, loc=-1),
              lambda p: (p > 0) & (p <= 1), (0.5,), discrete=True, kinds=('prob',), desc=('probability of success',)))
    _add(Dist('Negative Binomial', 'nbin', 'NegativeBinomial', ('R', 'p'), (None, None), lambda r, p: st.nbinom(r, p),
              lambda r, p: (r > 0) & np.isfinite(r) & (p > 0) & (p <= 1), (1.0, 0.5), discrete=True,
              mk_defaults=(1.0, 0.5), kinds=('pos', 'prob'), desc=('number of successes', 'probability of success')))
    _add(Dist('Hypergeometric', 'hyge', None, ('M', 'K', 'N'), (None, None, None), lambda M, K, N: st.hypergeom(M, K, N),
              lambda M, K, N: _isint(M) & _isint(K) & _isint(N) & (M >= 0) & (K >= 0) & (N >= 0) & (K <= M) & (N <= M),
              (1.0, 1.0, 1.0), discrete=True, desc=('population size', 'successes in the population', 'draws')))
    _add(Dist('Chi-square', 'chi2', None, ('nu',), (None,), lambda v: st.chi2(v), lambda v: v > 0, (1.0,),
              desc=('degrees of freedom',)))
    _add(Dist('Noncentral Chi-square', 'ncx2', None, ('nu', 'delta'), (None, None), lambda v, d: st.ncx2(v, d),
              lambda v, d: (v > 0) & (d >= 0), (1.0, 1.0), desc=('degrees of freedom', 'noncentrality')))
    _add(Dist('t', 't', None, ('nu',), (None,), lambda v: st.t(v), lambda v: v > 0, (1.0,), desc=('degrees of freedom',)))
    _add(Dist('Noncentral t', 'nct', None, ('nu', 'delta'), (None, None), lambda v, d: st.nct(v, d),
              lambda v, d: (v > 0) & np.isfinite(d), (1.0, 0.0), desc=('degrees of freedom', 'noncentrality')))
    _add(Dist('F', 'f', None, ('nu1', 'nu2'), (None, None), lambda a, b: st.f(a, b), lambda a, b: _pos(a, b), (1.0, 1.0),
              desc=('numerator degrees of freedom', 'denominator degrees of freedom')))
    _add(Dist('Noncentral F', 'ncf', None, ('nu1', 'nu2', 'delta'), (None, None, None), lambda a, b, d: st.ncf(a, b, d),
              lambda a, b, d: _pos(a, b) & (d >= 0), (1.0, 1.0, 0.0),
              desc=('numerator degrees of freedom', 'denominator degrees of freedom', 'noncentrality')))
    _add(Dist('Extreme Value', 'ev', 'ExtremeValue', ('mu', 'sigma'), (0.0, 1.0), lambda m, s: st.gumbel_l(m, s),
              lambda m, s: np.isfinite(m) & (s > 0), (0.0, 1.0), kinds=('real', 'pos'), desc=('location', 'scale')))
    _add(Dist('Generalized Extreme Value', 'gev', 'GeneralizedExtremeValue', ('k', 'sigma', 'mu'), (None, None, None),
              lambda k, s, m: st.genextreme(-k, m, s), lambda k, s, m: np.isfinite(k) & (s > 0) & np.isfinite(m),
              (0.0, 1.0, 0.0), mk_defaults=(0.0, 1.0, 0.0), kinds=('real', 'pos', 'real'), desc=('shape', 'scale', 'location')))
    _add(Dist('Generalized Pareto', 'gp', 'GeneralizedPareto', ('k', 'sigma', 'theta'), (None, 1.0, 0.0),
              lambda k, s, t: st.genpareto(k, t, s), lambda k, s, t: np.isfinite(k) & (s > 0) & np.isfinite(t),
              (0.0, 1.0, 0.0), mk_defaults=(1.0, 1.0, 0.0), kinds=('real', 'pos', 'real'), desc=('shape', 'scale', 'threshold')))
    _add(Dist('Rayleigh', 'rayl', 'Rayleigh', ('B',), (1.0,), lambda b: st.rayleigh(scale=b), lambda b: b > 0, (1.0,),
              kinds=('pos',), desc=('scale',)))
    # the ones made with makedist only (and the generic functions)
    _add(Dist('Logistic', None, 'Logistic', ('mu', 'sigma'), (0.0, 1.0), lambda m, s: st.logistic(m, s),
              lambda m, s: np.isfinite(m) & (s > 0), (0.0, 1.0), kinds=('real', 'pos'), desc=('mean', 'scale')))
    _add(Dist('Loglogistic', None, 'Loglogistic', ('mu', 'sigma'), (0.0, 1.0), lambda m, s: st.fisk(1 / s, scale=exp(m)),
              lambda m, s: np.isfinite(m) & (s > 0), (0.0, 1.0), kinds=('real', 'pos'), desc=('log location', 'log scale')))
    _add(Dist('Inverse Gaussian', None, 'InverseGaussian', ('mu', 'lambda'), (1.0, 1.0), lambda m, l: st.invgauss(m / l, scale=l),
              lambda m, l: _pos(m, l), (1.0, 1.0), kinds=('pos', 'pos'), desc=('mean', 'shape')))
    _add(Dist('Nakagami', None, 'Nakagami', ('mu', 'omega'), (1.0, 1.0), lambda m, w: st.nakagami(m, scale=np.sqrt(w)),
              lambda m, w: (m >= 0.5) & (w > 0), (1.0, 1.0), kinds=('pos', 'pos'), desc=('shape', 'scale')))
    _add(Dist('Rician', None, 'Rician', ('s', 'sigma'), (1.0, 1.0), lambda s, g: st.rice(s / g, scale=g),
              lambda s, g: (s >= 0) & (g > 0), (1.0, 1.0), kinds=('pos', 'pos'), desc=('noncentrality', 'scale')))
    _add(Dist('Birnbaum-Saunders', None, 'BirnbaumSaunders', ('beta', 'gamma'), (1.0, 1.0),
              lambda b, g: st.fatiguelife(g, scale=b), lambda b, g: _pos(b, g), (1.0, 1.0), kinds=('pos', 'pos'),
              desc=('scale', 'shape')))
    _add(Dist('Burr', None, 'Burr', ('alpha', 'c', 'k'), (1.0, 1.0, 1.0), lambda a, c, k: st.burr12(c, k, scale=a),
              lambda a, c, k: _pos(a, c, k), (1.0, 1.0, 1.0), kinds=('pos', 'pos', 'pos'), desc=('scale', 'first shape', 'second shape')))
    _add(Dist('Half Normal', None, 'HalfNormal', ('mu', 'sigma'), (0.0, 1.0), lambda m, s: st.halfnorm(m, s),
              lambda m, s: np.isfinite(m) & (s > 0), (0.0, 1.0), kinds=('real', 'pos'), desc=('location', 'scale')))
    _add(Dist('tLocationScale', None, 'tLocationScale', ('mu', 'sigma', 'nu'), (0.0, 1.0, 5.0),
              lambda m, s, v: st.t(v, m, s), lambda m, s, v: np.isfinite(m) & _pos(s, v), (0.0, 1.0, 5.0),
              kinds=('real', 'pos', 'pos'), desc=('location', 'scale', 'degrees of freedom')))
    _add(Dist('Triangular', None, 'Triangular', ('A', 'B', 'C'), (0.0, 0.5, 1.0),
              lambda a, b, c: st.triang((b - a) / (c - a), a, c - a), lambda a, b, c: (a <= b) & (b <= c) & (a < c),
              (0.0, 0.5, 1.0), desc=('lower limit', 'peak', 'upper limit')))
    _add(Dist('Loguniform', None, 'Loguniform', ('Lower', 'Upper'), (1.0, 4.0), lambda a, b: st.loguniform(a, b),
              lambda a, b: (a > 0) & (a < b), (1.0, 4.0), desc=('lower limit', 'upper limit')))


def _key(s):
    return ''.join(c for c in s.lower() if c.isalnum())


_NAMES = {}


def _names():
    if not _NAMES:
        if not DISTS:
            _define()
        for d in DISTS.values():
            _NAMES[_key(d.name)] = d
            if d.code:
                _NAMES[_key(d.code)] = d
            if d.objname:
                _NAMES[_key(d.objname)] = d
        _NAMES.update({'gaussian': DISTS['Normal'], 'chisq': DISTS['Chi-square'], 'student': DISTS['t'],
                       'studentt': DISTS['t'], 'weib': DISTS['Weibull'], 'negbin': DISTS['Negative Binomial']})
    return _NAMES


def find_dist(name, fn):
    """The distribution of a name: its whole name, its prefix (norm) or its
    makedist name, in any case, with or without spaces and hyphens."""
    names = _names()
    k = _key(name)
    d = names.get(k)
    if d is None:
        hits = {v.name for kk, v in names.items() if kk.startswith(k)} if len(k) >= 3 else set()
        if len(hits) == 1:
            d = DISTS[hits.pop()]
    if d is None:
        raise err('stats:probdists:UnrecognizedName', f"Unrecognized distribution name: '{name}'.", fn)
    return d


def dist_of(code):
    _names()
    for d in DISTS.values():
        if d.code == code:
            return d
    raise KeyError(code)


# ---- the functions of each distribution ------------------------------------------------------

def _params(d, args, fn, required=None):
    """The parameters from args, the defaults for those left out."""
    if len(args) > len(d.params):
        raise err('MATLAB:TooManyInputs', 'Too many input arguments.', fn)
    vals = []
    for i, p in enumerate(d.params):
        if i < len(args):
            vals.append(darr(args[i]).real.astype(float))
        elif d.defaults[i] is not None:
            vals.append(np.array(d.defaults[i]))
        else:
            raise err('MATLAB:minrhs', 'Not enough input arguments.', fn)
    return vals


def _common(arrays, fn):
    try:
        return np.broadcast_arrays(*arrays)
    except ValueError:
        raise err('stats:probdists:InputSizeMismatch', 'Non-scalar arguments must match in size.', fn)


def _value(d, method, x, params, fn):
    arrs = _common([x] + list(params), fn)
    x, params = arrs[0], arrs[1:]
    dist, ok = d.frozen(params)
    with np.errstate(all='ignore'):
        r = getattr(dist, method)(x)
    r = np.where(ok & ~np.isnan(x), r, np.nan).astype(float)
    return out(r if r.ndim >= 2 else r.reshape((1, -1)) if r.ndim == 1 else r.reshape(1, 1))


def _upper(args):
    """A trailing 'upper' (the probability above x)."""
    if args and opt_str(args[-1]) is not None and opt_str(args[-1]).lower() == 'upper':
        return list(args[:-1]), True
    return list(args), False


def _size_args(args, fn):
    if not args:
        return None
    shape, _, _ = dims_from(args, fn, allow_class=False)
    return shape


def draw(d, params, shape, fn):
    """Random numbers of a distribution: params broadcast to shape."""
    if shape is None:
        params = _common(params, fn)
        shape = params[0].shape if params else (1, 1)
        if len(shape) < 2:
            shape = (1, 1) if not shape else (1, shape[0])
    else:
        for p in params:
            if p.size != 1 and tuple(p.shape) != tuple(shape):
                raise err('stats:random:InputSizeMismatch', 'Size information is inconsistent.', fn)
        params = [np.broadcast_to(p.reshape(()) if p.size == 1 else p, shape) for p in params]
    if 0 in shape:
        return np.zeros(shape)
    with np.errstate(all='ignore'):
        ok = np.asarray(d.valid(*params), bool)
    safe = [np.where(ok, p, s) for p, s in zip(params, d.safe)]
    if d.discrete:
        # counts go to NumPy's samplers as integers (a float number of trials is refused)
        safe = [v.astype(np.int64) if np.all(np.isfinite(v)) and np.all(v == np.floor(v)) else v for v in safe]
    with np.errstate(all='ignore'):
        r = np.asarray(d.make(*safe).rvs(size=shape, random_state=_rs()), float)
    return np.where(ok, r, np.nan)


def _register(d):
    code = d.code

    @bi(code + 'pdf')
    def _pdf(nargout, *args):
        if not args:
            raise err('MATLAB:minrhs', 'Not enough input arguments.', code + 'pdf')
        x = darr(args[0]).real
        return _value(d, 'pmf' if d.discrete else 'pdf', x, _params(d, args[1:], code + 'pdf'), code + 'pdf')

    @bi(code + 'cdf')
    def _cdf(nargout, *args):
        args, upper = _upper(args)
        if not args:
            raise err('MATLAB:minrhs', 'Not enough input arguments.', code + 'cdf')
        x = darr(args[0]).real
        return _value(d, 'sf' if upper else 'cdf', x, _params(d, args[1:], code + 'cdf'), code + 'cdf')

    @bi(code + 'inv')
    def _inv(nargout, *args):
        if not args:
            raise err('MATLAB:minrhs', 'Not enough input arguments.', code + 'inv')
        p = darr(args[0]).real
        return _value(d, 'ppf', p, _params(d, args[1:], code + 'inv'), code + 'inv')

    @bi(code + 'rnd')
    def _rnd(nargout, *args):
        # the parameters come first, then the size
        np_ = min(len(args), len(d.params))
        params = _params(d, args[:np_], code + 'rnd')
        shape = _size_args(args[np_:], code + 'rnd')
        return out(draw(d, params, shape, code + 'rnd'))

    @bi(code + 'stat', nout=2)
    def _stat(nargout, *args):
        params = _common(_params(d, args, code + 'stat'), code + 'stat')
        dist, ok = d.frozen(params)
        with np.errstate(all='ignore'):
            m, v = dist.stats(moments='mv')
        m = np.where(ok, m, np.nan).astype(float)
        v = np.where(ok, v, np.nan).astype(float)
        m = out(m if m.ndim >= 2 else m.reshape(1, -1) if m.ndim == 1 else m.reshape(1, 1))
        v = out(v if v.ndim >= 2 else v.reshape(1, -1) if v.ndim == 1 else v.reshape(1, 1))
        return (m, v) if nargout > 1 else m


def _register_all():
    _names()
    for d in DISTS.values():
        if d.code:
            _register(d)


_register_all()


# ---- fitting: estimates, intervals, covariance ------------------------------------------------

def _vector(x, fn):
    a = darr(x).real.astype(float)
    if a.ndim > 2 or (a.ndim == 2 and min(a.shape) > 1):
        raise err('stats:fit:VectorRequired', 'The data must be a vector.', fn)
    a = a.reshape(-1)
    a = a[~np.isnan(a)]
    if a.size == 0:
        raise err('stats:fit:NoData', 'There are no data to fit.', fn)
    return a


def _alpha(args, i, fn):
    a = float(num(args[i])) if len(args) > i and not is_str(args[i]) and np.size(darr(args[i])) else 0.05
    if not 0 < a < 1:
        raise err('stats:fit:BadAlpha', 'ALPHA must be a scalar between 0 and 1.', fn)
    return a


def nll(d, values, x):
    """The negative log-likelihood of data under a distribution."""
    dist, ok = d.frozen([np.array(v) for v in values])
    if not np.all(ok):
        return math.inf
    with np.errstate(all='ignore'):
        lp = dist.logpmf(x) if d.discrete else dist.logpdf(x)
    s = -float(np.sum(lp))
    return s if np.isfinite(s) else math.inf


def hessian_cov(d, values, x):
    """The asymptotic covariance of the estimates: the inverse of the observed
    information (the Hessian of the negative log-likelihood, by differences)."""
    v = np.array(values, float)
    k = v.size
    h = 1e-4 * np.maximum(np.abs(v), 1e-2)
    H = np.zeros((k, k))
    f0 = nll(d, v, x)
    for i in range(k):
        for j in range(i, k):
            if i == j:
                e = np.zeros(k)
                e[i] = h[i]
                fp, fm = nll(d, v + e, x), nll(d, v - e, x)
                H[i, i] = (fp - 2 * f0 + fm) / h[i] ** 2
            else:
                ei = np.zeros(k)
                ej = np.zeros(k)
                ei[i] = h[i]
                ej[j] = h[j]
                H[i, j] = H[j, i] = (nll(d, v + ei + ej, x) - nll(d, v + ei - ej, x) - nll(d, v - ei + ej, x)
                                     + nll(d, v - ei - ej, x)) / (4 * h[i] * h[j])
    try:
        C = np.linalg.inv(H)
    except np.linalg.LinAlgError:
        C = np.full((k, k), np.nan)
    if not np.all(np.isfinite(C)):
        C = np.full((k, k), np.nan)
    return C


def wald(d, values, cov, alpha):
    """Intervals from the covariance: on the log scale for positive
    parameters, the logit scale for probabilities, as they are otherwise."""
    st = _st()
    z = st.norm.ppf(1 - alpha / 2)
    ci = np.zeros((2, len(values)))
    for i, (v, kind) in enumerate(zip(values, d.kinds)):
        se = math.sqrt(cov[i, i]) if np.isfinite(cov[i, i]) and cov[i, i] >= 0 else math.nan
        if kind == 'pos' and v > 0:
            w = z * se / v
            ci[:, i] = [v * math.exp(-w), v * math.exp(w)]
        elif kind == 'prob' and 0 < v < 1:
            lo = math.log(v / (1 - v))
            w = z * se / (v * (1 - v))
            ci[:, i] = [1 / (1 + math.exp(-(lo - w))), 1 / (1 + math.exp(-(lo + w)))]
        else:
            ci[:, i] = [v - z * se, v + z * se]
    return ci


def _normal_parts(x, alpha):
    st = _st()
    n = x.size
    mu = float(np.mean(x))
    s = float(np.std(x, ddof=1)) if n > 1 else 0.0
    if n > 1:
        t = st.t.ppf(1 - alpha / 2, n - 1)
        muci = [mu - t * s / math.sqrt(n), mu + t * s / math.sqrt(n)]
        sci = [s * math.sqrt((n - 1) / st.chi2.ppf(1 - alpha / 2, n - 1)), s * math.sqrt((n - 1) / st.chi2.ppf(alpha / 2, n - 1))]
    else:
        muci = [math.nan, math.nan]
        sci = [math.nan, math.nan]
    cov = np.array([[s * s / n, 0.0], [0.0, s * s / (2 * n)]])
    return [mu, s], np.array([muci, sci]).T, cov


def fit_dist(d, x, alpha=0.05, fn='fitdist'):
    """Estimates of the distribution's parameters from data x (a vector),
    their intervals (2 x k) and covariance. Normal and lognormal estimate
    sigma without bias, as normfit does; the rest are maximum likelihood."""
    st = _st()
    n = x.size
    name = d.name

    def need(cond, what):
        if not cond:
            raise err('stats:fit:BadData', f'The data must be {what} to fit a {name} distribution.', fn)
    if name == 'Normal':
        return _normal_parts(x, alpha)
    if name == 'Lognormal':
        need(np.all(x > 0), 'positive')
        return _normal_parts(np.log(x), alpha)
    if name == 'Exponential':
        need(np.all(x >= 0), 'nonnegative')
        mu = float(np.mean(x))
        ci = np.array([[2 * n * mu / st.chi2.ppf(1 - alpha / 2, 2 * n)], [2 * n * mu / st.chi2.ppf(alpha / 2, 2 * n)]])
        return [mu], ci, np.array([[mu * mu / n]])
    if name == 'Poisson':
        need(np.all((x >= 0) & (x == np.floor(x))), 'nonnegative whole numbers')
        lam = float(np.mean(x))
        s = float(np.sum(x))
        lo = st.chi2.ppf(alpha / 2, 2 * s) / (2 * n) if s > 0 else 0.0
        hi = st.chi2.ppf(1 - alpha / 2, 2 * s + 2) / (2 * n)
        return [lam], np.array([[lo], [hi]]), np.array([[lam / n]])
    if name == 'Rayleigh':
        need(np.all(x >= 0), 'nonnegative')
        s2 = float(np.sum(x * x))
        b = math.sqrt(s2 / (2 * n))
        ci = np.array([[math.sqrt(s2 / st.chi2.ppf(1 - alpha / 2, 2 * n))], [math.sqrt(s2 / st.chi2.ppf(alpha / 2, 2 * n))]])
        return [b], ci, np.array([[b * b / (4 * n)]])
    if name == 'Uniform':
        a, b = float(np.min(x)), float(np.max(x))
        tmp = (b - a) / alpha ** (1 / n)
        return [a, b], np.array([[b - tmp, b], [a, a + tmp]]), np.full((2, 2), np.nan)
    if name == 'Inverse Gaussian':
        need(np.all(x > 0), 'positive')
        mu = float(np.mean(x))
        lam = n / float(np.sum(1 / x - 1 / mu))
        v = [mu, lam]
        cov = np.array([[mu ** 3 / (lam * n), 0.0], [0.0, 2 * lam * lam / n]])
        return v, wald(d, v, cov, alpha), cov
    if name == 'Half Normal':
        need(np.all(x >= 0), 'nonnegative')
        s = math.sqrt(float(np.mean(x * x)))
        v = [0.0, s]
        cov = np.array([[0.0, 0.0], [0.0, s * s / (2 * n)]])
        return v, np.array([[0.0, s * math.sqrt(n / st.chi2.ppf(1 - alpha / 2, n))], [0.0, s * math.sqrt(n / st.chi2.ppf(alpha / 2, n))]]), cov
    if name == 'Negative Binomial':
        need(np.all((x >= 0) & (x == np.floor(x))), 'nonnegative whole numbers')
        m, v_ = float(np.mean(x)), float(np.var(x))
        if v_ <= m:
            raise err('stats:nbinfit:MeanExceedsVariance', 'The sample variance is not greater than the sample mean: the data '
                      'look like a Poisson sample, and the negative binomial has no maximum likelihood estimate.', fn)
        from scipy.optimize import minimize_scalar
        from scipy.special import gammaln

        def prof(lr):
            r = math.exp(lr)
            p = r / (r + m)
            return -float(np.sum(gammaln(x + r) - gammaln(r) - gammaln(x + 1) + r * math.log(p) + x * math.log(1 - p)))
        r0 = m * m / (v_ - m)
        res = minimize_scalar(prof, bracket=(math.log(r0) - 1, math.log(r0) + 1))
        r = math.exp(res.x)
        v = [r, r / (r + m)]
        cov = hessian_cov(d, v, x)
        return v, wald(d, v, cov, alpha), cov
    # maximum likelihood through scipy, with what the language fixes held
    if name == 'Gamma':
        need(np.all(x > 0), 'positive')
        a, _, b = st.gamma.fit(x, floc=0)
        v = [a, b]
    elif name == 'Beta':
        need(np.all((x > 0) & (x < 1)), 'between 0 and 1')
        a, b, _, _ = st.beta.fit(x, floc=0, fscale=1)
        v = [a, b]
    elif name == 'Weibull':
        need(np.all(x > 0), 'positive')
        c, _, s = st.weibull_min.fit(x, floc=0)
        v = [s, c]
    elif name == 'Extreme Value':
        m, s = st.gumbel_l.fit(x)
        v = [m, s]
    elif name == 'Generalized Extreme Value':
        c, m, s = st.genextreme.fit(x)
        v = [-c, s, m]
    elif name == 'Generalized Pareto':
        need(np.all(x >= 0), 'nonnegative')
        c, _, s = st.genpareto.fit(x, floc=0)
        v = [c, s, 0.0]
        cov2 = hessian_cov(_GP2, [c, s], x)
        cov = np.zeros((3, 3))
        cov[:2, :2] = cov2
        ci = np.hstack([wald(_GP2, [c, s], cov2, alpha), [[0.0], [0.0]]])
        return v, ci, cov
    elif name == 'Logistic':
        m, s = st.logistic.fit(x)
        v = [m, s]
    elif name == 'Loglogistic':
        need(np.all(x > 0), 'positive')
        c, _, s = st.fisk.fit(x, floc=0)
        v = [math.log(s), 1 / c]
    elif name == 'Nakagami':
        need(np.all(x > 0), 'positive')
        nu, _, s = st.nakagami.fit(x, floc=0)
        v = [nu, s * s]
    elif name == 'Rician':
        need(np.all(x >= 0), 'nonnegative')
        b, _, s = st.rice.fit(x, floc=0)
        v = [b * s, s]
    elif name == 'Birnbaum-Saunders':
        need(np.all(x > 0), 'positive')
        c, _, s = st.fatiguelife.fit(x, floc=0)
        v = [s, c]
    elif name == 'Burr':
        need(np.all(x > 0), 'positive')
        c, k, _, s = st.burr12.fit(x, floc=0)
        v = [s, c, k]
    elif name == 'tLocationScale':
        nu, m, s = st.t.fit(x)
        v = [m, s, nu]
    else:
        raise err('stats:fitdist:NoFit', f'A {name} distribution cannot be fitted here; makedist makes one with the parameters given.', fn)
    v = [float(a) for a in v]
    cov = hessian_cov(d, v, x)
    return v, wald(d, v, cov, alpha), cov


# the generalized Pareto with its threshold held at 0, for the covariance of the two others
def _gp2():
    st = _st()
    return Dist('Generalized Pareto (threshold 0)', None, None, ('k', 'sigma'), (None, 1.0),
                lambda k, s: st.genpareto(k, 0, s), lambda k, s: np.isfinite(k) & (s > 0), (0.0, 1.0),
                kinds=('real', 'pos'))


_GP2 = _gp2()


def _row(v):
    return out(np.array(v, float).reshape(1, -1))


def _fit_fn(code, outs):
    d = dist_of(code)

    @bi(code + 'fit', nout=outs)
    def _fit(nargout, *args):
        nargchk(args, 1, 6, code + 'fit')
        x = _vector(args[0], code + 'fit')
        alpha = _alpha(args, 1, code + 'fit')
        v, ci, cov = fit_dist(d, x, alpha, code + 'fit')
        if code == 'gp':
            v, ci = v[:2], ci[:, :2]
        if len(v) == 1:
            return (v[0], out(ci)) if nargout > 1 else v[0]
        return (_row(v), out(ci)) if nargout > 1 else _row(v)
    return _fit


for _c in ('logn', 'gam', 'beta', 'wbl', 'ev', 'gev', 'gp', 'rayl', 'nbin', 'exp', 'poiss'):
    _fit_fn(_c, 2)


def _columns(x, fn):
    a = darr(x).real.astype(float)
    if a.ndim == 2 and a.shape[0] == 1:
        a = a.reshape(-1, 1)
    if a.ndim != 2:
        raise err('stats:fit:MatrixRequired', 'The data must be a vector or a matrix.', fn)
    return a


@bi('normfit', nout=4)
def normfit(nargout, *args):
    nargchk(args, 1, 5, 'normfit')
    X = _columns(args[0], 'normfit')
    alpha = _alpha(args, 1, 'normfit')
    mus, ss, mci, sci = [], [], [], []
    for j in range(X.shape[1]):
        v, ci, _ = _normal_parts(X[:, j][~np.isnan(X[:, j])], alpha)
        mus.append(v[0])
        ss.append(v[1])
        mci.append(ci[:, 0])
        sci.append(ci[:, 1])
    res = (_row(mus), _row(ss), out(np.array(mci).T), out(np.array(sci).T))
    return res[:max(nargout, 1)] if nargout > 1 else res[0]


@bi('unifit', nout=4)
def unifit(nargout, *args):
    nargchk(args, 1, 2, 'unifit')
    X = _columns(args[0], 'unifit')
    alpha = _alpha(args, 1, 'unifit')
    a, b, aci, bci = [], [], [], []
    for j in range(X.shape[1]):
        v, ci, _ = fit_dist(DISTS['Uniform'], X[:, j][~np.isnan(X[:, j])], alpha, 'unifit')
        a.append(v[0])
        b.append(v[1])
        aci.append(ci[:, 0])
        bci.append(ci[:, 1])
    res = (_row(a), _row(b), out(np.array(aci).T), out(np.array(bci).T))
    return res[:max(nargout, 1)] if nargout > 1 else res[0]


@bi('binofit', nout=2)
def binofit(nargout, *args):
    nargchk(args, 2, 3, 'binofit')
    st = _st()
    x = darr(args[0]).real.astype(float)
    n = darr(args[1]).real.astype(float)
    alpha = _alpha(args, 2, 'binofit')
    x, n = np.broadcast_arrays(x, n)
    if np.any((x < 0) | (x > n) | (x != np.floor(x)) | (n != np.floor(n))):
        raise err('stats:binofit:InvalidX', 'X must be whole numbers between 0 and N.', 'binofit')
    with np.errstate(all='ignore'):
        p = x / n
        lo = np.where(x == 0, 0.0, st.beta.ppf(alpha / 2, x, n - x + 1))
        hi = np.where(x == n, 1.0, st.beta.ppf(1 - alpha / 2, x + 1, n - x))
    ph = out(p.astype(float))
    ci = out(np.stack([lo.reshape(-1), hi.reshape(-1)], axis=1))
    return (ph, ci) if nargout > 1 else ph


def _like_fn(code):
    d = dist_of(code)

    @bi(code + 'like', nout=2)
    def _like(nargout, *args):
        nargchk(args, 2, 4, code + 'like')
        v = darr(args[0]).real.reshape(-1).astype(float)
        if code == 'gp' and v.size == 2:
            v = np.append(v, 0.0)
        if v.size != len(d.params):
            raise err('stats:like:BadParams', f'PARAMS must have {len(d.params)} values.', code + 'like')
        x = _vector(args[1], code + 'like')
        f = nll(d, v, x)
        if nargout > 1:
            vv = v[:2] if code == 'gp' else v
            C = hessian_cov(_GP2 if code == 'gp' else d, list(vv), x)
            return f, out(C)
        return f
    return _like


for _c in ('norm', 'logn', 'exp', 'gam', 'beta', 'wbl', 'ev', 'gev', 'gp', 'nbin'):
    _like_fn(_c)


# ---- distribution objects ---------------------------------------------------------------------

class ProbDist(Obj):
    """A probability distribution object (makedist, fitdist): its distribution,
    the values of its parameters, a truncation, and the data it was fitted
    to (with the estimates' covariance and intervals)."""
    __slots__ = ('d', 'values', 'lo', 'hi', 'data', 'cov', 'ci', 'alpha')
    is_handle = False
    is_probdist = True

    def __init__(self, d, values, data=None, cov=None, ci=None):
        self.d = d
        self.values = [float(v) for v in values]
        self.lo = None
        self.hi = None
        self.data = data
        self.cov = cov
        self.ci = ci
        self.alpha = 0.05

    @property
    def cls(self):
        return f'prob.{self.d.objname}Distribution'

    def frozen(self):
        return self.d.frozen([np.array(v) for v in self.values])[0]

    # values, through the truncation if there is one
    def bounds(self):
        f = self.frozen()
        return (f.cdf(self.lo) if self.lo is not None else 0.0, f.cdf(self.hi) if self.hi is not None else 1.0)

    def pdf(self, x):
        f = self.frozen()
        with np.errstate(all='ignore'):
            v = f.pmf(x) if self.d.discrete else f.pdf(x)
            if self.lo is not None:
                a, b = self.bounds()
                lo_ok = x > self.lo if self.d.discrete else x >= self.lo
                v = np.where(lo_ok & (x <= self.hi), v / (b - a), 0.0)
        return v

    def cdf(self, x, upper=False):
        f = self.frozen()
        with np.errstate(all='ignore'):
            v = f.cdf(x)
            if self.lo is not None:
                a, b = self.bounds()
                v = np.clip((v - a) / (b - a), 0.0, 1.0)
                v = np.where(x < self.lo, 0.0, np.where(x >= self.hi, 1.0, v))
        return 1 - v if upper else v

    def icdf(self, p):
        f = self.frozen()
        with np.errstate(all='ignore'):
            if self.lo is not None:
                a, b = self.bounds()
                return np.where((p >= 0) & (p <= 1), f.ppf(a + p * (b - a)), np.nan)
            return f.ppf(p)

    def random(self, shape):
        f = self.frozen()
        if self.lo is None:
            return np.asarray(f.rvs(size=shape, random_state=_rs()), float)
        a, b = self.bounds()
        u = _rs().random_sample(shape)
        return np.asarray(f.ppf(a + u * (b - a)), float)

    def moment(self, which):
        f = self.frozen()
        if which in ('median', 'iqr'):
            q = self.icdf(np.array([0.25, 0.5, 0.75]))
            return float(q[1]) if which == 'median' else float(q[2] - q[0])
        if self.lo is None:
            m, v = f.stats(moments='mv')
            m, v = float(m), float(v)
        else:
            m = float(f.expect(lambda t: t, lb=self.lo, ub=self.hi, conditional=True))
            v = float(f.expect(lambda t: (t - m) ** 2, lb=self.lo, ub=self.hi, conditional=True))
        return {'mean': m, 'var': v, 'std': math.sqrt(v) if v >= 0 else math.nan}[which]

    def negloglik(self):
        if self.data is None:
            raise err('stats:probdists:NoData', 'The distribution was not fitted to data.', 'negloglik')
        with np.errstate(all='ignore'):
            return -float(np.sum(np.log(self.pdf(self.data))))

    def paramci(self, alpha):
        k = len(self.values)
        if self.data is None:
            return np.array([self.values, self.values], float)
        if alpha == self.alpha and self.ci is not None:
            return self.ci
        _, ci, _ = fit_dist(self.d, self.data, alpha, 'paramci')
        return ci

    # properties
    def getprop(self, name):
        if name in self.d.params:
            return self.values[self.d.params.index(name)]
        if name == 'DistributionName':
            return Char.of(self.d.objname)
        if name == 'ParameterNames':
            return Cell.of_list([Char.of(p) for p in self.d.params])
        if name == 'ParameterDescription':
            return Cell.of_list([Char.of(p) for p in self.d.desc])
        if name == 'ParameterValues':
            return out(np.array(self.values).reshape(1, -1))
        if name == 'NumParameters':
            return float(len(self.values))
        if name == 'ParameterCovariance':
            return out(self.cov if self.cov is not None else np.zeros((len(self.values),) * 2))
        if name == 'ParameterIsFixed':
            return out(np.array([self.data is None] * len(self.values)).reshape(1, -1))
        if name == 'Truncation':
            return out(np.array([[self.lo, self.hi]])) if self.lo is not None else EMPTY()
        if name == 'IsTruncated':
            return self.lo is not None
        if name == 'InputData':
            if self.data is None:
                return EMPTY()
            return Struct.scalar({'data': out(self.data.reshape(-1, 1)), 'cens': EMPTY(), 'freq': EMPTY()})
        return super().getprop(name)

    def setprop(self, name, value):
        if name in self.d.params:
            v = list(self.values)
            v[self.d.params.index(name)] = float(num(value))
            _, ok = self.d.frozen([np.array(x) for x in v])
            if not np.all(ok):
                raise err('stats:probdists:BadParameter', f'That is not a valid value of {name} for a {self.d.objname} distribution.')
            self.values = v
            self.data = self.cov = self.ci = None
            return
        super().setprop(name, value)

    def propnames(self):
        return list(self.d.params) + ['DistributionName', 'ParameterNames', 'ParameterDescription', 'ParameterValues',
                                      'NumParameters', 'ParameterCovariance', 'ParameterIsFixed', 'Truncation',
                                      'IsTruncated', 'InputData']

    def display_lines(self):
        from ..display import FMT
        lines = [f'  {self.d.objname}Distribution', '']
        head = f'  {self.d.name} distribution'
        if self.data is not None:
            head += f', fitted to {self.data.size} value{"s" if self.data.size != 1 else ""}'
        lines.append(head)
        w = max(len(p) for p in self.d.params)
        for i, p in enumerate(self.d.params):
            text = f'{self.values[i]:.6g}'
            if self.data is not None and self.ci is not None:
                text = f'{text:<10}  [{self.ci[0, i]:.6g}, {self.ci[1, i]:.6g}]'
            lines.append(f'    {p.rjust(w)} = {text}')
        if self.lo is not None:
            lines.append(f'  truncated to [{self.lo:g}, {self.hi:g}]')
        if FMT.get('spacing') == 'loose':
            lines.append('')
        return lines


class KernelDist(Obj):
    """A kernel density (fitdist(x, 'Kernel')): the data, the kernel and its bandwidth."""
    __slots__ = ('data', 'kernel', 'bw', 'lo', 'hi')
    cls = 'prob.KernelDistribution'
    is_probdist = True

    def __init__(self, data, kernel='normal', bw=None):
        self.data = np.sort(np.asarray(data, float))
        self.kernel = kernel
        self.bw = bw if bw is not None else default_bandwidth(self.data)
        self.lo = None
        self.hi = None

    def _k(self):
        return KERNELS[self.kernel]

    def pdf(self, x):
        pdf_, _ = self._k()
        x = np.asarray(x, float)
        u = (x.reshape(-1, 1) - self.data.reshape(1, -1)) / self.bw
        v = np.mean(pdf_(u), axis=1).reshape(x.shape) / self.bw
        return self._trunc_pdf(x, v)

    def _raw_cdf(self, x):
        _, cdf_ = self._k()
        x = np.asarray(x, float)
        u = (x.reshape(-1, 1) - self.data.reshape(1, -1)) / self.bw
        return np.mean(cdf_(u), axis=1).reshape(x.shape)

    def bounds(self):
        return (float(self._raw_cdf(np.array(self.lo))) if self.lo is not None else 0.0,
                float(self._raw_cdf(np.array(self.hi))) if self.hi is not None else 1.0)

    def _trunc_pdf(self, x, v):
        if self.lo is None:
            return v
        a, b = self.bounds()
        return np.where((x >= self.lo) & (x <= self.hi), v / (b - a), 0.0)

    def cdf(self, x, upper=False):
        x = np.asarray(x, float)
        v = self._raw_cdf(x)
        if self.lo is not None:
            a, b = self.bounds()
            v = np.where(x < self.lo, 0.0, np.where(x >= self.hi, 1.0, (v - a) / (b - a)))
        return 1 - v if upper else v

    def icdf(self, p):
        from scipy.optimize import brentq
        p = np.asarray(p, float)
        a, b = self.bounds()
        lo = self.data[0] - 10 * self.bw if self.lo is None else self.lo
        hi = self.data[-1] + 10 * self.bw if self.hi is None else self.hi
        outv = np.empty(p.shape)
        for i, q in np.ndenumerate(p):
            if not 0 <= q <= 1:
                outv[i] = np.nan
            elif q == 0:
                outv[i] = lo if self.lo is not None else -np.inf
            elif q == 1:
                outv[i] = hi if self.hi is not None else np.inf
            else:
                target = a + q * (b - a)
                outv[i] = brentq(lambda t: float(self._raw_cdf(np.array(t))) - target, lo, hi, xtol=1e-12)
        return outv

    def random(self, shape):
        n = int(np.prod(shape))
        if self.lo is not None:
            return self.icdf(_rs().random_sample(n)).reshape(shape)
        i = _rs().randint(0, self.data.size, n)
        return (self.data[i] + self.bw * KERNEL_DRAW[self.kernel](n)).reshape(shape)

    def moment(self, which):
        if which in ('median', 'iqr'):
            q = self.icdf(np.array([0.25, 0.5, 0.75]))
            return float(q[1]) if which == 'median' else float(q[2] - q[0])
        if self.lo is not None:
            from scipy.integrate import quad
            a, b = self.bounds()
            m = quad(lambda t: t * float(self.pdf(np.array(t))), self.lo, self.hi)[0]
            v = quad(lambda t: (t - m) ** 2 * float(self.pdf(np.array(t))), self.lo, self.hi)[0]
        else:
            m = float(np.mean(self.data))
            v = float(np.var(self.data)) + self.bw ** 2 * KERNEL_VAR[self.kernel]
        return {'mean': m, 'var': v, 'std': math.sqrt(v)}[which]

    def negloglik(self):
        with np.errstate(all='ignore'):
            return -float(np.sum(np.log(self.pdf(self.data))))

    def paramci(self, alpha):
        raise err('stats:probdists:NoParameters', 'A kernel distribution has no parameters.', 'paramci')

    def getprop(self, name):
        if name == 'Kernel':
            return Char.of(self.kernel)
        if name == 'BandWidth' or name == 'Bandwidth':
            return float(self.bw)
        if name == 'DistributionName':
            return Char.of('Kernel')
        if name == 'InputData':
            return Struct.scalar({'data': out(self.data.reshape(-1, 1)), 'cens': EMPTY(), 'freq': EMPTY()})
        if name == 'Truncation':
            return out(np.array([[self.lo, self.hi]])) if self.lo is not None else EMPTY()
        if name == 'IsTruncated':
            return self.lo is not None
        return super().getprop(name)

    def propnames(self):
        return ['Kernel', 'BandWidth', 'DistributionName', 'InputData', 'Truncation', 'IsTruncated']

    def display_lines(self):
        lines = ['  KernelDistribution', '', f'    Kernel = {self.kernel}', f'    Bandwidth = {self.bw:.6g}',
                 f'    Data: {self.data.size} values']
        if self.lo is not None:
            lines.append(f'  truncated to [{self.lo:g}, {self.hi:g}]')
        return lines


def _kernels():
    st = _st()
    return {
        'normal': (lambda u: np.exp(-0.5 * u * u) / math.sqrt(2 * math.pi), lambda u: st.norm.cdf(u)),
        'box': (lambda u: np.where(np.abs(u) <= math.sqrt(3), 1 / (2 * math.sqrt(3)), 0.0),
                lambda u: np.clip((u + math.sqrt(3)) / (2 * math.sqrt(3)), 0.0, 1.0)),
        'triangle': (lambda u: np.maximum(0.0, (1 - np.abs(u) / math.sqrt(6)) / math.sqrt(6)),
                     lambda u: _tri_cdf(u / math.sqrt(6))),
        'epanechnikov': (lambda u: np.where(np.abs(u) <= math.sqrt(5), 3 / (4 * math.sqrt(5)) * (1 - u * u / 5), 0.0),
                         lambda u: _epa_cdf(u / math.sqrt(5))),
    }


def _tri_cdf(t):
    t = np.clip(t, -1, 1)
    return np.where(t < 0, 0.5 * (1 + t) ** 2, 1 - 0.5 * (1 - t) ** 2)


def _epa_cdf(t):
    t = np.clip(t, -1, 1)
    return 0.5 + 0.75 * t - 0.25 * t ** 3


KERNELS = _kernels()
# each kernel scaled to unit variance, so that the bandwidth is its standard deviation
KERNEL_VAR = {'normal': 1.0, 'box': 1.0, 'triangle': 1.0, 'epanechnikov': 1.0}
KERNEL_DRAW = {
    'normal': lambda n: _rs().standard_normal(n),
    'box': lambda n: (2 * _rs().random_sample(n) - 1) * math.sqrt(3),
    'triangle': lambda n: (_rs().random_sample(n) - _rs().random_sample(n)) * math.sqrt(6),
    'epanechnikov': lambda n: _epa_draw(n) * math.sqrt(5),
}


def _epa_draw(n):
    u = _rs().random_sample((3, n)) * 2 - 1
    a = np.abs(u)
    return np.where((a[2] >= a[1]) & (a[2] >= a[0]), u[1], u[2])


def default_bandwidth(x):
    """The bandwidth that is best for normal data, with a robust spread: the
    median absolute deviation over 0.6745, times (4/(3n))^(1/5)."""
    x = np.asarray(x, float)
    n = x.size
    sig = float(np.median(np.abs(x - np.median(x)))) / 0.6745
    if sig <= 0:
        sig = float(np.std(x)) or 1.0
    return sig * (4 / (3 * n)) ** 0.2


def kernel_name(s, fn):
    k = s.lower()
    if k in ('gaussian', 'norm'):
        k = 'normal'
    if k == 'epan':
        k = 'epanechnikov'
    if k not in KERNELS:
        raise err('stats:ksdensity:BadKernel', f"Unknown kernel '{s}': use 'normal', 'box', 'triangle' or 'epanechnikov'.", fn)
    return k


def is_dist(v):
    return getattr(v, 'is_probdist', False)


def _nv(args, start, fn):
    """Name-value pairs from args[start:]: {lowercase name: value}."""
    out_ = {}
    i = start
    while i < len(args):
        s = opt_str(args[i])
        if s is None or i + 1 >= len(args):
            raise err('stats:NameValue', 'Options must come in name-value pairs.', fn)
        out_[s.lower()] = args[i + 1]
        i += 2
    return out_


@bi('makedist', arr=False)
def makedist(nargout, *args):
    _names()
    if not args:
        names = sorted(d.objname for d in DISTS.values() if d.objname)
        return Cell.of_list([Char.of(n) for n in names], (len(names), 1))
    name = sval(args[0], 'distribution name', 'makedist')
    d = find_dist(name, 'makedist')
    if d.objname is None:
        raise err('stats:makedist:NoObject', f'The {d.name} distribution has no object here; use the {d.code}pdf, {d.code}cdf... '
                  'functions, or pdf, cdf, icdf and random with its name.', 'makedist')
    nv = _nv(args, 1, 'makedist')
    values = list(d.mk_defaults)
    for k, v in nv.items():
        hit = [i for i, p in enumerate(d.params) if p.lower() == k]
        if not hit:
            raise err('stats:makedist:BadParameter', f"'{k}' is not a parameter of the {d.objname} distribution "
                      f"(its parameters: {', '.join(d.params)}).", 'makedist')
        values[hit[0]] = float(num(v))
    _, ok = d.frozen([np.array(v) for v in values])
    if not np.all(ok):
        raise err('stats:makedist:BadParameterValue', f'Those are not valid parameters of a {d.objname} distribution.', 'makedist')
    return ProbDist(d, values)


@bi('fitdist', nout=3, arr=False)
def fitdist(nargout, *args):
    nargchk(args, 2, 20, 'fitdist')
    name = sval(args[1], 'distribution name', 'fitdist')
    nv = _nv(args, 2, 'fitdist')
    raw = darr(args[0]).real.astype(float)
    if raw.ndim == 2 and min(raw.shape) > 1:
        raise err('stats:fitdist:VectorRequired', 'The data must be a vector.', 'fitdist')
    x = raw.reshape(-1)
    by = nv.get('by')

    def one(x):
        x = x[~np.isnan(x)]
        if _key(name) == 'kernel':
            k = kernel_name(sval(nv['kernel']), 'fitdist') if 'kernel' in nv else 'normal'
            bw = float(num(nv['bandwidth'])) if 'bandwidth' in nv else None
            return KernelDist(x, k, bw)
        d = find_dist(name, 'fitdist')
        if d.objname is None:
            raise err('stats:fitdist:NoObject', f'The {d.name} distribution has no object here.', 'fitdist')
        v, ci, cov = fit_dist(d, x, 0.05, 'fitdist')
        return ProbDist(d, v, data=x.copy(), cov=cov, ci=ci)
    if by is None:
        return one(x)
    from .statdesc import groups
    labels, idx = groups(by, x.size, 'fitdist')
    pds = Cell.of_list([one(x[idx == g]) for g in range(len(labels))])
    gn = Cell.of_list([Char.of(s) for s in labels], (len(labels), 1))
    return (pds, gn, gn)[:nargout] if nargout > 1 else pds


@bi('mle', nout=2)
def mle(nargout, *args):
    nargchk(args, 1, 20, 'mle')
    x = _vector(args[0], 'mle')
    nv = _nv(args, 1, 'mle')
    name = sval(nv['distribution'], 'distribution name', 'mle') if 'distribution' in nv else 'Normal'
    alpha = float(num(nv['alpha'])) if 'alpha' in nv else 0.05
    d = find_dist(name, 'mle')
    if d.name == 'Normal':
        n = x.size
        mu = float(np.mean(x))
        s = float(np.std(x))         # the likelihood's own estimate (over n)
        v = [mu, s]
        _, ci, _ = _normal_parts(x, alpha)
    elif d.name == 'Lognormal':
        lx = np.log(x)
        v = [float(np.mean(lx)), float(np.std(lx))]
        _, ci, _ = _normal_parts(lx, alpha)
    elif d.name in ('Binomial',):
        nt = float(num(nv['ntrials'])) if 'ntrials' in nv else None
        if nt is None:
            raise err('stats:mle:NeedNTrials', "The binomial needs 'NTrials', the number of trials.", 'mle')
        p = float(np.mean(x)) / nt
        v = [nt, p]
        st = _st()
        s, n = float(np.sum(x)), x.size * nt
        ci = np.array([[nt, st.beta.ppf(alpha / 2, s, n - s + 1) if s > 0 else 0.0],
                       [nt, st.beta.ppf(1 - alpha / 2, s + 1, n - s) if s < n else 1.0]])
    elif d.name == 'Geometric':
        m = float(np.mean(x))
        p = 1 / (1 + m)
        v = [p]
        cov = np.array([[p * p * (1 - p) / x.size]])
        ci = wald(d, v, cov, alpha)
    elif d.name == 'Discrete Uniform':
        v = [float(np.max(x))]
        ci = np.array([[v[0]], [math.floor(v[0] / alpha ** (1 / x.size))]])
    else:
        v, ci, _ = fit_dist(d, x, alpha, 'mle')
        if d.name == 'Generalized Pareto':
            v, ci = v[:2], ci[:, :2]
    ph = _row(v)
    return (ph, out(ci)) if nargout > 1 else ph


def _dist_arg(args, fn):
    """(distribution, parameters, rest) for pdf(name, x, A, B, C) and the like."""
    name = sval(args[0], 'distribution name', fn)
    return find_dist(name, fn)


def _by_name(method, nargout, args, fn):
    d = _dist_arg(args, fn)
    rest = list(args[1:])
    rest, upper = _upper(rest) if method == 'cdf' else (rest, False)
    if not rest:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', fn)
    x = darr(rest[0]).real
    params = _params(d, rest[1:1 + len(d.params)], fn)
    m = {'pdf': 'pmf' if d.discrete else 'pdf', 'cdf': 'sf' if upper else 'cdf', 'icdf': 'ppf'}[method]
    return _value(d, m, x, params, fn)


def _obj_value(pd, method, x, upper=False):
    x = np.asarray(darr(x).real, float)
    if method == 'pdf':
        r = pd.pdf(x)
    elif method == 'cdf':
        r = pd.cdf(x, upper)
    else:
        r = pd.icdf(x)
    r = np.asarray(r, float)
    return out(r if r.ndim >= 2 else r.reshape(1, 1) if r.ndim == 0 else r.reshape(1, -1))


@bi('pdf')
def pdf(nargout, *args):
    nargchk(args, 2, 6, 'pdf')
    if is_dist(args[0]):
        return _obj_value(args[0], 'pdf', args[1])
    return _by_name('pdf', nargout, args, 'pdf')


@bi('cdf')
def cdf(nargout, *args):
    nargchk(args, 2, 7, 'cdf')
    if is_dist(args[0]):
        rest, upper = _upper(args[1:])
        return _obj_value(args[0], 'cdf', rest[0], upper)
    return _by_name('cdf', nargout, args, 'cdf')


@bi('icdf')
def icdf(nargout, *args):
    nargchk(args, 2, 6, 'icdf')
    if is_dist(args[0]):
        return _obj_value(args[0], 'icdf', args[1])
    return _by_name('icdf', nargout, args, 'icdf')


@bi('random')
def random(nargout, *args):
    nargchk(args, 1, 10, 'random')
    if is_dist(args[0]):
        shape = _size_args(args[1:], 'random') or (1, 1)
        return out(np.asarray(args[0].random(shape), float))
    d = _dist_arg(args, 'random')
    rest = list(args[1:])
    k = len(d.params)
    params = _params(d, rest[:k], 'random')
    shape = _size_args(rest[k:], 'random')
    return out(draw(d, params, shape, 'random'))


def method_of(name):
    """mean(pd), median(pd), std(pd), var(pd), iqr(pd): the distribution's own."""
    def fn(pd):
        return pd.moment(name)
    return fn


@bi('truncate', arr=False)
def truncate(nargout, *args):
    nargchk(args, 3, 3, 'truncate')
    pd = args[0]
    if not is_dist(pd):
        raise err('stats:truncate:NotADistribution', 'The first argument must be a probability distribution object.', 'truncate')
    lo, hi = float(num(args[1])), float(num(args[2]))
    if not lo < hi:
        raise err('stats:truncate:BadLimits', 'The lower limit must be less than the upper one.', 'truncate')
    import copy
    t = copy.copy(pd)
    t.lo, t.hi = lo, hi
    a, b = t.bounds()
    if not b > a:
        raise err('stats:truncate:NoProbability', 'The distribution has no probability between those limits.', 'truncate')
    return t


@bi('paramci')
def paramci(nargout, *args):
    nargchk(args, 1, 3, 'paramci')
    pd = args[0]
    if not is_dist(pd):
        raise err('stats:paramci:NotADistribution', 'The first argument must be a probability distribution object.', 'paramci')
    nv = _nv(args, 1, 'paramci')
    alpha = float(num(nv['alpha'])) if 'alpha' in nv else 0.05
    return out(np.asarray(pd.paramci(alpha), float))


@bi('negloglik')
def negloglik(nargout, *args):
    nargchk(args, 1, 1, 'negloglik')
    if not is_dist(args[0]):
        raise err('stats:negloglik:NotADistribution', 'The argument must be a probability distribution object.', 'negloglik')
    return args[0].negloglik()


# ---- multivariate normal and t, sampling ---------------------------------------------------------

def _mv_args(X, mu, S, fn):
    X = darr(X).real.astype(float)
    if X.ndim == 2 and X.shape[0] == 1 and mu is not None and np.size(mu) == X.shape[1]:
        pass
    d = X.shape[1] if X.ndim == 2 else 1
    mu = np.zeros(d) if mu is None or np.size(mu) == 0 else darr(mu).real.astype(float).reshape(-1)
    if S is None or np.size(S) == 0:
        S = np.eye(d)
    else:
        S = darr(S).real.astype(float)
        if S.ndim == 2 and S.shape == (1, d) and d > 1:
            S = np.diag(S.reshape(-1))
    if mu.size != d or S.shape != (d, d):
        raise err('stats:mvn:BadSize', 'MU must have as many values, and SIGMA as many rows and columns, as X has columns.', fn)
    return X, mu, S


@bi('mvnpdf')
def mvnpdf(nargout, *args):
    nargchk(args, 1, 3, 'mvnpdf')
    st = _st()
    X, mu, S = _mv_args(args[0], args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None, 'mvnpdf')
    try:
        v = st.multivariate_normal(mu, S, allow_singular=False).pdf(X)
    except (np.linalg.LinAlgError, ValueError):
        raise err('stats:mvnpdf:BadMatrixSigma', 'SIGMA must be a symmetric, positive definite matrix.', 'mvnpdf')
    return out(np.atleast_1d(v).reshape(-1, 1))


@bi('mvncdf')
def mvncdf(nargout, *args):
    nargchk(args, 1, 3, 'mvncdf')
    st = _st()
    X, mu, S = _mv_args(args[0], args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None, 'mvncdf')
    try:
        v = st.multivariate_normal(mu, S).cdf(X)
    except (np.linalg.LinAlgError, ValueError):
        raise err('stats:mvncdf:BadMatrixSigma', 'SIGMA must be a symmetric, positive definite matrix.', 'mvncdf')
    return out(np.atleast_1d(v).reshape(-1, 1))


@bi('mvnrnd')
def mvnrnd(nargout, *args):
    nargchk(args, 2, 3, 'mvnrnd')
    mu = darr(args[0]).real.astype(float)
    S = darr(args[1]).real.astype(float)
    d = mu.shape[1] if mu.ndim == 2 else mu.size
    n = int(num(args[2])) if len(args) > 2 else (mu.shape[0] if mu.ndim == 2 else 1)
    if S.shape == (1, d) and d > 1:
        S = np.diag(S.reshape(-1))
    mu2 = np.broadcast_to(mu.reshape(-1, d), (n, d))
    try:
        L = np.linalg.cholesky(S)
    except np.linalg.LinAlgError:
        w, V = np.linalg.eigh(S)
        if np.min(w) < -1e-10 * max(1.0, np.max(np.abs(w))):
            raise err('stats:mvnrnd:BadCovariance', 'SIGMA must be a symmetric, positive semi-definite matrix.', 'mvnrnd')
        L = V * np.sqrt(np.clip(w, 0, None))
    z = _rs().standard_normal((n, d))
    return out(mu2 + z @ L.T)


@bi('mvtpdf')
def mvtpdf(nargout, *args):
    nargchk(args, 3, 3, 'mvtpdf')
    st = _st()
    X = darr(args[0]).real.astype(float)
    C = darr(args[1]).real.astype(float)
    df = float(num(args[2]))
    v = st.multivariate_t(np.zeros(C.shape[0]), C, df=df).pdf(X)
    return out(np.atleast_1d(v).reshape(-1, 1))


@bi('mvtcdf')
def mvtcdf(nargout, *args):
    nargchk(args, 3, 3, 'mvtcdf')
    st = _st()
    X = darr(args[0]).real.astype(float)
    C = darr(args[1]).real.astype(float)
    df = float(num(args[2]))
    v = st.multivariate_t(np.zeros(C.shape[0]), C, df=df).cdf(X, random_state=_rs())
    return out(np.atleast_1d(v).reshape(-1, 1))


@bi('mvtrnd')
def mvtrnd(nargout, *args):
    nargchk(args, 2, 3, 'mvtrnd')
    C = darr(args[0]).real.astype(float)
    df = float(num(args[1]))
    n = int(num(args[2])) if len(args) > 2 else 1
    d = C.shape[0]
    L = np.linalg.cholesky(C)
    z = _rs().standard_normal((n, d)) @ L.T
    w = _rs().chisquare(df, n) / df
    return out(z / np.sqrt(w).reshape(-1, 1))


@bi('randsample')
def randsample(nargout, *args):
    nargchk(args, 2, 4, 'randsample')
    pop = args[0]
    row = False
    if type(pop) in (Cell, Char):
        items = list(pop.a.reshape(-1, order='F'))
        row = pop.a.ndim == 2 and pop.a.shape[0] == 1
    else:
        pa = darr(pop)
        if pa.size == 1:
            items = np.arange(1.0, int(pa.reshape(-1)[0]) + 1)
        else:
            items = pa.reshape(-1, order='F')
            row = pa.ndim == 2 and pa.shape[0] == 1
    n = len(items)
    k = int(num(args[1]))
    replace = bool(num(args[2])) if len(args) > 2 else False
    w = darr(args[3]).real.reshape(-1).astype(float) if len(args) > 3 else None
    if w is not None:
        if w.size != n or np.any(w < 0) or not np.sum(w) > 0:
            raise err('stats:randsample:InvalidWeights', 'W must be nonnegative weights, one for each value.', 'randsample')
        w = w / np.sum(w)
    if not replace and k > n:
        raise err('stats:randsample:SampleTooLarge', 'K must be no more than the population size when sampling without replacement.', 'randsample')
    idx = _rs().choice(n, size=k, replace=replace, p=w)
    shape = (1, k) if row else (k, 1)
    if type(pop) is Cell:
        return Cell.of_list([items[i] for i in idx], shape)
    if type(pop) is Char:
        return Char.of(''.join(items[i] for i in idx)) if row else Char.rows([items[i] for i in idx])
    return out(np.asarray(items)[idx].reshape(shape))


@bi('datasample', nout=2)
def datasample(nargout, *args):
    nargchk(args, 2, 8, 'datasample')
    data = args[0]
    k = int(num(args[1]))
    rest = list(args[2:])
    dim = None
    if rest and not is_str(rest[0]):
        dim = int(num(rest.pop(0)))
    nv = _nv(rest, 0, 'datasample')
    replace = bool(num(nv['replace'])) if 'replace' in nv else True
    w = darr(nv['weights']).real.reshape(-1).astype(float) if 'weights' in nv else None
    a = darr(data)
    vec = a.ndim == 2 and 1 in a.shape
    if dim is None:
        dim = (2 if a.shape[0] == 1 else 1) if vec else 1
    n = a.shape[dim - 1]
    if w is not None:
        w = w / np.sum(w)
    if not replace and k > n:
        raise err('stats:datasample:TooManySamples', 'K must be no more than the number of values when sampling without replacement.', 'datasample')
    idx = _rs().choice(n, size=k, replace=replace, p=w)
    y = np.take(a, idx, axis=dim - 1)
    res = out(y)
    if nargout > 1:
        return res, out((idx + 1).astype(float).reshape(1, -1) if dim == 2 else (idx + 1).astype(float).reshape(-1, 1))
    return res
